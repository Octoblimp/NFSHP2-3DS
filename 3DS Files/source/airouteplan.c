// airouteplan -- see airouteplan.h and docs/formats/ai-route.md.
#include "airouteplan.h"

#include <stddef.h>

// A path still to walk: where it is, and the distance it has left. Twelve
// bytes on the image's stack, copied whole with `ldl`/`ldr` and a word.
typedef struct PlanPath {
    TrackRoute      *Route;
    TrackRoutePoint *Point;
    float            Dist;
} PlanPath;

// The paths still to walk (sp+0 .. sp+248 in the image). Front is where
// the next one comes off, and where sign 0's branch and the way on go
// back on; Back is where the other signs' branches go. With Full set
// nothing goes on, and what would have is dropped. Front == Back is
// empty unless Full.
typedef struct PlanRing {
    PlanPath Path[ROUTEPLAN_RING];
    int32_t  Front;
    int32_t  Back;
    int32_t  Full;
} PlanRing;

static void push_front(PlanRing *q, const PlanPath *p)
{
    q->Front = q->Front == 0 ? ROUTEPLAN_RING - 1 : q->Front - 1;
    q->Full = q->Back == q->Front;
    q->Path[q->Front] = *p;
}

static void push_back(PlanRing *q, const PlanPath *p)
{
    q->Path[q->Back] = *p;
    q->Back++;
    if (q->Back == ROUTEPLAN_RING)
        q->Back = 0;
    q->Full = q->Back == q->Front;
}

// The point after `p` on `r` walking forwards, or before it walking back;
// NULL off either end. The index is worked out as airoute.c's point_index
// does, the image's way.
static TrackRoutePoint *step(TrackRoute *r, TrackRoutePoint *p, int fwd)
{
    uint32_t d = (uint32_t)((uintptr_t)p
                            - (uintptr_t)r->TrackRoutePointTable);
    int32_t  i = (int32_t)(d * 0xb6db6db7u) >> 4;

    if (fwd) {
        i++;
        if (!(i < r->NumPoints))
            return NULL;
    } else {
        if (i == 0)
            return NULL;
        i--;
    }
    return (TrackRoutePoint *)(void *)((uint8_t *)r->TrackRoutePointTable
                                       + (int32_t)((uint32_t)i * 112u));
}

// The distance left at `to`, reached through `p`'s signpost: `p`'s Length
// back on, less how far `to` lies along `p`'s direction.
static float across(float dist, const TrackRoutePoint *p,
                    const TrackRoutePoint *to)
{
    return (dist + p->Length)
           - ((to->Position.x - p->Position.x) * p->Direction.x
              + (to->Position.y - p->Position.y) * p->Direction.y);
}

// 0x001cbb70.
int32_t ai_guess_target_destinations(NearestRoutePointInfo *out,
                                     uint32_t count, TrackRoute *route,
                                     TrackRoutePoint *point, float dist,
                                     int fwd)
{
    PlanRing q;
    PlanPath cur;
    int32_t  found = 0;
    int32_t  paths = 0;
    int32_t  steps = 1;

    q.Front = 0;
    q.Back = 0;
    q.Full = 0;
    if (route == NULL || point == NULL)
        return 0;
    cur.Route = route;
    cur.Point = point;
    cur.Dist = dist;
    if (!fwd)
        cur.Dist = dist + point->Length;

    for (;;) {
        TrackRoutePoint *p = cur.Point;

        cur.Dist = cur.Dist - p->Length;
        if (cur.Dist < 0.0f) {
            out->Route = cur.Route;
            out->Point = p;
            found++;
            if ((uint32_t)found == count)
                return found;
            out++;
            cur.Point = NULL;
        } else {
            int advance = 1;

            if (trpoint_has_signpost(p)) {
                Signpost *s = trpoint_get_signpost(p);
                int       back = (s->Flags & SIGNPOST_BACKWARDS) != 0;

                // A Backwards sign is for the walk back alone.
                if (fwd ? !back : back) {
                    uint32_t sign = s->Flags & SIGNPOST_SIGN_MASK;

                    advance = 0;
                    if (sign == SIGN_STOP) {
                        // This point, next time round.
                        cur.Dist = -1.0f;
                    } else if (sign == SIGN_ALWAYS_TAKE) {
                        TrackRoutePoint *to = signpost_get_new_route_point(s);

                        cur.Dist = across(cur.Dist, p, to);
                        cur.Route = signpost_get_new_route(s);
                        cur.Point = to;
                    } else {
                        PlanPath branch;

                        branch.Route = signpost_get_new_route(s);
                        branch.Point = signpost_get_new_route_point(s);
                        branch.Dist = across(cur.Dist, p, branch.Point);
                        cur.Point = step(cur.Route, p, fwd);
                        if (cur.Point != NULL && !q.Full)
                            push_front(&q, &cur);
                        if (!q.Full) {
                            if (sign == SIGN_FASTER)
                                push_front(&q, &branch);
                            else
                                push_back(&q, &branch);
                        }
                        cur.Point = NULL;
                    }
                }
            }
            if (advance)
                cur.Point = step(cur.Route, p, fwd);
        }

        if (cur.Point != NULL && !trpoint_is_posted(cur.Point))
            cur.Point = NULL;
        if (cur.Point == NULL) {
            if (!q.Full && q.Front == q.Back)
                return found;
            cur = q.Path[q.Front];
            q.Front++;
            if (q.Front == ROUTEPLAN_RING)
                q.Front = 0;
            q.Full = 0;
            if (++paths >= ROUTEPLAN_MAX_PATHS)
                return 0;
        }
        if (++steps > ROUTEPLAN_MAX_STEPS)
            return 0;
    }
}

// ------------------------------------------------- the routes to a target

static int routes_empty(const RoutePlanRoutes *r)
{
    return !r->Full && r->Front == r->Back;
}

// PushBack, which every caller in the image skips when the deque is full.
static void routes_push(RoutePlanRoutes *r, TrackRoute *route)
{
    if (r->Full)
        return;
    r->Item[r->Back] = route;
    r->Back++;
    if (r->Back == ROUTEPLAN_RING)
        r->Back = 0;
    r->Full = r->Back == r->Front;
}

// Front to Back, as the image looks. It stops only at Back, after a step
// and before the wrap, so it goes round for ever when Back is 0 or the
// deque is full and the route is not there. Twenty looks cover every slot.
static int routes_contain(const RoutePlanRoutes *r, const TrackRoute *route)
{
    int32_t i, n;

    if (routes_empty(r))
        return 0;
    i = r->Front;
    for (n = 0; n < ROUTEPLAN_RING; n++) {
        if (r->Item[i] == route)
            return 1;
        i++;
        if (i == r->Back)
            return 0;
        if (i == ROUTEPLAN_RING)
            i = 0;
    }
    return 0;
}

// GetRelativePoint, but from no point to none.
static TrackRoutePoint *relative(TrackRoute *r, TrackRoutePoint *p, int fwd)
{
    if (p == NULL)
        return NULL;
    return troute_get_relative_point(r, p, fwd);
}

// 0x001cc130.
int32_t ai_return_to_last_branch(NearestRoutePointInfo *info,
                                 RoutePlanBranches *b, RoutePlanRoutes *r)
{
    TrackRoute *route;

    if (!b->Full && b->Front == b->Back)
        return 0;
    *info = b->Item[b->Front];
    b->Front++;
    if (b->Front == ROUTEPLAN_RING)
        b->Front = 0;
    b->Full = 0;
    route = info->Route;
    for (;;) {
        if (routes_empty(r))
            return 0;
        if (r->Item[r->Back == 0 ? ROUTEPLAN_RING - 1 : r->Back - 1] == route)
            return 1;
        r->Back = r->Back == 0 ? ROUTEPLAN_RING - 1 : r->Back - 1;
        r->Full = 0;
    }
}

// 0x001cc270.
int32_t ai_find_routes_to_target(const NearestRoutePointInfo *start,
                                 TrackRoute *target, RoutePlanRoutes *routes,
                                 int fwd, int heli)
{
    RoutePlanBranches b;
    NearestRoutePointInfo cur;
    int32_t walk = 0;

    b.Front = 0;
    b.Back = 0;
    b.Full = 0;
    cur = *start;
    routes_push(routes, start->Route);
    if (cur.Route == target)
        return 1;
    for (;;) {
        if (trpoint_has_signpost(cur.Point)) {
            Signpost *s = trpoint_get_signpost(cur.Point);
            int       back = (s->Flags & SIGNPOST_BACKWARDS) != 0;

            if (fwd ? !back : back) {
                TrackRoute *to = signpost_get_new_route(s);
                uint32_t    sign = s->Flags & SIGNPOST_SIGN_MASK;

                if (to == target) {
                    routes_push(routes, to);
                    return 1;
                }
                if (!routes_contain(routes, to)) {
                    routes_push(routes, to);
                    if (sign != SIGN_ALWAYS_TAKE) {
                        cur.Point = troute_get_relative_point(cur.Route,
                                                              cur.Point, fwd);
                        if (!b.Full) {
                            b.Front = b.Front == 0 ? ROUTEPLAN_RING - 1
                                                   : b.Front - 1;
                            b.Full = b.Back == b.Front;
                            b.Item[b.Front] = cur;
                        }
                    }
                    cur.Route = to;
                    cur.Point = signpost_get_new_route_point(s);
                } else if (sign == SIGN_ALWAYS_TAKE || sign == SIGN_STOP) {
                    if (!ai_return_to_last_branch(&cur, &b, routes))
                        break;
                }
            }
        }
        if (++walk > ROUTEPLAN_MAX_WALK)
            break;
        cur.Point = relative(cur.Route, cur.Point, fwd);
        if (cur.Point == NULL)
            break;
        // Back to the last branch, whose point is looked at next as it is.
        if (heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0
            && (!ai_return_to_last_branch(&cur, &b, routes)
                || cur.Point == NULL))
            break;
    }
    routes->Back = routes->Front;
    routes->Full = 0;
    return 0;
}

// 0x001cc5d0.
uint32_t ai_find_points_to_target(const NearestRoutePointInfo *start,
                                  const NearestRoutePointInfo *target,
                                  NearestRoutePointInfo *out, uint32_t count,
                                  int fwd, int heli)
{
    RoutePlanRoutes routes;
    NearestRoutePointInfo cur;
    uint32_t n = 0;

    routes.Front = 0;
    routes.Back = 0;
    routes.Full = 0;
    if (start->Point == target->Point) {
        *out = *target;
        return 1;
    }
    if (heli && (start->Point->Bits & TRP_NO_HELISHEET) != 0)
        return 0;
    cur = *start;
    for (;;) {
        int step = 1;

        if (trpoint_has_signpost(cur.Point)) {
            Signpost *s = trpoint_get_signpost(cur.Point);
            int       back = (s->Flags & SIGNPOST_BACKWARDS) != 0;

            if (fwd ? !back : back) {
                uint32_t sign = s->Flags & SIGNPOST_SIGN_MASK;
                int      take;

                if (sign == SIGN_STOP) {
                    cur.Point = NULL;
                    step = 0;
                    take = 0;
                } else if (sign == SIGN_ALWAYS_TAKE) {
                    take = 1;
                } else {
                    ai_find_routes_to_target(&cur, target->Route, &routes,
                                             fwd, heli);
                    if (routes_empty(&routes))
                        return n;
                    take = routes.Item[routes.Front]
                           == signpost_get_new_route(s);
                }
                if (take) {
                    step = 0;
                    cur.Route = signpost_get_new_route(s);
                    cur.Point = signpost_get_new_route_point(s);
                }
            }
        }
        if (step)
            cur.Point = troute_get_relative_point(cur.Route, cur.Point, fwd);
        if (cur.Point == NULL)
            return n;
        if (heli && (cur.Point->Bits & TRP_NO_HELISHEET) != 0)
            return n;
        *out++ = cur;
        n++;
        if (cur.Point == target->Point || !(n < count))
            return n;
    }
}

// 0x001cc838.
int32_t ai_find_nearby_signpost(NearestRoutePointInfo *info, int fwd)
{
    int32_t n = 1;

    while (info->Point != NULL) {
        if (trpoint_has_signpost(info->Point))
            return n;
        info->Point = troute_get_relative_point(info->Route, info->Point,
                                                fwd);
        n++;
    }
    return 0;
}
