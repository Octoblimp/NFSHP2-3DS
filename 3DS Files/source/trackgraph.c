// trackgraph -- see trackgraph.h.

#include "trackgraph.h"

#include <stddef.h>

#include "bmem.h"
#include "car.h"
#include "copmanager.h"
#include "copmgr.h"
#include "coputil.h"
#include "replay.h"
#include "trackpath.h"
#include "vtable.h"

tTrackGraph *TheTrackGraph;
BSlotPool   *TrackGraphRoadBlockInfoSlotPool;
BSlotPool   *TrackGraphSpeedTrapInfoSlotPool;

typedef void (*DtorFn)(void *self, int32_t flags);

#define INFO_SLOT_SIZE ((int)sizeof(tTrackGraphInfo))

static void list_init(bNode *l)
{
    l->next = l;
    l->prev = l;
}

// bTList::AddTail: the old tail, the list's prev, takes the node next.
static void add_tail(bNode *l, tTrackGraphInfo *info, int32_t index)
{
    bNode *tail = l->prev;

    tail->next = &info->Link;
    l->prev = &info->Link;
    info->nIndexIntoLoadedData = index;
    info->Link.prev = tail;
    info->Link.next = l;
}

// The list's head unlinked and handed back to `pool`, until the list is
// its own sentinel again: ~tTrackGraph...Info with flags 3, which is
// bNode's empty destructor and the class's operator delete.
static void drain(bNode *l, BSlotPool *pool)
{
    while (l->next != l) {
        bNode *n = l->next;

        n->prev->next = n->next;
        n->next->prev = n->prev;
        bSlotFree(pool, n);
    }
}

// ----------------------------------------------------------- the build

// 0x0024e420. The point's number is its index in the route's table.
static void add_vertex(tTrackGraph *g, TrackRoute *r, TrackRoutePoint *p)
{
    tTrackGraphVertex  *v = &g->Vertex[g->nNumVerticies++];
    TrackPathCoordinate c;

    v->ForwardEdgeIndecies[0] = -1;
    v->ForwardEdgeIndecies[1] = -1;
    v->pSignpost = trpoint_get_signpost(p);
    v->nRouteNumber = r->RouteNumber;
    v->nRoutePointNumber = (int32_t)(p - r->TrackRoutePointTable);
    trackpath_coord_init_at(&c, &p->Position);
    v->fDistanceAroundTrack = c.DistanceAroundTrack;
}

int32_t trackgraph_get_vertex_number(const tTrackGraph *g, int32_t route,
                                     int32_t point)
{
    int32_t i;

    for (i = 0; i < g->nNumVerticies; ++i) {
        const tTrackGraphVertex *v = &g->Vertex[i];

        if (v->nRouteNumber == route && v->nRoutePointNumber == point)
            return i;
        if (v->pSignpost->NewRoute == route
            && v->pSignpost->NewPoint == point)
            return i;
    }
    return -1;
}

// 0x0024e560. Down the vertex's own route from its point, or with `follow`
// down its sign's new route from the sign's point, to the next signposted
// point that is a vertex. Every point on the way, both ends in, adds its
// roadblock and radar trap to the edge's lists and can clear bHelisheet.
// No vertex before the route's end leaves nToVertex -1 and nLastRoutePoint
// as the block had it; no retail track has such an edge.
static int32_t add_edge(tTrackGraph *g, int32_t from, int32_t follow,
                        int32_t cloaked)
{
    int32_t            n = g->nNumEdges++;
    tTrackGraphEdge   *e = &g->Edge[n];
    tTrackGraphVertex *v = &g->Vertex[from];
    TrackRoute        *r;
    int32_t            i;

    e->nToVertex = -1;
    e->bCloakable = cloaked;
    e->nFromVertex = from;
    e->bIsCloaked = cloaked;
    e->nRouteNumber = follow ? (int32_t)v->pSignpost->NewRoute
                             : v->nRouteNumber;
    e->nFirstRoutePoint = follow ? (int32_t)v->pSignpost->NewPoint
                                 : v->nRoutePointNumber;
    e->bHelisheet = 1;
    // GetRoute inlined: NULL below 0. Retail goes on to read the NULL
    // route's NumPoints; the port stops. Every sign on the disc names a
    // loaded route.
    r = e->nRouteNumber >= 0
        ? TheTrackRouteManager.pTrackRoutes[e->nRouteNumber] : NULL;
    if (r == NULL)
        return n;
    for (i = e->nFirstRoutePoint; i < r->NumPoints; ++i) {
        TrackRoutePoint *p = &r->TrackRoutePointTable[i];

        if (p->Bits & TRP_NO_HELISHEET)
            e->bHelisheet = 0;
        if ((p->Bits & TRP_ROADBLOCK_MASK) != TRP_ROADBLOCK_MASK)
            add_tail(&e->RoadBlockList,
                     bSlotOMalloc(TrackGraphRoadBlockInfoSlotPool),
                     (int32_t)trpoint_road_block_number(p));
        if ((p->Bits & TRP_RADARTRAP_MASK) != TRP_RADARTRAP_MASK)
            add_tail(&e->SpeedTrapList,
                     bSlotOMalloc(TrackGraphSpeedTrapInfoSlotPool),
                     (int32_t)trpoint_radar_trap_number(p));
        if (i != e->nFirstRoutePoint && trpoint_has_signpost(p)) {
            int32_t to = trackgraph_get_vertex_number(g, e->nRouteNumber, i);

            if (to != -1) {
                e->nLastRoutePoint = i;
                e->nToVertex = to;
                break;
            }
        }
    }
    return n;
}

tTrackGraph *trackgraph_construct(tTrackGraph *g)
{
    int32_t r, i;

    g->vptr = TTRACKGRAPH_VTABLE;
    for (i = 0; i < TRACKGRAPH_MAX_EDGES; ++i) {
        list_init(&g->Edge[i].RoadBlockList);
        list_init(&g->Edge[i].SpeedTrapList);
    }
    g->nNumVerticies = 0;
    g->nNumEdges = 0;
    g->bHasCloakedEdge = 0;
    TrackGraphRoadBlockInfoSlotPool =
        bNewSlotPool(INFO_SLOT_SIZE, 128, "rbSlotPool", 16);
    TrackGraphSpeedTrapInfoSlotPool =
        bNewSlotPool(INFO_SLOT_SIZE, 128, "stSlotPool", 16);

    for (r = 0; r < TRACKGRAPH_NUM_ROUTES; ++r) {
        TrackRoute *route = TheTrackRouteManager.pTrackRoutes[r];
        int32_t     n;

        if (route == NULL)
            continue;
        n = route->NumPoints;
        for (i = 0; i < n; ++i) {
            TrackRoutePoint *p = &route->TrackRoutePointTable[i];
            const Signpost  *s;

            if (!trpoint_has_signpost(p))
                continue;
            s = trpoint_get_signpost(p);
            if ((s->Flags & SIGNPOST_BACKWARDS)
                && (s->Flags & SIGNPOST_SIGN_MASK) != SIGN_STOP)
                continue;
            if (s->Flags & SIGNPOST_CLOAKED)
                g->bHasCloakedEdge = 1;
            add_vertex(g, route, p);
        }
    }

    for (i = 0; i < g->nNumVerticies; ++i) {
        tTrackGraphVertex *v = &g->Vertex[i];
        uint32_t           sign = v->pSignpost->Flags & SIGNPOST_SIGN_MASK;

        if (sign == SIGN_STOP && !(v->pSignpost->Flags & SIGNPOST_BACKWARDS))
            continue;
        if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {
            v->ForwardEdgeIndecies[0] = add_edge(g, i, 1, 0);
        } else {
            v->ForwardEdgeIndecies[0] = add_edge(g, i, 0, 0);
            v->ForwardEdgeIndecies[1] = add_edge(
                g, i, 1, (v->pSignpost->Flags & SIGNPOST_CLOAKED) != 0);
        }
    }

    for (i = 0; i < g->nNumVerticies; ++i) {
        g->Vertex[i].BackwardEdgeIndecies[0] = -1;
        g->Vertex[i].BackwardEdgeIndecies[1] = -1;
    }
    for (i = 0; i < g->nNumEdges; ++i) {
        int32_t  to = g->Edge[i].nToVertex;
        int32_t *b;

        // Retail indexes Vertex[-1] for an edge that ran off its route.
        // That vertex's BackwardEdgeIndecies are the graph's nNumEdges and
        // bHasCloakedEdge, and nNumEdges is never -1, so the edge's number
        // lands in bHasCloakedEdge.
        if (to == -1) {
            g->bHasCloakedEdge = i;
            continue;
        }
        b = g->Vertex[to].BackwardEdgeIndecies;
        b[b[0] != -1] = i;
    }
    for (i = 0; i < g->nNumVerticies; ++i) {
        tTrackGraphVertex *v = &g->Vertex[i];
        int32_t            b1 = v->BackwardEdgeIndecies[1];
        int32_t            f0 = v->ForwardEdgeIndecies[0];

        if (b1 == -1 || f0 == -1)
            continue;
        if (g->Edge[b1].bIsCloaked)
            continue;
        if (g->Edge[b1].nRouteNumber != g->Edge[f0].nRouteNumber)
            continue;
        v->BackwardEdgeIndecies[1] = v->BackwardEdgeIndecies[0];
        v->BackwardEdgeIndecies[0] = b1;
    }
    return g;
}

// The edges' and vertices' own destructors follow the pools' deletion and
// do nothing: the lists are empty by then and bList's is empty.
void trackgraph_destruct(tTrackGraph *g, int32_t flags)
{
    int32_t i;

    g->vptr = TTRACKGRAPH_VTABLE;
    for (i = 0; i < g->nNumEdges; ++i) {
        drain(&g->Edge[i].RoadBlockList, TrackGraphRoadBlockInfoSlotPool);
        drain(&g->Edge[i].SpeedTrapList, TrackGraphSpeedTrapInfoSlotPool);
    }
    bDeleteSlotPool(TrackGraphRoadBlockInfoSlotPool);
    TrackGraphRoadBlockInfoSlotPool = NULL;
    bDeleteSlotPool(TrackGraphSpeedTrapInfoSlotPool);
    TrackGraphSpeedTrapInfoSlotPool = NULL;
    if (flags & 1)
        bFree(g);
}

void trackgraph_uncloak_all_edges(tTrackGraph *g)
{
    int32_t i;

    for (i = 0; i < g->nNumEdges; ++i) {
        tTrackGraphEdge *e = &g->Edge[i];

        if (e->bIsCloaked) {
            e->bIsCloaked = 0;
            g->Vertex[e->nFromVertex].pSignpost->Flags &=
                (uint8_t)~SIGNPOST_CLOAKED;
        }
    }
    g->bHasCloakedEdge = 0;
}

// ------------------------------------------------------------ the finds

tTrackGraphEdge *trackgraph_find_edge_by_route_and_point(tTrackGraph *g,
                                                         int32_t route,
                                                         int32_t point)
{
    int32_t i;

    for (i = 0; i < g->nNumEdges; ++i) {
        tTrackGraphEdge *e = &g->Edge[i];

        if (e->bIsCloaked)
            continue;
        if (e->nRouteNumber != route)
            continue;
        if (point < e->nFirstRoutePoint)
            continue;
        if (e->nLastRoutePoint < point)
            continue;
        return e;
    }
    return NULL;
}

// The edge the car is on, by its route and point (both found afresh).
static tTrackGraphEdge *car_edge(tTrackGraph *g, Car *car)
{
    TrackRoute      *r = car_get_route(car, 1);
    TrackRoutePoint *p = car_get_route_point(car, 1);

    if (r == NULL || p == NULL)
        return NULL;
    return trackgraph_find_edge_by_route_and_point(
        g, r->RouteNumber, (int32_t)(p - r->TrackRoutePointTable));
}

// The edge after `e` going forward (the To vertex's first forward edge) or
// back (the From vertex's first backward one); NULL at -1. Forward from an
// edge that ran off its route, retail reads Vertex[-1]'s first forward
// edge, which is the word before the graph's block: bMalloc's header.
// The port stops there instead. No retail track has such an edge.
static tTrackGraphEdge *next_edge(tTrackGraph *g, const tTrackGraphEdge *e,
                                  int32_t forward)
{
    int32_t v = forward ? e->nToVertex : e->nFromVertex;
    int32_t n;

    if (v < 0)
        return NULL;
    n = forward ? g->Vertex[v].ForwardEdgeIndecies[0]
                : g->Vertex[v].BackwardEdgeIndecies[0];
    return n == -1 ? NULL : &g->Edge[n];
}

// GetForwardTrackDistance from the spot to the car, or the car to the spot.
static int32_t in_range(float spot, float car, float fMin, float fMax,
                        int32_t forward)
{
    float d = forward ? get_forward_track_distance(spot, car)
                      : get_forward_track_distance(car, spot);

    return d < fMax && fMin <= d;
}

tRoadBlock *trackgraph_find_road_block(tTrackGraph *g, Car *car, float fMin,
                                       float fMax, int32_t forward)
{
    tTrackGraphEdge *e = car_edge(g, car);
    float            d;
    int32_t          steps = 0;

    if (e == NULL)
        return NULL;
    d = car->TheTrackPathCoordinate.DistanceAroundTrack;
    for (;;) {
        bNode *n;

        for (n = e->RoadBlockList.next; n != &e->RoadBlockList;
             n = n->next) {
            tRoadBlock *rb = copmanager_get_road_block_from_loaded_data_index(
                pCopManager, ((tTrackGraphInfo *)n)->nIndexIntoLoadedData);

            if (rb == NULL)
                continue;
            if (!in_range(rb->fDistanceAroundTrack, d, fMin, fMax, forward))
                continue;
            if (!is_teleport_location_clear(&rb->v2Position))
                continue;
            return rb;
        }
        if (++steps >= 5)
            return NULL;
        e = next_edge(g, e, forward);
        if (e == NULL)
            return NULL;
    }
}

tSpeedTrap *trackgraph_find_speed_trap(tTrackGraph *g, Car *car, float fMin,
                                       float fMax, int32_t forward)
{
    tTrackGraphEdge *e = car_edge(g, car);
    float            d;
    int32_t          steps = 0;

    if (e == NULL)
        return NULL;
    d = car->TheTrackPathCoordinate.DistanceAroundTrack;
    for (;;) {
        bNode *n;

        for (n = e->SpeedTrapList.next; n != &e->SpeedTrapList;
             n = n->next) {
            tSpeedTrap *st = copmanager_get_speed_trap_from_loaded_data_index(
                pCopManager, ((tTrackGraphInfo *)n)->nIndexIntoLoadedData);

            if (st == NULL)
                continue;
            if (!in_range(st->fDistanceAroundTrack, d, fMin, fMax, forward))
                continue;
            return st;
        }
        if (++steps >= 5)
            return NULL;
        e = next_edge(g, e, forward);
        if (e == NULL)
            return NULL;
    }
}

int32_t trackgraph_has_cloaked_edges(const tTrackGraph *g)
{
    return g->bHasCloakedEdge;
}

tTrackGraphVertex *trackgraph_get_vertex(tTrackGraph *g, int32_t i)
{
    return &g->Vertex[i];
}

tTrackGraphEdge *trackgraph_get_edge(tTrackGraph *g, int32_t i)
{
    return &g->Edge[i];
}

// ------------------------------------------------- InitTrackGraph et al

void trackgraph_init(void)
{
    TheTrackGraph = trackgraph_construct(
        (tTrackGraph *)bMalloc((int)sizeof(tTrackGraph), "TrackGraph", 0,
                               16));
}

void trackgraph_cleanup(void)
{
    tTrackGraph *g = TheTrackGraph;

    if (g != NULL) {
        const VtEntry *e = vt_slot(g->vptr, TTRACKGRAPH_VT_DTOR);

        ((DtorFn)e->fn)(vt_this(g, e), 3);
    }
    TheTrackGraph = NULL;
}

// ------------------------------------------------------------ the table

static void dtor_entry(void *self, int32_t flags)
{
    trackgraph_destruct((tTrackGraph *)self, flags);
}

static const VtEntry trackgraph_vt[] = {
    { 0, 0, NULL },
    { 0, 0, (VtFn)dtor_entry },                 //   8  0x0024e148
};

void trackgraph_install_vtables(void)
{
    vt_install(TTRACKGRAPH_VTABLE, trackgraph_vt,
               (int)(sizeof trackgraph_vt / sizeof trackgraph_vt[0]));
}

void trackgraph_do_snapshot(tTrackGraph *g, ReplaySnapshot *s)
{
    int32_t i;
    ReplaySnapshot_MoveBool(s, &g->bHasCloakedEdge, 1);
    for (i = 0; i < g->nNumEdges; i++)
        if (g->Edge[i].bCloakable != 0)
            ReplaySnapshot_MoveBool(s, &g->Edge[i].bIsCloaked, 1);
}
