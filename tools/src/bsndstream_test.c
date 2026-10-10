// Harness for tools/bsndstream_check.py: runs the checker's script on
// bsnd.c's streams -- the "_STREAM" bank, the "_CHAIN" queue and
// bsnd_stream_active -- and prints what the model prints for retail's
// bSnd_VoicePlay (0x002611c0), PlayChain (0x00262848) and 0x00263090. The
// sink is a recorder: it prints the parts and the rate a stream is
// handed and the mix that follows, and answers `playing` for the channel
// the last stream went to until the script drains it, as bsndstream.c
// does. With --decode it runs bsndstream.c's decoder over a file of
// frames instead. See the checker's docstring.
//
//     bsndstream_test script.txt > out.txt
//     bsndstream_test --decode frames.bin out.pcm seed

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsnd.h"
#include "bsndstream.h"

static BsndDriver gD;
static int gStreamCh = -1;          // the channel the last stream went to
static int gActive;                 // and whether it still has audio

static void rec_start(void* user, unsigned ch, const uint8_t* data,
                      uint32_t bytes, uint32_t samples, const int16_t* coefs,
                      uint32_t rate, bool looping)
{
    (void)user;
    (void)data;
    (void)bytes;
    (void)samples;
    (void)coefs;
    (void)looping;
    printf("  start %u %u\n", ch, rate);
}

static void rec_stop(void* user, unsigned ch)
{
    (void)user;
    printf("  stop %u\n", ch);
    if ((int)ch == gStreamCh)
        gStreamCh = -1;
}

static void rec_mix(void* user, unsigned ch, uint16_t left, uint16_t right)
{
    (void)user;
    printf("  mix %u %u %u\n", ch, left, right);
}

static void rec_rate(void* user, unsigned ch, uint32_t hz)
{
    (void)user;
    printf("  rate %u %u\n", ch, hz);
}

static void rec_pause(void* user, unsigned ch, bool paused)
{
    (void)user;
    printf("  pause %u %d\n", ch, paused ? 1 : 0);
}

static bool rec_playing(void* user, unsigned ch)
{
    (void)user;
    return (int)ch == gStreamCh && gActive;
}

static void rec_stream(void* user, unsigned ch, const BsndStreamPart* parts,
                       unsigned count, uint32_t rate)
{
    unsigned i;

    (void)user;
    printf("  stream %u hz=%u n=%u\n", ch, rate, count);
    for (i = 0; i < count; i++)
        printf("    part '%s' %u %u\n", parts[i].path, parts[i].offset,
               parts[i].size);
    gStreamCh = (int)ch;
    gActive = 1;
}

static const BsndSink kRecSink = {
    rec_start, rec_stop, rec_mix, rec_rate, rec_pause, rec_playing, NULL,
    rec_stream
};

// ------------------------------------------------------------- the dumps

static void dump(void)
{
    unsigned i;

    printf("  chain n=%u\n", gD.chainCount);
    for (i = 0; i < BSND_CHAIN_MAX; i++) {
        const BsndChainPart* c = &gD.chain[i];

        if (c->name[0] == '\0' && c->rate == 0 && c->volume == 0
            && c->offset == 0 && c->size == 0)
            continue;
        printf("  q%u '%s' r=%u v=%u o=%u s=%u\n", i, c->name, c->rate,
               c->volume, c->offset, c->size);
    }
    for (i = 0; i < gD.voices; i++) {
        const BsndVoice* v = &gD.voice[i];

        if (v->pan == 0 && v->loopChannel == 0 && v->streamChannel == -1
            && v->paused == 0 && v->type == 0 && v->pitch == 0
            && v->volume == 0 && v->effectVolume == 0 && v->azimuth == 0
            && v->adsr == 0 && gD.key[i] == 0)
            continue;
        printf("  v%u pan=%d loop=%u st=%d pa=%u ty=%u pitch=%u vol=%u "
               "eff=%u az=%u adsr=%08x key=%u\n", i, v->pan, v->loopChannel,
               v->streamChannel, v->paused, v->type, v->pitch, v->volume,
               v->effectVolume, v->azimuth, v->adsr, gD.key[i]);
    }
}

// --------------------------------------------------------------- the ops

static uint32_t num(const char* s)
{
    return (uint32_t)strtoul(s, NULL, 0);
}

static void op(char** f, int n)
{
    const char* o = f[0];

    if (strcmp(o, "path") == 0) {
        bsnd_set_load_path(&gD, n > 1 ? f[1] : "");
    } else if (strcmp(o, "mode") == 0) {
        bsnd_set_mode(&gD, (uint8_t)num(f[1]));
    } else if (strcmp(o, "key") == 0) {
        gD.key[num(f[1])] = (uint8_t)num(f[2]);
    } else if (strcmp(o, "lock") == 0) {
        gD.lock[num(f[1])] = (int8_t)num(f[2]);
    } else if (strcmp(o, "eff") == 0) {
        gD.voice[num(f[1])].effectVolume = (uint16_t)num(f[2]);
    } else if (strcmp(o, "play") == 0) {
        uint32_t voice = num(f[8]);
        uint16_t r = bsnd_voice_play_at(
            &gD, f[1], f[2], num(f[3]), (uint16_t)num(f[4]),
            (uint16_t)num(f[5]), num(f[6]), num(f[7]),
            voice == 48 ? BSND_VOICE_ALLOC : (uint16_t)voice);
        printf("  = %u\n", r == BSND_VOICE_ALLOC ? 48u : r);
    } else if (strcmp(o, "active") == 0) {
        printf("  = %d\n", bsnd_stream_active(&gD, (uint16_t)num(f[1])) ? 1
                                                                       : 0);
    } else if (strcmp(o, "clear") == 0) {
        memset(gD.key, 0, sizeof(gD.key));
        memset(gD.lock, 0, sizeof(gD.lock));
    } else if (strcmp(o, "drain") == 0) {
        gActive = 0;
    } else if (strcmp(o, "dump") == 0) {
        dump();
    } else {
        printf("  unknown op %s\n", o);
    }
}

// --decode in out seed: the frames of `in` through bss_decode in runs of
// 1 to 300 frames, the seed's, to the PCM16 of `out`.
static int decode_file(const char* in, const char* out, uint32_t seed)
{
    FILE* fp = fopen(in, "rb");
    uint8_t* buf;
    int16_t* pcm;
    long len;
    uint32_t frames, at = 0, nout = 0;
    BssDecoder dec;

    if (fp == NULL)
        return 2;
    fseek(fp, 0, SEEK_END);
    len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    buf = (uint8_t*)malloc((size_t)len + 1);
    if (buf == NULL || fread(buf, 1, (size_t)len, fp) != (size_t)len)
        return 2;
    fclose(fp);
    frames = (uint32_t)len / BSS_FRAME;
    pcm = (int16_t*)malloc((frames + 1) * BSS_SAMPLES * sizeof(int16_t));
    if (pcm == NULL)
        return 2;
    bss_decoder_reset(&dec);
    while (at < frames && !dec.ended) {
        uint32_t run, got;

        seed = seed * 1103515245u + 12345u;
        run = 1 + (seed >> 16) % 300;
        if (run > frames - at)
            run = frames - at;
        got = bss_decode(&dec, buf + at * BSS_FRAME, run, pcm + nout);
        nout += got * BSS_SAMPLES;
        at += got;
        if (got < run)
            break;
    }
    fp = fopen(out, "wb");
    if (fp == NULL)
        return 2;
    fwrite(pcm, sizeof(int16_t), nout, fp);
    fclose(fp);
    free(pcm);
    free(buf);
    return 0;
}

int main(int argc, char** argv)
{
    static char line[1024];
    FILE* fp;

    if (argc == 5 && strcmp(argv[1], "--decode") == 0)
        return decode_file(argv[2], argv[3],
                           (uint32_t)strtoul(argv[4], NULL, 0));
    if (argc < 2) {
        fprintf(stderr, "usage: bsndstream_test script.txt\n");
        return 2;
    }
    fp = fopen(argv[1], "r");
    if (fp == NULL) {
        perror(argv[1]);
        return 2;
    }
    bsnd_init(&gD, &kRecSink, BSND_PS2_VOICES);
    while (fgets(line, sizeof(line), fp)) {
        char* f[16];
        int n = 0;
        char* p = line;
        size_t len = strlen(line);

        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = '\0';
        if (len == 0)
            continue;
        printf("> %s\n", line);
        f[n++] = p;
        while ((p = strchr(p, '|')) != NULL && n < 16) {
            *p++ = '\0';
            f[n++] = p;
        }
        op(f, n);
    }
    fclose(fp);
    return 0;
}
