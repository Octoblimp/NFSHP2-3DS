// efog -- the PS2's fog, EcstasyE.obj's part of it (retail's 0x001189f8 ..
// 0x00119b54): the depth into the frame's alpha, the fog's palette for a
// view, and the pass that puts it over the frame. Retail's: the demo's
// (0x00118878 .. 0x00119e50) read a 16-bit Z, and retail rewrote the chain
// for its 24-bit one.
//
// On the PS2 the fog is a pass over the finished frame. eDisplayFrame, once
// everything is drawn, the sun and the alpha polys too (0x001138ac):
//
//   if (InGameFlag && eAttachDepthIntoAlpha(chain, 0x342800)) {
//       eAttachFog(chain, 0x342c00);
//       eAttachDepthOfField(chain, 0x344000, 0x342c00);
//   }
//
// eAttachDepthIntoAlpha copies the Z into the frame's alpha in four
// passes. The first two read the PSMZ24 buffer as PSMZ16 and write its
// low halves' high bytes, the Z's bits 8 to 15, into the draw frame's
// alpha, through a PSMCT16 view of it and a FRAME mask of 0x3fff. The
// third sets the shown frame's alpha to 255, and the fourth copies the
// draw frame's alpha over it where the Z is 0xffff or under, by a Z test.
// What that leaves in the alpha is the Z over 256, or 255 for a Z past
// 0xffff. eAttachFog then makes a palette of 256 for each player's view
// from the weather at its camera (CreateFogPalette), reads the alpha back
// as an 8-bit texture through it, and draws one sprite over the view,
// blended by the fog mode's ALPHA_1.
// Mode 0, the one the image has, blends the palette's colour over the
// frame by the palette's alpha: none near, up to the weather's amount at
// the far plane and in the sky, which leaves its Z at 0.
//
// The palette depends only on the camera and the globals, so the port makes
// it before the draws, and trackview.c hands it to the PICA's fog unit as a
// lookup by depth (efog_keep, efog_colour).
//
// Not here, the GS's: the CLUT uploads, the sprites and the DMA packets.
// The port draws none of it; eattach_fog hands each view's palette to
// gEFogAttachFn where the image builds the packet. eAttachDepthOfField,
// the chain's next, is efocus.h's.
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

// FogModeInfos, 0x002da6d0 (the demo's 0x002d9d30, the same values), by
// mode. 0 blends the palette over the frame; 1 darkens the frame by it.
extern FogModeInfo FogModeInfos[4];

// The globals, as retail's image has them. FogPower was the demo's 4.6.
extern int32_t DrawFog;                 // gp-24144 (0x0032faa0)  1
extern int32_t FogMode1;                // gp-24152 (0x0032fa98)  0, player 1's
extern int32_t FogMode2;                // gp-24148 (0x0032fa9c)  0, the others
extern float   FogPower;                // gp-24140 (0x0032faa4)  4.0
extern int32_t EnableDepthIntoAlpha;    // gp-24180 (0x0032fa7c)  1

// FogPalette, 0x002da780: three palettes of 256, by view ID less one.
// GetFogPalette gives a fourth for view 4, which in the image is the first
// of FocusPalettes, the depth of field's; here it is the fourth row.
extern uint32_t FogPalette[4][256];

// fpow(float, float), the demo's 0x00119628: x to the y, by the floats'
// bits. x under 0.01 is taken as 0.01. Retail has it inlined in
// CreateFogPalette, with the 0.01 at gp-32456.
float fpow(float x, float y);

// RemapLinearIntoClut8(unsigned *, unsigned *), 0x001189f8: 256 colours
// into the order the GS's CSM1 reads them, which in each 32 swaps the
// second 8 with the third.
void RemapLinearIntoClut8(uint32_t *dst, const uint32_t *src);

// The CLUT's entry for index k: the swap is its own inverse.
static inline uint32_t efog_clut_index(uint32_t k)
{
    return (k & ~0x18u) | ((k & 8u) << 1) | ((k & 0x10u) >> 1);
}

// GetFogPalette(eView *), 0x001192d8: the view's palette for views 1 to 4,
// else NULL.
uint32_t *GetFogPalette(eView *view);

// CreateFogPalette(eView *, unsigned *), 0x00119308: the view's palette,
// from its weather query and its mode. Nothing for a NULL view or palette.
// Mode 3 writes one entry, at the fog's start; the image does not bound
// it, and here one outside 0 .. 255 is not written.
void CreateFogPalette(eView *view, uint32_t *palette);

// eAttachDepthIntoAlpha(eDmaChain *, unsigned), 0x00118a60: 0 when
// EnableDepthIntoAlpha is clear, else its packet and 1. The image builds
// the packet in the frame's memory, 5,504 bytes, and returns 0 when that
// runs out; the port draws no packet.
int eattach_depth_into_alpha(void);

// eAttachFog(eDmaChain *, unsigned), 0x00119768: 0 when DrawFog is clear.
// Else, for views 1 and 2, each one active with an active first render
// target and a palette: CreateFogPalette, then gEFogAttachFn with the
// view, its palette and its mode's FogModeInfo. Then 1. The image returns
// 0 when the frame's memory runs out, which the port's cannot.
int eattach_fog(void);
extern void (*gEFogAttachFn)(eView *view, const uint32_t *palette,
                             const FogModeInfo *mode);

// The mode a view's fog takes: FogMode1 for view 1, else FogMode2.
int32_t efog_view_mode(const eView *view);

// ------------------------------------------------------ the port's, the PICA's

// The alpha eAttachDepthIntoAlpha's passes leave for a 24-bit Z: its bits
// 8 to 15, or 255 past 0xffff.
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
