// The speech's stream on the 3DS. See bsndstream.h.
#include "bsndstream.h"

#include <string.h>

// Sony's predictor pairs, scaled by 64 (audio_convert.py, jbstream.c).
static const int32_t kFilter[5][2] = {
    { 0, 0 }, { 60, 0 }, { 115, -52 }, { 98, -55 }, { 122, -60 },
};

void bss_decoder_reset(BssDecoder* d)
{
    memset(d, 0, sizeof *d);
}

uint32_t bss_decode(BssDecoder* d, const uint8_t* in, uint32_t frames,
                    int16_t* out)
{
    uint32_t n = 0;
    while (n < frames && !d->ended) {
        const uint8_t* f = in + n * BSS_FRAME;
        unsigned pred = f[0] >> 4, shift = f[0] & 15;
        int32_t h1 = d->hist[0], h2 = d->hist[1];
        int32_t f0, f1;
        unsigned k;

        if (f[1] == 7) {
            d->ended = true;
            break;
        }
        if (pred > 4) {
            pred = 0;                // the SPU clamps rather than faulting
        }
        f0 = kFilter[pred][0];
        f1 = kFilter[pred][1];
        for (k = 0; k < BSS_SAMPLES; k++) {
            // Low nibble first; the delta's sign is bit 15 of nibble << 12.
            int32_t v = (int16_t)(uint16_t)(((f[2 + k / 2] >> ((k & 1) * 4))
                                             & 15) << 12);
            v = (v >> shift) + ((f0 * h1 + f1 * h2 + 32) >> 6);
            if (v > 32767) {
                v = 32767;
            }
            if (v < -32768) {
                v = -32768;
            }
            h2 = h1;
            h1 = v;
            out[k] = (int16_t)v;
        }
        d->hist[0] = h1;
        d->hist[1] = h2;
        out += BSS_SAMPLES;
        n++;
        if (f[1] == 1) {
            d->ended = true;
        }
    }
    return n;
}

// -- the 3DS half ------------------------------------------------------------

#ifdef __3DS__

#include <3ds.h>
#include <stdio.h>
#include <stdlib.h>

#include "gamedata.h"
#include "threadguard.h"

#define BSS_WAVES        8
#define BSS_WAVE_FRAMES  128                 // 3584 samples, 149 ms at 24 kHz
#define BSS_READ         (BSS_WAVE_FRAMES * BSS_FRAME)   // 2 KB a read

typedef struct {
    int16_t*    pcm;
    ndspWaveBuf wave;
} BssWave;

typedef struct {
    LightLock      lock;
    LightEvent     wake;
    Thread         worker;
    bool           quit;
    bool           created;

    // Under the lock.
    int            ch;               // the stream's channel, -1 for none
    BsndStreamPart parts[BSND_CHAIN_MAX];
    unsigned       count, part;      // the chain, and the part being read
    FILE*          file;
    char           filePath[256];    // what `file` is, kept open across parts
    uint32_t       left;             // the part's bytes not yet read
    BssDecoder     dec;
    bool           done;             // every part read and decoded
    uint8_t*       buf;
    uint32_t       bufLen, bufPos;
    BssWave        waves[BSS_WAVES];
    unsigned       head, n;
    volatile bool  active;           // bsndstream_playing's answer
    BssStats       stats;
} BssStream;

static BssStream g_ss;

static FILE* open_card(const char* path)
{
    char rel[GAMEDATA_MAX_PATH], full[GAMEDATA_MAX_PATH];
    size_t i;
    for (i = 0; path[i] && i + 1 < sizeof rel; i++) {
        rel[i] = path[i] == '\\' ? '/' : path[i];
    }
    rel[i] = 0;
    if (path[i]) {
        return NULL;
    }
    if (strchr(rel, ':')) {
        return fopen(rel, "rb");
    }
    if (!gamedata_path(rel[0] == '/' ? rel + 1 : rel, full, sizeof full)) {
        return NULL;
    }
    return fopen(full, "rb");
}

// Under the lock: the next part opened and sought, or the chain done. The
// decoder's history carries on, as the SPU's did across the IOP's chain;
// only the part's end is forgotten.
static void next_part(BssStream* s)
{
    while (s->part < s->count) {
        const BsndStreamPart* p = &s->parts[s->part++];
        if (!s->file || strcmp(s->filePath, p->path) != 0) {
            if (s->file) {
                fclose(s->file);
            }
            s->file = open_card(p->path);
            strcpy(s->filePath, s->file ? p->path : "");
        }
        if (!s->file || fseek(s->file, (long)p->offset, SEEK_SET) != 0) {
            continue;                // a part that cannot be read is skipped
        }
        s->left = p->size ? p->size : UINT32_MAX;
        s->bufLen = s->bufPos = 0;
        s->dec.ended = false;
        s->stats.parts++;
        return;
    }
    s->done = true;
}

// Under the lock: up to `frames` frames of the chain decoded to `out`,
// moving through the parts. Returns the samples written.
static uint32_t fill(BssStream* s, int16_t* out, uint32_t frames)
{
    uint32_t n = 0;
    while (n < frames && !s->done) {
        uint32_t avail, got;

        if (s->dec.ended) {
            next_part(s);
            continue;
        }
        if (s->bufLen - s->bufPos < BSS_FRAME) {
            // A part ends at its size, or at the file's end; a frame cut
            // short by either is dropped.
            uint32_t want = s->left < BSS_READ ? s->left : BSS_READ;
            size_t r = want ? fread(s->buf, 1, want, s->file) : 0;
            s->left -= (uint32_t)r;
            s->bufLen = (uint32_t)r;
            s->bufPos = 0;
            s->stats.bytes += (uint32_t)r;
            if (r < BSS_FRAME) {
                s->dec.ended = true;
                continue;
            }
        }
        avail = (s->bufLen - s->bufPos) / BSS_FRAME;
        if (avail > frames - n) {
            avail = frames - n;
        }
        got = bss_decode(&s->dec, s->buf + s->bufPos, avail,
                         out + n * BSS_SAMPLES);
        s->bufPos += got * BSS_FRAME;
        n += got;
    }
    return n * BSS_SAMPLES;
}

// Under the lock: the played waves back, the free ones filled, and the
// chain over once the last of it has been heard.
static void pump(BssStream* s)
{
    if (s->ch < 0) {
        return;
    }
    while (s->n && s->waves[s->head].wave.status == NDSP_WBUF_DONE) {
        s->head = (s->head + 1) % BSS_WAVES;
        s->n--;
    }
    while (s->n < BSS_WAVES && !s->done) {
        BssWave* w = &s->waves[(s->head + s->n) % BSS_WAVES];
        uint32_t got = fill(s, w->pcm, BSS_WAVE_FRAMES);
        if (!got) {
            break;
        }
        DSP_FlushDataCache(w->pcm, got * sizeof(int16_t));
        memset(&w->wave, 0, sizeof w->wave);
        w->wave.data_vaddr = w->pcm;
        w->wave.nsamples = got;
        ndspChnWaveBufAdd(s->ch, &w->wave);
        s->stats.samples += got;
        s->n++;
    }
    if (s->done && !s->n) {
        s->active = false;
    }
}

static void worker_main(void* arg)
{
    BssStream* s = (BssStream*)arg;
    for (;;) {
        LightEvent_WaitTimeout(&s->wake, threadguard_wait_ns());
        LightLock_Lock(&s->lock);
        if (s->quit) {
            LightLock_Unlock(&s->lock);
            return;
        }
        pump(s);
        LightLock_Unlock(&s->lock);
    }
}

// Under the lock: the channel emptied and the chain let go.
static void halt(BssStream* s)
{
    if (s->ch >= 0) {
        ndspChnWaveBufClear(s->ch);
        // Let the DSP let go of the buffer it was reading.
        for (int i = 0; i < 20 && ndspChnIsPlaying(s->ch); i++) {
            svcSleepThread(1000000);
        }
    }
    // The file stays open: the next sentence is in the same one.
    s->ch = -1;
    s->count = s->part = 0;
    s->done = true;
    s->active = false;
    s->head = s->n = 0;
    for (int i = 0; i < BSS_WAVES; i++) {
        memset(&s->waves[i].wave, 0, sizeof s->waves[i].wave);
    }
}

bool bsndstream_init(void)
{
    BssStream* s = &g_ss;
    if (s->created) {
        return true;
    }
    memset(s, 0, sizeof *s);
    s->ch = -1;
    s->done = true;
    s->buf = (uint8_t*)malloc(BSS_READ);
    if (!s->buf) {
        return false;
    }
    for (int i = 0; i < BSS_WAVES; i++) {
        s->waves[i].pcm = (int16_t*)linearAlloc(
            BSS_WAVE_FRAMES * BSS_SAMPLES * sizeof(int16_t));
        if (!s->waves[i].pcm) {
            return false;
        }
    }
    LightLock_Init(&s->lock);
    LightEvent_Init(&s->wake, RESET_ONESHOT);
    // Above the game's thread, as the jukebox's worker is.
    s32 prio = 0x30;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    if (prio > 0x19) {
        prio--;
    }
    s->worker = threadCreate(worker_main, s, 16 << 10, prio, -2, false);
    s->created = s->worker != NULL;
    threadguard_watch("speech stream", s->worker, &s->wake);
    return s->created;
}

void bsndstream_exit(void)
{
    BssStream* s = &g_ss;
    if (s->created) {
        LightLock_Lock(&s->lock);
        s->quit = true;
        halt(s);
        LightLock_Unlock(&s->lock);
        threadguard_signal(&s->wake, "speech stream: quit");
        threadJoin(s->worker, U64_MAX);
        threadguard_forget(s->worker);
        threadFree(s->worker);
        s->worker = NULL;
        s->created = false;
    }
    if (s->file) {
        fclose(s->file);
        s->file = NULL;
    }
    for (int i = 0; i < BSS_WAVES; i++) {
        if (s->waves[i].pcm) {
            linearFree(s->waves[i].pcm);
        }
        s->waves[i].pcm = NULL;
    }
    free(s->buf);
    s->buf = NULL;
}

void bsndstream_play(unsigned ch, const BsndStreamPart* parts,
                     unsigned count, uint32_t rate)
{
    BssStream* s = &g_ss;
    if (!s->created || count == 0) {
        return;
    }
    if (count > BSND_CHAIN_MAX) {
        count = BSND_CHAIN_MAX;
    }
    LightLock_Lock(&s->lock);
    halt(s);
    // A patch's channel set-up, for PCM16 instead of DSPADPCM. The driver
    // sets the mix straight after.
    ndspChnReset(ch);
    ndspChnSetInterp(ch, NDSP_INTERP_LINEAR);
    ndspChnSetRate(ch, (float)rate);
    ndspChnSetFormat(ch, NDSP_FORMAT_MONO_PCM16);
    memcpy(s->parts, parts, count * sizeof *parts);
    s->count = count;
    s->part = 0;
    s->ch = (int)ch;
    s->done = false;
    s->active = true;
    bss_decoder_reset(&s->dec);
    s->dec.ended = true;             // so the worker's first fill opens part 0
    LightLock_Unlock(&s->lock);
    // The opens and the reads are the worker's, so the game's frame never
    // waits on the card; the voice counts as playing from here.
    threadguard_signal(&s->wake, "speech stream: play");
}

void bsndstream_stop(unsigned ch)
{
    BssStream* s = &g_ss;
    if (!s->created || s->ch != (int)ch) {
        return;
    }
    LightLock_Lock(&s->lock);
    if (s->ch == (int)ch) {
        halt(s);
    }
    LightLock_Unlock(&s->lock);
}

bool bsndstream_playing(unsigned ch)
{
    return g_ss.created && g_ss.ch == (int)ch && g_ss.active;
}

bool bsndstream_owns(unsigned ch)
{
    return g_ss.created && g_ss.ch == (int)ch;
}

void bsndstream_stats(BssStats* out)
{
    BssStream* s = &g_ss;
    memset(out, 0, sizeof *out);
    if (!s->created) {
        return;
    }
    LightLock_Lock(&s->lock);
    *out = s->stats;
    LightLock_Unlock(&s->lock);
}

#endif
