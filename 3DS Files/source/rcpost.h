// rcpost -- RaceCoordinator.obj from retail: the pause and the post-race,
// and the Player calls the pause makes.
//
//   RaceCoordinator::RCStatePauseCallback     0x0014b3d8  400 bytes
//   RaceCoordinator::RCStatePostRaceCallback  0x0014bdd8  796 bytes
//   Player::BeginPause                        0x00181bd0    4 bytes
//   Player::EndPause                          0x00181bd8   44 bytes
//   TellPlayersToPause                        0x00181c88   92 bytes
//   TellPlayersToUnPause                      0x00181ce8   92 bytes
//
// Step 8g. The two replays and the two demos are the last four states;
// rcreplay.c has the instant replay (72g-3), and the other three entries
// in gRCStateCallbacks stay NULL until their slices.
// docs/formats/race-coordinator.md has the decode.

#ifndef RCPOST_H
#define RCPOST_H

#include <stdint.h>

#include "fred.h"
#include "joystick.h"
#include "racecoord.h"

struct EndGameScreens;
struct PauseMenu;
struct Player;
struct ReplayManager;

// ------------------------------------------------------------ the states

// PAUSE. ACTIVATE tells the players, enters the pause menu with the port
// that asked, changes to the "Pause Menu" screen and mutes the sound.
// UNACTIVATE changes to no screen, exits the pause menu and tells the
// players. TICK is taken. REQUEST_UNPAUSE on its UnPauseReasonType:
// RESUME_RACE unmutes and goes back to the state before the pause;
// INSTANT_REPLAY goes to INSTANT_REPLAY; QUIT_RACE tells the frontend, goes
// to NONE and sends QUIT_RACE; RESTART_RACE goes to NONE and sends
// RESTART_RACE. Any other reason is taken and does nothing.
int32_t rc_state_pause_callback(RaceCoordinator *rc, RCMessage msg,
                                int32_t param);

// POSTRACE. ACTIVATE puts every player's camera mover to CM_NONE, unmutes,
// flushes the speech, mutes the replay's sound if its word at +12 says so,
// begins the race's highlights and resumes the end-game screens. Then,
// with two players, the one who finished best (TransientStats'
// FinishPosition, lowest) becomes the one the demo camera follows; with
// one, player 0. UNACTIVATE suspends the end-game screens, deletes the
// demo camera and puts the joystick type handlers back. TICK, once
// WorldLoopCounter reaches the highlight's end, begins the next highlight
// with a new demo camera; SKIP_REPLAY does too, at once, with the replay's
// sound muted. START_REPLAY goes to INSTANT_REPLAY. RESTART_RACE (with the
// frontend told), NEXT_RACE and QUIT_RACE go to NONE and send the message
// on. TAKE_AUTOSNAPSHOT is taken.
int32_t rc_state_post_race_callback(RaceCoordinator *rc, RCMessage msg,
                                    int32_t param);

// ------------------------------------------------------- the Player calls

// 0x00181bd0: Player::ClearHudAnimations (0x0017c7c8), as a tail call.
void player_begin_pause(struct Player *p);

// 0x00181bd8: the player's JoyType from GetJoystickType on its port.
void player_end_pause(struct Player *p);

// 0x00181c88 and 0x00181ce8: BeginPause and EndPause on each player in
// pPlayersByIndex order, re-reading NumPlayers every pass.
void tell_players_to_pause(void);
void tell_players_to_unpause(void);

// ---------------------------------------------------------------- seams
//
// Shared with other files: rcstates.h's gSoundMuteFn,
// gDemoCameraCoordinatorCtorFn and DEMO_CAMERA_COORDINATOR_SIZE,
// racecoord.h's gSpeechFlushQueueFn and playercam.h's
// gCameraCoordinatorDeleteFn. Each one below does nothing when NULL, and
// answers 0 unless it says otherwise.

// ChangeToScreen (0x0014cc78): TheFlailerScreenList's ChangeToScreen
// (0x0016c4c0) with the screen's name, NULL for none, and whether to push
// the one showing.
extern void (*gChangeToScreenFn)(const char *name, int32_t push);
#define RC_PAUSE_MENU_SCREEN "Pause Menu"

// PauseMenu::EnterPause (0x00170638) and ExitPause (0x00170720), on
// racecoord.h's ThePauseMenu, NULL or not.
extern void (*gPauseMenuEnterPauseFn)(struct PauseMenu *m, JoystickPort port);
extern void (*gPauseMenuExitPauseFn)(struct PauseMenu *m);

// Player::ClearHudAnimations (0x0017c7c8).
extern void (*gPlayerClearHudAnimationsFn)(struct Player *p);

// TheFrontendDatabase's TheRaceWasQuit (0x00187800) and
// TheRaceWasRestarted (0x00187880).
extern void (*gFEDTheRaceWasQuitFn)(void);
extern void (*gFEDTheRaceWasRestartedFn)(void);

// sound::MuteReplay (0x001af940).
extern void (*gSoundMuteReplayFn)(int32_t on);

// ReplayManager's BeginRaceHighlights (0x0013e308) and
// BeginNextRaceHighlight (0x0013e318), on pReplayManager, NULL or not; and
// two of its words: retail's new word at +12, which mutes the replay's
// sound for the highlights, and EndCurrentHighlightTime (+160), a
// WorldLoopCounter. The TICK reads the second only with a ReplayManager,
// and with that seam NULL never begins the next highlight.
extern void (*gReplayBeginRaceHighlightsFn)(struct ReplayManager *rm);
extern void (*gReplayBeginNextRaceHighlightFn)(struct ReplayManager *rm);
extern int32_t (*gReplayMuteHighlightsFn)(const struct ReplayManager *rm);
extern int32_t (*gReplayEndCurrentHighlightTimeFn)(
    const struct ReplayManager *rm);

// EndGameScreens::ResumeScreens (0x001dcf38) and SuspendScreens
// (0x001dcfe8), on pEndGameScreens, NULL or not.
extern void (*gEndGameScreensResumeFn)(struct EndGameScreens *s);
extern void (*gEndGameScreensSuspendFn)(struct EndGameScreens *s);

// TransientStats::GetDriver (0x00187080) on TheTransientStats
// (0x002fc3dc): the race's stats element for a driver number, or NULL.
// The element is fred.h's, 100 bytes in retail.
extern const TransientStatsElement *(*gTransientStatsGetDriverFn)(
    int32_t driverNumber);

// The unnamed 0x001543f0: for both ports, RemoveJoyHandler and AddJoyHandler
// of JOY_EVENT_TYPE_CHANGED with TypeChangedHandler (0x001542a8).
extern void (*gRestoreTypeChangedHandlersFn)(void);

#endif
