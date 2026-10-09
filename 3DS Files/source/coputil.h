// coputil -- the cops' helpers, retail's coputil.obj (0x00230de8 ..
// 0x002315cc): teleport checks, collision tests, top speeds, angles and
// cubics. CarInRecentCollision is here for CopDriver, GetForwardTrackDistance
// and IsTeleportLocationClear for the track graph, and CanTeleport and
// CarCausedRecentCollision for the cops' logic (12g-2), DidTheseCarsCollide
// for the chase's (12g-3); the rest come with the chases. GetTopSpeed is
// pursuit.c's, its only caller's.

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

// CanTeleport(Car *, bVector2 *), 0x00230ff0: 0 when a player is within
// 250 m (the two-dimensional distance) of the car or of `dest`, or when
// any other of pCurrentWorld's cars is within 15 m of the car in x and y;
// else 1. The count is read once.
int32_t can_teleport(struct Car *car, const bVector2 *dest);

// CarCausedRecentCollision(Car *), 0x00231118: of the car's collisions
// this frame, the first two-car one whose other car is stopped, or ahead
// of it (Car::IsCarInFront within 8192 BAM) and going forward slower than
// it; that car, or NULL. A two-car collision with no other car ends the
// search.
struct Car *car_caused_recent_collision(struct Car *car);

// DidTheseCarsCollide(Car *, Car *), 0x00231268: 1 when one of car a's
// two-car collisions this frame is with car b. As in
// CarCausedRecentCollision, a two-car collision with no other car ends
// the search, with 0.
int32_t did_these_cars_collide(struct Car *a, struct Car *b);

// CarInRecentCollision, 0x00231258: 1 when the car's dynamic collision
// body has a collision this frame (its NumCollisions byte, signed, is not
// 0).
int32_t car_in_recent_collision(struct Car *car);

#endif
