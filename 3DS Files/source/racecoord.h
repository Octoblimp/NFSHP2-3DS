// racecoord -- RaceCoordinator.obj from retail: the coordinator's lifetime,
// from the constructor through InitForRace to the destructor's
// CleanupAfterRace, and the message queue its states run on.
//
//   RaceCoordinator::ChangeState                  0x00149520   84 bytes
//   RaceCoordinator::ExecuteQueuedMessages        0x00149578  216 bytes
//   RaceCoordinator::SendMessage                  0x00149650  132 bytes
//   RaceCoordinator::PostMessage                  0x001496d8   96 bytes
//   RaceCoordinator::RaceCoordinator              0x00149738  284 bytes
//   RaceCoordinator::~RaceCoordinator             0x00149858  148 bytes
//   RaceCoordinator::InitForRace                  0x00149988  512 bytes
//   RaceCoordinator::CleanupAfterRace             0x00149b88  304 bytes
//   RaceCoordinator::CleanupPlayers               0x00149d78   92 bytes
//   RaceCoordinator::CleanupCars                  0x0014a5f0  116 bytes
//   SetAIDriverModesFromPlayers                   0x001cd240  456 bytes
//   RaceParameters::GetDriverInfoByDriverNumber   0x001edb40  132 bytes
//
// Step 8e. The ten state callbacks, which the queue calls, are later
// slices' and seams here. docs/formats/race-coordinator.md has the decode.

#ifndef RACECOORD_H
#define RACECOORD_H

#include <stdint.h>

#include "blist.h"
#include "bvector.h"
#include "race.h"

struct BSlotPool;
struct Car;
struct Chopper;
struct DriverInfo;
struct EndGameScreens;
struct PauseMenu;
struct ReplayManager;

// RCMessage, from the .mdebug enum (t1005).
typedef int32_t RCMessage;
#define RC_MSG_NONE             ((RCMessage)0)
#define RC_ACTIVATE             ((RCMessage)1)
#define RC_UNACTIVATE           ((RCMessage)2)
#define RC_TICK                 ((RCMessage)3)
#define RC_SKIP                 ((RCMessage)4)
#define RC_REQUEST_PAUSE        ((RCMessage)5)
#define RC_REQUEST_UNPAUSE      ((RCMessage)6)
#define RC_REQUEST_AUTO_REPLAY  ((RCMessage)7)
#define RC_RESTART_RACE         ((RCMessage)8)
#define RC_NEXT_RACE            ((RCMessage)9)
#define RC_QUIT_RACE            ((RCMessage)10)
#ifndef RC_SKIP_REPLAY         // world.h has it too
#define RC_SKIP_REPLAY          ((RCMessage)11)
#endif
#define RC_START_REPLAY         ((RCMessage)12)
#define RC_TAKE_AUTOSNAPSHOT    ((RCMessage)13)
#define RC_MOVE_REPLAY          ((RCMessage)14)
#define NUM_RC_MSGS             ((RCMessage)15)

// RCQueuedMessage, 16 bytes on the EE (type#1017): a bTNode, the message
// and its parameter. The queue's slot pool hands them out.
typedef struct RCQueuedMessage {
    bNode     Node;    // 0
    RCMessage Msg;     // 8
    int32_t   Param;   // 12
} RCQueuedMessage;

// RaceCoordinator, 144 bytes (type#1044). retail_layout finds every field
// where the demo has it. Retail adds a word at 140, in the demo's tail
// padding: the constructor zeroes it, and only RCStatePostRaceCallback
// (0x0014bdd8) reads or writes it otherwise.
struct RaceCoordinator {
    RCState   CurrentRCState;                     //   0
    bNode     RCQueuedMessageList;                //   4  bTList<RCQueuedMessage>
    int32_t   RCExecutingMessage;                 //  12
    int32_t   DisplayingCountdownNumber;          //  16
    int32_t   PausedJoystickPort;                 //  20
    RCState   BeforePauseRCState;                 //  24
    void     *pDemoCameraCoordinator;             //  28
    void     *pFlyByCameraCoordinator;            //  32
    void     *pPreRaceCameraCoordinator;          //  36
    struct EndGameScreens *pEndGameScreens;       //  40
    void     *pReplayScreen;                      //  44
    int32_t   mNumRewinds;                        //  48
    void     *mpCameraMover;                      //  52
    void     *mpCD;                               //  56
    void     *mIncidentPoint;                     //  60
    bVector3  mIncidentCoord;                     //  64
    bVector3  mFinalPosition;                     //  80
    bVector3  mStartPosition;                     //  96
    void     *mpEyeVerts;                         // 112
    void     *mpBankVerts;                        // 116
    void     *mpFOVtable;                         // 120
    struct Car *mpHighlightCar;                   // 124
    struct Car *mpHighlightCar2;                  // 128
    int32_t   mViewID;                            // 132
    void     *mpRoute;                            // 136
    int32_t   PostRacePlayerNumber;               // 140  retail's
};                                                // 144

#if !defined(RACECOORD_NO_ASSERT) && UINTPTR_MAX == 0xffffffffu
#include <stddef.h>
typedef char racecoord_layout_check[
    (offsetof(struct RaceCoordinator, RCQueuedMessageList) == 4
     && offsetof(struct RaceCoordinator, RCExecutingMessage) == 12
     && offsetof(struct RaceCoordinator, BeforePauseRCState) == 24
     && offsetof(struct RaceCoordinator, pEndGameScreens) == 40
     && offsetof(struct RaceCoordinator, mpCD) == 56
     && offsetof(struct RaceCoordinator, mIncidentCoord) == 64
     && offsetof(struct RaceCoordinator, mStartPosition) == 96
     && offsetof(struct RaceCoordinator, mpEyeVerts) == 112
     && offsetof(struct RaceCoordinator, mpRoute) == 136
     && offsetof(struct RaceCoordinator, PostRacePlayerNumber) == 140
     && sizeof(struct RaceCoordinator) == 144
     && sizeof(RCQueuedMessage) == 16) ? 1 : -1];
#endif

// The queue's slot pool, gp-22192 (0x00330240): sixteen-byte slots, eight
// to a block, made by the constructor and deleted by the destructor.
extern struct BSlotPool *RCQueuedMessageSlotPool;

// ThePauseMenu, gp-21064 (0x003306a8), which the constructor builds and
// the destructor deletes.
extern struct PauseMenu *ThePauseMenu;

// ------------------------------------------------------------ the methods

// 0x00149738, on memory the caller allocated. The queue empty and its
// pool made, ThePauseMenu built, the camera coordinators and the end-game
// screens NULL, PausedJoystickPort -1. With less than 0x7d000 bytes free
// in pool 16, the prerace animation's resource file is unloaded first, so
// that InitForRace then finds none. Then InitForRace, and last the
// auto-replay's camera fields zeroed.
RaceCoordinator *racecoordinator_construct(RaceCoordinator *rc);

// `new RaceCoordinator`, as BeginGameFlowLoadingTrackSpecific's caller
// has it: bMalloc(144 in retail, "RaceCoordinator", 0, 16) and the
// constructor. trackflow.h's gNewRaceCoordinatorFn takes this.
RaceCoordinator *racecoordinator_new(void);

// 0x00149858. Out of any state through ChangeState(RCSTATE_NONE), then
// CleanupAfterRace and CleanUpAutoReplay, ThePauseMenu deleted, the pool
// deleted. `flags & 1` frees the coordinator.
void racecoordinator_destroy(RaceCoordinator *rc, int32_t flags);

// 0x00149988. The players, a ReplayManager, the Race, the World, the cars
// and the players' cars, then the first state and the race's stage:
//
//   AIDemoMode (render eggs off)   RCSTATE_AI_DEMO_MODE      RACING
//   ReplayDemoMode                 RCSTATE_REPLAY_DEMO_MODE  RACING
//   SkipFE                         RCSTATE_RACE_IN_PROGRESS  RACING
//   BeACop                         RCSTATE_CAMERA_FLYBY      FLYBY
//   PRERACEANIM.LZC loaded         RCSTATE_CAMERA_FLYBY      FLYBY
//   otherwise                      RCSTATE_RACE_IN_PROGRESS  COUNTDOWN
//
// Race::Init on the stage, the ghost cars, the AI's driving styles, the
// collision sounds and the speech queue, pRaceCoordinator this, and a
// ChangeState to the state.
void racecoordinator_init_for_race(RaceCoordinator *rc);

// 0x00149b88. What InitForRace made, taken down: the camera coordinators,
// the players' race state, the cars and the helicopter, the effects, the
// Race and the World, the music and the one-shots, the ReplayManager, the
// end-game screens, and the players last to first.
void racecoordinator_cleanup_after_race(RaceCoordinator *rc);

// 0x00149d78. Player::CleanupAfterRace on each player, in pPlayersByIndex
// order.
void racecoordinator_cleanup_players(RaceCoordinator *rc);

// 0x0014a5f0. Each car on the World's CarList unlinked and destroyed with
// flags 3, the World re-read every pass. Then the helicopter.
void racecoordinator_cleanup_cars(RaceCoordinator *rc);

// 0x00149520. RC_UNACTIVATE to the state it is in, RC_ACTIVATE to `state`
// and RC_TICK, each through SendMessage.
void racecoordinator_change_state(RaceCoordinator *rc, RCState state);

// 0x00149650. The message on the end of the queue, and the queue run
// unless a message is running already.
void racecoordinator_send_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param);

// 0x001496d8. The message on the end of the queue, and nothing run.
void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param);

// 0x00149578. Each message from the front, taken off and freed after its
// state's callback has run. RC_ACTIVATE makes its parameter the state
// before the call, and RC_UNACTIVATE leaves RCSTATE_NONE after it.
void racecoordinator_execute_queued_messages(RaceCoordinator *rc);

// 0x001cd240. Each AI racer's DriverMode from the players' DrivingStyle.
// With two player cars, the leading player's style goes to the AI cars
// ahead of the middle of the AI field and the other's to the rest, the
// middle moved one back for each player at or ahead of it. Otherwise all
// take the first player's. Nothing without a World and a Race.
void set_ai_driver_modes_from_players(void);

// 0x001edb40. The DriverInfo whose UniqueDriverNumber is `number`, or NULL.
struct DriverInfo *race_parameters_get_driver_info_by_driver_number(
    int32_t number);

// ---------------------------------------------------------------- seams

// The ten state callbacks, by RCState (the table at 0x002f0bf0):
//
//   RCStateNoneCallback            0x0014a668
//   RCStateCameraFlybyCallback     0x0014abe0
//   RCStatePreRaceCallback         0x0014acf8
//   RCStateRaceInProgressCallback  0x0014ae80
//   RCStateInstantReplayCallback   0x0014b568
//   RCStateAutoReplayCallback      0x0014b848
//   RCStatePauseCallback           0x0014b3d8
//   RCStatePostRaceCallback        0x0014bdd8
//   RCStateAIDemoModeCallback      0x0014a8c0
//   RCStateReplayDemoModeCallback  0x0014aa38
//
// Each answers whether it took the message, which nothing reads. A NULL
// entry takes nothing. rcstates.c defines the table, with the first four;
// the other six stay NULL until their slices.
typedef int32_t (*RCStateCallbackFn)(RaceCoordinator *rc, RCMessage msg,
                                     int32_t param);
extern RCStateCallbackFn gRCStateCallbacks[NUM_RCSTATES];

// Seams this shares with other files: trackflow.h's gBCountFreeMemoryFn
// (bCountFreeMemory, 0x00257988; NULL reads as plenty) and
// gUnloadResourceFileFn (0x00199728), playercam.h's gPlayerCamSkipFE (the
// flow's SkipFE, gp-23220) and gCameraCoordinatorDeleteFn (the camera
// coordinators' virtual destructor).

// FindResourceFile by name (0x00199828), for "GLOBAL\PRERACEANIM.LZC".
// NULL finds nothing.
extern void *(*gFindResourceFileByNameFn)(const char *name);

// PauseMenu's constructor (0x00170580, on bMalloc(56)) and destructor
// (0x001705e0). With the constructor NULL there is no pause menu, and
// nothing is allocated for one.
extern struct PauseMenu *(*gPauseMenuCtorFn)(void *mem);
extern void (*gPauseMenuDestroyFn)(struct PauseMenu *m, int32_t flags);
#define PAUSE_MENU_SIZE 56

// ReplayManager's constructor (0x0013d448, on bMalloc(20664)) and
// destructor (0x0013d5c0). With the constructor NULL pReplayManager stays
// NULL, which everything reads as not replaying.
extern struct ReplayManager *(*gReplayManagerCtorFn)(void *mem);
extern void (*gReplayManagerDestroyFn)(struct ReplayManager *rm,
                                       int32_t flags);
#define REPLAY_MANAGER_SIZE 20664

// DisableRenderEggs (0x0024c000), which the AI demo calls.
extern void (*gDisableRenderEggsFn)(void);

// collision_sound::Reset (0x001e51c8), and the speech manager's FlushQueue
// (0x0020a230) on speech::mgr_t::getInstance (0x00209ef0).
extern void (*gCollisionSoundResetFn)(void);
extern void (*gSpeechFlushQueueFn)(void);

// RaceCoordinator::CleanUpAutoReplay (0x0014c148), which the destructor
// calls. It goes with the auto replay.
extern void (*gRCCleanUpAutoReplayFn)(RaceCoordinator *rc);

// Chopper's destructor (0x001e7b80), AcidEffectSystem::KillAllActiveEffects
// (0x001276a8) on WorldEffects, jukebox::Stop (0x001aec90),
// sound3d_oneshot::Reset (0x00209208) and EndGameScreens' destructor
// (0x001dcda8).
extern void (*gChopperDestroyFn)(struct Chopper *h, int32_t flags);
extern void (*gKillAllActiveEffectsFn)(void);
extern void (*gJukeboxStopFn)(void);
extern void (*gSound3dOneshotResetFn)(void);
extern void (*gEndGameScreensDestroyFn)(struct EndGameScreens *s,
                                        int32_t flags);

// RaceCoordinator::DoSnapshot, retail's 0x001498f0, in worldsnap.c (TASKS
// 72d-2), section "RaceCoordinator": pCurrentWorld's snapshot,
// pCurrentRace's, then each of PlayerPlayersByIndex's. The coordinator
// itself has nothing in it.
struct ReplaySnapshot;
void racecoordinator_do_snapshot(RaceCoordinator *rc,
                                 struct ReplaySnapshot *s);

#endif
