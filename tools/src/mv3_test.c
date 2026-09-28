// Harness for tools/mv3_check.py: runs the checker's scenarios on mv3.c and
// avimovie.c and prints what the model prints from retail's own code. See
// the checker's docstring for the scenarios.
//
//     mv3_test scenarios.txt > out.txt

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "avimovie.h"
#include "bsnd.h"
#include "mv3.h"

// ------------------------------------------------------------ helpers

static uint32_t crc_table[256];

static uint32_t crc32(const uint8_t* p, size_t n)
{
    uint32_t c = 0xffffffffu;
    size_t i;
    if (!crc_table[1]) {
        uint32_t k, j;
        for (k = 0; k < 256; k++) {
            uint32_t v = k;
            for (j = 0; j < 8; j++) v = (v & 1) ? 0xedb88320u ^ (v >> 1) : v >> 1;
            crc_table[k] = v;
        }
    }
    for (i = 0; i < n; i++) c = crc_table[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

static size_t unhex(const char* s, uint8_t* out, size_t cap)
{
    size_t n = 0;
    while (s[0] && s[1] && n < cap) {
        unsigned v;
        if (sscanf(s, "%2x", &v) != 1) break;
        out[n++] = (uint8_t)v;
        s += 2;
    }
    return n;
}

static void put_hex(const uint8_t* p, size_t n)
{
    size_t i;
    for (i = 0; i < n; i++) printf("%02x", p[i]);
}

static char* tok(char** s)
{
    char* p = *s;
    char* start;
    while (*p == ' ' || *p == '\t') p++;
    if (!*p) { *s = p; return NULL; }
    start = p;
    while (*p && *p != ' ' && *p != '\t') p++;
    if (*p) *p++ = 0;
    *s = p;
    return start;
}

static uint8_t* read_file_part(const char* path, long off, size_t n)
{
    FILE* f = fopen(path, "rb");
    uint8_t* b;
    if (!f) return NULL;
    b = (uint8_t*)malloc(n ? n : 1);
    if (fseek(f, off, SEEK_SET) != 0 || fread(b, 1, n, f) != n) {
        free(b);
        b = NULL;
    }
    fclose(f);
    return b;
}

// ------------------------------------------------------------ the scenarios

static void do_table(void)
{
    const uint8_t* t = mv3_decode_table();
    int i;
    for (i = 0; i < 8; i++) {
        printf("table %d ", i);
        put_hex(t + i * 128, 128);
        printf("\n");
    }
}

static void do_quant(char* s)
{
    static Mv3Codec m;
    int q = atoi(tok(&s)), d = atoi(tok(&s)), t, i;
    mv3_init_idct_tables(&m, q, d);
    for (t = 0; t < 4; t++) {
        printf("quant %d %d %d", q, d, t);
        for (i = 0; i < 64; i++) printf(" %d", m.quant[t][i]);
        printf("\n");
    }
}

static uint8_t data[1 << 16];

static void do_bits(char* s)
{
    size_t n = unhex(tok(&s), data, sizeof(data));
    Mv3Bits b;
    char* w;
    mv3_bits_init(&b, data, data + n);
    printf("bits");
    while ((w = tok(&s)) != NULL) printf(" %08x", (unsigned)mv3_get_bits(&b, (unsigned)atoi(w)));
    printf(" | %08x %u %u\n", (unsigned)b.accum, (unsigned)b.count,
           (unsigned)(b.p - data));
}

static void do_huff(char* s)
{
    static int16_t out[4096 + 80];
    size_t n = unhex(tok(&s), data, sizeof(data));
    uint32_t count = (uint32_t)atoi(tok(&s)), i;
    Mv3Bits b;
    for (i = 0; i < count + 72; i++) out[i] = 0x5555;
    mv3_bits_init(&b, data, data + n);
    mv3_decompress(&b, out, count);
    printf("huff %u", (unsigned)count);
    for (i = 0; i < count + 72; i++) printf(" %d", out[i]);
    printf(" | %08x %u %u\n", (unsigned)b.accum, (unsigned)b.count,
           (unsigned)(b.p - data));
}

static void do_idct(char* s)
{
    int kind = atoi(tok(&s)), i;
    int16_t q[64], c[64];
    uint8_t dst[8 * 16];
    for (i = 0; i < 64; i++) q[i] = (int16_t)atoi(tok(&s));
    for (i = 0; i < 64; i++) c[i] = (int16_t)atoi(tok(&s));
    memset(dst, 0x5a, sizeof(dst));
    switch (kind) {
    case 0: mv3_idct_zero(dst, 16); break;
    case 1: mv3_idct1(c, q, dst, 16); break;
    case 2: mv3_idct4(c, q, dst, 16); break;
    case 3: mv3_idct(c, q, dst, 16); break;
    default: mv3_idct_zigzag(c, q, dst, 16); break;
    }
    printf("idct %d ", kind);
    put_hex(dst, sizeof(dst));
    printf("\n");
}

static void do_yuv(char* s)
{
    static uint8_t planes[3][1 << 14];
    static uint8_t rgba[1 << 16], back[1 << 16];
    static uint32_t tex[1 << 14];
    Mv3Codec m;
    int w = atoi(tok(&s)), h = atoi(tok(&s)), flip = atoi(tok(&s));
    int tw = 8, th, x, y;
    memset(&m, 0, sizeof(m));
    unhex(tok(&s), planes[0], sizeof(planes[0]));
    unhex(tok(&s), planes[1], sizeof(planes[1]));
    unhex(tok(&s), planes[2], sizeof(planes[2]));
    m.width = w;
    m.height = h;
    m.y = planes[0];
    m.u = planes[1];
    m.v = planes[2];
    mv3_to_rgba(&m, rgba, flip);
    printf("yuv %d %d %d ", w, h, flip);
    put_hex(rgba, (size_t)w * h * 4);
    printf("\n");
    if (!flip) return;

    // The texture layout, read back into rows: the same pixels as flip 1.
    while (tw < w) tw *= 2;
    th = (h + 7) & ~7;
    memset(tex, 0, sizeof(uint32_t) * (size_t)tw * th);
    mv3_to_tiled_rgba8(&m, tex, tw);
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            uint32_t t = tex[((y >> 3) * (tw >> 3) + (x >> 3)) * 64
                             + ((x & 1) | (y & 1) << 1 | (x & 2) << 1
                                | (y & 2) << 2 | (x & 4) << 2 | (y & 4) << 3)];
            uint8_t* d = back + ((size_t)y * w + x) * 4;
            d[0] = (uint8_t)(t >> 24);
            d[1] = (uint8_t)(t >> 16);
            d[2] = (uint8_t)(t >> 8);
            d[3] = (uint8_t)t;
        }
    printf("tiled %d %d ", w, h);
    put_hex(back, (size_t)w * h * 4);
    printf("\n");
}

static void do_frame(char* s)
{
    const char* path = tok(&s);
    long off = atol(tok(&s));
    size_t n = (size_t)atol(tok(&s));
    int w = atoi(tok(&s)), h = atoi(tok(&s)), rc, x, y, tw = 8;
    uint8_t* frame = read_file_part(path, off, n);
    uint8_t* rgba = (uint8_t*)malloc((size_t)w * h * 4);
    uint8_t* back = (uint8_t*)malloc((size_t)w * h * 4);
    uint32_t* tex;
    Mv3Codec m;

    while (tw < w) tw *= 2;
    tex = (uint32_t*)calloc((size_t)tw * h, 4);
    if (!frame || mv3_init(&m, w, h) != MV3_OK) {
        printf("frame error\n");
        return;
    }
    mv3_clamp_misses = 0;
    rc = mv3_decode(&m, frame, n);
    mv3_to_rgba(&m, rgba, 1);
    mv3_to_tiled_rgba8(&m, tex, tw);
    for (y = 0; y < h; y++)
        for (x = 0; x < w; x++) {
            uint32_t t = tex[((y >> 3) * (tw >> 3) + (x >> 3)) * 64
                             + ((x & 1) | (y & 1) << 1 | (x & 2) << 1
                                | (y & 2) << 2 | (x & 4) << 2 | (y & 4) << 3)];
            uint8_t* d = back + ((size_t)y * w + x) * 4;
            d[0] = (uint8_t)(t >> 24);
            d[1] = (uint8_t)(t >> 16);
            d[2] = (uint8_t)(t >> 8);
            d[3] = (uint8_t)t;
        }
    printf("frame %d %08x %08x misses %u\n", rc,
           (unsigned)crc32(rgba, (size_t)w * h * 4),
           (unsigned)crc32(back, (size_t)w * h * 4), (unsigned)mv3_clamp_misses);
    mv3_free(&m);
    free(frame);
    free(rgba);
    free(back);
    free(tex);
}

static void tag_str(uint32_t t, char* out)
{
    int i;
    for (i = 0; i < 4; i++) {
        char c = (char)(t >> (8 * i));
        out[i] = (c > ' ' && c < 127) ? c : '.';
    }
    out[4] = 0;
}

static void do_avi(char* s)
{
    const char* path = tok(&s);
    FILE* f = fopen(path, "rb");
    AviInfo in;
    AviChunk c;
    uint32_t pos;
    char t[5];
    if (!f || !avi_parse(f, &in)) {
        printf("avi none\n");
        if (f) fclose(f);
        return;
    }
    tag_str(in.videoCodec, t);
    printf("avi %u %u %d %s %u %u %u | %u %u %u %u | %d %d %u %u\n",
           (unsigned)in.width, (unsigned)in.height, (int)in.bmpHeight, t,
           (unsigned)in.scale, (unsigned)in.rate, (unsigned)in.frames,
           in.audioFormat, in.audioChannels, in.audioBits,
           (unsigned)in.audioRate, in.videoStream, in.audioStream,
           (unsigned)in.moviStart, (unsigned)in.moviEnd);
    pos = in.moviStart;
    while (avi_next_chunk(f, &in, &pos, &c)) {
        tag_str(c.tag, t);
        printf("c %s %d %u %u\n", t, avi_chunk_stream(c.tag),
               (unsigned)c.offset, (unsigned)c.size);
    }
    printf("avi end %u\n", (unsigned)pos);
    fclose(f);
}

static void on_audio(void* user, FILE* f, const AviChunk* c)
{
    (void)user;
    (void)f;
    printf("a %u %u\n", (unsigned)c->offset, (unsigned)c->size);
}

static void do_pace(char* s)
{
    const char* path = tok(&s);
    AviMovie m;
    char* w;
    if (!avimovie_open(&m, path)) {
        printf("pace none\n");
        return;
    }
    m.audio = on_audio;
    printf("pace %.6f\n", avimovie_duration(&m));
    while ((w = tok(&s)) != NULL) {
        double t = strtod(w, NULL);
        uint32_t target = avimovie_frame_at(&m, t);
        int changed = avimovie_advance(&m, target);
        printf("t %s %u %d %d %u %u %u %d %d %d\n", w, (unsigned)target,
               changed, (int)m.shown, (unsigned)m.decoded, (unsigned)m.skipped,
               (unsigned)m.nextFrame, m.ended, m.error, avimovie_done(&m));
    }
    avimovie_close(&m);
}

// The sound: after every push, pull with each of `pulls` in turn for as
// long as anything is ready, and say what came out. The PCM goes into one
// running CRC, left and right interleaved, as the host lays int16 out
// (little-endian, like the 3DS).
typedef struct {
    AviSound snd;
    uint32_t pulls[64];
    int      npulls, next;
    uint32_t samples, crc;
    int16_t  pcm[AVISOUND_FRAMES * AVISOUND_SAMPLES * 2];
} SndRun;

static uint32_t crc_more(uint32_t crc, const uint8_t* p, size_t n)
{
    // crc32() above, carried across calls.
    uint32_t c = crc ^ 0xffffffffu;
    size_t i;
    crc32(p, 0);
    for (i = 0; i < n; i++) c = crc_table[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

static void snd_drain(SndRun* r)
{
    uint32_t got = 0, ready = avisound_ready(&r->snd);
    while (avisound_ready(&r->snd)) {
        uint32_t want = r->pulls[r->next++ % r->npulls], n;
        if (want > AVISOUND_FRAMES) want = AVISOUND_FRAMES;
        n = avisound_pull(&r->snd, r->pcm, want);
        r->crc = crc_more(r->crc, (const uint8_t*)r->pcm, (size_t)n * 4);
        got += n;
        if (want && !n) {
            // ready said yes and pull said no: say so rather than spin.
            printf("stuck %u\n", (unsigned)avisound_ready(&r->snd));
            break;
        }
    }
    r->samples += got;
    printf("s %u %u %u %u %u\n", (unsigned)r->snd.pushed, (unsigned)ready,
           (unsigned)r->snd.len, (unsigned)r->snd.frame, (unsigned)got);
}

static void snd_end(SndRun* r)
{
    printf("snd end %u %u %u %u %08x\n", (unsigned)r->snd.pushed,
           (unsigned)r->snd.len, (unsigned)r->snd.frame, (unsigned)r->samples,
           (unsigned)r->crc);
    avisound_free(&r->snd);
}

// The pull sizes, after a "/".
static int snd_pulls(SndRun* r, char* s)
{
    char* w;
    memset(r, 0, sizeof(*r));
    while ((w = tok(&s)) != NULL && r->npulls < 64)
        if (strcmp(w, "/")) r->pulls[r->npulls++] = (uint32_t)strtoul(w, NULL, 10);
    return r->npulls;
}

static void do_snd(char* s)
{
    static SndRun r;
    const char* path = tok(&s);
    char* slash = strstr(s, " / ");
    uint32_t sizes[256];
    int nsizes = 0, k = 0;
    FILE* f;
    uint8_t* buf;
    long len;
    char* w;

    if (!slash) { printf("snd none\n"); return; }
    *slash = 0;
    while ((w = tok(&s)) != NULL && nsizes < 256)
        sizes[nsizes++] = (uint32_t)strtoul(w, NULL, 10);
    if (!snd_pulls(&r, slash + 3) || !nsizes || !(f = fopen(path, "rb"))) {
        printf("snd none\n");
        return;
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    buf = read_file_part(path, 0, (size_t)len);
    fclose(f);
    if (!buf) { printf("snd none\n"); return; }
    for (long at = 0; at < len; k++) {
        uint32_t n = sizes[k % nsizes];
        if (n > (uint32_t)(len - at)) n = (uint32_t)(len - at);
        if (!avisound_push(&r.snd, buf + at, n)) { printf("snd push failed\n"); break; }
        at += n;
        snd_drain(&r);
    }
    free(buf);
    snd_end(&r);
}

static void on_movie_sound(void* user, FILE* f, const AviChunk* c)
{
    SndRun* r = (SndRun*)user;
    if (!avisound_read(&r->snd, f, c)) printf("snd read failed\n");
    snd_drain(r);
}

static void do_movsnd(char* s)
{
    static SndRun r;
    const char* path = tok(&s);
    AviMovie m;
    if (!snd_pulls(&r, s) || !avimovie_open(&m, path)) {
        printf("snd none\n");
        return;
    }
    m.audio = on_movie_sound;
    m.audioUser = &r;
    while (!avimovie_done(&m)) avimovie_advance(&m, m.info.frames);
    avimovie_close(&m);
    snd_end(&r);
}

static void do_rate(void)
{
    printf("rate %u %u %u\n", (unsigned)AVISOUND_RATE,
           (unsigned)bsnd_hz_to_spu(AVISOUND_RATE), (unsigned)avisound_rate_hz());
}

int main(int argc, char** argv)
{
    static char line[1 << 20];
    FILE* f;
    if (argc < 2 || !(f = fopen(argv[1], "r"))) {
        fprintf(stderr, "usage: mv3_test scenarios.txt\n");
        return 2;
    }
    while (fgets(line, sizeof(line), f)) {
        char* s = line;
        char* cmd;
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
        cmd = tok(&s);
        if (!cmd) continue;
        if (!strcmp(cmd, "table")) do_table();
        else if (!strcmp(cmd, "quant")) do_quant(s);
        else if (!strcmp(cmd, "bits")) do_bits(s);
        else if (!strcmp(cmd, "huff")) do_huff(s);
        else if (!strcmp(cmd, "idct")) do_idct(s);
        else if (!strcmp(cmd, "yuv")) do_yuv(s);
        else if (!strcmp(cmd, "frame")) do_frame(s);
        else if (!strcmp(cmd, "avi")) do_avi(s);
        else if (!strcmp(cmd, "pace")) do_pace(s);
        else if (!strcmp(cmd, "snd")) do_snd(s);
        else if (!strcmp(cmd, "movsnd")) do_movsnd(s);
        else if (!strcmp(cmd, "rate")) do_rate();
        else printf("unknown %s\n", cmd);
        fflush(stdout);
    }
    fclose(f);
    return 0;
}
