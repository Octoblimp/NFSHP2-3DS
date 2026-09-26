// scenery_test -- the harness tools/scenery_check.py runs against the first
// part of Scenery.obj's port, 3DS Files/source/scenery.c.
//
// It reads a script of hex words from argv[1], one op and its operands at a
// time (the checker has the list), and prints what the model prints. No
// address is printed. S and Z are the two lists' heads, #n is the nth model
// bOMalloc handed out, zs is the scratch zone, and a pointer into chunk k is
// named by the child j it falls in: hk.j for a header, ik.j[i] for the ith
// kind, nk.j[i] for the ith object, tk.j[i] for the ith tree node, zk[i]
// for the ith visible zone, and ck.j+off for anywhere else in a child. A
// value that is none of those is printed as its low 32 bits after a ?.
//
// A chunk comes in as the disc's bytes and the misalignment mod 16 the
// model loads it at. The header and the kinds hold pointers, so the host's
// are wider: a container is rebuilt here with those records widened, each
// child chunk at the misalignment the image sees it at (so the pad before
// a header or the objects is the image's), and each child's size given the
// slack that keeps the next one there. The objects and the tree hold no
// pointer and are copied as they are. A zone chunk is widened likewise;
// nothing in it depends on where it lies, so it is put where the host's
// pointers are aligned.
//
// eModel::Init and the model's deleting destructor are the seams, and
// bSlotOMalloc and bFree are defined here: each is printed as the model
// prints its stub.

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "bslotpool.h"
#include "emath.h"
#include "race.h"
#include "scenery.h"

enum {
    OP_TAG = 1, OP_SINIT, OP_SCLOSE, OP_LIST, OP_TABLE, OP_CHUNK, OP_LOAD,
    OP_UNLOAD, OP_DIR, OP_FIND_INFO, OP_FIND_INST_HASH, OP_FIND_INST,
    OP_PIP, OP_FIND_ZONE, OP_ZSET, OP_ZINDEX, OP_ZFREE, OP_INIT_VZ,
    OP_CLOSE_VZ, OP_BLINK, OP_SETZONE, OP_GETZONE, OP_TSET, OP_IS,
    OP_TOGGLE, OP_FACADE, OP_DUMP_INST, OP_FLIP,
};

#define NCHUNK  256
#define NCHILD  8
#define NMODEL  8192
#define NPOLY   64
#define TGUARD  16              // table slots either side of the table
#define TSIZE   64

// The disc's record sizes.
#define DISC_HEADER 56u
#define DISC_INFO   40u
#define DISC_ZONE   288u

static FILE *script;

typedef struct Child {
    uint32_t id, size;          // the disc's
    uint8_t *c;                 // the host child
    uint8_t *base;              // its records
    size_t   rs;                // the host's record size
    long     nrec;
    char     letter;
    uint32_t hsize;             // the host child's size
} Child;

typedef struct Chunk {
    uint8_t *mem;
    uint8_t *chunk;
    uint32_t id, size;          // the disc's
    int      zones;             // a 0x34106 chunk
    long     nzones;
    int      nchild;
    Child    child[NCHILD];
} Chunk;

static Chunk chunks[NCHUNK];

static eModel *models[NMODEL];
static int     nmodels;

static VisibleZone zscratch;
static int16_t     tbuf[TGUARD + TSIZE + TGUARD];
static bVector2    poly[NPOLY];

// eModelSlotPool is only compared, never used as a pool.
static int pool_sentinel;

// ---------------------------------------------------------------- output

static uint32_t crc32_update(uint32_t c, const void *p, size_t n)
{
    const uint8_t *s = (const uint8_t *)p;
    size_t i;
    int k;

    c = ~c;
    for (i = 0; i < n; i++) {
        c ^= s[i];
        for (k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1u)));
    }
    return ~c;
}

static void out(const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
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

// Bits, with every NaN as the one quiet NaN.
static uint32_t fx(float f)
{
    uint32_t b = fb(f);

    if ((b & 0x7f800000u) == 0x7f800000u && (b & 0x007fffffu))
        return 0x7fc00000u;
    return b;
}

static uint32_t rd32(const uint8_t *p)
{
    uint32_t v;

    memcpy(&v, p, 4);
    return v;
}

static int16_t rd16(const uint8_t *p)
{
    int16_t v;

    memcpy(&v, p, 2);
    return v;
}

static void *ptr_of(uint32_t v)
{
    return (void *)(uintptr_t)v;
}

// ---------------------------------------------------------------- naming

static const char *name_of(const void *vp)
{
    static char buf[8][64];
    static int slot;
    char *b = buf[slot++ & 7];
    const uint8_t *p = (const uint8_t *)vp;
    int k, j, i;

    if (p == NULL)
        return "null";
    if (p == (const uint8_t *)&ScenerySectionHeaderList)
        return "S";
    if (p == (const uint8_t *)&VisibleZoneList)
        return "Z";
    if (p == (const uint8_t *)&zscratch)
        return "zs";
    for (i = 0; i < nmodels; i++)
        if (p == (const uint8_t *)models[i]) {
            snprintf(b, 64, "#%d", i);
            return b;
        }
    for (k = 0; k < NCHUNK; k++) {
        Chunk *ck = &chunks[k];

        if (ck->mem == NULL)
            continue;
        if (ck->zones) {
            const uint8_t *base = ck->chunk + 8;
            long nr = ck->nzones > 0 ? ck->nzones : 0;

            if (p >= base && p <= base + nr * (long)sizeof(VisibleZone)) {
                long off = (long)(p - base);
                long idx = off / (long)sizeof(VisibleZone);
                long r = off % (long)sizeof(VisibleZone);

                if (r)
                    snprintf(b, 64, "z%d[%ld]+%ld", k, idx, r);
                else
                    snprintf(b, 64, "z%d[%ld]", k, idx);
                return b;
            }
            continue;
        }
        for (j = 0; j < ck->nchild; j++) {
            Child *ch = &ck->child[j];
            long nr = ch->nrec > 0 ? ch->nrec : 0;

            if (ch->letter == 'c')
                continue;
            if (p >= ch->base && p <= ch->base + nr * (long)ch->rs) {
                long off = (long)(p - ch->base);
                long idx = off / (long)ch->rs;
                long r = off % (long)ch->rs;

                if (ch->letter == 'h' && idx == 0 && r == 0)
                    snprintf(b, 64, "h%d.%d", k, j);
                else if (r)
                    snprintf(b, 64, "%c%d.%d[%ld]+%ld", ch->letter, k, j,
                             idx, r);
                else
                    snprintf(b, 64, "%c%d.%d[%ld]", ch->letter, k, j, idx);
                return b;
            }
        }
        for (j = 0; j < ck->nchild; j++) {
            Child *ch = &ck->child[j];

            if (p >= ch->c && p < ch->c + 8 + ch->hsize) {
                snprintf(b, 64, "c%d.%d%+ld", k, j, (long)(p - (ch->c + 8)));
                return b;
            }
        }
    }
    snprintf(b, 64, "?%08x", (uint32_t)(uintptr_t)p);
    return b;
}

// ---------------------------------------------------------------- stubs

void *bSlotOMalloc(BSlotPool *pool)
{
    eModel *m;

    if (nmodels >= NMODEL) {
        fprintf(stderr, "too many models\n");
        exit(2);
    }
    m = malloc(sizeof *m);
    if (m == NULL)
        exit(2);
    memset(m, 0xa5, sizeof *m);
    models[nmodels] = m;
    if (pool == (BSlotPool *)(void *)&pool_sentinel)
        out("  omalloc #%d pool\n", nmodels);
    else
        out("  omalloc #%d pool %s\n", nmodels, name_of(pool));
    nmodels++;
    return m;
}

void bFree(void *p)
{
    out("  free %s\n", name_of(p));
}

static void f_init(eModel *m, uint32_t name_hash)
{
    out("  init %s hash %08x name %08x solid %08x\n", name_of(m), name_hash,
        m->NameHash, (uint32_t)(uintptr_t)m->Solid);
}

static void f_destroy(eModel *m, int32_t flags)
{
    out("  ~model %s %d\n", name_of(m), (int)flags);
}

// ---------------------------------------------------------------- chunks

static uint32_t align16(uint32_t a)
{
    return (a + 15u) & ~15u;
}

static void widen_header(ScenerySectionHeader *h, const uint8_t *s)
{
    h->Node.next = ptr_of(rd32(s + 0));
    h->Node.prev = ptr_of(rd32(s + 4));
    h->SectionNumber = (int32_t)rd32(s + 8);
    h->NumPolygonsInMemory = (int32_t)rd32(s + 12);
    h->NumPolygonsInWorld = (int32_t)rd32(s + 16);
    h->pSceneryInfo = ptr_of(rd32(s + 20));
    h->NumSceneryInfo = (int32_t)rd32(s + 24);
    h->pSceneryInstance = ptr_of(rd32(s + 28));
    h->NumSceneryInstances = (int32_t)rd32(s + 32);
    h->SceneryTreeNodeTable = ptr_of(rd32(s + 36));
    h->NumSceneryTreeNodes = (int32_t)rd32(s + 40);
    h->SceneryTreeGroupNodeTable = ptr_of(rd32(s + 44));
    h->NumSceneryTreeGroupNodes = (int32_t)rd32(s + 48);
    h->ViewsVisibleThisFrame = rd32(s + 52);
}

static void widen_info(SceneryInfo *f, const uint8_t *s)
{
    int k;

    for (k = 0; k < 3; k++) {
        f->NameHash[k] = rd32(s + 4 * k);
        f->FarClipSize[k] = rd16(s + 12 + 2 * k);
        f->pModel[k] = ptr_of(rd32(s + 20 + 4 * k));
        f->IsFacadeFlag[k] = s[32 + k];
    }
    f->Dummy = rd16(s + 18);
    f->Dummy2 = s[35];
    f->Radius = as_float(rd32(s + 36));
}

static void widen_zone(VisibleZone *z, const uint8_t *s)
{
    int k;

    z->Node.next = ptr_of(rd32(s + 0));
    z->Node.prev = ptr_of(rd32(s + 4));
    z->ZoneNumber = (int32_t)rd32(s + 8);
    z->Center.x = as_float(rd32(s + 12));
    z->Center.y = as_float(rd32(s + 16));
    z->pCaffeineObj = ptr_of(rd32(s + 20));
    z->NumVisibleScenerySections = (int32_t)rd32(s + 24);
    for (k = 0; k < VISIBLE_ZONE_MAX_SECTIONS; k++)
        z->VisibleScenerySections[k] = rd16(s + 28 + 2 * k);
    z->NumPerimeterPoints = (int32_t)rd32(s + 156);
    for (k = 0; k < VISIBLE_ZONE_MAX_POINTS; k++) {
        z->PerimeterPoints[k].x = as_float(rd32(s + 160 + 8 * k));
        z->PerimeterPoints[k].y = as_float(rd32(s + 164 + 8 * k));
    }
}

static void load_container(Chunk *ck, int k, const uint8_t *d, uint32_t n,
                           uint32_t mis)
{
    uint32_t o, end = 8 + ck->size;
    size_t cap = (size_t)n * 2 + 4096;
    uint8_t *base, *c;

    if (end > n) {
        fprintf(stderr, "chunk %d is short\n", k);
        exit(2);
    }
    ck->mem = calloc(1, cap);
    base = (uint8_t *)(((uintptr_t)ck->mem + 15) & ~(uintptr_t)15);
    ck->chunk = base + mis;
    memcpy(ck->chunk, d, 4);
    c = ck->chunk + 8;
    for (o = 8; o < end;) {
        uint32_t cid = rd32(d + o), csize = rd32(d + o + 4);
        uint32_t da = mis + o;
        uint32_t pad = 0, host;
        Child *ch;

        if (o + 8 + csize > end) {
            fprintf(stderr, "chunk %d: child past the end\n", k);
            exit(2);
        }
        if (ck->nchild >= NCHILD) {
            fprintf(stderr, "chunk %d: too many children\n", k);
            exit(2);
        }
        ch = &ck->child[ck->nchild++];
        ch->id = cid;
        ch->size = csize;
        ch->c = c;
        if (cid == SCENERY_HEADER_ID || cid == SCENERY_INSTANCE_ID)
            pad = align16(da + 8) - (da + 8);
        if ((size_t)(c - ck->mem) + 8 + pad + (size_t)csize * 2 + 256 > cap) {
            fprintf(stderr, "chunk %d: no room\n", k);
            exit(2);
        }
        ch->base = c + 8 + pad;
        if (cid == SCENERY_HEADER_ID) {
            if (csize < pad + DISC_HEADER) {
                fprintf(stderr, "chunk %d: short header\n", k);
                exit(2);
            }
            ch->letter = 'h';
            ch->rs = sizeof(ScenerySectionHeader);
            ch->nrec = 1;
            widen_header((ScenerySectionHeader *)(void *)ch->base,
                         d + o + 8 + pad);
            host = pad + (uint32_t)sizeof(ScenerySectionHeader);
        } else if (cid == SCENERY_INFO_ID) {
            long r;

            ch->letter = 'i';
            ch->rs = sizeof(SceneryInfo);
            ch->nrec = (long)(csize / DISC_INFO);
            if ((uintptr_t)ch->base & 7u) {
                fprintf(stderr, "chunk %d: kinds at a 4-byte residue; keep "
                        "the script's info chunks 8-aligned\n", k);
                exit(2);
            }
            for (r = 0; r < ch->nrec; r++)
                widen_info((SceneryInfo *)(void *)ch->base + r,
                           d + o + 8 + (uint32_t)r * DISC_INFO);
            host = (uint32_t)ch->nrec * (uint32_t)sizeof(SceneryInfo);
        } else {
            // The objects, the tree and anything else: the same bytes.
            if (cid == SCENERY_INSTANCE_ID) {
                ch->letter = 'n';
                ch->rs = sizeof(SceneryInstance);
                ch->nrec = ((long)csize - (long)pad) / (long)ch->rs;
            } else if (cid == SCENERY_TREE_ID) {
                ch->letter = 't';
                ch->rs = sizeof(SceneryTreeNode);
                ch->nrec = (long)(csize / ch->rs);
            } else {
                ch->letter = 'c';
                ch->rs = 1;
                ch->nrec = csize;
            }
            memcpy(c + 8, d + o + 8, csize);
            host = csize;
        }
        // The size keeps the disc's residue mod 16, so the next child sits
        // where the image has it; the slack is under 16 bytes, less than any
        // host record, so the count is the disc's.
        host += (csize - host) & 15u;
        ch->hsize = host;
        memcpy(c, &cid, 4);
        memcpy(c + 4, &host, 4);
        c += 8 + host;
        o += 8 + csize;
    }
    {
        uint32_t hs = (uint32_t)(c - (ck->chunk + 8));

        memcpy(ck->chunk + 4, &hs, 4);
    }
}

static void load_zones(Chunk *ck, const uint8_t *d)
{
    long r;
    uint32_t host;

    ck->zones = 1;
    ck->nzones = (long)(ck->size / DISC_ZONE);
    host = (uint32_t)ck->nzones * (uint32_t)sizeof(VisibleZone)
           + ck->size % DISC_ZONE;
    ck->mem = calloc(1, (size_t)host + 64);
    ck->chunk = (uint8_t *)(((uintptr_t)ck->mem + 15) & ~(uintptr_t)15);
    memcpy(ck->chunk, d, 4);
    memcpy(ck->chunk + 4, &host, 4);
    for (r = 0; r < ck->nzones; r++)
        widen_zone((VisibleZone *)(void *)(ck->chunk + 8) + r,
                   d + 8 + (uint32_t)r * DISC_ZONE);
}

static void load_chunk(int k, const uint8_t *d, uint32_t n, uint32_t mis)
{
    Chunk *ck = &chunks[k];

    if (ck->mem != NULL) {
        fprintf(stderr, "chunk %d given twice\n", k);
        exit(2);
    }
    ck->id = rd32(d);
    ck->size = rd32(d + 4);
    if (ck->id == SCENERY_CONTAINER_ID) {
        load_container(ck, k, d, n, mis);
    } else if (ck->id == VISIBLE_ZONE_ID) {
        load_zones(ck, d);
    } else {
        ck->mem = calloc(1, (size_t)n + 32);
        ck->chunk = (uint8_t *)(((uintptr_t)ck->mem + 15) & ~(uintptr_t)15)
                    + mis;
        memcpy(ck->chunk, d, n);
    }
}

// ---------------------------------------------------------------- dumps

static void dump_list(const char *label, bNode *head)
{
    bNode *n, *prev = head;
    int i = 0;

    out("  %s:", label);
    for (n = head->next; n != head && i < 1000; n = n->next, i++) {
        out(" %s", name_of(n));
        if (n->prev != prev)
            out("<%s", name_of(n->prev));
        prev = n;
    }
    if (i == 1000)
        out(" ...");
    else if (head->prev != prev)
        out(" tail %s", name_of(head->prev));
    out("\n");
}

static void dump_lists(void)
{
    dump_list("S", &ScenerySectionHeaderList);
    dump_list("Z", &VisibleZoneList);
}

static void dump_header(int k, int j)
{
    ScenerySectionHeader *h =
        (ScenerySectionHeader *)(void *)chunks[k].child[j].base;

    out("  h%d.%d next %s prev %s sec %d polys %d %d info %s %d inst %s %d "
        "tree %s %d group %s %d views %08x\n", k, j, name_of(h->Node.next),
        name_of(h->Node.prev), (int)h->SectionNumber,
        (int)h->NumPolygonsInMemory, (int)h->NumPolygonsInWorld,
        name_of(h->pSceneryInfo), (int)h->NumSceneryInfo,
        name_of(h->pSceneryInstance), (int)h->NumSceneryInstances,
        name_of(h->SceneryTreeNodeTable), (int)h->NumSceneryTreeNodes,
        name_of(h->SceneryTreeGroupNodeTable),
        (int)h->NumSceneryTreeGroupNodes, h->ViewsVisibleThisFrame);
}

static void dump_info(int k, int j)
{
    Child *ch = &chunks[k].child[j];
    long i;

    for (i = 0; i < ch->nrec; i++) {
        SceneryInfo *f = (SceneryInfo *)(void *)ch->base + i;

        out("  i%d.%d[%ld] hash %08x %08x %08x clip %d %d %d %d models %s "
            "%s %s facade %u %u %u %u radius %08x\n", k, j, i,
            f->NameHash[0], f->NameHash[1], f->NameHash[2],
            f->FarClipSize[0], f->FarClipSize[1], f->FarClipSize[2],
            f->Dummy, name_of(f->pModel[0]), name_of(f->pModel[1]),
            name_of(f->pModel[2]), f->IsFacadeFlag[0], f->IsFacadeFlag[1],
            f->IsFacadeFlag[2], f->Dummy2, fx(f->Radius));
    }
}

static void dump_crc(int k, int j)
{
    Child *ch = &chunks[k].child[j];
    long nr = ch->nrec > 0 ? ch->nrec : 0;

    out("  %c%d.%d %ld crc %08x\n", ch->letter, k, j, ch->nrec,
        crc32_update(0, ch->base, (size_t)nr * ch->rs));
}

static void dump_instances(int k, int j)
{
    Child *ch = &chunks[k].child[j];
    long i;
    int r;

    for (i = 0; i < ch->nrec; i++) {
        SceneryInstance *s = (SceneryInstance *)(void *)ch->base + i;

        out("  n%d.%d[%ld] box %d %d %d %d %d %d kind %d flags %04x pos "
            "%08x %08x %08x rot", k, j, i, s->BBox.BBoxMin[0],
            s->BBox.BBoxMin[1], s->BBox.BBoxMin[2], s->BBox.BBoxMax[0],
            s->BBox.BBoxMax[1], s->BBox.BBoxMax[2], s->SceneryInfoNumber,
            s->ExcludeFlags, fx(s->Position[0]), fx(s->Position[1]),
            fx(s->Position[2]));
        for (r = 0; r < 9; r++)
            out(" %d", s->Rotation[r]);
        out(" pad %04x\n", s->Pad);
    }
}

static void dump_zone(const char *label, const VisibleZone *z)
{
    int i;

    out("  %s num %d:", label, (int)z->NumVisibleScenerySections);
    for (i = 0; i < VISIBLE_ZONE_MAX_SECTIONS; i++)
        out(" %d", z->VisibleScenerySections[i]);
    out("\n");
}

static void dump_zones(int k)
{
    Chunk *ck = &chunks[k];
    long i;

    for (i = 0; i < ck->nzones; i++) {
        VisibleZone *z = (VisibleZone *)(void *)(ck->chunk + 8) + i;

        out("  z%d[%ld] next %s prev %s zone %d caffeine %s\n", k, i,
            name_of(z->Node.next), name_of(z->Node.prev), (int)z->ZoneNumber,
            name_of(z->pCaffeineObj));
    }
}

// Every header's slot, and the whole table's digest.
static void dump_table_for(int k)
{
    Chunk *ck = &chunks[k];
    int j;

    for (j = 0; j < ck->nchild; j++) {
        if (ck->child[j].letter == 'h') {
            int32_t s = ((ScenerySectionHeader *)(void *)ck->child[j].base)
                        ->SectionNumber;

            if (s >= 0 && s < SCENERY_MAX_SECTIONS)
                out("  table[%d] %s\n", (int)s,
                    name_of(ScenerySectionHeaderTable[s]));
        }
    }
}

static void dump_table(void)
{
    int s;

    out("  table:");
    for (s = 0; s < SCENERY_MAX_SECTIONS; s++)
        if (ScenerySectionHeaderTable[s] != NULL)
            out(" %d=%s", s, name_of(ScenerySectionHeaderTable[s]));
    out("\n");
}

static void dump_chunk(int k, int full)
{
    Chunk *ck = &chunks[k];
    int j;

    dump_lists();
    if (ck->zones) {
        dump_zones(k);
        return;
    }
    if (ck->id != SCENERY_CONTAINER_ID)
        return;
    dump_table_for(k);
    for (j = 0; j < ck->nchild; j++) {
        switch (ck->child[j].letter) {
        case 'h':
            dump_header(k, j);
            break;
        case 'i':
            if (full)
                dump_info(k, j);
            break;
        case 'n':
        case 't':
            if (full)
                dump_crc(k, j);
            break;
        default:
            break;
        }
    }
}

static void dump_tbuf(void)
{
    int i;

    out("  tbuf");
    for (i = 0; i < TGUARD + TSIZE + TGUARD; i++)
        out(" %d", tbuf[i]);
    out("\n");
}

static void dump_m(const bMatrix4 *m)
{
    const float *f = &m->v0.x;
    int i;

    for (i = 0; i < 16; i++)
        out(" %08x", fx(f[i]));
}

// ---------------------------------------------------------------- main

int main(int argc, char **argv)
{
    uint32_t op;

    if (argc != 2 || (script = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: scenery_test script\n");
        return 2;
    }
    eMathInit();                // eInit's, before any facade
    eModelSlotPool = (BSlotPool *)(void *)&pool_sentinel;
    gEModelInitFn = f_init;
    gEModelDestroyFn = f_destroy;
    memset(&zscratch, 0xa5, sizeof zscratch);

    while (fscanf(script, "%x", &op) == 1) {
        switch (op) {
        case OP_TAG:
            out("[%u]\n", next());
            break;
        case OP_SINIT:
            scenery_static_init();
            out("static init\n");
            dump_lists();
            break;
        case OP_SCLOSE:
            out("static close\n");
            scenery_static_close();
            dump_lists();
            break;
        case OP_LIST:
            out("list\n");
            dump_lists();
            break;
        case OP_TABLE:
            out("table\n");
            dump_table();
            break;
        case OP_CHUNK: {
            int k = (int)next();
            uint32_t mis = next(), n = next(), w;
            uint8_t *d = calloc(1, (size_t)n + 4);

            if (k < 0 || k >= NCHUNK || d == NULL) {
                fprintf(stderr, "bad chunk %d\n", k);
                return 2;
            }
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
            int k = (int)next(), full = (int)next();
            int r = (int)scenery_loader(chunks[k].chunk);

            out("load %d -> %d\n", k, r);
            dump_chunk(k, full);
            break;
        }
        case OP_UNLOAD: {
            int k = (int)next();
            int r = (int)scenery_unloader(chunks[k].chunk);

            out("unload %d -> %d\n", k, r);
            dump_chunk(k, 0);
            break;
        }
        case OP_DIR:
            RaceParametersTrackDirection = (eTrackDirection)next();
            out("direction %d\n", (int)RaceParametersTrackDirection);
            break;
        case OP_FIND_INFO: {
            uint32_t h = next();

            out("find info %08x -> %s\n", h, name_of(scenery_find_info(h)));
            break;
        }
        case OP_FIND_INST_HASH: {
            uint32_t h = next();

            out("find instance %08x -> %s\n", h,
                name_of(scenery_find_instance_by_hash(h)));
            break;
        }
        case OP_FIND_INST: {
            int32_t s = (int32_t)next(), i = (int32_t)next();

            out("find instance %d %d -> %s\n", (int)s, (int)i,
                name_of(scenery_find_instance(s, i)));
            break;
        }
        case OP_PIP: {
            int32_t n = (int32_t)next();
            bVector2 pt;
            int i;

            pt.x = as_float(next());
            pt.y = as_float(next());
            if (n > NPOLY) {
                fprintf(stderr, "polygon too big\n");
                return 2;
            }
            for (i = 0; i < n; i++) {
                poly[i].x = as_float(next());
                poly[i].y = as_float(next());
            }
            out("pip %d %08x %08x -> %d\n", (int)n, fb(pt.x), fb(pt.y),
                (int)scenery_is_point_in_poly(&pt, poly, n));
            break;
        }
        case OP_FIND_ZONE: {
            bVector2 pt;

            pt.x = as_float(next());
            pt.y = as_float(next());
            out("find zone %08x %08x -> %s\n", fb(pt.x), fb(pt.y),
                name_of(scenery_find_visible_zone(&pt)));
            dump_list("Z", &VisibleZoneList);
            break;
        }
        case OP_ZSET: {
            int i;

            zscratch.NumVisibleScenerySections = (int32_t)next();
            for (i = 0; i < VISIBLE_ZONE_MAX_SECTIONS; i += 2) {
                uint32_t w = next();

                zscratch.VisibleScenerySections[i] = (int16_t)(w & 0xffff);
                zscratch.VisibleScenerySections[i + 1] = (int16_t)(w >> 16);
            }
            dump_zone("zs", &zscratch);
            break;
        }
        case OP_ZINDEX: {
            int32_t s = (int32_t)next();

            out("zone index %d -> %d\n", (int)s,
                (int)visible_zone_find_index_to(&zscratch, s));
            break;
        }
        case OP_ZFREE: {
            int32_t r = visible_zone_find_next_free_index(&zscratch);

            out("zone free -> %d num %d\n", (int)r,
                (int)zscratch.NumVisibleScenerySections);
            break;
        }
        case OP_INIT_VZ:
            out("init visible zones\n");
            scenery_init_visible_zones();
            out("  boundary %s\n", name_of(pVisibleZoneBoundaryModel));
            break;
        case OP_CLOSE_VZ:
            out("close visible zones\n");
            scenery_close_visible_zones();
            out("  boundary %s\n", name_of(pVisibleZoneBoundaryModel));
            break;
        case OP_BLINK: {
            int32_t s = (int32_t)next();

            scenery_handle_joystick_blink_section(s);
            out("blink %d -> %d\n", (int)s,
                (int)AdvanceFastBlinkSectionNumber);
            break;
        }
        case OP_SETZONE:
            CurrentZoneNumber = (int32_t)next();
            break;
        case OP_GETZONE:
            out("zone number %d\n", (int)scenery_get_current_zone_number());
            break;
        case OP_TSET: {
            int i;

            for (i = 0; i < TGUARD + TSIZE + TGUARD; i += 2) {
                uint32_t w = next();

                tbuf[i] = (int16_t)(w & 0xffff);
                tbuf[i + 1] = (int16_t)(w >> 16);
            }
            break;
        }
        case OP_IS: {
            int32_t n = (int32_t)next(), v = (int32_t)next();

            out("is in table %d %d -> %d\n", (int)n, (int)v,
                (int)scenery_is_in_table(tbuf + TGUARD, n, v));
            break;
        }
        case OP_TOGGLE: {
            int32_t n = (int32_t)next(), max = (int32_t)next();
            int32_t v = (int32_t)next();

            out("toggle %d %d %d -> %d\n", (int)n, (int)max, (int)v,
                (int)scenery_toggle_is_in_table(tbuf + TGUARD, n, max, v));
            dump_tbuf();
            break;
        }
        case OP_FACADE: {
            bVector3 pos, eye;
            bMatrix4 m;

            pos.x = as_float(next());
            pos.y = as_float(next());
            pos.z = as_float(next());
            pos.pad = as_float(next());
            eye.x = as_float(next());
            eye.y = as_float(next());
            eye.z = as_float(next());
            eye.pad = as_float(next());
            memset(&m, 0xa5, sizeof m);
            scenery_create_facade_matrix(&m, &pos, &eye);
            out("facade");
            dump_m(&m);
            out("\n");
            break;
        }
        case OP_DUMP_INST: {
            int k = (int)next(), j = (int)next();

            out("instances %d.%d\n", k, j);
            dump_instances(k, j);
            break;
        }
        case OP_FLIP: {
            int k = (int)next(), j = (int)next();

            out("flip h%d.%d\n", k, j);
            scenery_flip_objects_on_backwards_track(
                (ScenerySectionHeader *)(void *)chunks[k].child[j].base);
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
