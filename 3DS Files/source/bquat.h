// bquat -- bQuaternion and bQuaternion.obj (0x002411f0 .. 0x00241bc8).
//
// Nine functions and one initialiser. Two of the nine are duplicates in the
// mathematical sense and not in the bitwise one: the library ships two ways
// of building a matrix from a quaternion and two ways of building a
// quaternion from a matrix, and each pair differs in the order it adds
// float32s. Both of each pair have callers, so both are here.
//
//   bQuaternionGetMatrix  0x002414b0   m00 = 1 - (yy2 + zz2)
//   bQuaternionToMatrix   0x00241800   m00 = (1 - yy2) - zz2
//
//   bQuaternionFromMatrix 0x002411f0   trace test through the soft-double
//                                      helpers, s != 0 likewise
//   bMatrixToQuaternion   0x002418c0   same algorithm, but the s != 0 test
//                                      is a plain c.eq.s
//
// C has no overloading, so the two that were C++ methods pick up a prefix.
// The four free functions below kept their names; nothing else ported so far
// claims them (bvector.h spells its own as bNormalize2, bLengthFix3 and so
// on).
//
// Written up in docs/formats/bmath.md.
#ifndef BQUAT_H
#define BQUAT_H

#include "bmatrix.h"

typedef struct bQuaternion {
    float x, y, z, w;
} bQuaternion;

// 0x00315290. Zero in the ELF image and filled with (0, 0, 0, 1) at startup
// by _GLOBAL_$I$bIdentityQuaternion (0x00241ba0), because the PS2 toolchain
// could not constant-fold a C++ constructor. C can, so it is static here --
// the same way bvector.c folds bVector3FLT_MAX (0x00315280) away.
extern const bQuaternion bIdentityQuaternion;

// 0x00241728. sqrtf(((x*x + y*y) + z*z) + w*w) -- the sum is accumulated in
// the x lane of a VU0 register in that order.
float bLength(const bQuaternion *q);

// 0x00241758. One reciprocal square root, then all four lanes scaled by it.
// There is no zero guard: a zero quaternion comes back as NaN, exactly as on
// the hardware. Returns o.
bQuaternion *bNormalize(bQuaternion *o, const bQuaternion *q);

// 0x002416f0. Negates x, y, z and copies w. Returns o.
bQuaternion *bConjugate(bQuaternion *o, const bQuaternion *q);

// 0x00241798. The Hamilton product *o = *a * *b, with the vector part built
// as a*b.w + (b*a.w + (a x b)) -- that grouping is the VU0 schedule and it
// is what decides the last bit. Returns o.
bQuaternion *bMult(bQuaternion *o, const bQuaternion *a, const bQuaternion *b);

// 0x00241570. Spherical linear interpolation. Falls back to a plain lerp of
// the two quaternions (no renormalise) when 1 - |cos| <= 0.05, and flips the
// sign of a's weight when the two point away from each other, so it always
// takes the short way round. The angles run through bASin and bSinBam, so
// the interpolation is quantised to 1/65536 of a turn.
void bSlerp(bQuaternion *o, const bQuaternion *a, const bQuaternion *b,
            float t);

// 0x002414b0 and 0x00241800. Both write a full 4x4 with row and column 3 set
// to (0, 0, 0, 1); see the note above for how they differ.
void bQuaternionGetMatrix(const bQuaternion *q, bMatrix4 *m);
void bQuaternionToMatrix(bMatrix4 *m, const bQuaternion *q);

// 0x002411f0 and 0x002418c0. Shepperd's method: the trace branch when the
// trace is positive, otherwise the largest diagonal element leads.
void bQuaternionFromMatrix(bQuaternion *q, const bMatrix4 *m);
void bMatrixToQuaternion(bQuaternion *q, const bMatrix4 *m);

#endif // BQUAT_H
