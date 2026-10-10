#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "bsound.h"
#include "jukebox.h"

// sound -- the game's own sound module over bSound: retail's Sound.obj
// (0x001ae018-0x001afbc0), the namespace `sound` and the free functions
// round it. It brings the driver up, loads and unloads the sound regions
// (the banks, by name), runs the per-frame update in its order, muffles
// every category's volume when a zone, the post-race or a speech asks it
// to, and mutes the lot for the pause menu and the replays.
//
//   UpdateVolumeMuffler                   0x001ae110
//   GetInGameSample                       0x001ae280
//   the region loader                     0x001ae340
//   SoundDriverCallback                   0x001ae3c8   bSound's client
//   InitializeSoundDriver                 0x001ae608
//   LoadSoundRegionsInGame                0x001ae798
//   LoadSoundRegionsFrontEnd              0x001ae9a0
//   RealIsSoundRegionLoadingComplete      0x001af290
//   IsSoundRegionLoadingComplete          0x001af2e8
//   the region poll                       0x001af308   sound::Update's first
//   UnLoadSoundRegions                    0x001af420
//   sound::Update                         0x001af4c0
//   ScaleCategoryVolumes                  0x001af638
//   MuteCarSounds                         0x001af6f8
//   PlayCommonRegionSample                0x001af760
//   sound::Mute / sound::MuteReplay       0x001af850 / 0x001af940
//   the two random helpers                0x001af9a0 / 0x001af9c0
//   sound::SetAudioMode / GetAudioMode    0x001af9e0 / 0x001afa10
//   TriggerFinishLineSound                0x001afb38
//
// sound::jukebox's half -- Start, Stop, SetSelection, the saved volumes,
// the default volumes -- is jukebox.c's, and this module holds a JBSound
// for it. TriggerTimerWarningSound is hudrender.c's, and the localized
// speech files (0x001ae4d8/0x001ae5e8) and the wedge's creation are
// sedwedge.c's. Not ported: IsNISPlaying (0x001ae098) and GetFrontEndSample
// (0x001ae2d8), which nothing calls; 0x001afa18, the 0.7 FlailerSlider's
// constructor asks for.
//
// The modules sound::Update and Mute call -- the speech, the SED wedge,
// the speech noise, the collision sounds, the sound scape, the car sounds,
// the chopper's, the one-shots -- are SoundHooks, which main.c binds; one
// left NULL does nothing. So is what the module reads of the game, so
// tools/sound_check.py can run sound.c next to retail's image.
//
// Written up in docs/formats/sound.md; checked by tools/sound_check.py.

// The regions the module loads itself, 0x003139a8: four of 36 bytes, a
// name and whether bSound has said it is in.
#define SOUND_REGIONS 4
typedef struct SoundRegionSlot {
    char    name[32];
    int32_t loaded;             // 32
} SoundRegionSlot;

typedef void (*SoundDoneFn)(intptr_t param);

typedef struct SoundHooks {
    void* ctx;

    // -- the game
    int      (*game_state)(void* ctx);  // gp-21420, GameFlowState; 3 IN_FRONTEND
    int      (*paused)(void* ctx);      // IsGameFlowPaused, 0x001680b8
    float    (*dt)(void* ctx);          // gp-19560, WorldTimeElapsed
    uint32_t (*vblank)(void* ctx);      // gp-19616, the VBlank count
    void     (*service_files)(void* ctx);   // bServiceFileSystem
    // bFileExists, on retail's own path: "sound\\NAME.msh".
    int      (*file_exists)(void* ctx, const char* path);
    // eFlashScreen (0x001083f0).
    void     (*flash)(void* ctx, int r, int g, int b, const char* why,
                      float seconds);
    // pRaceCoordinator's state (gp-22216, +0), or -1 with no coordinator.
    int      (*race_state)(void* ctx);
    // Player::NumPlayers (gp-20920), and pPlayersByIndex[i]'s (gp-20928)
    // bZoneMuffleSound (+144), nZoneCurrent (+88) and fZoneMuffleVolume
    // (+148).
    int      (*num_players)(void* ctx);
    void     (*player_zone)(void* ctx, int i, int* muffle, int* zone,
                            float* volume);
    // CurrentTrackInfo's SoundRegion (gp-21952, +132), or NULL with no
    // track.
    const char* (*track_region)(void* ctx);
    // TheRaceParameters.GetDriverInfoByDriverNumber(i) (0x001edb40):
    // NULL when there is none or its EliminatedRank (retail +0) is above
    // 0, else its car type's Sound (CarTypeInfos, gp-20616, +816).
    const char* (*driver_region)(void* ctx, int driver);
    // pCurrentWorld's CarList (gp-22120, +0): how many, and each car's
    // pBaseCarSound (retail +2132), which may be NULL.
    int      (*num_cars)(void* ctx);
    void*    (*car_sound)(void* ctx, int i);
    // pCurrentWorld && pCurrentWorld->Helicopter (+24). Retail reads
    // pCurrentWorld without a test in Mute and MuteReplay.
    int      (*helicopter)(void* ctx);
    // Joylog: Joylog_ReplayingFlag (gp-20668), GetData (0x00183358),
    // AddData (0x00183498).
    int      (*joylog_replaying)(void* ctx);
    int32_t  (*joylog_get)(void* ctx, int bits, int channel);
    void     (*joylog_add)(void* ctx, int32_t value, int bits, int channel);
    // What SetPath is handed: retail's "sound\\"; the card's SOUND
    // directory on the 3DS, where bsnd finds NAME.SBK.
    const char* sound_path;
    // The port's: a region that cannot come in -- no file, no ndsp, no
    // room -- counts as in, silent, and the next is asked for. Retail
    // waits for it until the 20-second "Hang loading sound", and asks
    // for none after it. tools/sound_check.py runs with this 0.
    int skip_missing;

    // -- the modules sound calls, each bound by main.c
    void (*speech_update)(void* ctx);           // speech::mgr_t::update
    void (*speech_mute)(void* ctx, int on);     // speech::mgr_t::Mute
    void (*speech_flush)(void* ctx);            // speech::mgr_t::FlushQueue
    // speech::mgr_t's previousSedPlaybackState (+1452).
    int  (*speech_sed_playing)(void* ctx);
    void (*sed_create)(void* ctx);              // new cSEDWedge, gp-19016
    void (*sed_update)(void* ctx);              // cSEDWedge::Update
    void (*noise_request)(void* ctx);           // SpeechNoise::RequestSamples
    void (*noise_unload)(void* ctx);            // SpeechNoise::UnLoadSamples
    void (*noise_update)(void* ctx);            // SpeechNoise::Update
    void (*noise_mute)(void* ctx, int on);      // SpeechNoise::Mute
    void (*collision_register)(void* ctx);      // collision_sound::Register
    void (*collision_unregister)(void* ctx);
    void (*collision_update)(void* ctx);
    void (*collision_mute)(void* ctx, int on);
    void (*scape_update)(void* ctx);            // sound_scape::Update
    void (*scape_mute)(void* ctx, int on);
    void (*car_sounds_update)(void* ctx);       // UpdateCarSounds
    // BaseCarSound's virtual Mute (vtable +32), on a car_sound.
    void (*car_sound_mute)(void* ctx, void* sound, int on);
    void (*chopper_update)(void* ctx);          // Chopper::UpdateSound
    void (*chopper_mute)(void* ctx, int on);    // Chopper::Mute
    void (*oneshot_init)(void* ctx);            // sound3d_oneshot::Init
    void (*oneshot_close)(void* ctx);
    void (*oneshot_update)(void* ctx);
    void (*oneshot_mute)(void* ctx, int on);
} SoundHooks;

// Sound.obj's statics, retail's places alongside.
typedef struct SoundModule {
    BSound*        bsound;          // gp-13696, bSound's instance
    BsndDriver*    driver;          // what bSound::Initialize brings up
    JBSound*       jb;              // sound::jukebox's, MusicEnabled and all
    const uint8_t* audioOptions;    // Fred's DataAudioOptionsScreen
    const SoundHooks* hooks;
    SoundRegionSlot region[SOUND_REGIONS];  // 0x003139a8
    BRegion*       inGameRegion;    // gp-19012, GetInGameSample's
    BRegion*       frontEndRegion;  // gp-19000, GetFrontEndSample's
    int32_t        commonLoaded;    // gp-19020
    SoundDoneFn    done;            // gp-19064
    intptr_t       doneParam;       // gp-19060
    int32_t        loading;         // gp-19056
    uint32_t       loadStart;       // gp-19052, the ticker
    uint32_t       lastUpdate;      // gp-18900, the ticker
    float          muffleCurrent;   // gp-19036, 1.0
    float          muffleTarget;    // gp-19032, 1.0
    float          lastScale;       // gp-18896, -1.0
    uint32_t       seed;            // gp-19068
    int32_t        audioMode;       // gp-18892, 1 (stereo)
    int32_t        speechEnabled;   // gp-16552, 1
    int32_t        printVoiceUsage; // gp-18904, a debug flag nothing sets
} SoundModule;

// The statics' values in the image, and the module sound_get answers.
// `driver` may be NULL (no ndsp): bSound then stays down, as retail's
// does when bSnd_Initialize fails.
void sound_init(SoundModule* m, BSound* bs, BsndDriver* driver, JBSound* jb,
                const uint8_t* audioOptions, const SoundHooks* hooks);
SoundModule* sound_get(void);
// What SetPath is handed: the hooks' sound_path, or SOUND_DIR without one.
// cSEDWedge::PlaySentence puts it back after its sentence.
const char* sound_get_path(const SoundModule* m);

// 0x001ae608. With SoundEnabled: bSound initialized with this module's
// callback, stereo, the path set and "common" loaded -- waited for, frame
// by frame -- then the jukebox's cartridge, the SED wedge and the default
// volumes. The port ends the wait when nothing is pending, so a card
// without COMMON.SBK boots silent instead of hanging.
void sound_initialize_driver(SoundModule* m);

// 0x001ae3c8, bSound's client: a region is in; the next one asked for
// is loaded.
void sound_driver_callback(uint32_t event, void* what, void* data);

// 0x001ae798 and 0x001ae9a0. `done(param)` is called from sound_update
// once every region asked for is in -- or after 20 seconds of waiting.
void sound_load_regions_in_game(SoundModule* m, SoundDoneFn done,
                                intptr_t param);
void sound_load_regions_front_end(SoundModule* m, SoundDoneFn done,
                                  intptr_t param);
int  sound_real_is_region_loading_complete(const SoundModule* m);
int  sound_is_region_loading_complete(const SoundModule* m);
void sound_unload_regions(SoundModule* m);                // 0x001af420

// 0x001af4c0, once a frame from the main loop.
void sound_update(SoundModule* m);
void sound_update_volume_muffler(SoundModule* m);         // 0x001ae110
// 0x001af638: categories 0, 1, 2, 5 and 4 to their saved volumes times
// `scale`, and the speech's, scaled only if `speechToo`.
void sound_scale_category_volumes(SoundModule* m, float scale, int speechToo);

void sound_mute(SoundModule* m, int32_t on);              // 0x001af850
void sound_mute_replay(SoundModule* m, int32_t on);       // 0x001af940
void sound_mute_car_sounds(SoundModule* m, int32_t on);   // 0x001af6f8

// 0x001ae280: the "InGame" region's sample, the region looked up once.
BSample* sound_get_in_game_sample(SoundModule* m, const char* name);
// 0x001af760: the common region's sample, played as a menu effect.
void sound_play_common_region_sample(SoundModule* m, const char* name,
                                     float volume);
void sound_trigger_finish_line_sound(SoundModule* m);     // 0x001afb38

int32_t sound_random_int(SoundModule* m, int32_t range);  // 0x001af9a0
float   sound_random_float(SoundModule* m, float range);  // 0x001af9c0
void    sound_set_audio_mode(SoundModule* m, int32_t mode);
int32_t sound_get_audio_mode(const SoundModule* m);
