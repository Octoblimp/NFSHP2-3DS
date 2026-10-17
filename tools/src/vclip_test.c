// vclip_test -- the harness tools/vclip_check.py runs against VClip.obj's
// port, 3DS Files/source/vclip.c.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints. The
// polyhedra are built here through the port's own New* calls, the same
// calls the model makes in the image: the records hold pointers, so the
// host's are wider than the handheld's, and only a transcript that names
// every feature by polyhedron, kind and index can be compared. The names
// are worked out here from the arrays' bounds -- not by
// vcpoly_get_feature_code, which is under test.
//
// A feature reference in the script is (poly << 24) | (kind << 16) | index,
// kind 0 vertex, 1 edge, 2 face; 0xffffffff is NULL.
//
// bMalloc and bFree go through logging hooks, and the five Espresso calls
// through logging seams that hand out handles 1, 2, 3...

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "espresso.h"
#include "vclip.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

enum {
    OP_TAG = 1, OP_POLY_CTOR, OP_POLY_ALLOC, OP_POLY_ARRAYS, OP_NEW_PLANES,
    OP_NEW_VERTEX, OP_NEW_EDGE, OP_NEW_FACE, OP_SET_NB, OP_SET_VORONOI,
    OP_SET_VORONOI_ONE, OP_DUMP_POLY, OP_MOVE_VERTEX, OP_MOVE_FACE,
    OP_NEXT_EDGE, OP_GET_CODE, OP_GET_FEATURE, OP_POKE_TYPE, OP_TO_INDICES,
    OP_TO_POINTERS, OP_DUMP_RAW, OP_MEMIMAGE_LOAD, OP_UNLOAD, OP_CLOSE,
    OP_DESTROY, OP_WIT_INIT, OP_WIT_SET, OP_VCLIP, OP_WIT_DESTROY,
    OP_WIT_PLOT, OP_POLY_PLOT, OP_ESP_NULL, OP_MESH_FACE, OP_XFORM, OP_XVEC,
    OP_XPT, OP_XVECP, OP_DIST, OP_XF_SET, OP_XF_EDGE, OP_XF_VERTEX,
    OP_CLIP_INIT, OP_CLIP_SET, OP_CLIP_PLANES, OP_CLIP_VERT, OP_CLIP_FACE,
    OP_FLAGS, OP_PRINT, OP_DUMP_WIT, OP_CHECK,
};

#define NPOLY 8
#define NWIT  8
#define NO_REF 0xffffffffu
#define CP_SENTINEL 0x40e00000u     // 7.0f, in both fourth lanes before VClip

static FILE *script;

static VCPolyhedron polys[NPOLY];
static int          dead[NPOLY];    // left out of the naming search
static VCWitness    wits[NWIT];
static int          tainted[NWIT][2];   // a fourth lane VClip left as junk

static VCTransform          X;
static VCTransformedFeature XF;
static VCVoronoiClip        C;

static uint32_t next(void)
{
    unsigned int w;

    if (fscanf(script, "%x", &w) != 1) {
        fprintf(stderr, "script ends inside an op\n");
        exit(2);
    }
    return (uint32_t)w;
}

static float as_float(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t fb(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

static float next_f(void)
{
    return as_float(next());
}

static bVector3 next_v(void)
{
    bVector3 v;

    v.x = next_f();
    v.y = next_f();
    v.z = next_f();
    v.pad = next_f();
    return v;
}

static bVector4 next_v4(void)
{
    bVector4 v;

    v.x = next_f();
    v.y = next_f();
    v.z = next_f();
    v.w = next_f();
    return v;
}

static bMatrix4 next_m(void)
{
    bMatrix4 m;

    m.v0 = next_v4();
    m.v1 = next_v4();
    m.v2 = next_v4();
    m.v3 = next_v4();
    return m;
}

static void put_v(const char *label, const bVector3 *v)
{
    printf(" %s %08x %08x %08x %08x", label, fb(v->x), fb(v->y), fb(v->z),
           fb(v->pad));
}

// ---------------------------------------------------------------- naming

static int in_array(const void *f, const void *base, int count, size_t size,
                    long *idx)
{
    const char *c = (const char *)f, *b = (const char *)base;

    if (base == NULL || count <= 0 || c < b || c >= b + (size_t)count * size)
        return 0;
    if ((size_t)(c - b) % size != 0) {
        *idx = -1;
        return 1;
    }
    *idx = (long)((size_t)(c - b) / size);
    return 1;
}

static const char *name_feature(const VCFeature *f)
{
    static char buf[8][32];
    static int k;
    char *s = buf[k++ & 7];
    int i;
    long idx;

    if (f == NULL)
        return "null";
    for (i = 0; i < NPOLY; i++) {
        const VCPolyhedron *p = &polys[i];

        if (dead[i])
            continue;
        if (in_array(f, p->pVertices, p->MaxVertices, sizeof(VCVertex),
                     &idx)) {
            snprintf(s, 32, idx < 0 ? "p%d.v?" : "p%d.v%ld", i, idx);
            return s;
        }
        if (in_array(f, p->pEdges, p->MaxEdges, sizeof(VCEdge), &idx)) {
            snprintf(s, 32, idx < 0 ? "p%d.e?" : "p%d.e%ld", i, idx);
            return s;
        }
        if (in_array(f, p->pFaces, p->MaxFaces, sizeof(VCFace), &idx)) {
            snprintf(s, 32, idx < 0 ? "p%d.f?" : "p%d.f%ld", i, idx);
            return s;
        }
    }
    return "?";
}

static const char *name_planes(const VCPolyhedron *p, const VCVoronoiPlane *pl)
{
    static char buf[4][24];
    static int k;
    char *s = buf[k++ & 3];
    long idx;

    if (pl == NULL)
        return "null";
    if (in_array(pl, p->pPlanes, p->MaxPlanes, sizeof(VCVoronoiPlane),
                 &idx) && idx >= 0) {
        snprintf(s, 24, "pl%ld", idx);
        return s;
    }
    return "?";
}

static const char *name_poly(const VCPolyhedron *p)
{
    static char buf[4][16];
    static int k;
    char *s = buf[k++ & 3];
    int i;

    if (p == NULL)
        return "null";
    for (i = 0; i < NPOLY; i++) {
        if (p == &polys[i]) {
            snprintf(s, 16, "%d", i);
            return s;
        }
    }
    return "?";
}

static VCFeature *resolve(uint32_t ref)
{
    VCPolyhedron *p;
    uint32_t idx = ref & 0xffffu;

    if (ref == NO_REF)
        return NULL;
    p = &polys[(ref >> 24) & 7];
    switch ((ref >> 16) & 0xffu) {
    case 0:
        return &p->pVertices[idx].Feature;
    case 1:
        return &p->pEdges[idx].Feature;
    default:
        return &p->pFaces[idx].Feature;
    }
}

static VCVoronoiPlane *plane_at(VCPolyhedron *p, uint32_t idx)
{
    return idx == NO_REF ? NULL : &p->pPlanes[idx];
}

// ---------------------------------------------------------------- hooks

#define NALLOC 256

static void    *allocs[NALLOC];
static int      nallocs;

static void *h_malloc(int size, const char *name, int flags, int pool)
{
    static const size_t rec[4] = {
        sizeof(VCVertex), sizeof(VCEdge), sizeof(VCFace),
        sizeof(VCVoronoiPlane),
    };
    static const char *const kind[4] = { "vertices", "edges", "faces",
                                         "planes" };
    int k = nallocs % 4;
    void *p = calloc(1, size > 0 ? (size_t)size : 1);

    (void)name;
    (void)flags;
    if (p == NULL) {
        fprintf(stderr, "out of memory\n");
        exit(2);
    }
    if (size % (int)rec[k] != 0)
        printf("  malloc #%d %s %d bytes? pool %d\n", nallocs, kind[k], size,
               pool);
    else
        printf("  malloc #%d %s x%d pool %d\n", nallocs, kind[k],
               size / (int)rec[k], pool);
    if (nallocs < NALLOC)
        allocs[nallocs] = p;
    nallocs++;
    return p;
}

static void h_free(void *p)
{
    int i;

    if (p == NULL) {
        printf("  free null\n");
        return;
    }
    for (i = 0; i < nallocs && i < NALLOC; i++) {
        if (allocs[i] == p) {
            printf("  free #%d\n", i);
            free(p);
            allocs[i] = NULL;
            return;
        }
    }
    for (i = 0; i < NPOLY; i++) {
        if (p == &polys[i]) {
            printf("  free poly %d\n", i);
            return;
        }
    }
    for (i = 0; i < NWIT; i++) {
        if (p == &wits[i]) {
            printf("  free wit %d\n", i);
            return;
        }
    }
    printf("  free ?\n");
}

static uint32_t next_handle = 1;
static int      null_creates;

static unsigned handle(void *o)
{
    return (unsigned)(uintptr_t)o;
}

static void *f_create(const char *layer, const char *type)
{
    uint32_t h = 0;

    if (null_creates > 0)
        null_creates--;
    else
        h = next_handle++;
    printf("  esp create %s %s -> %u\n", layer, type, (unsigned)h);
    return (void *)(uintptr_t)h;
}

static void f_delete(void *o)
{
    printf("  esp delete %u\n", handle(o));
}

static void f_mesh(void *o, int32_t faces)
{
    printf("  esp mesh %u %d\n", handle(o), (int)faces);
}

static void f_face(void *o, int32_t face, FloatVector *v)
{
    int k;

    printf("  esp face %u %d", handle(o), (int)face);
    for (k = 0; k < 4; k++)
        printf(" %08x %08x %08x", fb(v[k].x), fb(v[k].y), fb(v[k].z));
    printf("\n");
}

static void f_pos(void *o, bVector3 *p)
{
    printf("  esp pos %u %08x %08x %08x\n", handle(o), fb(p->x), fb(p->y),
           fb(p->z));
}

// ---------------------------------------------------------------- dumps

static void dump_poly(int i)
{
    VCPolyhedron *p = &polys[i];
    int k;

    printf("  poly %d num %d %d %d %d max %d %d %d %d dyn %d obj %u arr "
           "%d%d%d%d\n", i, p->NumVertices, p->NumEdges, p->NumFaces,
           p->NumPlanes, p->MaxVertices, p->MaxEdges, p->MaxFaces,
           p->MaxPlanes, (int)p->DynamicallyAllocated,
           handle(p->pCaffeineObj), p->pVertices != NULL, p->pEdges != NULL,
           p->pFaces != NULL, p->pPlanes != NULL);
    for (k = 0; k < p->NumVertices && p->pVertices != NULL; k++) {
        const VCVertex *v = &p->pVertices[k];

        printf("  v%d t%d n%d %s pos %08x %08x %08x\n", k, v->Feature.Type,
               v->Feature.NumPlanes, name_planes(p, v->pPlanes),
               fb(v->CompressedPosition[0]), fb(v->CompressedPosition[1]),
               fb(v->CompressedPosition[2]));
    }
    for (k = 0; k < p->NumEdges && p->pEdges != NULL; k++) {
        const VCEdge *e = &p->pEdges[k];

        printf("  e%d t%d n%d %s dir %d %d %d\n", k, e->Feature.Type,
               e->Feature.NumPlanes, name_planes(p, e->pPlanes),
               e->CompressedDirection[0], e->CompressedDirection[1],
               e->CompressedDirection[2]);
    }
    for (k = 0; k < p->NumFaces && p->pFaces != NULL; k++) {
        const VCFace *f = &p->pFaces[k];

        printf("  f%d t%d n%d %s plane %08x %08x %08x %08x\n", k,
               f->Feature.Type, f->Feature.NumPlanes,
               name_planes(p, f->pPlanes), fb(f->Plane.CompressedNormal[0]),
               fb(f->Plane.CompressedNormal[1]),
               fb(f->Plane.CompressedNormal[2]),
               fb(f->Plane.CompressedPlaneDistance));
    }
    for (k = 0; k < p->NumPlanes && p->pPlanes != NULL; k++) {
        const VCVoronoiPlane *pl = &p->pPlanes[k];

        printf("  pl%d %08x %08x %08x %08x nb %s\n", k,
               fb(pl->Plane.CompressedNormal[0]),
               fb(pl->Plane.CompressedNormal[1]),
               fb(pl->Plane.CompressedNormal[2]),
               fb(pl->Plane.CompressedPlaneDistance),
               name_feature(pl->Neighbor));
    }
}

static unsigned raw(const void *p)
{
    return (unsigned)(uint32_t)(uintptr_t)p;
}

static void dump_raw(int i)
{
    VCPolyhedron *p = &polys[i];
    int k;

    printf("  raw %d", i);
    for (k = 0; k < p->NumVertices; k++)
        printf(" %x", raw(p->pVertices[k].pPlanes));
    printf(" |");
    for (k = 0; k < p->NumEdges; k++)
        printf(" %x", raw(p->pEdges[k].pPlanes));
    printf(" |");
    for (k = 0; k < p->NumFaces; k++)
        printf(" %x", raw(p->pFaces[k].pPlanes));
    printf(" |");
    for (k = 0; k < p->NumPlanes; k++)
        printf(" %x", raw(p->pPlanes[k].Neighbor));
    printf("\n");
}

// The fourth lanes VClip leaves as the frame's: see vclip.c's head.
static void dump_wit(int i, int status)
{
    VCWitness *w = &wits[i];
    int t1 = w->F1 != NULL ? w->F1->Type : -1;
    int t2 = w->F2 != NULL ? w->F2->Type : -1;
    int m1 = tainted[i][0], m2 = tainted[i][1];

    if (t1 == 0 && t2 == 0 && (status == 1 || status == 2))
        m1 = m2 = 1;
    if (status == 2 && ((t1 == 0 && t2 == 1) || (t1 == 1 && t2 == 0))) {
        if (w->SwitchState == 1)
            m1 = 1;
        else
            m2 = 1;
    }
    tainted[i][0] = m1;
    tainted[i][1] = m2;
    printf("  wit %d ss %d f1 %s f2 %s p %s %s", i, (int)w->SwitchState,
           name_feature(w->F1), name_feature(w->F2), name_poly(w->P1),
           name_poly(w->P2));
    printf(" cp1 %08x %08x %08x ", fb(w->CP1.x), fb(w->CP1.y), fb(w->CP1.z));
    if (m1)
        printf("--------");
    else
        printf("%08x", fb(w->CP1.pad));
    printf(" cp2 %08x %08x %08x ", fb(w->CP2.x), fb(w->CP2.y), fb(w->CP2.z));
    if (m2)
        printf("--------");
    else
        printf("%08x", fb(w->CP2.pad));
    printf(" dist %08x obj %u %u\n", fb(w->Distance),
           handle(w->pCaffeineObj1), handle(w->pCaffeineObj2));
}

static void dump_xf(void)
{
    printf("  xf %s", name_feature(XF.pFeature));
    put_v("head", &XF.Head);
    put_v("tail", &XF.Tail);
    put_v("edge", &XF.Edge);
    printf("\n");
}

static void dump_clip(void)
{
    printf("  clip %08x %08x %s %s %d\n", fb(C.LambdaMin), fb(C.LambdaMax),
           name_feature(C.NeighborMin), name_feature(C.NeighborMax),
           (int)C.Penetration);
}

static void dump_x(void)
{
    const float *m = &X.Matrix.v0.x;
    int k;

    printf("  x");
    for (k = 0; k < 16; k++)
        printf(" %08x", fb(m[k]));
    printf("\n");
}

// ---------------------------------------------------------------- main

int main(int argc, char **argv)
{
    uint32_t op;
    unsigned int w0;

    if (argc != 2) {
        fprintf(stderr, "usage: vclip_test script\n");
        return 2;
    }
    script = fopen(argv[1], "r");
    if (script == NULL) {
        perror(argv[1]);
        return 2;
    }
    bSetMemoryHooks(h_malloc, h_free);
    gEspCreateObjectFn = f_create;
    gEspDeleteObjectFn = f_delete;
    gEspCreateUserMeshFn = f_mesh;
    gEspSetUserMeshFaceFn = f_face;
    gEspSetObjectPositionFn = f_pos;

    while (fscanf(script, "%x", &w0) == 1) {
        op = (uint32_t)w0;
        switch (op) {
        case OP_TAG:
            printf("[%u]\n", (unsigned)next());
            break;
        case OP_POLY_CTOR: {
            int i = (int)next();

            printf("ctor %d -> %s\n", i, name_poly(vcpoly_init(&polys[i])));
            dead[i] = 0;
            dump_poly(i);
            break;
        }
        case OP_POLY_ALLOC: {
            int i = (int)next();
            int32_t a = (int32_t)next(), b = (int32_t)next();
            int32_t c = (int32_t)next(), d = (int32_t)next();

            printf("alloc %d %d %d %d %d\n", i, a, b, c, d);
            vcpoly_init_alloc(&polys[i], a, b, c, d);
            dump_poly(i);
            break;
        }
        case OP_POLY_ARRAYS: {
            int i = (int)next();
            int32_t a = (int32_t)next(), b = (int32_t)next();
            int32_t c = (int32_t)next(), d = (int32_t)next();

            printf("arrays %d %d %d %d %d\n", i, a, b, c, d);
            vcpoly_init_arrays(&polys[i],
                               calloc((size_t)a + 1, sizeof(VCVertex)), a,
                               calloc((size_t)b + 1, sizeof(VCEdge)), b,
                               calloc((size_t)c + 1, sizeof(VCFace)), c,
                               calloc((size_t)d + 1, sizeof(VCVoronoiPlane)),
                               d);
            dump_poly(i);
            break;
        }
        case OP_NEW_PLANES: {
            VCPolyhedron *p = &polys[next()];
            int32_t n = (int32_t)next();
            VCVoronoiPlane *r = vcpoly_new_voronoi_planes(p, n);

            printf("planes %d -> %s num %d\n", n, name_planes(p, r),
                   p->NumPlanes);
            break;
        }
        case OP_NEW_VERTEX: {
            VCPolyhedron *p = &polys[next()];
            bVector3 v = next_v();
            int32_t n = (int32_t)next();
            VCVoronoiPlane *pl = plane_at(p, next());

            printf("vertex -> %s\n",
                   name_feature((VCFeature *)vcpoly_new_vertex(p, &v, n,
                                                               pl)));
            break;
        }
        case OP_NEW_EDGE: {
            VCPolyhedron *p = &polys[next()];
            bVector3 v = next_v();
            int32_t n = (int32_t)next();
            VCVoronoiPlane *pl = plane_at(p, next());

            printf("edge -> %s\n",
                   name_feature((VCFeature *)vcpoly_new_edge(p, &v, n, pl)));
            break;
        }
        case OP_NEW_FACE: {
            VCPolyhedron *p = &polys[next()];
            bVector3 v = next_v();
            float d = next_f();
            int32_t n = (int32_t)next();
            VCVoronoiPlane *pl = plane_at(p, next());

            printf("face -> %s\n",
                   name_feature((VCFeature *)vcpoly_new_face(p, &v, d, n,
                                                             pl)));
            break;
        }
        case OP_SET_NB: {
            VCPolyhedron *p = &polys[next()];
            uint32_t idx = next();

            p->pPlanes[idx].Neighbor = resolve(next());
            break;
        }
        case OP_SET_VORONOI: {
            int i = (int)next();

            printf("set voronoi %d\n", i);
            vcpoly_set_voronoi_planes(&polys[i]);
            break;
        }
        case OP_SET_VORONOI_ONE: {
            VCFeature *f = resolve(next());

            printf("set voronoi %s\n", name_feature(f));
            if (f->Type == VCFEATURE_VERTEX)
                vcvertex_set_voronoi_planes((VCVertex *)f);
            else if (f->Type == VCFEATURE_EDGE)
                vcedge_set_voronoi_planes((VCEdge *)f);
            else
                vcface_set_voronoi_planes((VCFace *)f);
            break;
        }
        case OP_DUMP_POLY:
            dump_poly((int)next());
            break;
        case OP_MOVE_VERTEX: {
            VCFeature *f = resolve(next());
            bVector3 d = next_v();

            printf("move %s\n", name_feature(f));
            vcvertex_move((VCVertex *)f, &d);
            break;
        }
        case OP_MOVE_FACE: {
            VCFeature *f = resolve(next());
            bVector3 d = next_v();

            printf("move %s\n", name_feature(f));
            vcface_move((VCFace *)f, &d);
            break;
        }
        case OP_NEXT_EDGE: {
            VCVertex *v = (VCVertex *)resolve(next());
            VCEdge *last = (VCEdge *)resolve(next());
            VCFace *f = (VCFace *)resolve(next());

            printf("next edge %s %s %s -> %s\n", name_feature(&v->Feature),
                   name_feature((VCFeature *)last),
                   name_feature(&f->Feature),
                   name_feature((VCFeature *)vcvertex_get_next_edge_in_face(
                       v, last, f)));
            break;
        }
        case OP_GET_CODE: {
            VCPolyhedron *p = &polys[next()];
            VCFeature *f = resolve(next());

            printf("code %s -> %08x\n", name_feature(f),
                   (unsigned)vcpoly_get_feature_code(p, f));
            break;
        }
        case OP_GET_FEATURE: {
            VCPolyhedron *p = &polys[next()];
            uint32_t code = next();

            printf("feature %08x -> %s\n", (unsigned)code,
                   name_feature(vcpoly_get_feature(p, code)));
            break;
        }
        case OP_POKE_TYPE: {
            VCFeature *f = resolve(next());

            f->Type = (int8_t)next();
            break;
        }
        case OP_TO_INDICES: {
            int i = (int)next();

            printf("to indices %d\n", i);
            vcpoly_convert_to_indicies(&polys[i]);
            dump_raw(i);
            break;
        }
        case OP_TO_POINTERS: {
            int i = (int)next();

            printf("to pointers %d\n", i);
            vcpoly_convert_to_pointers(&polys[i]);
            break;
        }
        case OP_DUMP_RAW:
            dump_raw((int)next());
            break;
        case OP_MEMIMAGE_LOAD: {
            int d = (int)next(), s = (int)next();
            VCPolyhedron *src = &polys[s];

            printf("memimage %d from %d\n", d, s);
            dead[s] = 1;
            vcpoly_memory_image_load(&polys[d], src->pVertices,
                                     src->NumVertices, src->pEdges,
                                     src->NumEdges, src->pFaces,
                                     src->NumFaces, src->pPlanes,
                                     src->NumPlanes);
            dump_poly(d);
            break;
        }
        case OP_UNLOAD: {
            int i = (int)next();

            printf("unload %d\n", i);
            vcpoly_memory_image_unload(&polys[i]);
            dump_poly(i);
            break;
        }
        case OP_CLOSE: {
            int i = (int)next();

            printf("close %d\n", i);
            vcpoly_close(&polys[i]);
            dump_poly(i);
            break;
        }
        case OP_DESTROY: {
            int i = (int)next();
            int32_t flags = (int32_t)next();

            printf("destroy %d %d\n", i, flags);
            vcpoly_destroy(&polys[i], flags);
            dump_poly(i);
            break;
        }
        case OP_WIT_INIT: {
            int i = (int)next(), a = (int)next(), b = (int)next();

            printf("witness %d %d %d\n", i, a, b);
            vcwitness_init(&wits[i], &polys[a], &polys[b]);
            dump_wit(i, -1);
            break;
        }
        case OP_WIT_SET: {
            int i = (int)next();

            wits[i].F1 = resolve(next());
            wits[i].F2 = resolve(next());
            break;
        }
        case OP_VCLIP: {
            int i = (int)next();
            bMatrix4 r1 = next_m();
            bVector3 t1 = next_v();
            bMatrix4 r2 = next_m();
            bVector3 t2 = next_v();
            int32_t st;

            wits[i].CP1.pad = as_float(CP_SENTINEL);
            wits[i].CP2.pad = as_float(CP_SENTINEL);
            tainted[i][0] = tainted[i][1] = 0;
            st = vcwitness_vclip(&wits[i], &r1, &t1, &r2, &t2);
            printf("vclip %d -> %d printing %s\n", i, (int)st,
                   name_poly(pPrintingPolygon));
            dump_wit(i, st);
            break;
        }
        case OP_DUMP_WIT: {
            int i = (int)next();

            dump_wit(i, -1);
            break;
        }
        case OP_CHECK: {
            // One step of VClip on its own, set up as VClip sets it up: the
            // two transforms, SwitchState, and the transforms and features
            // passed swapped when the check's first feature is F2. The walk
            // settles on the same pair whichever way a step goes, so a step
            // is only seen whole here.
            static int32_t (*const checks[5])(VCWitness *, VCTransform *,
                                              VCTransform *,
                                              VCTransformedFeature *,
                                              VCTransformedFeature *) = {
                vcwitness_check_vertex_vertex, vcwitness_check_vertex_edge,
                vcwitness_check_vertex_face, vcwitness_check_edge_edge,
                vcwitness_check_edge_face,
            };
            int i = (int)next();
            uint32_t kind = next(), swap = next();
            bMatrix4 r1 = next_m();
            bVector3 t1 = next_v();
            bMatrix4 r2 = next_m();
            bVector3 t2 = next_v();
            VCTransform x12, x21;
            VCTransformedFeature xf1, xf2;
            int32_t st;

            memset(&xf1, 0, sizeof xf1);
            memset(&xf2, 0, sizeof xf2);
            vctransform_init(&x12, &r2, &t2, &r1, &t1);
            vctransform_init(&x21, &r1, &t1, &r2, &t2);
            wits[i].SwitchState = swap ? 2 : 1;
            wits[i].CP1.pad = as_float(CP_SENTINEL);
            wits[i].CP2.pad = as_float(CP_SENTINEL);
            tainted[i][0] = tainted[i][1] = 0;
            if (swap)
                st = checks[kind](&wits[i], &x21, &x12, &xf2, &xf1);
            else
                st = checks[kind](&wits[i], &x12, &x21, &xf1, &xf2);
            printf("check %d %u %u -> %d\n", i, (unsigned)kind,
                   (unsigned)swap, (int)st);
            dump_wit(i, st);
            break;
        }
        case OP_WIT_DESTROY: {
            int i = (int)next();
            int32_t flags = (int32_t)next();

            printf("wit destroy %d %d\n", i, flags);
            vcwitness_destroy(&wits[i], flags);
            dump_wit(i, -1);
            break;
        }
        case OP_WIT_PLOT: {
            int i = (int)next();
            bMatrix4 m1 = next_m();
            bMatrix4 m2 = next_m();

            printf("wit plot %d\n", i);
            vcwitness_plot_to_caffeine(&wits[i], &m1, &m2);
            dump_wit(i, -1);
            break;
        }
        case OP_POLY_PLOT: {
            int i = (int)next();
            bMatrix4 m = next_m();

            printf("poly plot %d\n", i);
            vcpoly_plot_to_caffeine(&polys[i], &m);
            printf("  obj %u\n", handle(polys[i].pCaffeineObj));
            break;
        }
        case OP_ESP_NULL:
            null_creates = (int)next();
            break;
        case OP_MESH_FACE: {
            static FloatVector out[VC_MESH_FACE_CORNERS];
            VCFeature *f = resolve(next());
            bMatrix4 m = next_m();
            int k, n = 4;

            for (k = 0; k < VC_MESH_FACE_CORNERS; k++) {
                out[k].x = as_float(0x7f7f0001u + (uint32_t)k);
                out[k].y = out[k].x;
                out[k].z = out[k].x;
            }
            if (f->Type == VCFEATURE_FACE && f->NumPlanes > 4)
                n = f->NumPlanes;
            vcfeature_create_user_mesh_face(f, out, &m);
            printf("mesh %s", name_feature(f));
            for (k = 0; k < n; k++)
                printf(" %08x %08x %08x", fb(out[k].x), fb(out[k].y),
                       fb(out[k].z));
            printf("\n");
            break;
        }
        case OP_XFORM: {
            bMatrix4 r1 = next_m();
            bVector3 t1 = next_v();
            bMatrix4 r2 = next_m();
            bVector3 t2 = next_v();

            printf("xform\n");
            vctransform_init(&X, &r1, &t1, &r2, &t2);
            dump_x();
            break;
        }
        case OP_XVEC:
        case OP_XPT: {
            bVector3 v = next_v();
            bVector3 r = op == OP_XVEC ? vctransform_transform_vector(&X, v)
                                       : vctransform_transform_point(&X, v);

            printf(op == OP_XVEC ? "xvec" : "xpt");
            put_v("->", &r);
            printf("\n");
            break;
        }
        case OP_XVECP: {
            bVector3 v = next_v();
            bVector3 r;

            vctransform_transform_vector_p(&X, &r, &v);
            printf("xvecp");
            put_v("->", &r);
            printf("\n");
            break;
        }
        case OP_DIST: {
            bVector3 a = next_v();
            bVector3 b = next_v();

            printf("dist -> %08x\n", fb(vc_dist_between(&a, &b)));
            break;
        }
        case OP_XF_SET:
            XF.pFeature = NULL;
            XF.Head = next_v();
            XF.Tail = next_v();
            XF.Edge = next_v();
            break;
        case OP_XF_EDGE: {
            VCEdge *e = (VCEdge *)resolve(next());

            printf("xf edge\n");
            vctf_transform_edge(&XF, &X, e);
            dump_xf();
            break;
        }
        case OP_XF_VERTEX: {
            VCVertex *v = (VCVertex *)resolve(next());

            printf("xf vertex\n");
            vctf_transform_vertex(&XF, &X, v);
            dump_xf();
            break;
        }
        case OP_CLIP_INIT:
            printf("clip init\n");
            vcclip_init(&C);
            dump_clip();
            break;
        case OP_CLIP_SET:
            C.LambdaMin = next_f();
            C.LambdaMax = next_f();
            C.NeighborMin = resolve(next());
            C.NeighborMax = resolve(next());
            C.Penetration = (int32_t)next();
            break;
        case OP_CLIP_PLANES: {
            VCPolyhedron *p = &polys[next()];
            uint32_t first = next();
            int32_t n = (int32_t)next();

            printf("clip planes -> %d\n",
                   (int)vcclip_clip_planes(&C, &XF, &p->pPlanes[first], n));
            dump_clip();
            break;
        }
        case OP_CLIP_VERT: {
            VCPolyhedron *p = &polys[next()];
            uint32_t first = next();
            int32_t n = (int32_t)next();
            uint32_t has = next();
            bVector3 v = next_v();

            printf("clip vert -> %s\n",
                   name_feature(vcclip_clip_vertex_planes(
                       &C, &XF, has ? &v : NULL, &p->pPlanes[first], n)));
            dump_clip();
            break;
        }
        case OP_CLIP_FACE: {
            VCPolyhedron *p = &polys[next()];
            uint32_t first = next();
            int32_t n = (int32_t)next();
            VCFace *f = (VCFace *)resolve(next());

            printf("clip face -> %s\n",
                   name_feature(vcclip_clip_face_planes(
                       &C, &XF, f, &p->pPlanes[first], n)));
            dump_clip();
            break;
        }
        case OP_FLAGS:
            PrintThisTime = (int32_t)next();
            PlotClosestFeatures = (int32_t)next();
            break;
        case OP_PRINT: {
            int i = (int)next();

            vcpoly_print(&polys[i]);
            printf("print %d printing %s\n", i, name_poly(pPrintingPolygon));
            break;
        }
        default:
            fprintf(stderr, "op %u\n", (unsigned)op);
            return 2;
        }
    }
    return 0;
}
