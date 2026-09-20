# TexturePack -- chunk `0xb0300001`

Every `*TEX*.BIN` in the archive opens with this chunk, and the track/frontend
`.BUN` bundles carry several of them nested inside other containers. It is the
GS texture atlas: a table of textures plus one flat blob holding all of their
CLUTs and pixels.

Reader: `tools/texture_convert.py` (`--list` to dump the table, otherwise it
writes one PNG per texture; stdlib only, no PIL).

## Container layout

`0xb0300001` is a container (bit 31 set), holding three leaves in this order:

| type         | size       | contents |
|--------------|-----------:|----------|
| `0x30300002` | 20         | pack header: a NUL-padded ASCII name (`HUD`, `CARTEXTURES`, `TRACK`), then a version word |
| `0x30300003` | n * 164    | the `TextureInfo` table, one record per texture |
| `0x30300004` | large      | all CLUTs and all pixel data, back to back |

A sibling container `0xb0300100` follows with the same three-leaf shape
(`0x30300101` / `0x30300102` / `0x30300103`) -- that is the TextureAnimPack,
the flipbook animations. It is decoded too; see the bottom of this file.

### The data base is 128-byte aligned, not the payload

`ImagePlacement` and `PalettePlacement` are offsets from the `0x30300004`
payload **rounded up to a 128-byte boundary**, not from the payload itself.
`LoaderTexturePack` (`0x00100830`):

```
001008a8  addiu  s2,v0,143      ; v0 + 8 (the payload) + 135
001008b0  and    s2,s2,a3       ; a3 = -128
```

`v0` is the data chunk's header, so `v0 + 8` is the payload and `s2` is that
address rounded up. The packer leaves room for it: the payload starts with
0 to 127 bytes of `0x11` filler. In this build the three UI bundles need 120,
108 and 88 bytes of it.

The bundle is loaded at a 128-byte-aligned address, so aligning the offset
within the file gives the same answer as aligning the pointer does.

Miss this and everything still parses -- the table is read from a different
chunk -- but every texture comes out rolled sideways by up to 127 bytes, one
scanline wrapping into the next. Small flat UI sprites survive it looking
almost right, which is what makes it easy to miss; photographs and logos do
not.

## `TextureInfo` -- 164 bytes

Offsets confirmed against `GetTex0__FP11TextureInfoUiUi` (`0x001094b8`), which
assembles the GS `TEX0` register directly out of the struct, and against
`AttachTextureDownloadPacket` (`0x00108938`), which DMAs the pixels to GS
memory. **Every field name below is bWare's own**, out of the `.mdebug` type
info; the whole 164 bytes are now accounted for. Sizes in the struct are byte
counts unless stated otherwise.

| offset | type       | field |
|-------:|------------|-------|
| `0x00` | `bTNode<TextureInfo>` | the base class: `pNext`/`pPrev`, 0 on disc |
| `0x08` | `char[24]` | `DebugName`, NUL padded |
| `0x20` | `u32`      | `NameHash` = `bStringHash(DebugName)` -- the lookup key |
| `0x24` | `u16`      | `Width` |
| `0x26` | `u16`      | `Height` |
| `0x28` | `u8`       | `BitDepth`: 4, 8 or 32 |
| `0x29` | `u8`       | `RenderingOrder` (0..7) -- the mip count is `0x6e`, not this |
| `0x2a` | `u16`      | `NumPaletteEntries`: 16, 256, or 0 when 32bpp |
| `0x2c` | `u16`      | `PaletteVramBlocksRequired` -- 256-byte GS blocks |
| `0x2e` | `u16`      | `ImageVramBlocksRequired` -- ditto |
| `0x30` | `u32`      | `ImagePlacement` -- pixel offset into the `0x30300004` blob |
| `0x34` | `u32`      | `PalettePlacement` -- CLUT offset into the same blob |
| `0x38` | `u32`      | `ImageSize` -- pixel byte count (the whole mip chain) |
| `0x3c` | `u32`      | `PaletteSize` |
| `0x40` | `u32`      | `ImageParentHash` -- the texture this one borrows its pixels from, 0 if it owns them |
| `0x44` | `u32`      | `BaseImageSize` -- repeat of `0x38` |
| `0x48` | `u8`       | `ShiftWidth` = `TW` = log2(width) |
| `0x49` | `u8`       | `ShiftHeight` = `TH` = log2(height) |
| `0x4a` | `u8`       | `PixelStorageMode` = `PSM`: `0x00` PSMCT32, `0x13` PSMT8, `0x14` PSMT4 |
| `0x4b` | `u8`       | `ClutPixelStorageMode` = `CPSM` (`0x00` PSMCT32 throughout) |
| `0x4c` | `u8`       | `TilableUV` |
| `0x4d` | `u8`       | `ApplyAlphaSorting` |
| `0x4e` | `u8`       | `TextureFx` = `TFX` |
| `0x4f` | `u8`       | `IsAnySemitransparencyFlag` |
| `0x50` | `u8`       | `bWriteZ` |
| `0x52` | `TextureImageInfo[7]` | `ImageInfos`, one 4-byte entry per mip level (see below) |
| `0x54` | `u8`       | level 0's `TextureBufferWidth` = `TBW` -- buffer width / 64; always equals `width / 64` here |
| `0x55` | `s8`       | level 0's `Is32BitSwizzelled` -- **this is what says whether the pixels are swizzled** |
| `0x6e` | `s8`       | `NumMipMapLevels` -- levels *after* the base, so `0` means one level |
| `0x6f` | `u8`       | `MMag` -- GS magnification filter |
| `0x70` | `u8`       | `MMin` -- GS minification filter |
| `0x71` | `u8`       | `MipMapL` -- the `TEX1` LOD `L` |
| `0x72` | `u16`      | `MipMapK` -- the `TEX1` LOD `K` |
| `0x74` | `u8`       | `GlossMapInAlpha` |
| `0x75` | `u8`       | `Padding` |
| `0x76` | `u8`       | `AlphaBits` |
| `0x77` | `u8`       | `AlphaFix` |
| `0x78` | `u8`       | `UsedFlag` |
| `0x79` | `u8`       | `ScrollType` |
| `0x7c` | `f32`      | `ScrollSpeedS` |
| `0x80` | `f32`      | `ScrollSpeedT` |
| `0x84` | `f32`      | `ScrollTimeStep` -- see *Scrolling textures* below |
| `0x88` | `u32`      | `pTexturePack` -- 0 on disc |
| `0x8c` | `u32`      | `pImageParent` -- 0 on disc; resolved from `ImageParentHash` |
| `0x90` | `u32`      | `ImageData` -- runtime pointer to the pixel bytes (0 on disc) |
| `0x94` | `u32`      | `PaletteData` -- runtime pointer to the CLUT (0 on disc) |
| `0x98` | `u32`      | `pActiveTexture` -- 0 on disc |
| `0x9c` | `u32`      | `pStackedActiveTexture` -- 0 on disc |
| `0xa0` | `u16`      | `PaletteVramAddress` -- 0 on disc |
| `0xa2` | `u16`      | `ImageVramAddress` -- 0 on disc |

`ImageData` and `PaletteData` are set when the pack is loaded and are the two
fields the texture animations rewrite -- see below.

**Correction.** This table used to call `0x00`/`0x04` "the runtime GS address
of the pixels / of the CLUT". They are not: they are the `bTNode<TextureInfo>`
base class the record inherits from, `!1,020,1732;` in the type string with
`1732 = bTNode<TextureInfo>, s8`. The GS addresses are the two `u16`s at the
very end, `PaletteVramAddress` and `ImageVramAddress`, and `GetTex0` does not
read either of them -- the caller passes both in as arguments. Nothing decoded
the field either way, so no output changes; the entry was simply a guess that
the completed type info now replaces.

Everything from `0x4c` down used to be blank or guessed here. It is filled in
because `tools/mdebug_stabs_scan.py` learned to join stab *continuations*: a
type string too long for the assembler's line limit is split across
consecutive symbol entries, each piece but the last ending in a backslash, and
the harvester was keeping only the first piece. `TextureInfo` was one of
thirteen structs that had been coming out truncated.

### Scrolling textures

`ScrollType`, `ScrollSpeedS`, `ScrollSpeedT` and `ScrollTimeStep` are a UV
animation the GS does with no extra pixels: the texture stays put and its
coordinates slide. `TextureInfo::GetScroll` (`0x00100a60`) is four
instructions of arithmetic and returns the offset to add to U or V:

```c
float TextureInfo::GetScroll(float time, float speed, int type, float step) {
    if (type == 0) return 0.0f;               // not a scrolling texture
    if (type == 2) time = (float)(int)(time / step);   // quantised
    float f = time * speed;
    return f - (float)(int)f;                 // fractional part, so it wraps
}
```

Type 1 slides continuously; type 2 snaps to whole `step`-second ticks, which
is a strobe rather than a slide. The caller in `RenderSingleFlailerBitmap`
(`0x00140600`) is what pins the offsets down independently of the type info:
it reads `ScrollType` from `0x79` into the `int`, `ScrollSpeedS` from `0x7c`
and then `ScrollSpeedT` from `0x80` into the speed, and `ScrollTimeStep` from
`0x84` into the step, and it sets the bitmap chunk's dirty byte afterwards so
the strip is rebuilt.

27 of the 2,642 texture records on the disc scroll -- every one of them found
by scanning the packs rather than by reading a list, since there is no list.
`texture_convert.py --scroll` prints them for any file:

```
python tools/texture_convert.py out/TRACKS/TEX12LOCATION.BIN --scroll
```


| where | textures | type | what it is |
|---|---|---|---|
| `TRACKS\TEX12LOCATION.BIN` | `WATERC`, `WATERC001`..`WATERC014` | 1 | river water, V at -1/64 |
| | `G_WATERFALL`, `G_WATERFALL_TOP` | 1 | V at -0.390625 |
| | `G_WATERFALL2` | 1 | V at -0.2734375 |
| | `W_BEACHWATER`, `W_LOGS3`, `W_MILLBELT` | 1 | U, the mill belt fastest at 1.03125 |
| `FRONTEND\FRONTB.BUN` | `ROADLINES` | 1 | U at 0.78125 -- the menu background |
| | `SCREEN_LINES` | 2 | the scanline overlay: -1/64 of V every 0.04s, i.e. 25 steps a second |
| `GLOBAL\INGAMEB.BUN` | `ZONE_PREVIEW_RIBBON` | 1 | V at -0.0234375 |

`SCREEN_LINES` is the only type 2 on the disc, and the only texture whose
`ScrollTimeStep` is not `1.0f`.

Everything else in the tail is inert on disc, and checked that way over all
2,642 records: the `bTNode` at `0x00`, every pointer from `0x88` to `0x9c`,
both VRAM addresses at `0xa0`/`0xa2`, and `UsedFlag` are zero in every single
one.

### The mip chain

The levels sit one after another in the `0x30300004` blob, base level first,
each halving both dimensions, with no padding between them. The check is
arithmetic and it is decisive: summing `max(1, w >> L) * max(1, h >> L) *
bpp / 8` over `NumMipMapLevels + 1` levels reproduces the record's own `0x38`
byte count **exactly**, on all 1,755 textures in the archive that own their
pixels, at every level count from 1 to 7.

Each level carries its own `Is32BitSwizzelled`, and they genuinely differ:
`BEAVER_SIGN` (256x128 PSMT4, 5 levels) is flagged at the base and raster at
every level below it. So a chain has to be decoded level by level, not
unswizzled wholesale.

`TextureImageInfo.TextureBasePointerOffset` is **not** the file offset. It is
the level's base pointer in GS memory, in 256-byte blocks, and it obeys the
GS's own page alignment: for `BEAVER_SIGN` it happens to match the packed
file offsets (0, 64, 80, 84, 85), but for a 64x128 PSMT8 texture it runs
0, 48, 60, 63 where the file offsets are 0, 32, 40, 42. Only 74 of 265
mipmapped textures agree. Use the arithmetic chain for file offsets and this
field only if you are reproducing the VRAM layout.

`tools/texture_convert.py --mips` writes the sub-levels as
`<name>.mip<N>.png`. They render as coherent, legible smaller copies of the
base image; they are *not* pixel-exact box downsamples of it, because the
art is dithered 16-colour and the levels were quantised independently.

The `0x52` array and the two fields around it are not inferred -- they are in
the `.mdebug` type info verbatim (`docs/mdebug_structs.txt`), which is also
where the swizzle answer was hiding in plain sight:

```
struct/class TextureImageInfo (size=4 bytes) [type#227]
    TextureBasePointerOffset     u16   offset=0
    TextureBufferWidth           u8    offset=16
    Is32BitSwizzelled            s8    offset=24
```

with `TextureInfo.ImageInfos: ar1;0;6;227,656,224` -- seven elements of 4
bytes at bit offset 656, i.e. `0x52` -- and `NumMipMapLevels` at bit offset
880, i.e. `0x6e`. `FillVramWithTextures` (`0x001081f8`) walks exactly that:
`0x001084ac` indexes `info + 0x52 + level * 4`, and `0x0010848c` reads `0x6e`
and adds one for the loop bound. Across the build, a chain of
`NumMipMapLevels + 1` halving levels accounts for `0x38` exactly, on all 2267
textures that own their pixels.

`GetTex0()` is the cross-check: it shifts `0x48` left by `0x1a` (TW), `0x49` by
`0x1e` (TH), `0x4a` by `0x14` (PSM), `0x4b` by `0x33` (CPSM), `0x4e` by `0x23`
(TFX) and `0x54` by `0xe` (TBW), which is exactly the GS `TEX0` field layout.

### Shared pixel data

`0x40` is how the game does palette swaps: several records point at the *same*
pixel offset with different CLUT offsets and name the owning texture in `0x40`.
`CORVETTELM_KMH` shares `CORVETTE_KMH`'s dial art; the four driver bodies
(`BODYF01`..`BODYF04`) and the cop car skins likewise share one image each. The
pixel data is stored once.

### Mipmaps

When `0x38` is 4/3 of `width * height * bpp / 8` the full mip chain follows the
base level, largest first. `texture_convert.py` emits only the base level.

## CLUT

RGBA8 and `CPSM` = PSMCT32 throughout. A **256-entry** CLUT is stored in GS
CSM1 order, not linearly: inside every group of 32 entries, 8..15 and 16..23
are exchanged, which is the same thing as swapping bits 3 and 4 of the index.
A **16-entry** CLUT is linear -- bit 4 is outside the palette, so there is
nothing to exchange.

`RemapLinearIntoClut8__FPUiT0` (`0x00118878`) *is* that permutation, and bWare
named it. It is eight passes over 32 entries, and each pass moves two quadword
pairs across each other and copies the rest straight through:

```
00118894  lq  t0,32(t2)     ; source entries  8..11
0011889c  lq  v0,64(t2)     ;         "      16..19
001188b8  sq  v0,32(t3)     ; 16..19 stored where  8..11 would be
001188c0  sq  t0,64(t3)     ;  8..11 stored where 16..19 would be
```

The name says which direction it runs: linear in, CLUT8 out. Its callers --
`eAttachDepthIntoAlpha`, `CreateFogPalette`, `CreateFocusPalette`,
`SetupBlackAndWhite`, `BuildYUV2ABGRPalettes` -- are all palettes the engine
*builds at runtime* in the obvious order and then has to convert. A pack CLUT
is uploaded to GS memory without that call, so it must already be in CLUT8
order, and a host decoder has to undo it. The permutation is an involution,
so one table does both directions.

Two checks, neither of which depends on anyone's taste in gauge faces:

* 173 of the 256-entry CLUTs on the disc have at least eight unused (all
  zero) entries. In CSM1 order those unused entries form a clean tail --
  logical indices *n*..255 -- for 54 of them, and for the other 119 the test
  cannot tell (all-zero tails that survive either reading, or palettes whose
  gaps are not a tail at all). Read linearly, **not one** of the 173 has its
  unused entries at the end.
* Decoding every 8-bit texture both ways and measuring the mean colour step
  between horizontally adjacent texels -- real art is locally smooth -- picks
  CSM1 order for 559 of 588 textures, by factors of up to 15x. The 29 that
  prefer linear are flat 16x16 UI sprites, 176x16 bars and the `MOVIE_*`
  planes whose on-disc CLUTs are placeholders, i.e. every case where the
  measurement has nothing to work with.

An earlier revision of this document claimed the opposite, on the grounds
that the swap "visibly wrecks the image". That test could not have worked:
it predates the 128-byte data base fix above, and `PalettePlacement` is
measured from the same base, so the CLUT being read was itself 120 bytes --
thirty entries -- off the real one. Both readings of a wrong palette are
wrecked; the swap took the blame for the offset.

Alpha is PS2-scale: `0x80` is fully opaque, so it doubles to reach 0..255.
(One texture, `OPEL_KMH`, carries alpha up to `0xfb`, so the doubling is a
convention rather than a hard invariant -- the converter clamps.)

Unused palette entries are left as bWare `0x11` chunk filler; `AIRFRONT` has
seven of them before its first real colour.

## Pixel data and the swizzle

Two different upload paths exist, and the record says which one a texture
takes. `AttachTextureDownloadPacket` (`0x00108938`) builds a host-to-local
DMA packet with `DPSM` from `0x4a` and `TRXREG` from `0x24`/`0x26`, i.e. a
native PSMT8/PSMT4 transfer at the real size -- for those the GS does the
swizzling itself and the file holds **plain raster** data.
`FillVramWithTextures` (`0x001081f8`) then rewrites that packet for any level
whose `Is32BitSwizzelled` byte is set:

```
0010850c  lb    v0,3(v1)        ; v1 = info + 0x52 + level*4, so +3 is the flag
00108510  beq   v0,zero,...     ; flag == 0: leave the packet alone
00108514  sra   s7,a1,24        ;            DBW = TBW
00108518  lb    v1,40(s3)       ; bits per pixel
0010851c  addiu v0,zero,4
00108520  bne   v1,v0,...       ; 8bpp: width/2, height/2
00108524  sra   s7,a1,25        ;       DBW = TBW/2
00108528  sra   s5,s5,1         ; 4bpp: width/2 ...
0010852c  b     ...
00108530  sra   s4,s4,2         ;       ... height/4
0010853c  sw    zero,32(sp)     ; DPSM = 0 = PSMCT32
```

(Both `sra`s sit in branch delay slots, so `DBW = TBW` is computed on every
path and the flagged path overwrites it with `TBW/2`.)

`Is32BitSwizzelled` is bWare's own name for the byte, and it describes the
situation exactly: a flagged texture is uploaded as a **PSMCT32 image
`width/2` texels wide** -- `height/2` rows for 8bpp, `height/4` for 4bpp, the
same byte count either way -- and then read back through `TEX0` as
PSMT8/PSMT4. The file therefore holds a 32-bit image whose bytes have been
pre-arranged into GS page/block/column order: the familiar PS2 "texture
swizzle". An unflagged texture is not swizzled at all.

In this build 809 of 2642 texture records are flagged (426 4-bit, 383 8-bit)
and none of them are 32-bit. Reading an unflagged texture as swizzled is
exactly as wrong as reading a flagged one as raster, which is why the
converter follows the flag rather than guessing from the size.

### The layout a flagged texture unpicks

GS memory is pages of 32 blocks of 4 columns. The three formats involved tile
a page differently:

| format   | page       | block   | block grid in a page |
|----------|------------|---------|----------------------|
| PSMCT32  | 64 x 32    | 8 x 8   | 8 x 4 |
| PSMT8    | 128 x 64   | 16 x 16 | 8 x 4 |
| PSMT4    | 128 x 128  | 32 x 16 | 4 x 8 |

Since the host image is half as wide and half (or a quarter) as tall, its
pages line up one-for-one with the texture's. The 8-bit block grid lines up
too. The 4-bit one does not: `blockTable4` is the **transpose** of
`blockTable32`, so a PSMT4 block's *x* index picks the host *row* and its *y*
index picks the host *column*. That transposition is the whole reason the
4-bit case is not just the 8-bit case at half scale, and it is what defeated
every attempt to derive it by analogy.

Inside a block, with `cx`/`cy` the coordinates within the block, `col = cy>>2`
the column, and `swap = cy1 ^ col0` the GS column swizzle:

| source bit | 8bpp lands on | 4bpp lands on |
|------------|---------------|---------------|
| `cx0`, `cx1`, `cx2 ^ swap` | host x | host x |
| `cx3` | byte 1 of the host word | nibble 1 |
| `cx4` | --                       | nibble 2 |
| `cy0` | host y | host y |
| `cy1` | byte 0 of the host word | nibble 0 |

One host 32-bit word thus holds the 4-bit texels `(x, x+8, x+16, x+24)` of two
rows two apart -- and the 8-bit texels `(x, x+8)` of the same two rows.
`unswizzle_map8()` and `unswizzle_map4()` compute exactly this, in closed
form, as an index per output texel.

Written out as a bit permutation of the source byte offset (`lw` = log2
width), the 8-bit case is the standard PS2 swizzle:

```
bit 0        <- y1
bit 1        <- x3
bit 2        <- x0
bit 3        <- x1
bit 4        <- x2 ^ y1 ^ y2      <- the GS column swap
bits 5..lw   <- x4, x5, ...
bit lw+1     <- y0
bit lw+2     <- y2
bit lw+3     <- y3
bits lw+4..  <- y4, y5, ...
```

The page/block/column derivation above reproduces this permutation exactly,
for every flagged size in the build including non-power-of-two widths -- which
is the cross-check that the host-raster model is right, since the 8-bit output
was already confirmed by eye.

### How the 4-bit map was confirmed

Visually: the track-name wordmarks (`LOGOTRACK*`, 4-bit 256x128) come out with
"Desert Heat", "Outback", "Alpine Trail" and the rest cleanly legible, and the
4-bit car skin atlases resolve into panels, lights and wheels. Both were
featureless noise under every earlier guess.

Two objective checks back it up, each run over all 200 flagged 4-bit textures
in the archive that own their pixels and are a whole number of pages, with the
known-good 8-bit map as the control:

* **flat tiles.** A correct unswizzle turns the art's flat areas back into
  perfectly uniform 8x8 output tiles -- a criterion a near-miss cannot satisfy.
  The winning assignment scores 0.292; the runners-up score 0.264 and 0.251.
* **the column swap.** `swap` moves texels only within each 8-wide group, so
  getting it wrong breaks horizontal continuity at one `x % 8` boundary and
  nowhere else. With the swap the disagreement profile by `x % 8` flattens
  (spread 0.242 vs 0.332); the 8-bit control shows the same signature (0.091
  vs 0.121). The flat-tile test cannot see this term at all -- a 4-texel
  rotation inside an 8x8 tile leaves it uniform -- so the two checks are
  independent, and between them they pin every bit of the map.

The geometry closes -- host raster a whole number of PSMCT32 pages wide, whole
blocks tall -- on every one of the 809 flagged textures in the build, with no
exceptions. `geometry_closes()` re-checks it per texture and falls back to a
raster read rather than reading off the end of a buffer.

### 32-bit (PSMCT32)

Stored linearly. Only the alpha doubling is applied. No 32-bit texture in the
build is flagged.

## Usage

```bash
python tools/texture_convert.py out/GLOBAL/HUDTEX.BIN --list
python tools/texture_convert.py out/GLOBAL/HUDTEX.BIN png/
python tools/texture_convert.py out/TRACKS/TRACKB12.BUN png/ --swizzle none
python tools/texture_convert.py out/TRACKS/TEX12LOCATION.BIN png/ --mips
```

`--swizzle auto` (the default) unswizzles exactly the textures flagged at
`0x55`, which is what the game does. `none` dumps the data as stored and
`all` forces the unswizzle on every paletted texture; both are for checking a
hunch, not for output. `--list` prints the flag in its `swiz` column and the
mip level count in `mip`. `--mips` additionally writes every level below the
base as `<name>.mip<N>.png`.

Output is one PNG per texture under `<outdir>/<pack name>/`. On this build:
84 textures in `GLOBAL/HUDTEX.BIN` (pack `HUD`), 772 in `CARS/TEXTURES.BIN`
(pack `CARTEXTURES`) and 396 in `TRACKS/TEX12LOCATION.BIN` (pack `TRACK`).

---

## TextureAnimPack -- chunk `0xb0300100`

The flipbook animations. Same three-leaf container shape as the texture pack,
and loaded by the same function: `LoaderTexturePack` (`0x00100830`) branches
on the container type and, for `0xb0300100`, walks the leaves by size and
hands them to `TextureAnimPack::TextureAnimPack` (`0x001a1650`).

| type         | size            | contents |
|--------------|----------------:|----------|
| `0x30300101` | 16              | `TextureAnimPackHeader`: `u32 Version` (1), `u32 pTextureAnimPack` (0 on disc, patched at load), `u32 pad[2]` |
| `0x30300102` | n * 52          | the `TextureAnim` table |
| `0x30300103` | m * 16          | the `TextureAnimEntry` table, one flat run |

The loader refuses anything whose `Version` is not 1; every pack on this disc
is version 1. Neither count is stored -- `n` and `m` are the leaf sizes
divided by 52 and 16.

All the layouts below are the `.mdebug` type info verbatim
(`docs/mdebug_structs.txt`), confirmed against the loader and
`InitAnims`/`UpdateTextureAnimations`.

### `TextureAnim` -- 52 bytes

| offset | type | field |
|-------:|------|-------|
| `0x00` | `char[24]` | `Name`, NUL padded |
| `0x18` | `u32` | `NameHash` -- also the hash of frame 0's texture |
| `0x1c` | `s32` | `NumFrames` |
| `0x20` | `s32` | `FramesPerSecond` |
| `0x24` | `s32` | `TimeBase` -- picks which of two clocks drives it |
| `0x28` | `u32` | `TextureAnimTable` -- 0 on disc; the constructor points it into the entry table |
| `0x2c` | `s32` | `Valid` -- 0 on disc; `InitAnims` sets it, and clears it if any frame's texture is missing |
| `0x30` | `s32` | `CurrentFrame` -- runtime |

### `TextureAnimEntry` -- 16 bytes

| offset | type | field |
|-------:|------|-------|
| `0x00` | `u32` | `NameHash` of this frame's texture |
| `0x04` | `u32` | `pTextureInfo` -- 0 on disc; `InitAnims` resolves it via `GetTextureInfo` |
| `0x08` | `u32` | `OriginalImageData` -- 0 on disc; a copy of that texture's `0x90` |
| `0x0c` | `u32` | `OriginalPaletteData` -- 0 on disc; a copy of its `0x94` |

Only `NameHash` carries data on disc. The other three are the runtime's
scratch.

### How the entry table is split

It is one flat run, and nothing in the file says where one animation's frames
end. The constructor implies it:

```
cursor = TextureAnimEntryTable
for each TextureAnim:
    anim->TextureAnimTable = cursor
    cursor += anim->NumFrames * 16
```

So animation *k*'s frames are the next `NumFrames` entries, in play order, and
the totals have to add up -- which they do: 4+8+4 = 16 in `GLOBAL/INGAMEB.BUN`
and 2+5+3+5+15 = 30 in `TRACKS/TEX12LOCATION.BIN`.

### What an animation actually does

`UpdateTextureAnimations` (`0x001a17e8`) walks the global
`TextureAnimPackList` every frame. For each `Valid` animation it computes

```
frame = (int)(fps * clock) % NumFrames
```

where `clock` is one of two global timers -- `TimeBase == 1` selects the
second -- and `fps` comes from a global override if one is set, otherwise from
`FramesPerSecond`. If the frame changed, it then does, for every `j` in
`0 .. NumFrames-1`:

```
dst = entry[j].pTextureInfo
src = entry[(j + frame) % NumFrames]
dst->0x90 = src->OriginalImageData
dst->0x94 = src->OriginalPaletteData
```

That is the whole mechanism: the frames' `TextureInfo` records have their
pixel and CLUT pointers **rotated** among themselves. Nothing re-uploads and
nothing re-binds, so any geometry referencing *any* one of the frame textures
animates, and the textures are otherwise ordinary members of the pack.

### On this disc

Only two of the thirteen anim packs are non-empty; the other eleven are
present but hold zero animations.

| file | animations |
|------|------------|
| `GLOBAL/INGAMEB.BUN` | `BULB` (4 frames, 7 fps), `SMOKE` (8, 0 fps), `TRACK_BARRIER_NEON` (4, 4 fps) |
| `TRACKS/TEX12LOCATION.BIN` | `D_BARRIERLIGHTFLASH` (2, 15), `D_LIGHTTUNNELLIGHT` (5, 7), `HELI_ROTOR` (3, 30), `W_TUNNELREFLECT` (5, 7), `WATERC` (15, 15) |

Every one of the 46 frame hashes resolves to a texture in the same file, and
the names confirm the reading: `WATERC` then `WATERC001`..`WATERC014`,
`HELI_ROTOR` then `HELI_ROTOR001`/`002`, and so on -- frame 0 is always the
texture the animation is named after. Independently: calling the engine's own
`bStringHash("WATERC")` under `tools/mipsemu.py` returns `0x82be0ae5`, which
is the `NameHash` in the record, so the field offsets are pinned to the
engine's hash rather than only to a name lookup. `SMOKE`'s `FramesPerSecond` of 0 is not
a parse error; it relies on the global rate override.

### Usage

```bash
python tools/texture_convert.py out/TRACKS/TEX12LOCATION.BIN --anims
```

`--anims` prints each animation with its frames resolved back to texture
names. A normal conversion run also drops an `anims.csv` beside the PNGs --
one row per frame in play order, with the PNG filename -- so a sequence can be
rebuilt without re-reading the chunk.
