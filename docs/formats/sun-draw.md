# The sun's draw

This is task 27's twenty-seventh slice, the draw half of `Sun.obj`:

- `StuffSun` (0x00123ec0, 1,540 bytes) and `StuffSunGlare` (0x001244c8,
  1,556 bytes);
- the glare's globals, and the 15 `SunZBuffer`s at 0x002dfe00;
- `ePoly`, the engine's one screen-space quad: its constructor,
  `__5ePoly` (0x0010e480), and what `ePoly::Render` (0x0010e580) does,
  which is a seam here.

`docs/formats/sky-sun.md` has the other half: the sun chunk, its loader,
and the five textures.

The port is in `3DS Files/source/`:

- `sundraw.{c,h}`: StuffSun, StuffSunGlare and their globals;
- `epoly.{c,h}`: ePoly, its constructor, and the Render seam;
- `trackview.c`: the 3DS side of the seams, which is `render_epoly`,
  `transfer_zbuffer_rect` and `trackview_read_depth`;
- `georender.c`: `georender_draw_quad`, the quad itself.

`tools/sun_check.py` runs StuffSun, StuffSunGlare and the constructor in
mipsemu, and `tools/src/sun_test.c` runs the port the same way:

- 91 scenarios, 2,680 lines, and none differ;
- 115 mutations: 114 caught and 1 equivalent. The equivalent one is
  `rect_end_x_le`, which gives 32 - 0 = 32 either way.

## ePoly

160 bytes (.mdebug type #2948):

| Offset | Field | |
|---|---|---|
| 0 | `Node[16]` | a `bTNode<ePoly>`, then pad |
| 16 | `Vertices[4]` | `bVector4`s in the render target's pixels |
| 80 | `UVs[4][3]` | u, v, q |
| 128 | `Colours[4][4]` | r, g, b, a; 0x80 is 1.0 |
| 144 | `AlphaA` .. `AlphaD` | ALPHA_1's A, B, C and D |
| 148 | `AlphaFix` | ALPHA_1's FIX |
| 149 | `AlphaEnabled` | |
| 150 | `SunPoly` | |
| 151 | `ApplyAspectRatio` | |
| 152 | `Flailer` | |
| 156 | `pDynamicFrameMemory` | the packet, when Render is asked to keep it |

The constructor does the following:

- It puts the vertices on a 64-pixel square at the top left, at z 65535
  (gp-32684) and w 0.
- It gives the UVs the whole texture, with q 1, and every colour 0x80.
- It sets ALPHA_1 to (Cs - Cd) * As + Cd with FIX 128, and sets
  AlphaEnabled to 0.
- It sets ApplyAspectRatio to 1, and SunPoly and Flailer to 0.
- It leaves the first 16 bytes as they are.

The destructor (0x001149f0) runs bTNode's destructor and then bNode's.
Neither does anything to a poly on the stack, so the port has no call for
it.

## StuffSun

eDisplayFrame calls `StuffSun(view)` once per view (0x00112ecc). The call
comes after StuffScenery and DrawNisObjects, and before RenderClans.
StuffSun calls StuffSunGlare first. Then it returns unless there is a sun
chunk and the view is view 1. If both hold, it does these steps.

1. **It projects the sun.**
   - The screen position is `eRotTransPers(WorldScreenMatrix, pos)`, and
     the eye position is `eMulVector(WorldViewMatrix, pos)`.
   - The target's pixels are `sx = (screen.x - 2048) + (ScissorW >> 1)`,
     and the same for y.
   - SunPosX and SunPosY, when either is not 0, replace both.
   - It returns if eye z is under 0, which means the sun is behind the
     view.
2. **It checks that the sun is on the target.** `m` is the largest
   CENTER layer's Size, and never under 0. StuffSun returns unless
   `-m <= sx <= w + m` and `-m <= sy <= h + m`.
3. **It counts the sky.** This is over the last frame's rect in the
   target's SunZBuffer (by the target's ID), from StartY to EndY and
   StartX to EndX. It counts the entries under 64, then multiplies by
   1/1024.
4. **It draws each layer** that has a texture and an IntensityScale that
   is not 0. It builds one ePoly for all of them: the constructor,
   AlphaEnabled 1, AlphaFix 64, and the UVs again.
   - `frac = (sx + m) / (w + m + m)`
   - `angle = (u16)(Angle + trunc(SweepAngleAmount * frac * 65536))`
   - `half = Size * 0.5`, `a = half * (sin + cos)`,
     `b = half * (cos - sin)`, with bSinBam and bCosBam of the angle
   - The alpha is `trunc(-IntensityScale * 128)` when IntensityScale is
     negative. Otherwise it is `trunc(count * (IntensityScale * 128))`.
   - The centre is `(sx + 0.0 + OffsetX, sy + 0.0 + OffsetY)`. The
     `+ 0.0` makes a -0 a +0.
   - The vertices are V0 `(cx - a, cy - b)`, V1 `(cx + b, cy - a)`,
     V2 `(cx + a, cy + b)` and V3 `(cx - b, cy + a)`.
   - ALPHA_1 is (Cs - Cd) * As + Cd for BLEND, and Cs * As + Cd
     otherwise. SunPoly is set, and the layer goes to
     `Render(poly, texture, 0)`.
5. **It asks for this frame's rect.**
   - `x0 = trunc(sx - 16)` and `y0 = trunc(sy - 16)`, then
     `eTransferZBufferRect(zb, x0, y0, 32, 32)`.
   - StartX is `-x0` when x0 is under 0, and 0 otherwise.
   - EndX is `32 - (x0 + 32 - ScissorW)` when that is past the target,
     and 32 otherwise. The sums wrap as the image's unsigned ones do.
   - The same goes for y.

## StuffSunGlare

This is the white-out that an explosion starts. `Munition::ExplodeWarhead`
(0x001b4798) sets bStartGlare for a MunitionsType of 1. Its globals:

| Address | Name | |
|---|---|---|
| gp-24140 | `SunPosX` | |
| gp-24136 | `SunPosY` | |
| gp-24132 | `GlareDist` | 1.0 |
| gp-24128 | `bStartGlare` | |
| gp-24124 | `bResetGlare` | |
| gp-24120 | `GlareStartTime` | seconds |
| gp-24116 | `iGlarePhase` | |
| 0x00290e50 | `PhaseTimes[4]` | 0.05, 0.2, 0.65, 5.0 |

It runs these steps:

1. **Reset.** bResetGlare clears the start time and both flags.
2. **Start.** bStartGlare, with `WorldTimer * 0.00025` over 0 and no
   start yet, takes that time as the start. It also clears the flag and
   sets the phase to 0.
3. **Advance.** With no start it returns. Otherwise it works out
   `el = now - start`. When el is past the phase's time, it takes the
   phase's time off el and makes now the start. The phase then goes on
   by one, mod 4.
4. **The phases:**
   - Phase 0 grows: size is `el / PhaseTimes[0]`.
   - Phase 1 holds at size 1.
   - Phase 2 fades: alpha is `1 - el / PhaseTimes[2]`.
   - Phase 3 clears the start, and draws at size 0, which is nothing.
5. **The layers.**
   - The glare sits at the camera's position plus GlareDist along its
     direction, with w 1.
   - The size is multiplied by 1.9 (gp-32204).
   - The projection and the on-target test are StuffSun's.
   - Each layer is drawn as StuffSun draws it, with these changes: half
     is `Size * 0.5 * size`, intensity is `size`, and the fade is
     `alpha`. The view does not matter.

The image reads the layers at SunInfo without checking it, so with no sun
chunk it reads 28 bytes on from NULL. The port returns instead. That is
its one change.

Nothing in the port sets bStartGlare yet, because the munitions are not ported.

## ePoly::Render

Render turns a poly into one GS packet:

- a GIF tag with PRE set;
- PRIM 0x1c, which is a triangle strip, Gouraud and textured. When the
  texture's `IsAnySemitransparencyFlag` is set, PRIM is 0x5c, which adds
  ABE;
- for a SunPoly, 13 registers: one A+D write of ALPHA_1 (0x42) from
  AlphaA..AlphaD and AlphaFix, then ST, RGBAQ and XYZ2 four times. The
  other polys take 12, and their texture's own ALPHA_1.

It also does the following:

- A NULL texture draws nothing.
- A SunPoly's ApplyAspectRatio is cleared, so every later Render of that
  poly skips the aspect ratio.
- With ApplyAspectRatio, x and y are multiplied by the target's
  AspectRatio2DX and 2DY. Without it, an x past the middle moves half a
  pixel left.
- XYZ2 is x and y plus `2048 - half the scissor`, in 12.4 fixed point
  with the fraction dropped.
- z is the vertex's z, or for a Flailer a table's.
- The strip's order is V0, V1, V3, V2.
- The packet goes on the texture's list. When the texture's
  ApplyAlphaSorting is set, it goes on the alpha sort by V0's z instead.
  The sun's textures are order 7, the last list.

The packet writes no TEST_1 or ZBUF. The main target's TEST_1 stays in
force, which is alpha GREATER 0x30 and Z GEQUAL
(`docs/formats/track-render.md`).

## The Z buffer

FetchZBuffer (0x0010f6f0) reads the Z buffer back with a BITBLTBUF of
0x3a080000: 512 wide (SBW 8), as PSMZ16S (SPSM 0x3a).
eTransferZBufferRect (0x00110610) queues its rect the same way: PSM 58,
and `w * h / 8` quadwords. So each SunZBuffer entry is a 16-bit Z.

The Z comes from the projection that `eview_calculate_view_matrices`
builds. It maps the view's near plane to ZMax and the far plane to ZMin:

- ZMax is 0x400ff000, a float in [2, 4). Its mantissa is the Z the GS
  gets, 0x0ff000.
- ZMin is 0x40000010, which gives 16.

Between them, Z is linear in `t = n (f - d) / (d (f - n))` for a depth
`d`. That is the same `t` citro3d's `Mtx_PerspTilt` writes, from 1 at the
near plane to 0 at the far one. The mapping is `Z = 16 + (0x0ff000 - 16) t`.

Under 64 means one of two things:

- the clear, which is what the sky leaves, because it is drawn with the Z
  writes off;
- scenery at the far end of the range. With TRACKB12's planes at 0.5 and
  5,000, that is past about 3.4 km.

The sun's quads are at z 65535. GEQUAL passes that against anything in a
16-bit buffer, so no scenery hides the sun. Only the count fades it,
which is the point of the count.

## On the 3DS

**The quads.** `render_epoly` does what Render does, then maps the
target's pixels to the top screen:

- `x3 = 200 + (x - W/2) * 400 / W / AspectRatioX`
- `y3 = 120 + (y - H/2) * 400 / W / AspectRatioY`

This is the view's own projection, which puts the cull's width across 400
pixels and makes the pixels square. `georender_draw_quad` then draws the
strip:

- through the scenery's shader, with an ortho projection, no light and an
  ambient of 1;
- with the texture modulating the vertex colour at the combiner's scale
  of 2, so that 0x80 is 1.0 as it is on the GS. The packs' alpha is
  doubled on upload already;
- with the poly's blend: ALPHA for (Cs - Cd) * As + Cd, ADD for
  Cs * As + Cd, and SUBTRACT for Cd - Cs * As. There is no blend when the
  texture is not semitransparent;
- with the main target's alpha test, GREATER 0x60 (0x30 doubled), and no
  depth test.

The quads come from a 64-quad ring on the linear heap, which is rewound
once a frame. Each quad is flushed from the data cache as it goes in.

**The Z rects.**

- `transfer_zbuffer_rect` queues the rect with its target's size and
  aspect ratios.
- main() calls `trackview_read_depth` after the next frame's
  `C3D_FrameBegin`, which waits for the GPU, and before the clear. It
  reads each PS2 pixel's centre out of the D24S8 buffer, in the low 24
  bits, and turns the depth into the GS's Z as above.
- Pixels off the target are 0xffff, and StuffSun counts none of them.
- The buffer is the screen on its side in 8×8 Morton tiles. Screen `(x, y)`
  is at buffer `(239 - y, x)`, in rows of 30 tiles.

**The probe** logs the colour and depth words at 15 screen points for the
first frame at each stop. They were compared with the screenshots of
seven stops, with each flip of the mapping tried. The error summed over
the RGB channels was:

| Mapping | Error |
|---|---|
| as written | 531 |
| x flipped | 3,643 |
| y flipped | 5,082 |
| both flipped | 5,931 |

**What Azahar shows.** At every stop the sun is above the frame. At stop
1 it is at y = -42, so its rect is off the target, the count is 0, and
all four layers draw with alpha 0.

`tools/run_azahar_track.ps1` now ends with a `track-sun` shot, which goes
back to stop 1 and looks up. There the whole rect is sky, the count is 1,
and the layers draw at 128, 64, 89 and 40.

The alpha test decides what shows at those values:

- Layer 1 (CENTER at 0.5) passes only where its texture's alpha is over
  0x60, which gives the halo a hard edge.
- Layer 3 (MAJORRAYS at 0.32) never passes. The highest alpha in the sun
  textures is 0x7f, and 0x7f × 40 >> 7 is 39, which is not over 0x30.

The PS2 does both of these the same way: the textures' alpha never goes
past 0x7f, so the doubled upload clamps nothing.

TRACKB12's sun (version 2, at -16384, 800, 6000):

| Layer | Texture | Alpha | Intensity | Size | Offset | Colour | Angle | Sweep |
|---|---|---|---|---|---|---|---|---|
| 0 | CENTER | ADD | 1.0 | 60 | 0, 0 | 255, 200, 100 | 0 | 0 |
| 1 | CENTER | ADD | 0.5 | 320 | 0, 0 | 130, 110, 25 | 0 | 0 |
| 2 | MAJORRAYS | ADD | 0.7 | 800 | -9, 28 | 159, 122, 75 | 0 | 0.2 |
| 3 | MAJORRAYS | ADD | 0.32 | 800 | 28, 9 | 166, 119, 72 | 16384 | 0.2 |

Layers 4 and 5 are empty.
