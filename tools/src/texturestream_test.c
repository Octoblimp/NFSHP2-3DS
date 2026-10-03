// Host harness for tools/texturestream_check.py: runs texturestream.c, the
// streaming half of TexturePack, over the checker's scenario, with
// texturepack.c, queuedfile.c and blist.c under it, and prints what each
// op leaves -- every pack, its ranges and loaded records, the queued
// reads, and every call into the stubs below.
//
// The stubs are this file's, as the model's are its:
//   * bfile.h over a fake file system: files read whole from the disc's
//     tree (FF) or given as hex (FS). A read's bytes land at once; an
//     asynchronous one's callback is due K bServiceFileSystem calls later.
//   * bMalloc and bFree over a fake heap: blocks 128-aligned, filled with
//     0xcd, labelled hN in order. A table's block (named for its pack) is
//     printed as the image's 164-byte records, whatever the host's are,
//     and labels as hN.i, record i.
//   * the slot pool, 128-byte slots filled with 0xcd, the lowest free first.
//   * eWaitUntilRenderingDone and eFixUpTables print. ~TexturePack's
//     ServiceQueuedFiles is the real one, QueuedFile run as the port has it.
//   * Joylog's GetData answers 0; AddData prints.
//   * cb prints its parameter; cb2 prints, then loads CH's textures into
//     CH's pack with cb and 77.
//
// Scenario lines (tools/texturestream_check.py has the full list):
//   B <n> | C | 0 | I              scenario, static inits, globals, pool
//   FF <name> <path> | FS <name> <hex> | FD <name> | K <n>
//   P <k> <name>                   pack k, constructed with no file name
//   T <k> <file>                   LoadTextureTableFromFile
//   L <k> <cb> <param> <n> <h>...  LoadTexturesFromFile
//   U <k> <n> <h>...               UnloadTexturesFromFile
//   A|R|FL|FN <k> <pos> <size>     Add, Remove, the two finds
//   LT|UT <k> <i>                  Load/UnloadTextureFromFile, record i
//   DL <k> <j>                     DeleteLoadedTextureData, range j
//   SV <k> | S <n> | W <k>         service, ServiceQueuedFiles, wait
//   UA <k> | GS <k> | D <k>        UnloadAll, GetLoadedSize, ~TexturePack
//   PR <k> <i> <f> <v> | PP <k> <f> <v> | PL <k> <j> <f> <v>   pokes
//   CH <k> <n> <h>...              cb2's load
// Every op is echoed as "> " and its first 48 characters; all but the file
// and stub settings print the state.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bfile.h"
#include "bmem.h"
#include "bslotpool.h"
#include "esolid.h"
#include "eview.h"
#include "joylog.h"
#include "queuedfile.h"
#include "texturepack.h"
#include "texturestream.h"

#define NSLOT      32
#define SLOT_BYTES 128
#define PATTERN    0xcd
#define MAXFILES   256
#define MAXFS      64
#define MAXREADS   64
#define MAXBLK     4096
#define MAXPACK    8
#define MAXH       64
#define HEAP_BYTES (12u << 20)
#define MAX_FS     4000
#define DISC_RECORD 164

// esolid.c, realtime.c and eview.c are not linked.
int32_t eDirtyTextures;
int32_t RealTimeFrames;
int32_t WorldTimeFrames;
void (*gEWaitUntilRenderingDoneFn)(void);
int32_t Joylog_ReplayingFlag;

typedef union Slot {
    uint8_t   b[SLOT_BYTES];
    uintptr_t align;
} Slot;

static Slot slots[NSLOT];
static int  slot_used[NSLOT];
static char pool_token;

typedef struct FsEntry {
    char     name[256];
    uint8_t *data;
    int32_t  size;
    int      present;
} FsEntry;

struct bFile {
    uint8_t *data;
    int32_t  size;
    int32_t  pos;
};

typedef struct Read {
    int           due;
    bFile        *f;
    bFileCallback cb;
    intptr_t      param;
} Read;

typedef struct Block {
    uint8_t *base;
    int32_t  size;
    int      live;
    int      table;     // a pack's table: labelled by record
} Block;

static FsEntry fs[MAXFS];
static int     nfs;
static bFile   files[MAXFILES];
static int     nfiles;
static Read    reads[MAXREADS];
static int     nreads;
static int     latency;
static int     fs_calls;

static uint8_t *heap;
static size_t   heap_top;
static Block    blocks[MAXBLK];
static int      nblocks;

static TexturePack *packs[MAXPACK];
static int          ch_pack;
static uint32_t     ch_hash[MAXH];
static int          ch_n;

static char  *line;
static size_t line_cap;

// --------------------------------------------------------------- labels

static int pack_of_list(const void *p)
{
    int k;

    for (k = 0; k < MAXPACK; k++)
        if (packs[k] != NULL && p == &packs[k]->LoadedTextureDataList)
            return k;
    return -1;
}

static const char *nm(const void *p)
{
    static char buf[8][32];
    static int k;
    char *b = buf[k++ & 7];
    const uint8_t *q = p;
    int i;

    if (p == NULL)
        return "NULL";
    if (p == &pool_token)
        return "pool";
    if (p == &QueuedFileList)
        return "QL";
    if (p == &TexturePackList)
        return "TPL";
    if ((i = pack_of_list(p)) >= 0) {
        snprintf(b, 32, "pk%d.ltd", i);
        return b;
    }
    if (q >= slots[0].b && q < slots[NSLOT].b
        && (size_t)(q - slots[0].b) % sizeof(Slot) == 0) {
        snprintf(b, 32, "#%d", (int)((size_t)(q - slots[0].b) / sizeof(Slot)));
        return b;
    }
    if (q >= (const uint8_t *)files
        && q < (const uint8_t *)(files + MAXFILES)) {
        snprintf(b, 32, "f%d", (int)((const bFile *)p - files));
        return b;
    }
    for (i = 0; i < nblocks; i++) {
        const uint8_t *base = blocks[i].base;
        int32_t size = blocks[i].size > 0 ? blocks[i].size : 1;

        if (q >= base && q < base + size) {
            size_t off = (size_t)(q - base);

            if (blocks[i].table) {
                size_t r = off / sizeof(TextureInfo);

                off %= sizeof(TextureInfo);
                if (off == 0)
                    snprintf(b, 32, "h%d.%d", i, (int)r);
                else
                    snprintf(b, 32, "h%d.%d+?", i, (int)r);
            } else if (off == 0) {
                snprintf(b, 32, "h%d", i);
            } else {
                snprintf(b, 32, "h%d+%d", i, (int)off);
            }
            return b;
        }
    }
    return "?";
}

// A parameter: a label when it is one, else the number.
static const char *pm(intptr_t v)
{
    static char buf[4][32];
    static int k;
    const char *s = nm((const void *)v);

    if (strcmp(s, "?") != 0)
        return s;
    snprintf(buf[k & 3], 32, "%d", (int)(int32_t)v);
    return buf[k++ & 3];
}

// A word the image holds as it was copied: its 32 bits.
static uint32_t w32(const void *p)
{
    return (uint32_t)(uintptr_t)p;
}

static void user_cb(intptr_t param);
static void user_cb2(intptr_t param);

static const char *cbnm(LoadedTextureDataCallback f)
{
    if (f == NULL)
        return "NULL";
    if (f == user_cb)
        return "cb";
    if (f == user_cb2)
        return "cb2";
    return "?";
}

static const char *esc(const char *s, size_t cap)
{
    static char buf[2][1024];
    static int k;
    char *b = buf[k++ & 1];
    size_t i, o = 0;

    for (i = 0; i < cap && s[i] != '\0'; i++) {
        unsigned c = (uint8_t)s[i];

        if (c >= 33 && c <= 126)
            b[o++] = (char)c;
        else
            o += (size_t)snprintf(b + o, 8, "%%%02x", c);
    }
    b[o] = '\0';
    return b;
}

// zlib's CRC-32.
static const char *crc(const uint8_t *p, int32_t n)
{
    static char buf[2][16];
    static int k;
    char *b = buf[k++ & 1];
    uint32_t c = 0xffffffffu;
    int32_t i;
    int j;

    if (p == NULL || n <= 0)
        return "-";
    for (i = 0; i < n; i++) {
        c ^= p[i];
        for (j = 0; j < 8; j++)
            c = (c >> 1) ^ (0xedb88320u & (0u - (c & 1)));
    }
    snprintf(b, 16, "%08x", c ^ 0xffffffffu);
    return b;
}

// ------------------------------------------------------------- the heap

static uint8_t *halloc(int32_t size, int table)
{
    size_t base = (heap_top + 127) & ~(size_t)127;
    size_t span = size > 0 ? (size_t)size : 1;

    if (base + span > HEAP_BYTES || nblocks >= MAXBLK) {
        fprintf(stderr, "heap full\n");
        exit(3);
    }
    heap_top = base + span;
    blocks[nblocks].base = heap + base;
    blocks[nblocks].size = size;
    blocks[nblocks].live = 1;
    blocks[nblocks].table = table;
    nblocks++;
    if (size > 0)
        memset(heap + base, PATTERN, (size_t)size);
    return heap + base;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    // Every block but a table is named for what it is; a table for its
    // pack, and sized by the host's records. A LoadedTextureData is the
    // host's size from pool 16; a range's data, named the same, is from
    // the pack's pool, 64 unless the script pokes it.
    int table = strcmp(name, "TextureTable") != 0
                && strcmp(name, "LoadedTextureData") != 0;
    uint8_t *p = halloc(size, table);

    printf("  malloc %d %s %d %d -> %s\n",
           table ? (int)((size_t)size / sizeof(TextureInfo) * DISC_RECORD)
                 : (strcmp(name, "LoadedTextureData") == 0 && pool == 16
                    && size == (int)sizeof(LoadedTextureData)) ? 44 : size,
           esc(name, 160), flags, pool, nm(p));
    return p;
}

void bFree(void *p)
{
    int i;

    for (i = 0; i < nblocks; i++) {
        if (blocks[i].base == p) {
            printf("  free %s%s\n", nm(p), blocks[i].live ? "" : " again");
            blocks[i].live = 0;
            return;
        }
    }
    printf("  free %s\n", nm(p));
}

// ------------------------------------------------------------- the pool

BSlotPool *bNewSlotPool(int slotSize, int numSlots, const char *name,
                        int memoryPool)
{
    printf("  newpool %d %d %s %d\n", slotSize, numSlots, name, memoryPool);
    return (BSlotPool *)(void *)&pool_token;
}

void bDeleteSlotPool(BSlotPool *pool)
{
    printf("  delpool %s\n", nm(pool));
}

void *bSlotOMalloc(BSlotPool *pool)
{
    int i;

    for (i = 0; i < NSLOT; i++) {
        if (!slot_used[i]) {
            slot_used[i] = 1;
            memset(&slots[i], PATTERN, sizeof slots[i]);
            printf("  omalloc %s -> #%d\n", nm(pool), i);
            return &slots[i];
        }
    }
    fprintf(stderr, "slots full\n");
    exit(3);
}

void bSlotFree(BSlotPool *pool, void *slot)
{
    const uint8_t *q = slot;

    printf("  pfree %s %s\n", nm(pool), nm(slot));
    if (q >= slots[0].b && q < slots[NSLOT].b)
        slot_used[(size_t)(q - slots[0].b) / sizeof(Slot)] = 0;
}

// ------------------------------------------------------ the file system

static FsEntry *fs_find(const char *name)
{
    int i;

    for (i = 0; i < nfs; i++)
        if (fs[i].present && strcmp(fs[i].name, name) == 0)
            return &fs[i];
    return NULL;
}

bFile *bOpen(const char *name)
{
    FsEntry *e = fs_find(name);
    bFile *f;

    if (e == NULL || nfiles >= MAXFILES) {
        printf("  open %s -> NULL\n", esc(name, 4096));
        return NULL;
    }
    f = &files[nfiles++];
    f->data = e->data;
    f->size = e->size;
    f->pos = 0;
    printf("  open %s -> %s\n", esc(name, 4096), nm(f));
    return f;
}

void bClose(bFile *f)
{
    printf("  close %s\n", nm(f));
}

int32_t bFileSize(bFile *f)
{
    printf("  size %s -> %d\n", nm(f), (int)f->size);
    return f->size;
}

int32_t bFileSizeName(const char *name)
{
    FsEntry *e = fs_find(name);
    int32_t n = e != NULL ? e->size : -1;

    printf("  sizename %s -> %d\n", esc(name, 4096), (int)n);
    return n;
}

void bSeek(bFile *f, int32_t pos, int32_t whence)
{
    f->pos = pos;
    printf("  seek %s %d %d\n", nm(f), (int)pos, (int)whence);
}

static void read_bytes(bFile *f, void *buf, int32_t n)
{
    if (n > 0) {
        int32_t k = f->size - f->pos;

        if (k > n)
            k = n;
        if (k > 0)
            memcpy(buf, f->data + f->pos, (size_t)k);
        f->pos += n;
    }
}

void bRead(bFile *f, void *buf, int32_t n)
{
    printf("  readsync %s %s %d %s\n", nm(f), nm(buf), (int)n,
           crc(f->data + f->pos,
               f->size - f->pos < n ? f->size - f->pos : n));
    read_bytes(f, buf, n);
}

void bReadAsync(bFile *f, void *buf, int32_t n, bFileCallback cb,
                intptr_t param)
{
    printf("  read %s %s %d %s %s\n", nm(f), nm(buf), (int)n,
           cb != NULL ? "rdone" : "NULL", pm(param));
    read_bytes(f, buf, n);
    if (nreads >= MAXREADS) {
        fprintf(stderr, "too many reads\n");
        exit(3);
    }
    reads[nreads].due = latency;
    reads[nreads].f = f;
    reads[nreads].cb = cb;
    reads[nreads].param = param;
    nreads++;
}

void bServiceFileSystem(void)
{
    Read due[MAXREADS];
    int i, ndue = 0, kept = 0;

    printf("  servicefs\n");
    if (++fs_calls > MAX_FS) {
        printf("fs spin\n");
        exit(5);
    }
    for (i = 0; i < nreads; i++) {
        if (--reads[i].due <= 0)
            due[ndue++] = reads[i];
        else
            reads[kept++] = reads[i];
    }
    nreads = kept;
    for (i = 0; i < ndue; i++) {
        printf("  readdone %s\n", nm(due[i].f));
        due[i].cb(due[i].f, due[i].param);
    }
}

// ------------------------------------------------------ the rest of them

int32_t Joylog_GetData(int32_t bits, int32_t channel)
{
    printf("  joyget %d %d -> 0\n", (int)bits, (int)channel);
    return 0;
}

void Joylog_AddData(int32_t value, int32_t bits, int32_t channel)
{
    printf("  joyadd %d %d %d\n", (int)value, (int)bits, (int)channel);
}

void efix_up_tables(void)
{
    printf("  fixup\n");
}

static void s_wait(void)
{
    printf("  waitrender\n");
}

static void user_cb(intptr_t param)
{
    printf("  callback %s\n", pm(param));
}

static void user_cb2(intptr_t param)
{
    printf("  callback2 %s\n", pm(param));
    texturepack_load_textures_from_file(packs[ch_pack], ch_hash, ch_n,
                                        user_cb, 77);
    printf("  chained\n");
}

// ------------------------------------------------------------ the print

static void print_records(const TexturePack *p)
{
    int32_t i;

    for (i = 0; i < p->NumTextures; i++) {
        const TextureInfo *t = &p->pTextureInfo[i];

        printf("  rec %d %s name=%s hash=%08x wh=%d,%d img=%d+%d "
               "pal=%d+%d parent=%s pack=%s node=%08x,%08x stk=%08x "
               "vram=%d,%d crc=%s\n", (int)i, nm(t),
               esc(t->DebugName, sizeof t->DebugName), t->NameHash,
               t->Width, t->Height, (int)t->ImagePlacement,
               (int)t->ImageSize, (int)t->PalettePlacement,
               (int)t->PaletteSize, nm(t->pImageParent), nm(t->pTexturePack),
               w32(t->Node.next), w32(t->Node.prev),
               w32(t->pStackedActiveTexture), t->PaletteVramAddress,
               t->ImageVramAddress,
               crc((const uint8_t *)t + offsetof(TextureInfo, DebugName),
                   128));
    }
}

static void print_pack(int k)
{
    const TexturePack *p = packs[k];
    const bNode *n;
    int32_t i;
    int c;

    printf("pk%d %s name=%s file=%s hash=%08x inv=%08x info=%s num=%d "
           "free=%d pos=%d cur=%s nyl=%d pool=%d prev=%s lprev=%s\n", k,
           nm(p), esc(p->Name, sizeof p->Name),
           esc(p->Filename, sizeof p->Filename), p->NameHash,
           (uint32_t)p->InventoryHandle, nm(p->pTextureInfo),
           (int)p->NumTextures, (int)p->pTextureInfoNeedsToBeFreed,
           (int)p->TextureDataFilePos, nm(p->CurrentLoadingTextureData),
           (int)p->NumNotYetLoadedTextureDatas, (int)p->MemoryPool,
           nm(p->Node.prev), nm(p->LoadedTextureDataList.prev));
    for (n = p->LoadedTextureDataList.next, c = 0;
         n != &p->LoadedTextureDataList && n != NULL && c < 256;
         n = n->next, c++) {
        const LoadedTextureData *d = (const LoadedTextureData *)n;
        int32_t len = d->HighPos - d->LowPos;

        printf("  ltd %s lo=%d hi=%d n=%d pool=%d buf=%s done=%d busy=%d "
               "cb=%s param=%s prev=%s data=%s\n", nm(d), (int)d->LowPos,
               (int)d->HighPos, (int)d->NumAssignments, (int)d->MemoryPool,
               nm(d->Buf), (int)d->LoadingCompleted,
               (int)d->LoadingInProgress, cbnm(d->Callback),
               pm(d->CallbackParam), nm(n->prev),
               d->LoadingCompleted && len > 0 && len < (1 << 22)
                   ? crc(d->Buf, len) : "-");
    }
    if (n == NULL)
        printf("  ltds null\n");
    else if (c == 256)
        printf("  ltds loop\n");
    for (i = 0; i < p->NumTextures; i++) {
        const TextureInfo *t = &p->pTextureInfo[i];

        if (t->ImageData != NULL || t->PaletteData != NULL)
            printf("  tex %d img=%s pal=%s\n", (int)i, nm(t->ImageData),
                   nm(t->PaletteData));
    }
}

static void print_state(void)
{
    const bNode *n;
    int k;

    for (k = 0; k < MAXPACK; k++)
        if (packs[k] != NULL)
            print_pack(k);
    printf("st dirty=%d handle=%d reading=%d pool=%s tpl=%s,%s\n",
           (int)eDirtyTextures, (int)QueuedFile_CurrentHandle,
           (int)QueuedFileReadInProgress, nm(QueuedFileSlotPool),
           nm(TexturePackList.next), nm(TexturePackList.prev));
    eDirtyTextures = 0;
    for (n = QueuedFileList.next, k = 0;
         n != &QueuedFileList && n != NULL && k < 64; n = n->next, k++) {
        const QueuedFile *qf = (const QueuedFile *)n;

        printf("qf %s buf=%s name=%s pos=%d n=%d read=%d block=%d prio=%d "
               "cb=%s param=%s handle=%d status=%d abort=%d prev=%s\n",
               nm(qf), nm(qf->pBuf), esc(qf->Filename, 48),
               (int)qf->FilePos, (int)qf->NumBytes, (int)qf->NumRead,
               (int)qf->BlockSize, (int)qf->Priority,
               qf->Callback != NULL ? "tpcb" : "NULL",
               pm(qf->CallbackParam), (int)qf->Handle, (int)qf->Status,
               (int)qf->AbortFlag, nm(n->prev));
    }
    if (n == NULL)
        printf("qfs null\n");
    else if (k == 64)
        printf("qfs loop\n");
    printf("qfs end prev=%s\n", nm(QueuedFileList.prev));
}

// ------------------------------------------------------------- the ops

static int hexval(int c)
{
    if (c >= '0' && c <= '9')
        return c - '0';
    if (c >= 'a' && c <= 'f')
        return c - 'a' + 10;
    if (c >= 'A' && c <= 'F')
        return c - 'A' + 10;
    return -1;
}

static int read_line(FILE *f)
{
    size_t n = 0;
    int c;

    while ((c = fgetc(f)) != EOF && c != '\n') {
        // A file path runs to the end of its line, and a CR is not in it.
        if (c == '\r')
            continue;
        if (n + 2 > line_cap) {
            line_cap = line_cap ? 2 * line_cap : 4096;
            line = realloc(line, line_cap);
            if (line == NULL)
                exit(3);
        }
        line[n++] = (char)c;
    }
    if (c == EOF && n == 0)
        return 0;
    if (line == NULL) {
        line_cap = 16;
        line = malloc(line_cap);
    }
    line[n] = '\0';
    return 1;
}

static void reset(void)
{
    nfs = 0;
    nfiles = 0;
    nreads = 0;
    latency = 1;
    memset(slot_used, 0, sizeof slot_used);
    memset(packs, 0, sizeof packs);
    heap_top = 0;
    nblocks = 0;
    fs_calls = 0;
    ch_pack = 0;
    ch_n = 0;
}

static FsEntry *fs_entry(const char *name)
{
    FsEntry *e = fs_find(name);

    if (e == NULL) {
        if (nfs >= MAXFS)
            exit(3);
        e = &fs[nfs++];
        strcpy(e->name, name);
        e->present = 1;
    }
    return e;
}

static void op_fs(const char *s)
{
    char name[256];
    int used = 0;
    FsEntry *e;
    size_t len, i;
    const char *hex;

    if (sscanf(s, "%255s%n", name, &used) != 1)
        exit(4);
    hex = s + used;
    while (*hex == ' ')
        hex++;
    e = fs_entry(name);
    len = strlen(hex) / 2;
    // The old bytes stay: a file opened on them still reads them.
    e->data = malloc(len ? len : 1);
    for (i = 0; i < len; i++) {
        int hi = hexval(hex[2 * i]), lo = hexval(hex[2 * i + 1]);

        if (hi < 0 || lo < 0)
            exit(5);
        e->data[i] = (uint8_t)(hi << 4 | lo);
    }
    e->size = (int32_t)len;
}

static void op_ff(const char *s)
{
    char name[256];
    int used = 0;
    const char *path;
    FILE *f;
    long len;
    FsEntry *e;

    if (sscanf(s, "%255s%n", name, &used) != 1)
        exit(4);
    path = s + used;
    while (*path == ' ')
        path++;
    if ((f = fopen(path, "rb")) == NULL) {
        fprintf(stderr, "no %s\n", path);
        exit(4);
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    e = fs_entry(name);
    e->data = malloc(len > 0 ? (size_t)len : 1);
    if (len > 0 && fread(e->data, 1, (size_t)len, f) != (size_t)len)
        exit(4);
    fclose(f);
    e->size = (int32_t)len;
}

static LoadedTextureDataCallback cb_of(int sel)
{
    return sel == 1 ? user_cb : sel == 2 ? user_cb2 : NULL;
}

static TexturePack *pk(int k)
{
    if (k < 0 || k >= MAXPACK || packs[k] == NULL)
        exit(6);
    return packs[k];
}

static LoadedTextureData *range_at(TexturePack *p, int j)
{
    bNode *n = p->LoadedTextureDataList.next;

    while (j-- > 0 && n != &p->LoadedTextureDataList)
        n = n->next;
    if (n == &p->LoadedTextureDataList)
        exit(6);
    return (LoadedTextureData *)(void *)n;
}

// The n hashes after the first `skip` numbers of `a`.
static int hashes(const char *a, int skip, uint32_t *h, int max)
{
    int n = 0, used;
    unsigned long v;

    while (skip-- > 0) {
        if (sscanf(a, "%lu%n", &v, &used) != 1)
            exit(4);
        a += used;
    }
    while (n < max && sscanf(a, "%lx%n", &v, &used) == 1) {
        h[n++] = (uint32_t)v;
        a += used;
    }
    return n;
}

int main(int argc, char **argv)
{
    FILE *f;

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: texturestream_test <scenarios>\n");
        return 2;
    }
    heap = malloc(HEAP_BYTES + 128);
    if (heap == NULL)
        return 3;
    heap += (128 - ((uintptr_t)heap & 127)) & 127;
    gEWaitUntilRenderingDoneFn = s_wait;
    // ~TexturePack waits on ServiceQueuedFiles, as the image's does.
    gServiceQueuedFilesFn = service_queued_files;

    while (read_line(f)) {
        char op[8], name[256], fld[16];
        const char *a;
        int used = 0, show = 1;
        int k, i1, i2, i3;
        long long v;
        uint32_t h[MAXH];

        if (line[0] == 'B' && line[1] == ' ') {
            printf("%s\n", line);
            reset();
            continue;
        }
        printf("> %.48s\n", line);
        fs_calls = 0;
        if (sscanf(line, "%7s%n", op, &used) != 1)
            return 7;
        a = line + used;
        if (strcmp(op, "C") == 0) {
            queuedfile_static_init();
            TexturePackList.next = TexturePackList.prev = &TexturePackList;
        } else if (strcmp(op, "0") == 0) {
            QueuedFile_CurrentHandle = 1;
            QueuedFileReadInProgress = 0;
            Joylog_ReplayingFlag = 0;
            eDirtyTextures = 0;
        } else if (strcmp(op, "I") == 0) {
            init_queued_files();
        } else if (strcmp(op, "FS") == 0) {
            op_fs(a);
            show = 0;
        } else if (strcmp(op, "FF") == 0) {
            op_ff(a);
            show = 0;
        } else if (strcmp(op, "FD") == 0) {
            FsEntry *e;

            sscanf(a, "%255s", name);
            e = fs_find(name);
            if (e == NULL)
                return 6;
            e->present = 0;
            show = 0;
        } else if (strcmp(op, "K") == 0) {
            sscanf(a, "%d", &latency);
            show = 0;
        } else if (strcmp(op, "CH") == 0) {
            sscanf(a, "%d", &ch_pack);
            ch_n = hashes(a, 1, ch_hash, MAXH);
            show = 0;
        } else if (strcmp(op, "P") == 0) {
            TexturePack *p;

            sscanf(a, "%d %255s", &k, name);
            p = (TexturePack *)(void *)halloc((int32_t)sizeof *p, 0);
            printf("  pack %d -> %s\n", k, nm(p));
            packs[k] = texturepack_construct(p, name, NULL);
        } else if (strcmp(op, "T") == 0) {
            sscanf(a, "%d %255s", &k, name);
            texturepack_load_texture_table_from_file(pk(k), name);
            print_records(pk(k));
        } else if (strcmp(op, "L") == 0) {
            sscanf(a, "%d %d %lld %d", &k, &i1, &v, &i2);
            hashes(a, 4, h, MAXH);
            texturepack_load_textures_from_file(pk(k), h, i2, cb_of(i1),
                                                (intptr_t)(int32_t)v);
        } else if (strcmp(op, "U") == 0) {
            sscanf(a, "%d %d", &k, &i2);
            hashes(a, 2, h, MAXH);
            texturepack_unload_textures_from_file(pk(k), h, i2);
        } else if (strcmp(op, "A") == 0) {
            sscanf(a, "%d %d %d", &k, &i1, &i2);
            texturepack_add_loaded_texture_data(pk(k), i1, i2);
        } else if (strcmp(op, "R") == 0) {
            sscanf(a, "%d %d %d", &k, &i1, &i2);
            printf("R -> %d\n",
                   (int)texturepack_remove_loaded_texture_data(pk(k), i1,
                                                               i2));
        } else if (strcmp(op, "FL") == 0) {
            sscanf(a, "%d %d %d", &k, &i1, &i2);
            printf("FL -> %s\n",
                   nm(texturepack_find_loaded_texture_data(pk(k), i1, i2)));
            show = 0;
        } else if (strcmp(op, "FN") == 0) {
            sscanf(a, "%d %d %d", &k, &i1, &i2);
            printf("FN -> %s\n",
                   nm(texturepack_find_not_yet_loaded_neighbour_texture_data(
                       pk(k), i1, i2)));
            show = 0;
        } else if (strcmp(op, "LT") == 0 || strcmp(op, "UT") == 0) {
            sscanf(a, "%d %d", &k, &i1);
            if (op[0] == 'L')
                texturepack_load_texture_from_file(pk(k),
                                                   &pk(k)->pTextureInfo[i1]);
            else
                texturepack_unload_texture_from_file(
                    pk(k), &pk(k)->pTextureInfo[i1]);
        } else if (strcmp(op, "DL") == 0) {
            sscanf(a, "%d %d", &k, &i1);
            texturepack_delete_loaded_texture_data(pk(k),
                                                   range_at(pk(k), i1));
        } else if (strcmp(op, "SV") == 0) {
            sscanf(a, "%d", &k);
            texturepack_service_loading_textures(pk(k));
        } else if (strcmp(op, "S") == 0) {
            sscanf(a, "%d", &i1);
            while (i1-- > 0)
                service_queued_files();
        } else if (strcmp(op, "W") == 0) {
            int m = 0;

            sscanf(a, "%d", &k);
            while (pk(k)->CurrentLoadingTextureData != NULL && m < 2000) {
                service_queued_files();
                m++;
            }
            printf("W -> %d\n", m);
        } else if (strcmp(op, "UA") == 0) {
            sscanf(a, "%d", &k);
            texturepack_unload_all_textures_from_file(pk(k));
        } else if (strcmp(op, "GS") == 0) {
            sscanf(a, "%d", &k);
            printf("GS -> %d\n", (int)texturepack_get_loaded_size(pk(k)));
            show = 0;
        } else if (strcmp(op, "D") == 0) {
            sscanf(a, "%d", &k);
            texturepack_destruct(pk(k), 3);
            packs[k] = NULL;
        } else if (strcmp(op, "PR") == 0) {
            TextureInfo *t;

            sscanf(a, "%d %d %15s %d", &k, &i1, fld, &i3);
            t = &pk(k)->pTextureInfo[i1];
            if (strcmp(fld, "ip") == 0)
                t->ImagePlacement = i3;
            else if (strcmp(fld, "is") == 0)
                t->ImageSize = i3;
            else if (strcmp(fld, "pp") == 0)
                t->PalettePlacement = i3;
            else if (strcmp(fld, "ps") == 0)
                t->PaletteSize = i3;
            else
                return 6;
        } else if (strcmp(op, "PP") == 0) {
            TexturePack *p;

            sscanf(a, "%d %15s %d", &k, fld, &i3);
            p = pk(k);
            if (strcmp(fld, "pos") == 0)
                p->TextureDataFilePos = i3;
            else if (strcmp(fld, "pool") == 0)
                p->MemoryPool = i3;
            else if (strcmp(fld, "nyl") == 0)
                p->NumNotYetLoadedTextureDatas = i3;
            else
                return 6;
        } else if (strcmp(op, "PL") == 0) {
            LoadedTextureData *d;

            sscanf(a, "%d %d %15s %d", &k, &i1, fld, &i3);
            d = range_at(pk(k), i1);
            if (strcmp(fld, "lo") == 0)
                d->LowPos = i3;
            else if (strcmp(fld, "hi") == 0)
                d->HighPos = i3;
            else if (strcmp(fld, "n") == 0)
                d->NumAssignments = i3;
            else if (strcmp(fld, "busy") == 0)
                d->LoadingInProgress = i3;
            else if (strcmp(fld, "done") == 0)
                d->LoadingCompleted = i3;
            else
                return 6;
        } else {
            fprintf(stderr, "bad op %s\n", line);
            return 7;
        }
        if (show)
            print_state();
    }
    fclose(f);
    return 0;
}
