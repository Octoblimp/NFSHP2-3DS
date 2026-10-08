// Harness for tools/trackgraph_check.py: runs the checker's script on
// trackgraph.c -- tTrackGraph's constructor and destructor, UncloakAllEdges,
// the vertex and edge lookups, FindRoadBlock and FindSpeedTrap -- and on
// coputil.c's GetForwardTrackDistance and IsTeleportLocationClear, and
// prints what the model prints for the retail image. See the checker's
// docstring.
//
//     trackgraph_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "car.h"
#include "collision.h"
#include "collisionbody.h"
#include "copmanager.h"
#include "copmgr.h"
#include "coputil.h"
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

// ------------------------------------------- what trackgraph.c reaches

tCopManager *pCopManager;

#define NCARS     8
#define NSPOTS    64
#define MAX_POOLS 2048
#define MAX_INFOS 200000
#define MAX_G     1024

static uint8_t          mgr_token[16];
static World            world;
static Car             *cars[NCARS];
static int32_t          car_route[NCARS];
static int32_t          car_point[NCARS];
static tRoadBlock       rbs[NSPOTS];
static tSpeedTrap       sts[NSPOTS];
static int32_t          rb_has[NSPOTS];
static int32_t          st_has[NSPOTS];
static uint8_t          pool_tokens[MAX_POOLS][16];
static tTrackGraphInfo  info_arena[MAX_INFOS];
static tTrackGraph     *graphs[MAX_G];
static int              mallocs, pools, infos;

static uint8_t *blob;

// ------------------------------------------------------------ the names

static char symbuf[8][48];
static int  symnext;

// Every pointer the log prints, named by where it is: the cars, the spots,
// the pools, the infos, the graphs and their edges' lists.
static const char *sym(const void *p)
{
    char          *b = symbuf[symnext++ & 7];
    const uint8_t *u = (const uint8_t *)p;
    int            k;

    if (p == NULL)
        return "0";
    if ((uintptr_t)p == (uintptr_t)0xcdcdcdcdcdcdcdcdull)
        return "cd";
    if (p == mgr_token)
        return "M0";
    for (k = 0; k < NCARS; ++k)
        if (p == cars[k]) {
            snprintf(b, 48, "A%d", k);
            return b;
        }
    for (k = 0; k < NSPOTS; ++k) {
        if (p == &rbs[k]) {
            snprintf(b, 48, "RB%d", k);
            return b;
        }
        if (p == &sts[k]) {
            snprintf(b, 48, "ST%d", k);
            return b;
        }
    }
    if (u >= &pool_tokens[0][0] && u < &pool_tokens[0][0] + sizeof pool_tokens
        && (u - &pool_tokens[0][0]) % 16 == 0) {
        snprintf(b, 48, "pool%d", (int)((u - &pool_tokens[0][0]) / 16));
        return b;
    }
    if (u >= (const uint8_t *)info_arena
        && u < (const uint8_t *)&info_arena[MAX_INFOS]
        && (u - (const uint8_t *)info_arena) % sizeof(tTrackGraphInfo) == 0) {
        snprintf(b, 48, "I%d", (int)((const tTrackGraphInfo *)(const void *)u
                                     - info_arena));
        return b;
    }
    for (k = mallocs - 1; k >= 0; --k) {
        const tTrackGraph *g = graphs[k];
        const uint8_t     *e0 = (const uint8_t *)g->Edge;

        if (p == g) {
            snprintf(b, 48, "G%d", k);
            return b;
        }
        if (u >= e0 && u < e0 + sizeof g->Edge) {
            int                    i = (int)((u - e0) / sizeof(tTrackGraphEdge));
            const tTrackGraphEdge *e = &g->Edge[i];

            if (p == &e->RoadBlockList)
                snprintf(b, 48, "G%d.E%d.rb", k, i);
            else if (p == &e->SpeedTrapList)
                snprintf(b, 48, "G%d.E%d.st", k, i);
            else
                break;
            return b;
        }
    }
    return "?";
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size);

    (void)nm;
    memset(p, 0xcd, (size_t)size);
    if (size == (int)sizeof(tTrackGraph))
        size = 23216;
    graphs[mallocs] = (tTrackGraph *)(void *)p;
    printf("  malloc2 %d %d -> G%d", size, pool, mallocs);
    if (flags != 0)
        printf(" flags %d", flags);
    printf("\n");
    mallocs++;
    return p;
}

void bFree(void *p)
{
    printf("  delete %s\n", sym(p));
}

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *nm,
                        int memoryPool)
{
    void *p = pool_tokens[pools];

    if (slotSize == (int)sizeof(tTrackGraphInfo))
        slotSize = 12;
    printf("  newpool %d %d %s %d -> pool%d\n", slotSize, numSlots, nm,
           memoryPool, pools);
    pools++;
    return (BSlotPool *)p;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", sym(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    tTrackGraphInfo *p = &info_arena[infos];

    memset(p, 0xcd, sizeof *p);
    printf("  omalloc %s -> I%d\n", sym(pool), infos);
    infos++;
    return p;
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    printf("  sfree %s %s\n", sym(pool), sym(slot));
}

static TrackRoute *route_of(int32_t n)
{
    return n >= 0 && n < TRACK_ROUTE_MAX_ROUTES
           ? TheTrackRouteManager.pTrackRoutes[n] : NULL;
}

static int car_index(const Car *c)
{
    int k;

    for (k = 0; k < NCARS; ++k)
        if (cars[k] == c)
            return k;
    return -1;
}

TrackRoute *car_get_route(Car *c, int find)
{
    int k = car_index(c);

    printf("  getroute A%d %d\n", k, find);
    return route_of(car_route[k]);
}

TrackRoutePoint *car_get_route_point(Car *c, int find)
{
    int         k = car_index(c);
    TrackRoute *r = route_of(car_route[k]);

    printf("  getrp A%d %d\n", k, find);
    if (r == NULL || car_point[k] == INT32_MIN)
        return NULL;
    return &r->TrackRoutePointTable[car_point[k]];
}

tRoadBlock *copmanager_get_road_block_from_loaded_data_index(tCopManager *m,
                                                             int32_t i)
{
    int has = i >= 0 && i < NSPOTS && rb_has[i];

    printf("  rbget %s %d -> %s\n", sym(m), i, has ? sym(&rbs[i]) : "0");
    return has ? &rbs[i] : NULL;
}

tSpeedTrap *copmanager_get_speed_trap_from_loaded_data_index(tCopManager *m,
                                                             int32_t i)
{
    int has = i >= 0 && i < NSPOTS && st_has[i];

    printf("  stget %s %d -> %s\n", sym(m), i, has ? sym(&sts[i]) : "0");
    return has ? &sts[i] : NULL;
}

// coputil.c's CarCausedRecentCollision's, which the script never reaches.
static void unreached(const char *f)
{
    fprintf(stderr, "trackgraph_test: %s reached\n", f);
    exit(3);
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

void collision_get_colliding_cars(Collision *c, Car **car1, Car **car2)
{
    (void)c; (void)car1; (void)car2;
    unreached("collision_get_colliding_cars");
}

int32_t car_is_car_in_front(Car *c, Car *other, uint16_t angle)
{
    (void)c; (void)other; (void)angle;
    unreached("car_is_car_in_front");
    return 0;
}

static float path_distance(const bVector2 *pos)
{
    return pos->x;
}

// ------------------------------------------------------------- the dump

static void dump_list(const char *what, int i, const bNode *l)
{
    const bNode *n = l->next;
    const bNode *prev = l;
    int          k = 0;

    printf("E%d %s", i, what);
    while (n != l && k < 400) {
        printf(" %s:%d%s", sym(n), ((const tTrackGraphInfo *)n)->nIndexIntoLoadedData,
               n->prev == prev ? "" : "!");
        prev = n;
        n = n->next;
        k++;
    }
    printf(" end%s\n", l->prev == prev ? "" : "!");
}

static void dump(void)
{
    tTrackGraph *g = TheTrackGraph;
    int          i, rest = 0;

    printf("pools %s %s\n", sym(TrackGraphRoadBlockInfoSlotPool),
           sym(TrackGraphSpeedTrapInfoSlotPool));
    if (g == NULL) {
        printf("G none\n");
        return;
    }
    printf("G %s nv %d ne %d hc %d vptr %08x\n", sym(g), g->nNumVerticies,
           g->nNumEdges, g->bHasCloakedEdge, g->vptr);
    for (i = 0; i < g->nNumVerticies; ++i) {
        const tTrackGraphVertex *v = &g->Vertex[i];

        printf("V%d S%d r%d p%d d%08x f%d %d b%d %d\n", i,
               (int)(v->pSignpost - SignpostArray), v->nRouteNumber,
               v->nRoutePointNumber, fb(v->fDistanceAroundTrack),
               v->ForwardEdgeIndecies[0], v->ForwardEdgeIndecies[1],
               v->BackwardEdgeIndecies[0], v->BackwardEdgeIndecies[1]);
    }
    for (i = 0; i < g->nNumEdges; ++i) {
        const tTrackGraphEdge *e = &g->Edge[i];

        printf("E%d %d>%d r%d %d..%d c%d %d h%d\n", i, e->nFromVertex,
               e->nToVertex, e->nRouteNumber, e->nFirstRoutePoint,
               e->nLastRoutePoint, e->bIsCloaked, e->bCloakable,
               e->bHelisheet);
        dump_list("rb", i, &e->RoadBlockList);
        dump_list("st", i, &e->SpeedTrapList);
    }
    for (i = g->nNumEdges; i < TRACKGRAPH_MAX_EDGES; ++i) {
        const tTrackGraphEdge *e = &g->Edge[i];

        if (e->RoadBlockList.next != &e->RoadBlockList
            || e->RoadBlockList.prev != &e->RoadBlockList
            || e->SpeedTrapList.next != &e->SpeedTrapList
            || e->SpeedTrapList.prev != &e->SpeedTrapList)
            rest++;
    }
    printf("rest %d\n", rest);
}

static void dump_signs(void)
{
    uint32_t i;

    printf("signs");
    for (i = 0; i < NumSignposts; ++i)
        printf("%s%02x", i % 32 ? "" : " ", SignpostArray[i].Flags);
    printf("\n");
}

// --------------------------------------------------------------- the ops

static char  *fields[16];
static int    nfields;

static int32_t I(int k)
{
    return (int32_t)strtol(fields[k], NULL, 0);
}

static float Fl(int k)
{
    return bf((uint32_t)strtoul(fields[k], NULL, 0));
}

static void load(const char *path)
{
    FILE    *fh = fopen(path, "rb");
    long     size;
    uint8_t *raw;
    uint32_t rsize;

    if (fh == NULL) {
        fprintf(stderr, "cannot open %s\n", path);
        exit(2);
    }
    fseek(fh, 0, SEEK_END);
    size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    // 16-aligned, as the bundle's chunks are. The old blob is left: the
    // script destroys every graph before it loads again.
    raw = malloc((size_t)size + 32);
    blob = (uint8_t *)(((uintptr_t)raw + 15) & ~(uintptr_t)15);
    if (fread(blob, 1, (size_t)size, fh) != (size_t)size) {
        fprintf(stderr, "short read %s\n", path);
        exit(2);
    }
    fclose(fh);
    memset(&TheTrackRouteManager, 0, sizeof TheTrackRouteManager);
    SignpostArray = NULL;
    NumSignposts = 0;
    memcpy(&rsize, blob + 4, 4);
    track_routes_loader(blob);
    track_routes_loader(blob + 8 + ((rsize + 15) & ~15u));
    printf("load signs %u\n", NumSignposts);
}

static void op(void)
{
    const char *o = fields[0];

    if (strcmp(o, "load") == 0) {
        load(fields[1]);
    } else if (strcmp(o, "tracklen") == 0) {
        TheTrackPathManager.TrackLength = Fl(1);
    } else if (strcmp(o, "init") == 0) {
        printf("init\n");
        trackgraph_init();
    } else if (strcmp(o, "cleanup") == 0) {
        printf("cleanup\n");
        trackgraph_cleanup();
    } else if (strcmp(o, "dtor") == 0) {
        printf("dtor %d\n", I(1));
        trackgraph_destruct(TheTrackGraph, I(1));
        TheTrackGraph = NULL;
    } else if (strcmp(o, "dump") == 0) {
        dump();
    } else if (strcmp(o, "signs") == 0) {
        dump_signs();
    } else if (strcmp(o, "uncloak") == 0) {
        printf("uncloak\n");
        trackgraph_uncloak_all_edges(TheTrackGraph);
    } else if (strcmp(o, "vnum") == 0) {
        printf("vnum %d %d -> %d\n", I(1), I(2),
               trackgraph_get_vertex_number(TheTrackGraph, I(1), I(2)));
    } else if (strcmp(o, "fedge") == 0) {
        tTrackGraphEdge *e =
            trackgraph_find_edge_by_route_and_point(TheTrackGraph, I(1), I(2));

        if (e == NULL)
            printf("fedge %d %d -> 0\n", I(1), I(2));
        else
            printf("fedge %d %d -> E%d\n", I(1), I(2),
                   (int)(e - TheTrackGraph->Edge));
    } else if (strcmp(o, "hasc") == 0) {
        printf("hasc %d\n", trackgraph_has_cloaked_edges(TheTrackGraph));
    } else if (strcmp(o, "getv") == 0) {
        printf("getv %d -> V%d\n", I(1),
               (int)(trackgraph_get_vertex(TheTrackGraph, I(1))
                     - TheTrackGraph->Vertex));
    } else if (strcmp(o, "gete") == 0) {
        printf("gete %d -> E%d\n", I(1),
               (int)(trackgraph_get_edge(TheTrackGraph, I(1))
                     - TheTrackGraph->Edge));
    } else if (strcmp(o, "car") == 0) {
        int k = I(1);

        car_route[k] = I(2);
        car_point[k] = strcmp(fields[3], "none") == 0 ? INT32_MIN : I(3);
        cars[k]->TheTrackPathCoordinate.DistanceAroundTrack = Fl(4);
    } else if (strcmp(o, "carpos") == 0) {
        cars[I(1)]->State.Position.x = Fl(2);
        cars[I(1)]->State.Position.y = Fl(3);
    } else if (strcmp(o, "world") == 0) {
        int k;

        world.TotalNumCars = I(1);
        for (k = 0; k < NCARS; ++k)
            world.CarTable[k] = cars[k];
        world.PlayerPositions[0].x = Fl(2);
        world.PlayerPositions[0].y = Fl(3);
        world.PlayerPositions[1].x = Fl(4);
        world.PlayerPositions[1].y = Fl(5);
    } else if (strcmp(o, "rb") == 0) {
        int k = I(1);

        rb_has[k] = strcmp(fields[2], "none") != 0;
        if (rb_has[k]) {
            rbs[k].fDistanceAroundTrack = Fl(2);
            rbs[k].v2Position.x = Fl(3);
            rbs[k].v2Position.y = Fl(4);
        }
    } else if (strcmp(o, "st") == 0) {
        int k = I(1);

        st_has[k] = strcmp(fields[2], "none") != 0;
        if (st_has[k]) {
            sts[k].fDistanceAroundTrack = Fl(2);
            sts[k].v2Position.x = Fl(3);
            sts[k].v2Position.y = Fl(4);
        }
    } else if (strcmp(o, "findrb") == 0) {
        tRoadBlock *rb;

        printf("findrb A%d %s %s %s %d\n", I(1), fields[2], fields[3],
               fields[4], I(4) != 0);
        rb = trackgraph_find_road_block(TheTrackGraph, cars[I(1)], Fl(2),
                                        Fl(3), I(4));
        printf("  -> %s\n", sym(rb));
    } else if (strcmp(o, "findst") == 0) {
        tSpeedTrap *st;

        printf("findst A%d %s %s %s %d\n", I(1), fields[2], fields[3],
               fields[4], I(4) != 0);
        st = trackgraph_find_speed_trap(TheTrackGraph, cars[I(1)], Fl(2),
                                        Fl(3), I(4));
        printf("  -> %s\n", sym(st));
    } else if (strcmp(o, "gftd") == 0) {
        printf("gftd %s %s -> %08x\n", fields[1], fields[2],
               fb(get_forward_track_distance(Fl(1), Fl(2))));
    } else if (strcmp(o, "clear") == 0) {
        bVector2 p;

        p.x = Fl(1);
        p.y = Fl(2);
        printf("clear %s %s -> %d\n", fields[1], fields[2],
               is_teleport_location_clear(&p));
    } else {
        fprintf(stderr, "unknown op %s\n", o);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    static char line[4096];
    FILE       *fh;
    int         k;

    if (argc < 2) {
        fprintf(stderr, "usage: trackgraph_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 2;
    }
    trackgraph_install_vtables();
    gTrackPathDistanceFn = path_distance;
    pCopManager = (tCopManager *)(void *)mgr_token;
    pCurrentWorld = &world;
    for (k = 0; k < NCARS; ++k) {
        cars[k] = calloc(1, sizeof(Car));
        car_route[k] = -1;
    }
    while (fgets(line, sizeof line, fh) != NULL) {
        char *s = line;

        line[strcspn(line, "\r\n")] = 0;
        if (line[0] == 0)
            continue;
        nfields = 0;
        while (nfields < 16) {
            fields[nfields++] = s;
            s = strchr(s, '|');
            if (s == NULL)
                break;
            *s++ = 0;
        }
        op();
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
