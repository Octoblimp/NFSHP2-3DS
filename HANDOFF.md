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
