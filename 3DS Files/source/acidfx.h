// acidfx -- AcidFXE.obj's matrix arithmetic (0x00124bf8 .. 0x001254d0):
// fDeterminant and fInvertMatrix, a general 4x4 inverse by cofactors.
//
// The view's matrices are the first caller the port has (CalculateViewMatricies
// inverts the two clip-to-screen matrices); the effects that share the
// object, the rain and the hermite curves, come later.
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

#endif
