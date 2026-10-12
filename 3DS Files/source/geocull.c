// The clusters' boxes and their test against the view (geocull.h).

#include <math.h>

#include "geocull.h"

// The margin's share of the terms: a dp4 on the PICA rounds the vertex,
// the matrix and each product and sum to 16 bits of mantissa, some seven
// roundings of 2^-17 at most, 5.3e-5 of the terms; twice that and more.
#define GEOCULL_MARGIN 2e-4f

void geocull_planes(const float mvp[4][4], GeoCullPlanes* out)
{
    static const int   row[4]  = { 0, 0, 1, 1 };
    static const float sign[4] = { 1.0f, -1.0f, 1.0f, -1.0f };
    int                i, j;

    for (i = 0; i < 4; i++) {
        for (j = 0; j < 4; j++) {
            out->pl[i][j]  = mvp[3][j] + sign[i] * mvp[row[i]][j];
            out->mag[i][j] = fabsf(mvp[3][j]) + fabsf(mvp[row[i]][j]);
        }
    }
}

int geocull_box(const GeoCullPlanes* planes, const GeoCluster* box)
{
    float a[3];
    int   res = GEOCULL_IN;
    int   i, k;

    // The largest size of each coordinate in the box, for the margin.
    for (k = 0; k < 3; k++) {
        float lo = fabsf(box->lo[k]);
        float hi = fabsf(box->hi[k]);

        a[k] = lo > hi ? lo : hi;
    }
    for (i = 0; i < 4; i++) {
        const float* p   = planes->pl[i];
        const float* m   = planes->mag[i];
        float        far = p[3];
        float        near = p[3];
        float        margin;

        // The corner furthest along the plane's normal, and the nearest.
        for (k = 0; k < 3; k++) {
            if (p[k] >= 0.0f) {
                far  += p[k] * box->hi[k];
                near += p[k] * box->lo[k];
            } else {
                far  += p[k] * box->lo[k];
                near += p[k] * box->hi[k];
            }
        }
        margin = GEOCULL_MARGIN * (m[0] * a[0] + m[1] * a[1] + m[2] * a[2]
                                   + m[3]);
        if (far < -margin) {
            return GEOCULL_OUT;
        }
        if (!(near >= 0.0f)) {
            res = GEOCULL_PART;
        }
    }
    return res;
}

int geocull_count(int count)
{
    return count > 0
         ? 1 + (count + GEO_CLUSTER_INDICES - 1) / GEO_CLUSTER_INDICES : 0;
}

static void box_empty(GeoCluster* b)
{
    int k;

    for (k = 0; k < 3; k++) {
        b->lo[k] = INFINITY;
        b->hi[k] = -INFINITY;
    }
}

static void box_add(GeoCluster* b, const float* p)
{
    int k;

    for (k = 0; k < 3; k++) {
        if (p[k] < b->lo[k]) {
            b->lo[k] = p[k];
        }
        if (p[k] > b->hi[k]) {
            b->hi[k] = p[k];
        }
    }
}

int geocull_build(const float* pos, int stride, const uint16_t* idx,
                  int count, GeoCluster* out)
{
    int n = geocull_count(count);
    int c, i;

    if (n == 0) {
        return 0;
    }
    box_empty(&out[0]);
    for (c = 1; c < n; c++) {
        int first = (c - 1) * GEO_CLUSTER_INDICES;
        int end   = first + GEO_CLUSTER_INDICES < count
                  ? first + GEO_CLUSTER_INDICES : count;

        box_empty(&out[c]);
        for (i = first; i < end; i++) {
            box_add(&out[c], pos + (long)idx[i] * stride);
        }
        box_add(&out[0], out[c].lo);
        box_add(&out[0], out[c].hi);
    }
    return n;
}
