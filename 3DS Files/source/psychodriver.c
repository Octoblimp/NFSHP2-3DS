// psychodriver -- see psychodriver.h.

#include "psychodriver.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "eefpu.h"
#include "realdriver.h"   // gBaseCarSoundStartHonkHornFn, ...StopHonkHornFn
#include "vtable.h"

// ------------------------------------------------------------- the seams

int32_t (*gBaseCarSoundIsHonkingFn)(struct BaseCarSound *);

// ----------------------------------------------------------- the globals

float   fPsychoCounterDiff;          // gp-13408, set by the start-up code
int32_t PsychoDriverWarnedAlready;   // gp-22576

// The arrays behind the tables, in the image's .data (retail 0x002f0588 ..
// 0x002f06d8), with the image's bits.
static const float PidProportionalData[10] = {
    0.275f, 0.204f, 0.148f, 0.115f, 0.09f,     // 3e8ccccd 3e50e560 3e178d50
    0.074f, 0.057f, 0.049f, 0.043f, 0.04f,     // 3deb851f 3db851ec ...
};
static const float PidDerivativeData[10] = {
    0.156f, 0.123f, 0.107f, 0.09f, 0.082f,     // 3e1fbe77 3dfbe76d 3ddb22d1
    0.076f, 0.071f, 0.067f, 0.064f, 0.062f,    // 3db851ec 3da7ef9e ...
};
static const float PidIntegralData[10] = {
    0.21f, 0.244f, 0.267f, 0.29f, 0.305f,      // 3e570a3d 3e79db23 3e88b439
    0.321f, 0.328f, 0.336f, 0.341f, 0.344f,    // 3e947ae1 3e9c28f6 ...
};
static const float PidSteerToData[10] = {
    15.0f, 18.0f, 23.3f, 28.0f, 34.8f,         // 41700000 41900000 41ba6666
    40.3f, 45.8f, 49.4f, 53.1f, 55.9f,         // 41e00000 420b3333 ...
};
static const float PsychoSteeringRangeData[10] = {
    45.0f, 30.0f, 20.0f, 12.0f, 8.0f,          // 42340000 41f00000 41a00000
    6.0f, 4.5f, 4.2f, 4.1f, 4.0f,              // 41400000 41000000 ...
};
static const float PsychoSteeringSpeedData[10] = {
    4.0f, 2.0f, 1.0f, 0.5f, 0.27f,             // 40800000 40000000 3f800000
    0.14f, 0.1f, 0.1f, 0.1f, 0.1f,             // 3f000000 3e8a3d71 ...
};
static const float PsychoSteeringCurveData[6] = {
    0.0f, 0.1f, 0.24f, 0.53f, 0.79f, 1.0f,     // 00000000 3dcccccd 3e75c28f
};

Table PidProportionalTable;
Table PidDerivativeTable;
Table PidIntegralTable;
Table PidSteerToTable;
Table PsychoSteeringRangeTable;
Table PsychoSteeringSpeedTable;
Table PsychoSteeringCurveTable;

// Retail 0x002aecf8, 0x002aed10, 0x002aed28 and 0x002aed40, each padded to
// 24 bytes.
const float PsychoSteeringProportionalWeight[5] = {
    0.9f, 1.0f, 0.8f, 1.0f, 0.5f,              // 3f666666 3f800000 3f4ccccd
};
const float PsychoSteeringIntegralWeight[5] = {
    0.2f, 0.0f, 0.1f, 0.0f, 0.0f,              // 3e4ccccd 0 3dcccccd
};
const float PsychoSteeringDerivativeWeight[5] = {
    0.3f, 0.08f, 0.18f, 0.0f, 0.5f,            // 3e99999a 3da3d70a 3e3851ec
};
const float PsychoDriverSteerToPointSecondsAhead[5] = {
    0.55f, 0.4f, 0.35f, 0.3f, 1.0f,            // 3f0ccccd 3ecccccd 3eb33333
};

// .sdata/.rodata through gp, with the image's bits.
#define PD_COUNTER_DIFF     0.000958738034f // gp-31560 3a7b53d2
#define PD_BAM_TO_RADIANS   9.58738e-05f   // gp-31632  38c90fdb
#define PD_WRAP_PI          3.14159f       // gp-31628  40490fd0
#define PD_WRAP_TWO_PI      6.28318f       // gp-31624  40c90fd0
#define PD_MIN_DT           0.0001f        // gp-31612  38d1b717
#define PD_DRIVER_MODE_GAIN 1.2f           // gp-31608  3f99999a
#define PD_MAX_STEER        0.7853982f     // gp-31604  3f490fdc
#define PD_TIME_EPSILON     0.001f         // gp-31600  3a83126f
#define PD_TIME_GAIN        0.3f           // gp-31596  3e99999a
#define PD_DEG_TO_RAD       0.017453294f   // gp-31592  3c8efa36
#define PD_RAD_TO_DEG       57.29578f      // gp-31588  42652ee0
#define PD_EBRAKE_SPEED     8.940545f      // gp-31584  410f0c79, 20 mph
#define PD_STEER_TO_GAIN    1.2f           // gp-31580  3f99999a
#define PD_THROTTLE_KP      0.1f           // gp-31576  3dcccccd
#define PD_THROTTLE_KD      0.01f          // gp-31572  3c23d70a
#define PD_THROTTLE_KI      0.02f          // gp-31568  3ca3d70a
#define PD_MIN_PEDAL        (-0.94f)       // gp-31564  bf70a3d7

// 360 / 65536, `lui at,0x3bb4`.
#define PD_BAM_TO_DEGREES   0.0054931640625f

#define PD_FILE_BODY     "Phsycho Body Pid"
#define PD_FILE_HEADING  "Phsycho Heading Pid"
#define PD_FILE_VELOCITY "Phsycho Velocity Pid"
#define PD_POOL          16

void psychodriver_static_init(void)
{
    // 0x00138d68, retail 0x0013ab68.
    fPsychoCounterDiff = PD_COUNTER_DIFF;
    table_init(&PidProportionalTable, PidProportionalData, 10, 0.0f, 160.0f);
    table_init(&PidDerivativeTable, PidDerivativeData, 10, 0.0f, 160.0f);
    table_init(&PidIntegralTable, PidIntegralData, 10, 0.0f, 160.0f);
    table_init(&PidSteerToTable, PidSteerToData, 10, 0.0f, 160.0f);
    table_init(&PsychoSteeringRangeTable, PsychoSteeringRangeData, 10,
               0.0f, 160.0f);
    table_init(&PsychoSteeringSpeedTable, PsychoSteeringSpeedData, 10,
               0.0f, 160.0f);
    table_init(&PsychoSteeringCurveTable, PsychoSteeringCurveData, 6,
               0.0f, 1.0f);
}

// `max.s` and `min.s`.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

static float min_s(float fs, float ft)
{
    return fs < ft ? fs : ft;
}

// ----------------------------------------------------- the free functions

float radian_wrap(uint16_t bam)
{
    float f = (float)(int32_t)bam * PD_BAM_TO_RADIANS;

    if (PD_WRAP_PI < f)
        f = f - PD_WRAP_TWO_PI;
    else if (f < -PD_WRAP_PI)
        f = f + PD_WRAP_TWO_PI;
    return f;
}

void ai_steer_straight_vector3d(bVector3 *out, Car *car, float dist)
{
    // 0x001cd148. bSinCos(&v.y, &v.x, Angle), then the VU's four lanes.
    float s, c, d;
    const bVector3 *p = &car->State.Position;

    bSinCos(&s, &c, car->State.Angle);
    d = max_s(5.0f, dist);
    out->x = c * d + p->x;
    out->y = s * d + p->y;
    out->z = 0.0f * d + p->z;
    out->pad = p->pad;
}

void ai_steer_straight_velocity3d(bVector3 *out, Car *car, float dist)
{
    // 0x001cd1d8.
    bVector3 n;
    const bVector3 *p = &car->State.Position;

    bNormalize3To(&n, &car->State.Velocity, max_s(5.0f, dist));
    out->x = n.x + p->x;
    out->y = n.y + p->y;
    out->z = n.z + p->z;
    out->pad = p->pad;
}

// ------------------------------------------------------------ the record

static PidError *new_pid_error(const char *name, int32_t integralSlots,
                               int32_t derivativeSlots)
{
    PidError *p = (PidError *)bMalloc((int)sizeof(PidError), name, 0,
                                      PD_POOL);

    return pid_error_init(p, integralSlots, derivativeSlots);
}

PsychoDriver *psychodriver_init(PsychoDriver *d, Car *car)
{
    // 0x00139760.
    cardriver_init(&d->Base);
    d->pCar = car;
    d->DirectionLatch = 1;
    d->AllowedToUseThrottleAndBrake = 1;
    d->Base.Steering = 0;
    d->DesiredSpeed = 0.0f;
    d->TimeToGetToDesiredSpeed = 0.0f;
    d->DesiredSpeedTolerance = 0.0f;
    d->EBrakeTimer = 0.0f;
    d->Base._vtable = PSYCHODRIVER_VTABLE;
    d->MaxThrottle = 1.0f;

    d->pBodyError = new_pid_error(PD_FILE_BODY, 15, 5);
    d->pHeadingError = new_pid_error(PD_FILE_HEADING, 15, 5);
    d->pVelocityError = new_pid_error(PD_FILE_VELOCITY, 6, 3);

    // Called, not dispatched.
    psychodriver_zero_steering_memory(d);
    psychodriver_zero_throttle_memory(d);
    d->SteerToPoint.x = 0.0f;
    d->SteerToPoint.y = 0.0f;
    return d;
}

void psychodriver_destroy(PsychoDriver *d, int32_t flags)
{
    // 0x001398e8.
    d->Base._vtable = PSYCHODRIVER_VTABLE;
    if (d->pBodyError != NULL)
        pid_error_destroy(d->pBodyError, 3);
    if (d->pHeadingError != NULL)
        pid_error_destroy(d->pHeadingError, 3);
    if (d->pVelocityError != NULL)
        pid_error_destroy(d->pVelocityError, 3);
    psychodriver_stop_honk_horn(d);
    cardriver_destroy(&d->Base, flags);
}

void psychodriver_set_desired_speed(PsychoDriver *d, float speed, float time,
                                    float tolerance, int32_t allowed)
{
    // 0x00139968.
    d->AllowedToUseThrottleAndBrake = allowed;
    d->DesiredSpeed = speed;
    d->TimeToGetToDesiredSpeed = time;
    d->DesiredSpeedTolerance = tolerance;
}

void psychodriver_set_target(PsychoDriver *d, DriveTarget *t)
{
    // 0x0013a3e0. `lb`, so the count is signed.
    if (t == NULL || t->NumPoints < 0 || 21 <= t->NumPoints)
        return;
    drivetarget_assign(&d->Base.MyDriveTarget, t);
    drivetarget_resample(&d->Base.MyDriveTarget, d->pCar);
}

// ------------------------------------------------------- the PID memories

int32_t psychodriver_get_error(PsychoDriver *d, float *head, float *vel)
{
    // 0x00139a68. The subtractions are `subu` on a 16-bit Angle and a word
    // bearing, cut to 16 bits.
    Car *car = d->pCar;
    int32_t ang = bATan(d->SteerToPoint.x - car->State.Position.x,
                        d->SteerToPoint.y - car->State.Position.y);
    float h;

    h = radian_wrap((uint16_t)((uint32_t)d->pCar->State.Angle
                               - (uint32_t)ang));
    *head = h;
    car = d->pCar;
    if (1.0f <= car->State.ForwardSpeed)
        *vel = radian_wrap((uint16_t)((uint32_t)bATan(car->State.Velocity.x,
                                                      car->State.Velocity.y)
                                      - (uint32_t)ang));
    else
        *vel = h;
    return ang;
}

void psychodriver_zero_steering_memory(PsychoDriver *d)
{
    // 0x00139b28.
    pid_error_reset(d->pBodyError, 0.0f);
    pid_error_reset(d->pHeadingError, 0.0f);
}

void psychodriver_clear_steering_memory(PsychoDriver *d)
{
    // 0x00139b68.
    float h, v;

    psychodriver_get_error(d, &h, &v);
    pid_error_reset(d->pBodyError, h);
    pid_error_reset(d->pHeadingError, v);
}

void psychodriver_zero_throttle_memory(PsychoDriver *d)
{
    // 0x00139bb0.
    pid_error_reset(d->pVelocityError, 0.0f);
}

void psychodriver_clear_throttle_memory(PsychoDriver *d)
{
    // 0x00139bc0, which nothing calls.
    pid_error_reset(d->pVelocityError, fabsf(d->DesiredSpeed)
                                       - d->pCar->State.VelocityMagnitude);
}

int32_t psychodriver_get_movement_index(PsychoDriver *d)
{
    // 0x00139be0, a jump table (retail 0x002aec10) on MovementMode - 1.
    Car *car = d->pCar;

    switch (car->TheMovementMode) {
    case PHYSICS_MOVEMENT:
        return PD_INDEX_PHYSICS;
    case MELLOW_MOVEMENT:
        return car->TheControlMode == TRAFFIC_CONTROL ? PD_INDEX_MELLOW
                                                      : PD_INDEX_BELT;
    case COP_MOVEMENT:
        return PD_INDEX_COP;
    case BELT_MOVEMENT:
        return PD_INDEX_BELT;
    default:   // TRAFFIC, DELIVERY and out of range
        return PD_INDEX_TRAFFIC;
    }
}

// The fixed indices, 3 and 4: `addiu v,idx,-3 ; sltiu v,v,2`.
static int is_fixed(int32_t idx)
{
    return (uint32_t)(idx - 3) < 2u;
}

// ------------------------------------------------------------ the steering

void psychodriver_calc_steer_to_point(PsychoDriver *d)
{
    // 0x0013a438.
    int32_t idx = psychodriver_get_movement_index(d);
    Car *car = d->pCar;
    bVector3 p;
    float dist;

    if (is_fixed(idx)) {
        dist = max_s(15.0f, car->State.ForwardSpeed
                            * PsychoDriverSteerToPointSecondsAhead[idx]);
    } else {
        dist = table_get_value(&PidSteerToTable, car->State.ForwardSpeed);
        car = d->pCar;
        if (car->State.DriverMode == 1)
            dist = dist * PD_STEER_TO_GAIN;
    }

    if (d->Base.MyDriveTarget.NumPoints < 2) {
        if (car->State.ForwardSpeed < 5.0f)
            ai_steer_straight_vector3d(&p, car, dist);
        else
            ai_steer_straight_velocity3d(&p, car, dist);
    } else {
        drivetarget_interpolate_point(&d->Base.MyDriveTarget, d->pCar, dist,
                                      &p);
    }
    d->SteerToPoint.x = p.x;
    d->SteerToPoint.y = p.y;
}

void psychodriver_calc_throttle_and_brake(PsychoDriver *d, float *thr,
                                          float *brk)
{
    // 0x0013a548. MaxThrottle is not read.
    PidError *p = d->pVelocityError;
    float dd = min_s(2.0f, max_s(p->aDerivative.fAverage, -2.0f));
    float pp = p->fCurrentError;
    float ii = p->aIntegral.fTotal;
    float c, f;

    if (!(d->DesiredSpeedTolerance
          < fabsf(fabsf(d->DesiredSpeed) - d->pCar->State.VelocityMagnitude))) {
        *thr = 0.0f;
        *brk = 0.0f;
        return;
    }
    c = (pp * PD_THROTTLE_KP + dd * PD_THROTTLE_KD) + ii * PD_THROTTLE_KI;
    c = min_s(0.25f, max_s(c, -0.25f));
    f = (d->Base.Throttle - d->Base.Brake) + c;
    f = min_s(1.0f, max_s(f, PD_MIN_PEDAL));
    if (f < 0.0f) {
        *thr = 0.0f;
        *brk = -f;
    } else {
        *thr = f;
        *brk = 0.0f;
    }
}

typedef void (*PsychoVoidFn)(void *self);

void psychodriver_drive(PsychoDriver *d, float dt)
{
    // 0x00139c48.
    Car *car = d->pCar;
    float steerDeg, dtc, spd, dx, dy, h, v, steer, copy, ve, thr, brk;
    float dd, pp, ii, kp, ki, kd, maxA, cur, des, delta, rate, out, t;
    int32_t front = 0, rear = 0, swap = 0, doCalc = 0, idx, fixed, i;
    Gear gear;
    PidError *pid;

    thr = 0.0f;
    brk = 0.0f;
    steerDeg = (float)(int32_t)d->Base.Steering * PD_BAM_TO_DEGREES;
    dtc = max_s(dt, PD_MIN_DT);
    spd = car->State.VelocityMagnitude;
    if (180.0f < steerDeg)
        steerDeg = steerDeg - 360.0f;
    if (car->State.ForwardSpeed < 0.0f)
        spd = -spd;

    psychodriver_calc_steer_to_point(d);
    dx = d->SteerToPoint.x - car->State.Position.x;
    dy = d->SteerToPoint.y - car->State.Position.y;
    if (200.0f < sqrtf(dx * dx + dy * dy))
        PsychoDriverWarnedAlready++;

    car = d->pCar;
    for (i = 0; i < 4; i++)
        if (car->State.WheelTouchingGround[i] != 0) {
            if (i < 2)
                front = 1;
            else
                rear = 1;
        }

    idx = psychodriver_get_movement_index(d);
    fixed = is_fixed(idx);
    psychodriver_get_error(d, &h, &v);

    if (front) {
        CollisionBody *b;

        pid_error_record(d->pBodyError, h, dt);
        pid_error_record(d->pHeadingError, v, dt);

        // Touching another car: start the steering's memory again, through
        // the table.
        b = &d->pCar->pDynamicCollisionBody->Dynamic.Body;
        for (i = 0; i < b->NumCollisions; i++)
            if (collision_is_two_car_collision(
                    collisionbody_get_collision(b, i))) {
                const VtEntry *e = vt_slot(d->Base._vtable,
                                           CARDRIVER_VT_CLEAR_STEERING_MEMORY);
                ((PsychoVoidFn)e->fn)(vt_this(d, e));
                break;
            }

        // The two errors disagree in sign, or the heading's is much the
        // larger: steer on the body's.
        if (h * v < 0.0f)
            swap = 1;
        else if (fPsychoCounterDiff < fabsf(v - h)
                 && fabsf(v) + fabsf(v) < fabsf(h))
            swap = 1;

        if (swap)
            pid = d->pBodyError;
        else if (d->pCar->State.ForwardSpeed < 5.0f)
            pid = d->pBodyError;
        else
            pid = d->pHeadingError;

        dd = min_s(0.5f, max_s(pid->aDerivative.fAverage, -0.5f));
        pp = pid->fCurrentError;
        ii = pid->aIntegral.fTotal;
        if (fixed) {
            kp = PsychoSteeringProportionalWeight[idx];
            ki = PsychoSteeringIntegralWeight[idx];
            kd = PsychoSteeringDerivativeWeight[idx];
        } else {
            kp = table_get_value(&PidProportionalTable, spd);
            kd = table_get_value(&PidDerivativeTable, spd);
            ki = table_get_value(&PidIntegralTable, spd);
            if (d->pCar->State.DriverMode == 1)
                kd = kd * PD_DRIVER_MODE_GAIN;
            else
                ki = ki * 0.5f;
        }
        steer = (-pp * kp - dd * kd) - ii * ki;
    } else {
        steer = -carstate_get_yaw_always(&d->pCar->State);
    }

    car = d->pCar;
    steer = min_s(PD_MAX_STEER, max_s(steer, -PD_MAX_STEER));
    copy = steer;

    // The speed's error, over the time left to reach it times 0.3 when
    // there is any.
    ve = fabsf(d->DesiredSpeed) - car->State.VelocityMagnitude;
    if (!(fabsf(d->TimeToGetToDesiredSpeed) <= PD_TIME_EPSILON))
        ve = ve / d->TimeToGetToDesiredSpeed * PD_TIME_GAIN;
    pid_error_record(d->pVelocityError, ve, dt);

    if (!rear) {
        // No rear wheel down: coast in first.
        gear = 1;
        thr = 0.0f;
        brk = 0.0f;
        psychodriver_zero_throttle_memory(d);
    } else if (fabsf(d->DesiredSpeed) < 2.0f) {
        gear = -1;
        thr = 0.0f;
        brk = 1.0f;
    } else if (0.0f < d->DesiredSpeed) {
        // Forwards. Rolling back faster than 7 m/s, brake and steer the
        // other way until under 2.
        if (spd < -7.0f)
            d->DirectionLatch = 0;
        else if (-2.0f < spd)
            d->DirectionLatch = 1;
        gear = -1;
        if (d->DirectionLatch) {
            doCalc = 1;
        } else {
            thr = 0.0f;
            brk = 0.5f;
            steer = -copy;
        }
    } else {
        // Backwards, in reverse, steering the other way; rolling forwards
        // faster than 7 m/s, brake until under 2.
        if (7.0f < spd)
            d->DirectionLatch = 0;
        else if (spd < 2.0f)
            d->DirectionLatch = 1;
        if (d->DirectionLatch) {
            steer = -copy;
            doCalc = 1;
            gear = 0;
        } else {
            thr = 0.0f;
            brk = 1.0f;
            gear = -1;
        }
    }

    if (doCalc)
        psychodriver_calc_throttle_and_brake(d, &thr, &brk);

    if (front) {
        // The wheel turns towards the angle at a rate, twice as fast back
        // towards the middle, except when the body's error has the wheel.
        maxA = 45.0f;
        if (fixed)
            maxA = min_s(45.0f, max_s(table_get_value(
                                          &PsychoSteeringRangeTable, spd),
                                      0.0f));
        cur = steerDeg / maxA;
        des = steer / (maxA * PD_DEG_TO_RAD);
        if (!swap && fixed)
            des = min_s(1.0f, max_s(des, -1.0f));
        delta = des - cur;
        if (fixed || !swap) {
            rate = table_get_value(&PsychoSteeringSpeedTable, spd) * 0.5f;
            if (0.0f < cur) {
                if (des < cur)
                    rate = rate + rate;
            } else if (cur < 0.0f) {
                if (cur < des)
                    rate = rate + rate;
            }
            rate = rate * dtc;
            delta = min_s(rate, max_s(delta, -rate));
        }
        out = (cur + delta) * maxA;
        if (fixed)
            out = out * d->pCar->pCarTypeInfo->Control.Steering;
    } else {
        out = steer * PD_RAD_TO_DEG;
    }

    t = d->TimeToGetToDesiredSpeed - dt;
    d->TimeToGetToDesiredSpeed = t;
    if (t < 0.0f)
        d->TimeToGetToDesiredSpeed = 0.0f;

    if (d->AllowedToUseThrottleAndBrake) {
        d->Base.Throttle = thr;
        d->Base.Brake = brk;
    } else {
        d->Base.Brake = 0.0f;
        d->Base.Throttle = 0.0f;
    }

    // Retail's e-brake: while the timer runs, over 20 mph.
    t = d->EBrakeTimer - dt;
    d->EBrakeTimer = t;
    if (0.0f < t && PD_EBRAKE_SPEED < fabsf(spd)) {
        d->Base.Brake = 0.0f;
        d->Base.EBrake = 1.0f;
        d->Base.Throttle = 0.0f;
    } else {
        d->Base.EBrake = 0.0f;
    }

    // Degrees to a BAM: `cvt.w.s` of out * 65536, then `div` by 360.
    d->Base.DesiredGear = gear;
    d->Base.Steering = (uint16_t)(ee_trunc_w(out * 65536.0f) / 360);
}

// ---------------------------------------------------------------- the horn

void psychodriver_start_honk_horn(PsychoDriver *d)
{
    // 0x0013a638. No UsageType test, unlike RealDriver's.
    struct BaseCarSound *s = d->pCar->pBaseCarSound;

    if (s != NULL && gBaseCarSoundStartHonkHornFn != NULL)
        gBaseCarSoundStartHonkHornFn(s);
}

void psychodriver_stop_honk_horn(PsychoDriver *d)
{
    // 0x0013a658.
    struct BaseCarSound *s = d->pCar->pBaseCarSound;

    if (s != NULL && gBaseCarSoundStopHonkHornFn != NULL)
        gBaseCarSoundStopHonkHornFn(s);
}

int32_t psychodriver_is_honking(PsychoDriver *d)
{
    // 0x0013a678.
    struct BaseCarSound *s = d->pCar->pBaseCarSound;

    if (s == NULL || gBaseCarSoundIsHonkingFn == NULL)
        return 0;
    return gBaseCarSoundIsHonkingFn(s);
}

// ------------------------------------------------------------ the getters

int32_t psychodriver_get_driver_number(PsychoDriver *d)
{
    // 0x0013ac80. `lh`.
    return d->pCar->DriverNumber;
}

void psychodriver_step_on_it_jeeves(PsychoDriver *d)
{
    // 0x0013acc0, which nothing calls.
    d->Base.EBrake = 0.0f;
    d->Base.Throttle = 1.0f;
    d->Base.Brake = 0.0f;
}

void psychodriver_set_low_gear(PsychoDriver *d)
{
    // 0x0013acd8.
    d->Base.DesiredGear = -1;
}

float psychodriver_get_desired_time_to_speed(PsychoDriver *d)
{
    // 0x0013ace8.
    return d->TimeToGetToDesiredSpeed;
}

float psychodriver_get_desired_speed(PsychoDriver *d)
{
    // 0x0013acf0.
    return d->DesiredSpeed;
}

void psychodriver_set_max_throttle(PsychoDriver *d, float f)
{
    // 0x0013acf8, which nothing calls.
    d->MaxThrottle = f;
}

bVector2 *psychodriver_get_steer_to_point(PsychoDriver *d)
{
    // 0x0013ad00.
    return &d->SteerToPoint;
}

void psychodriver_set_ebrake_timer(PsychoDriver *d, float f)
{
    // 0x0013ad08, which nothing calls: the only other store to the timer
    // is Drive's own countdown, so the e-brake never comes on in the game.
    d->EBrakeTimer = f;
}

void psychodriver_set_steer_to_point(PsychoDriver *d, bVector2 *p)
{
    // 0x0013ad10.
    d->SteerToPoint.y = p->y;
    d->SteerToPoint.x = p->x;
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$12PsychoDriver, retail 0x002aec50.
static const VtEntry psychodriver_vt[CARDRIVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(psychodriver_destroy),                   //   8  0x001398e8
    E(psychodriver_drive),                     //  16  0x00139c48
    { 0, 0, NULL },                            //  24  DoSnapshot, 0x00139980
    E(cardriver_add_joy_handlers),             //  32  0x00136cf0
    E(cardriver_remove_joy_handlers),          //  40  0x00136ce8
    E(psychodriver_set_low_gear),              //  48  0x0013acd8
    E(psychodriver_set_desired_speed),         //  56  0x00139968
    E(psychodriver_set_target),                //  64  0x0013a3e0
    E(psychodriver_set_steer_to_point),        //  72  0x0013ad10
    E(psychodriver_get_driver_number),         //  80  0x0013ac80
    E(psychodriver_start_honk_horn),           //  88  0x0013a638
    E(psychodriver_stop_honk_horn),            //  96  0x0013a658
    E(psychodriver_is_honking),                // 104  0x0013a678
    E(cardriver_max_speed_to_target),          // 112  0x00136c40
    E(psychodriver_zero_steering_memory),      // 120  0x00139b28
    E(psychodriver_clear_steering_memory),     // 128  0x00139b68
    E(psychodriver_get_desired_speed),         // 136  0x0013acf0
    E(psychodriver_get_desired_time_to_speed), // 144  0x0013ace8
    E(cardriver_set_physics_mode),             // 152  0x00136c08
    E(psychodriver_get_steer_to_point),        // 160  0x0013ad00
};

#undef E

void psychodriver_install_vtables(void)
{
    vt_install(PSYCHODRIVER_VTABLE, psychodriver_vt, CARDRIVER_VT_ENTRIES);
}
