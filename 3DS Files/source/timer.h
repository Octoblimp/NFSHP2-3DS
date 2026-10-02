// timer -- Timer, the game's one-word clock stamp, and the methods of it the
// port has reached.
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

// Retail 0x001a3d70 (the demo's 0x00199af8). The time in seconds rounded to
// the nearest multiple of `f`, half up, then up to the next whole tick:
// q = seconds / f is floored (`cvt.w.s` and one less when that went up),
// one more when the rest is a half or over, and the multiple times 4000 is
// ceilinged the same way before it goes back to seconds by 0.00025
// (gp-29388).
float timer_round_seconds(const Timer *t, float f);

// Retail 0x001a3e28. The time set to RoundSeconds' ticks, to the nearest:
// `seconds * 4000 + 0.5`, then `cvt.w.s`. Race's start and each racing
// car's crossings go through it with f = 0.01.
void timer_round(Timer *t, float f);

#endif
