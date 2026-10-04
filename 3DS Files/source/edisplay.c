// edisplay -- see edisplay.h.

#include "edisplay.h"

#include "realtime.h"

int32_t ScreenDisplayOffsets[2][2] = {   // 0x002c79c0
    { 56, 27 },
    { 0, 0 },
};

int32_t WaitBufferSwapTime;     // gp-24456
int32_t VifTime;                // gp-24452

// 16.16 to milliseconds, 0x37800000.
#define EDISPLAY_FIX_MS  (1.0f / 65536.0f)

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

float GetWaitForBufferSwapTime(void)
{
    return (float)WaitBufferSwapTime * EDISPLAY_FIX_MS;
}

float GetVifTime(void)
{
    return (float)VifTime * EDISPLAY_FIX_MS;
}
