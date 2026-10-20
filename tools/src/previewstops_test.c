// Harness for tools/previewstops_check.py: runs the checker's script on
// 3DS Files/source/previewstops.c, and prints what the model prints for
// the retail image. See the checker's docstring.
//
//     previewstops_test script.txt > out.txt
//
// The harness owns what previewstops.c reaches outside itself and the
// files linked with it: bMalloc and bFree (a pool of 0xa5-filled blocks,
// each call printed), pCurrentWorld (race.c owns pCurrentRace), and the
// stubs the model prints on its side too: Collision::IsTwoCarCollision,
// TopologyCoordinate's SetInterestBBox and SegmentIntersects, and
// DownSampleXY (previewspline.c's, another helper's). copmanager.c's
// roadblock walk, race.c's GetRacingCar, spline.c and trackroute.c's
// heap_sort are the port's own.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// is. Vectors print without their fourth lane where retail's comes from a
// stack word.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmem.h"
#include "car.h"
#include "chopper.h"
#include "collision.h"
#include "copmanager.h"
#include "previewroute.h"
#include "previewspline.h"
#include "previewstops.h"
#include "race.h"
#include "spline.h"
#include "topology.h"
#include "world.h"

#define PAT     0xa5
#define POOL    (1 << 20)
#define NALLOC  4096
#define NCOP    12
#define NCAR    14
#define NRB     8
#define NPUR    8
#define NSPIKE  6
#define NCOLL   8
#define NPTS    64
#define NSTOPS  8
#define NTOPO   64

World *pCurrentWorld;
int32_t WorldTimer;         // realtime.c's, which replay.c reads
int32_t WorldLoopCounter;

static tCopManager mgr;
static tCop cops[NCOP];
static Car cars[NCAR];
static struct RacingCar rcars[NCAR];
static tRoadBlock rbs[NRB];
static tPursuit purs[NPUR];
static int npur;
static tSpikeStrip spikes[NSPIKE];
static int nspike;
static struct Chopper heli;
static World world;
static Collision colls[NCOLL];
static int colltwo[NCOLL];
static int ncoll;
static uint8_t race_buf[64];
static TopologyCoordinate tc;
static PreviewRoute route;
static Spline eye, look, ahead;
static bVector3 eye_pts[NPTS], look_pts[NPTS], ahead_pts[NPTS];
static Linear lin_e, lin_l;
static float stops[NSTOPS];
static int topo[NTOPO];
static int ntopo, itopo;

static unsigned char pool[POOL] __attribute__((aligned(16)));
static size_t pool_used;
static void *allocs[NALLOC];
static int nalloc;

static void fill(void *p, size_t n)
{
    memset(p, PAT, n);
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (p == &tc)
        return "tc";
    if (p == &route)
        return "route";
    if (p == &eye)
        return "eye";
    if (p == &look)
        return "look";
    if (p == &ahead)
        return "ahead";
    if (p == stops)
        return "stops";
    if (p == eye_pts)
        return "eyepts";
    if (p == look_pts)
        return "lookpts";
    if (p == ahead_pts)
        return "aheadpts";
    for (i = 0; i < NCOLL; i++)
        if (p == &colls[i]) {
            sprintf(b, "c%d", i);
            return b;
        }
    for (i = 0; i < nalloc; i++)
        if (p == allocs[i]) {
            sprintf(b, "m%d", i);
            return b;
        }
    return "?";
}

static uint32_t bits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static const char *fx(float f)
{
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08x", (unsigned)u);
    return b;
}

static float fh(const char *s)
{
    uint32_t u = (uint32_t)strtoul(s, NULL, 16);
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool_)
{
    unsigned char *a;
    int csize = size;

    pool_used = (pool_used + 15) & ~(size_t)15;
    a = pool + pool_used;
    if (size < 0)
        size = 0;
    pool_used += (size_t)size;
    if (pool_used > POOL || nalloc >= NALLOC) {
        fprintf(stderr, "pool exhausted\n");
        exit(2);
    }
    fill(a, (size_t)size);
    allocs[nalloc] = a;
    // The console's sizes: the host's pointers are wider.
    if (!strcmp(name, "PreviewPause") && size == (int)sizeof(PreviewPause))
        csize = 16;
    if (!strcmp(name, "PreviewPausePoint")
        && size == (int)sizeof(PreviewPausePoint))
        csize = 32;
    printf("  malloc %s %d %d %d -> m%d\n", name, flags, pool_, csize,
           nalloc);
    nalloc++;
    return a;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

int32_t collision_is_two_car_collision(Collision *c)
{
    int i = (int)(c - colls);
    int r = (i >= 0 && i < NCOLL) ? colltwo[i] : 0;

    printf("  two %s -> %d\n", nm(c), r);
    return r;
}

void topology_set_interest_bbox3(TopologyCoordinate *t, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  bbox %s %s %s %s %s %s\n", nm(t), fx(pos->x), fx(pos->y),
           fx(pos->z), fx(r), nm(vel));
}

int topology_segment_intersects(TopologyCoordinate *t, const bVector3 *a,
                                const bVector3 *b, float r)
{
    int ans = itopo < ntopo ? topo[itopo] : 0;

    itopo++;
    printf("  seg %s %s %s %s %s %s %s %s -> %d\n", nm(t), fx(a->x),
           fx(a->y), fx(a->z), fx(b->x), fx(b->y), fx(b->z), fx(r), ans);
    return ans;
}

void preview_down_sample_xy(Spline *s, float fraction, const float *st,
                            int32_t numStops)
{
    int i;

    printf("  down %s %s %s %d", nm(s), fx(fraction), nm(st), (int)numStops);
    for (i = 0; i < numStops && i < NSTOPS; i++)
        printf(" %s", fx(st[i]));
    printf("\n");
}

// ------------------------------------------------------------ the world

static void reset(void)
{
    int i;

    fill(&mgr, sizeof mgr);
    fill(cops, sizeof cops);
    fill(cars, sizeof cars);
    fill(rcars, sizeof rcars);
    fill(rbs, sizeof rbs);
    fill(purs, sizeof purs);
    fill(spikes, sizeof spikes);
    fill(&heli, sizeof heli);
    fill(&world, sizeof world);
    fill(colls, sizeof colls);
    fill(&eye, sizeof eye);
    fill(&look, sizeof look);
    fill(&ahead, sizeof ahead);
    fill(eye_pts, sizeof eye_pts);
    fill(look_pts, sizeof look_pts);
    fill(ahead_pts, sizeof ahead_pts);
    fill(&lin_e, sizeof lin_e);
    fill(&lin_l, sizeof lin_l);
    mgr.nNumCops = 0;
    for (i = 0; i < COPMANAGER_MAX_COPS; i++)
        mgr.Cops[i] = NULL;
    mgr.PursuitList.Next = mgr.PursuitList.Prev = &mgr.PursuitList;
    mgr.SpikeStripList.Next = mgr.SpikeStripList.Prev = &mgr.SpikeStripList;
    world.CollisionList.next = world.CollisionList.prev =
        &world.CollisionList;
    world.Helicopter = NULL;
    world.AICarPos = 0;
    world.CopCarPos = 0;
    for (i = 0; i < WORLD_MAX_CARS; i++)
        world.CarTable[i] = NULL;
    pCopManager = NULL;
    pCurrentWorld = &world;
    pCurrentRace = (Race *)(void *)race_buf;
    npur = nspike = ncoll = 0;
    ntopo = itopo = 0;
    pool_used = 0;
    nalloc = 0;
}

static void vec4(bVector3 *v, char **t)
{
    v->x = fh(t[0]);
    v->y = fh(t[1]);
    v->z = fh(t[2]);
    v->pad = fh(t[3]);
}

static void set_spline(Spline *s, bVector3 *pts, char **t)
{
    int n = atoi(t[1]), i;

    s->ControlPointBufferSize = n;
    s->NumControlPoints = n;
    s->Type = (SplineType)atoi(t[0]);
    s->pControlPoints = pts;
    s->pControlPointArray = NULL;
    s->Dirty = 1;
    s->TableSize = 16384;
    s->CalLevel = 0;
    s->Length = 0.0f;
    s->CalTableStep = 0.0f;
    s->CalTableSize = 0;
    s->pCalTable = NULL;
    for (i = 0; i < n; i++)
        vec4(&pts[i], t + 2 + 4 * i);
}

static void dump_spline(const char *tag, const Spline *s)
{
    printf("  %s n %d buf %d type %d dirty %d pts %s arr %s\n", tag,
           (int)s->NumControlPoints, (int)s->ControlPointBufferSize,
           (int)s->Type, (int)s->Dirty, nm(s->pControlPoints),
           nm(s->pControlPointArray));
}

static void find(int maxStops)
{
    int i;

    fill(stops, sizeof stops);
    ahead.ControlPointBufferSize = NPTS;
    ahead.NumControlPoints = 0;
    ahead.Type = SPLINE_EXTRAPOLATE;
    ahead.pControlPoints = ahead_pts;
    ahead.pControlPointArray = NULL;
    ahead.Dirty = 0;
    ahead.TableSize = 16384;
    ahead.pCalTable = NULL;
    printf("  count %d\n",
           (int)preview_route_find_stops(&route, &tc, &eye, &look, &ahead,
                                         &lin_e, &lin_l, stops, maxStops));
    printf("  stops");
    for (i = 0; i < NSTOPS; i++)
        printf(" %s", fx(stops[i]));
    printf("\n");
    dump_spline("eye", &eye);
    dump_spline("look", &look);
    dump_spline("ahead", &ahead);
    for (i = 0; i < ahead.NumControlPoints && i < NPTS; i++)
        printf("  ahead %d %s %s %s\n", i, fx(ahead.pControlPoints[i].x),
               fx(ahead.pControlPoints[i].y), fx(ahead.pControlPoints[i].z));
}

static void op(char **t, int n, const char *line)
{
    const char *c = t[0];

    if (!strcmp(c, "B")) {
        printf("B %s\n", t[1]);
        reset();
    } else if (!strcmp(c, "mgr")) {
        pCopManager = atoi(t[1]) ? &mgr : NULL;
    } else if (!strcmp(c, "ncops")) {
        mgr.nNumCops = atoi(t[1]);
    } else if (!strcmp(c, "slot")) {
        int o = atoi(t[2]);

        mgr.Cops[atoi(t[1])] = o < 0 ? NULL : &cops[o];
    } else if (!strcmp(c, "cop")) {
        tCop *cp = &cops[atoi(t[1])];

        cp->pMyCar = &cars[atoi(t[2])];
        cp->DesiredLogicState = (eLogicState)atoi(t[3]);
    } else if (!strcmp(c, "car")) {
        int k = atoi(t[1]);
        Car *car = &cars[k];

        car->pRacingCar = &rcars[k];
        vec4(&car->State.GeometryPosition, t + 2);
        vec4(&car->State.Position, t + 6);
        car->State.nWheelsTouchingGround = atoi(t[10]);
        rcars[k].RacePosition = (int8_t)atoi(t[11]);
    } else if (!strcmp(c, "rb")) {
        tRoadBlock *rb = &rbs[atoi(t[1])];
        int k;

        for (k = 0; k < 2; k++) {
            int o = atoi(t[2 + k]);

            rb->cops[k] = o < 0 ? NULL : (struct stAICop *)(void *)&cops[o];
        }
        rb->nIndexIntoLoadedData = atoi(t[4]);
    } else if (!strcmp(c, "pur")) {
        tPursuit *p = &purs[npur++];
        int r = atoi(t[1]);

        p->pRoadBlock = r < 0 ? NULL : &rbs[r];
        p->Node.Next = &mgr.PursuitList;
        p->Node.Prev = mgr.PursuitList.Prev;
        mgr.PursuitList.Prev->Next = &p->Node;
        mgr.PursuitList.Prev = &p->Node;
    } else if (!strcmp(c, "spike")) {
        tSpikeStrip *s = &spikes[nspike++];
        int k, m = atoi(t[2]);

        s->nRoadBlockID = atoi(t[1]);
        s->nNumElements = m;
        for (k = 0; k < m; k++) {
            bVector4 *v = &s->Elements[k].Base.Matrix.v3;

            v->x = fh(t[3 + 4 * k]);
            v->y = fh(t[4 + 4 * k]);
            v->z = fh(t[5 + 4 * k]);
            v->w = fh(t[6 + 4 * k]);
        }
        s->Node.Next = &mgr.SpikeStripList;
        s->Node.Prev = mgr.SpikeStripList.Prev;
        mgr.SpikeStripList.Prev->Next = &s->Node;
        mgr.SpikeStripList.Prev = &s->Node;
    } else if (!strcmp(c, "heli")) {
        if (atoi(t[1])) {
            world.Helicopter = &heli;
            heli.Plan = (ChopperPlan)atoi(t[2]);
            vec4(&heli.CurrentPos, t + 3);
        } else {
            world.Helicopter = NULL;
        }
    } else if (!strcmp(c, "world")) {
        int k;

        world.AICarPos = atoi(t[1]);
        world.CopCarPos = atoi(t[2]);
        for (k = 0; k < WORLD_MAX_CARS; k++) {
            int o = atoi(t[3 + k]);

            world.CarTable[k] = o < 0 ? NULL : &cars[o];
        }
    } else if (!strcmp(c, "coll")) {
        Collision *cl = &colls[ncoll];
        Collision *head = (Collision *)(void *)&world.CollisionList;
        Collision *last = (Collision *)world.CollisionList.prev;

        vec4(&cl->CurrentContactPoint, t + 1);
        colltwo[ncoll] = atoi(t[5]);
        ncoll++;
        cl->Link.next = head;
        cl->Link.prev = last;
        if (last == head)
            world.CollisionList.next = cl;
        else
            last->Link.next = cl;
        world.CollisionList.prev = cl;
    } else if (!strcmp(c, "topo")) {
        int k;

        ntopo = 0;
        itopo = 0;
        for (k = 1; k < n && ntopo < NTOPO; k++)
            topo[ntopo++] = atoi(t[k]);
    } else if (!strcmp(c, "eye")) {
        set_spline(&eye, eye_pts, t + 1);
    } else if (!strcmp(c, "look")) {
        set_spline(&look, look_pts, t + 1);
    } else if (!strcmp(c, "lin")) {
        Linear *l = t[1][0] == 'E' ? &lin_e : &lin_l;

        l->m = fh(t[2]);
        l->b = fh(t[3]);
    } else if (!strcmp(c, "find")) {
        printf("> %s\n", line);
        find(atoi(t[1]));
    } else if (!strcmp(c, "appr")) {
        bVector3 p;

        printf("> %s\n", line);
        vec4(&p, t + 3);
        printf("  appr %s\n", fx(spline_find_approach_param(&eye, &p,
                                                           fh(t[1]),
                                                           fh(t[2]))));
    } else if (!strcmp(c, "cosine")) {
        bVector3 p;

        printf("> %s\n", line);
        vec4(&p, t + 2);
        printf("  cos %s\n", fx(spline_approach_cosine(&eye, &p, fh(t[1]))));
    } else if (!strcmp(c, "inv")) {
        Linear l;

        printf("> %s\n", line);
        l.m = fh(t[1]);
        l.b = fh(t[2]);
        printf("  inv %s\n", fx(linear_get_inverse(&l, fh(t[3]))));
    } else if (!strcmp(c, "block")) {
        bVector3 a, b;

        printf("> %s\n", line);
        vec4(&a, t + 1);
        vec4(&b, t + 5);
        printf("  block %d\n", (int)topology_segment_blocked(&tc, &a, &b));
    } else if (!strcmp(c, "centre")) {
        bVector3 o;

        printf("> %s\n", line);
        tspikestrip_get_centre(&spikes[atoi(t[1])], &o);
        printf("  centre %s %s %s\n", fx(o.x), fx(o.y), fx(o.z));
    } else {
        fprintf(stderr, "bad op %s\n", c);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[65536];
    static char copy[65536];
    static char *tok[4096];
    FILE *f;

    if (argc < 2) {
        fprintf(stderr, "usage: previewstops_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f)) {
        int n = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        strcpy(copy, line);
        for (p = strtok(line, " "); p != NULL && n < 4095;
             p = strtok(NULL, " "))
            tok[n++] = p;
        tok[n] = NULL;
        op(tok, n, copy);
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
