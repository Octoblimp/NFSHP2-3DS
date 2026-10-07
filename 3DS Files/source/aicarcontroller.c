// aicarcontroller -- see aicarcontroller.h and
// docs/formats/ai-car-controller.md.
#include "aicarcontroller.h"

#include <math.h>
#include <string.h>

#include "aiactions.h"
#include "bmath.h"
#include "bmem.h"
#include "cardriver.h"
#include "carmodes.h"
#include "difficultyinfo.h"
#include "drivetarget.h"
#include "drivingchoice.h"
#include "race.h"
#include "racecore.h"
#include "raceinit.h"
#include "track.h"
#include "trackpath.h"
#include "vtable.h"
#include "world.h"

// gp-29940 and gp-29928, the constructor's and JustReset's: -1/140, so
// each car's first evaluation is staggered by its index.
#define AICC_EVALUATION_STAGGER (-0.007142857648432255f)

// The constructor's ProgressTimer (gp-29936, 6000.5 already in ticks),
// SetToPhysicsMode's OffBeltTimer (gp-29756, 8000.5) and RealPhysicsTimer
// (gp-29752, 12000.5): 1.5, 2 and 3 seconds.
#define AICC_PROGRESS_SECONDS      1.5f
#define AICC_OFF_BELT_SECONDS      2.0f
#define AICC_REAL_PHYSICS_SECONDS  3.0f

// gp-29932: no pull-over timeout to speak of.
#define AICC_PULL_OVER_TIMEOUT 10000000.0f

// FindClosestTrackRoute's starting best and search radius (gp-29924 and
// gp-29920), and GetNewDrivingLine's first hit time (gp-29828), which
// IsDriveable overwrites before reading.
#define AICC_NO_ROUTE_DISTANCE 999999.0f
#define AICC_ROUTE_RADIUS      999999.0f
#define AICC_NO_HIT_TIME       99999.0f

// FindClosestTrackRoute's FindClosestPoint flags: 3, ahead and posted.
#define AICC_ROUTE_FLAGS (TRFIND_AHEAD_ONLY | TRFIND_POSTED_ONLY)

// DoStickyDecisions: a decision is dropped 10 m past its sign (`lui
// 0x4120`), and signs are decided AIDriverSecondsToLookAhead times my
// speed times 1.1 (gp-29840) ahead, but no less than 100 m and no more
// than 250.
#define AICC_STICKY_DROP      10.0f
#define AICC_SIGN_SPEED_SCALE 1.10000002f
#define AICC_SIGN_AHEAD_MIN   100.0f
#define AICC_SIGN_AHEAD_MAX   250.0f

// SignPostDecision's race clock (gp-29836): ticks to seconds.
#define AICC_TICKS_TO_SECONDS 0.000250000012f

// GetCurrentTrackRoutePoint's TakenSignpostTimer: gp-29832, 10000.5,
// through `cvt.w.s`, so 10000 ticks. Not WorldTimer plus that: the
// timer is a span of 2.5 s, as `Timer(2.5f)` builds one.
#define AICC_TAKEN_SIGN_TICKS 10000.5f

// A sticky decision's word: bit 0 the slot in use, bit 1 the sign taken,
// bits 2 to 7 the line, bits 8 to 15 the sign's index (a byte).
#define STICKY_USED      0x1u
#define STICKY_TAKE      0x2u
#define STICKY_LINE_MASK 0xfcu
#define STICKY_SIGN(w)   (((w) >> 8) & 0xffu)

typedef void       (*DriverFn)(void *self);
typedef void       (*DriverPointFn)(void *self, bVector2 *p);
typedef void       (*ActionDtorFn)(void *self, int32_t flags);
typedef void       (*ActionInfoFn)(void *self, DrivingInformation *info);
typedef void       (*SetRouteFn)(void *self, TrackRoute *r,
                                 TrackRoutePoint *p);
typedef void       (*ControllerFn)(void *self);

// ------------------------------------------------------------ dispatch

// `delete a`, through the action's table: its destructor with flags 3.
static void delete_action(AIAction *a)
{
    const VtEntry *e = vt_slot(a->Base._vtable, AIACTION_VT_DTOR);

    ((ActionDtorFn)e->fn)(vt_this(a, e), 3);
}

static void action_calculate_points(AIAction *a, DrivingInformation *info)
{
    const VtEntry *e = vt_slot(a->Base._vtable,
                               AIACTION_VT_CALCULATE_POINTS_TO_DRIVE);

    ((ActionInfoFn)e->fn)(vt_this(a, e), info);
}

static void choose_new_action(AICarController *c, AIAction **out,
                              AIActionType type)
{
    const VtEntry *e = vt_slot(c->Base._vtable,
                               AICARCONTROLLER_VT_CHOOSE_NEW_ACTION);

    ((AICarControllerChooseFn)e->fn)(vt_this(c, e), out, type);
}

static void find_where_i_am(AICarController *c)
{
    const VtEntry *e = vt_slot(c->Base._vtable,
                               CARCONTROLLER_VT_FIND_WHERE_I_AM);

    ((ControllerFn)e->fn)(vt_this(c, e));
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

// -------------------------------------------------------- the record

AICarController *aicarcontroller_init(AICarController *c, Car *car)
{
    // 0x00190140.
    NearbyCarList *list = &c->MyCurrentDrivingInformation.MyNearbyCarList;
    int i;

    carcontroller_init(&c->Base, car);
    c->Base._vtable = AICARCONTROLLER_VTABLE;
    // The NearbyCars' and the DrivingLocation's own constructors.
    for (i = 0; i < NEARBYCARLIST_MAX; i++)
        list->Array[i].TheCar = NULL;
    list->MyCar = car;
    nearbycarlist_clear_array(list);
    c->MyCurrentDrivingInformation.MyDrivingLocation
        .LastRelaxedDrivingLineSwitchTime.PackedTime = 0;
    drivinglocation_clear(&c->MyCurrentDrivingInformation.MyDrivingLocation);
    drivingchoice_clear(&c->MyCurrentDrivingInformation.MyDrivingChoice);
    drivinginformation_clear(&c->MyCurrentDrivingInformation);
    // The Timers' constructors, then the sticky decisions'.
    c->LastRoutePointLookaheadSwitch.PackedTime = 0;
    c->LastTimeNonGetUnstuckActionWasCalled.PackedTime = 0;
    c->BrakeStandTimer.PackedTime = 0;
    c->BrakeStandTimerStart.PackedTime = 0;
    c->LastBoostCalculationTime.PackedTime = 0;
    c->OffBeltTimer.PackedTime = 0;
    c->RealPhysicsTimer.PackedTime = 0;
    c->ProgressTimer.PackedTime = 0;
    c->GlueOnTimer.PackedTime = 0;
    c->GlueOffTimer.PackedTime = 0;
    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
        c->aStickyDecisions[i] &= ~1u;
    c->TakenSignpostTimer.PackedTime = 0;

    c->SecondsBeforeNextActionEvaluation =
        (float)car->CarIndex * AICC_EVALUATION_STAGGER;
    c->ForceCurrentAction = AIACTION_NONE;
    c->LastTrackRouteNumber = -1;
    c->CurrentAction = NULL;
    drivinginformation_clear(&c->MyCurrentDrivingInformation);
    c->CurrentDrivingLocation =
        &c->MyCurrentDrivingInformation.MyDrivingLocation;
    c->CurrentDrivingChoice = &c->MyCurrentDrivingInformation.MyDrivingChoice;
    c->CurrentNearbyCarList = list;
    c->LastRoutePointLookaheadSwitch.PackedTime = 0;
    c->CurrentRoutePointLookahead = 0;
    c->CarToExcludeFromCollisionPrediction = NULL;
    c->LastBoostCalculationTime.PackedTime = 0;
    c->OffBeltTimer.PackedTime = 0;
    c->RealPhysicsTimer.PackedTime = 0;
    c->pGlueCar = NULL;
    c->GlueOnTimer.PackedTime = 0;
    c->GlueOffTimer.PackedTime = 0;
    c->nGlueOffReason = 0;
    timer_set_time(&c->ProgressTimer, AICC_PROGRESS_SECONDS);
    c->pProgress = average_init(
        (Average *)bMalloc((int)sizeof(Average), "Progress Average", 0,
                           CAR_MEMORY_POOL), 10);
    c->pDeltaLineSpeed = average_init(
        (Average *)bMalloc((int)sizeof(Average), "DeltaLineSPeed Average", 0,
                           CAR_MEMORY_POOL), 5);
    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);
    c->bBoostAllowed = 1;
    c->pCatchupPlayer = NULL;
    c->LastTimeNonGetUnstuckActionWasCalled.PackedTime = 0;
    c->PullOverTimeout = AICC_PULL_OVER_TIMEOUT;
    aicarcontroller_clear_sticky_decisions(c);
    c->nSignpostIndex = signpost_get_index(car->TheTrackPathCoordinate
                                               .DistanceAroundTrack);
    c->BrakeStanding = 1;
    c->TakenSignpostIndex = -1;
    c->TakenSignpostTimer.PackedTime = 0;
    return c;
}

void aicarcontroller_destroy(AICarController *c, int32_t flags)
{
    // 0x001903a0. Freed and not cleared: nothing reads them again.
    c->Base._vtable = AICARCONTROLLER_VTABLE;
    if (c->CurrentAction != NULL)
        delete_action(c->CurrentAction);
    if (c->pProgress != NULL)
        average_destroy(c->pProgress, 3);
    if (c->pDeltaLineSpeed != NULL)
        average_destroy(c->pDeltaLineSpeed, 3);
    // ~DrivingInformation with flags 2 does nothing.
    carcontroller_destroy(&c->Base, flags);
}

void aicarcontroller_debug_display(AICarController *c)
{
    // 0x00191138.
    (void)c;
}

// -------------------------------------------------------- the route

void aicarcontroller_set_current_route(AICarController *c, TrackRoute *r,
                                       TrackRoutePoint *p)
{
    // 0x00190670.
    int32_t line;
    TrackRoute *old;

    if (r == NULL || p == NULL)
        return;
    old = c->CurrentDrivingLocation->pRoute;
    c->LastTrackRouteNumber = old != NULL ? (int8_t)old->RouteNumber : -1;
    line = 0;
    aicarcontroller_get_new_driving_line(c, r, p, 1, &line, NULL);
    drivinglocation_set_route(c->CurrentDrivingLocation, r, p, line, 1);
}

static void find_if_clear(AICarController *c, int find)
{
    if (find && drivinglocation_is_clear(c->CurrentDrivingLocation)) {
        const VtEntry *e = vt_slot(c->Base._vtable,
                                   CARCONTROLLER_VT_FIND_WHERE_I_AM);

        ((ControllerFn)e->fn)(vt_this(c, e));
        // IsClear again, its answer unused.
    }
}

TrackRoute *aicarcontroller_get_current_route(AICarController *c, int find)
{
    // 0x00190708.
    find_if_clear(c, find);
    return c->CurrentDrivingLocation->pRoute;
}

TrackRoutePoint *aicarcontroller_get_current_route_point(AICarController *c,
                                                         int find)
{
    // 0x00190760.
    find_if_clear(c, find);
    return c->CurrentDrivingLocation->pRoutePoint;
}

float aicarcontroller_get_amount_out_of_bounds(AICarController *c)
{
    // 0x001907b8.
    const TrackRoutePoint *p;
    const bVector3 *pos;
    float f;

    if (drivinglocation_is_clear(c->CurrentDrivingLocation))
        return 0.0f;
    p = c->CurrentDrivingLocation->pRoutePoint;
    pos = &c->Base.pCar->State.Position;
    f = (pos->x - p->Position.x) * p->Direction.y
        - (pos->y - p->Position.y) * p->Direction.x;
    if (0.0f < f)
        return f - p->RightWidth;
    return -(f + p->LeftWidth);
}

void aicarcontroller_find_where_i_am(AICarController *c)
{
    // 0x00192f10. Both arms of the control mode test are the same call.
    int32_t first, last;
    const VtEntry *e;

    drivinglocation_clear(c->CurrentDrivingLocation);
    e = vt_slot(c->Base._vtable, AICARCONTROLLER_VT_GET_ROUTE_NUMBERS_TO_USE);
    ((AICarControllerRouteNumbersFn)e->fn)(vt_this(c, e), &first, &last);
    aicarcontroller_find_closest_track_route(c, first, last);
}

void aicarcontroller_find_closest_track_route(AICarController *c,
                                              int32_t first, int32_t last)
{
    // 0x00190900.
    Car *car = c->Base.pCar;
    TrackRoute *current = c->CurrentDrivingLocation->pRoute;
    float d = car->TheTrackPathCoordinate.DistanceAroundTrack;
    float best = AICC_NO_ROUTE_DISTANCE;
    TrackRoute *bestRoute = NULL;
    TrackRoutePoint *bestPoint = NULL;
    int pass;

    for (pass = 0; pass < 2 && bestRoute == NULL; pass++) {
        int32_t i;

        for (i = first; i <= last; i++) {
            // `bltz`: no slot below 0, and none checked above 99.
            TrackRoute *r = i >= 0 ? TheTrackRouteManager.pTrackRoutes[i]
                                   : NULL;
            TrackRoutePoint *p;
            bVector3 v, dv;
            float dist;

            if (r == NULL)
                continue;
            if (pass <= 0 && !troute_distance_is_within_route(r, d))
                continue;
            p = troute_find_closest_point(
                r, (const bVector2 *)(const void *)&car->State.Position,
                AICC_ROUTE_RADIUS, AICC_ROUTE_FLAGS, 0.0f);
            if (p == NULL)
                continue;
            trpoint_get_position3(p, &v, 0.0f, 0.0f);
            dv.x = car->State.Position.x - v.x;
            dv.y = car->State.Position.y - v.y;
            dv.z = car->State.Position.z - v.z;
            dist = sqrtf(dv.x * dv.x + dv.y * dv.y + dv.z * dv.z);
            if (dist < best && r != current) {
                bestPoint = p;
                bestRoute = r;
                best = dist;
            }
        }
    }
    if (bestRoute != NULL && bestPoint != NULL) {
        const VtEntry *e = vt_slot(c->Base._vtable,
                                   CARCONTROLLER_VT_SET_CURRENT_ROUTE);

        ((SetRouteFn)e->fn)(vt_this(c, e), bestRoute, bestPoint);
        return;
    }
    // Clear, inline.
    c->CurrentDrivingLocation->DrivingLine = -1;
    c->CurrentDrivingLocation->LastRelaxedDrivingLineSwitchTime.PackedTime = 0;
    c->CurrentDrivingLocation->pRoute = NULL;
    c->CurrentDrivingLocation->pRoutePoint = NULL;
}

int aicarcontroller_get_new_driving_line(AICarController *c, TrackRoute *r,
                                         TrackRoutePoint *p, int relaxed,
                                         int32_t *line,
                                         DrivingLocation *highlight)
{
    // 0x00192488.
    DriveTarget t;
    DrivingChoice ch;
    DrivingLocation l;
    float score = -1.0f, hitTime = AICC_NO_HIT_TIME;
    Car *hit = NULL;
    int found = 0;

    drivetarget_init(&t);
    drivingchoice_clear(&ch);
    l.LastRelaxedDrivingLineSwitchTime.PackedTime = 0;
    drivinglocation_clear(&l);
    *line = drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,
                                           c->Base.pCar);
    drivinglocation_set_route(&l, r, p, *line, relaxed);
    if (r != NULL && p != NULL) {
        DrivingChoiceType type;

        for (type = CHOICE_DRIVING_LINE_0;
             type - 1 < AICarControllerNumDrivingLinesToConsider; type++) {
            drivingchoice_set_choice(&ch, type, NULL, 0);
            drivinglocation_set_driving_line(
                &l, drivingchoice_get_driving_line(type, c->Base.pCar),
                relaxed);
            if (drivingchoice_is_driveable(
                    &ch, &t, 0, &score, &hit, &hitTime, &l,
                    c->CurrentNearbyCarList, 0.0f,
                    AIDriverAvoidCarsImpactTimeThreshold, 0.0f,
                    MOVEMENT_TOWARDS_LINE)) {
                found = 1;
                *line = drivingchoice_get_driving_line(type, c->Base.pCar);
                break;
            }
        }
        if (highlight != NULL)
            ai_highlight_driving_line(highlight,
                                      aicarcontroller_get_my_driver_number(c));
    }
    drivetarget_destroy(&t);
    return found;
}

void aicarcontroller_just_reset(AICarController *c)
{
    // 0x00190850.
    CarDriver *d;
    const VtEntry *e;

    c->SecondsBeforeNextActionEvaluation =
        (float)c->Base.pCar->CarIndex * AICC_EVALUATION_STAGGER;
    memset(&c->vPreviousLinePoint, 0, sizeof c->vPreviousLinePoint);
    d = c->Base.Driver;
    e = vt_slot(d->_vtable, CARDRIVER_VT_ZERO_STEERING_MEMORY);
    ((DriverFn)e->fn)(vt_this(d, e));
    aicarcontroller_clear_sticky_decisions(c);
    c->nSignpostIndex = signpost_get_index(
        c->Base.pCar->TheTrackPathCoordinate.DistanceAroundTrack);
}

int32_t aicarcontroller_get_my_driver_number(AICarController *c)
{
    // 0x001908f0.
    return c->Base.pCar->DriverNumber;
}

void aicarcontroller_clear_sticky_decisions(AICarController *c)
{
    // 0x00191d10.
    int i;

    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
        c->aStickyDecisions[i] &= ~1u;
}

void aicarcontroller_steer_straight_ahead(AICarController *c)
{
    // 0x00192848.
    Car *car = c->Base.pCar;
    uint16_t a = car->State.Angle;
    float cs = bCosBam(a), sn = bSinBam(a);
    bVector2 to;
    CarDriver *d;
    const VtEntry *e;

    to.x = car->State.Position.x + cs;
    to.y = car->State.Position.y + sn;
    d = c->Base.Driver;
    e = vt_slot(d->_vtable, CARDRIVER_VT_SET_STEER_TO_POINT);
    ((DriverPointFn)e->fn)(vt_this(d, e), &to);
}

// ---------------------------------------------------------- the signposts

// nSignpostIndex one on, and back to 0 at NumSignposts (`slt`, signed).
static void next_signpost(AICarController *c)
{
    int32_t i = c->nSignpostIndex + 1;

    c->nSignpostIndex = i;
    if (!(i < (int32_t)NumSignposts))
        c->nSignpostIndex = 0;
}

void aicarcontroller_find_signpost_index(AICarController *c)
{
    // 0x00191d40.
    float mine = c->Base.pCar->TheTrackPathCoordinate.DistanceAroundTrack;

    while (SignpostArray[c->nSignpostIndex].Distance < mine) {
        int32_t i = c->nSignpostIndex + 1;

        c->nSignpostIndex = i;
        if (!(i < (int32_t)NumSignposts)) {
            c->nSignpostIndex = 0;
            return;
        }
    }
}

int32_t aicarcontroller_get_sticky_index(AICarController *c)
{
    // 0x00191d90.
    int32_t i;

    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++)
        if (!(c->aStickyDecisions[i] & STICKY_USED))
            return i;
    return -1;
}

void aicarcontroller_do_sticky_decisions(AICarController *c)
{
    // 0x00191b30.
    Car *car = c->Base.pCar;
    float mine = car->TheTrackPathCoordinate.DistanceAroundTrack;
    float ahead;
    int i;

    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++) {
        uint32_t w = c->aStickyDecisions[i];

        if (!(w & STICKY_USED))
            continue;
        if (AICC_STICKY_DROP
            < trackpath_compare_distances(
                &TheTrackPathManager, mine,
                SignpostArray[STICKY_SIGN(w)].Distance)) {
            c->aStickyDecisions[i] &= ~STICKY_USED;
            if ((int32_t)STICKY_SIGN(c->aStickyDecisions[i])
                == c->TakenSignpostIndex)
                c->TakenSignpostIndex = -1;
        }
    }
    ahead = AIDriverSecondsToLookAhead
            * (car->State.VelocityMagnitude * AICC_SIGN_SPEED_SCALE);
    ahead = min_s(AICC_SIGN_AHEAD_MAX, max_s(ahead, AICC_SIGN_AHEAD_MIN));
    while (aicarcontroller_get_sticky_index(c) != -1) {
        Signpost *s = &SignpostArray[c->nSignpostIndex];
        float d = trackpath_compare_distances(&TheTrackPathManager,
                                              s->Distance, mine);

        if (d < 0.0f) {
            next_signpost(c);
        } else if (d < ahead) {
            int32_t line = -1;

            aicarcontroller_sign_post_decision(c, s, &line,
                                               c->CurrentDrivingLocation);
            next_signpost(c);
        } else {
            break;
        }
    }
}

// The line a sign not taken keeps: the location's, or line 0's with the
// location clear.
static int32_t keep_line(AICarController *c, const DrivingLocation *loc)
{
    if (drivinglocation_is_clear(loc))
        return drivingchoice_get_driving_line(CHOICE_DRIVING_LINE_0,
                                              c->Base.pCar);
    return loc->DrivingLine;
}

// Whether the AI may take a sign other than AlwaysTake yet: past the
// track's SignpostGracePeriod on the race clock, or with -1 there, out of
// the race's grace period.
static int past_sign_grace(AICarController *c)
{
    int32_t g = track_get_info(TheRaceParameters.TrackNumber)
                    ->SignpostGracePeriod;

    if (g == -1)
        return !race_grace_period_is_active(pCurrentRace, c->Base.pCar);
    return (float)g < (float)(int32_t)pCurrentRace->RaceTime.PackedTime
                          * AICC_TICKS_TO_SECONDS;
}

// A Faster, Slower or Stop sign, by my skill's TakeSignChance: a draw at
// or under the first takes a Slower sign, one at or under the second, or
// over all three, a Faster one, and one between the second and the third
// none. SignPostDecision's switch (the table at 0x002b4cb0).
static int take_by_skill(AICarController *c, uint32_t sign)
{
    int32_t skill = c->Base.pCar->MyDriver->SkillLevel;
    const float *chance;
    float r;
    int k = 0;

    // `pmaxw` and `pminw`: 0 to 9.
    skill = skill < 0 ? 0 : skill;
    skill = skill < 9 ? skill : 9;
    r = world_random_f(pCurrentWorld, 1.0f);
    chance = TheDifficultyInfo.AISkillLevel[skill].TakeSignChance;
    if (r <= chance[0])
        k = 2;
    else if (r <= chance[1])
        k = 1;
    else if (r <= chance[2])
        k = 3;
    switch (k) {
    case 0:
    case 1:
        return sign == SIGN_FASTER;
    case 2:
        return sign == SIGN_SLOWER;
    default:
        return 0;
    }
}

int aicarcontroller_sign_post_decision(AICarController *c, Signpost *s,
                                       int32_t *line, DrivingLocation *loc)
{
    // 0x00191de0.
    uint32_t flags = s->Flags;
    uint32_t sign = flags & SIGNPOST_SIGN_MASK;
    uint32_t index, v;
    uint32_t *slotp;
    int32_t slot;
    int take = 0;
    int i;

    if ((flags & SIGNPOST_BACKWARDS) != 0
        || ((flags & SIGNPOST_CLOAKED) != 0 && sign != SIGN_ALWAYS_TAKE)) {
        *line = keep_line(c, loc);
        return 0;
    }
    index = (uint32_t)(s - SignpostArray) & 0xffu;
    for (i = 0; i < AICC_NUM_STICKY_DECISIONS; i++) {
        uint32_t w = c->aStickyDecisions[i];

        if ((w & STICKY_USED) && STICKY_SIGN(w) == index) {
            *line = (int32_t)((w >> 2) & 0x3fu);
            return (int)((w >> 1) & 1u);
        }
    }
    slot = aicarcontroller_get_sticky_index(c);
    if (sign == SIGN_ALWAYS_TAKE) {
        take = 1;
    } else {
        if (!past_sign_grace(c))
            take = 0;
        else if (sign == SIGN_EQUIVALENT)
            take = world_random_f(pCurrentWorld, 1.0f) < 0.5f;
        else if (sign == SIGN_DONT_TAKE)
            take = 0;
        else
            take = take_by_skill(c, sign);
        if (!take) {
            // Not IsClear: the location's line as it is.
            *line = loc->DrivingLine;
        } else if (aicarcontroller_get_new_driving_line(
                       c, signpost_get_new_route(s),
                       signpost_get_new_route_point(s), 1, line, loc)) {
            if (s->AIHint == SIGNPOST_AIHINT_HOLD_LINE_SPEED)
                c->TakenSignpostIndex = (int32_t)index;
        } else {
            take = 0;
        }
    }
    // A taken sign with no line yet (AlwaysTake's, from a caller's -1)
    // asks for one, and keeps whatever it gets.
    if (take && *line < 0)
        aicarcontroller_get_new_driving_line(
            c, signpost_get_new_route(s), signpost_get_new_route_point(s), 1,
            line, loc);
    if (!((uint32_t)*line < 2u))
        *line = keep_line(c, loc);
    // With every slot in use, retail's `652 + 4 * -1` is nSignpostIndex,
    // which takes the decision instead.
    slotp = slot >= 0 ? &c->aStickyDecisions[slot]
                      : (uint32_t *)(void *)&c->nSignpostIndex;
    v = ((*slotp | STICKY_USED) & ~STICKY_TAKE) | ((uint32_t)take << 1);
    v = (v & ~STICKY_LINE_MASK) | (((uint32_t)*line & 0x3fu) << 2);
    *slotp = (v & ~0xff00u) | (index << 8);
    return take;
}

void aicarcontroller_get_current_track_route_point(AICarController *c,
                                                   Car *car)
{
    // 0x001921f8. `car` is not read.
    float margin = c->MyCurrentDrivingInformation.MyNearbyCarList.MyHalfSizeL;
    DrivingLocation *loc = c->CurrentDrivingLocation;
    TrackRoute *r;
    TrackRoutePoint *p, *np;
    const bVector3 *pos;
    float f;
    int atEnd = 0, took = 0;
    int32_t i, last;

    (void)car;
    if (drivinglocation_is_clear(loc)) {
        find_where_i_am(c);
        return;
    }
    p = loc->pRoutePoint;
    pos = &c->Base.pCar->State.Position;
    f = (pos->x - p->Position.x) * p->Direction.y
        - (pos->y - p->Position.y) * p->Direction.x;
    if (p->RightWidth < f - margin || f + margin < -p->LeftWidth) {
        find_where_i_am(c);
        return;
    }
    r = loc->pRoute;
    np = troute_find_closest_point_ahead(
        r, (const bVector2 *)(const void *)pos, p);
    if (np == NULL) {
        atEnd = 1;
        np = &r->TrackRoutePointTable[r->NumPoints - 1];
    }
    drivinglocation_set_route_point(c->CurrentDrivingLocation, np);
    last = troute_get_point_number(r, np);
    for (i = troute_get_point_number(r, p); i <= last; i++) {
        TrackRoutePoint *pt = &r->TrackRoutePointTable[i];
        Signpost *s;
        int32_t line = -1;

        if (!trpoint_has_signpost(pt))
            continue;
        s = trpoint_get_signpost(pt);
        if (aicarcontroller_sign_post_decision(c, s, &line,
                                               c->CurrentDrivingLocation)) {
            DrivingLocation *l = c->CurrentDrivingLocation;

            c->LastTrackRouteNumber = drivinglocation_is_clear(l)
                                          ? -1
                                          : (int8_t)l->pRoute->RouteNumber;
            drivinglocation_set_route(c->CurrentDrivingLocation,
                                      signpost_get_new_route(s),
                                      signpost_get_new_route_point(s), line,
                                      1);
            took = 1;
            if (s->AIHint == 1)
                c->TakenSignpostTimer.PackedTime =
                    (int32_t)AICC_TAKEN_SIGN_TICKS;
            break;
        }
        // Asked for, and dropped.
        signpost_get_new_route(s);
    }
    if (atEnd && !took)
        find_where_i_am(c);
}

// -------------------------------------------------------- the action

void aicarcontroller_choose_new_action(AICarController *c, AIAction **out,
                                       AIActionType type)
{
    // 0x00192780.
    (void)c;
    (void)out;
    (void)type;
}

AIAction *aicarcontroller_interrupt_action(AICarController *c)
{
    // 0x00192788.
    AIAction *a = NULL;

    if (c->ForceCurrentAction == AIACTION_NONE) {
        choose_new_action(c, &a, AIACTION_NONE);
        if (a == NULL)
            return NULL;
        if (c->CurrentAction != NULL && c->CurrentAction->Score < a->Score)
            return a;
        delete_action(a);
        return NULL;
    }
    choose_new_action(c, &a, c->ForceCurrentAction);
    c->ForceCurrentAction = AIACTION_NONE;
    return a;
}

void aicarcontroller_generate_points_to_fulfill_action(AICarController *c,
                                                       AIAction *a)
{
    // 0x00192668.
    DrivingInformation *info = &c->MyCurrentDrivingInformation;
    DrivingChoiceType type;

    nearbycarlist_get_car_ahead(c->CurrentNearbyCarList, c->Base.pCar);
    action_calculate_points(a, info);
    if (!a->PointsToDriveWillExecuteAction) {
        if (c->CurrentAction != NULL)
            delete_action(c->CurrentAction);
        c->CurrentAction = NULL;
        choose_new_action(c, &c->CurrentAction, AIACTION_DRAFT);
        action_calculate_points(c->CurrentAction, info);
    }
    type = c->CurrentDrivingChoice->Type;
    if (drivingchoice_type_is_driving_line(type)) {
        int32_t line = drivingchoice_get_driving_line(type, c->Base.pCar);

        if (line != c->CurrentDrivingLocation->DrivingLine) {
            drivinglocation_set_driving_line(c->CurrentDrivingLocation, line,
                                             0);
            ai_highlight_driving_line(c->CurrentDrivingLocation,
                                      aicarcontroller_get_my_driver_number(c));
        }
    }
}

AIActionType aicarcontroller_get_current_action_type(AICarController *c)
{
    // 0x00194000.
    return c->CurrentAction != NULL ? c->CurrentAction->Type
                                    : AIACTION_NONE;
}

void aicarcontroller_force_my_current_action(AICarController *c,
                                             AIActionType type)
{
    // 0x00194020.
    c->ForceCurrentAction = type;
}

// -------------------------------------------------------- the physics

void aicarcontroller_set_to_physics_mode(AICarController *c, Car *car)
{
    // 0x00193650.
    Car *mine = c->Base.pCar;
    MovementMode old = mine->TheMovementMode;
    MovementMode mode = nDefaultMovementMode;

    if (old == BELT_MOVEMENT)
        timer_set_time(&c->OffBeltTimer, AICC_OFF_BELT_SECONDS);
    if (car != NULL && car->pPlayer != NULL)
        mode = PHYSICS_MOVEMENT;
    if (mode != old)
        car_set_movement_mode(mine, mode);
    if (mode == PHYSICS_MOVEMENT)
        timer_set_time(&c->RealPhysicsTimer, AICC_REAL_PHYSICS_SECONDS);
}

float aicarcontroller_get_current_driving_line_speed(AICarController *c)
{
    // 0x001936f0. The byte at 90 + line of the point, which for line -1
    // is the last offset's high byte. `(b << 16) * 2^-16`, which is b.
    const DrivingLocation *l = c->CurrentDrivingLocation;
    const uint8_t *b;

    if (drivinglocation_is_clear(l))
        return 0.0f;
    b = (const uint8_t *)l->pRoutePoint
        + offsetof(TrackRoutePoint, DrivingLineSpeeds) + l->DrivingLine;
    return (float)*b;
}

float aicarcontroller_line_speed_seam(CarController *ctl)
{
    return aicarcontroller_get_current_driving_line_speed(
        (AICarController *)(void *)ctl);
}

void aicarcontroller_force_boost(AICarController *c, float f)
{
    // 0x00193758.
    carcontroller_force_boost(&c->Base, f);
    c->bBoostAllowed = 0;
}

void aicarcontroller_release_boost(AICarController *c)
{
    // 0x00193780.
    carcontroller_release_boost(&c->Base);
    c->bBoostAllowed = 1;
}

int32_t aicarcontroller_about_to_fly(AICarController *c, float t)
{
    // 0x00191130.
    (void)c;
    (void)t;
    return 0;
}

void aicarcontroller_set_off_belt_timer(AICarController *c, float seconds)
{
    // 0x00194028.
    timer_set_time(&c->OffBeltTimer, seconds);
}

Car *aicarcontroller_get_car_to_exclude_from_collision_prediction(
    AICarController *c)
{
    // 0x00193fe0.
    return c->CarToExcludeFromCollisionPrediction;
}

void aicarcontroller_set_car_to_exclude_from_collision_prediction(
    AICarController *c, Car *car)
{
    // 0x00193fe8.
    c->CarToExcludeFromCollisionPrediction = car;
}

DrivingLocation *aicarcontroller_get_current_driving_location(
    AICarController *c)
{
    // 0x00193ff8.
    return c->CurrentDrivingLocation;
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$15AICarController, retail's 0x002b4d90. DoSnapshot waits on
// ReplaySnapshot, Think is step 11e-5's, and GetRouteNumbersToUse is pure.
static const VtEntry aicarcontroller_vt[AICARCONTROLLER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aicarcontroller_destroy),                       //   8  0x001903a0
    E(aicarcontroller_debug_display),                 //  16  0x00191138
    { 0, 0, NULL },                                   //  24  0x00190438
    { 0, 0, NULL },                                   //  32  0x00191148
    E(aicarcontroller_set_current_route),             //  40  0x00190670
    E(aicarcontroller_get_current_route),             //  48  0x00190708
    E(aicarcontroller_get_current_route_point),       //  56  0x00190760
    E(aicarcontroller_get_amount_out_of_bounds),      //  64  0x001907b8
    E(aicarcontroller_find_where_i_am),               //  72  0x00192f10
    E(aicarcontroller_just_reset),                    //  80  0x00190850
    E(aicarcontroller_set_to_physics_mode),           //  88  0x00193650
    E(aicarcontroller_force_boost),                   //  96  0x00193758
    E(aicarcontroller_release_boost),                 // 104  0x00193780
    { 0, 0, NULL },                                   // 112  pure
    E(aicarcontroller_choose_new_action),             // 120  0x00192780
    E(aicarcontroller_generate_points_to_fulfill_action), // 128  0x00192668
};

#undef E

void aicarcontroller_install_vtables(void)
{
    vt_install(AICARCONTROLLER_VTABLE, aicarcontroller_vt,
               AICARCONTROLLER_VT_ENTRIES);
}
