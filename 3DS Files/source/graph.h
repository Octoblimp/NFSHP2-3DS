// graph -- the Graph class (ctor 0x00187440, GetValue 0x00187450).
//
// A piecewise-linear curve over a caller-owned array of bVector2 knees,
// sorted by x. Fifteen call sites read one: the draft falloff and the
// catchup multipliers on Car, the jump stabilisers on PhysicsCar and
// MellowMover, the AI controller's glue speed and position boost, the
// belt mover's slide coefficient, Mellovator's derivative, the analog
// scanner's response curve and the preview comet's render.
//
// Graph is a header-inline class like Table, not an object file of its
// own, which is why its two methods sit in the 0x00187xxx run next to
// Table's rather than in a Graph.obj.
//
// The record does NOT own its points. pPoints is the array the
// constructor was handed -- usually a static bVector2[] in the
// compilation unit that built the Graph -- and nothing here copies or
// frees it.
//
// See docs/formats/car-graph.md.

#ifndef GRAPH_H
#define GRAPH_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

typedef struct Graph {
    const bVector2 *pPoints;   // 0
    int32_t         NumPoints; // 4
} Graph;                       // 8

// Eight bytes on the PS2: a four-byte pointer and a four-byte count, with
// nothing after them. This is the first record in the port whose size
// needs a round-up rather than the usual `+ (sizeof(void *) - 4)`: on a
// 64-bit host the pointer forces eight-byte alignment, so the int32 at the
// end is followed by four bytes of tail padding and sizeof is 16, not 12.
// The offsets are what the claim is really about, and they are exact on
// both.
#ifndef GRAPH_NO_ASSERT
typedef char graph_layout_check[
    (offsetof(Graph, pPoints)   == 0
     && offsetof(Graph, NumPoints) == sizeof(void *)
     && sizeof(Graph) == ((sizeof(void *) + 4 + sizeof(void *) - 1)
                          / sizeof(void *)) * sizeof(void *)) ? 1 : -1];
#endif

// gp-30256, 0x003215c0. The guard on the divide, and it is a strict
// `eps < fabsf(dx)` rather than a `!=` -- a knee pair closer together
// than this in x takes the midpoint arm below instead of dividing.
#define GRAPH_EPSILON 9.99999997e-07f

// 0x00187440, sixteen bytes: two stores and `move v0,a0`. It aliases the
// array, so the caller's points have to outlive the Graph.
Graph *graph_init(Graph *g, const bVector2 *points, int32_t count);

// 0x00187450. Piecewise-linear lookup with three early-outs and one
// walk.
//
// Four things are worth reading off the listing rather than assumed:
//
//   * The two tests in the walk are NOT symmetric. `p[i].x <= x` is a
//     c.le.s and `x < p[i+1].x` is a c.lt.s, so a sample landing exactly
//     on a knee belongs to the segment that STARTS there.
//   * The interpolation is `(x - p[i].x) / dx * dy`, divide before
//     multiply. Reordering it to `(x - p[i].x) * dy / dx` is a different
//     float.
//   * The degenerate arm returns the MIDPOINT, `p[i].y + dy * 0.5f`, not
//     `p[i].y`.
//   * `NumPoints < 2` reads `pPoints[0].y` without checking that there
//     is a point at all. A Graph built over an empty array reads off the
//     front of it -- a real out-of-bounds read in the shipped game, the
//     same flavour as `Table::GetValue`'s and `DriveTarget::GetAngle`'s.
//     Kept.
float graph_get_value(Graph *g, float x);

#endif
