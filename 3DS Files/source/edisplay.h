// edisplay -- the screen's display offsets, per video mode, and the
// frame's two display times.
//
// ScreenDisplayOffsets (0x002c79c0) holds an x and a y for each of the
// two video modes, PAL's (56, 27) and NTSC's (0, 0) on the disc. The
// display calibration screen moves them, and its defaults read them.
//
// WaitBufferSwapTime and VifTime are milliseconds in 16.16, from
// bGetFixTickerDifference. eDisplayFrame times its wait for the GPU
// (eWaitUntilRenderingDone) into the first (0x00113e00), and
// ServiceRenderStageQueue the VIF's frame into the second (0x001119f4).
// CalculateFrameRate reads both (docs/formats/frame-profiler.md). On the
// 3DS, main.c sets them from C3D_FrameBegin's wait and citro3d's GPU time.

#ifndef EDISPLAY_H
#define EDISPLAY_H

#include <stdint.h>

extern int32_t ScreenDisplayOffsets[2][2];
extern int32_t WaitBufferSwapTime;      // gp-24456
extern int32_t VifTime;                 // gp-24452

// eGetScreenDisplayOffsets, 0x00105728: the current mode's (GetVideoMode).
void eGetScreenDisplayOffsets(int32_t *x, int32_t *y);

// 0x001056d8: the current mode's set.
void eSetScreenDisplayOffsets(int32_t x, int32_t y);

// GetWaitForBufferSwapTime, 0x00111f28, and GetVifTime, 0x00111f40: the
// word, signed, times 2^-16.
float GetWaitForBufferSwapTime(void);
float GetVifTime(void);

#endif
