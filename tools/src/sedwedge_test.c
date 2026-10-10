// Harness for tools/sedwedge_check.py: runs the checker's script on
// sedwedge.c and prints what the model prints for the retail image.
// bFile, bMalloc and bFree, the speech library, the chain sample and
// bSound's SetPath are logging fakes, the same fakes the checker gives
// retail's code. See the checker's docstring.
//
//     sedwedge_test script.txt > out.txt

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bfile.h"
#include "bmem.h"
#include "bsound.h"
#include "sedwedge.h"
#include "sound.h"
#include "spch.h"

int32_t SoundEnabled = 1;
int32_t RealTimeFrames;

static uint32_t bits(float f)
{
    uint32_t v;

    memcpy(&v, &f, 4);
    return v;
}

// ------------------------------------------------------------- the objects

#define MAXBLK   512
#define MAXFILE  16
#define MAXOPEN  256
#define MAXQ     64

static SedWedge    W;
static int         fakebsound;
static int         fakeslot;
static SoundModule fakemod;
static BSample     chain;
static SpchExtVecs fakeVecs;
static BSoundCallback cb;
static void       *cbdata;
static SpchRequestFn reqfn;
static int         quietAlloc;
static int         nullGet, noChain;

static struct {
    uint8_t *p;
    int      size;
    char     nm[16];
} blocks[MAXBLK];
static int nblocks;

static struct {
    char    nm[64];
    uint8_t data[512];
    int     size;
    int     missing;
} files[MAXFILE];
static int nfiles;

struct bFile {
    int id;
    int file;
};
static struct bFile handles[MAXOPEN];
static int nhandles;

static int32_t checkQ[MAXQ], resolveQ[MAXQ], handleQ[MAXQ];
static int nCheck, atCheck, nResolve, atResolve, nHandle, atHandle;
static int32_t nextHandle;
static struct { int32_t bank, off, size; } parts[MAXQ];
static int nparts;

static const char *name(const void *p)
{
    static char buf[8][48];
    static int k;
    char *b = buf[k++ & 7];
    const uint8_t *q = (const uint8_t *)p;
    int i;

    if (p == NULL)
        return "0";
    if (p == (const void *)&W)
        return "wedge";
    if (p == (const void *)W.evLogBuffer)
        return "wedge.evlog";
    if (p == (const void *)&chain)
        return "chain";
    if (p == (const void *)&fakeVecs)
        return "vecs";
    if (p == (const void *)&fakebsound)
        return "bsound";
    if (p == (const void *)&fakeslot)
        return "slot";
    for (i = 0; i < nhandles; i++) {
        if (p == (const void *)&handles[i]) {
            sprintf(b, "f%d", i + 1);
            return b;
        }
    }
    for (i = 0; i < nblocks; i++) {
        int n = blocks[i].size > 1 ? blocks[i].size : 1;

        if (q >= blocks[i].p && q < blocks[i].p + n) {
            if (q == blocks[i].p)
                return blocks[i].nm;
            sprintf(b, "%s+%d", blocks[i].nm, (int)(q - blocks[i].p));
            return b;
        }
    }
    return "?";
}

typedef void (*AnyFn)(void);

static const char *fnname(AnyFn f)
{
    if (f == NULL)
        return "0";
    if (f == (AnyFn)sedwedge_abort_message)
        return "abort";
    if (f == (AnyFn)sedwedge_debug_print)
        return "print";
    if (f == (AnyFn)sedwedge_timer_get_tick)
        return "tick";
    if (f == (AnyFn)sedwedge_test_sentence_rule)
        return "test";
    if (f == (AnyFn)sedwedge_set_sentence_rule)
        return "set";
    if (f == (AnyFn)sedwedge_sentence_part_request)
        return "req";
    if (f == (AnyFn)sedwedge_sample_callback)
        return "samplecb";
    if (f == (AnyFn)sedwedge_write_evlog)
        return "evlog";
    return "?";
}

static uint8_t *block(int size, const char **nm)
{
    int n = size > 4 ? size : 4;
    uint8_t *p = malloc((size_t)n + 16);

    memset(p, 0xa5, (size_t)(size > 0 ? size : 0));
    blocks[nblocks].p = p;
    blocks[nblocks].size = size;
    sprintf(blocks[nblocks].nm, "blk%d", nblocks + 1);
    *nm = blocks[nblocks].nm;
    nblocks++;
    return p;
}

// ------------------------------------------------------------- the files

static void add_file(const char *nm, const uint8_t *data, int size)
{
    strcpy(files[nfiles].nm, nm);
    memcpy(files[nfiles].data, data, (size_t)size);
    files[nfiles].size = size;
    nfiles++;
}

static void put32(uint8_t *p, uint32_t v)
{
    memcpy(p, &v, 4);
}

static void ban_file(const char *nm, int nbanks, uint32_t base)
{
    uint8_t b[512];
    int i, k, n = 0;

    for (i = 0; i < nbanks; i++) {
        put32(b + n, i == 0 ? (uint32_t)nbanks : 0x5a5a0000u + (uint32_t)i);
        put32(b + n + 4, (uint32_t)(16 * nbanks + 64 * i));
        put32(b + n + 8, 0);
        put32(b + n + 12, base + 0x1000u * (uint32_t)(i * i));
        n += 16;
    }
    for (i = 0; i < nbanks; i++)
        for (k = 0; k < 64; k++)
            b[n++] = (uint8_t)((i * 7 + k) & 0xff);
    add_file(nm, b, n);
}

static void make_files(void)
{
    static const char *const langs[5] = {
        "English", "French", "German", "Italian", "Spanish",
    };
    uint8_t ev[120], dat[64];
    char nm[64];
    int i;

    for (i = 0; i < 120; i++)
        ev[i] = (uint8_t)(i % 40);
    add_file("Sound\\Speech\\Events.evt", ev, 120);
    memset(dat, 0, sizeof(dat));
    for (i = 0; i < 5; i++) {
        sprintf(nm, "Sound\\Speech\\%sBAN.pck", langs[i]);
        ban_file(nm, 3 + i % 3, 0x100u * (uint32_t)(i + 1));
        sprintf(nm, "Sound\\Speech\\%sDAT.pck", langs[i]);
        add_file(nm, dat, 64);
    }
}

static int find_file(const char *nm)
{
    int i;

    for (i = 0; i < nfiles; i++)
        if (!strcmp(files[i].nm, nm))
            return i;
    return -1;
}

// ------------------------------------------------------------- bFile, bMem

bFile *bOpen(const char *nm)
{
    int i = find_file(nm);
    bFile *h = NULL;

    if (i >= 0 && !files[i].missing) {
        h = &handles[nhandles++];
        h->id = nhandles;
        h->file = i;
    }
    printf("  bopen %s -> %s\n", nm, name(h));
    return h;
}

void bClose(bFile *f)
{
    printf("  bclose %s\n", name(f));
}

int32_t bFileSize(bFile *f)
{
    int32_t n = files[f->file].size;

    printf("  bfilesize %s -> %d\n", name(f), n);
    return n;
}

int32_t bFileSizeName(const char *nm)
{
    int i = find_file(nm);

    return i < 0 || files[i].missing ? -1 : files[i].size;
}

void bRead(bFile *f, void *buf, int32_t n)
{
    int32_t k = n < files[f->file].size ? n : files[f->file].size;

    memcpy(buf, files[f->file].data, (size_t)k);
    printf("  bread %s %s %d\n", name(f), name(buf), n);
}

void *bGetFile(const char *nm, int32_t *size, int32_t pool)
{
    int i = find_file(nm);
    const char *bn;
    uint8_t *p;

    if (nullGet) {
        nullGet = 0;
        printf("  bgetfile %s %s %d -> 0\n", nm, name(size), pool);
        return NULL;
    }
    p = block(files[i].size, &bn);
    memcpy(p, files[i].data, (size_t)files[i].size);
    printf("  bgetfile %s %s %d -> %s\n", nm, name(size), pool, bn);
    return p;
}

void *bMalloc(int size, const char *nm, int flags, int pool)
{
    const char *bn;
    uint8_t *p;

    (void)nm;
    if (quietAlloc) {
        // sedwedge_create's, into the record the ops use; the size is the
        // host's.
        quietAlloc = 0;
        printf("  bmalloc wedge %d %d\n", flags, pool);
        return &W;
    }
    p = block(size, &bn);
    printf("  bmalloc %d %d %d -> %s\n", size, flags, pool, bn);
    return p;
}

void bFree(void *p)
{
    printf("  bfree %s\n", name(p));
}

// -------------------------------------------------------- the speech library

int32_t spch_get_sample_data_rate(int32_t rate, int32_t bitsz, int32_t mode)
{
    printf("  spch_rate %d %d %d\n", rate, bitsz, mode);
    return 4410;
}

int32_t spch_init(SpchRequestFn request, int32_t game, int32_t rate)
{
    reqfn = request;
    printf("  spch_init %s %d %d\n", fnname((AnyFn)request), game, rate);
    return 1;
}

void spch_deinit(void)
{
    printf("  spch_deinit\n");
}

int32_t spch_get_bank_ptr_mem_size(int32_t n)
{
    printf("  spch_memsize %d\n", n);
    return 4 * n;
}

void spch_init_bank_mem(int32_t n, uint8_t **table)
{
    printf("  spch_bankmem %d %s\n", n, name(table));
}

SpchExtVecs *spch_get_ext_vecs(void)
{
    printf("  spch_vecs\n");
    return &fakeVecs;
}

int32_t spch_init_evlog(void *buf, int32_t size, void (*write)(char *, int32_t))
{
    printf("  spch_evlog %s %d %s\n", name(buf), size, fnname((AnyFn)write));
    return 1;
}

void spch_init_rule_callbacks(SpchRuleTestFn test, SpchRuleSetFn set)
{
    printf("  spch_rules %s %s\n", fnname((AnyFn)test), fnname((AnyFn)set));
}

int32_t spch_resolve_data(const uint8_t *dat)
{
    int32_t v = atResolve < nResolve ? resolveQ[atResolve++] : 1;

    printf("  spch_resolve %s -> %d\n", name(dat), v);
    return v;
}

void spch_get_event_dat_info(const uint8_t *dat, uint32_t *a, uint32_t *b)
{
    printf("  spch_datinfo %s\n", name(dat));
    *a = 7;
    *b = 9;
}

int32_t spch_add_bank(uint8_t *bank)
{
    int32_t v = atHandle < nHandle ? handleQ[atHandle++] : nextHandle++;

    printf("  spch_addbank %s -> %d\n", name(bank), v);
    return v;
}

void spch_clear_event_queue(void)
{
    printf("  spch_clear\n");
}

int32_t spch_check_event_queue(int32_t channel)
{
    int32_t v = atCheck < nCheck ? checkQ[atCheck++] : 0;

    printf("  spch_check %d -> %d\n", channel, v);
    return v;
}

int32_t spch_choose(int32_t channel)
{
    printf("  spch_choose %d\n", channel);
    return 1;
}

static void request(int32_t bank, int32_t off, int32_t size)
{
    SpchSampleRequest r;

    r.bank = bank;
    r.offset = off;
    r.size = size;
    r.event = 0x1234;
    r.channel = 0;
    r.subBank = 5;
    r.datId = 6;
    reqfn(&r);
}

int32_t spch_play(int32_t channel)
{
    int n = nparts, i;

    nparts = 0;
    printf("  spch_play %d (%d)\n", channel, n);
    for (i = 0; i < n; i++)
        request(parts[i].bank, parts[i].off, parts[i].size);
    return n;
}

// ------------------------------------------------------ bSample, bSound

BSample *bsample_chain_new(void)
{
    printf("  newchain pool\n");
    if (noChain) {
        noChain = 0;
        return NULL;
    }
    memset(&chain, 0, sizeof(chain));
    cb = NULL;
    cbdata = NULL;
    return &chain;
}

void bsample_set_rate(BSample *s, uint32_t rate)
{
    s->rate = rate;
}

void bsample_set_category(BSample *s, uint32_t category)
{
    printf("  bcat %s %u\n", name(s), category);
}

void bsample_initialize_callback(BSample *s, BSoundCallback fn, void *data)
{
    cb = fn;
    cbdata = data;
    printf("  bcallback %s %s %s\n", name(s), fnname((AnyFn)fn), name(data));
}

void bsample_pause(BSample *s, bool pause)
{
    printf("  bpause %s %d\n", name(s), pause ? 1 : 0);
}

void bsample_stop(BSample *s)
{
    printf("  bstop %s\n", name(s));
    if (s != NULL && cb != NULL)
        cb(8, s, cbdata);
}

BVoice *bsample_play(BSample *s, float volume, float pan, float pitch)
{
    printf("  bplay %s %08x %08x %08x\n", name(s), bits(volume), bits(pan),
           bits(pitch));
    return NULL;
}

void bsample_set_volume(BSample *s, float volume)
{
    printf("  bvol %s %08x\n", name(s), bits(volume));
}

void bsample_chain_add(BSample *s, const char *path, uint32_t offset,
                       uint32_t size, bool start)
{
    printf("  addtochain %s %.32s %08x %08x %d\n", name(s), path, offset, size,
           start ? 1 : 0);
}

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

void bsound_set_path(BSound *s, const char *path)
{
    printf("  setpath %s %s\n", name(s), path);
}

SoundModule *sound_get(void)
{
    return &fakemod;
}

const char *sound_get_path(const SoundModule *m)
{
    (void)m;
    return "sound\\";
}

// --------------------------------------------------------------- the dumps

static void dump(void)
{
    printf("  nd init=%d bank=%s sb=%s count=%d game=%d mem=%s evt=%s "
           "dat=%s name=%.31s vecs=%s segs=%d sample=%s slot=%s status=%d "
           "pause=%d\n",
           W.initialized, name(W.bankFile), name(W.speechBank), W.bankCount,
           W.gameNumber, name(W.bankMem), name(W.eventData),
           name(W.dataPackFile), W.dataPackFileName, name(W.extVecs),
           W.segmentCount, name(W.sentenceSample), name(W.slot), W.status,
           W.pauseState);
    if (W.extVecs == &fakeVecs)
        printf("  vecs %s %s %s\n", fnname((AnyFn)fakeVecs.abort),
               fnname((AnyFn)fakeVecs.print), fnname((AnyFn)fakeVecs.gettick));
    if (W.sentenceSample == &chain)
        printf("  rate %u\n", chain.rate);
}

static void dump_segs(void)
{
    int i;

    for (i = 0; i < SEDWEDGE_SEGMENTS; i++) {
        const BSegment *s = W.segment[i];
        const char *nm = name(s);

        if (!strncmp(nm, "blk", 3) && strchr(nm, '+') == NULL)
            printf("  seg%d %s %.255s init=%d off=%08x size=%08x %u %u\n", i,
                   nm, s->name, s->initialized, s->offset, s->size,
                   s->field268, s->flags);
        else
            printf("  seg%d %s\n", i, nm);
    }
}

static void dump_bank(void)
{
    int i, k;

    if (W.speechBank == NULL || strncmp(name(W.speechBank), "blk", 3)) {
        printf("  bank none\n");
        return;
    }
    for (i = 0; i < W.bankCount && i < 8; i++) {
        printf("  bank%d", i);
        for (k = 0; k < 4; k++) {
            uint32_t v;

            memcpy(&v, W.speechBank + 16 * i + 4 * k, 4);
            printf(" %08x", v);
        }
        printf("\n");
    }
}

// ------------------------------------------------------------- the ops

static void slashes(char *s)
{
    for (; *s; s++)
        if (*s == '/')
            *s = '\\';
}

static void set_missing(char *nm, int missing)
{
    int i;

    slashes(nm);
    i = find_file(nm);
    if (i >= 0)
        files[i].missing = missing;
}

static void op(char **f, int nf)
{
#define I(k) ((k) < nf ? (int32_t)strtoll(f[k], NULL, 0) : 0)
#define FL(k) ((k) < nf ? (float)atof(f[k]) : 1.0f)
    const char *o = f[0];

    if (!strcmp(o, "fill")) {
        memset(&W, 0xa5, sizeof(W));
    } else if (!strcmp(o, "ctor")) {
        sedwedge_construct(&W);
    } else if (!strcmp(o, "create")) {
        quietAlloc = 1;
        sedwedge_create();
    } else if (!strcmp(o, "nd")) {
        dump();
    } else if (!strcmp(o, "segs")) {
        dump_segs();
    } else if (!strcmp(o, "bank")) {
        dump_bank();
    } else if (!strcmp(o, "init")) {
        int k;

        for (k = 1; k < 5 && k < nf; k++)
            slashes(f[k]);
        printf("  = %d\n", sedwedge_initialize(&W, f[1], f[2], f[3], f[4],
                                               &fakeslot));
    } else if (!strcmp(o, "load")) {
        sedwedge_load_localized_speech_files(I(1));
    } else if (!strcmp(o, "unload")) {
        sedwedge_unload_localized_speech_files();
    } else if (!strcmp(o, "loaddata")) {
        uint8_t *out = NULL;
        int32_t v;

        slashes(f[1]);
        v = sedwedge_load_data_file(&W, f[1], &out);
        printf("  = %d %s\n", v, name(out));
    } else if (!strcmp(o, "part")) {
        sedwedge_add_sentence_part(&W, I(1), (uint32_t)I(2), (uint32_t)I(3));
    } else if (!strcmp(o, "req")) {
        request(I(1), I(2), I(3));
    } else if (!strcmp(o, "cleanup")) {
        sedwedge_cleanup(&W);
    } else if (!strcmp(o, "clear")) {
        printf("  = %d\n", sedwedge_clear_event_queue(&W));
    } else if (!strcmp(o, "update")) {
        sedwedge_update(&W);
    } else if (!strcmp(o, "fade")) {
        sedwedge_fade(&W, FL(1));
    } else if (!strcmp(o, "mute")) {
        sedwedge_mute(&W, I(1) != 0);
    } else if (!strcmp(o, "pending")) {
        printf("  = %d\n", sedwedge_get_event_pending(&W, I(1)));
    } else if (!strcmp(o, "queue")) {
        printf("  = %d\n", sedwedge_queue_sentence_event(&W, I(1)));
    } else if (!strcmp(o, "stop")) {
        printf("  = %d\n", sedwedge_stop_sentence(&W, I(1)));
    } else if (!strcmp(o, "play")) {
        printf("  = %d\n", sedwedge_play_sentence(&W, I(1), FL(2)));
    } else if (!strcmp(o, "tick")) {
        printf("  tick %d\n", (int32_t)sedwedge_timer_get_tick());
    } else if (!strcmp(o, "cb")) {
        sedwedge_sample_callback((uint32_t)I(1), &chain, &W);
    } else if (!strcmp(o, "poke")) {
        int32_t v = I(2);

        if (!strcmp(f[1], "init"))
            W.initialized = v;
        else if (!strcmp(f[1], "segs"))
            W.segmentCount = v;
        else if (!strcmp(f[1], "status"))
            W.status = v;
        else if (!strcmp(f[1], "pause"))
            W.pauseState = v;
        else
            W.bankCount = v;
    } else if (!strcmp(o, "sound")) {
        SoundEnabled = I(1);
    } else if (!strcmp(o, "speech")) {
        fakemod.speechEnabled = I(1);
    } else if (!strcmp(o, "frames")) {
        RealTimeFrames = I(1);
    } else if (!strcmp(o, "missing")) {
        set_missing(f[1], 1);
    } else if (!strcmp(o, "present")) {
        set_missing(f[1], 0);
    } else if (!strcmp(o, "check")) {
        checkQ[nCheck++] = I(1);
    } else if (!strcmp(o, "resolve")) {
        resolveQ[nResolve++] = I(1);
    } else if (!strcmp(o, "handle")) {
        handleQ[nHandle++] = I(1);
    } else if (!strcmp(o, "spchpart")) {
        parts[nparts].bank = I(1);
        parts[nparts].off = I(2);
        parts[nparts].size = I(3);
        nparts++;
    } else if (!strcmp(o, "segclean")) {
        bsegment_cleanup(W.segment[I(1)]);
    } else if (!strcmp(o, "rule")) {
        int32_t v = sedwedge_test_sentence_rule(NULL, I(1), I(2), I(3));

        sedwedge_set_sentence_rule(NULL, I(1), I(2), I(3));
        printf("  rule %d\n", v);
    } else if (!strcmp(o, "nullget")) {
        nullGet = 1;
    } else if (!strcmp(o, "nochain")) {
        noChain = 1;
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef FL
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *fh;

    if (argc < 2) {
        fprintf(stderr, "usage: sedwedge_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    make_files();
    fakemod.speechEnabled = 1;
    while (fgets(line, sizeof(line), fh)) {
        char *f[32];
        int nf = 0;
        char *p;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0] || line[0] == '#')
            continue;
        printf("> %s\n", line);
        p = line;
        f[nf++] = p;
        while ((p = strchr(p, '|')) != NULL && nf < 32) {
            *p++ = 0;
            f[nf++] = p;
        }
        op(f, nf);
        fflush(stdout);
    }
    fclose(fh);
    return 0;
}
