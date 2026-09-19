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
what the 3DS DSP wants; that step is Phase 3 task 22 and is not wired up yet.
