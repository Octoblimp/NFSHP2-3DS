// track -- Track.obj, 0x0014e7d0 .. 0x001509d4. See topology.h and track.h.
//
// Every function here is the listing's, in the listing's order. Where the
// EE moves four lanes the port moves four too if a caller can read the
// fourth, and three if nothing can; each place says which.
//
// The divides are plain. The ones the code guards need no help, and the
// two it does not -- the normal's reciprocal square root in the
// constructor and GetElevation's divide by the normal's z -- are only zero
// for a polygon whose vertices are collinear or, for the second, a floor
// that stands on its edge. TRACKB12 has neither (all 15708 polygons,
// tools/track_check.py counts them), and the EE's quotient for a zero
// divisor is FLT_MAX where ARM's is infinity, so a track that did would
// need ee_div here and would show it in that count first.

#include "track.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "bchunk.h"
#include "bslotpool.h"
#include "bticker.h"
#include "bvector.h"
#include "eefpu.h"
#include "p32.h"
#include "terraintype.h"
#include "topology.h"

TopologyTree  TheTopologyTree;
BSlotPool    *TrackPolygonSlotPool;
float         TopologyTiming[10];
uint32_t      TopologyTimingIndex;

TrackListNode TrackPositionMarkerList;
TrackInfo    *CurrentTrackInfo;
TrackInfo    *TrackInfoTable;
int32_t       HighestTrackNumber;
int32_t       LoadedTrackNumber;

const float RoadNoiseTable[16] = {
    -0.5f, -0.2f,  0.5f,  0.2f, -0.4f, -0.1f,  0.2f,  0.5f,
    -0.2f, -0.5f,  0.4f, -0.3f,  0.3f,  0.0f, -0.2f,  0.1f,
};

// 0x37800000, the Q16 scale every fixed-point coordinate is read through.
#define TRACK_Q16 (1.0f / 65536.0f)

// gp-31496: HasTopology's probe height, 99999.1 as a float.
#define TRACK_PROBE_Z 99999.1015625f

// gp-31492 and gp-31488: the "nothing yet" distance both segment walks
// start from.
#define TRACK_FAR 999999.0f

// ---------------------------------------------------------------- helpers

static TrackListNode *node_at(uint32_t h)
{
    return (TrackListNode *)p32_ptr(h);
}

// `(v << 13)`, the shift done on the bits: a negative v is sign-extended by
// `lh` and shifted as a word, which C only defines for unsigned.
static float xy_of(int16_t v)
{
    return (float)(int32_t)((uint32_t)(int32_t)v << 13) * TRACK_Q16;
}

// `(v << 8) + (zbase << 16)`, added as words before the conversion -- so it
// wraps, and it rounds once, not twice.
static float z_of(int16_t v, int16_t zbase)
{
    uint32_t w = ((uint32_t)(int32_t)v << 8)
               + ((uint32_t)(int32_t)zbase << 16);
    return (float)(int32_t)w * TRACK_Q16;
}

// vmul.xyz, vaddy.x, vaddz.x.
static float dot3(const bVector3 *a, float nx, float ny, float nz)
{
    return (a->x * nx + a->y * ny) + a->z * nz;
}

// vopmula.xyz ACC,a,b then vopmsub.xyz c,b,a.
static void cross3(bVector3 *c, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    c->x = x;
    c->y = y;
    c->z = z;
}

// The unlink every list walk here does: the node's own words are left
// pointing at its old neighbours.
static void unlink_node(TrackListNode *n)
{
    TrackListNode *next = node_at(n->pNext);
    TrackListNode *prev = node_at(n->pPrev);

    prev->pNext = p32_of(next);
    next->pPrev = p32_of(prev);
}

// bTList::AddTail.
static void append_node(TrackListNode *head, TrackListNode *n)
{
    TrackListNode *tail = node_at(head->pPrev);

    tail->pNext = p32_of(n);
    head->pPrev = p32_of(n);
    n->pPrev    = p32_of(tail);
    n->pNext    = p32_of(head);
}

// ------------------------------------------------------------ the markers

// 0x0014e7d0.
int track_get_num_position_markers(uint32_t hash)
{
    TrackListNode *head = &TrackPositionMarkerList;
    TrackListNode *n;
    int count = 0;

    for (n = node_at(head->pNext); n != head; n = node_at(n->pNext)) {
        if (((TrackPositionMarker *)n)->NameHash == hash)
            count++;
    }
    return count;
}

// 0x0014e810.
TrackPositionMarker *track_get_position_marker(uint32_t hash, int i)
{
    TrackListNode *head = &TrackPositionMarkerList;
    TrackListNode *n;
    int seen = 0;

    for (n = node_at(head->pNext); n != head; n = node_at(n->pNext)) {
        if (((TrackPositionMarker *)n)->NameHash != hash)
            continue;
        if (seen == i)
            return (TrackPositionMarker *)n;
        seen++;
    }
    return NULL;
}

// 0x0014e858.
int track_get_num_position_markers_named(const char *name)
{
    return track_get_num_position_markers(bchunk_hash(name));
}

// 0x0014e880.
TrackPositionMarker *track_get_position_marker_named(const char *name, int i)
{
    return track_get_position_marker(bchunk_hash(name), i);
}

// ---------------------------------------------------------- TrackPolygon

// 0x0014e8b0.
TrackPolygon *trackpolygon_init(TrackPolygon *tp, TopologyTreePolygon *p)
{
    unsigned m;
    int i;
    bVector3 a, b, c;
    float q;

    tp->TheTerrainType = p->Type;
    tp->ReferenceCount = 0;
    tp->Flags = p->Flags;
    tp->pCollisionBody = NULL;

    m = p->MaxMinBits;
    tp->BBoxMin.x = xy_of(p->VerticesX[m & 3]);
    tp->BBoxMin.y = xy_of(p->VerticesY[(m >> 2) & 3]);
    tp->BBoxMax.x = xy_of(p->VerticesX[(m >> 4) & 3]);
    tp->BBoxMax.y = xy_of(p->VerticesY[m >> 6]);

    // All four, triangle or not: GetElevation walks four edges whatever
    // NumVertices says, so the fourth vertex of a triangle is data.
    for (i = 0; i < 4; i++) {
        tp->Vertices[i].x = xy_of(p->VerticesX[i]);
        tp->Vertices[i].y = xy_of(p->VerticesY[i]);
        tp->Vertices[i].z = z_of(p->VerticesZ[i], p->ZBase);
    }

    tp->NumVertices = (tp->Flags & TRACKPOLY_QUAD) ? 4 : 3;

    if (tp->Flags & TRACKPOLY_Z_TIMES_FOUR) {
        for (i = 0; i < 4; i++)
            tp->Vertices[i].z = tp->Vertices[i].z * 4.0f;
    }

    // The normal: the cross of the first two edges out of vertex 0, scaled
    // by vrsqrt's 1/sqrt. xyz only -- the fourth lane of the product is the
    // pad of an edge, and the store takes three words.
    a.x = tp->Vertices[1].x - tp->Vertices[0].x;
    a.y = tp->Vertices[1].y - tp->Vertices[0].y;
    a.z = tp->Vertices[1].z - tp->Vertices[0].z;
    b.x = tp->Vertices[2].x - tp->Vertices[0].x;
    b.y = tp->Vertices[2].y - tp->Vertices[0].y;
    b.z = tp->Vertices[2].z - tp->Vertices[0].z;
    cross3(&c, &a, &b);
    q = 1.0f / sqrtf((c.x * c.x + c.y * c.y) + c.z * c.z);
    tp->Normal.x = c.x * q;
    tp->Normal.y = c.y * q;
    tp->Normal.z = c.z * q;

    tp->PlaneDistance = dot3(&tp->Vertices[0], tp->Normal.x, tp->Normal.y,
                             tp->Normal.z);

    p->TrackPolygonNumber =
        (int16_t)bGetSlotNumber(TrackPolygonSlotPool, tp);
    tp->pPolygon = p;
    return tp;
}

// 0x0014eb78. ~bTNode is ~bNode with its delete bit clear, which is
// nothing; the slot goes back through __dl, 0x001509c8.
void trackpolygon_destroy(TrackPolygon *tp, int flags)
{
    if (tp->pPolygon != NULL)
        tp->pPolygon->TrackPolygonNumber = -1;
    if (flags & 1)
        bSlotFree(TrackPolygonSlotPool, tp);
}

// 0x0014ebe0. The edges out of `pt`, crossed in order round the polygon;
// inside when every cross points the normal's way. Three lanes: the
// crosses are masked xyz and the dots read xyz.
int trackpolygon_point_in_shaft(const TrackPolygon *tp, const bVector3 *pt,
                                float *dist)
{
    int n = (int8_t)tp->NumVertices;
    bVector3 d[4] = {{0}};
    bVector3 c[4];
    int i;

    for (i = 0; i < n; i++) {
        d[i].x = tp->Vertices[i].x - pt->x;
        d[i].y = tp->Vertices[i].y - pt->y;
        d[i].z = tp->Vertices[i].z - pt->z;
    }
    cross3(&c[0], &d[0], &d[1]);
    cross3(&c[1], &d[1], &d[2]);
    if (n == 4) {
        cross3(&c[2], &d[2], &d[3]);
        cross3(&c[3], &d[3], &d[0]);
    } else {
        cross3(&c[2], &d[2], &d[0]);
    }

    for (i = 0; i < n; i++) {
        if (dot3(&c[i], tp->Normal.x, tp->Normal.y, tp->Normal.z) < 0.0f)
            return 0;
    }
    if (dist != NULL)
        *dist = -dot3(&d[0], tp->Normal.x, tp->Normal.y, tp->Normal.z);
    return 1;
}

// 0x0014ed98. Four lanes for the crossing, since `out` gets all sixteen
// bytes; the fourth is the ends' pads interpolated.
int trackpolygon_segment_intersects(const TrackPolygon *tp, const bVector3 *a,
                                    const bVector3 *b, bVector3 *out)
{
    const bVector3 *v0 = &tp->Vertices[0];
    bVector3 da, db, hit;
    float sa, sb, t;

    da.x = a->x - v0->x;
    da.y = a->y - v0->y;
    da.z = a->z - v0->z;
    db.x = b->x - v0->x;
    db.y = b->y - v0->y;
    db.z = b->z - v0->z;
    sa = dot3(&da, tp->Normal.x, tp->Normal.y, tp->Normal.z);
    sb = dot3(&db, tp->Normal.x, tp->Normal.y, tp->Normal.z);
    if (!(sa * sb < 0.0f))
        return 0;

    t = fabsf(sa) / (fabsf(sa) + fabsf(sb));
    hit.x   = (b->x   - a->x)   * t + a->x;
    hit.y   = (b->y   - a->y)   * t + a->y;
    hit.z   = (b->z   - a->z)   * t + a->z;
    hit.pad = (b->pad - a->pad) * t + a->pad;

    if (!trackpolygon_point_in_shaft(tp, &hit, NULL))
        return 0;
    if (out != NULL)
        *out = hit;
    return 1;
}

// 0x0014ee90.
int trackpolygon_test_segment(const TrackPolygon *tp, float *best,
                              const bVector3 *a, const bVector3 *b,
                              const bVector3 *bmin, const bVector3 *bmax,
                              int twoSided)
{
    bVector3 mn, mx, hit, d;
    float len;
    int i;

    bInitializeBoundingBox3At(&mn, &mx, &tp->Vertices[0]);
    for (i = 1; i < (int8_t)tp->NumVertices; i++)
        bExpandBoundingBox3(&mn, &mx, &tp->Vertices[i]);
    if (!bBoundingBoxOverlapping3(&mn, &mx, bmin, bmax))
        return 0;
    if (!trackpolygon_segment_intersects(tp, a, b, &hit))
        return 0;

    d.x = hit.x - a->x;
    d.y = hit.y - a->y;
    d.z = hit.z - a->z;
    if (!twoSided) {
        if (!(dot3(&d, tp->Normal.x, tp->Normal.y, tp->Normal.z) < 0.0f))
            return 0;
    }
    len = sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);
    if (!(len < *best))
        return 0;
    *best = len;
    return 1;
}

// ---------------------------------------------------- TopologyCoordinate

// 0x0014f030. The counts first, because ClearInterestBBox releases
// TotalNumTrackPolygons entries of a table nothing has filled.
void topology_init(TopologyCoordinate *tc)
{
    tc->TotalNumTrackPolygons = 0;
    tc->NumTrackPolygons = 0;
    tc->NumVerticalTrackPolygons = 0;
    tc->NumUpsideDownTrackPolygons = 0;
    topology_clear_interest_bbox(tc);
}

// 0x0014f068.
void topology_destroy(TopologyCoordinate *tc)
{
    topotree_remove(&TheTopologyTree, tc->TrackPolygonTable,
                    tc->TotalNumTrackPolygons);
}

// 0x0014f0c8.
void topology_clear_interest_bbox(TopologyCoordinate *tc)
{
    bInitializeBoundingBox2(&tc->InterestBBoxMin, &tc->InterestBBoxMax);
    bInitializeBoundingBox2(&tc->CachedBBoxMin, &tc->CachedBBoxMax);
    topotree_remove(&TheTopologyTree, tc->TrackPolygonTable,
                    tc->TotalNumTrackPolygons);
    tc->NumUpsideDownTrackPolygons = 0;
    tc->TotalNumTrackPolygons = 0;
    tc->NumTrackPolygons = 0;
    tc->NumVerticalTrackPolygons = 0;
}

// 0x0014f120.
//
// The table is filled in three passes over what the build returned:
// neither-vertical-nor-upside-down, then vertical, then upside-down, the
// last two only when the one before left something out. The third count
// is stored as (everything placed) - (vertical), which is the upside-down
// count only when there are no floors -- with the usual all-floor build it
// comes out as the total. The image does that and so does the port;
// nothing in Track.obj reads the count back.
void topology_set_interest_bbox(TopologyCoordinate *tc, const bVector2 *pos,
                                float r, const bVector2 *vel)
{
    TrackPolygon *local[TOPOLOGY_MAX_POLYGONS];
    TrackPolygon **table = tc->TrackPolygonTable;
    float scale = 0.5f;
    int n, k, vertical, i;

    bInitializeBoundingBox2(&tc->InterestBBoxMin, &tc->InterestBBoxMax);
    bExpandBoundingBox2R(&tc->InterestBBoxMin, &tc->InterestBBoxMax, pos, r);
    if (bBoundingBoxContains2(&tc->CachedBBoxMin, &tc->CachedBBoxMax,
                              &tc->InterestBBoxMin, &tc->InterestBBoxMax))
        return;

    r = r + 0.5f;
    topotree_remove(&TheTopologyTree, table, tc->TotalNumTrackPolygons);
    tc->TotalNumTrackPolygons = 0;
    tc->NumTrackPolygons = 0;
    tc->NumVerticalTrackPolygons = 0;
    tc->NumUpsideDownTrackPolygons = 0;

    for (i = 0; i < 10; i++) {
        float dx, dy;

        bInitializeBoundingBox2(&tc->CachedBBoxMin, &tc->CachedBBoxMax);
        bExpandBoundingBox2R(&tc->CachedBBoxMin, &tc->CachedBBoxMax, pos, r);
        if (vel != NULL) {
            bVector2 ahead;

            bScaleAdd2(&ahead, pos, vel, scale);
            bExpandBoundingBox2R(&tc->CachedBBoxMin, &tc->CachedBBoxMax,
                                 &ahead, r);
        }
        dx = tc->CachedBBoxMin.x - tc->CachedBBoxMax.x;
        dy = tc->CachedBBoxMin.y - tc->CachedBBoxMax.y;
        if (sqrtf(dx * dx + dy * dy) < 32.0f)
            break;
        scale = scale * 0.5f;
    }

    n = topotree_build(&TheTopologyTree, local, TOPOLOGY_MAX_POLYGONS,
                       &tc->CachedBBoxMin, &tc->CachedBBoxMax);

    k = 0;
    for (i = 0; i < n; i++) {
        if (local[i]->Flags & TRACKPOLY_VERTICAL)
            continue;
        if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)
            continue;
        table[k++] = local[i];
    }
    tc->NumTrackPolygons = k;

    vertical = 0;
    if (k != n) {
        int base = k;

        for (i = 0; i < n; i++) {
            if (local[i]->Flags & TRACKPOLY_VERTICAL)
                table[k++] = local[i];
        }
        vertical = k - base;
    }
    tc->NumVerticalTrackPolygons = vertical;

    if (k != n) {
        for (i = 0; i < n; i++) {
            if (local[i]->Flags & TRACKPOLY_UPSIDE_DOWN)
                table[k++] = local[i];
        }
    }
    tc->TotalNumTrackPolygons = n;
    tc->NumUpsideDownTrackPolygons = k - vertical;
}

// 0x00134f28, emitted in Car.obj: the bVector3 overload is `j 0x0014f120`,
// the same four registers, so x and y are read out of each vector and the
// rest of it is not.
void topology_set_interest_bbox3(TopologyCoordinate *tc, const bVector3 *pos,
                                 float r, const bVector3 *vel)
{
    topology_set_interest_bbox(tc, (const bVector2 *)pos, r,
                               (const bVector2 *)vel);
}

// 0x0014f418.
//
// Two passes over the floors: the first for a surface below pt.z + 1, the
// second, if that found none, for one at any height. A polygon counts when
// (x, y) is in its box and on the inner side of all four edges -- four
// whatever NumVertices says, skipping any of zero length -- and its plane
// is above everything accepted so far. One strictly inside, and not
// flagged INFINITELY_HIGH, ends the pass at once; one on an edge, or
// flagged, is remembered and raises the floor for the rest of the pass.
//
// A hit at index 5 or later moves to the front of the table, so a car that
// stays on one polygon finds it first next time.
float topology_get_elevation(TopologyCoordinate *tc, const bVector3 *pt,
                             int32_t *terrain, bVector3 *normal,
                             int32_t *found)
{
    uint32_t start = bGetTicker();
    TrackPolygon **table = tc->TrackPolygonTable;
    bVector2 xy;
    float hi, result = 0.0f;
    int num, pass, hit = -1;

    if (found != NULL)
        *found = 1;
    xy.x = pt->x;
    xy.y = pt->y;
    if (!bBoundingBoxIsInside2(&tc->InterestBBoxMin, &tc->InterestBBoxMax,
                               &xy, 0.0f))
        topology_set_interest_bbox(tc, &xy, 8.0f, NULL);

    hi = pt->z + 1.0f;
    num = tc->NumTrackPolygons;
    for (pass = 0; pass < 2 && hit < 0; pass++) {
        float lo = -BVECTOR_FLT_MAX;
        int cand = -1;
        int i;

        for (i = 0; i < num; i++) {
            const TrackPolygon *tp = table[i];
            float px = pt->x, py = pt->y;
            float m, elev;
            int e;

            if (!(tp->BBoxMin.x <= px) || !(px <= tp->BBoxMax.x))
                continue;
            if (!(tp->BBoxMin.y <= py) || !(py <= tp->BBoxMax.y))
                continue;

            m = -1.0f;
            for (e = 0; e < 4; e++) {
                const bVector3 *ve = &tp->Vertices[e];
                const bVector3 *vj = &tp->Vertices[(e + 1) % 4];
                float cross;

                if (ve->x == vj->x && ve->y == vj->y)
                    continue;
                cross = (vj->y - ve->y) * (px - ve->x)
                      - (vj->x - ve->x) * (py - ve->y);
                if (0.0f < cross) {
                    m = cross;
                    break;
                }
                if (m < cross)
                    m = cross;
            }
            if (!(m <= 0.0f))
                continue;

            elev = (tp->PlaneDistance
                    - (tp->Normal.x * px + tp->Normal.y * py)) / tp->Normal.z;
            if (!(lo < elev) || !(elev < hi))
                continue;
            if ((tp->Flags & TRACKPOLY_INFINITELY_HIGH) || !(m < 0.0f)) {
                lo = elev;
                cand = i;
                continue;
            }
            hit = i;
            result = elev;
            break;
        }
        if (hit < 0 && cand >= 0) {
            hit = cand;
            result = lo;
        }
        hi = BVECTOR_FLT_MAX;
    }

    if (hit < 0) {
        result = pt->z;
        if (found != NULL)
            *found = 0;
        if (terrain != NULL)
            *terrain = 1;
        if (normal != NULL) {
            normal->x = 0.0f;
            normal->z = -1.0f;
            normal->y = 0.0f;
        }
    } else {
        TrackPolygon *tp = table[hit];

        if (hit >= 5) {
            int k;

            for (k = hit; k > 0; k--)
                table[k] = table[k - 1];
            table[0] = tp;
        }
        if (terrain != NULL)
            *terrain = (int8_t)tp->TheTerrainType;
        if (normal != NULL) {
            normal->x = tp->Normal.x;
            normal->y = tp->Normal.y;
            normal->z = tp->Normal.z;
            normal->pad = tp->PlaneDistance;
        }
    }

    TopologyTiming[TopologyTimingIndex % 10u] =
        bGetTickerDifference(start, bGetTicker()) * 1000.0f;
    TopologyTimingIndex++;
    return result;
}

// 0x0014f7e8.
int topology_has_topology(TopologyCoordinate *tc, const bVector2 *xy)
{
    bVector3 p;
    int32_t found;

    p.x = xy->x;
    p.y = xy->y;
    p.z = TRACK_PROBE_Z;
    p.pad = 0.0f;
    topology_get_elevation(tc, &p, NULL, NULL, &found);
    return found;
}

// 0x0014f830. The first crossing ends the walk; `best` only filters.
int topology_segment_intersects(TopologyCoordinate *tc, const bVector3 *a,
                                const bVector3 *b, float r)
{
    bVector3 mn, mx;
    float best = TRACK_FAR;
    int i;

    bInitializeBoundingBox3At(&mn, &mx, a);
    bExpandBoundingBox3R(&mn, &mx, b, r);
    for (i = 0; i < tc->TotalNumTrackPolygons; i++) {
        if (trackpolygon_test_segment(tc->TrackPolygonTable[i], &best, a, b,
                                      &mn, &mx, 0))
            return 1;
    }
    return 0;
}

// 0x0014f920. The whole table is walked and the nearest crossing kept.
//
// `d` and the new `to` are four lanes: the moves are vadd.xyzw and
// vsub.xyzw and `to` is stored whole, while bNormalize writes only xyz. So
// on the two paths that rebuild `to` from `from`, its fourth lane comes
// back as from.pad + (to.pad - from.pad), rounded, and the port does the
// same sum. With no polygon crossed the best distance stays at 999999 and
// the move is left alone unless it is longer than that -- in which case
// the image reads the flags of a NULL polygon and so would the port.
int topology_constrain(TopologyCoordinate *tc, int type, int twoSided,
                       const bVector3 *from, bVector3 *to, float dist,
                       float lift)
{
    const TrackPolygon *hitp = NULL;
    bVector3 mn, mx, d;
    float best = TRACK_FAR;
    float len, s;
    int i;

    bInitializeBoundingBox3At(&mn, &mx, from);
    bExpandBoundingBox3R(&mn, &mx, to, dist);
    for (i = 0; i < tc->TotalNumTrackPolygons; i++) {
        const TrackPolygon *tp = tc->TrackPolygonTable[i];

        if (trackpolygon_test_segment(tp, &best, from, to, &mn, &mx,
                                      twoSided))
            hitp = tp;
    }

    d.x   = to->x   - from->x;
    d.y   = to->y   - from->y;
    d.z   = to->z   - from->z;
    d.pad = to->pad - from->pad;
    len = sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);
    if (!(best < len))
        return 0;

    if (type == TOPOLOGY_CONSTRAIN_BY_ROTATION) {
        if (hitp->Flags & TRACKPOLY_VERTICAL) {
            float k;

            s = best - dist;
            k = s / len;
            bNormalize3To(&d, &d, s);
            d.z = d.z + lift * (1.0f - k);
            to->x   = from->x   + d.x;
            to->y   = from->y   + d.y;
            to->z   = from->z   + d.z;
            to->pad = from->pad + d.pad;
        } else if (hitp->Flags & TRACKPOLY_UPSIDE_DOWN) {
            to->z = (hitp->PlaneDistance
                     - (hitp->Normal.x * to->x + hitp->Normal.y * to->y))
                    / hitp->Normal.z - dist;
        } else {
            to->z = (hitp->PlaneDistance
                     - (hitp->Normal.x * to->x + hitp->Normal.y * to->y))
                    / hitp->Normal.z + dist;
        }
        return 1;
    }
    if (type == TOPOLOGY_CONSTRAIN_BY_SCALE) {
        s = best - dist;
        bNormalize3To(&d, &d, s);
        to->x   = from->x   + d.x;
        to->y   = from->y   + d.y;
        to->z   = from->z   + d.z;
        to->pad = from->pad + d.pad;
        return 1;
    }
    return 1;
}

// ---------------------------------------------------------- TopologyTree

// 0x0014fb80.
void topotree_init(TopologyTree *t)
{
    t->TrackPolygonList.pNext = p32_of(&t->TrackPolygonList);
    t->TrackPolygonList.pPrev = p32_of(&t->TrackPolygonList);
    t->pNodeTable = NULL;
    t->NumNodes = 0;
    t->pSquareTable = NULL;
    t->NumSquares = 0;
    t->pPolygonTable = NULL;
    t->NumPolygons = 0;
    t->pPolygonIndexTable = NULL;
    t->NumPolygonIndicies = 0;
}

// 0x0014fbb8. Sized by the port's record, so a host slot is wider than
// the image's 128 bytes and a slot number means the same thing on both.
void topotree_init_tree(TopologyTree *t)
{
    (void)t;
    TrackPolygonSlotPool = bNewSlotPool((int)sizeof(TrackPolygon), 1024,
                                        "TrackPolygonSlotPool", 16);
    bClearSlotPoolFlag(TrackPolygonSlotPool, BSP_OVERFLOW_IF_FULL);
    bClearSlotPoolFlag(TrackPolygonSlotPool, BSP_ZERO_ALLOCATED_MEMORY);
}

// 0x0014fc00.
void topotree_close_tree(TopologyTree *t)
{
    TrackListNode *head = &t->TrackPolygonList;
    TrackListNode *n;

    if (TrackPolygonSlotPool == NULL)
        return;
    for (n = node_at(head->pNext); n != head; n = node_at(head->pNext)) {
        unlink_node(n);
        trackpolygon_destroy((TrackPolygon *)n, 3);
    }
    bDeleteSlotPool(TrackPolygonSlotPool);
    TrackPolygonSlotPool = NULL;
}

// 0x0014fc78. The node and square chunks' records start at the first
// 16-byte boundary past the header, so their counts are what is left of
// the chunk after that pad.
int topotree_loader(TopologyTree *t, uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);
    uint32_t size = bchunk_u32(chunk + 4);
    uint8_t *body = chunk + 8;
    uint8_t *aligned =
        (uint8_t *)(((uintptr_t)chunk + 23) & ~(uintptr_t)15);

    if (type == 0x34130) {
        t->pNodeTable = (TopologyTreeNode *)aligned;
        t->NumNodes = (int32_t)((size - (uint32_t)(aligned - body)) >> 3);
        return 1;
    }
    if (type == 0x34131) {
        t->pSquareTable = (TopologyTreeSquare *)aligned;
        t->NumSquares = (int32_t)((size - (uint32_t)(aligned - body)) / 12u);
        return 1;
    }
    if (type == 0x34132) {
        int32_t n = (int32_t)(size >> 5);
        int32_t i;

        t->pPolygonTable = (TopologyTreePolygon *)body;
        t->NumPolygons = n;
        for (i = 0; i < n; i++)
            t->pPolygonTable[i].TrackPolygonNumber = -1;
        return 1;
    }
    if (type == 0x34133) {
        t->pPolygonIndexTable = (uint16_t *)body;
        t->NumPolygonIndicies = (int32_t)(size >> 1);
        return 1;
    }
    return 0;
}

// 0x0014fd98.
int topotree_unloader(TopologyTree *t, const uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);

    if (type == 0x34130) {
        t->NumNodes = 0;
        t->pNodeTable = NULL;
        return 1;
    }
    if (type == 0x34131) {
        t->NumSquares = 0;
        t->pSquareTable = NULL;
        return 1;
    }
    if (type == 0x34132) {
        t->NumPolygons = 0;
        t->pPolygonTable = NULL;
        return 1;
    }
    if (type == 0x34133) {
        t->NumPolygonIndicies = 0;
        t->pPolygonIndexTable = NULL;
        return 1;
    }
    return 0;
}

// 0x0014fe18. The mask is -(int)2097152.0f, 32 in Q16.
float topotree_get_square_corner(float f)
{
    int32_t q = ee_trunc_w(f * 65536.0f) & -2097152;

    return (float)q * TRACK_Q16;
}

// 0x0014fe70. Ten levels, halving from 32768: level 1's children are
// squares. The "nearest" substitute is scored by the distance from (x, y)
// to the quadrant corner just chosen, which is the same for all four
// children, so it is the first non-empty one -- or -1, which the image
// then indexes with, as the port does.
TopologyTreeSquare *topotree_get_square(const TopologyTree *t, float x,
                                        float y, int nearest)
{
    const TopologyTreeNode *node = t->pNodeTable;
    float minx = -16384.0f, miny = -16384.0f;
    int lvl;

    for (lvl = 10; ; lvl--) {
        float half = ((float)(1 << lvl) * 32.0f) * 0.5f;
        float mx = minx + half;
        float my = miny + half;
        int q = 0;
        int32_t c;

        if (mx <= x)
            q = 1;
        if (my <= y)
            q += 2;
        if (q & 1)
            minx = mx;
        if (q & 2)
            miny = my;

        c = node->ChildrenNodeNumbers[q];
        if (c == 0) {
            float dx, dy, best = 0.0f;
            int32_t pick = -1;
            int k;

            if (!nearest)
                return NULL;
            dx = minx - x;
            dy = miny - y;
            for (k = 0; k < 4; k++) {
                float dd = fabsf(dx) + fabsf(dy);
                int32_t ch = node->ChildrenNodeNumbers[k];

                if (ch == 0)
                    continue;
                if (dd < best || pick < 0) {
                    pick = ch;
                    best = dd;
                }
            }
            c = pick;
        }
        if (lvl == 1)
            return t->pSquareTable + c;
        node = t->pNodeTable + c;
    }
}

// 0x0014ffa0. The polygon's box from its MaxMinBits, touching counted.
int topotree_get_intersecting_polygons(const TopologyTree *t,
                                       TopologyTreePolygon **out, int max,
                                       const TopologyTreeSquare *sq,
                                       const bVector2 *bmin,
                                       const bVector2 *bmax)
{
    int count = 0;
    int i, end;

    if (sq == NULL)
        return 0;
    end = (int)sq->FirstPolygonIndex + sq->NumPolygons;
    for (i = sq->FirstPolygonIndex; i < end; i++) {
        TopologyTreePolygon *p =
            &t->pPolygonTable[t->pPolygonIndexTable[i]];
        unsigned m = p->MaxMinBits;

        if (p->UsedByNeighbourFlag != 0)
            continue;
        if (!(xy_of(p->VerticesX[m & 3]) <= bmax->x))
            continue;
        if (!(xy_of(p->VerticesY[(m >> 2) & 3]) <= bmax->y))
            continue;
        if (!(bmin->x <= xy_of(p->VerticesX[(m >> 4) & 3])))
            continue;
        if (!(bmin->y <= xy_of(p->VerticesY[m >> 6])))
            continue;
        if (count < max) {
            out[count++] = p;
            p->UsedByNeighbourFlag = 1;
        }
    }
    return count;
}

// 0x00150110. Oldest first. A flush that finds nothing to free calls
// bBreak (0x00238888, `break`), the debugger's stop: with every slot held,
// the pool cannot supply the slot AssignTrackPolygon is about to take.
// There is no debugger on the handheld; the port carries on to the same
// NULL the image would reach had the break returned.
void topotree_flush_unused(TopologyTree *t)
{
    TrackListNode *head = &t->TrackPolygonList;
    TrackListNode *n = node_at(head->pNext);
    int deleted = 0;

    while (n != head) {
        TrackListNode *prev;

        if ((int8_t)((TrackPolygon *)n)->ReferenceCount != 0) {
            n = node_at(n->pNext);
            continue;
        }
        prev = node_at(n->pPrev);
        unlink_node(n);
        trackpolygon_destroy((TrackPolygon *)n, 3);
        deleted++;
        if (!(deleted < 101))
            break;
        n = node_at(prev->pNext);
    }
}

// 0x001501b0.
TrackPolygon *topotree_assign(TopologyTree *t, TopologyTreePolygon *p)
{
    TrackPolygon *tp;

    if (p->TrackPolygonNumber >= 0) {
        tp = (TrackPolygon *)bGetSlot(TrackPolygonSlotPool,
                                      p->TrackPolygonNumber);
    } else {
        if (bIsSlotPoolFull(TrackPolygonSlotPool))
            topotree_flush_unused(t);
        tp = trackpolygon_init((TrackPolygon *)bSlotMalloc(TrackPolygonSlotPool),
                               p);
        append_node(&t->TrackPolygonList, &tp->node);
    }
    tp->ReferenceCount = (uint8_t)(tp->ReferenceCount + 1);
    return tp;
}

// 0x00150250.
void topotree_unassign(TopologyTree *t, TrackPolygon *tp)
{
    (void)t;
    tp->ReferenceCount = (uint8_t)(tp->ReferenceCount - 1);
}

// 0x00150260. The four corners' squares, each gathered once: a corner
// whose square an earlier corner already had is skipped.
int topotree_build(TopologyTree *t, TrackPolygon **out, int max,
                   const bVector2 *bmin, const bVector2 *bmax)
{
    TopologyTreePolygon *stack[TOPOLOGY_MAX_POLYGONS];
    TopologyTreeSquare *s0, *s1, *s2, *s3;
    int n, i;

    s0 = topotree_get_square(t, bmin->x, bmin->y, 0);
    s1 = topotree_get_square(t, bmax->x, bmin->y, 0);
    s2 = topotree_get_square(t, bmin->x, bmax->y, 0);
    s3 = topotree_get_square(t, bmax->x, bmax->y, 0);

    n = topotree_get_intersecting_polygons(t, stack, max, s0, bmin, bmax);
    if (s1 != s0)
        n += topotree_get_intersecting_polygons(t, stack + n, max - n, s1,
                                                bmin, bmax);
    if (s2 != s1 && s2 != s0)
        n += topotree_get_intersecting_polygons(t, stack + n, max - n, s2,
                                                bmin, bmax);
    if (s3 != s2 && s3 != s1 && s3 != s0)
        n += topotree_get_intersecting_polygons(t, stack + n, max - n, s3,
                                                bmin, bmax);

    for (i = 0; i < n; i++) {
        stack[i]->UsedByNeighbourFlag = 0;
        out[i] = topotree_assign(t, stack[i]);
    }
    return n;
}

// 0x00150420.
void topotree_remove(TopologyTree *t, TrackPolygon **table, int n)
{
    int i;

    for (i = 0; i < n; i++)
        topotree_unassign(t, table[i]);
}

// ------------------------------------------------------------ TrackInfo

// 0x00150478.
TrackInfo *track_get_info(int i)
{
    TrackInfo *p;

    if (i <= 0 || HighestTrackNumber < i)
        return NULL;
    p = TrackInfoTable + (i - 1);
    return p->Name[0] != 0 ? p : NULL;
}

// ------------------------------------------------------------ road noise

// 0x001504b0. The products wrap, as mult's low word does.
float track_get_road_noise_grid_value(int x, int y)
{
    uint32_t a = (uint32_t)x * (uint32_t)y * 11u;
    uint32_t b = ((uint32_t)x + 1u) * ((uint32_t)y + 1u) * 13u;

    return RoadNoiseTable[(a + b) & 15u];
}

// 0x001504f0. floor() spelled as cvt.w.s and a correction, the corners
// weighted in the listing's order and summed left to right.
float track_get_road_noise(const bVector2 *p, int32_t terrain)
{
    const TerrainTypeInfo *info = &TerrainTypeInfoTable[terrain];
    float fx = p->x * info->RoadNoiseGridSpacingInverse;
    float fy = p->y * info->RoadNoiseGridSpacingInverse;
    float flx = (float)ee_trunc_w(fx);
    float fly;
    float tx, ty, acc;
    int ix, iy;

    if (fx < flx)
        flx = flx - 1.0f;
    fly = (float)ee_trunc_w(fy);
    if (fy < fly)
        fly = fly - 1.0f;
    ix = ee_trunc_w(flx);
    iy = ee_trunc_w(fly);
    ty = fy - fly;
    tx = fx - flx;

    acc = ((1.0f - tx) * (1.0f - ty)) * track_get_road_noise_grid_value(ix, iy);
    acc = acc + (tx * (1.0f - ty))
                * track_get_road_noise_grid_value(ix + 1, iy);
    acc = acc + ((1.0f - tx) * ty)
                * track_get_road_noise_grid_value(ix, iy + 1);
    acc = acc + (tx * ty) * track_get_road_noise_grid_value(ix + 1, iy + 1);
    return acc * info->RoadNoiseScale;
}

// ------------------------------------------------------------ the loader

// 0x00150660. Track 54's entry in the global table is cleared on load --
// whatever it was, the game is not to offer it.
int track_loader_geometry(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);
    uint32_t size = bchunk_u32(chunk + 4);

    if (type == 0x34200) {
        CurrentTrackInfo = (TrackInfo *)(chunk + 8);
        LoadedTrackNumber = CurrentTrackInfo->TrackNumber;
        return 1;
    }
    if (type == 0x34201) {
        TrackInfo *hidden;

        TrackInfoTable = (TrackInfo *)(chunk + 8);
        HighestTrackNumber = (int32_t)(size / 160u);
        hidden = track_get_info(54);
        if (hidden != NULL)
            memset(hidden, 0, sizeof(TrackInfo));
        return 1;
    }
    if (type == 0x34146) {
        int32_t n = (int32_t)(size / 24u);
        int32_t i;

        for (i = 0; i < n; i++) {
            TrackPositionMarker *m =
                (TrackPositionMarker *)(chunk + 8 + 24 * i);

            append_node(&TrackPositionMarkerList, &m->node);
        }
        return 1;
    }
    return topotree_loader(&TheTopologyTree, chunk) != 0;
}

// 0x00150770.
int track_unloader_geometry(const uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);
    uint32_t size = bchunk_u32(chunk + 4);

    if (type == 0x34200) {
        CurrentTrackInfo = NULL;
        LoadedTrackNumber = 0;
        return 1;
    }
    if (type == 0x34201) {
        TrackInfoTable = NULL;
        HighestTrackNumber = 0;
        return 1;
    }
    if (type == 0x34146) {
        int32_t n = (int32_t)(size / 24u);
        int32_t i;

        for (i = 0; i < n; i++) {
            TrackPositionMarker *m =
                (TrackPositionMarker *)(chunk + 8 + 24 * i);

            unlink_node(&m->node);
        }
        return 1;
    }
    return topotree_unloader(&TheTopologyTree, chunk) != 0;
}

// 0x00150938.
void track_static_init(void)
{
    TrackPositionMarkerList.pPrev = p32_of(&TrackPositionMarkerList);
    TrackPositionMarkerList.pNext = p32_of(&TrackPositionMarkerList);
    topotree_init(&TheTopologyTree);
}
