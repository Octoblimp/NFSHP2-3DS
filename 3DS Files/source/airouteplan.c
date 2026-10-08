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
