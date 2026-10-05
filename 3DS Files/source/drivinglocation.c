// drivinglocation -- see drivinglocation.h.
#include "drivinglocation.h"

#include "realtime.h"   // WorldTimer

// The tick, gp-26780 (0x0032f054): 0x3983126f.
#define DRIVINGLOCATION_TICK 0.00025f

void drivinglocation_clear(DrivingLocation *d)
{
    // 0x001941e0.
    d->LastRelaxedDrivingLineSwitchTime.PackedTime = 0;
    d->DrivingLine = -1;
    d->pRoute = NULL;
    d->pRoutePoint = NULL;
}

void drivinglocation_set_route(DrivingLocation *d, TrackRoute *r,
                               TrackRoutePoint *p, int32_t line,
                               int relaxed)
{
    // 0x00239bb0, a tail call into SetDrivingLine.
    d->pRoute = r;
    d->pRoutePoint = p;
    drivinglocation_set_driving_line(d, line, relaxed);
}

void drivinglocation_set_route_point(DrivingLocation *d, TrackRoutePoint *p)
{
    // 0x00239bc8.
    d->pRoutePoint = p;
}

void drivinglocation_set_driving_line(DrivingLocation *d, int32_t line,
                                      int relaxed)
{
    // 0x00239bd0, a tail call into SetRelaxedSwitch.
    d->DrivingLine = line;
    drivinglocation_set_relaxed_switch(d, relaxed);
}

void drivinglocation_set_relaxed_switch(DrivingLocation *d, int relaxed)
{
    // 0x00239be0. The bool is a word, tested whole.
    d->LastRelaxedDrivingLineSwitchTime.PackedTime =
        relaxed ? (uint32_t)WorldTimer : 0u;
}

float drivinglocation_get_num_seconds_left_in_relaxed_switch(
    const DrivingLocation *d)
{
    // 0x00239bf8. `c.le.s 0,left` and the 0 in the delay slot: a NaN
    // takes the 0.
    int32_t ticks = (int32_t)((uint32_t)WorldTimer
                              - d->LastRelaxedDrivingLineSwitchTime.PackedTime);
    float left = DRIVINGLOCATION_RELAXED_SWITCH_SECONDS
               - (float)ticks * DRIVINGLOCATION_TICK;

    return 0.0f <= left ? left : 0.0f;
}

int drivinglocation_are_we_in_a_relaxed_switch(const DrivingLocation *d)
{
    // 0x00239c48. `c.lt.s 0,left`.
    return 0.0f < drivinglocation_get_num_seconds_left_in_relaxed_switch(d);
}
