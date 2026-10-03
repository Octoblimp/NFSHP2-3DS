# The track on the screen

Roadmap step 1, task 27's twenty-third slice. TRACKB12.BUN's scenery goes
through the ported loader and cull and draws on the top screen through
`georender`, from a free camera. The code is `trackview.c`, `emodel.c`
and the `MODE_TRACK` arm of `main.c`. SELECT cycles to it after the
geometry viewer.

This is not a port of the renderer. eModel::Render, the strip lists and
the attach loops are the PS2's VU1 and DMA code, and the port draws what
`geometry.c` decodes of a solid instead. What the port does keep is the
engine's decisions: which objects draw (the ported cull), where they draw
(the cull's matrices), and in what order and with what blend and depth
state. The last is below.

## What loads

```
trackview: entered, 122 sections, 23 zones, 6160 ms
trackview: 1135 solids linked, 2494 models, 7 without a solid, 915 baked,
           125498 tris, 342 textures (0 missing, 0 reduced), 36268 KB linear free
```

- The bundle is read whole into linear memory, and the scenery works on it
  in place, the way LoaderScenery does.
- The 1,135 eSolids are linked onto `SolidList` in place, by the bNode at
  each one's start. That is the part of LoaderSolidList that eFindSolid
  needs, and it is all the port does of it until the LoaderTable (step 2).
  `geometry.c`'s `GeoSolid.header` is the eSolid as it sits in the file.
- `emodel.c` is eModel.obj's list half: Init, which names the model, finds
  its solid and puts it on `ModelList`, and the deleting destructor.
  Seven of the 2,494 models name a solid the bundle does not have.
- Every solid a model names is baked at load into `georender`'s triangle
  lists: 915 solids, 125,498 triangles. Their 342 textures come from
  TRACKB12's three packs and fit at level 0.
- The camera starts on route 1. The D-pad's left and right step between 24
  stops along it.

`tools/run_azahar_track.ps1` boots the build in Azahar, drives it to the
viewer and takes eleven screenshots into `%TEMP%\nfshp2_track`. They are
stop 1, a move forward, a look each way, a look down from above, then
stops 2 to 7. The frame after each jump writes the names of what it drew
to the log.

## eMathInit

InitializeEverything calls `eMathInit` (0x0011b9a0) at 0x0012d9f0, just
before eInitEngine. It is the only thing that fills `eMathIdentityMatrix`.
StuffScenery hands that matrix to every object drawn where it stands
(Flags 0x0200: the road, the terrain, the potholes). With it left zero,
each of those objects folded to a point, and the viewer showed trees
standing in the sky. `main.c` calls it now. The frame's log counts
in-place draws, and the names list marks them with `*`.

## The engine's draw order

Four functions decide the order, blend and depth state:

1. **`eModel::RenderStrips`** (0x0010c8a0) takes each strip's texture from
   the solid's texture table. A texture with `ApplyAlphaSorting` gets an
   `eNewAlphaSortKey` (0x00104690) on the render target's alpha list, and
   its depth is `GetAABBZDepth` (0x0010b888). That depth is the strip's
   box centre through the local and view matrices: view z, +z forward.
   Any other strip goes on its texture's own list for the target.
2. **`AttachSolidPolys`** (0x0010a7f0) runs first. `AddTexturesSorted`
   (0x00107ee8) puts the frame's textures into eight lists by
   `RenderingOrder`. Within a list they keep the order the frame first used
   them, except that a texture sharing an earlier one's `pImageParent`
   goes straight after it (`pStackedActiveTexture`, +0x9c). Each
   texture's strips then go out in the order they came.
3. **`AttachAlphaPolys`** (0x0010a4c0) runs next. `SortAlphaKeys`
   (0x00104ae8) radix-sorts the keys (0x00104710) by depth, then by
   `7 - order`, and builds the list back to front. The result is
   `RenderingOrder` up and, within an order, farthest first.
4. **The depth and alpha test state.** Retail's attach loops (0x0010bb20
   and 0x0010b838) give each texture a mode: bit 0 is set for
   `IsAnySemitransparencyFlag` or `GlossMapInAlpha`, and bit 1 for
   `bWriteZ`, which is cleared unless `eGetZWriteState`. (The demo's loops
   worked the mode out from the order instead.) `AttachDmaDataList` sends
   the render target's register block at `240 + 224 * mode`. The four
   blocks differ only in ZBUF's mask and TEST_1 (below). Byte 117, the
   record's `Padding`, picks the matrix pack:
   - 1 is `MatrixPack1`;
   - 2 is the pack at 148;
   - anything else is `MatrixPack0`.

   On the disc it is 1 on exactly the order-4 textures, the shadows, and
   0 on the rest.

`CreateTextureContext` (0x00109f48) writes TEX0, TEX1, MIPTBP1/2, CLAMP
and `ALPHA_1 = AlphaFix << 32 | AlphaBits`, and no TEST or ZBUF. The main
target's TEST_1 comes from `UpdateGifTags` (0x00104ec0):
`ZTST << 17 | 0x10301 | ATST << 1` in the blocks for modes 0 and 2. The
render target's setup gives it ZTST 2 and ATST 6, which mean:
- the alpha test is on, and passes alpha GREATER than AREF 0x30 (of the
  GS's 0x80);
- a pixel that fails is not written, colour or depth (AFAIL KEEP);
- the depth test is GEQUAL.

Modes 1 and 3 have `ZTST << 17 | 0x1000b` instead: the test is GEQUAL
AREF 0, which every pixel passes. So a translucent texture's faint texels
are blended rather than cut, and a gloss map in alpha never cuts holes.
That matters most for T_RD2DIRT, the road's edge into the dirt: its
alpha is a gloss map, and 80% of it is below the cut.

### The TextureInfo fields

The fields are in the 164-byte record, which `texture-pack.md` lays out:

| Offset | Field | On the disc |
|---|---|---|
| 41 | `RenderingOrder` | 0 opaque; 1 WATERC; 2 road water; 3 bulbs, skids; 4 SHADOW*; 5 other translucents; 7 the sun |
| 77 | `ApplyAlphaSorting` | set on the semitransparent ones, and on five order-0 decals: START_LINE, XETT_GRAVELA, XETT_MULCHA, T_MULCH_BLENDA, W_BRIDGEFENCE |
| 79 | `IsAnySemitransparencyFlag` | always with an order of 1 to 7, and with `bWriteZ` 0 except on the order-1 and 2 waters (WATER*, WATERC*, the puddles, the waterfalls) |
| 80 | `bWriteZ` | 1 on every opaque texture, and on those waters |
| 116 | `GlossMapInAlpha` | the roads (T_ROAD*, ST_ROAD, T_RD2DIRT, W_ROADSTRIPES, the tunnel roads) and the car skins; all opaque, AlphaBits 0x0a |
| 117 | `Padding` | the matrix pack, in retail; 1 on the order-4 textures |
| 118 | `AlphaBits` | the GS's ALPHA_1 low byte, below |

`AlphaBits` is `A | B << 2 | C << 4 | D << 6` of `(A - B) * C >> 7 + D`,
with A, B and D taken from Cs, Cd and 0, and C from As, Ad and FIX:

| AlphaBits | Equation | Used by | Port |
|---|---|---|---|
| 0x44 | (Cs - Cd) * As + Cd | the ordinary translucents | `GEO_BLEND_ALPHA` |
| 0x48 | Cs * As + Cd | the bulbs, the sun, W_BEACHWATER, GRADIENT_GREY | `GEO_BLEND_ADD` |
| 0x42 | Cd - Cs * As | SKID_* | `GEO_BLEND_SUBTRACT` (the PICA's reverse subtract) |
| 0x0a | Cs | SIDEWALK, ST_ROAD, some road textures | `GEO_BLEND_NONE` |

## What the port does

- **`georender_draw_mask`** draws the batches in a bit mask, each with its
  texture's `GeoPass`. The pass holds the blend above, whether the batch
  writes depth, and whether it is alpha-tested. The tested ones are the
  attach loops' modes 0 and 2: neither semitransparent nor a gloss map.
  Depth is GEQUAL throughout. The alpha test is GREATER than 0x60, which
  is AREF 0x30 doubled, because the packs' alpha is doubled on the way
  in. `georender_draw` is unchanged for the geometry viewer.
- **`render_model`** draws a solid's opaque order-0 unsorted batches at
  once. Every other batch is held back in `deferred[]`, with its
  model-view matrix and its box centre's view z.
- **`draw_deferred`**, after StuffScenery, sorts what was held back into
  the attach loops' order:
  - first the unsorted ones, by order, then the texture's first use in the
    frame, then arrival;
  - then the sorted ones, by order, then farthest first, with ties the
    last added first.

  It draws each one with its own matrix.
- The frame puts the alpha test and blend back for citro2d afterwards.

A typical frame holds back 20 to 70 batches, of which 1 to 12 are sorted.
Stop 2 is the busiest: 380 draws, 27,838 triangles and 139,068 of the
command buffer's 262,144 words.

Where the port departs from the engine:

- **A batch is a texture's strips in one solid**, so the alpha sort is
  per batch where the engine's is per strip. The depth is the centre of
  the box round all of the batch's triangles.
- **`pStackedActiveTexture` is not modelled.** Textures that share an
  image parent are not moved next to each other. That changes only the
  order of two unsorted textures of one order that overlap on screen.
- **Order 4's second matrix pack is not modelled.** The shadows draw with
  the same projection as the road they lie on, and GEQUAL puts them on
  top.
- **The sky draws in the main view.** Section 99's SKYDOME and
  SKYDOME_ENVMAP are what StuffSky would draw with its own pass (step 3).
  Until then they are culled and drawn like any other scenery, and the
  frame clears to a sky blue.
- **No light materials.** Scenery is prelit, and the port draws it in its
  vertex colour times its texture.

## Two build fixes that came with it

- **The command buffer is four times citro3d's default.** A track frame
  is a draw per object the cull keeps, and each carries its own matrices.
  The default 256 KB holds about 500 of them, and `GPUCMD_Add` drops what
  does not fit without an error. `trackview.c` stops drawing 8,192 words
  short of the end and counts what it skipped. The count has been 0 at
  every stop.
- **`tools/check_3dsx.py`** walks a .3dsx's relocations the way the
  loader does. It names any word the loader would refuse: an absolute
  relocation with a top-four bit set, which is an address outside every
  segment. Azahar says only "Failed to load ROM (Error 1)", before a line
  of the app runs. `build_cia.ps1` runs the check after every build.

  The first bad word was in `bFixATan1` (`bmath.c`), and it came from
  INT32_MIN, which negates to itself. The image's signed `slti` sends that
  input to the low table with an index of -0x100000, 2 MB before the
  table. gcc folded that address into a negative constant. The port
  compares unsigned instead, so INT32_MIN saturates the way -0x7fffffff
  does, and every other input compares the same. Nothing in the game
  passes INT32_MIN: `bFixATan2` does only for y = INT32_MIN, x = 0.
