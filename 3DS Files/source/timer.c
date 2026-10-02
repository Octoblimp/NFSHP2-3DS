// timer -- see timer.h.

#include "timer.h"

#include "eefpu.h"

void timer_set_time(Timer *t, float seconds)
{
    t->PackedTime = (uint32_t)ee_trunc_w(seconds * 4000.0f);
}

float timer_round_seconds(const Timer *t, float f)
{
    float q = (float)(int32_t)t->PackedTime * 0.00025f / f;
    float fl = (float)ee_trunc_w(q);
    float x, c;

    if (q < fl)
        fl = fl - 1.0f;
    if (0.5f <= q - fl)
        fl = fl + 1.0f;
    x = fl * f * 4000.0f;
    c = (float)ee_trunc_w(x);
    if (c < x)
        c = c + 1.0f;
    return c * 0.00025f;
}

void timer_round(Timer *t, float f)
{
    t->PackedTime = (uint32_t)ee_trunc_w(timer_round_seconds(t, f) * 4000.0f
                                         + 0.5f);
}
