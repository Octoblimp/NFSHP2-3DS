// drivinglocation -- DrivingLocation, where on the route network an AI car
// drives: a route, a point on it, a driving line across it, and when the
// line last changed in a relaxed switch. Retail's DrivingLocation.hpp,
// 0x00239bb0 .. 0x00239f28 (the demo's 0x00223f18 ..), with Clear at
// 0x001941e0.
//
// Every method the game calls is here. Six are not, because nothing in
// retail calls them: GetLineSpeed (0x00239d90), GetLinePosition
// (0x00239e50) and the DoesThisRoutePointMatchThisRoute they share
// (0x00239c90), IsDrivingLineOkay (0x00239cc0), operator= (0x00239cc8;
// the copies are inline) and GetTextDescription (0x00239f28, a debug
// string). DoSnapshot (0x00239cf0) is the replay's, since TASKS 72c.
//
// Checked against retail by tools/nearbycar_check.py. Written up in
// docs/formats/ai-driving-info.md.
#ifndef DRIVINGLOCATION_H
#define DRIVINGLOCATION_H

#include <stddef.h>
#include <stdint.h>

#include "timer.h"
#include "trackroute.h"

// 16 bytes, type#1041. The fields are the stab's but for the two
// pointers, which the port has always called pRoute and pRoutePoint
// (the stab's Route and RoutePoint).
typedef struct DrivingLocation {
    TrackRoute      *pRoute;                            //  0
    TrackRoutePoint *pRoutePoint;                       //  4
    int32_t          DrivingLine;                       //  8
    Timer            LastRelaxedDrivingLineSwitchTime;  // 12
} DrivingLocation;                                      // 16

#ifndef DRIVINGLOCATION_NO_ASSERT
typedef char drivinglocation_layout_check[
    (offsetof(DrivingLocation, pRoutePoint) == sizeof(void *)
     && offsetof(DrivingLocation, DrivingLine) == 2 * sizeof(void *)
     && offsetof(DrivingLocation, LastRelaxedDrivingLineSwitchTime)
        == 2 * sizeof(void *) + 4
     && sizeof(DrivingLocation) == 2 * sizeof(void *) + 8) ? 1 : -1];
#endif

// How long a relaxed switch lasts: GetNumSecondsLeftInRelaxedSwitch's
// 3.0, built with `lui`.
#define DRIVINGLOCATION_RELAXED_SWITCH_SECONDS 3.0f

// 0x00239c80. `pRoute == NULL`, and nothing else.
static inline int drivinglocation_is_clear(const DrivingLocation *d)
{
    return d->pRoute == NULL;
}

// 0x001941e0. No route and no point, line -1, and the switch time 0.
void drivinglocation_clear(DrivingLocation *d);

// 0x00239bb0. Stores the route and the point, then SetDrivingLine.
void drivinglocation_set_route(DrivingLocation *d, TrackRoute *r,
                               TrackRoutePoint *p, int32_t line,
                               int relaxed);

// 0x00239bc8.
void drivinglocation_set_route_point(DrivingLocation *d, TrackRoutePoint *p);

// 0x00239bd0. Stores the line, then SetRelaxedSwitch.
void drivinglocation_set_driving_line(DrivingLocation *d, int32_t line,
                                      int relaxed);

// 0x00239be0. The switch time becomes WorldTimer when `relaxed`, and 0
// when not.
void drivinglocation_set_relaxed_switch(DrivingLocation *d, int relaxed);

// 0x00239bf8. 3 less the seconds since the switch, `WorldTimer - time`
// through a signed convert times 0.00025 (gp-26780), or 0 when that is
// below 0 or a NaN.
float drivinglocation_get_num_seconds_left_in_relaxed_switch(
    const DrivingLocation *d);

// 0x00239c48. Whether the seconds left are above 0.
int drivinglocation_are_we_in_a_relaxed_switch(const DrivingLocation *d);

// 0x00239cf0, a "DrivingLocation" section: the route by number, the point
// by its index in that route, the line as one signed byte and the switch
// time.
struct ReplaySnapshot;
void drivinglocation_do_snapshot(DrivingLocation *d, struct ReplaySnapshot *s);

#endif /* DRIVINGLOCATION_H */
