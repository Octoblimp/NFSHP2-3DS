// radialblur -- the radial blur (TASKS 80d): the nitro's, the zones' and
// the replay's, retail 0x0010f0d0 to 0x0010f4f0 (eview.cpp). The demo has
// the same functions at 0x0010dc80 to 0x0010dff0.
//
// A view's blur is a texture pointer, RADIALBLUR (pTextureInfoRadialBlur),
// at retail's eView+108; the port keeps the demo's layout, where it is
// +104, pBlendMask. Each of the two player views has two alphas, bytes
// with 0x80 as 1.0: the centre's ("from", gp-24712) and the edges'
// ("to", gp-24704).
//
// eDisplayFrame (0x00113a54) draws a view's blur after its scene, the cars
// and the alpha lists, and before its rear-view mirror and the HUD, in two
// steps:
// - DisplayRadialBlur (0x0010f280) draws four quads over the view, the
//   quarters of its scissor, each from a corner to the middle. ALPHA_1 is
//   (Cs - Cs) * As + Cd, which leaves the colour as it was. But the GS
//   writes the fragment's alpha into the target whatever the equation, so
//   the quads put a mask in the target's alpha: RADIALBLUR's alpha, 63 at
//   the edges down to 35 in the middle (the texture's (1, 1) is at the
//   middle of the view), times the edges' alpha at the corners and the
//   middles of the sides and the centre's at the middle. Gouraud between.
// - DisplayBlendPrevious (0x0010f4f0) draws the other screen buffer
//   (gp-24920; eSwapScreenBuffers swaps it each frame), the last frame's
//   picture, over the view with (Cs - Cd) * Ad + Cd: the last frame by the
//   mask. Its UVs are the scissor's from (x0 + 0.5, y0 + 0.5) to (w - 0.5,
//   h - 0.5) of a 512 by 512 texture.
// Each frame the edges keep some of the frame before, which kept some of
// the one before that, so a fast camera leaves trails at the edges and
// none in the middle: with the nitro's 0 and 0.8, the corners keep 63 *
// 204 / 128 = 100, 0.78 of the last frame.
//
// The quads and the blend are ePolys, so this builds them and the seam's
// owner draws them (trackview.c, display_radial_blur). The 3DS keeps the
// last frame itself: a copy of the view after its blend.
//
// Cross-check: tools/radialblur_check.py. Write-up: docs/formats/
// radial-blur.md.

#ifndef RADIALBLUR_H
#define RADIALBLUR_H

#include <stdbool.h>
#include <stdint.h>

#include "epoly.h"
#include "eview.h"

// gp-24712 and gp-24704: by view ID less 1 (On), or by player (Alpha).
extern uint8_t RadialBlurFromAlpha[2];
extern uint8_t RadialBlurToAlpha[2];

// GetPlayerView (0x0010f0d0): eGetView(player + 1), but in the instant
// replay view 1 for the replay screen's player and NULL for any other.
eView *radialblur_player_view(int32_t player);

// 0x0010f128: RADIALBLUR into the view, the edges' alpha 160 and the
// centre's 0. Nothing in the post-race state.
void radialblur_view_on(eView *view);

// 0x0010f1a8: the view's blur off.
void radialblur_view_off(eView *view);

// RadialBlurOn and RadialBlurOff (0x0010f178, 0x0010f1b0), for the
// player's view; nothing when it has none. gRadialBlurOnFn's and
// gRadialBlurOffFn's.
void radialblur_on(int32_t player);
void radialblur_off(int32_t player);

// RadialBlurOnOff (0x0010f1e0), on a view: the replay screen's.
void radialblur_on_off_view(int32_t on, eView *view);

// RadialBlurOnOff(bool, int) (0x0010f1f8): RadialBlurOn or RadialBlurOff
// for the player, and the player back: the Motion Blur egg's stomp
// (stomper.h), which keeps what it returns and gives it back to turn off.
int32_t radialblur_on_off(int32_t on, int32_t player);

// RadialBlurAlpha (0x0010f238): the player's centre and edge alphas, each
// truncated from times 255. gRadialBlurAlphaFn's.
void radialblur_alpha(int32_t player, float from, float to);

// gReplayScreenRadialBlurFn's: RadialBlurOnOff on eGetView(1).
void radialblur_replay(int32_t on);

// DisplayRadialBlur's four polys for the view, in the order it draws them:
// how many, 0 when it draws none (no blur, a view but 1 and 2, or a target
// not active). They draw with the view's texture, pBlendMask.
int radialblur_mask_polys(const eView *view, ePoly polys[4]);

// DisplayBlendPrevious's poly for the view: false when it draws none (the
// view not active, no blur, or the target not active). Its texture is the
// last frame.
bool radialblur_previous_poly(const eView *view, ePoly *poly);

#endif
