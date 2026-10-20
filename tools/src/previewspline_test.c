// Host harness for 3DS Files/source/previewspline.c: PreviewRoute::
// MakeSplines and the free functions it calls. Runs the op script
// tools/previewspline_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// The harness owns the route, its route points and their TrackRoutePoints,
// the four splines, the Linear, the stops, a Graph and its knees, and
// printing stand-ins for bMalloc (a patterned arena), bFree and the
// TopologyCoordinate calls: SetInterestBBox, GetElevation (answers from a
// scripted list) and ConstrainToTopology's member (moves `to` and answers
// from a scripted list). zonecam.c's ConstrainToTopology, previewroute.c's
// GetPosition, trackroute.c, spline.c, graph.c and average.c are the
// port's own.
//
// Every block, route point and spline header starts as 0xa5 bytes, and the
// arena's first block starts 16 bytes in, as the model's does, so a read
// off either end of a buffer reads the same bytes on both sides. A float
// prints as its bits, every NaN as "nan", and a pointer by what it points
// at. A spline's points print with the slot either side of them. After
// MakeSplines they print without the pad lanes: retail's walk leaves stack
// words there.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "average.h"
#include "bmem.h"
#include "car.h"
#include "graph.h"
#include "playerzone.h"
#include "previewroute.h"
#include "previewspline.h"
#include "spline.h"
#include "topology.h"
#include "trackroute.h"
#include "zonecam.h"

// What the linked modules reach for and nothing here calls.
int32_t WorldTimer;
int32_t WorldLoopCounter;
float WorldTimeElapsed = 1.0f / 30.0f;
float RealTimeElapsed = 1.0f / 30.0f;
int32_t SoundEnabled = 1;
void (*gRadialBlurOffFn)(int32_t view);
void (*gRadialBlurAlphaFn)(int32_t view, float from, float to);

#define NSPL 4
#define NPTS 160
#define NKNEE 16
#define NSTOP 8
#define ARENA_SIZE 0x80000
#define ARENA_GUARD 16
#define NBLOCK 512
#define PAT 0xa5

static TrackRoutePoint trps[NPTS];
static PreviewRoutePoint rpts[NPTS];
static PreviewRoute route;
static TopologyCoordinate tc;
static Spline spl[NSPL];
static Linear lin;
static float stops[NSTOP];
static bVector2 knees[NKNEE];
static Graph graph;

static unsigned char arena[ARENA_SIZE] __attribute__((aligned(16)));
static size_t arena_used;
static void *blocks[NBLOCK];
static int nblocks;

static uint32_t elevs[64];
static int nelev, ielev;
static struct { int r; uint32_t d[3]; } cons[64];
static int ncons, icons;

static int block_index(const void *p)
{
    int i;

    for (i = nblocks - 1; i >= 0; i--)
        if (blocks[i] == p)
            return i;
    return -1;
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if ((i = block_index(p)) >= 0) {
        sprintf(b, "m%d", i);
        return b;
    }
    if (p == 0)
        return "null";
    if (p == &tc)
        return "tc";
    for (i = 0; i < NSPL; i++) {
        if (p == &spl[i]) {
            sprintf(b, "s%d", i);
            return b;
        }
    }
    sprintf(b, "?%08lx", (unsigned long)(uint32_t)(uintptr_t)p);
    return b;
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
    static char buf[32][12];
    static int slot;
    char *b = buf[slot++ & 31];
    uint32_t u = bits(f);

    if ((u & 0x7f800000u) == 0x7f800000u && (u & 0x7fffffu))
        return "nan";
    sprintf(b, "%08lx", (unsigned long)u);
    return b;
}

static const char *v3(const bVector3 *v)
{
    static char buf[8][40];
    static int slot;
    char *b = buf[slot++ & 7];

    sprintf(b, "%s %s %s", fx(v->x), fx(v->y), fx(v->z));
    return b;
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    size_t off = (arena_used + 15) & ~(size_t)15;
    void *p = arena + off;

    arena_used = off + (size_t)size;
    if (arena_used > ARENA_SIZE || nblocks == NBLOCK) {
        fprintf(stderr, "arena full\n");
        exit(2);
    }
    blocks[nblocks] = p;
    printf("  malloc %d %s %d %d -> m%d\n", size, name, flags, pool, nblocks);
    nblocks++;
    return p;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

void topology_set_interest_bbox3(TopologyCoordinate *t, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    printf("  bbox %s pos %s r %s vel %s\n", nm(t), v3(pos), fx(r),
           vel != NULL ? v3(vel) : "null");
}

float topology_get_elevation(TopologyCoordinate *t, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    float v = from_bits(elevs[ielev++ % nelev]);

    printf("  elev %s pt %s args %d%d%d -> %s\n", nm(t), v3(pt),
           terrain != NULL, normal != NULL, found != NULL, fx(v));
    return v;
}

int topology_constrain(TopologyCoordinate *t, int type, int twoSided,
                       const bVector3 *from, bVector3 *to, float dist,
                       float lift)
{
    int k = icons++ % ncons;

    printf("  constrain %s type %d two %d from %s to %s dist %s lift %s"
           " -> %d\n", nm(t), type, twoSided, v3(from), v3(to), fx(dist),
           fx(lift), cons[k].r);
    to->x = to->x + from_bits(cons[k].d[0]);
    to->y = to->y + from_bits(cons[k].d[1]);
    to->z = to->z + from_bits(cons[k].d[2]);
    return cons[k].r;
}

// What the linked modules call and MakeSplines never does.
static void unreached(const char *what)
{
    fprintf(stderr, "unreached: %s\n", what);
    exit(3);
}

void topology_init(TopologyCoordinate *t)
{
    (void)t;
    unreached("topology_init");
}

void topology_destroy(TopologyCoordinate *t)
{
    (void)t;
    unreached("topology_destroy");
}

TrackRoute *car_get_route(Car *c, int find)
{
    (void)c;
    (void)find;
    unreached("car_get_route");
    return NULL;
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    (void)c;
    (void)find;
    unreached("car_get_route_point");
    return NULL;
}

void player_update_zone_sound(struct Player *p, float muffle, float volume,
                              uint16_t azimuth, float pitch)
{
    (void)p;
    (void)muffle;
    (void)volume;
    (void)azimuth;
    (void)pitch;
    unreached("player_update_zone_sound");
}

// ------------------------------------------------------------ the dumps

static void pspline(int j, int lanes)
{
    const Spline *s = &spl[j];
    int i;

    printf("  s%d buf %ld n %ld type %ld pts %s arr %s dirty %ld tab %ld"
           " len %s cal %s\n", j, (long)s->ControlPointBufferSize,
           (long)s->NumControlPoints, (long)(int32_t)s->Type, nm(s->pControlPoints),
           nm(s->pControlPointArray), (long)s->Dirty, (long)s->TableSize,
           fx(s->Length), nm(s->pCalTable));
    if (block_index(s->pControlPoints) < 0 || s->NumControlPoints < 0
        || s->NumControlPoints > 1024)
        return;
    // The points and the slot either side, so a write off either end shows.
    for (i = -1; i <= s->NumControlPoints; i++) {
        const bVector3 *p = &s->pControlPoints[i];

        if (lanes == 4)
            printf("    s%d %d %s %s\n", j, i, v3(p), fx(p->pad));
        else
            printf("    s%d %d %s\n", j, i, v3(p));
    }
}

static void reset(void)
{
    memset(trps, PAT, sizeof trps);
    memset(rpts, PAT, sizeof rpts);
    memset(&route, PAT, sizeof route);
    memset(spl, PAT, sizeof spl);
    memset(&lin, PAT, sizeof lin);
    memset(stops, PAT, sizeof stops);
    memset(knees, PAT, sizeof knees);
    memset(&graph, PAT, sizeof graph);
    memset(arena, PAT, sizeof arena);
    arena_used = ARENA_GUARD;
    nblocks = 0;
    elevs[0] = 0;
    nelev = 1;
    ielev = 0;
    memset(cons, 0, sizeof cons);
    ncons = 1;
    icons = 0;
}

static char *tok(void)
{
    char *t = strtok(NULL, " \t\r\n");

    if (t == NULL) {
        fprintf(stderr, "short line\n");
        exit(2);
    }
    return t;
}

static int itok(void) { return atoi(tok()); }
static uint32_t xtok(void) { return (uint32_t)strtoul(tok(), NULL, 16); }
static float ftok(void) { return from_bits(xtok()); }

static void read_vec(bVector3 *v)
{
    v->x = ftok();
    v->y = ftok();
    v->z = ftok();
    v->pad = ftok();
}

int main(int argc, char **argv)
{
    static char line[65536];
    FILE *fp;

    if (argc != 2) {
        fprintf(stderr, "usage: previewspline_test SCRIPT\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }

    while (fgets(line, sizeof line, fp) != NULL) {
        char echo[64];
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        snprintf(echo, sizeof echo, "%.40s", line);
        t = strtok(line, " \t");
        if (t == NULL)
            continue;
        if (!strcmp(t, "B")) {
            printf("B %d\n", itok());
            reset();
            continue;
        }
        if (strchr("tpEXcl", t[0]) == NULL || t[1])
            printf("> %s\n", echo);

        if (!strcmp(t, "t")) {
            TrackRoutePoint *q = &trps[itok()];

            q->Position.x = ftok();
            q->Position.y = ftok();
            q->Elevation = ftok();
            q->Direction.x = ftok();
            q->Direction.y = ftok();
            q->BankSlope = ftok();
            q->ForwardSlope = ftok();
        } else if (!strcmp(t, "p")) {
            PreviewRoutePoint *q = &rpts[itok()];

            q->pPoint = &trps[itok()];
            q->fLength = ftok();
            q->fOffset = ftok();
            q->fRouteGap = ftok();
        } else if (!strcmp(t, "r")) {
            route.nPoints = itok();
            route.fDistance = ftok();
            route.fOffset = ftok();
            route.pPoints = itok() ? NULL : rpts;
        } else if (!strcmp(t, "E")) {
            int i;

            nelev = itok();
            for (i = 0; i < nelev; i++)
                elevs[i] = xtok();
            ielev = 0;
        } else if (!strcmp(t, "X")) {
            int i;

            ncons = itok();
            for (i = 0; i < ncons; i++) {
                cons[i].r = itok();
                cons[i].d[0] = xtok();
                cons[i].d[1] = xtok();
                cons[i].d[2] = xtok();
            }
            icons = 0;
        } else if (!strcmp(t, "l")) {
            lin.m = ftok();
            lin.b = ftok();
        } else if (!strcmp(t, "a")) {
            int j = itok(), type = itok(), buf = itok();

            memset(&spl[j], PAT, sizeof spl[j]);
            spline_init_alloc(&spl[j], (SplineType)type, buf, 16384);
            pspline(j, 4);
        } else if (!strcmp(t, "c")) {
            Spline *s = &spl[itok()];
            int n = itok(), i;

            for (i = 0; i < n; i++)
                read_vec(&s->pControlPoints[i]);
            s->NumControlPoints = n;
        } else if (!strcmp(t, "y")) {
            Spline *s = &spl[itok()];

            s->Type = (SplineType)itok();
        } else if (!strcmp(t, "M")) {
            int mask = itok(), j;

            preview_route_make_splines(&route, &tc,
                                       mask & 1 ? &spl[0] : NULL,
                                       mask & 2 ? &spl[1] : NULL,
                                       mask & 4 ? &spl[2] : NULL,
                                       mask & 8 ? &lin : NULL);
            printf("  route n %ld dist %s off %s\n", (long)route.nPoints,
                   fx(route.fDistance), fx(route.fOffset));
            for (j = 0; j < 3; j++)
                pspline(j, 3);
        } else if (!strcmp(t, "H")) {
            int r = itok(), s = itok(), i = itok();
            float gap = ftok();

            preview_enforce_height_gap_at(&spl[r], &spl[s], i, gap);
            pspline(s, 4);
        } else if (!strcmp(t, "G")) {
            int r = itok(), s = itok(), i = itok();

            preview_enforce_height_gap(&spl[r], &spl[s], i);
            pspline(s, 4);
        } else if (!strcmp(t, "D")) {
            int j = itok();
            float frac = ftok();
            int null = itok(), n = itok(), i;

            for (i = 0; i < n && i < NSTOP; i++)
                stops[i] = ftok();
            preview_down_sample_xy(&spl[j], frac, null ? NULL : stops, n);
            pspline(j, 4);
        } else if (!strcmp(t, "S")) {
            int j = itok();

            preview_enforce_maximum_slope(&spl[j], ftok());
            pspline(j, 4);
        } else if (!strcmp(t, "W")) {
            int j = itok(), i = itok();
            bVector3 v;

            read_vec(&v);
            spline_set_control_point(&spl[j], i, &v);
            pspline(j, 4);
        } else if (!strcmp(t, "K")) {
            float from = ftok(), to = ftok(), step = ftok();

            printf("  seek %s\n", fx(preview_linear_seek(from, to, step)));
        } else if (!strcmp(t, "I")) {
            int n = itok(), m, i;

            for (i = 0; i < n; i++) {
                knees[i].x = ftok();
                knees[i].y = ftok();
            }
            graph_init(&graph, knees, n);
            m = itok();
            for (i = 0; i < m; i++) {
                float y = ftok();

                printf("  inv %s -> %s\n", fx(y),
                       fx(graph_get_inverse(&graph, y)));
            }
        } else if (!strcmp(t, "d")) {
            pspline(itok(), 4);
        } else {
            fprintf(stderr, "bad op %s\n", t);
            return 2;
        }
    }
    fclose(fp);
    return 0;
}
