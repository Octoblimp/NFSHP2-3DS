// bquat -- bQuaternion.obj (0x002411f0 .. 0x00241bc8).
//
// Half of this object is VU0 macro mode and the other half is scalar FPU,
// and the split matters: the VU code fixes the order the four lanes are
// summed in (always x, then y, then z, then w, accumulated in the x lane),
// and the scalar code fixes the order the matrix conversions add their
// terms. Neither order is the obvious one, and float32 addition is not
// associative, so both are transcribed rather than tidied.
//
// One deliberate divergence: the VU's VRSQRT is a hardware estimate, not a
// correctly rounded reciprocal square root. bNormalize uses 1.0f / sqrtf()
// here, which is closer to the truth than the PS2 was. Nothing else in the
// object leans on VU precision.
//
// docs/formats/bmath.md has the decode with an address for every rule.
#include "bquat.h"

#include "bmath.h"

#include <math.h>
#include <stdint.h>

// 0x00315290. Runtime-initialised on the PS2 because that toolchain could
// not constant-fold a C++ constructor; static here.
const bQuaternion bIdentityQuaternion = { 0.0f, 0.0f, 0.0f, 1.0f };

// 0x00241728.
float bLength(const bQuaternion *q)
{
    float n = ((q->x * q->x + q->y * q->y) + q->z * q->z) + q->w * q->w;

    return sqrtf(n);
}

// 0x00241758. No zero guard in the original and none here.
bQuaternion *bNormalize(bQuaternion *o, const bQuaternion *q)
{
    float n = ((q->x * q->x + q->y * q->y) + q->z * q->z) + q->w * q->w;
    float k = 1.0f / sqrtf(n);

    o->x = q->x * k;
    o->y = q->y * k;
    o->z = q->z * k;
    o->w = q->w * k;
    return o;
}

// 0x002416f0.
bQuaternion *bConjugate(bQuaternion *o, const bQuaternion *q)
{
    float w = q->w;

    o->x = -q->x;
    o->y = -q->y;
    o->z = -q->z;
    o->w = w;
    return o;
}

// 0x00241798. *o = *a * *b.
//
// The vector part is grouped the way the VU schedules it: the cross product
// is folded into b*a.w first, and a*b.w is added to that sum, not the other
// way round. The scalar w falls out of a separate FPU chain and is stored
// last, over the w lane the quadword store has just written.
bQuaternion *bMult(bQuaternion *o, const bQuaternion *a, const bQuaternion *b)
{
    float cx = a->y * b->z - a->z * b->y;
    float cy = a->z * b->x - a->x * b->z;
    float cz = a->x * b->y - a->y * b->x;

    float dot = (a->x * b->x + a->y * b->y) + a->z * b->z;
    float w   = a->w * b->w - dot;

    float tx = b->x * a->w + cx;
    float ty = b->y * a->w + cy;
    float tz = b->z * a->w + cz;

    o->x = a->x * b->w + tx;
    o->y = a->y * b->w + ty;
    o->z = a->z * b->w + tz;
    o->w = w;
    return o;
}

// gp-26976 = 0x00322290, 0x3d4ccccd.
#define SLERP_EPS 0.0500000007f

// 0x00241570.
//
// Three things here are easy to read past. The interpolation parameter is
// turned into a binary angle with a truncating cast, so a slerp is quantised
// to 1/65536 of a turn and the endpoints are not exactly a and b. The
// short-way-round fix flips the sign of the weight on a only, leaving the
// weight on b alone, which is what makes the result track b when the two
// inputs are more than a quarter turn apart.
//
// And the epsilon test is load-bearing, not an optimisation. bASin indexes
// bASinTable by (x * 65536) walked down through eleven octaves, and an
// argument above 1 indexes past the end of it -- the table is 209 entries
// and the walk would ask for thousands. The only thing keeping |cos| under
// 0.95 is that both quaternions are unit length. Callers must normalise.
void bSlerp(bQuaternion *o, const bQuaternion *a, const bQuaternion *b,
            float t)
{
    float cs = ((a->x * b->x + a->y * b->y) + a->z * b->z) + a->w * b->w;
    float ka, kb;

    if (SLERP_EPS < 1.0f - fabsf(cs)) {
        int32_t theta = (16384 - bASin(fabsf(cs))) & 0xffff;
        float   sn    = bSinBam((uint16_t)theta);
        float   th    = (float)theta;

        ka = bSinBam((uint16_t)(int32_t)((1.0f - t) * th)) / sn;
        kb = bSinBam((uint16_t)(int32_t)(t * th)) / sn;
    } else {
        // A plain lerp of the components with no renormalise, which is only
        // all right because the two are nearly parallel here.
        ka = 1.0f - t;
        kb = t;
    }

    if (cs < 0.0f) {
        ka = -ka;
    }

    o->x = b->x * kb + a->x * ka;
    o->y = b->y * kb + a->y * ka;
    o->z = b->z * kb + a->z * ka;
    o->w = b->w * kb + a->w * ka;
}

// 0x002414b0. Sums the two squares that leave each diagonal entry, then
// subtracts the sum from 1.
void bQuaternionGetMatrix(const bQuaternion *q, bMatrix4 *m)
{
    float x2 = q->x + q->x, y2 = q->y + q->y, z2 = q->z + q->z;

    float xx2 = q->x * x2, yy2 = q->y * y2, zz2 = q->z * z2;
    float wx2 = q->w * x2, wy2 = q->w * y2, wz2 = q->w * z2;
    float xy2 = q->x * y2, xz2 = q->x * z2, yz2 = q->y * z2;

    float sxy = xx2 + yy2;
    float sxz = xx2 + zz2;
    float syz = yy2 + zz2;

    m->v0.x = 1.0f - syz; m->v0.y = xy2 - wz2;  m->v0.z = xz2 + wy2;
    m->v1.x = xy2 + wz2;  m->v1.y = 1.0f - sxz; m->v1.z = yz2 - wx2;
    m->v2.x = xz2 - wy2;  m->v2.y = yz2 + wx2;  m->v2.z = 1.0f - sxy;

    m->v0.w = 0.0f;
    m->v1.w = 0.0f;
    m->v2.w = 0.0f;
    m->v3.x = 0.0f; m->v3.y = 0.0f; m->v3.z = 0.0f; m->v3.w = 1.0f;
}

// 0x00241800. The same matrix, subtracting the two squares one at a time.
// The rounding differs from bQuaternionGetMatrix in the last bit and both
// have callers, so both ship.
void bQuaternionToMatrix(bMatrix4 *m, const bQuaternion *q)
{
    float x2 = q->x + q->x, y2 = q->y + q->y, z2 = q->z + q->z;
    float w2 = q->w + q->w;

    float xx2 = x2 * q->x, yy2 = y2 * q->y, zz2 = z2 * q->z;
    float wx2 = w2 * q->x, wy2 = w2 * q->y, wz2 = w2 * q->z;
    float xy2 = x2 * q->y, xz2 = x2 * q->z, yz2 = y2 * q->z;

    float ax = 1.0f - xx2;
    float ay = 1.0f - yy2;

    m->v0.x = ay - zz2;  m->v0.y = xy2 - wz2; m->v0.z = xz2 + wy2;
    m->v1.x = xy2 + wz2; m->v1.y = ax - zz2;  m->v1.z = yz2 - wx2;
    m->v2.x = xz2 - wy2; m->v2.y = yz2 + wx2; m->v2.z = ax - yy2;

    m->v0.w = 0.0f;
    m->v1.w = 0.0f;
    m->v2.w = 0.0f;
    m->v3.x = 0.0f; m->v3.y = 0.0f; m->v3.z = 0.0f; m->v3.w = 1.0f;
}

// Shepperd's method, shared by 0x002411f0 and 0x002418c0.
//
// The two originals are the same algorithm instruction for instruction; the
// only difference is that the constructor spells the s != 0 test through the
// soft-double helpers and bMatrixToQuaternion uses a plain c.eq.s. That is
// the same predicate for a float, so one function serves for both.
//
// The sixteen floats go to a flat array first, which is what the original
// does too -- it has to index the matrix by a computed row and column.
static void shepperd(bQuaternion *q, const bMatrix4 *m)
{
    // 0x002a3060, read out of the ELF rather than assumed.
    static const int next[3] = { 1, 2, 0 };

    float a[16];
    float trace;

    a[0]  = m->v0.x; a[1]  = m->v0.y; a[2]  = m->v0.z; a[3]  = m->v0.w;
    a[4]  = m->v1.x; a[5]  = m->v1.y; a[6]  = m->v1.z; a[7]  = m->v1.w;
    a[8]  = m->v2.x; a[9]  = m->v2.y; a[10] = m->v2.z; a[11] = m->v2.w;
    a[12] = m->v3.x; a[13] = m->v3.y; a[14] = m->v3.z; a[15] = m->v3.w;

    trace = (a[0] + a[5]) + a[10];

    if (trace > 0.0f) {
        float s = sqrtf(trace + 1.0f);
        float k;

        q->w = s * 0.5f;
        k = 0.5f / s;
        q->x = (a[6] - a[9]) * k;   // m12 - m21
        q->y = (a[8] - a[2]) * k;   // m20 - m02
        q->z = (a[1] - a[4]) * k;   // m01 - m10
    } else {
        int   i = (a[0] < a[5]) ? 1 : 0;
        int   j, k;
        float s, q4[4];

        if (a[i * 5] < a[10]) {
            i = 2;
        }
        j = next[i];
        k = next[j];

        s = sqrtf((a[i * 5] - (a[j * 5] + a[k * 5])) + 1.0f);
        q4[i] = s * 0.5f;
        // Dead, and worth knowing it is dead. s == 0 means
        // m[i][i] + 1 == m[j][j] + m[k][k], and since i indexes the largest
        // diagonal that forces m[i][i] >= 1, hence a trace of 2*m[i][i] + 1
        // >= 3 -- which took the branch above. Kept because it is in the
        // original, and because a caller with a NaN in the matrix is better
        // off not dividing.
        if (s != 0.0f) {
            s = 0.5f / s;
        }
        q4[3] = (a[j * 4 + k] - a[k * 4 + j]) * s;
        q4[j] = (a[i * 4 + j] + a[j * 4 + i]) * s;
        q4[k] = (a[i * 4 + k] + a[k * 4 + i]) * s;

        q->x = q4[0];
        q->y = q4[1];
        q->z = q4[2];
        q->w = q4[3];
    }
}

// 0x002411f0, the bQuaternion(const bMatrix4&) constructor.
void bQuaternionFromMatrix(bQuaternion *q, const bMatrix4 *m)
{
    shepperd(q, m);
}

// 0x002418c0.
void bMatrixToQuaternion(bQuaternion *q, const bMatrix4 *m)
{
    shepperd(q, m);
}
