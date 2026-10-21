# The weather regions and the fog

This is task 27's twenty-eighth slice. It covers three things:

- all of `WeatherMan.obj` (0x001a8248 .. 0x001a8f28). This is the
  track's weather chunk, slot 29 of the LoaderTable, and the query that
  blends the weather regions for a point;
- `eView::GetWeatherQuery` (0x00112680) and its cache, one query per view
  per frame;
- the fog half of `EcstasyE.obj`: the fog palette (`CreateFogPalette`,
  0x00119308), and the two attaches eDisplayFrame lays over the frame,
  `eAttachDepthIntoAlpha` (0x00118a60) and `eAttachFog` (0x00119768).

The addresses are retail's (`SLES_507.31`), with the demo's in brackets
where a function or global first comes up. Retail's `WeatherMan.obj` is
the demo's but for the query's first test. Retail rewrote
`eAttachDepthIntoAlpha` for its 24-bit Z buffer, made `FogPower` 4.0, and
dropped the demo's copy over the palette's entries 252 to 254.

The port is in `3DS Files/source/`:

- `weatherman.{c,h}`: the regions, the lists, the loader and unloader, the
  query and the view's cache;
- `efog.{c,h}`: the fog's globals, `fpow`, `RemapLinearIntoClut8`, the
  palettes and the two attaches, with the PICA's side of the fog;
- `trackview.c`: the fog's fractions, from the palette the image makes;
- `georender.c`: the fog laid on, through texture unit 1 and the last
  combiner stage.

`tools/weather_check.py` cross-checks `weatherman.c` and `efog.c`
against `tools/src/weather_test.c`.

## The chunk

A track has one `0x00034250` chunk. Its payload is a 16-byte
`WeatherRegionPack` at the next 16 in the chunk, then `NumRegions`
128-byte `WeatherRegion`s.

| Offset | Pack field | What |
|---|---|---|
| 0 | `Unnamed[2]` | not named in the .mdebug, and never read |
| 8 | `Version` | 2 |
| 12 | `NumRegions` | |

| Offset | Region field | What |
|---|---|---|
| 0 | `Node` | the list links, a `bTNode` |
| 8 | `NameHash` | |
| 12 | `GroupNameHash` | |
| 16 | `Name[32]` | e.g. `FOG<MAIN>` |
| 48 | `GroupName[32]` | |
| 80 | `Type` | 0 rain, 1 fog, 2 snow, 3 wind |
| 84 | `FogColour` | r, g, b, a from the bottom byte |
| 88 | `FogStart` | a palette index, 0 to 255 |
| 92 | `Parameter1` | |
| 96 | `Position` | x, y, z |
| 108 | `Radius` | where the region ends |
| 112 | `Intensity` | the fog's amount, 0 to 1 |
| 116 | `FarFalloffStart` | where it starts to fade |
| 120 | | 8 bytes of pad |

TRACKB12's chunk is version 2 and has twenty fog regions:

- `FOG<MAIN>`, 2005 wide with no fade, at 0.1 of 0xa0a082 from 246;
- eleven `FOG<TUNNEL>`s, 85 wide and fading from 55, at 0;
- six `FOG<SMOKE>`s, 50 wide and fading from 25, at 0.8 of 0x6e6e6e;
- three `FOG<TUNNELSM>`s, 46.42 wide and fading from 29.32, at 0.

So in a tunnel the fog thins, and in the smoke it thickens and greys.

## The lists

There are five lists:

| Address | What |
|---|---|
| `0x003110e0` (`0x00308fe0`) | `WeatherRegionLists[4]`, by type |
| `0x00330d88` (`0x00323df8`) | `WeatherRegionInactiveList` |
| `0x00330d90` (`0x00323e00`) | `WeatherRainList` .. `WeatherWindList`, each a pointer to its list; nothing reads them |

The static constructor (0x001a8ee8, the demo's 0x0019ebd8) links each list
to itself.

**`LoaderWeatherMan`**, 0x001a8258 (0x0019dff8), returns 0 for a chunk of
any other type. For a pack that is not version 2 it returns 1 and links
nothing. Otherwise it calls `WeatherAddRegion` for each region, in the
pack's order, and returns 1. **`UnloaderWeatherMan`**, 0x001a82d8
(0x0019e078), is the same with `WeatherRemoveRegion`. The regions stay in
the chunk, and the lists are threaded through their first eight bytes.

- **`WeatherAddRegion`**, 0x001a8358 (0x0019e0f8), puts the region on the
  tail of its type's list. A type past 3, or below 0, goes on none: the
  image leaves the region holding the chunk's bytes, and the unloader
  then writes through them. The port links such a region to itself
  instead, so the unload unlinks it from nothing. This is the one change.
- **`WeatherRemoveRegion`**, 0x001a8398 (0x0019e138), unlinks it.
- **`WeatherSetRegionState(r, state)`**, 0x001a83b0 (0x0019e150), unlinks
  it, then puts it on the tail of its type's list if `state` is not 0,
  else on the inactive list's. The type is not checked.
- **`WeatherSetGroupState(hash, state)`**, 0x001a83f8 (0x0019e198), walks
  the lists and calls SetRegionState for each region in the group, or for
  every region when the hash is 0. A state of 0 walks the four lists, and any
  other state walks the inactive one. It reads the next region before it
  moves one. Nothing in the image calls it.

## The query

**`WeatherManQuery(q, pos)`**, 0x001a84f0 (0x0019e290), fills a 96-byte
`WeatherQuery`:

| Offset | Field |
|---|---|
| 0 | `Rain`, `Fog`, `Snow`, `Wind` |
| 16 | `FogColour`, `FogStart` |
| 24 | `RootScale`, `HitScale` |
| 32 | `RegionR`: the root's name, colour, start and scale |
| 48, 64, 80 | `Region0` .. `Region2`: the hits' |

Retail's query first tests `WeatherHeavyFog` (0x00330db8), which the
demo has not, and which the Heavy Fog egg sets. When it is set the query
gives a fog of 0.957753, the colour 0x887062 and a start of `-1000 +
200 sin(0.02 t) + 150 sin(0.001 t) + 100 sin(0.01 t)`, with t
`WorldTimeFrames`, and leaves everything else as it was.

When `WeatherUseTweakerValues` (0x00330da0, the demo's 0x00323e10) is
set, the query gives the tweaker's fog, start and colour (0x00330da4 ..
0x00330db4), with 0 for the rest, and leaves everything else as it was.
They are all 0 in the image.

Otherwise it clears the query, then takes each list in turn:

1. For each region, d^2 is `(dx^2 + dy^2) + dz^2` of the absolute
   differences, and r^2 is the radius squared. A region holds the point
   when d^2 < r^2.
2. A region whose r^2 equals its f^2, the fade start squared, does not
   fade. Of those, the nearest is the root. The search starts at
   9999999 (0x0032e6f0), and a tie keeps the first.
3. A region that fades is a hit, with a scale of
   `1 - (d^2 - f^2) / (r^2 - f^2)`, if that is above 0. After the third hit
   the walk stops.
4. The sum of the three scales is `(s0 + s1) + s2`. The root's scale is
   `1 - sum` and each hit's is 1. Past a sum of 1, the hits share
   `1 / sum` and the root gets 0. The two go into `RootScale` and
   `HitScale`, so the last list's are the ones left.
5. For fog, each region's colour bytes, start and intensity are scaled by
   its weight and summed. The root's weight is its scale, and each hit's
   is its own scale times `HitScale`. Each region's line in the query
   gets its name, its scale, its scaled start and its scaled colour,
   unmasked. The sums give `Fog`, `FogStart` and `FogColour`, whose
   bytes are masked.
6. For rain, snow and wind, the value is the root's intensity times its
   scale, plus each hit's intensity times `HitScale` alone, not times its
   own scale as well.

**`eView::GetWeatherQuery`**, 0x00112680 (0x001123f8), returns
`CachedWeatherQueries[view->ID]` (0x002d55b8). When the view's
`WeatherQueryCounter` is not `eFrameCounter` (0x0032f644), it first
queries again from the camera's position and sets the counter. The
counter is at +104 in retail's eView, +100 in the demo's and the port's.
The ID is not checked. `eFrameCounter` counts eDisplayFrame's frames, at
its very end.

## The fog palette

The PS2 draws the fog after the frame, in two attaches:

1. **`eAttachDepthIntoAlpha`**, 0x00118a60 (0x00119330), writes the Z
   buffer into the frame's alpha, in four passes of sprites that it
   builds in the frame's memory, 5,504 bytes. The Z buffer is PSMZ24.
   The first two passes read it as PSMZ16, each over half of it in
   strips 8 wide, and write a PSMCT16 view of the draw frame under a
   FRAME mask of 0x3fff, so that each pixel's alpha gets its Z's bits 8
   to 15. The third sets the shown frame's alpha to 255. The fourth
   copies the draw frame's alpha over it by a Z test, a sprite at Z
   0xffff and GEQUAL, so only where the Z is 0xffff or under. So the
   alpha is `Z >> 8`, or 255 for a Z past 0xffff. It returns 0 when
   `EnableDepthIntoAlpha` (0x0032fa7c) is 0, or the frame's memory runs
   out. The demo's read a PSMZ16S buffer through two palettes into
   `min(Z >> 6, 0xfc) | ((Z >> 6) & 3)`.
2. **`eAttachFog`**, 0x00119768 (0x00119af8), draws the frame's alpha as
   an 8-bit texture over the frame, through the view's fog palette, with
   the blend of the view's `FogModeInfo`. It returns 0 when `DrawFog`
   (0x0032faa0) is 0, or at once when the frame's memory runs out. It
   does views 1 and 2, each one whose `Active` byte, render target and
   `GetFogPalette` are not 0. The mode is `FogMode1` (0x0032fa98) for
   view 1 and `FogMode2` (0x0032fa9c) for the others, and it indexes
   `FogModeInfos` (0x002da6d0) unbounded.

eDisplayFrame (0x001138ac) attaches them once everything is drawn, the
sun and the alpha polys too: the fog only when the depth went in, and
then the depth of field.

Each palette goes through **`RemapLinearIntoClut8`**, 0x001189f8
(0x00118878), the GS's CSM1 order: of each 32 entries, the second 8 and
the third 8 trade places. So entry k of a linear palette is at
`(k & ~0x18) | ((k & 8) << 1) | ((k & 0x10) >> 1)`, which is its own
inverse.

**`GetFogPalette(view)`**, 0x001192d8 (0x001195f8), is `FogPalette[ID -
1]` (0x002da780) for IDs 1 to 4, else NULL. The fourth is
`FocusPalettes[0]`.

**`CreateFogPalette(view, palette)`**, 0x00119308 (0x00119678), returns at
once for a
NULL view or palette. Otherwise it takes the view's weather query, with
the colour's bytes r, g and b, `amount = Fog * 128` and `start =
FogStart`, and fills 256 linear entries by the view's mode:

| Mode | Entry i |
|---|---|
| 1 | alpha only: `trunc(v * amount) << 24` at `255 - i`, with v 1 below the start and `1 - (i - start) / (255 - start)` from it; the divide is made for every entry |
| 2 | a grey ramp at half alpha, `0x80000000 \| i * 0x010101`: a view of the Z |
| 3 | all 0, but the colour and `trunc(amount)` as its alpha at the one entry `trunc(start)` |
| 0, and past 3 | the colour, with the alpha `trunc(fpow(x, FogPower) * amount)` at `255 - i`, where x is 0 below the start, `(i - start) / (255 - start)` from it, and 1 at 255 |

The image's mode 0 has a second curve, from 240, behind a test of 0
against 0 that is always taken. Then the palette is remapped. The demo
first gave entries 252, 253 and 254 entry 255's, for its alphas of a Z
past 16383; retail has no such copy.

**`fpow(x, y)`** is the float trick: x's bits as a float, times y, plus
`0x3f800000 - y * 0x3f800000`, truncated back to bits. x is clamped to at
least 0.01 first (0x0032da28), and the truncate saturates. Retail has it
inlined in `CreateFogPalette`; the demo's is a function, 0x00119628.
`FogPower` (0x0032faa4) is 4.0, the demo's 4.6.

The four `FogModeInfo`s, 32 bytes each, are the GS's `ALPHA_1` fields A,
B, C, D and FIX, and six floats that nothing in the slice reads:

| Mode | A B C D FIX | Blend |
|---|---|---|
| 0 | 0 1 0 1 128 | `Cd + (Cs - Cd) * As / 128`: the fog over the frame |
| 1 | 1 0 0 2 128 | `(Cd - Cs) * As / 128`: the frame darkened |
| 2, 3 | 0 1 0 1 128 | as mode 0 |

## On the 3DS

The PICA has no pass that reads its own depth buffer back as a texture.
So `trackview.c` makes the palette before the frame, and `georender.c`
lays the fog on as each thing is drawn:

- The fog goes by the view's depth u = (far - d) / (far - near), 1 at the
  near plane and 0 at the far.
- For u, the GS's Z is `zmin + (zmax - zmin) * near * u / (far - u *
  (far - near))`, from the view's target's `ZRanges` entry: player 1's is
  PSMZ24's, 16 to 0x800000. `efog_depth_alpha` gives the alpha retail's
  passes leave for that Z, `Z >> 8` or 255 past 0xffff. That alpha
  indexes the fog palette, and the fraction of the frame that `ALPHA_1`
  keeps is `efog_keep`'s: `1 - a / 128` for mode 0's blend and `a / 128`
  for mode 1's.
- The fraction is taken at 129 steps, u = j / 128, and is straight
  between them. The fog's colour is the palette's one colour. A palette
  with more than one colour where its alpha is not 0, or mode 1's with
  any colour but black, is not a colour by a fraction: it is left off and
  counted.
- The sky and the sun get fractions that are constant at Z = 0, since
  the dome leaves the Z as the clear did. The additive and subtractive
  blends get a fog colour of 0.
- After the track, the fog goes off.

The fractions are a 256 by 8 A8 texture, step j in column j and the last
step's past it, every row alike. Texture unit 1 reads it bilinear and
clamped, so between two columns' middles it is straight, as the steps
are. Each vertex hands over its s in texcoord1: its view-space position
dotted with the projection's w row, scaled and offset (`fogRow` in
`geosolid` and `geolit`), so s = (128 u + 0.5) / 256 for its u. The
texcoord is perspective-correct, so the s a fragment gets is its own
depth's. The last combiner stage, 5, is `INTERPOLATE(previous, fog
colour, texture 1's alpha)`: the colour by the fraction kept and the fog
by the rest, with the alpha passed. A screen quad's s is a constant, from
its depth.

The PICA has a fog unit of its own, a 128-entry lookup by the fragment's
depth, which the port used first. The depth it looks up is the one the
depth buffer gets, so the fog wanted a W-buffer, `C3D_DepthMap(false, -1
/ near, 0)`, whose depth is u. On the PICA that depth does not hold a
decal to its surface: a car's licence plate, drawn over the body at the
same depth, broke up into the body within a second of the race's start.
The Z-buffer's depth, `near (far - d) / ((far - near) d)`, holds it. So
the depth buffer is the Z-buffer's, citro3d's own map, and the fog goes
by the texture.

With retail's chain, TRACKB12's lines are these (the port's code on the
host, for the track viewer's planes, 0.5 and 5,000):

```
weather: 0 rain, 20 fog, 0 snow, 0 wind regions, 0 off; DrawFog 1, modes 0 0, FogPower 4.00, depth into alpha 1
fog on, mode 0, 82a0a0 x0.100 from 246.0, root FOG<MAIN> + 0; keep at 250..4000 1.000 1.000 1.000 0.992 0.906, sky 0.906; 1 view, 0 unfit
```

At 250, 500, 1,000, 2,000 and 4,000 the Z is 15,955, 7,566, 3,371, 1,274
and 225, so the alpha is 62, 29, 13, 4 and 0. The palette's alpha is 0
from entry 255 down to entry 5, then 1, 2, 3, 7 and 12 at entries 4 to
0. So `FOG<MAIN>` leaves 99.2% of the frame at 2,000 and 90.6% at 4,000
and in the sky. The demo's chain, over the PSMZ16S range, left 97.7% at
2,000. The first frame's query comes back empty, since the view's
counter and `eFrameCounter` are both 0 then.

## The cross-check

`tools/weather_check.py` runs retail's LoaderWeatherMan,
UnloaderWeatherMan, WeatherAddRegion, WeatherRemoveRegion,
WeatherSetRegionState, WeatherSetGroupState, WeatherManQuery,
GetWeatherQuery, RemapLinearIntoClut8, GetFogPalette, CreateFogPalette
(fpow and all), eAttachDepthIntoAlpha and eAttachFog in mipsemu. It
stubs eGetView, eGetRenderTarget, bMemSet, AttachImageDataPacket and
eDmaChain::Add. For eAttachFog's packet, the stub prints the view, the
palette and the packet's `ALPHA_1`. The harness links `weatherman.c` and
`efog.c`, and the seam `gEFogAttachFn` prints the same line from the
`FogModeInfo` it is handed. After each step both sides dump the five
lists, walked both ways, and every region's links. The palettes and the
queries are dumped where a step makes them.

eAttachDepthIntoAlpha's packet is drawn. The checker has enough of a GS
for it, with PCSX2's swizzles for the formats it uses, sprites, nearest
texels, the FRAME mask and the alpha and Z tests; anything else the
packet asks for stops it. It lays the packet over a PSMZ24 buffer that
holds each of 32 Zs at a pixel of its own, either side of each byte and
past 16 bits, and reads the shown frame's alpha back at each. The
harness prints `efog_depth_alpha` for the same Zs. The rest of the
PICA's side has nothing in the image to run, so its model is the spec
above, written out over the image's fog palette and the drawn alpha.

The model's chunk gives each region its own address in its first eight
bytes, where the disc has a PS2 pointer, so the image's unlink of a type
past 3 is safe.

The scenarios cover:

- TRACKB12's kinds of region at the points that matter;
- roots that overlap, tie and touch; more than three hits; sums past 1;
  fade starts past the radius, at 0 and at the radius;
- each type, and types past 3 and below 0;
- the chunk at each misalignment, with versions 1, 2, 3 and 0x102, and
  with the wrong type;
- the region and group states, and the tweaker;
- the cache, by frame and by view, and across the counter's wrap;
- each palette mode, with the amounts, starts and powers at their edges;
- the palettes by view ID, and the depth into alpha on and off;
- eAttachFog for each view state, DrawFog value and mode;
- the PICA's colour and fraction for each mode's palette under each blend.

Results: 76 scenarios, 4,180 lines, 0 differ. Of the 88 mutations, 83
are caught. The other 5 are equivalent:

- Both chunks give each region its own address in its first eight bytes,
  so a region of a type past 3 is linked to itself whether or not
  WeatherAddRegion links it.
- At a sum of exactly 1, `1 - sum` and the branch both give the root 0,
  and `1 / sum` is 1.
- No weight is below 0 and together they are at most 1, so no byte of
  the blended colour passes 255, and its mask changes nothing.
- No `FogModeInfo` has A, B and C of 0, 1 and 0 with a D other than 1,
  so the over test needs no D.
- fpow's sum leaves an int only for a `FogPower` past 57 or under -19.
  Retail's is 4.0, and nothing writes it (its one access is
  CreateFogPalette's load); the scenarios' powers run from -1.5 to 10.
  Within an int, a plain conversion and the saturating one agree.

Five inputs came from mutations that first survived:

- a region of type -5;
- a point where `(dx^2 + dy^2) + dz^2` and `dx^2 + (dy^2 + dz^2)` round apart;
- a mode 0 palette, 1.25 from 95 at retail's power of 4, where the two
  orders of fpow's sum truncate 33 alphas apart;
- a view whose counter is past the frame;
- a mode 3 palette whose one entry has an alpha of 1.

The port's orders are the image's in both rounding cases.

`loadertable_check` treats slot 29 as ported. Its dump now shows the
weather lists' heads, and a scenario loads and unloads a one-region pack
through both tables at each misalignment. The host's `WeatherRegion` is
136 bytes, so the region has its type at both offsets. It has 27,933 ops
and 42,243 lines, and 0 differ. Of its 105 mutations, 103 are caught and
2 are equivalent.
