// trackroute -- see trackroute.h.
#include "trackroute.h"

#include <stdlib.h>
#include <math.h>
#include <string.h>

#include "bchunk.h"
#include "trackpath.h"

// .lit4 0x003219f8. The reciprocal of the nominal point spacing, used by
// FindClosestPoint's skip heuristic and by nothing else.
#define TR_INV_POINT_SPACING 0.0416666679084301f

// .lit4 0x003219fc, EraseDrivingLine's "no lap time".
#define TR_NO_LINE_TIME 999.0f

// 0x41c00000, the nominal point spacing, in GetDistanceAway and
// CalculatePointDirection.
#define TR_POINT_SPACING 24.0f

TrackRouteManager TheTrackRouteManager;
Signpost         *SignpostArray;
uint32_t          NumSignposts;

// ------------------------------------------------------------ route points

// 0x001b7290. The byte store then the word read-modify-write, in that order:
// the fields the original never touches keep whatever the memory held.
void trpoint_init(TrackRoutePoint *p)
{
    p->Bits = ((p->Bits & ~0xffu) | 0xffu) | 0x0fc03f00u;
    p->Bits &= ~(TRP_NO_HELISHEET | TRP_POSTED | TRP_POSTED_BACKWARDS);
    p->BankSlope    = 0.0f;
    p->ForwardSlope = 0.0f;
}

// 0x001b72e0.
void trpoint_get_position2(const TrackRoutePoint *p, bVector2 *o, float d,
                           float l)
{
    bVector2 perp;

    perp.x = p->Direction.y;
    perp.y = -p->Direction.x;
    bScaleAdd2(o, &p->Position, &perp, l);
    bScaleAdd2(o, o, &p->Direction, d);
}

// 0x001b7358. Two VU0 fmas over four lanes; the fourth lane's inputs are
// stack slots the original never writes, so `pad` is left alone here.
void trpoint_get_position3(const TrackRoutePoint *p, bVector3 *o, float d,
                           float l)
{
    float lx = p->Direction.y;
    float ly = -p->Direction.x;
    float lz = p->BankSlope;
    float ax = p->Direction.x;
    float ay = p->Direction.y;
    float az = p->ForwardSlope;

    o->x = lx * l + p->Position.x;
    o->y = ly * l + p->Position.y;
    o->z = lz * l + p->Elevation;

    o->x = ax * d + o->x;
    o->y = ay * d + o->y;
    o->z = az * d + o->z;
}

// 0x001b73e0.
void trpoint_set_width(TrackRoutePoint *p, float left, float right)
{
    if (64.0f < left)  left  = 64.0f;
    if (left < 1.0f)   left  = 1.0f;
    if (64.0f < right) right = 64.0f;
    if (right < 1.0f)  right = 1.0f;
    p->RightWidth = right;
    p->LeftWidth  = left;
}

// 0x001b7448, retail 0x001c14f8, which steps by retail's 12.
Signpost *trpoint_get_signpost(const TrackRoutePoint *p)
{
    return &SignpostArray[p->Bits & TRP_SIGN_MASK];
}

// 0x001b7460. Forty-eight bytes: Position through Bits, and no further.
void trpoint_swap_point_data(TrackRoutePoint *a, TrackRoutePoint *b)
{
    uint8_t tmp[48];

    memcpy(tmp, a, 48);
    memcpy(a, b, 48);
    memcpy(b, tmp, 48);
}

// 0x001b74c0.
void trpoint_reverse_point(TrackRoutePoint *p)
{
    bVector3 moved;
    float    left, right;
    int      i;

    trpoint_get_position3(p, &moved, p->Length, 0.0f);
    p->Position.x = moved.x;
    p->Position.y = moved.y;
    p->Elevation  = moved.z;

    p->Direction.x = -p->Direction.x;
    p->Direction.y = -p->Direction.y;

    left  = p->LeftWidth;
    right = p->RightWidth;
    p->RightWidth   = left;
    p->ForwardSlope = -p->ForwardSlope;
    p->BankSlope    = -p->BankSlope;
    p->LeftWidth    = right;

    p->DistanceAroundTrack =
        TheTrackPathManager.TrackLength - p->DistanceAroundTrack;

    // Lines 0..9 trade places with 10..19; the original spells this as five
    // outer passes of two. Line 20 stays where it is.
    for (i = 0; i < 10; ++i) {
        int16_t o = p->DrivingLineOffsets[i];
        uint8_t s = p->DrivingLineSpeeds[i];
        p->DrivingLineOffsets[i]      = p->DrivingLineOffsets[i + 10];
        p->DrivingLineSpeeds[i]       = p->DrivingLineSpeeds[i + 10];
        p->DrivingLineOffsets[i + 10] = o;
        p->DrivingLineSpeeds[i + 10]  = s;
    }
}

// 0x001b75d8.
void trpoint_reverse_traffic_route_point(TrackRoutePoint *p)
{
    p->DistanceAroundTrack =
        TheTrackPathManager.TrackLength - p->DistanceAroundTrack;
}

// 0x001b75f0.
float trpoint_get_distance_away(const TrackRoutePoint *p, const bVector2 *pos,
                                float d)
{
    float dx    = p->Position.x - pos->x;
    float dy    = p->Position.y - pos->y;
    float plane = sqrtf(dx * dx + dy * dy);
    float along = trackpath_compare_distances(&TheTrackPathManager,
                                              p->DistanceAroundTrack, d);

    along = (along < 0.0f ? -along : along) - TR_POINT_SPACING;
    return plane < along ? along : plane;
}

// Inlined at every call site; see the header for where the scales come from.
float trpoint_get_driving_line_offset(const TrackRoutePoint *p, int line)
{
    return (float)((int32_t)p->DrivingLineOffsets[line] << 8) * 0.0000152587890625f;
}

float trpoint_get_driving_line_speed(const TrackRoutePoint *p, int line)
{
    return (float)((int32_t)p->DrivingLineSpeeds[line] << 16) * 0.0000152587890625f;
}

// ------------------------------------------------------------------ routes

// 0x001b7660, retail 0x001c1710, which clears DontTakeTarget as well.
void troute_init(TrackRoute *r, int routeNumber)
{
    int i;

    for (i = 0; i < TRACK_ROUTE_MAX_POINTS; ++i)
        trpoint_init(&r->TrackRoutePointTable[i]);

    r->RouteNumber = (int16_t)routeNumber;
    r->Version     = 1;
    r->Type        = routeNumber < 50 ? TRACK_ROUTE_RACING
                   : (routeNumber < 70 ? TRACK_ROUTE_TRAFFIC
                                       : TRACK_ROUTE_RACING);
    r->Flags      &= ~(TROUTE_MEMORY_IMAGE_LOADED | TROUTE_REVERSED |
                       TROUTE_DONT_TAKE_TARGET);
    r->MaxPoints   = TRACK_ROUTE_MAX_POINTS;
    r->NumPoints   = 0;
    r->CurrentlyTuningDrivingLine = 0;

    for (i = 0; i < TRP_NUM_DRIVING_LINES; ++i)
        troute_erase_driving_line(r, i);

    bInitializeBoundingBox2(&r->BBoxMin, &r->BBoxMax);
}

// 0x001b7760.
TrackRoutePoint *troute_add_point(TrackRoute *r, const bVector2 *pos,
                                  float elevation, float leftWidth,
                                  float rightWidth)
{
    TrackRoutePoint *p;
    uint8_t          routeNumber;

    if (r->NumPoints >= r->MaxPoints) return 0;

    routeNumber = (uint8_t)r->RouteNumber;
    p = &r->TrackRoutePointTable[r->NumPoints];
    ++r->NumPoints;

    p->RouteNumber = routeNumber;
    p->Position    = *pos;
    p->Elevation   = elevation;
    p->LeftWidth   = leftWidth;
    p->RightWidth  = rightWidth;
    bExpandBoundingBox2(&r->BBoxMin, &r->BBoxMax, &p->Position);
    p->Length = 4.0f;

    if (r->NumPoints >= 2) {
        TrackRoutePoint *prev = &r->TrackRoutePointTable[r->NumPoints - 2];
        troute_calculate_point_direction(r, prev);
        p->Direction = prev->Direction;
    } else {
        p->Direction.y  = 0.0f;
        p->Direction.x  = 1.0f;
        p->ForwardSlope = 0.0f;
    }
    return p;
}

// 0x001b7858.
TrackRoutePoint *troute_get_relative_point(TrackRoute *r, TrackRoutePoint *p,
                                           int forward)
{
    int i = troute_get_point_number(r, p);

    if (forward) {
        if (i + 1 < r->NumPoints) return &r->TrackRoutePointTable[i + 1];
        return 0;
    }
    if (i == 0) return 0;
    return &r->TrackRoutePointTable[i - 1];
}

// 0x001b78d8.
int troute_calculate_point_direction(TrackRoute *r, TrackRoutePoint *p)
{
    TrackRoutePoint *next;
    float            len, slope;

    int i = troute_get_point_number(r, p);
    if (i >= r->NumPoints - 1) return 0;
    next = &r->TrackRoutePointTable[i + 1];

    p->Direction.x = next->Position.x - p->Position.x;
    p->Direction.y = next->Position.y - p->Position.y;

    len = sqrtf(p->Direction.x * p->Direction.x +
                      p->Direction.y * p->Direction.y);
    p->Length = len;

    // Written to both points. The store into `next` is the delay slot of the
    // call to bNormalize, so it happens before the direction is unitised and
    // the value is the same one either way.
    slope = (next->Elevation - p->Elevation) / len;
    p->ForwardSlope    = slope;
    next->ForwardSlope = slope;

    bNormalize2(&p->Direction, &p->Direction);

    len = p->Length;
    if (TR_POINT_SPACING < len) return 1;
    if (len < 4.0f) return 1;
    return 0;
}

// 0x001b79e0. Elevation comes from pos->x; see the header.
int troute_move_point(TrackRoute *r, TrackRoutePoint *p, const bVector3 *pos)
{
    int i = troute_get_point_number(r, p);
    int n;

    if (i < 0) return 1;
    if (i >= r->NumPoints) return 1;

    p->Position.x = pos->x;
    p->Position.y = pos->y;
    p->Elevation  = pos->x;

    n = troute_calculate_point_direction(r, p);
    if (i > 0)
        n += troute_calculate_point_direction(
                 r, &r->TrackRoutePointTable[i - 1]);
    return n;
}

// 0x001b7a90.
TrackRoutePoint *troute_find_closest_point(TrackRoute *r, const bVector2 *pos,
                                           float radius, int flags,
                                           float distanceAround)
{
    TrackRoutePoint *best = 0;
    int              byTrackDistance = flags & TRFIND_BY_TRACK_DISTANCE;
    int              i;

    if (!bBoundingBoxIsInside2(&r->BBoxMin, &r->BBoxMax, pos, radius))
        return 0;

    for (i = 0; i < r->NumPoints;) {
        TrackRoutePoint *p = &r->TrackRoutePointTable[i];
        float dx, dy, dist, dot;
        int   skip;

        if (byTrackDistance) {
            dist = trpoint_get_distance_away(p, pos, distanceAround);
        } else {
            dx   = p->Position.x - pos->x;
            dy   = p->Position.y - pos->y;
            dist = sqrtf(dx * dx + dy * dy);
        }

        dot = -((pos->x - p->Position.x) * p->Direction.x +
                (pos->y - p->Position.y) * p->Direction.y);

        for (;;) {
            if ((flags & TRFIND_AHEAD_ONLY) && !(0.0f < dot)) break;
            if (!(dist < radius)) break;
            if ((flags & TRFIND_POSTED_ONLY) && !(p->Bits & TRP_POSTED)) break;
            if ((flags & TRFIND_NO_HELISHEET) && (p->Bits & TRP_NO_HELISHEET))
                break;
            best   = p;
            radius = dist;
            break;
        }

        // Consecutive points are no more than TR_POINT_SPACING apart, so a
        // point closer than `dist` cannot be hiding in the next
        // dist/24 - 2 of them.
        skip = (int)(dist * TR_INV_POINT_SPACING) - 2;
        if (skip > 0) i += skip;
        ++i;
    }
    return best;
}

// 0x001b7c78.
TrackRoutePoint *troute_find_closest_point_ahead(TrackRoute *r,
                                                 const bVector2 *pos,
                                                 TrackRoutePoint *start)
{
    TrackRoutePoint *p;
    int              i, n;

    if (!pos || !start) return 0;

    n = r->NumPoints;
    i = troute_get_point_number(r, start);
    p = &r->TrackRoutePointTable[i];

    for (;;) {
        float dot;
        ++i;
        dot = -((pos->x - p->Position.x) * p->Direction.x +
                (pos->y - p->Position.y) * p->Direction.y);
        if (!(dot < 0.0f)) break;
        if (i >= n) break;
        ++p;
    }
    // `i` runs one ahead of `p`, so the last point never qualifies.
    return i < n ? p : 0;
}

// 0x001b7d28.
void troute_erase_driving_line(TrackRoute *r, int line)
{
    DrivingLineInfo *info = &r->DrivingLineInfoTable[line];
    int              i;

    for (i = 0; i < r->NumPoints; ++i) {
        r->TrackRoutePointTable[i].DrivingLineOffsets[line] = 0;
        r->TrackRoutePointTable[i].DrivingLineSpeeds[line]  = 0;
    }

    info->Flags &= ~(DLI_IS_VALID | DLI_IS_FAKE);
    info->LineTime = TR_NO_LINE_TIME;
    memset(info->DriverName, 0, sizeof info->DriverName);
}

// 0x001b8200.
int troute_has_driving_line_data(const TrackRoute *r)
{
    const TrackRoutePoint *mid = &r->TrackRoutePointTable[r->NumPoints / 2];
    int                    k;

    for (k = 0; k < 2; ++k)
        if (30.0f < trpoint_get_driving_line_speed(mid, k)) return 1;
    return 0;
}

// 0x001b8280.
void troute_reverse_route(TrackRoute *r)
{
    int n = r->NumPoints;
    int i;

    for (i = 0; i < n / 2; ++i)
        trpoint_swap_point_data(&r->TrackRoutePointTable[i],
                                &r->TrackRoutePointTable[n - 1 - i]);

    for (i = 0; i < r->NumPoints; ++i)
        trpoint_reverse_point(&r->TrackRoutePointTable[i]);

    for (i = 0; i < 10; ++i) {
        DrivingLineInfo t = r->DrivingLineInfoTable[i];
        r->DrivingLineInfoTable[i]      = r->DrivingLineInfoTable[i + 10];
        r->DrivingLineInfoTable[i + 10] = t;
    }

    r->Flags = (r->Flags & ~TROUTE_REVERSED) |
               ((~(r->Flags >> 1) & 1u) << 1);
}

// 0x001b84e8.
void troute_reverse_traffic_route(TrackRoute *r)
{
    int i;
    for (i = 0; i < r->NumPoints; ++i)
        trpoint_reverse_traffic_route_point(&r->TrackRoutePointTable[i]);
}

// 0x001b8548.
//
// Point 0's distance seeds the "did we jump" test but is never put in a
// bucket, so a one-point route comes out with fStart = TrackLength and
// fEnd = 0 -- empty, which is what DistanceIsWithinRoute then reports for
// every distance but those two.
void troute_set_first_and_last(TrackRoute *r)
{
    TrackPathCoordinate coord;
    float mn[2], mx[2];
    float half = TheTrackPathManager.TrackLength * 0.5f;
    float prev;
    int   bucket  = 0;
    int   wrapped = 0;
    int   i;

    mn[0] = TheTrackPathManager.TrackLength;
    mx[0] = 0.0f;
    mn[1] = TheTrackPathManager.TrackLength;
    mx[1] = 0.0f;

    trackpath_coord_init(&coord);
    trackpath_coord_update_position(&coord,
                                    &r->TrackRoutePointTable[0].Position);
    prev = coord.DistanceAroundTrack;

    for (i = 1; i < r->NumPoints; ++i) {
        float d, gap;
        trackpath_coord_update_position(
            &coord, &r->TrackRoutePointTable[i].Position);
        d   = coord.DistanceAroundTrack;
        gap = d - prev;
        if (gap < 0.0f) gap = -gap;
        if (half < gap) {
            wrapped = 1;
            bucket ^= 1;
        }
        prev = d;
        if (mx[bucket] < d) mx[bucket] = d;
        if (d < mn[bucket]) mn[bucket] = d;
    }

    if (wrapped) {
        r->fStartDistance = mn[0] > mn[1] ? mn[0] : mn[1];
        r->fEndDistance   = mx[0] < mx[1] ? mx[0] : mx[1];
    } else {
        r->fStartDistance = mn[0];
        r->fEndDistance   = mx[0];
    }
}

// 0x001b86c8.
int troute_distance_is_within_route(const TrackRoute *r, float d)
{
    int after  = r->fStartDistance <= d;
    int before = d <= r->fEndDistance;

    if (r->fStartDistance < r->fEndDistance) return after && before;
    return after || before;
}

// ------------------------------------------------------------- the manager

// 0x001b8738. On the disc both bTLists point at themselves; here both
// arrays are empty, which is the same statement.
void trmgr_init(TrackRouteManager *m)
{
    int i;

    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; ++i) m->pTrackRoutes[i] = 0;
    m->NumRacing  = 0;
    m->NumTraffic = 0;
}

// Drop a route from whichever list holds it, keeping the rest in order.
// This is the unlink the disc spells with four pointer stores.
static void trmgr_unlink(TrackRouteManager *m, TrackRoute *r)
{
    TrackRoute **list;
    int         *count;
    int          i, j;

    for (j = 0; j < 2; ++j) {
        list  = j ? m->Traffic : m->Racing;
        count = j ? &m->NumTraffic : &m->NumRacing;
        for (i = 0; i < *count; ++i) {
            if (list[i] != r) continue;
            for (; i + 1 < *count; ++i) list[i] = list[i + 1];
            --*count;
            return;
        }
    }
}

// 0x001b87e8. Appends to the tail, which is what the bTList does. A Type
// that is neither racing nor traffic lands in the slot table and nowhere
// else -- the disc's two equality tests, not a default branch.
void trmgr_add_route_to_right_list(TrackRouteManager *m, TrackRoute *r)
{
    m->pTrackRoutes[(int16_t)r->RouteNumber] = r;

    if (r->Type == TRACK_ROUTE_RACING) {
        if (m->NumRacing < TRACK_ROUTE_MAX_ROUTES)
            m->Racing[m->NumRacing++] = r;
    } else if (r->Type == TRACK_ROUTE_TRAFFIC) {
        if (m->NumTraffic < TRACK_ROUTE_MAX_ROUTES)
            m->Traffic[m->NumTraffic++] = r;
    }
}

// 0x001b8848. Each record is a TrackRoute with the unused tail of its point
// table cut off, so the stride shrinks by 112 bytes for every point the
// route does not have. Nothing is copied: the manager's routes point into
// the bundle.
void trmgr_loader(TrackRouteManager *m, const uint8_t *chunk)
{
    uint32_t       size = bchunk_u32(chunk + 4);
    const uint8_t *p    = chunk + 8;
    const uint8_t *end  = chunk + 8 + size;

    while (p < end) {
        TrackRoute *r = (TrackRoute *)(uintptr_t)p;
        trmgr_add_route_to_right_list(m, r);
        p += (uint32_t)sizeof(TrackRoute) -
             (uint32_t)(TRACK_ROUTE_MAX_POINTS - r->NumPoints) *
                 (uint32_t)sizeof(TrackRoutePoint);
    }
}

// 0x001b88e8.
void trmgr_unloader(TrackRouteManager *m)
{
    int i;

    for (i = 0; i < TRACK_ROUTE_MAX_ROUTES; ++i) {
        TrackRoute *r = m->pTrackRoutes[i];
        if (!r) continue;
        trmgr_unlink(m, r);
        if (!(r->Flags & TROUTE_MEMORY_IMAGE_LOADED)) free(r);
        m->pTrackRoutes[i] = 0;
    }
}

// 0x001b8ce0. Two passes over the two lists. Whichever list a pass would
// walk, the matching skip flag turns it into no list at all.
TrackRoutePoint *trmgr_find_closest_point(TrackRouteManager *m,
                                          const bVector2 *pos, float radius,
                                          int flags, float distanceAround)
{
    TrackRoutePoint *best = 0;
    int              pass;

    for (pass = 0; pass < 2; ++pass) {
        TrackRoute **list;
        int          count, i;

        if (pass == 0) {
            if (flags & TRFIND_SKIP_RACING) continue;
            list  = m->Racing;
            count = m->NumRacing;
        } else {
            if (flags & TRFIND_SKIP_TRAFFIC) continue;
            list  = m->Traffic;
            count = m->NumTraffic;
        }

        for (i = 0; i < count; ++i) {
            TrackRoute      *r = list[i];
            TrackRoutePoint *p = troute_find_closest_point(
                r, pos, radius, flags, distanceAround);
            if (!p) continue;
            if (flags & TRFIND_BY_TRACK_DISTANCE) {
                radius = trpoint_get_distance_away(p, pos, distanceAround);
            } else {
                float dx = p->Position.x - pos->x;
                float dy = p->Position.y - pos->y;
                radius = sqrtf(dx * dx + dy * dy);
            }
            best = p;
        }
    }
    return best;
}

// 0x001b8a00. Slots 50..69 are traffic; every other slot below 70 is not.
void trmgr_reverse_routes(TrackRouteManager *m)
{
    int i;

    for (i = 0; i < 70; ++i) {
        TrackRoute *r = m->pTrackRoutes[i];
        if (!r) continue;
        if (i >= 50) troute_reverse_traffic_route(r);
        else         troute_reverse_route(r);
    }
}

// ---------------------------------------------------------------- signposts

// 0x001b6f60. The original guards the lookup with a `bltz` on a value it
// just zero-extended from a byte, so the NULL return is unreachable.
TrackRoute *signpost_get_new_route(const Signpost *s)
{
    return TheTrackRouteManager.pTrackRoutes[s->NewRoute];
}

// 0x001b6f88.
TrackRoutePoint *signpost_get_new_route_point(const Signpost *s)
{
    TrackRoute *r = signpost_get_new_route(s);
    if (!r) return 0;
    return &r->TrackRoutePointTable[s->NewPoint];
}

// 0x001b7080.
int signpost_is_racing_route(const Signpost *s)
{
    return s->NewRoute < 50;
}

// 0x001b6fc8, retail 0x001c1060, which steps by retail's 12.
void signpost_reverse_signs(void)
{
    uint32_t i;

    for (i = 0; i < NumSignposts; ++i) {
        Signpost   *s = &SignpostArray[i];
        TrackRoute *r;
        if (!signpost_is_racing_route(s)) continue;
        r = signpost_get_new_route(s);
        s->NewPoint = (uint16_t)(r->NumPoints - s->NewPoint - 1);
        s->Flags    = (uint8_t)((s->Flags & ~SIGNPOST_BACKWARDS) |
                                ((~(s->Flags >> 3) & 1u) << 3));
    }
}

// 0x001b7090, retail 0x001c1138, which steps by retail's 12. Two hops,
// not one: the sign's own target point is used only to
// read *its* signpost, and the distance comes from that second sign's target
// point. On track 12 the signs are paired -- sign i's point names sign i^1,
// the same junction seen from the other direction -- so the pair share a
// distance. All 56 resolve in range there; the check below is the port's,
// not the disc's, and costs one compare.
void signpost_set_distances(void)
{
    TrackPathCoordinate coord;
    uint32_t            i;

    trackpath_coord_init(&coord);

    for (i = 0; i < NumSignposts; ++i) {
        Signpost        *s = &SignpostArray[i];
        TrackRoutePoint *p = signpost_get_new_route_point(s);
        Signpost        *other;
        TrackRoutePoint *target;

        if (!p) continue;
        if ((p->Bits & TRP_SIGN_MASK) >= NumSignposts) continue;
        other  = trpoint_get_signpost(p);
        target = signpost_get_new_route_point(other);
        if (!target) continue;

        trackpath_coord_update_position(&coord, &target->Position);
        s->Distance = coord.DistanceAroundTrack;
    }
}

// 0x001b7120, retail 0x001c11d8, which steps by retail's 12.
int signpost_get_index(float d)
{
    uint32_t i;

    for (i = 0; i < NumSignposts; ++i)
        if (!(SignpostArray[i].Distance < d)) return (int)i;
    return 0;
}

// 0x001b8f20.
int signposts_present(void)
{
    return SignpostArray != 0;
}

// 0x001b7168. The loop runs, the distance is computed, and nothing is kept:
// the asserts it fed went out with NDEBUG. Nothing calls it.
void signpost_test_consistency(void)
{
    TrackPathCoordinate coord;
    uint32_t            i;

    trackpath_coord_init(&coord);

    for (i = 0; i < NumSignposts; ++i) {
        Signpost        *s = &SignpostArray[i];
        TrackRoutePoint *p = signpost_get_new_route_point(s);
        if (!p) continue;
        trackpath_coord_update_position(&coord, &p->Position);
        (void)coord.DistanceAroundTrack;
    }
}

// ----------------------------------------------------------------- sorting

// 0x001b8f30. Numerical Recipes' heapsort, one for one, including the
// one-based indexing and the malloc'd holding slot.
void heap_sort(void *base, int n, int size, HeapSortCompare cmp)
{
    uint8_t *ra = (uint8_t *)base;
    uint8_t *rra;
    int      l, ir, i, j;

    if (n < 2) return;
    rra = (uint8_t *)malloc((size_t)size);
    if (!rra) return;

    l  = n / 2 + 1;
    ir = n;
    for (;;) {
        if (l >= 2) {
            --l;
            memcpy(rra, ra + (l - 1) * size, (size_t)size);
        } else {
            memcpy(rra, ra + (ir - 1) * size, (size_t)size);
            memcpy(ra + (ir - 1) * size, ra, (size_t)size);
            --ir;
            if (ir == 1) {
                memcpy(ra, rra, (size_t)size);
                break;
            }
        }
        i = l;
        j = l + l;
        while (j <= ir) {
            if (j < ir &&
                cmp(ra + (j - 1) * size, ra + j * size) < 0.0f)
                ++j;
            if (cmp(rra, ra + (j - 1) * size) < 0.0f) {
                memcpy(ra + (i - 1) * size, ra + (j - 1) * size, (size_t)size);
                i = j;
                j += j;
            } else {
                j = ir + 1;
            }
        }
        memcpy(ra + (i - 1) * size, rra, (size_t)size);
    }
    free(rra);
}

// 0x001b9170. The elements are Signpost pointers paired with their original
// index, so the compare dereferences once.
typedef struct SignpostSortEntry {
    Signpost *pSignpost;
    int32_t   Index;
} SignpostSortEntry;

static float compare_signposts(const void *a, const void *b)
{
    const SignpostSortEntry *ea = (const SignpostSortEntry *)a;
    const SignpostSortEntry *eb = (const SignpostSortEntry *)b;
    return ea->pSignpost->Distance - eb->pSignpost->Distance;
}

// ------------------------------------------------------------- chunk hooks

// 0x001b8e60, retail 0x001c2f18. The count is the payload over retail's
// 12, a divu, where the demo shifted by 3.
int track_routes_loader(const uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == CHUNK_TRACK_ROUTES) {
        trmgr_loader(&TheTrackRouteManager, chunk);
        return 1;
    }
    if (type == CHUNK_TRACK_SIGNPOSTS) {
        SignpostArray = (Signpost *)(uintptr_t)(chunk + 8);
        NumSignposts  = bchunk_u32(chunk + 4) / (uint32_t)sizeof(Signpost);
        return 1;
    }
    return 0;
}

// 0x001b8ec8.
int track_routes_unloader(const uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == CHUNK_TRACK_ROUTES) {
        trmgr_unloader(&TheTrackRouteManager);
        return 1;
    }
    if (type == CHUNK_TRACK_SIGNPOSTS) {
        SignpostArray = 0;
        NumSignposts  = 0;
        return 1;
    }
    return 0;
}

// 0x001b9188, retail 0x001c3250. Retail adds one pass after the
// reversal: the NewRoute of every DontTake sign is marked. The stride of
// the sort's gather is retail's 12.
void init_track_routes(int forward)
{
    // Indexed by a point's old SignNumber, which is a byte. The original
    // puts exactly this on its stack.
    uint8_t            remap[256];
    SignpostSortEntry *pairs;
    Signpost          *sorted;
    uint32_t           i;
    int                n;

    if (!forward) {
        trmgr_reverse_routes(&TheTrackRouteManager);
        signpost_reverse_signs();
    }

    // Retail stores through GetNewRoute's result unchecked. A sign whose
    // route is not loaded would write near address 0 there; the port skips
    // it. No retail track has one.
    for (i = 0; i < NumSignposts; ++i) {
        const Signpost *s = &SignpostArray[i];
        TrackRoute     *r;
        if ((s->Flags & SIGNPOST_SIGN_MASK) != SIGN_DONT_TAKE) continue;
        r = signpost_get_new_route(s);
        if (r) r->Flags |= TROUTE_DONT_TAKE_TARGET;
    }

    for (n = 0; n < TRACK_ROUTE_MAX_ROUTES; ++n) {
        TrackRoute *r = TheTrackRouteManager.pTrackRoutes[n];
        if (r) troute_set_first_and_last(r);
    }

    signpost_set_distances();

    if (NumSignposts == 0) return;

    pairs = (SignpostSortEntry *)malloc(NumSignposts * sizeof *pairs);
    if (!pairs) return;
    for (i = 0; i < NumSignposts; ++i) {
        pairs[i].pSignpost = &SignpostArray[i];
        pairs[i].Index     = (int32_t)i;
    }

    heap_sort(pairs, (int)NumSignposts, (int)sizeof *pairs, compare_signposts);

    memset(remap, 0, sizeof remap);
    for (i = 0; i < NumSignposts; ++i)
        remap[(uint8_t)pairs[i].Index] = (uint8_t)i;

    for (n = 0; n < TRACK_ROUTE_MAX_ROUTES; ++n) {
        TrackRoute *r = TheTrackRouteManager.pTrackRoutes[n];
        int         j;
        if (!r) continue;
        for (j = 0; j < r->NumPoints; ++j) {
            TrackRoutePoint *p    = &r->TrackRoutePointTable[j];
            uint32_t         sign = p->Bits & TRP_SIGN_MASK;
            if (sign == TRP_SIGN_MASK) continue;
            p->Bits = (p->Bits & ~TRP_SIGN_MASK) | remap[sign];
        }
    }

    // The original allocates this with new[], so every entry gets the
    // Signpost default constructor -- which is then immediately overwritten
    // by the gather below. Skipped here; the result is identical.
    sorted = (Signpost *)malloc(NumSignposts * sizeof *sorted);
    if (sorted) {
        for (i = 0; i < NumSignposts; ++i) sorted[i] = *pairs[i].pSignpost;
        memcpy(SignpostArray, sorted, NumSignposts * sizeof *sorted);
        free(sorted);
    }
    free(pairs);
}

// 0x001b9428.
void close_track_routes(void)
{
}
