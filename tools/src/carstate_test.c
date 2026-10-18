// Host harness for 3DS Files/source/carstate.c. Prints a transcript that
// tools/carstate_check.py diffs line by line against an independent model
// built from the ELF listing and the .mdebug layout.
//
// Same rules as the other harnesses: every float is a float32 printed with
// %.9g, so a one-ulp disagreement is a changed line rather than something a
// tolerance swallows. Nothing that is a pointer is ever printed.
//
// Two things this file has to be careful about, both properties of the
// object rather than of the test:
//
//   * CarState is a 1024-byte record that is *partially* written by almost
//     every function in the object. Which fields a function leaves alone is
//     as much a part of its behaviour as which it writes -- ResetCarForSound
//     exists precisely because it skips some. So the harness dirties every
//     field with a distinct recognisable value before each scenario, and
//     prints the pads and holes alongside the real fields. An unwritten
//     slot then shows its dirt instead of being invisible.
//   * The dirtying is done field by field and never with a memset over the
//     record, because the host's pointers are eight bytes where the PS2's
//     are four, so a byte pattern at absolute offsets would mean different
//     things in the harness and in the model. By field, the transcript says
//     the same thing on either. The dirty values are part of the
//     transcript's contract and the model reproduces them.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bvector.h"
#include "carstate.h"
#include "emath.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// ----------------------------------------------------------------- dirty

static uint32_t bits_of(float f)
{
    uint32_t u;
    memcpy(&u, &f, sizeof u);
    return u;
}

// A running counter turned into a distinctive float. Every dirty slot gets
// a different one, so a field copied from its neighbour is visible.
static int   g_dirt;
static float dirt(void)      { g_dirt++; return -1000.0f - (float)g_dirt; }
static int32_t dirti(void)   { g_dirt++; return -900 - g_dirt; }

static void fill_pattern(CarState *s)
{
    int i;

    g_dirt = 0;

    for (i = 0; i < 8; i++)  s->_hole8[i] = (uint8_t)(0xA0 + i);
    // DistanceMoved and the tail after it, as the twelve bytes they were.
    for (i = 0; i < 4; i++)
        ((uint8_t *)&s->DistanceMoved)[i] = (uint8_t)(0xD0 + i);
    for (i = 0; i < 8; i++)  s->_tail[i]  = (uint8_t)(0xD4 + i);

    s->pCarInfo            = 0;
    s->pTopologyCoordinate = 0;

    s->GeometryPosition.x = dirt(); s->GeometryPosition.y = dirt();
    s->GeometryPosition.z = dirt(); s->GeometryPosition.pad = dirt();
    s->Position.x = dirt(); s->Position.y = dirt();
    s->Position.z = dirt(); s->Position.pad = dirt();
    s->Velocity.x = dirt(); s->Velocity.y = dirt();
    s->Velocity.z = dirt(); s->Velocity.pad = dirt();
    s->Acceleration.x = dirt(); s->Acceleration.y = dirt();
    s->Acceleration.z = dirt(); s->Acceleration.pad = dirt();
    s->AngularVelocity.x = dirt(); s->AngularVelocity.y = dirt();
    s->AngularVelocity.z = dirt(); s->AngularVelocity.pad = dirt();
    s->AngularAcceleration.x = dirt(); s->AngularAcceleration.y = dirt();
    s->AngularAcceleration.z = dirt(); s->AngularAcceleration.pad = dirt();

    {
        float *m = (float *)&s->BodyMatrix;
        for (i = 0; i < 16; i++) m[i] = dirt();
    }
    for (i = 0; i < 4; i++) {
        float *m = (float *)&s->WheelMatrix[i];
        int j;
        for (j = 0; j < 16; j++) m[j] = dirt();
    }
    for (i = 0; i < 4; i++) {
        float *m = (float *)&s->BrakeMatrix[i];
        int j;
        for (j = 0; j < 16; j++) m[j] = dirt();
    }
    {
        float *m = (float *)&s->RelCoordMatrix;
        for (i = 0; i < 16; i++) m[i] = dirt();
    }

    for (i = 0; i < 4; i++) {
        s->WheelAngularVelocity[i]    = dirt();
        s->WheelAngle[i]              = dirt();
        s->WheelZForce[i]             = dirt();
        s->WheelRoadNoise[i]          = dirt();
        s->WheelBottomOutMagnitude[i] = dirt();
        s->WheelSuspensionHeight[i]   = dirt();
        s->WheelTractionUsage[i]      = dirt();
        s->WheelSlip[i].x             = dirt();
        s->WheelSlip[i].y             = dirt();
        s->WheelTouchingGround[i]     = (int8_t)(0x50 + i);
        s->WheelTerrain[i]            = dirti();
        s->CrossedWheelTerrain[i]     = dirti();
    }

    s->Angle         = 0xBEE1;
    s->SteeringAngle = 0xBEE2;

    s->Odometer        = dirt();
    s->TractionUsage   = dirt();
    s->SkidLeft        = dirt();
    s->SkidRight       = dirt();
    s->ForwardSpeed    = dirt();
    s->VelocityMagnitude = dirt();
    s->Throttle        = dirt();
    s->RPM             = dirt();
    s->RedLineSyncRPM  = dirt();
    s->BoostFactor     = dirt();
    s->BurnOutTime     = dirt();
    s->BurnOutTraction = dirt();
    s->BurnOutAllow    = dirt();

    s->nWheelsTouchingGround = dirti();
    s->CurrentGear           = dirti();
    s->ClutchEngaged         = dirti();
    s->DriverMode            = dirti();
    s->BurnOutState          = dirti();
    s->MatrixValid           = dirti();
}

// ---------------------------------------------------------------- output

static void pvec3(const char *tag, const bVector3 *v)
{
    printf("  %-10s %.9g %.9g %.9g pad %08lx\n", tag, v->x, v->y, v->z,
           (unsigned long)bits_of(v->pad));
}

static void pmat(const char *tag, const bMatrix4 *m)
{
    printf("  %s\n", tag);
    printf("    %.9g %.9g %.9g %.9g\n", m->v0.x, m->v0.y, m->v0.z, m->v0.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v1.x, m->v1.y, m->v1.z, m->v1.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v2.x, m->v2.y, m->v2.z, m->v2.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v3.x, m->v3.y, m->v3.z, m->v3.w);
}

// The whole record, in layout order, holes and pads included.
static void pstate(const char *tag, const CarState *s)
{
    int i;

    printf("%s\n", tag);
    printf("  hole8     ");
    for (i = 0; i < 8; i++) printf(" %02x", (unsigned)s->_hole8[i]);
    printf("\n");

    pvec3("geompos", &s->GeometryPosition);
    pvec3("position", &s->Position);
    pvec3("velocity", &s->Velocity);
    pvec3("accel", &s->Acceleration);
    pmat("bodymatrix", &s->BodyMatrix);
    pvec3("angvel", &s->AngularVelocity);
    pvec3("angaccel", &s->AngularAcceleration);

    for (i = 0; i < 4; i++) {
        char t[32];
        sprintf(t, "wheelmatrix%d", i);
        pmat(t, &s->WheelMatrix[i]);
    }
    for (i = 0; i < 4; i++) {
        char t[32];
        sprintf(t, "brakematrix%d", i);
        pmat(t, &s->BrakeMatrix[i]);
    }

    printf("  wangvel   ");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelAngularVelocity[i]);
    printf("\n  wangle    ");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelAngle[i]);
    printf("\n  wzforce   ");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelZForce[i]);
    printf("\n  wroadnoise");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelRoadNoise[i]);
    printf("\n  wbottomout");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelBottomOutMagnitude[i]);
    printf("\n  wsusp     ");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelSuspensionHeight[i]);
    printf("\n  wtouch    ");
    for (i = 0; i < 4; i++) printf(" %d", (int)s->WheelTouchingGround[i]);
    printf("\n  wterrain  ");
    for (i = 0; i < 4; i++) printf(" %ld", (long)s->WheelTerrain[i]);
    printf("\n  wcrossed  ");
    for (i = 0; i < 4; i++) printf(" %ld", (long)s->CrossedWheelTerrain[i]);
    printf("\n  wslip     ");
    for (i = 0; i < 4; i++)
        printf(" (%.9g %.9g)", s->WheelSlip[i].x, s->WheelSlip[i].y);
    printf("\n  wtraction ");
    for (i = 0; i < 4; i++) printf(" %.9g", s->WheelTractionUsage[i]);
    printf("\n");

    printf("  angle %u steer %u odo %.9g traction %.9g\n",
           (unsigned)s->Angle, (unsigned)s->SteeringAngle,
           s->Odometer, s->TractionUsage);
    printf("  skid %.9g %.9g ntouch %ld fwdspeed %.9g velmag %.9g\n",
           s->SkidLeft, s->SkidRight, (long)s->nWheelsTouchingGround,
           s->ForwardSpeed, s->VelocityMagnitude);
    printf("  gear %ld throttle %.9g rpm %.9g redline %.9g clutch %ld\n",
           (long)s->CurrentGear, s->Throttle, s->RPM, s->RedLineSyncRPM,
           (long)s->ClutchEngaged);
    printf("  drivermode %ld boost %.9g burnout %ld %.9g %.9g %.9g\n",
           (long)s->DriverMode, s->BoostFactor, (long)s->BurnOutState,
           s->BurnOutTime, s->BurnOutTraction, s->BurnOutAllow);
    pmat("relcoord", &s->RelCoordMatrix);
    printf("  matrixvalid %ld\n", (long)s->MatrixValid);
    printf("  tail      ");
    for (i = 0; i < 4; i++)
        printf(" %02x", (unsigned)((const uint8_t *)&s->DistanceMoved)[i]);
    for (i = 0; i < 8; i++)  printf(" %02x", (unsigned)s->_tail[i]);
    printf("\n");
}

// A short form, for scenarios where only a few fields move.
static void pshort(const char *tag, const CarState *s)
{
    int i;
    printf("%s ntouch %ld touch", tag, (long)s->nWheelsTouchingGround);
    for (i = 0; i < 4; i++) printf(" %d", (int)s->WheelTouchingGround[i]);
    printf(" terr");
    for (i = 0; i < 4; i++) printf(" %ld", (long)s->WheelTerrain[i]);
    printf(" crossed");
    for (i = 0; i < 4; i++) printf(" %ld", (long)s->CrossedWheelTerrain[i]);
    printf("\n");
}

// --------------------------------------------------------------- the info

// A CarTypeInfo prefix with distinct, awkward numbers in every slot CarState
// reads, so that a wheel picked up from the wrong index or a centre of
// gravity read from the wrong offset cannot coincide with the right answer.
static CarTypeInfoPrefix g_info;

static void make_info(void)
{
    static const float px[4] = { 1.25f, -1.25f,  1.5f, -1.5f };
    static const float py[4] = { 2.75f,  2.75f, -2.25f, -2.25f };
    static const float pz[4] = { 0.375f, 0.4375f, 0.5f, 0.5625f };
    static const float rad[4] = { 0.3f, 0.31f, 0.32f, 0.33f };
    static const float oy[4] = { -0.01f, 0.03f, 0.07f, -0.05f };
    int i;

    memset(&g_info, 0, sizeof g_info);

    g_info.CenterOfGravity.x   = 0.125f;
    g_info.CenterOfGravity.y   = -0.0625f;
    g_info.CenterOfGravity.z   = 0.75f;
    g_info.CenterOfGravity.pad = 0.0f;

    for (i = 0; i < 4; i++) {
        g_info.Wheels[i].PositionX  = px[i];
        g_info.Wheels[i].PositionY  = py[i];
        g_info.Wheels[i].PositionZ  = pz[i];
        g_info.Wheels[i].Radius     = rad[i];
        g_info.Wheels[i].Width      = 0.2f;
        g_info.Wheels[i].WheelNumber = i;
        g_info.Wheels[i].OffsetY    = oy[i];
    }
}

static CarState g_state;

// ------------------------------------------------------------- scenarios

// The constructor, over a patterned record: which of the 1024 bytes it
// actually writes, and which it leaves to ResetCar.
static void scenario_init(void)
{
    printf("== init ==\n");
    fill_pattern(&g_state);
    carstate_init(&g_state, 0, &g_info);
    pstate("after ctor", &g_state);
}

// ResetCar on its own, from a dirty record rather than a fresh one.
static void scenario_reset(void)
{
    printf("== reset ==\n");
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    g_state.pTopologyCoordinate = 0;
    carstate_reset_car(&g_state);
    pstate("after reset", &g_state);
}

// ResetCarForSound is defined as much by what it skips as by what it sets,
// so this runs it over a record that has been reset and then deliberately
// dirtied in every field it is supposed to leave alone.
static void scenario_reset_for_sound(void)
{
    int i;

    printf("== reset for sound ==\n");
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    g_state.pTopologyCoordinate = 0;
    carstate_reset_car(&g_state);

    // Things it must keep.
    for (i = 0; i < 4; i++)
        g_state.WheelRoadNoise[i] = 0.5f + (float)i;
    g_state.CurrentGear     = 4;
    g_state.ClutchEngaged   = 0;
    g_state.BoostFactor     = 2.5f;
    g_state.BurnOutState    = 3;
    g_state.BurnOutTime     = 1.5f;
    g_state.BurnOutTraction = 0.25f;
    g_state.Throttle        = 0.75f;
    g_state.ForwardSpeed    = 40.0f;
    g_state.RPM             = 6500.0f;
    g_state.RedLineSyncRPM  = 7000.0f;
    g_state.Odometer        = 123.5f;
    g_state.Angle           = 1000;
    g_state.SteeringAngle   = 2000;
    g_state.MatrixValid     = 1;
    g_state.Position.x      = 10.0f;

    // Things it must clear.
    for (i = 0; i < 4; i++) {
        g_state.WheelAngularVelocity[i] = 9.0f + (float)i;
        g_state.WheelZForce[i]          = 3.0f;
        g_state.WheelTouchingGround[i]  = 0;
        g_state.WheelTerrain[i]         = 7;
        g_state.CrossedWheelTerrain[i]  = 9;
    }
    g_state.nWheelsTouchingGround = 0;
    g_state.SkidLeft  = 4.0f;
    g_state.SkidRight = 5.0f;

    carstate_reset_car_for_sound(&g_state);
    pstate("after reset for sound", &g_state);
}

// BeginTimestep, and the interaction with SetWheelTerrain that gives
// CrossedWheelTerrain its meaning.
static void scenario_terrain(void)
{
    printf("== terrain ==\n");
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    pshort("  reset       ", &g_state);

    carstate_set_wheel_terrain(&g_state, 0, 5);
    carstate_set_wheel_terrain(&g_state, 1, 3);
    pshort("  set 0=5 1=3 ", &g_state);

    // Lower than what has been crossed: WheelTerrain drops, Crossed holds.
    carstate_set_wheel_terrain(&g_state, 0, 2);
    pshort("  set 0=2     ", &g_state);

    // Equal, which the `<` does not take.
    carstate_set_wheel_terrain(&g_state, 1, 3);
    pshort("  set 1=3     ", &g_state);

    // Negative, below the reset value of 1.
    carstate_set_wheel_terrain(&g_state, 2, -4);
    pshort("  set 2=-4    ", &g_state);

    carstate_begin_timestep(&g_state);
    pshort("  begin       ", &g_state);

    carstate_set_wheel_terrain(&g_state, 3, 8);
    pshort("  set 3=8     ", &g_state);
}

// Every transition of SetWheelTouchingGround, and the fact that a repeat
// does not move the count.
static void scenario_touching(void)
{
    int i;
    static const int   wheel[] = { 0, 0, 1, 1, 1, 2, 3, 3, 0, 2 };
    static const int8_t val[]  = { 0, 0, 0, 1, 1, 0, 0, 1, 1, 1 };

    printf("== touching ==\n");
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    pshort("  reset       ", &g_state);

    for (i = 0; i < (int)(sizeof val / sizeof val[0]); i++) {
        char t[64];
        carstate_set_wheel_touching_ground(&g_state, wheel[i], val[i]);
        sprintf(t, "  w%d=%d        ", wheel[i], (int)val[i]);
        pshort(t, &g_state);
    }

    // A non-zero that is not 1: the count is driven by zero/non-zero, not
    // by the value.
    carstate_set_wheel_touching_ground(&g_state, 1, 0);
    pshort("  w1=0        ", &g_state);
    carstate_set_wheel_touching_ground(&g_state, 1, 42);
    pshort("  w1=42       ", &g_state);
    carstate_set_wheel_touching_ground(&g_state, 1, -1);
    pshort("  w1=-1       ", &g_state);
}

// GetYaw and GetYawAlways: the 5.0 speed gate, the BAM subtraction, the
// wrap at the image's pi, and a heading that is exactly opposite.
static void scenario_yaw(void)
{
    static const float  vx[]    = { 1.0f, 0.0f, -1.0f, -1.0f, 0.5f, 3.0f, 0.0f };
    static const float  vy[]    = { 0.0f, 1.0f,  0.0f, -1.0f, 0.25f, -4.0f, 0.0f };
    static const uint16_t ang[] = { 0, 16384, 32768, 49152, 1000, 60000, 12345 };
    static const float  spd[]   = { 10.0f, 4.99999f, 5.0f, -20.0f, 0.0f, 100.0f, 5.0f };
    int i, j;

    printf("== yaw ==\n");
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);

    for (i = 0; i < (int)(sizeof vx / sizeof vx[0]); i++) {
        g_state.Velocity.x = vx[i];
        g_state.Velocity.y = vy[i];
        for (j = 0; j < (int)(sizeof ang / sizeof ang[0]); j++) {
            g_state.Angle       = ang[j];
            g_state.ForwardSpeed = spd[i];
            printf("  v %.9g %.9g ang %u spd %.9g -> yaw %.9g always %.9g\n",
                   vx[i], vy[i], (unsigned)ang[j], spd[i],
                   carstate_get_yaw(&g_state),
                   carstate_get_yaw_always(&g_state));
        }
    }
}

// GetTransformMatrix: both branches, the cache, and the reverse flip. The
// squared-length threshold is 1.0, so the velocities here sit either side
// of it on purpose.
static void scenario_transform(void)
{
    /* Case 6 is the one where z decides: x*x + y*y is 0.5 and does not
       clear the threshold, but with z*z it is 1.5 and does, so the basis
       comes from the velocity rather than from Angle. */
    static const float vx[]  = { 3.0f, 0.5f, 0.0f,  -2.0f, 0.7f,  0.6f, 0.5f };
    static const float vy[]  = { 4.0f, 0.5f, 0.0f,   0.0f, 0.7f,  0.8f, 0.5f };
    static const float vz[]  = { 0.0f, 0.0f, 0.0f,   1.0f, 0.0f,  0.0f, 1.0f };
    static const float spd[] = { 20.0f, 1.0f, 0.0f, -20.0f, 1.0f, -1.0f, 9.0f };
    static const uint16_t ang[] = { 0, 8192, 16384, 40000, 22222, 65535, 3000 };
    int i;

    printf("== transform ==\n");

    for (i = 0; i < (int)(sizeof vx / sizeof vx[0]); i++) {
        fill_pattern(&g_state);
        g_state.pCarInfo = &g_info;
        carstate_reset_car(&g_state);

        g_state.Velocity.x  = vx[i];
        g_state.Velocity.y  = vy[i];
        g_state.Velocity.z  = vz[i];
        g_state.Velocity.pad = 0.0f;
        g_state.ForwardSpeed = spd[i];
        g_state.Angle        = ang[i];

        carstate_get_transform_matrix(&g_state);
        printf("  case %d v %.9g %.9g %.9g spd %.9g ang %u\n",
               i, vx[i], vy[i], vz[i], spd[i], (unsigned)ang[i]);
        pmat("    matrix", &g_state.RelCoordMatrix);
        printf("    valid %ld\n", (long)g_state.MatrixValid);

        // Second call must not recompute: change the inputs underneath it
        // and show the cached matrix survives.
        g_state.Velocity.x = 999.0f;
        g_state.Angle      = 111;
        carstate_get_transform_matrix(&g_state);
        pmat("    cached", &g_state.RelCoordMatrix);

        // Clearing the bit is the simulation's job; do it by hand and the
        // new inputs take effect.
        g_state.MatrixValid = 0;
        carstate_get_transform_matrix(&g_state);
        pmat("    rebuilt", &g_state.RelCoordMatrix);
    }

    // The velocity pad takes part in the negate even though it cannot reach
    // the result. Shown rather than asserted.
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    g_state.Velocity.x   = 2.0f;
    g_state.Velocity.y   = 1.0f;
    g_state.Velocity.z   = 0.0f;
    g_state.Velocity.pad = 7.0f;
    g_state.ForwardSpeed = -3.0f;
    carstate_get_transform_matrix(&g_state);
    pmat("  pad participates", &g_state.RelCoordMatrix);
}

// The four transforms, forward and back.
static void scenario_spaces(void)
{
    static const float px[] = { 0.0f, 10.0f, -5.5f };
    static const float py[] = { 0.0f, -3.0f,  8.25f };
    static const float qx[] = { 1.0f, 0.0f, -2.5f, 100.0f };
    static const float qy[] = { 0.0f, 1.0f,  3.5f, -50.0f };
    int i, j;

    printf("== spaces ==\n");

    for (i = 0; i < 3; i++) {
        fill_pattern(&g_state);
        g_state.pCarInfo = &g_info;
        carstate_reset_car(&g_state);
        g_state.Position.x   = px[i];
        g_state.Position.y   = py[i];
        g_state.Position.z   = 1.5f;
        g_state.Position.pad = 0.0f;
        g_state.Velocity.x   = 3.0f;
        g_state.Velocity.y   = 4.0f;
        g_state.Velocity.z   = 0.0f;
        g_state.Velocity.pad = 0.0f;
        g_state.ForwardSpeed = 25.0f;
        g_state.Angle        = 9000;

        printf("  pos %.9g %.9g\n", px[i], py[i]);

        for (j = 0; j < 4; j++) {
            bVector2 in, w2c, c2w, c2wu;
            bVector3 in3, w2c3;

            in.x = qx[j];
            in.y = qy[j];

            carstate_world_to_car2(&g_state, &w2c, &in);
            carstate_car_to_world(&g_state, &c2w, &in);
            carstate_car_to_world_unadjusted(&g_state, &c2wu, &in);

            in3.x = qx[j];
            in3.y = qy[j];
            in3.z = 2.25f;
            in3.pad = 0.0f;
            carstate_world_to_car3(&g_state, &w2c3, &in3);

            printf("    q %.9g %.9g w2c %.9g %.9g c2w %.9g %.9g"
                   " c2wu %.9g %.9g\n",
                   qx[j], qy[j], w2c.x, w2c.y, c2w.x, c2w.y, c2wu.x, c2wu.y);
            printf("      w2c3 %.9g %.9g %.9g pad %08lx\n",
                   w2c3.x, w2c3.y, w2c3.z,
                   (unsigned long)bits_of(w2c3.pad));
        }
    }

    // The 3D overload subtracts the pad too; a non-zero pair shows it.
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    g_state.Position.x = 1.0f; g_state.Position.y = 2.0f;
    g_state.Position.z = 3.0f; g_state.Position.pad = 4.0f;
    g_state.ForwardSpeed = 0.0f;
    g_state.Angle = 0;
    {
        bVector3 in3, out3;
        in3.x = 5.0f; in3.y = 6.0f; in3.z = 7.0f; in3.pad = 11.0f;
        carstate_world_to_car3(&g_state, &out3, &in3);
        printf("  pad subtract -> %.9g %.9g %.9g pad %08lx\n",
               out3.x, out3.y, out3.z, (unsigned long)bits_of(out3.pad));
    }
}

// The wheel matrices, over angles that exercise the truncation and the
// steering split between the front pair and the back.
static void scenario_wheels(void)
{
    static const float wangle[4] = { 0.0f, 1.5f, -2.25f, 1000.0f };
    static const float susp[4]   = { 0.0f, 0.125f, -0.0625f, 1.5f };
    static const uint16_t steer[] = { 0, 4096, 32768, 65535 };
    int k, i;

    printf("== wheels ==\n");

    for (k = 0; k < (int)(sizeof steer / sizeof steer[0]); k++) {
        fill_pattern(&g_state);
        g_state.pCarInfo = &g_info;
        carstate_reset_car(&g_state);

        for (i = 0; i < 4; i++) {
            g_state.WheelAngle[i]            = wangle[i];
            g_state.WheelSuspensionHeight[i] = susp[i];
        }
        g_state.SteeringAngle = steer[k];

        carstate_calculate_wheel_matrices(&g_state);

        printf("  steer %u\n", (unsigned)steer[k]);
        for (i = 0; i < 4; i++) {
            char t[40];
            sprintf(t, "    wheel%d", i);
            pmat(t, &g_state.WheelMatrix[i]);
            sprintf(t, "    brake%d", i);
            pmat(t, &g_state.BrakeMatrix[i]);
        }
    }

    // The one-wheel form on its own, so that a mutation which rebuilds all
    // four when asked for one shows up.
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    for (i = 0; i < 4; i++) {
        g_state.WheelAngle[i]            = 0.5f * (float)(i + 1);
        g_state.WheelSuspensionHeight[i] = 0.25f * (float)i;
    }
    g_state.SteeringAngle = 8192;
    carstate_calculate_wheel_matrices_one(&g_state, 2);
    printf("  single wheel 2\n");
    for (i = 0; i < 4; i++) {
        char t[40];
        sprintf(t, "    wheel%d", i);
        pmat(t, &g_state.WheelMatrix[i]);
    }
}

// GeometryPosition, over a body matrix that is not the identity.
static void scenario_geometry(void)
{
    static const uint16_t yaw[] = { 0, 8192, 30000, 65535 };
    int k;

    printf("== geometry ==\n");

    for (k = 0; k < (int)(sizeof yaw / sizeof yaw[0]); k++) {
        fill_pattern(&g_state);
        g_state.pCarInfo = &g_info;
        carstate_reset_car(&g_state);

        g_state.Position.x   = 12.5f;
        g_state.Position.y   = -7.25f;
        g_state.Position.z   = 3.0f;
        g_state.Position.pad = 0.0f;

        eIdentity(&g_state.BodyMatrix);
        eRotateZ(&g_state.BodyMatrix, &g_state.BodyMatrix, yaw[k]);

        carstate_calculate_geometry_position(&g_state);

        printf("  yaw %u\n", (unsigned)yaw[k]);
        pvec3("    geompos", &g_state.GeometryPosition);
    }

    // A body matrix with a translation in row 3: bMulMatrixVec3 is the
    // three-component multiply, so row 3 must not reach the result.
    fill_pattern(&g_state);
    g_state.pCarInfo = &g_info;
    carstate_reset_car(&g_state);
    g_state.Position.x = 0.0f; g_state.Position.y = 0.0f;
    g_state.Position.z = 0.0f; g_state.Position.pad = 0.0f;
    eIdentity(&g_state.BodyMatrix);
    g_state.BodyMatrix.v3.x = 100.0f;
    g_state.BodyMatrix.v3.y = 200.0f;
    g_state.BodyMatrix.v3.z = 300.0f;
    carstate_calculate_geometry_position(&g_state);
    pvec3("  translated", &g_state.GeometryPosition);
}

int main(void)
{
    // The PS2-equivalent size, with the host's wider pointers taken back
    // out, so this line says 1024 on a 32-bit target and on this one.
    printf("sizes state %lu wheelinfo %lu infoprefix %lu\n",
           (unsigned long)(sizeof(CarState) - CARSTATE_SLACK),
           (unsigned long)sizeof(WheelInfo),
           (unsigned long)sizeof(CarTypeInfoPrefix));

    make_info();

    scenario_init();
    scenario_reset();
    scenario_reset_for_sound();
    scenario_terrain();
    scenario_touching();
    scenario_yaw();
    scenario_transform();
    scenario_spaces();
    scenario_wheels();
    scenario_geometry();

    carstate_print_state(&g_state);
    printf("printstate returned\n");
    return 0;
}
