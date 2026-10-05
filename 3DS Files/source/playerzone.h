// playerzone -- the Player's camera zones and the jump cam. The addresses
// are retail's.
//
// Car::FinishMovement asks for the jump cam through car.h's four Player
// seams. This file is where they are being ported: so far
// IsJumpCamAvailable (0x001769e8). RequestZone, ClearZone and
// ClearZoneSound follow, with the jump cam's movers.
//
// Written up in docs/formats/camera.md, "The jump cam's route"; checked on
// retail's image by tools/prevroute_check.py.

#ifndef PLAYERZONE_H
#define PLAYERZONE_H

#include <stdint.h>

#include "bvector.h"

struct Player;

// 0x001769e8. CleanUpJumpCam, then a PreviewRoute 50 out and 75 long from
// the player's car into pJumpCamRoute. Yes if it has five points or more;
// if not, the route is cleaned up again. On the track whose
// SameAsTrackNumber is 21 there is no jump cam within 40 of (1646, -884),
// and no route is built.
int32_t player_is_jump_cam_available(struct Player *p);

// That place, and how near counts.
#define PLAYER_NO_JUMP_CAM_TRACK 21
extern const bVector2 PlayerNoJumpCamPlace;
#define PLAYER_NO_JUMP_CAM_RADIUS 40.0f

#endif
