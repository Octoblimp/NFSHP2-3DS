// bmatrix -- bMatrix4 and bMatrix.obj (0x002424f8 .. 0x00242890).
//
// Seven functions: two identities, an affine inverse, three multiplies and a
// transpose. The matrix is row-major, 64 bytes, row i at offset 16i, and the
// convention is row-vector: a point is a row on the LEFT of the matrix, so
// the translation lives in row 3 and `a then b` composes as `a * b`.
//
// That convention is read straight off the VU0 code rather than guessed. The
// vector overload at 0x00242770 broadcasts the *vector's* lanes across the
// matrix's rows --
//
//     out = v.x*m.row0 + v.y*m.row1 + v.z*m.row2 + v.w*m.row3
//
// -- which is `v * m` and nothing else. The matrix-matrix overload at
// 0x002426f8 runs the identical instruction pattern with m2's rows in the
// broadcast slot and m1's rows in the accumulated slot, so it transforms
// each row of m2 by m1: `*o = *m2 * *m1`. The arguments multiply right to
// left. Written up in docs/formats/bmath.md.
#ifndef BMATRIX_H
#define BMATRIX_H

#include "bvector.h"

typedef struct bMatrix4 {
    bVector4 v0, v1, v2, v3;
} bMatrix4;

// 0x002424f8 and 0x00242528 -- the same identity, one built with 128-bit
// integer shuffles and one written scalar. Both ship; both are here because
// callers reference both symbols.
void bIdentity(bMatrix4 *m);
void bOldIdentity(bMatrix4 *m);

// 0x00242578. Adjugate over determinant for the upper 3x3, then
// row3 = -(m.row3 * inv3x3). Not a general 4x4 inverse: it assumes the
// fourth column is (0,0,0,1) and writes that back out.
void bInvertMatrix(bMatrix4 *o, const bMatrix4 *m);

// 0x002426f8. *o = *m2 * *m1 -- see the note above. o may not alias either
// input; the original loads all eight rows up front, so in practice it can,
// but the port makes that explicit with a temporary.
void bMulMatrix(bMatrix4 *o, const bMatrix4 *m1, const bMatrix4 *m2);

// 0x00242770. *o = *v * *m, all four components.
void bMulMatrixVec4(bVector4 *o, const bMatrix4 *m, const bVector4 *v);

// 0x002427b0. The same with w forced to 1, so it is the full affine point
// transform including the translation row. The original stages the vector
// through the stack to set w and then moves sixteen bytes, which is why
// bVector3 is padded.
void bMulMatrixVec3(bVector3 *o, const bMatrix4 *m, const bVector3 *v);

// 0x00242808. Reads all sixteen floats before writing any, so o == m is
// safe.
void bTransposeMatrix(bMatrix4 *o, const bMatrix4 *m);

#endif // BMATRIX_H
