// spline -- see spline.h.

#include "spline.h"

#include <stddef.h>

#include "bmath.h"
#include "bmem.h"
#include "eefpu.h"

// GetControlPoint's answer past either end of an EXTRAPOLATE spline,
// retail's 0x003341a0.
static bVector3 SplineExtrapolated;

Spline *spline_init(Spline *s, SplineType type, int32_t n, bVector3 *points,
                    int32_t tableSize)
{
    s->Type = type;
    s->NumControlPoints = n;
    s->Dirty = 1;
    s->TableSize = tableSize;
    s->pControlPoints = points;
    s->ControlPointBufferSize = n;
    s->Length = 0.0f;
    s->pCalTable = NULL;
    s->pControlPointArray = NULL;
    return s;
}

void spline_destroy(Spline *s, int32_t flags)
{
    if (s->pControlPointArray != NULL)
        bFree(s->pControlPointArray);
    if (s->pCalTable != NULL)
        bFree(s->pCalTable);
    if (flags & 1)
        bFree(s);
}

// a*k + b, lane by lane, as VU0's vmulx then vadd.
static void scale_add(bVector3 *o, const bVector3 *a, float k,
                      const bVector3 *b)
{
    o->x = a->x * k + b->x;
    o->y = a->y * k + b->y;
    o->z = a->z * k + b->z;
    o->pad = a->pad * k + b->pad;
}

const bVector3 *spline_get_control_point(const Spline *s, float t)
{
    const bVector3 *cv = s->pControlPoints;
    int32_t n = s->NumControlPoints;
    float last;

    if (s->Type == SPLINE_LOOP)
        last = (float)n;
    else if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)
        last = (float)(n - 1);
    else
        last = 0.0f;

    switch (s->Type) {
    case SPLINE_LOOP:
        t = bFMod(t, last);
        break;
    case SPLINE_CLAMP:
        if (t < 0.0f)
            t = 0.0f;
        else if (last < t)
            t = last;
        break;
    case SPLINE_EXTRAPOLATE:
        if (t < 0.0f) {
            bVector3 d;

            d.x = cv[1].x - cv[0].x;
            d.y = cv[1].y - cv[0].y;
            d.z = cv[1].z - cv[0].z;
            d.pad = cv[1].pad - cv[0].pad;
            scale_add(&SplineExtrapolated, &d, t, &cv[0]);
            return &SplineExtrapolated;
        }
        if (last < t) {
            const bVector3 *e = &cv[n - 1];
            bVector3 d;

            d.x = e->x - e[-1].x;
            d.y = e->y - e[-1].y;
            d.z = e->z - e[-1].z;
            d.pad = e->pad - e[-1].pad;
            scale_add(&SplineExtrapolated, &d, t - last, e);
            return &SplineExtrapolated;
        }
        break;
    default:
        break;
    }
    return &cv[ee_trunc_w(t)];
}

void spline_evaluate(const Spline *s, bVector3 *o, float t, float c0,
                     float c1, float c2, float c3)
{
    const bVector3 *p;
    bVector3 acc;

    p = spline_get_control_point(s, t - 1.0f);
    acc.x = p->x * c0;
    acc.y = p->y * c0;
    acc.z = p->z * c0;
    acc.pad = p->pad * c0;
    p = spline_get_control_point(s, t);
    scale_add(&acc, p, c1, &acc);
    p = spline_get_control_point(s, t + 1.0f);
    scale_add(&acc, p, c2, &acc);
    p = spline_get_control_point(s, t + 2.0f);
    scale_add(&acc, p, c3, &acc);
    *o = acc;
}

void spline_get_point(const Spline *s, bVector3 *o, float t)
{
    float base = (float)ee_trunc_w(t);
    float u, u2, u3, c0, c1, c2, c3;

    if (t < base)
        base = base - 1.0f;
    u = t - base;
    u2 = u * u;
    u3 = u2 * u;
    // In the image's order: each weight is built up from u2 and u3 and
    // halved last.
    c3 = (u3 - u2) * 0.5f;
    c0 = (((u2 + u2) - u3) - u) * 0.5f;
    c1 = ((u3 * 3.0f - u2 * 5.0f) + 2.0f) * 0.5f;
    c2 = ((u2 * 4.0f - u3 * 3.0f) + u) * 0.5f;
    spline_evaluate(s, o, base, c0, c1, c2, c3);
}
