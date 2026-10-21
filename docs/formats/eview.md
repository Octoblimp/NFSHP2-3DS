# eView

This is task 27's twenty-second slice: `eView.obj` (0x00106650 ..
0x001075a8), the renderer's record of one view of the world, and the words
beside it in `EcstasyE.obj` that it needs:

- `CalculateH` (0x00103ce0), `eGetRenderTarget` (0x00104d00) and
  `eRenderTarget::SetupMatrixPacks` (0x00104d18);
- `CreateViewMatricies` (0x0010d268);
- the static constructor's share of the cameras and the views (0x00114098,
  up to the texture downloader at 0x001142ac);
- the view modes, the render target table and the screen's globals.

A view is a camera, the matrices the renderer made from that camera this
frame, and the render targets it draws into. The cull (`scenerycull.md`)
reads the camera, `H`, the id, `WorldViewMatrix` and
`WorldScreenClipMatrix`. `StuffScenery` hands `WorldLightContext` to the
models it draws.

The port is in `3DS Files/source/`:

- `eview.{c,h}`: the table, the render targets, the lookups, the movers'
  lists and the view modes;
- `eviewmatrix.{c,h}`: the projection, the frame's matrices, the pixel
  sizes, the screen position and the light context.

`tools/eview_check.py` cross-checks both against the image, through
`tools/src/eview_test.c`.

## The records

These layouts come from `.mdebug`.

**eView**, 128 bytes (type#2524). The table of ten is at 0x002ab230, and
`eGetView(id)` (0x001071f0) is `&table[id]`.

| Offset | Field | |
|---|---|---|
| 0 | `ID` | |
| 4 | `Active` | a byte |
| 5 | `LetterBox` | a byte |
| 6 | `OverrideRendering` | *retail's*, a byte: set, with the word at 116, by `NisManager::EnableOverrideRendering` (0x001b1ce0) for the view a NIS takes over, and cleared by `DisableOverrideRendering` (0x001b24a8). `RenderSkids` draws nothing in such a view. The NIS player is not ported, so it stays 0 |
| 8 | `H` | the focal length in the PS2's pixels |
| 12, 16 | `NearZ`, `FarZ` | this frame's planes |
| 20 | `FovBias` | 1 from the constructor; nothing here writes it again |
| 24 | `FovDegrees` | |
| 32 | `ViewDirection` | the camera's, copied |
| 48, 52 | `pRenderTarget0`, `pRenderTarget1` | |
| 56 | `pCamera` | |
| 60 | `CameraMoverList` | a list head: next, prev |
| 68 .. 96 | eight matrix pointers | see "The frame's matrices" |
| 100 | `WeatherQueryCounter` | |
| 104 | `pBlendMask` | |
| 108 | `WorldLightContext` | |
| 112 | `BlackAndWhiteMode` | |

**eRenderTarget**, 1168 bytes (type#3199). The table of 22 is at
0x002c9a20, zero in the image; `SetScreenBuffers` fills it. The fields
this slice touches:

| Offset | Field |
|---|---|
| 8 | `Active` (a word) |
| 20 .. 32 | `ScissorX`, `ScissorY`, `ScissorW`, `ScissorH` |
| 84, 88 | `AspectRatioX`, `AspectRatioY` |
| 100 | `FovBias` |
| 1136, 1140 | `MatrixPack0`, `MatrixPack1` |
| 1144 .. 1160 | `WorldClip`, `WorldView`, `ClipScreen`, `VUClipScreen`, `VUClipScreen1` |

**eRenderTargetMatrixPack**, 192 bytes (type#4358): `WorldView`,
`WorldClip` and `VUClipScreen`, which is what the VU1 microcode is handed.

**eLightContext**, 288 bytes (type#3201): three 4x4 matrices for the
lights' colours, directions and positions, the eye at 192, `NumLights` at
208, `SunlightIntensity` at 212, and `EnvMapMatrix` at 224.

## The globals

| Address | Name | Image |
|---|---|---|
| 0x00322860 | `MainDraw0Context` | `&RenderTargets[16]` |
| 0x00322894 | the current view (gp-25436) | 0 |
| 0x00322898 | `CurrentViewMode` | 0 |
| 0x0032289c | `RenderingViewMode` | 0 |
| 0x003228a0 | `TweakerViewMode` | 0 |
| 0x003227c8, 0x003227cc | `ScreenWidth`, `ScreenHeight` | 512, 448 |
| 0x00322920, 0x00322924 | `ClipVolumeScaleX`, `Y` | 0.5, 0.5 |
| 0x00322928, 0x0032292c | `CenterX`, `CenterY` | 2048, 2048 |
| 0x00322930, 0x00322934 | `ZMin`, `ZMax` | 0x40000010, 0x400ff000 |
| 0x00322938, 0x0032293c | `ZMin1`, `ZMax1` | 0x40000040, 0x400ffff0 |
| 0x00325300 | `aBaselineFovMip` | 16384 from the constructor |
| 0x00325302 | `aBaselineFovZ` | 9102 from the constructor |
| 0x002aa150 | `DefaultMatrixPack` | 0 |
| 0x002d6170 | `hack_man_matrix` | 0 |
| 0x002dfdf0 | `SunPosition` | 0; the sun sets it |

The projections are in the GS's coordinates: a 4096-pixel square centred
on (2048, 2048), with the screen in its middle, and depths between `ZMin`
and `ZMax`. 9102 is 50 degrees, which the compiler folded from `50 *
65536 / 360` (the constructor still has the divide's zero check).

## The static constructor, and eInitViews

`_GLOBAL_$I$FloatingVBlankTimeMin` (0x00114098) runs the four `Camera`
constructors, 448 bytes apart from 0x002a9a50: the flailer's, player 1's,
player 2's and the mirror's. It sets `aBaselineFovZ`, clears two tables of
other things, sets `aBaselineFovMip`, and constructs the ten views.
`eView::eView` (0x00106650) links the list head to itself, zeroes all 128
bytes with `bMemSet` (which clears the head too), links the head again,
and sets `FovBias` to 1. The port calls `eview_static_init` first in
`sinit_run`.

`eInitViews` (0x001070f8) wires views 0 to 3:

| View | ID | Target 0 | Target 1 | Camera | Active |
|---|---|---|---|---|---|
| 0 | 0 | 0 | 3 | the flailer's | 1 |
| 1 | 1 | 1 | 4 | player 1's | left |
| 2 | 2 | 2 | 5 | player 2's | left |
| 3 | 3 | 7 | left | the mirror's | left |

"Left" means eInitViews does not write it. Views 4 to 9 are the six
environment maps, and eInitViews leaves them alone.

`eGetViewIDName` (0x00107010) gives `EVIEW_NONE` for -1,
`EVIEW_FLAILER`, `EVIEW_PLAYER1`, `EVIEW_PLAYER2`, `EVIEW_PLAYER1_RVM` and
`EVIEW_ENVMAP0F`, `R`, `B`, `L`, `U`, `D` for 0 to 9, and
`EVIEW_UNKNOWN(?)` for anything else. `eGetCurrentCamera` (0x00107218) is
the current view's camera, or NULL when there is no current view.

## The movers, and the view mode

A view's `CameraMoverList` holds the movers looking through it, by the
8-byte link at the start of each `CameraMover`. `AttachCameraMover`
(0x00106b18) puts the mover at the head. `UnattachCameraMover`
(0x00106b38) unlinks it from its neighbours and never reads the view it
is given. Both then call `eUpdateViewMode` (0x00107240), which sets
`CurrentViewMode` from which views have a first mover:

| Player 1 | Player 2 | Mirror | Mode |
|---|---|---|---|
| yes | yes | either | 3 |
| yes | no | yes | 2 |
| yes | no | no | 1 |
| no | either | either | 0 |

A list whose head reads NULL counts as empty.

`MaybeChangeViewMode` (0x00107310) cuts the render targets for the mode.
The mode to draw is `TweakerViewMode` when that is non-zero, and
`CurrentViewMode` otherwise. When it differs from `RenderingViewMode`, it
first waits for the GS (`eWaitUntilRenderingDone`, 0x00110770, a seam in
the port), then updates `RenderingViewMode`. The cut happens every call,
whether the mode changed or not.

The targets are player 1's and player 2's first, their seconds (each
falls back to the first when there is none), and the mirror's. The screen
is `MainDraw0Context`'s scissor, `w` by `h`:

| Mode | Player 1 | Player 2 | Mirror |
|---|---|---|---|
| 0, 1 | 0, 0, w, h | 0, 0, 0, 0; off | 0, 0, 0, 0; off |
| 2 | 0, 0, w, h | 0, 0, 0, 0; off | 0, 0, 256, 64; on |
| 3 | 0, 0, w, h >> 1 | 0, h >> 1, w, h >> 1; on | 0, 0, 0, 0; off |
| 4 | 0, 0, w >> 1, h | w >> 1, 0, w >> 1, h; on | 0, 0, 0, 0; off |

Each "on" or "off" sets both the target's `Active` and its view's. Player
1 is always on. A mode past 4, or below 0, cuts nothing. The shifts are
arithmetic, so a negative size rounds down. The stores go in the listing's
order: the three first targets, then the two seconds, then the flags. That
order only shows when two of the targets are the same one, and the port
keeps it.

## The projection

`CalculateH(fov)` (0x00103ce0) is the focal length in pixels:
`(ScreenWidth >> 1) / tan(fov / 2)`, or 10 when the tangent is 0. The
tangent is `bSin(half) / bCos(half)` with `half = fov >> 1` as a u16, and
that is how every tangent below is taken.

`CreateViewMatricies(view, a, b, c, d, e, nearz, farz, e_farz)`
(0x0010d268) works from the view's camera and its first render target:

1. **The bias.** `tan(aBaselineFovMip / 2) / tan(fov / 2)` goes into both
   targets' `FovBias`; the second only when there is one.
2. **The planes.** Players 1 and 2 (`ID - 1 < 2`, unsigned) have the near
   plane scaled by `tan(aBaselineFovZ / 2) / tan(fov / 2)`, and keep the
   depth between the planes. This is skipped when the view's first mover
   drives or is the bumper camera. A non-zero `nearz` or `farz` then
   overrides that plane.
3. **The view.** `NearZ`, `FarZ`, `H = CalculateH(fov)`, `FovDegrees =
   fov * 0.0054931640625` (fov as an int) and `ViewDirection`.
4. **a, view to screen.** With `span = far - near`:
   `a[0] = AspectRatioX`, `a[5] = AspectRatioY`, `a[8] = CenterX / H`,
   `a[9] = CenterY / H`, `a[10] = (-ZMax * near + ZMin * far) / span / H`,
   `a[11] = 1 / H`, `a[14] = far * near * (ZMax - ZMin) / span / H`. A twin
   with `ZMin1` and `ZMax1` feeds d.
5. **The clip volume.** `gx = ScissorW * ClipVolumeScaleX` and `gy`
   likewise. For e, `cx = min(ScissorW / 2, gx)` and `cy` likewise.
6. **b, view to clip**, from gx and gy: `b[0] = 2n / 2q`, `b[5] = 2n / 2p`
   (with `p = near * gy / H`, `q = near * gx / H`), `b[10] = (far + near) /
   (far - near)`, `b[11] = 1`, `b[14] = -2 * far * near / (far - near)`,
   `b[15] = 0`.
7. **c and d, clip to screen.** b's inverse, taken by hand (`1 / b[0]`,
   `1 / b[5]`, 0, `1 / b[14]`; row 3 is `0, 0, 1, -b[10] / b[14]`),
   times a for c, and times a's twin for d.
8. **e**, view to a clip volume the size of the screen: b's shape from cx
   and cy, with `e_farz` for the far plane when it is non-zero.
9. Last, `a = b * c`.

## The frame's matrices

`eView::CalculateViewMatricies(nearz, farz, e_farz)` (0x00106700) runs
once a frame for each active view. It takes 512 bytes of frame memory
(`eframe.h`):

| Offset | Matrix | |
|---|---|---|
| +0 | `WorldView` | the camera's matrix |
| +64 | `WorldClip` | `WorldView * b` |
| +128 | `WorldScreen` | `WorldView * a` |
| +192 | `WorldScreenClip` | `WorldView * e` |
| +256 | `ClipScreen` | c |
| +320 | `ViewScreen` | never written |
| +384 | `VUClipScreen` | c's diagonal and row 3, then c⁻¹'s |
| +448 | `VUClipScreen1` | the same from d |

Each `VUClipScreen` row pair has a zero after the diagonal. The view's
eight pointers go to those, and each render target gets five. Then
`SetupMatrixPacks` (0x00104d18) takes both 192-byte packs from frame
memory before filling either. It copies `WorldView`, `WorldClip` and
`VUClipScreen` into the first pack, and the same with `VUClipScreen1` into
the second. With no frame memory, every pointer is `eMathIdentityMatrix`
and nothing is inverted. A pack the frame memory cannot give is
`DefaultMatrixPack`.

The frame malloc's test is `pos + n < end`, and a failure does not move
`pos`. So a block that fails can leave room for the packs after it.
`tools/eview_check.py` runs the frame memory out at each of the five
allocations.

## The rest

- `CalculateLocalToScreenClip` (0x00106a20) and `CalculateLocalToClip`
  (0x00106a38) are `local * WorldScreenClip` and `local * WorldClip`.
- `BiasMatrixForZSorting(m, scale)` (0x00106a50) scales m about the eye:
  m's row 3 moves to `eye + (row 3 - eye) * scale`, and m becomes m without
  its translation, times the scale and the move. Nothing happens without a
  camera.
- The three `GetPixelSize` return how many pixels across a thing is, by
  `H` over its distance, truncated:

  | Form | Address | |
  |---|---|---|
  | `(r, d)` | 0x00106b50 | `r * H / d` while `r / 2 < d`, else `2H` |
  | `(point, r)` | 0x00106b98 | from the eye, less r; 0 when behind the eye by more than r; else as above |
  | `(min, max)` | 0x00106c90 | the box's centre and half its diagonal; `r * H / (dist - r)` while `r < dist - r`, else `H`, not `2H` |

  The second calls `bGetTicker` and throws the answer away. The port
  leaves that call out.
- `GetScreenPosition` (0x00106d98) runs the point, with w = 1, through
  `WorldScreen` and the divide. It then moves x and y from the GS's square
  to the first target's scissor: `(x - 2048) + ScissorW / 2`, a C divide
  that rounds toward zero. z is the depth, and the fourth word is left
  alone. `GetScreenWidth` and `GetScreenHeight` are the scissor as floats.
- `SetupWorldLightContext` (retail 0x00107900, the demo's 0x00106e98)
  clears `WorldLightContext` and returns when there is no camera.
  Otherwise it takes 288 bytes of frame memory, and returns with NULL
  stored when there are none. The eye is 10 units back along the camera's
  z column and 4 up (the demo's 9 and 7). It calls
  `elSetupLightContext(lc, eMathIdentityMatrix, hack_man_matrix, eye,
  view)`: 1928 bytes of lighting that belong to the renderer, and a seam in
  the port. Then it makes a look-at from `SunPosition` at the origin, with
  z up, multiplies it by an identity, and stores it in
  `LocalLightPositions` (+128), which no VU1 program reads. The demo's
  went into `EnvMapMatrix`, so in retail the world's environment pass
  keeps the matrix `elSetupLightContext` made from `hack_man_matrix`, as a
  car's does. tools/eview_check.py runs retail's.

  `eDisplayFrame` calls it for views 1 to 3; the port does not.
  `StuffScenery` hands the context only to scenery drawn in place, and no
  in-place solid on any track has a lit (0x80) or environment-mapped
  (0x100) strip. The three solids that do, `TRACK_HELICOPTER`,
  `FIRETRUCK_00` and `XB_GASTRKTANK_L1A_00`, sit around their origin and
  are drawn with a matrix, which gets no light context.

## What the handheld does with it

The port keeps the GS's coordinates as they are. The cull and the level of
detail are measured in the PS2's pixels, and their thresholds (a 2-pixel
cut, the LOD distances) were tuned in them. The 3DS renderer takes the
camera and `H` from the view and builds its own projection for the
400-by-240 screen. It does not use a or `WorldScreen`.

## Divergences

- `~eView` (0x001066a8) is not ported. The global destructors run it at
  exit, which the handheld never reaches.
- `GetPixelSize(point, r)` drops its `bGetTicker` call. The call's answer
  was never used.
- `eWaitUntilRenderingDone` and `elSetupLightContext` are seams
  (`gEWaitUntilRenderingDoneFn`, `gElSetupLightContextFn`) that do nothing
  when NULL.
- The view id test is `(uint32_t)ID - 1 < 2`, written so that an id of
  `INT_MIN` is defined in C. The listing's `addiu` and `sltiu` give the
  same answer.

## The check

`tools/eview_check.py` runs the shipped functions under `tools/mipsemu.py`
and the port under `tools/src/eview_test.c`, walks both through one
script, and diffs the transcripts. The static constructor runs in place,
from its first word to the texture downloader. The two seams are stubs in
the model that print their calls. The frame memory is 2 KB, filled with a
pattern before each use, so whatever a call leaves alone shows up.

The script covers:

- the constructor's cameras, fields of view and views; eInitViews; every
  name, and some past the ends; the lookups and the current view;
- movers on and off each view in every order, including off the middle of
  a list and through the wrong view; the eight ways players 1 and 2 and
  the mirror can have movers; a head that reads NULL;
- MaybeChangeViewMode across 125 combinations of the three modes, with
  every target scrambled first; odd, negative and zero screens; players
  without a second target; shared targets, which show the order of the
  stores; the frame drawn into four other targets;
- CalculateH over 54 fields of view and 11 screen widths, odd and
  negative;
- CreateViewMatricies over 160 random cameras, targets and screens, then
  every view id against every mover type and override, 341 in all;
- CalculateViewMatricies and SetupMatrixPacks with the frame memory
  running out at each allocation, one target, two, and one twice;
- the local-to-clip products, including aliased ones; the bias; the three
  pixel sizes on both sides of their branches; the screen position with
  odd and negative scissors; the light context with and without a camera
  and frame memory;
- a frame as the game makes one.

Result: 12 scenarios, 2,103 ops, 15,454 lines, 0 differ.

The check also found one bug outside this slice. The camera's eye is a
subtraction from VU0's constant (see `camera.md`), and the port had
negated it. That gave the default eye `-0` in x and y where the disc has
`+0`.

The mutation pass (`--mutate`) makes 153 mutations across `eview.c` and
`eviewmatrix.c`: 152 caught, 1 equivalent, 0 unexplained. The equivalent
one gives GetScreenPosition's vector the point's own fourth word for its
w; `eRotTransPers` forces w to 1, so that word is never read.

Two survived the first pass. One was the equivalent. The other was
`r * (H / d)` for `r * H / d`, and the two orders only truncate to
different pixel counts when one of them lands exactly on a whole number.
A search in float32 found such a pair at H = 256: r = 0.0061383927 and
d = 1.5714285 give exactly 1 one way and just under it the other, and
r = 0.02734375 and d = 7 give the reverse. Both are in the script now.
