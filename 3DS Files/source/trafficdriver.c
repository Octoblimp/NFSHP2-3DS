// trafficdriver -- see trafficdriver.h and docs/formats/traffic-driver.md.
#include "trafficdriver.h"

#include "aiaction.h"
#include "aiactions.h"
#include "aidriver.h"   // the actions' scores, lifetimes and timeouts
#include "bmem.h"
#include "bvector.h"
#include "car.h"
#include "cardriver.h"
#include "carmodes.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "drivingchoice.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "psychodriver.h"
#include "realtime.h"   // WorldLoopCounter, WorldTimer
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// The constructor's first think, -1/70 s for each car's index (gp-30032),
// and Think's 0.2 s between thinks (gp-30028).
#define TD_THINK_STAGGER  (-0.0142857153f)
#define TD_THINK_INTERVAL 0.200000003f

// A traffic car thinks on the odd frames of twelve, the half its place
// among the traffic.
#define TD_TURNS 12

// gp-30024: a tick in seconds. GetUnstuck waits 2 s since the last
// (`lui 0x4000`).
#define TD_TICKS_TO_SECONDS 0.000250000012f
#define TD_UNSTUCK_WAIT     2.0f

// The actions' lifetimes but GetUnstuck's, IJustGotHit's and AvoidCars',
// and GetUnstuck's minimum lifetime (`lui 0xbf80`).
#define TD_NO_LIFETIME (-1.0f)

// CalculateDesiredSpeed. The most (gp-30020); the hairpin scan's 75 m
// (`lui 0x4296`) and 18.75 points (`lui 0x4196`, through `cvt.w.s`: 18,
// counted from 0); a hairpin's 0.32782 m/s a metre (gp-30016) and its
// route taken within 10 m (`lui 0x4120`); a bend's cosine (gp-30012) and
// its 10 m/s; the tolerance of either, 2 (`lui 0x4000`); and the least,
// 10.
#define TD_TOP_SPEED         24.5865002f
#define TD_HAIRPIN_LOOK      75.0f
#define TD_HAIRPIN_POINTS    18.75f
#define TD_HAIRPIN_SPEED     0.327820003f
#define TD_HAIRPIN_TAKE      10.0f
#define TD_BEND_COS          0.639999986f
#define TD_BEND_SPEED        10.0f
#define TD_SLOW_TOLERANCE    2.0f
#define TD_LEAST_SPEED       10.0f

// The routes a traffic car may take (GetRouteNumbersToUse), and JustReset's
// and CalculateDesiredSpeed's tests of the route it is on.
#define TD_LOW_FIRST  50
#define TD_LOW_LAST   59
#define TD_HIGH_FIRST 60
#define TD_HIGH_LAST  69

#define TD_POOL CAR_MEMORY_POOL

typedef void (*DriverDtorFn)(void *self, int32_t flags);
typedef void (*ActionDtorFn)(void *self, int32_t flags);
typedef void (*ActionInfoFn)(void *self, DrivingInformation *info);
typedef void (*DriverTargetFn)(void *self, const DriveTarget *t);
// Retail's SetDesiredSpeed (56): the speed, the time to reach it, the
// tolerance and whether the throttle and brake may be used.
typedef void (*DriverDesiredSpeedFn)(void *self, float speed, float time,
                                     float tolerance, int32_t allowed);

// `max.s` and `min.s`.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

static float min_s(float fs, float ft)
{
    return fs < ft ? fs : ft;
}

// Seconds since `t`: `WorldTimer - t` as a signed word, converted, times
// the tick.
static float seconds_since(const Timer *t)
{
    return (float)(int32_t)((uint32_t)WorldTimer - t->PackedTime)
           * TD_TICKS_TO_SECONDS;
}

// `delete a`, through the action's table: its destructor with flags 3.
static void delete_action(AIAction *a)
{
    const VtEntry *e = vt_slot(a->Base._vtable, AIACTION_VT_DTOR);

    ((ActionDtorFn)e->fn)(vt_this(a, e), 3);
}

// The current action, if any, deleted, as each step of the cascade does
// before its `new`; the pointer is overwritten at once.
static void delete_current(TrafficDriver *d)
{
    if (d->Base.CurrentAction != NULL)
        delete_action(d->Base.CurrentAction);
}

// `new AIActionJustDrive(score, -1)`, the slot from AIActionSlotPool by
// bOMalloc, inline, with no test.
static AIAction *new_just_drive(int32_t score)
{
    return &aijustdrive_init((AIActionJustDrive *)aiaction_new(), score,
                             TD_NO_LIFETIME)->Base;
}

// A car leaving its traffic belt, as AvoidCars and PullOver have it do.
static void off_the_belt(Car *car)
{
    if (car->TheMovementMode == TRAFFIC_MOVEMENT)
        car_set_movement_mode(car, MELLOW_MOVEMENT);
}

// -------------------------------------------------------------- the record

TrafficDriver *trafficdriver_init(TrafficDriver *d, Car *car)
{
    // 0x0018c380.
    PsychoDriver *pd;

    aicarcontroller_init(&d->Base, car);
    d->Base.Base._vtable = TRAFFICDRIVER_VTABLE;
    pd = (PsychoDriver *)bMalloc((int)sizeof(PsychoDriver), "PsychoDriver",
                                 0, TD_POOL);
    pd = psychodriver_init(pd, car);
    d->Base.Base.Driver = &pd->Base;
    d->Base.ForceCurrentAction = AIACTION_NONE;
    d->PickLowNumberedRoutes = 1;
    d->Base.CurrentAction = NULL;
    d->Base.SecondsBeforeNextActionEvaluation =
        (float)car->CarIndex * TD_THINK_STAGGER;
    return d;
}

CarController *trafficdriver_construct(void *mem, Car *car)
{
    return &trafficdriver_init((TrafficDriver *)mem, car)->Base.Base;
}

void trafficdriver_destroy(TrafficDriver *d, int32_t flags)
{
    // 0x0018c418. Freed and not cleared: nothing reads it again.
    CarDriver *drv;

    d->Base.Base._vtable = TRAFFICDRIVER_VTABLE;
    drv = d->Base.Base.Driver;
    if (drv != NULL) {
        const VtEntry *e = vt_slot(drv->_vtable, CARDRIVER_VT_DTOR);
        ((DriverDtorFn)e->fn)(vt_this(drv, e), 3);
    }
    aicarcontroller_destroy(&d->Base, flags);
}

// ---------------------------------------------------------------- Think

// Whether this frame is my think: for a traffic car, the odd frames of
// twelve whose half is my place among the traffic in the world's car
// table; for any other, the clock run out.
static int my_turn(TrafficDriver *d, Car *car)
{
    World *w;
    int32_t m;

    if (car->MyDriver->TheDriverType != DRIVER_TYPE_TRAFFIC_CAR)
        return d->Base.SecondsBeforeNextActionEvaluation <= 0.0f;
    // `div` and `mfhi`: the remainder takes the counter's sign.
    m = WorldLoopCounter % TD_TURNS;
    if ((m & 1) == 0)
        return 0;
    m >>= 1;
    w = pCurrentWorld;
    return m < w->TotalNumCars - w->TrafficCarPos
        && w->CarTable[w->TrafficCarPos + m] == car;
}

void trafficdriver_think(TrafficDriver *d, float dt)
{
    // 0x0018c4d8.
    AICarController *c = &d->Base;
    DrivingInformation *info = &c->MyCurrentDrivingInformation;
    Car *car = c->Base.pCar;
    DrivingChoice choice;
    DrivingChoiceType type;
    Car *hitCar, *avoidCar;
    float secs;
    int okay, used;
    int32_t best, s;

    // Retail first calls Car::PrintAbove (0x0018d078) with the car's
    // driver number when CameraFollowDefaultCar is 0 and this is not the
    // camera's car; it ships empty.
    c->SecondsBeforeNextActionEvaluation -= dt;
    if (!my_turn(d, car))
        return;

    aicarcontroller_do_sticky_decisions(c);
    c->SecondsBeforeNextActionEvaluation += TD_THINK_INTERVAL;
    nearbycarlist_build_array(&info->MyNearbyCarList,
                              c->CurrentDrivingLocation,
                              AIDriverSecondsToLookAhead);
    aicarcontroller_get_current_track_route_point(c, NULL);
    if (drivinglocation_is_clear(c->CurrentDrivingLocation))
        return;

    if (c->CurrentAction == NULL) {
        c->CurrentAction = new_just_drive(AIActionJustDriveScore);
    } else {
        aiaction_update_status(c->CurrentAction, info);
        best = aiplan_time_to_change(&c->CurrentAction->Base)
                   ? -1 : c->CurrentAction->Score;

        // The out slots, as the stack has them, and the choice Cleared.
        hitCar = NULL;
        avoidCar = NULL;
        okay = 1;
        used = 0;
        secs = 0.0f;
        drivingchoice_clear(&choice);

        if (best < AIActionGetUnstuckScore
            && TD_UNSTUCK_WAIT
                   < seconds_since(&c->LastTimeNonGetUnstuckActionWasCalled)) {
            s = aigetunstuck_calculate_score(info);
            if (best < s) {
                delete_current(d);
                c->CurrentAction = &aigetunstuck_init(
                    (AIActionGetUnstuck *)aiaction_new(), s,
                    AIActionGetUnstuckLifetime, TD_NO_LIFETIME)->Base;
                c->LastTimeNonGetUnstuckActionWasCalled.PackedTime =
                    (uint32_t)WorldTimer;
                best = c->CurrentAction->Score;
            }
        }

        if (best < AIActionAccidentRecoveryScore) {
            s = aiaccidentrecovery_calculate_score(info);
            if (best < s) {
                delete_current(d);
                c->CurrentAction = &aiaccidentrecovery_init(
                    (AIActionAccidentRecovery *)aiaction_new(), s,
                    TD_NO_LIFETIME)->Base;
                best = c->CurrentAction->Score;
            }
        }

        if (best < AIActionIJustGotHitScore) {
            s = aijustgothit_calculate_score(info, &hitCar);
            if (best < s) {
                delete_current(d);
                aicarcontroller_maybe_honk_and_or_blink_headlights(
                    c, hitCar, &info->MyNearbyCarList);
                c->CurrentAction = &aijustgothit_init(
                    (AIActionIJustGotHit *)aiaction_new(), s,
                    AIActionIJustGotHitLifetime, hitCar)->Base;
                best = c->CurrentAction->Score;
            }
        }

        if (best < AIActionAvoidCarsScore) {
            s = aiavoidcars_calculate_score(info, &avoidCar, &choice, &secs,
                                            &okay, &used);
            if (best < s) {
                delete_current(d);
                // AIDriver's arguments, one place on: the bool `okay`
                // (converted unsigned) as the seconds, `used` as okay, and
                // 0 as usedPreferred.
                c->CurrentAction = &aiavoidcars_init(
                    (AIActionAvoidCars *)aiaction_new(), s,
                    AIActionAvoidCarsLifetime, avoidCar,
                    (float)(uint32_t)okay, used, 0)->Base;
                info->MyDrivingChoice = choice;
                aicarcontroller_maybe_honk_and_or_blink_headlights(
                    c, avoidCar, &info->MyNearbyCarList);
                off_the_belt(car);
                best = c->CurrentAction->Score;
            }
        }

        if (best < AIActionPullOverScore) {
            s = aipullover_calculate_score(info);
            if (best < s) {
                delete_current(d);
                c->CurrentAction = &aipullover_init(
                    (AIActionPullOver *)aiaction_new(), s, TD_NO_LIFETIME,
                    AIActionPullOverTrafficCarTimeout,
                    c->CurrentNearbyCarList, c->CurrentDrivingLocation)->Base;
                off_the_belt(car);
                best = c->CurrentAction->Score;
            }
        }

        if (best < AIActionJustDriveScore) {
            s = aijustdrive_calculate_score(info);
            if (best < s) {
                delete_current(d);
                c->CurrentAction = new_just_drive(s);
            }
        }

        // ~DrivingChoice with flags 2: nothing to do. Every step replaces
        // the action it deletes, so the test after it never finds none.
        if (c->CurrentAction == NULL)
            c->CurrentAction = new_just_drive(AIActionJustDriveScore);
    }

    type = c->CurrentDrivingChoice->Type;
    if (drivingchoice_type_is_driving_line(type)) {
        int32_t line = drivingchoice_get_driving_line(type, car);

        if (line != c->CurrentDrivingLocation->DrivingLine) {
            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,
                                             0);
            ai_highlight_driving_line(c->CurrentDrivingLocation,
                                      aicarcontroller_get_my_driver_number(c));
        }
    }
    // A `jal`, not through the table.
    trafficdriver_execute_current_action(d);
}

void trafficdriver_get_route_numbers_to_use(TrafficDriver *d, int32_t *first,
                                            int32_t *last)
{
    // 0x0018cae8.
    if (d->PickLowNumberedRoutes) {
        *first = TD_LOW_FIRST;
        *last = TD_LOW_LAST;
    } else {
        *first = TD_HIGH_FIRST;
        *last = TD_HIGH_LAST;
    }
}

void trafficdriver_just_reset(TrafficDriver *d)
{
    // 0x0018cb10. The route of MyDrivingLocation, which
    // CurrentDrivingLocation points at.
    AICarController *c = &d->Base;
    TrackRoute *r = c->MyCurrentDrivingInformation.MyDrivingLocation.pRoute;

    if (r != NULL)
        d->PickLowNumberedRoutes =
            (uint32_t)(r->RouteNumber - TD_LOW_FIRST)
            < (uint32_t)(TD_LOW_LAST - TD_LOW_FIRST + 1);
    delete_current(d);
    aicarcontroller_clear_sticky_decisions(c);
    c->CurrentAction = new_just_drive(AIActionJustDriveScore);
    trafficdriver_execute_current_action(d);
}

// ----------------------------------------------------------- the driving

void trafficdriver_execute_current_action(TrafficDriver *d)
{
    // 0x0018cb98.
    AICarController *c = &d->Base;
    AIAction *a = c->CurrentAction;
    const VtEntry *e = vt_slot(a->Base._vtable,
                               AIACTION_VT_CALCULATE_POINTS_TO_DRIVE);
    CarDriver *drv;
    float speed, time, tol;

    ((ActionInfoFn)e->fn)(vt_this(a, e), &c->MyCurrentDrivingInformation);
    if (aicarcontroller_get_my_driver_number(c) == CameraFollowThisCarInstead)
        drivetargetrenderer_set_target_to_render(
            &TheDriveTargetRenderer, &c->CurrentAction->PointsToDrive);
    speed = 0.0f;
    time = 0.0f;
    tol = 0.0f;
    trafficdriver_calculate_desired_speed(d, &speed, &time, &tol);
    drv = c->Base.Driver;
    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_TARGET);
    ((DriverTargetFn)e->fn)(vt_this(drv, e),
                            &c->CurrentAction->PointsToDrive);
    drv = c->Base.Driver;
    e = vt_slot(drv->_vtable, CARDRIVER_VT_SET_DESIRED_SPEED);
    ((DriverDesiredSpeedFn)e->fn)(vt_this(drv, e), speed, time, tol,
                                  c->CurrentAction->AllowedToUseThrottleAndBrake);
    aiaction_clear_points_to_drive(c->CurrentAction);
}

// The first hairpin sign, not a backwards one, from the location's point
// on: within 75 m (the lengths summed up to it) and 19 points, and short
// of the route's end. NULL if none; `*dist` the distance either way.
static TrackRoutePoint *find_hairpin(const DrivingLocation *l, float *dist)
{
    TrackRoute *r = l->pRoute;
    TrackRoutePoint *p;
    float sum = 0.0f;
    int32_t i, k = 0;
    int32_t n = (int32_t)TD_HAIRPIN_POINTS;

    // Retail asks IsClear again, for an index of -1; the caller already
    // has.
    i = drivinglocation_is_clear(l) ? -1
                                    : troute_get_point_number(r, l->pRoutePoint);
    // Retail's first test is the tolerance's 0 against 75: always so.
    if (n < 0 || !(i < r->NumPoints)) {
        *dist = sum;
        return NULL;
    }
    p = &r->TrackRoutePointTable[i];
    for (;;) {
        if (trpoint_has_signpost(p)) {
            const Signpost *s = trpoint_get_signpost(p);

            if ((s->Flags & SIGNPOST_HAIRPIN)
                && !(s->Flags & SIGNPOST_BACKWARDS)) {
                *dist = sum;
                return p;
            }
        }
        i++;
        sum += p->Length;
        p++;
        if (!(sum < TD_HAIRPIN_LOOK))
            break;
        k++;
        if (n < k || !(i < r->NumPoints))
            break;
    }
    *dist = sum;
    return NULL;
}

void trafficdriver_calculate_desired_speed(TrafficDriver *d, float *speed,
                                           float *time, float *tol)
{
    // 0x0018cc78.
    AICarController *c = &d->Base;
    const AIAction *a;
    float most = TD_TOP_SPEED;
    float give;

    *speed = 0.0f;
    *time = 0.0f;
    *tol = 0.0f;
    give = *tol;

    if (!drivinglocation_is_clear(c->CurrentDrivingLocation)) {
        float dist;
        TrackRoutePoint *p = find_hairpin(c->CurrentDrivingLocation, &dist);

        if (p != NULL) {
            const Signpost *s;

            give = TD_SLOW_TOLERANCE;
            s = trpoint_get_signpost(p);
            most = dist * TD_HAIRPIN_SPEED;
            if (dist < TD_HAIRPIN_TAKE) {
                DrivingLocation *l;

                drivinglocation_set_route(c->CurrentDrivingLocation,
                                          signpost_get_new_route(s),
                                          signpost_get_new_route_point(s),
                                          0, 0);
                l = c->CurrentDrivingLocation;
                d->PickLowNumberedRoutes =
                    (drivinglocation_is_clear(l) ? -1
                                                 : l->pRoute->RouteNumber)
                    < TD_HIGH_FIRST;
            }
        }
    }

    // A bend: the points' first half against their second, by direction.
    a = c->CurrentAction;
    if (a->PointsToDrive.NumPoints >= 3) {
        int32_t n = a->PointsToDrive.NumPoints;
        const bVector3 *p0 = &a->PointsToDrive.Points[0];
        const bVector3 *pm = &a->PointsToDrive.Points[n / 2];
        const bVector3 *pn = &a->PointsToDrive.Points[n - 1];
        bVector2 in, out;

        in.x = pm->x - p0->x;
        in.y = pm->y - p0->y;
        out.y = pn->y - pm->y;
        out.x = pn->x - pm->x;
        bNormalize2(&in, &in);
        bNormalize2(&out, &out);
        if (in.x * out.x + in.y * out.y < TD_BEND_COS) {
            most = TD_BEND_SPEED;
            give = TD_SLOW_TOLERANCE;
        }
    }

    most = max_s(most, TD_LEAST_SPEED);
    if (a->UseDrivingLineSpeed) {
        *speed = most;
        *time = 0.0f;
        *tol = give;
    } else {
        *speed = a->DesiredSpeed;
        *time = a->TimeToGetToDesiredSpeed;
        *tol = a->DesiredSpeedTolerance;
    }
    *speed = min_s(*speed, most);
}

void trafficdriver_set_direction(TrafficDriver *d, int32_t low)
{
    // 0x0018d030.
    d->PickLowNumberedRoutes = low;
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$13TrafficDriver, retail's 0x002b4730. DoSnapshot (0x0018c478) waits
// on ReplaySnapshot.
static const VtEntry trafficdriver_vt[AICARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(trafficdriver_destroy),                         //   8  0x0018c418
    E(aicarcontroller_debug_display),                 //  16  0x00191138
    { 0, 0, NULL },                                   //  24  0x0018c478
    E(trafficdriver_think),                           //  32  0x0018c4d8
    E(aicarcontroller_set_current_route),             //  40  0x00190670
    E(aicarcontroller_get_current_route),             //  48  0x00190708
    E(aicarcontroller_get_current_route_point),       //  56  0x00190760
    E(aicarcontroller_get_amount_out_of_bounds),      //  64  0x001907b8
    E(aicarcontroller_find_where_i_am),               //  72  0x00192f10
    E(trafficdriver_just_reset),                      //  80  0x0018cb10
    E(aicarcontroller_set_to_physics_mode),           //  88  0x00193650
    E(aicarcontroller_force_boost),                   //  96  0x00193758
    E(aicarcontroller_release_boost),                 // 104  0x00193780
    E(trafficdriver_get_route_numbers_to_use),        // 112  0x0018cae8
    E(aicarcontroller_choose_new_action),             // 120  0x00192780
    E(aicarcontroller_generate_points_to_fulfill_action), // 128  0x00192668
};

#undef E

void trafficdriver_install_vtables(void)
{
    vt_install(TRAFFICDRIVER_VTABLE, trafficdriver_vt,
               AICARCONTROLLER_VT_ENTRIES);
}
