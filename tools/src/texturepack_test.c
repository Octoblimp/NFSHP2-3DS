// Harness for tools/texturepack_check.py: runs the checker's op script on
// the port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the labels.
//
//     texturepack_test ops.bin > out.txt
//
// The script describes each chunk as the disc lays it out. This host has
// 8-byte pointers, so the records do not fit where the disc puts them:
// each one is rebuilt here with the host's struct. A pack's blob payload
// is put at the disc's address mod 128, which is what the loader rounds,
// by the bytes the table's size has past its last record: the loader only
// divides that size by the record's, so they are free. The header is the
// host's too, 88 bytes to the disc's 84: its pointer is 8 bytes here, and
// its high half 0, so a name that runs on through the pointer reads the
// half the disc does not have. No scenario's does.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "texturepack.h"

// esolid.c and realtime.c are not linked.
int32_t eDirtyTextures;
int32_t RealTimeFrames;
int32_t WorldTimeFrames;

enum {
    OP_TAG, OP_NAME, OP_REC, OP_PACK, OP_ANIM, OP_ENTRY, OP_APACK, OP_RAW,
    OP_LOAD, OP_GTI, OP_GNTI, OP_GLT, OP_ASSIGN, OP_UNASSIGN, OP_ATTACH,
    OP_DESTRUCT, OP_POKE, OP_LTD, OP_RTSET, OP_UPDATE, OP_GTA, OP_DUMP,
    OP_RECS, OP_ANIMS, OP_HDRS, OP_RPOKE, OP_RENAME, OP_SWAP, OP_NAMES,
    OP_CONSTRUCT
};

#define PACK_ID     0xb0300001u
#define ANIM_ID     0xb0300100u

#define PRE         1024        // before each chunk
#define POST        (4096 + 256)
#define SLACK       4096        // a blob's label runs this far past it
#define MARGIN      2           // records a table's label runs before it
#define MAX_CHUNKS  4096
#define MAX_ALLOCS  8192
#define MAX_RECS    4096
#define MAX_RT      16

typedef char host_info_check[
    (offsetof(TextureInfo, pTexturePack) - offsetof(TextureInfo, DebugName)
     == 128) ? 1 : -1];

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

static uint32_t rd32(const uint8_t *p)
{
    uint32_t v;

    memcpy(&v, p, 4);
    return v;
}

static void wr32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, 4);
}

static void *ptr_of(uint32_t w)
{
    return (void *)(uintptr_t)w;
}

// ------------------------------------------------------------- regions

enum { R_PLAIN, R_STRIDE };

typedef struct {
    uintptr_t lo, base;
    size_t    size;
    int       kind, stride, end_ok, alloc;
    char      name[16];
} Region;

static Region *regs;
static int     nregs, capregs, sorted;

static void add_region(const void *base, size_t size, const char *name,
                       int stride, int end_ok, size_t margin, int alloc)
{
    Region r;

    if (nregs == capregs) {
        capregs = capregs ? 2 * capregs : 1024;
        regs = realloc(regs, sizeof(Region) * (size_t)capregs);
    }
    r.base = (uintptr_t)base;
    r.lo = r.base - margin;
    r.size = size;
    r.kind = stride ? R_STRIDE : R_PLAIN;
    r.stride = stride;
    r.end_ok = end_ok;
    r.alloc = alloc;
    snprintf(r.name, sizeof r.name, "%s", name);
    regs[nregs++] = r;
    sorted = 0;
}

static int cmp_region(const void *a, const void *b)
{
    const Region *x = a, *y = b;

    return x->lo < y->lo ? -1 : x->lo > y->lo;
}

static char lbuf[8][64];
static int  lnext;

static const char *label(const void *p)
{
    uintptr_t a = (uintptr_t)p;
    char     *b = lbuf[lnext++ & 7];
    int       lo = 0, hi, i, back;

    if (a == 0)
        return "null";
    if (p == &TexturePackList)
        return "TPL";
    if (p == &TextureAnimPackList)
        return "TAPL";
    if (!sorted) {
        qsort(regs, (size_t)nregs, sizeof(Region), cmp_region);
        sorted = 1;
    }
    hi = nregs - 1;
    while (lo <= hi) {
        int mid = (lo + hi) / 2;

        if (regs[mid].lo <= a)
            lo = mid + 1;
        else
            hi = mid - 1;
    }
    for (i = hi, back = 0; i >= 0 && back < 4; i--, back++) {
        const Region *r = &regs[i];
        long long off = (long long)(a - r->base);

        if (a < r->base + r->size
            || (a == r->base + r->size && r->end_ok)) {
            if (r->kind == R_STRIDE) {
                long long s = r->stride;
                long long idx = off >= 0 ? off / s : -((-off + s - 1) / s);
                long long rem = off - idx * s;

                if (rem == 0)
                    snprintf(b, 64, "%s.%lld", r->name, idx);
                else
                    snprintf(b, 64, "%s.%lld+%lld", r->name, idx, rem);
            } else if (off == 0) {
                snprintf(b, 64, "%s", r->name);
            } else if (r->alloc
                       && off == (long long)offsetof(TexturePack,
                                                     LoadedTextureDataList)) {
                snprintf(b, 64, "%s.ltd", r->name);
            } else {
                snprintf(b, 64, "%s+%lld", r->name, off);
            }
            return b;
        }
    }
    snprintf(b, 64, "x%08x", (uint32_t)a);
    return b;
}

// ------------------------------------------------------------- the heap

static void *allocs[MAX_ALLOCS];
static int   nallocs;

static void *h_malloc(int size, const char *name, int flags, int pool)
{
    uint8_t *p = malloc((size_t)size + 16);
    char     nm[16];

    (void)flags;
    (void)pool;
    memset(p, 0xcd, (size_t)size);
    snprintf(nm, sizeof nm, "a%d", nallocs);
    add_region(p, (size_t)size, nm, 0, 0, 0, 1);
    allocs[nallocs++] = p;
    printf("  malloc %s a%d\n", name, nallocs - 1);
    return p;
}

static void h_free(void *p)
{
    printf("  free %s\n", label(p));
}

static uint8_t *raw_alloc(size_t n)
{
    uint8_t *raw = calloc(1, n + 128);

    return (uint8_t *)(((uintptr_t)raw + 127u) & ~(uintptr_t)127u);
}

// ------------------------------------------------------------- the seams

static TextureInfo rt_infos[MAX_RT];
static uint32_t    rt_hash[MAX_RT];
static int         nrt;

static TextureInfo *rt_seam(uint32_t hash)
{
    TextureInfo *r = NULL;
    int i;

    for (i = 0; i < nrt; i++) {
        if (rt_hash[i] == hash) {
            r = &rt_infos[i];
            break;
        }
    }
    printf("  rt %08x %s\n", hash, label(r));
    return r;
}

static TexturePack *service_pack;
static int32_t      service_n;

static void sqf_seam(void)
{
    service_n--;
    printf("  sqf %d\n", service_n);
    if (service_n <= 0 && service_pack != NULL)
        service_pack->CurrentLoadingTextureData = NULL;
}

// ------------------------------------------------------------- the chunks

enum { C_PACK, C_ANIM, C_RAW };

typedef struct {
    int               kind;
    uint8_t          *c;
    TextureInfo      *t;
    int               n;
    uint8_t          *d;
    TextureAnim      *a;
    int               na;
    TextureAnimEntry *e;
    int               ne;
} Chunk;

static Chunk    chunks[MAX_CHUNKS];
static int      nchunks;
static uint8_t  pname[80];      // the header's name, then its file name
static uint8_t  precs[MAX_RECS][164];
static int      nprecs;
static uint8_t  panims[MAX_RECS][52];
static int      npanims;
static uint8_t  pents[MAX_RECS][16];
static int      npents;

static void host_info(TextureInfo *t, const uint8_t *d)
{
    memset(t, 0, sizeof *t);
    t->Node.next = ptr_of(rd32(d));
    t->Node.prev = ptr_of(rd32(d + 4));
    memcpy(t->DebugName, d + 8, 128);
    t->pTexturePack = ptr_of(rd32(d + 136));
    t->pImageParent = ptr_of(rd32(d + 140));
    t->ImageData = ptr_of(rd32(d + 144));
    t->PaletteData = ptr_of(rd32(d + 148));
    t->pActiveTexture = ptr_of(rd32(d + 152));
    t->pStackedActiveTexture = ptr_of(rd32(d + 156));
    memcpy(&t->PaletteVramAddress, d + 160, 2);
    memcpy(&t->ImageVramAddress, d + 162, 2);
}

static void build_pack(int32_t mis, uint32_t ptr, int32_t extra,
                       uint32_t blob)
{
    Chunk *k = &chunks[nchunks];
    char   nm[16];
    // The chunk's start to its blob's payload, less the table: 116 bytes
    // on the disc, whose header is 84, and 32 more than the host's header
    // here.
    size_t   pre = 32 + sizeof(TexturePackHeader);
    uint32_t tdisc = 164u * (uint32_t)nprecs + (uint32_t)extra;
    uint32_t target = ((uint32_t)mis + 116u + tdisc) & 127u;
    size_t   hsz = sizeof(TextureInfo);
    uint32_t r = (target - (uint32_t)pre - (uint32_t)(nprecs * hsz)) & 127u;
    uint32_t xh = (r == 0 && extra > 0) ? 128u : r;
    uint32_t htsize = (uint32_t)(nprecs * hsz) + xh;
    size_t   total = pre + htsize + blob;
    uint8_t *c = raw_alloc(PRE + total + POST) + PRE;
    TexturePackHeader *h = (TexturePackHeader *)(void *)(c + 16);
    uint8_t *tb = c + 16 + sizeof(TexturePackHeader), *db;
    int i;

    wr32(c, PACK_ID);
    wr32(c + 4, (uint32_t)total - 8);
    wr32(c + 8, 0x30300002u);
    wr32(c + 12, (uint32_t)sizeof(TexturePackHeader));
    memcpy(h->Name, pname, sizeof h->Name);
    memcpy(h->Filename, pname + sizeof h->Name, sizeof h->Filename);
    h->pTexturePack = ptr_of(ptr);
    wr32(tb, 0x30300003u);
    wr32(tb + 4, htsize);
    k->t = (TextureInfo *)(void *)(tb + 8);
    for (i = 0; i < nprecs; i++)
        host_info(&k->t[i], precs[i]);
    memset((uint8_t *)k->t + nprecs * hsz, 0x77, xh);
    db = tb + 8 + htsize;
    wr32(db, 0x30300004u);
    wr32(db + 4, blob);
    k->kind = C_PACK;
    k->c = c;
    k->n = nprecs;
    k->d = db + 8;
    snprintf(nm, sizeof nm, "h%d", nchunks);
    add_region(c + 16, sizeof(TexturePackHeader), nm, 0, 0, 0, 0);
    snprintf(nm, sizeof nm, "t%d", nchunks);
    add_region(k->t, nprecs * hsz, nm, (int)hsz, 1, MARGIN * hsz, 0);
    snprintf(nm, sizeof nm, "d%d", nchunks);
    add_region(k->d, blob + SLACK, nm, 0, 1, 0, 0);
    nchunks++;
    nprecs = 0;
}

static void build_anim(int32_t version, uint32_t ptr, int32_t pad0,
                       int32_t pad1, int32_t aextra, int32_t eextra)
{
    Chunk *k = &chunks[nchunks];
    char   nm[16];
    size_t asz = sizeof(TextureAnim), esz = sizeof(TextureAnimEntry);
    uint32_t xa = (uint32_t)aextra & ~7u;
    uint32_t hasize, hesize;
    size_t   total;
    uint8_t *c, *ab, *eb;
    TextureAnimPackHeader *h;
    int i;

    if (xa == 0 && aextra > 0)
        xa = 8;
    hasize = (uint32_t)(npanims * asz) + xa;
    hesize = (uint32_t)(npents * esz) + (uint32_t)eextra;
    total = 56 + hasize + hesize;
    c = raw_alloc(PRE + total + POST) + PRE;
    h = (TextureAnimPackHeader *)(void *)(c + 16);
    wr32(c, ANIM_ID);
    wr32(c + 4, (uint32_t)total - 8);
    wr32(c + 8, 0x30300101u);
    wr32(c + 12, (uint32_t)sizeof(TextureAnimPackHeader));
    h->Version = version;
    h->pTextureAnimPack = ptr_of(ptr);
    h->pad[0] = pad0;
    h->pad[1] = pad1;
    ab = c + 40;
    wr32(ab, 0x30300102u);
    wr32(ab + 4, hasize);
    k->a = (TextureAnim *)(void *)(ab + 8);
    for (i = 0; i < npanims; i++) {
        const uint8_t *d = panims[i];
        TextureAnim   *a = &k->a[i];

        memcpy(a->Name, d, 24);
        a->NameHash = rd32(d + 24);
        a->NumFrames = (int32_t)rd32(d + 28);
        a->FramesPerSecond = (int32_t)rd32(d + 32);
        a->TimeBase = (int32_t)rd32(d + 36);
        a->TextureAnimTable = ptr_of(rd32(d + 40));
        a->Valid = (int32_t)rd32(d + 44);
        a->CurrentFrame = (int32_t)rd32(d + 48);
    }
    memset((uint8_t *)k->a + npanims * asz, 0x66, xa);
    eb = ab + 8 + hasize;
    wr32(eb, 0x30300103u);
    wr32(eb + 4, hesize);
    k->e = (TextureAnimEntry *)(void *)(eb + 8);
    for (i = 0; i < npents; i++) {
        const uint8_t    *d = pents[i];
        TextureAnimEntry *e = &k->e[i];

        e->NameHash = rd32(d);
        e->pTextureInfo = ptr_of(rd32(d + 4));
        e->OriginalImageData = ptr_of(rd32(d + 8));
        e->OriginalPaletteData = ptr_of(rd32(d + 12));
    }
    memset((uint8_t *)k->e + npents * esz, 0x55, (size_t)eextra);
    k->kind = C_ANIM;
    k->c = c;
    k->na = npanims;
    k->ne = npents;
    snprintf(nm, sizeof nm, "h%d", nchunks);
    add_region(c + 16, sizeof(TextureAnimPackHeader), nm, 0, 0, 0, 0);
    snprintf(nm, sizeof nm, "A%d", nchunks);
    add_region(k->a, npanims * asz, nm, (int)asz, 1, 0, 0);
    snprintf(nm, sizeof nm, "E%d", nchunks);
    add_region(k->e, npents * esz, nm, (int)esz, 1, 0, 0);
    nchunks++;
    npanims = 0;
    npents = 0;
}

static void build_raw(uint32_t type, int32_t size)
{
    Chunk   *k = &chunks[nchunks++];
    uint8_t *c = raw_alloc(PRE + 8 + (size_t)size + POST) + PRE;

    wr32(c, type);
    wr32(c + 4, (uint32_t)size);
    memset(c + 8, 0xa5, (size_t)size);
    k->kind = C_RAW;
    k->c = c;
}

// ------------------------------------------------------------- the dumps

// All n bytes, past any NUL: what the copies left after it shows too.
static void hexbytes(char *b, const void *s, int n)
{
    int i;

    for (i = 0; i < n; i++)
        sprintf(b + 2 * i, "%02x", ((const unsigned char *)s)[i]);
    b[2 * n] = 0;
}

static void dump(void)
{
    bNode *n;
    int    count;

    printf("  packs");
    for (n = TexturePackList.next, count = 0;
         n != &TexturePackList && count < 10000; n = n->next, count++)
        printf(" %s", label(n));
    printf(" tail %s\n", label(TexturePackList.prev));
    for (n = TexturePackList.next, count = 0;
         n != &TexturePackList && count < 10000; n = n->next, count++) {
        TexturePack *p = (TexturePack *)(void *)n;
        bNode *m;
        char   name[2 * sizeof p->Name + 1];
        char   file[2 * sizeof p->Filename + 1];
        int    any = 0, c2;

        hexbytes(name, p->Name, (int)sizeof p->Name);
        hexbytes(file, p->Filename, (int)sizeof p->Filename);
        printf("  pack %s prev %s name %s file %s hash %08x inv %08x "
               "info %s num %d free %d pos %d cur %s nyl %d pool %d ltd",
               label(p), label(p->Node.prev), name, file, p->NameHash,
               (uint32_t)p->InventoryHandle, label(p->pTextureInfo),
               p->NumTextures, p->pTextureInfoNeedsToBeFreed,
               p->TextureDataFilePos, label(p->CurrentLoadingTextureData),
               p->NumNotYetLoadedTextureDatas, p->MemoryPool);
        for (m = p->LoadedTextureDataList.next, c2 = 0;
             m != &p->LoadedTextureDataList && c2 < 10000;
             m = m->next, c2++) {
            printf(" %s", label(m));
            any = 1;
        }
        printf("%s\n", any ? "" : " -");
    }
    printf("  apacks");
    for (n = TextureAnimPackList.next, count = 0;
         n != &TextureAnimPackList && count < 10000; n = n->next, count++)
        printf(" %s", label(n));
    printf(" tail %s\n", label(TextureAnimPackList.prev));
    for (n = TextureAnimPackList.next, count = 0;
         n != &TextureAnimPackList && count < 10000; n = n->next, count++) {
        TextureAnimPack *p = (TextureAnimPack *)(void *)n;

        printf("  apack %s prev %s anims %s ents %s na %d ne %d\n",
               label(p), label(p->Node.prev), label(p->TextureAnimTable),
               label(p->TextureAnimEntryTable), p->NumTextureAnims,
               p->NumTextureAnimEntries);
    }
    printf("  dirty %d breaks %d\n", eDirtyTextures, texturepack_breaks);
    eDirtyTextures = 0;
}

static void dump_recs(int k)
{
    Chunk *c = &chunks[k];
    int    i;

    for (i = 0; i < c->n; i++) {
        TextureInfo *t = &c->t[i];

        printf("  t%d.%d %08x %s %s used %d pack %s parent %s img %s "
               "pal %s act %s stk %s vram %d %d\n",
               k, i, t->NameHash, label(t->Node.next), label(t->Node.prev),
               t->UsedFlag, label(t->pTexturePack), label(t->pImageParent),
               label(t->ImageData), label(t->PaletteData),
               label(t->pActiveTexture), label(t->pStackedActiveTexture),
               t->PaletteVramAddress, t->ImageVramAddress);
    }
}

static void dump_anims(int k)
{
    Chunk *c = &chunks[k];
    int    i;

    for (i = 0; i < c->na; i++) {
        TextureAnim *a = &c->a[i];

        printf("  A%d.%d %08x nf %d fps %d tb %d tab %s valid %d cur %d\n",
               k, i, a->NameHash, a->NumFrames, a->FramesPerSecond,
               a->TimeBase, label(a->TextureAnimTable), a->Valid,
               a->CurrentFrame);
    }
    for (i = 0; i < c->ne; i++) {
        TextureAnimEntry *e = &c->e[i];

        printf("  E%d.%d %08x ti %s img %s pal %s\n", k, i, e->NameHash,
               label(e->pTextureInfo), label(e->OriginalImageData),
               label(e->OriginalPaletteData));
    }
}

static void dump_hdrs(void)
{
    int k;

    for (k = 0; k < nchunks; k++) {
        Chunk *c = &chunks[k];

        if (c->kind == C_PACK) {
            TexturePackHeader *h = (TexturePackHeader *)(void *)(c->c + 16);

            printf("  h%d %s\n", k, label(h->pTexturePack));
        } else if (c->kind == C_ANIM) {
            TextureAnimPackHeader *h =
                (TextureAnimPackHeader *)(void *)(c->c + 16);

            printf("  h%d v%d %s %08x %08x\n", k, h->Version,
                   label(h->pTextureAnimPack), (uint32_t)h->pad[0],
                   (uint32_t)h->pad[1]);
        }
    }
}

// Each record's name and hash, all 24 bytes of the name; k < 0 for the
// render targets'.
static void dump_names(int k)
{
    TextureInfo *t = k < 0 ? rt_infos : chunks[k].t;
    int          n = k < 0 ? nrt : chunks[k].n;
    char         b[2 * sizeof t->DebugName + 1];
    int          i;

    for (i = 0; i < n; i++) {
        hexbytes(b, t[i].DebugName, (int)sizeof t[i].DebugName);
        if (k < 0)
            printf("  rt.%d %08x %s\n", i, t[i].NameHash, b);
        else
            printf("  n%d.%d %08x %s\n", k, i, t[i].NameHash, b);
    }
}

// ------------------------------------------------------------- the run

static int nltds, nbufs;

int main(int argc, char **argv)
{
    FILE    *fh;
    long     size;
    int32_t  ntags, i;
    char   **tags;
    size_t   end;

    if (argc < 2) {
        fprintf(stderr, "usage: texturepack_test ops.bin\n");
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

    ntags = next();
    tags = malloc(sizeof(char *) * (size_t)(ntags > 0 ? ntags : 1));
    for (i = 0; i < ntags; i++) {
        int32_t len = next(), k;

        tags[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            tags[i][k] = (char)next();
        tags[i][len] = 0;
    }
    end = (size_t)next();
    end += rd;

    bSetMemoryHooks(h_malloc, h_free);
    gERenderTargetTextureInfoFn = rt_seam;
    gServiceQueuedFilesFn = sqf_seam;
    add_region(rt_infos, sizeof rt_infos, "rt", (int)sizeof(TextureInfo),
               0, 0, 0);
    if (getenv("TP_UNBUFFERED") != NULL)
        setvbuf(stdout, NULL, _IONBF, 0);
    else
        setvbuf(stdout, NULL, _IOFBF, 1 << 20);

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            fflush(stdout);
            printf("[%s]\n", tags[next()]);
            break;
        case OP_NAME:
            for (i = 0; i < 20; i++)
                wr32(pname + 4 * i, (uint32_t)next());
            break;
        case OP_REC:
            for (i = 0; i < 41; i++)
                wr32(precs[nprecs] + 4 * i, (uint32_t)next());
            nprecs++;
            break;
        case OP_PACK: {
            int32_t mis = next();
            uint32_t ptr = (uint32_t)next();
            int32_t extra = next();
            uint32_t blob = (uint32_t)next();

            build_pack(mis, ptr, extra, blob);
            break;
        }
        case OP_ANIM:
            for (i = 0; i < 13; i++)
                wr32(panims[npanims] + 4 * i, (uint32_t)next());
            npanims++;
            break;
        case OP_ENTRY:
            for (i = 0; i < 4; i++)
                wr32(pents[npents] + 4 * i, (uint32_t)next());
            npents++;
            break;
        case OP_APACK: {
            int32_t version = next();
            uint32_t ptr = (uint32_t)next();
            int32_t pad0 = next(), pad1 = next();
            int32_t aextra = next(), eextra = next();

            build_anim(version, ptr, pad0, pad1, aextra, eextra);
            break;
        }
        case OP_RAW: {
            uint32_t type = (uint32_t)next();
            int32_t sz = next();

            build_raw(type, sz);
            break;
        }
        case OP_LOAD: {
            int32_t k = next(), unload = next();
            int r = unload ? unloader_texture_pack(chunks[k].c)
                           : loader_texture_pack(chunks[k].c);

            printf("  %s c%d ret %d\n", unload ? "unload" : "load", k, r);
            break;
        }
        case OP_GTI: {
            uint32_t h = (uint32_t)next();
            int32_t d = next(), u = next();
            TextureInfo *r = GetTextureInfo(h, d, u);

            printf("  gti %08x %d %d %s\n", h, d, u, label(r));
            break;
        }
        case OP_GNTI: {
            int32_t n = next();
            TextureInfo *r = GetNthTextureInfo(n);

            printf("  gnti %d %s\n", n, label(r));
            break;
        }
        case OP_GLT: {
            int32_t kind = next(), k = next();
            uint32_t arg = (uint32_t)next();
            TexturePack *p = allocs[k];
            TextureInfo *r;
            static const char *const nm[3] = { "glt", "gt", "gnt" };

            if (kind == 0)
                r = texturepack_get_loaded_texture(p, arg);
            else if (kind == 1)
                r = texturepack_get_texture(p, arg);
            else
                r = texturepack_get_nth_texture(p, (int32_t)arg);
            printf("  %s a%d %08x %s\n", nm[kind], k, arg, label(r));
            break;
        }
        case OP_ASSIGN: {
            int32_t k = next(), c = next(), off = next();
            int32_t pos = next(), sz = next();

            texturepack_assign_texture_data(allocs[k], chunks[c].d + off,
                                            pos, sz);
            break;
        }
        case OP_UNASSIGN: {
            int32_t k = next(), pos = next(), sz = next();

            texturepack_unassign_texture_data(allocs[k], pos, sz);
            break;
        }
        case OP_ATTACH: {
            int32_t k = next(), c = next(), num = next();

            texturepack_attach_texture_table(allocs[k], chunks[c].t, num);
            break;
        }
        case OP_DESTRUCT: {
            int32_t k = next(), flags = next();

            service_pack = allocs[k];
            texturepack_destruct(allocs[k], flags);
            printf("  destruct a%d %d info %s\n", k, flags,
                   label(((TexturePack *)allocs[k])->pTextureInfo));
            break;
        }
        case OP_POKE: {
            int32_t k = next(), field = next(), v = next();
            TexturePack *p = allocs[k];

            if (field == 0) {
                p->pTextureInfoNeedsToBeFreed = v;
            } else {
                p->CurrentLoadingTextureData = v ? ptr_of(0x1234) : NULL;
                service_pack = p;
                service_n = v;
            }
            break;
        }
        case OP_LTD: {
            int32_t k = next(), withbuf = next();
            TexturePack *p = allocs[k];
            LoadedTextureData *d = calloc(1, sizeof *d);
            bNode *head = &p->LoadedTextureDataList, *last = head->prev;
            char nm[16];

            snprintf(nm, sizeof nm, "L%d", nltds++);
            add_region(d, sizeof *d, nm, 0, 0, 0, 0);
            if (withbuf) {
                uint8_t *b = calloc(1, 16);

                snprintf(nm, sizeof nm, "B%d", nbufs++);
                add_region(b, 16, nm, 0, 0, 0, 0);
                d->Buf = b;
            }
            last->next = &d->Node;
            head->prev = &d->Node;
            d->Node.prev = last;
            d->Node.next = head;
            break;
        }
        case OP_RTSET:
            rt_hash[nrt++] = (uint32_t)next();
            break;
        case OP_UPDATE: {
            int32_t w = next(), r = next(), t = next();

            WorldTimeFrames = w;
            RealTimeFrames = r;
            TweakFPS = t;
            UpdateTextureAnimations();
            printf("  update %d %d %d\n", w, r, t);
            break;
        }
        case OP_GTA: {
            uint32_t h = (uint32_t)next();

            printf("  gta %08x %s\n", h, label(GetTextureAnim(h)));
            break;
        }
        case OP_DUMP:
            dump();
            break;
        case OP_RECS:
            dump_recs(next());
            break;
        case OP_ANIMS:
            dump_anims(next());
            break;
        case OP_HDRS:
            dump_hdrs();
            break;
        case OP_RPOKE: {
            int32_t c = next(), idx = next(), field = next(), v = next();

            if (field == 0)
                chunks[c].t[idx].ImageSize = v;
            else
                chunks[c].t[idx].PaletteSize = v;
            break;
        }
        case OP_RENAME: {
            uint32_t h = (uint32_t)next();
            uint8_t  nm[24];

            for (i = 0; i < 6; i++)
                wr32(nm + 4 * i, (uint32_t)next());
            printf("  rename %08x ret %d\n", h,
                   RenameTextureInfo(h, (const char *)nm));
            break;
        }
        case OP_SWAP: {
            uint32_t a = (uint32_t)next(), b = (uint32_t)next();

            printf("  swap %08x %08x ret %d\n", a, b,
                   SwapTextureInfoNames(a, b));
            break;
        }
        case OP_NAMES:
            dump_names(next());
            break;
        case OP_CONSTRUCT: {
            uint8_t      nm[64];
            TexturePack *p;

            for (i = 0; i < 16; i++)
                wr32(nm + 4 * i, (uint32_t)next());
            p = h_malloc((int)sizeof(TexturePack), "TexturePack", 0, 16);
            texturepack_construct(p, (const char *)nm, NULL);
            printf("  construct %s\n", label(p));
            break;
        }
        default:
            fprintf(stderr, "op %d\n", op);
            return 2;
        }
    }
    MaybePrintUnusedTextures();
    fflush(stdout);
    return 0;
}
