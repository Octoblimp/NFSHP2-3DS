// previewspline -- see previewspline.h.

#include "previewspline.h"

#include <math.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>

#include "eefpu.h"
#include "zonecam.h"

// The walk: a control point every 10 along the road (lui 0x4120), the
// interest box 12 about it (0x4140), the look spline 1.5 above the ground
// (0x3fc0), the eye-forward one 0.5 above that (0x3f00) and the
// eye-backward one 10 (the step's register again). The route's offset
// seeks each route point's at 4 a step (0x4080).
#define PS_STEP          10.0f
#define PS_WALK_BOX      12.0f
#define PS_LOOK_HEIGHT   1.5f
#define PS_FORWARD_RISE  0.5f
#define PS_BACKWARD_RISE 10.0f
#define PS_SEEK_STEP     4.0f

// The pass against the walls: 100 samples (slti 100) at 1/99 of the look
// spline apart (gp-30692, -30684 and -30680), each with an interest box of
// 10.7 (gp-30688).
#define PS_SAMPLES       100
#define PS_SAMPLE_STEP   0.01010101f
#define PS_SAMPLE_BOX    10.7f

// The eye splines' slope (gp-30676, -30672), and the share of points the
// smoothing keeps (gp-30668, -30664, -30660): 0.3333, not a third.
#define PS_MAX_SLOPE     0.4f
#define PS_DOWN_SAMPLE   0.3333f

// EnforceHeightGap's smallest gap to start from (lui 0x447a).
#define PS_GAP_START     1000.0f

// The most coarse points DownSampleXY keeps on the stack (1 KB); see there.
#define PS_STACK_COARSE  64

// The Graph lookup the other way round: its epsilon, gp-29948 (retail's
// GetValue, 0x0018f9f0, has gp-29952, the same value).
#define GRAPH_INVERSE_EPSILON 9.99999997e-07f

// The spline's last parameter, as the image works it out inline at every
// use: n for a loop, n - 1 for the two that end, else 0.
static float spline_last(const Spline *s)
{
    if (s->Type == SPLINE_LOOP)
        return (float)s->NumControlPoints;
    if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)
        return (float)(s->NumControlPoints - 1);
    return 0.0f;
}

// ---------------------------------------------------------- MakeSplines

void preview_route_make_splines(PreviewRoute *pr, TopologyCoordinate *tc,
                                Spline *look, Spline *eyeForward,
                                Spline *eyeBackward, const Linear *eyeParam)
{
    float along = 0.0f;   // past route point i, along the road
    float dist = 0.0f;    // the last control point's distance
    float next = 0.0f;    // the next one's
    int32_t i = 0;

    if (pr->pPoints == NULL)
        return;

    // The walk. Each control point is the route at `along` past point i
    // and the route's offset across it, on the ground. The w lanes are 0
    // here; retail's are whatever its stack held (GetPosition writes its
    // own stack's, and the eye points' are never written), and no lane
    // reaches another anywhere below.
    while (i < pr->nPoints - 1 && next < pr->fDistance) {
        bVector3 pos, eye;

        pos.pad = 0.0f;
        preview_route_point_get_position_at(&pr->pPoints[i], &pos, along,
                                            pr->fOffset);
        topology_set_interest_bbox3(tc, &pos, PS_WALK_BOX, NULL);
        pos.z = topology_get_elevation(tc, &pos, NULL, NULL, NULL)
                + PS_LOOK_HEIGHT;
        if (look != NULL)
            spline_add_control_point(look, &pos);
        if (eyeForward != NULL) {
            eye.x = pos.x;
            eye.y = pos.y;
            eye.z = pos.z + PS_FORWARD_RISE;
            eye.pad = 0.0f;
            spline_add_control_point(eyeForward, &eye);
        }
        if (eyeBackward != NULL) {
            eye.x = pos.x;
            eye.y = pos.y;
            eye.z = pos.z + PS_BACKWARD_RISE;
            eye.pad = 0.0f;
            spline_add_control_point(eyeBackward, &eye);
        }
        dist = next;
        next = dist + PS_STEP;
        along += PS_STEP;
        // On past the route points `along` has passed, taking up each
        // jump's sideways gap; never past the last point, and not at all
        // once the next control point would be past the end.
        while (next < pr->fDistance && i < pr->nPoints - 1
               && pr->pPoints[i].fLength < along) {
            along -= pr->pPoints[i].fLength;
            i++;
            pr->fOffset += pr->pPoints[i].fRouteGap;
        }
        pr->fOffset = preview_linear_seek(pr->fOffset, pr->pPoints[i].fOffset,
                                          PS_SEEK_STEP);
    }
    pr->fDistance = dist;

    // The walls. At each of 100 samples along the look spline the ground is
    // found again; each eye spline's point is put above it, 0.5 or 10, and
    // the move from the look point up to it is constrained both ways (which
    // may move the look point too); what height is left is the most that
    // eye spline may stand above the look spline at the four control
    // points that sample reads.
    if (look != NULL && eyeForward != NULL && eyeBackward != NULL) {
        float gapForward[PS_SAMPLES];
        float gapBackward[PS_SAMPLES];
        int32_t k, j, at;

        for (k = 0; k < PS_SAMPLES; k++) {
            float t = spline_last(look) * (float)k * PS_SAMPLE_STEP;
            bVector3 pos, eye;

            spline_get_point(look, &pos, t);
            topology_set_interest_bbox3(tc, &pos, PS_SAMPLE_BOX, NULL);
            pos.z = topology_get_elevation(tc, &pos, NULL, NULL, NULL)
                    + PS_LOOK_HEIGHT;
            spline_get_point(eyeForward, &eye, t);
            eye.z = pos.z + PS_FORWARD_RISE;
            zone_constrain_to_topology(tc, &pos, &eye, 1, 0);
            gapForward[k] = eye.z - pos.z;
            spline_get_point(eyeBackward, &eye, t);
            eye.z = pos.z + PS_BACKWARD_RISE;
            zone_constrain_to_topology(tc, &pos, &eye, 1, 0);
            gapBackward[k] = eye.z - pos.z;
        }
        for (k = 0; k < PS_SAMPLES; k++) {
            at = ee_trunc_w(spline_last(look) * (float)k * PS_SAMPLE_STEP);
            for (j = at - 1; j < at + 3; j++)
                preview_enforce_height_gap_at(look, eyeForward, j,
                                              gapForward[k]);
        }
        for (k = 0; k < PS_SAMPLES; k++) {
            at = ee_trunc_w(spline_last(look) * (float)k * PS_SAMPLE_STEP);
            for (j = at - 1; j < at + 3; j++)
                preview_enforce_height_gap_at(look, eyeBackward, j,
                                              gapBackward[k]);
        }
    }

    // The ends of the flight: the eye's parameter at 0 and at 1, as control
    // points of the eye-forward spline, each with one gap about it.
    if (eyeParam != NULL && look != NULL && eyeForward != NULL) {
        int32_t first = ee_trunc_w(spline_last(eyeForward)
                                   * linear_get_value(eyeParam, 0.0f));
        int32_t last = ee_trunc_w(spline_last(eyeForward)
                                  * linear_get_value(eyeParam, 1.0f));

        preview_enforce_height_gap(look, eyeForward, first);
        preview_enforce_height_gap(look, eyeForward, last);
        if (eyeBackward != NULL) {
            preview_enforce_height_gap(look, eyeBackward, first);
            preview_enforce_height_gap(look, eyeBackward, last);
        }
    }

    if (eyeForward != NULL)
        preview_enforce_maximum_slope(eyeForward, PS_MAX_SLOPE);
    if (eyeBackward != NULL)
        preview_enforce_maximum_slope(eyeBackward, PS_MAX_SLOPE);
    if (look != NULL)
        preview_down_sample_xy(look, PS_DOWN_SAMPLE, NULL, 0);
    if (eyeForward != NULL)
        preview_down_sample_xy(eyeForward, PS_DOWN_SAMPLE, NULL, 0);
    if (eyeBackward != NULL)
        preview_down_sample_xy(eyeBackward, PS_DOWN_SAMPLE, NULL, 0);
}

// ---------------------------------------------------- the free functions

float preview_linear_seek(float from, float to, float step)
{
    float d = to - from;

    if (fabsf(d) <= step)
        step = fabsf(d);
    if (to < from)
        return from - step;
    if (from < to)
        return from + step;
    return from;
}

// The point is copied whole, its z changed and the copy stored, so the
// other three lanes go back as they were.
void preview_enforce_height_gap_at(const Spline *ref, Spline *s, int32_t i,
                                   float gap)
{
    bVector3 p;
    float below;

    if (i < 0 || !(i < s->NumControlPoints))
        return;
    p = s->pControlPoints[i];
    below = ref->pControlPoints[i].z;
    if (gap < p.z - below) {
        p.z = below + gap;
        spline_set_control_point(s, i, &p);
    }
}

// The span is measured on the curves (GetPoint at whole parameters, so
// past either end it is the extrapolation), and held on the control
// points, which the bounds check keeps to s's own.
void preview_enforce_height_gap(const Spline *ref, Spline *s, int32_t i)
{
    int32_t lo, hi, j;
    float gap = PS_GAP_START;

    if (i < s->NumControlPoints / 2) {
        lo = 0;
        hi = i + 2;
    } else {
        lo = i - 2;
        hi = s->NumControlPoints - 1;
    }
    for (j = lo; j <= hi; j++) {
        bVector3 a, b;

        spline_get_point(ref, &a, (float)j);
        spline_get_point(s, &b, (float)j);
        if (b.z - a.z < gap)
            gap = b.z - a.z;
    }
    for (j = lo; j <= hi; j++)
        preview_enforce_height_gap_at(ref, s, j, gap);
}

// bRound, inline at 0x00165328: down when the fraction is under a half,
// else up, each by cvt.w.s and a compare.
static float round_half_up(float x)
{
    float t = (float)ee_trunc_w(x);
    float down = x < t ? t - 1.0f : t;

    if (x - down < 0.5f)
        return down;
    return t < x ? t + 1.0f : t;
}

// The knees map a coarse point's index (x) to the spline's parameter (y):
// (0, 0), each stop at its parameter and its index rounded, and the last
// coarse point at the last parameter. Read forwards they place the coarse
// points; read the other way they say where on the coarse spline each
// control point's parameter falls.
//
// The knees are retail's five bVector2 at its frame's foot (the
// constructor loop runs five times), with eight bytes of padding after
// them before the Graph at +48; four stops write the closing knee into
// that padding, so four is the most that works there too. The port's
// array has room for all six and starts zeroed: retail's knees between
// the stops and the closing one are whatever the stack held when `stops`
// is NULL but `numStops` is not, which no caller does.
//
// The coarse points are retail's alloca, count * 16 bytes below its frame.
// With 3 points or fewer there is one, and GetPoint on a one-point
// EXTRAPOLATE spline reads the slot past it (retail's: its knee array) and
// the slot before it (retail's: below its stack pointer, the callee's
// frame), each with a weight of 0. The port keeps a zeroed spare at each
// end, so it reads zeros. The 3DS's stack is 32 KB, so past
// PS_STACK_COARSE coarse points they go on the heap instead (malloc, as
// they are the function's own and gone before it returns); with no room
// there the spline is left as it is. MakeSplines's splines have a point
// every 10 along a route of 320 or so, about 11 coarse points.
//
// The control points are rewritten one by one while the loop still reads
// the spline, so each GetPoint on `s` past the first sees the points
// before it already moved in XY; only their z is read back, and that was
// kept.
void preview_down_sample_xy(Spline *s, float fraction, const float *stops,
                            int32_t numStops)
{
    int32_t n = s->NumControlPoints;
    float want = fraction * (float)n;
    float whole = (float)ee_trunc_w(want);
    int32_t count, room, i;
    bVector2 knees[PREVIEW_MAX_STOPS + 2] = {{0}};
    Graph g;
    Spline coarse;
    float top;

    if (whole < want)
        whole += 1.0f;
    count = ee_trunc_w(whole);
    room = count > 0 ? count : 0;
    {
        bVector3 local[(room <= PS_STACK_COARSE ? room : 0) + 2];
        bVector3 *buf = local, *heap = NULL;
        bVector3 *pts;

        if (room > PS_STACK_COARSE) {
            heap = (bVector3 *)malloc(((size_t)room + 2) * sizeof(bVector3));
            if (heap == NULL)
                return;
            buf = heap;
        }
        pts = &buf[1];
        memset(&buf[0], 0, sizeof buf[0]);
        memset(&pts[room], 0, sizeof buf[0]);
        top = (float)(count - 1);
        knees[0].x = 0.0f;
        knees[0].y = 0.0f;
        if (stops != NULL && numStops > 0) {
            for (i = 0; i < numStops; i++) {
                knees[i + 1].x = round_half_up(top * stops[i]
                                               / spline_last(s));
                knees[i + 1].y = stops[i];
            }
        }
        knees[numStops + 1].x = top;
        knees[numStops + 1].y = spline_last(s);
        graph_init(&g, knees, numStops + 2);

        for (i = 0; i < count; i++)
            spline_get_point(s, &pts[i], graph_get_value(&g, (float)i));
        spline_init(&coarse, SPLINE_EXTRAPOLATE, count, pts, 0);

        for (i = 0; i < n; i++) {
            float t = (float)i * spline_last(s) / (float)(n - 1);
            bVector3 p, q;

            spline_get_point(&coarse, &p, graph_get_inverse(&g, t));
            spline_get_point(s, &q, t);
            p.z = q.z;
            spline_set_control_point(s, i, &p);
        }
        spline_destroy(&coarse, 2);
        free(heap);
    }
}

// Each pass reads the point it has just written as the next one's
// neighbour, so a drop runs on down the line.
void preview_enforce_maximum_slope(Spline *s, float slope)
{
    int32_t n = s->NumControlPoints;
    bVector3 *p = s->pControlPoints;
    int32_t i;

    for (i = 1; i < n; i++) {
        float dx = p[i].x - p[i - 1].x;
        float dy = p[i].y - p[i - 1].y;
        float z = p[i - 1].z + sqrtf(dx * dx + dy * dy) * slope;

        if (z < p[i].z)
            p[i].z = z;
    }
    for (i = n - 1; i > 0; i--) {
        float dx = p[i - 1].x - p[i].x;
        float dy = p[i - 1].y - p[i].y;
        float z = p[i].z + sqrtf(dx * dx + dy * dy) * slope;

        if (z < p[i - 1].z)
            p[i - 1].z = z;
    }
}

// ---------------------------------------- other classes' methods, for now

void spline_set_control_point(Spline *s, int32_t i, const bVector3 *v)
{
    s->pControlPoints[i] = *v;
}

float graph_get_inverse(const Graph *g, float y)
{
    const bVector2 *p = g->pPoints;
    int32_t n = g->NumPoints;
    int32_t i;

    if (n < 2)
        return p[0].y;
    if (y <= p[0].y)
        return p[0].x;
    if (p[n - 1].y <= y)
        return p[n - 1].x;
    for (i = 0; i < n - 1; i++) {
        if (p[i].y <= y && y < p[i + 1].y) {
            float dy = p[i + 1].y - p[i].y;
            float dx = p[i + 1].x - p[i].x;

            if (GRAPH_INVERSE_EPSILON < fabsf(dy))
                return p[i].x + (y - p[i].y) / dy * dx;
            return p[i].x + dx * 0.5f;
        }
    }
    // pPoints[0].y, as GetValue's own fall-through.
    return p[0].y;
}
