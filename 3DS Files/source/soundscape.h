// soundscape -- SoundScape.obj: SoundArea, ReverbArea, LoopingAmbient,
// OneShotAmbient, SoundScape and sound_scape (retail 0x001cdde0 ..
// 0x001cff20).
//
// The track's own sounds. Each track bundle but one (TRACKA12) has a
// 0x80038000 chunk of three kinds of record, each over a SoundArea, a set
// of ground-plane triangles:
//   - reverb areas, the tunnels and bridges: while a player's car is under
//     one and there is road above it, the SPU2's reverb is turned up;
//   - looping ambients -- a campfire, a stream, a log mill -- played while
//     a camera is in the area, faded in and out, panned towards the sound
//     source when there is one; or, when the source lies inside the area,
//     a sound sphere around the source whose volume falls off with the
//     cameras' distance from it;
//   - one-shot ambients, the birds, played on entering the area and then
//     every Repeat seconds, give or take, at a random pitch and azimuth.
//
// The 3DS's bsnd has no reverb unit, so the four reverb calls go through
// seams the port leaves NULL; the reverb areas still decide
// SoundScapeIsInsideTunnel, which the chopper's sound fades on.
//
// docs/formats/soundscape.md has the rest; tools/soundscape_check.py runs
// retail's code against this.

#ifndef SOUNDSCAPE_H
#define SOUNDSCAPE_H

#include <stdint.h>

#include "bsound.h"
#include "bvector.h"

struct Camera;
struct Car;

// ------------------------------------------------------------ the records

// SoundArea, 16 bytes: the vertices and the faces, three vertex indices
// each (SoundAreaFace), both in the chunk.
typedef struct SoundArea {
    int32_t         NumAreaVerts;   //  0
    const bVector2 *AreaVerts;      //  4
    int32_t         NumAreaFaces;   //  8
    const int32_t  *AreaFaces;      // 12
} SoundArea;

// SoundDesc, 12 bytes. Nothing reads one.
typedef struct SoundDesc {
    const char *SampleName;         // 0  the chunk's, 32 bytes
    float       Period;             // 4
    float       PeriodError;        // 8
} SoundDesc;

#define REVERBAREA_SOUNDS 8

// ReverbArea, 124 bytes. Reverb and the sounds are read in and not used.
typedef struct ReverbArea {
    const char *Name;               //  0
    int32_t     Reverb;             //  4
    SoundArea   Area;               //  8
    int32_t     NumSounds;          // 24
    SoundDesc   Sounds[REVERBAREA_SOUNDS]; // 28
} ReverbArea;

// LoopingAmbient, 64 bytes. Sample is its own, a copy of the region's
// from bSample's pool, made the first time Update finds the region in.
typedef struct LoopingAmbient {
    const char *Name;               //  0
    const char *SampleName;         //  4
    int32_t     FadeInDuration;     //  8  ms
    int32_t     FadeOutDuration;    // 12  ms
    int32_t     IsActive;           // 16
    int32_t     HasSoundSource;     // 20
    int32_t     UseSoundSphere;     // 24
    BSample    *Sample;             // 28
    SoundArea   Area;               // 32
    bVector2    SoundSource;        // 48
    float       SoundSourceDistanceCoeff; // 56  read by nothing called
    float       SoundSphereRadius;  // 60
} LoopingAmbient;

// OneShotAmbient, 244 bytes in retail, whose offsets these are; the
// port's bSample is 184 bytes to retail's 188, so Area sits at 224 here.
// Sample is the region's own. Sample360Azimuth plays the same sound at
// the back when AzimuthDeviation is 360, the one in front at 16384 and it
// at 0xc000.
typedef struct OneShotAmbient {
    const char *Name;               //  0
    const char *SampleName;         //  4
    float       Repeat;             //  8  seconds; 0 plays once
    float       RepeatDeviation;    // 12
    float       Pitch;              // 16
    float       PitchDeviation;     // 20
    float       AzimuthDeviation;   // 24  degrees: 0, 360 or other
    int32_t     IsActive;           // 28
    float       UpdateOneShotTime;  // 32
    BSample    *Sample;             // 36
    BSample     Sample360Azimuth;   // 40
    SoundArea   Area;               // 228
} OneShotAmbient;

// ------------------------------------------------------------ the statics

#define SOUNDSCAPE_REVERB_AREAS    32
#define SOUNDSCAPE_LOOPING_AMBIENT 32
#define SOUNDSCAPE_ONESHOT_AMBIENT 48

// The chunk and its three children.
#define SOUNDSCAPE_CHUNK           0x80038000u
#define SOUNDSCAPE_CHUNK_REVERB    0x00038010u
#define SOUNDSCAPE_CHUNK_LOOPING   0x00038020u
#define SOUNDSCAPE_CHUNK_ONESHOT   0x00038030u

extern ReverbArea     SoundScapeReverbAreaArray[SOUNDSCAPE_REVERB_AREAS];
                                                    // 0x00317c80
extern LoopingAmbient SoundScapeLoopingAmbientArray[SOUNDSCAPE_LOOPING_AMBIENT];
                                                    // 0x00314688
extern OneShotAmbient SoundScapeOneShotAmbientArray[SOUNDSCAPE_ONESHOT_AMBIENT];
                                                    // 0x00314e88

extern int32_t  SoundScapeDataJustLoaded;           // gp-18088
extern int32_t  SoundScapeNumReverbAreas;           // gp-18084
extern int32_t  SoundScapeCurrentlyActiveReverbArea; // gp-18080, -1
extern int32_t  SoundScapeReverbOn;                 // gp-18076
// gp-18072. Only UpdateWeather, which nothing calls, would set it.
extern BSample *SoundScapeRain;
extern float    SoundScapeReverbVolume;             // gp-18068
extern float    SoundScapeTargetReverbVolume;       // gp-18064
extern float    SoundScapeReverbPan;                // gp-18060
extern int32_t  SoundScapeNumLoopingAmbient;        // gp-17996
extern int32_t  SoundScapeNumOneShotAmbient;        // gp-18000

// The reverb's mode and its four parameters, each a current value and a
// desired one, equal in the image (REVERB_MODE_MEDIUM, .65, 1, .85, .75).
// Nothing writes a desired one, so UpdateReverbAreas never sends either.
extern int32_t  ReverbMode;                         // gp-18056
extern int32_t  DesiredReverbMode;                  // gp-18052
extern float    ReverbDelay, DesiredReverbDelay;    // gp-18048, -18044
extern float    ReverbFeedback, DesiredReverbFeedback; // gp-18040, -18036
extern float    ReverbLevel, DesiredReverbLevel;    // gp-18032, -18028
extern float    ReverbDepth, DesiredReverbDepth;    // gp-18024, -18020

// ReverbModeEnum to bEffect's modes, 0x00317c48.
extern const uint32_t ReverbModeTable[13];

// The SPU2's reverb, which the 3DS does not have. NULL, the port's default,
// skips the call:
//   bDriver::PlatSetEffectVolume(voices, on, volume, pan)  0x0025d4f8, on
//     bSound's driver; voices 0xffffffff and on 1 at every call;
//   bEffect::SetMode(mode)                                 0x002703e8;
//   bEffect::SetParameter(which, core, value)              0x002705c0.
extern void (*gSoundScapeEffectVolumeFn)(uint32_t voices, uint32_t on,
                                         float volume, float pan);
extern void (*gSoundScapeEffectModeFn)(uint32_t mode);
extern void (*gSoundScapeEffectParameterFn)(uint32_t which, uint32_t core,
                                            float value);

// --------------------------------------------------------------- SoundArea

// 0x001cdde0. The area over chunk data at p; returns the end of it.
const uint8_t *soundarea_initialize(SoundArea *a, const uint8_t *p);
// 0x001cde20. Whether any face holds pt (eIsPointInPoly, three corners).
int32_t soundarea_is_point_in_area(const SoundArea *a, const bVector2 *pt);
// 0x001cdf30. Of the two cameras, those set whose position is in the area,
// in a static pair (gp-13384); *count says how many.
struct Camera **soundarea_are_cameras_in_area(const SoundArea *a,
                                              struct Camera **cams,
                                              int32_t *count);

// -------------------------------------------------------------- ReverbArea

void reverbarea_initialize(ReverbArea *r, const uint8_t *chunk); // 0x001cdfd0

// ---------------------------------------------------------- LoopingAmbient

// 0x001ce078. The fades as whole milliseconds. With a sound source inside
// the area, the sound sphere: its radius the farthest vertex.
void loopingambient_initialize(LoopingAmbient *l, const uint8_t *chunk);
// 0x001ce218. Where the source lies about the camera's heading, a BAM.
uint16_t loopingambient_compute_azimuth(const LoopingAmbient *l,
                                        const struct Camera *cam);
void loopingambient_update_using_area(LoopingAmbient *l,
                                      struct Camera **cams);   // 0x001ce2d8
void loopingambient_update_using_sound_sphere(LoopingAmbient *l,
                                              struct Camera **cams);
                                                            // 0x001ce478
// 0x001ce6b0. The sample made first if it can be, then one of the two.
void loopingambient_update(LoopingAmbient *l, struct Camera **cams);
void loopingambient_mute(LoopingAmbient *l, int32_t on);       // 0x001ce780

// ---------------------------------------------------------- OneShotAmbient

void oneshotambient_initialize(OneShotAmbient *o, const uint8_t *chunk);
                                                            // 0x001ce7a0
// 0x001ce7f8. Played at the pitch and azimuth, each varied when it is
// to be, and the next time set when it repeats.
void oneshotambient_play(OneShotAmbient *o);
void oneshotambient_update(OneShotAmbient *o, struct Camera **cams);
                                                            // 0x001ce9e0
void oneshotambient_mute(OneShotAmbient *o, int32_t on);       // 0x001ceb20

// The static constructor (0x001cfe98): the 48 Sample360Azimuth bSamples
// constructed. Once at boot.
void soundscape_init(void);

// -------------------------------------------------------------- SoundScape

// 0x001ceb40. Whether the car is in reverb area i; 0 past the last.
int32_t soundscape_will_sound_right(int32_t i, struct Car *car);
// 0x001ceb88. The first reverb area the car is in, or -1.
int32_t soundscape_find_good_reverb_area(struct Car *car);
// 0x001ced40. One player: the target the reverb volume eases to. Two: the
// car's road noise scaled by 1 + v.
void soundscape_set_reverb_volume(float v, struct Car *car);
// 0x001ced88. Keeps CurrentlyActiveReverbArea, searching again when it
// no longer holds; returns which of the two cars the area is the second's.
int32_t soundscape_is_inside_reverb_area(struct Car **cars);
void soundscape_update_reverb_areas(void);                  // 0x001cee60
void soundscape_update_looping_ambient(void);               // 0x001cf478
void soundscape_update_one_shot_ambient(void);              // 0x001cf4e8
// 0x001cec00. With a race coordinator: the three above.
void soundscape_update(void);
// 0x001cec38. Every ambient paused or not, the rain muted when it plays;
// on, the reverb off.
void soundscape_mute(int32_t on);

// sound_scape::Update and Mute, 0x001cebf0 and 0x001cebf8, jump to the two
// above. sound.h's scape hooks.
void sound_scape_update(void);
void sound_scape_mute(int32_t on);

// 0x001cf698. Whether a reverb area is current. ChopperSound's.
int32_t soundscape_is_inside_tunnel(void);

// 0x001cf6a8 and 0x001cf838, bchunkload's slot 21.
int loader_sound_scape(uint8_t *chunk);
int unloader_sound_scape(uint8_t *chunk);

#endif
