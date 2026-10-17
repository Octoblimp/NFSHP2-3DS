// airoute -- the route helpers out of the AI's utility object
// (0x001c1660 .. 0x001c1a14, and NearestRoutePointInfo::IsValid at
// 0x001c3268).
//
// A NearestRoutePointInfo is a route and a point on it: the answer to
// "where on the route network is this". GetNearestRoutePoint fills one in
// from a position, GetNextRoutePoint steps it one point along -- down a
// signposted branch if the sign says so -- and GetNextRoutePointAhead
// steps it until the point is in front of where it started. TrackedController
// and RealController (FindWhereIAm, the predictors) use all of them, and so
// do the AI's route planners further up this object.
//
// The planners (GuessTargetDestinations, ReturnToLastBranch,
// FindRoutesToTarget, FindPointsToTarget, FindNearbySignpost) are in
// airouteplan.c. ai_calculate_look_ahead_distance,
// ai_straight_line_predict and ai_is_point_ahead_of_car, from the same
// object, live in drivetarget.c.
//
// Written up in docs/formats/ai-route.md.
#ifndef AIROUTE_H
#define AIROUTE_H

#include <stdint.h>

#include "bvector.h"
#include "trackroute.h"

// 8 bytes on the disc.
typedef struct NearestRoutePointInfo {
    TrackRoute      *Route; // 0
    TrackRoutePoint *Point; // 4
} NearestRoutePointInfo;

// The RoutesToSearch enum, from the .mdebug. A signed word, as the image
// passes it: an enum with no negative values would be unsigned here, and a
// caller's -1 would not be the image's -1.
typedef int32_t RoutesToSearch;
#define ALL_RACING_ROUTES       ((RoutesToSearch)0)
#define ALL_TRAFFIC_ROUTES      ((RoutesToSearch)1)
#define FORWARD_TRAFFIC_ROUTES  ((RoutesToSearch)2)
#define ONCOMING_TRAFFIC_ROUTES ((RoutesToSearch)3)

// GetNearestRoutePoint's starting radius, gp-28896 (0x497423f0).
#define AIROUTE_SEARCH_RADIUS 999999.0f

// A traffic route numbered below this runs with the track.
#define AIROUTE_FORWARD_TRAFFIC_LIMIT 60

// 0x001c3268. Both pointers set, the route's number below 70 (unsigned),
// and the point's index into that route's table in [0, NumPoints).
int nrpi_is_valid(const NearestRoutePointInfo *info);

// 0x001cd460, the replay's (TASKS 72c), a "NearestRoutePointInfo"
// section: the route by number, then the point by its index in it.
struct ReplaySnapshot;
void nrpi_do_snapshot(NearestRoutePointInfo *info, struct ReplaySnapshot *s);

// 0x001c1660. The nearest point to `pos` over every route of the kind
// `which` names. Each route's FindClosestPoint is handed `flags`, the
// best distance so far as its radius, and `distanceAround`. With
// TRFIND_BY_TRACK_DISTANCE in `flags` the routes are compared by
// GetDistanceAway, otherwise by the 2D distance. Fills `info` and returns
// 1 when something was found; leaves `info` alone and returns 0 when not.
int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround);

// 0x001c1808. One point on. A point with a signpost whose sign is 0 or 2,
// and not Backwards, sends `info` down the sign's route instead. Off the
// end of the route the point becomes NULL; the route stays. Both pointers
// must be set: the image reads through them untested.
void ai_get_next_route_point(NearestRoutePointInfo *info);

// 0x001c1918. One step. Then, only if the start point has a signpost --
// the step may have jumped down a branch, to a point behind -- a second
// step if the new point lies behind the start along the start point's
// direction, and a third if that one is within 8 units of the start.
// Nothing at all with no point or no route; it stops at a NULL point
// after the first step, and the port also stops at one after the second,
// where the image reads through it.
void ai_get_next_route_point_ahead(NearestRoutePointInfo *info);

#endif
