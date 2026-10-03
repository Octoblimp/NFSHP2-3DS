// playerupdate -- the Player's frame outside the game state: what MainLoop
// runs for each player after the world's step. The addresses are retail's.
//
// This is step 8l-3b: UpdateNonGameState (0x00180e60), the loop over the
// players (UpdatePlayersNonGameState, 0x00181d88) and BeginCountdownCameras
// (0x001768e0). In a race, UpdateNonGameState gives a player with no
// camera the countdown cameras while the race counts down and the drive
// camera after, unless a NIS plays; it retires a driving line that has
// outlived its lifetime, and pauses for a pad pulled out or swapped. Out
// of a race it notes the pad's type. Then UpdateHud.
//
// The countdown's coordinator and the HUD are seams, NULL until their
// classes are ported. With the coordinator's NULL, BeginCountdownCameras
// still takes the player's camera away, as retail does before it builds
// one, and the player has no camera until the race starts.
//
// Written up in docs/formats/player.md, "The frame outside the game
// state"; checked on retail's image by tools/playerupdate_check.py.

#ifndef PLAYERUPDATE_H
#define PLAYERUPDATE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "cammover.h"

struct CountdownCameraCoordinator;
struct Player;

// BaseCameraCoordinator's head (.mdebug type#2329, 28 bytes in the demo):
// a bTNode, then the mover it runs. CountdownCameraCoordinator::Update
// (0x0019b1a0) deletes its mover each time the number on screen changes
// and builds the next from that number's camera data, so it has none once
// a number has no data; UpdateNonGameState reads that here.
typedef struct CameraCoordinatorHead {
    bNode        Node;                     //  0
    CameraMover *pCameraMover;             //  8
} CameraCoordinatorHead;

// VisibleDrivingLine's head (.mdebug type#1662, 104 bytes in the demo):
// the line lasts Lifetime seconds from StartTime, a WorldTimer.
typedef struct VisibleDrivingLineHead {
    struct Player *pPlayer;                //  0
    float          Lifetime;               //  4
    int32_t        StartTime;              //  8
} VisibleDrivingLineHead;

#if UINTPTR_MAX == 0xffffffffu
typedef char playerupdate_layout_check[
    (offsetof(CameraCoordinatorHead, pCameraMover) == 8
     && offsetof(VisibleDrivingLineHead, Lifetime) == 4
     && offsetof(VisibleDrivingLineHead, StartTime) == 8) ? 1 : -1];
#endif

// 0x00180e60. pRaceCoordinator must be set: retail reads its state
// without a test.
void player_update_non_game_state(struct Player *p);

// 0x00181d88. UpdateNonGameState for each of PlayerPlayersByIndex, the
// count read again after each.
void update_players_non_game_state(void);

// 0x001768e0. With no countdown coordinator yet: ChangeCameraMover(0, 0),
// then CountdownCameraCoordinator(ViewID, p) on bMalloc(36,
// "CountdownCameraCoordinator", 0, 16).
void player_begin_countdown_cameras(struct Player *p);

// ---------------------------------------------------------------- the seams

// CountdownCameraCoordinator's constructor (0x0019b130), which returns the
// coordinator. Player::UpdateHud (0x0017ecf0).
extern struct CountdownCameraCoordinator *(*gCountdownCameraCoordinatorFn)(
    void *mem, int32_t viewID, struct Player *p);
extern void (*gPlayerUpdateHudFn)(struct Player *p);

#endif
