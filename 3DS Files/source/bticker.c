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

static uint32_t bPlatformTicker(void)
{
#ifdef __3DS__
    // tick * 294912000 / 268111856 without overflowing 64 bits: the whole
    // seconds and the remainder separately. The remainder is below
    // 268111856, so its product stays under 2^57.
    uint64_t t = svcGetSystemTick();
    uint64_t q = t / BTICKER_3DS_HZ;
    uint64_t r = t % BTICKER_3DS_HZ;
    return (uint32_t)(q * BTICKER_RATE_HZ
                      + r * BTICKER_RATE_HZ / BTICKER_3DS_HZ);
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
