// polyhedra -- polyhedra.cpp (0x00205058 .. 0x00206440): the convex
// polyhedra the collision bodies hand to VClip, and the loader for the ones
// that come off the disc.
//
// Three kinds, each a VCPolyhedron with its arrays behind it:
//
//   RectPolyhedron      2800  an axis-aligned box, built from its six
//                             bounds. CarCollisionBody and Smokeable make
//                             one when no collision volume is named for
//                             them. CubePolyhedron is the same record; its
//                             constructor is inline and is a box of half
//                             the size each way.
//   WaferPolyhedron      992  a track polygon given two faces, one each way
//                             up, so VClip can treat it as a solid of no
//                             thickness. TrackPolygonCollisionBody's.
//   PipelinePolyhedron    96  a collision volume from the art pipeline: a
//                             chunk 0x80034020 in a car's GEOMETRY.BIN,
//                             INGAMEB.BUN or a track bundle. The record is
//                             the chunk's own bytes, found by name hash.
//
// The Rect and Wafer builders lay the features out by table. The Voronoi
// plane lists follow vclip.h's rule: a vertex's are its edges, an edge's
// are its tail and head vertices then its two faces, a face's are the
// edges around it. The tables give each neighbour; the planes themselves
// are left to SetVoronoiPlanes.
//
// On the handheld every record here is the image's layout. On a 64-bit host
// the pointers widen, and the asserts below allow for it the way vclip.h's
// do. A loaded PipelinePolyhedron is the chunk's bytes, so the loader's
// strides are the records' sizes: exact on the handheld, and the host's own
// on the host, where tools/src/polyhedra_test.c widens a disc chunk before
// handing it over.
//
// TestCubes, InitVoronoiClip, RandomLocation and TestVClipRepeatability are
// timing and soak tests. Nothing calls them: InitVoronoiClip never returns,
// and TestVClipRepeatability runs a million VClips and checks none of
// them. They are ported because they are in the image.
//
// docs/formats/polyhedra.md has the decode.

#ifndef POLYHEDRA_H
#define POLYHEDRA_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "topology.h"
#include "vclip.h"

// 2800 bytes on the handheld.
typedef struct RectPolyhedron {
    VCPolyhedron   Poly;              //    0
    VCVertex       VertexArray[8];    //   48
    VCEdge         EdgeArray[12];     //  208
    VCFace         FaceArray[6];      //  352
    VCVoronoiPlane PlaneArray[96];    //  496
} RectPolyhedron;                     // 2800

// The stabs give CubePolyhedron its own name and no members.
typedef RectPolyhedron CubePolyhedron;

// 992 bytes on the handheld. Four of everything, for a quad; a triangle
// leaves the last of each unused.
typedef struct WaferPolyhedron {
    VCPolyhedron   Poly;              //    0
    VCVertex       VertexArray[4];    //   48
    VCEdge         EdgeArray[4];      //  128
    VCFace         FaceArray[2];      //  176
    VCVoronoiPlane PlaneArray[32];    //  224
} WaferPolyhedron;                    //  992

// 96 bytes on the handheld: the header record of a collision volume, as it
// lies in the chunk. The disc leaves junk in Link and in the four array
// pointers, and the tool's own maxima in Max*; LoaderCollisionVolumes
// overwrites them all. CenterOfGravityFixed is 0 on the disc and goes to
// 1 the first time FindPipelinePolyhedron is asked to move it.
typedef struct PipelinePolyhedron {
    VCPolyhedron Poly;                  //  0
    uint32_t     NameHash;              // 48  bStringHash(Name)
    char         Name[32];              // 52
    int32_t      CenterOfGravityFixed;  // 84
    uint8_t      dummy[8];              // 88
} PipelinePolyhedron;                   // 96

#ifndef POLYHEDRA_NO_ASSERT
// Each array starts where the one before it ends, on both targets; on the
// handheld the offsets are the image's exactly.
#define PH_NEXT(T, a, b) \
    (offsetof(T, b) == offsetof(T, a) + sizeof(((T *)0)->a))
typedef char polyhedra_layout_check[
    (PH_NEXT(RectPolyhedron, Poly, VertexArray)
     && PH_NEXT(RectPolyhedron, VertexArray, EdgeArray)
     && PH_NEXT(RectPolyhedron, EdgeArray, FaceArray)
     && PH_NEXT(RectPolyhedron, FaceArray, PlaneArray)
     && PH_NEXT(WaferPolyhedron, Poly, VertexArray)
     && PH_NEXT(WaferPolyhedron, VertexArray, EdgeArray)
     && PH_NEXT(WaferPolyhedron, EdgeArray, FaceArray)
     && PH_NEXT(WaferPolyhedron, FaceArray, PlaneArray)
     && VC_AT(PipelinePolyhedron, NameHash, 48, 8)
     && VC_AT(PipelinePolyhedron, Name, 52, 8)
     && VC_AT(PipelinePolyhedron, CenterOfGravityFixed, 84, 8)
     && VC_AT(PipelinePolyhedron, dummy, 88, 8)
     && VC_SIZE(PipelinePolyhedron, 96, 8)
#if UINTPTR_MAX == 0xffffffffu
     && sizeof(RectPolyhedron) == 2800
     && offsetof(RectPolyhedron, EdgeArray) == 208
     && offsetof(RectPolyhedron, FaceArray) == 352
     && offsetof(RectPolyhedron, PlaneArray) == 496
     && sizeof(WaferPolyhedron) == 992
     && offsetof(WaferPolyhedron, EdgeArray) == 128
     && offsetof(WaferPolyhedron, FaceArray) == 176
     && offsetof(WaferPolyhedron, PlaneArray) == 224
#endif
     ) ? 1 : -1];
#undef PH_NEXT
#endif

// The chunk ids. The container holds groups of five: the header, then
// vertices, edges, faces and planes, each record array starting on the
// first 16-byte boundary of its payload.
#define CHUNK_COLLISION_VOLUMES   0x80034020u
#define CHUNK_COLLISION_VOLUME    0x00034021u  // the PipelinePolyhedron
#define CHUNK_CV_FACES            0x00034022u
#define CHUNK_CV_EDGES            0x00034023u
#define CHUNK_CV_VERTICES         0x00034024u
#define CHUNK_CV_PLANES           0x00034025u

// gp-27804: the tolerance WaferPolyhedron::Init tests the last two corners
// against. A polygon whose fourth corner is its third is a triangle.
#define WAFER_TRIANGLE_EPSILON    0.001f

// gp-27800 and gp-27796: TestCubes's degrees to radians, and the quarter
// turn it adds to make a sine a cosine. Neither is quite what its name
// says: 0x3c8efa36 and 0x3fc90fdc, each one ulp above the float nearest
// pi/180 and pi/2.
#define POLY_DEG_TO_RAD           0.017453294f
#define POLY_HALF_PI              1.5707965f

// The builders' tables, 0x00313a08 .. 0x00313c48. For each feature, the
// neighbours its Voronoi planes face, in plane order.
extern const int32_t RectEdgesNearFaces[6][4];         // 0x00313a08
extern const int32_t RectEdgesNearVertices[8][3];      // 0x00313a68
extern const int32_t RectFacesNearEdges[12][2];        // 0x00313ac8
extern const int32_t RectVerticesNearEdges[12][2];     // 0x00313b28
extern const int32_t WaferEdgesNearFaces[2][4];        // 0x00313b88
extern const int32_t WaferEdgesNearVertices[4][2];     // 0x00313ba8
extern const int32_t WaferFacesNearEdges[4][2];        // 0x00313bc8
extern const int32_t WaferVerticesNearEdges[4][2];     // 0x00313be8
extern const int32_t TriWaferEdgesNearVertices[4][2];  // 0x00313c08
extern const int32_t TriWaferVerticesNearEdges[4][2];  // 0x00313c28

// 0x00324a30: every loaded collision volume, in load order. A bTList: the
// head is a bare node, linked to itself when empty.
extern VCPolyhedronNode PipelinePolyhedronList;

// 0x00324a28: InitVoronoiClip's seed counter. 5248 on the disc.
extern int32_t TestCounter;

// ------------------------------------------------------------------- Rect

// 0x00205058. The eight corners are the bounds picked by the index's bits
// (bit 0 x, bit 1 y, bit 2 z; clear is max). Face 2k+1 faces -axis k.
// Each edge's direction is its head less its tail, divided by the extent
// along the first axis it runs along -- so +/-1 on that axis for a proper
// box, and left unscaled if all three differences are zero.
RectPolyhedron *rectpoly_init(RectPolyhedron *r, float xmax, float xmin,
                              float ymax, float ymin, float zmax,
                              float zmin);

// Inline in the image (TestCubes, 0x00205a1c): a Rect of +/-size/2 each way,
// the negative bound worked as (-size) * 0.5.
CubePolyhedron *cubepoly_init(CubePolyhedron *c, float size);

// 0x00206418 and 0x00206410. Both are VCPolyhedron's destructor.
void rectpoly_destroy(RectPolyhedron *r, int32_t flags);
void cubepoly_destroy(CubePolyhedron *c, int32_t flags);

// ------------------------------------------------------------------ Wafer

// 0x00205470. tp's corners less origin; a triangle when corners 2 and 3
// are bEqual within WAFER_TRIANGLE_EPSILON. Face 0 is tp's plane and face 1
// the same plane facing the other way. Edge directions are normalised by
// the VU's 1/sqrt.
void waferpoly_init(WaferPolyhedron *w, const TrackPolygon *tp,
                    const bVector3 *origin);

// 0x001cebc0, in CollisionBody.obj: VCPolyhedron's destructor.
void waferpoly_destroy(WaferPolyhedron *w, int32_t flags);

// --------------------------------------------------------------- Pipeline

// 0x00205c00. Links and loads every volume in a 0x80034020 container, in
// place: the header record is the polyhedron, the four arrays behind it
// are its features. Answers 0 for any other chunk and 1 otherwise.
int  loader_collision_volumes(uint8_t *chunk);

// 0x00205db0. Unlinks and unloads every 0x34021 volume in the container.
int  unloader_collision_volumes(uint8_t *chunk);

// 0x00205e68. The first volume in the list with this name hash, or NULL.
// When cog is given and the volume's has not been fixed yet, it is moved
// there first.
PipelinePolyhedron *find_pipeline_polyhedron(uint32_t name_hash,
                                             bVector3 *cog);

// 0x00205ed0. Every vertex and face moved by 0 - cog, the Voronoi planes
// rebuilt, and CenterOfGravityFixed set.
void pipelinepoly_move_center_of_gravity(PipelinePolyhedron *p,
                                         const bVector3 *cog);

// 0x00206408. VCPolyhedron's destructor.
void pipelinepoly_destroy(PipelinePolyhedron *p, int32_t flags);

// 0x002063f8 (_GLOBAL_$I$): PipelinePolyhedronList linked to itself.
void polyhedra_init_globals(void);

// 0x002063e8 (_GLOBAL_$D$), through ~bTList<PipelinePolyhedron> at
// 0x00206378: each volume still listed is unlinked and destroyed with
// flags 3 -- which frees it, though it lives in a chunk. The console never
// runs its static destructors, and nothing on the handheld calls this.
void polyhedra_close_globals(void);

// ------------------------------------------------------------------ tests

// 0x00205860. Two cubes, one of each random size up to 100 and turned at
// random, placed within +/-100 of the origin: VClip, then VClip again 30
// further along x. A third cube is made on the heap and deleted unused.
// Each step is bracketed by bGetTicker, and every result is thrown away.
void test_cubes(void);

// 0x00205bc0. Reseeds from TestCounter + 1000000 and runs TestCubes,
// forever.
void init_voronoi_clip(void);

// 0x00205f90. A random orthonormal turn (three rows of bRandom(1) through
// eOrthonormalizeMatrix) and a position within +/-25 of the origin. The
// position's fourth lane is 1.0, left in the scratch quadword by the
// matrix's last row.
void random_location(bVector3 *t, bMatrix4 *m);

// 0x00206140. DIABLO_CV against itself, 1000000 times: a pair of random
// poses re-rolled until VClip does not report penetration, then a fresh
// witness run at one more random pair and then at the first. Nothing is
// compared. The inner loop is a do-while whose counter starts at 0 and is
// tested after a decrement, so it runs once.
void test_vclip_repeatability(void);

// The same with the outer count given, for the harness: the image's is the
// `lui 0xf ; ori 0x423f` pair, 999999, tested with slt after the increment.
void test_vclip_repeatability_n(int32_t last);

#endif
