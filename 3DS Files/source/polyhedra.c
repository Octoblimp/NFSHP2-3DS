// polyhedra -- see polyhedra.h.
//
// The vector work is VU0's, lane-wise in the listing's order: a dot product
// is ((x*x' + y*y') + z*z'), and the Wafer's reversed normal is
// `vsub.xyzw vf, vf00, vf` -- 0 - x, which gives +0 for a +0. Where the
// listing assembles a vector on the stack and leaves its fourth lane
// unwritten, the lane goes on into NewVertex, NewEdge or NewFace, which
// read three; the port writes 0 there.
//
// docs/formats/polyhedra.md has the decode.

#include "polyhedra.h"

#include <math.h>
#include <stdint.h>

#include "bmath.h"
#include "bmem.h"
#include "bticker.h"
#include "bchunk.h"
#include "emath.h"

const int32_t RectEdgesNearFaces[6][4] = {
    { 0, 1, 2, 3 }, { 4, 5, 6, 7 }, { 0, 8, 4, 9 },
    { 2, 10, 6, 11 }, { 1, 9, 5, 10 }, { 3, 11, 7, 8 },
};
const int32_t RectEdgesNearVertices[8][3] = {
    { 0, 1, 9 }, { 4, 5, 9 }, { 1, 2, 10 }, { 5, 6, 10 },
    { 3, 0, 8 }, { 7, 4, 8 }, { 2, 3, 11 }, { 6, 7, 11 },
};
const int32_t RectFacesNearEdges[12][2] = {
    { 2, 0 }, { 0, 4 }, { 0, 3 }, { 5, 0 }, { 1, 2 }, { 4, 1 },
    { 3, 1 }, { 1, 5 }, { 2, 5 }, { 4, 2 }, { 3, 4 }, { 5, 3 },
};
const int32_t RectVerticesNearEdges[12][2] = {
    { 0, 4 }, { 0, 2 }, { 2, 6 }, { 4, 6 }, { 1, 5 }, { 1, 3 },
    { 3, 7 }, { 5, 7 }, { 4, 5 }, { 0, 1 }, { 2, 3 }, { 6, 7 },
};
const int32_t WaferEdgesNearFaces[2][4] = {
    { 0, 1, 2, 3 }, { 0, 1, 2, 3 },
};
const int32_t WaferEdgesNearVertices[4][2] = {
    { 0, 3 }, { 0, 1 }, { 1, 2 }, { 2, 3 },
};
const int32_t WaferFacesNearEdges[4][2] = {
    { 0, 1 }, { 0, 1 }, { 0, 1 }, { 1, 0 },
};
const int32_t WaferVerticesNearEdges[4][2] = {
    { 0, 1 }, { 1, 2 }, { 2, 3 }, { 0, 3 },
};
const int32_t TriWaferEdgesNearVertices[4][2] = {
    { 0, 2 }, { 0, 1 }, { 1, 2 }, { 0, 0 },
};
const int32_t TriWaferVerticesNearEdges[4][2] = {
    { 0, 1 }, { 1, 2 }, { 0, 2 }, { 0, 0 },
};

VCPolyhedronNode PipelinePolyhedronList = {
    (VCPolyhedron *)&PipelinePolyhedronList,
    (VCPolyhedron *)&PipelinePolyhedronList,
};

int32_t TestCounter = 5248;

// The list's links. A bTNode is the first thing in a VCPolyhedron, and the
// list head is a node standing alone, so a node and its polyhedron share
// an address and the head passes for a polyhedron wherever only the links
// are touched.
static VCPolyhedronNode *node(VCPolyhedron *p)
{
    return (VCPolyhedronNode *)(void *)p;
}

#define LIST_HEAD ((VCPolyhedron *)(void *)&PipelinePolyhedronList)

static bVector3 vertex_pos(const VCFeature *f)
{
    const VCVertex *v = (const VCVertex *)f;
    bVector3 r;

    r.x = v->CompressedPosition[0];
    r.y = v->CompressedPosition[1];
    r.z = v->CompressedPosition[2];
    r.pad = 0.0f;
    return r;
}

// ------------------------------------------------------------------- Rect

RectPolyhedron *rectpoly_init(RectPolyhedron *r, float xmax, float xmin,
                              float ymax, float ymin, float zmax,
                              float zmin)
{
    VCPolyhedron *p = &r->Poly;
    VCVoronoiPlane *pl;
    bVector3 v;
    int32_t i, k;

    vcpoly_init(p);
    vcpoly_init_arrays(p, r->VertexArray, 8, r->EdgeArray, 12,
                       r->FaceArray, 6, r->PlaneArray, 96);

    for (i = 0; i < 8; i++) {
        v.x = (i & 1) ? xmin : xmax;
        v.y = (i & 2) ? ymin : ymax;
        v.z = (i & 4) ? zmin : zmax;
        v.pad = 0.0f;
        pl = vcpoly_new_voronoi_planes(p, 3);
        for (k = 0; k < 3; k++)
            pl[k].Neighbor = &p->pEdges[RectEdgesNearVertices[i][k]].Feature;
        vcpoly_new_vertex(p, &v, 3, pl);
    }

    for (i = 0; i < 6; i++) {
        float d = 0.0f;

        v.x = 0.0f;
        v.y = 0.0f;
        v.z = 0.0f;
        v.pad = 0.0f;
        (&v.x)[i / 2] = (i & 1) ? -1.0f : 1.0f;
        switch (i) {          // the jump table at 0x0029f250
        case 0: d = xmax;  break;
        case 1: d = -xmin; break;
        case 2: d = ymax;  break;
        case 3: d = -ymin; break;
        case 4: d = zmax;  break;
        case 5: d = -zmin; break;
        }
        pl = vcpoly_new_voronoi_planes(p, 4);
        for (k = 0; k < 4; k++)
            pl[k].Neighbor = &p->pEdges[RectEdgesNearFaces[i][k]].Feature;
        vcpoly_new_face(p, &v, d, 4, pl);
    }

    for (i = 0; i < 12; i++) {
        bVector3 head, tail;
        float extent;

        pl = vcpoly_new_voronoi_planes(p, 4);
        for (k = 0; k < 2; k++) {
            pl[2 + k].Neighbor =
                &p->pFaces[RectFacesNearEdges[i][k]].Feature;
            pl[k].Neighbor =
                &p->pVertices[RectVerticesNearEdges[i][k]].Feature;
        }
        head = vertex_pos(pl[1].Neighbor);
        tail = vertex_pos(pl[0].Neighbor);
        v.x = head.x - tail.x;
        v.y = head.y - tail.y;
        v.z = head.z - tail.z;
        v.pad = 0.0f;
        // The first axis the edge runs along picks the extent it is scaled
        // by; an edge that runs along none is left as it is.
        if (v.x != 0.0f)
            extent = xmax - xmin;
        else if (v.y != 0.0f)
            extent = ymax - ymin;
        else if (v.z != 0.0f)
            extent = zmax - zmin;
        else
            goto store;
        {
            float s = 1.0f / extent;

            v.x = v.x * s;
            v.y = v.y * s;
            v.z = v.z * s;
        }
store:
        vcpoly_new_edge(p, &v, 4, pl);
    }

    vcpoly_set_voronoi_planes(p);
    return r;
}

CubePolyhedron *cubepoly_init(CubePolyhedron *c, float size)
{
    float hi = size * 0.5f;
    float lo = -size * 0.5f;

    return rectpoly_init(c, hi, lo, hi, lo, hi, lo);
}

void rectpoly_destroy(RectPolyhedron *r, int32_t flags)
{
    vcpoly_destroy(&r->Poly, flags);
}

void cubepoly_destroy(CubePolyhedron *c, int32_t flags)
{
    rectpoly_destroy(c, flags);
}

// ------------------------------------------------------------------ Wafer

void waferpoly_init(WaferPolyhedron *w, const TrackPolygon *tp,
                    const bVector3 *origin)
{
    VCPolyhedron *p = &w->Poly;
    VCVoronoiPlane *pl;
    bVector3 v, n;
    int32_t tri, nv, ne, i, k;
    float d;

    tri = bEqual3(&tp->Vertices[2], &tp->Vertices[3],
                  WAFER_TRIANGLE_EPSILON) != 0;
    nv = tri ? 3 : 4;
    ne = tri ? 3 : 4;
    vcpoly_init_arrays(p, w->VertexArray, nv, w->EdgeArray, ne,
                       w->FaceArray, 2, w->PlaneArray, 2 * nv + 4 * ne + 8);

    for (i = 0; i < nv; i++) {
        pl = vcpoly_new_voronoi_planes(p, 2);
        for (k = 0; k < 2; k++) {
            int32_t e = tri ? TriWaferEdgesNearVertices[i][k]
                            : WaferEdgesNearVertices[i][k];

            pl[k].Neighbor = &p->pEdges[e].Feature;
        }
        v.x = tp->Vertices[i].x - origin->x;
        v.y = tp->Vertices[i].y - origin->y;
        v.z = tp->Vertices[i].z - origin->z;
        v.pad = tp->Vertices[i].pad - origin->pad;
        vcpoly_new_vertex(p, &v, 2, pl);
    }

    // The plane's distance, measured from corner 0 as moved.
    v.x = tp->Vertices[0].x - origin->x;
    v.y = tp->Vertices[0].y - origin->y;
    v.z = tp->Vertices[0].z - origin->z;
    d = (tp->Normal.x * v.x + tp->Normal.y * v.y) + tp->Normal.z * v.z;

    // Each face takes four planes whatever it uses, which is why the pool
    // is sized with 8 for the two of them.
    for (i = 0; i < 2; i++) {
        int32_t nf = tri ? 3 : 4;

        pl = vcpoly_new_voronoi_planes(p, 4);
        for (k = 0; k < nf; k++)
            pl[k].Neighbor = &p->pEdges[WaferEdgesNearFaces[i][k]].Feature;
        if (i == 0) {
            n.x = tp->Normal.x;
            n.y = tp->Normal.y;
            n.z = tp->Normal.z;
            n.pad = tp->PlaneDistance;
        } else {
            n.x = 0.0f - tp->Normal.x;
            n.y = 0.0f - tp->Normal.y;
            n.z = 0.0f - tp->Normal.z;
            n.pad = 1.0f - tp->PlaneDistance;
        }
        vcpoly_new_face(p, &n, i != 0 ? -d : d, nf, pl);
    }

    for (i = 0; i < ne; i++) {
        bVector3 head, tail;
        float len2, q;

        pl = vcpoly_new_voronoi_planes(p, 4);
        for (k = 0; k < 2; k++) {
            // A triangle's edges read the face pairs one row down: its
            // closing edge, 0 to 2, is the quad's closing edge, 0 to 3,
            // and runs the other way round the faces.
            int32_t f = WaferFacesNearEdges[tri ? i + 1 : i][k];
            int32_t c = tri ? TriWaferVerticesNearEdges[i][k]
                            : WaferVerticesNearEdges[i][k];

            pl[2 + k].Neighbor = &p->pFaces[f].Feature;
            pl[k].Neighbor = &p->pVertices[c].Feature;
        }
        head = vertex_pos(pl[1].Neighbor);
        tail = vertex_pos(pl[0].Neighbor);
        v.x = head.x - tail.x;
        v.y = head.y - tail.y;
        v.z = head.z - tail.z;
        v.pad = 0.0f;
        // `vrsqrt Q,vf00w,vf01x ; vaddq.x vf01,vf00,Q`: 1/sqrt, plus 0.
        len2 = (v.x * v.x + v.y * v.y) + v.z * v.z;
        q = 0.0f + 1.0f / sqrtf(len2);
        v.x = v.x * q;
        v.y = v.y * q;
        v.z = v.z * q;
        vcpoly_new_edge(p, &v, 4, pl);
    }

    vcpoly_set_voronoi_planes(p);
}

void waferpoly_destroy(WaferPolyhedron *w, int32_t flags)
{
    vcpoly_destroy(&w->Poly, flags);
}

// --------------------------------------------------------------- Pipeline

// The first 16-byte boundary at or after a chunk's payload.
static uint8_t *payload16(uint8_t *chunk)
{
    return (uint8_t *)(((uintptr_t)chunk + 8 + 15) & ~(uintptr_t)15);
}

static uint8_t *next_chunk(uint8_t *chunk)
{
    return chunk + 8 + bchunk_u32(chunk + 4);
}

// A record array's length: the payload less the pad in front of it, over
// the record.
static int32_t records(uint8_t *chunk, uint32_t size)
{
    uint32_t pad = (uint32_t)(payload16(chunk) - (chunk + 8));

    return (int32_t)((bchunk_u32(chunk + 4) - pad) / size);
}

int loader_collision_volumes(uint8_t *chunk)
{
    uint8_t *end, *c;

    if (bchunk_u32(chunk) != CHUNK_COLLISION_VOLUMES)
        return 0;
    end = next_chunk(chunk);
    // The group's chunk ids are not looked at: header, vertices, edges,
    // faces and planes, in that order.
    for (c = chunk + 8; c < end;) {
        uint8_t *cv = next_chunk(c);
        uint8_t *ce = next_chunk(cv);
        uint8_t *cf = next_chunk(ce);
        uint8_t *cp = next_chunk(cf);
        PipelinePolyhedron *pp = (PipelinePolyhedron *)(void *)payload16(c);
        VCPolyhedron *p = &pp->Poly;

        node(p)->prev = PipelinePolyhedronList.prev;
        node(PipelinePolyhedronList.prev)->next = p;
        PipelinePolyhedronList.prev = p;
        node(p)->next = LIST_HEAD;

        vcpoly_memory_image_load(
            p, (VCVertex *)(void *)payload16(cv),
            records(cv, sizeof(VCVertex)),
            (VCEdge *)(void *)payload16(ce), records(ce, sizeof(VCEdge)),
            (VCFace *)(void *)payload16(cf), records(cf, sizeof(VCFace)),
            (VCVoronoiPlane *)(void *)payload16(cp),
            records(cp, sizeof(VCVoronoiPlane)));
        vcpoly_set_voronoi_planes(p);
        c = next_chunk(cp);
    }
    return 1;
}

int unloader_collision_volumes(uint8_t *chunk)
{
    uint8_t *end, *c;

    if (bchunk_u32(chunk) != CHUNK_COLLISION_VOLUMES)
        return 0;
    end = next_chunk(chunk);
    for (c = chunk + 8; c < end; c = next_chunk(c)) {
        VCPolyhedron *p;

        if (bchunk_u32(c) != CHUNK_COLLISION_VOLUME)
            continue;
        p = (VCPolyhedron *)(void *)payload16(c);
        node(p->Link.prev)->next = p->Link.next;
        node(p->Link.next)->prev = p->Link.prev;
        vcpoly_memory_image_unload(p);
    }
    return 1;
}

PipelinePolyhedron *find_pipeline_polyhedron(uint32_t name_hash,
                                             bVector3 *cog)
{
    VCPolyhedron *p;

    for (p = PipelinePolyhedronList.next; p != LIST_HEAD; p = p->Link.next) {
        PipelinePolyhedron *pp = (PipelinePolyhedron *)p;

        if (pp->NameHash != name_hash)
            continue;
        if (cog != NULL && pp->CenterOfGravityFixed == 0)
            pipelinepoly_move_center_of_gravity(pp, cog);
        return pp;
    }
    return NULL;
}

void pipelinepoly_move_center_of_gravity(PipelinePolyhedron *pp,
                                         const bVector3 *cog)
{
    VCPolyhedron *p = &pp->Poly;
    bVector3 d;
    int32_t i;

    d.x = 0.0f - cog->x;
    d.y = 0.0f - cog->y;
    d.z = 0.0f - cog->z;
    d.pad = 1.0f - cog->pad;
    for (i = 0; i < p->NumVertices; i++)
        vcvertex_move(&p->pVertices[i], &d);
    for (i = 0; i < p->NumFaces; i++)
        vcface_move(&p->pFaces[i], &d);
    vcpoly_set_voronoi_planes(p);
    pp->CenterOfGravityFixed = 1;
}

void pipelinepoly_destroy(PipelinePolyhedron *p, int32_t flags)
{
    vcpoly_destroy(&p->Poly, flags);
}

void polyhedra_init_globals(void)
{
    PipelinePolyhedronList.prev = LIST_HEAD;
    PipelinePolyhedronList.next = LIST_HEAD;
}

void polyhedra_close_globals(void)
{
    VCPolyhedron *p;

    while ((p = PipelinePolyhedronList.next) != LIST_HEAD) {
        node(p->Link.prev)->next = p->Link.next;
        node(p->Link.next)->prev = p->Link.prev;
        pipelinepoly_destroy((PipelinePolyhedron *)p, 3);
    }
}

// ------------------------------------------------------------------ tests

void test_cubes(void)
{
    CubePolyhedron c1, c2, *heap;
    VCWitness w;
    bMatrix4 m1, m2;
    bVector3 t1, t2;
    float s1, s2, a1, a2, cos1, sin1, cos2, sin2;

    s1 = bRandomF(100.0f, &bDefaultSeed);
    s2 = bRandomF(100.0f, &bDefaultSeed);
    a1 = bRandomF(360.0f, &bDefaultSeed) * POLY_DEG_TO_RAD;
    a2 = bRandomF(360.0f, &bDefaultSeed) * POLY_DEG_TO_RAD;
    bIdentity(&m1);
    bIdentity(&m2);
    cos1 = bSinF(a1 + POLY_HALF_PI);
    sin1 = bSinF(a1);
    cos2 = bSinF(a2 + POLY_HALF_PI);
    sin2 = bSinF(a2);
    m1.v0.x = cos1;
    m1.v0.y = sin1;
    m1.v1.x = -sin1;
    m1.v1.y = cos1;
    m2.v1.y = cos2;
    m2.v1.z = sin2;
    m2.v2.y = -sin2;
    m2.v2.z = cos2;
    t1.pad = 0.0f;
    t2.pad = 0.0f;
    t1.x = bRandomF(200.0f, &bDefaultSeed) - 100.0f;
    t1.y = bRandomF(200.0f, &bDefaultSeed) - 100.0f;
    t1.z = bRandomF(200.0f, &bDefaultSeed) - 100.0f;
    t2.x = bRandomF(200.0f, &bDefaultSeed) - 100.0f;
    t2.y = bRandomF(200.0f, &bDefaultSeed) - 100.0f;
    t2.z = bRandomF(200.0f, &bDefaultSeed) - 100.0f;

    bGetTicker();
    cubepoly_init(&c1, s1);
    bGetTicker();
    cubepoly_init(&c2, s2);
    bGetTicker();
    bGetTicker();
    heap = (CubePolyhedron *)bMalloc((int)sizeof(CubePolyhedron),
                                     "CubePolyhedron", 0, 16);
    cubepoly_init(heap, s2);
    bGetTicker();
    if (heap != NULL)
        cubepoly_destroy(heap, 3);

    vcwitness_init(&w, &c1.Poly, &c2.Poly);
    bGetTicker();
    vcwitness_vclip(&w, &m1, &t1, &m2, &t2);
    bGetTicker();
    t1.x = t1.x + 30.0f;
    vcwitness_vclip(&w, &m1, &t1, &m2, &t2);
    bGetTicker();
    vcwitness_destroy(&w, 2);
    cubepoly_destroy(&c2, 2);
    cubepoly_destroy(&c1, 2);
}

void init_voronoi_clip(void)
{
    for (;;) {
        bSetRandomSeed((uint32_t)TestCounter + 1000000u, &bDefaultSeed);
        test_cubes();
        // addiu: past INT32_MAX it wraps, which ++ on an int32_t may not.
        TestCounter = (int32_t)((uint32_t)TestCounter + 1u);
    }
}

static void random_row(bVector4 *r)
{
    r->x = bRandomF(1.0f, &bDefaultSeed);
    r->y = bRandomF(1.0f, &bDefaultSeed);
    r->z = bRandomF(1.0f, &bDefaultSeed);
    r->w = 0.0f;
}

void random_location(bVector3 *t, bMatrix4 *m)
{
    random_row(&m->v0);
    random_row(&m->v1);
    random_row(&m->v2);
    m->v3.x = 0.0f;
    m->v3.y = 0.0f;
    m->v3.z = 0.0f;
    m->v3.w = 1.0f;
    eOrthonormalizeMatrix(m, m);
    t->x = bRandomF(50.0f, &bDefaultSeed) - 25.0f;
    t->y = bRandomF(50.0f, &bDefaultSeed) - 25.0f;
    t->z = bRandomF(50.0f, &bDefaultSeed) - 25.0f;
    t->pad = 1.0f;
}

void test_vclip_repeatability_n(int32_t last)
{
    PipelinePolyhedron *pp;
    VCPolyhedron *p;
    VCWitness w, w2;
    bMatrix4 m1, m2, m3, m4;
    bVector3 t1, t2, t3, t4;
    int32_t runs = 0;

    pp = find_pipeline_polyhedron(bchunk_hash("DIABLO_CV"), NULL);
    p = pp != NULL ? &pp->Poly : NULL;
    do {
        int32_t again = 0;

        vcwitness_init(&w, p, p);
        random_location(&t1, &m1);
        random_location(&t2, &m2);
        runs++;
        while (vcwitness_vclip(&w, &m1, &t1, &m2, &t2) == 2) {
            random_location(&t1, &m1);
            random_location(&t2, &m2);
        }
        do {
            vcwitness_init(&w2, p, p);
            random_location(&t3, &m3);
            random_location(&t4, &m4);
            vcwitness_vclip(&w2, &m3, &t3, &m4, &t4);
            vcwitness_vclip(&w2, &m1, &t1, &m2, &t2);
            vcwitness_destroy(&w2, 2);
        } while (again-- > 0);
        vcwitness_destroy(&w, 2);
    } while (!(last < runs));
}

void test_vclip_repeatability(void)
{
    test_vclip_repeatability_n(999999);
}
