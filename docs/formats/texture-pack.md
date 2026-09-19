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
| `0x29` | `u8`       | flags (0..7; *not* a mip count) |
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
| `0x54` | `u8`       | `TBW` -- buffer width / 64; always equals `width / 64` here |
| `0x84` | `f32`      | `1.0f` |

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

`AttachTextureDownloadPacket` uploads the pixels with `DPSM` taken straight
from `0x4a`, `DBW` from `0x54` and `TRXREG` from `0x24`/`0x26`, i.e. as a
genuine PSMT8 / PSMT4 host-to-local transfer. Those two transfer paths are the
ones where the GS does *not* write texels in plain raster order, so the data on
disc is pre-arranged to compensate. That pre-arrangement is the familiar PS2
"texture swizzle".

### 8-bit (PSMT8) -- solved

The standard PS2 8-bit swizzle. As a bit permutation of the source byte offset
(`lw` = log2 width):

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

which is what `unswizzle_map8()` computes in closed form. Verified visually:
the HUD dials come out with their `200 300 km/h` legends readable and their
needles and bezels intact, and the car drop-shadow textures resolve into clean
car silhouettes. Dropping the `^ y1 ^ y2` term leaves the image recognisable
but torn into alternating 4-row bands, which is the useful failure signature.

Fine-grained speckle in the decoded dials is ordered dithering in the source
art, not a decoding error -- the flat-shaded textures come out clean.

### 32-bit (PSMCT32)

Stored linearly. Only the alpha doubling is applied.

### 4-bit (PSMT4) -- **NOT SOLVED**

944 of the 1438 textures in this build are 4-bit, and none of them decode yet.
`unswizzle_map4()` ships a placeholder with the right block geometry (32x16
blocks, 32x4 columns, a bijection over exactly `width * height` nibbles) that
does not reconstruct recognisable art, so the real column order differs. Treat
all 4-bit output as wrong. `--swizzle none` dumps the raw nibbles instead,
which is equally wrong but at least unprocessed.

Ruled out so far:

* reading it as 8-bit on a `width/2` buffer with the nibble chosen by `x0`
  (either polarity);
* reading it as 8-bit on a `height/2` buffer with the nibble chosen by `y0`
  (either polarity);
* the nibble chosen by `x4`, i.e. paired texels 16 apart inside the 32-wide
  column (either polarity);
* the 8-bit permutation scaled to nibbles with the nibble chosen by `y1`;
* an exhaustive search over bit-interleavings scored on neighbour similarity
  and on total variation -- both metrics prefer visibly worse mappings, and a
  mip-chain consistency score (level 1 against a box filter of level 0) fails
  to separate the known-good 8-bit mapping from a known-bad one, so automated
  scoring is a dead end here.

The way to close this is almost certainly to transcribe the GS `blockTable4` /
`columnWord4` tables rather than to keep deriving by analogy from the 8-bit
case.

## Sizes below one block

The block geometry only closes on 16x16 (8-bit) and 32x16 (4-bit) boundaries.
Smaller textures -- HUD pips, 8x8 flares -- fit inside a single block and are
stored linearly; the converter falls back to a linear read for them.

## Usage

```bash
python tools/texture_convert.py out/GLOBAL/HUDTEX.BIN --list
python tools/texture_convert.py out/GLOBAL/HUDTEX.BIN png/
python tools/texture_convert.py out/TRACKS/TRACKB12.BUN png/ --swizzle none
```

Output is one PNG per texture under `<outdir>/<pack name>/`. On this build:
84 textures in `GLOBAL/HUDTEX.BIN` (pack `HUD`), 772 in `CARS/TEXTURES.BIN`
(pack `CARTEXTURES`) and 396 in `TRACKS/TEX12LOCATION.BIN` (pack `TRACK`).
