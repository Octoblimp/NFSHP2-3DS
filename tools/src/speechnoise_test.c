// Harness for tools/speechnoise_check.py: runs the checker's script on
// speechnoise.c and prints what the model prints for the retail image.
// bSound's Region, bRegion's Sample, bSample, the sound's random int and
// float and its loading flag are logging fakes, the same fakes the
// checker gives retail's code. See the checker's docstring.
//
//     speechnoise_test script.txt > out.txt

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsound.h"
#include "sound.h"
#include "speechnoise.h"

static uint32_t bits(float f)
{
    uint32_t v;

    memcpy(&v, &f, 4);
    return v;
}

static float unbits(uint32_t v)
{
    float f;

    memcpy(&f, &v, 4);
    return f;
}

// ------------------------------------------------------------- the objects

#define MAXSRC 32
#define MAXQ   128

static SpeechNoise *N;
static int          fakebsound;
static int          fakeregion;
static SoundModule  fakemod;
static int          noRegion;
static int          loading;

// The samples bRegion's Sample hands out, one a name; `nosrc` names get
// none.
static struct {
    char    nm[32];
    BSample s;
    int     playing;
} srcs[MAXSRC];
static int  nsrcs;
static char nosrc[16][32];
static int  nnosrc;

static uint32_t randF[MAXQ], randI[MAXQ];
static int      nRandF, atRandF, nRandI, atRandI;

static uint32_t pop(uint32_t *q, int n, int *at)
{
    return *at < n ? q[(*at)++] : 0;
}

static const char *name(const void *p)
{
    static char buf[8][48];
    static int k;
    char *b = buf[k++ & 7];
    int i;

    if (p == NULL)
        return "0";
    if (p == (const void *)&fakebsound)
        return "bsound";
    if (p == (const void *)&fakeregion)
        return "region";
    for (i = 0; i < nsrcs; i++) {
        if (p == &srcs[i].s) {
            sprintf(b, "src:%s", srcs[i].nm);
            return b;
        }
    }
    return "?";
}

static int src_index(const BSample *s)
{
    int i;

    for (i = 0; i < nsrcs; i++)
        if (s == &srcs[i].s)
            return i;
    return -1;
}

static BSample *src_named(const char *nm)
{
    int i;

    for (i = 0; i < nnosrc; i++)
        if (!strcmp(nosrc[i], nm))
            return NULL;
    for (i = 0; i < nsrcs; i++)
        if (!strcmp(srcs[i].nm, nm))
            return &srcs[i].s;
    if (nsrcs == MAXSRC)
        return NULL;
    strncpy(srcs[nsrcs].nm, nm, sizeof(srcs[nsrcs].nm) - 1);
    return &srcs[nsrcs++].s;
}

// --------------------------------------------------------- bSound, bRegion

BSound *bsound_get(void)
{
    return (BSound *)(void *)&fakebsound;
}

BRegion *bsound_region(const BSound *s, const char *nm)
{
    BRegion *r = noRegion ? NULL : (BRegion *)(void *)&fakeregion;

    printf("  region %s %s -> %s\n", name(s), nm, name(r));
    return r;
}

BSample *bregion_sample(const BRegion *r, const char *nm)
{
    BSample *s = r == NULL ? NULL : src_named(nm);

    printf("  rsample %s %s -> %s\n", name(r), nm, name(s));
    return s;
}

// --------------------------------------------------------------- bSample

void bsample_set_category(BSample *s, uint32_t category)
{
    printf("  bcat %s %u\n", name(s), category);
    if (s != NULL)
        s->category = category;
}

BVoice *bsample_play(BSample *s, float volume, float pan, float pitch)
{
    int i = src_index(s);

    printf("  bplay %s %08x %08x %08x\n", name(s), bits(volume), bits(pan),
           bits(pitch));
    if (i >= 0)
        srcs[i].playing = 1;
    return NULL;
}

void bsample_stop(BSample *s)
{
    int i = src_index(s);

    printf("  bstop %s\n", name(s));
    if (i >= 0)
        srcs[i].playing = 0;
}

void bsample_pause(BSample *s, bool pause)
{
    printf("  bpause %s %d\n", name(s), pause ? 1 : 0);
}

// Retail asks it of a missing squelch, and the model's fake is silent
// then. The port must ask none: the real one reads through the sample.
bool bsample_is_playing(const BSample *s)
{
    int i = src_index(s);
    int v = i >= 0 && srcs[i].playing;

    if (s == NULL) {
        printf("  bisplaying of no sample\n");
        return false;
    }
    printf("  bisplaying %s %d\n", name(s), v);
    return v != 0;
}

// ---------------------------------------------------------- the sound module

SoundModule *sound_get(void)
{
    return &fakemod;
}

int sound_is_region_loading_complete(const SoundModule *m)
{
    (void)m;
    printf("  loading -> %d\n", loading);
    return !loading;
}

int32_t sound_random_int(SoundModule *m, int32_t range)
{
    int32_t v = (int32_t)pop(randI, nRandI, &atRandI);

    (void)m;
    printf("  randi %d -> %d\n", range, v);
    return v;
}

float sound_random_float(SoundModule *m, float range)
{
    uint32_t v = pop(randF, nRandF, &atRandF);

    (void)m;
    printf("  randf %08x -> %08x\n", bits(range), v);
    return unbits(v);
}

// --------------------------------------------------------------- the dumps

static void dump(void)
{
    int i;

    printf("  nd heli=%s sq=%s,%s radio=", name(N->Helicopter),
           name(N->Squelch[0]), name(N->Squelch[1]));
    for (i = 0; i < SPEECHNOISE_RADIOS; i++)
        printf("%s%s", i ? "," : "", name(N->Radio[i]));
    printf(" on=%d req=%d muted=%d\n", N->RadioNoiseOn,
           N->RequestSampleLoad, N->SpeechNoiseMuted);
}

static void dump_cats(void)
{
    int i;

    for (i = 0; i < nsrcs; i++)
        printf("  cat %s %u\n", name(&srcs[i].s), srcs[i].s.category);
}

// ------------------------------------------------------------- the ops

static void op(char **f, int nf)
{
#define I(k) ((k) < nf ? (int)strtol(f[k], NULL, 0) : 0)
#define U(k) ((k) < nf ? (uint32_t)strtoul(f[k], NULL, 16) : 0u)
    const char *o = f[0];

    if (!strcmp(o, "inst")) {
        SpeechNoise *p = speechnoise_get_instance();

        if (N == NULL)
            N = p;
        printf("  -> %s\n", p == N ? "inst" : "?");
    } else if (!strcmp(o, "fill")) {
        memset(N, 0xa5, sizeof(*N));
    } else if (!strcmp(o, "ctor")) {
        speechnoise_construct(N);
    } else if (!strcmp(o, "nd")) {
        dump();
    } else if (!strcmp(o, "cats")) {
        dump_cats();
    } else if (!strcmp(o, "load")) {
        speechnoise_load_samples(N);
    } else if (!strcmp(o, "request")) {
        speechnoise_request_samples(N);
    } else if (!strcmp(o, "unload")) {
        speechnoise_unload_samples(N);
    } else if (!strcmp(o, "update")) {
        speechnoise_update(N);
    } else if (!strcmp(o, "mute")) {
        speechnoise_mute(N, I(1));
    } else if (!strcmp(o, "hstart")) {
        speechnoise_start_helicopter_noise(N);
    } else if (!strcmp(o, "hstop")) {
        speechnoise_stop_helicopter_noise(N);
    } else if (!strcmp(o, "rstart")) {
        speechnoise_start_radio_noise(N);
    } else if (!strcmp(o, "rstop")) {
        speechnoise_stop_radio_noise(N);
    } else if (!strcmp(o, "isradio")) {
        printf("  = %d\n", speechnoise_is_radio_noise(N));
    } else if (!strcmp(o, "squelch")) {
        speechnoise_begin_squelch_noise(N);
    } else if (!strcmp(o, "issquelch")) {
        printf("  = %d\n", speechnoise_is_squelch_noise_playing(N));
    } else if (!strcmp(o, "heli")) {
        N->Helicopter = !strcmp(f[1], "0") ? NULL : src_named(f[1]);
    } else if (!strcmp(o, "slot")) {
        // A squelch (s0, s1) or a static (r0 .. r6) set to a sample, or 0.
        BSample *s = !strcmp(f[2], "0") ? NULL : src_named(f[2]);

        if (f[1][0] == 's')
            N->Squelch[atoi(f[1] + 1)] = s;
        else
            N->Radio[atoi(f[1] + 1)] = s;
    } else if (!strcmp(o, "poke")) {
        if (!strcmp(f[1], "on"))
            N->RadioNoiseOn = I(2);
        else if (!strcmp(f[1], "req"))
            N->RequestSampleLoad = I(2);
        else
            N->SpeechNoiseMuted = I(2);
    } else if (!strcmp(o, "noregion")) {
        noRegion = I(1);
    } else if (!strcmp(o, "nosrc")) {
        strncpy(nosrc[nnosrc++], f[1], 31);
    } else if (!strcmp(o, "unsrc")) {
        nnosrc = 0;
    } else if (!strcmp(o, "loading")) {
        loading = I(1);
    } else if (!strcmp(o, "rf")) {
        randF[nRandF++] = U(1);
    } else if (!strcmp(o, "ri")) {
        randI[nRandI++] = (uint32_t)I(1);
    } else if (!strcmp(o, "playing")) {
        BSample *s = src_named(f[1]);
        int i = src_index(s);

        if (i >= 0)
            srcs[i].playing = I(2);
    } else {
        printf("  unknown op %s\n", o);
    }
#undef I
#undef U
}

int main(int argc, char **argv)
{
    char line[512];
    FILE *fh;

    if (argc < 2) {
        fprintf(stderr, "usage: speechnoise_test script.txt\n");
        return 2;
    }
    fh = fopen(argv[1], "r");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
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
