// previewstops -- 0x00165a70, the Zone Preview's stops, and the functions
// it calls, out of zonecameras.cpp. The addresses are retail's.
//
// The Zone Preview camera flies ahead along the road (zonepreview.c). On
// the way it stops to look at what is waiting for the player: the spike
// strips, the roadblocks, the cops on the road and the helicopter in a cop
// race; the leader, the car in second, the cars in the air and the
// two-car crashes in a race without cops. 0x00165a70, new in retail and
// without a symbol, finds them. Points within 20 of each other make one
// stop (a PreviewPause). For each stop, it finds where on the eye-forward
// spline the camera sees it ahead, about 53 degrees off its way (a cosine
// of -0.6), and from the two Linears the look spline's control point the
// camera looks at then. The look-ahead spline is the look spline with each
// such point moved onto its stop, and `stops` gets those points' numbers,
// in order, for DownSampleXY to keep where they are and for the mover to
// slow down at.
//
// The names PreviewPause and PreviewPausePoint are the strings retail's
// bMalloc gets for them; the rest are the port's.
//
// Four methods of other classes are here until their modules take them:
// two of Spline's (spline.cpp), one of Linear's (average.cpp), one of
// TopologyCoordinate's (topology.cpp) and one of tSpikeStrip's
// (spikestrip.cpp). All five are new in retail.
//
// Written up in docs/formats/preview-stops.md; checked on retail's image
// by tools/previewstops_check.py.

#ifndef PREVIEWSTOPS_H
#define PREVIEWSTOPS_H

#include <stddef.h>
#include <stdint.h>

#include "average.h"
#include "blist.h"
#include "bvector.h"
#include "previewroute.h"
#include "spline.h"
#include "topology.h"

struct tSpikeStrip;

// A point a stop is made of, 32 bytes, bMalloc'd as "PreviewPausePoint"
// (0x002b1fc0) at 16-byte alignment.
typedef struct PreviewPausePoint {
    bNode    Node;          //  0  on its PreviewPause's Points
    uint8_t  _pad8[8];      //  8  the quadword round-up
    bVector3 Position;      // 16  all four lanes, as given
} PreviewPausePoint;        // 32

// A stop, 16 bytes, bMalloc'd as "PreviewPause" (0x002b1fd8) at 16-byte
// alignment: the points within 20 of each other, kept on a list on
// 0x00165a70's stack.
typedef struct PreviewPause {
    bNode Node;             //  0  on 0x00165a70's list
    bNode Points;           //  8  bTList<PreviewPausePoint>, in order
} PreviewPause;             // 16

// A stop found on the look spline: the control point's number and where
// the stop is. 0x00165a70 keeps an array of them on its stack, maxStops
// long, and sorts it by Param.
typedef struct PreviewStopEntry {
    float    Param;         //  0  a look spline control point, as a float
    uint8_t  _pad4[12];     //  4
    bVector3 Position;      // 16  the stop's centre
} PreviewStopEntry;         // 32

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char previewstops_layout_check[
    (offsetof(PreviewPausePoint, Position) == 16
     && sizeof(PreviewPausePoint) == 32
     && offsetof(PreviewPause, Points) == 8 && sizeof(PreviewPause) == 16
     && offsetof(PreviewStopEntry, Position) == 16
     && sizeof(PreviewStopEntry) == 32) ? 1 : -1];
#endif

// 0x00165a70. The stops along the preview's way, at most `maxStops` of
// them. With a cop manager: each spike strip's centre (and the cops of the
// active roadblocks with its roadblock ID are not looked at again); each
// cop in Cops[0..nNumCops) not already seen whose DesiredLogicState is
// SPEED_TRAP, DRIVING_ON_PATROL, CAUGHT_SPEEDER or GUARD_LOCATION, at its
// car's GeometryPosition; a ROAD_BLOCK cop at its car's, or halfway
// between its active roadblock's two cops' cars when those are closer
// than 10, and that roadblock's cops are then seen; and the helicopter
// when its Plan is PURSUIT, HEAD_TO_STAKEOUT, AT_STAKEOUT or BOMBING_RUN.
// Without one: the first car from AICarPos to CopCarPos in first place,
// then each there in second place or with no wheel on the ground, at its
// Position, and each two-car collision's CurrentContactPoint; these only
// start stops, never join one, and a stop the topology hides from the
// camera is dropped.
//
// For each stop, in the order found, its centre's parameter on
// `eyeForward` (spline_find_approach_param), back through `eyeParam` to
// the preview's time and on through `lookParam` to the look spline,
// floored: that control point, or the one before when it is taken or
// past the end. It must lie strictly between the look spline's parameters
// at time 0 and time 1, and the stop within 60 of the eye-forward spline
// there. Then `stops` gets the points' numbers in order, `lookAhead`
// (empty, as the mover makes it) gets each of look's control points or,
// for a stop's, the stop's centre, and DownSampleXY smooths it in XY with
// the stops pinned. The stops are freed. `stops` past the count is left
// alone.
//
// Returns the count; its one caller, the mover's constructor, drops it.
// Retail's `route` is not read. `look` needs a control point:
// with none retail's bMemSet runs away (a size of -1); the port goes on.
int32_t preview_route_find_stops(PreviewRoute *route,
                                 TopologyCoordinate *tc, Spline *eyeForward,
                                 Spline *look, Spline *lookAhead,
                                 const Linear *eyeParam,
                                 const Linear *lookParam, float *stops,
                                 int32_t maxStops);

// 0x001659d0, the stops' HeapSort compare: a's Param less b's.
float preview_stop_compare(const void *a, const void *b);

// ---------------------------------------- other classes' methods, for now

// 0x0018a160 (spline.cpp, no symbol): the cosine between the way from `pt`
// to the spline's point at `t` and the spline's direction there. Each is
// scaled by VU0's reciprocal root of its length squared; a zero length
// gives a NaN.
float spline_approach_cosine(const Spline *s, const bVector3 *pt, float t);

// 0x0018a238 (spline.cpp, no symbol): where on the spline the cosine
// above reaches `target`. The cosine less the target at each whole
// parameter from 0 to the last control point; between each pair where
// that changes sign, the pair's midpoint's distance to `pt`; the nearest
// pair wins (the first on a tie). Then up to 10 halvings of that pair,
// stopping within `tol`. Retail starts the halving with the sign of the
// last control point's, not the pair's upper end's. With no change of
// sign: past the end (the last parameter + 1) when the last is below the
// target, else -1.
float spline_find_approach_param(const Spline *s, const bVector3 *pt,
                                 float target, float tol);

// 0x00190088 (average.cpp, no symbol): the x where the line reaches `y`;
// b itself when the slope is within 0.001 (gp-29944) of flat.
float linear_get_inverse(const Linear *l, float y);

// 0x00152690 (topology.cpp, no symbol): 1 when the segment from `a` to `b`
// crosses the topology. Shorter than 30, one SetInterestBBox about the
// middle and one SegmentIntersects of a-b; else ceil(length / 30) steps
// from `b` towards `a`, each with a box about its own middle and the step
// tested from its far end back, stopping at the first that crosses.
int32_t topology_segment_blocked(TopologyCoordinate *tc, const bVector3 *a,
                                 const bVector3 *b);

// 0x00241960 (spikestrip.cpp, no symbol): the mean of the belt pieces'
// positions (their matrices' fourth rows), times 1/n from two pieces on.
// Retail starts the fourth lane of the sum from a stack word; the port
// from 0.
void tspikestrip_get_centre(const struct tSpikeStrip *s, bVector3 *out);

#endif
