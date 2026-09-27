# The retail build

`PS2 Files/Full Game/` is the PAL retail disc: `SLES_507.31`, built in
August 2002, with `ZDIR.BIN`, `ZZDATA.BIN` and the IOP modules. Everything
before it was ported from `PS2 Files/NFSHP2.ELF`, the June 2002 demo disc.
This file says what differs and how the tools bridge it.

## The ELF

`SLES_507.31` is the retail game's program, the counterpart of the demo's
`NFSHP2.ELF`. The disc's `SYSTEM.CNF` boots it (`BOOT2 =
cdrom0:\SLES_507.31;1`, `VMODE = PAL`), and the name is the product code,
SLES-50731, the PAL release. The 3DS build never ships or reads it: the
game runs on its own C and the extracted data. The tools on the PC read it
as the reference for the full game's code: the matcher, the audit, and the
checkers' retail model (`tools/retail_model.py`).

The retail ELF is stripped: no `.symtab`, no `.mdebug`. Its `.text` is
431,681 words to the demo's 402,445. gp is `0x003358f0` (demo
`0x00328bf0`).

**The demo already carries most of the full game's code.** The memory
card flow, the save game, the autosave, the event tree (career) and the
tourney screens are all in the demo ELF. What made it a demo was its data
(one track, a few cars) and `TheDemoDiscManager`, whose `bActive` nothing
sets. So the retail ELF matters for what it changed and for the code the
demo does not have, not as a whole new game to read.

### Carrying the names over

`tools/retail_match.py` pairs each demo function with its retail twin. See
its docstring for the passes: masked exact matches, then call pairs, vtable
slots and shared data as evidence, then gap alignment between known
neighbours. The demo side is `.symtab` plus the 1,336 procedures only
`.mdebug` lists (`tools/mdebug.py`), which are each unit's own copies of
inline destructors and `operator delete`, and the statics.

```
demo bodies 9669: same 6980, changed 2352, unplaced 337
retail .text covered: 391435 of 431681 words (90.7%)
retail code with no demo twin: 1063 pieces, 142,372 bytes
```

- `--out out/retail_syms.txt` writes the whole map: each retail
  function's address and size, `same` or `changed`, the match ratio and
  the demo name. It takes 25 seconds, so it is not committed.
- `--diff NAME` prints a demo function and its twin side by side.
- `--audit docs/retail_audit.txt` is the port's own list, below.

Two known limits:
- A changed function's retail extent ends at the first unit start that
  follows a return or that another placement holds. It is cut at the
  return that gives it as many returns as the demo body. A function that
  ends in a call to something that never returns can run on into the next.
- Where retail wrapped a function (EndPullover(int) is now `move a1,a0 ;
  j body ; lw a0,gp`), the placement is the wrapper, 4 words.

Gap alignment cuts retail's code at every return that no branch crosses.
A function with two exits has a return in the middle, and the branch that
skips it lands past it. Cutting there anyway once put UnloaderHeliSheet
on the three words after LoaderHeliSheet's first return.

### What the port cites

`docs/retail_audit.txt` lists every demo function address the port's
sources cite, with its retail twin:

| kind | all | cited from a `.c` |
|---|---|---|
| same | 1,148 | 464 |
| layout | 139 | 73 |
| changed | 301 | 130 |
| unplaced | 29 | 13 |

- **same**: the same instructions once link addresses are masked.
- **layout**: the same but for load and store displacements, stack
  offsets and member-address addius. The port needs nothing for these: its
  structs keep the demo's layout, and nothing on the 3DS reads the PS2's.
- **changed**: the code differs. The `code` column is how much still
  agrees once offsets are set aside. Low values are either a rewrite or a
  compiler change. GetHorizontalGroundForceInCarFrame is an inlined matrix
  multiply now, the same maths. Others are real behaviour. SetBoost now
  scales the boost it hands the engine by a constant when two car flags
  are set.
- A citation only in a header is mostly a seam, a function the port calls
  through a pointer and has not ported.

### Where the fields went

`tools/retail_layout.py` infers, per class, where retail moved each demo
field. Wherever a demo method and its twin line up but for displacements,
a load or store off `this` in both is a vote for demo offset -> retail
offset. `docs/retail_layout.txt` prints each class where the shift
changes. 91 classes moved. A few:

```
Car             2016 bytes   +4 at 960, +16 at 1088, ..., +184 at 1960
CarRenderInfo   1856 bytes   +16 at 740, +28 at 1348, +484 at 1852
FlailerObjectChunk, FlailerTextChunk, FlailerBitmapChunk   +24 at the start
CarSelector     reordered: LoadedCar 312 -> 80
```

This is what lets retail code be read in the demo's field names, and it is
the map a checker will need to lay a scenario out for the retail image.

## The retail model

`tools/retail_model.py` puts the retail image in mipsemu under the demo's
names. `retail_model.emu(True)` is a `RetailEmu`. `addr_of`, `call` and
`stub` take demo names and resolve them to retail addresses through the
matcher's map. Three calls take a demo address or offset:

- `e.code(a)` gives the retail twin of a demo function address.
- `e.data(a)` gives where retail keeps a demo datum. It uses the data map
  first. Then the object that holds it, moved as a whole. Then a single
  vote that nothing contradicts.
- `e.field(cls, off)` gives retail's offset for a demo field.

The plain `Emu` answers the same three calls with what it is given. So a
checker written with them runs either image. The matcher's result is
cached in `out/retail_map.json` and rebuilt when either ELF or a matching
tool changes: 8,026 names, 4,210 data addresses (2,982 more on one vote),
and 400 classes' fields.

### Two images, one harness

The port follows retail's behaviour. It keeps the demo's names, and the
demo's struct layouts wherever the PS2's layout does not reach the 3DS. A
record read in place from the disc takes retail's layout, because the port
reads retail's discs. TrackInfo is one.

A checker whose object retail changed runs two scripts through the same
harness:

- scenarios over the functions the port follows as retail has them run on
  the retail image, over `extracted-retail/`;
- the rest run on the demo image, over `extracted/`, as before.

Both transcripts must match the port's. A demo scenario over code retail
changed would fail, so the split is also the list of what is still the
demo's. Two checkers have it so far:

- `track_check.py`: the track info is retail's; the topology is still the
  demo's.
- `loadertable_check.py`: the claims, and the walks through LoadChunks,
  are retail's.

## The data

406 directory entries to the demo's 223. The retail disc lays three files
down twice, one hash at two places: `GLOBAL\HUDTEX.BIN`,
`CARS\TEXTURES.BIN` and index 18/225. `tools/zdir_names.py --retail` names
369 of the 406 into `docs/zdir_names_retail.txt`, using the demo's names
and ELF as well. The 37 left are replays, the AVI movies, a 192 MB
`InGame` stream, and a 6 MB block that opens with a "Guest" profile
record.

- **Tracks**: five locations of six, `TRACKB11`-`TRACKB66` (no 5x),
  with their `TEX<nn>LOCATION` and `TEX<nn>TRACK` packs. Most tracks are
  only on the disc as `.LZC`. The port has a C decompressor in `lzc.c`.
- **Cars**: 95 entries under `CARS\`.

`tools/zdir_extract.py --retail --only GLOB` extracts into
`extracted-retail/`, which is ignored. With `--decompress`, a track's
`TRACKB<nn>.LZC` is written out expanded as its `TRACKB<nn>.BUN`. The game
always loads `TRACKS\TRACKB%d.LZC` and names it `.BUN` once expanded
(BeginGameFlowLoadingTrackSpecific, retail 0x001690a0). The port ships the
tracks already expanded: a 9 MB track never needs its 5 MB compressed copy
beside it on a tight heap, and loading is faster. The disc is 3 GB and the tree is
under OneDrive, so take what a check needs:

```bash
python tools/zdir_extract.py --retail --decompress --only 'GLOBAL\*' --only 'FRONTEND\FRONTB.BUN' --only 'TRACKS\*12*' --only 'CARS\*\GEOMETRY.*' --only 'LANGUAGES\*'
```

`extracted/` stays the demo's, because the checkers run the demo image
against it. They run the retail image against `extracted-retail/`.

### The formats, TRACKB12 and the bundles

The chunk ids are the demo's, with these differences (`bchunk_dump.py
--stats`):

Counts are retail's first, then the demo's.

- TRACKB12: HeliSheet (`0x34800`) is a container now, `0x80034800` with
  `0x34801` and `0x34802` in it. `0x36001` and `0x36002` are gone. 6,659
  chunks, 7,076.
- GLOBALB.BUN: no SolidList (`0x80034000`), and more textures: 64
  `0x10212`, 40.
- FRONTB.BUN: 17 solids, 16. Two EventTrees, four. 1,015 `0x10210`,
  875.

A loader that the retail image changed will show in the audit, as
`Loader...` rows.

What the port has taken on so far:

- **TrackInfo** is 164 bytes, the demo's 160. Retail put an int32
  `SignpostGracePeriod` at 128 before `SoundRegion`, now at 132. See
  `formats/topology.md`.
- **The LoaderTable** has 30 slots, the demo's 31 less PhysPredict (slot
  20). Retail has no `0x34700` chunk. HeliSheet's guard takes the container
  `0x80034800`. See `formats/loader-table.md`.
- **The sun chunk** `0x34202` is 256 bytes in retail's TRACKB12, 244 in
  the demo's. The record is the same 244 bytes, behind 12 bytes of
  alignment that the loader skips. Retail's LoaderSun also fills a fixed
  244-byte glare record at 0x002ef4c0 for StuffSunGlare. That belongs to
  the sun's retail pass, with StuffSun (0.49), StuffSunGlare (0.66) and
  SunTrackLoader (0.85).
- **DifficultyInfo** (`0x34b00`) grew from 744 bytes to 992: retail's
  LoaderDifficultyInfo copies 992. Not yet taken on.
