// warp -- a test run's start somewhere else on the track. Not on the disc.
//
// A test on Azahar can only hold buttons, and the gas alone runs the car
// into the first bend: what is further round the lap (the jump cam's ramps,
// say) cannot be reached that way. When WARP_FLAG is on the card as a race
// starts, its line
//
//   seconds x y z angle speed
//
// puts player 1's car at (x, y, z), heading `angle` (sixteen bits, 0 along
// +x as Car's State.Angle) at `speed`, once the race has run that many
// seconds, through Car::ResetToPosition (carreset.c), as a reset would.
// Once a race. Without the file nothing changes.

#ifndef WARP_H
#define WARP_H

#include <stdbool.h>

#define WARP_FLAG "sdmc:/nfshp2_warp.txt"

// Each race frame, before the world's step: whether a race is running.
void warp_race(bool racing);

#endif
