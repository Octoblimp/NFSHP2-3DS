#include "sedwedge.h"

#include <stdio.h>
#include <string.h>

#include "bmem.h"
#include "realtime.h"
#include "sound.h"

extern int32_t SoundEnabled;

static SedWedge *gInstance;                 // m_pInstance, gp-16544
static float     gClockMs;                  // m_clock_in_ms, gp-16548
static SedWedge *gSoundSedWedge;            // Sound.obj's, gp-19016
static void     *gSoundSpeechSlot;          // gp-19044, never set

// bWare's name for every block the wedge takes; retail's is the source
// file's path, and its line is bMalloc's third word.
static const char kFile[] = "sedwedge.cpp";

// The BAN file's 16-byte entries, read and written in place.
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

// bStrNCpy, 0x002535a0: up to n bytes, stopping after the terminator.
static void b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

// ------------------------------------------------------------------ bSegment

void bsegment_construct(BSegment *s)
{
    // Retail asserts that bSound is up first (bSegment.cpp, line 19).
    s->initialized = 0;
    s->offset = 0;
    s->size = 0;
    s->field268 = 0;
    s->flags = 0;
    strcpy(s->name, "<Not Initialized>");
}

void bsegment_initialize(BSegment *s, const char *name, uint32_t offset,
                         uint32_t size, uint32_t flags)
{
    // Retail asserts m_nStatus == 0 (line 56), copies the name twice, and
    // reports the segment through bSound::Printf.
    b_strncpy(s->name, name, 255);
    s->initialized = 1;
    s->offset = offset;
    s->size = size;
    s->field268 = 0;
    s->flags = flags;
}

void bsegment_cleanup(BSegment *s)
{
    s->initialized = 0;
    s->offset = 0;
    s->size = 0;
    s->field268 = 0;
    s->flags = 0;
    strcpy(s->name, "<Not Initialized>");
}

uint32_t bsegment_get_offset(const BSegment *s)
{
    return s->offset;
}

uint32_t bsegment_get_size(const BSegment *s)
{
    return s->size;
}

// ----------------------------------------------------- the library's calls

// S_AbortMessage, 0x00205998: bVPrintf, to the debug channel.
void sedwedge_abort_message(const char *msg)
{
    fputs(msg, stderr);
}

// S_DebugPrint, 0x002059d0.
void sedwedge_debug_print(const char *msg)
{
    (void)msg;
}

// S_TimerGetTick, 0x00205a00: the clock Update keeps, cut to a whole ms.
uint32_t sedwedge_timer_get_tick(void)
{
    return (uint32_t)(int32_t)gClockMs;
}

// S_TestSentenceRule, 0x00205a18: no rule of the game's passes.
int32_t sedwedge_test_sentence_rule(uint32_t *event, int32_t rule,
                                    int32_t value, int32_t dat)
{
    (void)event;
    (void)rule;
    (void)value;
    (void)dat;
    return 0;
}

// S_SetSentenceRule, 0x00205a20.
void sedwedge_set_sentence_rule(uint32_t *event, int32_t rule,
                                int32_t value, int32_t dat)
{
    (void)event;
    (void)rule;
    (void)value;
    (void)dat;
}

// S_SentencePartRequest, 0x00205a28.
void sedwedge_sentence_part_request(SpchSampleRequest *r)
{
    sedwedge_add_sentence_part(gInstance, r->bank, (uint32_t)r->offset,
                               (uint32_t)r->size);
}

// S_SampleCallback, 0x00205a58: the chain sample's.
void sedwedge_sample_callback(uint32_t event, void *sample, void *data)
{
    if (event == BSOUND_SAMPLE_STREAM_ACTIVE) {
        if (SoundEnabled && sound_get()->speechEnabled)
            bsample_play((BSample *)sample, 1.0f, 0.0f, 0.0f);
        bsample_set_volume((BSample *)sample, 1.0f);
    } else if (event == BSOUND_SAMPLE_STOPPED) {
        ((SedWedge *)data)->status = SEDWEDGE_STOPPED;
    }
}

// S_WriteEVLog, 0x00205ae0.
void sedwedge_write_evlog(char *buf, int32_t size)
{
    (void)buf;
    (void)size;
}

// ----------------------------------------------------------------- cSEDWedge

void sedwedge_construct(SedWedge *w)
{
    w->status = SEDWEDGE_IDLE;
    w->pauseState = 0;
    w->bankCount = 0;
    gClockMs = 0.0f;
    w->bankMem = NULL;
    w->extVecs = NULL;
    w->eventData = NULL;
    gInstance = w;
    w->sentenceSample = NULL;
    w->initialized = 0;
    w->dataPackFile = NULL;
}

int32_t sedwedge_load_data_file(SedWedge *w, const char *path, uint8_t **out)
{
    bFile  *f = bOpen(path);
    int32_t size;

    (void)w;
    if (f == NULL)
        return 0;
    size = bFileSize(f);
    *out = bMalloc(size, kFile, 92, 16);
    bRead(f, *out, size);
    bClose(f);
    return 1;
}

void sedwedge_add_sentence_part(SedWedge *w, int32_t bank, uint32_t offset,
                                uint32_t size)
{
    uint32_t at;

    if (bank < 0 || bank >= w->bankCount)
        return;
    // The port's: retail has room for ten and writes on past them, over
    // the count. No sentence has more than ten parts.
    if (w->segmentCount >= SEDWEDGE_SEGMENTS)
        return;
    at = rd32(w->speechBank + bank * 16 + 12) + offset;
    bsegment_cleanup(w->segment[w->segmentCount]);
    bsegment_initialize(w->segment[w->segmentCount], "Segment", at, size, 0);
    w->segmentCount++;
}

int32_t sedwedge_initialize(SedWedge *w, const char *events, const char *hdr,
                            const char *dat, const char *ban, void *slot)
{
    SpchExtVecs *v;
    uint32_t a, b;
    int32_t i;

    (void)hdr;
    w->gameNumber = 0;
    w->slot = slot;
    // The port's: bGetFile stops the game on a file that is not there, as
    // retail's assert does. A card without the speech has none.
    if (bFileSizeName(ban) < 0) {
        w->initialized = 0;
        return 0;
    }
    w->bankFile = bGetFile(ban, NULL, 16);
    w->bankCount = 0;
    w->speechBank = w->bankFile;
    if (w->bankFile != NULL)
        w->bankCount = (int32_t)rd32(w->bankFile);
    w->dataPackFile = bOpen(dat);
    b_strncpy(w->dataPackFileName, dat, 31);
    // Retail ends the name at [32], the ext vecs' first byte, which it
    // writes over next; the port ends it in the name.
    w->dataPackFileName[31] = '\0';
    spch_init(sedwedge_sentence_part_request, w->gameNumber,
              spch_get_sample_data_rate(22050, 16, 1));
    w->bankMem = bMalloc(spch_get_bank_ptr_mem_size(SEDWEDGE_BANK_PTRS),
                         kFile, 423, 16);
    spch_init_bank_mem(SEDWEDGE_BANK_PTRS, w->bankMem);
    v = spch_get_ext_vecs();
    v->abort = sedwedge_abort_message;
    v->print = sedwedge_debug_print;
    v->gettick = sedwedge_timer_get_tick;
    w->extVecs = v;
    spch_init_evlog(w->evLogBuffer, SEDWEDGE_EVLOG_SIZE, sedwedge_write_evlog);
    spch_init_rule_callbacks(sedwedge_test_sentence_rule,
                             sedwedge_set_sentence_rule);
    if (!sedwedge_load_data_file(w, events, &w->eventData)
        || !spch_resolve_data(w->eventData)) {
        w->initialized = 0;
        return 0;
    }
    spch_get_event_dat_info(w->eventData, &a, &b);
    for (i = 0; i < w->bankCount; i++) {
        int32_t h = spch_add_bank(w->bankFile + rd32(w->speechBank + i * 16 + 4));

        wr32(w->speechBank + i * 16, (uint32_t)h);
    }
    if (w->sentenceSample == NULL) {
        w->sentenceSample = bsample_chain_new();
        // The port's: retail constructs on what the full pool answers.
        if (w->sentenceSample == NULL) {
            w->initialized = 0;
            return 0;
        }
    }
    bsample_set_rate(w->sentenceSample, 24000);
    for (i = 0; i < SEDWEDGE_SEGMENTS; i++) {
        BSegment *s = bMalloc((int)sizeof(BSegment), kFile, 496, 16);

        bsegment_construct(s);
        w->segment[i] = s;
    }
    w->segmentCount = 0;
    spch_clear_event_queue();
    spch_clear_event_queue();
    sedwedge_mute(w, false);
    w->initialized = 1;
    return 1;
}

void sedwedge_fade(SedWedge *w, float fade)
{
    (void)fade;
    if (!SoundEnabled)
        return;
    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED) {
        bsample_stop(w->sentenceSample);
        // bSample::Cleanup (0x00273360) does nothing.
        w->status = SEDWEDGE_IDLE;
    }
}

void sedwedge_mute(SedWedge *w, bool on)
{
    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED)
        bsample_pause(w->sentenceSample, on);
    w->pauseState = on;
}

void sedwedge_cleanup(SedWedge *w)
{
    int32_t i;

    if (w->initialized != 1)
        return;
    spch_deinit();
    if (w->dataPackFile != NULL) {
        bClose(w->dataPackFile);
        w->dataPackFile = NULL;
    }
    if (w->bankFile != NULL) {
        bFree(w->bankFile);
        w->bankFile = NULL;
        w->speechBank = NULL;
        w->bankCount = 0;
    }
    if (w->eventData != NULL) {
        bFree(w->eventData);
        w->eventData = NULL;
    }
    if (w->bankMem != NULL) {
        bFree(w->bankMem);
        w->bankMem = NULL;
    }
    // The chain is kept for the next Initialize.
    if (w->sentenceSample != NULL)
        bsample_stop(w->sentenceSample);
    for (i = 0; i < SEDWEDGE_SEGMENTS; i++) {
        if (w->segment[i] != NULL) {
            bFree(w->segment[i]);
            w->segment[i] = NULL;
        }
    }
    w->initialized = 0;
}

int32_t sedwedge_get_event_pending(SedWedge *w, int32_t channel)
{
    if (w->initialized != 1)
        return 0;
    return spch_check_event_queue(channel) != 0 ? 1 : 0;
}

int32_t sedwedge_queue_sentence_event(SedWedge *w, int32_t channel)
{
    if (w->initialized != 1)
        return 0;
    spch_choose(channel);
    spch_play(channel);
    return 1;
}

int32_t sedwedge_play_sentence(SedWedge *w, int32_t channel, float volume)
{
    int32_t i, n;

    (void)channel;
    (void)volume;
    if (w->initialized != 1)
        return 0;
    if (w->status == SEDWEDGE_PLAYING || w->status == SEDWEDGE_STOPPED) {
        bsample_stop(w->sentenceSample);
        w->status = SEDWEDGE_IDLE;
    }
    if (w->segmentCount != 0) {
        bsample_set_category(w->sentenceSample, 6);
        bsample_initialize_callback(w->sentenceSample,
                                    sedwedge_sample_callback, w);
        // The DAT file's name is the whole path, so bSound's goes while
        // the parts are handed over.
        bsound_set_path(bsound_get(), "");
        n = w->segmentCount;
        for (i = 0; i < n; i++) {
            uint32_t offset = bsegment_get_offset(w->segment[i]) + 48;
            uint32_t size = bsegment_get_size(w->segment[i]) - 48;

            bsample_chain_add(w->sentenceSample, w->dataPackFileName,
                              offset, size, i == n - 1);
        }
        // Retail puts back "sound\\"; the port's is the card's.
        bsound_set_path(bsound_get(), sound_get_path(sound_get()));
        w->segmentCount = 0;
        w->status = SEDWEDGE_PLAYING;
    }
    return 1;
}

int32_t sedwedge_stop_sentence(SedWedge *w, int32_t channel)
{
    (void)channel;
    if (w->initialized != 1)
        return 0;
    bsample_stop(w->sentenceSample);
    w->status = SEDWEDGE_IDLE;
    return 1;
}

int32_t sedwedge_clear_event_queue(SedWedge *w)
{
    if (w->initialized != 1)
        return 0;
    spch_clear_event_queue();
    if (w->status != SEDWEDGE_IDLE)
        sedwedge_stop_sentence(w, 0);
    return 1;
}

void sedwedge_update(SedWedge *w)
{
    if (w->initialized == 0 || w->pauseState != 0)
        return;
    // gp-27664, a sixtieth.
    gClockMs = (float)RealTimeFrames * (1.0f / 60.0f) * 1000.0f;
    if (w->status == SEDWEDGE_STOPPED)
        w->status = SEDWEDGE_IDLE;
    if (w->status != SEDWEDGE_IDLE && w->status != SEDWEDGE_PAUSED)
        return;
    if (sedwedge_get_event_pending(w, 0)) {
        sedwedge_queue_sentence_event(w, 0);
        sedwedge_play_sentence(w, 0, 1.0f);
    }
}

// ----------------------------------------------------------------- Sound.obj

SedWedge *sedwedge_create(void)
{
    SedWedge *w = bMalloc((int)sizeof(SedWedge), "Sound.cpp", 388, 16);

    sedwedge_construct(w);
    gSoundSedWedge = w;
    return w;
}

SedWedge *sedwedge_sound_instance(void)
{
    return gSoundSedWedge;
}

static const char *const kSpeechLanguages[6] = {
    "English", "French", "German", "Italian", "Spanish", "English",
};

void sedwedge_load_localized_speech_files(int32_t lang)
{
    char hdr[64], dat[64], ban[64];
    const char *name;

    if (!SoundEnabled || (uint32_t)lang >= 6)
        return;
    // A demo disc's is "DemoDisk" whatever the language.
    name = kSpeechLanguages[lang];
    snprintf(hdr, sizeof(hdr), "Sound\\Speech\\%sHDR.pck", name);
    snprintf(ban, sizeof(ban), "Sound\\Speech\\%sBAN.pck", name);
    snprintf(dat, sizeof(dat), "Sound\\Speech\\%sDAT.pck", name);
    // The port's: no wedge, no speech. Retail's is made at boot.
    if (sound_get()->speechEnabled && gSoundSedWedge != NULL)
        sedwedge_initialize(gSoundSedWedge, "Sound\\Speech\\Events.evt", hdr,
                            dat, ban, gSoundSpeechSlot);
}

void sedwedge_unload_localized_speech_files(void)
{
    if (SoundEnabled && gSoundSedWedge != NULL)
        sedwedge_cleanup(gSoundSedWedge);
}
