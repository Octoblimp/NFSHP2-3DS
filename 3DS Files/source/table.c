// table -- see table.h.

#include "table.h"

#include <math.h>

void table_calc_index_multiplier(Table *t)
{
    t->IndexMultiplier = (float)(t->NumEntries - 1) / (t->MaxArg - t->MinArg);
}

void table_set_min_max(Table *t, float minarg, float maxarg)
{
    t->MinArg = minarg;
    t->MaxArg = maxarg;
    table_calc_index_multiplier(t);
}

void table_init(Table *t, const float *entries, int32_t n,
                float minarg, float maxarg)
{
    t->pTable     = entries;
    t->NumEntries = n;
    table_set_min_max(t, minarg, maxarg);
}

float table_get_value(const Table *t, float arg)
{
    float   frac;
    int32_t i, last;

    // The low clamp and the high clamp are separate branches in the
    // listing, not a min/max pair: the high test is only reached when the
    // low one did not fire. It matters for a NaN argument, which fails both
    // comparisons and falls through unclamped -- and the original does the
    // same, so it is left alone.
    if (arg < t->MinArg)
        arg = t->MinArg;
    else if (t->MaxArg < arg)
        arg = t->MaxArg;

    frac = (arg - t->MinArg) * t->IndexMultiplier;

    // cvt.w.s, so this truncates toward zero.
    i    = (int32_t)frac;
    last = t->NumEntries - 1;

    // The top of the range lands exactly on the last index, and there is no
    // entry after it to interpolate against, so it is returned as-is.
    if (i == last)
        return t->pTable[i];

    return t->pTable[i]
         + (t->pTable[i + 1] - t->pTable[i]) * (frac - (float)i);
}

float table_inverse_lookup(const Table *t, float value)
{
    const float *p = t->pTable;
    float   first = p[0];
    int32_t i, n = t->NumEntries;
    int32_t above, now;

    // gp-30264, 0x003215b8: 1e-6 (0x358637bd).
    if (fabsf(value - first) < 1e-6f)
        return first;

    // `c.lt.s $f2,$f12`: which side of the value the walk starts on.
    above = first < value;

    for (i = 1; i < n; i++) {
        float v = p[i];

        // gp-30260, 0x003215bc: the same 1e-6, pooled twice.
        if (fabsf(value - v) < 1e-6f)
            return t->MinArg + (float)i / t->IndexMultiplier;

        now = v < value;
        if (now != above) {
            float prev = p[i - 1];
            return t->MinArg
                 + ((float)(i - 1) + (value - prev) / (v - prev))
                   / t->IndexMultiplier;
        }
        above = now;
    }

    return t->MinArg + (float)(n - 1) / t->IndexMultiplier;
}
