# The retail build

`PS2 Files/Full Game/` is the PAL retail disc: `SLES_507.31`, built in
August 2002, with `ZDIR.BIN`, `ZZDATA.BIN` and the IOP modules. Everything
before it was ported from `PS2 Files/NFSHP2.ELF`, the June 2002 demo disc.
This file says what differs and how the tools bridge it.

## The ELF

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
demo bodies 9669: same 6980, changed 2353, unplaced 336
retail .text covered: 391458 of 431681 words (90.7%)
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
`extracted-retail/`, which is ignored. The disc is 3 GB and the tree is
under OneDrive, so take what a check needs:

```bash
python tools/zdir_extract.py --retail --decompress --only 'GLOBAL\*' --only 'FRONTEND\FRONTB.BUN' --only 'TRACKS\*12*' --only 'CARS\*\GEOMETRY.*' --only 'LANGUAGES\*'
```

`extracted/` stays the demo's, because the checkers run the demo image
against it.

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
