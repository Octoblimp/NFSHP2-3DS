// edisplay -- see edisplay.h.

#include "edisplay.h"

#include "realtime.h"

int32_t ScreenDisplayOffsets[2][2] = {   // 0x002c79c0
    { 56, 27 },
    { 0, 0 },
};

void eGetScreenDisplayOffsets(int32_t *x, int32_t *y)
{
    int32_t m = GetVideoMode();

    *x = ScreenDisplayOffsets[m][0];
    *y = ScreenDisplayOffsets[m][1];
}

void eSetScreenDisplayOffsets(int32_t x, int32_t y)
{
    int32_t m = GetVideoMode();

    ScreenDisplayOffsets[m][0] = x;
    ScreenDisplayOffsets[m][1] = y;
}
