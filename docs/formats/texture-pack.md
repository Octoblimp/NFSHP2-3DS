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

A sibling container `0xb0300100` usually follows with the same three-leaf shape
(`0x30300101` / `0x30300102` / `0x30300103`) but 52-byte records -- that is the
TextureAnimPack (scrolling/flipbook animations referencing textures by hash).
It is not decoded yet.

## `TextureInfo` -- 164 bytes

Offsets confirmed against `GetTex0__FP11TextureInfoUiUi` (`0x001094b8`), which
assembles the GS `TEX0` register directly out of the struct, and against
`AttachTextureDownloadPacket` (`0x00108938`), which DMAs the pixels to GS
memory. Sizes in the struct are byte counts unless stated otherwise.

| offset | type       | field |
|-------:|------------|-------|
| `0x00` | `u32`      | runtime GS address of the pixels (0 on disc) |
| `0x04` | `u32`      | runtime GS address of the CLUT (0 on disc) |
| `0x08` | `char[24]` | name, NUL padded |
| `0x20` | `u32`      | `bStringHash(name)` -- the lookup key |
| `0x24` | `u16`      | width |
| `0x26` | `u16`      | height |
| `0x28` | `u8`       | bits per pixel: 4, 8 or 32 |
| `0x29` | `u8`       | `RenderingOrder` (0..7) -- the mip count is `0x6e`, not this |
| `0x2a` | `u16`      | palette entry count: 16, 256, or 0 when 32bpp |
| `0x2c` | `u16`      | palette size in 256-byte GS blocks |
| `0x2e` | `u16`      | pixel size in 256-byte GS blocks |
| `0x30` | `u32`      | pixel offset into the `0x30300004` blob |
| `0x34` | `u32`      | CLUT offset into the same blob |
| `0x38` | `u32`      | pixel byte count (the whole mip chain) |
| `0x3c` | `u32`      | CLUT byte count |
| `0x40` | `u32`      | name hash of the texture this one borrows its pixels from, 0 if it owns them |
| `0x44` | `u32`      | repeat of `0x38` |
| `0x48` | `u8`       | `TW` = log2(width) |
| `0x49` | `u8`       | `TH` = log2(height) |
| `0x4a` | `u8`       | `PSM`: `0x00` PSMCT32, `0x13` PSMT8, `0x14` PSMT4 |
| `0x4b` | `u8`       | `CPSM` (CLUT format; `0x00` PSMCT32 throughout) |
| `0x4e` | `u8`       | `TFX` |
| `0x52` | `TextureImageInfo[7]` | one 4-byte entry per mip level (see below) |
| `0x54` | `u8`       | level 0's `TextureBufferWidth` = `TBW` -- buffer width / 64; always equals `width / 64` here |
| `0x55` | `s8`       | level 0's `Is32BitSwizzelled` -- **this is what says whether the pixels are swizzled** |
| `0x6e` | `s8`       | `NumMipMapLevels` -- levels *after* the base, so `0` means one level |
| `0x84` | `f32`      | `1.0f` |

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

RGBA8, `CPSM` = PSMCT32, and **stored linearly** -- index *n* is the *n*-th
4-byte entry, with no CSM1 column shuffle. Two independent confirmations:

* `RemapLinearIntoClut8__FPUiT0` (`0x00118878`) is the only CLUT-reordering
  routine in the ELF, and its only callers are `eAttachDepthIntoAlpha`,
  `CreateFogPalette`, `CreateFocusPalette`, `SetupBlackAndWhite` and
  `BuildYUV2ABGRPalettes` -- all palettes the engine *builds at runtime*.
  Nothing on the texture-pack path touches it.
* Applying the CSM1 bit3/bit4 swap to a pack CLUT visibly wrecks the image.

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
```

`--swizzle auto` (the default) unswizzles exactly the textures flagged at
`0x55`, which is what the game does. `none` dumps the data as stored and
`all` forces the unswizzle on every paletted texture; both are for checking a
hunch, not for output. `--list` prints the flag in its `swiz` column and the
mip level count in `mip`.

Output is one PNG per texture under `<outdir>/<pack name>/`. On this build:
84 textures in `GLOBAL/HUDTEX.BIN` (pack `HUD`), 772 in `CARS/TEXTURES.BIN`
(pack `CARTEXTURES`) and 396 in `TRACKS/TEX12LOCATION.BIN` (pack `TRACK`).
