// emath -- eMathE.obj (0x0011b9a0 .. 0x0011c7b8).
//
// Almost all of this is VU0 macro mode in the original, so the listings only
// became readable once tools/vudis.py existed. Every function below carries
// the address it came from; docs/formats/emath.md has the decode.
//
// Float32 throughout. The EE has no double and neither does the VU, so every
// intermediate here is a float local -- promoting one to double would move
// the last bit of a camera position, and the cross-checker would see it.
#include "emath.h"

#include <math.h>
#include <string.h>

#include "bmath.h"

bMatrix4 eMathIdentityMatrix;
bMatrix4 eMathZeroMatrix;

// 0x0011b9a0. eIdentity on one, bMemSet on the other.
void eMathInit(void)
{
    eIdentity(&eMathIdentityMatrix);
    memset(&eMathZeroMatrix, 0, sizeof eMathZeroMatrix);
}

// 0x0011ba18.
void eIdentity(bMatrix4 *m)
{
    bIdentity(m);
}

// 0x0011ba68.
void eZeroMatrix(bMatrix4 *m)
{
    memset(m, 0, sizeof *m);
}

// 0x0011bab0.
//
//     vf4..vf7  <- m1     the broadcast operand
//     vf8..vf11 <- m2     the accumulated operand
//     vmulax  ACC,  vf8,  vf4x
//     vmadday ACC,  vf9,  vf4y
//     vmaddaz ACC,  vf10, vf4z
//     vmaddw  vf12, vf11, vf4w
//
// so out.row0 = m1.row0.x*m2.row0 + m1.row0.y*m2.row1 + ... = m1.row0 * m2.
// bMulMatrix (0x002426f8) runs the same four words with the loads swapped,
// which is why its arguments read the other way round. Expressing one in
// terms of the other is the honest way to say that out loud.
void eMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2)
{
    bMulMatrix(o, m2, m1);
}

// 0x0011bb28.
void eMulVector4(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    bMulMatrixVec4(o, m, v);
}

// 0x0011bb68. Copies the vector, forces w to 1, and calls the above.
void eMulVector3(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    bMulMatrixVec3(o, m, v);
}

// 0x0011c368.
void eTransposeMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    bTransposeMatrix(o, m);
}

// 0x0011c310.
void eCreateTranslationMatrix(bMatrix4 *m, const bVector3 *v)
{
    bIdentity(m);
    m->v3.x = v->x;
    m->v3.y = v->y;
    m->v3.z = v->z;
}

// ---------------------------------------------------------------- eSin

// 0x0011bf50. Reduce into [0, 2pi) by repeated add/subtract -- not fmod, so
// a huge argument spins -- then fold the upper half onto the lower and the
// second quadrant onto the first, then a 9th-order odd polynomial.
//
// The reduction loops are `while`, not `if`, and they compare against the
// image's own 0x40c90fdb rather than a rounded 2*pi. The sum order below is
// the order the compiler emitted at 0x0011c01c..0x0011c038, which for float
// is not the same number as any other order.
#define E_TWO_PI   0x1.921fb6p+2f     /* 0x40c90fdb */
#define E_PI       0x1.921fb6p+1f     /* 0x40490fdb */
#define E_HALF_PI  0x1.921fb6p+0f     /* 0x3fc90fdb */
#define E_SIN_C3   -0x1.555548p-3f    /* 0xbe2aaaa4 */
#define E_SIN_C5   0x1.110e7cp-7f     /* 0x3c08873e */
#define E_SIN_C7   -0x1.9f643ep-13f   /* 0xb94fb21f */
#define E_SIN_C9   0x1.5d3828p-19f    /* 0x362e9c14 */

float eSin(float x)
{
    float sign = 1.0f;
    float x2, x3, x5, x7, x9, r;

    while (E_TWO_PI < x) x = x - E_TWO_PI;
    while (x < 0.0f)     x = x + E_TWO_PI;

    if (E_PI <= x) {
        x = x - E_PI;
        sign = -1.0f;
    }
    if (E_HALF_PI <= x) x = E_PI - x;

    x2 = x * x;
    x3 = x * x2;
    x5 = x3 * x2;
    x7 = x5 * x2;
    x9 = x7 * x2;

    r = x + x3 * E_SIN_C3;
    r = r + x5 * E_SIN_C5;
    r = r + x7 * E_SIN_C7;
    r = r + x9 * E_SIN_C9;
    return r * sign;
}

// --------------------------------------------------------------- rotations

// The three eRotate* functions share a shape: BAM to radians, cosine as
// eSin(theta + pi/2), sine as eSin(theta), then *o = *m * R.
//
// The half-turn constant they add is 0x3fc90fdc, one ulp above the 0x3fc90fdb
// that eSin itself compares against. Both spellings are in the image and the
// port keeps them apart, because collapsing them changes the last bit of
// every cosine.
#define E_BAM_TO_RAD   0x1.921fb6p-14f   /* 0x38c90fdb */
#define E_ROT_HALF_PI  0x1.921fb8p+0f    /* 0x3fc90fdc */

static void rot_sin_cos(uint16_t bam, float *s, float *c)
{
    float theta = (float)(int)bam * E_BAM_TO_RAD;

    *c = eSin(theta + E_ROT_HALF_PI);
    *s = eSin(theta);
}

// 0x0011c048.
void eRotateX(bMatrix4 *o, const bMatrix4 *m, uint16_t bam)
{
    bMatrix4 r;
    float s, c;

    rot_sin_cos(bam, &s, &c);
    memset(&r, 0, sizeof r);
    r.v0.x = 1.0f;
    r.v1.y = c;  r.v1.z = s;
    r.v2.y = -s; r.v2.z = c;
    r.v3.w = 1.0f;
    eMulMatrix(o, m, &r);
}

// 0x0011c110.
void eRotateY(bMatrix4 *o, const bMatrix4 *m, uint16_t bam)
{
    bMatrix4 r;
    float s, c;

    rot_sin_cos(bam, &s, &c);
    memset(&r, 0, sizeof r);
    r.v0.x = c;  r.v0.z = -s;
    r.v1.y = 1.0f;
    r.v2.x = s;  r.v2.z = c;
    r.v3.w = 1.0f;
    eMulMatrix(o, m, &r);
}

// 0x0011c1d8.
void eRotateZ(bMatrix4 *o, const bMatrix4 *m, uint16_t bam)
{
    bMatrix4 r;
    float s, c;

    rot_sin_cos(bam, &s, &c);
    memset(&r, 0, sizeof r);
    r.v0.x = c;  r.v0.y = s;
    r.v1.x = -s; r.v1.y = c;
    r.v2.z = 1.0f;
    r.v3.w = 1.0f;
    eMulMatrix(o, m, &r);
}

// 0x0011c2a0.
void eTranslate(bMatrix4 *o, const bMatrix4 *m, const bVector3 *v)
{
    bMatrix4 t;

    eCreateTranslationMatrix(&t, v);
    eMulMatrix(o, m, &t);
}

// 0x0011bc68. bCosBam/bSinBam here, not eSin -- the one place in the file
// that reads the table.
void eCreateAxisRotationMatrix(bMatrix4 *m, const bVector3 *axis, uint16_t bam)
{
    float c = bCosBam(bam);
    float s = bSinBam(bam);
    float x = axis->x, y = axis->y, z = axis->z;
    float k = 1.0f - c;
    float sz = s * z, sy = s * y, sx = x * s;
    float kx = k * x, ky = k * y, kz = k * z;
    float kxz = kx * z, kzz = kz * z, kyz = ky * z;
    float kyy = ky * y, kxy = kx * y, kxx = kx * x;

    m->v0.x = kxx + c;  m->v0.y = kxy - sz; m->v0.z = kxz + sy; m->v0.w = 0.0f;
    m->v1.x = kxy + sz; m->v1.y = kyy + c;  m->v1.z = kyz - sx; m->v1.w = 0.0f;
    m->v2.x = kxz - sy; m->v2.y = kyz + sx; m->v2.z = kzz + c;  m->v2.w = 0.0f;
    m->v3.x = 0.0f; m->v3.y = 0.0f; m->v3.z = 0.0f; m->v3.w = 1.0f;
}

// The VU cross product, which every caller spells the same way:
//
//     vopmula.xyz ACC, a, b        ACC = (a.y*b.z, a.z*b.x, a.x*b.y)
//     vopmsub.xyz d,   b, a        d   = ACC - (b.y*a.z, b.z*a.x, b.x*a.y)
//
// -- so d = a x b, and the subtraction order is fixed. w is not written.
static void vu_cross(bVector3 *d, const bVector3 *a, const bVector3 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    d->x = x; d->y = y; d->z = z;
}

// The normalise the rest of the image uses: the squared length is summed x,
// then y, then z, and the scale applied to all four lanes.
//
// The hardware gets the scale from VRSQRT, which is a reduced-precision unit
// rather than an IEEE divide-and-root, so this is the one place in the file
// where the port cannot be bit-exact. It is the same compromise bmath.c
// makes, for the same reason. The fourth lane is scaled on the VU too and is
// not reproduced: nothing downstream reads it, and for a bVector3 argument
// it is the uninitialised pad that bvector.h warns about.
static void vu_normalize(bVector3 *v)
{
    float d = v->x * v->x;
    float k;

    d = d + v->y * v->y;
    d = d + v->z * v->z;
    k = 1.0f / sqrtf(d);
    v->x *= k; v->y *= k; v->z *= k;
}

// 0x0011bd68. dir = normalize(target - eye); right = (-up) x dir;
// up' = dir x right; then rows (right, up', dir) as COLUMNS -- the matrix is
// written transposed, which is what makes it a world-to-camera transform --
// and finally o = T(-eye) * that.
void eCreateLookAtMatrix(bMatrix4 *m, const bVector3 *eye,
                         const bVector3 *target, const bVector3 *up)
{
    bVector3 dir, negUp, right, newUp;
    bMatrix4 rot, trans, tmp;

    // vsub.xyzw through vf00 at 0x0011bd7c, so the hardware also writes
    // 1 - up.w into the fourth lane. Every later read is .xyz.
    negUp.x = 0.0f - up->x;
    negUp.y = 0.0f - up->y;
    negUp.z = 0.0f - up->z;

    dir.x = target->x - eye->x;
    dir.y = target->y - eye->y;
    dir.z = target->z - eye->z;
    vu_normalize(&dir);

    vu_cross(&right, &negUp, &dir);
    vu_cross(&newUp, &dir, &right);
    vu_normalize(&right);
    vu_normalize(&newUp);

    rot.v0.x = right.x; rot.v0.y = newUp.x; rot.v0.z = dir.x; rot.v0.w = 0.0f;
    rot.v1.x = right.y; rot.v1.y = newUp.y; rot.v1.z = dir.y; rot.v1.w = 0.0f;
    rot.v2.x = right.z; rot.v2.y = newUp.z; rot.v2.z = dir.z; rot.v2.w = 0.0f;
    rot.v3.x = 0.0f; rot.v3.y = 0.0f; rot.v3.z = 0.0f; rot.v3.w = 1.0f;

    bIdentity(&trans);
    trans.v3.x = 0.0f - eye->x;
    trans.v3.y = 0.0f - eye->y;
    trans.v3.z = 0.0f - eye->z;

    tmp = rot;
    eMulMatrix(m, &trans, &tmp);
}

// 0x0011c3f0.
void eInvertTransformationMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    bMatrix4 rot, trans;

    rot.v0.x = m->v0.x; rot.v0.y = m->v1.x; rot.v0.z = m->v2.x; rot.v0.w = 0.0f;
    rot.v1.x = m->v0.y; rot.v1.y = m->v1.y; rot.v1.z = m->v2.y; rot.v1.w = 0.0f;
    rot.v2.x = m->v0.z; rot.v2.y = m->v1.z; rot.v2.z = m->v2.z; rot.v2.w = 0.0f;
    rot.v3.x = 0.0f; rot.v3.y = 0.0f; rot.v3.z = 0.0f; rot.v3.w = 1.0f;

    bIdentity(&trans);
    trans.v3.x = 0.0f - m->v3.x;
    trans.v3.y = 0.0f - m->v3.y;
    trans.v3.z = 0.0f - m->v3.z;

    eMulMatrix(o, &trans, &rot);
}

// 0x0011c6a0. Transpose, then clear the fourth column, row 3, AND o[3][3].
void eInvertRotationMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    eTransposeMatrix(o, m);
    o->v0.w = 0.0f;
    o->v1.w = 0.0f;
    o->v2.w = 0.0f;
    o->v3.x = 0.0f;
    o->v3.y = 0.0f;
    o->v3.z = 0.0f;
    o->v3.w = 0.0f;
}

// 0x0011c5d0. Note the order: row2 comes out of the ORIGINAL row1, before
// row1 is replaced, and only rows 0 and 1 of the input are read at all.
void eOrthonormalizeMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    bVector3 x, y, z;

    x.x = m->v0.x; x.y = m->v0.y; x.z = m->v0.z;
    y.x = m->v1.x; y.y = m->v1.y; y.z = m->v1.z;

    vu_normalize(&x);
    vu_cross(&z, &x, &y);
    vu_normalize(&z);
    vu_cross(&y, &z, &x);

    o->v0.x = x.x; o->v0.y = x.y; o->v0.z = x.z; o->v0.w = 0.0f;
    o->v1.x = y.x; o->v1.y = y.y; o->v1.z = y.z; o->v1.w = 0.0f;
    o->v2.x = z.x; o->v2.y = z.y; o->v2.z = z.z; o->v2.w = 0.0f;
    o->v3.x = 0.0f; o->v3.y = 0.0f; o->v3.z = 0.0f; o->v3.w = 1.0f;
}

// 0x0011b9e0. The 2D-length bug is in the two lines that build `d`: the
// accumulator gets x+y in its x lane and z in its z lane, and the vmaddw
// that follows reads only the x lane. See docs/formats/emath.md.
void eNormalizedDirection(bVector4 *o, const bVector4 *from, const bVector4 *to)
{
    float dx = to->x - from->x;
    float dy = to->y - from->y;
    float dz = to->z - from->z;
    float d = dx * dx + dy * dy;
    float k = 1.0f / sqrtf(d);

    o->x = dx * k;
    o->y = dy * k;
    o->z = dz * k;
}

// 0x0011bf48.
void eReflectVector(bVector4 *o, const bVector4 *v, const bVector4 *n)
{
    (void)o; (void)v; (void)n;
}

// One row of a transform with w forced to 1 from vf00, NOT from the vector.
static void transform_w1(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    float x = v->x * m->v0.x + v->y * m->v1.x + v->z * m->v2.x + m->v3.x;
    float y = v->x * m->v0.y + v->y * m->v1.y + v->z * m->v2.y + m->v3.y;
    float z = v->x * m->v0.z + v->y * m->v1.z + v->z * m->v2.z + m->v3.z;
    float w = v->x * m->v0.w + v->y * m->v1.w + v->z * m->v2.w + m->v3.w;

    o->x = x; o->y = y; o->z = z; o->w = w;
}

// 0x0011bb98. xyz are divided by w; w itself is stored undivided.
void eRotTransPers(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    bVector4 t;
    float q;

    transform_w1(&t, m, v);
    q = 1.0f / t.w;
    t.x *= q; t.y *= q; t.z *= q;
    *o = t;
}

// 0x0011bc00. VU0's VCLIPw compares each of x, y, z against +|w| and -|w|
// with strict inequalities and pushes six bits into the clip register; the
// caller keeps the low six, which is the most recent test.
uint32_t eGetClipFlags(const bVector4 *v, const bMatrix4 *m)
{
    bVector4 t;
    float w;
    uint32_t f = 0;

    transform_w1(&t, m, v);
    w = t.w < 0.0f ? -t.w : t.w;
    if (t.x > w)  f |= 0x01u;
    if (t.x < -w) f |= 0x02u;
    if (t.y > w)  f |= 0x04u;
    if (t.y < -w) f |= 0x08u;
    if (t.z > w)  f |= 0x10u;
    if (t.z < -w) f |= 0x20u;
    return f;
}

// 0x0011c4e8. Row i of o is v x row i of m. The scalar code writes nine
// floats and leaves the fourth column and row 3 exactly as it found them.
void eVectorStarMatrix(bMatrix4 *o, const bVector3 *v, const bMatrix4 *m)
{
    float vx = v->x, vy = v->y, vz = v->z;

    o->v0.x = -vz * m->v0.y + vy * m->v0.z;
    o->v0.y = vz * m->v0.x + -vx * m->v0.z;
    o->v0.z = -vy * m->v0.x + vx * m->v0.y;
    o->v1.x = -vz * m->v1.y + vy * m->v1.z;
    o->v1.y = vz * m->v1.x + -vx * m->v1.z;
    o->v1.z = -vy * m->v1.x + vx * m->v1.y;
    o->v2.x = -vz * m->v2.y + vy * m->v2.z;
    o->v2.y = vz * m->v2.x + -vx * m->v2.z;
    o->v2.z = -vy * m->v2.x + vx * m->v2.y;
}

// 0x0011c6e8. Crossing number. `j` trails `i` by one and starts at n-1, and
// the y comparison is half-open on one side only, so a ray through a vertex
// is counted once rather than twice.
int eIsPointInPoly(const bVector2 *pt, const bVector2 *poly, int n)
{
    int i, j = n - 1, inside = 0;

    for (i = 0; i < n; i++) {
        if (((poly[i].y <= pt->y && pt->y < poly[j].y)) ||
            ((poly[j].y <= pt->y && pt->y < poly[i].y))) {
            float t = (poly[j].x - poly[i].x) * (pt->y - poly[i].y);

            if (pt->x < t / (poly[j].y - poly[i].y) + poly[i].x)
                inside = !inside;
        }
        j = i;
    }
    return inside;
}
