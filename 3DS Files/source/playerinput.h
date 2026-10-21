// playerinput -- which joystick handlers a player has, by the race's state.
// The addresses are retail's.
//
// MainLoop runs DetermineAllPlayersInputModes (0x00181c28) each frame.
// Each player's DetermineInputMode (0x00177608) picks a mode from the
// RaceCoordinator's state, the finish and the camera zone, and a new mode
// goes to SetInputMode (0x001776b0), which takes the old mode's handlers
// off the player's port and puts the new one's on. Racing is the mode
// that hands the pad to the car: SetInputMode gives the RealDriver its
// port and calls its AddJoyHandlers, and nothing else does. So until this
// runs, a race's car never reads the pad.
//
// The handlers are Player's: RacingJoyHandler (0x00178978, through its
// bridge at 0x001832d8), PreRaceJoyHandler (0x00177b88), which the demo
// had and retail rewrote, FinishRaceJoyHandler (0x00177be0) and the debug
// camera's on the second pad (0x00178540, bridge 0x001832b8), which only
// DebugCamerasEnabled turns on and the disc ships off.
//
// The JoyEvent numbers are retail's (joyeventid.h): retail added
// JOY_EVENT_REPLAY_ERASE_DEMO at 110, so from STEER on they are one above
// the demo's, and its 128 to 132 are REQUEST_ROADBLOCK to SKIP.
//
// Written up in docs/formats/player.md, "Input modes".

#ifndef PLAYERINPUT_H
#define PLAYERINPUT_H

#include <stdint.h>

#include "joyevent.h"

struct AnimatedDriver;
struct Player;
struct tCopManager;

// PlayerInputModes (.mdebug type#1511).
#define PLAYER_MODE_NONE            0
#define PLAYER_MODE_PAUSEMENU       1
#define PLAYER_MODE_CAR_RACING      2
#define PLAYER_MODE_FROZEN_ZONE     3
#define PLAYER_MODE_AI_DEMO         4
#define PLAYER_MODE_PRERACE         5
#define PLAYER_MODE_FINISH_RACE     6
#define PLAYER_MODE_INSTANT_REPLAY  7

// gp-23080 (the demo's DebugCamerasEnabled, gp-23652). LoadConfigItems
// reads it from the config; 0 on the disc.
extern int32_t DebugCamerasEnabled;

// 0x00181c28. DetermineInputMode for each of Player::NumPlayers players.
void determine_all_players_input_modes(void);

// 0x00177608. By pRaceCoordinator's state: NONE, PRERACE for the flyby and
// the prerace, CAR_RACING while racing, PAUSEMENU paused, AI_DEMO in the
// AI demo and INSTANT_REPLAY for the rest (the replays, the postrace and
// the replay demo); NONE past the states. A finished player is
// FINISH_RACE instead, and then a player in zone 1 or 2 (freeze, preview)
// FROZEN_ZONE, by a byte table at 0x00330790. SetInputMode only when the
// mode changes. pRaceCoordinator must be set.
void player_determine_input_mode(struct Player *p);

// 0x001776b0. The old mode's handlers off, the debug camera's off the
// second pad, PlayerInputMode = `mode`, the new mode's on, then the debug
// camera's back on for a lone first player who is racing or in the AI
// demo. The racing modes (CAR_RACING and INSTANT_REPLAY, with POV, pause
// and HUD only for CAR_RACING) take look-back; the zones, or in Be A Cop
// the roadblock and the helicopter when the player's car is the player
// cop's; the car's driver, which a REAL_CONTROL car is given the port for;
// and the three camera movers'. A mode past 7 takes nothing on.
void player_set_input_mode(struct Player *p, int32_t mode);

// The handlers, as AddJoyHandler takes them; `obj` is the Player.
void player_racing_joy_handler_bridge(JoystickPort port, JoyEvent ev,
                                      uint8_t value, void *obj);
void player_pre_race_joy_handler(JoystickPort port, JoyEvent ev,
                                 uint8_t value, void *obj);
void player_finish_race_joy_handler(JoystickPort port, JoyEvent ev,
                                    uint8_t value, void *obj);
void player_change_debug_camera_joy_handler_bridge(JoystickPort port,
                                                   JoyEvent ev,
                                                   uint8_t value, void *obj);

// 0x00178978. Pause; POV change once a second at most, for the drive
// camera while racing; look-back, which sets bLookBack, the zone timer
// when the tweaker has not paused the world, the drive camera's (or the
// saved one's) DesiredLookBackParam and the driver animation; the three
// zones; the HUD cycle when PlayerSettings.New40 allows; and Be A Cop's
// two requests, which also hold off the POV change.
void player_racing_joy_handler(struct Player *p, JoystickPort port,
                               JoyEvent ev, uint8_t value);

// 0x001788b8 (TASKS 73). RealDriver hands it an automatic box's shift
// buttons (realdriver.h's gPlayerRerouteJoyEventFn). Retail's makes them
// RacingJoyHandler's: SHIFTUP the preview zone and SHIFTDOWN the freeze
// zone, or in Be A Cop the roadblock and the helicopter calls when the
// player's car is the player cop's (nothing when it is not). Any other
// event does nothing; the demo's passed nothing on at all.
void player_reroute_joy_event(struct Player *p, JoystickPort port,
                              JoyEvent ev, uint8_t value);

// 0x00178540. With DebugCamerasEnabled, the next camera in the mode's
// cycle: none, orbit, debug world in the AI demo (the demo cameras
// suspended off none and resumed on it), else drive, orbit, debug world,
// track route editor.
void player_change_debug_camera_joy_handler(struct Player *p,
                                            JoystickPort port, JoyEvent ev,
                                            uint8_t value);

// ---------------------------------------------------------------- the seams
//
// Player::CycleHud (0x00178ba8), tCopManager's BeACopRequestRoadBlock
// (0x002288c8) and BeACopRequestChopper (0x002287d8), and AnimatedDriver's
// Begin/EndLookingBackwards (0x001a9c40, 0x001a9c68; animdriver.c).
// RequestZone (0x00177c88) is car.h's gPlayerRequestZoneFn. A NULL seam
// does nothing, so a button with no port is a dead button rather than an
// abort.
extern void (*gPlayerCycleHudFn)(struct Player *p, int32_t dir);
extern void (*gCopManagerBeACopRequestRoadBlockFn)(struct tCopManager *m);
extern void (*gCopManagerBeACopRequestChopperFn)(struct tCopManager *m);
extern void (*gAnimatedDriverBeginLookingBackwardsFn)(struct AnimatedDriver *d);
extern void (*gAnimatedDriverEndLookingBackwardsFn)(struct AnimatedDriver *d);

#endif
