// Harness for tools/trackpath_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the heap labels.
//
//     trackpath_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "quickspline.h"
#include "trackpath.h"

// realtime.c's clock, which ReplaySnapshot_Init stamps; not linked here.
int32_t WorldTimer;
int32_t WorldLoopCounter;

enum {
    OP_TAG, OP_PATH, OP_POINT, OP_CHUNK, OP_LOAD, OP_SETUP, OP_CLOSE,
    OP_UNLOAD, OP_CTOR, OP_DTOR, OP_LOADER, OP_UNLOADER, OP_MPOKE, OP_DUMP,
    OP_FCP, OP_FCAP, OP_CINIT, OP_CINITAT, OP_UPDATE, OP_ALONG, OP_CPOKE,
    OP_CDUMP, OP_CMP, OP_FCPD, OP_CRESET, OP_CRESETD
};

enum { M_LEN, M_REV, M_NPATHS, M_PATHS, M_NPOINTS, M_POINTS };
enum {
    C_X, C_Y, C_PT, C_PARAM, C_RATIO, C_DIST, C_DIRX, C_DIRY, C_CAF,
    C_CAFHI
};

#define NPATHS    16
#define NPOINTS   512
#define CHUNK_W   4096
#define NCOORDS   4
#define SLACK     16        // quickspline.c's extra vector, in bytes
#define MAX_DUMP  80
#define MAX_HEAP  4096
#define IMAGE_QUICKSPLINE_SIZE 40

static TrackPath           paths_tab[NPATHS];
static TrackPathPoint      points_tab[NPOINTS];
static uint32_t            chunk_w[CHUNK_W];
static TrackPathCoordinate coords[NCOORDS];

static const char TRACKPATH_CPP[]   = "..\\indep\\src\\trackpath.cpp";
static const char QUICKSPLINE_CPP[] = "..\\indep\\src\\quickspline.cpp";

// ------------------------------------------------------------- the heap

static struct {
    const void *p;
    size_t      span;       // what the port asked for
} heap[MAX_HEAP];
static int nheap;

// The image's QuickSpline is 40 bytes and the port's is not on a 64-bit
// host; its buffers are one vector short of the port's. The log prints
// what the image asked for.
static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    void *p = malloc((size_t)size);
    int   shown = size;

    if (nheap >= MAX_HEAP) {
        fprintf(stderr, "heap log full\n");
        exit(3);
    }
    if (strcmp(name, TRACKPATH_CPP) == 0 && size == (int)sizeof(QuickSpline))
        shown = IMAGE_QUICKSPLINE_SIZE;
    else if (strcmp(name, QUICKSPLINE_CPP) == 0)
        shown = size - SLACK;
    heap[nheap].p = p;
    heap[nheap].span = (size_t)size;
    printf("  alloc h%d size %d name %s flags %d pool %d\n", nheap, shown,
           name, flags, pool);
    nheap++;
    return p;
}

static void label(char *buf, size_t n, const void *a);

// Logged, never freed, so no address is handed out twice.
static void free_hook(void *p)
{
    char b[48];

    label(b, sizeof b, p);
    printf("  free %s\n", b);
}

static void label(char *buf, size_t n, const void *a)
{
    const char *base = (const char *)a;
    struct { const void *p; size_t size; const char *name; } r[4];
    int i;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return;
    }
    r[0].p = paths_tab;  r[0].size = sizeof paths_tab;  r[0].name = "paths";
    r[1].p = points_tab; r[1].size = sizeof points_tab; r[1].name = "points";
    r[2].p = chunk_w;    r[2].size = sizeof chunk_w;    r[2].name = "chunk";
    r[3].p = QuickSplineBasisMatricies;
    r[3].size = sizeof QuickSplineBasisMatricies;
    r[3].name = "basis";

    for (i = 0; i < 4; i++) {
        const char *p = (const char *)r[i].p;
        if (base >= p && base < p + r[i].size) {
            if (base == p)
                snprintf(buf, n, "%s", r[i].name);
            else
                snprintf(buf, n, "%s+%d", r[i].name, (int)(base - p));
            return;
        }
    }
    for (i = 0; i < nheap; i++) {
        const char *p = (const char *)heap[i].p;
        if (base >= p && base < p + heap[i].span) {
            if (base == p)
                snprintf(buf, n, "h%d", i);
            else
                snprintf(buf, n, "h%d+%d", i, (int)(base - p));
            return;
        }
    }
    snprintf(buf, n, "?");
}

static int is_heap(const void *a)
{
    int i;

    for (i = 0; i < nheap; i++)
        if (heap[i].p == a)
            return 1;
    return 0;
}

// ------------------------------------------------------------ the script

static int32_t *words_in;
static size_t   nwords_in, rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "script overrun\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next(), i, k;
    char  **out = malloc(sizeof(char *) * (size_t)(n > 0 ? n : 1));

    for (i = 0; i < n; i++) {
        int32_t len = next();
        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, sizeof u);
    return u;
}

static float bitsf(int32_t b)
{
    float f;

    memcpy(&f, &b, sizeof f);
    return f;
}

// ------------------------------------------------------------ the prints

static void pvec(const char *pre, const bVector4 *v)
{
    printf("%s%08x %08x %08x %08x", pre, (unsigned)fbits(v->x),
           (unsigned)fbits(v->y), (unsigned)fbits(v->z),
           (unsigned)fbits(v->w));
}

static void dump_spline(const QuickSpline *s)
{
    char b0[48], b1[48], b2[48];
    int  i, cnt;

    label(b0, sizeof b0, s->pControlPointBuffer);
    label(b1, sizeof b1, s->pControlPoints);
    label(b2, sizeof b2, s->pBasisMatricies);
    printf("    ept %d bt %d max %08x min %08x len %08x dirty %d alloc %d "
           "minc %d maxc %d n %d buf %s cp %s basis %s\n",
           (int)s->EndPointType, (int)s->BasisType,
           (unsigned)fbits(s->MaxParam), (unsigned)fbits(s->MinParam),
           (unsigned)fbits(s->Length), s->ControlPointsDirty,
           s->BufferWasAllocated, s->MinControlPoints, s->MaxControlPoints,
           s->NumControlPoints, b0, b1, b2);
    cnt = s->MaxControlPoints + 3;
    if (cnt > MAX_DUMP)
        cnt = MAX_DUMP;
    for (i = 0; i < cnt; i++) {
        char pre[16];
        snprintf(pre, sizeof pre, "    b%d ", i);
        pvec(pre, &s->pControlPointBuffer[i]);
        printf("\n");
    }
    if (is_heap(s->pControlPointBuffer)
        && s->MaxControlPoints + 3 <= MAX_DUMP) {
        pvec("    slack ",
             &s->pControlPointBuffer[s->MaxControlPoints + 3]);
        printf("\n");
    }
}

static void dump(int splines)
{
    TrackPathManager *m = &TheTrackPathManager;
    char b0[48], b1[48];
    int  i, n;

    label(b0, sizeof b0, m->pPaths);
    label(b1, sizeof b1, m->pPoints);
    printf("mgr len %08x rev %d npaths %d paths %s npoints %d points %s\n",
           (unsigned)fbits(m->TrackLength), m->ReverseTrackDirection,
           m->NumPaths, b0, m->NumPoints, b1);
    if (m->pPaths == NULL)
        return;
    n = m->NumPaths < NPATHS ? m->NumPaths : NPATHS;
    for (i = 0; i < n; i++) {
        const TrackPath *p = &m->pPaths[i];
        QuickSpline     *s = trackpath_path_spline(p);
        char             b[48];

        label(b, sizeof b, s);
        if (s == NULL && p->pQuickSpline != 0)
            snprintf(b, sizeof b, "word %08x", (unsigned)p->pQuickSpline);
        printf("  path%d num %d loop %d begin %d end %d n %d bd %08x ed %08x "
               "ratio %08x bp %08x %08x ep %08x %08x spline %s\n",
               i, p->PathNumber, p->Looping, p->BeginPointNumber,
               p->EndPointNumber, p->NumPoints,
               (unsigned)fbits(p->BeginDistance),
               (unsigned)fbits(p->EndDistance),
               (unsigned)fbits(p->DistanceRatio),
               (unsigned)fbits(p->BeginPosition.x),
               (unsigned)fbits(p->BeginPosition.y),
               (unsigned)fbits(p->EndPosition.x),
               (unsigned)fbits(p->EndPosition.y), b);
        if (splines && s != NULL)
            dump_spline(s);
    }
}

static void cdump(int slot)
{
    const TrackPathCoordinate *c = &coords[slot];
    char b0[48], b1[48];

    label(b0, sizeof b0, c->pTrackPoint);
    label(b1, sizeof b1, c->pCaffeineObj);
    printf("c%d pos %08x %08x pt %s param %08x ratio %08x dist %08x "
           "dir %08x %08x caf %s %08x\n",
           slot, (unsigned)fbits(c->Position.x),
           (unsigned)fbits(c->Position.y), b0,
           (unsigned)fbits(c->SplineParam),
           (unsigned)fbits(c->RatioAroundTrack),
           (unsigned)fbits(c->DistanceAroundTrack),
           (unsigned)fbits(c->PathDirection.x),
           (unsigned)fbits(c->PathDirection.y), b1,
           (unsigned)c->CaffeineObjHigh);
}

// A table pointer from a poke: -1 is NULL, anything else a byte offset.
static void *at(void *base, int32_t off)
{
    return off < 0 ? NULL : (void *)((uint8_t *)base + off);
}

// The manager's point `idx`, by bytes, the way the image indexes.
static TrackPathPoint *mpoint(int32_t idx)
{
    return (TrackPathPoint *)(void *)
        ((uint8_t *)TheTrackPathManager.pPoints + (ptrdiff_t)idx * 20);
}

static void mpoke(int k, int32_t v)
{
    TrackPathManager *m = &TheTrackPathManager;

    switch (k) {
    case M_LEN:     m->TrackLength = bitsf(v); break;
    case M_REV:     m->ReverseTrackDirection = v; break;
    case M_NPATHS:  m->NumPaths = v; break;
    case M_PATHS:   m->pPaths = at(paths_tab, v); break;
    case M_NPOINTS: m->NumPoints = v; break;
    case M_POINTS:  m->pPoints = at(points_tab, v); break;
    default:
        fprintf(stderr, "mpoke %d\n", k);
        exit(2);
    }
}

static void cpoke(TrackPathCoordinate *c, int k, int32_t v)
{
    switch (k) {
    case C_X:     c->Position.x = bitsf(v); break;
    case C_Y:     c->Position.y = bitsf(v); break;
    case C_PT:    c->pTrackPoint = v < 0 ? NULL : mpoint(v); break;
    case C_PARAM: c->SplineParam = bitsf(v); break;
    case C_RATIO: c->RatioAroundTrack = bitsf(v); break;
    case C_DIST:  c->DistanceAroundTrack = bitsf(v); break;
    case C_DIRX:  c->PathDirection.x = bitsf(v); break;
    case C_DIRY:  c->PathDirection.y = bitsf(v); break;
    case C_CAF:   c->pCaffeineObj = (void *)(uintptr_t)(uint32_t)v; break;
    case C_CAFHI: c->CaffeineObjHigh = (uint32_t)v; break;
    default:
        fprintf(stderr, "cpoke %d\n", k);
        exit(2);
    }
}

int main(int argc, char **argv)
{
    FILE    *fh;
    long     size;
    char   **tags;
    int32_t  ntags;
    size_t   end;

    if (argc < 2) {
        fprintf(stderr, "usage: trackpath_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words_in = malloc((size_t)size);
    nwords_in = (size_t)size / 4;
    if (fread(words_in, 4, nwords_in, fh) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);

    tags = read_strings(&ntags);
    end = (size_t)next();
    end += rd;

    bSetMemoryHooks(malloc_hook, free_hook);

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_PATH: {
            int32_t idx = next(), w[10], k;
            for (k = 0; k < 10; k++)
                w[k] = next();
            memcpy(&paths_tab[idx], w, sizeof w);
            break;
        }
        case OP_POINT: {
            int32_t idx = next(), w[5], k;
            for (k = 0; k < 5; k++)
                w[k] = next();
            memcpy(&points_tab[idx], w, sizeof w);
            break;
        }
        case OP_CHUNK: {
            int32_t off = next(), w = next();
            chunk_w[off / 4] = (uint32_t)w;
            break;
        }
        case OP_LOAD: {
            int32_t npoints = next(), npaths = next(), wrap = next();
            printf("load points %d paths %d\n", npoints, npaths);
            if (wrap)
                load_track_paths(points_tab, npoints, paths_tab, npaths);
            else
                trackpath_manager_load(&TheTrackPathManager, points_tab,
                                       npoints, paths_tab, npaths);
            break;
        }
        case OP_SETUP:
            printf("init\n");
            if (next())
                init_track_paths();
            else
                trackpath_manager_setup(&TheTrackPathManager);
            break;
        case OP_CLOSE:
            printf("close\n");
            if (next())
                close_track_paths();
            else
                trackpath_manager_close(&TheTrackPathManager);
            break;
        case OP_UNLOAD:
            printf("unload\n");
            if (next())
                unload_track_paths();
            else
                trackpath_manager_unload(&TheTrackPathManager);
            break;
        case OP_CTOR:
            printf("ctor\n");
            trackpath_manager_init(&TheTrackPathManager);
            break;
        case OP_DTOR:
            printf("dtor\n");
            trackpath_manager_dtor(&TheTrackPathManager);
            break;
        case OP_LOADER: {
            int r;
            if (next())
                r = loader_track_path((uint8_t *)chunk_w);
            else
                r = trackpath_loader(&TheTrackPathManager,
                                     (uint8_t *)chunk_w);
            printf("loader -> %d\n", r);
            break;
        }
        case OP_UNLOADER: {
            int r;
            if (next())
                r = unloader_track_path((const uint8_t *)chunk_w);
            else
                r = trackpath_unloader(&TheTrackPathManager,
                                       (const uint8_t *)chunk_w);
            printf("unloader -> %d\n", r);
            break;
        }
        case OP_MPOKE: {
            int32_t k = next(), v = next();
            mpoke(k, v);
            break;
        }
        case OP_DUMP:
            dump(next());
            break;
        case OP_FCP: {
            int32_t x = next(), y = next();
            bVector2 p;
            char b[48];
            p.x = bitsf(x);
            p.y = bitsf(y);
            label(b, sizeof b,
                  trackpath_find_closest_point(&TheTrackPathManager, &p));
            printf("fcp %08x %08x -> %s\n", (unsigned)x, (unsigned)y, b);
            break;
        }
        case OP_FCAP: {
            int32_t x = next(), y = next(), idx = next();
            bVector2 p;
            char b[48];
            p.x = bitsf(x);
            p.y = bitsf(y);
            label(b, sizeof b,
                  trackpath_find_closest_adjacent_point(&TheTrackPathManager,
                                                        &p, mpoint(idx)));
            printf("fcap %08x %08x pt %d -> %s\n", (unsigned)x, (unsigned)y,
                   idx, b);
            break;
        }
        case OP_CINIT: {
            int32_t slot = next();
            printf("cinit c%d\n", slot);
            trackpath_coord_init(&coords[slot]);
            break;
        }
        case OP_CINITAT: {
            int32_t slot = next(), x = next(), y = next();
            bVector2 p;
            p.x = bitsf(x);
            p.y = bitsf(y);
            printf("cinit c%d at %08x %08x\n", slot, (unsigned)x,
                   (unsigned)y);
            trackpath_coord_init_at(&coords[slot], &p);
            break;
        }
        case OP_UPDATE: {
            int32_t slot = next(), x = next(), y = next(), via = next();
            bVector2 p;
            p.x = bitsf(x);
            p.y = bitsf(y);
            printf("update c%d %08x %08x\n", slot, (unsigned)x, (unsigned)y);
            if (via)
                trackpath_coord_update_position(&coords[slot], &p);
            else
                trackpath_manager_update_position(&TheTrackPathManager,
                                                  &coords[slot], &p);
            break;
        }
        case OP_ALONG: {
            int32_t slot = next(), along = next(), side = next();
            int32_t path = next(), via = next();
            printf("along c%d %08x %08x path %d\n", slot, (unsigned)along,
                   (unsigned)side, via ? 0 : path);
            if (via)
                trackpath_coord_update_position_along(&coords[slot],
                                                      bitsf(along),
                                                      bitsf(side));
            else
                trackpath_manager_update_position_along(
                    &TheTrackPathManager, &coords[slot], bitsf(along),
                    bitsf(side), path);
            break;
        }
        case OP_CPOKE: {
            int32_t slot = next(), k = next(), v = next();
            cpoke(&coords[slot], k, v);
            break;
        }
        case OP_CDUMP:
            cdump(next());
            break;
        case OP_FCPD: {
            int32_t x = next(), y = next(), d = next();
            bVector2 p;
            char b[48];
            p.x = bitsf(x);
            p.y = bitsf(y);
            label(b, sizeof b,
                  trackpath_find_closest_point_near(&TheTrackPathManager, &p,
                                                    bitsf(d)));
            printf("fcpd %08x %08x %08x -> %s\n", (unsigned)x, (unsigned)y,
                   (unsigned)d, b);
            break;
        }
        case OP_CRESET: {
            int32_t slot = next(), x = next(), y = next();
            bVector2 p;
            p.x = bitsf(x);
            p.y = bitsf(y);
            printf("reset c%d %08x %08x\n", slot, (unsigned)x, (unsigned)y);
            trackpath_coord_reset_position(&coords[slot], &p);
            break;
        }
        case OP_CRESETD: {
            int32_t slot = next(), x = next(), y = next(), d = next();
            bVector2 p;
            p.x = bitsf(x);
            p.y = bitsf(y);
            printf("reset c%d %08x %08x near %08x\n", slot, (unsigned)x,
                   (unsigned)y, (unsigned)d);
            trackpath_coord_reset_position_near(&coords[slot], &p, bitsf(d));
            break;
        }
        case OP_CMP: {
            int32_t kind = next(), a = next(), b = next();
            float r;
            if (kind == 0)
                r = trackpath_compare_distances(&TheTrackPathManager,
                                                bitsf(a), bitsf(b));
            else if (kind == 1)
                r = trackpath_compare_percent_distances(&TheTrackPathManager,
                                                        bitsf(a), bitsf(b));
            else
                r = trackpath_compare_ratios(&TheTrackPathManager, bitsf(a),
                                             bitsf(b));
            printf("cmp%d %08x %08x -> %08x\n", kind, (unsigned)a,
                   (unsigned)b, (unsigned)fbits(r));
            break;
        }
        default:
            fprintf(stderr, "op %d at word %u\n", (int)op, (unsigned)rd);
            return 2;
        }
    }
    (void)ntags;
    return 0;
}
