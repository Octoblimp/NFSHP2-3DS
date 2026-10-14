// cardamageabove -- Car::DamageAbove (retail 0x00135280) and Car::DamageCap
// (retail 0x00135490), the marker You're The Cop draws over a car: an
// upside-down pyramid of four sides, its colour saying whether a cop is on
// the car, and its sides filled from the point up as the cops' damage on
// the car grows.
//
// RenderCars calls DamageAbove for every car it drew, through
// gCarDamageAboveFn (carrenderinfo.h), unless the view's player is in the
// jump cam; only DamageAbove calls DamageCap. Both are retail's: the demo
// has DamageAbove only, and with no cop manager to ask.
//
// Cross-check: tools/cardamageabove_check.py. Write-up:
// docs/formats/car-damage.md ("The marker over the car").

#ifndef CARDAMAGEABOVE_H
#define CARDAMAGEABOVE_H

#include <stdint.h>

#include "car.h"

// Car::DamageAbove(bVector3 *eye, bVector3 *direction).
//
// First, always: fAngleToCamera. With `n` the unit way from the car to the
// eye, it is (direction . n + 1) / 2, negated when z of direction x n is
// at or above 0: 0 for a car straight ahead of the camera, 0.5 either way
// for one beside it, 1 either way for one straight behind.
// Player::DrawTracker draws a tracker within 0.5 of 0 either way.
//
// Then the marker, only when no player has a NIS playing, the race is
// You're The Cop and in progress, there is a cop manager, and the car is
// an AI racer or a player's car that is not a cop: DamageCap with whether
// a cop pursues the car, the cop manager's damage for its CarIndex, and
// the car's distance from the eye over 200, held to 0 .. 1.
void car_damage_above(Car *c, bVector3 *eye, bVector3 *direction);

// Car::DamageCap(bool pursued, float damage, float distance).
//
// ObjectPoints 0 .. 4, the pyramid's point and its square's four corners,
// times 2 * distance + 0.05 (0.1 in an instant replay or after the race),
// drawn through DamageAboveMatrix (half size, 1 up) on the car's body
// matrix at its position, a frame matrix, on WHITE16X16_NOALPHA, through
// gEPolyRender3DFn. With no damage, each side is one colour, 0xff00aa00
// (green), or 0xffcc0000 (blue) when pursued. With damage, each side is
// two: from the point to `damage` of the way up its edges in 0xff005599
// (orange), or 0xff995500 when pursued, and the rest in the side's own
// colour. Then the square on top, in the side's colour. No frame memory,
// no marker.
void car_damage_cap(Car *c, int32_t pursued, float damage, float distance);

#endif
