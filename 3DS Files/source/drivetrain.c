// drivetrain -- DriveTrain.obj (0x00182828 .. 0x00183e10).
//
// Written from the listing. Every float expression keeps the image's
// association and its divides, because none of the rewrites a compiler
// would like are exact: (a + b) * 0.5f is not (a * 0.5f + b * 0.5f) once
// the sum rounds, and x * (1.0f / y) is not x / y.
//
// See drivetrain.h for the layout and docs/formats/car-drivetrain.md for
// the write-up.

#include "drivetrain.h"

#include <math.h>

#include "eefpu.h"
#include "replay.h"
#include "table.h"

// ---------------------------------------------------------- the constants

// The object's pooled literals, in the order the listing reads them.
#define K_SPLIT_LOW        0.00100000005f  // 0x3a83126f, the rear-drive test
#define K_SPLIT_HIGH       0.999000013f    // 0x3f7fbe77, the front-drive test
#define K_MPS_TO_MPH       2.23699999f     // 0x400f2b02
#define K_SLIP_THROTTLE    0.200000003f    // 0x3e4ccccd, ComputeAuxiliaries
#define K_ENGINE_PULL      0.0399999991f   // 0x3d23d70a, the 4% drag
#define K_ENGAGING_PEDAL   0.699999988f    // 0x3f333333, ThrottleOverride
#define K_IDLE_THROTTLE    0.300000012f    // 0x3e99999a, Idling and the
                                           //             CLUTCH_DISENGAGED arm
#define K_IDLE_SLOP        9.99999975e-05f // 0x38d1b717, Idling's 0.0001
#define K_SHIFT_THROTTLE   0.200000003f    // 0x3e4ccccd, the crawl arms

// Spelled as literals in the instruction stream rather than pooled:
// `lui at,0x...` then `mtc1`.
#define K_LOW_SPEED_MPH    40.0f           // 0x42200000
#define K_SHIFT_STEP       50.0f           // 0x42480000
#define K_SHIFT_CEILING    200.0f          // 0x43480000
#define K_CRAWL_OVER_IDLE  100.0f          // 0x42c80000
#define K_UPSHIFT_SLIP     4.0f            // 0x40800000
#define K_SPORT_HOLD       10.0f           // 0x41200000
#define K_LIMITER_MARGIN   300.0f          // 0x43960000

// 0x00307f30, ClutchSpeed. In Engine.obj's .data, read only from here.
static const float kClutchSpeed[4] = {
    DRIVETRAIN_CLUTCH_SPEED_DISENGAGING,
    DRIVETRAIN_CLUTCH_SPEED_DISENGAGED,
    DRIVETRAIN_CLUTCH_SPEED_ENGAGING,
    DRIVETRAIN_CLUTCH_SPEED_ENGAGED,
};

// ------------------------------------------------------------ the globals
//
// .sdata, 0x00323970 .. 0x0032398c, with the shipped values. The float
// spellings are the exact decimal of the word in the image, not a rounded
// literal: 0.95f would be 0x3f733333 here by luck, but 0.35f would not
// round to 0x3eb33333 on every toolchain, so all of them are written out.
float   gEngineBrakingFactor    = 40.0f;           // 0x42200000
float   gShiftUpDetune          = 0.949999988f;    // 0x3f733333
float   gShiftDownDetune        = 0.949999988f;    // 0x3f733333
int32_t gGearShiftMethod        = 1;
float   gLimitedSlip            = 0.349999994f;    // 0x3eb33333
float   gClutchLimiter          = 300.0f;          // 0x43960000
float   gClutchMatchedThreshold = 50.0f;           // 0x42480000
float   gMaxDownShiftOver       = 1.10000002f;     // 0x3f8ccccd

// ----------------------------------------------------------- the free one

void drivetrain_calculate_shift_points(const DriveTrainInfo *dti,
                                       const EngineInfo *ei,
                                       float *up, float *down, float scale)
{
    Table torque;
    int32_t i;
    int32_t last;

    // Built over the engine's torque curve, not over a gear: nine entries
    // spanning IdleRPM..MaxRPM, the same Table the engine itself keeps.
    table_init(&torque, ei->TorqueCurveTable, 9, ei->IdleRPM, ei->MaxRPM);

    last = dti->NumGears + 1;

    for (i = FIRST_GEAR; i < last; i++) {
        float ratio = dti->GearRatios[i];
        float next  = dti->GearRatios[i + 1];
        float point;

        if (gGearShiftMethod) {
            float ceiling = ei->MaxRPM - K_SHIFT_CEILING;
            float rpm     = (ei->IdleRPM + ei->MaxRPM) * 0.5f;
            int32_t searching = 1;

            // A do/while behind an entry test, which is what the image's
            // `bc1f` before the loop and `bne` after it spell. The
            // searching flag is set in that first branch's delay slot, so
            // it is 1 even when the loop never runs.
            if (rpm < ceiling) {
                do {
                    float here  = table_get_value(&torque, rpm);
                    float there = table_get_value(&torque, rpm * next / ratio)
                                      * next / ratio;

                    if (here < there) {
                        up[i] = rpm;
                        searching = 0;
                    }

                    rpm += K_SHIFT_STEP;
                } while (rpm < ceiling && searching);
            }

            if (searching)
                up[i] = ei->MaxRPM - K_SHIFT_CEILING;

            // Both arms join here, so the fallback is scaled as well.
            point = up[i] * scale;
        } else {
            // The dead arm: gGearShiftMethod is 1 in the image. Note it
            // never sees `scale`.
            point = ei->IdleRPM
                  + dti->ShiftUpPoint * (ei->RedLineRPM - ei->IdleRPM);
        }

        up[i] = point;

        // The gear above gets its down point from the gear below's up
        // point, geared across. Entry FIRST_GEAR of `down` is therefore
        // never written by this function.
        down[i + 1] = gShiftDownDetune * up[i] * next / ratio;
    }

    // i is NumGears + 1 here whether or not the loop ran: the top gear
    // never shifts up.
    up[i] = ei->MaxRPM;
}

// ------------------------------------------------------------- the object

void drivetrain_init(DriveTrain *d, const DriveTrainInfo *dti, Engine *e,
                     Wheel *const *wheels, CarState *cs)
{
    int32_t k;

    d->pEngine = e;
    d->_vtable = DRIVETRAIN_VTABLE;
    d->DTI = dti;

    // `bgez a2` with a2 counting 3, 2, 1, 0, -1: four pointers.
    for (k = 0; k < 4; k++)
        d->pDriveWheel[k] = wheels[k];

    d->pCarState = cs;

    drivetrain_calculate_shift_points(dti, e->EI, d->ShiftUpRPM,
                                      d->ShiftDownRPM, gShiftUpDetune);

    d->DesiredGear = FIRST_GEAR;
    d->State.clutch = 0.0f;
    d->CurrentClutchState = CLUTCH_ENGAGING;
    d->CurrentGear = FIRST_GEAR;
    d->Shifting = 0;

    // PreviousGear, DifferentialAngularVelocity, GearHoldTime and
    // SportGear are deliberately not written: the listing stores to 20, 8,
    // 16, 24, 44, 12, 56, 48, 60 and stops. See drivetrain.h.
}

float drivetrain_get_differential_angular_velocity(const DriveTrain *d)
{
    const DriveTrainInfo *dti = d->DTI;
    float split = dti->TorqueSplit;
    float w = 0.0f;
    int32_t rear = (K_SPLIT_LOW <= split);
    int32_t both = 1;

    if (rear)
        w = ((d->pDriveWheel[2]->State.w + d->pDriveWheel[3]->State.w) * 0.5f)
                * dti->FinalDrive[1];

    if (split <= K_SPLIT_HIGH) {
        w += ((d->pDriveWheel[0]->State.w + d->pDriveWheel[1]->State.w) * 0.5f)
                 * dti->FinalDrive[0];

        // Reached only through this arm: a rear-drive car never halves.
        if (!rear)
            both = 0;

        if (both)
            w *= 0.5f;
    }

    return w * dti->GearRatios[d->CurrentGear];
}

float drivetrain_get_drive_wheel_slippage(const DriveTrain *d)
{
    const DriveTrainInfo *dti = d->DTI;
    float split = dti->TorqueSplit;
    float s = 0.0f;

    if (K_SPLIT_LOW <= split)
        s = (d->pDriveWheel[2]->OldSlip + d->pDriveWheel[3]->OldSlip) * 0.5f;

    // No `both` flag here, unlike GetDifferentialAngularVelocity: the
    // halving is unconditional inside the front arm, so a front-drive car
    // gets half of its own mean.
    if (split <= K_SPLIT_HIGH)
        s = (s + (d->pDriveWheel[0]->OldSlip + d->pDriveWheel[1]->OldSlip)
                     * 0.5f) * 0.5f;

    return s;
}

// The body of SetDifferentialAngularVelocity, once per driven pair. `lo`
// and `hi` are the pair's wheel indices and `drive` its final drive.
static void drivetrain_share_out(DriveTrain *d, float delta, int32_t lo,
                                 int32_t hi, float drive, int32_t slow)
{
    Wheel *a = d->pDriveWheel[lo];
    Wheel *b = d->pDriveWheel[hi];
    float ratio;
    float step;
    float wa;
    float wb;

    if (!a->TouchingGround && !b->TouchingGround)
        slow = 1;

    ratio = d->DTI->GearRatios[d->CurrentGear] * drive;

    // In the delay slot of the `beq`, so it happens before the averaging
    // and regardless of it.
    step = delta / ratio;

    wa = a->State.w;
    wb = b->State.w;

    if (slow) {
        wb = (wa + wb) * 0.5f;
        wa = wb;
    }

    wheel_set_state_w(a, wa + step);
    wheel_set_state_w(b, wb + step);
}

void drivetrain_set_differential_angular_velocity(DriveTrain *d, float w)
{
    float delta = w - drivetrain_get_differential_angular_velocity(d);
    float mph = d->pCarState->VelocityMagnitude * K_MPS_TO_MPH;
    const DriveTrainInfo *dti = d->DTI;

    // The low-speed test is recomputed for each pair, so a rear pair with
    // both wheels up does not drag the front pair into the average.
    if (K_SPLIT_LOW <= dti->TorqueSplit)
        drivetrain_share_out(d, delta, 2, 3, dti->FinalDrive[1],
                             mph < K_LOW_SPEED_MPH);

    if (dti->TorqueSplit <= K_SPLIT_HIGH)
        drivetrain_share_out(d, delta, 0, 1, dti->FinalDrive[0],
                             mph < K_LOW_SPEED_MPH);
}

// One driven wheel's contribution to the differential's acceleration.
// GetRadius is called before GetMomentOfInertia in the listing and the
// divide lands in a delay slot; both are pure, so only the arithmetic
// order matters here.
static float drivetrain_wheel_acceleration(Wheel *w)
{
    float radius = wheel_get_radius(w);

    return (w->AppliedTorque - w->GroundForce[0] * radius)
               / wheel_get_moment_of_inertia(w);
}

float drivetrain_get_differential_angular_acceleration(DriveTrain *d)
{
    const DriveTrainInfo *dti = d->DTI;
    float acc = 0.0f;
    int32_t rear = (K_SPLIT_LOW <= dti->TorqueSplit);
    int32_t both = 1;

    if (rear)
        acc = ((drivetrain_wheel_acceleration(d->pDriveWheel[2])
                + drivetrain_wheel_acceleration(d->pDriveWheel[3])) * 0.5f)
                  * dti->FinalDrive[1];

    if (dti->TorqueSplit <= K_SPLIT_HIGH) {
        acc += ((drivetrain_wheel_acceleration(d->pDriveWheel[0])
                 + drivetrain_wheel_acceleration(d->pDriveWheel[1])) * 0.5f)
                   * dti->FinalDrive[0];

        if (!rear)
            both = 0;

        if (both)
            acc *= 0.5f;
    }

    return acc * dti->GearRatios[d->CurrentGear];
}

void drivetrain_compute_auxiliaries(DriveTrain *d)
{
    Engine *e;

    d->DifferentialAngularVelocity =
        drivetrain_get_differential_angular_velocity(d);

    e = d->pEngine;

    switch (d->CurrentClutchState) {
    case CLUTCH_DISENGAGING:
        e->ThrottleOverride = 0.0f;

        // The image reloads the word it has just stored and compares
        // against that, so the right-hand side is the zero it wrote.
        if (d->State.clutch <= e->ThrottleOverride) {
            d->CurrentClutchState = CLUTCH_DISENGAGED;
            d->State.clutch = e->ThrottleOverride;
        }
        break;

    case CLUTCH_DISENGAGED:
        // The gear actually changes here, with the clutch all the way out.
        d->CurrentGear = d->DesiredGear;
        e->ThrottleOverride = 0.0f;

        if (d->Shifting || K_IDLE_THROTTLE < e->Throttle) {
            d->Shifting = 0;
            d->CurrentClutchState = CLUTCH_ENGAGING;
        }
        break;

    case CLUTCH_ENGAGING:
        e->ThrottleOverride = K_ENGAGING_PEDAL;

        if (1.0f <= d->State.clutch) {
            d->State.clutch = 1.0f;

            if (drivetrain_clutch_matched(d) || d->CurrentGear == NEUTRAL)
                d->CurrentClutchState = CLUTCH_ENGAGED;
        }

        if (drivetrain_idling(d))
            d->CurrentClutchState = CLUTCH_DISENGAGING;
        break;

    case CLUTCH_ENGAGED:
        e->ThrottleOverride = 1.0f;

        // NEUTRAL skips every bit of clutch physics below and goes
        // straight to the shift test, but the store above still happened:
        // it is the branch's delay slot.
        if (d->CurrentGear != NEUTRAL) {
            float slip = d->DifferentialAngularVelocity - e->State.w;

            // Called before the throttle test, not behind it: the listing
            // has the `jal` at 0x0018317c and the compare at 0x00183194.
            // It reads nothing this function has written, so the order
            // only matters for the shape.
            float slippage = drivetrain_get_drive_wheel_slippage(d);

            if (K_SLIP_THROTTLE < e->Throttle && 0.0f < slippage) {
                // Wheelspin under power: throw the drivetrain's speed
                // away and match the engine exactly.
                d->DifferentialAngularVelocity = e->State.w;
                drivetrain_set_differential_angular_velocity(
                    d, e->State.w);
            } else {
                e->State.w += slip * K_ENGINE_PULL;
            }

            if (drivetrain_idling(d))
                d->CurrentClutchState = CLUTCH_DISENGAGING;
        }

        if (d->CurrentGear != d->DesiredGear) {
            d->CurrentClutchState = CLUTCH_DISENGAGING;
            d->Shifting = 1;
        }
        break;

    default:
        break;
    }
}

int32_t drivetrain_get_derivative(const DriveTrain *d, float *out)
{
    out[0] = d->DTI->ShiftSpeed * kClutchSpeed[d->CurrentClutchState];

    return 0;
}

// One driven pair's share of a clutch torque.
//
// `first` and `second` are the pair in index order, which is the order the
// listing tests TouchingGround and BrakeLocked in and the order it stores
// AppliedTorque in. `name_first` says which of the two the spin share is
// computed for: the rear block names its *first* wheel (index 2) and the
// front block names its *second* (index 1).
//
// That choice is invisible in the clamped and open cases, which are
// symmetric under share -> 1 - share, and visible in the burnout cases,
// which are not. BurnOutState 1 therefore hands the large share to wheels
// 1 and 2 and the small one to 0 and 3 -- diagonally, which is almost
// certainly a copy-and-paste in the original rather than a design.
static void drivetrain_split_torque(DriveTrain *d, float torque,
                                    Wheel *first, Wheel *second,
                                    int32_t name_first)
{
    Wheel *named = name_first ? first : second;
    Wheel *other = name_first ? second : first;
    float threshold = 0.5f;
    float share;
    float first_share;
    float second_share;

    // Both wheels of the pair on the ground narrows the band the open
    // differential is allowed to work in, from [0.5, 0.5] -- which is no
    // band at all, so an airborne pair is always clamped -- to
    // [0.35, 0.65].
    if (first->TouchingGround && second->TouchingGround)
        threshold = gLimitedSlip;

    if (d->pCarState->BurnOutState == 1) {
        share = 1.0f - threshold;
    } else if (d->pCarState->BurnOutState == 2) {
        share = threshold;
    } else {
        // A pair standing still is 0/0 here, and the console's answer is
        // FLT_MAX, which the clamp below turns into the small share for
        // the named wheel. IEEE's NaN would go on into AppliedTorque, the
        // wheels and the body -- a car sitting in gear on the grid does
        // this every frame. See eefpu.h.
        share = ee_div(named->State.w, named->State.w + other->State.w);

        // The clamp goes the other way on purpose: a rim whose share has
        // fallen below the threshold is the one being held back, so it is
        // handed the large share, and a rim that has run away is cut to
        // the small one. That is the limited-slip behaviour; between the
        // two thresholds the differential is open and the faster rim
        // keeps the larger share.
        if (share < threshold)
            share = 1.0f - gLimitedSlip * 0.5f;
        else if (1.0f - threshold < share)
            share = gLimitedSlip * 0.5f;
    }

    first_share  = name_first ? share : 1.0f - share;
    second_share = name_first ? 1.0f - share : share;

    if (!first->BrakeLocked)
        first->AppliedTorque += torque * first_share;

    if (!second->BrakeLocked)
        second->AppliedTorque += torque * second_share;
}

void drivetrain_apply_clutch_torque(DriveTrain *d, float torque)
{
    const DriveTrainInfo *dti;
    float geared;

    // NEUTRAL returns before RoadTorque is touched, so a torque applied in
    // neutral vanishes rather than braking the engine.
    if (d->CurrentGear == NEUTRAL)
        return;

    dti = d->DTI;

    d->pEngine->RoadTorque -= torque;

    geared = torque * dti->GearRatios[d->CurrentGear];

    // The front pair names index 1 and the rear pair index 2; the listing
    // loads 32(a0) at the front and 32(a3) at the rear.
    drivetrain_split_torque(d, geared * (1.0f - dti->TorqueSplit)
                                   * dti->FinalDrive[0],
                            d->pDriveWheel[0], d->pDriveWheel[1], 0);
    drivetrain_split_torque(d, geared * dti->TorqueSplit
                                   * dti->FinalDrive[1],
                            d->pDriveWheel[2], d->pDriveWheel[3], 1);
}

void drivetrain_guess_clutch_torque(DriveTrain *d)
{
    switch (d->CurrentClutchState) {
    case CLUTCH_DISENGAGED:
        break;

    case CLUTCH_DISENGAGING:
    case CLUTCH_ENGAGING: {
        float slip = d->pEngine->State.w - d->DifferentialAngularVelocity;

        if (gClutchLimiter < slip)
            slip = gClutchLimiter;
        else if (slip < -gClutchLimiter)
            slip = -gClutchLimiter;

        drivetrain_apply_clutch_torque(
            d, slip * d->DTI->ClutchStiffness * d->State.clutch);
        break;
    }

    case CLUTCH_ENGAGED:
        drivetrain_apply_clutch_torque(
            d, engine_get_total_engine_torque(d->pEngine));
        break;

    default:
        break;
    }
}

void drivetrain_modify_clutch_torque(DriveTrain *d)
{
    Engine *e;
    const DriveTrainInfo *dti;
    float difference;
    float inverse;

    if (d->CurrentClutchState != CLUTCH_ENGAGED)
        return;

    e = d->pEngine;

    // Engine::GetDerivative's expression, recomputed inline rather than
    // called: the listing does the add and the divide here.
    difference = (engine_get_total_engine_torque(e) + e->RoadTorque)
                     / e->EI->MomentOfInertia;
    difference -= drivetrain_get_differential_angular_acceleration(d);

    inverse = 1.0f / e->EI->MomentOfInertia;

    dti = d->DTI;

    if (dti->TorqueSplit <= K_SPLIT_HIGH) {
        float geared = dti->FinalDrive[0] * dti->GearRatios[d->CurrentGear];

        inverse += ((1.0f - dti->TorqueSplit) * 0.5f)
                       * (geared * (1.0f
                              / wheel_get_moment_of_inertia(
                                    d->pDriveWheel[0])))
                       * geared;
    }

    if (K_SPLIT_LOW <= dti->TorqueSplit) {
        float geared = dti->FinalDrive[1] * dti->GearRatios[d->CurrentGear];

        inverse += (dti->TorqueSplit * 0.5f)
                       * (geared * (1.0f
                              / wheel_get_moment_of_inertia(
                                    d->pDriveWheel[2])))
                       * geared;
    }

    // One wheel per axle, not two: the listing reads pDriveWheel[0] and
    // pDriveWheel[2] and never the odd ones.
    drivetrain_apply_clutch_torque(d, difference / inverse);
}

void drivetrain_finalize_clutch_torque(DriveTrain *d)
{
    (void)d;
}

int32_t drivetrain_idling(const DriveTrain *d)
{
    const Engine *e = d->pEngine;

    if (!(e->Throttle < K_IDLE_THROTTLE))
        return 0;

    return d->DifferentialAngularVelocity
               <= e->EI->IdleRPM * DRIVETRAIN_RPM_TO_RADS + K_IDLE_SLOP;
}

int32_t drivetrain_clutch_matched(const DriveTrain *d)
{
    return fabsf(d->pEngine->State.w - d->DifferentialAngularVelocity)
               <= gClutchMatchedThreshold;
}

Gear drivetrain_set_sport_gear(DriveTrain *d, Gear g)
{
    if (!(g < FIRST_GEAR) && !(d->DTI->NumGears + 1 < g)) {
        if (d->SportGear == NEUTRAL)
            d->GearHoldTime = 0.0f;

        d->SportGear = g;
    }

    return d->SportGear;
}

Gear drivetrain_set_desired_gear(DriveTrain *d, Gear g)
{
    Engine *e;
    Gear current;
    float rpm;
    float down;

    if (g == AUTOMATIC) {
        current = d->CurrentGear;
        d->SportGear = NEUTRAL;

        // Out of reverse or neutral the automatic only ever asks for
        // first; there is no reverse logic in this object at all.
        if (current < FIRST_GEAR) {
            d->DesiredGear = FIRST_GEAR;
            return g;
        }

        if (d->CurrentClutchState != CLUTCH_ENGAGED)
            return g;

        e = d->pEngine;
        rpm = e->State.w * DRIVETRAIN_RADS_TO_RPM;

        if (current < THIRD_GEAR) {
            // First and second have no table down point. With the
            // throttle nearly shut they drop out just above idle, and
            // with it open they never drop out at all.
            if (e->Throttle < K_SHIFT_THROTTLE)
                down = e->EI->IdleRPM + K_CRAWL_OVER_IDLE;
            else
                down = 0.0f;
        } else {
            down = d->ShiftDownRPM[current];
        }

        if (d->ShiftUpRPM[current] < rpm
                && current < d->DTI->NumGears + 1
                && d->pDriveWheel[0]->CurrentSlip < K_UPSHIFT_SLIP
                && d->pDriveWheel[0]->TouchingGround
                && d->pDriveWheel[1]->CurrentSlip < K_UPSHIFT_SLIP
                && d->pDriveWheel[1]->TouchingGround
                && d->pDriveWheel[2]->CurrentSlip < K_UPSHIFT_SLIP
                && d->pDriveWheel[2]->TouchingGround
                && d->pDriveWheel[3]->CurrentSlip < K_UPSHIFT_SLIP
                && d->pDriveWheel[3]->TouchingGround) {
            d->DesiredGear = current + 1;
            return g;
        }

        if (rpm < down && !(current < FIRST_GEAR))
            d->DesiredGear = current - 1;

        return g;
    }

    if (g != SPORT_SHIFT) {
        d->DesiredGear = g;
        return g;
    }

    // ---- SPORT_SHIFT

    d->GearHoldTime += WorldTimeElapsed;

    if (d->CurrentClutchState != CLUTCH_ENGAGED)
        return g;

    e = d->pEngine;
    current = d->CurrentGear;
    rpm = e->State.w * DRIVETRAIN_RADS_TO_RPM;

    if (current < THIRD_GEAR) {
        if (e->Throttle < K_SHIFT_THROTTLE)
            down = e->EI->IdleRPM + K_CRAWL_OVER_IDLE;
        else
            down = 0.0f;
    } else {
        // Not the ShiftDownRPM table: the sport path asks whether the
        // engine would still be over the limiter in the gear below, at
        // gMaxDownShiftOver times MaxRPM.
        down = e->EI->MaxRPM * gMaxDownShiftOver
                   * d->DTI->GearRatios[current]
                   / d->DTI->GearRatios[current - 1];
    }

    if (d->DesiredGear != d->SportGear) {
        d->PreviousGear = current;

        if (d->SportGear < d->DesiredGear) {
            if (down < rpm) {
                // Too fast to drop a gear: refuse, and put the driver's
                // request back where it was.
                d->DesiredGear = current;
                d->GearHoldTime = 0.0f;
                d->SportGear = current;
                return g;
            }

            d->GearHoldTime = 0.0f;
            d->DesiredGear = current - 1;
            return g;
        }

        if (d->DesiredGear < d->SportGear) {
            d->GearHoldTime = 0.0f;
            d->DesiredGear = current + 1;
            return g;
        }

        // 0x00183b94. Unreachable: DesiredGear and SportGear are two
        // ints, they are not equal by the test above, and neither
        // ordering held. Ported because the image has it, and argued in
        // docs/formats/car-drivetrain.md rather than deleted.
        if (rpm < e->EI->IdleRPM + K_CRAWL_OVER_IDLE
                && !(current < THIRD_GEAR)) {
            d->DesiredGear = current - 1;
            return AUTOMATIC;
        }

        return g;
    }

    // The requested gear is in. Hand the driver back to the automatic
    // after ten seconds of not shifting...
    if (K_SPORT_HOLD < d->GearHoldTime)
        return AUTOMATIC;

    // ...or immediately, if they have shifted up into the limiter.
    if (d->PreviousGear < current
            && e->EI->MaxRPM - K_LIMITER_MARGIN < rpm)
        return AUTOMATIC;

    return g;
}

void drivetrain_print_current_state(const DriveTrain *d)
{
    (void)d;
}

// -------------------------------------------------------------- accessors

int32_t drivetrain_rear_wheel_drive(const DriveTrain *d)
{
    return K_SPLIT_LOW <= d->DTI->TorqueSplit;
}

int32_t drivetrain_front_wheel_drive(const DriveTrain *d)
{
    return d->DTI->TorqueSplit <= K_SPLIT_HIGH;
}

Gear drivetrain_get_top_gear(const DriveTrain *d)
{
    return d->DTI->NumGears + 1;
}

Gear drivetrain_get_desired_gear(const DriveTrain *d)
{
    return d->DesiredGear;
}

Gear drivetrain_get_previous_gear(const DriveTrain *d)
{
    return d->PreviousGear;
}

Gear drivetrain_get_sport_gear(const DriveTrain *d)
{
    return d->SportGear;
}

Gear drivetrain_get_current_gear(const DriveTrain *d)
{
    return d->CurrentGear;
}

int32_t drivetrain_is_clutch_engaged(const DriveTrain *d)
{
    return d->CurrentClutchState == CLUTCH_ENGAGED;
}

Engine *drivetrain_get_engine(const DriveTrain *d)
{
    return d->pEngine;
}

const DriveTrainInfo *drivetrain_get_drive_train_info(const DriveTrain *d)
{
    return d->DTI;
}

ClutchState drivetrain_get_current_clutch_state(const DriveTrain *d)
{
    return d->CurrentClutchState;
}

float drivetrain_get_shift_down_rpm(const DriveTrain *d, Gear g)
{
    return d->ShiftDownRPM[g];
}

float drivetrain_get_shift_up_rpm(const DriveTrain *d, Gear g)
{
    return d->ShiftUpRPM[g];
}

void drivetrain_set_state_gear(DriveTrain *d, Gear g)
{
    d->DesiredGear = g;
    d->State.clutch = 1.0f;
    d->CurrentClutchState = CLUTCH_ENGAGED;
    d->CurrentGear = g;
}

void drivetrain_set_state_array(DriveTrain *d, const float *in)
{
    d->State.clutch = in[0];
}

void drivetrain_get_state_array(const DriveTrain *d, float *out)
{
    out[0] = d->State.clutch;
}

DriveTrainState *drivetrain_get_state(DriveTrain *d)
{
    return &d->State;
}

int32_t drivetrain_get_size(const DriveTrain *d)
{
    (void)d;

    return DRIVETRAIN_STATE_FLOATS;
}

// ---------------------------------------------------------------- the replay

// 0x0018af10. The gears and the clutch state go in through MoveData(void *)
// rather than the int overload: four bytes each, unsigned.
void drivetrain_do_snapshot(DriveTrain *d, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "DriveTrain");
    ReplaySnapshot_MoveFloat(s, &d->State.clutch);
    ReplaySnapshot_MoveData(s, &d->DesiredGear, 4, -1, 0);
    ReplaySnapshot_MoveData(s, &d->SportGear, 4, -1, 0);
    ReplaySnapshot_MoveData(s, &d->PreviousGear, 4, -1, 0);
    ReplaySnapshot_MoveData(s, &d->CurrentGear, 4, -1, 0);
    ReplaySnapshot_MoveData(s, &d->CurrentClutchState, 4, -1, 0);
    ReplaySnapshot_MoveInt(s, &d->Shifting, 4);
    ReplaySnapshot_MoveFloat(s, &d->DifferentialAngularVelocity);
    ReplaySnapshot_MoveFloat(s, &d->GearHoldTime);
    ReplaySnapshot_MoveFloat(s, &d->ShiftUpRPM[0]);
    ReplaySnapshot_EndNamedSection(s);
}
