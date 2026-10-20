# The radial blur

The blur at the screen's edges under the nitro, in the zones (the freeze
and the preview) and in the replays: retail `0x0010f0d0` to `0x0010f4f0`,
from `eview.cpp`. The demo has the same functions at `0x0010dc80` to
`0x0010dff0`. Ported in `radialblur.c` (TASKS 80d); `trackview.c` draws it.

## The state

A view's blur is a texture pointer, RADIALBLUR (`pTextureInfoRadialBlur`,
gp-25124, set by `eFixUpTables`), at retail's `eView+108`. The port keeps
the demo's view layout, where it is `+104`, `pBlendMask`. NULL is off.

The two player views have two alpha bytes each, 0x80 as 1.0 as the GS
takes them:

| gp | name | what |
| --- | --- | --- |
| -24712 | `RadialBlurFromAlpha[2]` | the centre's |
| -24704 | `RadialBlurToAlpha[2]` | the edges' |

## The calls

| retail | port | what |
| --- | --- | --- |
| `0x0010f0d0` GetPlayerView | `radialblur_player_view` | `eGetView(player + 1)`; but while the coordinator is in the instant replay (state 4) with a replay screen, view 1 for the screen's player and NULL for any other |
| `0x0010f128` | `radialblur_view_on` | nothing in the post-race state (7); else RADIALBLUR into the view, the edges' alpha 160 and the centre's 0, at the view's ID less 1 |
| `0x0010f1a8` | `radialblur_view_off` | the pointer NULL |
| `0x0010f178` RadialBlurOn | `radialblur_on` | the player's view on, when there is one |
| `0x0010f1b0` RadialBlurOff | `radialblur_off` | off the same way |
| `0x0010f1e0` | `radialblur_on_off_view` | on or off, on a view: `ReplayScreen::ChangeCameraMover`'s, on `eGetView(1)` (`radialblur_replay`) |
| `0x0010f238` RadialBlurAlpha | `radialblur_alpha` | each of the two floats times 255, `cvt.w.s` (truncated), stored as a byte, by player |
| `0x0010f1f8` RadialBlurOnOff(bool, int) | `radialblur_on_off` | RadialBlurOn or RadialBlurOff by the bool, for the player; returns the player. No `jal` calls it: the Motion Blur egg's list does, through its pointer (`stomper.md`) |

The view-on indexes the bytes by the view's ID less one unchecked, and
RadialBlurAlpha by the player; the port checks both against 2. The game
only calls them for the player views, 1 and 2, and players 0 and 1.

`main.c` binds them: `gRadialBlurOnFn`, `gRadialBlurOffFn` and
`gRadialBlurAlphaFn` (the nitro's in `realdriver.c`, the zones' in
`zonecam.c` and `playerzone.c`) and `gReplayScreenRadialBlurFn`. The
nitro's alpha is `(0, 0.8)`: the edges 204.

## The draw

`eDisplayFrame` calls, for each view, after its scene, the cars and the
alpha lists and before the rear-view mirrors and the HUD
(`0x00113a44` to `0x00113a64`): `DisplayFilter`, then `DisplayRadialBlur`
(`0x0010f280`), then `DisplayBlendPrevious` (`0x0010f4f0`).

**DisplayRadialBlur** draws nothing unless the view has a blur, its ID is
1 or 2, and its render target (`+48`) is active. It builds one ePoly on
the stack and changes it between four `Render`s, so each quarter keeps
what the one before set but for the corner it moves:

- ALPHA_1 `A = Cs, B = Cs, C = As, D = Cd`: `(Cs - Cs) * As + Cd`, the
  colour left as it was. `SunPoly` 1, `ApplyAspectRatio` 0.
- Every z is the target's `MaxZ` (`+116`).
- The colours are the constructor's 0x80 grey; the alphas the edges' at
  V0, V1 and V3 and the centre's at V2.
- The UVs are the constructor's, the whole texture with V2 at (1, 1), so
  the texture's bottom right corner sits at the middle of the view.
- With the scissor `(x0, y0, w, h)` (`+20` to `+32`), `x1 = x0 + w`,
  `y1 = y0 + h`, `cx = x0 + w / 2`, `cy = y0 + h / 2` (C's division):

| quad | V0 | V1 | V2 | V3 |
| --- | --- | --- | --- | --- |
| 1 | (x0, y0) | (cx, y0) | (cx, cy) | (x0, cy) |
| 2 | (x1, y0) | (cx, y0) | (cx, cy) | (x1, cy) |
| 3 | (x1, y1) | (cx, y1) | (cx, cy) | (x1, cy) |
| 4 | (x0, y1) | (cx, y1) | (cx, cy) | (x0, cy) |

Then `AttachSolidPolys` and the destructor. The GS writes the fragment's
alpha into a PSMCT32 target whatever ALPHA_1 says, so the quads leave a
mask in the target's alpha: RADIALBLUR's alpha times the vertex alpha,
`>> 7`.

RADIALBLUR is 64 by 64, 32 bits, semitransparent, every texel's colour 0.
Its alpha is 63 at the edges and falls to about 35 at (1, 1).

**DisplayBlendPrevious** draws nothing unless the view is active (`+4`),
has a blur, and its target is active. It sets byte 79 of the other screen
buffer's TextureInfo (`GetTextureInfo` of gp-24920, which
`eSwapScreenBuffers` swaps each frame) to 1, semitransparent, so `Render`
blends it, and draws that buffer, the last frame's picture, over the
scissor:

- ALPHA_1 `A = Cs, B = Cd, C = Ad, D = Cd`: `(Cs - Cd) * Ad + Cd`, the
  last frame by the mask. `SunPoly` 1, `ApplyAspectRatio` 0, z `MaxZ`.
- V0 to V3 the scissor's corners, clockwise from the top left.
- The UVs over 512 (`lui 0x3b00`): u from `(x0 + 0.5) / 512` to
  `(w - 0.5) / 512`, v from `(y0 + 0.5) / 512` to `(h - 0.5) / 512`. The
  far edge is `w`, not `x0 + w`: the same for a view at the origin.

Each frame the edges keep some of the frame before, which kept some of
the one before that: a moving camera leaves trails at the edges and none
in the middle, and going forward the trails run out from the middle. With
the view-on's 160 the corners keep `63 * 160 / 128 = 78`, 0.61 of the
last frame; with the nitro's 204, 100, 0.78.

## On the 3DS

`radialblur.c` builds the ePolys (`radialblur_mask_polys`,
`radialblur_previous_poly`), and `trackview.c`'s `display_radial_blur`
draws them where `eDisplayFrame` does, after `georender_set_fog(NULL, 0)`
and before `display_rvms`:

- The quads go through `epoly_screen`, as `render_epoly`'s do, with
  `GEO_BLEND_KEEP`: colour `(0, 1)`, alpha `(1, 0)`, the source's alpha
  into the target. RADIALBLUR is semitransparent, so no alpha test. The
  combiner's scale of 2 does the GS's `>> 7`: 63 is 126 in the pack,
  times 160 over 255, twice, is 0.62.
- The last frame is a copy of the top screen: after the blend, what is
  drawn so far goes to the GPU (`hangwatch_gpu_send_now`, whether the
  frame goes in parts or not), and `GX_TextureCopy` copies the 240 by 400
  buffer, tiled, into a 256 by 512 RGBA8 texture in the linear heap, two
  tiles' gap at the end of each row. It is made at the blur's first frame
  and freed with the track. A frame with no blur, or no room, empties it,
  and the next blur's first frame draws the mask alone.
- The last frame draws with `GEO_BLEND_DEST_ALPHA`: colour
  `(DST_ALPHA, ONE_MINUS_DST_ALPHA)`, alpha `(1, 0)`. Its UVs are the
  PS2's over 512, put on the top screen as the vertices are and from there
  into the copy, whose columns run up the screen (`s = (240 - y) / 256`)
  and rows across it (`t = x / 512`).
- Retail copies nothing: its other buffer is the whole last frame, the
  mirror and the HUD too. The 3DS copy is the view before its mirror and
  HUD, which so leave no trails. `render_epoly`'s half pixel past the
  middle leaves the last column out of both, as on the PS2.

The race's log line counts them: `race: radial blur N frames blended, M
failed` (no RADIALBLUR, or no room in the command buffer).

Seen in Azahar (2026-10-20) with a test build that turned it on for the
whole of a SkipFE race at the nitro's alphas: 148 of 150 frames blended,
none failed; trails at the edges and the middle sharp, the HUD and the
mirror clean. A second test build drew the copy opaque over the view:
the picture stayed upright and in place, so the copy's UVs are right.
Neither is in the game. The nitro is a cop's, in Be A Cop alone
(`realdriver.c`), so a race shows the blur in a zone, in the replays
and with the Motion Blur egg (`stomper.md`).

## The check

`tools/radialblur_check.py` runs retail's nine functions above in mipsemu,
with `ePoly::Render` printing each poly, against a host build of
`radialblur.c`: every coordinator state with each player, on and off by
player, by view and by the replay's, the alphas at the nitro's, the edges
and past them, and the draws of every view, active or not, with or
without a blur, its target active or not, a blur on views 0, 3 and
others, and 40 scissors at random, odd,
off the origin and negative. Facts checked in the image: the call order
in `eDisplayFrame`, that `RadialBlurOnOff(bool, int)` has no `jal` caller, the
byte 79 store, and the constants 160, 255 and 1/512.

    python tools/radialblur_check.py           # 335 steps, 3757 lines, 0 differ; 6 facts
    python tools/radialblur_check.py --mutate  # 43 mutations, 43 caught
