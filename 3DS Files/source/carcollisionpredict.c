// carcollisionpredict -- see carcollisionpredict.h.
//
// Written from retail's listing. Every float expression keeps the image's
// association: the radii's three-term sums are `(a + b) + c`, and the
// steps along a leg are `(step * speed) / length`.

#include "carcollisionpredict.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "aicarcontroller.h"
#include "bmath.h"
#include "cardriver.h"
#include "drivetarget.h"
#include "drivingchoice.h"   // AITrafficTuningMode
#include "drivinglocation.h"
#include "eefpu.h"
#include "nearbycar.h"
#include "world.h"

// Retail's constants: CarCollisionPredict.obj's .lit4 from gp-28120 to
// gp-28052, and the few built with `lui`.
#define CCP_NO_HIT          99999.0f     // gp-28120, -28108, -28080
#define CCP_NOT_YET         1234.0f      // gp-28116, never read
#define CCP_STILL           0.00100000005f  // gp-28112, -28088
#define CCP_TRAFFIC_SCALE   1.29999995f  // gp-28104, -28100
#define CCP_BACKING_SCALE   1.29999995f  // gp-28096, -28092
#define CCP_LEG_DONE        0.00100000005f  // gp-28084
#define CCP_SAME            0.00100000005f  // gp-28076
#define CCP_AXIS_STILL      9.99999975e-05f // gp-28072
#define CCP_NEVER           9999.0f      // gp-28068, -28060
#define CCP_ALWAYS         -9999.0f      // gp-28064
#define CCP_NO_OVERLAP      99999.0f     // gp-28056, -28052
#define CCP_STOPPED_SPEED   5.0f         // lui 0x40a0
#define CCP_STOPPED_AHEAD   23.0f        // lui 0x41b8
#define CCP_ON_ROAD        -0.25f        // lui 0xbe80
#define CCP_SLOW            2.0f         // lui 0x4000
#define CCP_TUNING_SCALE    1000.0f      // lui 0x447a
#define CCP_MAX_POINTS      20

// `max.s`, fs then ft, as collision.c has it.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// The type of a car's current action, NONE with none. Only for a car
// under AI control: nothing checks.
static AIActionType action_type(Car *c)
{
    AIAction *a = car_ai_controller(c)->CurrentAction;

    return a == NULL ? AIACTION_NONE : a->Type;
}

// A car backing up whose action is no help (getting unstuck, none, or
// recovering from an accident) or whose target is empty.
static int backing_blind(Car *c, const DriveTarget *t)
{
    AIActionType type = action_type(c);

    return type == AIACTION_GET_UNSTUCK || type == AIACTION_NONE
           || type == AIACTION_ACCIDENT_RECOVERY || t->NumPoints == 0;
}

Car *ccp_who_will_this_drive_target_hit(DriveTarget *t, NearbyCarList *list,
                                        DrivingLocation *loc, float maxTime,
                                        float *when)
{
    float best = CCP_NO_HIT;
    Car *hit = NULL;
    Car *exclude;
    int k;

    if (loc == NULL || drivinglocation_is_clear(loc))
        return NULL;
    if (t->NumPoints <= 0 || !(t->NumPoints < CCP_MAX_POINTS + 1))
        return NULL;

    exclude = car_ai_controller(list->MyCar)
                  ->CarToExcludeFromCollisionPrediction;
    for (k = 0; k < list->NumCarsInArray; k++) {
        NearbyCar *nc = &list->Array[k];
        float its = CCP_NOT_YET;
        int r;

        if (!ai_do_we_care_about_this_car(nc, list))
            continue;
        if (ccp_is_this_car_stopped_directly_in_front_of_me(nc, list)) {
            its = 0.0f;
            r = 1;
        } else if (fabsf(list->MyCar->State.VelocityMagnitude) <= CCP_STILL
                   || nc->TheCar == exclude) {
            r = 0;
        } else {
            r = ccp_will_i_hit_this_car(t, loc, list->MyCar, nc->TheCar,
                                        maxTime, &its);
        }
        if (r && its < best) {
            hit = nc->TheCar;
            best = its;
        }
        // 0x0014e568, inlined nowhere else.
        pCurrentWorld->CollisionPredictionID++;
    }
    *when = best;
    return hit;
}

int ccp_is_this_car_stopped_directly_in_front_of_me(NearbyCar *nc,
                                                    NearbyCarList *list)
{
    if (!(fabsf(nc->TheCar->State.VelocityMagnitude) <= CCP_STOPPED_SPEED))
        return 0;
    return fabsf(nc->Position.x) < list->MyHalfSizeL + nc->ApparentHalfSizeL
           && nc->Position.y < (list->MyHalfSizeD + nc->ApparentHalfSizeD)
                                   + CCP_STOPPED_AHEAD;
}

// Retail keeps these on its stack (4720 bytes in all). The 3DS's main
// stack is 32KB and nothing here recurses or runs off the main thread, so
// they are static.
static DriveTarget s_mine, s_its;
static OBB         s_my_obbs[CCP_MAX_POINTS], s_its_obbs[CCP_MAX_POINTS];

int ccp_will_i_hit_this_car(DriveTarget *t, DrivingLocation *loc, Car *me,
                            Car *other, float maxTime, float *when)
{
    float hit = CCP_NO_HIT, elapsed;
    float myScale, itsScale, mySpeed, itsSpeed, myV0, itsV0;
    bVector2 myPos, itsPos;
    int i, j, k, r;

    (void)loc;
    drivetarget_copy(&s_mine, t);
    drivetarget_copy(&s_its, &other->pCarDriver->MyDriveTarget);

    // Traffic on the road follows where its acceleration takes it; the
    // rest blend that into their targets. Another car's target is left as
    // it is unless the car is traffic, and then blended only when its
    // action is not just driving.
    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
        && CCP_ON_ROAD < car_get_amount_out_of_bounds(me))
        drivetarget_fill_with_current_acceleration(&s_mine, me);
    else
        drivetarget_blend_with_current_acceleration(&s_mine, me);
    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {
        if (CCP_ON_ROAD < car_get_amount_out_of_bounds(other))
            drivetarget_fill_with_current_acceleration(&s_its, other);
        else if (action_type(other) != AIACTION_JUST_DRIVE)
            drivetarget_blend_with_current_acceleration(&s_its, other);
    }

    myScale = 1.0f;
    itsScale = 1.0f;
    if (me->TheControlMode == TRAFFIC_CONTROL)
        myScale = CCP_TRAFFIC_SCALE;
    if (other->TheControlMode == TRAFFIC_CONTROL)
        itsScale = CCP_TRAFFIC_SCALE;
    myV0 = mySpeed = me->State.VelocityMagnitude;
    itsV0 = itsSpeed = other->State.VelocityMagnitude;

    // A car backing up with nothing better to go on is taken straight
    // along its velocity, in a wider box.
    if (me->State.ForwardSpeed < 0.0f && backing_blind(me, &s_mine)) {
        ai_straight_line_predict(me, &s_mine);
        mySpeed = fabsf(myV0);
        myScale = CCP_BACKING_SCALE;
    }
    if (other->State.ForwardSpeed < 0.0f
        && (other->TheControlMode == AI_CONTROL
            || other->TheControlMode == TRAFFIC_CONTROL)
        && backing_blind(other, &s_its)) {
        ai_straight_line_predict(other, &s_its);
        itsSpeed = fabsf(itsV0);
        itsScale = CCP_BACKING_SCALE;
    }

    mySpeed = max_s(mySpeed, CCP_STILL);
    itsSpeed = max_s(itsSpeed, CCP_STILL);
    if (mySpeed < CCP_SLOW)
        myScale = 1.0f;
    if (itsSpeed < CCP_SLOW)
        itsScale = 1.0f;
    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
        && AITrafficTuningMode != 0)
        myScale = CCP_TUNING_SCALE;

    for (k = 0; k < CCP_MAX_POINTS; k++)
        obb_init(&s_my_obbs[k]);
    for (k = 0; k < CCP_MAX_POINTS; k++)
        obb_init(&s_its_obbs[k]);
    elapsed = 0.0f;
    ccp_make_obbs_for_drive_target(&s_mine, s_my_obbs, me, myScale);
    ccp_make_obbs_for_drive_target(&s_its, s_its_obbs, other, itsScale);
    i = drivetarget_get_first_point(&s_mine, &me->State);
    j = drivetarget_get_first_point(&s_its, &other->State);
    myPos.x = me->State.Position.x;
    myPos.y = me->State.Position.y;
    itsPos.x = other->State.Position.x;
    itsPos.y = other->State.Position.y;

    // One step to whichever car reaches its next point first. The image
    // keeps each car's next point in a local and reloads it from the box
    // past the one it leaves, before testing the index: past the last
    // box, a word it never uses. The port reads the box at the top of the
    // pass, once the index has been tested.
    while (i < s_mine.NumPoints && j < s_its.NumPoints
           && elapsed <= maxTime) {
        const bVector3 *myTo = &s_my_obbs[i].Position;
        const bVector3 *itsTo = &s_its_obbs[j].Position;
        bVector2 myLeg, itsLeg, myVel, itsVel;
        bVector3 d, v;
        float myLen, itsLen, myTime, itsTime, step, fm, fi, at;

        myLeg.x = myTo->x - myPos.x;
        myLeg.y = myTo->y - myPos.y;
        itsLeg.x = itsTo->x - itsPos.x;
        itsLeg.y = itsTo->y - itsPos.y;
        myLen = sqrtf(myLeg.x * myLeg.x + myLeg.y * myLeg.y);
        itsLen = sqrtf(itsLeg.x * itsLeg.x + itsLeg.y * itsLeg.y);
        itsTime = itsLen / itsSpeed;
        myTime = myLen / mySpeed;
        step = myTime < itsTime ? myTime : itsTime;

        d.x = itsPos.x - myPos.x;
        d.y = itsPos.y - myPos.y;
        d.z = 0.0f;
        d.pad = 0.0f;
        myVel = myLeg;
        itsVel = itsLeg;
        bNormalize2To(&myVel, &myVel, mySpeed);
        bNormalize2To(&itsVel, &itsVel, itsSpeed);
        v.x = itsVel.x - myVel.x;
        v.y = itsVel.y - myVel.y;
        v.z = 0.0f;
        v.pad = 0.0f;

        at = ccp_when_will_overlap_occur_2d(&s_my_obbs[i], &s_its_obbs[j],
                                            &d, &v);
        if (at <= step) {
            hit = elapsed + at;
            break;
        }

        // ee_div: a car already at its next point has a leg of 0, and the
        // EE's FLT_MAX times the 0 still to go leaves it where it is,
        // where IEEE's 0/0 would be a NaN.
        fm = ee_div(step * mySpeed, myLen);
        fi = ee_div(step * itsSpeed, itsLen);
        myPos.x = myPos.x + (myTo->x - myPos.x) * fm;
        itsPos.y = itsPos.y + (itsTo->y - itsPos.y) * fi;
        itsPos.x = itsPos.x + (itsTo->x - itsPos.x) * fi;
        myPos.y = myPos.y + (myTo->y - myPos.y) * fm;
        if (fabsf(myTime - step) <= CCP_LEG_DONE)
            i++;
        else
            j++;
        elapsed = elapsed + step;
    }

    *when = hit;
    r = hit < CCP_NO_HIT && !(fabsf(hit - CCP_NO_HIT) <= CCP_SAME);

    for (k = CCP_MAX_POINTS - 1; k >= 0; k--)
        obb_destroy(&s_its_obbs[k]);
    for (k = CCP_MAX_POINTS - 1; k >= 0; k--)
        obb_destroy(&s_my_obbs[k]);
    drivetarget_destroy(&s_its);
    drivetarget_destroy(&s_mine);
    return r;
}

void ccp_make_obbs_for_drive_target(DriveTarget *t, OBB *obbs, Car *car,
                                    float scale)
{
    bVector3 lo, hi;
    float h0, h1, h2, s, c;
    int i;

    if (t == NULL || t->NumPoints <= 0 || obbs == NULL || car == NULL)
        return;

    car_get_car_space_bounding_box(car, &lo, &hi);
    h0 = fabsf((hi.x - lo.x) * 0.5f) * scale;
    h1 = fabsf((hi.y - lo.y) * 0.5f) * scale;
    h2 = fabsf((hi.z - lo.z) * 0.5f) * scale;

    s = 0.0f;
    c = 0.0f;
    bSinCos(&s, &c, car->State.Angle);
    obbs[0].A0.x = c;
    obbs[0].A0.y = s;
    obbs[0].A0.pad = 0.0f;
    obbs[0].A0.z = 0.0f;
    obbs[0].A1.x = -s;
    obbs[0].A1.y = c;
    obbs[0].A1.pad = 0.0f;
    obbs[0].A1.z = 0.0f;
    obbs[0].A2.x = 0.0f;
    obbs[0].A2.pad = 0.0f;
    obbs[0].A2.z = 1.0f;
    obbs[0].A2.y = 0.0f;
    obbs[0].a0 = h0;
    obbs[0].a1 = h1;
    obbs[0].a2 = h2;
    obbs[0].Position = t->Points[0];

    // Each later box lies along the leg back to the point before it.
    // NumPoints is read again on every pass, as the image does.
    for (i = 1; i < t->NumPoints; i++) {
        bVector2 dir;
        OBB *o = &obbs[i];

        dir.y = t->Points[i - 1].y - t->Points[i].y;
        dir.x = t->Points[i - 1].x - t->Points[i].x;
        bNormalize2(&dir, &dir);
        o->A0.y = dir.y;
        o->A0.pad = 0.0f;
        o->A0.z = 0.0f;
        o->A0.x = dir.x;
        o->A1.pad = 0.0f;
        o->A1.y = dir.x;
        o->A1.z = 0.0f;
        o->A1.x = -dir.y;
        o->A2.z = 1.0f;
        o->A2.pad = 0.0f;
        o->A2.x = 0.0f;
        o->A2.y = 0.0f;
        o->a0 = h0;
        o->a1 = h1;
        o->a2 = h2;
        o->Position = t->Points[i];
    }
}

float ccp_when_will_overlap_occur_2d(OBB *a, OBB *b, const bVector3 *d,
                                     const bVector3 *v)
{
    // The cosines between the two boxes' axes: cAB is a's axis A against
    // b's axis B.
    float c10 = a->A1.x * b->A0.x + a->A1.y * b->A0.y;
    float c00 = a->A0.x * b->A0.x + a->A0.y * b->A0.y;
    float c11 = a->A1.x * b->A1.x + a->A1.y * b->A1.y;
    float c01 = a->A0.x * b->A1.x + a->A0.y * b->A1.y;
    // Each axis' reach: its own box's half size and the other's shadow.
    float rA1 = (fabsf(a->a1) + fabsf(b->a0 * c10)) + fabsf(b->a1 * c11);
    float rA0 = (fabsf(a->a0) + fabsf(b->a0 * c00)) + fabsf(b->a1 * c01);
    float rB1 = (fabsf(b->a1) + fabsf(a->a0 * c01)) + fabsf(a->a1 * c11);
    float rB0 = (fabsf(b->a0) + fabsf(a->a0 * c00)) + fabsf(a->a1 * c10);
    float in[8], lo, hi;

    ccp_time_interval_for_separating_axis(
        v->x * a->A1.x + v->y * a->A1.y, d->x * a->A1.x + d->y * a->A1.y,
        rA1, &in[0], &in[1]);
    ccp_time_interval_for_separating_axis(
        v->x * a->A0.x + v->y * a->A0.y, d->x * a->A0.x + d->y * a->A0.y,
        rA0, &in[2], &in[3]);
    ccp_time_interval_for_separating_axis(
        v->x * b->A1.x + v->y * b->A1.y, d->x * b->A1.x + d->y * b->A1.y,
        rB1, &in[4], &in[5]);
    ccp_time_interval_for_separating_axis(
        v->x * b->A0.x + v->y * b->A0.y, d->x * b->A0.x + d->y * b->A0.y,
        rB0, &in[6], &in[7]);

    if (!ccp_interval_overlap(in[0], in[1], in[2], in[3], &lo, &hi)
        || !ccp_interval_overlap(lo, hi, in[4], in[5], &lo, &hi)
        || !ccp_interval_overlap(lo, hi, in[6], in[7], &lo, &hi)) {
        lo = CCP_NO_OVERLAP;
        hi = CCP_NO_OVERLAP;
    }

    if (0.0f < lo)
        return lo;
    if (lo < 0.0f && 0.0f < hi)
        return 0.0f;
    return CCP_NO_OVERLAP;
}

void ccp_time_interval_for_separating_axis(float v, float d, float r,
                                           float *tmin, float *tmax)
{
    if (fabsf(v) < CCP_AXIS_STILL) {
        if (r < fabsf(d)) {
            *tmin = CCP_NEVER;
            *tmax = CCP_NEVER;
        } else {
            *tmin = CCP_ALWAYS;
            *tmax = CCP_NEVER;
        }
        return;
    }
    *tmax = (r - d) / v;
    *tmin = -(r + d) / v;
    if (v < 0.0f) {
        float lo = *tmin;

        *tmin = *tmax;
        *tmax = lo;
    }
}

int ccp_interval_overlap(float a0, float a1, float b0, float b1, float *lo,
                         float *hi)
{
    float e[4];
    int n, k;

    e[0] = a0;
    e[1] = a1;
    e[2] = b0;
    e[3] = b1;
    // A bubble sort, three passes.
    for (n = 3; n > 0; n--) {
        for (k = 0; k < n; k++) {
            if (e[k + 1] < e[k]) {
                float x = e[k];

                e[k] = e[k + 1];
                e[k + 1] = x;
            }
        }
    }
    if (a0 <= e[1] && e[1] <= a1 && b0 <= e[1] && e[1] <= b1) {
        *lo = e[1];
        *hi = e[2];
        return 1;
    }
    return 0;
}
