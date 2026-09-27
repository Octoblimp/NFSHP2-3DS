// sundraw -- the draw half of Sun.obj: StuffSun (0x00123ec0), StuffSunGlare
// (0x001244c8), the glare's globals and the 15 SunZBuffers.
//
// eDisplayFrame calls StuffSun once per view, after the NIS objects and
// before the clans and the particles. It first calls StuffSunGlare, which
// draws the white-out an explosion starts. Then, for view 1 alone and only
// with a sun chunk, StuffSun does these steps:
// 1. It projects the sun's position. It returns when the sun is behind the
//    view, or off the render target by more than the largest CENTER layer.
//    SunPosX and SunPosY, when either is not 0, put it at those pixels
//    instead.
// 2. It counts the pixels whose Z is under 64 in the 32 by 32 rect the
//    last frame read back, over 1,024. Only the sky is that far, because
//    it is drawn with the Z writes off. Each layer's alpha is its
//    IntensityScale times 128 times that count. A negative IntensityScale
//    is its size times 128 and is not counted.
// 3. It draws each layer as a quad: the layer's Size across, turned by its
//    Angle plus SweepAngleAmount times how far across the screen the sun
//    is, at the layer's Offset from the sun. BLEND layers draw
//    (Cs - Cd) * As + Cd, and ADD layers Cs * As + Cd.
// 4. It asks eTransferZBufferRect for the 32 by 32 rect around the sun,
//    for the next frame's count, and clips the rect to the render target.
//
// StuffSunGlare takes no count. Its quads are at the camera's position
// plus GlareDist along its direction, 1.9 times the layers' size at most.
// The glare goes through four phases, of PhaseTimes seconds each:
// - 0: it grows;
// - 1: it holds;
// - 2: it fades;
// - 3: it ends.
// bStartGlare starts it at the next frame with a WorldTimer past 0, and
// bResetGlare stops it.
//
// Cross-check: tools/sun_check.py. Write-up: docs/formats/sun-draw.md.

#ifndef SUNDRAW_H
#define SUNDRAW_H

#include <stdint.h>

#include "eview.h"
#include "sun.h"

// SunZBuffer, 2064 bytes: a 32 by 32 rect of Z, and the part of it that
// is on the render target.
#define SUN_ZBUFFER_SIZE 32

typedef struct SunZBuffer {
    uint16_t Buffer[SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE];   //    0
    int32_t  StartX;                                        // 2048
    int32_t  EndX;                                          // 2052
    int32_t  StartY;                                        // 2056
    int32_t  EndY;                                          // 2060
} SunZBuffer;                                               // 2064

typedef char sun_zbuffer_layout_check[
    sizeof(SunZBuffer) == 2064 ? 1 : -1];

// One per render target, by ID.
#define NUM_SUN_ZBUFFERS 15

// SunZBuffers, 0x002dfe00.
extern SunZBuffer SunZBuffers[NUM_SUN_ZBUFFERS];

// The glare's globals, gp-24140 .. gp-24116, and PhaseTimes, 0x00290e50.
extern float   SunPosX;         // gp-24140  0: from the position
extern float   SunPosY;         // gp-24136
extern float   GlareDist;       // gp-24132  1.0
extern int32_t bStartGlare;     // gp-24128  Munition::ExplodeWarhead's
extern int32_t bResetGlare;     // gp-24124  the Player's
extern float   GlareStartTime;  // gp-24120  seconds; 0 with no glare
extern int32_t iGlarePhase;     // gp-24116

#define NUM_GLARE_PHASES 4

extern float PhaseTimes[NUM_GLARE_PHASES];   // 0.05, 0.2, 0.65, 5.0

// eTransferZBufferRect(unsigned char *, int, int, int, int), 0x00110610:
// queues a read of the w by h rect of the render target's Z at (x, y),
// in its pixels, into `dst` as 16-bit Z by rows. The GS answers after the
// frame. NULL reads nothing.
extern void (*gETransferZBufferRectFn)(uint8_t *dst, int x, int y, int w,
                                       int h);

// StuffSun(eView *), 0x00123ec0, and StuffSunGlare(eView *), 0x001244c8.
void StuffSun(eView *view);
void StuffSunGlare(eView *view);

#endif
