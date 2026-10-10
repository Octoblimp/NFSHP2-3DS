#include "choppersound.h"

#include "bmem.h"
#include "carinit.h"
#include "chopper.h"
#include "realtime.h"
#include "sound.h"
#include "soundscape.h"
#include "vtable.h"

Sound3dEnvelope ChopperSoundEnvelope = { 5.0f, 200.0f, 0.005f };

// `max.s`, fs then ft, as collision.c has it.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

void choppersound_construct(ChopperSound *s, struct Chopper *h)
{
    sound3d_construct(&s->Sound);
    s->pChopper = h;
    s->Sound._vtable = CHOPPERSOUND_VTABLE;
    s->pChopperSample = NULL;
    if (SoundEnabled) {
        s->pChopperSample = sound_get_in_game_sample(sound_get(),
                                                     "ChopperEngine");
        bsample_set_category(s->pChopperSample, 0);
        // Retail asks IsPlaying of a missing sample too; the port's test.
        if (s->pChopperSample != NULL
            && bsample_is_playing(s->pChopperSample))
            bsample_stop(s->pChopperSample);
    }
    s->InSideTunnel = 0;
    s->TunnelFadeCounter = 0.0f;
}

void choppersound_destroy(ChopperSound *s, int32_t flags)
{
    s->Sound._vtable = CHOPPERSOUND_VTABLE;
    sound3d_destroy(&s->Sound, flags);
}

void choppersound_adjust_for_tunnel_volume(ChopperSound *s, float *volume)
{
    int32_t t = soundscape_is_inside_tunnel();

    if (t) {
        if (!s->InSideTunnel) {
            s->InSideTunnel = t;
            s->TunnelFadeCounter = 1.0f;
        } else if (0.0f < s->TunnelFadeCounter) {
            s->TunnelFadeCounter -= WorldTimeElapsed;
            *volume = max_s(*volume * s->TunnelFadeCounter, 0.0f);
        } else {
            *volume = 0.0f;
        }
    } else if (s->InSideTunnel) {
        if (s->TunnelFadeCounter <= 0.0f) {
            s->TunnelFadeCounter = 1.0f;
            *volume = 0.0f;
        } else {
            *volume *= s->TunnelFadeCounter;
            s->TunnelFadeCounter = 1.0f - s->TunnelFadeCounter;
        }
        s->InSideTunnel = t;
    } else if (0.0f < s->TunnelFadeCounter) {
        s->TunnelFadeCounter -= WorldTimeElapsed;
        *volume *= 1.0f - s->TunnelFadeCounter;
    }
}

void choppersound_update(ChopperSound *s, float volume, uint16_t azimuth,
                         float pitch)
{
    (void)volume;
    (void)azimuth;
    (void)pitch;
    if (!SoundEnabled || !s->Sound.Activated || s->pChopperSample == NULL)
        return;
    sound3d_update(&s->Sound, &s->pChopper->CurrentPos,
                   &ChopperSoundEnvelope);
    choppersound_adjust_for_tunnel_volume(s, &s->Sound.Volume);
    if (bsample_is_playing(s->pChopperSample)) {
        bsample_set_volume(s->pChopperSample, s->Sound.Volume);
        bsample_set_azimuth(s->pChopperSample, s->Sound.Azimuth);
        bsample_set_pitch(s->pChopperSample, s->Sound.Pitch - 1.0f);
    } else {
        bsample_play(s->pChopperSample, s->Sound.Volume,
                     (float)(int32_t)s->Sound.Azimuth,
                     s->Sound.Pitch - 1.0f);
    }
}

void choppersound_mute(ChopperSound *s, int32_t on)
{
    if (SoundEnabled && s->pChopperSample != NULL)
        bsample_pause(s->pChopperSample, on != 0);
}

void choppersound_deactivate_sound(ChopperSound *s)
{
    if (SoundEnabled && s->pChopperSample != NULL)
        bsample_stop(s->pChopperSample);
}

void choppersound_activate_sound(ChopperSound *s)
{
    if (SoundEnabled && s->pChopperSample != NULL)
        bsample_play(s->pChopperSample, s->Sound.Volume,
                     (float)(int32_t)s->Sound.Azimuth,
                     s->Sound.Pitch - 1.0f);
}

Sound3d *choppersound_create(struct Chopper *h)
{
    ChopperSound *s = (ChopperSound *)bMalloc((int)sizeof(ChopperSound),
                                              "ChopperSound", 0, 16);

    choppersound_construct(s, h);
    return &s->Sound;
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$12ChopperSound, 0x002bc2a8.
static const VtEntry choppersound_vt[CHOPPERSOUND_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(choppersound_destroy),                            //  8  0x00214df0
    E(sound3d_activate),                                // 16  0x00208b28
    E(choppersound_update),                             // 24  0x00214f30
    E(choppersound_mute),                               // 32  0x00215000
    E(choppersound_deactivate_sound),                   // 40  0x00215028
    E(choppersound_activate_sound),                     // 48  0x00215050
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56  0x00208c78
};

#undef E

void choppersound_install_vtables(void)
{
    vt_install(CHOPPERSOUND_VTABLE, choppersound_vt,
               CHOPPERSOUND_VT_ENTRIES);
}
