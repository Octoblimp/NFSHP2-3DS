// playerinit -- the Player's lifetime: its constructor and destructor, and
// the two RaceCoordinator calls around each race. The addresses are
// retail's.
//
// This is step 8a: the constructor (0x001751d8), the destructor
// (0x00175bf0), InitForRace (0x00181920), PredetermineNisNumbers
// (0x001819e0), CleanupAfterRace (0x00181970) and CleanUpJumpCam
// (0x00176ab0). RaceCoordinator::InitForRace builds both players
// (bMalloc(2752) each), and InitPlayers hands each its car.
//
// The HUD, the NIS managers, the samples and the joystick handlers are
// seams, NULL until their classes are ported, and the port skips a NULL
// one. A NULL constructor seam allocates nothing and leaves its pointer
// NULL, as playercam.c's movers do.
//
// They sit apart from player.c because they reach the topology, the
// Average, the drivers and the camera functions, and player.c goes into
// harnesses that need none of those.
//
// Written up in docs/formats/player.md; checked on retail's image by
// tools/player_check.py.

#ifndef PLAYERINIT_H
#define PLAYERINIT_H

#include <stdint.h>

#include "joystick.h"
#include "player.h"

struct bSample;
struct Car;
struct FlailerObjectChunk;
struct HudAnimator;
struct NisManager;
struct VisibleDrivingLine;

// 0x001751d8, on memory the caller allocated (2752 bytes in retail).
// Registers the player in PlayerPlayersByIndex and PlayerPlayersByNumber,
// links the two players' pOtherPlayer once there are two, copies
// TheRaceParameters' settings for `number`, and builds what it owns: the
// topology, the NIS overlay, the NIS manager, the speed Average, the jump
// cam's CameraDataItems and its 32 FOV entries. The views come from
// NumPlayerCars: with one player car the view is 1 and the mirror 3, and
// with two the views are 1 and 2 by number and there is no mirror. Like
// retail it leaves alone what it does not write: the tach point list,
// two of the flailer words, the live-split arrays, strEventTitle,
// DriftTime, EyeVerts and BankVerts, the first auto-replay word, the
// pursuit positions and PursuitOffsetState.
struct Player *player_init(struct Player *p, JoystickPort port,
                           int32_t number);

// 0x00175bf0. Takes the HUD down and deletes what the player owns, then
// takes it out of the two tables and sets bResetGlare. `flags` bit 0 frees
// the player too.
void player_destroy(struct Player *p, int32_t flags);

// 0x00181920. The car's player becomes this and MyCar the car, which takes
// the settings' DrivingStyle as its DriverMode. A car under REAL_CONTROL
// has its driver take the settings' TransmissionType. Then
// PredetermineNisNumbers.
void player_init_for_race(struct Player *p, struct Car *c);

// 0x001819e0. CreateRandomNisArray for NIS type 1, TicketNisIndex -1, then
// for type 2 and ArrestNisIndex -1.
void player_predetermine_nis_numbers(struct Player *p);

// 0x00181970. Undoes InitForRace, in retail's order: AutoPilotOff (an
// empty function in retail), RadialBlurOff for the player's view,
// RemoveCameraMovers, the NIS stopped and its overlay finished while the
// manager plays one, SetInputMode(0), and MyCar and the car's player
// cleared. The demo cleared MyCar first.
void player_cleanup_after_race(struct Player *p);

// 0x00176ab0. Deletes pJumpCamRoute, if any, and clears it. Car's
// FinishMovement calls it through gPlayerCleanUpJumpCamFn.
void player_clean_up_jump_cam(struct Player *p);

// cPlayerSettings::ResetToDefaults, 0x001edf90. Rumble 1 and the other
// three leading bytes 0; the POV 1, or with SkipFE PlayerSkipFEPOVIndex;
// bytes 5-7 0; CameraSpring 0, Lookback 1, PreferredHudFeatures 853, the
// name "PLAYER"; New44 and New40 1, then the two records 0.
void player_settings_reset_to_defaults(cPlayerSettings *s);

// TheRaceParameters.PlayerSettings, retail's 0x0031ab24 (+652), 48 bytes
// each: what the constructor copies. All zeroes on the disc;
// RaceParameters::InitWithDefaults resets both.
extern cPlayerSettings RaceParametersPlayerSettings[2];

// The byte at gp-23172, 1 on the disc: ResetToDefaults' POV under SkipFE.
extern uint8_t PlayerSkipFEPOVIndex;

// ---------------------------------------------------------------- the seams

// The constructor's. NisManager's constructor (0x001b0fe0) on bMalloc(320,
// "NisManager", 0, 16), named "Player%d" for 1 - number; it returns the
// manager. GetInGameSample (0x001ae280). FindFlailerObject (0x00143d50),
// whose type 2 is a bitmap, and FlailerObjectChunk::GetTopLeft
// (0x00140978). Retail calls GetTopLeft without testing the object; the
// port skips a NULL one, and reads 0 for both then or with the seam NULL.
extern struct NisManager *(*gNewNisManagerFn)(void *mem, const char *name,
                                              int32_t number);
extern struct bSample *(*gGetInGameSampleFn)(const char *name);
extern struct FlailerObjectChunk *(*gFindFlailerObjectFn)(uint32_t screen,
                                                          uint32_t object,
                                                          int32_t type);
extern void (*gFlailerChunkGetTopLeftFn)(struct FlailerObjectChunk *o,
                                         float *x, float *y);

// The destructor's. Player::ResetFlailerMovement (0x0017bd20) and
// SetHudFeatures (0x001796b0), which it calls with 0. The zone sample's
// virtual destructor with flag 3 (its vtable is at +184).
// VisibleDrivingLine's destructor (0x00175030), NisManager's (0x001b1110)
// and HudAnimator's (0x0023b168), each with flag 3. The two PreviewRoutes
// go through playercam.h's gPreviewRouteDeleteFn.
extern void (*gPlayerResetFlailerMovementFn)(struct Player *p);
extern void (*gPlayerSetHudFeaturesFn)(struct Player *p, uint32_t features);
extern void (*gSampleDeleteFn)(struct bSample *s);
extern void (*gVisibleDrivingLineDeleteFn)(struct VisibleDrivingLine *l);
extern void (*gDeleteNisManagerFn)(struct NisManager *m);
extern void (*gHudAnimatorDeleteFn)(struct HudAnimator *a);

// The race's. Player::CreateRandomNisArray (0x00181a28), NIS type 1 for
// tickets and 2 for arrests. The NisManager's word at +68, which is set
// while it plays a NIS, and NisManager::Stop (0x001b1388). Player::
// SetInputMode (0x001776b0), which moves the joystick handlers.
extern void (*gPlayerCreateRandomNisArrayFn)(struct Player *p, int32_t type);
extern int32_t (*gNisManagerIsPlayingFn)(const struct NisManager *m);
extern void (*gNisManagerStopFn)(struct NisManager *m);
extern void (*gPlayerSetInputModeFn)(struct Player *p, int32_t mode);

#endif
