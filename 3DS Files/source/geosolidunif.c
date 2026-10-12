// geosolidunif -- see geosolidunif.h.

#include "geosolidunif.h"

void geosolid_model(const float projection[4][4], const float modelView[4][4],
                    const float fogRow[4], const float lightVec[3],
                    GeoSolidModel* out)
{
    int i, j;

    // Row i of P M', where M' is the model-view with its last row (0, 0,
    // 0, 1): the view-space position the old shader made had a w of 1.
    for (i = 0; i < 4; i++) {
        for (j = 0; j < 4; j++) {
            float s = projection[i][0] * modelView[0][j]
                      + projection[i][1] * modelView[1][j]
                      + projection[i][2] * modelView[2][j];

            out->mvp[i][j] = j == 3 ? s + projection[i][3] : s;
        }
    }
    // The fog's row the same way: a row vector times M'.
    for (j = 0; j < 4; j++) {
        float s = fogRow[0] * modelView[0][j] + fogRow[1] * modelView[1][j]
                  + fogRow[2] * modelView[2][j];

        out->fog[j] = j == 3 ? s + fogRow[3] : s;
    }
    // L . (M n) = (L M) . n over the upper 3x3, with the normal's 1/127.
    for (j = 0; j < 3; j++) {
        out->light[j] = (lightVec[0] * modelView[0][j]
                         + lightVec[1] * modelView[1][j]
                         + lightVec[2] * modelView[2][j]) * (1.0f / 127.0f);
    }
    out->light[3] = 0.0f;
}

void geosolid_colours(float r, float g, float b, float ambient,
                      float lightClr[4], float ambientClr[4])
{
    const float k = 1.0f / 255.0f;

    lightClr[0]   = r * k;
    lightClr[1]   = g * k;
    lightClr[2]   = b * k;
    lightClr[3]   = 0.0f;
    ambientClr[0] = ambient * k;
    ambientClr[1] = ambient * k;
    ambientClr[2] = ambient * k;
    ambientClr[3] = k;
}
