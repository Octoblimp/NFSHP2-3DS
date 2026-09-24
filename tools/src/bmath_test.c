// Host harness for the bware scalar math library.
//
// Builds "3DS Files/source/bmath.c" plus its generated tables for the host
// and sweeps every entry point, printing one line per call:
//
//     scenario <name>
//     <op> <inputs> -> <outputs>
//
// tools/bmath_check.py prints the same from a Python model written off the
// disassembly at 0x00241bc8 rather than off this code, and diffs the two.
//
// Floats print as %.9g -- more significant digits than a float32 holds, so
// the text pins the bits exactly. Every input float is built from an integer
// over a power of two, so both sides start from the same bits without having
// to agree on how a decimal literal rounds.
//
// Two things are deliberately NOT swept:
//
//   * INT32_MIN through bSignedMod and bFixATan2. The EE's `div` with a -1
//     divisor is architecturally undefined and the port would have to invent
//     an answer; no caller in the game goes there.
//   * Anything that would make the EE FPU produce a denormal, an infinity or
//     a NaN. It has none of those -- it flushes and saturates -- so a test
//     that provoked one would be testing the host, not the port.
//
// Usage: bmath_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "bmath.h"

// A float from an exact dyadic rational, so the Python side gets the same
// bits without parsing a decimal.
static float dy(int32_t num, int shift)
{
    return (float)num / (float)(1 << shift);
}

// ------------------------------------------------------------------ integer

static void s_inverse(void)
{
    static const int32_t v[] = {
        0, 1, -1, 2, -2, 3, -3, 4, 7, 10, 16, 100, 255, 256, 1000, 4096,
        65535, 65536, 1000000, 0x10000000, 0x40000000, 0x7fffffff,
        -7, -100, -65536, -0x40000000, -0x7fffffff,
    };
    size_t i;

    for (i = 0; i < sizeof v / sizeof v[0]; i++) {
        printf("inverse %11d -> %11d\n", v[i], bInverse(v[i]));
    }
}

static void s_div(void)
{
    static const int32_t n[] = {
        0, 1, -1, 2, -2, 5, -5, 100, -100, 65536, -65536, 1000000,
        0x7fffffff, -0x7fffffff,
    };
    static const int32_t d[] = {
        0, 1, -1, 2, -2, 3, 7, -7, 100, 256, 65536, -65536, 0x7fffffff,
    };
    size_t i, j;

    for (i = 0; i < sizeof n / sizeof n[0]; i++) {
        for (j = 0; j < sizeof d / sizeof d[0]; j++) {
            printf("div %11d %11d -> %11d\n", n[i], d[j], bDiv(n[i], d[j]));
        }
    }
}

static void s_sqrt32(void)
{
    uint32_t n;
    int k;

    for (n = 0; n <= 40; n++) {
        printf("sqrt32 %10u -> %10u\n", n, bSqrt32(n));
    }
    for (k = 0; k < 32; k++) {
        uint32_t u = 1u << k;
        printf("sqrt32 %10u -> %10u\n", u - 1u, bSqrt32(u - 1u));
        printf("sqrt32 %10u -> %10u\n", u, bSqrt32(u));
        printf("sqrt32 %10u -> %10u\n", u + 1u, bSqrt32(u + 1u));
    }
    for (k = 1; k <= 64; k++) {
        uint32_t r = (uint32_t)k * 1013u;
        uint32_t sq = r * r;
        printf("sqrt32 %10u -> %10u\n", sq - 1u, bSqrt32(sq - 1u));
        printf("sqrt32 %10u -> %10u\n", sq, bSqrt32(sq));
        printf("sqrt32 %10u -> %10u\n", sq + 1u, bSqrt32(sq + 1u));
    }
    printf("sqrt32 %10u -> %10u\n", 0xfffffffeu, bSqrt32(0xfffffffeu));
    printf("sqrt32 %10u -> %10u\n", 0xffffffffu, bSqrt32(0xffffffffu));
}

// ------------------------------------------------------------------- random

static void s_random(void)
{
    static const uint32_t seeds[] = {0u, 1u, 12345u, 0xdeadbeefu, 0xffffffffu};
    static const int32_t ranges[] = {0, 1, 2, 6, 100, 65536, 0x7fffffff};
    size_t i, j;
    int k;

    for (i = 0; i < sizeof seeds / sizeof seeds[0]; i++) {
        for (j = 0; j < sizeof ranges / sizeof ranges[0]; j++) {
            uint32_t seed = 0;
            int32_t r0 = bSetRandomSeed(seeds[i], &seed);
            printf("seed %10u range %11d -> setret %d state %10u\n",
                   seeds[i], ranges[j], r0, seed);
            for (k = 0; k < 6; k++) {
                int32_t r = bRandomI(ranges[j], &seed);
                printf("  randi -> %11d state %10u\n", r, seed);
            }
        }
    }
}

static void s_randomf(void)
{
    static const uint32_t seeds[] = {0u, 7u, 0x5f3759dfu};
    static const int32_t scale[] = {0, 1, 2, -1, 100, 4096};
    size_t i, j;
    int k;

    for (i = 0; i < sizeof seeds / sizeof seeds[0]; i++) {
        for (j = 0; j < sizeof scale / sizeof scale[0]; j++) {
            uint32_t seed = 0;
            float f = dy(scale[j], 0);
            (void)bSetRandomSeed(seeds[i], &seed);
            printf("seedf %10u scale %.9g\n", seeds[i], (double)f);
            for (k = 0; k < 5; k++) {
                float r = bRandomF(f, &seed);
                printf("  randf -> %.9g state %10u\n", (double)r, seed);
            }
        }
    }
}

// ------------------------------------------------------------------- modulo

static void s_fmod(void)
{
    static const int32_t a[] = {
        0, 1, -1, 7, -7, 64, -64, 100, -100, 1000, -1000, 12345, -12345,
    };
    static const int32_t b[] = {1, -1, 2, -2, 6, -6, 64, 360, -360};
    size_t i, j;

    for (i = 0; i < sizeof a / sizeof a[0]; i++) {
        for (j = 0; j < sizeof b / sizeof b[0]; j++) {
            float x = dy(a[i], 2);      // quarters, so the fraction matters
            float y = dy(b[j], 0);
            printf("fmod %.9g %.9g -> %.9g\n",
                   (double)x, (double)y, (double)bFMod(x, y));
        }
    }
    // Quotients past 2**31, where cvt.w.s saturates by sign. QuickSpline's
    // ClampParam hands bFMod whatever t it is given.
    {
        static const int32_t ha[] = {
            2000000000, -2000000000, 1500000000, 0x7fffff80, -0x7fffff80,
        };
        static const int32_t hb[][2] = {{1, 1}, {1, 2}, {-1, 3}, {3, 2}, {1, 0}};
        for (i = 0; i < sizeof ha / sizeof ha[0]; i++) {
            for (j = 0; j < sizeof hb / sizeof hb[0]; j++) {
                float x = dy(ha[i], 0);
                float y = dy(hb[j][0], hb[j][1]);
                printf("fmod %.9g %.9g -> %.9g\n",
                       (double)x, (double)y, (double)bFMod(x, y));
            }
        }
    }
}

static void s_signedmod(void)
{
    static const int32_t a[] = {
        0, 1, -1, 2, -2, 5, -5, 6, -6, 7, -7, 12, -12, 100, -100,
        0x7fffffff, -0x7fffffff,
    };
    static const int32_t b[] = {0, 1, -1, 2, -2, 3, -3, 6, 360, -360, 65536};
    size_t i, j;

    for (i = 0; i < sizeof a / sizeof a[0]; i++) {
        for (j = 0; j < sizeof b / sizeof b[0]; j++) {
            printf("smod %11d %11d -> %11d\n", a[i], b[j],
                   bSignedMod(a[i], b[j]));
        }
    }
}

// --------------------------------------------------------------------- trig

// 0, 1, 2, ... 65535 is far too much output; 257 evenly spaced samples plus
// the four quadrant corners and the seams either side of them is enough to
// catch a wrong reduction, and cheap to read.
static void bam_sweep(void (*f)(uint16_t))
{
    static const uint16_t edge[] = {
        0, 1, 16383, 16384, 16385, 24575, 24576, 24577,
        32767, 32768, 32769, 49151, 49152, 49153, 65534, 65535,
    };
    size_t i;
    int k;

    for (k = 0; k < 257; k++) {
        f((uint16_t)(k * 256));
    }
    for (i = 0; i < sizeof edge / sizeof edge[0]; i++) {
        f(edge[i]);
    }
}

static void one_sin(uint16_t bam)
{
    printf("sin %5u -> %.9g\n", bam, (double)bSinBam(bam));
}

static void one_cos(uint16_t bam)
{
    printf("cos %5u -> %.9g\n", bam, (double)bCosBam(bam));
}

static void one_sincos(uint16_t bam)
{
    float s = 0.0f, c = 0.0f;
    bSinCos(&s, &c, bam);
    printf("sincos %5u -> %.9g %.9g\n", bam, (double)s, (double)c);
}

static void one_fixsin(uint16_t bam)
{
    printf("fixsin %5u -> %11d\n", bam, bFixSin(bam));
}

static void one_fixsincos(uint16_t bam)
{
    int32_t s = 0, c = 0;
    bFixSinCos(&s, &c, bam);
    printf("fixsincos %5u -> %11d %11d\n", bam, s, c);
}

static void s_sin(void)       { bam_sweep(one_sin); }
static void s_cos(void)       { bam_sweep(one_cos); }
static void s_sincos(void)    { bam_sweep(one_sincos); }
static void s_fixsin(void)    { bam_sweep(one_fixsin); }
static void s_fixsincos(void) { bam_sweep(one_fixsincos); }

static void s_sinf(void)
{
    int k;

    for (k = -64; k <= 64; k++) {
        float x = dy(k, 4);             // sixteenths of a radian, +/- 4 rad
        printf("sinf %.9g -> %.9g\n", (double)x, (double)bSinF(x));
    }
    // And a pass out to +/-64 radians. Nothing in the game calls bSinF
    // with an angle that big, but the product is truncated to a whole BAM,
    // so a one-ulp error in RAD_TO_BAM stays invisible until the product is
    // large enough to cross an integer. At +/-4 radians it never is.
    for (k = -256; k <= 256; k++) {
        float x = dy(k, 2);
        printf("sinf %.9g -> %.9g\n", (double)x, (double)bSinF(x));
    }
    // Whole radians big enough that the BAM product passes 2**31 and
    // cvt.w.s saturates; 205887 is the last below.
    {
        static const int32_t big[] = {
            205887, 205888, 300000, -300000, 1000000, -1000000,
            2000000000, -2000000000,
        };
        size_t i;
        for (i = 0; i < sizeof big / sizeof big[0]; i++) {
            float x = dy(big[i], 0);
            printf("sinf %.9g -> %.9g\n", (double)x, (double)bSinF(x));
        }
    }
}

static void s_asin(void)
{
    int k;

    for (k = -256; k <= 256; k++) {
        float x = dy(k, 8);
        printf("asin %.9g -> %11d\n", (double)x, bASin(x));
    }
    // Those all land exactly on a bucket's left edge in the low
    // octaves, so they multiply the secant slope by zero and never
    // test it. Half a step over fixes that.
    for (k = -256; k < 256; k++) {
        float x = dy(2 * k + 1, 9);
        printf("asin %.9g -> %11d\n", (double)x, bASin(x));
    }
    // The top sixty-four sixty-five-thousand-five-hundred-and-thirty-
    // sixths, where the octave walk runs out of octaves and its own
    // oct >= 11 guard is all that stops a shift by a negative amount.
    for (k = 1; k <= 64; k++) {
        float x = dy(65536 - k, 16);
        printf("asin %.9g -> %11d\n", (double)x, bASin(x));
        printf("asin %.9g -> %11d\n", (double)-x, bASin(-x));
    }
    // Outside [-1, 1] it saturates; just either side of the clamp.
    printf("asin %.9g -> %11d\n", (double)dy(257, 8), bASin(dy(257, 8)));
    printf("asin %.9g -> %11d\n", (double)dy(-257, 8), bASin(dy(-257, 8)));
    printf("asin %.9g -> %11d\n", (double)dy(64, 4), bASin(dy(64, 4)));
}

static void s_atan(void)
{
    int ix, iy;

    for (ix = -8; ix <= 8; ix++) {
        for (iy = -8; iy <= 8; iy++) {
            float x = dy(ix, 2);
            float y = dy(iy, 2);
            printf("atan %.9g %.9g -> %11d\n",
                   (double)x, (double)y, bATan(x, y));
        }
    }
    // The long thin cases, where one leg dwarfs the other.
    for (ix = 1; ix <= 12; ix++) {
        float big = dy(1 << ix, 0);
        printf("atan %.9g %.9g -> %11d\n",
               (double)big, 1.0, bATan(big, 1.0f));
        printf("atan %.9g %.9g -> %11d\n",
               1.0, (double)big, bATan(1.0f, big));
        printf("atan %.9g %.9g -> %11d\n",
               (double)-big, 1.0, bATan(-big, 1.0f));
        printf("atan %.9g %.9g -> %11d\n",
               1.0, (double)-big, bATan(1.0f, -big));
    }
}

static void s_fixatan1(void)
{
    static const int32_t edge[] = {
        0, 1, 0x7ff, 0x800, 0x801, 0x3ffff, 0x40000, 0x40001,
        0x3fff, 0x4000, 0x1ffffe, 0x1fffff, 0x200000, 0x200001,
        0xfffffe, 0xffffff, 0x1000000, 0x1000001, 0x7fffffff,
    };
    size_t i;
    int k;

    for (k = 0; k <= 96; k++) {
        int32_t t = k * 0x5555;                 // across the low table
        printf("fatan1 %11d -> %11d\n", t, bFixATan1(t));
        printf("fatan1 %11d -> %11d\n", -t, bFixATan1(-t));
    }
    for (k = 0; k <= 64; k++) {
        int32_t t = 0x40000 + k * 0x7000;       // across the high table
        printf("fatan1 %11d -> %11d\n", t, bFixATan1(t));
    }
    for (k = 0; k <= 32; k++) {
        int32_t t = 0x200000 + k * 0x70000;     // across the ramp
        printf("fatan1 %11d -> %11d\n", t, bFixATan1(t));
    }
    for (i = 0; i < sizeof edge / sizeof edge[0]; i++) {
        printf("fatan1 %11d -> %11d\n", edge[i], bFixATan1(edge[i]));
        printf("fatan1 %11d -> %11d\n", -edge[i], bFixATan1(-edge[i]));
    }
}

static void s_fixatan2(void)
{
    static const int32_t v[] = {
        0, 1, -1, 0x10000, -0x10000, 0x20000, -0x20000, 0x80000, -0x80000,
        0x400000, -0x400000, 0x10000000, -0x10000000,
    };
    size_t i, j;

    for (i = 0; i < sizeof v / sizeof v[0]; i++) {
        for (j = 0; j < sizeof v / sizeof v[0]; j++) {
            printf("fatan2 %11d %11d -> %11d\n", v[i], v[j],
                   bFixATan2(v[i], v[j]));
        }
    }
}

// -------------------------------------------------------------------- polar

// The atan grid again, the long thin legs, and six wide pairs in all four
// quadrants. The wide ones are there for the radius: their squares round,
// so sqrtf of the rounded sum and a correctly-rounded hypotf disagree in
// the last bit for each of them. The grid's squares are exact, and there
// the two can never differ.
static void s_topolar(void)
{
    static const int32_t wide[6][2] = {
        {2893789, 2707410}, {2718082, 1925942}, {1020165, 694390},
        {2671451, 1521480}, {2464977, 2338812}, {3321659, 2144691},
    };
    bVector2 v;
    bPolar p;
    const bPolar *ret;
    int ix, iy, k, q;

    for (ix = -8; ix <= 8; ix++) {
        for (iy = -8; iy <= 8; iy++) {
            v.x = dy(ix, 2);
            v.y = dy(iy, 2);
            bToPolar(&p, &v);
            printf("polar %.9g %.9g -> %.9g %5u\n",
                   (double)v.x, (double)v.y, (double)p.r, p.a);
        }
    }
    for (ix = 1; ix <= 12; ix++) {
        v.x = dy(1 << ix, 0);
        v.y = -1.0f;
        bToPolar(&p, &v);
        printf("polar %.9g %.9g -> %.9g %5u\n",
               (double)v.x, (double)v.y, (double)p.r, p.a);
    }
    for (k = 0; k < 6; k++) {
        for (q = 0; q < 4; q++) {
            v.x = dy((q & 1) ? -wide[k][0] : wide[k][0], 16);
            v.y = dy((q & 2) ? -wide[k][1] : wide[k][1], 16);
            // The return is `out`, and the checker holds it to that.
            p.r = -1.0f;
            p.a = 0xdead;
            ret = bToPolar(&p, &v);
            printf("polar %.9g %.9g -> %.9g %5u %s\n",
                   (double)v.x, (double)v.y, (double)p.r, p.a,
                   (ret == &p) ? "out" : "other");
        }
    }
}

// --------------------------------------------------------------- the tables

// Not a function test -- a check that bmathtab.c holds what the ELF holds.
// The checker reads the ELF itself, so a bad generator run shows up here.
static void s_tables(void)
{
    int i;

    for (i = 0; i <= 512; i++) {
        printf("sintab %3d -> %11d\n", i, (int)bSinTable[i]);
    }
    for (i = 0; i < 209; i++) {
        printf("asintab %3d -> %5u %.9g\n", i,
               (unsigned)bASinTable[i].angle, (double)bASinTable[i].slope);
    }
    for (i = 0; i <= 128; i++) {
        printf("atanlo %3d -> %5u   atanhi %3d -> %5u\n",
               i, (unsigned)bFixATanTableLow[i],
               i, (unsigned)bFixATanTableHigh[i]);
    }
}

// --------------------------------------------------------------------- main

static const struct { const char *name; void (*fn)(void); } SCENARIOS[] = {
    {"inverse",    s_inverse},
    {"div",        s_div},
    {"sqrt32",     s_sqrt32},
    {"random",     s_random},
    {"randomf",    s_randomf},
    {"fmod",       s_fmod},
    {"signedmod",  s_signedmod},
    {"sin",        s_sin},
    {"sinf",       s_sinf},
    {"cos",        s_cos},
    {"sincos",     s_sincos},
    {"asin",       s_asin},
    {"atan",       s_atan},
    {"fixsin",     s_fixsin},
    {"fixsincos",  s_fixsincos},
    {"fixatan1",   s_fixatan1},
    {"fixatan2",   s_fixatan2},
    {"topolar",    s_topolar},
    {"tables",     s_tables},
};

#define NSCENARIOS ((int)(sizeof SCENARIOS / sizeof SCENARIOS[0]))

int main(int argc, char **argv)
{
    int i, a;

    if (argc < 2) {
        for (i = 0; i < NSCENARIOS; i++) {
            printf("scenario %s\n", SCENARIOS[i].name);
            SCENARIOS[i].fn();
        }
        return 0;
    }
    for (a = 1; a < argc; a++) {
        for (i = 0; i < NSCENARIOS; i++) {
            if (strcmp(argv[a], SCENARIOS[i].name) == 0) {
                printf("scenario %s\n", SCENARIOS[i].name);
                SCENARIOS[i].fn();
                break;
            }
        }
        if (i == NSCENARIOS) {
            fprintf(stderr, "unknown scenario: %s\n", argv[a]);
            return 1;
        }
    }
    return 0;
}
