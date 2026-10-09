// chopper_test -- tools/chopper_check.py's harness.
//
// Runs chopper.c, with coputil.c's RotateVector, emath.c's rotations,
// bmath.c's bSinCos and bmatrix.c's bIdentity under it, over the
// checker's script. Everything else the Chopper calls is a stub here that
// logs its arguments and answers from the script, as the model's stubs
// do. Pointers print as names: H for the helicopter (H.topo, H.dust,
// H.tp and H.pos for its parts), T for the ChopperTarget, C0.. for cars,
// R0.. routes, P0.. points, S0.. signposts, and SND, WO, WOP, SHEET, TPM
// and WORLD; anything else is "?".
//
// The points sit in their routes' tables, PER_ROUTE to a route, because
// BeginStakeout compares two points' indices worked out from their
// addresses.

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "acidsys.h"
#include "airoute.h"
#include "airouteplan.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "chopper.h"
#include "collision.h"
#include "collisionbody.h"
#include "coputil.h"
#include "helisheet.h"
#include "race.h"
#include "raceinit.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"
#include "worldobject.h"

#define NCARS   3
#define NROUTES 4
#define NPOINTS 24
#define PER_ROUTE 6
#define NBOXES  8

// Point i, in its route's table.
#define PT(i) (&routes[(i) / PER_ROUTE].TrackRoutePointTable[(i) % PER_ROUTE])

// ---------------------------------------------------- what the port reads

World            *pCurrentWorld;
HeliSheet        *TheHeliSheet;
BSlotPool        *WorldObjectSlotPool;
TrackPathManager  TheTrackPathManager;
RaceParameters    TheRaceParameters;
EggIsOnFn         gEggIsOnFn;

static World           world;
static Car             cars[NCARS];
static TrackRoute      routes[NROUTES];
static Signpost        signs[NPOINTS];
static ChopperTarget   tgt;
static HeliSheet       sheet;
static WorldObject     wo;
static Sound3d         snd;
static char            pool;
static struct Chopper  chopper;
static struct Chopper *H;

// ------------------------------------------------------- the answers

static int32_t          q_egg;
static int32_t          q_signs = 1;
static float            q_elev;
static int32_t          q_terrain;
static float            q_cmp;
static TrackRoute      *q_car_route[NCARS];
static TrackRoutePoint *q_car_point[NCARS];
static int32_t          q_guess_n;
static NearestRoutePointInfo q_guess[5];
static int32_t          q_zhit[NPOINTS];
static uint32_t         q_zflags[NPOINTS];
static int32_t          q_near;
static NearestRoutePointInfo q_near_info;
static TrackRoutePoint *q_closest[NROUTES];
static TrackRoutePoint *q_ahead[NROUTES];
static TrackRoute      *q_newroute;
static int              sound_on = 1;
// The sheet away from the points: boxes, the first holding a spot wins.
static int              q_nbox;
static float            q_box[NBOXES][5];  // x0 y0 x1 y1 z
static uint32_t         q_box_flags[NBOXES];
// GetNextRoutePoint's dead ends, after these points.
static int32_t          q_end[NPOINTS];
// Each sign's own route and point, when set.
static int32_t          q_sign_set[NPOINTS];
static TrackRoute      *q_sign_route[NPOINTS];
static TrackRoutePoint *q_sign_point[NPOINTS];
// FindNearbySignpost from each point: the count, and where it stops.
static int32_t          q_nearby[NPOINTS];
static NearestRoutePointInfo q_nearby_at[NPOINTS];
// FindPointsToTarget from each point.
static uint32_t         q_ptt_n[NPOINTS];
static NearestRoutePointInfo q_ptt[NPOINTS][8];

// ------------------------------------------------------------- printing

static uint32_t fb(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bf(uint32_t u)
{
    float f;

    memcpy(&f, &u, 4);
    return f;
}

static const char *pname(const void *p)
{
    static char buf[8][16];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "NULL";
    if (H != NULL) {
        if (p == (const void *)H)
            return "H";
        if (p == (const void *)&H->TopologyCoord)
            return "H.topo";
        if (p == (const void *)&H->DustEmitters)
            return "H.dust";
        if (p == (const void *)&H->TP)
            return "H.tp";
        if (p == (const void *)&H->CurrentPos)
            return "H.pos";
    }
    if (p == (const void *)&tgt)
        return "T";
    for (i = 0; i < NCARS; i++)
        if (p == (const void *)&cars[i]) {
            sprintf(b, "C%d", i);
            return b;
        }
    for (i = 0; i < NROUTES; i++)
        if (p == (const void *)&routes[i]) {
            sprintf(b, "R%d", i);
            return b;
        }
    for (i = 0; i < NPOINTS; i++) {
        if (p == (const void *)PT(i)) {
            sprintf(b, "P%d", i);
            return b;
        }
        if (p == (const void *)&signs[i]) {
            sprintf(b, "S%d", i);
            return b;
        }
    }
    if (p == (const void *)&snd)
        return "SND";
    if (p == (const void *)&wo)
        return "WO";
    if (p == (const void *)&pool)
        return "WOP";
    if (p == (const void *)&sheet)
        return "SHEET";
    if (p == (const void *)&TheTrackPathManager)
        return "TPM";
    if (p == (const void *)&world)
        return "WORLD";
    return "?";
}

static void *byname(const char *s)
{
    int i = atoi(s + 1);

    if (!strcmp(s, "NULL"))
        return NULL;
    switch (s[0]) {
    case 'C': return &cars[i];
    case 'R': return &routes[i];
    case 'P': return PT(i);
    }
    fprintf(stderr, "chopper_test: no object %s\n", s);
    exit(2);
}

// The point's number, or -1 for anything else.
static int find_point(const void *p)
{
    int i;

    for (i = 0; i < NPOINTS; i++)
        if (p == (const void *)PT(i))
            return i;
    return -1;
}

static int point_index(const void *p)
{
    int i = find_point(p);

    if (i < 0) {
        fprintf(stderr, "chopper_test: not a point\n");
        exit(2);
    }
    return i;
}

static void dump(void)
{
    const struct Chopper *h = H;
    const uint8_t *pad;
    int i;

    printf("dump plan %d mm %d think %08x car %s\n", h->Plan, h->MoveMode,
           fb(h->TimeUntilThink), pname(h->CurrentCar));
    printf("  route %s %s target %s %s old %s %s td %08x\n",
           pname(h->ChopperRoute), pname(h->ChopperPoint),
           pname(h->TargetRoute), pname(h->TargetPoint),
           pname(h->OldCarRoute), pname(h->OldCarPoint),
           fb(h->TargetDistance));
    printf("  bomb %d %d %08x %d timeout %08x stuck %08x total %d\n",
           h->BombRunType, h->NumSalvosReleased, fb(h->TimeUntilNextSalvo),
           h->NextLauncher, fb(h->Timeout), fb(h->StuckTime),
           h->TotalSalvos);
    printf("  pos %08x %08x %08x %08x\n", fb(h->CurrentPos.x),
           fb(h->CurrentPos.y), fb(h->CurrentPos.z), fb(h->CurrentPos.pad));
    printf("  mat");
    for (i = 0; i < 16; i++)
        printf(" %08x", fb(((const float *)&h->Matrix)[i]));
    printf("\n");
    printf("  speed %08x acc %08x %08x roll %08x %08x yaw %08x"
           " pitch %08x %08x\n", fb(h->Speed), fb(h->Acceleration.x),
           fb(h->Acceleration.y), fb(h->Roll), fb(h->DesiredRoll),
           fb(h->Yaw), fb(h->Pitch), fb(h->DesiredPitch));
    printf("  rot %08x zv %08x gz %08x dust %d n960 %d\n", fb(h->RotRate),
           fb(h->ZVelocity), fb(h->GroundZ), h->EmitDust, h->New960);
    printf("  tp %08x %08x %s %08x %08x %08x %08x %08x %s %08x\n",
           fb(h->TP.Position.x), fb(h->TP.Position.y),
           pname(h->TP.pTrackPoint), fb(h->TP.SplineParam),
           fb(h->TP.RatioAroundTrack), fb(h->TP.DistanceAroundTrack),
           fb(h->TP.PathDirection.x), fb(h->TP.PathDirection.y),
           pname(h->TP.pCaffeineObj), h->TP.CaffeineObjHigh);
    printf("  snd %s wo %s dust %s %s pad", pname(h->pChopperSound),
           pname(h->WorldObj), pname(h->DustEmitters.next),
           pname(h->DustEmitters.prev));
    pad = h->_pad964;
    for (i = 0; i < 12; i++)
        printf(" %02x", pad[i]);
    printf("\n");
    printf("  tgt %08x %08x %08x\n", fb(tgt.Location.x), fb(tgt.Location.y),
           fb(tgt.DesiredSpeed));
}

// ---------------------------------------------------------- the sound

static const char *soff(void *self)
{
    static char b[24];

    sprintf(b, "SND%+d", (int)((char *)self - (char *)&snd));
    return b;
}

static void s_dtor(void *self, int32_t flags)
{
    printf("  snd_dtor %s %d\n", soff(self), flags);
}

static void s_activate(void *self, int32_t on)
{
    printf("  snd_activate %s %d\n", soff(self), on);
}

static void s_update(void *self, float a, uint16_t b, float c)
{
    printf("  snd_update %s %08x %u %08x\n", soff(self), fb(a), b, fb(c));
}

static void s_mute(void *self, int32_t i)
{
    printf("  snd_mute %s %d\n", soff(self), i);
}

static Sound3d *s_create(struct Chopper *h)
{
    printf("  snd_new %s\n", pname(h));
    memset(&snd, 0, sizeof snd);
    snd._vtable = CHOPPERSOUND_VTABLE;
    return &snd;
}

static int32_t egg(int32_t n)
{
    return n == EGG_HELICOPTER ? q_egg : 0;
}

// ------------------------------------------------------------ the stubs

void topology_init(TopologyCoordinate *tc)
{
    printf("  topo_init %s\n", pname(tc));
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topo_dtor %s\n", pname(tc));
}

void topology_set_interest_bbox(TopologyCoordinate *tc, const bVector2 *pos,
                                float r, const bVector2 *vel)
{
    printf("  topo_bbox %s %s %08x %08x %08x %s\n", pname(tc), pname(pos),
           fb(pos->x), fb(pos->y), fb(r), pname(vel));
}

void topology_clear_interest_bbox(TopologyCoordinate *tc)
{
    printf("  topo_clear %s\n", pname(tc));
}

float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    printf("  topo_elev %s %08x %08x %08x %s %s %s\n", pname(tc),
           fb(pt->x), fb(pt->y), fb(pt->z), terrain != NULL ? "T" : "NULL",
           pname(normal), pname(found));
    if (terrain != NULL)
        *terrain = q_terrain;
    return q_elev;
}

void trackpath_coord_init(TrackPathCoordinate *c)
{
    printf("  tp_init %s\n", pname(c));
    memset(c, 0, sizeof *c);
    c->PathDirection.x = 1.0f;
}

void trackpath_coord_reset_position(TrackPathCoordinate *c,
                                    const bVector2 *pos)
{
    printf("  tp_reset %s %s %08x %08x\n", pname(c), pname(pos),
           fb(pos->x), fb(pos->y));
    c->pTrackPoint = NULL;
}

float trackpath_compare_distances(const TrackPathManager *m, float a,
                                  float b)
{
    printf("  tp_cmp %s %08x %08x\n", pname(m), fb(a), fb(b));
    return q_cmp;
}

void *bSlotOMalloc(BSlotPool *p)
{
    printf("  omalloc %s\n", pname(p));
    memset(&wo, 0xcd, sizeof wo);
    return &wo;
}

void bFree(void *p)
{
    printf("  free %s\n", pname(p));
}

WorldObject *worldobject_construct(WorldObject *o, uint32_t name_hash,
                                   const bMatrix4 *matrix,
                                   int32_t add_lighting)
{
    printf("  wo_ctor %s %08x %s %d\n", pname(o), name_hash, pname(matrix),
           add_lighting);
    return o;
}

void worldobject_destruct(WorldObject *o, int32_t flags)
{
    printf("  wo_dtor %s %d\n", pname(o), flags);
}

void afx_get_emitters(bNode *list, uint32_t group_hash)
{
    printf("  afx_get %s %08x\n", pname(list), group_hash);
}

void afx_delete_emitters(bNode *list)
{
    printf("  afx_del %s\n", pname(list));
}

int signposts_present(void)
{
    printf("  has_signposts\n");
    return q_signs;
}

static int car_index(const Car *c)
{
    int i = (int)(c - cars);

    if (i < 0 || i >= NCARS) {
        fprintf(stderr, "chopper_test: not a car\n");
        exit(2);
    }
    return i;
}

TrackRoute *car_get_route(Car *c, int find)
{
    printf("  get_route %s %d\n", pname(c), find);
    return q_car_route[car_index(c)];
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    printf("  get_point %s %d\n", pname(c), find);
    return q_car_point[car_index(c)];
}

int32_t ai_guess_target_destinations(NearestRoutePointInfo *out,
                                     uint32_t count, TrackRoute *route,
                                     TrackRoutePoint *point, float dist,
                                     int fwd)
{
    int32_t i;

    printf("  guess %u %s %s %08x %d\n", count, pname(route), pname(point),
           fb(dist), fwd);
    for (i = 0; i < q_guess_n; i++)
        out[i] = q_guess[i];
    return q_guess_n;
}

void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    int i;

    printf("  next %s %s\n", pname(info->Route), pname(info->Point));
    i = point_index(info->Point);
    if (q_end[i] || i + 1 >= NPOINTS) {
        info->Point = NULL;
        return;
    }
    i++;
    info->Route = &routes[i / PER_ROUTE];
    info->Point = PT(i);
}

// A point's polygon is the script's, per point; anywhere else, the first
// box holding the spot.
int32_t helisheet_find_z_value(HeliSheet *s, const bVector2 *pt, float *z,
                               uint32_t *flags)
{
    int i = find_point(pt);
    int k;

    printf("  zval %s %s %s %s %08x %08x\n", pname(s), pname(pt),
           z != NULL ? "Z" : "NULL", flags != NULL ? "F" : "NULL",
           fb(pt->x), fb(pt->y));
    if (i >= 0) {
        if (!q_zhit[i])
            return 0;
        if (z != NULL)
            *z = 1.0f;
        if (flags != NULL)
            *flags = q_zflags[i];
        return 1;
    }
    for (k = 0; k < q_nbox; k++) {
        if (q_box[k][0] <= pt->x && pt->x <= q_box[k][2]
            && q_box[k][1] <= pt->y && pt->y <= q_box[k][3]) {
            if (z != NULL)
                *z = q_box[k][4];
            if (flags != NULL)
                *flags = q_box_flags[k];
            return 1;
        }
    }
    return 0;
}

int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    printf("  nearest %s %08x %08x %d %d %08x\n", pname(pos), fb(pos->x),
           fb(pos->y), which, flags, fb(distanceAround));
    if (!q_near)
        return 0;
    *info = q_near_info;
    return 1;
}

TrackRoutePoint *troute_find_closest_point(TrackRoute *r, const bVector2 *pos,
                                           float radius, int flags,
                                           float distanceAround)
{
    int i = (int)(r - routes);

    printf("  closest %s %s %08x %d %08x\n", pname(r), pname(pos),
           fb(radius), flags, fb(distanceAround));
    if (i < 0 || i >= NROUTES) {
        fprintf(stderr, "chopper_test: not a route\n");
        exit(2);
    }
    return q_closest[i];
}

TrackRoutePoint *troute_find_closest_point_ahead(TrackRoute *r,
                                                 const bVector2 *pos,
                                                 TrackRoutePoint *start)
{
    int i = (int)(r - routes);

    printf("  ahead %s %s %08x %08x %s\n", pname(r), pname(pos),
           fb(pos->x), fb(pos->y), pname(start));
    if (i < 0 || i >= NROUTES) {
        fprintf(stderr, "chopper_test: not a route\n");
        exit(2);
    }
    return q_ahead[i];
}

// 12k-6's; here, what the run stands at when it fires.
void chopper_fire_salvo(struct Chopper *h)
{
    printf("  fire_salvo %s %d %d %d\n", pname(h), h->BombRunType,
           h->NumSalvosReleased, h->TotalSalvos);
}

Signpost *trpoint_get_signpost(const TrackRoutePoint *p)
{
    printf("  get_sign %s\n", pname(p));
    return &signs[point_index(p)];
}

static int sign_index(const Signpost *s)
{
    int i = (int)(s - signs);

    if (i < 0 || i >= NPOINTS) {
        fprintf(stderr, "chopper_test: not a sign\n");
        exit(2);
    }
    return i;
}

TrackRoute *signpost_get_new_route(const Signpost *s)
{
    int i = sign_index(s);

    printf("  new_route %s\n", pname(s));
    return q_sign_set[i] ? q_sign_route[i] : q_newroute;
}

TrackRoutePoint *signpost_get_new_route_point(const Signpost *s)
{
    int i = sign_index(s);

    printf("  new_point %s\n", pname(s));
    return q_sign_set[i] ? q_sign_point[i] : NULL;
}

// The neighbour within the point's own route, or NULL.
TrackRoutePoint *troute_get_relative_point(TrackRoute *r, TrackRoutePoint *p,
                                           int forward)
{
    int i = find_point(p);
    int j;

    printf("  relpt %s %s %d\n", pname(r), pname(p), forward);
    if (i < 0)
        return NULL;
    j = forward ? i + 1 : i - 1;
    if (j < 0 || j / PER_ROUTE != i / PER_ROUTE)
        return NULL;
    return PT(j);
}

int32_t ai_find_nearby_signpost(NearestRoutePointInfo *info, int fwd)
{
    int i = find_point(info->Point);

    printf("  nearby %s %s %d\n", pname(info->Route), pname(info->Point),
           fwd);
    if (i < 0 || q_nearby[i] == 0) {
        info->Point = NULL;
        return 0;
    }
    *info = q_nearby_at[i];
    return q_nearby[i];
}

uint32_t ai_find_points_to_target(const NearestRoutePointInfo *start,
                                  const NearestRoutePointInfo *target,
                                  NearestRoutePointInfo *out, uint32_t count,
                                  int fwd, int heli)
{
    int i = find_point(start->Point);
    uint32_t k, n;

    printf("  ptt %s %s %s %s %u %d %d\n", pname(start->Route),
           pname(start->Point), pname(target->Route), pname(target->Point),
           count, fwd, heli);
    if (i < 0)
        return 0;
    n = q_ptt_n[i] < count ? q_ptt_n[i] : count;
    for (k = 0; k < n; k++)
        out[k] = q_ptt[i][k];
    return n;
}

// The spot is (d, l) itself, which the boxes then judge.
void trpoint_get_position2(const TrackRoutePoint *p, bVector2 *o, float d,
                           float l)
{
    printf("  getpos %s %s %08x %08x\n", pname(p), pname(o), fb(d), fb(l));
    o->x = d;
    o->y = l;
}

// coputil.c's other callees, which nothing here reaches.

static void unreached(const char *f)
{
    fprintf(stderr, "chopper_test: %s reached\n", f);
    exit(3);
}

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    (void)c, (void)other, (void)angle;
    unreached("car_is_car_in_front");
    return 0;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    (void)c;
    unreached("collision_is_two_car_collision");
    return 0;
}

void collision_get_colliding_cars(Collision *c, struct Car **car1,
                                  struct Car **car2)
{
    (void)c, (void)car1, (void)car2;
    unreached("collision_get_colliding_cars");
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b, (void)i;
    unreached("collisionbody_get_collision");
    return NULL;
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    (void)w, (void)p;
    unreached("world_get_distance_to_closest_player_2d");
    return 0.0f;
}

// ------------------------------------------------------------- the script

#define MAXT 40

static int split(char *line, char **t)
{
    int n = 0;
    char *s = line;

    for (;;) {
        char *bar = strchr(s, '|');

        if (n < MAXT)
            t[n++] = s;
        if (bar == NULL)
            break;
        *bar = 0;
        s = bar + 1;
    }
    return n;
}

static uint32_t hx(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static float fh(const char *s)
{
    return bf(hx(s));
}

static void set_field(char **t)
{
    const char *f = t[1];
    struct Chopper *h = H;

    if (!strcmp(f, "plan"))
        h->Plan = atoi(t[2]);
    else if (!strcmp(f, "car"))
        h->CurrentCar = (Car *)byname(t[2]);
    else if (!strcmp(f, "n960"))
        h->New960 = atoi(t[2]);
    else if (!strcmp(f, "pos")) {
        h->CurrentPos.x = fh(t[2]);
        h->CurrentPos.y = fh(t[3]);
        h->CurrentPos.z = fh(t[4]);
    } else if (!strcmp(f, "yaw"))
        h->Yaw = fh(t[2]);
    else if (!strcmp(f, "roll"))
        h->Roll = fh(t[2]);
    else if (!strcmp(f, "pitch"))
        h->Pitch = fh(t[2]);
    else if (!strcmp(f, "gz"))
        h->GroundZ = fh(t[2]);
    else if (!strcmp(f, "td"))
        h->TargetDistance = fh(t[2]);
    else if (!strcmp(f, "tpd"))
        h->TP.DistanceAroundTrack = fh(t[2]);
    else if (!strcmp(f, "bomb"))
        h->BombRunType = atoi(t[2]);
    else if (!strcmp(f, "mm"))
        h->MoveMode = atoi(t[2]);
    else if (!strcmp(f, "salvos"))
        h->NumSalvosReleased = atoi(t[2]);
    else if (!strcmp(f, "launcher"))
        h->NextLauncher = atoi(t[2]);
    else if (!strcmp(f, "total"))
        h->TotalSalvos = atoi(t[2]);
    else if (!strcmp(f, "dust"))
        h->EmitDust = atoi(t[2]);
    else if (!strcmp(f, "think"))
        h->TimeUntilThink = fh(t[2]);
    else if (!strcmp(f, "nsalvo"))
        h->TimeUntilNextSalvo = fh(t[2]);
    else if (!strcmp(f, "timeout"))
        h->Timeout = fh(t[2]);
    else if (!strcmp(f, "stuck"))
        h->StuckTime = fh(t[2]);
    else if (!strcmp(f, "speed"))
        h->Speed = fh(t[2]);
    else if (!strcmp(f, "acc")) {
        h->Acceleration.x = fh(t[2]);
        h->Acceleration.y = fh(t[3]);
    } else if (!strcmp(f, "droll"))
        h->DesiredRoll = fh(t[2]);
    else if (!strcmp(f, "dpitch"))
        h->DesiredPitch = fh(t[2]);
    else if (!strcmp(f, "rot"))
        h->RotRate = fh(t[2]);
    else if (!strcmp(f, "zv"))
        h->ZVelocity = fh(t[2]);
    else if (!strcmp(f, "chop")) {
        h->ChopperRoute = (TrackRoute *)byname(t[2]);
        h->ChopperPoint = (TrackRoutePoint *)byname(t[3]);
    } else if (!strcmp(f, "target")) {
        h->TargetRoute = (TrackRoute *)byname(t[2]);
        h->TargetPoint = (TrackRoutePoint *)byname(t[3]);
    } else if (!strcmp(f, "old")) {
        h->OldCarRoute = (TrackRoute *)byname(t[2]);
        h->OldCarPoint = (TrackRoutePoint *)byname(t[3]);
    } else {
        fprintf(stderr, "chopper_test: no field %s\n", f);
        exit(2);
    }
}

static void answer(char **t, int n)
{
    const char *q = t[1];
    int i;

    if (!strcmp(q, "egg"))
        q_egg = atoi(t[2]);
    else if (!strcmp(q, "demo")) {
        TheRaceParameters.AIDemoMode = atoi(t[2]);
        TheRaceParameters.ReplayDemoMode = atoi(t[3]);
    } else if (!strcmp(q, "sheet"))
        TheHeliSheet = atoi(t[2]) ? &sheet : NULL;
    else if (!strcmp(q, "signs"))
        q_signs = atoi(t[2]);
    else if (!strcmp(q, "elev")) {
        q_elev = fh(t[2]);
        q_terrain = atoi(t[3]);
    } else if (!strcmp(q, "cmp"))
        q_cmp = fh(t[2]);
    else if (!strcmp(q, "carroute")) {
        i = atoi(t[2]);
        q_car_route[i] = (TrackRoute *)byname(t[3]);
        q_car_point[i] = (TrackRoutePoint *)byname(t[4]);
    } else if (!strcmp(q, "guess")) {
        q_guess_n = (n - 2) / 2;
        for (i = 0; i < q_guess_n; i++) {
            q_guess[i].Route = (TrackRoute *)byname(t[2 + 2 * i]);
            q_guess[i].Point = (TrackRoutePoint *)byname(t[3 + 2 * i]);
        }
    } else if (!strcmp(q, "zval")) {
        i = atoi(t[2]);
        q_zhit[i] = atoi(t[3]);
        q_zflags[i] = hx(t[4]);
    } else if (!strcmp(q, "near")) {
        q_near = atoi(t[2]);
        q_near_info.Route = (TrackRoute *)byname(t[3]);
        q_near_info.Point = (TrackRoutePoint *)byname(t[4]);
    } else if (!strcmp(q, "closest"))
        q_closest[atoi(t[2])] = (TrackRoutePoint *)byname(t[3]);
    else if (!strcmp(q, "ahead"))
        q_ahead[atoi(t[2])] = (TrackRoutePoint *)byname(t[3]);
    else if (!strcmp(q, "newroute"))
        q_newroute = (TrackRoute *)byname(t[2]);
    else if (!strcmp(q, "sound"))
        sound_on = atoi(t[2]);
    else if (!strcmp(q, "zbox")) {
        if (n == 2)
            q_nbox = 0;
        else {
            for (i = 0; i < 5; i++)
                q_box[q_nbox][i] = fh(t[2 + i]);
            q_box_flags[q_nbox++] = hx(t[7]);
        }
    } else if (!strcmp(q, "end"))
        q_end[atoi(t[2])] = atoi(t[3]);
    else if (!strcmp(q, "signto")) {
        i = atoi(t[2]);
        q_sign_set[i] = 1;
        q_sign_route[i] = (TrackRoute *)byname(t[3]);
        q_sign_point[i] = (TrackRoutePoint *)byname(t[4]);
    } else if (!strcmp(q, "nearby")) {
        i = atoi(t[2]);
        q_nearby[i] = atoi(t[3]);
        q_nearby_at[i].Route = (TrackRoute *)byname(t[4]);
        q_nearby_at[i].Point = (TrackRoutePoint *)byname(t[5]);
    } else if (!strcmp(q, "ptt")) {
        int k = atoi(t[2]);

        q_ptt_n[k] = (uint32_t)((n - 3) / 2);
        for (i = 0; i < (int)q_ptt_n[k]; i++) {
            q_ptt[k][i].Route = (TrackRoute *)byname(t[3 + 2 * i]);
            q_ptt[k][i].Point = (TrackRoutePoint *)byname(t[4 + 2 * i]);
        }
    } else {
        fprintf(stderr, "chopper_test: no answer %s\n", q);
        exit(2);
    }
}

static void car_op(char **t)
{
    Car *c = &cars[atoi(t[1])];

    c->State.Position.x = fh(t[2]);
    c->State.Position.y = fh(t[3]);
    c->State.Position.z = fh(t[4]);
    c->State.Angle = (uint16_t)atoi(t[5]);
    c->State.VelocityMagnitude = fh(t[6]);
    c->TheTrackPathCoordinate.DistanceAroundTrack = fh(t[7]);
}

static void point_op(char **t)
{
    TrackRoutePoint *p = PT(atoi(t[1]));

    p->Position.x = fh(t[2]);
    p->Position.y = fh(t[3]);
    p->Length = fh(t[4]);
    p->Bits = hx(t[5]);
    p->Direction.x = fh(t[6]);
    p->Direction.y = fh(t[7]);
}

static NearestRoutePointInfo info_of(char **t)
{
    NearestRoutePointInfo info;

    info.Route = (TrackRoute *)byname(t[0]);
    info.Point = (TrackRoutePoint *)byname(t[1]);
    return info;
}

static void run(char **t, int n)
{
    const char *op = t[0];
    struct Chopper *h = H;
    bVector2 v, o;

    printf("%s\n", op);
    if (!strcmp(op, "new")) {
        memset(&chopper, 0xcd, sizeof chopper);
        H = &chopper;
        gCreateChopperSoundFn = sound_on ? s_create : NULL;
        printf("  ret %s\n", pname(chopper_construct(&chopper)));
    } else if (!strcmp(op, "del")) {
        chopper_destruct(h, atoi(t[1]));
        return;
    } else if (!strcmp(op, "clear"))
        chopper_clear_variables(h);
    else if (!strcmp(op, "follow"))
        printf("  ret %d\n", chopper_follow_this_car(h, (Car *)byname(t[1])));
    else if (!strcmp(op, "attack"))
        printf("  ret %d\n", chopper_attack_car(h, atoi(t[1])));
    else if (!strcmp(op, "adjust"))
        chopper_adjust_bomb_target(h);
    else if (!strcmp(op, "shift"))
        chopper_shift_target(h, fh(t[1]));
    else if (!strcmp(op, "spot"))
        chopper_find_unobstructed_spot(h);
    else if (!strcmp(op, "ground"))
        printf("  ret %d\n", chopper_find_ground_height(h));
    else if (!strcmp(op, "place")) {
        v.x = fh(t[1]);
        v.y = fh(t[2]);
        chopper_place_in_world(h, &v, fh(t[3]));
    } else if (!strcmp(op, "remove")) {
        chopper_remove_from_world(h);
        printf("  wo %d\n", wo.Enabled);
    } else if (!strcmp(op, "behind"))
        printf("  ret %d\n", chopper_behind_car(h));
    else if (!strcmp(op, "rotate")) {
        v.x = fh(t[1]);
        v.y = fh(t[2]);
        chopper_rotate_to_chopper_coord(h, &o, &v);
        printf("  out %08x %08x\n", fb(o.x), fb(o.y));
        chopper_rotate_to_chopper_coord(h, &v, &v);
        printf("  same %08x %08x\n", fb(v.x), fb(v.y));
    } else if (!strcmp(op, "maxdecel"))
        printf("  ret %08x\n", fb(chopper_get_max_deceleration(h)));
    else if (!strcmp(op, "abort"))
        chopper_abort_bombing_run(h);
    else if (!strcmp(op, "mute"))
        chopper_mute(h, atoi(t[1]));
    else if (!strcmp(op, "usound"))
        chopper_update_sound(h);
    else if (!strcmp(op, "scratch"))
        chopper_find_point_from_scratch(h);
    else if (!strcmp(op, "routepoint"))
        chopper_find_route_point(h);
    else if (!strcmp(op, "matrix"))
        chopper_calc_matrix(h);
    else if (!strcmp(op, "wobj")) {
        int i;

        chopper_update_world_object(h);
        printf("  wo %d", wo.Enabled);
        for (i = 0; i < 16; i++)
            printf(" %08x", fb(((const float *)&wo.Matrix)[i]));
        printf("\n");
    } else if (!strcmp(op, "set"))
        set_field(t);
    else if (!strcmp(op, "q")) {
        answer(t, n);
        return;
    } else if (!strcmp(op, "car")) {
        car_op(t);
        return;
    } else if (!strcmp(op, "point")) {
        point_op(t);
        return;
    } else if (!strcmp(op, "carvel")) {
        Car *c = &cars[atoi(t[1])];

        c->State.Velocity.x = fh(t[2]);
        c->State.Velocity.y = fh(t[3]);
        c->State.Velocity.z = fh(t[4]);
        return;
    } else if (!strcmp(op, "width")) {
        TrackRoutePoint *p = PT(atoi(t[1]));

        p->LeftWidth = fh(t[2]);
        p->RightWidth = fh(t[3]);
        return;
    } else if (!strcmp(op, "sign")) {
        uint32_t w = hx(t[2]);

        memcpy(&signs[atoi(t[1])], &w, 4);
        return;
    } else if (!strcmp(op, "tgt")) {
        tgt.Location.x = fh(t[1]);
        tgt.Location.y = fh(t[2]);
        tgt.DesiredSpeed = fh(t[3]);
        return;
    } else if (!strcmp(op, "start"))
        printf("  ret %d\n", chopper_start_chase_logic(h, &tgt, atoi(t[1]),
                                                       hx(t[2]), fh(t[3])));
    else if (!strcmp(op, "endchase"))
        printf("  ret %d\n", chopper_end_chase_logic(h, &tgt));
    else if (!strcmp(op, "fspeed"))
        chopper_set_follow_speed(h, &tgt);
    else if (!strcmp(op, "prevfork")) {
        NearestRoutePointInfo info = info_of(t + 1);
        int32_t r = chopper_find_previous_fork(h, &info, atoi(t[3]));

        printf("  ret %d %s %s\n", r, pname(info.Route), pname(info.Point));
    } else if (!strcmp(op, "switchfork")) {
        NearestRoutePointInfo in = info_of(t + 1), out;
        int32_t r;

        memset(&out, 0xcd, sizeof out);
        r = chopper_switch_to_nearby_fork(h, &out, &in, atoi(t[3]),
                                          fh(t[4]));
        printf("  ret %d %s %s\n", r, pname(out.Route), pname(out.Point));
    } else if (!strcmp(op, "tcp"))
        chopper_target_chopper_point(h, &tgt);
    else if (!strcmp(op, "followroute"))
        chopper_follow_route(h, &tgt, (TrackRoute *)byname(t[1]),
                             (TrackRoutePoint *)byname(t[2]), atoi(t[3]));
    else if (!strcmp(op, "stakeout"))
        chopper_begin_stakeout(h, &tgt, (TrackRoute *)byname(t[1]),
                               (TrackRoutePoint *)byname(t[2]));
    else if (!strcmp(op, "hangout"))
        chopper_hangout_near_here(h, &tgt, (TrackRoute *)byname(t[1]),
                                  (TrackRoutePoint *)byname(t[2]));
    else if (!strcmp(op, "bail"))
        chopper_bail_to_point_near_chopper(h, &tgt);
    else if (!strcmp(op, "minfollow"))
        printf("  ret %08x\n",
               fb(chopper_calc_min_route_follow_distance(h, &tgt)));
    else if (!strcmp(op, "inbounds"))
        printf("  ret %d\n", chopper_adjust_target_in_bounds(h, &tgt));
    else if (!strcmp(op, "difffork"))
        printf("  ret %d\n", chopper_on_different_fork(
                   h, (TrackRoute *)byname(t[1]),
                   (TrackRoutePoint *)byname(t[2])));
    else if (!strcmp(op, "local"))
        chopper_adjust_target_local(h, &tgt);
    else if (!strcmp(op, "testloc"))
        printf("  ret %d\n", chopper_test_location(h, fh(t[1]), fh(t[2])));
    else if (!strcmp(op, "bythink"))
        printf("  ret %08x\n", fb(chopper_adjust_by_think_time(h, fh(t[1]))));
    else if (!strcmp(op, "clever"))
        chopper_clever_pursuit_plan(h, &tgt, atoi(t[1]), hx(t[2]));
    else if (!strcmp(op, "bombrun"))
        chopper_bomb_run_logic(h, &tgt);
    else if (!strcmp(op, "hlp"))
        printf("  ret %d\n", chopper_high_level_planning(h, &tgt));
    else {
        fprintf(stderr, "chopper_test: no op %s\n", op);
        exit(2);
    }
    dump();
}

int main(int argc, char **argv)
{
    static const VtEntry vt[5] = {
        { 0, 0, NULL },
        { 8, 0, (VtFn)s_dtor },
        { 8, 0, (VtFn)s_activate },
        { 8, 0, (VtFn)s_update },
        { 8, 0, (VtFn)s_mute },
    };
    static char line[4096];
    char *t[MAXT];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: chopper_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    vt_install(CHOPPERSOUND_VTABLE, vt, 5);
    pCurrentWorld = &world;
    world.CarTable[0] = &cars[0];
    WorldObjectSlotPool = (BSlotPool *)(void *)&pool;
    gEggIsOnFn = egg;
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);
        int n;

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        n = split(line, t);
        run(t, n);
    }
    fclose(f);
    return 0;
}
