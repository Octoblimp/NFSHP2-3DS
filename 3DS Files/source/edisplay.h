// edisplay -- the screen's display offsets, per video mode.
//
// ScreenDisplayOffsets (0x002c79c0) holds an x and a y for each of the
// two video modes, PAL's (56, 27) and NTSC's (0, 0) on the disc. The
// display calibration screen moves them, and its defaults read them.

#ifndef EDISPLAY_H
#define EDISPLAY_H

#include <stdint.h>

extern int32_t ScreenDisplayOffsets[2][2];

// eGetScreenDisplayOffsets, 0x00105728: the current mode's (GetVideoMode).
void eGetScreenDisplayOffsets(int32_t *x, int32_t *y);

// 0x001056d8: the current mode's set.
void eSetScreenDisplayOffsets(int32_t x, int32_t y);

#endif
