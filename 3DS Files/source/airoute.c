// airoute -- see airoute.h and docs/formats/ai-route.md.
#include "airoute.h"

#include <math.h>
#include <stddef.h>

#include "race.h"

// A point's index in `r`'s table, the way the image works it out: the byte
// distance from the table, times the inverse of 7 mod 2^32 (0xb6db6db7),
// shifted right four as a signed word. Exact for a point in the table; for
// anything else it is the same garbage the image gets, provided the bytes
// sit the same distance apart, which a route loaded in place guarantees.
static int32_t point_index(const TrackRoute *r, const TrackRoutePoint *p)
{
    uint32_t d = (uint32_t)((uintptr_t)p
                            - (uintptr_t)r->TrackRoutePointTable);

    return (int32_t)(d * 0xb6db6db7u) >> 4;
}

// The same, back: `mult` by 112, plus 1064, plus the route, all mod 2^32.
static TrackRoutePoint *point_at(TrackRoute *r, int32_t idx)
{
    return (TrackRoutePoint *)(void *)((uint8_t *)r->TrackRoutePointTable
                                       + (int32_t)((uint32_t)idx * 112u));
}

// 0x001c3268.
int nrpi_is_valid(const NearestRoutePointInfo *info)
{
    const TrackRoute *r = info->Route;
    int32_t           idx;

    if (r == NULL || info->Point == NULL)
        return 0;
    // `lh` then `sltiu`: a negative route number fails too.
    if (!((uint32_t)(int32_t)r->RouteNumber < 70u))
        return 0;
    idx = point_index(r, info->Point);
    if (idx < 0)
        return 0;
    return idx < r->NumPoints;
}

// 0x001c1660.
int ai_get_nearest_route_point(NearestRoutePointInfo *info,
                               const bVector2 *pos, RoutesToSearch which,
                               int flags, float distanceAround)
{
    TrackRouteManager *m = &TheTrackRouteManager;
    TrackRoute       **list;
    TrackRoute        *bestRoute = NULL;
    TrackRoutePoint   *bestPoint = NULL;
    float              best = AIROUTE_SEARCH_RADIUS;
    int                count, i;
    int                filter = 0;
    // `sltiu s3,v1,1` on TheRaceParameters.TrackDirection.
    int                forward =
        RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD;
    int                byTrack = flags & TRFIND_BY_TRACK_DISTANCE;

    // Racing for 0, traffic for anything else; anything but 0 and 1 keeps
    // only the traffic routes running one way, and 3 flips which way.
    if (which == ALL_RACING_ROUTES) {
        list = m->Racing;
        count = m->NumRacing;
    } else {
        list = m->Traffic;
        count = m->NumTraffic;
        if (which != ALL_TRAFFIC_ROUTES) {
            if (which == ONCOMING_TRAFFIC_ROUTES)
                forward = !forward;
            filter = 1;
        }
    }

    for (i = 0; i < count; i++) {
        TrackRoute      *r = list[i];
        TrackRoutePoint *p;
        float            d;

        if (filter
            && (r->RouteNumber < AIROUTE_FORWARD_TRAFFIC_LIMIT) != forward)
            continue;

        // The best so far is the next route's radius.
        p = troute_find_closest_point(r, pos, best, flags, distanceAround);
        if (p == NULL)
            continue;

        if (byTrack) {
            d = trpoint_get_distance_away(p, pos, distanceAround);
        } else {
            float dx = p->Position.x - pos->x;
            float dy = p->Position.y - pos->y;
            d = sqrtf(dx * dx + dy * dy);
        }

        // `c.lt.s`: the first of equals.
        if (d < best) {
            best = d;
            bestPoint = p;
            bestRoute = r;
        }
    }

    if (bestRoute == NULL || bestPoint == NULL)
        return 0;
    info->Point = bestPoint;
    info->Route = bestRoute;
    return 1;
}

// 0x001c1808.
void ai_get_next_route_point(NearestRoutePointInfo *info)
{
    TrackRoute      *r = info->Route;
    TrackRoutePoint *p = info->Point;
    int32_t          idx;

    if (trpoint_has_signpost(p)) {
        Signpost *s = trpoint_get_signpost(p);
        uint32_t  sign = s->Flags & SIGNPOST_SIGN_MASK;

        // Not Backwards, and a sign of 0 or 2: down the branch.
        if (!(s->Flags & SIGNPOST_BACKWARDS) && (sign == 2 || sign == 0)) {
            info->Route = signpost_get_new_route(s);
            info->Point = signpost_get_new_route_point(s);
            return;
        }
    }

    // One on, or NULL off the end. The route stays either way.
    idx = point_index(r, info->Point);
    if (idx + 1 < r->NumPoints)
        info->Point = point_at(r, idx + 1);
    else
        info->Point = NULL;
}

// 0x001c1918.
void ai_get_next_route_point_ahead(NearestRoutePointInfo *info)
{
    TrackRoutePoint *start = info->Point;
    TrackRoutePoint *p;
    float            dx, dy, d;

    if (start == NULL || info->Route == NULL)
        return;
    ai_get_next_route_point(info);

    // Only a signposted start can have jumped somewhere behind.
    if (!trpoint_has_signpost(start))
        return;
    p = info->Point;
    if (p == NULL)
        return;

    d = (p->Position.x - start->Position.x) * start->Direction.x
        + (p->Position.y - start->Position.y) * start->Direction.y;
    if (!(d < 0.0f))
        return;

    ai_get_next_route_point(info);
    p = info->Point;
    // The image reads the new point without testing it: off the end of
    // the route that is address 0. The port stops.
    if (p == NULL)
        return;
    dx = start->Position.x - p->Position.x;
    dy = start->Position.y - p->Position.y;
    if (sqrtf(dx * dx + dy * dy) < 8.0f)
        ai_get_next_route_point(info);
}
