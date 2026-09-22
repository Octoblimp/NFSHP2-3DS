// Transcript harness for Graph. Cross-checked by tools/graph_check.py,
// which models the same behaviour from the disassembly at 0x00187440 and
// 0x00187450 without reading this file.
//
// Every fixture float is its own decimal literal, and none is computed
// from another: a sum rounds twice where a literal rounds once, and the
// fixtures are not the thing under test.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "graph.h"

static void hdr(const char *tag, const bVector2 *p, int shown, int n)
{
    int i;
    printf("[%s] n %d\n", tag, n);
    for (i = 0; i < shown; i++)
        printf("  p%d %.9g %.9g\n", i, p[i].x, p[i].y);
}

static void at(Graph *g, float x)
{
    char buf[32];
    snprintf(buf, sizeof buf, "%.9g", x);
    printf("  at %-14s -> %.9g\n", buf, graph_get_value(g, x));
}

// --------------------------------------------------------------- layout

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("sizeof Graph %zu\n", sizeof(Graph));
    printf("off pPoints %zu\n", offsetof(Graph, pPoints));
    printf("off NumPoints %zu\n", offsetof(Graph, NumPoints));
    printf("eps %.9g\n", (float)GRAPH_EPSILON);
    {
        float e = (float)GRAPH_EPSILON;
        unsigned int w;
        memcpy(&w, &e, 4);
        printf("eps bits %08x\n", w);
    }
    printf("half %.9g\n", 0.5f);
}

// ------------------------------------------------------------ scenarios

static const bVector2 kRamp[4] = {
    { 0.0f, 0.0f }, { 1.0f, 10.0f }, { 2.0f, 30.0f }, { 4.0f, -10.0f }
};

static const bVector2 kOne[1] = { { 7.0f, 3.25f } };

static const bVector2 kTwo[2] = { { -2.0f, 1.0f }, { 2.0f, -3.0f } };

static const bVector2 kTight[4] = {
    { 0.0f, 0.0f }, { 1.0f, 4.0f }, { 1.0000005f, 6.0f }, { 3.0f, 8.0f }
};

static const bVector2 kAtEps[4] = {
    { -1.0f, 0.0f }, { 0.0f, 2.0f }, { 9.99999997e-07f, 6.0f },
    { 1.0f, 8.0f }
};

static const bVector2 kSameX[4] = {
    { 0.0f, 0.0f }, { 1.0f, 4.0f }, { 1.0f, 10.0f }, { 2.0f, 12.0f }
};

static const bVector2 kOrder[3] = {
    { 0.0f, 0.0f }, { 3.0f, 7.0f }, { 10.0f, 1.0f }
};

static const bVector2 kUnsorted[4] = {
    { 0.0f, 100.0f }, { 8.0f, 1.0f }, { 2.0f, 2.0f }, { 10.0f, 3.0f }
};

static const bVector2 kNegative[4] = {
    { -8.0f, -4.0f }, { -4.0f, 2.0f }, { -1.0f, -6.0f }, { 0.0f, 0.0f }
};

static const bVector2 kFlat[3] = {
    { 0.0f, 5.0f }, { 10.0f, 5.0f }, { 20.0f, 9.0f }
};

static const bVector2 kDupFront[3] = {
    { 1.0f, 2.0f }, { 1.0f, 8.0f }, { 3.0f, 10.0f }
};

static const bVector2 kUlpOver[4] = {
    { -1.0f, 0.0f }, { 0.0f, 2.0f }, { 1.00000011e-06f, 6.0f },
    { 1.0f, 8.0f }
};

int main(void)
{
    Graph g;

    scenario_layout();

    // Every arm of the walk, on a curve that rises at two rates and then
    // falls.
    hdr("ramp", kRamp, 4, 4);
    graph_init(&g, kRamp, 4);
    at(&g, -5.0f); at(&g, -0.0000001f); at(&g, 0.0f); at(&g, 0.25f);
    at(&g, 0.5f); at(&g, 1.0f); at(&g, 1.5f); at(&g, 2.0f); at(&g, 3.0f);
    at(&g, 3.999f); at(&g, 4.0f); at(&g, 4.0000005f); at(&g, 100.0f);

    // The interior knees. Each belongs to the segment that starts there,
    // so the answer comes through the divide with a zero numerator rather
    // than off the end of the segment before it.
    hdr("knees", kRamp, 4, 4);
    graph_init(&g, kRamp, 4);
    at(&g, 1.0f); at(&g, 2.0f);

    // Fewer than two points: n = 1, not 0, because p[0] is defined and
    // whatever sits in front of the array is not.
    hdr("one point", kOne, 1, 1);
    graph_init(&g, kOne, 1);
    at(&g, -1.0f); at(&g, 7.0f); at(&g, 99.0f);

    hdr("two points", kTwo, 2, 2);
    graph_init(&g, kTwo, 2);
    at(&g, -3.0f); at(&g, -2.0f); at(&g, -1.0f); at(&g, 0.0f);
    at(&g, 1.0f); at(&g, 2.0f); at(&g, 3.0f);

    // A segment narrower than the epsilon: the midpoint of the two y
    // values, and neither endpoint.
    hdr("tight", kTight, 4, 4);
    graph_init(&g, kTight, 4);
    at(&g, 0.5f); at(&g, 1.0f); at(&g, 1.00000025f); at(&g, 1.0000003f);
    at(&g, 2.0f);

    // dx exactly at the epsilon. The test is strict, so this is still the
    // midpoint arm.
    hdr("dx at eps", kAtEps, 4, 4);
    graph_init(&g, kAtEps, 4);
    at(&g, -0.5f); at(&g, 0.0f); at(&g, 5e-07f); at(&g, 9.9e-07f);
    at(&g, 9.99999997e-07f); at(&g, 0.5f);

    // Two knees at the same x. dx is 0, which is inside the epsilon, so
    // the divide is never reached.
    hdr("same x", kSameX, 4, 4);
    graph_init(&g, kSameX, 4);
    at(&g, 0.5f); at(&g, 1.0f); at(&g, 1.5f);

    // The order of the divide and the multiply.
    hdr("order", kOrder, 3, 3);
    graph_init(&g, kOrder, 3);
    at(&g, 1.0f); at(&g, 1.1000000238418579f); at(&g, 2.0f);
    at(&g, 2.9000000953674316f); at(&g, 3.0f); at(&g, 5.0f); at(&g, 7.0f);
    at(&g, 9.0f);

    // Unsorted: bracketed by the early-outs, contained by no segment, so
    // the walk falls off the end and returns p[0].y.
    hdr("unsorted", kUnsorted, 4, 4);
    graph_init(&g, kUnsorted, 4);
    at(&g, 1.0f); at(&g, 5.0f); at(&g, 9.0f);

    hdr("negative", kNegative, 4, 4);
    graph_init(&g, kNegative, 4);
    at(&g, -9.0f); at(&g, -8.0f); at(&g, -6.0f); at(&g, -4.0f);
    at(&g, -2.5f); at(&g, -1.0f); at(&g, -0.5f); at(&g, 0.0f);

    // A flat segment: dy is 0 and the divide still runs.
    hdr("flat", kFlat, 3, 3);
    graph_init(&g, kFlat, 3);
    at(&g, 0.0f); at(&g, 5.0f); at(&g, 10.0f); at(&g, 15.0f);
    at(&g, 20.0f);

    // NumPoints smaller than the array: everything past it is invisible,
    // including a knee that would have bracketed the sample.
    hdr("short count", kRamp, 4, 2);
    graph_init(&g, kRamp, 2);
    at(&g, -1.0f); at(&g, 0.5f); at(&g, 1.0f); at(&g, 1.5f); at(&g, 3.0f);

    // The count's width, stored and read back. Nothing else here can tell
    // a 32-bit NumPoints from a 16-bit one: the offsets and the sizeof
    // come out the same on a host whose pointer forces the alignment, and
    // no curve above has more than four knees. These never index
    // anything.
    {
        static const int32_t kCounts[5] = {
            70000, -70000, 32768, 2147483647, -2147483648
        };
        int i;
        printf("[count width] n 0\n");
        for (i = 0; i < 5; i++) {
            graph_init(&g, kRamp, kCounts[i]);
            printf("  store %-12d -> %d\n", kCounts[i], (int)g.NumPoints);
        }
    }

    // A duplicate x at the FRONT of the array, sampled exactly on it. The
    // low early-out is `x <= p[0].x`; made strict it misses, and the walk
    // then skips segment 0 -- whose right edge is the same x -- and
    // answers off segment 1. Anywhere else a strict miss lands on a
    // segment with a zero numerator and interpolates back to the same
    // point.
    hdr("dup front", kDupFront, 3, 3);
    graph_init(&g, kDupFront, 3);
    at(&g, 0.0f); at(&g, 1.0f); at(&g, 2.0f); at(&g, 3.0f); at(&g, 4.0f);

    // dx one ulp above the epsilon: 0x358637be against the image's
    // 0x358637bd. The real code divides; an epsilon one ulp higher takes
    // the midpoint.
    hdr("dx one ulp over", kUlpOver, 4, 4);
    graph_init(&g, kUlpOver, 4);
    at(&g, 0.0f); at(&g, 5e-07f); at(&g, 1.0000001e-06f);

    return 0;
}
