// carsound -- CarSounds.obj (retail 0x0018d0a8 .. 0x0018f800): the sound a
// car makes, HornSound3d and SirenSound3d.
//
// Every car with sound has a BaseCarSound, made by Car's constructor
// (carinit.c) through one of the three sound::Create* below. It is a
// Sound3d at the car's position that owns the car's other sounds: the horn
// (every car), the siren (cop cars, UsageType 1), the engine and the tyres
// (steps 14-4 and 14-5), and the splashes and the tyre pop, which are
// shared bSamples of the in-game region. The player's adds the wind, the
// engine's echo off cars going the other way, and its own envelope; the
// AI's has a shorter envelope, and only the closest few AI cars sound at
// all.
//
// Once a sound frame, sound::Update calls UpdateCarSounds, which runs each
// car's Update (Car::UpdateSound, through slot 24) and then lets the three
// closest non-player cars in the sound sphere play -- six with one player
// -- and silences the rest.
//
// Retail's records, with the port's: BaseCarSound is 80 bytes and holds
// only pointers after its Sound3d, so it is the same on the 3DS. The four
// that hold a bSample are 4 bytes shorter for each one here, since the
// port's bSample has no vptr (bsound.h); the comments give retail's
// offsets. docs/formats/carsound.md has the rest; tools/carsound_check.py
// runs retail's code against this.

#ifndef CARSOUND_H
#define CARSOUND_H

#include <stdint.h>

#include "bsound.h"
#include "sound3d.h"

struct Car;
struct HornSound3d;
struct SirenSound3d;
struct TopologyCoordinate;

// ------------------------------------------------------------- the tables

// Retail's tables. Each Sound3d-derived class keeps Sound3d's slots
// (sound3d.h); the car sounds add GetHornSample at 64.
#define BASECARSOUND_VTABLE        0x002b4968u
#define BASEPLAYERCARSOUND_VTABLE  0x002b4920u
#define BASEAICARSOUND_VTABLE      0x002b48d8u
#define HORNSOUND3D_VTABLE         0x002b4898u
#define SIRENSOUND3D_VTABLE        0x002b49b0u

#define CARSOUND_VT_GET_HORN_SAMPLE 64  // (this) -> BSample *
#define CARSOUND_VT_ENTRIES          9
#define HORNSOUND3D_VT_ENTRIES       8
#define SIRENSOUND3D_VT_ENTRIES      8

// Registers the five. Once at boot, before a car is made.
void carsound_install_vtables(void);

// ------------------------------------------------------------ the records

// Sound3dEnvelope's three (sound3d.h), and the player's and the AI's,
// which the static constructor (0x0018f0f8) fills: 1.3 out to 260 and to
// 130, each a quarter circle. The demo's were both out to 200.
extern Sound3dEnvelope BasePlayerCarSoundEnvelope;  // 0x00310070
extern Sound3dEnvelope BaseAICarSoundEnvelope;      // 0x00310080

typedef struct BaseCarSound {
    Sound3d   Sound;                    //  0  vptr at 28
    struct Car *pCar;                   // 32
    int32_t   SplashLeft;               // 36  a level, from TriggerSplash
    int32_t   SplashRight;              // 40
    int32_t   SplashLeftTimer;          // 44  frames until the next splash
    int32_t   SplashRightTimer;         // 48
    struct HornSound3d  *HornSound;     // 52
    struct SirenSound3d *SirenSound;    // 56  cop cars only
    Sound3d  *EngineSound;              // 60  step 14-4's
    BSample  *TireSoundBlowOut;         // 64  the in-game "TirePop1"
    Sound3d  *TireSound[2];             // 68  step 14-5's, by side
    const Sound3dEnvelope *pSoundEnvelope;  // 76
} BaseCarSound;                         // 80

typedef struct BasePlayerCarSound {
    BaseCarSound Base;                  //   0
    // For SoundScape's reverb (14-7). Nothing here sets its box: only
    // UpdateTopologyReflections (0x0018e3b8) would, and nothing in retail
    // calls that, so the port leaves it out.
    struct TopologyCoordinate *ReverbTopologyCoordinate;    //  80
    int32_t  EngineReflectionLeft;      //  84
    int32_t  EngineReflectionRight;     //  88
    int32_t  CheckForReflected;         //  92
    BSample  WindSample;                //  96  "Wind", never played
    uint16_t PlayerAzimuth;             // 284 (280 here)
} BasePlayerCarSound;                   // 288

typedef struct BaseAICarSound {
    BaseCarSound Base;                  //  0
} BaseAICarSound;                       // 80

typedef struct HornSound3d {
    Sound3d Sound;                      //   0
    BSample HornSample;                 //  32
    float   DetunePitch;                // 220 (216 here), 1.0
} HornSound3d;                          // 224

typedef struct SirenSound3d {
    Sound3d Sound;                      //   0
    BSample SirenSampleTable[3];        //  32  "CopSiren01" .. "03"
    int32_t CurrentSiren;               // 596 (584 here)
    float   SwitchSirenTime;            // 600  seconds to the next, 17
    int32_t IsSirenBroken;              // 604  bool
    float   BrokenSirenPitchTarget;     // 608
    float   CurrBrokenSirenPitch;       // 612
} SirenSound3d;                         // 616

// ------------------------------------------------------------ the globals

// CarSounds.obj's switches, each 1 on the disc and nothing writes them.
// RoadNoiseEnabled is CarSoundTires.obj's in retail and sits here until
// step 14-5 brings that.
extern int32_t CarSoundEnabled;         // gp-20456
extern int32_t CarDamageSoundEnabled;   // gp-20460
extern int32_t RoadNoiseEnabled;        // gp-16248

// ClosestCarSounds (0x003100c0): the AI cars allowed to sound this frame,
// MaxActiveCarSounds of them (gp-20400; 3, or 6 with one player) and
// NumClosestCarSounds filled (gp-20396).
#define CARSOUND_MAX_CLOSEST 6
extern BaseCarSound *ClosestCarSounds[CARSOUND_MAX_CLOSEST];
extern int32_t       MaxActiveCarSounds;
extern int32_t       NumClosestCarSounds;

// What CarSounds.obj calls that is not ported yet, each NULL until its
// step binds it: the engine_sound and tire_sound factories (14-4, 14-5),
// and tire_sound's TriggerBlowOut and ScaleRoadNoise. A NULL factory makes
// no engine or tyre, and every call on one is skipped.
typedef Sound3d *(*CarSoundCreateFn)(struct Car *c);
typedef Sound3d *(*CarSoundCreateTireFn)(struct Car *c, int32_t side);
extern CarSoundCreateFn     gCreatePlayerEngineFn;  // 0x00211d90
extern CarSoundCreateFn     gCreateAIEngineFn;      // 0x00211de0
extern CarSoundCreateTireFn gCreatePlayerTireFn;    // 0x002141f8
extern CarSoundCreateFn     gCreateAITireFn;        // 0x00214250
extern void (*gTireSoundTriggerBlowOutFn)(Sound3d *tire);       // 0x00214338
extern void (*gTireSoundScaleRoadNoiseFn)(Sound3d *tire, float f); // 0x00214360

// ------------------------------------------------------------ the module

// 0x0018d0a8. The car's player's drive camera POV's volume for the engine
// (0), the tyres (1) or the wind (2), from POVVolumeTable; 1 for any other
// type. A car with no player reads POV 0.
float carsound_get_pov_volume(struct Car *c, int32_t type);

// 0x0018eb28, 0x0018eb70 and 0x0018ebb8, Car's constructor's three: a
// BasePlayerCarSound, and a BaseAICarSound for an AI car or a cop.
BaseCarSound *carsound_create_player(struct Car *c);
BaseCarSound *carsound_create_ai(struct Car *c);
BaseCarSound *carsound_create_ai_cop(struct Car *c);

// Car's destructor's: `delete` through slot 8, with `flags`.
void carsound_delete(BaseCarSound *s, int32_t flags);

// 0x0018ec00. The player's sound's TopologyCoordinate; SoundScape's.
struct TopologyCoordinate *carsound_get_reverb_topology_coordinate(
    BaseCarSound *s);

// 0x0018ea18. Once a sound frame from sound::Update: every car's
// Car::UpdateSound, then the closest non-player cars on and the others off.
void carsound_update_car_sounds(void);
void carsound_maybe_insert(BaseCarSound *s);    // 0x0018e8b0
void carsound_maybe_activate(BaseCarSound *s);  // 0x0018e970

// ----------------------------------------------------------- BaseCarSound

// 0x0018d140. The horn is the derived constructor's, and so is starting it.
void basecarsound_construct(BaseCarSound *s, struct Car *c);
// 0x0018d258, slot 8: the horn, engine, siren and tyres deleted, then
// Sound3d's destructor with `flags`.
void basecarsound_destroy(BaseCarSound *s, int32_t flags);
// 0x0018d340, slot 24.
void basecarsound_update(BaseCarSound *s, float volume, uint16_t azimuth,
                         float pitch);
void basecarsound_update_siren_sound(BaseCarSound *s);   // 0x0018d3f8
BSample *basecarsound_get_horn_sample(BaseCarSound *s);  // 0x0018d480, 64
// 0x0018d488. `level` to SplashRight if `right`, else to SplashLeft.
void basecarsound_trigger_splash(BaseCarSound *s, int32_t right,
                                 int32_t level);
void basecarsound_update_splash(BaseCarSound *s, float volume,
                                int32_t *splash, int32_t *timer);
void basecarsound_mute(BaseCarSound *s, int32_t on);     // 0x0018d550, 32
void basecarsound_trigger_tire_blow_out(BaseCarSound *s); // 0x0018d650
void basecarsound_scale_road_noise(BaseCarSound *s, float f); // 0x0018d6e8
int32_t basecarsound_in_sound_sphere(BaseCarSound *s);   // 0x0018d750
void basecarsound_start_honk_horn(BaseCarSound *s);      // 0x0018d780
void basecarsound_stop_honk_horn(BaseCarSound *s);       // 0x0018d7c0
int32_t basecarsound_is_honking(BaseCarSound *s);        // 0x0018d800
void basecarsound_deactivate_sound(BaseCarSound *s);     // 0x0018d830, 40
void basecarsound_activate_sound(BaseCarSound *s);       // 0x0018d8d8, 48
// 0x0018d950. "Splash1" .. "Splash3", or one of the three at random for -1.
BSample *basecarsound_get_splash_sample(int32_t i);

// ----------------------------------------------------- BasePlayerCarSound

void baseplayercarsound_construct(BasePlayerCarSound *s, struct Car *c);
void baseplayercarsound_destroy(BasePlayerCarSound *s, int32_t flags);
void baseplayercarsound_update(BasePlayerCarSound *s, float volume,
                               uint16_t azimuth, float pitch);
void baseplayercarsound_mute(BasePlayerCarSound *s, int32_t on);
// 0x0018dda0, slot 64: the car's region's sample Prefix + "Horn".
BSample *baseplayercarsound_get_horn_sample(BasePlayerCarSound *s);
// 0x0018de00. "Reflection01" or "02", or either at random for -1.
BSample *baseplayercarsound_get_engine_reflection_sample(
    BasePlayerCarSound *s, int32_t i);
float baseplayercarsound_calc_wind_volume(BasePlayerCarSound *s, float f);
float baseplayercarsound_calc_wind_pitch(BasePlayerCarSound *s, float f);
// 0x0018deb0. The azimuth and pitch are not read.
void baseplayercarsound_update_engine_reflection(BasePlayerCarSound *s,
                                                 float volume,
                                                 uint16_t azimuth,
                                                 float pitch);
void baseplayercarsound_update_dynamic_body_reflections(
    BasePlayerCarSound *s);                              // 0x0018e018

// --------------------------------------------------------- BaseAICarSound

void baseaicarsound_construct(BaseAICarSound *s, struct Car *c);
void baseaicarsound_destroy(BaseAICarSound *s, int32_t flags);
void baseaicarsound_update(BaseAICarSound *s, float volume,
                           uint16_t azimuth, float pitch);

// ------------------------------------------------------------ HornSound3d

// Inline in both car sounds' constructors: Sound3d's, the table, the
// sample from `sample` -- ChooseHornSample's when NULL -- in category 0,
// and DetunePitch 1.
void hornsound3d_construct(HornSound3d *h, BSample *sample);
void hornsound3d_destroy(HornSound3d *h, int32_t flags);    // 0x0018f2b0
void hornsound3d_activate_sound(HornSound3d *h);            // 0x0018f160
void hornsound3d_deactivate_sound(HornSound3d *h);          // 0x0018f188
// 0x0018f190. "Horn01", "Horn02", "Horn03" in turn, game-wide.
BSample *hornsound3d_choose_horn_sample(HornSound3d *h);
void hornsound3d_mute(HornSound3d *h, int32_t on);          // 0x0018f208
void hornsound3d_update(HornSound3d *h, float volume, uint16_t azimuth,
                        float pitch);                       // 0x0018f218

// ----------------------------------------------------------- SirenSound3d

void sirensound3d_construct(SirenSound3d *s);               // 0x0018f388
void sirensound3d_destroy(SirenSound3d *s, int32_t flags);  // 0x0018f710
// 0x0018f300. On for any mode but 0, broken in mode 4.
void sirensound3d_update_mode(SirenSound3d *s, int32_t mode);
void sirensound3d_activate_sound(SirenSound3d *s);          // 0x0018f4d0
void sirensound3d_deactivate_sound(SirenSound3d *s);        // 0x0018f508
void sirensound3d_set_siren_broken(SirenSound3d *s, int32_t on); // 0x0018f520
void sirensound3d_mute(SirenSound3d *s, int32_t on);        // 0x0018f528
void sirensound3d_update(SirenSound3d *s, float volume, uint16_t azimuth,
                         float pitch);                      // 0x0018f548
float sirensound3d_get_broken_siren_pitch(SirenSound3d *s); // 0x0018f7a0

#endif
