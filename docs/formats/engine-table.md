# `ENGINE.CTB` / `ENGINE.LTB` -- the engine crossfade tables

Two 6504-byte files in `SOUND\` that between them are the entire player car
engine note. Each holds six sample slots and, per slot, a 512-entry curve
giving that sample's volume at a given engine speed. The runtime mixes all
twelve slots every frame and crossfades between them; there is no synthesis
anywhere, just twelve looping ADPCM samples and these curves.

Reader: `tools/engine_table.py` (`--plot` for taller ASCII curves, `--csv` to
export every curve; stdlib only).

The struct layouts are the engine's own, from `docs/mdebug_structs.txt`
(`EngineDef`, `EngineDefEntry`, `EngineDefEvent`). The semantics come from
`PlayerEngineSound` in `obj\release\CarSoundEngine.obj`, `.text` at
`0x001fd078`.

## Layout

```
off     what
0       EngineDef                 360 bytes
360     EngineDefEntry xlate[12]  512 bytes each -- the curves
```

`360 + 12 * 512 == 6504`, the exact size of both files. Unlike almost
everything else on the disc these are **not** `bChunk` containers -- they are
raw structs read straight off the CD.

## `EngineDef`, 360 bytes

| offset | type | field |
|-------:|------|-------|
| 0x00 | `char[4]` | `id` -- always `CRDl` |
| 0x04 | `u8`  | `ver` -- always 2 |
| 0x05 | `u8`  | `resolved` -- 0 on disc, set to 1 once the pointers are fixed up |
| 0x06 | `u8`  | `startevent` |
| 0x07 | `u8`  | `controllerpercent` -- always 100 |
| 0x08 | `s16` | `lowrandomtargetlevel` |
| 0x0A | `s16` | `lowrandomtargetrange` |
| 0x0C | `s32` | `lowrandomattacktime` |
| 0x10 | `s32` | `lowrandomattackrange` |
| 0x14 | `s16` | `highrandomtargetlevel` |
| 0x16 | `s16` | `highrandomtargetrange` |
| 0x18 | `s32` | `highrandomattacktime` |
| 0x1C | `s32` | `highrandomattackrange` |
| 0x20 | `s8[8]` | `patchnum` -- sample index per slot, -1 = slot unused |
| 0x28 | `EngineDefEvent[16]` | `event` -- all zero in both shipped files |
| 0x128 | `u32[8]` | `pvoltable` -- volume curve per slot |
| 0x148 | `u32[8]` | `pbendtable` -- pitch bend curve per slot |

Both files carry identical header values apart from `patchnum`:
`controllerpercent` 100, low random 20/15/500/200, high random
100/40/300/100. The `low`/`high` random fields drive the small idle wobble
`PlayerEngineSound::Update` adds through `bRandom()`.

### The pointer arrays are self-relative

`pvoltable[i]` and `pbendtable[i]` hold a byte offset **from their own
address**, not from the start of the file, so the target is

```
0x128 + 4 * i + pvoltable[i]
```

and a zero means "no table". `PlayerEngineSound::ResolveTables`
(`0x001fd9c8`) walks both arrays doing `*p += (uintptr_t)p` in place and then
sets `resolved` so a second load is a no-op. In both shipped files this
resolves to `pvoltable[i] -> block 2 * i` and `pbendtable[i] -> block 2*i+1`,
i.e. the twelve blocks are laid out vol/bend/vol/bend in slot order.

## `EngineDefEntry`, 512 bytes

A bare `u8 xlate[512]`: the curve itself, one byte per engine-speed step.
Values run 0..127.

## The slots

`patchnum` indexes a fixed twelve-name table in the ELF's `.sdata` at
`0x00324910`:

```
 0 lelo   1 lemd   2 lehi    3 lxlo   4 lxmd   5 lxhi
 6 ceid   7 cemd   8 cehi    9 cxid  10 cxmd  11 cxhi
```

which read as **l**oad / **c**oast, **e**ngine mic / e**x**haust mic, then
the RPM band -- `lo`/`md`/`hi`, or `id`/`md`/`hi` for the coast set whose
bottom band is idle rather than low. So:

* `ENGINE.LTB` is the **L**oad table, used on throttle, `patchnum`
  `{0, 1, 2, -1, 3, 4, 5, -1}`
* `ENGINE.CTB` is the **C**oast table, used off throttle, `patchnum`
  `{6, 7, 8, -1, 9, 10, 11, -1}`

Slots 0-2 are the engine mic's three RPM bands and slots 4-6 the exhaust
mic's; slots 3 and 7 are unused, leaving room for a fourth band per mic.
Slots 4-6 carry curves byte-identical to slots 0-2 -- the two mics share a
crossfade and differ only in which sample they play.

`ActivateSound` decides which mic a slot is by testing the second character
of its name literally (`name[1] ^ 'x'`) and caching the answer per voice.

### Which samples

The sample name is the car's prefix concatenated with the patch name, looked
up in that car's engine bank. For the Ferrari 348, `SOUND\NEWE348.MSH` holds
exactly

```
348CEHi 348CEid 348CEMd 348CXHi 348CXid 348CXMd
348LEHi 348LELo 348LEMd 348LXHi 348LXLo 348LXMd   (+ 348Horn)
```

`PlayerEngineSound::Init` builds each name with `bStrCat`, resolves it with
`bRegion::Sample()`, and initialises both `left[i]` and `right[i]` from it --
the stereo pair is the same sample placed by `Azim`/`Seperation`. See
`docs/formats/sound-bank.md` for the bank format; `tools/audio_convert.py`
will dump these to WAV.

## How a curve is read

`PlayerEngineSound::UpdateEngine` (`0x001fdfd0`) loops over voices 0..15,
taking `definitions[voice >> 3]` -- `.CTB` is `definitions[0]`, `.LTB` is
`definitions[1]` -- and slot `voice & 7`:

```
level = min(440, 440 * CurrentRPM / MaxRPM)             0..440
v     = pvoltable[slot][level] * Volume       >> 7
v     = v * CrossFade[throttle ? r : 127 - r] >> 7      r = throttle * 127
v     = min(127, v * 5 / 4)
v     = v * CrossFade[exhaust ? t : 127 - t]  >> 7      t = Timbre
```

So the curve is indexed by engine speed scaled to 0..440. The shipped curves
are authored out to index 441 and the remaining 70 entries are zero; the
runtime can never reach them.

`CrossFade` is a static 128-entry table at `0x003137b0` and is an equal-power
curve, `CrossFade[i] ~= 127 * sqrt(i / 127)`. It is applied twice: once to
blend `.CTB` against `.LTB` by throttle position, and once to blend engine
mic against exhaust mic by `Timbre`.

The crossfade windows in the shipped data:

| | slot 0 | slot 1 | slot 2 |
|-|--------|--------|--------|
| `.LTB` load  | 0..220 | 110..330 | 221..441 |
| `.CTB` coast | 0..89  | 0..290   | 157..441 |

Three overlapping bells for load, and for coast a narrow idle band under a
wide mid band -- an off-throttle engine spends its time either idling or
trailing down through the mid range.

## `pbendtable` is dead

`ResolveTables` relocates it, but nothing in `CarSoundEngine.obj` ever reads
offset `0x148`: only `pvoltable` at `0x128` is used. Pitch comes from
`EngineSample.detune` through the 256-entry `CentsToPitch` table at
`0x00313838` instead. The bend curves are still authored and still sensible
-- monotonic ramps rising across each band's window -- so a port can either
ignore them, as the PS2 build does, or use them as the pitch ramp they were
clearly meant to be.

## For the 3DS port

Everything needed is already decodable: `tools/engine_table.py` gives the
curves, `tools/audio_convert.py` gives the twelve samples per car. A faithful
reimplementation needs twelve looping voices, the `min(440, 440 * rpm /
maxrpm)` index, and the two equal-power crossfades. The `sqrt` table is
cheap enough to compute at startup rather than baking in the PS2's copy.
