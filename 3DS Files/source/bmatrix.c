// bmatrix -- bMatrix.obj (0x002424f8 .. 0x00242890).
//
// The three multiplies are VU0 macro mode in the original, four instructions
// per output row:
//
//     vmulax  ACC,  vf8,  vf4x
//     vmadday ACC,  vf9,  vf4y
//     vmaddaz ACC,  vf10, vf4z
//     vmaddw  vf12, vf11, vf4w
//
// -- so each output row is a linear combination of vf8..vf11 weighted by the
// four lanes of vf4. Which operand lands where is the whole question of
// argument order, and bmatrix.h answers it.
//
// Every multiply here loads all of its inputs before storing anything, which
// is free on the VU and costs a temporary in C. The temporary is kept, so
// `bMulMatrix(&m, &m, &n)` behaves the same in the port as on the hardware.
//
// docs/formats/bmath.md has the decode with an address for every rule.
#include "bmatrix.h"

#include <string.h>

// 0x002424f8. The original assembles this out of por/pexew/pexcw/pextlw on a
// 128-bit GPR, which is just a clever way of writing the identity.
void bIdentity(bMatrix4 *m)
{
    memset(m, 0, sizeof *m);
    m->v0.x = 1.0f;
    m->v1.y = 1.0f;
    m->v2.z = 1.0f;
    m->v3.w = 1.0f;
}

// 0x00242528. The same matrix, written a float at a time. Both symbols ship
// and both have callers.
void bOldIdentity(bMatrix4 *m)
{
    bIdentity(m);
}

// 0x00242578. Adjugate over determinant on the upper 3x3, then the
// translation row through the inverted rotation.
//
// The negated cofactors are produced by multiplying with -k rather than by
// negating afterwards (neg.s $f1,$f9 at 0x00242630). For float32 that is the
// same number everywhere except the sign of a zero, and it is what the
// hardware does.
void bInvertMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    float a = m->v0.x, b = m->v0.y, c = m->v0.z;
    float d = m->v1.x, e = m->v1.y, f = m->v1.z;
    float g = m->v2.x, h = m->v2.y, i = m->v2.z;
    float tx = m->v3.x, ty = m->v3.y, tz = m->v3.z;

    float ei_fh = e * i - f * h;
    float di_fg = d * i - f * g;
    float dh_eg = d * h - e * g;

    float det = a * ei_fh - b * di_fg + c * dh_eg;
    float k = 1.0f / det;
    float nk = -k;

    float o00 = ei_fh * k;
    float o01 = (b * i - c * h) * nk;
    float o02 = (b * f - c * e) * k;
    float o10 = di_fg * nk;
    float o11 = (a * i - c * g) * k;
    float o12 = (a * f - c * d) * nk;
    float o20 = dh_eg * k;
    float o21 = (a * h - b * g) * nk;
    float o22 = (a * e - b * d) * k;

    o->v0.x = o00; o->v0.y = o01; o->v0.z = o02; o->v0.w = 0.0f;
    o->v1.x = o10; o->v1.y = o11; o->v1.z = o12; o->v1.w = 0.0f;
    o->v2.x = o20; o->v2.y = o21; o->v2.z = o22; o->v2.w = 0.0f;

    o->v3.x = -(tx * o00 + ty * o10 + tz * o20);
    o->v3.y = -(tx * o01 + ty * o11 + tz * o21);
    o->v3.z = -(tx * o02 + ty * o12 + tz * o22);
    o->v3.w = 1.0f;
}

// One output row: acc = r.x*m0 + r.y*m1 + r.z*m2 + r.w*m3, which is the
// four COP2 words above.
static void row_times_matrix(bVector4 *out, const bVector4 *r,
                             const bMatrix4 *m)
{
    out->x = r->x * m->v0.x + r->y * m->v1.x + r->z * m->v2.x
             + r->w * m->v3.x;
    out->y = r->x * m->v0.y + r->y * m->v1.y + r->z * m->v2.y
             + r->w * m->v3.y;
    out->z = r->x * m->v0.z + r->y * m->v1.z + r->z * m->v2.z
             + r->w * m->v3.z;
    out->w = r->x * m->v0.w + r->y * m->v1.w + r->z * m->v2.w
             + r->w * m->v3.w;
}

// 0x002426f8. *o = *m2 * *m1 -- each row of m2 transformed by m1.
void bMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2)
{
    bMatrix4 t;

    row_times_matrix(&t.v0, &m2->v0, m1);
    row_times_matrix(&t.v1, &m2->v1, m1);
    row_times_matrix(&t.v2, &m2->v2, m1);
    row_times_matrix(&t.v3, &m2->v3, m1);
    *o = t;
}

// 0x00242770.
void bMulMatrixVec4(bVector4 *o, const bMatrix4 *m, const bVector4 *v)
{
    bVector4 t;

    row_times_matrix(&t, v, m);
    *o = t;
}

// 0x002427b0. w is forced to 1 before the multiply, so the translation row
// applies -- this transforms a point, not a direction.
void bMulMatrixVec3(bVector3 *o, const bMatrix4 *m, const bVector3 *v)
{
    bVector4 in, t;

    in.x = v->x;
    in.y = v->y;
    in.z = v->z;
    in.w = 1.0f;
    row_times_matrix(&t, &in, m);
    o->x = t.x;
    o->y = t.y;
    o->z = t.z;
    o->pad = t.w;
}

// 0x00242808.
void bTransposeMatrix(bMatrix4 *o, const bMatrix4 *m)
{
    bMatrix4 t;

    t.v0.x = m->v0.x; t.v0.y = m->v1.x; t.v0.z = m->v2.x; t.v0.w = m->v3.x;
    t.v1.x = m->v0.y; t.v1.y = m->v1.y; t.v1.z = m->v2.y; t.v1.w = m->v3.y;
    t.v2.x = m->v0.z; t.v2.y = m->v1.z; t.v2.z = m->v2.z; t.v2.w = m->v3.z;
    t.v3.x = m->v0.w; t.v3.y = m->v1.w; t.v3.z = m->v2.w; t.v3.w = m->v3.w;
    *o = t;
}
