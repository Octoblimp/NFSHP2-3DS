// Host harness for bware's vector, matrix and quaternion library.
//
// Builds "3DS Files/source/bvector.c", "bmatrix.c" and "bquat.c" for the
// host (plus bmath.c, which the fixed-point normalisers call into) and
// sweeps every entry point, printing one line per call:
//
//     scenario <name>
//     <op> <inputs> -> <outputs>
//
// tools/bvector_check.py prints the same from a Python model written off the
// disassembly at 0x00240198, 0x002411f0 and 0x002424f8 rather than off this
// code, and diffs the two. bMath.obj has its own pair.
//
// Floats print as %.9g -- more significant digits than a float32 holds, so
// the text pins the bits exactly. Every input float is an integer over 256,
// so both sides start from the same bits without having to agree on how a
// decimal literal rounds.
//
// Four things are deliberately NOT swept, for the same reason bmath_test.c
// gives: the EE FPU has no infinities and no NaNs, so a test that provoked
// one would be testing the host.
//
//   * bNormalize2To / bNormalize3To with len == 0.
//   * bNormalize on the zero quaternion.
//   * Singular matrices through bInvertMatrix.
//   * bSlerp on quaternions that are not unit length. That one is not just
//     a float nicety: |cos| > 1 sends bASin off the end of bASinTable. See
//     the note in bquat.c.
//
// Usage: bvector_test [scenario]...      (no argument runs them all)

#include <stdio.h>
#include <string.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bquat.h"
#include "bvector.h"

// ------------------------------------------------------------ input decks

// Floats are NUMS[k] / 256: exact dyadic rationals spanning four decades in
// both signs, with a zero in the deck so the degenerate paths get hit by the
// sweep rather than only by the hand-written cases.
static const int32_t NUMS[] = {
    0, 1, -1, 2, 3, -5, 7, -11, 16, 33, -64, 128,
    255, -256, 1000, -1023, 4096, -8192, 65536, -100000, 123456, -987654,
    31, 17,
};
#define NNUM ((int)(sizeof NUMS / sizeof NUMS[0]))

static float fv(int k)
{
    return (float)NUMS[k % NNUM] / 256.0f;
}

// Q16 integers, including both ends of the range so the wrapping adds and
// the pre-scale's sixteen-bit test are exercised.
static const int32_t FIXN[] = {
    0, 1, -1, 2, -3, 100, -1000, 0x8000, -0x8000, 0x10000, -0x10000,
    0x1234, -0x4321, 0x100000, -0x100000, 0x7fffff, -0x7fffff,
    0x1000000, -0x1000000, 0x20000000, -0x20000000, 0x7fffffff,
    -0x7fffffff, 12345678, -87654321, 65536000, 3, -7,
};
#define NFIX ((int)(sizeof FIXN / sizeof FIXN[0]))

static int32_t iv(int k)
{
    return FIXN[k % NFIX];
}

static bVector2 v2(int k)
{
    bVector2 v;

    v.x = fv(k);
    v.y = fv(k + 1);
    return v;
}

static bVector3 v3(int k)
{
    bVector3 v;

    v.x = fv(k);
    v.y = fv(k + 1);
    v.z = fv(k + 2);
    v.pad = 0.0f;
    return v;
}

// Components from far apart in the deck. Adjacent entries are close
// enough in magnitude that the two ways of grouping x*x + y*y + z*z always
// round to the same float32; these are not.
static bVector3 v3m(int k)
{
    bVector3 v;

    v.x = fv(k);
    v.y = fv(k + 10);
    v.z = fv(k + 14);
    v.pad = 0.0f;
    return v;
}

static bVector4 v4(int k)
{
    bVector4 v;

    v.x = fv(k);
    v.y = fv(k + 1);
    v.z = fv(k + 2);
    v.w = fv(k + 3);
    return v;
}

static bFixVector2 f2(int k)
{
    bFixVector2 v;

    v.x = iv(k);
    v.y = iv(k + 1);
    return v;
}

static bFixVector3 f3(int k)
{
    bFixVector3 v;

    v.x = iv(k);
    v.y = iv(k + 1);
    v.z = iv(k + 2);
    return v;
}

static bMatrix4 mgen(int k)
{
    bMatrix4 m;

    m.v0 = v4(k);
    m.v1 = v4(k + 4);
    m.v2 = v4(k + 8);
    m.v3 = v4(k + 12);
    return m;
}

// A unit quaternion. The +1 on w keeps the deck's single zero from lining up
// into an all-zero quaternion.
static bQuaternion uq(int k)
{
    bQuaternion q, n;

    q.x = fv(k);
    q.y = fv(k + 1);
    q.z = fv(k + 2);
    q.w = fv(k + 3) + 1.0f;
    bNormalize(&n, &q);
    return n;
}

// Rotation, then a per-row scale, then a translation. The scales are offset
// by 2 because no entry of the deck is -2, so the determinant cannot be
// zero.
static bMatrix4 affine(int k)
{
    bQuaternion q = uq(k);
    bMatrix4 m;
    float sx = fv(k + 6) + 2.0f;
    float sy = fv(k + 7) + 2.0f;
    float sz = fv(k + 8) + 2.0f;

    bQuaternionToMatrix(&m, &q);
    m.v0.x *= sx; m.v0.y *= sx; m.v0.z *= sx;
    m.v1.x *= sy; m.v1.y *= sy; m.v1.z *= sy;
    m.v2.x *= sz; m.v2.y *= sz; m.v2.z *= sz;
    m.v3.x = fv(k + 9);
    m.v3.y = fv(k + 10);
    m.v3.z = fv(k + 11);
    return m;
}

// ---------------------------------------------------------------- printing

static void p2(const bVector2 *v)
{
    printf(" (%.9g %.9g)", v->x, v->y);
}

static void p3(const bVector3 *v)
{
    printf(" (%.9g %.9g %.9g)", v->x, v->y, v->z);
}

static void p4(const bVector4 *v)
{
    printf(" (%.9g %.9g %.9g %.9g)", v->x, v->y, v->z, v->w);
}

static void pq(const bQuaternion *q)
{
    printf(" (%.9g %.9g %.9g %.9g)", q->x, q->y, q->z, q->w);
}

static void pm(const bMatrix4 *m)
{
    p4(&m->v0);
    p4(&m->v1);
    p4(&m->v2);
    p4(&m->v3);
}

static void pf2(const bFixVector2 *v)
{
    printf(" (%d %d)", v->x, v->y);
}

static void pf3(const bFixVector3 *v)
{
    printf(" (%d %d %d)", v->x, v->y, v->z);
}

// -------------------------------------------------------------------- Q16

static void s_fixmul(void)
{
    int i, j;

    for (i = 0; i < NFIX; i++) {
        for (j = 0; j < NFIX; j++) {
            printf("fixmul %11d %11d -> %11d\n",
                   FIXN[i], FIXN[j], bFixMul(FIXN[i], FIXN[j]));
        }
    }
}

// ------------------------------------------------------------------ float

static void s_normalize2(void)
{
    bVector2 z = { 0.0f, 0.0f };
    bVector2 o;
    int k;

    bNormalize2(&o, &z);
    printf("normalize2");
    p2(&z);
    printf(" ->");
    p2(&o);
    printf("\n");

    for (k = 0; k < 3 * NNUM; k++) {
        bVector2 v = v2(k);

        bNormalize2(&o, &v);
        printf("normalize2");
        p2(&v);
        printf(" ->");
        p2(&o);
        printf("\n");
    }
}

static void s_normalize2to(void)
{
    static const int lens[] = { 1, 2, -3, 17, -1024 };
    bVector2 z = { 0.0f, 0.0f };
    bVector2 o;
    int k, i;

    for (i = 0; i < (int)(sizeof lens / sizeof lens[0]); i++) {
        float len = (float)lens[i] / 4.0f;

        bNormalize2To(&o, &z, len);
        printf("normalize2to");
        p2(&z);
        printf(" %.9g ->", len);
        p2(&o);
        printf("\n");

        for (k = 0; k < 2 * NNUM; k++) {
            bVector2 v = v2(k);

            bNormalize2To(&o, &v, len);
            printf("normalize2to");
            p2(&v);
            printf(" %.9g ->", len);
            p2(&o);
            printf("\n");
        }
    }
}

static void s_normalize3to(void)
{
    static const int lens[] = { 1, 2, -3, 17, -1024 };
    bVector3 z = { 0.0f, 0.0f, 0.0f, 0.0f };
    bVector3 o;
    int k, i;

    for (i = 0; i < (int)(sizeof lens / sizeof lens[0]); i++) {
        float len = (float)lens[i] / 4.0f;

        bNormalize3To(&o, &z, len);
        printf("normalize3to");
        p3(&z);
        printf(" %.9g ->", len);
        p3(&o);
        printf("\n");

        for (k = 0; k < 2 * NNUM; k++) {
            bVector3 v = v3(k);

            bNormalize3To(&o, &v, len);
            printf("normalize3to");
            p3(&v);
            printf(" %.9g ->", len);
            p3(&o);
            printf("\n");
        }

        for (k = 0; k < 2 * NNUM; k++) {
            bVector3 v = v3m(k);

            bNormalize3To(&o, &v, len);
            printf("normalize3tomix");
            p3(&v);
            printf(" %.9g ->", len);
            p3(&o);
            printf("\n");
        }
    }
}

static void s_scaleadd2(void)
{
    int k;

    for (k = 0; k < 2 * NNUM; k++) {
        bVector2 a = v2(k);
        bVector2 b = v2(k + 5);
        float s = fv(k + 11);
        bVector2 o;

        bScaleAdd2(&o, &a, &b, s);
        printf("scaleadd2");
        p2(&a);
        p2(&b);
        printf(" %.9g ->", s);
        p2(&o);
        printf("\n");
    }
}

static void s_equal(void)
{
    static const int eps[] = { 0, 1, 4, 256, 65536 };
    int k, i;

    for (i = 0; i < (int)(sizeof eps / sizeof eps[0]); i++) {
        float e = (float)eps[i] / 256.0f;

        for (k = 0; k < NNUM; k++) {
            bVector2 a = v2(k);
            bVector2 b = v2(k + 1);
            bVector3 c = v3(k);
            bVector3 d = v3(k + 1);

            printf("equal2");
            p2(&a);
            p2(&b);
            printf(" %.9g -> %d\n", e, bEqual2(&a, &b, e));
            printf("equal2");
            p2(&a);
            p2(&a);
            printf(" %.9g -> %d\n", e, bEqual2(&a, &a, e));
            printf("equal3");
            p3(&c);
            p3(&d);
            printf(" %.9g -> %d\n", e, bEqual3(&c, &d, e));
            printf("equal3");
            p3(&c);
            p3(&c);
            printf(" %.9g -> %d\n", e, bEqual3(&c, &c, e));
        }
    }
}

// --------------------------------------------------------- bounding boxes

static void s_bbox2(void)
{
    bVector2 mn, mx;
    int k;

    bInitializeBoundingBox2(&mn, &mx);
    printf("init2 ->");
    p2(&mn);
    p2(&mx);
    printf("\n");

    for (k = 0; k < NNUM; k++) {
        bVector2 p = v2(k);

        bExpandBoundingBox2(&mn, &mx, &p);
        printf("expand2");
        p2(&p);
        printf(" ->");
        p2(&mn);
        p2(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector2 p = v2(k + 3);
        float r = fv(k + 7);

        bExpandBoundingBox2R(&mn, &mx, &p, r);
        printf("expand2r");
        p2(&p);
        printf(" %.9g ->", r);
        p2(&mn);
        p2(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector2 lo = v2(k + 2);
        bVector2 hi = v2(k + 9);

        bExpandBoundingBox2Box(&mn, &mx, &lo, &hi);
        printf("expand2box");
        p2(&lo);
        p2(&hi);
        printf(" ->");
        p2(&mn);
        p2(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector2 a = v2(k);
        bVector2 b = v2(k + 4);
        bVector2 lo, hi, ilo, ihi;
        float e = fv(k + 6);

        bInitializeBoundingBox2At(&lo, &hi, &a);
        printf("init2at");
        p2(&a);
        printf(" ->");
        p2(&lo);
        p2(&hi);
        printf("\n");

        bExpandBoundingBox2(&lo, &hi, &b);
        ilo = v2(k + 1);
        ihi = v2(k + 5);

        printf("inside2");
        p2(&lo);
        p2(&hi);
        p2(&ilo);
        printf(" %.9g -> %d\n", e, bBoundingBoxIsInside2(&lo, &hi, &ilo, e));
        printf("contains2");
        p2(&lo);
        p2(&hi);
        p2(&ilo);
        p2(&ihi);
        printf(" -> %d\n", bBoundingBoxContains2(&lo, &hi, &ilo, &ihi));
        printf("contains2self");
        p2(&lo);
        p2(&hi);
        printf(" -> %d\n", bBoundingBoxContains2(&lo, &hi, &lo, &hi));
        printf("overlap2");
        p2(&lo);
        p2(&hi);
        p2(&ilo);
        p2(&ihi);
        printf(" -> %d\n", bBoundingBoxOverlapping2(&lo, &hi, &ilo, &ihi));
        printf("overlap2self");
        p2(&lo);
        p2(&hi);
        printf(" -> %d\n", bBoundingBoxOverlapping2(&lo, &hi, &lo, &hi));
    }
}

// Boxes that meet exactly on one axis, one axis at a time, so each of the
// four comparisons in bBoundingBoxOverlapping2 is exercised at equality --
// and points sitting exactly on bBoundingBoxIsInside2's grown edge. Without
// these the two documented quirks of this file (contains is inclusive,
// overlapping is not) are never actually tested.
static void s_bbox2edge(void)
{
    bVector2 alo = { 0.0f, 0.0f }, ahi = { 2.0f, 1.0f };
    bVector2 xlo = { 2.0f, 0.0f }, xhi = { 3.0f, 1.0f };
    bVector2 ylo = { 0.0f, 1.0f }, yhi = { 2.0f, 2.0f };
    bVector2 hix = { 3.0f, 1.0f }, lox = { -1.0f, 0.0f };

    printf("overlap2touchx -> %d\n",
           bBoundingBoxOverlapping2(&alo, &ahi, &xlo, &xhi));
    printf("overlap2touchxrev -> %d\n",
           bBoundingBoxOverlapping2(&xlo, &xhi, &alo, &ahi));
    printf("overlap2touchy -> %d\n",
           bBoundingBoxOverlapping2(&alo, &ahi, &ylo, &yhi));
    printf("overlap2touchyrev -> %d\n",
           bBoundingBoxOverlapping2(&ylo, &yhi, &alo, &ahi));
    printf("contains2edge -> %d\n",
           bBoundingBoxContains2(&alo, &ahi, &alo, &ahi));
    printf("contains2past -> %d\n",
           bBoundingBoxContains2(&alo, &ahi, &alo, &xhi));
    printf("inside2edge -> %d\n",
           bBoundingBoxIsInside2(&alo, &ahi, &hix, 1.0f));
    printf("inside2past -> %d\n",
           bBoundingBoxIsInside2(&alo, &ahi, &hix, 0.9375f));
    printf("inside2low -> %d\n",
           bBoundingBoxIsInside2(&alo, &ahi, &lox, 1.0f));
    printf("inside2lowpast -> %d\n",
           bBoundingBoxIsInside2(&alo, &ahi, &lox, 0.9375f));
}

static void s_bbox3edge(void)
{
    bVector3 alo = { 0.0f, 0.0f, 0.0f, 0.0f };
    bVector3 ahi = { 2.0f, 1.0f, 1.0f, 0.0f };
    bVector3 xlo = { 2.0f, 0.0f, 0.0f, 0.0f };
    bVector3 xhi = { 3.0f, 1.0f, 1.0f, 0.0f };
    bVector3 ylo = { 0.0f, 1.0f, 0.0f, 0.0f };
    bVector3 yhi = { 2.0f, 2.0f, 1.0f, 0.0f };
    bVector3 zlo = { 0.0f, 0.0f, 1.0f, 0.0f };
    bVector3 zhi = { 2.0f, 1.0f, 2.0f, 0.0f };
    bVector3 hix = { 3.0f, 1.0f, 1.0f, 0.0f };
    bVector3 lox = { -1.0f, 0.0f, 0.0f, 0.0f };

    printf("overlap3touchx -> %d\n",
           bBoundingBoxOverlapping3(&alo, &ahi, &xlo, &xhi));
    printf("overlap3touchxrev -> %d\n",
           bBoundingBoxOverlapping3(&xlo, &xhi, &alo, &ahi));
    printf("overlap3touchy -> %d\n",
           bBoundingBoxOverlapping3(&alo, &ahi, &ylo, &yhi));
    printf("overlap3touchyrev -> %d\n",
           bBoundingBoxOverlapping3(&ylo, &yhi, &alo, &ahi));
    printf("overlap3touchz -> %d\n",
           bBoundingBoxOverlapping3(&alo, &ahi, &zlo, &zhi));
    printf("overlap3touchzrev -> %d\n",
           bBoundingBoxOverlapping3(&zlo, &zhi, &alo, &ahi));
    printf("contains3edge -> %d\n",
           bBoundingBoxContains3(&alo, &ahi, &alo, &ahi));
    printf("contains3past -> %d\n",
           bBoundingBoxContains3(&alo, &ahi, &alo, &xhi));
    printf("inside3edge -> %d\n",
           bBoundingBoxIsInside3(&alo, &ahi, &hix, 1.0f));
    printf("inside3past -> %d\n",
           bBoundingBoxIsInside3(&alo, &ahi, &hix, 0.9375f));
    printf("inside3low -> %d\n",
           bBoundingBoxIsInside3(&alo, &ahi, &lox, 1.0f));
    printf("inside3lowpast -> %d\n",
           bBoundingBoxIsInside3(&alo, &ahi, &lox, 0.9375f));
}

static void s_bbox3(void)
{
    bVector3 mn, mx;
    int k;

    bInitializeBoundingBox3(&mn, &mx);
    printf("init3 ->");
    p3(&mn);
    p3(&mx);
    printf("\n");

    for (k = 0; k < NNUM; k++) {
        bVector3 p = v3(k);

        bExpandBoundingBox3(&mn, &mx, &p);
        printf("expand3");
        p3(&p);
        printf(" ->");
        p3(&mn);
        p3(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector3 p = v3(k + 3);
        float r = fv(k + 7);

        bExpandBoundingBox3R(&mn, &mx, &p, r);
        printf("expand3r");
        p3(&p);
        printf(" %.9g ->", r);
        p3(&mn);
        p3(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector3 lo = v3(k + 2);
        bVector3 hi = v3(k + 9);

        bExpandBoundingBox3Box(&mn, &mx, &lo, &hi);
        printf("expand3box");
        p3(&lo);
        p3(&hi);
        printf(" ->");
        p3(&mn);
        p3(&mx);
        printf("\n");
    }

    for (k = 0; k < NNUM; k++) {
        bVector3 a = v3(k);
        bVector3 b = v3(k + 4);
        bVector3 lo, hi, ilo, ihi;
        float e = fv(k + 6);

        bInitializeBoundingBox3At(&lo, &hi, &a);
        printf("init3at");
        p3(&a);
        printf(" ->");
        p3(&lo);
        p3(&hi);
        printf("\n");

        bExpandBoundingBox3(&lo, &hi, &b);
        ilo = v3(k + 1);
        ihi = v3(k + 5);

        printf("inside3");
        p3(&lo);
        p3(&hi);
        p3(&ilo);
        printf(" %.9g -> %d\n", e, bBoundingBoxIsInside3(&lo, &hi, &ilo, e));
        printf("contains3");
        p3(&lo);
        p3(&hi);
        p3(&ilo);
        p3(&ihi);
        printf(" -> %d\n", bBoundingBoxContains3(&lo, &hi, &ilo, &ihi));
        printf("contains3self");
        p3(&lo);
        p3(&hi);
        printf(" -> %d\n", bBoundingBoxContains3(&lo, &hi, &lo, &hi));
        printf("overlap3");
        p3(&lo);
        p3(&hi);
        p3(&ilo);
        p3(&ihi);
        printf(" -> %d\n", bBoundingBoxOverlapping3(&lo, &hi, &ilo, &ihi));
        printf("overlap3self");
        p3(&lo);
        p3(&hi);
        printf(" -> %d\n", bBoundingBoxOverlapping3(&lo, &hi, &lo, &hi));
    }
}

// ------------------------------------------------------------ fixed point

static void s_lengthfix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector3 b = f3(k);

        printf("lengthfix2");
        pf2(&a);
        printf(" -> %d\n", bLengthFix2(&a));
        printf("lengthfix3");
        pf3(&b);
        printf(" -> %d\n", bLengthFix3(&b));
    }
}

static void s_distfix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector2 b = f2(k + 5);
        bFixVector3 c = f3(k);
        bFixVector3 d = f3(k + 7);

        printf("distfix2");
        pf2(&a);
        pf2(&b);
        printf(" -> %d\n", bDistBetweenFix2(&a, &b));
        printf("distfix3");
        pf3(&c);
        pf3(&d);
        printf(" -> %d\n", bDistBetweenFix3(&c, &d));
    }
}

static void s_scalefix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector3 b = f3(k);
        int32_t s = iv(k + 11);
        bFixVector2 o2;
        bFixVector3 o3;

        bScaleFix2(&o2, &a, s);
        printf("scalefix2");
        pf2(&a);
        printf(" %d ->", s);
        pf2(&o2);
        printf("\n");

        bScaleFix3(&o3, &b, s);
        printf("scalefix3");
        pf3(&b);
        printf(" %d ->", s);
        pf3(&o3);
        printf("\n");
    }
}

static void s_scaleaddfix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector2 b = f2(k + 3);
        bFixVector3 c = f3(k);
        bFixVector3 d = f3(k + 4);
        int32_t s = iv(k + 13);
        bFixVector2 o2;
        bFixVector3 o3;

        bScaleAddFix2(&o2, &a, &b, s);
        printf("scaleaddfix2");
        pf2(&a);
        pf2(&b);
        printf(" %d ->", s);
        pf2(&o2);
        printf("\n");

        bScaleAddFix3(&o3, &c, &d, s);
        printf("scaleaddfix3");
        pf3(&c);
        pf3(&d);
        printf(" %d ->", s);
        pf3(&o3);
        printf("\n");
    }
}

static void s_dotfix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector2 b = f2(k + 6);
        bFixVector3 c = f3(k);
        bFixVector3 d = f3(k + 9);

        printf("dotfix2");
        pf2(&a);
        pf2(&b);
        printf(" -> %d\n", bDotFix2(&a, &b));
        printf("dotfix3");
        pf3(&c);
        pf3(&d);
        printf(" -> %d\n", bDotFix3(&c, &d));
    }
}

static void s_crossfix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector3 a = f3(k);
        bFixVector3 b = f3(k + 5);
        bFixVector3 o;

        bCrossFix3(&o, &a, &b);
        printf("crossfix3");
        pf3(&a);
        pf3(&b);
        printf(" ->");
        pf3(&o);
        printf("\n");
    }
}

static void s_normalizefix(void)
{
    int k;

    for (k = 0; k < 4 * NFIX; k++) {
        bFixVector2 a = f2(k);
        bFixVector3 b = f3(k);
        bFixVector2 o2;
        bFixVector3 o3;

        bNormalizeFix2(&o2, &a);
        printf("normalizefix2");
        pf2(&a);
        printf(" ->");
        pf2(&o2);
        printf("\n");

        bNormalizeFix3(&o3, &b);
        printf("normalizefix3");
        pf3(&b);
        printf(" ->");
        pf3(&o3);
        printf("\n");
    }
}

// ----------------------------------------------------------------- matrix

static void s_identity(void)
{
    bMatrix4 a = mgen(3);
    bMatrix4 b = mgen(7);

    bIdentity(&a);
    printf("identity ->");
    pm(&a);
    printf("\n");

    bOldIdentity(&b);
    printf("oldidentity ->");
    pm(&b);
    printf("\n");
}

static void s_invert(void)
{
    int k;

    for (k = 0; k < 2 * NNUM; k++) {
        bMatrix4 m = affine(k);
        bMatrix4 o;

        bInvertMatrix(&o, &m);
        printf("invert");
        pm(&m);
        printf(" ->");
        pm(&o);
        printf("\n");
    }
}

static void s_mulmatrix(void)
{
    int k;

    for (k = 0; k < 2 * NNUM; k++) {
        bMatrix4 m1 = mgen(k);
        bMatrix4 m2 = mgen(k + 5);
        bMatrix4 o;

        bMulMatrix(&o, &m1, &m2);
        printf("mulmatrix");
        pm(&m1);
        pm(&m2);
        printf(" ->");
        pm(&o);
        printf("\n");
    }

    // o aliasing an input: the original loads all eight rows before it
    // stores, so this has to come out the same as the non-aliased call.
    for (k = 0; k < NNUM; k++) {
        bMatrix4 m1 = mgen(k);
        bMatrix4 m2 = mgen(k + 5);
        bMatrix4 o = m1;

        bMulMatrix(&o, &o, &m2);
        printf("mulmatrixalias");
        pm(&m1);
        pm(&m2);
        printf(" ->");
        pm(&o);
        printf("\n");
    }
}

static void s_mulvec(void)
{
    int k;

    for (k = 0; k < 2 * NNUM; k++) {
        bMatrix4 m = mgen(k);
        bVector4 a = v4(k + 3);
        bVector3 b = v3(k + 7);
        bVector4 o4;
        bVector3 o3;

        bMulMatrixVec4(&o4, &m, &a);
        printf("mulvec4");
        pm(&m);
        p4(&a);
        printf(" ->");
        p4(&o4);
        printf("\n");

        bMulMatrixVec3(&o3, &m, &b);
        printf("mulvec3");
        pm(&m);
        p3(&b);
        printf(" ->");
        p3(&o3);
        printf("\n");
    }
}

static void s_transpose(void)
{
    int k;

    for (k = 0; k < 2 * NNUM; k++) {
        bMatrix4 m = mgen(k);
        bMatrix4 o;

        bTransposeMatrix(&o, &m);
        printf("transpose");
        pm(&m);
        printf(" ->");
        pm(&o);
        printf("\n");

        // o == m is safe; all sixteen floats are read before any is written.
        o = m;
        bTransposeMatrix(&o, &o);
        printf("transposeself");
        pm(&m);
        printf(" ->");
        pm(&o);
        printf("\n");
    }
}

// ------------------------------------------------------------- quaternion

static void s_qbasic(void)
{
    int k;

    printf("identityq ->");
    pq(&bIdentityQuaternion);
    printf("\n");

    for (k = 0; k < 3 * NNUM; k++) {
        bQuaternion q;
        bQuaternion o;

        q.x = fv(k);
        q.y = fv(k + 1);
        q.z = fv(k + 2);
        q.w = fv(k + 3) + 1.0f;

        printf("qlength");
        pq(&q);
        printf(" -> %.9g\n", bLength(&q));

        bNormalize(&o, &q);
        printf("qnormalize");
        pq(&q);
        printf(" ->");
        pq(&o);
        printf("\n");

        bConjugate(&o, &q);
        printf("qconjugate");
        pq(&q);
        printf(" ->");
        pq(&o);
        printf("\n");

        // In place, which every one of the three supports.
        o = q;
        bConjugate(&o, &o);
        printf("qconjugateself");
        pq(&q);
        printf(" ->");
        pq(&o);
        printf("\n");
    }
}

static void s_qmult(void)
{
    int k;

    for (k = 0; k < 3 * NNUM; k++) {
        bQuaternion a, b, o;

        a.x = fv(k);     a.y = fv(k + 1); a.z = fv(k + 2); a.w = fv(k + 3);
        b.x = fv(k + 5); b.y = fv(k + 7); b.z = fv(k + 9); b.w = fv(k + 11);

        bMult(&o, &a, &b);
        printf("qmult");
        pq(&a);
        pq(&b);
        printf(" ->");
        pq(&o);
        printf("\n");

        // The product is not commutative, so run it the other way too.
        bMult(&o, &b, &a);
        printf("qmultrev");
        pq(&b);
        pq(&a);
        printf(" ->");
        pq(&o);
        printf("\n");
    }
}

static void s_slerp(void)
{
    static const int ts[] = { 0, 1, 64, 128, 192, 255, 256, 300, -64 };
    int k, i;

    for (k = 0; k < 2 * NNUM; k++) {
        bQuaternion a = uq(k);
        bQuaternion b = uq(k + 7);

        for (i = 0; i < (int)(sizeof ts / sizeof ts[0]); i++) {
            float t = (float)ts[i] / 256.0f;
            bQuaternion o;

            bSlerp(&o, &a, &b, t);
            printf("slerp");
            pq(&a);
            pq(&b);
            printf(" %.9g ->", t);
            pq(&o);
            printf("\n");
        }
    }

    // a and b nearly parallel, which is the branch that skips bASin.
    for (k = 0; k < NNUM; k++) {
        bQuaternion a = uq(k);
        bQuaternion b, o;
        float t = (float)(k % 5) / 4.0f;

        b.x = a.x + fv(k) / 4096.0f;
        b.y = a.y;
        b.z = a.z;
        b.w = a.w;
        bNormalize(&b, &b);

        bSlerp(&o, &a, &b, t);
        printf("slerpnear");
        pq(&a);
        pq(&b);
        printf(" %.9g ->", t);
        pq(&o);
        printf("\n");

        // Antiparallel: cos < 0, so the weight on a flips sign.
        b.x = -a.x; b.y = -a.y; b.z = -a.z; b.w = -a.w;
        bSlerp(&o, &a, &b, t);
        printf("slerpanti");
        pq(&a);
        pq(&b);
        printf(" %.9g ->", t);
        pq(&o);
        printf("\n");
    }
}

static void s_q2m(void)
{
    int k;

    for (k = 0; k < 3 * NNUM; k++) {
        bQuaternion q = uq(k);
        bQuaternion r;
        bMatrix4 m;

        bQuaternionGetMatrix(&q, &m);
        printf("getmatrix");
        pq(&q);
        printf(" ->");
        pm(&m);
        printf("\n");

        bQuaternionToMatrix(&m, &q);
        printf("tomatrix");
        pq(&q);
        printf(" ->");
        pm(&m);
        printf("\n");

        // Unnormalised too: neither routine renormalises, and the two
        // orderings diverge fastest when the quaternion is not unit.
        r.x = fv(k);
        r.y = fv(k + 2);
        r.z = fv(k + 4);
        r.w = fv(k + 6);
        bQuaternionGetMatrix(&r, &m);
        printf("getmatrixraw");
        pq(&r);
        printf(" ->");
        pm(&m);
        printf("\n");

        bQuaternionToMatrix(&m, &r);
        printf("tomatrixraw");
        pq(&r);
        printf(" ->");
        pm(&m);
        printf("\n");
    }
}

static void s_m2q(void)
{
    int k;

    for (k = 0; k < 3 * NNUM; k++) {
        bQuaternion q = uq(k);
        bQuaternion o;
        bMatrix4 m;

        bQuaternionToMatrix(&m, &q);

        bQuaternionFromMatrix(&o, &m);
        printf("frommatrix");
        pm(&m);
        printf(" ->");
        pq(&o);
        printf("\n");

        bMatrixToQuaternion(&o, &m);
        printf("matrixtoq");
        pm(&m);
        printf(" ->");
        pq(&o);
        printf("\n");
    }

    // Diagonals picked to walk the else branch through all three choices of
    // i, plus the zero matrix. A negative radicand is not reachable: when
    // the trace is not positive the largest diagonal always leaves
    // m[i][i] - m[j][j] - m[k][k] + 1 >= 0.
    {
        static const int diag[][3] = {
            { 0, 0, 0 }, { -256, -256, -256 }, { -256, 0, -512 },
            { -512, -256, 0 }, { 0, -512, -256 }, { -1024, -1024, 256 },
            { 256, -1024, -1024 }, { -1024, 256, -1024 },
        };
        int i;

        for (i = 0; i < (int)(sizeof diag / sizeof diag[0]); i++) {
            bMatrix4 m = mgen(i * 3);
            bQuaternion o;

            m.v0.x = (float)diag[i][0] / 256.0f;
            m.v1.y = (float)diag[i][1] / 256.0f;
            m.v2.z = (float)diag[i][2] / 256.0f;

            bMatrixToQuaternion(&o, &m);
            printf("matrixtoqdiag");
            pm(&m);
            printf(" ->");
            pq(&o);
            printf("\n");
        }
    }
}

// --------------------------------------------------------------- dispatch

static const struct {
    const char *name;
    void (*fn)(void);
} SCENARIOS[] = {
    {"fixmul",        s_fixmul},
    {"normalize2",    s_normalize2},
    {"normalize2to",  s_normalize2to},
    {"normalize3to",  s_normalize3to},
    {"scaleadd2",     s_scaleadd2},
    {"equal",         s_equal},
    {"bbox2",         s_bbox2},
    {"bbox2edge",     s_bbox2edge},
    {"bbox3",         s_bbox3},
    {"bbox3edge",     s_bbox3edge},
    {"lengthfix",     s_lengthfix},
    {"distfix",       s_distfix},
    {"scalefix",      s_scalefix},
    {"scaleaddfix",   s_scaleaddfix},
    {"dotfix",        s_dotfix},
    {"crossfix",      s_crossfix},
    {"normalizefix",  s_normalizefix},
    {"identity",      s_identity},
    {"invert",        s_invert},
    {"mulmatrix",     s_mulmatrix},
    {"mulvec",        s_mulvec},
    {"transpose",     s_transpose},
    {"qbasic",        s_qbasic},
    {"qmult",         s_qmult},
    {"slerp",         s_slerp},
    {"q2m",           s_q2m},
    {"m2q",           s_m2q},
};

#define NSCENARIOS ((int)(sizeof SCENARIOS / sizeof SCENARIOS[0]))

int main(int argc, char **argv)
{
    int i, a;

    if (argc < 2) {
        for (i = 0; i < NSCENARIOS; i++) {
            printf("scenario %s\n", SCENARIOS[i].name);
            SCENARIOS[i].fn();
        }
        return 0;
    }
    for (a = 1; a < argc; a++) {
        for (i = 0; i < NSCENARIOS; i++) {
            if (strcmp(argv[a], SCENARIOS[i].name) == 0) {
                printf("scenario %s\n", SCENARIOS[i].name);
                SCENARIOS[i].fn();
                break;
            }
        }
        if (i == NSCENARIOS) {
            fprintf(stderr, "unknown scenario: %s\n", argv[a]);
            return 1;
        }
    }
    return 0;
}
