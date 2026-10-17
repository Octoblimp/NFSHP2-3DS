// polyhedra_test -- the harness tools/polyhedra_check.py runs against
// polyhedra.cpp's port, 3DS Files/source/polyhedra.c.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints. Every
// polyhedron is named, not printed as an address: r0..r3 and w0..w3 are the
// Rect and Wafer slots, Vk.j is volume j of chunk k, #n is the nth block
// bMalloc handed out, and p1 and p2 are a witness's polyhedra when they are
// none of those (TestCubes's cubes on the stack). A feature is its
// polyhedron's name, its kind and its index, worked out from the arrays'
// bounds.
//
// A chunk comes in as the disc's bytes and the misalignment mod 16 the
// model loads it at. The records hold pointers, so the host's are wider:
// the chunk is rebuilt here with each record widened, each child chunk at
// the misalignment the image sees it at (so every pad before a record
// array is the image's), and each child's size given the slack that keeps
// the next one there. The loader under test then works out the counts from
// the host's sizes.
//
// TestCubes, InitVoronoiClip and TestVClipRepeatability throw every result
// away, so what is compared is what they call: the witness constructor,
// VClip (its arguments, its answer and the witness it leaves), the witness
// and polyhedron destructors, bGetTicker, bMalloc and bFree. The four vclip.c
// calls are seen through the linker's --wrap; bGetTicker is defined here.
// InitVoronoiClip never returns, so bGetTicker longjmps out of it at the
// first ticker after the script's count of TestCubes.
//
// A dump line can be folded into a CRC32 instead of printed (the model does
// the same), which is how TRACKB12's fifteen thousand wafers are compared.

#include <math.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "espresso.h"
#include "polyhedra.h"
#include "vclip.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

enum {
    OP_TAG = 1, OP_TABLES, OP_CONSTS, OP_RECT, OP_CUBE, OP_WAFER,
    OP_DESTROY, OP_CHUNK, OP_LOAD, OP_UNLOAD, OP_FIND, OP_MOVECOG, OP_LIST,
    OP_DUMP_VOL, OP_INIT_GLOBALS, OP_CLOSE_GLOBALS, OP_SEED, OP_RANDLOC,
    OP_TESTCUBES, OP_INITVC, OP_REPEAT, OP_SETOBJ, OP_BOOT,
};

enum { KIND_RECT, KIND_CUBE, KIND_WAFER, KIND_VOLUME };

#define NRECT  4
#define NWAFER 4
#define NCHUNK 32
#define NVOL   256
#define NALLOC 256

static FILE *script;

static RectPolyhedron  rects[NRECT];
static WaferPolyhedron wafers[NWAFER];

typedef struct Chunk {
    uint8_t *mem;       // the allocation
    uint8_t *chunk;     // the widened container, at its misalignment
} Chunk;

static Chunk chunks[NCHUNK];

typedef struct Volume {
    PipelinePolyhedron *p;
    int chunk, index;
    int loaded;         // searched for features once its chunk is loaded
} Volume;

static Volume vols[NVOL];
static int    nvols;

static VCPolyhedron *ctx[2];      // a witness's unregistered polyhedra

// The polyhedron being dumped, searched first: a heap block's features are
// found only this way.
static const VCPolyhedron *dump_hint;

static void *allocs[NALLOC];
static int   nallocs;

// ---------------------------------------------------------------- output

static int      digest;           // fold lines into crc rather than print
static uint32_t crc;

static uint32_t crc32_update(uint32_t c, const char *s, size_t n)
{
    size_t i;
    int k;

    c = ~c;
    for (i = 0; i < n; i++) {
        c ^= (uint8_t)s[i];
        for (k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static void out(const char *fmt, ...)
{
    char buf[1024];
    va_list ap;
    int n;

    va_start(ap, fmt);
    n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n < 0 || n >= (int)sizeof buf) {
        fprintf(stderr, "line too long\n");
        exit(2);
    }
    if (digest)
        crc = crc32_update(crc, buf, (size_t)n);
    else
        fputs(buf, stdout);
}

// ---------------------------------------------------------------- script

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

// Bits, with every NaN as the one quiet NaN: the host and the model's
// interpreter do not agree on a NaN's sign or payload.
static uint32_t fx(float f)
{
    uint32_t b = fb(f);

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu))
        return 0x7fc00000u;
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

// ---------------------------------------------------------------- naming

static char namebuf[8][48];
static int  nameslot;

static char *scratch(void)
{
    nameslot = (nameslot + 1) & 7;
    return namebuf[nameslot];
}

static const char *vol_name(int i)
{
    char *s = scratch();

    snprintf(s, 48, "V%d.%d", vols[i].chunk, vols[i].index);
    return s;
}

static int is_registered(const VCPolyhedron *p)
{
    int i;

    for (i = 0; i < NRECT; i++)
        if (p == &rects[i].Poly)
            return 1;
    for (i = 0; i < NWAFER; i++)
        if (p == &wafers[i].Poly)
            return 1;
    for (i = 0; i < nvols; i++)
        if (p == &vols[i].p->Poly)
            return 1;
    return 0;
}

static const char *name_poly(const void *a)
{
    char *s;
    int i;

    if (a == NULL)
        return "null";
    if (a == (const void *)&PipelinePolyhedronList)
        return "head";
    if (ctx[0] != NULL && a == (const void *)ctx[0])
        return "p1";
    if (ctx[1] != NULL && a == (const void *)ctx[1])
        return "p2";
    for (i = 0; i < NRECT; i++)
        if (a == (const void *)&rects[i]) {
            s = scratch();
            snprintf(s, 48, "r%d", i);
            return s;
        }
    for (i = 0; i < NWAFER; i++)
        if (a == (const void *)&wafers[i]) {
            s = scratch();
            snprintf(s, 48, "w%d", i);
            return s;
        }
    for (i = 0; i < nvols; i++)
        if (a == (const void *)vols[i].p)
            return vol_name(i);
    for (i = 0; i < nallocs; i++)
        if (allocs[i] != NULL && a == allocs[i]) {
            s = scratch();
            snprintf(s, 48, "#%d", i);
            return s;
        }
    return "?";
}

// The search order the model uses: the one being dumped, a witness's own,
// the slots, then the volumes. No two overlap, so the order only saves
// time.
static int search_list(const VCPolyhedron **l)
{
    int n = 0, i;

    if (dump_hint != NULL)
        l[n++] = dump_hint;
    if (ctx[0] != NULL)
        l[n++] = ctx[0];
    if (ctx[1] != NULL)
        l[n++] = ctx[1];
    for (i = 0; i < NRECT; i++)
        l[n++] = &rects[i].Poly;
    for (i = 0; i < NWAFER; i++)
        l[n++] = &wafers[i].Poly;
    for (i = 0; i < nvols; i++)
        if (vols[i].loaded)
            l[n++] = &vols[i].p->Poly;
    return n;
}

static int in_array(const void *f, const void *base, int count, size_t size,
                    int *idx)
{
    const uint8_t *a = (const uint8_t *)f, *b = (const uint8_t *)base;

    if (base == NULL || count <= 0 || a < b || a >= b + (size_t)count * size)
        return 0;
    if ((size_t)(a - b) % size) {
        *idx = -1;
        return 1;
    }
    *idx = (int)((size_t)(a - b) / size);
    return 1;
}

static const char *name_feature(const VCFeature *f)
{
    const VCPolyhedron *l[3 + NRECT + NWAFER + NVOL];
    int n, i, idx;
    char *s;

    if (f == NULL)
        return "null";
    n = search_list(l);
    for (i = 0; i < n; i++) {
        const VCPolyhedron *p = l[i];
        const void *base[3] = { p->pVertices, p->pEdges, p->pFaces };
        const int max[3] = { p->MaxVertices, p->MaxEdges, p->MaxFaces };
        const size_t size[3] = { sizeof(VCVertex), sizeof(VCEdge),
                                 sizeof(VCFace) };
        int k;

        for (k = 0; k < 3; k++) {
            if (in_array(f, base[k], max[k], size[k], &idx)) {
                s = scratch();
                if (idx < 0)
                    snprintf(s, 48, "%s.%c?", name_poly(p), "vef"[k]);
                else
                    snprintf(s, 48, "%s.%c%d", name_poly(p), "vef"[k], idx);
                return s;
            }
        }
    }
    return "?";
}

static const char *name_planes(const VCPolyhedron *p, const VCVoronoiPlane *pl)
{
    int idx;
    char *s;

    if (pl == NULL)
        return "null";
    if (in_array(pl, p->pPlanes, p->MaxPlanes, sizeof(VCVoronoiPlane), &idx)
        && idx >= 0) {
        s = scratch();
        snprintf(s, 48, "pl%d", idx);
        return s;
    }
    return "?";
}

static unsigned handle(const void *o)
{
    return (unsigned)(uint32_t)(uintptr_t)o;
}

// ---------------------------------------------------------------- dumps

// A witness's own polyhedra are TestCubes's, on its stack, and nothing
// writes their links: those are masked.
static void dump_poly(const char *label, const VCPolyhedron *p)
{
    int stack = p == ctx[0] || p == ctx[1];
    int k;

    dump_hint = p;
    out("  poly %s num %d %d %d %d max %d %d %d %d dyn %d obj %u arr "
        "%d%d%d%d link %s %s\n", label, p->NumVertices, p->NumEdges,
        p->NumFaces, p->NumPlanes, p->MaxVertices, p->MaxEdges, p->MaxFaces,
        p->MaxPlanes, (int)p->DynamicallyAllocated, handle(p->pCaffeineObj),
        p->pVertices != NULL, p->pEdges != NULL, p->pFaces != NULL,
        p->pPlanes != NULL, stack ? "-" : name_poly(p->Link.next),
        stack ? "-" : name_poly(p->Link.prev));
    for (k = 0; k < p->NumVertices && p->pVertices != NULL; k++) {
        const VCVertex *v = &p->pVertices[k];

        out("  v%d t%d n%d %s pos %08x %08x %08x\n", k, v->Feature.Type,
            v->Feature.NumPlanes, name_planes(p, v->pPlanes),
            fx(v->CompressedPosition[0]), fx(v->CompressedPosition[1]),
            fx(v->CompressedPosition[2]));
    }
    for (k = 0; k < p->NumEdges && p->pEdges != NULL; k++) {
        const VCEdge *e = &p->pEdges[k];

        out("  e%d t%d n%d %s dir %d %d %d\n", k, e->Feature.Type,
            e->Feature.NumPlanes, name_planes(p, e->pPlanes),
            e->CompressedDirection[0], e->CompressedDirection[1],
            e->CompressedDirection[2]);
    }
    for (k = 0; k < p->NumFaces && p->pFaces != NULL; k++) {
        const VCFace *f = &p->pFaces[k];

        out("  f%d t%d n%d %s plane %08x %08x %08x %08x\n", k,
            f->Feature.Type, f->Feature.NumPlanes, name_planes(p, f->pPlanes),
            fx(f->Plane.CompressedNormal[0]), fx(f->Plane.CompressedNormal[1]),
            fx(f->Plane.CompressedNormal[2]),
            fx(f->Plane.CompressedPlaneDistance));
    }
    for (k = 0; k < p->NumPlanes && p->pPlanes != NULL; k++) {
        const VCVoronoiPlane *pl = &p->pPlanes[k];

        out("  pl%d %08x %08x %08x %08x nb %s\n", k,
            fx(pl->Plane.CompressedNormal[0]),
            fx(pl->Plane.CompressedNormal[1]),
            fx(pl->Plane.CompressedNormal[2]),
            fx(pl->Plane.CompressedPlaneDistance),
            name_feature(pl->Neighbor));
    }
    dump_hint = NULL;
}

static void dump_vol(int i)
{
    const PipelinePolyhedron *p = vols[i].p;
    char name[33];
    int k;

    // Never loaded, its array pointers are still the disc's junk.
    if (!vols[i].loaded) {
        out("  vol %s not loaded\n", vol_name(i));
        return;
    }
    memcpy(name, p->Name, 32);
    name[32] = 0;
    out("  vol %s hash %08x name %s cog %d dummy", vol_name(i), p->NameHash,
        name, (int)p->CenterOfGravityFixed);
    for (k = 0; k < 8; k++)
        out(" %02x", p->dummy[k]);
    out("\n");
    dump_poly(vol_name(i), &p->Poly);
}

static void dump_list(void)
{
    const VCPolyhedron *p;
    int n;

    out("  list");
    for (p = PipelinePolyhedronList.next, n = 0;
         p != (const VCPolyhedron *)(const void *)&PipelinePolyhedronList
         && n < 200; p = p->Link.next, n++)
        out(" %s", name_poly(p));
    out(" |");
    for (p = PipelinePolyhedronList.prev, n = 0;
         p != (const VCPolyhedron *)(const void *)&PipelinePolyhedronList
         && n < 200; p = p->Link.prev, n++)
        out(" %s", name_poly(p));
    out("\n");
}

static void dump_m(const bMatrix4 *m)
{
    const float *f = &m->v0.x;
    int k;

    for (k = 0; k < 16; k++)
        out(" %08x", fx(f[k]));
}

// The translation's fourth lane is left out: TestCubes never writes it.
static void dump_t(const bVector3 *t)
{
    out(" %08x %08x %08x", fx(t->x), fx(t->y), fx(t->z));
}

// ------------------------------------------------------ hooks and wraps

static void *h_malloc(int size, const char *name, int flags, int pool)
{
    void *p;

    (void)name;
    (void)flags;
    if (nallocs >= NALLOC) {
        fprintf(stderr, "too many allocations\n");
        exit(2);
    }
    p = calloc(1, (size_t)(size > 0 ? size : 1));
    if (size == (int)sizeof(RectPolyhedron))
        out("  malloc #%d rect pool %d\n", nallocs, pool);
    else
        out("  malloc #%d %d bytes pool %d\n", nallocs, size, pool);
    allocs[nallocs++] = p;
    return p;
}

static void h_free(void *p)
{
    int i;

    out("  free %s\n", name_poly(p));
    for (i = 0; i < nallocs; i++) {
        if (allocs[i] != NULL && allocs[i] == p) {
            free(p);
            allocs[i] = NULL;
            return;
        }
    }
}

static void f_delete(void *o)
{
    out("  esp delete %u\n", handle(o));
}

static jmp_buf  stop_jb;
static int      ticks, stop_at;

uint32_t bGetTicker(void)
{
    out("  ticker\n");
    if (stop_at > 0 && ++ticks == stop_at)
        longjmp(stop_jb, 1);
    return 0;
}

void    __real_vcwitness_init(VCWitness *w, VCPolyhedron *p1,
                              VCPolyhedron *p2);
int32_t __real_vcwitness_vclip(VCWitness *w, bMatrix4 *r1, bVector3 *t1,
                               bMatrix4 *r2, bVector3 *t2);
void    __real_vcwitness_destroy(VCWitness *w, int32_t flags);
void    __real_vcpoly_destroy(VCPolyhedron *p, int32_t flags);

void __wrap_vcwitness_init(VCWitness *w, VCPolyhedron *p1, VCPolyhedron *p2)
{
    ctx[0] = (p1 != NULL && !is_registered(p1)) ? p1 : NULL;
    ctx[1] = (p2 != NULL && !is_registered(p2) && p2 != p1) ? p2 : NULL;
    out("  witness %s %s\n", name_poly(p1), name_poly(p2));
    if (ctx[0] != NULL)
        dump_poly("p1", ctx[0]);
    if (ctx[1] != NULL)
        dump_poly("p2", ctx[1]);
    __real_vcwitness_init(w, p1, p2);
}

int32_t __wrap_vcwitness_vclip(VCWitness *w, bMatrix4 *r1, bVector3 *t1,
                               bMatrix4 *r2, bVector3 *t2)
{
    int32_t st;

    out("  vclip %s %s m1", name_poly(w->P1), name_poly(w->P2));
    dump_m(r1);
    out(" t1");
    dump_t(t1);
    out(" m2");
    dump_m(r2);
    out(" t2");
    dump_t(t2);
    out("\n");
    st = __real_vcwitness_vclip(w, r1, t1, r2, t2);
    out("  -> %d wit ss %d f1 %s f2 %s cp1 %08x %08x %08x cp2 %08x %08x "
        "%08x dist %08x\n", (int)st, (int)w->SwitchState, name_feature(w->F1),
        name_feature(w->F2), fx(w->CP1.x), fx(w->CP1.y), fx(w->CP1.z),
        fx(w->CP2.x), fx(w->CP2.y), fx(w->CP2.z), fx(w->Distance));
    return st;
}

void __wrap_vcwitness_destroy(VCWitness *w, int32_t flags)
{
    out("  ~witness %d\n", (int)flags);
    __real_vcwitness_destroy(w, flags);
}

void __wrap_vcpoly_destroy(VCPolyhedron *p, int32_t flags)
{
    int i;

    out("  ~poly %s %d\n", name_poly(p), (int)flags);
    // TestCubes's heap cube is seen nowhere else.
    for (i = 0; i < nallocs; i++)
        if (allocs[i] != NULL && allocs[i] == (void *)p)
            dump_poly(name_poly(p), p);
    __real_vcpoly_destroy(p, flags);
}

// ---------------------------------------------------------------- chunks

enum { R_HEADER, R_VERTEX, R_EDGE, R_FACE, R_PLANE };

static const size_t DISC_RS[5] = { 96, 20, 12, 24, 24 };
static const size_t HOST_RS[5] = {
    sizeof(PipelinePolyhedron), sizeof(VCVertex), sizeof(VCEdge),
    sizeof(VCFace), sizeof(VCVoronoiPlane),
};

static uint32_t rd32(const uint8_t *p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16
           | (uint32_t)p[3] << 24;
}

static uint16_t rd16(const uint8_t *p)
{
    return (uint16_t)(p[0] | p[1] << 8);
}

static void *ptr_of(uint32_t w)
{
    return (void *)(uintptr_t)w;
}

static void widen(int kind, uint8_t *dst, const uint8_t *s)
{
    int k;

    switch (kind) {
    case R_HEADER: {
        PipelinePolyhedron *p = (PipelinePolyhedron *)(void *)dst;

        p->Poly.Link.next = (VCPolyhedron *)ptr_of(rd32(s));
        p->Poly.Link.prev = (VCPolyhedron *)ptr_of(rd32(s + 4));
        p->Poly.DynamicallyAllocated = (int32_t)rd32(s + 8);
        p->Poly.pCaffeineObj = ptr_of(rd32(s + 12));
        p->Poly.NumVertices = (int16_t)rd16(s + 16);
        p->Poly.NumEdges = (int16_t)rd16(s + 18);
        p->Poly.NumFaces = (int16_t)rd16(s + 20);
        p->Poly.NumPlanes = (int16_t)rd16(s + 22);
        p->Poly.MaxVertices = (int16_t)rd16(s + 24);
        p->Poly.MaxEdges = (int16_t)rd16(s + 26);
        p->Poly.MaxFaces = (int16_t)rd16(s + 28);
        p->Poly.MaxPlanes = (int16_t)rd16(s + 30);
        p->Poly.pVertices = (VCVertex *)ptr_of(rd32(s + 32));
        p->Poly.pEdges = (VCEdge *)ptr_of(rd32(s + 36));
        p->Poly.pFaces = (VCFace *)ptr_of(rd32(s + 40));
        p->Poly.pPlanes = (VCVoronoiPlane *)ptr_of(rd32(s + 44));
        p->NameHash = rd32(s + 48);
        memcpy(p->Name, s + 52, 32);
        p->CenterOfGravityFixed = (int32_t)rd32(s + 84);
        memcpy(p->dummy, s + 88, 8);
        break;
    }
    case R_VERTEX: {
        VCVertex *v = (VCVertex *)(void *)dst;

        v->Feature.Type = (int8_t)s[0];
        v->Feature.NumPlanes = (int8_t)s[1];
        v->Padding = rd16(s + 2);
        for (k = 0; k < 3; k++)
            v->CompressedPosition[k] = as_float(rd32(s + 4 + 4 * k));
        v->pPlanes = (VCVoronoiPlane *)ptr_of(rd32(s + 16));
        break;
    }
    case R_EDGE: {
        VCEdge *e = (VCEdge *)(void *)dst;

        e->Feature.Type = (int8_t)s[0];
        e->Feature.NumPlanes = (int8_t)s[1];
        for (k = 0; k < 3; k++)
            e->CompressedDirection[k] = (int16_t)rd16(s + 2 + 2 * k);
        e->pPlanes = (VCVoronoiPlane *)ptr_of(rd32(s + 8));
        break;
    }
    case R_FACE: {
        VCFace *f = (VCFace *)(void *)dst;

        f->Feature.Type = (int8_t)s[0];
        f->Feature.NumPlanes = (int8_t)s[1];
        f->_pad2[0] = s[2];
        f->_pad2[1] = s[3];
        for (k = 0; k < 3; k++)
            f->Plane.CompressedNormal[k] = as_float(rd32(s + 4 + 4 * k));
        f->Plane.CompressedPlaneDistance = as_float(rd32(s + 16));
        f->pPlanes = (VCVoronoiPlane *)ptr_of(rd32(s + 20));
        break;
    }
    case R_PLANE: {
        VCVoronoiPlane *pl = (VCVoronoiPlane *)(void *)dst;

        pl->Padding = rd16(s);
        pl->_pad2[0] = s[2];
        pl->_pad2[1] = s[3];
        for (k = 0; k < 3; k++)
            pl->Plane.CompressedNormal[k] = as_float(rd32(s + 4 + 4 * k));
        pl->Plane.CompressedPlaneDistance = as_float(rd32(s + 16));
        pl->Neighbor = (VCFeature *)ptr_of(rd32(s + 20));
        break;
    }
    }
}

static uint32_t align16(uint32_t a)
{
    return (a + 15u) & ~15u;
}

// The disc container `d` as the image sees it at misalignment `mis`,
// rebuilt at the same misalignment with every record widened.
static void load_chunk(int k, const uint8_t *d, uint32_t n, uint32_t mis)
{
    uint32_t id = rd32(d), size = rd32(d + 4);
    uint32_t o, end = 8 + size;
    size_t cap = (size_t)n * 3 + 65536;
    uint8_t *base, *h, *c;
    int j = 0, idx = 0;

    if (end > n) {
        fprintf(stderr, "chunk %d is short\n", k);
        exit(2);
    }
    if (chunks[k].mem != NULL) {
        fprintf(stderr, "chunk %d given twice\n", k);
        exit(2);
    }
    chunks[k].mem = calloc(1, cap);
    base = (uint8_t *)(((uintptr_t)chunks[k].mem + 15) & ~(uintptr_t)15);
    h = base + mis;
    chunks[k].chunk = h;
    memcpy(h, &id, 4);
    c = h + 8;
    for (o = 8; o < end;) {
        uint32_t cid = rd32(d + o), csize = rd32(d + o + 4);
        uint32_t da = mis + o;                       // the disc address
        uint32_t pad = align16(da + 8) - (da + 8);
        size_t n_rec, host, r, slack;
        int kind = j % 5;

        if (o + 8 + csize > end) {
            fprintf(stderr, "chunk %d: child past the end\n", k);
            exit(2);
        }
        n_rec = kind == R_HEADER ? 1 : (csize - pad) / DISC_RS[kind];
        if ((uint8_t *)c + 8 + pad + n_rec * HOST_RS[kind] + 32
            > chunks[k].mem + cap) {
            fprintf(stderr, "chunk %d: no room\n", k);
            exit(2);
        }
        for (r = 0; r < n_rec; r++)
            widen(kind, c + 8 + pad + r * HOST_RS[kind],
                  d + o + 8 + pad + r * DISC_RS[kind]);
        if (kind == R_HEADER) {
            if (nvols >= NVOL) {
                fprintf(stderr, "too many volumes\n");
                exit(2);
            }
            vols[nvols].p = (PipelinePolyhedron *)(void *)(c + 8 + pad);
            vols[nvols].chunk = k;
            vols[nvols].index = idx++;
            nvols++;
        }
        // The size keeps the disc's residue mod 16, so the next child sits
        // where the image has it; the slack is under 16 bytes, less than any
        // host record, so the count is the disc's.
        host = pad + n_rec * HOST_RS[kind];
        slack = (size_t)((csize - host) & 15u);
        host += slack;
        memcpy(c, &cid, 4);
        {
            uint32_t hs = (uint32_t)host;

            memcpy(c + 4, &hs, 4);
        }
        c += 8 + host;
        o += 8 + csize;
        j++;
    }
    {
        uint32_t total = (uint32_t)(c - (h + 8));

        memcpy(h + 4, &total, 4);
    }
}

// ---------------------------------------------------------------- tests

static void set_ctx_none(void)
{
    ctx[0] = ctx[1] = NULL;
}

static void put_tables(const char *label, const int32_t *t, int n)
{
    int i;

    out("  %s", label);
    for (i = 0; i < n; i++)
        out(" %d", (int)t[i]);
    out("\n");
}

int main(int argc, char **argv)
{
    uint32_t op;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: polyhedra_test script\n");
        return 2;
    }
    // What the constructors leave alone shows as 0xa5 on both sides.
    memset(rects, 0xa5, sizeof rects);
    memset(wafers, 0xa5, sizeof wafers);
    bSetMemoryHooks(h_malloc, h_free);
    gEspDeleteObjectFn = f_delete;

    while (fscanf(script, "%x", &op) == 1) {
        set_ctx_none();
        switch (op) {
        case OP_TAG:
            printf("[%u]\n", next());
            break;
        case OP_TABLES:
            out("tables\n");
            put_tables("RectEdgesNearFaces", &RectEdgesNearFaces[0][0], 24);
            put_tables("RectEdgesNearVertices", &RectEdgesNearVertices[0][0],
                       24);
            put_tables("RectFacesNearEdges", &RectFacesNearEdges[0][0], 24);
            put_tables("RectVerticesNearEdges", &RectVerticesNearEdges[0][0],
                       24);
            put_tables("WaferEdgesNearFaces", &WaferEdgesNearFaces[0][0], 8);
            put_tables("WaferEdgesNearVertices",
                       &WaferEdgesNearVertices[0][0], 8);
            put_tables("WaferFacesNearEdges", &WaferFacesNearEdges[0][0], 8);
            put_tables("WaferVerticesNearEdges",
                       &WaferVerticesNearEdges[0][0], 8);
            put_tables("TriWaferEdgesNearVertices",
                       &TriWaferEdgesNearVertices[0][0], 8);
            put_tables("TriWaferVerticesNearEdges",
                       &TriWaferVerticesNearEdges[0][0], 8);
            break;
        case OP_CONSTS:
            out("consts eps %08x deg %08x halfpi %08x counter %d\n",
                fb(WAFER_TRIANGLE_EPSILON), fb(POLY_DEG_TO_RAD),
                fb(POLY_HALF_PI), (int)TestCounter);
            break;
        case OP_RECT: {
            int i = (int)next();
            float b[6];
            RectPolyhedron *r;
            int k;

            for (k = 0; k < 6; k++)
                b[k] = next_f();
            r = rectpoly_init(&rects[i], b[0], b[1], b[2], b[3], b[4], b[5]);
            out("rect r%d -> %s\n", i, name_poly(r));
            dump_poly(name_poly(&rects[i]), &rects[i].Poly);
            break;
        }
        case OP_CUBE: {
            int i = (int)next();
            float s = next_f();
            CubePolyhedron *c = cubepoly_init(&rects[i], s);

            out("cube r%d -> %s\n", i, name_poly(c));
            dump_poly(name_poly(&rects[i]), &rects[i].Poly);
            break;
        }
        case OP_WAFER: {
            int i = (int)next();
            int dig = (int)next();
            TrackPolygon tp;
            bVector3 org;
            int k;

            memset(&tp, 0, sizeof tp);
            for (k = 0; k < 4; k++)
                tp.Vertices[k] = next_v();
            tp.Normal.x = next_f();
            tp.Normal.y = next_f();
            tp.Normal.z = next_f();
            tp.PlaneDistance = next_f();
            org = next_v();
            waferpoly_init(&wafers[i], &tp, &org);
            if (dig) {
                digest = 1;
                crc = 0;
                dump_poly(name_poly(&wafers[i]), &wafers[i].Poly);
                digest = 0;
                out("wafer w%d crc %08x\n", i, crc);
            } else {
                out("wafer w%d\n", i);
                dump_poly(name_poly(&wafers[i]), &wafers[i].Poly);
            }
            break;
        }
        case OP_DESTROY: {
            int kind = (int)next(), i = (int)next();
            int32_t flags = (int32_t)next();

            switch (kind) {
            case KIND_RECT:
                out("destroy rect r%d %d\n", i, (int)flags);
                rectpoly_destroy(&rects[i], flags);
                dump_poly(name_poly(&rects[i]), &rects[i].Poly);
                break;
            case KIND_CUBE:
                out("destroy cube r%d %d\n", i, (int)flags);
                cubepoly_destroy(&rects[i], flags);
                dump_poly(name_poly(&rects[i]), &rects[i].Poly);
                break;
            case KIND_WAFER:
                out("destroy wafer w%d %d\n", i, (int)flags);
                waferpoly_destroy(&wafers[i], flags);
                dump_poly(name_poly(&wafers[i]), &wafers[i].Poly);
                break;
            default:
                out("destroy volume %s %d\n", vol_name(i), (int)flags);
                pipelinepoly_destroy(vols[i].p, flags);
                dump_vol(i);
                break;
            }
            break;
        }
        case OP_CHUNK: {
            int k = (int)next();
            uint32_t mis = next(), n = next(), w;
            uint8_t *d = calloc(1, (size_t)n + 4);

            for (w = 0; w < (n + 3) / 4; w++) {
                uint32_t v = next();

                memcpy(d + 4 * w, &v, 4);
            }
            load_chunk(k, d, n, mis);
            free(d);
            out("chunk %d mis %u\n", k, mis);
            break;
        }
        case OP_LOAD: {
            int k = (int)next(), i;
            int r = loader_collision_volumes(chunks[k].chunk);

            if (r)
                for (i = 0; i < nvols; i++)
                    if (vols[i].chunk == k)
                        vols[i].loaded = 1;
            out("load %d -> %d\n", k, r);
            dump_list();
            for (i = 0; i < nvols; i++)
                if (vols[i].chunk == k)
                    dump_vol(i);
            break;
        }
        case OP_UNLOAD: {
            int k = (int)next(), i;
            int r = unloader_collision_volumes(chunks[k].chunk);

            out("unload %d -> %d\n", k, r);
            dump_list();
            for (i = 0; i < nvols; i++)
                if (vols[i].chunk == k)
                    dump_vol(i);
            break;
        }
        case OP_FIND: {
            uint32_t h = next(), has = next();
            bVector3 cog = next_v();
            PipelinePolyhedron *p;
            int i, at = -1;

            p = find_pipeline_polyhedron(h, has ? &cog : NULL);
            for (i = 0; i < nvols; i++)
                if (vols[i].p == p)
                    at = i;
            out("find %08x %s -> %s\n", h, has ? "cog" : "null",
                name_poly(p));
            if (at >= 0 && has)
                dump_vol(at);
            break;
        }
        case OP_MOVECOG: {
            int i = (int)next();
            bVector3 cog = next_v();

            pipelinepoly_move_center_of_gravity(vols[i].p, &cog);
            out("movecog %s\n", vol_name(i));
            dump_vol(i);
            break;
        }
        case OP_LIST:
            out("list\n");
            dump_list();
            break;
        case OP_DUMP_VOL: {
            int i = (int)next();

            out("vol %s\n", vol_name(i));
            dump_vol(i);
            break;
        }
        case OP_INIT_GLOBALS:
            polyhedra_init_globals();
            out("init globals\n");
            dump_list();
            break;
        case OP_CLOSE_GLOBALS:
            out("close globals\n");
            polyhedra_close_globals();
            dump_list();
            break;
        case OP_SEED:
            bDefaultSeed = next();
            break;
        case OP_RANDLOC: {
            bVector3 t;
            bMatrix4 m;

            memset(&t, 0, sizeof t);
            memset(&m, 0, sizeof m);
            random_location(&t, &m);
            out("randloc t %08x %08x %08x %08x m", fx(t.x), fx(t.y), fx(t.z),
                fx(t.pad));
            dump_m(&m);
            out(" seed %08x\n", bDefaultSeed);
            break;
        }
        case OP_TESTCUBES:
            out("testcubes seed %08x\n", bDefaultSeed);
            stop_at = 0;
            test_cubes();
            out("  seed %08x\n", bDefaultSeed);
            break;
        case OP_INITVC: {
            int32_t counter = (int32_t)next();
            int n = (int)next();

            TestCounter = counter;
            out("initvc counter %d tests %d\n", (int)counter, n);
            ticks = 0;
            stop_at = 8 * n + 1;          // the next test's first ticker
            if (setjmp(stop_jb) == 0)
                init_voronoi_clip();
            stop_at = 0;
            out("  counter %d seed %08x\n", (int)TestCounter, bDefaultSeed);
            break;
        }
        case OP_REPEAT: {
            int32_t last = (int32_t)next();

            out("repeat last %d seed %08x\n", (int)last, bDefaultSeed);
            test_vclip_repeatability_n(last);
            out("  seed %08x\n", bDefaultSeed);
            break;
        }
        case OP_BOOT:
            // The image's list is linked by _GLOBAL_$I$ at boot, which the
            // model runs here; the port's is linked where it is defined.
            out("boot\n");
            dump_list();
            break;
        case OP_SETOBJ: {
            int kind = (int)next(), i = (int)next();
            void *o = ptr_of(next());

            if (kind == KIND_WAFER)
                wafers[i].Poly.pCaffeineObj = o;
            else
                rects[i].Poly.pCaffeineObj = o;
            break;
        }
        default:
            fprintf(stderr, "unknown op %u\n", op);
            return 2;
        }
        fflush(stdout);         // a crash's transcript ends at its op
    }
    return 0;
}
