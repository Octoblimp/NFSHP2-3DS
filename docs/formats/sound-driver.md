# `bSnd` -- the voice layer

`bSnd_*` is the sound API the game actually calls: the frontend asks for
`bSnd_VoicePlay("COMMON", "MenuSelect")` and the layer below finds a free SPU
voice, works out what volume each side should get, and starts it. Everything
here was read out of `PS2 Files/NFSHP2.ELF` -- the addresses are in the table
below, and `PS2 Files/NFSHP2.MAP` names the functions, including their C++
argument types, which is how the overloads below are told apart.

The bank format the layer plays out of is `docs/formats/sound-bank.md`. The
port: `3DS Files/source/bsnd.c`, checked by `tools/bsnd_check.py`.

## Where things are

| address | symbol | what |
|---------|--------|------|
| `0x247f00` | `bSnd_VoicePlay(char const*, char const*, uint, ushort, ushort, uint, uint, ushort)` | the master overload; every other one tail-calls it |
| `0x247ad8` | `bSnd_VoicePlay(..., uint, ushort, schar, uint, uint)` | the pan-taking form |
| `0x247b78` | `bSnd_VoicePlay(char const*, char const*)` | bank + patch, everything else defaulted |
| `0x24d928` | `GetVolumesFromPan(ushort*, ushort*, ushort, schar)` | volume -> left, right |
| `0x24f688` | `GetPanFromAzimuth(ushort)` | azimuth -> pan |
| `0x24f8a8` | `GetVolumesFromAzimuth(int*, int*, int, int, int)` | Prologic only |
| `0x24e660` | `GetChannelNum(uchar)` | `LoopChannel >> 4`: 0 mono, 1 stereo |
| `0x24e6b0` | `GetLoop(uchar)` | `LoopChannel & 1` |
| `0x2528b8` | `SOUND_HzToSPU(uint)` | Hz -> SPU pitch register |
| `0x2520c0` | `SOUND_FindFreeSPUChannels(uint, uint, uint, bool, char*)` | the allocator |
| `0x316a50` | `bVoiceMgr::Voices` | 48 voice records, 80 bytes each |
| `0x3179a0` | (the key array) | one byte per voice: 0 off, 3 on, 4 releasing |
| `0x317d00` | `bSnd_nArraydBPanTable` | 256 `u16`, the pan curve |

## The pan table

256 `u16` at `0x317d00`, indexed by `pan + 127`, so entry 127 is centre. It is
a quarter cosine: entries 0..224 are exactly

    table[i] = int(16383 * cos(i * pi / 512))

-- entry 0 is 16383, entry 224 is 3196 -- and from 225 on it leaves the curve
and falls away faster than the cosine would (2726 where the formula wants
3097), down to 5 at entry 254. `tools/gen_bsnd_tables.py` extracts it into
`bsndtab.c` and verifies both halves of that claim: the cosine by recomputing
it, the tail by asserting entry 225 is *off* the cosine, so a later edit that
"fixes" the table into a pure cosine fails instead of silently changing every
sound's balance.

Because the index is `pan + 127` and the right channel reads `127 - pan`, a
centred voice gets `table[127]` = 11655 on both sides, which is 0.711 of full
-- the equal-power pan law, down about 3 dB in the middle so that a sound
panning across keeps its loudness instead of bulging at the centre.

## Volumes

`GetVolumesFromPan` is four lines:

    if (mode < 2) pan = 0;                          // mono: no balance at all
    *left  = (volume * table[pan + 127]) >> 14;     // arithmetic shift
    *right = (volume * table[127 - pan]) >> 14;

`mode` is the byte at `gp-15348`: 1 mono, 2 stereo, 3 Prologic. With `volume`
at most `0x7fff` and the table at most 16383, neither side can exceed `0x7ffe`.

`pan = -128` indexes `table[-1]`, reading the `u16` in front of the table. On
the play path that cannot happen -- `-128` means "use the patch's own pan" and
is substituted before the call -- but `bSnd_SetVoicePan(v, -128)` reaches it.
**The port clamps to -127 instead**, which is the one place `bsnd.c`
deliberately does not do what the ROM does; reading off the front of a table
is not behaviour worth reproducing, and no disc patch has a nonzero pan to
reach it with anyway.

## Azimuth

An azimuth is a full circle in `u16`: `0x0000` ahead, `0x4000` right,
`0x8000` behind, `0xc000` left. `GetPanFromAzimuth` folds it onto the pan axis
by quadrant, each arm a multiply by 127 and an arithmetic shift right 14 with
the usual negative-rounding fixup (`x < 0 ? x + 16383 : x`):

| azimuth | pan |
|---------|-----|
| `<= 0x4000` | `az * 127 >> 14` |
| `> 0xbfff` | `(0x10000 - az) * -127 >> 14` |
| `0x8000..0xbfff` | `(az - 0x8000) * -127 >> 14` |
| else (`0x4001..0x7fff`) | `(0x8000 - az) * 127 >> 14` |

Front and back fold onto the same pan, which is the whole point: with two
speakers there is nothing else to do with "behind you".

`GetAzimuthFromPan` goes the other way in single precision -- `pan *
129.00787353515625f`, negated and taken from 65536 for a negative pan -- so
the round trip is not the identity and is not meant to be. The port keeps the
float arithmetic in `float`, because the EE has no double and a Python model
using one would diff against the C for the wrong reason.

`GetVolumesFromAzimuth` returns at its first branch unless `mode == 3`. So on
a stereo TV an azimuth reaches the mix **only** through `GetPanFromAzimuth`;
what it otherwise changes is the stored `Azimuth` and the voice's `Type`,
which becomes 4 instead of `loop + 1`. The one thing the call does leave
behind on every path is the `& 0x7fff` the caller applies to both volumes
afterwards -- dead with the values above, kept in the port because it is
cheap and the next person to widen a volume should not have to rediscover it.

## `bSnd_VoicePlay`, the master overload

Arguments: bank, patch, `rate`, `volume`, `azimuth`, two `u32`s, `voice`.
The two `u32`s are used by the queueing path only (below); the normal path
ignores them, and the port leaves them out.

Before anything else, `pan = GetPanFromAzimuth(azimuth)`. There is no pan
argument: the overloads that take one convert it to an azimuth first and come
back through here.

Then the bank name decides which of three paths runs:

- 7 characters matching `gp-15224` -- the streaming path, which defaults
  `rate` to 22050 rather than to the patch's, and forces a `-128` pan to 0.
- 16 characters matching `gp-15208` -- a queue: the call is appended to eight
  52-byte slots at `0x328938` with the two spare `u32`s, `rate` and `volume`,
  and played later. Overflowing eight slots prints and resets the count.
- anything else -- the normal path, which is what the frontend and the port
  use, and what the rest of this section describes.

1. `bSnd_GetPatchID(bank, patch)`; `0xfffa` (no such patch) returns `0xfffe`.
2. `channels = GetChannelNum(LoopChannel) + 1`. A nonzero azimuth on a
   multi-channel patch prints a warning and carries on.
3. If `voice == 48` the allocator picks one; otherwise the voice is taken as
   given, and a **stereo** patch whose `voice + 1` would reach 48 returns
   `0xfffc`. A mono patch is not bounds-checked here at all.
4. `rate == 0xffffffff` takes the patch's `Pitch`; `volume == 0xffff` takes
   the patch's `Volume`.
5. Per channel `n`:
   - stereo forces `pan = (n == 0) ? -127 : 127` -- a stereo patch is hard
     left and hard right, and its `Azimuth` is ignored for the mix;
   - mono with `pan == -128` takes the patch's own `Pan` field.
   - `GetVolumesFromPan`, then the azimuth pass, then the record is filled:

| offset | field | value |
|-------:|-------|-------|
| 0  | `Pan` | as resolved above |
| 1  | `LoopChannel` | `GetLoop(flags) + ((channels - 1) << 4)` |
| 4  | `Type` | `azimuth ? 4 : GetLoop(flags) + 1` |
| 8  | `Pitch` | rate in **Hz**, not the SPU register |
| 12 | `Volume` | as resolved above |
| 16 | `VolumeLeft` | |
| 20 | `VolumeRight` | |
| 24 | `EffectVolume` | the patch's |
| 28 | `ADSR` | the patch's, or `0x1a00000a` if that is 0 |
| 32 | `BankName` | 16 chars |

Every patch on this disc has `ADSR = 0`, so `0x1a00000a` is what every voice
in the game actually gets.

The call returns the first voice, `0xfffe` for an unknown patch, `0xfffc` for
a bad explicit voice, and `0xfffa` when nothing could be allocated.

## The allocator

`SOUND_FindFreeSPUChannels(first, last, count, ignoreKeys, keys)` walks from
`first` toward `last` -- backwards if `last < first` -- counting voices whose
key byte is 0 and whose lock byte is clear, and returns the start of the first
run of `count` of them. Out-of-range endpoints return -2 (`first`) and -3
(`last`); no run returns -1. Walking backwards returns the *low* end of the
run either way, so a pair is always `(n, n+1)`.

Locks are separate from keys: a locked voice is skipped by the allocator but
keeps playing. That is how the engine reserves voices for the car it is
following without stopping what is already in them.

`bSnd_LockChannels(count)` (`0x002638a0`) is an allocator too: it finds the
first run of `count` voices that are neither locked nor sounding, walking
down from 47, locks it and returns its low end, or `0xfffc` when there is
none. bSample takes every voice it plays on this way, so bSound's voices come
from the top while `bSnd_VoicePlay`'s own allocation comes from the bottom.
`bSnd_UnlockChannels(first, count)` (`0x002639a0`) gives the run back.

## What bSound asks of the banks

bRegion and bSample (docs/formats/bsound.md) read the banks by name:

| | address | answers |
|---|---|---|
| `bSnd_BankNumber` | `0x00260b38` | the bank's slot, `0xffff` when not loaded |
| `bSnd_GetNumberOfPatches` | `0x00264cf8` | 0 for a bank not loaded |
| `bSnd_PatchName` | `0x00264e10` | the k'th patch's name, in one buffer each call overwrites |
| `bSnd_GetPatchID` | | `0xfffa` when either name misses |
| `bSnd_GetPatchPitch`, `GetPatchVolume`, `GetPatchChannels` | `0x00264f58`, `0x00265088`, `0x002652b0` | 0 when either name misses |

The disc counts patches as the records whose channel number is 0, which is
every patch but a stereo pair's right half; .SBK has joined those already.

`bSnd_SetVoiceAzimuth` (`0x00263f40`) pans each channel of a voice, both of a
stereo pair, to the azimuth's pan at its own volume. A voice's near end
(`0x00263090`) is 0 for any voice that is not a stream.

## What the port does differently

The 3DS has 24 ndsp channels against the PS2's 48 SPU voices, and ndsp's
DSPADPCM is mono per channel -- which is already how the PS2 plays a stereo
patch, as two voices. So the allocator is the same code with a shorter range,
and `BSND_PS2_VOICES` stays in the header so the checker can drive the
original width as well as the port's.

The sentinels move, because the port's "let the allocator pick" cannot be 48
when 48 is not off the end any more:

| | PS2 | port |
|---|---|---|
| allocate a voice | `48` | `BSND_VOICE_ALLOC` = `0xffff` |
| use the patch's rate | `0xffffffff` | `BSND_RATE_PATCH` |
| use the patch's volume | `0xffff` | `BSND_VOLUME_PATCH` |
| use the patch's pan | `-128` | `BSND_PAN_PATCH` |

Everything else -- the pan table, the shifts, the rounding, the quadrants,
the record layout, the return codes -- is the ROM's. `tools/bsnd_check.py`
drives both the port and an independent Python model of this document through
twelve scenarios and diffs the transcripts line for line.

The ndsp sink's `hw_mix` turns each side's volume into a channel mix of
`volume / 16383`, clamped at 1.0 (a volume can come in at up to `0x7fff`), and
then doubles it, 6 dB. That gain is the port's: bSound's categories put the
effects at 0.31 to 0.55 of full (jukebox.c's `kDefaultVolume`), a level set
for a TV's amplifier and too quiet on the 3DS's speakers. Every voice takes
it, so the categories keep their balance among themselves; the music is its
own ndsp channel in `jbstream.c` and keeps its level. The checker never sees
the sink, so it is unchanged.

The streaming and queueing paths are not ported. Nothing in the frontend
reaches them, and the music they exist for is task 29's problem. So no voice
is a stream, and the near end is always false.
