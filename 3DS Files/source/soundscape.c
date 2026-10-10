#include "soundscape.h"

#include <stddef.h>

#include "bchunk.h"
#include "bmath.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "carsound.h"
#include "eefpu.h"
#include "emath.h"
#include "player.h"
#include "race.h"
#include "realtime.h"
#include "sound.h"
#include "sound3d.h"
#include "topology.h"
#include "track.h"

ReverbArea     SoundScapeReverbAreaArray[SOUNDSCAPE_REVERB_AREAS];
LoopingAmbient SoundScapeLoopingAmbientArray[SOUNDSCAPE_LOOPING_AMBIENT];
OneShotAmbient SoundScapeOneShotAmbientArray[SOUNDSCAPE_ONESHOT_AMBIENT];

int32_t  SoundScapeDataJustLoaded;                  // gp-18088
int32_t  SoundScapeNumReverbAreas;                  // gp-18084
int32_t  SoundScapeCurrentlyActiveReverbArea = -1;  // gp-18080
int32_t  SoundScapeReverbOn;                        // gp-18076
BSample *SoundScapeRain;                            // gp-18072
float    SoundScapeReverbVolume;                    // gp-18068
float    SoundScapeTargetReverbVolume;              // gp-18064
float    SoundScapeReverbPan;                       // gp-18060
int32_t  SoundScapeNumLoopingAmbient;               // gp-17996
int32_t  SoundScapeNumOneShotAmbient;               // gp-18000

int32_t  ReverbMode = 2;                            // gp-18056
int32_t  DesiredReverbMode = 2;                     // gp-18052
float    ReverbDelay = 0.65f;                       // gp-18048
float    DesiredReverbDelay = 0.65f;                // gp-18044
float    ReverbFeedback = 1.0f;                     // gp-18040
float    DesiredReverbFeedback = 1.0f;              // gp-18036
float    ReverbLevel = 0.85f;                       // gp-18032
float    DesiredReverbLevel = 0.85f;                // gp-18028
float    ReverbDepth = 0.75f;                       // gp-18024
float    DesiredReverbDepth = 0.75f;                // gp-18020

const uint32_t ReverbModeTable[13] = {
    0, 1, 2, 3, 4, 5, 6, 7, 0x65, 0x66, 0x67, 0x68, 0x69
};

void (*gSoundScapeEffectVolumeFn)(uint32_t voices, uint32_t on,
                                  float volume, float pan);
void (*gSoundScapeEffectModeFn)(uint32_t mode);
void (*gSoundScapeEffectParameterFn)(uint32_t which, uint32_t core,
                                     float value);

// AreCamerasInArea's and UpdateUsingSoundSphere's, gp-13384 and gp-13376.
static struct Camera *CameraInsideArea[2];
static struct Camera *CameraInsideSphere[2];

#define AMBIENT_VOLUME 0.84f        // gp-28504, -28500, -28496

// ---------------------------------------------------------------- helpers

// `max.s`, fs then ft, as collision.c has it.
static float max_s(float fs, float ft)
{
    return fs < ft ? ft : fs;
}

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

// The ground-plane distance from the source to the camera, the camera's
// side first.
static float sphere_distance(const LoopingAmbient *l,
                             const struct Camera *cam)
{
    float dx = cam->CurrentKey.Position.x - l->SoundSource.x;
    float dy = cam->CurrentKey.Position.y - l->SoundSource.y;

    return ee_sqrt(dx * dx + dy * dy);
}

// bSound::Region of the track's SoundRegion. CurrentTrackInfo is read
// without a test in retail; the port's gives no region without one.
static BRegion *track_region(void)
{
    if (CurrentTrackInfo == NULL)
        return NULL;
    return bsound_region(bsound_get(), CurrentTrackInfo->SoundRegion);
}

// bDriver::PlatSetEffectVolume on bSound's driver, voices 0xffffffff, on.
static void set_effect_volume(float volume, float pan)
{
    if (gSoundScapeEffectVolumeFn != NULL)
        gSoundScapeEffectVolumeFn(0xffffffffu, 1, volume, pan);
}

static void set_effect_parameter(uint32_t which, float value)
{
    if (gSoundScapeEffectParameterFn != NULL)
        gSoundScapeEffectParameterFn(which, 0, value);
}

// --------------------------------------------------------------- SoundArea

const uint8_t *soundarea_initialize(SoundArea *a, const uint8_t *p)
{
    a->NumAreaVerts = (int32_t)bchunk_u32(p);
    a->AreaVerts = (const bVector2 *)(p + 4);
    p += 4 + 8 * a->NumAreaVerts;
    a->NumAreaFaces = (int32_t)bchunk_u32(p);
    a->AreaFaces = (const int32_t *)(p + 4);
    return p + 4 + 12 * a->NumAreaFaces;
}

int32_t soundarea_is_point_in_area(const SoundArea *a, const bVector2 *pt)
{
    int32_t i;

    for (i = 0; i < a->NumAreaFaces; i++) {
        const int32_t *f = a->AreaFaces + 3 * i;
        bVector2 poly[3];

        poly[0] = a->AreaVerts[f[0]];
        poly[1] = a->AreaVerts[f[1]];
        poly[2] = a->AreaVerts[f[2]];
        if (eIsPointInPoly(pt, poly, 3))
            return 1;
    }
    return 0;
}

struct Camera **soundarea_are_cameras_in_area(const SoundArea *a,
                                              struct Camera **cams,
                                              int32_t *count)
{
    int32_t i;

    *count = 0;
    for (i = 0; i < 2; i++) {
        struct Camera *cam = cams[i];
        bVector2 pos;

        if (cam == NULL)
            continue;
        pos.x = cam->CurrentKey.Position.x;
        pos.y = cam->CurrentKey.Position.y;
        if (soundarea_is_point_in_area(a, &pos))
            CameraInsideArea[(*count)++] = cam;
    }
    return CameraInsideArea;
}

// -------------------------------------------------------------- ReverbArea

void reverbarea_initialize(ReverbArea *r, const uint8_t *c)
{
    const uint8_t *p;
    int32_t i;

    r->Name = (const char *)(c + 8);
    r->Reverb = (int32_t)bchunk_u32(c + 40);
    p = soundarea_initialize(&r->Area, c + 44);
    r->NumSounds = (int32_t)bchunk_u32(p);
    p += 4;
    // No test against the eight in retail; the retail tracks have at most
    // one.
    for (i = 0; i < r->NumSounds; i++) {
        r->Sounds[i].SampleName = (const char *)p;
        r->Sounds[i].Period = bchunk_f32(p + 32);
        r->Sounds[i].PeriodError = bchunk_f32(p + 36);
        p += 40;
    }
}

// ---------------------------------------------------------- LoopingAmbient

void loopingambient_initialize(LoopingAmbient *l, const uint8_t *c)
{
    l->SoundSource.x = bchunk_f32(c + 84);
    l->FadeOutDuration = ee_trunc_w(bchunk_f32(c + 76) * 1000.0f);
    l->FadeInDuration = ee_trunc_w(bchunk_f32(c + 72) * 1000.0f);
    l->SoundSource.y = bchunk_f32(c + 88);
    l->HasSoundSource = bchunk_u32(c + 80) != 0;
    l->IsActive = 0;
    l->Sample = NULL;
    l->Name = (const char *)(c + 8);
    l->SampleName = (const char *)(c + 40);
    l->SoundSourceDistanceCoeff = bchunk_f32(c + 92);
    soundarea_initialize(&l->Area, c + 96);
    l->UseSoundSphere = 0;
    l->SoundSphereRadius = 0.0f;
    if (l->HasSoundSource
        && soundarea_is_point_in_area(&l->Area, &l->SoundSource)) {
        int32_t i;

        l->UseSoundSphere = 1;
        for (i = 0; i < l->Area.NumAreaVerts; i++) {
            const bVector2 *v = &l->Area.AreaVerts[i];
            float dy = l->SoundSource.y - v->y;
            float dx = l->SoundSource.x - v->x;
            float d = ee_sqrt(dx * dx + dy * dy);

            l->SoundSphereRadius = max_s(l->SoundSphereRadius, d);
        }
    }
}

uint16_t loopingambient_compute_azimuth(const LoopingAmbient *l,
                                        const struct Camera *cam)
{
    float dy = l->SoundSource.y - cam->CurrentKey.Position.y;
    float dx = l->SoundSource.x - cam->CurrentKey.Position.x;
    float len = ee_sqrt(dx * dx + dy * dy);
    float hx = cam->CurrentKey.Direction.x;
    float hy = cam->CurrentKey.Direction.y;
    uint32_t r;

    dx = ee_div(dx, len);
    dy = ee_div(dy, len);
    r = (uint32_t)(16384 - bASin(dx * hx + dy * hy));
    // Left of the heading: the other way round.
    if (-dy * hx + dx * hy < 0.0f)
        r = 0u - (r & 0xffffu);
    return (uint16_t)r;
}

void loopingambient_update_using_area(LoopingAmbient *l,
                                      struct Camera **cams)
{
    int32_t count;
    struct Camera **in = soundarea_are_cameras_in_area(&l->Area, cams,
                                                       &count);

    if (l->IsActive) {
        if (count > 0) {
            int32_t sum = 0;
            int32_t i;

            if (!l->HasSoundSource)
                return;
            for (i = 0; i < count; i++)
                sum += loopingambient_compute_azimuth(l, in[i]);
            if (l->Sample != NULL)
                bsample_set_azimuth(l->Sample, (uint16_t)(sum / count));
        } else {
            if (l->FadeOutDuration == 0)
                bsample_stop(l->Sample);
            else
                bsample_fade(l->Sample, 0.0f,
                             (uint32_t)l->FadeOutDuration);
            l->IsActive = 0;
        }
    } else if (count > 0) {
        if (l->FadeInDuration == 0) {
            if (SoundEnabled)
                bsample_play(l->Sample, AMBIENT_VOLUME, 0.0f, 0.0f);
        } else if (SoundEnabled) {
            bsample_play(l->Sample, 0.0f, 0.0f, 0.0f);
            bsample_fade(l->Sample, AMBIENT_VOLUME,
                         (uint32_t)l->FadeInDuration);
        }
        l->IsActive = 1;
    } else if (bsample_is_playing(l->Sample)
               && bsample_get_volume(l->Sample) == 0.0f) {
        bsample_stop(l->Sample);
    }
}

void loopingambient_update_using_sound_sphere(LoopingAmbient *l,
                                              struct Camera **cams)
{
    int32_t n = 0;
    int32_t i;

    for (i = 0; i < 2; i++) {
        struct Camera *cam = cams[i];

        if (cam != NULL
            && sphere_distance(l, cam) < l->SoundSphereRadius)
            CameraInsideSphere[n++] = cam;
    }
    if (n > 0) {
        float dist = 0.0f;
        int32_t sum = 0;
        float nf, r, coeff, volume;
        uint16_t az;

        for (i = 0; i < n; i++) {
            sum += loopingambient_compute_azimuth(l, CameraInsideSphere[i]);
            dist += sphere_distance(l, CameraInsideSphere[i]);
        }
        nf = (float)n;
        az = (uint16_t)(sum / n);
        r = l->SoundSphereRadius;
        dist = ee_div(dist, nf);
        // A Sound3dEnvelope of 2 out to the radius, inline.
        coeff = ee_div(1.0f, r);
        if (r < dist) {
            volume = 0.0f;
        } else {
            float dc = dist * coeff;

            volume = 1.0f - ee_sqrt((dist + dist) * coeff - dc * dc);
            volume = volume + volume;
        }
        if (bsample_is_playing(l->Sample))
            bsample_set_volume(l->Sample, volume);
        else if (SoundEnabled)
            bsample_play(l->Sample, volume, 0.0f, 0.0f);
        bsample_set_azimuth(l->Sample, az);
    } else if (bsample_is_playing(l->Sample)) {
        bsample_stop(l->Sample);
    }
}

void loopingambient_update(LoopingAmbient *l, struct Camera **cams)
{
    if (l->Sample == NULL) {
        BRegion *r = track_region();

        if (r != NULL) {
            BSample *s = bregion_sample(r, l->SampleName);

            if (s != NULL) {
                l->Sample = bsample_new(0);
                bsample_initialize_copy(l->Sample, s);
                if (l->Sample != NULL)
                    bsample_set_category(l->Sample, 0);
            }
        }
        if (l->Sample == NULL)
            return;
    }
    if (l->UseSoundSphere)
        loopingambient_update_using_sound_sphere(l, cams);
    else
        loopingambient_update_using_area(l, cams);
}

void loopingambient_mute(LoopingAmbient *l, int32_t on)
{
    if (l->Sample != NULL)
        bsample_pause(l->Sample, on);
}

// ---------------------------------------------------------- OneShotAmbient

void oneshotambient_initialize(OneShotAmbient *o, const uint8_t *c)
{
    o->UpdateOneShotTime = 0.0f;
    o->Name = (const char *)(c + 8);
    o->SampleName = (const char *)(c + 40);
    o->Repeat = bchunk_f32(c + 72);
    o->IsActive = 0;
    o->RepeatDeviation = bchunk_f32(c + 76);
    o->Sample = NULL;
    o->Pitch = bchunk_f32(c + 80);
    o->PitchDeviation = bchunk_f32(c + 84);
    o->AzimuthDeviation = bchunk_f32(c + 88);
    soundarea_initialize(&o->Area, c + 92);
}

void oneshotambient_play(OneShotAmbient *o)
{
    float pitch;
    uint16_t az = 0;

    if (o->Sample == NULL)
        return;
    pitch = o->Pitch;
    if (o->PitchDeviation != 0.0f) {
        float r = sound_random_float(sound_get(), o->PitchDeviation);

        pitch = (pitch - o->PitchDeviation * 0.5f) + r;
    }
    if (o->AzimuthDeviation == 360.0f)
        az = 16384;
    else if (o->AzimuthDeviation != 0.0f)
        az = (uint16_t)sound_random_int(sound_get(), 0x10000);
    if (SoundEnabled) {
        bsample_play(o->Sample, AMBIENT_VOLUME, 0.0f, 0.0f);
        bsample_set_azimuth(o->Sample, az);
        bsample_set_pitch(o->Sample, pitch);
        if (o->AzimuthDeviation == 360.0f) {
            bsample_play(&o->Sample360Azimuth, AMBIENT_VOLUME, 0.0f, 0.0f);
            bsample_set_azimuth(&o->Sample360Azimuth, 0xc000);
            bsample_set_pitch(&o->Sample360Azimuth, pitch);
        }
    }
    if (0.0f < o->Repeat) {
        float t = o->Repeat;

        if (o->RepeatDeviation != 0.0f) {
            float r = sound_random_float(sound_get(), o->RepeatDeviation);

            t = (t - o->RepeatDeviation * 0.5f) + r;
        }
        o->UpdateOneShotTime = t;
    }
}

void oneshotambient_update(OneShotAmbient *o, struct Camera **cams)
{
    int32_t count;

    if (o->Sample == NULL) {
        BRegion *r = track_region();

        if (r == NULL)
            return;
        o->Sample = bregion_sample(r, o->SampleName);
        if (o->Sample == NULL)
            return;
        bsample_set_category(o->Sample, 0);
        if (o->AzimuthDeviation == 360.0f) {
            bsample_initialize_copy(&o->Sample360Azimuth, o->Sample);
            bsample_set_category(&o->Sample360Azimuth, 0);
        }
    }
    soundarea_are_cameras_in_area(&o->Area, cams, &count);
    if (o->IsActive) {
        if (count <= 0) {
            o->IsActive = 0;
        } else if (0.0f < o->Repeat) {
            o->UpdateOneShotTime -= WorldTimeElapsed;
            if (o->UpdateOneShotTime < 0.0f)
                oneshotambient_play(o);
        }
    } else if (count > 0) {
        oneshotambient_play(o);
        o->IsActive = 1;
    }
}

void oneshotambient_mute(OneShotAmbient *o, int32_t on)
{
    if (o->Sample != NULL)
        bsample_pause(o->Sample, on);
}

void soundscape_init(void)
{
    int32_t i;

    for (i = 0; i < SOUNDSCAPE_ONESHOT_AMBIENT; i++)
        bsample_construct(&SoundScapeOneShotAmbientArray[i].Sample360Azimuth,
                          0);
}

// -------------------------------------------------------------- SoundScape

int32_t soundscape_will_sound_right(int32_t i, struct Car *car)
{
    bVector2 pos;

    if (i >= SoundScapeNumReverbAreas)
        return 0;
    pos.x = car->State.Position.x;
    pos.y = car->State.Position.y;
    return soundarea_is_point_in_area(&SoundScapeReverbAreaArray[i].Area,
                                      &pos);
}

int32_t soundscape_find_good_reverb_area(struct Car *car)
{
    int32_t i;

    for (i = 0; i < SoundScapeNumReverbAreas; i++)
        if (soundscape_will_sound_right(i, car))
            return i;
    return -1;
}

void soundscape_set_reverb_volume(float v, struct Car *car)
{
    if (TheRaceParameters.NumPlayerCars < 2) {
        SoundScapeTargetReverbVolume = v;
        return;
    }
    if (car != NULL && car->pBaseCarSound != NULL)
        basecarsound_scale_road_noise(car->pBaseCarSound, v + 1.0f);
}

int32_t soundscape_is_inside_reverb_area(struct Car **cars)
{
    int32_t search = 0;
    int32_t second = 0;

    if (SoundScapeCurrentlyActiveReverbArea == -1
        || SoundScapeDataJustLoaded) {
        search = 1;
        SoundScapeDataJustLoaded = 0;
    } else if (!soundscape_will_sound_right(
                   SoundScapeCurrentlyActiveReverbArea, cars[0])) {
        search = 1;
    } else if (cars[1] != NULL
               && !soundscape_will_sound_right(
                      SoundScapeCurrentlyActiveReverbArea, cars[1])) {
        search = 1;
        second = 1;
    }
    if (search) {
        int32_t i = soundscape_find_good_reverb_area(cars[0]);

        if (i == -1 && cars[1] != NULL) {
            second = 1;
            i = soundscape_find_good_reverb_area(cars[1]);
        }
        SoundScapeCurrentlyActiveReverbArea = i;
    }
    return second;
}

void soundscape_update_reverb_areas(void)
{
    struct Car *cars[2];
    int32_t any = 0;
    int32_t i;
    float rate = 0.05f;                                 // gp-28492
    float v;

    if (SoundScapeReverbVolume < SoundScapeTargetReverbVolume)
        rate = 0.333f;                                  // gp-28488
    v = smooth(SoundScapeReverbVolume, SoundScapeTargetReverbVolume, rate);
    if (v != SoundScapeReverbVolume) {
        SoundScapeReverbVolume = v;
        set_effect_volume(SoundScapeReverbVolume, SoundScapeReverbPan);
    }

    if (DesiredReverbMode != ReverbMode) {
        soundscape_set_reverb_volume(0.0f, NULL);
        ReverbMode = DesiredReverbMode;
        if (gSoundScapeEffectModeFn != NULL)
            gSoundScapeEffectModeFn(ReverbModeTable[ReverbMode]);
        SoundScapeReverbOn = 0;
    }
    if (DesiredReverbDelay != ReverbDelay) {
        ReverbDelay = DesiredReverbDelay;
        set_effect_parameter(1, DesiredReverbDelay);
    }
    if (DesiredReverbFeedback != ReverbFeedback) {
        ReverbFeedback = DesiredReverbFeedback;
        set_effect_parameter(2, DesiredReverbFeedback);
    }
    if (DesiredReverbLevel != ReverbLevel) {
        ReverbLevel = DesiredReverbLevel;
        set_effect_parameter(3, DesiredReverbLevel);
    }
    if (DesiredReverbDepth != ReverbDepth) {
        ReverbDepth = DesiredReverbDepth;
        set_effect_parameter(4, DesiredReverbDepth);
    }

    for (i = 0; i < 2; i++) {
        struct Player *p = PlayerPlayersByIndex[i];

        cars[i] = p != NULL ? p->MyCar : NULL;
        if (p != NULL)
            any = 1;
    }
    if (!any)
        return;

    i = soundscape_is_inside_reverb_area(cars);
    if (SoundScapeCurrentlyActiveReverbArea == -1) {
        if (SoundScapeReverbOn) {
            int32_t k;

            for (k = 0; k < 2; k++)
                if (cars[k] != NULL)
                    soundscape_set_reverb_volume(0.0f, cars[k]);
            SoundScapeReverbOn = 0;
        }
    } else {
        struct Car *car = cars[i];
        bVector3 pos = car->State.Position;
        float here, top, under;
        int32_t below, onUnder;

        here = topology_get_elevation(&car->TheTopologyCoordinate, &pos,
                                      NULL, NULL, NULL);
        pos.z = 99999.0f;                               // gp-28484
        top = topology_get_elevation(&car->TheTopologyCoordinate, &pos,
                                     NULL, NULL, NULL);
        pos.z = top - 2.0f;
        under = topology_get_elevation(&car->TheTopologyCoordinate, &pos,
                                       NULL, NULL, NULL);
        // Road over the car: the highest surface above it, or one just
        // under that still at or over it.
        below = here < top;
        onUnder = here <= under;
        if (!SoundScapeReverbOn) {
            if (below || onUnder) {
                SoundScapeReverbPan = 0.0f;
                soundscape_set_reverb_volume(0.85f, car);   // gp-28480
                SoundScapeReverbOn = 1;
            }
        } else if (!below && !onUnder) {
            soundscape_set_reverb_volume(0.0f, car);
            SoundScapeReverbOn = 0;
        }
    }
}

void soundscape_update_looping_ambient(void)
{
    int32_t i;

    for (i = 0; i < SoundScapeNumLoopingAmbient; i++)
        loopingambient_update(&SoundScapeLoopingAmbientArray[i],
                              get_active_cameras());
}

void soundscape_update_one_shot_ambient(void)
{
    int32_t i;

    for (i = 0; i < SoundScapeNumOneShotAmbient; i++)
        oneshotambient_update(&SoundScapeOneShotAmbientArray[i],
                              get_active_cameras());
}

void soundscape_update(void)
{
    if (pRaceCoordinator == NULL)
        return;
    soundscape_update_reverb_areas();
    soundscape_update_looping_ambient();
    soundscape_update_one_shot_ambient();
}

void soundscape_mute(int32_t on)
{
    int32_t i;

    for (i = 0; i < SoundScapeNumLoopingAmbient; i++)
        loopingambient_mute(&SoundScapeLoopingAmbientArray[i], on);
    for (i = 0; i < SoundScapeNumOneShotAmbient; i++)
        oneshotambient_mute(&SoundScapeOneShotAmbientArray[i], on);
    if (SoundScapeRain != NULL && bsample_is_playing(SoundScapeRain))
        bsample_mute(SoundScapeRain, on);
    if (on) {
        set_effect_volume(0.0f, 0.0f);
        SoundScapeReverbOn = 0;
        SoundScapeCurrentlyActiveReverbArea = -1;
    }
}

void sound_scape_update(void)
{
    soundscape_update();
}

void sound_scape_mute(int32_t on)
{
    soundscape_mute(on);
}

int32_t soundscape_is_inside_tunnel(void)
{
    return SoundScapeCurrentlyActiveReverbArea != -1;
}

// -------------------------------------------------------------- the chunk

int loader_sound_scape(uint8_t *chunk)
{
    const uint8_t *c, *end;

    if (bchunk_u32(chunk) != SOUNDSCAPE_CHUNK)
        return 0;
    SoundScapeDataJustLoaded = 1;
    SoundScapeCurrentlyActiveReverbArea = -1;
    SoundScapeNumReverbAreas = 0;
    SoundScapeNumLoopingAmbient = 0;
    SoundScapeNumOneShotAmbient = 0;
    end = chunk + 8 + bchunk_u32(chunk + 4);
    // Retail tests none of the three counts; the retail tracks have at
    // most 18, 19 and 43. The port's drops a record past the end.
    for (c = chunk + 8; c < end; c += 8 + bchunk_u32(c + 4)) {
        switch (bchunk_u32(c)) {
        case SOUNDSCAPE_CHUNK_REVERB:
            if (SoundScapeNumReverbAreas < SOUNDSCAPE_REVERB_AREAS)
                reverbarea_initialize(
                    &SoundScapeReverbAreaArray[SoundScapeNumReverbAreas++], c);
            break;
        case SOUNDSCAPE_CHUNK_LOOPING:
            if (SoundScapeNumLoopingAmbient < SOUNDSCAPE_LOOPING_AMBIENT)
                loopingambient_initialize(
                    &SoundScapeLoopingAmbientArray
                        [SoundScapeNumLoopingAmbient++], c);
            break;
        case SOUNDSCAPE_CHUNK_ONESHOT:
            if (SoundScapeNumOneShotAmbient < SOUNDSCAPE_ONESHOT_AMBIENT)
                oneshotambient_initialize(
                    &SoundScapeOneShotAmbientArray
                        [SoundScapeNumOneShotAmbient++], c);
            break;
        default:
            break;
        }
    }
    return 1;
}

int unloader_sound_scape(uint8_t *chunk)
{
    int32_t i;

    if (bchunk_u32(chunk) != SOUNDSCAPE_CHUNK)
        return 0;
    SoundScapeCurrentlyActiveReverbArea = -1;
    SoundScapeNumReverbAreas = 0;
    SoundScapeNumOneShotAmbient = 0;
    SoundScapeRain = NULL;
    // The samples are deleted and the pointers left; the next load starts
    // each record over.
    for (i = 0; i < SoundScapeNumLoopingAmbient; i++) {
        LoopingAmbient *l = &SoundScapeLoopingAmbientArray[i];

        if (l->Sample == NULL)
            continue;
        bsample_stop(l->Sample);
        bsample_delete(l->Sample);
    }
    SoundScapeNumLoopingAmbient = 0;
    return 1;
}
