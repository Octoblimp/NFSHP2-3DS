// Host harness for 3DS Files/source/raceinit.c: CalculateRacerPositions,
// AddRacingCar, RaceCoordinator::InitCars and InitPlayers. Runs the op
// script tools/raceinit_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// raceinit.c is the port source under test, with race.c (GetDriverInfo),
// airoute.c (NearestRoutePointInfo::IsValid) and vtable.c under it. The
// harness owns everything else: bMalloc over a numbered arena, the bPNode
// pool, the track path, the topology, the markers, the track info, bATan,
// Car's constructor and its two mode setters, the World's car table and
// its two lookups, Player::InitForRace and the seams. Each prints its
// arguments in the model's words. A car's controller has a fake vtable
// whose four route slots print too.
//
// The track path, the ground and bATan answer from mix(), a hash of their
// arguments that both sides compute the same way, so where a value came
// from shows in the dump.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "car.h"
#include "carcontroller.h"
#include "carinit.h"
#include "player.h"
#include "playerinit.h"
#include "race.h"
#include "raceinit.h"
#include "topology.h"
#include "track.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// The DoSnapshots (TASKS 72c) call these; nothing here takes a
// snapshot.
static void snapshot_unreached(const char *f)
{
    fprintf(stderr, "%s reached\n", f);
    exit(3);
}

void trmgr_do_point_pointer_snapshot_in_route(TrackRouteManager *m,
                                              struct ReplaySnapshot *s,
                                              TrackRoutePoint **pp,
                                              TrackRoute *route)
{
    (void)m; (void)s; (void)pp; (void)route;
    snapshot_unreached("trmgr_do_point_pointer_snapshot_in_route");
}

void trmgr_do_route_pointer_snapshot(TrackRouteManager *m,
                                     struct ReplaySnapshot *s,
                                     TrackRoute **pp)
{
    (void)m; (void)s; (void)pp;
    snapshot_unreached("trmgr_do_route_pointer_snapshot");
}

#define NOBJ 256                // a0 .. a255
#define OBJ_BYTES 4096
#define NNODE 256               // n0 .. n255
#define NDRV 12
#define NMARK 16
#define NROUTE 4
#define NBUF 9
#define NPLAYER 2
#define PATTERN 0xa5
#define CAR_RETAIL_BYTES 2208
#define FAKE_VT 0x00ffe000u

// The size printed for a Car is retail's, so no other allocation may ask
// for the port's.
typedef char sizes_distinct[(sizeof(Car) != CHOPPER_SIZE) ? 1 : -1];
typedef char car_fits[(sizeof(Car) <= OBJ_BYTES) ? 1 : -1];

// What raceinit.c reaches outside the sources linked with it.
World *pCurrentWorld;
TrackRouteManager TheTrackRouteManager;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];

static World world;
static struct Player players[NPLAYER];
static DriverInfo drivers[NDRV];
static TrackRoute routes[NROUTE];
static TrackPositionMarker markers[2][NMARK];
static int markerCount[2];
static TrackInfo trackInfo;
static RacerStartLocation buf[NBUF];
static int32_t eggs[8];
static TrackRoute *findRoute;
static TrackRoutePoint *findPoint;
static uint32_t seed;
static int tpcCount;
static const TopologyCoordinate *topoAt;
static int32_t mmode0;     // nDefaultMovementMode as raceinit.c starts it

static _Alignas(16) unsigned char arena[NOBJ][OBJ_BYTES];
static int nobj;
static struct {
    int mode;       // from SetControlMode, -1 before
    int driver;     // the DriverInfo the constructor took, -1 for none
} meta[NOBJ];
static CarController ctrls[NOBJ];
static bPNode nodes[NNODE];
static int nnode;

// ------------------------------------------------------------- the names

static int obj_index(const void *p)
{
    const unsigned char *c = p;
    size_t off;

    if (c < arena[0] || c >= arena[NOBJ])
        return -1;
    off = (size_t)(c - arena[0]);
    return off % OBJ_BYTES ? -1 : (int)(off / OBJ_BYTES);
}

static const char *nm(const void *p)
{
    static char b16[16][32];
    static int slot;
    char *b = b16[slot++ & 15];
    const unsigned char *c = p;
    int i;

    if (p == NULL)
        return "null";
    if (p == &world)
        return "w";
    for (i = 0; i < NPLAYER; i++) {
        if (p == &players[i]) {
            sprintf(b, "p%d", i);
            return b;
        }
    }
    for (i = 0; i < NDRV; i++) {
        if (p == &drivers[i]) {
            sprintf(b, "d%d", i);
            return b;
        }
    }
    for (i = 0; i < NROUTE; i++) {
        const unsigned char *t = (const unsigned char *)routes[i].TrackRoutePointTable;

        if (p == &routes[i]) {
            sprintf(b, "r%d", i);
            return b;
        }
        if (c >= t && c < t + sizeof routes[i].TrackRoutePointTable
            && (size_t)(c - t) % sizeof(TrackRoutePoint) == 0) {
            sprintf(b, "r%d.%d", i, (int)((size_t)(c - t) / sizeof(TrackRoutePoint)));
            return b;
        }
    }
    for (i = 0; i < NBUF; i++) {
        if (p == &buf[i] || p == &buf[i].Position) {
            sprintf(b, "b%d", i);
            return b;
        }
    }
    for (i = 0; i < NNODE; i++) {
        if (p == &nodes[i]) {
            sprintf(b, "n%d", i);
            return b;
        }
    }
    for (i = 0; i < NOBJ; i++) {
        if (p == &ctrls[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
        if (c == (const unsigned char *)&ctrls[i] + 4) {
            sprintf(b, "c%d+4", i);
            return b;
        }
    }
    i = obj_index(p);
    if (i >= 0) {
        sprintf(b, "a%d", i);
        return b;
    }
    return "s";
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float from_bits(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *fx(float f)
{
    static char b16[16][12];
    static int slot;
    char *b = b16[slot++ & 15];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

// A word from three, and a float in 2^-7 .. 2^8 of either sign from it.
static uint32_t mixw(uint32_t a, uint32_t b, uint32_t salt)
{
    uint32_t h = a * 0x9e3779b1u + b * 0x85ebca77u + salt * 0xc2b2ae3du
               + seed * 0x27d4eb2fu;

    return h ^ (h >> 15);
}

static float mixf(uint32_t a, uint32_t b, uint32_t salt)
{
    uint32_t h = mixw(a, b, salt);

    return from_bits((h & 0x807fffffu) | ((120u + ((h >> 23) & 15u)) << 23));
}

// ----------------------------------------------------- the arena and pool

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p;
    int shown = size == (int)sizeof(Car) ? CAR_RETAIL_BYTES : size;

    if (nobj >= NOBJ) {
        fprintf(stderr, "arena full\n");
        exit(3);
    }
    p = arena[nobj];
    memset(p, PATTERN, OBJ_BYTES);
    meta[nobj].mode = -1;
    meta[nobj].driver = -1;
    nobj++;
    printf("  malloc %d %s %d %d -> %s\n", shown, name, flags, pool, nm(p));
    return p;
}

bPNode *bpnode_malloc(void)
{
    bPNode *n;

    if (nnode >= NNODE) {
        fprintf(stderr, "node pool full\n");
        exit(3);
    }
    n = &nodes[nnode++];
    memset(n, PATTERN, sizeof *n);
    printf("  pnode -> %s\n", nm(n));
    return n;
}

// -------------------------------------------- the track path and ground

void trackpath_coord_init(TrackPathCoordinate *c)
{
    printf("  tpc\n");
    memset(c, PATTERN, sizeof *c);
    c->Position.x = mixf(1, 0, 11);
    c->Position.y = mixf(2, 0, 11);
}

void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos)
{
    uint32_t x = bits(pos->x), y = bits(pos->y);

    printf("  tpcat %s %s\n", fx(pos->x), fx(pos->y));
    memset(c, PATTERN, sizeof *c);
    c->Position = *pos;
    c->DistanceAroundTrack = mixf(x, y, 3);
    c->PathDirection.x = mixf(x, y, 4);
    c->PathDirection.y = mixf(x, y, 5);
}

void trackpath_coord_update_position_along(TrackPathCoordinate *c,
                                           float along, float side)
{
    uint32_t a = bits(along), s = bits(side);

    printf("  tpcmove %s %s\n", fx(along), fx(side));
    c->Position.x = mixf(a, s, 6 + 2 * (uint32_t)tpcCount);
    c->Position.y = mixf(a, s, 7 + 2 * (uint32_t)tpcCount);
    tpcCount++;
}

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo\n");
    topoAt = tc;
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topodel %s\n", tc == topoAt ? "same" : "other");
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    float r = mixf(bits(pt->x) ^ bits(pt->z), bits(pt->y), 9);

    printf("  elev %s %s %s %s %d%d%d -> %s\n", tc == topoAt ? "same" : "other",
           fx(pt->x), fx(pt->y), fx(pt->z), terrain != NULL, normal != NULL,
           found != NULL, fx(r));
    return r;
}

int32_t bATan(float x, float y)
{
    int32_t r = (int32_t)mixw(bits(x), bits(y), 10);

    printf("  atan %s %s -> %d\n", fx(x), fx(y), (int)r);
    return r;
}

// ------------------------------------------------------------ the track

static uint32_t marker_hash(int list)
{
    return bchunk_hash(list ? "BackwardStartingPosition"
                            : "ForwardStartingPosition");
}

int track_get_num_position_markers(uint32_t hash)
{
    int n = 0, k;

    for (k = 0; k < 2; k++)
        if (hash == marker_hash(k))
            n = markerCount[k];
    printf("  nmark %08lx -> %d\n", (unsigned long)hash, n);
    return n;
}

TrackPositionMarker *track_get_position_marker(uint32_t hash, int i)
{
    int k;

    for (k = 0; k < 2; k++) {
        if (hash == marker_hash(k) && i >= 0 && i < markerCount[k]) {
            printf("  mark %08lx %d -> m%d.%d\n", (unsigned long)hash, i, k, i);
            return &markers[k][i];
        }
    }
    printf("  mark %08lx %d -> null\n", (unsigned long)hash, i);
    return NULL;
}

TrackInfo *track_get_info(int i)
{
    printf("  trackinfo %d\n", i);
    return &trackInfo;
}

// ---------------------------------------------------------- the trackroute
// airoute.c's other functions call these; nothing here reaches them.

static void unreached(const char *what)
{
    fprintf(stderr, "%s reached\n", what);
    exit(4);
}

Signpost *trpoint_get_signpost(const TrackRoutePoint *p)
{
    (void)p;
    unreached("trpoint_get_signpost");
    return NULL;
}

float trpoint_get_distance_away(const TrackRoutePoint *p, const bVector2 *pos,
                                float d)
{
    (void)p; (void)pos; (void)d;
    unreached("trpoint_get_distance_away");
    return 0.0f;
}

TrackRoutePoint *troute_find_closest_point(TrackRoute *r, const bVector2 *pos,
                                           float radius, int flags,
                                           float distanceAround)
{
    (void)r; (void)pos; (void)radius; (void)flags; (void)distanceAround;
    unreached("troute_find_closest_point");
    return NULL;
}

TrackRoute *signpost_get_new_route(const Signpost *s)
{
    (void)s;
    unreached("signpost_get_new_route");
    return NULL;
}

TrackRoutePoint *signpost_get_new_route_point(const Signpost *s)
{
    (void)s;
    unreached("signpost_get_new_route_point");
    return NULL;
}

// ------------------------------------------------------- Car and the World

static void s_find(void *self)
{
    printf("  find %s\n", nm(self));
}

static TrackRoute *s_getroute(void *self, int32_t f)
{
    printf("  getroute %s %d -> %s\n", nm(self), (int)f, nm(findRoute));
    return findRoute;
}

static TrackRoutePoint *s_getpoint(void *self, int32_t f)
{
    printf("  getpoint %s %d -> %s\n", nm(self), (int)f, nm(findPoint));
    return findPoint;
}

static void s_setroute(void *self, TrackRoute *r, TrackRoutePoint *p)
{
    printf("  setroute %s %s %s\n", nm(self), nm(r), nm(p));
}

static void install_fake_vtable(void)
{
    static VtEntry vt[CARCONTROLLER_VT_ENTRIES];

    vt[VT_SLOT(CARCONTROLLER_VT_SET_CURRENT_ROUTE)].delta = 4;
    vt[VT_SLOT(CARCONTROLLER_VT_SET_CURRENT_ROUTE)].fn = (VtFn)s_setroute;
    vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE)].fn = (VtFn)s_getroute;
    vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT)].delta = 4;
    vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT)].fn = (VtFn)s_getpoint;
    vt[VT_SLOT(CARCONTROLLER_VT_FIND_WHERE_I_AM)].fn = (VtFn)s_find;
    vt_install(FAKE_VT, vt, CARCONTROLLER_VT_ENTRIES);
}

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    int k = obj_index(c);
    int d = -1, i;

    for (i = 0; i < NDRV; i++)
        if (driver == &drivers[i])
            d = i;
    printf("  car %s %s %s %s %s %s angle %d dist %s\n", nm(c), nm(driver),
           nm(pos), fx(pos->x), fx(pos->y), fx(pos->z), (int)angle, fx(dist));
    if (k < 0) {
        fprintf(stderr, "a car outside the arena\n");
        exit(3);
    }
    meta[k].driver = d;
    ctrls[k]._vtable = FAKE_VT;
    c->pCarController = &ctrls[k];
    return c;
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    int k = obj_index(c);

    printf("  ctl %s %d\n", nm(c), (int)mode);
    if (k >= 0)
        meta[k].mode = (int)mode;
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  move %s %d\n", nm(c), (int)mode);
}

// The cars on CarList, in order, at most `max`.
static int walk_cars(Car **out, int max)
{
    void *p = world.CarList.next;
    int n = 0;

    while (p != (void *)&world.CarList && n < max) {
        out[n++] = p;
        p = ((Car *)p)->Link.next;
    }
    return n;
}

// The players' cars, then the AI racers', then the rest, from CarList.
void world_build_car_table(World *w)
{
    Car *list[64];
    int n = walk_cars(list, 64), slot = 0, pass, i, np = 0, nai = 0;

    printf("  table %s\n", nm(w));
    for (pass = 0; pass < 3; pass++) {
        for (i = 0; i < n; i++) {
            int m = meta[obj_index(list[i])].mode;
            int want = pass == 0 ? m == 1 : pass == 1 ? m == 2
                                                      : (m != 1 && m != 2);

            if (want && slot < WORLD_MAX_CARS) {
                w->CarTable[slot++] = list[i];
                if (pass == 0)
                    np++;
                else if (pass == 1)
                    nai++;
            }
        }
    }
    for (i = slot; i < WORLD_MAX_CARS; i++)
        w->CarTable[i] = NULL;
    w->TotalNumCars = slot;
    w->AICarPos = np;
    w->CopCarPos = np + nai;
    w->TrafficCarPos = np + nai;
}

Car *world_get_car_by_number(const World *w, int32_t n)
{
    Car *list[64], *r = NULL;
    int count = walk_cars(list, 64), i;

    for (i = 0; i < count && r == NULL; i++) {
        int d = meta[obj_index(list[i])].driver;

        if (d >= 0 && drivers[d].UniqueDriverNumber == n)
            r = list[i];
    }
    printf("  bynum %s %d -> %s\n", nm(w), (int)n, nm(r));
    return r;
}

void world_add_traffic_car(World *w, DriverInfo *info)
{
    printf("  traffic %s %s\n", nm(w), nm(info));
}

void player_init_for_race(struct Player *p, Car *c)
{
    printf("  ifr %s %s\n", nm(p), nm(c));
}

// ---------------------------------------------------------------- the seams

static void s_cop(DriverInfo *info, int32_t beACop)
{
    printf("  cop %s %d\n", nm(info), (int)beACop);
}

static struct Chopper *s_chopper(void *mem)
{
    printf("  chopper %s\n", nm(mem));
    return mem;
}

static int32_t s_egg(int32_t n)
{
    return n >= 0 && n < 8 ? eggs[n] : 0;
}

// ---------------------------------------------------------------- the dump

static void dump(void)
{
    Car *list[64];
    int n = walk_cars(list, 64), i;
    void *p;
    bNode *b;

    printf("  list");
    for (i = 0; i < n; i++)
        printf(" %s", nm(list[i]));
    printf(" |");
    p = world.CarList.prev;
    for (i = 0; p != (void *)&world.CarList && i < 64; i++) {
        printf(" %s", nm(p));
        p = ((Car *)p)->Link.prev;
    }
    printf("\n  ai");
    b = world.AICarList.next;
    for (i = 0; (void *)b != (void *)&world.AICarList && i < 64; i++) {
        printf(" %s:%s", nm(b), nm(((bPNode *)b)->Object));
        b = b->next;
    }
    printf(" |");
    b = world.AICarList.prev;
    for (i = 0; (void *)b != (void *)&world.AICarList && i < 64; i++) {
        printf(" %s", nm(b));
        b = b->prev;
    }
    printf("\n  heli %s total %d ai %d cop %d traffic %d\n",
           nm(world.Helicopter), (int)world.TotalNumCars, (int)world.AICarPos,
           (int)world.CopCarPos, (int)world.TrafficCarPos);
    printf("  carstable");
    for (i = 0; i < WORLD_MAX_CARS; i++)
        printf(" %s", nm(world.CarTable[i]));
    printf("\n");
    for (i = 0; i < NBUF; i++)
        printf("  b%d %s %s %s %s\n", i, fx(buf[i].Position.x),
               fx(buf[i].Position.y), fx(buf[i].Position.z),
               fx(buf[i].Position.pad));
}

// ---------------------------------------------------------------- the ops

static void reset(void)
{
    int i;

    nobj = 0;
    nnode = 0;
    memset(meta, 0, sizeof meta);
    memset(&world, 0, sizeof world);
    world.CarList.next = world.CarList.prev = &world.CarList;
    world.AICarList.next = world.AICarList.prev = &world.AICarList;
    pCurrentWorld = &world;
    memset(drivers, PATTERN, sizeof drivers);
    RaceParametersDriverInfo = drivers;
    RaceParametersNumDriverInfo = 0;
    RaceParametersTrackNumber = 1;
    RaceParametersTrackDirection = TRACK_DIRECTION_FORWARD;
    RaceParametersAIDemoMode = 0;
    RaceParametersBeACop = 0;
    nDefaultMovementMode = mmode0;
    memset(markers, 0, sizeof markers);
    markerCount[0] = markerCount[1] = 0;
    memset(routes, 0, sizeof routes);
    memset(&TheTrackRouteManager, 0, sizeof TheTrackRouteManager);
    memset(&trackInfo, 0, sizeof trackInfo);
    trackInfo.OverrideStartingRouteForAI = -1;
    memset(buf, PATTERN, sizeof buf);
    memset(eggs, 0, sizeof eggs);
    findRoute = NULL;
    findPoint = NULL;
    seed = 0;
    tpcCount = 0;
    topoAt = NULL;
    PlayerNumPlayers = 0;
    for (i = 0; i < NPLAYER; i++) {
        players[i].PlayerNumber = i;
        PlayerPlayersByIndex[i] = &players[i];
    }
}

static int32_t num(const char *s)
{
    return (int32_t)strtoll(s, NULL, 0);
}

static void set_global(const char *f, int32_t v)
{
    if (!strcmp(f, "dir"))
        RaceParametersTrackDirection = (eTrackDirection)v;
    else if (!strcmp(f, "track"))
        RaceParametersTrackNumber = v;
    else if (!strcmp(f, "aidemo"))
        RaceParametersAIDemoMode = v;
    else if (!strcmp(f, "beacop"))
        RaceParametersBeACop = v;
    else if (!strcmp(f, "ndrv"))
        RaceParametersNumDriverInfo = v;
    else if (!strcmp(f, "override"))
        trackInfo.OverrideStartingRouteForAI = v;
    else if (!strcmp(f, "mmode"))
        nDefaultMovementMode = v;
    else if (!strcmp(f, "nplay"))
        PlayerNumPlayers = v;
    else if (!strcmp(f, "seed"))
        seed = (uint32_t)v;
    else {
        fprintf(stderr, "bad global %s\n", f);
        exit(2);
    }
}

static TrackRoutePoint *point_of(int r, int k)
{
    if (r < 0 || k < 0)
        return NULL;
    return &routes[r].TrackRoutePointTable[k];
}

static void op(char **t, int n)
{
    char c = t[0][0];
    int full = 1;

    if (c == 'S') {
        set_global(t[1], num(t[2]));
        full = 0;
    } else if (c == 'D') {
        DriverInfo *d = &drivers[num(t[1])];

        d->EliminatedRank = (int8_t)num(t[2]);
        d->UniqueDriverNumber = (int8_t)num(t[3]);
        d->StartingPosition = (int8_t)num(t[4]);
        d->TheDriverType = num(t[5]);
        full = 0;
    } else if (c == 'K') {
        markerCount[num(t[1])] = num(t[2]);
        full = 0;
    } else if (c == 'M') {
        TrackPositionMarker *m = &markers[num(t[1])][num(t[2])];

        m->Param = num(t[3]);
        m->Position.x = from_bits((uint32_t)num(t[4]));
        m->Position.y = from_bits((uint32_t)num(t[5]));
        full = 0;
    } else if (c == 'R') {
        int r = num(t[2]);

        TheTrackRouteManager.pTrackRoutes[num(t[1])] = r < 0 ? NULL : &routes[r];
        full = 0;
    } else if (c == 'P') {
        routes[num(t[1])].RouteNumber = (int16_t)num(t[2]);
        routes[num(t[1])].NumPoints = num(t[3]);
        full = 0;
    } else if (c == 'F') {
        int r = num(t[1]);

        findRoute = r < 0 ? NULL : &routes[r];
        findPoint = point_of(num(t[2]), num(t[3]));
        full = 0;
    } else if (c == 'E') {
        eggs[num(t[1])] = num(t[2]);
        full = 0;
    } else if (c == 'Q') {
        players[num(t[1])].PlayerNumber = num(t[2]);
        full = 0;
    } else if (c == 'L') {
        int k = num(t[1]);

        buf[k].Position.x = from_bits((uint32_t)num(t[2]));
        buf[k].Position.y = from_bits((uint32_t)num(t[3]));
        buf[k].Position.z = from_bits((uint32_t)num(t[4]));
        full = 0;
    } else if (c == 'C') {
        calculate_racer_positions(num(t[1]), buf);
    } else if (c == 'A') {
        add_racing_car(&drivers[num(t[1])], &buf[num(t[3])], num(t[2]));
    } else if (c == 'I') {
        racecoordinator_init_cars(NULL);
    } else if (c == 'J') {
        racecoordinator_init_players(NULL);
    } else {
        fprintf(stderr, "bad op %s\n", t[0]);
        exit(2);
    }
    (void)n;
    if (full)
        dump();
}

int main(int argc, char **argv)
{
    FILE *f;
    char line[512];

    if (argc < 2) {
        fprintf(stderr, "usage: raceinit_test scenarios.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    mmode0 = nDefaultMovementMode;
    install_fake_vtable();
    gAddCopCarToRaceFn = s_cop;
    gChopperCtorFn = s_chopper;
    gEggIsOnFn = s_egg;
    while (fgets(line, sizeof line, f)) {
        char echo[512];
        char *t[16];
        int n = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        // The model echoes the first 40 characters of each op.
        strcpy(echo, line);
        echo[40] = 0;
        p = strtok(line, " ");
        while (p != NULL && n < 16) {
            t[n++] = p;
            p = strtok(NULL, " ");
        }
        if (n == 0)
            continue;
        if (t[0][0] == 'B') {
            printf("B %s\n", t[1]);
            reset();
            continue;
        }
        printf("> %s\n", echo);
        op(t, n);
    }
    fclose(f);
    return 0;
}
