// sundraw -- the draw half of Sun.obj: StuffSun (retail 0x001252b0, the
// demo's 0x00123ec0), StuffSunGlare (retail 0x00125918, the demo's
// 0x001244c8), the glare's globals and the 15 SunZBuffers.
//
// eDisplayFrame calls StuffSun once per view, after the NIS objects and
// before the clans and the particles. It first calls StuffSunGlare, which
// draws the white-out an explosion starts. Then, for view 1 alone and only
// with a sun chunk, StuffSun does these steps:
// 1. It projects the sun's position. It returns when the sun is behind the
//    view, or off the render target by more than the largest CENTER layer.
//    SunPosX and SunPosY, when either is not 0, put it at those pixels
//    instead.
// 2. It counts the pixels whose Z, the low 24 bits, is under 2 in the rect
//    the last frame read back, over 1,024. Only the sky is that far,
//    because it is drawn with the Z writes off. Each layer's alpha is its
//    IntensityScale times 128 times that count. A negative IntensityScale
//    is its size times 128 and is not counted.
// 3. It draws each layer as a quad: the layer's Size across, turned by its
//    Angle plus SweepAngleAmount times how far across the screen the sun
//    is, at the layer's Offset from the sun. BLEND layers draw
//    (Cs - Cd) * As + Cd, and ADD layers Cs * As + Cd. The first layer is
//    at a z of 1, so it shows only over the sky; the rest are at the
//    render target's MaxZ, over everything.
// 4. It asks eTransferZBufferRect for the 32 by 32 rect around the sun,
//    moved onto the render target, for the next frame's count. The part
//    of it that was the sun's is StartX..EndX and StartY..EndY.
//
// StuffSunGlare takes no count, and draws SunGlareInfo's layers at MaxZ.
// Its quads are at the camera's position plus GlareDist along its
// direction, 1.9 times the layers' size at most. The glare goes through
// four phases, of PhaseTimes seconds each:
// - 0: it grows;
// - 1: it holds;
// - 2: it fades;
// - 3: it ends.
// bStartGlare starts it at the next frame with a RealTimer past 0, and
// bResetGlare stops it.
//
// The demo counted a 16-bit Z under 64, read the rect where it fell even
// off the target, drew every layer at 65535 (the constructor's), and timed
// the glare in WorldTimer's seconds, drawing the track's own layers.
//
// Cross-check: tools/sun_check.py. Write-up: docs/formats/sun-draw.md.

#ifndef SUNDRAW_H
#define SUNDRAW_H

#include <stdint.h>

#include "eview.h"
#include "sun.h"
#include "timer.h"

// SunZBuffer, 4112 bytes: a 32 by 32 rect of Z, 32 bits a pixel of which
// the low 24 are the Z, and the part of it that was the sun's. The demo's
// was 16 bits a pixel, 2064 bytes.
#define SUN_ZBUFFER_SIZE 32

typedef struct SunZBuffer {
    uint32_t Buffer[SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE];   //    0
    int32_t  StartX;                                        // 4096
    int32_t  EndX;                                          // 4100
    int32_t  StartY;                                        // 4104
    int32_t  EndY;                                          // 4108
} SunZBuffer;                                               // 4112

typedef char sun_zbuffer_layout_check[
    sizeof(SunZBuffer) == 4112 ? 1 : -1];

// One per render target, by ID.
#define NUM_SUN_ZBUFFERS 15

// SunZBuffers, retail 0x002e03d0.
extern SunZBuffer SunZBuffers[NUM_SUN_ZBUFFERS];

// The glare's globals, retail gp-23580 .. gp-23556, and PhaseTimes,
// retail 0x002ad128.
extern float   SunPosX;         // gp-23580  0: from the position
extern float   SunPosY;         // gp-23576
extern float   GlareDist;       // gp-23572  1.0
extern int32_t bStartGlare;     // gp-23568  Munition::ExplodeWarhead's
extern int32_t bResetGlare;     // gp-23564  the Player's
extern Timer   GlareStartTime;  // gp-23560  RealTimer's; 0 with no glare
extern int32_t iGlarePhase;     // gp-23556

#define NUM_GLARE_PHASES 4

extern float PhaseTimes[NUM_GLARE_PHASES];   // 0.05, 0.2, 0.65, 5.0

// eTransferZBufferRect(unsigned char *, int, int, int, int), retail
// 0x00111c58: queues a read of the w by h rect of the render target's Z at
// (x, y), in its pixels, into `dst` as 32-bit words by rows. The GS
// answers after the frame. NULL reads nothing.
extern void (*gETransferZBufferRectFn)(uint8_t *dst, int x, int y, int w,
                                       int h);

// StuffSun(eView *) and StuffSunGlare(eView *).
void StuffSun(eView *view);
void StuffSunGlare(eView *view);

#endif
