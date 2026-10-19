// playernis -- a player's NIS and game state: what a pullover plays, how
// it ends, the wrong-way test, the trouble watch and the step that runs
// them (retail 0x00176308 .. 0x00176648 and 0x00180c28 .. 0x00182200).
//
// A pullover of a player's car with a NIS to play (pullover.h) calls
// PlayNextNis with the callback that ends the pullover. That starts the
// player's NisManager (nismanager.h) on the next ticket or arrest NIS and
// its camcorder overlay, and World's step (worldstep.c) runs
// UpdatePlayersGameState, whose ServiceNis stops the NIS once its time is
// up and calls the callback.
//
// The port has no NIS player yet: nothing poses or animates the cars and
// the characters, and there is no NIS camera coordinator. Retail hands
// the view to that coordinator, ChangeCameraMover(NONE) and then
// CreateNisCameraCoordinator; with the seam NULL the port keeps the
// player's camera instead, so the view goes on following the stopped car
// under the TICKET or ARREST overlay for the NIS's time, and ServiceNis's
// ChangeCameraMover(DRIVE) then finds a drive camera already there. With
// the seam bound the two follow retail.
//
// Names are the demo's (.mdebug type#2091's methods); retail has no
// symbols. See docs/formats/nis.md; tools/playernis_check.py runs these
// against retail.

#ifndef PLAYERNIS_H
#define PLAYERNIS_H

#include <stdint.h>

#include "nismanager.h"

struct Car;
struct NisCameraCoordinator;
struct Player;

// Player::CreateRandomNisArray(NisType), 0x00181a28. The NisNumbers of
// the table's NISes of that type in order (a missing one is the first
// ticket's, untested) are drawn without repeats -- each one bRandom(how
// many are left) on bDefaultSeed, counted through the ones not yet drawn
// -- into TicketNisNumbers for a ticket and ArrestNisNumbers for anything
// else, and each one's camera is bRandom(its NumCameras) into
// TicketCameraNumbers or ArrestCameraNumbers.
void player_create_random_nis_array(struct Player *p, int32_t type);

// Player::PlayNextNis(Car *car, Car *cop, void (*done)(int), int param),
// 0x00176308; returns 1. The callback and its parameter kept; car's
// tickets from pCopManager; ClearZone(1); RadialBlurOff for the cop's
// player's view; car stops blinking; bResetGlare 1; both NIS indices at
// least 0. An arrest when the race is not a free run and the tickets have
// reached nNumTicketsBeforeArrest, else a ticket: either way the NIS and
// its camera are read at TicketNisIndex (the arrest's too), and a camera
// the other player's playing NIS is on moves to the next of the NIS's
// NumCameras. Then NisManager::Start, the overlay's StartTicket or
// StartArrest, and outside a replay the view to the NIS camera (see the
// top of this file).
//
// The port's: a player without a NisManager plays nothing, and the
// callback runs at once.
int32_t player_play_next_nis(struct Player *p, struct Car *car,
                             struct Car *cop, void (*done)(int32_t),
                             int32_t param);

// Player::ServiceNis, 0x00176530. Nothing while the manager is not
// playing. Once WorldTimeFrames reaches its EndTime: outside a replay the
// drive camera back, NisManager::Stop, the callback with its parameter
// and then both cleared, NisManager::Unload and the overlay's Finish.
// AllowDebugLooping, always 0, would have restarted the NIS camera first.
void player_service_nis(struct Player *p);

// Player::DetectWrongWay(int was), 0x00181058. The car's Angle against
// the track path's direction (bATan of its x and y), folded to 0..32768
// and 1820 more when `was`: under 20024 (110 degrees) is the right way.
// Wrong, and faster than 10 mph forwards or backwards: the velocity's
// heading the same way decides, wrong being `was` or else all four
// wheels down. Wrong and slower: `was`.
int32_t player_detect_wrong_way(struct Player *p, int32_t was);

// Player::IsAllowedToReset, 0x00181e98. Not in a zone that blocks
// requests (but the 6 and 7 zones), not while a NIS plays, not above 60
// mph; in Be A Cop only from 5 s into the race.
int32_t player_is_allowed_to_reset(struct Player *p);

// Player::PlayerSelectedReset, 0x00182208 (TASKS 73): RealDriver's reset
// button, once the car is back on the route. Both reset timers cleared;
// the camera mover's ResetState; a drive camera's DesiredLookBackParam
// back to bLookBack (1 or 0); and HangTime 0, so the stunt score does not
// count the drop. The demo's did the first timer and ResetState.
void player_selected_reset(struct Player *p);

// Player::ChooseToDisplayReset, 0x00181f68: the trouble watch.
// LastTimeCarInTrouble is WorldTimer when the car, within 3 s of its last
// penetration, is above 60 mph and yawing more than 50 degrees a second,
// or was above 60 at the last half-second sample and is losing more than
// 70 mph a second; or when below 10 mph upside down. Five seconds on it
// is let go. While it holds, with the car allowed to reset and not being
// chased, it is let go too unless TimeToDisplayResetPrompt is showing --
// which nothing in retail sets: the reset prompt was cut, and this is
// what is left. TimeToDisplayResetPrompt goes after 3 s.
void player_choose_to_display_reset(struct Player *p);

// Player::UpdateGameState, 0x00180c28. ServiceNis, the wrong-way flag,
// the trouble watch; in a race or a replay, once a second the car's speed
// over its driving line's speed (1 off a line that is neither valid nor
// fake) into pAverageSpeedRatio and its peak into fMaxSpeedRatio; and the
// freeze zone's delay counted down, the zone requested when it runs out
// and, given, PlayBustRoadBlock at the car.
void player_update_game_state(struct Player *p);

// UpdatePlayersGameState, 0x00181de8: each player by index, the count
// read again each time. World's step's gUpdatePlayersGameStateFn.
void player_update_players_game_state(void);

// NisManager::CreateNisCameraCoordinator(int view), 0x001b2af0, the NIS
// player's. NULL keeps the player's camera (see the top of this file).
extern struct NisCameraCoordinator *(*gNisCreateCameraCoordinatorFn)(
    NisManager *m, int32_t view);

#endif
