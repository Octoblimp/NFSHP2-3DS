// emath -- eMathE.obj (0x0011b9a0 .. 0x0011c7b8).
//
// The engine's own matrix layer, sitting on top of bMatrix.obj. Twenty-six
// symbols in 3.6 KB, and everything above it -- the camera, the car sim, the
// AI, the collision code -- is written in terms of these rather than the b*
// ones. It is ported whole because it is small and because the first caller
// (Camera, task 23) already needs eight of them.
//
// Same conventions as bmatrix: row-major, row 3 is the translation, a point
// is a row on the LEFT. Angles are BAMs, 65536 to the turn.
//
// Three things here are traps rather than choices, and the port keeps all
// three. They are written up with addresses in docs/formats/emath.md.
//
//   * eMulMatrix and bMulMatrix take their operands in OPPOSITE orders.
//     eMulMatrix(o, a, b) is o = a * b; bMulMatrix(o, a, b) is o = b * a.
//     The VU0 code differs only in which pair of quadwords is loaded into
//     vf4..vf7 (the broadcast operand) and which into vf8..vf11.
//   * eNormalizedDirection divides by sqrt(dx^2 + dy^2) -- the 2D length of
//     a 3D vector. It is the only normalise in the image written with the
//     accumulator form, the other ~50 all sum three components, and its one
//     caller is dead code. It is ported as it is, bug included.
//   * eInvertRotationMatrix leaves 1.0 out of the corner: it zeroes row3 AND
//     m[3][3], so the result is not a valid transform on its own.
//
// eReflectVector is `jr ra` with no body and no callers. It is declared here
// so the symbol list matches the disc, and it does nothing.
#ifndef EMATH_H
#define EMATH_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

// ------------------------------------------------------------- the globals

// 0x002dc580 and 0x002dc5c0, filled by eMathInit (0x0011b9a0). The zero one
// is bMemSet rather than eZeroMatrix, which is the same 64 bytes.
extern bMatrix4 eMathIdentityMatrix;
extern bMatrix4 eMathZeroMatrix;

void eMathInit(void);

// --------------------------------------------------------------- the basics

// 0x0011ba18 / 0x0011ba68. Identical to bIdentity; kept separate because the
// engine calls this symbol and a reader tracing an address wants to find it.
void eIdentity(bMatrix4 *m);
void eZeroMatrix(bMatrix4 *m);

// 0x0011bab0. *o = *m1 * *m2 -- each row of m1 transformed by m2, so `m1
// then m2` reads left to right. This is the reverse of bMulMatrix's order;
// see the header comment. Aliasing is safe: the original loads all eight
// quadwords before it stores anything, and so does this.
void eMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2);

// 0x0011bb28 / 0x0011bb68. o = v * m. The bVector3 form forces w to 1 first,
// so it moves a point and picks up the translation row.
void eMulVector4(bVector4 *o, const bMatrix4 *m, const bVector4 *v);
void eMulVector3(bVector3 *o, const bMatrix4 *m, const bVector3 *v);

// 0x0011c368. o = transpose(m), all sixteen elements.
void eTransposeMatrix(bMatrix4 *o, const bMatrix4 *m);

// ------------------------------------------------------- building a matrix

// 0x0011c310. Identity with row 3 set to v.
void eCreateTranslationMatrix(bMatrix4 *m, const bVector3 *v);

// 0x0011c048 / 0x0011c110 / 0x0011c1d8. *o = *m * R(bam), the rotation
// applied after m. Each one converts the BAM to radians and takes both sine
// and cosine from eSin, which is why they do not agree with bSinBam to the
// last bit.
void eRotateX(bMatrix4 *o, const bMatrix4 *m, uint16_t bam);
void eRotateY(bMatrix4 *o, const bMatrix4 *m, uint16_t bam);
void eRotateZ(bMatrix4 *o, const bMatrix4 *m, uint16_t bam);

// 0x0011c2a0. *o = *m * T(v).
void eTranslate(bMatrix4 *o, const bMatrix4 *m, const bVector3 *v);

// 0x0011bc68. Rodrigues about an arbitrary axis, which is assumed to be unit
// length already -- nothing here normalises it. Uses bSinBam/bCosBam, not
// eSin. Row 3 is cleared.
void eCreateAxisRotationMatrix(bMatrix4 *m, const bVector3 *axis,
                               uint16_t bam);

// 0x0011bd68. The view matrix: translate(-eye) then the basis built from
// (target - eye) and up. `up` is negated on the way in, which is what puts
// the engine's Z-down world the right way up on screen.
void eCreateLookAtMatrix(bMatrix4 *m, const bVector3 *eye,
                         const bVector3 *target, const bVector3 *up);

// ------------------------------------------------------------- undoing one

// 0x0011c3f0. The affine inverse of a rigid transform: T(-t) * R^T. Wrong
// for anything with scale or shear in it, which is why it is not
// bInvertMatrix.
void eInvertTransformationMatrix(bMatrix4 *o, const bMatrix4 *m);

// 0x0011c6a0. The transpose with the whole fourth column and row cleared --
// including m[3][3], which the header comment warns about.
void eInvertRotationMatrix(bMatrix4 *o, const bMatrix4 *m);

// 0x0011c5d0. Gram-Schmidt from rows 0 and 1: row0 normalised, row2 =
// row0 x row1 normalised, row1 = row2 x row0. Row 3 is cleared.
void eOrthonormalizeMatrix(bMatrix4 *o, const bMatrix4 *m);

// ------------------------------------------------------------------ vectors

// 0x0011b9e0. o = normalize(to - from) -- except that it divides by the 2D
// length. See the header comment; this is the disc's arithmetic.
void eNormalizedDirection(bVector4 *o, const bVector4 *from,
                          const bVector4 *to);

// 0x0011bf48. Empty on the disc, and nothing calls it.
void eReflectVector(bVector4 *o, const bVector4 *v, const bVector4 *n);

// 0x0011bb98. Transform by m with w forced to 1, then divide xyz by the
// resulting w -- the projective divide, with w left alone.
void eRotTransPers(bVector4 *o, const bMatrix4 *m, const bVector4 *v);

// 0x0011bc00. Transform by m with w forced to 1 and return VU0's six clip
// flags for the result: bit 0 is +x, bit 1 -x, bit 2 +y, bit 3 -y, bit 4
// +z, bit 5 -z, each set when the component is outside +/-w.
uint32_t eGetClipFlags(const bVector4 *v, const bMatrix4 *m);

// 0x0011c4e8. Row i of o is v x row i of m. The fourth column and row 3 are
// left untouched, so o must already hold something sensible there.
void eVectorStarMatrix(bMatrix4 *o, const bVector3 *v, const bMatrix4 *m);

// 0x0011bf50. Range reduction and a 9th-order odd polynomial, in float.
float eSin(float radians);

// 0x0011c6e8. Crossing-number point-in-polygon on the xy plane, n vertices,
// implicitly closed. A vertex exactly on a horizontal edge counts once
// because the y test is half-open.
int eIsPointInPoly(const bVector2 *pt, const bVector2 *poly, int n);

#endif
