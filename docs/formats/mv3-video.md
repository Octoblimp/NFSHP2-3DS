# `MOVIES\*.AVI` -- the MV3 video codec and the movies' sound

The movies on this disc are **not** VP6 and **not** EA's `SCHl`/`MVhd`
streaming format, which is what `source/vp6/` (inherited from NFSU2-3DS)
handles. They are ordinary RIFF/AVI files whose video fourcc is `MV30` --
EA's own MV3 codec, whose decoder ships inside the ELF -- with a sound
stream that the header calls 8-bit mono PCM and that is really the SPU's
ADPCM, in stereo.

The port plays them natively: `3DS Files/source/mv3.c` decodes MV3,
`avimovie.c` streams the AVI off the card, decodes the sound and paces both,
and `tools/mv3_check.py` holds the decoder to the retail image's own, run in
`mipsemu`. Retail addresses (SLES_507.31) throughout, with the demo's where
they matter.

## The movies

Retail has twelve boot movies in `MOVIES\INTRO`, all 512x256:

| movie | frames | fps | time | sound bytes | pairs | quality |
|-------|-------:|----:|-----:|------------:|------:|--------:|
| `EALOGO_EN` / `_FR` / `_GE` / `_IT` / `_SP` / `_SW` | 180 | 30 | 6.0 s | 327,680 | 5 | 93, -4 |
| `NFSINTRO_EN` | 2,425 | 30.0003 | 80.8 s | 4,128,768 | 63 | 95, -2 |
| `NFSINTRO_FR` | 2,471 | 30.0003 | 82.4 s | 4,128,682 | 62.999 | 95, -2 |
| `BBGLOGO_EN` | 392 | 30 | 13.1 s | 720,896 | 11 | 90, -4 |
| `REWARD_EN` / `_FR` | 1,131 | 29.97 | 37.7 s | 1,900,544 | 29 | 95, -2 |
| `MAKEOF_EN` | 14,537 | 29.97 | 8 min 5 s | 24,443,721 | 372.982 | 93, 0 |

"Pairs" is the sound's length in 0x10000-byte left/right pairs (see "The
sound"). "Quality" is the first frame's two header bytes.

And five menu movies in `MOVIES`, all 256x384, 900 frames at 30 fps (30 s),
with no sound:

| movie | intra frames | played by |
|-------|-------------:|-----------|
| `MAINMENU_MOVIE` | 10 | `NewMainMenu` |
| `HOTPURSUIT_MOVIE` | 64 | `CopsOnModeSelect`, `StartTheRightMovie` |
| `WORLDRACING_ MOVIE` | 206 | `CopsOffModeSelect`, `StartTheRightMovie` |
| `OPTIONS_MOVIE_NEW` | 39 | `OptionsScreenBase`, `CreditsScreen` |
| `OPTIONS_MOVIE` | 19 | `StartDefaultMovie` (`0x0016d100`), which nothing calls |

`WORLDRACING_ MOVIE.AVI` has the space in its name on the disc, and the
code asks for it that way. `python tools/mv3_check.py --survey` prints both
tables' counts.

**Every frame of every boot movie is intra.** The layout word in each
frame's header is 0, so no frame needs the one before it. That is what lets
the boot movies' player read past frames it is late for (see "The
player"). **The menu movies are nearly all inter**: a keyframe now and then
and deltas between, so they are decoded frame by frame, none skipped. The
demo disc's `EALOGO_EN.AVI` -- 90 frames, one keyframe and 89 deltas -- has
them too, and the port does not play the demo's data.

The menu movies are anamorphic. `NEW_MAIN_MENU`'s `PANELMOVIE` plane is
scaled 1.95 x 0.698, so the 256x384 frame is drawn at 499x268, and the
picture only looks right that way.

The title screen plays `EALOGO_<language>` and then `NFSINTRO_EN`, or
`NFSINTRO_FR` in French (`TitleMoviesToPlay`, `docs/formats/boot-flow.md`).
The other boot movies are not in that table. The menus' movie is
`FlailerScreenList`'s, started by each screen's constructor (see "The
player").

## Where the code is

| symbol | retail | demo | what |
|--------|-------:|-----:|------|
| `Codec::Codec` | `0x00231e10` | `0x0021c9c8` | fills the 768-byte clamp table, once |
| `_GLOBAL_$I$_5Codec$Clamp` | `0x00232128` | `0x0021cce0` | `OffsetClamp = Clamp + 128` |
| `DCTImage::IDCT` | `0x00232d60` | `0x0021d918` | the full 8x8 transform |
| `DCTImage::IDCT1` / `IDCT4` | `0x00233950` / `0x002339a8` | `0x0021e508` / `0x0021e560` | DC only, the 2x2 |
| `DCTImage::IDCTAdd` / `IDCTAdd1` / `IDCTAdd4` | `0x00233c20` / `0x00233fa0` / `0x00234090` | | the same, added onto the block |
| `DCTImage::IDCTAddImageData` | `0x00234aa0` | | the scan, then `IDCTAdd` |
| `DCTImage::DCTImage` | `0x002343d8` | `0x0021ef90` | inverts the scan |
| `DCTImage::Init` | `0x00234560` | | sizes the planes and `pDCTData` |
| `DCTImage::InitIDCTTables` | `0x00234718` | `0x0021f2b8` | two quality bytes -> four dequant tables |
| `DCTImage::IDCTImageData` | `0x00234838` | `0x0021f3d8` | the scan, then the IDCT the mode word picks |
| `DCTImage::IDCTZero` | `0x00234a68` | `0x0021f608` | a block with no coefficients |
| `DCTImage::ToImage` | `0x00234b38` | `0x0021f6d8` | the decode loop |
| `DCTImage::ToImage32` | `0x002363a8` | `0x00220ac0` | YUV -> RGBA |
| `DCTImage::SwapPrevBuffer` | `0x00236638` | | the frame and the one before it trade places |
| `DCTImage::CopyPreviousFrameBlock` | `0x00236950` | | a macroblock of the previous frame, by its vector |
| `DCTTable::ConvertQualityToScale` | `0x00236df8` | | IJG's quality curve |
| `GenerateLuma` / `GenerateChroma` | `0x00236e48` / `0x00236e98` | | one table at a quality, via `ScaleTable` (`0x00236d90`) |
| `Huffman::GetBits` | `0x00237228` | `0x00221728` | refill, then take |
| `Huffman::BuildDecodeTab` | `0x002372a8` | `0x002217a8` | the 9-bit decode table |
| `Huffman::Decompress` | `0x00237428` | `0x00221928` | the entropy layer |
| `GETBITS` | `0x00237660` | | take, without the refill |
| `MV3Codec::MV3Codec` | `0x00238e28` | `0x002231a8` | |
| `MV3Codec::BeginDecompress` | `0x00239050` | `0x002233d0` | checks the headers, `Init`s the planes |
| `MV3Codec::DecompressFrameShared` | `0x00239148` | `0x002234c8` | one frame |
| `MoviePlayer::InitFile` / `Close` | `0x00237ad8` / `0x00237fc8` | | open a movie, and empty the player |
| `MoviePlayer::Update` | `0x002380a8` | `0x002224f8` | paces the menus' movie; makes the sound's `bSample`, stores its rate |
| `FlailerScreenList::StartMovie` / `UpdateMovie` / `StopMovie` | `0x0016ce30` / `0x0016d028` / `0x0016d0a0` | | the menus' movie (`docs/formats/boot-flow.md`) |
| `SOUND_HzToSPU` | `0x0026d258` | `0x002528b8` | every rate bSnd hands the SPU |

| data | retail | what |
|------|-------:|------|
| `aanscales` | `0x002bda88` | the IJG AAN factors, 14 bits |
| `DCTBlockAdvance` | `0x002bdb08` | a block type's coefficient count: 0, 1, 4, 64 |
| `LumaQuant` / `ChromaQuant` | `0x002bdb30` / `0x002bdbb0` | the base dequant tables |
| `PrefixTab` | `0x002bdc48` | 12 x `length << 16 \| code` |
| `Clamp - 256` | `0x0031c6a0` | 256 zeros, the identity, 256 x 255 |
| the scan | `0x0031c9a0` | each natural position's index in the stream |
| the inverse scan | `0x00334a68` | built by `DCTImage`'s constructor |
| `DecodeTab` | `0x00334be8` | built by `BuildDecodeTab` |
| the IDCT mode word | `gp - 15420` (`0x00331cb4`) | 2 on retail: the scalar IDCT |

Struct layouts (`MV3Codec` 648 bytes, `DCTImage` 600, `Huffman` 24) come
from the `.mdebug` type info (`docs/mdebug_structs.txt`).

## The container

Plain RIFF/AVI, nothing EA-specific:

```
RIFF 'AVI '
  LIST hdrl
    avih
    LIST strl     strh  'vids' 'mv30', scale/rate 1/30 or 33333/1000000 or 33367/1000000
                  strf  BITMAPINFOHEADER, 512x256, biCompression 'MV30'
    LIST strl     strh  'auds'
                  strf  WAVEFORMATEX: format 1, 1 channel, 8 bits,
                        nSamplesPerSec = nAvgBytesPerSec = bytes / duration
  LIST movi
    00db ... 01wb ... 00db ...     interleaved
  idx1
```

Every video chunk is `00db`, a keyframe. The sound comes in chunks of up to
the strh's suggested buffer size (191,145 bytes on `EALOGO_EN`, 194,092 on
`NFSINTRO_EN`), and the cuts fall anywhere, even in the middle of an SPU
frame. The strf's numbers are none of them true: the "rate" is just the
sound's byte count over the movie's length (327,680 / 6 s = 54,613 on
`EALOGO`), and nothing reads it. `MoviePlayer`'s `ExtractVideoHeader` reads
the audio strh and never the strf.

`avimovie.c` reads the header and walks `movi` chunk by chunk, into
`LIST rec ` and over `JUNK`.

## The frame header

Each video chunk starts with four bytes, read by `DecompressFrameShared`:

| offset | type | meaning |
|-------:|------|---------|
| 0 | `s8` | intra quality, IJG's 1..100 scale |
| 1 | `s8` | added to it for the inter tables |
| 2 | `u16` big-endian | the layout: 0 is intra, anything else has motion |
| 4 | | `pCompData` |

Both quality bytes are signed. `InitIDCTTables` builds four tables a frame:
luma and chroma, at `quality` and at `quality + delta`. An intra frame only
uses the first luma and chroma pair.

`ToImage` takes a flags word:

| bit | set when | effect |
|----:|----------|--------|
| 0 | the output `biHeight` is negative | `ToImage32` writes the rows bottom to top |
| 1 | the layout word is 0 | the intra `pCompData` layout |
| 2 | `ConvertImageToRGBA` (+644) is set | convert to RGBA |

The planes hold the picture bottom row first, the way a positive-height DIB
is stored, so bit 0 is what turns it top-down. `mv3_to_rgba(m, dst, 1)` is
that; `mv3_to_tiled_rgba8` always writes top-down.

## `pCompData`, intra

```
+0     s16  size of the block-type array, in bytes
+2     u8[] the block types
+2+n   the bitstream
```

The block types are two bits a block, four a byte, low pair first. Blocks
run macroblock by macroblock in raster order, and each 16x16 macroblock is
six blocks: four luma in raster order within it, then U, then V, 4:2:0.
Raster order is the planes', which run bottom row first. At 512x256 that is 32 x 16 x 6 = 3,072 blocks, or 768
bytes. The type indexes `DCTBlockAdvance`:

| type | coefficients | block |
|-----:|-------------:|-------|
| 0 | 0 | `IDCTZero`: mid grey, 0x80 |
| 1 | 1 | `IDCT1`: the DC alone |
| 2 | 4 | `IDCT4`: the top-left 2x2 |
| 3 | 64 | `IDCTImageData`: unscan, then the full IDCT |

## `pCompData`, inter

A layout word other than 0 is an inter frame. `DCTImage` keeps two frames,
the one being decoded and the one before it, each a single allocation of Y,
U and V (each `area` bytes, the Y plane's size rounded up to 128) and then
the motion vectors. `ToImage` ends with `SwapPrevBuffer`, so the frame just
made is the next one's previous.

```
+0     s16  size of the block-type array, in bytes
+2     s16  how many motion vectors
+4     u8[] pTransp: (macroblocks + 3) / 4 bytes
+4+t   the block types
       the bitstream: the vectors, then the rows
```

`pTransp` has a byte per four macroblocks: bit `i` says macroblock `i` of
the four is copied, and bit `i + 4` that the copy has no residual. The
bitstream starts with the vectors, `2 * count` values through `Decompress`,
a `dx, dy` for each copied macroblock in order. Each row then starts with
the intra row's 16-bit coefficient count and an 8-bit count of how many of
its macroblocks carry coefficients, which is what the DC predictors walk.
Block types are listed only for those.

A macroblock that is not copied is coded as an intra one, at the intra
tables. A copied one is `CopyPreviousFrameBlock` at its vector: luma from
`(x + dx, y + dy)` of the previous frame, chroma from half of each, C's
division, toward zero. Then, unless its no-residual bit is set, six blocks
of residual go onto it through the `IDCTAdd` family at the inter tables,
`quality + delta`. A residual block of type 0 is nothing. The adds clamp
through `Codec::Clamp` directly rather than `OffsetClamp`.

A vector may reach past its plane. Retail reads whatever the allocation
holds there, the next plane's bytes or the vectors, and the port keeps the
layout so that it reads the same. One that leaves the allocation reads 0
(`mv3_copy_misses`); retail's data never does.

The port swaps as `mv3_decode` starts, not as it ends. Between frames `y`,
`u` and `v` are then the frame just decoded, which is what the colour
conversion reads.

## Per macroblock row

`ToImage` loops over the rows of macroblocks. For each one:

1. `GetBits(16)`: how many `s16` coefficients the row holds.
2. `Decompress` that many into `pDCTData`.
3. The DC predictors, one each for Y, U and V, start at 0. Walking the
   row's blocks, each block that has coefficients adds its channel's
   predictor to its first and makes that the new predictor.
4. The blocks, dispatched on their types.

`Init` sizes `pDCTData` at a row of full blocks, `mbw * 384`. A count past
that is refused (`MV3_ERR_ROW`).

## The entropy layer (`Huffman`)

A fixed prefix code, not a Huffman code: twelve magnitude classes, with an
escape for the long ones.

The reader is a 32-bit MSB-first accumulator. `GetBits` refills a byte at a
time while fewer than 25 bits are live, then takes. `GETBITS` takes without
the refill. Both shift the way MIPS does, by the low five bits of the
count, so taking 0 bits returns the whole accumulator rather than 0.
Past the end of the frame the port refills with zeros, where the PS2 reads
whatever memory follows.

`PrefixTab` gives each class `k` (0..11) a prefix: `00 01 100 101 110 1110
11110 111110 1111110 11111110 111111110 111111111`. After the prefix come
`k` bits. The top one is the sign, 0 for positive; the rest are the low bits
of a magnitude whose top bit, `1 << (k - 1)`, is implied. Class 0 has no
bits and means a run of zeros.

`BuildDecodeTab` spreads that into 512 entries, indexed by the
accumulator's top 9 bits, of `{ bits, value }`:

* **A value neither 0 nor -128**: emit it, consume `bits`.
* **0**: a run of zeros. Consume the 2-bit prefix and a flag. A set flag
  reads 6 bits of `run - 9`, a clear one 3 bits of `run - 1`. The run is
  written whole even when it passes the count, by up to 72, so `pDCTData`
  needs that slack past the row.
* **-128**: an escape, for a class whose prefix and bits do not fit in 9.
  `bits` holds `kk = k - 1`. Consume class `kk + 1`'s prefix, then one sign
  bit (1 is negative), then `kk` bits of magnitude under an implied
  `1 << kk`.

The demo's notes left the escape's sign open. It is the bit straight after
the prefix, and the checker's random streams take it both ways.

## Quantisation and the IDCT

`GenerateLuma` and `GenerateChroma` scale the base tables by IJG's curve:
`scale = q < 50 ? 5000 / q : 200 - 2q`, with q clamped to 1..100 first, and
each entry is `(base * scale + 50) / 100`, clamped to 1..32767. Then
`InitIDCTTables` prescales every entry by `aanscales` as
`(entry * aan + 2048) >> 12`.

The transform is IJG's "ifast" AAN IDCT, not a Chen-Wang one. Its
constants are 8-bit fractions: 362 (1.414), 473 (1.848), 277 (1.082) and
-669 (-2.613). `IDCTImageData` first scatters the stream through the
inverse scan into natural order, then picks a transform by the mode word at
`gp - 15420`. On retail that word is 2, the scalar `IDCT` at `0x00232d60`.
Columns go first, each coefficient dequantised as it is read. Rows go
second, each output shifted down 5 bits into `OffsetClamp`. The arithmetic
is the PS2's: 32-bit wrapping products and sums and arithmetic shifts, so
`mv3.c` works in `uint32_t` and shifts through `SRA`.

`IDCT1` fills the block with `OffsetClamp[(dc * q) >> 5]`. `IDCT4` is the
same pair of passes with only the top-left 2x2 live. When a column's second
coefficient, or a row's, is 0, it copies instead of transforming.

`OffsetClamp` points 128 bytes into the identity run of a 768-byte table,
and the PS2 indexes it without a bound. Retail's own data never reaches
past it (the checker counts), and the port saturates if it ever does
(`mv3_clamp_misses`).

## YUV -> RGBA

`ToImage32` is BT.601 at full range in 8.8 fixed point, one chroma pair to
a 2x2 of luma:

```
cr = V - 128, cb = U - 128
r = Clamp[Y + 359 * cr / 256]
g = Clamp[Y + (-88 * cb - 183 * cr) / 256]
b = Clamp[Y + 454 * cb / 256]
a = 255
```

The divisions round toward zero (a +255 bias below zero, then a shift).
`mv3_to_tiled_rgba8` writes the same pixels straight into the PICA200's
RGBA8 texels, in 8x8 Morton tiles and top row first, so a frame goes into
the texture without a swizzle pass. A 2x2 quad is four consecutive texels in
Morton order, and it shares one chroma sample.

## The sound

The sound stream is PS2 SPU ADPCM: 16-byte frames of 28 samples, the codec
the sound banks use (`docs/formats/sound-bank.md`). Byte 0 is
`predictor << 4 | shift` and byte 1 the flags. The nibbles run low first,
and each sample is

```
s = (sext16(nibble << 12) >> shift) + ((f0 * s1 + f1 * s2 + 32) >> 6)
```

clamped to 16 bits, with the filters `{0, 0}, {60, 0}, {115, -52}, {98, -55},
{122, -60}`. A predictor above 4 is taken as 0. The movies carry no loop or
end flags.

It is in stereo, in pairs of blocks: 0x8000 bytes (2,048 frames) of the
left channel, then 0x8000 of the right. Each channel's history runs on from
its own previous block. Every retail movie but two is a whole number of
pairs. `MAKEOF` and `NFSINTRO_FR` end with part of one, and their tails are
silent.

None of that is in the EE's code: the IOP fed the SPU, and the layout is
worked out from the data. The rate is the EE's. `MoviePlayer::Update`
makes the stream's `bSample` and stores `0xaa66`, 43,622, over its rate
(`ori` at `0x002381b0`). The jukebox's caller writes the same field with
the JBC header's 32,000, so it is a rate in Hz. Every rate bSnd gives the
SPU goes through `SOUND_HzToSPU`, `(hz << 12) / 48000`, which makes pitch
3,722: 43,617 Hz, for every movie, whatever the strf says.

`avisound_*` in `avimovie.c` holds the stream's bytes until a whole pair is
in, because the chunks cut it anywhere, and then decodes it a frame of each
channel at a time into interleaved stereo PCM. A partial pair never plays.
On the 3DS the PCM goes to ndsp channel 23, the one `bsnd` leaves free
(`BSND_HW_VOICES`), at `avisound_rate_hz()`: 43,617 Hz, through bsnd's
own round trip. It plays from a ring of six waves of 7,168 samples each,
about a second queued.

## The player

`AviMovie` reads the file a chunk at a time. `avimovie_advance(m, target)`
reads on until frame `target` has been read, hands every sound chunk on the
way to the sound, and decodes `target` alone of the video chunks it passes.
Every frame of a boot movie is intra, so a player that has fallen behind
skips straight to the frame that is due and stays in time with the sound.

The clock is the console's tick from the moment the movie opened, and the
frame due at `t` seconds is `floor(t * rate / scale)`. A movie is over when
`movi` is used up and the clock has passed `frames * scale / rate`. On
Azahar at 100% the intro decodes 366 of the first 591 frames and reads past
the rest; the EA logo decodes 154 of its 180.

The title screen draws the texture through its movie planes, and the port
stretches it across the whole top screen (`docs/formats/boot-flow.md`).

The menus' movies cannot be read past: an inter frame is drawn over the one
before it. They are paced the way retail paces every movie, by
`MoviePlayer::Update`, which `FlailerScreenList::UpdateMovie` calls once a
frame:

1. `InitFile` zeroes the counters (+0, +12 and +1056..+1088), keeps the
   frame's length in seconds at +4 (`scale / rate`) and the file at +28,
   and decodes nothing.
2. `Update` answers 0 with no file open. Otherwise it reads on, then takes
   the vblank rate from `GetVideoMode` (`0x001a3390`): 50.0 on PAL, 59.94
   otherwise.
3. The first call notes the start, `eVBlankCounter / rate` (plus 0.16 s
   when the movie has sound).
4. Every call takes `t = max(vblanks / rate - start, 0)` and the frame due,
   `target = t / length`, truncated. When fewer than `target` frames have
   been decoded, or none has, it decodes the next one: one a call, in
   order, never skipping. A movie that falls behind plays slower.
5. It answers 1 while frames are left, and 0 once the last is decoded and
   the stream is empty. `UpdateMovie` reopens the movie on a 0, so the
   menus' movie loops.

`avimovie_step` is that rule, and `aviplayer_init` and `aviplayer_update`
drive it off the console's tick where retail counts vblanks. At an exact
frame boundary retail's vblank count lands a vblank later than the tick,
so the two can take a frame a frame apart and agree again on the next.

A menu movie is 256x384 but plays wider than tall: `NEW_MAIN_MENU`'s
`PANELMOVIE` plane draws it at 499x268 (`docs/formats/boot-flow.md`).

On Azahar at 100% a menu frame costs about 22 ms to read and decode and 9
to convert into the texture (`movie cost` in the log; the EA logo's intra
frames are 16 and 12). That is more than a frame at 30 fps, so the player
is always behind and decodes on every call. The main menu then runs at
about 25 FPS and its movie with it: 900 frames in 35.5 s, 85% speed. The
Cops screens, which cost more to draw, run at 20 to 22. Retail's loop ran
at 50 or 60 Hz, well above the movie's rate, so it never met this.

## Checked

`python tools/mv3_check.py` holds `mv3.c` to the retail image, run in
`mipsemu`, and `avimovie.c` to the checker's own reading of RIFF and the
sound:

- `BuildDecodeTab`'s 512 entries, and `InitIDCTTables` at every kind of
  quality pair: both halves of IJG's curve, 1 and 100 and past them, and
  bytes with the sign bit set.
- `GetBits` at every width across refills, and `Decompress` over random
  streams that reach every class, the escape's sign both ways, both run
  lengths, and runs that write past the count.
- Every IDCT on random blocks at real tables, with DCs that clamp at both
  ends, and `ToImage32` on random planes in both row orders.
- Whole frames of retail's movies through `DecompressFrameShared`: each
  boot movie's first, a middle and its last, and one of each other kind.
  They are compared as CRCs of the RGBA and of the port's tiled texture
  read back into rows, with the port's clamp misses at 0.
- Inter frames decoded in order from a new codec, compared plane by plane,
  so a wrong copy or residual carries on into the next frame. Four
  synthetic movies, which the checker encodes with the image's own prefix
  code and scan: every kind of macroblock (coded, copied with a residual,
  copied without), frames all of one kind, four sizes, ten quality pairs,
  and either byte of the layout word set. Then two runs of
  `MAINMENU_MOVIE`: its first six frames, and six from 473, across two
  keyframes. All the frames share one emulator, and `BuildDecodeTab`'s 12.7
  million instructions run once; a later call only checks that the table
  is unchanged.
- The `IDCTAdd` family on the same blocks, added onto zeros, 0xff and
  noise so the sums clamp both ways. `CopyPreviousFrameBlock` at four sizes
  and six kinds of vector, from inside the frame to past either end of the
  allocation, with odd and negative ones for chroma's rounding.
- Every retail movie's header and chunk list, and the pacing over a
  schedule of clock times (which frames are decoded, which read past, which
  sound chunks are handed on), on three movies and a synthetic AVI with
  what retail's files leave out. `avimovie_step` against retail's own
  `MoviePlayer::Update`, run on a player whose ring buffer is the movie's
  chunks: a synthetic inter movie called at 50 Hz and slower, the synthetic
  AVI for its sound chunks, and `MAINMENU_MOVIE` to its end and past it,
  with a stretch left out so that it falls behind and catches up.
- The sound against `audio_convert.py`'s SPU decoder, the one
  `sndbank_check` holds the banks to: two boot movies' whole streams as the
  player reads them, and random streams over every predictor and shift,
  clamping both ways, with a partial pair at the end. They are pushed in
  sizes from a byte to three pairs and pulled from none to a whole block.
  The rate is read out of the image: `Update`'s immediate and
  `HzToSPU`'s arithmetic.

It runs in about three and a half minutes, most of it retail's decoder on
the inter sequences. `--mutate` breaks `mv3.c`, `avimovie.c` and
`avimovie.h` one way at a time (the tables, the reader, the escape, each
IDCT and its adding twin, the copy, the inter layout, the colour, the
container, both pacings, the sound's decoder, layout, stream and rate). Of
171, 168 are caught. Some hang the harness, which counts: `pace-done` and
`pace-first` leave a movie that never ends. The other three are equivalent
by construction: they turn off the 4-point IDCT's shortcuts for a zero
coefficient, in the columns, the rows and `IDCTAdd4`'s rows, and the long
way computes the same values.

The mutants are written into the real sources and restored afterwards, so
nothing may be built while `--mutate` runs. One ARM build did, took
`pace-done` with it, and hung the EA logo on its last frame on Azahar.

## Still open

- Two of `Update`'s answers are not ported: 0 after 20 s without a frame
  (`RealTimeFrames`, `gp - 19600`), and 1 while its ring buffer waits on
  the disc. A movie read off the card never needs either.
- The IOP's side of the sound: whether its streaming module did anything
  to the rate before the SPU. The EE's 43,617 Hz is what the port plays.
  It is not settled from the data whether the content was mastered at
  44.1 kHz. If it was, retail's sound ran 1.1% slow and ended up 0.9 s
  behind the intro's picture, and the port does the same.
- Decode speed. The numbers above are Azahar's emulated Old 3DS. The menu
  movies are too slow there to keep 30 fps (see The player). On the host a
  menu frame's decode is about 35% `Decompress` and 60% IDCTs, over 1,450
  to 1,550 full 64-coefficient blocks a frame.
- `ToImage32_5P` and `ToImageYUYV` are unread; nothing uses them.
