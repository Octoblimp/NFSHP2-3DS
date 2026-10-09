// Harness for tools/pursuit_check.py: runs the checker's script on
// pursuit.c -- tPursuit's constructor and destructor, its state switch and
// the calls under it, RequestPursuit and the supervisor call -- with
// barricade.c and copmgr.c's spike strips, and prints what the model
// prints for the retail image. See the checker's docstring.
//
//     pursuit_test script.txt > out.txt

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airoute.h"
#include "barricade.h"
#include "bmath.h"
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinfo.h"
#include "cartypeinfo.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "cop.h"
#include "copmgr.h"
#include "drivetarget.h"
#include "hudscore.h"
#include "pursuit.h"
#include "race.h"
#include "racecoord.h"
#include "realdriver.h"
#include "table.h"
#include "topology.h"
#include "trackgraph.h"
#include "trackpath.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

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

#define MAX_NAMES 4096

static struct {
    const void *p;
    char        name[24];
} names[MAX_NAMES];
static int nnames;

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

static const char *sym(const void *p)
{
    uintptr_t u = (uintptr_t)p;
    int       i;

    if (p == NULL)
        return "0";
    if (u == (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        return "cd";
    for (i = nnames - 1; i >= 0; i--)
        if (names[i].p == p)
            return names[i].name;
    return "?";
}

// ------------------------------------------------ what pursuit.c reaches

RaceParameters   TheRaceParameters;
TrackPathManager TheTrackPathManager;
World           *pCurrentWorld;
float            SkipFETimeUntilCopsAppear;
float            WorldTimeElapsed;
Race            *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
tTrackGraph     *TheTrackGraph;

#define NCARS     6
#define NCOPS     8
#define NRBS      4
#define NSTRIPS   6
#define NCHOPPERS 2
#define NBODIES   16
#define BODY_SIZE 1136
#define MAX_PURSUITS 1024
#define MAX_BARRICADES 1024

static World            the_world;
static RaceCoordinator  the_rc;
static tCopManager      the_mgr;
static Car              cars[NCARS];
static CarTypeInfo      ctis[NCARS];
static RideInfo         rides[NCARS];
static RacingCar        rcars[NCARS];
static uint8_t          players[2][16];
static tCop             cops[NCOPS];
static tRoadBlock       rbs[NRBS];
static tSpikeStrip      strips[NSTRIPS];
static uint8_t          choppers[NCHOPPERS][1024];
static uint8_t          bodymem[NBODIES][BODY_SIZE];
static uint8_t          pool_token[16];
static uint8_t          tabtok[8][16];
static uint32_t         acc_cut[8], acc_low[8];
static tPursuit        *pursuits[MAX_PURSUITS];
static int              npursuits;
static BarricadeManager *barricades[MAX_BARRICADES];
static int              nbarricades;

static void unreached(const char *f)
{
    fprintf(stderr, "pursuit_test: %s reached\n", f);
    exit(3);
}

// ---- the allocators

void *bSlotOMalloc(BSlotPool *pool)
{
    tPursuit *p = malloc(sizeof *p);

    if (npursuits == MAX_PURSUITS)
        unreached("too many pursuits");
    memset(p, 0xcd, sizeof *p);
    name(p, "U%d", npursuits);
    name(&p->FarDriveTarget, "U%d.far", npursuits);
    name(&p->NearDriveTarget, "U%d.near", npursuits);
    printf("  slotalloc %s -> U%d\n", sym(pool), npursuits);
    pursuits[npursuits++] = p;
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  slotfree %s %s\n", sym(pool), sym(slot));
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size);

    if (nbarricades == MAX_BARRICADES)
        unreached("too many blocks");
    memset(p, 0xcd, (size_t)size);
    name(p, "B%d", nbarricades);
    printf("  malloc %d %s %d %d -> B%d\n", size, nm, flags, pool,
           nbarricades);
    barricades[nbarricades++] = (BarricadeManager *)(void *)p;
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", sym(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *nm,
                        int memoryPool)
{
    (void)slotSize; (void)numSlots; (void)nm; (void)memoryPool;
    unreached("bNewSlotPool");
    return NULL;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    (void)pool;
    unreached("bDeleteSlotPool");
}

// ---- the drive targets, the tables, the score

DriveTarget *drivetarget_init(DriveTarget *t)
{
    printf("  dt init %s\n", sym(t));
    return t;
}

void drivetarget_destroy(DriveTarget *t)
{
    printf("  dt destroy %s\n", sym(t));
}

Table *get_acceleration_table(int32_t type)
{
    printf("  acctab %d\n", type);
    return (Table *)(void *)tabtok[type & 7];
}

// Huge below the type's cut, its low value from there.
float table_get_value(const Table *t, float arg)
{
    int      k = (int)((const uint8_t (*)[16])(const void *)t - tabtok);
    uint32_t r = fb(arg) >= acc_cut[k] ? acc_low[k] : 0x7f000000u;

    printf("  accel T%d %08x -> %08x\n", k, fb(arg), r);
    return bf(r);
}

void player_start_score(struct Player *p, int32_t scoring)
{
    printf("  score %s %d\n", sym(p), scoring);
}

// ---- the cops

void taicop_return_to_patrol(tAICop *c)
{
    printf("  patrol %s\n", sym(c));
}

void tcop_set_pursuit(tCop *c, tPursuit *p)
{
    printf("  setpursuit %s %s\n", sym(c), sym(p));
    c->pMyPursuit = p;
}

void tcop_set_desired_logic_state(tCop *c, eLogicState s)
{
    printf("  desired %s %d\n", sym(c), (int)s);
    c->DesiredLogicState = s;
}

static int32_t ai_controlled(void *self)
{
    (void)self;
    return 1;
}

static int32_t player_controlled(void *self)
{
    (void)self;
    return 0;
}

static const VtEntry aicop_vt[] = {
    { 0, 0, NULL }, { 0, 0, NULL },
    { 0, 0, (VtFn)ai_controlled },          // 16  0x00230d60
};

static const VtEntry playercop_vt[] = {
    { 0, 0, NULL }, { 0, 0, NULL },
    { 0, 0, (VtFn)player_controlled },      // 16  0x00230d98
};

// ---- the bodies

CollisionBody *collisionbody_find(int32_t i)
{
    CollisionBody *b = NULL;

    if (i >= 0 && i < NBODIES && i % 3 != 2)
        b = (CollisionBody *)(void *)bodymem[i];
    printf("  findbody %d -> %s\n", i, sym(b));
    return b;
}

static void mark_fading(CollisionBody *b)
{
    ((uint8_t *)b)[1123] = 1;
}

static void delete_barrel(int16_t id)
{
    printf("  barrel delete %d\n", id);
}

// ---- the seams

static void start_speech(tPursuit *p)
{
    printf("  speech start %s\n", sym(p));
}

static void join_speech(tPursuit *p)
{
    printf("  speech join %s\n", sym(p));
}

static void backoff_speech(tPursuit *p)
{
    printf("  speech backoff %s\n", sym(p));
}

static void crash_tow(uint32_t was, uint32_t now)
{
    printf("  speech tow %08x %08x\n", was, now);
}

static void crash(uint32_t was, uint32_t now)
{
    printf("  speech crash %08x %08x\n", was, now);
}

static void flat_tire(uint32_t was, uint32_t now)
{
    printf("  speech flat %08x %08x\n", was, now);
}

static void super_request(uint32_t s)
{
    printf("  speech super %08x\n", s);
}

static void load_next_nis(struct Player *pl, struct Car *chased,
                          struct Car *cop, int32_t tickets)
{
    printf("  nis %s %s %s %d\n", sym(pl), sym(chased), sym(cop),
           (int)tickets);
}

static int32_t chopper_960(struct Chopper *c)
{
    int32_t v;

    memcpy(&v, (uint8_t *)c + 960, 4);
    return v;
}

static void follow(struct Chopper *c, struct Car *car)
{
    printf("  follow %s %s\n", sym(c), sym(car));
}

static void poof(tSpikeStrip *s)
{
    printf("  poof %s\n", sym(s));
}

// ---- copmgr.c's, which the script never reaches

int32_t config_skip_fe(void)
{
    unreached("config_skip_fe");
    return 0;
}

int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    (void)info; (void)pos; (void)which; (void)flags; (void)distanceAround;
    unreached("ai_get_nearest_route_point");
    return 0;
}

void topology_init(TopologyCoordinate *tc)
{
    (void)tc;
    unreached("topology_init");
}

int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy)
{
    (void)tc; (void)xy;
    unreached("topology_has_topology");
    return 0;
}

void topology_destroy(TopologyCoordinate *tc)
{
    (void)tc;
    unreached("topology_destroy");
}

void trackpath_coord_init_at(TrackPathCoordinate *c, const bVector2 *pos)
{
    (void)c; (void)pos;
    unreached("trackpath_coord_init_at");
}

void trpoint_get_position2(const TrackRoutePoint *p, bVector2 *o, float d,
                           float l)
{
    (void)p; (void)o; (void)d; (void)l;
    unreached("trpoint_get_position2");
}

float world_random_f(World *w, float f)
{
    (void)w; (void)f;
    unreached("world_random_f");
    return 0.0f;
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    (void)w; (void)p;
    unreached("world_get_distance_to_closest_player_2d");
    return 0.0f;
}

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    (void)g;
    unreached("trackgraph_uncloak_all_edges");
}

int32_t is_point_in_poly(const bVector2 *p, const bVector2 *poly, int32_t n)
{
    (void)p; (void)poly; (void)n;
    unreached("is_point_in_poly");
    return 0;
}

struct Collision *collisionbody_get_collision(CollisionBody *b, int32_t i)
{
    (void)b; (void)i;
    unreached("collisionbody_get_collision");
    return NULL;
}

int32_t collision_is_two_car_collision(Collision *c)
{
    (void)c;
    unreached("collision_is_two_car_collision");
    return 0;
}

void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    (void)c; (void)pos; (void)speed; (void)angle;
    unreached("car_reset_to_position");
}

void realdriver_force_ebrake_stop(RealDriver *d, int32_t on)
{
    (void)d; (void)on;
    unreached("realdriver_force_ebrake_stop");
}

tAICop *taicop_construct(tAICop *c, struct DriverInfo *info, int32_t n)
{
    (void)c; (void)info; (void)n;
    unreached("taicop_construct");
    return NULL;
}

void *taicop_new(void)
{
    unreached("taicop_new");
    return NULL;
}

tPlayerCop *tplayercop_construct(tPlayerCop *c, struct Car *car, int32_t n)
{
    (void)c; (void)car; (void)n;
    unreached("tplayercop_construct");
    return NULL;
}

// ------------------------------------------------------------ the dumps

static void hexbytes(const void *p, int n)
{
    const uint8_t *b = p;
    int            i;

    for (i = 0; i < n; i++)
        printf("%02x", b[i]);
}

static int pursuit_index(const tPursuit *p)
{
    int i;

    for (i = 0; i < npursuits; i++)
        if (pursuits[i] == p)
            return i;
    return -1;
}

static void dump_barricades(const BarricadeManager *b)
{
    int i;

    printf("%s ids", sym(b));
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++)
        printf(" %d", b->nBarrel[i]);
    printf(" t");
    for (i = 0; i < BARRICADE_MAX_BARRELS; i++)
        printf(" %08x", fb(b->fFadeTimer[i]));
    printf(" vptr %08x\n", b->vptr);
}

static void dump(int u)
{
    const tPursuit        *p = pursuits[u];
    const tPursuitHistory *h = &p->History;
    const tRoadBlockStateMachine *s = &p->RoadBlockStateMachine;
    int                    i;

    printf("U%d node %s %s max %d %d chased %s rb %s chopper %s cops %s %s"
           " pad ", u, sym(p->Node.Next), sym(p->Node.Prev),
           (int)p->nMaxChaseCops, (int)p->nMaxRoadBlockCops,
           sym(p->pChasedCar), sym(p->pRoadBlock), sym(p->pChopper),
           sym(p->Cops[0]), sym(p->Cops[1]));
    hexbytes(p->Pad36, 12);
    printf("\nU%d hist %d v", u, (int)h->nCount);
    for (i = 0; i < 30; i++)
        printf(" %08x %08x", fb(h->v2Velocity[i].x),
               fb(h->v2Velocity[i].y));
    printf(" t");
    for (i = 0; i < 30; i++)
        printf(" %08x", fb(h->fTime[i]));
    printf(" vptr %08x\n", h->vptr);
    printf("U%d bar %s ncops %d id %d pad ", u, sym(p->pBarricades),
           (int)p->nNumCops, (int)p->nPursuitId);
    hexbytes(p->Pad1481, 3);
    printf(" state %d sub %d hud %d spk %08x %08x lm %d joined %d hit %d"
           " backup %d\n", (int)p->PursuitState, (int)p->PursuitSubState,
           (int)p->nHUDPursuitLevel, p->PrimaryCopSpeaker,
           p->SecondaryCopSpeaker, (int)p->CurrentLandmark,
           (int)p->bAlreadyJoined, (int)p->bAlreadyBeenHit,
           (int)p->bAlreadyCalledForBackup);
    printf("U%d f %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n", u,
           fb(p->fCatchCarTimer), fb(p->fPursuitStateTimer),
           fb(p->fRoadBlockDisbandTimer), fb(p->fRoadBlockSpawnTimer),
           fb(p->fChopperAttackTimer), fb(p->fChopperNextAttackTime),
           fb(p->fChasedCarTopSpeed), fb(p->fChaseDirection),
           fb(p->fChaseDirectionTimer), fb(p->New1556));
    printf("U%d rbsm %d %08x %08x %d %s chst %d rbc %d flags %08x vptr %08x"
           " pad ", u, (int)s->State, fb(s->fStateTimer), s->SpeechFlags,
           (int)s->nRoadBlockCount, sym(s->pPursuit), (int)p->ChopperState,
           (int)p->nRoadblockCount, p->BehaviourFlags, p->vptr);
    hexbytes(p->Pad1596, 4);
    printf("\n");
}

static void dump_all(const tPursuit *p)
{
    dump(pursuit_index(p));
    if (p->pBarricades != NULL
        && (uintptr_t)p->pBarricades != (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        dump_barricades(p->pBarricades);
}

static void mdump(void)
{
    const tCopManager *m = pCopManager;
    int                i;

    printf("M plist %s %s byid", sym(m->PursuitList.Next),
           sym(m->PursuitList.Prev));
    for (i = 0; i < COPMANAGER_MAX_PURSUITS; i++)
        printf(" %s", sym(m->PursuitsById[i]));
    printf(" spk %08x %08x %08x %08x %d %d %d beacop %08x super %08x"
           " busy %d spawn %08x\n", m->CopSpeakers.Data[0],
           m->CopSpeakers.Data[1], m->CopSpeakers.Data[2],
           m->CopSpeakers.Data[3], (int)m->CopSpeakers.Head,
           (int)m->CopSpeakers.Tail, (int)m->CopSpeakers.Full,
           m->BeACopId, fb(m->fSupervisorTimer), (int)m->bChopperBusy,
           fb(fRoadBlockSpawnTime));
    printf("M timers");
    for (i = 0; i < 8; i++)
        printf(" %08x", fb(m->fPursuableTimer[i]));
    printf(" st");
    for (i = 0; i < 8; i++)
        printf(" %08x", fb(m->fSpeedTrapSpawnTimer[i]));
    printf(" seed %08x\n", bDefaultSeed);
}

static void cdump(void)
{
    int i;

    printf("C");
    for (i = 0; i < NCOPS; i++)
        printf(" %s/%d", sym(cops[i].pMyPursuit),
               (int)cops[i].DesiredLogicState);
    printf(" rb");
    for (i = 0; i < NRBS; i++)
        printf(" %s/%s", sym(rbs[i].cops[0]), sym(rbs[i].cops[1]));
    printf("\n");
}

static void fades(void)
{
    int i;

    printf("fades");
    for (i = 0; i < NBODIES; i++)
        if (bodymem[i][1123] != 0) {
            printf(" %d", i);
            bodymem[i][1123] = 0;
        }
    printf("\n");
}

// --------------------------------------------------------------- the ops

static uint32_t num(const char *s)
{
    return (uint32_t)strtoll(s, NULL, 0);
}

// U<n>'s number, or L<k>, the k-th on the manager's list.
static tPursuit *pursuit_tok(const char *s)
{
    if (s[0] == 'L') {
        const tPursuitNode *l = &the_mgr.PursuitList;
        const tPursuitNode *n = l->Next;
        int                 k = atoi(s + 1);

        while (n != l && k-- > 0)
            n = n->Next;
        return n == l ? NULL : (tPursuit *)(void *)n;
    } else {
        char   *end;
        int32_t u = (int32_t)strtol(s, &end, 0);

        if (end == s || *end != 0)
            return NULL;
        return u >= 0 && u < npursuits ? pursuits[u] : NULL;
    }
}

static tCop *cop_arg(const char *s)
{
    int k = (int)(int32_t)num(s);

    return k < 0 ? NULL : &cops[k];
}

static Car *car_arg(const char *s)
{
    int k = (int)(int32_t)num(s);

    return k < 0 ? NULL : &cars[k];
}

static void reset(void)
{
    tCopManager *m = &the_mgr;

    memset(m, 0, sizeof *m);
    m->PursuitList.Next = m->PursuitList.Prev = &m->PursuitList;
    m->SpikeStripList.Next = m->SpikeStripList.Prev = &m->SpikeStripList;
    m->nPlayerCopIndex = -1;
    memset(cops, 0, sizeof cops);
    memset(rbs, 0, sizeof rbs);
    memset(bodymem, 0, sizeof bodymem);
}

static void mset(const char *f, uint32_t v)
{
    tCopManager *m = &the_mgr;
    int          k = f[strlen(f) - 1] - '0';

    if (strcmp(f, "diff") == 0)
        m->nDifficultyLevel = (int32_t)v;
    else if (strcmp(f, "beacop") == 0)
        m->BeACopId = v;
    else if (strcmp(f, "super") == 0)
        m->fSupervisorTimer = bf(v);
    else if (strcmp(f, "busy") == 0)
        m->bChopperBusy = (int32_t)v;
    else if (strcmp(f, "pcidx") == 0)
        m->nPlayerCopIndex = (int32_t)v;
    else if (strcmp(f, "head") == 0)
        m->CopSpeakers.Head = (int32_t)v;
    else if (strcmp(f, "tail") == 0)
        m->CopSpeakers.Tail = (int32_t)v;
    else if (strcmp(f, "full") == 0)
        m->CopSpeakers.Full = (int32_t)v;
    else if (strncmp(f, "spk", 3) == 0)
        m->CopSpeakers.Data[k] = v;
    else if (strncmp(f, "pur", 3) == 0)
        m->fPursuableTimer[k] = bf(v);
    else if (strncmp(f, "stt", 3) == 0)
        m->fSpeedTrapSpawnTimer[k] = bf(v);
    else if (strncmp(f, "tix", 3) == 0)
        m->CarPullovers[k].nNumTickets = (int8_t)v;
    else if (strncmp(f, "mcop", 4) == 0)
        m->Cops[k] = (int32_t)v < 0 ? NULL : &cops[v];
    else
        unreached(f);
}

static void pset(tPursuit *p, const char *f, uint32_t v)
{
    int32_t i = (int32_t)v;

    if (strcmp(f, "state") == 0)
        p->PursuitState = i;
    else if (strcmp(f, "ncops") == 0)
        p->nNumCops = i;
    else if (strcmp(f, "cop0") == 0)
        p->Cops[0] = i < 0 ? NULL : &cops[i];
    else if (strcmp(f, "cop1") == 0)
        p->Cops[1] = i < 0 ? NULL : &cops[i];
    else if (strcmp(f, "rb") == 0)
        p->pRoadBlock = i < 0 ? NULL : &rbs[i];
    else if (strcmp(f, "chopper") == 0)
        p->pChopper = i < 0 ? NULL
                    : (struct Chopper *)(void *)choppers[i];
    else if (strcmp(f, "chst") == 0)
        p->ChopperState = i;
    else if (strcmp(f, "primary") == 0)
        p->PrimaryCopSpeaker = v;
    else if (strcmp(f, "secondary") == 0)
        p->SecondaryCopSpeaker = v;
    else if (strcmp(f, "backup") == 0)
        p->bAlreadyCalledForBackup = i;
    else if (strcmp(f, "maxchase") == 0)
        p->nMaxChaseCops = i;
    else if (strcmp(f, "rbtimer") == 0)
        p->fRoadBlockSpawnTimer = bf(v);
    else if (strcmp(f, "flags") == 0)
        p->BehaviourFlags = v;
    else if (strcmp(f, "chased") == 0)
        p->pChasedCar = i < 0 ? NULL : &cars[i];
    else if (strcmp(f, "landmark") == 0)
        p->CurrentLandmark = i;
    else if (strcmp(f, "rbstate") == 0)
        p->RoadBlockStateMachine.State = i;
    else
        unreached(f);
}

static void one_liner(const char *f, tPursuit *p, const char *arg)
{
    uint32_t v = arg != NULL ? num(arg) : 0;

    if (strcmp(f, "addcop") == 0) {
        tpursuit_add_cop(p, cop_arg(arg));
        printf("addcop\n");
    } else if (strcmp(f, "numcops") == 0)
        printf("numcops %d\n", (int)tpursuit_get_num_cops(p));
    else if (strcmp(f, "id") == 0)
        printf("id %d\n", (int)tpursuit_get_pursuit_id(p));
    else if (strcmp(f, "rbstate") == 0)
        printf("rbstate %d\n", (int)tpursuit_get_road_block_state(p));
    else if (strcmp(f, "dir") == 0)
        printf("dir %08x\n", fb(tpursuit_get_chase_direction(p)));
    else if (strcmp(f, "chst") == 0)
        printf("chst %d\n", (int)tpursuit_get_chopper_state(p));
    else if (strcmp(f, "over") == 0)
        printf("over %d\n", (int)tpursuit_is_pursuit_over(p));
    else if (strcmp(f, "called") == 0)
        printf("called %d\n", (int)tpursuit_has_called_for_backup(p));
    else if (strcmp(f, "needed") == 0)
        printf("needed %d\n", (int)tpursuit_is_backup_needed(p));
    else if (strcmp(f, "other") == 0)
        printf("other %s\n", sym(tpursuit_get_other_cop(p, cop_arg(arg))));
    else if (strcmp(f, "primcar") == 0)
        printf("primcar %d\n", (int)tpursuit_is_primary_car(p,
                                                              car_arg(arg)));
    else if (strcmp(f, "prim") == 0)
        printf("prim %d\n", (int)tpursuit_is_primary(p, cop_arg(arg)));
    else if (strcmp(f, "allowed") == 0)
        printf("allowed %d\n", (int)tpursuit_is_behaviour_allowed(p, v));
    else if (strcmp(f, "disallowall") == 0) {
        tpursuit_disallow_all_behaviours(p);
        printf("disallowall\n");
    } else if (strcmp(f, "disallow") == 0) {
        tpursuit_disallow_behaviour(p, v);
        printf("disallow\n");
    } else if (strcmp(f, "allow") == 0) {
        tpursuit_allow_behaviour(p, v);
        printf("allow\n");
    } else if (strcmp(f, "landmark") == 0)
        printf("landmark %d\n", (int)tpursuit_get_current_landmark(p));
    else if (strcmp(f, "hud") == 0)
        printf("hud %d\n", (int)tpursuit_get_pursuit_level_for_hud(p));
    else
        unreached(f);
}

static void op(char **a, int na)
{
    const char *o = a[0];
    tPursuit   *p = NULL;

    // The pursuit, for the ops whose first argument names one.
    if (na > 1)
        p = pursuit_tok(a[1]);
    if (strcmp(o, "reset") == 0) {
        reset();
    } else if (strcmp(o, "rp") == 0) {
        int32_t v = (int32_t)num(a[2]);

        if (strcmp(a[1], "Point2Point") == 0)
            TheRaceParameters.Point2Point = v;
        else if (strcmp(a[1], "NumLaps") == 0)
            TheRaceParameters.NumLapsInRace = v;
        else if (strcmp(a[1], "NumPlayerCars") == 0)
            TheRaceParameters.NumPlayerCars = v;
        else if (strcmp(a[1], "bRoadBlocks") == 0)
            TheRaceParameters.bRoadBlocks = v;
        else if (strcmp(a[1], "BeACop") == 0)
            TheRaceParameters.BeACop = v;
        else if (strcmp(a[1], "Units") == 0)
            TheRaceParameters.GlobalDisplaySettings.Units = (int8_t)v;
        else
            unreached(a[1]);
    } else if (strcmp(o, "g") == 0) {
        uint32_t v = num(a[2]);

        if (strcmp(a[1], "tracklen") == 0)
            TheTrackPathManager.TrackLength = bf(v);
        else if (strcmp(a[1], "rc") == 0)
            the_rc.CurrentRCState = (RCState)v;
        else if (strcmp(a[1], "seed") == 0)
            bDefaultSeed = v;
        else if (strcmp(a[1], "copcarpos") == 0)
            the_world.CopCarPos = (int32_t)v;
        else
            unreached(a[1]);
    } else if (strcmp(o, "m") == 0) {
        mset(a[1], num(a[2]));
    } else if (strcmp(o, "car") == 0) {
        int  k = (int)num(a[1]);
        Car *c = &cars[k];
        int  pl = (int)(int32_t)num(a[3]);

        c->CarIndex = (int16_t)num(a[2]);
        c->pPlayer = pl < 0 ? NULL : (Player *)(void *)players[pl];
        c->State.Position.x = bf(num(a[4]));
        c->State.Position.y = bf(num(a[5]));
        c->State.VelocityMagnitude = bf(num(a[6]));
        c->BlownTireBits = (uint8_t)num(a[7]);
        rcars[k].FinishReason = (int16_t)num(a[8]);
        rides[k].Type = (int32_t)num(a[9]);
        ctis[k].Aero.Drag = bf(num(a[10]));
        ctis[k].Body.Mass = bf(num(a[11]));
    } else if (strcmp(o, "acc") == 0) {
        int k = (int)num(a[1]);

        acc_cut[k] = num(a[2]);
        acc_low[k] = num(a[3]);
    } else if (strcmp(o, "cop") == 0) {
        tCop *c = &cops[num(a[1])];

        c->pMyPursuit = NULL;
        c->pMyCar = car_arg(a[3]);
        c->DesiredLogicState = 0;
        c->vptr = strcmp(a[2], "ai") == 0 ? TAICOP_VTABLE : TPLAYERCOP_VTABLE;
    } else if (strcmp(o, "rb") == 0) {
        tRoadBlock *r = &rbs[num(a[1])];

        r->cops[0] = (struct stAICop *)(void *)cop_arg(a[2]);
        r->cops[1] = (struct stAICop *)(void *)cop_arg(a[3]);
        r->nIndexIntoLoadedData = (int32_t)num(a[4]);
        r->CopSpeaker = num(a[5]);
    } else if (strcmp(o, "strip") == 0) {
        tSpikeStrip  *s = &strips[num(a[1])];
        tPursuitNode *l = &the_mgr.SpikeStripList;

        s->nRoadBlockID = (int32_t)num(a[2]);
        s->Node.Next = l;
        s->Node.Prev = l->Prev;
        l->Prev->Next = &s->Node;
        l->Prev = &s->Node;
    } else if (strcmp(o, "chopper") == 0) {
        uint32_t v = num(a[2]);

        memcpy(choppers[num(a[1])] + 960, &v, 4);
    } else if (strcmp(o, "pset") == 0) {
        pset(p, a[2], num(a[3]));
    } else if (strcmp(o, "barrel") == 0) {
        p->pBarricades->nBarrel[num(a[2])] = (int16_t)num(a[3]);
    } else if (strcmp(o, "new") == 0) {
        tPursuit *q = copmanager_new_pursuit(pCopManager,
                                             (int32_t)num(a[1]),
                                             car_arg(a[2]));

        printf("new %d %s -> %s\n", (int)(int32_t)num(a[1]),
               sym(car_arg(a[2])), sym(q));
    } else if (strcmp(o, "req") == 0) {
        int32_t r = copmanager_request_pursuit(pCopManager, cop_arg(a[1]),
                                               car_arg(a[2]));

        printf("req %s %s -> %d\n", sym(cop_arg(a[1])), sym(car_arg(a[2])),
               (int)r);
    } else if (strcmp(o, "sw") == 0) {
        tpursuit_switch_state(p, (ePursuitState)num(a[2]));
        printf("sw U%d %d\n", pursuit_index(p), (int)(int32_t)num(a[2]));
    } else if (strcmp(o, "st") == 0) {
        printf("st %08x -> %08x\n", num(a[1]),
               fb(tpursuit_state_time(bf(num(a[1])))));
    } else if (strcmp(o, "trans") == 0) {
        printf("trans U%d -> %d\n", pursuit_index(p),
               (int)tpursuit_do_state_transition(p));
    } else if (strcmp(o, "speed") == 0) {
        printf("speed U%d -> %08x\n", pursuit_index(p),
               fb(tpursuit_get_speed_mph_or_kph(p)));
    } else if (strcmp(o, "release") == 0) {
        tpursuit_release_all_cops(p);
        printf("release U%d\n", pursuit_index(p));
    } else if (strcmp(o, "disband") == 0) {
        tpursuit_disband_road_block(p, (int32_t)num(a[2]));
        printf("disband U%d %d\n", pursuit_index(p), (int)num(a[2]));
    } else if (strcmp(o, "remove") == 0) {
        printf("remove U%d %s -> %d\n", pursuit_index(p), sym(cop_arg(a[2])),
               (int)tpursuit_remove_cop_from_pursuit(p, cop_arg(a[2])));
    } else if (strcmp(o, "isin") == 0) {
        printf("isin U%d %s -> %d\n", pursuit_index(p), sym(cop_arg(a[2])),
               (int)tpursuit_is_cop_in_pursuit(p, cop_arg(a[2])));
    } else if (strcmp(o, "rps") == 0) {
        tpursuit_remove_primary_speaker(p, (int32_t)num(a[2]));
        printf("rps U%d %d\n", pursuit_index(p), (int)num(a[2]));
    } else if (strcmp(o, "rbr") == 0) {
        printf("rbr U%d -> %d\n", pursuit_index(p),
               (int)tpursuit_road_block_encountered_recently(p));
    } else if (strcmp(o, "sel") == 0) {
        tpursuit_select_primary_cop(p);
        printf("sel U%d\n", pursuit_index(p));
    } else if (strcmp(o, "spk1") == 0) {
        printf("spk1 U%d -> %08x\n", pursuit_index(p),
               tpursuit_get_cop_speaker(p));
    } else if (strcmp(o, "spk2") == 0) {
        printf("spk2 U%d -> %08x\n", pursuit_index(p),
               tpursuit_get_secondary_cop_speaker(p));
    } else if (strcmp(o, "pi") == 0) {
        printf("pi U%d -> %d\n", pursuit_index(p),
               (int)tpursuit_is_player_involved(p));
    } else if (strcmp(o, "super") == 0) {
        copmanager_possible_call_supervisor(pCopManager, p);
        printf("super U%d\n", pursuit_index(p));
    } else if (strcmp(o, "del") == 0) {
        copmanager_delete_pursuit(pCopManager, p);
        printf("del U%d\n", pursuit_index(p));
    } else if (strcmp(o, "dtor") == 0) {
        tpursuit_destruct(p, (int32_t)num(a[2]));
        printf("dtor U%d %d\n", pursuit_index(p), (int)num(a[2]));
    } else if (strcmp(o, "top") == 0) {
        printf("top %s -> %08x\n", sym(car_arg(a[1])),
               fb(get_top_speed(car_arg(a[1]))));
    } else if (strcmp(o, "dss") == 0) {
        copmanager_delete_road_block_spike_strips(pCopManager,
                                                  (int32_t)num(a[1]));
        printf("dss %d\n", (int)(int32_t)num(a[1]));
    } else if (strcmp(o, "bfade") == 0) {
        barricademanager_fade(p->pBarricades, bf(num(a[2])));
        printf("bfade U%d %08x\n", pursuit_index(p), num(a[2]));
    } else if (strcmp(o, "ol") == 0) {
        one_liner(a[1], pursuit_tok(a[2]), na > 3 ? a[3] : NULL);
    } else if (strcmp(o, "dump") == 0) {
        dump_all(p);
    } else if (strcmp(o, "ldump") == 0) {
        const tPursuitNode *l = &the_mgr.PursuitList;
        const tPursuitNode *n;

        for (n = l->Next; n != l; n = n->Next)
            dump_all((tPursuit *)(void *)n);
    } else if (strcmp(o, "mdump") == 0) {
        mdump();
    } else if (strcmp(o, "cdump") == 0) {
        cdump();
    } else if (strcmp(o, "fades") == 0) {
        fades();
    } else {
        unreached(o);
    }
}

int main(int argc, char **argv)
{
    static char line[1 << 16];
    FILE       *f;
    int         i;

    if (argc != 2) {
        fprintf(stderr, "usage: pursuit_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    pCopManager = &the_mgr;
    pCurrentWorld = &the_world;
    pRaceCoordinator = &the_rc;
    PursuitSlotPool = (BSlotPool *)(void *)pool_token;
    name(pool_token, "pool", 0);
    name(&the_mgr.PursuitList, "M.plist", 0);
    name(&the_mgr.SpikeStripList, "M.slist", 0);
    for (i = 0; i < NCARS; i++) {
        cars[i].pCarTypeInfo = &ctis[i];
        cars[i].pRideInfo = &rides[i];
        cars[i].pRacingCar = &rcars[i];
        name(&cars[i], "A%d", i);
    }
    for (i = 0; i < 2; i++)
        name(players[i], "P%d", i);
    for (i = 0; i < NCOPS; i++)
        name(&cops[i], "C%d", i);
    for (i = 0; i < NRBS; i++)
        name(&rbs[i], "R%d", i);
    for (i = 0; i < NSTRIPS; i++)
        name(&strips[i], "S%d", i);
    for (i = 0; i < NCHOPPERS; i++)
        name(choppers[i], "H%d", i);
    for (i = 0; i < NBODIES; i++)
        name(bodymem[i], "Y%d", i);
    vt_install(TAICOP_VTABLE, aicop_vt, 3);
    vt_install(TPLAYERCOP_VTABLE, playercop_vt, 3);
    pursuit_install_vtables();
    barricade_install_vtables();
    gPursuitStartSpeechFn = start_speech;
    gPursuitJoinSpeechFn = join_speech;
    gPursuitBackOffSpeechFn = backoff_speech;
    gSpeechRaiseCrashTowFn = crash_tow;
    gSpeechRaiseCrashFn = crash;
    gSpeechRaiseFlatTireFn = flat_tire;
    gSpeechRaiseSuperRequestFn = super_request;
    gPlayerLoadNextNisFn = load_next_nis;
    gChopperNew960Fn = chopper_960;
    gChopperFollowThisCarFn = follow;
    gSpikeStripBlinkBlinkPoofFn = poof;
    gBarricadeDeleteBarrelFn = delete_barrel;
    gBarricadeMarkBodyFadingFn = mark_fading;
    reset();
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
