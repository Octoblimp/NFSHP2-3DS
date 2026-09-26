// timer -- see timer.h.

#include "timer.h"

#include "eefpu.h"

void timer_set_time(Timer *t, float seconds)
{
    t->PackedTime = (uint32_t)ee_trunc_w(seconds * 4000.0f);
}
