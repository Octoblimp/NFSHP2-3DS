// rcreplay -- RaceCoordinator.obj from retail: the instant replay.
//
//   RaceCoordinator::RCStateInstantReplayCallback  0x0014b568  736 bytes
//
// TASKS 72g-3. View Replay, on the pause menu and on the End Game Menu,
// changes to RCSTATE_INSTANT_REPLAY, and this state puts the ReplayScreen
// (replayscreen.h) over the replay. The auto replay (0x0014b848) is
// rcauto.c's.
// docs/formats/replay.md has the decode.

#ifndef RCREPLAY_H
#define RCREPLAY_H

#include <stdint.h>

#include "racecoord.h"

// The snapshots the state takes, restores and deletes by name.
#define RC_REPLAY_LAP_SNAPSHOT     "LAP_SNAPSHOT"
#define RC_REPLAY_THE_PRESENT      "THE_PRESENT"
#define RC_REPLAY_INSTANT_REPLAY   "INSTANT_REPLAY"

// The name the screen's allocation gives (line 0, pool 16).
#define RC_REPLAY_SCREEN_NAME      "ReplayScreen"

// INSTANT_REPLAY.
//
// ACTIVATE, from the end screens (pEndGameScreens set): the first
// LAP_SNAPSHOT restored, the race's start; when there is none, a change
// back to POSTRACE is queued, and the screen is made all the same. From the
// pause: THE_PRESENT taken and the first INSTANT_REPLAY restored; when
// either fails, a change back to PAUSE and no screen. The screen made:
// every player's camera movers off, and the ReplayScreen in pReplayScreen
// for the player the pause menu's ReplayChooser names -- 1 for player 1,
// -1 for the player who finished best (TransientStats' FinishPosition,
// lowest; ties keep the first), anything else player 0.
//
// UNACTIVATE deletes the screen, mutes the sound, turns the camera movers
// back on and puts the joystick's type handlers back. TICK ticks the
// screen. SKIP_REPLAY goes back to POSTRACE from the end screens; from the
// pause it restores THE_PRESENT, deletes it and goes back to PAUSE.
// MOVE_REPLAY restores the snapshot its param points at and makes the
// screen's camera again. TAKE_AUTOSNAPSHOT is taken. Every other message
// answers 0.
int32_t rc_state_instant_replay_callback(RaceCoordinator *rc, RCMessage msg,
                                         int32_t param);

#endif
