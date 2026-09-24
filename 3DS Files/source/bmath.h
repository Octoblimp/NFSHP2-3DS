// bmath -- bware's scalar math library, out of bMath.obj (0x00241bc8).
//
// Nineteen functions: integer reciprocal and divide, an integer square root,
// a random generator, two modulos, and the trigonometry the whole engine
// runs on. Everything angular is a BAM -- a 16-bit binary angle where
// 0x4000 is 90 degrees -- and the trig is table- and series-driven, not a
// call out to libm.
//
// That last part is the reason this is ported rather than replaced. bSin
// (0x00241df8) is a five-term Taylor series that overshoots: at the peak it
// returns 1.00000358, and the frontend's bloom animation is already built on
// that number. Swapping in sinf would move pixels. The same goes for bASin,
// which is a 209-entry piecewise-linear table good to 0.011 degrees, and for
// bFixSin, which interpolates a 513-entry Q15 table.
//
// The four tables live in bmathtab.c, generated from the ELF by
// tools/gen_bmath_tables.py. Written up in docs/formats/bmath.md.
#ifndef BMATH_H
#define BMATH_H

#include <stdint.h>

#include "bvector.h"

// ------------------------------------------------------------------- angles

// Both constants are the float32 literals the game holds. RAD_TO_BAM is the
// correctly-rounded float32 of 32768/pi -- 10430.3779296875 against the exact
// 10430.3783504705, so 0.04 ppm low. That sounds far too small to matter and
// is not: int(atan(1.0) * K) is 8191 with the float32 and 8192 with the
// double, and that one entry is what identified the atan tables' generator.
#define BMATH_RAD_TO_BAM 10430.37793f
#define BMATH_BAM_TO_RAD 9.587380191e-05f

// --------------------------------------------------------------- the tables

typedef struct BASinEntry {
    uint16_t angle;   // BAM at the bucket's left edge
    float    slope;   // slope across the bucket, in turns per unit x
} BASinEntry;

// 209, not 192. The twelve octaves of sixteen buckets are indices 0..191;
// 192..207 are the tail bASin reaches when its octave walk stops on the
// `oct >= 11` guard rather than on a comparison, which happens for
// x >= 0.99976. 208 is a terminator and is never read.

extern const int16_t    bSinTable[513];
extern const BASinEntry bASinTable[209];
extern const uint16_t   bFixATanTableLow[129];
extern const uint16_t   bFixATanTableHigh[129];

// ------------------------------------------------------------------ integer

// 0 in, 0x7fffffff out; otherwise about 2**32 / x, so it pairs with a >> 16
// to make a Q16 reciprocal.
int32_t bInverse(int32_t x);

// a / b in Q16. Dividing by zero saturates to +/-0x7fffffff by the sign of a
// (and 0 for 0/0) rather than trapping.
int32_t bDiv(int32_t a, int32_t b);

// Sixteen rounds of restoring square root. Exactly floor(sqrt(n)) -- checked
// against math.isqrt over 44,003 values in the harness.
uint32_t bSqrt32(uint32_t n);

// ------------------------------------------------------------------- random

// Seeds, then returns bRandom(1, seed) -- which is always 0, because the
// original falls straight through into it. Kept because callers use the
// return value's existence, not its value.
int32_t bSetRandomSeed(uint32_t s, uint32_t *seed);

// Returns the OLD seed modulo range, then advances the seed by a three-step
// xorshift. Note the order: the value handed back is computed before the
// state moves, so the first draw after a reseed is the seed itself.
int32_t bRandomI(int32_t range, uint32_t *seed);
float   bRandomF(float f, uint32_t *seed);

// gp-15456, 0x00324f90: the seed callers pass when they have none of their
// own. 0x12345678 in the image.
extern uint32_t bDefaultSeed;

// ------------------------------------------------------------------- modulo

// Floored, not truncated: the result is always in [0, |b|).
float bFMod(float a, float b);

// The integer twin -- with one wart. An exact negative multiple of b comes
// back as |b| rather than 0. It is in the shipped code and it is reproduced.
int32_t bSignedMod(int32_t a, int32_t b);

// --------------------------------------------------------------------- trig

float bSinBam(uint16_t bam);      // the series; overshoots to 1.00000358
float bSinF(float radians);       // bSinBam((uint16_t)(int)(x * RAD_TO_BAM))
float bCosBam(uint16_t bam);      // bSinBam(bam + 16384)
void  bSinCos(float *s, float *c, uint16_t bam);

// asin, in BAM, saturating to +/-16384 outside [-1, 1].
int32_t bASin(float x);

// atan2(y, x) in BAM -- note the argument order, x first. The quadrant comes
// out of the signs and the magnitude out of one bASin call.
int32_t bATan(float x, float y);

// The fixed-point side. bFixSin's result is Q16-ish: 1.0 comes back as
// 65534, because the table is Q15 and the code doubles it.
int32_t bFixSin(uint16_t bam);
void    bFixSinCos(int32_t *s, int32_t *c, uint16_t bam);

// atan of a Q16 tangent, and atan2 of a Q16 pair, both in BAM.
int32_t bFixATan1(int32_t t);
int32_t bFixATan2(int32_t x, int32_t y);

// ------------------------------------------------------------------- polar

// The length of `v` and bATan(v->x, v->y). Returns `out`.
bPolar *bToPolar(bPolar *out, const bVector2 *v);

#endif // BMATH_H
