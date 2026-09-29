// The jukebox's sample on the 3DS. See jbstream.h.
#include "jbstream.h"

#include <string.h>

// Sony's predictor pairs, scaled by 64 (avimovie.c and audio_convert.py
// have the same).
static const int32_t kFilter[5][2] = {
    { 0, 0 }, { 60, 0 }, { 115, -52 }, { 98, -55 }, { 122, -60 },
};

void jbs_decoder_reset(JBSDecoder* d)
{
    memset(d, 0, sizeof *d);
}

// One frame of one channel: 28 samples to out[0], out[2], ...
static void spu_frame(const uint8_t* f, int32_t* hist, int16_t* out)
{
    unsigned pred = f[0] >> 4, shift = f[0] & 15;
    int32_t  h1 = hist[0], h2 = hist[1];

    if (pred > 4) {
        pred = 0;
    }
    int32_t f0 = kFilter[pred][0], f1 = kFilter[pred][1];
    for (unsigned k = 0; k < JBS_SAMPLES; k++) {
        // Low nibble first; the delta's sign is bit 15 of nibble << 12.
        int32_t v = (int16_t)(uint16_t)(((f[2 + k / 2] >> ((k & 1) * 4)) & 15)
                                        << 12);
        v = (v >> shift) + ((f0 * h1 + f1 * h2 + 32) >> 6);
        if (v > 32767) {
            v = 32767;
        }
        if (v < -32768) {
            v = -32768;
        }
        h2 = h1;
        h1 = v;
        out[2 * k] = (int16_t)v;
    }
    hist[0] = h1;
    hist[1] = h2;
}

uint32_t jbs_decode(JBSDecoder* d, const uint8_t* pair, int16_t* out,
                    uint32_t frames)
{
    uint32_t n = 0;
    while (n < frames && !d->ended && d->frame < JBS_FRAMES) {
        const uint8_t* l = pair + d->frame * JBS_FRAME;
        const uint8_t* r = l + JBS_BLOCK;
        if (l[1] == 7 || r[1] == 7) {
            d->ended = true;
            break;
        }
        spu_frame(l, d->hist[0], out);
        spu_frame(r, d->hist[1], out + 1);
        out += 2 * JBS_SAMPLES;
        n++;
        d->frame++;
        if (l[1] == 1 || r[1] == 1) {
            d->ended = true;
        }
    }
    return n * JBS_SAMPLES;
}

// -- the 3DS half ------------------------------------------------------------

#ifdef __3DS__

#include <3ds.h>
#include <stdio.h>
#include <stdlib.h>

#include "gamedata.h"

#define JBS_WAVES        8
#define JBS_WAVE_FRAMES  128                 // 3584 samples, 112 ms
#define JBS_PREBUFFER    4                   // waves queued to be "buffered"

// What the worker saw, for the poll to hand on.
enum { EV_BUFFERED = 1, EV_PLAY_END = 2, EV_FADE_END = 4 };

typedef struct {
    int16_t*    pcm;
    ndspWaveBuf wave;
} JBSWave;

typedef struct {
    LightLock    lock;
    LightEvent   wake;
    Thread       worker;
    bool         quit;

    // The worker's, under the lock: the tune and the ring.
    FILE*        file;
    uint32_t     left;             // bytes of the tune not yet read
    uint8_t*     pair;
    bool         havePair;
    JBSDecoder   dec;
    bool         loaded;           // a tune is loaded and not stopped
    bool         announced;        // its buffered event is given
    bool         endSent;          // its play end is given
    JBSWave      waves[JBS_WAVES];
    uint32_t     head, count;
    // For the log: pairs read, and samples queued and given back played.
    uint32_t     pairsRead, samplesQueued, samplesPlayed;

    uint32_t     events;           // EV_*, atomic

    // The main thread's.
    bool         created;
    bool         played, paused;
    uint32_t     category;
    float        scale, playVolume;
    float        fadeFrom, fadeTo, level;
    uint64_t     fadeStart;
    uint32_t     fadeMs;
    bool         fading;
    float        mixSet;
    const float* volumes;
    void       (*log)(int line);
} JBStream;

static JBStream g_js;

// The disc's SOUND\JukeboxM.JBC is the card's SOUND/JUKEBOXM.JBC under the
// data directory; FAT does not mind the case.
static FILE* open_card(const char* path)
{
    char rel[GAMEDATA_MAX_PATH], full[GAMEDATA_MAX_PATH];
    size_t i;
    for (i = 0; path[i] && i + 1 < sizeof rel; i++) {
        rel[i] = path[i] == '\\' ? '/' : path[i];
    }
    rel[i] = 0;
    if (path[i] || !gamedata_path(rel, full, sizeof full)) {
        return NULL;
    }
    return fopen(full, "rb");
}

static void post(JBStream* s, uint32_t ev)
{
    __atomic_fetch_or(&s->events, ev, __ATOMIC_SEQ_CST);
}

// The next pair of blocks off the card, while the tune has one whole.
static bool next_pair(JBStream* s)
{
    if (!s->file || s->left < JBS_PAIR) {
        return false;
    }
    if (fread(s->pair, 1, JBS_PAIR, s->file) != JBS_PAIR) {
        return false;
    }
    s->left -= JBS_PAIR;
    s->pairsRead++;
    s->havePair = true;
    s->dec.frame = 0;
    return true;
}

// Under the lock: the finished waves back, the free ones filled in order,
// and the events that follow.
static void pump(JBStream* s)
{
    if (!s->loaded) {
        return;
    }
    while (s->count && s->waves[s->head].wave.status == NDSP_WBUF_DONE) {
        s->samplesPlayed += s->waves[s->head].wave.nsamples;
        s->head = (s->head + 1) % JBS_WAVES;
        s->count--;
    }
    while (s->count < JBS_WAVES && !s->dec.ended) {
        JBSWave* w = &s->waves[(s->head + s->count) % JBS_WAVES];
        uint32_t n = 0;
        while (n < JBS_WAVE_FRAMES * JBS_SAMPLES && !s->dec.ended) {
            if ((!s->havePair || s->dec.frame >= JBS_FRAMES) &&
                !next_pair(s)) {
                s->dec.ended = true;         // short or unreadable: stop
                break;
            }
            n += jbs_decode(&s->dec, s->pair, w->pcm + 2 * n,
                            JBS_WAVE_FRAMES - n / JBS_SAMPLES);
        }
        if (!n) {
            break;
        }
        DSP_FlushDataCache(w->pcm, n * 4);
        memset(&w->wave, 0, sizeof w->wave);
        w->wave.data_vaddr = w->pcm;
        w->wave.nsamples = n;
        ndspChnWaveBufAdd(JBS_CHANNEL, &w->wave);
        s->samplesQueued += n;
        s->count++;
    }
    if (!s->announced && (s->count >= JBS_PREBUFFER || s->dec.ended)) {
        s->announced = true;
        post(s, EV_BUFFERED);
    }
    if (s->announced && s->dec.ended && !s->count && !s->endSent) {
        s->endSent = true;
        post(s, EV_PLAY_END);
    }
}

static void worker_main(void* arg)
{
    JBStream* s = (JBStream*)arg;
    for (;;) {
        LightEvent_WaitTimeout(&s->wake, 10 * 1000000LL);
        LightLock_Lock(&s->lock);
        if (s->quit) {
            LightLock_Unlock(&s->lock);
            return;
        }
        pump(s);
        LightLock_Unlock(&s->lock);
    }
}

static void set_paused(JBStream* s)
{
    ndspChnSetPaused(JBS_CHANNEL, !s->played || s->paused);
}

// Under the lock: the channel emptied and the tune let go.
static void halt(JBStream* s)
{
    ndspChnWaveBufClear(JBS_CHANNEL);
    // Let the DSP let go of the buffer it was reading.
    for (int i = 0; i < 20 && ndspChnIsPlaying(JBS_CHANNEL); i++) {
        svcSleepThread(1000000);
    }
    if (s->file) {
        fclose(s->file);
        s->file = NULL;
    }
    s->loaded = false;
    s->havePair = false;
    s->head = s->count = 0;
    for (int i = 0; i < JBS_WAVES; i++) {
        memset(&s->waves[i].wave, 0, sizeof s->waves[i].wave);
    }
}

// -- the host ---------------------------------------------------------------

static void h_create(void* ctx, uint32_t rate)
{
    JBStream* s = (JBStream*)ctx;
    if (s->created) {
        return;
    }
    s->pair = (uint8_t*)malloc(JBS_PAIR);
    for (int i = 0; i < JBS_WAVES; i++) {
        s->waves[i].pcm = (int16_t*)linearAlloc(
            JBS_WAVE_FRAMES * JBS_SAMPLES * 2 * sizeof(int16_t));
        if (!s->waves[i].pcm) {
            return;
        }
    }
    if (!s->pair) {
        return;
    }
    ndspChnReset(JBS_CHANNEL);
    ndspChnSetInterp(JBS_CHANNEL, NDSP_INTERP_LINEAR);
    ndspChnSetRate(JBS_CHANNEL, (float)rate);
    ndspChnSetFormat(JBS_CHANNEL, NDSP_FORMAT_STEREO_PCM16);
    float mix[12];
    memset(mix, 0, sizeof mix);
    ndspChnSetMix(JBS_CHANNEL, mix);
    s->mixSet = 0.0f;
    ndspChnSetPaused(JBS_CHANNEL, true);

    LightLock_Init(&s->lock);
    LightEvent_Init(&s->wake, RESET_ONESHOT);
    s->quit = false;
    // Above the game's thread, so the ring never waits on a frame; each
    // wake is a few decoded frames or a read that sleeps in the kernel.
    s32 prio = 0x30;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    if (prio > 0x19) {
        prio--;
    }
    s->worker = threadCreate(worker_main, s, 16 << 10, prio, -2, false);
    s->created = s->worker != NULL;
}

static void h_destroy(void* ctx)
{
    JBStream* s = (JBStream*)ctx;
    if (!s->created) {
        return;
    }
    LightLock_Lock(&s->lock);
    s->quit = true;
    halt(s);
    LightLock_Unlock(&s->lock);
    LightEvent_Signal(&s->wake);
    threadJoin(s->worker, U64_MAX);
    threadFree(s->worker);
    s->worker = NULL;
    ndspChnReset(JBS_CHANNEL);
    for (int i = 0; i < JBS_WAVES; i++) {
        if (s->waves[i].pcm) {
            linearFree(s->waves[i].pcm);
        }
        s->waves[i].pcm = NULL;
    }
    free(s->pair);
    s->pair = NULL;
    s->created = false;
}

// Play__7bSamplePCcUiUi: the tune from `offset` for `size` bytes, buffered
// but held until Play.
static void h_load(void* ctx, const char* path, uint32_t offset,
                   uint32_t size)
{
    JBStream* s = (JBStream*)ctx;
    if (!s->created) {
        return;
    }
    LightLock_Lock(&s->lock);
    halt(s);
    s->file = open_card(path);
    if (s->file && fseek(s->file, (long)offset, SEEK_SET) != 0) {
        fclose(s->file);
        s->file = NULL;
    }
    s->left = size;
    jbs_decoder_reset(&s->dec);
    s->loaded = true;
    s->announced = false;
    s->endSent = false;
    __atomic_store_n(&s->events, 0, __ATOMIC_SEQ_CST);
    LightLock_Unlock(&s->lock);
    s->played = false;
    s->fading = false;
    s->level = 1.0f;
    set_paused(s);
    LightEvent_Signal(&s->wake);
}

static void h_play(void* ctx, float volume, float a, float b)
{
    JBStream* s = (JBStream*)ctx;
    (void)a;
    (void)b;
    s->playVolume = volume;
    s->played = true;
    if (s->created) {
        set_paused(s);
    }
}

static void h_stop(void* ctx)
{
    JBStream* s = (JBStream*)ctx;
    if (!s->created) {
        return;
    }
    LightLock_Lock(&s->lock);
    halt(s);
    __atomic_store_n(&s->events, 0, __ATOMIC_SEQ_CST);
    LightLock_Unlock(&s->lock);
    s->played = false;
    s->fading = false;
    set_paused(s);
}

static void h_pause(void* ctx, bool on)
{
    JBStream* s = (JBStream*)ctx;
    s->paused = on;
    if (s->created) {
        set_paused(s);
    }
}

// Fade__7bSamplefUi: from where the level is to `to` over `ms`.
static void h_fade(void* ctx, float to, uint32_t ms)
{
    JBStream* s = (JBStream*)ctx;
    s->fadeFrom = s->level;
    s->fadeTo = to;
    s->fadeMs = ms;
    s->fadeStart = svcGetSystemTick();
    s->fading = true;
}

static void h_cleanup(void* ctx)
{
    h_stop(ctx);
}

static void h_category(void* ctx, uint32_t cat)
{
    ((JBStream*)ctx)->category = cat;
}

static void h_scale(void* ctx, float v)
{
    ((JBStream*)ctx)->scale = v;
}

static void* h_open(void* ctx, const char* path)
{
    (void)ctx;
    return open_card(path);
}

static int h_read(void* ctx, void* file, void* buf, uint32_t n)
{
    (void)ctx;
    return (int)fread(buf, 1, n, (FILE*)file);
}

static void h_close(void* ctx, void* file)
{
    (void)ctx;
    fclose((FILE*)file);
}

static int h_sound_up(void* ctx)
{
    (void)ctx;
    return 1;          // the host exists only once ndsp is up
}

static void h_assert(void* ctx, int line)
{
    JBStream* s = (JBStream*)ctx;
    if (s->log) {
        s->log(line);
    }
}

static const JBHost kHost = {
    &g_js, h_create, h_destroy, h_load, h_play, h_stop, h_pause, h_fade,
    h_cleanup, h_category, h_scale, h_open, h_read, h_close, h_sound_up,
    h_assert,
};

const JBHost* jbstream_host(const float* volumes, void (*log)(int line))
{
    memset(&g_js, 0, sizeof g_js);
    g_js.volumes = volumes;
    g_js.log = log;
    g_js.scale = 1.0f;
    g_js.playVolume = 1.0f;
    g_js.level = 1.0f;
    g_js.category = 0xFFFFFFFFu;
    g_js.mixSet = -1.0f;
    return &kHost;
}

void jbstream_poll(JBPlayer* p)
{
    JBStream* s = &g_js;
    if (!s->created) {
        return;
    }
    if (s->fading) {
        uint64_t ms = (svcGetSystemTick() - s->fadeStart) / CPU_TICKS_PER_MSEC;
        if (ms >= s->fadeMs) {
            s->level = s->fadeTo;
            s->fading = false;
            post(s, EV_FADE_END);
        } else {
            s->level = s->fadeFrom +
                       (s->fadeTo - s->fadeFrom) * (float)ms / (float)s->fadeMs;
        }
    }
    // bSound::GetCategoryVolume's rule: past the sixteen, full.
    float cat = s->category < 16 && s->volumes ? s->volumes[s->category] : 1.0f;
    float v = s->scale * s->playVolume * s->level * cat;
    if (v < 0.0f) {
        v = 0.0f;
    }
    if (v != s->mixSet) {
        float mix[12];
        memset(mix, 0, sizeof mix);
        mix[0] = mix[1] = v;
        ndspChnSetMix(JBS_CHANNEL, mix);
        s->mixSet = v;
    }
    uint32_t ev = __atomic_exchange_n(&s->events, 0, __ATOMIC_SEQ_CST);
    if (ev & EV_BUFFERED) {
        jb_sample_callback(p, JB_EVENT_BUFFERED);
    }
    if (ev & EV_FADE_END) {
        jb_sample_callback(p, JB_EVENT_FADE_END);
    }
    if (ev & EV_PLAY_END) {
        jb_sample_callback(p, JB_EVENT_PLAY_END);
    }
}

void jbstream_stats(JBStreamStats* out)
{
    JBStream* s = &g_js;
    memset(out, 0, sizeof *out);
    if (!s->created) {
        return;
    }
    LightLock_Lock(&s->lock);
    out->pairsRead = s->pairsRead;
    out->samplesQueued = s->samplesQueued;
    out->samplesPlayed = s->samplesPlayed;
    LightLock_Unlock(&s->lock);
    out->mix = s->mixSet;
}

#endif
