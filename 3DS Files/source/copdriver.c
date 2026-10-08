// copdriver -- see copdriver.h.

#include "copdriver.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"          // gCopMoverCtorFn, gCopDriverCtorFn
#include "carstate.h"
#include "cartypeinfo.h"
#include "cop.h"
#include "copmanager.h"        // pCopManager
#include "coputil.h"
#include "drivetarget.h"
#include "eefpu.h"
#include "emath.h"
#include "realcontroller.h"
#include "topology.h"
#include "trackroute.h"
#include "vtable.h"

// ------------------------------------------------------------ the tuning

// The .lit4 constants, gp-29508 .. gp-29472, then the ones the code builds
// with `lui`. gp-29504 and gp-29500 are both 0.3 (each state reads its
// own), as are gp-29480 and gp-29476 both 12000.
#define CM_BASE_MAX_SPEED   84.9351806640625f  // gp-29508  42a9ded0
#define CM_BRAKE_SHOWN      0.3f               // gp-29504  3e99999a
#define CM_ELEV_LOW         1000000.0f         // gp-29496  49742400
#define CM_ELEV_HIGH        -1000000.0f        // gp-29492  c9742400
#define CM_RAD_TO_BAM       10435.66796875f    // gp-29488  46230eac
#define CM_TURN_SLOPE       -9000.0f           // gp-29484  c60ca000
#define CM_TURN_LIMIT       12000.0f           // gp-29480  463b8000
#define CM_TURN_GAIN        0.3f               // gp-29472  3e99999a
#define CM_BRAKING_ACCEL    40.0f              // 42200000
#define CM_MAX_TRANSVERSE   35.0f              // 420c0000
#define CM_MAX_JERK         150.0f             // 43160000
#define CM_MAX_INTO_GROUND  4.0f               // 40800000
#define CM_MAX_STEP         2.0f               // 40000000
#define CM_DIR_SCALE        65536.0f           // 47800000

// The most the heading turns, in BAM a second: `0x780000 / 360` in
// integers, 21845, converted. (The image guards the divide by 360 against
// zero, `beql ; break`, which nothing reaches.)
#define CM_MAX_TURN_RATE    ((float)(0x780000 / 360))

// 0x002b5808, by tCopManager::nDifficultyLevel: added to fBaseMaxSpeed, so
// the easier cops top out 10 and 5 mph slower.
static const float CopMaxSpeedOffset[3] = {
    -4.470272541046143f,                       // c08f0c79
    -2.2351362705230713f,                      // c00f0c79
    0.0f
};

// The five points Move samples the ground at, about the car: (x, y).
static const bVector2 CopGroundSamples[5] = {
    { 0.0f, 0.0f }, { 1.0f, 0.0f }, { -1.0f, 0.0f },
    { 0.0f, 1.0f }, { 0.0f, -1.0f }
};

// --------------------------------------------------------- VU idioms

// `vmul.xyz ; vaddy.x ; vaddz.x`: (x*x + y*y) + z*z, left to right.
static float dot3(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// `min.s fd, a, b` and `max.s fd, a, b`, the limit second: b when it
// compares below (above) a, else a, so a NaN in either gives a.
static float min_f(float a, float b)
{
    return b < a ? b : a;
}

static float max_f(float a, float b)
{
    return a < b ? b : a;
}

// ------------------------------------------------------------ the class

CopMover *copmover_init(CopMover *m, Car *car)
{
    m->Mover._vtable = COPMOVER_VTABLE;
    m->pCar = car;
    m->v3Velocity = car->State.Velocity;
    m->v3DesiredVelocity = m->v3Velocity;
    m->State = eCMS_STEERING;
    m->fDesiredSpeed = car->State.ForwardSpeed;
    m->aDesiredFacingAngle = car->State.Angle;
    m->fBaseMaxSpeed = CM_BASE_MAX_SPEED;
    m->fSpeed = car->State.ForwardSpeed;
    m->aFacingAngle = car->State.Angle;
    copmover_reset_max_throttle_accel(m);

    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;
    m->v2TransverseAccel.x = 0.0f;
    m->v2TransverseAccel.y = 0.0f;
    m->v3GroundNormal.x = 0.0f;
    m->v3GroundNormal.y = 0.0f;
    m->v3GroundNormal.z = 1.0f;
    m->v3GroundNormal.pad = 0.0f;
    m->bIsAirborne = 0;
    m->New64 = 0.0f;
    return m;
}

CarMover *copmover_construct(void *mem, Car *car)
{
    return &copmover_init((CopMover *)mem, car)->Mover;
}

void copmover_destroy(CopMover *m, int32_t flags)
{
    m->Mover._vtable = COPMOVER_VTABLE;
    carmover_destroy(&m->Mover, flags);
}

void copmover_reset_max_throttle_accel(CopMover *m)
{
    switch (m->pCar->pCarTypeInfo->Type) {
    case 4:
        m->fMaxThrottleAccel = 11.25f;
        break;
    case 31:
        m->fMaxThrottleAccel = 12.75f;
        break;
    case 32:
    case 33:
        m->fMaxThrottleAccel = 15.0f;
        break;
    case 34:
        m->fMaxThrottleAccel = 14.25f;
        break;
    default:
        break;
    }
}

// Braking: the ramp climbs two a second to 1, and the deceleration is held
// to fMaxBrakingAccel times it. The driver's Brake shows how hard, as a
// fraction of fMaxBrakingAccel, once that is past 0.3 or the ramp is full;
// below, Brake is left as it was. `shown` is what Brake is worked from.
static float brake_ramp(CopMover *m, float dt)
{
    float r = m->New64 + (dt + dt);

    m->New64 = r;
    if (1.0f < r)
        m->New64 = 1.0f;
    return m->fMaxBrakingAccel * m->New64;
}

// Takes `v` off along the ground's normal, by no more than 4 m/s: what the
// car would drive into the ground. More than that and it is in the air.
static void hold_to_ground(CopMover *m, float vx, float vy)
{
    float dot, k;

    m->v3Velocity.x = vx;
    m->v3Velocity.y = vy;
    dot = dot3(&m->v3Velocity, &m->v3GroundNormal);
    k = min_f(dot, CM_MAX_INTO_GROUND);
    m->v3Velocity.z = m->v3Velocity.z - m->v3GroundNormal.z * k;
    m->v3Velocity.x = vx - m->v3GroundNormal.x * k;
    m->v3Velocity.y = vy - m->v3GroundNormal.y * k;
    if (CM_MAX_INTO_GROUND < dot)
        m->bIsAirborne = 1;
}

// eCMS_STEERING: the speed eased towards fDesiredSpeed, along the heading.
static void move_steering(CopMover *m, float dt, float max_speed,
                          float throttle)
{
    Car *car = m->pCar;
    CarState *cs = &car->State;
    float speed, a, mag, lim, s;
    uint16_t ang;

    copmover_calculate_facing_angle(m, max_speed, dt);
    speed = m->fSpeed;
    cs->Angle = m->aFacingAngle;
    a = (m->fDesiredSpeed - speed) / dt;
    mag = fabsf(a);
    if (a < 0.0f) {
        lim = brake_ramp(m, dt);
        if (lim < mag)
            a = a * (lim / mag);
        // The unclamped deceleration, here.
        if (m->fMaxBrakingAccel * CM_BRAKE_SHOWN < mag || m->New64 == 1.0f)
            car->pCarDriver->Brake = mag / m->fMaxBrakingAccel;
    } else {
        m->New64 = 0.0f;
        if (throttle < mag) {
            car->NitroEffectFlag = 1;
            a = a * (throttle / mag);
        }
        car->pCarDriver->Brake = 0.0f;
    }

    s = speed + a * dt;
    m->fSpeed = s;
    if (max_speed < fabsf(s))
        m->fSpeed = s * (max_speed / fabsf(s));
    cs->ForwardSpeed = m->fSpeed;

    ang = m->aFacingAngle;
    s = m->fSpeed;
    hold_to_ground(m, s * bCosBam(ang), s * bSinBam(ang));
    cs->Velocity = m->v3Velocity;
    cs->VelocityMagnitude = sqrtf(dot3(&m->v3Velocity, &m->v3Velocity));
    cs->MatrixValid = 0;
}

// eCMS_TRANSLATING: the velocity eased towards v3DesiredVelocity, the
// change split along the car's velocity and across it. Across is held to
// 35 m/s/s and its change to 150 m/s/s/s; along brakes and accelerates as
// STEERING does. The heading follows the velocity.
static void move_translating(CopMover *m, float dt, float max_speed,
                             float throttle)
{
    Car *car = m->pCar;
    CarState *cs = &car->State;
    bVector2 old;
    bVector3 d;
    float len, dvx, dvy, ux, uy, along, lx, ly, tx, ty, jx, jy, n, k;
    float lmag, shown, inv;

    len = sqrtf(dot3(&m->v3Velocity, &m->v3Velocity));
    dvx = (m->v3DesiredVelocity.x - m->v3Velocity.x) / dt;
    dvy = (m->v3DesiredVelocity.y - m->v3Velocity.y) / dt;
    // A cop standing still divides by zero, the EE's way.
    uy = ee_div(m->v3Velocity.y, len);
    ux = ee_div(m->v3Velocity.x, len);
    along = dvx * ux + dvy * uy;
    lx = along * ux;
    ly = along * uy;

    old = m->v2TransverseAccel;
    tx = dvx - lx;
    ty = dvy - ly;
    m->v2TransverseAccel.x = tx;
    m->v2TransverseAccel.y = ty;
    n = sqrtf(tx * tx + ty * ty);
    if (CM_MAX_TRANSVERSE < n) {
        k = CM_MAX_TRANSVERSE / n;
        m->v2TransverseAccel.x = tx * k;
        m->v2TransverseAccel.y = ty * k;
    }

    jx = (m->v2TransverseAccel.x - old.x) / dt;
    jy = (m->v2TransverseAccel.y - old.y) / dt;
    n = sqrtf(jx * jx + jy * jy);
    if (CM_MAX_JERK < n) {
        k = CM_MAX_JERK / n;
        jy = jy * k;
        jx = jx * k;
        m->v2TransverseAccel.y = old.y + jy * dt;
        m->v2TransverseAccel.x = old.x + jx * dt;
    }

    lmag = sqrtf(lx * lx + ly * ly);
    shown = lmag;
    if (along < 0.0f) {
        float lim = brake_ramp(m, dt);
        if (lim < lmag) {
            k = lim / lmag;
            shown = lim;
            ly = ly * k;
            lx = lx * k;
        }
        // The clamped deceleration, here.
        if (m->fMaxBrakingAccel * CM_BRAKE_SHOWN < shown || m->New64 == 1.0f)
            car->pCarDriver->Brake = shown / m->fMaxBrakingAccel;
    } else {
        m->New64 = 0.0f;
        car->pCarDriver->Brake = 0.0f;
        if (throttle < lmag) {
            // The image stores State, which is 1 here.
            car->NitroEffectFlag = 1;
            k = throttle / lmag;
            ly = ly * k;
            lx = lx * k;
        }
    }

    hold_to_ground(m,
                   m->v3Velocity.x + (lx + m->v2TransverseAccel.x) * dt,
                   m->v3Velocity.y + (ly + m->v2TransverseAccel.y) * dt);

    // No faster than max_speed, all four lanes.
    len = sqrtf(dot3(&m->v3Velocity, &m->v3Velocity));
    if (max_speed < fabsf(len)) {
        k = max_speed / fabsf(len);
        m->v3Velocity.x = m->v3Velocity.x * k;
        m->v3Velocity.y = m->v3Velocity.y * k;
        m->v3Velocity.z = m->v3Velocity.z * k;
        m->v3Velocity.pad = m->v3Velocity.pad * k;
        len = len * k;
    }
    cs->Velocity = m->v3Velocity;
    cs->VelocityMagnitude = sqrtf(dot3(&m->v3Velocity, &m->v3Velocity));
    cs->ForwardSpeed = len;
    cs->MatrixValid = 0;

    // `vrsqrt Q,vf00w,vf01x ; vaddq.x ; vmulx.xyzw`: the velocity's
    // direction, as a Q16 pair for bFixATan.
    d = m->v3Velocity;
    inv = 0.0f + ee_div(1.0f, sqrtf(dot3(&d, &d)));
    d.x = d.x * inv;
    d.y = d.y * inv;
    m->aDesiredFacingAngle = (uint16_t)bFixATan2(
        ee_trunc_w(d.x * CM_DIR_SCALE), ee_trunc_w(d.y * CM_DIR_SCALE));
    copmover_calculate_facing_angle(m, max_speed, dt);
    cs->Angle = m->aFacingAngle;
}

float copmover_move(CopMover *m, float dt)
{
    Car *car = m->pCar;
    CarState *cs = &car->State;
    const CarTypeInfo *cti;
    int32_t terrain, found, i, j;
    float max_speed, throttle;

    // The ground's normal under the car, straight up if there is none.
    topology_get_elevation(&car->TheTopologyCoordinate, &cs->Position,
                           &terrain, &m->v3GroundNormal, &found);
    if (!found) {
        // The fourth word is the image's stack; the port's is 0.
        m->v3GroundNormal.x = 0.0f;
        m->v3GroundNormal.y = 0.0f;
        m->v3GroundNormal.z = 1.0f;
        m->v3GroundNormal.pad = 0.0f;
    }

    m->aFacingAngle = cs->Angle;
    m->fSpeed = cs->ForwardSpeed;
    m->v3Velocity = cs->Velocity;

    // The top speed for the cops' strength, and the most the throttle can
    // do, falling to nothing at it.
    max_speed = m->fBaseMaxSpeed
              + CopMaxSpeedOffset[pCopManager->nDifficultyLevel];
    m->bIsAirborne = 0;
    throttle = ee_div(-m->fMaxThrottleAccel, max_speed) * fabsf(m->fSpeed)
             + m->fMaxThrottleAccel;
    if (max_speed < m->fDesiredSpeed)
        m->fDesiredSpeed = max_speed;
    car->NitroEffectFlag = 0;

    if (m->State == eCMS_STEERING)
        move_steering(m, dt, max_speed, throttle);
    else if (m->State == eCMS_TRANSLATING)
        move_translating(m, dt, max_speed, throttle);

    // Moved, all four lanes.
    cs->Position.x = m->v3Velocity.x * dt + cs->Position.x;
    cs->Position.y = m->v3Velocity.y * dt + cs->Position.y;
    cs->Position.z = m->v3Velocity.z * dt + cs->Position.z;
    cs->Position.pad = m->v3Velocity.pad * dt + cs->Position.pad;

    // On the ground: the height at the car and a metre each way along x
    // and y. If they span 2 m or less the car sits on them, on its rear
    // right wheel's height, tipped to their slopes; else it is in the air.
    if (!m->bIsAirborne) {
        float e[5], hi = CM_ELEV_HIGH, lo = CM_ELEV_LOW;
        int32_t terr[5];

        for (i = 0; i < 5; i++) {
            bVector3 p;

            p.x = CopGroundSamples[i].x + cs->Position.x;
            p.y = CopGroundSamples[i].y + cs->Position.y;
            p.z = cs->Position.z;
            p.pad = 0.0f;
            e[i] = topology_get_elevation(&car->TheTopologyCoordinate, &p,
                                          &terr[i], NULL, NULL);
            hi = max_f(hi, e[i]);
            lo = min_f(lo, e[i]);
        }

        if (fabsf(hi - lo) <= CM_MAX_STEP) {
            bMatrix4 mat;
            float sx, sy;
            uint16_t about_x, about_y;

            cti = car->pCarTypeInfo;
            sx = (((e[1] - e[0]) - (e[2] - e[0])) * 0.5f) * CM_RAD_TO_BAM;
            sy = (((e[3] - e[0]) - (e[4] - e[0])) * 0.5f) * CM_RAD_TO_BAM;
            about_y = (uint16_t)(0u - (uint32_t)ee_trunc_w(sx));
            about_x = (uint16_t)ee_trunc_w(sy);
            cs->Position.z = ((e[0] + cti->Wheels[3].Radius)
                              - cti->Wheels[3].PositionZ)
                           + cti->CenterOfGravity.z;
            eIdentity(&mat);
            eRotateZ(&mat, &mat, cs->Angle);
            eRotateX(&mat, &mat, about_x);
            eRotateY(&cs->BodyMatrix, &mat, about_y);
            cs->GeometryPosition.x = cs->Position.x - cti->CenterOfGravity.x;
            cs->GeometryPosition.y = cs->Position.y - cti->CenterOfGravity.y;
            cs->GeometryPosition.z = cs->Position.z - cti->CenterOfGravity.z;
            cs->GeometryPosition.pad =
                cs->Position.pad - cti->CenterOfGravity.pad;
        } else {
            m->bIsAirborne = 1;
        }
    }
    carstate_calculate_geometry_position(cs);

    // No spin. The fourth word is the image's stack; the port's is 0.
    cs->AngularVelocity.x = 0.0f;
    cs->AngularVelocity.y = 0.0f;
    cs->AngularVelocity.z = 0.0f;
    cs->AngularVelocity.pad = 0.0f;

    // The wheels roll at the speed, on the ground, with nothing on them.
    cti = car->pCarTypeInfo;
    cs->SteeringAngle = car->pCarDriver->Steering;
    for (i = 0; i < 4; i++) {
        float w = m->fSpeed / cti->Wheels[i].Radius;

        cs->WheelAngularVelocity[i] = w;
        cs->WheelAngle[i] = cs->WheelAngle[i] + w * dt;
        cs->WheelSuspensionHeight[i] = 0.0f;
        carstate_set_wheel_touching_ground(cs, i, 1);
        carstate_set_wheel_terrain(cs, i, TERRAIN_DEFAULT);
        cs->WheelSlip[i].x = 0.0f;
        cs->WheelSlip[i].y = 0.0f;
        cs->WheelTractionUsage[i] = 0.0f;
        cs->WheelZForce[i] = 0.0f;
        // All four, each time round.
        for (j = 3; j >= 0; j--)
            cs->WheelBottomOutMagnitude[j] = 0.0f;
    }
    carstate_calculate_wheel_matrices(cs);
    car_compute_fake_rpm(car);
    return dt;
}

float copmover_calculate_facing_angle(CopMover *m, float max_speed, float dt)
{
    float speed = m->fSpeed;
    float limit, d, r, step;

    // Up to 12000 BAM off the desired heading at a standstill, less as the
    // speed nears the top; backing up, always 12000.
    if (0.0f <= speed)
        limit = ee_div(CM_TURN_SLOPE, max_speed) * fabsf(speed)
              + CM_TURN_LIMIT;
    else
        limit = CM_TURN_LIMIT;
    d = (float)(int16_t)(uint16_t)(m->aDesiredFacingAngle - m->aFacingAngle);
    if (limit < fabsf(d))
        d = d * ee_div(limit, fabsf(d));

    r = d * (fabsf(speed) * CM_TURN_GAIN);
    if (CM_MAX_TURN_RATE < fabsf(r))
        r = (0.0f <= r) ? CM_MAX_TURN_RATE : -CM_MAX_TURN_RATE;
    step = r * dt;
    if (fabsf(d) < fabsf(step))
        step = d;
    m->aFacingAngle = (uint16_t)(m->aFacingAngle + ee_trunc_w(step));
    return r;
}

// ------------------------------------------------------------ accessors

const bVector2 *copmover_get_transverse_accel(const CopMover *m)
{
    return &m->v2TransverseAccel;
}

int32_t copmover_is_airborne(const CopMover *m)
{
    return m->bIsAirborne;
}

void copmover_set_max_throttle_accel(CopMover *m, float a)
{
    m->fMaxThrottleAccel = a;
}

void copmover_set_max_brake_accel(CopMover *m, float a)
{
    m->fMaxBrakingAccel = a;
}

void copmover_set_base_max_speed(CopMover *m, float s)
{
    m->fBaseMaxSpeed = s;
}

float copmover_get_max_speed(const CopMover *m)
{
    return m->fBaseMaxSpeed;
}

void copmover_set_desired_velocity(CopMover *m, const bVector3 *v)
{
    m->v3DesiredVelocity = *v;
    m->v3DesiredVelocity.z = 0.0f;
}

void copmover_set_desired_speed(CopMover *m, float s)
{
    m->fDesiredSpeed = s;
}

void copmover_set_desired_angle(CopMover *m, uint16_t a)
{
    m->aDesiredFacingAngle = a;
}

void copmover_set_state(CopMover *m, eCopMoverState s)
{
    m->State = s;
}

// ============================================================= CopDriver

// The .lit4 constants CopDriver reads, gp-29468 .. gp-29440, the pursuit
// file's gp-15596, and the ones the code builds with `lui`. gp-29460 and
// gp-29452 are both the mph factor and gp-29456 and gp-29448 both 1.1:
// each of Think's two arms reads its own.
#define CD_PATROL_SPEED     29.056772232055664f  // gp-29468  41e87445 65 mph
#define CD_TRANSLATE_SPEED  13.410818099975586f  // gp-29464  415692b6 30 mph
#define CD_MPS_TO_MPH       2.236999988555908f   // gp-29460  400f2b02
#define CD_SPEED_UP         1.100000023841858f   // gp-29456  3f8ccccd
#define CD_SLOW_SPEED       8.940545082092285f   // gp-29444  410f0c79 20 mph
#define CD_BACK_UP_SPEED    -8.940545082092285f  // gp-29440  c10f0c79
#define CD_HISTORY_EARLY    0.25f                // 3e800000
#define CD_HISTORY_LATE     0.6499999761581421f  // gp-15596  3f266666
#define CD_TARGET_DIST      20.0f                // 41a00000
#define CD_TRANSLATE_DIST   40.0f                // 42200000
#define CD_TURN_THROTTLE    4.0f                 // 40800000
#define CD_BACK_UP_TIME     2.0f                 // 40000000
#define CD_STUCK_SPEED      2.0f                 // 40000000
#define CD_STUCK_TIME       1.0f                 // 3f800000
#define CD_ACQUIRE_LANE     2.5f                 // 40200000
#define CD_ACQUIRE_MPH      60.0f                // 42700000
#define CD_QUARTER_TURN     16384.0f             // 46800000

// 0x00310ef8, by tCopManager::nDifficultyLevel (2 when the chased car has
// no player): how far past the driving line's own speed a chasing cop may
// go.
static const float CopLineSpeedScale[3] = {
    1.149999976158142f,                          // 3f933333
    1.2000000476837158f,                         // 3f99999a
    1.25f                                        // 3fa00000
};

typedef void (*DriverDtorFn)(void *self, int32_t flags);
// Retail's SetDesiredSpeed (56): the speed, the time to reach it, the
// tolerance and whether the throttle and brake may be used.
typedef void (*DriverDesiredSpeedFn)(void *self, float speed, float time,
                                     float tolerance, int32_t allowed);

// The cop this car is: Cops[nCopIndex], always a tAICop.
static tAICop *cop_of(const CopDriver *d)
{
    return (tAICop *)(void *)pCopManager->Cops[d->nCopIndex];
}

static const bVector2 *car_pos(const Car *car)
{
    return (const bVector2 *)(const void *)&car->State.Position;
}

// How far the car is across its route point, to the right:
// (p - rp) . (Dir.y, -Dir.x), the two products taken apart.
static float route_lateral(Car *car)
{
    const TrackRoutePoint *rp = car_get_route_point(car, 1);

    return (car->State.Position.x - rp->Position.x) * rp->Direction.y
         - (car->State.Position.y - rp->Position.y) * rp->Direction.x;
}

CopDriver *copdriver_init(CopDriver *d, Car *car)
{
    CarDriver *drv;

    trackedcontroller_init(&d->Base, car);
    d->Base.Base._vtable = COPDRIVER_VTABLE;

    // A NullDriver, with CarDriver's constructor inline and the table
    // changed after.
    drv = (CarDriver *)bMalloc((int)sizeof(NullDriver), "NullDriver", 0,
                               CAR_MEMORY_POOL);
    cardriver_init(drv);

    d->fStuckTimer = 0.0f;
    drv->_vtable = NULLDRIVER_VTABLE;
    drv->NitroFlag = 0;
    d->nCopIndex = -1;
    // `lwc1 $f1,48(s2)`: the 0 just stored, read back for both words.
    d->v2SteerTarget.x = d->fStuckTimer;
    d->fPatrolSpeed = CD_PATROL_SPEED;
    d->StateBeforeGettingStuck = eCDS_PARKED;
    d->Base.Base.Driver = drv;
    drv->DesiredGear = -1;
    d->fBackingUpTimer = 0.0f;
    d->v2SteerTarget.y = d->fStuckTimer;
    d->SubState = 1;
    d->State = eCDS_PARKED;

    switch (d->Base.Base.pCar->pCarTypeInfo->Type) {
    case 32:
        d->nCarClass = 0;
        break;
    case 33:
        d->nCarClass = 1;
        break;
    case 34:
        d->nCarClass = 2;
        break;
    case 31:
        d->nCarClass = 3;
        break;
    case 4:
        d->nCarClass = 4;
        break;
    default:
        break;
    }
    return d;
}

CarController *copdriver_construct(void *mem, Car *car)
{
    return &copdriver_init((CopDriver *)mem, car)->Base.Base;
}

void copdriver_destroy(CopDriver *d, int32_t flags)
{
    CarDriver *drv;

    d->Base.Base._vtable = COPDRIVER_VTABLE;
    drv = d->Base.Base.Driver;
    if (drv != NULL) {
        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);

        ((DriverDtorFn)e->fn)(vt_this(drv, e), 3);
    }
    trackedcontroller_destroy(&d->Base, flags);
}

// ------------------------------------------------------- the two walkers

int32_t copdriver_find_point_by_distance(bVector2 *out, float *lateral,
                                         const DriveTarget *t,
                                         const bVector2 *pos, float dist,
                                         const DLOffset *off)
{
    const bVector3 *p = t->Points;
    int32_t         n = t->NumPoints;
    int32_t         found = 0;
    int32_t         i;

    if (n == 1) {
        float dx = pos->x - p[0].x, dy = pos->y - p[0].y;

        if (sqrtf(dx * dx + dy * dy) <= dist) {
            out->x = p[0].x;
            out->y = p[0].y;
            found = 1;
            *lateral = 0.0f;
        }
    } else if (n != 0) {
        // From the last segment back, the first that pos is alongside.
        for (i = n - 2; i >= 0; i--) {
            float dx = p[i + 1].x - p[i].x;
            float dy = p[i + 1].y - p[i].y;
            float len = sqrtf(dx * dx + dy * dy);
            float ux = dx, uy = dy, along, acc;
            int32_t j;

            if (len != 0.0f) {
                float inv = ee_div(1.0f, len);

                uy = dy * inv;
                ux = dx * inv;
            }
            along = (pos->x - p[i].x) * ux + (pos->y - p[i].y) * uy;
            if (!(0.0f <= along && along < len))
                continue;

            // Then on from where pos is, a segment at a time, to `dist`.
            acc = -along;
            for (j = i; j < n - 1; j++) {
                float sx = p[j + 1].x - p[j].x;
                float sy = p[j + 1].y - p[j].y;
                float seg = sqrtf(sx * sx + sy * sy);

                acc += seg;
                if (dist <= acc) {
                    float inv = ee_div(1.0f, seg);
                    float over = acc - dist;
                    float vx = sx * inv, vy = sy * inv;

                    out->x = ((p[j + 1].x - vx * over) + vx * off->x)
                             + vy * off->y;
                    out->y = ((p[j + 1].y - vy * over) + vy * off->x)
                             + -vx * off->y;
                    *lateral = fabsf((pos->x - out->x) * vy
                                     + (pos->y - out->y) * -vx);
                    found = 1;
                    break;
                }
            }
            break;
        }
    }
    if (!found) {
        const bVector3 *q = &p[n >= 2 ? 1 : 0];

        out->y = q->y;
        out->x = q->x;
    }
    return found;
}

void copdriver_get_point_by_dl_offset_from_start(bVector2 *out,
                                                 const DriveTarget *t,
                                                 const DLOffset *off)
{
    int32_t n = t->NumPoints;
    // `addu a1,a1,n*16`: Points[n - 1], whatever n is.
    const bVector3 *a = (const bVector3 *)(const void *)
        ((const uint8_t *)t + n * 16);
    const bVector3 *b = a;
    float acc = 0.0f, dx, dy, d, px, py, l;

    if (n < 2) {
        out->x = a->x;
        out->y = a->y;
        return;
    }

    // Back from the last point while the length so far is within off->x:
    // b is the nearer end of the segment it stops in, a the farther.
    if (0.0f <= off->x) {
        int32_t left = n - 1;
        const bVector3 *next = a;

        for (;;) {
            float ex, ey;

            a = next;
            ex = a->x - b->x;
            ey = a->y - b->y;
            acc += sqrtf(ex * ex + ey * ey);
            if (--left < 0)
                break;
            next = a - 1;
            if (!(acc <= off->x))
                break;
            b = a;
        }
    }

    dy = b->y - a->y;
    dx = b->x - a->x;
    d = sqrtf(dx * dx + dy * dy);
    if (0.0f < d) {
        float s = ee_div(acc - off->x, d);

        dy = dy * s;
        dx = dx * s;
    }
    out->x = a->x + dx;
    out->y = a->y + dy;

    // Then off->y across: (dy, -dx) of the segment, made a unit.
    px = b->y - a->y;
    py = -(b->x - a->x);
    l = sqrtf(px * px + py * py);
    if (l != 0.0f) {
        py = ee_div(py, l);
        px = ee_div(px, l);
    }
    out->x = out->x + px * off->y;
    out->y = out->y + py * off->y;
}

// ----------------------------------------------------------- the pursuit

void copdriver_get_pursuit_target_point(CopDriver *d, bVector2 *out)
{
    tAICop    *cop = cop_of(d);
    tPursuit  *p = cop->Base.pMyPursuit;
    Car       *chased, *car;
    CarDriver *drv;
    DLOffset   none, off;
    float      lateral;

    if (p == NULL)
        return;
    chased = p->pChasedCar;
    none.x = 0.0f;
    none.y = 0.0f;
    drv = d->Base.Base.Driver;

    switch (cop->Base.LogicSubState) {
    case LSS_LOW_SPEED_CLOSE_FOLLOW:
    case LSS_FOLLOW_BACKWARDS:
    case LSS_FLANK:
    case LSS_BUMP:
    case LSS_BLOCK:
    case LSS_GET_AHEAD:
    case LSS_LIMBO_READY: {
        float dx, dy;

        // The pursuit's own targets: within 20 m of the chased car the
        // near one, from its start; else the far one, 20 m on from here.
        // Either is copied into the driver's.
        car = d->Base.Base.pCar;
        d->SubState = 1;
        dy = car->State.Position.y - chased->State.Position.y;
        dx = car->State.Position.x - chased->State.Position.x;
        if (sqrtf(dx * dx + dy * dy) < CD_TARGET_DIST) {
            drivetarget_assign(&drv->MyDriveTarget, &p->NearDriveTarget);
            copdriver_get_point_by_dl_offset_from_start(
                out, &p->NearDriveTarget, &cop->New48);
        } else {
            drivetarget_assign(&drv->MyDriveTarget, &p->FarDriveTarget);
            copdriver_find_point_by_distance(
                out, &lateral, &p->FarDriveTarget, car_pos(d->Base.Base.pCar),
                CD_TARGET_DIST, &cop->New48);
        }
        break;
    }
    case LSS_ACQUIRE:
        // Along the chased car's route, as far across it as the car is.
        d->SubState = 0;
        taicop_initialize_drive_target(cop);
        taicop_update_drive_target(cop, car_pos(chased), 0);
        drv = d->Base.Base.Driver;
        off.x = 0.0f;
        off.y = route_lateral(chased);
        copdriver_find_point_by_distance(out, &lateral, &drv->MyDriveTarget,
                                         car_pos(chased), CD_TARGET_DIST,
                                         &off);
        break;
    case LSS_STOP:
        d->SubState = 0;
        taicop_initialize_drive_target(cop);
        taicop_update_drive_target(cop, car_pos(chased), 0);
        copdriver_find_point_by_distance(out, &lateral, &drv->MyDriveTarget,
                                         car_pos(chased), CD_TARGET_DIST,
                                         &none);
        break;
    case LSS_LIMBO_DISABLED:
        // Along its own route.
        d->SubState = 0;
        taicop_initialize_drive_target(cop);
        taicop_update_drive_target(cop, car_pos(d->Base.Base.pCar), 0);
        copdriver_find_point_by_distance(
            out, &lateral, &d->Base.Base.Driver->MyDriveTarget,
            car_pos(d->Base.Base.pCar), CD_TARGET_DIST, &none);
        break;
    default:
        break;
    }
}

int32_t copdriver_are_we_stuck(CopDriver *d, float dt)
{
    if (!car_in_recent_collision(d->Base.Base.pCar))
        return 0;
    switch (d->State) {
    case eCDS_PATROLLING:
    case eCDS_PURSUIT:
        if (!(d->Base.Base.pCar->State.VelocityMagnitude < CD_STUCK_SPEED)) {
            d->fStuckTimer = 0.0f;
            return 0;
        }
        d->fStuckTimer = d->fStuckTimer + dt;
        return CD_STUCK_TIME < d->fStuckTimer;
    case eCDS_DISABLED:
    case eCDS_PARKED:
    case eCDS_BACKING_UP:
        d->fStuckTimer = 0.0f;
        return 0;
    default:
        return 0;
    }
}

// ----------------------------------------------------------------- Think

// DISABLED: everything off and the brakes full on, and the driver's
// SetDesiredSpeed (a NullDriver's does nothing) asked for its Throttle
// over 10 s.
static void think_disabled(CopDriver *d, CopMover *m)
{
    CarDriver     *drv = d->Base.Base.Driver;
    const VtEntry *e;

    m->fMaxBrakingAccel = 2.0f;
    m->fDesiredSpeed = 0.0f;
    drv->Throttle = 0.0f;
    drv->EBrake = 1.0f;
    drv->SportGear = -1;
    drv->Brake = 1.0f;
    drv->Steering = 0;
    drv->DesiredGear = -1;
    m->State = eCMS_STEERING;
    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_DESIRED_SPEED);
    ((DriverDesiredSpeedFn)e->fn)(vt_this(drv, e), drv->Throttle, 10.0f,
                                  drv->Throttle, 1);
}

// PATROLLING's and BACKING_UP's tail (0x001a2a4c): steer for the steer
// target at `speed`, the throttle held to 4 m/s/s.
static void steer_at_target(CopDriver *d, CopMover *m, float speed)
{
    const Car *car = d->Base.Base.pCar;
    bVector2   to;
    bPolar     pol;

    to.x = d->v2SteerTarget.x - car->State.Position.x;
    to.y = d->v2SteerTarget.y - car->State.Position.y;
    bToPolar(&pol, &to);
    m->aDesiredFacingAngle = pol.a;
    m->fMaxThrottleAccel = CD_TURN_THROTTLE;
    m->fDesiredSpeed = speed;
}

// Close behind and as fast: a velocity, the chased car's (its history's
// for a player's, at the speed it had 0.65 s back) plus the way to the
// target, the part along the cop's own velocity and the part across it
// each weighted, and stretched by `extra`.
static void pursue_translating(CopDriver *d, tAICop *cop, tPursuit *p,
                               Car *chased, CopMover *m, const bVector2 *to)
{
    float    along = 1.0f, across = 1.5f, extra = 0.0f, proj, len;
    bVector2 v, u, a, q;
    bVector3 want;
    Car     *car;

    m->State = eCMS_TRANSLATING;
    if (chased->pPlayer != NULL) {
        bVector2 w;
        float    n0;

        tpursuithistory_velocity_at(&w, &p->History, CD_HISTORY_EARLY);
        v = w;
        n0 = sqrtf(w.x * w.x + w.y * w.y);
        if (0.0f < n0) {
            float s;

            tpursuithistory_velocity_at(&w, &p->History, CD_HISTORY_LATE);
            s = ee_div(sqrtf(w.x * w.x + w.y * w.y), n0);
            v.x = v.x * s;
            v.y = v.y * s;
        }
    } else {
        v.x = chased->State.Velocity.x;
        v.y = chased->State.Velocity.y;
    }

    switch (cop->Base.LogicSubState) {
    case LSS_BLOCK:
    case LSS_STOP:
        along = 1.5f;
        extra = 3.0f;
        break;
    case LSS_GET_AHEAD:
        extra = 3.0f;
        across = 10.0f;
        break;
    case LSS_ACQUIRE: {
        float lc = route_lateral(chased);
        float lm = route_lateral(d->Base.Base.pCar);
        float s;

        if (fabsf(lc - lm) <= CD_ACQUIRE_LANE) {
            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH) {
                v.x = 0.0f;
                v.y = 0.0f;
                break;
            }
            s = 0.5f;
        } else {
            s = CD_SPEED_UP;
        }
        v.x = v.x * s;
        v.y = v.y * s;
        break;
    }
    case LSS_LIMBO_READY:
        m->fMaxBrakingAccel = 14.0f;
        across = 3.0f;
        break;
    default:
        break;
    }

    car = d->Base.Base.pCar;
    bNormalize2(&u, (const bVector2 *)(const void *)&car->State.Velocity);
    proj = to->x * u.x + to->y * u.y;
    a.y = u.y * proj;
    a.x = u.x * proj;
    q.y = to->y - a.y;
    q.x = to->x - a.x;
    want.z = 0.0f;
    if (cop->Base.LogicSubState == LSS_LIMBO_READY) {
        want.x = 0.0f;
        want.y = 0.0f;
    } else {
        want.y = (a.y * along + q.y * across) + v.y;
        want.x = (a.x * along + q.x * across) + v.x;
    }
    len = sqrtf(dot3(&want, &want));
    if (0.0f < len) {
        float s = ee_div(len + extra, len);

        want.x = want.x * s;
        want.y = want.y * s;
    }
    // The image stores the quadword and then a 0 over z; its fourth word is
    // the stack's, and the port leaves `pad` as it was.
    m->v3DesiredVelocity.x = want.x;
    m->v3DesiredVelocity.y = want.y;
    m->v3DesiredVelocity.z = 0.0f;
}

// Otherwise: a heading for the target and a speed by the sub-state, held
// to the cop's route point's driving line speed (for the slower class of
// the two cars) times the strength's scale, and to 20 mph while the chased
// car is more than a quarter turn off the cop's heading.
static void pursue_steering(CopDriver *d, tAICop *cop, Car *chased,
                            CopMover *m, const bVector2 *to, float dist,
                            float ch_speed)
{
    const TrackRoutePoint *rp;
    bPolar  pol;
    float   speed = 0.0f, lim;
    int32_t cls, cc, lvl;

    m->State = eCMS_STEERING;
    bToPolar(&pol, to);
    m->aDesiredFacingAngle = pol.a;

    switch (cop->Base.LogicSubState) {
    case LSS_LOW_SPEED_CLOSE_FOLLOW:
    case LSS_FOLLOW_BACKWARDS:
    case LSS_BUMP:
    case LSS_BLOCK:
    case LSS_GET_AHEAD:
        speed = dist + ch_speed;
        break;
    case LSS_FLANK:
        speed = dist * 5.0f + ch_speed;
        break;
    case LSS_ACQUIRE: {
        float lc = route_lateral(chased);
        float lm = route_lateral(d->Base.Base.pCar);

        if (fabsf(lc - lm) <= CD_ACQUIRE_LANE) {
            if (chased->State.ForwardSpeed * CD_MPS_TO_MPH < CD_ACQUIRE_MPH)
                speed = 0.0f;
            else
                speed = ch_speed * 0.5f;
        } else {
            speed = ch_speed * CD_SPEED_UP;
        }
        break;
    }
    case LSS_STOP:
        speed = ch_speed * CD_SPEED_UP;
        break;
    case LSS_LIMBO_DISABLED:
        speed = m->fBaseMaxSpeed;
        break;
    default:
        break;
    }

    cls = d->nCarClass;
    cc = chased->pCarTypeInfo->CarClass;
    if (cc < cls)
        cls = cc;
    rp = car_get_route_point(d->Base.Base.pCar, 1);
    lvl = chased->pPlayer != NULL ? pCopManager->nDifficultyLevel : 2;
    lim = trpoint_get_driving_line_speed(rp, cls) * CopLineSpeedScale[lvl];
    speed = min_f(lim, speed);

    if (CD_SLOW_SPEED < speed) {
        const Car *car = d->Base.Base.pCar;
        bVector2   ahead;
        bPolar     pc;
        int16_t    turn;

        ahead.x = chased->State.Position.x - car->State.Position.x;
        ahead.y = chased->State.Position.y - car->State.Position.y;
        bToPolar(&pc, &ahead);
        turn = (int16_t)(uint16_t)(pc.a - d->Base.Base.pCar->State.Angle);
        if (CD_QUARTER_TURN < fabsf((float)turn) && 1.0f < pc.r)
            speed = CD_SLOW_SPEED;
    }
    m->fDesiredSpeed = speed;
}

// PURSUIT: steer for GetPursuitTargetPoint's point, or, within 40 m of the
// chased car, going its way and at 30 mph or more, translate.
static void think_pursuit(CopDriver *d, tAICop *cop, tPursuit *p,
                          Car *chased, CopMover *m)
{
    float     ch_speed = chased->State.VelocityMagnitude;
    float     dx, dy, dist, dot;
    bVector2  to;
    Car      *car;

    copdriver_get_pursuit_target_point(d, &d->v2SteerTarget);
    car = d->Base.Base.pCar;
    to.x = d->v2SteerTarget.x - car->State.Position.x;
    to.y = d->v2SteerTarget.y - car->State.Position.y;
    // (The image works out |to| here too, and drops it.)
    dx = car->State.Position.x - chased->State.Position.x;
    dy = car->State.Position.y - chased->State.Position.y;
    dist = sqrtf(dx * dx + dy * dy);
    dot = chased->State.Velocity.x * car->State.Velocity.x
        + chased->State.Velocity.y * car->State.Velocity.y;

    if (dist < CD_TRANSLATE_DIST && 0.0f < dot
        && CD_TRANSLATE_SPEED <= car->State.VelocityMagnitude)
        pursue_translating(d, cop, p, chased, m, &to);
    else
        pursue_steering(d, cop, chased, m, &to, dist, ch_speed);
}

void copdriver_think(CopDriver *d, float dt)
{
    Car       *car;
    tAICop    *cop;
    tPursuit  *p;
    Car       *chased;
    CopMover  *m;
    CarDriver *drv;
    float      lateral;

    trackedcontroller_think(&d->Base, dt);
    car = d->Base.Base.pCar;
    // The image reads Cops[nCopIndex] before this test; the port, after.
    if (car->TheMovementMode != COP_MOVEMENT)
        return;
    cop = cop_of(d);
    p = cop->Base.pMyPursuit;
    chased = p != NULL ? p->pChasedCar : NULL;
    m = (CopMover *)(void *)car->pCarMover;
    drv = d->Base.Base.Driver;

    if (copdriver_are_we_stuck(d, dt) && !taicop_is_near_pursuit_target(cop)) {
        d->StateBeforeGettingStuck = d->State;
        d->State = eCDS_BACKING_UP;
        d->fBackingUpTimer = CD_BACK_UP_TIME;
    }
    m->fMaxBrakingAccel = CM_BRAKING_ACCEL;
    copmover_reset_max_throttle_accel(m);

    switch (d->State) {
    case eCDS_DISABLED:
        think_disabled(d, m);
        break;
    case eCDS_PARKED:
        m->fDesiredSpeed = 0.0f;
        m->State = eCMS_STEERING;
        break;
    case eCDS_PATROLLING:
        // Along the cop's own drive target (its AI's), 20 m on.
        m->State = eCMS_STEERING;
        copdriver_find_point_by_distance(&d->v2SteerTarget, &lateral,
                                         &drv->MyDriveTarget,
                                         car_pos(d->Base.Base.pCar),
                                         CD_TARGET_DIST, &cop->New48);
        steer_at_target(d, m, d->fPatrolSpeed);
        break;
    case eCDS_PURSUIT:
        if (p != NULL)
            think_pursuit(d, cop, p, chased, m);
        break;
    case eCDS_BACKING_UP:
        // For 2 s, in reverse at 20 mph towards where it was going, then
        // back to that.
        d->fBackingUpTimer = d->fBackingUpTimer - dt;
        if (d->fBackingUpTimer < 0.0f) {
            d->State = d->StateBeforeGettingStuck;
            break;
        }
        if (d->StateBeforeGettingStuck == eCDS_PATROLLING)
            copdriver_find_point_by_distance(
                &d->v2SteerTarget, &lateral,
                &d->Base.Base.Driver->MyDriveTarget,
                car_pos(d->Base.Base.pCar), CD_TARGET_DIST, &cop->New48);
        else if (d->StateBeforeGettingStuck == eCDS_PURSUIT)
            copdriver_get_pursuit_target_point(d, &d->v2SteerTarget);
        m->State = eCMS_STEERING;
        steer_at_target(d, m, CD_BACK_UP_SPEED);
        break;
    default:
        break;
    }
}

// ------------------------------------------------------------- accessors

void copdriver_get_route_numbers_to_use(CopDriver *d, int32_t *a,
                                        int32_t *b)
{
    (void)d;
    (void)a;
    (void)b;
}

void copdriver_set_patrol_speed(CopDriver *d, float s)
{
    d->fPatrolSpeed = s;
}

void copdriver_set_state(CopDriver *d, eCopDriverStates s)
{
    d->State = s;
}

void copdriver_set_cop_index(CopDriver *d, int32_t n)
{
    d->nCopIndex = n;
}

// ------------------------------------------------------------ the entries

static void vt_CopMover_dtor(void *self, int32_t flags)
{
    copmover_destroy((CopMover *)self, flags);
}

static float vt_CopMover_Move(void *self, float dt)
{
    return copmover_move((CopMover *)self, dt);
}

// DoSnapshot is not ported yet; see copdriver.h.
static const VtEntry copmover_vt[COPMOVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)vt_CopMover_dtor },      //  8  0x001a0e88
    { 0, 0, (VtFn)vt_CopMover_Move },      // 16  0x001a1030
    { 0, 0, NULL },                        // 24  0x001a0f20
};

void copmover_install_vtables(void)
{
    vt_install(COPMOVER_VTABLE, copmover_vt, COPMOVER_VT_ENTRIES);
}

void copmover_install_seams(void)
{
    gCopMoverCtorFn = copmover_construct;
}

static void vt_CopDriver_dtor(void *self, int32_t flags)
{
    copdriver_destroy((CopDriver *)self, flags);
}

static void vt_CopDriver_Think(void *self, float dt)
{
    copdriver_think((CopDriver *)self, dt);
}

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$9CopDriver, 0x002b5998. Its own destructor and Think, DoSnapshot not
// ported yet, and the rest TrackedController's and CarController's.
static const VtEntry copdriver_vt[CARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(vt_CopDriver_dtor),                           //   8  0x001a1e30
    E(carcontroller_debug_display),                 //  16  0x001c0198
    { 0, 0, NULL },                                 //  24  0x001a2b58
    E(vt_CopDriver_Think),                          //  32  0x001a2110
    E(trackedcontroller_set_current_route),         //  40  0x0023a178
    E(trackedcontroller_get_current_route),         //  48  0x0023a198
    E(trackedcontroller_get_current_route_point),   //  56  0x0023a3d0
    E(trackedcontroller_get_amount_out_of_bounds),  //  64  0x0023a300
    E(trackedcontroller_find_where_i_am),           //  72  0x0023a1c8
    E(trackedcontroller_just_reset),                //  80  0x0023a2f8
    E(carcontroller_set_to_physics_mode),           //  88  0x001c0100
    E(carcontroller_force_boost),                   //  96  0x001c0140
    E(carcontroller_release_boost),                 // 104  0x001c0160
};

#undef E

void copdriver_install_vtables(void)
{
    vt_install(COPDRIVER_VTABLE, copdriver_vt, CARCONTROLLER_VT_ENTRIES);
}

void copdriver_install_seams(void)
{
    gCopDriverCtorFn = copdriver_construct;
}
