// timer -- Timer, the game's one-word clock stamp, and the one method of it
// the port has reached.
//
// Timer is `Timer:Tt2847=s4PackedTime:/030,0,32`: a uint32 of ticks, four
// thousand to the second. WorldTimer (0x00323cf0) counts in the same ticks,
// and every "how long ago" in Car is `(WorldTimer - stamp) * 0.00025f`
// through a signed convert. The class's methods sit in Car.obj's tail, and
// the port takes them as it reaches them. CarCollisionBody holds two,
// RacingCar thirty-seven, and Car's blink adds one through SetTime.

#ifndef TIMER_H
#define TIMER_H

#include <stdint.h>

typedef struct Timer {
    uint32_t PackedTime;                        //   0
} Timer;                                        //   4

// 0x00134ef0. `seconds * 4000.0f`, then `cvt.w.s`, which truncates and
// saturates: ee_trunc_w, not a cast. The multiplier is built with
// `lui at,0x457a`, not loaded.
void timer_set_time(Timer *t, float seconds);

#endif
