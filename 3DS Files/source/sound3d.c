#include "sound3d.h"

#include <math.h>

#include "bmath.h"
#include "bmem.h"
#include "camera.h"
#include "eefpu.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "sound.h"
#include "vtable.h"

// SoundEnabled (gp-23056), carinit.c's.
extern int32_t SoundEnabled;

uint16_t CarSoundMultiPlayerAzimuth;            // gp-20464
float    SpeedOfSound = 350.0f;                 // gp-16480
BSlotPool *Sound3dSampleSlotPool;               // gp-16448
// _GLOBAL_$I$ (0x00209da8): empty, its own sentinel.
bNode Sound3dOneshotList = { &Sound3dOneshotList, &Sound3dOneshotList };

static struct Camera *ActiveCameras[2];         // gp-13368

typedef void (*VtDestroyFn)(void *self, int32_t flags);
typedef void (*VtActivateFn)(void *self, int32_t on);
typedef void (*VtUpdateFn)(void *self, float volume, uint16_t azimuth,
                           float pitch);
typedef void (*VtMuteFn)(void *self, int32_t on);
typedef void (*VtVoidFn)(void *self);
typedef void (*VtCamRelativeFn)(void *self, const bVector3 *pos);
typedef void (*VtUpdateAtFn)(void *self, const bVector3 *pos, float volume,
                             uint16_t azimuth, float pitch);

// ------------------------------------------------------------- SoundScape

struct Camera **get_active_cameras(void)
{
    int i;

    for (i = 0; i < 2; i++)
        ActiveCameras[i] = PlayerPlayersByIndex[i] != NULL
                           ? eGetView(i + 1)->pCamera : NULL;
    return ActiveCameras;
}

// ---------------------------------------------------------------- Sound3d

void sound3d_construct(Sound3d *s)
{
    s->_vtable = SOUND3D_VTABLE;
    s->DopplerIsActive = 1;
    s->Pitch = 1.0f;
    s->Activated = 0;
    s->Volume = 1.0f;
    s->Azimuth = 0;
    s->SndToCameraVelocity = 0.0f;
    s->SndToCameraDistance = 0.0f;
}

void sound3d_destroy(Sound3d *s, int32_t flags)
{
    s->_vtable = SOUND3D_VTABLE;
    if (flags & 1)
        bFree(s);                               // __builtin_delete
}

void sound3d_activate(Sound3d *s, int32_t on)
{
    const VtEntry *e;

    if (!on) {
        e = vt_slot(s->_vtable, SOUND3D_VT_DEACTIVATE);
        ((VtVoidFn)e->fn)(vt_this(s, e));
    } else if (!s->Activated) {
        e = vt_slot(s->_vtable, SOUND3D_VT_ACTIVATESOUND);
        ((VtVoidFn)e->fn)(vt_this(s, e));
    }
    s->Activated = on;
}

// vsub.xyzw, vmul.xyz, vaddy.x and vaddz.x: (x*x + y*y) + z*z.
static float dist_sq(const bVector3 *a, const bVector3 *b)
{
    float x = a->x - b->x, y = a->y - b->y, z = a->z - b->z;

    return (x * x + y * y) + z * z;
}

float sound3d_get_dist_to_closest_camera(const bVector3 *pos)
{
    struct Camera **cams = get_active_cameras();
    float best = 9e9f;                          // gp-27656, 0x50061c46
    int i;

    for (i = 0; i < 2; i++) {
        if (cams[i] != NULL) {
            float d = sqrtf(dist_sq(pos, &cams[i]->CurrentKey.Position));

            best = best < d ? best : d;         // min(best, d), min.s's order
        }
    }
    if (best == 9e9f)
        best = sqrtf(dist_sq(pos,
                             &eGetView(1)->pCamera->CurrentKey.Position));
    return best;
}

void sound3d_update_cam_relative_dist_and_velocity(Sound3d *s,
                                                   const bVector3 *pos)
{
    float d = sound3d_get_dist_to_closest_camera(pos);
    // A frame with no world time is a divide by zero, which the clamp
    // throws out on the console and here alike.
    float v = ee_div(d - s->SndToCameraDistance, WorldTimeElapsed);

    if (v < 80.0f && -80.0f < v)
        s->SndToCameraVelocity = v;
    s->SndToCameraDistance = d;
}

void sound3d_update(Sound3d *s, const bVector3 *pos,
                    const Sound3dEnvelope *env)
{
    const VtEntry *e = vt_slot(s->_vtable, SOUND3D_VT_CAMRELATIVE);

    ((VtCamRelativeFn)e->fn)(vt_this(s, e), pos);
    if (s->DopplerIsActive)
        s->Pitch = 1.0f - s->SndToCameraVelocity / SpeedOfSound;
    if (env != NULL) {
        // Sound3dEnvelope::GetVolAtDistance, inline.
        float d = s->SndToCameraDistance;
        float vol;

        if (env->CutOffDistance < d) {
            vol = 0.0f;
        } else {
            float r = d * env->Coeff;

            vol = env->MaxVolAtSource
                  * (1.0f - ee_sqrt((d + d) * env->Coeff - r * r));
        }
        s->Volume = 1.0f < vol ? 1.0f : vol;
    } else {
        s->Volume = 1.0f;
    }
    s->Azimuth = sound3d_compute_azimuth(pos);
}

uint16_t sound3d_compute_azimuth(const bVector3 *pos)
{
    const Camera *cam;
    float x, y, len, dirX, dirY;
    uint16_t az;

    if (PlayerNumPlayers >= 2) {
        struct Camera **cams = get_active_cameras();
        int32_t n = PlayerNumPlayers;
        float best = 9e9f;                      // gp-27648
        int32_t i, closest = -1;

        // Neither camera is tested for NULL: two players have two.
        for (i = 0; i < n; i++) {
            const bVector3 *c = &cams[i]->CurrentKey.Position;
            float cx = c->x - pos->x, cy = c->y - pos->y;
            float dsq = cx * cx + cy * cy;

            if (dsq < best) {
                best = dsq;
                closest = i;
            }
        }
        if (closest != 0)
            return CarSoundMultiPlayerAzimuth;
        return (uint16_t)-CarSoundMultiPlayerAzimuth;
    }
    cam = eGetView(1)->pCamera;
    y = pos->y - cam->CurrentKey.Position.y;
    x = pos->x - cam->CurrentKey.Position.x;
    len = sqrtf(x * x + y * y);
    // A sound right over the camera is 0/0, which the console makes FLT_MAX.
    x = ee_div(x, len);
    y = ee_div(y, len);
    dirY = cam->CurrentKey.Direction.y;
    dirX = cam->CurrentKey.Direction.x;
    az = (uint16_t)(16384 - bASin(x * dirX + y * dirY));
    // Behind or ahead from the asin; which side from the cross product. The
    // image tests a 360 for zero here, for a modulo it never takes.
    if (-y * dirX + x * dirY < 0.0f)
        az = (uint16_t)-az;
    return az;
}

float sound3d_compute_volume(const bVector3 *pos, float cutOff)
{
    float d = sound3d_get_dist_to_closest_camera(pos);
    // A unit envelope out to cutOff, built on the stack: the coefficient
    // is worked out before the cut-off is tested, so a cut-off of 0 is the
    // console's FLT_MAX. Within the cut-off d * c is at most about 1, so
    // the product cannot overflow and the root's operand is not negative.
    float c = ee_div(1.0f, cutOff);
    float r;

    if (cutOff < d)
        return 0.0f;
    r = d * c;
    return 1.0f - sqrtf((d + d) * c - r * r);
}

float sound3d_azimuth_to_pan(uint16_t azimuth)
{
    uint32_t a = azimuth;
    float f = (float)(int32_t)(a % 16383u) * 6.10351562e-05f;   // 2^-14
    float pan;

    if (a < 16383u)
        pan = f;
    else if (a - 16383u < 16385u)
        pan = 1.0f - f;
    else if (((a - 32768u) & 0xffffu) < 16385u)
        pan = -f;
    else
        pan = f - 1.0f;
    return pan * 0.5f;
}

uint16_t sound3d_pan_to_azimuth(float pan)
{
    if (pan < 0.0f) {
        float t = pan + 0.5f;

        return (uint16_t)ee_trunc_w((t + t) * 16383.0f + 49152.0f);
    }
    if (0.0f < pan)
        return (uint16_t)ee_trunc_w((pan + pan) * 16383.0f);
    return 0;
}

float sound3d_get_azimuth(const Sound3d *s)
{
    return (float)(int32_t)s->Azimuth;
}

// ---------------------------------------------------------- Sound3dSample

// At the head of the one-shots' list, as both constructors put it.
static void link_first(Sound3dSample *s)
{
    bNode *first = Sound3dOneshotList.next;

    Sound3dOneshotList.next = &s->Node;
    first->prev = &s->Node;
    s->Node.prev = &Sound3dOneshotList;
    s->Node.next = first;
}

void sound3d_sample_construct(Sound3dSample *s)
{
    sound3d_construct(&s->Sound);
    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;
    bsample_construct(&s->Sample, 0);
    link_first(s);
    s->Envelope.MaxVolAtSource = 1.0f;
    s->Envelope.CutOffDistance = 200.0f;
    s->Envelope.Coeff = 0.005f;                 // gp-27636
    s->PositionIsDefined = 0;
}

void sound3d_sample_construct_at(Sound3dSample *s, const bVector3 *pos,
                                 float maxVol)
{
    sound3d_construct(&s->Sound);
    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;
    bsample_construct(&s->Sample, 0);
    s->Envelope.MaxVolAtSource = maxVol;
    s->Envelope.CutOffDistance = 135.0f;
    s->Envelope.Coeff = 1.0f / 135.0f;          // gp-27632
    s->Position = *pos;
    link_first(s);
    s->PositionIsDefined = 1;
}

void sound3d_sample_destroy(Sound3dSample *s, int32_t flags)
{
    s->Sound._vtable = SOUND3DSAMPLE_VTABLE;
    bsample_stop(&s->Sample);
    s->Node.prev->next = s->Node.next;
    s->Node.next->prev = s->Node.prev;
    bsample_destruct(&s->Sample);
    sound3d_destroy(&s->Sound, 0);
    if (flags & 1)
        sound3d_sample_free(s);
}

Sound3dSample *sound3d_sample_new(void)
{
    return (Sound3dSample *)bSlotOMalloc(Sound3dSampleSlotPool);
}

void sound3d_sample_free(Sound3dSample *s)
{
    bSlotFree(Sound3dSampleSlotPool, s);
}

// Through Sound3d's slot 8, as `delete` on a Sound3d * is.
static void delete_sample(Sound3dSample *s)
{
    const VtEntry *e = vt_slot(s->Sound._vtable, SOUND3D_VT_DESTROY);

    ((VtDestroyFn)e->fn)(vt_this(&s->Sound, e), 3);
}

void sound3d_sample_update_at(Sound3dSample *s, const bVector3 *pos,
                              float volume, uint16_t azimuth, float pitch)
{
    const VtEntry *e;

    if (!SoundEnabled || !s->Sound.Activated)
        return;
    s->Position = *pos;
    s->PositionIsDefined = 1;
    e = vt_slot(s->Sound._vtable, SOUND3D_VT_UPDATE);
    ((VtUpdateFn)e->fn)(vt_this(&s->Sound, e), volume, azimuth, pitch);
}

void sound3d_sample_update(Sound3dSample *s, float volume, uint16_t azimuth,
                           float pitch)
{
    (void)azimuth;
    if (SoundEnabled && s->Sound.Activated) {
        sound3d_update(&s->Sound, &s->Position, &s->Envelope);
        sound3d_sample_set_volume(s, s->Sound.Volume * volume);
        sound3d_sample_set_pitch(s, s->Sound.Pitch * pitch);
        bsample_set_azimuth(&s->Sample, s->Sound.Azimuth);
    }
    if (volume == 0.0f)
        bsample_stop(&s->Sample);
}

void sound3d_remove_sample(uint32_t event, void *sample, void *data)
{
    (void)sample;
    if (event == BSOUND_SAMPLE_STOPPED && data != NULL)
        delete_sample((Sound3dSample *)data);
}

void sound3d_sample_set_delete_when_done(Sound3dSample *s, int32_t on)
{
    if (on) {
        s->Sample.callbackData = s;
        s->Sample.callback = sound3d_remove_sample;
    } else {
        s->Sample.callbackData = NULL;
        s->Sample.callback = NULL;
    }
}

void sound3d_sample_activate_sound(Sound3dSample *s)
{
    if (SoundEnabled && !bsample_is_playing(&s->Sample))
        bsample_play(&s->Sample, 0.0f, 0.0f, 0.0f);
}

void sound3d_sample_deactivate_sound(Sound3dSample *s)
{
    bsample_stop(&s->Sample);
}

void sound3d_sample_set_position(Sound3dSample *s, const bVector3 *pos)
{
    s->Position = *pos;
}

void sound3d_sample_set_azimuth(Sound3dSample *s, uint16_t azimuth)
{
    s->Sound.Azimuth = azimuth;
    bsample_set_azimuth(&s->Sample, azimuth);
}

void sound3d_sample_set_volume(Sound3dSample *s, float volume)
{
    s->Sound.Volume = volume;
    bsample_set_volume(&s->Sample, volume);
}

void sound3d_sample_set_pitch(Sound3dSample *s, float pitch)
{
    s->Sound.Pitch = pitch;
    bsample_set_pitch(&s->Sample, pitch - 1.0f);
}

void sound3d_sample_mute(Sound3dSample *s, int32_t on)
{
    bsample_pause(&s->Sample, on != 0);
}

// -------------------------------------------------------- sound3d_oneshot

void sound3d_oneshot_init(void)
{
    if (Sound3dSampleSlotPool == NULL)
        Sound3dSampleSlotPool = bNewSlotPool((int)sizeof(Sound3dSample), 30,
                                             "Sound3dSampleSlotPool", 16);
}

void sound3d_oneshot_reset(void)
{
    while (Sound3dOneshotList.next != &Sound3dOneshotList) {
        Sound3dSample *s;

        sound3d_sample_set_delete_when_done(
            (Sound3dSample *)Sound3dOneshotList.next, 0);
        s = (Sound3dSample *)Sound3dOneshotList.next;
        if (s != NULL)
            delete_sample(s);
    }
}

void sound3d_oneshot_close(void)
{
    sound3d_oneshot_reset();
    if (Sound3dSampleSlotPool != NULL) {
        bDeleteSlotPool(Sound3dSampleSlotPool);
        Sound3dSampleSlotPool = NULL;
    }
}

void sound3d_oneshot_update(void)
{
    bNode *n;

    for (n = Sound3dOneshotList.next; n != &Sound3dOneshotList; n = n->next) {
        Sound3dSample *s = (Sound3dSample *)n;

        if (!s->Sample.paused) {
            const VtEntry *e = vt_slot(s->Sound._vtable, SOUND3D_VT_UPDATE);

            ((VtUpdateFn)e->fn)(vt_this(&s->Sound, e), 1.0f, 0, 1.0f);
        }
    }
}

void sound3d_oneshot_mute(int32_t on)
{
    bNode *n;

    for (n = Sound3dOneshotList.next; n != &Sound3dOneshotList; n = n->next) {
        Sound3dSample *s = (Sound3dSample *)n;
        const VtEntry *e = vt_slot(s->Sound._vtable, SOUND3D_VT_MUTE);

        ((VtMuteFn)e->fn)(vt_this(&s->Sound, e), on);
    }
}

Sound3dSample *sound3d_oneshot_play(BSample *sample, const bVector3 *pos,
                                    float volume, float pitch)
{
    Sound3dSample *s;
    const VtEntry *e;

    if (!SoundEnabled)
        return NULL;
    // operator new is not tested: the pool grows when it is full.
    s = sound3d_sample_new();
    sound3d_sample_construct_at(s, pos, volume);
    bsample_initialize_copy(&s->Sample, sample);
    s->Sound.DopplerIsActive = 0;
    e = vt_slot(s->Sound._vtable, SOUND3D_VT_ACTIVATE);
    ((VtActivateFn)e->fn)(vt_this(&s->Sound, e), 1);
    sound3d_sample_set_delete_when_done(s, 1);
    e = vt_slot(s->Sound._vtable, SOUND3DSAMPLE_VT_UPDATE_AT);
    ((VtUpdateAtFn)e->fn)(vt_this(s, e), pos, volume, 0, pitch);
    return s;
}

Sound3dSample *sound3d_oneshot_play_named(struct SoundModule *m,
                                          const char *name,
                                          const bVector3 *pos, float volume,
                                          float pitch)
{
    return sound3d_oneshot_play(sound_get_in_game_sample(m, name), pos,
                                volume, pitch);
}

// ------------------------------------------------------------- the tables

#define E(d, f) { (int16_t)(d), 0, (VtFn)(f) }
// The Sound3d inside a Sound3dSample, back to the Sound3dSample: -8 on the
// console.
#define SUB (-(int)offsetof(Sound3dSample, Sound))

// _vt$7Sound3d, 0x002bb2b0. `__pure_virtual` at 24, 32, 40 and 48.
static const VtEntry sound3d_vt[SOUND3D_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(0, sound3d_destroy),                              //  8  0x002091a0
    E(0, sound3d_activate),                             // 16  0x00208b28
    { 0, 0, NULL },                                     // 24  Update
    { 0, 0, NULL },                                     // 32  Mute
    { 0, 0, NULL },                                     // 40  DeactivateSound
    { 0, 0, NULL },                                     // 48  ActivateSound
    E(0, sound3d_update_cam_relative_dist_and_velocity), // 56 0x00208c78
};

// _vt$13Sound3dSample, 0x002bb358.
static const VtEntry sound3dsample_vt[SOUND3DSAMPLE_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(SUB, sound3d_sample_destroy),                     //  8  0x002095d0
    E(0, sound3d_activate),                             // 16  0x00208b28
    E(SUB, sound3d_sample_update),                      // 24  0x002096f8
    E(SUB, sound3d_sample_mute),                        // 32  0x00209e98
    E(SUB, sound3d_sample_deactivate_sound),            // 40  0x00209e18
    E(SUB, sound3d_sample_activate_sound),              // 48  0x00209dc0
    E(0, sound3d_update_cam_relative_dist_and_velocity), // 56 0x00208c78
    E(0, sound3d_sample_update_at),                     // 64  0x002096a0
};

#undef SUB
#undef E

void sound3d_install_vtables(void)
{
    vt_install(SOUND3D_VTABLE, sound3d_vt, SOUND3D_VT_ENTRIES);
    vt_install(SOUND3DSAMPLE_VTABLE, sound3dsample_vt,
               SOUND3DSAMPLE_VT_ENTRIES);
}
