// acidfx -- fDeterminant and fInvertMatrix. See acidfx.h.
//
// Generated from the listings by walking their registers, then laid out:
// a[k] is element k of m, row by row. C's left-to-right + and * give the
// listing's own nesting; the brackets are where it pairs otherwise.

#include <string.h>

#include "acidfx.h"

float fDeterminant(const bMatrix4 *m)
{
    float a[16];

    memcpy(a, m, sizeof a);
    return a[3] * a[12] * (a[9] * a[6])
         - a[2] * a[12] * (a[9] * a[7])
         - a[3] * a[12] * (a[10] * a[5])
         + a[1] * a[12] * (a[10] * a[7])
         + a[2] * a[12] * (a[11] * a[5])
         - a[1] * a[12] * (a[11] * a[6])
         - a[3] * a[13] * (a[8] * a[6])
         + a[2] * a[13] * (a[8] * a[7])
         + a[3] * a[13] * (a[10] * a[4])
         - a[0] * a[13] * (a[10] * a[7])
         - a[2] * a[13] * (a[11] * a[4])
         + a[0] * a[13] * (a[11] * a[6])
         + a[3] * a[14] * (a[8] * a[5])
         - a[1] * a[14] * (a[8] * a[7])
         - a[3] * a[14] * (a[9] * a[4])
         + a[0] * a[14] * (a[9] * a[7])
         + a[1] * a[14] * (a[11] * a[4])
         - a[0] * a[14] * (a[11] * a[5])
         - a[2] * a[15] * (a[8] * a[5])
         + a[1] * a[15] * (a[8] * a[6])
         + a[2] * a[15] * (a[9] * a[4])
         - a[0] * a[15] * (a[9] * a[6])
         - a[1] * a[15] * (a[10] * a[4])
         + a[0] * a[15] * (a[10] * a[5]);
}

void fInvertMatrix(bMatrix4 *out, const bMatrix4 *m)
{
    float a[16], o[16], inv;

    memcpy(a, m, sizeof a);
    inv = 1.0f / fDeterminant(m);
    o[0] = inv * (a[6] * a[11] * a[13] - a[7] * a[10] * a[13] + a[7] * a[9] * a[14] -
                  a[5] * a[11] * a[14] - a[6] * a[9] * a[15] + a[5] * a[10] * a[15]);
    o[1] = inv * (a[3] * a[10] * a[13] - a[2] * a[11] * a[13] - a[3] * a[9] * a[14] +
                  a[1] * a[11] * a[14] + a[2] * a[9] * a[15] - a[1] * a[10] * a[15]);
    o[2] = inv * (a[2] * a[7] * a[13] - a[3] * a[6] * a[13] + a[3] * a[5] * a[14] -
                  a[1] * a[7] * a[14] - a[2] * a[5] * a[15] + a[1] * a[6] * a[15]);
    o[3] = inv * (a[3] * a[6] * a[9] - a[2] * a[7] * a[9] - a[3] * a[5] * a[10] +
                  a[1] * a[7] * a[10] + a[2] * a[5] * a[11] - a[1] * a[6] * a[11]);
    o[4] = inv * (a[7] * a[10] * a[12] - a[6] * a[11] * a[12] - a[7] * a[8] * a[14] +
                  a[4] * a[11] * a[14] + a[6] * a[8] * a[15] - a[4] * a[10] * a[15]);
    o[5] = inv * (a[2] * a[11] * a[12] - a[3] * a[10] * a[12] + a[3] * a[8] * a[14] -
                  a[0] * a[11] * a[14] - a[2] * a[8] * a[15] + a[0] * a[10] * a[15]);
    o[6] = inv * (a[3] * a[6] * a[12] - a[2] * a[7] * a[12] - a[3] * a[4] * a[14] +
                  a[0] * a[7] * a[14] + a[2] * a[4] * a[15] - a[0] * a[6] * a[15]);
    o[7] = inv * (a[2] * a[7] * a[8] - a[3] * a[6] * a[8] + a[3] * a[4] * a[10] -
                  a[0] * a[7] * a[10] - a[2] * a[4] * a[11] + a[0] * a[6] * a[11]);
    o[8] = inv * (a[5] * a[11] * a[12] - a[7] * a[9] * a[12] + a[7] * a[8] * a[13] -
                  a[4] * a[11] * a[13] - a[5] * a[8] * a[15] + a[4] * a[9] * a[15]);
    o[9] = inv * (a[3] * a[9] * a[12] - a[1] * a[11] * a[12] - a[3] * a[8] * a[13] +
                  a[0] * a[11] * a[13] + a[1] * a[8] * a[15] - a[0] * a[9] * a[15]);
    o[10] = inv * (a[1] * a[7] * a[12] - a[3] * a[5] * a[12] + a[3] * a[4] * a[13] -
                   a[0] * a[7] * a[13] - a[1] * a[4] * a[15] + a[0] * a[5] * a[15]);
    o[11] = inv * (a[3] * a[5] * a[8] - a[1] * a[7] * a[8] - a[3] * a[4] * a[9] +
                   a[0] * a[7] * a[9] + a[1] * a[4] * a[11] - a[0] * a[5] * a[11]);
    o[12] = inv * (a[6] * a[9] * a[12] - a[5] * a[10] * a[12] - a[6] * a[8] * a[13] +
                   a[4] * a[10] * a[13] + a[5] * a[8] * a[14] - a[4] * a[9] * a[14]);
    o[13] = inv * (a[1] * a[10] * a[12] - a[2] * a[9] * a[12] + a[2] * a[8] * a[13] -
                   a[0] * a[10] * a[13] - a[1] * a[8] * a[14] + a[0] * a[9] * a[14]);
    o[14] = inv * (a[2] * a[5] * a[12] - a[1] * a[6] * a[12] - a[2] * a[4] * a[13] +
                   a[0] * a[6] * a[13] + a[1] * a[4] * a[14] - a[0] * a[5] * a[14]);
    o[15] = inv * (a[1] * a[6] * a[8] - a[2] * a[5] * a[8] + a[2] * a[4] * a[9] -
                   a[0] * a[6] * a[9] - a[1] * a[4] * a[10] + a[0] * a[5] * a[10]);
    memcpy(out, o, sizeof o);
}
