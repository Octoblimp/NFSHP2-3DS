// epoly -- ePoly (.mdebug type#2948), the engine's one screen-space quad,
// and its constructor, __5ePoly (retail 0x0010f968, the demo's 0x0010e480).
//
// A poly is four vertices in the render target's pixels, their UVs and
// colours, and the GS's ALPHA_1 equation, (A - B) * C >> 7 + D, with each
// of A, B and D one of Cs, Cd and 0, and C one of As, Ad and FIX. The sun
// and its glare build one on the stack and draw each layer through it.
//
// ePoly::Render (retail 0x0010fa68, the demo's 0x0010e580) turns a poly
// into a GS packet for the texture's list, or for the alpha sort. It is the
// seam here, and the 3DS side's is in trackview.c. What it does, so that
// the seam's owner can do the same:
// - It draws nothing for a NULL texture.
// - Each vertex's GS Z is its z, truncated to an integer. The list's test
//   is GEQUAL, so a z of the render target's MaxZ draws over anything, and
//   one of 1 only where the Z is still the clear's 0: the sky. (A Flailer
//   poly's z is an index into a table of Zs instead, which the sun never
//   sets.)
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
// ePoly::Render3D (retail 0x0010ff88, the demo's 0x0010ea60) is the same
// poly in a model's space instead, drawn through a local-to-world matrix.
// It is a seam too, and trackview.c's draws it as a strip. What it does:
// - It draws nothing for a NULL texture.
// - It lays out the four vertices, colours and UVs for the VU1 in the
//   order V0, V1, V3, V2, a strip, and only their x, y and z.
// - The packet goes on the texture's list with the matrix, or on the
//   alpha sort when the texture's ApplyAlphaSorting is set, by V0's z
//   through the view's WorldViewMatrix -- V0 as it is, not through the
//   matrix. That is eEndStrip's.
// - Its last argument is not read.
//
// The destructor (retail 0x00114db8, the demo's 0x001149f0) runs
// bTNode's, then bNode's, and neither does anything to a poly on the
// stack. The port has no call for it.
//
// Cross-check: tools/sun_check.py. Write-up: docs/formats/sun-draw.md.

#ifndef EPOLY_H
#define EPOLY_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
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

// ALPHA_1's C.
enum {
    EPOLY_ALPHA_AS  = 0,
    EPOLY_ALPHA_AD  = 1,
    EPOLY_ALPHA_FIX = 2
};

// The z every vertex starts at. Retail's constructor stores 0; the demo's
// loaded 65535 from gp-32684. The sun and its glare set every z they draw.
#define EPOLY_DEFAULT_Z 0.0f

// __5ePoly. The vertices are a 64-pixel square at the top left, at
// EPOLY_DEFAULT_Z and w = 0. The UVs are the whole texture with q = 1, the
// colours 0x80 (1.0 on the GS), and ALPHA_1 (Cs - Cd) * As + Cd with FIX
// 128, turned off. ApplyAspectRatio is set. The first 16 bytes are left as
// they are.
void epoly_init(ePoly *p);

// ePoly::Render(TextureInfo *, int). NULL draws nothing.
extern void (*gEPolyRenderFn)(ePoly *p, TextureInfo *tex, int flags);

// ePoly::Render3D(TextureInfo *, bMatrix4 *, int). NULL draws nothing.
extern void (*gEPolyRender3DFn)(ePoly *p, TextureInfo *tex,
                                bMatrix4 *local_world, int flags);

#endif
