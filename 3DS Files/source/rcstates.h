// rcstates -- RaceCoordinator.obj from retail: the states a race runs
// through up to its finish, and what they call.
//
//   RaceCoordinator::RCStateNoneCallback            0x0014a668  396 bytes
//   RaceCoordinatorJoystickHandler                  0x0014a7f8   32 bytes
//   RaceCoordinator::ResumeDemoCameras              0x0014a818   92 bytes
//   RaceCoordinator::SuspendDemoCameras             0x0014a878   68 bytes
//   RaceCoordinator::RCStateCameraFlybyCallback     0x0014abe0  276 bytes
//   RaceCoordinator::RCStatePreRaceCallback         0x0014acf8  392 bytes
//   RaceCoordinator::RCStateRaceInProgressCallback  0x0014ae80  648 bytes
//   Animate321GoElement                             0x0014b108  344 bytes
//   RaceCoordinator::DisplayCountdownNumber         0x0014b260  376 bytes
//   RaceCoordinator::TheRaceHasFinished             0x0014bce0  248 bytes
//   RaceCoordinator::RequestUnPause                 0x00174e00   12 bytes
//   RaceCoordinator::RequestPause                   0x001832a8   12 bytes
//   FrontendDatabase's record times, no symbol      0x001842a8  112 bytes
//
// Step 8f. Step 8g's rcpost.c has the pause and the post-race, 72g-3's
// rcreplay.c the instant replay and 72g-4's rcauto.c the auto replay. The
// two demos are later slices'; their entries in gRCStateCallbacks stay
// NULL until then.
// docs/formats/race-coordinator.md has the decode.

#ifndef RCSTATES_H
#define RCSTATES_H

#include <stdint.h>

#include "joyeventid.h"
#include "joystick.h"
#include "race.h"
#include "racecoord.h"

struct AnimatedDriver;
struct bSample;
struct Car;
struct FlailerObjectChunk;
struct Player;
struct ReplayManager;

// eContinueRaceType (t4230), which TheRaceHasFinished gives EndGameScreens.
typedef int32_t eContinueRaceType;
#define CONTINUE_RACE_TYPE_NONE       ((eContinueRaceType)0)
#define CONTINUE_RACE_TYPE_NEXT_RACE  ((eContinueRaceType)1)
#define CONTINUE_RACE_TYPE_RESTART    ((eContinueRaceType)2)

// UnPauseReasonType (t1007), RequestUnPause's parameter.
typedef int32_t UnPauseReasonType;
#define UNPAUSE_REASON_NONE            ((UnPauseReasonType)0)
#define UNPAUSE_REASON_RESUME_RACE     ((UnPauseReasonType)1)
#define UNPAUSE_REASON_RESTART_RACE    ((UnPauseReasonType)2)
#define UNPAUSE_REASON_QUIT_RACE       ((UnPauseReasonType)3)
#define UNPAUSE_REASON_INSTANT_REPLAY  ((UnPauseReasonType)4)

// The countdown's Flailer screen and its three numbers, as
// DisplayCountdownNumber names them.
#define RC_COUNTDOWN_SCREEN  0x936ace42u
#define RC_COUNTDOWN_3       0x93667af3u
#define RC_COUNTDOWN_2       0x93667af2u
#define RC_COUNTDOWN_1       0x93667af1u

// ------------------------------------------------------------ the states

// The four states this slice ports, as gRCStateCallbacks holds them. Each
// answers whether it took the message.
//
// NONE takes ACTIVATE, UNACTIVATE and TICK and does nothing with them.
// RESTART_RACE is CleanupAfterRace, InitForRace, sound::Mute(false), the
// record times, the display settings, and the music's delayed start put
// off. NEXT_RACE is SetupNextRace when the parameter is set, the record
// times, the display settings, and the flow to UNLOADING_TRACK_SPECIFIC
// with LOADING_TRACK_SPECIFIC pending. QUIT_RACE is the flow to
// UNLOADING_TRACK_SPECIFIC with nothing pending.
int32_t rc_state_none_callback(RaceCoordinator *rc, RCMessage msg,
                               int32_t param);

// CAMERA_FLYBY. ACTIVATE makes the flyby camera if there is none and turns
// the start-race screens on; UNACTIVATE turns them off. TICK, once the
// flyby is finished, and SKIP set the stage to PRERACE and go to PRERACE.
// REQUEST_PAUSE keeps the port and the state and goes to PAUSE.
int32_t rc_state_camera_flyby_callback(RaceCoordinator *rc, RCMessage msg,
                                       int32_t param);

// PRERACE. ACTIVATE makes the prerace camera if there is none and deletes
// the flyby's. UNACTIVATE cancels every car's driver animations and
// unloads the prerace animation. TICK on the PRERACE stage, once the
// prerace camera is finished, and SKIP set the stage to COUNTDOWN and go to
// RACE_IN_PROGRESS. REQUEST_PAUSE as the flyby.
int32_t rc_state_prerace_callback(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param);

// RACE_IN_PROGRESS. ACTIVATE deletes the prerace camera, UNACTIVATE puts
// countdown number 0 up. TICK puts the countdown up, marks the replay's
// beginning of time and starts the music six seconds on once the stage is
// RACING, finishes the race once every player has finished and the last
// one's finish animation has run, and with two players turns a finished
// player's view to the other's car. SKIP finishes the race once every
// player has finished. REQUEST_PAUSE as the flyby; REQUEST_AUTO_REPLAY
// goes to AUTO_REPLAY; NEXT_RACE goes to NONE and sends NEXT_RACE on.
// TAKE_AUTOSNAPSHOT is taken and does nothing.
int32_t rc_state_race_in_progress_callback(RaceCoordinator *rc,
                                           RCMessage msg, int32_t param);

// rcstates.c defines racecoord.h's gRCStateCallbacks with the four above
// and rcpost.h's two at their RCStates; the other four stay NULL for now.

// --------------------------------------------------------- the methods

// 0x0014b260. Countdown number `n` (racefinish.h's), at the race's
// progress. At the GO, before 0.8, the "CountDownHigh" sample unless it is
// playing. The countdown screen shows only for 1, 2 and 3 up to a
// progress of 1.0, with the three numbers each animated over its quarter
// (Animate321GoElement, 0x0014b108); otherwise the screen is hidden.
void racecoordinator_display_countdown_number(RaceCoordinator *rc,
                                              int32_t n);

// 0x0014bce0. The replay's end of time, the abort check, the finish
// simulated, the results recorded, the frontend told, and EndGameScreens
// made on what comes next: another race, nothing for a multi-track event,
// or a restart. Then POSTRACE. Retail's demo-disc branch is not ported:
// DemoDiscManager is never active on the retail disc.
void racecoordinator_the_race_has_finished(RaceCoordinator *rc);

// 0x0014a7f8. JOY_EVENT_SKIP_DEMO_MODE posts SKIP to pRaceCoordinator.
void racecoordinator_joystick_handler(JoystickPort port, JoyEvent ev,
                                      uint8_t value, void *obj);

// 0x001832a8 and 0x00174e00: REQUEST_PAUSE with the port, and
// REQUEST_UNPAUSE with the reason, posted.
void racecoordinator_request_pause(RaceCoordinator *rc, int32_t port);
void racecoordinator_request_unpause(RaceCoordinator *rc,
                                     UnPauseReasonType reason);

// 0x0014a818 and 0x0014a878. A demo camera on the first player's car, made
// if there is none; and the demo camera deleted.
void racecoordinator_resume_demo_cameras(RaceCoordinator *rc);
void racecoordinator_suspend_demo_cameras(RaceCoordinator *rc);

// ---------------------------------------------------------------- seams
//
// Shared with other files: playerinit.h's gGetInGameSampleFn and
// gFindFlailerObjectFn, trackflow.h's gSetFlailerScreenVisibilityFn and
// gUnloadResourceFileFn, racecoord.h's gFindResourceFileByNameFn and
// playercam.h's gCameraCoordinatorDeleteFn. Each one below does nothing
// when NULL, and answers 0 unless it says otherwise.

// sound::Mute (0x001af850).
extern void (*gSoundMuteFn)(int32_t on);

// TheFrontendDatabase's (0x002fc050): SetupNextRace (0x00184270), whose
// answer nothing reads; SetRecordTimesToBeat (0x00184490), for each player
// car; CheckForAbortion (0x00187518); TheRaceIsOver (0x001875a0);
// IsThereAnotherRace (0x00184210) and IsMultiTrack (0x00184248).
extern void (*gFEDSetupNextRaceFn)(void);
extern void (*gFEDSetRecordTimesToBeatFn)(int32_t player);
extern void (*gFEDCheckForAbortionFn)(void);
extern void (*gFEDTheRaceIsOverFn)(Race *r);
extern int32_t (*gFEDIsThereAnotherRaceFn)(void);
extern int32_t (*gFEDIsMultiTrackFn)(void);

// TheFrontendDatabase+332 in retail: the display settings RESTART_RACE and
// NEXT_RACE copy to TheRaceParameters'. NULL copies nothing.
extern const tGlobalDisplaySettings *gFEDGlobalDisplaySettings;

// sound::jukebox's DelayedStart (0x001aec88), and its timer (gp-19028),
// which RESTART_RACE sets to 9e9 so the music waits for the next start.
// NULL stores nothing.
extern void (*gJukeboxDelayedStartFn)(float seconds);
extern float *gJukeboxDelayedStartTimer;

// ChangeGameFlow (0x001680d8): the desired and the pending GameFlowState.
extern void (*gChangeGameFlowFn)(int32_t desired, int32_t pending);

// The camera coordinators, each made on a bMalloc of its size from
// racecoordinator.cpp's line: FlyByCameraCoordinator (0x0019abd8, 40
// bytes), PreRaceCameraCoordinator (0x0019ad78, 188) and
// DemoCameraCoordinator (0x0019a440, 52, on a car). With a constructor
// NULL nothing is allocated and the field stays NULL.
extern void *(*gFlyByCameraCoordinatorCtorFn)(void *mem, int32_t a);
extern void *(*gPreRaceCameraCoordinatorCtorFn)(void *mem, int32_t a);
extern void *(*gDemoCameraCoordinatorCtorFn)(void *mem, int32_t a,
                                             struct Car *car);
#define FLYBY_CAMERA_COORDINATOR_SIZE    40
#define PRERACE_CAMERA_COORDINATOR_SIZE  188
#define DEMO_CAMERA_COORDINATOR_SIZE     52

// FlyByCameraCoordinator::IsFinished (0x0019ac40), and the word at +184 of
// the PreRaceCameraCoordinator that the prerace TICK reads. Retail reads
// both from whatever the field holds; the port reads a NULL seam or a NULL
// camera as finished, so a race without the camera goes on.
extern int32_t (*gFlyByCameraIsFinishedFn)(void *coord);
extern int32_t (*gPreRaceCameraIsFinishedFn)(void *coord);

// EnableStartRaceScreens (0x001e39b0) and DisableStartRaceScreens
// (0x001e39c0): tStartRaceScreenManager's Enable and Disable on
// TheStartRaceScreenManager (0x0031a3e0).
extern void (*gEnableStartRaceScreensFn)(void);
extern void (*gDisableStartRaceScreensFn)(void);

// AnimatedDriver::CancelAllAnimations (0x001a9b30), on each car's driver.
extern void (*gAnimatedDriverCancelAllAnimationsFn)(
    struct AnimatedDriver *d);

// ReplayManager's: the Timer at retail's +92 (its BeginningOfTime; replay.h
// has the demo's head, where +92 is EndOfTime), MarkTheBeginningOfTime
// (0x0013d6f8) and MarkTheEndOfTime (0x0013d868). With no ReplayManager
// the TICK neither marks the beginning nor starts the music: retail
// dereferences pReplayManager there unchecked.
extern int32_t (*gReplayGetBeginningOfTimeFn)(const struct ReplayManager *rm);
extern void (*gReplayMarkTheBeginningOfTimeFn)(struct ReplayManager *rm);
extern void (*gReplayMarkTheEndOfTimeFn)(struct ReplayManager *rm);

// Player::BeginDemoCameras (0x00176868): the player's view on a car.
extern void (*gPlayerBeginDemoCamerasFn)(struct Player *p, struct Car *car);

// EndGameScreens' constructor (0x001dcd28) on bMalloc(72,
// "EndGameScreens", 0, 16). NULL allocates nothing and leaves
// pEndGameScreens NULL.
extern struct EndGameScreens *(*gEndGameScreensCtorFn)(
    void *mem, eContinueRaceType type);
#define END_GAME_SCREENS_SIZE 72

// bSample::IsPlaying (0x00274410) and Play(float, float, float)
// (0x00274080).
extern int32_t (*gSampleIsPlayingFn)(struct bSample *s);
extern void (*gSamplePlayFn)(struct bSample *s, float volume, float a,
                             float b);

// The countdown numbers' Flailer calls: the visibility byte (+41) of an
// object FindFlailerObject found, FlailerSetVisibility (0x00144968; 1 is
// visible), FlailerSetAlpha (0x001448e8) and FlailerScaleAboutCenter
// (0x001445b0).
extern int32_t (*gFlailerObjectVisibilityFn)(struct FlailerObjectChunk *o);
extern void (*gFlailerSetVisibilityFn)(uint32_t screen, uint32_t object,
                                       int32_t visibility);
extern void (*gFlailerSetAlphaFn)(uint32_t screen, uint32_t object,
                                  int32_t alpha);
extern void (*gFlailerScaleAboutCenterFn)(uint32_t screen, uint32_t object,
                                          float scale);

#endif
