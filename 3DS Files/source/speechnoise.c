#include "speechnoise.h"

#include "sound.h"

static SpeechNoise gSpeechNoise;            // 0x003341d0
static int32_t     gSpeechNoiseBuilt;       // gp-19072

static const char *const SquelchNames[SPEECHNOISE_SQUELCHES] = {
    "RadioNoiseSquelch01", "RadioNoiseSquelch02",
};

static const char *const RadioNames[SPEECHNOISE_RADIOS] = {
    "RadioNoise01", "RadioNoise02", "RadioNoise03", "RadioNoise04",
    "RadioNoise05", "RadioNoise06", "RadioNoise07",
};

SpeechNoise *speechnoise_get_instance(void)
{
    // Retail registers the destructor with atexit; it does nothing
    // without the delete flag.
    if (!gSpeechNoiseBuilt) {
        speechnoise_construct(&gSpeechNoise);
        gSpeechNoiseBuilt = 1;
    }
    return &gSpeechNoise;
}

void speechnoise_construct(SpeechNoise *n)
{
    n->RadioNoiseOn = 0;
    n->RequestSampleLoad = 0;
    n->Helicopter = NULL;
    n->SpeechNoiseMuted = 0;
}

void speechnoise_load_samples(SpeechNoise *n)
{
    BRegion *r = bsound_region(bsound_get(), "InGame");
    int i;

    for (i = 0; i < SPEECHNOISE_SQUELCHES; i++) {
        n->Squelch[i] = bregion_sample(r, SquelchNames[i]);
        bsample_set_category(n->Squelch[i], 6);
    }
    for (i = 0; i < SPEECHNOISE_RADIOS; i++) {
        n->Radio[i] = bregion_sample(r, RadioNames[i]);
        bsample_set_category(n->Radio[i], 6);
    }
    n->RequestSampleLoad = 0;
}

void speechnoise_request_samples(SpeechNoise *n)
{
    n->RequestSampleLoad = 1;
}

void speechnoise_unload_samples(SpeechNoise *n)
{
    if (n->Helicopter != NULL)
        speechnoise_stop_helicopter_noise(n);
    speechnoise_stop_radio_noise(n);
    n->Helicopter = NULL;
}

void speechnoise_update(SpeechNoise *n)
{
    SoundModule *m = sound_get();

    if (n->RequestSampleLoad && sound_is_region_loading_complete(m))
        speechnoise_load_samples(n);
    if (!sound_is_region_loading_complete(m) || n->SpeechNoiseMuted
        || !n->RadioNoiseOn)
        return;
    if (sound_random_float(m, 1.0f) < 0.03f) {              // gp-27372
        float vol = sound_random_float(m, 0.4f) + 0.6f;     // gp-27368, -27364
        BSample *s = n->Radio[sound_random_int(m, SPEECHNOISE_RADIOS)];

        if (s != NULL)
            bsample_play(s, vol, 0.0f, 1.0f);
    }
}

void speechnoise_mute(SpeechNoise *n, int32_t on)
{
    int i;

    n->SpeechNoiseMuted = on;
    for (i = 0; i < SPEECHNOISE_RADIOS; i++)
        if (n->Radio[i] != NULL)
            bsample_pause(n->Radio[i], on != 0);
    if (n->Helicopter != NULL)
        bsample_pause(n->Helicopter, on != 0);
}

void speechnoise_start_helicopter_noise(SpeechNoise *n)
{
    if (n->Helicopter != NULL)
        bsample_play(n->Helicopter, 1.0f, 0.0f, 0.0f);
}

void speechnoise_stop_helicopter_noise(SpeechNoise *n)
{
    if (n->Helicopter != NULL && bsample_is_playing(n->Helicopter))
        bsample_stop(n->Helicopter);
}

void speechnoise_start_radio_noise(SpeechNoise *n)
{
    n->RadioNoiseOn = 1;
}

void speechnoise_stop_radio_noise(SpeechNoise *n)
{
    n->RadioNoiseOn = 0;
}

int32_t speechnoise_is_radio_noise(const SpeechNoise *n)
{
    return n->RadioNoiseOn;
}

void speechnoise_begin_squelch_noise(SpeechNoise *n)
{
    // Retail plays it unguarded; the port's bsample_play skips a missing
    // one.
    bsample_play(n->Squelch[sound_random_int(sound_get(),
                                             SPEECHNOISE_SQUELCHES)],
                 1.0f, 0.0f, 0.0f);
}

int32_t speechnoise_is_squelch_noise_playing(const SpeechNoise *n)
{
    // Retail asks a missing squelch too; the port's test.
    int32_t playing = 0;

    if (n->Squelch[0] != NULL && bsample_is_playing(n->Squelch[0]))
        playing = 1;
    else if (n->Squelch[1] != NULL && bsample_is_playing(n->Squelch[1]))
        playing = 1;
    return playing;
}
