# HANDOFF

Session-by-session engineering log. Read this before starting work; update it
at the end of every session. Convention borrowed from NFSU2-3DS.

---

## Session 1 (2026-09-18) -- Project scaffolding, RE survey

**Goal:** turn the empty `NFSHP2-3DS` skeleton (just `PS2 Files/` + empty
`3DS Files/`) into a buildable devkitARM project, and figure out exactly what
we're working with on the PS2 side before committing to an RE approach.

### Key finding: this is NOT the NFSU2-3DS situation

NFSU2-3DS had no usable PS2 symbols and had to cross-reference an unrelated
GameCube debug ELF against a stripped PC binary to recover names ("Rosetta
Stone" approach, see that project's own HANDOFF.md).

`PS2 Files/NFSHP2.ELF` is different: it is **not stripped**.
- `.symtab`: 8,333 real `FUNC` symbols, GNU C++ v2 mangled (e.g.
  `AddRacingCar__FP...`), grouped by original object file via
  `NFSHP2.MAP` (`Main.obj`, `Camera.obj`, `EcstasyE.obj`, `Sound.obj`,
  `TrackRoute.obj`, `SEDWedge.obj`, `AnimatedDriver.obj`, ...).
- `.stab`/`.stabstr`: present but **small** (1,691 entries, ~20KB) -- turned
  out to be mostly `SLINE`/`SO`/`SOL` entries for VU0/VU1 microcode assembly
  source (`.vsm` files like `ecstasyu0Cap.vsm`), not general C++ type info.
  Dumped with `tools/stabs_dump.py`; output at `docs/stabs_dump.txt`.
- `.mdebug`: ~24.9MB (`0x17ce66c` bytes) -- this is almost certainly where
  the *real* struct/class layout and function-signature debug info actually
  lives. It's **MIPS ECOFF symbolic debug info** ("stabs-in-mdebug" is the
  SN Systems/SGI-toolchain convention for MIPS: local symbols use stab-style
  strings but are stored inside the ECOFF symbolic header's tables, not in a
  separate `.stab` section). The `readelf -p`/`strings` output showing full
  struct layouts (e.g. `DataEventSelectScreen:Tt1267=s16SelectedTreeType:...`)
  came from **this** section, not `.stab`.
- **This machine has no MIPS-aware binutils/gdb yet** (checked for
  `mips*-gdb`, `ee-gdb`, `ps2dev` -- none installed). Reading `.mdebug`
  properly needs one of: a `ps2dev`/`ee-gcc` toolchain install (its
  `ee-objdump`/`ee-gdb` understand ECOFF debug), a generic
  `mips64-elf-gdb`/`mips-linux-gnu-gdb` pointed at the ELF, or a
  hand-written ECOFF `HDRR`/`FDR`/`SYMR`/aux-table parser (bigger lift,
  only worth it if no working GDB can be found).
- **Next session should start here**: install/locate a MIPS-capable GDB or
  ps2dev toolchain, load `NFSHP2.ELF`, and confirm `ptype`/`info functions`
  surfaces the rich struct data before writing any custom ECOFF parser.

This engine is **bWare** (Black Box Games' in-house engine), confirmed via
`.MAP` library names (`bware/lib/libbware.a`, `bsound/lib/psx2/libbsndm.a`,
`bWare/devsys/psx2/ee/lib/libgraph.a`) and widespread `b`-prefixed symbol
names (`bVector`, `bQuaternion`, `bSlotPool`, `bDriverPS2`, etc). This is a
**different engine from NFSU2's**, so none of NFSU2-3DS's game-logic files
(`carsim.c`, `world.c`, `cardb.c`, `fng.c`, `texpack.c`, `model3d.c`, etc.)
are directly reusable -- only its **3DS-platform skeleton** is.

### What was done

1. `git init` + `.gitignore` (excludes `PS2 Files/` -- 300MB+ dump, not
   distributable -- and build artifacts).
2. Copied the reusable, engine-agnostic parts of NFSU2-3DS's 3DS-side
   project into `3DS Files/`:
   - `Makefile` (renamed `TARGET`/`APP_TITLE`/etc. for HP2)
   - `meta/app.rsf` (renamed `Title`/`ProductCode`/`UniqueId` -- kept every
     New3DS/memory/DSP ExHeader setting identical: `SystemMode: 96MB`,
     `SystemModeExt: 178MB`, `CpuSpeed: 804MHz`, `EnableL2Cache: true`,
     `CanAccessCore2: true`, the DSP `IORegisterMapping`, `StackSize: 0x40000`)
   - `source/heapcfg.c/.h` (Old/New3DS heap-split logic, verbatim except
     `NFSU2_HEAPCFG_H` -> `NFSHP2_HEAPCFG_H`, `NfsuHeapInfo` -> `NfsHeapInfo`)
   - `source/vp6/` (entire FFmpeg-derived VP6 decoder + EA SCHl demuxer +
     GPU-upload display layer, verbatim)
   - `source/jdlz.c/.h` (EA Blackbox JDLZ decompressor, verbatim -- **not
     yet confirmed HP2 uses JDLZ**; check `.symtab`/`.MAP` for
     `jdlz`/`JDLZ`-named symbols before relying on it in Phase 1)
   - `tools/3ds-bin/{makerom,bannertool}.exe`, `tools/bin/dspenc.exe` +
     `vgmstream/`, `tools/src/dspenc.c`, `tools/build_cia.ps1` (renamed
     paths/output name for HP2)
3. Wrote a placeholder `source/main.c` (New3DS-check + heap-diagnostic stub,
   no real boot flow yet -- that's Phase 2) just to prove the skeleton
   compiles and links.
4. **Verified the full build works end-to-end**: `NFSHP2-3DS.3dsx`,
   `.smdh`, and `.cia` all built successfully via
   `tools/build_cia.ps1`. Two things had to be fixed to get there:
   - `osGetSystemMode()` doesn't exist in libctru -- replaced with
     `APT_CheckNew3DS()` in the stub (that's the correct call anyway;
     it was a stub-writing mistake, not a skeleton problem).
   - **Environment gotcha, confirmed present on THIS machine and equally on
     NFSU2-3DS itself**: invoking `make` from a plain Git-Bash/PowerShell
     shell with `DEVKITARM`/`DEVKITPRO` exported manually silently produces
     an empty `$(INCLUDE)` inside the recursive `make -C build` step (all
     `-I...` flags vanish, so even `<3ds.h>` fails to resolve), even though
     the top-level `ifeq ($(strip $(DEVKITARM)),)` check passes. This is
     **not new** -- it reproduces identically against NFSU2-3DS's own
     Makefile in this environment. The only combination that works is
     `tools/build_cia.ps1`'s approach: `subst` a space-free drive letter,
     then run `make` through **devkitPro's own `msys2\usr\bin\bash.exe -l`**
     (its login profile sets `DEVKITARM`/`DEVKITPRO`/`PATH` correctly) --
     do not invoke devkitPro's `make.exe` from a different shell and expect
     manually-exported env vars to survive the recursive `$(MAKE) -C build`
     hop.
5. Wrote `tools/stabs_dump.py` (parses `.stab`/`.stabstr` into readable
   text, handling the per-compilation-unit string-offset-base reset that
   real STABS use). Confirmed working, but see the `.mdebug` finding above
   for why its output is small/limited right now.

### Next session

1. Get a MIPS-capable GDB or ps2dev toolchain installed; read `.mdebug` for
   real struct/class layouts (see finding above). This blocks meaningful
   Phase 1/2 RE work.
2. Set up the Ghidra project importing `NFSHP2.ELF` (MIPS R3000/R5900);
   check whether a community PS2 EE Ghidra processor extension is needed for
   MMI/VU-adjacent instructions, or if stock MIPS analysis is good enough
   for the mostly-scalar bWare game-logic code.
3. Start Phase 1: reverse-engineer `ZDIR.BIN`'s directory format (2,676
   bytes) as the index into `ZZDATA.BIN` (273MB). Look at what pulls in
   `bFile.obj`/`bFileE.obj`/`QueuedFile.obj` in the `.MAP` as the starting
   point for the loader code to decompile.

---

## Session 2 (2026-09-18 cont'd) -- `.mdebug` cracked without a MIPS toolchain

**Goal:** unblock task 1 above (real struct/class layouts) without needing
to source/install a MIPS-aware GDB or ps2dev toolchain, since installing an
external binary would need explicit user sign-off first and a hand-rolled
binary ECOFF (`HDRR`/`FDR`/`SYMR`) parser risks subtly wrong offsets that
would poison every struct layout downstream.

**Shortcut found:** ECOFF's local string pool -- where `.mdebug` stores
every symbol/type *name* -- uses the exact same plain-ASCII a.out/GDB stab
string grammar as a conventional `.stabstr` section (this is what plain
`strings NFSHP2.ELF` was already showing back in Session 1, e.g.
`DataEventSelectScreen:Tt1267=s16SelectedTreeType:1,0,32;...`). So instead
of parsing ECOFF's binary record tables, `tools/mdebug_stabs_scan.py`
regex-scans `.mdebug`'s raw bytes for stab-shaped strings and decodes the
`name:T?t?<typenum>=s<size><fields>;<methods>;` struct/class grammar
directly out of the text. No MIPS toolchain needed at all.

**Result:** 68,317 unique stab-like strings harvested
(`docs/mdebug_raw_strings.txt`), **1,432 struct/class definitions fully
decoded** with exact size + every field's type#/byte-offset/bit-size
(`docs/mdebug_structs.txt`). Method (C++ member function) entries are left
as raw undecoded text -- full mangled-signature decoding is a much bigger
chunk of GDB's `stabsread.c` for comparatively low payoff versus the field
layouts. See `docs/formats/mdebug-stabs.md` for the grammar reference and
tool usage.

Spot-checked coverage against every phase's named systems in `TASKS.md`:
confirmed present with real field layouts --
`Car`/`CarState`/`CarController`/`CarDamage`/`CarDriver` (Phase 4 physics),
`AICarController`/`AIDriver`/`AIAction*` (Phase 4 AI),
`tCop`/`tAICop`/`tCopManager`/`tPursuit`/`tRoadBlock`/`tSpikeStrip`/
`CopDriver`/`CopMover` (Phase 4 HP2-specific pursuit systems),
`Camera`/`CameraMover`/`DriveCameraMover`/`BumperCameraMover` (Phase 3),
`FrontendDatabase`/`NewMainMenu`/`PauseMenu`/`tHelpMenu`/
`DataEventSelectScreen`/`DataSelectTrackScreen` (Phase 2 frontend).

This means **task 1 above is superseded** -- a MIPS toolchain is no longer
a blocker. `.symtab` (function addresses/names) + `docs/mdebug_structs.txt`
(struct layouts) together cover most of what Ghidra decompilation needs
type-wise; Ghidra is still useful for actual instruction-level decompilation
of function *bodies*, but not for discovering type shapes from scratch.

### Next session

1. Ghidra project import of `NFSHP2.ELF` (MIPS R3000/R5900); check whether a
   community PS2 EE processor extension is needed for MMI/VU-adjacent
   instructions, or stock MIPS analysis suffices for bWare's mostly-scalar
   game-logic code. Cross-reference decompiled accessor functions against
   `docs/mdebug_structs.txt` field offsets to validate the stab-scan output
   is trustworthy before leaning on it heavily.
2. Start Phase 1: reverse-engineer `ZDIR.BIN`'s directory format (2,676
   bytes) as the index into `ZZDATA.BIN` (273MB). Look at what pulls in
   `bFile.obj`/`bFileE.obj`/`QueuedFile.obj` in the `.MAP` as the starting
   point for the loader code to decompile.

---

## Session 3 -- Ghidra set up properly, Phase 1 archive cracked

**Goal:** the two things session 2 left open -- get Ghidra actually
decompiling this ELF, and reverse `ZDIR.BIN`/`ZZDATA.BIN` so asset work can
start. Both done; tasks 6, 8, 9 and 11 are closed and 10 is most of the way.

### The Ghidra language gotcha (this was the whole blocker)

Importing `NFSHP2.ELF` with Ghidra's default `MIPS:LE:32` *appears* to work:
the loader accepts it, analysis runs, 8,333 functions get named from
`.symtab`. But nearly every function then decompiles to a single
`halt_baddata()` with "Control flow encountered bad instruction data".

It is not the EE's MMI/VU instructions and it does **not** need a community
PS2 processor extension. Dumping the raw words at a failing function shows
opcode `0x3f` (`sd`) and SPECIAL funct `0x2d` (`daddu`) in the *prologue* --
ordinary MIPS III. The EE is a 64-bit core and SN's compiler uses
`sd`/`ld`/`daddu` for every register save and register-to-register move, so a
MIPS32 decoder dies on instruction two.

Re-importing as **`MIPS:LE:64:64-32addr` with cspec `o32`** fixes it outright:
of the 12 functions that previously produced nothing, 11 now decompile fully.

    analyzeHeadless <GhidraProjects> NFSHP2 -import NFSHP2.ELF \
        -processor "MIPS:LE:64:64-32addr" -cspec o32 -overwrite

Note `-processor` takes the 4-part language id only; appending the cspec to
it (`...:o32`) is rejected as "Unsupported language". The project now lives in
`Development/GhidraProjects/NFSHP2`, next to the existing NFSU2/LiquidTV
ones, and `tools/ghidra_scripts/DecompileByName.java` batch-decompiles any
list of symbols by name into a file.

### `ZDIR.BIN` / `ZZDATA.BIN`

Full writeup in `docs/formats/zdir-archive.md`. Summary:

* 223 x 12-byte records, `{Hash, Fad, Size}` -- the `DirectoryEntry` struct
  straight out of `docs/mdebug_structs.txt`, which is the first time the
  session-2 stab-scan output has been validated against real data.
* `Fad` is a 2048-byte CD sector index; the highest `Fad * 2048 + Size` across
  all records lands 1,884 bytes short of `ZZDATA.BIN`'s length -- exact,
  modulo trailing sector padding.
* Names are stored only as `bStringHash()` -- djb2 seeded with -1 -- of the
  **uppercased** path. `tools/bhash.py` has the hash plus a
  meet-in-the-middle `crack()` that brute-forces a name back out of a 32-bit
  hash (the hash is linear over the characters, so the middle can be split
  and tabled).

**200 of 223 names recovered** into `docs/zdir_names.txt`. The trick that got
most of them: the assets still carry the authoring-machine path they were
built from (`..\Psx2\CD\CARS\BARCHETTA\DASHGEOM.BIN`), so grepping the
payloads and hash-checking everything after `\CD\` names them for free. The
sound banks had to be brute-forced -- `SOUND\ALPINE`, `DESERT`, `GREECE`,
`PARKLAND`, `TROPICS`, and 23 `SOUND\NEWE<car>.MSB`/`.MSH` engine banks.

Still unnamed: 16 `REPLAY\*` attract-mode recordings (5 of them under
`REPLAY\MAY31\`), 5 plain-text marker design notes, and a handful of sound
entries. The directory's alphabetical sort brackets each one between its two
named neighbours, so they are crackable with more CPU if it ever matters.

### Compression -- and a correction to a Phase 0 assumption

**HP2 does not use JDLZ.** There is no `jdlz`/`JDLZ` symbol anywhere in the
ELF or the `.MAP`. `.LZC` files are a `COMP`-magic LZSS container from
`LZCompress.obj`; the format is documented in `docs/formats/zdir-archive.md`
and reimplemented in `tools/lzdecompress.py`, validated byte-exact against
the raw twin of every compressed entry (including the 15 MB
`FRONTEND\FRONTB.BUN`). `3DS Files/source/jdlz.c`, copied over from
NFSU2-3DS, is dead weight and should be replaced by a C port of that script.

**The movies are not VP6 either.** `MOVIES\*.AVI` is a plain RIFF/AVI with
fourcc `MV30` at 512x256 -- EA's MV3 codec, whose decoder (`MV3Codec` +
`Huffman`) is right there in the ELF. So `3DS Files/source/vp6/` does not
apply to HP2 and task 12's video tool needs an MV3 port instead.

### The chunk system

Every asset is a flat `bChunk` stream (`{u32 Type; u32 Size;}`, size excludes
the header, bit 31 of Type = container). `LoadChunks()` is a one-liner over
`LoaderTable` (`0x003081d0`, 31 slots), and each `Loader*()` opens by
rejecting chunks that are not its own type -- so `tools/chunk_loader_table.py`
reads the table out of the ELF's program headers and decodes each guard's
`lui`/`ori` pair to produce the **complete chunk-type -> asset-kind map with
no decompiler involved at all**. Table and walker:
`docs/formats/bchunk.md`, `tools/bchunk_dump.py`.

Things that fell out of it for later phases: `0x80010200` is the "Flailer" UI
system (Phase 2 task 16), `0x00034121` TrackRoutes (Phase 3 task 24),
`0x80034405` Cameras (task 23), `0x00034600` CarInfo and `0x80034500` Cops
(Phase 4).

### What the disc actually holds

`PS2 Files/` is a **demo disc**, which is worth knowing before anyone hunts
for missing content: only track 12 ships, the jukebox is
`JUKEBOXMDEMODISK.JBC`, speech is `DEMODISK*.PCK`. But there are 30 car
models under `CARS\<NAME>\GEOMETRY.BIN` and 23 engine sound banks, so the car
set is close to complete even though the track set is not.
`LANGUAGES\FE_ENGLISH.BIN` already reads far enough to pull menu and event
text (track names: Coastal Parklands, Calypso Coast, Ancient Ruins, Autumn
Crossing, Alpine Trail, Tropical Paradise, National Forest).

### Next session

1. Task 12: the `0xb0300001` GS texture pack is the highest-value next
   format -- it unblocks anything visual. `LoaderTexturePack` at `0x00100830`
   decompiles properly now.
2. Port `tools/lzdecompress.py` to C and drop `source/jdlz.c`.
3. Task 10 leftovers: VU1 geometry `0x00034005`, the `.MSB`/`.MSH` sample
   bank record layout, and `LoaderFlailerChunk` (`0x80010200`) -- the last
   one also opens Phase 2 tasks 14/16, and `FlailerObjectChunk` /
   `FlailerBitmapChunk` / `FlailerTextChunk` / `FlailerMenuItem` are already
   in `docs/mdebug_structs.txt`.
4. Optional: finish the last 23 filenames with a longer `bhash.crack()` run.
