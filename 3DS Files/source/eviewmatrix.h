// eviewmatrix -- the matrix half of eView.obj (0x00106700 .. 0x00107010)
// and the three helpers it calls in EcstasyE.obj: CalculateH (0x00103ce0),
// eRenderTarget::SetupMatrixPacks (0x00104d18) and CreateViewMatricies
// (0x0010d268).
//
// Once a frame the renderer calls CalculateViewMatricies for each active
// view. It turns the camera into the five matrices the frame draws with,
// puts them in frame memory, and hands them to the view and to its render
// targets. The cull reads two of them: WorldViewMatrix, the camera's own,
// and WorldScreenClipMatrix, world space to a clip volume the size of the
// screen.
//
// Everything is in the GS's coordinates: a 4096-pixel square centred on
// (2048, 2048) with the screen, ScreenWidth by ScreenHeight, in its middle,
// and depths between ZMin and ZMax. The handheld keeps them. The cull and
// the level of detail are measured in the PS2's pixels, and the renderer
// takes the camera and H from the view and makes its own projection for
// the 3DS's screen.
//
// Written up with addresses in docs/formats/eview.md; checked by
// tools/eview_check.py.

#ifndef EVIEWMATRIX_H
#define EVIEWMATRIX_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "eview.h"

// DefaultMatrixPack, 0x002aa150, zero in the image: what a render target
// is given when the frame memory runs out.
extern eRenderTargetMatrixPack DefaultMatrixPack;

// hack_man_matrix (0x002d6170) and SunPosition (0x002dfdf0), zero in the
// image: the light context's second matrix and the eye of its look-at.
// The sun sets SunPosition.
extern bMatrix4 hack_man_matrix;
extern bVector3 SunPosition;

// eLightContext, 288 bytes (.mdebug type#3201).
typedef struct eLightContext {
    bMatrix4 LocalColourMatrix;         //   0
    bMatrix4 LocalDirectionMatrix;      //  64
    bMatrix4 LocalLightPositions;       // 128
    bVector4 LocalEyePosition;          // 192
    int32_t  NumLights;                 // 208
    float    SunlightIntensity;         // 212
    int32_t  pad1;                      // 216
    int32_t  pad2;                      // 220
    bMatrix4 EnvMapMatrix;              // 224
} eLightContext;

// elSetupLightContext(eLightContext *, bMatrix4 *, bMatrix4 *, bVector4 *,
// eView *), 0x001154b8, the seam: 1928 bytes of the lighting that is the
// renderer's. NULL does nothing.
extern void (*gElSetupLightContextFn)(eLightContext *lc,
                                      const bMatrix4 *local_world,
                                      const bMatrix4 *hack,
                                      const bVector4 *eye, eView *view);

// 0x00103ce0. The focal length in pixels: half the screen's width over
// tan(fov / 2), or 10 when the tangent is 0. The tangent is bSin over bCos
// of the half angle, as a u16.
float CalculateH(uint16_t fov);

// 0x0010d268. From the view's camera and first render target:
//
//   the render targets' FovBias, tan(aBaselineFovMip / 2) / tan(fov / 2);
//   the view's NearZ, FarZ, H, FovDegrees and ViewDirection;
//   a  view to screen            (always)
//   b  view to clip              (when b)
//   c  clip to screen            (when c, and b)
//   d  clip to screen, ZMin1     (when d, and b)
//   e  view to a clip volume the size of the screen (when e)
//   and last a = b * c, which needs both.
//
// Players 1 and 2 have their near plane scaled by tan(aBaselineFovZ / 2) /
// tan(fov / 2) and keep their depth, unless their first mover drives or is
// the bumper camera. A non-zero `nearz` or `farz` then overrides the
// plane, and a non-zero `e_farz` e's far plane.
void CreateViewMatricies(eView *view, bMatrix4 *a, bMatrix4 *b, bMatrix4 *c,
                         bMatrix4 *d, bMatrix4 *e, float nearz, float farz,
                         float e_farz);

// eView::CalculateViewMatricies(float, float, float), 0x00106700. The five
// matrices and their inverses into 512 bytes of frame memory:
//
//     +0    WorldView        the camera's matrix
//     +64   WorldClip        WorldView * b
//     +128  WorldScreen      WorldView * a
//     +192  WorldScreenClip  WorldView * e
//     +256  ClipScreen       c
//     +320  ViewScreen       never written
//     +384  VUClipScreen     c's diagonal and row 3, then c^-1's
//     +448  VUClipScreen1    the same from d
//
// then the view's eight pointers and each render target's five, and the
// targets' matrix packs. With no frame memory every pointer is
// eMathIdentityMatrix and nothing is inverted.
void eview_calculate_view_matrices(eView *view, float nearz, float farz,
                                   float e_farz);

// eRenderTarget::SetupMatrixPacks, 0x00104d18. Two 192-byte packs from
// frame memory, taken before either is filled: WorldView, WorldClip and
// VUClipScreen, then the same with VUClipScreen1. A pack the frame memory
// cannot give is DefaultMatrixPack.
void erender_setup_matrix_packs(eRenderTarget *rt);

// eView::CalculateLocalToScreenClip (0x00106a20) and CalculateLocalToClip
// (0x00106a38): o = local * WorldScreenClip, o = local * WorldClip.
void eview_local_to_screen_clip(eView *view, bMatrix4 *o,
                                const bMatrix4 *local);
void eview_local_to_clip(eView *view, bMatrix4 *o, const bMatrix4 *local);

// eView::BiasMatrixForZSorting(bMatrix4 *, float), 0x00106a50. Scales m
// about the camera's eye by `scale`: m's row 3 is moved to eye + (row 3 -
// eye) * scale and m becomes m, less its translation, times that scale and
// move. Nothing happens without a camera.
void eview_bias_matrix_for_z_sorting(eView *view, bMatrix4 *m, float scale);

// The three eView::GetPixelSize: how many pixels across a thing is, by H
// over its distance, truncated. They differ at the near end:
//
//   (float r, float d)  0x00106b50  r * H / d while r / 2 < d, else 2H
//   (bVector3 *, r)     0x00106b98  from the eye, less r; 0 behind the eye
//                                   by more than r; else as above
//   (min, max)          0x00106c90  the box's centre and half its diagonal;
//                                   r * H / (dist - r) while r < dist - r,
//                                   else H, not 2H
//
// The second calls bGetTicker and drops what it returns; the port leaves
// the call out.
int32_t eview_get_pixel_size(eView *view, float r, float d);
int32_t eview_get_pixel_size_sphere(eView *view, const bVector3 *p, float r);
int32_t eview_get_pixel_size_box(eView *view, const bVector3 *mn,
                                 const bVector3 *mx);

// eView::GetScreenPosition(bVector3 *, bVector3 const *), 0x00106d98:
// through WorldScreen and the divide, then from the GS's square to the
// first render target's scissor. z is the depth, as it comes.
void eview_get_screen_position(eView *view, bVector3 *o, const bVector3 *p);

// eView::GetScreenWidth (0x00106e68) and GetScreenHeight (0x00106e80): the
// first render target's scissor, as floats.
float eview_get_screen_width(eView *view);
float eview_get_screen_height(eView *view);

// eView::SetupWorldLightContext, 0x00106e98. A light context for the
// world, from frame memory, lit from 9 units behind the eye and 7 above,
// with its environment map looking from SunPosition at the origin. NULL
// without a camera or frame memory.
void eview_setup_world_light_context(eView *view);

#endif
