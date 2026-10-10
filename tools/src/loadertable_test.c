// Harness for tools/loadertable_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the labels.
//
//     loadertable_test ops.bin > out.txt
//
// The script describes each buffer as the disc lays it out. This host has
// 8-byte pointers, so a solid list's records do not fit where the disc puts
// them: each one is rebuilt here with the host's struct, and each padded
// child gets the host's own pad before it. What the loader reads of a
// child's size -- the strip data's length less its pad, the texture
// table's size over its entry -- comes out as it would on the disc.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bchunkload.h"
#include "bmath.h"
#include "bslotpool.h"
#include "eframe.h"
#include "emodel.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "epositionmarker.h"
#include "nisinfo.h"
#include "esolid.h"
#include "racefinish.h"
#include "soundscape.h"
#include "sun.h"
#include "texturepack.h"
#include "weatherman.h"

// eview.c is not linked, whose eFrameCounter weatherman.c's query reads,
// nor is realtime.c, whose clocks only texturepack.c's flipbooks and the
// drivetrain and engine under slot 16's loader read, nor eviewmatrix.c,
// whose SunPosition sun.c's loader writes.
bNode SolidList;
bNode ModelList;
int32_t RealTimeFrames;
int32_t WorldTimeFrames;
int32_t WorldTimer;
float WorldTimeElapsed;
bVector3 SunPosition;
uint32_t eFrameCounter;

// Nor are eview.c, eviewmatrix.c and eframe.c for acidsys.c's
// RenderEffects, which slot 6's loader never calls: these fail loudly.
uint8_t *CurrentBufferPos;
uint8_t *CurrentBufferEnd;
int32_t FrameMallocFailed;
uint32_t FrameMallocFailAmount;

eView *eGetView(int32_t id)
{
    fprintf(stderr, "eGetView(%d) called\n", (int)id);
    abort();
    return NULL;
}

float CalculateH(uint16_t fov)
{
    fprintf(stderr, "CalculateH(%u) called\n", (unsigned)fov);
    abort();
    return 0.0f;
}

// Nor is racefinish.c for cameracoord.c's countdown coordinator, which
// slot 13's loader never reaches.
int32_t race_get_countdown_number_to_display(const Race *r)
{
    (void)r;
    fprintf(stderr, "race_get_countdown_number_to_display called\n");
    abort();
    return 0;
}

// Nor are player.c and configitems.c, whose players and
// TunePreRaceSequence the pre-race coordinator reads.
struct Player;
int32_t        PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
int32_t        TunePreRaceSequence;

enum {
    OP_TAG, OP_BUF, OP_LEAF, OP_BULK, OP_OPEN, OP_CLOSE, OP_BUFEND,
    OP_CLAIMS, OP_CLAIM, OP_SWAP, OP_TRAVERSE, OP_LOAD, OP_CALL, OP_FIXUP,
    OP_SET, OP_DUMP, OP_MNEW, OP_MINIT, OP_MUNINIT, OP_MDELETE, OP_MRECON,
    OP_MRTT, OP_MAPPLY, OP_MALL, OP_MPOKE, OP_MDUMP, OP_REPL, OP_RENT,
    OP_FIND, OP_MATRIX, OP_RAMP, OP_RAMPDUMP, OP_SEED, OP_MARK, OP_RELEASE,
    OP_DUP, OP_DELDUP
};

enum {
    K_S, K_SE, K_SD, K_TT, K_TR, K_LF, K_RA, K_LM, K_HD, K_DS, K_DSE, K_DSD,
    NKIND
};
static const char *const KIND[NKIND] = {
    "s", "se", "sd", "tt", "tr", "lf", "ra", "lm", "hd", "ds", "dse", "dsd"
};

#define MAX_BUF     256
#define MAX_TOP     4096
#define MAX_DEPTH   8
#define MAX_MODELS  256
#define MAX_REPL    64
#define MAX_CLAIMS  512
#define MAX_WALK    40000
#define NTI         (1 << 20)
#define NLM         (1 << 18)
#define MAX_RAMPS   64

// The falloff ramp's texture, which eFixUpTables looks up by this hash.
#define RAMP_HASH   0xb9ab56e4u

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

static uint32_t rd32(const uint8_t *p)
{
    uint32_t v;

    memcpy(&v, p, 4);
    return v;
}

// ------------------------------------------------------------- regions

typedef struct {
    const uint8_t *p;
    size_t         size;
    int            kind, idx;       // a record; for a chunk, idx and buf
    int            desz, hesz;      // a table's entry, disc and host
} Region;

typedef struct {
    Region *r;
    int     n, cap, sorted;
} Regions;

static Regions recs, tops;
static uint8_t *solid_by_idx[1 << 16];

static void add_region(Regions *t, Region r)
{
    if (t->n == t->cap) {
        t->cap = t->cap ? 2 * t->cap : 1024;
        t->r = realloc(t->r, sizeof(Region) * (size_t)t->cap);
    }
    t->r[t->n++] = r;
    t->sorted = 0;
}

static int cmp_region(const void *a, const void *b)
{
    const Region *x = a, *y = b;

    return x->p < y->p ? -1 : x->p > y->p;
}

static const Region *find_region(Regions *t, const void *a)
{
    const uint8_t *p = a;
    int lo = 0, hi;

    if (!t->sorted) {
        qsort(t->r, (size_t)t->n, sizeof(Region), cmp_region);
        t->sorted = 1;
    }
    hi = t->n - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;

        if (t->r[mid].p <= p)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    if (hi < 0)
        return NULL;
    if (p < t->r[hi].p + t->r[hi].size
        || (t->r[hi].size == 0 && p == t->r[hi].p))
        return &t->r[hi];
    return NULL;
}

// ------------------------------------------------------------- buffers

typedef struct {
    uint8_t *raw, *p;
    size_t   len;
    int      nchunks;
    uint8_t *chunk[MAX_TOP];
} Buf;

static Buf *bufs[MAX_BUF];
static int  nbufs;
static Buf *cur;

// The buffer being built: host bytes at `stage`, and where the disc would
// have put the same bytes.
static uint8_t *stage;
static size_t   slen, scap;
static uint32_t dlen, misalign;
static struct { size_t hoff; uint32_t doff, type; } stack[MAX_DEPTH];
static int depth;
static size_t top_off[MAX_TOP];
static int    ntop;
static struct { Region r; size_t off; } pend[1 << 16];
static int npend;
static int kind_count[NKIND];

static void grow(size_t n)
{
    if (slen + n > scap) {
        scap = (slen + n) * 2 + 4096;
        stage = realloc(stage, scap);
    }
}

static void put(const void *src, size_t n)
{
    grow(n);
    if (src != NULL)
        memcpy(stage + slen, src, n);
    else
        memset(stage + slen, 0, n);
    slen += n;
}

static void put32(uint32_t v)
{
    put(&v, 4);
}

static size_t hpad_at(size_t off)
{
    return (16u - (misalign + off) % 16u) % 16u;
}

static uint32_t dpad_at(uint32_t off)
{
    return (16u - (misalign + off) % 16u) % 16u;
}

static void pend_region(int kind, size_t off, size_t size, int desz,
                        int hesz)
{
    Region r;

    r.p = NULL;
    r.size = size;
    r.kind = kind;
    r.idx = kind_count[kind]++;
    r.desz = desz;
    r.hesz = hesz;
    pend[npend].r = r;
    pend[npend].off = off;
    npend++;
}

static void begin_chunk(void)
{
    if (depth == 0)
        top_off[ntop++] = slen;
}

// The host's copy of a 192-byte disc eSolid.
static void host_solid(eSolid *s, const uint8_t *d)
{
    memset(s, 0, sizeof *s);
    s->Node.next = (bNode *)(uintptr_t)rd32(d + 0);
    s->Node.prev = (bNode *)(uintptr_t)rd32(d + 4);
    memcpy(&s->NameHash, d + 8, 4);
    memcpy(&s->Version, d + 12, 4);
    memcpy(s->Name, d + 16, 24);
    memcpy(&s->ExternalRigidAnimationNameHash, d + 40, 4);
    s->pVertexAnimator = (void *)(uintptr_t)rd32(d + 44);
    memcpy(&s->Flags, d + 48, 2);
    memcpy(&s->StripFlags, d + 50, 2);
    memcpy(&s->NumStrips, d + 52, 2);
    memcpy(&s->NumPolys, d + 54, 2);
    memcpy(&s->NumVerts, d + 56, 2);
    memcpy(&s->NumOriginalVerts, d + 58, 2);
    memcpy(&s->SizeofStripEntryData, d + 60, 4);
    memcpy(&s->AABBMin, d + 64, 16);
    memcpy(&s->AABBMax, d + 80, 16);
    memcpy(&s->PivotMatrix, d + 96, 64);
    memcpy(&s->AnimationTreeNumNodes, d + 160, 4);
    s->pAnimationTreeNodes = (void *)(uintptr_t)rd32(d + 164);
    s->pRigidAnimation = (uint8_t *)(uintptr_t)rd32(d + 168);
    memcpy(&s->NumTextureTableEntries, d + 172, 2);
    memcpy(&s->NumLightMaterials, d + 174, 2);
    s->StripEntryTable = (void *)(uintptr_t)rd32(d + 176);
    s->StripEntryDataStart = (void *)(uintptr_t)rd32(d + 180);
    s->pTextureTable = (void *)(uintptr_t)rd32(d + 184);
    s->LightMaterialTable = (void *)(uintptr_t)rd32(d + 188);
}

static void host_strip(eStripEntry *e, const uint8_t *d)
{
    memset(e, 0, sizeof *e);
    memcpy(e, d, 8);
    e->Data = (uint8_t *)(uintptr_t)rd32(d + 8);
    memcpy(&e->DataQWordSize, d + 12, 52);
}

static void host_rigid(eRigidAnimation *r, const uint8_t *d)
{
    memset(r, 0, sizeof *r);
    memcpy(r, d, 8);
    r->pLabelledFrames = (uint8_t *)(uintptr_t)rd32(d + 8);
    memcpy(&r->Padding, d + 12, 100);
}

typedef char strip_tail_check[
    (offsetof(eStripEntry, Padding) - offsetof(eStripEntry, DataQWordSize)
     == 51) ? 1 : -1];
typedef char rigid_tail_check[
    (offsetof(eRigidAnimation, Matricies) + 64
     - offsetof(eRigidAnimation, Padding) == 100) ? 1 : -1];

// A leaf of a solid container, rebuilt for the host. `d` is the disc
// payload, `n` its size.
static void solid_child(uint32_t type, const uint8_t *d, uint32_t n)
{
    size_t   hoff = slen, hp = hpad_at(hoff + 8), size;
    uint32_t dp = dpad_at(dlen + 8);
    size_t   k, cnt, rem;

    begin_chunk();
    put32(type);
    put32(0);
    switch (type) {
    case 0x00034003u: {
        eSolid s;

        host_solid(&s, d + dp);
        put(NULL, hp);
        pend_region(K_S, slen, sizeof s, 1, 1);
        put(&s, sizeof s);
        put(NULL, n - dp - 192);
        break;
    }
    case 0x00034004u:
        cnt = (n - dp) / 64;
        rem = (n - dp) % 64;
        put(NULL, hp);
        pend_region(K_SE, slen, cnt * sizeof(eStripEntry), 64,
                    (int)sizeof(eStripEntry));
        for (k = 0; k < cnt; k++) {
            eStripEntry e;

            host_strip(&e, d + dp + 64 * k);
            put(&e, sizeof e);
        }
        put(NULL, rem);
        break;
    case 0x00034006u:
        cnt = n / 8;
        rem = n % 8;
        pend_region(K_TT, slen, cnt * sizeof(eTextureTable), 8,
                    (int)sizeof(eTextureTable));
        for (k = 0; k < cnt; k++) {
            eTextureTable t;

            t.NameHash = rd32(d + 8 * k);
            t.pTextureInfo = (void *)(uintptr_t)rd32(d + 8 * k + 4);
            put(&t, sizeof t);
        }
        put(NULL, rem);
        break;
    case 0x0003401du:
        cnt = (n - dp) / 8;
        rem = (n - dp) % 8;
        put(NULL, hp);
        pend_region(K_LM, slen, cnt * sizeof(eLightMaterialEntry), 8,
                    (int)sizeof(eLightMaterialEntry));
        for (k = 0; k < cnt; k++) {
            eLightMaterialEntry t;

            t.NameHash = rd32(d + dp + 8 * k);
            t.LightMaterial = (void *)(uintptr_t)rd32(d + dp + 8 * k + 4);
            put(&t, sizeof t);
        }
        put(NULL, rem);
        break;
    case 0x00034012u: {
        eRigidAnimation r;

        host_rigid(&r, d + dp);
        put(NULL, hp);
        pend_region(K_RA, slen, sizeof r, 1, 1);
        put(&r, sizeof r);
        put(NULL, n - dp - 112);
        break;
    }
    case 0x00034005u:
    case 0x00034007u:
        put(NULL, hp);
        pend_region(type == 0x00034005u ? K_SD : K_TR, slen, n - dp, 1, 1);
        put(d + dp, n - dp);
        break;
    case 0x00034011u:
        pend_region(K_LF, slen, n, 1, 1);
        put(d, n);
        break;
    default:
        put(d, n);
        break;
    }
    size = slen - hoff - 8;
    memcpy(stage + hoff + 4, &(uint32_t){ (uint32_t)size }, 4);
    dlen += 8 + n;
}

static void leaf(uint32_t type, const uint8_t *d, uint32_t n)
{
    uint32_t parent = depth ? stack[depth - 1].type : 0;

    if (parent == 0x80034002u) {
        solid_child(type, d, n);
        return;
    }
    begin_chunk();
    if (parent == 0x80034000u && type == 0x00034001u)
        pend_region(K_HD, slen + 8, n, 1, 1);
    put32(type);
    put32(n);
    put(d, n);
    dlen += 8 + n;
}

static void buf_begin(uint32_t mis)
{
    slen = 0;
    dlen = 0;
    misalign = mis;
    depth = 0;
    ntop = 0;
    npend = 0;
}

static void buf_end(void)
{
    Buf *b = calloc(1, sizeof *b);
    int  i;

    b->raw = malloc(slen + 64);
    b->p = (uint8_t *)(((uintptr_t)b->raw + 15u) & ~(uintptr_t)15u)
           + misalign;
    memcpy(b->p, stage, slen);
    b->len = slen;
    b->nchunks = ntop;
    for (i = 0; i < ntop; i++) {
        Region r;

        b->chunk[i] = b->p + top_off[i];
        r.p = b->chunk[i];
        r.size = (i + 1 < ntop ? top_off[i + 1] : slen) - top_off[i];
        r.kind = nbufs;
        r.idx = i;
        r.desz = r.hesz = 1;
        add_region(&tops, r);
    }
    for (i = 0; i < npend; i++) {
        Region r = pend[i].r;

        r.p = b->p + pend[i].off;
        add_region(&recs, r);
        if (r.kind == K_S)
            solid_by_idx[r.idx] = (uint8_t *)r.p;
    }
    bufs[nbufs++] = b;
    cur = b;
}

// -------------------------------------------------------------- labels

static uint8_t *models[MAX_MODELS];
static eReplacementTextureTable *repl[MAX_REPL];
static int nrepl_entries[MAX_REPL];
static char ti_arr[NTI], lm_arr[NLM];
static int  nti, nlm;

// OP_RAMP's textures, tx0, tx1, ...; the lookup hands out the last, and
// each one's palette, with its count and the two guard words after it.
static TextureInfo *ramps[MAX_RAMPS];
static uint32_t    *ramp_pal[MAX_RAMPS];
static int32_t      ramp_n[MAX_RAMPS];
static int          nramps;
static TextureInfo *ramp_now;

// eVertexAnimatorSlotPool's blocks, from the allocator hook.
static struct { uint8_t *p; size_t n; } va_blocks[64];
static int nva_blocks;

static int is_va(const void *a)
{
    int i;

    for (i = 0; i < nva_blocks; i++)
        if ((const uint8_t *)a >= va_blocks[i].p
            && (const uint8_t *)a < va_blocks[i].p + va_blocks[i].n)
            return 1;
    return 0;
}

static void label(char *b, size_t n, const void *a);

static void va_label(char *b, size_t n, const eVertexAnimator *va)
{
    char s[64];

    label(s, sizeof s, va->SolidTable[0]);
    snprintf(b, n, "va(%s)", s);
}

static void label(char *b, size_t n, const void *a)
{
    const uint8_t *p = a;
    const Region  *r;
    int i;

    if (a == NULL) {
        snprintf(b, n, "null");
        return;
    }
    if ((r = find_region(&recs, a)) != NULL) {
        size_t off = (size_t)(p - r->p);

        if (off == 0)
            snprintf(b, n, "%s%d", KIND[r->kind], r->idx);
        else
            snprintf(b, n, "%s%d+%zu", KIND[r->kind], r->idx,
                     off / (size_t)r->hesz * (size_t)r->desz
                     + off % (size_t)r->hesz);
        return;
    }
    if ((r = find_region(&tops, a)) != NULL) {
        size_t off = (size_t)(p - r->p);

        if (off == 0)
            snprintf(b, n, "b%d.c%d", r->kind, r->idx);
        else
            snprintf(b, n, "b%d.c%d+%zu", r->kind, r->idx, off);
        return;
    }
    for (i = nbufs - 1; i >= 0; i--) {
        if (p == bufs[i]->p + bufs[i]->len) {
            snprintf(b, n, "b%d.end", i);
            return;
        }
    }
    if (a == &SolidList) {
        snprintf(b, n, "SL");
        return;
    }
    if (a == &ModelList) {
        snprintf(b, n, "ML");
        return;
    }
    for (i = 0; i < WEATHER_NUM_TYPES; i++) {
        if (a == &WeatherRegionLists[i]) {
            snprintf(b, n, "W%d", i);
            return;
        }
    }
    if (a == &WeatherRegionInactiveList) {
        snprintf(b, n, "Wi");
        return;
    }
    for (i = MAX_MODELS - 1; i >= 0; i--) {
        if (models[i] != NULL && a == models[i]) {
            snprintf(b, n, "m%d", i);
            return;
        }
    }
    for (i = MAX_REPL - 1; i >= 0; i--) {
        const uint8_t *t = (const uint8_t *)repl[i];

        if (t != NULL && p >= t
            && p < t + sizeof(eReplacementTextureTable)
                       * (size_t)nrepl_entries[i]) {
            size_t off = (size_t)(p - t);

            if (off == 0)
                snprintf(b, n, "r%d", i);
            else
                snprintf(b, n, "r%d+%zu", i, off);
            return;
        }
    }
    for (i = nramps - 1; i >= 0; i--) {
        if (a == (const void *)ramps[i]) {
            snprintf(b, n, "tx%d", i);
            return;
        }
    }
    if (p >= (const uint8_t *)ti_arr && p < (const uint8_t *)ti_arr + NTI) {
        snprintf(b, n, "ti#%d", (int)(p - (const uint8_t *)ti_arr));
        return;
    }
    if (p >= (const uint8_t *)lm_arr && p < (const uint8_t *)lm_arr + NLM) {
        snprintf(b, n, "lm#%d", (int)(p - (const uint8_t *)lm_arr));
        return;
    }
    if (is_va(a)) {
        va_label(b, n, a);
        return;
    }
    snprintf(b, n, "?");
}

// Labels, eight at a time, for one printf.
static char lab_ring[8][96];
static int  lab_next;

static const char *L(const void *a)
{
    char *b = lab_ring[lab_next];

    lab_next = (lab_next + 1) % 8;
    label(b, 96, a);
    return b;
}

// --------------------------------------------------------------- seams

static int ti_null(uint32_t hash, int use_default)
{
    return hash == 0 || hash % 7u == 3u || (!use_default && hash % 3u == 0u);
}

static void *ti_seam(uint32_t hash, int use_default, int include_unloaded)
{
    void *r = NULL;

    if (hash == RAMP_HASH) {
        r = ramp_now;
    } else if (!ti_null(hash, use_default)) {
        if (nti >= NTI) {
            fprintf(stderr, "ti full\n");
            exit(3);
        }
        r = &ti_arr[nti++];
    }
    printf("  gti %08x %d %d %s\n", (unsigned)hash, use_default,
           include_unloaded, L(r));
    return r;
}

static void *lm_seam(uint32_t hash)
{
    void *r = NULL;

    if (hash % 5u != 2u) {
        if (nlm >= NLM) {
            fprintf(stderr, "lm full\n");
            exit(3);
        }
        r = &lm_arr[nlm++];
    }
    printf("  glm %08x %s\n", (unsigned)hash, L(r));
    return r;
}

static void fixsts_seam(eSolid *s)
{
    printf("  fixsts %s\n", L(s));
}

static void autok_seam(eSolid *s)
{
    printf("  autok %s\n", L(s));
}

static void rcanim_seam(void)
{
    printf("  rcanim\n");
}

static void lightupd_seam(void)
{
    printf("  lightupd\n");
}

static void afxupd_seam(void)
{
    printf("  afxupd\n");
}

static void flailfix_seam(void)
{
    printf("  flailfix\n");
}

static void fern_seam(void)
{
    printf("  fern\n");
}

static int32_t breaks_seen;

// The matrix's record of what an unported slot handed on.
static struct { int set, slot, unload; uint8_t *chunk; } seam_rec;
static int in_matrix;

static void unported_seam(int slot, int unload, uint8_t *chunk)
{
    if (in_matrix) {
        seam_rec.set++;
        seam_rec.slot = slot;
        seam_rec.unload = unload;
        seam_rec.chunk = chunk;
        return;
    }
    printf("  unported %d %d %s\n", slot, unload, L(chunk));
}

static void *pool_alloc(size_t bytes, const char *name, int memoryPool)
{
    uint8_t *p = malloc(bytes);

    (void)memoryPool;
    if (name != NULL && strcmp(name, "eVertexAnimatorSlotPool") == 0
        && nva_blocks < 64) {
        va_blocks[nva_blocks].p = p;
        va_blocks[nva_blocks].n = bytes;
        nva_blocks++;
    }
    return p;
}

static void pool_release(void *p)
{
    (void)p;            // kept, so no address is handed out twice
}

// -------------------------------------------------------------- probes

static struct { int slot; uint32_t type; int32_t ret; } claims[MAX_CLAIMS];
static int nclaims;

static int probe(int k, uint8_t *c)
{
    uint32_t type = bchunk_u32(c);
    int i;

    printf("  try %d %s\n", k, L(c));
    for (i = 0; i < nclaims; i++)
        if (claims[i].slot == k && claims[i].type == type)
            return claims[i].ret;
    return 0;
}

#define PROBE(k) static int probe##k(uint8_t *c) { return probe(k, c); }
PROBE(0) PROBE(1) PROBE(2) PROBE(3) PROBE(4) PROBE(5) PROBE(6) PROBE(7)
PROBE(8) PROBE(9) PROBE(10) PROBE(11) PROBE(12) PROBE(13) PROBE(14)
PROBE(15) PROBE(16) PROBE(17) PROBE(18) PROBE(19) PROBE(20) PROBE(21)
PROBE(22) PROBE(23) PROBE(24) PROBE(25) PROBE(26) PROBE(27) PROBE(28)
PROBE(29) PROBE(30)

// One more than the tables have: the demo's 31, for the walks over probes.
#define NPROBES 31

static BChunkLoader probes[NPROBES] = {
    probe0, probe1, probe2, probe3, probe4, probe5, probe6, probe7,
    probe8, probe9, probe10, probe11, probe12, probe13, probe14, probe15,
    probe16, probe17, probe18, probe19, probe20, probe21, probe22,
    probe23, probe24, probe25, probe26, probe27, probe28, probe29,
    probe30,
};

static BChunkLoader saved_load[BCHUNK_NUM_LOADERS];
static BChunkLoader saved_unload[BCHUNK_NUM_LOADERS];

// The slots whose object is not ported, which hand what they take to
// gUnportedLoaderFn. Retail's numbering.
static int unported_slot(int k)
{
    return !(k == 0 || k == 1 || k == 2 || k == 4 || k == 5 || k == 6
             || k == 8 || k == 9 || k == 11 || k == 13 || k == 14 || k == 16
             || k == 15 || k == 18 || k == 19 || k == 20 || k == 21
             || k == 22 || k == 23 || k == 25 || k == 28);
}

// --------------------------------------------------------------- dumps

static void dump_va(const eVertexAnimator *va)
{
    int i, n = va->NumSolids;

    printf("  %s rate %d n %d:", L(va), (int)va->FrameRate, n);
    if (n > EVERTEXANIMATOR_MAX_SOLIDS)
        n = EVERTEXANIMATOR_MAX_SOLIDS;
    for (i = 0; i < n; i++)
        printf(" %s", L(va->SolidTable[i]));
    printf("\n");
}

static int region_is(const void *a, int kind)
{
    const Region *r = find_region(&recs, a);

    return r != NULL && r->kind == kind && r->p == a;
}

static void dump_solid(const eSolid *s)
{
    char own[96];
    int  i;

    printf("  %s name %08x flags %04x strips %d szdata %u data %s se %s"
           " tt %d:%s lm %d:%s\n",
           L(s), (unsigned)s->NameHash, (unsigned)s->Flags,
           (int)s->NumStrips, (unsigned)s->SizeofStripEntryData,
           L(s->StripEntryDataStart), L(s->StripEntryTable),
           (int)s->NumTextureTableEntries, L(s->pTextureTable),
           (int)s->NumLightMaterials, L(s->LightMaterialTable));
    printf("   tree %d:%s rigid %s va %s ext %08x",
           (int)s->AnimationTreeNumNodes, L(s->pAnimationTreeNodes),
           L(s->pRigidAnimation), L(s->pVertexAnimator),
           (unsigned)s->ExternalRigidAnimationNameHash);
    if (region_is(s->pRigidAnimation, K_RA)) {
        const eRigidAnimation *r = (const void *)s->pRigidAnimation;

        printf(" lf %s trig %d", L(r->pLabelledFrames),
               (int)r->TriggerableFlag);
    }
    printf("\n");
    if (region_is(s->pTextureTable, K_TT)) {
        const eTextureTable *t = s->pTextureTable;

        printf("   tt");
        for (i = 0; i < s->NumTextureTableEntries; i++)
            printf(" %08x=%s", (unsigned)t[i].NameHash,
                   L(t[i].pTextureInfo));
        printf("\n");
    }
    if (region_is(s->LightMaterialTable, K_LM)) {
        const eLightMaterialEntry *t = s->LightMaterialTable;

        printf("   lmt");
        for (i = 0; i < s->NumLightMaterials; i++)
            printf(" %08x=%s", (unsigned)t[i].NameHash,
                   L(t[i].LightMaterial));
        printf("\n");
    }
    if (region_is(s->StripEntryTable, K_SE)
        || region_is(s->StripEntryTable, K_DSE)) {
        const eStripEntry *e = s->StripEntryTable;
        const uint8_t *d = s->StripEntryDataStart;

        label(own, sizeof own, d);
        printf("   sd");
        for (i = 0; i < s->NumStrips; i++) {
            if ((region_is(d, K_SD) || region_is(d, K_DSD)) && e[i].Data >= d
                && e[i].Data < d + s->SizeofStripEntryData)
                printf(" +%x", (unsigned)(e[i].Data - d));
            else
                printf(" %s", L(e[i].Data));
        }
        printf("\n");
    }
}

static void dump_model(const eModel *m)
{
    int i, k, n;

    printf("  %s name %08x solid %s repl %s n %d inst %d start %d"
           " next %s prev %s\n",
           L(m), (unsigned)m->NameHash, L(m->Solid),
           L(m->pReplacementTextureTable), (int)(int8_t)m->NumReplacementTextures,
           (int)(int8_t)m->ReplacementTextureInstanceIndex,
           (int)m->RigidAnimationStartTime, L(m->Node.next),
           L(m->Node.prev));
    n = (int8_t)m->NumReplacementTextures;
    for (i = 0; i < MAX_REPL; i++) {
        if (repl[i] == NULL
            || (void *)repl[i] != m->pReplacementTextureTable)
            continue;
        if (n > nrepl_entries[i])
            n = nrepl_entries[i];
        for (k = 0; k < n; k++) {
            const eReplacementTextureTable *r = &repl[i][k];
            int j;

            printf("   r%d[%d] %08x %08x %s idx", i, k,
                   (unsigned)r->OldNameHash, (unsigned)r->NewNameHash,
                   L(r->pTextureInfo));
            for (j = 0; j < 16; j++)
                printf(" %d", (int)r->ReplaceIndex[j]);
            printf("\n");
        }
        break;
    }
}

static bNode *walk[MAX_WALK];

// A list's nodes by next, then whether prev walks them back.
static int walk_list(bNode *head, const char *name)
{
    bNode *n;
    int    count = 0, i, ok = 1;

    for (n = head->next; n != head && count < MAX_WALK; n = n->next)
        walk[count++] = n;
    printf("  %s %d%s:", name, count, count == MAX_WALK ? "+" : "");
    for (i = 0; i < count; i++)
        printf(" %s", L(walk[i]));
    printf("\n");
    n = head->prev;
    for (i = count - 1; i >= 0; i--, n = n->prev) {
        if (n != walk[i]) {
            ok = 0;
            break;
        }
    }
    if (ok && n != head)
        ok = 0;
    printf("  %s prev %s\n", name, ok ? "ok" : "broken");
    return count;
}

static void dump(void)
{
    const void *seen[64];
    uint32_t    pos[3];
    int nseen = 0, count, i, j;

    printf("  flags dis %d solids %d tex %d anim %d seed %08x\n",
           (int)eDisableFixUpTables, (int)eDirtySolids, (int)eDirtyTextures,
           (int)eDirtyAnimations, (unsigned)bDefaultSeed);
    printf("  ti %s %s %s %s %s %s %s", L(pTextureInfoRVMInfo),
           L(pTextureInfoRVMMask), L(pTextureInfoSolidGrey),
           L(pTextureInfoFilterGrey), L(pTextureInfoShadowMap1),
           L(pTextureInfoRadialBlur), L(pTextureInfoSpecularFalloff));
    printf(" %s %s\n", L(pTextureInfoFalloffRamp),
           L(pTextureInfoCarSelectEnvMap));
    memcpy(pos, &SunPosition, sizeof pos);
    printf("  sun %s pos %08x %08x %08x\n", L(SunInfo), (unsigned)pos[0],
           (unsigned)pos[1], (unsigned)pos[2]);
    printf("  weather");
    for (i = 0; i < WEATHER_NUM_TYPES + 1; i++) {
        const bNode *w = i < WEATHER_NUM_TYPES ? &WeatherRegionLists[i]
                                               : &WeatherRegionInactiveList;

        printf(" %s/%s", L(w->next), L(w->prev));
    }
    printf("\n");
    count = walk_list(&SolidList, "solids");
    for (i = 0; i < count; i++) {
        const eSolid *s = (const eSolid *)(void *)walk[i];

        dump_solid(s);
        if (s->pVertexAnimator != NULL && is_va(s->pVertexAnimator)) {
            for (j = 0; j < nseen; j++)
                if (seen[j] == s->pVertexAnimator)
                    break;
            if (j == nseen && nseen < 64) {
                seen[nseen++] = s->pVertexAnimator;
                dump_va(s->pVertexAnimator);
            }
        }
    }
    count = walk_list(&ModelList, "models");
    for (i = 0; i < count; i++)
        dump_model((const eModel *)(void *)walk[i]);
    printf("  pools va %d model %d\n",
           eVertexAnimatorSlotPool
               ? (int)eVertexAnimatorSlotPool->numAllocatedSlots : -1,
           eModelSlotPool ? (int)eModelSlotPool->numAllocatedSlots : -1);
}

// ----------------------------------------------------------- the copies

static void add_rec(int kind, const void *p, size_t size, int desz, int hesz)
{
    Region r;

    r.p = p;
    r.size = size;
    r.kind = kind;
    r.idx = kind_count[kind]++;
    r.desz = desz;
    r.hesz = hesz;
    add_region(&recs, r);
}

// eduplicate_solid, and its copy named, with its name: whether the strip
// data and the strip table, but each strip's Data, are the first solid of
// the name's, as the copy's own walk finds it. The disc's strip data comes
// as sizes, all 0, so the first solid's is given a pattern first.
static void dup(const char *from, const char *to)
{
    uint32_t h = bchunk_hash(from);
    bNode   *n, *tail = SolidList.prev;
    eSolid  *src = NULL, *s;

    for (n = SolidList.next; n != &SolidList; n = n->next) {
        if (((eSolid *)(void *)n)->NameHash == h) {
            src = (eSolid *)(void *)n;
            break;
        }
    }
    if (src != NULL) {
        uint8_t *d = src->StripEntryDataStart;
        uint32_t k;

        for (k = 0; k < src->SizeofStripEntryData; k++)
            d[k] = (uint8_t)(k * 7 + 3);
    }
    eduplicate_solid(from, to);
    s = (eSolid *)(void *)SolidList.prev;
    printf("  dup %s %s", from, to);
    if (&s->Node != tail && src != NULL) {
        const eStripEntry *se = s->StripEntryTable,
                          *sse = src->StripEntryTable;
        int same, tbl = 1, i;

        add_rec(K_DS, s, sizeof(eSolid), 192, (int)sizeof(eSolid));
        add_rec(K_DSE, se, (size_t)s->NumStrips * sizeof(eStripEntry), 64,
                (int)sizeof(eStripEntry));
        add_rec(K_DSD, s->StripEntryDataStart, s->SizeofStripEntryData, 1,
                1);
        same = memcmp(s->StripEntryDataStart, src->StripEntryDataStart,
                      s->SizeofStripEntryData) == 0;
        for (i = 0; i < s->NumStrips; i++) {
            eStripEntry a = se[i], b = sse[i];

            a.Data = b.Data = NULL;
            if (memcmp(&a, &b, sizeof a) != 0)
                tbl = 0;
        }
        printf(" %s %.24s from %s data %s tbl %s", L(s), s->Name, L(src),
               same ? "same" : "differs", tbl ? "same" : "differs");
    } else if (&s->Node != tail) {
        printf(" %s from none", L(s));
    }
    printf(" mem %d\n", (int)MemoryUsedByDuplicatedSolids);
}

// edelete_all_duplicated_solids, and the copies' names forgotten.
static void deldup(void)
{
    int i, k = 0;

    edelete_all_duplicated_solids();
    for (i = 0; i < recs.n; i++)
        if (recs.r[i].kind != K_DS && recs.r[i].kind != K_DSE
            && recs.r[i].kind != K_DSD)
            recs.r[k++] = recs.r[i];
    recs.n = k;
    printf("  deldup mem %d\n", (int)MemoryUsedByDuplicatedSolids);
}

// ---------------------------------------------------------------- main

static uint8_t *chunk_ptr(int32_t idx)
{
    if (idx == cur->nchunks)
        return cur->p + cur->len;
    return cur->chunk[idx];
}

// One slot on one type. Mode 0 is a bare chunk, the type and zeros; 1 is a
// take without the call; 2 is a header-only solid list; 3 is a chunk of size
// 0 whose payload is 0xa5s, for a ported unloader, which reads no further
// than the header -- a loader in its place reads the sizes and faults; 4
// is a position-marker chunk of one record, linked first for the
// unloader, and the list after the call must hold just it (the loader)
// or nothing (the unloader); 5 is a NIS table chunk of 479 bytes, loaded
// first for the unloader, and the table after the call must be its two
// records (the loader) or empty (the unloader); 6 is a sound-scape chunk
// of one empty reverb area, loaded first for the unloader, and the areas
// after the call must number one (the loader) or none (the unloader).
static void matrix(int table, int slot, uint32_t type, int mode)
{
    static uint8_t raw[512];
    uint8_t *c = (uint8_t *)(((uintptr_t)raw + 15u) & ~(uintptr_t)15u);
    BChunkLoader *t = table ? UnloaderTable : LoaderTable;
    int r;

    if (mode == 1) {
        printf("  m %d %d %08x take\n", table, slot, (unsigned)type);
        return;
    }
    memset(c, mode == 3 ? 0xa5 : 0, 256);
    if (mode == 3) {
        memcpy(c, &type, 4);
        memset(c + 4, 0, 4);
    } else if (mode == 4) {
        uint32_t w[2] = { 0x00034013u, 8 + (uint32_t)sizeof(ePositionMarker) };

        memcpy(c, w, sizeof w);
        if (table)
            (void)loader_position_markers(c);
    } else if (mode == 5) {
        uint32_t w[2] = { NIS_INFO_CHUNK_ID, 479 };

        memcpy(c, w, sizeof w);
        if (table)
            (void)loader_nis_info(c);
    } else if (mode == 6) {
        uint32_t w[4] = { SOUNDSCAPE_CHUNK, 56, SOUNDSCAPE_CHUNK_REVERB, 48 };

        memcpy(c, w, sizeof w);
        if (table)
            (void)loader_sound_scape(c);
    } else if (mode == 2) {
        uint32_t w[4] = { 0x80034000u, 60, 0x00034001u, 52 };

        memcpy(c, w, sizeof w);
        memcpy(c + 16, "matrix", 6);
    } else {
        memcpy(c, &type, 4);
    }
    seam_rec.set = 0;
    in_matrix = 1;
    r = t[slot](c);
    in_matrix = 0;
    printf("  m %d %d %08x %s\n", table, slot, (unsigned)type,
           r ? "take" : "no");
    if (mode == 4) {
        bNode *m = (bNode *)(void *)(c + 16), *h = &PositionMarkerList;
        int ok = table ? h->next == h && h->prev == h
                       : h->next == m && h->prev == m && m->next == h
                         && m->prev == h;

        if (!ok)
            printf("  list wrong\n");
        h->next = h;
        h->prev = h;
    }
    if (mode == 5) {
        int ok = table ? NisInfoTable == NULL && NumNisInfos == 0
                       : NisInfoTable == (NisInfo *)(void *)(c + 8)
                         && NumNisInfos == 2;

        if (!ok)
            printf("  nis wrong\n");
        NisInfoTable = NULL;
        NumNisInfos = 0;
    }
    if (mode == 6) {
        if (SoundScapeNumReverbAreas != (table ? 0 : 1))
            printf("  soundscape wrong\n");
        SoundScapeNumReverbAreas = 0;
    }
    if (unported_slot(slot) && r) {
        if (seam_rec.set != 1 || seam_rec.slot != slot
            || seam_rec.unload != table || seam_rec.chunk != c)
            printf("  seam wrong\n");
    } else if (seam_rec.set) {
        printf("  seam wrong\n");
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
        fprintf(stderr, "usage: loadertable_test ops.bin\n");
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

    SolidList.next = SolidList.prev = &SolidList;
    ModelList.next = ModelList.prev = &ModelList;
    bSetSlotPoolAllocator(pool_alloc, pool_release);
    bSlotPoolManagerInit();
    esolid_init_slot_pool();
    emodel_init_slot_pool();
    gGetTextureInfoFn = ti_seam;
    gElGetLightMaterialFn = lm_seam;
    gFixStripSTsFn = fixsts_seam;
    gCalcAutoKFn = autok_seam;
    gReconnectAllAnimationsFn = rcanim_seam;
    gELightUpdateTexturesFn = lightupd_seam;
    gAfxUpdateTexturesFn = afxupd_seam;
    gFlailerPostLoadFixupFn = flailfix_seam;
    gEmptyFernFlattenersFn = fern_seam;
    gUnportedLoaderFn = unported_seam;
    // LT_UNBUFFERED=1 for a crash's last line.
    if (getenv("LT_UNBUFFERED") != NULL)
        setvbuf(stdout, NULL, _IONBF, 0);
    else
        setvbuf(stdout, NULL, _IOFBF, 1 << 20);

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            // Flushed, so a crash shows the scenario it was in.
            fflush(stdout);
            printf("[%s]\n", tags[next()]);
            break;
        case OP_BUF:
            buf_begin((uint32_t)next());
            break;
        case OP_LEAF: {
            uint32_t type = (uint32_t)next();
            uint32_t n = (uint32_t)next();
            int32_t  nw = next(), k;
            uint8_t *d = malloc((size_t)nw * 4 + 4);

            for (k = 0; k < nw; k++) {
                int32_t w = next();
                memcpy(d + 4 * k, &w, 4);
            }
            leaf(type, d, n);
            free(d);
            break;
        }
        case OP_BULK: {
            uint32_t type = (uint32_t)next();
            uint32_t n = (uint32_t)next();
            uint8_t *d = calloc(1, (size_t)n + 4);

            leaf(type, d, n);
            free(d);
            break;
        }
        case OP_OPEN: {
            uint32_t type = (uint32_t)next();

            begin_chunk();
            stack[depth].hoff = slen;
            stack[depth].doff = dlen;
            stack[depth].type = type;
            depth++;
            put32(type);
            put32(0);
            dlen += 8;
            break;
        }
        case OP_CLOSE: {
            uint32_t n;

            depth--;
            n = (uint32_t)(slen - stack[depth].hoff - 8);
            memcpy(stage + stack[depth].hoff + 4, &n, 4);
            break;
        }
        case OP_BUFEND:
            buf_end();
            break;
        case OP_CLAIMS:
            nclaims = 0;
            break;
        case OP_CLAIM:
            claims[nclaims].slot = next();
            claims[nclaims].type = (uint32_t)next();
            claims[nclaims].ret = next();
            nclaims++;
            break;
        case OP_SWAP:
            if (next()) {
                memcpy(saved_load, LoaderTable, sizeof saved_load);
                memcpy(saved_unload, UnloaderTable, sizeof saved_unload);
                memcpy(LoaderTable, probes, sizeof LoaderTable);
                memcpy(UnloaderTable, probes, sizeof UnloaderTable);
            } else {
                memcpy(LoaderTable, saved_load, sizeof saved_load);
                memcpy(UnloaderTable, saved_unload, sizeof saved_unload);
            }
            break;
        case OP_TRAVERSE: {
            int32_t dir = next(), first = next(), last = next(), num = next();

            if (dir)
                traverse_chunks_backwards(chunk_ptr(first), chunk_ptr(last),
                                          probes, num);
            else
                traverse_chunks(chunk_ptr(first), chunk_ptr(last), probes,
                                num);
            printf("  breaks %d\n", (int)(bchunk_breaks - breaks_seen));
            breaks_seen = bchunk_breaks;
            break;
        }
        case OP_LOAD: {
            int32_t dir = next(), mode = next();
            uint8_t *p = mode == 1 ? NULL : cur->p;
            int32_t  n = mode == 2 ? 0 : (int32_t)cur->len;

            if (dir)
                unload_chunks(p, n);
            else
                load_chunks(p, n);
            printf("  breaks %d\n", (int)(bchunk_breaks - breaks_seen));
            breaks_seen = bchunk_breaks;
            break;
        }
        case OP_CALL: {
            int32_t which = next(), idx = next();
            uint8_t *c = chunk_ptr(idx);
            int r = which ? unloader_solid_list(c) : loader_solid_list(c);

            // The header's InventoryHandle, which the loader fills.
            if (bchunk_u32(c) == 0x80034000u)
                printf("  ret %d inv %08x\n", r, (unsigned)rd32(c + 64));
            else
                printf("  ret %d\n", r);
            break;
        }
        case OP_FIXUP: {
            int32_t which = next();

            if (which == 0)
                efix_up_tables();
            else if (which == 1)
                post_load_fixup();
            else
                hot_chunks_post_load_fixup();
            break;
        }
        case OP_SET: {
            int32_t var = next(), v = next();

            if (var == 0)
                eDisableFixUpTables = v;
            else if (var == 1)
                eDirtySolids = v;
            else if (var == 2)
                eDirtyTextures = v;
            else
                eDirtyAnimations = v;
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_MNEW: {
            int32_t idx = next();

            models[idx] = bSlotOMalloc(eModelSlotPool);
            memset(models[idx], 0xcd, sizeof(eModel));
            break;
        }
        case OP_MINIT: {
            int32_t idx = next();

            emodel_init((eModel *)(void *)models[idx], (uint32_t)next());
            break;
        }
        case OP_MUNINIT:
            emodel_uninit((eModel *)(void *)models[next()]);
            break;
        case OP_MDELETE: {
            int32_t idx = next();

            emodel_delete((eModel *)(void *)models[idx], next());
            break;
        }
        case OP_MRECON:
            emodel_reconnect_solid((eModel *)(void *)models[next()]);
            break;
        case OP_MRTT:
            emodel_reconnect_texture_table((eModel *)(void *)models[next()]);
            break;
        case OP_MAPPLY:
            emodel_apply_replacement_texture_table(
                (eModel *)(void *)models[next()]);
            break;
        case OP_MALL:
            emodel_reconnect_all_models();
            break;
        case OP_MPOKE: {
            eModel *m = (eModel *)(void *)models[next()];
            int32_t field = next(), v = next();

            switch (field) {
            case 0: m->NameHash = (uint32_t)v; break;
            case 1: m->Solid = v < 0 ? NULL : solid_by_idx[v]; break;
            case 2: m->pReplacementTextureTable = v < 0 ? NULL : repl[v];
                    break;
            case 3: m->NumReplacementTextures = (uint8_t)v; break;
            case 4: m->ReplacementTextureInstanceIndex = (uint8_t)v; break;
            default: m->RigidAnimationStartTime = (int16_t)v; break;
            }
            break;
        }
        case OP_MDUMP:
            dump_model((const eModel *)(void *)models[next()]);
            break;
        case OP_REPL: {
            int32_t idx = next(), n = next();

            repl[idx] = calloc((size_t)n, sizeof(eReplacementTextureTable));
            nrepl_entries[idx] = n;
            break;
        }
        case OP_RENT: {
            int32_t idx = next(), k = next(), j;
            eReplacementTextureTable *r = &repl[idx][k];

            r->OldNameHash = (uint32_t)next();
            r->NewNameHash = (uint32_t)next();
            r->pTextureInfo = NULL;
            for (j = 0; j < 4; j++) {
                int32_t w = next();
                memcpy(r->ReplaceIndex + 4 * j, &w, 4);
            }
            break;
        }
        case OP_FIND: {
            uint32_t h = (uint32_t)next();

            printf("  find %08x %s\n", (unsigned)h, L(eFindSolid(h)));
            break;
        }
        case OP_MATRIX: {
            int32_t table = next(), slot = next(), type = next(), mode = next();

            matrix(table, slot, (uint32_t)type, mode);
            break;
        }
        case OP_RAMP: {
            // Mode 0 takes the texture away; 1 is one with a palette of
            // PaletteSize >> 2 words, filled with 0xcd, and two guards
            // after it; 2 is one with no palette.
            int32_t mode = next(), psize = next(), width = next(), k;
            TextureInfo *t;

            if (mode == 0) {
                ramp_now = NULL;
                break;
            }
            t = calloc(1, sizeof(TextureInfo));
            t->Width = (uint16_t)width;
            t->PaletteSize = psize;
            ramp_n[nramps] = psize >> 2 > 0 ? psize >> 2 : 0;
            if (mode == 1) {
                k = ramp_n[nramps] + 2;
                ramp_pal[nramps] = malloc(4 * (size_t)k);
                memset(ramp_pal[nramps], 0xcd, 4 * (size_t)k);
                t->PaletteData = (uint8_t *)ramp_pal[nramps];
            }
            ramps[nramps++] = t;
            ramp_now = t;
            break;
        }
        case OP_RAMPDUMP: {
            int32_t i = next(), k;

            printf("  %s pal", L(ramps[i]));
            if (ramp_pal[i] == NULL) {
                printf(" none\n");
                break;
            }
            for (k = 0; k < ramp_n[i] + 2; k++)
                printf(" %08x", (unsigned)ramp_pal[i][k]);
            printf("\n");
            break;
        }
        case OP_SEED:
            bDefaultSeed = (uint32_t)next();
            break;
        case OP_DUP: {
            const char *from = tags[next()];

            dup(from, tags[next()]);
            break;
        }
        case OP_DELDUP:
            deldup();
            break;
        case OP_MARK:
        case OP_RELEASE:
            // The model's heap, given back after a disc file; this host
            // keeps every buffer, so no address is handed out twice.
            break;
        default:
            fprintf(stderr, "op %d\n", (int)op);
            return 2;
        }
    }
    fflush(stdout);
    return 0;
}
