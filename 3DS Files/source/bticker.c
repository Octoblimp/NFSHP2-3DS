// bticker -- see bticker.h.

#include "bticker.h"

#ifdef __3DS__
#include <3ds.h>
#endif

// The ARM11 system tick rate: SYSCLOCK_ARM11 in libctru's os.h, spelled out
// so the arithmetic below does not depend on the header's spelling of it.
#define BTICKER_3DS_HZ 268111856ull

static bTickerSourceFn bTickerSource;

void bSetTickerSource(bTickerSourceFn fn)
{
    bTickerSource = fn;
}

// The high 64 bits of a * b, from four 32-bit products.
static uint64_t mul_high(uint64_t a, uint64_t b)
{
    uint64_t al = (uint32_t)a, ah = a >> 32;
    uint64_t bl = (uint32_t)b, bh = b >> 32;
    uint64_t ll = al * bl, lh = al * bh, hl = ah * bl, hh = ah * bh;
    uint64_t mid = (ll >> 32) + (uint32_t)lh + (uint32_t)hl;

    return hh + (lh >> 32) + (hl >> 32) + (mid >> 32);
}

// n / BTICKER_3DS_HZ, with the remainder in *r. The ARM11 has no divide,
// and libgcc's 64-bit one is a long loop: bGetTicker took two of them,
// several per car a step in the physics' stopwatches (TASKS 46). So a
// multiply by 2^64 / BTICKER_3DS_HZ rounded down, which comes out at most
// one short -- n is under 2^64, so the reciprocal's error times n is under
// one -- and the step after makes it the quotient.
static uint64_t div_3ds_hz(uint64_t n, uint64_t *r)
{
    uint64_t q = mul_high(n, UINT64_MAX / BTICKER_3DS_HZ);

    *r = n - q * BTICKER_3DS_HZ;
    if (*r >= BTICKER_3DS_HZ) {
        q++;
        *r -= BTICKER_3DS_HZ;
    }
    return q;
}

uint32_t bTickerFromSystemTick(uint64_t t)
{
    // tick * 294912000 / 268111856 without overflowing 64 bits: the whole
    // seconds and the remainder separately. The remainder is below
    // 268111856, so its product stays under 2^57.
    uint64_t r, unused;
    uint64_t q = div_3ds_hz(t, &r);

    return (uint32_t)(q * BTICKER_RATE_HZ
                      + div_3ds_hz(r * BTICKER_RATE_HZ, &unused));
}

static uint32_t bPlatformTicker(void)
{
#ifdef __3DS__
    return bTickerFromSystemTick(svcGetSystemTick());
#else
    return 0;
#endif
}

void bInitTicker(void)
{
}

uint32_t bGetTicker(void)
{
    if (bTickerSource)
        return bTickerSource();
    return bPlatformTicker();
}

float bGetTickerDifference(uint32_t from, uint32_t to)
{
    uint32_t d = to - from;
    uint32_t half = d >> 1;          // the srl in the bltz delay slot
    float f;

    if ((int32_t)d >= 0) {
        f = (float)(int32_t)d;
    } else {
        f = (float)(int32_t)((d & 1u) | half);
        f = f + f;
    }
    return f / BTICKER_ASSUMED_HZ * 1000.0f;
}

uint32_t bGetFixTickerDifference(uint32_t from, uint32_t to)
{
    return ((to - from) << 6) / 293u;
}
