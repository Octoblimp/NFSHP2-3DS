// Host harness for 3DS Files/source/previewroute.c, the jump cam's route,
// and playerzone.c's IsJumpCamAvailable. Runs the op script
// tools/prevroute_check.py writes and prints the transcript it diffs
// against the retail image, run in mipsemu over the same script.
//
// The harness owns what the two files reach outside themselves: bMalloc
// and bFree (a pool of 0xa5-filled blocks, each call printed), the car's
// route and route point (the script's), CleanUpJumpCam (printed, and the
// route freed as retail's destructor frees it), TheRaceParameters and
// CurrentTrackInfo. trackroute.c is the port's own.
//
// A float prints as its bits, every NaN as "nan", and a pointer by what it
// points at.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "player.h"
#include "playerinit.h"
#include "playerzone.h"
#include "previewroute.h"
#include "race.h"
#include "track.h"
#include "trackroute.h"

#define NROUTES 6
#define LINES   21
#define PAT     0xa5
#define POOL    (1 << 20)
#define NALLOC  8192

RaceParameters TheRaceParameters;
TrackInfo *CurrentTrackInfo;

static TrackRoute routes[NROUTES];
static TrackInfo trackinfo;
static CarTypeInfo cti;
static Car car;
static struct Player player;
static PreviewRoute pr;
static PreviewRoutePoint outp;
static TrackRoute *car_route;
static TrackRoutePoint *car_point;

static unsigned char pool[POOL] __attribute__((aligned(16)));
static size_t pool_used;
static struct {
    void *p;
    int size;
    int count;
} allocs[NALLOC];
static int nalloc;

static TrackRoute *cur_route;
static int cur_n;

static void fill(void *p, size_t n)
{
    memset(p, PAT, n);
}

static int is_pat(const void *p)
{
    uintptr_t v = (uintptr_t)p;
    size_t i;

    for (i = 0; i < sizeof v; i++)
        if (((v >> (8 * i)) & 0xff) != PAT)
            return 0;
    return 1;
}

static const char *nm(const void *p)
{
    static char buf[16][32];
    static int slot;
    char *b = buf[slot++ & 15];
    int i;

    if (p == NULL)
        return "null";
    if (is_pat(p))
        return "pat";
    if (p == &pr)
        return "pr";
    for (i = 0; i < NROUTES; i++) {
        const TrackRoute *r = &routes[i];

        if (p == r) {
            sprintf(b, "R%d", i);
            return b;
        }
        if ((const char *)p >= (const char *)r->TrackRoutePointTable
            && (const char *)p < (const char *)(r + 1)) {
            ptrdiff_t off = (const char *)p
                            - (const char *)r->TrackRoutePointTable;

            if (off % (ptrdiff_t)sizeof(TrackRoutePoint) == 0) {
                sprintf(b, "R%d:%d", i,
                        (int)(off / (ptrdiff_t)sizeof(TrackRoutePoint)));
                return b;
            }
        }
    }
    for (i = 0; i < nalloc; i++) {
        if (p == allocs[i].p) {
            sprintf(b, "A%d", i);
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

static const char *fx(float f)
{
    static char buf[16][12];
    static int slot;
    char *b = buf[slot++ & 15];
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

void *bMalloc(int size, const char *name, int line, int flags)
{
    unsigned char *a;
    char what[32];

    (void)flags;
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
    allocs[nalloc].p = a;
    allocs[nalloc].size = size;
    allocs[nalloc].count = 0;
    if (line == 1538) {
        allocs[nalloc].count = size / (int)sizeof(PreviewRoutePoint);
        sprintf(what, "pts %d", allocs[nalloc].count);
    } else if (line == 1245 && size == (int)sizeof(PreviewRoute)) {
        sprintf(what, "route");
    } else {
        sprintf(what, "size %d", size);
    }
    printf("  malloc A%d %s %d %s\n", nalloc, name, line, what);
    nalloc++;
    return a;
}

void bFree(void *p)
{
    printf("  free %s\n", nm(p));
}

TrackRoute *car_get_route(Car *c)
{
    (void)c;
    return car_route;
}

TrackRoutePoint *car_get_route_point(Car *c)
{
    (void)c;
    return car_point;
}

void player_clean_up_jump_cam(struct Player *p)
{
    printf("  cleanup %s\n", nm(p->pJumpCamRoute));
    if (p->pJumpCamRoute != NULL)
        preview_route_delete(p->pJumpCamRoute);
    p->pJumpCamRoute = NULL;
}

// ------------------------------------------------------------ the dumps

static int count_of(const void *p)
{
    int i;

    for (i = 0; i < nalloc; i++)
        if (p == allocs[i].p)
            return allocs[i].count;
    return 0;
}

static void dump_point(const char *tag, const PreviewRoutePoint *q)
{
    printf("    %s %s %s len %s off %s line %d gap %s\n", tag, nm(q->pRoute),
           nm(q->pPoint), fx(q->fLength), fx(q->fOffset), (int)q->nLine,
           fx(q->fRouteGap));
}

static void dump_pr(const PreviewRoute *r)
{
    int i, n;

    printf("  %s n %d dir %s %s dist %s off %s pts %s\n", nm(r),
           (int)r->nPoints, fx(r->vTrackDirection.x),
           fx(r->vTrackDirection.y), fx(r->fDistance), fx(r->fOffset),
           nm(r->pPoints));
    n = count_of(r->pPoints);
    if (n > 120)
        n = 120;
    for (i = 0; i < n; i++) {
        char tag[8];

        sprintf(tag, "%d", i);
        dump_point(tag, &r->pPoints[i]);
    }
}

// ------------------------------------------------------------ the world

static void reset(void)
{
    pool_used = 0;
    nalloc = 0;
    memset(&TheTrackRouteManager, 0, sizeof TheTrackRouteManager);
    TheRaceParameters.Point2Point = 0;
    fill(&trackinfo, sizeof trackinfo);
    trackinfo.SameAsTrackNumber = 0;
    CurrentTrackInfo = &trackinfo;
    fill(&player, sizeof player);
    player.MyCar = &car;
    player.pJumpCamRoute = NULL;
    fill(&car, sizeof car);
    fill(&cti, sizeof cti);
    car.pCarTypeInfo = &cti;
    car_route = NULL;
    car_point = NULL;
}

static TrackRoutePoint *point_of(const char *s)
{
    int k, j;

    if (strcmp(s, "-") == 0)
        return NULL;
    if (sscanf(s, "%d:%d", &k, &j) != 2) {
        fprintf(stderr, "bad point %s\n", s);
        exit(2);
    }
    return &routes[k].TrackRoutePointTable[j];
}

static int pr_ok(int need)
{
    return pr.pPoints != NULL && !is_pat(pr.pPoints)
           && need < count_of(pr.pPoints);
}

static void op(char **t, int n)
{
    char c = t[0][0];

    (void)n;
    if (c == 'G') {
        int k = atoi(t[1]), typ = atoi(t[2]), np = atoi(t[3]), i;
        TrackRoute *r = &routes[k];

        memset(r, 0, offsetof(TrackRoute, TrackRoutePointTable));
        r->Version = 1;
        r->RouteNumber = (int16_t)k;
        r->Type = typ;
        r->NumPoints = np;
        r->MaxPoints = np;
        r->BBoxMin.x = fh(t[4]);
        r->BBoxMin.y = fh(t[5]);
        r->BBoxMax.x = fh(t[6]);
        r->BBoxMax.y = fh(t[7]);
        for (i = 0; i < LINES; i++)
            r->DrivingLineInfoTable[i].Flags =
                (uint32_t)strtoul(t[8 + i], NULL, 16);
        if (typ == 0)
            TheTrackRouteManager.Racing[TheTrackRouteManager.NumRacing++] = r;
        else
            TheTrackRouteManager.Traffic[TheTrackRouteManager.NumTraffic++] =
                r;
        cur_route = r;
        cur_n = 0;
    } else if (c == 'P') {
        uint32_t w[28];
        int i;

        for (i = 0; i < 28; i++)
            w[i] = (uint32_t)strtoul(t[1 + i], NULL, 16);
        memcpy(&cur_route->TrackRoutePointTable[cur_n++], w, sizeof w);
    } else if (c == 'K') {
        TheRaceParameters.Point2Point = atoi(t[1]);
    } else if (c == 'S') {
        trackinfo.SameAsTrackNumber = (int8_t)atoi(t[1]);
    } else if (c == 'C') {
        int k;

        car.State.Position.x = fh(t[1]);
        car.State.Position.y = fh(t[2]);
        car.State.Position.z = fh(t[3]);
        car.TheTrackPathCoordinate.PathDirection.x = fh(t[4]);
        car.TheTrackPathCoordinate.PathDirection.y = fh(t[5]);
        cti.CarClass = (int8_t)atoi(t[6]);
        k = atoi(t[7]);
        car_route = k >= 0 ? &routes[k] : NULL;
        car_point = point_of(t[8]);
    } else if (c == 'N') {
        fill(&pr, sizeof pr);
        preview_route_init(&pr, &car, fh(t[1]), fh(t[2]));
        dump_pr(&pr);
    } else if (c == 'D') {
        preview_route_destroy(&pr, 0);
        pr.pPoints = NULL;
        printf("  destroyed\n");
    } else if (c == 'J') {
        int got = player_is_jump_cam_available(&player);

        printf("  jump %d route %s\n", got, nm(player.pJumpCamRoute));
        if (player.pJumpCamRoute != NULL)
            dump_pr(player.pJumpCamRoute);
    } else if (c == 'Q') {
        bVector2 v;
        int got;

        if (!pr_ok(atoi(t[5]))) {
            printf("  skip\n");
            return;
        }
        v.x = fh(t[1]);
        v.y = fh(t[2]);
        got = preview_route_closest_point(&pr, &v, fh(t[3]), atoi(t[4]),
                                          atoi(t[5]), point_of(t[6]));
        printf("  closest %d\n", got);
        dump_pr(&pr);
    } else if (c == 'W') {
        bVector2 v;
        char pt[32];
        float d;

        v.x = fh(t[3]);
        v.y = fh(t[4]);
        snprintf(pt, sizeof pt, "%s:%s", t[1], t[2]);
        fill(&outp, sizeof outp);
        d = preview_route_closest_distance(&pr, &outp, &routes[atoi(t[1])],
                                           point_of(pt), &v, atoi(t[5]));
        printf("  dist %s\n", fx(d));
        dump_point("out", &outp);
    } else if (c == 'X') {
        int i = atoi(t[1]);
        float d;

        if (!pr_ok(i) || pr.pPoints[i - 1].pPoint == NULL
            || is_pat(pr.pPoints[i - 1].pPoint)) {
            printf("  skip\n");
            return;
        }
        d = preview_route_next_point(&pr, i, fh(t[2]), atoi(t[3]));
        printf("  next %s\n", fx(d));
        dump_pr(&pr);
    } else {
        fprintf(stderr, "bad op %s\n", t[0]);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    FILE *f;

    if (argc != 2) {
        fprintf(stderr, "usage: prevroute_test SCRIPT\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    while (fgets(line, sizeof line, f) != NULL) {
        char *t[64];
        int n = 0;
        char *s;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        if (line[0] == 'B') {
            printf("%s\n", line);
            reset();
            continue;
        }
        if (line[0] != 'G' && line[0] != 'P')
            printf("> %.48s\n", line);
        for (s = strtok(line, " "); s != NULL && n < 64; s = strtok(NULL, " "))
            t[n++] = s;
        op(t, n);
    }
    fclose(f);
    return 0;
}
