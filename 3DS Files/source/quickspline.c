// quickspline -- QuickSpline, transcribed from quickspline.cpp (0x00227e98
// .. 0x00228e4c). See quickspline.h and docs/formats/quickspline.md.
//
// The VU0 code is written lane by lane. Every vsub, vmul and vadd is its
// own rounding, so `(a - b) * k + c` below is three operations per lane,
// never a fused one; the host build is -ffp-contract=off to keep it so.

#include <math.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "eefpu.h"
#include "quickspline.h"

bMatrix4 QuickSplineBasisMatricies[3];
int32_t  QuickSplineBasisMatrixInitDone;

// The allocating constructor's buffer is MaxControlPoints + 3 vectors in
// the image, never cleared. The port asks for one more and clears the lot.
//
// The extra one is for a LOOP spline, which can read one past the end:
// bFMod(t, n) comes back as exactly n for a t a hair below a multiple of n
// (-1e-6 against n = 100 is enough), GetPoint then starts its segment at
// cp[n-1] and reads cp[n+2], which is buffer[n+3]. A LINE spline of four
// or more points reads the never-written cp[n+1] the same way, because
// MaxParam - 1e-7 rounds back to MaxParam once MaxParam reaches 3.
//
// The position and tangent bases weight that point by exactly zero at the
// segment's start, so on the EE -- where every bit pattern is a finite
// float -- the stray read cannot move the answer. On the 3DS a NaN there
// would, through the zero, so the port gives the read a defined zero to
// land on. The second-derivative basis does weight it; there the image
// reads heap garbage and the port reads zero.
#define QUICKSPLINE_SLACK_POINTS 1

// Wrapping int32 arithmetic, for the index sums GetPoint and the
// extrapolation do with `addu`/`subu`. A saturated cvt.w.s can hand them
// INT_MAX or INT_MIN, and the console wraps where C would not.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

static int32_t sub32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a - (uint32_t)b);
}

// --------------------------------------------------------- the basis

static void set_row(bVector4 *r, float x, float y, float z, float w)
{
    r->x = x;
    r->y = y;
    r->z = z;
    r->w = w;
}

// `vmulx.xyzw vf1,vf1,vf3x` with vf3.x = 0.5: every lane halved. Exact for
// every entry here, but written as the multiply the image does.
static void halve_row(bVector4 *r)
{
    r->x = r->x * 0.5f;
    r->y = r->y * 0.5f;
    r->z = r->z * 0.5f;
    r->w = r->w * 0.5f;
}

static void halve(bMatrix4 *m)
{
    halve_row(&m->v0);
    halve_row(&m->v1);
    halve_row(&m->v2);
    halve_row(&m->v3);
}

void quickspline_init_basis_matricies(void)
{
    bMatrix4 *m = QuickSplineBasisMatricies;

    // gp-16120. Set after all three are built, so a spline constructed
    // later finds them ready.
    if (QuickSplineBasisMatrixInitDone != 0)
        return;

    // The Catmull-Rom matrix, times two, as rows of the four control
    // points' weights in powers of t -- and then its derivative and second
    // derivative. The image stores these scattered across fifty swc1s; the
    // rows are what they add up to.
    set_row(&m[0].v0,   0.0f,  -1.0f,   2.0f, -1.0f);
    set_row(&m[0].v1,   2.0f,   0.0f,  -5.0f,  3.0f);
    set_row(&m[0].v2,   0.0f,   1.0f,   4.0f, -3.0f);
    set_row(&m[0].v3,   0.0f,   0.0f,  -1.0f,  1.0f);
    halve(&m[0]);

    set_row(&m[1].v0,  -1.0f,   4.0f,  -3.0f,  0.0f);
    set_row(&m[1].v1,   0.0f, -10.0f,   9.0f,  0.0f);
    set_row(&m[1].v2,   1.0f,   8.0f,  -9.0f,  0.0f);
    set_row(&m[1].v3,   0.0f,  -2.0f,   3.0f,  0.0f);
    halve(&m[1]);

    set_row(&m[2].v0,   4.0f,  -6.0f,   0.0f,  0.0f);
    set_row(&m[2].v1, -10.0f,  18.0f,   0.0f,  0.0f);
    set_row(&m[2].v2,   8.0f, -18.0f,   0.0f,  0.0f);
    set_row(&m[2].v3,  -2.0f,   6.0f,   0.0f,  0.0f);
    halve(&m[2]);

    // In place, all three. bTransposeMatrix reads everything before it
    // writes.
    bTransposeMatrix(&m[0], &m[0]);
    bTransposeMatrix(&m[1], &m[1]);
    bTransposeMatrix(&m[2], &m[2]);

    QuickSplineBasisMatrixInitDone = 1;
}

// ------------------------------------------------- construction

QuickSpline *quickspline_init(QuickSpline *s, QuickSplineEndPointType ept,
                              QuickSplineBasisType basis, int32_t n)
{
    bVector4 *buf;
    int32_t   max;

    // `sh a3,24(s1)` and `andi s0,a3,0xffff`: the count is cut to sixteen
    // bits before the size is worked out from it.
    s->MaxControlPoints = (uint16_t)n;
    s->BufferWasAllocated = 1;
    max = s->MaxControlPoints;

    // bMalloc((max + 3) * 16, "..\indep\src\quickspline.cpp", 77, 16) --
    // plus the slack point above. The image follows the call with an
    // empty loop of max + 3 turns: bVector4's constructor, inlined to
    // nothing, so its block holds whatever the heap left there. The
    // port's is cleared, slack and all.
    buf = bMalloc((max + 3 + QUICKSPLINE_SLACK_POINTS)
                      * (int)sizeof(bVector4),
                  "..\\indep\\src\\quickspline.cpp", 77, 16);
    if (buf != NULL)
        memset(buf, 0, (size_t)(max + 3 + QUICKSPLINE_SLACK_POINTS)
                           * sizeof(bVector4));
    s->pControlPointBuffer = buf;

    quickspline_setup(s, ept, basis);
    return s;
}

QuickSpline *quickspline_init_with_buffer(QuickSpline *s,
                                          QuickSplineEndPointType ept,
                                          QuickSplineBasisType basis,
                                          bVector4 *buf, int32_t n)
{
    // `addiu t0,t0,-3`: the caller's buffer holds the three fixup points
    // too.
    s->BufferWasAllocated = 0;
    s->MaxControlPoints = (uint16_t)sub32(n, 3);
    s->pControlPointBuffer = buf;
    quickspline_setup(s, ept, basis);
    return s;
}

void quickspline_destroy(QuickSpline *s, int32_t flags)
{
    // __builtin_vec_delete (0x00114ab0) is `j bFree`, like
    // __builtin_delete beside it.
    if (s->BufferWasAllocated != 0 && s->pControlPointBuffer != NULL)
        bFree(s->pControlPointBuffer);
    if (flags & 1)
        bFree(s);
}

void quickspline_setup(QuickSpline *s, QuickSplineEndPointType ept,
                       QuickSplineBasisType basis)
{
    s->EndPointType = ept;
    s->BasisType = basis;

    // `bne a2,zero`: any basis but OVERHAUSER gets no matrices at all, and
    // would fault on its first evaluation.
    s->pBasisMatricies = NULL;
    if (basis == QUICKSPLINE_OVERHAUSER)
        s->pBasisMatricies = QuickSplineBasisMatricies;

    s->pControlPoints = s->pControlPointBuffer + 1;

    // Re-read from the record, not taken from the argument.
    s->MinControlPoints = 2;
    if (s->EndPointType == QUICKSPLINE_LOOP)
        s->MinControlPoints = 3;

    s->Length = 0.0f;
    quickspline_set_num_control_points(s, 0);

    // A tail call: the matrices are built by the first spline anyone
    // constructs, not at boot.
    quickspline_init_basis_matricies();
}

void quickspline_set_num_control_points(QuickSpline *s, int32_t n)
{
    s->ControlPointsDirty = 1;
    s->NumControlPoints = (uint16_t)n;

    // `andi v1,a1,0xffff`: the stored count, so 65536 is no points.
    if (s->NumControlPoints == 0) {
        s->MinParam = 0.0f;
        s->MaxParam = 0.0f;
        return;
    }

    switch (s->EndPointType) {
    case QUICKSPLINE_LOOP:
        s->MinParam = 0.0f;
        s->MaxParam = (float)s->NumControlPoints;
        break;
    case QUICKSPLINE_LINE:
        s->MinParam = 0.0f;
        s->MaxParam = (float)(s->NumControlPoints - 1);
        break;
    case QUICKSPLINE_EXTRAPOLATED:
        s->MinParam = QUICKSPLINE_EXTRAPOLATED_MIN;
        s->MaxParam = QUICKSPLINE_EXTRAPOLATED_MAX;
        break;
    default:
        // Any other type leaves the range as it was.
        break;
    }
}

// ------------------------------------------------------ the endpoints

// o = (a - b) * k + base, lane by lane: vsub, vmulx, vadd. Built in a
// temporary because o is often one of the inputs' neighbours and, for a
// one-point spline, one of the inputs.
static void extrapolate(bVector4 *o, const bVector4 *a, const bVector4 *b,
                        float k, const bVector4 *base)
{
    bVector4 r;

    r.x = a->x - b->x;
    r.y = a->y - b->y;
    r.z = a->z - b->z;
    r.w = a->w - b->w;
    r.x = r.x * k;
    r.y = r.y * k;
    r.z = r.z * k;
    r.w = r.w * k;
    r.x = r.x + base->x;
    r.y = r.y + base->y;
    r.z = r.z + base->z;
    r.w = r.w + base->w;
    *o = r;
}

void quickspline_fixup_endpoints(QuickSpline *s)
{
    int32_t   n = s->NumControlPoints;
    bVector4 *cp = s->pControlPoints;

    if (n == 0)
        return;

    // Every copy is a whole quadword, and each is a load then a store in
    // this order -- which matters for n = 1, where cp[n] is cp[1] and the
    // third copy reads what the second just wrote.
    switch (s->EndPointType) {
    case QUICKSPLINE_LOOP:
        cp[-1] = cp[n - 1];
        cp[n] = cp[0];
        cp[n + 1] = cp[1];
        // c.eq.s, so -0.0 counts as no length too.
        if (s->Length == 0.0f)
            return;
        // Around the loop, the distance carries on: the point before the
        // first is a lap back, the two after the last a lap on.
        cp[-1].w = cp[n - 1].w - s->Length;
        cp[n].w = s->Length + cp[0].w;
        cp[n + 1].w = s->Length + cp[1].w;
        return;

    case QUICKSPLINE_LINE:
        cp[-1] = cp[0];
        cp[n] = cp[n - 1];
        if (s->Length == 0.0f)
            return;
        // Mirrored distances -- and not symmetrically. The front reflects
        // cp[1] about zero (`lwc1 $f0,28(a1)` is cp[1].w, not cp[0].w);
        // the back reflects cp[n-1] about Length.
        cp[-1].w = -cp[1].w;
        cp[n].w = (s->Length + s->Length) - cp[n - 1].w;
        return;

    case QUICKSPLINE_EXTRAPOLATED:
        // One segment's step beyond each end, along the end segment. The
        // multiplies by -1 and 1 are there in the image, as vmulx.
        extrapolate(&cp[-1], &cp[1], &cp[0], -1.0f, &cp[0]);
        extrapolate(&cp[n], &cp[n - 1], &cp[n - 2], 1.0f, &cp[n - 1]);
        if (s->Length == 0.0f)
            return;
        cp[-1].w = -cp[1].w;
        cp[n].w = (s->Length + s->Length) - cp[n - 1].w;
        return;

    default:
        return;
    }
}

void quickspline_generate_extrapolated_control_points(QuickSpline *s,
                                                      bVector4 *out,
                                                      int32_t start)
{
    int32_t   n = s->NumControlPoints;
    bVector4 *cp = s->pControlPoints;
    int32_t   i;

    for (i = 0; i < 4; i++) {
        int32_t k = add32(start, i);

        // cp[-1] and cp[n] exist -- FixupEndpoints wrote them -- so only
        // what lies beyond those is made up, as a straight line through
        // the end pair.
        if (k < -1)
            extrapolate(&out[i], &cp[0], &cp[1], (float)sub32(0, k),
                        &cp[0]);
        else if (n < k)
            extrapolate(&out[i], &cp[n - 1], &cp[n - 2],
                        (float)add32(sub32(k, n), 1), &cp[n - 1]);
        else
            out[i] = cp[k];
    }
}

// ------------------------------------------------------ evaluation

void quickspline_evaluate_spline(QuickSpline *s, bVector4 *out, float t,
                                 int32_t basis, const bVector4 *pts)
{
    bVector4 v, w;
    bMatrix4 m;
    float    t2 = t * t;

    // t^3 is t * t^2, not t^2 * t: `mul.s $f1,$f12,$f2`.
    v.x = 1.0f;
    v.y = t;
    v.z = t2;
    v.w = t * t2;

    // Two bMulMatrix calls: the powers through the basis, giving the four
    // points' weights, then the weights through the points as a matrix.
    bMulMatrixVec4(&w, &s->pBasisMatricies[basis], &v);
    memcpy(&m, pts, sizeof m);
    bMulMatrixVec4(out, &m, &w);
}

float quickspline_clamp_param(QuickSpline *s, float t)
{
    if (s->EndPointType == QUICKSPLINE_LOOP)
        return bFMod(t, s->MaxParam);

    if (s->EndPointType == QUICKSPLINE_LINE) {
        float hi = s->MaxParam - QUICKSPLINE_LINE_EPSILON;

        // `max.s $f1,$f12,$f1` then `min.s $f12,$f0,$f1`, written as the
        // comparisons so a zero keeps its sign as the EE's does.
        t = (t < s->MinParam) ? s->MinParam : t;
        return (t < hi) ? t : hi;
    }

    return t;
}

bVector4 *quickspline_get_point(QuickSpline *s, bVector4 *out, float t,
                                int32_t basis)
{
    float   whole;
    int32_t seg;

    if (s->ControlPointsDirty != 0) {
        quickspline_fixup_endpoints(s);
        s->ControlPointsDirty = 0;
    }

    if (s->NumControlPoints == 0) {
        out->x = 0.0f;
        out->y = 0.0f;
        out->z = 0.0f;
        out->w = 0.0f;
        return out;
    }

    // Floor by truncate-and-correct, then the fraction. cvt.w.s saturates,
    // so an EXTRAPOLATED t past 2^31 lands on INT_MAX and the index sums
    // below wrap.
    t = quickspline_clamp_param(s, t);
    whole = (float)ee_trunc_w(t);
    if (t < whole)
        whole = whole - 1.0f;
    t = t - whole;
    seg = ee_trunc_w(whole);

    // Off either end of an EXTRAPOLATED spline -- and on its last
    // segment, which needs cp[n+1] and FixupEndpoints did not write one --
    // the four points are made up.
    if (s->EndPointType == QUICKSPLINE_EXTRAPOLATED
        && (seg < 0 || seg >= s->NumControlPoints - 1)) {
        bVector4 pts[4];

        quickspline_generate_extrapolated_control_points(s, pts,
                                                         sub32(seg, 1));
        quickspline_evaluate_spline(s, out, t, basis, pts);
        return out;
    }

    quickspline_evaluate_spline(s, out, t, basis,
                                &s->pControlPoints[seg - 1]);
    return out;
}

// ------------------------------------------------------- the searches

// The distance the VU0 works out: the xyz of p minus the point, squared
// lane by lane, summed x + y then + z, and sqrt.s. The point's w is
// ignored and so is p's pad.
static float dist3(const bVector3 *p, const bVector4 *q)
{
    float dx = p->x - q->x;
    float dy = p->y - q->y;
    float dz = p->z - q->z;

    return sqrtf(dx * dx + dy * dy + dz * dz);
}

int32_t quickspline_find_closest_control_point_from(QuickSpline *s,
                                                    const bVector3 *p,
                                                    int32_t start)
{
    bVector4 *cp = s->pControlPoints;
    int32_t   n = s->NumControlPoints;
    int32_t   best = start;
    float     bestd = dist3(p, &cp[start]);
    int32_t   i;

    // Forward while each point is strictly nearer than the best so far
    // (`c.le.s best,d` stops on a tie)...
    for (i = start + 1; i < n; i++) {
        float d = dist3(p, &cp[i]);

        if (bestd <= d)
            break;
        best = i;
        bestd = d;
    }

    // ...then backward from start - 1, whatever the forward walk did,
    // against the best distance it left behind.
    for (i = start - 1; i >= 0; i--) {
        float d = dist3(p, &cp[i]);

        if (bestd <= d)
            break;
        best = i;
        bestd = d;
    }

    return best;
}

int32_t quickspline_find_closest_control_point(QuickSpline *s,
                                               const bVector3 *p)
{
    int32_t n = s->NumControlPoints;
    int32_t best = -1;
    float   bestd = 0.0f;
    int32_t i;

    // `c.lt.s d,best`: the first of equally near points wins.
    for (i = 0; i < n; i++) {
        float d = dist3(p, &s->pControlPoints[i]);

        if (best < 0 || d < bestd) {
            bestd = d;
            best = i;
        }
    }

    return best;
}

float quickspline_find_closest_param(QuickSpline *s, const bVector3 *p,
                                     float guess, float tolerance)
{
    float    t = guess;
    float    prevErr = 0.0f;
    float    prevStep = 0.0f;
    float    limit = 1.0f;
    int32_t  left = 998;
    bVector4 pos, tan;

    if (s->ControlPointsDirty != 0) {
        quickspline_fixup_endpoints(s);
        s->ControlPointsDirty = 0;
    }

    if (s->NumControlPoints == 0)
        return 0.0f;

    do {
        float speed, err, slope, step, next;

        quickspline_get_point(s, &pos, t, 0);
        quickspline_get_point(s, &tan, t, 1);

        speed = sqrtf(tan.x * tan.x + tan.y * tan.y + tan.z * tan.z);
        if (speed == 0.0f)
            return t;

        // How far p lies along the tangent from the curve's point: the
        // error the search drives to zero.
        err = ((p->x - pos.x) * tan.x + (p->y - pos.y) * tan.y
               + (p->z - pos.z) * tan.z) / speed;
        if (fabsf(err) < tolerance)
            return t;

        // The first step divides by the speed; after that the slope is
        // the secant through the last two errors.
        if (prevStep == 0.0f) {
            slope = speed;
        } else {
            slope = (prevErr - err) / prevStep;
            if (slope == 0.0f)
                return t;
        }

        // `max.s` against -limit then `min.s` against limit.
        step = err / slope;
        step = (step < -limit) ? -limit : step;
        step = (step < limit) ? step : limit;

        next = quickspline_clamp_param(s, t + step);

        // An overshoot -- this step against the last one's sign -- halves
        // how far the next may go.
        if (step * prevStep < 0.0f)
            limit = limit * 0.5f;

        t = next;
        prevStep = step;
        prevErr = err;
    } while (--left != 0);

    return t;
}

void quickspline_calibrate_length(QuickSpline *s, int32_t samples)
{
    float    total = 0.0f;
    int32_t  i, j;
    bVector4 prev, cur;

    for (i = 0; i < s->NumControlPoints; i++) {
        float fi = (float)i;

        // The distance so far goes into this point's w before its segment
        // is measured, and the dirty flag goes up every time -- so every
        // segment's first GetPoint reruns FixupEndpoints, against the w
        // values written so far and the Length from before this call.
        s->pControlPoints[i].w = total;
        s->ControlPointsDirty = 1;

        // A LINE spline's last point starts no segment.
        if (!(fi < s->MaxParam))
            continue;

        quickspline_get_point(s, &cur, fi, 0);
        prev = cur;
        if (samples < 1)
            continue;

        for (j = 1; j <= samples; j++) {
            float dx, dy, dz;

            quickspline_get_point(s, &cur, fi + (float)j / (float)samples,
                                  0);
            dx = cur.x - prev.x;
            dy = cur.y - prev.y;
            dz = cur.z - prev.z;
            total = total + sqrtf(dx * dx + dy * dy + dz * dz);
            prev = cur;
        }
    }

    s->Length = total;
    s->ControlPointsDirty = 1;
}
