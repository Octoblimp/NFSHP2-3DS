// aiaction -- see aiaction.h.
//
// Written from retail's listing. Every float expression keeps the image's
// association, and each virtual call reloads the vptr as the image does.

#include "aiaction.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "bmath.h"
#include "bmem.h"
#include "bvector.h"
#include "cardriver.h"
#include "drivetargetrenderer.h"
#include "eefpu.h"
#include "realtime.h"   // WorldTimer
#include "replay.h"
#include "vtable.h"

// Retail's constants: AIAction.obj's .lit4 from gp-28764 to gp-28740, and
// the few built with `lui`.
#define AIA_MIN_TIME_TO_SPEED   0.100000001f  // gp-28764
#define AIA_LOOK_AHEAD_SECONDS  0.100000001f  // gp-28760
#define AIA_EDGE_RATE_MIN       0.00100000005f  // gp-28756, gp-28748
#define AIA_NO_EDGE             99999.0f      // gp-28752
#define AIA_BACKWARDS_COS       0.342000008f  // gp-28744, cos 70 degrees
#define AIA_BOX_SHARE           0.949999988f  // gp-28740
#define AIA_MOVING_SPEED        1.0f          // lui 0x3f80
#define AIA_RATE_SCALE          10.0f         // lui 0x4120, 1 / 0.1 s
#define AIA_EDGE_SOON           1.0f          // lui 0x3f80
#define AIA_SLOW_LOOK_AHEAD     2.0f          // lui 0x4000
#define AIA_STEER_AHEAD         0.5f          // lui 0x3f00
#define AIA_TICKS_TO_SECONDS    0.000250000012f  // gp-28528
#define AIA_SECONDS_TO_TICKS    4000.0f       // lui 0x457a

BSlotPool *AIActionSlotPool;
int32_t    AIActionJustDriveScore;

// `max.s`, fs then ft, as collision.c has it.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// ---------------------------------------------------------------- AIPlan

void ai_init_ai_plans(void)
{
    // 0x001c6028.
    AIActionSlotPool = bNewSlotPool(AIACTION_SLOT_SIZE, AIACTION_SLOTS,
                                    "AIActionSlotPool", 16);
}

void ai_close_ai_plans(void)
{
    // 0x001c6058.
    if (AIActionSlotPool != NULL) {
        bDeleteSlotPool(AIActionSlotPool);
        AIActionSlotPool = NULL;
    }
    drivetargetrenderer_destroy_target_markers(&TheDriveTargetRenderer);
}

AIPlan *aiplan_init(AIPlan *p, float timeout)
{
    // 0x001cac70. ExpiryTimer's own constructor, then the vptr in
    // SetTimeout's delay slot.
    p->ExpiryTimer.PackedTime = 0;
    p->_vtable = AIPLAN_VTABLE;
    aiplan_set_timeout(p, timeout);
    return p;
}

void aiplan_destroy(AIPlan *p, int32_t flags)
{
    // 0x001cac48. `j __builtin_delete`, which is bFree on the general heap.
    p->_vtable = AIPLAN_VTABLE;
    if (flags & 1)
        bFree(p);
}

void aiplan_set_timeout(AIPlan *p, float timeout)
{
    // 0x001cab90. `c.le.s` 0 against the timeout: -0 can expire.
    p->CanExpire = 0.0f <= timeout;
    p->DeltaTime = timeout;
    p->ExpiryTimer.PackedTime = (uint32_t)ee_trunc_w(
        ((float)WorldTimer * AIA_TICKS_TO_SECONDS) * AIA_SECONDS_TO_TICKS
        + 0.5f);
}

int aiplan_time_to_change(const AIPlan *p)
{
    // 0x001cab48.
    if (p == NULL)
        return 1;
    if (p->Status == STATUS_SUCCESS || p->Status == STATUS_FAILURE)
        return 1;
    return p->Status == STATUS_EXPIRED && p->CanExpire != 0;
}

PlanStatus aiplan_get_status(const AIPlan *p)
{
    // 0x001cabf0.
    return p->Status;
}

int aiplan_is_not_done(const AIPlan *p)
{
    // 0x001cabf8.
    return p->Status == STATUS_NOT_DONE;
}

int aiplan_failure(const AIPlan *p)
{
    // 0x001cac08.
    return p->Status == STATUS_FAILURE;
}

int aiplan_success(const AIPlan *p)
{
    // 0x001cac18.
    return p->Status == STATUS_SUCCESS;
}

int aiplan_is_expired(const AIPlan *p)
{
    // 0x001cac28.
    return p->Status == STATUS_EXPIRED && p->CanExpire != 0;
}

// -------------------------------------------------------------- AIAction

AIAction *aiaction_init(AIAction *a, int32_t score, float timeout)
{
    // 0x001c6118. AIPlan's constructor inline; Status is the one field it
    // leaves, and this sets it.
    a->Base.ExpiryTimer.PackedTime = 0;
    a->Base._vtable = AIPLAN_VTABLE;
    aiplan_set_timeout(&a->Base, timeout);
    a->Base._vtable = AIACTION_VTABLE;
    drivetarget_init(&a->PointsToDrive);
    a->Score = score;
    a->AllowedToUseThrottleAndBrake = 1;
    a->Base.Status = STATUS_NOT_DONE;
    a->DesiredSpeed = 0.0f;
    a->DesiredSpeedTolerance = 0.0f;
    a->TimeToGetToDesiredSpeed = 0.0f;
    a->UseDrivingLineSpeed = 1;
    a->AllowedToUseBoost = 1;
    return a;
}

void aiaction_destroy(AIAction *a, int32_t flags)
{
    // 0x001c6b30. Retail passes PointsToDrive's destructor 2, which only
    // says not to delete it.
    a->Base._vtable = AIACTION_VTABLE;
    drivetarget_destroy(&a->PointsToDrive);
    aiplan_destroy(&a->Base, 0);
    if (flags & 1)
        aiaction_delete(a);
}

void *aiaction_new(void)
{
    // 0x001cab08 and 0x001cab28: bOMalloc, the full path.
    return bSlotOMalloc(AIActionSlotPool);
}

void aiaction_delete(void *p)
{
    // 0x001caaf8.
    bSlotFree(AIActionSlotPool, p);
}

typedef int (*AIActionTestFn)(void *self, DrivingInformation *info);

void aiaction_update_status(AIAction *a, DrivingInformation *info)
{
    // 0x001c6a98. Later answers win: an action that has both failed and
    // been accomplished has succeeded.
    const VtEntry *e;

    a->Base.Status = STATUS_NOT_DONE;
    e = vt_slot(a->Base._vtable, AIACTION_VT_HAS_EXPIRED);
    if (((AIActionTestFn)e->fn)(vt_this(a, e), info))
        a->Base.Status = STATUS_EXPIRED;
    e = vt_slot(a->Base._vtable, AIACTION_VT_HAS_FAILED);
    if (((AIActionTestFn)e->fn)(vt_this(a, e), info))
        a->Base.Status = STATUS_FAILURE;
    e = vt_slot(a->Base._vtable, AIACTION_VT_HAS_BEEN_ACCOMPLISHED);
    if (((AIActionTestFn)e->fn)(vt_this(a, e), info))
        a->Base.Status = STATUS_SUCCESS;
}

void aiaction_set_desired_speed_slower_than_this_car(AIAction *a,
                                                     NearbyCar *nc,
                                                     NearbyCarList *list,
                                                     float delta,
                                                     float unused)
{
    // 0x001c64e8. Retail stores the speed before the clamp and again
    // after it. The gap is closed at the car's apparent closing speed, and
    // a car keeping pace divides by zero (0x001c6520): the EE's FLT_MAX
    // there makes the time FLT_MAX or 0.1, where IEEE's infinity or NaN
    // would leave it infinite or NaN.
    float speed = nc->TheCar->State.VelocityMagnitude - delta;
    float gap;

    (void)unused;
    a->DesiredSpeed = speed;
    a->DesiredSpeed = max_s(speed, 0.0f);
    gap = (nc->Position.y - list->MyHalfSizeD) - nc->ApparentHalfSizeD;
    a->TimeToGetToDesiredSpeed = max_s(ee_div(gap, nc->Velocity.y),
                                       AIA_MIN_TIME_TO_SPEED);
}

void aiaction_set_desired_speed_to_max_acceleration(AIAction *a, Car *car,
                                                    float t)
{
    // 0x001c6530.
    float v = car->State.VelocityMagnitude;
    float accel = ai_calculate_max_acceleration(car, v);

    a->TimeToGetToDesiredSpeed = t;
    a->DesiredSpeed = v + accel * t;
}

void aiaction_set_desired_speed_to_max_deceleration(AIAction *a, Car *car,
                                                    float t)
{
    // 0x001c6588.
    float v = car->State.VelocityMagnitude;
    float decel = ai_calculate_max_deceleration(car, v);

    a->TimeToGetToDesiredSpeed = t;
    a->DesiredSpeed = v + decel * t;
}

// How far `p` is to the left of the route point's line, across its
// direction: `(p.x - rp.x) * dir.y - (p.y - rp.y) * dir.x`.
static float lateral(const bVector2 *p, const TrackRoutePoint *rp)
{
    return (p->x - rp->Position.x) * rp->Direction.y
           - (p->y - rp->Position.y) * rp->Direction.x;
}

typedef bVector2 *(*CarDriverPointFn)(void *self);

static bVector2 *steer_to_point(Car *car)
{
    CarDriver *d = car->pCarDriver;
    const VtEntry *e = vt_slot(d->_vtable, CARDRIVER_VT_GET_STEER_TO_POINT);

    return ((CarDriverPointFn)e->fn)(vt_this(d, e));
}

HeadingClassification aiaction_get_heading_classification(
    DrivingLocation *loc, Car *car, int steer_check)
{
    // 0x001c65e0.
    const TrackRoutePoint *rp = loc->pRoutePoint;
    HeadingClassification r = HEADING_OKAY;
    bVector2 pos, ahead, dir;
    float lat_now, lat_ahead, l_now, r_now, l_ahead, r_ahead;

    pos.x = car->State.Position.x;
    pos.y = car->State.Position.y;

    if (AIA_MOVING_SPEED < fabsf(car->State.VelocityMagnitude)) {
        // Moving: where the car will be in 0.1 s, and how fast its left
        // edge distance grows.
        bVector2 vel;
        float rate, t = AIA_NO_EDGE;
        int out = 0;

        vel.x = car->State.Velocity.x;
        vel.y = car->State.Velocity.y;
        bScaleAdd2(&ahead, &pos, &vel, AIA_LOOK_AHEAD_SECONDS);
        lat_ahead = lateral(&ahead, rp);
        lat_now = lateral(&pos, rp);
        l_ahead = rp->LeftWidth + lat_ahead;
        r_ahead = rp->RightWidth - lat_ahead;
        l_now = rp->LeftWidth + lat_now;
        r_now = rp->RightWidth - lat_now;
        rate = (l_ahead - l_now) * AIA_RATE_SCALE;

        // Seconds to the right edge for a car on the road drifting right.
        // Retail's second test (0x001c6718) asks the same three things
        // with the left distance on top, so it is never taken, and a car
        // drifting left is never timed; it is left out.
        if (AIA_EDGE_RATE_MIN < rate && 0.0f < r_now && 0.0f < l_now)
            t = r_now / rate;

        if (t <= AIA_EDGE_SOON)
            out = 1;
        else if (r_now < 0.0f && r_ahead < r_now)
            out = 1;
        else if (l_now < 0.0f && l_ahead < l_now)
            out = 1;
        if (out)
            r = 0.0f < car->State.ForwardSpeed
                    ? HEADING_OUT_OF_ROUTE_FORWARDS
                    : HEADING_OUT_OF_ROUTE_BACKWARDS;
    } else {
        // Barely moving: 2 m ahead along the way the car points. Retail
        // asks bCos and then bSin.
        dir.x = bCosBam(car->State.Angle);
        dir.y = bSinBam(car->State.Angle);
        bScaleAdd2(&ahead, &pos, &dir, AIA_SLOW_LOOK_AHEAD);
        lat_ahead = lateral(&ahead, rp);
        l_ahead = rp->LeftWidth + lat_ahead;
        r_ahead = rp->RightWidth - lat_ahead;
        lat_now = lateral(&pos, rp);
        l_now = rp->LeftWidth + lat_now;
        r_now = rp->RightWidth - lat_now;
        if (r_ahead < 0.0f && r_ahead - r_now < 0.0f)
            r = HEADING_OUT_OF_ROUTE_FORWARDS;
        else if (l_ahead < 0.0f && l_ahead - l_now < 0.0f)
            r = HEADING_OUT_OF_ROUTE_FORWARDS;
    }

    if (r == HEADING_OUT_OF_ROUTE_FORWARDS && steer_check) {
        // Retail asks the driver twice. The first answer goes through
        // WorldToCar into a stack copy that nothing reads.
        bVector2 local = *steer_to_point(car);

        car_world_to_car(car, &local, &local);
        if (ai_is_point_ahead_of_car(steer_to_point(car), car,
                                     AIA_STEER_AHEAD))
            r = HEADING_OKAY;
    }
    if (r == HEADING_OUT_OF_ROUTE_BACKWARDS) {
        bVector2 body, route, n_body, n_route;

        body.x = car->State.BodyMatrix.v0.x;
        body.y = car->State.BodyMatrix.v0.y;
        route.x = rp->Direction.x;
        route.y = rp->Direction.y;
        bNormalize2(&n_body, &body);
        bNormalize2(&n_route, &route);
        if (AIA_BACKWARDS_COS
            < n_body.x * n_route.x + n_body.y * n_route.y)
            r = HEADING_OKAY;
    }
    return r;
}

CollisionClassification aiaction_get_collision_classification(
    Collision *coll, Car *car)
{
    // 0x001c69d8. The contact point's x, across the car, is held against
    // the box's y, along it: retail's own mix.
    bVector3 min, max;
    bVector2 contact, local;

    car_get_car_space_bounding_box(car, &min, &max);
    contact.x = coll->CurrentContactPoint.x;
    contact.y = coll->CurrentContactPoint.y;
    car_world_to_car(car, &local, &contact);
    if (local.x < max.y * AIA_BOX_SHARE && min.y * AIA_BOX_SHARE < local.x)
        return 0.0f < local.y ? COLLISION_IN_FRONT : COLLISION_BEHIND;
    return 0.0f < local.x ? COLLISION_RIGHT_SIDE : COLLISION_LEFT_SIDE;
}

void aiaction_clear_points_to_drive(AIAction *a)
{
    // 0x001caa60.
    drivetarget_clear(&a->PointsToDrive, NULL, 0.0f);
}

const char *aiaction_get_name(AIAction *a)
{
    // 0x001caae0, an empty string at 0x00331170.
    (void)a;
    return "";
}

// ------------------------------------------------------------- the replay

void aiplan_do_snapshot(AIPlan *p, ReplaySnapshot *s)
{
    // 0x001c6088. Status goes as its low byte.
    ReplaySnapshot_BeginNamedSection(s, "AIPlan");
    ReplaySnapshot_MoveBool(s, &p->CanExpire, 1);
    ReplaySnapshot_MoveData(s, &p->ExpiryTimer, 4, -1, 0);
    ReplaySnapshot_MoveFloat(s, &p->DeltaTime);
    ReplaySnapshot_MoveData(s, &p->Status, 1, -1, 0);
    ReplaySnapshot_EndNamedSection(s);
}

void aiaction_do_snapshot(AIAction *a, ReplaySnapshot *s)
{
    // 0x001c6198. The tolerance before the time, and the permissions out
    // of order; Type is the pointer's to save.
    ReplaySnapshot_BeginNamedSection(s, "AIAction");
    drivetarget_do_snapshot(&a->PointsToDrive, s);
    ReplaySnapshot_MoveFloat(s, &a->DesiredSpeed);
    ReplaySnapshot_MoveFloat(s, &a->DesiredSpeedTolerance);
    ReplaySnapshot_MoveFloat(s, &a->TimeToGetToDesiredSpeed);
    ReplaySnapshot_MoveBool(s, &a->UseDrivingLineSpeed, 1);
    ReplaySnapshot_MoveBool(s, &a->AllowedToUseBoost, 1);
    ReplaySnapshot_MoveBool(s, &a->PointsToDriveWillExecuteAction, 1);
    ReplaySnapshot_MoveBool(s, &a->AllowedToUseThrottleAndBrake, 1);
    ReplaySnapshot_MoveInt(s, &a->Score, 4);
    aiplan_do_snapshot(&a->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$6AIPlan, retail 0x002b7cd0.
static const VtEntry aiplan_vt[AIPLAN_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiplan_destroy),                      //   8  0x001cac48
    E(aiplan_do_snapshot),                  //  16  0x001c6088
};

// _vt$8AIAction, retail 0x002b7c90. `__pure_virtual` at 24, 40, 48 and
// 56.
static const VtEntry aiaction_vt[AIACTION_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aiaction_destroy),                    //   8  0x001c6b30
    E(aiaction_do_snapshot),                //  16  0x001c6198
    { 0, 0, NULL },                         //  24  CalculatePointsToDrive
    E(aiaction_get_name),                   //  32  0x001caae0
    { 0, 0, NULL },                         //  40  HasBeenAccomplished
    { 0, 0, NULL },                         //  48  HasFailed
    { 0, 0, NULL },                         //  56  HasExpired
};

#undef E

void aiaction_install_vtables(void)
{
    vt_install(AIPLAN_VTABLE, aiplan_vt, AIPLAN_VT_ENTRIES);
    vt_install(AIACTION_VTABLE, aiaction_vt, AIACTION_VT_ENTRIES);
}
