#include "enginesound.h"

#include <stddef.h>
#include <string.h>

#include "bfile.h"
#include "bmem.h"
#include "bticker.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "carsound.h"
#include "cartypeinfo.h"
#include "drivetrain.h"
#include "eefpu.h"
#include "engine.h"
#include "eview.h"
#include "physicscar.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "realtime.h"
#include "sound.h"
#include "vtable.h"

PlayerEngineSound *LastPlayerEngineSound;       // gp-16268

// The game's audio mode as the player's engine sees it: sound's own with
// retail's voices, and mono, 0, without (enginesound.h).
static int32_t engine_audio_mode(void)
{
#if ENGINESOUND_RETAIL_VOICES
    return sound_get_audio_mode(sound_get());
#else
    return 0;
#endif
}

// CrossFade (0x0031bc80), 129 bytes from 0 to 127: how loud each side of a
// crossfade is, by how far along it is. UpdateEngine indexes it with
// 127 - Timbre, and Timbre is a signed byte that the replay cameras can
// take below 0, so retail reads up to 128 bytes either side: these are
// 0x0031bc00 .. 0x0031bd7f, the table at 128, its neighbours as the image
// has them (CentsToPitch's head after it).
static const uint8_t CrossFadeImage[384] = {
    0x40, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00,  // 0031bc00
    0x00, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x08, 0x00, 0x00, 0x00,  // 0031bc10
    0x40, 0x00, 0x00, 0x00, 0x00, 0x02, 0x00, 0x00, 0x00, 0x10, 0x00, 0x00, 0x00, 0x80, 0x00, 0x00,  // 0031bc20
    0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x20, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // 0031bc30
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // 0031bc40
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // 0031bc50
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // 0031bc60
    0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,  // 0031bc70
    0x00, 0x03, 0x07, 0x0a, 0x0d, 0x10, 0x13, 0x16, 0x18, 0x1b, 0x1d, 0x1f, 0x21, 0x23, 0x25, 0x27,  // 0031bc80
    0x29, 0x2b, 0x2d, 0x2e, 0x30, 0x32, 0x33, 0x35, 0x36, 0x37, 0x39, 0x3a, 0x3c, 0x3d, 0x3e, 0x3f,  // 0031bc90
    0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50,  // 0031bca0
    0x51, 0x52, 0x53, 0x54, 0x54, 0x55, 0x56, 0x57, 0x58, 0x58, 0x59, 0x5a, 0x5b, 0x5b, 0x5c, 0x5d,  // 0031bcb0
    0x5e, 0x5e, 0x5f, 0x60, 0x60, 0x61, 0x62, 0x62, 0x63, 0x64, 0x64, 0x65, 0x65, 0x66, 0x67, 0x67,  // 0031bcc0
    0x68, 0x68, 0x69, 0x6a, 0x6a, 0x6b, 0x6b, 0x6c, 0x6c, 0x6d, 0x6d, 0x6e, 0x6e, 0x6f, 0x6f, 0x70,  // 0031bcd0
    0x70, 0x71, 0x71, 0x72, 0x72, 0x73, 0x73, 0x74, 0x74, 0x75, 0x75, 0x76, 0x76, 0x77, 0x77, 0x77,  // 0031bce0
    0x78, 0x78, 0x79, 0x79, 0x7a, 0x7a, 0x7a, 0x7b, 0x7b, 0x7c, 0x7c, 0x7d, 0x7d, 0x7d, 0x7e, 0x7f,  // 0031bcf0
    0x7f, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x02, 0x03, 0x04, 0x04, 0x05,  // 0031bd00
    0x06, 0x07, 0x07, 0x08, 0x09, 0x09, 0x0a, 0x0b, 0x0c, 0x0c, 0x0d, 0x0e, 0x0e, 0x0f, 0x10, 0x11,  // 0031bd10
    0x11, 0x12, 0x13, 0x14, 0x14, 0x15, 0x16, 0x17, 0x17, 0x18, 0x19, 0x1a, 0x1a, 0x1b, 0x1c, 0x1d,  // 0031bd20
    0x1e, 0x1e, 0x1f, 0x20, 0x21, 0x21, 0x22, 0x23, 0x24, 0x25, 0x25, 0x26, 0x27, 0x28, 0x29, 0x29,  // 0031bd30
    0x2a, 0x2b, 0x2c, 0x2d, 0x2d, 0x2e, 0x2f, 0x30, 0x31, 0x32, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37,  // 0031bd40
    0x37, 0x38, 0x39, 0x3a, 0x3b, 0x3c, 0x3d, 0x3d, 0x3e, 0x3f, 0x40, 0x41, 0x42, 0x43, 0x43, 0x44,  // 0031bd50
    0x45, 0x46, 0x47, 0x48, 0x49, 0x4a, 0x4b, 0x4b, 0x4c, 0x4d, 0x4e, 0x4f, 0x50, 0x51, 0x52, 0x53,  // 0031bd60
    0x54, 0x55, 0x56, 0x56, 0x57, 0x58, 0x59, 0x5a, 0x5b, 0x5c, 0x5d, 0x5e, 0x5f, 0x60, 0x61, 0x62,  // 0031bd70
};

// CrossFade[i], `lb`: -128 .. 255.
static int32_t cross_fade(int32_t i)
{
    return (int8_t)CrossFadeImage[128 + i];
}

// AIEngineSound's settling after a gear change, by frames since it:
// 0x0031be08's steps and 0x0031be18's volume scales.
static const int16_t GearChangeSteps[6] = { 12, 25, 50, 100, 200, 400 };
static const float GearChangeVolumes[6] = {
    0.8f, 0.6f, 0.4f, 0.4f, 0.4f, 0.8f
};

// --------------------------------------------------------------- helpers

// smooth<float> (0x00136630): `a` a step of at most `step` towards `b`.
static float smooth(float a, float b, float step)
{
    float up = a + step;
    float down;

    if (up < b)
        return up;
    down = a - step;
    if (b < down)
        return down;
    return b;
}

// smooth<float> (0x002123b8), with a step each way.
static float smooth4(float a, float b, float up_step, float down_step)
{
    float up = a + up_step;
    float down;

    if (up < b)
        return up;
    down = a - down_step;
    if (b < down)
        return down;
    return b;
}

// smooth<short> (0x002122e0), the sums in a word.
static int16_t smooth_s16(int16_t a, int16_t b, int16_t step)
{
    int32_t up = a + step;
    int32_t down;

    if (up < b)
        return (int16_t)up;
    down = a - step;
    if (b < down)
        return (int16_t)down;
    return b;
}

// min<int> (0x00212340), max<int> (0x00212330), clamp<int> (0x00212350).
static int32_t min_i(int32_t a, int32_t b)
{
    return a < b ? a : b;
}

static int32_t max_i(int32_t a, int32_t b)
{
    return b < a ? a : b;
}

static int32_t clamp_i(int32_t x, int32_t lo, int32_t hi)
{
    return min_i(max_i(x, lo), hi);
}

// min<float> and max<float> (0x001365f0, 0x001365e0), min.s and max.s.
static float min_f(float a, float b)
{
    return b < a ? b : a;
}

static float max_f(float a, float b)
{
    return a < b ? b : a;
}

// The car's RPM, or the debug TestRPM (car.h) once that is off 100.
static float car_rpm(const Car *c)
{
    return TestRPM == 100.0f ? c->State.RPM : TestRPM;
}

static DriveTrain *car_drive_train(const Car *c)
{
    return ((PhysicsCar *)(void *)c->pCarMover)->pDriveTrain;
}

// Slot `a`'s volume by level. The tables keep their self-relative offsets
// (enginesound.h): the field's own address plus what it holds.
static const int8_t *vol_table(const EngineDef *d, int32_t a)
{
    return (const int8_t *)&d->pvoltable[a] + d->pvoltable[a];
}

// ------------------------------------------------------------- VoiceAttr

void enginevoice_play(EngineVoiceAttr *v, const EnginePlayOptions *o)
{
    int16_t vol = o->vol < 0 ? 0 : o->vol;

    v->vol = vol;
    v->azim = o->azimuth;
    v->pitch = o->pitch;
    v->bend = o->bend;
    if (SoundEnabled && CarSoundEnabled)
        bsample_play(&v->sample, (float)vol * (1.0f / 127.0f), 0.0f,
                     o->pitch);                         // gp-27628
    bsample_set_azimuth(&v->sample, v->azim);
}

void enginevoice_stop(EngineVoiceAttr *v)
{
    if (v->vol != 0)
        enginevoice_set_volume(v, 0);
    else
        bsample_stop(&v->sample);
}

void enginevoice_set_volume(EngineVoiceAttr *v, int16_t vol)
{
    int16_t n = smooth_s16(v->vol, vol, 15);

    if (n == v->vol)
        return;
    if (n < 0)
        n = 0;
    v->vol = n;
    bsample_set_volume(&v->sample, (float)n * (1.0f / 127.0f)); // gp-27624
}

void enginevoice_set_pitch(EngineVoiceAttr *v, float pitch)
{
    if (v->pitch == pitch)
        return;
    v->pitch = pitch;
    bsample_set_pitch(&v->sample, pitch);
}

void enginevoice_set_azimuth(EngineVoiceAttr *v, uint16_t a)
{
    if (v->azim == a)
        return;
    v->azim = a;
    bsample_set_azimuth(&v->sample, a);
}

// ---------------------------------------------------- PlayerEngineSound

// 0x0020fc70.
void playerenginesound_construct(PlayerEngineSound *s, Car *c)
{
    int32_t i;

    sound3d_construct(&s->Sound);
    s->Sound._vtable = PLAYERENGINESOUND_VTABLE;
    bsample_construct(&s->NitroStartSample, 0);
    bsample_construct(&s->NitroLoopSample, 0);
    for (i = 0; i < ENGINESOUND_VOICES; i++) {
        s->left[i].vol = 0;
        s->left[i].bend = 0;
        s->left[i].pitch = 0.0f;
        s->left[i].azim = 0;
        bsample_construct(&s->left[i].sample, 0);
    }
    for (i = 0; i < ENGINESOUND_VOICES; i++) {
        s->right[i].vol = 0;
        s->right[i].bend = 0;
        s->right[i].pitch = 0.0f;
        s->right[i].azim = 0;
        bsample_construct(&s->right[i].sample, 0);
    }
    for (i = 0; i < ENGINESOUND_PATCHES; i++) {
        s->engineSample[i].bnkID = -1;
        s->engineSample[i].patchtype = 0;
        s->engineSample[i].isEnabled = 1;
        s->engineSample[i].sample = NULL;
        s->engineSample[i].detune = 0;
        s->engineSample[i].volume = 1.0f;
    }
    s->pCar = c;
    s->CurrThrottle = 0;
    s->CurrentRPM = car_rpm(c);
    s->GearShiftingUp = 0;
    s->EngineBackfireBuildup = 0;
    s->UpdateBlownRodTime = 0.0f;
    s->fEngineDuckerThrottleTime = 0.0f;
    s->fEngineDuckerVolumeScale = 1.0f;
    s->GearShiftVolumeScale = 1.0f;
    playerenginesound_init(s);
    bsample_initialize_copy(&s->NitroStartSample,
                            sound_get_in_game_sample(sound_get(),
                                                     "NitroStart"));
    bsample_set_category(&s->NitroStartSample, 2);
    bsample_initialize_copy(&s->NitroLoopSample,
                            sound_get_in_game_sample(sound_get(),
                                                     "NitroLoop"));
    bsample_set_category(&s->NitroLoopSample, 2);
    sound3d_activate(&s->Sound, 1);
}

// 0x0020fe70.
void playerenginesound_destroy(PlayerEngineSound *s, int32_t flags)
{
    int32_t i;

    s->Sound._vtable = PLAYERENGINESOUND_VTABLE;
    for (i = 0; i < ENGINESOUND_PATCHES; i++) {
        bsample_stop(&s->left[i].sample);
        bsample_stop(&s->right[i].sample);
    }
    for (i = 0; i < 2; i++) {
        if (s->definitions[i] != NULL) {
            bFree(s->definitions[i]);
            s->definitions[i] = NULL;
        }
    }
    for (i = ENGINESOUND_VOICES - 1; i >= 0; i--)
        bsample_destruct(&s->right[i].sample);
    for (i = ENGINESOUND_VOICES - 1; i >= 0; i--)
        bsample_destruct(&s->left[i].sample);
    bsample_destruct(&s->NitroLoopSample);
    bsample_destruct(&s->NitroStartSample);
    sound3d_destroy(&s->Sound, flags);
}

void playerenginesound_init(PlayerEngineSound *s)
{
    static const char *const menu[6] = {
        "MenuStart", "MenuLeftRight", "MenuUpDown",       // 0x002bbe50 ..
        "MenuSelect", "MenuCancel", "MenuWrong",
    };
    static const char *const patches[ENGINESOUND_PATCHES] = {
        "lelo", "lemd", "lehi", "lxlo", "lxmd", "lxhi",   // 0x002bbeb0
        "ceid", "cemd", "cehi", "cxid", "cxmd", "cxhi",
    };
    static const char *const tables[2] = {
        "sound\\engine.ctb", "sound\\engine.ltb",         // 0x00331950
    };
    const SoundInfo *si;
    BRegion *r;
    char name[16];
    uint32_t t;
    int32_t i;

    if (!SoundEnabled)
        return;
    // The menu's sounds stop, and the driver runs twice, 16 ms apart, to
    // let their voices go before the engine locks its own.
    r = bsound_region(bsound_get(), "common");
    for (i = 0; i < 6; i++)
        bsample_stop(bregion_sample(r, menu[i]));
    bsound_update(bsound_get());
    t = bGetTicker();
    while (bGetTickerDifference(t, bGetTicker()) < 16.0f)
        ;
    bsound_update(bsound_get());
    t = bGetTicker();
    while (bGetTickerDifference(t, bGetTicker()) < 16.0f)
        ;
    bsound_update(bsound_get());

    si = &s->pCar->pCarTypeInfo->Sound;
    r = bsound_region(bsound_get(), si->BaseName);
    s->IsStereo = 1;
    s->CurrAudioMode = engine_audio_mode();
    for (i = 0; i < 4; i++)
        s->POVTimbre[i] = (int8_t)si->Timbre[i];
    s->BendRange = si->BendRange;
    s->BassAdd = si->BaseAdd;
    s->RedLineRPMOffset = (float)si->RedLineOffset;
    s->TopGearRPMOffset = (float)si->TopGearOffset;
    for (i = 0; i < ENGINESOUND_PATCHES; i++) {
        EngineSample *es = &s->engineSample[i];
        BSample *smp;

        es->detune = si->Detune[i];
        es->volume = si->Volume[i];
        es->patchtype = patches[i][1] == 'x';
        strcpy(name, si->Prefix);
        strcat(name, patches[i]);
        smp = bregion_sample(r, name);
        if (smp == NULL)
            return;
        es->bnkID = 1;
        bsample_initialize_copy(&s->left[i].sample, smp);
        bsample_set_category(&s->left[i].sample, 2);
        bsample_initialize_copy(&s->right[i].sample, smp);
        bsample_set_category(&s->right[i].sample, 2);
        // The "l" patches play whenever the engine does, so their voices
        // are held; retail holds the right ones too with one player.
        if (i < 6) {
            bsample_lock_voice(&s->left[i].sample);
#if ENGINESOUND_RETAIL_VOICES
            if (PlayerNumPlayers == 1)
                bsample_lock_voice(&s->right[i].sample);
#endif
        }
    }
    for (i = 0; i < 2; i++)
        s->definitions[i] = (EngineDef *)bGetFile(tables[i], NULL, 16);
    playerenginesound_resolve_tables(s);
}

void playerenginesound_deactivate_sound(PlayerEngineSound *s)
{
    (void)s;
}

void playerenginesound_activate_sound(PlayerEngineSound *s)
{
    (void)s;
}

// Unmuted in a new audio mode, every voice is let go, to start again from
// UpdateEngine in the new one; otherwise all are paused or resumed.
void playerenginesound_mute(PlayerEngineSound *s, int32_t on)
{
    bool pause = false;
    int32_t i;

    if (on == 0 && engine_audio_mode() != s->CurrAudioMode) {
        for (i = 0; i < ENGINESOUND_PATCHES; i++) {
            enginevoice_stop(&s->left[i]);
            enginevoice_stop(&s->right[i]);
        }
    } else {
        pause = on != 0;
        for (i = 0; i < ENGINESOUND_PATCHES; i++) {
            bsample_pause(&s->left[i].sample, pause);
            bsample_pause(&s->right[i].sample, pause);
        }
    }
    bsample_pause(&s->NitroStartSample, pause);
    bsample_pause(&s->NitroLoopSample, pause);
    s->CurrAudioMode = engine_audio_mode();
}

// Retail turns each table's offsets into addresses, once; the port reads
// them as offsets (vol_table) and only marks the table. HighestPatch is
// one past the last slot of the sixteen with a patch -- by retail's test,
// which reads slot 0 of the first table for the first eight and slot 1 of
// the second for the rest, so it is 16 with the disc's tables.
void playerenginesound_resolve_tables(PlayerEngineSound *s)
{
    int32_t i;

    for (i = 0; i < 2; i++)
        if (s->definitions[i]->resolved == 0)
            s->definitions[i]->resolved = 1;
    s->Volume = 0;
    s->ControllerLevel = 0;
    s->HighestPatch = 0;
    for (i = 0; i < 16; i++)
        if (s->definitions[i >= 8]->patchnum[i / 8] >= 0)
            s->HighestPatch = (int8_t)(i + 1);
}

// CurrThrottle follows the pedal, 0 .. 255: half the way up a frame, an
// eighth down, and snapped to the end near either.
void playerenginesound_ramp_throttle(PlayerEngineSound *s)
{
    int32_t t = ee_trunc_w(s->pCar->State.Throttle * 255.0f);
    int32_t cur = s->CurrThrottle;

    if (cur < t) {
        s->CurrThrottle = cur + (t - cur) / 2;
        if (s->CurrThrottle >= 254)
            s->CurrThrottle = 255;
    } else if (t < cur) {
        s->CurrThrottle = cur + (t - cur) / 8;
        if (s->CurrThrottle < 9)
            s->CurrThrottle = 0;
    }
    s->CurrThrottle = clamp_i(s->CurrThrottle, 0, 255);
}

// 0x00210788. On a shift up, while the clutch is out, the engine follows
// the clutch down to 0.4 of its volume.
void playerenginesound_update_gear_shift_effect(PlayerEngineSound *s)
{
    Car *c = s->pCar;
    DriveTrain *dt;
    float target = 1.0f;

    if (c == NULL || c->TheMovementMode != PHYSICS_MOVEMENT)
        return;
    dt = car_drive_train(c);
    if (dt->CurrentGear < dt->DesiredGear)
        s->GearShiftingUp = 1;
    else if (dt->DesiredGear < dt->CurrentGear)
        s->GearShiftingUp = 0;
    if (s->GearShiftingUp && 1500.0f < car_rpm(c)       // gp-27620
        && (dt->CurrentClutchState == CLUTCH_DISENGAGING
            || dt->CurrentClutchState == CLUTCH_ENGAGING))
        target = max_f(0.4f, drivetrain_get_state(dt)->clutch);
    s->GearShiftVolumeScale = smooth(s->GearShiftVolumeScale, target, 0.2f);
}

// The engine's sound runs to the red line in every gear from second up,
// whatever the shift point: the RPM is scaled by the red line (plus the
// car's offset) over the shift point, and the top gear adds its own
// offset. The result is State.RedLineSyncRPM too.
void playerenginesound_update_to_red_line_rpm(PlayerEngineSound *s,
                                              float *rpm)
{
    Car *c = s->pCar;
    float r = *rpm;

    if (c != NULL && c->TheMovementMode == PHYSICS_MOVEMENT) {
        DriveTrain *dt = car_drive_train(c);
        const EngineInfo *ei = dt->pEngine->EI;
        int32_t gear = dt->CurrentGear;

        if (gear >= 2) {
            float red = ei->RedLineRPM + s->RedLineRPMOffset;
            float shift = dt->ShiftUpRPM[gear + 1];
            float ratio;

            if (red < shift)
                shift = red;
            ratio = ee_div(red, shift);
            r *= ratio;
            if (c->State.CurrentGear
                == c->pCarTypeInfo->DriveTrain.NumGears + 1)
                r += s->TopGearRPMOffset;
            r = min_f(r, ei->MaxRPM * ratio);
        }
    }
    c->State.RedLineSyncRPM = r;
    *rpm = r;
}

// Nitro: a start and a loop, two and a half times the engine's volume. The
// loop rises in pitch over the boost and fades after 3.2 seconds of it.
void playerenginesound_update_nitro_effect(PlayerEngineSound *s,
                                           float volume, uint16_t azimuth,
                                           float pitch)
{
    Car *c = s->pCar;
    Engine *e;

    if (c == NULL || c->TheMovementMode != PHYSICS_MOVEMENT)
        return;
    e = car_drive_train(c)->pEngine;
    if (e->NitroFlag) {
        if (!bsample_is_playing(&s->NitroLoopSample)) {
            float v = volume * 2.5f;
            float a = (float)azimuth;

            // The azimuth goes in as the pan, as retail has it.
            bsample_play(&s->NitroStartSample, v, a, 0.0f);
            bsample_play(&s->NitroLoopSample, v, a, pitch);
        } else {
            float f = (WorldTimeSeconds - e->NitroBoostTimer) * 0.25f;
            float p = f + 0.5f;
            float scale = 1.0f;

            if (0.8f < f)                                   // gp-27608
                scale = 1.0f - (f - 0.8f) * 5.0f;
            bsample_set_volume(&s->NitroLoopSample, volume * scale * 2.5f);
            bsample_set_azimuth(&s->NitroLoopSample, azimuth);
            bsample_set_pitch(&s->NitroLoopSample, pitch * p);
        }
    } else if (bsample_is_playing(&s->NitroLoopSample)) {
        bsample_stop(&s->NitroLoopSample);
    }
}

// With the music up, five seconds on the throttle bring the engine down
// to three quarters; lifting brings it back.
void playerenginesound_update_engine_ducker(PlayerEngineSound *s)
{
    if (!(0.05f < bsound_get_category_volume(bsound_get(), 4)))
        return;
    if (s->pCar->State.Throttle < 0.5f) {
        s->fEngineDuckerThrottleTime = 0.0f;
        s->fEngineDuckerVolumeScale =
            smooth(s->fEngineDuckerVolumeScale, 1.0f, 0.008f);
    } else {
        s->fEngineDuckerThrottleTime += WorldTimeElapsed;
        if (5.0f < s->fEngineDuckerThrottleTime)
            s->fEngineDuckerVolumeScale =
                smooth(s->fEngineDuckerVolumeScale, 0.75f, 0.008f);
    }
}

// Slots 0 .. 7 are engine.ctb's (coast), 8 .. 15 engine.ltb's (load); each
// names a patch. Its volume at this level comes from its table, crossfaded
// by the throttle between the two sets and by Timbre between the "e" and
// "x" patches; its bend from the level. A patch that goes quiet is let
// go. One that starts plays its left voice, and the right follows two
// frames later in stereo.
void playerenginesound_update_engine(PlayerEngineSound *s)
{
    int32_t i;

    playerenginesound_update_gear_shift_effect(s);
    s->CurrentLevel = s->ControllerLevel = s->ControllerLevelTarget;
    for (i = 0; i < s->HighestPatch; i++) {
        int32_t load = i >= 8;
        int32_t a = load ? i - 8 : i;
        const EngineDef *def = s->definitions[load];
        int32_t patch = def->patchnum[a];
        EngineSample *es;
        EngineVoiceAttr *l, *r;
        EnginePlayOptions o;
        int32_t lvl, b, v, vol;
        uint16_t azl, azr;
        float pitch, f;

        if (patch < 0)
            continue;
        es = &s->engineSample[patch];
        if (es->bnkID == -1)
            continue;
        lvl = s->CurrentLevel;
        b = (int8_t)ee_trunc_w((float)(lvl * 127) * (1.0f / 440.0f));
        pitch = (float)(s->BassAdd + es->detune
                        + (((b - 64) * s->BendRange) >> 6))
                * (1.0f / 1200.0f);                         // gp-27592
        v = (vol_table(def, a)[lvl] * s->Volume) >> 7;
        v = (v * cross_fade(load ? s->Ratio : 127 - s->Ratio)) >> 7;
        l = &s->left[patch];
        r = &s->right[patch];
        if (v == 0) {
            if (bsample_is_playing(&l->sample)) {
                enginevoice_stop(l);
                enginevoice_stop(r);
            }
            continue;
        }
        v = (v * 5) >> 2;
        if (v >= 128)
            v = 127;
        v = (v * cross_fade(es->patchtype ? s->Timbre : 127 - s->Timbre))
            >> 7;
        f = s->GearShiftVolumeScale * s->fEngineDuckerVolumeScale
            * es->volume;
        if (s->CurrAudioMode == 0)
            f *= 1.3f;                                      // gp-27588
        azr = (uint16_t)(s->Azim + s->Seperation);
        azl = (uint16_t)(s->Azim - s->Seperation);
        vol = ee_trunc_w((float)v * f);

        if (!bsample_is_playing(&l->sample)) {
            s->delay[patch] = 2;
            o.vol = (int16_t)vol;
            o.bend = 64;
            o.pitch = pitch;
            o.azimuth = azl;
            o.elevation = 0;
            if (es->isEnabled)
                enginevoice_play(l, &o);
            continue;
        }
        if (s->IsStereo && !bsample_is_playing(&r->sample)
            && s->delay[patch] <= 0) {
            o.vol = (int16_t)vol;
            o.bend = 64;
            o.pitch = pitch;
            o.azimuth = azr;
            o.elevation = 0;
            if (es->isEnabled)
                enginevoice_play(r, &o);
        } else {
            s->delay[patch] = (int8_t)(uint8_t)(s->delay[patch] - 1);
        }
        if (!es->isEnabled && bsample_is_playing(&l->sample))
            enginevoice_stop(l);
        if (!es->isEnabled && bsample_is_playing(&r->sample))
            enginevoice_stop(r);
        enginevoice_set_volume(l, (int16_t)(vol > -1 ? vol : 0));
        enginevoice_set_volume(r, (int16_t)(vol > -1 ? vol : 0));
        enginevoice_set_azimuth(l, azl);
        enginevoice_set_azimuth(r, azr);
        enginevoice_set_pitch(l, pitch);
        enginevoice_set_pitch(r, pitch);
    }
}

void playerenginesound_update(PlayerEngineSound *s, float volume,
                              uint16_t azimuth, float pitch)
{
    const CarTypeInfo *cti;
    const Camera *cam;
    RCState st;
    Car *c;
    float dx, dy, dz, dist, rpm, facing = 0.0f;
    int32_t vol, ratio, dist2, dop, thr, pov = 0;

    if (!s->Sound.Activated || !SoundEnabled || !CarSoundEnabled)
        return;
    playerenginesound_ramp_throttle(s);
    c = s->pCar;
    cti = c->pCarTypeInfo;
    cam = eGetView(c->pPlayer->ViewID)->pCamera;
    // The distance to the camera is worked out and passed to Set, which
    // does not read it.
    dx = c->State.Position.x - cam->CurrentKey.Position.x;
    dy = c->State.Position.y - cam->CurrentKey.Position.y;
    dz = c->State.Position.z - cam->CurrentKey.Position.z;
    dist = ee_sqrt((dx * dx + dy * dy) + dz * dz);
    rpm = car_rpm(c) - (float)(uint16_t)cti->Sound.IdleOffset;
    playerenginesound_update_to_red_line_rpm(s, &rpm);
    s->CurrentRPM = smooth4(s->CurrentRPM, rpm, 270.0f, 650.0f);
    playerenginesound_update_engine_ducker(s);
    playerenginesound_update_nitro_effect(s, volume, azimuth, pitch);

    vol = ee_trunc_w(volume * 127.0f);
    ratio = min_i(440, ee_trunc_w(ee_div(s->CurrentRPM, cti->Engine.MaxRPM)
                                  * 440.0f));
    dist2 = ee_trunc_w(dist * dist);
    dop = ee_trunc_w(pitch * 65536.0f);
    thr = s->CurrThrottle;
    if (c->pPlayer != NULL)
        pov = c->pPlayer->PlayerSettings.DriveCameraPOVIndex;
    // In a replay the timbre follows how far the car faces the camera.
    st = pRaceCoordinator->CurrentRCState;
    if (st == RCSTATE_INSTANT_REPLAY || st == RCSTATE_POSTRACE
        || st == RCSTATE_AUTO_REPLAY
        || racecoordinator_is_replay_demo_mode(pRaceCoordinator)) {
        const bVector3 *d = &cam->CurrentKey.Direction;
        const bVector4 *body = &c->State.BodyMatrix.v0;

        facing = (d->x * body->x + d->y * body->y) + d->z * body->z;
        pov = -1;
    }
    // From the car's own camera, stereo spreads each pair either side of
    // the middle; elsewhere, and in mono, the pair is one voice where the
    // car is.
    if ((float)azimuth == 0.0f && engine_audio_mode() == 1) {
        s->IsStereo = 1;
        s->Seperation = 8000;
        s->Azim = 0;
    } else if ((float)azimuth == 0.0f && engine_audio_mode() == 2) {
        s->IsStereo = 1;
        s->Seperation = 6000;
        s->Azim = 0;
    } else {
        s->IsStereo = 0;
        s->Azim = azimuth;
        s->Seperation = 0;
    }
    playerenginesound_set(s, vol, ratio, thr, dist2, dop, azimuth, facing,
                          pov);
    playerenginesound_update_engine(s);
}

void playerenginesound_set(PlayerEngineSound *s, int32_t volume,
                           int32_t ratio, int32_t throttle, int32_t dist2,
                           int32_t doppler, int32_t azimuth, float facing,
                           int32_t pov)
{
    (void)dist2;
    (void)azimuth;
    s->ControllerLevelTarget = (int16_t)ratio;
    s->Doppler = (uint16_t)(doppler >> 4);
    s->Ratio = min_i(127, throttle + (throttle >> 5));
    if (s->Ratio < 4)
        s->Ratio = 0;
    if (pov == -1)
        s->Timbre = (int8_t)ee_trunc_w((facing < 0.0f ? facing * 30.0f
                                                      : facing * 60.0f)
                                       + 44.0f);
    else
        s->Timbre = (int8_t)s->POVTimbre[pov];
    if (!(s->Timbre < 127))                     // min<char>
        s->Timbre = 127;
    s->Volume = volume;
}

// -------------------------------------------------------- AIEngineSound

void aienginesound_construct(AIEngineSound *s, Car *c)
{
    sound3d_construct(&s->Sound);
    s->Sound._vtable = AIENGINESOUND_VTABLE;
    bsample_construct(&s->EngineSample, 0);
    average_init(&s->RPMAverage, 20);
    s->pCar = c;
    s->StartLineCurrPitch = 0.0f;
    s->StartLineTargetPitch = -1.0f;
    s->CurrGear = -1;
    s->GearFrames = 10;
    s->SmoothRPM = 1000.0f;
    s->GearVolumeScale = 1.0f;
    s->EnginePitchBase = -sound_random_float(sound_get(), 0.4f);
    bsample_initialize_copy(
        &s->EngineSample,
        sound_get_in_game_sample(sound_get(),
                                 aienginesound_get_engine_sample_name(s)));
    bsample_set_category(&s->EngineSample, 0);
}

void aienginesound_destroy(AIEngineSound *s, int32_t flags)
{
    s->Sound._vtable = AIENGINESOUND_VTABLE;
    average_destroy(&s->RPMAverage, 2);
    bsample_destruct(&s->EngineSample);
    sound3d_destroy(&s->Sound, flags);
}

// Below 5 mph before the start, the engine revs at random; otherwise it
// follows the RPM, quieter after a gear change and at low speed.
void aienginesound_update(AIEngineSound *s, float volume, uint16_t azimuth,
                          float pitch)
{
    int32_t start = 0;
    float rate, p;

    if (!s->Sound.Activated)
        return;
    if (pCurrentRace != NULL
        && (race_get_race_stage(pCurrentRace) == RACE_STAGE_PRERACE
            || race_get_race_stage(pCurrentRace) == RACE_STAGE_COUNTDOWN))
        start = 1;
    if (!(s->pCar->State.VelocityMagnitude * 2.237f < 5.0f))
        start = 0;
    rate = 0.3f;
    if (start) {
        rate = 0.075f;
        p = aienginesound_compute_start_line_rpm_pitch_shift(s);
    } else {
        float kph;

        p = aienginesound_compute_rpm_pitch_shift(s);
        kph = s->pCar->State.VelocityMagnitude * 3.6f;
        volume *= s->GearVolumeScale;
        if (kph < 75.0f)
            volume *= kph * (1.0f / 75.0f) * 0.5f + 0.5f;  // gp-27556
    }
    if (!bsample_is_playing(&s->EngineSample)) {
        if (SoundEnabled && CarSoundEnabled)
            bsample_play(&s->EngineSample, volume, 0.0f, 0.0f);
    } else {
        bsample_set_volume(&s->EngineSample,
                           smooth(s->EngineSample.currentVolume, volume,
                                  rate));
    }
    bsample_set_pitch(&s->EngineSample,
                      (s->EnginePitchBase + p * pitch) - 1.0f);
    bsample_set_azimuth(&s->EngineSample, azimuth);
}

void aienginesound_mute(AIEngineSound *s, int32_t on)
{
    bsample_pause(&s->EngineSample, on != 0);
}

const char *aienginesound_get_engine_sample_name(AIEngineSound *s)
{
    static char name[10];                       // 0x00334a08
    const Car *c = s->pCar;
    int32_t n = 0;

    if (cartypeinfo_get(c->pRideInfo->Type)->UsageType != 2)
        n = (uint16_t)c->pCarTypeInfo->Sound.AIEngineNumber;
    strcpy(name, "AIEngine0");
    name[8] = (char)(name[8] + n);
    return name;
}

// The mean of the last twenty RPMs, which a gear change refills with the
// new one; the pitch eases towards it, slowly for six frames after the
// change (when the volume dips too) and then at up to 5000 a frame.
float aienginesound_compute_rpm_pitch_shift(AIEngineSound *s)
{
    const Car *c = s->pCar;
    float step = 5000.0f;
    float scale = 1.0f;

    if (c->State.CurrentGear != s->CurrGear) {
        average_flush(&s->RPMAverage, car_rpm(c));
        s->GearFrames = 0;
    }
    s->CurrGear = c->State.CurrentGear;
    average_record(&s->RPMAverage, car_rpm(c));
    if (s->GearFrames < 6) {
        step = (float)GearChangeSteps[s->GearFrames];
        scale = GearChangeVolumes[s->GearFrames];
    }
    s->GearVolumeScale = scale;
    s->SmoothRPM = smooth(s->SmoothRPM, s->RPMAverage.fAverage, step);
    s->GearFrames++;
    return s->SmoothRPM * 0x1.a36e30p-13f;      // gp-27548, just over 0.0002
}

// Idling at 0.3, with a 4% chance a frame of a blip up to 1.0, which then
// falls back, and may blip again on the way down.
float aienginesound_compute_start_line_rpm_pitch_shift(AIEngineSound *s)
{
    int32_t falling;
    float step;

    if (s->StartLineTargetPitch == -1.0f) {
        s->StartLineTargetPitch = 0.3f;
        s->StartLineCurrPitch = 0.3f;
    }
    if (s->StartLineCurrPitch < s->StartLineTargetPitch) {
        step = 0.15f;
        falling = 0;
    } else {
        step = 0.08f;
        falling = 1;
    }
    s->StartLineCurrPitch = smooth(s->StartLineCurrPitch,
                                   s->StartLineTargetPitch, step);
    if (s->StartLineCurrPitch == s->StartLineTargetPitch || falling) {
        if ((s->StartLineCurrPitch == 0.3f || falling)
            && sound_random_float(sound_get(), 100.0f) < 4.0f)
            s->StartLineTargetPitch = 1.0f;
        if (s->StartLineCurrPitch == 1.0f)
            s->StartLineTargetPitch = 0.3f;
    }
    return s->StartLineCurrPitch;
}

void aienginesound_deactivate_sound(AIEngineSound *s)
{
    bsample_stop(&s->EngineSample);
}

void aienginesound_activate_sound(AIEngineSound *s)
{
    if (SoundEnabled && CarSoundEnabled)
        bsample_play(&s->EngineSample, 0.0f, 0.0f, 0.0f);
}

// ---------------------------------------------------------- engine_sound

Sound3d *enginesound_create_player(Car *c)
{
    PlayerEngineSound *s = bMalloc(sizeof(PlayerEngineSound),
                                   "PlayerEngineSound", 0, 16);

    playerenginesound_construct(s, c);
    LastPlayerEngineSound = s;
    return &s->Sound;
}

Sound3d *enginesound_create_ai(Car *c)
{
    AIEngineSound *s = bMalloc(sizeof(AIEngineSound), "AIEngineSound", 0, 16);

    aienginesound_construct(s, c);
    return &s->Sound;
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

static const VtEntry playerenginesound_vt[SOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(playerenginesound_destroy),                       //  8  0x0020fe70
    E(sound3d_activate),                                // 16  0x00208b28
    E(playerenginesound_update),                        // 24  0x00211390
    E(playerenginesound_mute),                          // 32  0x00210410
    E(playerenginesound_deactivate_sound),              // 40  0x00210400
    E(playerenginesound_activate_sound),                // 48  0x00210408
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56  0x00208c78
};

static const VtEntry aienginesound_vt[SOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(aienginesound_destroy),                           //  8  0x00212418
    E(sound3d_activate),                                // 16
    E(aienginesound_update),                            // 24  0x002118a0
    E(aienginesound_mute),                              // 32  0x00211a80
    E(aienginesound_deactivate_sound),                  // 40  0x00211d58
    E(aienginesound_activate_sound),                    // 48  0x00211d60
    E(sound3d_update_cam_relative_dist_and_velocity),   // 56
};

#undef E

void enginesound_install_vtables(void)
{
    vt_install(PLAYERENGINESOUND_VTABLE, playerenginesound_vt,
               SOUND3D_VT_ENTRIES);
    vt_install(AIENGINESOUND_VTABLE, aienginesound_vt, SOUND3D_VT_ENTRIES);
}
