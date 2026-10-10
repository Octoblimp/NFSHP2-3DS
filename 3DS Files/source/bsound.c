#include "bsound.h"

#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "bslotpool.h"
#include "eefpu.h"

// bSound, bSample, bRegion and bVoiceMgr -- see bsound.h.

// bSample::Initialize(int) and bRegion::Initialize(int), gp-13816 and
// gp-13840: made once, the first time bSound::Initialize runs.
static BSlotPool* s_samplePool;
static BSlotPool* s_regionPool;

// VoiceManager's records, 0x00327c88.
static BVoice s_voices[BVOICE_COUNT];

// gp-13696, which bSound's constructor points at itself and bSample reaches
// through 0x00332370.
static BSound* s_instance;

// The constants the -O0 code loads from gp: 16383 (gp-26316, gp-26308), its
// reciprocal as the compiler rounded it (gp-26312, gp-26304) and Fade's
// steps per millisecond (gp-26300, 60/1000.2).
#define VOLUME_SCALE      16383.0f
#define VOLUME_RECIPROCAL 0x1.0004p-14f
#define FADE_STEPS_PER_MS 0x1.eb6bf6p-5f

// CalcPitch's two tables. gp-13812 is the byte 8, the octave table's centre;
// 0x00327a38 is 2^(i-8) for i in 0..15 (two zero words follow it), and
// 0x00327a80 is 4096 * 2^((i-128)/64), a sixty-fourth of an octave a step
// over -2..+2 octaves. CalcPitch indexes the second one step high, so the
// word past its end is read at +2 octaves exactly: it is the padding before
// VoiceManager, always 0, and is kept here as the last entry.
#define PITCH_OCTAVES 8
static const float kOctave[16] = {
    0.00390625f, 0.0078125f, 0.015625f, 0.03125f, 0.0625f, 0.125f, 0.25f,
    0.5f, 1.0f, 2.0f, 4.0f, 8.0f, 16.0f, 32.0f, 64.0f, 128.0f,
};
static const uint16_t kPitchFine[258] = {
     1024,  1035,  1046,  1057,  1069,  1080,  1092,  1104,  1116,  1128,
     1141,  1153,  1166,  1178,  1191,  1204,  1217,  1231,  1244,  1257,
     1271,  1285,  1299,  1313,  1327,  1342,  1357,  1371,  1386,  1401,
     1417,  1432,  1448,  1463,  1479,  1495,  1512,  1528,  1545,  1562,
     1579,  1596,  1613,  1631,  1649,  1667,  1685,  1703,  1722,  1740,
     1759,  1779,  1798,  1817,  1837,  1857,  1878,  1898,  1919,  1940,
     1961,  1982,  2004,  2025,  2048,  2070,  2092,  2115,  2138,  2161,
     2185,  2209,  2233,  2257,  2282,  2307,  2332,  2357,  2383,  2409,
     2435,  2462,  2488,  2515,  2543,  2571,  2599,  2627,  2655,  2684,
     2714,  2743,  2773,  2803,  2834,  2865,  2896,  2927,  2959,  2991,
     3024,  3057,  3090,  3124,  3158,  3192,  3227,  3262,  3298,  3334,
     3370,  3407,  3444,  3481,  3519,  3558,  3596,  3635,  3675,  3715,
     3756,  3796,  3838,  3880,  3922,  3965,  4008,  4051,  4096,  4140,
     4185,  4231,  4277,  4323,  4371,  4418,  4466,  4515,  4564,  4614,
     4664,  4715,  4766,  4818,  4870,  4924,  4977,  5031,  5086,  5142,
     5198,  5254,  5311,  5369,  5428,  5487,  5547,  5607,  5668,  5730,
     5792,  5855,  5919,  5983,  6049,  6114,  6181,  6248,  6316,  6385,
     6455,  6525,  6596,  6668,  6741,  6814,  6888,  6963,  7039,  7116,
     7193,  7271,  7351,  7431,  7512,  7593,  7676,  7760,  7844,  7930,
     8016,  8103,  8192,  8281,  8371,  8462,  8554,  8647,  8742,  8837,
     8933,  9030,  9129,  9228,  9328,  9430,  9533,  9637,  9741,  9848,
     9955, 10063, 10173, 10284, 10396, 10509, 10623, 10739, 10856, 10974,
    11094, 11214, 11336, 11460, 11585, 11711, 11838, 11967, 12098, 12229,
    12363, 12497, 12633, 12771, 12910, 13051, 13193, 13336, 13482, 13628,
    13777, 13927, 14078, 14232, 14387, 14543, 14702, 14862, 15024, 15187,
    15353, 15520, 15689, 15860, 16032, 16207, 16384,     0,
};

// bSnd_VoicePlay's and bSnd_GetPatchID's "no such patch", which bSample
// also takes for a voice it must not play on (0x002740d0).
#define VOICE_NONE 0xfffau

static BsndDriver* drv(void)
{
    return s_instance != NULL ? s_instance->driver : NULL;
}

// bStrICmp, 0x002536a8, as terraintype.c has it: both characters folded,
// sign-extended, before either is tested. Only "equal" is asked here.
static int32_t to_upper(char c)
{
    int32_t v = (int8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

static int32_t str_icmp(const char* a, const char* b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca != cb)
            return ca - cb;
        if (ca == 0)
            return 0;
    }
}

// bStrNCpy, 0x002535a0, as resource.c has it: up to n bytes, stopping
// after the terminator, and none when n runs out first.
static void b_strncpy(char* dst, const char* src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

// -- the vectors ---------------------------------------------------------------
//
// bFragmentedVector<bRegion*> (0x00279730-0x0027a510) and <bSample*>
// (0x0012f6a0-0x0025dc88), one template.

// GrowArrayBy: n more slots after the last. Retail adds them as a new
// fragment, which never moves; nothing outside the vector can tell, so
// here they are one block, reallocated. Retail's come from bMalloc
// uncleared, and find looks at them; bmem's bMalloc clears what it hands
// out, as a fresh heap is.
static void vec_grow_by(BPtrVec* v, int32_t n)
{
    void** items;

    if (n <= 0)
        return;
    items = (void**)bMalloc((int)((v->capacity + n) * (int32_t)sizeof(void*)),
                            "bFragmentedVector", 0, 16);
    if (v->capacity != 0)
        memcpy(items, v->items, (size_t)v->capacity * sizeof(void*));
    bFree(v->items);
    v->items = items;
    v->capacity += n;
}

// GrowArrayTo, which bSound::Initialize asks for 16 regions with.
static void vec_grow_to(BPtrVec* v, int32_t n)
{
    if (v->capacity < n)
        vec_grow_by(v, n - v->capacity);
}

// pushBack: when full, room for max(1, twice the capacity).
static void vec_push(BPtrVec* v, void* p)
{
    if (v->count == v->capacity)
        vec_grow_to(v, v->capacity * 2 > 1 ? v->capacity * 2 : 1);
    v->items[v->count++] = p;
}

// find: every slot there is, the ones past the count included.
static int32_t vec_find(const BPtrVec* v, const void* p)
{
    int32_t i;

    for (i = 0; i < v->capacity; i++)
        if (v->items[i] == p)
            return i;
    return -1;
}

// eraseAt (0x00279b10): every slot from `i` up takes the next one's, the
// last slot left as it was, and the count goes down whether or not `i`
// was below it. An index past the last slot changes nothing.
//
// On an empty vector retail's count goes to -1, and the vector is broken
// from then on: pushBack writes before the first slot, and a loop over the
// count runs on past the last and never ends. The port leaves an empty
// vector as it is.
static void vec_erase_at(BPtrVec* v, int32_t i)
{
    int32_t k;

    if (i < 0 || i >= v->capacity || v->count <= 0)
        return;
    for (k = i; k < v->capacity - 1; k++)
        v->items[k] = v->items[k + 1];
    v->count--;
}

// erase(const T&).
static void vec_erase(BPtrVec* v, const void* p)
{
    int32_t i = vec_find(v, p);

    if (i >= 0)
        vec_erase_at(v, i);
}

static void vec_free(BPtrVec* v)
{
    bFree(v->items);
    memset(v, 0, sizeof(*v));
}

// -- bVoiceMgr -------------------------------------------------------------------

// 0x0027ac80: Release on all 48, which clears the sample and leaves the id.
static void voice_mgr_initialize(void)
{
    int32_t i;

    for (i = 0; i < BVOICE_COUNT; i++)
        s_voices[i].sample = NULL;
}

// 0x0027ad00. A record already holding `id` is taken from its sample (an
// assert in the debug build); otherwise the first free record. NULL when
// all 48 are held.
static BVoice* voice_mgr_get_voice(uint16_t id, BSample* s)
{
    int32_t i;

    for (i = 0; i < BVOICE_COUNT; i++) {
        BVoice* v = &s_voices[i];

        if (v->sample != NULL && v->id == id) {
            bsample_release_voice(v->sample);
            v->id = id;
            v->sample = s;
            return v;
        }
    }
    for (i = 0; i < BVOICE_COUNT; i++) {
        BVoice* v = &s_voices[i];

        if (v->sample == NULL) {
            v->id = id;
            v->sample = s;
            return v;
        }
    }
    return NULL;
}

// 0x0027af48.
static void voice_mgr_release_voice(BVoice* v)
{
    v->sample = NULL;
}

// 0x0027b2f0. A voice whose channel has gone quiet is stopped, unless its
// sample locked the voice and is not playing on it; then every held
// sample's Update, the one just stopped included.
static void voice_mgr_update(void)
{
    BsndDriver* d = drv();
    int32_t i;

    for (i = 0; i < BVOICE_COUNT; i++) {
        BSample* s = s_voices[i].sample;

        if (s == NULL)
            continue;
        if (!bsnd_channel_busy(d, s_voices[i].id)) {
            if (!s->voiceLock || s->voiceLockPlaying)
                bsample_stop(s);
        }
        bsample_update(s);
    }
}

const BVoice* bsound_voices(void)
{
    return s_voices;
}

// -- bSound ----------------------------------------------------------------------

// 0x00277ed8.
static void notify_client(uint32_t event, void* what)
{
    BSound* s = s_instance;

    if (s != NULL && s->client != NULL)
        s->client(event, what, s->clientData);
}

void bsound_init(BSound* s, BsndDriver* d, BSoundCallback client,
                 void* clientData)
{
    int32_t i;

    // The constructor, 0x002776c0. Retail's instance is in .bss, so what the
    // constructor leaves alone -- the pending count among it -- starts 0.
    memset(s, 0, sizeof(*s));
    s_instance = s;
    for (i = 0; i < 16; i++)
        s->categoryVolume[i] = 1.0f;
    s->path[0] = '\0';
    s->driver = d;
    if (d == NULL)
        return;

    // Initialize, 0x00277820. bSnd_Initialize is bsnd_hw_init's, already
    // done by the time the game makes its bSound.
    s->client = client;
    s->clientData = clientData;
    s->status = 1;
    if (s_samplePool == NULL)
        s_samplePool = bNewSlotPool((int)sizeof(BSample), 255,
                                    "bSoundSamples", 16);
    if (s_regionPool == NULL)
        s_regionPool = bNewSlotPool((int)sizeof(BRegion), 32,
                                    "bSoundRegions", 16);
    voice_mgr_initialize();
    vec_grow_to(&s->regions, 16);
}

BSound* bsound_get(void)
{
    return s_instance;
}

// 0x0027a720 / 0x0027a6d8 / 0x00278088 / 0x002780f0. One slot, so at most
// one region is ever pending; removing takes the last whatever the name,
// and clears only its first byte, as bStrCpy of "" does.
static void add_pending_region(BSound* s, const char* name)
{
    char* slot = s->pending[s->pendingCount++];

    // bStrCpy, unbounded in retail; no region name comes near 255.
    strncpy(slot, name, sizeof(s->pending[0]) - 1);
    slot[sizeof(s->pending[0]) - 1] = '\0';
}

static void remove_pending_region(BSound* s)
{
    if (s->pendingCount != 0) {
        s->pendingCount--;
        s->pending[s->pendingCount][0] = '\0';
    }
}

// 0x00277f38. A pending region whose bank has come in becomes a bRegion;
// "common" is remembered as the common region; the client hears of it.
static void update_pending_regions(BSound* s)
{
    int32_t i;

    for (i = 0; i < s->pendingCount; i++) {
        BRegion* r;

        if (!bsnd_bank_loaded(s->driver, s->pending[i]))
            continue;
        r = bregion_new(s->pending[i]);
        if (r == NULL)
            continue;
        if (strcmp(bregion_name(r), "common") == 0)
            s->common = r;
        vec_push(&s->regions, r);
        remove_pending_region(s);
        notify_client(BSOUND_REGION_LOADED, r);
    }
}

void bsound_update(BSound* s)
{
    if (s->status != 1)
        return;
    // bSnd_DriverUpdate, and bSnd_Flush when it fails -- which the port's
    // driver never does. bsnd_update is the voices' end-of-sound sweep,
    // what bSound::updateCompletedVoices was before it became empty.
    bsnd_update(s->driver);
    update_pending_regions(s);
    voice_mgr_update();
    // gp-13692 takes bGetTicker() here; nothing in the game reads it.
}

BRegion* bsound_common_region(const BSound* s)
{
    return s->common;
}

BRegion* bsound_region(const BSound* s, const char* name)
{
    int32_t i;

    for (i = 0; i < s->regions.count; i++) {
        BRegion* r = (BRegion*)s->regions.items[i];

        if (strcmp(bregion_name(r), name) == 0)
            return r;
    }
    return NULL;
}

int32_t bsound_region_count(const BSound* s)
{
    return s->regions.count;
}

BRegion* bsound_region_at(const BSound* s, int32_t i)
{
    return (BRegion*)s->regions.items[i];
}

int32_t bsound_load_region(BSound* s, const char* name)
{
    if (s->status != 1)
        return 0;
    // bSnd_BankLoad(name, 0xffff, 1), 0x0025f720. The load starts before
    // the pending count is looked at, so a second region asked for while
    // one is pending is read in and then refused.
    if (!bsnd_bank_load(s->driver, name))
        return 0;
    if (s->pendingCount > 0)
        return 0;
    add_pending_region(s, name);
    return 1;
}

// 0x00277c00. The common region is not forgotten when it is the one
// unloaded, as retail does not forget it; nothing asks for it afterwards.
// A name with no region is erased all the same, as NULL: find takes the
// first empty slot past the count, and eraseAt then shortens the vector
// by one -- the last region is gone from it, though not deleted.
void bsound_unload_region(BSound* s, const char* name)
{
    BRegion* r = bsound_region(s, name);

    vec_erase(&s->regions, r);
    if (r != NULL)
        bregion_delete(r);
}

void bsound_set_category_volume(BSound* s, uint32_t category, float v)
{
    int32_t i;

    if (category >= 16)
        return;
    s->categoryVolume[category] = v;
    for (i = 0; i < BVOICE_COUNT; i++) {
        BSample* smp = s_voices[i].sample;

        // GetPitch, which answers the current volume: each sample is set
        // to the volume it already has, and so takes the new category's.
        if (smp != NULL && bsample_get_category(smp) == category)
            bsample_set_volume(smp, bsample_get_pitch(smp));
    }
}

float bsound_get_category_volume(const BSound* s, uint32_t category)
{
    if (category < 16)
        return s->categoryVolume[category];
    return 1.0f;
}

void bsound_set_path(BSound* s, const char* path)
{
    b_strncpy(s->path, path, 63);
    // The port's: with no ndsp there is no driver to tell. Retail's bSnd
    // calls take no instance, so it never needed to ask.
    if (s->driver != NULL)
        bsnd_set_load_path(s->driver, path);
}

int32_t bsound_get_status(const BSound* s)
{
    return s->status;
}

void bsound_set_mode(BSound* s, int32_t mode)
{
    if (s->driver == NULL)          // the port's, as bsound_set_path's
        return;
    switch (mode) {
    case 0: bsnd_set_mode(s->driver, BSND_MODE_MONO); break;
    case 1: bsnd_set_mode(s->driver, BSND_MODE_STEREO); break;
    case 2: bsnd_set_mode(s->driver, BSND_MODE_PROLOGIC); break;
    default: break;
    }
}

void bsound_flush(BSound* s, int32_t wait)
{
    (void)s;
    (void)wait;
}

BSlotPool* bsound_sample_pool(void)
{
    return s_samplePool;
}

BSlotPool* bsound_region_pool(void)
{
    return s_regionPool;
}

// -- bRegion ---------------------------------------------------------------------

// 0x00272c40: 32 characters at most, the 33rd byte forced to NUL.
static void bregion_set_name(BRegion* r, const char* name)
{
    if (strlen(name) >= 33) {
        b_strncpy(r->name, name, 32);
        r->name[32] = '\0';
    } else {
        strcpy(r->name, name);
    }
}

BRegion* bregion_new(const char* name)
{
    BsndDriver* d = drv();
    BRegion* r;
    uint16_t bank, count, i;

    if (s_regionPool == NULL)
        return NULL;
    r = (BRegion*)bSlotOMalloc(s_regionPool);
    if (r == NULL)
        return NULL;
    // 0x002716f8. The slot comes back cleared, which is the vector's
    // constructor.
    bregion_set_name(r, name);
    bank = bsnd_bank_number(d, bregion_name(r));
    count = (uint16_t)bsnd_bank_patch_count(d, bank);
    for (i = 0; i < count; i++) {
        BSample* s = bsample_new(0);
        const char* patch;

        if (s == NULL)
            break;
        patch = bsnd_bank_patch_name(d, bank, i);
        bsample_initialize(s, patch != NULL ? patch : "", bregion_name(r));
        vec_push(&r->samples, s);
    }
    return r;
}

void bregion_delete(BRegion* r)
{
    // 0x00271840: the front sample taken out and deleted until none are
    // left, then the bank unloaded.
    while (r->samples.count != 0) {
        BSample* s = (BSample*)r->samples.items[0];

        vec_erase(&r->samples, s);
        if (s != NULL)
            bsample_delete(s);
    }
    bsnd_bank_unload(drv(), bregion_name(r));
    vec_free(&r->samples);
    bSlotFree(s_regionPool, r);
}

BSample* bregion_sample(const BRegion* r, const char* name)
{
    int32_t i;

    // The port's: a region that never loaded -- no bank on the card, or no
    // ndsp -- has no samples, where retail would read through NULL.
    if (r == NULL)
        return NULL;
    for (i = 0; i < r->samples.count; i++) {
        BSample* s = (BSample*)r->samples.items[i];

        if (str_icmp(bsample_get_name(s), name) == 0)
            return s;
    }
    return NULL;
}

const char* bregion_name(const BRegion* r)
{
    return r->name;
}

int32_t bregion_sample_count(const BRegion* r)
{
    return r->samples.count;
}

BSample* bregion_sample_at(const BRegion* r, int32_t i)
{
    return (BSample*)r->samples.items[i];
}

// -- bSample ---------------------------------------------------------------------

void bsample_construct(BSample* s, int8_t type)
{
    // 0x00272ff0 / 0x00273098, store for store. The fade target, the
    // callback's word, the muting volume, the locked-playing flag and the
    // rate are left as they were: a slot comes cleared, and a bSample held
    // by value is its owner's to clear.
    s->voice = NULL;
    s->scaleVolume = 1.0f;
    s->currentVolume = 1.0f;
    s->currentPan = 0.0f;
    s->currentPitch = 0.0f;
    s->fadeAdjust = 0.0f;
    s->callback = NULL;
    s->muted = 0;
    s->paused = 0;
    s->category = 0;
    s->name[0] = '\0';
    s->bankName[0] = '\0';
    s->offset = 0;
    s->size = 0;
    s->type = type;
    s->voiceLock = 0;
    s->sampleId = VOICE_NONE;
    s->field8 = 0;
    s->nearEndNotified = 0;
}

void bsample_destruct(BSample* s)
{
    // 0x00273148: unlocked first, so Stop gives the voice back.
    s->voiceLock = 0;
    bsample_stop(s);
}

BSample* bsample_new(int8_t type)
{
    BSample* s;

    if (s_samplePool == NULL)
        return NULL;
    s = (BSample*)bSlotOMalloc(s_samplePool);
    if (s != NULL)
        bsample_construct(s, type);
    return s;
}

void bsample_delete(BSample* s)
{
    bsample_destruct(s);
    bSlotFree(s_samplePool, s);
}

void bsample_initialize_copy(BSample* s, const BSample* other)
{
    // The port's, as bregion_sample's: no slot, or no sample to copy.
    if (s == NULL || other == NULL)
        return;
    bsample_set_name(s, bsample_get_name(other));
    bsample_set_bank_name(s, bsample_get_bank_name(other));
}

void bsample_initialize_callback(BSample* s, BSoundCallback cb, void* data)
{
    s->callback = cb;
    s->callbackData = data;
}

void bsample_initialize(BSample* s, const char* name, const char* bank)
{
    // 0x002732c0. "_MOVIE" is the movies' sound, which has no patch.
    uint16_t id = VOICE_NONE;

    if (strcmp("_MOVIE", name) != 0)
        id = bsnd_patch_id(drv(), bank, name);
    s->sampleId = id;
    bsample_set_name(s, name);
    bsample_set_bank_name(s, bank);
}

void bsample_lock_voice(BSample* s)
{
    // 0x00273388. A failed lock is reported and asserted in the debug build
    // and carries on regardless: the voice record takes the 0xfffc.
    uint16_t ch;

    s->voiceLock = 1;
    ch = bsnd_lock_channels(drv(), (uint16_t)bsample_get_channels(s));
    s->voice = voice_mgr_get_voice(ch, s);
}

void bsample_set_name(BSample* s, const char* name)
{
    b_strncpy(s->name, name, 31);
}

void bsample_set_bank_name(BSample* s, const char* bank)
{
    b_strncpy(s->bankName, bank, 31);
}

const char* bsample_get_name(const BSample* s)
{
    return s->name;
}

const char* bsample_get_bank_name(const BSample* s)
{
    return s->bankName;
}

void bsample_set_category(BSample* s, uint32_t category)
{
    if (s == NULL)                  // the port's, as bregion_sample's
        return;
    s->category = category;
}

void bsample_set_pan(BSample* s, float pan)
{
    if (s->voice != NULL)
        bsnd_set_voice_pan(drv(), s->voice->id, bsample_calc_pan(s, pan));
    s->currentPan = pan;
}

int8_t bsample_calc_pan(const BSample* s, float pan)
{
    (void)s;
    return (int8_t)ee_trunc_w(pan * 255.0f);
}

int32_t bsample_set_pitch(BSample* s, float pitch)
{
    // 0x00273738. The bPrintf for a bank whose name starts '_' is left out.
    if (s->voice != NULL)
        bsnd_set_voice_pitch(drv(), s->voice->id,
                             bsample_calc_pitch(s, pitch));
    s->currentPitch = pitch;
    return s->voice != NULL ? (int32_t)s->voice->id : 9999;
}

uint32_t bsample_calc_pitch(const BSample* s, float pitch)
{
    // 0x00273850. The truncation is kept in a signed byte, as retail keeps
    // it, so a pitch past +-127 wraps before it is range-checked.
    int8_t semi = (int8_t)ee_trunc_w(pitch);
    float ratio = 1.0f;
    uint32_t base;

    if (bsample_get_type(s) == 0)
        base = bsnd_get_patch_pitch(drv(), s->bankName, s->name);
    else
        base = s->rate;

    if (abs((int32_t)semi) >= PITCH_OCTAVES - 1) {
        // "Pitch Shift out of range", and clamped to +-7 octaves.
        if ((float)(PITCH_OCTAVES - 1) < pitch)
            pitch = (float)(PITCH_OCTAVES - 1);
        if (pitch < (float)-(PITCH_OCTAVES - 1))
            pitch = (float)-(PITCH_OCTAVES - 1);
        semi = (int8_t)ee_trunc_w(pitch);
    }

    if (-2.0f <= pitch && pitch <= 2.0f) {
        // One step high: pitch 0 reads 4140, not 4096, so every sample in
        // this range plays 18.75 cents sharp -- and +2.0 reads the 0 past
        // the table's end.
        ratio = (float)kPitchFine[ee_trunc_w((pitch + 2.0f) * 64.0f) + 1]
              * 0x1p-12f;
    } else {
        // Outside +-2 octaves: the octave's ratio plus a straight line to
        // the next, the line's slope taken from the octave above when
        // rising and the one below when falling.
        float frac = pitch - (float)semi;

        if (semi > 0)
            ratio = kOctave[semi + PITCH_OCTAVES]
                  + kOctave[semi + PITCH_OCTAVES] * frac;
        else
            ratio = kOctave[semi + PITCH_OCTAVES]
                  + kOctave[semi + PITCH_OCTAVES - 1] * frac;
    }
    return (uint32_t)ee_trunc_w((float)base * ratio);
}

void bsample_set_scale_volume(BSample* s, float scale)
{
    s->scaleVolume = scale;
    if (s->voice != NULL) {
        uint16_t v = (uint16_t)ee_trunc_w(bsample_get_scaled_volume(s)
                                          * VOLUME_SCALE);
        bsnd_set_voice_volume(drv(), s->voice->id, v);
    }
}

float bsample_get_scaled_volume(const BSample* s)
{
    // 0x00273c80: the patch's volume (full for a sample with a type), its
    // category's volume as a fraction of 16383, and the scale.
    uint16_t vol = 16383;
    float cat;

    if (bsample_get_type(s) == 0)
        vol = bsnd_get_patch_volume(drv(), s->bankName, s->name);
    cat = s_instance != NULL
        ? bsound_get_category_volume(s_instance, s->category) : 1.0f;
    return ((float)vol * (cat * VOLUME_RECIPROCAL)) * s->scaleVolume;
}

void bsample_set_volume(BSample* s, float volume)
{
    // 0x00273d50. Without a voice nothing is remembered. The Printf for a
    // bank whose name starts '_' is left out.
    if (s->voice != NULL) {
        uint16_t v;

        s->currentVolume = volume;
        v = bsample_calc_volume(s, volume);
        bsnd_set_voice_volume(drv(), s->voice->id, v);
    }
}

uint16_t bsample_calc_volume(const BSample* s, float volume)
{
    float v = volume * bsample_get_scaled_volume(s);

    return (uint16_t)ee_trunc_w(v * VOLUME_SCALE);
}

void bsample_set_azimuth(BSample* s, uint16_t azimuth)
{
    if (s == NULL)                  // the port's, as bregion_sample's
        return;
    if (s->voice != NULL)
        bsnd_set_voice_azimuth(drv(), s->voice->id, azimuth);
}

float bsample_get_volume(const BSample* s)
{
    if (s->voice != NULL)
        return (float)bsnd_get_voice_volume(drv(), s->voice->id)
             * VOLUME_RECIPROCAL;
    return 0.0f;
}

BVoice* bsample_play_named(BSample* s, const char* name, uint32_t offset,
                           uint32_t size)
{
    bsample_set_name(s, name);
    s->offset = offset;
    s->size = size;
    return bsample_play(s, s->currentVolume, 0.0f, 0.0f);
}

BVoice* bsample_play(BSample* s, float volume, float pan, float pitch)
{
    BsndDriver* d = drv();
    uint32_t rate;
    uint16_t vol;
    int8_t p;

    if (s == NULL)                  // the port's, as bregion_sample's
        return NULL;
    if (s->voice != NULL) {
        if (s->voice->id == VOICE_NONE)
            return NULL;
        if (bsnd_channel_busy(d, s->voice->id))
            bsample_stop(s);
    }
    if (s->voice == NULL) {
        uint16_t ch;

        if (bsample_get_channels(s) == 0)
            return NULL;
        ch = bsnd_lock_channels(d, (uint16_t)bsample_get_channels(s));
        if (ch == BSND_BAD_VOICE)
            return NULL;            // "no voices for %s", in the debug build
        s->voice = voice_mgr_get_voice(ch, s);
        // Retail asserts and carries on into a NULL voice. All 48 records
        // held means 48 locked runs, which 22 channels cannot make.
        if (s->voice == NULL)
            return NULL;
    }
    s->currentVolume = volume;
    s->currentPan = pan;
    s->currentPitch = pitch;
    rate = bsample_calc_pitch(s, pitch);
    vol = bsample_calc_volume(s, volume);
    p = bsample_calc_pan(s, pan);
    // With an offset or a size, retail plays through the overload that
    // starts a stream part-way (0x00260ce8). The port's driver has no
    // streams, so both reach the same call; only the speech's streams ever
    // set them.
    bsnd_voice_play_pan(d, s->bankName, s->name, rate, vol, p, s->voice->id);
    s->voiceLockPlaying = 1;
    s->paused = 0;
    return s->voice;
}

bool bsample_is_playing(const BSample* s)
{
    return s->voice != NULL && bsnd_channel_busy(drv(), s->voice->id);
}

void bsample_pause(BSample* s, bool pause)
{
    // 0x00274488. The paused flag only changes when the channel is busy.
    BsndDriver* d = drv();

    if (s == NULL)                  // the port's, as bregion_sample's
        return;
    if (s->voice == NULL)
        return;
    if (pause) {
        if (bsnd_channel_busy(d, s->voice->id)) {
            bsnd_voice_pause(d, s->voice->id);
            s->paused = pause;
        }
    } else {
        if (bsnd_channel_busy(d, s->voice->id)) {
            bsnd_voice_resume(d, s->voice->id);
            s->paused = pause;
        }
    }
}

void bsample_stop(BSample* s)
{
    // 0x00274618. A locked voice is kept, stopped; otherwise its channels
    // are unlocked and the record given back. Either way the client and
    // the sample's own callback hear that it stopped.
    BsndDriver* d = drv();

    if (s == NULL || s->voice == NULL)  // NULL: the port's
        return;
    s->voiceLockPlaying = 0;
    bsnd_voice_stop(d, s->voice->id);
    if (!bsample_is_voice_locked(s)) {
        uint16_t id = s->voice->id;

        bsnd_unlock_channels(d, id, (uint16_t)bsample_get_channels(s));
        voice_mgr_release_voice(s->voice);
        s->voice = NULL;
    }
    notify_client(BSOUND_SAMPLE_STOPPED, s);
    if (s->callback != NULL)
        s->callback(BSOUND_SAMPLE_STOPPED, s, s->callbackData);
    s->paused = 0;
}

void bsample_mute(BSample* s, bool mute)
{
    BsndDriver* d = drv();

    if (s->voice == NULL || s->muted == (int32_t)mute)
        return;
    if (mute) {
        s->volumeBeforeMuting = bsnd_get_voice_volume(d, s->voice->id);
        bsnd_set_voice_volume(d, s->voice->id, 0);
    } else {
        bsnd_set_voice_volume(d, s->voice->id, s->volumeBeforeMuting);
    }
    s->muted = mute;
}

void bsample_fade(BSample* s, float volume, uint32_t ms)
{
    if (s->voice == NULL)
        return;
    if (ms < 33) {
        bsample_set_volume(s, bsample_get_scaled_volume(s) * volume);
    } else {
        // The target is in scaled terms and the current volume is not, so
        // a fade towards 1.0 of a quieter patch steps down to it.
        s->fadeTarget = volume * bsample_get_scaled_volume(s);
        s->fadeAdjust = (s->fadeTarget - s->currentVolume)
                      / ((float)ms * FADE_STEPS_PER_MS);
    }
}

uint32_t bsample_get_channels(const BSample* s)
{
    // 0x00274960. The banks named '_' are the streams: _STREAMS and _MOVIE
    // are stereo, _STREAM mono, any other 0.
    if (s->bankName[0] == '_') {
        if (strncmp(s->bankName, "_STREAMS", 8) == 0)
            return 2;
        if (strncmp(s->bankName, "_MOVIE", 7) == 0)
            return 2;
        if (strncmp(s->bankName, "_STREAM", 7) == 0)
            return 1;
        return 0;
    }
    return bsnd_get_patch_channels(drv(), s->bankName, s->name);
}

void bsample_update(BSample* s)
{
    // 0x00274a98. A fade's step, stopping at the target; then, still
    // inside the fade, the near-end poll -- so a stream that is not fading
    // never raises event 4. Retail's, kept.
    float v;

    if (s->voice == NULL || s->fadeAdjust == 0.0f)
        return;
    v = s->currentVolume + s->fadeAdjust;
    if (s->fadeAdjust < 0.0f) {
        if (v < s->fadeTarget) {
            v = s->fadeTarget;
            s->fadeAdjust = 0.0f;
        }
    } else {
        if (s->fadeTarget < v) {
            v = s->fadeTarget;
            s->fadeAdjust = 0.0f;
        }
    }
    bsample_set_volume(s, v);
    if (s->voice != NULL && !s->nearEndNotified && s->callback != NULL
        && bsnd_stream_near_end(drv(), s->voice->id)) {
        notify_client(BSOUND_SAMPLE_NEAR_END, s);
        if (s->callback != NULL)
            s->callback(BSOUND_SAMPLE_NEAR_END, s, s->callbackData);
        s->nearEndNotified = 1;
    }
}

int8_t bsample_get_type(const BSample* s)
{
    return s->type;
}

int32_t bsample_is_voice_locked_playing(const BSample* s)
{
    return s->voiceLockPlaying;
}

int32_t bsample_is_voice_locked(const BSample* s)
{
    return s->voiceLock;
}

void bsample_release_voice(BSample* s)
{
    s->voice = NULL;
}

uint32_t bsample_get_category(const BSample* s)
{
    return s->category;
}

int32_t bsample_is_paused(const BSample* s)
{
    return s->paused;
}

float bsample_get_pitch(const BSample* s)
{
    return s->currentVolume;
}

void bsample_set_callback(BSample* s, BSoundCallback cb, void* data)
{
    s->callback = cb;
    s->callbackData = data;
}
