// epoly -- ePoly (.mdebug type#2948), the engine's one screen-space quad,
// and its constructor, __5ePoly (0x0010e480).
//
// A poly is four vertices in the render target's pixels, their UVs and
// colours, and the GS's ALPHA_1 equation, (A - B) * C >> 7 + D, with each
// of A, B and D one of Cs, Cd and 0, and C one of As, Ad and FIX. The sun
// and its glare build one on the stack and draw each layer through it.
//
// ePoly::Render (0x0010e580) turns a poly into a GS packet for the
// texture's list, or for the alpha sort. It is the seam here, and the 3DS
// side's is in trackview.c. What it does, so that the seam's owner can do
// the same:
// - It draws nothing for a NULL texture.
// - A SunPoly carries its own ALPHA_1, from AlphaA..AlphaD and AlphaFix.
//   Render also clears the poly's ApplyAspectRatio, so every later Render
//   of the same poly skips the aspect ratio, sun or not.
// - With ApplyAspectRatio, x and y are scaled by the render target's
//   AspectRatio2DX and 2DY. Without it, an x past the middle moves half a
//   pixel left.
// - It blends only when the texture's IsAnySemitransparencyFlag is set.
// - It goes on the alpha sort by V0's z when the texture's
//   ApplyAlphaSorting is set. Otherwise it goes on the texture's list.
// - It draws a strip in the order V0, V1, V3, V2.
//
// The destructor (0x001149f0) runs bTNode's, then bNode's, and neither
// does anything to a poly on the stack. The port has no call for it.
//
// Cross-check: tools/sun_check.py. Write-up: docs/formats/sun-draw.md.

#ifndef EPOLY_H
#define EPOLY_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "texturepack.h"

typedef struct ePoly {
    uint8_t   Node[16];                     //   0  bTNode<ePoly>, then pad
    bVector4  Vertices[4];                  //  16
    float     UVs[4][3];                    //  80  u, v, q
    uint8_t   Colours[4][4];                // 128  r, g, b, a
    uint8_t   AlphaA;                       // 144
    uint8_t   AlphaB;                       // 145
    uint8_t   AlphaC;                       // 146
    uint8_t   AlphaD;                       // 147
    uint8_t   AlphaFix;                     // 148
    uint8_t   AlphaEnabled;                 // 149
    uint8_t   SunPoly;                      // 150
    uint8_t   ApplyAspectRatio;             // 151
    uint8_t   Flailer;                      // 152
    uint8_t   pad153[3];                    // 153
    void     *pDynamicFrameMemory;          // 156
} ePoly;                                    // 160

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char epoly_layout_check[
    (sizeof(ePoly) == 160 && offsetof(ePoly, Vertices) == 16
     && offsetof(ePoly, UVs) == 80 && offsetof(ePoly, Colours) == 128
     && offsetof(ePoly, AlphaA) == 144 && offsetof(ePoly, Flailer) == 152
     && offsetof(ePoly, pDynamicFrameMemory) == 156) ? 1 : -1];
#endif

// ALPHA_1's A, B and D.
enum {
    EPOLY_ALPHA_CS   = 0,
    EPOLY_ALPHA_CD   = 1,
    EPOLY_ALPHA_ZERO = 2
};

// The z every vertex starts at, gp-32684.
#define EPOLY_DEFAULT_Z 65535.0f

// __5ePoly. The vertices are a 64-pixel square at the top left, at
// EPOLY_DEFAULT_Z and w = 0. The UVs are the whole texture with q = 1, the
// colours 0x80 (1.0 on the GS), and ALPHA_1 (Cs - Cd) * As + Cd with FIX
// 128, turned off. ApplyAspectRatio is set. The first 16 bytes are left as
// they are.
void epoly_init(ePoly *p);

// ePoly::Render(TextureInfo *, int). NULL draws nothing.
extern void (*gEPolyRenderFn)(ePoly *p, TextureInfo *tex, int flags);

#endif
