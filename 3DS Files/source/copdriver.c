// copdriver -- see copdriver.h.

#include "copdriver.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"          // gCopMoverCtorFn
#include "carstate.h"
#include "cartypeinfo.h"
#include "copmanager.h"        // pCopManager
#include "eefpu.h"
#include "emath.h"
#include "topology.h"
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
