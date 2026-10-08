// airouteplan -- the route planners out of the AI's utility object, the same
// object as airoute.c's helpers. GuessTargetDestinations so far
// (0x001cbb70).
//
// GuessTargetDestinations walks the route network from a point, a set
// distance on, and returns where it can get to. Every signpost on the way
// either applies in the walk's direction or not; one that applies stops
// the walk (sign 3), jumps it down the sign's route (sign 2), or splits it
// in two, the branch going on a 20-slot ring of paths still to walk -- at
// the front for sign 0, at the back for the rest. TrafficTeleporter asks it
// for one point 250 units on and then 50 at a time.
//
// ReturnToLastBranch, FindRoutesToTarget, FindPointsToTarget and
// FindNearbySignpost are not here yet.
//
// Written up in docs/formats/ai-route.md.
#ifndef AIROUTEPLAN_H
#define AIROUTEPLAN_H

#include <stdint.h>

#include "airoute.h"

// The ring's size and the two guards, retail's literals.
#define ROUTEPLAN_RING           20
#define ROUTEPLAN_MAX_PATHS      71        // a 71st path ends it, with 0
#define ROUTEPLAN_MAX_STEPS      0x11800   // so does a step past this

// 0x001cbb70. Up to `count` points `dist` on from `point`, on `route`,
// walking forwards (`fwd`) or back, into out[0 ..]. Returns how many --
// or 0 when the walk runs past either guard, whatever it found by then.
// 0 at once with no route or no point.
//
// A point counts once the distance left goes below 0: each point walked
// takes its Length off. Walking back, the start's Length is added first.
// A point with its Posted bit clear ends that path, and so does either end
// of the route.
int32_t ai_guess_target_destinations(NearestRoutePointInfo *out,
                                     uint32_t count, TrackRoute *route,
                                     TrackRoutePoint *point, float dist,
                                     int fwd);

#endif
