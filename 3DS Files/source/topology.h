// topology -- the track's collision surface: TopologyTree, TrackPolygon and
// TopologyCoordinate, Track.obj 0x0014e8b0 .. 0x001509d4.
//
// The surface ships as four chunks inside the track bundle: a quadtree of
// nodes, the squares at its leaves, the polygons, and a table of polygon
// indices that each square slices. TopologyTree holds pointers into those
// chunks (`topotree_loader`) and never copies them. Nothing reads a
// TopologyTreePolygon directly except to build a TrackPolygon from it -- the
// float form, with its vertices unpacked, its normal and its plane -- and
// those live in a 1024-slot pool, reference counted, on one list. A
// TopologyCoordinate is one object's window onto them: the TrackPolygons
// under a box around it, sorted into the ones it can stand on, the vertical
// ones and the upside-down ones, re-gathered whenever it leaves the box.
//
// Everything is spelled as the .mdebug has it (`TopologyTree (size=40)`,
// `TrackPolygon (size=128)`, `TopologyCoordinate (size=560)`), and the
// three records that hold pointers carry layout asserts: each is exact on
// the handheld, and on a 64-bit host every offset past a widened pointer
// moves by a counted number of slack units, the way wheel.h's records do.
// A slot pool of TrackPolygons is sized by sizeof, so the host pool is
// 144-byte slots where the image's are 128; slot *numbers* are what cross
// between the two, and they agree.
//
// The list links are bNode's two words, kept as p32 handles (p32.h) so the
// layout is the image's on both. The two pointers a TrackPolygon carries --
// back to its TopologyTreePolygon, and to a collision body -- are real
// pointers: fifteen thousand polygons would overflow the host's handle
// registry, and neither is ever on a list.
//
// Written up in docs/formats/topology.md.

#ifndef TOPOLOGY_H
#define TOPOLOGY_H

#include <stddef.h>
#include <stdint.h>

#include "bslotpool.h"
#include "bvector.h"

// A bNode: Next then Prev, as p32 handles. The list heads are the same two
// words standing alone -- bTList<T> is a bList, which is a bNode.
typedef struct TrackListNode {
    uint32_t pNext;
    uint32_t pPrev;
} TrackListNode;

// ------------------------------------------------------ the chunk records

// 8 bytes, chunk 0x34130. The quadtree: four child numbers, into the node
// table above the leaves and into the square table at them. 0 is "none".
typedef struct TopologyTreeNode {
    uint16_t ChildrenNodeNumbers[4];
} TopologyTreeNode;

// 12 bytes, chunk 0x34131. A leaf: its polygons are
// pPolygonIndexTable[FirstPolygonIndex .. FirstPolygonIndex + NumPolygons).
typedef struct TopologyTreeSquare {
    bVector2 Center;
    uint16_t FirstPolygonIndex;
    int16_t  NumPolygons;
} TopologyTreeSquare;

// 32 bytes, chunk 0x34132. Vertices in fixed point: x and y are
// (v << 13) / 65536, z is ((v << 8) + (ZBase << 16)) / 65536 -- times four
// when Flags has bit 2. MaxMinBits picks the bounding box out of the four
// vertices, two bits per bound: min x, min y, max x, max y from the low
// bits up. TrackPolygonNumber is the slot of the TrackPolygon built from
// this one, or -1; the loader writes -1 over every entry, so the chunk is
// read-write.
typedef struct TopologyTreePolygon {
    int8_t   UsedByNeighbourFlag;   //  0  set while a build has it listed
    uint8_t  MaxMinBits;            //  1
    uint8_t  Type;                  //  2  the TerrainType
    uint8_t  Flags;                 //  3  TRACKPOLY_*
    int16_t  ZBase;                 //  4
    int16_t  TrackPolygonNumber;    //  6
    int16_t  VerticesX[4];          //  8
    int16_t  VerticesY[4];          // 16
    int16_t  VerticesZ[4];          // 24
} TopologyTreePolygon;              // 32

// The Flags bits the code tests. Bit 0 makes GetElevation keep looking for
// a higher surface, bit 1 is a wall, bit 2 scales z by four, bit 3 is a
// ceiling, bit 4 makes the polygon a quad. TRACKB12 uses 0, 1, 8, 16, 17,
// 18, 22 and 24, and never 2 with 8.
#define TRACKPOLY_INFINITELY_HIGH 0x01u
#define TRACKPOLY_VERTICAL        0x02u
#define TRACKPOLY_Z_TIMES_FOUR    0x04u
#define TRACKPOLY_UPSIDE_DOWN     0x08u
#define TRACKPOLY_QUAD            0x10u

// ---------------------------------------------------------- TrackPolygon

// .mdebug type#1637: twelve bytes. GetNormal hands out its address as a
// bVector3 *, so a four-lane read of it picks up PlaneDistance as the pad,
// and GetElevation's copy-out does exactly that.
typedef struct TrackPolygonNormal {
    float x, y, z;
} TrackPolygonNormal;

struct TrackPolygonCollisionBody;

// 128 bytes on the handheld.
typedef struct TrackPolygon {
    TrackListNode node;                             //   0  on the tree's list
    uint8_t  ReferenceCount;                        //   8
    uint8_t  NumVertices;                           //   9  3, or 4 for a quad
    uint8_t  Flags;                                 //  10  TRACKPOLY_*
    uint8_t  TheTerrainType;                        //  11
    TopologyTreePolygon *pPolygon;                  //  12
    struct TrackPolygonCollisionBody *pCollisionBody; // 16  zeroed, then
                                                    //      left to others
    bVector2 BBoxMin;                               //  20
    bVector2 BBoxMax;                               //  28
    uint8_t  _pad0[12];                             //  36  bVector3 is
                                                    //      16-aligned on the EE
    bVector3 Vertices[4];                           //  48
    TrackPolygonNormal Normal;                      // 112
    float    PlaneDistance;                         // 124
} TrackPolygon;                                     // 128

// One slack unit for the alignment pad in front of pPolygon, one for
// pPolygon widening, one for pCollisionBody widening; everything from
// BBoxMin on carries all three, and the size rounds up to the pointer.
#define TOPOLOGY_SLACK ((size_t)(sizeof(void *) - 4))
#define TRACKPOLYGON_SIZEOF                                                 \
    ((size_t)((128 + 3 * TOPOLOGY_SLACK + sizeof(void *) - 1)               \
              / sizeof(void *) * sizeof(void *)))

#ifndef TOPOLOGY_NO_ASSERT
typedef char trackpolygon_layout_check[
    (offsetof(TrackPolygon, ReferenceCount) == 8
     && offsetof(TrackPolygon, NumVertices) == 9
     && offsetof(TrackPolygon, Flags) == 10
     && offsetof(TrackPolygon, TheTerrainType) == 11
     && offsetof(TrackPolygon, pPolygon) == 12 + 1 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, pCollisionBody) == 16 + 2 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, BBoxMin) == 20 + 3 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, BBoxMax) == 28 + 3 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, Vertices) == 48 + 3 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, Normal) == 112 + 3 * TOPOLOGY_SLACK
     && offsetof(TrackPolygon, PlaneDistance) == 124 + 3 * TOPOLOGY_SLACK
     && sizeof(TrackPolygon) == TRACKPOLYGON_SIZEOF
     && sizeof(TopologyTreePolygon) == 32
     && offsetof(TopologyTreePolygon, TrackPolygonNumber) == 6
     && offsetof(TopologyTreePolygon, VerticesZ) == 24
     && sizeof(TopologyTreeSquare) == 12
     && offsetof(TopologyTreeSquare, NumPolygons) == 10
     && sizeof(TopologyTreeNode) == 8) ? 1 : -1];
#endif

// ---------------------------------------------------------- TopologyTree

// 40 bytes on the handheld: four chunk pointers, their counts, and the list
// of every TrackPolygon built so far, oldest first.
typedef struct TopologyTree {
    TopologyTreeNode    *pNodeTable;            //  0
    int32_t              NumNodes;              //  4
    TopologyTreeSquare  *pSquareTable;          //  8
    int32_t              NumSquares;            // 12
    TopologyTreePolygon *pPolygonTable;         // 16
    int32_t              NumPolygons;           // 20
    uint16_t            *pPolygonIndexTable;    // 24
    int32_t              NumPolygonIndicies;    // 28
    TrackListNode        TrackPolygonList;      // 32
} TopologyTree;                                 // 40

#ifndef TOPOLOGY_NO_ASSERT
typedef char topologytree_layout_check[
    (offsetof(TopologyTree, NumNodes) == 4 + 1 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, pSquareTable) == 8 + 2 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, NumSquares) == 12 + 3 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, pPolygonTable) == 16 + 4 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, NumPolygons) == 20 + 5 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, pPolygonIndexTable) == 24 + 6 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, NumPolygonIndicies) == 28 + 7 * TOPOLOGY_SLACK
     && offsetof(TopologyTree, TrackPolygonList) == 32 + 7 * TOPOLOGY_SLACK
     && sizeof(TopologyTree) == 40 + 8 * TOPOLOGY_SLACK) ? 1 : -1];
#endif

// ---------------------------------------------------- TopologyCoordinate

#define TOPOLOGY_MAX_POLYGONS 128

// 560 bytes on the handheld. Car embeds one at 1280 (car.h). The table is
// partitioned: [0, Num) are the polygons GetElevation searches, then the
// vertical ones, then the upside-down ones, Total in all -- except that
// NumUpsideDownTrackPolygons is not what its name says; see
// topology_set_interest_bbox.
typedef struct TopologyCoordinate {
    bVector2      InterestBBoxMin;                       // 0
    bVector2      InterestBBoxMax;                       // 8
    bVector2      CachedBBoxMin;                         // 16
    bVector2      CachedBBoxMax;                         // 24
    TrackPolygon *TrackPolygonTable[TOPOLOGY_MAX_POLYGONS]; // 32
    int32_t       TotalNumTrackPolygons;                 // 544
    int32_t       NumTrackPolygons;                      // 548
    int32_t       NumVerticalTrackPolygons;              // 552
    int32_t       NumUpsideDownTrackPolygons;            // 556
} TopologyCoordinate;                                    // 560

// On a 64-bit host the 128 pointers widen and nothing else does, so every
// offset past the table shifts by exactly 128 slack units and the size
// follows.
#define TOPOLOGY_SIZEOF ((size_t)(560 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK))

#ifndef TOPOLOGY_NO_ASSERT
typedef char topology_layout_check[
    (offsetof(TopologyCoordinate, InterestBBoxMin)  == 0
     && offsetof(TopologyCoordinate, InterestBBoxMax) == 8
     && offsetof(TopologyCoordinate, CachedBBoxMin)   == 16
     && offsetof(TopologyCoordinate, CachedBBoxMax)   == 24
     && offsetof(TopologyCoordinate, TrackPolygonTable) == 32
     && offsetof(TopologyCoordinate, TotalNumTrackPolygons)
        == 544 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumTrackPolygons)
        == 548 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumVerticalTrackPolygons)
        == 552 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumUpsideDownTrackPolygons)
        == 556 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && sizeof(TopologyCoordinate) == TOPOLOGY_SIZEOF) ? 1 : -1];
#endif

// ------------------------------------------------------------ the globals

// 0x002f14c8. The one tree; every TopologyCoordinate method reaches it by
// address rather than through a member.
extern TopologyTree TheTopologyTree;

// 0x00323424. Made by topotree_init_tree, NULL until then and after
// topotree_close_tree.
extern BSlotPool *TrackPolygonSlotPool;

// 0x002f1530 and 0x00323418. GetElevation's own profile: the milliseconds
// each call took, in a ring of ten, and the running count that indexes it.
extern float    TopologyTiming[10];
extern uint32_t TopologyTimingIndex;

// ---------------------------------------------------------- TrackPolygon

// 0x0014e8b0. Builds `tp` from `p` and writes tp's slot number back into
// p->TrackPolygonNumber. The node words are left alone -- the caller links
// it -- and so is the collision body past being zeroed.
TrackPolygon *trackpolygon_init(TrackPolygon *tp, TopologyTreePolygon *p);

// 0x0014eb78. Marks the TopologyTreePolygon unbuilt again (number -1) and,
// with bit 0 of `flags`, frees the slot. Does not unlink.
void trackpolygon_destroy(TrackPolygon *tp, int flags);

// 0x0014ebe0. Is `pt` inside the prism the polygon's edges sweep along its
// normal? With `dist`, also writes the signed distance from the plane.
int trackpolygon_point_in_shaft(const TrackPolygon *tp, const bVector3 *pt,
                                float *dist);

// 0x0014ed98. Does segment a-b cross the polygon? Writes the crossing to
// `out` (all four lanes) when it does and `out` is not NULL.
int trackpolygon_segment_intersects(const TrackPolygon *tp, const bVector3 *a,
                                    const bVector3 *b, bVector3 *out);

// 0x0014ee90. The segment test with a bounding-box reject in front and a
// nearest-so-far behind: 1, and *best lowered, only for a crossing nearer a
// than *best -- and, unless `twoSided`, only for a move against the normal,
// which is one from the side the polygon faces.
int trackpolygon_test_segment(const TrackPolygon *tp, float *best,
                              const bVector3 *a, const bVector3 *b,
                              const bVector3 *bmin, const bVector3 *bmax,
                              int twoSided);

// ---------------------------------------------------- TopologyCoordinate

// 0x0014f030 / 0x0014f068. The destructor releases the table; it has no
// delete flag here because nothing heap-allocates one.
void topology_init(TopologyCoordinate *tc);
void topology_destroy(TopologyCoordinate *tc);

// 0x0014f0c8. Empties both boxes and the table.
void topology_clear_interest_bbox(TopologyCoordinate *tc);

// 0x0014f120. Makes the interest box `pos` +/- `r`, and when that is not
// inside the cached box, gathers a new cache: `pos` +/- (r + 0.5), grown
// towards `pos + vel * s` for the largest s in 0.5, 0.25, ... (ten tries)
// that keeps the box's diagonal under 32. `vel` may be NULL.
void topology_set_interest_bbox(TopologyCoordinate *tc, const bVector2 *pos,
                                float r, const bVector2 *vel);

// 0x00134f28. The bVector3 overload, which Car, the cameras and the movers
// call: the same box, from pos's and vel's x and y.
void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel);

// 0x0014f418. The height of the ground under `pt`: the highest surface
// below pt.z + 1, else the highest at all, else pt.z itself. `terrain`,
// `normal` and `found` may each be NULL. The normal is four lanes, the
// plane distance in the fourth; with no surface it is (0, 0, -1) and the
// fourth lane is not written.
float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found);

// 0x0014f7e8. Is there any surface under (x, y)?
int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy);

// 0x0014f830. Does segment a-b cross any cached polygon, from the side it
// faces?
int topology_segment_intersects(TopologyCoordinate *tc, const bVector3 *a,
                                const bVector3 *b, float r);

// 0x0014f920. eConstraintType. BY_ROTATION turns the move: short of a wall
// it keeps the length to `dist` before the crossing and lifts the end by
// `lift`, scaled by how much of the move was cut; over a floor or under a
// ceiling it puts the end `dist` off the plane. BY_SCALE shortens the move
// to `dist` before the crossing and keeps its direction.
enum {
    TOPOLOGY_CONSTRAIN_BY_ROTATION = 0,
    TOPOLOGY_CONSTRAIN_BY_SCALE    = 1
};

// Returns 1 when the move from `from` to `to` crossed a polygon, having
// moved `to`; 0, and `to` untouched, when it did not. A type other than
// the two returns 1 and moves nothing.
int topology_constrain(TopologyCoordinate *tc, int type, int twoSided,
                       const bVector3 *from, bVector3 *to, float dist,
                       float lift);

// ---------------------------------------------------------- TopologyTree

// 0x0014fb80. Empties the tree: no chunks, the list pointing at itself.
void topotree_init(TopologyTree *t);

// 0x0014fbb8 / 0x0014fc00. The pool: made with neither overflow nor
// zeroing, and closed by destroying every TrackPolygon still listed.
void topotree_init_tree(TopologyTree *t);
void topotree_close_tree(TopologyTree *t);

// 0x0014fc78 / 0x0014fd98. One of the four chunks, header and all. 1 when
// it was one of them. The loader writes -1 into every polygon's
// TrackPolygonNumber.
int topotree_loader(TopologyTree *t, uint8_t *chunk);
int topotree_unloader(TopologyTree *t, const uint8_t *chunk);

// 0x0014fe18. Rounds down to the 32-unit grid, through Q16.
float topotree_get_square_corner(float f);

// 0x0014fe70. The leaf under (x, y), walking ten levels down from a
// 32768-unit root at -16384. With `nearest`, an empty child is replaced by
// the node's first non-empty one; without, it ends the walk with NULL.
TopologyTreeSquare *topotree_get_square(const TopologyTree *t, float x,
                                        float y, int nearest);

// 0x0014ffa0. Appends to `out`, up to `max`, the square's polygons whose
// boxes touch [bmin, bmax] and that no earlier square listed, marking each.
int topotree_get_intersecting_polygons(const TopologyTree *t,
                                       TopologyTreePolygon **out, int max,
                                       const TopologyTreeSquare *sq,
                                       const bVector2 *bmin,
                                       const bVector2 *bmax);

// 0x00150110. Destroys up to 101 TrackPolygons nobody holds.
void topotree_flush_unused(TopologyTree *t);

// 0x001501b0 / 0x00150250. Take and release a reference, building the
// TrackPolygon on first use.
TrackPolygon *topotree_assign(TopologyTree *t, TopologyTreePolygon *p);
void topotree_unassign(TopologyTree *t, TrackPolygon *tp);

// 0x00150260. Fills `out` with a referenced TrackPolygon for every polygon
// under [bmin, bmax], from the up to four squares its corners fall in.
// `max` is at most 128. Returns the count.
int topotree_build(TopologyTree *t, TrackPolygon **out, int max,
                   const bVector2 *bmin, const bVector2 *bmax);

// 0x00150420. Releases `n` references.
void topotree_remove(TopologyTree *t, TrackPolygon **table, int n);

#endif // TOPOLOGY_H
