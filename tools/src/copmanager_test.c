// Harness for tools/copmanager_check.py: runs the checker's script on
// copmgr.c -- the cop chunks' loader, tCopManager's constructor and
// destructor, the roadblock and speed-trap tables, the speakers and the
// landmarks -- and prints what the model prints for the retail image. See
// the checker's docstring.
//
//     copmanager_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "cop.h"
#include "copmgr.h"
#include "coputil.h"
#include "drivetarget.h"
#include "drivetargetrenderer.h"
#include "race.h"
#include "racecoord.h"
#include "raceparams.h"
#include "racesplit.h"
#include "realdriver.h"
#include "realtime.h"
#include "timer.h"
#include "topology.h"
#include "trackgraph.h"
#include "trackmap.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

// tPlayerCop's and tAICop's DoSnapshots, slot 32 of their tables
// (copsnap.c, TASKS 72e-2, checked by tools/copsnap_check.py): in the
// tables, never called here.
void tplayercop_do_snapshot(tPlayerCop *c, struct ReplaySnapshot *s)
{
    (void)c;
    (void)s;
    fprintf(stderr, "tplayercop_do_snapshot reached\n");
    abort();
}

void taicop_do_snapshot(tAICop *c, struct ReplaySnapshot *s)
{
    (void)c;
    (void)s;
    fprintf(stderr, "taicop_do_snapshot reached\n");
    abort();
}

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

// ------------------------------------------------------------ the names

#define MAX_NAMES  512
#define MAX_CHUNKS 64

static struct {
    const void *p;
    char        name[24];
} names[MAX_NAMES];
static int nnames;

static struct {
    uint8_t *base;
    size_t   size;
} chunks[MAX_CHUNKS];

static void name(const void *p, const char *fmt, int k)
{
    if (nnames == MAX_NAMES) {
        fprintf(stderr, "too many names\n");
        exit(2);
    }
    names[nnames].p = p;
    snprintf(names[nnames].name, sizeof names[nnames].name, fmt, k);
    nnames++;
}

static char symbuf[8][32];
static int  symnext;

static const char *sym(const void *p)
{
    char     *b = symbuf[symnext++ & 7];
    uintptr_t u = (uintptr_t)p;
    int       i;

    if (p == NULL)
        return "0";
    if (u == (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        return "cd";
    for (i = nnames - 1; i >= 0; i--)
        if (names[i].p == p)
            return names[i].name;
    for (i = 0; i < MAX_CHUNKS; i++)
        if (chunks[i].base != NULL && (const uint8_t *)p >= chunks[i].base
            && (const uint8_t *)p < chunks[i].base + chunks[i].size) {
            snprintf(b, 32, "c%d+%d", i,
                     (int)((const uint8_t *)p - chunks[i].base));
            return b;
        }
    return "?";
}

// ------------------------------------------------- what copmgr.c reaches

RaceParameters   TheRaceParameters;
TrackPathManager TheTrackPathManager;
World           *pCurrentWorld;
float            SkipFETimeUntilCopsAppear;
float            WorldTimeElapsed;
Race            *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
tTrackGraph     *TheTrackGraph;

static int32_t         skipfe;
static World           world_token;
static Race            the_race;
static RaceCoordinator the_rc;
static tTrackGraph     the_graph;
static uint32_t        dist_bits;
static int32_t         speech_state;
static TrackRoutePoint pts[16];
static TrackRoute      routes[3];
static int32_t         npts;
static int32_t         topo_force = -1;
static int32_t         polyhit = -1;
static const void     *topo;
static int             mgrs, pools;

int32_t config_skip_fe(void)
{
    return skipfe;
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size);

    memset(p, 0xcd, (size_t)size);
    name(p, "M%d", mgrs);
    if (size == (int)sizeof(tCopManager)) {
        name(&((tCopManager *)(void *)p)->PursuitList, "M%d.plist", mgrs);
        name(&((tCopManager *)(void *)p)->SpikeStripList, "M%d.slist",
             mgrs);
        size = TCOPMANAGER_SIZE;
    }
    printf("  malloc %d %s %d %d -> M%d\n", size, nm, flags, pool, mgrs);
    mgrs++;
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", sym(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *nm,
                        int memoryPool)
{
    static uint8_t tokens[16][16];
    void          *p = tokens[pools & 15];

    name(p, "pool%d", pools);
    printf("  newpool %d %d %s %d -> pool%d\n", slotSize, numSlots, nm,
           memoryPool, pools);
    pools++;
    return (BSlotPool *)p;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", sym(pool));
}

static void voices(void)
{
    printf("  voices\n");
}

static void flush(void)
{
    printf("  flush\n");
}

int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    uint32_t x = fb(pos->x), y = fb(pos->y);
    uint32_t h = x * 0x9E3779B1u + y;
    int32_t  k = (int32_t)((h >> 7) % (uint32_t)(npts + 1));

    printf("  nrp %08x %08x w%d f%d %08x", x, y, (int)which, flags,
           fb(distanceAround));
    if (k == npts) {
        printf(" -> none\n");
        return 0;
    }
    info->Route = &routes[k % 3];
    info->Point = &pts[k];
    printf(" -> R%d P%d\n", k % 3, k);
    return 1;
}

void topology_init(TopologyCoordinate *tc)
{
    topo = tc;
    printf("  topo init\n");
}

int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy)
{
    uint32_t x = fb(xy->x), y = fb(xy->y);
    int      has = ((x ^ (y >> 3) ^ 0x5bd1e995u) % 7) != 0;

    if (topo_force >= 0)
        has = topo_force != 0;
    printf("  topo has %08x %08x %s -> %d\n", x, y,
           (const void *)tc == topo ? "same" : "other", has);
    return has;
}

void topology_destroy(TopologyCoordinate *tc)
{
    printf("  topo destroy %s\n",
           (const void *)tc == topo ? "same" : "other");
    topo = NULL;
}

void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos)
{
    uint32_t x = fb(pos->x), y = fb(pos->y);

    c->DistanceAroundTrack = bf(((x >> 1) + (y >> 2)) & 0x3fffffffu);
    printf("  tpc %08x %08x\n", x, y);
}

void trpoint_get_position2(const TrackRoutePoint *p, bVector2 *o, float d,
                           float l)
{
    int32_t k = (int32_t)(p - pts);

    o->x = bf(fb(d) ^ 0x00012345u);
    o->y = bf(fb(l) + 0x100u + (uint32_t)k);
    printf("  getpos %s %08x %08x\n", sym(p), fb(d), fb(l));
}

// World::Random's answers: the script's queue first (12j-1), then the
// bits with 0x00300000 flipped (the float's) or 0 (the int's).
#define RQ_MAX 256
static uint32_t rq[RQ_MAX];
static int32_t  riq[RQ_MAX];
static int      nrq, rqi, nriq, riqi;

float world_random_f(World *w, float f)
{
    printf("  random %s %08x\n", sym(w), fb(f));
    if (rqi < nrq)
        return bf(rq[rqi++]);
    return bf(fb(f) ^ 0x00300000u);
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    printf("  dist %s %08x %08x -> %08x\n", sym(w), fb(p->x), fb(p->y),
           dist_bits);
    return bf(dist_bits);
}

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    printf("  uncloak %s\n", g == &the_graph ? "G" : "?");
}

int32_t is_point_in_poly(const bVector2 *p, const bVector2 *poly, int32_t n)
{
    uint32_t x = fb(p->x), y = fb(p->y);
    const Landmark *l = (const Landmark *)(const void *)
        ((const uint8_t *)poly - offsetof(Landmark, VertsForArea));
    int32_t  idx = (int32_t)(l - LandmarkData->LandmarkArray);
    int      in;

    if (polyhit >= 0)
        in = idx == polyhit;
    else
        in = (x + 3u * y + (uint32_t)idx * 0x10001u) % 5u == 0;
    printf("  poly L%d n%d %08x %08x -> %d\n", idx, n, x, y, in);
    return in;
}

// ----------------------------------------------------- the impacts

#define NCARS 6

static Car              cars[NCARS];
static CarCollisionBody bodies[NCARS];
static int32_t          colls[16];
static int32_t          ncoll;
static uint8_t          ktok[16][16];

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b;
    printf("  getcoll %d\n", i);
    return (struct Collision *)(void *)ktok[i];
}

int32_t collision_is_two_car_collision(Collision *c)
{
    int i = (int)((uint8_t (*)[16])(void *)c - ktok);

    printf("  twocar %d -> %d\n", i, colls[i]);
    return colls[i];
}

// cop.c's, which the script never reaches.
static void unreached(const char *f)
{
    fprintf(stderr, "copmanager_test: %s reached\n", f);
    exit(3);
}

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    (void)c; (void)driver; (void)pos; (void)angle; (void)dist;
    unreached("car_construct");
    return NULL;
}

int32_t can_teleport(Car *car, const bVector2 *dest)
{
    (void)car; (void)dest;
    unreached("can_teleport");
    return 0;
}

Car *car_caused_recent_collision(Car *car)
{
    (void)car;
    unreached("car_caused_recent_collision");
    return NULL;
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    (void)c; (void)mode;
    unreached("car_set_control_mode");
}

// tAICop::Teleport's, under SetSpeedTrap (12j-1).
void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  movement %s %d\n", sym(c), (int)mode);
}

void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    printf("  reset %s %08x %08x %08x %08x %04x\n", sym(c), fb(pos->x),
           fb(pos->y), fb(pos->z), fb(speed), angle);
}

void *bSlotOMalloc(BSlotPool *pool)
{
    (void)pool;
    unreached("bSlotOMalloc");
    return NULL;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    (void)pool; (void)slot;
    unreached("bSlotFree");
}

// The drive target's (12d), which cop_check checks.
TrackRoute *car_get_route(Car *c, int find)
{
    (void)c; (void)find;
    unreached("car_get_route");
    return NULL;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    (void)c; (void)find;
    unreached("car_get_route_point");
    return NULL;
}

void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    (void)info;
    unreached("ai_get_next_route_point");
}

float trpoint_get_driving_line_offset(const TrackRoutePoint *p, int line)
{
    (void)p; (void)line;
    unreached("trpoint_get_driving_line_offset");
    return 0.0f;
}

void trpoint_get_position3(const TrackRoutePoint *p, bVector3 *o, float d,
                           float l)
{
    (void)p; (void)o; (void)d; (void)l;
    unreached("trpoint_get_position3");
}

void drivetarget_clear(DriveTarget *t, Car *car, float speed)
{
    (void)t; (void)car; (void)speed;
    unreached("drivetarget_clear");
}

void drivetarget_add_point3(DriveTarget *t, const bVector3 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car)
{
    (void)t; (void)p; (void)route; (void)rpn; (void)dl; (void)check;
    (void)car;
    unreached("drivetarget_add_point3");
}

// tAICop::Think's and ResetAllDamage's (12g). The script's cops think
// through this harness's own tables, so these are never reached.
int32_t             CameraFollowThisCarInstead = -1;
DriveTargetRenderer TheDriveTargetRenderer;

void drivetargetrenderer_set_target_to_render(DriveTargetRenderer *r,
                                              DriveTarget *t)
{
    (void)r; (void)t;
    unreached("drivetargetrenderer_set_target_to_render");
}

void collisionbody_enable_collisions(CollisionBody *b)
{
    (void)b;
    unreached("collisionbody_enable_collisions");
}

void collisionbody_disable_collisions(CollisionBody *b)
{
    (void)b;
    unreached("collisionbody_disable_collisions");
}

void realdriver_force_ebrake_stop(RealDriver *d, float t)
{
    (void)d; (void)t;
    unreached("realdriver_force_ebrake_stop");
}

int32_t world_random_i(World *w, int32_t range)
{
    int32_t v = riqi < nriq ? riq[riqi++] : 0;

    printf("  randomi %s %d -> %d\n", sym(w), range, v);
    return v;
}

// The chase's (12g-3), which cop_check checks.

void carstate_world_to_car2(CarState *s, bVector2 *out, const bVector2 *in)
{
    (void)s; (void)out; (void)in;
    unreached("carstate_world_to_car2");
}

// The radar's (12n). IsCarInFront answers by the car asked about, and
// CompareDistances by its second distance's bits (0 for one not given).
static int32_t  infront[NCARS];
static uint32_t cmp_key[16], cmp_ans[16];
static int      ncmp;

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    int32_t v = infront[other - cars];

    printf("  infront %s %s %d -> %d\n", sym(c), sym(other), (int)angle, v);
    return v;
}

float trackpath_compare_distances(const TrackPathManager *m, float a,
                                  float b)
{
    uint32_t v = 0;
    int      i;

    for (i = 0; i < ncmp; i++)
        if (cmp_key[i] == fb(b))
            v = cmp_ans[i];
    printf("  compare %s %08x %08x -> %08x\n",
           m == &TheTrackPathManager ? "TPM" : "?", fb(a), fb(b), v);
    return bf(v);
}

int32_t did_these_cars_collide(Car *a, Car *b)
{
    (void)a; (void)b;
    unreached("did_these_cars_collide");
    return 0;
}

static void disable_my_car(tCop *cop, int32_t b)
{
    printf("  disable %s %d\n", sym(cop), b);
}

// ---------------------------------------- the pursuits', cops', spikes'

#define VT_PURSUIT    0x002bd460u
#define VT_AICOP      0x002bd698u
#define VT_PLAYERCOP  0x002bd6c0u
#define VT_SPIKE      0x002be688u

static void pursuit_dtor(void *self, int32_t flags)
{
    printf("  pursuit dtor %s flags %d\n", sym(self), flags);
}

static void aicop_dtor(void *self, int32_t flags)
{
    printf("  aicop dtor %s flags %d\n", sym(self), flags);
}

static void playercop_dtor(void *self, int32_t flags)
{
    printf("  playercop dtor %s flags %d\n", sym(self), flags);
}

static void spike_dtor(void *self, int32_t flags)
{
    printf("  spike dtor %s flags %d\n", sym(self), flags);
}

static const VtEntry pursuit_vt[] = { {0, 0, NULL},
                                      {0, 0, (VtFn)pursuit_dtor} };
// IsAIControlled, 0x00230d60 and 0x00230d98, which the model runs.
static int32_t aicop_is_ai(void *self)
{
    (void)self;
    return 1;
}

static int32_t playercop_is_ai(void *self)
{
    (void)self;
    return 0;
}

// Think, 0x0022df88 and 0x0022d5c8, which the model stubs.
static void aicop_think(void *self)
{
    printf("  aicop think %s\n", sym(self));
}

static void playercop_think(void *self)
{
    printf("  playercop think %s\n", sym(self));
}

static const VtEntry aicop_vt[] = { {0, 0, NULL},
                                    {0, 0, (VtFn)aicop_dtor},
                                    {0, 0, (VtFn)aicop_is_ai},
                                    {0, 0, (VtFn)aicop_think} };
static const VtEntry playercop_vt[] = { {0, 0, NULL},
                                        {0, 0, (VtFn)playercop_dtor},
                                        {0, 0, (VtFn)playercop_is_ai},
                                        {0, 0, (VtFn)playercop_think} };
static const VtEntry spike_vt[] = { {0, 0, NULL},
                                    {0, 0, (VtFn)spike_dtor} };

static tPursuit *pursuits[16];
static int32_t   updates[16], cansupers[16];
static uint8_t   player_token[16];

static int pursuit_index(const tPursuit *p)
{
    int u;

    for (u = 0; u < 16; u++)
        if (pursuits[u] == p)
            return u;
    return -1;
}

// ---------------------------------------------------- Think's seams

static int32_t pursuit_update(tPursuit *p)
{
    int u = pursuit_index(p);

    printf("  update U%d -> %d\n", u, updates[u]);
    return updates[u];
}

static int32_t can_super(tPursuit *p)
{
    int u = pursuit_index(p);

    printf("  cansuper U%d -> %d\n", u, cansupers[u]);
    return cansupers[u];
}

static void super_initiates(tPursuit *p)
{
    printf("  superinit U%d\n", pursuit_index(p));
}

// The cookie's retail offset in the manager when it is the manager's.
static void filler(tPursuit *p, uint32_t *cookie)
{
    printf("  filler U%d %d\n", pursuit_index(p),
           cookie == &pCopManager->SpeechFillerCookie ? 10352 : -1);
}

static int32_t speech_playback(void)
{
    return speech_state;
}

static void spawn_speed_traps(tCopManager *m)
{
    printf("  spawnst %s\n", sym(m));
}

static void spike_belts(tCopManager *m)
{
    printf("  spikebelts %s\n", sym(m));
}

static void end_pullover(tCopManager *m, int32_t i)
{
    printf("  endpull %s %d\n", sym(m), i);
}

static void beacop_think(tCopManager *m)
{
    printf("  beacopthink %s\n", sym(m));
}

// ------------------------------------------- SpawnSpeedTraps's (12j-1)

static int32_t  split_set;
static uint32_t split_bits;
static int32_t  freerun_v;
static int32_t  ftrap_k = -1;
static int32_t  tclear_v;

// CalculateSplitTime's answer, or none: the timer left as it was.
void race_calculate_split_time(Race *r, Timer *out, struct RacingCar *a,
                               struct RacingCar *b)
{
    printf("  split %s %s %s", sym(r), sym(a), sym(b));
    if (split_set) {
        out->PackedTime = split_bits;
        printf(" -> %08x\n", split_bits);
    } else {
        printf(" -> none\n");
    }
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    printf("  freerun %s -> %d\n", rp == &TheRaceParameters ? "RP" : "?",
           freerun_v);
    return freerun_v;
}

static const char *trap_sym(const void *p)
{
    static char b[8][16];
    static int  n;
    char       *s = b[n++ & 7];
    int         k;

    for (k = 0; k < COPMANAGER_MAX_SPEEDTRAPS; k++) {
        if (p == &pCopManager->SpeedTraps[k]) {
            snprintf(s, 16, "st%d", k);
            return s;
        }
        if (p == &pCopManager->SpeedTraps[k].v2Position) {
            snprintf(s, 16, "st%d.pos", k);
            return s;
        }
    }
    return sym(p);
}

struct tSpeedTrap *trackgraph_find_speed_trap(tTrackGraph *g,
                                              struct Car *car, float fMin,
                                              float fMax, int32_t forward)
{
    tSpeedTrap *t = ftrap_k >= 0 ? &pCopManager->SpeedTraps[ftrap_k] : NULL;

    printf("  findtrap %s %s %08x %08x %d -> %s\n",
           g == &the_graph ? "G" : "?", sym(car), fb(fMin), fb(fMax),
           forward, t != NULL ? trap_sym(t) : "none");
    return t;
}

int32_t is_teleport_location_clear(const bVector2 *p)
{
    printf("  tclear %s %08x %08x -> %d\n", trap_sym(p), fb(p->x),
           fb(p->y), tclear_v);
    return tclear_v;
}

static uint32_t num(const char *s);

static int spawn_op(tCopManager *m, char **a)
{
    const char *o = a[0];

    if (!strcmp(o, "race")) {
        the_race.NumRacingCars = (int32_t)num(a[1]);
    } else if (!strcmp(o, "rcar")) {
        int               i = atoi(a[1]), k = atoi(a[2]);
        struct RacingCar *rc = &the_race.RacingCarTable[i];

        if (k < 0) {
            the_race.pRacingCars[i] = NULL;
        } else {
            the_race.pRacingCars[i] = rc;
            rc->pCar = &cars[k];
            rc->FinishReason = (int16_t)num(a[3]);
            rc->FinishedLapNumberExact = bf(num(a[4]));
        }
    } else if (!strcmp(o, "pcops")) {
        tPursuit *p = pursuits[atoi(a[1])];

        p->nMaxChaseCops = (int32_t)num(a[2]);
        p->nNumCops = (int32_t)num(a[3]);
        p->bAlreadyCalledForBackup = (int32_t)num(a[4]);
    } else if (!strcmp(o, "tickets")) {
        m->CarPullovers[atoi(a[1])].nNumTickets = (int8_t)num(a[2]);
    } else if (!strcmp(o, "clss")) {
        m->Cops[atoi(a[1])]->LogicSubState = (eLogicSubState)num(a[2]);
    } else if (!strcmp(o, "rq") || !strcmp(o, "riq")) {
        int f = !strcmp(o, "rq");

        if (!strcmp(a[1], "clear")) {
            if (f)
                nrq = rqi = 0;
            else
                nriq = riqi = 0;
        } else if (f) {
            if (rqi == nrq)
                nrq = rqi = 0;
            if (nrq == RQ_MAX) {
                fprintf(stderr, "rq full\n");
                exit(2);
            }
            rq[nrq++] = num(a[1]);
        } else {
            if (riqi == nriq)
                nriq = riqi = 0;
            if (nriq == RQ_MAX) {
                fprintf(stderr, "riq full\n");
                exit(2);
            }
            riq[nriq++] = (int32_t)num(a[1]);
        }
    } else if (!strcmp(o, "split")) {
        split_set = strcmp(a[1], "none") != 0;
        if (split_set)
            split_bits = num(a[1]);
    } else if (!strcmp(o, "freerun")) {
        freerun_v = (int32_t)num(a[1]);
    } else if (!strcmp(o, "ftrap")) {
        ftrap_k = atoi(a[1]);
    } else if (!strcmp(o, "tclear")) {
        tclear_v = (int32_t)num(a[1]);
    } else if (!strcmp(o, "stcop")) {
        int c = atoi(a[2]);

        m->SpeedTraps[atoi(a[1])].cop = c >= 0 ? m->Cops[c] : NULL;
    } else if (!strcmp(o, "stpos")) {
        tSpeedTrap *s = &m->SpeedTraps[atoi(a[1])];

        s->v2Position.x = bf(num(a[2]));
        s->v2Position.y = bf(num(a[3]));
        s->ang = (uint16_t)num(a[4]);
    } else if (!strcmp(o, "spawn")) {
        copmanager_spawn_speed_traps(m);
        printf("spawn\n");
    } else if (!strcmp(o, "findcop")) {
        printf("findcop -> %s\n",
               sym(copmanager_find_cop_for_speed_trap(m)));
    } else if (!strcmp(o, "realspawn")) {
        gCopManagerSpawnSpeedTrapsFn = num(a[1]) ? copmanager_spawn_speed_traps
                                                 : spawn_speed_traps;
    } else if (!strcmp(o, "spstate")) {
        int k;

        printf("sp timer");
        for (k = 0; k < 8; k++)
            printf(" %08x", fb(m->fSpeedTrapSpawnTimer[k]));
        printf(" cops");
        for (k = 0; k < 7; k++) {
            const tAICop *c = (const tAICop *)(const void *)m->Cops[k];

            if (c == NULL)
                printf(" -");
            else
                printf(" %d/%d/%s", c->Base.DesiredLogicState,
                       c->Base.LogicSubState, trap_sym(c->pMySpeedTrap));
        }
        printf(" traps");
        for (k = 0; k < 8; k++)
            printf(" %s", sym(m->SpeedTraps[k].cop));
        printf("\n");
    } else {
        return 0;
    }
    return 1;
}

static void link_tail(tPursuitNode *list, tPursuitNode *node)
{
    tPursuitNode *prev = list->Prev;

    node->Next = list;
    node->Prev = prev;
    prev->Next = node;
    list->Prev = node;
}

// ---------------------------------------------------------- the dump

static void statics(void)
{
    printf("statics traps %s blocks %s land %s\n", sym(SpeedTrapData),
           sym(RoadblockData), sym(LandmarkData));
}

static void hexwords(const void *p, int n)
{
    const uint8_t *b = p;
    int            i;

    for (i = 0; i < n; i++) {
        uint32_t w;

        memcpy(&w, b + 4 * i, 4);
        printf("%s%08x", i ? " " : "", w);
    }
}

static void dump(void)
{
    tCopManager *m = pCopManager;
    int          k;

    if (m == NULL) {
        printf("M none pools %s", sym(PursuitSlotPool));
        printf(" %s", sym(CopSlotPool));
        printf(" %s\n", sym(SpikeStripSlotPool));
        return;
    }
    printf("M %s head %d %d %d %d\n", sym(m), m->nBeACopNumRoadBlocks,
           m->nNumAICops, m->nNumCops, m->nPlayerCopIndex);
    printf("M cops");
    for (k = 0; k < 7; k++)
        printf(" %s", sym(m->Cops[k]));
    printf("\nM plist %s", sym(m->PursuitList.Next));
    printf(" %s\n", sym(m->PursuitList.Prev));
    printf("M byid");
    for (k = 0; k < 6; k++)
        printf(" %s", sym(m->PursuitsById[k]));
    printf("\nM new76 %s\n", sym(m->New76));
    printf("M slist %s", sym(m->SpikeStripList.Next));
    printf(" %s\n", sym(m->SpikeStripList.Prev));
    for (k = 0; k < 8; k++) {
        const tCarPulloverInfo *pl = &m->CarPullovers[k];
        const uint8_t          *pad = (const uint8_t *)&pl->nNumTickets;

        printf("M pull%d %d %08x %d %02x%02x%02x %d %d %d %d\n", k,
               pl->nCopIndex, fb(pl->fHoldTimer), pl->nNumTickets, pad[1],
               pad[2], pad[3], pl->bActive, pl->bPlayNIS, pl->bArrest,
               pl->bShouldDisplayBustedText);
    }
    printf("M chopper %d nrb %d\n", m->bChopperBusy, m->nNumRoadBlocks);
    for (k = 0; k < 64; k++) {
        const tRoadBlock *r = &m->RoadBlocks[k];

        printf("M rb%02d %s", k, sym(r->cops[0]));
        printf(" %s pos ", sym(r->cops[1]));
        hexwords(r->CopPos, 4);
        printf(" ang %08x icon %04x %04x name %s",
               (uint32_t)r->CopAng[0] | (uint32_t)r->CopAng[1] << 16,
               r->aTrackMapIconAngle, r->Pad30, sym(r->Name));
        printf(" pt %s", sym(r->RoutePoint));
        printf(" rt %s w %08x side %d belt ", sym(r->Route),
               fb(r->fRoadWidth), r->nSpikeSide);
        hexwords(&r->v2SpikeBeltPos, 2);
        printf(" ");
        hexwords(&r->v2SpikeBeltVec, 2);
        printf(" pos %08x %08x D %08x %08x L %08x %08x esc %08x %08x "
               "dist %08x idx %d diff %d flags %08x spk %08x\n",
               fb(r->v2Position.x), fb(r->v2Position.y), fb(r->D.x),
               fb(r->D.y), fb(r->L.x), fb(r->L.y), fb(r->v2EscapeLane.x),
               fb(r->v2EscapeLane.y), fb(r->fDistanceAroundTrack),
               r->nIndexIntoLoadedData, r->Difficulty, r->Flags,
               r->CopSpeaker);
    }
    printf("M rbidx");
    for (k = 0; k < 64; k++)
        printf(" %d", m->RealRoadBlockIndexFromDataIndex[k]);
    printf("\nM nst %d\n", m->nNumSpeedTraps);
    for (k = 0; k < 64; k++) {
        const tSpeedTrap *t = &m->SpeedTraps[k];

        printf("M st%02d %s pos %08x %08x ang %04x %04x", k, sym(t->cop),
               fb(t->v2Position.x), fb(t->v2Position.y), t->ang, t->Pad14);
        printf(" name %s dist %08x flags %08x\n", sym(t->Name),
               fb(t->fDistanceAroundTrack), t->Flags);
    }
    printf("M stidx");
    for (k = 0; k < 64; k++)
        printf(" %d", m->RealSpeedTrapIndexFromDataIndex[k]);
    printf("\nM spk ");
    hexwords(m->CopSpeakers.Data, 4);
    printf(" %d %d %d\n", m->CopSpeakers.Head, m->CopSpeakers.Tail,
           m->CopSpeakers.Full);
    printf("M id %08x speech %08x %08x %08x %08x\n", m->BeACopId,
           fb(m->TimeSinceLastSpeech), fb(m->MaxSpeechGapTime),
           fb(m->fSupervisorTimer), (uint32_t)m->SpeechFillerCookie);
    printf("M pursuable ");
    hexwords(m->fPursuableTimer, 8);
    printf("\nM sttimer ");
    hexwords(m->fSpeedTrapSpawnTimer, 8);
    printf("\nM dmg ");
    hexwords(m->fCarDamage, 14);
    printf("\nM diff %d time %08x said %d n10488 %d choppers %d arrests %d "
           "n10500 %d xdim %08x ydim %08x vptr %08x\n", m->nDifficultyLevel,
           fb(m->fBeACopTime), m->bBeACopAlreadySaidLookOutForSpeeders,
           m->New10488, m->nBeACopNumChopperAttacks,
           m->nBeACopNumArrestsMade, m->New10500, fb(m->fMaxCopCarXdim),
           fb(m->fMaxCopCarYdim), m->vptr);
    printf("M pools %s", sym(PursuitSlotPool));
    printf(" %s", sym(CopSlotPool));
    printf(" %s\n", sym(SpikeStripSlotPool));
}

// ---------------------------------------------------------- the ops

static int32_t *rp_field(const char *f)
{
    RaceParameters *r = &TheRaceParameters;

    if (!strcmp(f, "TrackDirection"))  return &r->TrackDirection;
    if (!strcmp(f, "AIDemoMode"))      return &r->AIDemoMode;
    if (!strcmp(f, "TimeTrialTime"))
        return (int32_t *)(void *)&r->TimeTrialTime.PackedTime;
    if (!strcmp(f, "Point2Point"))     return &r->Point2Point;
    if (!strcmp(f, "NumLaps"))         return &r->NumLapsInRace;
    if (!strcmp(f, "nMaxCops"))        return &r->nMaxCops;
    if (!strcmp(f, "bRoadBlocks"))     return &r->bRoadBlocks;
    if (!strcmp(f, "BeACop"))          return &r->BeACop;
    if (!strcmp(f, "BeACopRB"))        return &r->nNumBeACopRoadBlocks;
    if (!strcmp(f, "BeACopChoppers"))  return &r->nNumBeACopChoppers;
    if (!strcmp(f, "CopStrength"))     return &r->CopStrength;
    if (!strcmp(f, "NumPlayerCars"))   return &r->NumPlayerCars;
    if (!strcmp(f, "Tickets"))         return &r->nNumTicketsBeforeArrest;
    fprintf(stderr, "no rp field %s\n", f);
    exit(2);
}

static uint32_t num(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static uint32_t hex(const char *s)
{
    return (uint32_t)strtoul(s, NULL, 16);
}

static void put_chunk(int k, const char *hexs)
{
    size_t   n = strlen(hexs) / 2, i;
    uint8_t *p = aligned_alloc(16, (n + 31) & ~(size_t)15);

    for (i = 0; i < n; i++) {
        unsigned v;

        sscanf(hexs + 2 * i, "%2x", &v);
        p[i] = (uint8_t)v;
    }
    chunks[k].base = p;
    chunks[k].size = n;
}

// The manager's fields Think reads and writes, by name.
static void *mfield(tCopManager *m, const char *f)
{
    int k;

    if (!strcmp(f, "tsls"))     return &m->TimeSinceLastSpeech;
    if (!strcmp(f, "gap"))      return &m->MaxSpeechGapTime;
    if (!strcmp(f, "super"))    return &m->fSupervisorTimer;
    if (!strcmp(f, "aicops"))   return &m->nNumAICops;
    if (!strcmp(f, "diff"))     return &m->nDifficultyLevel;
    if (sscanf(f, "sttimer%d", &k) == 1)
        return &m->fSpeedTrapSpawnTimer[k];
    if (sscanf(f, "pursuable%d", &k) == 1)
        return &m->fPursuableTimer[k];
    if (sscanf(f, "pulltimer%d", &k) == 1)
        return &m->CarPullovers[k].fHoldTimer;
    if (sscanf(f, "pullactive%d", &k) == 1)
        return &m->CarPullovers[k].bActive;
    if (sscanf(f, "pullnis%d", &k) == 1)
        return &m->CarPullovers[k].bPlayNIS;
    fprintf(stderr, "no manager field %s\n", f);
    exit(2);
}

static int think_op(tCopManager *m, char **a)
{
    const char *o = a[0];

    if (!strcmp(o, "t")) {
        const char *g = a[1];
        uint32_t    v = num(a[2]);

        if (!strcmp(g, "wte"))
            WorldTimeElapsed = bf(v);
        else if (!strcmp(g, "racetime"))
            the_race.RaceTime.PackedTime = v;
        else if (!strcmp(g, "rc"))
            the_rc.CurrentRCState = (RCState)v;
        else if (!strcmp(g, "speech"))
            speech_state = (int32_t)v;
        else if (!strcmp(g, "cloaked"))
            the_graph.bHasCloakedEdge = (int32_t)v;
        else if (!strcmp(g, "copcarpos"))
            world_token.CopCarPos = (int32_t)v;
        else if (!strcmp(g, "dist"))
            dist_bits = v;
        else if (!strcmp(g, "seed"))
            bDefaultSeed = v;
        else if (!strcmp(g, "mgr")) {
            // Hides the manager from GlobalCopThink, and brings it back.
            static tCopManager *hidden;

            if (v == 0 && pCopManager != NULL) {
                hidden = pCopManager;
                pCopManager = NULL;
            } else if (v != 0 && pCopManager == NULL) {
                pCopManager = hidden;
            }
        } else
            return 0;
    } else if (!strcmp(o, "wcar")) {
        world_token.CarTable[atoi(a[1])] = &cars[atoi(a[2])];
    } else if (!strcmp(o, "pst")) {
        tPursuit *p = pursuits[atoi(a[1])];

        p->PursuitState = (ePursuitState)num(a[2]);
        p->fPursuitStateTimer = bf(num(a[3]));
        p->fRoadBlockSpawnTimer = bf(num(a[4]));
        p->ChopperState = (eChopperState)num(a[5]);
    } else if (!strcmp(o, "prb")) {
        int k = atoi(a[2]);

        pursuits[atoi(a[1])]->pRoadBlock = k >= 0 ? &m->RoadBlocks[k] : NULL;
    } else if (!strcmp(o, "rbpos")) {
        tRoadBlock *r = &m->RoadBlocks[atoi(a[1])];

        r->v2Position.x = bf(num(a[2]));
        r->v2Position.y = bf(num(a[3]));
    } else if (!strcmp(o, "blown")) {
        cars[atoi(a[1])].BlownTireBits = (uint8_t)num(a[2]);
    } else if (!strcmp(o, "player")) {
        cars[atoi(a[1])].pPlayer =
            num(a[2]) ? (Player *)(void *)player_token : NULL;
    } else if (!strcmp(o, "update")) {
        updates[atoi(a[1])] = (int32_t)num(a[2]);
    } else if (!strcmp(o, "cansuper")) {
        cansupers[atoi(a[1])] = (int32_t)num(a[2]);
    } else if (!strcmp(o, "mset")) {
        uint32_t v = num(a[2]);

        memcpy(mfield(m, a[1]), &v, 4);
    } else if (!strcmp(o, "cset")) {
        m->Cops[atoi(a[1])]->DesiredLogicState = (eLogicState)num(a[2]);
    } else if (!strcmp(o, "copstates")) {
        int k;

        printf("copstates");
        for (k = 0; k < 7; k++)
            if (m->Cops[k] != NULL)
                printf(" %d", m->Cops[k]->DesiredLogicState);
            else
                printf(" -");
        printf("\n");
    } else if (!strcmp(o, "mstate")) {
        int k;

        printf("mstate %08x %08x %08x %08x pur", fb(m->TimeSinceLastSpeech),
               fb(m->MaxSpeechGapTime), fb(m->fSupervisorTimer),
               m->SpeechFillerCookie);
        for (k = 0; k < 8; k++)
            printf(" %08x", fb(m->fPursuableTimer[k]));
        printf(" hold");
        for (k = 0; k < 8; k++)
            printf(" %08x", fb(m->CarPullovers[k].fHoldTimer));
        printf("\n");
    } else if (!strcmp(o, "plist")) {
        tPursuitNode *n;

        printf("plist");
        for (n = m->PursuitList.Next; n != &m->PursuitList; n = n->Next)
            printf(" %s", sym(n));
        printf("\n");
    } else if (!strcmp(o, "think")) {
        copmanager_think(m);
        printf("think\n");
    } else if (!strcmp(o, "global")) {
        copmgr_global_cop_think(bf(num(a[1])));
        printf("global\n");
    } else if (!strcmp(o, "tbs")) {
        copmanager_time_based_speech(m);
        printf("tbs\n");
    } else if (!strcmp(o, "supervisor")) {
        copmanager_supervisor_activate(m);
        printf("supervisor\n");
    } else if (!strcmp(o, "pm")) {
        copmanager_pursuit_management(m);
        printf("pm\n");
    } else if (!strcmp(o, "fpp")) {
        tPursuit *p = copmanager_find_player_pursuit(m);

        printf("fpp -> %s\n", sym(p));
    } else if (!strcmp(o, "gapnext")) {
        copmanager_set_next_speech_filler_gap(m);
        printf("gapnext\n");
    } else if (!strcmp(o, "pulls")) {
        copmanager_monitor_pullovers(m);
        printf("pulls\n");
    } else if (!strcmp(o, "reclaim")) {
        copmanager_reclaim_patrollers(m);
        printf("reclaim\n");
    } else if (!strcmp(o, "about")) {
        int u = atoi(a[1]);

        printf("about U%d -> %d\n", u,
               tpursuit_about_to_say_something(pursuits[u]));
    } else if (!strcmp(o, "notchasing")) {
        int u = atoi(a[1]);

        printf("notchasing U%d -> %d\n", u,
               tpursuit_not_in_chasing_state(pursuits[u]));
    } else {
        return 0;
    }
    return 1;
}

static void op(char **a, int na)
{
    const char  *o = a[0];
    tCopManager *m = pCopManager;

    (void)na;
    if (!strcmp(o, "raw")) {
        put_chunk(atoi(a[1]), a[2]);
    } else if (!strcmp(o, "load") || !strcmp(o, "unload")) {
        int k = atoi(a[1]);
        int r = !strcmp(o, "load") ? copmgr_loader(chunks[k].base)
                                   : copmgr_unloader(chunks[k].base);

        printf("%s c%d -> %d\n", o, k, r);
        statics();
    } else if (!strcmp(o, "static")) {
        SpeedTrapData = NULL;
        RoadblockData = NULL;
        LandmarkData = NULL;
        statics();
    } else if (!strcmp(o, "rp")) {
        *rp_field(a[1]) = (int32_t)num(a[2]);
    } else if (!strcmp(o, "g")) {
        if (!strcmp(a[1], "world"))
            pCurrentWorld = num(a[2]) ? &world_token : NULL;
        else if (!strcmp(a[1], "skipfe"))
            skipfe = (int32_t)num(a[2]);
        else if (!strcmp(a[1], "skipfetime"))
            SkipFETimeUntilCopsAppear = bf(num(a[2]));
        else if (!strcmp(a[1], "tracklen"))
            TheTrackPathManager.TrackLength = bf(num(a[2]));
    } else if (!strcmp(o, "npts")) {
        npts = atoi(a[1]);
    } else if (!strcmp(o, "pt")) {
        TrackRoutePoint *p = &pts[atoi(a[1])];

        p->Position.x = bf(hex(a[2]));
        p->Position.y = bf(hex(a[3]));
        p->Direction.x = bf(hex(a[4]));
        p->Direction.y = bf(hex(a[5]));
        p->LeftWidth = bf(hex(a[6]));
        p->RightWidth = bf(hex(a[7]));
    } else if (!strcmp(o, "topo")) {
        topo_force = atoi(a[1]);
    } else if (!strcmp(o, "polyhit")) {
        polyhit = atoi(a[1]);
    } else if (!strcmp(o, "initcops")) {
        copmgr_init_cops();
        printf("initcops -> %s\n", sym(pCopManager));
    } else if (!strcmp(o, "dump")) {
        dump();
    } else if (!strcmp(o, "cleanup")) {
        copmgr_cleanup_cops();
        printf("cleanup -> %s\n", sym(pCopManager));
    } else if (!strcmp(o, "initrb")) {
        copmanager_init_road_block_structures(m);
        printf("initrb\n");
    } else if (!strcmp(o, "initst")) {
        copmanager_init_speed_trap_structures(m);
        printf("initst\n");
    } else if (!strcmp(o, "rb")) {
        int32_t     i = (int32_t)num(a[1]);
        tRoadBlock *r = copmanager_get_road_block_from_loaded_data_index(m,
                                                                         i);

        if (r == NULL)
            printf("rb %d -> none\n", i);
        else
            printf("rb %d -> %d\n", i, (int)(r - m->RoadBlocks));
    } else if (!strcmp(o, "st")) {
        int32_t     i = (int32_t)num(a[1]);
        tSpeedTrap *t = copmanager_get_speed_trap_from_loaded_data_index(m,
                                                                         i);

        if (t == NULL)
            printf("st %d -> none\n", i);
        else
            printf("st %d -> %d\n", i, (int)(t - m->SpeedTraps));
    } else if (!strcmp(o, "base")) {
        printf("base -> %08x\n",
               fb(copmanager_get_base_speed_trap_spawn_time(m)));
    } else if (!strcmp(o, "current")) {
        printf("current -> %08x\n", copmanager_get_current_cop_speaker(m));
    } else if (!strcmp(o, "reserve")) {
        printf("reserve -> %08x\n", copmanager_reserve_cop_speaker(m));
    } else if (!strcmp(o, "release")) {
        copmanager_release_cop_speaker(m, num(a[1]));
        printf("release %08x\n", num(a[1]));
    } else if (!strcmp(o, "next")) {
        copmanager_next_cop_speaker(m);
        printf("next\n");
    } else if (!strcmp(o, "landmark")) {
        bVector2  pos;
        Landmark *l;

        pos.x = bf(num(a[1]));
        pos.y = bf(num(a[2]));
        l = copmgr_find_landmark(&pos);
        if (l == NULL)
            printf("landmark %08x %08x -> none\n", num(a[1]), num(a[2]));
        else
            printf("landmark %08x %08x -> L%d\n", num(a[1]), num(a[2]),
                   (int)(l - LandmarkData->LandmarkArray));
    } else if (!strcmp(o, "freeid")) {
        printf("freeid -> %d\n", copmanager_find_free_pursuit_id(m));
    } else if (!strcmp(o, "pursuit")) {
        int       u = atoi(a[1]), pid = atoi(a[2]);
        tPursuit *p = malloc(sizeof *p);

        memset(p, 0xcd, sizeof *p);
        name(p, "U%d", u);
        pursuits[u] = p;
        link_tail(&m->PursuitList, &p->Node);
        p->nPursuitId = (int8_t)pid;
        p->vptr = VT_PURSUIT;
        m->PursuitsById[pid] = p;
    } else if (!strcmp(o, "new76")) {
        int u = atoi(a[1]);

        m->New76 = u >= 0 ? pursuits[u] : NULL;
    } else if (!strcmp(o, "delpursuit")) {
        int u = atoi(a[1]);

        copmanager_delete_pursuit(m, u >= 0 ? pursuits[u] : NULL);
        printf("delpursuit %d\n", u);
    } else if (!strcmp(o, "cop")) {
        int   k = atoi(a[1]);
        tCop *c = malloc(sizeof(tAICop));

        memset(c, 0xcd, sizeof(tAICop));
        name(c, "C%d", k);
        c->vptr = !strcmp(a[2], "ai") ? VT_AICOP : VT_PLAYERCOP;
        m->Cops[k] = c;
    } else if (!strcmp(o, "car")) {
        Car *c = &cars[atoi(a[1])];

        c->CarIndex = (int16_t)atoi(a[2]);
        c->TheControlMode = (ControlMode)atoi(a[3]);
        c->State.Position.x = bf(num(a[4]));
        c->State.Position.y = bf(num(a[5]));
    } else if (!strcmp(o, "copcar")) {
        int j = atoi(a[2]);

        m->Cops[atoi(a[1])]->pMyCar = j >= 0 ? &cars[j] : NULL;
    } else if (!strcmp(o, "copp")) {
        int u = atoi(a[2]);

        m->Cops[atoi(a[1])]->pMyPursuit = u >= 0 ? pursuits[u] : NULL;
    } else if (!strcmp(o, "copt")) {
        ((tAICop *)(void *)m->Cops[atoi(a[1])])->New32 = bf(num(a[2]));
    } else if (!strcmp(o, "copn")) {
        m->nNumCops = (int32_t)num(a[1]);
    } else if (!strcmp(o, "copidx")) {
        m->nPlayerCopIndex = (int32_t)num(a[1]);
    } else if (!strcmp(o, "chase")) {
        pursuits[atoi(a[1])]->pChasedCar = &cars[atoi(a[2])];
    } else if (!strcmp(o, "colls")) {
        int i;

        ncoll = atoi(a[1]);
        for (i = 2; i < na; i++)
            colls[i - 2] = (int32_t)num(a[i]);
    } else if (!strcmp(o, "impact")) {
        int k = atoi(a[1]);

        bodies[k].Dynamic.Body.NumCollisions = (int8_t)ncoll;
        // carcollisionbody_add_damage's test, then its seam.
        if (pCopManager != NULL)
            copmgr_car_impact(pCopManager, &bodies[k], bf(num(a[2])));
        printf("impact A%d %08x\n", k, num(a[2]));
    } else if (!strcmp(o, "dmg")) {
        printf("dmg ");
        hexwords(m->fCarDamage, 14);
        printf("\n");
    } else if (!strcmp(o, "dat")) {
        cars[atoi(a[1])].TheTrackPathCoordinate.DistanceAroundTrack =
            bf(num(a[2]));
    } else if (!strcmp(o, "front")) {
        infront[atoi(a[1])] = (int32_t)num(a[2]);
    } else if (!strcmp(o, "cmp")) {
        // An answer for a distance's bits, in place of any it had.
        int i;

        for (i = 0; i < ncmp && cmp_key[i] != num(a[1]); i++)
            ;
        if (i == ncmp)
            ncmp++;
        cmp_key[i] = num(a[1]);
        cmp_ans[i] = num(a[2]);
    } else if (!strcmp(o, "radar")) {
        int     k = atoi(a[1]);
        int32_t flag = (int32_t)num(a[2]);
        float   r = copmanager_get_radar_detector_intensity(m, &cars[k],
                                                            &flag);

        printf("radar A%d -> %08x flag %d\n", k, fb(r), flag);
    } else if (!strcmp(o, "spike")) {
        int          k = atoi(a[1]);
        tSpikeStrip *s = malloc(sizeof *s);

        memset(s, 0xcd, sizeof *s);
        name(s, "S%d", k);
        link_tail(&m->SpikeStripList, &s->Node);
        s->vptr = VT_SPIKE;
    } else if (think_op(m, a)) {
        // Think's (12f).
    } else if (spawn_op(m, a)) {
        // SpawnSpeedTraps's (12j-1).
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 20];
    FILE       *f;
    int         i;

    if (argc != 2) {
        fprintf(stderr, "usage: copmanager_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    for (i = 0; i < 16; i++)
        name(&pts[i], "P%d", i);
    for (i = 0; i < 3; i++)
        name(&routes[i], "R%d", i);
    name(&world_token, "W%d", 0);
    name(&the_race, "RACE", 0);
    for (i = 0; i < RACE_MAX_RACING_CARS; i++)
        name(&the_race.RacingCarTable[i], "RC%d", i);
    pCurrentRace = &the_race;
    pRaceCoordinator = &the_rc;
    TheTrackGraph = &the_graph;
    gPursuitUpdateFn = pursuit_update;
    gPursuitCanSupervisorInitiateFn = can_super;
    gPursuitSuperInitiatesFn = super_initiates;
    gSayFillerSpeechFn = filler;
    gCopSpeechPlaybackStateFn = speech_playback;
    gCopManagerSpawnSpeedTrapsFn = spawn_speed_traps;
    gCopManagerMonitorSpikeBeltsFn = spike_belts;
    gCopManagerEndPulloverFn = end_pullover;
    gCopManagerBeACopThinkFn = beacop_think;
    gCopSpeechAllocateVoicesFn = voices;
    gCopSpeechFlushQueueFn = flush;
    vt_install(VT_PURSUIT, pursuit_vt, 2);
    vt_install(VT_AICOP, aicop_vt, 4);
    vt_install(VT_PLAYERCOP, playercop_vt, 4);
    for (i = 0; i < NCARS; i++) {
        bodies[i].pCar = &cars[i];
        name(&cars[i], "A%d", i);
    }
    gAICopDisableMyCarFn = disable_my_car;
    vt_install(VT_SPIKE, spike_vt, 2);
    copmgr_install_vtables();
    while (fgets(line, sizeof line, f) != NULL) {
        char *a[16], *s = line;
        int   na = 0;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        while (na < 16) {
            a[na++] = s;
            s = strchr(s, '|');
            if (s == NULL)
                break;
            *s++ = 0;
        }
        op(a, na);
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
