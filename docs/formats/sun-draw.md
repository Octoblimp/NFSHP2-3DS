# The sun's draw

This is the draw half of `Sun.obj`. It was task 27's twenty-seventh slice,
on the demo's image, and task 36's seventh slice moved it onto retail's.
The addresses here are retail's, with the demo's after them:

    StuffSun               0x001252b0   1,636 bytes   the demo's 0x00123ec0, 1,540
    StuffSunGlare          0x00125918   1,620 bytes   0x001244c8, 1,556
    ePoly's constructor    0x0010f968     252 bytes   0x0010e480
    ePoly::Render          0x0010fa68   1,268 bytes   0x0010e580
    ePoly's destructor     0x00114db8      80 bytes   0x001149f0
    eTransferZBufferRect   0x00111c58     176 bytes   0x00110610
    FetchZBuffer           0x00110d20                 0x0010f6f0
    SunZBuffers[15]        0x002e03d0   4,112 each    0x002dfe00, 2,064 each
    SunGlareInfo           0x002ef4c0     244 bytes   none
    PhaseTimes[4]          0x002ad128                 0x00290e50

`ePoly` is the engine's one screen-space quad. Render is a seam here.

`docs/formats/sky-sun.md` has the other half: the sun chunk, its loader,
the glare's record, and the five textures.

The port is in `3DS Files/source/`:

- `sundraw.{c,h}`: StuffSun, StuffSunGlare and their globals;
- `epoly.{c,h}`: ePoly, its constructor, and the Render seam;
- `eview.{c,h}`: the render target's `MaxZ`, and `eview_set_max_z`;
- `trackview.c`: the 3DS side of the seams, which is `render_epoly`,
  `transfer_zbuffer_rect` and `trackview_read_depth`;
- `georender.c`: `georender_draw_quad`, the quad itself.

## What retail changed

- **The Z buffer is 24 bits.** Its rects come back as 32-bit words, so a
  SunZBuffer is 4,112 bytes. The count takes a word's low 24 bits under 2,
  which only the clear leaves. The demo's buffer was 16 bits, and it
  counted a Z under 64, which far scenery reached too.
- **Each layer has its own z.** StuffSun's first layer is at z 1. GEQUAL
  passes that only over the clear, so scenery in front hides the sun's
  disc pixel by pixel. The other layers, and all of the glare, are at the
  render target's `MaxZ`, over everything. The constructor's z is 0. The
  demo drew every layer at the constructor's 65535.
- **The rect is moved onto the target.** The demo asked for the rect
  where it fell and clipped the part it counted.
- **The glare keeps its own layers and clock.** It draws `SunGlareInfo`,
  four fixed layers that LoaderSun fills, where the demo drew the
  track's. That record is never NULL, so the demo's read through a NULL
  `SunInfo` is gone. The glare times itself in `RealTimer`'s ticks, in a
  `Timer`, where 0 and 0x7fffffff mean it is not set. The demo used
  `WorldTimer`'s seconds, in a float.
- **eTransferZBufferRect needs a race.** It does nothing unless
  `InGameFlag` (gp-21424) is set.

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

- It puts the vertices on a 64-pixel square at the top left, at z 0 and
  w 0. The demo's z was 65535, from gp-32684.
- It gives the UVs the whole texture, with q 1, and every colour 0x80.
- It sets ALPHA_1 to (Cs - Cd) * As + Cd with FIX 128, and sets
  AlphaEnabled to 0.
- It sets ApplyAspectRatio to 1, and SunPoly and Flailer to 0.
- It leaves the first 16 bytes as they are.

The destructor runs bTNode's destructor and then bNode's. Neither does
anything to a poly on the stack, so the port has no call for it.

## StuffSun

eDisplayFrame calls `StuffSun(view)` once per view. The call comes after
StuffScenery and DrawNisObjects, and before RenderClans. StuffSun calls
StuffSunGlare first. Then it returns unless there is a sun chunk and the
view is view 1. If both hold, it does these steps.

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
   StartX to EndX. It counts the words whose low 24 bits are under 2,
   then multiplies by 1/1024. `MaxZ` is read from the target at +116.
4. **It draws each layer** that has a texture and an IntensityScale that
   is not 0. It builds one ePoly for all of them: the constructor,
   AlphaEnabled 1, AlphaFix 64, and the UVs again.
   - The four vertices' z is 1 for layer 0 and `MaxZ` for the others.
     A layer that is skipped sets nothing, so the z always goes with the
     layer drawn.
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
5. **It asks for this frame's rect**, 32 by 32 around the sun, moved onto
   the target. With `x0 = trunc(sx - 16)`:
   - StartX is 0 and EndX is 32 to begin with.
   - When x0 is under 0, EndX is `x0 + 32` and x0 becomes 0.
   - Then, when x0 is past `ScissorW - 33`, StartX is
     `x0 + 1 - (ScissorW - 32)` and x0 becomes `ScissorW - 33`.
   - The same goes for y, with ScissorH. The sums wrap as the image's
     unsigned ones do.
   - It stores the four and calls
     `eTransferZBufferRect(zb, x0, y0, 32, 32)`.

   So StartX..EndX is the part of the rect that was the sun's. The rect
   never reaches the target's last column or row, and on a target under
   33 across both tests fire, which leaves x0 under 0.

## StuffSunGlare

This is the white-out that an explosion starts. `Munition::ExplodeWarhead`
(the demo's 0x001b4798) sets bStartGlare for a MunitionsType of 1. Its
globals:

| Address | Name | | The demo's |
|---|---|---|---|
| gp-23580 | `SunPosX` | | gp-24140 |
| gp-23576 | `SunPosY` | | gp-24136 |
| gp-23572 | `GlareDist` | 1.0 | gp-24132 |
| gp-23568 | `bStartGlare` | | gp-24128 |
| gp-23564 | `bResetGlare` | | gp-24124 |
| gp-23560 | `GlareStartTime` | a `Timer`, RealTimer's ticks | a float, seconds |
| gp-23556 | `iGlarePhase` | | gp-24116 |
| 0x002ad128 | `PhaseTimes[4]` | 0.05, 0.2, 0.65, 5.0 | 0x00290e50 |

`RealTimer` is gp-19608, 4,000 ticks a second; the glare's 0.00025s are
gp-32140 and gp-32136. The start time is set unless it is 0 or
0x7fffffff, as Car's blink has it. StuffSunGlare runs these steps:

1. **Reset.** bResetGlare zeroes the start time and clears both flags.
2. **Start.** bStartGlare, with `RealTimer * 0.00025` over 0 and no start
   set, clears the flag, takes RealTimer as the start, and sets the phase
   to 0.
3. **Advance.** With no start set it returns. Otherwise it works out
   `el = (int32)(RealTimer - start) * 0.00025`. When el is past the
   phase's time, it takes the phase's time off el and makes RealTimer the
   start. The phase then goes on by one, mod 4.
4. **The phases:**
   - Phase 0 grows: size is `el / PhaseTimes[0]`.
   - Phase 1 holds at size 1.
   - Phase 2 fades: alpha is `1 - el / PhaseTimes[2]`.
   - Phase 3 zeroes the start, and draws at size 0, which is nothing.
5. **The layers**, which are SunGlareInfo's.
   - The glare sits at the camera's position plus GlareDist along its
     direction, with w 1.
   - The size is multiplied by 1.9 (gp-32132).
   - The projection and the on-target test are StuffSun's, with `m` from
     SunGlareInfo's CENTER layers.
   - Every quad is at `MaxZ`.
   - Each layer is drawn as StuffSun draws it, with these changes: half
     is `Size * 0.5 * size`, intensity is `size`, and the fade is
     `alpha`. The view does not matter.

SunGlareInfo is zero until a sun chunk loads, and its layers are then
TRACKB12's but for two numbers (`sky-sun.md`). With no chunk ever loaded
every layer has IntensityScale 0, and the glare draws nothing. The port
does what the image does; the demo's port had to stop at a NULL SunInfo.

Nothing in the port sets bStartGlare yet, because the munitions are not
ported.

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
- Z is the vertex's z, truncated. A Flailer's z instead indexes a table
  of floats at 0x002c9e70 (10, 11, 12 ..): entries 20 to 24 are the Z,
  and any other is `MaxZ` less the entry. The sun sets no Flailer.
- The strip's order is V0, V1, V3, V2.
- The packet goes on the texture's list. When the texture's
  ApplyAlphaSorting is set, it goes on the alpha sort by V0's z instead.
  The sun's textures are order 7, the last list.

The packet writes no TEST_1 or ZBUF. The main target's TEST_1 stays in
force, which is alpha GREATER 0x30 and Z GEQUAL
(`docs/formats/track-render.md`). Whether the Z writes are on when the
sun's list draws is the eView retail pass's; the port's quads write none.

## The Z buffer

Retail's is PSMZ24 at block 8192. FetchZBuffer's BITBLTBUF is
0x31082000: SPSM 0x31, SBW 8 (512 wide), SBP 8192. eTransferZBufferRect
queues its rect the same way but reads the words as PSMZ32 (48), with
`w * h / 4` quadwords, the rect at +8 and x, y, w and h at +20 .. +26 of
its record. So each SunZBuffer word is a 24-bit Z under 8 bits of
whatever the buffer holds there; StuffSun masks them off. The demo's two
were PSMZ16S at block 0, with `w * h / 8` quadwords.

**MaxZ.** Retail's eRenderTarget is 176 bytes, the demo's 1,168. Its
`MaxZ`, at +116, is the largest Z the target's buffer holds.
0x00105ac0 sets it each frame, as it builds the target's GS packets:
16777215 (gp-32736) when `ZBufferMode` is PSMZ24 (0x31), and 65535
(gp-32732) otherwise. The port keeps the demo's struct, with `MaxZ` cut
out at retail's offset from the packets' bytes, and `eview_set_max_z`
does that one part of 0x00105ac0.

**The range.** Retail's table at 0x002c9e20 gives each Z mode its
projection's ZMin and ZMax, floats near 2 and 4 whose mantissa is the
GS's Z. PSMZ24's ZMin is 0x40000010, which gives 16, as the demo's was.
The port still builds the demo's projection (ZMax 0x400ff000, 0x0ff000),
the view's near plane at ZMax and its far plane at ZMin. Between them,
Z is linear in `t = n (f - d) / (d (f - n))` for a depth `d`, the same
`t` citro3d's `Mtx_PerspTilt` writes. The rest of the table is the eView
retail pass's.

So under 2 is the clear, or a Z of 1, which is layer 0's. The sky is
drawn with the Z writes off, and all the scenery writes at least ZMin's
16, however far it is.

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
- with the main target's alpha test, GREATER 0x60 (0x30 doubled);
- with no depth write, and the depth test that the poly's Z asks for.

**The quads' Z.** `depth_of_gs_z` runs the range above backwards, from a
GS Z to the PICA's depth:

- A Z at or past the nearest the scenery reaches, as `MaxZ` is, passes
  against anything, so the quad draws with no depth test.
- A Z at or under ZMin, as layer 0's 1 is, is the depth 0, which only the
  clear has. The quad draws GEQUAL, so only over the sky.
- A Z between is the depth that Z has.

The viewer's depth is the Z-buffer's, which is `t` itself, so a GS Z's
depth is its `t`. `georender_draw_quad` maps the depth with a scale of 0
and the quad's depth as the offset, so every fragment has that depth,
and puts the Z-buffer's map back after.
The viewer sets its target's `ZBufferMode` to PSMZ24, since the PICA's
depth buffer is 24 bits, so `MaxZ` is 16777215.

The quads come from a 64-quad ring on the linear heap, which is rewound
once a frame. Each quad is flushed from the data cache as it goes in.

**The Z rects.**

- `transfer_zbuffer_rect` queues the rect with its target's size and
  aspect ratios. It does not test InGameFlag: the viewer is a race's
  view.
- main() calls `trackview_read_depth` after the next frame's
  `C3D_FrameBegin`, which waits for the GPU, and before the clear. It
  reads each PS2 pixel's centre out of the D24S8 buffer, in the low 24
  bits. A depth of 0 is the clear's Z, 0; any other is its GS Z as
  above, at most 0xffffff.
- Pixels off the target are 0xffffff, and StuffSun counts none of them.
  Only a target under 33 across puts part of a rect there.
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

**What Azahar showed on the demo's disc.** At every stop the sun is above
the frame. At stop 1 it is at y = -42, so its rect is off the target, the
count is 0, and all four layers draw with alpha 0.

`tools/run_azahar_track.ps1` ends with a `track-sun` shot, which goes
back to stop 1 and looks up. There the whole rect is sky, the count is 1,
and the layers draw at 128, 64, 89 and 40.

The alpha test decides what shows at those values:

- Layer 1 (CENTER at 0.5) passes only where its texture's alpha is over
  0x60, which gives the halo a hard edge.
- Layer 3 (MAJORRAYS at 0.32) never passes. The highest alpha in the sun
  textures is 0x7f, and 0x7f × 40 >> 7 is 39, which is not over 0x30.

The PS2 does both of these the same way: the textures' alpha never goes
past 0x7f, so the doubled upload clamps nothing. Retail's TRACKB12 has the
same layers with the sun at (-3900, 650, 1300) (`sky-sun.md`), and its
walk in Azahar is still to come.

The demo's TRACKB12 sun (version 2, at -16384, 800, 6000):

| Layer | Texture | Alpha | Intensity | Size | Offset | Colour | Angle | Sweep |
|---|---|---|---|---|---|---|---|---|
| 0 | CENTER | ADD | 1.0 | 60 | 0, 0 | 255, 200, 100 | 0 | 0 |
| 1 | CENTER | ADD | 0.5 | 320 | 0, 0 | 130, 110, 25 | 0 | 0 |
| 2 | MAJORRAYS | ADD | 0.7 | 800 | -9, 28 | 159, 122, 75 | 0 | 0.2 |
| 3 | MAJORRAYS | ADD | 0.32 | 800 | 28, 9 | 166, 119, 72 | 16384 | 0.2 |

Layers 4 and 5 are empty.

## The cross-check

`tools/sun_check.py` runs StuffSun, StuffSunGlare and ePoly's
constructor and destructor on the retail image in mipsemu, with IEEE
floats, and `tools/src/sun_test.c` runs the port the same way. Every
other callee is a stub that prints its arguments; Render prints the poly
field by field, and eTransferZBufferRect its rect. After each step both
sides dump the glare's globals, RealTimer, and each SunZBuffer's rect.
Each step also sets WorldTimer to what RealTimer is not, so a read of
the demo's clock shows. Retail's image is stripped, so the checker's
addresses are read off its code, and each one that `retail_model`'s map
pairs with the demo's is checked against the map.

The scenarios cover:

- TRACKB12's sun and layers of every kind: BLEND and ADD, a NULL
  texture, IntensityScale 0, negative and large, and every angle;
- view IDs other than 1, and no sun chunk;
- the sun behind the view, at -0 and NaN, and off each edge and on it;
- SunPosX and SunPosY, alone, together, -0 and NaN;
- the count over each shape of rect and each kind of Z word (the high
  byte set, 0, 1, 2 and 0xffffff), and the rect moved onto the target at
  each edge, on targets of 20 by 40, 32 and 33 too;
- `MaxZ` at 16777215, 65535, 0.5, -0 and NaN;
- the glare from its start through each phase and around again, the
  reset, RealTimer running back and wrapping past 0x80000000, a start of
  0x7fffffff and 0x7ffffffe, GlareDist, SunGlareInfo against the track's
  layers, and SunGlareInfo with no sun chunk.

Results: 115 scenarios, 3,427 lines, 0 differ. All 154 mutations are
caught. `layer_z_first_drawn` gives layer 0's z to whichever layer draws
first; a scenario whose layer 0 is skipped tells them apart.

    python tools/sun_check.py
    python tools/sun_check.py --mutate [--only a,b]
