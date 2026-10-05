// acidfx -- AcidFXE.obj's matrix arithmetic (0x00124bf8 .. 0x001254d0):
// fDeterminant and fInvertMatrix, a general 4x4 inverse by cofactors, and
// hermite_basis (retail 0x00126960, the demo's 0x001254d0).
//
// The view's matrices are the first caller the port has (CalculateViewMatricies
// inverts the two clip-to-screen matrices); the effect system's DoTimeStep
// (acidsys.c) makes each emitter data's two curves with hermite_basis. The
// rain, which shares the object, comes later.
//
// Both are straight-line FPU code, 408 and 1856 bytes of it, with no test on
// the determinant: a singular matrix divides 1 by zero. The sums are the
// image's, term by term and in its order, and so are the products' pairings.
// Written up in docs/formats/eview.md; checked by tools/eview_check.py.

#ifndef ACIDFX_H
#define ACIDFX_H

#include "bmatrix.h"

// 0x00124bf8. The 24 terms of the Leibniz sum, each a pair of pairs.
float fDeterminant(const bMatrix4 *m);

// 0x00124d90. o = m's adjugate times 1 / fDeterminant(m). Each element is
// its cofactor's six products, summed left to right, then scaled.
//
// The listing loads m as it goes and stores o element by element, so an o
// that is m would read some of its own results. The port reads m whole
// first. None of the five callers passes one matrix twice.
void fInvertMatrix(bMatrix4 *o, const bMatrix4 *m);

// 0x00126960 (the demo's 0x001254d0, the same code). A curve's matrix
// from its four control rows `ctrl` at the four keys k0..k3:
// o = H * M * inverse(T) * ctrl, where T's rows are (k^3, k^2, k, 1) of
// each key, M is the rows (0 0 0 1) (1 1 1 1) (0 0 1 0) (3 2 1 0), and H
// is Hermite's, (2 -2 1 1) (-3 3 -2 -1) (0 0 1 0) (1 0 0 0). Each product
// is eMulMatrix, right to left as written: M * inverse(T) first.
void hermite_basis(bMatrix4 *o, const bMatrix4 *ctrl, float k0, float k1,
                   float k2, float k3);

#endif
