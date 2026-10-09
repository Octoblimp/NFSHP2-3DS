// helisheet -- see helisheet.h.

#include "helisheet.h"

#include <math.h>
#include <stddef.h>

#include "bchunk.h"
#include "eefpu.h"
#include "p32.h"

HeliSheet *TheHeliSheet;

// Corner i, 16 bytes on from the last; past the fourth it runs on into the
// next polygon, as the image's does.
static const float *corner(const HeliPoly *p, int32_t i)
{
    return (const float *)(const void *)((const uint8_t *)p + 16 * i);
}

// HeliPoly::PointInPoly(bVector2 *), 0x001eb6a8. Outside the x range is
// outside. Then each edge, in order, to the next corner (the last to the
// first): a point to the edge's left (a cross product above 0) is outside.
// A count of 0 or less holds every point in range.
static int32_t helipoly_point_in_poly(const HeliPoly *p, const bVector2 *pt)
{
    float   x = pt->x, y;
    int32_t n, i;

    if (x < p->MinX || p->MaxX < x)
        return 0;
    n = p->NumPoints;
    y = pt->y;
    for (i = 0; i < n; i++) {
        const float *a = corner(p, i);
        const float *b = corner(p, (i + 1) % n);
        float        dx = x - a[0];
        float        dy = y - a[1];

        if ((b[1] - a[1]) * dx - (b[0] - a[0]) * dy > 0.0f)
            return 0;
    }
    return 1;
}

// HeliPoly::ZValue(bVector2 *), 0x001eb840: the height of the polygon's
// plane at the point. A triangle's plane is its own. A quad is split on
// the diagonal from the third corner to the first, and the point's side of
// it picks the half: P0 P1 P2 on the right of it or on it, P2 P3 P0 on the
// left (or for a NaN). The normal is the two edges' cross product
// (vopmula/vopmsub), scaled by the VU's reciprocal root over
// (x*x + y*y) + z*z; the plane goes through the first corner whichever
// half it is.
static float helipoly_z_value(const HeliPoly *p, const bVector2 *pt)
{
    const float *a, *b, *c;
    float        x = pt->x, y = pt->y;
    float        e1[3], e2[3], n[3], q, d;

    if (p->NumPoints == 3) {
        a = p->P0;
        b = p->P1;
        c = p->P2;
    } else {
        float side = (p->P0[1] - p->P2[1]) * (x - p->P2[0])
                   - (p->P0[0] - p->P2[0]) * (y - p->P2[1]);

        if (side <= 0.0f) {
            a = p->P0;
            b = p->P1;
            c = p->P2;
        } else {
            a = p->P2;
            b = p->P3;
            c = p->P0;
        }
    }
    e1[0] = b[0] - a[0];
    e1[1] = b[1] - a[1];
    e1[2] = b[2] - a[2];
    e2[0] = c[0] - a[0];
    e2[1] = c[1] - a[1];
    e2[2] = c[2] - a[2];
    n[0] = e1[1] * e2[2] - e2[1] * e1[2];
    n[1] = e1[2] * e2[0] - e2[2] * e1[0];
    n[2] = e1[0] * e2[1] - e2[0] * e1[1];
    q = 1.0f / sqrtf((n[0] * n[0] + n[1] * n[1]) + n[2] * n[2]);
    n[0] *= q;
    n[1] *= q;
    n[2] *= q;
    d = (p->P0[0] * n[0] + p->P0[1] * n[1]) + p->P0[2] * n[2];
    return (d - (n[0] * x + n[1] * y)) / n[2];
}

static HeliPoly *polys(const HeliSheet *s)
{
    return (HeliPoly *)p32_ptr(s->Polys);
}

// The image reads the count and the recent three with `lh`.
int32_t helisheet_find_z_value(HeliSheet *s, const bVector2 *pt, float *z,
                               uint32_t *flags)
{
    HeliPoly *poly = polys(s);
    int32_t   found = -1, slot = -1, i;

    if (s->NumPolys == 0)
        return 0;
    for (i = 0; i < 3; i++) {
        int32_t k = s->Recent[i];

        if (helipoly_point_in_poly(&poly[k], pt)) {
            found = k;
            slot = i;
            break;
        }
    }
    if (found < 0) {
        float   x = pt->x;
        int32_t b, start, k;

        // `cvt.w.s`, then pmaxw with 0 and pminw with 255.
        b = ee_trunc_w((x - s->MinX) / (s->MaxX - s->MinX) * 256.0f);
        if (b < 0)
            b = 0;
        if (b > 255)
            b = 255;
        start = s->Bucket[b];
        for (k = start; k < s->NumPolys && poly[k].MinX <= x; k++) {
            if (helipoly_point_in_poly(&poly[k], pt)) {
                found = k;
                break;
            }
        }
        if (found < 0) {
            for (k = start - 1; k >= 0 && x - s->MaxWidth <= poly[k].MinX;
                 k--) {
                if (helipoly_point_in_poly(&poly[k], pt)) {
                    found = k;
                    break;
                }
            }
        }
        if (found < 0)
            return 0;
    }
    if (z != NULL)
        *z = helipoly_z_value(&poly[found], pt);
    if (flags != NULL)
        *flags = poly[found].Flags;
    // To the front of the three: the ones before its slot (all three when
    // it was not one of them, the last dropping off) move down one.
    if (slot < 0)
        slot = 2;
    for (i = slot - 1; i >= 0; i--)
        s->Recent[i + 1] = s->Recent[i];
    s->Recent[0] = (int16_t)found;
    return 1;
}

// The first child's size takes `v` to eight short of the second's header:
// its size is at 12 and its data at 16, rounded up to 16 for the
// polygons. The padding comes off the size, and `srl` by 6 is the count.
int loader_heli_sheet(uint8_t *chunk)
{
    uint8_t   *d, *v, *p;
    HeliSheet *s;
    uint32_t   size;

    if (bchunk_u32(chunk) != HELISHEET_CHUNK_ID)
        return 0;
    d = chunk + 8;
    s = (HeliSheet *)(void *)(d + 8);
    TheHeliSheet = s;
    v = d + bchunk_u32(d + 4);
    p = (uint8_t *)(((uintptr_t)v + 31) & ~(uintptr_t)15);
    size = bchunk_u32(v + 12);
    s->Polys = p32_of(p);
    size -= (uint32_t)(p - (v + 16));
    s->NumPolys = (int16_t)(size >> 6);
    return 1;
}

int unloader_heli_sheet(uint8_t *chunk)
{
    if (bchunk_u32(chunk) != HELISHEET_CHUNK_ID)
        return 0;
    TheHeliSheet = NULL;
    return 1;
}
