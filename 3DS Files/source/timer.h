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

// Retail 0x00136dd0, and its copies in other objects (0x0013ed60,
// 0x001494e8, 0x001a3ed0 and more). `seconds * 4000.0f + 0.5f`, then
// `cvt.w.s`, which truncates and saturates: ee_trunc_w, not a cast. So the
// ticks are rounded, half up for a positive time and toward 0 by a half
// for a negative one. Both constants are built with `lui`. The demo's
// (0x00134ef0) had no 0.5 and truncated: a sixtieth was 66 ticks there and
// is 67 in retail, so the world clock runs at retail's rate only with this.
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

// Retail 0x001a3cf0, CountDown(float). A valid timer loses
// `cvt.w.s(dt * 4000.0f)` ticks -- truncated, no 0.5, unlike SetTime --
// and stops at 0 where the signed difference went below it; an invalid one
// (0 or 0x7fffffff) is left alone. Answers whether the timer is still
// valid afterwards, so a count that reaches 0 answers 0 at once.
int timer_count_down(Timer *t, float dt);

// A stamp the race has not set: 0 or 0x7fffffff. RacingCar's accessors
// and the HUD test each crossing with both.
#define TIMER_UNSET 0x7fffffffu
static inline int timer_is_valid(const Timer *t)
{
    return t->PackedTime != 0 && t->PackedTime != TIMER_UNSET;
}

// The flags PrintToString takes: a '-' in the first character, or a '+'.
// RenderHud's splits ask for the sign with 2; a negative time adds 1.
#define TIMER_PRINT_MINUS 1
#define TIMER_PRINT_SIGN  2

// GetHoursMinsSeconds, 0x001a3b28. The stamp as a signed count of ticks:
// the whole seconds split into hours, minutes and seconds by signed
// division, and the ticks left over over 4, the milliseconds.
void timer_get_hours_mins_seconds(const Timer *t, int32_t *h, int32_t *m,
                                  int32_t *s, int32_t *ms);

// PrintToString(char *, int flags, int h, int m, int s, int cs),
// 0x001a3838. A template by the largest unit that is not 0 and by the
// language (CurrLanguage, 0x0031c1c8, which the port takes as an
// argument), then the numbers written into it by IntToString2 (0x001a37b8,
// two places each, the first without leading zeros):
//
//   hours     "--h:--:--", or "--h:--'--\"" in French and Italian
//   minutes   "--:--.--" English, "--:--:--" German, Spanish, Swedish,
//             "--'--\"--" French, Italian
//   seconds   "   --.--", "   --:--", "   --\"--" the same way
//   neither   "    0.--", "    0:--", "    0\"--"
//
// With the sign asked for and ten or more hours or minutes, the text moves
// right one, losing its last character. Then a '-' goes in the first for
// flag 1, else a '+' for flag 2. `buf` takes at least 11 bytes.
//
// Retail does the move through the template itself, a bStrNCpy into the
// string in its data that leaves the template's digits as this call's;
// every later call writes the same places over, so the port moves through
// a copy instead.
void timer_print_to_string_hms(char *buf, int32_t flags, int32_t h,
                               int32_t m, int32_t s, int32_t cs,
                               int32_t language);

// Timer::PrintToString(char *, int flags), 0x001a3b98. An unset stamp
// prints as all zeros. Otherwise the parts of its size, and flag 1 added
// when it is negative; the hundredths are the milliseconds over 10.
void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t language);

// Timer::PrintToString(char *, float, int), 0x001a3ca0. The time rounded by
// RoundSeconds(f) into a Timer of its own by SetTime, then printed by the
// one above. The race-over overlay's times go through it with f = 0.01.
void timer_print_to_string_rounded(const Timer *t, char *buf, float f,
                                   int32_t flags, int32_t language);

#endif
