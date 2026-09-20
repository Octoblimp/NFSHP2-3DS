# `MOVIES\*.AVI` -- the MV3 video codec

The movies on this disc are **not** VP6 and **not** EA's `SCHl`/`MVhd`
streaming format, which is what `source/vp6/` (inherited from NFSU2-3DS)
handles. They are ordinary RIFF/AVI files whose video fourcc is `MV30` --
EA's own MV3 codec -- and the decoder for it ships inside `NFSHP2.ELF`.

There is exactly one movie on the disc: `MOVIES\INTRO\EALOGO_EN.AVI`,
955,904 bytes, 512x256 at 30 fps, 90 frames, plus a three-second mono
soundtrack. The `_EN` suffix is the only localisation; no other language
variants were shipped.

Reader: `tools/video_extract.py` (`--list` for the stream and frame tables;
stdlib only, but it needs `tools/mipsemu.py` and the ELF to decode pixels).

## How this one was cracked

Unlike every other format in this directory, the tool does not reimplement
the format -- it **runs the shipped decoder**. MV3 is ~5,000 instructions of
fixed-point IDCT, MMI-vectorised in places, where a hand transcription is a
guess until something checks it. `tools/mipsemu.py` loads the ELF into a flat
memory image and calls `MV3Codec::DecompressFrameShared()` directly, so the
frames that come out are the PS2's own output rather than an approximation.

It costs about 5 million emulated instructions (~16 s) per frame. For one
90-frame movie that is fine.

The format notes below are still a real disassembly of the decoder, and are
enough to write a native decoder from -- they are what a Phase 3 C port would
be built on. Where something has not been pinned down, it says so.

### Where the code is

| symbol | addr | what |
|--------|-----:|------|
| `__8MV3Codec` | `0x002231a8` | constructor; chains to `Codec::Codec()` |
| `__5Codec` | `0x0021c9c8` | builds `ClampTable` and `Bits5to8`, once, under `BaseRefCount` |
| `_GLOBAL_$I$_5Codec$Clamp` | `0x0021cce0` | static initialiser: `OffsetClamp = Clamp + 128` |
| `BeginDecompress__8MV3CodecP10BitmapInfoT1` | `0x002233d0` | validates the headers, `DCTImage::Init()`s the planes |
| `DecompressFrameShared__8MV3CodecUiP16BitmapInfoHeaderPUcT2T3` | `0x002234c8` | the per-frame entry point |
| `ToImage__8DCTImagePUcici` | `0x0021f6d8` | the whole decode loop, 4,624 bytes |
| `Decompress__7HuffmanPsUi` | `0x00221928` | the entropy layer |
| `BuildDecodeTab__7Huffman` | `0x002217a8` | builds the 9-bit decode LUT from `PrefixTab` |
| `InitIDCTTables__8DCTImagecc` | `0x0021f2b8` | quality -> the four dequant tables |
| `IDCT__8DCTImagePsT1PUci` | `0x0021d918` | the full 8x8 inverse transform |
| `CopyPreviousFrameBlock__8DCTImagellPUcT3T3l` | `0x002210e0` | motion compensation |
| `ToImage32__8DCTImagePUci` | `0x00220ac0` | YUV -> RGBA |
| `SwapPrevBuffer__8DCTImage` | `0x00220d50` | this frame becomes the next frame's reference |

Addresses are as printed by `tools/mipsdis.py`.

Struct layouts (`MV3Codec` 648 bytes, `DCTImage` 600, `Huffman` 24) come from
the recovered `.mdebug` type info -- see `docs/mdebug_structs.txt`.

## The container

Plain RIFF/AVI, nothing EA-specific:

```
RIFF 'AVI '
  LIST hdrl
    avih
    LIST strl     strh  fccType 'vids', fccHandler 'MV30'
                  strf  BITMAPINFOHEADER, 512x256, 24bpp, biCompression 'MV30'
    LIST strl     strh  fccType 'auds'
                  strf  WAVEFORMATEX, 0x0001 (PCM), 1ch, 65470 Hz, 8-bit
  LIST movi
    00db          keyframe   -- one, the first
    00dc          delta      -- 89 of them
    01wb          196,608 bytes of unsigned 8-bit PCM, in a single chunk
  idx1
```

196,608 / 65,470 = 3.003 s, and 90 frames at 30 fps = 3.000 s, so the audio is
one unsplit blob covering the whole movie rather than being interleaved. The
sample rate is a genuine 65,470 Hz and not a typo for 65,536 or 22,050.

`db`/`dc` is the standard AVI "compressed DIB, keyframe / delta" distinction
and it agrees with the codec: the keyframe is the only frame whose header
selects the intra-only layout.

## The frame header

Each `00db`/`00dc` payload starts with four bytes, read by
`DecompressFrameShared`:

| offset | type | meaning |
|-------:|------|---------|
| 0 | `s8` | intra quality, on the IJG 1..100 scale. 90 in this movie |
| 1 | `s8` | signed delta added to it for inter blocks. -4 in this movie |
| 2 | `u16` **big-endian** | layout selector. 0 on the keyframe, `0x0100` on every delta |
| 4 | | `pCompData` -- everything else |

The two quality bytes are passed straight to `InitIDCTTables`, which builds
*four* dequant tables per frame: luma and chroma, each at the intra quality
and at `quality + delta`.

Those bytes then become a flags word for `DCTImage::ToImage()`:

| bit | set when | effect |
|----:|----------|--------|
| 0 | the **output** `BITMAPINFOHEADER`'s `biHeight` is negative | `ToImage32` walks the destination backwards, one row at a time |
| 1 | the header `u16` at +2 is zero | select the simple (intra) `pCompData` layout |
| 2 | `MV3Codec::ConvertImageToRGBA` (field +644) is non-zero | convert to RGBA instead of leaving YUV |

Bit 0 is worth spelling out because it is the one that bites. The codec's
planes hold the picture the way the encoder fed it in, which for a
positive-`biHeight` DIB is bottom-up. Clearing bit 0 copies them out in that
order, so a naive read of the buffer comes out upside down. Asking for a
**negative** `biHeight` sets bit 0, `ToImage32` reverses the row order, and
the result is a normal top-down image. `tools/video_extract.py` therefore
passes `biHeight = -height` in the output header.

## `pCompData`

Two layouts, chosen by flags bit 1.

**Simple (intra, the keyframe).** Flags bit 1 set:

```
+0   s16   size of the DCT-type array, in bytes  (little-endian, via GetI16)
+2   u8[]  the DCT-type array               -> DCTImage::pDCTType
+2+n ...   the Huffman bitstream
```

**With motion (inter, every delta).** Flags bit 1 clear:

```
+0   s16   size of the DCT-type array, in bytes
+2   s16   size of the motion-vector stream, in *shorts*
+4   u8[]  (NumVects + 3) / 4 bytes, memcpy'd to DCTImage::pTransp
+m   u8[]  the DCT-type array               -> pDCTType,  m = 4 + (NumVects+3)/4
+m+n ...   the Huffman bitstream
```

In the motion layout the decoder first calls `Huffman::Decompress(pVects,
2 * size)` to unpack the motion vectors, then proceeds as in the simple case.

`pTransp` is a pair of packed bit-planes, two bits per macroblock:

* bit `(i & 3)` -- copy this macroblock from the previous frame
* bit `4 + (i & 3)` -- no residual follows; the copy is the final result

## The DCT-type array

One frame-wide array, **two bits per block**, four blocks packed per byte,
low pair first. The blocks run in raster order: for each macroblock, four
8x8 luma blocks then one U then one V (4:2:0, so a 16x16 macroblock is six
blocks). The two bits index `DCTBlockAdvance` at `0x002a0498`:

| type | `DCTBlockAdvance` | meaning |
|-----:|------------------:|---------|
| 0 | 0 | no coefficients -- `IDCTZero`, or a straight copy on an inter block |
| 1 | 1 | DC only -- `IDCT1` / `IDCTAdd1` |
| 2 | 4 | the top-left 2x2 -- `IDCT4` / `IDCTAdd4` |
| 3 | 64 | the full block -- `IDCT` / `IDCTAdd` |

The value is both the dispatch selector and the number of coefficients to
consume from the decoded stream, which is why the array sizes work out: at
512x256 there are 32x16 macroblocks x 6 blocks = 3,072 blocks, 2 bits each,
= **768 bytes**, exactly the `s16` in the header.

Intra blocks use `DLTab[0]` / `DCTab[0]`; inter blocks use `DLTab[1]` /
`DCTab[1]`, the tables built at `quality + delta`.

## Per macroblock row

`ToImage` loops over `(YSize + 15) / 16` rows. For each:

1. `Huffman::GetBits(16)` -- how many `s16` coefficients this row holds.
2. In the motion layout only, `Huffman::GetBits(8)` -- how many macroblocks
   this row covers. In the simple layout it is always `(XSize + 15) / 16`.
3. `Huffman::Decompress(pDCTData, count)` -- unpack the whole row's
   coefficients in one go.
4. Walk the row's blocks, reading each one's 2-bit type, adding the running
   DC predictor to the block's first coefficient, and dispatching to the
   matching IDCT.

Three DC predictors -- Y, U and V -- are zeroed at the start of every
macroblock row, so a decoder can resync at row granularity but not within a
row.

## The entropy layer (`Huffman`)

Despite the class name this is not a Huffman coder in the canonical sense; it
is a fixed prefix code with an escape into a magnitude-class ladder.

The bit reader is a 32-bit MSB-aligned accumulator (`Huffman::accum`, with
`accumCount` as the live bit count). It refills a byte at a time while fewer
than 25 bits are live.

`BuildDecodeTab` expands `PrefixTab` (12 entries at `0x002a05d8`, each
`length << 16 | code`) into a 512-entry table indexed by the top **9** bits
of the accumulator, two bytes per entry:

```
byte 0   number of bits this symbol consumes
byte 1   the signed coefficient, or one of two markers
```

The twelve prefix codes are `00 01 100 101 110 1110 11110 111110 1111110
11111110 111111110 111111111` -- unary escape with a two-bit base.

Decoding one symbol, from the 9-bit lookup:

* **byte 1 is neither 0 nor -128** -- the common case. Emit it as the
  coefficient and consume `byte 0` bits. One table hit, no branches.
* **byte 1 == 0** -- a run of zeros. Consume the 2-bit prefix, then one flag
  bit: set means a 6-bit field giving `run + 9`, clear means a 3-bit field
  giving `run + 1`. Emit `run` zero coefficients.
* **byte 1 == -128** -- escape. `byte 0` is a magnitude class `k`. Consume
  `PrefixTab[k + 1]`'s bit length, read `k` more bits, and form
  `(1 << k) + bits`, conditionally negated.

The exact condition on that final negation is the one piece of the entropy
layer not re-derived instruction by instruction; `tools/mipsemu.py` executes
it rather than modelling it. Everything else above is read straight off
`Decompress__7HuffmanPsUi` at `0x00221928`.

`Decompress` writes `s16` and stops on a count, not on a marker, so the
caller always knows the length up front -- which is what the `GetBits(16)`
in step 1 is for.

## Quantisation and the IDCT

`InitIDCTTables(quality, delta)` builds four 64-entry `s16` tables inside
`DCTImage`:

| table | offset in `DCTImage` | built from | at quality |
|-------|---------------------:|------------|------------|
| `DLTab[0]` | 88 | `LumaQuant` (`0x002a04c0`) | `quality` |
| `DLTab[1]` | 216 | `LumaQuant` | `quality + delta` |
| `DCTab[0]` | 344 | `ChromaQuant` (`0x002a0540`) | `quality` |
| `DCTab[1]` | 472 | `ChromaQuant` | `quality + delta` |

`ChromaQuant` is the JPEG Annex K chrominance table verbatim; `LumaQuant` is
a lightly tweaked Annex K luminance table. `DCTTable::ConvertQualityToScale`
is IJG's quality-to-scale curve.

Each table is then prescaled in place by `aanscales` (`0x002a0418`, the IJG
AAN scale factors) as `(q * aan + 2048) >> 12`, folding the transform's
row/column scaling into the dequant step. The transform itself is a
Chen-Wang style integer IDCT (`IDCTRowReference` / `IDCTColReference` are the
readable versions; `IDCT` is the MMI-vectorised one actually called).

Output samples are clamped by indexing `Codec::OffsetClamp`, which points
into a 768-byte table: 256 zeros, then the identity 0..255, then 256 copies
of 255. `Codec::Clamp` points at the identity run and is statically
initialised in `.data`; `OffsetClamp = Clamp + 128` is set **only** by the
static initialiser `_GLOBAL_$I$_5Codec$Clamp`, and the table's contents are
filled **only** by `Codec::Codec()`. Anything driving this code outside a
normal boot has to arrange for both, which is why `tools/mipsemu.py` grew a
`run_ctors()`.

## Motion compensation

For an inter macroblock whose `pTransp` copy bit is set,
`CopyPreviousFrameBlock` fetches a 16x16 luma block and the matching 8x8
chroma blocks from the previous frame's planes at the macroblock's motion
vector. If the "no residual" bit is also set the copy is the whole answer;
otherwise the `IDCTAdd*` family adds the dequantised residual on top.

After the frame is complete, `SwapPrevBuffer` exchanges `pData`/`pY`/`pU`/
`pV` with `pPrevData`/`pPrevY`/`pPrevU`/`pPrevV`, so decoding is stateful:
**a delta frame can only be decoded after every frame before it.**
`tools/video_extract.py`'s `--frames N` can therefore only trim from the end.

## YUV -> RGBA

With flags bit 2 set, `ToImage32` does the colour conversion itself. It is
BT.601 at full range, in 8.8 fixed point, two pixels at a time (4:2:0, so one
chroma pair feeds two luma samples):

```
cr = V - 128
cb = U - 128
r  = Clamp[ Y + (359 * cr) / 256 ]
g  = Clamp[ Y - ( 88 * cb + 183 * cr) / 256 ]
b  = Clamp[ Y + (454 * cb) / 256 ]
a  = 255
```

The divisions are arithmetic shifts with a +255 bias on negative values, i.e.
truncation toward zero, not rounding. 359/256 = 1.402 and 454/256 = 1.773 are
the usual BT.601 coefficients.

Bytes land in the destination as **R, G, B, A** -- so the buffer is
RGBA8888 and can go straight into a PNG.

`ToImage32_5P` and `ToImageYUYV` are the alternative output paths (5-bit
packed and YUY2); neither is used here.

## Verified

* `tools/video_extract.py --list` reproduces the AVI's own stream and frame
  tables, and the per-frame quality bytes are constant (90, -4) across all 90
  frames.
* All 90 frames decode, in one 26-minute run costing 4.6M-5.5M emulated
  instructions each. The keyframe is a pixel-accurate EA GAMES wordmark; the
  deltas animate the ring sweep around it and bring up the
  `EAGAMES.COM` tagline, with `CopyPreviousFrameBlock` and the `IDCTAdd*`
  family carrying the motion and `IDCTZero` dropping from 930 calls on frame
  0 to single digits after, exactly as the intra/inter split predicts. The
  last frame is clean, so nothing drifts across 89 chained deltas.
* The audio chunk is plain PCM and is written out unconverted -- AVI and WAV
  agree on unsigned 8-bit and on signed little-endian 16-bit, so there is
  nothing to translate.

## What the 3DS port does instead: bake it

Nothing on the handheld decodes MV3. Porting ~5,000 instructions of
MMI-vectorised IDCT, motion compensation and a prefix-coded entropy layer to
ARM11 to replay three seconds of EA logo is the wrong trade, so the port
decodes the movie once, on a desktop, and ships the result:

```
python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/
python tools/movie_bake.py out/EALOGO_EN <data>/MOVIES/INTRO/EALOGO_EN.M3V
```

`tools/video_extract.py` runs the PS2's own decoder under `tools/mipsemu.py`,
so the 90 PNGs are the console's output rather than an approximation of it,
and `tools/movie_bake.py` turns them into one file the 3DS streams with no
per-pixel work. `3DS Files/source/movie.c` plays it;
`3DS Files/source/main.c` points the title screen's movie plane at it through
`uirender_override_texture`.

### `.M3V`, the baked format

Two ideas, both exploiting the same fact -- this is a logo on a black field:

* **Already in the GPU's layout.** RGB565 in 8x8 Morton tiles, exactly what
  `texpack_upload` builds by hand for every other texture, so a decoded frame
  goes into `C3D_Tex::data` without a swizzling pass.
* **Tile skipping plus RLE16.** A delta frame carries a bitmap of which tiles
  changed and data for those only; the data is runs of `u16` control words,
  bit 15 set for "repeat the next pixel n times", clear for "n literals
  follow". Runs cross tile boundaries, so a black band spanning eight tiles
  costs one control word rather than eight.

Everything is little-endian:

```
0x00  char[4]  "M3V1"
0x04  u16      width, u16 height, u16 frames, u16 fps
0x0c  u16      format (0 = RGB565 / 3DS Morton tiles)
0x0e  u16      bytes per tile (128)
0x10  u32      largest frame payload, so the player sizes one buffer
0x14  u32      frame table offset
0x18  u32      audio offset, u32 audio length, u32 sample rate
0x24  u16      channels, u16 bits per sample
0x28  u32[2]   reserved, zero
0x30           frame table: frames x { u32 offset, u32 length }
               frame payloads
               audio: raw PCM exactly as the AVI stored it

frame payload:  u8 kind (0 = full, 1 = delta)
                if delta: u8[(tiles + 7) / 8] changed-tile bitmap, LSB first
                RLE16 over the changed tiles' pixels, in tile order
```

Frame 0 is the only full frame, so an `.M3V` plays forwards from the start
and does not seek -- the same constraint MV3 itself has, and all
`TitleScreen` ever asks for.

On `EALOGO_EN.AVI` that is **1.50 MB**, audio included: 6.7% of the 22.5 MB
the same 90 frames would cost as raw RGB565, with 10.0% of tiles touched on
average. Frames 65-90, where only the `EAGAMES.COM` tagline blinks, cost
about 320 bytes each.

The audio -- 196,608 bytes of unsigned 8-bit mono at 65,470 Hz -- is carried
through unconverted and is not played yet; sound is Phase 3.

### Checked

`tools/movie_check.py` builds `3DS Files/source/movie.c` for the host, runs
it over a baked file, decodes the same file again with an independent Python
reader, and diffs a CRC32 of the whole tile-order surface after every frame,
plus the header, where `m3v_drive()` lands after stepping at 60 fps, and the
`.AVI` -> `.M3V` path rewriting. On `EALOGO_EN.M3V`: **102 lines, 0 differ**.

And looked at: `--png` untiles the decoded surface back to PNGs. Frame 44 is
the EA GAMES wordmark inside its ring; frame 88 has the `EAGAMES.COM` line
and the `EA GAMES is an Electronic Arts Brand` strapline under it, which is
what `docs/formats/mv3-video.md` predicted from the decoder and what the PS2
shows.

## Still open

* No native C decoder, and there will not be one: the port pre-decodes, as
  above. Anything that needs MV3 decoded on the handheld -- a movie added
  after the fact, or an attract-mode clip streamed rather than shipped --
  would have to write one, and these notes are what it would be built on.
* The sign condition on the entropy escape path (see above).
* `ToImage32_5P` and `ToImageYUYV` are unread; nothing on this disc uses them.
