// bvector -- bVector.obj (0x00240198 .. 0x002411f0).
//
// Ported instruction by instruction. The operation order is the original's
// wherever float32 can tell the difference, which for a dot product means
// it matters: the VU0 sum in bNormalize3To is (x*x + y*y) + z*z and writing
// it any other way moves the last bit.
//
// docs/formats/bmath.md has the decode with an address for every rule.
#include "bvector.h"

#include <math.h>

#include "bmath.h"
#include "eefpu.h"

// ------------------------------------------------------------------- Q16

// The original is mult + dsll 16 + dsra32: a 32x32 signed multiply into 64
// bits, shifted left sixteen (which drops the product's top sixteen bits)
// and then arithmetic-shifted right thirty-two. That is bits 16..47 of the
// product, sign-extended -- the same thing as >> 16 on the low 48 bits, and
// this is the spelling that says so without inviting a wider shift.
int32_t bFixMul(int32_t a, int32_t b)
{
    return (int32_t)(((int64_t)a * (int64_t)b) >> 16);
}

// pmaxw x,x,-x -- absolute value that wraps at INT32_MIN rather than
// trapping, which is what the hardware does.
static int32_t absw(int32_t x)
{
    int32_t n = (int32_t)(0u - (uint32_t)x);
    return n > x ? n : x;
}

// The pre-scale both bLengthFix and bNormalizeFix open with: shift right in
// steps of two until the sum of absolute components fits in sixteen bits,
// so the squares below cannot overflow the 32-bit multiply.
static int prescale(int32_t sum)
{
    int s = 0;

    if (0xffff < sum) {
        do {
            s += 2;
        } while (0xffff < (sum >> s));
    }
    return s;
}

// mult/mult1 keep only the low 32 bits of the product.
static int32_t sqw(int32_t x)
{
    return (int32_t)((uint32_t)x * (uint32_t)x);
}

// addu / subu. Every sum below can reach the end of the range on inputs the
// game will never produce, and signed overflow is undefined in C, so the
// wrap is spelled out rather than left to the optimiser.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

static int32_t sub32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a - (uint32_t)b);
}

// --------------------------------------------------------------- float

// 0x00240198.
void bNormalize2(bVector2 *o, const bVector2 *v)
{
    float y = v->y, x = v->x;
    float len = sqrtf(x * x + y * y);

    if (len == 0.0f) {
        o->y = 0.0f;
        o->x = 1.0f;
        return;
    }
    o->y = y / len;
    o->x = x / len;
}

// 0x002401f0. Note what happens when the vector is zero: it writes (1, 0)
// and never looks at `len`. That is the shipped behaviour.
void bNormalize2To(bVector2 *o, const bVector2 *v, float len)
{
    float y = v->y, x = v->x;
    float k = sqrtf(x * x + y * y) / len;

    if (k == 0.0f) {
        o->y = 0.0f;
        o->x = 1.0f;
        return;
    }
    o->y = y / k;
    o->x = x / k;
}

// 0x00240250. The length comes off VU0 as (x*x + y*y) + z*z -- vmul.xyz,
// vaddy.x, vaddz.x, qmfc2 the x lane -- and then this one reciprocates once
// and multiplies, where the 2D pair divides three times.
//
// The first divide, 0x00240274, is ee_div's. MellowMover::JumpStabilizer
// asks for a length of zero whenever the car is already where it would
// turn it, and then the vector is zero too: 0/0, a NaN here and FLT_MAX on
// the console, whose reciprocal scales the zero to a zero.
void bNormalize3To(bVector3 *o, const bVector3 *v, float len)
{
    float n = (v->x * v->x + v->y * v->y) + v->z * v->z;
    float k = ee_div(sqrtf(n), len);
    float r;

    if (k == 0.0f) {
        o->x = len;
        o->z = 0.0f;
        o->y = 0.0f;
        return;
    }
    r = 1.0f / k;
    o->z = v->z * r;
    o->x = v->x * r;
    o->y = v->y * r;
}

// 0x002402d0.
void bScaleAdd2(bVector2 *o, const bVector2 *a, const bVector2 *b, float s)
{
    o->y = a->y + b->y * s;
    o->x = a->x + b->x * s;
}

// 0x00240300. The test is `eps < |d|` fails, so a difference of exactly eps
// still counts as equal.
int bEqual2(const bVector2 *a, const bVector2 *b, float eps)
{
    if (eps < fabsf(a->x - b->x)) return 0;
    if (eps < fabsf(a->y - b->y)) return 0;
    return 1;
}

// 0x00240350.
int bEqual3(const bVector3 *a, const bVector3 *b, float eps)
{
    if (eps < fabsf(a->x - b->x)) return 0;
    if (eps < fabsf(a->y - b->y)) return 0;
    if (eps < fabsf(a->z - b->z)) return 0;
    return 1;
}

// ------------------------------------------------------- bounding boxes

// 0x00240cb8.
void bInitializeBoundingBox2(bVector2 *mn, bVector2 *mx)
{
    mn->y = BVECTOR_FLT_MAX;
    mn->x = BVECTOR_FLT_MAX;
    mx->y = -BVECTOR_FLT_MAX;
    mx->x = -BVECTOR_FLT_MAX;
}

// 0x00240f20. The original loads bVector3FLT_MAX (0x00315280) as a quadword
// and makes the max corner as vf0 - it, where vf0 is the VU's (0,0,0,1) --
// so its pad lanes come out 0.0f and 1.0f. The port has no pad lane to fill
// and leaves .pad alone.
void bInitializeBoundingBox3(bVector3 *mn, bVector3 *mx)
{
    mn->x = BVECTOR_FLT_MAX;
    mn->y = BVECTOR_FLT_MAX;
    mn->z = BVECTOR_FLT_MAX;
    mx->x = -BVECTOR_FLT_MAX;
    mx->y = -BVECTOR_FLT_MAX;
    mx->z = -BVECTOR_FLT_MAX;
}

// 0x00240ce0.
void bInitializeBoundingBox2At(bVector2 *mn, bVector2 *mx, const bVector2 *p)
{
    mn->y = p->y;
    mn->x = p->x;
    mx->y = p->y;
    mx->x = p->x;
}

// 0x00240f40.
void bInitializeBoundingBox3At(bVector3 *mn, bVector3 *mx, const bVector3 *p)
{
    mn->x = p->x;
    mn->y = p->y;
    mn->z = p->z;
    mx->x = p->x;
    mx->y = p->y;
    mx->z = p->z;
}

// 0x00240d00.
void bExpandBoundingBox2(bVector2 *mn, bVector2 *mx, const bVector2 *p)
{
    if (p->x < mn->x) mn->x = p->x;
    if (p->y < mn->y) mn->y = p->y;
    if (mx->x < p->x) mx->x = p->x;
    if (mx->y < p->y) mx->y = p->y;
}

// 0x00240f58 -- vmini/vmax over the whole quadword, so the original also
// folds the pad lane in. x/y/z only here.
void bExpandBoundingBox3(bVector3 *mn, bVector3 *mx, const bVector3 *p)
{
    if (p->x < mn->x) mn->x = p->x;
    if (p->y < mn->y) mn->y = p->y;
    if (p->z < mn->z) mn->z = p->z;
    if (mx->x < p->x) mx->x = p->x;
    if (mx->y < p->y) mx->y = p->y;
    if (mx->z < p->z) mx->z = p->z;
}

// 0x00240d40.
void bExpandBoundingBox2R(bVector2 *mn, bVector2 *mx, const bVector2 *p,
                          float r)
{
    float lox = p->x - r, loy = p->y - r;
    float hix = p->x + r, hiy = p->y + r;

    if (lox < mn->x) mn->x = lox;
    if (loy < mn->y) mn->y = loy;
    if (mx->x < hix) mx->x = hix;
    if (mx->y < hiy) mx->y = hiy;
}

// 0x00240f80. The original builds the radius vector on the stack and writes
// only sp[0..2], then loads all sixteen bytes -- so the w lane of the
// vmini/vmax is whatever was on the stack, and both corners' pad lanes get
// it. That is not reproducible and should not be: operate on x/y/z.
void bExpandBoundingBox3R(bVector3 *mn, bVector3 *mx, const bVector3 *p,
                          float r)
{
    float lox = p->x - r, loy = p->y - r, loz = p->z - r;
    float hix = p->x + r, hiy = p->y + r, hiz = p->z + r;

    if (lox < mn->x) mn->x = lox;
    if (loy < mn->y) mn->y = loy;
    if (loz < mn->z) mn->z = loz;
    if (mx->x < hix) mx->x = hix;
    if (mx->y < hiy) mx->y = hiy;
    if (mx->z < hiz) mx->z = hiz;
}

// 0x00240d90.
void bExpandBoundingBox2Box(bVector2 *mn, bVector2 *mx, const bVector2 *lo,
                            const bVector2 *hi)
{
    if (lo->x < mn->x) mn->x = lo->x;
    if (lo->y < mn->y) mn->y = lo->y;
    if (mx->x < hi->x) mx->x = hi->x;
    if (mx->y < hi->y) mx->y = hi->y;
}

// 0x00240fc0.
void bExpandBoundingBox3Box(bVector3 *mn, bVector3 *mx, const bVector3 *lo,
                            const bVector3 *hi)
{
    if (lo->x < mn->x) mn->x = lo->x;
    if (lo->y < mn->y) mn->y = lo->y;
    if (lo->z < mn->z) mn->z = lo->z;
    if (mx->x < hi->x) mx->x = hi->x;
    if (mx->y < hi->y) mx->y = hi->y;
    if (mx->z < hi->z) mx->z = hi->z;
}

// 0x00240dd8. Six strict compares; the point is outside only when it is
// strictly past the grown edge.
int bBoundingBoxIsInside2(const bVector2 *mn, const bVector2 *mx,
                          const bVector2 *p, float eps)
{
    if (p->x < mn->x - eps) return 0;
    if (mx->x + eps < p->x) return 0;
    if (p->y < mn->y - eps) return 0;
    if (mx->y + eps < p->y) return 0;
    return 1;
}

// 0x00240ff0.
int bBoundingBoxIsInside3(const bVector3 *mn, const bVector3 *mx,
                          const bVector3 *p, float eps)
{
    if (p->x < mn->x - eps) return 0;
    if (mx->x + eps < p->x) return 0;
    if (p->y < mn->y - eps) return 0;
    if (mx->y + eps < p->y) return 0;
    if (p->z < mn->z - eps) return 0;
    if (mx->z + eps < p->z) return 0;
    return 1;
}

// 0x00240e50. Inclusive: a box contains itself.
int bBoundingBoxContains2(const bVector2 *mn, const bVector2 *mx,
                          const bVector2 *iMn, const bVector2 *iMx)
{
    if (!(mn->x <= iMn->x)) return 0;
    if (!(iMx->x <= mx->x)) return 0;
    if (!(mn->y <= iMn->y)) return 0;
    if (!(iMx->y <= mx->y)) return 0;
    return 1;
}

// 0x002410a0.
int bBoundingBoxContains3(const bVector3 *mn, const bVector3 *mx,
                          const bVector3 *iMn, const bVector3 *iMx)
{
    if (!(mn->x <= iMn->x)) return 0;
    if (!(iMx->x <= mx->x)) return 0;
    if (!(mn->y <= iMn->y)) return 0;
    if (!(iMx->y <= mx->y)) return 0;
    if (!(mn->z <= iMn->z)) return 0;
    if (!(iMx->z <= mx->z)) return 0;
    return 1;
}

// 0x00240eb8. Exclusive, so two boxes sharing an edge do not overlap.
int bBoundingBoxOverlapping2(const bVector2 *mn, const bVector2 *mx,
                             const bVector2 *oMn, const bVector2 *oMx)
{
    if (!(oMn->x < mx->x)) return 0;
    if (!(mn->x < oMx->x)) return 0;
    if (!(oMn->y < mx->y)) return 0;
    if (!(mn->y < oMx->y)) return 0;
    return 1;
}

// 0x00241138.
int bBoundingBoxOverlapping3(const bVector3 *mn, const bVector3 *mx,
                             const bVector3 *oMn, const bVector3 *oMx)
{
    if (!(oMn->x < mx->x)) return 0;
    if (!(mn->x < oMx->x)) return 0;
    if (!(oMn->y < mx->y)) return 0;
    if (!(mn->y < oMx->y)) return 0;
    if (!(oMn->z < mx->z)) return 0;
    if (!(mn->z < oMx->z)) return 0;
    return 1;
}

// --------------------------------------------------------- fixed point

// 0x002403c0.
int32_t bLengthFix2(const bFixVector2 *v)
{
    int32_t y = v->y, x = v->x;
    int s = prescale(add32(absw(x), absw(y)));
    int32_t xs = x >> s, ys = y >> s;

    return (int32_t)((uint32_t)bSqrt32((uint32_t)add32(sqw(xs), sqw(ys)))
                     << s);
}

// 0x00240448. The absolute sum accumulates (|x| + |y|) + |z| and the squares
// (x*x + y*y) + z*z, in that order -- neither can overflow after the
// pre-scale, but keep the shape.
int32_t bLengthFix3(const bFixVector3 *v)
{
    int32_t x = v->x, y = v->y, z = v->z;
    int s = prescale(add32(add32(absw(x), absw(y)), absw(z)));
    int32_t xs = x >> s, ys = y >> s, zs = z >> s;

    return (int32_t)((uint32_t)bSqrt32(
        (uint32_t)add32(add32(sqw(xs), sqw(ys)), sqw(zs))) << s);
}

// 0x002404f0. Not the pre-scale loop -- a straight choice between two
// shifts, so a very small distance between two very distant points loses
// eight bits it did not have to.
int32_t bDistBetweenFix2(const bFixVector2 *a, const bFixVector2 *b)
{
    int32_t dx = sub32(a->x, b->x), dy = sub32(a->y, b->y);
    int s = add32(absw(dx), absw(dy)) > 0x00ffffff ? 16 : 8;
    int32_t xs = dx >> s, ys = dy >> s;

    return (int32_t)((uint32_t)bSqrt32((uint32_t)add32(sqw(xs), sqw(ys)))
                     << s);
}

// 0x00240580.
int32_t bDistBetweenFix3(const bFixVector3 *a, const bFixVector3 *b)
{
    int32_t dx = sub32(a->x, b->x), dy = sub32(a->y, b->y);
    int32_t dz = sub32(a->z, b->z);
    int s = add32(add32(absw(dx), absw(dy)), absw(dz)) > 0x00ffffff ? 16 : 8;
    int32_t xs = dx >> s, ys = dy >> s, zs = dz >> s;

    return (int32_t)((uint32_t)bSqrt32(
        (uint32_t)add32(add32(sqw(xs), sqw(ys)), sqw(zs))) << s);
}

// 0x00240640.
void bScaleFix2(bFixVector2 *o, const bFixVector2 *v, int32_t s)
{
    o->y = bFixMul(v->y, s);
    o->x = bFixMul(v->x, s);
}

// 0x00240710.
void bScaleFix3(bFixVector3 *o, const bFixVector3 *v, int32_t s)
{
    o->z = bFixMul(v->z, s);
    o->x = bFixMul(v->x, s);
    o->y = bFixMul(v->y, s);
}

// 0x002406a0.
void bScaleAddFix2(bFixVector2 *o, const bFixVector2 *a,
                   const bFixVector2 *b, int32_t s)
{
    o->y = (int32_t)((uint32_t)a->y + (uint32_t)bFixMul(b->y, s));
    o->x = (int32_t)((uint32_t)a->x + (uint32_t)bFixMul(b->x, s));
}

// 0x002407a0.
void bScaleAddFix3(bFixVector3 *o, const bFixVector3 *a,
                   const bFixVector3 *b, int32_t s)
{
    o->x = (int32_t)((uint32_t)a->x + (uint32_t)bFixMul(b->x, s));
    o->y = (int32_t)((uint32_t)a->y + (uint32_t)bFixMul(b->y, s));
    o->z = (int32_t)((uint32_t)a->z + (uint32_t)bFixMul(b->z, s));
}

// 0x00240848.
int32_t bDotFix2(const bFixVector2 *a, const bFixVector2 *b)
{
    int32_t px = bFixMul(a->x, b->x);
    int32_t py = bFixMul(a->y, b->y);

    return (int32_t)((uint32_t)px + (uint32_t)py);
}

// 0x002408a8. Summed as (x + y) + z.
int32_t bDotFix3(const bFixVector3 *a, const bFixVector3 *b)
{
    int32_t px = bFixMul(a->x, b->x);
    int32_t py = bFixMul(a->y, b->y);
    int32_t pz = bFixMul(a->z, b->z);

    return (int32_t)(((uint32_t)px + (uint32_t)py) + (uint32_t)pz);
}

// 0x00240938.
void bCrossFix3(bFixVector3 *o, const bFixVector3 *a, const bFixVector3 *b)
{
    int32_t yx = bFixMul(a->y, b->x);
    int32_t xz = bFixMul(a->x, b->z);
    int32_t zx = bFixMul(a->z, b->x);
    int32_t xy = bFixMul(a->x, b->y);
    int32_t yz = bFixMul(a->y, b->z);
    int32_t zy = bFixMul(a->z, b->y);

    o->y = (int32_t)((uint32_t)zx - (uint32_t)xz);
    o->z = (int32_t)((uint32_t)xy - (uint32_t)yx);
    o->x = (int32_t)((uint32_t)yz - (uint32_t)zy);
}

// 0x00240a48. bInverse of the length is about 2**32/len, so multiplying a
// pre-scaled component by it in Q16 lands on a Q16 unit vector. Note that
// both the component and the length are the pre-scaled ones -- the shift
// cancels.
bFixVector2 *bNormalizeFix2(bFixVector2 *o, const bFixVector2 *v)
{
    int32_t y = v->y, x = v->x;
    int s = prescale(add32(absw(x), absw(y)));
    int32_t xs = x >> s, ys = y >> s;
    int32_t len = (int32_t)bSqrt32((uint32_t)add32(sqw(xs), sqw(ys)));
    int32_t inv;

    if (len == 0) {
        o->y = 0;
        o->x = 0x10000;
        return o;
    }
    inv = bInverse(len);
    o->y = bFixMul(ys, inv);
    o->x = bFixMul(xs, inv);
    return o;
}

// 0x00240b58.
bFixVector3 *bNormalizeFix3(bFixVector3 *o, const bFixVector3 *v)
{
    int32_t x = v->x, y = v->y, z = v->z;
    int s = prescale(add32(add32(absw(x), absw(y)), absw(z)));
    int32_t xs = x >> s, ys = y >> s, zs = z >> s;
    int32_t len = (int32_t)bSqrt32(
        (uint32_t)add32(add32(sqw(xs), sqw(ys)), sqw(zs)));
    int32_t inv;

    if (len == 0) {
        o->y = 0;
        o->z = 0;
        o->x = 0x10000;
        return o;
    }
    inv = bInverse(len);
    o->x = bFixMul(xs, inv);
    o->y = bFixMul(ys, inv);
    o->z = bFixMul(zs, inv);
    return o;
}
