#include "avimovie.h"

#include <stdlib.h>
#include <string.h>

#include "bsnd.h"

static uint32_t rd32(const uint8_t* p)
{
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16
         | (uint32_t)p[3] << 24;
}

static uint16_t rd16(const uint8_t* p)
{
    return (uint16_t)(p[0] | p[1] << 8);
}

static bool read_at(FILE* f, uint32_t off, void* buf, size_t n)
{
    if (fseek(f, (long)off, SEEK_SET) != 0) return false;
    return fread(buf, 1, n, f) == n;
}

// -- the container -----------------------------------------------------------

int avi_chunk_stream(uint32_t tag)
{
    int a = (int)(tag & 0xff) - '0', b = (int)(tag >> 8 & 0xff) - '0';
    if (a < 0 || a > 9 || b < 0 || b > 9) return -1;
    return a * 10 + b;
}

// One strl: its strh and strf, for stream number `n`.
static void parse_strl(FILE* f, uint32_t off, uint32_t end, int n, AviInfo* o)
{
    uint8_t  h[8], strh[56];
    uint32_t type = 0;

    while (off + 8 <= end && read_at(f, off, h, 8)) {
        uint32_t tag = rd32(h), size = rd32(h + 4);
        uint32_t body = off + 8;
        if (tag == AVI_TAG('s', 't', 'r', 'h') && size >= 36
            && read_at(f, body, strh, size < 56 ? size : 56)) {
            type = rd32(strh);
            if (type == AVI_TAG('v', 'i', 'd', 's') && o->videoStream < 0) {
                o->videoStream = n;
                o->scale  = rd32(strh + 20);
                o->rate   = rd32(strh + 24);
                o->frames = rd32(strh + 32);
            } else if (type == AVI_TAG('a', 'u', 'd', 's') && o->audioStream < 0) {
                o->audioStream = n;
            }
        } else if (tag == AVI_TAG('s', 't', 'r', 'f')) {
            uint8_t b[20];
            if (type == AVI_TAG('v', 'i', 'd', 's') && o->videoStream == n
                && size >= 20 && read_at(f, body, b, 20)) {
                o->width      = rd32(b + 4);
                o->bmpHeight  = (int32_t)rd32(b + 8);
                o->height     = (uint32_t)(o->bmpHeight < 0 ? -o->bmpHeight
                                                            : o->bmpHeight);
                o->videoCodec = rd32(b + 16);
            } else if (type == AVI_TAG('a', 'u', 'd', 's') && o->audioStream == n
                       && size >= 16 && read_at(f, body, b, 16)) {
                o->audioFormat   = rd16(b);
                o->audioChannels = rd16(b + 2);
                o->audioRate     = rd32(b + 4);
                o->audioBits     = rd16(b + 14);
            }
        }
        off = body + size + (size & 1);
    }
}

bool avi_parse(FILE* f, AviInfo* o)
{
    uint8_t  h[12];
    uint32_t off, end;
    int      streams = 0;

    memset(o, 0, sizeof(*o));
    o->videoStream = o->audioStream = -1;
    if (!f || !read_at(f, 0, h, 12)) return false;
    if (rd32(h) != AVI_TAG('R', 'I', 'F', 'F')
        || rd32(h + 8) != AVI_TAG('A', 'V', 'I', ' '))
        return false;
    end = 8 + rd32(h + 4);

    for (off = 12; off + 12 <= end && read_at(f, off, h, 12);) {
        uint32_t tag = rd32(h), size = rd32(h + 4), kind = rd32(h + 8);
        if (tag == AVI_TAG('L', 'I', 'S', 'T') && kind == AVI_TAG('h', 'd', 'r', 'l')) {
            uint32_t sub = off + 12, subEnd = off + 8 + size;
            while (sub + 12 <= subEnd && read_at(f, sub, h, 12)) {
                uint32_t st = rd32(h), ss = rd32(h + 4);
                if (st == AVI_TAG('L', 'I', 'S', 'T')
                    && rd32(h + 8) == AVI_TAG('s', 't', 'r', 'l'))
                    parse_strl(f, sub + 12, sub + 8 + ss, streams++, o);
                sub += 8 + ss + (ss & 1);
            }
        } else if (tag == AVI_TAG('L', 'I', 'S', 'T')
                   && kind == AVI_TAG('m', 'o', 'v', 'i')) {
            o->moviStart = off + 12;
            o->moviEnd   = off + 8 + size;
            break;
        }
        off += 8 + size + (size & 1);
    }
    return o->videoStream >= 0 && o->moviStart != 0 && o->width && o->height
        && o->scale && o->rate;
}

bool avi_next_chunk(FILE* f, const AviInfo* info, uint32_t* pos, AviChunk* out)
{
    uint8_t h[12];

    while (*pos + 8 <= info->moviEnd) {
        uint32_t tag, size;
        if (!read_at(f, *pos, h, 8)) return false;
        tag = rd32(h);
        size = rd32(h + 4);
        if (tag == AVI_TAG('L', 'I', 'S', 'T')) {
            // `LIST rec `: its chunks are the stream's, so step inside.
            *pos += 12;
            continue;
        }
        if (size > info->moviEnd - (*pos + 8)) return false;
        out->tag = tag;
        out->offset = *pos + 8;
        out->size = size;
        *pos += 8 + size + (size & 1);
        if (tag == AVI_TAG('J', 'U', 'N', 'K')) continue;
        return true;
    }
    return false;
}

// -- the player ------------------------------------------------------------

bool avimovie_open(AviMovie* m, const char* path)
{
    memset(m, 0, sizeof(*m));
    m->shown = -1;
    m->file = fopen(path, "rb");
    if (!m->file) return false;
    // Chunk headers and payloads alternate, all forwards: a buffer a frame
    // or two long makes each a read from memory rather than from the card.
    setvbuf(m->file, NULL, _IOFBF, 64 << 10);
    if (!avi_parse(m->file, &m->info)
        || m->info.videoCodec != AVI_TAG('M', 'V', '3', '0')
        || mv3_init(&m->codec, (int)m->info.width, (int)m->info.height) != MV3_OK) {
        avimovie_close(m);
        return false;
    }
    m->pos = m->info.moviStart;
    return true;
}

void avimovie_close(AviMovie* m)
{
    if (m->file) fclose(m->file);
    m->file = NULL;
    mv3_free(&m->codec);
    free(m->frameBuf);
    m->frameBuf = NULL;
    m->frameCap = 0;
}

uint32_t avimovie_frame_at(const AviMovie* m, double seconds)
{
    double f;
    if (seconds <= 0.0) return 0;
    f = seconds * (double)m->info.rate / (double)m->info.scale;
    return f >= 4294967295.0 ? 0xffffffffu : (uint32_t)f;
}

double avimovie_duration(const AviMovie* m)
{
    return (double)m->info.frames * (double)m->info.scale / (double)m->info.rate;
}

static bool decode_chunk(AviMovie* m, const AviChunk* c)
{
    int rc;
    if (c->size > m->frameCap) {
        uint8_t* b = (uint8_t*)realloc(m->frameBuf, c->size);
        if (!b) { m->error = MV3_ERR_ALLOC; return false; }
        m->frameBuf = b;
        m->frameCap = c->size;
    }
    if (!read_at(m->file, c->offset, m->frameBuf, c->size)) {
        m->error = MV3_ERR_SHORT;
        return false;
    }
    rc = mv3_decode(&m->codec, m->frameBuf, c->size);
    if (rc != MV3_OK) { m->error = rc; return false; }
    return true;
}

bool avimovie_advance(AviMovie* m, uint32_t target)
{
    AviChunk c;
    bool changed = false;

    if (m->info.frames && target >= m->info.frames) target = m->info.frames - 1;
    while (!m->ended && !m->error && (m->shown < 0 || (uint32_t)m->shown < target)) {
        int s;
        if (!avi_next_chunk(m->file, &m->info, &m->pos, &c)) {
            m->ended = true;
            break;
        }
        s = avi_chunk_stream(c.tag);
        if (s == m->info.audioStream) {
            if (m->audio) m->audio(m->audioUser, m->file, &c);
            continue;
        }
        if (s != m->info.videoStream) continue;
        if (m->nextFrame < target) {
            m->nextFrame++;
            m->skipped++;
            continue;
        }
        if (!decode_chunk(m, &c)) break;
        m->shown = (int32_t)m->nextFrame++;
        m->decoded++;
        changed = true;
    }
    return changed;
}

// Update's test is `decoded < target || !shown` (0x0023833c): +12 counts
// the frames decoded and +1088 is set by the first. Past that it takes the
// ring buffer's next frame, and with none left and the file used up
// answers 0 (0x002383c8). Retail's decode failing is not seen -- it draws
// whatever came out -- where the port stops the movie.
int avimovie_step(AviMovie* m, uint32_t target, bool* changed)
{
    AviChunk c;

    if (changed) *changed = false;
    if (m->error || m->ended) return 0;
    if (m->shown >= 0 && m->decoded >= target) return 1;
    for (;;) {
        int s;
        if (!avi_next_chunk(m->file, &m->info, &m->pos, &c)) {
            m->ended = true;
            return 0;
        }
        s = avi_chunk_stream(c.tag);
        if (s == m->info.audioStream) {
            if (m->audio) m->audio(m->audioUser, m->file, &c);
            continue;
        }
        if (s != m->info.videoStream) continue;
        if (!decode_chunk(m, &c)) return 0;
        m->shown = (int32_t)m->nextFrame++;
        m->decoded++;
        if (changed) *changed = true;
        return 1;
    }
}

bool avimovie_done(const AviMovie* m)
{
    if (m->error || m->ended) return true;
    return m->info.frames && m->shown >= 0
        && (uint32_t)m->shown + 1 >= m->info.frames;
}

// -- the sound ---------------------------------------------------------------

// The SPU's predictor pairs, in 64ths. A predictor past 4 is taken as 0, as
// audio_convert.py takes it. No movie has one, and none sets a frame's flag
// byte either, so the flags are not read at all.
static const int8_t kSpuFilter[5][2] = {
    { 0, 0 }, { 60, 0 }, { 115, -52 }, { 98, -55 }, { 122, -60 },
};

static bool grow(AviSound* s, uint32_t n)
{
    uint32_t cap;
    uint8_t* b;
    if (s->len + n <= s->cap) return true;
    for (cap = s->cap ? s->cap : AVISOUND_PAIR; cap < s->len + n; cap *= 2) {}
    b = (uint8_t*)realloc(s->buf, cap);
    if (!b) return false;
    s->buf = b;
    s->cap = cap;
    return true;
}

bool avisound_push(AviSound* s, const void* p, uint32_t n)
{
    if (!grow(s, n)) return false;
    memcpy(s->buf + s->len, p, n);
    s->len += n;
    s->pushed += n;
    return true;
}

bool avisound_read(AviSound* s, FILE* f, const AviChunk* c)
{
    if (!grow(s, c->size) || !read_at(f, c->offset, s->buf + s->len, c->size))
        return false;
    s->len += c->size;
    s->pushed += c->size;
    return true;
}

uint32_t avisound_ready(const AviSound* s)
{
    uint32_t pairs = s->len / AVISOUND_PAIR;
    return pairs ? pairs * AVISOUND_FRAMES - s->frame : 0;
}

// One frame of one channel: 28 samples to out[0], out[2], ...
static void spu_frame(const uint8_t* f, int32_t* hist, int16_t* out)
{
    unsigned pred = f[0] >> 4, shift = f[0] & 15;
    int32_t  h1 = hist[0], h2 = hist[1], f0, f1;
    int      k;

    if (pred > 4) pred = 0;
    f0 = kSpuFilter[pred][0];
    f1 = kSpuFilter[pred][1];
    for (k = 0; k < AVISOUND_SAMPLES; k++) {
        // Low nibble first; the delta's sign is bit 15 of nibble << 12.
        int32_t v = (int16_t)(uint16_t)(((f[2 + k / 2] >> ((k & 1) * 4)) & 15) << 12);
        v = (v >> shift) + ((f0 * h1 + f1 * h2 + 32) >> 6);
        if (v > 32767) v = 32767;
        if (v < -32768) v = -32768;
        h2 = h1;
        h1 = v;
        out[2 * k] = (int16_t)v;
    }
    hist[0] = h1;
    hist[1] = h2;
}

uint32_t avisound_pull(AviSound* s, int16_t* out, uint32_t frames)
{
    uint32_t done = 0;
    while (done < frames && s->len >= AVISOUND_PAIR) {
        const uint8_t* l = s->buf + s->frame * 16;
        spu_frame(l, s->hist[0], out);
        spu_frame(l + AVISOUND_BLOCK, s->hist[1], out + 1);
        out += 2 * AVISOUND_SAMPLES;
        done++;
        if (++s->frame == AVISOUND_FRAMES) {
            s->len -= AVISOUND_PAIR;
            memmove(s->buf, s->buf + AVISOUND_PAIR, s->len);
            s->frame = 0;
        }
    }
    return done * AVISOUND_SAMPLES;
}

void avisound_free(AviSound* s)
{
    free(s->buf);
    memset(s, 0, sizeof(*s));
}

uint32_t avisound_rate_hz(void)
{
    return bsnd_spu_to_hz(bsnd_hz_to_spu(AVISOUND_RATE));
}

// -- the 3DS half ------------------------------------------------------------

#ifdef __3DS__

// Takes back every wave the DSP has finished, then decodes into the free
// ones, in order, as far as the stream has whole pairs.
static void feed(AviPlayer* p)
{
    if (!p->sound) return;
    while (p->waveCount
           && p->waves[p->waveHead].wave.status == NDSP_WBUF_DONE) {
        p->waveHead = (p->waveHead + 1) % AVIMOVIE_WAVES;
        p->waveCount--;
    }
    while (p->waveCount < AVIMOVIE_WAVES && avisound_ready(&p->snd)) {
        AviWave* w = &p->waves[(p->waveHead + p->waveCount) % AVIMOVIE_WAVES];
        uint32_t n = avisound_pull(&p->snd, w->pcm, AVIMOVIE_WAVE_FRAMES);
        DSP_FlushDataCache(w->pcm, n * 4);
        memset(&w->wave, 0, sizeof(w->wave));
        w->wave.data_vaddr = w->pcm;
        w->wave.nsamples = n;
        ndspChnWaveBufAdd(AVIMOVIE_CHANNEL, &w->wave);
        p->waveCount++;
        p->audioSamples += n;
    }
}

static void stop_sound(AviPlayer* p)
{
    int i;
    if (p->sound) {
        ndspChnWaveBufClear(AVIMOVIE_CHANNEL);
        // Let the DSP let go of the buffer it was reading.
        for (i = 0; i < 20 && ndspChnIsPlaying(AVIMOVIE_CHANNEL); i++)
            svcSleepThread(1000000);
    }
    p->sound = false;
    p->waveHead = p->waveCount = 0;
}

// Each sound chunk joins the stream. One that cannot be held ends the sound
// rather than letting the pairs slip out of step, which would put the left
// channel's bytes through the right's history.
static void queue_audio(void* user, FILE* f, const AviChunk* c)
{
    AviPlayer* p = (AviPlayer*)user;
    if (!p->sound) return;
    if (!avisound_read(&p->snd, f, c)) {
        stop_sound(p);
        return;
    }
    feed(p);
}

static bool start_sound(AviPlayer* p)
{
    float mix[12];
    int i;

    if (p->movie.info.audioStream < 0) return false;
    for (i = 0; i < AVIMOVIE_WAVES; i++) {
        p->waves[i].pcm = (int16_t*)linearAlloc(
            AVIMOVIE_WAVE_FRAMES * AVISOUND_SAMPLES * 2 * sizeof(int16_t));
        if (!p->waves[i].pcm) return false;
    }
    ndspChnReset(AVIMOVIE_CHANNEL);
    ndspChnSetInterp(AVIMOVIE_CHANNEL, NDSP_INTERP_LINEAR);
    ndspChnSetRate(AVIMOVIE_CHANNEL, (float)avisound_rate_hz());
    ndspChnSetFormat(AVIMOVIE_CHANNEL, NDSP_FORMAT_STEREO_PCM16);
    memset(mix, 0, sizeof(mix));
    mix[0] = mix[1] = 1.0f;
    ndspChnSetMix(AVIMOVIE_CHANNEL, mix);
    return true;
}

static void show(AviPlayer* p)
{
    mv3_to_tiled_rgba8(&p->movie.codec, (uint32_t*)p->tex.data, p->tex.width);
    C3D_TexFlush(&p->tex);
}

static void free_waves(AviPlayer* p)
{
    int i;
    for (i = 0; i < AVIMOVIE_WAVES; i++) {
        if (p->waves[i].pcm) linearFree(p->waves[i].pcm);
        p->waves[i].pcm = NULL;
    }
}

// The GPU's sides are 8 to 1024 and powers of two.
static u16 pot(uint32_t n)
{
    u16 p = 8;
    while (p < n && p < 1024) p <<= 1;
    return p;
}

// Both opens: the file, a cleared texture and the sound, no frame yet.
static bool open_player(AviPlayer* p, const char* path)
{
    memset(p, 0, sizeof(*p));
    if (!avimovie_open(&p->movie, path)) return false;
    if (p->movie.info.width > 1024 || p->movie.info.height > 1024
        || !C3D_TexInit(&p->tex, pot(p->movie.info.width),
                        pot(p->movie.info.height), GPU_RGBA8)) {
        avimovie_close(&p->movie);
        return false;
    }
    C3D_TexSetFilter(&p->tex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(&p->tex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    memset(p->tex.data, 0, p->tex.size);

    // A movie with no sound, or no memory for it, still plays its picture.
    p->sound = start_sound(p);
    if (!p->sound) free_waves(p);
    p->movie.audio = queue_audio;
    p->movie.audioUser = p;
    return true;
}

bool aviplayer_open(AviPlayer* p, const char* path)
{
    if (!open_player(p, path)) return false;
    if (avimovie_advance(&p->movie, 0)) show(p);
    else C3D_TexFlush(&p->tex);
    p->startTick = svcGetSystemTick();
    p->started = true;
    return true;
}

bool aviplayer_init(AviPlayer* p, const char* path)
{
    if (!open_player(p, path)) return false;
    C3D_TexFlush(&p->tex);
    return true;
}

void aviplayer_close(AviPlayer* p)
{
    stop_sound(p);
    free_waves(p);
    avisound_free(&p->snd);
    avimovie_close(&p->movie);
    if (p->tex.data) C3D_TexDelete(&p->tex);
    p->tex.data = NULL;
}

bool aviplayer_drive(AviPlayer* p)
{
    double t = (double)(svcGetSystemTick() - p->startTick) / SYSCLOCK_ARM11;
    u64    t0 = svcGetSystemTick(), t1;
    bool   changed = avimovie_advance(&p->movie, avimovie_frame_at(&p->movie, t));
    t1 = svcGetSystemTick();
    p->stepTicks += t1 - t0;
    if (changed) {
        show(p);
        p->showTicks += svcGetSystemTick() - t1;
    }
    p->calls++;
    feed(p);
    if (p->movie.error) return true;
    return avimovie_done(&p->movie) && t >= avimovie_duration(&p->movie);
}

// Update's clock is eVBlankCounter over the TV's rate, less what it read on
// the first call (0x00238238); this one is the console's tick.
bool aviplayer_update(AviPlayer* p)
{
    double t;
    bool   changed;
    int    r;
    u64    t0, t1;

    if (!p->started) {
        p->startTick = svcGetSystemTick();
        p->started = true;
    }
    t0 = svcGetSystemTick();
    t = (double)(t0 - p->startTick) / SYSCLOCK_ARM11;
    r = avimovie_step(&p->movie, avimovie_frame_at(&p->movie, t), &changed);
    t1 = svcGetSystemTick();
    p->stepTicks += t1 - t0;
    if (changed) {
        show(p);
        p->showTicks += svcGetSystemTick() - t1;
    }
    p->calls++;
    feed(p);
    return r != 0;
}
#endif
