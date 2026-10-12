#ifndef GEOCULL_H
#define GEOCULL_H

// The triangles of a batch no view can show, left unsent (TASKS 46).
//
// A model the cull passes is drawn whole, and a big one is mostly off the
// view: on Azahar's track 12, of what an envmap face drew 72 to 90 per cent
// of the triangles lay wholly outside it, of the mirror's 60 to 75, of the
// race view's 10 to 35. So each batch of a baked mesh (georender_bake) has
// a box round it and one round each GEO_CLUSTER_TRIS of its triangles, in
// their order, which the strips make neighbours. The draw sends a batch
// whole when its box is inside the view, nothing when it is outside, and
// otherwise each run of the clusters that are not outside as one draw.
//
// "Outside" is wholly beyond one of the view's four side planes, x or y
// past +-w, in the model's own space: the planes are rows of the matrix
// the shader is handed (geosolidunif.h). The PICA works in 24-bit floats,
// so a vertex just beyond a plane here can land just inside it there; a
// box is outside only when it is beyond the plane by more than that
// rounding could make up. A cluster left out is one the GPU would clip
// away entirely, so the frame is the same. tools/geocull_check.py runs
// the clusters it leaves out through geosolid.v.pica on the PICA's floats.
//
// Plain C, for the host check as well.

#include <stdint.h>

#define GEO_CLUSTER_TRIS    32
#define GEO_CLUSTER_INDICES (3 * GEO_CLUSTER_TRIS)

typedef struct {
    float lo[3];
    float hi[3];
} GeoCluster;

// The view's side planes, x >= -w, x <= w, y >= -w and y <= w: w's row of
// the matrix plus or minus x's or y's, each with the size of its terms for
// the rounding's margin.
typedef struct {
    float pl[4][4];
    float mag[4][4];            // |w's row| + |x's or y's|
} GeoCullPlanes;

enum {
    GEOCULL_OUT,                // beyond a plane: none of it can show
    GEOCULL_PART,               // across a plane, or near one
    GEOCULL_IN                  // inside every plane
};

// `mvp` as geosolid_model makes it: the projection times the model-view.
void geocull_planes(const float mvp[4][4], GeoCullPlanes* out);

int geocull_box(const GeoCullPlanes* planes, const GeoCluster* box);

// How many boxes a batch of `count` indices has: its own, then one for
// each GEO_CLUSTER_INDICES of them. None for an empty batch.
int geocull_count(int count);

// A batch's boxes into `out`, geocull_count(count) of them: the `count`
// indices at `idx` into vertices of `stride` floats each from `pos`, x y z
// first. Returns how many it wrote.
int geocull_build(const float* pos, int stride, const uint16_t* idx,
                  int count, GeoCluster* out);

#endif
