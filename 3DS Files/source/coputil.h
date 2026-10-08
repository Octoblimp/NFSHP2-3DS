// coputil -- the cops' helpers, retail's coputil.obj (0x00230de8 ..
// 0x002315cc): teleport checks, collision tests, top speeds, angles and
// cubics. CarInRecentCollision is here for CopDriver, and
// GetForwardTrackDistance and IsTeleportLocationClear for the track graph;
// the rest come with tAICop's Think (step 12g).

#ifndef COPUTIL_H
#define COPUTIL_H

#include <stdint.h>

#include "bvector.h"

struct Car;

// GetForwardTrackDistance, 0x00230de8: a - b, plus TheTrackPathManager's
// TrackLength when that is below 0.
float get_forward_track_distance(float a, float b);

// IsTeleportLocationClear, 0x00230e18: 0 within 250 of a player (World::
// GetDistanceToClosestPlayer's two-dimensional form) or within 15 of any
// of pCurrentWorld's cars, in x and y; else 1.
int32_t is_teleport_location_clear(const bVector2 *p);

// CarInRecentCollision, 0x00231258: 1 when the car's dynamic collision
// body has a collision this frame (its NumCollisions byte, signed, is not
// 0).
int32_t car_in_recent_collision(struct Car *car);

#endif
