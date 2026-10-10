// Host harness for the ported bSnd driver.
//
// Builds "3DS Files/source/bsnd.c" (plus sndbank.c and the generated
// bsndtab.c) for the host, installs a sink that prints every call instead of
// making a sound, and runs it through scripted sequences. tools/bsnd_check.py
// prints the same transcript from a second implementation written from the
// disassembly and diffs the two.
//
// What the transcript has to contain is everything a wrong driver could get
// wrong without crashing: which voices an allocation picked, what left and
// right volumes each one ended up with, what rate survived the SPU pitch
// round trip, and which bytes of which patch were handed over. So every sink
// call prints its arguments, a CRC of the audio it was given, and the state of
// every voice that changed.
//
// Build (bsnd_check.py does this for you):
//   cc -O2 -I"3DS Files/source" -o bsnd_test tools/src/bsnd_test.c
//      "3DS Files/source/bsnd.c" "3DS Files/source/sndbank.c"
//      "3DS Files/source/bsndtab.c"
//
// Usage: bsnd_test <dir-of-SBK>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bsnd.h"

static uint32_t crc32_buf(const uint8_t* p, size_t n)
{
    static uint32_t table[256];
    static int built = 0;
    if (!built) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++)
                c = (c & 1) ? 0xedb88320u ^ (c >> 1) : c >> 1;
            table[i] = c;
        }
        built = 1;
    }
    uint32_t c = 0xffffffffu;
    for (size_t i = 0; i < n; i++)
        c = table[(c ^ p[i]) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

// -- the recording sink ------------------------------------------------------

// gLeft is how many bsnd_update() ticks each channel has before the harness
// says its audio has run out. A looping channel never does, which is how the
// transcript shows that a loop holds its voice and a one-shot gives it back.
static int gLeft[BSND_PS2_VOICES];
static int gLoop[BSND_PS2_VOICES];

static void rec_start(void* user, unsigned ch, const uint8_t* data,
                      uint32_t bytes, uint32_t samples, const int16_t* coefs,
                      uint32_t rate, bool looping)
{
    uint8_t cb[32];
    (void)user;
    for (int i = 0; i < 16; i++) {
        cb[i * 2]     = (uint8_t)(coefs[i] & 0xff);
        cb[i * 2 + 1] = (uint8_t)((coefs[i] >> 8) & 0xff);
    }
    printf("  start ch=%u bytes=%u samples=%u rate=%u loop=%d data=%08x coef=%08x\n",
           ch, bytes, samples, rate, looping ? 1 : 0,
           crc32_buf(data, bytes), crc32_buf(cb, 32));
    gLeft[ch] = 3;
    gLoop[ch] = looping ? 1 : 0;
}

static void rec_stop(void* user, unsigned ch)
{
    (void)user;
    printf("  stop ch=%u\n", ch);
    gLeft[ch] = 0;
    gLoop[ch] = 0;
}

static void rec_mix(void* user, unsigned ch, uint16_t l, uint16_t r)
{
    (void)user;
    printf("  mix ch=%u l=%u r=%u\n", ch, l, r);
}

static void rec_rate(void* user, unsigned ch, uint32_t hz)
{
    (void)user;
    printf("  rate ch=%u hz=%u\n", ch, hz);
}

static void rec_pause(void* user, unsigned ch, bool paused)
{
    (void)user;
    printf("  pause ch=%u %d\n", ch, paused ? 1 : 0);
}

static bool rec_playing(void* user, unsigned ch)
{
    (void)user;
    return gLoop[ch] || gLeft[ch] > 0;
}

static const BsndSink kRecSink = {
    rec_start, rec_stop, rec_mix, rec_rate, rec_pause, rec_playing, NULL,
    NULL
};

// One bsnd_update() tick: every sounding one-shot gets one closer to done.
static void tick(BsndDriver* d)
{
    for (unsigned i = 0; i < BSND_PS2_VOICES; i++)
        if (!gLoop[i] && gLeft[i] > 0) gLeft[i]--;
    printf("  tick\n");
    bsnd_update(d);
}

// -- transcript helpers ------------------------------------------------------

static void dump_voices(const BsndDriver* d)
{
    for (unsigned i = 0; i < d->voices; i++) {
        const BsndVoice* v = &d->voice[i];
        if (v->patch == BSND_PATCH_NONE && d->key[i] == BSND_KEY_OFF
            && d->lock[i] == 0)
            continue;
        printf("  v%02u pan=%d lc=%02x pitch=%u vol=%u fx=%u az=%u ty=%u "
               "adsr=%08x l=%u r=%u patch=%u paused=%u key=%u lock=%d\n",
               i, v->pan, v->loopChannel, v->pitch, v->volume, v->effectVolume,
               v->azimuth, v->type, v->adsr, v->volL, v->volR, v->patch,
               v->paused, d->key[i], d->lock[i]);
    }
}

static void play(BsndDriver* d, const char* bank, const char* patch,
                 uint32_t rate, uint16_t vol, uint16_t az, uint16_t voice)
{
    uint16_t r = bsnd_voice_play(d, bank, patch, rate, vol, az, voice);
    printf("play %s/%s rate=%u vol=%u az=%u voice=%u -> %u\n",
           bank, patch, rate, vol, az, voice, r);
    dump_voices(d);
}

// The same, reached the way the game reaches it: through a pan.
static void play_pan(BsndDriver* d, const char* bank, const char* patch,
                     uint32_t rate, uint16_t vol, int pan, uint16_t voice)
{
    uint16_t r = bsnd_voice_play_pan(d, bank, patch, rate, vol, (int8_t)pan,
                                     voice);
    printf("playpan %s/%s rate=%u vol=%u pan=%d voice=%u -> %u az=%04x\n",
           bank, patch, rate, vol, pan, voice, r,
           bsnd_azimuth_from_pan((int8_t)pan));
    dump_voices(d);
}

static uint8_t* slurp(const char* path, size_t* size)
{
    FILE* f = fopen(path, "rb");
    long n;
    uint8_t* b;
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    n = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (n <= 0) { fclose(f); return NULL; }
    b = (uint8_t*)malloc((size_t)n);
    if (!b || fread(b, 1, (size_t)n, f) != (size_t)n) { fclose(f); free(b); return NULL; }
    fclose(f);
    *size = (size_t)n;
    return b;
}

static void scenario(int n, const char* name)
{
    printf("== %d %s\n", n, name);
}

// -- scenarios ---------------------------------------------------------------

int main(int argc, char** argv)
{
    char path[512];
    uint8_t *common, *frontend;
    size_t commonSize = 0, frontendSize = 0;
    BsndDriver d;

    if (argc < 2) {
        fprintf(stderr, "usage: bsnd_test <dir-of-SBK>\n");
        return 2;
    }
    snprintf(path, sizeof(path), "%s/COMMON.SBK", argv[1]);
    common = slurp(path, &commonSize);
    snprintf(path, sizeof(path), "%s/FRONTEND.SBK", argv[1]);
    frontend = slurp(path, &frontendSize);
    if (!common || !frontend) {
        fprintf(stderr, "need COMMON.SBK and FRONTEND.SBK under %s\n", argv[1]);
        return 2;
    }

    // 1. The units, on their own, before any state exists to confuse them.
    scenario(1, "units");
    {
        static const uint32_t rates[] = {
            0, 1, 8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000, 48001,
            96000, 4000000
        };
        for (size_t i = 0; i < sizeof(rates) / sizeof(rates[0]); i++) {
            uint32_t spu = bsnd_hz_to_spu(rates[i]);
            printf("  hz %u -> spu %u -> hz %u\n", rates[i], spu,
                   bsnd_spu_to_hz(spu));
        }
        for (uint32_t az = 0; az < 0x10000u; az += 0x400u)
            printf("  az %04x -> pan %d\n", az, bsnd_pan_from_azimuth((uint16_t)az));
        // The four quadrant boundaries, where an off-by-one in the compare
        // chain would land in the wrong branch and only there.
        static const uint16_t edges[] = {
            0x3fff, 0x4000, 0x4001, 0x7fff, 0x8000, 0x8001, 0xbfff, 0xc000,
            0xc001, 0xfffe, 0xffff
        };
        for (size_t i = 0; i < sizeof(edges) / sizeof(edges[0]); i++)
            printf("  az %04x -> pan %d\n", edges[i],
                   bsnd_pan_from_azimuth(edges[i]));
        // Every pan, out to an azimuth and back. The round trip is not the
        // identity and is not meant to be; what matters is that both halves
        // land where the EE's single-precision multiply lands, so the whole
        // range is printed rather than a few samples of it.
        for (int pan = -128; pan <= 127; pan++) {
            uint16_t az = bsnd_azimuth_from_pan((int8_t)pan);
            printf("  pan %+04d -> az %04x -> pan %d\n", pan, az,
                   bsnd_pan_from_azimuth(az));
        }
    }

    // 2. The pan table, swept end to end at four volumes, in all three modes.
    scenario(2, "pan table");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    for (int mode = BSND_MODE_MONO; mode <= BSND_MODE_PROLOGIC; mode++) {
        bsnd_set_mode(&d, (uint8_t)mode);
        for (int vol = 0; vol <= 0x7fff; vol += 0x1fff) {
            for (int pan = -128; pan <= 127; pan++) {
                uint16_t l, r;
                bsnd_volumes_from_pan(&d, &l, &r, (uint16_t)vol, (int8_t)pan);
                printf("  m%d v%05d p%+04d -> %u %u\n", mode, vol, pan, l, r);
            }
        }
    }

    // 3. The allocator, with holes punched in it by hand. Both widths, because
    //    the port's 24 and the PS2's 48 take different paths through the
    //    bounds checks at the top of SOUND_FindFreeSPUChannels.
    scenario(3, "allocator");
    for (unsigned width = BSND_MAX_VOICES; width <= BSND_PS2_VOICES;
         width += BSND_PS2_VOICES - BSND_MAX_VOICES) {
        bsnd_init(&d, &kRecSink, width);
        printf("  width %u\n", width);
        for (unsigned count = 0; count <= 3; count++)
            printf("   empty count=%u -> %d\n", count,
                   bsnd_find_free_channels(&d, 0, width - 1, count));
        // Busy every even channel: no pair anywhere, singles everywhere.
        for (unsigned i = 0; i < width; i += 2) d.key[i] = BSND_KEY_ON;
        printf("   evens busy 1 -> %d  2 -> %d\n",
               bsnd_find_free_channels(&d, 0, width - 1, 1),
               bsnd_find_free_channels(&d, 0, width - 1, 2));
        // Free one pair in the middle and find it from both directions.
        d.key[width / 2] = BSND_KEY_OFF;
        printf("   one pair 2 -> %d  reversed -> %d\n",
               bsnd_find_free_channels(&d, 0, width - 1, 2),
               bsnd_find_free_channels(&d, width - 1, 0, 2));
        // Locks are invisible to the allocator but do not stop the audio.
        // bSnd_LockChannels allocates from the top down and returns the run's
        // lowest channel.
        {
            uint16_t got = bsnd_lock_channels(&d, 2);
            uint16_t again, one;
            printf("   lock 2 -> %u  locked 2 -> %d\n", (unsigned)got,
                   bsnd_find_free_channels(&d, 0, width - 1, 2));
            again = bsnd_lock_channels(&d, 2);
            one = bsnd_lock_channels(&d, 1);
            printf("   lock 2 again -> %u  lock 1 -> %u\n", (unsigned)again,
                   (unsigned)one);
            bsnd_unlock_channels(&d, got, 2);
            printf("   unlocked 2 -> %d\n",
                   bsnd_find_free_channels(&d, 0, width - 1, 2));
            bsnd_unlock_channels(&d, (uint16_t)(width - 1), 1);
        }
        // Out-of-range endpoints, which return their own error each.
        printf("   bad first -> %d  bad last -> %d\n",
               bsnd_find_free_channels(&d, width, width - 1, 1),
               bsnd_find_free_channels(&d, 0, width, 1));
        // A sub-range, and one that is a single channel wide.
        printf("   sub 3..9 2 -> %d  single 7..7 1 -> %d\n",
               bsnd_find_free_channels(&d, 3, 9, 2),
               bsnd_find_free_channels(&d, 7, 7, 1));
    }

    // 4. Banks: load, look up, unload, and the misses in between.
    scenario(4, "banks");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    printf("  loaded COMMON=%d\n", bsnd_bank_loaded(&d, "COMMON"));
    printf("  register COMMON=%d\n",
           bsnd_bank_register(&d, "COMMON", common, commonSize, false));
    printf("  register COMMON again=%d\n",
           bsnd_bank_register(&d, "COMMON", common, commonSize, false));
    printf("  register FRONTEND=%d\n",
           bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false));
    printf("  patchCount=%u\n", d.patchCount);
    {
        static const char* names[] = {
            "MenuSelect", "MenuUpDown", "MenuLeftRight", "MenuCancel",
            "MenuStart", "MenuWrong", "MenuAdjustVolume", "NoSuchPatch",
            "menuselect"
        };
        for (size_t i = 0; i < sizeof(names) / sizeof(names[0]); i++) {
            uint16_t id = bsnd_patch_id(&d, "COMMON", names[i]);
            printf("  id COMMON/%s = %u ch=%u\n", names[i], id,
                   bsnd_patch_channels(&d, id));
        }
        printf("  id NOPE/MenuSelect = %u\n", bsnd_patch_id(&d, "NOPE", "MenuSelect"));
        printf("  id FRONTEND/HelpLoop = %u ch=%u\n",
               bsnd_patch_id(&d, "FRONTEND", "HelpLoop"),
               bsnd_patch_channels(&d, bsnd_patch_id(&d, "FRONTEND", "HelpLoop")));
        printf("  id FRONTEND/RewardEnter = %u ch=%u\n",
               bsnd_patch_id(&d, "FRONTEND", "RewardEnter"),
               bsnd_patch_channels(&d, bsnd_patch_id(&d, "FRONTEND", "RewardEnter")));
    }

    // 5. Playing: the defaults, then each override in turn.
    scenario(5, "play defaults");
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "COMMON", "MenuUpDown", 8000, 0x4000, 0, BSND_VOICE_ALLOC);
    play_pan(&d, "FRONTEND", "RewardEnter", BSND_RATE_PATCH, BSND_VOLUME_PATCH,
             -64, BSND_VOICE_ALLOC);
    play(&d, "FRONTEND", "RewardEnter", BSND_RATE_PATCH, BSND_VOLUME_PATCH,
         0x2000, BSND_VOICE_ALLOC);
    play_pan(&d, "FRONTEND", "RewardExit", BSND_RATE_PATCH, BSND_VOLUME_PATCH,
             127, BSND_VOICE_ALLOC);
    play_pan(&d, "FRONTEND", "RewardExit", BSND_RATE_PATCH, BSND_VOLUME_PATCH,
             -127, BSND_VOICE_ALLOC);
    play_pan(&d, "FRONTEND", "RewardExit", BSND_RATE_PATCH, BSND_VOLUME_PATCH,
             BSND_PAN_PATCH, BSND_VOICE_ALLOC);
    play(&d, "COMMON", "NoSuchPatch", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "NOPE", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);

    // 6. Explicit voices, including the two that must be refused.
    scenario(6, "explicit voices");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "COMMON", common, commonSize, false);
    bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0, 10);
    play(&d, "FRONTEND", "RewardEnter", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_MAX_VOICES - 1);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_MAX_VOICES - 1);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_MAX_VOICES);

    // 7. Exhaustion: stereo patches are two voices each, so twelve of them
    //    fill a 24-channel driver and the thirteenth must fail.
    scenario(7, "exhaustion");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "COMMON", common, commonSize, false);
    for (int i = 0; i < 14; i++)
        play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
             BSND_VOICE_ALLOC);
    printf("busy:");
    for (unsigned i = 0; i < d.voices; i++)
        printf(" %d", bsnd_channel_busy(&d, (uint16_t)i) ? 1 : 0);
    printf("\n");
    // Free one pair and watch the next allocation land in the hole.
    bsnd_voice_stop(&d, 6);
    dump_voices(&d);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);

    // 8. Setters on a live voice, both channels of a stereo pair at once.
    scenario(8, "setters");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "COMMON", common, commonSize, false);
    bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "FRONTEND", "RewardEnter", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    for (int mode = BSND_MODE_MONO; mode <= BSND_MODE_PROLOGIC; mode++) {
        bsnd_set_mode(&d, (uint8_t)mode);
        printf("mode %d\n", mode);
        bsnd_set_voice_volume(&d, 0, 0x2000);
        bsnd_set_voice_pan(&d, 0, 64);
        bsnd_set_voice_volume_pan(&d, 0, 0x7fff, -32);
        bsnd_set_voice_pitch(&d, 0, 11025);
        bsnd_set_voice_volume(&d, 2, 0x1000);
        bsnd_set_voice_pan(&d, 2, -100);
        bsnd_set_voice_pitch(&d, 2, 44100);
        printf("  get v0 vol=%u pan=%d pitch=%u | v2 vol=%u pan=%d pitch=%u\n",
               bsnd_get_voice_volume(&d, 0), bsnd_get_voice_pan(&d, 0),
               bsnd_get_voice_pitch(&d, 0), bsnd_get_voice_volume(&d, 2),
               bsnd_get_voice_pan(&d, 2), bsnd_get_voice_pitch(&d, 2));
        dump_voices(&d);
    }
    // Out-of-range voices must do nothing rather than write past the table.
    bsnd_set_mode(&d, BSND_MODE_STEREO);
    bsnd_set_voice_volume(&d, BSND_MAX_VOICES, 0x100);
    bsnd_set_voice_pan(&d, 0xffff, 0);
    bsnd_voice_stop(&d, BSND_MAX_VOICES + 5);
    printf("  out of range v=%u pan=%d pitch=%u busy=%d paused=%d\n",
           bsnd_get_voice_volume(&d, BSND_MAX_VOICES),
           bsnd_get_voice_pan(&d, BSND_MAX_VOICES),
           bsnd_get_voice_pitch(&d, BSND_MAX_VOICES),
           bsnd_channel_busy(&d, BSND_MAX_VOICES) ? 1 : 0,
           bsnd_voice_paused(&d, BSND_MAX_VOICES) ? 1 : 0);
    dump_voices(&d);

    // 9. Pause and resume, and what an update does to a paused voice.
    scenario(9, "pause");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "COMMON", common, commonSize, false);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    bsnd_voice_pause(&d, 0);
    printf("  paused=%d busy=%d\n", bsnd_voice_paused(&d, 0) ? 1 : 0,
           bsnd_channel_busy(&d, 0) ? 1 : 0);
    tick(&d); tick(&d); tick(&d); tick(&d);
    dump_voices(&d);
    bsnd_voice_resume(&d, 0);
    printf("  paused=%d\n", bsnd_voice_paused(&d, 0) ? 1 : 0);
    tick(&d); tick(&d); tick(&d); tick(&d);
    dump_voices(&d);

    // 10. Retirement: a one-shot gives its voices back, a loop does not.
    scenario(10, "retirement");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false);
    play(&d, "FRONTEND", "HelpLoop", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "FRONTEND", "RewardEnter", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    for (int i = 0; i < 5; i++) { tick(&d); dump_voices(&d); }
    play(&d, "FRONTEND", "RewardExit", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);

    // 11. Unloading a bank stops what it was playing and leaves the rest.
    scenario(11, "unload");
    bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
    bsnd_bank_register(&d, "COMMON", common, commonSize, false);
    bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false);
    play(&d, "COMMON", "MenuSelect", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "FRONTEND", "HelpLoop", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    play(&d, "COMMON", "MenuWrong", BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0,
         BSND_VOICE_ALLOC);
    printf("unload FRONTEND=%d\n", bsnd_bank_unload(&d, "FRONTEND"));
    dump_voices(&d);
    printf("  patchCount=%u loaded COMMON=%d FRONTEND=%d\n", d.patchCount,
           bsnd_bank_loaded(&d, "COMMON"), bsnd_bank_loaded(&d, "FRONTEND"));
    printf("unload FRONTEND again=%d\n", bsnd_bank_unload(&d, "FRONTEND"));
    printf("  id FRONTEND/HelpLoop = %u\n", bsnd_patch_id(&d, "FRONTEND", "HelpLoop"));
    // Two statements, not one printf: C does not say which argument is
    // evaluated first, so a single call would print patchCount from before or
    // after the register depending on the compiler, and the checker would be
    // diffing the host toolchain rather than the driver.
    {
        int ok = bsnd_bank_register(&d, "FRONTEND", frontend, frontendSize, false);
        printf("  re-register FRONTEND=%d patchCount=%u\n", ok, d.patchCount);
    }
    printf("  id FRONTEND/HelpLoop = %u\n", bsnd_patch_id(&d, "FRONTEND", "HelpLoop"));
    dump_voices(&d);

    // 12. Every patch in both banks, played once on its own driver, which is
    //     the pass that would notice a patch whose audio went astray.
    scenario(12, "every patch");
    {
        static const char* banks[2] = { "COMMON", "FRONTEND" };
        for (int b = 0; b < 2; b++) {
            bsnd_init(&d, &kRecSink, BSND_MAX_VOICES);
            bsnd_bank_register(&d, banks[b], b ? frontend : common,
                               b ? frontendSize : commonSize, false);
            for (uint16_t id = 0; id < d.patchCount; id++) {
                SndPatch p;
                if (!bsnd_patch_get(&d, id, &p)) { printf("  id %u reject\n", id); continue; }
                printf("  patch %u %s ch=%u rate=%u vol=%u loop=%d\n",
                       id, p.name, p.channels, p.rate, p.volume, p.looping ? 1 : 0);
                play(&d, banks[b], p.name, BSND_RATE_PATCH, BSND_VOLUME_PATCH, 0, 0);
                bsnd_voice_stop(&d, 0);
            }
        }
    }

    free(common);
    free(frontend);
    return 0;
}
