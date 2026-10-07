// previewroute -- see previewroute.h.

#include "previewroute.h"

#include <math.h>
#include <stddef.h>

#include "bmem.h"
#include "car.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "race.h"

// The points' allocation, as retail's bMalloc names it.
#define ZONECAMERAS_CPP "..\\indep\\src\\zonecameras.cpp"

// DrivingLineInfo's two flag bits, IsValid and IsFake. A line with either
// counts.
#define LINE_VALID 0x1u
#define LINE_FAKE  0x2u

void preview_route_point_get_position(const PreviewRoutePoint *pt,
                                      bVector3 *o)
{
    trpoint_get_position3(pt->pPoint, o, 0.0f, pt->fOffset);
}

void preview_route_point_get_position_at(const PreviewRoutePoint *pt,
                                         bVector3 *o, float along,
                                         float across)
{
    trpoint_get_position3(pt->pPoint, o, along, across);
}

PreviewRoute *preview_route_init(PreviewRoute *pr, struct Car *car,
                                 float radius, float length)
{
    const bVector2 *pos = (const bVector2 *)&car->State.Position;
    TrackRoute *r;
    TrackRoutePoint *p;
    int32_t line, ok, i;
    float total;

    pr->pPoints = NULL;
    pr->fDistance = length;
    pr->nPoints = ee_trunc_w(length * 0.25f);
    pr->pPoints = (PreviewRoutePoint *)bMalloc(
        pr->nPoints * (int)sizeof(PreviewRoutePoint), ZONECAMERAS_CPP, 1538,
        16);
    pr->vTrackDirection = car->TheTrackPathCoordinate.PathDirection;
    line = car->pCarTypeInfo->CarClass;
    r = car_get_route(car, 1);
    p = car_get_route_point(car, 1);
    if (r != NULL && p != NULL)
        ok = preview_route_closest_distance(pr, pr->pPoints, r, p, pos, line)
             <= radius;
    else
        ok = preview_route_closest_point(pr, pos, radius, line, 0, NULL);
    if (!ok) {
        bFree(pr->pPoints);
        pr->pPoints = NULL;
        pr->nPoints = 0;
        return pr;
    }

    p = pr->pPoints[0].pPoint;
    pr->fOffset = (pos->x - p->Position.x) * p->Direction.y
                  - (pos->y - p->Position.y) * p->Direction.x;
    total = 0.0f;
    for (i = 1; i < pr->nPoints; i++) {
        total += preview_route_next_point(pr, i, radius, line);
        if (pr->fDistance < total)
            break;
        if (pr->pPoints[i].pPoint == NULL)
            break;
    }
    pr->fDistance = total;
    pr->nPoints = i;
    return pr;
}

void preview_route_destroy(PreviewRoute *pr, int32_t flags)
{
    if (pr->pPoints != NULL)
        bFree(pr->pPoints);
    if (flags & 1)
        bFree(pr);
}

void preview_route_delete(PreviewRoute *pr)
{
    preview_route_destroy(pr, 3);
}

float preview_route_next_point(PreviewRoute *pr, int32_t i, float radius,
                               int32_t line)
{
    PreviewRoutePoint *prev = &pr->pPoints[i - 1];
    PreviewRoutePoint *cur;
    TrackRoute *r = prev->pRoute;
    TrackRoutePoint *pp = prev->pPoint;
    int32_t prevLine = prev->nLine;
    bVector3 from, to;
    float dx, dy, dz, d;

    preview_route_point_get_position(prev, &from);
    if (troute_get_point_number(r, pp) + 1 < r->NumPoints) {
        cur = &pr->pPoints[i];
        cur->pRoute = r;
        cur->nLine = prevLine;
        cur->pPoint = pp + 1;
        if (prevLine != -1)
            cur->fOffset = trpoint_get_driving_line_offset(cur->pPoint,
                                                           prevLine);
        else
            cur->fOffset = 0.0f;
        cur->fRouteGap = 0.0f;
    } else {
        if (!preview_route_closest_point(pr, (const bVector2 *)&from, radius,
                                         line, i, pp))
            return 0.0f;
        cur = &pr->pPoints[i];
        cur->fRouteGap =
            (pp->Position.x - cur->pPoint->Position.x)
                * cur->pPoint->Direction.y
            - (pp->Position.y - cur->pPoint->Position.y)
                * cur->pPoint->Direction.x;
    }

    // On VU0, so (x*x + y*y) + z*z.
    preview_route_point_get_position(cur, &to);
    dx = to.x - from.x;
    dy = to.y - from.y;
    dz = to.z - from.z;
    d = sqrtf(dx * dx + dy * dy + dz * dz);
    pr->pPoints[i - 1].fLength = d;
    return d;
}

// The loop's third pass is not a third line: it is the centre, tried only
// when neither line was there, and only if the route point faces the car's
// way along the track.
float preview_route_closest_distance(const PreviewRoute *pr,
                                     PreviewRoutePoint *out, TrackRoute *r,
                                     TrackRoutePoint *point,
                                     const bVector2 *pos, int32_t line)
{
    float best = PREVIEW_ROUTE_FAR;
    float bestOffset = 0.0f;
    int32_t bestLine = -1;
    int32_t found = 0;
    int32_t i;

    for (i = 0; i < 3; i++) {
        bVector2 at;
        float offset, dx, dy, d;
        int32_t l;

        if (i == 2) {
            if (found)
                break;
            if (point->Direction.x * pr->vTrackDirection.x
                + point->Direction.y * pr->vTrackDirection.y < 0.0f)
                break;
            l = -1;
            offset = 0.0f;
        } else {
            uint32_t flags;

            l = 2 * line + i;
            flags = r->DrivingLineInfoTable[l].Flags;
            if (!(flags & LINE_VALID) && !(flags & LINE_FAKE))
                continue;
            found = 1;
            offset = trpoint_get_driving_line_offset(point, l);
        }
        trpoint_get_position2(point, &at, 0.0f, offset);
        dx = pos->x - at.x;
        dy = pos->y - at.y;
        d = sqrtf(dx * dx + dy * dy);
        if (d < best) {
            best = d;
            bestOffset = offset;
            bestLine = l;
            if (found)
                break;
        }
    }
    out->pRoute = r;
    out->pPoint = point;
    out->fOffset = bestOffset;
    out->nLine = bestLine;
    return best;
}

// `p` is the last route's answer, not the best one's, as retail keeps it.
// Retail reads prev's DistanceAroundTrack even when prev is NULL, which
// only the constructor passes, for a car with no route; the port lets the
// point through.
int32_t preview_route_closest_point(PreviewRoute *pr, const bVector2 *pos,
                                    float radius, int32_t line,
                                    int32_t index, TrackRoutePoint *prev)
{
    PreviewRoutePoint cand = { NULL, NULL, 0.0f, 0.0f, -1, 0.0f };
    PreviewRoutePoint best = cand;
    float bestDist = PREVIEW_ROUTE_FAR;
    TrackRoutePoint *p = NULL;
    int i;

    for (i = 0; i < TheTrackRouteManager.NumRacing; i++) {
        TrackRoute *r = TheTrackRouteManager.Racing[i];
        float d;

        p = troute_find_closest_point(r, pos, radius, TRFIND_AHEAD_ONLY,
                                      0.0f);
        if (p == NULL || p == prev)
            continue;
        d = preview_route_closest_distance(pr, &cand, r, p, pos, line);
        if (d < bestDist) {
            best = cand;
            bestDist = d;
        }
    }
    pr->pPoints[index] = best;
    if (p == NULL || best.pPoint == NULL)
        return 0;
    if (!RaceParametersPoint2Point || prev == NULL)
        return 1;
    return !(best.pPoint->DistanceAroundTrack < prev->DistanceAroundTrack);
}
