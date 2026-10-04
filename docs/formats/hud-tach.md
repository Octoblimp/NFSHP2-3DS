# The tach's red band (step 8m-4c-3)

Both of the HUD's tachometers have a red band that runs from the car's
red line to the top of the dial. In INGAMEB the band is a bitmap whose
Animation is TACH_GRADIENT (10):

| gradient | hash | group | view |
|----------|------|-------|------|
| TACHGRADIENT | `0x39c9eead` | `457755c9` | the chase view (GAUGES_OUTSIDE) |
| TACHGRADIENT2 | `0x7307c47f` | `cd086c25` | the bumper view (GAUGES) |

Each gradient keeps its own texture: TACHGRADIENT `454e4a1f` and
TACHGRADIENT2 `39c9eead`. SetHudFeatures (`hud-features.md`) changes the
speedo's, the shadow's and the tach's textures, not the gradients'. It
hides TACHGRADIENT2 for a car whose tach is in its speedo. The checker
runs the gradients at 112 × 112 and 104 × 40.

RenderHud turns the gradient to the red line each frame
(`hud-render.md`). The port used to draw the gradient as an ordinary
quad, so the whole ring was red. Retail never draws it as a quad. It
cuts a fan out of the bitmap, from the centre, that ends at the
gradient's Rotation.

| function | address | size | port |
|----------|---------|------|------|
| InitializeFlailerTachometer | `0x001434a0` | 952 | `flailer_initialize_tachometer` |
| RenderFlailerTachometer | `0x00143858` | 1272 | `flailer_render_tachometer` |
| next_power_of_2 | `0x0013ff60` | 68 | `next_power_of_2` |

All three are in `hudtach.c`. `main.c` binds
`gInitializeFlailerTachometerFn`, which SetHudFeatures calls when it
finds the gauges (`hud-features.md`). `uirender.c` calls Render as it
draws the bitmap.

## The point list

FlailerTachometerPointList is 180 bytes: nine points of 20, each
(x, y, z, u, v). Player keeps one at +796. Init fills it, and the
gradient keeps its address at +108.

## InitializeFlailerTachometer(needle, gradient, list)

The needle is not read. Init asks for the gradient's TextureInfo,
GetTextureInfo(hash, 1, 0), caches it at +84, and reads the image's
width and height from the halfwords at +36 and +38. Then:

- pw and ph are next_power_of_2 of w and h;
- sw = (int)(w × ScaleX) and sh = (int)(h × ScaleY), w and h converted
  unsigned;
- umax = w / pw and vmax = h / ph, also unsigned;
- cx = X + (float)(sw / 2) and cy = Y + (float)(sh / 2), with signed
  division; right = X + sw and bottom = Y + sh;
- uhalf = 0 + umax × 0.5 and vhalf = 0 + vmax × 0.5;
- z is the Z byte (+42), signed.

The nine points are the centre, then the bottom middle and on
clockwise:

| point | x | y | u | v |
|-------|---|---|---|---|
| 0 | cx | cy | uhalf | vhalf |
| 1 | cx | bottom | uhalf | vmax |
| 2 | X | bottom | 0 | vmax |
| 3 | X | cy | 0 | vhalf |
| 4 | X | Y | 0 | 0 |
| 5 | cx | Y | uhalf | 0 |
| 6 | right | Y | umax | 0 |
| 7 | right | cy | umax | vhalf |
| 8 | right | bottom | umax | vmax |

The UVs are over the power-of-two allocation, as the GS sees the
texture.

next_power_of_2 answers 0 for 0. Otherwise it starts at 2 and doubles
once for each bit of (n − 1) >> 1, so 1 and 2 both give 2.

## RenderFlailerTachometer(gradient, list)

- a = (int)(360 − (float)Rotation), q = a / 90 and r = (float)(a % 90).
- If 45 < r, then r −= 45 and s = 1. Otherwise s = 2.
- t = 1 − r × (1/45). The constant, gp-31488, is `0x3cb60b61`.
- A NULL list returns here.

The quarters are rows of the table at `0x002f09e0`, four points each:

| row | points | quarter |
|-----|--------|---------|
| 0 | 0, 7, 8, 1 | bottom right |
| 1 | 0, 5, 6, 7 | top right |
| 2 | 0, 3, 4, 5 | top left |
| 3 | 0, 1, 2, 3 | bottom left |

Row 0 is never read. Rows 4 to 27, the data after the table, are
zeros, and row 28 holds pointers. A Rotation of 0 or below reads row 4
and on, and one of −2160 or below reaches row 28.

**The whole quarters.** Rows 1 to q − 1 each take a poly from
FlailerStrip::AddPoly (`0x00145868`), which allocates one and runs
ePoly's constructor (`epoly.h`). Each corner c gets the xy and uv of
point row[c]. Each poly also gets:

- the bitmap's z;
- ALPHA_1 from gp-22356 on: AlphaEnabled 1, (Cs − Cd) × As + Cd, Fix
  0x80;
- the bitmap's four Colors;
- Flailer 1.

**The cut.** One more poly takes row max(q, 1):

- Corner 0 is the centre.
- Corner 1 is A + t × (B − A), with A = row[s] and B = row[s + 1].
- Corners s + 1 to 3 copy their points.
- With s = 2, corner 2 keeps the constructor's: (64, 64), uv (1, 1).
- Its colours are all `0x80808080`, not the bitmap's.

ePoly::Render draws a poly as a strip in corner order 0, 1, 3, 2.

## Where it draws

RenderSingleFlailerBitmap (`0x001428f0`), for Animation 10, runs
CreateFlailerStrip, then Render with the list +108 names, then
AddFlailerStrip. It draws no ordinary quad, so with no list nothing is
drawn.

`uirender.c`'s `draw_tach` does the same:

1. Render goes into a pool of four ePolys, each run through
   `epoly_init`.
2. Each poly becomes a strip in Render's order, in the 640×480 space
   mapped as the rest of the screen is.
3. The colours are the poly's, on the GS scale, with the alpha times
   the screen's fade.
4. The polys draw through `georender_draw_hud_quad`, after a
   `C2D_Flush` of what citro2d has queued. citro2d has no strip with a
   colour past 1.0 at each corner. The quad sets texenv stages 1 to 5 to
   pass its colour through, since citro2d's image stages are still
   there.
5. Then `C2D_Prepare` runs, with the depth test off, as the race frame
   sets citro2d up after the track.

The UV scale is next_power_of_2 of the image over the upload's
allocation, which can be bigger than the power of two.

`BUIObject` has a new field, `chunk`: the object itself on retail's
layout, the memory the Flailer setters write. It is NULL on the demo's
layout, so a demo bundle's gradient draws nothing.

## The word at 108

A list's address does not fit the word on a 64-bit host, so the word
holds a token instead: 0 for none, and otherwise 1 + a slot in
`hudtach.c`'s table of four. `hudtach_points` turns it back. A list the
table has not seen takes the next slot round, so the last four lists
stay good and a new race needs no reset. One Player has one list, and
the port has one Player.

## The bumper view's sliver

When s is 2, corner 2 of the cut stays at the constructor's (64, 64)
with uv (1, 1). The strip's second triangle then runs from the cut's
edge to (64, 64), a sliver across the screen. Its UVs run from the
image's right edge into the padding, out to (1, 1).

The chase view always has s = 1. In the bumper view, 13 of the 64 cars
have the tach in the speedo, and SetHudFeatures hides the gradient. Of
the other 51, 38 cut with s = 2. The port draws the sliver as retail
does. It has not been
compared with PCSX2. Whether it shows depends on what the padding holds
on each side.

## Where the port differs

- **AddPoly** can answer NULL, and Render stops there. The PS2's pool
  has no limit. `uirender.c`'s pool holds four polys: past four the rows
  are zeros, and their polys have no area.
- **Rows 28 and on** are pointers on the PS2, read as point numbers far
  outside the list. The port reads them as zeros. Only a Rotation of
  −2160 or below gets there, and the checker's pool stops before them.
- **The TextureInfo** is not cached at +84. The size comes from
  `gFlailerBitmapTextureSizeFn`, and with no texture Init writes
  nothing, where the PS2 reads through its NULL.
- **The draw** keeps the fraction that the GS's 12.4 coordinates drop.
  It also does not apply ApplyAspectRatio, since the screen's own
  mapping is the 640×480 one.

The checker shows none of the first three, and the draw is not checked.

## The checker

**`tools/hudtach_check.py`** runs Init (with next_power_of_2) and Render
from retail's image in the emulator, against `hudtach.c` and `epoly.c`
in the harness `tools/src/hudtach_test.c`.

- **The stubs.** GetTextureInfo answers the scripted size. AddPoly
  hands out blocks that retail's constructor (`0x0010f968`) has
  filled over a pattern. The model checks that AddPoly is given the
  bitmap's strip and TextureInfo. Both stubs log each call.
- **The pool.** Both sides hand out 27 polys, as many as the table's
  zeros reach, and then stop: the stub stops retail, and the harness's
  AddPoly answers NULL.
- **Compared,** after each op: both lists, the bitmap's 144 bytes (the
  word at 108 as the list it names), and every poly handed out.
- **The script:**
  - both disc gradients, through every whole degree and round past
    both ends, out to INT_MIN;
  - the texture sizes and scales that next_power_of_2 and the unsigned
    conversions treat apart;
  - each layer and each corner's colour;
  - both lists, a list the bitmap does not name, and none.

**The result:** 2287 ops, 7804 lines, 0 differ.

**The mutation pass:** 93 mutations, 89 caught, 4 equivalent:

- `pow2-zero-kept`: for 0 the loop runs 31 times, and 2 << 31 is 0 in
  32 bits.
- `init-uhalf-no-zero-add`: 0 + x differs from x only at −0, and umax
  is never −0.
- `table-row0`: row 0 is never read.
- `angle-q-floor`: q differs only for a negative angle, where both are
  below 2 and the cut takes row 1.

The first pass left `angle-c-cast` alive. A C cast of 360 − INT_MIN
overflows where the EE saturates, and no scenario reached it. INT_MIN
is in the script now, with the pool cut off at 27 so that the
24 million quarters stop.
