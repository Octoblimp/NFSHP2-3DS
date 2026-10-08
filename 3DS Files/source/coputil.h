// coputil -- the cops' helpers, retail's coputil.obj (0x00230de8 ..
// 0x002315cc): teleport checks, collision tests, top speeds, angles and
// cubics. CarInRecentCollision is here so far, for CopDriver; the rest
// come with tAICop's Think (step 12g).

#ifndef COPUTIL_H
#define COPUTIL_H

#include <stdint.h>

struct Car;

// CarInRecentCollision, 0x00231258: 1 when the car's dynamic collision
// body has a collision this frame (its NumCollisions byte, signed, is not
// 0).
int32_t car_in_recent_collision(struct Car *car);

#endif
