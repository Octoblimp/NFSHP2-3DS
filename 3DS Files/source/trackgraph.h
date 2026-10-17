// trackgraph -- retail's TrackGraph.obj (0x0024dd58 .. 0x0024ef84): the
// racing routes as a graph for the cops. A vertex is a signposted point,
// an edge the run of route from one vertex to the next, and each edge
// carries the roadblock and radar-trap spots along it. FindRoadBlock and
// FindSpeedTrap walk the edges from a car to find a spot so far ahead or
// behind it. See docs/formats/track-graph.md.
//
//   tTrackGraph::tTrackGraph             0x0024dd58  1004
//   tTrackGraph::~tTrackGraph            0x0024e148   464
//   tTrackGraph::DoSnapshot              0x0024e318   160  (TASKS 72d)
//   tTrackGraph::UncloakAllEdges         0x0024e3b8   100
//   tTrackGraph::AddVertex               0x0024e420   176
//   tTrackGraph::GetVertexNumber         0x0024e4d0   144
//   tTrackGraph::AddEdge                 0x0024e560   560
//   tTrackGraph::FindEdgeByRouteAndPoint 0x0024e790   128
//   tTrackGraph::FindRoadBlock           0x0024e880   488
//   tTrackGraph::FindSpeedTrap           0x0024ea68   468
//   InitTrackGraph                       0x0024ec40    44
//   CleanupTrackGraph                    0x0024ec70    56
//   HasCloakedEdges, GetVertex, GetEdge  0x0024ecb8 .. 0x0024ecec
//
// Not ported: DebugDump (0x0024e810), whose two loops per vertex only
// count down: its prints are compiled out.

#ifndef TRACKGRAPH_H
#define TRACKGRAPH_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "trackroute.h"

struct Car;
struct tRoadBlock;
struct tSpeedTrap;

#define TRACKGRAPH_MAX_VERTICES 100
#define TRACKGRAPH_MAX_EDGES    400

// The constructor takes its vertices from routes 0 to 48 only: the racing
// routes. Traffic's, 50 to 69, are left out.
#define TRACKGRAPH_NUM_ROUTES   49

// tTrackGraphRoadBlockInfo and tTrackGraphSpeedTrapInfo, 12 bytes each: a
// node on an edge's list and the index of the spot's record in the cops'
// chunk. Each comes from its own slot pool (pMySlotPool, a static).
typedef struct tTrackGraphInfo {
    bNode   Link;                   //  0
    int32_t nIndexIntoLoadedData;   //  8
} tTrackGraphInfo;                  // 12

// 40 bytes, as the demo's. The node is never linked.
typedef struct tTrackGraphVertex {
    bNode     Link;                     //  0
    Signpost *pSignpost;                //  8  the point's sign
    int32_t   nRouteNumber;             // 12
    int32_t   nRoutePointNumber;        // 16
    float     fDistanceAroundTrack;     // 20
    int32_t   ForwardEdgeIndecies[2];   // 24  -1 for none
    int32_t   BackwardEdgeIndecies[2];  // 32
} tTrackGraphVertex;                    // 40

// 48 bytes in retail, the demo's 40 with two words before the lists.
typedef struct tTrackGraphEdge {
    int32_t nFromVertex;        //  0
    int32_t nToVertex;          //  4  -1 if the route ran out first
    int32_t nRouteNumber;       //  8
    int32_t nFirstRoutePoint;   // 12
    int32_t nLastRoutePoint;    // 16  the To vertex's point; never set
                                //     when the route runs out
    int32_t bIsCloaked;         // 20
    // Retail's two. The first is AddEdge's cloaked argument, as bIsCloaked
    // starts out; DoSnapshot saves bIsCloaked only where it is set. The
    // second is 1 unless a point from nFirstRoutePoint up to where the
    // edge ends is flagged NoHelisheet.
    int32_t bCloakable;         // 24
    int32_t bHelisheet;         // 28
    bNode   RoadBlockList;      // 32  bTList<tTrackGraphRoadBlockInfo>
    bNode   SpeedTrapList;      // 40  bTList<tTrackGraphSpeedTrapInfo>
} tTrackGraphEdge;              // 48

// 23216 bytes, the demo's 20016 and 8 more per edge.
typedef struct tTrackGraph {
    int32_t           nNumVerticies;                    //     0
    int32_t           nNumEdges;                        //     4
    int32_t           bHasCloakedEdge;                  //     8
    tTrackGraphVertex Vertex[TRACKGRAPH_MAX_VERTICES];  //    12
    tTrackGraphEdge   Edge[TRACKGRAPH_MAX_EDGES];       //  4012
    uint32_t          vptr;                             // 23212  0x002bf3d8
} tTrackGraph;                                          // 23216

#define TTRACKGRAPH_VTABLE  0x002bf3d8u
#define TTRACKGRAPH_VT_DTOR 8

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char ttrackgraph_layout_check[
    (sizeof(tTrackGraphInfo) == 12
     && offsetof(tTrackGraphVertex, pSignpost) == 8
     && offsetof(tTrackGraphVertex, fDistanceAroundTrack) == 20
     && offsetof(tTrackGraphVertex, ForwardEdgeIndecies) == 24
     && offsetof(tTrackGraphVertex, BackwardEdgeIndecies) == 32
     && sizeof(tTrackGraphVertex) == 40
     && offsetof(tTrackGraphEdge, bIsCloaked) == 20
     && offsetof(tTrackGraphEdge, bHelisheet) == 28
     && offsetof(tTrackGraphEdge, RoadBlockList) == 32
     && offsetof(tTrackGraphEdge, SpeedTrapList) == 40
     && sizeof(tTrackGraphEdge) == 48
     && offsetof(tTrackGraph, Vertex) == 12
     && offsetof(tTrackGraph, Edge) == 4012
     && offsetof(tTrackGraph, vptr) == 23212
     && sizeof(tTrackGraph) == 23216) ? 1 : -1];
#endif

// gp-14840, 0x00331ef8. NULL outside a World.
extern tTrackGraph *TheTrackGraph;

// gp-14848 and gp-14844: the two infos' pMySlotPool, made by the
// constructor and deleted by the destructor.
extern BSlotPool *TrackGraphRoadBlockInfoSlotPool;
extern BSlotPool *TrackGraphSpeedTrapInfoSlotPool;

// 0x0024dd58. The pools (128 slots each), then a vertex for every
// signposted point of routes 0..48 but a Backwards sign that is not a
// Stop, then the edges: one along the sign's new route for AlwaysTake and
// a Backwards Stop, none for any other Stop, and two otherwise -- along
// the vertex's own route, then along the sign's, cloaked as the sign is.
// Last, the backward edges, and a swap that puts first the uncloaked
// backward edge on the route of the vertex's first forward edge.
tTrackGraph *trackgraph_construct(tTrackGraph *g);

// 0x0024e148. Frees every info to its pool, deletes both pools, and frees
// `g` when bit 0 of `flags` is set. Slot 8 of the table.
void trackgraph_destruct(tTrackGraph *g, int32_t flags);

// 0x0024e3b8. Clears every cloaked edge, and the Cloaked flag of its From
// vertex's sign, then bHasCloakedEdge.
void trackgraph_uncloak_all_edges(tTrackGraph *g);

// 0x0024e4d0. The first vertex at the route and point, as its own point or
// as its sign's target; -1 for none.
int32_t trackgraph_get_vertex_number(const tTrackGraph *g, int32_t route,
                                     int32_t point);

// 0x0024e790. The first uncloaked edge on the route whose points span
// `point`, both ends in; NULL for none.
tTrackGraphEdge *trackgraph_find_edge_by_route_and_point(tTrackGraph *g,
                                                         int32_t route,
                                                         int32_t point);

// 0x0024e880 and 0x0024ea68. From the edge the car is on, the first spot
// of the edge whose forward track distance from the car (from the spot to
// the car with `forward` clear) is in [fMin, fMax), and for a roadblock
// whose spot is clear to teleport to; then the next edge on, forward or
// back, five edges at most. NULL for none, and for a car with no route or
// point or on no edge.
struct tRoadBlock *trackgraph_find_road_block(tTrackGraph *g,
                                              struct Car *car, float fMin,
                                              float fMax, int32_t forward);
struct tSpeedTrap *trackgraph_find_speed_trap(tTrackGraph *g,
                                              struct Car *car, float fMin,
                                              float fMax, int32_t forward);

// 0x0024ecb8, 0x0024ecc0, 0x0024ecd8.
int32_t            trackgraph_has_cloaked_edges(const tTrackGraph *g);
tTrackGraphVertex *trackgraph_get_vertex(tTrackGraph *g, int32_t i);
tTrackGraphEdge   *trackgraph_get_edge(tTrackGraph *g, int32_t i);

// InitTrackGraph, 0x0024ec40: a graph in a 23216-byte block, pool 16.
// CleanupTrackGraph, 0x0024ec70: its destructor through its table, flags
// 3, then NULL. World's constructor and destructor call them, through
// gInitTrackGraphFn and gCleanupTrackGraphFn.
void trackgraph_init(void);
void trackgraph_cleanup(void);

void trackgraph_install_vtables(void);

// DoSnapshot, 0x0024e318, with no section of its own: bHasCloakedEdge in
// one byte, then bIsCloaked in one byte for each edge that is bCloakable.
struct ReplaySnapshot;
void trackgraph_do_snapshot(tTrackGraph *g, struct ReplaySnapshot *s);

#endif
