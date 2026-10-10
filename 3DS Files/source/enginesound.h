// enginesound -- CarSoundEngine.obj: PlayerEngineSound, AIEngineSound and
// engine_sound's two factories (retail 0x0020fad0 .. 0x00212470).
//
// Every car with sound has an engine, made by its BaseCarSound's
// constructor (carsound.c) through engine_sound::CreatePlayerEngine or
// CreateAIEngine and owned as its EngineSound. Both are Sound3ds, updated
// each sound frame from the BaseCarSound's Update with its volume, azimuth
// and Doppler pitch.
//
// The player's is EA's granular engine: twelve patches of the car's own
// region -- the "l" six for load, on the throttle, and the "c" six for
// coast -- each a loop at a few RPMs. Two tables on the disc,
// sound\engine.ctb and sound\engine.ltb, say how loud each patch is at
// each of 441 levels of the engine's RPM; the throttle crossfades the two
// sets, and the camera's timbre crossfades the "e" (engine) and "x"
// (exhaust) patches within each. Every patch plays a pair of voices, one
// each side of the car's azimuth, and bends with the RPM. Nitro adds a
// start and a loop; a gear change ducks the engine while the clutch is
// out, and long stretches on full throttle duck it under the music.
//
// An AI car's is one sample, "AIEngine0" plus the car's AIEngineNumber, its
// pitch from a running mean of the RPM that settles at each gear change.
// On the start line, below 5 mph, it revs at random instead.
//
// Retail's records, with the port's: the bSample in each is 4 bytes
// shorter here (bsound.h), so everything after one sits earlier; the
// comments give retail's offsets. docs/formats/enginesound.md has the
// rest; tools/enginesound_check.py runs retail's code against this.

#ifndef ENGINESOUND_H
#define ENGINESOUND_H

#include <stdint.h>

#include "average.h"
#include "bsound.h"
#include "sound3d.h"

struct Car;

// The port's voice budget. ndsp gives the game 22 voices (bsnd.h) where
// the PS2 had 48, and retail's player engine locks twelve of them with one
// player -- both voices of each "l" patch -- and takes up to eight more for
// the "c" patches, twenty of the twenty-two. So on the 3DS the player's
// engine runs as retail's does in mono, audio mode 0: one voice a patch, at
// the car's azimuth, 1.3 times as loud, and it locks only the six voices it
// plays, ten at most in all. The checker builds with this at 1 to run
// retail's pair as well.
#ifndef ENGINESOUND_RETAIL_VOICES
#define ENGINESOUND_RETAIL_VOICES 0
#endif

// ------------------------------------------------------------- the tables

// Retail's. Sound3d's slots (sound3d.h); ActivateSound and DeactivateSound
// do nothing in the player's.
#define PLAYERENGINESOUND_VTABLE 0x002bbfc0u
#define AIENGINESOUND_VTABLE     0x002bbf80u

// Registers the two. Once at boot, before a car is made.
void enginesound_install_vtables(void);

// ------------------------------------------------------------ the records

// EngineDefEvent, 16 bytes: the tables' event list. Every one on the disc
// is zero, and nothing reads them.
typedef struct EngineDefEvent {
    uint8_t use;            //  0
    uint8_t patnum;         //  1
    uint8_t pad1;           //  2
    uint8_t pad2;           //  3
    int16_t delta;          //  4
    int16_t max;            //  6
    int32_t attackdelta;    //  8
    int32_t decaydelta;     // 12
} EngineDefEvent;           // 16

// EngineDef, the 360 bytes at the head of engine.ctb and engine.ltb (6504
// bytes each), "CRDl", version 2. patchnum maps each of eight slots to an
// engineSample, -1 for none; pvoltable and pbendtable point at each slot's
// 512 bytes of volume and of bend, one per level. Only the volumes are
// read. The pointers are self-relative on the disc and ResolveTables adds
// their own address to each once; the port keeps the offsets, since a
// 32-bit field cannot hold a host's address, and adds it at the read.
typedef struct EngineDef {
    int32_t id;                         //   0
    int8_t  ver;                        //   4
    int8_t  resolved;                   //   5
    int8_t  startevent;                 //   6
    int8_t  controllerpercent;          //   7
    int16_t lowrandomtargetlevel;       //   8
    int16_t lowrandomtargetrange;       //  10
    int32_t lowrandomattacktime;        //  12
    int32_t lowrandomattackrange;       //  16
    int16_t highrandomtargetlevel;      //  20
    int16_t highrandomtargetrange;      //  22
    int32_t highrandomattacktime;       //  24
    int32_t highrandomattackrange;      //  28
    int8_t  patchnum[8];                //  32
    EngineDefEvent event[16];           //  40
    int32_t pvoltable[8];               // 296
    int32_t pbendtable[8];              // 328
} EngineDef;                            // 360

// EnginePlayOptions, 12 bytes: what VoiceAttr::Play is given.
typedef struct EnginePlayOptions {
    int16_t  vol;           //  0  0 .. 127
    int16_t  bend;          //  2  64, and not read
    float    pitch;         //  4  bSample's, an offset from 1
    uint16_t azimuth;       //  8
    uint16_t elevation;     // 10  0, and not read
} EnginePlayOptions;        // 12

// PlayerEngineSound::VoiceAttr, 200 bytes: a voice and the volume, pitch
// and azimuth last given it, so a call that changes nothing is dropped.
typedef struct EngineVoiceAttr {
    int16_t  vol;           //  0
    int16_t  bend;          //  2
    float    pitch;         //  4
    uint16_t azim;          //  8
    BSample  sample;        // 12
} EngineVoiceAttr;          // 200 (196 here)

// PlayerEngineSound::EngineSample, 20 bytes: one of the twelve patches.
typedef struct EngineSample {
    int32_t  bnkID;         //  0  -1 until Init finds the patch, then 1
    int16_t  patchtype;     //  4  1 for an "x" (exhaust) patch
    int16_t  isEnabled;     //  6  1, and nothing clears it
    BSample *sample;        //  8  0, and nothing sets it
    int32_t  detune;        // 12  SoundInfo.Detune, in cents
    float    volume;        // 16  SoundInfo.Volume
} EngineSample;             // 20

#define ENGINESOUND_PATCHES 12
#define ENGINESOUND_VOICES  16

typedef struct PlayerEngineSound {
    Sound3d   Sound;                    //    0
    struct Car *pCar;                   //   32
    int32_t   CurrThrottle;             //   36  0 .. 255, RampThrottle's
    float     RedLineRPMOffset;         //   40
    float     TopGearRPMOffset;         //   44
    BSample   NitroStartSample;         //   48
    BSample   NitroLoopSample;          //  236 (232 here)
    struct DriveTrain *pDriveTrain;     //  424 (416) never written
    float     GearShiftVolumeScale;     //  428 (420)
    int32_t   GearShiftingUp;           //  432  bool
    float     UpdateBlownRodTime;       //  436  0, and nothing reads it
    uint8_t   bHandle;                  //  440  not used
    int32_t   Volume;                   //  444  0 .. 127, Set's
    int32_t   Ratio;                    //  448  the throttle, 0 .. 127
    uint16_t  Doppler;                  //  452  not read
    uint16_t  Azim;                     //  454
    uint16_t  Seperation;               //  456  each voice of a pair's
    int8_t    Timbre;                   //  458  the e/x crossfade
    int8_t    HighestPatch;             //  459
    int16_t   ControllerLevel;          //  460
    int16_t   ControllerLevelTarget;    //  462  the RPM, 0 .. 440
    int16_t   CurrentLevel;             //  464
    int32_t   BendRange;                //  468
    int32_t   BassAdd;                  //  472
    int16_t   POVTimbre[4];             //  476  each drive camera's Timbre
    int32_t   IsStereo;                 //  484  bool: the right voices too
    int32_t   EngineBackfireBuildup;    //  488  0, and nothing reads it
    float     CurrentRPM;               //  492
    float     fEngineDuckerThrottleTime;//  496
    float     fEngineDuckerVolumeScale; //  500
    EngineVoiceAttr left[ENGINESOUND_VOICES];   //  504 (496)
    EngineVoiceAttr right[ENGINESOUND_VOICES];  // 3704 (3632)
    int8_t    delay[ENGINESOUND_VOICES];        // 6904 (6768) frames to
                                                // the right voice
    EngineDef *definitions[2];          // 6920 (6784) engine.ctb's, .ltb's
    EngineDef *RPMdef;                  // 6928  never written
    EngineSample engineSample[ENGINESOUND_PATCHES]; // 6932
    int32_t   CurrAudioMode;            // 7172
} PlayerEngineSound;                    // 7176

// 268 bytes. The demo's was 256; retail added the three at the end, which
// have no names on the disc: those here are the port's.
typedef struct AIEngineSound {
    Sound3d   Sound;                    //   0
    struct Car *pCar;                   //  32
    BSample   EngineSample;             //  36
    float     EnginePitchBase;          // 224 (220 here) -0.4 .. 0
    float     StartLineTargetPitch;     // 228  -1 until the first rev
    float     StartLineCurrPitch;       // 232
    Average   RPMAverage;               // 236  twenty samples
    int32_t   CurrGear;                 // 252
    int32_t   GearFrames;               // 256  updates since the change
    float     SmoothRPM;                // 260
    float     GearVolumeScale;          // 264
} AIEngineSound;                        // 268

// gp-16268: the last player engine made. Written, and nothing reads it.
extern PlayerEngineSound *LastPlayerEngineSound;

// ---------------------------------------------------------- engine_sound

// 0x00211d90 and 0x00211de0: carsound.h's gCreatePlayerEngineFn and
// gCreateAIEngineFn.
Sound3d *enginesound_create_player(struct Car *c);
Sound3d *enginesound_create_ai(struct Car *c);

// ----------------------------------------------------------- VoiceAttr

// 0x0020fad0. Plays, sound on, at vol / 127 from the centre, then turns
// to the azimuth whether it played or not.
void enginevoice_play(EngineVoiceAttr *v, const EnginePlayOptions *o);
// 0x0020fb78. A voice with a volume is turned down -- smoothly, so it
// stops some frames later -- and one at 0 is stopped.
void enginevoice_stop(EngineVoiceAttr *v);
// 0x0020fb98. At most 15 steps towards `vol` a call.
void enginevoice_set_volume(EngineVoiceAttr *v, int16_t vol);
void enginevoice_set_pitch(EngineVoiceAttr *v, float pitch);   // 0x0020fc18
void enginevoice_set_azimuth(EngineVoiceAttr *v, uint16_t a);  // 0x0020fc48

// ---------------------------------------------------- PlayerEngineSound

void playerenginesound_construct(PlayerEngineSound *s, struct Car *c);
void playerenginesound_destroy(PlayerEngineSound *s, int32_t flags);
// 0x0020ffc0. The car's twelve patches, the voices locked, the two tables
// read. It quiets the menu sounds and lets the sound driver run twice
// first, sixteen milliseconds apart, so their voices are free.
void playerenginesound_init(PlayerEngineSound *s);
void playerenginesound_deactivate_sound(PlayerEngineSound *s);  // 0x00210400
void playerenginesound_activate_sound(PlayerEngineSound *s);    // 0x00210408
void playerenginesound_mute(PlayerEngineSound *s, int32_t on);  // 0x00210410
void playerenginesound_resolve_tables(PlayerEngineSound *s);    // 0x002105d0
void playerenginesound_ramp_throttle(PlayerEngineSound *s);     // 0x002106c8
void playerenginesound_update_gear_shift_effect(PlayerEngineSound *s);
void playerenginesound_update_to_red_line_rpm(PlayerEngineSound *s,
                                              float *rpm);       // 0x00210880
void playerenginesound_update_nitro_effect(PlayerEngineSound *s,
                                           float volume, uint16_t azimuth,
                                           float pitch);         // 0x00210950
void playerenginesound_update_engine_ducker(PlayerEngineSound *s);
void playerenginesound_update_engine(PlayerEngineSound *s);     // 0x00210bf8
// 0x00211390, slot 24.
void playerenginesound_update(PlayerEngineSound *s, float volume,
                              uint16_t azimuth, float pitch);
// 0x002116d8. The distance and the azimuth are passed and not read.
void playerenginesound_set(PlayerEngineSound *s, int32_t volume,
                           int32_t ratio, int32_t throttle, int32_t dist2,
                           int32_t doppler, int32_t azimuth, float facing,
                           int32_t pov);

// -------------------------------------------------------- AIEngineSound

void aienginesound_construct(AIEngineSound *s, struct Car *c); // 0x002117c8
void aienginesound_destroy(AIEngineSound *s, int32_t flags);   // 0x00212418
void aienginesound_update(AIEngineSound *s, float volume,
                          uint16_t azimuth, float pitch);      // 0x002118a0
void aienginesound_mute(AIEngineSound *s, int32_t on);         // 0x00211a80
// 0x00211a90. A static buffer: "AIEngine0" with the car's number added to
// the digit, or 0 for a traffic car's type.
const char *aienginesound_get_engine_sample_name(AIEngineSound *s);
float aienginesound_compute_rpm_pitch_shift(AIEngineSound *s); // 0x00211b10
float aienginesound_compute_start_line_rpm_pitch_shift(
    AIEngineSound *s);                                         // 0x00211c40
void aienginesound_deactivate_sound(AIEngineSound *s);         // 0x00211d58
void aienginesound_activate_sound(AIEngineSound *s);           // 0x00211d60

#endif
