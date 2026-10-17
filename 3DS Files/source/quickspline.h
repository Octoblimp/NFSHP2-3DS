// quickspline -- QuickSpline, out of quickspline.cpp (0x00227e98 ..
// 0x00228e4c).
//
// An Overhauser (Catmull-Rom) spline through a buffer of bVector4 control
// points. Three classes build one, all with the allocating constructor and
// all with the one basis the enum has:
//
//   * TrackPathManager::Init (0x001f50e0), one per track path, LOOP for a
//     closed path and EXTRAPOLATED for an open one, sized to the path's
//     point count and then calibrated with CalibrateLength(16);
//   * RealController (0x002247e0), EXTRAPOLATED over four points -- the
//     driving line the player's car is measured against;
//   * BeltMover (0x001f1d60), EXTRAPOLATED over twenty.
//
// The w lane is not a coordinate. CalibrateLength writes each control
// point's distance along the curve into it, so GetPoint's w comes back as
// arc length and callers read distance out of the same evaluation that
// gives them position.
//
// The parameter runs one unit per segment: control point i sits at t = i.
// pControlPoints is the buffer plus one, so the endpoint fixups can write
// cp[-1] (and, for LOOP, cp[n] and cp[n+1]) around the caller's points.
//
// Nothing in the image calls the buffer-taking constructor; it is here
// because it is in quickspline.cpp and costs five lines. DoSnapshot (retail
// 0x0023d208) is the replay's, since TASKS 72c; BeltMover's is its one
// caller.
//
// See docs/formats/quickspline.md.

#ifndef QUICKSPLINE_H
#define QUICKSPLINE_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

// The stabs spell these out: QUICKSPLINE_LOOP:0, QUICKSPLINE_LINE:1,
// QUICKSPLINE_EXTRAPOLATED:2, and QUICKSPLINE_OVERHAUSER:0 for the basis.
// LINE is never constructed in the image.
typedef int32_t QuickSplineEndPointType;
#define QUICKSPLINE_LOOP          0
#define QUICKSPLINE_LINE          1
#define QUICKSPLINE_EXTRAPOLATED  2

typedef int32_t QuickSplineBasisType;
#define QUICKSPLINE_OVERHAUSER    0

typedef struct QuickSpline {
    QuickSplineEndPointType EndPointType;   // 0
    QuickSplineBasisType    BasisType;      // 4
    float     MaxParam;                     // 8
    float     MinParam;                     // 12
    float     Length;                       // 16
    // All three are read with `lb`, so signed; none is ever above 3.
    int8_t    ControlPointsDirty;           // 20
    int8_t    BufferWasAllocated;           // 21
    int8_t    MinControlPoints;             // 22
    uint16_t  MaxControlPoints;             // 24
    uint16_t  NumControlPoints;             // 26
    bVector4 *pControlPointBuffer;          // 28
    bVector4 *pControlPoints;               // 32, the buffer plus one
    bMatrix4 *pBasisMatricies;              // 36, three of them, or NULL
} QuickSpline;                              // 40

// Forty bytes on the PS2 and the 3DS. On a 64-bit host the first pointer
// is pushed from 28 to 32 by its own alignment, not just by slack, so the
// three pointers are placed by a formula of their own.
#define QUICKSPLINE_PTR_AT(k) \
    (sizeof(void *) == 4 ? (size_t)(28 + 4 * (k)) : (size_t)(32 + 8 * (k)))
#ifndef QUICKSPLINE_NO_ASSERT
typedef char quickspline_layout_check[
    (offsetof(QuickSpline, MaxParam) == 8
     && offsetof(QuickSpline, Length) == 16
     && offsetof(QuickSpline, ControlPointsDirty) == 20
     && offsetof(QuickSpline, MinControlPoints) == 22
     && offsetof(QuickSpline, MaxControlPoints) == 24
     && offsetof(QuickSpline, NumControlPoints) == 26
     && offsetof(QuickSpline, pControlPointBuffer) == QUICKSPLINE_PTR_AT(0)
     && offsetof(QuickSpline, pControlPoints) == QUICKSPLINE_PTR_AT(1)
     && offsetof(QuickSpline, pBasisMatricies) == QUICKSPLINE_PTR_AT(2)
     && sizeof(QuickSpline) == QUICKSPLINE_PTR_AT(3)) ? 1 : -1];
#endif

// gp-27168 and gp-27164, 0x003221d0: the parameter range an EXTRAPOLATED
// spline reports, whatever its point count. The two literals are the
// float32 nearest +/-9999999, which is 9999999 exactly.
#define QUICKSPLINE_EXTRAPOLATED_MIN (-9999999.0f)
#define QUICKSPLINE_EXTRAPOLATED_MAX 9999999.0f

// gp-27160, 0x003221d8: how far below MaxParam ClampParam holds a LINE
// spline. Bits 0x33d6bf95.
#define QUICKSPLINE_LINE_EPSILON 1.00000001e-07f

// 0x00314490 and gp-16120. The three basis matrices -- position, first
// derivative, second derivative -- built on first use, and the flag that
// says they have been. Exported for the cross-check.
extern bMatrix4 QuickSplineBasisMatricies[3];
extern int32_t  QuickSplineBasisMatrixInitDone;

// 0x00227e98, file-static in the image. Idempotent.
void quickspline_init_basis_matricies(void);

// 0x00228110. Allocates MaxControlPoints + 3 vectors: the caller's points
// with one before and two after. The port allocates one more than that
// and clears the whole block; see quickspline.c for why.
QuickSpline *quickspline_init(QuickSpline *s, QuickSplineEndPointType ept,
                              QuickSplineBasisType basis, int32_t n);

// 0x002281c8. Takes a caller's buffer of n vectors, so n - 3 points.
QuickSpline *quickspline_init_with_buffer(QuickSpline *s,
                                          QuickSplineEndPointType ept,
                                          QuickSplineBasisType basis,
                                          bVector4 *buf, int32_t n);

// 0x00228200. Frees the buffer only if the constructor allocated it, then
// the object itself on flags & 1.
void quickspline_destroy(QuickSpline *s, int32_t flags);

// 0x00228268, the private Init both constructors end in.
void quickspline_setup(QuickSpline *s, QuickSplineEndPointType ept,
                       QuickSplineBasisType basis);

// 0x00228398. Marks the points dirty and sets the parameter range: [0, n)
// for LOOP, [0, n-1] for LINE, +/-9999999 for EXTRAPOLATED, and [0, 0] for
// no points at all whatever the type.
void quickspline_set_num_control_points(QuickSpline *s, int32_t n);

// 0x00228430. Writes the points around the caller's: cp[-1], cp[n] and, for
// LOOP, cp[n+1]. Run lazily by GetPoint and FindClosestParam whenever
// ControlPointsDirty is set.
void quickspline_fixup_endpoints(QuickSpline *s);

// 0x002286c8. The four points a segment starting at `start` needs, with
// any that fall off either end extrapolated linearly from the end pair.
void quickspline_generate_extrapolated_control_points(QuickSpline *s,
                                                      bVector4 *out,
                                                      int32_t start);

// 0x002285f0. out = pts * (basis * (1, t, t^2, t^3)).
void quickspline_evaluate_spline(QuickSpline *s, bVector4 *out, float t,
                                 int32_t basis, const bVector4 *pts);

// 0x00228670. LOOP wraps with bFMod; LINE clamps to
// [MinParam, MaxParam - 1e-7]; EXTRAPOLATED passes t through.
float quickspline_clamp_param(QuickSpline *s, float t);

// 0x002287d0. The point (basis 0), tangent (1) or second derivative (2) at
// t. Zero with no control points.
bVector4 *quickspline_get_point(QuickSpline *s, bVector4 *out, float t,
                                int32_t basis);

// 0x00228930. Walks forward from `start` while the next point is nearer,
// then backward from start - 1, and returns the index it stops on.
int32_t quickspline_find_closest_control_point_from(QuickSpline *s,
                                                    const bVector3 *p,
                                                    int32_t start);

// 0x00228a48. Every point, first nearest wins; -1 with none.
int32_t quickspline_find_closest_control_point(QuickSpline *s,
                                               const bVector3 *p);

// 0x00228ad0. A Newton-secant search from `guess` for the t whose tangent
// is perpendicular to p - point(t), to within `tolerance` of projected
// distance, in at most 998 steps.
float quickspline_find_closest_param(QuickSpline *s, const bVector3 *p,
                                     float guess, float tolerance);

// 0x00228cc8. Writes each control point's arc length into its w, summed
// over `samples` chords per segment, and the total into Length.
void quickspline_calibrate_length(QuickSpline *s, int32_t samples);

// Retail 0x0023d208, a "QuickSpline" section: NumControlPoints in two
// bytes; when taking or restoring, SetNumControlPoints with it; then the
// first n floats of each control point (BeltMover passes 3).
struct ReplaySnapshot;
void quickspline_do_snapshot(QuickSpline *q, struct ReplaySnapshot *s,
                             int32_t n);

#endif
