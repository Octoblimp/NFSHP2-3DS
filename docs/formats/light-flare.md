# Light flares

A light flare is the glow round a lamp: a car's headlights, brake lights
and reverse lights, the cop cars' red, blue and white, and the tunnels'
lamps. The flares themselves are data. CarRenderInfo makes a car's from
its markers (see [car-render-info](car-render-info.md)), and a track's
come in its bundle (chunk 0x80034019, see [light](light.md)). This page
covers the drawing half of `eLight.obj`, retail `0x00116118` ..
`0x00116820`. The port has it in `elightflare.{c,h}`, and
`tools/lightflare_check.py` cross-checks it against the image.

Retail's ELF is stripped. The function names are the demo's. The two
tables are retail's own: the demo's were laid out differently. Their
field names are the port's.

| function | retail | |
|---|---|---|
| (the part renderer) | `0x00116118` | one square of one texture |
| eLightUpdateTextures | `0x00116488` | the three textures, from PostLoadFixup |
| eRenderLightFlare | `0x001164f0` | one flare through a model's matrix |
| eRenderWorldLightFlares | `0x00116778` | every loaded pack's flares |

## The textures

There are three textures, all in GLOBALB.BUN. Their hashes are at
`0x002d6070`, and `eLightUpdateTextures` keeps what `GetTextureInfo(hash,
0, 0)` answers at `0x002d6328`: NULL until the bundle loads.

| index | name | hash |
|---:|---|---|
| 0 | HEADLIGHTFLAREINNER | `0x8868656f` |
| 1 | HEADLIGHTFLAREOUTER | `0x88d8e8a2` |
| 2 | HEADLIGHTGLOW | `0x3394fe62` |

All three are additive (AlphaBits 0x48), semitransparent, alpha sorted,
written without depth, rendering order 6.

## The parts

A part is 60 bytes. Retail has nine at `0x002d6080`. Colours are the GS's,
where 128 is 1.0.

| offset | field | |
|---:|---|---|
| 0 | MinSize | pixels at a facing of 0 |
| 4 | MaxSize | pixels at 1 |
| 8 | MinColour[4] | r, g, b, a |
| 24 | MaxColour[4] | |
| 40 | Power | the facing's exponent |
| 44 | TowardCamera | world units it is drawn in front of the lamp |
| 48 | MinScale | world units a pixel, at least |
| 52 | MaxScale | and at most |
| 56 | Texture | 0..2 |

| part | at | sizes | min colour | max colour | power | toward | scale | tex |
|---:|---|---|---|---|---:|---:|---|---:|
| 0 | `0x6080` | 0 .. 64 | 0 0 0 0 | 100 120 170 80 | 1.45 | 0.8 | 0.01 .. 0.015 | 0 |
| 1 | `0x60bc` | 28 | 0 0 0 0 | 100 120 140 20 | 3 | 0.8 | 0.01 .. 0.015 | 1 |
| 2 | `0x60f8` | 20 .. 30 | 0 0 0 0 | 128 0 0 80 | 1 | 0.2 | 0.01 .. 0.02 | 2 |
| 3 | `0x6134` | 20 | 0 0 0 0 | 255 255 255 128 | 1.2 | 0.2 | 0.005 .. 0.01 | 2 |
| 4 | `0x6170` | 20 | 0 0 0 0 | 128 128 128 128 | 1 | 0.2 | 0.005 .. 0.01 | 2 |
| 5 | `0x61ac` | 30 .. 40 | 128 64 64 48 | 128 64 64 128 | 1 | 1 | 0.01 .. 0.02 | 0 |
| 6 | `0x61e8` | 30 .. 40 | 64 64 128 48 | 64 64 128 128 | 1 | 1 | 0.01 .. 0.02 | 0 |
| 7 | `0x6224` | 30 .. 40 | 128 128 128 32 | 128 128 128 128 | 1 | 1 | 0.01 .. 0.02 | 0 |
| 8 | `0x6260` | 30 .. 50 | 110 100 75 96 | 110 100 75 110 | 1 | 4 | 0.001 .. 0.1 | 2 |

## The types

A flare's Type picks two parts from `0x002d62d8`. The second is NULL for
all but the headlights.

| type | what | parts |
|---:|---|---|
| 0 | a car's headlight flare | 0, 1 |
| 1 | a brake light | 2 |
| 2 | a reverse light | 3 |
| 3 | unused | 4 |
| 4, 5, 6 | a cop's red, blue, white | 5, 6, 7 |
| 7, 8 | the headlights' own lamps | 0, 1 |
| 9 | a tunnel's lamp (`EF_TunnelA`, every track's pack) | 8 |

The cops' red and blue have Flags bit 0 set: they light both ways.

## eRenderLightFlare

`eRenderLightFlare(view, flare, local_world, intensity)` answers 1 when it
drew and 0 when it did not.

1. It answers 0 with no flare, no matrix or no camera, and for a flare
   whose Enabled byte is 0.
2. The position goes through the matrix to the world, as
   `v0·x + v1·y + v2·z + v3`, summed left to right.
3. The world point goes through the view's WorldClipMatrix with w 1. The
   flare is off the screen when any of x, y and z is past |w| either way
   (`vclipw`), and the answer is 0.
4. The direction goes through the matrix's rotation. The vector to the
   camera's position is normalised by `1 / sqrt(len²)`. Facing is their
   dot product, or its magnitude when Flags bit 0 is set.
5. Right and up are the WorldViewMatrix's first two columns. The depth is
   the point's z through the camera's own matrix, over the view's H.
6. Each of the type's parts is drawn, and the answer is 1.

## A part

1. A part whose texture is NULL draws nothing.
2. `k` is pow(facing, Power), the fast way, times the intensity. Facing
   is held at 0.01 or more. Its bits are read as an integer, made a float,
   times Power, plus `(1 - Power) × 1065353216`, truncated, and read back
   as a float's bits.
3. The size is `Min + (Max - Min) × k` pixels. A size of 0 or less draws
   nothing.
4. The centre is the point moved TowardCamera along the vector to the
   camera.
5. The depth over H is held between MinScale and MaxScale. A flare far
   off shrinks with distance, and one close in grows. The half-width in
   world units is the size times that.
6. The colours are `Min + (Max - Min) × k`, each truncated to a byte, and
   the same at all four corners.
7. The square is: V0 `(c - r) + u`, V1 `(c + r) + u`, V2 `(c + r) - u`,
   V3 `(c - r) - u`, with UVs (0,0), (1,0), (1,1), (0,1). It goes to
   `ePoly::Render3D` with `eMathIdentityMatrix`, flags 0.

**ePoly::Render3D** (`0x0010ff88`) is eEndStrip's packet. It draws nothing
for a NULL texture. Otherwise it takes the strip V0, V1, V3, V2, x, y and
z alone, onto the texture's list with the matrix, or onto the alpha sort
by V0's z through the WorldViewMatrix. Its flags argument is not read.

## eRenderWorldLightFlares

While InGameFlag (gp-21424) is set, it walks `eLightFlarePackList`
(gp-24272) and each pack's flares (the header's list at +56). It draws each
through `eMathIdentityMatrix` at intensity 1. eDisplayFrame calls it after
RenderWorldObjects and RenderFlailerModels, and before RenderEffects.

## Where they are drawn

- **The cars.** CarRenderInfo::Render calls eRenderLightFlare for each of
  the car's lit flares, with the intensity carrender.c works out: the
  headlights when they are on, the brakes when braking, the cop lights as
  they flash. The flares are drawn in step 8 of [Render](car-render-info.md).
- **The world.** trackview.c calls `el_render_world_light_flares` after
  the world objects, in the main view before the effects, and in the
  rear-view mirror.
- **The textures.** PostLoadFixup's second call,
  `gELightUpdateTexturesFn`, is `el_update_textures`.

Until this slice, `gERenderLightFlareFn` was NULL, so no car's lights
glowed. The cop lights did not flash, and the headlights and brakes
showed no glow.

Even then the cars had no flares to draw until Session 62: the
position-marker loader (slot 8) was not ported, so CreateCarLightFlares
found none of a car's markers. With it, each car gets its flares from the
GEOMETRY.BIN's markers (see [car-render-info](car-render-info.md), "The
position markers").

## The port

- **The Type.** Retail indexes the types' table with the signed Type and
  no check. The port draws nothing for a Type outside 0..9, and still
  answers 1. No shipped flare has one.
- **Render3D** is `gEPolyRender3DFn`, which trackview.c binds to
  `render_epoly_3d`. It builds a four-vertex strip through the same
  strip builder as eBeginStrip's (`strip_begin` .. `strip_end`), so it
  sorts and blends as retail's packet does. A view holds at most 256
  strips and 2048 strip vertices; `stripsDropped` counts what did not
  fit.

## The cross-check

`tools/lightflare_check.py` runs retail's four functions and ePoly's
constructor in mipsemu against `elightflare.c` and `epoly.c`, with the
tables as shipped. GetTextureInfo and Render3D are stubs on both sides.
Each logs what it is handed, Render3D the whole poly from its vertices on.
ePoly's destructor does nothing. The model shares the port's Type guard:
a hook where retail forms the table's index points it at two NULLs for a
Type outside 0..9.

The script covers:

- the textures in each combination;
- NULL arguments and disabled flares;
- each clip plane by one ulp, with w either sign and w from the depth;
- every type and some outside the table, facing toward, edge on and
  away, with each flag;
- intensities from below 0 to 100;
- depths either side of each part's scale clamps, and a flare at the eye;
- the world's packs, with InGameFlag off and on, and with no packs or
  empty packs;
- 400 random flares on random cars through random views.

The result is 3143 ops, 5499 lines and 0 differ, with 1034 polys drawn.
All 96 mutations are caught.
