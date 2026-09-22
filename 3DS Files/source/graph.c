// graph -- Graph::Graph and Graph::GetValue, transcribed from
// 0x00187440 and 0x00187450. See graph.h and docs/formats/car-graph.md.

#include <math.h>

#include "graph.h"

Graph *graph_init(Graph *g, const bVector2 *points, int32_t count)
{
    // 0x00187440: sw a1,0(a0); move v0,a0; sw a2,4(a0). The array is
    // aliased, not copied.
    g->pPoints = points;
    g->NumPoints = count;
    return g;
}

float graph_get_value(Graph *g, float x)
{
    const bVector2 *p = g->pPoints;
    int32_t n = g->NumPoints;
    int32_t i;

    // 0x00187454: slti v0,v1,2. Fewer than two knees is not a curve, and
    // the answer is the first point's y -- read without a bounds check.
    if (n < 2) return p[0].y;

    // 0x00187468 and 0x00187488, both c.le.s: inclusive at each end.
    if (x <= p[0].x) return p[0].y;
    if (p[n - 1].x <= x) return p[n - 1].y;

    for (i = 0; i < n - 1; i++) {
        // 0x001874c4 is c.le.s and 0x001874d8 is c.lt.s -- closed on the
        // left, open on the right.
        if (p[i].x <= x && x < p[i + 1].x) {
            float dx = p[i + 1].x - p[i].x;
            float dy = p[i + 1].y - p[i].y;

            // 0x001874fc: c.lt.s eps,|dx| -- strict, so a dx exactly at
            // the epsilon takes the midpoint.
            if (fabsf(dx) > GRAPH_EPSILON) {
                // 0x0018752c: div.s then mul.s then add.s, in that
                // order.
                return p[i].y + (x - p[i].x) / dx * dy;
            }
            return p[i].y + dy * 0.5f;
        }
    }

    // 0x00187524 reloads 4(a0), which is pPoints[0].y and not the last
    // point's. Unreachable while the array is sorted, because the two
    // early-outs above bracket x -- but the object does it, so the port
    // does.
    return p[0].y;
}
