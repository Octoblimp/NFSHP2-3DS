// Harness for tools/traffictele_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out, and stands in for what the checker stubs.
//
//     traffictele_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airouteplan.h"
#include "airoute.h"
#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "carinit.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "trackpath.h"
#include "trackroute.h"
#include "traffictele.h"
#include "vtable.h"
#include "world.h"

enum {
    OP_TAG, OP_JUNK, OP_NEW, OP_DEL, OP_STEP, OP_PLACE, OP_TRY, OP_GOOD,
    OP_VIS, OP_VISAT, OP_THINKT, OP_FOB, OP_FILL, OP_CLOSEAT, OP_CLOSE,
    OP_PICK, OP_RPC, OP_SKIN, OP_SWITCH, OP_GTD, OP_DUMP, OP_STATIC,
    OP_TPOKE, OP_SET, OP_RI, OP_RF, OP_SEED, OP_RCLEAR, OP_GLOBAL, OP_SLOT,
    OP_ROUTE, OP_RPOINT, OP_SIGN, OP_CAR, OP_LCLEAR, OP_LADD, OP_WORLD,
    OP_TABLE, OP_PLAYER, OP_INFO
};

enum {
    K_PDAT, K_DIST, K_NEAR_RET, K_NEAR_ROUTE, K_NEAR_POINT, K_NSKINS,
    K_SKINBASE, K_CTLDELTA, K_POOF_MASK, K_COUNT
};

enum {
    G_DENSITY, G_ONCOMING, G_TRACKLEN, G_TIMER, G_NPLAYERS, G_RACE, G_STAGE,
    G_START, G_BOUNDARY, G_BDIST
};

enum { PF_X, PF_Y, PF_Z, PF_DX, PF_DY, PF_LEN, PF_DAT, PF_BITS };

enum { C_DAT, C_X, C_Y, C_RENDER, C_DTYPE, C_CT, C_SKIN };

#define NO_CAR    (-1)
#define NCARS     8
#define NCT       4
#define NROUTES   6
#define NSIGNS    256    // every index a point's byte can give
#define NBDIST    5
#define NOUT      32     // the out entries the checker reads
#define OUT_ROOM  128    // and room past them
#define NQUEUE    4096
#define SLACK     16
#define MAX_HEAP  4096
#define CTL_ROOM  512

// The test controller's table, where the model's is.
#define FAKE_CTL_VT 0x01e01400u

// ------------------------------------------------------------- the world

static union {
    TrafficTeleporter t;
    unsigned char     b[sizeof(TrafficTeleporter)];
} tu;
static TrafficTeleporter *const t = &tu.t;

static Car           cars[NCARS];
static RideInfo      rides[NCARS];
static DriverInfo    drvs[NCARS];
static World         world;
static Race          race;
static DriverInfo    info;
static struct Player players[2];
static char          cts[NCT][16];  // only their addresses are read
static TrackRoute    routes[NROUTES];
static Signpost      signs[NSIGNS];

// The controller in the middle of room either side, for a this-adjustment
// either way.
static union {
    CarController c;
    double        align;
    char          b[2 * CTL_ROOM];
} ctl_mem;
#define CTL ((CarController *)(void *)(ctl_mem.b + CTL_ROOM))

static NearestRoutePointInfo scr_info;
static bVector2              scr_vec;
static uint32_t              scr_words[11];
static NearestRoutePointInfo out[OUT_ROOM];

// What the linked files leave to the game.
int32_t        WorldTimer;
World         *pCurrentWorld;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];

static uint32_t vals[K_COUNT];
static uint32_t qi[NQUEUE], qf[NQUEUE];
static int      qi_head, qi_tail, qf_head, qf_tail;
static uint32_t seed;

static int order[NCARS * 4];
static int norder;

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static Car *car_of(int32_t i)
{
    if (i == NO_CAR)
        return NULL;
    if (i < 0 || i >= NCARS) {
        fprintf(stderr, "no car %d\n", i);
        exit(2);
    }
    return &cars[i];
}

static TrackRoute *route_of(int32_t k)
{
    if (k < 0)
        return NULL;
    if (k >= NROUTES) {
        fprintf(stderr, "no route %d\n", k);
        exit(2);
    }
    return &routes[k];
}

// k <= -2: route -k-2's point, given with no route.
static TrackRoutePoint *point_of(int32_t k, int32_t i)
{
    if (k <= -2)
        return point_of(-k - 2, i);
    if (k < 0 || i < 0)
        return NULL;
    if (i >= TRACK_ROUTE_MAX_POINTS) {
        fprintf(stderr, "no point %d\n", i);
        exit(2);
    }
    return &route_of(k)->TrackRoutePointTable[i];
}

static const CarTypeInfo *ct_of(int32_t k)
{
    if (k < 0)
        return NULL;
    if (k >= NCT) {
        fprintf(stderr, "no car type %d\n", k);
        exit(2);
    }
    return (const CarTypeInfo *)(const void *)cts[k];
}

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;
} heap[MAX_HEAP];
static int nheap;

// The console's size of what the port asked for: its Car is wider on a
// 64-bit host.
static int console_size(int size, const char *name)
{
    if (strcmp(name, "Car") == 0 && size == (int)sizeof(Car))
        return 2208;
    return size;
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    size_t span = (size > 0 ? (size_t)size : 0) + SLACK;
    void  *p = malloc(span);

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    memset(p, 0xcd, span);
    heap[nheap].p = p;
    heap[nheap].span = span;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap,
           console_size(size, name), name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a)
{
    static const struct {
        const void *p;
        const char *name;
    } named[] = {
        { &tu, "t" },
        { &world, "world" },
        { &race, "race" },
        { &info, "info" },
        { &scr_info, "scr" },
        { &scr_vec, "scr" },
        { scr_words, "scr" },
        { &players[0], "p0" },
        { &players[1], "p1" },
    };
    const char *b = (const char *)a;
    size_t k;
    int i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    for (k = 0; k < sizeof named / sizeof named[0]; k++)
        if (a == named[k].p) {
            snprintf(buf, n, "%s", named[k].name);
            return;
        }
    if (b >= ctl_mem.b && b < ctl_mem.b + sizeof ctl_mem.b) {
        ptrdiff_t off = b - (const char *)CTL;
        if (off == 0)
            snprintf(buf, n, "ctl");
        else if (off > 0)
            snprintf(buf, n, "ctl+%d", (int)off);
        else
            snprintf(buf, n, "ctl-%d", (int)-off);
        return;
    }
    for (i = 0; i < NCARS; i++) {
        if (a == (const void *)&cars[i]) {
            snprintf(buf, n, "c%d", i);
            return;
        }
        if (a == (const void *)&rides[i]) {
            snprintf(buf, n, "ride%d", i);
            return;
        }
        if (a == (const void *)&drvs[i]) {
            snprintf(buf, n, "drv%d", i);
            return;
        }
    }
    for (i = 0; i < NCT; i++)
        if (a == (const void *)cts[i]) {
            snprintf(buf, n, "ct%d", i);
            return;
        }
    for (i = 0; i < NROUTES; i++) {
        const char *p = (const char *)&routes[i];
        if (b >= p && b < p + sizeof(TrackRoute)) {
            ptrdiff_t off = b - p;
            ptrdiff_t tab = (ptrdiff_t)offsetof(TrackRoute,
                                                TrackRoutePointTable);
            if (off == 0)
                snprintf(buf, n, "r%d", i);
            else if (off >= tab
                     && (off - tab) % (ptrdiff_t)sizeof(TrackRoutePoint) == 0)
                snprintf(buf, n, "r%dp%d", i,
                         (int)((off - tab)
                               / (ptrdiff_t)sizeof(TrackRoutePoint)));
            else
                snprintf(buf, n, "r%d+%d", i, (int)off);
            return;
        }
    }
    for (i = 0; i < NSIGNS; i++)
        if (a == (const void *)&signs[i]) {
            snprintf(buf, n, "s%d", i);
            return;
        }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (b >= p && b < p + heap[i].span) {
            if (b == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(b - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static const char *lab(const void *a)
{
    static char bufs[16][48];
    static int k;
    char *b = bufs[k++ & 15];

    label(b, 48, a);
    return b;
}

// Logged, never freed, so no address is handed out twice.
static void free_hook(void *p)
{
    printf("  free %s\n", lab(p));
}

// ------------------------------------------------------- the random numbers

static uint32_t lcg(void)
{
    seed = seed * 1103515245u + 12345u;
    return seed >> 8;
}

int32_t world_random_i(World *w, int32_t range)
{
    int32_t r;

    if (qi_head < qi_tail) {
        r = (int32_t)qi[qi_head++];
    } else {
        uint32_t x = lcg();
        r = range > 0 ? (int32_t)(x % (uint32_t)range) : 0;
    }
    printf("  rand %s %d -> %d\n", lab(w), range, r);
    return r;
}

float world_random_f(World *w, float f)
{
    uint32_t r;

    if (qf_head < qf_tail) {
        r = qf[qf_head++];
    } else {
        float u = (float)lcg() * (1.0f / 16777216.0f);
        r = bitsf(u * f);
    }
    printf("  randf %s %08x -> %08x\n", lab(w), bitsf(f), r);
    return fbits(r);
}

static void push(uint32_t *q, int *tail, uint32_t v)
{
    if (*tail >= NQUEUE) {
        fprintf(stderr, "random queue full\n");
        exit(3);
    }
    q[(*tail)++] = v;
}

// ------------------------------------------------------------ stand-ins

float world_get_dat_to_closest_player(const World *w, float dat)
{
    float    r = dat - fbits(vals[K_PDAT]);
    uint32_t rb = r != r ? 0x7fc00000u : bitsf(r);

    printf("  datclose %s %08x -> %08x\n", lab(w), bitsf(dat), rb);
    return fbits(rb);
}

float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p)
{
    printf("  distclose %s %08x %08x -> %08x\n", lab(w), bitsf(p->x),
           bitsf(p->y), vals[K_DIST]);
    return fbits(vals[K_DIST]);
}

int ai_get_nearest_route_point(NearestRoutePointInfo *o, const bVector2 *pos,
                               RoutesToSearch which, int flags,
                               float distanceAround)
{
    int32_t r = (int32_t)vals[K_NEAR_RET];

    printf("  nearest scr %08x %08x routes %d %d %08x -> %d\n",
           bitsf(pos->x), bitsf(pos->y), (int)which, flags,
           bitsf(distanceAround), r);
    if (r) {
        int32_t k = (int32_t)vals[K_NEAR_ROUTE];
        o->Route = route_of(k);
        o->Point = point_of(k, (int32_t)vals[K_NEAR_POINT]);
    }
    return r;
}

int32_t car_is_poofed(Car *c)
{
    int     i = (int)(c - cars);
    int32_t r = (int32_t)((vals[K_POOF_MASK] >> i) & 1u);

    printf("  poofed %s -> %d\n", lab(c), r);
    return r;
}

// The image indexes the CarTypeInfo array itself.
const CarTypeInfo *cartypeinfo_get(int32_t carType)
{
    return ct_of(carType);
}

int32_t cartypeinfo_get_num_skins(const CarTypeInfo *ct)
{
    int32_t r = (int32_t)vals[K_NSKINS];

    printf("  numskins %s -> %d\n", lab(ct), r);
    return r;
}

int32_t cartypeinfo_get_skin_number(const CarTypeInfo *ct, int32_t i)
{
    int32_t r = (int32_t)((uint32_t)i + vals[K_SKINBASE]);

    printf("  skinnumber %s %d -> %d\n", lab(ct), i, r);
    return r;
}

Car *car_construct(Car *c, DriverInfo *driver, const bVector3 *pos,
                   uint16_t angle, float dist)
{
    printf("  car init %s %s pos %08x %08x %08x angle %d dat %08x\n",
           lab(c), lab(driver), bitsf(pos->x), bitsf(pos->y), bitsf(pos->z),
           (int)angle, bitsf(dist));
    c->pCarController = CTL;
    return c;
}

void car_set_movement_mode(Car *c, MovementMode mode)
{
    printf("  mode %s %d\n", lab(c), (int)mode);
}

void car_set_control_mode(Car *c, ControlMode mode)
{
    printf("  control %s %d\n", lab(c), (int)mode);
}

void car_reset_to_route_point(Car *c, TrackRoute *route,
                              TrackRoutePoint *point, float speed,
                              int32_t blink, float direction)
{
    printf("  resetto %s %s %s speed %08x blink %d dir %08x\n", lab(c),
           lab(route), lab(point), bitsf(speed), blink, bitsf(direction));
}

void car_switch_skin(Car *c, uint32_t skin)
{
    printf("  switchskin %s %d\n", lab(c), (int32_t)skin);
}

// The test controller's SetCurrentRoute (slot 40).
static void fake_set_route(void *self, TrackRoute *r, TrackRoutePoint *p)
{
    printf("  setroute %s %s %s\n", lab(self), lab(r), lab(p));
}

static VtEntry ctl_vt[VT_SLOT(CARCONTROLLER_VT_SET_CURRENT_ROUTE) + 1];

static void install_ctl_vt(int16_t delta)
{
    VtEntry *e = &ctl_vt[VT_SLOT(CARCONTROLLER_VT_SET_CURRENT_ROUTE)];

    e->delta = delta;
    e->fn = (VtFn)fake_set_route;
    vt_install(FAKE_CTL_VT, ctl_vt,
               (int)(sizeof ctl_vt / sizeof ctl_vt[0]));
}

// TrackPathCoordinate's ResetPosition, through trackpath.c's seam.
static float reset_seam(const bVector2 *pos)
{
    printf("  reset %08x %08x\n", bitsf(pos->x), bitsf(pos->y));
    return 0.0f;
}

// ------------------------------------------------------------- the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **strs = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        strs[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            strs[i][k] = (char)next();
        strs[i][len] = 0;
    }
    *count = n;
    return strs;
}

static void global(int32_t g, int32_t v)
{
    uint32_t u = (uint32_t)v;

    switch (g) {
    case G_DENSITY:  TheRaceParameters.TrafficDensity = fbits(u); break;
    case G_ONCOMING: TheRaceParameters.TrafficOncoming = fbits(u); break;
    case G_TRACKLEN: TheTrackPathManager.TrackLength = fbits(u); break;
    case G_TIMER:    WorldTimer = v; break;
    case G_NPLAYERS: PlayerNumPlayers = v; break;
    case G_RACE:     pCurrentRace = v ? &race : NULL; break;
    case G_STAGE:    race.RaceStage = (eRaceStage)v; break;
    case G_START:    race.StartTime.PackedTime = u; break;
    case G_BOUNDARY: race.StartLineBoundaryNumber = (int8_t)v; break;
    default:
        if (g >= G_BDIST && g < G_BDIST + NBDIST) {
            race.BoundaryDistances[g - G_BDIST] = fbits(u);
            break;
        }
        fprintf(stderr, "no global %d\n", g);
        exit(2);
    }
}

static void rpoint(int32_t k, int32_t i, int32_t f, int32_t v)
{
    TrackRoutePoint *p = point_of(k, i);
    float            x = fbits((uint32_t)v);

    switch (f) {
    case PF_X:    p->Position.x = x; break;
    case PF_Y:    p->Position.y = x; break;
    case PF_Z:    p->Elevation = x; break;
    case PF_DX:   p->Direction.x = x; break;
    case PF_DY:   p->Direction.y = x; break;
    case PF_LEN:  p->Length = x; break;
    case PF_DAT:  p->DistanceAroundTrack = x; break;
    case PF_BITS: p->Bits = (uint32_t)v; break;
    default:
        fprintf(stderr, "no point field %d\n", f);
        exit(2);
    }
}

static void car_field(int32_t i, int32_t f, int32_t v)
{
    Car *c = car_of(i);

    switch (f) {
    case C_DAT:
        c->TheTrackPathCoordinate.DistanceAroundTrack = fbits((uint32_t)v);
        break;
    case C_X:      c->State.Position.x = fbits((uint32_t)v); break;
    case C_Y:      c->State.Position.y = fbits((uint32_t)v); break;
    case C_RENDER: c->RenderingEnabled = (int8_t)v; break;
    case C_DTYPE:  drvs[i].TheDriverType = v; break;
    case C_CT:     c->pCarTypeInfo = (CarTypeInfo *)(void *)ct_of(v); break;
    case C_SKIN:   rides[i].SkinNumber = (int8_t)v; break;
    default:
        fprintf(stderr, "no car field %d\n", f);
        exit(2);
    }
}

// The World's car list in `order`, the World its head and end.
static void links(void)
{
    CarNode *end = (CarNode *)(void *)&world.CarList;
    CarNode *prev = end;
    int      k;

    for (k = 0; k < norder; k++) {
        CarNode *n = &cars[order[k]].Link;
        prev->next = n;
        n->prev = prev;
        prev = n;
    }
    prev->next = end;
    end->prev = prev;
}

static void dump(void)
{
    int k;

    printf("t time %08x last %d fwd", bitsf(t->TimeUntilTeleport),
           t->LastCar);
    for (k = 0; k < TRAFFIC_ROUTES_EACH; k++)
        printf(" %u", t->ForwardTotals[k]);
    printf(" back");
    for (k = 0; k < TRAFFIC_ROUTES_EACH; k++)
        printf(" %u", t->BackwardTotals[k]);
    printf("\n");
}

// ------------------------------------------------------------- the main

int main(int argc, char **argv)
{
    FILE   *fp;
    long    len;
    int32_t ntags, nflat;
    char  **tags;
    size_t  end;
    int     k;

    if (argc != 2) {
        fprintf(stderr, "usage: traffictele_test ops.bin\n");
        return 2;
    }
    fp = fopen(argv[1], "rb");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fp) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fp);

    tags = read_strings(&ntags);
    nflat = next();
    end = rd + (size_t)nflat;

    bSetMemoryHooks(malloc_hook, free_hook);
    vt_reset();
    install_ctl_vt(0);
    CTL->_vtable = FAKE_CTL_VT;
    gTrackPathDistanceFn = reset_seam;
    pCurrentWorld = &world;
    pCurrentRace = &race;
    SignpostArray = signs;
    PlayerPlayersByIndex[0] = &players[0];
    PlayerPlayersByIndex[1] = &players[1];
    for (k = 0; k < NCARS; k++) {
        cars[k].pRideInfo = &rides[k];
        cars[k].MyDriver = &drvs[k];
    }
    links();

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_JUNK:
            memset(&tu, next() & 0xff, sizeof tu);
            break;
        case OP_NEW: {
            TrafficTeleporter *r = traffic_teleporter_construct(t);
            printf("new -> %s\n", lab(r));
            break;
        }
        case OP_DEL: {
            int32_t flags = next();
            printf("del %d\n", flags);
            traffic_teleporter_destroy(t, flags);
            break;
        }
        case OP_STEP: {
            uint32_t dt = (uint32_t)next();
            printf("step %08x\n", dt);
            traffic_teleporter_do_timestep(t, fbits(dt));
            break;
        }
        case OP_PLACE: {
            Car *c;
            printf("place\n");
            c = traffic_teleporter_place_new_car(t, &info);
            printf("place -> %s\n", lab(c));
            if (c != NULL)
                printf("  render %d\n", c->RenderingEnabled);
            printf("  info skin %d\n", info.CurrentRideInfo.SkinNumber);
            break;
        }
        case OP_TRY: {
            Car *c = car_of(next());
            printf("try %s\n", lab(c));
            traffic_teleporter_try_to_teleport_car(t, c);
            break;
        }
        case OP_GOOD: {
            int32_t kk = next(), i = next(), ex = next(), al = next(), r;
            scr_info.Route = route_of(kk);
            scr_info.Point = point_of(kk, i);
            r = traffic_teleporter_is_good_place(t, &scr_info, car_of(ex),
                                                 al);
            printf("good r%dp%d %s %d -> %d\n", kk, i, lab(car_of(ex)), al,
                   r);
            break;
        }
        case OP_VIS: {
            uint32_t dat = (uint32_t)next();
            int32_t  r = traffic_teleporter_check_is_visible(t, fbits(dat));
            printf("vis %08x -> %d\n", dat, r);
            break;
        }
        case OP_VISAT: {
            int32_t r;
            scr_vec.x = fbits((uint32_t)next());
            scr_vec.y = fbits((uint32_t)next());
            r = traffic_teleporter_check_is_visible_at(t, &scr_vec);
            printf("visat -> %d\n", r);
            break;
        }
        case OP_THINKT:
            traffic_teleporter_set_think_time(t);
            break;
        case OP_FOB:
            printf("fob -> %d\n", traffic_teleporter_forwards_or_backwards(t));
            break;
        case OP_FILL: {
            int32_t first = next();
            for (k = 0; k < 11; k++)
                scr_words[k] = 0x5a5a5a5au;
            traffic_teleporter_fill_in_totals(t, scr_words, first);
            printf("fill %d ->", first);
            for (k = 0; k < 11; k++)
                printf(" %d", (int32_t)scr_words[k]);
            printf("\n");
            break;
        }
        case OP_CLOSEAT: {
            uint32_t x = (uint32_t)next(), y = (uint32_t)next();
            int32_t  ex = next(), al = next(), r;
            scr_vec.x = fbits(x);
            scr_vec.y = fbits(y);
            r = traffic_teleporter_too_close_at(t, &scr_vec, car_of(ex), al);
            printf("closeat %08x %08x %s %d -> %d\n", x, y, lab(car_of(ex)),
                   al, r);
            break;
        }
        case OP_CLOSE: {
            uint32_t dat = (uint32_t)next();
            int32_t  ex = next(), al = next(), r;
            r = traffic_teleporter_too_close_to_another_car(
                t, fbits(dat), car_of(ex), al);
            printf("close %08x %s %d -> %d\n", dat, lab(car_of(ex)), al, r);
            break;
        }
        case OP_PICK: {
            int32_t fwd = next();
            memset(&scr_info, 0x5a, sizeof scr_info);
            traffic_teleporter_pick_route_point(t, &scr_info, fwd);
            printf("pick %d -> %s %s\n", fwd, lab(scr_info.Route),
                   lab(scr_info.Point));
            break;
        }
        case OP_RPC:
            printf("rpc -> %s\n",
                   lab(traffic_teleporter_random_player_car(t)));
            break;
        case OP_SKIN: {
            const CarTypeInfo *ct = ct_of(next());
            printf("skin -> %d\n", traffic_teleporter_pick_random_skin(t, ct));
            break;
        }
        case OP_SWITCH: {
            Car *c = car_of(next());
            printf("switch %s\n", lab(c));
            traffic_teleporter_switch_skin(t, c);
            break;
        }
        case OP_GTD: {
            int32_t  count = next(), kk = next(), i = next();
            uint32_t dist = (uint32_t)next();
            int32_t  fwd = next(), r, j;
            int64_t  m;
            memset(out, 0x5a, sizeof out);
            r = ai_guess_target_destinations(out, (uint32_t)count,
                                             route_of(kk), point_of(kk, i),
                                             fbits(dist), fwd);
            if (r > NOUT) {
                fprintf(stderr, "gtd wrote %d\n", r);
                return 3;
            }
            m = r;
            if ((int64_t)(uint32_t)count > m)
                m = (uint32_t)count;
            if (m < 0)
                m = 0;
            if (m + 1 < NOUT)
                m = m + 1;
            else
                m = NOUT;
            printf("gtd %u r%dp%d %08x %d -> %d", (uint32_t)count, kk, i,
                   dist, fwd, r);
            for (j = 0; j < (int32_t)m; j++)
                printf(" %s/%s", lab(out[j].Route), lab(out[j].Point));
            printf("\n");
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_STATIC:
            printf("k min %08x speed %08x\n", bitsf(TELEPORT_MIN_DENSITY),
                   bitsf(TELEPORT_SPEED));
            break;
        case OP_TPOKE: {
            int32_t idx = next(), v = next();
            uint32_t u = (uint32_t)v;
            if (idx < 0 || (size_t)idx >= sizeof tu / 4) {
                fprintf(stderr, "no word %d\n", idx);
                return 2;
            }
            memcpy(tu.b + 4 * idx, &u, 4);
            break;
        }
        case OP_SET: {
            int32_t key = next(), v = next();
            if (key < 0 || key >= K_COUNT) {
                fprintf(stderr, "no key %d\n", key);
                return 2;
            }
            vals[key] = (uint32_t)v;
            if (key == K_CTLDELTA)
                install_ctl_vt((int16_t)v);
            break;
        }
        case OP_RI:
            push(qi, &qi_tail, (uint32_t)next());
            break;
        case OP_RF:
            push(qf, &qf_tail, (uint32_t)next());
            break;
        case OP_SEED:
            seed = (uint32_t)next();
            break;
        case OP_RCLEAR:
            qi_head = qi_tail = 0;
            qf_head = qf_tail = 0;
            break;
        case OP_GLOBAL: {
            int32_t g = next(), v = next();
            global(g, v);
            break;
        }
        case OP_SLOT: {
            int32_t idx = next(), kk = next();
            if (idx < 0 || idx >= TRACK_ROUTE_MAX_ROUTES) {
                fprintf(stderr, "no slot %d\n", idx);
                return 2;
            }
            TheTrackRouteManager.pTrackRoutes[idx] = route_of(kk);
            break;
        }
        case OP_ROUTE: {
            TrackRoute *r = route_of(next());
            r->NumPoints = next();
            r->RouteNumber = (int16_t)next();
            break;
        }
        case OP_RPOINT: {
            int32_t kk = next(), i = next(), f = next(), v = next();
            rpoint(kk, i, f, v);
            break;
        }
        case OP_SIGN: {
            int32_t i = next(), flags = next(), nr = next(), np = next();
            if (i < 0 || i >= NSIGNS) {
                fprintf(stderr, "no sign %d\n", i);
                return 2;
            }
            signs[i].Flags = (uint8_t)flags;
            signs[i].NewRoute = (uint8_t)nr;
            signs[i].NewPoint = (uint16_t)np;
            break;
        }
        case OP_CAR: {
            int32_t i = next(), f = next(), v = next();
            car_field(i, f, v);
            break;
        }
        case OP_LCLEAR:
            norder = 0;
            links();
            break;
        case OP_LADD: {
            int32_t i = next();
            car_of(i);
            if (norder >= (int)(sizeof order / sizeof order[0])) {
                fprintf(stderr, "car list full\n");
                return 2;
            }
            order[norder++] = i;
            links();
            break;
        }
        case OP_WORLD:
            world.TotalNumCars = next();
            world.TrafficCarPos = next();
            break;
        case OP_TABLE: {
            int32_t i = next(), c = next();
            if (i < 0 || i >= WORLD_MAX_CARS) {
                fprintf(stderr, "no table slot %d\n", i);
                return 2;
            }
            world.CarTable[i] = car_of(c);
            break;
        }
        case OP_PLAYER: {
            int32_t i = next(), c = next();
            if (i < 0 || i >= 2) {
                fprintf(stderr, "no player %d\n", i);
                return 2;
            }
            players[i].MyCar = car_of(c);
            break;
        }
        case OP_INFO:
            info.CurrentRideInfo.Type = next();
            info.CurrentRideInfo.SkinNumber = (int8_t)next();
            break;
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    return 0;
}
