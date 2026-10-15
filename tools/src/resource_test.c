// Host harness for tools/resource_check.py: runs resource.c and
// queuedfile.c over the scenario and prints what each op leaves -- the
// globals, both lists and every call into the stubs below.
//
// The stubs are this file's, as the model's are its:
//   * bfile.h over a fake file system of named byte strings. A read's bytes
//     land at once and its callback is due K bServiceFileSystem calls
//     later; due ones run in the order the reads were made.
//   * bMalloc and bFree over a fake heap: blocks 128-aligned, filled with
//     0xcd, labelled hN in order. ResourceFile's own block is printed as the
//     image's 216 bytes, whatever the host's struct is.
//   * the slot pool, 128-byte slots filled with 0xcd, the lowest free first.
//   * LoadChunks and UnloadChunks print the CRC-32 of their bytes;
//     PostLoadFixup and eWaitUntilRenderingDone print.
//   * Joylog's GetData answers J's value; AddData prints.
//   * cb prints; cb2 prints and loads CH's file. qcb prints; qcb2 prints
//     and queues another read.
//
// Scenario lines (tools/resource_check.py has the full list):
//   B <n>                          scenario n: every stub's state reset
//   C | 0 | I | X | Z              static inits, globals, Init/Close, dtors
//   FS <name> [hex] | FD <name>    a file on the fake disc, or gone
//   K <n> | J <v> | CH <name>      read latency, Joylog's answer, cb2's file
//   V <replay|handle|reading|numres> <v>   a global
//   L <name> <type> <flags> <cb> <param>
//   LH <name> <type> <hot> <keep> <cb> <param>
//   R | RC | U <k> | N <k> <name>  service, complete, unload, rename
//   FN <name> | FT <type>          the two finds
//   GS <k> <id> <cnt> | GT <type> <id> <cnt>
//   Q <name> <pos> <n> <bufsize> <qcb> <param>
//   P <h> <prio> <block> | A <h> | FQ <h> | S | BQ <k> <n>
//   H <k>                          hot-chunk entries, as hot chunking sets
// Every op is echoed as "> " and its first 48 characters; all but the
// finds, sizes, BQ and the stub settings print the state.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunkload.h"
#include "bfile.h"
#include "bmem.h"
#include "bslotpool.h"
#include "eview.h"
#include "joylog.h"
#include "queuedfile.h"
#include "resource.h"

#define NSLOT      32
#define SLOT_BYTES 128
#define PATTERN    0xcd
#define MAXFILES   256
#define MAXFS      64
#define MAXREADS   64
#define MAXRF      256
#define MAXQB      256
#define MAXBLK     1024
#define HEAP_BYTES (9u << 20)
#define MAX_FS     400

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
} Block;

static FsEntry fs[MAXFS];
static int     nfs;
static bFile   files[MAXFILES];
static int     nfiles;
static Read    reads[MAXREADS];
static int     nreads;
static int     latency;
static int32_t joy;
static char    chain[256];
static int     fs_calls;

static uint8_t *heap;
static size_t   heap_top;
static Block    blocks[MAXBLK];
static int      nblocks;

static ResourceFile *rfs[MAXRF];
static int           nrf;
static uint8_t      *qbufs[MAXQB];
static int           nqb;

static char  *line;
static size_t line_cap;

// --------------------------------------------------------------- labels

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
    if (p == &ResourceFileList)
        return "RL";
    if (p == &QueuedFileList)
        return "QL";
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
            if (q == base)
                snprintf(b, 32, "h%d", i);
            else
                snprintf(b, 32, "h%d+%d", i, (int)(q - base));
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

static void user_cb(intptr_t param);
static void user_cb2(intptr_t param);
static void user_qcb(intptr_t param, int32_t error);
static void user_qcb2(intptr_t param, int32_t error);

static const char *rcbnm(ResourceFileCallback f)
{
    if (f == NULL)
        return "NULL";
    if (f == user_cb)
        return "cb";
    if (f == user_cb2)
        return "cb2";
    return "?";
}

// FileTransferCallback is resource.c's own.
static const char *qcbnm(QueuedFileCallback f)
{
    if (f == NULL)
        return "NULL";
    if (f == user_qcb)
        return "qcb";
    if (f == user_qcb2)
        return "qcb2";
    return "ftcb";
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

static uint8_t *halloc(int32_t size)
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
    nblocks++;
    if (size > 0)
        memset(heap + base, PATTERN, (size_t)size);
    return heap + base;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    uint8_t *p = halloc(size);

    printf("  malloc %d %s %d %d -> %s\n",
           strcmp(name, "ResourceFile") == 0 ? 216 : size, esc(name, 160),
           flags, pool, nm(p));
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

// The port's own: the fake file system holds each file as it is named,
// and retail's image has no such call, so it says nothing.
int bFileIsExpanded(const char *name)
{
    (void)name;
    return 0;
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

void bReadAsync(bFile *f, void *buf, int32_t n, bFileCallback cb,
                intptr_t param)
{
    printf("  read %s %s %d %s %s\n", nm(f), nm(buf), (int)n,
           cb != NULL ? "rdone" : "NULL", pm(param));
    if (n > 0) {
        int32_t k = f->size - f->pos;

        if (k > n)
            k = n;
        if (k > 0)
            memcpy(buf, f->data + f->pos, (size_t)k);
        f->pos += n;
    }
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
    printf("  joyget %d %d -> %d\n", (int)bits, (int)channel, (int)joy);
    return joy;
}

void Joylog_AddData(int32_t value, int32_t bits, int32_t channel)
{
    printf("  joyadd %d %d %d\n", (int)value, (int)bits, (int)channel);
}

void load_chunks(uint8_t *chunks, int32_t size)
{
    printf("  loadchunks %s %d %s\n", nm(chunks), (int)size,
           crc(chunks, size));
}

void unload_chunks(uint8_t *chunks, int32_t size)
{
    printf("  unloadchunks %s %d %s\n", nm(chunks), (int)size,
           crc(chunks, size));
}

void post_load_fixup(void)
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
    ResourceFile *rf;

    printf("  callback2 %s\n", pm(param));
    rf = load_resource_file(chain, 3, 0, user_cb, 99);
    if (nrf < MAXRF)
        rfs[nrf++] = rf;
    printf("  chained %s\n", nm(rf));
}

static void user_qcb(intptr_t param, int32_t error)
{
    printf("  qcallback %s %d\n", pm(param), (int)error);
}

static void user_qcb2(intptr_t param, int32_t error)
{
    uint8_t *buf;
    int32_t h;

    printf("  qcallback2 %s %d\n", pm(param), (int)error);
    buf = halloc(16);
    if (nqb < MAXQB)
        qbufs[nqb++] = buf;
    h = add_queued_file(buf, "SMALL.BIN", 2, 6, user_qcb, 77);
    printf("  queued %d %s\n", (int)h, nm(buf));
}

// ------------------------------------------------------------ the print

static void print_state(void)
{
    bNode *n;
    int k;

    printf("st n=%d hot=%d handle=%d reading=%d pool=%s replay=%d\n",
           (int)NumResourcesBeingLoaded, (int)HotChunkFilesNeedUpdating,
           (int)QueuedFile_CurrentHandle, (int)QueuedFileReadInProgress,
           nm(QueuedFileSlotPool), (int)Joylog_ReplayingFlag);
    for (n = ResourceFileList.next, k = 0;
         n != &ResourceFileList && n != NULL && k < 64; n = n->next, k++) {
        const ResourceFile *rf = (const ResourceFile *)n;

        printf("rf %s type=%d flags=%d name=%s hot0=%02x xfer=%d done=%d "
               "cb=%s param=%s buf=%s size=%d hent=%s hnum=%d hno=%d inv=%d "
               "prev=%s\n", nm(rf), (int)rf->Type, (int)rf->Flags,
               esc(rf->Filename, 160), (uint8_t)rf->HotFilename[0],
               (int)rf->FileTransfersInProgress,
               (int)rf->LoadingFinishedFlag, rcbnm(rf->Callback),
               pm(rf->CallbackParam), nm(rf->pFirstChunk),
               (int)rf->SizeofChunks, nm(rf->pLoadedHotFileEntries),
               (int)rf->NumLoadedHotFileEntries, (int)rf->HotFileNumber,
               (int)rf->InventoryHandle, nm(n->prev));
    }
    if (n == NULL)
        printf("rfs null\n");
    else if (k == 64)
        printf("rfs loop\n");
    printf("rfs end prev=%s\n", nm(ResourceFileList.prev));
    for (n = QueuedFileList.next, k = 0;
         n != &QueuedFileList && n != NULL && k < 64; n = n->next, k++) {
        const QueuedFile *qf = (const QueuedFile *)n;

        printf("qf %s buf=%s name=%s pos=%d n=%d read=%d block=%d prio=%d "
               "cb=%s param=%s handle=%d status=%d abort=%d prev=%s\n",
               nm(qf), nm(qf->pBuf), esc(qf->Filename, 48),
               (int)qf->FilePos, (int)qf->NumBytes, (int)qf->NumRead,
               (int)qf->BlockSize, (int)qf->Priority, qcbnm(qf->Callback),
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
    nrf = 0;
    nqb = 0;
    nfs = 0;
    nfiles = 0;
    nreads = 0;
    latency = 1;
    joy = 0;
    strcpy(chain, "CHAIN.BUN");
    memset(slot_used, 0, sizeof slot_used);
    heap_top = 0;
    nblocks = 0;
    fs_calls = 0;
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
    e = fs_find(name);
    if (e == NULL) {
        if (nfs >= MAXFS)
            exit(3);
        e = &fs[nfs++];
        strcpy(e->name, name);
        e->present = 1;
    }
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

static ResourceFileCallback rcb(int sel)
{
    return sel == 1 ? user_cb : sel == 2 ? user_cb2 : NULL;
}

static QueuedFileCallback qcb(int sel)
{
    return sel == 1 ? user_qcb : sel == 2 ? user_qcb2 : NULL;
}

static ResourceFile *rf_at(int k)
{
    if (k < 0 || k >= nrf)
        exit(6);
    return rfs[k];
}

int main(int argc, char **argv)
{
    FILE *f;

    if (argc != 2 || (f = fopen(argv[1], "r")) == NULL) {
        fprintf(stderr, "usage: resource_test <scenarios>\n");
        return 2;
    }
    heap = malloc(HEAP_BYTES + 128);
    if (heap == NULL)
        return 3;
    heap += (128 - ((uintptr_t)heap & 127)) & 127;
    gEWaitUntilRenderingDoneFn = s_wait;

    while (read_line(f)) {
        char op[8], name[256];
        const char *a;
        int used = 0, show = 1;
        int i1, i2, i3, i4;
        long long id, param;

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
            resource_static_init();
            queuedfile_static_init();
        } else if (strcmp(op, "0") == 0) {
            NumResourcesBeingLoaded = 0;
            HotChunkFilesNeedUpdating = 0;
            QueuedFile_CurrentHandle = 1;
            QueuedFileReadInProgress = 0;
            Joylog_ReplayingFlag = 0;
        } else if (strcmp(op, "I") == 0) {
            init_queued_files();
        } else if (strcmp(op, "X") == 0) {
            close_queued_files();
        } else if (strcmp(op, "FS") == 0) {
            op_fs(a);
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
        } else if (strcmp(op, "J") == 0) {
            sscanf(a, "%d", &i1);
            joy = i1;
            show = 0;
        } else if (strcmp(op, "CH") == 0) {
            sscanf(a, "%255s", chain);
            show = 0;
        } else if (strcmp(op, "V") == 0) {
            sscanf(a, "%255s %d", name, &i1);
            if (strcmp(name, "replay") == 0)
                Joylog_ReplayingFlag = i1;
            else if (strcmp(name, "handle") == 0)
                QueuedFile_CurrentHandle = i1;
            else if (strcmp(name, "reading") == 0)
                QueuedFileReadInProgress = i1;
            else if (strcmp(name, "numres") == 0)
                NumResourcesBeingLoaded = i1;
            else
                return 6;
        } else if (strcmp(op, "L") == 0) {
            ResourceFile *rf;

            sscanf(a, "%255s %d %d %d %lld", name, &i1, &i2, &i3, &param);
            rf = load_resource_file(name, i1, i2, rcb(i3),
                                    (intptr_t)(int32_t)param);
            if (nrf < MAXRF)
                rfs[nrf++] = rf;
            printf("L -> %s\n", nm(rf));
        } else if (strcmp(op, "LH") == 0) {
            ResourceFile *rf;

            sscanf(a, "%255s %d %d %d %d %lld", name, &i1, &i2, &i3, &i4,
                   &param);
            rf = load_resource_file_hot(name, i1, i2, i3, rcb(i4),
                                        (intptr_t)(int32_t)param);
            if (nrf < MAXRF)
                rfs[nrf++] = rf;
            printf("LH -> %s\n", nm(rf));
        } else if (strcmp(op, "R") == 0) {
            printf("R -> %d\n", (int)service_resource_loading());
        } else if (strcmp(op, "RC") == 0) {
            printf("RC -> %d\n", (int)is_resource_loading_complete());
        } else if (strcmp(op, "U") == 0) {
            sscanf(a, "%d", &i1);
            unload_resource_file(rf_at(i1));
        } else if (strcmp(op, "N") == 0) {
            sscanf(a, "%d %255s", &i1, name);
            change_filename_for_hot_chunking(rf_at(i1), name);
        } else if (strcmp(op, "FN") == 0) {
            sscanf(a, "%255s", name);
            printf("FN -> %s\n", nm(find_resource_file(name)));
            show = 0;
        } else if (strcmp(op, "FT") == 0) {
            sscanf(a, "%d", &i1);
            printf("FT -> %s\n", nm(find_resource_file_by_type(i1)));
            show = 0;
        } else if (strcmp(op, "GS") == 0 || strcmp(op, "GT") == 0) {
            int32_t count = (int32_t)0xeeeeeeeeu, r;

            sscanf(a, "%d %lld %d", &i1, &id, &i2);
            if (op[1] == 'S')
                r = resource_file_get_size(rf_at(i1), (uint32_t)id,
                                           i2 ? &count : NULL);
            else
                r = get_resource_file_size(i1, (uint32_t)id,
                                           i2 ? &count : NULL);
            printf("%s -> %d %d\n", op, (int)r, (int)count);
            show = 0;
        } else if (strcmp(op, "Q") == 0) {
            uint8_t *buf;
            int32_t h;

            sscanf(a, "%255s %d %d %d %d %lld", name, &i1, &i2, &i3, &i4,
                   &param);
            buf = halloc(i3);
            if (nqb < MAXQB)
                qbufs[nqb++] = buf;
            h = add_queued_file(buf, name, i1, i2, qcb(i4),
                                (intptr_t)(int32_t)param);
            printf("Q -> %d %s\n", (int)h, nm(buf));
        } else if (strcmp(op, "P") == 0) {
            sscanf(a, "%d %d %d", &i1, &i2, &i3);
            change_queued_file_params(i1, i2, i3);
        } else if (strcmp(op, "A") == 0) {
            sscanf(a, "%d", &i1);
            printf("A -> %d\n", (int)abort_queued_file(i1));
        } else if (strcmp(op, "FQ") == 0) {
            sscanf(a, "%d", &i1);
            printf("FQ -> %s\n", nm(find_queued_file(i1)));
            show = 0;
        } else if (strcmp(op, "S") == 0) {
            service_queued_files();
        } else if (strcmp(op, "BQ") == 0) {
            sscanf(a, "%d %d", &i1, &i2);
            if (i1 < 0 || i1 >= nqb)
                return 6;
            printf("BQ -> %s\n", crc(qbufs[i1], i2));
            show = 0;
        } else if (strcmp(op, "H") == 0) {
            ResourceFile *rf;

            sscanf(a, "%d", &i1);
            rf = rf_at(i1);
            rf->pLoadedHotFileEntries = halloc(32);
            rf->NumLoadedHotFileEntries = 3;
            rf->HotFileNumber = 5;
            rf->InventoryHandle = 9;
        } else if (strcmp(op, "Z") == 0) {
            resource_static_destruct();
            queuedfile_static_destruct();
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
