// traffictele -- see traffictele.h.
#include "traffictele.h"

#include "bmem.h"
#include "race.h"
#include "trackroute.h"

// The first think is no sooner than this (`lui 0x41a0`): 20 s, more than
// SetThinkTime ever gives.
#define TELEPORT_FIRST_THINK 20.0f

TrafficTeleporter *traffic_teleporter_construct(void *mem)
{
    TrafficTeleporter *t = (TrafficTeleporter *)mem;

    traffic_teleporter_fill_in_totals(t, t->ForwardTotals,
                                      TRAFFIC_FORWARD_ROUTES);
    traffic_teleporter_fill_in_totals(t, t->BackwardTotals,
                                      TRAFFIC_BACKWARD_ROUTES);
    traffic_teleporter_set_think_time(t);
    // `c.lt.s` and a likely store: a NaN is left alone.
    if (t->TimeUntilTeleport < TELEPORT_FIRST_THINK)
        t->TimeUntilTeleport = TELEPORT_FIRST_THINK;
    t->LastCar = NULL;
    return t;
}

void traffic_teleporter_destroy(TrafficTeleporter *t, int32_t flags)
{
    if (flags & 1)
        bFree(t);
}

void traffic_teleporter_set_think_time(TrafficTeleporter *t)
{
    t->TimeUntilTeleport =
        (1.0f - TheRaceParameters.TrafficDensity) * 15.0f + 1.0f;
}

// The route slots are read straight out of the manager's table, a
// negative number reading none (`bltz`); first is 50 or 60, so the top is
// never passed.
void traffic_teleporter_fill_in_totals(TrafficTeleporter *t, uint32_t *out,
                                       int32_t first)
{
    uint32_t total = 0;
    int32_t  i;

    (void)t;
    for (i = 0; i < TRAFFIC_ROUTES_EACH; i++) {
        const TrackRoute *r = trmgr_get_route(&TheTrackRouteManager,
                                              first + i);

        if (r != NULL)
            total += (uint32_t)r->NumPoints;
        out[i] = total;
    }
}
