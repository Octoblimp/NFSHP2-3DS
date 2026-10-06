// drivingchoice -- see drivingchoice.h.

#include "drivingchoice.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "aicarcontroller.h"
#include "cartypeinfo.h"
#include "collisionbody.h"   // WilliamsAITuningMode
#include "drivetarget.h"
#include "drivinglocation.h"
#include "nearbycar.h"
#include "race.h"
#include "racecore.h"
#include "trackroute.h"

AISignPostDecisionFn gAISignPostDecisionFn;

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
