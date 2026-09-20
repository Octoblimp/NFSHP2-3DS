// bvector -- bware's vector types and bVector.obj (0x00240198 .. 0x002411f0).
//
// The types come first because everything else in the math library is built
// on them: bMatrix4 is four bVector4s, bQuaternion has the same shape, and
// the fixed-point pair is what the collision and track code carries.
//
// C has no overloading, so the C++ names pick up a suffix: the digit is the
// component count, `Fix` means the Q16 integer form, and a trailing word
// distinguishes the overloads that differ only in their arguments. Every
// declaration carries the address it was ported from.
//
// Three things here are quirks rather than choices, and the port keeps them:
//
//   * A degenerate normalise does not write a zero vector. The 2D float pair
//     writes (1, 0) -- and the one that takes a length ignores that length
//     while doing it. The 3D float one writes (len, 0, 0). The Q16 ones
//     write (1.0, 0) in Q16, i.e. 0x10000.
//   * bBoundingBoxIsInside tests with <= , bBoundingBoxOverlapping with < ,
//     so a point on the boundary is inside but two boxes that merely touch
//     do not overlap.
//   * bVector3 is sixteen bytes and the VU0 code moves all four lanes, so
//     the original's `pad` participates in the 3D bounding boxes. One of
//     them feeds it uninitialised stack; see bvector.c. The port operates on
//     x/y/z and leaves pad alone.
//
// Written up in docs/formats/bmath.md.
#ifndef BVECTOR_H
#define BVECTOR_H

#include <stdint.h>

// ---------------------------------------------------------------- the types

typedef struct bVector2 {
    float x, y;
} bVector2;

// Sixteen bytes, not twelve. bMulMatrix loads and stores it as one quadword,
// which is the whole reason for the pad.
typedef struct bVector3 {
    float x, y, z, pad;
} bVector3;

typedef struct bVector4 {
    float x, y, z, w;
} bVector4;

// Polar, with the angle as a BAM.
typedef struct bPolar {
    float    r;
    uint16_t a;
} bPolar;

typedef struct bFixVector2 {
    int32_t x, y;
} bFixVector2;

typedef struct bFixVector3 {
    int32_t x, y, z;
} bFixVector3;

// FLT_MAX as the ELF holds it at 0x00324f84, used to open a bounding box.
#define BVECTOR_FLT_MAX 3.40282347e+38f

// ------------------------------------------------------------------- Q16

// (int)(((int64_t)a * b) >> 16), which the compiler emits as mult + dsll 16
// + dsra32 over the 64-bit product. Exported because half the engine's
// fixed-point arithmetic is spelled with it.
int32_t bFixMul(int32_t a, int32_t b);

// --------------------------------------------------------------- float

// 0x00240198. Zero length writes (1, 0).
void bNormalize2(bVector2 *o, const bVector2 *v);

// 0x002401f0. Scales to length `len` by dividing through by length/len.
// Zero length writes (1, 0) -- not (len, 0). Quirk, kept.
void bNormalize2To(bVector2 *o, const bVector2 *v, float len);

// 0x00240250. The sum runs on VU0, so it is (x*x + y*y) + z*z, and unlike
// the 2D pair it reciprocates once and multiplies. Zero length writes
// (len, 0, 0) -- different again.
void bNormalize3To(bVector3 *o, const bVector3 *v, float len);

// 0x002402d0. o = a + b*s.
void bScaleAdd2(bVector2 *o, const bVector2 *a, const bVector2 *b, float s);

// 0x00240300 / 0x00240350. Per-component |d| > eps fails, so eps is
// inclusive.
int bEqual2(const bVector2 *a, const bVector2 *b, float eps);
int bEqual3(const bVector3 *a, const bVector3 *b, float eps);

// ------------------------------------------------------- bounding boxes

// 0x00240cb8 / 0x00240f20. mn = +FLT_MAX, mx = -FLT_MAX, so the first
// expansion sets both.
void bInitializeBoundingBox2(bVector2 *mn, bVector2 *mx);
void bInitializeBoundingBox3(bVector3 *mn, bVector3 *mx);

// 0x00240ce0 / 0x00240f40. mn = mx = *p.
void bInitializeBoundingBox2At(bVector2 *mn, bVector2 *mx, const bVector2 *p);
void bInitializeBoundingBox3At(bVector3 *mn, bVector3 *mx, const bVector3 *p);

// 0x00240d00 / 0x00240f58.
void bExpandBoundingBox2(bVector2 *mn, bVector2 *mx, const bVector2 *p);
void bExpandBoundingBox3(bVector3 *mn, bVector3 *mx, const bVector3 *p);

// 0x00240d40 / 0x00240f80. Expands by p +/- r.
void bExpandBoundingBox2R(bVector2 *mn, bVector2 *mx, const bVector2 *p,
                          float r);
void bExpandBoundingBox3R(bVector3 *mn, bVector3 *mx, const bVector3 *p,
                          float r);

// 0x00240d90 / 0x00240fc0. Expands by another box's two corners.
void bExpandBoundingBox2Box(bVector2 *mn, bVector2 *mx, const bVector2 *lo,
                            const bVector2 *hi);
void bExpandBoundingBox3Box(bVector3 *mn, bVector3 *mx, const bVector3 *lo,
                            const bVector3 *hi);

// 0x00240dd8 / 0x00240ff0. Is p inside the box grown by eps? Strict < on
// each test, so the grown boundary counts as inside.
int bBoundingBoxIsInside2(const bVector2 *mn, const bVector2 *mx,
                          const bVector2 *p, float eps);
int bBoundingBoxIsInside3(const bVector3 *mn, const bVector3 *mx,
                          const bVector3 *p, float eps);

// 0x00240e50 / 0x002410a0. Is [iMn, iMx] contained in [mn, mx]? Inclusive.
int bBoundingBoxContains2(const bVector2 *mn, const bVector2 *mx,
                          const bVector2 *iMn, const bVector2 *iMx);
int bBoundingBoxContains3(const bVector3 *mn, const bVector3 *mx,
                          const bVector3 *iMn, const bVector3 *iMx);

// 0x00240eb8 / 0x00241138. Exclusive -- boxes that only touch do not
// overlap.
int bBoundingBoxOverlapping2(const bVector2 *mn, const bVector2 *mx,
                             const bVector2 *oMn, const bVector2 *oMx);
int bBoundingBoxOverlapping3(const bVector3 *mn, const bVector3 *mx,
                             const bVector3 *oMn, const bVector3 *oMx);

// --------------------------------------------------------- fixed point

// 0x002403c0 / 0x00240448. Pre-scales until the sum of absolute components
// fits in sixteen bits, squares the shifted components, bSqrt32, shifts
// back. The pre-scale is an arithmetic shift, so it floors rather than
// truncating toward zero.
int32_t bLengthFix2(const bFixVector2 *v);
int32_t bLengthFix3(const bFixVector3 *v);

// 0x002404f0 / 0x00240580. Same idea, but with a fixed choice of two
// shifts: 16 when the absolute sum exceeds 0x00ffffff, otherwise 8.
int32_t bDistBetweenFix2(const bFixVector2 *a, const bFixVector2 *b);
int32_t bDistBetweenFix3(const bFixVector3 *a, const bFixVector3 *b);

// 0x00240640 / 0x00240710.
void bScaleFix2(bFixVector2 *o, const bFixVector2 *v, int32_t s);
void bScaleFix3(bFixVector3 *o, const bFixVector3 *v, int32_t s);

// 0x002406a0 / 0x002407a0. o = a + b*s.
void bScaleAddFix2(bFixVector2 *o, const bFixVector2 *a,
                   const bFixVector2 *b, int32_t s);
void bScaleAddFix3(bFixVector3 *o, const bFixVector3 *a,
                   const bFixVector3 *b, int32_t s);

// 0x00240848 / 0x002408a8.
int32_t bDotFix2(const bFixVector2 *a, const bFixVector2 *b);
int32_t bDotFix3(const bFixVector3 *a, const bFixVector3 *b);

// 0x00240938.
void bCrossFix3(bFixVector3 *o, const bFixVector3 *a, const bFixVector3 *b);

// 0x00240a48 / 0x00240b58. Pre-scale as in bLengthFix, bSqrt32, then
// fixmul against bInverse(length) -- note it normalises the *shifted*
// components against the *shifted* length, which is why the ratio still
// comes out right. Zero length writes (0x10000, 0) / (0x10000, 0, 0).
// Both return o.
bFixVector2 *bNormalizeFix2(bFixVector2 *o, const bFixVector2 *v);
bFixVector3 *bNormalizeFix3(bFixVector3 *o, const bFixVector3 *v);

#endif // BVECTOR_H
