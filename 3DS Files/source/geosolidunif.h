// geosolidunif -- what geosolid.v.pica and geolit.v.pica are handed for a
// model (TASKS 46).
//
// The shaders take the model-view and the projection as one matrix, and
// the fog's row and the light's direction in the model's own space, so a
// vertex costs 17 instructions where it cost 31. These are the products,
// made once a model on the CPU. Free of <3ds.h>, so tools/geosolid_check.py
// builds it for the host and runs the shaders on what it makes.
//
// Matrices are rows, each x, y, z, w: citro3d's C3D_Mtx read through its
// fields. The model-view's last row is taken as (0, 0, 0, 1), as the
// shader it replaced took the view-space position's w.

#ifndef GEOSOLIDUNIF_H
#define GEOSOLIDUNIF_H

typedef struct {
    float mvp[4][4];    // the projection times the model-view
    float fog[4];       // the fog's row times the model-view
    float light[4];     // the light's direction in the model's space / 127
} GeoSolidModel;

// For a model drawn through `projection` and `modelView`: `fogRow` is the
// view-space row whose dot with the view-space position is the fog's s
// (georender.c's fog_row), and `lightVec` the unit direction towards the
// light in view space.
void geosolid_model(const float projection[4][4], const float modelView[4][4],
                    const float fogRow[4], const float lightVec[3],
                    GeoSolidModel* out);

// The light's colour and the ambient as the shader takes them: over 255,
// the colour's w 0 and the ambient's 1/255, so the vertex's alpha comes
// out over 255.
void geosolid_colours(float r, float g, float b, float ambient,
                      float lightClr[4], float ambientClr[4]);

#endif
