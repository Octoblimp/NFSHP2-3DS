// previewspline -- PreviewRoute::MakeSplines and the free functions it
// calls, out of zonecameras.cpp. The addresses are retail's.
//
// The Zone Preview camera flies ahead along the road and back. Its course
// is three splines laid along a PreviewRoute, one control point every 10
// along the road at the route's lateral offset:
//
//   - the look spline, 1.5 above the ground (the comet runs along it and
//     the camera looks at it);
//   - the eye-forward spline, 0.5 above that (the camera's way out);
//   - the eye-backward spline, 10 above the look spline (its way back).
//
// The ground is TopologyCoordinate::GetElevation's under each point. Then
// 100 samples along the look spline push each eye spline's point out of
// the walls (ConstrainToTopology) and cap its height above the look spline
// at what the walls left it; the two ends of the flight, by the eye's
// Linear, share one height gap each; the eye splines' slopes are held to
// 0.4; and all three are smoothed in XY by DownSampleXY to a third of
// their points and back.
//
// The names are the demo's .mdebug record's (ZonePreviewCameraMover's
// mLookSpline, mEyeForwardSpline, mEyeBackwardSpline and EyeParameter),
// matched to MakeSplines's arguments by the demo's constructor. Retail's
// mover passes this + 108, + 204, + 252 and + 300; its VisibleDrivingLine
// (0x00174fe8) passes a look spline alone, with NULL for the rest, and
// retail's MakeSplines tests each for NULL where the demo's did not.
//
// Two methods of other classes are here until their modules take them:
// Spline::SetControlPoint (spline.cpp) and the Graph lookup the other way
// round, new in retail (table.cpp's inline Graph).
//
// Written up in docs/formats/preview-splines.md; checked on retail's image
// by tools/previewspline_check.py.

#ifndef PREVIEWSPLINE_H
#define PREVIEWSPLINE_H

#include <stdint.h>

#include "average.h"
#include "bvector.h"
#include "graph.h"
#include "previewroute.h"
#include "spline.h"
#include "topology.h"

// The most stops DownSampleXY keeps: its knee array has room for this many
// and the two ends. Retail does not check; its one caller with stops,
// 0x00165a70, passes at most 4.
#define PREVIEW_MAX_STOPS 4

// 0x00166570, PreviewRoute::MakeSplines. Every spline may be NULL, and
// `eyeParam` too: the walk lays each spline there is; the 100-sample pass
// against the walls needs all three; the two ends' gaps need the look and
// eye-forward splines and `eyeParam` (the eye-backward one joins in when
// it is there); the slope limit and the smoothing go to each spline there
// is. Each spline gets its points with AddControlPoint, so it should come
// empty (Spline's allocating constructor). The walk moves the route's
// fOffset towards each route point's offset, 4 a step, and leaves
// fDistance at the last control point's distance along the road. Nothing
// happens when the route has no points.
void preview_route_make_splines(PreviewRoute *pr, TopologyCoordinate *tc,
                                Spline *look, Spline *eyeForward,
                                Spline *eyeBackward, const Linear *eyeParam);

// 0x00164e58, LinearSeek: `from` moved towards `to` by `step`, landing on
// `to` when it is no more than `step` away.
float preview_linear_seek(float from, float to, float step);

// 0x00164ea8, EnforceHeightGap(Spline *, Spline *, int, float): control
// point `i` of `s` put no more than `gap` above control point `i` of `ref`.
// An `i` outside s's points does nothing; ref's count is not checked.
void preview_enforce_height_gap_at(const Spline *ref, Spline *s, int32_t i,
                                   float gap);

// 0x00164f20, EnforceHeightGap(Spline *, Spline *, int): the smallest gap
// between the two curves at the whole parameters from 0 to i + 2 (when `i`
// is in s's first half) or from i - 2 to s's last point (when not),
// starting from 1000, and then every point of that span held to it.
void preview_enforce_height_gap(const Spline *ref, Spline *s, int32_t i);

// 0x00165150, DownSampleXY (the demo's DownSampleXY__FP6Splinef; retail
// added `stops` and `numStops`). Smooths the spline's XY: the curve is
// sampled at ceil(fraction * n) points, a spline through those is read
// back at each of the n control points' parameters, and the control point
// takes that x and y and keeps the curve's own z there. Each of the
// `numStops` parameters in `stops` (none when `stops` is NULL; at most
// PREVIEW_MAX_STOPS) is pinned to a coarse point, so the smoothing leaves
// it where it was. The coarse points are on the stack (past 64 of them, a
// malloc'd block freed before the return; no bMalloc). Sets no Dirty flag.
// A spline of 3 points or fewer samples to one coarse point, and retail
// then reads its stack past it; see the .c.
void preview_down_sample_xy(Spline *s, float fraction, const float *stops,
                            int32_t numStops);

// 0x001656b0, EnforceMaximumSlope: forwards then backwards, each control
// point no higher than its neighbour plus `slope` times their distance in
// XY. Changes z only, and sets no Dirty flag.
void preview_enforce_maximum_slope(Spline *s, float slope);

// ---------------------------------------- other classes' methods, for now

// 0x00189460, Spline::SetControlPoint (spline.cpp): control point `i`
// becomes `v`, all four lanes. No bounds check, and Dirty is not set.
void spline_set_control_point(Spline *s, int32_t i, const bVector3 *v);

// 0x0018faf0, new in retail, beside Graph::GetValue (0x0018f9f0): the
// lookup the other way round, the x where the curve reaches `y`. The knees
// must climb in y. Its quirks are GetValue's mirrored: below the first
// knee the first x, at or past the last the last x, a pair of knees closer
// than 1e-6 in y (gp-29948) their midpoint in x; and with fewer than two
// knees, or a `y` no segment holds (a NaN), the first knee's *y*.
float graph_get_inverse(const Graph *g, float y);

#endif
