// bticker_test -- bTickerFromSystemTick (3DS Files/source/bticker.c)
// against the division it replaced, for tools/bticker_check.py.
//
// bGetTicker scales the 3DS's system tick to the EE's 294.912 MHz. It was
// `t / HZ * RATE + t % HZ * RATE / HZ` on 64 bits, and the ARM11 has no
// divide, so libgcc's long one ran twice a call (TASKS 46). The port now
// divides by a multiply and one correction. This runs both over:
//
//   - random ticks of every size, and a year of uptime's worth;
//   - each whole second's edges, for the first million seconds and the
//     last million below 2^64;
//   - each step of the remainder's product, near zero and five seconds in.
//
// It prints "N ticks, M differ" and exits 1 if any differ.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

#include "bticker.h"

#define HZ 268111856ull

static uint32_t old_ticks(uint64_t t)
{
    uint64_t q = t / HZ;
    uint64_t r = t % HZ;
    return (uint32_t)(q * BTICKER_RATE_HZ + r * BTICKER_RATE_HZ / HZ);
}

static uint64_t s = 0x9E3779B97F4A7C15ull;
static uint64_t rnd(void)
{
    s ^= s << 13; s ^= s >> 7; s ^= s << 17;
    return s;
}

static long bad;
static void one(uint64_t t)
{
    if (bTickerFromSystemTick(t) != old_ticks(t) && bad++ < 10)
        printf("t %llu: new %lu old %lu\n", (unsigned long long)t,
               (unsigned long)bTickerFromSystemTick(t),
               (unsigned long)old_ticks(t));
}

int main(void)
{
    long n = 10000000, i;
    uint64_t k, d;
    long count = 0;

    for (i = 0; i < n; i++) {
        uint64_t t = rnd();
        int sh = (int)(rnd() % 64);
        one(t);                     // anywhere
        one(t >> sh);               // every size
        one((t >> 20) % (HZ * 3600 * 24 * 365));  // a year of uptime
        count += 3;
    }
    // Each whole second and its neighbours, for the first million seconds
    // and near the top.
    for (k = 0; k < 1000000; k++) {
        for (d = 0; d < 3; d++) {
            one(k * HZ + d);
            if (k) one(k * HZ - 1 - d);
            count += 2;
        }
    }
    for (k = 0; k < 1000000; k++) {
        uint64_t top = UINT64_MAX - k;
        one(top);
        one((UINT64_MAX / HZ - k) * HZ);
        one((UINT64_MAX / HZ - k) * HZ - 1);
        count += 3;
    }
    // Each remainder's step: where r * RATE / HZ moves on.
    for (k = 0; k < HZ; k += 1 + (k & 7)) {
        one(k);
        one(5 * HZ + k);
        count += 2;
    }
    printf("%ld ticks, %ld differ\n", count, bad);
    return bad != 0;
}
