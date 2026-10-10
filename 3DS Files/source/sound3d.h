// sound3d -- Sound3d.obj: Sound3d, sound3d_oneshot and Sound3dSample
// (retail 0x00208ae8 .. 0x00209ea8), with SoundScape's GetActiveCameras
// (0x001cf268), which the first is built on.
//
// Sound3d is thirty-two bytes and no pointers, so it is the same record on
// every target. Every positional sound in the game derives from it -- the
// car's engine, horn and siren, the chopper, the one-shots. It knows how far
// the closest camera is and how fast that is changing, and from that its
// volume (an envelope), its pitch (Doppler) and its azimuth. What it plays
// is the derived class's: Update(float, unsigned short, float), Mute,
// ActivateSound and DeactivateSound are pure here.
//
// Sound3dSample is a Sound3d over one bSample, on sound3d_oneshot's list:
// the one-shots -- glass, foliage, explosions, the smokeables -- are each a
// Sound3dSample new'd from a pool of 30, played once at a place and deleted
// by their bSample's callback when it stops.
//
// Car reaches Sound3d once: UpdateSound calls `Update` on the BaseCarSound,
// and BaseCarSound's first base is Sound3d at offset 0
// (`BaseCarSound:Tt824=s80!1,020,3181`), so the vptr Car reads at +28 of
// the BaseCarSound is this record's. BaseCarSound itself stays opaque until
// 14-3 brings it. docs/formats/sound3d.md has the rest.

#ifndef SOUND3D_H
#define SOUND3D_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "bsound.h"
#include "bvector.h"

struct Camera;
struct SoundModule;

typedef struct Sound3d {
    int32_t  Activated;             //  0  bool, a word wide in this compiler
    int32_t  DopplerIsActive;       //  4  bool
    float    Volume;                //  8
    float    Pitch;                 // 12
    uint16_t Azimuth;               // 16
    uint8_t  _pad18[2];             // 18
    float    SndToCameraVelocity;   // 20
    float    SndToCameraDistance;   // 24
    uint32_t _vtable;               // 28  `$vf3181:47,224`
} Sound3d;                          // 32

typedef char sound3d_layout_check[
    (offsetof(Sound3d, Azimuth) == 16
     && offsetof(Sound3d, SndToCameraVelocity) == 20
     && offsetof(Sound3d, _vtable) == 28
     && sizeof(Sound3d) == 32) ? 1 : -1];

// _vt$7Sound3d and _vt$13Sound3dSample, retail's.
#define SOUND3D_VTABLE        0x002bb2b0u
#define SOUND3DSAMPLE_VTABLE  0x002bb358u

// _vt$12BaseCarSound. Slot 24 is BaseCarSound::Update(float, unsigned
// short, float), overriding Sound3d's.
#define BASECARSOUND_VTABLE        0x00297dc8u
#define BASEPLAYERCARSOUND_VTABLE  0x00297d80u
#define BASEAICARSOUND_VTABLE      0x00297d38u

// The slots, by byte offset. Sound3d's table has `__pure_virtual` at 24,
// 32, 40 and 48.
#define SOUND3D_VT_DESTROY        8    // (this, flags): flags & 1 deletes
#define SOUND3D_VT_ACTIVATE      16    // (this, bool)
#define SOUND3D_VT_UPDATE        24    // (this, float, unsigned short, float)
#define SOUND3D_VT_MUTE          32    // (this, int)
#define SOUND3D_VT_DEACTIVATE    40    // DeactivateSound (this)
#define SOUND3D_VT_ACTIVATESOUND 48    // ActivateSound (this)
#define SOUND3D_VT_CAMRELATIVE   56    // UpdateCamRelativeDistAndVelocity
// Sound3dSample's own, called on the Sound3dSample, not its Sound3d.
#define SOUND3DSAMPLE_VT_UPDATE_AT 64  // (this, bVector3 *, float, ushort, float)

#define SOUND3D_VT_ENTRIES       8
#define SOUND3DSAMPLE_VT_ENTRIES 9

// Sound3dEnvelope, 12 bytes. The volume at distance d is
// MaxVolAtSource * (1 - sqrt(2*d*Coeff - (d*Coeff)^2)) out to the cut-off,
// and 0 past it: a quarter circle when Coeff is 1 / CutOffDistance, which
// is how both of Sound3dSample's constructors set it.
typedef struct Sound3dEnvelope {
    float MaxVolAtSource;           // 0
    float CutOffDistance;           // 4
    float Coeff;                    // 8
} Sound3dEnvelope;

// Sound3dSample, 272 bytes in retail, whose offsets the comments give. The
// port's bSample is 184 bytes to retail's 188 (it has no vptr), so here
// everything after it sits 4 earlier, and the pointers differ on a host.
typedef struct Sound3dSample {
    bNode           Node;               //   0  sound3d_oneshot's list
    Sound3d         Sound;              //   8
    BSample         Sample;             //  40
    Sound3dEnvelope Envelope;           // 228
    int32_t         DeleteWhenDone;     // 240  never written in retail
    int32_t         PositionIsDefined;  // 244
    bVector3        Position;           // 256
} Sound3dSample;

// Installs the two tables. Once at boot, before any Sound3d is made.
void sound3d_install_vtables(void);

// ------------------------------------------------------------- SoundScape

// GetActiveCameras, 0x001cf268: the two players' cameras by index, each
// eGetView(i + 1)'s, or NULL where there is no player. A static pair
// (gp-13368), filled again on every call. Retail falls back to view 1's
// camera when there are no players, but its count of players is bumped in
// a delay slot for every slot, so the fallback never runs; nor does it here.
struct Camera **get_active_cameras(void);

// ---------------------------------------------------------------- Sound3d

// 0x00208ae8: inactive, Doppler on, volume and pitch 1, the rest 0.
void sound3d_construct(Sound3d *s);
// 0x002091a0, slot 8: the vptr back to Sound3d's, and with flags & 1 the
// delete. A derived class's destructor calls it with 0.
void sound3d_destroy(Sound3d *s, int32_t flags);

// 0x00208b28, slot 16. Off: DeactivateSound. On: ActivateSound unless it
// is on already. Either way Activated is the argument, as passed.
void sound3d_activate(Sound3d *s, int32_t on);

// 0x00208b98. The distance from pos to the closer of the active cameras,
// or to view 1's camera when neither is closer than 9e9.
float sound3d_get_dist_to_closest_camera(const bVector3 *pos);

// 0x00208c78, slot 56. The distance, and its rate of change over the
// frame's WorldTimeElapsed when that is within 80 either way.
void sound3d_update_cam_relative_dist_and_velocity(Sound3d *s,
                                                   const bVector3 *pos);

// 0x00208cf0. UpdateCamRelativeDistAndVelocity through the table, then the
// Doppler pitch (1 - velocity / SpeedOfSound), the volume (the envelope's,
// at most 1, or 1 without one) and the azimuth.
void sound3d_update(Sound3d *s, const bVector3 *pos,
                    const Sound3dEnvelope *env);

// 0x00208df8. With two players, CarSoundMultiPlayerAzimuth, negated when
// the closer camera is the first player's. Otherwise where pos lies about
// view 1's camera's heading in the ground plane, as a BAM.
uint16_t sound3d_compute_azimuth(const bVector3 *pos);

// 0x00208f70. The volume a unit envelope out to `cutOff` gives at the
// closest camera's distance.
float sound3d_compute_volume(const bVector3 *pos, float cutOff);

// 0x00208fe0 and 0x00209070: an azimuth as a pan in [-0.5, 0.5], and back.
float    sound3d_azimuth_to_pan(uint16_t azimuth);
uint16_t sound3d_pan_to_azimuth(float pan);

// 0x00209150: the azimuth, as a float.
float sound3d_get_azimuth(const Sound3d *s);

// The globals it reads. CarSoundMultiPlayerAzimuth (gp-20464) is 0 on the
// disc and nothing writes it; SpeedOfSound (gp-16480) is 350.
extern uint16_t CarSoundMultiPlayerAzimuth;
extern float    SpeedOfSound;

// ---------------------------------------------------------- Sound3dSample

// The pool, "Sound3dSampleSlotPool" (gp-16448), and the one-shots' list
// (gp-16456), which every Sound3dSample joins at its head.
extern BSlotPool *Sound3dSampleSlotPool;
extern bNode      Sound3dOneshotList;

// 0x002094b0: unplaced, the unit envelope out to 200.
void sound3d_sample_construct(Sound3dSample *s);
// 0x00209530: at pos, an envelope of `maxVol` out to 135.
void sound3d_sample_construct_at(Sound3dSample *s, const bVector3 *pos,
                                 float maxVol);
// 0x002095d0, slot 8: stopped, off the list, the parts destroyed, and with
// flags & 1 the slot back to the pool.
void sound3d_sample_destroy(Sound3dSample *s, int32_t flags);

// 0x00209670 and 0x00209690: a slot, and one given back.
Sound3dSample *sound3d_sample_new(void);
void           sound3d_sample_free(Sound3dSample *s);

// 0x002096a0, slot 64. With sound on and the sound active: the position,
// then Update(volume, azimuth, pitch) through the table.
void sound3d_sample_update_at(Sound3dSample *s, const bVector3 *pos,
                              float volume, uint16_t azimuth, float pitch);
// 0x002096f8, slot 24. Sound3d's Update at Position with the envelope,
// then the volume and pitch scaled by the arguments and the azimuth; a
// volume of 0 stops it, sound or no sound. The azimuth argument is not
// read.
void sound3d_sample_update(Sound3dSample *s, float volume, uint16_t azimuth,
                           float pitch);

// 0x002097a8: the bSample's callback while DeleteWhenDone. A stop with a
// Sound3dSample to hand deletes it.
void sound3d_remove_sample(uint32_t event, void *sample, void *data);
// 0x002097e8: on, the callback above with this; off, no callback at all.
void sound3d_sample_set_delete_when_done(Sound3dSample *s, int32_t on);

void sound3d_sample_activate_sound(Sound3dSample *s);    // 0x00209dc0
void sound3d_sample_deactivate_sound(Sound3dSample *s);  // 0x00209e18
void sound3d_sample_set_position(Sound3dSample *s, const bVector3 *pos);
void sound3d_sample_set_azimuth(Sound3dSample *s, uint16_t azimuth);
void sound3d_sample_set_volume(Sound3dSample *s, float volume);
// 0x00209e78: bSample's pitch is an offset from 1.
void sound3d_sample_set_pitch(Sound3dSample *s, float pitch);
// 0x00209e98: a pause, not a mute.
void sound3d_sample_mute(Sound3dSample *s, int32_t on);

// -------------------------------------------------------- sound3d_oneshot

void sound3d_oneshot_init(void);     // 0x002091d0: the pool, once
// 0x00209208: every one-shot deleted, its callback cleared first.
void sound3d_oneshot_reset(void);
void sound3d_oneshot_close(void);    // 0x00209268: Reset, and the pool
// 0x002092a0: each one-shot not paused, Update(1, 0, 1).
void sound3d_oneshot_update(void);
void sound3d_oneshot_mute(int32_t on);  // 0x00209320: Mute on each

// 0x002093d8. With sound on, a new Sound3dSample at pos with the sample's
// patch, Doppler off, activated (so playing), deleted when done, and
// updated once at pos; NULL with sound off.
Sound3dSample *sound3d_oneshot_play(BSample *sample, const bVector3 *pos,
                                    float volume, float pitch);
// 0x00209388: the same, with the in-game region's sample by name.
Sound3dSample *sound3d_oneshot_play_named(struct SoundModule *m,
                                          const char *name,
                                          const bVector3 *pos, float volume,
                                          float pitch);

#endif
