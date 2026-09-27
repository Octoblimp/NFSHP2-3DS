// bmath -- bMath.obj (0x00241bc8 .. 0x002424f8), nineteen functions.
//
// Ported instruction by instruction. Where the original's operation order
// looks gratuitous it is kept, because float32 is not associative and the
// cross-check in tools/bmath_check.py is exact, not approximate.
//
// docs/formats/bmath.md has the decode with an address for every rule.
#include "bmath.h"

#include <math.h>

#include "eefpu.h"

// The original negates with `subu x,zero,x` and takes absolute values with
// `pmaxw x,x,-x`, both of which wrap silently at INT32_MIN. C's unary minus
// does not -- it is undefined there -- so the wrap is spelled out.
static int32_t neg32(int32_t x)
{
    return (int32_t)(0u - (uint32_t)x);
}

static int32_t mul32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a * (uint32_t)b);
}

// The literals, with the addresses they were read from. All of these are
// float32 roundings held in the ELF, not computed constants -- writing
// 32768.0f/3.14159265f instead of BMATH_RAD_TO_BAM moves the last bit.
//
// There are two pools, and they are byte-identical where they overlap: bSin
// reads 0x00322294..0x003222b8 and bSinCos reads 0x003222bc..0x003222ec.
// One set of names covers both.
#define C_BAM_TO_RAD 9.587380191e-05f    // 0x00322294 / 0x003222bc
#define C_3PI_2      4.712388992f        // 0x00322298 / 0x003222c0
#define C_2PI        6.283185482f        // 0x0032229c / 0x003222c4
#define C_PI_2       1.570796371f        // 0x003222a0 / 0x003222c8
#define C_PI         3.141592741f        // 0x003222a4 / 0x003222cc
#define C_1_6        0.1666666716f       // 0x003222a8 / 0x003222d0
#define C_1_24       0.0416666679f       // 0x003222d4
#define C_1_120      0.008333333768f     // 0x003222ac / 0x003222d8
#define C_1_720      0.001388888923f     // 0x003222dc
#define C_1_5040     0.0001984127011f    // 0x003222b0 / 0x003222e0
#define C_1_40320    2.480158764e-05f    // 0x003222e4
#define C_1_362880   2.755731884e-06f    // 0x003222b4 / 0x003222e8
#define C_1_3628800  2.755731998e-07f    // 0x003222ec
#define C_RAD_TO_BAM 10430.37793f        // 0x003222b8

// ----------------------------------------------------------------- integer

// 0x00241bc8. The doubling is a 32-bit shift in the original, so it wraps
// rather than widening: bInverse(1) is 0xfffffffe, i.e. -2.
int32_t bInverse(int32_t x)
{
    if (x == 0) {
        return 0x7fffffff;
    }
    return (int32_t)((uint32_t)(0x7fffffff / x) << 1);
}

// 0x00241bf8. Dividing by zero saturates by the sign of the numerator
// instead of trapping; 0/0 is 0.
int32_t bDiv(int32_t a, int32_t b)
{
    int64_t p;

    if (b == 0) {
        if (a == 0) {
            return 0;
        }
        return a > 0 ? 0x7fffffff : (int32_t)0x80000000;
    }
    p = (int64_t)a * (int64_t)(0x7fffffff / b);
    return (int32_t)((uint32_t)(int32_t)(p >> 16) << 1);
}

// 0x00241c68. Sixteen rounds of restoring square root; the accumulator holds
// twice the root all the way through, which is what the final shift undoes.
// The `r <<= 1` sits between the two halves of the remainder update in the
// original, and moving it changes the answer, so it stays where it is.
uint32_t bSqrt32(uint32_t n)
{
    uint32_t r = 0, rem = 0;
    int i;

    for (i = 0; i < 16; i++) {
        uint32_t hi = rem << 2;
        uint32_t t;
        r <<= 1;
        t = hi + (n >> 30);
        if (r < t) {
            rem = t - r - 1u;
            r += 2u;
        } else {
            rem = t;
        }
        n <<= 2;
    }
    return r >> 1;
}

// ------------------------------------------------------------------ random

uint32_t bDefaultSeed = 0x12345678u;   // 0x00324f90

// 0x00241cc8. The value handed back is the OLD seed reduced mod range, and
// the state moves afterwards -- so the draw immediately after a reseed is
// the seed itself, not a function of it.
int32_t bRandomI(int32_t range, uint32_t *seed)
{
    uint32_t s = *seed;
    uint32_t t, u, v;

    if (range == 0) {
        return 0;               // the original's divide-by-zero trap
    }
    t = s ^ 0x1d872b41u;
    u = t ^ (t >> 5);
    v = t ^ (u << 27);
    *seed = u ^ v;
    return (int32_t)(s % (uint32_t)range);
}

// 0x00241cb8. Falls straight through into bRandom(1, seed), so it always
// returns 0 -- and it advances the seed past the value just stored.
int32_t bSetRandomSeed(uint32_t s, uint32_t *seed)
{
    *seed = s;
    return bRandomI(1, seed);
}

// 0x00241d08. 0x30000000 is 2**-31.
float bRandomF(float f, uint32_t *seed)
{
    int32_t r = bRandomI(0x7fffffff, seed);
    float k = f * 4.656612873e-10f;

    if (r < 0) {
        // Unreachable: bRandomI(0x7fffffff, ...) is at most 0x7ffffffe. The
        // original carries gcc's unsigned-to-float fixup anyway, so so does
        // this.
        uint32_t h = ((uint32_t)r >> 1) | ((uint32_t)r & 1u);
        float t = (float)(int32_t)h;
        return k * (t + t);
    }
    return k * (float)r;
}

// ------------------------------------------------------------------ modulo

// 0x00241d80. Floored, so the result is in [0, |b|) whatever the sign of a.
float bFMod(float a, float b)
{
    float m = fabsf(b);
    float q = a / m;
    // cvt.w.s: toward zero, and saturating by sign past 2**31. A bare cast
    // is undefined there and x86 answers 0x80000000 for both ends, so a
    // quotient of 3e9 came back as 5.1e9 on the host. QuickSpline's
    // ClampParam is the caller that found it.
    float t = (float)ee_trunc_w(q);

    if (q < t) {
        t = t - 1.0f;
    }
    q = q - t;
    return q * m;
}

// 0x00241dc0. Floored too -- with the wart that an exact negative multiple
// comes back as |b| rather than 0. Shipped behaviour, reproduced.
int32_t bSignedMod(int32_t a, int32_t b)
{
    int32_t nb = neg32(b);
    int32_t m = nb > b ? nb : b;        // pmaxw b,b,-b
    int32_t p;

    if (m == 0) {
        return 0;               // the original's divide-by-zero trap
    }
    p = mul32(a / m, m);
    if (a < 0) {
        p = p - m;
    }
    return a - p;
}

// -------------------------------------------------------------------- trig

// 0x00241df8. Reduce into [-pi/2, pi/2] with a sign, then five Taylor terms.
// It overshoots -- bSinBam(0x4000) is 1.00000358, not 1.0 -- and the
// frontend's bloom is built on exactly that, so this is not sinf.
float bSinBam(uint16_t bam)
{
    float x = (float)(int32_t)(bam & 0xffff) * C_BAM_TO_RAD;
    float sign = 1.0f;
    float x2, x3, x5, x7, x9, r;

    if (C_3PI_2 <= x) {
        x = x - C_2PI;
    } else if (C_PI_2 <= x) {
        sign = -1.0f;
        x = x - C_PI;
    }
    x2 = x * x;
    x3 = x * x2;
    x5 = x3 * x2;
    x7 = x5 * x2;
    x9 = x7 * x2;
    r = x - x3 * C_1_6;
    r = r + x5 * C_1_120;
    r = r - x7 * C_1_5040;
    r = r + x9 * C_1_362880;
    return r * sign;
}

// 0x00241e98.
float bSinF(float radians)
{
    // The same saturating cvt.w.s: past +/-2**31 BAM the image gets
    // 0x7fffffff or 0x80000000, whose low sixteen bits are 0xffff and 0.
    return bSinBam((uint16_t)ee_trunc_w(radians * C_RAD_TO_BAM));
}

// 0x00241ec8, minus a dead divide-by-360 guard the compiler left behind.
float bCosBam(uint16_t bam)
{
    return bSinBam((uint16_t)(bam + 16384));
}

// 0x00241ef8. The same reduction, then the two series interleaved. Both
// results take the same sign, because the reduction's pi shift negates sine
// and cosine alike.
void bSinCos(float *s, float *c, uint16_t bam)
{
    float x = (float)(int32_t)(bam & 0xffff) * C_BAM_TO_RAD;
    float sign = 1.0f;
    float x2, x3, x4, x5, x6, x7, x8, x9, x10;
    float rs, rc;

    if (C_3PI_2 <= x) {
        x = x - C_2PI;
    } else if (C_PI_2 <= x) {
        sign = -1.0f;
        x = x - C_PI;
    }
    x2 = x * x;
    x3 = x * x2;
    x4 = x2 * x2;
    x5 = x3 * x2;
    x6 = x4 * x2;
    x7 = x5 * x2;
    x8 = x6 * x2;
    x9 = x7 * x2;
    x10 = x8 * x2;

    rc = 1.0f - x2 * 0.5f;
    rs = x - x3 * C_1_6;
    rc = rc + x4 * C_1_24;
    rs = rs + x5 * C_1_120;
    rc = rc - x6 * C_1_720;
    rs = rs - x7 * C_1_5040;
    rc = rc + x8 * C_1_40320;
    rs = rs + x9 * C_1_362880;
    rc = rc - x10 * C_1_3628800;

    *s = rs * sign;
    *c = rc * sign;
}

// 0x00242000. Twelve octaves of sixteen buckets, linearly interpolated.
//
// The octave search reads like a binary search and is not one: it only ever
// adds, walking 0x8000, 0xc000, 0xe000, ... while it stays at or below the
// input, and the loop backs its last step out on the way out.
int32_t bASin(float x)
{
    int neg = 0;
    int32_t v, oct, base, width, bucket, lo, idx, r;
    const BASinEntry *e;

    if (x < 0.0f) {
        x = -x;
        neg = 1;
    }

    if (1.0f <= x) {
        return neg ? 0xc000 : 16384;
    }

    v = (int32_t)(x * 65536.0f);
    oct = 0;
    width = 0x8000;
    base = 0x8000;
    if (v < base) {
        base = 0;
    } else {
        width >>= 1;
        for (;;) {
            base += width;
            oct++;
            if (v < base) {
                base -= width;
                break;
            }
            if (oct >= 11) {
                base -= width;
                break;
            }
            width >>= 1;
        }
    }

    bucket = (v - base) >> (11 - oct);
    lo = base + mul32(bucket, width >> 4);
    idx = (oct << 4) + bucket;
    e = &bASinTable[idx];
    r = (int32_t)e->angle
        + (int32_t)((x - (float)lo * 1.52587890625e-05f) * e->slope * 65536.0f);
    if (neg) {
        r = neg32(r);
    }
    return r & 0xffff;
}

// 0x00242148. atan2(y, x) in BAM -- x is the FIRST argument. The quadrant
// falls out of the signs; the magnitude is one bASin of the smaller leg over
// the hypotenuse, which keeps the argument inside the table's good range.
int32_t bATan(float x, float y)
{
    int q = (x < 0.0f) ? 1 : 0;
    float arg;
    int32_t r;

    if (y < 0.0f) {
        q ^= 3;
    }
    // The two zero guards are not cosmetic. The second one is the only thing
    // standing between bATan(0, 0) and a 0/0, and a NaN here walks straight
    // off the end of bASinTable.
    if (fabsf(y) < fabsf(x)) {
        arg = (y == 0.0f) ? 0.0f : fabsf(y) / sqrtf(y * y + x * x);
        r = bASin(arg);
    } else {
        arg = (x == 0.0f) ? 0.0f : fabsf(x) / sqrtf(y * y + x * x);
        r = (16384 - bASin(arg)) & 0xffff;
    }

    switch (q) {
    case 0:  return r & 0xffff;
    case 1:  return (0x8000 - r) & 0xffff;
    case 2:  return (r - 0x8000) & 0xffff;
    default: return (-r) & 0xffff;
    }
}

// ------------------------------------------------------- trig, fixed point

// 0x00242268. The table is Q15 and both taps are doubled before the lerp, so
// a result of "1.0" is 65534 rather than 65536.
int32_t bFixSin(uint16_t bam)
{
    int32_t a = bam & 0xffff;
    int32_t i = a >> 7;
    int32_t frac = (a << 9) & 0xffff;
    int32_t lo = (int32_t)bSinTable[i] << 1;
    int32_t hi = (int32_t)bSinTable[i + 1] << 1;

    return lo + ((int32_t)((uint32_t)(hi - lo) * (uint32_t)frac) >> 16);
}

// 0x002422b0.
void bFixSinCos(int32_t *s, int32_t *c, uint16_t bam)
{
    *s = bFixSin(bam);
    *c = bFixSin((uint16_t)(bam + 16384));
}

// 0x00242308. Four ranges: two interpolated tables, then a crude linear ramp
// from atan(32) to atan(256), then saturation.
//
// There is a visible seam where the tables hand over to the ramp -- at
// t = 0x001fffff the table says 16058 and the ramp says 16093, a fifth of a
// degree. It is in the shipped code.
//
// One input is the port's own. INT32_MIN negates to itself, so the image's
// signed `slti` sends it to the low table with an index of -0x100000 and
// reads 2 MB before it. Nothing in the game passes it -- bFixATan2 does only
// for y = INT32_MIN, x = 0 -- but at -O3 gcc folds that path's address into
// a constant, and a negative absolute address is a relocation the 3DSX
// loader refuses: Azahar would not start the build that first linked
// bFixATan2. Compared unsigned, the magnitude saturates, as -0x7fffffff's
// does; every other input compares the same either way.
int32_t bFixATan1(int32_t t)
{
    int neg = 0;
    int32_t lo, hi, frac, r;

    if (t < 0) {
        neg = 1;
        t = neg32(t);
    }

    if ((uint32_t)t > 0x001fffffu) {
        if ((uint32_t)t > 0x00ffffffu) {
            lo = 16383;
            hi = 16383;
            frac = 0;
        } else {
            lo = 16058;                 // bFixATanTableHigh[128], atan(32)
            hi = 16343;                 // atan(256)
            frac = t >> 8;
        }
    } else if (t > 0x0003ffff) {
        int32_t i = t >> 14;
        lo = bFixATanTableHigh[i];
        hi = bFixATanTableHigh[i + 1];
        frac = (t << 2) & 0xffff;
    } else {
        int32_t i = t >> 11;
        lo = bFixATanTableLow[i];
        hi = bFixATanTableLow[i + 1];
        frac = (t << 5) & 0xffff;
    }

    r = lo + ((int32_t)((uint32_t)(hi - lo) * (uint32_t)frac) >> 16);
    return (neg ? -r : r) & 0xffff;
}

// 0x002423e0. atan2(y, x) again, x first, same four-case fixup as bATan.
// The (|y| >> 14) < |x| test is an overflow guard on bDiv, not a precision
// one: past it the answer is pinned at 90 degrees.
int32_t bFixATan2(int32_t x, int32_t y)
{
    int q = (x < 0) ? 1 : 0;
    int32_t r;

    if (y < 0) {
        q ^= 3;
    }
    if (x < 0) {
        x = neg32(x);
    }
    if (y < 0) {
        y = neg32(y);
    }
    r = ((y >> 14) < x) ? bFixATan1(bDiv(y, x)) : 16384;

    switch (q) {
    case 0:  return r & 0xffff;
    case 1:  return (0x8000 - r) & 0xffff;
    case 2:  return (r - 0x8000) & 0xffff;
    default: return (-r) & 0xffff;
    }
}

// ------------------------------------------------------------------- polar

// 0x002424a0. `(x * x) + (y * y)` and `sqrt.s`, then bATan with the two
// components still in $f12 and $f13 -- x first, as always. The image stores
// the angle before the radius, which nothing can see.
//
// Documented with the rest of bMath.obj from the start, and the nineteenth
// of its nineteen functions, but the last to be ported: nothing called it
// until Car::IsCarInFront.
bPolar *bToPolar(bPolar *out, const bVector2 *v)
{
    float r = sqrtf(v->x * v->x + v->y * v->y);

    out->a = (uint16_t)bATan(v->x, v->y);
    out->r = r;
    return out;
}
