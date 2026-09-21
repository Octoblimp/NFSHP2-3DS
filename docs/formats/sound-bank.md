# `.MSH` / `.MSB` -- bWare sound banks

Every sound effect in the game lives in a pair of files under `SOUND\`: an
`.MSH` index and an `.MSB` blob of PS2 SPU ADPCM. There are 30 banks on this
disc holding 469 patches between them.

Reader: `tools/audio_convert.py` (`--list` for the table, otherwise WAV per
patch plus a `patches.csv`; stdlib only).

Both structs are the engine's own, taken verbatim from the recovered `.mdebug`
type information in `docs/mdebug_structs.txt` -- nothing here was inferred
from byte patterns.

## `.MSH` -- the index

### `SOUND_MSH_HEADER_INFO`, 12 bytes

| offset | type  | field             | meaning |
|-------:|-------|-------------------|---------|
| 0      | `u32` | `MSHSize`         | total `.MSH` size: 12 + 52 * n + `MSHPad` |
| 4      | `u32` | `MSHPad`          | padding after the last record, rounding the file to 64 bytes |
| 8      | `u32` | `NumberOfPatches` | |

### `SOUND_PATCH_INFO`, 52 bytes, one per patch

| offset | type       | field           | meaning |
|-------:|------------|-----------------|---------|
| 0      | `char[32]` | `Name`          | NUL padded (`CopSiren01`, `348Horn`, `MenuSelect`) |
| 32     | `s8`       | `Pan`           | 0 in every bank on this disc |
| 33     | `s8`       | `LoopChannel`   | bit 0 = looping, bit 4 = right half of a stereo pair |
| 34     | `u16`      | `Pitch`         | sample rate in Hz |
| 36     | `u16`      | `Volume`        | 0..0x7fff |
| 38     | `u16`      | `EffectVolume`  | 0 or 0x3fff |
| 40     | `u32`      | `Offset`        | byte offset into the `.MSB` |
| 44     | `u32`      | `ADSR`          | 0 in every bank on this disc |
| 48     | `u32`      | `Reserved`      | 0 in every bank on this disc |

A patch runs from its `Offset` to the next patch's, and the last one runs to
the end of the `.MSB`.

Values actually used across all 30 banks:

* `Pitch`: 22050 (423 patches), 44100 (30), 11025 (13), 8000 (2), 16000 (1).
* `LoopChannel`: 1 (334 -- looping), 0 (105), 16 (28), 17 (2).
* `Pan`, `ADSR` and `Reserved` are always 0, so the ADSR envelope must be
  applied at play time rather than stored here.

### Stereo pairs

The 30 records with bit 4 set are exactly the 30 cases where a patch repeats
the previous patch's name and byte length, and the two halves hold different
audio. They are the left and right channels of one stereo sound -- every
menu effect in `COMMON` is stored this way. `audio_convert.py` joins them
into a single stereo WAV unless `--no-stereo` is given.

### The engine side

`SOUND_GetMSHInfo__FUiP14SOUND_MSH_INFOUi` (`0x00252fb0`) reads a patch record
into the runtime `SOUND_MSH_INFO`; `SOUND_GetMSHSampleCount__FUi`
(`0x00252e58`) reads the header count; `SOUND_PatchMSH__FUiUiUiUi`
(`0x00252ea8`) and `Patch_MSH_PatchInfo__FUiPcUs` (`0x0024db78`) rewrite the
offsets once a bank has been placed in SPU memory, and
`SOUND_TransIOPToSPU__FUiUiUi` (`0x00253f80`) does the upload. The public API
above them is `bSnd_BankLoad()` / `bSnd_VoicePlay()` in `bSnd`.

`SOUND_MIH_INFO` is the same shape for `.MIH`/`.MIB` streamed music, which
this disc does not use -- the jukebox is a single `.JBC` instead.

## `.MSB` -- the audio

Plain PS2 SPU ADPCM, patches concatenated, nothing between them.

* 16-byte frames, 28 samples each.
* Byte 0: `predictor << 4 | shift`. Predictors 0..4 index Sony's usual
  coefficient pairs (scaled by 64): `(0,0) (60,0) (115,-52) (98,-55) (122,-60)`.
* Byte 1: the SPU frame flag -- 1 ends the stream, 3 ends a loop, 4 and 6
  start one, 7 ends without decoding the frame.
* Bytes 2..15: 28 signed 4-bit deltas, low nibble first.

Decoding is the standard recurrence, with the delta sign-extended from bit 15
of `nibble << 12`:

```
sample = (delta >> shift) + ((f0 * prev1 + f1 * prev2 + 32) >> 6)
```

Every patch begins with a frame of zeroes, which is the conventional SPU
lead-in; looping patches then carry flag 4 on the second frame, so their loop
start is sample 28 and the loop covers the whole body.

## Contents

| bank | what |
|------|------|
| `COMMON` | 7 stereo menu effects (start, up/down, left/right, select, cancel, wrong, volume) |
| `FRONTEND` | 50 patches, the frontend soundscape |
| `INGAME` | 68 patches: sirens, road and gravel noise, skids, wind, crash layers |
| `ALPINE`, `DESERT`, `GREECE`, `PARKLAND`, `TROPICS` | per-location ambience (leaves, stream, campfire, birds, frogs) |
| `NEWE<car>` * 22 | per-car engine banks: 12 looping engine states (CE/CX/LE/LX * Hi/Mid/Lo) plus a horn |

The engine-state naming is bWare's: `C`/`L` for coasting and load, `E`/`X`
for interior and exterior, then `Hi`/`Md`/`Lo`/`id` (idle) for the rev band.
`ENGINE.CTB` / `ENGINE.LTB` beside them hold the crossfade tables that pick
between these; those are not decoded yet.

## Usage

```bash
python tools/audio_convert.py out/SOUND/INGAME.MSH --list
python tools/audio_convert.py out/SOUND/INGAME.MSH wav/
python tools/audio_convert.py out/SOUND/COMMON.MSH wav/ --no-stereo --raw
```

Output goes to `<outdir>/<bank name>/`, one 16-bit PCM WAV per patch, plus
`patches.csv` carrying name, channel count, rate, volume, loop flag and loop
points for the port to consume. `--raw` also dumps each patch as untouched
SPU ADPCM. All 30 banks convert in about 14 seconds, producing 439 WAVs.

For the 3DS the WAVs feed `tools/bin/dspenc.exe` to become DSPADPCM, which is
what the 3DS DSP wants. `tools/audio_pack.py` does that end to end; the
result is the `.SBK` below.

## The port's `.SBK`

The 3DS DSP reads Nintendo DSPADPCM and nothing else, so the disc's SPU ADPCM
has to be transcoded before it can be played. Both formats are 4 bits a
sample, so this costs no space: 6.6 MB of `.MSB` becomes 6.51 MB of `.SBK`,
where decoding to PCM16 instead would have cost 23 MB and the ARM11 cycles to
mix it. One `.SBK` per `.MSH`/`.MSB` pair, 30 of them, 439 patches.

Built by `tools/audio_pack.py`, read by `3DS Files/source/sndbank.c`, and the
two are held together by `tools/sndbank_check.py`.

### Header, 32 bytes

| offset | type       | field        | meaning |
|-------:|------------|--------------|---------|
| 0      | `u32`      | `Magic`      | `'SBK1'` = `0x314b4253` |
| 4      | `u32`      | `Version`    | 1 |
| 8      | `u32`      | `PatchCount` | |
| 12     | `u32`      | `DataOffset` | start of the DSPADPCM blob |
| 16     | `u32`      | `DataSize`   | |
| 20     | `u32`      | `NameHash`   | `bStringHash` of the bank name |
| 24     | `char[8]`  | `Name`       | `COMMON`, `NEWE911`, ... NUL padded |

### Patch record, 128 bytes, one per patch, straight after the header

| offset | type          | field          | meaning |
|-------:|---------------|----------------|---------|
| 0x00   | `char[32]`    | `Name`         | the `.MSH` name, NUL padded |
| 0x20   | `u32`         | `NameHash`     | `bStringHash(Name)` -- the lookup key |
| 0x24   | `u32`         | `Samples`      | per channel |
| 0x28   | `u32`         | `DataOffset`   | into the blob |
| 0x2c   | `u32`         | `DataSize`     | both channels together |
| 0x30   | `u16`         | `Rate`         | Hz, the `.MSH`'s `Pitch` |
| 0x32   | `u16`         | `Volume`       | 0..0x7fff, the `.MSH`'s `Volume` |
| 0x34   | `u16`         | `EffectVolume` | |
| 0x36   | `u8`          | `Channels`     | 1, or 2 for a joined stereo pair |
| 0x37   | `u8`          | `Flags`        | bit 0 = looping |
| 0x38   | `s16[2][16]`  | `Coefs`        | DSPADPCM coefficients, per channel |
| 0x78   | `u32[2]`      | --             | zero |

Audio is channel-major within a patch: all of channel 0's frames, then all of
channel 1's. `Samples` and `DataSize` are redundant, deliberately --
`DataSize / Channels / 8` must equal `ceil(Samples / 14)`, and a record where
it does not is rejected rather than played, because that is the one corruption
the DSP would not notice: it would read the next patch and play it as noise.

### Two things the transcode changes

**Stereo pairs are joined.** The 30 records with `LoopChannel` bit 4 set are
the right channel of the record before them and repeat its name, so they
become one two-channel patch under one name -- which is what the engine's own
`bSnd_GetPatchChannels()` returns 2 for.

**Looping patches lose their 28-sample lead-in.** All 334 of the disc's
looping patches loop from sample 28 to their end, without exception, because
the SPU convention is a silent first frame with the loop-start flag on the
second. Dropping those 28 samples makes the whole buffer the loop body, which
is the only shape ndsp can loop without queueing a second `waveBuf`. There is
no patch on the disc that loops from anywhere else, so nothing is lost.

`dspenc` pads its last block out with silence, which would put a gap in the
middle of a loop, so `audio_pack.py` sizes the block to hold the whole patch.
In practice that padding is zero samples wide anyway: every patch is a whole
number of 28-sample SPU frames and 14 divides 28.

### What the checkers actually prove

`tools/sndbank_check.py` runs three passes, and only the second reaches past
the pack to the disc:

```bash
python tools/audio_pack.py extracted/SOUND out/SOUND
python tools/sndbank_check.py out/SOUND --audio --mutate 20000
```

1. **Reader against reader.** `sndbank.c` and the checker's own Python reader
   were both written from this document; both walk all 30 banks and emit a
   line per patch with a CRC of the audio and of the coefficients, plus a
   hash-lookup line. 908 lines, 0 differ.
2. **Pack against disc.** Two readers agreeing about one file says nothing
   about whether the right audio went into it, so `--audio` decodes the
   DSPADPCM back to PCM16 in Python -- a decoder written from the DSP's own
   recurrence, not from `dspenc.c` -- and compares it with the SPU ADPCM
   decoded straight out of the `.MSB`. 469 channels, worst SNR **22.59 dB**
   (`FRONTEND/MenuCarColour`), typical 30-37 dB, nothing under 15. That the
   figure matches `dspenc --verify` to the hundredth of a dB is the useful
   part: two encoders' worth of independent arithmetic land on the same
   number.
3. **Reader against corruption.** `--mutate` flips bits in the header and the
   record table and checks both readers agree on what is still readable. A
   `.SBK` comes off an SD card, and a record that quietly points past the blob
   would reach the DSP as a wall of noise.
