// physicscar -- see physicscar.h.

#include "physicscar.h"

#include <math.h>
#include <stdlib.h>

#include "bmath.h"
#include "bmem.h"
#include "bmatrix.h"
#include "bticker.h"
#include "cardamage.h"
#include "eefpu.h"
#include "emath.h"
#include "joystick.h"
#include "physcomp.h"
#include "race.h"
#include "realdriver.h"
#include "replay.h"
#include "vtable.h"

// ------------------------------------------------------------ the tuning

PhysicsCarResetFn gPhysicsCarPleaseResetMeLaterFn;

int32_t UseNewSuspensionCalibration = 1;       // 0x003230b4  00000001
int32_t TriggerBounce               = 0;       // 0x003230b8
float   LowSpeedYawBoost            = 0.0f;    // 0x003230c0
float   HighSpeedYawBoost           = 1.0f;    // 0x003230c4  3f800000
float   LowSpeedSpeed               = 0.0f;    // 0x003230c8
float   HighSpeedSpeed              = 30.0f;   // 0x003230cc  41f00000
float   MaxYawBonus                 = 0.7f;    // 0x003230d0  3f333333
float   YawLockThreshold;                      // 0x003230e0  the initialiser's
int32_t UseMagicForce               = 0;       // 0x00323114
int32_t PhysicsCarResolveCounter;              // 0x00323118  counter.3921
float   SkidNormalize               = 6.0f;    // 0x0032311c  40c00000
Graph   JumpStabilization;                     // 0x00323120  the initialiser's
float   ResolveTime;                           // 0x00323128
float   IterateTime;                           // 0x0032312c

int32_t RigidBodyDebugInfo          = 0;       // 0x003230ac
int32_t DriveTrainDebugInfo         = 0;       // 0x003230b0
float   NFSAdjust                   = 0.85f;   // 0x003230d4  3f59999a
float   MaximumTimeStep             = 0.0044f; // 0x003230d8  3b902de0
float   BurnOutTorqueValue          = 1.5f;    // 0x003230e4  3fc00000
float   BurnOutTorqueValueClip      = 3.0f;    // 0x003230e8  40400000
float   BurnOutCancelTorqueValue    = 1.0f;    // 0x003230ec  3f800000
float   BurnOutMaxSpeed             = 15.0f;   // 0x003230f0  41700000
float   BurnOutTractionValue        = 0.4f;    // 0x003230f4  3ecccccd
float   BurnOutMinTime              = 1.0f;    // 0x003230f8  3f800000
float   BurnOutAllowTime            = 0.166666672f; // 0x003230fc  3e2aaaab
float   BurnOutYawMax               = 0x1.921fap-3f; // 0x00323100  3e490fd0
float   BurnOutYawCancel            = 0.3f;    // 0x00323104  3e99999a
int32_t SpeedDebugInfo              = 0;       // 0x00323108

float   SpeedDebugStartTime;                   // 0x00323134
float   SpeedDebugDisplayTime60;               // 0x00323138
float   SpeedDebugDisplayTime100;              // 0x0032313c
float   SpeedDebugDisplayTimeQM;               // 0x00323140
float   SpeedDebug060Time;                     // 0x00323144
float   SpeedDebug0100Time;                    // 0x00323148
float   SpeedDebugQMTime;                      // 0x0032314c
float   SpeedDebugQMMeasure;                   // 0x00323150
float   SpeedDebugQMSpeed;                     // 0x00323154

float    BrakeSettings[4]  = { 1.0f, 1.0f, 0.6f, 0.6f };   // 0x002e8550
float    EBrakeSettings[4] = { 0.0f, 0.0f, 1.0f, 1.0f };   // 0x002e8560
bVector4 SpeedDebugX;                                       // 0x002e8570
bMatrix4 SpeedDebugR;                                       // 0x002e8580

// 0x002e85c0, 24 bytes of .bss that the initialiser fills. The Graph
// aliases it, so it lives as long as the Graph does.
static bVector2 JumpStabilizationGraph[3];

// The .lit4 constants, by gp offset.
#define PC_GRAVITY            9.8f                // gp-31888  411ccccd
#define PC_DAMP_THROTTLE      0.3f                // gp-31884  3e99999a
#define PC_DAMP_SPEED         0.7f                // gp-31880  3f333333
#define PC_DAMP_FACTOR        0.95f               // gp-31876  3f733333
#define PC_YAW_LOCK_ANGLE     0.349065899848938f  // gp-31872  3eb2b8c4, 20 degrees
#define PC_RPM_TO_RADS        0.10471967607736588f // gp-31784 3dd67745, pi/30
#define PC_RADS_TO_RPM        9.549304008483887f  // gp-31780  4118c9f3, 30/pi
#define PC_JUMP_KNEE          0.4f                // gp-31776  3ecccccd
#define PC_YAW_LOCK_THRESHOLD 0.0872664749622345f // gp-31772  3db2b8c4, 5 degrees

// Move's, gp-31868 .. gp-31788. The tick is there seven times over and
// the mph factor twice.
#define PC_TICK               0.00025f            // gp-31868  3983126f
#define PC_MOVE_DAMP_THROTTLE 0.3f                // gp-31864  3e99999a
#define PC_MOVE_DAMP_TILT     0.15f               // gp-31860  3e19999a
#define PC_MS_TO_MPH          2.237f              // gp-31856  400f2b02
#define PC_EBRAKE_KNEE        0.2f                // gp-31852, gp-31844  3e4ccccd
#define PC_EBRAKE_YAW         0.3f                // gp-31840  3e99999a
#define PC_EXTREME_YAW        0.1f                // gp-31832  3dcccccd
#define PC_DAMAGE_DERATE      0.03f               // gp-31828  3cf5c28f
#define PC_DYNO_STOPPED       0.8f                // gp-31812  3f4ccccd
#define PC_DYNO_QUARTER_MILE  400.5f              // gp-31796  43c84000

// Retail's BottomOut (0x00137938): a car whose up axis has under 0.1 of z
// is on its roof or side, and one moving faster than 0.8 is not resting
// there. The second is retail's gp-31780 and gp-31772, the first gp-31768.
#define PC_FLIP_SPEED         0.8f                // retail gp-31780  3f4ccccd
#define PC_FLIP_UP            0.1f                // retail gp-31768  3dcccccd

// Retail's Move (0x00137d90): the rear brakes with both pedals down (the
// throttle past 0.8, the brake held 0.05 a mph), and the lurch's random
// part of 0.15 s after 0.4. The demo's NFS handbrake extra of 0.7
// (gp-31848) and blown-tyre traction of 0.4 (gp-31836) are gone.
#define PC_LAUNCH_THROTTLE    0.8f                // retail gp-31740  3f4ccccd
#define PC_LAUNCH_BRAKE       0.05f               // retail gp-31736  3d4ccccd
#define PC_LURCH_RANDOM       0.15f               // retail gp-31708  3e19999a
#define PC_LURCH_MIN          0.4f                // retail gp-31704  3ecccccd

void physicscar_static_init(void)
{
    JumpStabilizationGraph[0].x = 0.0f;
    JumpStabilizationGraph[0].y = 0.0f;
    JumpStabilizationGraph[1].x = PC_JUMP_KNEE;
    JumpStabilizationGraph[1].y = 0.0f;
    YawLockThreshold = PC_YAW_LOCK_THRESHOLD;
    JumpStabilizationGraph[2].y = 20.0f;
    JumpStabilizationGraph[2].x = 2.0f;
    graph_init(&JumpStabilization, JumpStabilizationGraph, 3);
}

// -------------------------------------------------------------- CarMover

void carmover_set_driver(CarMover *m, CarDriver *d)
{
    m->Driver = d;
}

void carmover_init(CarMover *m)
{
    m->_vtable = CARMOVER_VTABLE;
}

void carmover_destroy(CarMover *m, int32_t flags)
{
    m->_vtable = CARMOVER_VTABLE;

    // `j __builtin_delete`, which is bFree on the general heap.
    if (flags & 1)
        bFree(m);
}

void carmover_do_snapshot(CarMover *m, void *snap)
{
    (void)m;
    (void)snap;
}

// ------------------------------------------------------------- the replay

// 0x00137450.
void physicscar_do_snapshot(PhysicsCar *pc, ReplaySnapshot *s)
{
    const VtEntry *e;
    int32_t i;

    ReplaySnapshot_BeginNamedSection(s, "PhysicsCar");
    ReplaySnapshot_MoveFloat(s, &pc->FrictionBoost);
    rigidbody_do_snapshot(pc->pBody, s);
    e = vt_slot(pc->pSteering->_vtable, STEERING_VT_DO_SNAPSHOT);
    ((SteeringDoSnapshotFn)e->fn)(vt_this(pc->pSteering, e), s);
    for (i = 0; i < 4; i++) {
        wheel_do_snapshot(pc->pWheel[i], s);
        suspension_do_snapshot(pc->pSuspension[i], s);
    }
    engine_do_snapshot(pc->pEngine, s);
    drivetrain_do_snapshot(pc->pDriveTrain, s);
    aerodynamics_do_snapshot(pc->pAerodynamics, s);
    carmover_do_snapshot(&pc->Mover, s);
    ReplaySnapshot_MoveFloat(s, &pc->YawControlMultiplier);
    ReplaySnapshot_MoveTimer(s, (int32_t *)&pc->BrakeStandTimer.PackedTime);
    ReplaySnapshot_MoveTimer(s,
                             (int32_t *)&pc->BrakeStandTimerStart.PackedTime);
    ReplaySnapshot_MoveBool(s, &pc->BrakeStanding, 1);
    ReplaySnapshot_MoveBool(s, &pc->ThrottleReleased, 1);
    ReplaySnapshot_MoveInt(s, &pc->LurchsLeft, 4);
    ReplaySnapshot_MoveTimer(s, (int32_t *)&pc->FlippedTimer.PackedTime);
    ReplaySnapshot_EndNamedSection(s);
}

// -------------------------------------------------------- the lifecycle

PhysicsCar *physicscar_init(PhysicsCar *pc, const CarTypeInfo *cti,
                            CarDriver *driver, Car *car)
{
    int32_t i;

    // CarMover's constructor is inlined: the vptr goes in the delay slot of
    // the call to PhysicsSystem's, and the driver is left for below.
    pc->Mover._vtable = CARMOVER_VTABLE;
    physicssystem_init(&pc->Vehicle);
    pc->Vehicle._vtable = PHYSICSVEHICLE_VTABLE;

    pc->Mover.Driver          = driver;
    pc->BrakeStandTimer.PackedTime      = 0;
    pc->BrakeStandTimerStart.PackedTime = 0;
    pc->FlippedTimer.PackedTime         = 0;
    pc->CTI                   = cti;
    pc->pCar                  = car;
    pc->Vehicle._vtable       = PHYSICSCAR_VEHICLE_VTABLE;
    pc->Mover._vtable         = PHYSICSCAR_VTABLE;
    pc->State                 = &car->State;
    pc->FrictionBoost         = 1.0f;

    pc->pBody = rigidbody_init(rigidbody_new(), &pc->CTI->Body);
    physicssystem_add_component(&pc->Vehicle, (PhysicsComponent *)pc->pBody);
    // HighPerformance from the argument, SpeedLimiter through the field.
    pc->pBody->IsHP         = (cti->HighPerformance != 0);
    pc->pBody->SpeedLimiter = pc->CTI->Control.SpeedLimiter;

    // TwoWheelAckermanSteering's constructor, inlined.
    pc->pSteering = &ackerman_init(ackerman_new(), pc->CTI)->base;

    for (i = 0; i < 4; i++) {
        Wheel *w;
        Suspension *s;

        w = wheel_new();
        pc->pWheel[i] = wheel_init(w, &pc->CTI->Wheels[i],
                                   &pc->CTI->Tires[i / 2],
                                   &pc->CTI->Control, pc->State);
        s = suspension_new();
        pc->pSuspension[i] = suspension_init(s, i, pc->pBody, pc->pWheel[i],
                                             (i < 2) ? pc->pSteering : NULL,
                                             &pc->CTI->Suspension[i / 2]);
        physicssystem_add_component(&pc->Vehicle,
                                    (PhysicsComponent *)pc->pWheel[i]);
        physicssystem_add_component(&pc->Vehicle,
                                    (PhysicsComponent *)pc->pSuspension[i]);
    }

    pc->pSuspension[0]->pSwayBar = pc->pSuspension[1];
    pc->pSuspension[1]->pSwayBar = pc->pSuspension[0];
    pc->pSuspension[2]->pSwayBar = pc->pSuspension[3];
    pc->pSuspension[3]->pSwayBar = pc->pSuspension[2];

    pc->pEngine = engine_new();
    engine_init(pc->pEngine, &pc->CTI->Engine, pc->State);
    physicssystem_add_component(&pc->Vehicle,
                                (PhysicsComponent *)pc->pEngine);
    pc->pEngine->IsHP = (cti->HighPerformance != 0);

    pc->pDriveTrain = drivetrain_new();
    drivetrain_init(pc->pDriveTrain, &pc->CTI->DriveTrain, pc->pEngine,
                    pc->pWheel, pc->State);
    physicssystem_add_component(&pc->Vehicle,
                                (PhysicsComponent *)pc->pDriveTrain);

    // Aerodynamics' constructor, inlined; it is not a component.
    pc->pAerodynamics = aerodynamics_new();
    aerodynamics_init(pc->pAerodynamics, pc->pBody, &pc->CTI->Aero);

    physicscar_calibrate(pc);
    physicscar_initialize_state_from_car(pc);
    physicscar_compute_auxiliaries(pc);

    pc->YawControlMultiplier = 1.0f;
    pc->ThrottleReleased     = 1;
    pc->LurchsLeft           = 2;
    pc->BrakeStanding        = 1;
    return pc;
}

void physicscar_destroy(PhysicsCar *pc, int32_t flags)
{
    pc->Vehicle._vtable = PHYSICSCAR_VEHICLE_VTABLE;
    pc->Mover._vtable   = PHYSICSCAR_VTABLE;

    if (pc->pSteering != NULL) {
        const VtEntry *e = vt_slot(pc->pSteering->_vtable, STEERING_VT_DTOR);
        ((SteeringDtorFn)e->fn)(vt_this(pc->pSteering, e), 3);
    }

    // `__dl__12AerodynamicsPv`, not null-checked.
    aerodynamics_delete(pc->pAerodynamics);

    // ~PhysicsVehicle, which is ~PhysicsSystem: every component goes.
    physicssystem_fini(&pc->Vehicle, 0);
    carmover_destroy(&pc->Mover, flags);
}

// ------------------------------------------------------------ the methods

void physicscar_calibrate(PhysicsCar *pc)
{
    const CarTypeInfo *cti;
    float cog, a, b, total, rear, front;

    rigidbody_calibrate(pc->pBody,
                        (const bVector4 *)&pc->CTI->CenterOfGravity);
    rigidbody_calculate_inertia_tensor(pc->pBody);

    cti = pc->CTI;
    cog = UseNewSuspensionCalibration ? cti->CenterOfGravity.x : 0.0f;
    a = cti->Wheels[0].PositionX - cog;
    b = cti->Wheels[3].PositionX - cog;

    total = pc->pBody->Mass * PC_GRAVITY;
    rear  = (a / (a - b)) * 0.5f;
    front = 0.5f - rear;
    total = total + cti->Aero.AutoBalanceDownforce
                    * aerodynamics_get_downforce_at_speed(
                          pc->pAerodynamics, pc->pCar->State.ForwardSpeed);

    front = total * front;
    rear  = total * rear;
    suspension_calibrate(pc->pSuspension[0], front);
    suspension_calibrate(pc->pSuspension[1], front);
    suspension_calibrate(pc->pSuspension[2], rear);
    suspension_calibrate(pc->pSuspension[3], rear);

    wheel_calibrate(pc->pWheel[0]);
    wheel_calibrate(pc->pWheel[1]);
    wheel_calibrate(pc->pWheel[2]);
    wheel_calibrate(pc->pWheel[3]);
}

void physicscar_compute_auxiliaries(PhysicsCar *pc)
{
    const VtEntry *e;

    physicssystem_compute_auxiliaries(&pc->Vehicle);
    physicscar_bottom_out(pc);

    e = vt_slot(pc->Vehicle._vtable, PHYSICSSYSTEM_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(&pc->Vehicle, e));
}

// ((x*x + y*y) + z*z), the VU0's `vmul.xyz ; vaddy.x ; vaddz.x`.
static float len2(const bVector4 *v)
{
    return (v->x * v->x + v->y * v->y) + v->z * v->z;
}

// Retail's, 0x001377d8 (the demo's 0x00135878). The throttle lets a car
// alone only while a wheel is down to drive it; with none down it is tested
// as one coasting. And two tests are new before the damping: a blinking
// car, just put back on the road, is let alone, and one with no wheel down
// is damped only while its body touches something -- lying on its roof,
// not in the air.
int32_t physicscar_check_damping_suitability(PhysicsCar *pc)
{
    const RigidBody *rb;
    Car *car = pc->pCar;
    int32_t wheels = car->State.nWheelsTouchingGround;
    float v, w;

    if (PC_DAMP_THROTTLE < pc->Mover.Driver->Throttle && wheels > 0)
        return DS_NO_DAMP;

    rb = pc->pBody;
    v = sqrtf(len2(&rb->Velocity));
    w = sqrtf(len2(&rb->AngularVelocity));
    if (PC_DAMP_SPEED < v || PC_DAMP_SPEED < w)
        return DS_NO_DAMP;

    // The z of the body's forward and side axes: how far it is tipped.
    if (0.25f < fabsf(rb->State.R.v0.z) || 0.25f < fabsf(rb->State.R.v1.z))
        return DS_NO_DAMP;

    if (car_is_blinking(car))
        return DS_NO_DAMP;
    if (wheels == 0
        && car->pDynamicCollisionBody->Dynamic.Body.NumCollisions == 0)
        return DS_NO_DAMP;

    if (0.25f < v || 0.25f < w)
        return DS_DAMP;
    return DS_DOUSE;
}

// Whether the body moves faster than a car lying on its roof: its Velocity,
// the auxiliaries' from before this BottomOut's damping.
static int32_t flip_moving(const PhysicsCar *pc)
{
    return PC_FLIP_SPEED < sqrtf(len2(&pc->pBody->Velocity));
}

void physicscar_bottom_out(PhysicsCar *pc)
{
    int32_t fired = 0;
    int32_t i;

    for (i = 0; i < 4; i++) {
        Suspension *s = pc->pSuspension[i];
        if (s->State.z == s->SI->BumpStop[0]) {
            float m;
            fired = 1;
            m = suspension_apply_ground_penalty_impulse(s);
            pc->State->WheelBottomOutMagnitude[i] += m;
        }
    }

    switch (physicscar_check_damping_suitability(pc)) {
    case DS_NO_DAMP:
        if (flip_moving(pc))
            pc->FlippedTimer.PackedTime = 0;
        pc->pCar->pDynamicCollisionBody->Dynamic.Body.ActiveCollisionDetection
            = 1;
        break;
    case DS_DAMP: {
        float k = PC_DAMP_FACTOR;
        RigidBody *rb = pc->pBody;
        rb->State.P.x *= k;  rb->State.P.y *= k;
        rb->State.P.z *= k;  rb->State.P.w *= k;
        rb = pc->pBody;
        rb->State.L.x *= k;  rb->State.L.y *= k;
        rb->State.L.z *= k;  rb->State.L.w *= k;
        for (i = 0; i < 4; i++)
            wheel_set_state_w(pc->pWheel[i], pc->pWheel[i]->State.w * k);
        fired = 1;
        if (flip_moving(pc))
            pc->FlippedTimer.PackedTime = 0;
        pc->pCar->pDynamicCollisionBody->Dynamic.Body.ActiveCollisionDetection
            = 1;
        break;
    }
    case DS_DOUSE: {
        // Three words stored and a quad loaded: the port zeroes the fourth.
        bVector4 zero = { 0.0f, 0.0f, 0.0f, 0.0f };
        pc->pBody->State.P = zero;
        pc->pBody->State.L = zero;
        if (pc->pCar->State.nWheelsTouchingGround > 0)
            for (i = 0; i < 4; i++)
                wheel_set_state_w(pc->pWheel[i], 0.0f);
        fired = 1;
        // On its roof or its side: a second of lying there and the car
        // asks to be put back on the road.
        if (pc->pBody->State.R.v2.z < PC_FLIP_UP) {
            if (!timer_is_valid(&pc->FlippedTimer))
                pc->FlippedTimer.PackedTime = (uint32_t)WorldTimer;
            else if (1.0f < (float)(int32_t)((uint32_t)WorldTimer
                                              - pc->FlippedTimer.PackedTime)
                                * PC_TICK
                     && gPhysicsCarPleaseResetMeLaterFn != NULL)
                gPhysicsCarPleaseResetMeLaterFn(pc->pCar);
        } else {
            pc->FlippedTimer.PackedTime = 0;
        }
        pc->pCar->pDynamicCollisionBody->Dynamic.Body.ActiveCollisionDetection
            = 0;
        break;
    }
    default:
        break;
    }

    // The debug bounce: 25 up, at the centre of mass, after the damping in
    // retail (the demo's came before it, and a car stopped dead lost it).
    // The image stores three lanes of each vector and leaves the fourth to
    // the stack.
    if (TriggerBounce && pc->pCar->TheControlMode == 1) {
        bVector4 at = { 0.0f, 0.0f, 0.0f, 0.0f };
        bVector4 j  = { 0.0f, 0.0f, 25.0f, 0.0f };
        fired = 1;
        TriggerBounce = 0;
        rigidbody_apply_impulse(pc->pBody, &j, &at);
    }

    if (fired) {
        gUglyTimestepHack = 0.0f;
        physicssystem_compute_auxiliaries(&pc->Vehicle);
    }
}

float YawFrictionBoost(float yaw, float ebrake, float speed,
                       float yawControl, float yawControlNFS,
                       int32_t driverMode, float *tilt,
                       float postCollisionBoost)
{
    float base, m, control, t, bonus;

    *tilt = fabsf(*tilt);
    base = *tilt + 1.0f;
    m = fabsf(yaw);
    if (driverMode)
        control = yawControl + postCollisionBoost * yawControlNFS;
    else
        control = yawControl + yawControlNFS;

    // With the handbrake on, a small yaw gets no help at all.
    if (0.5f < ebrake && m < PC_YAW_LOCK_ANGLE)
        return base;

    m = m * control;
    t = LowSpeedYawBoost
        + (HighSpeedYawBoost - LowSpeedYawBoost)
          * ((speed - LowSpeedSpeed) / (HighSpeedSpeed - LowSpeedSpeed));
    bonus = m * t;
    if (MaxYawBonus < bonus)
        bonus = MaxYawBonus;
    return base + bonus;
}

float physicscar_get_brake_settings(const PhysicsCar *pc, int32_t wheel)
{
    float bb = pc->CTI->Control.BrakeBias;
    double r;

    if (wheel < 2)
        return bb + bb;
    r = 1.0 - (double)bb;
    return (float)(r + r);
}

void physicscar_initialize_state_from_car(PhysicsCar *pc)
{
    CarState *cs = pc->State;
    float rpm;
    int32_t i;

    rigidbody_set_state(pc->pBody, (const bVector4 *)&cs->Position,
                        &cs->BodyMatrix, (const bVector4 *)&cs->Velocity,
                        (const bVector4 *)&cs->AngularVelocity);

    for (i = 0; i < 4; i++) {
        suspension_set_state(pc->pSuspension[i]);
        cs = pc->State;
        wheel_set_state2(pc->pWheel[i], cs->WheelAngle[i],
                         cs->WheelAngularVelocity[i]);
    }

    cs = pc->State;
    rpm = TestRPM;
    if (TestRPM == 100.0f)
        rpm = cs->RPM;
    pc->pEngine->State.w = rpm * PC_RPM_TO_RADS;

    pc->pDriveTrain->State.clutch       = 1.0f;
    pc->pDriveTrain->DesiredGear        = cs->CurrentGear;
    pc->pDriveTrain->CurrentClutchState = CLUTCH_ENGAGED;
    pc->pDriveTrain->CurrentGear        = cs->CurrentGear;
}

void physicscar_resolve_forces(PhysicsCar *pc)
{
    uint32_t t0;
    const VtEntry *e;
    float downforce;
    int32_t i;

    t0 = bGetTicker();
    PhysicsCarResolveCounter++;
    e = vt_slot(pc->pBody->_vtable, PHYSICSCOMPONENT_VT_RESOLVE_FORCES);
    ((PhysicsVoidFn)e->fn)(vt_this(pc->pBody, e));

    aerodynamics_resolve_forces(pc->pAerodynamics, &downforce);
    if (UseMagicForce)
        downforce = downforce * 0.25f;
    else
        downforce = 0.0f;
    for (i = 0; i < 4; i++)
        suspension_resolve_forces(pc->pSuspension[i], downforce);

    (void)bGetTicker();
    physicscar_iterate_forces(pc);
    IterateTime = bGetTickerDifference(t0, bGetTicker());

    for (i = 0; i < 4; i++)
        suspension_resolve_more_forces(pc->pSuspension[i]);
    physicscar_jump_stabilizer(pc);
    ResolveTime = bGetTickerDifference(t0, bGetTicker());
}

void physicscar_iterate_forces(PhysicsCar *pc)
{
    bMatrix4 rt;
    bVector3 local, f;
    int32_t pass, i, collisions;

    drivetrain_guess_clutch_torque(pc->pDriveTrain);
    // Retail's (0x00138f38): the car's collision count, read once for the
    // four wheels' GuessGroundForce.
    collisions =
        pc->pCar->pDynamicCollisionBody->Dynamic.Body.NumCollisions;
    for (i = 0; i < 4; i++)
        wheel_guess_ground_force(pc->pWheel[i], NULL, collisions);

    // The body's force accumulator in the body's own frame. The multiply
    // is bMulMatrixVec3's, the affine one, as RigidBody.obj's private
    // bMulMatrixVector is a `j` to it.
    bTransposeMatrix(&rt, &pc->pBody->State.R);
    bMulMatrixVec3(&local, &rt,
                   (const bVector3 *)&pc->pBody->ForceAccumulator);

    for (pass = 0; pass < 5; pass++) {
        bVector3 acc = local;
        float yaw = 0.0f;
        float mass, izz;
        bVector2 a;

        for (i = 0; i < 4; i++) {
            const Suspension *s;
            wheel_get_horizontal_ground_force_car(pc->pWheel[i], &f);
            // `vadd.xyzw`; only x and y are read.
            acc.x += f.x;
            acc.y += f.y;
            s = pc->pSuspension[i];
            yaw = (yaw + s->RestPosition.x * f.y) - s->RestPosition.y * f.x;
        }

        mass = pc->pBody->Mass;
        a.x = acc.x / mass;
        a.y = acc.y / mass;
        izz = 1.0f / pc->pBody->I_body_inv.v2.z;
        yaw = yaw / izz;

        for (i = 0; i < 4; i++) {
            Wheel *w = pc->pWheel[i];
            if (w->Slipping == 0 && w->BrakeLocked == 0) {
                const Suspension *s = pc->pSuspension[i];
                bVector2 v;
                v.y = a.y + yaw * s->RestPosition.x;
                v.x = a.x - yaw * s->RestPosition.y;
                wheel_modify_ground_force(w, &v);
            }
        }
        drivetrain_modify_clutch_torque(pc->pDriveTrain);
    }

    for (i = 0; i < 4; i++)
        wheel_finalize_ground_force(pc->pWheel[i], i);
    drivetrain_finalize_clutch_torque(pc->pDriveTrain);
}

// `lqc2 ; sqc2`: all four lanes, the pad included.
static void quad_to3(bVector3 *o, const bVector4 *v)
{
    o->x = v->x;
    o->y = v->y;
    o->z = v->z;
    o->pad = v->w;
}

// `max.s`. Both arguments are absolute values here, so the zero of either
// sign and the NaN the EE FPU does not have are not in play.
static float max_s(float a, float b)
{
    return (a < b) ? b : a;
}

void physicscar_update_car(PhysicsCar *pc, float dt)
{
    CarState *cs;
    const RigidBody *rb;
    const Engine *e;
    const DriveTrain *d;
    float l, r;
    int32_t i;

    (void)dt;

    rb = pc->pBody;
    cs = pc->State;
    quad_to3(&cs->Position, &rb->State.X);
    cs->BodyMatrix = rb->State.R;
    carstate_calculate_geometry_position(pc->State);

    rb = pc->pBody;
    cs = pc->State;
    quad_to3(&cs->Velocity, &rb->Velocity);
    cs->VelocityMagnitude = sqrtf(len2(&rb->Velocity));
    cs->MatrixValid = 0;
    quad_to3(&cs->AngularVelocity, &rb->AngularVelocity);

    cs->Angle = (uint16_t)bFixATan2(
        ee_trunc_w(cs->BodyMatrix.v0.x * 65536.0f),
        ee_trunc_w(cs->BodyMatrix.v0.y * 65536.0f));
    cs->SteeringAngle = pc->Mover.Driver->Steering;
    cs->ForwardSpeed = (cs->Velocity.x * cs->BodyMatrix.v0.x
                        + cs->Velocity.y * cs->BodyMatrix.v0.y)
                       + cs->Velocity.z * cs->BodyMatrix.v0.z;

    for (i = 0; i < 4; i++) {
        const Wheel *w = pc->pWheel[i];
        const Suspension *s = pc->pSuspension[i];
        float z, mrc, over;

        cs->WheelAngularVelocity[i] = w->State.w;
        cs->WheelAngle[i] = w->State.a;

        // Clamped to MaxRenderingCompression by adding the difference,
        // so an unclamped height still has 0 added to it.
        mrc = s->SI->MaxRenderingCompression;
        z = s->State.z;
        over = 0.0f;
        if (!(z < mrc))
            over = mrc - z;
        cs->WheelSuspensionHeight[i] = z + over;

        carstate_set_wheel_touching_ground(cs, i, (int8_t)w->TouchingGround);
        carstate_set_wheel_terrain(pc->State, i,
                                   (TerrainType)pc->pWheel[i]->Terrain);

        w = pc->pWheel[i];
        cs = pc->State;
        cs->WheelTractionUsage[i] = w->TractionUsage;
        cs->WheelSlip[i].x = w->Slip[0];
        cs->WheelSlip[i].y = w->Slip[1];
        cs->WheelZForce[i] = w->ZForce;
        cs->WheelRoadNoise[i] = ((int8_t)w->TouchingGround != 0)
                                ? w->RoadNoise : 0.0f;
    }

    e = pc->pEngine;
    d = pc->pDriveTrain;
    cs->Throttle      = e->Throttle * e->ThrottleOverride;
    cs->CurrentGear   = d->CurrentGear;
    cs->ClutchEngaged = (d->CurrentClutchState == CLUTCH_ENGAGED);
    cs->RPM           = e->State.w * PC_RADS_TO_RPM;

    // The worse slip of the two corners on each side: 3 and 0 are the
    // left, 2 and 1 the right.
    l = max_s(fabsf(pc->pWheel[3]->CurrentSlip),
              fabsf(pc->pWheel[0]->CurrentSlip));
    r = max_s(fabsf(pc->pWheel[2]->CurrentSlip),
              fabsf(pc->pWheel[1]->CurrentSlip));
    l = l / SkidNormalize;
    r = r / SkidNormalize;
    if (1.0f < l)
        l = 1.0f;
    if (1.0f < r)
        r = 1.0f;
    cs->SkidLeft  = l;
    cs->SkidRight = r;

    cs->TractionUsage = (((pc->pWheel[0]->TractionUsage
                           + pc->pWheel[1]->TractionUsage)
                          + pc->pWheel[2]->TractionUsage)
                         + pc->pWheel[3]->TractionUsage) * 0.25f;

    carstate_calculate_wheel_matrices(cs);
}

void physicscar_set_boost(PhysicsCar *pc, float f)
{
    int32_t i;

    pc->pEngine->CatchupTorqueMultiplier = f;
    pc->pBody->CatchUpMultiplier = f;
    pc->pAerodynamics->Boost = f;
    pc->pAerodynamics->Draft = 1.0f - pc->pCar->DraftFactor;
    for (i = 0; i < 4; i++)
        pc->pWheel[i]->CatchupFrictionMultiplier = f;
}

void physicscar_jump_stabilizer(PhysicsCar *pc)
{
    float k;
    bVector4 m;
    const bVector4 *w;

    if (pc->pCar->State.nWheelsTouchingGround >= 2)
        return;

    w = &pc->pBody->AngularVelocity;
    k = pc->pBody->Mass
        * graph_get_value(&JumpStabilization, sqrtf(len2(w)));
    k = -k;

    w = &pc->pBody->AngularVelocity;
    m.x = w->x * k;
    m.y = w->y * k;
    m.z = w->z * k;
    m.w = w->w * k;
    rigidbody_apply_moment(pc->pBody, &m);
}

void physicscar_set_friction_boost(PhysicsCar *pc, float f)
{
    pc->FrictionBoost = f;
}

// ------------------------------------------------------------------ Move

// A NULL table is every terrain at 1, wheel.c's convention. The image
// indexes its 140-byte records at 0x00310a90 with no bounds test.
static float static_friction(const Wheel *w)
{
    if (gTerrainTypeInfoTable == NULL)
        return 1.0f;
    return gTerrainTypeInfoTable[w->Terrain].StaticFrictionMultiplier;
}

// The burn-out, for a human on a pad. A running one is cancelled when its
// time is up, when the car yaws past BurnOutYawCancel, or when every wheel
// has been under BurnOutCancelTorqueValue for longer than BurnOutAllowTime.
// A new one needs HP mode, the wheel straight, a speed under
// BurnOutMaxSpeed and a small yaw, and a wheel over BurnOutTorqueValue --
// the rear pair looked at first. State 1 cuts the traction of wheels 0
// and 3, state 2 of wheels 1 and 2.
static void move_burn_out(PhysicsCar *pc, const CarDriver *d, CarState *cs,
                          float mph)
{
    Wheel *const *w = pc->pWheel;
    float t, tr;
    int32_t pick;

    if (cs->BurnOutState != 0) {
        cs->BurnOutTime -= WorldTimeElapsed;
        if (cs->BurnOutTime < 0.0f) {
            cs->BurnOutState = 0;
        } else if (BurnOutYawCancel < fabsf(carstate_get_yaw(cs))) {
            cs->BurnOutState = 0;
        } else if (w[0]->AppliedTorque < BurnOutCancelTorqueValue
                   && w[1]->AppliedTorque < BurnOutCancelTorqueValue
                   && w[2]->AppliedTorque < BurnOutCancelTorqueValue
                   && w[3]->AppliedTorque < BurnOutCancelTorqueValue) {
            cs->BurnOutAllow += WorldTimeElapsed;
            if (BurnOutAllowTime < cs->BurnOutAllow)
                cs->BurnOutState = 0;
        } else {
            cs->BurnOutAllow = 0.0f;
        }
        return;
    }

    if (cs->DriverMode != 1 || d->Steering != 0)
        return;
    if (!(0.0f < mph && mph < BurnOutMaxSpeed))
        return;
    if (!(fabsf(carstate_get_yaw(cs)) < BurnOutYawMax))
        return;

    pick = -1;
    if (BurnOutTorqueValue < w[2]->AppliedTorque
        || BurnOutTorqueValue < w[3]->AppliedTorque) {
        if (w[3]->AppliedTorque < w[2]->AppliedTorque) {
            pick = 2;
            cs->BurnOutState = 1;
        } else {
            pick = 3;
            cs->BurnOutState = 2;
        }
    } else if (BurnOutTorqueValue < w[0]->AppliedTorque
               || BurnOutTorqueValue < w[1]->AppliedTorque) {
        if (w[0]->AppliedTorque < w[1]->AppliedTorque) {
            pick = 1;
            cs->BurnOutState = 1;
        } else {
            pick = 0;
            cs->BurnOutState = 2;
        }
    }

    // The state is already stored. A blinking car keeps it, with whatever
    // BurnOutTime and BurnOutTraction the last burn-out left.
    if (pick < 0 || car_is_blinking(pc->pCar))
        return;

    t = (w[pick]->AppliedTorque - BurnOutTorqueValue)
        / (BurnOutTorqueValueClip - BurnOutTorqueValue);
    if (1.0f < t)
        t = 1.0f;
    tr = BurnOutTractionValue;
    if (!(static_friction(w[2]) == 1.0f && static_friction(w[3]) == 1.0f))
        tr *= 1.25f;
    cs->BurnOutTime = BurnOutMinTime;
    cs->BurnOutTraction = tr + ((mph / BurnOutMaxSpeed) * (1.0f - t))
                               * (1.0f - tr);
}

// Before the green light. From PRERACE on the front brakes hold the car
// (BrakeStanding), and a press of the throttle after a release lets it
// lurch: the brakes come off for 0.4 to 0.55 s (retail's; the demo's was
// a quarter to a half second for the first of the constructor's two,
// then a half to a whole one) and go back on when the timer runs out or
// the throttle is let go. Retail rounds both stamps to the nearest tick.
static void move_brake_stand(PhysicsCar *pc, eRaceStage stage)
{
    const CarDriver *d = pc->Mover.Driver;

    if (stage >= RACE_STAGE_PRERACE) {
        if ((float)(int32_t)pc->BrakeStandTimer.PackedTime * PC_TICK
            < (float)(int32_t)((uint32_t)WorldTimer
                               - pc->BrakeStandTimerStart.PackedTime)
              * PC_TICK)
            pc->BrakeStanding = 1;

        if (0.5f < d->Throttle) {
            if (pc->ThrottleReleased && pc->LurchsLeft) {
                float r = bRandomF(PC_LURCH_RANDOM, &bDefaultSeed);

                pc->BrakeStandTimer.PackedTime =
                    (uint32_t)ee_trunc_w((r + PC_LURCH_MIN) * 4000.0f
                                         + 0.5f);
                pc->LurchsLeft--;
                pc->BrakeStanding = 0;
                pc->ThrottleReleased = 0;
                pc->BrakeStandTimerStart.PackedTime =
                    (uint32_t)ee_trunc_w((float)WorldTimer * PC_TICK
                                         * 4000.0f + 0.5f);
            }
        } else {
            pc->BrakeStanding = 1;
            pc->ThrottleReleased = 1;
        }
    }

    if (pc->BrakeStanding) {
        // Three words stored and a quad loaded: the port zeroes the fourth.
        bVector4 zero = { 0.0f, 0.0f, 0.0f, 0.0f };
        pc->pBody->State.P = zero;
    }
}

// SpeedDebugInfo in the race: a dyno. The car is put back where the
// sub-step started, at the height it reached, and the clock records 0-60,
// 0-100 and a quarter mile (400.5 m of the distance it would have gone),
// each shown for 30 seconds. Below 0.8 mph it all starts again.
static void move_speed_debug(PhysicsCar *pc)
{
    RigidBody *body = pc->pBody;
    float mph = pc->State->ForwardSpeed * PC_MS_TO_MPH;
    bVector4 dx;

    if (mph < PC_DYNO_STOPPED) {
        float now = (float)WorldTimer * PC_TICK;

        SpeedDebugQMMeasure = 0.0f;
        SpeedDebugQMTime = -1.0f;
        SpeedDebug060Time = -1.0f;
        SpeedDebugStartTime = now;
        SpeedDebug0100Time = -1.0f;
        SpeedDebugDisplayTimeQM = 0.0f;
        SpeedDebugDisplayTime100 = 0.0f;
        SpeedDebugDisplayTime60 = 0.0f;
    }
    if (SpeedDebug060Time < 0.0f && 60.0f < mph) {
        SpeedDebugDisplayTime60 = 30.0f;
        SpeedDebug060Time = (float)WorldTimer * PC_TICK - SpeedDebugStartTime;
    }
    if (SpeedDebug0100Time < 0.0f && 100.0f < mph) {
        SpeedDebugDisplayTime100 = 30.0f;
        SpeedDebug0100Time = (float)WorldTimer * PC_TICK - SpeedDebugStartTime;
    }
    if (SpeedDebugQMTime < 0.0f) {
        dx.x = SpeedDebugX.x - body->State.X.x;
        dx.y = SpeedDebugX.y - body->State.X.y;
        dx.z = SpeedDebugX.z - body->State.X.z;
        dx.w = SpeedDebugX.w - body->State.X.w;
        SpeedDebugQMMeasure += sqrtf(len2(&dx));
        if (PC_DYNO_QUARTER_MILE < SpeedDebugQMMeasure) {
            SpeedDebugQMSpeed = mph;
            SpeedDebugDisplayTimeQM = 30.0f;
            SpeedDebugQMTime = (float)WorldTimer * PC_TICK - SpeedDebugStartTime;
        }
    }

    SpeedDebugX.z = body->State.X.z;
    body->State.X = SpeedDebugX;
}

// In the race without the dyno the clock is parked: the three times at 1,
// so none of them reads as waiting, and nothing on show.
static void move_speed_debug_idle(void)
{
    SpeedDebugQMTime = 1.0f;
    SpeedDebugDisplayTime60 = 0.0f;
    SpeedDebug060Time = 1.0f;
    SpeedDebugStartTime = (float)WorldTimer * PC_TICK;
    SpeedDebug0100Time = 1.0f;
    SpeedDebugDisplayTimeQM = 0.0f;
    SpeedDebugDisplayTime100 = 0.0f;
}

float physicscar_move(PhysicsCar *pc, float dt)
{
    CarDriver *d;
    CarState *cs;
    Car *car;
    RigidBody *body;
    const ControlInfo *ctl = &pc->CTI->Control;
    const VtEntry *e;
    uint32_t t0, t;
    float boost, mph, ym, k, step;
    int32_t i, n;

    t0 = bGetTicker();
    physicscar_set_boost(pc, pc->pCar->State.BoostFactor);
    physicscar_calibrate(pc);

    d = pc->Mover.Driver;
    if (d->Brake < d->Throttle && d->EBrake < d->Throttle) {
        if (d->Brake < 0.5f)
            d->Brake = 0.0f;
        if (d->EBrake < 0.5f)
            d->EBrake = 0.0f;
    } else if (d->Throttle < 0.5f) {
        d->Throttle = 0.0f;
    }

    e = vt_slot(pc->pSteering->_vtable, STEERING_VT_SET_STEERING);
    ((SteeringSetSteeringFn)e->fn)(vt_this(pc->pSteering, e), d->Steering);

    // SetSportGear's answer is dropped; SetDesiredGear's goes back to the
    // driver, with the gearbox's own SportGear.
    pc->pEngine->Throttle = d->Throttle;
    (void)drivetrain_set_sport_gear(pc->pDriveTrain, d->SportGear);
    if (d->NitroFlag) {
        pc->pEngine->NitroFlag = 1;
        pc->pEngine->NitroBoostTimer = (float)WorldTimer * PC_TICK;
    }
    engine_decrement_nitro(pc->pEngine);
    {
        Gear want = d->DesiredGear;

        d->NitroFlag = 0;
        d->DesiredGear = drivetrain_set_desired_gear(pc->pDriveTrain, want);
    }
    d->SportGear = pc->pDriveTrain->SportGear;

    cs = pc->State;
    if (PC_MOVE_DAMP_THROTTLE < d->Throttle
        || (cs->nWheelsTouchingGround == 4
            && PC_MOVE_DAMP_TILT < fabsf(cs->BodyMatrix.v0.z)))
        pc->pBody->MotionDamping = 0;
    else
        pc->pBody->MotionDamping = 1;

    boost = pc->FrictionBoost;
    if (cs->DriverMode == 0)
        boost *= NFSAdjust;

    for (i = 3; i >= 0; i--)
        cs->WheelBottomOutMagnitude[i] = 0.0f;
    mph = cs->ForwardSpeed * PC_MS_TO_MPH;

    if (pc->pCar->TheControlMode == REAL_CONTROL
        && !IsJoystickTypeWheel(((const RealDriver *)d)->Port))
        move_burn_out(pc, d, cs, mph);

    // The handbrake winds the yaw control down to half at 20 a second, and
    // it comes back at 1 a second.
    ym = pc->YawControlMultiplier;
    if (0.5f <= d->EBrake) {
        ym -= dt * 20.0f;
        if (ym < 0.5f)
            ym = 0.5f;
    } else {
        ym += dt;
        if (1.0f < ym)
            ym = 1.0f;
    }
    pc->YawControlMultiplier = ym;

    car = pc->pCar;
    for (i = 0; i < 4; i++) {
        Wheel *w = pc->pWheel[i];
        float eb;

        // Before the race only the front brakes hold, and only while the
        // car is brake-standing. Retail's: with the throttle past 0.8 and
        // the brake past 0.5 under 10 mph, a rear brake holds by the speed
        // alone, so a car standing on both pedals spins its rear wheels.
        if (race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING
            || (pc->BrakeStanding && i < 2)) {
            if (PC_LAUNCH_THROTTLE < d->Throttle && 0.5f < d->Brake
                && mph < 10.0f && i >= 2)
                w->Brake = mph * PC_LAUNCH_BRAKE;
            else
                w->Brake = d->Brake * BrakeSettings[i];
        } else {
            w->Brake = 0.0f;
        }

        // Retail adds the HP arm's 0.5 in NFS mode too; the demo's 0.7.
        eb = d->EBrake * EBrakeSettings[i];
        if (cs->DriverMode == 0) {
            if (PC_EBRAKE_KNEE < eb)
                eb += 0.5f;
        } else if (PC_EBRAKE_KNEE < eb
                   && PC_EBRAKE_YAW < fabsf(carstate_get_yaw(cs))
                   && mph < 80.0f) {
            eb += 0.5f;
        }
        w->EBrake = eb;

        if (i == 2) {
            float tilt  = pc->pBody->State.R.v0.z;
            float yaw   = carstate_get_yaw(cs);
            float eb2   = pc->pWheel[2]->EBrake;
            int32_t mode = cs->DriverMode;
            float speed = cs->VelocityMagnitude;
            float pcb   = car_get_post_collision_yaw_control_boost(car);
            float r     = YawFrictionBoost(yaw, eb2, speed, ctl->YawControl,
                                           ctl->YawControlNFS, mode, &tilt,
                                           pcb);

            boost *= ym * (r - 1.0f) + 1.0f;
        }

        w->TractionBoost = boost;
        if ((i == 0 || i == 3) ? cs->BurnOutState == 1
                               : cs->BurnOutState == 2)
            w->TractionBoost = boost * cs->BurnOutTraction;

        // Retail's: a blown tyre is its wheel's Damage, which the wheel's
        // spin reads as drag (wheel_get_derivative). The demo cut all
        // four tractions for one blown tyre, and by fTractionBoostOverride
        // otherwise, which retail reads nowhere.
        w->Damage = (((int8_t)car->BlownTireBits >> i) & 1) ? 1.0f : 0.0f;
    }

    if (car->fDamageBoostOverride != 0.0f && car->BlownTireBits == 0)
        physicscar_set_boost(pc, car->fDamageBoostOverride);

    pc->pAerodynamics->Throttle = d->Throttle;
    pc->pAerodynamics->GroundEffect =
        (float)cs->nWheelsTouchingGround * 0.25f;

    // HP mode with no extreme limit of its own gets one of 20 while the
    // car is yawing against its spin.
    body = pc->pBody;
    if (cs->DriverMode == 0) {
        body->MaxMomentZ = ctl->MaxZMomentAcc;
    } else {
        float m = ctl->MaxZMomentAccExtreme;

        if (m == 0.0f) {
            float yaw = carstate_get_yaw(cs);

            if (yaw * body->State.L.z < 0.0f && PC_EXTREME_YAW < fabsf(yaw))
                m = 20.0f;
        }
        body->MaxMomentZ = m;
    }

    // The limiter is off under nitro, 60 on a blown tyre, and otherwise
    // the CTI's, less 3% for each whole unit of visible damage.
    // The image tests pCar here, long after using it.
    k = 1.0f;
    if (car != NULL && car->pCarDamage != NULL)
        k = 1.0f - bodydamage_get_visible_total_damage(
                       &car->pCarDamage->TheBodyDamage) * PC_DAMAGE_DERATE;
    if (pc->pEngine->NitroFlag)
        body->SpeedLimiter = 0.0f;
    else if (car->BlownTireBits != 0)
        body->SpeedLimiter = 60.0f;
    else
        body->SpeedLimiter = ctl->SpeedLimiter * k;

    // `cvt.w.s`, then one more: a dt of exactly n steps still takes n + 1.
    // The add wraps as `addiu` does, so a saturated count runs no steps.
    n = (int32_t)((uint32_t)ee_trunc_w(dt / MaximumTimeStep) + 1u);
    step = dt / (float)n;
    for (i = 0; i < n; i++) {
        eRaceStage stage;

        if (SpeedDebugInfo != 0
            || race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING) {
            SpeedDebugX = pc->pBody->State.X;
            SpeedDebugR = pc->pBody->State.R;
        }

        gUglyTimestepHack = step;
        t = bGetTicker();
        physicssystem_integrate_euler(&pc->Vehicle, step);
        eOrthonormalizeMatrix(&pc->pBody->State.R, &pc->pBody->State.R);
        (void)bGetTickerDifference(t, bGetTicker());
        if (RigidBodyDebugInfo)
            rigidbody_print_current_state(pc->pBody);
        if (DriveTrainDebugInfo)
            drivetrain_print_current_state(pc->pDriveTrain);

        stage = race_get_race_stage(pCurrentRace);
        if (stage != RACE_STAGE_RACING)
            move_brake_stand(pc, stage);
        else if (SpeedDebugInfo)
            move_speed_debug(pc);
        else
            move_speed_debug_idle();
    }

    if (SpeedDebugInfo) {
        if (0.0f < SpeedDebugDisplayTime60)
            SpeedDebugDisplayTime60 -= WorldTimeElapsed;
        if (0.0f < SpeedDebugDisplayTime100)
            SpeedDebugDisplayTime100 -= WorldTimeElapsed;
        if (0.0f < SpeedDebugDisplayTimeQM)
            SpeedDebugDisplayTimeQM -= WorldTimeElapsed;
    }

    physicscar_update_car(pc, dt);
    if (car_should_visual_effects_be_generated(pc->pCar))
        for (i = 0; i < 4; i++)
            wheel_maybe_make_skids(pc->pWheel[i], pc->pCar, dt);

    (void)bGetTickerDifference(t0, bGetTicker());
    return dt;
}

// ------------------------------------------------------------ the entries

static void vt_PhysicsCar_dtor(void *self, int32_t flags)
{
    physicscar_destroy((PhysicsCar *)self, flags);
}

static void vt_PhysicsCar_DoSnapshot(void *self, void *snap)
{
    physicscar_do_snapshot((PhysicsCar *)self, snap);
}

static float vt_PhysicsCar_Move(void *self, float dt)
{
    return physicscar_move((PhysicsCar *)self, dt);
}

static void vt_PhysicsCar_ComputeAuxiliaries(void *self)
{
    physicscar_compute_auxiliaries((PhysicsCar *)self);
}

static void vt_PhysicsCar_ResolveForces(void *self)
{
    physicscar_resolve_forces((PhysicsCar *)self);
}

static void vt_CarMover_dtor(void *self, int32_t flags)
{
    carmover_destroy((CarMover *)self, flags);
}

// 0x001374d0, `j _$_13PhysicsSystem`.
static void vt_PhysicsVehicle_dtor(void *self, int32_t flags)
{
    physicssystem_fini((PhysicsSystem *)self, flags);
}

static void vt_PhysicsVehicle_ComputeAuxiliaries(void *self)
{
    physicssystem_compute_auxiliaries((PhysicsSystem *)self);
}

static void vt_PhysicsVehicle_ResolveForces(void *self)
{
    physicssystem_resolve_forces((PhysicsSystem *)self);
}

// ------------------------------------------------------------ the tables

// Move is the base's __pure_virtual.
static const VtEntry carmover_vt[CARMOVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_CarMover_dtor },
    { 0, 0, NULL },
    { 0, 0, (VtFn)carmover_do_snapshot },
};

static const VtEntry physicscar_vt[PHYSICSCAR_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_PhysicsCar_dtor },
    { 0, 0, (VtFn)vt_PhysicsCar_Move },
    { 0, 0, (VtFn)vt_PhysicsCar_DoSnapshot },
};

// The PhysicsVehicle's entries adjust back to the PhysicsCar, and the empty
// entry 0 carries the delta as well.
#define VEHICLE_DELTA ((int16_t)-(int)offsetof(PhysicsCar, Vehicle))
static const VtEntry physicscar_vehicle_vt[PHYSICSCAR_VT_ENTRIES] = {
    { VEHICLE_DELTA, 0, NULL },
    { VEHICLE_DELTA, 0, (VtFn)vt_PhysicsCar_dtor },
    { VEHICLE_DELTA, 0, (VtFn)vt_PhysicsCar_ComputeAuxiliaries },
    { VEHICLE_DELTA, 0, (VtFn)vt_PhysicsCar_ResolveForces },
};

static const VtEntry physicsvehicle_vt[PHYSICSCAR_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_PhysicsVehicle_dtor },
    { 0, 0, (VtFn)vt_PhysicsVehicle_ComputeAuxiliaries },
    { 0, 0, (VtFn)vt_PhysicsVehicle_ResolveForces },
};

void physicscar_install_vtables(void)
{
    vt_install(CARMOVER_VTABLE, carmover_vt, CARMOVER_VT_ENTRIES);
    vt_install(PHYSICSCAR_VTABLE, physicscar_vt, PHYSICSCAR_VT_ENTRIES);
    vt_install(PHYSICSCAR_VEHICLE_VTABLE, physicscar_vehicle_vt,
               PHYSICSCAR_VT_ENTRIES);
    vt_install(PHYSICSVEHICLE_VTABLE, physicsvehicle_vt,
               PHYSICSCAR_VT_ENTRIES);
}
