// spline -- spline.cpp's Spline, in part. The addresses are retail's.
//
// A Catmull-Rom curve through a list of bVector3 control points, the
// parameter counting control points: 0 is the first, n-1 the last. The jump
// cam's TrackCarCameraMover keeps four of them over its CameraDataItems'
// and CameraShake's arrays (the eye, the bank, the field of view and the
// shake), built with the constructor that takes the array, and reads them
// with GetPoint alone. That is what is ported: the constructor over an
// array (0x00189238), the destructor (0x00189268), GetControlPoint
// (0x001895c8), Evaluate (0x00189810) and GetPoint (0x00189948).
// Calibrate, the length and parameter searches, the allocating constructor
// and AddControlPoint wait for a caller. DoSnapshot (0x001892d8) is here
// with the replay's, since TASKS 72c, though nothing in retail calls it.
//
// The arithmetic is VU0's on all four lanes, so a control point's pad lane
// is carried through to the result's, as it is on the disc.
//
// Written up in docs/formats/camera.md, "The jump cam's mover"; checked on
// retail's image by tools/trackcarcam_check.py.

#ifndef SPLINE_H
#define SPLINE_H

#include <stdint.h>

#include "bvector.h"

// What a parameter outside 0..n-1 does. The disc's enum names are not in
// the demo's symbols; these are the port's, from what GetControlPoint
// does with each.
typedef enum SplineType {
    SPLINE_CLAMP = 0,        // held at the first or last control point
    SPLINE_LOOP = 1,         // wrapped round, n control points to a lap
    SPLINE_EXTRAPOLATE = 2   // carried on along the first or last span
} SplineType;

// 48 bytes, the demo's .mdebug record; retail's constructor writes the
// same offsets.
typedef struct Spline {
    int32_t    ControlPointBufferSize;   // 0
    int32_t    NumControlPoints;         // 4
    SplineType Type;                     // 8
    bVector3  *pControlPoints;           // 12
    bVector3  *pControlPointArray;       // 16  its own, or NULL
    int32_t    Dirty;                    // 20
    int32_t    TableSize;                // 24
    int32_t    CalLevel;                 // 28
    float      Length;                   // 32
    float      CalTableStep;             // 36
    int32_t    CalTableSize;             // 40
    float     *pCalTable;                // 44
} Spline;

// 0x00189238. Over `points`, which stay the caller's. Dirty is 1 and the
// length 0; CalLevel, CalTableStep and CalTableSize are not written.
Spline *spline_init(Spline *s, SplineType type, int32_t n, bVector3 *points,
                    int32_t tableSize);

// 0x00189268. Frees its own control point array and calibration table,
// each if it has one; with flags bit 0, the spline as well.
void spline_destroy(Spline *s, int32_t flags);

// 0x001895c8. Control point trunc(t), after the type has its say: CLAMP
// holds t in 0..n-1, LOOP takes bFMod(t, n), EXTRAPOLATE answers from the
// first or last span when t is below 0 or above n-1, into one static that
// the next call overwrites, and any other type takes t as it is.
const bVector3 *spline_get_control_point(const Spline *s, float t);

// 0x00189810. c0*P(t-1) + c1*P(t) + c2*P(t+1) + c3*P(t+2), summed in that
// order, on all four lanes.
void spline_evaluate(const Spline *s, bVector3 *o, float t, float c0,
                     float c1, float c2, float c3);

// 0x00189948. The Catmull-Rom weights for u = t - floor(t), then
// Evaluate at floor(t).
void spline_get_point(const Spline *s, bVector3 *o, float t);

// 0x001892d8, a "Spline" section: the buffer size, the count and the type,
// each control point, Dirty, TableSize, CalLevel, Length, CalTableStep,
// CalTableSize, and that many bytes of the table when there is one.
struct ReplaySnapshot;
void spline_do_snapshot(Spline *sp, struct ReplaySnapshot *s);

#endif
