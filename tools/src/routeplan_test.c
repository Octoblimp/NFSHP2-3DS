// routeplan_test -- tools/routeplan_check.py's harness.
//
// Runs airouteplan.c's FindNearbySignpost, FindPointsToTarget,
// FindRoutesToTarget and ReturnToLastBranch, with trackroute.c under them,
// over the checker's script. The routes, the signposts and the two deques
// are this file's. A route prints as rK, a point as rK.pJ, NULL as 0, and
// anything else as "?".

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "airouteplan.h"
#include "trackroute.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

#define NROUTES 24
#define NSIGNS  256
#define NOUT    16
#define MAXT    64

static TrackRoute        routes[NROUTES];
static Signpost          signs[NSIGNS];
static RoutePlanRoutes   rq;
static RoutePlanBranches bq;

static const char *rname(const TrackRoute *r)
{
    static char buf[4][16];
    static int k;
    int i;

    if (r == NULL)
        return "0";
    for (i = 0; i < NROUTES; i++)
        if (r == &routes[i]) {
            k = (k + 1) & 3;
            snprintf(buf[k], sizeof buf[k], "r%d", i);
            return buf[k];
        }
    return "?";
}

static const char *pname(const TrackRoutePoint *p)
{
    static char buf[4][24];
    static int k;
    int i;

    if (p == NULL)
        return "0";
    for (i = 0; i < NROUTES; i++) {
        const char *t = (const char *)routes[i].TrackRoutePointTable;
        const char *c = (const char *)p;

        if (c >= t && c < t + sizeof routes[i].TrackRoutePointTable
            && (size_t)(c - t) % sizeof(TrackRoutePoint) == 0) {
            k = (k + 1) & 3;
            snprintf(buf[k], sizeof buf[k], "r%d.p%d", i,
                     (int)((size_t)(c - t) / sizeof(TrackRoutePoint)));
            return buf[k];
        }
    }
    return "?";
}

static TrackRoute *route_of(int v)
{
    return v < 0 ? NULL : &routes[v];
}

static TrackRoutePoint *point_of(int v)
{
    return v < 0 ? NULL : &routes[v / 1024].TrackRoutePointTable[v % 1024];
}

static void print_rq(void)
{
    int i;

    printf("  rq %d %d %d", rq.Front, rq.Back, rq.Full);
    for (i = 0; i < ROUTEPLAN_RING; i++)
        printf(" %s", rname(rq.Item[i]));
    printf("\n");
}

static void print_bq(void)
{
    int i;

    printf("  bq %d %d %d", bq.Front, bq.Back, bq.Full);
    for (i = 0; i < ROUTEPLAN_RING; i++)
        printf(" %s,%s", rname(bq.Item[i].Route), pname(bq.Item[i].Point));
    printf("\n");
}

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

static int I(const char *s)
{
    return (int)strtol(s, NULL, 10);
}

static void run(char **t, int n)
{
    const char *op = t[0];
    int i;

    (void)n;
    printf("%s\n", op);
    if (strcmp(op, "clr") == 0) {
        int k;

        memset(routes, 0, sizeof routes);
        memset(signs, 0, sizeof signs);
        for (k = 0; k < NROUTES; k++)
            for (i = 0; i < I(t[1]); i++)
                routes[k].TrackRoutePointTable[i].Bits = 0xff;
    } else if (strcmp(op, "rt") == 0) {
        routes[I(t[1])].NumPoints = I(t[2]);
    } else if (strcmp(op, "pb") == 0) {
        routes[I(t[1])].TrackRoutePointTable[I(t[2])].Bits =
            (uint32_t)strtoul(t[3], NULL, 16);
    } else if (strcmp(op, "sg") == 0) {
        Signpost *s = &signs[I(t[1])];

        s->NewRoute = (uint8_t)I(t[2]);
        s->Flags = (uint8_t)I(t[3]);
        s->NewPoint = (uint16_t)I(t[4]);
    } else if (strcmp(op, "rq") == 0) {
        rq.Front = I(t[1]);
        rq.Back = I(t[2]);
        rq.Full = I(t[3]);
        for (i = 0; i < ROUTEPLAN_RING; i++)
            rq.Item[i] = route_of(I(t[4 + i]));
    } else if (strcmp(op, "bq") == 0) {
        bq.Front = I(t[1]);
        bq.Back = I(t[2]);
        bq.Full = I(t[3]);
        for (i = 0; i < ROUTEPLAN_RING; i++) {
            bq.Item[i].Route = route_of(I(t[4 + 2 * i]));
            bq.Item[i].Point = point_of(I(t[5 + 2 * i]));
        }
    } else if (strcmp(op, "nearby") == 0) {
        NearestRoutePointInfo info;
        int32_t r;

        info.Route = route_of(I(t[1]));
        info.Point = point_of(I(t[2]));
        r = ai_find_nearby_signpost(&info, I(t[3]));
        printf("  -> %d %s %s\n", r, rname(info.Route), pname(info.Point));
    } else if (strcmp(op, "points") == 0) {
        NearestRoutePointInfo s, g, out[NOUT];
        uint32_t count = (uint32_t)I(t[5]), r;

        memset(out, 0, sizeof out);
        s.Route = route_of(I(t[1]));
        s.Point = point_of(I(t[2]));
        g.Route = route_of(I(t[3]));
        g.Point = point_of(I(t[4]));
        r = ai_find_points_to_target(&s, &g, out, count, I(t[6]), I(t[7]));
        printf("  -> %u", r);
        for (i = 0; i < NOUT; i++)
            printf(" %s,%s", rname(out[i].Route), pname(out[i].Point));
        printf("\n");
    } else if (strcmp(op, "routes") == 0) {
        NearestRoutePointInfo s;
        int32_t r;

        s.Route = route_of(I(t[1]));
        s.Point = point_of(I(t[2]));
        r = ai_find_routes_to_target(&s, route_of(I(t[3])), &rq, I(t[4]),
                                     I(t[5]));
        printf("  -> %d\n", r);
        print_rq();
    } else if (strcmp(op, "rtlb") == 0) {
        NearestRoutePointInfo info;
        int32_t r;

        info.Route = route_of(I(t[1]));
        info.Point = point_of(I(t[2]));
        r = ai_return_to_last_branch(&info, &bq, &rq);
        printf("  -> %d %s %s\n", r, rname(info.Route), pname(info.Point));
        print_bq();
        print_rq();
    } else {
        fprintf(stderr, "bad op %s\n", op);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[8192];
    char *t[MAXT];
    FILE *f;
    int k;

    if (argc != 2) {
        fprintf(stderr, "usage: routeplan_test script\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    SignpostArray = signs;
    NumSignposts = NSIGNS;
    for (k = 0; k < NROUTES; k++)
        TheTrackRouteManager.pTrackRoutes[k] = &routes[k];
    while (fgets(line, sizeof line, f) != NULL) {
        char *e = line + strlen(line);

        while (e > line && (e[-1] == '\n' || e[-1] == '\r'))
            *--e = 0;
        if (line[0] == 0)
            continue;
        run(t, split(line, t));
    }
    fclose(f);
    return 0;
}
