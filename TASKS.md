# TASKS

Status flags: `[ ]` not started, `[~]` in progress, `[x]` done, `[!]` blocked.
Numbered IDs are stable -- don't renumber when inserting new tasks.

## Phase 0 -- Project scaffolding & tooling setup

1. [x] `git init` + `.gitignore` (exclude `PS2 Files/`, build artifacts)
2. [x] Copy/adapt NFSU2-3DS's reusable 3DS-side skeleton (Makefile, app.rsf,
       heapcfg.c/.h, source/vp6/, jdlz.c/.h, build_cia.ps1, makerom/
       bannertool/dspenc binaries)
3. [x] Placeholder `main.c` stub; verify full build (`.3dsx`/`.smdh`/`.cia`)
3b. [x] `tools/mipsdis.py` -- a MIPS III / R5900 disassembler (integer,
       64-bit `ld`/`sd`/`daddu`, COP1 FPU, branch-likely; MMI and COP2 shown
       raw), resolving `.symtab` names on jump targets. Ghidra is still the
       tool for whole-function decompilation, but this answers "which bit
       does this branch test" in one command, and it was what settled the
       Flailer `FormatOptions` bit order. Note `.symtab`'s `st_size` is
       unreliable in this ELF, so it defaults to the gap to the next symbol.

4. [x] STABS/debug-info dumper -- `tools/stabs_dump.py` (small `.stab`
       section, VU asm line info only) plus `tools/mdebug_stabs_scan.py`,
       which cracked the real struct/class layouts out of `.mdebug` by
       harvesting its embedded stab-syntax strings directly (no MIPS
       toolchain needed). 1,432 struct/class definitions decoded with exact
       sizes/field offsets -- `docs/mdebug_structs.txt`,
       `docs/formats/mdebug-stabs.md`. See HANDOFF.md Session 2.
5. [x] ~~Install/locate a MIPS-capable GDB or ps2dev toolchain~~ --
       superseded by task 4's text-based `.mdebug` extraction; not needed.
6. [x] Ghidra project import of `NFSHP2.ELF`. No community PS2 EE extension
       needed, but the language matters: import as **`MIPS:LE:64:64-32addr`
       / `o32`**, not the default `MIPS:LE:32`. The EE code is MIPS III
       (`sd`/`ld`/`daddu` everywhere), which MIPS32 rejects -- with the wrong
       language nearly every function decompiles to `halt_baddata()`. Project
       lives in `Development/GhidraProjects/NFSHP2` alongside the existing
       NFSU2/LiquidTV projects. See HANDOFF.md Session 3.
7. [x] `HANDOFF.md`, `TASKS.md`, `README.md` created

## Phase 1 -- Asset extraction pipeline

8. [x] Reverse-engineer `ZDIR.BIN` directory format (index into `ZZDATA.BIN`).
       223 x 12-byte `DirectoryEntry{Hash,Fad,Size}`; `Fad` is a 2048-byte CD
       sector index. Filenames are stored only as `bStringHash()` (djb2 seeded
       -1) of the uppercased path -- `tools/bhash.py` implements it plus a
       meet-in-the-middle cracker. 200/223 names recovered
       (`docs/zdir_names.txt`, `tools/zdir_names.py`).
       Format writeup: `docs/formats/zdir-archive.md`.
9. [x] `tools/zdir_extract.py` -- extracts all 223 entries from `ZZDATA.BIN`
       into the original directory tree, with `--decompress` for `.LZC`.
10. [x] Identify per-asset formats. Done so far: the `bChunk` container that
        every asset is built from, and the complete chunk-type -> `Loader*()`
        map pulled straight out of `LoaderTable`
        (`docs/formats/bchunk.md`, `tools/chunk_loader_table.py`,
        `tools/bchunk_dump.py`) and the `0xb0300001` GS texture pack --
        container, the 164-byte `TextureInfo` record, the linear CLUT and
        both GS swizzles (`docs/formats/texture-pack.md`), and the
        `.MSH`/`.MSB` sound banks -- `SOUND_MSH_HEADER_INFO` and
        `SOUND_PATCH_INFO` straight out of the `.mdebug` type info, over plain
        SPU ADPCM (`docs/formats/sound-bank.md`); the `0x80010200` Flailer UI
        chunk -- the project/screen/bitmap/text tree every menu and HUD screen
        is built from (`docs/formats/flailer-ui.md`, `tools/flailer_dump.py`);
        and the `0x00039000` `LANGUAGES\FE_*.BIN` string tables that Flailer
        text objects resolve their `LanguageID` against
        (`docs/formats/language-table.md`, `tools/language_dump.py`).
        Also done: the `0x80034000` eSolid solid lists -- the chunk tree,
        `eSolid`/`eStripEntry`, and the `0x00034005` VU1 packets themselves:
        XYZ and normals are transposed in groups of four vertices, ST too
        except for an interleaved tail, colours are one RGBA5551 quad each,
        and the quad at VU address 1 is a per-vertex ADC bitfield whose set
        bits cancel a drawing kick. Verified over all 1,465 solids /
        22,280 strips on the disc: every strip reproduces its
        `eStripEntry.NumVerts` and `NumPolys` exactly, every vertex lands
        inside its `eSolid` AABB, every normal is unit length, and 99.65% of
        triangles wind the way their normals say they should
        (`docs/formats/solid-geometry.md`).
        Also done: the `ENGINE.CTB`/`.LTB` engine crossfade tables -- a bare
        360-byte `EngineDef` plus twelve 512-byte `EngineDefEntry` curves, no
        `bChunk` wrapper, with self-relative pointer arrays that
        `PlayerEngineSound::ResolveTables` fixes up in place. `.LTB` is the
        **L**oad table (on throttle) and `.CTB` the **C**oast table (off
        throttle); each holds three RPM bands heard through an engine and an
        exhaust mic, named `lelo`/`lemd`/`lehi`/`lxlo`/... in an ELF `.sdata`
        table, and those names concatenated with the car prefix are exactly
        the patches in that car's `NEWE*.MSH` bank. The curve is indexed by
        `min(440, 440 * rpm / maxrpm)` and crossfaded twice through an
        equal-power sqrt table -- by throttle between the two files, by
        `Timbre` between the two mics. `pbendtable` is relocated but never
        read (`docs/formats/engine-table.md`, `tools/engine_table.py`).
        **Movies are not VP6**: `MOVIES\*.AVI` are RIFF/AVI with fourcc
        `MV30` (EA's MV3 codec, `MV3Codec`+`Huffman` in the ELF), 512x256.
        The `source/vp6/` decoder copied from NFSU2-3DS does not apply.
11. [x] JDLZ: **HP2 does not use it** -- no `jdlz`/`JDLZ` symbol in the ELF or
        `.MAP`. `.LZC` files are a `COMP`-magic LZSS container handled by
        `LZDecompress()` (`LZCompress.obj`, 0x001aa460). Reimplemented in
        `tools/lzdecompress.py` and validated byte-exact against every raw
        twin in the archive, up to the 15 MB `FRONTEND\FRONTB.BUN`.
        `3DS Files/source/jdlz.c` was therefore dead weight and has been
        deleted; the runtime decoder is now `3DS Files/source/lzc.c`.
12. [x] Conversion tools. Done: `tools/texture_convert.py` -- walks any file
        (including nested `.BUN` bundles) for `0xb0300001` packs and writes one
        PNG per texture, stdlib only. **All three pixel formats now decode**,
        including PSMT4. The key was that being swizzled is a property of the
        individual texture, not of the format: byte `0x55` of the record is
        `Is32BitSwizzelled` (bWare's own name, straight out of the `.mdebug`
        `TextureImageInfo`), read by `FillVramWithTextures`, and when it is
        set the texture is
        uploaded as a PSMCT32 image half the width (and half or a quarter the
        height) and read back as PSMT8/PSMT4. Working in that host image's
        page/block/column space -- where a PSMT4 page's block grid is the
        transpose of PSMCT32's -- gives the 4-bit map, and reproduces the
        already-confirmed 8-bit one exactly. 809 of the 2642 texture records
        in the archive are flagged; the other 1833 are plain raster and were
        previously being unswizzled wrongly. Verified on the `LOGOTRACK*`
        wordmarks (legible), the 4-bit car skin atlases, and two objective
        tests over all 200 whole-page flagged 4-bit textures
        (`docs/formats/texture-pack.md`).
        Also done: the runtime C decoder `3DS Files/source/lzc.c` / `lzc.h`,
        ported from `tools/lzdecompress.py`, replacing the inapplicable
        `jdlz.c`. Byte-identical to the Python reference on all 37 COMP files
        in the archive (largest 15 MB), bounds-checked against corrupt
        SD-card data (20,000 fuzzed blocks, no overruns), and it builds into
        the .3dsx/.cia.
        Also done: `tools/flailer_dump.py` -- decodes the `0x80010200` UI
        tree into a screen-by-screen listing or JSON, resolving texture,
        font, screen and object hashes back to names and replacing every
        text object's stale authoring placeholder with the real string, and
        `tools/language_dump.py` -- reads any `FE_*.BIN` and can emit a
        1,896-row x 8-language CSV of every string in the game.
        Also done: `tools/audio_convert.py` -- unpacks any `SOUND\*.MSH` +
        `.MSB` bank into 16-bit WAVs plus a `patches.csv` of rates, volumes
        and loop points, joining the stereo pairs. All 30 banks convert, 439
        WAVs. Feeding those to `tools/bin/dspenc.exe` for DSPADPCM is Phase 3
        task 22.
        Also done: `tools/geometry_convert.py` -- decodes any file holding a
        `0x80034000` solid list (including nested `.BUN` bundles) to Wavefront
        OBJ + MTL, with per-vertex colours on the `v` lines, one group per
        solid and one material per light material hash. All 35 geometry files
        on the disc convert; see `docs/formats/solid-geometry.md`.
        Also done: `tools/video_extract.py` -- demuxes any `MOVIES\*.AVI` and
        writes one PNG per frame plus the soundtrack as a WAV and a
        `frames.csv`. This is **MV3-in-AVI**, not VP6/SCHl, so
        `source/vp6/ea_demux.c` does not apply. Rather than transcribe
        ~5,000 instructions of fixed-point, MMI-vectorised IDCT, the tool
        *runs the shipped decoder*: `tools/mipsemu.py` (new) is a small R5900
        interpreter that loads `NFSHP2.ELF` into a flat memory image and
        calls `MV3Codec::DecompressFrameShared()` directly, so the frames are
        the PS2's own output. ~16 s/frame; the disc has exactly one movie
        (`MOVIES\INTRO\EALOGO_EN.AVI`, 512x256, 90 frames, 3 s of 8-bit PCM)
        so that is fine. The format is disassembled and documented anyway in
        `docs/formats/mv3-video.md` -- frame header, the two `pCompData`
        layouts, the 2-bit-per-block DCT type array, the prefix/escape
        entropy coder, IJG quality scaling with an AAN prescale, the
        copy/skip bit-planes, and the BT.601 clamp-table conversion --
        because a Phase 3 C port (or a build-time pre-decode) needs it.
        Fixing `tools/mipsdis.py` was a prerequisite: variable shifts
        (`sllv`/`srlv`/`srav`) print `rd,rt,rs`, not `rd,rs,rt`, and had been
        coming out with their operands swapped; the EE's 3-operand
        `mult`/`multu`, the MMI opcode space and `lq`/`sq` were missing too.
        Also done: the `0xb0300100` **TextureAnimPack** sibling container --
        the flipbook animations, same three-leaf shape as the texture pack
        and loaded by the same `LoaderTexturePack`. A 52-byte `TextureAnim`
        per animation (name, hash, frame count, fps, time base) over one flat
        run of 16-byte `TextureAnimEntry` records, split by the constructor
        `NumFrames` at a time. The runtime plays an animation by *rotating*
        the frames' pixel and CLUT pointers among their own `TextureInfo`
        records, so nothing re-uploads. `texture_convert.py --anims` lists
        them and a conversion run writes an `anims.csv`. Eight animations
        across the disc (three in `GLOBAL\INGAMEB.BUN`, five in
        `TRACKS\TEX12LOCATION.BIN`); all 46 frame hashes resolve to textures
        in the same file.
        Also done: **mip levels**. The chain is stored base-first, tightly
        packed, each level halving both dimensions -- the sum reproduces the
        record's own `0x38` byte count exactly on all 1,755 textures that own
        their pixels. Each level has its own `Is32BitSwizzelled`, and they do
        differ within one chain, so `--mips` decodes level by level.
        `TextureBasePointerOffset` is a GS address, not a file offset, and
        disagrees with the file layout on 191 of 265 mipmapped textures.
        That leaves `3DS Files/source/vp6/` as dead weight the way `jdlz.c`
        was -- nothing on this disc is VP6 -- but it is left in place for now
        rather than deleted, in case the Phase 3 intro ends up reusing its
        player scaffolding around a pre-decoded frame sequence.
        **Correction, and it was a big one**: `ImagePlacement` /
        `PalettePlacement` are relative to the `0x30300004` payload *rounded
        up to 128 bytes*, not to the payload -- `LoaderTexturePack`
        (`0x001008a8`: `addiu s2,v0,143` / `and s2,s2,-128`), with the packer
        leaving 0 to 127 bytes of `0x11` filler to make room. Every texture
        had been coming out rolled sideways by that much, which flat UI
        sprites hide and photographs do not. Fixed in `texture_convert.py`
        and `3DS Files/source/texpack.c`; the two still agree texture for
        texture on all three UI bundles.
        **Second correction, from the same sweep**: a PSMT8 CLUT is stored in
        GS **CSM1 order**, not linearly -- entries 8..15 and 16..23 of every
        group of 32 are exchanged. bWare names the permutation:
        `RemapLinearIntoClut8` (`0x00118878`) is eight passes that swap
        exactly those two quadword pairs, and the engine calls it on palettes
        it *builds*, never on a pack CLUT, so a pack CLUT is already in that
        order. PSMT4 CLUTs are linear. This document previously claimed the
        opposite; that test predates the 128-byte fix above, and since
        `PalettePlacement` shares the same base it was comparing two readings
        of a palette that was thirty entries out of place. Both decoders now
        apply it and still agree on all 2,040 textures in the ten packs on
        the disc.
13. [x] Confirm asset delivery: external SD-card game directory (matching
        NFSU2-3DS), not ROMFS, given 273MB source archive size.
        Implemented in `3DS Files/source/gamedata.c`. Resolution order, first
        hit wins: `nfshp2_config.txt` (looked for next to the executable then
        in `sdmc:/3ds/NFSHP2-3DS/`, first non-comment line is the directory),
        then `sdmc:/3ds/NFSHP2-3DS/data`, then `sdmc:/NFSHP2`. A candidate
        only counts when `GLOBAL/GLOBALB.BUN` is actually in it, so a stale
        config file falls through to a working default instead of leaving the
        game pointed at nothing.

## Phase 2 -- Boot flow & frontend menus (first milestone)

14. [x] Decompile boot/logo sequence driver; look for a `BootFlowManager`-
        equivalent class in the recovered `.mdebug` type info.
        There is no `BootFlowManager` class -- the boot sequence is two
        separate mechanisms and the `.mdebug` type info names neither as a
        driver. Written up in `docs/formats/boot-flow.md`, address per rule.
        The outer one is a table-driven state machine:
        `GameFlowStateInfoTable` (`0x002f2eb0`), 10 states x
        `{const char *Name; void (*Begin)(); void (*End)(); void (*Loop)();}`.
        `main` (`0x0012da88`) asks for `LOADING_FRONTEND` and then hands the
        thread to `MainLoop`, which calls `ServiceGameFlow` (`0x001636f8`)
        *twice* per frame. `ServiceGameFlow` loops until the desired state
        stops changing, so a state whose `Begin` immediately redirects costs
        no frame -- that is how loading chains without a visible hitch.
        The inner one is `LaunchFrontendMenus` (`0x0016aa40`): it pushes
        screen names onto a 388-byte LIFO `ScreenStack` (12 x 32 bytes +
        index) in the order `Title Screen`, `Legal MumboJumbo`,
        `Language Options Pre FE`, `BootAutoload`, then enters the one on
        *top*, i.e. the last push that passed its predicate. So the push list
        reads backwards from the boot order.
        Four things a reimplementation gets wrong if it guesses:
        `ShouldSeeLegalMumboJumbo` (`0x0016aa28`) is `return 0` -- the legal
        screen is authored (`0xdd4197c9` in `FRONTB.BUN`, with its text
        object `0xdd479599`) and unreachable. `TheDemoDiscManager`
        (`0x002e8120`) is a 48-byte object rather than a pointer, its ctor
        clears `bActive` and nothing ever sets it, so every demo-disc branch
        is dead. `FlailerScreenVisibility` is `VISIBLE=0 / INVISIBLE=1` but
        `FlailerObjectVisibility` is `INVISIBLE=0 / VISIBLE=1` -- opposite
        polarities, used one line apart in `TitleScreen::HandleTick`, and
        reading them the same way makes the flow look nonsensical. And the EA
        logo cannot be skipped while the NFS intro can: `HandleEvent`
        (`0x0016a148`) gates the advance on
        `Mode == 1 || (Mode == 2 && MovieIndex != 0)`.
        `TitleMoviesToPlay` (`0x002f3770`) is 8 language rows x 2 x
        `{const char *Name; int Letterboxed}`, but only
        `MOVIES\INTRO\EALOGO_EN.AVI` is on this disc -- `NFSINTRO_EN.AVI` is
        absent from all 223 entries in `docs/zdir_names.txt`. So the retail
        boot is `BootAutoload` -> (`Language Options` on PAL) ->
        `Title Screen` (one movie) -> `New Main Menu`.
        Both clocks pinned down while in there (`AdvanceRealTime`
        `0x00199410`): `RealTime` is 60 Hz ticks and is forced to advance at
        least 1 per frame, `RealTimer` is in 1/4000 s units because
        `Timer::SetTime(float)` (`0x00134ef0`) is `(int)(f * 4000.0f)`. The
        shipped timeouts are `LegalScreenTimeout` = `AntiPiracyTimeout` =
        7.0s, `BeginDemoModeTimeout` = 30.0s, `DemoModeTimeout` = 120.0s.
        The one piece of data this needed had no table to read: the screen
        registry. Every `ChangeToScreen("...")` resolves through a linked
        list of `FlailerScreenConfig` built one `jal` at a time by
        `_GLOBAL_$I$*` constructors across a dozen object files. So
        `tools/screen_registry.py` walks `.text`, finds every call to either
        constructor, and back-propagates the argument registers out of the
        enclosing block -- a backward walk, because a forward sweep loses
        every value at a branch. It recovers 49 of the 51 sites (the other
        two are the 4-arg ctor forwarding to the 7-arg one) = 49 configs and
        49 flailer screens, all of which exist in the bundles.
        That turned up the last surprise: `ScreenName` and `FlailerHashes[0]`
        are different strings. The flow code says `"Title Screen"`; the
        bundle screen is `bhash("TITLE_SCREEN")` = `0xb5761d00`, and
        `bhash("Title Screen")` is in no bundle. Two namespaces, joined only
        by `FlailerScreenConfig`, which the port has to carry
15. [x] Reimplement as `kVideoStages[]`-style table in `main.c` (pattern
        already proven in NFSU2-3DS)
        `3DS Files/source/gameflow.c` + `.h` (1,200 lines) is the port of the
        whole boot flow: `GameFlowStateInfoTable` as
        `BGameFlowStateInfo[BGF_NUM_STATES]`, `ServiceGameFlow`'s
        End-then-Begin loop-until-settled, the 388-byte 12x32 `ScreenStack`
        with `ChangeToScreen` / `MoveToPreviousScreen` / `PopUntil`, the
        `LaunchFrontendMenus` backwards push order and its four predicates,
        and the `TitleScreen` movie sequencer. `main.c` holds the three
        concrete tables, and `kBootStages[]` is the `kVideoStages[]`
        analogue:
            { "Title Screen",            bgf_should_see_title_sequence },
            { "Legal MumboJumbo",        bgf_should_see_legal_mumbo_jumbo },
            { "Language Options Pre FE", bgf_should_see_language_select },
            { "BootAutoload",            bgf_should_see_autoload },
        Everything the flow touches on the outside -- screen and object
        visibility, texture changes, movies, resource loads, save jobs, sound
        -- goes through a `BGameFlowHooks` vtable, so the module builds on
        the host with no `<3ds.h>`; `main.c` wires the hooks to `bui.c` and
        `uirender.c`. One hook was missing on the `bui` side and is new:
        `bui_set_object_visible` writes `FlailerObjectVisibility` at +17 and
        the dirty byte at +19.
        Checked the usual two ways. `tools/bootflow_check.py` is a second,
        independent implementation in Python -- including a float32 emulation
        for the frame clock, because `RealTime` advances by
        `(int)(accum * 60.0f)` in C `float` and a Python double drifts off it
        -- and it diffs a full transcript over 12 scenarios (ntsc, pal,
        nolang, skipmovies, relaunch, demodisc, attract, select, skipintro,
        mainmenu, mumbo, legal): **3,659 lines, 0 differ**. Three of those scenarios
        exist because the first pass silently covered nothing: an event
        injected at frame 0 is overwritten by the boot itself, and a "skip"
        pressed after the movie already ended never reaches the
        "the EA logo cannot be skipped" branch.
        And looked at, which is the part a cross-check cannot do. Rendering
        the four boot screens turned up one thing the transcript could never
        have shown: **`Title Screen` composites to solid black as authored**,
        because its two movie planes draw `SPLASH_SCREEN` -- a 512x256 buffer
        that is 131,072 pixels of opaque black, the blit target, not art --
        and layer 0 is the *frontmost* layer of the main pass, so they cover
        `PRESS START` at layer 13 and the logo at layer 24. Hide them, as
        `HandleTick` does when the last movie ends, and the retail title
        screen appears. A port that skipped that one line would have shipped
        a black title screen and no way to tell why. Also: `BootAutoload` has
        zero objects in both bundles, and `Legal MumboJumbo` draws `EA_LEGAL`
        out of `GLOBAL\DYNTEX.BIN`, which reads "PLACEHOLDER LEGAL SCREEN" --
        independent confirmation that `ShouldSeeLegalMumboJumbo` really is
        `return 0` and the screen never shipped. All of it is in
        `docs/formats/boot-flow.md`.
16. [~] Reimplement bWare's menu/UI system (`source/bui.c` + `uirender.c`).
        **The data half is done and on screen.** `bui.c` parses the
        `0x80010200` tree; `uirender.c` draws a screen through citro2d with
        real textures, real fonts and real translated strings; `main.c` is a
        viewer that pages through all 76 screens in any of the 8 languages.
        Every module is cross-checked against its Python reference rather
        than trusted on inspection: texpack 397/397 textures, langtab 15,168
        strings across 8 files, bfont 953 lines, bui 2,331 lines -- 0 differ
        in each. `tools/flailer_render.py` composites the same screens to PNG
        for eyeballing, and the main menu, the option screens and the help
        screen all come out looking like the game.
        Two engine behaviours that had to be recovered for that: the layer
        draw order is back-to-front in a fixed *non*-monotonic sequence
        (`24..20`, `15..0`, `19..16`, `28..25` -- four descending loops in
        `eDisplayFrame`), and `RenderCharacter` scales glyph width by
        `ScaleX` twice, a shipped bug the screens were authored against.
        Both are written up in `docs/formats/flailer-ui.md`.
        The behaviour half is task 17 and is now done too, in
        `source/bmenu.c`. `DataEventSelectScreen` (seen in the `.mdebug`
        strings survey) is a concrete first screen-data class
17. [x] Wire hid input -> menu navigation, citro2d text, citro3d backgrounds.
        `3DS Files/source/bmenu.c` is the port of `FlailerMenu` /
        `FlailerMenuItem` / `FlailerScreen`'s JoyHandler, decompiled out of
        the ELF because none of those classes ships as a chunk. Written up
        with an address per rule in `docs/formats/flailer-menu.md`.
        The headline finding is how a menu is built at all: there is exactly
        one construction site in the game, `Activate__13FlailerScreen+0x3c`,
        and it passes the literal `"MENUITEM_%d"`. So a menu is simply the
        screen's text objects named `MENUITEM_0` .. `MENUITEM_15`, gaps
        allowed -- `NEW_MAIN_MENU` uses 1, 2 and 3 and skips 0. 46 screens
        on the disc have one, from 1 to 10 items.
        Two things that a reimplementation gets wrong if it guesses:
        `SetColor__16FlailerTextChunk` (`0x0013e820`) replaces only the low
        24 bits and keeps the chunk's alpha, and the colours are written
        straight back into the loaded chunk because there is no separate
        runtime copy. And `AlignBar` is dead: it has zero callers, and no
        bundle on the disc contains the `HIGHLIGHT_BAR` object it would move
        -- 0 hits across all 2,252 objects. Screens animate their own
        highlight instead (`NewMainMenu` through `tHighlightAnimation`).
        The shipped values of the gp globals came out of `.data`, since
        nothing writes them: `LoopingMenuScrollMode` is 1, so wrapping with
        disabled items skipped is the real behaviour, and the highlight is
        `HighlightR/G/B` = 128/64/0, the frontend's orange.
        Checked the same way as everything else: `tools/bmenu_check.py`
        diffs the C against a second Python implementation over an identical
        event script -- messages, per-item state and live colour after every
        step -- 3,234 lines on `FRONTB.BUN` and 1,783 on `INGAMEB.BUN`, 0
        differ. And looked at: `tools/flailer_render.py --menu-item N
        --gray M` applies the same recolouring to a composited PNG, and
        `NEW_MAIN_MENU` comes out with the right entry in the right orange.
        `main.c` now navigates the screen it is showing with the D-pad.
18. [x] Milestone acceptance: EA logo -> publisher logos -> legal/PSA
        screens -> main menu, real assets, navigable on 3DS controls.
        **Accepted, on the emulator, with the sequence trimmed to what the
        disc actually contains.** Two of the four things this milestone names
        do not exist on NFSHP2: there are no publisher logos beyond EA's --
        `MOVIES\INTRO` holds `EALOGO_EN.AVI` and a `NFSINTRO_EN.AVI` that was
        never pressed (task 15) -- and the legal/PSA screens are gated off by
        `ShouldSeeLegalMumboJumbo` (`0x0016a648`), which is `return 0`, with
        `EA_LEGAL` in `DYNTEX.BIN` reading "PLACEHOLDER LEGAL SCREEN". So the
        shipped sequence is BootAutoload -> title screen with the EA logo
        movie -> PRESS START -> main menu, and that is what the port does.
        `tools/run_azahar_test.ps1` is the acceptance test: it boots the
        `.3dsx` in Azahar, waits on lines in `sdmc:/nfshp2_debug.txt`, drives
        START / D-pad / A / B / SELECT in with `PostMessage`, captures the
        window at each step with `PrintWindow(PW_RENDERFULLCONTENT)`, and
        asks the app to leave its main loop rather than killing it so the
        texture tally comes out with it. Method lifted wholesale from
        NFSU2-3DS; the three things that make it work at all (`.3dsx` not
        `.cia`, `PW_RENDERFULLCONTENT`, `SetProcessDPIAware` first) are in
        the script's header. Current verdict: **PASS -- booted, movie played
        90/90 frames at 512x256/30fps, reached the main menu, exited
        cleanly; 19 textures cached, 0 missing, 0 fonts missing**, 60 fps at
        100% speed, nine screenshots.
        Looking at those screenshots found two defects a cross-check could
        not, which is exactly why the rule exists:
        **The title screen rendered as PRESS START on an empty field** -- no
        NFS logo, no top border. `texpack_upload` refused anything that was
        not a power of two, on a comment that claimed "every texture in these
        packs already satisfies" it. Nothing had checked: **292 of FRONTB's
        397 are not**, nor are `LOADING` (512x184) or `TOP_BORDER` (512x24).
        The GS takes any size, the PICA200 does not. Fixed by padding the
        allocation up to the next power of two per axis with the image in the
        top-left and the edge texel repeated into the pad (so GPU_LINEAR at
        the image edge blends with a copy of itself, as CLAMP_TO_EDGE did),
        the caller sizing the quad from `TexInfo` and taking UVs against
        `C3D_Tex`'s padded `width`/`height`. The title screen and the main
        menu's grid, panels and logo all appear.
        **Selecting anything in the main menu did nothing**, and B then
        dropped to the title screen, which replays the EA logo -- which is
        what it looked like from the outside. Two separate causes.
        `New Main Menu` was registered with `bgf_plain_screen_callback`, and
        `menuCallback` threw away the item hash and sent the *screen's*, so a
        three-way test on the item could never have matched. Ported
        `NewMainMenu::HandleEvent` (`0x00203768`) properly: SELECT routes
        `MENUITEM_1` "Hot Pursuit" to `CopsOn = 1` + `"Cops On Mode Select"`
        (`0x00203800`), `MENUITEM_2` "World Racing" to `CopsOn = 0` +
        `"Cops Off Mode Select"` (`0x00203818`), and `MENUITEM_3` "Options"
        to `"Options"` (`0x00203830`); added `bgf_menu_item_event()` so the
        item's own hash goes with the message. None of those three screens is
        in the registry yet, so the flow traces `unregistered Options` and is
        left with no current screen -- which is also what `ChangeToScreen`
        does, since it clears `pCurrent` *before* the lookup. All three push
        `New Main Menu`, so B comes back. Covered by a new `mainmenu`
        scenario in the boot-flow cross-check (12 scenarios, 3,659 lines, 0
        differ), and `final` now prints `CopsOn`.
        One thing that looks like a bug and is not: re-entering the title
        screen replays the EA logo from the start. `TitleScreen::Callback`
        (`0x0016a590`) allocates a **new** `TitleScreen` on every ACTIVATE,
        and the constructor (`0x0016a1d0`) stores zero to `movieIndex` at
        `0x0016a224` and opens movie 0 unconditionally. The PS2 does the
        same thing.

The two entries below are scope that only appeared once the main menu was
on screen and its items led somewhere. They are lettered rather than
numbered so that the Phase 3-5 numbers other documents already cite --
task 21 in `docs/formats/bchunk.md`, task 22 in `docs/formats/sound-bank.md`
-- keep pointing at the same work.

18a.[x] The three screens the main menu leads to: `Cops On Mode Select`,
        `Cops Off Mode Select`, `Options`. Ported to
        `3DS Files/source/bscreens.c`, written up in
        `docs/formats/frontend-screens.md`. These are real C++ classes in
        the ELF, not chunk data: `CopsOnModeSelect` (`0x00204e10`),
        `CopsOffModeSelect` (`0x00205a58`) and `tOptionsScreen` /
        `OptionsScreenBase` (`0x001b8e30`), each reached through a
        `FlailerScreenConfig` row that joins the authored `ScreenName`
        ("Cops On Mode Select") to the hash of a quite different string
        (`bhash("COPS_ON_MODE_SELECT")`). The two namespaces are joined
        nowhere else, which is why the registry row is not optional.
        What the port reproduces: the per-item blurb (`tAnimatedBlurb`
        retargets `SCROLLING_TEXT` at a `LanguageID` from a table -- the
        bundle ships the authoring placeholder "This text will scroll
        sideways..." in that object, which is what you see if the blurb
        never fires); the selection brackets (`MENUITEM_UNDERSCORE` /
        `MENUITEM_OVERSCORE` snapped to the highlighted item's bitmap
        bounds, offset -3.0 and +6.0 from two globals at `0x00324a1c` and
        `0x00324a18`); `GrayMenuItem` (`0x001b8a18`) and which of its
        three modes also hides the object; the exit animations, whose
        0.25 / 0.20 / 0.40 s durations are `0.05 + n * 0.05` over the
        screen's `MENUITEM_n_GROUP` count and were confirmed by counting
        those groups in `FRONTB.BUN` rather than by reading the code;
        and `StartQuickRace` (`0x001a8e08`), all 25 stores into
        `RaceParameters`. `JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION` is a
        *held* button, not a pressed one: the Mode Selects only remember
        whether it is down and `StartQuickRace` reads that when it runs.
        Cross-checked the usual way -- `tools/bscreens_check.py` is an
        independent Python model of all three screens, 17 scenarios, 1246
        lines, 0 differ -- and walked on the emulator, which now enters
        Cops On Mode Select and Options with the brackets and the blurb
        already on the right item.
        One ordering bug came out of that walk and is fixed in
        `gameflow.c`: the `enterScreen` hook ran *before*
        `SCREEN_ACTIVATE`, so the menu it builds delivered its opening
        `MENUITEM_HIGHLIGHT` to a screen instance that did not exist yet
        and the first highlight was dropped -- brackets and blurb sat
        where the bundle authored them until the player pressed a
        direction. In the original the menu is built by the screen's own
        constructor, which runs on `SCREEN_ACTIVATE`, so the hook belongs
        after the message. Same reasoning applies at exit, so `main.c`
        now leaves through `bgf_change_to_screen(NULL)` instead of
        closing the menu behind the flow's back.
        Three object hashes in these screens were still uncracked here:
        `0x6eb9985d`, `0x70a404ec`, `0xab671c9a`. A 4,185-word list and an
        exhaustive sweep of every string up to 4 characters missed all
        three. 18b cracked the first two (`NONAME`, `WHITEOUT_BAR`) plus
        `0x97bf4b25` (`UNDERSCORE_GROUP`) by working from the names the
        animation layer already uses; `0xab671c9a` and `0x1042eac3` are
        still named in the doc as unknowns rather than guessed.

18b.[x] The frontend animation layer, ported to
        `3DS Files/source/banim.c` (~700 lines) and written up in
        `docs/formats/frontend-animation.md`. `tCubic1D` + `SplineSeek`
        (`0x001d0790`), `AnimationGroup` (`0x00232010` / `0x002320d0`),
        `tSlideAnimation` with its three uses -- `tSlideInAnimation`
        (`0x00232a48`), `tSlideOutAnimation` (`0x00232958`),
        `tExitScreenAnimation` (`0x00232b50`) -- `feAnimAlphaElement`
        (`0x00231ba8`), `tHighlightAnimation` (`0x00232318`),
        `tAnimatedBlurb` (`0x00232c18`) and `SelectionSet` (`0x00169358`).
        The group and mask hashes are built at runtime by `SprintfAndHash`
        (`0x001d1d98`), so the port computes them from the djb2 stride
        rather than tabling them: `MENUITEM_n_GROUP = 0x59c1995e +
        n*33^6` and `MI_n_MASK = 0x6bdfbaaf + n*33^5`, checked against
        `tools/bhash.py` for n in 0..9.
        The payoff at the screens layer: `BSCR_EXIT_COPS_ON/OFF/OPTIONS`
        are gone. Those three hand-measured constants (0.25 / 0.20 /
        0.40 s) are now what falls out of `tSlideOutAnimation` asking the
        bundle which `MENUITEM_n_GROUP`s exist, and the harness prints
        0.250 / 0.200 / 0.400 back unchanged -- derived instead of
        asserted.
        Four shipped oddities are reproduced rather than corrected,
        because "the original does this" is what makes the two
        implementations comparable: `bSin` called twice per bloom frame,
        `FlailerGetScale` called twice in `SetCurrentMenuItem`,
        `SetupToAnimate`'s dead `state = 2`, and `AddItems` counting a
        mask the screen does not have so the item indices keep their hole.
        `bSin` (`0x00241e98`) is a BAM table walk that overshoots to
        1.00000358 at the peak, so it is ported rather than replaced with
        `sinf`. `ClampSecondDerivative`'s argument bug (`0x001d0818` tests
        the second-derivative limit, `0x001d0824` passes the first) is
        documented in `banim.h` but not carried: the frontend's only
        caller passes 0 for both.
        Wiring: `gameflow.c` now also keeps `RealTimeElapsed`
        (`0x00323cdc`) beside `RealTimer`, because the integrator wants
        the frame delta and everything else wants the total; `bscreens.c`
        owns one `BAnim` and re-slaves it from both at every entry point
        rather than starting a second clock. `main.c` implements the
        eighteen `BAnimHooks` against `bui.c`/`uirender.c`, which needed
        five new primitives underneath -- `bui_get_object_alpha` /
        `bui_set_object_alpha`, `bui_set_object_scale`,
        `bui_set_text_string`, `bui_next_in_group` and
        `uirender_text_extent` -- plus `ScaleAboutCenter`'s geometry
        recovered from `0x0013eb20`.
        Cross-checked the usual way: `tools/banim_check.py` is an
        independent Python model, 23 scenarios, 2219 lines, 0 differ, and
        mutation-tested (Taylor coefficient `2.755731884e-06` -> `e-05`
        moves 28 lines, slide stride 0.05 -> 0.06 moves 173).
        `tools/bscreens_check.py` and `tools/bootflow_check.py` still run
        clean at 1246 and 3659 lines. Built and walked on Azahar: PASS,
        13 screenshots, 19 textures cached, 0 missing.

## Phase 3 -- Core engine systems

19. [x] Math/vector/quaternion/matrix (`bMath`, `bVector`, `bQuaternion`,
        `bMatrix`). Four contiguous objects, 73 functions, 10.3 KB of
        `.text`: `bVector.obj` `0x00240198`, `bQuaternion.obj` `0x002411f0`,
        `bMath.obj` `0x00241bc8`, `bMatrix.obj` `0x002424f8`. All 73
        decoded and ported: `bmath.c`, `bmathtab.c`, `bvector.c`,
        `bmatrix.c` and `bquat.c` with their headers, in
        `3DS Files/source`. The decode is written up in
        `docs/formats/bmath.md`, address by address.
        Two checkers hold the C to that document, each an independent
        Python model written from the disassembly and diffed line for
        line, each mutation-tested so a checker that cannot fail does not
        get to claim a pass: `tools/bmath_check.py` (18 scenarios, 6065
        lines, 12 of 12 mutations caught) and `tools/bvector_check.py`
        (27 scenarios, 5721 lines, 23 of 23).
        `tools/gen_bmath_tables.py --check` holds `bmathtab.c` to the ELF.
        The two atan tables regenerate exactly as
        `(int)(atan(i/s) * 10430.3779296875)` -- the float32-rounded BAM
        constant, not `32768/pi`; `bSinTable` and `bASinTable` do not
        regenerate from any model found and are embedded verbatim.
        `banim.c`'s private `banim_bsin` is gone, folded into `bMath`'s
        `bSinF`. `tCubic1D` stays in `banim.c` -- it is `Point.obj`, game
        code, not bware.
        Two deliberate divergences, both stated at the site: the
        quaternion `bNormalize` uses a true reciprocal square root where
        VU0 uses a hardware estimate, and the host checker build compiles
        with `-ffp-contract=off` so it cannot fuse a multiply-add that the
        EE does not fuse.
        Hazard carried forward: `bSlerp`'s 0.05 epsilon is the only thing
        keeping `bASin`'s argument inside `bASinTable`. Callers must pass
        unit quaternions; nothing in the routine checks, and an
        out-of-range argument reads past the end of the table rather than
        returning a wrong answer.
20. [x] Memory/slot-pool allocator (`bSlotPool`/`bNewSlotPool`) on top of
        `heapcfg.c`. `bSlotPool.obj` `0x0023f508`-`0x00240198`, 3216 bytes,
        34 symbols, all decoded and ported: `3DS Files/source/bslotpool.c`
        and `.h`, written up address by address in
        `docs/formats/bslotpool.md`. Fixed-size blocks carved out of one
        allocation, a free list threaded through word 0 of every free slot,
        an expansion chain when a pool runs dry, and a manager holding every
        pool on bWare's intrusive `bTList` so the lot can be printed.
        `main.c` builds the manager explicitly where `_GLOBAL_$I$`
        (`0x00240070`) builds it at load time, and points the `bPrintf` hook
        at the debug log through a line buffer, because a
        `PrintAllSlotPools` row arrives in up to six separate calls and only
        the last ends the line. The allocator hook is left at its default,
        `malloc`, which is already the heap `heapcfg.c` sized.
        `tools/bslotpool_check.py` is an independent Python model written
        from the disassembly, not from the C: 17 scenarios, 990 lines,
        0 differ. An allocator has no return value worth checking on its
        own, so what is compared is the *sequence* -- after every step both
        sides print the pool chain, the free list in order, the six counters
        and which arena blocks are still checked out.
        `tools/bslotpool_mutate.py` holds it honest, 37 of 37 caught, and
        unlike the bvector and bmath runners it is kept: the mutation set is
        a list of every behavioural claim the module makes, and rebuilding
        it from nothing cost a session.
        The mutation test found one real hole. Freeing only the head of an
        expansion chain and dropping the rest moved 0 lines, because the
        transcript reported a block's liveness only as a side effect of
        printing a pointer into it and after a teardown nothing does. Both
        sides now end every scenario with an `arena:` line; the mutation
        moves 10.
        Four deliberate divergences, all stated at the site and listed in
        the doc: `ExpandSlotPool` checks its allocation where the original
        dereferences it unconditionally (`0x0023f7c8`); `new_pool` clears
        the `bTNode` links the original leaves as garbage, so a pool made
        while the manager is down can be deleted once it is up;
        `CleanupExpandedSlotPools` keeps a pool whose recount disagrees
        instead of trapping (`0x0023f9bc`); and the header-size arithmetic
        is computed from the host's pointer width so the module is correct
        at 8-byte pointers and reduces to the PS2's 48-byte header at 4.
        `PrintAllSlotPools` is compiled into the retail build, not stubbed
        -- a real prologue at `0x0023fef8` and a 304-byte body -- so the
        high-water mark was readable on a shipped disc and the port keeps
        the whole debug path.
        Hazards carried forward, all faithful to the ROM: `Free` has no
        NULL check, no ownership check and no double-free check, so a
        double free corrupts the list silently and `numAllocatedSlots` can
        go negative; `GetSlotNumber` divides unsigned (`0x0023f5d4`), so a
        pointer below the slot array comes back as 357913939 rather than
        -2; and `FlushSlotPool` on a pool that has expanded strands every
        expanded slot, which is safe only where the original uses it.
        Built and walked on Azahar: PASS, 13 screenshots, 19 textures
        cached, 0 missing, exits cleanly.
21. [ ] Rendering: VU1 geometry submission -> citro3d equivalent
22. [ ] Sound: new 3DS DSP driver behind the recovered `bDriver`/`bSnd` interface
23. [ ] Camera (`Camera.obj`, `CameraMover.obj`)
24. [ ] Track/route system (`TrackRoute.obj`, `espEmptyLayer` -- "Esp" spline/
        track-layer format, needs `docs/formats/track-route.md`)

## Phase 4 -- Car physics & gameplay

25. [ ] Car simulation (recovered car-state struct layout from `.mdebug`)
26. [ ] Race/event logic, cop AI, pursuit (roadblocks, spike strips) --
        `HotPursuitEvent` already seen in the `.mdebug` strings survey
27. [ ] Track rendering/streaming, collision
28. [ ] New3DS perf: core2 for background streaming/decode, gate higher
        fidelity behind the New3DS speedup flag

## Phase 5 -- Polish

29. [ ] Save data, options menus, final sound mix pass
30. [ ] Split-screen/multiplayer scope decision (HP2 supported split-screen;
        not committed to yet -- decide once single-player core is solid)
31. [ ] Final CIA packaging + Old3DS/New3DS compatibility pass
