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

---

## Session 4 -- Flailer UI and the string tables

**Goal:** close the last of the session-3 leftovers that blocks Phase 2 --
the `0x80010200` Flailer chunk, which is every menu and HUD screen in the
game. Done, and it pulled the `FE_*.BIN` string tables in with it.

### `0x80010200` -- Flailer

Full writeup in `docs/formats/flailer-ui.md`; reader is
`tools/flailer_dump.py`. Three files carry one project each (`FRONTB.BUN` 39
screens, `INGAMEB.BUN` 29, `GLOBALB.BUN` 8), 76 screens and 2,252 objects
total, all 640x480.

The layout came straight out of `docs/mdebug_structs.txt` -- the on-disc
chunk sizes are literally `sizeof()` (20/40/120) -- and the check that
validates the whole thing is that `FlailerScreenChunk::NumObjects` equals the
parsed child count on **all 76 screens**, with `ObjectType` agreeing with the
chunk id on all 2,252 objects.

Three things were not guessable from the type info and needed the code:

* **`FormatOptions` bit order is not declaration order.** The seven
  `Is*()` predicates are declared Centered, Left, Right, DarkBackground,
  Clipped, Wrapped, FixedWidth, but the bits are `0x01` **right**, `0x02`
  left, `0x04` **centered**. The renderer settles it -- `0x01` subtracts the
  full `GetScaledWidth()` from the pen, `0x04` subtracts half -- and the data
  agrees (median `TopLeftX` 490 / 172 / 365 on a 640-wide screen). Taking
  declaration order on faith would have right-aligned every centred label in
  the game. This was wrong in the first draft of the tool and is fixed.
* **`Visible` on a screen is dead on disc.** `LoaderFlailerChunk` does
  `sh 1,0x1e(screen)` on every screen it links, so they all start
  `FLAILER_SCREEN_INVISIBLE`; the `0x0040` the exporter writes is padding.
  `CallbackHash`/`HelpMenuHash`/`BackgroundHash` are `0xffffffff` (the
  empty-string hash) on all 76 -- never authored, wired up at runtime.
* **`Z` is a layer index, not a sort key.** `AddFlailerStrip` uses it to
  index `FlailerRenderManager::LayerRenderInfoTable[29]`; values on disc run
  0..28, exactly the table size.

Fonts resolve 934/934 and textures 1307/1318, because a font's glyph sheet is
a texture of the same name in the same pack (there is no name string in a
font chunk -- `FindFont` matches `tTTFontHeader::mHashID` at offset 8). Ten
fonts are in use. Screen names resolve only 18/76: those are the ones the
frontend C++ names as literals, the rest exist only in the authoring tool.

### `0x00039000` -- the `FE_*.BIN` string tables

Writeup in `docs/formats/language-table.md`, reader
`tools/language_dump.py`.

This turned out to be mandatory rather than a bonus: **the string baked into
a Flailer text chunk is only the authoring placeholder and is routinely
stale.** When `LanguageID` is set the renderer draws
`GetTranslatedString(LanguageID)` instead. The main menu ships `'Speed'`,
`'Championship'` and `'Mode Select'` where the game draws `'World Racing'`,
`'Hot Pursuit'` and `'Main Menu'` -- so a port built from the chunk strings
alone would have had the wrong text on its very first screen.

The format is a `LanguageDescription` header (again verbatim from
`.mdebug`) plus three arrays that simply follow it; the stored pointers are
dead PS2 addresses. `108 + 8*NumHash + 8*NumID + TextTableSize` accounts for
every one of the eight files exactly, modulo the chunk's rounding to 4.
1,896 IDs, 1,403 distinct strings. Two of the eight "languages" are build
tools: `FE_LONGEST` holds the longest translation of each string for layout
testing, `FE_ID` maps each ID to its own number.

Two gotchas: the last string in the text table is **not** NUL-terminated, so
reads must clamp at `TextTableSize`; and both lookup tables are sorted as
*signed* ints, because `GetString` binary-searches them with `slt`.

### `tools/mipsdis.py`

Each of the last three sessions has rebuilt a throwaway MIPS disassembler in
the scratchpad, so this one is in the repo. MIPS III integer plus the 64-bit
`ld`/`sd`/`daddu` that SN's compiler uses for every register save and move,
the COP1 FPU, branch-likely forms, and `.symtab` names on jump targets. It is
not a Ghidra replacement -- it exists to answer "which bit does this branch
test", which is exactly what settled the `FormatOptions` order above.

One trap it now handles: **`.symtab`'s `st_size` is unreliable in this ELF.**
`RenderFlailerText` records 144 bytes, and it really is a 144-byte wrapper,
but reading past it silently walks into `Render__16FlailerTextChunk` --
which is how the real renderer got mis-attributed at first. `mipsdis` now
defaults to the gap to the next symbol instead.

### Next session

1. **Task 12, PSMT4.** Still the biggest single gap: 944 of the 1,438
   textures in this build are 4-bit and decode wrong, so most of the UI
   Flailer now describes cannot actually be looked at. `docs/formats/
   texture-pack.md` lists what has been ruled out; the likely fix is
   transcribing the GS `blockTable4`/`columnWord4` tables rather than
   deriving them from the 8-bit case.
2. **Task 16, the C side.** The Flailer data format is done, so `source/bui.c`
   can start: load the chunk, resolve hashes, draw layers 0..28 via citro2d.
   The behaviour half (`FlailerMenu`/`FlailerMenuItem`, which never appear on
   disc) still needs the frontend C++ decompiled.
3. Task 10 leftovers: `0x00034005` VU1 geometry, `ENGINE.CTB`/`.LTB`.
4. Optional: `bhash.crack()` the 58 unnamed screens and the 23 unnamed
   `ZDIR` entries -- the screen names use a plain `A-Z0-9_` alphabet, so
   they should be cheap.

---

## Session 5 (2026-09-19) -- PSMT4 cracked; the swizzle is per-texture

**Goal:** task 12's last gap -- the 4-bit texture swizzle, which session 4
left as the biggest single blocker (944 of 1,438 textures in the frontend
build are 4-bit, so most of the UI could not be looked at).

Solved, and the answer moved the ground under the 8-bit case too.

### The finding: swizzling is a property of the texture, not the format

Every previous attempt assumed "PSMT4 data is swizzled, find the permutation".
It is not that simple. `AttachTextureDownloadPacket` builds a native
PSMT8/PSMT4 host-to-local transfer at the real size -- for those the GS does
the swizzling itself and the file holds plain raster data. But
`FillVramWithTextures` (`0x001081f8`) then *rewrites* that packet for any mip
level whose flag byte is set, at `0x0010850c`:

    flag == 0  ->  leave it: native PSM upload, file data is raster
    flag == 1  ->  DPSM = PSMCT32, (width/2, height/2) for 8bpp or
                   (width/2, height/4) for 4bpp, DBW = TBW/2

The flag lives at `0x55`, which turned out to be part of a per-mip array at
`0x52` -- so the long-documented "`0x54` = TBW" is just level 0's entry, and
the real mip count is the `s8` at `0x6e`. A chain of `0x6e + 1` halving levels
accounts for the pixel byte count exactly on all 2,267 textures that own their
pixels, which confirms the array walk.

Then, checking that against `docs/mdebug_structs.txt`, it turned out bWare had
already named all of it for us and the answer had been sitting in the repo
since session 2:

    struct/class TextureImageInfo (size=4 bytes) [type#227]
        TextureBasePointerOffset     u16   offset=0
        TextureBufferWidth           u8    offset=16
        Is32BitSwizzelled            s8    offset=24

with `ImageInfos: ar1;0;6;227,656,224` (seven of them at bit 656 = `0x52`) and
`NumMipMapLevels` at bit 880 = `0x6e`. **`Is32BitSwizzelled`** -- the field
says in so many words that a swizzled texture is swizzled *as a 32-bit image*,
which is the whole finding. Worth remembering for the next format: the
`.mdebug` type info is the first place to look, not the last.

So a flagged texture is a 32-bit image the GS re-reads as PSMT4/PSMT8, and the
right question is not "what is the PSMT4 permutation" but "where does the GS
find texel (x, y) inside that 32-bit image".

### The 4-bit map

In host-image space it falls out of the page/block/column geometry. Pages line
up one-for-one (PSMT4 128x128 <-> PSMCT32 64x32), and the one twist is that a
PSMT4 page's 4x8 block grid is the **transpose** of PSMCT32's 8x4 -- a PSMT4
block's x index picks the host *row*, its y index the host *column*. That
transposition is why nothing derived by analogy from the 8-bit case ever
worked. Inside a block the free bits land as:

    cx0, cx1, cx2 ^ swap -> host x        (swap = cy1 ^ col0, the GS column swap)
    cx3, cx4             -> nibble 1, 2
    cy0                  -> host y
    cy1                  -> nibble 0

i.e. one host 32-bit word holds the texels `(x, x+8, x+16, x+24)` of two rows
two apart. The same derivation with `cx4` dropped reproduces the shipping,
eye-verified 8-bit permutation *exactly*, at every flagged size in the build
including non-power-of-two widths -- that agreement is the reason to trust the
4-bit result, which has no such prior.

Checks, all of them re-run this session:

* `LOGOTRACK*` (4-bit 256x128) now reads "Desert Heat", "Outback", "Alpine
  Trail"; the 4-bit car skin atlases resolve into panels, lights and wheels.
* flat-8x8-tile count over all 200 whole-page flagged 4-bit textures: winner
  0.292, runners-up 0.264 / 0.251. Sharp, unlike neighbour-similarity scoring,
  which session 4 had already found to be a dead end.
* the column swap, which the tile test is blind to, settled separately by
  horizontal continuity per `x % 8`: spread 0.242 with it vs 0.332 without,
  the 8-bit control showing the same signature (0.091 vs 0.121).
* geometry closes on all 809 flagged textures in the archive, no exceptions.

### Consequence: 1,337 textures were being decoded wrong the *other* way

The old converter guessed from the size (`w % 16`, `h % 16`) and so unswizzled
1,337 textures that are plain raster -- DODGE_BADGE, the event flags, the
small maps, every HUD pip. `texture_convert.py` now follows the flag:
`--swizzle auto` (default) unswizzles exactly the flagged ones, `none` and
`all` remain as escape hatches, and `--list` prints the flag and mip count.
2,642 records across the archive; 809 flagged (426 4-bit, 383 8-bit), no
32-bit ones. `CARS/TEXTURES.BIN` converts 772/772 with none skipped.

### Next session

1. **Task 16, the C side.** Nothing in the asset pipeline blocks the frontend
   any more: Flailer describes the screens, the string tables give the text,
   and every texture they reference now decodes. `source/bui.c` can start --
   load the chunk, resolve texture/font hashes, draw layers 0..28 via citro2d.
   The behaviour half (`FlailerMenu`/`FlailerMenuItem`, never on disc) still
   needs the frontend C++ decompiled.
2. **Mip levels.** Only the base level is emitted. The chain is understood now
   (`0x52` array, `0x6e` count) so emitting or discarding it is a small job,
   and the 3DS side will want mips.
3. Task 10 leftovers: `0x00034005` VU1 geometry packets, `ENGINE.CTB`/`.LTB`.
4. The `0xb0300100` TextureAnimPack sibling container (52-byte records,
   scrolling/flipbook animations referencing textures by hash) is still
   undecoded -- cheap now that the texture side is closed.

Housekeeping: the archive extract these sessions have been working from lives
in a session scratchpad, not in the repo. Re-make it with
`python tools/zdir_extract.py --decompress` into the gitignored `extracted/`
before starting asset work. Only 13 files in it carry texture packs:
`CARS\TEXTURES.BIN`, `GLOBAL\{HUDTEX,DRIVTEX,DYNTEX}.BIN`, the three
`*B.BUN` bundles, `FRONTEND\{FRONTB.BUN,TSELECT.BIN}` and
`TRACKS\TEX12*.BIN`.

---

## Session 6 (2026-09-19) -- MV3 video cracked by running the shipped decoder

**Goal:** finish task 12's last conversion tool, `tools/video_extract.py`,
then keep working down the outstanding list.

### First: a real bug in `tools/mipsdis.py`

The variable shifts (`sllv`/`srlv`/`srav` and their 64-bit forms) were falling
through to the generic `rd,rs,rt` printer, but MIPS prints them `rd,rt,rs` --
the shift amount comes **last**. Every shift-heavy function read this session
or the last four had its operands printed swapped. Fixed, along with three
other gaps found while reading the codec: the EE's three-operand
`mult`/`multu` (which also writes `rd`), the whole MMI opcode space
(`0x1c` and its four sub-tables -- `pmulth`, `pcpyld`, `pcpyud`, `pcpyh`,
`pmaxw`, `pmfhi`, `pmflo` and friends), and `lq`/`sq`.

Worth carrying forward: a disassembler bug is silent. Nothing looked wrong
until a shift's operands had to be reasoned about rather than skimmed.

### The approach: stop transcribing, start executing

MV3 is ~5,000 instructions of fixed-point IDCT, MMI-vectorised in the hot
paths. Transcribing that into Python and eyeballing the output is how you get
a decoder that is 95% right and unfalsifiable. So instead:

**`tools/mipsemu.py`** (new) -- a small R5900 interpreter. It loads
`PS2 Files/NFSHP2.ELF` into a flat 32 MB image and calls shipped functions
directly, so the game's own code is the oracle. Only what the asset code
needs is implemented -- MIPS III, the 64-bit loads/stores SN's compiler
emits, the second multiplier (`mult1`/`mfhi1`/`mflo1`), the MMI ops the IDCT
uses, and enough COP1 for the codec's profiling timers. Anything else raises
rather than quietly computing the wrong thing. Library calls are stubbed:
`bMalloc` is a bump allocator, `bMemSet`/`bMemCpy` run natively, tickers
return zero. Arguments go in a0-a3 **then t0-t3**: this ELF is MIPS EABI, not
o32, so the fifth argument is a register and not a stack slot.

Two things had to be discovered the hard way:

* **Static initialisers matter.** The first decode produced an all-zero Y
  plane even though the IDCT was demonstrably running (3,072 block calls).
  `Codec::OffsetClamp` is set *only* by `_GLOBAL_$I$_5Codec$Clamp`, which the
  boot code we never execute is what normally runs. Hence `Emu.run_ctors()`.
  The clamp *table* is a separate problem again -- it is zero in the ELF and
  filled only by `Codec::Codec()`, under a refcount.
* **The output header's `biHeight` sign is load-bearing.** The first correct
  image came out upside down. `DecompressFrameShared` sets `ToImage`'s flags
  bit 0 only when the output `BITMAPINFOHEADER` has a negative `biHeight`,
  and that bit is what reverses the row order. Pass `-height`.

### What MV3 turned out to be

A JPEG-like codec, fully documented now in `docs/formats/mv3-video.md`:
16x16 macroblocks, 4:2:0, six 8x8 blocks each, a 2-bit-per-block DCT type
selecting 0/1/4/64 coefficients, IJG quality scaling over tweaked Annex K
quant tables with an AAN prescale, a Chen-Wang integer IDCT, a fixed prefix
code with a zero-run symbol and a magnitude-class escape, per-macroblock
copy/skip bit-planes driving motion compensation, and BT.601 full-range
YUV->RGBA through a 768-byte clamp table.

**`tools/video_extract.py`** (new) demuxes the AVI, decodes every frame and
writes PNGs plus the soundtrack as a WAV and a `frames.csv`. `--list` prints
the stream and frame tables without touching the emulator.

It costs ~5.5 M emulated instructions and ~17 s per frame. There is exactly
one movie on the disc (`MOVIES\INTRO\EALOGO_EN.AVI`, 512x256, 90 frames,
3.0 s of unsigned 8-bit mono PCM at 65,470 Hz), so ~25 minutes for the lot is
a price worth paying for output that is the PS2's, bit for bit. The keyframe
is a pixel-accurate EA GAMES wordmark and the deltas animate the ring sweep,
with `CopyPreviousFrameBlock` and the `IDCTAdd*` family carrying the motion
and `IDCTZero` dropping from 930 calls on frame 0 to single digits after.

`3DS Files/source/vp6/` is now dead weight the way `jdlz.c` was -- nothing on
this disc is VP6. It is left in place rather than deleted, on the theory that
the Phase 3 intro will most likely be a pre-decoded frame sequence played
through something like that scaffolding.

### Then: the last two texture-pack gaps

**TextureAnimPack (`0xb0300100`)**, which has been "not decoded yet" since
session 3. It is loaded by `LoaderTexturePack` itself, which branches on the
container type. Layouts came straight out of `docs/mdebug_structs.txt` again
(`TextureAnim` 52 bytes, `TextureAnimEntry` 16, `TextureAnimPack` 24,
`TextureAnimPackHeader` 16) and were confirmed against the loader,
`InitAnims` and `UpdateTextureAnimations`.

The entry table is one flat run with nothing marking the boundaries -- the
constructor implies the split by advancing `NumFrames * 16` per animation.
And the play mechanism is neat: rather than rebinding anything, the runtime
**rotates the frames' pixel and CLUT pointers** (`TextureInfo` `0x90`/`0x94`)
among their own records, so any geometry referencing any frame animates.

Only two of the thirteen packs on the disc are non-empty: three animations in
`GLOBAL\INGAMEB.BUN` (`BULB`, `SMOKE`, `TRACK_BARRIER_NEON`) and five in
`TRACKS\TEX12LOCATION.BIN` (`WATERC` at 15 frames, `HELI_ROTOR`,
`D_LIGHTTUNNELLIGHT`, `W_TUNNELREFLECT`, `D_BARRIERLIGHTFLASH`). All 46
frame hashes resolve to textures in the same file, and the names confirm the
reading -- `WATERC` then `WATERC001`..`WATERC014`.

**Mip levels.** The chain is stored base-first and tightly packed, each level
halving both dimensions; the sum reproduces the record's own `0x38` byte
count exactly on all 1,755 textures that own their pixels, at every level
count from 1 to 7. `--mips` writes them as `<name>.mip<N>.png`.

Two traps found here:

* Each level has its **own** `Is32BitSwizzelled`, and they differ within one
  chain -- `BEAVER_SIGN` is flagged at the base and raster below it. Levels
  have to be decoded one at a time.
* `TextureImageInfo.TextureBasePointerOffset` looks like a file offset and is
  not -- it is the level's GS address in 256-byte blocks, obeying page
  alignment, and it disagrees with the file layout on 191 of the 265
  mipmapped textures. It happens to match on `BEAVER_SIGN`, which is how it
  nearly became a wrong "confirmation".

A caution on verifying sub-levels: they render as coherent, legible smaller
copies of the base, but they are **not** pixel-exact box downsamples, because
the art is dithered 16-colour and each level was quantised on its own. Time
was lost chasing an apparent half-image rotation in `BEAVER_SIGN`'s level 1
that turned out to be an artefact of eyeballing two small dithered renders;
scoring the candidate shifts put them all within noise of each other.
Regression check: `CARS\TEXTURES.BIN` still converts 772/772 with none
skipped.

### Next session

1. **Task 16, the C side.** Unchanged and now the only thing left before the
   frontend can start: `source/bui.c` -- load the Flailer chunk, resolve
   texture/font hashes, draw layers 0..28 via citro2d. The behaviour half
   (`FlailerMenu`/`FlailerMenuItem`, never on disc) still needs the frontend
   C++ decompiled.
2. **Task 13**, asset delivery: SD-card game directory vs ROMFS. Cheap to
   settle and it gates the Phase 3 packaging work.
3. **The intro.** Decide between a C MV3 decoder and pre-decoding to a frame
   sequence at build time. `tools/video_extract.py` already emits exactly the
   sequence the second option needs, and for one three-second movie that
   looks like the right answer.
4. Optional: `bhash.crack()` the 58 unnamed screens and the 23 unnamed `ZDIR`
   entries -- plain `A-Z0-9_` alphabet, so cheap.

`tools/mipsemu.py` is worth reaching for again. Anything left in the ELF that
is dense arithmetic -- and the frontend behaviour code may well qualify --
can be answered by calling it rather than by reading it.

## Session 7 (2026-09-19) -- the frontend on screen

The port stopped being a set of Python tools and started drawing the game.
Four format readers are now in the 3DS build, a citro2d renderer draws real
Flailer screens from real bundles, and two engine behaviours that had been
guessed wrong were found and fixed.

### New in `3DS Files/source/`

| file | what it is |
|------|------------|
| `bchunk.[ch]` | the container walker, plus `bchunk_hash` (`bStringHash`) |
| `texpack.[ch]` | `0xb0300001` -- `TextureInfo`, CLUTs, both GS swizzles |
| `bfont.[ch]` | `0x00015010` -- `tTTFontHeader`, glyphs, kerning |
| `langtab.[ch]` | `0x00039000` -- the `FE_*.BIN` string tables |
| `bui.[ch]` | `0x80010200` -- the Flailer project/screen/object tree |
| `uirender.[ch]` | draws a `BUIScreen` through citro2d |
| `gamedata.[ch]` | where the disc lives on the SD card (task 13) |

`main.c` is now a screen viewer: it loads `FRONTB.BUN`, `GLOBALB.BUN`,
`INGAMEB.BUN` and a language file off the SD card and pages through all 76
screens, D-pad to change screen, A to cycle the 8 languages.

**Nothing here is trusted on inspection.** Each C module has a host-built
test binary (`tools/src/*_test.c`) driven by a Python checker that diffs it
against the existing reference tool:

| checker | scope | result |
|---------|-------|--------|
| `tools/texpack_check.py` | 397 textures in `FRONTB.BUN` | 0 differ |
| `tools/langtab_check.py` | 15,168 strings, 8 files | 0 differ |
| `tools/bfont_check.py` | 11 fonts, 953 lines | 0 differ |
| `tools/bui_check.py` | 2,331 lines, 3 bundles | 0 differ |

`tools/hostbuild.py` is the shared host compiler those share (with the msys2
login-shell fallback that devkitPro's environment needs on Windows).

### Three bugs that only a picture would have caught

**1. Layer order.** `FlailerObjectChunk::Z` is a layer index -- that part was
already right -- but higher Z is *further back*, and the sweep is not
monotonic. `eDisplayFrame` calls `RenderLayer` from four loops and every one
of them counts down: `24..20` before the world, then `15..0`, then `19..16`,
then `28..25`. The four ranges cover 0..28 exactly once, which is how you
know you have found all of them. Drawn ascending, `NEW_MAIN_MENU`'s 512x384
backgrounds (Z 7..10) bury the title and the menu text (Z 0 and 2), which is
exactly what the first render looked like.

**2. The texture pack data base is 128-byte aligned.** This one was live for
several sessions and quietly corrupted every texture in the project.
`ImagePlacement` and `PalettePlacement` are offsets from the `0x30300004`
payload **rounded up to 128**, not from the payload:

```
001008a8  addiu  s2,v0,143      ; v0 + 8 (the payload) + 135
001008b0  and    s2,s2,a3       ; a3 = -128
```

The packer leaves 0 to 127 bytes of `0x11` filler for it -- 120, 108 and 88
bytes in the three UI bundles. Without the alignment every texture is rolled
sideways by that much, one scanline wrapping into the next. Flat UI sprites
survive that looking nearly right, which is why it lasted: arrows, bars and
swatches all looked fine. Photographs and logos do not, and the first
composited menu was the first time anything photographic was looked at.

Worth noting how it was found, because the method generalises: the failing
textures were dumped as *index maps* (palette index as brightness) instead of
as colour. That separates "the geometry is wrong" from "the palette is
wrong" in one look -- `NFS_LOGO` came out as a clean, legible wordmark split
across the wrap, which says geometry, and therefore offset, immediately.
Several plausible theories (CLUT twiddle, PSMT8 page swizzle, a wrong `TBW`)
had already been tried and rejected against colour renders that could not
distinguish them.

Both `tools/texture_convert.py` and `3DS Files/source/texpack.c` are fixed
and still agree texture for texture.

**3. PSMT8 CLUTs are in GS CSM1 order.** Found by doing item 4 of this
session's own next-session list -- sweeping the ten texture packs on the disc
now that the alignment was fixed. `FRONTEND/TSELECT.BIN` came out as
recognisable landscape photographs wearing the wrong colours: geometry
perfect, palette scrambled. `GLOBAL/DRIVTEX.BIN`'s driver faces were the
same, with spiky hair and mottled skin.

Inside every group of 32 entries, 8..15 and 16..23 are exchanged -- bit 3
swapped with bit 4. bWare names the permutation itself:

```
--- RemapLinearIntoClut8__FPUiT0 @ 0x00118878 ---
  00118894  lq  t0,32(t2)     ; source entries  8..11
  0011889c  lq  v0,64(t2)     ;         "      16..19
  001188b8  sq  v0,32(t3)     ; 16..19 stored where  8..11 would be
  001188c0  sq  t0,64(t3)     ;  8..11 stored where 16..19 would be
```

eight passes of 32 entries, everything else copied straight through. *Linear
into CLUT8* -- the name says which direction. Its callers are all palettes the
engine builds at runtime (`CreateFogPalette`, `BuildYUV2ABGRPalettes`, ...)
and has to convert; a pack CLUT is uploaded raw, so it is already in CLUT8
order and a host decoder has to undo it.

Two checks that do not depend on anyone's eye:

* 173 of the 256-entry CLUTs on the disc have eight or more unused (all-zero)
  entries. Read in CSM1 order those form a clean tail for 54 of them and are
  inconclusive for the rest. Read linearly, **not one** of the 173 has its
  unused entries at the end.
* Decoding every 8-bit texture both ways and measuring the mean colour step
  between adjacent texels -- art is locally smooth -- picks CSM1 order for 559
  of 588, by up to 15x. The 29 that prefer linear are 16x16 arrows, 176x16
  bars and the `MOVIE_*` planes whose disc CLUTs are placeholders: every case
  where the measurement has nothing to measure.

`TUNNELROADSIDEB` is the one that shows it with no statistics at all. It has a
32-entry PSMT8 CLUT holding a grey ramp, and the ramp runs 1..7 then 16..23,
with 9..15 and 24..31 left white. The image uses indices 1..15.

`docs/formats/texture-pack.md` had claimed the opposite, citing
`RemapLinearIntoClut8`'s caller list (right observation, inverted conclusion)
and a render test. That test could not have worked: it predates the 128-byte
fix, and `PalettePlacement` is measured from the same base, so the CLUT being
compared was itself thirty entries out of place. Two wrong readings of a wrong
palette.

Both decoders apply it now, and still agree on all **2,040** textures across
the ten packs. The screens render correctly: the main menu's grid background,
its `NEED FOR SPEED / HOT PURSUIT 2` logo, the track-select photographs, the
car skins and the driver faces all look like the game.

### The texture-pack sweep, finished

Ten files on the disc hold texture packs. Every one needed a non-zero
alignment pad except `TSELECT.BIN`:

| file | pad | what is in it |
|------|-----|---------------|
| `CARS/TEXTURES.BIN` | 60 | 772 -- car skins, lights, shadows |
| `FRONTEND/FRONTB.BUN` | 120 | 397 -- the frontend |
| `FRONTEND/TSELECT.BIN` | 0 | 123 -- track-select photographs |
| `GLOBAL/DRIVTEX.BIN` | 16 | 23 -- driver faces and bodies |
| `GLOBAL/DYNTEX.BIN` | 68 | 18 -- legal screens, controller maps |
| `GLOBAL/GLOBALB.BUN` | 108 | 88 |
| `GLOBAL/HUDTEX.BIN` | 124 | 84 -- per-car speedo/tacho dials |
| `GLOBAL/INGAMEB.BUN` | 88 | 117 |
| `TRACKS/TEX12LOCATION.BIN` | 28 | 396 -- road signs, foliage, boats |
| `TRACKS/TEX12TRACK.BIN` | 52 | 22 -- skydome and track map |

(The `.LZC.raw` files are the same three bundles before archiving, with the
same pads.) All ten now cross-check clean and all ten have been looked at as
contact sheets rather than trusted.

### Engine behaviour recovered for the renderer

* `RenderCharacter` (`0x0013f698`) multiplies glyph **width** by `ScaleX`
  twice (`mul.s` at `0x0013f750` and `0x0013f794`) while height is scaled
  once and the pen advances once. The raw instruction words were decoded by
  hand to rule out a disassembler artifact. It is a shipped bug and the
  screens were laid out with it on screen, so `uirender.c` reproduces it.
* `Font::FixedWidthCell` is not in the font chunk. `Font::Font`
  (`0x0013dd60`) computes it as `GetWidestCharacter(this, "1234567890:- ")`.
* `ColonCrapola` -- a real gp-relative global, and a real name -- would give
  `:` and `.` a proportional advance inside a fixed-width string. It is 0 and
  nothing writes it, so that path is dead.
* Help characters: bytes `0x80`..`0x91` in a string are button icons.
  `RenderHelpCharacter` (`0x0013f9b8`) hashes `"BUTTONSOUT"` and indexes an
  18-byte table at `0x002e8a10`, ignoring the text object's own font.
* `RenderSingleFlailerBitmap` sizes the quad from the `TextureInfo`, not the
  UVs, and truncates to int.
* `bfont.c`'s kerning model was wrong at first: `tTTGlyph::mKerningTable` is
  an **index** into the font's one flat kerning array, not a pointer and not
  a byte offset. Several fonts ship `0xCDCDCDCD` there with a zero pair
  count, so the count has to be checked first.

### Texture orientation, settled with evidence

PICA200 `Tex3DS_SubTexture` wants `top = 1 - y/h` and
`bottom = 1 - (y+h)/h` for an upright texture, because memory row 0 sits at
`v = 1`. Rather than guess, this was taken from `source/vp6/vp6_display.c`,
which is hardware-verified in NFSU2-3DS.

### Menus, which closes Phase 2's data/behaviour split

Task 17. `FlailerMenu`, `FlailerMenuItem` and `FlailerScreen` are in the
type info and ship as no chunk at all, so this was a decompilation job.
`3DS Files/source/bmenu.[ch]` is the result and
`docs/formats/flailer-menu.md` is the write-up, with an address per rule.

**How a menu is built.** There is exactly one construction site in the whole
game -- `Activate__13FlailerScreen+0x3c` (`0x00165c5c`) -- and it passes a
literal `"MENUITEM_%d"` at `0x00295DD0`. The constructor formats that for
`n` in 0..15, hashes it, and asks the screen for a text object of that name.
That is the entire mechanism: a menu is a screen's text objects called
`MENUITEM_0` through `MENUITEM_15`. The loop never breaks early, so gaps are
fine -- `NEW_MAIN_MENU` uses 1, 2 and 3 and skips 0. Running the rule over
the disc finds menus on 46 screens, 29 in `FRONTB.BUN` and 17 in
`INGAMEB.BUN`, from one item to ten.

**Two things a guess gets wrong.** Colours are written *into the loaded
chunk* -- there is no runtime copy, the renderer reads
`FlailerTextChunk::Color` every frame -- and `SetColor__16FlailerTextChunk`
(`0x0013e820`) masks the new value with `0x00ffffff` and keeps the chunk's
existing alpha. Writing the whole word makes every highlighted label opaque.
`bui_set_text_color` reproduces the mask.

**`AlignBar` is dead code, twice over.** `AlignBar__15FlailerMenuItem`
(`0x00164e70`) has zero callers -- `Highlight` does not call it, and the
only references to its address are in the symbol and debug sections. Then
the data side says the same thing independently: **no `HIGHLIGHT_BAR` object
exists anywhere on the disc**, 0 hits across all 2,252 Flailer objects, so
`FlailerMenu::HighlightBar` is NULL on every screen. Screens animate their
own highlight instead; `NewMainMenu` pulses the label through
`tHighlightAnimation`. The geometry is still ported, opt-in, because it is
the only statement in the image of where a bar *should* sit. (It also
contains its own shipped bug: `GetWidth` on the label is called and the
result discarded.)

**The gp globals are never written, so `.data` is the answer.** Nothing in
the image stores to any of them except `SetIgnoreJoystick`, which means the
initialised values are what the game runs with:
`LoopingMenuScrollMode` = 1, so wrapping with disabled items skipped is the
real behaviour and the non-wrapping path is unused;
`HighlightR/G/B` = 128/64/0, the frontend's orange on the GS 0..128 scale;
`GrayedR/G/B` = 24.

**Input is three levels, each handling what it owns.** Screen
(`0x00165dc0`) takes START, L1 and R1; menu (`0x00165820`) takes up/down and
moves the selection *after* the callback gets a chance to consume it by
writing `Param`; item (`0x001651d8`) is a 15-entry jump table on `event-5`
taking left/right, select and square. `MenuJoyEvents` at `0x002f3030` is the
exact list of sixteen events the frontend registers, for ports 0 and 1.

**Checked both ways.** `tools/bmenu_check.py` runs an identical event script
through the C and through a second Python implementation, diffing the whole
transcript -- every callback message, and every item's state and live colour
after every step: 3,234 lines on `FRONTB.BUN` and 1,783 on `INGAMEB.BUN`,
0 differ. That only proves the C matches the notes, so there is also a
picture: `tools/flailer_render.py --menu-item N --gray M` applies the same
recolouring to a composited screen, and `NEW_MAIN_MENU` comes out with the
right entry in the right orange and a grayed entry that reads as disabled.
`main.c` navigates the screen it is showing with the D-pad; the CIA builds
clean.

One tooling fix fell out of this. `tools/mipsdis.py` labelled calls by the
first symbol at an address, and every compilation unit emits a zero-sized
`gcc2_compiled.` marker on its first function -- which is how `bStringHash`
and `bList::GetNode` both showed up as `gcc2_compiled.` inside `FlailerMenu`
and stayed unidentified for a while. It now prefers a named, sized symbol.

### Also

* `tools/flailer_render.py` -- the whole renderer again in pure Python,
  compositing a screen to a PNG (its own zlib PNG writer, nearest-neighbour
  sampling, bilinear corner tint). This is what makes the format
  falsifiable: if a screen does not look like the game, something is wrong.
* `tools/font_dump.py` -- a Python reader for `0x00015010`, the reference
  `bfont.c` is checked against.
* `docs/formats/language-table.md` had the English hash table at 1,403
  entries. It has **1,896**, with 1,403 distinct keys -- 55 hashes are
  ambiguous. Corrected, with a warning.

### Next session

1. ~~Task 17, menu behaviour~~ -- done, see above. What is *not* ported is
   the level above it: `FlailerScreenList` (`0x001675a8`) owns the screen
   stack, `ChangeToScreen` (`0x00167850`), `PopUntil`, the popup and movie
   hooks, and `SCREEN_BACK_BUTTON`. Nothing needs it until screens have to
   lead to other screens, which is task 18.
2. **Tasks 14/15**, the boot/logo sequence -- now the only thing between
   here and the Phase 2 milestone. Same kind of job as task 17 was.
3. **The intro.** Still a choice between a C MV3 decoder and pre-decoding to
   a frame sequence at build time. `tools/video_extract.py` already emits
   exactly what the second option needs, and for one three-second movie that
   still looks like the right answer.
4. ~~Sweep the other texture packs~~ -- done in this session, and it paid
   for itself: see the CSM1 CLUT order above. All ten packs on the disc have
   now been decoded, cross-checked and looked at.
5. Optional: `bhash.crack()` the 58 unnamed screens and the 23 unnamed
   `ZDIR` entries -- plain `A-Z0-9_` alphabet, so cheap.
6. Mip chains were checked too, since the same class of bug could have been
   hiding there: `BEAVER_SIGN` (4bpp, 5 levels) and `LOGTRUCK` (8bpp, 5
   levels, swizzled at 0-1 and raster at 2-4) stay legible all the way down.
   `texpack_check.py` still only diffs level 0 and the 3DS side still only
   uploads level 0, which is fine until something needs them.

The lesson from the alignment bug is worth keeping, and the CLUT order
repeated it within the same session: a cross-check between two
implementations proves they agree, not that they are right. Both had the same
wrong base for weeks, and then the same wrong palette order. Rendering the
thing and looking at it is a different kind of test, and it caught what
several `0 differ` runs could not -- twice. The corollary is the one that
cost the most time here: a conclusion recorded in `docs/` with two
confirmations next to it can still be wrong, and it is worth asking what
*else* was broken when the confirming test was run.

## Session 8 (2026-09-19) -- the boot flow

Task 14. Full writeup, address per rule, in `docs/formats/boot-flow.md`.

**There is no `BootFlowManager`.** The task said to look for one in the
`.mdebug` type info and the answer is that the class does not exist. The boot
sequence is two mechanisms stacked, and neither is named after booting.

**The outer one is a state table.** `GameFlowStateInfoTable` (`0x002f2eb0`) is
10 x `{const char *Name; void (*Begin)(); void (*End)(); void (*Loop)();}` --
`NONE`, `LOADING_FRONTEND`, `UNLOADING_FRONTEND`, `IN_FRONTEND`,
`LOADING_TRACK_COMMON`, `LOADING_TRACK_SPECIFIC`, `RACING`,
`UNLOADING_TRACK_SPECIFIC`, `UNLOADING_TRACK_COMMON`, `EXIT_DEMO_DISC`. This
*is* the `kVideoStages[]` the task list was looking for; it was already the
shape the port wanted.

`main` (`0x0012da88`) is nine lines: initialise, ask for `LOADING_FRONTEND`,
then `bDoWithStack(MainLoop, 0x70004000, 0, 0)` -- the main loop runs on
scratchpad. `MainLoop` calls `ServiceGameFlow` (`0x001636f8`) *twice* a frame,
at `0x0012dc18` and `0x0012dc4c`, once either side of the frame's work.

`ServiceGameFlow` loops until the desired state stops moving:

```c
for (;;) {
    if (Current != Desired) {
        if (Table[Current].End) Table[Current].End();
        Current = Desired;
        if (Table[Current].Begin) Table[Current].Begin();
    }
    if (Table[Current].Loop) Table[Current].Loop();
    if (Current == Desired) return;
}
```

So a state whose `Begin` immediately redirects costs zero frames. That is how
the loading chain runs through several states without a visible hitch, and it
is load-bearing: implement it as one transition per call and the boot stalls.

**The inner one is a stack, filled backwards.** `LaunchFrontendMenus`
(`0x0016aa40`) pushes onto a 388-byte LIFO (`char[12][32]` + index) in the
order `Title Screen`, `Legal MumboJumbo`, `Language Options Pre FE`,
`BootAutoload` -- and then enters the one on *top*. The push list reads
backwards from the boot order, and each push is behind a predicate.

**Four things that a guess gets wrong.**

* `ShouldSeeLegalMumboJumbo` (`0x0016aa28`) is `return 0`. The screen was
  authored and shipped -- `0xdd4197c9` in `FRONTB.BUN`, with its text object
  `0xdd479599` -- and nothing can reach it. The art is on the disc, the road
  to it is not.
* `TheDemoDiscManager` (`0x002e8120`) is a 48-byte object, not a pointer. Its
  ctor clears `bActive` and nothing in the image ever sets it, so every
  demo-disc branch -- including a whole second legal slideshow -- is dead.
* `FlailerScreenVisibility` is `VISIBLE=0 / INVISIBLE=1`, but
  `FlailerObjectVisibility` is `INVISIBLE=0 / VISIBLE=1`. Opposite polarities,
  used one line apart in `TitleScreen::HandleTick`. Reading them the same way
  makes the flow read as "show it, then hide it"; the enum is in
  `docs/mdebug_raw_strings.txt` and settles it.
* **The EA logo cannot be skipped and the NFS intro can.** `HandleEvent`
  (`0x0016a148`) gates the advance on `Mode == 1 || (Mode == 2 && MovieIndex
  != 0)`, so START does nothing during movie 0.

**What actually boots on this disc.** `TitleMoviesToPlay` (`0x002f3770`) is 8
language rows x 2 x `{const char *Name; int Letterboxed}`, but only
`MOVIES\INTRO\EALOGO_EN.AVI` exists -- `NFSINTRO_EN.AVI` is in none of the
223 entries in `docs/zdir_names.txt`. With `FrontendLaunchType` = 1,
`SkipFE` = 0 and `SkipMovies` = 0 as shipped, retail boot is
`BootAutoload` -> (`Language Options` on PAL) -> `Title Screen`, one movie ->
`New Main Menu`.

**Both clocks, since the timeouts need them.** `AdvanceRealTime`
(`0x00199410`): `RealTime` (`0x00323cd4`) is 60 Hz ticks and is forced to
advance by at least 1 each frame; `RealTimer` (`0x00323cd0`) is in 1/4000 s
units, because `Timer::SetTime(float)` (`0x00134ef0`) is `(int)(f * 4000.0f)`
against the constant at `0x003213fc`. Shipped timeouts: `LegalScreenTimeout`
= `AntiPiracyTimeout` = 7.0s, `BeginDemoModeTimeout` = 30.0s,
`DemoModeTimeout` = 120.0s.

### The screen registry had no table to read

`ChangeToScreen` takes a name and `FlailerScreenList::FindScreen` walks a
linked list of `FlailerScreenConfig`. The list is built one `jal` at a time by
`_GLOBAL_$I$*` constructors scattered over a dozen object files -- there is
nothing to dump. `tools/screen_registry.py` walks `.text`, finds every call to
either `FlailerScreenConfig` constructor, and recovers the arguments by
back-propagating from the call site.

Backward, not forward, and that was the whole difficulty. A forward sweep has
to drop every register at a branch and found 32 of 51 sites. Walking back from
the call to the first definition of each argument register survives branches
and found 49. Three fixes got it there: read the delay slot *first* and skip
the `jal` itself (otherwise the scan hits the call and gives up immediately);
let `s0`-`s7`/`s8` scan back past a call, since they survive one; and evaluate
`lw rt, imm(gp)` by reading the initialised word out of the ELF, which is how
the names loaded from `.sdata` resolve. The two remaining sites are the 4-arg
constructor forwarding to the 7-arg one, which register nothing.

49 configs, 49 flailer screens, every hash present in the bundles.

**And the registry answered a question the port was about to get wrong:**
`ScreenName` and `FlailerHashes[0]` are different strings. The flow code says
`"Title Screen"`; the bundle screen is `bhash("TITLE_SCREEN")` = `0xb5761d00`.
`bhash("Title Screen")` = `0x0ae7daa1` is in no bundle. Same for
`New Main Menu` -> `NEW_MAIN_MENU`, and `Language Options Pre FE` ->
`LANGUAGE_OPTIONS`, which also loses its suffix. So there are two namespaces,
the join is `FlailerScreenConfig` and nothing else, and the port has to carry
the same join.

Not mechanical enough to compute, either: `BootAutoload`'s `0xfa2ac5c6`
matches none of `BOOT_AUTOLOAD`, `BOOTAUTOLOAD`, `AUTOLOAD`, and a
`bhash.crack()` over `[A-Z0-9_]` to 8 characters -- plain, and with a
`_1`/`_BG`-style suffix -- finds nothing readable, so its authored name is
longer than that. Doesn't matter; the hash is what the lookup wants. The one
object name that did fall out is the title screen's `0xb070dbc9` =
`PRESS_START_1`, which also shows that Flailer's uniquifying `_1` suffix is
part of the hashed string.

### The port: `gameflow.c`, and the table `main.c` was always missing

Task 15 asked for the `kVideoStages[]`-style table. It is `kBootStages[]` in
`3DS Files/source/main.c`, four entries, name plus predicate, in the order
`LaunchFrontendMenus` pushes them -- which is the *reverse* of the order they
appear in, because the stack is a LIFO and the last push that passes its
predicate is the one entered. `main.c` also holds `kScreens[]` (the
`FlailerScreenConfig` join between the two name namespaces) and
`kGameFlowStages[BGF_NUM_STATES]`.

The machine itself is `gameflow.c` + `gameflow.h`, 1,200 lines, and it has no
`<3ds.h>` in it: everything it does to the outside world -- show a screen,
show an object, swap a texture, open/drive/close a movie, start a load, poll a
save, pick a language, play a sound -- goes through a `BGameFlowHooks` vtable.
That is what lets `tools/src/gameflow_test.c` build it for the host against a
simulated world, and it is the same shape `bui.c` and `bmenu.c` already use.

`tools/bootflow_check.py` is the second implementation, in Python, and the two
agree over 11 scenarios: **3,531 transcript lines, 0 differ**. One thing that
took a while: the Python had to grow a float32 emulation. `RealTime` advances
by `(int)(accum * 60.0f)` with `accum` a C `float`, and a Python double
accumulates a different rounding within about 200 frames, which shows up as an
off-by-one on every timeout afterwards. `f32()` around each step fixes it.

Worth repeating from last session, because it happened again: three of the 11
scenarios were covering nothing. An event injected at frame 0 gets overwritten
by the boot sequence itself before anything reads it, and a "skip" pressed
after the last movie has already ended never reaches the branch that decides
the EA logo cannot be skipped. Both looked like passing tests.

### Rendering the boot screens found what the diff could not

A cross-check proves two implementations agree. It does not prove they are
right, so the four boot screens went through `tools/flailer_render.py`.

`Title Screen` came out **completely black**, with all seven of its objects
authored `VISIBLE`. Three facts together:

* `SPLASH_SCREEN`, the texture on both of its bitmap planes, is 512x256 of
  `00 00 00 fe` -- all 131,072 pixels. It is the movie blit target, not art.
* Those two planes are `MOVIE_PLANE_43` and `MOVIE_PLANE_LB`, at layer 0, and
  layer 0 is the *frontmost* layer of `eDisplayFrame`'s main pass (`15..0`),
  not the backmost. Scaled 1.25x1.88 they cover the screen.
* So they hide `PRESS START` at layer 13 and, at layer 24, `LOADING` (the
  Need for Speed logo) and `TOP_BORDER` (the bar it sits on).

The authored state is the *during a movie* state. `HandleTick` turns it into a
title screen by hiding both planes when the last movie ends -- one line, and
without it the port would boot to a black screen with nothing to grep for.
`bgf_title` already had it, because it is a transcription rather than a guess;
the render is what made it possible to know that.

Two smaller things fell out of the same pass. `BootAutoload` has **zero**
objects, in `FRONTB.BUN` and `INGAMEB.BUN` both -- it exists only to own a
tick while the memory card job runs, which is also why cracking its name found
no object names to help. And `Legal MumboJumbo`'s one object draws `EA_LEGAL`,
which is not in `FRONTB.BUN` or `GLOBALB.BUN` at all but in the `DYNAMIC` pack
in `GLOBAL\DYNTEX.BIN`; decoded it reads "PLACEHOLDER LEGAL SCREEN" in blue on
white, and `ANTIPIRACY` is on the disc nowhere. Retail shipped a placeholder
for a screen that `ShouldSeeLegalMumboJumbo`'s `return 0` made unreachable --
which is the ELF finding confirmed from the other side, by the art.

### Task 18: the milestone, on the emulator

The Phase 2 milestone is accepted, with the sequence trimmed to what the disc
has. Two of the four things the task names never shipped: there are no
publisher logos beyond EA's, and the legal/PSA screens are gated off by a
`return 0` behind placeholder art (both established in Session 8). What the
disc does is BootAutoload -> title screen playing `EALOGO_EN` -> PRESS START
-> main menu, and that is what runs.

The movie problem the last handoff left open was solved by not solving it:
MV3 is decoded **on the host**, by running the shipped PS2 decoder under
`tools/mipsemu.py`, and `tools/movie_bake.py` writes an `.M3V` -- RGB565
already in the PICA200's 8x8 Morton order, a changed-tile bitmap per frame,
and an RLE16 stream whose runs cross tile boundaries. `source/movie.c` is then
a 300-line reader that decodes straight into a `C3D_Tex`. EALOGO_EN is 1.50 MB
for 90 frames, 6.7% of raw, and only 10.0% of tiles change per frame.
`docs/formats/mv3-video.md` has the format; `tools/movie_check.py` diffs the C
against a second Python reader (102 lines, 0 differ) and will write the frames
back out as PNGs to look at.

### Testing in Azahar, and the two things it caught

`tools/run_azahar_test.ps1` boots the `.3dsx`, waits on lines in
`sdmc:/nfshp2_debug.txt`, drives real key presses in with `PostMessage`,
captures the window with `PrintWindow(PW_RENDERFULLCONTENT)` at each step, and
asks the app to leave its main loop (SELECT, then START in the viewer) instead
of killing it, so the texture tally comes out with it. The method is lifted
from NFSU2-3DS, including the three things that took that project several
sessions: pass the `.3dsx` and never the `.cia`, capture with
`PW_RENDERFULLCONTENT` and never BitBlt, and call `SetProcessDPIAware()` first
or the capture is silently cropped to the top-left -- losing the bottom
screen, and looking fine.

Do not bother with `azahar.exe --dump-video`: the long option is parsed as
bundled short ones, and `-d` fails with "FFmpeg could not be loaded".

Both defects this found were invisible to every cross-check in the repo,
because both implementations agreed and both were fine -- the disagreement was
with the GPU and with the ELF.

**The PICA200 will not take a non-power-of-two texture.** `texpack_upload`
refused them, on a comment asserting that every texture in these packs is
already a power of two. Nobody had counted: **292 of FRONTB.BUN's 397 are
not**, nor are `LOADING` (512x184) or `TOP_BORDER` (512x24), which is why the
title screen came up as PRESS START on an empty field. The GS takes any size.
The fix pads the allocation to the next power of two per axis, puts the image
in the top-left, and repeats the edge texel into the pad so `GPU_LINEAR` at
the image boundary blends with a copy of itself -- what `CLAMP_TO_EDGE` used
to do. The quad is sized from `TexInfo`; the UVs divide by `C3D_Tex`'s padded
`width`/`height`. Anything that uploads a texture from now on has to keep
those two sizes apart.

**A menu item's hash has to travel with its message.** `New Main Menu` was
registered with `bgf_plain_screen_callback`, and `menuCallback` in `main.c`
called `bgf_screen_event`, which fills `ItemHash` with the *screen's* hash --
so `NewMainMenu`'s three-way test on the item could never have matched even
once the callback existed. Selecting Hot Pursuit, World Racing or Options all
did nothing; B then dropped to the title screen, which replays the EA logo,
and from the outside that reads as "Options shows the EA logo again".

`NewMainMenu::HandleEvent` (`0x00203768`) is now ported. SELECT is a three-way
test on the item hash and nothing else:

| item | text | at | does |
|---|---|---|---|
| `MENUITEM_1` `0x52e039f3` | Hot Pursuit | `0x00203800` | `CopsOn`(`0x002f3fdc`) = 1, `ChangeToScreen("Cops On Mode Select", 1)` |
| `MENUITEM_2` `0x52e039f4` | World Racing | `0x00203818` | `CopsOn` = 0, `ChangeToScreen("Cops Off Mode Select", 1)` |
| `MENUITEM_3` `0x52e039f5` | Options | `0x00203830` | `ChangeToScreen("Options", 1)` |

The two Mode Selects are one screen either side of a global. None of the three
is in the port's registry, so the flow traces `unregistered <name>` and is
left with no current screen -- which is what `ChangeToScreen` does too, since
it clears `pCurrent` before the lookup. All three push `New Main Menu`, so B
comes back. `bgf_menu_item_event()` is the new entry point that carries the
item hash; the `mainmenu` scenario covers it (12 scenarios, 3,659 lines, 0
differ) and `final` now prints `CopsOn`.

One thing that looks like a bug and is not: **backing out to the title screen
replays the EA logo from the start.** `TitleScreen::Callback` (`0x0016a590`)
`bMalloc`s a new `TitleScreen` on every ACTIVATE and deletes it on
UNACTIVATE; the constructor (`0x0016a1d0`) stores zero to `movieIndex` at
`0x0016a224` and opens movie 0 unconditionally. There is no "already seen it"
flag -- `SkipMovies` (`0x00322fbc`) is read there but never written anywhere
in `.text`. The PS2 does exactly this.

### Next session

Phase 2 is closed. Phase 3 starts at task 19 (`bMath`/`bVector`/
`bQuaternion`/`bMatrix`), but the first thing a player would notice is that
the main menu is a dead end: `Cops On Mode Select`, `Cops Off Mode Select` and
`Options` are all real screens in `FRONTB.BUN` with real `MENUITEM_n` objects,
and registering them is now only a matter of porting each screen's
`HandleEvent` the way `NewMainMenu`'s was. `tools/screen_registry.py` already
knows their name-to-hash pairs.

## Session 9 (2026-09-19/20) -- the main menu leads somewhere

Task 18a. Full writeup, address per rule, in `docs/formats/frontend-screens.md`.

The main menu was a dead end at the end of Session 8: all three of its items
called `ChangeToScreen` with a name the port had never registered. All three
are registered now, and both of the reachable ones are walked by the
acceptance test.

**These screens are code, not data.** `NewMainMenu` was the exception that
made the last session look easy -- most Flailer screens are a C++ class in the
ELF with a `Callback(ScreenMessage, ScreenCallbackData *)`, plus a chunk in
`FRONTB.BUN` holding only their art. The three here are `CopsOnModeSelect`
(`0x00204e10`), `CopsOffModeSelect` (`0x00205a58`) and `tOptionsScreen` on top
of `OptionsScreenBase` (`0x001b8e30`).

**The two name namespaces, and why the registry row is not optional.** A
screen has an authored `ScreenName` -- `"Cops On Mode Select"`, with spaces,
which is what `ChangeToScreen` is called with -- and a chunk whose name hashes
`bhash("COPS_ON_MODE_SELECT")`. Those are different strings and neither can be
derived from the other. `FlailerScreenConfig` is the only place they are
joined: one static row per screen, registered from the object file's
`_GLOBAL_$I$` constructor. `tools/screen_registry.py` recovers all 64 rows.

`gameflow.c` already had the dispatch, so the port is `bscreens.c`: one
`BScreens` holding a small instance per live screen, driven by the messages
the flow forwards. What it reproduces, in the order a player notices it:

* **The blurb.** One text object, `SCROLLING_TEXT` (`0x75980cf0`), retargeted
  at a different `LanguageID` per highlighted item -- `tAnimatedBlurb::NewText`
  (`0x00232ef0`), ported as `bui_set_text_language`. Every screen in
  `FRONTB.BUN` that has a blurb ships the same authoring placeholder in that
  object ("This text will scroll sideways across the screen...") with
  `LanguageID` 0, so if the blurb never fires you are looking at the
  placeholder, not at a missing string. Resolved all of them in
  `FE_ENGLISH.BIN` to check the tables were not off by one: 10014 "Fill your
  ticket quota for big points!" is You're The Cop, 100025 "See who made this
  game." is Credits, 100026 "Select a different language." is Languages.
* **The selection brackets.** `MENUITEM_UNDERSCORE` and `MENUITEM_OVERSCORE`
  moved in Y only to the highlighted item's bitmap bounds, plus two globals:
  `UnderscoreOffset` (`0x00324a1c`) = **-3.0** and `OverscoreOffset`
  (`0x00324a18`) = **+6.0**, the second subtracted. Needed
  `FlailerGetBoundingBox` (`0x00141ed0`), ported as `uirender_object_bounds`.
* **Greying out.** `GrayMenuItem` (`0x001b8a18`) takes a mode; only two of its
  three modes also hide the object, which is why a disabled item is sometimes
  dim and sometimes gone.
* **The exit animations.** A screen does not change on SELECT -- it starts an
  exit animation and changes when that finishes. `tExitScreenAnimation`'s
  duration is `0.05 + n * 0.05` where `n` is the screen's `MENUITEM_n_GROUP`
  count, giving 0.25 s for Cops On, 0.20 s for Cops Off and 0.40 s for
  Options. **Confirmed from the bundle, not the code**: counted the groups
  whose `GroupHash` is `bhash("MENUITEM_i_GROUP")` in each screen -- 4, 3 and
  7. `SplineBaseDuration` and `SplineDeltaDuration` (`0x00324db4`,
  `0x00324db8`) are both 0.05, which is where the two 0.05s come from.
* **`StartQuickRace`** (`0x001a8e08`), all 25 stores into `RaceParameters`,
  with offsets, in the doc.

One behaviour worth remembering because it is not what it looks like:
`JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION` is a **held** button. The Mode
Selects register a handler that does nothing but record whether it is down,
and `StartQuickRace` reads that flag at the moment it runs -- so the port
pushes the state through every frame rather than on an edge.

Cross-checked the usual way. `tools/bscreens_check.py` is an independent
Python model of all three screens (it subclasses `bootflow_check.Flow` and
replaces the registry and the dispatch): **17 scenarios, 974 lines, 0 differ**.

### The ordering bug the emulator found

The walkthrough screenshots showed both brackets still sitting where
`FRONTB.BUN` authored them and the blurb still showing the placeholder, until
the first D-pad press -- then everything worked. **The first
`MENUITEM_HIGHLIGHT` was being dropped.** `gameflow.c` called the
`enterScreen` hook *before* `bgf_send(SCREEN_ACTIVATE)`; `enterScreen` is
where the port builds and activates the `BMenu`, and activating it highlights
an item immediately, so that highlight arrived at a screen instance
`bscreens.c` had not created yet.

There is no `enterScreen` in the original -- it is the port's name for "build
the menu" -- and in the original the menu is built by the screen's own
constructor, which runs on `SCREEN_ACTIVATE`. So the hook belongs after the
message, and now is; `leaveScreen` was already after `SCREEN_UNACTIVATE`.
`bootflow_check.py` got the matching move (still 12 scenarios, 3,659 lines, 0
differ). The same reasoning applied at exit, where `main.c` was calling
`bmenu_unactivate` on the flow's own menu directly and so delivering an
`UNHIGHLIGHT` and a run of `UNACTIVATE`s to a screen that had never been told
it was going away -- it now leaves through `bgf_change_to_screen(NULL)`.

Second regression fixed in passing: the screen *viewer* -- the debug mode that
pages through all 76 screens -- shared `menuCallback` with the live menu, so
browsing it forwarded one screen's `MENUITEM_2` into whichever screen the game
was actually standing on. It has its own callback now.

Acceptance test after both: **PASS -- booted, movie played 90/90 frames,
walked Cops On Mode Select and Options and came back, exited cleanly; 6
bracket moves, 6 blurb changes, 19 textures cached, 0 missing**, 13
screenshots. The two entry screenshots now show the brackets around Quick Race
and Audio with the matching blurb under them.

### Three RE-tool bugs, all of which were hiding data

None of the above would have been right with the tools as they were. All three
were found by a field being *missing* rather than wrong, which is the failure
mode to watch for here.

1. **`tools/screen_registry.py` scanned for `jal` only.** gcc tail-calls the
   last constructor in each `_GLOBAL_$I$` function, so that one is a `j`.
   **13 of the 64 registrations on this disc are that tail call** -- the
   scanner was silently losing the last screen of every object file that
   registers more than one.
2. **`tools/mdebug_stabs_scan.py` did not join split stab strings.** A stab
   string too long for the assembler's line limit is broken across
   consecutive symbol entries, each piece but the last ending in a backslash.
   **10,318 of the 68,317 strings in this `.mdebug` are continuations.** Any
   struct whose definition straddled one came out truncated with no warning:
   `RaceParameters` stopped at `CopStrength` and lost `Boost`,
   `PlayerSettings`, `OpponentStrength` and five more.
3. **The same scanner's field regex required a bare type number.** A member
   whose type is spelled out in place -- an array, usually -- carries the whole
   definition instead, with its own `;` and `,` in it:
   `PlayerStartPosition:1024=ar1;0;1;10,480,16`. Those were all being filed
   under "methods" and dropped. `RaceParameters` lost `PlayerStartPosition`
   and `sObjective` that way, both of which `StartQuickRace` writes. Anchoring
   the offset and size to the *end* of the entry tells the two apart; method
   entries are never at risk because they all use `::`.

`docs/mdebug_structs.txt` is regenerated with all three fixed: +3,483 lines.
`RaceParameters` is complete at 768 bytes, 42 fields.

A fourth, smaller: `tools/mipsdis.py` printed `andi`/`ori`/`xori` immediates
as signed decimal. They are zero-extended, so `ori a1,a1,0xe350` was coming
out as `ori a1,a1,-7344` -- read back as a constant that builds the wrong
address, which is how a menu-item hash table came out 0x40 off once.

### `TextureInfo` finished, and scrolling textures

With the stabs scanner fixed, `TextureInfo`'s own type info came out whole, so
`docs/formats/texture-pack.md` now names **every field in all 164 bytes** in
bWare's own spelling rather than describing half of them by what the code does
with them. The fields that were still blank turned out to include a UV
animation: `ScrollType` at `+0x79`, `ScrollSpeedS`/`ScrollSpeedT` at `+0x7c`
and `+0x80`, `ScrollTimeStep` at `+0x84`, consumed by
`TextureInfo::GetScroll` (`0x00100a60`) -- type 1 is continuous, type 2 steps
in `ScrollTimeStep` quanta, and the result is the fractional part only.
`tools/texture_convert.py --scroll` lists them. There are exactly two in
`FRONTB`: `SCREEN_LINES` (type 2, T -0.015625, step 0.04 -- the scanlines
crawling up the menu background) and `ROADLINES` (type 1, S +0.78125). Nothing
draws them animated yet; that belongs with task 18b.

> **Corrected in Session 16.** "The scanlines crawling up the menu
> background" was a guess and it is wrong twice over. The menu background is
> `GRID_BLUEPRINT1`; both of these hashes occur exactly once in the whole of
> `extracted/`, in their own record, so nothing on the disc draws either. And
> `SCREEN_LINES` could not animate if it did: its alpha pattern repeats every
> four rows and one step moves exactly four rows. See
> `docs/formats/texture-pack.md`.

### Object names cracked, and three that did not

New this session, by hash search: `SCROLLING_TEXT` (`0x75980cf0`),
`SCROLL_TEXT_CLIP` (`0x5e11b599`), `GRID_SHADOW` (`0x67d295ca`) and `GRID`
(`0x00163ce5`). `bStringHash` is djb2 x33 seeded `0xFFFFFFFF` and incremental,
so a constant delta between two hashes means a single varying character, which
is what makes this tractable at all.

**Three resisted**: `0x6eb9985d`, `0x70a404ec`, `0xab671c9a`. A 4,185-word
list and an exhaustive sweep of every string up to 4 characters missed all
three. They are in the doc as unknowns rather than guessed at.

### Next session

Task 18b, the frontend animation layer, is the obvious next thing: everything
in 18a snaps instantly because `tSlideAnimation` / `tSlideInAnimation` /
`tSlideOutAnimation`, `tHighlightAnimation`, `tAnimatedBlurb`'s scroll,
`SelectionSet` / `AnimationGroup` and `SplineSeek` are not ported. The hooks
already fire at the right moments, so it is a layer on top rather than a
rework -- `bscreens.c` keeps deciding *what* moves, the new module decides
*when* it arrives. Time it in the 1/4000 s `RealTimer` (`Timer::SetTime`,
`0x00134ef0`, is `(int)(f * 4000.0f)`); at 60 fps it gains 66 a frame.

Otherwise Phase 3 starts at task 19 (`bMath`/`bVector`/`bQuaternion`/
`bMatrix`), and task 21 -- VU1 geometry to citro3d -- is the one with the
survey work already done, in `docs/formats/solid-geometry.md`.

---

## Session 10 (2026-09-20) -- the menus move

Task 18b, the frontend animation layer. Full writeup, address per rule, in
`docs/formats/frontend-animation.md`. The port is `3DS Files/source/banim.c`
(~700 lines), driven from `bscreens.c` and hooked to the real Flailer in
`main.c`.

Everything in 18a happened instantly because the classes that make it take
time were not ported. They are now: `tCubic1D` + `SplineSeek`
(`0x001d0790`), `AnimationGroup` (`0x00232010` and `0x002320d0`),
`tSlideAnimation` with its three uses (`tSlideInAnimation` `0x00232a48`,
`tSlideOutAnimation` `0x00232958`, `tExitScreenAnimation` `0x00232b50`),
`feAnimAlphaElement` (`0x00231ba8`), `tHighlightAnimation` (`0x00232318`),
`tAnimatedBlurb` (`0x00232c18`) and `SelectionSet` (`0x00169358`).

### The `.mdebug` scanner was hiding the classes it needed

Before any of that: `tools/mdebug_stabs_scan.py` reported `AnimationGroup`
and `tHighlightAnimation` as having **no data members at all**. A 76-byte
class with nothing in it should have been suspicious a session earlier.

The field regex required a bare type number after the colon. A member of a
*class* rather than a struct carries a visibility digit first -- `/0`
private, `/1` protected, `/2` public -- so `ScreenHash:/01,64,32` never
matched and got filed under "methods, raw, not decoded". 3,159 entries in
this `.mdebug` have one. Static data members were being lost the same way:
they have no offset or size, ending in their linker symbol instead
(`HighlightAnimationTime:/014:_19tHighlightAnimation$HighlightAnimationTime`),
which is exactly where the tuning constants live.

Both are fixed and `docs/mdebug_structs.txt` is regenerated. The payoff was
immediate and worth stating, because it is the difference between reading a
layout and guessing one:

```
struct/class AnimationGroup (size=76 bytes)
    ScreenHash   int    +8      GroupHash   int    +12
    MasterHash   int    +16     SavedXPos   int    +20
    SavedYPos    int    +24     Spline      tCubic1D +28

struct/class tHighlightAnimation (size=32 bytes)
    ScreenHash int +0   CurrentMenuItem int +4   AnimationTimer Timer +8
    TextForAnimation int +12   TargetColor int +16
    StartScale float +20   EndScale float +24   Timeout float +28
    6 statics: HighlightAnimationTime StartHighlightScale EndHighlightScale
               StartAlpha EndAlpha HighlightTimeout
```

`SavedXPos`/`SavedYPos` being `int` is not a detail. The constructor reads
them through `FlailerGetTopLeftPosition`'s int overload (`0x00141d28`, which
`cvt.w.s`'s both), and the port had them as floats. Fixed. It changes nothing
visible -- all 2252 objects across the four bundles are authored on whole
pixels, checked -- but the destructor's restore is where it would have shown.

### Group 0 does not mean "the group whose hash is 0"

The one thing in this layer that would have been a real bug. `Animate`
(`0x00232290`) branches on the group field:

```
if (Group == 0) FlailerSetTopLeftPosition(Screen, Master, x, SavedYPos)
else            FlailerSetGroupPosition  (Screen, Group, Master, x, SavedYPos)
```

Zero is the "no group, just move the master" flag. The blurb's own slide uses
the five-argument `AnimationGroup` constructor, which writes 0 there; the menu
rows use the six-argument one, which stores `MENUITEM_n_GROUP`. Reading it as
a hash would have dragged every object whose `GroupHash` happens to be 0
across the screen on every blurb change -- and `NONAME` objects, of which
there are many, are exactly that.

### Three constants deleted, which is the point

`BSCR_EXIT_COPS_ON/OFF/OPTIONS` are gone. Session 9 measured them -- 0.25 s,
0.20 s, 0.40 s -- by counting `MENUITEM_n_GROUP`s in `FRONTB.BUN`, because
there was no animation to ask. `tSlideOutAnimation` gives slot i a duration of
`SplineBaseDuration + i * SplineDeltaDuration` (`0x00324db4`, `0x00324db8`,
both 0.05), so the total is `0.05 * numGroups`, and the harness now prints:

```
exit start Challenge          0.250s
exit start View Event Tree    0.200s
exit start Audio Options      0.400s
```

Same numbers, derived rather than asserted. This is the shape a port should
converge on: a measurement in a header is a placeholder for a mechanism.

### Four things that look like bugs and are kept

* `bSin` is called **twice** per bloom frame -- once for the scale, again
  inside the alpha expression.
* `FlailerGetScale` is called **twice** in `SetCurrentMenuItem`, with the
  scale reset to 1.0 before each.
* `SetupToAnimate`'s first inlined `SetValDesired` writes `state = 2` and the
  next instruction overwrites it with 0.
* `SelectionSet::AddItems` increments `NumItems` for a mask the screen does
  *not* have, leaving a hole so item indices stay aligned.

All four are in the shipped code, all four were confirmed in the
disassembly rather than assumed, and all four are reproduced. The first three
are unobservable except as instruction count; the fourth is load-bearing on a
screen with a gap in its `MENUITEM_n` sequence.

`bSin` itself (`0x00241e98`) is a BAM table walk, not `sinf`: radians x
`10430.37793`, truncated to a 16-bit binary angle, scaled back by
`9.587380191e-05`, range-reduced, five-term Taylor. It **overshoots** -- at
the peak it returns `1.00000358`. That is the number the bloom's scale and
alpha come from, so it is ported rather than called out to libm.

One genuine bug is documented and *not* carried: `ClampSecondDerivative`
(`0x001d01f8`) guards on the second-derivative limit in `$f22` at
`0x001d0818` and then passes the first-derivative limit in `$f20` from the
delay slot at `0x001d0824`. The frontend's only caller passes 0 for both, so
it cannot fire here. `banim.h` records it next to the declaration.

### Wiring

* `gameflow.c`/`.h` now keep `RealTimeElapsed` (`0x00323cdc`) beside
  `RealTimer`. They are separate globals in the original because the spline
  integrator wants the frame delta and everything else wants the total.
* `bscreens.c` owns one `BAnim` and re-slaves it from both at every entry
  point, rather than starting a second clock that could drift.
* `BAnimHooks` has a single `user` pointer but two hooks with a different
  owner: `ChangeToScreen` and the tracing are free functions on a global in
  the original. `bscr_set_anim_hooks` installs the caller's table and then
  overwrites those two slots with its own, which find the instance through a
  file-static -- leaving `user` for the Flailer side.
* `main.c` implements the other sixteen against `bui.c`/`uirender.c`.

Five primitives had to go in underneath, each one an original:

| new | original |
|-----|----------|
| `bui_get_object_alpha` / `bui_set_object_alpha` | `0x0013e098`/`0x0013ea48` (text), `0x0013efa8`/`0x0013ed50` (bitmap corner) |
| `bui_set_object_scale` | the scale half of `ScaleAboutCenter` |
| `bui_set_text_string` | `FlailerPrintf` (`0x00141ae8`) with a bare `"%s"` |
| `bui_next_in_group` | `FindFlailerObjectByGroup` (`0x00141a50`) |
| `uirender_text_extent` | `GetScaledWidth`/`GetScaledHeight` (`0x0013e8b0`, `0x0013e858`) |

Two details from those worth keeping: alpha is the top byte of the colour
word in both object types (`lbu v0,71(a0)` for text, `lbu v0,67(a0+corner*4)`
for a bitmap), a bitmap `SetAlpha` with corner -1 writes all four, and
`GetScaledHeight` truncates the font's line height to an int *before* `ScaleY`
multiplies it.

`ScaleAboutCenter` (`0x0013eb20`) is the one with geometry. It nudges the
anchor by the half-extent the scale change costs so the glyphs grow out of the
middle, and which coordinate moves depends on the justification bits --
`LEFT` moves both, `CENTER` only Y, `RIGHT` moves Y down and X back, untagged
moves neither.

### Three more object names cracked

New tool: `tools/bhash_crack.py`, a meet-in-the-middle preimage search.
`bStringHash` splits as `h(p + q) = h(p) * 33**|q| + H(q)`, so tabulating
every suffix once turns `37**8` into `37**4 + 37**4`. It also says when an
answer means anything: at 32 bits a sweep of N names throws up about
`N / 2**32` false preimages, which is 0.6 expected at six characters and 815
at eight. Six is decisive, seven is eyeballable, past that only a word list
works.

| hash | name |
|------|------|
| `0x70a404ec` | `WHITEOUT_BAR` |
| `0x6eb9985d` | `NONAME` |
| `0x97bf4b25` | `UNDERSCORE_GROUP` |

Honest about the method: `NONAME` and `WHITEOUT_BAR` both fell to a guess
about what the object was *for*, once the animation layer made that clear --
not to a bigger sweep. Cracking these is dictionary-bound, not
compute-bound. `0xab671c9a` and `0x1042eac3`, the two bloom text objects, are
still unnamed.

### Checking it

`tools/banim_check.py` is an independent Python model written from the
disassembly, diffed against the C line for line: **23 scenarios, 2219 lines,
0 differ**. `tools/bscreens_check.py` imports it wholesale -- one `Bundle`
class subclassing `banim_check.World` -- so the screens model drives the real
animation model rather than a second copy of it, and comes out at 17
scenarios, 1246 lines, 0 differ. `tools/bootflow_check.py` is unchanged at 12
scenarios, 3659 lines.

Float determinism is the whole difficulty. The Python side rounds to float32
after **every** operation; one unrounded intermediate moves a truncated pixel.
Two constants nearly got written wrong from the decompiler's rendering:
`0.00025f` is *not* `1.0f/4000.0f` (0x3983126f vs 0x3983126e, one ulp), and
`BANIM_GROUP0` was typed from memory as `0x29dc47a1` before
`bhash("MENUITEM_0_GROUP")` said `0x59c1995e`.

Mutation-tested, because a cross-check that cannot fail proves nothing. Two
first attempts changed nothing -- `4.712388992f` to `4.712389f` and
`6.283185482f` to `6.2831855f` are the same float32. The ones that bite:
Taylor coefficient `2.755731884e-06f` to `e-05f` moves 28 lines, slide stride
`0.05f` to `0.06f` moves 173.

Built and walked on Azahar: **PASS**, 13 screenshots, 19 textures cached, 0
missing, 0 fonts missing, exits cleanly. The menus slide, the blurb whites out
and scrolls, and the brackets and bloom track the current item.

### Things that bit, for the next session

* **Heredocs mangle backslashes.** Four separate failures this session
  writing Python through `<<'PY'`: `\\n` inside the heredoc became a real
  newline and `\\\\` collapsed to `\`. Use the `Write` tool for anything
  large, or `BS = chr(92)` and concatenation.
* **Line endings are per-file and must be preserved.** `gameflow.*` and
  `TASKS.md` are CRLF; `bscreens.*`, `banim.*`, `bui.*`, `main.c`,
  `uirender.*`, `tools/*.py`, `tools/src/*.c` and the docs are LF. A patch
  script should detect and restore, not assume.
* **gcc argument evaluation order is right-to-left here.** A harness line
  that called `banim_exit_message(...)` inside a `printf` alongside the
  out-params it writes printed stale values. Hoist the call.
* **gcc from Git Bash cannot find its own `/usr/include`.** Always build host
  harnesses through `tools/hostbuild.py`, which retries via the msys2 login
  shell.

### Next session

Phase 2 is done: the frontend boots, plays the logo, reaches the main menu,
walks into all three screens it leads to, and now animates doing it. Phase 3
starts at task 19 (`bMath`/`bVector`/`bQuaternion`/`bMatrix`). `banim_bsin`
is `bMath.obj`'s `bSin` and should move out into a `bmath.c` when that lands
rather than being duplicated; `tCubic1D` and `SplineSeek` should not -- the
map puts them in `Point.obj`, which is game code, not bware. Task 21, VU1
geometry to citro3d, is the one with the survey work already done, in
`docs/formats/solid-geometry.md`.

The two scrolling textures found in Session 9 (`SCREEN_LINES`, `ROADLINES`,
via `TextureInfo::GetScroll` at `0x00100a60`) are still not animated. They
were filed under 18b but belong to the renderer, not the animation layer:
`uirender.c` would offset the UVs, and nothing in `banim.c` touches them.

---

## Session 11 (2026-09-20) -- reading the math library

A short session and an honest one: **no code was written.** Phase 3 opens at
task 19, the bware math library, and the whole session went into disassembling
it. The output is `docs/formats/bmath.md`, which is the decode of 67 of its 73
functions with an address for every rule. Task 19 is `[~]`, not `[x]`.

Four contiguous objects, 10.3 KB of `.text`, sitting between the slot-pool
allocator and the network stubs:

| object | range | functions | decoded |
|--------|-------|-----------|---------|
| `bVector.obj` | `0x00240198`-`0x002411f0` | 38 | all |
| `bQuaternion.obj` | `0x002411f0`-`0x00241bc8` | 9 | 3 |
| `bMath.obj` | `0x00241bc8`-`0x002424f8` | 19 | all |
| `bMatrix.obj` | `0x002424f8`-`0x00242890` | 7 | all |

`bVector` has no out-of-line member functions at all -- the class is inline in
its header, and the object holds only free functions. That is worth knowing
before going looking for `bVector3::Normalize`.

### The tables are the interesting part

Four data tables have to cross with the code, and three of them turned out to
be reconstructible, which is the difference between porting a magic blob and
porting a decision.

`bFixATanTableLow` (`0x00315d30`) and `bFixATanTableHigh` (`0x00315e38`),
129 `u16` each, both reproduce **exactly** as

```python
(int)(math.atan(i / 32.0) * 10430.3779296875)     # Low
(int)(math.atan(i /  4.0) * 10430.3779296875)     # High
```

-- double `atan`, truncated, times the *float32-rounded* radians-to-BAM
constant. Getting that last part right took one entry. `atan(1.0)` lands
exactly on 8192 BAM; both tables store **8191** there (`lo[32]`, `hi[4]`). With
the exact ratio `32768/pi` that entry rounds up and the model mismatches by
one; with `10430.3779296875` it truncates down and all 258 entries match. A
single off-by-one, and it is the only entry in either table that can tell the
two constants apart.

`bASinTable` (`0x003152a0`) is a 192-entry piecewise-linear table over twelve
octaves of sixteen buckets, `{u16 angle; u16 pad; float slope}`, where the
slope is in *turns* per unit x so the code's trailing `* 65536.0f` converts to
BAM. The octave search in `bASin` is not a binary search despite looking like
one: it only ever adds, walking `0x8000, 0xC000, 0xE000, ...` while it stays
below the input, and the final add is backed out on the way out of the loop.
Reimplemented in Python and swept against `math.asin` over 20,001 samples:
max error **1.93 BAM = 0.0106 degrees**. That is the evidence the decode is
right.

`bSinTable` (`0x00315928`, 513 `s16`) is the one that did **not** fall. It is
obviously `sin` scaled to 32767 -- peak at index 128, trough at 384 -- but the
residual against `round(sin(2*pi*i/512) * 32767)` drifts 0 -> +3 at i=256 ->
-6 at i=511 before being forced back to 0. A two-parameter fit lands on
amplitude 32767 and an angular step 31 ppm short of `2*pi/512`, which
reproduces every entry to within 1 LSB, but no plausible constant produces
that step, and the game's own overshooting `bSin` does not generate it either
(395 of 513 entries differ). Tried and rejected: `sin*32768` clamped, truncate
instead of round, float32 accumulation of the angle, the BAM round-trip
`i*128/10430.37793`. **Embed the 513 shipped values.** It is 1 KB and it is
correct; a model that is right to 1 LSB is still wrong.

### Two quirks that will matter when this is ported

`bNormalize` has three degenerate cases and they disagree with each other.
`bNormalize(bVector2*, v)` (`0x00240198`) and
`bNormalize(bVector2*, v, len)` (`0x002401f0`) both write `(1, 0)` on a
zero-length input -- the second one *ignores its own `len` argument* doing so.
`bNormalize(bVector3*, v, len)` (`0x00240250`) writes `(len, 0, 0)`. All three
are in the shipped code and all three should be reproduced.

`bExpandBoundingBox(bVector3*, bVector3*, const bVector3*, float r)`
(`0x00240f80`) builds its radius vector on the stack and writes only
`sp[0..2]`, then loads all sixteen bytes into a VU register. The `w` lane --
`bVector3::pad` -- is fed uninitialised stack and lands in both corners of the
box. Harmless while nothing reads `.pad`, but the port cannot reproduce it and
should not pretend to: operate on x/y/z and say so in a comment.

### `bMulMatrix` multiplies right-to-left

`bMulMatrix(out, m1, m2)` computes `out = m2 * m1`, not `m1 * m2`. The four
VU0 macro-mode words load `vf8..vf11` from the **second** argument and
`vf4..vf7` from the **third**, and the `vmulax/vmadday/vmaddaz/vmaddw` chain
makes each row of the third argument a row-vector through the matrix in the
second.

This is decoded from the instruction encodings, not from a caller, and it is
flagged as such in `docs/formats/bmath.md`. **Verify it against a caller
before writing code against it.** The decode itself is solid -- the COP2 macro
fields are `dest 24..21 / ft 20..16 / fs 15..11 / fd 10..6 / func 5..0`, and
for func `0x3c`-`0x3f` the real opcode is the Special2 entry at
`(fd << 2) | (func & 3)`, which puts `0x4be441bc` on VMULAx and `0x4be45b0b` on
VMADDw -- but argument order is exactly the kind of thing that reads fine and
is backwards.

### Housekeeping

`bSqrt32` (`0x00241c68`) was carried into this session from the last one with a
note saying it "returns root >> 1", which reads like it returns half the root.
It does not: the accumulator holds twice the root throughout, so the shift
gives the root itself. Checked against `math.isqrt` over `0..3999` plus 40,000
random 32-bit values plus the boundaries -- 0 mismatches, it is exactly the
floor integer square root. The note was describing the instruction, not the
function, and the distinction would have put a factor of two into every
fixed-point normalise.

All four cross-checkers still run clean, unchanged from Session 10:

```
banim_check        23 scenarios, 2219 lines, 0 differ
bscreens_check     17 scenarios, 1246 lines, 0 differ
bootflow_check     12 scenarios, 3659 lines, 0 differ
bui_check          FRONTB.BUN     1395 lines, 0 differ
```

### Next session

`CONTINUE.md` has the pick-up-here list. In short: finish the seven
`bQuaternion` functions, then write `bmath.c`/`bvector.c`/`bmatrix.c`/
`bquat.c` with their headers, then `tools/src/bmath_test.c` +
`tools/bmath_check.py`, then mutation-test, then delete `banim_bsin` from
`banim.c` and point it at the real `bSin`.

---

## Session 12 (2026-09-20) -- the math library ported, and two holes in its checker

Task 19 is `[x]`. All 73 functions of the four bware math objects are decoded
and in `3DS Files/source`, held to `docs/formats/bmath.md` by two independent
cross-checkers that were themselves mutation-tested. Session 11 left seven
`bQuaternion` functions undecoded and no code at all; both are now closed.

| file | lines | |
|------|-------|-|
| `bmath.c` / `.h` | 435 / 109 | 19 functions, `bMath.obj` |
| `bmathtab.c` | 324 | the four tables, generated by `tools/gen_bmath_tables.py` |
| `bvector.c` / `.h` | 501 / 180 | 38 functions, `bVector.obj` |
| `bmatrix.c` / `.h` | 147 / 57 | 7 functions, `bMatrix.obj` |
| `bquat.c` / `.h` | 258 / 73 | 9 + 1 initialiser, `bQuaternion.obj` |
| `tools/bmath_check.py` + `tools/src/bmath_test.c` | 761 + 427 | 18 scenarios |
| `tools/bvector_check.py` + `tools/src/bvector_test.c` | 1078 + 1239 | 27 scenarios |

### The VU0 field order, corrected the hard way

`VDIV`/`VSQRT`/`VRSQRT` do not use the `dest` field; bits `24..21` are two
2-bit lane selectors instead. I read them as `fsf` then `ftf` and got
`Q = vf0.x / sqrt(vf1.w)` out of `bNormalize`, which is not a thing anyone
would compute. The correct split is **`ftf` = bits 24..23, `fsf` = bits
22..21**, giving `Q = vf0.w / sqrt(vf1.x)` -- `1.0 / sqrt(sum)`, which is. The
tell was that the wrong reading produces a *plausible-looking* instruction
rather than an invalid one; nothing rejects it except knowing what the
function is for.

### `bQuaternionGetMatrix` and `bQuaternionToMatrix` are not duplicates

Two quaternion-to-matrix routines ship, and it is tempting to call one dead
weight. They compute the same rotation matrix and differ only in the order the
squares are summed:

```
GetMatrix   m00 = 1 - (yy2 + zz2)
ToMatrix    m00 = (1 - yy2) - zz2
```

That is one rounding step in a different place, so the two disagree in the
last float32 bit, and both have callers. The port keeps both. A mutation that
gave `GetMatrix` the other one's grouping produces **54 differing lines** in
the cross-check, which is the evidence that the distinction is real and that
the checker can see it -- had it produced zero, the honest move would have
been to collapse them.

The mirror case went the other way. `bMatrixToQuaternion` (`0x002418c0`) is
the `bQuaternion(const bMatrix4&)` constructor again, instruction for
instruction: same Shepperd branch, same stack layout (matrix staged at `sp+16`
with `m[i][i]` at stride 20, `next[]` at `sp+80`, `q4[]` at `sp+0`). The only
difference is that the `s != 0` test is a plain `c.eq.s` where the constructor
uses the soft-double pair -- same predicate for a float. One static
`shepperd()` serves both.

### A guard that cannot fire, and a guard that is holding the roof up

The `s != 0` test inside Shepperd's else-branch is **dead code**, and it is
worth writing down why rather than leaving it as folklore. `s == 0` requires
`m[i][i] + 1 == m[j][j] + m[k][k]`; `i` indexes the largest diagonal entry, so
that forces `m[i][i] >= 1`, hence `trace = 2*m[i][i] + 1 >= 3 > 0` -- which
would have taken the trace branch above instead. It is ported anyway, because
it is in the original and because a caller with a NaN in the matrix is better
off not dividing. The same argument shows the else-branch radicand is never
negative, which is what makes it safe to feed the cross-check arbitrary
non-rotation matrices.

`bSlerp`'s epsilon is the opposite: it looks like an optimisation and is not.
If `1 - |cos|` is at most 0.05 the routine falls back to a plain lerp; above
that it calls `bASin(|cos|)`. `bASin` indexes `bASinTable` from `x * 65536`
walked down eleven octaves, and an argument above 1 asks for indices in the
thousands against a **209-entry** table. Nothing in `bSlerp` normalises and
nothing checks. The only thing keeping `|cos|` below 1 is that both inputs are
unit quaternions, so **callers must normalise** -- an unnormalised pair does
not get a wrong angle, it reads past the end of the table. Said in `bquat.h`,
`bquat.c`, `bvector_test.c` and `docs/formats/bmath.md`, because this is the
kind of thing that gets debugged twice.

### `bMulMatrix`'s argument order, settled without a caller

Session 11 flagged `out = m2 * m1` as decoded-from-encodings and asked for a
caller to confirm it. It does not need one. The vector overload at
`0x00242770` runs the same four-instruction `vmulax/vmadday/vmaddaz/vmaddw`
chain with a *vector* in the broadcast slot, which can only mean
`out = v.x*row0 + v.y*row1 + v.z*row2 + v.w*row3` -- a row vector on the left.
The matrix-matrix form puts `m2`'s rows in that same slot, so it transforms
each row of `m2` by `m1`, and the arguments multiply right to left. The caveat
is out of `docs/formats/bmath.md`, replaced by that argument.

### Undefined behaviour that the PS2 does not have

The fixed-point half of `bvector.c` adds and subtracts `int32_t` in places
where the EE is plainly relying on wraparound: the absolute-value sums in
`bLengthFix2/3`, the differences in `bDistBetweenFix2/3`, the square sums in
`bNormalizeFix2/3`. The listing at `0x002403c0` is `subu`/`pmaxw`/`addu`, all
of which wrap. In C that is signed overflow, i.e. undefined, and `-O2` on ARM
is entitled to assume it never happens -- which would let it delete the
pre-scale guard that exists precisely to handle large inputs. Spelled out as
`add32`/`sub32` helpers doing the arithmetic through `uint32_t`. Nothing in
the game reaches those magnitudes today; the point is that the compiler does
not know that.

`tools/hostbuild.py` gained `-ffp-contract=off` for the same class of reason.
The host may fuse a multiply and an add into one rounding step; the EE does
not. A checker that let it happen would report a difference that exists only
on this machine.

### The mutation test found two things the cross-check could not see

This is the part worth reading. 23 mutations, all caught -- but two of them
only after the test deck was fixed, and they were caught at zero the first
time round.

**`bNormalize3To`, regrouping the length sum.** `(x*x + y*y) + z*z` against
`x*x + (y*y + z*z)` differed on **0 of 5721 lines**. Probing the deck showed
why: adjacent entries are close enough in magnitude that the two groupings
round identically on 0 of 48 samples. Vectors built from entries a stride of
(10, 14) apart separate them on 8 of 48. Added a `v3m()` selector and a
`normalize3tomix` sweep.

**`bBoundingBoxOverlapping2`, `<` to `<=`.** Also 0 differences. The documented
quirk -- boxes that touch exactly do not count as overlapping -- was never
tested, because no two boxes in the sweep shared an edge. The fix is subtler
than it looks: a "touching at a corner" case would **not** have caught it
either, because a mutation to a single comparison still fails the test on the
other axis. The boxes have to touch on exactly one axis while genuinely
overlapping on the others, so each comparison is exercised at equality on its
own. Added `bbox2edge`/`bbox3edge` doing that one axis at a time, plus points
sitting exactly on the `isInside` epsilon boundary.

Both are the same failure: a passing cross-check proves the model and the code
agree on the inputs it was given, and nothing else. Mutation-testing is what
turns that into a claim about the code.

One tooling bug in the same area: the mutation runner reported `?` for a
mutation that *was* caught, because it read line 1 of the output and the
mutation had left a variable unused, so line 1 was `compiler warnings:`. It
now scans for the line containing `differ`.

### Build notes for this machine

Two workarounds are now baked into the host build, both devkitPro-msys2
specifics rather than anything about this project:

* its cygwin gcc reports every stock include directory as nonexistent (the
  mount table does not resolve under the sandbox), so the build passes
  `-nostdinc` plus explicit `-isystem` paths;
* compiling and linking in one step pulls cygwin's `libcmain.o` and fails with
  `undefined reference to WinMain` even though `nm` shows `T main` in the
  object. Compile each source to a `.o`, then link.

And, again: **heredocs are unreliable here.** New files go through the Write
tool, edits through a Python patch script.

### Where things stand

```
bvector_check      27 scenarios, 5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios, 6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios, 2219 lines, 0 differ
bscreens_check     17 scenarios, 1246 lines, 0 differ
bootflow_check     12 scenarios, 3659 lines, 0 differ
bui_check          FRONTB.BUN     1395 lines, 0 differ
gen_bmath_tables --check           bmathtab.c is up to date
```

`banim.c`'s private `banim_bsin` is gone; it calls `bSinF` now, and
`banim_check` still runs clean across the fold. `tCubic1D` stays in `banim.c`
-- it is `Point.obj`, game code, not bware.

Four things the cross-check deliberately does not cover, all for the same
reason: the EE FPU has no infinities and no NaNs, so feeding it a zero `len`,
a zero quaternion, a singular matrix or a non-unit slerp would compare the
host's IEEE behaviour against hardware that cannot produce it. Listed at the
top of `bvector_test.c` so the gap is a decision and not an oversight.

### Next session

Task 20, `bSlotPool` / `bNewSlotPool` (`0x0023f508`-`0x00240198`), sitting
directly below `bVector.obj` in `.text`, on top of the existing `heapcfg.c`.
`CONTINUE.md` has the pick-up-here list.

---

## Session 13 (2026-09-20) -- the slot-pool allocator, and what a leak looks like

Task 20. `bSlotPool.obj`, `0x0023f508`-`0x00240198`, 3216 bytes, 34 symbols,
all decoded and ported. `3DS Files/source/bslotpool.c` / `.h`, written up
address by address in `docs/formats/bslotpool.md`,
`tools/src/bslotpool_test.c` driving the C and `tools/bslotpool_check.py`
modelling it again in Python from the listing.

```
17 scenarios, 990 lines, 0 differ   (37/37 mutations caught)
```

The shape is three layers: thin `bMalloc`/`bFree`-style forwarders, the
`SlotPool` that does the work, and a `SlotPoolManager` holding every pool on
bWare's intrusive `bTList`. Fixed-size blocks come out of one allocation, a
free list runs through word 0 of every free slot, and a pool that runs dry
grows a second pool chained behind the first.

### An allocator's cross-check has to compare sequences

`Malloc` returning "the third slot" is right or wrong only relative to every
allocate, release, expand and clean-up before it, so nothing here compares a
return value on its own. After every step both sides print the pool chain,
the free list in walk order, the six counters, and -- as of this session --
which arena blocks are still checked out. Three counters disagree with each
other on purpose and the model reproduces all three: `numAllocatedSlots` on
an expansion pool is not maintained during normal use at all (cleanup
reconstructs it at `0x0023f858`/`0x0023f880`), `FlushSlotPool` rebuilds every
free list but leaves the counters alone, and the printed Overflow column is
`TotalNumSlots - NumSlots`, which is only ever non-zero after an expand.

### The mutation test found one real hole

**A `bDeleteSlotPool` that frees the head of an expansion chain and drops the
rest moved 0 of 990 lines.** The transcript named a block's liveness only as
a side effect of printing a pointer into it -- `P2!+0` marks a released block
-- and after a teardown nothing prints one, so a leaked expansion pool was
invisible in a transcript that otherwise reported everything. Both sides now
end every scenario with an `arena:` line stating outright which blocks the
arena handed out and which are still live. The mutation moves 10 lines.

Same lesson as session 12's two: a passing cross-check proves the model and
the code agree on what it was shown, and nothing else. The deck has to be
asked whether it *can* see the failure, not just whether it passes.

Two of the four first-round misses were defective mutations rather than deck
holes, and both looked identical to a real hole at first:

* clobbering only `node.next` in `new_pool` left `node.prev` NULL, so
  `list_remove`'s guard still fired and the mutant behaved exactly like the
  port. The divergence being tested is that *both* links start as garbage.
* dropping the `oldFree` splice in `bExpandSlotPool` left the variable
  unused, so `-Wall` caught it before the checker could. A mutation the
  compiler rejects tests the compiler.

One is a genuine equivalent mutant and is now recorded as such in the
runner's `EQUIVALENT` list, so a later session does not re-add it as a miss:
`bNewSlotPool` tests the manager's sentinel against 1 while
`bDeleteSlotPool` tests it against 0, and since only init and shutdown ever
write that file-static field it is never anything but 0 or 1. The asymmetry
is real in the ROM and unobservable from outside it.

### The mutation runner is kept this time

`tools/bslotpool_mutate.py`, not a scratchpad script. The bvector and bmath
runners were thrown away after use and rebuilding this one from nothing cost
a session; the mutation set is worth more than the run, because it is a list
of every behavioural claim the module makes in a form that fails loudly when
one of them stops being checked. It edits a tracked file in place and
restores it in a `finally`, with a `.mutate-backup` beside the source that a
hard kill leaves behind and the next run refuses to start over.

Six of the 37 are caught by the harness segfaulting rather than by a
transcript difference. That is detection, but weaker: a diff says which
behaviour changed, a crash only says that something did.

### Divergences and hazards

Four deliberate divergences, all stated at the site and listed in the doc:
`ExpandSlotPool` checks its allocation where `0x0023f7c8` dereferences it
unconditionally; `new_pool` clears the `bTNode` links the original leaves as
garbage, which fixes the one case the original supports and then breaks (a
pool created while the sentinel is clear, deleted once it is set); cleanup
keeps a pool whose recount disagrees instead of trapping at `0x0023f9bc`; and
the header size is computed from the host's pointer width, so the module is
right at 8-byte pointers and reduces to the PS2's 48-byte header at 4.

Hazards kept because the ROM has them: `Free` has no NULL check, no ownership
check and no double-free check, so `numAllocatedSlots` can go negative;
`GetSlotNumber` divides *unsigned* (`0x0023f5d4`), so a pointer below the
slot array reads back as 357913939 rather than -2; `FlushSlotPool` on an
expanded pool strands every expanded slot, which is safe only where the
original uses it -- inside `NewSlotPool`, on a chain one long.

`PrintAllSlotPools` is **compiled into the retail build**, not stubbed -- a
real prologue at `0x0023fef8`, 304 bytes -- so this allocator's high-water
mark was readable on a shipped disc, and the port keeps the whole debug path
rather than eliding it. `main.c` points the hook at the debug log through a
line buffer, because a row arrives in up to six `bPrintf` calls and only the
last of them ends the line.

Nothing calls the allocator yet; tasks 21 onward are its callers. It is live
in the build rather than dead-stripped: `main.c` builds the manager where
`_GLOBAL_$I$` (`0x00240080`) builds it at load time, and releases the pools
on the way out, which the original does not do -- `~SlotPoolManager` clears
the sentinel and then walks an already-emptied list, so every pool made
through the manager is leaked at shutdown by construction.

### Things that bit

* **devkitARM makes `int32_t` a `long`.** The shipped `%d` format strings are
  kept byte for byte out of `.rodata` so a log from the port lines up with
  one from the PS2, which means the *arguments* get cast at the call sites
  rather than the formats being changed. Four sites.
* **The checker reported a bare `2816` for a crashed harness.** That is
  cygwin's `signal << 8`, i.e. SIGSEGV. It says `killed by signal 11` now.
* **Reading the failure reason off line 1 hides it** -- the same tooling bug
  as session 12's, from the other end. `hostbuild` prints `compiler
  warnings:` first and keeps going, so line 1 is the compiler's and the last
  line is whatever stderr trailed off with. The runner looks for the line
  starting `harness failed`.

Built and walked on Azahar: **PASS**, 13 screenshots, 19 textures cached, 0
missing, 0 fonts missing, exits cleanly.

### Next session

Task 21, VU1 geometry submission to citro3d. The survey work is already in
`docs/formats/solid-geometry.md`. `CONTINUE.md` has the pick-up-here list.

## Session 14 (2026-09-20) -- the geometry decoder, and what a mutation is for

Task 21 split in two on the way in, and 21a -- the decoder -- is done. 21b,
the citro3d submission path, is written and compiling but not yet wired to
anything on screen.

### The decoder

`3DS Files/source/geometry.c`/`.h`, written from
`docs/formats/solid-geometry.md` and deliberately not from
`tools/geometry_convert.py`, which is the other half of the cross-check. It
reads the `0x80034000` chunk tree, the 64-byte `eStripEntry` table and the
VU1 packets in `0x00034005`, replays the VIF UNPACKs into an image of
quadwords, and reads back transposed XYZ and normals, interleaved trailing-
group ST, per-vertex RGBA5551, the ADC suppression bitfield and the winding
that follows from it.

Nothing in it allocates. A strip cannot exceed 30 vertices -- the VU1 input
buffer is what bounds it -- so `GeoStrip` is a fixed scratch buffer the
caller owns and reuses. That matters for a 1,135-solid track bundle on a
handheld, and it is the reason the API is a cursor rather than an index:
`geo_decode_strip(solid, i, ...)` has to add up every preceding
`DataQWordSize` to find strip i's slice, which is quadratic across a
253-strip solid. `geo_decode_next` carries the running offset instead.

### The cross-check is shaped differently, for a reason

Every earlier checker in `tools/` drives scripted scenarios, because the only
oracle available was a second implementation written from the same
disassembly. Here there was a real one. `tools/geometry_convert.py` came
first and was validated against the shipped data itself, not against a port:
every vertex of all 1,465 solids inside its own AABB, the ADC rule
reproducing `eStripEntry.NumPolys` for all 22,280 strips, unit-length
normals. So `tools/geometry_check.py` drives the *disc*.

    python tools/geometry_check.py
    30 files, 42047 lines, 0 differ

A full per-vertex dump of that would be tens of millions of lines, so the
transcript has two densities and both sides print both: an FNV-1a digest per
strip and per solid, which covers every vertex without printing one, and the
invariant counts recomputed independently on each side. `--detail NAME`
switches one named solid to a full per-vertex dump on both sides, which is
what to reach for when a digest differs. Floats are never recomputed -- XYZ
and ST are read verbatim out of the file -- so unlike bmath's checker there
is no float-determinism problem here at all and the digest can be taken over
raw bit patterns.

`tools/geometry_mutate.py`: 51 of 51 caught, about two minutes over a
three-file subset (911TURBO, BARCHETTA, and TRACKA12 for the failure path).
`--full` runs all thirty.

### What the port found

Five corrections to `docs/formats/solid-geometry.md`, all now in it:

* **Normals are 125..127, not "126 or 127".** The old claim rejects 16% of
  the real data. They are unit vectors quantised onto a radius-127 sphere and
  rounding costs up to about 1.6. Measured over all 28 cars: 192,822 of
  192,822 non-zero normals inside the band, shortest 125.355. 53 of the
  192,875 are exactly zero -- in the data, not a decode failure, and *not*
  the same condition as "this strip has no normal field", which is about 17%
  of strips. Test whether the `V4-8` unpack at address 92 happened; do not
  test for a zero vector.
* **`eSolid.NumTextureTableEntries` at 0xAC is dead.** Zero on all 1,411
  solids, including one whose `0x00034006` table has 28 entries. The field is
  real -- it is where `eSolid::GetNumTextures()` reads -- but nothing the
  exporter ran ever wrote it. Count the chunk. `NumLightMaterials` at 0xAE,
  two bytes along, agrees with its table on all 1,411.
* **`eStripEntry.TextureNumber` at offset 0x00 was missing from the document
  altogether**, and it is the only link between geometry and the
  `0xb0300001` packs. 25 strips across the disc carry `TextureNumber ==
  NumTextures` -- one past the end -- which is the untextured sentinel: one
  strip of `TS50_C` and four each in the four `XS_CURVE35*_S*_00` track
  pieces. Range-check it; do not index with it.
* **The entry table is a redundant copy.** `NumVerts`, `NumPolys` and
  `LightMaterialIndex` agree with the strip's own VU header quad on all
  18,848 strips, zero disagreements. A renderer can size every buffer and
  skip every strip it does not want from the 64-byte table without replaying
  a single packet -- which is exactly what `georender_bake` does.
* **`TRACKS\TRACKA12.BUN` has no `0x80034000` at all.** All 1,135 track
  solids are in B12. A reader pointed at A12 should say "no solid list", not
  treat an empty result as a parse failure.

### And one real defect, found by a mutation

`geo_decode_next` did not advance its cursor past a strip it could not
decode. The natural caller loop -- decode, report the error, continue -- then
never terminates. Nothing on the disc triggers it, so no amount of running
the checker would have found it; the mutation that made `vif_replay` reject
every packet did, by printing 72 million copies of one line in sixty seconds.
The cursor now advances on every outcome but `GEO_EEND`, and `geometry.h`
says so with the loop it is protecting spelled out.

That run also exposed a deadlock in the checker worth remembering, because
every other checker in `tools/` has the same shape. `subprocess.run` with
`capture_output=True` needs the parent to drain a pipe the child is filling;
when the child runs away, the parent blocks on the drain, and `timeout=` does
not help because killing a cygwin-built exe from Windows does not reliably
close its handles. Fifteen minutes of a mutation run went into one hung
mutant. Harness stdout now goes to a **file**, not a pipe, and the transcript
is capped at two million lines -- the whole disc is 42,047.

Two mutations turned out to be equivalent only because of what this disc
contains, and both are written down with the measurement rather than quietly
dropped: starting the triangle loop at vertex 1 instead of 2 is invisible
because ADC bits 0 and 1 are set on all 18,848 strips, and making the
`adc_bit` range guard return 1 instead of 0 is invisible because the only
strips that could show it -- 17 vertices with bit 16 set -- do not exist here
(75 have 17 vertices; none has the bit).

### 21b, where it stands

`3DS Files/source/geosolid.v.pica` and `georender.c`/`.h` are written,
compile for ARM and link; the CIA still builds. Nothing is on screen yet.

The shader transforms and lights in view space, which is the same place in
the pipeline VU1 did it. Two PICA200 constraints cost an iteration each and
are worth knowing before writing another one: at most one uniform per
instruction and only in the **first** source slot, so `dp3 r3, r2, lightVec`
is rejected while the same operands reversed are fine; and `mad` cannot take
a uniform in either of the slots it leaves over, so ambient-plus-diffuse is
spelled as `mul` then `add`.

`georender_bake` sorts a solid's strips by `TextureNumber` before baking, so
a solid draws in one call per distinct texture rather than one per strip --
cheap, because the entry table already carries the texture number and the
triangle count. The vertex is 28 bytes; a triangle list rather than indexed,
because strips share no vertices in the source data and the largest solid on
the disc (911TURBO_A, 4,139 triangles) costs 348 KB. Cull mode is
`GPU_CULL_NONE`: the GS had no hardware backface culling, the VU did it in
software, and nothing in the data forces a consistent winding between the two
mirrored sides of a car body.

### Next session

21b's remaining work: wire `georender` into `main.c` behind the existing
viewer mode, resolve each `eTextureTable` hash through `texpack_find` and
`texpack_upload` (which already returns a `C3D_Tex`), and get one car on the
top screen from `CARS\*\GEOMETRY.BIN`. A single car is one solid list and
needs no streaming decision, which is why it is the cheapest first milestone.

Also carried: the user wants Phase 4's HUD designed for **two screens** from
the start -- some readouts on the bottom screen rather than stacked on the
top one. Recorded at the head of Phase 4 in `TASKS.md`.


## Session 15 (2026-09-20) -- a car on screen, and two bugs a cross-check waved through

Task 21 is closed. Cars draw on the top screen out of the shipped
`CARS\*\GEOMETRY.BIN`, with their own textures, lit, at 144 FPS in Azahar.
`4DR_SEDAN`, `4DR_SEDAN02`, `911TURBO` and `AMBULANCE` are recognisably
themselves -- the ambulance has its blue star of life and its red belt line
in the right places, which is the kind of evidence no digest gives you.

### What got written

`geoview.c`/`.h` is the third mode `main.c`'s SELECT cycles to: scan `CARS\`,
load a car, orbit it with the circle pad, step solids one at a time, toggle
textures with X. It deliberately does not place parts (wheels and mirrors are
in their own local space and the part transforms are not decoded yet, so
"draw everything" piles them at the origin) and does not pick a LOD beyond
"largest by triangle count", which is the `_A` body.

`texsrc.c`/`.h` reads a texture pack off the card a texture at a time.
`CARS\TEXTURES.BIN` is 15,300,536 bytes and one car needs about 400 KB of it,
while the port already holds 17.6 MB of UI bundles resident, so a second 15 MB
is not available on an Old3DS. Only the `0x30300003` info tables stay in
memory -- 126,608 bytes for the whole car set. The pixel blob stays on the
card and the two ranges one texture needs are staged at upload time. Nothing
about the format is re-implemented: `texsrc_upload` rewrites the offsets in a
*copy* of the `TexInfo` and calls `texpack_upload`, so `texpack.c` is still
the only decoder and `tools/src/texpack_test.c` still covers it.
`tools/texsrc_check.py` diffs the streaming reader against the whole-file one:
6 packs, 2 levels, 2952 textures, 0 differ.

`main.c` swapped `C2D_CreateScreenTarget` for an explicit
`C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8, GPU_RB_DEPTH24_STENCIL8)`,
because the citro2d helper gives no depth buffer and `C3D_DepthTest` against
no depth buffer silently does nothing.

### The two bugs, which is the part worth reading

**ST was decoded wrong, and the cross-check passed the whole time.**
`docs/formats/solid-geometry.md` said ST was transposed like XYZ -- a quad of
four S, a quad of four T. It is two vertices to a quad with the odd vertex's
pair mirrored: `(S_even, T_even, T_odd, S_odd)`, which is
`eStripDataE::GetElementST0` (`0x0011c8b0`) read literally. Session 14's
entry above says "interleaved trailing-group ST"; that was the wrong reading.

`geometry.c` and `geometry_convert.py` agreed exactly, digest and all, for
four sessions -- and the digest **does** cover every S and T. They agreed
because `geometry.c` was written from the document and the document was
written from the Python. Independence has to reach back to the source, not
just to a second implementation. The transposed reading consumes the same
bytes and yields plausible UVs in 0..1, so the symptom was a car upholstered
in smeared fragments of its own atlas -- which reads as "something is off in
the texture path", not as "the ST layout is wrong". The measurement that
settles it without a screenshot is the S==T rate: **44.43%** under the
transposed reading against **1.68%** under the right one, over all 212,408
car vertices. Transposing a mirrored pair aliases the two components
together, and real UVs almost never land on the diagonal.

**The `0x11` filler scan ate a hash.** Chunk payloads are front-padded with
`0x11` to a 16-byte boundary and every reader here skipped that run a byte at
a time. A byte scan cannot tell filler from a payload that begins `0x11`, and
`TS50_C`'s first texture hash is `0x4342fd11` -- little-endian puts the `0x11`
first. The scan eats it, the table shifts right one byte, and every hash in
that solid comes out as the real one shifted eight bits: not absent, not
obviously wrong, just resolving to nothing. 5 of the 1,461 solids on the disc,
silently, because a shifted hash is indistinguishable from a texture the packs
genuinely do not have. Both readers now step the two 8-byte tables an entry at
a time, which cannot over-skip in turn because the pointer half of an entry is
zero in all 4,646 entries on the disc. Checked against the sizes the
structures give: the byte scan is still right for the 192-byte header, the
`64 * NumStrips` entry table and the packet blob, on all 1,461.

Both bugs draw a car. That is the point. **A cross-check proves two decoders
agree; only looking at the output proves either one is right** -- and even
looking only found the first of these. The second took a specific suspicion
and a measurement.

The deck grew accordingly: `tools/geometry_mutate.py` is now 53 of 53, with
four ST mutations for the real layout and `table-filler-byte-at-a-time` for
the filler rule. `TS50` joined the fast file set because it is the only cheap
file that can reach that rule at all. Both filler mutations keep calling both
skip functions on a throwaway cursor, because dropping a call leaves an
uncalled static and then it is the compiler catching the mutation rather than
the cross-check, which says nothing about the deck.

### Two harness bugs, same session, same shape

The "untextured" screenshot came out identical to the textured one. The run
script was pressing `X` = `0x58`, which is Azahar's **Y** button; its X is
`Z` = `0x5A`. `%APPDATA%\Azahar\config\qt-config.ini` is the authority.

And one run captured the title screen and labelled it "first car", because the
script slept a fixed time after the boot marker and a *faster* boot moved the
keypresses earlier rather than later. `main.c` now logs the mode on every
SELECT and the script presses-and-confirms against the log instead of sleeping.
Any screenshot harness that sleeps has this bug latent in it.

### Recorded, not fixed

**58 of the 132 texture hashes** the car geometry refers to are in no
`0xb0300001` pack anywhere on the disc -- 729 of 8,114 strips, 9.0%.
`0x7b220ddf` alone is 140 strips across 13 cars. One name cracked so far,
`0xece04847` = `WIPER01`; the busiest six survive a full `bhash_crack` sweep
to six characters, so the answer is a better guess about what they are *for*,
not a bigger sweep. (The count before the filler fix was 68 of 142, ten of
them phantoms -- that is how well a shifted hash hides.)

**No alpha blending.** Glass draws opaque, white on the 911 and black on the
sedan. It is not vertex alpha: all 212,408 car vertex colours have their alpha
bit set. So it is texture alpha plus a GS blend mode, and recovering the blend
state is ELF work nobody has done yet. Strip `Flags` high bytes seen so far:
`0x4100` on body, `0xc100` on the unresolved textures, `0x5000`, `0x0c00`,
`0x0000`.

**Light materials** (`0x0003401d`) are still decoded and carried on every
strip and read by nothing.

### Next session

Task 16 (`bui.c`/`uirender.c`) back to `[x]` -- the outstanding part is 18b's
two scrolling background textures, `SCREEN_LINES` and `ROADLINES`. That closes
Phase 2. Then 22 (sound/DSP) onwards in order.

Still carried: Phase 4's HUD is to be designed for **two screens** from the
start, keeping the top screen's view of the road clear. Which elements go
below is the user's call and has not been asked yet.

---

## Session 16 (2026-09-20) -- the scrolling textures, and what they turned out to be

Task 16 was `[~]` on one outstanding item carried over from 18b: the two
scrolling frontend background textures. It is `[x]` now, which closes Phase 2.

### What got written

* `texpack.h`/`texpack.c`: four scroll fields on `TexInfo` (`ScrollType` at
  `0x79`, the two speeds at `0x7c`/`0x80`, `ScrollTimeStep` at `0x84`) and
  `texpack_scroll_axis()` / `texpack_scroll()`, a port of
  `TextureInfo::GetScroll` (`0x00100a60`).
* `uirender.c`: `UITexture` carries the scroll fields, `find_texture()` puts
  `GPU_REPEAT` on the scrolling axis (and only when the image fills that axis
  of the padded allocation -- both of these do), `uirender_set_time()` takes
  the clock, and `draw_bitmap()` offsets the subtexture after
  `subtex_from_pixels()` rather than before, because the original divides by
  the power-of-two size before adding.
* `bui.c`: `bui_set_bitmap_texture()`, a port of
  `FlailerBitmapChunk::ChangeTexture` (`0x0013eee0`), dirty byte 10 and all.
  Nothing in this build calls the original; it exists so the viewer can point
  a bitmap at a scrolling texture through the real draw path.
* `main.c`: the viewer's B key cycles the current screen's bitmaps through
  `ROADLINES`, `SCREEN_LINES` and back, sized to the screen, with a readout
  line of its own carrying the clock and the two offsets.
* `tools/src/scrollline.h`, shared by both texture harnesses, plus the
  reference in `texpack_check.py`. The sample times are the point: a port
  that reads all four fields correctly and *rounds* where `GetScroll`
  truncates prints the same six fields and a different animation, and the
  samples catch it (checked by making that exact change: 2 of 2 differ).
  `texture_convert.py`'s `scroll_uv()` now rounds every intermediate to
  single precision, because the EE has no double and neither does the port.

### The two textures are cut content

`ROADLINES` (`0x63d32d60`) and `SCREEN_LINES` (`0x2cd838f9`) occur **exactly
once each in all of `extracted/`** -- their own `0x30300003` record. No
Flailer bitmap, no second pack, and nothing in `NFSHP2.ELF`. A texture the
frontend draws occurs 16 or 17 times, so the count means what it looks like.
Session 9's guess that `SCREEN_LINES` is the menu background's scanlines is
struck out above.

And `SCREEN_LINES` could not have animated on the PS2 either: 8x256 of one
colour with the pattern in alpha, `162,162,220,220` repeating -- period four
rows -- while one step moves `0.015625 * 256` = exactly four rows. Every step
lands on the same phase. Frames of it a second apart are bit-identical, and
that is the right answer, not a missing offset.

### Looking at it, which is the only thing that proves it

`tools/run_azahar_scroll.ps1`. `ROADLINES` at t = 50.34, 53.16, 56.15 s: the
device reported du = +0.3293, +0.5336, +0.8668, each the fractional part of
`t * 0.78125` worked out by hand. du grew by 0.2043 then 0.3332 between the
frames, which across the quad's 618 px in the capture predicts 126 px and
206 px of travel leftwards; circular cross-correlation of two separate row
bands measures 126 px and 206 px. `SCREEN_LINES` at t = 60.75, 63.53, 66.50:
dv = -0.7188, -0.8125, -0.9688, each `frac(trunc(t/0.04) * -0.015625)` -- the
type-2 truncation, on the device.

That the correlation is *circular* is the other half: the texture wraps
through the allocation instead of clamping, which is `GPU_REPEAT` doing its
job on the scrolling axis.

### Recorded, not fixed

* **The half-texel inset.** `RenderSingleFlailerBitmap` insets every UV corner
  by half a texel of the padded size before adding the scroll. The port does
  not. It applies to all 397 textures in `FRONTB.BUN` rather than the two that
  scroll, so it is a change to every UI quad and wants its own pass.
* **`bgf_consider_start_demo_mode()` traces every frame once the idle timer
  expires**, because the port's `startDemoMode` hook is a stub and never
  changes state. That is two SD writes a frame; it slows the emulated app
  enough that most `PostMessage` key presses fall inside one frame and are
  never scanned, and it is why `run_azahar_scroll.ps1` presses SELECT up to
  40 times. The fix belongs in `gameflow.c`, which `bootflow_check.py`
  diffs transcripts of, so the Python reference has to move with it.

  It makes `run_azahar_test.ps1` itself flaky, which cost a full
  regression hunt this session. Two runs in a row came back PARTIAL --
  once "reached the main menu, but not Cops On Mode Select", once
  "movie played, never reached the main menu" -- both with 0 bracket
  moves, and the two differed from each other, which is the tell. The
  check that settled it: stash the source changes, rebuild at `0a58704`,
  run -- PASS; restore, rebuild, run twice -- PASS, PASS. Three in a row
  after two failures, so the verdict is load, not code. Both PARTIALs
  followed a long `run_azahar_scroll.ps1` run on the same machine. A
  PARTIAL from this harness is worth one re-run before it is believed;
  a *repeatable* one, or one whose failure mode is the same twice, is
  real.
* **The bui setters are not cross-checked at all** -- `bui_check.py` covers
  the parse path only, and `bui_set_bitmap_texture()` joins seven existing
  setters outside it.

### Next session

Task 23 Camera, then 24 TrackRoute/Esp, 25 car sim, 26 race and cop AI,
27 track render/stream/collision, 28 New3DS perf, 29 save/options/sound mix,
30 split-screen, 31 the final CIA pass.

Still carried: Phase 4's HUD is to be designed for **two screens** from the
start, keeping the top screen's view of the road clear. Which elements go
below is the user's call and has not been asked yet.

## Session 17 (2026-09-20) -- sound, and two checkers that were lying

Task 22 closed, all three parts. The game makes noise now, and the noise is
the disc's.

### 22a, the banks

`tools/audio_pack.py` transcodes the 30 `SOUND\*.MSH`+`.MSB` pairs into 30
`.SBK` files, 439 patches and 6.51 MB of Nintendo DSPADPCM, joining each
stereo pair into one record. `sndbank.c` reads them and refuses anything whose
`dataSize` does not match its sample count. `tools/sndbank_check.py` diffs it
against an independent Python reader: 908 lines, 0 differ, worst re-decoded
SNR 22.59 dB across all 469 channels.

One thing the pack now refuses: a record with a nonzero `Pan` or `ADSR`. All
469 on this disc are 0, `.SBK` has nowhere to put them, and the port
substitutes `BSND_PATCH_PAN` and the driver's `0x1a00000a` default. A bank
that broke the assumption would otherwise have played centred and nobody
would have known.

### 22b, the driver

`bsnd.[ch]` is the port of `bDriverPS2.o`'s voice layer -- allocation, the pan
table, the volume/pitch units -- over ndsp. `docs/formats/sound-driver.md` is
the writeup, and `tools/gen_bsnd_tables.py` extracts
`bSnd_nArraydBPanTable` (`0x00317d00`) into `bsndtab.c`, re-verifying the
cosine half every run.

`tools/bsnd_check.py` drives both it and a second implementation through
twelve scenarios: 5157 lines, 0 differ, and 25 of 25 deliberate breaks of the
C caught.

Three things the ELF corrected mid-port:

* **The master `bSnd_VoicePlay` has no pan argument.** Placement is an
  azimuth (`0x00247fac`), and every pan-taking overload converts through
  `GetAzimuthFromPan` first. The first port took both and produced a voice
  with `az=8192` and `pan=0`, which is not a state the engine can reach.
* **`GetVolumesFromAzimuth` returns at its first branch unless the driver is
  in Prologic.** So on a stereo TV an azimuth only ever reaches the mix
  through `GetPanFromAzimuth`; what it otherwise changes is `Type`.
* **The pan table is the equal-power law, not a linear fade.** Entry 127 --
  dead centre -- is 11655, 0.711 of full, about 3 dB down each side. An
  earlier draft of the doc called it "0.04 dB down", which was simply wrong
  arithmetic and would have made a plausible-looking bug hard to find later.

### 22c, the frontend

`fesound.[ch]` is `MakeFrontendSound` (`0x001692c0`) and the 33-entry table it
indexes (`0x002f30ac`), generated into `bsndtab.c` alongside the pan table.
`bmenu.c` already raised the events -- `BMenuSoundFn`, from a previous session
-- so wiring it up was installing `fesound_play` on two menus, `bsnd_hw_init`
after `gamedata_init`, and `bsnd_update` once a frame.

Azahar: `Sound: 34 patches in 24 voices`, a stereo pair per key press at
22042 Hz, and the busy count never climbing past 2 across a whole run, which
is what says the per-frame retirement works. The sounds were heard.

### Two checkers that were lying, and what that cost

**`sndbank_check.py` stripped every CR, not just the line endings.** Its
`run_c()` did `.replace(CR, "")` to normalise Windows text mode. A mutation
that flips a name byte to `0x0d` then vanished from the C transcript while the
Python model still had it, and the run reported 11 disagreements that were
nothing of the kind. The fix is to split on newlines first and drop one
trailing CR per line. With that, 20000 mutations over 30 banks: 0 disagree.

**Two of `bsnd_check.py`'s mutations were equivalent mutants.** They
"survived", which looks exactly like a coverage hole:

* `if (azimuth <= 0x4000)` -> `<` is identical on all 65536 azimuths, because
  the first quadrant computes `az * 127` and the last computes
  `(0x8000 - az) * 127`, and at `az == 0x4000` those are the same number.
* `const float k` -> `const double k` is identical on all 256 pans: the
  constant is exactly representable as a float and every product fits a
  double exactly, so the double path rounds once, where the float path also
  rounds once.

Both were replaced with mutations that do change behaviour, and the reasoning
is in a comment above the table so nobody re-adds them. A survivor is a claim
about the scenarios *or* about the mutation, and it is worth a minute to find
out which before writing more tests.

### Also

* **The Bash tool eats one level of backslash in a heredoc.** Two patch
  scripts silently half-applied -- `
` inside a replacement string became a
  real newline, so the pattern never matched, and the script printed "done".
  Any patch script whose replacement contains a C escape needs the backslash
  built from `chr(92)`, or the edit made with the file-editing tool instead.
* **`tools/hostbuild.py` has no CLI.** `python tools/hostbuild.py --out ...`
  exits 0 and builds nothing. It is a library; call `hostbuild.build()`.
* **A `printf` with a side-effecting argument makes the transcript
  compiler-dependent.** `bsnd_test.c` had one call printing both
  `bsnd_bank_register(...)` and `d.patchCount`; C does not order those, so the
  count printed would depend on the toolchain. Split into two statements.
* **FRONTEND has two patches named `SelectFinal` and four identical
  waveforms at its tail.** `RewardEnter`, `RewardExit`, `AudioSliderUpDown`
  and the second `SelectFinal` are four copies of the same 5728 bytes on the
  disc. That is the disc's doing, not the packer's -- checked against the
  `.MSB` before believing it.

## Session 18 (2026-09-20) -- VU0 made readable, and the camera on the boom

Task 23 closed, and the layer under it with it. Two objects ported
(`Camera.obj`, and `CameraMover.obj`'s base plus `CM_ORBIT_CAR`), one new
disassembler, two new cross-checkers, and a bug that only showed up when
somebody looked at the screen.

### `tools/vudis.py`, because none of this could be read

Almost every line of `eMathE.obj` is VU0 macro mode -- COP2 opcodes in the EE
instruction stream -- and `mipsdis.py` printed them as `cop2` plus a raw
word. The new decoder is checked against sixteen hand-derived words and then
against the whole image: 3087 COP2 words in `.text`, 41 distinct mnemonics,
nothing left undecoded.

### `eMathE.obj` -> `emath.[ch]`

Twenty-six symbols, `docs/formats/emath.md`, and
`tools/emath_check.py` at 9 scenarios / 2416 lines / 0 differ with 39 of 39
mutations caught. Three traps are written up there: `eMulMatrix(o,a,b)` is
`a*b` where `bMulMatrix` is `b*a`; `eInvertRotationMatrix` clears the corner
as well as transposing; and `eNormalizedDirection` divides a 3D vector by its
**2D** length, which is a bug in the original that the port keeps.

### `Camera.obj` -> `camera.[ch]`

The camera does not decide where it is. It is handed a matrix once a frame
and pulls the eye, the direction, the target and the velocities out of it,
and `SetCameraMatrix` is the whole object.

**Half the velocity record is dead, and it is dead on the disc.**
`SetCameraMatrix` copies `CurrentKey` over `PreviousKey` as its first act and
then recomputes only the matrix and the three vectors, so when it reaches the
six scalar subtractions each pair is the same word. All six velocities --
target distance, focal distance, depth of field, near, far, field of view --
are identically zero and nothing can arrange otherwise; every writer of those
six writes before the call, never between the copy and the subtraction. That
is measured, not argued: all 44 velocity records in the transcript print
`scal 0 0 0 0 0 fov 0`. The u16 wrap and the truncation on the field of view
are ported anyway, because that is what the instructions say, and three
mutations of them are on the equivalent list as a result.

Two more that a sensible re-implementation gets wrong: the fourth column of
the matrix is never cleared, so the constructor's stray `100.0` lands in
`Position` and the default eye is a hundred units short of its own
translation row; and the negate is `vsub.xyzw vf02,vf00,vf02` against VU0's
constant `(0,0,0,1)`, so the pad lane comes out `1 - w`. `bVector3` is a
padded quadword and the pad is differenced and divided like everything else,
so the port carries all four lanes.

### `CameraMover.obj` -> `cammover.[ch]`

The base class and `CM_ORBIT_CAR`, which is the boom the car select and the
replay orbit ride. The other seventeen movers need `Car`, `TrackRoute` or the
streaming world, so they wait for tasks 24-27.

`Enable` and `Disable` are not symmetric and the asymmetry is load-bearing:
`Disable` does not test `StopUpdating` at all, and it copies the camera's two
render flags back *into* the mover on the way out, so a disable/enable pair
round-trips whatever another mover left on the camera rather than restoring
what this one first saw. The first port had `Disable` as a bare flag write;
disassembling `0x154658` fixed it.

`TweakOrbitFOV` is not behind `UseTweakables`. It lands on the camera every
frame, so the constructor's `InGameFOV` of 13020 is overwritten before
anything can use it and the orbit really is 8000 BAMs, about 44 degrees. A
debug tweakable that shipped switched on.

`tools/camera_check.py`: 7 scenarios, 1200 lines, 0 differ; 47 mutations, 40
caught, **7 equivalent with a written argument each**, 0 unexplained. Four of
the seven are arithmetic identities (a bounded approach whose step lands
exactly on its target at a gap of exactly `accel`; the same argument for the
80-BAM angle walk; clamping `Radius` or `DesiredRadius` first; and
`TargetDistance = Radius` versus `DesiredRadius`, which the zoom transcript
shows are equal on every frame). The other three are the dead FOV velocity.

### Then somebody looked at it

The geometry viewer no longer has a camera of its own. It builds a
`CamCarView` at the current solid's AABB centre, runs a real
`OrbitCarCameraMover` against a real `Camera`, and hands `CurrentKey.Matrix`
and `CurrentKey.FieldOfView` to citro3d. The first run drew a black fan of
triangles radiating from a point.

**`C3D_FVec` is declared `w, z, y, x`, in that order.** So `r[i].c[j]` is
element `(i, 3 - j)`, and the loop that transposed the engine's row-vector
matrix into it was writing every row backwards: the translation ended up in
column 0, the eye never left the world origin, and the car was being drawn
from inside its own bodyshell. The cross-check could not have caught it --
the matrix it diffs was correct -- and neither could code review, because a
transposed-and-mirrored view matrix reads exactly like a transposed one.

With `c[3 - c]` the cars are cars again, and `run_azahar_geo.ps1` now
captures the boom doing each of its jobs: a held zoom and a shot 1.5 s after
release that differs by 0.011/255 (two frames of the idle spin differ by
1.009, so the test can fail), the acceleration limiter 150 ms into a held
pad, and the elevation clamp stopping short of overhead.

The pad signs came out of the ELF rather than out of taste: `JoyHandler`'s
jump table at `0x2950e0` is nine **debug camera** events, 46..54, not the
`JOY_EVENT_CARSEL_ORBIT_*` ones at 35..43 -- the car select screen drives
this mover through its setters instead. `ROTATE_UP` asks for a *negative*
vertical speed, so holding up walks `AngleV` toward `MaxAngleV` and lowers
the boom. The viewer is wired the same way.

### Also

* **Azahar's "Update Available" dialog swallows every posted keypress.** The
  geometry run pressed SELECT eight times into a modal dialog and reported
  that the viewer was never reached, with a perfectly healthy log to go with
  it. All three `run_azahar_*.ps1` now close any visible top-level window of
  the emulator process that is not titled "Azahar" before they press
  anything.
* **The orbit is per frame, not per second.** Rotation speeds are BAMs per
  frame and the zoom compounds 1% per frame, so at the 139 FPS Azahar gives
  this build the zoom is a factor of four in a second and puts the eye inside
  the car. That is the disc's own behaviour on a fixed console. Task 28 has
  to decide whether the 3DS keeps it.
* **Two requests arrived mid-session** and are written down as tasks 32 and
  33: stretch the frontend to fill the 3DS's 5:3 top screen rather than
  leaving the 4:3 sides empty, and `ChallengeBeACop` -- which the flow
  changes to and then reports `unregistered`, the same shape as the
  `Options` gap from session 9.

### The second screen finally does something

Three requests arrived while task 23 was running. Two are done.

**32, the aspect.** `UIView` carried one `scale` and centred what it drew;
it now carries a `scaleX` and a `scaleY` with both origins at 0, so the
disc's 640x480 maps onto the top screen by stretching -- 400/640 across,
240/480 down -- instead of fitting inside it with 20 px of nothing down
each side. Only the final quad is stretched: object positions, hit boxes,
the menu and the scroll demo all still work in the space the disc authored,
and the movie plane is a bitmap object like any other, so it comes along.

**34, the blurb.** The one-line description under a menu is `SCROLLING_TEXT`
driven by `tAnimatedBlurb`. It is about ten pixels tall in a 480-line frame,
which is five on the top screen; the zoom of a frontend screenshot that
settled it is unreadable at 6x. So it is off the top screen now
(`uirender_hide_object` skips it and the `WHITEOUT_BAR` it is wiped out
with, at layer-walk time rather than by writing the visibility field the
animation owns) and the bottom screen is given over to it: the screen's name
along the top under the frontend's red, the line wrapped and centred in
FONT_A at a 19 px line height, the controls along the bottom.

Two things were worth getting right rather than fast:

* **Where the line lives.** Not at the `setBlurb` hook. `tAnimatedBlurb`
  sets `LanguageID` back to 0 at the end of its wipe and *prints the
  resolved translation into the object* (`banim.c:620`), so the hook sees
  only some of the changes. The panel reads the object every frame instead,
  through a new `uirender_object_string()`, and crossfades when the string
  differs from the one it is drawing. That also means it tracks the wipe's
  own 0.5 s debounce for free: holding a direction on the menu still reads
  as one change, not one per item.
* **The wrap does not reproduce the shipped bug.** `RenderCharacter`
  multiplies a glyph's width by `ScaleX` twice (`0x0013f750` and
  `0x0013f794`) and the screen path keeps it, because the disc's screens
  were laid out with it on screen. A wrap width has to agree with the width
  actually laid down, so `uirender_draw_wrapped()` does not -- and it counts
  kerning when it measures, which `GetScaledWidth` also does not. Both
  divergences are in `docs/formats/flailer-ui.md`.

**35, no console on the bottom screen.** The first run of the panel came out
as two half-width copies of itself under a teal dither, which is what
`consoleInit(GFX_BOTTOM)` and citro3d look like sharing a framebuffer: the
console switches that screen to RGB565 and citro3d keeps presenting BGR8
into it. The console is gone. The three bring-up overlays it carried --
flow state, geometry viewer, screen viewer -- go to `nfshp2_debug.txt`
instead, one slot per line and only when the line changes, because at
Azahar's 140 FPS a line a frame is a megabyte a minute of identical text.
The two viewer modes get the same panel with their own controls on it, and
the only console the port still creates is on the *top* screen, in the three
paths that are about to exit.

Looked at, not just diffed: `run_azahar_test.ps1` PASS (13 shots, 12 blurb
changes, 20 textures cached, 0 missing, 0 fonts missing -- one more texture
than before, which is FONT_A's glyph sheet) and `run_azahar_geo.ps1` 18
shots with the zoom-creep test still passing at 0.015/255. The first pass of
the panel also said the numbers were "in nfshp2_debug.txt"; FONT_A has no
underscore, the glyph was dropped, and the screen confidently named a file
that does not exist. It says "the debug log on the SD card" now.

### Ten screens that were not there

**33, `ChallengeBeACop` is unregistered.** It was, and so were nine others.
The interesting part is not the missing rows, it is what a missing row
costs. `ChangeToScreen` (`0x00167850`) unactivates the old screen and clears
`pCurrent` *before* it looks the new name up, so a name with no registry row
does not leave the player where they were -- it leaves the list with no
current screen at all. On the port that is a black top screen, one line of
trace, and BACK as the only way out. An unported screen is cheap; an
unregistered name is a dead end.

So the whole set got gathered at once instead of one at a time on the
emulator. Ten names the port's own C can pass to `bgf_change_to_screen` had
no row: `Challenge`, `ChallengeBeACop` and `View Event Tree` off the two
Mode Selects, and the seven Options pages. All ten are registered now to
`bgf_plain_screen_callback`, which is an empty function -- the chunk draws,
`bmenu` moves the highlight, BACK works, A does nothing -- and every one of
their chunks was already in `FRONTB.BUN`, so the CIA did not grow and the
texture count went from 20 to 22.

Two of the rows share a screen with a row that already existed, which is the
ELF's doing rather than a shortcut: `Language Options` is the same chunk and
the same class as `Language Options Pre FE` under a second name, and
`NameEntry` draws the same chunk as `Username Options`.

`tools/screen_registry.py --check-port` is the standing check, and it exists
because a hand-written table of hashes is exactly the kind of thing that
goes quietly wrong. It reads `FlailerScreenConfigList` out of the ELF and
`kScreens[]` out of `main.c` and prints two lists: rows whose hash disagrees
with the ELF, and screen names a source file mentions that the table does
not carry. The second list is the useful one -- the Mode Selects' item
tables and the Options pages spell their destinations out as literals, so a
literal naming a registered screen is a name the player can reach. Both
lists are empty: 18 of 62 registered, 44 to go.

Looked at, not just diffed: `run_azahar_test.ps1` PASS, 14 shots, 22
textures cached, 0 missing, 0 fonts missing, and the new `beacop` shot is
"You're The Cop" with Players / Skill Level / Setup drawn where a black
screen used to be. The panel underneath said nothing at all on the first
pass, because it takes its line from `SCROLLING_TEXT` and a plain screen has
no blurb -- an empty panel under a screen name reads as a bug, so there is a
fixed line for plain screens now saying the class behind it is not ported
and B is the way out. Written without an apostrophe, on the same grounds as
last session's underscore.

One thing the run caught that is worth remembering: the first attempt came
back PARTIAL because a single A press at the main menu never registered, and
the harness walked on to the wrong item. Re-running was clean. The harness
drives Azahar by synthesised keystrokes and it can drop one; a PARTIAL is
worth repeating before it is worth debugging.

Two stale comments went with it. `gameflow.c` said `Challenge`,
`ChallengeBeACop` and the Options pages were unregistered, which is what
this task changed, and it also said `View Event Tree` "is in no screen
config" -- it is (`tEventTreeView`, `0x147f8a59`); what is true is that
nothing pushes it as a boot stage, so the `SelectedEventData` branch in
`LaunchFrontendMenus` is dead for that reason and not the one written down.

## Session 19 (2026-09-21) -- the centreline, and a format that did not exist

Task 24 closed, and Phase 3 with it. Two objects ported (`TrackRoute.obj`
whole, and the slice of `TrackPath.obj` it reaches), one new cross-checker,
one tool bug fixed, and a correction to the task list that was most of the
first hour.

### `espEmptyLayer` is not a format

`TASKS.md` entry 24 asked for the "`espEmptyLayer` -- 'Esp' spline/track-layer
format". There isn't one. **Espresso** is bware's live remote-editor
protocol, spoken over `bFunk` to a PC-side server; **Caffeine** is the
program on the other end. The evidence is all in the image:

| where | what |
|-------|------|
| file `0x1a40c8` (VA `0x2a30c8`) | `EspressoServer` |
| file `0x1a4142` | `Espresso version conflict.  Caffeine = %d, Espresso = %d` |
| mdebug | `EspressoFunctions:t306=eEF_IsCaffeineRunning:0,EF_InitCommunication:...,EF_LoadWorld:3,EF_ReloadWorld:4,...` |
| mdebug | `UpdateToCaffeine__10TrackRoute`, listed beside `EraseDrivingLine` |

An enum of `EF_LoadWorld`/`EF_ReloadWorld` members and a version handshake is
an RPC protocol, not a container. `EspClient.obj` is its client;
`TrackRoute::UpdateToCaffeine` (`0x1b7de8`) pushes one route down the wire,
and its only caller is `TrackRouteEditor::Service`, which is dead in the
retail build. None of it is ported, none of it is on the disc, and the task
entry now says so rather than sending the next session after it again.

What the tracks actually carry is two chunks, both plain `bChunk` payloads
inside the track bundle: `0x00034121` TrackRoutes and `0x00034122` Signposts.
Neither has a count field.

### The thing that made this port different

**The loader does not parse.** `TrackRoutesLoader` casts the chunk bytes to
`TrackRoute *` and registers the pointer. Nothing is copied, nothing is read
field by field, and a `TrackRoute *` the game holds points straight into the
loaded bundle -- which is why `Unloader` unlinks routes and never frees them.
The on-disc record is therefore the in-memory layout exactly, with one
economy: the 1024-entry point table is truncated to the points the route
actually has, so the stride is

    115752 - (1024 - NumPoints) * 112

and the walk reads `NumPoints` out of each record to find the next. In
`extracted/TRACKS/TRACKB12.BUN` that is 17 routes over 302008 bytes at
`0x7af66c`, and 56 signposts over 448 bytes at `0x7f922c`.

A format loaded by casting has no decode step that can fail loudly. A field
at the wrong offset compiles, loads, and then reads nonsense. Two
consequences, both of which the harness caught rather than review:

* `sizeof(TrackRoute)` came out **115760** on the 64-bit host, not 115752.
  The record's `bTNode` list links are host pointers in the original
  declaration and they have to be `u32` slots here -- they hold disc garbage
  that the manager overwrites on link anyway. `trackroute.h` now asserts the
  size, and `TrackRouteManager` came to 832 bytes for the same reason.
* `tools/trackroute_check.py` models every record as a **byte image** with
  accessors at the offsets the listing loads and stores from, rather than as
  a Python object with named fields. On a cast-loaded format that is the only
  way a wrong offset moves a line in the transcript instead of hiding behind
  a field name.

Both are worth carrying to the next cast-loaded chunk, and the note is in
`CONTINUE.md`.

### `TrackPath.obj`, and an honest hole

Three functions in `trackroute.c` want one number from `TrackPath` -- how far
around the lap a position is: `Signpost::SetDistances`,
`TrackRoute::SetFirstAndLastPoints` and `TestSignpostConsistency`. Nothing
else in the object touches it. So `trackpath.[ch]` carries the three
structures, the chunk loader and `CompareDistances` ported exactly, and stops
at one declared hole: `TrackPathManager::UpdatePosition` (`0x1f5620`, reached
from `0x1f5dd0`) refines against a `QuickSpline`, and `QuickSpline.obj`
(`0x00227e98`, 0x1018 bytes -- basis matrices, arc-length calibration) is a
separate library that is not ported.

While it is not, distances come out zero, and that is *visible* rather than
silent: `trackpath_have_splines()` says so and the route viewer prints it.
`gTrackPathDistanceFn` is the seam -- `NULL` on the handheld, and in the
harness a closed-form ramp built only from add, multiply and compare so the
Python model reproduces it bit for bit. It exists to reach
`SetFirstAndLastPoints` wrap detection, which is the one piece of TrackRoute
arithmetic only a non-zero distance can get to. The debt is written onto
task 27, where `QuickSpline` belongs.

### Two shipped quirks, kept

**`MovePoint` sets elevation from `pos->x`.** The listing stores the same
register into `Position.x` and into `Elevation`; `pos->z`, the height the
caller passes, is never read. **`GetPosition` (3D) does not write `pad`** --
the VU0 macro-mode ops work four lanes at a time and the `w` lane two inputs
are stack slots the function never initialises. Only the track-route editor
called either, so neither ever ran in a shipped build. Both are kept as-is
and both have a mutation pointed at them, so anyone who "corrects" one finds
out from the checker rather than from a car driving underground.

### The harness, and the one survivor

10 scenarios, 671 lines, 0 differ; 53 mutations, 52 caught, 1 equivalent,
0 unexplained. The survivor is `find-no-bbox-early-out`, and it is an
argument rather than an excuse: the bounding box holds every point on the
route, so a query outside it grown by `radius` is further than `radius` from
every point in at least one axis, and the track-distance metric cannot rescue
it either, because `GetDistanceAway` returns the larger of the plane distance
and the along-track one and so is never below the plane distance. The
early-out can save the loop; it cannot change what the loop returns.

Three of the first four survivors *were* coverage holes and got scenarios.
The fourth was a scenario that happened to be degenerate: the wide route two
bucketings coincided, so retuning it to three points separated them.

### `bchunk_dump.py` was stopping at the first pad

Found while surveying the track bundle: the walker treated an all-zero
eight-byte header as a terminator, so it reported **8 chunks** in
TRACKB12.BUN 9 MB -- five at the top level and three nested, because the
walk hit the alignment run at `0x7048` and stopped. `bchunk.c` had always
skipped such headers, so the tool and the C had disagreed silently for as
long as both existed. Skipping the pad and continuing finds **472 top-level
chunks** (25 zero-pad headers among them) and **7076** counted recursively
at the default depth. The dumper is not the authority on the format; the
loader is.

### Also

`tools/trackroute_check.py` was written out with the file-editing tool rather
than a heredoc, because the Bash tool mangles apostrophes as well as
backslashes. The `CONTINUE.md` warning covered only backslashes and now
covers both. It cost one failed command this session even after being
written down, which is the argument for writing it down twice.

The line-ending note in `CONTINUE.md` was inverted and is now measured. There
is no `.gitattributes`, `core.autocrlf` is true, and **every blob in the repo
is LF** -- so endings never reach a diff. The working tree is mixed, though:
`TASKS.md`, `HANDOFF.md`, `CONTINUE.md`, the `.c`/`.h` under
`3DS Files/source/` and `tools/geometry_convert.py` are CRLF; the other
`tools/*.py`, `tools/src/*.c`, `README.md` and all of `docs/` are LF. Three
files written this session were off-convention and were converted to match
their neighbours.

The build links clean with `trackroute.c`, `trackpath.c` and the rest
(`tools/build_cia.ps1`; the `.note.GNU-stack` warning out of the devkitARM
`crtn.o` is pre-existing). Nothing in the port calls into TrackRoute yet --
there is no gameplay to call it -- so this is a diffed port, not a run one,
and the task entry says so.

### Next session

Phase 4, task 25, the car simulation. **Its HUD is two screens from the
start** -- the standing constraint is at the head of Phase 4 in `TASKS.md`
and repeated in `CONTINUE.md`; which readouts go on the bottom screen is not
decided and wants asking before anything is built.

## Session 20 -- CarState.obj (task 25, first slice)

Ported `CarState.obj` (`0x001b6170`..`0x001b6f60`), the car's state record
and the sixteen functions that maintain it, to
`3DS Files/source/carstate.{c,h}`. Cross-checked by
`tools/carstate_check.py` against `tools/src/carstate_test.c`: 10
scenarios, 653 lines, 0 differ; 63 mutations, 56 caught, 7 equivalent, 0
unexplained. Written up in `docs/formats/car-state.md`.

`DoSnapshot` (`0x001b6230`) is deliberately not ported -- it needs
`ReplaySnapshot`, which belongs to a later task.

Findings:

* **The object carries its own pi.** `0x40490fd0`/`0x40c90fd0` at
  `0x003219ec`, against bMath's `0x40490fdb`/`0x40c90fdb`. Not cosmetic:
  `GetYawAlways` folds on `pi < rad`, and the products of the BAM
  difference step past `0x40490fd0` through a 402-ulp gap, so every
  wrapping angle folds -- whereas with bMath's value the exact half-turn
  sits *on* the boundary and does not. Reproduced bit-for-bit; the
  `pi-from-library` mutation is caught.
* **Two quadword operations are decorative.** WorldToCar3's pad subtract
  and CarToWorldUnadjusted's z both die on `eMulVector3` forcing w to 1.
  Kept because the object does them, argued in `EQUIVALENT` rather than
  dropped.
* **`CARSTATE_SLACK`.** CarState's two pointers are dereferenced, so the
  `uint32_t` trick used on TrackRoute's list links was not available. The
  layout assert instead carries `2 * (sizeof(void *) - 4)`, so all ~40
  offsets are still checked on a 64-bit host, and the harness dirties by
  field rather than by byte pattern so the transcript means the same
  thing on both widths.

Two mutation survivors on the first pass were real coverage gaps, not
equivalents, and the scenarios were extended to close them: nothing
set RPM away from 1000 before `ResetCarForSound`, and no transform case
had a z that decided the `lensq` branch. A third (`wheel-brake-gets-spin`)
was a badly written mutation -- it applied a rotation by zero -- and was
rewritten to actually give the brake matrix the spin.

Task 25 is **not** finished: `Car`, `PhysicsCar`, `Suspension`, `Wheel`,
`Engine`, `CarDriver` and the bulk of `CarTypeInfo` are still to port.

---

## Session 20 (2026-09-21) -- Task 25, four more slices of the car sim

Ported, each with its own model, transcript, mutation pass and format doc:

| Slice | Commit | Transcript | Mutations |
|-------|--------|-----------|-----------|
| `Engine.obj` + `Table` | `457967f` | 8 scen, 413 lines, 0 differ | 56, 54 caught, 2 equiv |
| `CarTypeInfo.obj` | `2608924` | 4 scen, 177 lines, 0 differ | 41, 41 caught |
| `CarDriver.obj` + `DriveTarget` layout | `85a27f8` | 5 scen, 118 lines, 0 differ | 48, 48 caught |
| `Steering.obj` + `TwoWheelAckermanSteering.obj` | `c165c01` | 5 scen, 873 lines, 0 differ | 44, 43 caught, 1 equiv |

`docs/formats/car-engine.md`, `car-type-info.md`, `car-driver.md` and
`car-steering.md`.

### The scope of task 25 was wrong by an order of magnitude

An earlier note in `TASKS.md` put the remainder at "178 functions, 16680
bytes". That tally matched only a narrow symbol pattern and missed most
methods. Re-measured by demangling every symbol to its owning class, what
was left at the start of this session was ~67.7 KB across ~366 functions
-- roughly 19x the CarState slice -- and after these four it is ~67.0 KB
across ~355. The corrected table is in `TASKS.md` under task 25.

**`RigidBody` and `DriveTarget` are prerequisites the task list never
named.** `Suspension`, `PhysicsCar` and `Car` all need `RigidBody`;
`CarDriver` needed `DriveTarget`'s record, whose layout is now done and
whose 28 methods are not. Suggested order for the rest: `RigidBody`,
`Suspension`, `Wheel`, `DriveTrain`, `DriveTarget`'s methods,
`PhysicsCar`, `Car`, with `Mellovator` and `MellowMover` last.

At this verification standard that is several more sessions, not one.
Task 25 stays `[~]`.

### Findings

* **The vtable pointer is at the END of every class in this image.** Old
  g++ ABI: `CarDriver` 556, `Steering` 8. The instinct is to look for it
  at offset 0, and every remaining class in task 25 has this shape.
* **Array extents are part of a layout claim.** Nine CarTypeInfo
  mutations survived the first pass, all of them shrink-an-array-and-pad.
  That leaves every following offset *and* the total size unchanged, so
  the static assert lets them through. They were a real coverage gap, not
  equivalents: the transcript now prints each array's extent, its element
  stride, and the field widths and signedness probes. The same trap
  reappeared in `Steering` and has a padded mutation of its own there.
* **Steering's pi is wrong in a useful direction.** The object carries
  `0x40490fd0` (pi), `0x40c90fd0` (2pi) -- the same eleven-ulps-low pair
  CarState has -- and `0x3fc90fdc` (pi/2), one ulp *high*, which reaches
  every steer matrix because the cosine there is `bSinF(angle + pi/2)`
  rather than a cosine call. Loosening the fold's `pi < rad` to `<=`
  survives the mutation pass and is genuinely equivalent, *because* of
  that constant: no 16-bit BAM produces exactly `0x40490fd0` (the
  products step `0x40490e49 -> 0x40490fdb` straight across it), whereas
  with the true float pi, BAM 32768 lands on it exactly and the two
  comparisons would part company.
* **SetSteering is Ackerman with tan(x) ~ x.**
  `outer = (W * inner) / (W + T * inner)`, which is why there is a divide
  and no atan. The port keeps the approximation including the angles
  where the denominator nears zero and it blows up; the transcript has a
  geometry that lands there on purpose.
* **`SportGear` is never initialised.** `CarDriver`'s constructor memsets
  the 528-byte `DriveTarget`, clears five inputs and sets `DesiredGear`
  -- byte 548 is never written, and a fresh driver inherits whatever the
  allocation held. Pinned by constructing over two byte patterns.
* **A field the debug info omits.** `CarTypeInfo.pCarSpecs` at 1368,
  recovered from `lw v0,1368(a0)` in all six string accessors. A second
  witness for `sizeof` came from `GetCarTypeInfo` at 0x001801c0 emitting
  `addiu v1,zero,1376` as a literal, in a different compilation unit from
  the `.mdebug` entry.
* **Two destructors leave the base class's vtable behind.**
  `~TwoWheelAckermanSteering` writes its own, then `~Steering` writes the
  base's over the top. The port keeps both writes in that order.
* **`operator new` ignores its size argument** (both `CarTypeInfo`'s and
  `TwoWheelAckermanSteering`'s) -- a bOMalloc on a slot pool, which only
  ever hands out one size. Not ported; recorded because it matters if a
  class grows.
* **Argument evaluation order can silently break a transcript.**
  `printf("%d %u", draw(&seed), seed)` read the global seed *before* the
  call under gcc's right-to-left order, putting every seed line off by
  one. Take the call into a variable first.

Not ported, for the usual reason: `Engine::DoSnapshot`,
`CarDriver::DoSnapshot`, `Steering::BaseDoSnapshot` and
`TwoWheelAckermanSteering::DoSnapshot` all need `ReplaySnapshot`.

---

## Session 21 (2026-09-21) -- Task 25, the rigid body and the suspension

| Slice | Commit | Transcript | Mutations |
|-------|--------|-----------|-----------|
| `RigidBody.obj` | `c421118` | 10 scen, 935 lines, 0 differ | 77, 75 caught, 2 equiv |
| `Suspension.obj` + `wheel.h` layout | this one | 10 scen, 1108 lines, 0 differ | 68, 66 caught, 2 equiv |

`docs/formats/rigid-body.md` and `car-suspension.md`.

`RigidBody` is 47 functions and 4508 bytes and was the prerequisite the
task list never named -- `Suspension`, `PhysicsCar` and `Car` all sit on
it. `Suspension` is 29 functions and 1944 bytes, and it needs two `Wheel`
methods it does not own, so `wheel.h` carries Wheel's 400-byte record and
the two entry points are function-pointer seams, the shape
`gTrackPathDistanceFn` already has. That header is **a layout, not a
port**; Wheel itself is the next slice.

Remaining in task 25: ~60.6 KB across ~279 functions. Order from here:
`Wheel`, `DriveTrain`, `DriveTarget`'s 28 methods, `PhysicsCar`, `Car`,
with `Mellovator` and `MellowMover` last.

### Build for ARM before calling a record done

The strongest finding of the session is a process one. `wheel.h`'s layout
assert was wrapped in `#if __SIZEOF_POINTER__ == 4`, reasoning that
nothing depended on Wheel's *host* layout yet. The effect was that the
claim was compiled by neither toolchain: the host build skipped it, and
nobody had run the ARM build. When the ARM build finally ran, it failed.

The PS2 record has four bytes of padding at 284 because `bVector4` is a
quadword type there and starts 16-aligned. **This port's `bVector4` is a
plain four-float struct with four-byte alignment**, so the gap does not
appear by itself: the handheld's record came out 396 bytes with every
contact vector four bytes early.

On the 64-bit host it was invisible, and invisible in an actively
misleading way. The four pointers in front widen by twenty bytes counting
alignment, `WorldGroundForce` needed only sixteen, and the missing gap
and the extra widening cancelled exactly. The model and the harness
agreed, at a SLACK multiplier of 4 rather than 5, on a record that was
wrong for the target. `wheel.h` writes the gap out as `_pad2[4]` now.

Two rules out of it, both general:

* **A claim no compiler checks is a comment.** Do not guard a layout
  assert with a host test that makes it vanish on the host.
* **The host harness cross-checks arithmetic, not layout.** It is not the
  target, and on the target the same struct can be a different size. Run
  `tools/build_cia.ps1` before a slice with a record in it is called done.

### Other findings

* **A constant the model caught because it reads the ELF.**
  `suspension.h` had `SUSPENSION_IMAGE_HALF_PI 1.5708f` (0x3fc90ff9).
  `ComputeAuxiliaries` loads `gp-29656` = 0x00321818, and that word is
  **0x3fc90fdc** -- the same one-ulp-high pi/2 `Steering` takes from the
  same pool, thirty ulps away from the rounded literal. The checker reads
  its constants out of the ELF rather than out of the header, so the two
  disagreed on the first run. A model that had copied the `#define`
  would have agreed with the bug.
* **A value that is zero makes the code that produced it invisible.**
  Five mutations survived the first pass on one mistake: every
  `[penalty]` case varied only the *z* lane of the contact normal, all
  four approached away from the surface, and all four took the early
  return, so the impulse, the mass factor, the `gNoWheels` path and the
  `w` lane were never executed. Two more survived because the force floor
  clamped a wrong answer and a right one to the same 0. The fixtures
  carry a `grazing` zero normal and two raised rest loads now.
* **Boundary fixtures have to be reachable.** A droop stop of -0.22f
  could not be hit: the surface is `FindDrivingSurface() + Radius`, and
  no float return value makes that sum exactly -0.22f, because the ulp at
  0.57 is twice the ulp at 0.22 and 0xbe6147ae has an odd mantissa. -0.25
  round-trips exactly (Sterbenz), so that is what the fixture uses. The
  compression stop is not the same problem -- `x - y` is exact there for
  the same reason -- which is why `su-bumpstop-inclusive` is a genuine
  equivalent and `su-droop-inclusive` was a real gap.
* **Two globals hide their own callers.** `gGroundPenaltyForce` ships as
  0.0 and `gUglyTimestepHack` as 1.0, so the penetration term and the
  divide are both dead at shipped values. The transcript moves them, the
  way the debug menu could.
* **`.sdata` tuning globals are worth reading rather than assuming.**
  Ten of them, all reachable from the debug menu, and three of the five
  coverage holes above were only visible once they moved.

Not ported, same dependency as ever: `RigidBody::DoSnapshot` and
`Suspension::DoSnapshot` need `ReplaySnapshot`, along with `CarState`,
`Engine`, `CarDriver` and `Steering`. `RigidBody::PrintCurrentState` is
ported empty -- it is not empty in the image, but the printf is gone, the
function is void and every store is dead.

## Session 22 (2026-09-21) -- Task 25, the wheel, and twelve survivors

`Wheel.obj` is ported: `3DS Files/source/wheel.{c,h}`, cross-checked by
`tools/wheel_check.py` (19 scenarios, 10693 lines, 0 differ; 154 mutations,
144 caught, 10 equivalent, 0 unexplained), written up in
`docs/formats/car-wheel.md`. `wheel.h` stops being "a layout, not a port";
the 400-byte record it carried for `Suspension` now has the object behind
it. The ARM build compiles both layout asserts unguarded, which is what
found the four-byte `_pad2` in the first place.

The port itself went the way the previous two slices did. The part worth
writing down is what happened afterwards.

### The mutation pass came back with twelve unexplained survivors

Not two or three -- twelve, on the biggest mutation list in the repo. Six
were real coverage holes, six were equivalent, and two of the twelve
mutations were themselves badly written and meant nothing until they were
rewritten. The whole triage is in `docs/formats/car-wheel.md`; these are
the three that generalise.

**A comment claiming a case is covered is not coverage, and it is worse
than no comment.** Both the harness and the model said, in prose, that a
vx of 0.4 with a spin of 1.25 put the slip at exactly zero and so reached
`GuessGroundForce`'s zero-magnitude early-out. `1.25 * 0.32f` is
0.399999976. The slip was -2.98e-08, the magnitude with it, and the guard
was never reached at any point in the transcript. The mutation that
deletes it survived, and the comment was twice the reason to look
somewhere else for the explanation. `37.5 * 0.32f` is 12 with nothing left
over, and that pair now has a block of its own -- run both loaded-and-free
and barely-loaded-and-braked, because `perMag` is read only on the
slipping arm.

**A boundary fixture can be masked by the test after it.** `|slip|`
exactly `gMaxStaticSlip` was already in the transcript, and had been since
the slice was written -- with a vx of 0 and a vy of -3, which puts the
slip angle far past `MaxSlipAngle` and sets `Slipping` on the *next*
test whichever way the trigger goes. The equality was pinned for
`CurrentSlip` and not for the branch, so `<` against `<=` survived a
fixture built for it. The new pair keeps vy at zero and vx positive.

**Two mutations could not have been caught by anything.** One wrote only
to its own parameters (`lo = hi = value;` in an empty function) -- three
dead stores. Rewritten to assign the global a debug slider plausibly
would, it still survived: the call passed 0.5 and `gMaxStaticSlip` already
*is* 0.5, so it wrote back the number that was there. It took a third
version -- call with 0.375, and re-dump the tuning block straight after
the call -- before "SetSliderValue is empty" became a checked claim rather
than a comment. The other deleted an explicit two-byte alignment pad in
front of a pointer, which the ABI puts straight back; that one is
equivalent by construction and is argued rather than rewritten.

### Other findings

* **`ExchangeZForces` returns 0.0f on every path.** Both exits end
  `mtc1 zero,$f0`. `Suspension::ResolveForces` writes that return value
  into its own `GroundForce`, so that field is zero on every frame of the
  shipped game. The transcript prints the return and the stored `ZForce`
  side by side so the two can never be conflated.
* **Negative zero is a distinguishable input.** `!(0.0f < z)` and
  `z < 0.0f` agree on every float except `-0.0f`, where the first is
  airborne and stores a clean `+0` and the second computes `-0.0f * d`.
  `%.9g` prints the sign, so one fixture value separates them.
* **One ulp in a dot product is not enough on its own.** Frames 2 and 3
  spend the dot on `N * -d + row`, where both terms are the same size and
  the last bit rounds straight back off. The row has to be nearly parallel
  to the contact normal first, so flattening cancels almost all of it and
  the residue carries the whole error; frame 3 then normalises the residue
  and it reaches the fifth significant digit of the world force.
* **A guard can be protecting the read rather than the number.**
  `Table::GetValue` returns `pTable[i]` outright at `i == last`. Delete it
  and the interpolation weight is exactly zero, so the arithmetic comes
  out identical -- off the back of a load one element past the end of the
  array. No transcript can see that; a sanitiser build would.
* **Two globals hide two thirds of this object.** `gUseNewTireForces` is 1
  and `gWheelForceFrame` is 1, which makes the old tyre model and three of
  the four force frames unreachable at shipped values. Both are `.sdata`
  the debug menu writes, so the transcript moves them.
* **`wheel.h` and `wheel.c` were written LF** while every other `.c`/`.h`
  under `3DS Files/source/` is CRLF in the working tree, and `carstate.h`
  got flipped to LF by a whole-file rewrite. Git normalises on commit so
  none of it showed in a diff. All three are back to CRLF.

**The two seams are wired but nothing installs them.**
`wheel_install_seams()` points `gWheelFindDrivingSurfaceFn` and
`gWheelExchangeZForcesFn` at the real methods, and nothing in
`3DS Files/source/` calls it -- so on the handheld they are still NULL.
That is right for now, because no car is constructed yet, but whichever
slice first builds a car owes that call before its first `ResolveForces`.
The seams are a port artifact and not something the image has: at
`0x0019bdd4` and `0x0019c104` the PS2 build makes two ordinary `jal`s.

Not ported: `MaybeMakeSkids` needs the `SkidMaker` and belongs to task 27
with the skid trails. `MaybeMakeSmoke` and `MaybeMakeTireSpew` are each a
bare `jr ra` in the shipped image and are ported empty, with a note rather
than a TODO. `DoSnapshot` needs `ReplaySnapshot`, the same dependency
`CarState`, `Engine`, `CarDriver`, `Steering`, `RigidBody` and
`Suspension` are all waiting on.

**Next is `DriveTrain`** -- 39 symbols, 5608 bytes, one contiguous run from
`0x00182828`, a 148-byte record fully named in the `.mdebug`, and every
dependency (`Engine`, `Table`, `Wheel`) already ported. The layout and the
reading order are in `CONTINUE.md`.

---

## Session 23 (2026-09-21) -- Task 25, the drivetrain, and eighteen survivors

`DriveTrain` is ported: `3DS Files/source/drivetrain.{c,h}`, cross-checked
by `tools/drivetrain_check.py` against `tools/src/drivetrain_test.c` (18
scenarios, 492 lines, 0 differ; 176 mutations, 173 caught, 3 equivalent, 0
unexplained), written up in `docs/formats/car-drivetrain.md`. The ARM build
compiles it and the 148-byte layout assert passes unguarded. Ninth slice of
task 25, and the first whose every dependency -- `Engine`, `Table`, `Wheel`
-- was already on the handheld.

The gearbox, the clutch and the differential: everything between the
crankshaft and the four rims. One state float, and it is not a physical
quantity -- it is how far the clutch pedal is up, 0 to 1.

### There is no DriveTrain.obj

The class is a contiguous run of 39 symbols, `0x00182828 .. 0x00183e10`,
5608 bytes, **inside `Engine.obj`** -- whose `.text` the map puts at
`0x001823d8`, `0x1b98` long, with Engine's own nine functions below the run
and twenty-five above it and none of Engine's interleaved. That is why the
vtable, `ClutchSpeed` and the pooled literals are all quoted as Engine.obj's
`.rodata`, `.data` and `.lit4`: DriveTrain has no sections of its own.

The same check turned up an error in an earlier slice's doc.
`docs/formats/car-steering.md` opened by quoting a `Steering.obj` and a
`TwoWheelAckermanSteering.obj`, and neither exists: both classes live in
`Suspension.obj` (`.text 0x0019ba98`, `0xb08`), and unlike DriveTrain they
are *not* contiguous -- the three are interleaved, with
`Steering::~Steering` as the object's first symbol and Suspension's 29
methods sitting in the middle of TwoWheelAckerman's range. The doc now says
so and lists the symbols in address order. `steering.h` was right all
along, which is why it gives addresses one at a time.

### The mutation pass came back with eighteen unexplained survivors

On a transcript that agreed with the model on every one of its 443 lines.
That is the reason to run the pass at all: **a clean diff says the two
sides compute the same thing, not that the scenarios reach the code.**
Sixteen were reachable and are now killed, which took the transcript to 492
lines; two cannot be killed by any input and are argued in `EQUIVALENT`.
Four groups, and three of them are shapes this repo had not seen before.

**A fixture can agree with itself.** Three survivors were that.
`ct-shift-points-use-down-detune` swaps which detune the constructor hands
to `CalculateShiftPoints` -- and the image ships `gShiftUpDetune` and
`gShiftDownDetune` both at 0.95, so the swap is invisible.
`ca-neutral-skips-pedal` drops the pedal store in NEUTRAL, and
`Engine::Engine` leaves `ThrottleOverride` at 1.0, which is exactly what
the arm writes. `au-low-gear-bound` clamps `DesiredGear` to `FIRST_GEAR`
when the constructor had already set it to `FIRST_GEAR`. Nothing is wrong
with the mutation or with the code in any of the three; the input cannot
tell them apart. Detunes of 0.8 and 0.6, a pedal pre-set to 0.25 and a
`DesiredGear` of fifth kill all three.

**An inclusive-comparison mutant needs the two sides equal bit for bit, and
picking a likely number is not good enough.** `au-up-test-inclusive` and
`au-down-inclusive` are killed by writing the shift point back as the very
RPM the object will compute, from the same product on both sides, so the
comparison is against itself -- choosing an engine speed and hoping the
product lands on a table entry is only true to a few ulps.
`ss-refuse-inclusive` could not be fed back that way: it needed an engine
speed whose sport RPM is exactly second gear's 900 RPM crawl point, and a
numeric search says `94.2477036f` is the one and only float whose product
with the rads-to-RPM constant is exactly 900.0f. Both neighbours land an
ulp off. `ss-limiter-margin` is a fourth boundary of a different shape --
it deletes the 300 RPM margin below `MaxRPM`, and the two engine speeds
already in the transcript were over both thresholds and under both; 720
rad/s sits in the band at 6875.5.

**A search loop can be in every scenario and never do any work.** The
crossover search only does anything when the torque curve falls hard past
its peak: the test compares the torque here against the torque at the
geared probe scaled by the same ratio, and with that ratio around 0.7 the
right side is already a third smaller before the curve is consulted. The
first fixture engine fell gently, so four gears out of five took the
fallback -- the loop ran and never found anything, and two of its mutations
rested on nothing. `sp-midpoint-is-redline` moves the search's start from
the midpoint of idle and `MaxRPM` to the midpoint of idle and
`RedLineRPM`; both are on the 50 RPM grid and every fixture crossed over
far above both, so the two starts converged. `sp-crossover-not-strict`
needs the two sides exactly equal, and since the probe is scaled by a ratio
below 1, a flat non-zero curve always comes out strictly smaller -- only an
all-zero curve gives equality. A steep engine and a zero engine, both
checked numerically before any code was written, kill the pair.

**And one was killed with a signed zero.** `gc-disengaged-applies` makes
the DISENGAGED arm apply a clutch torque of zero instead of returning.
Adding zero to a float changes nothing -- unless the float is `-0.0f`,
where `-0` plus `0 * share` is `+0`. `AppliedTorque` and `RoadTorque` start
at `-0.0f` in that fixture and `%.9g` prints the sign, so the original
prints `-0` and the mutant prints `0`. Both sides agreed, which also
confirms C and Python print signed zero identically here.

### The two that survive, and the one listed for another reason

`gc-clamp-inclusive` makes the clutch limiter's comparison inclusive. The
two differ on exactly one input, slip equal to `gClutchLimiter`, and there
the mutant assigns the slip the value it already holds. The scenario *does*
sit on that boundary -- `gc DISENGAGING slip 300` drives it exactly, the
fixture putting the differential at 200 and the engine at 200 plus slip
against a limiter of 300 -- and the mutant survives it. That is the
argument, not a gap in it.

`au-down-into-neutral` drops the second half of the automatic's downshift
test, the part that refuses to shift below first. The arm is only reached
past an earlier guard that returns outright when the current gear is below
first, and nothing writes the gear in between -- it is read once from
`CurrentGear` at the top. The image tests it anyway, because the PS2
compiler reloaded `CurrentGear` and compared it again rather than proving
the same thing.

`h-slack-is-zero` is in `EQUIVALENT` for a different reason.
`DRIVETRAIN_SLACK` is `sizeof(void *) - 4` and appears only in the layout
assert, so pinning it to 0 makes the assert wrong on this 64-bit host and
the mutant does not compile -- it is reported as *caught* here. It is named
so that a future run on a 32-bit host, where the same edit compiles and
changes nothing, reports it as equivalent instead of stopping on a hole
that is not one. `mutate_pass` was changed to count the equivalents that
actually survived rather than the length of the list, so naming it costs
nothing on this machine: the summary says 3 equivalent, not 4.

### Smaller findings

* **Gear indices are the enum, not zero-based.** `GearRatios[2]` is first
  gear. SPORT_SHIFT is -2, AUTOMATIC -1, REVERSE 0, NEUTRAL 1, FIRST_GEAR 2
  through SEVENTH_GEAR 8, and both RPM arrays are `float[9]` indexed the
  same way.
* **Two of the three differential queries halve and one does not**, and
  they disagree about when. The details are in the doc, because it is the
  kind of asymmetry that reads as a transcription slip and is not one.
* **The clutch torque split is diagonal under `BurnOutState`**, not
  front/rear.
* **Fixtures are spelled, not computed.** Every fixture float is its own
  decimal literal on both sides. `0.32f + 0.01f` is 0.329999983, one ulp
  below the float nearest 0.33: the model rounds a literal once and the C
  rounds the sum twice. The `ac share` lines are tagged with the numerator
  rather than the ratio for the same reason -- a ratio computed in double
  on one side and in float on the other is a fixture disagreeing with
  itself.
* **`make` still only works through `tools/build_cia.ps1`.** Exporting
  `DEVKITARM` by hand from Git-Bash and running `make` fails at the
  top-level guard, which is a *different* failure from the one documented
  at the top of this file, where the guard passes and `$(INCLUDE)` comes
  out empty. Map a space-free drive letter with `subst` and go through
  devkitPro's own msys2 login shell; nothing else has ever worked here.

Not ported: `DoSnapshot` (`0x00182b00`) needs `ReplaySnapshot`, the same
dependency `CarState`, `Engine`, `CarDriver`, `Steering`, `RigidBody`,
`Suspension` and `Wheel` are all waiting on. `operator new` and
`operator delete` are the PS2 slot allocator (`DriveTrainSlotPool`,
`0x00323090`). `PrintCurrentState` (`0x00183c28`) is a bare `jr ra` in the
shipped image and is ported empty, with a note rather than a TODO.
`CheckFunction` is declared in `.mdebug` and has no code at all.

**`Wheel`'s two seams are still wired and still not installed.** DriveTrain
does not construct a car, so `wheel_install_seams()` remains uncalled and
`gWheelFindDrivingSurfaceFn` and `gWheelExchangeZForcesFn` are NULL on
hardware. Whichever slice first builds a car owes that call before its
first `ResolveForces`.

**Next is `DriveTarget`'s methods.** `DriveTarget.obj` exists this time --
`.text 0x002086f8`, `0x24d0` long -- but it is not all DriveTarget: seven
`OBB` methods and the free function `bDoublesBack` (`0x00208fa0`) are in
the same run, which is why the object is 9424 bytes against a DriveTarget
tally of 8636. The copy constructor is emitted somewhere else again, at
`0x001da210` inside `CarCollisionDetect.obj` (`.text 0x001d8770`, `0x1bf8`
long). The tally of 28 reconciles exactly once the two non-methods are
named: twenty-six methods in the object, that copy constructor outside it,
and the `_GLOBAL_$I$__11DriveTarget` static-init thunk at `0x0020ab48`,
8636 bytes between them. **Twenty-six functions to port.** The 528-byte
record is already spelled out and ARM-compiled in `drivetarget.h`, so the
layout is done.

### DriveTarget does not need Car, and that was checked

The order recorded in `CONTINUE.md` and `TASKS.md` had DriveTarget waiting
on `Car`, on the strength of thirteen of its twenty-six methods taking a
`Car *`. They do, and it does not matter: **every one of them reaches
`Car` only through the `CarState` embedded at byte 64**, which has been
ported since the first slice of this task. `Car` is 2016 bytes and its
`.mdebug` entry carries `State:/0263,512,8192` -- bit 512, so byte 64,
1024 bytes -- and across `Clear`, `InterpolatePoint`, `Resample`,
`EstimateScore`, `CalculateMaxSpeed`, the acceleration fillers and the
four `AddPointToTarget` overloads the only Car offsets touched are 64
(passed straight on as a `CarState *`), 96 (`State.Position`) and 112
(`State.Velocity`). The three free functions in the call graph are the
same story: `IsPointAheadOfCar` (`0x001c0e30`) reads 96 and 112 and
nothing else, `CalculateLookAheadDistance` (`0x001c0c20`) is
`max(State.VelocityMagnitude * 2.0f, 20.0f)` in six instructions, and
`GetMaxLateralAcceleration(Car *)` (`0x00209f30`) never reads its
argument -- it is `lui at,0x41f0; mtc1 at,$f0`, a constant 30.0f. A `Car`
stand-in whose only live member is a `CarState` covers the class, so
**DriveTarget can be ported in full now**, and the docs have been
corrected to say so.

Blocked, and only these three: `DoSnapshot` on `ReplaySnapshot`; `Dump` on
`Car::WorldToCar`, which is a tail-jump to
`CarState::WorldToCar(bVector2 *, bVector2 *)` at `0x001b6ab0` that
`carstate.c` does not carry yet; and the `DrivingLocation` overload of
`AddPointToTarget` on `DrivingLocation::IsClear`, which is
`lw v0,0(a0); sltiu v0,v0,1` -- one word at offset 0, so a stand-in
covers it until task 26 brings the class.

The gp-relative constants are resolved and written into `CONTINUE.md` so
they do not have to be found twice (`_gp` is `0x00328bf0`): `Clear`'s and
`CalculateTime`'s speed epsilons are both 0.001 at `0x00321fa8` and
`0x00321fc0`, `CalculateTime`'s "no time" return is 9999999.0 at
`0x00321fc4`, and the look-ahead scale and floor are 2.0 and 20.0 at
`0x00323a50` and `0x00323a54`.

Two shapes to model carefully when the port is written. `GetAngle` clamps
its index down to `NumPoints - 2` and never back up to 0, so a
`NumPoints` of 0 or 1 indexes `Points[-2]` and `Points[-1]` -- a real
out-of-bounds read in the shipped game, the same flavour as
`Table::GetValue`'s. And `SetPoint`'s `bVector2` overload builds a stack
`bVector3`, writes x, y and z and leaves w alone, then the `bVector3`
overload copies all sixteen bytes with `lqc2`/`sqc2`, so `Points[i].w`
takes whatever was on the stack.

---


## Session 24 (2026-09-22) -- Task 25, DriveTarget, and a restore that failed quietly

`DriveTarget`'s methods are ported: `3DS Files/source/drivetarget.c`,
cross-checked by `tools/drivetarget_check.py` against
`tools/src/drivetarget_test.c` (22 scenarios, 821 lines, 0 differ; 259
mutations, 239 caught, 20 equivalent, 0 unexplained), written up in
`docs/formats/car-drive-target.md`. Tenth slice of task 25. The 528-byte
record had already been ARM-compiled through `cardriver.c` in the previous
slice; `drivetarget.c` itself now compiles and links into the 3DS ELF, so
the layout assert holds on a 32-bit-pointer target as well as on the host.

### The first mutation pass left seventy-two survivors

On a transcript that already agreed with the model on every one of its 660
lines -- the same lesson as DriveTrain's eighteen and Wheel's twelve, and
it keeps being worth the pass: **a clean diff says the two sides compute
the same thing, not that the scenarios reach the code.** The transcript is
821 lines now.

### Two boundaries the fixtures sat on and still could not see

The last two survivors were a shape the earlier slices had not produced.
In every previous case a survivor meant the fixture never reached the
branch. These two reached it exactly -- the two versions really did take
different paths -- and the dump printed the same numbers anyway.

`bl-window-inclusive` turns `accTime < 0.75` into `accTime <= 0.75` at the
tail of `BlendWithCurrentAcceleration`. The fixture already put `accTime`
at exactly 0.75, so the mutant ran one more pass. That pass blends at
`0.75 * 1.33333337`, which clamps to 1 and leaves x and y where they are;
z, pad and `CalculatedSpeed` were zero already and `SetPoint3` writes zero
into all three. An extra pass that changes nothing. Giving the points a z
of 3 makes it visible, because `SetPoint3` zeroes z whatever the blend is
and `Length` is recalculated from it.

`rs-inner-test-strict` turns `len[k] <= travelled` into `len[k] <
travelled` at the head of `Resample`'s step-over. It needs `travelled ==
len[k]` exactly, and that is still not enough: the real code then emits
`Points[k+1]` at frac 0 and the mutant emits `Points[k] + seg[k]` at frac
1, which is the same point unless the addition fails to undo the
subtraction. Three points with legs of exactly 5 m put the accumulator on
the boundary, and the separation goes in the pad, where `16777218 - 1` and
`1 + 16777216` are both ties that round to 16777216 -- two ulps short of
where the other arm lands. The pad is not in `len3`, so the geometry stays
a plain 3-4-5 ladder, and everything after that one slot re-syncs.

**So a survivor has two possible causes, not one.** Either the fixture
does not reach the branch, or it reaches it and the branch's effect is
invisible in what the dump prints. The second is harder to spot, because
the fixture's comment says it is on the boundary and the comment is
correct.

### A cheap mistake worth not repeating

The first attempt at the `rs-inner-test-strict` fixture wrote 16777218 into
`dt_point`'s fourth float, which is the `CalculatedSpeed` and not the pad.
`dt_point` writes 0.0 into every pad by design, so the number never reached
the arithmetic under test and the mutation survived a fixture built
entirely around it. The dump said so -- `s 16777218` in the speed column,
`0` in the pad column -- which is an argument for a dump that prints every
field rather than the interesting ones.

### The restore failed and the tree kept the mutation

Mid-pass, a write came back `OSError: [Errno 22] Invalid argument` on
`drivetarget.c`. These sources are under OneDrive and a write to a file the
sync client has open fails that way; it is transient. The problem was where
it landed. The failing write was the **restore** in the `finally`, so the
pass died with the tree holding `ga-clamp-order-swapped`, and the traceback
said only that a write had failed. The next clean run reported `ga one
42441` against the model's `9673` with nothing in the diff to say why.

Every checker in `tools/` had the same shape, so every one of the twelve
that runs a mutation pass now has a `write_source()` that retries five
times, and a restore that -- if it truly cannot put the original back --
exits naming the file and the mutation instead of letting the numbers that
follow describe a source nobody meant to write. Patched:
`cardriver`, `carstate`, `cartypeinfo`, `drivetarget`, `drivetrain`,
`engine`, `rigidbody`, `steering`, `suspension`, `wheel`, `camera`,
`trackroute`.

That is the second repo-wide hole in the mutation runners found this way.
The first, last session, was the missing `timeout=` -- a mutant that turns
a loop into one with no exit hangs the pass. Both were invisible until a
mutation happened to trigger them.

### Moving a forward-ported function home broke the slice that borrowed it

`drivetarget_assign` had been living at the top of `cardriver.c` since the
CarDriver slice, because `SetDriveTarget` tail-calls it and DriveTarget had
no `.c` of its own. This slice moved it to where it belongs, and
`cardriver_check.py` stopped linking -- twice: first on
`drivetarget_assign`, then, once `drivetarget.c` was added to its sources,
on `WorldTimer`, which `engine.c` owns. Its harness now defines its own tick
the way `drivetarget_test.c` does, rather than dragging Engine, Table,
CarTypeInfo and Wheel in behind it, and its source list carries
`drivetarget.c` and the eight files that reaches.

Worth saying because it will happen again: **every forward-ported helper
sitting in a neighbour's file is a link edge that breaks when its real file
arrives**, and the checker that breaks is not the one being worked on. Run
the whole checker list, not the new one, before calling a slice done.

### A third repo-wide hole: multi-line mutations that never matched

Re-running `cardriver_check --mutate` after the move above reported
**32 mutations, 32 caught** where `TASKS.md` records 48. The sixteen that
vanished printed `PATTERN NOT FOUND` and were then dropped from the
denominator, so the tally line read clean.

The cause is line endings. `core.autocrlf` is `true` and there is no
`.gitattributes`, so a checked-out ported source is CRLF, while a source a
port script wrote in place is LF -- the tree is a genuine mix, 51 of the
files under `3DS Files/source/` are LF today and the rest are not. The
mutation patterns are written in the checkers with bare `
`. A single-line
pattern does not care. **A multi-line pattern misses every time against a
CRLF file, and misses silently**, because "not found" is a different
outcome from "survived".

Worse, it is not stable: the same mutation matches or does not depending on
whether that file was last written by git or by a patch script. `cardriver`
was measured at 48/48 when `cardriver.c` and `cardriver.h` happened to be
LF. Nothing changed in the checker between then and now.

`rigidbody`, `steering`, `suspension`, `wheel`, `drivetrain` and
`drivetarget` already detected the file's newline and translated the
pattern. `cardriver`, `carstate`, `cartypeinfo` and `engine` did not, and
now do. `camera` and `trackroute` had a second version of the same bug from
the other end: they read the source with universal newlines, so their
patterns matched, but `write_source` writes with `newline=""` -- so a
mutation pass **rewrote every file it touched from CRLF to LF and left it
that way**. They now read with `newline=""` and translate like the others.

Three of `cardriver`'s sixteen were the `assign-*` mutations, which are
`drivetarget.c`'s to make now; `drivetarget_check` already carries
`as-copies-half` and `as-returns-src`. Dropped rather than retargeted --
**a checker mutates the file it owns.** The other thirteen all pass:
`cardriver_check --mutate` is **45 mutations, 45 caught, 0 unexplained**,
and 45 rather than 48 is the honest number.

### The slice order in TASKS.md was wrong: Car comes before PhysicsCar

`PhysicsCar::Move` (`0x00135c78`) calls three `Car` methods and reads seven
`Car` offsets outside the embedded `CarState`, so PhysicsCar cannot be
modelled with the `CarState`-only stand-in that DriveTarget used. Car has
to be ported first. Both `CONTINUE.md` and `TASKS.md` said the opposite.

### What Car actually is, measured rather than assumed

Eighty methods, 22876 bytes, `Car.obj` at `0x0012f150` (`0x5e1c`). Six are
emitted outside that object, including the eight-byte `Car::WorldToCar` at
`0x00138e90` that `DriveTarget::Dump` is waiting on. The record is 2016
bytes with one non-virtual base at offset 0, `bTNode<Car>` (8 bytes) --
**Car has no vtable**; the `__pure_virtual` the map shows against Car.obj
belongs to the `CarDriver` / `CarMover` / `CarController` abstract bases
that share the object.

**Car is the hub, not the physics.** Thirty-three of the eighty call
nothing outside the class and are pure state work. `Think` and `Drive` are
among them because they are pure dispatch -- load `pCarController` (offset
40) or `pCarDriver` (44), read the (delta, fn) pair out of the vtable,
jump. The rest reach into about a dozen subsystems that belong to tasks 26,
27 and 29: replay, cop manager, the effect system, force feedback, sound,
topology, collision, render info, damage, `Player` and `Race`, and eleven
driver/mover classes that `SetControlMode` and `SetMovementMode` construct
between them.

Two small things to do first, both outside Car -- or so this said. It was
one. `Graph` is 8 bytes and two methods (`0x00187440`, `0x00187450`) and
four Car methods want it; it is ported now, below. The second,
`CarState::WorldToCar`, was already done and is covered below too.

`SetMovementMode`'s physics arm is also where `wheel_install_seams()`
finally belongs -- it is what constructs the `PhysicsCar` that owns the
`Suspension` and the four `Wheel`s.

## Graph, and the prerequisite that was already ported

`Graph` is the last thing standing between the port and `Car`, and it is
small: eight bytes, two methods, and no object file of its own. Like
`Table` it is a header-inline class, so its code lands in whichever
compilation unit used it -- which is why `Graph::Graph` and
`Graph::GetValue` sit at `0x00187440` and `0x00187450`, right after
`Table`'s five, rather than in a `Graph.obj`. Sixteen call sites build one;
four of them are `Car`'s.

Ported to `3DS Files/source/graph.{c,h}`, cross-checked by
`tools/graph_check.py` (16 scenarios, 151 lines, 0 differ; 25 mutations,
21 caught, 4 equivalent, 0 unexplained), written up in
`docs/formats/car-graph.md`.

Four things about it are worth carrying forward.

### `1e-6f` and `9.99999997e-07f` are the same float, so one mutation was a no-op

The epsilon `Graph::GetValue` compares `|dx|` against is
`lwc1 $f6,-30256(gp)` with `_gp` at `0x00328bf0` -- `0x003215c0`, holding
`0x358637bd`. The first mutation written against it replaced the
spelled-out `9.99999997e-07f` in the header with `1e-6f`, which is the
obvious way to write the same number and rounds to the same bits. It
survived, and it had to: it changed nothing. The tally would have read
"1 unexplained" forever while the test was sound.

**A float mutation has to be checked as bits, not as source text.** It was
rewritten as one ulp up -- `1.00000011e-06f`, `0x358637be` -- and killed by
a fixture whose `dx` is exactly that value.

### A prerequisite that was already ported, found by grepping the wrong name

`CarState::WorldToCar` was the other half of this session's plan: 144
bytes at `0x001b6ab0`, plus a `bVector3` overload at `0x001b6b40`. It is
already in `carstate.c` -- both overloads, as `carstate_world_to_car2` and
`carstate_world_to_car3`, modelled in `carstate_check.py`, exercised by
three mutations, and documented. The `CarState` slice took it.

The plan called it outstanding because the reconnaissance was done with
`mipsdis.py --grep WorldToCar` against the ELF and never against the ported
tree, and a grep for `WorldToCar` does not find `carstate_world_to_car2`.
**Before porting anything a plan calls a prerequisite, grep the ported
sources for it under the name the port would have given it.** The port
renames on a rule -- `Class::Method` becomes `class_method` -- so the
search that answers the question is for the snake-case name, or for the
PS2 address, which every ported function carries in a comment.

`DriveTarget::Dump` is still blocked, and always was: not on
`CarState::WorldToCar` but on `Car::WorldToCar` at `0x00138e90`, which is
two instructions -- `j CarState::WorldToCar` with `addiu a0,a0,64` in the
delay slot -- and still needs a `Car *` to take that `+64` of.

### A size assert that needed a round-up, not a slack constant

Every record so far has asserted its size as `PS2 size + (sizeof(void *) -
4)` per widened pointer. `Graph` is the first where that is wrong. It is a
pointer followed by an `int32_t`: on a 64-bit host the pointer forces
eight-byte alignment on the whole record, so the `int32_t` is followed by
four bytes of *tail* padding and `sizeof` comes out 16, not 12. The assert
now states the size as a round-up to `sizeof(void *)` and checks the two
offsets directly, which is what the claim was really about. Expect this
again for any record whose last field is narrower than a pointer.

### Two survivors that are dead code, and the argument that says so

`GetValue`'s walk is followed by `return p[0].y`, and two mutations reach
it. The return is unreachable, and it takes an argument rather than a
fixture to say so: past the low early-out `x > p[0].x`, so `p[i].x <= x`
holds at `i == 0`; past the high one `p[n-1].x > x`, so it fails at
`i == n-1`. A predicate true at one end and false at the other flips
somewhere between, and that flip *is* the bracket the loop tests for. So
the loop always returns at or before `i == n - 2`, in any array, sorted or
not. There is no NaN to escape with either -- the EE's FPU has none.

The third survivor, `gr-low-strict`, was **not** equivalent, and nearly
looked it. Making `x <= p[0].x` strict changes no answer on an ordinary
curve: the early-out stops firing, the walk lands on segment 0 with a zero
numerator, and the divide returns `p[0].y` anyway. It takes a duplicate x
at the *front* of the array, sampled exactly on it, to separate them --
segment 0's right edge is then the same x, `x < p[1].x` fails, and the walk
answers off segment 1 instead. **An early-out that a later path happens to
reproduce is not redundant; it is untested.**


## Car: the record, and the eighteen methods that need nothing else

`Car` is the hub of task 25 and not its physics. Eighty methods, 22876
bytes, a 2016-byte record -- but the simulation lives in the movers that
`SetMovementMode` constructs. Car owns the state they write into, the
lights, the horn, the wipers, the blown tyres and the blinking, and hands
everything else off.

The record is whole: `car.h`, 72 offsets, each re-derived from a load or a
store before it was written down, and through the ARM build where every
`CAR_SLACK` term is zero and `CAR_AT(f, n, k)` collapses to the console's
raw offset. Eighteen methods are ported: the seventeen that reach nothing
outside Car, CarState and the two world clocks, plus the eight-byte
`Car::WorldToCar`. 20 scenarios, 1871 lines, 0 differ; 82 mutations, 78
caught, 4 equivalent, 0 unexplained. Write-up in `docs/formats/car.md`.

Six things below are worth carrying forward; three of them are about the
verification rather than about Car.

### `cvt.w.s` saturates by the sign of the source, and a C cast does not

`CalculateDebugChecksum` is four instructions -- add x to y, scale by
65536, convert, return -- and it was the one function in the slice whose
first transcript did not match. Fifty lines differed, all of them at the
ends of the range.

Truncation toward zero is the easy half and a cast does it. The other half
is what happens off the ends:

```
                          above 2^31    below -2^31
R5900   cvt.w.s           0x7fffffff    0x80000000
ARM     vcvt.s32.f32      0x7fffffff    0x80000000
x86-64  cvttss2si         0x80000000    0x80000000
```

ARM agrees with the console. The host does not, and the C conversion is
undefined behaviour on all three besides. So the port spells it out --
`car_trunc_w`, which is `camera_check.py`'s model function moved to the
source side, where the camera slice had written it as a model two slices
ago and nobody had needed it in C yet.

**Where a port casts a float to an int, ask what the three targets do off
the ends before trusting the cast.** There will be more of these: every
`cvt.w.s` in the remaining 122 functions has the same question behind it.

Two of the four surviving mutations are here, and the second is the
interesting one. Deleting the *negative* arm changes nothing on any of the
three targets -- x86 already returns `0x80000000` below range, and the
other two agree with the arm. What the arm buys is not a different answer
but a defined one. That is a real equivalence and it is recorded as one,
with the reason spelled out rather than the label alone.

### A comment that was wrong, found by a mutation that could not fail

`car.c` said the tick was written as a literal because `1.0f / 4000.0f`
rounds to `0x3983126e`, one ulp below the image's `0x3983126f`.

It does not. The correctly-rounded float32 of 1/4000 *is* `0x3983126f` --
the two spellings are the same word. The mutation that swapped them
survived against a clean transcript, and it survived because there was
nothing to catch: it was a no-op. That is what exposed the comment.

This is the Graph slice's lesson arriving from the other side. There it was
`1e-6f` and `9.99999997e-07f` being the same float, so the mutation was
worthless. Here the same fact made the mutation *informative* -- a no-op
mutation that survives is telling you something about the source when the
source claims the two are different.

The word that genuinely differs, `0x3983126e`, was not separated by any
fixture either: everything in the slice compared far enough from a
boundary that one ulp of tick changed no answer. Two scenarios were added
that do. 4000 ticks of the correct word is exactly `1.0f`, so
`IsBlinking`'s `elapsed < duration` with a duration of `1.0f` answers no on
the right word and yes on the wrong one; the honk's `cycle < elapsed` falls
the other way round, which is deliberate, since the two call sites read the
constant from different `gp` displacements and the port asserts they are
one constant.

### A fixture that could not see its own mutation

`stub-event-writes` makes `EventHandler` secretly set `bPoofed = 1`. It
survived the first pass -- and not because the scenario was weak. The
`[stubs]` scenario snapshots all 2016 bytes, calls the three stubs, and
counts changed bytes. It is exactly the right shape.

The fixture had set `bPoofed = 1` itself before snapshotting. The write
stored the value that was already there.

**A no-op fixture value is a blind spot, and only a mutation finds it.**
The fixture now seeds 2 into the three fields the three stub mutations
write. Worth checking wherever a scenario's assertion is "nothing changed":
the fixture has to be hostile to the change it is meant to detect.

### Padding asserted by offset is not asserted

`_hole56` is eight bytes between `pDynamicCollisionBody` and `State`.
Shortening it to four and rebuilding on the host changes nothing at all --
`CarState` is eight-byte aligned here, so the compiler pads the gap
straight back and every offset still holds, `State` included.

On ARM the alignment is four and the same edit slides the entire record
from `State` onwards. The mutation found the gap; the seven holes now carry
`sizeof` asserts as well as offset asserts, and the host build says so too.

### "Makes no call outside the class" is not "can be written today"

Thirty-four of the eighty make no outside call, and the reconnaissance said
so plainly -- the count is of `jal` targets, so a method whose only calls
are to other Car methods lands there even when one of *those* is blocked.
Read carelessly that number looks like a work estimate. It is not.

It partitions 17 + 10 + 7: seventeen written, ten that do nothing but
dispatch through a driver, controller or mover vtable, seven whose callees
reach a task 26/27 class. The partition is at the bottom of `car.c` and the
arithmetic is made to close on purpose -- 17 + 10 + 7 = 34 is the check
that the three groups do not overlap, which a list of names alone would not
give.

`car.h` and `car.c` first said thirty-one and nine. Both were wrong, and
the recon file had the right number the whole time; the error was in the
transcription, not the measurement.

### A plan's "blocked on" list decays. The sources do not.

Last session's entry recorded that `CarState::WorldToCar`, listed as a
prerequisite, had already been ported by the CarState slice -- and drew the
lesson about grepping the ported sources under the port's naming convention
rather than the ELF's.

The line immediately after it, in both `CONTINUE.md` and `TASKS.md`, said
`DriveTarget::Dump` was still blocked on `Car::WorldToCar`. It was not.
`drivetarget_dump` has been in `drivetarget.c` since the DriveTarget slice
and reaches the transform the way the forwarder would --
`carstate_world_to_car2(&car->State, ...)`, which is the `+64` written out
-- and `docs/formats/car-drive-target.md` said so at the time, in a section
headed "Dump prints nothing and is still observable".

So the same correction had to be made twice in two sessions, one line
apart, and the second time the *format doc* had been right all along while
both planning documents were stale. **Check the source before believing the
plan, including when the plan is this file.** DriveTarget has two blocked
methods and always had two.

`Car::WorldToCar` is ported now regardless -- it is one of the eighty and
it is `j CarState::WorldToCar; addiu a0,a0,64`, a tail call with the
embedded CarState's address. Its six fixtures print `MatrixValid` next to
the transformed point, because that flag is what makes the *offset*
observable: `GetTransformMatrix` sets it on whichever CarState it was
handed, so a forwarder passing the wrong address would leave the flag at
Car+64 clear even if the numbers happened to agree. The transform itself is
reused from `carstate_check`'s model rather than restated, since restating
it would test the file against itself.

### The stand-in is gone

`drivetarget.h` carried a stand-in `Car` -- ten bytes of padding,
`DriverNumber`, `pPlayer` and the embedded `CarState` -- inside its own
`#ifndef CAR_H`. It includes `car.h` now.

Two consequences, both handled. The include-ordering rule `car.h`'s header
describes is retired: while the stand-in existed, including drivetarget.h
first would define `CAR_H` with the stand-in and `car.h` would then vanish
into its own guard silently, which is why `car.h` declares
`typedef struct Car Car;` above its own includes. And `drivetarget_check`'s
`[layout]` scenario changed, because the stand-in's padding had been
written to cancel the host's pointer slack and the real record does not:
the three offsets read 18, 48 and 112 on this host, which is
`CAR_AT(DriverNumber, 10, 2)`, `CAR_AT(pPlayer, 24, 6)` and
`CAR_AT(State, 64, 12)`. On ARM they are 10, 24 and 64 again. The two
mutations that used to aim at the stand-in now aim at `car.h`, which is
strictly better coverage -- that is the header the game is built from.

### The include cycle the stand-in had been hiding

With the stand-in gone, `cardriver_check` stopped compiling:
`unknown type name 'CarDriver'`. `cardriver.h` includes `drivetarget.h`,
which now includes `car.h`, which included `cardriver.h` -- a cycle. In
`cardriver.c` the outer `CARDRIVER_H` guard is already set when `car.h`
asks for it, so the inner include is empty and `struct Car` reaches
`CarDriver *pCarDriver` before `CarDriver` exists.

Car holds both `CarDriver` and `CarTypeInfo` by pointer only, so `car.h`
now names them (`typedef struct CarDriver CarDriver;`) and includes
neither. `car.c` and `car_test.c` include `cardriver.h` themselves, for
`pCarDriver->Steering`. The ordering paragraph at the top of `car.h` is
gone too; nothing depends on include order any more.

### Where the next slice starts

The vtable seam plus `SetMovementMode`'s jump table. It unblocks ten
methods at once and it is where `wheel_install_seams()` finally belongs --
the `MM_PHYSICS` arm is what constructs the `PhysicsCar` that owns the
`Suspension` and the four `Wheel`s, and the call has to happen before that
car's first `ResolveForces` or every corner reports airborne.

38.0 KB across 122 functions left in task 25: the rest of `Car` (62
methods, 21912 B), `PhysicsCar` (16 / 8496), `Mellovator` (31 / 5420),
`MellowMover` (13 / 3096). The eighteen ported are 964 B of 22876, because
the cheap ones went first.

## The mutant a stopped run left behind, and the restore that added a CR

Two faults in the mutation runners, found in one sitting, neither in the
port.

### `sr-count-signed` spent a session inside `drivetarget.c`

The DriveTarget pass that was stopped so `car.h` could be edited was
stopped with a mutant in place. The runners restore the original in a
`finally`, and a killed process does not run its `finally`. The check made
at the time for a stranded mutant missed it.

It hid well. `sr-count-signed` swaps the image's `lbu` for a signed read of
`NumPoints`, and it is one of the recorded equivalents -- so every plain
run of `drivetarget_check` stayed at 0 differ with the mutant compiled in.
What found it was the next `--mutate`: `1 PATTERN NOT FOUND`, because the
text the mutation looks for was no longer in the file. The disassembly
settled which line was the original (`lbu v1,0(t2); addu v1,v1,t6` at
`0x0020a524`), and the line is back.

**The PATTERN NOT FOUND guard is the only thing that sees an equivalent
mutant stranded in a source.** A plain run cannot, by definition.

### `camera_check` and `trackroute_check` doubled every CR

Every line of `camera.c`, `cammover.c` and `trackroute.c` ended in
`CR CR LF`. Those two runners read the original with `newline=""` -- which
keeps CRLF intact, correctly -- and then wrote it back with Python's
default translating write, which turns each LF into CRLF on Windows. The
restore itself was the corruption, one extra CR per line per pass.

The compilers accepted it -- host and ARM builds both passed -- which is
why nothing failed. `git diff` did not -- 1427 lines "changed" across the
three files. After collapsing `CR CR LF` to `CR LF`, all three are
byte-identical to HEAD, so no real edit was lost or hidden. Two stray
`CR CR LF`s in `drivetarget_check.py`, from my own patches last session,
were fixed the same way. A scan of the source, tools, docs and planning
files finds none left.

### One `write_source` for all sixteen runners

Sixteen checkers each carried their own copy of `write_source`, and it
differed in exactly the way that mattered. Now each one is
`write_source = hostbuild.write_source`, which:

- always writes with `newline=""`;
- keeps the OneDrive `EINVAL` retry;
- before the first write a process makes to a file, parks the file's
  current bytes beside it as `<name>.<pid>.mutate-backup` (gitignored), and
  removes that when a write puts those bytes back;
- exits rather than write to a file another *live* process has parked --
  two passes over one file would each restore the other's mutant.

`hostbuild.build()`, which every checker calls before it runs anything,
restores any backup whose process has died and says so on stderr. For a
live one it warns, because a build that includes that file will see the
mutant. The liveness check is `OpenProcess` / `GetExitCodeProcess` on
Windows and not `os.kill(pid, 0)`, which on Windows is `CTRL_C_EVENT`.

Tested by hand: a child writes a mutant and hard-exits with `os._exit`, and
the next `recover()` restores a mixed CRLF/LF original byte-exact; a second
writer is refused while the first owner is alive; the owner's own restore
leaves no backup behind. `bslotpool_mutate.py` and `geometry_mutate.py`
keep their older pid-less `.mutate-backup` scheme, and the scan skips it.

**Rules that still stand:** never edit a source a live pass compiles, and
never run two passes that mutate the same file at once. `car_check` and
`drivetarget_check` both mutate `car.h` now, so they run one after the
other.

## Session 25 (2026-09-22) -- Task 25, Car's second slice, and four initialisers nothing ran

Car's second code slice is closed: the vtable seam, the nine methods that
are pure dispatch through it, the three fields Car borrows from other
classes, the draft, and `_GLOBAL_$I$fDraftFalloff`. Fourteen methods, which
makes thirty-two of Car's eighty and 2316 of its 22876 bytes. 42 scenarios,
3864 lines, 0 differ; 178 mutations, 169 caught, 9 equivalent, 0 unexplained. Write-up in `docs/formats/car.md`, which
has the details; what is worth carrying forward is below.

### The vtable seam is a registry keyed by the image's own address

The port has always stored each vptr as the image's address, in a
`uint32_t` at the image's offset. `vtable.{c,h}` adds the other half: a
map from that address to the port's `{int16 delta, int16 index, fn}`
entries. A call site is then the image's four instructions written out --
`vt_slot(obj->_vtable, S)`, then `vt_this(obj, e)` -- and a harness can
install a recording table *at the real address* and see which slot was
taken, with which adjustment, in which order. `car_test.c` gives every
class a table with delta 0 and one with a nonzero delta, and every fake
prints its `this` as `<fixture>+<offset>`, so a dispatcher that drops the
delta shows as `ctl+0` against the model's `ctl+4`.

`vt_slot` never returns NULL: a vptr nobody installed, a misaligned slot,
slot 0, a negative slot, a slot past the end and an empty entry each abort
with a message, and `vt_install` aborts past 96 tables. Each refusal runs
as its own process under `car_check`, message included.

**The deltas in a real table are port data.** A delta is the distance
between two bases, and the host's slack moves bases, so a class that
installs a real table computes its deltas with `offsetof` rather than
copying the image's `lh` values.

### Four static initialisers had been ported and never run

Car's, RigidBody's, Wheel's and DriveTarget's `*_static_init` all existed.
Nothing called any of them. On hardware the rigid body's two damping
Tables, the wheel's cornering-force and seven load-sensitivity Tables, the
draft's Table and Graph, and `DriveTargetMinDistanceToPointSquared` would
all have been zero the first time the physics read them.
The image never has the problem: `main+0x14` calls `__main`, which walks
`__CTOR_LIST__` (`0x00314f78`, 109 entries) forwards before `main` does
anything of its own.

`sinit.{c,h}` is that walk over the ported entries, in list order --
`[14]` Car, `[41]` RigidBody, `[44]` Wheel, `[87]` DriveTarget, `[103]` the
slot-pool manager -- and `main.c` calls `sinit_run()` where it used to call
`bSlotPoolManagerInit()` alone. `tools/sinit_check.py` reads the calls'
comments and holds each to its list entry and its symbol, requires the
indices to increase and each function's own source to cite the same
address, and fails if any `*_static_init` defined anywhere is not called
exactly once. Six mutations, six caught -- including one that comments out
the call in `main.c`, which survived until the check stopped counting
comments.

**The walk corrected an address.** `main.c`, this file and `TASKS.md` all
credited the manager to `_GLOBAL_$I$` at `0x00240070`. That is the `$D$`
beside it. The constructor is `_GLOBAL_$I$bNewSlotPool__FiiPCci` at
`0x00240080`, entry 103 -- so on the console the manager is built *after*
the physics tables, and the walk keeps that order. All three citations
are fixed.

### The static initialiser is run, not transcribed

`car_check` runs `_GLOBAL_$I$fDraftFalloff` in `mipsemu`, the Table and
Graph constructors included, and diffs every word it leaves against what
`car_static_init` leaves. The run showed two things a transcription would
have got wrong: the initialiser never stores an `ObjectPoints` pad lane,
and the road-noise knees are the image's `1.388889f` and `13.888889f`, not
what `5 / 3.6f` rounds to.

### The draft: a redundant test, and a NaN the console cannot make

The slowest-leader test (`speed < vDraftSpeedRange[1].x`) is redundant:
the speed Graph is 0 at every speed up to 1.0, so a leader that slips past
it divides by zero, the Table clamps `+inf` to its last entry, and that is
0 -- the early return's answer. Two mutations of the test are equivalent
for that reason, and `f <= 0` for `f < 0` is a third.

Two cars at exactly the same position make `dot / dist` 0 / 0. The EE's
FPU has no NaN, so the console carries on with large finite numbers; the
port is IEEE, and the NaN reaches `table_get_value`'s `(int32_t)` cast --
0 on ARM, a draft of NaN that the sum then turns into the cap, and
`0x80000000` on x86, an index far outside the table. No fixture builds it.
Whether two cars can ever share a position is task 26's question, because
task 26 owns spawning.

### Five survivors, all of them fixtures

The first pass left five mutants alive, and none of them was equivalent:

- **The reach, as `<=` and as 150.** The draft past 60 looks as if it is
  always 0, because `f * g` is at most 60. That holds only in exact
  arithmetic: `dot / dist` can round above 1, and then a leader exactly 60
  away keeps 3.7e-6 of draft. No single-axis fixture can produce that,
  since `sqrtf(a * a)` is `|a|` again when both roundings are correct --
  which is why the existing fixtures at 60 and 60.0001, all along x, never
  could. The two diagonal cases were found by searching the model.
- **`len2` and `dot`, regrouped.** Every fixture's sums rounded the same
  under either grouping. There is now one case with three awkward
  components for each.
- **The sum counting `c`.** `c` stood still in every world, and a car
  below the knee adds exactly 0. It moves at 30 now, which the sum never
  reads. A sum that counts `c` drafts from itself -- 0 / 0 -- and crashes
  the host harness. That crash is the only way to catch it.

**A fixture at a boundary is not a boundary test until you check that the
boundary can be reached from it.** The 60 and 60.0001 fixtures were right
at the reach, and still could not see the reach.

### A layout assert only the host could see was wrong

`CarCollisionBody`'s assert put `pCar` nine slacks past the console
offset, on the reasoning that `DynamicCollisionBody` was already a multiple
of eight on the host. It is 292, and a pointer's alignment rounds it to
296, so the right count is ten. On ARM every slack is 0, and both readings
agree there.

### The 34/46 split, remeasured

It is over all eighty, and seventy-four of the eighty are in `Car.obj`;
the other six (`WorldToCar` and `PrintAbove` among them) were emitted in
other objects. A rescan for any `jal`, or `j` out of the body, to a non-Car
symbol gives the same 34 and 46, with `WorldToCar` in the 46. So thirty of
the thirty-four are ported and two of the forty-six. `car.c`'s closing
note had called `WorldToCar` "outside the eighty"; it is fixed.

### Where the next slice starts

Six methods whose outside callees are all ported: `IsCarToLeft` and
`IsCarToRight` (`CarState::WorldToCar`), `GetRelativeCarPosition`
(`bNormalize2`), `GetPostCollisionYawControlBoost` (`Graph::GetValue`),
`IsDrifting` (`CarState::GetYaw`) and `ComputeFakeRPM` (`smooth<float>`, a
52-byte template inside `Car.obj`). With them comes `IsCarInFront`, whose
one callee `bToPolar` (`0x002424a0`) the math library has not ported yet.
Then `SetMovementMode` / `SetControlMode` with `PhysicsCar`, which carries
`SetToPhysicsMode`, `SetFrictionBoost` and the `wheel_install_seams()`
call.

36.7 KB across 108 functions left in task 25: the rest of `Car` (48 /
20560), `PhysicsCar` (16 / 8496), `Mellovator` (31 / 5420), `MellowMover`
(13 / 3096).

## Session 25, continued -- Car's third slice, and a function the math library only said it had

Car's third code slice is closed: `IsCarToLeft`, `IsCarToRight`,
`GetRelativeCarPosition`, `IsCarInFront`, `GetPostCollisionYawControlBoost`,
`IsDrifting` and `ComputeFakeRPM`, with the `smooth<float>` template it
calls. Seven methods, 1304 bytes, which makes thirty-nine of Car's eighty
and 3620 of its 22876 bytes. 58 scenarios, 4238
lines, 0 differ; 254 mutations, 238 caught, 16 equivalent, 0
unexplained. Write-up in
`docs/formats/car.md`, "What is in the third code slice".

### `bToPolar` had been documented as ported and never written

`docs/formats/bmath.md` listed `bMath.obj` as nineteen functions, all
ported, and `bmath_check` as covering them. `bmath.c` had eighteen.
`bToPolar` (`0x002424a0`) was decoded, written up, and missing, and nothing
noticed because nothing called it until `IsCarInFront`. It is in `bmath.c`
now with a `topolar` scenario -- a 17x17 grid, twelve long legs and six
awkward pairs in all four quadrants -- and `bmath_check` has a kept
`--mutate` pass for it, 9 mutations, 9 caught. The document's claim is
corrected.

**A table in a document that says "all" is a claim, not a check.** The
next time a module's document says every function is ported, grep the
source for each address.

### What the slice found in the image

- **The drift threshold is not symmetric.** 1356 BAM is the first drifting
  yaw one way and 1357 the other, because `GetYaw`'s fold subtracts 2 pi
  in float32 and the `sub.s` rounds 64180 to -0.12999964. The first
  fixture had 64180 and 64181 and so never saw the negative side's
  boundary; it has 64179 now.
- **`ComputeFakeRPM` reads past its table.** The band from 80 to 89.51
  reads pair 6 of six, which is `PostCollisionYawControlProfileData[0]`,
  (0, 0) -- so from 80 up the fake RPM heads for 0 at 50 a call. Pair 1 is
  never read at all. The port names the overread element and `car_check`
  asserts the adjacency from the symbol table.
- **Two tests cannot be seen as shipped.** The yaw boost's four-second
  cutoff sits past the profile's last knee, where it is 0 anyway, and a
  stamp in the future lands before its first knee, also 0. The Graph
  aliases a writable array, so the fixture pokes it -- a knee at 8 s, a
  first value of 0.125 -- and both show.
- **`GetRelativeCarPosition` uses the velocity, not the heading,** so a
  stopped car measures along world x, and `IsCarInFront` treats a car at
  the same position as a quarter-turn left, because `bATan(0, 0)` is 16384.

### Fixtures, again

Three weak fixtures were found by reading the transcript, before the
mutation pass had a chance to: no negative-side drift boundary, no speed
below -25.38 to exercise the reverse clamp, and an `IsCarInFront` pass
off the origin whose other cars were all behind the car. Each has a case
now.

The pass then caught sixty-nine of the seventy-six new mutations on its
first run and left seven, every one of them predicted and written into
`EQUIVALENT` before the run with its reason: a negated product, a turn
measured backwards, the 0.13 boundary no yaw reaches, `GetYaw`'s gate
under the test against 12, a clamp that stores what is already there,
a loop pass the branch above rules out, and the smoothing's start point
when `TestRPM` throws the result away. `car.md` has the table.

### Where the next slice starts

`SetMovementMode` is a seven-way jump table (`0x00292200`): `NullMover`,
`PhysicsCar`, `TrafficCar`, `DeliveryMover`, `MellowMover`, `CopMover`,
`BeltMover`. Four of those are task 26's. `PhysicsCar` needs two classes
the task-25 count never included: `PhysicsSystem` (`0x00192460`, the
integrator the components hang from) and `Aerodynamics` (`0x001a4b58`).
Its constructor builds a RigidBody, a `TwoWheelAckermanSteering`, four
Wheels and four Suspensions, an Engine, a DriveTrain and the Aerodynamics,
adds each to the system, then runs `Calibrate`, `InitializeStateFromCar`
and `ComputeAuxiliaries`. `Move` alone is 3900 bytes.

35.4 KB across 101 functions left in task 25: the rest of `Car` (41 /
19256), `PhysicsCar` (16 / 8496), `Mellovator` (31 / 5420), `MellowMover`
(13 / 3096) -- plus `PhysicsSystem` and `Aerodynamics`, about 1.9 KB more.

## Session 26 (2026-09-22) -- Task 25, PhysicsSystem and Aerodynamics, the two classes the count never had

The two classes `PhysicsCar`'s constructor needs and task 25's function
count had left out are ported and checked. Each has a harness, a model
written from the listing, a mutation pass and a document:

```
physicssystem_check  12 scenarios, 739 lines, 0 differ   62 mutations, 61 caught, 1 equivalent
aerodynamics_check    7 scenarios, 107 lines, 0 differ   74 mutations, 74 caught
```

Both documents are new: `docs/formats/physics-system.md` and
`docs/formats/aerodynamics.md`. The full list -- twenty-nine checkers
and both table generators -- passes, and the CIA builds.

### PhysicsSystem, the ticker, and p32

`PhysicsSystem.obj` is a list of PhysicsComponents and a running total of
their state sizes. It came with two things it needed:

- **`bticker.{c,h}`**, the EE clock the system times `ComputeAuxiliaries`
  with. **`bGetTickerDifference` divides by 300 MHz** rather than the
  EE's 294.912, so every millisecond the game measures is 1.7% short;
  kept. The unsigned difference is converted in two steps because
  `cvt.s.w` is signed. The one equivalent mutant replaces that with a
  direct unsigned conversion. The two are equal, and that was checked
  over 723,967 values rather than argued.
- **`p32.{c,h}`**, a registry that lets a 32-bit link slot hold a
  pointer on the 64-bit host. On the 3DS it is two casts. The point is
  that the list walk the checker runs is the same code the handheld
  runs, and every component record still has the image's offsets.

What the listing fixed, and the shape of the code did not:

- **IntegrateEuler is the only integrator the game runs.** PhysicsCar,
  MellowMover and Smokeable all call it. IntegrateRungeKutta is a textbook
  RK4 -- h = dt/2, so the weights are 1/3, 2/3, 1/3, 1/6 -- with no caller
  in the image. Ported anyway.
- **The walk calls the slot, then asks the size, then reads the next
  link.** A component that resizes itself or splices in a node during
  the call is seen doing it. The fake components in the harness
  misbehave on request, so each of those orders is in the transcript.
- **A PhysicsSystem owns its components.** Its destructor destroys every
  one of them with flags 3, then frees itself if asked. Anything that
  also frees a component frees it twice.
- **`AuxTime` is written and never read.** The store is the only
  reference in the image.
- **AddComponent reads `Size` after `GetSize` returns**, so a `GetSize`
  that moves `Size` keeps its move.

The first run had 0 differing lines. The mutation pass is what showed
the diff could fail.

### Aerodynamics

Drag and two downforces, with no state and no vtable. Three findings:

- **The downforce is linear in speed**, not quadratic; only the drag
  multiplies s by the velocity again.
- **The "direction" is not a unit vector unless Boost is 1.** ResolveForces
  divides the velocity by s, and s is the speed over Boost.
- **The drag's application point has an uninitialised w.** It flows into
  `MomentAccumulator.w`, which nothing reads. The port zeroes it, the way
  RigidBody's port zeroes the accumulators' own w lanes. This is the one
  deviation, and it is written down in both the header and the document.

**`ApplyForceInFrame` had no checker until this one.** It is two
`bMulMatrixVector` calls, the first an eight-byte `j` thunk to
`bMulMatrixVec3`, followed by `ApplyForce`. That is now modelled from
`0x00193170`, and five of the mutations are in `rigidbody.c` and
`bmatrix.c` on its account. **`SetGroundEffect` was missing from the
port**, although the other three setters were there. It is in now,
with a harness line and a mutation.

### Fixtures, again

One hole was found by reading the transcript, before any mutation ran.
`at-floor` and `over-floor` printed identical lines, because both
velocities lay along x, where the default direction (1, 0, 0) and the
real one coincide. Both cases move along y now.

The first mutation pass left two survivors:

- `dot-bracket` survived because no velocity had squares that round
  differently when grouped the other way. The fix came from a search of
  the model over one-decimal velocities, which found (15, 4.3, 0.7).
- `sdata-height` was a no-op: `-0.1f` is the same float as the image's
  `-0.100000001f`.

**A mutation that writes the value already there is not a mutation.**
Before writing a float constant into a mutant, check its bits against
the image's.

### What PhysicsCar needs next

**No component class installs its vtable.** Every caller so far has
called `rigidbody_*`, `wheel_*` and the others directly, and the records
carry the image's vptr values only as numbers. The first
`physicssystem_add_component` given a real RigidBody therefore aborts in
`vt_slot`. The tables are `_vt$9RigidBody` `0x002987e8`, `_vt$5Wheel`
`0x00298f20`, `_vt$10Suspension` `0x00298fb0`, `_vt$6Engine` `0x00297a78`
and `_vt$10DriveTrain` `0x00297a30`, plus the steering's `0x00298ff8`
and `0x00299018`. Those come first, each held to the image's entries by
its own checker.

`PhysicsCar` is 116 bytes: `CarMover` at 0, a `PhysicsVehicle` (itself
a `PhysicsSystem`) at 8, then eleven pointers and seven scalars. It has
two vtables, `0x00292708` and `0x002926e8`. The constructor, the
destructor and `Move` are dumped from the ELF, ready to read.

## Session 26, continued -- the component vtables, destructors and pools

The seven component tables are installed, so the first real
`physicssystem_add_component` no longer aborts in `vt_slot`. With them
came everything else the image gives each class as an object: its
destructor, its operator new and delete, and the slot pool behind them.
All of it is in `3DS Files/source/physcomp.{c,h}`, and the per-class
`.c` files are untouched except `engine.c`, whose init stores
`_vt$6Engine` now.

```
physcomp_check   8 scenarios, 239 lines, 0 differ   46 mutations, 45 caught, 1 equivalent
```

`docs/formats/physics-components.md` is new. The full list -- thirty
checkers and both table generators -- passes, and the CIA builds.

### What the listing fixed

- **Every pool starts with flags 15, so every new component is zeroed.**
  `bOMalloc` is `SlotPool::Malloc`, the full path, and it clears the
  slot. The harness dirties each pool's first slot before the news to
  prove it.
- **A destroyed component carries PhysicsComponent's vptr**, and a
  destroyed Ackerman carries Steering's, because each destructor stores
  its base's table on the way down. The harness reads the vptr back from
  the freed slot, which keeps everything except the free list's link.
- **`~Engine`'s own store is dead.** The base overwrites it with no
  virtual call in between. Kept, and listed as the one equivalent.
- **`~SkidMaker` is `MakeNoSkid`**: it tells its `SkidSet` it is
  finished and stores nothing. The set is not ported, so the call goes
  through `gSkidSetFinishedAddingFn`, and a wheel that never got a set
  never reaches it.
- **RigidBody's GetSize is 32 but its array copies move 29 floats.**
  PhysicsSystem still allots 32, so three derivative slots are never
  written by the copies.
- **The RigidBody pool is n + 32.** Three constructors draw on it --
  PhysicsCar's, MellowMover's and Smokeable's -- and a car is one or the
  other, so the 32 are the Smokeables'.
- **Aerodynamics has a delete but no new.** PhysicsCar's and
  MellowMover's constructors inline the `bOMalloc`; the port gives them
  `aerodynamics_new`.
- **The slot size is rounded up to 4** by `NewSlotPool`, which is why
  the harness prints `sizeof` for each pool rather than a number: on the
  host the records are wider and the round is the same.

### Fixtures, again

Two survivors on the first pass, both the harness's fault:

- `dt-steering-no-fini`: the bare Steering test ran `~Steering` on an
  object whose vptr was already Steering's, so a destructor that forgot
  to store it looked right. The test now starts from Ackerman's table.
- `h-mellovator-size`: the harness printed every pool's slot size as a
  number, so a wrong constant for an unported class matched a wrong
  model. Ported pools print `sizeof` when the slot is the rounded
  `sizeof`, and the three unported ones are asserted against
  `physcomp.h` inside the model.

### Where PhysicsCar starts

The four tables are dumped: `_vt$8CarMover` `0x002923e0` (destructor,
a pure `Move`, `DoSnapshot`), `_vt$10PhysicsCar` `0x00292708`,
`_vt$10PhysicsCar$14PhysicsVehicle` `0x002926e8` (delta -8 on every
entry, the offset of the `PhysicsVehicle`), and `_vt$14PhysicsVehicle`
`0x00292728`. The constructor, the destructor and the fourteen methods
the constructor and `ResolveForces` need are read; `Move` is the second
slice, with its seams into force feedback, damage, skids and race mode.

## Session 27 (2026-09-23) -- Task 25, PhysicsCar and MellowMover, checked against the shipped code itself

`PhysicsCar.obj` is ported except `DoSnapshot`, which waits on the replay:
the constructor and destructor, the four tables, Calibrate,
ComputeAuxiliaries, BottomOut and the damping test, ResolveForces and the
five-pass IterateForces, UpdateCar, Move, the small methods and the static
initialiser. `3DS Files/source/physicscar.{c,h}` is new, and three small
modules Move reads came with it: `race.{c,h}` (GetRaceStage, the first word
of a Race), `cardamage.{c,h}` (BodyDamage::GetVisibleTotalDamage) and
`joystick.{c,h}` (the pad-type table and IsJoystickTypeWheel).

```
physicscar_check  106 scenarios, 102908 lines, 0 differ
                  263 mutations, 257 caught, 6 equivalent, 0 unexplained
```

`docs/formats/physics-car.md` is new. Every checker in the run-all line passes, thirty-two and both table generators, once physcomp_check was brought up to date: it still asserted the Mellovator's and MellowMover's slot-size constants, which are `sizeof` now. Its pass is 47 mutations, 46 caught, 1 equivalent, 0 unexplained, with two new mutants: the Mellovator's pool sized as a MellowMover, and NullMover's constant moved.

### The oracle is the image

Every other car class has a Python model written from the listing.
PhysicsCar is orchestration: which component is asked what, in which
order, with whose output. A model of that would be a second port of the
whole car, and would agree with the first for the same reasons the first
was wrong. So `physicscar_check` runs the shipped code. `mipsemu` loads
NFSHP2.ELF and runs the constructor, both integrators, UpdateCar, Move and
the direct calls from the instruction stream, including every component
method they reach, the VU0 macro code of the matrix library and the
soft-float doubles, on a Car and a RealDriver laid out in emulated memory.
The harness runs the port on the same records, and both print every field
of every object the car owns. The dump is generated from the port's
headers, and every offset is checked against the mdebug record first.

That took three things from mipsemu:

- **`Emu(ieee=True)`**: the scalar FPU in full, the VU0 macro-mode
  instructions the physics uses, and the four MMI ops bIdentity is made
  of. IEEE single, one rounding per operation, because the port runs on
  IEEE hardware and has to match the algorithm and its operation order,
  not the EE's round-toward-zero.
- **`Emu(eediv=True)`**: division by zero the EE's way (below).
- **`emu.hook(sym, fn)`**, which runs `fn` before an instruction and
  carries on. The model zeroes the image's uninitialised stack words with
  it, on the instruction before each is first read. There are six such
  places now (`physics-car.md` has the table), and the port writes zero
  in each.

The stand-ins are identical on both sides: the terrain, the allocator, the
ticker, the skids (MaybeMakeSkids logs its wheel and dt), and the race, a
zeroed block whose first word is the stage.

### What running the shipped code found

- **Wheel::GetLateralForce's curve scale is 12, not 11** (`lui
  at,0x4140`). The port and wheel_check's model had both read 11, so they
  agreed with each other and every tyre-curve index was 11/12 of the
  image's. The first sign was one ulp in a driven wheel's AppliedTorque
  in the constructor's dump. Fixed in `wheel.c` and the model, with a
  mutation.
- **Wheel::CheckTerrain refreshes the wheel's terrain.** The `move` read
  as a NULL terrain out-parameter is the *fifth* argument (raw word
  `0x0000402d`, rd = 8); `a2` arrives holding the wheel's own Terrain,
  and GetElevation writes through it. Port, model and stand-in all fixed;
  the stand-in writes 77 so a dropped pointer shows.
- **IntegrateEuler writes RigidBodyState's padding**: all 32 words of the
  body are advanced in place from a derivative array the body fills 29 of.
  The port's integrator now clears the array.
- **A car sitting in gear divides zero by zero.** DriveTrain splits the
  clutch torque by `w / (w + w')`, and a pair standing still -- including
  the front pair of any rear-drive car, which is split too -- is 0/0 every
  frame. The EE gives FLT_MAX, signed by the XOR of the signs, which the
  clamp turns into the small share. IEEE gives NaN, and every car on the
  grid would have gone NaN on its first frame. `eefpu.h` has `ee_div`,
  the port's two share divides use it, and drivetrain_check has an
  `ac still` scenario and a mutation for it. mipsemu's `eediv_pcs`
  records every `div.s` that takes the path; those two are the only ones
  the scenarios reach.
- **The Ackerman matrices are zero out of the constructor**, which frames
  the wheels from them, so a car already moving when it reaches its first
  Move has front wheels with no frame. The game's cars come to Move from
  rest. The scenarios start at speed, so both sides set the steering and
  run ComputeAuxiliaries once first.
- **One blown tyre cuts all four wheels' traction**: Move's per-wheel test
  is `(1 << i) != 0`, which always holds.
- **The joystick table is two bytes**, read with `lbu` and no bounds check.

### A mutation pass that took minutes a mutant

The first full pass ran at minutes a mutant. Each one rebuilt thirty-odd
sources it had not touched, then diffed 94,909 lines with difflib. A
mutant takes about 2 s now:

- **`hostbuild` caches objects.** Each source is compiled alone and kept
  in the system temp directory under a key made of the flags, the path,
  the bytes and every header in the tree, so a mutant rebuilds one file.
  The misses compile in parallel. drivetrain_check's build went from 6.2 s
  to 1.6 s warm. `HOSTBUILD_NO_CACHE=1` builds the old way.
- **The diff was the pass.** difflib over 94,909 lines takes minutes when
  a mutant moves a third of them. `diff_count` compares line for line
  when the lengths agree, which they do for nearly every mutant, and
  gives difflib only the trimmed middle otherwise.
- **A build that only links decides nothing.** hostbuild remembers
  whether a compile worked straight from the host's `cc` or needed
  msys2's shell. One pass's first build was all cache hits, so it only
  linked, which works outside msys2, and the mode was set to direct.
  Every mutant after it then failed to compile (no `<stddef.h>`) and was
  counted as caught. Only a build that compiled something sets the mode
  now, and that pass was run again.

### What the mutation pass found

The first pass left 16 of 263 alive. Six are equivalent, each checked in
the image, and ten were holes in the scenarios. `physics-car.md` has all
sixteen. Two are worth knowing before the next checker:

- **Locked and gripping is out of any scenario's reach.** By the first
  force pass, IntegrateEuler has moved the body on the constructor's
  derivative, so no contact patch is still. `s_lock` stills the patches
  by hand, one lock mask at a time, and calls IterateForces directly.
- **The first frame hides the yaw boost.** VelocityMagnitude is 0 until
  UpdateCar has run, so the collision boost was multiplied by zero in
  every scenario that had one.

`sinit_check`'s `swap-first-two` mutant swapped `car_static_init` with
`rigidbody_static_init`, the next line down. `physicscar_static_init` [15]
sits between them now, so the pattern stopped matching and the pass said
PATTERN NOT FOUND. It swaps [14] and [15] now.

### MellowMover and the Mellovator

`MellowMover.obj` (`0x00206448` .. `0x002086f8`) is ported except its two
DoSnapshots. `3DS Files/source/mellowmover.{c,h}` has the Mellovator's
methods and MellowMover's, the three tables at the image's addresses, and
`_GLOBAL_$I$MellowForceFeedbackGraph`. A MellowMover is the cheap car. A
RigidBody and a Mellovator share one PhysicsSystem, the Mellovator's state
is four wheel speeds, and the four Wheels are built only so the car can
render and skid.

```
mellowmover_check  39 scenarios, 56080 lines, 0 differ
                   346 mutations, 341 caught, 5 equivalent, 0 unexplained
```

`docs/formats/mellow-mover.md` is new. The checker runs the image, as
physicscar_check does, on PhysicsCar's four records plus three synthetic
ones.

- **The `.lit4` half-pi is `0x3fc90fdc`**, one ulp above the float nearest
  pi/2. It feeds `bSin`, which truncates to a BAM, so a heading a hair
  under a BAM boundary lands on it in the image, and the tyre forces go
  one BAM apart. The port's first BAM-to-radian constant was the same
  mistake the other way, a decimal a digit short. The checker now reads
  all eighteen pool constants back out and checks each against its
  literal and the comment beside it.
- **A level car in the air divides 0/0 in `bNormalize3To`**
  (`0x00240274`). JumpStabilizer's level moment normalises a zero vector
  to a zero length. The EE answers FLT_MAX, and the vector stays zero;
  IEEE answered NaN into the angular momentum, and the harness died in
  the first airborne scenario. `bvector.c` divides with `ee_div` now.
  `eediv_pcs` shows it and JumpStabilizer's own `vrsqrt` as the only
  divides by zero any scenario reaches.
- **The pools balance.** The Mellovator's and MellowMover's slot sizes
  are `sizeof` now, not image constants. `s_dtors` prints every pool
  after each destructor, and a freed Mellovator's slot still shows
  PhysicsComponent's vptr (`0x00298728`), since a freed slot keeps all
  but its first word.
- **The first pass left 28 of 346 alive**: five equivalent and 23 holes.
  The holes wanted three records the shipped data does not have: car 34
  for `FinalDrive[1]`, car 0 with CoG.y set, and car 0 with its droop
  stops at -2. They also wanted hand-set shift points, grip knee and
  slipping flags, a CarState that is not the Car's, and a frame under
  the suspension's 0.0001 s floor. The last took two tries. A car at
  rest has `p - old` of 0, so the floor cannot show until the car starts
  above its rest height.
- **In the game `State` is the Car's own CarState.** SetMovementMode's
  MELLOW_MOVEMENT arm, the constructor's only caller, passes `car + 64`.
  The port still reads each from where the image does.

### Where the next slice starts

Car's fourth slice: the movement and control modes. That is
`SetMovementMode` (`0x0012fd58`), `SetControlMode` (`0x0012fb50`),
`SetToPhysicsMode` (`0x0012ff68`) and `SetFrictionBoost` (`0x0012fd38`),
with the `wheel_install_seams()` call in the physics arm.

- **SetMovementMode's seven-way table** (`0x00292200`) builds, in
  MovementMode order, a NullMover, a PhysicsCar, a TrafficCar, a
  DeliveryMover, a MellowMover, a CopMover or a BeltMover.
- **NullMover** (`_vt$9NullMover`, `0x002923c0`, a 12-byte slot) comes
  with the slice. The four task 26 movers go behind a seam until then.
- **SetControlMode** wants the `CarController` base (`0x0029a6e0`),
  `NullController` (`0x00292350`) and `NullDriver` (`0x00292400`) the
  same way.

After that, task 25 is the rest of Car: 41 methods, 19256 bytes, most of
them reaching into tasks 26, 27 and 29.

## Session 28 (2026-09-23) -- Task 25 closed: the movement and control modes

Car's fourth code slice:

- **The four methods:** `SetMovementMode` (`0x0012fd58`),
  `SetControlMode` (`0x0012fb50`), `SetToPhysicsMode` (`0x0012ff68`) and
  `SetFrictionBoost` (`0x0012fd38`), 1092 bytes.
- **The small classes they build or reach:** `NullMover`,
  `NullController`, `NullDriver`, the `CarController` base, and
  `CarCollisionBody`'s `SetupPhysicsPointers` and `SetToPhysicsMode`.
- **The five vtables,** at the image's addresses.

New sources: `carmodes.{c,h}`, `carcontroller.c` and `collisionbody.c`;
the two headers were layouts before and gained the methods. `cardriver.c` gained NullDriver and both tables,
and `main.c` installs every table at boot and calls
`wheel_install_seams()`.

```
carmode_check      74 transitions, 27324 lines, 0 differ
                   114 mutations, 114 caught, 0 equivalent, 0 unexplained
cardriver_check    46 mutations, 45 caught, 1 equivalent, 0 unexplained
```

`docs/formats/car-modes.md` is new; `car.md`, `car-driver.md`,
`car-wheel.md` and `physics-components.md` are brought up to date. All
thirty-three checkers in the run-all line pass, with both table
generators, and the ARM build links and packs the CIA.

### The oracle is the image again

`carmode_check` borrows `mellowmover_check`'s machinery, and `mipsemu`
runs the shipped methods. The harness runs the port on the same records.

**The general heap is hooked on both sides.** Every allocation logs its
name, the image's size, its flags and its pool. A new block is filled
with 0xa5 and a freed one with 0xdd, and neither is reused. So
CarDriver's unwritten SportGear shows on both sides.

**The eight task-26 classes are stand-ins** at fixed table addresses.
Each logs what it is given and the two modes it finds on the car. That is
what makes the mode-before-arm store observable. A port that stored the
mode at the end would pass every check that looks only at the car
afterwards.

### Two survivors, and both were the dump not looking

- **`friction-mellow-too`:** a SetFrictionBoost that also stores into a
  MellowMover through the PhysicsCar type. PhysicsCar's FrictionBoost is
  at 108 and a MellowMover is 64 bytes, so the store lands in the next
  pool slot. No dump reaches a slot the car does not own. The friction
  scenario now compares the 128 bytes past the mover around each call.
- **`nc-dtor-driver-flags-1`:** NullController deleting its driver with 1
  instead of 3. The CarDriver hierarchy tests only bit 0, so on a
  NullDriver they are the same. A stand-in driver that logs its flags
  now shows the 3 the image passes.

### A broken build scored as nineteen catches

The first cardriver rerun reported its last nineteen mutants as "did not
compile (caught)", with no compiler output behind any of them. Run
again, all nineteen were caught on the transcript. The build environment
had failed, not the code -- most likely a locked file.

**`hostbuild` now raises `BuildEnvironmentError`** when a build fails
with no diagnostic. No checker catches it, so a pass stops instead of
scoring it. **A "did not compile" line is only a catch if a compiler
error sits above it.**

### Task 25 closes at the physics boundary

Forty-three of Car's eighty methods are ported, 4712 of 22876 bytes. The
other thirty-seven (18164 B) each reach a class another task owns:

- **The constructor** builds the car's sound (`CreatePlayerCarSound`,
  `espSetAttributeInt`), its render info, `CarDamage`, the
  `CarCollisionBody` and `PutFlatOnTrack`.
- **`Move`** goes through `UpdatePosition` (the sound object) and
  `ResetToRoutePoint`.
- **`BeginMovement`** reaches `TopologyCoordinate`.
- **`FinishMovement`** reaches `Collision`, the `Player`'s zones, `Race`
  and `ReplayManager`.

TASKS.md now lists every one under task 26, 27 or 29.

### Where the next slice starts

Task 26, the player's input: `Joystick.obj`, a generated
`ScannerConfigTable`, a 3DS backend where `ReadRegularController` was,
and `RealDriver`. CONTINUE.md has the addresses.

## Session 29 (2026-09-23) -- Task 26's first slice: the player's input

The first slice of task 26 is closed. It covers everything between the
3DS's buttons and CarDriver's input record: the joystick layer, a
generated `ScannerConfigTable`, a HID backend, and `RealDriver`.

### The joystick layer

- **`Joystick.obj`** is ported as `joyevent.{c,h}`: the event nodes, the
  eleven scanners, the queue and `GenerateJoyEvents`.
- **The pad ring** is `joypad.{c,h}`, and the joylog's two accessors are
  `joylog.{c,h}`.
- **The tables are generated.** `gen_scanner_tables.py` writes
  `scannertab.c` and `joyeventid.h` from the image and the stabs, and
  `--check`s they are current.
- **The 3DS pretends to be a DualShock 2.** `joyhid.{c,h}` builds the
  pad's 32-byte buffer from the HID, in pressure mode. The port reads as
  type 121, takes configuration 30, and every shipped row works as it is.
  Nothing in the joystick layer knows what a button is, which is what
  makes that possible.

`docs/formats/joystick.md` has the buffer, the rows, the scanners and the
3DS map.

```
joystick_check     64240 ops, 75891 lines, 0 differ
                   253 mutations, 250 caught, 3 equivalent, 0 unexplained
joyhid_check       every key and stick reaches its event
```

The mutation pass ran in two halves. The first stopped after 106 mutants
on a `BuildEnvironmentError`, a compile that failed with no diagnostic.
That is the guard added in Session 28 doing its job: the pass stopped
instead of scoring nineteen false catches. The other 139 ran with
`--only`. One survived: `da-p1-repeat-n`, in the DigitalAnalog scanner's
repeat. No script edge crossed that threshold from the side it tests, and
an edge loop now does.

The two type predicates are asked about all 256 type codes.
`DoesJoystickHaveStiffThrottle` (0x0011daf8) is new with RealDriver,
which is its only caller. It is true for types 83, 115 and 121.

### RealDriver

`RealDriver.obj` is ported but for `DoSnapshot`. That is 640 bytes and
twenty-five functions, plus the static constructor that builds its seven
steering Tables and `_vt$10RealDriver`. `table.c` gained
`Table::InverseLookup`, which only DoSteering calls. It is ported with its
quirk: an exact hit on the first entry answers the entry, not `MinArg`.

Fourteen calls go into other tasks' classes, through seams that do nothing
while NULL:

- the route editor's two hooks;
- the radial blur;
- the replay's event log;
- three Player methods;
- two `tCopManager` methods;
- `Car::ResetToRoutePoint`;
- the horn's sound.

None of them feeds the physics.

`realdriver_static_init` is `__CTOR_LIST__` [17] in `sinit.c`, and
`main.c` installs the table at boot. `docs/formats/real-driver.md` is new.

```
realdriver_check  152455 ops, 41163 lines, 0 differ
                  122 mutations, 118 caught, 4 equivalent, 0 unexplained
```

### The image is the oracle, with the seams on a mask

`realdriver_check` runs every RealDriver method but DoSnapshot in
mipsemu. It also runs, as shipped, everything those methods call that
the port has: the Tables, `GetYaw` and `bATan`, `GetRoute` and
`GetRoutePoint`, CarDriver's constructor and destructor, DriveTarget and
the vtable dispatch. The pad layer's five calls and the fourteen seams are
stubs that log.

- **The seam mask.** The image calls every seam unconditionally, and the
  port skips a NULL one. So the script carries a mask. A clear bit leaves
  the harness's pointer NULL and makes the model's stub silent,
  answering what the port's NULL case assumes. That puts the port's
  NULL branches under the same check as its calls.
- **Poison.** The model's Car, CarTypeInfo and Player are filled with
  0x55, and only the fields RealDriver should read are set. A field read
  by one side and not the other shows up as a difference.

### What reading the listing got wrong first

Four transcription errors were caught before the checker existed, by
reading each constant back to its pool entry:

- **Globals, not literals.** DoThrottleBrakeReverse's speed thresholds and
  DoSteering's `CounterSteerFadeStart`, `SteeringSpeed` and
  `SteeringReturnFactor` are `.sdata` globals.
- **The exception.** The 0.6 that latches reversing is a `.lit4` literal,
  even though a `BrakingSpeed` global with the same value sits beside it.
  Nothing reads that global.
- **NitroWasActive's limit** is `NitrousActiveTime`, not 4.0.
- **NitroActive tests validity** first.

**The route editor's hooks are live.** `MaybeAddTrackRoutePoint` and
`CancelTuningDrivingLines` looked like retail no-ops. But the editor is
built on every track load (`EndGameFlowLoadingTrackSpecific` →
`InitTrackRouteEditor`), so they are seams like the rest.

### Seven survivors, three of them real

- **`drive-order`.** Drive runs DoThrottleBrakeReverse and then
  DoSteering. The two share no state, so their order shows only in what
  each logs: the e-brake's replay event and the wheel query. No drive
  frame had the e-brake on. Directed frames now do.
- **`reset-cap`.** A `<=` in place of `min.s` differs only at a tie, and
  at a tie only in the sign of a zero. The reset now runs ±0.0 against a
  ∓0.0 cap.
- **`nitro-age-scale`.** At 4 s, any scale within a part in 16000 flips
  between the same two ticks. A 1000 s nitro separates 0.00025 from
  0.00025001, and so does a frame time that falls between two ticks'
  ages.

The four equivalents are in `real-driver.md`:

- **Two power-slide thresholds.** The yaw takes 65536 values, and neither
  5.0 nor 7.0 is one of them.
- **Two signs of a zero** that the steering arithmetic absorbs.

### Where the next slice starts

`RealController` (0x00224740, 84 bytes) has the image's only call to the
RealDriver constructor. It sits on `TrackedController` (0x00224388),
whose first 28 bytes `carcontroller.h` already has. Setting
`gRealControllerCtorFn` is what lets `Car::SetControlMode` give a car to
the player. CONTINUE.md has the addresses.


## Session 29, continued (2026-09-23) -- What RealController stands on

RealController needed four things the port did not have yet. All four are
done now. Each runs against the image in mipsemu, with a checker and a doc
under `docs/formats/`.

### QuickSpline, TrackPath and Average

- **`QuickSpline.obj`** (`quickspline.{c,h}`, 133/133 mutations caught).
  It found a real bug below it. `bFMod` truncated with a C cast, which is
  undefined past 2^31. The EE's `cvt.w.s` saturates. `bFMod` and `bSinF`
  now use `ee_trunc_w`, and `bmath_check` tests quotients past 2^31.
- **`TrackPath.obj`** (`trackpath.{c,h}`, 185 caught, 3 equivalent): the
  manager, the loader, and TrackPathCoordinate. `UpdatePosition` is no
  longer a stub. Five checkers that link `trackpath.c` needed
  `quickspline.c` and `bmem.c` added to their sources.
- **Average, PidError and Linear** (`average.{c,h}`, 64/64): table.cpp's
  three filters. Average's two roundings, at a total of 2^24, are a
  scenario of their own.

### The route helpers

`airoute.{c,h}` has GetNearestRoutePoint, GetNextRoutePoint,
GetNextRoutePointAhead and NearestRoutePointInfo::IsValid. `airoute_check`
runs the image's own FindClosestPoint, route manager and loader beneath
them. So it also checks `trackroute.c`'s search against the shipped code,
which `trackroute_check`'s Python model never could. 14,738 ops, 7,224
lines; 86 of 91 mutations caught, 5 equivalent.

- **No point keeps its index.** Every function divides the pointer
  distance by 112 with the inverse of 7. For a foreign or misaligned
  point that gives garbage, and the port reproduces the same garbage by
  laying the routes out as the loader does.
- **GetNextRoutePointAhead only looks further when the *start* point has a
  signpost.** I first read it as testing the new point. The header had it
  wrong until the transcript showed which step each case reached.
- **GetNewRoutePoint on an empty slot is a divergence.** It stays one on
  purpose. The image's NULL test is a `bltz` on an `lbu`, which can never
  fire. The port's test is its own, and so was `trackroute_check`'s model,
  which is why nobody noticed. No shipped sign names an empty slot. The
  model now hooks the case, and `trackroute.h` says so.
- **`TrackDirection`** (TheRaceParameters+12, 0x0031252c) is in `race.h`.
  It is in `.data` and 0 on the disc.

Four mutants survived the first pass, and each exposed a gap in the
checking:

- `RoutesToSearch` was an enum with no negative values. GCC makes that
  unsigned, so the checker's -1 was not the image's -1, and two range
  tests passed. It is an `int32_t` with defines now, like
  `eTrackDirection`.
- A step from below a route's table only lands right on a 64-bit host if
  the offset is sign-extended. Nothing read through the result. Three
  steps in a row now do.
- Every scenario set the direction before searching, so the starting
  value went unseen. One search now runs before any is set.

The last full mutation pass stopped twice on `BuildEnvironmentError`: msys
bash exited non-zero and printed nothing. Retrying five times in a row did
not get past it. The same mutant then built and was caught when run alone,
and 33 GB were free. The tally comes from two runs, and the doc says so.

### Where the next slice starts

TrackedController and RealController are read, not written. CONTINUE.md
has what the disassembly says: field by field, the constants, and the one
missing callee (`SetTargetToRender`, whose flag ships off).


## Session 30 (2026-09-24) -- Task 26's second slice: RealController, and a DriveTarget test the wrong way round

The second slice of task 26 is closed. `Car::SetControlMode(REAL_CONTROL)`
now builds a RealController, and the RealController builds the player's
RealDriver.

### What is ported

- **`realcontroller.{c,h}`**: TrackedController (0x00224388) and
  RealController (0x00224740), but for their two DoSnapshots, which wait on
  ReplaySnapshot. TrackedController's record is in `carcontroller.h`, so
  that car.c can reach its Acceleration.
- **`drivetargetrenderer.{c,h}`**: SetTargetToRender's flag-off path, and
  DestroyTargetMarkers. `RenderDriveTargetPoints` is 0 on the disc; the
  flag-on path builds WorldObjects and aborts.
- **The boot wiring.** `main.c` installs both tables and sets
  `gRealControllerCtorFn`. `REALCONTROLLER_SIZE` is `sizeof`: 84 bytes on
  the console, 160 on a 64-bit host. `carmodes.h` now counts seven classes
  unported, not eight.

`docs/formats/real-controller.md` is new.

```
realcontroller_check  14096 ops, 25318 lines, 0 differ
                      140 mutations, 129 caught, 11 equivalent, 0 unexplained
```

`realcontroller_check` runs the image in mipsemu as the oracle, and runs
everything beneath the two classes as shipped: CarController, RealDriver
and CarDriver, DriveTarget, the AI route helpers, TrackRoute's search,
Average, QuickSpline and bMath. Only the edges are stubbed. bMalloc logs
and maps the port's sizes to the image's, the pad calls exit, and
SetMovementMode and RadialBlurOff log.

### The image check found a DriveTarget bug that its own checker passed

**FillWithCurrentAcceleration's first test was negated, in `drivetarget.c`
and in `drivetarget_check.py`'s model both.** The image is `c.lt.s` of
0.75 |v| against |a|, then `bc1f` past the StraightLinePredict call. So it
integrates while the acceleration is at most three quarters of the speed,
and draws a straight line past that. The port and the model had it the
other way round, and they agreed. drivetarget_check passed, and its
`fi-dominates-flipped` mutant was killed for the wrong reason.

The first ComboPredict that fell through, with no acceleration at all, gave
fifteen points in the image and one in the port. Both sides are fixed. Every
`fi` fixture was re-derived so that it reaches the branch its label names,
and `fi still` and `fi ratio over` are new. With `fi still` in the
transcript, the twenty-point wall is no longer redundant, so `fi-no-wall`
is caught and its EQUIVALENT argument is gone.

```
drivetarget_check  22 scenarios, 894 lines, 0 differ
                   260 mutations, 241 caught, 19 equivalent, 0 unexplained
```

**The lesson is in CONTINUE's "What not to trust".** A model written from
the disassembly can share a misreading with the port, and a check that runs
the image cannot. Most of task 25's checkers are models: carstate, engine,
cartypeinfo, cardriver, steering, rigidbody, suspension, wheel, drivetrain,
drivetarget, graph, physicssystem, aerodynamics and physcomp. The rest of
DriveTarget is still checked against its model alone: Resample,
EstimateScore, GetFirstPoint, InterpolatePoint, the shifts and the copies.

### Three things the listing says that are easy to miss

- **A predicted point's pad is garbage on the console.**
  `GetPosition(bVector3)` stores four VU0 lanes. The fourth comes from two
  stack words, 12(sp) and 44(sp), that it never sets. The port's pad is the
  car position's (STACK-W), and the checker compares no pad.
- **Think's blend is dead.** BlendWithCurrentAcceleration returns at once
  for a car with a Player, and Think has already read through pPlayer for
  bWrongWay. So a human's target is never blended.
- **ComboPredict has no caller.** No `jal` reaches it, and it is not
  virtual. It is ported anyway, and its fall-through is what showed the
  DriveTarget bug.

Think's wrong-way test is `pPlayer->bWrongWay`: Car+24, then Player+736. An
earlier CONTINUE note said pRideInfo, which was wrong.

### The mutation pass

The first pass left nineteen survivors. Eight were gaps in the script:

- **FindWhereIAm's out-of-bounds drop, and its radius.** The network's
  routes have random widths, and when the drop fired, the fallback found
  the same point again. A traffic lane of known width, beside a racing
  route, now makes a drop show.
- **The two route tests, in Think and in RouteDeltaPredict.** They decide
  only when the route is NULL and the point is not. Nothing passed that,
  and it now does: a point whose route the manager does not hold, and a
  direct call.
- **Fill at a ForwardSpeed of exactly 10**, with nothing predicted.
- **CalculateLateral's too-few exit after the Average had been fed.**

The eleven that remain are argued in `EQUIVALENT` and listed in the doc.
Two of them are facts about the class:

- **No class in the image overrides FindWhereIAm.** The three tables that
  hold it all hold 0x00224530: TrackedController's, RealController's and
  CopDriver's (0x00298d68). CopDriver is a TrackedController too. Its own
  fields start at 36, and its table shares slots 40 to 80 with
  TrackedController's.
- **The Clear at a route's end is repeated** by StraightLinePredict.

**A pass can run from a copy of the tree.** RealController's harness links
`drivetarget.c`, and DriveTarget's pass was mutating it, so the first
RealController pass ran from a copy in the scratchpad. The checkers find
their sources from their own path. A copy of `tools/`, `3DS Files/source/`,
`PS2 Files/NFSHP2.ELF`, `docs/mdebug_structs.txt` and the two extracted
bundles is enough.

DriveTarget's own pass stopped once on a `BuildEnvironmentError`, after
twelve mutants. The other 248 ran with the build retried on that error and
the finished twelve skipped. The tally is the two runs together.

### Where the next slice starts

Seven of Car's eight constructor seams are still NULL: TrafficCar,
DeliveryMover, CopMover and BeltMover, and AIDriver, TrafficDriver and
CopDriver. CopDriver (0x00197d48, 76 bytes) is a TrackedController, so
it can take FindWhereIAm, SetCurrentRoute and the rest from
`realcontroller.c` as they stand.

## Session 30, continued (2026-09-25) -- Task 27's first slice: the ground under the car

`Track.obj` and `TerrainType.obj` are ported. They give the port the track's
collision surface, its markers, its info table and its road noise.
`docs/formats/topology.md` is new.

### What is ported

- **`track.c`, `topology.h`, `track.h`.** These cover:
  - the TopologyTree over its four chunks;
  - the TrackPolygon pool: 1024 slots, reference counted, flushed at most
    101 at a time;
  - TopologyCoordinate, which is what a car stands on;
  - the position markers, GetTrackInfo, the road noise, and
    LoaderTrackGeometry with its unloader.

  Every function except the exit-time destructor is ported.
- **`terraintype.c`**, the two MatchTerrainTypes and the static initialiser
  that hashes the names. `terraintypetab.c` is the 33-entry table, written
  by `tools/gen_terrain_table.py` out of the ELF.

```
track_check  13557 ops, 9736 lines, 0 differ
             172 mutations, 170 caught, 2 equivalent, 0 unexplained
```

`track_check` runs the image in mipsemu as the oracle, with bWare's slot
pool, bVector and bStringHash beneath it. It drives a synthetic world
through every entry point, then TRACKB12, whose squares it walks until the
pool has flushed several times. It found no disagreement between the image
and the port. Two bugs turned up along the way, both in the checker's own
scenarios and model:
- a REMOVE ran past what a BUILD had filled, which crashed the harness on
  NULL entries;
- the model passed 32-bit arguments zero-extended where the image's `lw`
  sign-extends, so a hash with its top bit set never matched.

### Three things the listing says that are easy to miss

- **`GetSquare`'s nearest child is its first non-empty one.** The score is
  the distance to the quadrant corner just chosen, which is the same for
  all four children. With none non-empty the pick stays -1, and the image
  indexes the table with it.
- **`NumUpsideDownTrackPolygons` holds (placed) minus (vertical).** For an
  all-floor build that is the total. A polygon both vertical and upside
  down is placed twice, unless it is the only thing the first pass left
  out, in which case the third pass never runs.
- **LoaderTrackGeometry takes seven types, and `chunk_loader_table.py`
  reports two.** `0x34146`'s compare comes after a `lw` that takes over the
  type register, and `0x34130`..`0x34133` go through a tail call into
  TopologyTree::Loader. `bchunk.md` has the details.

### The mutation pass

The first pass left ten survivors. Eight were inputs that no scenario
reached, and each now has one:
- a collision body in the slot before the constructor runs;
- a best distance exactly equal to a crossing's;
- floors plus a wall that is also a ceiling, with the ceiling beside it
  left out of the box;
- HasTopology over a flat floor at height 0 under a sloped one at 100;
- a negative clearance, the one input where Constrain's box margin shows;
- a clearance past 999999, where the mutant reads a NULL polygon;
- a noise coordinate past 2^24, where an integer minus one rounds;
- enough random noise probes for the corner weights' rounding to show.

The last two are argued in `EQUIVALENT`:
- **`flush-resume`.** A walk resumed from the head comes back to the same
  node, since nothing in the loop changes a count.
- **`icmp-diff`.** The case-blind compare's only caller tests it against 0.

### Where the next slice starts

The surface is ported but not live. Three things are missing:
- the port has no LoaderTable to hand it chunks;
- `EndGameFlowLoadingTrackSpecific` does not call `InitTree` yet;
- Car.obj's `SetInterestBBox(bVector3)` wrapper (0x00134f28) is not
  ported.

After those comes the rest of task 27's list in TASKS.md: Car's constructor
and `Move`, `PutFlatOnTrack`, `FindFlatOnTrackPosition` and the collision
bodies.

## Session 30, continued (2026-09-25) -- Task 27's second slice: Car on the ground

Car's `FindFlatOnTrackPosition` (`0x00130c58`) and `PutFlatOnTrack`
(`0x00130e90`) are ported in `cartrack.c`. They are the first of Car's
methods to call into the topology. The first version put them in `car.c`,
and `realdriver_check` and `realcontroller_check` stopped linking, because
`car.c` goes into six checkers that carry no topology. So they have their
own file, the same way `carmodes.c` does. The `bVector3` overload of
`SetInterestBBox` (`0x00134f28`), eight bytes the compiler emitted in
`Car.obj`, is `topology_set_interest_bbox3` in `track.c`.

```
track_check  14753 ops, 11231 lines, 0 differ
             209 mutations, 206 caught, 3 equivalent, 0 unexplained
```

`track_check` checks them because it has the topology loaded already. A
`Car` and a `CarTypeInfo` sit at fixed addresses in the model. The
synthetic world has a skew slope, a gap along x and another along y, a
cliff, and ground with nothing under it. TRACKB12 gets ninety cars, each
set down 1.5 above the centroid of a random floor polygon. No disagreement
between the image and the port was found.

### What the listing says

- **The slope's constant is 65536 / 6.28**, `0x46230eac`, not 65536 / 2 pi.
  It is kept, and a mutation to either neighbour is caught.
- **The slopes are differences of differences**, `(h1 - h0) - (h2 - h0)`.
  They part from `h1 - h2` only when one sample is far from the others,
  which means one that found nothing and got the probe's own z back. Until
  the y gap was added, `h3 - h4` in the pitch survived.
- **`cvt.w.s` saturates**, and only the low sixteen bits make the BAM.
  Getting there takes a probe billions high over a gap, and the fixtures
  have one on each axis in each direction.
- **`PutFlatOnTrack`'s centre of gravity is not rotated.** It is a four-lane
  `vsub` in body space, where `CalculateGeometryPosition` rotates it.

### The mutation pass

The full pass stopped once at mutant 173 on the transient "compile failed
with no diagnostic" error. The sources were checked as restored, and the
last 37 were rerun with `--only`. The one new equivalent is
`flat-terrain-null`: nothing reads the terrain local, and GetElevation only
stores through it.

### Next

Car's reset group: `ResetCore`, `ResetToPosition`, `ResetToRoutePoint` and
`DebugSetPosition`. ResetCore's `pPlayer` arm calls
`ReplayManager::InvalidateInterestingEvents`, which adds -99 to every
snapshot named `INSTANT_REPLAY` while capturing. The name it is given is
never read.

## Session 30, continued (2026-09-25) -- Task 27's third slice: the resets

Car's reset group is ported in `carreset.c`: `ResetCore` (`0x001312c0`),
`ResetToPosition` (`0x00131418`), `ResetToRoutePoint` (`0x00131480`) and
`DebugSetPosition` (`0x001317d0`). ResetCore's player arm needs
`ReplayManager::RegisterInterestingEvent` (`0x0013c290`) and
`InvalidateInterestingEvents` (`0x0013c310`), so both are ported in
`replay.c`. `replay.h` now has the manager's 116 bytes and
ReplaySnapshot's 332, all checked against mdebug.

```
carmode_check  74 transitions, 19 resets, 32797 lines, 63 masked, 0 differ
               188 mutations, 185 caught, 3 equivalent, 0 unexplained
```

`carmode_check` already had the modes, the stand-in controllers and
drivers, and the logged heap, so the resets run there, after the
transitions. The track path is real: a twelve-point looping circle loaded
through `LoaderTrackPath`, with its QuickSplines' heap unlogged on both
sides. The replay has five snapshots with near-miss names. No disagreement
between the image and the port was found.

### What the listing says

- **The velocity after a reset is never zero.** It is the body's forward
  row normalised to `speed + 0.1`.
- **`ResetToRoutePoint`'s position has a fourth lane nobody wrote.** It is
  built from three stores, then copied whole into `Position`, and
  `PutFlatOnTrack` carries it into `GeometryPosition`.
  `ResetCore`'s `bNormalize` result is the same. The port writes 0 in
  both.
- **The replay is not tested for NULL** before
  `InvalidateInterestingEvents`. The port tests it, the slice's one
  deliberate difference, because nothing builds a ReplayManager yet.
- **`RegisterInterestingEvent` never reads its description.** Every event
  lands on the snapshots named `INSTANT_REPLAY`.
- **`DebugSetPosition`'s heading is relative to the road**: `angle` plus
  the track path's direction.

### The stack

The model poisons the 8 KB below `sp` at each reset entry, once with
`0xC4424000` and once with `0x43A6A000`. It then merges the two
transcripts. A line may differ only in the fourth lane of a named vector,
and that token becomes `*`. To prove nothing else reads the stack, the two
words were zeroed at their source: the two poisoned runs came out
identical.

### The mutation pass

Seventy-four new mutations; the first pass caught 68. Three of the six
survivors were blind spots:

- `rp-no-tpc` and `rr-no-tpc` drop the second
  `TrackPathCoordinate::UpdatePosition`. `UpdatePosition` keeps its point
  when the car has moved less than 128 units, and then searches only that
  point's neighbours. So three resets were added that walk the path from
  point 2 to 0, where only the second update gets there.
- `rc-invalidate-always` survived because no case had a capturing replay
  without a player. The new "bystander" case adds one.

The other three are copies of what `ResetCar` already did, and are
recorded as equivalent: `SteeringAngle = 0`, `MatrixValid = 0` and
`CalculateWheelMatrices`.

### Next

`AverageAir` (`0x00133e48`) and `BeginMovement` (`0x001303a8`), in
`cartrack.c` and checked by `track_check`. Neither calls anything outside
the topology, `bMulMatrix` and `CarState`. AverageAir takes every
wheel's contact point through `WheelMatrix[0]`, whatever the wheel. Port
it as shipped.

## Session 30, continued (2026-09-25) -- Task 27's fourth slice: the air under the car

`Car::AverageAir` (`0x00133e48`, 740 bytes) and `Car::BeginMovement`
(`0x001303a8`, 216) are ported in `cartrack.c`, beside
`FindFlatOnTrackPosition` and `PutFlatOnTrack`. They are declared in
`car.h`. Car is now 51 of its 80 methods, 7236 of 22876 bytes.
`track_check` runs them over the flat scenario's world, with four new
ops: two set a car vector or word, and two run the methods.

```
track_check    16149 ops, 11790 lines, 0 differ
               the slice's 62 mutations: 60 caught, 2 equivalent, 0 unexplained
carmode_check  74 transitions, 19 resets, 32797 lines, 63 masked, 0 differ
```

No disagreement between the image and the port was found. Nothing is
committed since `409501b`.

### What the listing says

- **Every wheel goes through `WheelMatrix[0]`.** The start point is wheel
  0's bottom, averaged over the four radii. It is ported as shipped.
- **The fall is `(g t + v) t`, with no half**, and `g` has the downforce
  folded in.
- **The mean is `sum / i - 1`.** The sample that meets the ground counts
  in `i` but not in `sum`.
- **`cvt.w.s` saturates**, and the port uses `ee_trunc_w`. A plain cast
  gives no samples where the image asks for 0x7fffffff.
- **`BeginMovement`'s box is sized from the velocity's own length**,
  `(x x + y y) + z z`, not from `VelocityMagnitude`.

### The mutation pass

The first pass caught 56 of 62. The six survivors:

- `air-first-normal` and `air-sample-no-normal` are equivalent. The
  normal goes to a local that nothing reads.
- `air-share-ulp`: a 1450 kg car's downforce is lost against gravity. A
  2^-13 kg car thrown up at `down` times its window catches it.
- `air-while-le`: no flight lasted its whole window. Three do now.
- `bm-speed-order`: (4096, .875, .875) gives radicands one ulp apart, and
  the square root rounds them back together.
  (138.234375, 2.46875, 1.90625) separates them.
- `air-no-floor` needed a start under the ground. Three were added. The
  old flights catch it too once the 4096 velocity is gone, which points at
  that car's 420-wide box staying cached for every later flight. That is
  **not confirmed**: apply the mutant with the old velocity back to check.

`carmode_check` links `cartrack.c` too, so its harness got stand-ins for
`topology_set_interest_bbox3` and `topology_has_topology` that abort if
anything reaches them.

**Not rerun:** the first 209 mutations were not rerun after the slice's
scenario went in ahead of the TRACKB12 section. A full
`track_check --mutate` (271 mutations, about 3.5 hours) would confirm
them.

### Next: slice five, `Car::Move`

`Move` (`0x00130200`, 388 bytes) is the per-step driver:

```
CalculateNewCatchupMultipliers(c)
r = pCarMover->Move(dt)                  CARMOVER_VT_MOVE, through vt_slot
UpdatePosition(c, &State.Position)
ChangeGear(c, State.Gear)                State+900
if ResetMe:
    ResetToRoutePoint(c, GetRoute(c), GetRoutePoint(c),
                      f[gp-23488] (0x323030), 1, 1.0f)
    ResetMe = 0
    return r
pen = GetLastPenetrationTime(c)          pDynamicCollisionBody->+260
if !IsBlinking(c) or pen == 0 or pen == 0x7fffffff: return r
k = f[gp-23484] (0x323034); tick = f[gp-32076] (0x320ea4)
if !(BlinkDuration - k < (WorldTimer - BlinkTimer) * tick): return r
s = (WorldTimer - pen) * tick
if !(s < k) or !(0 <= s): return r
BlinkTimer += Timer::SetTime(k)          ee_trunc_w(k * 4000.0f)
return r
```

- **`ChangeGear`** (`0x00130ff8`) returns early when `gear == DispGear`.
  If the old gear is 1, or there is no `pAnimatedDriver`, it stores the
  gear and stops. Otherwise it calls `EndDrivingBackwards` if the old gear
  was 0, then `BeginGearChange`, then `BeginDrivingBackwards` if the new
  gear is 0, and stores the gear. The three AnimatedDriver methods are
  small: `QueueAnimation(11)`, and a flag at byte 105 around
  `HandleDrivingBackwards` / `ReleaseAnimation(3)`. AnimatedDriver is not
  ported, so give them seams in the carmodes style: NULL aborts, and
  nothing sets `pAnimatedDriver` yet.
- **`CalculateNewCatchupMultipliers`** (`0x001334f0`) needs a
  `pPlayer`, `TheRaceParameters+740` (`0x00312804`) nonzero, and
  `NumPlayers == 2`. `Race::GetRacingCar` (`0x00146ad8`) is only
  `return car->pRacingCar`, so no Race layout is needed. The other car
  is `pPlayersByNumber[PlayerNumber == 0 ? 1 : 0]->MyCar`. The graph's x
  is `me.CurrentLapNumberExact * L - other.CurrentLapNumberExact * L`,
  with `L = TheTrackPathManager.TrackLength` (`0x00313768`). Its four
  points are at `0x002e847c` (`TheDifficultyInfo+700`); read them out of
  the image. `Graph::GetValue(x)` goes to `State.BoostFactor` (car+988).
- **`UpdatePosition`** (`0x00130388`) is `if (pCaffeineObj)
  espSetObjectPosition(obj, pos)`. Per `trackroute.h`, "Esp" is the
  Espresso/Caffeine live-editor link, not sound. TASKS.md files it under
  task 29 as sound. Check who sets `pCaffeineObj` before choosing between
  a no-op and a seam.
- Check it in `carmode_check`, which has the stand-in movers already.
  Read the three gp floats out of the image first.

## Session 30, continued (2026-09-25) -- Task 27's fifth slice: the step

The step is ported in `carmove.c`:
- `Car::Move` (`0x00130200`, 388 bytes);
- `ChangeGear` (`0x00130ff8`, 120);
- `CalculateNewCatchupMultipliers` (`0x001334f0`, 220);
- `UpdatePosition` (`0x00130388`, 28).

They are declared in `car.h`. Car is now 55 of its 80 methods, 7992 of
22876 bytes. Four pieces came with them:
- **`timer.{c,h}`**: Timer, moved out of `collisionbody.h`, and
  `Timer::SetTime` (`0x00134ef0`), which is
  `ee_trunc_w(seconds * 4000)`.
- **`player.c`**: `Player::NumPlayers` (gp-21520) and `pPlayersByNumber`
  (gp-21536).
- **`difficultyinfo.{c,h}`**: the 744-byte table (`0x002e81c0`) and the
  loader and unloader for chunk `0x00034b00`. The port has no
  LoaderTable, so nothing registers the loader yet.
- **`race.h`** has the whole 192-byte `RacingCar`, with thirty-seven
  Timers, and `Race::GetRacingCar` (`0x00146ad8`). `race.c` has
  `TheRaceParameters.Boost` (`0x00312804`) as `RaceParametersBoost`.

```
carmode_check  74 transitions, 19 resets, 35405 lines, 103 masked, 0 differ
               the slice's 79 mutations: 77 caught, 2 equivalent, 0 unexplained
```

No disagreement between the image and the port was found. Nothing is
committed since `409501b`.

### What the listing says

- **The mover's float is `Move`'s return on every path.** Neither the
  reset nor the blink changes it.
- **`GetRoute` is called before `GetRoutePoint`.** The first port wrote
  them as the reset's arguments, and gcc evaluated them right to left.
  The stand-in controller logged the order, and the checker showed 4
  differing lines. That was a port bug, not a disagreement. The port now
  calls them as two statements.
- **The lead is each car's own product, then the difference**:
  `me * L - other * L`. The checker has two leads where
  `(me - other) * L` gives a boost one ulp away.
- **The other player is `pPlayersByNumber[PlayerNumber == 0 ? 1 : 0]`.**
  The compiler copied the second `GetRacingCar` into both arms, so the
  listing has three call sites and each run makes two calls.
- **`pCaffeineObj` is only ever zeroed**, by the constructor at
  `0x0012f514`. So `UpdatePosition`'s editor link is dead on the disc.
- **`ChangeGear` out of neutral (1) only stores the gear.**
- **One more lane is poisoned.** The body's `State` at 96 (the angular
  momentum) takes a stack word's fourth lane through the physics step
  after a reset. It is in the merge's list.

### The mutation pass

The first pass caught 72 of 79. The seven survivors:

- `mv-s-unsigned` and `tm-plain-cast` are equivalent, and are recorded
  with their reasons.
- `cu-pick-inverted` and `cu-pick-by-one` edited the comment above the
  code, which spells the same index. Their patterns now start at
  `c->pPlayer->`.
- `mv-pen-zero-ok`, `mv-pen-max-ok` and `mv-pen-max-off` needed a
  `WorldTimer` near the sentinels. `mv()` now takes `now=`, and four
  cases put the clock a quarter second past 0, 1, `0x7fffffff` and
  `0x7ffffffe`.

The fourth and sixth slices' 188 were not rerun. Everything they are
caught on comes before the step.

### track_check's first 209

The first 209 mutations were rerun on their own
(`track_check --mutate --only` with the 209 names). The result is the same
as before slice four's scenario went in ahead of the TRACKB12 section:

```
track_check --only (the first 209)  209 mutations, 206 caught, 3 equivalent, 0 unexplained
```

The three equivalents are the same ones: `flush-resume`, `icmp-diff` and
`flat-terrain-null`. With the slice's 62, all 271 of `track_check`'s
mutations have now been run against its current scenario.

### Car's ninth slice (done; see below)

The methods of Car that make one outside call each:
- `GetDistanceAndSpeed` (`0x001326b0`, 32 bytes). It is static:
  `DynamicCollisionBody::GetDistanceAndSpeed(d, a->pDCB, b->pDCB)`,
  which is `*d = 0; return *d`.
- `FixBlownTires` (`0x00133450`, 44). It clears bytes 1944 and 1945 and
  the word at 1948. Under `REAL_CONTROL` it then tail-calls
  `RealDriver::ForceEBrakeStop(pCarDriver, 0)`, which is ported.
- `PleaseResetMeLater` (`0x00131580`, 108). It stores `ResetMe = 1`
  unless every test passes: `TheRaceParameters.BeACop` (+624) set,
  `nMaxCops` (+604) positive, `MyDriver->DriverType` equal to 2, and
  `TheCopManager` (gp-16500) `->IsBeingPursued(this)` true. So a car that
  is being chased in Be a Cop is not reset.
- `GetDrivingLineSpeed` (`0x00131700`, 60). Under control mode 2 or 3,
  it returns `AICarController::GetCurrentDrivingLineSpeed(pCarController)`,
  and 0 otherwise.
- `DeliverMeFromEvil` (`0x001326d0`, 108): `SetMovementMode(3)`, then a
  tail call to `DeliveryMover::SetDestination(pCarMover, pos, angle,
  f12, f13)`.
- `TriggerTireBlowOut` (`0x00133368`, 232). It sets the blown-tire bits,
  sets the timer at 1948 to 7.0, and counts the blown tires into 1945.
  It calls `TriggerEffect(8, 1.0, 0x50000 + i * 0x10000, NULL)` for each
  newly blown one, then `BaseCarSound::TriggerTireBlowOut` if there is
  a sound at 1952.

The tCopManager, AICarController, DeliveryMover, TriggerEffect and
BaseCarSound calls need seams. `DeliverMeFromEvil` reaches
`SetMovementMode`, so it goes where `carmode_check` can run it.

## Session 30, continued (2026-09-25) -- Task 27's sixth slice: Car's calls out

Six methods of Car that make one outside call each are ported in
`carrace.c`:
- `GetDistanceAndSpeed` (`0x001326b0`, 32 bytes), which is static;
- `FixBlownTires` (`0x00133450`, 44);
- `TriggerTireBlowOut` (`0x00133368`, 232);
- `PleaseResetMeLater` (`0x00131580`, 108);
- `GetDrivingLineSpeed` (`0x00131700`, 60);
- `DeliverMeFromEvil` (`0x001326d0`, 108).

They are declared in `car.h`. Car is now 61 of its 80 methods, 8576 of
22876 bytes. Also new:
- `collisionbody.c` has `DynamicCollisionBody::GetDistanceAndSpeed`
  (`0x001cd068`), which stores 0 through its pointer and returns it.
- `race.{c,h}` have `RaceParametersMaxCops` (`0x0031277c`, compared
  signed).
- `car.h` has the `CarEffect` enum (type#1034), and a file-scope
  `tCopManager` typedef beside the other strangers.
- `main.c` sets `gCarResetToRoutePointFn = car_reset_to_route_point` at
  boot. RealDriver's reset button did nothing while it was NULL.

```
carmode_check  74 transitions, 19 resets, 35602 lines, 103 masked, 0 differ
               the slice's 43 mutations: 43 caught, 0 equivalent, 0 unexplained
tools/build_cia.ps1  builds the CIA, with no new warnings
```

No disagreement between the image and the port was found. Nothing is
committed since `409501b`.

### The seams

```
gCopManagerIsBeingPursuedFn                   tCopManager::IsBeingPursued                  aborts
gAICarControllerGetCurrentDrivingLineSpeedFn  AICarController::GetCurrentDrivingLineSpeed  aborts
gDeliveryMoverSetDestinationFn                DeliveryMover::SetDestination                aborts
gCarTriggerEffectFn                           Car::TriggerEffect (0x0011e328, 720 bytes)   skipped
gBaseCarSoundTriggerTireBlowOutFn             BaseCarSound::TriggerTireBlowOut             skipped
```

`Car::TriggerEffect` is Car's own method. It is compiled into the effect
system's object, not `Car.obj`. `TriggerCarTerrainEffects` calls it too, so
the next slice uses the same seam.

### What the listing says

- **The count covers every blown tyre, and the effect only the mask's.**
  The count's store is in a delay slot, so it happens whether or not the
  mask has the bit.
- **Bits past the fourth tyre are kept** in `BlownTireBits` and counted by
  nothing.
- **`SetMovementMode(DELIVERY)` under DELIVERY builds a new mover.** The
  transcript shows the old one destroyed first. `DeliverMeFromEvil` reads
  `pCarMover` after the call.

### The mutation pass

41 of 43 were caught on the first pass. `blow-where-base` and
`blow-where-step` matched the comment above the function, which spells
the same `0x50000 + i * 0x10000`. Their patterns now end in `, NULL);`,
and both are caught.

### Next: Car's tenth slice, `TriggerCarTerrainEffects`

`TriggerCarTerrainEffects` (`0x00131db8`, 1872 bytes) walks the four
wheels. Its outside calls are `GetElevation`,
`BodyDamage::GetVisibleTotalDamage`, `bMulMatrix`, `TriggerEffect` and
`BaseCarSound::TriggerSplash`, and it calls `TurnWipersOnForDuration`,
which is Car's. Only the splash is not ported or a seam yet. The effect
it asks for is `CARFX_SKID_SMOKE` (3). The terrain comes from the
140-byte TerrainTypeInfo table at `0x00310a90`, which `terraintype.c`
has. `carmode_check`'s ground is a stand-in elevation that logs, and
`track_check` has the real topology, so decide which checker runs it
after reading the whole listing.

## Session 30, continued (2026-09-25) -- Task 27's seventh slice: the terrain's effects

Car's tenth slice is one method, `TriggerCarTerrainEffects`
(`0x00131db8`, 1872 bytes), in a file of its own, `careffects.c`. It is
declared in `car.h`. Car is now 62 of its 80 methods, 10448 of 22876
bytes.

It walks the four wheels for skid smoke and tire spew, and marks the wet
ones. With three or four wheels down it asks the topology for the ground
and gives the two drive-over effects and bottom-out. Then come the
splash (the wipers and the sound), the radiator and engine smoke, the
nitro, and the flat tires. `car.md` has the pseudocode and what the
listing says.

```
carmode_check  74 transitions, 19 resets, 35875 lines, 103 masked, 0 differ
               the slice's 107 mutations: 104 caught, 3 equivalent, 0 unexplained
tools/build_cia.ps1  builds the CIA, with careffects.o in it
```

Nothing is committed since `409501b`.

### A finding, and its fix

**Car's `NumTimesSkidding` is `unsigned char[4]`, not an `int32_t`.**
The stab at 1984 is `ar1;0;3;11`, and the listing reads and writes it a
byte a wheel (`lbu`, `sb`, `pminw` against 255). The offset is the same,
so nothing moved. `car.h` has `uint8_t NumTimesSkidding[4]`, and
`car_check`'s fixture and its mutation set `[0]`. All forty-three
checkers and the four generators still pass, and `car_check --mutate`
still has 0 unexplained.

### Two smaller fixes along the way

- **Four checkers did not link.** `replay.c` now calls `p32_ptr`, and
  `realdriver_check`, `realcontroller_check`, `joystick_check` and
  `joyhid_check` did not list `p32.c`. All four do now, after
  `replay.c`.
- **`mipsemu.py` had never met `madd`, `maddu` or `pminw`.** The terrain
  table is indexed with the R5900's three-operand `madd`, the table's
  address first put in `lo` by `mtlo`, and the skid count is capped with
  `pminw`. The model stopped at `0x00131e90` with `mmi fn=0x00`. Both
  are in `_mmi` now. `madd` adds the product to `hi:lo`, and puts the
  sign-extended low word in `lo` and in `rd`.

### The seam

```
gBaseCarSoundTriggerSplashFn  BaseCarSound::TriggerSplash (0x00185038)  task 29  skipped
```

`TriggerEffect` is the sixth slice's seam again, and so are both skipped
when NULL.

### How the check reaches it

`carmode_check` runs one more scenario after the sixth slice's: 54
cases. The stand-in elevation takes a terrain for the ground from each
case, but only around the call, so the physics car's setup reads the
checker's plane as it did. The effect stand-in logs a point's four lanes
when there is one. Terrain 4's drive-over window is patched and restored
in three cases, to reach the order test's both sides and its tie.

### Next: the clock object

The eighteen Car methods left all reach classes that are not ported.
`car.md` lists them. The next piece is the clock object, `0x001992a0` ..
`0x00199678`, about 1 KB: `Get/SetVideoMode`, the quantised real
timestep, `PrepareRealTimestep`, `AdvanceRealTime`, `ResetWorldTime`,
`PrepareWorldTimestep` and `AdvanceWorldTime`. Its globals are
`0x00323cc8` .. `0x00323d0c`. `WorldTimer` and `WorldTimeFrames` are
declared in the port and defined only in the harnesses. Car reads them,
and the 3DS link survives only because `--gc-sections` drops every
reader. `realtime.{c,h}` has `RealTimer` and `FrameCounter`,
`gameflow.c` keeps its own copies in its record, and `cammover.c`
defines `RealTimeElapsed` as 1/60. The object's outside calls are
`Joylog::GetData`, `Joylog::AddData` and `Timer::SetTime`, all ported.
`WorldTimeDoSnapshot` waits on ReplaySnapshot.

After it comes the collision system that `FinishMovement` needs: VClip
(`0x001c5d90` ..), `CollisionBody.obj` (`0x001ca1c8` ..), `Collision`
(`0x0020b290` ..), and `World`'s timestep (`0x0014a4e8` ..).

## Session 30, continued (2026-09-25) -- Task 27's eighth slice: the clock object

The video mode, the real clock and the world clock are ported in
`realtime.c`. They are nine functions, `0x001992a0` .. `0x001995d8`, and
the eighteen globals at `0x00323cc8` .. `0x00323d0c`, each at its .sdata
value. `docs/formats/realtime.md` has the table, the pseudocode, and what
MainLoop gives each one.

```
realtime_check  20 scenarios, 1044 ops, 3470 lines, 0 differ
                86 mutations: 84 caught, 2 equivalent, 0 unexplained
the suite       all 44 checkers and the 4 generators, 0 differ
tools/build_cia.ps1  built NFSHP2-3DS.cia, 307,648 bytes
```

Nothing is committed since `409501b`.

### The globals have one home now

Four of them had been defined wherever a reader first needed them:

- `WorldTimer` in `engine.c`;
- `WorldTimeElapsed` in `drivetrain.c`;
- `WorldLoopCounter` in `world.c`;
- `RealTimeElapsed` in `cammover.c`, at 1/60.

All eighteen are in `realtime.c`. `engine.h`, `world.h` and `cammover.h`
include `realtime.h` where they had an `extern`, and so do `car.c`,
`careffects.c` and `carmove.c`. A harness that does not link `realtime.c`
defines the ones its files read, at the value it had before. That is
engine, drivetrain, physcomp, camera, physicscar, mellowmover, carmode,
realdriver and realcontroller. `joystick_check` and `joyhid_check` link
`realtime.c`, and now `timer.c` after it.

### main.c drives the clocks

MainLoop prepares the real step from the ticker at the top of the frame,
then the world's from the real one when there is no race. It advances
both at the frame's end. The port does the same, with `BOOT_DT` as the
ticker's measure, and advances at the top of the next frame. The joystick
now reads the clock object's `RealTimer`, not `uiTimer`. That timer runs
1.0167 times the ticker, as the image's does. `gameflow.c`'s own clock and
`uiTimer` are still apart.

### What the listing says

- NTSC's ceiling is `0x3d4cccce`, one ulp above 0.05f, and is spelled
  `0.050000004f`.
- The carried error is the clamped step minus the whole timer ticks, and
  it goes in after the 1.0167 scale.
- Replaying, the step is not clamped, and the loop count's four bits are
  read and dropped.
- AdvanceRealTime's minimum of one frame is a `movn`, so a negative count
  is kept. AdvanceWorldTime has no minimum. It returns on a step of 0 or
  -0, with the prepare flag already set.
- ResetWorldTime leaves the prepare flag alone. `WorldTimer` starts at 0
  while the seconds start at 1.0.

No disagreement between the image and the port was found.

### Next: the collision system

Next is what `FinishMovement` needs:

- VClip, `0x001c5d90` ..;
- `CollisionBody.obj`, `0x001ca1c8` ..;
- `Collision`, `0x0020b290` ..;
- `World`'s timestep, `0x0014a4e8` ...

## Session 30, continued (2026-09-25) -- Task 27's ninth slice: VClip

`VClip.obj` (`0x001c5d90` .. `0x001ca008`, 54 functions) is ported in
`vclip.{c,h}`. That is V-Clip, the closest-feature walk the collision
bodies run between two convex polyhedra. `docs/formats/vclip.md` covers
the features and planes, the walk, each check and clip, and the lanes.

```
vclip_check     47 scenarios, 11890 ops, 22389 lines, 0 differ
                2001 VClips (0 x32, 1 x1046, 2 x923), 938 single checks
                281 mutations: 280 caught, 1 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

### What came with it

- `espresso.{c,h}`: the Espresso editor's five client calls as seams,
  which abort if reached unset. Every create call is behind a debug switch
  that is zero on the disc. `gEspSetObjectPositionFn`, which Car had
  declared, is defined here now, and `carmode_check` links `espresso.c`.
- `tools/src/vclip_test.c` and `tools/vclip_check.py`. The records hold
  pointers, so both sides build the same polyhedra through the same calls,
  and the transcript names every feature by polyhedron, kind and index.
- `hostbuild.py`: under msys2 a link with every object cached failed with
  "compile failed (msys2 bash)" and no diagnostic. The branch took "nothing
  to compile" for a failure. It is fixed.

`DoSnapshot` is not ported. It waits on ReplaySnapshot, as
`CarState::DoSnapshot` does.

### Single steps

The walk converges to the same closest pair whichever way one step goes.
After the whole-walk scenarios, 21 mutants survived:

- the touch limits of VV and VF;
- the distance VE, EE and EF leave on penetration;
- the parallel paths;
- the carried-over clips;
- two polyhedron calls no scenario reached.

`OP_CHECK` runs one check on its own, set up as VClip sets it up: both
transforms, `SwitchState`, and the swap when the check's first feature is
F2. The new single-step scenarios kill all 21.

The last to die was `ef-from-g-head`: CheckEdgeFace measuring from the
head of the face's edge instead of its tail. The line is the same, so in
exact arithmetic the answer is too. The mutant only shows when:

- the edge is parallel to the face's edge exactly as stored;
- both are along an octahedron's diagonal, stored as 5793 x 2^-13, which
  is not unit length;
- the edge lies within a few 1e-4 of the face's edge.

There, which point of the line is passed moves both the parallel branch's
choice of end and the foot on the line. In a hunt over 4,000 such cases
the mutant changed 83 answers. The checker runs 800.

### How the survivors were found

The scratchpad's `hunt.py` built each survivor's harness once. Candidate
scripts then ran through the base harness and each mutant with no
emulator, and the output was compared by tag. A family either kills a
mutant in seconds or it does not. The full checker then confirms the
model agrees on it. That is far quicker than a `--mutate` pass for each
idea, and it is worth keeping for the next checker.

### Next: CollisionBody

`CollisionBody.obj`, `0x001ca1c8` .. `0x001cebb8`, is next:

- the NumberAllocator, and `Init/CloseCollisionBody`'s pools, ID table and
  witness bit field;
- CollisionBody and StaticCollisionBody;
- DynamicCollisionBody and CarCollisionBody;
- TrackPolygonCollisionBody, whose `WaferPolyhedron` is Collision.obj's;
- CollisionBodyWitness;
- Contact.

After it come `Collision` (`0x0020b290` ..), the polyhedron builder,
`World`'s timestep (`0x0014a4e8` ..) and `Car::FinishMovement`.

## Session 30, continued (2026-09-25) -- Task 27's tenth slice: polyhedra.cpp

`polyhedra.cpp` (`0x00205058` .. `0x00206440`) is ported in
`polyhedra.{c,h}`. It holds the convex polyhedra the collision bodies hand
to VClip, so it goes in ahead of `CollisionBody.obj`:

- `RectPolyhedron` and `CubePolyhedron`: the box CarCollisionBody and
  Smokeable fall back on when no volume is named for them;
- `WaferPolyhedron::Init`: a track polygon as a solid of no thickness, for
  TrackPolygonCollisionBody;
- `PipelinePolyhedron`: the loader and unloader for chunk `0x80034020`'s
  collision volumes, `FindPipelinePolyhedron`, `MoveCenterOfGravity`, and
  the list's static constructor and destructor;
- the four debug tests nothing calls: TestCubes, InitVoronoiClip,
  RandomLocation and TestVClipRepeatability.

`docs/formats/polyhedra.md` covers all of it.

```
polyhedra_check  55 scenarios, 15907 ops, 64560 lines, 0 differ
                 15708 TRACKB12 polygons (6752 triangles), 93 volume dumps
                 184 mutations: 172 caught, 12 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

This unit is the polyhedron builder the ninth slice listed after
`Collision`. It comes first because CollisionBody calls into it and it needs
only VClip and TrackPolygon. The ninth slice's "Next" and `vclip.md` also
put it, and TrackPolygonCollisionBody's `WaferPolyhedron`, in
Collision.obj. It is its own unit; only the Wafer's destructor is
elsewhere, at `0x001cebc0` in `CollisionBody.obj`. `vclip.md` is fixed.

### What came with it

- `tools/src/polyhedra_test.c` and `tools/polyhedra_check.py`. As with
  VClip, the records hold pointers, so both sides build through the same
  calls, and the transcript names each polyhedron instead of printing its
  address.
- Neither side can take the other's memory, so the harness rebuilds each
  disc container with the host's record sizes (VCVertex 24, VCEdge 16,
  VCFace 32, VCVoronoiPlane 32), padded for where it lies. The model loads
  the disc's own bytes.
- Every one of the disc's 43 volumes loads: one per car, CS_SMOKEBOMB and
  CS_Rocket in INGAMEB, and TRACKB12's 27 props. Every one of TRACKB12's
  15708 polygons goes through `WaferPolyhedron::Init` as the image's
  TrackPolygon constructor builds it.
- The tests throw their results away, so the checker compares what they
  call: the witness constructor, VClip's arguments and the witness it
  leaves, the destructors, bGetTicker, bMalloc and bFree.

### What the listing says

- **The loader never looks at a group's ids**, and the unloader does. A
  header chunk with another id is loaded and linked, then skipped by the
  unloader, and stays listed.
- **A container only loads at its own 16-byte residue.** The pipeline laid
  each array's pad out for where the container lies on the disc, and the
  loader just rounds up.
- **MemoryImageUnload only closes the polyhedron.** The arrays stay as
  pointers into the chunk, so a container unloaded in place is not fit to
  load again.
- **The triangle test is `bEqual3` on corners 2 and 3**, not NumVertices,
  and bEqual3 only fails on a lane *more* than 0.001 apart. 6752 of
  TRACKB12's polygons are triangles by it.
- **A triangle's edges read the quad's face pairs one row down**, so its
  closing edge runs the other way round the faces.
- **DEG and HALF_PI are each one ulp above** the float nearest pi/180 and
  pi/2.
- **TestCounter's add is an `addiu`**, which wraps at 2^31. The port adds
  as unsigned.
- **TestCubes's `NULL` test never fails:** the image's bMalloc asserts in
  bWare rather than return NULL.

No disagreement between the image and the port was found.

### Two things about the tools

- **mipsemu zero-extends a call's arguments.** The image's `lw`
  sign-extends and its `bnel` compares whole registers, so Find of a hash
  with the top bit set missed in the model. The checker passes arguments
  through `s32`.
- **A `--mutate` run's output is block-buffered** when it goes to a file,
  so nothing shows until it ends. Run it with `python -u`. The background
  shell's timeout did not stop the run either. `polyhedra.c` is untracked,
  so a pristine copy was kept in the scratchpad and diffed after each pass.

### The survivors

The first pass left seven unexplained. Four were equivalent:

- scaling a Rect edge of no length by its zero extent. That is NaN on the
  host, which `ee_trunc_w` stores as 0, and 0 on the EE, which has no NaN;
- three of RandomLocation's writes, which eOrthonormalizeMatrix never
  reads and then writes whole.

Three needed cases of their own:

- **len²'s grouping.** `(x·x + y·y) + z·z` and `x·x + (y·y + z·z)` differ
  by enough to move a truncated direction lane for about one random
  vector in 7,000, and for no track edge. float32 arithmetic in numpy
  found three, and the checker runs a quad on each.
- **The cog's `0 - x`** against `-x`. They only part on a +0 cog lane
  added to a -0, and no volume on the disc has a -0. The checker loads a
  car's volume with one vertex's y at -0.
- **TestVClipRepeatability's re-draw.** It only runs when the first pair
  of poses penetrates. The harness alone, with no emulator, tried seeds
  until one did: the 2,291st, `0xea76529b`.

### Next: CollisionBody

`CollisionBody.obj`, `0x001ca1c8` .. `0x001cebb8`, as the ninth slice
listed it. Its bodies now have their polyhedra to build. After it come
`Collision` (`0x0020b290` ..), `World`'s timestep (`0x0014a4e8` ..) and
`Car::FinishMovement`.

## Session 30, continued (2026-09-25) -- Task 27's eleventh slice: the bodies that do not move

The first part of `CollisionBody.obj` (`0x001ca1c8` .. `0x001cebb8`) is
ported in `collisionbody.{c,h}`:

- the NumberAllocator, and `Init/CloseCollisionBody`'s pools, ID table,
  matrices and witness bit field;
- the stats;
- the CollisionBody base class: its constructor and destructor, the list
  sorted on BBoxMax.x, the widest-body bookkeeping, the debug name, the ID
  table, the collision count and the two box tests;
- StaticCollisionBody and its twenty-two methods;
- TrackPolygonCollisionBody, built on the tree's polygons with a
  WaferPolyhedron;
- the CollisionBodyWitness's constructor and destructor, the pair bit
  field, EndCollision, HasExpired, EliminateAllWitnesses,
  DoesWitnessExist and IsYawControlInducingCollisionBody;
- the three virtual tables, and the static initialiser and destructor.

`docs/formats/collision-body.md` covers all of it.

```
collisionbody_check  21 scenarios, 743 ops, 2945 lines, 39 dumps, 0 differ
                     TrackPolygon bodies on TRACKB12 polygons 2 11 1553 1543 40 220 734
                     184 mutations: 175 caught, 9 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

### What came with it

- `tools/src/collisionbody_test.c` and `tools/collisionbody_check.py`. The
  model runs the image with bWare's slot pools, track.cpp's tree and
  polyhedra.cpp's wafers under it. The harness runs the port with track.c,
  polyhedra.c and vclip.c. Records are labelled, not printed as
  addresses, and the heap is filled with 0xa5 so an unwritten field shows.
- **Car's two CarCollisionBody methods moved to `carcollisionbody.c`**,
  `SetupPhysicsPointers` and `SetToPhysicsMode`, with
  `DynamicCollisionBody::GetDistanceAndSpeed`, a stub on the disc. They need car.h and the movers, which
  `collisionbody_check` does not link. `carmode_check` links
  `carcollisionbody.c` and not `collisionbody.c`. car.md, car-modes.md and
  CONTINUE.md name the new file.
- `sinit.c` runs `collisionbody_static_init` at [67], where the image's
  `_GLOBAL_$I$TheCollisionStats` sits, so `sinit_check` now counts 13
  calls. It leaves the three pools to InitCollisionBody.
- `topology.md` no longer lists TrackPolygonCollisionBody as unported.

### What the listing says

- **Two of Init's allocations are short.** SetMaxNumbers takes `n >> 3`
  bytes, so for 206 numbers IDs 200 to 205 are in a twenty-sixth byte, and
  for 7 numbers it takes none. The witness bit field is 5304 bytes for
  42,436 bits, so the pairs (205, 202) to (205, 205) are in a 5305th. The
  image reads and writes both bytes, inside bMalloc's round-up on the
  console. The port asks for one byte more (`COLLISIONBODY_SHORT_SLACK`).
- **The widest-body recompute skips the body that narrowed.** When the
  widest body narrows, the widest becomes the largest of the *other*
  bodies' widths, from 0. A body alone on the list that narrows from 10 to
  5 leaves `MaxCollisionBodyWidthX` at 0.
- **EndCollision drops the counts whether or not there was a collision.**
  Ended twice, a body's `NumCollisions` and the stats go negative.
- **The witness destructor tests the type, not the class.** Any body of
  type 3 left with no witness is destroyed, and the type is read through
  the pointer before the pointer's NULL test.
- **A second body on a taken ID** takes the table entry over, and its
  destructor frees the number the first still holds.
- **Two track bodies on one polygon** each take a reference. The
  TrackPolygon points at the second, and either one's destructor clears
  the pointer.
- **Enable and Disable store a byte.** 127 disabled once more is -128,
  and enabling a negative count takes it further down.
- **The list's ties go by ID, lowest first.** The header's comment said
  the highest; it is fixed.

No disagreement between the image and the port was found.

### What the script must not do

The game keeps rules that the functions do not check. The script keeps
them too, and says why where it builds the witnesses:

- **No witness on a body with a negative ID.** The pair bit
  `ID1 * 206 + ID2` would land before the field. The first script did
  this, and the host wrote junk just before the bit field. In the game
  the only negative IDs are a virgin smokeable's: VirginSmokeable
  (`0x0020c3b4`) gives it `~index`, and MaybeCreateWitnesses calls
  ConvertToSmokeable at `0x001cd2e0` before building the witness.
- **No witness from a body to itself.** Its last destructor would destroy a
  track body twice. The first script had one, and both sides freed a body
  twice.
- **No destroying a type-3 body that still has witnesses,** and no use of a
  body after it is gone.

### Two things about the tools

- **The harness printed the tree's polygon count as 0.** It loaded the
  tree and printed the count in the same printf, and C leaves the order of
  the arguments open. The load is sequenced first now.
- **A mutant that breaks the body list hangs the harness**, for example a
  destructor that does not unlink. The first pass's timeout was 300 s, and
  the hung harnesses were killed by hand at 30 s, which that pass logged
  as "crashed the harness (caught)". The checker's timeout is 30 s now;
  the whole script runs in about four seconds.
- **The tally printed the size of the equivalents list**, not the number
  that survived, so an entry whose mutant was caught went unnoticed. It
  counts the survivors now, and fails on a stale entry.

### The mutation pass

184 mutations: 175 caught and 9 equivalent, with 0
unexplained. The equivalents are listed in `collision-body.md`.

The first pass (184 mutations) left two unexplained, and one listed
equivalent was caught:

- **`width_was_widest`**, `cur == widest` against `<=`. They part only
  when a body that was not the widest narrows. The script had that case,
  but UPDW printed only its inputs and the next op set the widest again
  before a dump. UPDW prints the widest after the call now.
- **`active_detection`**, the accessor answering `CollisionsDisabled`.
  Every body the script read had both at 0. It now reads H10 with -1
  and 0.
- **`pair_bit_swapped`** was listed as equivalent because the field is
  symmetric. DoesWitnessExist answers the masked byte, though, so the
  order picks which power of two comes back. It is off the list.

All three are caught now, and the pass was rerun whole.

### Next: DynamicCollisionBody

Slice B is `DynamicCollisionBody` (`0x001cc8a8` .. `0x001cd710`, with its
inline methods at `0x001ce820` ..): the bounding volumes, the move,
backup and interpolation, and the witnesses it makes against track
polygons and other bodies. MaybeCreateWitnesses reaches
`ConvertToSmokeable`, which is Smokeable.obj's. Slices C (CarCollisionBody),
D (the witness's TestForContact and collision) and E (Contact) follow, and
then `Collision` (`0x0020b290` ..), `World`'s timestep (`0x0014a4e8` ..) and
`Car::FinishMovement`.

## Session 30, continued (2026-09-25) -- Task 27's twelfth slice: DynamicCollisionBody

The second part of `CollisionBody.obj` is ported in `collisionbody.{c,h}`:
DynamicCollisionBody's constructor and destructor, BuildBoundingVolumes,
UpdatePosition, BeginMove, Interpolate, InterpolateVelocity and Backup,
the RigidBody and PhysicsSystem pass-throughs, GetLocalCollisionBodies,
MaybeCreateWitnesses, CreateTrackPolygonCollisionBodies,
TrackPolygonCheck, ChangeInEnergy, the seven inline methods and
`_vt$20DynamicCollisionBody`. Two of its methods are elsewhere:
`GetDistanceAndSpeed` came with Car's sixth slice and is in
`carcollisionbody.c`, and `FindWaferNormal` (`0x001ca460`) belongs to the
contact tests of slice D. `docs/formats/collision-body.md` has a section
for the class.

```
collisionbody_check  39 scenarios, 1039 ops, 8733 lines, 60 dumps, 0 differ
                     TrackPolygon bodies on TRACKB12 polygons 2 11 1553 1543 40 220 734
                     329 mutations: 318 caught, 11 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

### How the checker runs a class with pure slots

The class leaves GetPosition, GetVelocity, GetRotation and
AreCollisionsEnabled pure, so neither side can run it on its own table.

- **D0..D3** are DynamicCollisionBodies in the checker's memory, filled
  with 0xa5 before they are built.
- **Two test tables.** testA is the class's table with those four slots
  pointed at logging stubs, each entry carrying a `this` delta of 8 that
  the caller has to add. testB is testA with Interpolate stubbed as well,
  so Backup's call through the table can be told from a direct one. Each
  side builds both from its own class table: the model copies
  `0x0029bcd8`, and the harness installs them with `vt_install`.
- **S0..S3** answer the stubs: a position, a velocity and a rotation per
  body, which the script sets.
- **PS0** is a PhysicsSystem whose ComputeAuxiliaries entry logs and
  carries a delta of 4. **RB0 and RB1** are RigidBodies the script fills
  word by word. **TC0** is a TopologyCoordinate over the TrackPolygon
  pool's slots. **dpoly0 and dpoly1** are stand-in polyhedra of up to
  eight vertices.
- **The root.** The model runs mipsemu with `eesqrt` and the port calls
  `ee_sqrt`. TrackPolygonCheck's `sqrt.s` (`0x001cd668`) is the one site
  that may take a negative. The model stops if any other site does, or if
  that one never does, so the case cannot fall out of the script unseen.

### What the listing says

- **Every extreme BuildBoundingVolumes finds starts at zero**, so the local
  box always holds the origin, and `if (hi < v) ... else if (v < lo)` is
  the same as two separate tests. The 0.05 margin goes on the cylinder's
  radius, top and base, and not on the sphere or the box. The top is the
  box's z maximum again, and the base is the negated z minimum plus the
  margin.
- **The interpolations' threshold is 1e-6 exactly**, `0x358637bd`, and
  that value is not below it. Past it, f = (BackupTime - t) / BackupTime,
  so t = 0 gives the body as it is and t = BackupTime gives the backup.
  All four lanes are blended and stored, pads included.
- **Backup stores a momentum.** The interpolated velocity is multiplied by
  `Mass` in all four lanes before it goes into the RigidBody's P.
  Interpolate is called through the table and InterpolateVelocity by
  name.
- **MaybeCreateWitnesses reads the widest width after it makes the track
  bodies**, and its walk on trusts that width. A body wider than the
  widest recorded is not reached, and the game can have one: when the
  widest body narrows, UpdateMaxCollisionBodyWidth leaves it out of the
  recount, so it can stay wider than the width recorded.
- **CreateTrackPolygonCollisionBodies keeps 48 and drops the rest without
  a word.** It bubble-sorts them by the tree polygon's address, and when
  the pool fills it returns how many it made. After each body it tests
  the boxes and drops the answer, then asks DoesWitnessExist of a body
  that has just been made and prints the body if a witness exists, which
  it cannot.
- **TrackPolygonCheck's root is `sqrt.s`**, the root of the magnitude. A
  rotation row that dots a little past one with the normal gives a small
  root on the console and a NaN under IEEE. The NaN would drop the
  polygon. Its compare is strict.

No disagreement between the image and the port was found.

### Four things about the tools

- **The harness's vcall printed the start of its line before the call**,
  so a stub's log landed in the middle of it: 40 lines of diff. It prints
  the whole line after the call now.
- **The model's scratch for GetLocalCollisionBodies' outputs overlapped
  the debug name's buffer.** It was moved to `scr+256`.
- **A witness reads both bodies' vertices**, so every H body is given a
  polyhedron before the witness scenarios.
- **The script names TrackPolygons by assignment order, not by pool slot**,
  so it does not depend on the order the pool hands out slots.

`collisionbody_check --mutate` takes `--only NAME,...` now, like
`carmode_check`, and judges only the entries it ran.

### The mutation pass

145 mutations are new, over every Dynamic function, the table, the
install and the layout. The first pass caught 138 and left 7:

- **`dyn_box_y_lt`**: the inlined box test's `b.min.y <= max.y` made
  strict. No box met a dynamic body's bottom edge exactly. H15 now does,
  (12, -2) to (12.5, 0) against D0's bottom at 0, and gets its witness.
- **`dyn_begin_time`**: BeginMove storing 0.5 for t. The script began the
  move at 0.5. It begins at 0.75 now and interpolates at both times.
- **`dyn_mcw_end_min`**: the walk on testing `BBoxMin.x` against the reach
  instead of `BBoxMax.x`. The two only part for a body wider than the
  widest recorded. A new scenario sets the widest to 2 with H6 and H14
  wider, and the walk misses both, as the image does.
- **`dyn_tpc_up_assoc`** and **`dyn_tpc_dist_assoc`**: the two dot
  products added in the other order. Every value in the script summed
  exactly. Two new cases put a tie one rounding away: 1.5 + b + c with b
  and c of -2^-24 is 1.5 one way and just under it the other, against a
  radius of 1.5. An `up` that is 1 one way and 1 - 2^-24 the other adds a
  lean of about 3.5e-4 against a height of 1.
- **`dyn_dtor_vtable`** and **`dyn_ctp_none`** are equivalent. The base's
  destructor overwrites the table pointer first. With nothing kept, the
  sort and the loop that makes the bodies run no times, and n is 0.

The whole pass was then rerun: 329 mutations, 318 caught, 11
equivalent, 0 unexplained.

### The tally in the other checkers

The eleventh slice found that `collisionbody_check` printed the size of
its equivalents list rather than the number that survived, which hid an
entry whose mutant was caught. The same line was in eighteen other
checkers. Each now counts the listed mutants that survived, and fails on
an entry whose mutant was caught or that names no mutation.
`drivetarget_image_check` already did. `emath_check` has no list.

Every checker with a list of equivalents, thirty-four, was then run
whole, seventeen to a copy of the tree, the two copies side by side.
Thirty-three ended rc 0 with no stale entry, 0 unexplained, and the
table's tally. CONTINUE.md had `wheel_check` at 144 caught; it is 145 of
155, and the line is corrected.

`drivetrain_check` ended rc 1: `g-world-time-nonzero` found nothing to
change. `WorldTimeElapsed` moved to `realtime.c` when RealTime was
ported, and the drivetrain harness defines its own, so the mutation had
no port source left. It is `realtime_check`'s now, as `rt-init-welapsed`.
That checker's first scenario holds every one of its eighteen globals'
initial values to the image's, but seven had no mutant to show it:
`WorldTimeElapsed`, `WorldTimeElapsedFrame`, `FrameCounter` and four of
the real clock's. Each has one now. Both reran whole and ended rc 0:
`drivetrain_check` at 176 mutations, 173 caught and 3 equivalent, and
`realtime_check` at 93, 91 caught and 2 equivalent.

### Next: CarCollisionBody

Slice C is `CarCollisionBody` (`0x001cd750` .. `0x001cddc0`, the inline
methods at `0x001ce6c0` .., table `0x0029bc08`): the car's body on top of
this class. SetupPhysicsPointers and SetToPhysicsMode are already in
`carcollisionbody.c`, and the rest goes there too, since it needs car.h.
What it reaches:

- ported: `DynamicCollisionBody`, `FindPipelinePolyhedron` and
  `RectPolyhedron`, `Car::Move`, `SetToPhysicsMode`, `IsBlinking` and
  `IsPoofed`, and `RigidBody::ApplyImpulseWithScaledInverseInertiaTensor`
  (`rigidbody_apply_impulse_scaled`);
- small, to port with it: `RaceCoordinator::IsReplayDemoMode`
  (`0x00134b00`, 16 bytes) and `bStrCat`;
- seams: `CarDamage::AddDamage` (`0x001aba30`), which reaches the damage
  system -- BodyDamage, the position markers, the glass sound,
  TriggerEffect, ApplyDamage -- and is this task's with Car's
  constructor; `tCopManager::MonitorImpact` (task 26);
  `AnimatedDriver::BeginCollision`; and the force feedback,
  `PortRumbleImpact` and `Car::StartForceImpact`.

`DoSnapshot` (`0x001cd950`) is the replay's, and its slot stays empty as
the other tables' do.

Its checker needs a Car and the collision code both, which no checker
links yet. `carmode_check` has the Car but never sets up the collision
lists, which UpdatePosition sorts the body into. The plan is
`collisionbody_check` with a stand-in Car -- only the fields slice C reads
-- and Car's four calls logging on both sides.

After it come the witness's TestForContact, BeginCollision and GetCollision
(D), `FindWaferNormal` with them, Contact (E), `Collision`
(`0x0020b290` ..), `World`'s timestep (`0x0014a4e8` ..) and
`Car::FinishMovement`.

## Session 30, continued (2026-09-26) -- Task 27's thirteenth slice: CarCollisionBody

The third part of `CollisionBody.obj` is ported in `carcollisionbody.c`.
That is all of CarCollisionBody:

- the constructor and destructor, and `new` and `delete` on the pool;
- the three getters and Move;
- ApplyImpulse, AddDamage and AnimateCollisionReaction;
- AreCollisionsEnabled, GetMassInverse and GetInertiaTensorInverse;
- IsBlinking and the five constant methods;
- the inline accessors;
- `_vt$16CarCollisionBody`.

SetupPhysicsPointers and SetToPhysicsMode were already there, from Car's
fourth slice. DoSnapshot (`0x001cd950`) is the replay's, and its slot stays
empty. `docs/formats/collision-body.md` has a section for the class.

```
collisionbody_check  55 scenarios, 1211 ops, 30218 lines, 73 dumps, 0 differ
                     TrackPolygon bodies on TRACKB12 polygons 2 11 1553 1543 40 220 734
                     483 mutations: 462 caught, 21 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

### What came with it

- **`race.c`**: `pRaceCoordinator` (`0x00323330`),
  `racecoordinator_get_current_state`, and
  `racecoordinator_is_replay_demo_mode` (`0x00134b00`).
- **The AI's two tuning switches**, `BoringAIForCameraTuningOn` and
  `WilliamsAITuningMode`, defined in `carcollisionbody.c` until the AI is
  ported.
- **Five seams in `collisionbody.h`**: `CarDamage::AddDamage`,
  `tCopManager::MonitorImpact`, `AnimatedDriver::BeginCollision`,
  `PortRumbleImpact` and `Car::StartForceImpact`.
  - The first three change what happens next, so a NULL one that is reached
    aborts. Nothing sets `pCarDamage`, `pCopManager` or `pAnimatedDriver`
    yet.
  - The rumble and the jolt are only felt, so a NULL one is skipped.
  - `main.c` sets none of the five.
- **`main.c`** installs the car's table after `collisionbody_install_vtables`.
- **`carmode_check`** links `collisionbody.c`, `polyhedra.c`, `vclip.c` and
  `terraintype.c` now, since the car body's constructor, destructor and
  Move reach them.

### How the checker runs a car

`collisionbody_check` gets a stand-in Car rather than Car.obj:

- **CAR0..CAR2** have only the fields a car's body reads, at the image's
  offsets in the model. In the harness they are real Cars. Each has a
  CarTypeInfo named DIABLO, BUS or NOSUCHCAR.
- **PP0 and PP1** are stand-in PipelinePolyhedrons, linked at the list's
  tail as the loader links them and hashed as DIABLO_CV and BUS_CV. PP1's
  centre of gravity is not fixed yet, so the first car on it moves it.
- **Car's four calls** are Move, IsBlinking, IsPoofed and SetToPhysicsMode.
  They are stubs in the model and the harness's own functions in the port,
  and they answer from the script. Move answers from a queue, so a step can
  fall short.
- **The five seams** are logging stubs on both sides. `G_SEAMS` leaves the
  rumble and the force NULL, as the 3DS build does, and quiets the model's
  two stubs, so a NULL seam is shown to skip the call and nothing else.
- **PL0, M0, M1, AD0, DMG0, RC0 and COP0** are what the cars and the
  globals point at. M0 is a PhysicsCar on RB1, and M1 a MellowMover on RB0.
- **A dump** lists the PipelinePolyhedrons and their corners, and a car
  body's box, so the move to the centre of gravity shows.
- **The model** runs `_GLOBAL_$I$RectEdgesNearFaces` to set the list's
  head up, and stubs the two-argument `bMalloc__Fii` the box comes from.

### What the listing says

- **The box** is 4.382 long, 1.942 wide and 0.824 high, off centre in x and
  z: x from -2.217 to 2.165, y ±0.971, z from -0.2 to 0.624. It comes from
  the one two-argument bMalloc in the file, (2800, 16), with no name.
- **The destructor looks the volume up again**, by name and with no centre,
  and destroys `pPoly` only when that finds nothing. That is the box, or a
  disc volume that has left the list. VCPolyhedron's destructor does not
  take a volume off the list, so in the script PP0 is found again by the
  next car on DIABLO.
- **ApplyImpulse's `vmulx` scales all four lanes**, the pad too. The length
  is summed (x² + y²) + z². The clamp holds a car lighter than 1.3 to what
  a car of 1.3 would take.
- **The car's frame** is the transpose of the RigidBody's rotation, applied
  by bMulMatrixVec3 with a w of 1. The transpose's fourth row, zero, comes
  in with it, and w goes into the pad. StartForceImpact gets a copy of all
  four lanes.
- **The rumble tests state 9 twice.** IsReplaying and IsDemoMode are
  inlined, IsReplayDemoMode is called out of line, and then `state − 8 < 2`
  unsigned shuts out 8 and 9. The port's first version subtracted in int32,
  which overflows at INT_MIN, and the script reads that state. It subtracts
  unsigned now, as the image does.
- **The flinch's thresholds, 20 and 4, are built with `lui`** and are
  strict. A NaN in any lane of the impulse is a NaN in every lane of the
  frame's, and a NaN direction is right (8).
- **GetMassInverse's `c.lt.s`** answers a NaN inverse mass as it is.
- **IsBlinking stops at IsBlinking.** IsPoofed is only called when it is 0.
- **The inline Timer getters** answer the Timer in `v0`.

No disagreement between the image and the port was found.

### The mutation pass

156 mutations were new, covering:

- the table and the install;
- every constant;
- each function's tests, branches and arguments;
- the inline accessors;
- the layout.

The first pass caught 138 and left 18:

- **Two were dropped.** One was a signed rewrite of the AI demo test, not a
  mutant: it shuts out the same two states. The other was
  GetDistanceAndSpeed's `*speed`, which is Car's sixth slice's, and
  `carmode_check` has it as `dcb-speed-kept`.
- **Ten are equivalent**, and are listed with a reason each:
  - the constructor's highest-count test as `<=`, and both clamps as `<=`,
    which store the same value;
  - the constructor's clearing of `pSystem` and `pBody`, which Dynamic's
    constructor has already cleared;
  - the destructor's table store, which Dynamic's destructor overwrites;
  - the two AddDamage tests in the other order;
  - either one of the two state-9 tests left out;
  - the x branch's `0 < x` as `<=`, since x is nonzero there;
  - SetupPhysicsPointers reading one mover as the other, since both hold
    the pointers at the same offsets.
- **Six were holes in the script:**
  - **`ccb_ctor_highest_always`.** Every dump came after the count was back
    at its highest. A dump now falls between the two cars made after two
    were destroyed.
  - **`ccb_ai_y_unscaled` and `ccb_ai_z_unscaled`.** The impulses on a
    light car had y and z of 0. One now has all three.
  - **`ccb_ai_sum_order`.** Every length summed exactly. (4.5, 0.1, 0.2)
    sums to different floats the two ways, and their roots differ.
  - **`ccb_ad_no_rumble_seam_test` and `ccb_an_no_force_seam_test`.** The
    harness always set both seams. `G_SEAMS` is new for them.

The whole pass was then rerun: 483 mutations, 462 caught, 21 equivalent,
0 unexplained.

### Next: the witness's contact tests

Slice D is the witness's TestForContact (`0x001cc058`), BeginCollision
(`0x001cbe18`) and GetCollision (`0x001cbde0`), with `FindWaferNormal`
(`0x001ca460`). What they reach:

- **TestForContact:** VClip, which is ported, and
  IsYawControlInducingCollisionBody. It also makes six calls through
  `jalr`, a pool allocation, and `bList::AddSorted`. The
  allocation is a Contact, built by its constructor (`0x001ca268`), and
  the sort uses `Contact::ContactTimeSorting` (`0x001ca240`). All three
  Contact pieces are slice E's.
- **BeginCollision:** a pool allocation and `Collision`'s constructor, from
  Collision.obj, which is not ported.
- **GetCollision:** BeginCollision.
- **FindWaferNormal:** one call through `jalr`.

So D wants Contact's constructor and sort from E, and a seam for
`Collision`'s constructor, the way `~Collision` has one. It may be simpler
to do D and E together. After them come `Collision` (`0x0020b290` ..),
`World`'s timestep (`0x0014a4e8` ..) and `Car::FinishMovement`.

## Session 30, continued (2026-09-26) -- Task 27's fourteenth and fifteenth slices: the contacts

The rest of `CollisionBody.obj` is ported in `contact.c`. Slice D, the
witness's contact tests, and slice E, Contact, were done together, because
TestForContact builds a Contact with E's constructor and sorts it with E's
ContactTimeSorting. That is:

- InitContact and CloseContact;
- RemoveContacts, ContactTimeSorting and `bList::AddSorted` (`0x00238290`);
- Contact's constructor, FindContactTime, Crowbar and Resolve;
- FindContactPointAndNormal, FindPlanarCollisionContactPoint,
  GetContactPointVelocity and DenominatorTerm;
- CollisionImpulse;
- the inline `~Contact` and its delete, which World.obj emitted
  (`0x0014c188`, `0x0014c330`);
- the witness's FindWaferNormal, GetCollision, BeginCollision and
  TestForContact.

`docs/formats/collision-body.md` has a section for Contact and one for the
witness's contact tests.

```
collisionbody_check  81 scenarios, 1572 ops, 35426 lines, 89 dumps, 0 differ
                     TrackPolygon bodies on TRACKB12 polygons 2 11 1553 1543 40 220 734
                     646 mutations: 622 caught, 24 equivalent, 0 unexplained
```

Nothing is committed since `409501b`.

### What came with it

- **Two seams in `collisionbody.h`** for Collision.obj, which is not
  ported: `gCollisionNewFn`, BeginCollision's `new Collision(w, pt)`, and
  `gCollisionAddImpulseFn`, `Collision::AddImpulse`. A collision is state
  the sound and the damage read, so a NULL one that is reached aborts.
  Nothing sets either yet.
- **`ContactSlotPool` and the five tuning globals** at `0x003243d8` ..
  `0x003243f8`, at the image's values. The four between them that nothing
  reads (ContactDebug, Restitution, TestImpulse,
  ContactFrictionCoefficient) are left out.

### How the checker runs a contact

- **E0..E3** are DynamicCollisionBodies on testC. That is Dynamic's table
  with the nineteen slots a contact calls pointed at logging stubs, each
  with a `this` delta of 8. What each body answers comes from the script's
  `E_STATE`:
  - its position, velocity and rotation;
  - its current velocities and inertia tensor inverse;
  - its maximum backup, mass inverse, bounciness and friction;
  - whether it moves and whether it blinks.

  Interpolate backs the position up along the velocity, and ApplyImpulse
  adds the mass inverse times the impulse to the current velocity.
  ConsiderImpulse answers a queue the script fills, then 1.
- **B0..B3** are RectPolyhedra that give them shapes. Two track bodies sit
  on TRACKB12 polygons whose vertices are rewritten as a flat quad and a
  leaning triangle.
- **A contact is named** by its pool slot (Xn), by its place on clist, or
  as the newest. The pool's free list runs last in, first out, so the
  script cannot predict the slots.
- **The Collision's two seams** are stubs in the model and the harness's own
  functions in the port. Both log.
- **Two stack lanes** are loaded without being written: FindContactTime's
  zero and FindPlanarCollisionContactPoint's up. The model zeroes both
  words, since the port writes them zero.
- **`eediv`**: the model stops if any division but CollisionImpulse's
  friction (`0x001cb278`) divides by zero, or if that one never does.

### What the listing says

- **The vectors are VU0's.** Every operation is all four lanes. A dot
  product is (x + y) + z, and a cross product keeps its first operand's
  fourth lane. Turning a vector round is `vsub` from vf00, so its fourth
  lane comes out 1 − w. A normalise of a zero length gives FLT_MAX.
- **CrowbarVector's pad is stack junk on the console.** FindContactTime
  zeroes it from a quadword whose fourth lane is never written. The port
  writes zero.
- **The list runs from the longest backup down**, and a tie goes after.
  ContactTimeSorting answers 0 only when the new contact backs up further,
  and AddSorted inserts before the first 0.
- **Crowbar tests the type, and FindContactPointAndNormal tests
  `Dynamic`.** A static body that is not a track polygon's would have its
  polyhedron read as a wafer by the second. The script does it to a
  dynamic body with `Dynamic` cleared.
- **Crowbar adds its step up**: s grows by 0.05 twenty times. A crowbar that
  fails leaves CrowbarVector as it was.
- **Only one negative answer is negated.** If ConsiderImpulse's first answer
  is negative it is negated, and otherwise the second's is. With both
  negative, the second stays negative and is the lesser, so j turns round.
- **The pull is always 0.4.** It starts as a fortieth of the scraper's
  velocity, but past 30 that is always past −0.4, so it is −0.4 / speed.
  z is then zeroed, and the image picks the side by comparing m1 with that
  zeroed z. The shortened lever arm stays for later rounds.
- **The friction divides by the slide.** A car dropped straight onto flat
  ground has none, and −0 / 0 is FLT_MAX on the EE, which the zero slide
  then makes 0. IEEE makes it NaN, which would reach both bodies. The port
  calls `ee_div` there.
- **A blinking car still hits the track.** It only goes through a body when
  both are dynamic.
- **BeginCollision makes a Collision without looking at the one there.**
  GetCollision is the one that tests.
- **FindPlanarCollisionContactPoint has no callers.** It moves the point
  onto the plane through both centres that is square to up's part across
  the line between them, which is horizontal for two level bodies. The
  header's comment called it vertical and is fixed.
- **0x001cb4f0 .. 0x001cb57c** holds more copies of the inline destructor
  and delete, and three thunks, none of them named. RemoveContacts calls
  World.obj's copy.

No disagreement between the image and the port was found.

### The mutation pass

163 mutations were new, covering:

- the four-lane helpers: the pads, vf00's 1, the dot product's order and
  the cross product;
- the pool, the list, the sort and AddSorted, and the destructor;
- every tuning global and literal;
- each function's tests, branches, arguments and order of calls.

The first pass caught 156 and left 7:

- **Three are equivalent**, and are listed with a reason each:
  - the pull's −0.025, which past 30 is always replaced;
  - the lever arm's `1 < speed + len` test, which past 30 always holds;
  - the lever arm's length taken from jn, whose first three lanes are
    jt's negated.
- **Four were holes in the script:**
  - **`ct_imp_jmin_times`.** Every floor case had a larger mass inverse of
    1, where dividing and multiplying agree. One now has 0.5 and 0.25.
  - **`ct_imp_scrape2_any`.** No case had a first body that is not a car
    against an immovable second. The mirror of the first branch's case is
    in now.
  - **`ct_test_blink_stamp2_any` and `ct_test_yaw2_any`.** Both cases were
    in the script, but the next test stamped the second body as a car
    before any dump. A dump now follows each.

The whole pass was then rerun: 646 mutations, 622 caught, 24 equivalent,
0 unexplained.

### Next: Collision

`Collision.obj` is `0x0020b238` .. `0x0020b87c`, about fifteen functions:
InitCollision and CloseCollision, the constructor (`0x0020b290`) and
destructor, AddImpulse (`0x0020b450`), Update, End, GetTerrainType, four
questions about which bodies are involved, and the delete. It fills three seams: the two
above and slice A's `gCollisionDestroyFn`. DoSnapshot is the replay's.
After it come `World`'s timestep (`0x0014a4e8` ..), whose
DoTimestepCollisions (`0x0014b110`) asks the witnesses for contacts and
resolves them, and `Car::FinishMovement`.

## Session 30, continued (2026-09-26) -- Task 27's sixteenth slice: Collision

Slices 1 to 15 went in as `b702739`. The sixteenth is `Collision.obj`
(`0x0020b238` .. `0x0020b87c`), ported in `collision.{c,h}`, with World's
two GetDistanceToClosestPlayer overloads (`0x0014bb60`, `0x0014bbb8`) in
`world.c`. That is:

- InitCollision and CloseCollision, on a 32-slot `CollisionSlotPool`;
- the constructor, the destructor and the delete;
- AddImpulse, which sums the impulse and its length and fires the scrape
  and impact particles near a player;
- Update, End and GetTerrainType;
- IsTwoCarCollision, GetCollidingCars, IsPlayerInvolved and
  IsSmokeableInvolved.

DoSnapshot is the replay's and waits on ReplaySnapshot. The decode is
`docs/formats/collision.md`.

```
collision_check      15 scenarios, 3587 ops, 6859 lines, 0 differ; 134 effects triggered
                     131 mutations: 121 caught, 10 equivalent, 0 unexplained
```

### What came with it

- **Four seams out, each skipped when NULL**: the sound's CreateSample,
  ReleaseSample and PlayScrape (task 29), and
  `TerrainEffectEmitters::TriggerEffect` (task 30). A skipped CreateSample
  answers NULL, as the sound does with no voice free.
- **Three seams in**: `main.c` now points `collisionbody.h`'s
  `gCollisionNewFn`, `gCollisionAddImpulseFn` and `gCollisionDestroyFn` at
  `collision.c`. A witness's first touch on hardware makes a real
  Collision.
- **World's fields up to PotentialDriveTargetID** in `world.h`, with
  asserts on the console offsets. PlayerPositions (336, 352) is what the
  distances read.

### What the listing says

- **The scrape's "faster body" is always body 1.** AddImpulse calls
  GetVelocity on body 1 twice and compares the first length with itself.
  The test never holds, so the particles get body 1's velocity. Both calls
  are made, so the port makes both.
- **ROAD's scrape range is 50 to 50.** The divide is x / 0 there, FLT_MAX
  on the EE; the clamp brings it to 1 either way, but the port uses
  `ee_div`.
- **Update never reads its argument.** The age is
  `(float)(int)(WorldTimer - LastContactTime) * 0.00025`, so a contact
  stamped after now counts as live, and 1200 ticks is exactly 0.3's float,
  not below it.
- **The two distance overloads differ.** The bVector3 one is VU0 in three
  dimensions and gates the sound at 100; the bVector2 one is scalar on the
  ground plane and gates the particles at 50.

### How the checker runs it

The model runs the image's own InitCollision, bNewSlotPool, bOMalloc and
bFree, and the harness runs `bslotpool.c`, each on a block the script owns.
So a collision is labelled by its slot (Cn), and the order a freed slot
comes back in is checked. R0 and R1 are built outside the pool on 0xa5
memory, which shows every field the constructor skips. The bodies share one
recording vtable, whose velocity and terrain slots take `this` eight bytes
in. The sound, the particles and the witness's EndCollision log on both
sides.

### The mutation pass

131 mutations. The first pass caught 119 and left 12:

- **Ten are equivalent**, each listed with a reason:
  - the lifetime one ulp down, since no whole number of ticks lands between;
  - the scrape's floor and plain divide, and the impact's floor, since
    each quotient is never negative;
  - three on the scrape's velocity, since both calls answer body 1's;
  - three on `min.s`, since a distance is never NaN or -0.
- **Two were holes**: `tick-near` and `upd-divide`, both of which changed
  how the age is scaled. `ticks * 0.00025f` and `ticks / 4000.0f` round
  apart at 5 ticks (3aa3d70b against 3aa3d70a). The new scenario sets the
  lifetime one ulp above each age's product at 5, 1200 and 4000 ticks.

The rerun: 131 mutations, 121 caught, 10 equivalent, 0 unexplained. The
checkers that link `world.c` or the witness (car, physicscar,
realcontroller, realdriver, carmode, collisionbody) were rerun after it,
all 0 differ, and the CIA built at 316,352 bytes.

### Next: World's timestep

DoTimestepMove (`0x0014b050`) and DoTimestepCollisions (`0x0014b110`),
which asks the witnesses for contacts and resolves them, then
FlushCollisions, Random, GetCarByNumber, GetDATToClosestPlayer and
GetTimestep. Smokeable::Break and DeleteFarAwaySmokeableCollisionBodies
become seams. Then `Car::FinishMovement`.

## Session 30, continued (2026-09-26) -- Task 27's seventeenth slice: World's timestep

The sixteenth slice went in as `4ad0652`. The seventeenth is the part of
`World.obj` that runs every frame (`0x0014ab08` .. `0x0014bce0`), ported
in `worldstep.c`, with bList::Sort (`0x00238328`) in `blist.c`. That is:

- the clock: SetTimeScale, ResetTimeScale, SetWorldPaused, BeginPause,
  EndPause, UpdateWorldPaused, IsWorldPaused and GetTimestep;
- the car table: BuildCarTable, GetCarByNumber, GetCarByDriverNumber,
  CarListCheckFlip and AddTrafficCar;
- the two Random overloads, GetDATToClosestPlayer and FlushCollisions;
- CalculateDebugChecksum and VerifyDebugChecksums;
- DoTimestepMove, DoTimestepCollisions and DoTimestep.

The constructor, the destructor, the collision prediction and the debug
views are the next slice. DoPointerSnapshot waits on ReplaySnapshot. The
decode is `docs/formats/world.md`.

```
world_check          24 scenarios, 2173 ops, 12963 lines, 0 differ; 85 steps
                     200 mutations: 200 caught, 0 equivalent, 0 unexplained
```

### What came with it

- **Twenty seams out**, in `world.h`: the teleporter's DoTimestep and
  PlaceNewCar, GlobalCopThink, Chopper::Fly, five Car methods
  (DoWheelForces, FinishMovement, TriggerEvents, MaybeCameraShake,
  MaybeRumble), the particles, WorldEffects' TweakerCheck and DoTimeStep,
  the events, the players' game state, the rain, the ferns, the tweaker
  damage, the route editor, Race::Update and
  RaceCoordinator::PostMessage. A NULL one is skipped, apart from
  FinishMovement, which moves a car to where its collisions left it, and
  PlaceNewCar, which AddTrafficCar has nothing to add without. Both
  abort.
- **`smokeable.h`**, Smokeable's head up to pSmokeableSpawner, with
  Break (which aborts when reached unset) and
  DeleteFarAwaySmokeableCollisionBodies (skipped) as seams.
- **`blist.c`**: bList::Sort, a bubble sort that swaps a pair in place
  and keeps going until a pass moves nothing.
- `TweakerPauseWorld` (gp-22620) is defined in `world.c`.

### What the listing says

- **GetTimestep reads pReplayManager twice, with no NULL test.** While the
  replay plays back, it spins on the ticker until the step has taken as
  long as it did when it was recorded. The wait is
  `min.s 0.3, max.s(x, 0)`, and with a NaN clock the order of the
  operands decides whether 0.3 or NaN comes out. The spin compares the ticker's
  milliseconds times 0.001 with `<`.
- **The pause and the time scale share one callback.** Each clears it
  after it runs. The pause counts down by RealTimeElapsed, the time scale
  by the step.
- **The car table leaves out a car of no known type.** It is players, AI
  racers, cops and super cops, then traffic, each group in list order.
- **DoTimestep reads the counts again after every car.** A player with no
  player object gets 9999999 in three lanes and its fourth left alone.
- **The shake test is made twice.** Once before the loop, and again
  before each car's rumble, so a MaybeCameraShake that changes the race
  state stops the rumble for the cars after it.
- **DoTimestepCollisions resolves at most 20 rounds** and then destroys
  what is left. A witness is tested once for each broken piece on it.
- **VerifyDebugChecksums posts RC_SKIP_REPLAY** only while replaying,
  only when not capturing, and only when the low byte differs.

### How the checker runs it

The model runs the image's World.obj, bRandom, bList::Sort,
GetRealTimeElapsedFromQuantized, bGetTickerDifference, IsReplayDemoMode
and ~bTList<Contact>, and the harness runs the port. Everything else the
step calls is a stub on both sides with the same simple semantics:

- the Car methods log;
- a witness's destroy and a collision's End unlink the node and zero both
  links, so a walk through a freed node falls over;
- TestForContact and MaybeCreateWitnesses append what the script queued,
  unless it is on the list already;
- RemoveContacts unlinks every contact on a body, and Break writes the
  pieces the script queued;
- the replay's and the Joylog's data, CompareDistances and bGetTicker
  answer from queues.

MaybeCameraShake can change the race state from inside the loop.

### The mutation pass

200 mutations. The first pass caught 193 and left 7, each a hole:

- **`waste min swapped` and `waste max swapped`**: the clock is now driven
  through a NaN.
- **`waste spin <=`**: ticker readings either side of exactly 0.3 s of
  wait (89,999,996 to 90,000,011 ticks all give exactly 0.3f).
- **`verify rget unmasked`**: a replay byte with high bits, after a drain
  so no stale reading answers it.
- **`move schedule 63`**: loop count 115, where `+ 77` is a multiple of 64
  but not of 128.
- **`step events <=` and `step terrain <=`**: player 0's car at the
  origin, and cars exactly 100 and 150 from it.

The rerun: 200 mutations, 200 caught, 0 equivalent, 0 unexplained. The
CIA builds with no warnings.

### Next: World's constructor and destructor

The constructor (`0x0014a4e8`) and destructor (`0x0014a748`), the record's
tail (the prediction's OBBs, positions, indices and drive targets, to
5936), the collision prediction's recorders, DebugDisplay and
UpdateAIDebugRendering. OBB's methods and GetVectorOnTrack come with them.
Then `Car::FinishMovement`.

## Session 30, continued (2026-09-26) -- Task 27's eighteenth slice: World's constructor and destructor

The seventeenth slice went in as `2a1661c`. The eighteenth is the rest of
`World.obj` but DoSnapshot and DoPointerSnapshot, ported in
`worldinit.c`:

- the constructor (`0x0014a4e8`) and the destructor (`0x0014a748`);
- DebugDisplay (`0x0014bd30`);
- the collision prediction's four recorders, SetOBBs, SetDriveTargets,
  RecordPotentialDriveTarget and RecordIteration, none of which has a
  caller in the shipped game;
- UpdateAIDebugRendering (`0x0014bed0`).

The record's tail is in `world.h` now: the prediction's forty OBBs, eighty
positions, eighty indices and three DriveTargets, to 5936. The decode is
`docs/formats/world.md`.

```
world_check          32 scenarios, 2742 ops, 15110 lines, 0 differ; 85 steps
                     328 mutations: 328 caught, 0 equivalent, 0 unexplained
bslotpool_check      18 scenarios, 1025 lines, 0 differ; 47/47 mutations caught
track_check          16212 ops, 11821 lines, 0 differ; 273 caught, 5 equivalent
```

### What came with it

- **`obb.c`**: OBB's constructor, destructor, operator=, Render,
  DoNotRender and Print, the last methods in DriveTarget.obj. DoSnapshot
  waits on ReplaySnapshot. **`worldobject.h`** names WorldObject up to its
  Matrix, and has its new and delete as seams, which is all Render needs.
- **`bplist.c`**: bPListInit, bPListClose, bPNode::Malloc and
  bPNode::Free, the pool the destructor gives AICarList's nodes back to.
  It is apart from `blist.c` so that world_test can stub the pool.
  `bslotpool_check` runs it on the real allocator.
- **GetVectorOnTrack** (`0x001c1210`), in `track.c`, which puts the
  prediction's positions on the ground. `track_check` runs 31 points
  through it, the bridge and the edges of the world among them.
- **Twenty-five seams**, in `world.h`: the eleven Init calls, eleven of
  the twelve Close calls (EliminateAllWitnesses is `collisionbody.c`'s),
  the TrafficTeleporter's constructor and destructor, and Car's
  destructor. The Init and Close calls are skipped when NULL. The other
  three abort, the constructor always and the destructors when there is
  something to destroy.

### What the listing says

- **The destructor closes in nearly the constructor's order reversed.**
  The terrain effects, the cops and the track graph close in the order
  they opened, and the clans before the skids. EliminateAllWitnesses
  comes fourth.
- **The members go in reverse**, the drive targets first, then the other
  car's boxes 19 to 0, then this car's, then CollisionList, AICarList and
  CarList. Each list's destructor unlinks a node and destroys it without
  touching the node's own links. WorldLoopCounter goes back to 100000.
- **The constructor leaves the car table, CarPositionTable and the
  prediction's records alone.**
- **OBB's operator= moves the cube.** It copies all four lanes of each
  axis and not the Position, deletes the destination's cube and takes the
  source's, so a box assigned to itself loses its cube.
- **Render never tests what bOMalloc returned**, and calls bStringHash
  ("DEBUG_CUBE") every time it makes a cube.
- **DebugDisplay reads AICarPos and CopCarPos again after each call.**
- **UpdateAIDebugRendering reads the chosen iteration twice**: once for
  the box indices and this car's position, and again after the first
  GetVectorOnTrack, for the other car's. The test is `max < it`, so the
  last recorded iteration is drawn.
- **A driver number that no car has is dereferenced.** The listing reads
  pCarDriver at 44 through a NULL car. The port passes NULL instead.

### How the checker runs it

The model runs the image's World.obj, OBB's methods, eIdentity and
eMulMatrix. Everything else is a logging stub on both sides:

- the Init and Close calls, bMalloc and bFree;
- the teleporter's constructor and destructor;
- Car's and Collision's destructors and bPNode::Free, which log the
  node's links and then zero them;
- DriveTarget's constructor, destructor and operator=;
- the DriveTargetRenderer;
- WorldObject's new and delete, which hand out cubes from a table.

A controller's DebugDisplay can move AICarPos and CopCarPos, and
GetVectorOnTrack, which swaps its two lanes so both calls show, can change
the iteration to render. That is what shows both are read again.

### The mutation pass

128 new mutations, on top of the timestep's 200. The first pass caught
127 and left 1, a hole:

- **`render mul order`**: `eMulMatrix(&out, &id, &m)` for
  `eMulMatrix(&out, &m, &id)`. The two differ only in signed zeros and
  NaNs. Each column of `I × m` adds the identity's fourth row times zero,
  a +0, so only an axis that is -0 in one lane and negative in the rest
  keeps its -0, and only in `m × I`. One box like that is in the script
  now.

The rerun: 328 mutations, 328 caught, 0 equivalent, 0 unexplained.
`bslotpool_mutate.py` takes an optional file per mutant now, and its ten
bPList mutants are all caught (47/47). GetVectorOnTrack's seven, in
`track_check`, are all caught. The CIA builds with no warnings from the
port's sources (only the devkitARM `crtn.o` one), at 316,352 bytes: the
linker drops the new code, since nothing on the boot path reaches it.

### Next: Car::FinishMovement

`Car::FinishMovement` (`0x00130480`, 2008 bytes), which DoTimestep calls
for every car and which aborts while it is unset. `car.md` has its
outline. Then the track's rendering and streaming, and
RaceCoordinator::InitForRace (`0x001473c0`), which is what will build a
World outside a harness.

## Session 30, continued (2026-09-26) -- Task 27's nineteenth slice: Car::FinishMovement

The eighteenth slice went in as `eac3756`. The nineteenth is
`Car::FinishMovement` (`0x00130480`, 2008 bytes), which World's step calls
for every car once the moves and the collisions are done. It is in
`carfinish.c`, apart from `car.c`, because it reaches Collision, the
world's car table and the Player, and `car.c` links into checkers that
carry none of them. Car is 63 of 80 methods now, 12456 of 22876 bytes. The
outline is in `docs/formats/car.md`.

```
carmode_check   74 transitions, 19 resets, 36396 lines, 103 masked, 0 differ
                88 new mutations: 82 caught, 6 equivalent, 0 unexplained
                505 in all: 491 caught, 14 equivalent
```

### What came with it

- **`main.c` sets `gCarFinishMovementFn`**, which aborted while unset, so
  World's step can run a car through to the end of its frame.
- **Four Player seams**, in `car.h`: ClearZone (`0x00171c70`), RequestZone
  (`0x00171610`), IsJumpCamAvailable (`0x00170408`) and CleanUpJumpCam
  (`0x00170488`). They move the camera between zones, which changes the
  game, so they abort when unset. Only a player's car reaches them.
- **`player.h` names three more fields**: `nZoneCurrent` (76), `bWrongWay`
  (736, already there) and `EyeVerts` (1600), with a layout check.
- **`g_DisableAutoReplay`** (`0x00323040`), Car.obj's and 0 in the image,
  is in `car.c`.
- **TrackPathCoordinate::ResetPosition** (`0x00134f18`, twelve bytes Car.obj
  emitted) is in `trackpath.c`. It zeroes the point in a tail jump's delay
  slot, so UpdatePosition searches afresh.

### What the listing says

- **The accelerations are VU0's**, over all four lanes with the pad. A
  denormal `dt` passes `0 < dt`, and the EE's `div.s` then reads it as
  zero, so `1 / dt` is `ee_div`'s FLT_MAX.
- **The odometer's two tests are both `<`**, so a NaN speed is added.
- **The three phases never meet**: the topology on `loop ≡ 25 (mod 32)`, the
  player's section on `loop ≡ 5 (mod 8)`, the search on a multiple of 60.
  The remainder is signed, so -60 searches.
- **The topology is asked twice**, at the car and a metre along +x, and only
  a miss at both marks the car for a reset.
- **A car past 5000 is never searched afresh**, even when the camera tuner
  keeps it, because the two distance tests are an if and an else.
- **The yaw is CarState::GetYaw's**, which is 0 below a ForwardSpeed of 5.
- **AverageAir starts from three seconds.** A jump under 0.9 s switches the
  zone back after five seconds, a longer one after half of it.
- **The first RequestZone skips the zone's own timer**, and only its answer
  decides the clean-up. The zone is read again after it.
- **CloseCars runs `AICarPos` up to `CopCarPos`** with no NULL test on the
  world, and does not skip the car itself.
- **The contact's age is signed**, so a stamp in the future is young.
- **RegisterInterestingEvent is called with no test** on `pReplayManager`.
  The port tests it, as `carreset.c` does, and the name is never read.

Three things are left out because they change nothing: the colliding cars'
swap after CarCollision, which nothing reads (the call is kept); the debug
tail behind `DoScreenPrintf` and `TerminalPrintPosition`, both 0; and the
second `30 < speed`, which the first has passed.

### How the checker runs it

`carmode_check` runs one more scenario, 105 cases, after the terrain
effects. Both sides make a player, a world whose table holds the car and
four others, a Collision, a witness and a plain body. Each case sets the
car's motion, the odometer, the wheels, the track path coordinate, the
counters and switches, the player's three fields, the table's positions
and the collision. The topology's answers are scripted one per question,
and a leftover answer fails the case. The four Player calls log, and
RequestZone answers as the case says. The replay's snapshots are zeroed
before the call and printed after it, which is where the events show.

The no-point case did not work the first time. With NumPoints at 0 the
search still found a point, because `trackpath_find_closest_point` walks the
paths. Zeroing NumPaths gives the NULL point, and the case is `nopaths` now.
AverageAir's edges (exactly 0.9 s, exactly 0.5 s, exactly 1.5 high) were
found by reading the image's frame after the call. The stack is scrubbed
around the call, and no line of the scenario is masked.

### The mutation pass

88 mutations. Four cases went in for them before the pass: `+0` speed on a
`-0` odometer, loop 9, a `-0` eye height under a `+0` car, and two cars at
exactly 40. The first pass caught 82 and left 6, all equivalent:

- **`fm-air-yaw-le` and `fm-slide-le`**: a yaw's `<` against `<=`. A scan of
  all 65536 BAM differences finds none exactly on 3.14/32 or 3.14/8; the
  cases sit on the nearest pairs (1023/1024 and 4093/4094).
- **`fm-air-name`**: the event's name is never read.
- **`fm-col-no-colliding-cars`**: the call's two answers are never read.
- **`fm-col-smoke-no-else`**: the first branch needs two car bodies, and
  then neither is smokeable.
- **`fm-col-smoke-no-speed`**: the second `30 < speed`.

Six mutants crash the harness, which counts as caught: the four that move,
widen or cut short the topology's test, `fm-close-with-cop`, which reads a
NULL slot past the table's cars, and `fm-replay-untested`. The eight
equivalents from the earlier slices were rerun and still survive.

The whole checker suite passes. The CIA builds with no warnings from the
port's sources (only the devkitARM `crtn.o` one), at 319,936 bytes, up
from 316,352: `main.c` now reaches `carfinish.c` and `collision.c`.

### Next: the track's rendering and streaming, and InitForRace

RaceCoordinator::InitForRace (`0x001473c0`, 500 bytes) is what will build a
World outside a harness. Most of what it calls is not ported: the
`Player(JoystickPort, int)` constructor, the ReplayManager and Race
constructors, InitCars (`0x00147ce8`, which needs Car's constructor),
InitPlayers (`0x001476e8`), Race::Init, SetupGhostCars,
SetAIDriverModesFromPlayers, and the speech and collision-sound resets.
The World constructor it calls is ported.

## Session 30, continued (2026-09-26) -- Task 27's twentieth slice: Scenery.obj's data half

The nineteenth slice went in as `16323fa`. The twentieth is the first of
`Scenery.obj` (0x0014c3a0 .. 0x0014e734), the track's scenery as it comes
off the disc and the visible zones that say which of it to draw. It is in
`scenery.c`. This half is the data: the loader and the unloader, the three
finds, the zones' lookups, the debug tables, the facade matrix, the
backwards-track flip and the statics. The cull is the next slice. The
decode is in `docs/formats/scenery.md`.

```
scenery_check   17 scenarios, 3450 ops, 16724 lines, 0 differ
                2843 models built
                79 mutations: 77 caught, 2 equivalent, 0 unexplained
```

### What the disc holds

TRACKB12 has 122 section containers and one zone chunk of 23 zones.
TRACKA12 is empty, and TRACKB12.BUN is loaded whole: no scenery streams by
section. Each container's children come as header, objects, kinds, tree.
There are 2108 kinds, 7765 objects and 1967 tree nodes; 28 kinds are
facades, and no object has the flip's bit, 0x400.

### What the listing says

- **The loader trusts the order.** A child before the header writes
  through a NULL header, and a second kinds chunk replaces the first.
- **The objects' count is unsigned** after the pad, so a pad larger than
  the chunk wraps it.
- **A LOD with no name keeps its pointer from the disc**, and the unloader
  destroys it if it is not NULL.
- **The flip is on a direction of exactly 1.** A direction of 2 does not
  flip. The position goes through the matrix's fourth row and back, pad
  and all, and comes out unchanged.
- **The unloader finds the header only as the first child.**
- **FindVisibleZone moves the zone it finds to the list's head.**
- **IsPointInPoly counts a vertex on the scanline for the edge above it
  only**, and multiplies before it divides.
- **FindNextFreeIndex does not catch a count past 64.**

### What came with it

- `sinit.c` calls `scenery_static_init` as `__CTOR_LIST__[21]`
  (0x0014e718), which empties both lists.
- eModel is named in `scenery.h`, 24 bytes. eModel::Init and the deleting
  destructor are `gEModelInitFn` and `gEModelDestroyFn`, which abort when
  reached unset; `eModelSlotPool` is NULL until the renderer makes it.
- On a 64-bit host the header, the kinds and the zones widen, and the
  harness rebuilds each container with them widened, each child at the
  misalignment the image sees.

### The mutation pass

79 mutations, 77 caught and 2 equivalent: the model's pointer stored after
Init rather than before (Init reads the model and the name, not the kind),
and the flip's fourth row given a w of 0 (it is never read back). Eight
mutants stop the harness: six crash it and two hang it, which is why the
checker's timeout is 30 s now.

The pass found one port bug. FindIndexTo read its shorts through
`VisibleScenerySections[i]`, and GCC at -O2 took the array's 64 as a bound
on the count, so `== 64` and `>= 64` compiled alike. It reads from the
zone's base now.

### Next: the cull

ClassifyAABB (0x0010b940) is VU0: the eight corners through the clip
matrix and `vclipw.xyz` on each, read back through the clip register.
`mipsemu` now models `vclipw`, `ctc2` and `cfc2` on vi18. Then the tree
cull, DrawAScenery, the section lists, DoCulling, StuffScenery and
eDisplayFrame's SetupSceneryCullInfo, with Ecstasy.obj's frame malloc.

## Session 30, continued (2026-09-26) -- Task 27's twenty-first slice: the scenery cull

The twentieth slice went in as `b73b760`. The twenty-first is the second
half of `Scenery.obj` (0x0014d460 .. 0x0014e59c): which of the loaded
scenery each view draws this frame, and in what matrix. With it come
ClassifyAABB and IsBoundingBoxVisible (0x0010b940, 0x0010bb10),
SetupSceneryCullInfo (0x0010e370), eDisplayFrame's loop over the views
(0x00112d18 .. 0x00112df0), Ecstasy.obj's frame malloc and the table of
ten eViews. That is 17 functions and 4,608 bytes, in `scenerycull.c`,
`eframe.c` and `eview.c`. The decode is in `docs/formats/scenerycull.md`.

```
scenerycull_check   9 scenarios, 7273 ops, 46687 lines, 0 differ
                    11623 draws, 7205 renders
                    148 mutations: 147 caught, 1 equivalent, 0 unexplained
```

### What the listing says

- **ClassifyAABB reads each face's four corners separately** out of the
  clip register. Both faces must be clear for a 2, and a 0 needs one flag
  on all eight corners. A corner exactly on a plane is inside, and a NaN
  is inside.
- **DrawAScenery takes any class but 1 as given**, 0, 3 and 5 included.
  Only a 1 classifies the object's own box.
- **A NULL LOD is skipped, not taken as the end** of the LODs.
- **The frame malloc is inline in DrawAScenery**, `pos + 64 < end`
  unsigned, and does not count `FrameMallocAllocNum`. A full draw table
  drops the object after its matrix has been taken.
- **Neither tree cull checks for a missing tree**, and a child count past
  five reads on into the next node. The stack is 64 deep with no test.
- **WhatSectionsShouldWeDraw** draws every section below 100 with no
  zone. With a zone, it draws the loaded nineties first, then the zone's
  list in its own order, duplicates and all. Only view 1 sets
  `CurrentZoneNumber`.
- **The environment-map test on the view ID is unsigned** (`sltiu`), so
  an ID of −1 or 0x80000004 is not one.
- **The facade's position z goes nowhere**: DrawAScenery writes the
  position over the matrix's last row straight after.

### The checker

The model runs eDisplayFrame's loop in place, from 0x00112d18 to a stub at
the DoCulling call, with the grand info at s7. eModel::Render, bMalloc
and bFree are stubbed and print their calls. VU0's `sqc2` drops an
address's low four bits, so every frame-malloc position the script sets is
16-aligned. The model leaves a 64-byte gap after each buffer, so that a
block past the end is named as past it, and not as the next buffer.

### The mutation pass

148 mutations: 147 caught, 1 equivalent. Seven of the catches crash or
hang the harness, so the timeout is 60 s. The equivalent one is the
facade's z given the object's y.

Six survived the first pass, and all six were float reassociations: the
minimum's four-term sum, the far corner's two edges, the dot product,
the distance, `r * (H / f1)`, and `r <= f1`. Each is exact on most
inputs. A search in float32 found one case for each where the other order
rounds across a plane, the 2 or a far clip. The image's order holds in
every one, and the port had it right.

### Next: eView.obj's matrices

The cull reads WorldViewMatrix, WorldScreenClipMatrix and H from a view.
`eView::CalculateViewMatricies` (0x00106700) and `CreateViewMatricies`
(0x0010d268) make them. Both come next, with CalculateLocalToClip,
CalculateLocalToScreenClip, BiasMatrixForZSorting, the three
GetPixelSizes, GetScreenPosition, the camera movers' attach and detach,
and eUpdateViewMode. Then a track viewer puts TRACKB12 on the screen
through the ported loader and cull.

## Session 30, continued (2026-09-26) -- Task 27's twenty-second slice: eView.obj

The twenty-first slice went in as `7004d9f`. The twenty-second is
`eView.obj` (0x00106650 .. 0x001075a8), with the words beside it in
`EcstasyE.obj` that it needs:
- CalculateH (0x00103ce0);
- eGetRenderTarget and SetupMatrixPacks;
- CreateViewMatricies (0x0010d268);
- the static constructor's cameras and views.

The code is in `eview.c` and `eviewmatrix.c`. The decode is in
`docs/formats/eview.md`.

```
eview_check         12 scenarios, 2103 ops, 15454 lines, 0 differ
                    153 mutations: 152 caught, 1 equivalent, 0 unexplained
camera_check        7 scenarios, 1201 lines, 0 differ
                    53 mutations: 46 caught, 7 equivalent, 0 unexplained
sinit_check         15 calls, 0 problems
```

### What the listing says

- **CreateViewMatricies makes five matrices.** They are view to screen,
  view to clip, clip to screen twice (once for each pair of depth
  limits), and view to a clip volume the size of the scissor. The last is
  `WorldScreenClip`, which the cull reads.
- **The near plane moves with the field of view** for players 1 and 2
  only, and not when the view's first mover drives or is the bumper
  camera. The test is `ID - 1 < 2`, unsigned.
- **The frame malloc's test is exclusive** (`pos + n < end`), and a
  failure leaves `pos` where it was. So a failed block can leave room for
  the matrix packs after it. The checker runs the memory out at each of
  the five allocations.
- **MaybeChangeViewMode cuts the targets on every call**, whether or not
  the mode changed. It waits for the GS only when the mode did change.
  The stores go in the listing's order, and that order shows when two
  targets are the same one.
- **GetPixelSize(point, r) calls bGetTicker** and throws the answer away.
  The port leaves the call out.
- **The box's pixel size falls back to H, not 2H**, and its test is
  `r < dist - r` where the other two test `r / 2 < d`.

### The checker

The static constructor runs in place from its first word to the texture
downloader, with a stub at the downloader's call. The two seams are stubs
that print their calls. The frame memory is 2 KB, filled with a pattern
before each use, so that whatever a call leaves alone shows up. The
harness's name buffer is 32 slots. A view's dump names twelve pointers in
one `printf`, and 8 slots wrapped. The frame array is 64 bytes over, so
that its end is not the next array's start.

### The camera's eye

The eye is `vsub` from vf00, which is (0, 0, 0, 1). The port negated it
instead, which is the same for everything but a zero. So the default
camera's eye was -0 in x and y, where the disc has +0. `eview_check`
printed the eye's bits and found it. `camera.c` subtracts from zero now,
and `camera_check`'s model does the same. Its new mutation
`position-plain-negate` puts the negation back and is caught.

### The mutation pass

Two mutants survived the first pass:
- **`spos-w` is equivalent.** It gives GetScreenPosition's vector the
  point's own fourth word for w, and `eRotTransPers` forces w to 1.
- **`pix-mul-order` was caught once the script had the right case.** It
  swaps `r * H / d` for `r * (H / d)`, and the pixel count only differs
  when one order lands exactly on a whole number. A search in float32
  found two such pairs at H = 256, one each way, and both are in the
  script now.

`sinit.c` had given eview's constructor index [1]. It is [2], because the
list's first function is 0x00102340, and `sinit_check` caught it.

### Next: the track on the screen

The loader, the cull and the view are all ported. A track viewer mode
comes next. It loads TRACKB12.BUN, hands the scenery to `scenery_loader`,
and draws what the cull picks through `georender`, with a free camera on
view 1. The scenery is 932 solids, 122,937 triangles and 330 textures,
and it fits the Old 3DS's linear heap as it is. CONTINUE.md has the count
of what is left to a playable demo.

## Session 30, continued (2026-09-26) -- Task 27's twenty-third slice: the track on the screen

The twenty-second slice went in as `53416ed`. The twenty-third is roadmap
step 1: TRACKB12.BUN's scenery through the ported loader and cull, drawn
on the top screen through `georender` from a free camera. The code is
`trackview.c`, `emodel.c` (eModel.obj's list half) and `main.c`'s
`MODE_TRACK`. The write-up is `docs/formats/track-render.md`.

```
trackview: entered, 122 sections, 23 zones, 6160 ms
trackview: 1135 solids linked, 2494 models, 7 without a solid, 915 baked,
           125498 tris, 342 textures (0 missing, 0 reduced), 36268 KB linear free
track drew 380 of 380 (11 in place), 27838 tris, cull zone 42      (stop 2)
track gpu peak 139068 words, 0 skipped, frame memory failed 0,
           held back 67 (12 sorted, 0 dropped)
```

### What it took

- **The build would not start.** Azahar said "Failed to load ROM (Error
  1)" and nothing else, once the viewer first linked `bFixATan2`. The
  3DSX loader refuses an absolute relocation whose word has a top-four
  bit set. gcc had folded `bFixATan1`'s INT32_MIN path, a table index of
  -0x100000, into a negative constant. `bmath.c` compares unsigned there
  now; only INT32_MIN changes, and nothing in the game passes it.
  `tools/check_3dsx.py` walks the relocations as the loader does, and
  `build_cia.ps1` runs it after every build.
- **Draws went missing past about 500 objects.** `GPUCMD_Add` drops what
  does not fit the command buffer without a word. `C3D_Init` gets 4x the
  default now, and `trackview.c` stops 8,192 words short of the end and
  counts the draws it skipped. The count is 0 at every stop, and the peak
  is 139,068 of 262,144 words.
- **The road and the terrain were missing.** They are drawn in place, with
  `eMathIdentityMatrix`, and nothing had filled it. InitializeEverything
  calls `eMathInit` (0x0011b9a0) just before eInitEngine, and `main.c`
  does the same now. Zero, it folded each of them to a point.
- **Stop 2's road was hidden behind a light beam.** The beam's texture is
  semitransparent and does not write depth. The port had drawn every
  batch opaque, in cull order, writing depth.

### The engine's draw order

`RenderStrips` (0x0010c8a0) puts each strip on its texture's list, or on
the frame's alpha list when the texture has `ApplyAlphaSorting`, keyed by
its box centre's view z. At the frame's end, `AttachSolidPolys`
(0x0010a7f0) draws the texture lists by `RenderingOrder` bucket, in first
use order. Then `AttachAlphaPolys` (0x0010a4c0) draws the alpha list, by
order and then farthest first. The GS's blend is `ALPHA_1`, which is
TextureInfo's `AlphaBits`. The disc uses four equations: alpha, add,
subtract (the skids) and replace. The test is the main target's TEST_1
from `UpdateGifTags`: depth GEQUAL, and alpha GREATER than 0x30.

A survey of the three packs:
- every semitransparent texture has `bWriteZ` 0 and an order of 1 to 7;
- every opaque texture has order 0 and writes depth;
- five order-0 decals are alpha-sorted all the same.

`georender_draw_mask` takes a per-texture `GeoPass`. `trackview.c` draws
the opaque order-0 batches at once and holds the rest back, then sorts
them into the attach loops' order after StuffScenery. All seven stops now
show the road, the start line, the signs and the dappled shadows.

### Where it departs

- The alpha sort is per batch (a texture's strips in one solid), not per
  strip.
- `pStackedActiveTexture`, which moves textures that share an image
  parent next to each other, is not modelled.
- The shadows' second matrix pack is not modelled.
- There are no light materials; the scenery is prelit anyway.
- Section 99's SKYDOME and SKYDOME_ENVMAP draw in the main view until
  StuffSky (step 3).

### Next: the LoaderTable

Step 2 makes every chunk type in TRACKB12 live through the real
LoaderTable: the solid list with its pointers fixed up, the texture packs,
the topology and the routes. After that, step 3 is the sky.

## Session 30, continued (2026-09-27) -- Task 27's twenty-fourth slice: the LoaderTable

The twenty-third slice went in as `f5b361c`. The twenty-fourth is the
first half of roadmap step 2: the table ResourceFile hands a bundle to,
and the one loader behind it that the viewer had been standing in for,
LoaderSolidList. The code is `bchunkload.c` (the walks, the two tables and
PostLoadFixup), `esolid.c` (LoaderSolidList, its unloader, eSolid's three
table fix-ups and eFixUpTables) and the rest of eModel.obj's list half in
`emodel.c`. The write-up is `docs/formats/loader-table.md`.

```
loadertable_check  27856 ops, 41730 lines, 0 differ
                   102 mutations: 100 caught, 2 equivalent, 0 unexplained
trackview: 1135 solids linked, 2494 models, 7 without a solid, 915 baked,
           125498 tris, 342 textures (0 missing, 0 reduced), 36256 KB linear free
```

### What the table does

TraverseChunks tries each chunk from the slot that took the last one, not
from slot 0. After a chunk nobody takes, its miss count is never reset,
so every later chunk gets one try at the walk's current slot until one is
taken. A stray type can therefore cost the chunks behind it. The disc
never hits this: every one of its 52 top-level types has exactly one
taker in each table. The port keeps the walk as it is, and the checker
drives it over probe tables to show both sides agree.

The unported slots are guards. Each takes the image's types and hands the
chunk to `gUnportedLoaderFn`. That keeps the walk's slot sequence the
image's, which matters because of the quirk above. TRACKB12 sends 14
chunks to 10 such slots: the lights, the effects, the event manager, the
cameras, the sun, the cops, the soundscape, the helicopter, the smokeables
and the weather.

### LoaderSolidList

The loader fixes the file up where it lies: strip data by the packet's
address, the texture table through GetTextureInfo, the light materials
through elGetLightMaterial, then the external rigid animation, the vertex
animation or duplicate-name flags, and the link onto SolidList. The
unloader looks at a container's first child only. Three cases in the image
go wrong (an animated solid named like an earlier plain one, unloading a
list that was never loaded, more than 64 frames), and none of them is on
the disc. The doc lists them.

On the disc, 110 lists in 44 files hold 1,465 solids. Every container has
its eSolid first. No solid is vertex animated and none has labelled
frames, so the checker builds lists for those. TRACKB12 has 65 lists, but
only 10 hold solids. The other 55 are a 60-byte header followed by a
padding chunk.

### The checker

`loadertable_check` runs the image's walks, tables, LoaderSolidList,
unloader, eFixUpTables and eModel methods in mipsemu against the port.
The host has 8-byte pointers, so the harness rebuilds each solid
container with the host's struct and pad, and prints offsets in disc
bytes. The claims scenario puts every disc type, every guard constant
and their neighbours through all 62 slots. In the model, a loader that
gets past its guard far enough to call anything counts as a take.

The first mutation pass caught 95 of 102, with 2 equivalent. The five
survivors were all holes in the script:
- the ported slots' unloaders were never called on a bare chunk (now the
  claims scenario calls them, all but Scenery's, whose unloader unlinks
  what its loader linked);
- no tree's pad was big enough to change its count of 96-byte nodes;
- the labelled frames always came straight after their animation;
- UnInit never ran on a model that still had a solid.

Each has a case now, and the second pass is 100 caught, 2 equivalent.

### The viewer

`trackview.c` stopped linking the solids itself. It counts the scenery for
its note, then calls `load_chunks` and `post_load_fixup`, and on the way
out `unload_chunks` and `post_load_fixup`. So the track path, the
topology tree and the collision volumes now load on the handheld through
their own ported loaders, as well as the scenery and the routes. Seen on
Azahar: the same counts as before, and the track draws as before.

### Next: the rest of step 2

- TexturePack.obj's loader in slot 2, so that GetTextureInfo is the game's
  and eFixUpTables fills the texture tables. TRACKB12 has no textures of
  its own; they are in TEX12LOCATION.BIN, TEX12TRACK.BIN and INGAMEB.BUN,
  which the viewer opens itself for now.
- The `InitTree` call in `EndGameFlowLoadingTrackSpecific` (0x0016461c), so
  that the topology the table now loads is built.

## Session 30, continued (2026-09-27) -- Task 27's twenty-fifth slice: the texture packs and the track flow

The twenty-fourth slice went in as `8fdcdeb`. The twenty-fifth closes
roadmap step 2. It has three parts:
- TexturePack.obj's loader in slot 2, with the object's in-memory half,
  in `texturepack.c`;
- the viewer using the packs through it;
- the two game-flow steps that bracket a race's track, in `trackflow.c`.
  The End calls InitTree.

The write-ups are `docs/formats/texture-pack.md` (a new section at the
end) and `docs/formats/track-flow.md`.

```
texturepack_check   5452 ops, 11201 lines, 0 differ
                    97 mutations: 95 caught, 2 equivalent, 0 unexplained
trackflow_check     16 scenarios, 694 lines, 0 differ
                    74 mutations: 73 caught, 1 equivalent (port-only), 0 unexplained
trackview: 1135 solids linked, 2495 models, 8 without a solid, 915 baked,
           125498 tris, 342 textures (0 missing, 0 reduced), 35984 KB linear free
trackview: 4 texture packs, 8 flipbooks, 49 names given the default, 0 breaks
trackflow: loaded, InGameFlag 1, eDisableFixUpTables 0, reverse 0
track flipbook frames 46 uploaded, 0 failed
trackview: freed, InGameFlag 0, eDisableFixUpTables 1, 0 solids, 0 models,
           0 texture packs left
```

### The texture packs

A loaded pack's records point into its blob. `ImageData` and `PaletteData`
become pointers, and the placements stay as offsets, so `texpack.c` still
reads a loaded pack. The blob's base is its payload rounded up to 128.
The packer's `0x11` filler was sized for the file's address, so a bundle
must sit at 128 in memory. `uirender.c` now reads with `memalign(128)`.

The `0x30300002` header's second word is not a version. It is
`pTexturePack`, 0 on the disc, and the loader writes the pack there.

GetTextureInfo asks each pack for the first *loaded* record of a name.
The pack that answers moves to the head of the list. Then it tries the
render targets, which are a seam. Then, with `use_default`, it tries
`0x19006835`, GLOBALB's default. The disc's numbers:
- the 1,135 solid tables name 415 distinct textures;
- 12 are first found in INGAMEB, 350 in TEX12LOCATION and 4 in
  TEX12TRACK;
- 49 are in no pack and take the default.

Azahar's count agrees.

UpdateTextureAnimations runs at the end of eDisplayFrame (`0x00113cd4`).
It rotates each flipbook's pixel and palette pointers among its frames'
records. The viewer re-uploads when a record's pointers move, and keeps
each frame's upload. There are 46 frames past the first on this track,
and all 46 uploaded.

### The track flow

EndGameFlowLoadingTrackSpecific (`0x001645e8`) is the one place the fix-up
runs. BeginGameFlowLoadingTrackSpecific sets `eDisableFixUpTables`, so
every PostLoadFixup after it does nothing to the tables. The End clears
the flag and runs eFixUpTables over everything. Only then do TRACKB12's
solids find the textures in TEX12LOCATION, which loads after the bundle.

The rest of the End starts these, in this order:
- the collision pools;
- InitTree;
- InitPhysics;
- the visible zones' `MARKER_BOUNDARY` model;
- the paths;
- the routes;
- a new RaceCoordinator.

Two stores sit in delay slots, and the checker pins both:
- `ReverseTrackDirection` is stored before InitTrackRoutes. It is
  `TrackDirection == 1`, and `forward` is `!= 1`.
- `WeHaveCheckedIfJR2ServerExists` is cleared before InitAIPlans.

The image's InitPhysics has no argument. It reads
`TheRaceParameters.NumDriverInfo` (`0x00312814`) itself, which the port
now has in `race.c`.

BeginGameFlowUnloadingTrackSpecific (`0x001646e0`) closes the same
systems in nearly the reverse order. Then
`while ((f = FindResourceFile(3))) UnloadResourceFile(f)` hands back the
track's files. FindResourceFile walks the list from its tail, so the
newest file goes first. Last, it calls
`ChangeGameFlow(PendingGameFlowState ? pending : 8, 0)`. That is the one
reader of `PendingGameFlowState`, and `gameflow.h` and `boot-flow.md` no
longer call it write-only. `BGameFlow` holds SkipFE and the pending state,
so the Begin reaches them through `gTrackFlowGameFlow`. When that is
NULL, as in the viewer, the three flow steps are skipped.

Every callee the port lacks is a seam in `trackflow.h`:
- the sky, the sun and the rain;
- the smokeables;
- the markers and the debug topology;
- the route editor, the world objects, the animated driver and the AI
  plans;
- the RaceCoordinator's new and delete;
- the HUD pack's unload, the resource files, the sound regions, the demo
  replay, the languages;
- bIsAsyncDone and bCountFreeMemory.

Steps 3 on fill them in.

### The checker

`trackflow_check` runs both functions from the image, with every callee
stubbed. Each stub prints its arguments and six globals read at the
moment of the call, so a store that moves across a call shows.

The first mutation pass caught 73 of 74. The survivor drops the
`gUnloadResourceFileFn != NULL` half of the resource-file loop's guard.
The image has no seams to test that against, so it is listed as
port-only: Find with no Unload would spin in the image too.

### The viewer

`trackview_load` now runs in the game's order:
1. the shared packs;
2. `eDisableFixUpTables = 1`;
3. TRACKB12;
4. TEX12TRACK;
5. TEX12LOCATION, each followed by `post_load_fixup`;
6. the End.

`trackview_free` runs the Begin, with Find and Unload seams over its
three files, newest first. Each is unloaded as `~ResourceFile`
(`0x0018fa50`) does it: UnloadChunks, the free, PostLoadFixup.

There is one more model than before, InitVisibleZones' `MARKER_BOUNDARY`.
It has no solid here because its solid is in INGAMEB, and the viewer
hands only INGAMEB's texture chunks to the table.

The cull is now told `InGameFlag` rather than a constant 1.

### Next: step 3, the sky, the sun and the weather

SkyLoader, SunTrackLoader and rain_Load are already the End's seams, and
their unloaders are the Begin's. StuffSky's draw is what the viewer's sky
domes are standing in for.

## Session 30, continued (2026-09-27) -- Task 27's twenty-sixth slice: the sky dome and the sun's data

The twenty-fifth slice went in as `efbe0b1`. The twenty-sixth starts
roadmap step 3. It covers:
- all of Sky.obj, in `sky.c`;
- the data half of Sun.obj, in `sun.c`: LoaderSun in slot 14, and the
  five SUN textures.

The End and the Begin call both objects' loaders and unloaders directly
now. The viewer draws the dome the way eDisplayFrame does. The write-up
is `docs/formats/sky-sun.md`.

```
sky_check           45 scenarios, 1159 lines, 0 differ
                    78 mutations: 76 caught, 2 equivalent, 0 unexplained
trackflow_check     16 scenarios, 702 lines, 0 differ
loadertable_check   27856 ops, 41730 lines, 0 differ
sky: SKYDOME drawn by StuffSky, the envmap views' its own; sun chunk
     version 2 at -16384 800 6000
sun texture 0..4: SUNCENTER, SUNHALO, SUNMAJORRAYS, SUNMINORRAYS, SUNRING,
     order 7 each
track drew 437 of 438 (11 in place, 1 sky), 28841 tris
trackview: freed, InGameFlag 0, eDisableFixUpTables 1, 0 solids, 0 models,
           0 texture packs left
```

### The dome

A track's sky is a scenery object called SKYDOME, and usually a second
one, SKYDOME_ENVMAP, for the environment-map views. SkyInitModel finds
the object, Inits one of Sky.obj's two models with its name, and builds a
matrix from its placement: the nine int16s times 2^-14, over the
position. Then it UnInits the kind's three LOD models. That is how the
dome leaves the scenery: the cull finds no solid for the kind and skips
it. With no envmap object, SkyLoader gives the envmap model SKYDOME's
name and a copy of its matrix.

StuffSky renders the sky model for views 1 to 3 and the envmap model for
every other view. The test is one unsigned compare, so view 0 goes to the
envmap too.

### The frame

eDisplayFrame turns the Z writes off, calls StuffSky for views 1 to 9,
attaches what it listed, and turns the Z writes on again, all before the
scenery's cull. `georender_set_zwrite` is the port's eSetZWriteState.
While it is off, every pass draws with `GPU_WRITE_COLOR`, whatever the
pass's own depth write. `trackview_draw` calls it around StuffSky and a
flush of the deferred list, so the dome is drawn, and finished, before
the first scenery object.

### The sun's data

LoaderSun keeps a pointer to the chunk's 244-byte SunChunkInfoE, which
sits at the chunk's data rounded up to 16. It copies the position to
SunPosition. The pointer is stored before the version check. A version
other than 2 clears it and zeroes the position, and the loader still
returns 1. SunPosition is eviewmatrix.c's, since the light context looks
from it, so sun.c only declares it.

SunTrackLoader looks up the five SUN names with the default allowed, and
gives each order 7. The image never checks for NULL, so a missing name
gives the default order 7. With no default either, the image stores
through NULL. The port skips a NULL pointer.

### The checker

`sky_check` runs all nine functions from the image, with every callee
stubbed. After each step it dumps both models, both matrices bit for
bit, DrawSky, the six LOD models, SunInfo, SunPosition, SunTextures and
six rendering orders.

The first mutation pass left five mutations. Three were holes in the
script:
- a mutation that moved the Init was placed where no state showed it. It
  now moves the Init to the end of SkyInitModel;
- DrawSky's starting value was never printed;
- the loader's type test was only tried one bit off in the low byte. It
  now also sees the container bit and the high half.

The other two are equivalent, and the checker says why for each.

### The viewer

The draw log counts the dome apart from the scenery ("1 sky"), and the
dome is the first thing on the draw list. The shots that look along the
canyon show the mountains and the clouds behind the rock and the trees.

### After the commit

The chain turned up two things, and both are fixed:
- `sinit_run` did not call `sky_static_init`. It now does, at entry [6];
- `loadertable_test.c` had no SunPosition.

One mutation survived: `loadertable_check`'s `unloader-14-loads`, which
puts `loader_sun` in the unloader table. The checker's dump showed
neither SunInfo nor SunPosition, and its one ported-unloader call gives
the unloader a payload of 0xa5s, whose version is not 2. So a loader in
the unloader's place ends in the same state. Now:
- both dumps print SunInfo and SunPosition;
- a new scenario loads TRACKB12's own SunChunkInfoE through the
  LoaderTable at each misalignment, then unloads it through the
  UnloaderTable, with a dump after each;
- the disc's payload as it is, and the record at version 1, follow.

`loadertable_check`: 27,897 ops, 41,988 lines, 0 differ. Of its 102
mutations, 100 are caught, 2 are equivalent, and 0 are unexplained.
The first commit's run and Azahar were repeated with the start-up fix.
The log is unchanged, and the track draws as before.

### Next: the rest of step 3

Notes on StuffSun, from reading it:
- It runs only for view 1, with a SunInfo.
- It projects the sun with eRotTransPers, and returns when the sun is
  behind the view or off the render target by more than the largest
  CENTER layer.
- It counts the pixels of the last frame's 32 by 32 SunZBuffer whose Z
  is under 64, over 1,024. Each layer's alpha is scaled by that count.
- It fills one ePoly per layer: a quad turned by Angle plus
  SweepAngleAmount times the sun's place across the screen, with
  AlphaB 1 for BLEND and 2 for ADD, and SunPoly set. Then it calls
  ePoly::Render.
- Last, it calls eTransferZBufferRect for the next frame's count.

The check can stub ePoly::Render and dump the ePoly at each call. The 3DS
side needs a 2D ePoly draw, and a depth readback from VRAM between
frames.

- StuffSun and StuffSunGlare. They measure how much of the sun shows by
  reading the PS2's Z buffer back through 15 SunZBuffers, so the 3DS
  needs its own way to measure it.
- WeatherMan (slot 29) and the fog palettes.
- The RainSystem behind rain_Load.

## Session 30, continued (2026-09-27) -- Task 27's twenty-seventh slice: the sun's draw

The twenty-sixth slice went in as `8afa8c6`, with its loadertable fix as
`884cb6c`. The twenty-seventh ports the draw half of Sun.obj:
- StuffSun, StuffSunGlare, the glare's globals and the 15 SunZBuffers,
  in `sundraw.c`;
- ePoly and its constructor, in `epoly.c`, with ePoly::Render as a seam;
- the 3DS side of the seams, in `trackview.c` and `georender.c`.

The write-up is `docs/formats/sun-draw.md`.

```
sun_check           91 scenarios, 2680 lines, 0 differ
                    115 mutations: 114 caught, 1 equivalent, 0 unexplained
```

The checker runs StuffSun, StuffSunGlare and the constructor as shipped.
It stubs eRotTransPers, eMulVector, bSin, bCos, ePoly::Render and
eTransferZBufferRect, and the harness links sundraw.c, epoly.c and
sun.c with the same stubs. The one equivalent mutation, `rect_end_x_le`,
gives 32 - 0 = 32 either way.

What the image showed:
- ePoly::Render's packet writes ALPHA_1 for a SunPoly and nothing else,
  so no TEST_1 and no ZBUF. The main target's alpha test (GREATER 0x30)
  and Z test (GEQUAL) apply.
- The Z buffer is PSMZ16S. FetchZBuffer's BITBLTBUF is 0x3a080000, and
  eTransferZBufferRect queues its rect with PSM 58.
- ZMin and ZMax are floats whose mantissas are the Z, 16 and 0x0ff000.
  Z is linear in the same t as citro3d's depth.
- The poly's z is 65535, which passes GEQUAL against any 16-bit Z. So no
  scenery hides the sun, and only the count fades it.
- Munition::ExplodeWarhead (`0x001b4798`) sets bStartGlare for a
  MunitionsType of 1.
- The port changes one thing: StuffSunGlare returns with no SunInfo,
  where the image reads 28 bytes past NULL.

The 3DS side:
- `render_epoly` does what Render does, then maps the target's pixels
  onto the top screen: `x3 = 200 + (x - W/2) * 400 / W / AspX`, and y the
  same with AspY about 120.
- `georender_draw_quad` draws a strip from a 64-quad ring on the linear
  heap. It goes through the scenery's shader with an ortho projection and
  no light. The combiner's scale is 2, because the GS's 0x80 is 1.0. The
  alpha test is GREATER 0x60, and there is no depth test.
- `trackview_read_depth` runs at the next C3D_FrameBegin, before the
  clear. It reads each PS2 pixel's centre out of the D24S8 buffer:
  screen `(x, y)` is at buffer `(239 - y, x)`, in 8 by 8 Morton tiles.
- A probe logs 15 points' colour and depth words for the first frame at
  each stop. Against seven stops' screenshots the mapping scores 531. The
  x flip scores 3,643, the y flip 5,082, and both 5,931.

Seen on Azahar:
- At every stop the sun is above the frame, 42 pixels above it at stop 1.
  So the rect is off the target, the count is 0, and all four layers draw
  at alpha 0.
- `run_azahar_track.ps1` now ends with a `track-sun` shot, which goes
  back to stop 1 and looks up. The whole rect is sky, 1,024 of 1,024, and
  the layers draw at 128, 64, 89 and 40.
- Layer 1, the halo, passes the alpha test only where its texture's alpha
  is over 0x60, so it has a hard edge. Layer 3 never passes, because
  0x7f * 40 >> 7 is 39. The PS2 does the same, since no sun texture's
  alpha is past 0x7f, and so the doubled upload clamps nothing.

`check_3dsx`: relocations OK. The chain's 57 checkers pass, 0 differ.

### Next: the rest of step 3

- WeatherMan (slot 29) and the fog palettes.
- The RainSystem behind rain_Load.

## Session 30, continued (2026-09-27) -- Task 27's twenty-eighth slice: the weather and the fog

The twenty-seventh slice went in as `3d773ed`. The twenty-eighth ports:
- all of WeatherMan.obj, in `weatherman.c`: the lists, slot 29's loader
  and unloader, the add, remove and state calls, WeatherManQuery, and
  eView::GetWeatherQuery with its cache;
- the fog half of EcstasyE.obj, in `efog.c`: FogModeInfos, fpow,
  RemapLinearIntoClut8, GetFogPalette, CreateFogPalette,
  eAttachDepthIntoAlpha and eAttachFog, with the fog sprite as the seam
  `gEFogAttachFn`;
- `eFrameCounter`, in `eview.c`, which the end of the track's draw
  counts, as eDisplayFrame's end does;
- the 3DS side, in `trackview.c` and `georender.c`.

The write-up is `docs/formats/weather-fog.md`.

```
weather_check       75 scenarios, 4368 lines, 0 differ
                    89 mutations: 85 caught, 4 equivalent, 0 unexplained
loadertable_check   27933 ops, 42243 lines, 0 differ
                    105 mutations: 103 caught, 2 equivalent, 0 unexplained
```

The checker runs the whole of WeatherMan.obj, GetWeatherQuery and the
fog functions as shipped. It stubs eGetView, eGetRenderTarget, bMemSet,
AttachImageDataPacket and eDmaChain::Add. For eAttachFog's packet, the
Add stub prints the view, the palette and the packet's ALPHA_1, and the
harness's seam prints the same from the FogModeInfo it is handed. The
PICA's side, `efog_depth_alpha`, `efog_colour` and `efog_keep`, is
checked against the spec, written out over the image's own depth
palettes.

What the image showed:
- The static constructor links the five lists to themselves, and
  WeatherRainList .. WeatherWindList point at the four. Nothing reads
  those four.
- WeatherAddRegion leaves a region of a type past 3, or below 0, holding
  the chunk's bytes, and the unloader writes through them. The port
  links it to itself. That is the slice's one change.
- The query's d^2 is `(dx^2 + dy^2) + dz^2`, and its sum `(s0 + s1) + s2`.
  Mutations of both orders survived until a scenario found points where
  they round apart; the port's are the image's.
- For rain, snow and wind, a hit's intensity is weighted by HitScale
  alone, not also by its own scale as the fog's is.
- GetWeatherQuery indexes CachedWeatherQueries by the view's ID
  unchecked, and eAttachFog indexes FogModeInfos by the mode unchecked.
- eAttachDepthIntoAlpha needs DepthIntoAlphaBuffer as well as
  EnableDepthIntoAlpha, and both attaches return 0 when their DMA runs
  out. The port checks only the flag.
- The alpha the Z becomes is `min(Z >> 6, 0xfc) | ((Z >> 6) & 3)`, and
  the palette's entry for it is at the CSM1 swizzle of that alpha.

The 3DS side:
- `C3D_DepthMap(false, -1 / near, 0)` for the track's draw makes the
  depth buffer a W-buffer. The depth tests are as they were, and the
  fog's lookup is by the view's own depth. It goes back to
  `C3D_DepthMap(true, -1, 0)` after the track, with the fog off.
- The lookup's entry for depth u takes the GS's Z,
  `zmin + (zmax - zmin) * near * u / (far - u * (far - near))`, then
  `efog_keep` for it.
- `georender_set_fog` binds the lookup, and the ADD and SUBTRACT blends
  get a fog colour of 0.
- The sky and the sun get a lookup constant at Z = 0.

Seen on Azahar:
- `weather: 0 rain, 20 fog, 0 snow, 0 wind regions, 0 off; DrawFog 1,
  modes 0 0, FogPower 4.60, depth into alpha 1`.
- `fog on, mode 0, 82a0a0 x0.100 from 246.0, root FOG<MAIN> + 0; keep at
  250..4000 1.000 1.000 1.000 0.977 0.906, sky 0.906; 1 view, 0 unfit`.
- The first frame's query comes back empty, because the view's counter
  and eFrameCounter are both 0. The next frame's has the fog.
- The render is intact, and the sun's depth readback still gives its
  lines.

`check_3dsx`: relocations OK. The chain's 58 checkers pass, 0 differ.

### Next: the rest of step 3

- The RainSystem behind rain_Load (`0x00128bf8`) and rain_Unload.

## Session 30, continued (2026-09-27) -- Task 27's twenty-ninth slice: the rain

The twenty-eighth slice went in as `ae0ac05`, after the chain's 62 steps
all passed. The twenty-ninth closes step 3. There was less to port than
the roadmap assumed: **the shipped image draws no rain, snow or storm.**

- rain_Load (`0x00128bf8`), rain_Unload, rain_TimeStep and rain_Render
  are each `jr ra ; nop`. `rain.c` has them as that. The End and the
  Begin of the track flow, and World::DoTimestep, call them directly,
  and the three seams are gone.
- RainSystem's constructor, destructor, Update, Render, SplashLoop and
  TweakSplashes have no caller and no address taken. The four
  RainSplash methods are reached only from SplashLoop.
- The storm, in EcstasyE.obj, is dead too:
  - UpdateStorm and RenderAllStorms have no caller.
  - SetStormType is empty, GetStormType returns 0, and
    GetStormTypeString always gives "None". PauseDebugMenu is their
    only caller.
  - Nothing reads DrawStorm, SnowStorm or WaterSpray.
- SoundScape::UpdateWeather has no caller: SoundScape::Update runs the
  reverb and the ambients only. So CreateFogPalette is the weather
  query's one live reader.

The write-up is `docs/formats/rain.md`.

```
rain_check          31 calls, 31 lines, 0 differ
                    41 image facts, 30 references, 0 wrong
                    5 mutations: 5 caught
trackflow_check     16 scenarios, 706 lines, 0 differ
                    76 caught, 1 equivalent
world_check         2742 ops, 15110 lines, 0 differ
                    330/330 mutations caught
```

How the checks work:
- **rain_check's scan** covers the ALLOC sections. A reference is:
  - a jal or j;
  - a lui with an addiu, load or store off the same register, in the
    same function, before the register is written again;
  - a gp-relative access;
  - a data word.

  ori does not count. The lui/ori pairs that land in StormInfo's 98,592
  bytes are GS register constants, 0x2c0400 and the like. Three data
  words fall in StormInfo's range too: two in LumaQuant and one in
  ascii_special. Both are value tables, and the expected list says so.
- **The call-site checkers.** trackflow_check's rain_Load and
  rain_Unload are named stubs now, not seams, so its null-seam
  scenarios print them. That is where the four new lines come from.
  - trackflow_check's new mutations drop rain_Load, turn it into
    rain_Unload, and drop rain_Unload.
  - world_check's new mutations drop rain_TimeStep, and move it ahead of
    UpdatePlayersGameState.

`check_3dsx`: relocations OK. The chain's 59 checkers pass, 0 differ.

### Next: step 4, a car on the track

- Car's constructor (`0x0012f240`) and destructor.
- Car::InitRenderInfo (`0x0011dce8`) and CloseRenderInfo.
- CarRenderInfo's constructor (`0x0011e8b0`), destructor and Render
  (`0x00120b08`).

## Session 30, continued (2026-09-27) -- The retail disc: task 36's first slice

The twenty-ninth slice went in as `7ab56d6` after the chain's 63 steps
passed and the CIA built clean (`check_3dsx`: relocations OK).

The user then put the PAL retail disc in `PS2 Files/Full Game/` and asked
for the full game, not the demo. `SLES_507.31` is stripped. So the first
work was to carry the demo's names over. Written up in `docs/retail.md`.

- **tools/mdebug.py** reads the ECOFF tables in the demo's `.mdebug`.
  There are 9,669 procedures to `.symtab`'s 8,333 functions. The 1,336
  extra are each unit's own copies of inline destructors and
  `operator delete`, and the statics. Without them a demo body in the
  matcher ran on through them: InitFrontend is `jr ra ; nop` but got
  1,132 bytes.
- **tools/retail_match.py** (the last session's, finished):
  - It uses those procedures.
  - A changed placement's extent now ends at the first unit start that
    follows a return or that another placement holds. Before, a stray code
    address inside a function cut it short: PidError::Reset got 4 words.
  - `--audit` checks every demo address the port cites. A `layout` kind
    separates offset-only changes from real ones, using a mask that also
    clears load and store displacements, stack offsets and member addius.
- **tools/retail_layout.py**: per class, demo offset -> retail offset,
  voted from loads and stores off `this` in aligned methods. `this` is a0
  and its moves, and a call's clobber applies after its delay slot.
- **zdir_names.py** gains `--known` (another disc's names), `--also-elf`
  and `--retail`. It names every entry of a shared hash: the retail
  disc lays HUDTEX.BIN, CARS\TEXTURES.BIN and one more down twice.
- **zdir_extract.py** gains `--only` and `--retail`, into the ignored
  `extracted-retail/`.

```
retail_match   demo bodies 9669: same 6980, changed 2353, unplaced 336
               retail .text covered 90.7%; 142,372 bytes with no demo twin
audit          1617 cited: 1148 same, 139 layout, 301 changed, 29 unplaced
               from a .c: 464 same, 73 layout, 130 changed, 13 unplaced
retail_layout  91 classes moved
zdir_names     demo 206/223 (unchanged), retail 369/406
```

What retail changed, from the audit's first reads:
- Field offsets, widely. For example, Car grows by 184 bytes ahead of
  its blink fields, and every Flailer UI chunk gains 24 bytes at the front.
- Real code. For example, SetBoost now scales the boost it hands the
  engine by a gp constant when a flag at car+2124 and a byte behind
  car+52 are both set. GetHorizontalGroundForceInCarFrame is only an
  inlined matrix multiply.
- Everything step 4 was to port: Car's constructor (1052 -> 1176
  bytes), CarRenderInfo's constructor (4020 -> 4700) and Render (7972 ->
  9844).
- The data. TRACKB12's HeliSheet is a container with two children, two
  0x3600x chunks are gone, GLOBALB has no SolidList, and FRONTB has one
  more solid and two fewer event trees. Most tracks are only on the disc
  as `.LZC`.

The decision: the port keeps the demo's layouts and its demo-image
checkers. It follows retail's code where retail changed it, read through
`retail_layout`'s map, and checked by a retail model run (step 5 of the
new road).

### Next: step 4 of "The road to the full game"

- The retail data in the track viewer: `.LZC` when there is no `.BUN`,
  the retail chunk set, the changed loaders, then a second location.

## Session 30, continued (2026-09-27) -- Task 36's second slice: the retail model

Two questions from the user first. Tracks: the port ships them already
expanded, `.BUN` from `.LZC`, not decompressed on the 3DS. The heap is
tight, and a 5 MB compressed copy beside its 9 MB expansion is the worst
moment. Loading is faster too. The frame: the port stays demo-based.
Behaviour follows retail. Names, struct layouts and the checkers' demo
reference stay the demo's. The exception is a record read in place from
the disc, which must take retail's layout. `SLES_507.31` is the retail
program that the disc's `SYSTEM.CNF` boots. The 3DS never uses it, and the
tools need it as the reference. `docs/retail.md` says so.

- **tools/retail_model.py**:
  - `RetailEmu` is mipsemu on the retail ELF with the demo's names at
    retail addresses. Its data map adds single unanimous votes as a
    fallback, which is how LoadChunks alone names LoaderTable.
  - `e.code`, `e.data` and `e.field` map demo addresses and offsets. The
    plain `Emu` answers them with what it is given.
  - The map is cached in `out/retail_map.json`: 8,026 names, 4,210 data
    addresses plus 2,982 on one vote, and 400 classes' fields.
- **TrackInfo is 164 bytes.** Retail's GetTrackInfo and
  LoaderTrackGeometry step by 164. The new int32 at 128 is
  `SignpostGracePeriod`, read only by retail's
  `AICarController::SignPostDecision`. -1 keeps the demo's grace test; 0
  (T23, T26, T42, T45) is a race time. `track.h` takes it and
  `track_check` runs the info scenarios on the retail image over retail
  GLOBALB (66 entries, 30 tracks) and TRACKB12. Retail GetElevation no
  longer calls bGetTicker, so the retail model prints the zero timing the
  port holds; no retail scenario calls it.
- **The LoaderTable is retail's 30 slots**, which were dumped from
  0x00310280 and 0x003102f8. They are the demo's without PhysPredict
  (slot 20), and HeliSheet's guard takes `0x80034800`. A census of every
  retail loader and unloader over the retail disc's types matched that
  and nothing else. `loadertable_check` runs the claims (60 slots over
  the retail disc's types), the walks through LoadChunks and retail
  TRACKB12's 279-chunk walk on the retail image. The other scenarios
  stay on the demo's, because TraverseChunks is unchanged and their
  chunks all go to ported slots.
- **retail_match** no longer cuts a gap at a return that a branch
  crosses. It had put UnloaderHeliSheet on the three words after
  LoaderHeliSheet's first return, and the matrix's stop on it made
  slot 23 take everything. Ten placements moved. GetStateSize went from
  a jump-table case to its real switch. The audit is unchanged.
- **zdir_extract.py --decompress** writes a `TRACKB*.LZC` out expanded as
  its `.BUN`, and skips a stale disc `.BUN` when it does.

```
track_check        demo 15050 ops 11620 lines, retail 1453 ops 348 lines, 0 differ
                   279 mutations: 274 caught, 5 equivalent
loadertable_check  demo 11536 ops 17046 lines, retail 15548 ops 20848 lines, 0 differ
                   109 mutations: 107 caught, 2 equivalent
```

What else the reads showed:
- The sun chunk's record is still 244 bytes. Retail's TRACKB12 pads it
  by 12, which is why the chunk is 256. Retail's LoaderSun then fills a
  fixed glare record at 0x002ef4c0 that StuffSunGlare reads. That goes
  with the sun's retail pass.
- LoaderDifficultyInfo copies 992 bytes, the demo's 744.
- LoadChunks and UnloadChunks differ only in table and count.

### Next

The rest of step 4: the changed loaders (TrackRoutes and its 12-byte
Signpost, TexturePack, DifficultyInfo, the solid list's unloader and
eFixUpTables), then retail TRACKB12 on Azahar, then a second location.

## Session 30, continued (2026-09-27) -- Task 36's third slice: TrackRoute's retail pass

The user: never stop, and get the port to 100%.

- **Signpost is 12 bytes.** Retail's GetSignpost, ReverseSigns,
  SetDistances and GetSignpostIndex step by 12, the loader divides the
  chunk by 12 (a `divu` where the demo shifted by three), and
  InitTrackRoutes' sort gathers 12-byte signs. The new int32 at 8 is
  `AIHint`. A survey of all 30 retail tracks has 1,628 signs at 0, 264 at
  1 and 128 at 2. Only 2 is tested: SignPostDecision keeps such a sign's
  index at controller +684, and ExecuteCurrentAction holds the car to the
  far point's driving-line speed until DoStickyDecisions drops the sign.
- **The Sign values** come from the .mdebug's predicate order (IsFaster,
  IsSlower, AlwaysTake, IsStop, IsEquivalent, IsDontTake), borne out by
  SignPostDecision: 2 is taken at once, 4 on a coin flip, 5 never.
- **DontTakeTarget.** Retail's InitTrackRoutes sets Flags bit 2 on each
  DontTake sign's `NewRoute`, and the constructor clears it. A scan for a
  load of route +24 then a test of bit 2 finds no reader in the image.
  The port sets and clears it anyway. The store goes through GetNewRoute
  unchecked; the port skips a sign whose route is not loaded, which no
  retail track has.
- **HeapSort** differs only in bMalloc's line argument, 1156 for 1148:
  not an element size. `TrackRoute` is still 115752 bytes.
- **trackroute_check** is a hand-written model, rewritten to retail. Its
  new scenario loads retail TRACKB12's and TRACKB21's own routes and signs
  from `extracted-retail/` and runs the loader, both inits and the
  unloader. TRACKB21's one DontTake sign marks route 17 (flags 1, 5 after
  the forward init, 7 after the reverse). A disc sign's Distance before
  SetDistances can be a NaN, so both sides spell it `nan`.
- airoute_test and realcontroller_test copy eight bytes per sign into
  their own arrays, which still works; the whole chain passes.

```
trackroute_check   11 scenarios, 1353 lines, 0 differ
                   58 mutations: 57 caught, 1 equivalent
```

### Next

LoaderTexturePack's retail pass. The 0x30300002 header is 84 bytes,
Name[16], a Filename[64] and the pointer at 80. TexturePack is 148
bytes: a 64-byte Filename and every field after it 16 on. The
constructor takes the filename. AttachTextureTable no longer asks
GetTextureInfo for each record. GetTextureInfo takes a third argument
that looks in unloaded records too, and two new functions rename a
texture and swap two textures' names (ServiceGameFlow swaps the French
loading screen and logo).

## Session 30, continued (2026-09-27) -- Task 36's fourth slice: the texture pack's retail pass

The user: never stop, and get the port to 100%.

- **The header** is 84 bytes: `Name[16]`, `Filename[64]`, the pointer at
  80. All 22 packs on the retail disc have it, each file name of the form
  `Global\GlobalTextures.tpk`.
- **The pack** is 148 bytes. `Name[32]` is at 8, `Filename[64]` at 40.
  The demo's `Filename` was 48 bytes and never written, so every field
  after it sits 16 on from the demo's.
- **The constructor** takes the name and the file name. Both are copied
  with bStrCpy, which does not bound them, so a long name runs on into
  `Filename` and the file name writes over it. `Filename[0]` is cleared
  in the delay slot of the NULL test, so a NULL file name empties it.
  LoadGlobalChunks and SelectTrackSlideshow pass NULL. The port copies
  into a buffer the size of the run and stores it back.
- **GetTextureInfo(hash, use_default, include_unloaded).** A nonzero
  third argument asks each pack's GetTexture, not GetLoadedTexture. The
  default's call is always `(0x19006835, 0, 0)`. Every call the port
  already had passes 0.
- **AttachTextureTable** no longer asks GetTextureInfo for each record,
  so attaching no longer reorders the pack list.
- **The rename** (`0x001ac4d8`, the port's `RenameTextureInfo`) finds a
  record, loaded or not, `bMemCpy`s 24 bytes over `DebugName` and hashes
  it again. **The swap** (`0x001ac548`, `SwapTextureInfoNames`) looks up
  both before testing either, swaps the names by way of the stack and
  hashes each. ServiceGameFlow's language toggle at `0x001681b0` swaps
  `LOADING` with `LOADING_FR` and `NFS_LOGO_ALPHA` with
  `NFS_LOGO_ALPHA_FR` in DYNTEX, reloading the pack's pixels between.
- **texturepack_check** runs on the retail image through a
  `RetailEmu` with 128 MB of RAM. The disc scenario runs twelve files:
  the ten a TRACKB12 race loads and TRACKB21's two, 2,362 records and 12
  flipbooks. It makes ServiceGameFlow's two swaps and swaps them back.
  Built scenarios cover unloaded records, renames and swaps, names and
  file names that run on, and packs constructed with no file name. The
  dump prints every byte of the names, past the NUL. The host's header is
  88 bytes, its pointer 8, and the harness says so.
- The demo's equivalent mutation that hashed the name as given is caught
  on retail: a name that runs into the file name hashes differently from
  its copy. `ctor_filename_not_emptied` needed the NULL-file-name
  constructions to be caught.
- `sky_check` has a new mutation, `tex_include_unloaded`, for the sky's
  lookup passing 0.

```
texturepack_check   6698 ops, 11464 lines, 0 differ
                    132 mutations: 131 caught, 1 equivalent
```

### Next

The rest of step 4. LoaderDifficultyInfo copies 992 bytes, the demo's
744. Then UnloaderTrackGeometry, UnloaderSolidList and eFixUpTables, and
the sun's retail pass (the glare record LoaderSun fills at 0x002ef4c0,
StuffSun, StuffSunGlare, SunTrackLoader). Then retail TRACKB12 in the
viewer on Azahar, then TRACKB21.

## Session 30, continued (2026-09-27) -- Task 36's fifth slice: the difficulty table's retail pass

The user: never stop, and get the port to 100%.

- **The record is 992 bytes.** Retail's LoaderDifficultyInfo copies 992
  where the demo's copied 744, and nothing else in it changed. The
  chunk's size is still not read, so the demo's chunk handed to retail's
  loader takes the 248 bytes after it.
- **The position ratios moved in.** The demo's DecideBoostFactor read two
  statics, `fPositionRatioOverOne` (`0x00307fe0`) and
  `fPositionRatioUnderOne` (`0x00308020`): eight rows of a two-knee Table
  over skill, one per race position. Retail's reads the same shape from
  the table at 240 and 304. The values are retuned.
- **A second set of skill distributions.** Retail's SetupCarsForRace
  indexes `SkillLevelDistribution[nMaxCops < 1][strength]`. In GLOBALB the
  sets differ in one value, strength 2 at skill 7: 0.5 with cops and 0.8
  without.
- **The layout comes from the readers.** Retail is stripped, so there is
  no stab to lay the record out from. Eleven functions form an address in
  the table. `difficulty_check` decodes 68 instructions in them, each at
  its address and inside its function, and evaluates each one's number
  over the model's layout and the port's `offsetof`s. A scan of retail's
  code for every address formed in the table's 992 bytes must find those
  eleven and no more. ExecuteCurrentAction is retail's alone; the demo has
  the other ten.
- **difficulty_check** is new. It runs retail's loader and unloader out
  of the retail image over retail GLOBALB's chunk, five with a wrong id,
  one of distinct bytes, the demo's 744-byte chunk and one whose size
  says 0, each followed by 256 bytes of a pattern. The table is filled
  with a pattern between loads, and both sides print it field by field.
- **carmode_check** loads retail's chunk in its harness while the demo
  image loads the demo's, so it now dumps only `TwoPlayerCatchup`, the
  one field the catchup reads, whose four knees both discs share. The
  seven loader mutations moved to `difficulty_check`.
- **Two carmode mutations had drifted.** `ccb-setup-keeps-system` and
  `-keeps-body` replaced the first `d->pSystem = NULL;` in
  `carcollisionbody.c`, which since b702739 has been
  `carcollisionbody_init`'s, not the set-up's. carmode's harness never
  calls the constructor, so both survived, and the tally hid it because
  it had been summed from `--only` runs. They are anchored to the
  set-up's test now, and both are caught. An audit of every checker lists
  37 mutations whose pattern matches more than once. carmode's other
  three are caught and mean the first match. The other 34 are in twelve
  checkers, and whether each still hits the line its name means is not
  yet checked.

```
difficulty_check   42 ops, 374 lines, 0 differ; 68 facts, 11 readers, 0 wrong
                   24 mutations: 24 caught
carmode_check      74 transitions, 19 resets, 36366 lines, 0 differ
                   498 mutations: 484 caught, 14 equivalent
```

### Next

The solid list's retail pass. UnloaderTrackGeometry and
UnloaderSolidList differ only in an address and a `div` that became
`divu` over a count that is never negative. eFixUpTables looks up a
ninth texture, `0xb9ab56e4`, whose name is on no disc, and then calls a
new function at `0x00103260` that fills that texture's palette with a
sine ramp. Retail's ReconnectSolid ORs `bRandom(256)` into the start
time of a solid with flag 0x20, which the 90 frames of TRACKB61..66's
waving flag carry. GetTextureInfo's new third argument is 0 at every
call in this unit.

## Session 30, continued (2026-09-27) -- Task 36's sixth slice: the solid list's retail pass

The user: never stop, and get the port to 100%.

- **Nine fixed textures.** Retail's eFixUpTables looks up
  `0xb9ab56e4` between SpecularFalloff and CarSelectEnvMap. No file on
  either disc names it: the texture is made at run time, as SHADOWMAP1's
  is. The port calls it `pTextureInfoFalloffRamp`. Retail's nine sit at
  gp-25144 .. -25112; most have no twin by the data map, so the checker
  gives them by retail's gp.
- **The ramp.** After the lookups, eFixUpTables calls `0x00103260`
  (`efix_falloff_ramp`). With a texture and a palette, each of
  `PaletteSize >> 2` entries becomes a grey
  `(int)(p(max(bSin(i/n * 1.57075 + 1.5707965), 0.01)) * 128) & 0xff`,
  where p is an inlined fast power to 1.0 (s with its low six bits
  rounded). It falls from 128 to 1. A loop of `Width` empty passes comes
  first.
- **The random start.** Retail's ReconnectSolid, after setting 0xc000,
  ORs in `bRandom(256)` from `bDefaultSeed` (`0x0025a488`, the one-argument
  bRandom) when the solid's flag 0x20 is set. The demo's eSolidFlags end
  at 0x10. On retail's disc 0x20 is only on `XF_FLAG_1_00`, the waving
  flag's 15 frames on each of TRACKB61..66; its first frame has the rigid
  animation, trigger 0.
- **GetTextureInfo's third argument** is 0 at every call in esolid and
  emodel. The seam is three-argument now, and the harness logs it.
- **The unloaders.** UnloaderSolidList's `div` became `divu` over a loop
  index whose quotient is never used, and UnloaderTrackGeometry changed
  only an address. Nothing to port.
- **loadertable_check** moved the vertex, layout, fix-up, model, disc and
  frame scenarios to the retail image. The demo image keeps the walks
  over probes, the sun and the weather. New scenarios: the random start
  (nine seeds, solids with and without the flag, rigid animation and
  trigger), the ramp (fourteen textures), and a list of a header alone:
  retail's disc has none, and only such a list shows where the unloader's
  walk starts. The disc scenario takes retail's files but the tracks,
  plus TRACKB12 and TRACKB61. Those overflow the model's 32 MB, so
  `OP_MARK` / `OP_RELEASE` give each file's heap back after it. The dump
  prints `bDefaultSeed` and all nine texture pointers; the demo image,
  which has no ramp, prints null in its slot.
- **A retail_model fix.** eModel's deleting destructor calls the copy of
  `__dl__6eModelPv` at demo `0x00114978`, which the demo's symbol names.
  The map kept the other copy, at `0x00227e20`, for the name, so on
  retail the free stub never ran and the pool count drifted. 134 names
  have more than one demo address and the map had not picked the
  symbol's. `RetailMap` now takes the twin of the demo symbol's copy, so a
  stub by name covers the same calls on both images.
- **Two survivors, fixed.** `efix-ramp-filled-first` added a call instead
  of moving it, and a second fill is idempotent; it moves the call now.
  `unload-header-as-container` was caught on the demo by TRACKB12's 55
  header-only lists; the new header-alone scenario catches it.

```
loadertable_check  demo 219 ops 1722 lines, retail 37334 ops 49070 lines, 0 differ
                   139 mutations: 137 caught, 2 equivalent
```

### Next

The sun's retail pass: LoaderSun's glare record at `0x002ef4c0`,
StuffSun (0.49), StuffSunGlare (0.66) and SunTrackLoader (0.85). Then
deploy `extracted-retail/` to Azahar and walk the viewer on retail
TRACKB12, then TRACKB21 or TRACKB31.

## Session 30, continued (2026-09-27) -- Task 36's seventh slice: the sun's retail pass

The user: never stop, and get the port to 100%.

- **A 24-bit Z.** Retail's FetchZBuffer (`0x00110d20`) reads the Z as
  PSMZ24 from block 8192 (BITBLTBUF `0x31082000`); the demo's read
  PSMZ16S from block 0. Retail's eTransferZBufferRect (`0x00111c58`)
  queues its rect as PSMZ32, `w * h / 4` quadwords, and returns unless
  `InGameFlag` (gp-21424) is set. So a SunZBuffer is 32 by 32 words,
  4,112 bytes at `0x002e03d0`, and StuffSun counts `(word & 0xffffff) <
  2`. The scenery writes at least ZMin's 16, so only the clear counts.
- **MaxZ.** Retail's eRenderTarget is 176 bytes. At +116 it keeps
  `MaxZ`, which `0x00105ac0` sets every frame: 16777215 (gp-32736) for
  `ZBufferMode` PSMZ24 (0x31), 65535 (gp-32732) otherwise. The port cuts
  `MaxZ` out of the demo's packet bytes at 116, and `eview_set_max_z`
  does that part of 0x00105ac0.
- **A z per layer.** ePoly::Render (`0x0010fa68`) writes each vertex's z,
  truncated, as the GS Z. (A Flailer's z indexes a float table at
  `0x002c9e70` instead: entries 20..24 as they are, others `MaxZ` less
  the entry.) Retail's constructor (`0x0010f968`) sets z to 0.
  StuffSun sets z 1 on the layer 0 quad, which GEQUAL passes only over
  the clear, so scenery hides the sun's disc pixel by pixel, and `MaxZ`
  on the others. StuffSunGlare sets `MaxZ` once for all its layers.
- **The rect.** Retail moves the 32 by 32 rect onto the target: under 0
  it takes `EndX = x0 + 32` and x0 = 0; past `ScissorW - 33` it takes
  `StartX = x0 + 1 - (ScissorW - 32)` and x0 = `ScissorW - 33`. The demo
  clipped the counted part and read where the rect fell.
- **The glare.** LoaderSun (`0x00124f30`, which the map could not pair)
  now memsets and fills `SunGlareInfo` (`0x002ef4c0`) for any sun chunk,
  whatever its version: TRACKB12's four layers, but layer 1's colour is
  130, 159, 122 and layer 3's intensity 0.3. UnloaderSun leaves it.
  StuffSunGlare draws it, not the track's, so no NULL read is left. Its
  clock is RealTimer (gp-19608) in a `Timer`, 0 and 0x7fffffff unset:
  `el = (int32)(RealTimer - start) * 0.00025`.
- **The disc.** All 30 retail tracks have a 256-byte sun chunk (12 bytes
  of 0x11, then the record), version 2. TRACKB14..16 and TRACKB24..26
  have no layers; TRACKB31..36 have their own (a HALO among them); the
  rest have TRACKB12's. `docs/formats/sky-sun.md` has the positions.
- **On the 3DS.** `render_epoly` runs the Z back to a PICA depth
  (`depth_of_gs_z`). `MaxZ` is past the nearest the scenery reaches and
  draws with no test. Layer 0's 1 is under ZMin, the depth 0, and draws
  GEQUAL with a depth map of scale 0 and that offset, so only over the
  clear. `georender_draw_quad` takes the test as an argument. The
  readback is 32-bit, `gs_z24`, with 0 for the clear. The viewer's
  target is PSMZ24.
- **The checkers.** `sun_check` runs on the retail image: MaxZ in the
  target, RealTimer and a WorldTimer set to what it is not, the glare's
  record in the dump, Z words with the high byte set, rects at each
  edge, targets under 33, and the Timer's two sentinels. Two survivors:
  `count_transposed`, caught once partial rects with big intensities
  came in, and `layer_z_once`, equivalent by construction and replaced
  by `layer_z_first_drawn`. `sky_check` runs on retail, adds
  retail TRACKB12's own chunk, and dumps the glare's
  record. `loadertable_check`'s sun scenario runs on retail.

```
sun_check           115 scenarios, 3427 lines, 0 differ   154/154 mutations caught
sky_check            46 scenarios, 1311 lines, 0 differ   93 caught, 2 equivalent
loadertable_check  demo 178 ops 1617 lines, retail 37375 ops 49175 lines, 0 differ
```

### Next

Deploy `extracted-retail/` to Azahar and walk the viewer on retail
TRACKB12, then TRACKB21 or TRACKB31. The eView retail pass is after:
the 176-byte eRenderTarget, 0x00105ac0 and the Z table at `0x002c9e20`.

## Session 30, continued (2026-09-27) -- Task 36's eighth slice: retail's data on the card

The user's rule from here on: the card holds one folder of retail files
and nothing of the demo's. The port reads `sdmc:/NFSHP2`.

- **The viewer takes any track.** `trackview_init(v, track)` names the
  bundle and both texture files from the number, as the game does from
  `RaceParameters.TrackNumber`. `trackview_next_track` walks 11..66,
  skipping a sixth digit past 6 and any bundle not on the card, and
  `trackview_switch` frees the one held, as the Begin of unloading does,
  and loads the next with the shared bundles kept. ZL and ZR drive it,
  and `logTrackView` writes the same lines on a switch as on entry.
  `run_azahar_track.ps1 -Switches N` presses ZR, waits for the log's
  "switched to" and takes three shots. TRACKB12, 21, 31, 41, 61 and 11
  all draw, with 0 missing textures. TRACKB61 and B64 have 1,345 solids,
  so `TRACKVIEW_MAX_SOLIDS` is 1,536.
- **Retail's Flailer objects.** A `char Name[24]` sits at +16, and every
  field from `ObjectType` on is 24 bytes later: a bitmap is 144 bytes and
  a text object `100 + MaxChars`. Retail's code agrees: AddFlailerStrip
  (`0x00145d38`) reads Z at 42, the text GetAlpha (`0x00140f08`) at 95,
  the bitmap one (`0x001413e8`) at 91, and SetColor (`0x00140ca0`) the
  colour at 92 with `DirtyFlag` at 43. The demo's +16 is `ObjectType`
  (1..5) and a retail name starts with a letter, so `bui.c` and
  `flailer_dump.py` pick the layout per object. `TITLE_LETTERBOX` and
  `TITLE_FULLSCREEN` are the two movie planes the demo only named by hash.
  `bui_check` diffs names too: 0 lines differ over both discs' three
  bundles.
- **DYNTEX.** The title's logo, `LOADING` (`0xab0e817d`, 512x184), is in
  the demo's GLOBALB.BUN but only in retail's `GLOBAL\DYNTEX.BIN`, one of
  the three packs the game loads at boot. `main.c` adds it to the UI's
  bundles. The user saw the logo come back.
- **Retail's sound, and no loss.** The card had no `SOUND`, so the port
  found 0 patches. Retail's `.MSH`/`.MSB` are the demo's format, 25 banks.
  And `audio_pack.py` no longer goes through PCM16 and `dspenc`: SPU
  ADPCM and DSPADPCM are one recurrence at different fixed points, so each
  16-byte SPU frame becomes two 8-byte DSP frames headed `pred << 4 |
  (12 - shift)`, nibbles swapped, with the SPU's coefficients times 32 in
  every patch. Both discs keep to predictors 0..4 and shifts 0..12, and
  every looping lead-in decodes to silence, so the zero history the port
  starts from is the SPU's. All 398 retail and 469 demo channels come back
  sample-exact; the old banks were 22.6 dB at worst and fail the new
  check on every channel. `sndbank_check --audio` asks for exactness now.
  The log reads `Sound: 29 patches in 24 voices`, and the user heard
  them.
- **The chain:** 64 of 64 pass, unchanged.

### Next

The boot movies. `run_azahar_test.ps1` fails on "title screen never
opened a movie": the port plays only the demo's baked `.M3V`, and
retail's intro is 2,425 frames of 512x256 MV30, too many to bake by
emulation. A native MV3 decoder, held bit-exact to the emulated one, then
played through the title's movie planes with its PCM.

## Session 30, continued (2026-09-27) -- Task 36's ninth slice: the boot movies

The title screen plays retail's own movies off the card. The EA logo
comes first, then the intro (the French one in French), with their
sound. The user watched and heard both on Azahar. START skips the
intro. `docs/formats/mv3-video.md` has the codec, the container, the
sound and the player.

- **A native MV3 decoder.** `mv3.c` holds these, from retail's code:
  - `BuildDecodeTab`, `InitIDCTTables`, `GetBits` and `Decompress`;
  - the IJG ifast AAN IDCTs, with their shortcuts for zero coefficients;
  - `ToImage32` and `DecompressFrameShared`.
  It covers intra frames only. All 12 retail movies are 512x256 intra,
  so the motion layout is not ported (`MV3_ERR_INTER`). Emulating the
  decoder cost 8 s a frame, so it could never be baked.
- **The AVI streamer.** `avimovie.c` reads `movi` a chunk at a time.
  - Every sound chunk it passes goes to the sound.
  - It decodes only the frame that is due, at `floor(t * rate / scale)`
    of the console's tick, and skips any late frame.
  - A movie is over when its last frame is shown and the clock has
    passed `frames * scale / rate`.
  Azahar at 100% decodes 154 of EALOGO's 180 frames and 366 of the
  intro's first 591.
- **The sound.** The `strf` says format 1, 8-bit mono, at a rate that is
  only bytes over duration. The data is really SPU ADPCM, stereo, in
  16-byte frames paired left and right, and a chunk can cut a pair
  anywhere. The rate is the EE's: `Update`'s immediate through
  `HzToSPU`, 43,617 Hz. `avisound` decodes it into ndsp wave buffers.
  `bSnd` keeps 23 hardware voices, and the movie takes the 24th channel.
  The first cut was static because it read the PCM the header claims.
- **Retail's table.** `TitleMoviesToPlay` is at `0x002fb750`. French
  plays `NFSINTRO_FR.AVI` second. `bootflow_check` holds the table to the
  image and runs a French scenario.
- **The demo's path is gone.** That removes `movie.c`/`.h`,
  `tools/movie_bake.py`, `movie_check.py` and `src/movie_test.c`. The
  card holds retail's files alone.
- **The movies fill the top screen, as the user asked.**
  `uirender_override_texture` takes a `fill` flag, and `draw_bitmap`
  draws a filled override across the whole target:
  - A 4:3 plane is stretched, as every menu is.
  - The letterboxed intro plane (640x304) is wider than the screen. It is
    cropped at the sides by at most a 32nd each and the rest is
    stretched. Keeping its shape outright cut the EA TRAX song credit,
    which is burned in 23 texels from the left, and the user caught it.
  `boot-flow.md` lists this among the port's deliberate differences.
- **START.** `main.c` sent `SCREEN_START_BUTTON` straight to the flow.
  The title screen swallows it, so START never skipped anything, and
  the test ended PARTIAL. FlailerMenu's `JoyHandler` sends it to the
  screen and then, unconsumed, to the item as `MENUITEM_SELECT`. With a
  menu up, `main.c` now hands `BJOY_START` to `bmenu_joy`.
  `run_azahar_test.ps1` passes: the EA logo, then the intro, then START
  on frame 130 to the main menu.
- **Two false alarms.**
  - The movies and their sound ran "way too fast". Azahar had
    `frame_limit=0`, and its status bar read "Speed: 1792%". With the
    user's say-so it is back at 100.
  - A later build stuck on the EA logo's last frame. `mv3_check
    --mutate` was running, and the build compiled avimovie.c holding the
    `pace-done` mutant, whose movie never ends. The harness restored the
    file afterwards. Never build while a mutation pass runs.
- **Checked.** `mv3_check`: 606 scenarios and 8 whole frames, 48,861
  lines, 0 differ. Of 94 mutations, 92 are caught; two of those hang the
  harness. The 2 that survive turn off the 4-point IDCT's zero shortcuts,
  so they are equivalent. The chain: 65 of 65 pass.

### Next

Step 6 of CONTINUE's road: Car's constructor and destructor, and
CarRenderInfo, from retail where it changed them, so that a car draws on
the track. Still open from this slice (`mv3-video.md`):
- The motion layout.
- Whether the IOP touched the sound's rate.
- Decode speed on hardware.

## Session 30, continued (2026-09-27) -- Task 36's tenth slice: Car's constructor and destructor

The first slice of road step 6. Car's constructor and destructor are
ported from retail's listing (`0x00130a48`, `0x00130ee0`), not the
demo's, onto the demo's layout of Car. `docs/formats/car.md`'s twelfth
code slice has the order, the seams and the field map.

- **Retail's Car.** It is 2200 bytes; the demo's is 2016. Retail adds
  four fields:
  - `vOldPos`;
  - a second horn duration;
  - `JustResetFrames`;
  - `InDeepWaterRegistered`.
  They go at the end of the port's record (2016..2047), so every demo
  offset, and every demo checker, still holds. Every other field moves
  by one of five shifts, from 0 to +184, and `car.md` tabulates them.
  `car_check` holds the port's side.
- **What retail changed in the constructor.**
  - It takes a distance along the track. At zero or above, the
    TrackPathCoordinate is reset with a search that also weighs each
    point's distance round the lap. So a car placed where the track
    crosses itself lands on the right leg.
  - It zeroes the new fields and the rumble timer.
  - It saves the start as `vOldPos`.
  - It has CarDamage look up its breakable parts once the render info
    exists.
  - It rounds `ForceBuzzTime`.
- **The track path.** `trackpath.c` gains retail's weighted
  `FindClosestPoint` (`0x00207d48`) and `ResetPosition(pos, dist)`
  (`0x00208848`). `trackpath_check` now also runs on retail's image,
  with scenarios for the two.
- **Moves.** `car_new_null_controller` moved from `carmodes.c` to
  `carcontroller.c`, so that the constructor's harness links without
  the modes. `espSetAttributeInt` is a seam in `espresso.c`.
  `CarUsageType`'s values are in `cartypeinfo.h`.
- **Seams.**
  - Skipped when unset: the three sound creators, CarDamage's
    constructor, InitRenderInfo, and the event manager's add and
    remove.
  - Abort when unset: the destructors of the sound, the damage and the
    render info, and the part lookup. Each can only be reached through
    something one of the skipped seams made.
  - `SoundEnabled` is in `carinit.c` until the sound layer comes.
  - Nothing calls the constructor yet. Step 8's InitCars will.
- **Checked.** `carinit_check` runs retail's four functions in
  RetailEmu, with CarController's constructor and the TrackPath
  destructor run as shipped and every other callee stubbed. After every
  call it prints the whole car at retail's offsets. So a store the port
  makes early, late, twice, or not at all shows up, and so does a read
  made before a call that could change it. The scenarios cover:
  - every driver number and usage;
  - positions with NaN and `-0` lanes;
  - distances either side of zero, NaN and infinity;
  - the timer where the rounding decides;
  - the returned damage and body;
  - InitRenderInfo's four effects;
  - the destructor over each pointer, delta and flag.
  Results:
  - `carinit_check`: 247 scenarios, 9,637 lines, 0 differ. It caught
    168 of 169 mutations. The one left changes only a stack lane that
    both sides mask.
  - `trackpath_check`: demo 4,746 lines, retail 5,095, 0 differ;
    201 caught, 3 equivalent.
  - The chain: 66 of 66 pass.

### Next

Step 6's second slice: `Car::InitRenderInfo` (`0x0011dc80`) and
CarRenderInfo's constructor (`0x0011e860`). The record is 2352 bytes in
retail, up from the demo's 1856. After those, `Render` (`0x00120ef8`),
so that a car draws on the track.

## Session 30, continued (2026-09-28) -- The frontend's first slice: retail's title screen

The user sent seven PCSX2 photos of the retail PAL frontend and asked for
the port's frontend to match them. TASKS.md's "The retail frontend" lists
them. Step 6's second slice waits on `wip/carrenderinfo` in the
meantime. First comes the title screen, which is now retail's. The user
confirmed on Azahar that both the title and the skip are right.
`docs/formats/boot-flow.md`, "Retail's `TitleScreen`", has it.

- **What retail changed.** The PAL disc rewrote `TitleScreen`
  (`0x0016eef8` to `0x0016f558`). The object grew from 20 bytes to 56.
  - A select during the intro stops the movie, and the screen stays on
    the title. The demo went to `New Main Menu`, and the port followed
    the demo, which is what the user caught.
  - A second `Timer` at `+20` starts on the first tick at rest.
    `PRESS START` shows, and the select that leaves is taken, only once
    that timer is four seconds old (`0x0016f4f8`).
  - Every tick sets the `TITLE_IMAGE` group (the logo, the bar, the
    copyright line) visible exactly when no movie plays.
  - A `tHighlightAnimation` blooms `PRESS START`.
- **The frozen frame.** The first cut kept the intro's last frame in
  the plane, reasoning that `MoviePlayer::Close` never touches the
  plane's texture. On Azahar, the frame covered the logo and only the
  copyright showed. `RenderFlailerBitmap` (`0x00143078`) is the answer.
  It draws a `SPLASH_SCREEN` or `PANELMOVIE` bitmap only as the movie,
  from `TheMoviePlayer`'s five texture slots, and not at all once
  `Close` has emptied them. So retail's still-visible plane draws
  nothing, and the title shows through. The frame retention is gone:
  - `uirender.c` skips those two textures unless an override stands in;
  - `hookMovieClose` drops the override;
  - `flailer_render.py` skips them too. The "the title renders black"
    finding was that renderer's alone.
- **The checker runs retail.** `bootflow_check` no longer writes the
  title again in Python. It runs `TitleScreen::Callback` (`0x0016f440`)
  on `SLES_507.31` in `mipsemu`, with the screen's calls stubbed onto
  its flow. It has a `--mutate` pass now, with 25 mutants over the gate,
  the skip, the constructor, the tick and the events. The first run
  left four alive, and each one showed a blind spot in the world:
  - Events started silent, so a swallowed click was invisible. They now
    start with their JoyHandler's Noise. The same `joyNoise` is in
    `gameflow.c`, and it changes nothing on the console, where the
    title's selects already come through `bmenu`.
  - Closing a movie was not traced.
  - No scenario sent START.
  - Nothing idled long enough for the Timer's restart to reach attract
    mode. `skipidle` and `restidle` do, at a second a frame.
  All 25 are caught now.
- **Checked.**
  - `bootflow_check`: 15 scenarios, 5,420 lines, 0 differ; 25 of 25
    mutations caught.
  - The chain: 66 of 66 pass.
  - `run_azahar_test.ps1` stops the intro, and fails if the skip
    reaches the main menu. At rest it shoots the title and presses a
    START that is too early. Once PRESS START shows, it shoots again and
    presses START for the main menu.

### Next

The frontend's second slice: the boot's retail pass. It covers PAL,
`LanguageOptionsScreenBase`, the loading screen, `BootAutoload` and
`ConsiderStartDemoMode`. CONTINUE.md has the addresses.

## Session 30, continued (2026-09-28) -- The frontend's second slice: the boot's loading and language screens

The user set the order: "The PCSX2 photo showing loading is the FIRST
THING SHOWN, then language, THEN boot screen, then on title you have
blank, and then press start, so do not change title". Azahar now shows
LOADING, then `Language Options Pre FE`, then the EA logo and the intro,
then the unchanged title. `docs/formats/boot-flow.md`, "Retail's
`LOADING_FRONTEND`", has the details.

- **LOADING comes before the flow.** Retail's `main` (`0x0012f000`) has
  no `LoadLanguageInfo`. `InitializeEverything` (`0x0012ee98`) ends by
  calling `LoadGlobalChunks` (`0x001682d0`), which:
  - loads GLOBALA and GLOBALB, and waits for them;
  - sets English;
  - loads the `LOADING` texture;
  - shows `LOADING_TRACK` and its copyright object;
  - calls `eDisplayFrame` once.

  That frame stays up until `MainLoop` draws. `main.c` does the same
  before the `FRONTEND` bundle decodes. `uirender_draw_visible` draws
  every visible screen by layer, because `LOADING_TRACK` is shown by
  visibility and never becomes the current screen.
- **The loading state runs on callbacks.** Begin sets
  `BeginScreenFadeTime = RealTime` and loads FRONTA and FRONTB.LZC.
  FRONTB's callback (`0x00168668`) loads the speech and then the sound
  regions. Their callback (`0x00168658`) changes the flow to
  `IN_FRONTEND`. The Loop only runs the demo slideshow. End hides
  `LOADING_TRACK` and the copyright line, then jumps to
  `LaunchFrontendMenus`. `main.c` gained a four-deep load queue, so
  that the callbacks land a frame later, as a loader's do.
- **The language screen is retail's.** `LanguageOptionsScreenBase`
  serves both names. The name is checked with `strcmp` on the current
  screen's config name.
  - The constructor grays Load All Languages.
  - SELECT on a language sets it. On the boot's screen it also applies
    the frontend defaults, then moves back.
  - BACK takes the highlighted language, unless none is set yet.
  - Load All Languages sets `gp-16016`.
- **Three corrections to the flow on the way.**
  - `MoveBackScreen` is `MoveToPreviousScreen(n, 0, -1)`. The pad's
    BACK is `(1, 1, port)`. KEY_B now calls `bgf_back_button`.
  - `MoveToPreviousScreen` memsets its data, so BACK names no item.
    The port used to pass the screen's hash.
  - The menu is built before `SCREEN_ACTIVATE` and activated after it,
    as `FlailerScreen::Activate` does. `hookEnterScreen` was split into
    `hookOpenScreen` and `hookEnterScreen`.
- **The checker runs retail.** `bootflow_check`'s `RetailLoading` and
  `RetailLanguage` run the image's code under `mipsemu`. The screen list
  at `gp-21324` is faked so that `strcmp` sees the entered name. The
  Python models of the demo's loading state are gone.
  - Five new scenarios: `palselect`, `palback`, `palall`, `palsame`
    and `palrevert`.
  - `demodisc` holds its loads back with `slow600`, so the slideshow
    runs through.
  - 32 new mutations, 57 in all. 56 are caught. `back-names-screen`
    survives, and is equivalent because nothing reads `ItemHash` on
    BACK.
  - One mutant first failed to compile, because its pattern stopped
    mid-comment. It is fixed and caught.
- **Checked.**
  - `bootflow_check`: 20 scenarios, 6,195 lines, 0 differ.
  - `bscreens_check`: 17 scenarios, 1,277 lines, 0 differ.
  - The chain: 66 of 66 pass.
  - The ARM build.
  - `run_azahar_test.ps1` now shoots LOADING and the language screen,
    presses A for English, and fails if a movie opens first. Verdict:
    PASS. The log reads, in order: global chunks loaded, FRONTB loaded,
    the sound regions, `BootAutoload`, the language screen, frontend
    defaults, the title, and the EA logo.

### Next

The frontend's third slice: `BootAutoload` and `ConsiderStartDemoMode`
in full. After that, the main menu's background movie, from TASKS.md's
"The retail frontend".

## Session 30, continued (2026-09-28) -- The frontend's third slice: BootAutoload and ConsiderStartDemoMode in full

The boot now checks for a save and loads it, as retail's does. The
card is the SD card. `docs/formats/boot-flow.md`, "The memory card" and
"Retail's `ConsiderStartDemoMode`", has the decompilation.

- **`memcard.{c,h}`: retail's `BootAutoLoader` and everything under it.**
  - **`MemcardLoader::HandleEvent`** (`0x00246c00`) is the state
    machine: check for the card, check for the file, read it, show the
    status, and leave. Its two tables are `0x002bee80` and
    `0x002beec0`, plus `0x002beea0` for the second look.
  - **Its two "leave with a message" orders are kept.** One is quiet
    and the other clicks.
  - **`MemcardTester`**: the unbounded pump, and the three jobs `Verify`,
    `Load` and `CheckForSavegameFile`.
  - **`MemcardPrompter`**: the two builders, and the table of which
    strings take the kilobytes.
  - **`SavegameData`**: `settings.db`, 0x114e0 bytes, with the word-sum
    checksum.
  - **`OverwriteFred`**: the copy, +904 cleared, and the boot's language
    kept.
- **`bpopup.{c,h}`: `tPopupMenu` and the screen list's two popups.**
  Summon, Dismiss, Tick and HandleJoy, `FlailerMenuItem`'s retail
  recolour, and `RenderTextIntoGroup`'s word wrap with its late cut and
  its `@`.
- **`ConsiderStartDemoMode` is retail's** (`0x0016ed50`): signed, the
  demo disc's attract mode, and `TheDemoModeReplay`'s loading and loaded
  flags.
- **The SD card.** On 2026-09-28 the user asked for every save under
  `/NFSHP2/SAVES`.
  - `main.c`'s `SdCard` is a `cDBFileSys` over
    `sdmc:/NFSHP2/SAVES/settings.db`, and makes the folders on demand.
  - Its free space comes from `FSUSER_GetSdmcArchiveResource`.
  - `g_flow.fred` is a buffer in `main.c`. Nothing reads it yet.
- **A popup takes the pad first.** In `MODE_FLOW`, the D-pad, A, START
  and B go to `bpopup_joy` while a popup is up, and the menus see only
  what is left.
- **The animation kit** gained the four answers the word wrap asks for.
- **The checker runs retail's code.** `bootflow_check`'s `RetailAutoload`
  runs `BootAutoLoader::Callback` and everything under it on the image,
  over a scripted card. The card's `Service` is a hook in front of four
  instructions, so that it can call back into retail code.
  - Both harnesses share a table of cards.
  - Twenty-six new scenarios, 46 in all.
  - `RetailAutoload.run` now restores the emulator's stubs. Its
    `MoveBackScreen` stub had been swallowing the language screen's.
  - The yes/no inputs were a frame early: a question put up in frame N's
    tick takes input from frame N+1. Fixing that killed a group of
    survivors.
  - The popup screen's first two lines have `MaxChars` 29 and 30 in the
    checker. At the file's 40, no message broke where "less two" matters.
  - **`mc-status-three-seconds` needed `manualhalf`**, a manual row at
    half-second frames. At one-second frames, 12000 x 0.00025f is
    3.0000002, so the two-second and three-second waits end together.
  - **`mc-check-ignores-job` needed the `slow` card**, whose jobs take six
    Services, so the Verify outlasts the wait.
  - 147 mutations: 144 caught and 3 equivalent. `mc-loadfailed-quiet` is
    equivalent because `READING_FILE` silences dismissals as
    `READY_TO_LEAVE` does. `mc-autoload-plays-on` is equivalent because
    no movie is open when `BootAutoload` starts.
- **Checked.**
  - `bootflow_check`: 46 scenarios, 24,267 lines, 0 differ.
  - `bscreens_check`: 17 scenarios, 1,277 lines, 0 differ.
  - The whole chain, the ARM build, and Azahar.
  - `run_azahar_test.ps1` shoots the popup checking and then answering.
    It shows "Checking" and then the no-save message, in real translated
    strings, on the top screen, before the language screen. A save
    put on the card by hand was loaded, then removed. The card holds
    retail's files only.
- **Owed.**
  - Message 24, `ANY_BUTTON_PRESSED`.
  - `OverwriteFred`'s six calls.
  - `MemcardSaver`.
  - The internals of `StartDemoMode` and `DemoModeReplay`.
  - Retail's recolour for `bmenu.c`'s menus.
  - The popup's title strip runs off the right edge, as authored.

### Next

The frontend's fourth slice: the main menu's background movie. That is
MV3's inter frames, and `StartMovie`, `UpdateMovie` and `StopMovie` on
`PANELMOVIE`.

## Session 30, continued (2026-09-28) -- The frontend's fourth slice: the menus' movie

The main menu's movie plays behind it in `PANELMOVIE` and loops. Cops
On's and Options' play behind theirs. `docs/formats/mv3-video.md` has the inter
layout and `Update`'s pacing; `docs/formats/boot-flow.md`, "The menus'
movie", has the screen list's three functions.

- **`mv3.c`: inter frames.** A layout word other than 0 has an s16
  vector count and `pTransp` after the type array's size: a byte per
  four macroblocks, copy bits low and no-residual bits high. The vectors
  come first in the bitstream. Each row has an 8-bit count of the
  macroblocks that carry coefficients, which is what the DC predictors
  walk. A copied macroblock is `CopyPreviousFrameBlock` at its vector
  (chroma at half, toward zero), then six residual blocks through the
  `IDCTAdd` family at the inter tables. The two frames trade places each
  frame, as `SwapPrevBuffer` does, with the planes and vectors in one
  allocation so that a vector past its plane reads what retail's does.
- **`avimovie_step`: `MoviePlayer::Update`'s pacing.** The next frame
  when fewer than are due have been decoded, one a call, never skipping.
  `aviplayer_init` and `aviplayer_update` run it off the console's tick.
  `Update`'s 20 s stall and its ring-buffer wait are not ported.
- **`gameflow.c`: `StartMovie`, `UpdateMovie` and `StopMovie`**
  (`0x0016ce30`, `0x0016d028`, `0x0016d0a0`). `UpdateMovie` runs from the
  frame after the popups, as `FlailerScreenList::Tick` has it, stops the
  movie in a race, and reopens it when `Update` says it is over.
  `StartDemoMode` and `UnlaunchFrontendMenus` stop it. The title's movie
  and the menus' share the player, as retail's do.
- **`main.c`.** `hookPanelMovieOpen` and `hookPanelMovieUpdate` draw the
  movie in its plane from its first frame (`movieAttached`). A missing
  menu movie is logged once. Each movie's close logs its `movie cost`.
- **The checkers.**
  - `mv3_check`: synthetic inter movies encoded with the image's own
    prefix code and scan, and two runs of `MAINMENU_MOVIE`, decoded in
    order on both sides; the `IDCTAdd` family and the copy on their own;
    `avimovie_step` against retail's `Update`. 904 scenarios, 0 differ;
    171 mutations, 168 caught and 3 equivalent (the 4-point shortcuts).
    `BuildDecodeTab` is built once per run and then only checked.
  - `bootflow_check`: `RetailMovie` runs the three functions on the
    image, with the player stubbed onto the world. `RetailTitle` runs
    `StartDemoMode`. Three new scenarios (`menumovie`, `menuagain`,
    `menuattract`) and 12 mutations: 49 scenarios, 159 mutations, 156
    caught and 3 equivalent. `mainmenu` had selected before PRESS START
    and never reached the menu; it is retimed.
  - `bscreens_check`: 17 scenarios, 0 differ.
- **Azahar.** `run_azahar_test.ps1 -MenuLoop` waits on the main menu
  until its movie opens a second time. It did: 900 of 900 frames, then
  the reopen. The menu movies on the card are retail's, byte for byte.
- **Too slow.** A menu frame costs about 22 ms to decode and 9 to
  convert on Azahar at 100%, more than a frame at 30 fps. So the player
  decodes on every call, the main menu runs at about 25 FPS, and its
  movie plays at 85% speed. The Cops screens run at 20 to 22. On the
  host, the decode is about 35% `Decompress` and 60% IDCTs, over 1,450
  to 1,550 full blocks a frame.

### Next

The frontend's fifth slice: the menu movie at full speed. The exact
IDCT shortcuts, a cheaper `refill` and zero run, a faster conversion or
the GPU's, and the second core if those are not enough.

## Session 30, continued (2026-09-28) -- The frontend's fifth slice: the menu movie at full speed

The main menu's movie plays at 30 fps on Azahar, 900 frames in 30.0 s,
and the menu runs at 59 FPS. The Cops screens run at about 60. Before,
the menu ran at 25 FPS and its movie at 85% speed.
`docs/formats/mv3-video.md`, "The player", has the worker.

- **The worker** (`avimovie.c`).
  - A movie with no sound gets a thread one priority below the main
    thread's, on core 2 on a New 3DS or else core 1.
  - It reads, decodes and converts each frame into one of three slots of
    linear memory, and queues them in order.
  - `aviplayer_update` keeps `MoviePlayer::Update`'s rule. Where the rule
    decodes, it takes the next slot by pointing the texture's data at it.
    With none ready it answers 1, as retail's does while its ring buffer
    waits.
  - A replaced slot is freed on the next call. The flow runs before
    `C3D_FrameBegin`, which waits for the GPU.
  - `aviplayer_halt` stops the thread, and `hookMovieClose` calls it
    first.
  - `avimovie_decode_next` is the read and decode alone, which
    `avimovie_step` and the worker share.
- **Faster, to the same values** (`mv3.c`).
  - The full IDCT copies a column whose AC terms are all 0, and a row
    whose last seven are, as the 4-point one does. The AAN pass gives the
    first term throughout there.
  - `IDCTImageData`'s and `IDCTAddImageData`'s scan is read inside the
    column pass, instead of into a scratch block first (`idct_columns`'
    `zig`).
  - `mv3_decompress` keeps the reader in a local. GCC then holds it in
    registers, instead of storing and reloading it around every table
    read and coefficient write.
  - The conversion writes a tile's quads in turn, and clamps with `UQADD8`
    and `UQSUB8`: Y plus the chroma term's part at or above 0, less its
    part below 0. `c.r` and `c.b` come from 256-entry tables. All
    16,777,216 combinations of Y, U and V agreed with `Clamp` on the
    host, and on Azahar with a temporary test.
- **Costs** for a main menu frame on Azahar: 2.7 ms reading, 17 decoding
  and 5.4 converting, against 22 and 9 on the main thread before.
  Options' movie is 29 ms a frame. The EA logo is still on the main thread
  and now decodes 176 of its 180 frames (154 before).
- **The checker.** `mv3_check`: 904 scenarios, 0 differ. New mutations
  cover the shortcuts, the fused scan, the reader's write-back, the tiles
  and the byte-wise clamp. Of 197 mutations, 191 are caught and 6 are
  equivalent. The three new equivalent ones turn off the full IDCT's
  shortcuts.
- **Not measured: real hardware.** An Old 3DS gives the worker 80% of
  core 1, about 27 ms a frame, so Options' movie would play a little slow
  there, as retail's rule does when it falls behind.

### Next

The rest of the retail photos: the Easter egg group (`0x74e404b4`), the
jukebox's `Start(1)`, the highlight's echo, EA TRAX, then Setup, car
select and the briefing. Then step 6's second slice, `Car::InitRenderInfo`.

## Session 30, continued (2026-09-28) -- The frontend's sixth slice: the Easter egg group hidden

"Unlocked" and "Easter Egg" are gone from the main menu, as in the retail
photos. `docs/formats/boot-flow.md`, "`NewMainMenu`", has retail's class.

- **What retail does.** The pair is group `0x74e404b4` of `NEW_MAIN_MENU`,
  authored visible: "Unlocked" (LanguageID 62001) at (10, 376) and
  `0xf58c1a4b` at (10, 400). The constructor (`0x00216460`) starts
  `TheEasterEggs` (`0x0031d7e8`, the port's name) and hides the group; the
  destructor stops it and hides the group again. `OnTick` shows it for
  three seconds, with sound 30 and the code's name, when one of the 78
  codes comes in.
- **`gameflow.c`.** `bgf_new_main_menu_callback` is retail's `Callback`
  (`0x00216a10`): `mainMenuCtor`, `mainMenuDtor` behind the instance flag
  (`BNewMainMenu.active`), and `mainMenuEvent`. `hooks.easterEggs` is
  `Start` and `Stop`; on the 3DS it only logs. `BGF_GROUP_EASTER_EGG` is
  the group.
- **BACK.** Retail's table sends it to `0x00216664`, which clears `Param`
  and `Noise`: a silent veto. The demo's did nothing with it, so BACK went
  to the title. The port now does what retail does.
- **`bootflow_check`.** `RetailMainMenu` runs retail's `Callback`,
  `HandleEvent` and `OnTick` on the image, in place of the model's
  demo-shaped `main_menu`. Stubbed silently: the four members, their
  Animates, `OnHighlight`'s calls, the jukebox, `MakeChallengeCarsAvailable`,
  `InitWithDefaults` and `ConsiderStartDemoMode`. `GetPopupActiveState`
  runs on `RetailAutoload`'s list.
  - The veto took coverage away, and the scenarios got it back.
    - `menuattract` had reached the title's BACK, and `StopMovie` with the
      menus' movie open, by going back from the main menu. It is
      `menuidle` now.
    - `select` presses BACK on the title itself.
    - `menumovie` drops InGameFlag again (`outgame`), so a gate kept up
      after `StopMovie` would reopen the movie.
    - `attractmovie` opens the options movie under the title at rest and
      lets attract mode stop it.
  - 50 scenarios, 28,920 lines, 0 differ. 10 new mutations: 169, 166
    caught and 3 equivalent, the same three as before.
  - A mutation pass compiles `tools/src/gameflow_test.c` for every mutant.
    An edit to it mid-pass made one pass's catches meaningless, and its
    output is block-buffered, so its progress looked further behind than
    it was. The second pass was run with `python -u`.
- **Azahar.** `run_azahar_test.ps1` presses B on the main menu now and
  reports the egg lines. PASS: `flow back vetoed` with no sound, the group
  set hidden 6 times and never shown, 60 FPS.
- **A backslash went missing** in `"MOVIES\\mainmenu_movie.AVI"` when the
  section was spliced in through a Bash heredoc. It was caught in the
  diff before a build.

### Next

The jukebox: `Start(1)` in `NewMainMenu`'s constructor (retail
`0x001aeab0`), `cJukeboxPlayer` and `SOUND\JUKEBOXM.JBC`. Then the
highlight's echo, EA TRAX, Setup, car select and the briefing, and step
6's `Car::InitRenderInfo`.

## Session 30, continued (2026-09-28) -- The main menu's highlight bars

The user reported that the main menu's two white bars stayed around Hot
Pursuit after going into a menu and back, while the orange highlight
moved. The Mode Selects' bars moved because `bscreens.c` ports their
highlight. The main menu's never had: its class had no `OnHighlight`.

- **Retail.** `HandleEvent` sends `MENUITEM_HIGHLIGHT` to `OnHighlight`
  (`0x00216938`). It points the bloom at the item, then picks the item's
  mask and blurb, or does nothing for any other hash. `HighlightMenuItem`
  (`0x00216880`) then:
  - takes the mask's `FlailerGetBoundingBox`;
  - moves `MI_UNDERSCORE` to its bottom plus `gp-16112` (-3.0), and
    `MI_OVERSCORE` to its top minus `gp-16116` (6.0);
  - calls `NewText` with the blurb;
  - calls `SelectionSet::SetCurrentItem`.
  The blurbs are 10016, 10015 and 10009: "Be the cops or beat the cops!",
  "Take on the world's best sports cars!", "Customize your settings."
- **`gameflow.c`.** `mainMenuHighlight` and `mainMenuHighlightItem`,
  through two new hooks, `moveBrackets` and `setBlurb`. On the 3DS they
  are the Mode Selects' `hookMoveBrackets` and `hookSetBlurb`. The top
  screen's `SCROLLING_TEXT` stays hidden, and the sentence shows on the
  bottom panel, as it does on the Mode Selects.
- **`bootflow_check`.** `RetailMainMenu` runs `HighlightMenuItem` now,
  with a box stubbed in for `FlailerGetBoundingBox`. The new scenario is
  `menuhighlight` (the new verb `hi<n>`): two items, an unknown one,
  Options and back, and two more. 51 scenarios, 30454 lines, 0 differ. 10
  new mutations: 179, 176 caught and the same 3 equivalent.
- **`run_azahar_test.ps1`** counts the bracket moves made while the main
  menu is the current screen, and a walk with none is PARTIAL.

### Next

The jukebox: `Start(1)` in `NewMainMenu`'s constructor (retail
`0x001aeab0`), `cJukeboxPlayer` and `SOUND\JUKEBOXM.JBC`. Then the echo
(with `OnHighlight`'s `SetCurrentMenuItem`), EA TRAX, Setup, car select
and the briefing, and step 6's `Car::InitRenderInfo`.

## Session 30, continued (2026-09-28) -- The demo disc's code out

The user asked for the demo disc's code to go, since the port is the
full game, and for the unused VP6 decoder to go with it.

- **The rule.** Retail's `TheDemoDiscManager.bActive` is always 0 on
  the retail disc, so the port is written as if it were. Every branch
  on it keeps only its `bActive == 0` side.
- **Gone.**
  - `demodisc.c` and `demodisc.h`;
  - `GAMEFLOW_STATE_EXIT_DEMO_DISC`;
  - `LOADING_FRONTEND`'s Loop (the demo's slideshow of `FIRSTLEGAL`,
    `SLIDE2` and `DISCLAIMER`) and `BeginScreenFadeTime`;
  - the one-movie title and the title's `StartDemoDiscGame`;
  - `CheckForDemoDiscTimeout`, and `GenerateJoyEvents`' activity stamp.
- **Kept.**
  - Attract mode, which is not the demo disc's: `StartDemoMode`,
    `ConsiderStartDemoMode`, `TheDemoModeReplay` and
    `Fred.DemoModeStatus`.
  - `JOY_EVENT_EXIT_DEMO_DISC` (2) and its START+SELECT scanner row.
    Removing them would renumber every event after them.
- **Checkers.** `bootflow_check`, `joystick_check` and
  `trackflow_check` hold `bActive` at 0 on the image, so retail takes
  the port's branches. The demo scenarios (`demodisc`, `demoattract`,
  `attractnodisc`) and their mutants are gone.
  - `bootflow_check`: 48 scenarios, 27,803 lines, 0 differ; 171
    mutations, 168 caught, 3 equivalent.
  - `joystick_check`: 75,891 lines, 0 differ; 250 mutations, 246
    caught, 4 equivalent. `gen-count` is equivalent now: the scanners'
    count had one reader, the demo disc's stamp.
  - `trackflow_check`: 709 lines, 0 differ; 74 mutations, 73 caught.
  - `bscreens_check` and `joyhid_check` pass.
- **VP6.** `source/vp6/` (37 files) is deleted. Every movie on the
  retail disc is MV3, which `mv3.c` decodes. The Makefile builds
  `source` alone.
- **Azahar.** PASS: the boot, the movies, the frontend walk and a clean
  exit, as before.

### Next

The jukebox, then the echo, EA TRAX, Setup, car select, the briefing
and step 6.

## Session 30, continued (2026-09-28) -- The echo, uncommitted; jukebox notes

The user stopped the session here, to pick up with the jukebox. Two
things are in hand: the highlight's echo, written and checked but not
committed, and what is known of the jukebox so far.

### The echo (uncommitted: `gameflow.c`, `gameflow.h`, `bootflow_check.py`)

- **Retail.** `NewMainMenu`'s constructor (`0x00216460`), in order:
  - `tAnimatedBlurb` at +4 (`SCROLLING_TEXT` twice, `WHITEOUT_BAR`);
  - `tHighlightAnimation` at +424 (`ANIMATING_MENUITEM`, gp-16136's
    colour);
  - `tSlideInAnimation` at +456, to `FlailerGetTopLeftX(MI_1_MASK)`;
  - `SelectionSet` at +480, with +476 (the idle Timer) and +632 zeroed;
  - `MakeChallengeCarsAvailable(Fred)` and
    `RaceParameters::InitWithDefaults` (`0x0031a898`);
  - the Timer set to RealTimer, and jukebox `Start(1)`;
  - IndicatorMode 1 (SelectionSet +144), then `AddItems` over the
    five-mask table at `0x0031be40`;
  - StartMovie, TheEasterEggs' Start, the egg group hidden, +628
    cleared.
- **The destructor** (`0x00216598`): TheEasterEggs' Stop, the group
  hidden, then the members in reverse. `SelectionSet`'s and
  `tHighlightAnimation`'s only free. `tSlideInAnimation`'s is
  `tSlideAnimation`'s (`0x00248c08`), which puts the groups back.
  `tAnimatedBlurb`'s releases its two alphas and its group.
- **OnTick** (`0x00216718`):
  - the eggs' half: help menu up (`0x001e4170`), or a code entered
    (TheEasterEggs +4) showing the group with sound 30;
  - the Timer reset while popup 0 is up;
  - `ConsiderStartDemoMode` on the Timer;
  - the three Animates (`0x00249348`, `0x00248970`, `0x00248d20`);
  - the group down three seconds after it went up.
- **OnHighlight** (`0x00216938`) first calls
  `tHighlightAnimation::SetCurrentMenuItem` (`0x002488d0`) with the
  ItemHash, whatever it is. `HighlightMenuItem` (`0x00216880`) calls
  `NewText` (`0x002494e8`) and `SelectionSet::SetCurrentItem`
  (`0x0016e270`).
- **The port.**
  - `BNewMainMenu` holds the four members. The constructor is in
    retail's order, through `menuBlurbInit`, `menuBloomInit`,
    `menuSlideInInit` and `menuSelAddItems`. Each traces what it is
    given.
  - `mainMenuTick` animates the three and takes the Timer reset.
  - `menuBloomSetItem` is OnHighlight's first call, the echo.
  - Message 24 resets the Timer.
  - The jukebox's `Start(1)` is in its place. On the 3DS it is still
    only a log line.
  - Still owed: the eggs' half of OnTick (the 78 codes),
    `ConsiderStartDemoMode` from the main menu (it waits on
    StartDemoMode's race), and `MakeChallengeCarsAvailable` and
    `InitWithDefaults` (for car select).
- **`bootflow_check`.** `RetailMainMenu` says the kit's calls as the port
  traces them: "blurb init", "bloom init", "slide in" (with
  `FlailerGetTopLeftX` answering 0.0, as the harness's world does),
  "sel items", "menu animate" once, "bloom item", "menu kit released"
  and "jukebox 1". 48 scenarios, 27,890 lines, 0 differ. 20 new
  mutations (`main-menu-blurb-wrong-bar` to `main-menu-kit-before-eggs`);
  `main-menu-blurb-first` was reworded for the NewText line. All 37 of
  the main menu's that ran were caught.
- **Left to do before committing:**
  - `main-menu-back-noisy` and `main-menu-back-allowed` are PATTERN NOT
    FOUND. They expect BACK's `break;` to be followed by `default:`, and
    the new TICK case now sits between them.
  - The full `--mutate` pass.
  - The 3DS build and `run_azahar_test.ps1`.
  - The docs: `boot-flow.md`, CONTINUE, TASKS.

### The jukebox, so far

The research agent was stopped before it wrote anything down. What is
known:

- **Callers.** `sound::jukebox::Start(1)` is called when the title comes
  to rest, in the Mode Selects' constructor and in `NewMainMenu`'s.
  Stop comes from `UnlaunchFrontendMenus`. All four calls are already
  in place in the port, through `hooks.jukebox`, and on the 3DS
  `hookJukebox` (`main.c`) only logs.
- **`sound::jukebox`** (retail):

  | Function | Address |
  |---|---|
  | `Start` | `0x001aeab0` |
  | the picker it calls | `0x001aea40` |
  | `IsPlaying` | `0x001aecb0` |
  | `Stop` | `0x001aec90` |
  | `GetTrackName`, `Artist`, `Label` | `0x001aee90`, `0x001aeee0`, `0x001aef30` |
  | `GetCurrentTrack` | `0x001af040` |
  | `SetSelection` | `0x001af050` |

- **`cJukeboxPlayer`** (retail), the instance at `0x003115d0`:

  | Method | Address |
  |---|---|
  | `Update` | `0x0027dff8` |
  | `Start(Ui)`, `Start(UiUiUi)` | `0x0027d640`, `0x0027d6a8` |
  | `Advance` | `0x0027da30` |
  | `Pause` | `0x0027e3e8` |
  | `IsFading` | `0x001b0200` |
  | `LoadCartridge(Pcb)` | `0x0027dac8` |
  | `PickNextTune` | `0x0027eca8` |
  | `SampleCallback` | `0x0027e1d8` |

  `InitializeSoundDriver` (`0x001ae608`) is the likely caller of
  `LoadCartridge`; that is a lead, not verified.
- **Fields** (bytes, from `docs/mdebug_structs.txt`, ~line 18342;
  8868 bytes in all):

  | Field | Offset | Field | Offset |
  |---|---|---|---|
  | cartridge | 0 | `m_nCurCatNum` | 8836 |
  | `m_SyncEventBuffer` | 584 | `m_nCurTuneNum` | 8840 |
  | `m_pFile` | 8776 | `m_bOn` | 8844 |
  | `m_pUserFile` | 8780 | `m_nCategory` | 8848 |
  | `m_FormHeader` | 8784 | `m_fVolume` | 8852 |
  | `m_pPlayingSample` | 8816 | `m_bCallbackTriggerPlaySample` | 8856 |
  | `m_StatePlay` | 8820 | `m_bPauseBeforePlay` | 8860 |
  | `m_KeepPlaying` | 8824 | `m_nLastCategory` | 8864 |
  | `m_pSlot` | 8828 | | |
  | `m_pSyncEventCallback` | 8832 | | |

  `JUKEBOX_STATE`: NOTINUSE 0, LOADING 1, PLAYING 2, PAUSED 3,
  DONE_PLAYING 4, FADING 5, DONE_FADING 6.
- **`SOUND\JUKEBOXM.JBC`** (193 MB):
  - A 32-byte form header: `0x10, 2, 32000` (the rate), 1 (categories),
    `0x1000` (the index's size), 0, 0, 0.
  - The index, read at `0x20`: a 64-byte record per category (+0 the
    tune count, 23; +4 the name, "InGame"), then its tunes. Each tune
    entry is 96 bytes: +0 file offset, +4 size, +8 sync size, +12 name.
  - Each tune is a `0x30`-byte VAG header ("VAGp", big-endian size, rate
    32000, "VAGx", 2 channels), then SPU ADPCM from +`0x30`.
    `avimovie.c`'s `spu_frame` and `kSpuFilter` decode that format.
- **Open questions:**
  - the stereo interleave: the block size per channel, to be checked by
    decoding tune 0 at 0x800, 0x1000, 0x4000 and so on and looking for
    continuity;
  - what the sync data is, and whether any tune has a nonzero sync size;
  - `PickNextTune`'s random number generator;
  - the volume getter `0x001ae028`, called with categories 4 and 5;
  - the stream layer: `0x00280370` (built with 188 bytes, argument 2),
    `0x00273280` (which sets the callback `0x0027e1d8`) and
    `0x00280340`, with their buffer sizes, refills and fades;
  - the globals `sound::jukebox` reads: gp-23056, gp-23048,
    gp-18916..-18928, gp-21420, gp-19616, `0x00313860`, and the table at
    `0x002fc0e4`.
- **Blocker: no free ndsp channel.** ndsp has 24 channels. `bsnd`
  takes 0..22 (`BSND_HW_VOICES` 23) and the movies take 23
  (`AVIMOVIE_CHANNEL`). The jukebox needs one of `bsnd`'s voices given
  up (`BSND_HW_VOICES` 22) or a share of the movie's channel. Retail's
  menus play the movies and the music at once, so sharing only works if
  it mixes.
- **Plan:**
  - `jukebox.c`: a host-agnostic port of `cJukeboxPlayer`,
    `cJukeboxCartridge` and `sound::jukebox`, held to retail by a new
    `jukebox_check.py`;
  - a 3DS stream host that reads the JBC off the card, decodes it to
    stereo PCM16 and feeds a wave ring on its own channel, as
    `avimovie.c`'s `feed()` does;
  - `hookJukebox` made to play, checked on Azahar.

### Next

Commit the echo (see the list above), then the jukebox, then EA TRAX
(`tNewSongMonitor`, `0x0016bd30`..`0x0016c214`, the CHYRON screen in
GLOBALB), Setup, car select, the briefing and step 6.

## Session 30, continued (2026-09-28) -- The echo, committed

The echo went in with one more fix, found on Azahar: no bloom had ever
shown, on any screen.

- **The stale mutations.** `main-menu-back-noisy` and
  `main-menu-back-allowed` now anchor on the `case BMSG_SCREEN_TICK:` that
  follows BACK's `break;`. Both are caught. The full pass: 190 mutations,
  187 caught, the same 3 equivalent.
- **Why nothing showed.** A burst of shots on the main menu
  (`run_azahar_test.ps1 -Echo`, as fast as `PrintWindow` goes for five
  seconds) caught the slide-in, but never the bloom. Every screen authors
  `ANIMATING_MENUITEM` off the bottom edge: y 534 on `NEW_MAIN_MENU`, 676
  on the title, 500 to 600 on the Mode Selects, Options and the popups.
  - Retail's `CopyFlailerText` (`0x001410a0`; the demo's `0x0013ec18`, with
    the name's 24-byte shift) is a 64-byte copy from `ObjectType` on:
    visibility, Z, position, scale, rotation, font, format, colour,
    LanguageID and the `String` pointer. The `jal`'s delay slot saves
    `pFlailerStrip`, which is put back after, and `DirtyFlag` is set to 8.
  - The port's `hookAnimCopyText` copied only the string, so the copy was
    drawn where it was authored, off screen.
  - `bui_copy_text` (`bui.c`) is the whole copy. The characters are copied
    inline, as far as dst has room, since the port has no shared `String`.
    The hook calls it, and no longer clears dst's LanguageID: the copy
    carries src's.
- **Azahar.** PASS. A red "Hot Pursuit" covers the label, grows to twice
  its size and fades out over half a second, every four seconds. The
  copy's Z is the item's, 2, and it comes later in the file, so it is
  drawn over the label. The title's PRESS START blooms now too.
- **Docs.** `boot-flow.md`, "What the port has" and "The echo"; TASKS and
  CONTINUE.

### Next

The jukebox (notes above), then EA TRAX (`tNewSongMonitor`,
`0x0016bd30`..`0x0016c214`, the CHYRON screen in GLOBALB), Setup, car
select, the briefing and step 6.

## Session 31 (2026-09-29) -- The jukebox, EA TRAX, and the GS's MODULATE

The main menu has its music and its EA TRAX box now, as the retail photo
shows. Getting the box to look like the photo found a colour bug that
reached every WHITE16X16 strip and mask in the frontend.

### The jukebox

- `jukebox.c` is retail's `cJukeboxPlayer`, `cJukeboxCartridge` and
  `sound::jukebox`. It is free of `<3ds.h>`; the sample is a `JBHost`.
  `jukebox_check`: 952 ops, 4833 lines, 0 differ. Of 283 mutations,
  279 are caught and 4 are equivalent.
- `jbstream.c` is the 3DS host. It streams `SOUND\JukeboxM.JBC` off the
  card, decodes a pair at a time on a worker thread into eight 128-frame
  waves on ndsp channel 22, and posts the events back for `jbstream_poll`
  to deliver in retail's order. `bsnd` gave up its last voice for it
  (`BSND_HW_VOICES` 22), and the movies keep 23. `jbstream_check` holds
  the decoder to `audio_convert.py`'s on real tunes, cut at the pair
  boundaries and the end: 0 differ. `jbstream_stats` counts
  the pairs read and the samples queued and played, and the shutdown
  line logs them.
- The format, the defaults and the port are in `docs/formats/jukebox.md`.
- **The user: "Still no audio starting after you get to main menu", then
  "The tune only starts once you go to like the audio settings".**
  Gameflow's own `hooks.jukebox` was never set; only the Mode Selects'
  `scrHooks.jukebox` was. So the title's `Start` and `NewMainMenu`'s did
  nothing, and the first `Start` to play came from a Mode Select. `main.c`
  sets it now. On Azahar the tune starts on entering the main menu:
  "jukebox start: Hot Action Cop-Fever for the Flava--Rock-4", about 46
  s of samples played in a run, mix 0.450.
- `run_azahar_test.ps1` reports the load line, each `jukebox start:` and
  the last `jukebox stream:` line.

### The EA TRAX box

- **The user: "Now I hear it but no EA Trax thing popped up on the
  bottom left".** The port had no `tNewSongMonitor`.
- `songmon.c` is retail's (`0x0016bd30`..`0x0016c214`). The layout and
  `Update`, step by step, are in `jukebox.md`, "The EA TRAX box". It shows
  GLOBALB's CHYRON screen for five seconds from each tune's start, prints
  the label, artist and "title", and stretches `CHYRON_BG_1..5` to the
  widest line plus 20.
  - `bgf_frame` ticks it after the movie, through `hooks.songMonitor`, as
    `FlailerScreenList::Tick` (+0x7c) does.
  - `uirender_object_width` is `FlailerObjectChunk::GetWidth`: a text
    object's summed advances times ScaleX, with no kerning and no fixed
    cell, or a bitmap's (int)(texture width * ScaleX).
  - `songmon_check`: 321 ops, 1307 lines, 0 differ. Of 48 mutations, 46
    are caught and 2 are equivalent (`t-unsigned`, `scale-preset`).
- On Azahar: "ea trax: Hot Action Cop / Fever for the Flava". The box
  shows "Fever for the Flava", Hot Action Cop and EA GAMES TRAX over the
  Help button, and the strips come out 184 wide (the PS2 photo's are about
  183).

### The GS's MODULATE

- **The user's side by side (3DS, then PS2).** The PS2 has solid charcoal
  bars behind the lines, with lighter rules between them. The 3DS showed
  the text over the grid.
- The strips were drawn: a shown-minus-hidden difference of two frames
  lifted the dark space and dimmed the grid lines inside the box. It was
  the colour arithmetic.
  - `WHITE16X16` is grey 0x80 at alpha 0x40 on the disc, not white.
  - The strips' colour is black at alpha 0xc8, over-bright on purpose.
    The GS multiplies texel by vertex over 0x80 and clamps the product:
    0x40 * 0xc8 >> 7 = 0x64, 78%.
  - `tint_color` doubled and clamped each byte first, and citro2d's
    `C2D_TintMult` caps the tint at 1.0, so it came out 50%. White on
    WHITE16X16 (`ffffffb4`) came out grey 0x80 rather than 0xff.
- `uirender.c` passes the raw GS byte as the tint now. `draw_image` sets
  texenv 0's scale to `GPU_TEVSCALE_2` after each screen-path draw. citro2d
  rebuilds texenv 0 only inside a draw, on a mode change, and flushes
  first. Switching the scale flushes, and `end_gs_scale` puts it back after
  `uirender_draw_screen` and `uirender_draw_visible`, so the port's own
  wrapped text and everything else drawn after the UI keep 1x. Values up
  to 0x80 give what they gave before, to 1/255.
- `flailer_render.py` does the same multiply. Its CHYRON over a grid is
  the photo's box.
- On Azahar the box has its charcoal bars and rules, and the grid is gone
  behind them. The main menu's unselected rows are darker too:
  `MI_n_MASK` is `000000aa` on WHITE16X16, 66% rather than 50%, which is
  the photo again. The title, Cops On, You're The Cop and Options look as
  they did.
- Not traced: `RenderSingleFlailerBitmap`'s GS registers. This is the
  standard `TFX=MODULATE` arithmetic, and the photo agrees with it.
  `flailer-ui.md`, "Colour: the GS's MODULATE".

### Still unlike the photo

- The TM between GAMES and TRAX, a half-scale text object, is a dot at
  400x240.
- The blurb is on the bottom screen, by design (`SCROLLING_TEXT` hidden).

### Next

The Setup screen, car select, the briefing, then step 6
(`Car::InitRenderInfo`, `wip/carrenderinfo`).

## Session 31, continued (2026-09-29) -- You're The Cop

Cops On Mode Select's second item opens a real screen now: Players, Skill
Level and Setup, with the arrows pulsing either side of the value.

### The port

- `bsetup.c` is retail's `BeACopChallengeSetup`: `Callback`
  (`0x001b6f18`), the constructor and destructor, `HandleEvent`,
  `OnTick`, `OnHighlight`, `OnScroll`, SELECT, `ResyncChangeables`, and
  the helpers round them. With it come two classes every setup screen
  shares: `tfeSineWave` (`0x0024a5c0`) and the arrows (`0x0024a690`), a
  retail class with no name that the port calls `BArrows`. It is free of
  `<3ds.h>`: every Flailer call goes through `BSetupHooks`.
- `DataChallengeScreen` is 20 bytes in retail, 16 in the demo. The fifth
  word is You're The Cop's skill level.
- Both the destructor and SELECT write the settings back to Fred, so BACK
  keeps them.
- SELECT writes `TheRaceParameters.NumPlayerCars` and `NFSRaceMode`. They
  are `race.c` globals now, and `InitWithDefaults` starts both at 1.
- `docs/formats/frontend-setup.md` has the decompilation.

### The check

- `setup_check` runs retail's callback on the image, with the kit, the
  Flailer, the pads and the Fred calls stubbed at their retail addresses.
  Its harness links `bsetup.c` with stand-in `banim_*`.
- The result: 359 ops, 2293 lines, 0 differ; 145 mutations, 142 caught,
  3 equivalent (`event-any`, `skill-changed`, `sel-range-signed`).
- **The first pass left 8 unexplained, and 6 were the checker's fault.**
  - The harness read Fred through `bsetup.h`'s own offsets, so a wrong
    offset moved both sides. It writes them out now.
  - A scroll wrapped the count back to 1 before the second pad went, so
    tick's 2 -> 1 change never ran.
  - No script BACKed out after a change without a SELECT.
  - The arrows' wave always runs from 0, so `lo` never mattered. The
    script now runs a `tfeSineWave` by itself.

### main.c

- `hookSetup*` answer the calls on the object layer:
  - `FlailerGetBoundingBox` in ints: the top left truncated, plus
    `GetWidth` and `GetHeight`;
  - `GetCenterY` from that box;
  - the int `SetTopLeftY`;
  - the arrows' alpha, `SetCenterY` and visibility, on bitmaps.
- `uirender_object_height` is `GetHeightFloat`:
  - text: `GetScaledHeight`, ScaleY * (float)(int) the font's height;
  - bitmap: `CalculateHeightFloat`, texture height * ScaleY, not
    truncated.
- `IsJoystickPluggedIn` is port 0 only, so the count stays 1 and Players
  shows no arrows.
- `SetHelpOverride` and the three car calls are logged, until `tHelpMenu`
  and car select.
- "Be The Cop Setup", "Select Car" and "Select Car2P" (player one's
  screen, `18dc8e52`) are registered as plain screens. All four hashes are
  in retail's `FRONTB.BUN`.
- Off Players, retail's `OnTick` resyncs every tick, so `hookGrayMenuItem`
  now logs only a call that differs from the last one.

### On Azahar

`run_azahar_test.ps1` now walks You're The Cop: down to Skill Level,
right three times through the wrap, then down to Setup and back.

- It passes.
- The log has the ACTIVATE, the three RIGHTs, the help lines
  805000..805003, and "help override off" on BACK.
- The shots:
  - the arrows either side of "Advanced";
  - Beginner again after the wrap, with "Fast opponents" wiping in;
  - on Setup, no arrows and "Customize the current Race Type."
  - The chevrons behind Skill Level in one shot are road signs in the
    FMV.

### Next

The Setup screen (`BeTheCopSetup` on `RaceSetupBaseClass`,
`tScrollingMenuList`), car select, the briefing, then step 6.

## Session 31, continued (2026-09-29) -- Be The Cop Setup

You're The Cop's third item, Setup, opens retail's screen now: Catch-up,
Traffic and Damage, with the arrows either side of the current row's value
and the FMV behind, as in the photo.

### The port

- `bsetup.c` gains `RaceSetupBaseClass` (`0x001b8390`): its constructor,
  `BuildMenu`, destructor, `SetupHighlight` and `HandleMenuEvent`. On it
  sits `BeTheCopSetup` (`0x001b9248`), whose `Callback` is `0x001b93d8`.
  With them comes `tScrollingMenuList` (`0x0024a888` on), the scroller
  every race setup shares. It keeps the rows' Y animations and the up and
  down arrows, and moves the visible window a row at a time.
- The rows are retail's `Changeable`s:
  - Catch-up and Damage flip 0 and 1;
  - Traffic steps through Minimum, Moderate, Maximum and Off with
    `ValueChanger`, and wraps.
- The destructor writes the three values to Fred's `DataBeTheCopSetup`
  (+64), so BACK keeps them. SELECT goes to "Select Car", or to "Select
  Car2P" with two cars.
- The three car calls (`SetupRaceParametersAfterRaceSetup`,
  `MakeChallengeCarsAvailable`) are logged, as You're The Cop's are.
- `bsetup_fred_defaults` puts retail's `InitWithDefaults` values in Fred
  at boot, for `DataChallengeScreen` (1,3,1,1,0) and `DataBeTheCopSetup`
  (2,0,1,0,1).
- Retail reads through a null row, an off-table value and an unset stack
  box in four places. The port guards them, and the doc lists them.

### main.c and bui.c

- Five more `hookSetup*`: `GetTopLeftY`, the int `SetTopLeftY`,
  `SetClipToPoly`, the alpha on any object, and `GrayMenuItem` by screen
  name.
- `bui_set_object_clip` is retail's `ObjectChunk::SetClipToPoly`: the poly
  at +76, dirty 4, and on text the format's clip bit with dirty 5.
  `uirender.c` does not clip with it yet. Three rows never reach the clip.
- "Be The Cop Setup" is registered with `bsetup_btc_callback`.

### The check

- `racesetup_check` runs retail's callback on the image, on
  `setup_check`'s harness with new ops: `btc`, `fdef`, `rpoke`, `rmsg`,
  `rdump`, and a Y for each object.
- The model's chunks carry their hash at +8, since `FindMenuElement`
  compares it there.
- The result: 398 ops, 3420 lines, 0 differ; 86 mutations, 82 caught, 4
  equivalent (`mask-off`, `row-index-default`, `traffic-changed`,
  `lr-silent-kept`).
- The first run differed in 72 lines, over two faults:
  - `BuildMenu`'s first `SetVisibility` is on the row's ChangeText, not
    its item.
  - The exit animation's constructor takes two arguments. The third that
    `setup_check` printed was a leftover register, so both checkers print
    two now.
- The first mutation pass's survivors were holes in the script. Each has
  a case now.
- Fourteen of `setup_check`'s mutation patterns matched the new code
  too, so each carries You're The Cop's own neighbour now. Its pass is
  145 mutations, 142 caught, 3 equivalent, as before.

### On Azahar

`run_azahar_test.ps1` now enters Setup from You're The Cop, goes down to
Traffic, presses right, goes down to Damage and presses B.

- It passes. The log has `flow enter Be The Cop Setup d1eadbca`, and B
  returns to ChallengeBeACop.
- The shots:
  - Catch-up On / Traffic Minimum / Damage On, with the arrows on
    Catch-up and "Set the catch-up boost on or off." It matches the
    photo.
  - After the RIGHT, Traffic reads Moderate, with the arrows and "Set the
    density of civilian traffic."
  - After the B, You're The Cop again.

### Next

The user asked for cars and racing next: "We don't need every single menu
working". So step 6 resumes: `Car::InitRenderInfo` and CarRenderInfo,
parked on `wip/carrenderinfo`, then `Render`, then the road to one car
driving the track.

## Session 31, continued (2026-09-29) -- CarRenderInfo

### The port

Step 6's second slice was parked on `wip/carrenderinfo` (`616bb08`). It
is cherry-picked into master now, and its checker is finished.

`carrenderinfo.c` is retail's:
- `Car::InitRenderInfo`;
- CarRenderInfo's constructor and destructor;
- SwitchSkin, UpdateCarReplacementTextures and CreateCarLightFlares;
- the part culler's InitPart.

It sits on:
- `epositionmarker.c`;
- `cartypeinfo.c`'s GetSkinInfo and GetUsedCarTextureInfo;
- `emodel.c`'s AttachReplacementTextureTable, RenameTexture,
  ReplaceLightMaterial and GetBoundingBox.

The write-up is `docs/formats/car-render-info.md`. Nothing calls it in
the game yet: `gCarInitRenderInfoFn` stays NULL until InitCars, in
step 8.

### The check

`tools/carrenderinfo_check.py` runs retail's functions in RetailEmu, and
`tools/src/carrenderinfo_test.c` is its new harness. Both print the
record, the lists, the solids' tables, the textures' rendering orders,
the model list, the cull table and the seed.

- The first run differed in 318 lines. Retail's static constructor
  (`0x00124528`) gives the flare-direction table's eighth row an x of
  0.95 (gp-32156), and the port had 0. The port has 0.95 now.
- The next ten were the box. bInitializeBoundingBox copies its empty box
  from `0x0031fda0`, and bmath's static constructor (`0x002598d8`)
  fills that with FLT_MAX. The model had never run that constructor, so
  its box started at zero. The model runs it now.
- The checker's address for the skin table was named `SKINS`, the same as
  its list of skins, which replaced it. The address is `SKIN_BASE` now.
- The result: 321 scenarios, 105544 lines, 0 differ.
- `--mutate` runs 163 mutations: 161 caught and 2 equivalent
  (`em-attach-apply`, `ep-none`). The first pass left two holes in the
  script, a body pivot with a y of 0 and an alpha info never overridden.
  It also had two bad patterns. All four are fixed.

The CIA builds with the new files. Azahar was not run, because nothing
in the game reaches the code yet.

### Next

Next is `CarRenderInfo::Render` (`0x00120ef8`), about 2460 instructions.
It needs the light flares, the driver, both shadows, the bodies, the
tyres and blur, the brakes and the wipers. CONTINUE.md has its outline,
from a first read of the disassembly. After Render come the culler's
two passes, and then steps 7 and 8.

## Session 31, continued (2026-09-29) -- CarRenderInfo::Render

### The port

`carrender.c` is new. It has retail's:
- CarRenderInfo::Render (`0x00120ef8`, 9840 bytes);
- UpdateLightStateTextures and CalculateTireBlur;
- the part culler's pass (`0x0011d980`);
- the hull shadow's sh_Setup, convex_hull, smooth_shadow_corners, ch2d,
  make_chain, cmpl and cmph.

Render draws the flares and the animated driver first. Then come the two
shadows: the collision body's hull cast along the sun, and a 4x4 grid
laid on the ground. After them it draws the body at its level of detail,
the mirrors, the plates and the scuffs, then the tyres and their blur, the
brakes and the wipers. It takes frame memory in retail's order and at
retail's sizes, and it skips whatever a failed block was for. Everything
it hands the renderer goes through a seam, and a NULL seam is skipped.
`docs/formats/car-render-info.md` has the order and where the port
differs:
- the hull casts at most 64 points;
- the dead GetBoundingBox call is left out;
- DriverInfo and CopLights have the port's layouts.

The culler's other function, `0x0011d648`, has no callers, so it is not
ported.

`car-type-info.md` now has bytes 228 to 231 as retail's four `lb` bytes:
HighPerformance, NumAvailableSkins, CarClass and OpenTop, which Render
reads. `Pad232` follows them. It also says that retail's GetRandomSkin
(`0x00188460`) is not the port's. CONTINUE.md has that as a follow-up.

### The check

`tools/carrender_check.py` runs retail's Render in RetailEmu, and
`tools/src/carrender_test.c` is its host harness. Every call below Render
that is not ported is a stub on both sides, and each stub prints its
arguments. After Render, both sides dump:
- the frame pointer;
- the culler's parts;
- the damage and the wipers' state;
- the three hull arrays.

- The first run differed in 4384 lines, and neither cause was the port:
  - The frame positions were unaligned. Retail uses `lq` and `sq` on frame
    memory, which the game always keeps 16-aligned, so the scenarios keep
    it aligned too.
  - The stubs zero-extended v0, so a -1 passed retail's `slti`. They
    sign-extend it now.
- After those two fixes: 697 scenarios, 197394 lines, 0 differ. Every stub
  is reached, and all 21 models are drawn.
- `--mutate` runs 304 mutations. The first pass caught 291, and 13
  survived.
- Three of the survivors are equivalent:
  - `chain_i`: from i = 1, V[1] is swapped with itself.
  - `hs_seg_len`: the smoothed hull always has 3n points.
  - `lf_brake_forced`: both values clamp to 1.
- The other ten are caught now:
  - the culler's extras are long enough for normalising to matter;
  - a car square to the axes, in a sun straight along x or y, puts points
    on a shared x, and three on a line (cmpl's y, make_chain's `<=`);
  - steep ground whose normal matches its slope reaches the hull's and
    the grid's 4;
  - level 2 forced from further in reaches the shadow's fade;
  - a driver exactly 101 pixels across in mode 3, and a camera 45
    degrees off behind the car;
  - the camera inside a longer box, 3 to 4 from the car's middle;
  - the light context's line prints QueryLightMat, so its set shows.
- The result: 740 scenarios, 211648 lines, 0 differ; 301 caught and 3
  equivalent.

`racesetup_check`, `carrenderinfo_check` and `carinit_check` still pass,
and so do the checkers that read CarTypeInfo's bytes: `cartypeinfo_check`,
`physicscar_check`, `realdriver_check` and `realcontroller_check`.
CONTINUE.md's run line was missing `racesetup_check` since the last
slice. It has that now, with `carrenderinfo_check` and `carrender_check`.
`cartypeinfo_check` reads OpenTop too, and has a mutation that makes
HighPerformance a word again. Its `--mutate` catches all 41.

The CIA builds. Nothing calls Render in the game yet, so the link drops
it, and Azahar was not run.

### Next

Next is RenderCars (`0x00124060`), which builds each car's tyre and brake
matrices and calls Render. The front end's RenderFrontEndCar and
RenderFrontEndCars (`0x00123c90`, `0x00123d28`) go with it. They close
step 6. Then come steps 7 and 8.

## Session 31, continued (2026-09-29) -- RenderCars

### The port

`rendercars.c` is new. It has retail's RenderCars (`0x00124060`, 580
bytes) and the two helpers of Car's that only it calls:
- `0x00133190`: whether the car blinks in a view;
- `0x00135fb8`: the four tyre and four brake matrices.

RenderCars walks the world's CarList. It skips the camera's own car, a
disabled car, a poofed car and a car the view can't see, and it draws at
most 99. A blinking car shows on odd frames unless the world is paused.
Where the override holds the view, the car is drawn at the override, and
its wheels are identities at the car type's wheel positions. Then
DamageAbove gets the camera's eye and direction, unless the view's player
is in the jump cam (zones 6 and 7). Retail's differs from the demo's: the
dashboard is gone, the override now reaches the blink and the wheels, and
the jump cam skips the damage.

DamageAbove is a seam, `gCarDamageAboveFn`, which stays NULL until the
cops (step 12). `player.h` now names ViewID, and `player.c` has
`PlayerPlayersByIndex`. The loop reads `pCurrentWorld` again for every
test, as retail does. `docs/formats/car-render-info.md` has a new
"RenderCars" section.

The front end's cars are not in this slice. Only CarSelector and
tCarModelViewer make a FrontEndRenderingCar, so they wait for the car
selector (step 16). CONTINUE.md keeps their addresses and layout notes.

### The check

`tools/rendercars_check.py` runs retail's RenderCars in RetailEmu, and
`tools/src/rendercars_test.c` is its host harness. IsPoofed, IsBlinking,
Render and DamageAbove are stubs on both sides, and each prints its
arguments. Render's stub also prints the eight matrices. Any stub can
move `pCurrentWorld` onto a later car, which tests the reread.

- 1272 scenarios, 20075 lines, 0 differ on the first run. They reach 3684
  renders (974 at the override), 3492 damage calls, the cap in six calls
  and the moved world in 27.
- `--mutate` runs 89 mutations, and all 89 are caught.

The CIA builds, and `rendercars.c` compiles without a warning. Nothing
calls RenderCars in the game yet, so Azahar was not run.

### Next

Step 6 is done. Next is step 7: DriveCameraMover (CM_DRIVE) and Player's
ChangeCameraMover. CONTINUE.md has the retail addresses.

## Session 31, continued (2026-09-29) -- the camera base (step 7a-1)

Step 7 is cut in four: 7a-1, the foundations; 7a-2, the shake and the
drive camera's small members; 7b, DriveCameraMover::Update; 7c, Player's
camera functions. This is 7a-1.

### The port

Two math functions retail changed, which the cameras sit on:
- bATan (`0x0025a890`): the squared length is worked out first, and below
  1e-4 (gp-26336 and gp-26332) the argument stays 0. The demo only tested
  the leg for 0.
- eMulVector (`0x0011b300`): the vector's x, y and z are added into a
  (0, 0, 0, 1) at `0x002dc400` (`vadd.xyz`), so w is 1 and a -0 lane comes
  in as +0. The demo copied the vector as it was.

Camera is retail's 464 bytes. ClearVelocity is new at 432, and the four
scalars after it moved up by four. While it is set, SetCameraMatrix
(`0x00156d68`) copies the new key over PreviousKey after the target,
so that frame's velocity is zero, and clears it. The two constructors
clear it, and they put the far plane at 10000 (gp-31300 and gp-31292)
where the demo's put 5000.

CameraMover has retail's vtable (`0x002b1e50`), fifteen slots of it:
`CameraMoverVtbl` in `cammover.h`, with the base's own defaults. The
destructor (`0x00157780`) puts the base's vtable back and calls Disable
directly. The type names end in "CM_UNKNOWN(?)". `update_camera_movers`
(`0x0015ef28`) calls Update on the first mover of each of the ten views,
and `render_camera_movers` (`0x0015eee0`) calls Render on one view's. The
JollyRancher debug feed and the empty CameraMoverAddNearbyDebugTopology
are not ported. The orbit mover now sits on the vtable. Its retail pass
(constructors, Update, and a GetTarget that returns the car's
GeometryPosition) waits for the car selector, step 16.

`docs/formats/camera.md` has a new "Retail" section.

### The check

`tools/cambase_check.py` is new: it runs retail's own camera and mover
base in RetailEmu, and `tools/src/cambase_test.c` runs the port over the
same script. It covers:
- the camera's constructors and SetCameraMatrix, with the clear and a
  camera built while frozen;
- the mover's constructor, destructor, Enable and Disable, every base
  slot, the accessors and the type names;
- both loops, over retail's own eView table and eUpdateViewMode.

The one stub is bFunkDoesServerExist, which answers 0. A second vtable
records Update, Render, Enable and Disable. Everything starts from a
0xa5 fill.

- 1588 ops, 5624 lines, 0 differ. `--mutate` runs 59 mutations, and all
  59 are caught.
- RetailEmu runs no static constructors, and the first run showed it:
  eMulVector's (0, 0, 0, 1) was all zero, so Position's fourth lane came
  out 1 and the fourth column never reached it. The checker now runs the
  one at `0x0011bf70`.

The older checkers follow:
- `camera_check`: 1251 lines, 0 differ; 52 caught, 7 equivalent. It
  dropped "ctor-sets-clear", which only a camera built while frozen can
  show; `cambase_check` has one.
- `bmath_check`: 6643 lines, 11 of 11 caught. It has new atan cases
  either side of the floor, and NaN.
- `emath_check`: 2418 lines, 42 of 42 caught. The "-0*n" case tests each
  lane's +0 alone.
- `eview_check`'s demo model reads 10000 for the far plane.
- `scenery_check` failed on its tiny facade case, (0.001, 0.002), which
  is under retail's floor. CreateFacadeMatrix is the same on both discs,
  so its demo model still runs the demo's, and the bATan under it now
  runs on retail's image. 0 differ, and 77 caught and 2 equivalent, as
  before.

The whole suite passes. The CIA builds. Nothing new runs in the game yet,
so Azahar was not run.

### Next

7a-2: tEnvelope, tShaker and the camera shake, then DriveCameraMover's
small members. CONTINUE.md has the list.

## Session 31, continued (2026-09-29) -- the camera shake (step 7a-2a)

Step 7a-2 is cut in two: 7a-2a, the camera shake, and 7a-2b,
DriveCameraMover's small members. This is 7a-2a.

### The port

`shake.c` is new. It ports the camera half of the object after
`CameraMover.obj` (retail `0x00155948 .. 0x00156b88`); the pad's rumble
half is not ported.
- tEnvelope: GetIndex, OutOfRange, both GetSlopes, GetValue and
  GetIntegral.
- tShaker: the constructor (out of line in retail), GetAmplitude,
  StartShaking, Update and the square-wave GetValue.
- The globals: CameraShakers[2], the amplitude envelope, bShakeTest and
  vShakeTest, vShakeAccelBias, vShakeRotation and fShakeIntensityCoeffs.
  Their share of the static initialiser is `sinit.c` [24].
- The reset (`0x00156480`), UpdateCameraShakers, GetShake,
  IsShakeActive, ApplyCameraShake, MaybeCameraShake and
  Car::MaybeCameraShake.

`player.c` has Player::IsCameraPOVInCar (`0x00178808`). `player.h` has
cPlayerSettings (40 bytes), and pCameraMover and nZoneCurrent at the
demo's offsets. `cammover.h` has POV (32 bytes) and its three types.
`main.c` sets `gCarMaybeCameraShakeFn`. No car has a player until step 8,
so nothing shakes yet.

The first run had 152 lines apart, all in ApplyCameraShake. The image's
frame puts the rotation matrix at sp+16 and eMulVector's output at sp+64,
so the shake in the camera's space is written into the matrix's own
translation row, with w 1. The camera therefore moves by the shake as
well as tipping. The row turns with each rotation, so the y angle reads
the shake's x after the turn about x, and the z angle an x and y that
have both moved. The port now builds the row in the same place.

`docs/formats/camera.md` has a new section, "The camera shake".
`car.c`'s and `car.md`'s tallies count MaybeCameraShake: thirty-five
methods are ported, and eleven are left.

### The check

`tools/shake_check.py` is new: it runs retail's code for all of the above
in RetailEmu, and `tools/src/shake_test.c` runs the port over the same
script. The movers' GetCameraInfo and GetPOV are the only stubs. The
Players, movers, POVs, the Car and the World are blobs at retail's
offsets. RetailEmu runs no static constructors, so the checker runs
`0x0011bf70` and the shake's `0x00156958` itself.

- 4114 ops, 10604 lines, 0 differ. `--mutate` runs 98 mutations: 95 are
  caught, 3 are equivalent, and none is unexplained.
- The first pass left three survivors. Two needed inputs the shipped data
  never gives. Clamping GetIntegral's b only matters for an envelope out
  of time order, so the script has one now. vShakeRotation's z is 0, so
  the script now moves all three lanes and the turn about z is checked.
- The third is equivalent: GetIntegral's count test. With b clamped to
  the last point, the time test always ends the loop first.
- `sinit_check` counts 17 calls.

The whole suite passes. The CIA builds. Nothing new runs in the game yet,
so Azahar was not run.

### Next

7a-2b: DriveCameraMover's constructor, destructor, ResetState and small
members, and CameraInfo. CONTINUE.md has the list, and two follow-ups:
the World constructor's reset, and MainLoop's UpdateCameraShakers.

## Session 31, continued (2026-09-29) -- the drive camera's small members (step 7a-2b)

This is 7a-2b: everything of DriveCameraMover (CM_DRIVE) but Update and
the helpers only Update calls.

### The port

`drivecam.c` and `drivecam.h` are new, and `camerainfo.h` with them.
- The record, 1008 bytes in retail. Its fields are the demo's .mdebug
  record's, and everything from TheTopologyCoordinate on is 144 bytes
  further on than the demo's, because retail's TopologyCoordinate is 704
  bytes to the demo's 560. DisableLag is at 884 and PerfectFocus at 992.
- The vtable (`0x002b1dd0`). Update, Render, the joystick pair, Enable and
  Disable are the base's until 7b.
- The constructor (`0x0015c258`), the destructor (`0x0015c400`),
  ResetState (`0x0015c470`), SetPOVIndex, GetPOV, GetTarget, GetCameraInfo
  and GetCarToFollow.
- The three virtuals new in retail: IsExteriorView (+68), IsLookingBack
  (+76) and GetWallGap (+84). Each counts a look back only while the
  mover's player has a Lookback of 0.
- The three corrections (yaw, pitch, in-car), CalculateLookbackAngle
  (`0x0015c5a8`), and the inline accessors' out-of-line copies
  (`0x0015fbf8 .. 0x0015fc9c`).

`camerainfo.h` lays out CameraInfo (272 bytes: two counts, then four
full-screen and four split-screen POVs) and moves POV there from
`cammover.h`. CarTypeInfo carries a CameraInfo at 960 now, not 272 bytes.
`cammover.h`'s GetCameraInfo and GetPOV return const pointers, and the
base's do-nothing Update and Render are public as `camera_mover_nothing`
and `camera_mover_render`, for the other movers' vtables to share.

`player.h`'s cPlayerSettings word at 12 is retail's int Lookback, where the
demo's was the float LookbackSpeed. ResetToDefaults (`0x001edf90`) sets it
to 1, and ToggleLookback (`0x001ee2d8`) swaps 0 and 1.

Retail against the demo: the three new virtuals, the larger
TopologyCoordinate, LastCarSpeed from State.VelocityMagnitude (the demo's
read ForwardSpeed), GetTarget from GeometryPosition (the demo's used
Position), and the fallback CameraInfo read inline from
CarTypeInfoArray[0] (the demo's called GetCarTypeInfo(0)).

A scan of the image found no caller of GetAccelLag (`0x0015c708`) and
nothing pointing at it, so it is not ported. The in-car correction has no
caller either, but it is ported. The constructor's four callers are
Player::ChangeCameraMover, DemoCameraCoordinator::Update, the
NisCameraCoordinator constructor and ReplayScreen::ChangeCameraMover.

`docs/formats/camera.md` has a new section, "The drive camera".

### The check

`tools/drivecam_check.py` is new. It runs retail's code for all of the
above in RetailEmu, over the base, the Camera constructor, bASin, bATan and
retail's eView table. `tools/src/drivecam_test.c` runs the port over the
same script. Only TopologyCoordinate's constructor and destructor are
stubs, since the port's is still the demo's.

- 8 scenarios, 2941 ops, 7406 lines, 0 differ. `--mutate` runs 149
  mutations: 146 are caught, 3 are equivalent, and none is unexplained.
- Writing the checker turned up one bug in the draft: the non-virtual
  IsLookingBack (`0x0015fc70`) reads DesiredLookBackParam, and the draft
  read LookBackParam. It is `drive_cam_look_back_full` now.
- The first mutation pass left 14 survivors. Twelve were ResetState's
  stores to fields only Update writes: nothing in this slice moves them,
  so they were still the constructor's 0s and 1s. The walk now scribbles
  distinct words over all 36 of them before most resets, standing in for
  Update, and all twelve are caught. A new mutant that zeroes
  AmountToUseYawCorrection in ResetState, which retail leaves alone, is
  caught too.
- The other two are equivalent: the constructor's and ResetState's
  16-bit mask on bASin's pitch. The image masks it (`andi 0xffff`), but
  the port's bASin already returns `r & 0xffff`. The third equivalent
  mutant is the destructor's vtable store, which the base's destructor
  makes again next.
- CalculateLookbackAngle's inputs include a searched set within 1e-6 of
  0.7071, where another order of the sums or the dots, or a divide in
  place of the reciprocal, crosses the threshold: four for each.

The whole suite passes. The CIA builds. Nothing new runs in the game yet,
so Azahar was not run.

### Next

7b: DriveCameraMover::Update (`0x0015c880`, 6056 bytes), with
GetLookbackCar and the two wall helpers. A scan at the end of this slice
found that the demo's wall code is dead in retail. The demo's Update calls
EnforceMinGapToWalls, which retail does not have, and GetBoomDistToWall,
DistanceToLineSegment and IntersectLineSegments have no caller in retail's
image. Retail's Update calls two new unnamed functions instead, `0x00157930`
and `0x00157b60`, and a third, `0x00157c60`, is the bumper camera's.
CONTINUE.md has the details.

## Session 31, continued (2026-09-29) -- the topology's retail pass

7b's Update calls SetInterestBBox, GetElevation and ConstrainToTopology on
the mover's own TopologyCoordinate, and retail had changed all three. So
the topology's retail pass came first. `track.c` is now retail's
`Track.obj` (`0x001513c8 .. 0x00153984`), except road noise.

### The port

- **TopologyCoordinate is retail's 704 bytes** (`topology.h`). The table
  holds 160 polygons, not 128. The four counts are at 672, the last
  polygon at 688, and three words at 692 that only the constructor
  writes. On a 64-bit host the 161 pointers widen, and `topology.h`
  counts the slack.
- **TopologyTree is 44 bytes.** A word at 32 is written only by the
  constructor, and the list head moved to 36. InitTree also zeroes
  `TopologyTreeUnused[2]` (`0x00330318`), which nothing in `Track.obj`
  reads.
- **Car's TC is 704 bytes at 1280** (retail's is at 1312). Everything
  after it moved on by 144: TrackPathCoordinate is at 1984, vOldPos at
  2160, and `car.h` is 2192 bytes. `car_check`'s layout table follows.
- **GetElevation tries the last polygon first.** When the point is
  strictly inside it, its plane is the answer at any height, with no look
  at the interest box. A slow-path hit strictly inside, not
  INFINITELY_HIGH, becomes the last polygon. A miss keeps it.
  SetInterestBBox's rebuild and ClearInterestBBox forget it. The terrain
  is read as a signed byte. The inside test's edges are 0-1, 1-2 and 3-0,
  plus 2-3 for a quad, and its `max.s` keeps m when a cross is NaN, so a
  NaN point is inside anything.
- **SetInterestBBox**:
  - the look-ahead starts at 0.15 and is multiplied by 0.75 per try;
  - there are five tries, and the fifth uses 0;
  - a box fits when its diagonal is under 28.8;
  - the build's cap is 160;
  - NumUpsideDown is what pass 3 placed. The demo's was total less
    vertical.
- **BuildTrackPolygons (`0x001531f8`) was rewritten**: every square under
  the box, y outer, x inner, from the square corner at or below the
  minimum, stepping 32 while at or below the maximum. It walks only when
  the box is strictly inside (-32768, 32767) on both axes.
- **The timing is gone**, with TopologyTiming and its index.
- BeginMovement keeps retail's vOldPos (`0x00131cc8`). AverageAir
  (`0x00135b30`), FindFlatOnTrackPosition (`0x001326d8`) and
  PutFlatOnTrack (`0x00132910`) are the demo's code at retail's offsets.
- Retail's `Track.obj` ends with a thunk at `0x00153970`, `j 0x00151d30`,
  that nothing calls. It is not ported.

### The check

`track_check` now runs everything except road noise and the two
MatchTerrainTypes on the retail image, over retail TRACKB12 (15098
polygons, 0 degenerate). Those three read the demo's 140-byte
TerrainTypeInfo, so they stay on the demo image until TerrainType's
retail pass.

- Retail: 16779 ops, 10306 lines, 0 differ. Demo: 1254 ops, 1073 lines, 0
  differ. The mutation pass has 314 mutations, 308 caught and 6
  equivalent.
- `track_test.c` gained OP_TREEPOKE, for the three unused words. It lost
  the ticker and the timing lines. TCPOKE reaches the last polygon and
  the unused words.
- The synthetic world grew:
  - a terrain-200 floor;
  - 170 dense slivers, to fill a coordinate's 160;
  - a floor in each of the row and the column that only a box ending on
    a square's edge reaches;
  - builds out to the bounds either side;
  - a section on the last polygon, and each standalone polygon poked in
    as the last one.
- **One model fix.** The first retail run of AverageAir had 114 lines
  differ. The start point had no translation: retail's
  `bMulMatrix(bVector3)` adds the vector to the constant at `0x00320a60`
  for its w of 1, and that constant is (0, 0, 0, 1) only after bmatrix's
  static initialiser (`0x0025afa8`) runs. The model runs it now. The port
  was right.
- The first mutation pass left three survivors:
  - `sib-diagonal-le`: no box had a diagonal of exactly 28.8. The
    existing 192 case is two ulps over. From x = 0 with no radius the
    box is `fl(v * 0.15f)` long, and v = 191.99998474121094 gives 28.8f
    exactly. Three such cases catch it now.
  - `elev-hi`: the first pass's ceiling of 1 above the probe. It only
    shows when a surface between 0.5 and 1 up is listed before a lower
    one, and the probe is not on the last polygon. The far square's two
    floors now go into a table of their own, in both orders, and the
    last polygon is cleared before each probe.
  - `inside-early-out` is equivalent. `track_max` never lowers m or makes
    it a NaN, so the next check returns a positive value too, and every
    caller tests only the sign.
- `docs/formats/topology.md` is rewritten for retail, with both images'
  addresses. `docs/formats/car.md` notes the seventh slice on the retail
  image.

The whole suite passes, all 77 commands. The CIA builds and
`check_3dsx` finds its relocations OK. Nothing new runs in the game
yet, so Azahar was not run.

### Next

7b: DriveCameraMover::Update (`0x0015c880`), with GetLookbackCar and the
two wall helpers. Update also calls GetRoadNoise, which is still the
demo's. Either do TerrainType's retail pass first (the table at
`0x00318c00`, 33 x 144), or stub GetRoadNoise in 7b's checker.

## Session 31, continued (2026-09-29) -- TerrainType's retail pass

7b's Update calls GetRoadNoise, which reads the terrain table, and retail
had changed the table. So TerrainType's retail pass came before 7b.
`terraintype.c` is retail's `TerrainType.obj` (`0x001d4428 ..
0x001d4520`), `terraintypetab.c` is generated from retail's ELF, and
`careffects.c`'s TriggerCarTerrainEffects is retail's.

### The port

- **TerrainTypeInfo is retail's 144 bytes** (`terraintype.h`). A float
  at 20 is new, and everything from RoadNoiseGridSpacingInverse on is 4
  bytes later. MaybeMakeSkids (`0x001a568c`) multiplies it into
  `WheelInfo.Width`, so the port calls it SkidWidthMultiplier. It is 1.4
  on the loose surfaces and 1 elsewhere. On a 64-bit host only
  SkidTextureName takes an alignment pad now, and the record is 184
  bytes.
- **The table is retail's** (`0x00318c00`, 33 x 144).
  `gen_terrain_table.py` reads `SLES_507.31` and holds the table's
  address and size to the static initialiser's three instructions.
  Retail changed the data as well as the layout:
  - ROAD's skid smoke window is 5 to 40 (the demo's 5 to 200);
  - the loose surfaces' emitter groups have new names and speeds: DIRT's
    drive-over moved to the second group, 35 to 100 (the demo's was the
    first, 50 to 200);
  - BOARDWALK's road noise is 10 at 0.042 and COBBLESTONE's 3 at 0.048
    (the demo's 1 at 0.04 and 3 at 0.045);
  - METAL_GRATE's ShouldTireMakeRoadSound is 1 (the demo's 0).
  The friction and collision fields are the demo's.
- The code is the demo's but for the stride and the address. GetRoadNoise
  (`0x00153498`) reads offsets 24 and 28, so `track.c` is now all of
  retail's `Track.obj`.
- **TriggerCarTerrainEffects is retail's** (`0x00133920`, 2064 bytes;
  the demo's `0x00131db8`, 1872). Two changes besides the offsets:
  - Inside the splash, a car with a player, on every fourth world step
    (`(WorldLoopCounter + 3) & 3`), above 30 m/s, tells the replay:
    "InDeepWater" at 10 once, through InDeepWaterRegistered, and
    "InShallowWater" at 1.25 every time. The flag is cleared whenever no
    wheel down is in deep water, splash or not.
  - The engine smokes above 0.9 of visible damage (the demo's 0.8). Short
    of that, the radiator steams only when breakable item 14's level is
    3, through the retail-only `0x00124d38`, and the visible damage is
    above 0.65. The demo's steamed at any radiator damage and smoked too.
  - TriggerSplash is retail's `0x0018d488`. RegisterInterestingEvent
    (`0x0013e270`) is `replay.c`'s, and the port tests `pReplayManager`
    for NULL, which the image does not.

### The checks

- **`careffects_check.py` is new** and runs retail's
  TriggerCarTerrainEffects in RetailEmu, with retail's table and, under
  it, retail's TurnWipersOnForDuration, bMulMatrix, item level and
  GetVisibleTotalDamage. `careffects_test.c` is the harness. Both sides
  stub TriggerEffect, TriggerSplash, RegisterInterestingEvent and
  GetElevation. 3 scenarios, 110 ops, 519 lines, 0 differ. Of 136
  mutations, 133 are caught and 3 are equivalent.
- **`carmode_check` lost slice ten**: its terrain scenario, stubs,
  constants and mutations, and `carmode_test.c`'s side of them. 74
  transitions, 19 resets, 36093 lines, 103 masked, 0 differ. Of
  391 mutations, 380 are caught and 11 are equivalent. Nine of them, the
  null controller's, still looked for `car_new_null_controller` in
  `carmode.c`, which it left in ffedc28; they point at `carcontroller.c`
  now and are caught (the full pass tallied 371 of the other 382).
- **`track_check` is wholly retail's.** Road noise and both
  MatchTerrainTypes moved to the retail script, and the demo image's run
  is gone. 18033 ops, 11379 lines, 0 differ. Of
  314 mutations, 308 are caught and 6 are equivalent. The full pass
  first left `elev-num-total` alive: road noise joining the retail
  script had shifted the world scenarios' random draws, and lost the one
  that put a point over a polygon past the floors. Road noise draws from
  its own stream now, and `--only elev-num-total` catches it. The pass
  also still ran the demo script it no longer builds, and stopped on
  `ops`; that run is gone.
- `wheel_check`'s layout dump carries retail's offsets and
  SkidWidthMultiplier: 19 scenarios, 10696 lines, 0 differ.
- `docs/formats/topology.md` has the table's retail pass,
  `docs/formats/car.md` the tenth slice's, and `docs/formats/car-wheel.md`
  the record's new slack.

The whole suite passes, all 78 commands. The CIA builds and `check_3dsx`
finds its relocations OK. Nothing new runs in the game yet, so Azahar was
not run.

### Next

7b: DriveCameraMover::Update (`0x0015c880`), with GetLookbackCar
(`0x0015c680`) and the two wall helpers (`0x00157930`, `0x00157b60`).
GetRoadNoise is retail's now, so 7b's checker can run it. `replay.h` is
still the demo's layout (retail puts ReplaySnapshotList at 112 and
TotalInterestingValue at 332), and owes a retail pass before anything
reads it in place.

## Session 31, continued (2026-09-29) -- the drive camera's Update (step 7b)

This is 7b: DriveCameraMover::Update (`0x0015c880`, 6056 bytes) and the
helpers only it calls. DriveCameraMover is all ported now.

### The port

`drivecam.c`:
- **Update**, the vtable's slot 20, in the image's order. It picks the car
  (CameraFollowDefaultCar and CameraFollowThisCarInstead can swap it), steps
  the look back at LookbackSpeed, or 4/3 a second for a cop turning to its
  chased car, and gets the POV, falling back to index 0. Then:
  - the acceleration lag, from twenty samples of the car-space forward
    acceleration, 60 a second
  - the tweakables, which stand in for the POV
  - the base: the heading outside, the body inside
  - a cop's look back, iLookBackParam and iLookBackHeight
  - the boom's yaw and pitch, trailing by the corrections, with road noise
  - a counted look back's swing
  - outside, the eye's interest box, screen offset, wall push, lift out of
    the car and look-at offset; inside, the eye held 0.7 over the ground
  - the camera's words, the shake and SetCameraMatrix
- **GetLookbackCar** (`0x0015c680`): the chased car for a cop, and
  `isCop`, or the car of the cop chasing this one.
- **The wall push** (`0x00157930`, `camera_wall_offset`): ConstrainToTopology,
  then up to three averaged pushes out of every polygon the camera may not
  go through whose shaft holds the eye within the gap (GetWallGap for a
  polygon flagged 2, 0.7 otherwise). Four VU0 lanes, as the image adds
  them.
- **The look-at offset** (`0x00157b60`, `camera_look_at_offset`): two
  look-at matrices, the second to the target moved by the offset times
  its depth.
- The Drive* and Cam* tuning words, at retail's values (checked against
  the image's words).

`copmanager.h` is retail's cut: tCop's pMyPursuit (0) and pMyCar (4),
tPursuit's pChasedCar at 16 (the demo's 20), `pCopManager` at gp-15620
(`0x00331bec`), and seams for GetCopByCar (`0x00224f70`) and GetCopByChase
(`0x00224fc8`). Nothing sets them until the cop manager is ported, and
Update asks only while `pCopManager` is set.

Two fixes to 7a-2b's work:
- **LastCarSpeed is State.ForwardSpeed**, retail's word at car +960, in
  the constructor and ResetState. 7a-2b called it VelocityMagnitude, and
  the HANDOFF entry above says so. Update's walking-pace and lag tests
  read the same word as the forward speed. The checker writes a car's
  ForwardSpeed at 960 and its VelocityMagnitude apart, and
  `ctor_speed_vel` and `reset_speed_vel` are caught.
- **The heading's constant is `0.21276592f`** (`0x3e59df4f`, 1/4.7). The
  first `0.212766f` was six units off in the last place, and no
  transcript showed it: a pass over every float literal in the update
  section, against the words the image loads, found it.

### The checks

`drivecam_check.py` runs Update, GetLookbackCar and both helpers in
RetailEmu, over retail's base, Camera, SetCameraMatrix, eMath, bASin, bATan,
bCos and bNormalize. Both sides stub, printing their arguments:
- the TopologyCoordinate's constructor, destructor, SetInterestBBox,
  GetElevation and ConstrainToTopology
- PointInShaft
- GetCarByDriverNumber, bRefreshTweaker, GetCopByCar and GetCopByChase
- CarState::GetYaw, GetRoadNoise, GetCarSpaceBoundingBox and
  ApplyCameraShake

`drivecam_test.c` has the stubs and the new ops.

Six new scenarios drive four simulated cars frame by frame
(`docs/formats/camera.md`, "The drive camera, cross-checked"). The first
five put a mover on each car: the edges, the chase, the look back, the
cops and the tuning. A `gcov -b` build of the harness over the script
showed what they missed, and each gap has a scenario now:
- The cop's look back never came round: a random `H 0` or `u 0 -1` early
  on cleared the cop manager or the pursuit, and slip skewed the heading.
  The cops scenario now pins the chased car at nine bearings in turn,
  holding the manager, the pursuit, the POV and no player each time. The
  car has no slip, and no scribbles land on the mover while it settles.
  That reaches both step speeds, both clamps, both wraps and the wrap to
  65536.
- The lag held with DisableLag and DriverMode 1, and with
  CamBackAdjustQuicker lowered to 0.2 so the quick return runs.
- StopUpdating held over twelve frames of the tuning scenario. No Update
  scenario had set it.

Left unrun:
- GetLookbackCar's no-cop-manager and NULL-seam answers, which Update
  never reaches.
- Retail's own dead branch: the "in the air" factor is ±1, then tested
  against 0.
- Combinations the code rules out: a NaN DesiredLookBackParam, and a
  look-back car while the look back counts.

Every line ran, but the first mutation pass over 493 mutants left 23
unexplained. Eleven were equivalent (below). The other twelve were
changes no scenario could see:
- The lag's last-place changes (dividing by CamSpeedAdjust instead of
  multiplying by its reciprocal, and grouping the product another way)
  round away hundreds of metres from the origin.
- The lag's pull never lined up while the tuning scenario held the
  tweakables on.
- No run had only the twentieth sample holding the lag back, braked
  through walking pace with the lag held, or went past CamSpeedAdjust.
- The nose never pointed straight up. bASin gives 16384 only there, the
  one pitch at which `p <= 32767` and `p <= 16383` differ.
- CameraFollowThisCarInstead was never exactly 0 with driver 0 missing.
- StopUpdating never held while the camera's focus was still 0.
- A cop's look back was never wanted half way, and never pointed at a
  chased car 40-50 m off.

The sixth scenario, the corners, runs each of those in fixed spells
behind one camera on a car driven slowly near the origin. Its first cut
had two faults, and three mutants still survived:
- It built the mover looking back. A round of 1 takes the lag out of the
  POV's boom, and LookBackAngle sends the pitch down its first branch.
- It left CamLagMultiplier at 1, where either grouping of the lag's
  product is exact. It is 1.37 now.

14 scenarios, 45598 ops, 105702 lines, 0 differ. Of 493 mutations, 474
are caught and 19 are equivalent. The full pass ran before the corners
scenario existed. The other thirteen scenarios are unchanged, so its
catches still hold. `--only` over those twelve, `wall_continue` and
every equivalent catches the thirteen and none of the nineteen.

The first pass also caught `wall_continue`, which the list had as
equivalent. A pass that finds no wall does leave the probe where it was,
but the stubbed PointInShaft prints each call, so the extra passes show.
It is off the list.

The nineteen equivalents:
- Ten are the dead boom. After the eye, Update translates the boom once
  more by (lagx, lat, -height) and turns it by
  `angle + raise * (maxAngle - angle)`. Outside, nothing reads it, since
  the matrix is the look-at from the eye. Inside, `o` is never worked out,
  `raise` is 0 and `lagx` is `lag`. The image works it all out anyway.
  So `raise`, `wall.z`'s lift, `o` and its three folds, `lagx` there,
  and `maxAngle` from either source (that turn is its only reader)
  cannot show. The port keeps the dead code, in the image's order.
- The push's fourth lane: summing into it, and clearing it on the way
  out. The eye's pad reaches only the look-at, which never reads it.
- Also carried over: the signed bASin (two), the destructor's vtable,
  GetLookbackCar's cop-manager test, the braking spring's `ok`,
  `!canLB` on the cop's turn, and the pitch's first mask.

Two older mutations, `ext_incar` and `ext_pov0`, matched text that Update
now repeats. Their patterns carry more context now.

The whole suite passes, all 78 commands. The CIA builds and `check_3dsx`
finds its relocations OK. Nothing builds a drive camera in the game until
7d, so Azahar was not run.

### Next

7c: the orbit mover's retail pass. Player::ChangeCameraMover
(`0x00176ae8`, 2372 bytes) builds an OrbitCarCameraMover for most types,
from a `Car *`. The port's is still the demo's and follows a CamCarView.
Retail's GetTarget (`0x001580e0`) returns the car's GeometryPosition
(+80), not Position. Its Update (`0x00158298`) returns while the game
flow is paused, and follows `pCurrentWorld->Helicopter`. Then 7d:
ChangeCameraMover and CycleDriveCameraPOVIndex (`0x001786d0`), with the
drive and orbit paths ported and the other seven movers as seams.

## Session 31, continued (2026-09-30) -- the orbit mover's retail pass (step 7c)

This is 7c: OrbitCarCameraMover as retail has it. Player::ChangeCameraMover
(7d) builds one for most view types, from a `Car *`.

### The port

The orbit mover moved out of `cammover.c` into `orbitcam.c` and
`orbitcam.h`, as `drivecam.c` holds CM_DRIVE. So the base's checkers,
cambase_check and camera_check, no longer need World, the joystick layer
and the race coordinator just to compile `cammover.c`.
- **The constructor** (`0x00157e48`) is the demo's but for the offsets and
  the car. It ends with AddJoyHandlers. **The destructor** (`0x00158080`)
  calls RemoveJoyHandlers first. Neither checks for a camera, so a
  detached mover is only safe while CameraStopUpdating is set. Retail
  never writes TM (112), and the port no longer clears it.
- **GetTarget** (`0x001580e0`) is the car's GeometryPosition (+80), or
  the camera's Target with no car. **GetCarToFollow** is `0x0015fb18`.
- **Update** (`0x00158298`) differs from the demo's three ways:
  - It returns at once while IsGameFlowPaused (`0x001680b8`). That is
    `is_game_flow_paused` in `race.c`: pRaceCoordinator is set and in
    RCSTATE_PAUSE.
  - FollowChopper follows `pCurrentWorld->Helicopter` while its Plan is
    below 3 (compared unsigned) or is 4. It reads the CurrentPos (+832)
    and the matrix at +848 with its translation cleared, and adds no boom
    offset.
  - The AngleV clamp is gone. MinAngleV and MaxAngleV are stored and
    never read.
- **AddJoyHandlers** (`0x00158100`) and **RemoveJoyHandlers**
  (`0x001581f8`) register JoyHandler for events 46-54 on JoyPort, through
  `joyevent.c`'s AddJoyHandler and RemoveJoyHandler, and set or clear
  HandlersAdded.
- **JoyHandler** (`0x001586c8`) is the demo's nine-way jump. NEXT_CAR and
  PREV_CAR step through the car's links at 0 and 4 and skip the World,
  whose CarList is the list's head.
- The vtable is retail's `0x002b1c50`. It shares five of the base's
  slots, which `cammover.h` now exports as `camera_mover_get_camera_info`,
  `_get_pov`, `_is_exterior_view`, `_is_looking_back` and
  `_get_wall_gap`.

`chopper.h` lays out the head of the police helicopter, as far as the
orbit mover reads it: Plan at 728, CurrentPos at 832 and the Matrix at
848. It is task 26's class. Its layout check counts from
TOPOLOGY_SIZEOF, since the TopologyCoordinate's table widens on a 64-bit
host, and asserts 728 only where pointers are 4 bytes. Nothing builds a
chopper yet, so Helicopter stays NULL and the car path is the one taken.

`cammover.h` has lost CamCarView, the demo port's stand-in for a car.
`drivecam.h`'s comment now says ChangeCameraMover is 7d.

**The geometry viewer** follows a stand-in `Car` now, with its
GeometryPosition, Position and BodyMatrix set. It clamps AngleV itself
after each Update, to the mover's MinAngleV and MaxAngleV, and stops the
vertical speed there so the ramp starts again from rest. It also
destroys its mover before building the next one, and in geoview_free.
Retail's constructor takes nine nodes from the 96 in EventNodeSlotPool,
which does not overflow, so about ten car changes would otherwise have
run the pool dry. The retail scanner table maps no button to events
46-54, so the handlers never fire on the 3DS.

### The checks

`orbit_check.py` runs retail's own code in RetailEmu: the constructor, the
destructor and Update through retail's vtable, GetTarget, GetCarToFollow
and JoyHandler. Under them run retail's CameraMover base, SetCameraMatrix,
the matrix layer and IsGameFlowPaused, over retail's eView table.
`tools/src/orbit_test.c` runs the port over the same script. Both sides
stub AddJoyHandler and RemoveJoyHandler to print their arguments. The
script lays out the World, six cars, a Chopper and a race coordinator in
memory, and every camera and mover starts from a `0xa5` fill.

The scenarios:
- construction and every vtable slot
- every event from 40 to 60 at five values, in and out of FEMode, with
  the car list walked both ways past its head
- the chopper against every plan
- the pause across coordinator states
- the clamps and approaches at their edges
- the tweakables
- three random walks of 200, 800 and 1500 frames

9 scenarios, 3416 ops, 28635 lines, 0 differ. Of 124 mutations, 119 are
caught and 5 are equivalent:
- the destructor's own vtable store, which nothing reads before the
  base's
- multiplying by exactly 1.0f
- the speed approach at a gap of exactly the acceleration, and the
  AngleV walk at a gap of exactly 80, which land on the target either way
- TargetDistance from DesiredRadius, which equals Radius by then

The first pass left four unexplained:
- The two zoom mutations changed the constant's last hex digit by one,
  which rounds back to the same float. They step one ULP now.
- The constructor's clears of CarNotToRender and RenderDash were only
  ever seen on a camera already holding zero. A new `N` op writes the
  camera's two words first, and a new `P` op prints the camera after the
  constructor.

`camera_check.py` loses its model of the demo's orbit mover. It keeps the
Camera and base-mover scenarios: 4 scenarios, 556 lines, 0 differ. Of 35
mutations, 32 are caught and 3 are equivalent. Its first pass left two
unexplained, `mover-view-zero` and `mover-pview-zero`: only a mover on a
view other than 0 shows them, and its only such movers were the orbit's.
They moved to `cambase_check` as `mctor_view_zero` and
`mctor_pview_zero`, and both are caught there, 61 of 61.
`cambase_test.c` loses a clock definition only the orbit needed.

`docs/formats/camera.md` has "Retail's orbit mover", under "Retail". Its
"Divergences from the disc" and "Cross-check" sections no longer describe
the demo port.

The whole chain in CONTINUE.md, orbit_check included, passes: 79
commands, 0 failed, 1021 s. On Azahar (Speed 100%, 60 FPS),
`run_azahar_geo.ps1 -Cars 14` rebuilds the mover 13 times and draws all
fourteen cars, with 0 textures missing. `cam-elev-clamped` is the
top-down view, held by the viewer's clamp, and the zoom creep measures
0.007/255. camera.md's "On the emulator" says so.

### Next

7d: Player::ChangeCameraMover (`0x00176ae8`, 2372 bytes) and
CycleDriveCameraPOVIndex (`0x001786d0`), with the drive and orbit paths
ported and the other seven movers as named seams. CONTINUE.md, step 7d,
has what is read so far.

## Session 31, continued (2026-09-30) -- Player's camera functions (step 7d)

This is 7d, and it closes step 7: Player::ChangeCameraMover and the five
small camera functions around it, as retail has them.

### The port

`playercam.c` and `playercam.h` are new. They sit apart from `player.c`
because they build movers, and `player.c` goes into harnesses that have
no use for `drivecam.c` and `orbitcam.c`.
- **ChangeCameraMover** (`0x00176ae8`, 2372 bytes) first deletes the demo
  and countdown coordinators and the NIS coordinator, and clears each
  pointer. Only then does it return if the mover is already of that type.
  The car is MyCar, or the first link of World's CarList, unchecked. With
  `keep`, the old mover is disabled and saved, and the one saved before
  it moves to the second slot. Without `keep` it is deleted through its
  virtual destructor. The switch is unsigned: 4-12 and anything past 17
  build the orbit.
- **The drive camera** is bMalloc(1008) and the constructor with the POV
  byte, 300.9 for the look-back speed, CameraSpring, 0 and 1. Its
  DesiredLookBackParam follows bLookBack, and the POV byte goes through
  the cycle. **The orbit** is bMalloc(208), then `orbit_init` with JOY
  port 1.
- **The other movers are seams**, each a function pointer that stays NULL
  until its class is ported: the debug world, the track route editor, the
  zone freeze, the zone preview, the cubic damper, and one for both zone
  jumpers. With a mover's seam NULL, nothing is allocated and the player
  has no camera. The coordinators, the NIS manager's three calls, the
  driving line's two and PreviewRoute's destructor are seams too.
- **CycleDriveCameraPOVIndex** (`0x001786d0`) takes the index mod 4, as
  C's remainder, and tries up to four POVs from there. A POV counts if
  SkipFE is set, the ride has a dash, or it is the bumper or the outside
  view. If none counts, the index is 0. It reads the car unchecked, as
  retail does.
- **RestoreCameraMover**, **RemoveCameraMovers**, **EnableCameraMovers**
  and **DisableCameraMovers** (`0x00176948`, `0x00177430`, `0x001774a8`,
  `0x00177558`) are retail's. The one difference is restoring with
  nothing saved: retail calls Enable through NULL, and the port does
  nothing.

`player.h` gains pSavedCameraMover2, retail's +208, at the port's 2480,
past the demo's layout. SkipFE is `gPlayerCamSkipFE`, which `main.c`
points at the flow's skipFE. NULL reads as 0.

Nothing calls these yet. Step 8 brings the callers.

### The checks

`playercam_check.py` runs retail's six functions in RetailEmu, and
`tools/src/playercam_test.c` runs `playercam.c`, over one op script. The
emulator's memory holds:
- the Player, four cars and their rides, World, and every coordinator,
  at retail's offsets
- two pools of movers, one for the new ones and one for those an op
  plants
- fake vtables, and stubs for bMalloc, the constructors, SetPOVIndex and
  the seams, each printing what it was handed

The zone jumpers' two slots in the jump table point at small thunks.
They call the seam's stub and return through the switch's tail.

The scenarios:
- every type, with and without keep, from the car and from World's list
- keep chains and restores
- the POV cycle over 14 POV layouts, indexes -9..9, SkipFE and the dash
- the coordinators' 16 masks
- three random walks of 300, 800 and 1500 ops

7 scenarios, 5277 ops, 162056 lines, 0 differ on the first full run.
The harness's pools had to grow to 1024 and 256 first, for the walks.

All 109 mutations are caught, and none are equivalent. Three crash the
harness on a NULL car: reading the car only from World, reading World's
list the other way, and ignoring SkipFE. On the first pass, the
mutations that removed a statement left the next one as the `if`'s body,
and three did not compile. Each now leaves an empty statement, and the
second pass compiled all 109.

`docs/formats/camera.md` has "The player's cameras", before "Divergences
from the disc".

The whole chain in CONTINUE.md, playercam_check included, passes: 80
commands, 0 failed, 960 s. `build_cia.ps1` builds the CIA. Nothing in
the game calls the new functions yet, so there is nothing new to see on
Azahar.

### Next

Step 8, first slice 8a: the Player constructor (`0x001751d8`, 2580 bytes),
Player::InitForRace (`0x00181920`) and Player::CleanupAfterRace
(`0x00181970`), which calls RemoveCameraMovers. Then RaceCoordinator's
InitForRace, InitCars and InitPlayers, the Race constructor and
Race::Init, and the flow into a race. CONTINUE.md, step 8, has the
call lists.

## Session 31, continued (2026-10-01) -- Player's lifetime (step 8a)

This is 8a, the first slice of step 8. It gives Player retail's layout and
ports the code that builds a Player, hands it a car and takes it back.

### The layout

`player.h` is retail's 2752-byte Player, field for field. The demo's is
2480. The map comes from lining up the two constructors (`0x0016ee50` in
the demo, `0x001751d8` in retail) and from the methods that read each
field. Against the demo the fields move in bands: +12 for the race and
zone words, +24 for the NIS words and the flailers, +64 from the radar
on, +208 for the auto-replay words. Retail adds words at 20
(pOtherPlayer), 180, 184, 2540 and 2616, and the score display at the
end. The NIS overlay at 2560 is 56 bytes, not 40, and lastCar is at
2616, not 2600. cPlayerSettings is retail's 48 bytes too: Lookback at 12
is an int, and retail adds the byte at 7 and the words at 40 and 44. The
offsets are asserted where pointers are 4 bytes. pSavedCameraMover2 moved
from the port's 2480 to retail's 208, so camera.md's offset table has one
column.

The harnesses that build a Player by name (carmode, collisionbody,
drivecam, realcontroller, realdriver, rendercars, shake, world,
playercam) all still pass.

### The port

`playerinit.c` and `playerinit.h` are new:
- the constructor (`0x001751d8`, 2580 bytes)
- the destructor (`0x00175bf0`)
- InitForRace (`0x00181920`)
- PredetermineNisNumbers (`0x001819e0`)
- CleanupAfterRace (`0x00181970`)
- CleanUpJumpCam (`0x00176ab0`)
- cPlayerSettings::ResetToDefaults (`0x001edf90`)

`nisoverlay.c` and `nisoverlay.h` are new too, with NISOverlayManager's
constructor, destructor, SetScreen (new in retail) and Finish. The HUD,
the NIS manager, the samples, the driving line, the HUD animators,
CreateRandomNisArray and SetInputMode are seams. Each is NULL until its
class is ported, and the port skips a NULL one. With the NIS manager's
seam NULL nothing is allocated, as playercam.c's movers do.

The port differs from retail in three places, each written up in
player.md:
- Both player tables stop at two. Retail's third pPlayersByIndex entry
  would be NumPlayers.
- GetTopLeft is not called on a missing score object. Retail reads
  through NULL there.
- The Average is the port's size until Average's retail pass.

TheRaceParameters' +628 is BeACop. `race.h` gains AIDemoMode and
ReplayDemoMode, and `playerinit.h` has PlayerSettings[2] at +652.
`main.c` now sets gPlayerCleanUpJumpCamFn, so Car::FinishMovement ends
the jump cam through playerinit.c. Nothing builds a Player yet. 8b's
InitCars and InitPlayers come first, then InitForRace.

### The checks

`player_check.py` runs retail's eleven functions in RetailEmu, and
`tools/src/player_test.c` runs `playerinit.c`, `nisoverlay.c` and
`player.c`, over one op script. Every callee is a stub that prints its
arguments, except AutoPilotOff (a bare `jr ra`) and bStrCpy, which run.
The script fills each Player before it is built (0xa5 mostly, sometimes
0xff, 0x5a or 0), so a field a call leaves alone shows. It covers:
- the ctor's flag combinations
- ResetToDefaults
- the destructor over what the player owns
- InitForRace and CleanupAfterRace over the control modes
- the score display's object masks
- three random walks of 300, 800 and 1500 ops

Before the run, the checker compiles `player.h` with devkitARM and asserts
all 158 Player fields and 14 overlay fields at retail's offsets.

8 scenarios, 3659 ops, 501513 lines, 0 differ. All 287 mutations are
caught, and none are equivalent. Three crash the harness, as three of
playercam's did: the constructor's index of 1, the constructor's count
left alone, and the destructor's clear of index 0. Each leaves the
player tables out of step, and the harness reads a NULL player.

The first pass had four survivors: the destructor's zeroes of LastSpeed,
the two Prev*Level words and LastSpeedSet. The constructor zeroes them
too, and no op changed them in between. The F op can now set all four,
and the destructor scenario and the walks use it. One mutant, removing
the car's pPlayer clear, had emptied an `if` and did not compile. It now
leaves an empty statement.

`docs/formats/player.md` is new. CONTINUE.md has the 8b plan, read from
retail: RaceCoordinator::InitForRace, InitPlayers, InitCars, AddRacingCar
and CalculateRacerPositions, and retail's 24-byte DriverInfo.

The whole chain in CONTINUE.md, player_check included, passes: 81
commands, 0 failed, 959 s. `build_cia.ps1` builds the CIA. Nothing in
the game builds a Player yet, so there is nothing new to see on Azahar.

### Next

8b: InitCars (`0x0014a2c8`) and InitPlayers (`0x00149cb8`), with
AddRacingCar (`0x00149f10`) and CalculateRacerPositions (`0x0014a020`).
CONTINUE.md, step 8, has what each does. Then 8c (Race's constructor,
Race::Init and SetupGhostCars) and 8d (RaceCoordinator::InitForRace and
ChangeState).

## Session 31, continued (2026-10-01) -- InitCars and InitPlayers (step 8b)

This is 8b, the second slice of step 8. It ports the code that puts a
race's cars on the grid and hands each Player its car.

### The port

`raceinit.c` and `raceinit.h` are new:
- RaceCoordinator::InitCars (`0x0014a2c8`, 808 bytes)
- RaceCoordinator::InitPlayers (`0x00149cb8`, 188 bytes)
- AddRacingCar (`0x00149f10`, 272 bytes)
- CalculateRacerPositions (`0x0014a020`, 680 bytes)

CalculateRacerPositions takes the grid from the track's starting markers
when every slot has one. Otherwise it steps the grid out along the track
path: pairs 17 apart from 100 on, 3 to either side. The heights come from
one TopologyCoordinate for every slot, and each probe starts from the
height of the slot before. The 8b notes in CONTINUE.md had a fresh
coordinate per slot, started from 0. The transcript showed otherwise, and
the notes are corrected.

AddRacingCar builds the car facing along the path, as far around it as
the path says, and sets its control mode. An AI racer starts in
nDefaultMovementMode (gp-22960, 4) and anything else in PHYSICS_MOVEMENT.
The car goes on the end of CarList, and an AI racer on AICarList too.

InitCars puts the first driver still in the event at each of the eight
positions and builds the car table. It gives the AI racers their first
route: the track's override, or else where the first AI racer finds
itself. Then come the traffic, the cops, the helicopter and the Be A Cop
call. AddCopCarToRace, Chopper's constructor and the egg table are seams.
With the cop seam NULL, each cop driver still counts towards the
helicopter and the Be A Cop call. InitPlayers hands each Player its car
by number, or from the car table under AIDemoMode.

DriverInfo is 24 bytes now, as retail's is. Retail put a rank byte in
front of the record; the port keeps the demo's offsets and puts it at 20,
as EliminatedRank. `race.c` and `race.h` gain TrackNumber, the driver
array and GetDriverInfo (`0x001edb28`). `car_check` expects the new size.

`main.c` sets gCarInitRenderInfoFn and gCarRenderInfoDestroyFn, and makes
the two render-info slot pools, so a car InitCars builds gets its render
info.

The port differs from retail in three places, none of them seen, each
written up in raceinit.md:
- With no override, the AI racers' start route is zeroed. Retail leaves
  it unset, and IsValid reads the stack.
- The slots' fourth lanes are zeroed.
- An override that names a NULL route gives a NULL point. Retail's is
  1064.

### The checks

`raceinit_check.py` runs retail's four functions in RetailEmu, and
`tools/src/raceinit_test.c` runs `raceinit.c`, `race.c`, `airoute.c` and
`vtable.c`, over one op script. Every callee is a stub on both sides. Each
answer is a hash of the call's arguments, so a wrong argument shows in
what follows. After each call the harness prints World's two lists, its
car table and helicopter, and the nine slots. The controller's fake
vtable gives SetCurrentRoute and GetCurrentRoutePoint a this-delta of 4,
so a call that skips the adjustment shows. Before the run, the checker
compiles `raceinit.h` with devkitARM and asserts DriverInfo's layout.

32 scenarios, 3280 ops, 13317 lines, 0 differ on the first full run. All
123 mutations are caught, and none are equivalent. Five crash the
harness: AddRacingCar with a NULL position, and each of the four list
links left out, which leave a list the harness cannot walk.

Retail's Car::GetRoute and GetRoutePoint take no argument, but the
controller slots they call take a bool, which gets the caller's a1.
CONTINUE.md has it as a follow-up for task 26's AICarController.

`docs/formats/raceinit.md` is new. CONTINUE.md marks 8b done and makes 8c
next.

The whole chain in CONTINUE.md, raceinit_check included, passes: 82
commands, 0 failed, 984 s. `build_cia.ps1` builds the CIA, and
check_3dsx passes. Nothing in the game calls InitCars yet, so there is
nothing new to see on Azahar.

### Next

8c: Race's constructor (`0x001475e8`), Race::Init (`0x00147960`) and
SetupGhostCars (`0x001485e0`). CONTINUE.md, step 8, has what the
constructor and Init do. Then 8d (RaceCoordinator::InitForRace,
ChangeState and GetDriverInfoByDriverNumber) and the flow into a race.

## Session 31, continued (2026-10-01) -- Race's construction (step 8c)

This is 8c, the third slice of step 8. It ports the Race a race runs on:
its constructor and destructor, the lap boundaries, and the table of how
long a lap takes. Race.obj was more than one slice, so step 8 is now 8c
(the construction), 8d (Race::Init and the lap counting) and 8e
(RaceCoordinator::InitForRace).

### The port

`race.h` now declares retail's whole 1716-byte Race, field for field. The
offsets and the size are asserted where pointers are 4 bytes.
pCurrentRace's comment gives retail's address, gp-22272 (`0x003301f0`).
`race.c` adds TheRaceParameters' Point2Point (+40) and NumLapsInRace
(+44, 2 by default).

`racecore.c` and `racecore.h` are new:
- Race::Race (`0x001475e8`) and Race::~Race (`0x001476e0`)
- FigureOutBoundaries (`0x00147b20`) and AddBoundaryPosition
  (`0x001479f8`)
- GetLapNumberExact (`0x00147d58`)
- SetupGhostCars (`0x001485e0`), which is empty in retail
- RacingCar's constructor (`0x001493b8`) and UnInit (`jr ra`)
- TimeAroundTrackTable's constructor (`0x001467a0`), GetTimeTableEntry,
  GetTimeAroundTrack and destructor

The constructor sets pCurrentRace and the lap count, which is 1 on a
point-to-point race that has laps. It zeroes what it owns, sets
BestLapTime to 0x7fffffff, and finds the boundaries. The boundaries are
the start line, three splits and, point to point, a finish line, each
from its track marker or else a fixed distance past the start. Split 3
has no fixed distance and so needs a marker. A backward track adds the
splits in the other order.

The destructor destroys the replaying ghost car's WorldObject only inside
the test of its data. That destructor is the one seam,
gWorldObjectDeleteFn. Nothing in retail makes a ghost car, so the seam
can stay NULL.

The boundaries are read and written through the Race's bytes, as the
image does. A finish number of -1 then reads the four bytes before the
array as a float, as retail does.

The TimeAroundTrackTable walks each racing route's driving line for the
car's class. Each segment gives the part of a lap it covers over the
time the line's speed takes, and that rate goes into the first 1/256 of
the lap it starts in. Entries without a rate take the one before's, and
the times add up from the line. `docs/formats/race.md` has every step.

### The checks

`racecore_check.py` runs everything above as shipped in RetailEmu, with
retail's TrackPathCoordinate constructors and destructor,
ComparePercentDistances, GetPosition and bScaleAdd under it.
`tools/src/racecore_test.c` runs `racecore.c` with `race.c`,
`trackroute.c`, `trackpath.c` and `bmem.c` over the same script. Only
UpdatePosition, the marker lookup, delete and the WorldObject destructor
are stubbed. UpdatePosition answers from a hash of the position, either
anywhere in 2^-7 .. 2^9 or in [0, 1) as a real track's would be. The
Race and the table are filled with 0xa5 before each build, so a field
left alone shows. Before the run, the checker compiles `racecore.h` with
devkitARM and asserts Race's and the table's layout.

9 scenarios, 6097 ops, 18698 lines, 0 differ, from the first run on. The
first run's routes rarely had a valid line for the class, so most tables
were the default. The generator now favours valid lines and longer
routes, and 16 of 36 tables carry real rates, 3737 entries. Of 161
mutations, 158 are caught. One of them, a constructor that leaves
pCurrentRace NULL, crashes the harness, since the table's lap lookups
go through pCurrentRace. The 3
equivalent ones are stores written again before they can be read.

`docs/formats/race.md` is new. CONTINUE.md marks 8c done and makes 8d
next, with RacingCar::Init and UpdateLapCounts read from the listing.

The whole chain in CONTINUE.md, racecore_check included, passes: 83 commands, 0 failed, in 1007 s.
`build_cia.ps1` builds the CIA, and check_3dsx passes. Nothing in the
game builds a Race yet, so there is nothing new to see on Azahar.

### Next

8d: Race::Init (`0x00147960`), AddRacingCars and AddRacingCar,
RacingCar::Init, UpdateLapCounts and CheckBoundaryCrossing,
SortRacingCarsByLeadership, SetRaceStage and FakeStartlineCrossing, and
Timer::Round. CONTINUE.md, step 8, has what Init, RacingCar::Init and
UpdateLapCounts do. Then 8e (RaceCoordinator::InitForRace, ChangeState
and GetDriverInfoByDriverNumber) and the flow into a race.

## Session 31, continued (2026-10-01) -- Race::Init and the lap counting (step 8d)

This is 8d, the fourth slice of step 8. It ports what a Race does once it
is built: Race::Init and everything under it that counts laps, times the
boundaries and orders the field.

### The port

`racerun.c` and `racerun.h` are new:
- Race::Init (`0x00147960`), AddRacingCars (`0x00147dc0`) and
  AddRacingCar (`0x00147e88`)
- SetRaceStage (`0x00147ef0`) and SortRacingCarsByLeadership
  (`0x00148218`)
- RacingCar::Init (`0x00146bb0`), UpdateLapCounts (`0x00146fd0`),
  CheckBoundaryCrossing (`0x00146e58`), FakeStartlineCrossing
  (`0x00146e08`) and GetPlayer (`0x001475b8`)

`timer.c` gains Timer::Round (`0x001a3e28`) and RoundSeconds
(`0x001a3d70`), which round a time to a hundredth, half up, and then up
to a whole tick.

Race::Init adds the World's racing cars (the players' cars below
AICarPos, then the AI racers up to CopCarPos), sorts them twice, sets
the stage, and builds the
TimeAroundTrackTable for the first car's class, or the second's for a
two-player cop race. SetRaceStage sets the drivers going on the way to
racing: the real drivers lose their start-line hold and the AI ones get
full throttle with the brakes off. It stamps the start time and frames,
and wakes the traffic at the countdown and the start.

UpdateLapCounts checks each boundary for a crossing since the last call,
from the percentage round the track, within 25 percent either side. A
forward crossing of a region the car has not reached yet stamps the time
the car crossed, backed off by how far past it is now at its speed, and
rounded to a hundredth. That time gives the running, best and lap times.
A backward crossing of the finish line takes a lap off. It also keeps the
top and average speeds, the exact lap and its smoothed rate. The sort is
retail's bubble sort: finished cars by their finishing order, the rest by
the exact lap they reached.

`race.h` adds the RaceTypes enum (type#1000) and TheRaceParameters'
RaceType (+32, `0x0031a8b8`). While a replay plays, only a time trial's
finish line is timed. FrontendDatabase::TheRaceIsLeaving is the one
seam, gRaceIsLeavingFn. SetRaceStage calls it on the way to racing.

The top speed of a car that is not the player's is what its driver
wants, through CarDriver's slot 136, GetDesiredSpeed, which
`cardriver.h` names now.

Retail's CarState has one float the demo's lacks, at State+876, which
UpdateLapCounts divides by the race time for the average speed. The port
calls it DistanceMoved and keeps it at 1012, in the record's spare tail,
so that every demo offset holds. The constructor zeroes it, as retail's
does, and `carstate_check` and `physicscar_check` know the field. Retail's
FinishMovement adds to it how far the car moved, and the port's, the
demo's, does not yet. Until it has its retail pass, AverageSpeed reads 0
in the game. CONTINUE.md records that as owed.

### The checks

`racerun_check.py` runs all ten functions and the two Timer ones as
shipped in RetailEmu, with retail's GetLapNumberExact,
ComparePercentDistances and TimeAroundTrackTable under them.
`tools/src/racerun_test.c` runs `racerun.c` with `timer.c`,
`racecore.c` and their callees over the same script. Only bMalloc,
SetMovementMode, DisableStartLineState, TheRaceIsLeaving, UpdatePosition
and the drivers' GetDesiredSpeed are stubbed. The desired speed sits in a
vtable the script owns, behind a this-adjustment it sets. The Race, the
Cars and their records are filled with 0xa5 first, so a field left alone
shows.

14 scenarios, 21656 ops, 40973 lines, 0 differ. Of 171 mutations,
169 are caught and 2 are equivalent. Three of them are caught by crashing the harness and two by hanging it. The two equivalents are Init's store to FinishedLapNumberExact, which UpdateLapCounts writes again before anything reads it, and TopSpeed's test for a change before it stores. A first pass left nine survivors; eight of them were gaps in the script, and the edge-case scenario closes them.

`docs/formats/race.md` has a section for 8d. CONTINUE.md marks 8d done
and makes 8e next.

The whole chain in CONTINUE.md, racerun_check included, passes: 84 commands, 0 failed, in 1015 s.
`build_cia.ps1` builds the CIA, and check_3dsx passes. Nothing in the
game calls Race::Init yet, so there is nothing new to see on Azahar.

### Next

8e: RaceCoordinator::InitForRace (`0x00149988`), ChangeState
(`0x00149520`) and GetDriverInfoByDriverNumber (`0x001edb40`).
CONTINUE.md, step 8, has what InitForRace does. Then the flow into a
race.

## Session 31, continued (2026-10-01) -- RaceCoordinator's lifetime (step 8e)

This is 8e, the fifth slice of step 8. It ports the RaceCoordinator up to
its state callbacks. That covers its constructor and destructor,
InitForRace, which builds a race out of everything 8a to 8d ported, and
CleanupAfterRace, which takes it down. It also covers the message queue
the ten states run on.

### The port

`racecoord.c` and `racecoord.h` are new:
- the constructor (`0x00149738`), the destructor (`0x00149858`) and
  `racecoordinator_new`, which is `new RaceCoordinator`
- InitForRace (`0x00149988`)
- CleanupAfterRace (`0x00149b88`), CleanupPlayers (`0x00149d78`) and
  CleanupCars (`0x0014a5f0`)
- ChangeState (`0x00149520`), SendMessage (`0x00149650`), PostMessage
  (`0x001496d8`) and ExecuteQueuedMessages (`0x00149578`)
- SetAIDriverModesFromPlayers (`0x001cd240`) and
  RaceParameters::GetDriverInfoByDriverNumber (`0x001edb40`)

The RaceCoordinator is 144 bytes. Every field is where the demo has it.
Retail adds one word at 140, in the demo's tail padding. Only the post-race
callback uses it, so the port calls it PostRaceWord140 for now.

InitForRace builds the players from the driver table: player 1 for driver
0 (or the AI demo), player 2 for driver 1, each unless eliminated. Then
it builds a ReplayManager, the Race and the World, and calls InitCars and
InitPlayers. It picks the first state and the race's stage:
- the AI demo, the replay demo, and SkipFE race at once
- Be A Cop, or a loaded prerace animation, starts with the flyby
- anything else starts with the countdown

Then it calls Race::Init, the ghosts, the AI driving styles, and the
sound and speech resets. It sets pRaceCoordinator, and changes state as
a tail call. The constructor unloads the prerace animation first when
pool 16 has less than 0x7d000 bytes free, so a short-on-memory race skips
the flyby.

The queue: SendMessage queues and runs the queue unless a message is
running. PostMessage only queues. ExecuteQueuedMessages runs the state's
callback for each message from the front, with ACTIVATE setting the state
before the call and UNACTIVATE clearing it after. ChangeState is
UNACTIVATE, ACTIVATE and TICK, in that order.

The ten callbacks are a seam table, gRCStateCallbacks. A NULL entry
takes nothing. Retail indexes its table unchecked, and the port guards
the index. Most of what InitForRace and the cleanups call is a NULL seam
until its class lands:
- the pause menu, the ReplayManager and EndGameScreens
- the Chopper's destructor and CleanUpAutoReplay
- the effects, the jukebox, the one-shots, collision_sound and the speech
  queue
- FindResourceFile by name

A NULL constructor seam allocates nothing.

Retail's destructor ends with ~bTList, which frees any message left on
the queue into the slot pool it deleted a moment before. The port only
empties the list.

`race.h` gains TheRaceParameters' NumAICars (+52), which the AI driving
styles split the field by.

`main.c` does not set trackflow's gNewRaceCoordinatorFn yet. Doing so
would build players, a World and cars through the real InitCars as soon
as a track loads, with every state callback still a NULL seam. It comes
with the slice that flows into a race. trackflow.h's and replay.h's
comments now give retail's addresses.

### The checks

`racecoord_check.py` runs all twelve functions as shipped in RetailEmu,
with GetDriverInfo, GetRacingCar, GetDrivingStyle, RaceParameters::Print,
World::FlushCollisions and RCQueuedMessage's destructor under them.
`tools/src/racecoord_test.c` runs `racecoord.c` with `race.c` over the
same script. Every other callee is stubbed on both sides. The World's
constructor builds the scenario's world, and the Player's constructor
registers the player as Player's own does. The ten state table entries
point at fake callbacks. Script reactions make them answer a message with
SendMessage, PostMessage, ChangeState or ExecuteQueuedMessages, run in
the image from inside the stub with the registers saved and restored.

175 scenarios, 7038 ops, 26129 lines, 0 differ. Of 136 mutations, 135
are caught: eleven by crashing the harness and one by hanging it. The
one equivalent is the destructor emptying the list, which no scenario
can leave a message on, because of the use-after-free above. The first
pass left one survivor: the executing flag cleared after the slot's free
instead of before. The free line now prints the flag, which catches it.
Before the run the checker compiles racecoord.h with devkitARM and
asserts its layout.

`docs/formats/race-coordinator.md` is new. CONTINUE.md marks 8e done and
makes 8f, the state callbacks, next.

The whole chain in CONTINUE.md, racecoord_check included, passes: 85 commands, 0 failed, in 1018 s.
`build_cia.ps1` builds the CIA, and check_3dsx passes. Nothing in the
game builds a RaceCoordinator yet, so there is nothing new to see on
Azahar.

### Next

8f: the state callbacks a race runs through. Start with
RCStateNoneCallback (`0x0014a668`), RCStateRaceInProgressCallback
(`0x0014ae80`), DisplayCountdownNumber and TheRaceHasFinished, then the
flyby and the prerace. CONTINUE.md, step 8, has the jump tables. Then
wire the coordinator in and flow into a race.

## Session 31, continued (2026-10-02) -- the race coordinator's states up to the finish (step 8f)

The user asked to keep going through the port without stopping. 8e was
committed as 1df517f. This slice ports the first four of the ten
RaceCoordinator states and what they call, from retail.

### The port

`rcstates.c`/`rcstates.h` have RCStateNoneCallback, the flyby, the
prerace and the race in progress, with DisplayCountdownNumber,
Animate321GoElement, TheRaceHasFinished, the joystick handler,
RequestPause, RequestUnPause, Resume/SuspendDemoCameras and the
frontend's unnamed record-times loop. `rcstates.c` defines
gRCStateCallbacks now, with the four at their RCStates. The other six
stay NULL.

`racefinish.c`/`racefinish.h` have the six Race methods the states ask:
the countdown's number and progress, SimulateRaceFinish,
NotifyTheRaceIsOver, AreAllPlayersFinishedRacing and
GetMostRecentlyFinishedPlayer. FinishCar and RaceEvent::RecordResults are
seams.

`race.h` gains tGlobalDisplaySettings and TheRaceParameters'
GlobalDisplaySettings (+748), which RESTART_RACE and NEXT_RACE copy from
the frontend database's +332.

Retail reads the flyby and prerace cameras, the ReplayManager and the
most recently finished player without a test. The port reads a missing
camera as finished, skips the replay's marks with no ReplayManager, and
does not finish a race with no players. The demo-disc branches (QUIT_RACE
and TheRaceHasFinished) are dropped, as for every port of retail.

### The checks

`rcstates_check.py` runs the twelve RaceCoordinator functions, the
record-times loop and the six Race methods as shipped, on top of the 8e
queue. `tools/src/rcstates_test.c` runs the port over the same script. It
takes `racecoord.c` through a wrapper the checker generates, because
hostbuild's object cache keys on a source's own bytes and not on a `.c`
it includes. The wrapper renames InitForRace and CleanupAfterRace so
both sides can stub them. States 4 to 9 are fake callbacks with script
reactions, as in 8e.

402 scenarios, 17258 ops, 40165 lines, 0 differ. Of 148 mutations, 143 are
caught and 5 are equivalent: four guards in the two-player hand-over,
which at most two players cannot tell apart, and the countdown's clamp at
the end of a window. The first pass left a flyby TICK with no camera and
RecordResults taking a car off the count untested. New edge scenarios and
an `rdrop` answer close both.

`docs/formats/race-coordinator.md` gains the 8f section. CONTINUE.md
marks 8f done and makes 8g, the pause and the post-race, next. It also
gives their decode. `rcpost.c`/`rcpost.h` hold an unchecked first draft
of 8g and are not committed with 8f.

### Next

8g: check `rcpost.c` against retail by extending rcstates_check, then the
replays and the demos, then wire the coordinator in.

## Session 31, continued (2026-10-02) -- the race coordinator's pause and post-race (step 8g)

8f was committed. This slice ports two more of the ten RaceCoordinator
states, PAUSE and POSTRACE, from retail. Midway the user asked how far
the port is, and how close a car on a track is. The answer was about
30-48 slices to the full game, and about 3-4 to a first drive on
Azahar, with the replay and demo states put off so that the wiring comes
first.

### The port

`rcpost.c`/`rcpost.h` have the pause, the post-race, Player::BeginPause
and EndPause, and TellPlayersToPause and TellPlayersToUnPause.
`rcstates.c`'s table has them at 6 and 7. RaceCoordinator+140, retail's
new word, is `PostRacePlayerNumber` now, in `racecoord.h`, `racecoord.c`,
`racecoord_check` and its harness.

The pause's ACTIVATE tells the players, enters the pause menu with the
port that asked, shows "Pause Menu" and mutes. Its unpause reasons
resume, go to the instant replay, quit or restart. The post-race puts
every camera mover to CM_NONE, flushes the speech, starts the
highlights and the end-game screens, and follows the best-placed
player's car with a demo camera. Each highlight's end in
WorldLoopCounter, or SKIP_REPLAY, makes a new camera.

The replay's two words are seams, because the port's ReplayManager is
not retail's layout. Retail reads the ReplayManager unchecked, and the
port's TICK does nothing without one. The demo disc's end reason on
QUIT_RACE is dropped.

### The checks

`rcstates_check` runs the two callbacks, the four Player calls,
GetJoystickType and the two empty World methods as shipped. States 4,
5, 8 and 9 stay fake, and the reactions answer only on them. The
harness gains joystick.c and stubs for the pause menu, ChangeToScreen,
the frontend's quit and restart, ChangeCameraMover, the speech, the
replay, the end-game screens, GetDriver, ClearHudAnimations and the
type-changed handlers' reinstall. The arena is 64 objects now, since
every highlight makes a camera.

600 scenarios, 29584 ops, 64046 lines, 0 differ. Of 230 mutations, 225 are caught
and 5 are equivalent.

### Next

Wiring the coordinator in, the plan for 8h, needs a Car, and Car's
constructor reads `CarTypeInfoArray`, which is NULL: LoaderCarInfo is
not ported. So 8h is the car data loader (LoaderCarInfo and the
acceleration tables), 8i is CarLoader (each car's geometry and skin),
and 8j wires the coordinator in for one car on a track on Azahar.
CONTINUE.md has the lists.

## Session 31, continued (2026-10-02) -- the car data loader (step 8h)

8g was committed. This slice ports slot 16 of the loader table from
retail: LoaderCarInfo and UnloaderCarInfo, and the 64 acceleration
tables they make, so that CarTypeInfoArray is set in the game and a Car
can be built.

### The port

`carinfo.c`/`carinfo.h` are new. The constructor gives each table its
own 32 entries over 0 to 200 km/h: 4.0 in the first 31 and 0 in the
last. The static constructor runs it over all 64 from `sinit.c`, at
`__CTOR_LIST__` [35]. 0x34600 points CarTypeInfoArray at the records,
which start at `(chunk + 23) & ~15`, and makes each type's table.
0x34601 points SkinInfoTable just past the header and counts the size
over 64, unsigned. The unloader zeroes the globals and keeps the
tables.

MakeAccelerationTable walks the speed from 0 in 5 km/h steps up to
500 km/h. Each step gives an acceleration from the torque at the
previous step's RPM, through the final drive and the gear, over the
wheel radius and the mass, with the front and rear mixed by
TorqueSplit. It changes up at CalculateShiftPoints' up points, scaled
by gShiftUpDetune. The samples, with the last zeroed, become a Table
over 0 to the last speed, and the type's 32 entries sample it evenly.
The 404-byte sample buffer is never freed, as in retail.

`bchunkload.c` routes slot 16 to the port, and `main.c` offers it
GLOBALB's top-level chunks at boot in the file's order
(loadGlobalCarInfo). The demo-disc block, which blanks the geometry
names of cars not on the demo, is left out.

The last session's notes had six-gear cars reading an up point that
CalculateShiftPoints never wrote (up[7]) and so taking boot-time stack
residue. That was wrong. The top gear's up point is MaxRPM at
NumGears + 1, so every point the walk reads is this car's. The checker
proves it by running every load under seven stack fills.

### The checks

`carinfo_check` runs the static constructor, the loader, the unloader,
GetAccelerationTable and MakeAccelerationTable as shipped, in
RetailEmu, with only bMalloc stubbed. It covers:

- GLOBALB's own two chunks at each word alignment;
- the 64 records changed type by type (gears 0 to 6 and -1, the split,
  unreachable red lines, narrow engines, three torque curves, odd
  ratios, the mass, the radius, the interpolated up points, and one
  record whose RPM lands exactly on its up point);
- the drivetrain globals varied;
- other chunk ids and skin sizes;
- direct calls over Tables of 0 to 40 entries;
- the constructor again over tables filled with a pattern.

6 scenarios, 114 ops, 2181 lines, 0 differ. Of 78 mutations, 77 are
caught. One is equivalent: `<=` against `<` at the 500 km/h cap, since
no speed the walk reaches equals the cap.

`loadertable_check` treats slot 16 as ported and links the car modules.
Its numbers are unchanged. It has one new mutation, for the slot 16
unloader: of 140, 138 are caught and 2 are equivalent. `sinit_check`
has 18 calls.

On Azahar the boot log has `car data: 2 chunks, 235 skins`, and
`run_azahar_test.ps1` passes.

### Next

8i, CarLoader: each car's geometry and skin, read through
GeometryFilename, so that eModel::Init finds the car's solids. Then 8j.
CONTINUE.md has the lists.

## Session 31, continued (2026-10-02) -- CarLoader (step 8i)

The previous session stopped partway through, with the port, the harness
and the checker written but none of it built. This one ran them, filled
in the mutations, wrote the doc, wired `main.c` and committed.

### The port

`carloader.c` and `carloader.h` are retail's CarLoader, `0x001b0260` to
`0x001b0fd0`. `docs/formats/car-loader.md` has the decode. There are
three records:

- **LoadedCar** (48 bytes) is one geometry file, a body or a dash.
- **LoadedSkin** (20 bytes) is one car in one skin.
- **CarLoader** (32 bytes) is a callback, RoundRobinFlag, InFrontEndFlag,
  LoadingInProgress and the two lists.

Both kinds of entry come from LoadedCarSlotPool, 42 slots of 48 bytes.

**Load** counts one more instance of each entry the ride needs, making
any it lacks: the car's body, its dash if the ride has one, and its skin.
Retail names the files by `CompressedGeometryFilename` (+96) and
`CompressedDashGeometryFilename` (+160); the demo read +64 and +128,
which the last entry's plan had wrong.

**BeginLoading** starts one load:

- while any skin is still to load, the textures, one skin at a time
  under round robin or all of them at once without it;
- after that, the bodies and dashes, one file at a time.

**LoadingDoneCallback** marks what was loading as loaded, drops what
nobody wants and starts the next load. When nothing is left to start, it
clears the kept callback and then calls it.

**Unload** counts down, and **RemoveUnusedCarsAndSkins** unloads and
frees what reaches 0, keeping an entry while it is still loading.
**UnloadEverything** services the resource system until both lists are
empty.

Retail rewrote **GetUsedTextures**. A skin of -1 lists every skin the car
has, through two CarTypeInfo getters that are new in retail and are now
in `cartypeinfo.c`:

- GetNumSkins (`0x001884b8`) is 1 for a cop.
- GetSkinNumber (`0x001884d8`) is the language's livery for a cop: 1 in
  English, 2 otherwise.

The language comes through `gCurrLanguageFn`.

The resource system and TexturePack's file loads are four seams, all
NULL in the game for now. Two port-only choices:

- UnloadEverything returns when the service seam is NULL, where retail
  would spin.
- The slot size is a literal 48, with a layout check on 32-bit builds.

Retail lets a count go below 0 when an entry still loading is unloaded
twice. The port does the same, and the checker covers it for a skin and a
dash.

`main.c` sets `gCurrLanguageFn` to the flow's `currLanguage` and calls
`init_car_loader` after the frontend's bundles, as InitializeEverything
does. `sinit.c` runs the static constructor at `__CTOR_LIST__` [56].

### The checks

`carloader_check` runs everything above as shipped, in RetailEmu, over
GLOBALB's own 64 records. It stubs:

- the slot pool (the lowest free slot, filled with 0xcd);
- the seams, with each load's completion queued;
- two callbacks, one of which calls BeginLoading again from inside the
  completion.

The script's D runs the oldest completion, and so does
ServiceResourceLoading. After each op the transcript holds the loader,
both lists and every back link. The eleven scenarios cover:

- boot;
- shared bodies and dashes;
- the round robin flow;
- UnloadEverything with loads pending;
- round robin off and the front end;
- the count wraps and a 130-instance ride;
- GetUsedTextures' caps;
- patched records (no skins, a cop with none, repeats);
- a second loader, so a port that reaches for the global shows up;
- all 64 cars at once, past the 512-texture cap;
- IsLoaded on missing and unloaded dashes and skins.

The first run segfaulted the harness, because the state print walked
lists the static constructor had not set up yet. Each scenario now starts
with the constructor, and both walks stop at a NULL link.

11 scenarios, 583 ops, 10747 lines, 0 differ. Of 114 mutations, 107 are
caught and 7 are equivalent:

- the cap's `return` against `continue`, since nothing follows it;
- clearing Loaded on an entry that is freed right after, twice;
- dropping the `!Loading` tests in BeginLoading, twice, since nothing is
  loading while LoadingInProgress is clear;
- UnloadEverything's own Remove, which LoadingDoneCallback already runs;
- GetSkinNumber's `%`, which its only caller never needs.

The first pass left five unexplained. Four were holes in the script and
one was a real equivalent:

- no Q on a ride whose dash was missing or not yet loaded;
- no Q on a loaded body under a skin not yet loaded;
- no case where a body is unloaded mid-load while a different body waits.
  The first try used types 7 and 8, which share the McLaren body, so it
  tested nothing.
- the equivalent was UnloadEverything's own Remove.

`sinit_check` has 19 calls. `cartypeinfo_check`, `carinfo_check`,
`carrenderinfo_check` and `loadertable_check` are unchanged. On Azahar
the boot log has `car loader: pool up`, and `run_azahar_test.ps1`
passes.

### Next

8j, the resource system (`0x00199320` .. `0x00199a60`). Every load into a
race goes through it. Then 8k, the track-loading game flow states, and
8l, the coordinator and the race. CONTINUE.md has what the disassembly
showed of each.

## Session 31, continued (2026-10-02) -- the resource system (step 8j)

The previous context ended with the port files written and none of them
built. This one wrote the checker and the harness, brought them to 0
differ, ran the mutations, wired `main.c` and committed.

### The port

`docs/formats/resource-file.md` has the decode. Three pairs of files:

- `resource.c` and `resource.h` are retail's ResourceFile, `0x00199320`
  to `0x00199a6c`, the same code as the demo's.
- `queuedfile.c` and `queuedfile.h` are retail's QueuedFile,
  `0x001ad6d8` to `0x001add40`, also the demo's.
- `bfile.c` and `bfile.h` are port-only: bWare's seven file calls over
  stdio and the SD card's extracted tree.

**LoadResourceFile** counts the load, makes a 216-byte ResourceFile and
puts it at the end of the list. The constructor sizes the file, allocates
a buffer and queues one read of all of it, at priority 5 in one block of
up to 32 MB. A missing or empty file gets no buffer and no read.

**ServiceResourceLoading** services the queue, then takes the first file
not yet loaded. Once its read is in, it expands a `COMP` file into a new
buffer, runs LoadChunks, frees the buffer under FREE_AFTER_LOADING and
runs PostLoadFixup. Then the count drops and the callback runs. One file
per call, in the order they were asked for.

**ServiceQueuedFiles** reads one block at a time. Between blocks the file
waits and the list is sorted by priority again. A missing or short file
fails, and its callback runs with 1. AbortQueuedFile drops a waiting file
at once and flags a reading one, which then goes with no callback.

What the port changes:

- `bfile.c` reads at once and runs the callback at the next
  bServiceFileSystem, so none runs before bReadAsync returns.
- `lzc.c` stands in for LZDecompress. It checks its bounds and writes the
  same bytes for a whole block. `lzc.h` builds on the host now.
- Names are cut at the field (79 and 47 characters), where the image's
  bStrCpy runs over. The disc's are far shorter.
- bRemoveCodeineInventory is left out. Only the debugger's channel heard
  it.
- `bmem.c`'s bMalloc keeps the pool word's alignment through memalign:
  0x40 is 128 bytes, 0x20 64, 0x10 32. ResourceFile asks for 0x40, as
  LoadChunks needs.

Wiring:

- `main.c` runs `init_queued_files` where InitializeEverything's
  InitQueuedFiles does (after LoadConfig, before eMathInit).
- The car loader's three resource seams, trackflow's
  `gFindResourceFileFn`, racecoord's `gFindResourceFileByNameFn` and the
  texture packs' `gServiceQueuedFilesFn` are the real functions now.
- ServiceResourceLoading runs after each frontend frame, before the
  frontend's own bundle callbacks.
- `trackview_free` used to set the two track seams to NULL after
  borrowing them. It now puts back what was there.
- `sinit.c` runs both static constructors: [39] and [52].

The frontend's bundles still come through `main.c`'s addBundle. Nothing
loads through ResourceFile in the game until 8k.

### The checks

`resource_check` runs all of ResourceFile and QueuedFile as shipped, in
RetailEmu, together with LZDecompress, bList::Sort, bStrCpy, bStrNCpy and
bStrCmp. It stubs:

- the file system, over named byte strings, with a set read latency (K);
- a heap of 128-aligned blocks filled with 0xcd, and the slot pool;
- LoadChunks and UnloadChunks, which print their bytes' CRC-32;
- PostLoadFixup, the renderer wait and Joylog;
- four callbacks: one loads another file and one queues another read,
  from inside the service.

The files include the disc's own `GLOBAL\PRERACEANIM.LZC` and
`CARS\PARCELVAN\GEOMETRY.LZC`. The ten scenarios cover:

- boot;
- raw bundles under every flag;
- compressed, stored, empty and fake `COMP` files;
- missing, emptied, vanished and shortened files;
- the load order, duplicates and chained loads;
- blocks, priorities, the aborts and the handle wrap;
- blocks past the end and an abort after a failed open;
- Joylog replay;
- hot-chunk entries, the six-argument load, the renames and the static
  destructors;
- unloads that wait.

The first runs differed in three places. All three were checker bugs:

- a size stub handed back -1 as 0xffffffff, which `bgez` read as
  positive;
- the model passed 32-bit arguments zero-extended, so chunk id 0x80034008
  never matched. They are sign-extended now, as the EE holds them;
- the harness took the `BQ` op for a `B` scenario line.

Ten scenarios, 429 ops and 3250 lines give 0 differ. The mutation pass
breaks the port in 155 ways and catches 153. The two it cannot see are
equivalent: `lif_guard_done` (only ServiceResourceLoading calls the
function, for a file not yet loaded) and `dtor_hnum` (the destructor
frees the record straight after). The first pass missed `srl_zero`
because the read latency hid it, and a `K 1` scenario catches it now.

The other checkers that link `bmem.c` pass unchanged, all 17 at 0 differ. `sinit_check`
has 21 calls. On Azahar it boots, plays the movie, walks the frontend and exits
cleanly, as before.

### Next

8k, the track-loading game flow states. BeginGameFlowLoadingTrackCommon
(`0x00168db8`) loads `GLOBAL\INGAMEA.BUN` (0 bytes on the disc, so it
loads as nothing), services until IsResourceLoadingComplete, then loads
`GLOBAL\INGAMEB.LZC` with flags 9 and Part1 as the callback, and renames
it `GLOBAL\INGAMEB.BUN`. CONTINUE.md has Part1, Part2 and the rest.

## Session 31, continued (2026-10-02) -- the track flow (step 8k)

The previous context ended with the port and the harness written and none
of it built. This one wrote the checker's model on the retail image,
brought it to 0 differ, ran the mutations, updated the docs and
committed.

### The port

`docs/formats/track-flow.md` has the decode. The game flow's four track
states are retail's now, with the callbacks that chain them:

- **Loading the common part.** BeginGameFlowLoadingTrackCommon
  (`0x00168db8`) counts free memory, puts the loading screen up unless
  SkipFE, loads INGAMEA (0 bytes) and waits it out, then queues INGAMEB.
  Part1 (`0x00168ac0`) loads the cars through TheCarLoader, the ones that
  cannot be vertex-damaged first, with traffic at skin -1 and instance 0.
  Part2 (`0x00168928`) copies each further instance's solids
  (`%s_A%d`, `%s_B%d`, `%s_SCUFFS%d`) and moves to LOADING_TRACK_SPECIFIC.
- **Loading the track's part.** The Begin (`0x001690a0`) queues TRACKA and
  TRACKB. Parts 1 to 6 load the speech, the demo replay, the sound
  regions, the HUD textures, PRERACEANIM unless SkipFE, the track's two
  texture files and DRIVTEX, then take the loading screen down and move to
  RACING.
- **LoadHudTextures** (`0x00168c30`) loads the player's gauges and the
  third-person gauge into the HUD pack. ChooseLoadableTextures
  (`0x001ee3c0`) names them; it is in `hudtex.c`, because
  Player::SetHudFeatures calls it too.
- **The End** (`0x00169168`) is the demo's plus SetRenderEggFromEasterEggs
  unless an AI or replay demo.
- **The Begins of unloading** (`0x00169288`, `0x00168ea0`) end with a leak
  check, a green eFlashScreen when free memory differs from before the
  load. The track's also resets the eggs unless a demo, and its language
  call is the speech's unload (`0x0021e280`), not the demo's
  UnloadAllLanguages.

What else changed:

- `gameflow.c` makes its speech load and unload public, as
  `bgf_load_current_speech` and `bgf_unload_current_speech`, and leaves
  the statics bootflow's mutations name alone.
- `bfile.c` opens a missing `.LZC` as its `.BUN`. The card has the
  tracks' TRACKB only expanded, and ResourceFile loads a file with no
  `COMP` header as it is.
- `main.c` wires the four states into `kGameFlowStages` through wrappers
  that set `gTrackFlowGameFlow`. `trackview_free` hides it around its
  Begin of unloading, so the viewer neither changes the flow nor unloads
  the frontend's speech.
- Eight new seams, all NULL on the device. A NULL load seam runs its
  callback at once, so the chain still reaches RACING.
- Part2 builds its names in 48-byte buffers where retail's are 32 and
  run over for a long name. The disc's longest base name is 11 letters.

Nothing enters LOADING_TRACK_COMMON yet: that is 8l.

### The checks

`trackflow_check` runs the fifteen functions as shipped in RetailEmu,
with GetDriverInfo, bSPrintf, bStringHash, bStrCmp, bStrLen, bMemSet and
bMemCpy under them. Every other callee is a stub that prints its
arguments and thirteen globals. The loads queue their callbacks, and the
script's D runs the oldest, so a scenario walks the chain one link at a
time. The cars are GLOBALB.BUN's own records.

22 scenarios, 749 ops, 2333 lines: 0 differ on the first run. The
mutation pass breaks the port in 254 ways and catches 252. The two
equivalents are port-only: both Find loops without the Unload half of
their guard, which the harness never sets apart. `p1c_racing_or_cop`
survived the first pass, because the patched racer was its type's first
instance and Load answered 0 either way; the scenario now loads from a
base of 3.

bootflow_check (48 scenarios, 0 differ) and bscreens_check (17, 0 differ)
pass with `gameflow.c`'s new wrappers. So do sinit_check (21 calls) and
rain_check. The 3DS build links, its relocations check out, and on Azahar it
boots, plays the movie, walks the frontend and exits cleanly, as before.
Nothing on the device enters the new states yet.

### Next

8l, wire the coordinator in and flow into a race. CONTINUE.md lists what
the chain needs on the device before anything can enter
LOADING_TRACK_COMMON: a way in, the HUD pack and the texture streaming,
eDuplicateSolid, the RaceCoordinator and the cameras.

## Session 31, continued (2026-10-02) -- InitFred and TheRaceParameters (step 8l-1)

The user's ask: start 8l-1, InitFred and RaceParameters, and keep going
through every task. The port, its harness and the checker were written
over two contexts. This one closed the last four mutations, reran every
checker, built, tested on Azahar, wrote the docs and committed.

### The port

`docs/formats/frontend-database.md` has the decode.

- **FrontendDatabase** (`fred.c`, `fred.h`) is retail's byte layout, so
  the card's save still loads over it whole. The parts are the
  constructor (`0x001836a0`), InitFred (`0x00183820`) and InitWithDefaults
  (`0x00183830`).
  - InitWithDefaults clears the record and sets each Data* block's
    defaults. It runs MakeChallengeCarsAvailable (`0x00183af8`) and gives
    both players their default car. It resets their settings and sets the
    two names from the language table.
  - HighScoreTable's InitStatsTables (`0x00186708`) numbers the first
    sixteen tracks that are their own high score track. The rest take
    their twin's number, and every time starts at 0x7fffffff.
  - FrontendPlayerInfo's SetCarAvailability, SetDefaultCarType,
    AssignCarOfType and SetCharacterInfo are here too.
- **RaceParameters** (`raceparams.c`, `raceparams.h`). These are its
  InitWithDefaults (`0x001ed5c8`), its static constructor (`0x001ee590`)
  and tGlobalDisplaySettings' defaults (`0x001ee0a0`). `race.h` has the
  788-byte struct, and the per-field globals the earlier slices declared
  are macros on TheRaceParameters now.
- **The characters** (`characterinfo.c`): the loader and unloader of
  chunks `0x34300` and `0x34301`, and the four getters.
- **The smaller files.** `playersettings.c` is cPlayerSettings' reset.
  `configitems.c` has the words LoadConfigItems fills: the SkipFE race and
  the default cars, at their disc values. `edisplay.c` has the display
  offsets.
- **The wiring.**
  - `main.c` calls InitFred after the global chunks, as
    InitializeEverything does after the sound driver. That replaces
    `bsetup_fred_defaults`, which only setup_test still uses.
  - GLOBALB's chunks go through LoaderCharacterInfo, and its track table
    through LoaderTrackGeometry.
  - Three new flow hooks. RaceParameters' defaults run from
    BeginGameFlowLoadingFrontEnd and NewMainMenu, Fred's from the
    language screen, and MakeChallengeCarsAvailable from NewMainMenu.
- **Seams.** IsCarUnlocked is NULL, which answers 0, as a fresh save does.
  The audio options' defaults are the jukebox's, and GetTranslatedString
  is the language table's.

### The checks

`fred_check` runs the image's code in RetailEmu. It covers both static
constructors, InitFred and everything under it, the four player methods,
InitStatsTables, RaceParameters' and the display's defaults, the character
loader, unloader and getters, LoaderTrackGeometry and the display offsets.
IsCarUnlocked, GetTranslatedString and the audio defaults are stubs on
both sides. The data are GLOBALB's own: 64 cars, 66 tracks and ten
characters, changed field by field.

The checker has 9 scenarios, 668 ops and 54344 lines, with 0 differ.
Getting there took four fixes:

- the host's CarTypeInfo is wider than retail's 1376 bytes (it holds a
  pointer), so the harness copies the records into a host array;
- the model sign-extends its arguments, because the EE holds an int in a
  64-bit register and retail tests `skin == -1` there;
- two validator assertions, about twins out of range, needed the
  scenarios changed;
- realtime.c pulls in joylog.c and timer.c.

All 103 mutations are caught. Four of them first survived and needed new
scenarios:

- a dash asked for on a car whose dash geometry is there but not offered;
- both default cars of one type, with the first player's skin -1;
- a fallback string that differs within its first 11 bytes, since
  bStrNCpy keeps only 11;
- New784 set to 1, since the memset already clears it.

Every checker that takes no arguments passes, including bootflow (48
scenarios), player, loadertable, careffects, trackflow and every one that
links `race.c`. `sinit_check` has 23 calls. The 3DS build links and its
relocations check out. On Azahar it boots, plays the movie, walks the
frontend and exits cleanly. The log reads `fred defaults: Player1 (Rick),
Player2 (Wayne), car 37 / 37`. Be The Cop's setup shows the same
defaults as before, read from the real Fred now.

### Next

8l-2, the race start:

- StartSkipFEGame (`0x00184bd8`), StartRace (`0x00184f68`) and
  SetupCarsForRace (`0x00185690`), with the helpers under them;
- the RaceEvent and EventTree calls as seams;
- a switch for SkipFE.

## Session 31, continued (2026-10-02) -- the race start (step 8l-2)

The user's ask: pick 8l-2 up where the last context stopped. The port,
its harness and the checker were written there, and the checker was at
0 differ. This context ran the mutation pass and closed its survivors,
wired the switch into `main.c`, reran every checker, built, tested on
Azahar, wrote the docs and committed.

### The port

`docs/formats/race-start.md` has the decode.

- **StartSkipFEGame** (`0x00184bd8`) fills TheRaceParameters from the
  SkipFE words and jumps into StartRace on the global Fred. As shipped
  that is one car (type 37) on track 12 for 8 laps, with no AI, no
  traffic and no cops.
- **StartRace** (`0x00184f68`) runs the race event's part for GameTypes
  4, 8 and 9, then the boost scales, the AI caps, point to point,
  SetupCarsForRace, the settings and the record times. Last it changes
  the flow: to UNLOADING_FRONTEND from IN_FRONTEND, and to
  LOADING_TRACK_COMMON from any other state.
- **SetupCarsForRace** (`0x00185690`) builds the drivers' table in four
  groups:
  - the players;
  - the AI racers, with up to 500 attempts over GenerateRandomRideInfo
    against the six-model limit and the type and colour rejections;
  - six traffic cars, when there is traffic;
  - the cops, on the cop car nearest the slowest class.

  CalculateStartingPositions then grids everyone who has no slot, by how
  quickly their car pulls away.
- **RaceParameters** gains AddDriverInfo, GetDriverInfoByDriverNumber, the
  restore and the eliminate, the model count and the two location
  getters.
- **Seams.** There are 17, for the race events, the event trees, the demo
  replay and the reward cars. `main.c` sets only the flow's two.
- **The switch** is R held at boot. Retail sets SkipFE only from a
  joylog's config items, and the port reads no joylog. `main.c` reads the
  pad once, after `bgf_init` and before InitFred, which reads SkipFE.
  Then, as retail's main does, it calls `fred_start_skip_fe_game(&Fred)`
  in place of ChangeGameFlow(LOADING_FRONTEND), and it logs the race and
  each driver. `tools/run_azahar_race.ps1` holds R through the boot.
- **Not ported:** BeginGameFlowUnloadingFrontEnd (`0x00168830`). The
  SkipFE path never enters UNLOADING_FRONTEND, so it goes with the
  frontend's way into a race. The doc lists what it calls.

### The checks

`fredrace_check` runs the image's code in RetailEmu: everything above
and what it calls, with InitFred and the loaders setting the scene. The
race events, the trees, the replay, the reward cars and ChangeGameFlow
are stubs on both sides. It has 8 scenarios, 2527 ops and 50503 lines,
with 0 differ.

The first mutation pass caught 200 of 217; 17 survived. `s_holes` takes
in what the other scenarios left alone:

- the three game-type tests called alone. StartRace tests GameType 2
  beside IsChallengeGame, so through it a mutant that lets 2 in hides;
- a grid of exactly nine;
- one cop at OpponentStrength 2, the only strength whose two skill
  tables differ;
- car 63 (the table's last) given a weight in the draw, and a car with a
  weight but no skins;
- an invalid track that keeps a high score index;
- a torque curve that peaks at its last point;
- the second database's totals moved (the `hs` op takes a salt now), so
  a lookup in the wrong table shows;
- a NumPlayerCars below 0, which SetupCarsForRace puts back to 0, with
  no driver before the cops;
- car 34, the class 2 cop, with no geometry. Cars 31 and 33 then tie,
  one class away;
- one AI racer over MaximumNumAICars;
- a traffic car and a rank-1 knockout in the model count;
- a driver left past the table's end.

`cp_pos1` is equivalent. The driver being placed stays in the table
with slot 0 until it is given one, so slot 0 always counts as held.

A rerun of the 17 caught 16, so of 217 mutations 216 are caught and 1 is
equivalent, with 0 unexplained.

Every checker in the chain passes: 91 commands, 0 failed, among them
fredrace_check (8 scenarios, 2527 ops, 50503 lines, 0 differ) and
sinit_check's 23 calls. The 3DS build links, and check_3dsx reports
its relocations OK.

On Azahar, the switch at first never fired. The script posted R once,
when the window appeared, and Azahar drops a press made before its
render window takes the keyboard. Now it posts R every 150 ms until the
log shows InitFred has run. The log then reads `SkipFE: R held at boot`
and the race start: track 12, 8 laps, one driver, car 37 skin 1 on grid
1. The flow goes from NONE to LOADING_TRACK_COMMON and runs its Begin.
It then stays on LOADING at 60 fps, with no fault. By the code, that is
Part1's car load waiting on the NULL LoadTexturesFromFile, though
nothing logs the step. `run_azahar_test.ps1` passes: the boot without R
walks the frontend as before.

### Next

8l-3, the race:

- the car's textures (LoadTexturesFromFile), where Part1 stops now;
- `main.c` building the coordinator and running MainLoop's race half;
- the items under 8l-3 in CONTINUE.md.

## Session 31, continued (2026-10-02) -- texture streaming (step 8l-3a)

The first slice of 8l-3. Part1 of LOADING_TRACK_COMMON hands the car's
skins to CarLoader, which asks pCarTexturePack for them through
LoadTexturesFromFile. That seam was NULL, so the callback never came and
the flow stopped on LOADING. `docs/formats/texture-streaming.md` has the
write-up.

- **`texturestream.{c,h}`** is TexturePack's streaming half, retail's
  `0x001ac608` to `0x001ad048`, with the read's bridge (`0x001ad608`):
  - LoadTextureTableFromFile reads a pack file's first 128 KB, copies the
    table out and keeps where the pixels start;
  - Find, FindNotYetLoadedNeighbour, Add, Remove and DeleteLoadedTextureData
    keep the list of ranges, each with its users, merging a range into a
    neighbour not yet read within 1 KB;
  - Load and UnloadTextureFromFile, Load and UnloadTexturesFromFile;
  - ServiceLoadingTextures reads one range at a time through QueuedFile,
    and ReadCallback assigns it, runs eFixUpTables and services again;
  - UnloadAllTexturesFromFile and GetLoadedSize.
- **Retail's oddities, kept**:
  - an empty range sets the waiting count one up, not one down;
  - a callback's empty range can be grown into a real one by a range at
    most 1 KB into the blob, or merged away as a second neighbour, and its
    callback is lost;
  - a callback is a barrier to the sort.
- **`texturepack.c`**: `loadedtexturedata_destruct` is no longer static,
  and the record's callback takes an `intptr_t`. **`bfile.c`** gains
  bRead.
- **`main.c`** makes LoadGlobalChunks' three packs:
  - DynTextures over `GLOBAL\DYNTEX.BIN`, then LOADING asked for and
    waited on, before `bgf_load_global_chunks`;
  - HudTextures over `GLOBAL\HUDTEX.BIN` and CarTextures over
    `CARS\TEXTURES.BIN` after it, and the second wait;
  - CarLoader's two seams and trackflow's UnloadAllTexturesFromFile.

  MainLoop's ServiceResourceLoading runs the reads.

### The heap

With the car's textures streaming, the flow went on to
LOADING_TRACK_SPECIFIC, and Azahar closed a moment later with nothing in
its log but a clean shutdown. The user saw the same: the loading screen,
then an exit. It was an abort. bMalloc cannot fail in the image, so the
port's prints the size and name to stderr and aborts, and on the device
stderr went nowhere. `main.c` now sends stderr to
`sdmc:/nfshp2_stderr.txt`, which read:

```
bMalloc: 8984588 bytes for TRACKS\TRACKB12.LZC
```

Each state's Begin now logs the heap. At LOADING_TRACK_SPECIFIC 22.8 MB
of the 28 MB malloc heap was in use, and the track's files want about
15 MB more (TRACKB12 8.6 MB, TEX12LOCATION 4.8 MB, the rest small). The
linear heap had 70 MB free of 76. So `heapcfg.c`'s HEAP_WANT is 48 MB
now. A small grant still gives the malloc heap no more than half.

### The checks

`texturestream_check` runs the image's code in RetailEmu. That covers all
of the above, plus TexturePack's constructor and destructor,
AttachTextureTable, Assign and UnAssignTextureData, GetTexture,
bList::Sort, QueuedFile and ServiceQueuedFiles. The file system, the heap
and the slot pool are stubs on both sides. The files are the disc's three
packs and packs the checker builds. 9 scenarios, 380 ops and 7353 lines
give 0 differ.

Of its 142 mutations, the first full pass caught 136. Two of the six it
missed did not test what they meant to: a poked range sat inside a
loaded one, and a marker's callback run after its free cannot be told
from one run before, since a marker has no block. The other four got
cases of their own: a palette larger than its image, a range below a
callback's 0, two ranges that start together, and a range grown into a
callback's. The second pass caught all 142, none equivalent. A hung
mutant is killed after 60 s now, not 300.

Every checker in the chain passes: 92 commands, 0 failed. The 3DS build
links, and check_3dsx reports its relocations OK.

On Azahar, R held at boot logs the three packs (`DynTextures 19,
HudTextures 89, CarTextures 783 textures`), and the flow runs
LOADING_TRACK_COMMON and LOADING_TRACK_SPECIFIC and enters RACING:

```
flow begin LOADING_TRACK_COMMON (heap: 20213 KB used, 28938 KB free; linear 70772 KB free)
flow want LOADING_TRACK_SPECIFIC
flow begin LOADING_TRACK_SPECIFIC (heap: 22772 KB used, 26379 KB free; linear 70644 KB free)
flow want RACING
flow end LOADING_TRACK_SPECIFIC
flow state RACING
```

It runs at 60 fps on the LOADING screen, since nothing draws the race
yet. `run_azahar_test.ps1` passes: the boot without R walks the frontend
as before.

### Next

8l-3b: the coordinator and MainLoop's race half. CONTINUE.md lists
MainLoop's calls in order. To draw the track, trackview needs a way to
take the bundle the resource system already loaded, where today it reads
and loads its own.

## Session 31, continued (2026-10-02) -- the race (step 8l-3b)

8l-3b went in as three commits. The first two have their own messages:
`3853ceb` runs the race from MainLoop's race half, and `4811ca7` draws
the cars. This entry is the third, the cars' lighting.
`docs/formats/light.md` has the write-up.

- **`elight.{c,h}`** is the database half of `eLight.obj`
  (`0x00114f38` to `0x00117460`) and `vAABBTree`'s leaf query:
  - LoaderTable slot 5: the light packs, the flares and GLOBALB's
    320-byte materials, with BuildDmaData's sixteen words;
  - QueryLightDatabase, with retail's arithmetic for the blended
    ambients;
  - elSetupLightContext: the sun and the two nearest point lights in the
    model's space, the ambient, the eye and EnvMapMatrix.
  `eLightFlare` moved from `carrenderinfo.h` to `elight.h`.
- **`geolit.v.pica`** is the VU1 lighter (`0x1620`, `0x1998`): the
  reflection, the diffuse and the specular by the fast power, CBVMix, the
  gloss map, and the environment pass's fresnel.
- **`eenvmap.{c,h}`** is eEnvMap (`eInitEnvMap` `0x00117508`,
  `UpdateCameras` `0x001175c8`): views 4..9, retail's axes, frustum and
  schedule, and the cull's exclude flags.
- **`georender.c`** draws a lit batch and its environment pass.
  **`trackview.c`**'s `lighting_for` fills the batch's inputs, and
  `trackview_draw_envmap` draws the six views.

### The cube map

Retail folds its six views into a sphere map. The PICA reads a cube map
by the reflection, so the port draws each view straight into a face.
Three things had to be found on the way:

- `C3D_RenderTargetCreateFromTex` checks that the texture's data is in
  VRAM. A cube's `data` is its `C3D_TexCube` pointer, so the check fails
  for every cube, and the first boot logged "no room for the environment
  map". Each face's target is now made over a 2D `C3D_Tex` whose data is
  that face's image, with the depth buffer in the other VRAM bank.
- The PICA picks a face and its s and t by OpenGL's rule. Azahar's
  `ConvertCubeCoord` (`renderer_software/sw_clipper.cpp`) has it, and a
  marker drawn into each face confirmed it.
- A render target puts NDC +y at t = 0, where OpenGL's framebuffer has it
  at 1. So a face filled the way the rule wants is a mirror image of any
  camera's view. Rather than flip every triangle's winding, the map's
  space is mirrored: `geolit` reads the cube at `(-r.x, r.y, r.z)`, and
  each face's camera looks along its axis with its up against the face's
  t (`kCubeUp`).

The screen quads' ring now rewinds at the start of the frame, not at the
sun. With the env views drawing first, a rewind at the sun could reuse
quads the frame had already queued.

### Checks

`loadertable_check` covers slot 5: the demo image gives 178 ops and 1617
lines, and the retail image 37375 ops and 49175 lines, with 0 differ.
Nothing else in the slice has a harness.

On Azahar, R held at boot runs into RACING, and with the throttle held
the Opel drives off the grid at 58-60 fps. The track draws about 310 of
its 410 solids, 31,000 triangles. The car is lit by the sun with the
sky in its reflections: the rear window is blue, and the deck has a
sheen. In the env views the road under the car is near-clipped, and
below the horizon the sky dome's lower half shows. That is what
retail's near plane of 0.5 and its exclude flags give.

### Next

8l is done, and step 9, one car driving the track, is reached. Next is
8m, the HUD, on the split decided on 2026-09-21. Then come the car's
sounds and the racer AI. CONTINUE.md has the list.

## Session 31, continued (2026-10-03) -- the Flailer runtime (step 8m-1)

The HUD, the pause menus and the frontend change their screens through
retail's Flailer runtime: they find a screen by hash, find an object on it
by hash, then set its string, colour, alpha, position, scale or texture.
8m-1 ports that runtime, so the later HUD slices can call it as retail
does. `docs/formats/flailer-runtime.md` has the write-up.

- **`flailer.{c,h}`** hold:
  - LoaderFlailerChunk's linking, as `flailer_add_project`.
  - FindFlailerScreen with its move-to-front, FindFlailerObject and
    FindFlailerObjectByGroup.
  - The object, text and bitmap methods (`0x00140518` to `0x00141488`).
  - The Flailer* wrappers (`0x00143e70` to `0x00145690`), including the
    group walks and both MakeVerticalLines.

  As on the PS2, an object is its chunk's payload. The setters write into
  the bytes `bui.c` already holds, so `uirender.c` draws whatever the game
  last set. The structs carry retail's layout and a compile-time check on
  every offset the code uses.
- **The seams.** Text sizes come from the font and bitmap sizes from the
  texture, both of which the renderer owns, so `main.c` binds three seams
  to `uirender.c`:
  - `uirender_text_scaled_width` is GetScaledWidth itself.
  - `uirender_object_height` answers the text's height.
  - `uirender_texture_size` is GetTextureInfo's Width and Height, an
    override's if the texture has one.
- **`main.c`** registers each bundle that has a Flailer chunk as a
  project when it loads it: GLOBALB, then FRONTB, then INGAMEB. It binds
  the race's existing seams to the runtime: the Player's HUD lookups, the
  countdown's and the NIS overlay's. `bui.c` keeps each screen chunk's
  payload (`BUIScreen::def`), which is what FindFlailerScreen returns.

Retail's oddities are kept and listed in the doc, among them:

- GetCenter adds half the width to both coordinates.
- FlailerSetCenterX centres on the height.
- The text's ScaleAboutCenter moves Y by `ScaleX` when the text is
  right-aligned.
- The bitmap's SetAlpha stamps dirty even when nothing changes.

Four departures are also listed:

- FlailerPrintf's buffers.
- SetString's copy.
- FlailerGetCenter on a missing object returns 0, where the PS2 returns
  stack garbage.
- GetTextureInfo's cache: the port asks the renderer every time.

Three screens are in both FRONTB and INGAMEB. Retail unloads FRONTB for
the race, but the port keeps it. The Player's constructor finds a screen
on INGAMEB while the race loads, which moves INGAMEB ahead of FRONTB, so
the shared screens still resolve to INGAMEB's copies during a race.

### The checks

`tools/flailer_check.py` runs retail's own LoaderFlailerChunk on
GLOBALB, FRONTB and INGAMEB in RetailEmu, with INGAMEB loaded twice so
that every INGAMEB screen is in two projects. It then runs retail's
lookups, methods and wrappers there. `tools/src/flailer_test.c` runs
`flailer.c` over `bui.c` on the same files. The size seams are stubbed by
the same formula on both sides. The checker compares:

- each call's result;
- the bytes of the object it touched;
- the order of the projects and of their screens;
- periodic CRCs of every screen and object.

The result: 54,104 ops, 120,233 lines, 0 differ. Of 110 mutations, 106
are caught and 4 are equivalent by construction (the doc gives the
reasons).

On Azahar, R held at boot logs `flailer: 3 projects, 86 screens` and runs
into RACING as before. The HUD still draws nothing, because nothing calls
SetHudFeatures or RenderHud yet; those are 8m-2 and 8m-3.

Azahar's App counter reads 24-29 FPS with the throttle held. The last run
before this slice (the lighting) read 20-22, and the runs before the cars
were lit read about 30, so this slice did not slow anything down. The world still steps 60 times a second of game time. The
earlier entries give "58-60 fps", which does not match the App counter; it
was likely read from the world's step count. Drawing at about 25 FPS is a
cost to look at, and the six environment views drawn each frame are the
first suspect.

### Next

8m-2: DetermineHudFeatures (`0x00178da0`), its helper (`0x001795f8`) and
SetHudFeatures (`0x001796b0`), which picks the HUD's objects and their
layout from the car's gauge data. CONTINUE.md has the rest of 8m.

## Session 31, continued (2026-10-03) -- the HUD's features (step 8m-2)

Each frame, UpdateHud asks Player::DetermineHudFeatures which parts of the
HUD the player should see. It hands the answer to SetHudFeatures, which
shows or hides the Flailer objects behind each bit that changed and finds
the ones UpdateHud writes into. 8m-2 ports both, so the HUD screen comes up
in a race. `docs/formats/hud-features.md` has the write-up, with a name for
each bit of the word.

- **`playerhud.{c,h}`** hold:
  - DetermineHudFeatures (`0x00178da0`) and its gauge helper
    (`0x001795f8`).
  - SetHudFeatures (`0x001796b0`): one block per bit, among them the
    gauges placed from the car's `HudInfo`, the lap block and its labels,
    the live split, the track map, the three pursuit meters, the radar,
    Be The Cop and the cinema bars.
  - SetTrackMapMode (`0x00178c90`) and its three mode tables.
  - UpdateHud's head (`0x0017ecf0` to `0x0017ed34`): SetHudFeatures when
    the answer differs from `CurrentHudFeatures`. `main.c` binds it to
    `gPlayerUpdateHudFn`, so UpdateNonGameState runs it each frame. The
    rest of UpdateHud is 8m-3.
- Under them: IsNisPlaying, ShouldShowBustedText and the CopManager's
  ShouldDisplayBustedText (`copmanager.c`), and RaceParameters::IsFreeRun
  (`raceparams.c`).
- `player.h` names the live split's fields (1300 to 1364) and retail's
  lead title and time (1396 and 1400), which were padding.
  `player_check` follows.
- The callees not ported are seams, skipped when NULL:
  SetRearViewMirrorCameraMover, InitializeFlailerTachometer, TrackMap's
  constructor and destructor, FillInRaceOverMessages, RaceFinishedSpeech,
  HudStartWrongWay, NISOverlayManager::SetVisible, ClearHudAnimations and
  the egg test. None is bound yet.
- `tools/ghidra_scripts/DecompileByAddr.java` decompiles the stripped
  retail ELF by address, after naming what `out/retail_syms.txt` places.
  `RetailSetGp.java` is the import's pre-script and sets gp.

Retail's oddities are kept and listed in the doc, among them:

- Preference bit 0x100 controls the lap counter, the best lap and the
  choice of pursuit meter.
- HudStartWrongWay runs once per object in the wrong-way group.
- The lap label's point-to-point test repeats the time-trial test with the
  race type reversed.
- `or_format` writes `FormatOptions` with no dirty flag in three blocks.
- The nZoneCurrent 1-or-2 check is dead, since an earlier check returns
  for any zone.

### The checks

`tools/hudfeatures_check.py` runs retail's DetermineHudFeatures,
SetHudFeatures and SetTrackMapMode in RetailEmu, on INGAMEB's Flailer
chunk loaded by retail's LoaderFlailerChunk. Under them run retail's
IsNisPlaying, ShouldShowBustedText, IsFreeRun, bSPrintf, bStringHash and
the Flailer runtime. The other callees are stubs that print their
arguments. `tools/src/hudfeatures_test.c` runs `playerhud.c` over
`flailer.c`, `bui.c`, `bchunk.c`, `copmanager.c` and `raceparams.c` on
the same bundle. After each op it compares Determine's answer, the stubs'
calls, each Player's HUD fields, the views' `LetterBox`, the display
settings and every Flailer object's bytes. After each dump both sides
clear every object's `DirtyFlag`, as a drawn frame would.

`hudfeatures_check`: 1298 ops, 10373 lines, 0 differ. The mutation pass
makes 170 mutations: 164 are caught and 6 are equivalent, with 0
unexplained. The doc gives each equivalent's reason. Six survivors of the
first pass were gaps in the script, now caught:

- three dirty-flag mutants, caught since the checker clears `DirtyFlag`
  after each dump;
- a circuit race with a time-trial time;
- a pursuit meter over an earlier `PrevPursuitLevel`;
- IsFreeRun's Be A Cop test.

`player_check`: 8 scenarios, 3659 ops, 515143 lines, 0 differ.

Writing the two-player script found one bug: the port showed the whole
bars screen in a two-player race, where retail hides it and shows the
player's half.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65`), the race runs as before
with no crash, and the log's screens line lists `f1f1f8e5`, the
one-player HUD. Shots are in `out/azahar_8m2`. These parts show the
bundle's own placeholder texts (Lap 99/99, 00:00:00, 299), since nothing
writes them until RenderHud (8m-3):

- the lap block;
- the third-person gauge;
- the split time.

These show too, and are 8m-3's:

- the debug texts (C: xxxFPS, G: xxxFPS, xxxx yyyy zzzz, 11234 km), which
  DisplayDebugInfo writes;
- the tracker's seven triangles, which DrawTracker places.

The App counter reads 20 FPS.

### Next

8m-3: the rest of UpdateHud and RenderHud (`0x0017f040`). CONTINUE.md
lists RenderHud's callees.

## Session 31, continued (2026-10-03) -- RenderHud (step 8m-3)

UpdateHud runs once a frame for each player. After its head (8m-2) it
fades the score, scores the start bonus, and calls RenderHud
(`0x0017f040`, 6812 bytes, with no symbol). RenderHud writes the frame's
numbers into the HUD's Flailer objects. 8m-3 ports both, so the HUD shows
the race. `docs/formats/hud-render.md` has the write-up.

- **`hudrender.{c,h}`** hold:
  - UpdateHud after its head: HudDoAnimations' seam, the score's fade
    (`0x0017d7c8`), the start bonus and UpdateScoring's seam.
  - RenderHud's sections:
    - the speedo, the tach, the shift light and the gear;
    - the lead, the lap time, the splits and the live split;
    - the lap counter, the race position and the tyres;
    - Be The Cop's panel and the trackers.
  - GetCurrentBestLapRecord, ConvertScoreString, DisplayDebugInfo,
    GetLetterForGear and TriggerTimerWarningSound.
- **`racesplit.{c,h}`** hold the RacingCar lap accessors
  (GetFinishReasonId and the four lap stamps) and Race::CalculateSplitTime
  (`0x001487e8`).
- **`bprintf.{c,h}`** is bWare's bSPrintf and bVSPrintf (`0x00251398`,
  `0x00251440`). Its rules are not the C library's:
  - `%f` with no precision has 3 places, and halves round away from 0.
  - `%e` and `%g` have 3 exponent digits, and `%g` is `%e`.
  - Unknown letters print themselves, and `%p` is `%.8X`.

  `flailer.c`'s FlailerPrintf now goes through it.
- **Under them:**
  - `timer.c`: Timer::PrintToString (`0x001a3b98`), with its
    language-dependent templates (`0x001a3838`), and GetHoursMinsSeconds
    (`0x001a3b28`).
  - Retail's Timer::SetTime (`0x00136dd0`) rounds, where the demo's
    truncated. A sixtieth of a second is now 67 ticks, as in retail.
    `realtime_check` now runs retail's clocks.
  - `copmanager.c`: IsBeingPursued, GetPursuitLevelForHUD and
    GetNumTickets.
  - `raceparams.c`: NumEliminated (`0x001edcd0`).
  - `carinfo.c`: InitCarInfo (`0x00188d08`) and FindCarLanguageInfo
    (`0x00187e80`), with retail's CarLanguageInfo table (`0x0030d578`).
    `main.c` runs InitCarInfo after the global chunks load, so each car
    type's `pCarSpecs` points at its names.
- **Retail layouts fixed:**
  - Retail's CarSpecs row has a seventh word, the top speed in km/h, at
    12. The port's names after it were one slot out, so the leaderboard's
    ShortName read the full name.
  - PlayerSettings has a new byte at 5. SplitTimeType and PreferredGender
    move to 6 and 7.
- `main.c` binds UpdateHud to `gPlayerUpdateHudFn` and
  GetTranslatedString to `fredTranslate`.
- **Still seams for 8m-4:**
  - HudDoAnimations, UpdateScoring and StartScore;
  - HudStartSpeedAnimation and HudStartGrowAnimation;
  - UpdatePursuitMeter and UpdateRadarDetector;
  - DrawTracker and NISOverlayManager::Update.

  InitializeFlailerTachometer and RenderFlailerTachometer also move to
  8m-4.

Retail reads past its arrays and through unchecked pointers in some
places. The port bounds or checks each one, and the doc lists them:

- the helicopter and ticket lights;
- the lead's other player;
- the trackers' World;
- the accessors' signed index;
- the finish-reason table;
- the cop arrays by CarIndex.

### The checks

`tools/hudrender_check.py` runs retail's UpdateHud, RenderHud and
GetCurrentBestLapRecord in RetailEmu, over INGAMEB's Flailer chunk. Under
them run retail's:

- DetermineHudFeatures and SetHudFeatures;
- the Flailer runtime;
- PrintToString, CalculateSplitTime and the accessors;
- NumEliminated, bSPrintf and bVSPrintf.

The 8m-4 seams and the World's lookups are stubs that print their
arguments. `tools/src/hudrender_test.c` runs the port on the same bundle.
After each op the checker compares:

- the stubs' calls;
- each Player's HUD fields;
- every Flailer object's bytes.

`hudrender_check`: 1278 ops, 7620 lines, 0 differ. Its mutation pass
makes 156 mutations: 152 are caught and 4 are equivalent. The doc gives
each equivalent's reason:

- the lead's fixed-width bit, which SetHudFeatures already set;
- two tests on the big position's grow, whose values are always equal;
- the port's bound on the boundary index.

The first pass left 12 more survivors, and all were gaps in the script.
Eight were the splits, whose comparison was printed on too few frames.
The others were the score's fade at its unset stamp and at its 4 s hold,
the shift light exactly at the red line, and the lead with no lap
counter. The script now covers each one.

`tools/bprintf_check.py` runs retail's bSPrintf against `b_snprintf`,
with a guard behind the port's buffer. It covers:

- 28 `%f` forms over about 170 values, with ties at every place;
- every integer, string and pointer conversion with each flag;
- `*` widths and precisions, and the size letters;
- the HUD's own formats;
- buffers of 0 to 17 bytes.

`bprintf_check`: 5879 ops, 11758 lines, 0 differ. Its mutation pass makes
36 mutations: 35 are caught, and 1 is equivalent (`h` on `%c`, which
every C library ignores).

The checkers this step touched, all 0 differ:

| Checker | Result | Mutations |
|---|---|---|
| carinfo | 7 scenarios, 198 ops, 2602 lines | 85 caught, 2 equivalent |
| cartypeinfo | 4 scenarios, 200 lines | 45 of 45 caught |
| realtime | 20 scenarios, 1044 ops, 3470 lines | |
| fredrace | 8 scenarios, 2527 ops, 50503 lines | |
| hudfeatures | 1298 ops, 10373 lines | |
| flailer | 54104 ops, 120233 lines | |
| player | 8 scenarios, 3659 ops, 515143 lines | |

Writing the checkers found two bugs in the port:

- It printed with the C library, whose `%f` gives six places and rounds
  halves to even. That is why `bprintf.c` exists.
- The CarSpecs slot, above.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65 -OutDir out/azahar_8m3`)
the race runs with no crash:

- The top screen's HUD shows Lap 1/8 and the record "--:--.--".
- The lap time counts: 0.74 at 18.6 s, 4.21 at 28.8 s, 7.67 at 39.1 s.
- The speed and gear rise: 13, 80 and 112, in gears 1, 2 and 3.
- The leaderboard shows "1 Player1".
- The debug strings and the trackers' triangles are hidden.
- The bottom screen still shows the frontend's help. That is 8m-5.

Speed is 100% and the App counter reads 20 FPS. The lap clock gains
3.46 s in 10.2 s, a third of real time, so the world steps once for each
drawn frame. CONTINUE.md's frame-rate item now says so.

`tools/ghidra_headless.sh` is new. It launches Ghidra's headless analyzer
from Git Bash through `java` and LaunchSupport, with no cmd.

### Next

8m-4 is in three parts. 8m-4a is the animations, 8m-4b the scoring and
8m-4c the pursuit meter, the radar, the trackers and the NIS overlay.
CONTINUE.md lists each with its addresses. 8m-5, the two-screen split,
now has the user's layout (2026-10-03):

- top screen: the speedometer where retail has it, the race position at
  the bottom left, and the radar top middle;
- bottom screen: the lap records and the other extra information, the
  minimap, and Be The Cop's panel (the helicopter, roadblock and
  spike-strip calls, the tickets and the damage).

## Session 31, continued (2026-10-03) -- the HUD's animations (step 8m-4a)

The HUD's moving parts are HudAnimators. Each one moves one Flailer text
or bitmap from a start to an end over a time: its top left, its scale, its
alpha and a text's colour. The Player holds twenty, each made on demand.
8m-4a ports HudAnimator and the Player functions that start, run and clear
them. `docs/formats/hud-anim.md` has the write-up.

### The port

- **`hudanim.{c,h}`** hold HudAnimator, 288 bytes from `bMalloc(288, 16)`:
  - the constructor and destructor (`0x0023b0f8`, `0x0023b168`);
  - its three StartAnimation: the scored text, the text and the bitmap
    (`0x0023b1e0`, `0x0023b498`, `0x0023b5e0`);
  - both DoAnimation (`0x0023b788`, `0x0023bb58`) and FinishAnimation
    (`0x0023bf60`).
- **The Player's side**, in the same file:
  - ClearHudAnimations (`0x0017c7c8`) and HudStartWrongWay
    (`0x0017c888`);
  - HudStartGrowAnimation (`0x0017cb18`) and HudStartSpeedAnimation
    (`0x0017cd30`);
  - the text's and the bitmap's HudStartAnimation (`0x0017cfb8`,
    `0x0017d130`);
  - HudDoAnimations (`0x0017e038`) and AddToTotalScore (`0x0017e350`).
- **`main.c`** binds six seams: HudDoAnimations, HudStartSpeedAnimation,
  HudStartGrowAnimation, HudStartWrongWay, ClearHudAnimations and the
  animator's delete, which the Player's destructor calls.
- **Left out:** nothing in retail calls HudStartBlink, StartBlink, the
  blink's DoAnimation, SetVisibility or StartMusicTitleAnimation, and no
  data holds their addresses.
- **Headers:**
  - `rcpost.h` drops its three-field TransientStatsElement for
    `fred.h`'s 100-byte one, so the two can be included together;
    `main.c` now includes both. The old copy spelled the second field
    `UniqueDriverNumber`. The .mdebug (type#692) and `fred.h` have
    `UniqueDriveNumber`, so `rcstates_test.c` now uses that.
  - `race.h` cites IsReplayDemoMode at retail's `0x001369a8`, not the
    demo's `0x00134b00`.

What retail does that a reader would not guess:

- The time each Player function is handed is never read. Every start
  reads WorldTimer itself, and so does DoAnimation(Timer). Only the scored
  DoAnimation reads the Timer it is handed.
- Nothing clamps `t` below 0 or the alpha at all. SetAlpha keeps the low
  byte, so an alpha of 300 shows as 44.
- A bitmap start leaves a running animator alone. Calling HudStartWrongWay
  again while WRONG WAY runs does nothing.
- An animator with both a text and a bitmap moves the text.
- A scored text's late frame carries its lateness into the next phase.

The port differs in two places, and neither shows in the checker:

- It skips the NULL text or bitmap that retail writes through, and the
  NULL `b` the grow functions read.
- It bounds the scored text's string to 63 characters.

### The checks

`tools/hudanim_check.py` runs each retail function above in RetailEmu,
over INGAMEB's Flailer chunk. Under them run retail's ConvertScoreString,
bSPrintf, bStrToLong, bStrNCmp, IsFreeRun and the Flailer runtime.
`tools/src/hudanim_test.c` runs the port on the same bundle.

The stubbed bMalloc fills each new animator with a pattern by offset, so a
field that nothing writes shows the same on both sides. After each op the
checker compares:

- each Player's twenty slots: the allocation number and the 288 bytes,
  with the two objects by name;
- `TotalScore`;
- every Flailer object's bytes;
- the scored DoAnimation's answer.

`hudanim_check`: 473 ops, 2829 lines, 0 differ. Its mutation pass makes
292 mutations: 290 are caught and 2 are equivalent:

- `lerp-w-dropped`: the colour's fourth component is never used;
- `da-inactive-run`: every animator call checks `bActive` first.

The first pass left ten survivors. Two were the equivalents above. The
other eight were gaps in the script, mostly FinishAnimation's bitmap path
(`fin-bitmap-*`), which no case had reached. The script now finishes
bitmaps in the unused slots 6 and 7, runs DoAnimation on a finished
text, and runs slot 12's scored text through its third phase.

The checkers this step touched, all 0 differ:

| Checker | Result | Why it ran |
|---|---|---|
| hudrender | 1278 ops, 7620 lines | calls the seams 8m-4a fills |
| hudfeatures | 1298 ops, 10373 lines | includes `rcpost.h` |
| rcstates | 600 scenarios, 29584 ops, 64046 lines | the TransientStatsElement change |
| flailer | 54104 ops, 120233 lines | under the animations |
| player | 8 scenarios, 3659 ops, 515143 lines | the destructor's delete seam |

The whole chain passes: 93 checkers with `hudanim_check` added, and the
four table generators, 0 of 97 failed, in 23 minutes. `rcstates_check` failed to compile before the
field-name fix above.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65`, shots in
`out/azahar_8m4a` and `out/azahar_8m4a_2`) the race runs with no crash:

- At 96 km/h the speedo shows only its digits.
- At 102 a larger, faded "100" sits behind them. That is the speed's grow,
  which RenderHud starts on passing a multiple of 50 from 100 to 400.
- By 115 the grow has faded out, a second after it started.
- The lap time, the lap counter and the leaderboard show as in 8m-3.

The first run read 57% speed and 11 FPS, with a mutation pass running on
the same machine. The second, on an idle machine, read 100% and 20 FPS,
as in 8m-3. CONTINUE.md's frame-rate item now warns about readings taken
under load.

Housekeeping:

- The first mutation pass was cut off when the last session ended, and it
  left `hudanim.c` holding `da-17-skipped`, with its
  `.mutate-backup` beside it. The original was put back from the backup
  and checked with `cmp` before the pass was rerun.
- HANDOFF's 8m-3 entry had `out\azahar_8m3` with `\a` turned into a BEL
  byte. It now reads `out/azahar_8m3`, and no other doc has a control
  byte.
- `build_cia.ps1` sets `$ErrorActionPreference = "Stop"`. If its output
  is redirected inside PowerShell (`2>$null`, `2>&1`), the linker's
  "missing .note.GNU-stack" warning becomes a terminating error. Run it
  with no redirection.

### Next

8m-4b, the scoring: StartScoreAnimation (`0x0017d370`), GetFinishBonus
(`0x0017e2d0`), the three StartScore (`0x0017e3b0`, `0x0017e558`,
`0x0017e6e8`) and UpdateScoring (`0x0017e820`). They start slots 10 to
13's scored texts, which 8m-4a already runs. PlayScoreSound
(`0x00175100`) goes with them. Then 8m-4c, the pursuit meter, the radar, the trackers and the NIS
overlay, and 8m-5, the two-screen split.

## Session 31, continued (2026-10-03) -- the race's bonus scores (step 8m-4b)

A bonus score is a line of ScoreInfoTable: a title such as CLEAN LAP, its
language id and its points as text. When one is earned, its title and
points fly in on the HUD's two event texts, and HudDoAnimations adds the
points to `TotalScore` when the points text finishes. 8m-4b ports what
earns the scores the HUD hands out itself, the sound and the animation.
`docs/formats/hud-score.md` has the write-up.

### The port

- **`hudscore.{c,h}`** hold:
  - PlayScoreSound (`0x00175100`): "ScorePoints" for BEAT THE COPS, TOOK
    1ST PLACE, TOP SPEED and QUOTA FILLED, not in a replay or after the
    race;
  - Player::StartScoreAnimation (`0x0017d370`): slots 10 and 11's scored
    texts, halved and moved for two players;
  - GetFinishBonus (`0x0017e2d0`) and both StartScore with an eScoring
    (`0x0017e3b0`, `0x0017e558`);
  - UpdateScoring (`0x0017e820`): the blink, a lap's or a segment's end,
    the top speed, a knock, the air and a place taken.
- **`main.c`** binds UpdateHud's two seams, `gUpdateScoringFn` and
  `gStartScoreFn`.
- **Left out:** StartScore() (`0x0017e6e8`). Nothing calls it and no data
  holds its address.
- `hudscore.h` names eScoring from the table's English titles, since
  retail keeps no names for it.

What retail does that a reader would not guess:

- StartScore(e, value) never reads `value`. Its callers print the points
  into `strEventScore` first.
- A knock's dot of the impulse against the car's up is added as
  `(x*x + y*y) + z*z`, the VU's order, and the order shows: 1e8 - 1e8 +
  0.5 is 0.5 one way and 0 the other.
- When both bodies of a collision are the player's car, the second wins,
  so the first's mass is the one tested.
- UpdateScoring never clears `bNewTopSpeed`.
- Place 8 scores the 1ST PLACE BONUS, one past TOOK 7TH PLACE. A race of
  eight never takes eighth.
- `baPlaceReached[place - 1]` is unbounded, so places 0, 9 and on reach
  the Player's next words. The port reaches the same words for places -1
  to 14 and skips the rest, which no race sets.

### The checks

`tools/hudscore_check.py` runs each function above in RetailEmu, over
hudanim_check's model and INGAMEB's Flailer chunk.
`tools/src/hudscore_test.c` runs the port. The stubs, scripted the same on
both sides and logged, are GetRacingCar, IsBlinking, GetCollision,
GetInGameSample, IsPlaying, Play, GetTranslatedString and each body's
GetMassInverse.

`hudscore_check`: 1608 ops, 6184 lines, 0 differ. Its mutation pass makes
150 mutations, and all are caught. The first full pass left 4 survivors,
all gaps in the script:

- StartScore(e, value) for a scoring with a sound;
- leading a lap with 0 laps done;
- a knock with both bodies the player's car;
- a dot that changes with the order of the adds.

With those added, the 4 and `scorev-prints-score`, which had been listed
as equivalent, were run again, and all 5 are caught. The first check had
94 lines differing, from place 10: retail writes the word past
`bShownMusicTitle` and the port skipped it. The port now reaches the same
words.

The whole chain: 94 checkers with `hudscore_check` added, and the four
table generators. 0 of 98 failed, in 1849 seconds.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65 -WatchSeconds 40`, shots in
`out/azahar_8m4b`), the race ran for 40 seconds with no crash, and the HUD
shows as in 8m-4a. No score fired: the race has one driver and no lap was
finished in that time. The chain was running on the same machine, so the
frame rate was not read.

`hudcop.{c,h}` (8m-4c-1) were written alongside and compile in the ARM
build. They are not bound and have no checker yet, so they are not part
of this step.

### Next

8m-4c, in three parts:

- **8m-4c-1:** UpdateRadarDetector (`0x0017be70`), DrawTracker
  (`0x0017c278`) and UpdatePursuitMeter (`0x0017c380`), in `hudcop.c`.
- **8m-4c-2:** the rest of NISOverlayManager: Start, Update,
  UpdateDateAndTime, SetVisible, new, StartArrest and StartTicket.
- **8m-4c-3:** InitializeFlailerTachometer (`0x001434a0`) and
  RenderFlailerTachometer (`0x00143858`).

CONTINUE.md's "MovePursuitMeter (`0x00182948`)" was wrong.
`retail_match` guessed it from a 0.12 ratio, but that address is
NISOverlayManager::Finish, which is already ported. The pursuit meter
moves inside UpdatePursuitMeter.

## Session 31, continued (2026-10-03) -- the HUD's cop parts (step 8m-4c-1)

Three of the HUD's parts follow the cops: the radar detector's row of
lights and its beep, the trackers over the cars near the player, and the
pursuit meter with its tickets. UpdateHud calls each through a seam, and
this step fills them. `docs/formats/hud-cop.md` has the write-up.

### The port

- **`hudcop.{c,h}`** hold Player::UpdateRadarDetector (`0x0017be70`),
  DrawTracker (`0x0017c278`) and UpdatePursuitMeter (`0x0017c380`).
- **`main.c`** binds `gUpdateRadarDetectorFn`, `gDrawTrackerFn` and
  `gUpdatePursuitMeterFn`.
- tCopManager::GetRadarDetectorIntensity (`0x002274a8`) walks the cops
  and the track path, so it stays a seam until step 12. Until then the
  radar reads 0: every light unlit and no beep.

What retail does that a reader would not guess:

- The lights lit are the intensity times 11, truncated, at most 10.
  Lights 10 and 11 are never lit by the count; they swell off lights 8
  and 9. The swell is started every frame, but a bitmap start leaves a
  running animator be, so while the lights stay up the light pulses.
- The beep's test is `<`. For 9 lights at 620 ticks the two sides are
  equal, and it does not beep.
- DrawTracker adds the squares as `(dx*dx + dy*dy) + dz*dz`, the VU's
  order. Its cap on the scale never acts: by then the distance is at
  most 50, and 50 x 0.02 rounds to exactly 1.
- Going down a level, the meter flies out one bar more than it loses.
- 0x00182bb8 and 0x00182c18, which `retail_match` had called
  NISOverlayManager's "new" and a "MovePursuitMeter", are Player
  functions that lay out the score texts. Nothing calls either.

Where the port differs: no cop manager yet; the radar's flag starts at
0, where retail reads the stack; the port skips a missing light, X,
tracker or sample where retail writes through it; and levels over 4,
which tCopManager never gives, stay on bars 0 to 3.

### The checks

`hudcop_check` runs the three retail functions in the emulator against
the port, over hudanim's checker on INGAMEB's Flailer chunk: 1187 ops,
4763 lines, 0 differ. The mutation pass makes 120 mutations: 115 are
caught and 5 are equivalent, each with its reason in the checker and the
doc. The first pass left `tracker-dist-order` alive. Two places found by
search, where adding the squares in the other order changes the scale's
last bit, are now in the script, and it is caught.

The whole chain: 95 checkers with `hudcop_check` added, and the four
table generators: 0 of 99 failed, in 1722 seconds
(`out/chain_8m4c1.txt`). It ran beside 8m-4c-2's mutation pass, which
only `hudnis_check` builds.

The ARM build is clean. It also compiled `hudnis.c` (8m-4c-2), which is
in the source folder but not yet called.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65 -WatchSeconds 40`, shots in
`out/azahar_8m4c1`), the race ran for 40 seconds with no crash, and the
HUD shows as in 8m-4b. The race has no cops, so DetermineHudFeatures
leaves the radar and the meter off, and with no AI cars no tracker is
drawn. The first try went to the title screen: the boot key was missed
while the chain was running. The second started the race. The frame rate
was not read, since the chain was running.

### Next

- **8m-4c-2:** the rest of NISOverlayManager: Start (`0x00182488`),
  Update (`0x001825f0`), UpdateDateAndTime (`0x00182748`), SetVisible
  (`0x00182a48`), StartArrest, StartTicket and StartBusted. `hudnis.c`
  and its harness are written; the checker, the doc and the bindings
  are left.
- **8m-4c-3:** InitializeFlailerTachometer (`0x001434a0`) and
  RenderFlailerTachometer (`0x00143858`).

## Session 31, continued (2026-10-03) -- the NIS overlay (step 8m-4c-2)

A ticket, an arrest or a bust plays under a camcorder overlay: a REC
light that blinks, the date and the time, BUSTED!, and the bounty's
"+2000". The constructor, the destructor, SetScreen and Finish were
ported with the Player. This step is the rest. `docs/formats/hud-nis.md`
has the write-up.

### The port

- **`hudnis.{c,h}`** hold Start (`0x00182488`), Update (`0x001825f0`),
  UpdateDateAndTime (`0x00182748`), SetVisible (`0x00182a48`),
  StartArrest (`0x001832f8`), StartTicket (`0x00183308`) and StartBusted
  (`0x00228f10`).
- **`main.c`** binds `gNisOverlayUpdateFn` (RenderHud's) and
  `gNisOverlaySetVisibleFn` (SetHudFeatures'). `gCdReadClockFn` is a new
  reader of the 3DS's clock: `time()` through `gmtime_r`, written as the
  drive's BCD. `gScfGetLocalTimeFn` stays NULL, since the 3DS's clock is
  local already.
- **`nisoverlay.h`**: the word at +24 is `PointsDisplay`, the "+2000"
  text Start finds. `player_check` and its harness use the new name.
- The three Start* are called by the cops' NIS code, so nothing calls
  them until step 12.

What retail does that a reader would not guess:

- Any month that is not 2 to 12 takes January's name, 0 and 13 and up
  included: the test is unsigned `month − 2 < 11`. The BCD is decoded
  with no check, so `0xff` is 165.
- English prints "%s %d 20%02d" and every other language
  "%d %s 20%02d".
- The date's 31-frame wait is a wrapping difference compared signed, so
  frames going back make it wait.
- BUSTED!'s scale and alpha are set every frame from the two tracks, so
  it shrinks from 5 to its own scale while it fades in over a quarter
  second.
- `0x00182bb8` and `0x00182c18`, once listed here as the overlay's
  "new", are Player functions, and nothing calls them.

**banim.c's GetdVal.** This checker is the first to run the port's
BSpline against retail's own tCubic1D. `bspline_get_dval` computed
`((c0 × t) × 3 + c1 + c1) × t + c2`, where retail computes
`(c0 × (t × 3) + (c1 + c1)) × t + c2`, so `dval` was off in its last bit
from the third frame on. `banim_check`'s Python model made the same
mistake in the first product, which is why the two agreed. Both now
follow retail. `banim_check`, `bscreens_check`, `setup_check`,
`racesetup_check` and `bootflow_check`, the other checkers that build
`banim.c`, pass with it. The fix was written up in
`frontend-animation.md` in the last session but never reached the code;
this session found it when the checker showed 78 lines off.

Where the port differs: the points' alpha is skipped without a points
text, no coordinator counts as no replay, a missing clock or
translation leaves the date be, and the wait's subtraction is unsigned
so that it cannot overflow.

### The checks

`hudnis_check` runs the seven retail functions in the emulator against
the port, over retail's SplineSeek, FlailerPrintf with bSPrintf and the
Flailer runtime on INGAMEB: 818 ops, 4359 lines, 0 differ. The mutation
pass makes 119 mutations: 118 are caught and 1 is equivalent
(`arrest-state-after`: Start never reads `State`). The first pass left
`start-last-kept` alive, since every scripted Start had a clock that
worked and wrote the field again. Two Starts are now in the script,
one with a clock that fails and one with a busy clock.

The whole chain: 96 checkers with `hudnis_check` added, and the four
table generators. 0 of 100 failed, in 1591 s
(`out/chain_8m4c2.txt`).

The ARM build is clean.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65 -WatchSeconds 40`, shots in
`out/azahar_8m4c2`), the race ran for 40 seconds with no crash, and the
HUD shows as in 8m-4c-1. The race has no cops, so the overlay never
shows. The mutation pass was running, so the frame rate was not read.

### Next

- **8m-4c-3:** InitializeFlailerTachometer (`0x001434a0`) and
  RenderFlailerTachometer (`0x00143858`). CONTINUE.md has what is read
  of them so far.

## Session 31, continued (2026-10-03) -- the tach's red band (step 8m-4c-3)

Both tachometers have a red band from the red line to the top of the
dial. It is a TACH_GRADIENT bitmap (Animation 10): TACHGRADIENT
(`0x39c9eead`) in the chase view, and TACHGRADIENT2 (`0x7307c47f`) in
the bumper view. The
port drew it as a quad, so the whole ring was red. Retail cuts a fan out
of it, from the centre to the red line. `docs/formats/hud-tach.md` has
the write-up.

### The port

- **`hudtach.{c,h}`** hold InitializeFlailerTachometer (`0x001434a0`),
  RenderFlailerTachometer (`0x00143858`) and next_power_of_2
  (`0x0013ff60`).
  - Init lays nine points over the gradient: the centre, then the edge
    middles and corners clockwise from the bottom. Each point carries
    the UVs over the power-of-two allocation.
  - Render draws the quarters before the needle's whole, and then one
    cut, through the table at `0x002f09e0`.
- **`main.c`** binds `gInitializeFlailerTachometerFn`, which
  SetHudFeatures calls when it finds the gauges.
- **`uirender.c`**'s `draw_bitmap` sends a TACH_GRADIENT bitmap to the
  new `draw_tach`:
  - Render fills a pool of four ePolys.
  - Each one draws as a strip in ePoly::Render's order, through the new
    `georender_draw_hud_quad`, between a `C2D_Flush` and a
    `C2D_Prepare`.
  - With no list, nothing draws, as on the PS2.
- **`georender.c`**: `georender_draw_quad`'s body is now
  `draw_screen_quad`, with the matrix and the alpha test as arguments.
  `georender_draw_hud_quad` uses it on citro2d's mapping, blended as
  citro2d blends, with no alpha or depth test. It first sets texenv
  stages 1 to 5 to pass the colour through. citro2d leaves its own image
  stages there; it sets 1 to 3 again at its next draw after
  `C2D_Prepare`, and `C2D_Prepare` sets 4 and 5. The tint mode is in
  bits 16 to 19 of citro2d's flags, which `C2D_Prepare` leaves alone.
- **`bui.{c,h}`**: `BUIObject.chunk` is the object itself on retail's
  layout, the memory the Flailer setters write. It is NULL on the
  demo's layout.
- **The word at +108** holds a token, not the list's address, which does
  not fit on a 64-bit host: 0 for none, otherwise 1 + a slot in
  `hudtach.c`'s table of four. `hudtach_points` turns it back.

What retail does that a reader would not guess:

- The cut poly's colours are all `0x80808080`, not the bitmap's.
- With s = 2, Render leaves the cut's corner 2 at ePoly's constructor
  default, (64, 64) with uv (1, 1). The strip's second triangle then
  runs to that point, a sliver across the screen. The chase view always
  cuts with s = 1. In the bumper view, 38 of the 51 cars that show
  the gradient cut with s = 2. The other 13 have the tach in the speedo,
  and SetHudFeatures hides it. The port draws what retail draws, and it
  has not been compared with PCSX2.
- Init converts the texture's size unsigned and halves the scaled size
  with a signed divide.
- Past the four quarters the table runs into zeros to row 27, then
  pointers. Only a Rotation of −2160 or below reaches the pointers.

### The checks

`hudtach_check` runs Init and Render from retail's image in the emulator
against `hudtach.c` and `epoly.c`.

- **Stubs:** GetTextureInfo, and an AddPoly that hands out blocks
  retail's ePoly constructor filled.
- **Script:** both disc gradients through every degree and out to
  INT_MIN, then sizes, scales, layers, colours and lists.
- **Result:** 2287 ops, 7804 lines, 0 differ.
- **Mutation pass:** 93 mutations, 89 caught, 4 equivalent. The four are
  `pow2-zero-kept`, `init-uhalf-no-zero-add`, `table-row0` and
  `angle-q-floor`; `hud-tach.md` says why each is equivalent.
  - The first pass left `angle-c-cast` alive. A C cast of 360 − INT_MIN
    overflows where the EE saturates.
  - INT_MIN is in the script now. Both sides stop after 27 polys, so the
    24 million quarters it asks for end there.
- **Model fix:** the model first refreshed its pool only on a Render,
  and kept stale corners in the polys it had not refreshed. It now
  rebuilds exactly the polys the last Render used.

The whole chain: 97 checkers with `hudtach_check` added, and the four
table generators. 0 of 101 failed, in 1545 s
(`out/chain_8m4c3.txt`).

The ARM build is clean.

On Azahar (`run_azahar_race.ps1 -HoldKeys 65 -WatchSeconds 30`, OPEL,
car 37, in the chase view), shots in `out/azahar_8m4c3` before the stage
reset and in `out/azahar_8m4c3b` after it. The band looks the same in
both:

- The band runs from about half past twelve to half past two.
- The needle, the gear and the speed draw as before.
- The rest of the HUD is as before.
- 20 FPS. No crash in 30 seconds.

### Next

- **8m-5:** the two-screen split, as the user placed it (CONTINUE.md).
- **The bumper view's sliver**, against PCSX2, when the bumper view is
  next looked at.
