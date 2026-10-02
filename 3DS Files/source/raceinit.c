// raceinit -- see raceinit.h and docs/formats/raceinit.md.
#include "raceinit.h"

#include <stddef.h>
#include <string.h>

#include "airoute.h"
#include "bchunk.h"
#include "blist.h"
#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "carcontroller.h"
#include "carinit.h"
#include "carmodes.h"
#include "player.h"
#include "playerinit.h"
#include "topology.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

int32_t nDefaultMovementMode = MELLOW_MOVEMENT;

AddCopCarToRaceFn gAddCopCarToRaceFn;
ChopperCtorFn     gChopperCtorFn;
EggIsOnFn         gEggIsOnFn;

// The controller slots InitCars calls. Retail's GetCurrentRoute and
// GetCurrentRoutePoint take a flag the demo's do not: AICarController's
// runs FindWhereIAm first when it is set and its driving location is
// clear. InitCars passes 1.
typedef void             (*RaceInitFindFn)(void *self);
typedef TrackRoute      *(*RaceInitGetRouteFn)(void *self, int32_t find);
typedef TrackRoutePoint *(*RaceInitGetPointFn)(void *self, int32_t find);
typedef void             (*RaceInitSetRouteFn)(void *self, TrackRoute *route,
                                               TrackRoutePoint *point);

// ----------------------------------------------- CalculateRacerPositions

void calculate_racer_positions(int32_t n, RacerStartLocation *locs)
{
    TrackPathCoordinate tpc;
    TopologyCoordinate  tc;
    uint32_t hash;
    int32_t  count, i, j;
    int      found, fromMarkers = 0;
    float    d, z;

    hash = bchunk_hash(RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD
                       ? "ForwardStartingPosition"
                       : "BackwardStartingPosition");
    count = track_get_num_position_markers(hash);

    // Slot i is the first marker whose Param is i. A slot with none
    // spoils the lot, and the slots before it are written over below.
    if (count >= n) {
        fromMarkers = 1;
        for (i = 0; i < n; i++) {
            found = 0;
            for (j = 0; j < count; j++) {
                TrackPositionMarker *m = track_get_position_marker(hash, j);

                if (m->Param == i) {
                    found = 1;
                    locs[i].Position.x = m->Position.x;
                    locs[i].Position.y = m->Position.y;
                    break;
                }
            }
            if (!found) {
                fromMarkers = 0;
                break;
            }
        }
    }

    // Ten steps along the path, 10 to 100, then the slots in pairs from
    // 100 on, 17 apart, 3 to either side.
    if (!fromMarkers) {
        trackpath_coord_init(&tpc);
        d = 0.0f;
        do {
            d += 10.0f;
            trackpath_coord_update_position_along(&tpc, d, 0.0f);
        } while (d < 100.0f);
        for (i = 0; i < n; i++) {
            trackpath_coord_update_position_along(
                &tpc, (float)(i / 2) * 17.0f + 100.0f,
                (i & 1) ? -3.0f : 3.0f);
            locs[i].Position.x = tpc.Position.x;
            locs[i].Position.y = tpc.Position.y;
        }
    }

    topology_init(&tc);
    z = 0.0f;
    for (i = 0; i < n; i++) {
        locs[i].Position.z = z;
        z = topology_get_elevation(&tc, &locs[i].Position, NULL, NULL, NULL);
        locs[i].Position.z = z;
    }
    topology_destroy(&tc);
}

// ---------------------------------------------------------- AddRacingCar

void add_racing_car(DriverInfo *info, RacerStartLocation *loc,
                    ControlMode mode)
{
    TrackPathCoordinate tpc;
    uint16_t heading;
    World   *w;
    Car     *c, *tail;

    trackpath_coord_init_at(&tpc,
                            (const bVector2 *)(const void *)&loc->Position);
    heading = (uint16_t)bATan(tpc.PathDirection.x, tpc.PathDirection.y);
    c = (Car *)bMalloc((int)sizeof(Car), "Car", 0, CAR_MEMORY_POOL);
    c = car_construct(c, info, &loc->Position, heading,
                      tpc.DistanceAroundTrack);
    car_set_control_mode(c, mode);
    car_set_movement_mode(c, mode == AI_CONTROL ? nDefaultMovementMode
                                                : PHYSICS_MOVEMENT);

    w = pCurrentWorld;
    tail = w->CarList.prev;
    tail->Link.next = &c->Link;
    w->CarList.prev = c;
    c->Link.prev = &tail->Link;
    c->Link.next = (CarNode *)(void *)&w->CarList;

    if (mode == AI_CONTROL) {
        bPNode *node = bpnode_malloc();
        bNode  *last = w->AICarList.prev;

        node->Object = c;
        last->next = &node->Node;
        w->AICarList.prev = node;
        node->Node.next = (bNode *)(void *)&w->AICarList;
        node->Node.prev = last;
    }
}

// -------------------------------------------------------------- InitCars

void racecoordinator_init_cars(RaceCoordinator *rc)
{
    RacerStartLocation    locs[RACEINIT_GRID_SLOTS];
    NearestRoutePointInfo start;
    TrackInfo  *ti;
    TrackRoute *r;
    int32_t     pos, i, cops;

    (void)rc;
    // Retail leaves the fourth lanes unset; they are 0 here.
    memset(locs, 0, sizeof locs);
    calculate_racer_positions(RACEINIT_GRID_SLOTS, locs);

    // Each position takes the first driver still in the event who starts
    // there. A driver who is neither a player nor an AI racer leaves the
    // position empty.
    for (pos = 1; pos <= RACEINIT_GRID_SLOTS; pos++) {
        for (i = 0; i < RaceParametersNumDriverInfo; i++) {
            DriverInfo *d = race_parameters_get_driver_info(i);

            if (d->EliminatedRank > 0 || d->StartingPosition != pos)
                continue;
            if (d->TheDriverType == DRIVER_TYPE_PLAYER)
                add_racing_car(d, &locs[pos - 1], REAL_CONTROL);
            else if (d->TheDriverType == DRIVER_TYPE_AI_RACER)
                add_racing_car(d, &locs[pos - 1], AI_CONTROL);
            break;
        }
    }
    world_build_car_table(pCurrentWorld);

    // The AI racers' first route: the track's override, at its first
    // point, when it names one. Retail leaves `start` unset without one;
    // it is zero here, and IsValid fails on it.
    memset(&start, 0, sizeof start);
    ti = track_get_info(RaceParametersTrackNumber);
    if (ti->OverrideStartingRouteForAI >= 0) {
        r = TheTrackRouteManager.pTrackRoutes[ti->OverrideStartingRouteForAI];
        start.Route = r;
        start.Point = r != NULL ? &r->TrackRoutePointTable[0] : NULL;
    }
    // Without a valid one the first AI racer finds where it is, and its
    // route and point go to the rest. The first racer is never given it.
    for (i = 0; i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos; i++) {
        CarController *ctl =
            pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i]
                ->pCarController;
        const VtEntry *e;

        if (i == 0 && !nrpi_is_valid(&start)) {
            e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_FIND_WHERE_I_AM);
            ((RaceInitFindFn)e->fn)(vt_this(ctl, e));
            e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_GET_CURRENT_ROUTE);
            start.Route = ((RaceInitGetRouteFn)e->fn)(vt_this(ctl, e), 1);
            e = vt_slot(ctl->_vtable,
                        CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT);
            start.Point = ((RaceInitGetPointFn)e->fn)(vt_this(ctl, e), 1);
        } else {
            e = vt_slot(ctl->_vtable, CARCONTROLLER_VT_SET_CURRENT_ROUTE);
            ((RaceInitSetRouteFn)e->fn)(vt_this(ctl, e), start.Route,
                                        start.Point);
        }
    }

    // The traffic and the cops, from every driver, knocked out or not.
    cops = 0;
    for (i = 0; i < RaceParametersNumDriverInfo; i++) {
        DriverInfo *d = race_parameters_get_driver_info(i);

        if (d->TheDriverType == DRIVER_TYPE_TRAFFIC_CAR) {
            world_add_traffic_car(pCurrentWorld, d);
        } else if (d->TheDriverType == DRIVER_TYPE_COP
                   || d->TheDriverType == DRIVER_TYPE_SUPER_COP) {
            cops++;
            if (gAddCopCarToRaceFn != NULL)
                gAddCopCarToRaceFn(d, 0);
        }
    }
    world_build_car_table(pCurrentWorld);

    if ((cops != 0 || (gEggIsOnFn != NULL && gEggIsOnFn(EGG_HELICOPTER)))
        && gChopperCtorFn != NULL) {
        World *w = pCurrentWorld;

        w->Helicopter = gChopperCtorFn(bMalloc(CHOPPER_SIZE, "Chopper", 0,
                                               CAR_MEMORY_POOL));
    }
    if (cops != 0 && RaceParametersBeACop && gAddCopCarToRaceFn != NULL)
        gAddCopCarToRaceFn(NULL, 1);
}

// ----------------------------------------------------------- InitPlayers

void racecoordinator_init_players(RaceCoordinator *rc)
{
    int32_t i;

    (void)rc;
    for (i = 0; i < PlayerNumPlayers; i++) {
        struct Player *p = PlayerPlayersByIndex[i];
        Car *c;

        if (RaceParametersAIDemoMode) {
            World *w = pCurrentWorld;

            player_init_for_race(p, w->CarTable[w->AICarPos
                                                + p->PlayerNumber]);
        } else {
            c = world_get_car_by_number(pCurrentWorld, p->PlayerNumber);
            if (c != NULL)
                player_init_for_race(p, c);
        }
    }
}
