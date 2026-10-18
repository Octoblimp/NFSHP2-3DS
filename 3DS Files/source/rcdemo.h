// rcdemo -- RaceCoordinator.obj from retail: the two demo states.
//
//   RaceCoordinator::RCStateAIDemoModeCallback      0x0014a8c0  376 bytes
//   RaceCoordinator::RCStateReplayDemoModeCallback  0x0014aa38  420 bytes
//
// TASKS 72h-2b. InitForRace (racecoord.c) starts a race in AI_DEMO_MODE
// when TheRaceParameters.AIDemoMode is set, and in REPLAY_DEMO_MODE when
// ReplayDemoMode is, which TheDemoModeReplay's restore sets (dmreplay.h).
// Both show the Demo overlay, a camera on the first player's car, and end
// on any button or when the demo runs out, back to the frontend.
// docs/formats/replay.md has the decode.

#ifndef RCDEMO_H
#define RCDEMO_H

#include <stdint.h>

#include "racecoord.h"

// The overlay both states show: two black bars, the game's logo top left
// and "Demo" (language ID 322002) at the bottom.
#define RC_DEMO_SCREEN 0xcc28b8a9u

// AI_DEMO_MODE.
//
// ACTIVATE shows the overlay, hands JOY_EVENT_SKIP_DEMO_MODE on both ports
// to racecoordinator_joystick_handler and makes the demo camera.
// UNACTIVATE hides the overlay, takes the two handlers away and deletes the
// camera. TICK ends the demo, timed out, once the race's time is past
// DemoModeTimeout (demomode.h); SKIP ends it, skipped. Ending is
// Fred.DemoModeStatus set, a change to NONE and RC_QUIT_RACE sent, which
// NONE takes. QUIT_RACE itself changes to NONE and sends itself on.
// TAKE_AUTOSNAPSHOT is taken. Every other message answers 0.
int32_t rc_state_ai_demo_mode_callback(RaceCoordinator *rc, RCMessage msg,
                                       int32_t param);

// REPLAY_DEMO_MODE.
//
// ACTIVATE begins TheDemoModeReplay's demo, which restores its first
// snapshot, and then does as the AI demo's. UNACTIVATE does as the AI
// demo's, then ends TheDemoModeReplay's demo and puts the joystick's
// type-changed handlers back. TICK ends the demo, timed out, once
// TheDemoModeReplay's test says it does not go on. SKIP and SKIP_REPLAY
// end it, skipped. MOVE_REPLAY, which the replay's ServiceDemoMode posts
// with the next snapshot, restores it and makes the camera again.
// QUIT_RACE and TAKE_AUTOSNAPSHOT are the AI demo's. Every other message
// answers 0.
int32_t rc_state_replay_demo_mode_callback(RaceCoordinator *rc,
                                           RCMessage msg, int32_t param);

#endif
