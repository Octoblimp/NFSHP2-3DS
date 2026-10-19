// traffictele -- see traffictele.h and docs/formats/traffic-teleporter.md.
#include "traffictele.h"

#include <math.h>

#include "airouteplan.h"
#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "carinit.h"
#include "carmodes.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "replay.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// The first think is no sooner than this (`lui 0x41a0`): 20 s, more than
// SetThinkTime ever gives.
#define TELEPORT_FIRST_THINK 20.0f

// WorldTimer's ticks in seconds (gp-27140) and the boundary distances'
// percent (gp-27136).
#define TELEPORT_TICK        0.00025f
#define TELEPORT_PERCENT     0.01f

typedef void (*TeleportSetRouteFn)(void *self, TrackRoute *route,
                                   TrackRoutePoint *point);

// The World's car list, as worldstep.c walks it.
#define CAR_END(w) ((Car *)(void *)&(w)->CarList)

TrafficTeleporter *traffic_teleporter_construct(void *mem)
{
    TrafficTeleporter *t = (TrafficTeleporter *)mem;

    traffic_teleporter_fill_in_totals(t, t->ForwardTotals,
                                      TRAFFIC_FORWARD_ROUTES);
    traffic_teleporter_fill_in_totals(t, t->BackwardTotals,
                                      TRAFFIC_BACKWARD_ROUTES);
    traffic_teleporter_set_think_time(t);
    // `c.lt.s` and a likely store: a NaN is left alone.
    if (t->TimeUntilTeleport < TELEPORT_FIRST_THINK)
        t->TimeUntilTeleport = TELEPORT_FIRST_THINK;
    t->LastCar = 0;
    return t;
}

void traffic_teleporter_destroy(TrafficTeleporter *t, int32_t flags)
{
    if (flags & 1)
        bFree(t);
}

// The traffic is CarTable[TrafficCarPos ..] up to TotalNumCars. The count
// is compared unsigned (`sltu`).
void traffic_teleporter_do_timestep(TrafficTeleporter *t, float dt)
{
    World   *w = pCurrentWorld;
    uint32_t i;

    // `c.lt.s`: a NaN density goes on.
    if (TheRaceParameters.TrafficDensity < TELEPORT_MIN_DENSITY)
        return;
    if (w->TotalNumCars == w->TrafficCarPos)
        return;
    // The image reads the race without testing it.
    if (pCurrentRace == NULL
        || race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING)
        return;
    if (PlayerNumPlayers == 0)
        return;
    t->TimeUntilTeleport = t->TimeUntilTeleport - dt;
    if (0.0f < t->TimeUntilTeleport)
        return;
    traffic_teleporter_set_think_time(t);

    i = (uint32_t)t->LastCar;
    for (;;) {
        Car *c;

        i++;
        if (!(i < (uint32_t)(w->TotalNumCars - w->TrafficCarPos)))
            i = 0;
        c = w->CarTable[w->TrafficCarPos + (int32_t)i];
        if (!traffic_teleporter_check_is_visible(
                t, c->TheTrackPathCoordinate.DistanceAroundTrack)) {
            traffic_teleporter_try_to_teleport_car(t, c);
            t->LastCar = (int32_t)i;
            return;
        }
        // Round to the last one again, all of them in sight.
        if (i == (uint32_t)t->LastCar)
            return;
    }
}

Car *traffic_teleporter_place_new_car(TrafficTeleporter *t,
                                      DriverInfo *info)
{
    TrackPathCoordinate   coord;
    NearestRoutePointInfo rp;
    TrackRoutePoint      *p;
    CarController        *ctl;
    const VtEntry        *e;
    bVector3              pos;
    uint32_t              tries;
    int32_t               fwd;
    uint16_t              angle;
    Car                  *c;

    trackpath_coord_init(&coord);
    fwd = traffic_teleporter_forwards_or_backwards(t);
    if (t->ForwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0
        || t->BackwardTotals[TRAFFIC_ROUTES_EACH - 1] == 0)
        return NULL;
    tries = 0;
    for (;;) {
        traffic_teleporter_pick_route_point(t, &rp, fwd);
        if (traffic_teleporter_is_good_place(t, &rp, NULL, 1))
            break;
        if (!(++tries < TELEPORT_PLACE_TRIES))
            return NULL;
    }

    // The image places a TrackPathCoordinate at the point and drops it.
    p = rp.Point;
    trackpath_coord_reset_position(&coord, &p->Position);
    angle = (uint16_t)bATan(rp.Point->Direction.x, rp.Point->Direction.y);
    pos.x = p->Position.x;
    pos.y = p->Position.y;
    pos.z = rp.Point->Elevation;
    pos.pad = 0.0f;
    info->CurrentRideInfo.SkinNumber = (int8_t)
        traffic_teleporter_pick_random_skin(
            t, cartypeinfo_get(info->CurrentRideInfo.Type));
    c = (Car *)bMalloc((int)sizeof(Car), "Car", 0, CAR_MEMORY_POOL);
    c = car_construct(c, info, &pos, angle,
                      rp.Point->DistanceAroundTrack);
    car_set_movement_mode(c, eNO_MOVEMENT);
    car_set_control_mode(c, TRAFFIC_CONTROL);
    ctl = c->pCarController;
    e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_SET_CURRENT_ROUTE);
    ((TeleportSetRouteFn)e->fn)(vt_this(ctl, e), rp.Route, rp.Point);
    c->RenderingEnabled = 0;
    return c;
}

void traffic_teleporter_try_to_teleport_car(TrafficTeleporter *t, Car *c)
{
    NearestRoutePointInfo info;
    int32_t               fwd;
    Car                  *pc;
    float                 carAhead, ahead;

    fwd = traffic_teleporter_forwards_or_backwards(t);
    pc = traffic_teleporter_random_player_car(t);
    // How far the car is ahead of the player.
    carAhead = trackpath_compare_distances(
        &TheTrackPathManager, c->TheTrackPathCoordinate.DistanceAroundTrack,
        pc->TheTrackPathCoordinate.DistanceAroundTrack);
    if (!ai_get_nearest_route_point(
            &info, (const bVector2 *)(const void *)&pc->State.Position,
            fwd ? FORWARD_TRAFFIC_ROUTES : ONCOMING_TRAFFIC_ROUTES, 0, 0.0f))
        return;
    if (ai_guess_target_destinations(&info, 1, info.Route, info.Point,
                                     TELEPORT_FIRST_AHEAD, fwd) != 1)
        return;
    for (;;) {
        // How far the place is ahead of the player.
        ahead = trackpath_compare_distances(
            &TheTrackPathManager, info.Point->DistanceAroundTrack,
            pc->TheTrackPathCoordinate.DistanceAroundTrack);
        if (traffic_teleporter_is_good_place(t, &info, c, 0)) {
            // Never further from the player than the car was ahead, and
            // never behind it.
            if (0.0f < carAhead && carAhead < ahead)
                return;
            if (ahead < 0.0f)
                return;
            car_reset_to_route_point(c, info.Route, info.Point,
                                     TELEPORT_SPEED, 0, 1.0f, 0);
            car_set_movement_mode(c, TRAFFIC_MOVEMENT);
            traffic_teleporter_switch_skin(t, c);
            return;
        }
        if (ai_guess_target_destinations(&info, 1, info.Route, info.Point,
                                         TELEPORT_STEP_AHEAD, fwd) != 1)
            return;
    }
}

// With no race the image reads the start line through address 0; the
// port leaves the start line out.
int32_t traffic_teleporter_is_good_place(TrafficTeleporter *t,
                                         const NearestRoutePointInfo *info,
                                         Car *except, int32_t all)
{
    Race   *r = pCurrentRace;
    int32_t nearStart = 0;
    int32_t tooClose = 0;

    if (r != NULL
        && (float)(int32_t)((uint32_t)WorldTimer - r->StartTime.PackedTime)
               * TELEPORT_TICK < TELEPORT_START_TIME) {
        float start = TheTrackPathManager.TrackLength * TELEPORT_PERCENT
                      * r->BoundaryDistances[r->StartLineBoundaryNumber];

        if (fabsf(trackpath_compare_distances(
                &TheTrackPathManager, info->Point->DistanceAroundTrack,
                start)) < TELEPORT_START_CLEAR)
            nearStart = 1;
    }
    if (!nearStart) {
        if (traffic_teleporter_check_is_visible(
                t, info->Point->DistanceAroundTrack))
            return 0;
        tooClose = traffic_teleporter_too_close_to_another_car(
            t, info->Point->DistanceAroundTrack, except, all);
    }
    return !nearStart && !tooClose;
}

int32_t traffic_teleporter_check_is_visible_at(TrafficTeleporter *t,
                                               const bVector2 *pos)
{
    (void)t;
    return world_get_distance_to_closest_player_2d(pCurrentWorld, pos)
           < TELEPORT_SIGHT;
}

int32_t traffic_teleporter_check_is_visible(TrafficTeleporter *t, float dat)
{
    (void)t;
    return fabsf(world_get_dat_to_closest_player(pCurrentWorld, dat))
           < TELEPORT_SIGHT;
}

void traffic_teleporter_set_think_time(TrafficTeleporter *t)
{
    t->TimeUntilTeleport =
        (1.0f - TheRaceParameters.TrafficDensity) * 15.0f + 1.0f;
}

int32_t traffic_teleporter_forwards_or_backwards(TrafficTeleporter *t)
{
    (void)t;
    return world_random_f(pCurrentWorld, 1.0f)
           < TheRaceParameters.TrafficOncoming;
}

// The route slots are read straight out of the manager's table, a
// negative number reading none (`bltz`); first is 50 or 60, so the top is
// never passed.
void traffic_teleporter_fill_in_totals(TrafficTeleporter *t, uint32_t *out,
                                       int32_t first)
{
    uint32_t total = 0;
    int32_t  i;

    (void)t;
    for (i = 0; i < TRAFFIC_ROUTES_EACH; i++) {
        const TrackRoute *r = trmgr_get_route(&TheTrackRouteManager,
                                              first + i);

        if (r != NULL)
            total += (uint32_t)r->NumPoints;
        out[i] = total;
    }
}

// Whether `c` is one TooCloseToAnotherCar passes over.
static int skip_car(Car *c, Car *except, int32_t all)
{
    if (c == except)
        return 1;
    if (car_is_poofed(c))
        return 1;
    return !all && c->RenderingEnabled == 0;
}

int32_t traffic_teleporter_too_close_at(TrafficTeleporter *t,
                                        const bVector2 *pos, Car *except,
                                        int32_t all)
{
    World *w = pCurrentWorld;
    Car   *c;

    (void)t;
    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next) {
        float dx, dy;

        if (skip_car(c, except, all))
            continue;
        dx = pos->x - c->State.Position.x;
        dy = pos->y - c->State.Position.y;
        if (sqrtf(dx * dx + dy * dy) < TELEPORT_TOO_CLOSE)
            return 1;
    }
    return 0;
}

int32_t traffic_teleporter_too_close_to_another_car(TrafficTeleporter *t,
                                                    float dat, Car *except,
                                                    int32_t all)
{
    World *w = pCurrentWorld;
    Car   *c;

    (void)t;
    for (c = w->CarList.next; c != CAR_END(w); c = (Car *)c->Link.next) {
        float d;

        if (skip_car(c, except, all))
            continue;
        d = trackpath_compare_distances(
            &TheTrackPathManager, dat,
            c->TheTrackPathCoordinate.DistanceAroundTrack);
        if (c->MyDriver->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {
            if (fabsf(d) < TELEPORT_TOO_CLOSE)
                return 1;
        } else if (d < TELEPORT_TOO_CLOSE && 0.0f < d) {
            return 1;
        }
    }
    return 0;
}

// The totals make each point as likely as any other: the route is the
// first whose running total passes the draw, the point the draw less the
// routes before it. Compared unsigned (`sltu`).
void traffic_teleporter_pick_route_point(TrafficTeleporter *t,
                                         NearestRoutePointInfo *out,
                                         int32_t fwd)
{
    const uint32_t *totals = fwd ? t->ForwardTotals : t->BackwardTotals;
    int32_t         first = fwd ? TRAFFIC_FORWARD_ROUTES
                                : TRAFFIC_BACKWARD_ROUTES;
    int32_t         tries = 0;
    TrackRoutePoint *p;

    do {
        uint32_t n = (uint32_t)world_random_i(
            pCurrentWorld, (int32_t)totals[TRAFFIC_ROUTES_EACH - 1]);
        int32_t  i = 0;

        while (!(n < totals[i]))
            i++;
        if (i != 0)
            n -= totals[i - 1];
        out->Route = trmgr_get_route(&TheTrackRouteManager, first + i);
        p = &out->Route->TrackRoutePointTable[n];
        out->Point = p;
        tries++;
    } while (tries < TELEPORT_PICK_TRIES && !trpoint_is_posted(p));
}

Car *traffic_teleporter_random_player_car(TrafficTeleporter *t)
{
    (void)t;
    return PlayerPlayersByIndex[world_random_i(pCurrentWorld,
                                               PlayerNumPlayers)]->MyCar;
}

int32_t traffic_teleporter_pick_random_skin(TrafficTeleporter *t,
                                            const CarTypeInfo *ct)
{
    int32_t n = cartypeinfo_get_num_skins(ct);

    (void)t;
    if (n == 0)
        return 0;
    return cartypeinfo_get_skin_number(ct, world_random_i(pCurrentWorld, n));
}

// The ride's SkinNumber is a signed byte (`lb`).
void traffic_teleporter_switch_skin(TrafficTeleporter *t, Car *c)
{
    int32_t skin = traffic_teleporter_pick_random_skin(t, c->pCarTypeInfo);

    if (skin != c->pRideInfo->SkinNumber)
        car_switch_skin(c, (uint32_t)skin);
}

void traffic_teleporter_do_snapshot(TrafficTeleporter *t, ReplaySnapshot *s)
{
    ReplaySnapshot_BeginNamedSection(s, "TrafficTeleporter");
    ReplaySnapshot_MoveFloat(s, &t->TimeUntilTeleport);
    ReplaySnapshot_MoveUInt(s, (uint32_t *)&t->LastCar, 4);
    ReplaySnapshot_EndSection(s);
}
