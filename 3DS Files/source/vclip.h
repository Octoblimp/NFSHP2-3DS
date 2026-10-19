// vclip -- VClip.obj (0x001c5d90 .. 0x001ca008): Mirtich's V-Clip closest-
// feature algorithm, as bWare wrote it for the collision system.
//
// A VCPolyhedron is a convex solid spelled as features -- vertices, edges
// and faces -- each carrying the Voronoi planes that bound its region of
// space, and each plane naming the neighbouring feature that lies across
// it. A VCWitness holds a pair of polyhedra and the feature of each that
// is currently closest to the other. VClip (0x001c8200) walks those two
// features towards each other, one Voronoi-plane violation at a time,
// until each lies in the other's region: then the pair is closest, the two
// points on them are the contact points, and the distance between is the
// separation. The walk reports 1 for disjoint, 2 for penetrating, and 0 if
// it has not settled after 80 steps. Retail's (0x001d2390) also restarts a
// walk that comes back to a pair from one of its last ten steps: from a
// random vertex of each, at most three times.
//
// The record layouts are the stabs', to the byte:
//
//   VCFeature             2  Type (0 vertex, 1 edge, 2 face), NumPlanes
//   VCPlane              16  a normal and a plane distance, plain floats
//                            despite the stab's "Compressed" names
//   VCVoronoiPlane       24  Padding, Plane at 4, Neighbor at 20
//   VCVertex             20  the feature, Padding, position at 4, planes
//                            at 16
//   VCEdge               12  the feature, a direction as three int16s in
//                            units of 2^-13 at 2, planes at 8
//   VCFace               24  the feature, its Plane at 4, planes at 20
//   VCPolyhedron         48  bTNode<VCPolyhedron>, the flags and the counts,
//                            then the four arrays at 32
//   VCTransform          64  one bMatrix4
//   VCTransformedFeature 64  the feature at 0, Head/Tail/Edge at 16/32/48
//   VCVoronoiClip        20  the lambda interval and its two neighbours
//   VCWitness            80  switch state, the features, the polyhedra,
//                            CP1/CP2 at 32/48, Distance at 64
//
// The plane lists are fixed by feature type, and everything below leans on
// it: a vertex's planes are one per edge that meets it; an edge's are four,
// 0 its tail vertex, 1 its head vertex, 2 and 3 its two faces; a face's are
// one per edge around it.
//
// Each record that holds a pointer carries a layout assert, exact on the
// handheld and offset by the wider pointers on a 64-bit host (VC_AT's
// slack count). The memory image that LoaderCollisionVolumes hands to
// MemoryImageLoad is the handheld layout exactly, indices where the
// pointers go.
//
// The Caffeine plot helpers and the Print family are development code: the
// plots have no callers at all, and every Print does nothing but store the
// polyhedron it was given (PrintFeature, PrintMatrix and PrintState are
// each a bare `jr ra`). DoSnapshot is retail's (0x001d0948), TASKS 72b, and
// VClip is retail's (0x001d2390), TASKS 73.
//
// docs/formats/vclip.md has the decode.

#ifndef VCLIP_H
#define VCLIP_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "espresso.h"

typedef struct VCFeature {
    int8_t Type;               // 0
    int8_t NumPlanes;          // 1
} VCFeature;                   // 2

#define VCFEATURE_VERTEX 0
#define VCFEATURE_EDGE   1
#define VCFEATURE_FACE   2

typedef struct VCPlane {
    float CompressedNormal[3];     //  0
    float CompressedPlaneDistance; // 12
} VCPlane;                         // 16

typedef struct VCVoronoiPlane {
    uint16_t   Padding;        //  0
    uint8_t    _pad2[2];       //  2
    VCPlane    Plane;          //  4
    VCFeature *Neighbor;       // 20
} VCVoronoiPlane;              // 24

typedef struct VCVertex {
    VCFeature       Feature;               //  0
    uint16_t        Padding;               //  2
    float           CompressedPosition[3]; //  4
    VCVoronoiPlane *pPlanes;               // 16
} VCVertex;                                // 20

typedef struct VCEdge {
    VCFeature       Feature;                //  0
    int16_t         CompressedDirection[3]; //  2
    VCVoronoiPlane *pPlanes;                //  8
} VCEdge;                                   // 12

typedef struct VCFace {
    VCFeature       Feature;   //  0
    uint8_t         _pad2[2];  //  2
    VCPlane         Plane;     //  4
    VCVoronoiPlane *pPlanes;   // 20
} VCFace;                      // 24

typedef struct VCPolyhedronNode {
    struct VCPolyhedron *next; // 0
    struct VCPolyhedron *prev; // 4
} VCPolyhedronNode;            // 8

typedef struct VCPolyhedron {
    VCPolyhedronNode Link;                 //  0  bTNode<VCPolyhedron>
    int32_t          DynamicallyAllocated; //  8
    void            *pCaffeineObj;         // 12
    int16_t          NumVertices;          // 16
    int16_t          NumEdges;             // 18
    int16_t          NumFaces;             // 20
    int16_t          NumPlanes;            // 22
    int16_t          MaxVertices;          // 24
    int16_t          MaxEdges;             // 26
    int16_t          MaxFaces;             // 28
    int16_t          MaxPlanes;            // 30
    VCVertex        *pVertices;            // 32
    VCEdge          *pEdges;               // 36
    VCFace          *pFaces;               // 40
    VCVoronoiPlane  *pPlanes;              // 44
} VCPolyhedron;                            // 48

typedef struct VCTransform {
    bMatrix4 Matrix;           // 0
} VCTransform;                 // 64

typedef struct VCTransformedFeature {
    VCFeature *pFeature;       //  0
    uint8_t    _pad4[12];      //  4  the quadword round-up
    bVector3   Head;           // 16
    bVector3   Tail;           // 32
    bVector3   Edge;           // 48
} VCTransformedFeature;        // 64

typedef struct VCVoronoiClip {
    float      LambdaMin;      //  0
    float      LambdaMax;      //  4
    VCFeature *NeighborMin;    //  8
    VCFeature *NeighborMax;    // 12
    int32_t    Penetration;    // 16
} VCVoronoiClip;               // 20

typedef struct VCWitness {
    int32_t       SwitchState;   //  0
    VCFeature    *F1;            //  4
    VCFeature    *F2;            //  8
    VCPolyhedron *P1;            // 12
    VCPolyhedron *P2;            // 16
    uint8_t       _pad20[12];    // 20  the quadword round-up
    bVector3      CP1;           // 32
    bVector3      CP2;           // 48
    float         Distance;      // 64
    void         *pCaffeineObj1; // 68
    void         *pCaffeineObj2; // 72
    uint8_t       _pad76[4];     // 76
} VCWitness;                     // 80

// VC_AT(T, f, n, k): offset n on the handheld, plus k pointers' worth of
// slack on a host with wider ones. VC_SIZE is the same for sizeof, rounded
// up to the pointer the way the host's alignment does.
#define VC_SLACK ((size_t)(sizeof(void *) - 4))
#define VC_AT(T, f, n, k) (offsetof(T, f) == (size_t)(n) + (k) * VC_SLACK)
#define VC_SIZE(T, n, k) \
    (sizeof(T) == (((size_t)(n) + (k) * VC_SLACK + sizeof(void *) - 1) \
                   / sizeof(void *) * sizeof(void *)))

#ifndef VCLIP_NO_ASSERT
typedef char vclip_layout_check[
    (sizeof(VCFeature) == 2 && sizeof(VCPlane) == 16
     && VC_AT(VCVoronoiPlane, Plane, 4, 0)
     && VC_AT(VCVoronoiPlane, Neighbor, 20, 1)
     && VC_SIZE(VCVoronoiPlane, 24, 1)
     && VC_AT(VCVertex, CompressedPosition, 4, 0)
     && VC_AT(VCVertex, pPlanes, 16, 0)
     && VC_SIZE(VCVertex, 20, 1)
     && VC_AT(VCEdge, CompressedDirection, 2, 0)
     && VC_AT(VCEdge, pPlanes, 8, 0)
     && VC_SIZE(VCEdge, 12, 1)
     && VC_AT(VCFace, Plane, 4, 0)
     && VC_AT(VCFace, pPlanes, 20, 1)
     && VC_SIZE(VCFace, 24, 1)
     && VC_AT(VCPolyhedron, DynamicallyAllocated, 8, 2)
     && VC_AT(VCPolyhedron, pCaffeineObj, 12, 3)
     && VC_AT(VCPolyhedron, NumVertices, 16, 4)
     && VC_AT(VCPolyhedron, MaxPlanes, 30, 4)
     && VC_AT(VCPolyhedron, pVertices, 32, 4)
     && VC_AT(VCPolyhedron, pPlanes, 44, 7)
     && VC_SIZE(VCPolyhedron, 48, 8)
     && sizeof(VCTransform) == 64
     && VC_AT(VCTransformedFeature, Head, 16, 1)
     && VC_AT(VCTransformedFeature, Edge, 48, 1)
     && VC_SIZE(VCTransformedFeature, 64, 1)
     && VC_AT(VCVoronoiClip, NeighborMin, 8, 0)
     && VC_AT(VCVoronoiClip, Penetration, 16, 2)
     && VC_SIZE(VCVoronoiClip, 20, 2)
     && VC_AT(VCWitness, F1, 4, 1)
     && VC_AT(VCWitness, P2, 16, 4)
     && VC_AT(VCWitness, CP1, 32, 5)
     && VC_AT(VCWitness, Distance, 64, 5)
     && VC_AT(VCWitness, pCaffeineObj2, 72, 6)
     && VC_SIZE(VCWitness, 80, 7)) ? 1 : -1];
#endif

// The gp constants, 0x00321b40..0x00321b5c, in the order the listing uses
// them. Three values, eight slots.
#define VC_VERTEX_MIN_TOUCH   9.99999975e-06f  // gp-28848  ClipVertexPlanes
#define VC_VERTEX_MAX_TOUCH   9.99999975e-06f  // gp-28844  ClipVertexPlanes
#define VC_FACE_MIN_TOUCH     9.99999975e-05f  // gp-28840  ClipFacePlanes
#define VC_FACE_MAX_TOUCH     9.99999975e-05f  // gp-28836  ClipFacePlanes
#define VC_VV_TOUCH           9.99999975e-06f  // gp-28832  CheckVertexVertex
#define VC_VF_TOUCH           9.99999975e-05f  // gp-28828  CheckVertexFace
#define VC_EE_PARALLEL        9.99999997e-07f  // gp-28824  CheckEdgeEdge
#define VC_EF_PARALLEL        9.99999997e-07f  // gp-28820  CheckEdgeFace

// The edge direction's unit: 0x39000000, 2^-13; and its inverse 0x46000000,
// which NewEdge multiplies by before truncating.
#define VC_DIRECTION_SCALE    1.22070312e-04f
#define VC_DIRECTION_UNSCALE  8192.0f

// VClip's step limit, retail's `slti v0,s6,80` at 0x001d2734 (the demo's
// at 0x001c850c), counted again from 0 after each restart.
#define VC_MAX_ITERATIONS     80

// Retail's restarts: a walk stops after its third (`slti v0,s7,3` at
// 0x001d272c), and a pair is looked for among the ten steps before it
// (0x001d2778's count from 9).
#define VC_MAX_RESTARTS       3
#define VC_CYCLE_LOOKBACK     10

// The feature code for "no feature", GetFeatureCode's answer for NULL.
#define VC_NO_FEATURE         0xffffffffu

// The three debug globals the listing touches: gp-18344 and gp-18360 are
// read by VClip, gp-18584 written by Print. The two switches are zero on
// the disc and nothing in the image writes them.
extern int32_t       PrintThisTime;        // 0x00324448
extern int32_t       PlotClosestFeatures;  // 0x00324438
extern VCPolyhedron *pPrintingPolygon;     // 0x00324358

// Retail's restart draws each vertex with World::Random (0x0014e520) on
// pCurrentWorld (gp-22120), so it takes from the world's seed, which the
// replays depend on. main.c binds world_random_i on pCurrentWorld; the
// cross-checker binds its own seed. NULL draws vertex 0.
extern int32_t (*gVClipWorldRandomFn)(int32_t range);

// ---------------------------------------------------------------- transform

// 0x001c5d90. |v1 - v2|: the VU's `vsqrt` of the bracketed sum of squares.
// The original returns a quadword whose x lane is this; every caller reads
// only the x.
float    vc_dist_between(const bVector3 *v1, const bVector3 *v2);

// 0x001c5dc8. The transform from the start frame into the end frame:
// transpose(endr) applied to startr with its translation row moved to
// startt - endt.
void     vctransform_init(VCTransform *x, const bMatrix4 *endr,
                          const bVector3 *endt, const bMatrix4 *startr,
                          const bVector3 *startt);
// 0x001c5e60. bMulMatrix(out, M-with-no-translation, in).
void     vctransform_transform_vector_p(const VCTransform *x, bVector3 *out,
                                        const bVector3 *in);
// 0x001c5ec8 and 0x001c5f20. The fVector3 forms: all four lanes, the rows
// weighted by v's x, y, z (and 1 for the point).
bVector3 vctransform_transform_vector(const VCTransform *x, bVector3 v);
bVector3 vctransform_transform_point(const VCTransform *x, bVector3 v);

// 0x001c5f68 and 0x001c5fd8.
void     vctf_transform_vertex(VCTransformedFeature *tf, const VCTransform *x,
                               VCVertex *v);
void     vctf_transform_edge(VCTransformedFeature *tf, const VCTransform *x,
                             VCEdge *e);

// ---------------------------------------------------------------- clipping

void       vcclip_init(VCVoronoiClip *c);                        // 0x001c6098
int32_t    vcclip_clip_planes(VCVoronoiClip *c, VCTransformedFeature *xedge,
                              VCVoronoiPlane *planes, int32_t n);
                                                                 // 0x001c60c0
VCFeature *vcclip_clip_vertex_planes(VCVoronoiClip *c,
                                     VCTransformedFeature *xedge,
                                     const bVector3 *vert,
                                     VCVoronoiPlane *planes, int32_t n);
                                                                 // 0x001c6228
VCFeature *vcclip_clip_face_planes(VCVoronoiClip *c,
                                   VCTransformedFeature *xedge, VCFace *face,
                                   VCVoronoiPlane *planes, int32_t n);
                                                                 // 0x001c6430

// ---------------------------------------------------------------- witness

void    vcwitness_init(VCWitness *w, VCPolyhedron *p1, VCPolyhedron *p2);
                                                                 // 0x001c6700
void    vcwitness_destroy(VCWitness *w, int32_t flags);          // 0x001c6750
void    vcwitness_print_state(VCWitness *w);                     // 0x001c68a0

// Retail's 0x001d0948, the replay's: a section for the witness named
// "VCWitness" with its two features as their polyhedra's codes (a restore
// looks them up again), SwitchState, the two closest points and the
// distance. The codes are taken from the features even when restoring.
struct ReplaySnapshot;
void    vcwitness_do_snapshot(VCWitness *w, struct ReplaySnapshot *s);

// The five pair checks. x12 takes the first feature into the second's
// frame and x21 the reverse; SwitchState says which of F1/F2 is which.
// Each returns VClip's status: 0 a feature moved, 1 disjoint, 2 touching
// or penetrating.
int32_t vcwitness_check_vertex_vertex(VCWitness *w, VCTransform *x12,
                                      VCTransform *x21,
                                      VCTransformedFeature *xf1,
                                      VCTransformedFeature *xf2);
                                                                 // 0x001c68a8
int32_t vcwitness_check_vertex_edge(VCWitness *w, VCTransform *x12,
                                    VCTransform *x21,
                                    VCTransformedFeature *xf1,
                                    VCTransformedFeature *xf2);
                                                                 // 0x001c6ba0
int32_t vcwitness_check_vertex_face(VCWitness *w, VCTransform *x12,
                                    VCTransform *x21,
                                    VCTransformedFeature *xf1,
                                    VCTransformedFeature *xf2);
                                                                 // 0x001c6ed8
int32_t vcwitness_sub_check_edge_edge(VCWitness *w,
                                      VCTransformedFeature *xf, VCEdge *edge,
                                      int32_t which);            // 0x001c7498
int32_t vcwitness_check_edge_edge(VCWitness *w, VCTransform *x12,
                                  VCTransform *x21,
                                  VCTransformedFeature *xf1,
                                  VCTransformedFeature *xf2);    // 0x001c7578
int32_t vcwitness_check_edge_face(VCWitness *w, VCTransform *x12,
                                  VCTransform *x21,
                                  VCTransformedFeature *xf1,
                                  VCTransformedFeature *xf2);    // 0x001c7ab0

// Retail's 0x001d2390 (the demo's 0x001c8200). r1/t1 place P1 in the
// world and r2/t2 place P2.
int32_t vcwitness_vclip(VCWitness *w, bMatrix4 *r1, bVector3 *t1,
                        bMatrix4 *r2, bVector3 *t2);

// 0x001c9730. No callers.
void    vcwitness_plot_to_caffeine(VCWitness *w, bMatrix4 *m1, bMatrix4 *m2);

// ---------------------------------------------------------------- features

void    vcvertex_set_voronoi_planes(VCVertex *v);                // 0x001c8548
VCEdge *vcvertex_get_next_edge_in_face(VCVertex *v, VCEdge *last,
                                       VCFace *face);            // 0x001c8698
void    vcvertex_move(VCVertex *v, const bVector3 *d);           // 0x001c8730
void    vcedge_set_voronoi_planes(VCEdge *e);                    // 0x001c8790
void    vcface_set_voronoi_planes(VCFace *f);                    // 0x001c8b08
void    vcface_move(VCFace *f, const bVector3 *d);               // 0x001c8df0

// 0x001c92f8. The feature as the corners of one user mesh face, in the
// frame m places it in less m's translation, padded to four by repeating
// the last corner. `out` takes max(4, corners): a face has one corner per
// plane, and NumPlanes is an int8, so VC_MESH_FACE_CORNERS holds any.
#define VC_MESH_FACE_CORNERS 128
void    vcfeature_create_user_mesh_face(VCFeature *f, FloatVector *out,
                                        bMatrix4 *m);

// ---------------------------------------------------------------- polyhedron

VCPolyhedron *vcpoly_init(VCPolyhedron *p);                      // 0x001c8e48
void    vcpoly_init_alloc(VCPolyhedron *p, int32_t max_vertices,
                          int32_t max_edges, int32_t max_faces,
                          int32_t max_planes);                   // 0x001c8e90
void    vcpoly_init_arrays(VCPolyhedron *p, VCVertex *vertices,
                           int32_t max_vertices, VCEdge *edges,
                           int32_t max_edges, VCFace *faces,
                           int32_t max_faces, VCVoronoiPlane *planes,
                           int32_t max_planes);                  // 0x001c8f48
void    vcpoly_destroy(VCPolyhedron *p, int32_t flags);          // 0x001c8f88
void    vcpoly_close(VCPolyhedron *p);                           // 0x001c8fc0
void    vcpoly_memory_image_load(VCPolyhedron *p, VCVertex *vertices,
                                 int32_t num_vertices, VCEdge *edges,
                                 int32_t num_edges, VCFace *faces,
                                 int32_t num_faces, VCVoronoiPlane *planes,
                                 int32_t num_planes);            // 0x001c9068
void    vcpoly_memory_image_unload(VCPolyhedron *p);             // 0x001c90d8

VCVoronoiPlane *vcpoly_new_voronoi_planes(VCPolyhedron *p, int32_t n);
                                                                 // 0x001c90e0
VCVertex *vcpoly_new_vertex(VCPolyhedron *p, const bVector3 *pos,
                            int32_t n, VCVoronoiPlane *planes);  // 0x001c9178
VCEdge   *vcpoly_new_edge(VCPolyhedron *p, const bVector3 *dir, int32_t n,
                          VCVoronoiPlane *planes);               // 0x001c91e0
VCFace   *vcpoly_new_face(VCPolyhedron *p, const bVector3 *normal, float d,
                          int32_t n, VCVoronoiPlane *planes);    // 0x001c9288

void      vcpoly_plot_to_caffeine(VCPolyhedron *p, bMatrix4 *m); // 0x001c9650
void      vcpoly_set_voronoi_planes(VCPolyhedron *p);            // 0x001c9830
uint32_t  vcpoly_get_feature_code(VCPolyhedron *p, VCFeature *f);
                                                                 // 0x001c98f0
VCFeature *vcpoly_get_feature(VCPolyhedron *p, uint32_t code);   // 0x001c99a8
void      vcpoly_convert_to_indicies(VCPolyhedron *p);           // 0x001c9a28
void      vcpoly_convert_to_pointers(VCPolyhedron *p);           // 0x001c9bb0

void      vcpoly_print_feature(VCPolyhedron *p, VCFeature *f);   // 0x001c9d18
void      vcpoly_print(VCPolyhedron *p);                         // 0x001c9d20
void      vcvoronoiplane_print(VCVoronoiPlane *p);               // 0x001c9e38
void      vcvertex_print(VCVertex *v);                           // 0x001c9e70
void      vcedge_print(VCEdge *e);                               // 0x001c9ee8
void      vcface_print(VCFace *f);                               // 0x001c9f88

#endif
