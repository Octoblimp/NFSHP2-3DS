#pragma once
#include <stdio.h>

#include "texpack.h"

// The scroll transcript line the two texture harnesses share.
//
// tools/texsrc_check.py diffs texpack_test's and texsrc_test's transcripts
// line for line, so these have to be byte-identical between the two; keeping
// the format in one header is cheaper than keeping two copies in step.
//
// One line per scrolling texture:
//
//     scroll <index> <name> <type> <s> <t> <step> [<du> <dv>] x SCROLL_TIMES
//
// The samples matter more than the parsed fields. TextureInfo::GetScroll
// (0x00100a60) truncates towards zero twice for a type-2 texture, and a port
// that reads the fields correctly and rounds instead of truncating produces
// exactly the same six numbers and a different animation.
//
// The times are deliberately a mix: 0 (the cold-start case), two that fall
// between type-2 steps, and three far enough out that the fractional part has
// wrapped many times over.
static const float SCROLL_TIMES[] = {
    0.0f, 0.1f, 1.0f, 7.3f, 100.0f
};
#define SCROLL_NTIMES ((int)(sizeof(SCROLL_TIMES) / sizeof(SCROLL_TIMES[0])))

static void print_scroll_line(uint32_t index, const TexInfo* ti)
{
    if (ti->scrollType == 0) return;

    printf("scroll %u %s %d %.6f %.6f %.6f", index, ti->name,
           (int)ti->scrollType, ti->scrollS, ti->scrollT, ti->scrollStep);
    for (int i = 0; i < SCROLL_NTIMES; i++) {
        float du = 0.0f, dv = 0.0f;
        texpack_scroll(ti, SCROLL_TIMES[i], &du, &dv);
        printf(" %.6f %.6f", du, dv);
    }
    printf("\n");
}
