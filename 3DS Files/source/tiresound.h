// tiresound -- CarSoundTires.obj: BaseTireSound, TerrainOneShot,
// PlayerTireSound, OpponentTireSound and tire_sound's factories (retail
// 0x002124d8 .. 0x00214d68).
//
// Every car with sound has tyres, made by its BaseCarSound's constructor
// (carsound.c) through tire_sound::CreatePlayerTire -- one for each side of
// the car, or one in all with two players -- or CreateAITire, and owned as
// its TireSound. Each is a Sound3d, updated each sound frame from the
// BaseCarSound's Update with its volume, azimuth and Doppler pitch.
//
// The player's are the full set: road noise or gravel noise by the wheels'
// terrain, a longitudinal skid and a squall from the wheels' slip and
// traction, the burn-out peel, leaves under the wheels in autumn, one-shots
// on metal grates and potholes, a flop when a wheel lands and a bottom-out
// when it lands hard, and with a tyre blown the thump of the rim and its
// scrape. An AI car's has only the skid, on road or on dirt, and the flop.
//
// Retail's records, with the port's: the bSample in each is 4 bytes
// shorter here (bsound.h), so everything after one sits earlier; the
// comments give retail's offsets. The names are the demo's, whose
// PlayerTireSound held TireFlop, BottomOut and the two touching flags that
// retail moved into BaseTireSound. docs/formats/tiresound.md has the rest;
// tools/tiresound_check.py runs retail's code against this.

#ifndef TIRESOUND_H
#define TIRESOUND_H

#include <stdint.h>

#include "bsound.h"
#include "sound3d.h"

struct Car;

// ------------------------------------------------------------- the tables

// Retail's. Sound3d's slots (sound3d.h), and BaseTireSound's two at 64 and
// 72; ActivateSound and DeactivateSound do nothing in the player's, and
// ActivateSound, TriggerTireBlowOut and ScaleRoadNoise nothing in the AI's.
#define BASETIRESOUND_VTABLE     0x002bc1e8u
#define PLAYERTIRESOUND_VTABLE   0x002bc198u
#define OPPONENTTIRESOUND_VTABLE 0x002bc148u

#define TIRESOUND_VT_TRIGGER_BLOW_OUT 64    // (this)
#define TIRESOUND_VT_SCALE_ROAD_NOISE 72    // (this, float)
#define TIRESOUND_VT_ENTRIES          10

// Registers the three. Once at boot, before a car is made.
void tiresound_install_vtables(void);

// ------------------------------------------------------------ the records

// The side of the car a player's tyres sound for, 0 or 1, and -1 an AI
// car's, all four wheels. Each function picks its own two wheels by it, and
// retail's do not agree on which two (docs/formats/tiresound.md).
typedef int32_t CarSide;

typedef struct BaseTireSound {
    Sound3d  Sound;                     //   0
    uint16_t FrontTireTouching;         //  32  a flag, 1 to start with
    uint16_t RearTireTouching;          //  34
    BSample  TireFlop;                  //  36  "TireFlop"
    BSample  BottomOut;                 // 224 (220 here) "BottomOut"
} BaseTireSound;                        // 412 (404)

// A one-shot played once each time the side's wheels cross a terrain.
typedef struct TerrainOneShot {
    int32_t  bFoundSample;              //   0
    int32_t  bOnTerrainType;            //   4
    float   *pTimeDelay;                //   8  shared: none plays while > 0
    BSample  TerrainSample;             //  12
    CarSide  Side;                      // 200 (196 here)
} TerrainOneShot;                       // 204 (200)

typedef struct PlayerTireSound {
    BaseTireSound Base;                 //    0
    struct Car *pCar;                   //  412 (404 here)
    float    LockedRearPitch;           //  416  the right's skid pitch, -1
    float    CurrSquallPitch;           //  420
    float    CurrSquallVolume;          //  424
    int32_t  Mode;                      //  428  0, and nothing reads it
    CarSide  Side;                      //  432
    float    RoadNoiseScale;            //  436  ScaleRoadNoise's
    int32_t  PlayThumperSounds;         //  440  bool: a tyre has blown
    float    UpdateThumperTime;         //  444  seconds to the next thump
    int32_t  PrevShouldMakeRoadNoise;   //  448  bool, kept through puddles
    TerrainOneShot MetalBump;           //  452  "MetalBump" on metal grates
    TerrainOneShot PotHole;             //  656  "TireFlop" in potholes
    int32_t  FoundLeavesSample;         //  860  bool
    BSample  LeavesNoise;               //  864  the track's "Leaves"
    BSample  RoadNoise;                 // 1052  "RoadNoise"
    BSample  DirtNoise;                 // 1240  "GravelNoise"
    BSample  RoadSkid;                  // 1428  "LongitudinalSkid"
    BSample  DirtSkid;                  // 1616  "GravelSkid"
    BSample  Squall;                    // 1804  "SquallSkid"
    BSample  DirtSquall;                // 1992  "GravelSkid"
    BSample  BurnOutPeel;               // 2180  "BurnOutPeel"
    BSample  Busted;                    // 2368  "TireFlat", the thump
    BSample  BustedScrape;              // 2556  "CrashMetalScrape"
} PlayerTireSound;                      // 2744 (2688)

typedef struct OpponentTireSound {
    BaseTireSound Base;                 //   0
    struct Car *pCar;                   // 412 (404 here)
    BSample  RoadSkid;                  // 416  "LongitudinalSkid"
    BSample  DirtSkid;                  // 604  "GravelSkid"
    BSample *PrevSkid;                  // 792  last frame's
    float    CurrSkidVolume;            // 796
    float    TargetSkidVolume;          // 800
} OpponentTireSound;                    // 804 (788)

// ------------------------------------------------------------ the globals

// PlayerTireSound::fOneShotTimeDelay (gp-16244): set to 0.3 by a one-shot,
// counted down by every player tyre's Update, and none plays while above 0.
extern float PlayerTireSoundOneShotTimeDelay;
// gp-16232, 0.0065: the road noise's pitch by the wheels' spin. Retail has
// no name for it; this is the port's.
extern float TireNoisePitchScale;
// gp-13344, 8192 from the static constructor (0x00214878): the thump's
// azimuth off the car's, an eighth of a turn, the other way on the right.
extern uint16_t ThumperAzimuthOffset;

// ------------------------------------------------------------ tire_sound

// 0x002141f8 and 0x00214250: carsound.h's gCreatePlayerTireFn and
// gCreateAITireFn.
Sound3d *tiresound_create_player(struct Car *c, int32_t side);
Sound3d *tiresound_create_ai(struct Car *c);
// 0x00214338 and 0x00214360: slots 64 and 72 on a tyre, carsound.h's
// gTireSoundTriggerBlowOutFn and gTireSoundScaleRoadNoiseFn.
void tiresound_trigger_blow_out(Sound3d *tire);
void tiresound_scale_road_noise(Sound3d *tire, float f);

// -------------------------------------------------------- BaseTireSound

void basetiresound_construct(BaseTireSound *s);                // 0x002124f0
void basetiresound_destroy(BaseTireSound *s, int32_t flags);   // 0x00214a78
void basetiresound_mute(BaseTireSound *s, int32_t on);         // 0x002125a0
// 0x002125e0. When a side's wheel lands -- its front or its rear, or any
// of the four for -1 -- the flop, as loud as the car falls fast, and the
// bottom-out too when it falls hard.
void basetiresound_update_tire_impact(BaseTireSound *s, struct Car *c,
                                      CarSide side);
void basetiresound_trigger_tire_blow_out(BaseTireSound *s);    // 0x00214a70
void basetiresound_scale_road_noise(BaseTireSound *s, float f); // 0x00214a68

// ------------------------------------------------------- TerrainOneShot

// 0x002127e0. Without a sample it never plays.
void terrainoneshot_init(TerrainOneShot *t, BSample *sample,
                         float *pTimeDelay, CarSide side);
void terrainoneshot_destroy(TerrainOneShot *t, int32_t flags); // 0x00214a10
void terrainoneshot_mute(TerrainOneShot *t, int32_t on);       // 0x00212840
// 0x00212860. Plays once when either of the side's wheels first crosses
// `terrain`, unless the shared delay is running.
void terrainoneshot_update(TerrainOneShot *t, struct Car *c,
                           int32_t terrain, float volume, uint16_t azimuth,
                           float pitch);

// ------------------------------------------------------ PlayerTireSound

void playertiresound_construct(PlayerTireSound *s, struct Car *c,
                               CarSide side);                  // 0x00212950
void playertiresound_destroy(PlayerTireSound *s, int32_t flags); // 0x00212cf0
void playertiresound_deactivate_sound(PlayerTireSound *s);     // 0x00212e88
void playertiresound_activate_sound(PlayerTireSound *s);       // 0x00212e90
// 0x00212e98. bSample's pitch is an offset from 1.
void playertiresound_set_sample_pitch(PlayerTireSound *s, BSample *smp,
                                      float pitch);
void playertiresound_calc_tire_squall_volume_and_pitch(
    PlayerTireSound *s, float *volume, float *pitch);          // 0x00212eb0
void playertiresound_calc_tire_skid_volume_and_pitch(
    PlayerTireSound *s, float *volume, float *pitch);          // 0x00212f80
float playertiresound_calc_tire_noise_volume(PlayerTireSound *s);  // 0x002131e0
float playertiresound_calc_tire_noise_pitch(PlayerTireSound *s);   // 0x002132a0
float playertiresound_calc_tire_squall_volume(PlayerTireSound *s); // 0x00213338
float playertiresound_calc_tire_squall_pitch(PlayerTireSound *s);  // 0x00213440
void playertiresound_mute(PlayerTireSound *s, int32_t on);     // 0x002134d8
// 0x002135a0, slot 24.
void playertiresound_update(PlayerTireSound *s, float volume,
                            uint16_t azimuth, float pitch);
void playertiresound_update_squall(PlayerTireSound *s, int32_t onRoad,
                                   float volume, uint16_t azimuth,
                                   float pitch);               // 0x00213c30
void playertiresound_update_leaves(PlayerTireSound *s, float volume,
                                   uint16_t azimuth, float pitch); // 0x00213dd8
void playertiresound_reset_thumper_time(PlayerTireSound *s);   // 0x00213f40
void playertiresound_update_thumper_tires(PlayerTireSound *s); // 0x00213f80
void playertiresound_trigger_tire_blow_out(PlayerTireSound *s); // 0x00214a00
void playertiresound_scale_road_noise(PlayerTireSound *s, float f);

// ---------------------------------------------------- OpponentTireSound

void opponenttiresound_construct(OpponentTireSound *s, struct Car *c);
void opponenttiresound_destroy(OpponentTireSound *s, int32_t flags);
void opponenttiresound_update(OpponentTireSound *s, float volume,
                              uint16_t azimuth, float pitch); // 0x00214928
void opponenttiresound_mute(OpponentTireSound *s, int32_t on); // 0x002148e0
void opponenttiresound_deactivate_sound(OpponentTireSound *s); // 0x00214898
void opponenttiresound_activate_sound(OpponentTireSound *s);   // 0x00214890
// 0x00214ad8. The skid on road or dirt by the wheels' terrain, as loud as
// the worst wheel's slip once that is over 10.
void opponenttiresound_update_skids(OpponentTireSound *s, float volume,
                                    uint16_t azimuth, float pitch);

#endif
