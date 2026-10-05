# eLight and eEnvMap

This slice lights the cars. It covers four pieces of retail:

- the database half of `eLight.obj` (0x00114f38 .. 0x00117460): the
  loader of the light packs, flares and materials, the query for the
  lights near a point, and `elSetupLightContext`;
- `vAABBTree`'s leaf query (0x001b9cd0 .. 0x001ba0a0);
- `eEnvMap` (`eInitEnvMap` 0x00117508, `UpdateCameras` 0x001175c8): the
  six views drawn round the car for its reflections;
- the VU1 lighter that the renderer sends lit strips through, and its
  environment pass.

The port is in `3DS Files/source/`:

- `elight.{c,h}`: the loader, the materials, the tree, the query and the
  light context;
- `eenvmap.{c,h}`: the views and their cameras;
- `geolit.v.pica`: the lighter, as a PICA vertex shader;
- `georender.c` (`georender_draw_lit`, the environment map) and
  `trackview.c` (`lighting_for`, `trackview_draw_envmap`): the draw.

`tools/loadertable_check.py` runs LoaderTable slot 5 against the image,
with the other loaders. Nothing else here has a harness yet.

## The chunks

LoaderTable slot 5 (`LoaderLightList` 0x00114f38, `UnloaderLightList`
0x001151e0) takes four chunk ids. A child's data starts at
`(chunk + 23) & ~15`, which is the payload rounded up to 16 bytes.

| Id | What |
|---|---|
| 0x80034015 | a track's light pack: children 0x34016 (the `eLightPack` header, version 1), 0x34017 (a `vAABBTree` with its nodes after it) and 0x34018 (the `eLight` array) |
| 0x80034019 | a track's light flares: children 0x3401a (`eLightFlarePackHeader`, version 1) and 0x3401b (the `eLightFlare`s) |
| 0x0003401c | taken and ignored |
| 0x0003401e | GLOBALB.BUN's light materials: version 1 at +8, the count at +12, and the 320-byte `eLightMaterial`s from +16 |

The loader links a light pack into `eLightPackList` (gp-24264), a flare
pack into `eLightFlarePackList` (gp-24272) with its flares on its own list,
and each material into `eLightMaterialList` (gp-24256). It builds each
material's DMA data as it goes. The material named "Default" (hash
0x2c420d64) becomes `eDefaultLightMaterial` (gp-24248). Until then, that
points at a zeroed static (0x002d5a00).

The unloader unlinks what the loader linked, and puts the default back
when "Default" goes. Retail's search for a pack's header tests the first
child's type over and over without moving on. A pack whose header was not
its first child would hang retail. The port's walk moves on instead, so
it differs from retail only where retail would hang.

## The records

These layouts come from `.mdebug`. `elight.h` has the full tables with a
layout check.

**eLight**, 96 bytes (type#4497):

| Offset | Field | |
|---|---|---|
| 0 | `Name[32]` | |
| 32 | `NameHash` | |
| 36 | `Type` | 0 ambient, 2 point |
| 37 | `AttenuationType` | 2: blended with the other ambients |
| 44 | `Colour` | R, G, B bytes from the bottom |
| 48 | `Position` | |
| 60 | `Size` | the radius it reaches |
| 76 | `Intensity` | |
| 80, 84 | `FarStart`, `FarEnd` | full strength inside `FarStart` |

**vAABB**, 48 bytes (type#2613): a centre, an extent (half the size) and
up to ten children. A parent's `NumChildren` counts its `ChildrenIndicies`
into the tree's `NodeArray`. A leaf's is minus the count, and its indices
are into the pack's `LightArray`.

**eLightMaterial**, 320 bytes (type#4326): the node, the hash, a 20-byte
name, then two `eLightMaterialData` (80 bytes, type#4591) at 32 and 112,
one for the frontend and one in game. Each has a 64-byte DMA block, built
on load, at 192 and 256. The renderer takes the in-game set when
`InGameFlag` is set.

## The material's DMA data

`eLightMaterial::BuildDmaData` (0x00116828 for one set, 0x001169f8 for
both) turns the 80 bytes into the sixteen words VU1 gets with each strip:

| Word | Value |
|---|---|
| 0 | `p = SpecularPower * SpecularPowerScale`, or 0 when the maximum is 0 |
| 1 | `bits(m) - p * bits(1.0)` for `m = SpecularMax * SpecularMaxScale` |
| 2 | 0.1, the specular's floor |
| 3 | `CBVMix / 255` |
| 4..6 | the diffuse colour scale |
| 7 | `(FresnelMin + (FresnelMax - FresnelMin) / 2) * 128` |
| 8..10 | the specular colour scale |
| 11 | `(FresnelMax - FresnelMin) / 2 * -128` |
| 12, 13 | the gloss map's power and bias, as words 0 and 1 |
| 14, 15 | `GlossMapAlphaMin`, and `GlossMapAlphaMax - GlossMapAlphaMin` |

`bits(x)` is the float's bit pattern read as an integer and converted to
a float. The power and the bias drive VU1's fast power: `m * x^p` is taken
as the float whose bits are `p * bits(x) + bias`. That is a logarithm that
is straight between powers of two. It is not `x^p`: at x = 0.7 and p = 10
it gives half of it. The port computes it the same way.

## The query

`QueryLightDatabase` (0x00115370) finds the lights at a point. For each
pack, `vAABBTree::QueryLeaf` (0x001b9fd8, with its helper 0x001b9ed8) finds
the first leaf, depth first, whose box strictly holds the point. Each light
in the leaf whose sphere holds the point gets an influence: 1 inside
`FarStart`, falling linearly in the squared distance to 0 at `Size`.

- A point light (type 2) goes on the list, up to ten.
- An ambient light with attenuation 2 is blended with the others of its
  kind by influence.
- Any other ambient is a base, and the nearest one wins.

When the blended influences total more than 1, they are scaled to sum to
1. Otherwise the base fills what they leave. Each blended light is scaled
by the total again, so a lone light at half strength counts a quarter.
That is retail's arithmetic, and the port keeps it. The result is the
ambient colour and a `LightScale`.

## The light context

`elSetupLightContext` (0x00115978) builds the `eLightContext` that the
lighter reads for one model. Everything is in the model's own space:

- three directions, the columns of `LocalDirectionMatrix`: to the sun
  (`SunDir` (-0.74, 0, 0.55) times 10000) and to the two nearest point
  lights;
- their colours, the rows of `LocalColourMatrix`: the sun's
  `SunColour` (80, 80, 80) times the clamped `LightScale`, never below
  0.7, and each point light's times its influence. Retail works out the
  point lights' blue and never stores it, so it stays 0.
- the ambient, the last row: the override when set, else the query's,
  else a flat 85; and 128 in w;
- `LocalEyePosition`, the eye in model space;
- `EnvMapMatrix`: the model's matrix times `hack_man_matrix`, with the eye
  in its last row.

### In the frontend

In the frontend (CurrentGameFlowState, gp-21420, is 3), the directions
and colours are the frontend's own, and SunlightIntensity is 1:
- **On the car select** (IsCarSelectScreenActive), they come from
  SetSelectCarLighting's set: view 2 takes the second set (0x002d5ff0),
  and every other view the first (0x002d5f70). The directions are held
  in view space. They are turned by the inverse of the view's
  WorldViewMatrix into world space, then into the model's like the
  rest. The set's three colours and its ambient replace the four rows.
  `docs/formats/car-select.md`, "The turntable car", has how the set is
  filled.
- **Elsewhere in the frontend** it uses three fixed directions
  (0x002d5b70): (0, -5, 5), (4.3, 2.5, 2.5) and (-4.3, 2.5, 2.5). The
  colours are greys of 128, 64 and 64, and the ambient is 0
  (0x002d5ba0).

The three colour rows get 0 in w and the ambient 128. The query still
runs, but its ambient and the override are overwritten.

For the directions, retail asks IsCarSelectScreenActive twice: before
it inverts the view's matrix, and again before it turns them. A no the
second time would turn a third set (0x002d5b40) instead. The answer
can't change between the two calls, so the port asks once there.

## The lighter

The strips whose `eStripEntry` flags have 0x80 are lit, and those with
0x100 get an environment pass as well. `geolit.v.pica` follows the VU1
microcode:

1. `vuiCalculateReflectionVectors` (VU1 0x1620) scales the normal to unit
   length by 1/127. It reflects the ray from the eye about the normal,
   `R = V - 2 (V.N) N`, and normalises R.
2. The lighter (VU1 0x1998) takes the diffuse as `max(N.L, 0)` for each of
   the three lights. The specular's base is `max(R.L, 0.1)`, raised by the
   fast power.
3. The colour is the ambient plus each light's diffuse and specular
   colour. That is scaled by `1 + (c - 255) * CBVMix / 255` for the
   vertex colour c, and clamped to 0..255, where 128 is 1.0 on the GS's
   scale.
4. The alpha is 128. A strip whose texture holds a gloss map in its
   alpha (flag 4) uses the gloss power for its specular instead. Its
   alpha is the material's minimum plus the range times the sun's
   specular.

The environment pass draws the strip again with the map, added to the
frame. Its colour is grey (128), under an alpha of
`FresnelMid + FresnelHalf * r.z`. A gloss map's strip instead uses the lit
colour under the frame's alpha, which the first pass left there. The VU1
reads a sphere map at `0.5 + 0.5 r.xy / |r + (0, 0, 1)|` for
`r = D (R * EnvMapMatrix)`, where D negates x and z.

## The environment views

`eInitEnvMap` (0x00117508), called from `eInitEngine` at 0x00102f68, makes
views 4..9 active on render targets 8..13. Each target is 64 square at
aspect 1, with a 2D aspect of 0.8 / 0.94 and a `FovBias` of 1. Each is
cleared to a grey of its own, 96 + 16i. Retail also builds the sphere
map's prims (0x00117a38).

`UpdateEnvironmentMapCameras` (0x00112a34) runs at the start of
`eDisplayFrame` when `EnableEnvMapViews` (gp-21072) is set. It centres
the six on the car the player's camera follows. `eEnvMap::UpdateCameras`
(0x001175c8) does the rest:

- It makes two look-ats: down +x from the origin, and from the camera
  to the car. What turns the first into the second, applied to six axes,
  gives each face's direction. The axes and their ups are the frontend's
  set at 0x002d6e50 / 0x002d6f10, or the race's at 0x002d6eb0 /
  0x002d6f70. With the camera level, the race's faces 0 and 2 look
  straight up and down.
- Face 2's look-at becomes `hack_man_matrix`, so the map's +z is the sky.
- The table at 0x002d6fd0, indexed by `eFrameCounter` over its count
  (gp-24200: 4 or 6), picks which views draw this frame. With one
  player's view (view modes 1 and 2), faces 0 and 5 draw every frame and
  faces 1 to 4 take turns. Otherwise one face draws a frame.
- Each camera has a near plane of 0.5, a far plane of 10000 (gp-32468)
  and a field of view of 30180, which is 90 degrees across 64 pixels.

The views cull to 32 units (gp-24208), and the cull leaves out flags 2
and 0x100 for them. The road under the car is near-clipped. So the faces
hold the sky, the trees and the far scenery, and below the horizon the
sky dome's lower half. The cars draw only into views 1..3.

## The sphere map

The targets are PSMCT16. Views 4..9 draw into targets 8..13, 64 square,
and target 14, 256 square, is the sphere map the environment pass reads.

`CreateRefSampleTable` (0x00117a38), from `eInitEnvMap`, fills the table
at 0x002d7130: ten grids of 7 by 7 samples, 28 bytes each (`x, y, z, s,
t, u, v`). Rows and columns 6 are never written.

- Grids 0..5 are a 6 by 6 grid on each view's target, u and v from 0 to
  1, with the direction that texel looks along in the map's space, and
  `ComputeReflectionST`'s s and t for it: `0.5 + 0.5 d.xy / |d + (0, 0,
  1)|` for d made unit.
- Grids 6..9 spread target 10, the view behind the map, round the
  sphere's rim, one grid from each of its edges to its centre. They have
  no direction; their s and t are on the rim.

`eCreateEnvMapPrims` (0x00118810) folds the targets into target 14 each
frame. `CreateEnvMap` (0x00118150) draws the grid of each view that drew
this frame, except view 2's, and `CreateBackEnvMap` (0x00118498) draws
the four back grids if view 2 drew. Each cell is two triangles of a strip:

- XYZ2 is `trunc(st * 256 - 128 + 2048)` in each axis, on a target whose
  offset is 1920, and UV is the view's texel at u and v.
- PRIM is 0x54, with no fog. RGBAQ is (96, 96, 96, 64), modulated, so the
  texel comes in at 0.75 and the alpha at a half.
- ALPHA_1 is 0x44, `(Cs - Cd) As + Cd`: target 14 becomes `0.5 * 0.75 *
  Ct + 0.5 * map`.

Nothing clears target 14. Each fold is half the new views and half what
the map held, so the map is a running blend. A view drawn every frame
settles in a few frames, and one that takes turns fades towards each new
look as its turn comes.

## The port's map

The six views draw into a 64-square cube in VRAM, one face each, with a
depth buffer per face. The cube is RGBA8 over D24S8 depth, the top
screen's pair. It was RGBA5551, as retail's PSMCT16 targets are, until a
New 3DS XL's GPU stopped at a face's first draw (2026-10-05). The stop
was not the pair: it was the first draw through `geosolid.v.pica`, and
the PICA freezes on two faults there that Azahar draws through. A
loader's attributes did not fill its stride (the normal's three bytes
left 27 of 28, `georender_init`), and the shaders left output
components unwritten (`tools/check_shbin.py`). A 5551 face waits on a
device run. Each view
keeps retail's axis, frustum and schedule. Its camera is
the cube face's: the same frustum, rolled by a multiple of 90 degrees so
the face's texels run the cube's way. A face whose view is inactive keeps
what it last drew. A face that has never drawn is cleared to its
target's grey.

Then `georender_envmap_fold` folds the cube into the sphere map, a
256-square RGBA5551 texture in VRAM with a target over it and no depth.
`trackview_envmap_init` builds the fold's triangles once from the sample
table: 25 cells of two triangles a grid, 150 vertices, ten grids.

- Each vertex is where retail's lands: its XYZ2 less the offset, moved
  half a pixel, since the PICA samples a pixel at its centre, in clip
  space.
- It reads the cube at the sample's direction, in the cube's mirrored
  space below: `(-x, y, z)`. A back grid's sample has no direction, so
  its u and v on view 2's target give one: `(1 - 2u, 2v - 1, -1)`,
  mirrored the same way.
- The grids draw in retail's order and by its rule: a view's grid when
  the view drew this frame, but view 2's, and the four back grids when
  view 2 drew.
- The colour is (0.75, 0.75, 0.75, 0.5), the texel by it, and the blend
  `SRC_ALPHA, ONE_MINUS_SRC_ALPHA`, with no depth, no alpha test and no
  fog. So the map is the same running blend as retail's.
- The map is cleared to 0 once, when it is first folded, and never
  after. The environment pass waits for that first fold.

The environment pass in `geolit` reads the sphere map at retail's s and
t, `0.5 + 0.5 r.xy / |r + (0, 0, 1)|`. `tools/envsample_check.py` runs
the image's table and ComputeReflectionST against `eenvmap.c`'s.

Two hardware facts set the orientation:

- The PICA picks a face and its s and t by OpenGL's rule.
  `ConvertCubeCoord` in Azahar's `renderer_software/sw_clipper.cpp` has
  it.
- A render target puts NDC +y at t = 0 and NDC +x at s = 1. OpenGL's
  framebuffer has NDC +y at t = 1.

So a face filled the way the rule wants is a mirror image of any camera's
view. Drawing it mirrored would flip every triangle's winding. Instead the
map's space is mirrored: the fold reads the cube at `(-x, y, z)`. In
that space each face's camera looks along the face's axis, with its up
the opposite of the way the face's t runs (`kCubeUp` in `eenvmap.c`).

`C3D_RenderTargetCreateFromTex` checks that `tex->data` is in VRAM. A
cube texture's `data` is its `C3D_TexCube` pointer, so the check fails
for every cube. Each face's target is therefore made over a 2D
`C3D_Tex` whose data is that face's image.
