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
#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "carinit.h"
#include "collision.h"
#include "collisionbody.h"
#include "configitems.h"
#include "cop.h"
#include "copmgr.h"
#include "drivetarget.h"
#include "race.h"
#include "topology.h"
#include "trackmap.h"
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

static int32_t         skipfe;
static uint8_t         world_token[64];
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

float world_random_f(World *w, float f)
{
    printf("  random %s %08x\n", sym(w), fb(f));
    return bf(fb(f) ^ 0x00300000u);
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

void car_set_control_mode(Car *c, ControlMode mode)
{
    (void)c; (void)mode;
    unreached("car_set_control_mode");
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    (void)c; (void)mode;
    unreached("car_set_movement_mode");
}

void car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                           uint16_t angle)
{
    (void)c; (void)pos; (void)speed; (void)angle;
    unreached("car_reset_to_position");
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

static const VtEntry aicop_vt[] = { {0, 0, NULL},
                                    {0, 0, (VtFn)aicop_dtor},
                                    {0, 0, (VtFn)aicop_is_ai} };
static const VtEntry playercop_vt[] = { {0, 0, NULL},
                                        {0, 0, (VtFn)playercop_dtor},
                                        {0, 0, (VtFn)playercop_is_ai} };
static const VtEntry spike_vt[] = { {0, 0, NULL},
                                    {0, 0, (VtFn)spike_dtor} };

static tPursuit *pursuits[16];

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
        hexwords(&r->pos, 4);
        printf(" ang %08x icon %04x %04x name %s", (uint32_t)r->ang,
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
            pCurrentWorld = num(a[2]) ? (World *)(void *)world_token : NULL;
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
        m->Cops[atoi(a[1])]->pMyCar = &cars[atoi(a[2])];
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
    } else if (!strcmp(o, "spike")) {
        int          k = atoi(a[1]);
        tSpikeStrip *s = malloc(sizeof *s);

        memset(s, 0xcd, sizeof *s);
        name(s, "S%d", k);
        link_tail(&m->SpikeStripList, &s->Node);
        s->vptr = VT_SPIKE;
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
    name(world_token, "W%d", 0);
    gCopSpeechAllocateVoicesFn = voices;
    gCopSpeechFlushQueueFn = flush;
    vt_install(VT_PURSUIT, pursuit_vt, 2);
    vt_install(VT_AICOP, aicop_vt, 3);
    vt_install(VT_PLAYERCOP, playercop_vt, 3);
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
