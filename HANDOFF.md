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
