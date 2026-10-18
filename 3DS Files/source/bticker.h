// bticker -- bWare's cycle counter, out of the ticker object at
// 0x00238d08 .. 0x00238d9c in NFSHP2.ELF (four functions, 140 bytes).
//
// On the PS2 a tick is the EE's COP0 Count register, which runs at the CPU
// clock, 294.912 MHz, and wraps every 14.56 seconds. bGetTicker is
// `mfc0 v0, Count` and nothing else, and every timing in the game is a
// difference of two of them: the frame time in World::GetTimestep, the
// physics budget in PhysicsCar::Move, the ComputeAuxiliaries stopwatch.
//
// The port keeps that tick. On the 3DS, bGetTicker scales the ARM11's
// system tick (268.111856 MHz) to 294.912 MHz and truncates it to 32 bits,
// so a difference means the same number of EE cycles it meant on the
// console and wraps at the same period. **bGetTickerDifference does not
// divide by 294.912 MHz** -- it divides by 300 MHz (gp-26980, 0x4d8f0d18),
// so every millisecond the game measures is 1.7% short. That is the
// image's, and it is kept.
//
// See docs/formats/physics-system.md.

#ifndef BTICKER_H
#define BTICKER_H

#include <stdint.h>

// The EE's Count rate, which the 3DS tick is scaled to.
#define BTICKER_RATE_HZ 294912000u

// The rate bGetTickerDifference *assumes*, gp-26980.
#define BTICKER_ASSUMED_HZ 300000000.0f

// 0x00238d08. `jr ra`: the counter needs no setting up.
void bInitTicker(void);

// 0x00238d10. The current tick.
uint32_t bGetTicker(void);

// 0x00238d20. Milliseconds from `from` to `to`:
//
//   d = to - from, as an unsigned 32-bit difference, so it survives a wrap
//   f = (float)d, which the listing does in two steps because cvt.s.w is
//       signed: when d has its top bit set it converts (d >> 1) | (d & 1)
//       and doubles the result, keeping the low bit so the rounding is the
//       one an unsigned conversion would make
//   return f / 300e6 * 1000
float bGetTickerDifference(uint32_t from, uint32_t to);

// 0x00238d78. `((to - from) << 6) / 293`, unsigned, the shift wrapping at
// 32 bits: roughly a microsecond count, since 294.912 / 64 is about 4.6 and
// 293 / 64 is the same. The `break` the listing guards the divide with
// cannot fire -- the divisor is a constant.
uint32_t bGetFixTickerDifference(uint32_t from, uint32_t to);

// Not in the image. Where bGetTicker reads its tick: NULL, the default, is
// the platform's counter; a harness installs a function that returns
// scripted ticks. On the host build the platform counter is always 0.
typedef uint32_t (*bTickerSourceFn)(void);
void bSetTickerSource(bTickerSourceFn fn);

// Not in the image. The 3DS's system tick `t` as bGetTicker gives it:
// t * 294912000 / 268111856 rounded down, in 32 bits. On every build, so
// the host can check it against the division.
uint32_t bTickerFromSystemTick(uint64_t t);

#endif
