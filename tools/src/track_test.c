// Harness for tools/track_check.py: runs the checker's op script on the
// port -- track.c, terraintype.c and cartrack.c -- and prints what the model prints for
// the image. The ops, their arguments and every line's format are the
// checker's; this file only carries them out. See the checker's docstring
// for the labels, the pool arena and the ticks.
//
//     track_test ops.bin > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bslotpool.h"
#include "bticker.h"
#include "bvector.h"
#include "car.h"
#include "p32.h"
#include "terraintype.h"
#include "topology.h"
#include "track.h"

enum {
    OP_TAG, OP_CLEAR, OP_CHUNKW, OP_FILE, OP_LOADER, OP_UNLOADER,
    OP_TTLOADER, OP_TTUNLOADER, OP_MEM, OP_TREEINIT, OP_INITTREE,
    OP_CLOSETREE, OP_TREEDUMP, OP_POOL, OP_TPINIT, OP_TPDESTROY, OP_TPDUMP,
    OP_VEC, OP_SHAFT, OP_TPSEG, OP_TPTEST, OP_TCINIT, OP_TCDESTROY,
    OP_TCCLEAR, OP_TCDUMP, OP_TCPOKE, OP_TCSET, OP_SIB, OP_ELEV,
    OP_HASTOPO, OP_TCSEG, OP_CONSTRAIN, OP_CORNER, OP_SQUARE, OP_GIP,
    OP_BUILD, OP_REMOVE, OP_ASSIGN, OP_UNASSIGN, OP_FLUSH, OP_NMARK,
    OP_GMARK, OP_NMARKN, OP_GMARKN, OP_MARKDUMP, OP_INFO, OP_GLOBALS,
    OP_GRID, OP_NOISE, OP_MATCHNAME, OP_MATCHHASH, OP_TICKSEED, OP_HSET,
    OP_TPCB, OP_COG, OP_WHEEL, OP_CARPOS, OP_FLAT, OP_PUTFLAT, OP_SIB3,
    OP_CARVEC, OP_CARF, OP_AIR, OP_BEGIN, OP_VOT,
    OP_COUNT
};

#define NCHUNK    8
#define CH_SPAN   0x100000
#define NTC       4
#define NVEC      16
#define NH        16
#define NSLOTS    1024
#define SENTINEL  0x5a5a5a5au
#define MAX_WALK  1100

static _Alignas(16) uint8_t chunkmem[NCHUNK][CH_SPAN];
static int32_t              mis[NCHUNK];
static TopologyCoordinate   tcs[NTC];
static _Alignas(16) bVector3 vecs[NVEC];
static TrackPolygon        *outs[NH][TOPOLOGY_MAX_POLYGONS];
static int32_t              held[NH];   // how many of outs[h] are set
static TopologyTreePolygon *gipout[TOPOLOGY_MAX_POLYGONS];

// The car FindFlatOnTrackPosition, PutFlatOnTrack, AverageAir and
// BeginMovement are handed, and its type. Beyond pCarTypeInfo, State and
// TheTopologyCoordinate, BeginMovement writes the two old velocities and
// LastInTroughPosition.
static Car           g_car;
static CarTypeInfo   g_cti;
static bMatrix4      g_mat;

static char **strs;
static int32_t nstrs;

// ------------------------------------------------------------ the arena

// Every pool the tree makes comes out of this one block, zeroed, as every
// one the model's image makes comes out of one fixed address: the same
// TrackPolygon addresses recur from pool to pool, so the p32 registry
// never holds more than one pool's worth, and a pointer left over from a
// closed pool labels the same way on both sides.
static _Alignas(16) uint8_t arena[BSLOTPOOL_HEADER_SIZE
                                  + NSLOTS * sizeof(TrackPolygon)];

static void *arena_alloc(size_t bytes, const char *name, int memoryPool)
{
    if (bytes > sizeof arena) {
        fprintf(stderr, "pool of %zu bytes does not fit the arena\n", bytes);
        exit(3);
    }
    printf("  pool alloc %s mp %d\n", name, memoryPool);
    memset(arena, 0, sizeof arena);
    return arena;
}

static void arena_release(void *block)
{
    (void)block;
    printf("  pool free\n");
}

static void printf_hook(const char *text)
{
    (void)text;
    printf("  printf\n");
}

// ------------------------------------------------------------ the ticks

static uint32_t tick_state;

static uint32_t tick(void)
{
    tick_state = tick_state * 1664525u + 1013904223u;
    return tick_state;
}

// ------------------------------------------------------------ the labels

static uint8_t *chunk_at(int k)
{
    return chunkmem[k] + mis[k];
}

static TrackPolygon *slot_tp(int32_t slot)
{
    if (slot < 0 || TrackPolygonSlotPool == NULL)
        return NULL;
    return (TrackPolygon *)bGetSlot(TrackPolygonSlotPool, slot);
}

static const char *label(char *buf, size_t n, const void *a)
{
    const uint8_t *p = (const uint8_t *)a;
    int k;

    if (a == NULL) {
        snprintf(buf, n, "null");
        return buf;
    }
    if (a == (const void *)&TrackPositionMarkerList) {
        snprintf(buf, n, "markers");
        return buf;
    }
    if (a == (const void *)&TheTopologyTree) {
        snprintf(buf, n, "tree");
        return buf;
    }
    if (a == (const void *)&TheTopologyTree.TrackPolygonList) {
        snprintf(buf, n, "tplist");
        return buf;
    }
    if (TrackPolygonSlotPool != NULL) {
        const uint8_t *base = (const uint8_t *)bGetSlot(TrackPolygonSlotPool, 0);
        size_t span = NSLOTS * sizeof(TrackPolygon);

        if (p >= base && p < base + span) {
            size_t off = (size_t)(p - base);
            if (off % sizeof(TrackPolygon) == 0)
                snprintf(buf, n, "tp%d", (int)(off / sizeof(TrackPolygon)));
            else
                snprintf(buf, n, "tp%d+?", (int)(off / sizeof(TrackPolygon)));
            return buf;
        }
    }
    for (k = 0; k < NCHUNK; k++) {
        if (p >= chunkmem[k] && p < chunkmem[k] + CH_SPAN) {
            snprintf(buf, n, "c%d%+d", k, (int)(p - chunk_at(k)));
            return buf;
        }
    }
    for (k = 0; k < NTC; k++) {
        const uint8_t *b = (const uint8_t *)&tcs[k];
        if (p >= b && p < b + sizeof tcs[k]) {
            if (p == b)
                snprintf(buf, n, "tc%d", k);
            else
                snprintf(buf, n, "tc%d+?", k);
            return buf;
        }
    }
    for (k = 0; k < NVEC; k++) {
        if (a == (const void *)&vecs[k]) {
            snprintf(buf, n, "v%d", k);
            return buf;
        }
    }
    snprintf(buf, n, "?");
    return buf;
}

// Eight buffers in turn, so one printf can carry eight labels. A function
// and not a macro: each call's increment is sequenced.
static char lb[8][48];
static unsigned li;

static const char *L(const void *p)
{
    char *b = lb[li++ & 7];

    return label(b, sizeof lb[0], p);
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

static const char *str(int32_t i)
{
    if (i < 0 || i >= nstrs) {
        fprintf(stderr, "string %d\n", i);
        exit(2);
    }
    return strs[i];
}

// ------------------------------------------------------------ the prints

// Sixteen labels to a line, each array read through its own type.
#define PRINT_LABELS(pre, arr, n)                                          \
    do {                                                                   \
        int i_;                                                            \
        for (i_ = 0; i_ < (n); i_++) {                                     \
            if (i_ % 16 == 0)                                              \
                printf("%s%s", i_ ? "\n" : "", (pre));                     \
            printf(" %s", L((arr)[i_]));                                   \
        }                                                                  \
        if ((n) > 0)                                                       \
            printf("\n");                                                  \
    } while (0)

static void tree_dump(int list)
{
    TopologyTree *t = &TheTopologyTree;
    TrackListNode *head = &t->TrackPolygonList;
    TrackListNode *nd;
    int i;

    printf("tree nodes %s %d squares %s %d polys %s %d idx %s %d "
           "list %s %s\n",
           L(t->pNodeTable), t->NumNodes, L(t->pSquareTable), t->NumSquares,
           L(t->pPolygonTable), t->NumPolygons, L(t->pPolygonIndexTable),
           t->NumPolygonIndicies, L(p32_ptr(head->pNext)),
           L(p32_ptr(head->pPrev)));
    if (!list)
        return;
    i = 0;
    for (nd = p32_ptr(head->pNext); nd != head && i < MAX_WALK;
         nd = p32_ptr(nd->pNext), i++) {
        if (i % 16 == 0)
            printf("%s  fwd", i ? "\n" : "");
        printf(" %s:%d", L(nd), ((TrackPolygon *)nd)->ReferenceCount);
    }
    if (i)
        printf("\n");
    i = 0;
    for (nd = p32_ptr(head->pPrev); nd != head && i < MAX_WALK;
         nd = p32_ptr(nd->pPrev), i++) {
        if (i % 16 == 0)
            printf("%s  back", i ? "\n" : "");
        printf(" %s", L(nd));
    }
    if (i)
        printf("\n");
}

static void pool_dump(void)
{
    BSlotPool *p = TrackPolygonSlotPool;

    if (p == NULL) {
        printf("pool null\n");
        return;
    }
    printf("pool flags %u alloc %d most %d slots %d total %d free %s\n",
           (unsigned)p->flags, p->numAllocatedSlots,
           p->mostNumAllocatedSlots, p->numSlots, p->totalNumSlots,
           L(p->freeSlots));
}

static void tp_dump(int32_t slot)
{
    TrackPolygon *tp = slot_tp(slot);
    int i;

    if (tp == NULL) {
        printf("tp%d none\n", slot);
        return;
    }
    printf("tp%d ref %d nv %d fl %d ty %d poly %s cb %s bb %08x %08x %08x "
           "%08x v",
           slot, tp->ReferenceCount, tp->NumVertices, tp->Flags,
           tp->TheTerrainType, L(tp->pPolygon), L(tp->pCollisionBody),
           (unsigned)fbits(tp->BBoxMin.x), (unsigned)fbits(tp->BBoxMin.y),
           (unsigned)fbits(tp->BBoxMax.x), (unsigned)fbits(tp->BBoxMax.y));
    for (i = 0; i < 4; i++)
        printf(" %08x %08x %08x", (unsigned)fbits(tp->Vertices[i].x),
               (unsigned)fbits(tp->Vertices[i].y),
               (unsigned)fbits(tp->Vertices[i].z));
    printf(" n %08x %08x %08x pd %08x\n", (unsigned)fbits(tp->Normal.x),
           (unsigned)fbits(tp->Normal.y), (unsigned)fbits(tp->Normal.z),
           (unsigned)fbits(tp->PlaneDistance));
}

static void tc_dump(int i)
{
    TopologyCoordinate *tc = &tcs[i];
    int n = tc->TotalNumTrackPolygons;

    printf("tc%d ib %08x %08x %08x %08x cb %08x %08x %08x %08x total %d "
           "num %d vert %d ud %d\n",
           i, (unsigned)fbits(tc->InterestBBoxMin.x),
           (unsigned)fbits(tc->InterestBBoxMin.y),
           (unsigned)fbits(tc->InterestBBoxMax.x),
           (unsigned)fbits(tc->InterestBBoxMax.y),
           (unsigned)fbits(tc->CachedBBoxMin.x),
           (unsigned)fbits(tc->CachedBBoxMin.y),
           (unsigned)fbits(tc->CachedBBoxMax.x),
           (unsigned)fbits(tc->CachedBBoxMax.y), n, tc->NumTrackPolygons,
           tc->NumVerticalTrackPolygons, tc->NumUpsideDownTrackPolygons);
    if (n < 0)
        n = 0;
    if (n > TOPOLOGY_MAX_POLYGONS)
        n = TOPOLOGY_MAX_POLYGONS;
    PRINT_LABELS("  t", tc->TrackPolygonTable, n);
}

static void mark_dump(void)
{
    TrackListNode *head = &TrackPositionMarkerList;
    TrackListNode *nd;
    int i = 0;

    printf("markers next %s prev %s\n", L(p32_ptr(head->pNext)),
           L(p32_ptr(head->pPrev)));
    for (nd = p32_ptr(head->pNext); nd != head && i < MAX_WALK;
         nd = p32_ptr(nd->pNext), i++) {
        const TrackPositionMarker *m = (const TrackPositionMarker *)nd;

        printf("  mk %s hash %08x param %d pos %08x %08x\n", L(nd),
               (unsigned)m->NameHash, m->Param,
               (unsigned)fbits(m->Position.x), (unsigned)fbits(m->Position.y));
    }
    i = 0;
    for (nd = p32_ptr(head->pPrev); nd != head && i < MAX_WALK;
         nd = p32_ptr(nd->pPrev), i++) {
        if (i % 16 == 0)
            printf("%s  back", i ? "\n" : "");
        printf(" %s", L(nd));
    }
    if (i)
        printf("\n");
}

static void globals_dump(void)
{
    int i;

    printf("globals cur %s table %s highest %d loaded %d pool %s tidx %u\n",
           L(CurrentTrackInfo), L(TrackInfoTable), HighestTrackNumber,
           LoadedTrackNumber, TrackPolygonSlotPool ? "pool" : "null",
           (unsigned)TopologyTimingIndex);
    printf("  timing");
    for (i = 0; i < 10; i++)
        printf(" %08x", (unsigned)fbits(TopologyTiming[i]));
    printf("\n");
}

static void pv(const bVector3 *v)
{
    printf("%08x %08x %08x %08x", (unsigned)fbits(v->x), (unsigned)fbits(v->y),
           (unsigned)fbits(v->z), (unsigned)fbits(v->pad));
}

static void mat_dump(const bMatrix4 *m)
{
    const float *f = (const float *)(const void *)m;
    int i;

    printf("  m");
    for (i = 0; i < 16; i++)
        printf(" %08x", (unsigned)fbits(f[i]));
    printf("\n");
}

static void timing_line(void)
{
    printf("  timing %u %08x\n", (unsigned)TopologyTimingIndex,
           (unsigned)fbits(TopologyTiming[(TopologyTimingIndex + 9u) % 10u]));
}

// CARVEC's vectors, by the model's number: the body matrix's rows, the
// velocity, the angular velocity, the four wheel matrices' sixteen rows,
// the two old velocities and Position.
static float *car_vec(int k)
{
    if (k < 4)
        return (float *)(void *)&g_car.State.BodyMatrix + 4 * k;
    if (k == 4)
        return &g_car.State.Velocity.x;
    if (k == 5)
        return &g_car.State.AngularVelocity.x;
    if (k < 22)
        return (float *)(void *)&g_car.State.WheelMatrix[(k - 6) / 4]
               + 4 * ((k - 6) % 4);
    if (k == 22)
        return &g_car.vOldVel.x;
    if (k == 23)
        return &g_car.vOldAngVel.x;
    return &g_car.State.Position.x;
}

// CARF's words.
static void *car_word(int k)
{
    switch (k) {
    case 0: return &g_car.State.VelocityMagnitude;
    case 1: return &g_car.State.nWheelsTouchingGround;
    case 2: return &g_car.LastInTroughPosition.x;
    case 3: return &g_car.LastInTroughPosition.y;
    case 4: return &g_cti.Body.Mass;
    case 5: return &g_cti.Aero.Drag;
    case 6: return &g_cti.Aero.FrontDownforce;
    case 7: return &g_cti.Aero.RearDownforce;
    case 8: return &g_cti.Aero.AutoBalanceDownforce;
    default: return &g_car.State.CrossedWheelTerrain[k - 9];
    }
}

static void begin_dump(void)
{
    int32_t t[4];
    int i;

    printf("  old ");
    pv(&g_car.vOldVel);
    printf(" ang ");
    pv(&g_car.vOldAngVel);
    printf("\n  trough %08x %08x crossed",
           (unsigned)fbits(g_car.LastInTroughPosition.x),
           (unsigned)fbits(g_car.LastInTroughPosition.y));
    memcpy(t, g_car.State.CrossedWheelTerrain, sizeof t);
    for (i = 0; i < 4; i++)
        printf(" %d", (int)t[i]);
    printf("\n");
}

static void fill(void *p, size_t n)
{
    uint32_t s = SENTINEL;
    size_t i;

    for (i = 0; i + 4 <= n; i += 4)
        memcpy((uint8_t *)p + i, &s, 4);
}

// ------------------------------------------------------------ the ops

static void load_file(int k, int32_t m, const char *path, long off,
                      int32_t nbytes)
{
    FILE *fh = fopen(path, "rb");

    if (fh == NULL || fseek(fh, off, SEEK_SET) != 0
        || nbytes < 0 || (size_t)nbytes + (size_t)m > CH_SPAN
        || fread(chunkmem[k] + m, 1, (size_t)nbytes, fh) != (size_t)nbytes) {
        fprintf(stderr, "cannot read %d bytes at %ld of %s\n", nbytes, off,
                path);
        exit(2);
    }
    fclose(fh);
}

static void set_tcfield(TopologyCoordinate *tc, int field, int32_t v)
{
    switch (field) {
    case 0: tc->InterestBBoxMin.x = bitsf(v); break;
    case 1: tc->InterestBBoxMin.y = bitsf(v); break;
    case 2: tc->InterestBBoxMax.x = bitsf(v); break;
    case 3: tc->InterestBBoxMax.y = bitsf(v); break;
    case 4: tc->CachedBBoxMin.x = bitsf(v); break;
    case 5: tc->CachedBBoxMin.y = bitsf(v); break;
    case 6: tc->CachedBBoxMax.x = bitsf(v); break;
    case 7: tc->CachedBBoxMax.y = bitsf(v); break;
    case 8: tc->TotalNumTrackPolygons = v; break;
    case 9: tc->NumTrackPolygons = v; break;
    case 10: tc->NumVerticalTrackPolygons = v; break;
    case 11: tc->NumUpsideDownTrackPolygons = v; break;
    default:
        fprintf(stderr, "tcpoke %d\n", field);
        exit(2);
    }
}

static void step(int code)
{
    int32_t a[8];
    static const int nargs[OP_COUNT] = {
        [OP_TAG] = 1, [OP_CLEAR] = 2, [OP_CHUNKW] = 3, [OP_FILE] = 5,
        [OP_LOADER] = 1, [OP_UNLOADER] = 1, [OP_TTLOADER] = 1,
        [OP_TTUNLOADER] = 1, [OP_MEM] = 3, [OP_TREEINIT] = 0,
        [OP_INITTREE] = 0, [OP_CLOSETREE] = 0, [OP_TREEDUMP] = 1,
        [OP_POOL] = 0, [OP_TPINIT] = 3, [OP_TPDESTROY] = 2, [OP_TPDUMP] = 1,
        [OP_VEC] = 5, [OP_SHAFT] = 3, [OP_TPSEG] = 4, [OP_TPTEST] = 7,
        [OP_TCINIT] = 1, [OP_TCDESTROY] = 1, [OP_TCCLEAR] = 1,
        [OP_TCDUMP] = 1, [OP_TCPOKE] = 3, [OP_TCSET] = 3, [OP_SIB] = 4,
        [OP_ELEV] = 3, [OP_HASTOPO] = 2, [OP_TCSEG] = 4, [OP_CONSTRAIN] = 7,
        [OP_CORNER] = 1, [OP_SQUARE] = 3, [OP_GIP] = 6, [OP_BUILD] = 4,
        [OP_REMOVE] = 2, [OP_ASSIGN] = 4, [OP_UNASSIGN] = 2, [OP_FLUSH] = 0,
        [OP_NMARK] = 1, [OP_GMARK] = 2, [OP_NMARKN] = 1, [OP_GMARKN] = 2,
        [OP_MARKDUMP] = 0, [OP_INFO] = 1, [OP_GLOBALS] = 0, [OP_GRID] = 2,
        [OP_NOISE] = 2, [OP_MATCHNAME] = 1, [OP_MATCHHASH] = 1,
        [OP_TICKSEED] = 1, [OP_HSET] = 3, [OP_TPCB] = 1,
        [OP_COG] = 4, [OP_WHEEL] = 3, [OP_CARPOS] = 5, [OP_FLAT] = 3,
        [OP_PUTFLAT] = 1, [OP_SIB3] = 4, [OP_CARVEC] = 5, [OP_CARF] = 2,
        [OP_AIR] = 4, [OP_BEGIN] = 2, [OP_VOT] = 2,
    };
    int i;

    if (code < 0 || code >= OP_COUNT) {
        fprintf(stderr, "op %d\n", code);
        exit(2);
    }
    for (i = 0; i < nargs[code]; i++)
        a[i] = next();

    switch (code) {
    case OP_TAG:
        printf("[%s]\n", str(a[0]));
        break;
    case OP_CLEAR:
        memset(chunkmem[a[0]], 0, CH_SPAN);
        mis[a[0]] = a[1];
        break;
    case OP_CHUNKW:
        memcpy(chunk_at(a[0]) + a[1], &a[2], 4);
        break;
    case OP_FILE:
        memset(chunkmem[a[0]], 0, CH_SPAN);
        mis[a[0]] = a[1];
        load_file(a[0], a[1], str(a[2]), (long)a[3], a[4]);
        break;
    case OP_LOADER:
        printf("loader c%d -> %d\n", a[0],
               track_loader_geometry(chunk_at(a[0])));
        break;
    case OP_UNLOADER:
        printf("unloader c%d -> %d\n", a[0],
               track_unloader_geometry(chunk_at(a[0])));
        break;
    case OP_TTLOADER:
        printf("ttloader c%d -> %d\n", a[0],
               topotree_loader(&TheTopologyTree, chunk_at(a[0])));
        break;
    case OP_TTUNLOADER:
        printf("ttunloader c%d -> %d\n", a[0],
               topotree_unloader(&TheTopologyTree, chunk_at(a[0])));
        break;
    case OP_MEM: {
        const uint8_t *p = chunk_at(a[0]) + a[1];

        printf("mem c%d%+d", a[0], a[1]);
        for (i = 0; i < a[2]; i++) {
            uint32_t w;
            memcpy(&w, p + 4 * i, 4);
            printf(" %08x", (unsigned)w);
        }
        printf("\n");
        break;
    }
    case OP_TREEINIT:
        printf("treeinit\n");
        topotree_init(&TheTopologyTree);
        break;
    case OP_INITTREE:
        printf("inittree\n");
        topotree_init_tree(&TheTopologyTree);
        break;
    case OP_CLOSETREE:
        printf("closetree\n");
        topotree_close_tree(&TheTopologyTree);
        break;
    case OP_TREEDUMP:
        tree_dump(a[0]);
        break;
    case OP_POOL:
        pool_dump();
        break;
    case OP_TPINIT: {
        TrackPolygon *tp = slot_tp(a[0]);
        TopologyTreePolygon *p = (TopologyTreePolygon *)(void *)
            (chunk_at(a[1]) + a[2]);

        printf("tpinit tp%d %s -> %s\n", a[0], L(p),
               L(trackpolygon_init(tp, p)));
        break;
    }
    case OP_TPDESTROY:
        printf("tpdestroy tp%d %d\n", a[0], a[1]);
        trackpolygon_destroy(slot_tp(a[0]), a[1]);
        break;
    case OP_TPDUMP:
        tp_dump(a[0]);
        break;
    case OP_VEC:
        vecs[a[0]].x = bitsf(a[1]);
        vecs[a[0]].y = bitsf(a[2]);
        vecs[a[0]].z = bitsf(a[3]);
        vecs[a[0]].pad = bitsf(a[4]);
        break;
    case OP_SHAFT: {
        float d;
        int r;

        fill(&d, sizeof d);
        r = trackpolygon_point_in_shaft(slot_tp(a[0]), &vecs[a[1]],
                                        a[2] ? &d : NULL);
        printf("shaft tp%d v%d -> %d dist %08x\n", a[0], a[1], r,
               (unsigned)fbits(d));
        break;
    }
    case OP_TPSEG: {
        bVector3 o;
        int r;

        fill(&o, sizeof o);
        r = trackpolygon_segment_intersects(slot_tp(a[0]), &vecs[a[1]],
                                            &vecs[a[2]], a[3] ? &o : NULL);
        printf("tpseg tp%d v%d v%d -> %d out ", a[0], a[1], a[2], r);
        pv(&o);
        printf("\n");
        break;
    }
    case OP_TPTEST: {
        float best = bitsf(a[1]);
        int r = trackpolygon_test_segment(slot_tp(a[0]), &best, &vecs[a[2]],
                                          &vecs[a[3]], &vecs[a[4]],
                                          &vecs[a[5]], a[6]);

        printf("tptest tp%d v%d v%d box v%d v%d two %d -> %d best %08x\n",
               a[0], a[2], a[3], a[4], a[5], a[6], r, (unsigned)fbits(best));
        break;
    }
    case OP_TCINIT:
        printf("tcinit tc%d\n", a[0]);
        topology_init(&tcs[a[0]]);
        break;
    case OP_TCDESTROY:
        printf("tcdestroy tc%d\n", a[0]);
        topology_destroy(&tcs[a[0]]);
        break;
    case OP_TCCLEAR:
        printf("tcclear tc%d\n", a[0]);
        topology_clear_interest_bbox(&tcs[a[0]]);
        break;
    case OP_TCDUMP:
        tc_dump(a[0]);
        break;
    case OP_TCPOKE:
        set_tcfield(&tcs[a[0]], a[1], a[2]);
        break;
    case OP_TCSET:
        tcs[a[0]].TrackPolygonTable[a[1]] = slot_tp(a[2]);
        break;
    case OP_SIB:
        printf("sib tc%d v%d r %08x vel %s\n", a[0], a[1], (unsigned)a[2],
               a[3] < 0 ? "null" : L(&vecs[a[3]]));
        topology_set_interest_bbox(&tcs[a[0]], (const bVector2 *)&vecs[a[1]],
                                   bitsf(a[2]),
                                   a[3] < 0 ? NULL
                                            : (const bVector2 *)&vecs[a[3]]);
        break;
    case OP_ELEV: {
        int32_t terr, found;
        bVector3 nrm;
        float r;

        fill(&terr, sizeof terr);
        fill(&found, sizeof found);
        fill(&nrm, sizeof nrm);
        r = topology_get_elevation(&tcs[a[0]], &vecs[a[1]],
                                   (a[2] & 1) ? &terr : NULL,
                                   (a[2] & 2) ? &nrm : NULL,
                                   (a[2] & 4) ? &found : NULL);
        printf("elev tc%d v%d -> %08x terr %08x norm ", a[0], a[1],
               (unsigned)fbits(r), (unsigned)terr);
        pv(&nrm);
        printf(" found %08x\n", (unsigned)found);
        printf("  timing %u %08x\n", (unsigned)TopologyTimingIndex,
               (unsigned)fbits(TopologyTiming[(TopologyTimingIndex + 9u)
                                              % 10u]));
        break;
    }
    case OP_HASTOPO:
        printf("hastopo tc%d v%d -> %d\n", a[0], a[1],
               topology_has_topology(&tcs[a[0]],
                                     (const bVector2 *)&vecs[a[1]]));
        break;
    case OP_TCSEG:
        printf("tcseg tc%d v%d v%d r %08x -> %d\n", a[0], a[1], a[2],
               (unsigned)a[3],
               topology_segment_intersects(&tcs[a[0]], &vecs[a[1]],
                                           &vecs[a[2]], bitsf(a[3])));
        break;
    case OP_CONSTRAIN: {
        int r = topology_constrain(&tcs[a[0]], a[1], a[2], &vecs[a[3]],
                                   &vecs[a[4]], bitsf(a[5]), bitsf(a[6]));

        printf("constrain tc%d type %d two %d v%d v%d dist %08x lift %08x "
               "-> %d to ",
               a[0], a[1], a[2], a[3], a[4], (unsigned)a[5], (unsigned)a[6],
               r);
        pv(&vecs[a[4]]);
        printf("\n");
        break;
    }
    case OP_CORNER:
        printf("corner %08x -> %08x\n", (unsigned)a[0],
               (unsigned)fbits(topotree_get_square_corner(bitsf(a[0]))));
        break;
    case OP_SQUARE:
        printf("square %08x %08x near %d -> %s\n", (unsigned)a[0],
               (unsigned)a[1], a[2],
               L(topotree_get_square(&TheTopologyTree, bitsf(a[0]),
                                     bitsf(a[1]), a[2])));
        break;
    case OP_GIP: {
        const TopologyTreeSquare *sq =
            a[0] < 0 ? NULL
                     : (const TopologyTreeSquare *)(void *)(chunk_at(a[0])
                                                            + a[1]);
        int n;

        fill(gipout, sizeof gipout);
        n = topotree_get_intersecting_polygons(
            &TheTopologyTree, gipout, a[4], sq, (const bVector2 *)&vecs[a[2]],
            (const bVector2 *)&vecs[a[3]]);
        printf("gip %s v%d v%d max %d -> %d\n", L(sq), a[2], a[3], a[4], n);
        PRINT_LABELS("  g", gipout, n);
        if (!a[5]) {
            for (i = 0; i < n; i++)
                gipout[i]->UsedByNeighbourFlag = 0;
        }
        break;
    }
    case OP_BUILD: {
        int n = topotree_build(&TheTopologyTree, outs[a[0]], a[3],
                               (const bVector2 *)&vecs[a[1]],
                               (const bVector2 *)&vecs[a[2]]);

        held[a[0]] = n;
        printf("build h%d v%d v%d max %d -> %d\n", a[0], a[1], a[2], a[3], n);
        PRINT_LABELS("  b", outs[a[0]], n);
        break;
    }
    case OP_REMOVE: {
        // At most what the handle holds: past that the table is NULLs or
        // stale pointers, which the image would read from address 0.
        int32_t n = a[1] < 0 || a[1] > held[a[0]] ? held[a[0]] : a[1];

        printf("remove h%d %d\n", a[0], n);
        topotree_remove(&TheTopologyTree, outs[a[0]], n);
        break;
    }
    case OP_ASSIGN: {
        TopologyTreePolygon *p = (TopologyTreePolygon *)(void *)
            (chunk_at(a[2]) + a[3]);

        outs[a[0]][a[1]] = topotree_assign(&TheTopologyTree, p);
        if (held[a[0]] < a[1] + 1)
            held[a[0]] = a[1] + 1;
        printf("assign h%d[%d] %s -> %s\n", a[0], a[1], L(p),
               L(outs[a[0]][a[1]]));
        break;
    }
    case OP_UNASSIGN:
        printf("unassign h%d[%d] %s\n", a[0], a[1], L(outs[a[0]][a[1]]));
        topotree_unassign(&TheTopologyTree, outs[a[0]][a[1]]);
        break;
    case OP_FLUSH:
        printf("flush\n");
        topotree_flush_unused(&TheTopologyTree);
        break;
    case OP_NMARK:
        printf("nmark %08x -> %d\n", (unsigned)a[0],
               track_get_num_position_markers((uint32_t)a[0]));
        break;
    case OP_GMARK:
        printf("gmark %08x %d -> %s\n", (unsigned)a[0], a[1],
               L(track_get_position_marker((uint32_t)a[0], a[1])));
        break;
    case OP_NMARKN:
        printf("nmarkn s%d -> %d\n", a[0],
               track_get_num_position_markers_named(str(a[0])));
        break;
    case OP_GMARKN:
        printf("gmarkn s%d %d -> %s\n", a[0], a[1],
               L(track_get_position_marker_named(str(a[0]), a[1])));
        break;
    case OP_MARKDUMP:
        mark_dump();
        break;
    case OP_INFO:
        printf("info %d -> %s\n", a[0], L(track_get_info(a[0])));
        break;
    case OP_GLOBALS:
        globals_dump();
        break;
    case OP_GRID:
        printf("grid %d %d -> %08x\n", a[0], a[1],
               (unsigned)fbits(track_get_road_noise_grid_value(a[0], a[1])));
        break;
    case OP_NOISE:
        printf("noise v%d %d -> %08x\n", a[0], a[1],
               (unsigned)fbits(track_get_road_noise(
                   (const bVector2 *)&vecs[a[0]], a[1])));
        break;
    case OP_MATCHNAME:
        printf("matchname s%d -> %d\n", a[0],
               terrain_match_name(a[0] < 0 ? NULL : str(a[0])));
        break;
    case OP_MATCHHASH:
        printf("matchhash %08x -> %d\n", (unsigned)a[0],
               terrain_match_hash((uint32_t)a[0]));
        break;
    case OP_TICKSEED:
        tick_state = (uint32_t)a[0];
        break;
    case OP_HSET:
        outs[a[0]][a[1]] = slot_tp(a[2]);
        if (held[a[0]] < a[1] + 1)
            held[a[0]] = a[1] + 1;
        break;
    case OP_TPCB:
        // Something for the constructor to clear: the tree, which the
        // label prints by name on both sides.
        slot_tp(a[0])->pCollisionBody =
            (struct TrackPolygonCollisionBody *)(void *)&TheTopologyTree;
        break;
    case OP_COG:
        g_cti.CenterOfGravity.x = bitsf(a[0]);
        g_cti.CenterOfGravity.y = bitsf(a[1]);
        g_cti.CenterOfGravity.z = bitsf(a[2]);
        g_cti.CenterOfGravity.pad = bitsf(a[3]);
        break;
    case OP_WHEEL:
        g_cti.Wheels[a[0]].PositionZ = bitsf(a[1]);
        g_cti.Wheels[a[0]].Radius = bitsf(a[2]);
        break;
    case OP_CARPOS:
        g_car.State.Position.x = bitsf(a[0]);
        g_car.State.Position.y = bitsf(a[1]);
        g_car.State.Position.z = bitsf(a[2]);
        g_car.State.Position.pad = bitsf(a[3]);
        g_car.State.Angle = (uint16_t)a[4];
        break;
    case OP_FLAT:
        printf("flat tc%d v%d angle %u\n", a[0], a[1],
               (unsigned)(uint16_t)a[2]);
        fill(&g_mat, sizeof g_mat);
        car_find_flat_on_track_position(&g_car, &g_mat, &vecs[a[1]],
                                        (uint16_t)a[2], &tcs[a[0]]);
        printf("  pos ");
        pv(&vecs[a[1]]);
        printf("\n");
        mat_dump(&g_mat);
        timing_line();
        break;
    case OP_PUTFLAT:
        // tc a[0] is lent to the car for the call and handed back: nothing
        // in a TopologyCoordinate points into itself.
        printf("putflat tc%d\n", a[0]);
        fill(&g_car.State.BodyMatrix, sizeof g_car.State.BodyMatrix);
        fill(&g_car.State.GeometryPosition,
             sizeof g_car.State.GeometryPosition);
        g_car.TheTopologyCoordinate = tcs[a[0]];
        car_put_flat_on_track(&g_car);
        tcs[a[0]] = g_car.TheTopologyCoordinate;
        printf("  pos ");
        pv(&g_car.State.Position);
        printf(" geom ");
        pv(&g_car.State.GeometryPosition);
        printf(" angle %u\n", (unsigned)g_car.State.Angle);
        mat_dump(&g_car.State.BodyMatrix);
        timing_line();
        break;
    case OP_CARVEC: {
        float *f = car_vec(a[0]);
        int i;

        for (i = 0; i < 4; i++)
            f[i] = bitsf(a[1 + i]);
        break;
    }
    case OP_CARF:
        memcpy(car_word(a[0]), &a[1], 4);
        break;
    case OP_AIR: {
        // a[3]: time and height are the one float.
        float t = bitsf(a[1]), h = bitsf(a[2]), r;

        printf("air tc%d time %08x height %08x%s\n", a[0], (unsigned)a[1],
               (unsigned)a[2], a[3] ? " alias" : "");
        g_car.TheTopologyCoordinate = tcs[a[0]];
        r = car_average_air(&g_car, &t, a[3] ? &t : &h);
        tcs[a[0]] = g_car.TheTopologyCoordinate;
        printf("  -> %08x time %08x height %08x\n", (unsigned)fbits(r),
               (unsigned)fbits(t), (unsigned)fbits(a[3] ? t : h));
        timing_line();
        break;
    }
    case OP_BEGIN:
        printf("begin tc%d dt %08x\n", a[0], (unsigned)a[1]);
        g_car.TheTopologyCoordinate = tcs[a[0]];
        car_begin_movement(&g_car, bitsf(a[1]));
        tcs[a[0]] = g_car.TheTopologyCoordinate;
        begin_dump();
        timing_line();
        break;
    case OP_VOT:
        fill(&vecs[a[0]], sizeof vecs[a[0]]);
        get_vector_on_track(&vecs[a[0]], (const bVector2 *)&vecs[a[1]]);
        printf("vot v%d v%d -> ", a[0], a[1]);
        pv(&vecs[a[0]]);
        printf("\n");
        timing_line();
        break;
    case OP_SIB3:
        printf("sib3 tc%d v%d r %08x vel %s\n", a[0], a[1], (unsigned)a[2],
               a[3] < 0 ? "null" : L(&vecs[a[3]]));
        topology_set_interest_bbox3(&tcs[a[0]], &vecs[a[1]], bitsf(a[2]),
                                    a[3] < 0 ? NULL : &vecs[a[3]]);
        break;
    }
}

int main(int argc, char **argv)
{
    FILE *fh;
    long len;
    int32_t nops;
    size_t end;

    if (argc != 2) {
        fprintf(stderr, "usage: track_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    len = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words_in = malloc((size_t)len);
    nwords_in = (size_t)len / 4;
    if (fread(words_in, 4, nwords_in, fh) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);

    // TRACK_TEST_UNBUFFERED: every line out as it is printed, so a crash
    // leaves the op it died in as the transcript's last line.
    if (getenv("TRACK_TEST_UNBUFFERED") != NULL)
        setvbuf(stdout, NULL, _IONBF, 0);

    strs = read_strings(&nstrs);
    nops = next();
    end = rd + (size_t)nops;

    bSlotPoolManagerInit();
    bSetSlotPoolAllocator(arena_alloc, arena_release);
    bSetSlotPoolPrintf(printf_hook);
    bSetTickerSource(tick);
    track_static_init();
    terraintype_static_init();
    g_car.pCarTypeInfo = &g_cti;

    while (rd < end)
        step(next());
    fflush(stdout);
    return 0;
}
