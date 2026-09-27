// efog -- the PS2's fog, EcstasyE.obj's part of it (0x00118878 ..
// 0x00119e50): the depth into the frame's alpha, the fog's palette for a
// view, and the pass that puts it over the frame.
//
// On the PS2 the fog is a pass over the finished frame. eDisplayFrame, once
// everything is drawn, the sun and the alpha polys too (0x00113420):
//
//   if (InGameFlag && eAttachDepthIntoAlpha(chain, 0x2c0400)) {
//       eAttachFog(chain, 0x2c0800);
//       eAttachDepthOfField(chain, 0x2c0c00);
//   }
//
// eAttachDepthIntoAlpha reads the 16-bit Z back as an 8-bit texture, twice,
// through two palettes: the Z's high byte into the alpha's top six bits and
// its low byte into the bottom two. What that leaves in the alpha is the Z
// over 64, or 252 .. 255 for a Z of 0x4000 and past. eAttachFog then makes
// a palette of 256 for each player's view from the weather at its camera
// (CreateFogPalette), reads the alpha back as an 8-bit texture through it,
// and draws one sprite over the view, blended by the fog mode's ALPHA_1.
// Mode 0, the one the image has, blends the palette's colour over the
// frame by the palette's alpha: none near, up to the weather's amount at
// the far plane and in the sky, which leaves its Z at 0.
//
// The palette depends only on the camera and the globals, so the port makes
// it before the draws, and trackview.c hands it to the PICA's fog unit as a
// lookup by depth (efog_keep, efog_colour).
//
// Not here, the GS's: the CLUT uploads, the sprites and the DMA packets,
// and eAttachDepthOfField. The port draws none of it; eattach_fog hands
// each view's palette to gEFogAttachFn where the image builds the packet.
//
// Cross-check: tools/weather_check.py. Write-up: docs/formats/weather-fog.md.

#ifndef EFOG_H
#define EFOG_H

#include <stddef.h>
#include <stdint.h>

#include "eview.h"

// FogModeInfo, 32 bytes: the GS's ALPHA_1 for the fog's sprite and four
// floats nothing reads. ALPHA_1 is ((A - B) * C >> 7) + D, where 0 is the
// source, 1 the frame and 2 zero, and C's 0 is the source's alpha and 2
// the Fix.
typedef struct FogModeInfo {
    uint8_t  AlphaA;                        //  0
    uint8_t  AlphaB;                        //  1
    uint8_t  AlphaC;                        //  2
    uint8_t  AlphaD;                        //  3
    uint8_t  AlphaFix;                      //  4
    uint8_t  pad[3];                        //  5
    float    Start;                         //  8
    float    End;                           // 12
    float    R, G, B, A;                    // 16
} FogModeInfo;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char efog_layout_check[
    (sizeof(FogModeInfo) == 32 && offsetof(FogModeInfo, Start) == 8
     && offsetof(FogModeInfo, A) == 28) ? 1 : -1];
#endif

// FogModeInfos, 0x002d9d30, by mode. 0 blends the palette over the frame;
// 1 darkens the frame by it.
extern FogModeInfo FogModeInfos[4];

// The globals, as the image has them.
extern int32_t DrawFog;                 // 0x00322bd8  1
extern int32_t FogMode1;                // 0x00322bd0  0, player 1's view
extern int32_t FogMode2;                // 0x00322bd4  0, every other one
extern float   FogPower;                // 0x00322bdc  4.6
extern int32_t EnableDepthIntoAlpha;    // 0x00322bb8  1

// FogPalette, 0x002da980: three palettes of 256, by view ID less one.
// GetFogPalette gives a fourth for view 4, which in the image is the first
// of FocusPalettes, the depth of field's; here it is the fourth row.
extern uint32_t FogPalette[4][256];

// DepthUpperPalette (0x002d9e20) and DepthLowerPalette (0x002da220), in the
// CLUT's order.
extern uint32_t DepthUpperPalette[256];
extern uint32_t DepthLowerPalette[256];

// fpow(float, float), 0x00119628: x to the y, by the floats' bits. x under
// 0.01 is taken as 0.01.
float fpow(float x, float y);

// RemapLinearIntoClut8(unsigned *, unsigned *), 0x00118878: 256 colours
// into the order the GS's CSM1 reads them, which in each 32 swaps the
// second 8 with the third.
void RemapLinearIntoClut8(uint32_t *dst, const uint32_t *src);

// The CLUT's entry for index k: the swap is its own inverse.
static inline uint32_t efog_clut_index(uint32_t k)
{
    return (k & ~0x18u) | ((k & 8u) << 1) | ((k & 0x10u) >> 1);
}

// GetFogPalette(eView *), 0x001195f8: the view's palette for views 1 to 4,
// else NULL.
uint32_t *GetFogPalette(eView *view);

// CreateFogPalette(eView *, unsigned *), 0x00119678: the view's palette,
// from its weather query and its mode. Nothing for a NULL view or palette.
// Mode 3 writes one entry, at the fog's start; the image does not bound
// it, and here one outside 0 .. 255 is not written.
void CreateFogPalette(eView *view, uint32_t *palette);

// eAttachDepthIntoAlpha(eDmaChain *, unsigned), 0x00119330: 0 when
// EnableDepthIntoAlpha is clear, else the two palettes and 1. The image
// also wants DepthIntoAlphaBuffer, the packet AllocateDepthIntoAlphaBuffers
// makes at start-up; the port draws no packet.
int eattach_depth_into_alpha(void);

// eAttachFog(eDmaChain *, unsigned), 0x00119af8: 0 when DrawFog is clear.
// Else, for views 1 and 2, each one active with an active first render
// target and a palette: CreateFogPalette, then gEFogAttachFn with the
// view, its palette and its mode's FogModeInfo. Then 1. The image returns
// 0 when its DMA runs out, which the port's cannot.
int eattach_fog(void);
extern void (*gEFogAttachFn)(eView *view, const uint32_t *palette,
                             const FogModeInfo *mode);

// The mode a view's fog takes: FogMode1 for view 1, else FogMode2.
int32_t efog_view_mode(const eView *view);

// ------------------------------------------------------ the port's, the PICA's

// The alpha the two depth passes leave for a 16-bit Z, through the
// palettes as the CLUT holds them.
uint32_t efog_depth_alpha(uint32_t z);

// The PS2's fog as the PICA's: out = frag * keep + colour * (1 - keep).
// efog_colour gives the colour, and 0 when the mode's blend cannot be put
// so: mode 0's blend with a colour that varies over the entries that have
// alpha, or any blend but mode 0's and mode 1's. keep is that fraction
// for a Z, 1 - a / 128 for mode 0's and a / 128 for mode 1's, where a is
// the alpha of the palette's entry for the Z's depth alpha.
int   efog_colour(const uint32_t *palette, const FogModeInfo *mode,
                  uint32_t *colour);
float efog_keep(const uint32_t *palette, const FogModeInfo *mode,
                uint32_t z);

#endif
