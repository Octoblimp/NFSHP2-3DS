// efocus -- the PS2's depth of field, EcstasyE.obj's last attach (retail's
// 0x00119b28 .. 0x0011a988): the focus palette for a view, from its
// camera's focal distance and depth of field, and the passes that blur the
// frame by it.
//
// eDisplayFrame runs it after the fog, from the same test (0x001138ac):
//
//   if (InGameFlag && eAttachDepthIntoAlpha(chain, 0x342800)) {
//       eAttachFog(chain, 0x342c00);
//       eAttachDepthOfField(chain, 0x344000, 0x342c00);
//   }
//
// The frame's alpha holds the Z over 256 by then (efog.h). The palette has
// an alpha for each of those 256: none inside the camera's band, the full
// 128 outside it, and a ramp of 23 between. eAttachDepthOfField reads the
// alpha back through the palette into the frame's alpha, blurs the frame
// into a buffer half as wide, and lays the blur back over the frame by
// that alpha. The mirror and the HUD come after, so stay sharp.
//
// Retail's palette is built as if index i stood for a Z of i << 12, the
// frame's alpha being Z >> 8: 16 apart. That is the game as shipped, and
// the port keeps it (docs/formats/depth-of-field.md).
//
// Not here, the GS's: the CLUT's upload, the sprites and the packets. The
// port's eattach_depth_of_field hands each view's palette to
// gEDofAttachFn where the image builds its pass, and calls gEDofBlurFn
// where it builds the blur's. The PICA's side, at the end, says what
// trackview.c's passes write for a palette.
//
// Cross-check: tools/dof_check.py. Write-up: docs/formats/depth-of-field.md.

#ifndef EFOCUS_H
#define EFOCUS_H

#include <stdint.h>

#include "eview.h"

// The globals, as retail's image has them (GP 0x003358f0). The demo's
// JitterBlend was 27, and it had no samples' count.
extern int32_t DrawDepthOfField;        // gp-24136 (0x0032faa8)  1
extern int32_t FocusPrintPalette;       // gp-24132 (0x0032faac)  0
extern float   FocusAlphaMin;           // gp-24128 (0x0032fab0)  0.0
extern float   FocusAlphaMax;           // gp-24124 (0x0032fab4)  128.0
extern float   FocalDistance;           // gp-24120 (0x0032fab8)  0, the camera's
extern float   DepthOfField;            // gp-24116 (0x0032fabc)  0, the camera's
extern int32_t JitterBlend;             // gp-24112 (0x0032fac0)  64
extern int32_t FocusJitterSamples;      // gp-24068 (0x0032faec)  2
extern int32_t FocusRampLength;         // gp-24056 (0x0032faf8)  24
extern float   FocusFirstPrevious;      // gp-24052 (0x0032fafc)  -FLT_MAX

// The jitter, 0x002da750: (x, y) in sixteenths of a texel, the first
// FocusJitterSamples of them. The names of the last four are the port's.
extern int32_t FocusJitter[6][2];

// FocusPalettes, 0x002db380 (FogPalette + 3072): four palettes of 256, by
// view ID less one. Each is in the order the GS's CSM1 reads it
// (RemapLinearIntoClut8).
extern uint32_t FocusPalettes[4][256];

// GetFocusPalette(eView *), 0x00119b28: the view's palette for views 1 to
// 4, else NULL.
uint32_t *GetFocusPalette(eView *view);

// The three helpers after it, 0x00119b58, 0x00119b70 and 0x00119b90; retail
// has no names for them, so these are the demo's. ZRanges[1] is the race's
// range (eview.h).
//
// MapScreenZToPaletteIndex: bits 12 to 19 of the float's bits.
// MapPaletteIndexToScreenZ: the float with ZRanges[1].ZMin's bits and
//   i & 0xff at bit 12.
// MapScreenZToViewZ: the view's depth for a screen Z, between the planes.
uint32_t MapScreenZToPaletteIndex(float z);
float    MapPaletteIndexToScreenZ(uint32_t i);
float    MapScreenZToViewZ(float near, float far, float sz);

// CreateFocusPalette(eView *, unsigned *), 0x00119c20: the view's palette,
// and 1. 0 for a NULL view or palette; and with neither a focal distance
// nor a depth of field, the palette cleared and 0. The image reads the
// camera at the view's +56 unchecked, and so does this.
int CreateFocusPalette(eView *view, uint32_t *palette);

// eAttachDepthOfField(eDmaChain *, unsigned, unsigned), 0x00119f70: 0 when
// DrawDepthOfField is clear. Else views 1 and 2, each active one with a
// palette, get CreateFocusPalette; and 0 when none came back 1. Then each
// active view with a palette, gEDofAttachFn with the view, its palette and
// the band CreateFocusPalette found (NULL where it found none); then
// gEDofBlurFn, and 1. The image returns 0 when the frame's memory runs out
// for the blur, which the port's cannot.
//
// EFocusBand is the port's: the entries of the view depths d[] (nearest
// first, d[255 - i] for the palette's index i) where CreateFocusPalette
// put the band's near and far edges, t0 and t1 in the write-up. The
// palette's indices Near..Far are 255 - Far .. 255 - Near.
typedef struct EFocusBand {
    int32_t Near;
    int32_t Far;
} EFocusBand;

int eattach_depth_of_field(void);
extern void (*gEDofAttachFn)(eView *view, const uint32_t *palette,
                             const EFocusBand *band);
extern void (*gEDofBlurFn)(void);

// ------------------------------------------------------ the port's, the PICA's

// The PICA's depth, read as an RGBA8 texture, has its top byte in G, its
// middle byte in B and the low in A. The PS2's index for it, the Z over
// 256, is 128 G + B / 2 for G of 0 and 1, give or take one at the odd Bs,
// and 255 for G of 2 or more (where the depth is past 1/128, nearer than
// 128 times the near plane). So the port writes a view's alpha in up to
// three passes, by G: one over the whole view for G 0, one for G 1 and
// past where the depth is 1/256 or more, and one where it is 1/128 or
// more. Each step is the palette's alpha over its indices: a constant, or
// the palette's ramps by B.
//
// A ramp's sum is w = sat(FarB - B) + sat(B - NearB), over 255, with a
// term left out where FarB is 0 or under, or NearB 255 or over. Then w is
// times Times, then times 4 Quads times, then w + w K / 255, or w K / 255
// alone for a Times of 0, each saturated: x, the ramp's 0 to 1 for the
// palette's 0 to the ramp's length; a K of 0 with a Times leaves x as w,
// and takes no stage. The alpha is Min + (Max - Min) x, over 255.
typedef struct EFocusStep {
    uint8_t Ramp;       // 0: Alpha alone
    uint8_t Alpha;      // the constant, the PICA's: 255 is the GS's 128
    int16_t FarB;
    int16_t NearB;
    uint8_t Quads;
    uint8_t Times;
    uint8_t K;
    uint8_t Min;
    uint8_t Max;
} EFocusStep;

// A view's passes. Count steps run, Step[0] over the view and the rest
// from the depth At[n]; 0 when the palette's alpha is 0 throughout, which
// leaves the frame as it is.
typedef struct EFocusPlan {
    int        Count;
    EFocusStep Step[3];
    float      At[3];
} EFocusPlan;

// The PICA's alpha for the GS's: 128 is 1.0, and the PICA's 255.
uint8_t efocus_pica_byte(uint32_t gsAlpha);

// The plan for a palette and the band CreateFocusPalette found for it, or
// NULL for none; the ramps are FocusAlphaMin's and FocusAlphaMax's over
// FocusRampLength entries. A region whose alpha is the same throughout is
// a constant, and the last two passes are one where they are the same.
void efocus_plan(const uint32_t *palette, const EFocusBand *band,
                 EFocusPlan *plan);

// What the plan's passes leave for a depth (24 bits), as the PICA's 0 to
// 1, with its combiners' sums in floats.
float efocus_pica_alpha(const EFocusPlan *plan, uint32_t d24);

#endif
