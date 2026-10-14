// bsound_test -- tools/bsound_check.py's harness.
//
// Runs bsound.c over the checker's script, on a fake bSnd driver defined
// here, and prints what the model prints for retail's bSample, bRegion,
// bVoiceMgr and bSound over the same fake. Every driver call is a line;
// after each op that can change anything, the state follows: the bSound,
// the voice records, the regions and every live sample's fields.
//
// Samples print as S<slot> (the samples' pool), samples built on the
// script's own storage as L<handle>, regions as R<slot>, voice records as
// V<index>, callbacks as A, B (a sample's) or C (the client's).
//
// "nodriver" is the port's own boot, with no driver (no ndsp): a run the
// model has no part in, checked for making no driver call at all.
//
//     bsound_test script.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bslotpool.h"
#include "bsound.h"

#define MAXH 64

// ------------------------------------------------------------ the fake bSnd

#define MAXCH 48

typedef struct {
    char     name[40];
    unsigned ch;
    uint32_t pitch;
    uint16_t vol;
} FPatch;

typedef struct {
    char   name[48];
    int    lazy, loaded, n;
    FPatch p[8];
} FBank;

static unsigned gN = 24;
static int gLock[MAXCH], gBusy[MAXCH], gWidth[MAXCH], gNear[MAXCH];
static uint16_t gVol[MAXCH];
static FBank gBank[12];
static int gBanks;
static char gPatchName[64];

static FBank* fbank(const char* name)
{
    int i;

    for (i = 0; i < gBanks; i++)
        if (strcmp(gBank[i].name, name) == 0)
            return &gBank[i];
    return NULL;
}

static const FPatch* fpatch(const char* bank, const char* patch)
{
    FBank* b = fbank(bank);
    int i;

    if (b == NULL || !b->loaded)
        return NULL;
    for (i = 0; i < b->n; i++)
        if (strcmp(b->p[i].name, patch) == 0)
            return &b->p[i];
    return NULL;
}

uint16_t bsnd_patch_id(const BsndDriver* d, const char* bank,
                       const char* patch)
{
    FBank* b = fbank(bank);
    uint16_t r = 0xfffa;
    int i;

    (void)d;
    if (b != NULL && b->loaded)
        for (i = 0; i < b->n; i++)
            if (strcmp(b->p[i].name, patch) == 0) {
                r = (uint16_t)(0x100 * (b - gBank) + i);
                break;
            }
    printf("  snd patchid %s %s -> %04x\n", bank, patch, r);
    return r;
}

uint16_t bsnd_lock_channels(BsndDriver* d, uint16_t count)
{
    int first, c, r = 0xfffc;

    (void)d;
    if (count != 0)
        for (first = (int)gN - (int)count; first >= 0; first--) {
            int ok = 1;

            for (c = first; c < first + count; c++)
                if (gLock[c] || gBusy[c])
                    ok = 0;
            if (ok) {
                for (c = first; c < first + count; c++)
                    gLock[c] = 1;
                r = first;
                break;
            }
        }
    printf("  snd lock %u -> %d\n", count, r);
    return (uint16_t)r;
}

void bsnd_unlock_channels(BsndDriver* d, uint16_t first, uint16_t count)
{
    unsigned c;

    (void)d;
    for (c = first; c < (unsigned)first + count; c++)
        if (c < gN)
            gLock[c] = 0;
    printf("  snd unlock %u %u\n", first, count);
}

void bsnd_set_voice_pan(BsndDriver* d, uint16_t voice, int8_t pan)
{
    (void)d;
    printf("  snd pan %u %d\n", voice, pan);
}

void bsnd_set_voice_pitch(BsndDriver* d, uint16_t voice, uint32_t hz)
{
    (void)d;
    printf("  snd pitch %u %u\n", voice, hz);
}

void bsnd_set_voice_volume(BsndDriver* d, uint16_t voice, uint16_t volume)
{
    (void)d;
    if (voice < gN)
        gVol[voice] = volume;
    printf("  snd vol %u %u\n", voice, volume);
}

uint16_t bsnd_get_voice_volume(const BsndDriver* d, uint16_t voice)
{
    uint16_t r = voice < gN ? gVol[voice] : 0;

    (void)d;
    printf("  snd getvol %u -> %u\n", voice, r);
    return r;
}

void bsnd_set_voice_azimuth(BsndDriver* d, uint16_t voice, uint16_t azimuth)
{
    (void)d;
    printf("  snd az %u %u\n", voice, azimuth);
}

uint16_t bsnd_voice_play_pan(BsndDriver* d, const char* bank,
                             const char* patch, uint32_t rate,
                             uint16_t volume, int8_t pan, uint16_t voice)
{
    const FPatch* p = fpatch(bank, patch);
    uint16_t r = 0xfffe;

    (void)d;
    printf("  snd play %s %s %u %u %d %u\n", bank, patch, rate, volume, pan,
           voice);
    if (p != NULL && voice < gN) {
        unsigned c;

        gWidth[voice] = (int)p->ch;
        for (c = voice; c < voice + p->ch && c < gN; c++)
            gBusy[c] = 1;
        gVol[voice] = volume;
        r = voice;
    }
    return r;
}

uint16_t bsnd_voice_play_part(BsndDriver* d, const char* bank,
                              const char* patch, uint32_t rate,
                              uint16_t volume, int8_t pan, uint32_t offset,
                              uint32_t size, uint16_t voice)
{
    const FPatch* p;
    uint16_t r = 0xfffe;
    char vs[16];

    (void)d;
    if (voice == BSND_VOICE_ALLOC)
        snprintf(vs, sizeof(vs), "alloc");
    else
        snprintf(vs, sizeof(vs), "%u", voice);
    printf("  snd playpart %s %s %u %u %d %u %u %s\n", bank, patch, rate,
           volume, pan, offset, size, vs);
    if (strcmp(bank, "_CHAIN") == 0)
        return voice;
    p = fpatch(bank, patch);
    if (p != NULL && voice < gN) {
        unsigned c;

        gWidth[voice] = (int)p->ch;
        for (c = voice; c < voice + p->ch && c < gN; c++)
            gBusy[c] = 1;
        gVol[voice] = volume;
        r = voice;
    }
    return r;
}

void bsnd_voice_stop(BsndDriver* d, uint16_t voice)
{
    (void)d;
    printf("  snd stop %u\n", voice);
    if (voice < gN) {
        unsigned c;

        for (c = voice; c < voice + (unsigned)gWidth[voice] && c < gN; c++)
            gBusy[c] = 0;
    }
}

void bsnd_voice_pause(BsndDriver* d, uint16_t voice)
{
    (void)d;
    printf("  snd pause %u\n", voice);
}

void bsnd_voice_resume(BsndDriver* d, uint16_t voice)
{
    (void)d;
    printf("  snd resume %u\n", voice);
}

bool bsnd_channel_busy(const BsndDriver* d, uint16_t voice)
{
    int r = voice < gN ? gBusy[voice] : 0;

    (void)d;
    printf("  snd busy %u -> %d\n", voice, r);
    return r != 0;
}

bool bsnd_stream_active(const BsndDriver* d, uint16_t voice)
{
    int r = voice < gN ? gNear[voice] : 0;

    (void)d;
    printf("  snd near %u -> %d\n", voice, r);
    return r != 0;
}

uint32_t bsnd_get_patch_pitch(const BsndDriver* d, const char* bank,
                              const char* patch)
{
    const FPatch* p = fpatch(bank, patch);
    uint32_t r = p != NULL ? p->pitch : 0;

    (void)d;
    printf("  snd ppitch %s %s -> %u\n", bank, patch, r);
    return r;
}

uint16_t bsnd_get_patch_volume(const BsndDriver* d, const char* bank,
                               const char* patch)
{
    const FPatch* p = fpatch(bank, patch);
    uint16_t r = p != NULL ? p->vol : 0;

    (void)d;
    printf("  snd pvol %s %s -> %u\n", bank, patch, r);
    return r;
}

unsigned bsnd_get_patch_channels(const BsndDriver* d, const char* bank,
                                 const char* patch)
{
    const FPatch* p = fpatch(bank, patch);
    unsigned r = p != NULL ? p->ch : 0;

    (void)d;
    printf("  snd pch %s %s -> %u\n", bank, patch, r);
    return r;
}

uint16_t bsnd_bank_number(const BsndDriver* d, const char* name)
{
    FBank* b = fbank(name);
    uint16_t r = (b != NULL && b->loaded) ? (uint16_t)(b - gBank) : 0xffff;

    (void)d;
    printf("  snd banknum %s -> %u\n", name, r);
    return r;
}

unsigned bsnd_bank_patch_count(const BsndDriver* d, uint16_t bank)
{
    unsigned r = (bank < gBanks && gBank[bank].loaded) ? gBank[bank].n : 0;

    (void)d;
    printf("  snd npatch %u -> %u\n", bank, r);
    return r;
}

const char* bsnd_bank_patch_name(const BsndDriver* d, uint16_t bank,
                                 unsigned k)
{
    (void)d;
    if (bank < gBanks && gBank[bank].loaded && k < (unsigned)gBank[bank].n) {
        strcpy(gPatchName, gBank[bank].p[k].name);
        printf("  snd pname %u %u -> %s\n", bank, k, gPatchName);
        return gPatchName;
    }
    printf("  snd pname %u %u -> 0\n", bank, k);
    return NULL;
}

bool bsnd_bank_load(BsndDriver* d, const char* name)
{
    FBank* b = fbank(name);
    int r = b != NULL;

    (void)d;
    if (b != NULL && !b->lazy)
        b->loaded = 1;
    printf("  snd bankload %s -> %d\n", name, r);
    return r != 0;
}

bool bsnd_bank_loaded(const BsndDriver* d, const char* name)
{
    FBank* b = fbank(name);
    int r = b != NULL && b->loaded;

    (void)d;
    printf("  snd isloaded %s -> %d\n", name, r);
    return r != 0;
}

bool bsnd_bank_unload(BsndDriver* d, const char* name)
{
    FBank* b = fbank(name);

    (void)d;
    if (b != NULL)
        b->loaded = 0;
    printf("  snd unload %s\n", name);
    return true;
}

void bsnd_update(BsndDriver* d)
{
    (void)d;
    printf("  snd update\n");
}

void bsnd_set_load_path(BsndDriver* d, const char* path)
{
    (void)d;
    printf("  snd path %s\n", path);
}

void bsnd_set_mode(BsndDriver* d, uint8_t mode)
{
    (void)d;
    printf("  snd mode %u\n", mode);
}

// ------------------------------------------------------------- the callbacks

static void cb_print(const char* who, uint32_t event, void* what, void* data);

static void cbA(uint32_t event, void* what, void* data)
{
    cb_print("A", event, what, data);
}

static void cbB(uint32_t event, void* what, void* data)
{
    cb_print("B", event, what, data);
}

static void cbC(uint32_t event, void* what, void* data)
{
    cb_print("C", event, what, data);
}

static BSoundCallback cb_of(const char* s)
{
    if (strcmp(s, "A") == 0)
        return cbA;
    if (strcmp(s, "B") == 0)
        return cbB;
    if (strcmp(s, "C") == 0)
        return cbC;
    return NULL;
}

static const char* cb_name(BSoundCallback cb)
{
    if (cb == NULL)
        return "0";
    if (cb == cbA)
        return "A";
    if (cb == cbB)
        return "B";
    if (cb == cbC)
        return "C";
    return "?";
}

// ------------------------------------------------------------------- labels

static BSound gSound;
static BsndDriver gDrv;
static BSample* gH[MAXH];
static int gLocal[MAXH];
static char gFrom[MAXH][48];

static const char* slabel(const BSample* s)
{
    static char buf[8][16];
    static int b;
    char* o = buf[b++ & 7];
    BSlotPool* pool = bsound_sample_pool();
    int h;

    if (s == NULL)
        return "0";
    for (h = 0; h < MAXH; h++)
        if (gLocal[h] && gH[h] == s) {
            snprintf(o, 16, "L%d", h);
            return o;
        }
    if (pool != NULL) {
        int n = bGetSlotNumber(pool, s);

        if (n >= 0 && n < 255) {
            snprintf(o, 16, "S%d", n);
            return o;
        }
    }
    return "?";
}

static const char* rlabel(const BRegion* r)
{
    static char buf[8][16];
    static int b;
    char* o = buf[b++ & 7];
    BSlotPool* pool = bsound_region_pool();

    if (r == NULL)
        return "0";
    if (pool != NULL) {
        int n = bGetSlotNumber(pool, r);

        if (n >= 0 && n < 32) {
            snprintf(o, 16, "R%d", n);
            return o;
        }
    }
    return "?";
}

static const char* vlabel(const BVoice* v)
{
    static char buf[4][16];
    static int b;
    char* o = buf[b++ & 3];

    if (v == NULL)
        return "0";
    snprintf(o, 16, "V%d", (int)(v - bsound_voices()));
    return o;
}

static void cb_print(const char* who, uint32_t event, void* what, void* data)
{
    printf("  cb %s ev=%u what=%s data=%08x\n", who, event,
           event == BSOUND_REGION_LOADED ? rlabel((BRegion*)what)
                                         : slabel((BSample*)what),
           (uint32_t)(uintptr_t)data);
}

static uint32_t fbits(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

static float bitsf(const char* s)
{
    uint32_t u = (uint32_t)strtoul(s, NULL, 0);
    float f;

    memcpy(&f, &u, 4);
    return f;
}

// ------------------------------------------------------------------ the dump

static void dump_sample(const BSample* s)
{
    printf("  %s v=%s r=%08x ne=%d f8=%d off=%u sz=%u cv=%08x sc=%08x "
           "ft=%08x fa=%08x pn=%08x pt=%08x cb=%s cd=%08x n='%.32s' "
           "b='%.32s' vm=%04x mu=%d pa=%d ca=%u ty=%d lk=%d lp=%d id=%04x\n",
           slabel(s), vlabel(s->voice), s->rate, s->nearEndNotified,
           s->field8, s->offset, s->size, fbits(s->currentVolume),
           fbits(s->scaleVolume), fbits(s->fadeTarget), fbits(s->fadeAdjust),
           fbits(s->currentPan), fbits(s->currentPitch),
           cb_name(s->callback), (uint32_t)(uintptr_t)s->callbackData,
           s->name, s->bankName, s->volumeBeforeMuting, s->muted, s->paused,
           s->category, s->type, s->voiceLock, s->voiceLockPlaying,
           s->sampleId);
}

static void dump(void)
{
    const BVoice* v = bsound_voices();
    int i, j, h;
    static int seen[255];

    printf("  snd st=%d com=%s pend=%d '%.255s' path='%.64s'\n",
           gSound.status, rlabel(gSound.common), gSound.pendingCount,
           gSound.pending[0], gSound.path);
    printf("  cat");
    for (i = 0; i < 16; i++)
        printf(" %08x", fbits(gSound.categoryVolume[i]));
    printf("\n  vo");
    for (i = 0; i < BVOICE_COUNT; i++)
        if (v[i].sample != NULL || v[i].id != 0)
            printf(" %d:%u:%s", i, v[i].id, slabel(v[i].sample));
    printf("\n");

    memset(seen, 0, sizeof(seen));
    for (i = 0; i < bsound_region_count(&gSound); i++) {
        BRegion* r = bsound_region_at(&gSound, i);

        printf("  region %s '%.33s'", rlabel(r), bregion_name(r));
        for (j = 0; j < bregion_sample_count(r); j++) {
            BSample* s = bregion_sample_at(r, j);
            const char* l = slabel(s);

            printf(" %s", l);
            if (l[0] == 'S')
                seen[atoi(l + 1)] = 1;
        }
        printf("\n");
    }
    for (h = 0; h < MAXH; h++) {
        if (gH[h] == NULL)
            continue;
        if (gLocal[h])
            dump_sample(gH[h]);
        else {
            const char* l = slabel(gH[h]);

            if (l[0] == 'S')
                seen[atoi(l + 1)] = 1;
        }
    }
    {
        BSlotPool* pool = bsound_sample_pool();

        for (i = 0; i < 255; i++)
            if (seen[i] && pool != NULL)
                dump_sample((BSample*)bGetSlot(pool, i));
    }
}

// ------------------------------------------------------------------- the ops

static int split(char* line, char** a, int max)
{
    int n = 0;
    char* p = line;

    while (n < max) {
        a[n++] = p;
        p = strchr(p, '|');
        if (p == NULL)
            break;
        *p++ = '\0';
    }
    return n;
}

static void bank_decl(char** a, int n)
{
    // bank|NAME|lazy|patch:ch:pitch:vol|...
    FBank* b = &gBank[gBanks++];
    int i;

    memset(b, 0, sizeof(*b));
    snprintf(b->name, sizeof(b->name), "%s", a[1]);
    b->lazy = atoi(a[2]);
    for (i = 3; i < n && b->n < 8; i++) {
        FPatch* p = &b->p[b->n++];
        char* f[4];
        int k = 0;
        char* q = a[i];

        while (k < 4) {
            f[k++] = q;
            q = strchr(q, ':');
            if (q == NULL)
                break;
            *q++ = '\0';
        }
        snprintf(p->name, sizeof(p->name), "%s", f[0]);
        p->ch = (unsigned)strtoul(f[1], NULL, 0);
        p->pitch = (uint32_t)strtoul(f[2], NULL, 0);
        p->vol = (uint16_t)strtoul(f[3], NULL, 0);
    }
}

static int run(char** a, int n)
{
    const char* o = a[0];
    BSample* s = NULL;
    int h = -1;

    if (n > 1 && strcmp(o, "bank") && strcmp(o, "load") && strcmp(o, "unload")
        && strcmp(o, "region") && strcmp(o, "arrive") && strcmp(o, "end")
        && strcmp(o, "near") && strcmp(o, "voices") && strcmp(o, "catvol")
        && strcmp(o, "getcatvol") && strcmp(o, "mode") && strcmp(o, "path")
        && strcmp(o, "boot") && strcmp(o, "nodriver") && strcmp(o, "chvol")) {
        h = atoi(a[1]);
        s = gH[h];
    }

    if (strcmp(o, "voices") == 0) {
        gN = (unsigned)atoi(a[1]);
        return 0;
    }
    if (strcmp(o, "bank") == 0) {
        bank_decl(a, n);
        return 0;
    }
    if (strcmp(o, "arrive") == 0) {
        FBank* b = fbank(a[1]);

        if (b != NULL)
            b->loaded = 1;
        printf("arrive %s\n", a[1]);
        return 1;
    }
    if (strcmp(o, "end") == 0) {
        gBusy[atoi(a[1])] = 0;
        printf("end %s\n", a[1]);
        return 1;
    }
    if (strcmp(o, "near") == 0) {
        gNear[atoi(a[1])] = atoi(a[2]);
        printf("near %s %s\n", a[1], a[2]);
        return 0;
    }
    if (strcmp(o, "chvol") == 0) {
        // Every channel's volume, as the driver would answer GetVolume.
        int c;

        for (c = 0; c < MAXCH; c++)
            gVol[c] = (uint16_t)strtoul(a[1], NULL, 0);
        printf("chvol %s\n", a[1]);
        return 0;
    }
    if (strcmp(o, "boot") == 0) {
        printf("boot %s %s\n", a[1], a[2]);
        bsound_init(&gSound, &gDrv, cb_of(a[1]),
                    (void*)(uintptr_t)strtoul(a[2], NULL, 0));
        return 1;
    }
    if (strcmp(o, "nodriver") == 0) {
        // The port's: no ndsp, so no driver (main.c's NULL). Every fake
        // call above prints a "  snd " line; after this there must be none.
        printf("nodriver %s %s\n", a[1], a[2]);
        bsound_init(&gSound, NULL, cb_of(a[1]),
                    (void*)(uintptr_t)strtoul(a[2], NULL, 0));
        return 1;
    }
    if (strcmp(o, "load") == 0) {
        printf("load %s\n", a[1]);
        printf("  -> %d\n", bsound_load_region(&gSound, a[1]));
        return 1;
    }
    if (strcmp(o, "update") == 0) {
        printf("update\n");
        bsound_update(&gSound);
        return 1;
    }
    if (strcmp(o, "unload") == 0) {
        int k;

        printf("unload %s\n", a[1]);
        if (bsound_region(&gSound, a[1]) != NULL)
            for (k = 0; k < MAXH; k++)
                if (!gLocal[k] && strcmp(gFrom[k], a[1]) == 0)
                    gH[k] = NULL;
        bsound_unload_region(&gSound, a[1]);
        return 1;
    }
    if (strcmp(o, "region") == 0) {
        printf("region %s -> %s\n", a[1], rlabel(bsound_region(&gSound, a[1])));
        return 0;
    }
    if (strcmp(o, "common") == 0) {
        printf("common -> %s\n", rlabel(bsound_common_region(&gSound)));
        return 0;
    }
    if (strcmp(o, "catvol") == 0) {
        printf("catvol %s %s\n", a[1], a[2]);
        bsound_set_category_volume(&gSound, (uint32_t)strtoul(a[1], NULL, 0),
                                   bitsf(a[2]));
        return 1;
    }
    if (strcmp(o, "getcatvol") == 0) {
        printf("getcatvol %s -> %08x\n", a[1],
               fbits(bsound_get_category_volume(
                   &gSound, (uint32_t)strtoul(a[1], NULL, 0))));
        return 0;
    }
    if (strcmp(o, "mode") == 0) {
        printf("mode %s\n", a[1]);
        bsound_set_mode(&gSound, atoi(a[1]));
        return 1;
    }
    if (strcmp(o, "path") == 0) {
        printf("path %s\n", a[1]);
        bsound_set_path(&gSound, a[1]);
        return 1;
    }
    if (strcmp(o, "status") == 0) {
        printf("status -> %d\n", bsound_get_status(&gSound));
        return 0;
    }

    // -- the ops on a handle
    if (strcmp(o, "chainnew") == 0) {
        gH[h] = bsample_chain_new();
        gLocal[h] = 0;
        gFrom[h][0] = '\0';
        printf("chainnew %d -> %s\n", h, slabel(gH[h]));
        return 1;
    }
    if (strcmp(o, "new") == 0) {
        gH[h] = bsample_new((int8_t)atoi(a[2]));
        gLocal[h] = 0;
        gFrom[h][0] = '\0';
        printf("new %d %s -> %s\n", h, a[2], slabel(gH[h]));
        return 1;
    }
    if (strcmp(o, "local") == 0) {
        BSample* m = (BSample*)malloc(sizeof(BSample));

        memset(m, 0xa5, sizeof(BSample));
        gH[h] = m;
        gLocal[h] = 1;
        gFrom[h][0] = '\0';
        bsample_construct(m, (int8_t)atoi(a[2]));
        printf("local %d %s\n", h, a[2]);
        return 1;
    }
    if (strcmp(o, "get") == 0) {
        BRegion* r = bsound_region(&gSound, a[2]);

        gH[h] = r != NULL ? bregion_sample(r, a[3]) : NULL;
        gLocal[h] = 0;
        snprintf(gFrom[h], sizeof(gFrom[h]), "%s", a[2]);
        printf("get %d %s %s -> %s\n", h, a[2], a[3], slabel(gH[h]));
        return 0;
    }
    if (strcmp(o, "at") == 0) {
        BRegion* r = bsound_region(&gSound, a[2]);
        int i = atoi(a[3]);

        gH[h] = (r != NULL && i < bregion_sample_count(r))
              ? bregion_sample_at(r, i) : NULL;
        gLocal[h] = 0;
        snprintf(gFrom[h], sizeof(gFrom[h]), "%s", a[2]);
        printf("at %d %s %d -> %s\n", h, a[2], i, slabel(gH[h]));
        return 0;
    }
    printf("%s %s", o, slabel(s));
    {
        int i;

        for (i = 2; i < n; i++)
            printf(" %s", a[i]);
    }
    printf("\n");
    // A handle whose sample went with its region, or that found none.
    if (s == NULL)
        return 0;
    if (strcmp(o, "delete") == 0) {
        // A local's storage is kept: a locked voice can still point at it,
        // as it can at a pool slot that was given back.
        if (gLocal[h]) {
            bsample_destruct(s);
        } else {
            bsample_delete(s);
        }
        gH[h] = NULL;
        return 1;
    }
    if (strcmp(o, "init") == 0) {
        bsample_initialize(s, a[2], a[3]);
        return 1;
    }
    if (strcmp(o, "initcopy") == 0) {
        bsample_initialize_copy(s, gH[atoi(a[2])]);
        return 1;
    }
    if (strcmp(o, "initcb") == 0) {
        bsample_initialize_callback(s, cb_of(a[2]),
                                    (void*)(uintptr_t)strtoul(a[3], NULL, 0));
        return 1;
    }
    if (strcmp(o, "setcb") == 0) {
        bsample_set_callback(s, cb_of(a[2]),
                             (void*)(uintptr_t)strtoul(a[3], NULL, 0));
        return 1;
    }
    if (strcmp(o, "setname") == 0) {
        bsample_set_name(s, a[2]);
        return 1;
    }
    if (strcmp(o, "setbank") == 0) {
        bsample_set_bank_name(s, a[2]);
        return 1;
    }
    if (strcmp(o, "setrate") == 0) {
        bsample_set_rate(s, (uint32_t)strtoul(a[2], NULL, 0));
        return 1;
    }
    if (strcmp(o, "chain") == 0) {
        bsample_chain_add(s, a[2], (uint32_t)strtoul(a[3], NULL, 0),
                          (uint32_t)strtoul(a[4], NULL, 0), atoi(a[5]) != 0);
        return 1;
    }
    if (strcmp(o, "lockvoice") == 0) {
        bsample_lock_voice(s);
        return 1;
    }
    if (strcmp(o, "play") == 0) {
        printf("  -> %s\n", vlabel(bsample_play(s, bitsf(a[2]), bitsf(a[3]),
                                                bitsf(a[4]))));
        return 1;
    }
    if (strcmp(o, "playn") == 0) {
        printf("  -> %s\n", vlabel(bsample_play_named(
                                s, a[2], (uint32_t)strtoul(a[3], NULL, 0),
                                (uint32_t)strtoul(a[4], NULL, 0))));
        return 1;
    }
    if (strcmp(o, "stop") == 0) {
        bsample_stop(s);
        return 1;
    }
    if (strcmp(o, "pause") == 0) {
        bsample_pause(s, atoi(a[2]) != 0);
        return 1;
    }
    if (strcmp(o, "mute") == 0) {
        bsample_mute(s, atoi(a[2]) != 0);
        return 1;
    }
    if (strcmp(o, "fade") == 0) {
        bsample_fade(s, bitsf(a[2]), (uint32_t)strtoul(a[3], NULL, 0));
        return 1;
    }
    if (strcmp(o, "setvol") == 0) {
        bsample_set_volume(s, bitsf(a[2]));
        return 1;
    }
    if (strcmp(o, "setscale") == 0) {
        bsample_set_scale_volume(s, bitsf(a[2]));
        return 1;
    }
    if (strcmp(o, "setpan") == 0) {
        bsample_set_pan(s, bitsf(a[2]));
        return 1;
    }
    if (strcmp(o, "setpitch") == 0) {
        printf("  -> %d\n", bsample_set_pitch(s, bitsf(a[2])));
        return 1;
    }
    if (strcmp(o, "setaz") == 0) {
        bsample_set_azimuth(s, (uint16_t)strtoul(a[2], NULL, 0));
        return 1;
    }
    if (strcmp(o, "cat") == 0) {
        bsample_set_category(s, (uint32_t)strtoul(a[2], NULL, 0));
        return 1;
    }
    if (strcmp(o, "supdate") == 0) {
        bsample_update(s);
        return 1;
    }
    if (strcmp(o, "calcpitch") == 0) {
        printf("  -> %u\n", bsample_calc_pitch(s, bitsf(a[2])));
        return 0;
    }
    if (strcmp(o, "calcvol") == 0) {
        printf("  -> %u\n", bsample_calc_volume(s, bitsf(a[2])));
        return 0;
    }
    if (strcmp(o, "calcpan") == 0) {
        printf("  -> %d\n", bsample_calc_pan(s, bitsf(a[2])));
        return 0;
    }
    if (strcmp(o, "scaled") == 0) {
        printf("  -> %08x\n", fbits(bsample_get_scaled_volume(s)));
        return 0;
    }
    if (strcmp(o, "getvol") == 0) {
        printf("  -> %08x\n", fbits(bsample_get_volume(s)));
        return 0;
    }
    if (strcmp(o, "getpitch") == 0) {
        printf("  -> %08x\n", fbits(bsample_get_pitch(s)));
        return 0;
    }
    if (strcmp(o, "isplaying") == 0) {
        printf("  -> %d\n", bsample_is_playing(s) ? 1 : 0);
        return 0;
    }
    if (strcmp(o, "channels") == 0) {
        printf("  -> %u\n", bsample_get_channels(s));
        return 0;
    }
    if (strcmp(o, "find") == 0) {
        BRegion* r = bsound_region(&gSound, a[2]);

        printf("  -> %s\n", slabel(r != NULL ? bregion_sample(r, a[3]) : NULL));
        return 0;
    }
    fprintf(stderr, "unknown op %s\n", o);
    exit(2);
}

int main(int argc, char** argv)
{
    static char line[4096];
    FILE* f;

    if (argc != 2) {
        fprintf(stderr, "usage: bsound_test script.txt\n");
        return 2;
    }
    f = fopen(argv[1], "r");
    if (f == NULL) {
        perror(argv[1]);
        return 2;
    }
    bSlotPoolManagerInit();
    while (fgets(line, sizeof(line), f) != NULL) {
        char* a[16];
        size_t len = strlen(line);
        int n;

        while (len > 0 && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = '\0';
        if (len == 0)
            continue;
        n = split(line, a, 16);
        if (run(a, n))
            dump();
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
