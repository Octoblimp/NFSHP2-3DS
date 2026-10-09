// airouteplan -- the route planners out of the AI's utility object, the same
// object as airoute.c's helpers: GuessTargetDestinations (0x001cbb70),
// ReturnToLastBranch (0x001cc130), FindRoutesToTarget (0x001cc270),
// FindPointsToTarget (0x001cc5d0) and FindNearbySignpost (0x001cc838).
//
// GuessTargetDestinations walks the route network from a point, a set
// distance on, and returns where it can get to. Every signpost on the way
// either applies in the walk's direction or not; one that applies stops
// the walk (sign 3), jumps it down the sign's route (sign 2), or splits it
// in two, the branch going on a 20-slot ring of paths still to walk -- at
// the front for sign 0, at the back for the rest. TrafficTeleporter asks it
// for one point 250 units on and then 50 at a time.
//
// FindPointsToTarget lists the points from one place towards another, and
// FindRoutesToTarget the routes between, depth first; the helicopter
// (chopper.c) follows them. FindNearbySignpost counts the points to the
// next signpost.
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

// The port's: FindRoutesToTarget gives up after this many steps.
#define ROUTEPLAN_MAX_WALK       0x11800

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

// Deque<TrackRoute *, 20>, 92 bytes: the routes taken, oldest at Front.
// Empty is Front == Back with Full clear; nothing goes on when Full.
typedef struct RoutePlanRoutes {
    TrackRoute *Item[ROUTEPLAN_RING];          //  0
    int32_t     Front;                         // 80
    int32_t     Back;                          // 84
    int32_t     Full;                          // 88
} RoutePlanRoutes;

// Deque<NearestRoutePointInfo, 20>, 172 bytes: the branches not taken,
// the newest at Front.
typedef struct RoutePlanBranches {
    NearestRoutePointInfo Item[ROUTEPLAN_RING]; //   0
    int32_t               Front;                // 160
    int32_t               Back;                 // 164
    int32_t               Full;                 // 168
} RoutePlanBranches;

// 0x001cc130. 0 with no branch left. Otherwise the newest branch comes off
// into `info`, and routes come off the back of `routes` until the branch's
// route is the last; 1.
//
// The divergence: with `routes` empty, before the branch's route is found,
// the port answers 0. The image compares the last route it took off (or,
// with none, a stale stack word) for ever.
int32_t ai_return_to_last_branch(NearestRoutePointInfo *info,
                                 RoutePlanBranches *branches,
                                 RoutePlanRoutes *routes);

// 0x001cc270. Depth first from `start`, walking forwards (`fwd`) or back,
// for a way onto `target`, each route taken going on `routes`; 1 when
// found. A signpost that applies (as GuessTargetDestinations') and names a
// route not taken yet is followed, the way on kept as a branch unless the
// sign is 2. One naming a route already taken is passed by, unless the
// sign is 2 or 3: then the walk goes back to the last branch. So it does
// at a point marked TRP_NO_HELISHEET when `heli` is set. Running off a
// route, or out of branches, empties `routes` and answers 0.
//
// The divergences:
//   - a branch kept at the end of a route has no point, and the port takes
//     it as running off (the image steps from address 0, and with `heli`
//     reads it);
//   - looking through a full `routes` that lacks the sign's route, the
//     port stops after twenty looks and the image never does;
//   - a full `routes` takes no more, so the walk can go round a loop of
//     routes for ever in the image. The port gives up as on running off
//     after ROUTEPLAN_MAX_WALK steps.
int32_t ai_find_routes_to_target(const NearestRoutePointInfo *start,
                                 TrackRoute *target, RoutePlanRoutes *routes,
                                 int fwd, int heli);

// 0x001cc5d0. Up to `count` points from `start` towards `target`, into
// out[0 ..], and how many: `target` alone when it is the start; 0 when
// `heli` and the start is marked TRP_NO_HELISHEET. Each point on is
// listed, and the list stops at the target, at the end of a route, at a
// sign 3, at a TRP_NO_HELISHEET point when `heli`, or once `count` are
// listed (one at least). A sign 2 is taken. At any other sign that applies
// FindRoutesToTarget fills one deque of routes for the whole call, and the
// sign is taken only when it names the route at the deque's front; an
// empty deque ends the list. That front is the first route ever put on,
// the start's, so in practice these signs are passed by.
uint32_t ai_find_points_to_target(const NearestRoutePointInfo *start,
                                  const NearestRoutePointInfo *target,
                                  NearestRoutePointInfo *out, uint32_t count,
                                  int fwd, int heli);

// 0x001cc838. `info` stepped along its route, forwards (`fwd`) or back,
// to the first point with a signpost: 1 plus the steps taken, or 0 when it
// runs off the route (`info->Point` NULL).
int32_t ai_find_nearby_signpost(NearestRoutePointInfo *info, int fwd);

#endif
