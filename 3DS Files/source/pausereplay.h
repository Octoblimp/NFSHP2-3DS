// pausereplay -- HandlePauseMenuReplaySpecialEvents (0x001703e0, 380
// bytes), from retail: the pause pages' changes as replay special events.
//
// A change on the pause menu's Options page (pauseoptions.c) does not
// happen there and then. It goes to the race's ReplayManager as a special
// event (AddSpecialEvent, 0x0013e3f8), which makes it at once through
// ReplayManager::HandleSpecialEvent (0x0013e4a8, a jump to this) and,
// while capturing, keeps it. A replay makes it again on the loop it was
// made on (CheckForSpecialEvents, 0x0013e4b0), so the replay drives as the
// race did. The debug menu (PauseDebugMenu, 0x00173e30), which retail never
// shows, makes 0 and 6. docs/formats/pause-options.md has the decode.

#ifndef PAUSEREPLAY_H
#define PAUSEREPLAY_H

#include <stdint.h>

#include "replay.h"

// The events, by ReplaySpecialEventInfo.Type, with what A and B hold.
#define PAUSE_EVENT_FORCE_FINISH  0   // A the place, B the player: the
                                      // Race's ForceRaceFinishPosition and
                                      // ForceRaceFinishPlayerNum
#define PAUSE_EVENT_HANDLING      1   // A the player, B the driving style
#define PAUSE_EVENT_DAMAGE        2   // A on or off
#define PAUSE_EVENT_TRANSMISSION  3   // A the player, B the type
#define PAUSE_EVENT_JUMP_CAMS     4   // A on or off
#define PAUSE_EVENT_ZONE_CAMS     5   // A on or off
#define PAUSE_EVENT_SUPER_EASY_AI 6   // A SuperEasyAI

// Makes event `e`, recorded or replayed. 1 handling: the player's car's
// State.DriverMode, the player's DrivingStyle (SetDrivingStyle) and
// TheRaceParameters.NFSRaceMode become B, then SetAIDriverModesFromPlayers.
// 2 damage: TheRaceParameters.DamageEnabled is A != 0, then every car with
// damage rethinks it. 3 transmission: the player's TransmissionType is B,
// and the car's RealDriver is told (SetManualTransmission). 4 and 5: the
// display settings' JumpCams and ZoneCams are A's low byte. Answers 1 for
// those seven and 0, doing nothing, for any other. Retail reads through
// the players, cars and world with no test; the port skips what is NULL
// or a player number off the table.
int32_t pause_menu_replay_special_event(const ReplaySpecialEventInfo *e);

#endif
