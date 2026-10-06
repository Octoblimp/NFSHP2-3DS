// drivingchoice -- see drivingchoice.h.

#include "drivingchoice.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "aicarcontroller.h"
#include "bvector.h"
#include "carcollisionpredict.h"
#include "cardriver.h"
#include "cartypeinfo.h"
#include "collisionbody.h"   // WilliamsAITuningMode
#include "drivetarget.h"
#include "drivinglocation.h"
#include "eefpu.h"
#include "nearbycar.h"
#include "race.h"
#include "racecore.h"
#include "trackroute.h"
#include "world.h"

AISignPostDecisionFn gAISignPostDecisionFn;

int32_t AITrafficTuningMode;           // gp-15152, 0x00331dc0
float   AISlowCarSpeed = 20.0f;        // gp-15120, 0x00331de0
float   AISlowTrafficSpeed = 10.0f;    // gp-15116, 0x00331de4
float   TryToDriveAroundCarMinSpeedForDrivingLine = 20.0f; // gp-15136

// AICarController.obj's (0x00330a48), here until step 11e ports the
// controller.
int32_t AICarControllerNumDrivingLinesToConsider = 1;      // gp-20136

// Retail's constants. The two speeds are 60 and 66 mph in metres a second.
#define DC_ON_ROAD          -0.00100000005f  // gp-26600, IsEnoughRoom
#define DC_ROOM_MARGIN       5.0f            // lui 0x40a0
#define DC_TRAFFIC_NEAR      5.0f            // lui 0x40a0
#define DC_NEAR_LINE         1.0f            // lui 0x3f80
#define DC_FAR_AHEAD         50.0f           // lui 0x4248
#define DC_BENDING           0.119999997f    // gp-26592
#define DC_SLOW              26.8216362f     // gp-26588
#define DC_FAST              29.5038013f     // gp-26584
#define DC_SPEED_SLOW_BACK   0.25f           // lui 0x3e80
#define DC_SPEED_FAST_BACK   0.5f            // lui 0x3f00
#define DC_PAST_TARGET      -10.0f           // lui 0xc120
#define DC_MIN_POINTS        5
#define DC_EDGE              1.0f            // lui 0x3f80, ReduceCurrentL
#define DC_EXTRA_LATERAL     4.0f            // lui 0x4080
#define DC_FAR_OFF_ROAD      5.0f            // lui 0x40a0
#define DC_PARALLEL_SPEED    5.0f            // lui 0x40a0
#define DC_PARALLEL_WHEELS   3
#define DC_SAME_HEADING      0.707099974f    // gp-26580, cos 45
#define DC_NO_EDGE           999999.0f       // gp-26572, and gp-26576 less
#define DC_FAR_AWAY          1.0e14f         // gp-26568
#define DC_SEARCH_STEP       0.0416666679f   // gp-26564, 1/24
#define DC_GAP               2.0f            // lui 0x4000
#define DC_GAP_PLAYER        1.5f            // lui 0x3fc0
#define DC_GAP_SLOW          6.0f            // lui 0x40c0
#define DC_NO_HIT            99999.0f        // gp-26628, -26620, -26608, -26596
#define DC_PREFERRED         1.20000005f     // gp-26624
#define DC_HIT_MARGIN        0.100000001f    // gp-26616
#define DC_NO_SCORE          0.00100000005f  // gp-26612, gp-26604

// `min.s` and `max.s`, fs then ft, as collision.c has them.
static float min_s(float fs, float ft)
{
    return ft < fs ? ft : fs;
}

static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

// TheTrackRouteManager's pTrackRoutes[n], NULL for a negative n as the
// image's `bltz` has it. The image has no bound above; trmgr_get_route's is
// the one drivetarget.c uses too.
static TrackRoute *route_numbered(int32_t n)
{
    return trmgr_get_route(&TheTrackRouteManager, n);
}

// How far `pos` is to the right of `p`'s line through it.
static float lateral(const TrackRoutePoint *p, float x, float y)
{
    return (x - p->Position.x) * p->Direction.y
           - (y - p->Position.y) * p->Direction.x;
}

// A future point's route point. Every list the port walks is filled from
// routes filed under their numbers.
static TrackRoutePoint *fp_point(const FuturePoint *fp)
{
    return troute_get_point(route_numbered(fp->nRouteNumber),
                            fp->nPointNumber);
}

// 0x002455b0. How far `l` across `p` is off the road: past the right edge
// for an `l` above 0, past the left otherwise; negative on it.
static float amount_out_of_bounds(const TrackRoutePoint *p, float l)
{
    if (0.0f < l)
        return l - p->RightWidth;
    return -(l + p->LeftWidth);
}

// ------------------------------------------------- the small methods

DrivingChoiceType drivingchoice_get_choice_type(int32_t line)
{
    // 0x00241c00.
    return line % 2 + 1;
}

int32_t drivingchoice_get_driving_line(DrivingChoiceType type, Car *car)
{
    // 0x00241c20. `lb 230(pCarTypeInfo)`.
    return (int32_t)car->pCarTypeInfo->CarClass * 2 + (type - 1);
}

void drivingchoice_set_choice(DrivingChoice *d, DrivingChoiceType type,
                              Car *car, int extra)
{
    // 0x00241cf8. Two `movz`s and a `movn` for the test; the stores are
    // the bool, the type and the car, in that order.
    int ok;

    if (drivingchoice_type_is_driving_line(type))
        ok = car == NULL;
    else
        ok = drivingchoice_type_is_side_of_car(type) && car != NULL;
    if (ok) {
        d->UseExtraLateralDistance = extra;
        d->Type = type;
        d->pCar = car;
    }
}

void drivingchoice_set_choice_location(DrivingChoice *d,
                                       const DrivingLocation *loc)
{
    // 0x001cacc8.
    drivingchoice_set_choice(d, drivingchoice_get_choice_type(loc->DrivingLine),
                             NULL, 0);
}

void drivingchoice_set_choice_choice(DrivingChoice *d,
                                     const DrivingChoice *other)
{
    // 0x00245370. GetType (0x002455f8), GetCar (0x002455f0) and
    // GetUseExtraLateralDistance (0x002455e8), then SetChoice.
    drivingchoice_set_choice(d, other->Type, other->pCar,
                             other->UseExtraLateralDistance);
}

void drivingchoice_clear(DrivingChoice *d)
{
    // 0x002453e0. The bool, the type, the car.
    d->UseExtraLateralDistance = 0;
    d->Type = CHOICE_NONE;
    d->pCar = NULL;
}

int drivingchoice_is_valid(const DrivingChoice *d, const DrivingLocation *loc,
                           NearbyCarList *list)
{
    // 0x00241d40.
    if (drivingchoice_type_is_driving_line(d->Type)) {
        int32_t rn = drivinglocation_is_clear(loc)
                         ? -1 : (int32_t)loc->pRoute->RouteNumber;

        if ((uint32_t)rn < 50u) {
            uint32_t flags = loc->pRoute->DrivingLineInfoTable[
                drivingchoice_get_driving_line(d->Type, list->MyCar)].Flags;

            return (flags & DLI_IS_VALID) != 0 || ((flags >> 1) & 1u) != 0;
        }
        // A traffic route has one line.
        if ((uint32_t)(rn - 50) < 20u)
            return d->Type == CHOICE_DRIVING_LINE_0;
        return 0;
    }
    if (drivingchoice_type_is_side_of_car(d->Type))
        return nearbycarlist_get_nearby_car(list, d->pCar) != NULL;
    return 0;
}

int drivingchoice_is_equal_to(const DrivingChoice *d,
                              const DrivingChoice *other)
{
    // 0x00241e30.
    if (drivingchoice_type_is_side_of_car(d->Type))
        return d->pCar == other->pCar && d->Type == other->Type;
    return d->Type == other->Type;
}

int drivingchoice_is_enough_room(const DrivingChoice *d, NearbyCar *nc,
                                 NearbyCarList *list)
{
    // 0x00242b08. Retail's GetRoutePoint takes a bool, 1 here, that only
    // AICarController's reads (step 11e); car_get_route_point has none yet.
    TrackRoutePoint *rp;
    float room, lat;

    if (drivingchoice_type_is_driving_line(d->Type))
        return 1;
    if (!drivingchoice_type_is_side_of_car(d->Type))
        return 0;
    if (!(car_get_amount_out_of_bounds(d->pCar) < DC_ON_ROAD))
        return 1;

    rp = car_get_route_point(d->pCar);
    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;
    lat = lateral(rp, d->pCar->State.Position.x, d->pCar->State.Position.y);
    if (d->Type == CHOICE_LEFT_SIDE_OF_CAR)
        return -rp->LeftWidth < lat - room;
    return lat + room < rp->RightWidth;
}

void drivingchoice_fixup_car_to_exclude_from_collision_prediction(
    const DrivingChoice *d, Car *car, int check, NearbyCarList *list)
{
    // 0x00243160.
    int ok;
    Car *other;

    if (drivingchoice_type_is_driving_line(d->Type)) {
        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;
        return;
    }
    if (!drivingchoice_type_is_side_of_car(d->Type))
        return;
    if (!check) {
        car_ai_controller(car)->CarToExcludeFromCollisionPrediction = NULL;
        return;
    }

    ok = 1;
    other = d->pCar;
    if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
        && other->State.BodyMatrix.v0.x * car->State.BodyMatrix.v0.x
           + other->State.BodyMatrix.v0.y * car->State.BodyMatrix.v0.y
           < 0.0f) {
        // A traffic car coming the other way.
        AICarController *oc = car_ai_controller(other);
        DrivingChoice *its = oc->CurrentDrivingChoice;
        AIActionType act = oc->CurrentAction != NULL
                               ? oc->CurrentAction->Type : AIACTION_NONE;

        if (drivingchoice_type_is_side_of_car(its->Type)
            && its->pCar == car) {
            if (its->Type == CHOICE_LEFT_SIDE_OF_CAR) {
                if (d->Type == CHOICE_RIGHT_SIDE_OF_CAR)
                    ok = 0;
            } else if (its->Type == CHOICE_RIGHT_SIDE_OF_CAR
                       && d->Type == CHOICE_LEFT_SIDE_OF_CAR) {
                ok = 0;
            }
        }
        if (act == AIACTION_PULL_OVER && d->Type == CHOICE_LEFT_SIDE_OF_CAR)
            ok = 0;
    }
    if (!ok)
        return;
    if (!drivingchoice_is_enough_room(
            d, nearbycarlist_get_nearby_car(list, d->pCar), list))
        return;
    car_ai_controller(car)->CarToExcludeFromCollisionPrediction = d->pCar;
}

int drivingchoice_get_preferred_side_of_car(NearbyCar *nc, NearbyCarList *list,
                                            DrivingLocation *loc)
{
    // 0x002432e8. Static: the image's `this` is never read.
    float curv = ai_get_current_curvature_of_driving_line(loc);
    TrackRoutePoint *p = loc->pRoutePoint;
    int32_t line = loc->DrivingLine;
    Car *other = nc->TheCar;
    Car *me = list->MyCar;
    TrackRoutePoint *cp;
    float otherLat, otherOff, myOff, room;
    int left = 1, decided = 0, blocked;

    cp = troute_find_closest_point_ahead(
        loc->pRoute, (const bVector2 *)&other->State.Position, p);
    if (cp == NULL)
        cp = p;

    otherLat = lateral(cp, other->State.Position.x, other->State.Position.y);
    otherOff = otherLat - trpoint_get_driving_line_offset(cp, line);
    myOff = lateral(p, me->State.Position.x, me->State.Position.y)
            - trpoint_get_driving_line_offset(p, line);

    // A traffic car passes one near its line on the right.
    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
        && otherOff < DC_TRAFFIC_NEAR) {
        decided = 1;
        left = 0;
    }
    // Both on the line, the other well ahead, in a bend: the inside.
    if (!decided && fabsf(myOff) <= DC_NEAR_LINE
        && fabsf(otherOff) <= DC_NEAR_LINE && DC_FAR_AHEAD < nc->Position.y
        && DC_BENDING <= fabsf(curv)) {
        left = 0.0f < curv ? 0 : 1;
        decided = 1;
    }
    // Otherwise the side away from it.
    if (!decided)
        left = otherOff < myOff ? 0 : 1;

    room = (nc->ApparentHalfSizeL + list->MyHalfSizeL) + DC_ROOM_MARGIN;
    if (left)
        blocked = otherLat - room < -cp->LeftWidth;
    else
        blocked = cp->RightWidth < otherLat + room;
    return blocked ? !left : left;
}

// ------------------------------------------- the walk along the route

void futurepointlist_add(FuturePointList *l, int32_t route, int32_t point,
                         int32_t line, float offset, int crossed)
{
    // 0x00244768. The count is reloaded for each store.
    FuturePoint *p = &l->Points[l->NumPoints];

    p->nRouteNumber = route;
    p->nPointNumber = point;
    p->nLine = line;
    l->NumPoints++;
    p->bCrossedSignpost = crossed;
    p->fOffset = offset;
}

int drivingchoice_advance_point(TrackRoute **route, TrackRoutePoint **point,
                                int32_t *pointNumber, float *offset,
                                int *crossed, int32_t *line,
                                AICarController *ctrl)
{
    // 0x00244588. The image's first argument is never read.
    int32_t n;

    if (trpoint_has_signpost(*point)) {
        Signpost *s = trpoint_get_signpost(*point);
        // The old line's offset is read before the decision, which may
        // change the line; the new point's after it.
        float off = trpoint_get_driving_line_offset(*point, *line);

        if (gAISignPostDecisionFn != NULL
            && gAISignPostDecisionFn(ctrl, s, line,
                                     ctrl->CurrentDrivingLocation)) {
            bVector3 pos;
            TrackRoutePoint *np;

            trpoint_get_position3(*point, &pos, 0.0f, off);
            *route = signpost_get_new_route(s);
            np = signpost_get_new_route_point(s);
            *point = np;
            *pointNumber = troute_get_point_number(*route, np);
            *crossed = 1;
            *offset = lateral(np, pos.x, pos.y)
                      - trpoint_get_driving_line_offset(np, *line);
            return 1;
        }
    }

    n = ++*pointNumber;
    if (!(n < (*route)->NumPoints))
        return 0;
    *offset = 0.0f;
    *crossed = 0;
    *point = troute_get_point(*route, n);
    return 1;
}

void drivingchoice_get_route_points_to_use(FuturePointList *l, DriveTarget *t,
                                           DrivingLocation *loc,
                                           NearbyCarList *list,
                                           float *currentL)
{
    // 0x002447c0.
    Car *me = list->MyCar;
    AICarController *ctrl = car_ai_controller(me);
    TrackRoute *route = loc->pRoute;
    TrackRoutePoint *point;
    int32_t ptnum, line = loc->DrivingLine;
    float offset = 0.0f;
    int crossed = 0;
    int i;
    float dist, lookAhead;

    l->NumPoints = 0;
    ptnum = drivinglocation_is_clear(loc)
                ? -1 : troute_get_point_number(loc->pRoute, loc->pRoutePoint);
    point = loc->pRoutePoint;

    // From the target's last point, 10 m past it.
    i = t->NumPoints - 1;
    if (i >= 0) {
        const bVector3 *last = &t->Points[i];

        route = route_numbered(t->Route[i]);
        // The image reads a missing route's Type at address 12 and walks
        // on from address 1064. The port leaves the list empty.
        if (route == NULL)
            return;
        if (me->MyDriver->TheDriverType == DRIVER_TYPE_AI_RACER
            && route->Type == TRACK_ROUTE_TRAFFIC) {
            // A racer whose target ends on a traffic route walks its own
            // route from where it is.
            route = loc->pRoute;
        } else {
            ptnum = t->RoutePointNumber[i];
            line = t->DrivingLine[i];
            point = troute_get_point(route, ptnum);
        }
        do {
            if (!drivingchoice_advance_point(&route, &point, &ptnum, &offset,
                                             &crossed, &line, ctrl))
                return;
        } while (DC_PAST_TARGET < (last->x - point->Position.x)
                                      * point->Direction.x
                                  + (last->y - point->Position.y)
                                      * point->Direction.y);
    }
    if (point == NULL)
        return;

    // Where the target ends, across the location's line.
    if (t->NumPoints == 0) {
        *currentL = lateral(point, me->State.Position.x, me->State.Position.y);
    } else {
        TrackRoute *r2;
        TrackRoutePoint *p2;

        if (drivetarget_get_route_and_route_point(t, t->NumPoints - 1, &r2,
                                                  &p2))
            *currentL = lateral(p2, t->Points[t->NumPoints - 1].x,
                                t->Points[t->NumPoints - 1].y);
        else
            *currentL = lateral(point, t->Points[t->NumPoints - 1].x,
                                t->Points[t->NumPoints - 1].y);
    }
    *currentL = *currentL - trpoint_get_driving_line_offset(point,
                                                            loc->DrivingLine);

    futurepointlist_add(l, route->RouteNumber,
                        troute_get_point_number(route, point), line, offset, 0);
    // Always: the count was 0. The second point is never marked crossed.
    if (l->NumPoints == 1) {
        if (!drivingchoice_advance_point(&route, &point, &ptnum, &offset,
                                         &crossed, &line, ctrl))
            return;
        futurepointlist_add(l, route->RouteNumber,
                            troute_get_point_number(route, point), line,
                            offset, 0);
    }

    // Then on to the look-ahead, at least five and at most twenty.
    dist = sqrtf((me->State.Position.x - point->Position.x)
                     * (me->State.Position.x - point->Position.x)
                 + (me->State.Position.y - point->Position.y)
                     * (me->State.Position.y - point->Position.y));
    lookAhead = ai_calculate_look_ahead_distance(me);
    for (;;) {
        int more;

        if (!(dist <= lookAhead) && !(l->NumPoints < DC_MIN_POINTS))
            return;
        more = l->NumPoints < FUTUREPOINTLIST_MAX;
        dist = dist + point->Length;
        if (!more)
            return;
        if (!drivingchoice_advance_point(&route, &point, &ptnum, &offset,
                                         &crossed, &line, ctrl))
            return;
        futurepointlist_add(l, route->RouteNumber,
                            troute_get_point_number(route, point), line,
                            offset, crossed);
    }
}

void drivingchoice_get_route_points_up_to(FuturePointList *l,
                                          DrivingLocation *loc,
                                          TrackRoutePoint *end)
{
    // 0x00244c88. For a clear location the image walks from point -1 of
    // route -1 to `end`'s index counted from address 0; the port leaves the
    // list empty.
    int32_t rn, line, i, last;

    l->NumPoints = 0;
    if (drivinglocation_is_clear(loc))
        return;
    rn = loc->pRoute->RouteNumber;
    line = loc->DrivingLine;
    i = troute_get_point_number(loc->pRoute, loc->pRoutePoint);
    last = troute_get_point_number(loc->pRoute, end);
    for (; !(last < i) && l->NumPoints < FUTUREPOINTLIST_MAX; i++)
        futurepointlist_add(l, rn, i, line, 0.0f, 0);
}

float drivingchoice_get_speed_back_to_line(NearbyCarList *list,
                                           DrivingLocation *loc,
                                           MovementWithRespectToLine m)
{
    // 0x002438b0.
    float v;

    if (m == MOVEMENT_PARALLEL_TO_LINE)
        return 0.0f;
    if ((uint32_t)(m - MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) < 2u
        || list->MyCar->TheControlMode == TRAFFIC_CONTROL)
        return DC_SPEED_FAST_BACK;
    if (race_grace_period_is_active(pCurrentRace, list->MyCar))
        return 0.0f;
    v = list->MyCar->State.VelocityMagnitude;
    if (v <= DC_SLOW)
        return 0.0f;
    if (v <= DC_FAST)
        return DC_SPEED_SLOW_BACK;
    return drivinglocation_are_we_in_a_relaxed_switch(loc)
               ? DC_SPEED_SLOW_BACK : DC_SPEED_FAST_BACK;
}

void drivingchoice_reduce_current_l(float *l, MovementWithRespectToLine m,
                                    TrackRoutePoint *point, int32_t line,
                                    float amount, float halfWidth, int inside)
{
    // 0x00243988.
    float off, hi, lo;

    if (m == MOVEMENT_TOWARDS_RIGHT_SIDE_OF_TRACK) {
        *l = *l + amount;
    } else if (m == MOVEMENT_TOWARDS_LEFT_SIDE_OF_TRACK) {
        *l = *l - amount;
    } else {
        float cur = *l;

        if (cur < 0.0f)
            *l = amount < -cur ? cur + amount : 0.0f;
        else
            *l = amount < cur ? cur - amount : 0.0f;
    }

    off = trpoint_get_driving_line_offset(point, line);
    if (inside) {
        hi = (point->RightWidth - DC_EDGE) - halfWidth;
        lo = (DC_EDGE - point->LeftWidth) + halfWidth;
    } else {
        hi = point->RightWidth;
        lo = -point->LeftWidth;
    }
    *l = min_s(hi - off, max_s(*l, lo - off));
}

void drivingchoice_add_to_drive_target(float l, DrivingLocation *loc,
                                       FuturePoint *p, DriveTarget *t)
{
    // 0x002437e8. The location is not read.
    TrackRoutePoint *pt = troute_get_point(route_numbered(p->nRouteNumber),
                                           p->nPointNumber);
    bVector3 pos;

    (void)loc;
    // GetPosition writes x, y and z, and AddPointToTarget copies all
    // sixteen bytes: the image's w is the stack's. STACK-W, as in
    // drivetarget.c.
    pos.pad = 0.0f;
    trpoint_get_position3(pt, &pos, 0.0f,
                          l + trpoint_get_driving_line_offset(pt, p->nLine));
    drivetarget_add_point3(t, &pos, (int8_t)p->nRouteNumber,
                           (int16_t)p->nPointNumber, (int8_t)p->nLine, 1,
                           NULL);
}

void drivingchoice_fill_up_drive_target(DriveTarget *t, DrivingLocation *loc,
                                        NearbyCarList *list,
                                        MovementWithRespectToLine m,
                                        int inside)
{
    // 0x00243568. Static: no `this`.
    FuturePointList fl;
    float ls[FUTUREPOINTLIST_MAX];
    float l, speed;
    DrivingChoice dc;
    int i;

    if (loc == NULL || t == NULL || list == NULL)
        return;
    if (drivinglocation_is_clear(loc))
        return;
    // The terrain is stored before the test, in its delay slot.
    t->TType = (int32_t)trpoint_terrain_type(loc->pRoutePoint);
    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))
        return;

    fl.NumPoints = 0;
    l = 0.0f;
    drivingchoice_get_route_points_to_use(&fl, t, loc, list, &l);
    speed = drivingchoice_get_speed_back_to_line(list, loc, m);

    for (i = 0; i < fl.NumPoints; i++) {
        FuturePoint *fp = &fl.Points[i];
        TrackRoutePoint *pt = troute_get_point(
            route_numbered(fp->nRouteNumber), fp->nPointNumber);

        // Past a sign the line is a new route's: no faster than 0.25.
        if (m == MOVEMENT_TOWARDS_LINE && fp->bCrossedSignpost)
            speed = min_s(speed, DC_SPEED_SLOW_BACK);
        drivingchoice_reduce_current_l(&l, m, pt, loc->DrivingLine, speed,
                                       list->MyHalfSizeL, inside);
        l = l + fp->fOffset;
        ls[i] = l;
    }
    for (i = 0; i < fl.NumPoints; i++) {
        if (WilliamsAITuningMode != 0 && m == MOVEMENT_TOWARDS_LINE)
            ls[i] = 0.0f;
        drivingchoice_add_to_drive_target(ls[i], loc, &fl.Points[i], t);
    }

    // The image's choice is not initialised, and SetChoice leaves it so
    // for a negative odd line. The port's starts as Clear leaves one.
    drivingchoice_clear(&dc);
    drivingchoice_set_choice_location(&dc, loc);
    drivingchoice_fixup_car_to_exclude_from_collision_prediction(
        &dc, list->MyCar, 0, list);
}

// ---------------------------------------- the target, and round a car

int32_t futurepointlist_find_closest_point_ahead(const FuturePointList *l,
                                                 const bVector2 *pos,
                                                 int32_t start)
{
    // 0x00244d80. `pmaxw` with zero for the start, the count read once.
    int32_t n = l->NumPoints;
    int32_t i = start < 0 ? 0 : start;
    int32_t best = -1;
    float bestDist = DC_FAR_AWAY;

    while (i < n) {
        const TrackRoutePoint *p = fp_point(&l->Points[i]);
        float dx = p->Position.x - pos->x;
        float dy = p->Position.y - pos->y;
        float d = sqrtf(dx * dx + dy * dy);
        float ahead = -((pos->x - p->Position.x) * p->Direction.x
                        + (pos->y - p->Position.y) * p->Direction.y);
        int32_t skip;

        if (0.0f < ahead && d < bestDist) {
            bestDist = d;
            best = i;
        }
        // `cvt.w.s`, then `slt` and `mult` for the max with 0. The add
        // wraps as the image's does, past 5e10 m.
        skip = ee_trunc_w(d * DC_SEARCH_STEP) - 2;
        i = (int32_t)((uint32_t)i + (uint32_t)(0 < skip ? skip : 0) + 1u);
    }
    return best;
}

void drivingchoice_do_smooth_offset_change(FuturePointList *l, DriveTarget *t,
                                           NearbyCarList *list, int32_t index,
                                           float fromL, float toL, int inside)
{
    // 0x00244ea0.
    int32_t last = index - 2, i;
    const TrackRoutePoint *p0, *pe;
    bVector2 a, b;
    float slope;

    if (last + 1 < 2)
        return;
    p0 = fp_point(&l->Points[0]);
    pe = fp_point(&l->Points[last]);
    trpoint_get_position2(p0, &a, 0.0f,
                          trpoint_get_driving_line_offset(p0,
                                                          l->Points[0].nLine));
    trpoint_get_position2(pe, &b, 0.0f,
                          trpoint_get_driving_line_offset(pe,
                                                          l->Points[last].nLine));
    // ee_div: the first and last points can be in one place (a point
    // twice, or a sign's route starting where the sign is), and the EE's
    // FLT_MAX there takes every point but the first to toL, where IEEE's
    // 0/0 would be a NaN.
    slope = ee_div(toL - fromL,
                   sqrtf((a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y)));
    if (!(t->NumPoints < DRIVETARGET_MAX_POINTS))
        return;

    i = 0;
    do {
        const FuturePoint *fp = &l->Points[i];
        const TrackRoutePoint *p = fp_point(fp);
        bVector2 c;
        bVector3 pos;
        float cur, lo, hi;

        trpoint_get_position2(p, &c, 0.0f,
                              trpoint_get_driving_line_offset(p, fp->nLine));
        cur = fromL + sqrtf((a.x - c.x) * (a.x - c.x)
                            + (a.y - c.y) * (a.y - c.y)) * slope;
        // No further than toL, either way.
        if (fromL < toL) {
            if (toL < cur)
                cur = toL;
        } else if (toL <= fromL) {
            if (cur < toL)
                cur = toL;
        }
        cur = (cur + trpoint_get_driving_line_offset(p, fp->nLine))
              + fp->fOffset;
        if (inside) {
            lo = (DC_EDGE - p->LeftWidth) + list->MyHalfSizeL;
            hi = (p->RightWidth - DC_EDGE) - list->MyHalfSizeL;
        } else {
            lo = -p->LeftWidth;
            hi = p->RightWidth;
        }
        // STACK-W, as in drivingchoice_add_to_drive_target.
        pos.pad = 0.0f;
        trpoint_get_position3(p, &pos, 0.0f, min_s(hi, max_s(cur, lo)));
        drivetarget_add_point3(t, &pos, (int8_t)fp->nRouteNumber,
                               (int16_t)fp->nPointNumber, (int8_t)fp->nLine,
                               1, NULL);
        i++;
    } while (!(last < i) && t->NumPoints < DRIVETARGET_MAX_POINTS);
}

float drivingchoice_get_clearance(NearbyCarList *list, NearbyCar *nc,
                                  const FuturePointList *l, int32_t index)
{
    // 0x002442c0. The image's first argument, the choice, is never read.
    Car *me, *other;
    float gap = 0.0f, least, v;

    if (nc == NULL)
        return 0.0f;
    me = list->MyCar;
    other = nc->TheCar;
    if (l->NumPoints != 0) {
        if (index == -1)
            index = futurepointlist_find_closest_point_ahead(
                l, (const bVector2 *)&other->State.Position, 0);
        if (index != -1) {
            const FuturePoint *f0 = &l->Points[0], *fi = &l->Points[index];
            const TrackRoutePoint *p0 = fp_point(f0), *pi = fp_point(fi);
            float mine, its;

            mine = (lateral(p0, me->State.Position.x, me->State.Position.y)
                    - trpoint_get_driving_line_offset(p0, f0->nLine))
                   + f0->fOffset;
            its = (lateral(pi, other->State.Position.x,
                           other->State.Position.y)
                   - trpoint_get_driving_line_offset(pi, fi->nLine))
                  + fi->fOffset;
            gap = (fabsf(mine - its) - list->MyHalfSizeL)
                  - nc->ApparentHalfSizeL;
        }
    }

    v = fabsf(other->State.VelocityMagnitude);
    if (me->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR)
        least = DC_GAP;
    else if (other->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
                 ? v <= AISlowTrafficSpeed : v <= AISlowCarSpeed)
        least = DC_GAP_SLOW;
    else
        least = other->pPlayer != NULL ? DC_GAP_PLAYER : DC_GAP;
    return max_s(gap, least);
}

void drivingchoice_make_drive_target_parallel_to_car(
    const DrivingChoice *d, DriveTarget *t, NearbyCarList *list,
    const FuturePointList *l, float side)
{
    // 0x00243f70.
    Car *other = d->pCar, *me = list->MyCar;
    DriveTarget *its;
    TrackRoute *r = NULL;
    TrackRoutePoint *p = NULL;
    bVector2 mine, theirs;
    int32_t j, from = 0;

    if (!(DC_PARALLEL_SPEED < other->State.VelocityMagnitude))
        return;
    if (!(DC_PARALLEL_SPEED < me->State.VelocityMagnitude))
        return;
    if (other->State.nWheelsTouchingGround < DC_PARALLEL_WHEELS)
        return;
    bNormalize2(&mine, (const bVector2 *)&me->State.Velocity);
    bNormalize2(&theirs, (const bVector2 *)&other->State.Velocity);
    if (!(DC_SAME_HEADING < mine.x * theirs.x + mine.y * theirs.y))
        return;

    its = &other->pCarDriver->MyDriveTarget;
    j = drivetarget_get_first_point(its, &other->State);
    while (t->NumPoints < DRIVETARGET_MAX_POINTS
           && drivetarget_get_route_and_route_point(its, j, &r, &p)) {
        const bVector3 *q = &its->Points[j];
        float want = lateral(p, q->x, q->y) + side;
        float lo = -DC_NO_EDGE, hi = DC_NO_EDGE, m;
        bVector3 pos;

        if (r->Type != TRACK_ROUTE_TRAFFIC) {
            lo = -p->LeftWidth;
            hi = p->RightWidth;
        } else {
            // On a traffic route, the road is our route's where it is
            // nearest ahead of the point; with none ahead, no edge.
            from = futurepointlist_find_closest_point_ahead(
                l, (const bVector2 *)&p->Position, from);
            if (from != -1) {
                const TrackRoutePoint *e = fp_point(&l->Points[from]);
                bVector2 le, re;
                float ll, rl;

                trpoint_get_position2(e, &le, 0.0f, -e->LeftWidth);
                trpoint_get_position2(e, &re, 0.0f, e->RightWidth);
                rl = lateral(p, re.x, re.y);
                ll = lateral(p, le.x, le.y);
                if (ll < rl) {
                    lo = ll;
                    hi = rl;
                } else {
                    lo = rl;
                    hi = ll;
                }
            }
        }
        m = list->MyHalfSizeL + DC_EDGE;
        lo = lo + m;
        hi = hi - m;
        // STACK-W.
        pos.pad = 0.0f;
        trpoint_get_position3(p, &pos, 0.0f, min_s(hi, max_s(want, lo)));
        drivetarget_add_point3(t, &pos, its->Route[j],
                               its->RoutePointNumber[j], its->DrivingLine[j],
                               1, me);
        j++;
    }
}

int drivingchoice_build_drive_target_around_car(DrivingChoice *d,
                                                DriveTarget *t,
                                                NearbyCarList *list,
                                                float unused,
                                                DrivingLocation *loc)
{
    // 0x00243aa8.
    FuturePointList fl;
    NearbyCar *nc;
    float currentL;
    int32_t idx;
    int done = 0;

    (void)unused;
    fl.NumPoints = 0;
    nc = nearbycarlist_get_nearby_car(list, d->pCar);
    currentL = 0.0f;
    drivingchoice_get_route_points_to_use(&fl, t, loc, list, &currentL);
    // The image reads the entry's car with no test: BuildDriveTarget only
    // comes here once IsValid has found the car on the list. The port
    // takes a missing one as a car not on the route ahead.
    if (fl.NumPoints != 0 && nc != NULL
        && (idx = futurepointlist_find_closest_point_ahead(
                &fl, (const bVector2 *)&nc->TheCar->State.Position, 0))
               != -1) {
        const FuturePoint *fp = &fl.Points[idx];
        TrackRoute *r;
        TrackRoutePoint *p;
        Car *other = nc->TheCar, *it;
        float clearance, side, room, lat, along, passL;
        int32_t line;
        DriverType its;

        clearance = drivingchoice_get_clearance(list, nc, &fl, idx);
        if (d->UseExtraLateralDistance)
            clearance = clearance + DC_EXTRA_LATERAL;
        r = route_numbered(fp->nRouteNumber);
        p = troute_get_point(r, fp->nPointNumber);
        line = fp->nLine;
        lat = lateral(p, other->State.Position.x, other->State.Position.y);
        if (amount_out_of_bounds(p, lat) < DC_FAR_OFF_ROAD) {
            bVector3 pos;

            // Retail tests a debug word here (gp-15124, 0) and, when it is
            // set, counts down the list's points with nothing done.
            side = d->Type == CHOICE_LEFT_SIDE_OF_CAR ? -1.0f : 1.0f;
            if (list->MyCar->MyDriver->TheDriverType
                    == DRIVER_TYPE_TRAFFIC_CAR
                && AITrafficTuningMode != 0)
                side = -side;
            room = side * ((list->MyHalfSizeL + nc->ApparentHalfSizeL)
                           + clearance);
            along = (other->State.Position.x - p->Position.x)
                        * p->Direction.x
                    + (other->State.Position.y - p->Position.y)
                        * p->Direction.y;
            passL = min_s((p->RightWidth - DC_EDGE) - list->MyHalfSizeL,
                          max_s((lat + room) + fp->fOffset,
                                list->MyHalfSizeL
                                    - (p->LeftWidth - DC_EDGE)));

            // The point beside the car, the way out to it, then the point.
            pos.pad = 0.0f;   // STACK-W
            trpoint_get_position3(p, &pos, along, passL);
            drivingchoice_do_smooth_offset_change(
                &fl, t, list, idx, currentL,
                passL - trpoint_get_driving_line_offset(p, line), 1);
            drivetarget_add_point3(t, &pos, (int8_t)r->RouteNumber,
                                   (int16_t)troute_get_point_number(r, p),
                                   (int8_t)line, 1, NULL);
            t->LastPointToScore = (int8_t)(t->NumPoints - 1);

            // Alongside a player that is no cop, or traffic when this is
            // not traffic, follow its own target.
            it = d->pCar;
            its = it->MyDriver->TheDriverType;
            if (it->pPlayer != NULL
                    ? its != DRIVER_TYPE_COP
                    : its == DRIVER_TYPE_TRAFFIC_CAR
                          && list->MyCar->MyDriver->TheDriverType
                                 != DRIVER_TYPE_TRAFFIC_CAR)
                drivingchoice_make_drive_target_parallel_to_car(d, t, list,
                                                                &fl, room);
            drivingchoice_fill_up_drive_target(t, loc, list,
                                               MOVEMENT_PARALLEL_TO_LINE, 1);
            done = 1;
        }
    }
    if (!done)
        drivingchoice_fill_up_drive_target(t, loc, list,
                                           MOVEMENT_PARALLEL_TO_LINE, 1);
    return done;
}

int drivingchoice_build_drive_target(DrivingChoice *d, DriveTarget *t,
                                     DrivingLocation *loc, NearbyCarList *list,
                                     float unusedA, float unusedB,
                                     MovementWithRespectToLine m)
{
    // 0x00241ea0.
    int built = 0;

    (void)unusedA;
    (void)unusedB;
    drivetarget_assign(t, &list->MyCar->pCarDriver->MyDriveTarget);
    drivetarget_clear(t, list->MyCar, 0.0f);
    if (!drivingchoice_is_valid(d, loc, list)) {
        drivingchoice_fill_up_drive_target(t, loc, list, m, 1);
    } else if (drivingchoice_type_is_driving_line(d->Type)) {
        DrivingLocation onLine = *loc;

        drivinglocation_set_driving_line(
            &onLine, drivingchoice_get_driving_line(d->Type, list->MyCar), 0);
        drivingchoice_fill_up_drive_target(t, &onLine, list, m, 1);
        built = 1;
    } else {
        built = drivingchoice_build_drive_target_around_car(d, t, list, 0.0f,
                                                            loc);
    }
    drivingchoice_fixup_car_to_exclude_from_collision_prediction(
        d, list->MyCar, 0, list);
    return built;
}

// ------------------------------------------------ choosing a new choice

int drivingchoice_is_driveable(DrivingChoice *d, DriveTarget *t,
                               int preferred, float *score, Car **hitCar,
                               float *hitTime, DrivingLocation *loc,
                               NearbyCarList *list, float unusedA,
                               float maxTime, float unusedC,
                               MovementWithRespectToLine m)
{
    // 0x00241ff8.
    int ok = 0;

    (void)unusedC;
    *score = -1.0f;
    *hitCar = NULL;
    *hitTime = DC_NO_HIT;
    if (drivingchoice_build_drive_target(d, t, loc, list, unusedA, maxTime,
                                         m)) {
        float s = drivetarget_estimate_score(t, list->MyCar);

        *score = s;
        if (-1.0f < s) {
            AICarController *c = car_ai_controller(list->MyCar);

            if (preferred) {
                *score = s * DC_PREFERRED;
                c->CarToExcludeFromCollisionPrediction = d->pCar;
            } else {
                c->CarToExcludeFromCollisionPrediction = NULL;
            }
            *hitCar = ccp_who_will_this_drive_target_hit(t, list, loc,
                                                         maxTime, hitTime);
            if (maxTime < *hitTime)
                ok = 1;
        }
    }
    pCurrentWorld->PotentialDriveTargetID++;
    return ok;
}

int drivingchoice_try_choice(DrivingChoice *c, int preferred, float maxTime,
                             DrivingLocation *loc, NearbyCarList *list,
                             float unused, int *found, DriveTarget *t,
                             DrivingChoice *best, DriveTarget *bestTarget,
                             int *bestOut, float *bestScore,
                             DrivingChoice *round, DriveTarget *roundTarget,
                             float *roundTime, Car **hitCar, float *hitTime,
                             Car *inTheWay)
{
    // 0x002428d0. Static in retail.
    float score = -1.0f;
    int scored;

    (void)unused;
    if (list->MyCar->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR
        && AITrafficTuningMode != 0) {
        int ok = 1;

        if (!drivingchoice_type_is_side_of_car(c->Type))
            ok = 0;
        else if (c->pCar->MyDriver->TheDriverType != DRIVER_TYPE_AI_RACER
                 && c->pCar->pPlayer == NULL)
            ok = 0;
        if (!ok)
            return 0;
    }
    *hitCar = NULL;
    *hitTime = DC_NO_HIT;
    if (drivingchoice_is_driveable(c, t, preferred, &score, hitCar, hitTime,
                                   loc, list, 0.0f, maxTime, 0.0f,
                                   MOVEMENT_TOWARDS_LINE)
        && *bestScore < score) {
        *found = 1;
        *best = *c;
        drivetarget_assign(bestTarget, t);
        *bestOut = 0;
        *bestScore = score;
    }
    scored = !(fabsf(score - -1.0f) <= DC_NO_SCORE);
    if (!drivingchoice_type_is_side_of_car(c->Type)
        || c->UseExtraLateralDistance || c->pCar != inTheWay)
        return scored;
    if (preferred) {
        *round = *c;
        drivetarget_assign(roundTarget, t);
        *roundTime = *hitTime;
    }
    return scored;
}

int drivingchoice_make_new_choice(DrivingChoice *d, DriveTarget *t,
                                  DrivingLocation *loc, NearbyCarList *list,
                                  float maxTime, float unused, int *out,
                                  int tryCurrent)
{
    // 0x00242170. Retail's frame is 1984 bytes: the three targets and four
    // choices are on its stack.
    DriveTarget round, best, scratch;
    DrivingChoice bestChoice, roundChoice, tryChoice, current;
    int found = 0, bestOut = 0, preferred = 0;
    float bestScore = -1.0f, roundTime = DC_NO_HIT, hitTime = DC_NO_HIT;
    float currentScore = -1.0f, currentTime = DC_NO_HIT;
    Car *hitCar = NULL, *inTheWay = NULL;
    int32_t i;

    drivetarget_init(&round);
    drivetarget_init(&best);
    drivetarget_init(&scratch);
    drivingchoice_clear(&bestChoice);
    drivingchoice_clear(&roundChoice);
    drivingchoice_clear(&tryChoice);
    // Retail never clears this one, so a location whose line gives
    // CHOICE_NONE (a negative odd line) leaves it as the stack had it.
    drivingchoice_clear(&current);
    drivingchoice_set_choice_location(&current, loc);
    if (drivingchoice_is_valid(d, loc, list))
        drivingchoice_set_choice_choice(&current, d);

    if (tryCurrent) {
        if (drivingchoice_type_is_side_of_car(current.Type)) {
            NearbyCar *nc = nearbycarlist_get_nearby_car(list, current.pCar);

            if (nc != NULL) {
                if (drivingchoice_get_preferred_side_of_car(nc, list, loc)) {
                    if (current.Type == CHOICE_LEFT_SIDE_OF_CAR)
                        preferred = 1;
                } else if (current.Type == CHOICE_RIGHT_SIDE_OF_CAR) {
                    preferred = 1;
                }
            }
        }
        drivingchoice_try_choice(&current, preferred, maxTime, loc, list,
                                 unused, &found, &scratch, &bestChoice, &best,
                                 &bestOut, &bestScore, &roundChoice, &round,
                                 &roundTime, &hitCar, &hitTime, NULL);
        // Read once here: a choice not found leaves the score at -1.
        currentScore = bestScore;
        currentTime = hitTime;
        inTheWay = hitCar;
        if (preferred && current.pCar == inTheWay) {
            roundChoice = current;
            drivetarget_assign(&round, &scratch);
        }
    }

    if (!found) {
        for (i = 0; i < AICarControllerNumDrivingLinesToConsider && !found;
             i++) {
            drivingchoice_set_choice(&tryChoice, i + 1, NULL, 0);
            if (tryCurrent && drivingchoice_is_equal_to(&tryChoice, &current))
                continue;
            drivingchoice_try_choice(&tryChoice, 0, maxTime, loc, list, unused,
                                     &found, &scratch, &bestChoice, &best,
                                     &bestOut, &bestScore, &roundChoice,
                                     &round, &roundTime, &hitCar, &hitTime,
                                     inTheWay);
        }
    }

    if (!found) {
        // Every car, found or not.
        for (i = 0; i < list->NumCarsInArray; i++) {
            NearbyCar *nc = &list->Array[i];
            int side, tried = 0;

            if (!ai_do_we_care_about_this_car(nc, list))
                continue;
            side = drivingchoice_get_preferred_side_of_car(nc, list, loc);
            drivingchoice_set_choice(&tryChoice, CHOICE_LEFT_SIDE_OF_CAR,
                                     nc->TheCar, 0);
            if (!tryCurrent
                || !drivingchoice_is_equal_to(&tryChoice, &current))
                tried = drivingchoice_try_choice(
                            &tryChoice, side, maxTime, loc, list, unused,
                            &found, &scratch, &bestChoice, &best, &bestOut,
                            &bestScore, &roundChoice, &round, &roundTime,
                            &hitCar, &hitTime, inTheWay) != 0;
            drivingchoice_set_choice(&tryChoice, CHOICE_RIGHT_SIDE_OF_CAR,
                                     nc->TheCar, 0);
            if (!tryCurrent
                || !drivingchoice_is_equal_to(&tryChoice, &current)) {
                int r = drivingchoice_try_choice(
                    &tryChoice, side ^ 1, maxTime, loc, list, unused, &found,
                    &scratch, &bestChoice, &best, &bestOut, &bestScore,
                    &roundChoice, &round, &roundTime, &hitCar, &hitTime,
                    inTheWay);

                tried = tried || r;
            }
            if (!tried) {
                // Neither side scored: if the car is coming the other way,
                // its preferred side with room to spare.
                const bVector3 *v = &nc->TheCar->State.Velocity;
                const bVector3 *mine = &list->MyCar->State.Velocity;
                float dot = v->x * mine->x;

                dot = dot + v->y * mine->y;
                if (dot < 0.0f) {
                    drivingchoice_set_choice(
                        &tryChoice, side ? CHOICE_LEFT_SIDE_OF_CAR
                                         : CHOICE_RIGHT_SIDE_OF_CAR,
                        nc->TheCar, 1);
                    drivingchoice_try_choice(
                        &tryChoice, 1, maxTime, loc, list, unused, &found,
                        &scratch, &bestChoice, &best, &bestOut, &bestScore,
                        &roundChoice, &round, &roundTime, &hitCar, &hitTime,
                        inTheWay);
                }
            }
        }
    }

    if (found) {
        drivingchoice_set_choice_choice(d, &bestChoice);
        drivetarget_assign(t, &best);
        *out = bestOut;
    } else if (drivingchoice_is_valid(&roundChoice, loc, list)
               && currentTime - DC_HIT_MARGIN <= roundTime) {
        drivingchoice_set_choice_choice(d, &roundChoice);
        drivetarget_assign(t, &round);
        *out = 1;
    } else if (!(fabsf(currentScore - -1.0f) <= DC_NO_SCORE)) {
        // Never: the current choice's score is -1 unless it was found.
        drivingchoice_set_choice_choice(d, &current);
        drivingchoice_build_drive_target(&current, t, loc, list, 0.0f, unused,
                                         MOVEMENT_PARALLEL_TO_LINE);
        *out = 0;
    } else {
        drivingchoice_set_choice_location(d, loc);
        drivingchoice_fill_up_drive_target(t, loc, list,
                                           MOVEMENT_PARALLEL_TO_LINE, 1);
        *out = 0;
        found = 0;
    }
    drivingchoice_fixup_car_to_exclude_from_collision_prediction(
        d, list->MyCar, *out, list);
    return found;
}

int drivingchoice_try_to_drive_around_car(DrivingChoice *d, DriveTarget *t,
                                          int *out, NearbyCar *nc,
                                          DrivingLocation *loc,
                                          NearbyCarList *list, float a,
                                          float maxTime, float unused,
                                          int tryCurrent)
{
    // 0x00242c20.
    int side = drivingchoice_get_preferred_side_of_car(nc, list, loc);
    int done = 0, fast = 0;
    float score = -1.0f, hitTime = DC_NO_HIT;
    Car *hitCar = NULL;
    DriveTarget saved;
    DrivingChoice current, line;
    int32_t i;

    (void)unused;
    drivetarget_copy(&saved, t);
    drivingchoice_clear(&current);
    if (d->Type != CHOICE_NONE)
        drivingchoice_set_choice_choice(&current, d);
    if (TryToDriveAroundCarMinSpeedForDrivingLine
            < nc->TheCar->State.VelocityMagnitude
        || TryToDriveAroundCarMinSpeedForDrivingLine
               < list->MyCar->State.VelocityMagnitude)
        fast = 1;

    if (tryCurrent
        && (!drivingchoice_type_is_driving_line(current.Type) || fast)
        && drivingchoice_is_valid(&current, loc, list)
        && (!drivingchoice_type_is_side_of_car(current.Type)
            || nc->TheCar == current.pCar)) {
        int preferred = 0;

        if (current.Type == CHOICE_LEFT_SIDE_OF_CAR)
            preferred = side != 0;
        else if (current.Type == CHOICE_RIGHT_SIDE_OF_CAR)
            preferred = side == 0;
        drivetarget_assign(t, &saved);
        if (drivingchoice_is_driveable(&current, t, preferred, &score, &hitCar,
                                       &hitTime, loc, list, a, maxTime, 0.0f,
                                       MOVEMENT_TOWARDS_LINE)) {
            done = 1;
            *out = preferred;
        }
    }
    drivingchoice_clear(&line);

    if (!done && fast) {
        for (i = 0; i < AICarControllerNumDrivingLinesToConsider && !done;
             i++) {
            drivingchoice_set_choice(&line, i + 1, NULL, 0);
            if (tryCurrent && drivingchoice_is_equal_to(&line, &current))
                continue;
            drivetarget_assign(t, &saved);
            if (drivingchoice_is_driveable(&line, t, 0, &score, &hitCar,
                                           &hitTime, loc, list, a, maxTime,
                                           0.0f, MOVEMENT_TOWARDS_LINE)) {
                drivingchoice_set_choice_choice(d, &line);
                done = 1;
                *out = 0;
            }
        }
    }

    if (!done) {
        DrivingChoice first, second;

        drivingchoice_clear(&first);
        drivingchoice_clear(&second);
        drivingchoice_set_choice(&first, side ? CHOICE_LEFT_SIDE_OF_CAR
                                              : CHOICE_RIGHT_SIDE_OF_CAR,
                                 nc->TheCar, 0);
        drivingchoice_set_choice(&second, side ? CHOICE_RIGHT_SIDE_OF_CAR
                                               : CHOICE_LEFT_SIDE_OF_CAR,
                                 nc->TheCar, 0);
        if (!(tryCurrent && drivingchoice_is_equal_to(&first, &current))
            && (fast || drivingchoice_is_enough_room(&first, nc, list))) {
            drivetarget_assign(t, &saved);
            if (drivingchoice_is_driveable(&first, t, 1, &score, &hitCar,
                                           &hitTime, loc, list, a, maxTime,
                                           0.0f, MOVEMENT_TOWARDS_LINE)) {
                drivingchoice_set_choice_choice(d, &first);
                done = 1;
                *out = 1;
            }
        }
        if (!done
            && !(tryCurrent && drivingchoice_is_equal_to(&second, &current))
            && (fast || drivingchoice_is_enough_room(&second, nc, list))) {
            drivetarget_assign(t, &saved);
            if (drivingchoice_is_driveable(&second, t, 0, &score, &hitCar,
                                           &hitTime, loc, list, a, maxTime,
                                           0.0f, MOVEMENT_TOWARDS_LINE)) {
                drivingchoice_set_choice_choice(d, &second);
                done = 1;
                *out = 0;
            }
        }
        if (!done) {
            // The current choice if it still holds, else the location's
            // line; `*out` is left as the caller had it.
            drivingchoice_clear(&first);
            if (drivingchoice_is_valid(&current, loc, list))
                drivingchoice_set_choice_choice(&first, &current);
            else
                drivingchoice_set_choice_location(&first, loc);
            drivingchoice_build_drive_target(&first, t, loc, list, a, maxTime,
                                             MOVEMENT_PARALLEL_TO_LINE);
            drivingchoice_set_choice_choice(d, &first);
        }
    }
    drivingchoice_fixup_car_to_exclude_from_collision_prediction(
        d, list->MyCar, *out, list);
    return done;
}
