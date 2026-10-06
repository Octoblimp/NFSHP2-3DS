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
        The `source/vp6/` decoder copied from NFSU2-3DS does not apply,
        and was deleted on 2026-09-28.
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
        That left `3DS Files/source/vp6/` as dead weight the way `jdlz.c`
        was -- nothing on this disc is VP6. It was kept in case the Phase 3
        intro reused its player scaffolding. The intro plays through
        `mv3.c` and `avimovie.c` instead, and the directory was deleted on
        2026-09-28, at the user's request.
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
16. [x] Reimplement bWare's menu/UI system (`source/bui.c` + `uirender.c`).
        **Done, including the UV scrolling that was the last thing out, so
        Phase 2 is closed.** `bui.c` parses the
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
        strings survey) is a concrete first screen-data class.
        **The scrolling textures**, carried over from 18b, were the last
        thing outstanding. `texpack_scroll_axis()` is the port of
        `TextureInfo::GetScroll` (`0x00100a60`); `uirender.c` caches the four
        fields per texture, puts `GPU_REPEAT` on the scrolling axis, and
        offsets the subtexture *after* `subtex_from_pixels()`, because the
        original divides its UVs by the power-of-two allocation before adding
        the offset -- so the offset is in padded space, and T's sign flips
        with the axis. `bui_set_bitmap_texture()` joins it, a port of
        `FlailerBitmapChunk::ChangeTexture` (`0x0013eee0`).
        The cross-check samples the offset at five times rather than just
        reading the four fields back, because a port that rounds where
        `GetScroll` truncates gets every field right and the animation wrong;
        making that exact change turns 0 differ into 2 differ.
        The finding that made this worth doing properly: **nothing on the
        disc draws either scrolling frontend texture.** `ROADLINES` and
        `SCREEN_LINES` occur exactly once each in all of `extracted/`, in
        their own record -- no Flailer bitmap, no second pack, nothing in the
        ELF -- against 16 and 17 occurrences for textures the frontend really
        uses. Session 9's guess that `SCREEN_LINES` is the menu background's
        scanlines is struck out in `HANDOFF.md`. And it could never have
        animated: its alpha pattern repeats every four rows and one step
        moves exactly four rows, so every step lands on the same phase.
        So the feature has no subject on the disc to be looked at over, and
        `main.c`'s viewer grew a B key that points the current screen's
        bitmaps at each in turn through the real draw path.
        Looked at, with `tools/run_azahar_scroll.ps1`: `ROADLINES` at
        t = 50.34/53.16/56.15 s reported du = +0.3293/+0.5336/+0.8668 on the
        device, each the fractional part of `t * 0.78125` by hand; du grew by
        0.2043 then 0.3332, predicting 126 px and 206 px of leftward travel
        across the quad's 618 px in the capture, and circular
        cross-correlation of two row bands measures 126 px and 206 px.
        `SCREEN_LINES` reported dv = -0.7188/-0.8125/-0.9688, each
        `frac(trunc(t/0.04) * -0.015625)`, and drew bit-identical frames,
        which is the correct result for it. Written up in
        `docs/formats/texture-pack.md`.
        **Not ported:** `RenderSingleFlailerBitmap` also insets every UV
        corner by half a texel of the padded size. That touches all 397
        textures rather than the two that scroll, so it wants its own
        verification pass; the omission is stated at the site.
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
        **Corrected in Session 25:** "all 73 ported" was 72. `bToPolar`
        (`0x002424a0`) was decoded and written up but never in
        `bmath.c`, and nothing noticed until `Car::IsCarInFront` called
        it. It is ported now: `bmath_check` is 19 scenarios, 6424
        lines, 0 differ, and its kept `--mutate` pass is 9 of 9.
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
        (`0x00240080`) builds it at load time, and points the `bPrintf` hook
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
21. [x] Rendering: VU1 geometry submission -> citro3d equivalent.
        Split in two -- **21a the decoder, 21b the submission path** --
        and both are done: cars draw on the top screen, with their own
        textures, out of the shipped `CARS\*\GEOMETRY.BIN`.

        **21a.** `3DS Files/source/geometry.c`/`.h` reads the `0x80034000`
        chunk tree, the 64-byte `eStripEntry` table and the VU1 packets
        inside `0x00034005`, and turns each strip into a triangle list with
        position, ST, RGBA5551 colour and a signed-byte normal. Written from
        `docs/formats/solid-geometry.md` and never from
        `tools/geometry_convert.py`, so the two are independent. Nothing in
        it allocates: a strip is bounded at 30 vertices by the format, so
        `GeoStrip` is a fixed scratch buffer the caller owns, and
        `GeoStripCursor` walks a solid in one pass instead of the O(n^2) the
        naive "add up every preceding DataQWordSize" would cost on a
        253-strip solid.

        Unlike every checker before it this one drives the *disc*, not a
        script, because for once there was a real oracle: the Python came
        first and was validated against the shipped data itself.
        `tools/geometry_check.py` diffs the two transcripts over 28 car
        files and both track bundles --
        **30 files, 42047 lines, 0 differ** -- carrying an FNV-1a digest per
        strip and per solid so every vertex is covered without printing tens
        of millions of lines, plus the invariants recomputed on both sides:
        1,411 solids, 18,848 strips, 0 vertices outside their AABB, 0
        normals outside the 125..127 band, and decoded triangles equal to
        `eStripEntry.NumPolys` on every strip. `--detail NAME` switches one
        solid to a full per-vertex dump on both sides.
        `tools/geometry_mutate.py`: **51 of 51 mutations caught**, about two
        minutes, with six more listed as equivalent and the measurement that
        proves each one cannot reach the output.

        Five things the port found that the document had wrong or missing,
        all now fixed in `docs/formats/solid-geometry.md`:

        * normals were documented as "length 126 or 127"; the real band is
          **125..127** and the old claim rejects 16% of the data. 53 of the
          192,875 normals across the car set are exactly zero, which is in
          the data and is not the same condition as "this strip has no
          normal field" (about 17% of strips).
        * `eSolid.NumTextureTableEntries` at 0xAC is **zero on all 1,411
          solids**, including one whose table has 28 entries. Count the
          `0x00034006` chunk instead. `NumLightMaterials` at 0xAE, by
          contrast, agrees with its table everywhere.
        * `eStripEntry.TextureNumber` at offset 0x00 was missing from the
          document's table entirely -- and it is the only link between
          geometry and the texture packs. 25 strips carry `TextureNumber ==
          NumTextures`, one past the end: the untextured sentinel.
        * `eStripEntry`'s NumVerts/NumPolys/LightMaterialIndex are an exact
          copy of the VU header quad on all 18,848 strips, so a renderer can
          size buffers and skip strips without replaying a packet.
        * `TRACKS\TRACKA12.BUN` holds no solid list at all; all 1,135 track
          solids are in B12.

        And one real defect in the port itself, found by a mutation rather
        than by review: `geo_decode_next` did not advance its cursor past a
        strip it could not decode, so the obvious caller loop spun forever.
        The mutation that made every packet unreadable printed 72 million
        lines in sixty seconds. The cursor now advances on every outcome but
        GEO_EEND, and the contract says so. The same run exposed a deadlock
        in the checker -- a pipe the parent could not drain while the timeout
        could not kill a cygwin-built child -- so harness output now goes to
        a file and is capped.

        **21b.** `geosolid.v.pica` (transform plus one directional light in
        view space; normals scaled by 1/127 in the shader rather than widened
        to floats in the vertex buffer, which costs one instruction against
        nine bytes a vertex) and `georender.c`/`.h` (28-byte vertex, a solid
        baked into one linear-heap triangle list sorted by `TextureNumber` so
        it draws in one call per distinct texture, `GPU_CULL_NONE` because the
        GS had no hardware culling and nothing in the data forces a consistent
        winding). `geoview.c`/`.h` is the bring-up mode main.c's SELECT cycles
        to: scan `CARS\`, load a car, orbit it, step solids, toggle textures.

        `texsrc.c`/`.h` exists because `CARS\TEXTURES.BIN` is 15,300,536
        bytes and one car needs about 400 KB of it, while the port already
        holds 17.6 MB of UI bundles resident. It keeps only the 0x30300003
        info tables in memory (126,608 bytes for the whole car set), leaves
        the pixel blob on the card, and stages the two ranges one texture
        needs at upload time. The decode is still `texpack.c`'s, unchanged, so
        `tools/src/texpack_test.c` still covers it; `tools/texsrc_check.py`
        diffs the streaming reader against the whole-file one --
        **6 packs, 2 levels, 2952 textures, 0 differ**.

        Three defects, and the interesting thing is that a passing
        cross-check is what hid two of them:

        * **ST is not transposed.** `docs/formats/solid-geometry.md` said it
          was stored like XYZ -- a quad of four S, a quad of four T. It is
          two vertices to a quad with the odd one's pair mirrored,
          `(S_even, T_even, T_odd, S_odd)`, which is
          `eStripDataE::GetElementST0` (`0x0011c8b0`) read literally. Both
          decoders had the transposed reading and **agreed with each other
          for four sessions**, digest and all, because `geometry.c` was
          written from the document and the document from the Python. The
          transposed reading still yields plausible UVs, so the symptom was a
          car upholstered in smeared fragments of its own atlas rather than
          anything that looks like a parse error. The cheap tell is the S==T
          rate: 44.43% wrong against 1.68% right, over all 212,408 car
          vertices.
        * **The `0x11` filler scan has to step a whole entry on the two
          8-byte tables.** A byte scan cannot tell filler from a payload
          beginning `0x11`, and `TS50_C`'s first texture hash is
          `0x4342fd11`. The table shifts right one byte and every hash in
          that solid comes out 8 bits off -- silently, because a shifted hash
          is indistinguishable from a texture the packs do not have. 5 of the
          1,461 solids on the disc. Stepping 8 bytes cannot over-skip in
          turn: the pointer half of an entry is zero in all 4,646 entries on
          the disc. Verified against the sizes that the byte scan is still
          right for the header, the entry table and the packet blob.
        * **T counts down from the top row.** The shader needs
          `v = 1 - T * scale`, the same convention `uirender.c`'s
          `subtex_from_pixels` already uses over the same upload path.
          Without it the atlas is mirrored top to bottom -- grille on the
          sill, wheel hub mid-door.

        The mutation deck grew to **53 of 53 caught**: four ST mutations for
        the real layout, `table-filler-byte-at-a-time` for the filler rule,
        and `TS50` added to the fast file set because it is the only cheap
        file that can reach that rule. Both filler mutations deliberately
        keep calling both skip functions, since dropping a call leaves an
        uncalled static and then it is the compiler catching the mutation,
        not the cross-check.

        Two findings recorded rather than fixed, both out of scope here:
        **58 of the 132 texture hashes** the car geometry refers to are in no
        `0xb0300001` pack anywhere on the disc -- 729 of 8,114 strips, 9.0%,
        with `0x7b220ddf` alone on 13 cars. Only `0xece04847` = `WIPER01` has
        been cracked, and the busiest six survive a full `bhash_crack` sweep
        to six characters. And there is **no alpha blending**: glass draws
        opaque because the GS blend state has not been recovered. It is not
        vertex alpha -- all 212,408 car vertex colours have the alpha bit
        set -- so it is texture alpha plus a blend mode, and recovering it is
        more ELF work.

        Looked at on Azahar, which is the half a cross-check cannot do:
        `4DR_SEDAN`, `4DR_SEDAN02`, `911TURBO` and `AMBULANCE` are
        recognisably themselves, textures in the right places, smooth vertex
        lighting, clean untextured geometry with X. 11 screenshots,
        `19 textures cached, 0 missing`, exits cleanly.
22. [x] Sound: new 3DS DSP driver behind the recovered `bDriver`/`bSnd`
        interface. Split into three, because the asset side and the driver
        side fail in completely different ways:
    a. [x] Sound banks: the 30 `SOUND\*.MSH`+`.MSB` pairs (439 patches,
           6.6 MB of PS2 SPU ADPCM) transcoded to a 3DS-native DSPADPCM
           bank, with a reader in the port and a cross-check.
           `tools/audio_pack.py` -> 30 `.SBK`, 6.51 MB; `sndbank.c` reads
           them; `tools/sndbank_check.py` 908 lines 0 differ, worst
           re-decoded SNR 22.59 dB over all 469 channels, 20000 byte
           mutations 0 disagree. `docs/formats/sound-bank.md`.
    b. [x] The driver: `bSnd_*` over ndsp -- voice allocation, the
           volume/pan/pitch units recovered from the ELF, and the two
           tables the engine looks them up in.
           `bsnd.[ch]` + generated `bsndtab.c`; `tools/bsnd_check.py`
           12 scenarios, 5157 lines, 0 differ, 25/25 mutations caught.
           `docs/formats/sound-driver.md`.
    c. [x] Wired into the frontend, so menu navigation makes the sounds the
           disc recorded, and heard on Azahar rather than only diffed.
           `fesound.[ch]` carries the FrontendSoundEvent table from
           `0x002f30ac` and hangs off `BMenu::sound`, which `bmenu.c`
           already raised. Azahar: `Sound: 34 patches in 24 voices`, a
           stereo pair per press at 22042 Hz, voices retired every frame --
           and the sounds were heard.
23. [x] Camera (`Camera.obj`, `CameraMover.obj`)
        `camera.[ch]` is the whole of `Camera.obj`; `cammover.[ch]` is the
        base `CameraMover` plus `CM_ORBIT_CAR`, which is the one the car
        select and the replay orbit use. `tools/camera_check.py` 7 scenarios,
        1200 lines, 0 differ; 47 mutations, 40 caught, 7 equivalent with a
        written argument each, 0 unexplained. `docs/formats/camera.md`.

        The finding: half the velocity record is dead on the disc, not here.
        `SetCameraMatrix` copies CurrentKey over PreviousKey as its first act
        and then recomputes only the matrix and the three vectors, so all six
        scalar velocities are a word minus itself. Measured, not asserted --
        all 44 velocity records in the transcript print
        `scal 0 0 0 0 0 fov 0` -- and it is why three of the seven equivalent
        mutants cannot be caught by any test.

        Looked at on Azahar, and looking found a bug a passing cross-check
        could not: `C3D_FVec` is declared `w, z, y, x`, so `r[i].c[j]` is
        element `(i, 3 - j)` and the view matrix was being written with its
        columns reversed -- the eye stuck at the world origin, inside the
        car. The geometry viewer now drives the real Camera through a real
        mover, and `tools/run_azahar_geo.ps1` captures the zoom (held,
        released, and measured for creep: 0.011/255 against 1.009 for two
        frames of the idle spin), the acceleration limiter, and the elevation
        clamp. The jump table at `0x2950e0` also settled the pad signs: the
        mover listens to the DEBUG camera joystick events, not the CARSEL
        ones, and "up" asks for a negative vertical speed.

        Two things the disc does that the port keeps and task 28 will have to
        decide about: the rotation speeds and the zoom multiplier are per
        *frame*, not per second, so both run four times too fast at the 139
        FPS Azahar gives this build.
24. [x] Track/route system (`TrackRoute.obj`)
        `trackroute.[ch]` is the whole of `TrackRoute.obj`: the routes, the
        points, the twenty-one driving lines per point, the signposts, the
        manager and its two chunk hooks. `trackpath.[ch]` is the boundary it
        calls into. `tools/trackroute_check.py` 10 scenarios, 671 lines, 0
        differ; 53 mutations, 52 caught, 1 equivalent with a written
        argument, 0 unexplained. `docs/formats/track-route.md`.

        **The task text was wrong and this entry corrects it.** There is no
        `espEmptyLayer` spline format. *Espresso* is bware's live remote
        editor protocol -- `EspressoServer` at file `0x1a40c8`, the version
        handshake `Caffeine = %d, Espresso = %d` at `0x1a4142`, and an
        `EspressoFunctions` enum in mdebug whose members are
        `eEF_IsCaffeineRunning`, `EF_InitCommunication`, `EF_LoadWorld`,
        `EF_ReloadWorld`. It is an RPC protocol spoken to a PC-side editor,
        not a file format, and nothing on the disc is stored in it.
        `TrackRoute::UpdateToCaffeine` (`0x1b7de8`) pushes a route down that
        wire; its only caller is `TrackRouteEditor::Service`, dead in retail.
        Not ported. What the tracks actually carry is two chunks:
        `0x00034121` TrackRoutes and `0x00034122` Signposts.

        The finding: TrackRoutes are **memory images the loader never
        parses**. It casts the chunk bytes to `TrackRoute *` and registers
        the pointer, so the on-disc record is the in-memory layout with the
        1024-entry point table truncated to `NumPoints` -- stride
        `115752 - (1024 - NumPoints) * 112`, and no count field on either
        chunk. That forced the port's layout to be exact rather than merely
        compatible: `pNext`/`pPrev` are `u32` slots holding disc garbage that
        the manager overwrites, not host pointers, and `trackroute.h` carries
        a `sizeof` assert so a 64-bit host cannot quietly widen the record
        (it did, to 115760, and the harness caught it). The checker models
        every record as a byte image with accessors at the listing's own
        offsets for the same reason.

        Two shipped quirks kept, both mutation-flagged so nobody "fixes"
        them silently: `MovePoint` stores `pos->x` into `Elevation` and never
        reads `pos->z`, and `GetPosition` (3D) leaves its `w` lane unwritten
        because the VU0 macro ops read two uninitialised stack slots. Only
        the editor called either, so neither ever ran in a shipped build.

        Not runnable for real yet, and the reason is outside this object:
        `TrackPathCoordinate::UpdatePosition` (`0x1f5dd0`) needs
        `QuickSpline.obj` (`0x00227e98`) to turn a world position into a
        distance around the track, and `SetFirstAndLastPoints`,
        `SetDistances` and `TestSignpostConsistency` all route through it.
        `gTrackPathDistanceFn` is that seam: `NULL` on hardware, and in the
        harness a closed-form ramp built only from add/multiply/compare so
        the model reproduces it bit for bit. `QuickSpline` belongs to task 27.

## Phase 4 -- Car physics & gameplay

**Standing constraint for this phase: the HUD is two screens, not one.**
The user wants gameplay readouts split across the top and bottom screens
rather than stacked on the top one, to keep the view of the road clear --
the PS2 drew one 4:3 screen with everything on it and the 3DS top screen is
400x240.

**Decided (2026-09-21, by the user): the bottom screen takes the minimap,
lap/position and the objective text. The top screen keeps the speedo/tach
and the pursuit meter**, because those two are monitored continuously rather
than glanced at, and they belong in the same eyeline as the road. The
remaining candidate list is settled; do not re-open it without asking.

Design tasks 25-27's HUD as two surfaces from the start rather
than building a top-screen HUD and splitting it afterwards. `uirender.c` is
citro2d and is the natural home for the bottom-screen widgets; `georender.c`
is citro3d and owns the top.

25. [x] Car simulation (recovered car-state struct layout from `.mdebug`).
        **`CarState.obj` (`0x001b6170`) is done**; the rest of the object
        list is not. Ported to `carstate.{c,h}`, cross-checked by
        `tools/carstate_check.py` (10 scenarios, 653 lines, 0 differ; 63
        mutations, 56 caught, 7 equivalent, 0 unexplained), written up in
        `docs/formats/car-state.md`.

        Three things worth carrying forward. **The object has its own pi.**
        At `0x003219ec`/`0x003219f0` it holds `0x40490fd0`/`0x40c90fd0`
        where bMath -- and `float(pi)` -- hold `0x40490fdb`/`0x40c90fdb`.
        Substituting the library value is not cosmetic: `GetYawAlways`
        folds on `pi < rad`, and with bMath's value the exact half-turn
        lands on the boundary and stops folding. Reproduced bit-for-bit.

        **Two of the quadword operations are decorative.** WorldToCar3
        subtracts the pad and CarToWorldUnadjusted feeds a z, but
        `eMulVector3` forces w to 1, so neither can reach the result. They
        are kept because the object does them, and both are argued in the
        checker's `EQUIVALENT` list rather than quietly dropped.

        **`CARSTATE_SLACK`.** The two pointers are dereferenced, so they
        could not be narrowed to `uint32_t` the way TrackRoute's list links
        were. The layout assert carries `2 * (sizeof(void *) - 4)` as a
        term instead, so it still checks all ~40 offsets on a 64-bit host.
        The harness dirties by field rather than by byte pattern for the
        same reason.

        `DoSnapshot` (`0x001b6230`) is **not** ported -- it needs
        `ReplaySnapshot`.

        **Also done since:** `Engine.obj` + `Table`
        (`docs/formats/car-engine.md`, `tools/engine_check.py`; 8
        scenarios, 413 lines, 0 differ; 56 mutations, 54 caught, 2
        equivalent). **`CarTypeInfo.obj`**
        (`docs/formats/car-type-info.md`, `tools/cartypeinfo_check.py`; 4
        scenarios, 177 lines, 0 differ; 40 mutations, 40 caught).
        **`CarDriver.obj` plus `DriveTarget`'s layout**
        (`docs/formats/car-driver.md`, `tools/cardriver_check.py`; 5
        scenarios, 118 lines, 0 differ; 45 mutations, 45 caught).
        **`Steering.obj` + `TwoWheelAckermanSteering.obj`**
        (`docs/formats/car-steering.md`, `tools/steering_check.py`; 5
        scenarios, 873 lines, 0 differ; 44 mutations, 43 caught, 1
        equivalent). **`RigidBody.obj`**
        (`docs/formats/rigid-body.md`, `tools/rigidbody_check.py`; 10
        scenarios, 935 lines, 0 differ; 78 mutations, 76 caught, 2
        equivalent). **`Suspension.obj` plus `Wheel`'s layout**
        (`docs/formats/car-suspension.md`, `tools/suspension_check.py`; 10
        scenarios, 1108 lines, 0 differ; 68 mutations, 66 caught, 2
        equivalent). **`Wheel.obj`** (`docs/formats/car-wheel.md`,
        `tools/wheel_check.py`; 19 scenarios, 10693 lines, 0 differ; 154
        mutations, 144 caught, 10 equivalent, 0 unexplained).
        **`DriveTrain`** (`docs/formats/car-drivetrain.md`,
        `tools/drivetrain_check.py`; 18 scenarios, 492 lines, 0 differ;
        176 mutations, 173 caught, 3 equivalent, 0 unexplained).
        **`DriveTarget`'s methods**
        (`docs/formats/car-drive-target.md`,
        `tools/drivetarget_check.py` and the image-backed
        `tools/drivetarget_image_check.py`; 22 scenarios, 897 lines,
        0 differ; 262 mutations, 243 caught, 19 equivalent, 0
        unexplained on each).

        **Wheel's first mutation pass came back with twelve unexplained
        survivors, and that is the part of the slice worth carrying
        forward.** Six were real coverage holes, six were equivalent, and
        two of the mutations were themselves badly written and had to be
        rewritten before they meant anything. The sharpest finding is that
        **a comment claiming a case is covered is not coverage**: both the
        harness and the model said vx 0.4 with a spin of 1.25 put the slip
        at exactly zero and so reached `GuessGroundForce`'s zero-magnitude
        early-out. It does not -- `1.25 * 0.32f` is 0.399999976, so the
        guard was never reached at all, and the comment had twice been read
        as the reason that survivor could not be a hole. The holes, the two
        rewritten mutations and the six equivalence arguments are written
        out in `docs/formats/car-wheel.md` and in `CONTINUE.md`'s "What not
        to trust".

        `MaybeMakeSkids` is **not** ported -- it needs the `SkidMaker`, and
        it belongs to task 27 with the rest of the skid trails.
        `MaybeMakeSmoke` and `MaybeMakeTireSpew` are each a bare `jr ra` in
        the shipped image and are ported empty, with a note rather than a
        TODO.

        **The two seams Suspension calls through are wired but not
        installed.** `wheel.c` defines `gWheelFindDrivingSurfaceFn` and
        `gWheelExchangeZForcesFn`, and `wheel_install_seams()` points them
        at the real methods -- but nothing in `3DS Files/source/` calls it,
        so on the handheld they are still NULL. That is right for now,
        because no car is constructed yet, but **whichever slice first
        builds a car owes that call**, before that car's first
        `ResolveForces`. The seams are a port artifact and not something
        the image has: at 0x0019bdd4 and 0x0019c104 the PS2 build makes two
        ordinary `jal`s.

        **Corrected scope -- read this before planning the rest.** An
        earlier note in this task put the remainder at "178 functions,
        16680 bytes". That was wrong by an order of magnitude: the tally
        behind it matched only a narrow symbol pattern and missed most
        methods. Re-measured by demangling every symbol to its owning
        class, what is left is:

        | Class | Funcs | Bytes |
        |-------|------:|------:|
        | Car | 80 | 22876 |
        | ~~DriveTarget (methods)~~ | ~~28~~ | ~~8636~~ |
        | PhysicsCar | 16 | 8496 |
        | ~~Wheel~~ | ~~73~~ | ~~7112~~ |
        | Mellovator | 31 | 5420 |
        | ~~DriveTrain~~ | ~~38~~ | ~~4920~~ |
        | ~~RigidBody~~ | ~~47~~ | ~~4508~~ |
        | MellowMover | 13 | 3096 |
        | ~~Suspension~~ | ~~29~~ | ~~1944~~ |
        | ~~TwoWheelAckermanSteering~~ | ~~7~~ | ~~624~~ |
        | ~~Steering~~ | ~~4~~ | ~~116~~ |

        ~67.7 KB across ~366 functions when it was measured, roughly 19x
        the CarState slice. What is still open is the four unstruck rows:
        **~39.9 KB across 140 functions** -- Car, PhysicsCar, Mellovator
        and MellowMover.
        At the verification standard this repo holds -- exact port,
        independent model, transcript diff, mutation pass with every
        survivor argued -- that is several sessions, not one.

        **RigidBody and DriveTarget are prerequisites the task list never
        named.** Suspension, PhysicsCar and Car all need RigidBody;
        CarDriver needed DriveTarget's record, whose layout is now done
        and whose 28 methods are not.

        Suggested order, smallest and most independent first, each
        verified and committed on its own: ~~Steering +
        TwoWheelAckermanSteering~~, ~~RigidBody~~, ~~Suspension~~,
        ~~Wheel~~, ~~DriveTrain~~, ~~DriveTarget's methods~~ (all done),
        then Car, then PhysicsCar, with Mellovator and MellowMover last.

        **That order used to read "PhysicsCar, Car" and it was wrong.**
        `PhysicsCar::Move` (`0x00135c78`) calls three `Car` methods and
        reads seven `Car` offsets outside the embedded `CarState`, so it
        cannot be modelled against the `CarState`-only stand-in that
        DriveTarget used. Car has to come first. Checked in the
        disassembly rather than inferred, the same way DriveTarget's
        independence from Car was.

        **DriveTrain's mutation pass came back with eighteen unexplained
        survivors**, on a transcript that agreed with the model on every
        line -- which is the whole reason to run the pass: a clean diff
        says the two sides compute the same thing, not that the
        scenarios reach the code. Sixteen were real holes and are
        killed; two are argued in `EQUIVALENT`. Three shapes are new and
        are written out in `docs/formats/car-drivetrain.md` and in
        `CONTINUE.md`'s "What not to trust": a **fixture that agrees
        with itself** (swapping two globals the image ships at the same
        value changes nothing), a `<`/`<=` boundary that can only be hit
        by **feeding the computed value back in** rather than guessing a
        number near it, and a **search loop no fixture ever made work**,
        because every engine's torque curve crossed over on the first
        probe.

        **DriveTarget's methods are done.** `DriveTarget.obj` is real
        -- `.text 0x002086f8`, `0x24d0` -- but it is not all DriveTarget:
        seven `OBB` methods and the free function `bDoublesBack`
        (`0x00208fa0`) are in it too, which is why the object is 9424
        bytes against a DriveTarget tally of 8636. The copy constructor
        is emitted elsewhere again, at `0x001da210` in
        `CarCollisionDetect.obj`. The tally of 28 reconciles: 26 methods
        in the object, that copy constructor outside it, and the
        `_GLOBAL_$I$` static-init thunk at `0x0020ab48` -- 8636 bytes
        between them, so **26 functions**, all ported into
        `3DS Files/source/drivetarget.c` and ARM-compiled.

        **`Car` was not a prerequisite for it, and that was checked
        rather than assumed.** Thirteen of the twenty-six take no
        `Car *` at all; the other thirteen reach `Car` only through the
        `CarState` embedded at byte 64, which is ported. The only Car
        offsets these methods touch are 64 (passed straight on as a
        `CarState *`), 96 (`State.Position`) and 112
        (`State.Velocity`). The free functions are the same story:
        `IsPointAheadOfCar` (`0x001c0e30`) reads 96 and 112 and nothing
        else, `CalculateLookAheadDistance` (`0x001c0c20`) is
        `max(State.VelocityMagnitude * 2, 20)`, and
        `GetMaxLateralAcceleration(Car *)` never reads the car at all --
        it is a constant 30.0f in four instructions. A `Car` stand-in
        whose only live member is a `CarState` covered the whole class.

        Three are still blocked, and only these three: `DoSnapshot` on
        `ReplaySnapshot`; `Dump` on `Car::WorldToCar`, which tail-jumps
        to `CarState::WorldToCar(bVector2 *, bVector2 *)` at
        `0x001b6ab0` and carstate.c does not carry that one yet; and the
        `DrivingLocation` overload of `AddPointToTarget` on
        `DrivingLocation::IsClear`, which is
        `lw v0,0(a0); sltiu v0,v0,1` and is carried by a one-word
        stand-in until task 26 brings the class. Two out-of-bounds
        shapes in the shipped code are modelled rather than fixed:
        `GetAngle` clamps its index down to `NumPoints - 2` without
        clamping back up to 0, so a `NumPoints` of 0 or 1 reads
        `Points[-2]`, and `SetPoint`'s `bVector2` overload leaves the
        stack `bVector3`'s w untouched before a sixteen-byte
        `lqc2`/`sqc2` copy.

        **A survivor has two causes, not one -- this slice produced the
        second.** Every earlier slice's unexplained survivors meant the
        fixture never reached the branch. Two of DriveTarget's reached it
        exactly and the dump still printed the same numbers, because the
        branch's effect landed in fields that were zero on both sides.
        `bl-window-inclusive` runs one extra blend pass that clamps to 1
        and therefore moves nothing -- until the points are given a
        non-zero z, which `SetPoint3` zeroes whatever the blend is.
        `rs-inner-test-strict` needs `travelled == len[k]` exactly *and*
        `fadd(P[k], fsub(P[k+1], P[k])) != P[k+1]` at the same k; the
        separation goes in the pad, where `16777218 - 1` and
        `1 + 16777216` are both ties landing on 16777216. Written out in
        `docs/formats/car-drive-target.md` and `CONTINUE.md`.

        **This said two small things came before Car. It was one, and
        it is done.** `Graph` -- 8 bytes, two methods (`0x00187440`,
        `0x00187450`), wanted by four Car methods -- is ported to
        `3DS Files/source/graph.{c,h}`, cross-checked by
        `tools/graph_check.py`: 16 scenarios, 151 lines, 0 differ;
        25 mutations, 21 caught, 4 equivalent, 0 unexplained; written up
        in `docs/formats/car-graph.md`.

        The second, `CarState::WorldToCar` (`0x001b6ab0` and the
        `bVector3` overload at `0x001b6b40`), **was already ported** --
        by the CarState slice, as `carstate_world_to_car2` and
        `carstate_world_to_car3`, with three mutations against them and
        a paragraph in `docs/formats/car-state.md` about the quadword
        subtract in the 3D one. This entry was written off a symbol
        search of the ELF, and searching for `WorldToCar` does not find
        `carstate_world_to_car2`. **Grep the ported sources under the
        name the port would have given a function, not the name the ELF
        has, before calling it outstanding.**

        **And the same error was sitting one line below it.** This entry
        then said `DriveTarget::Dump` was still blocked on
        `Car::WorldToCar`. It was not. `drivetarget_dump` has been in
        `drivetarget.c` since the DriveTarget slice and reaches the
        transform the way the forwarder would --
        `carstate_world_to_car2(&car->State, ...)`, which is the `+64`
        written out -- and `docs/formats/car-drive-target.md` said so at
        the time. DriveTarget has two blocked methods, not three, and had
        two all along.

        So the lesson is not about one symbol. **A plan's "blocked on"
        list decays and the ported sources do not. Check the source
        before believing the plan, including when the plan is this
        file.**

        `Car::WorldToCar` is ported now regardless: it is one of the
        eighty and it is eight bytes, `j CarState::WorldToCar` with
        `addiu a0,a0,64` in the delay slot. `Car::IsCarToLeft` and
        `IsCarToRight` come with a later Car slice.

        **Two constants that are the same float cost a mutation.** The
        Graph epsilon is `0x358637bd`, which `1e-6f` also rounds to
        exactly, so the obvious mutation of the spelled-out
        `9.99999997e-07f` was a no-op that could never be caught. It was
        rewritten as one ulp up. **A float mutation has to be checked as
        bits, not as source text.**

        **Car is the hub, not the physics, and that is measured.**
        Eighty methods, 22876 bytes, `Car.obj` at `0x0012f150`
        (`0x5e1c`); six are emitted outside that object, including the
        eight-byte `Car::WorldToCar` at `0x00138e90`. The record is 2016
        bytes with one non-virtual base at offset 0, `bTNode<Car>` --
        **Car has no vtable**; the `__pure_virtual` the map shows against
        `Car.obj` belongs to the `CarDriver` / `CarMover` /
        `CarController` abstract bases that share the object.
        Thirty-four of the eighty call nothing outside the class and are
        pure state work; `Think` and `Drive` are among them because they
        are pure dispatch -- load `pCarController` (offset 40) or
        `pCarDriver` (44), read the (delta, fn) pair out of the vtable,
        jump. The rest reach about a dozen subsystems belonging to tasks
        26, 27 and 29. `SetMovementMode`'s physics arm is where
        `wheel_install_seams()` finally belongs -- it is what constructs
        the `PhysicsCar` that owns the `Suspension` and the four
        `Wheel`s.

        **Car's record is whole and its first code slice is closed.**
        `3DS Files/source/car.h` carries all 2016 bytes -- 72 offsets,
        each re-derived from a load or a store -- plus `RideInfo`,
        `DriverInfo`, `OverrideRenderingPosition`, `CarNode` and the four
        enums. `topology.h` came with it, layout only: Car embeds a
        `TopologyCoordinate` by value and its `TrackPolygonTable` is 128
        *pointers*, so an opaque 560-byte blob would have agreed with the
        wrong number on the host and the right one only on ARM. The ARM
        build has run: every `CAR_SLACK` term is zero there and
        `CAR_AT(f, n, k)` reduces to the console's raw offset.

        Eighteen methods are ported to `3DS Files/source/car.c` -- the
        seventeen that reach nothing outside Car, CarState and the two
        world clocks, plus `Car::WorldToCar`. `tools/car_check.py`:
        20 scenarios, 1871 lines, 0 differ; 82 mutations, 78 caught,
        4 equivalent, 0 unexplained. Written up in `docs/formats/car.md`.

        **"Makes no call outside the class" is not "can be written
        today", and the partition is 17 + 10 + 7.** Thirty-four of the
        eighty make no outside call. Seventeen are done; ten are pure
        vtable dispatch and wait on that seam; seven call only other Car
        methods whose callees reach a task 26/27 class. The arithmetic
        closing is the check that the three groups are a partition rather
        than three overlapping lists -- it is spelled out at the bottom
        of `car.c`.

        **`cvt.w.s` saturates by the sign of the source, and a C cast
        does not.** `CalculateDebugChecksum` is four instructions and it
        was the one function in the slice whose first transcript did not
        match. The R5900 gives `0x7fffffff` above 2^31 and `0x80000000`
        below -2^31; ARM's `vcvt.s32.f32` agrees; x86-64's `cvttss2si`
        returns `0x80000000` for both, and the C cast is undefined
        behaviour besides. So the conversion is written out rather than
        cast -- `camera_check.py`'s model function moved to the source
        side. **Where a port casts a float to an int, ask what the three
        targets do off the ends before trusting the cast.**

        **A fixture holding the value a mutation writes cannot see that
        mutation.** `stub-event-writes` makes `EventHandler` secretly set
        `bPoofed = 1`; it survived because the `[stubs]` fixture had set
        `bPoofed = 1` itself before snapshotting. A no-op fixture value is
        a blind spot, and only a mutation finds it.

        **A comment can be wrong in a way no test catches, until a
        mutation asks.** `car.c` claimed `1.0f / 4000.0f` rounds one ulp
        below the image's tick. It does not -- both spellings are
        `0x3983126f`. The mutation swapping them survived against a clean
        transcript because there was nothing to catch, which is what
        exposed the comment. The word that *is* different, `0x3983126e`,
        was not separated by any fixture either, so two boundary
        scenarios were added: 4000 ticks of the right word is exactly
        `1.0f`, and the blink's `<` and the honk's `<` fall on opposite
        sides of it.

        **Padding has to be asserted by width as well as by offset.**
        Shortening `_hole56` from 8 bytes to 4 changes nothing on this
        host, because CarState is 8-byte aligned here and the compiler
        pads the gap straight back; on ARM the alignment is 4 and the
        same edit slides the whole record. The mutation found it and the
        seven holes now carry `sizeof` asserts too.

        `drivetarget.h`'s stand-in `Car` is gone -- it includes `car.h`
        now -- which retires the include-ordering rule and moved
        `drivetarget_check`'s three Car offsets onto the real record's
        host slack (18, 48, 112 here; 10, 24, 64 on ARM).

        `car.h` names `CarTypeInfo` and `CarDriver` instead of including
        them: `cardriver.h` -> `drivetarget.h` -> `car.h` is a cycle, and
        with the include in place `cardriver.c` reached `struct Car`
        before `CarDriver` was defined.

        **A killed mutation pass strands its mutant, and a translating
        write corrupts the restore.** `drivetarget.c` kept
        `sr-count-signed` from a stopped run -- an equivalent mutant, so
        plain runs stayed clean and only the next `--mutate`'s PATTERN
        NOT FOUND saw it. And `camera_check`/`trackroute_check` read with
        `newline=""` but wrote with the platform default, which put CR
        CR LF on every line of three sources. Both are fixed in one
        place: every checker's `write_source` is `hostbuild.write_source`,
        which writes untranslated, parks the original as
        `<name>.<pid>.mutate-backup`, and has `build()` restore any whose
        process died. Tested with a child that hard-exits mid-mutant.

        **Build for ARM before calling a record done.** `wheel.h`'s layout
        assert was guarded with `#if __SIZEOF_POINTER__ == 4`, which meant
        neither toolchain compiled it -- and when the ARM build finally
        ran it failed. This port's `bVector4` is four-byte aligned where
        the PS2's was a sixteen-byte quadword, so a four-byte gap the PS2
        record has at 284 simply did not appear, and the handheld's Wheel
        came out 396 bytes. On the 64-bit host the pointer widening
        happened to cancel it exactly, so the model and the harness agreed
        on the wrong record. Every remaining class in this task has
        `bVector4` fields in it.

        **Car's second code slice is closed: the vtable seam, and
        fourteen more methods.** `vtable.{c,h}` is a registry from the
        image's own vtable address to the port's `{delta, index, fn}`
        entries, so a call site is written the way the image writes it --
        same slot, same delta -- and a harness can install a recording
        table at the real address. `vt_slot` aborts rather than return
        NULL, on six distinct refusals, and `car_check` runs each one as
        its own process. On top of it: the nine dispatchers,
        `GetCarSpaceBoundingBox`, `GetLastPenetrationTime` and
        `GetTrackedAcceleration`, both `CalculateDraftFactor`s, and
        `_GLOBAL_$I$fDraftFalloff`, which `car_check` runs in `mipsemu`
        and diffs word for word. 42 scenarios, 3864 lines, 0 differ;
        178 mutations, 169 caught, 9 equivalent, 0 unexplained. Written up in `docs/formats/car.md`.

        **Four ported static initialisers had never run.** Car's,
        RigidBody's, Wheel's and DriveTarget's `*_static_init` existed and
        nothing called them, so every Table and Graph they fill would have
        been zero on hardware. `sinit.{c,h}` is the image's `__main` walk
        over `__CTOR_LIST__` (`0x00314f78`, 109 entries), restricted to the
        ported entries and kept in list order, and `main.c` calls it first
        thing. `tools/sinit_check.py` holds each call to its list index
        and its symbol, and fails if any `*_static_init` in the source is
        not called exactly once: 6 mutations, 6 caught. The same walk
        showed that the slot-pool manager's constructor is `0x00240080`;
        the `0x00240070` this file and HANDOFF cited is the `$D$` beside
        it.

        **Five survivors, and all five were fixtures.** The draft's reach
        can be seen only through a rounding: `dot / dist` has to come out
        above 1. No single-axis fixture can produce that, because
        `sqrtf(a * a)` is `|a|`, so two diagonal cases were found by
        searching the model. Two more separate the groupings of the
        velocity's length and of the dot. The sum's self-skip is caught
        now that `c` moves, because a sum that counts `c` drafts from
        itself: 0 / 0.

        **The 34/46 split is over all eighty, and `WorldToCar` is in the
        46.** Rescanned for any `jal`, or `j` out of the body, to a
        non-Car symbol. Thirty of the thirty-four are ported, and two of
        the forty-six: `CalculateDraftFactor(Car *)` and `WorldToCar`.
        That is thirty-two of the eighty, 2316 of 22876 bytes. Seventy-four
        of the eighty are in `Car.obj`; the other six, `WorldToCar` and
        `PrintAbove` among them, were emitted in other objects.

        That leaves **36.7 KB across 108 functions** still to go: the
        rest of `Car` (48 methods, 20560 B), then `PhysicsCar`
        (16 / 8496), `Mellovator` (31 / 5420) and `MellowMover`
        (13 / 3096). The next Car slice is six methods whose outside
        callees are all ported -- `IsCarToLeft`, `IsCarToRight`,
        `GetRelativeCarPosition`, `GetPostCollisionYawControlBoost`,
        `IsDrifting`, and `ComputeFakeRPM` with its `smooth<float>` --
        plus `IsCarInFront`, which brings `bToPolar` with it. After that
        come `SetMovementMode` / `SetControlMode` with `PhysicsCar`, and
        with them `SetToPhysicsMode`, `SetFrictionBoost` and the
        `wheel_install_seams()` call.

        **Car's third code slice is closed: seven methods that call out
        into ported code.** `IsCarToLeft`, `IsCarToRight`,
        `GetRelativeCarPosition`, `IsCarInFront`,
        `GetPostCollisionYawControlBoost`, `IsDrifting` and
        `ComputeFakeRPM` with its `smooth<float>`, 1304 B, and `bToPolar`
        in `bmath.c` for `IsCarInFront`. 58 scenarios, 4238 lines, 0
        differ; 254 mutations, 238 caught, 16 equivalent, 0 unexplained.
        Thirty-nine of the eighty, 3620 of 22876 bytes, nine of the
        forty-six outside-call methods. Written up in
        `docs/formats/car.md`: the drift threshold is 1356 BAM one way
        and 1357 the other, `ComputeFakeRPM`'s top band reads the eight
        bytes past `RPMTable` (so the fake RPM heads for 0 from 80 up),
        and two tests that are invisible as shipped are made visible by
        poking the Graph's aliased array.

        That leaves **35.4 KB across 101 functions**: the rest of `Car`
        (41 / 19256), `PhysicsCar` (16 / 8496), `Mellovator`
        (31 / 5420), `MellowMover` (13 / 3096). **Plus two classes the
        count never had:** `PhysicsCar`'s constructor adds every
        component to a `PhysicsSystem` (`0x00192460`, ~1.2 KB) and
        builds an `Aerodynamics` (`0x001a4b58`, ~0.65 KB), and neither is
        ported. They come first. `SetMovementMode` is a seven-way jump
        table (`0x00292200`) of which four arms -- `TrafficCar`,
        `DeliveryMover`, `CopMover`, `BeltMover` -- construct task 26's
        movers.

        **`PhysicsSystem` and `Aerodynamics` are closed.** The system
        came with the EE ticker (`bticker.{c,h}`) that times its
        `ComputeAuxiliaries` walk, and with `p32.{c,h}`, which lets the
        image's 32-bit link slots hold pointers on the 64-bit host so the
        walk the checker runs is the walk the handheld runs.
        `physicssystem_check`: 12 scenarios, 739 lines, 0 differ; 62
        mutations, 61 caught, 1 equivalent. `aerodynamics_check`: 7
        scenarios, 107 lines, 0 differ; 74 mutations, 74 caught. Written
        up in `docs/formats/physics-system.md` and `aerodynamics.md`.
        IntegrateEuler is the only integrator the image calls; a system
        owns and destroys its components; `bGetTickerDifference` divides
        by 300 MHz, not 294.912. `ApplyForceInFrame` is checked for the
        first time, and `SetGroundEffect`, which the port lacked, is in.

        **The component vtables are closed.** `physcomp.{c,h}` installs
        the seven tables at the image's addresses -- RigidBody
        `0x002987e8`, Wheel `0x00298f20`, Suspension `0x00298fb0`, Engine
        `0x00297a78`, DriveTrain `0x00297a30`, the steering's
        `0x00298ff8` / `0x00299018` -- with the eight destructors, every
        operator new and delete, and `InitPhysics` / `ClosePhysics` with
        their ten slot pools. `physcomp_check`: 8 scenarios, 239 lines, 0
        differ; 47 mutations, 46 caught, 1 equivalent (Engine's dead vptr
        store). Written up in `docs/formats/physics-components.md`. A new
        component is zeroed by its pool; a destroyed one carries its
        base's vptr; `~SkidMaker` is `MakeNoSkid`, behind a seam until
        skids are ported. Ackerman's `DoSnapshot` is the one pending
        entry.

        **`PhysicsCar` is closed** but for `DoSnapshot`, with the three
        small modules `Move` reads: `race.{c,h}`, `cardamage.{c,h}` and
        `joystick.{c,h}`. `physicscar_check` is the first checker whose
        oracle is the image itself: `mipsemu` runs the shipped
        constructor, both integrators, `UpdateCar` and `Move` with every
        component method they reach, and the harness runs the port on the
        same records. 106 scenarios, 102908 lines, 0 differ; 263
        mutations, 257 caught, 6 equivalent, 0 unexplained. Written up in
        `docs/formats/physics-car.md`. Two older ports were wrong and
        their hand-written models agreed with them (GetLateralForce's
        curve scale is 12, and CheckTerrain's fifth argument is the
        terrain it refreshes), and a car sitting in gear divides 0/0 in
        the clutch split, which the EE answers with FLT_MAX.

        **`MellowMover` and its `Mellovator` are closed** but for their
        two `DoSnapshot`s. `mellowmover_check` runs the image the same
        way, on PhysicsCar's four records plus three synthetic ones: 39
        scenarios, 56080 lines, 0 differ; 346 mutations, 341 caught, 5
        equivalent, 0 unexplained. Written up in
        `docs/formats/mellow-mover.md`. The `.lit4` half-pi is one ulp
        above the nearest float, and an airborne level car divides 0/0
        in `bNormalize3To`, which now uses `ee_div`.

        That leaves **18.8 KB across 41 functions**, all of it `Car`'s
        (41 / 19256), plus three `DoSnapshot`s that wait on
        `ReplaySnapshot`.

        **Car's fourth code slice is closed: the movement and control
        modes.** `SetMovementMode` (`0x0012fd58`), `SetControlMode`
        (`0x0012fb50`), `SetToPhysicsMode` (`0x0012ff68`) and
        `SetFrictionBoost` (`0x0012fd38`), 1092 B, with `NullMover`,
        `NullController`, `NullDriver`, the `CarController` base,
        `CarCollisionBody`'s `SetupPhysicsPointers` and `SetToPhysicsMode`,
        and the five tables at the image's addresses. Task 26's four movers
        and four controllers are behind constructor seams that abort,
        naming the class, while NULL. `carmode_check` runs the shipped
        image as the oracle: 74 transitions, 27324 lines, 0 differ; 114
        mutations, 114 caught, 0 equivalent. Written up in
        `docs/formats/car-modes.md`. Both methods store the mode *before*
        the arm, which the stand-in constructors log; the first
        NullMover's `Driver` stays 0 until the first switch; and a
        SetFrictionBoost through the wrong type writes into the next pool
        slot, which only a check past the mover's end can see.
        `wheel_install_seams()` now runs at boot in `main.c`.

        **Task 25 stops here, at the physics boundary.** Forty-three of
        Car's eighty methods are ported (4712 of 22876 bytes). The other
        thirty-seven (18164 B) each reach a class another task owns, and
        they move to it: the constructor and destructor build the car's
        sound (`CreatePlayerCarSound`, `espSetAttributeInt`; task 29), its
        render info and `CarDamage`, its `CarCollisionBody` and its
        `PutFlatOnTrack` (task 27); the reset group reaches `tCopManager`
        and `Player` (task 26); force feedback drives the wheel's motors.
        Three `DoSnapshot`s -- PhysicsCar's, MellowMover's, the
        Mellovator's -- wait on `ReplaySnapshot`.
26. [ ] Race/event logic, cop AI, pursuit (roadblocks, spike strips) --
        `HotPursuitEvent` already seen in the `.mdebug` strings survey
        **Inherited from task 25:** the eight classes behind Car's
        constructor seams (`gTrafficCarCtorFn` .. `gCopDriverCtorFn` in
        `carmodes.h` -- set each at boot and change its `_SIZE` to
        `sizeof`), and Car's `ResetToRoutePoint`, `AssignAnimatedDriver`
        / `UnAssignAnimatedDriver` and the three AnimatedDriver methods
        behind `ChangeGear`'s seams, `DamageAbove` and `DamageCap`. Also
        three seams in `car.h` that Car's ninth slice left:
        `gCopManagerIsBeingPursuedFn`,
        `gAICarControllerGetCurrentDrivingLineSpeedFn` and
        `gDeliveryMoverSetDestinationFn`. `PleaseResetMeLater`,
        `GetDrivingLineSpeed` and `DeliverMeFromEvil` abort on them until
        they are set. **First
        slice: the player's input** -- `Joystick.obj` (0x00150a50 ..
        0x00152860: event nodes, the eleven scanners, the queue,
        `GenerateJoyEvents`), `ScannerConfigTable` (0x002dc6c0, 231 x 32
        bytes) generated from the image, a 3DS backend in place of
        `ReadRegularController` (0x0011d420) that fills the 32-byte
        `scePadRead` buffer from the HID, and `RealDriver` (640 bytes,
        26 functions) but for `DoSnapshot`.

        **The first slice is closed.** `Joystick.obj` is ported as
        `joyevent.{c,h}`, the pad ring as `joypad.{c,h}`, and the joylog's
        two accessors as `joylog.{c,h}`. `gen_scanner_tables.py` writes
        `scannertab.c` and `joyeventid.h` from the image. `joyhid.{c,h}`
        builds a DualShock 2 buffer out of the 3DS's buttons, so the port
        reads as type 121 and every shipped row works unchanged.
        `joystick_check`: 64,240 ops, 75,891 lines, 0 differ; 253
        mutations, 250 caught, 3 equivalent. `joyhid_check` presses every
        key and stick through the tables. Written up in
        `docs/formats/joystick.md`. `RealDriver` is ported but for
        `DoSnapshot`, with its seven steering Tables (a new
        `Table::InverseLookup`, the only one in the image) and
        `DoesJoystickHaveStiffThrottle`. Its fourteen calls into other
        tasks' classes go through seams that do nothing while NULL.
        `realdriver_check` runs the image as the oracle: 152,455 ops,
        41,163 lines, 0 differ; 122 mutations, 118 caught, 4 equivalent,
        0 unexplained. Written up in `docs/formats/real-driver.md`. The
        static constructor is `__CTOR_LIST__` [17] in `sinit.c`, and
        `main.c` installs `_vt$10RealDriver` at boot. The route editor's
        two hooks are live calls on retail, not dead code; the 0.6 that
        latches reversing is a literal, not the `BrakingSpeed` global
        beside it; and the analog e-brake doubles and *wraps*.

        **What RealController stands on is done** (Session 29,
        continued): `QuickSpline.obj`, `TrackPath.obj`, table.cpp's
        Average / PidError / Linear, and the AI's four route helpers
        (`airoute.{c,h}`). Each is checked against the image in mipsemu;
        see `quickspline.md`, `track-path.md`, `average.md` and
        `ai-route.md`.

        **The second slice is closed:** `TrackedController` and
        `RealController` (0x00224388 .. 0x002253fc) but for their two
        `DoSnapshot`s, and `DriveTargetRenderer`'s flag-off path.
        `main.c` installs both tables and sets `gRealControllerCtorFn`;
        `REALCONTROLLER_SIZE` is `sizeof`. So a REAL_CONTROL car now
        builds its RealDriver. `realcontroller_check` runs the image as the
        oracle: 14,096 ops, 25,318 lines, 0 differ, and 129 of 140
        mutations caught with 11 equivalent. Written up in
        `docs/formats/real-controller.md`. The image check found
        FillWithCurrentAcceleration's first test negated, in `drivetarget.c`
        and in `drivetarget_check`'s model both; both are fixed.
        `drivetarget_image_check` (every DriveTarget method run in
        mipsemu under the model's scenarios, STACK-W pads masked) then
        found StraightLinePredict's inline VU0 normalise dividing the
        pad lane too, which port and model had both copied across
        unscaled; fixed, with `fn slp divide` and two mutants. Seven of
        the eight seams remain: the four movers, and AIDriver,
        TrafficDriver and CopDriver.

        **The jump cam is closed (Session 37, commits ce37726, 351b187,
        ee33932 and 6f168b6).** The jump cam was the Player half of
        Car::FinishMovement's four seams. `previewroute.c` is
        PreviewRoute and IsJumpCamAvailable. `spline.c` and
        `trackcarcam.c` are Spline and TrackCarCameraMover.
        `playerzone.c` is ChangeCameraMover's types 15 and 16,
        RequestZone, ClearZone, ClearZoneSound and PlayerClearZone.
        `main.c` sets all four seams, the jump mover and the route's
        delete. The checkers have 0 differ:
        - `prevroute_check`: 2934 ops, 57 mutations caught.
        - `trackcarcam_check`: 6969 ops, 157 caught.
        - `playerzone_check`: 5283 ops, 197 caught, 1 equivalent.
        On Azahar a ramp gives zone 6 at 0.4 speed under the roadside
        camera, then zone 7, then the chase camera as the car lands, at
        30 FPS. Still seams, NULL in `main.c`:
        - ZoneFreezeCameraMover and ZonePreviewCameraMover (zones 1 and
          2 are a dead button);
        - the zones' samples;
        - RadialBlurOn and RadialBlurOff.
        Written up in `docs/formats/camera.md`.

        **The racer AI's first slice (11a) is closed.** `nearbycar.c`
        is NearbyCarList (BuildArray, ClearArray and the three
        lookups), DrivingInformation's Clear, and CalculateMaxAcceleration,
        CanICatchThisCar, DoWeCareAboutThisCar,
        GetCurrentCurvatureOfDrivingLine and HighlightDrivingLine.
        `drivinglocation.c` is DrivingLocation's methods, and
        `drivingchoice.h` the choice's record. `nearbycar_check` runs
        the image as the oracle, with only the belt mover's gravity
        stubbed (`gBeltMoverGravityFn`): 36 scenarios, 10,309 lines,
        0 differ; 99 mutations, all caught. Written up in
        `docs/formats/ai-driving-info.md`.

        **11b-1: DriveTarget is retail's.** The byte at 516 and its
        accessor, CalculateMaxSpeed's split, the corner from the car
        and EstimateScore's new walks, with the EE's two divides for a
        car at rest. `drivetarget_check` and its image check: 22
        scenarios, 993 lines, 0 differ; 288 mutations, 268 caught, 20
        equivalent. The 54 checkers that link `drivetarget.c` or
        `bvector.c` still have 0 differ. Next is 11b-2,
        DrivingChoice's small methods and the walk along the route
        (0x00241b88 .. 0x002455f8).
27. [ ] Track rendering/streaming, collision. Task 24's debt is paid:
        `QuickSpline.obj` and `TrackPath.obj` are ported (Session 29,
        continued), and `TrackPathCoordinate::UpdatePosition` measures
        through the spline as shipped. `gTrackPathDistanceFn` is now only
        `trackroute_check`'s closed form, and it is NULL on hardware.
        **Inherited from task 25:** Car's constructor and destructor (a
        `TopologyCoordinate`, a `TrackPathCoordinate`, the
        `CarCollisionBody`, `CarDamage`, `PutFlatOnTrack`), the per-frame
        `Move` / `BeginMovement` / `FinishMovement` (`0x00130200`,
        `0x001303a8`, `0x00130480`), `FindFlatOnTrackPosition`,
        `PutFlatOnTrack`, `ResetCore`, `ResetToPosition`,
        `DebugSetPosition`, `AverageAir`, `TriggerEvents`,
        `TriggerCarTerrainEffects`, and the render group: `InitRenderInfo`,
        `CloseRenderInfo`, `TriggerEffect` (behind `gCarTriggerEffectFn`
        now), `SwitchSkin`.

        **The first slice is closed: the collision surface.** It is written
        up in `docs/formats/topology.md`.
        - `Track.obj` (0x0014e7d0 .. 0x001509d4) is ported as `track.c`,
          `topology.h` and `track.h`. It carries the TopologyTree over the
          four chunks, 0x34130 .. 0x34133, and the 1024-slot pool of
          reference-counted TrackPolygons with its 101-at-a-time flush.
        - It also carries TopologyCoordinate: SetInterestBBox's three
          passes, GetElevation, HasTopology, SegmentIntersects and
          ConstrainToTopology. With them come the position markers
          (0x34146), GetTrackInfo over 0x34200 / 0x34201 (entry 54 cleared
          on load), the road noise, and `LoaderTrackGeometry` with its
          unloader.
        - `TerrainType.obj` is ported as `terraintype.c`. Its 33-entry
          table is `terraintypetab.c`, which `gen_terrain_table.py` writes
          out of the ELF.
        - `track_check` runs the image as the oracle, over a synthetic
          world and over TRACKB12's 15708 polygons: 13,557 ops, 9,736
          lines, 0 differ. Of 172 mutations, 170 are caught and 2 are
          equivalent, with 0 unexplained. No disagreement between the
          image and the port was found.
        - Not wired yet: the port has no LoaderTable, so nothing calls the
          loader outside the checker. Also not wired are the `InitTree`
          call in `EndGameFlowLoadingTrackSpecific` and
          TrackPolygonCollisionBody.

        **The second slice is closed: Car on the ground.** Car's
        `FindFlatOnTrackPosition` (0x00130c58) and `PutFlatOnTrack`
        (0x00130e90) are ported in `cartrack.c`. It is kept apart from
        `car.c` because `car.c` links into six checkers that have no
        topology. The `SetInterestBBox(bVector3)` wrapper (0x00134f28),
        which the compiler emitted in Car.obj, is in `track.c`.
        `track_check` checks them over a synthetic world with a gap on
        each axis, and over ninety cars set down on TRACKB12's road. It
        is now 14,753 ops, 11,231 lines, 0 differ, and of 209 mutations
        206 are caught and 3 are equivalent. The slope's BAM constant is
        65536 / 6.28, not 65536 / 2 pi, and that is kept. Written up in
        `docs/formats/car.md`.

        **The third slice is closed: the resets.** `ResetCore`
        (0x001312c0), `ResetToPosition`, `ResetToRoutePoint` (task 26's
        inherited one) and `DebugSetPosition` are ported in `carreset.c`.
        `ReplayManager::RegisterInterestingEvent` and
        `InvalidateInterestingEvents` are ported in `replay.c`, whose
        header now has the manager's 116 bytes and ReplaySnapshot's 332.
        `carmode_check` runs them after its transitions. It uses its
        stand-in controllers and drivers, a twelve-point looping track path
        loaded through `LoaderTrackPath`, and a five-snapshot replay. That
        is 19 resets, 32,797 lines, 0 differ. The checker's whole pass is
        188 mutations, 185 caught and 3 equivalent, with 0 unexplained.
        The image leaves two stack words in the state, both fourth lanes.
        The checker poisons the stack two ways and masks just those.
        The port tests `pReplayManager` for NULL where the image does not,
        because the replay is not ported yet. No disagreement between the
        image and the port was found. Written up in `docs/formats/car.md`.

        **The fourth slice is closed: the air under the car.**
        `AverageAir` (0x00133e48) and `BeginMovement` (0x001303a8) are
        ported in `cartrack.c`, which makes Car 51 of 80 methods.
        `track_check` runs them over the flat world: 16,149 ops, 11,790
        lines, 0 differ. Of the slice's 62 mutations, 60 are caught and 2
        are equivalent. The first 209, rerun since, are still 206 caught
        and 3 equivalent. Every
        wheel's contact goes through `WheelMatrix[0]`, and that is kept.
        No disagreement between the image and the port was found. Written
        up in `docs/formats/car.md`.

        **The fifth slice is closed: the step.** `Car::Move`
        (0x00130200), `ChangeGear`, `CalculateNewCatchupMultipliers` and
        `UpdatePosition` are ported in `carmove.c`. That makes Car 55 of
        80 methods, 7992 of 22876 bytes. Four pieces came with them:
        - `timer.{c,h}`: Timer, moved out of `collisionbody.h`, and
          `Timer::SetTime`.
        - `player.c`: `NumPlayers` and `pPlayersByNumber`.
        - `difficultyinfo.{c,h}`: the 744-byte table and chunk 0x34b00's
          loader.
        - `race.h`: the whole 192-byte `RacingCar`.
        `carmode_check` runs seventy steps after its resets, over
        GLOBALB.BUN's own difficulty table: 35,405 lines, 0 differ. Of the
        slice's 79 mutations, 77 are caught and 2 are equivalent. The
        AnimatedDriver's three methods and `espSetObjectPosition` are
        seams that abort if reached unset. Nothing sets `pAnimatedDriver`
        yet, and the image only ever stores zero in `pCaffeineObj`. No
        disagreement between the image and the port was found. Written up
        in `docs/formats/car.md`.

        **The sixth slice is closed: Car's calls out.** Six methods that
        make one outside call each are ported in `carrace.c`:
        `GetDistanceAndSpeed`, `FixBlownTires`, `TriggerTireBlowOut`,
        `PleaseResetMeLater`, `GetDrivingLineSpeed` and
        `DeliverMeFromEvil`. `DynamicCollisionBody::GetDistanceAndSpeed`,
        a 12-byte stub on the disc, came with them. That makes Car 61 of
        80 methods, 8576 of 22876 bytes. Five calls are seams in `car.h`:
        the cop manager, the AI's controller and the DeliveryMover abort
        if reached unset, and the effect and the sound are skipped.
        `carmode_check` runs a scenario for them after the steps: 35,602
        lines, 0 differ. All 43 of the slice's mutations are caught. No
        disagreement between the image and the port was found. Written up
        in `docs/formats/car.md`.

        **The seventh slice is closed: the terrain's effects.**
        `TriggerCarTerrainEffects` (0x00131db8, 1872 bytes) is ported in
        `careffects.c`. That makes Car 62 of 80 methods, 10448 of 22876
        bytes. `BaseCarSound::TriggerSplash` is a seam in `car.h`, skipped
        when NULL. `carmode_check` runs 54 cases after the sixth slice's:
        35,875 lines, 0 differ. Of the slice's 107 mutations, 104 are
        caught and 3 are equivalent. The listing found one disagreement
        with the port: Car's `NumTimesSkidding` is four bytes, a count a
        wheel, not one `int32_t`. It is fixed, and every checker still gives
        0 differ. `mipsemu.py` now has the R5900's `madd`, `maddu` and
        `pminw`. Written up in `docs/formats/car.md`.

        **The eighth slice is closed: the clock object.** The video mode,
        the real clock and the world clock (0x001992a0 .. 0x001995d8) are
        ported in `realtime.c`, with all eighteen of their globals at the
        image's initial values. Four globals that `engine.c`,
        `drivetrain.c`, `world.c` and `cammover.c` had defined moved there.
        `main.c` prepares and advances both clocks as MainLoop does with
        no race. `realtime_check` is new, with the image as the oracle: 20
        scenarios, 1,044 ops, 3,470 lines, 0 differ. Of its 86 mutations,
        84 are caught and 2 are equivalent. No disagreement between the
        image and the port was found. Written up in
        `docs/formats/realtime.md`.

        **The ninth slice is closed: VClip.** All of `VClip.obj`
        (0x001c5d90 .. 0x001ca008, 54 functions) is ported in `vclip.c`
        except `DoSnapshot`, which waits on ReplaySnapshot. That covers
        the polyhedron, its Voronoi planes, the feature codes, memory
        images, the transform, the clips, the checks and the walk. The
        Caffeine plots reach the editor through the new `espresso.{c,h}`
        seams. `vclip_check` is new, with the image as the oracle: 47
        scenarios, 11,890 ops, 22,389 lines, 0 differ, over 2,001 VClips
        and 938 single checks. Of its 281 mutations, 280 are caught and 1
        is equivalent. No disagreement between the image and the port was
        found. Written up in `docs/formats/vclip.md`.

        **The tenth slice is closed: polyhedra.cpp.** All of it
        (0x00205058 .. 0x00206440) is ported in `polyhedra.c`: the Rect,
        Cube and Wafer polyhedra the collision bodies hand to VClip, the
        loader and unloader for the disc's collision volumes, Find and
        MoveCenterOfGravity, the list's globals, and the four debug tests.
        `polyhedra_check` is new, with the image as the oracle: 55
        scenarios, 15,907 ops, 64,560 lines, 0 differ, over all 15,708 of
        TRACKB12's polygons and the disc's 43 volumes. Of its 184
        mutations, 172 are caught and 12 are equivalent. No disagreement
        between the image and the port was found. Written up in
        `docs/formats/polyhedra.md`.

        **The eleventh slice is closed: the bodies that do not move.** The
        first part of `CollisionBody.obj` is ported in `collisionbody.c`:
        the NumberAllocator, Init and Close, the stats, the base class and
        its sorted list, StaticCollisionBody, TrackPolygonCollisionBody,
        the witness's constructor, destructor and bookkeeping, the three
        tables and the static initialiser and destructor. Car's two
        CarCollisionBody methods are in `carcollisionbody.c`.
        `collisionbody_check` is new, with the image as the oracle: 21
        scenarios, 743 ops, 2,945 lines, 0 differ. Of its 184 mutations,
        175 are caught and 9 are equivalent. No disagreement between the
        image and the port was found. Written up in
        `docs/formats/collision-body.md`.

        **The twelfth slice is closed: DynamicCollisionBody.** The body
        that moves is ported in `collisionbody.c`: its constructor and
        destructor, the bounding volumes, UpdatePosition, BeginMove, the
        two interpolations and Backup, the RigidBody and PhysicsSystem
        pass-throughs, GetLocalCollisionBodies, MaybeCreateWitnesses,
        CreateTrackPolygonCollisionBodies, TrackPolygonCheck, the inline
        methods and its table. `collisionbody_check` runs it on bodies
        whose four pure slots are logging stubs: 39 scenarios, 1,039 ops,
        8,733 lines, 0 differ. Of its 329 mutations, 318 are caught
        and 11 are equivalent. No disagreement between the image and
        the port was found. Written up in
        `docs/formats/collision-body.md`.

        **The thirteenth slice is closed: CarCollisionBody.** The car's
        body is ported in `carcollisionbody.c`: its constructor and
        destructor, the getters, Move, ApplyImpulse, AddDamage,
        AnimateCollisionReaction, AreCollisionsEnabled, the mass and
        inertia, IsBlinking, the constants, the inline accessors and
        its table. RaceCoordinator's pointer, state and
        IsReplayDemoMode came with it, in `race.c`. The damage, the
        pursuit, the driver's animation, the rumble and the force
        feedback are five seams. `collisionbody_check` runs it on
        stand-in Cars, with Car's four calls and the five seams logging
        on both sides: 55 scenarios, 1,211 ops, 30,218 lines, 0 differ.
        Of its 483 mutations, 462 are caught and 21 are equivalent. No
        disagreement between the image and the port was found, but the
        port's AI demo test subtracted in int32, which overflows at
        INT_MIN. It subtracts unsigned now, as the image does. Written
        up in `docs/formats/collision-body.md`.

        **The fourteenth and fifteenth slices are closed: the contacts.**
        The rest of `CollisionBody.obj` is ported in `contact.c`, the two
        slices together because the witness's tests build a Contact. That
        is InitContact and CloseContact, RemoveContacts, the sort and
        `bList::AddSorted`, and all of Contact: its constructor,
        FindContactTime, Crowbar, Resolve, the contact point and normal,
        the planar contact point, the point velocity, the denominator term,
        CollisionImpulse, and its inline destructor and delete. The
        witness's FindWaferNormal, GetCollision, BeginCollision and
        TestForContact came with them. `Collision`'s constructor and
        AddImpulse are two seams that abort if reached unset.
        `collisionbody_check` runs the contacts on bodies whose nineteen
        contact slots are logging stubs: 81 scenarios, 1,572 ops, 35,426
        lines, 0 differ. Of its 646 mutations, 622 are caught and 24 are
        equivalent. CollisionImpulse's friction divides by the slide,
        which is zero for a car dropped straight onto flat ground; the
        EE's division makes that 0 where IEEE makes it NaN, so the port
        calls `ee_div`. No disagreement between the image and the port
        was found. Written up in `docs/formats/collision-body.md`.

        **The sixteenth slice is closed: `Collision.obj`**, in
        `collision.c`, with World's two GetDistanceToClosestPlayer
        overloads in `world.c`. That is InitCollision and CloseCollision,
        the constructor and destructor, AddImpulse, Update, End,
        GetTerrainType, IsTwoCarCollision, GetCollidingCars,
        IsPlayerInvolved and IsSmokeableInvolved. DoSnapshot waits on
        ReplaySnapshot. The sound's CreateSample, ReleaseSample and
        PlayScrape and the particles' TriggerEffect are four seams that
        are skipped when NULL. `main.c` fills the witness's three
        Collision seams with it. `collision_check` runs the image's pool
        and Collision in mipsemu against the port: 15 scenarios, 3,587
        ops, 6,859 lines, 0 differ. Of its 131 mutations, 121 are caught
        and 10 are equivalent. The scrape's particles look as if they get
        the faster body's velocity, but both calls are on body 1 and the
        test compares a length with itself, so they always get body 1's.
        ROAD's scrape range is 50 to 50, and the port divides with
        `ee_div` there. No disagreement between the image and the port
        was found. Written up in `docs/formats/collision.md`.

        **The seventeenth slice is closed: World's timestep**, in
        `worldstep.c`, with bList::Sort in `blist.c`. That is the clock
        (SetTimeScale, ResetTimeScale, SetWorldPaused, Begin- and
        EndPause, UpdateWorldPaused, IsWorldPaused, GetTimestep), the car
        table (BuildCarTable, GetCarByNumber, GetCarByDriverNumber,
        CarListCheckFlip, AddTrafficCar), the two Randoms,
        GetDATToClosestPlayer, FlushCollisions, Calculate- and
        VerifyDebugChecksums, DoTimestepMove, DoTimestepCollisions and
        DoTimestep. The twenty calls the step makes into classes the port
        does not have are seams in `world.h`, skipped when NULL, apart
        from FinishMovement and PlaceNewCar, which abort. Smokeable::Break
        and DeleteFarAwaySmokeableCollisionBodies are `smokeable.h`'s.
        `world_check` runs the image's World.obj in mipsemu against the
        port: 24 scenarios, 2,173 ops, 12,963 lines, 0 differ. All 200 of
        its mutations are caught. GetTimestep's wait for a replay's frame
        is capped at `min.s 0.3, max(x, 0)`, and the shake test is made
        again before each car's rumble. No disagreement between the image
        and the port was found. Written up in `docs/formats/world.md`.

        **The eighteenth slice is closed: World's constructor and
        destructor**, in `worldinit.c`, with the rest of the record in
        `world.h`. That is the constructor and the destructor,
        DebugDisplay, the collision prediction's four recorders and
        UpdateAIDebugRendering, which leaves only DoSnapshot and
        DoPointerSnapshot of World.obj's methods. OBB's methods came
        with them, in `obb.c`, with the front of WorldObject in
        `worldobject.h`. So did the bPNode pool, in `bplist.c`, and
        GetVectorOnTrack, in `track.c`. The constructor's eleven Init
        calls and the destructor's eleven Close calls are seams, skipped
        when NULL. The TrafficTeleporter's constructor and destructor and
        Car's destructor are seams that abort when they are needed and
        unset. `world_check` runs the image against the port: 32
        scenarios, 2,742 ops, 15,110 lines, 0 differ. All 328 of its
        mutations are caught. `bslotpool_check` has a bPList scenario
        (47/47 mutations caught), and `track_check` puts 31 points on
        the ground (273 caught, 5 equivalent). The port departs from
        the listing in one place: UpdateAIDebugRendering dereferences
        the car of a driver number that no car has, and the port passes
        NULL. Written up in `docs/formats/world.md`.

        **The nineteenth slice is closed: Car::FinishMovement**, in
        `carfinish.c`, which makes Car 63 of 80 methods and 12,456 of
        its 22,876 bytes. World's timestep calls it for every car
        through `gCarFinishMovementFn`, and `main.c` sets it now. The
        Player's ClearZone, RequestZone, IsJumpCamAvailable and
        CleanUpJumpCam are four seams that abort when unset;
        `player.h` names the three fields it reads.
        `g_DisableAutoReplay` is in `car.c` and
        TrackPathCoordinate::ResetPosition in `trackpath.c`.
        `carmode_check` runs it in 105 cases, with the topology's
        answers scripted: 36,396 lines, 0 differ. Of its 88 mutations,
        82 are caught and 6 are equivalent. No disagreement between the
        image and the port was found. Written up in
        `docs/formats/car.md`.

        **The twentieth slice is closed: Scenery.obj's data half**, in
        `scenery.c`: the loader and unloader, the three finds, the
        visible zones' lookups, the debug tables, CreateFacadeMatrix,
        FlipObjectsOnBackwardsTrack and the statics
        (`__CTOR_LIST__[21]`). eModel::Init and its deleting destructor
        are seams that abort when unset. `scenery_check` loads all 122
        of TRACKB12's sections and its 23 zones against the image: 17
        scenarios, 3,450 ops, 16,724 lines, 0 differ. Of its 79
        mutations, 77 are caught and 2 are equivalent. Written up in
        `docs/formats/scenery.md`.

        **The twenty-first slice is closed: the scenery cull**, in
        `scenerycull.c`, `eframe.c` and `eview.c`: ClassifyAABB and
        IsBoundingBoxVisible, the tree and brute-force culls,
        DrawAScenery, the sections a view draws, DoCulling,
        StuffScenery, SetupSceneryCullInfo and eDisplayFrame's loop over
        the views, Ecstasy.obj's frame malloc and the table of eViews.
        eModel::Render is a seam that aborts when unset.
        `scenerycull_check` runs it over made-up sections and all of
        TRACKB12's: 9 scenarios, 7,273 ops, 46,687 lines, 0 differ. Of
        its 148 mutations, 147 are caught and 1 is equivalent. Written
        up in `docs/formats/scenerycull.md`.

        **The twenty-second slice is closed: `eView.obj`**, in `eview.c`
        and `eviewmatrix.c`. It covers:
        - CalculateViewMatricies, CreateViewMatricies, CalculateH and
          SetupMatrixPacks, which make the matrices and H that the cull
          reads;
        - the local-to-clip products, the Z-sort bias, the pixel sizes,
          the screen position and the light context;
        - the movers' attach and detach and the view modes;
        - the static constructor's cameras and views.

        `eview_check` runs the image against the port: 12 scenarios,
        2,103 ops, 15,454 lines, 0 differ. Of its 153 mutations, 152 are
        caught and 1 is equivalent. The check found that `camera.c`
        negated the eye where the disc subtracts it from zero, which gave
        the default eye -0 in x and y. That is fixed. Written up in
        `docs/formats/eview.md`.

        **The twenty-third slice is closed: the track on the screen**,
        roadmap step 1, in `trackview.c`, `emodel.c` and `main.c`'s track
        mode. TRACKB12's 1,135 solids are linked in place, its 122
        sections and 23 zones load, eModel::Init connects 2,487 of 2,494
        models, and the ported cull's picks draw through `georender` in
        the engine's order: opaque first, then the attach loops'
        RenderingOrder buckets and the alpha sort, with the GS's blend
        equations and alpha test. Seen on Azahar at seven stops of
        route 1. It needed `eMathInit`, which fills the identity matrix
        the road is drawn with; a 4x command buffer; and
        `tools/check_3dsx.py`, after `bFixATan1`'s INT32_MIN path linked
        a relocation Azahar refuses. Written up in
        `docs/formats/track-render.md`.

        **The twenty-fourth slice is closed: the LoaderTable**, the first
        half of roadmap step 2, in `bchunkload.c`, `esolid.c` and
        `emodel.c`. That is ResourceFile's load half (both walks,
        LoadChunks, UnloadChunks and PostLoadFixup), the two tables of 31
        slots, LoaderSolidList and its unloader, eSolid's table fix-ups,
        eFixUpTables, and the rest of eModel.obj's list half. The slots
        whose object is not ported are guards that hand the chunk to
        `gUnportedLoaderFn`. The track viewer loads TRACKB12 through
        `load_chunks` now; seen on Azahar. `loadertable_check` runs the
        image against the port: 27,856 ops, 41,730 lines, 0 differ. Of its
        102 mutations, 100 are caught and 2 are equivalent. Written up in
        `docs/formats/loader-table.md`. Left of step 2: TexturePack.obj's
        loader in slot 2, and the `InitTree` call.

        **The twenty-fifth slice is closed: the rest of roadmap step 2.**
        TexturePack.obj is ported in `texturepack.c`: its loader and
        unloader are slot 2, and its in-memory half has GetTextureInfo,
        the flipbooks and UpdateTextureAnimations. The two track-flow
        steps are ported in `trackflow.c`: EndGameFlowLoadingTrackSpecific
        and BeginGameFlowUnloadingTrackSpecific. The End calls InitTree,
        InitPhysics, the collision pools, the visible zones and the paths
        and routes.

        The viewer loads in the game's order now:
        1. GLOBALB's and INGAMEB's packs;
        2. `eDisableFixUpTables` set;
        3. TRACKB12;
        4. TEX12TRACK;
        5. TEX12LOCATION;
        6. the End, which runs the one eFixUpTables.

        It unloads through the Begin. Seen on Azahar: the track draws
        textured by the game's own lookups, and 49 names get the default,
        as the disc predicts. All 46 flipbook frames upload. After the
        free, no solids, models or packs are left.

        `texturepack_check`: 5,452 ops, 11,201 lines, 0 differ; of its 97
        mutations, 95 are caught and 2 are equivalent. `trackflow_check`:
        16 scenarios, 694 lines, 0 differ; of its 74 mutations, 73 are
        caught and 1 is port-only. Written up in
        `docs/formats/texture-pack.md` and `docs/formats/track-flow.md`.
        CONTINUE.md has what is next, and how far it is to a playable
        demo.

        **The twenty-sixth slice is closed: the sky dome and the sun's
        data**, the first part of roadmap step 3. Sky.obj is ported whole
        in `sky.c`. SkyLoader takes SKYDOME and SKYDOME_ENVMAP out of the
        scenery and into two models of its own. StuffSky draws them first
        in each view, with the Z writes off, as eDisplayFrame does. The
        data half of Sun.obj is ported in `sun.c`: LoaderSun and
        UnloaderSun in slot 14, and SunTrackLoader and SunTrackUnloader,
        which find the five SUN textures and give them order 7. The End
        and the Begin call all four directly now.

        Seen on Azahar: SKYDOME is drawn by StuffSky, the sun chunk is
        version 2 at (-16384, 800, 6000), and all five sun textures are
        found. The mountains and the clouds show behind the canyon.
        `sky_check`: 45 scenarios, 1,159 lines, 0 differ; of its 78
        mutations, 76 are caught and 2 are equivalent. Written up in
        `docs/formats/sky-sun.md`. Left of step 3: StuffSun and
        StuffSunGlare, WeatherMan and the fog, and the RainSystem.

        **The twenty-seventh slice is closed: the sun's draw.**
        StuffSun and StuffSunGlare are ported in `sundraw.c`, with the
        glare's globals and the 15 SunZBuffers. ePoly and its
        constructor are in `epoly.c`, and ePoly::Render is a seam.

        On the 3DS, `trackview.c`'s `render_epoly` draws each quad
        through `georender_draw_quad`. It uses the poly's blend, the main
        target's alpha test, and no depth test. `trackview_read_depth`
        fills the SunZBuffers from the last frame's depth buffer, before
        the clear, as the GS's 16-bit Z.

        Seen on Azahar: the sun draws at alpha 0 where it is above the
        frame. In the new `track-sun` shot, it draws faded by a full
        count. `sun_check`: 91 scenarios, 2,680 lines, 0 differ; of its
        115 mutations, 114 are caught and 1 is equivalent. Written up in
        `docs/formats/sun-draw.md`. Left of step 3: WeatherMan and the
        fog, and the RainSystem.

        **The twenty-eighth slice is closed: the weather and the fog.**
        WeatherMan.obj is ported whole in `weatherman.c`: the weather
        lists, LoaderWeatherMan and its unloader in slot 29, and
        WeatherManQuery, with eView::GetWeatherQuery's cache by
        `eFrameCounter`. The fog half of EcstasyE.obj is in `efog.c`:
        CreateFogPalette's four modes, fpow, the CSM1 remap, and
        eAttachDepthIntoAlpha and eAttachFog, whose fog sprite is a seam.

        On the 3DS, `trackview.c` makes the palette before the frame and
        lays it on with the PICA's fog, over a W-buffer. Each depth's
        fraction is what the GS's ALPHA_1 would leave for the alpha the
        image's depth palettes give that depth's Z.

        Seen on Azahar: TRACKB12's 20 fog regions load, and FOG<MAIN>
        leaves 90.6% of the frame at 4000 and in the sky.
        `weather_check`: 75 scenarios, 4,368 lines, 0 differ; of its 89
        mutations, 85 are caught and 4 are equivalent. Written up in
        `docs/formats/weather-fog.md`. Left of step 3: the RainSystem.

        **The twenty-ninth slice is closed: the rain, and with it step
        3.** The shipped image draws no rain, snow or storm. Its four
        rain entry points are `jr ra ; nop`, and are ported as such in
        `rain.c`, called directly where the seams were. The RainSystem,
        the RainSplashes and the storm have no live caller. Nor does
        SoundScape::UpdateWeather, so the fog is the weather query's one
        live reader.

        `rain_check` proves this from the image: every reference to that
        code and data in the loaded sections, 30 of them, is expected.
        It runs the entry points against `rain.c`: 31 calls, 0 differ, 5
        of 5 mutations caught. Written up in `docs/formats/rain.md`.
        Step 4, a car on the track, is step 6 of CONTINUE.md's road now:
        task 36 goes first.
28. [ ] New3DS perf: core2 for background streaming/decode, gate higher
        fidelity behind the New3DS speedup flag
        **Re-scoped by the user on 2026-10-03:** New 3DS mode in full,
        and a smooth 30 FPS race on the New 3DS. Only the optimizations
        the New 3DS needs to hold 30 go in. Nothing is done for the Old
        3DS alone; it keeps booting and gets what the New 3DS work gives
        it. CONTINUE.md's step 13b has the four slices, taken right after
        the HUD (step 13):
        - **13b-1:** the real clock. Feed PrepareRealTimestep the measured
          frame time in place of `BOOT_DT`; retail's own clamp then runs
          the race in real time down to 20 FPS. Pace the race at 30.
        - **13b-2:** a frame profiler by phase, plus the console's model,
          speedup, memory grant and cores logged at boot.
        - **13b-3:** New 3DS mode checked part by part at runtime: 804 MHz
          and L2, the 178 MB extended memory (the heap sized from the
          grant), and core 2 for the streams where the profile says so.
        - **13b-4:** only the cuts the profile demands, keeping retail's
          look. Any cut that changes the look goes to the user first.

## Phase 5 -- Polish

29. [ ] Save data, options menus, final sound mix pass
        **For the full game (task 36):** the saves go to the SD card in
        the memory card's place, with retail's save game layout and
        screens: Phils Load Save, the Autosaver, the BootAutoLoader and
        the options. The demo ELF has all of it; check each against
        `docs/retail_audit.txt` before porting it.
        **Inherited from task 25:** the sound half of Car's constructor,
        and `BaseCarSound::TriggerTireBlowOut` and `TriggerSplash` behind
        `gBaseCarSoundTriggerTireBlowOutFn` and
        `gBaseCarSoundTriggerSplashFn`; the rumble and force-feedback group,
        `MaybeRumble`, `MaybeCameraShake`, `DoWheelForces`,
        `CalcForceParameters`, `StartForceImpact`, which the 3DS has no
        motors for; and every `DoSnapshot`, which waits on
        `ReplaySnapshot`.
30. [ ] Split-screen/multiplayer scope decision (HP2 supported split-screen;
        not committed to yet -- decide once single-player core is solid)
31. [ ] Final CIA packaging + Old3DS/New3DS compatibility pass
        (Since 2026-10-03 the New 3DS is the target, task 28. Since
        2026-10-05 it is the only one, the user's call: an Old 3DS stops
        at boot with a message (6ac29d1), and the pass checks only that.)

## Asked for during the port

Raised by the user mid-session; kept here so they do not get lost between
phases.

32. [x] Stretch the frontend to the 3DS aspect. The PS2 drew a 4:3 screen
        and the 3DS top screen is 400x240 (5:3), so the screens as shipped
        left 20 px of nothing down each side. `UIView` now carries a
        `scaleX` and a `scaleY` instead of one `scale` and both origins are
        0, so 640x480 maps to 400x240 by stretching: 400/640 across,
        240/480 down, everything 25% wider relative to its height. Only the
        final quad is stretched -- object positions, hit boxes, the menu and
        the scroll demo all still work in the 640x480 space the disc
        authored, so nothing downstream had to change. The movie plane is a
        bitmap object like any other and comes along with it. Milestone test
        re-run: PASS, 13 screenshots, the menu art runs edge to edge.
33. [x] `ChallengeBeACop` is unregistered, and the nine others with it.
        It is in the blurb table (`bscreens.c:336`, blurb 10014,
        `BMODE_BE_A_COP`) and the flow changed to it -- the Azahar log
        showed `flow change ChallengeBeACop 1` followed by
        `flow unregistered ChallengeBeACop` -- so the name resolved and no
        screen was registered for it. That is worse than a screen that does
        nothing: `ChangeToScreen` (`0x00167850`) clears `pCurrent` before it
        looks the name up, so the flow is left with no current screen at
        all, and the top screen goes black until BACK.
        The whole set is gathered now rather than found one at a time on the
        emulator. Ten names the port's own C can reach had no row --
        `Challenge`, `ChallengeBeACop` and `View Event Tree` from the two
        Mode Selects, and the seven Options pages (`Audio Options`,
        `Joystick PreConfig`, `Display Options`, `Phils Load Save`,
        `NameEntry`, `Credits`, `Language Options`) -- and all ten are in
        `kScreens[]` now on `bgf_plain_screen_callback`, an empty function:
        the screen draws, the highlight moves, BACK works, A does nothing.
        Their chunks were already in `FRONTB.BUN`, so nothing new is loaded,
        and the bottom panel says what they are (`kPlainScreenNote`) instead
        of sitting empty, since a plain screen has no blurb.
        `python tools/screen_registry.py --check-port` is the standing
        check: it diffs `kScreens[]` against the ELF's
        `FlailerScreenConfigList` row by row and lists every screen name a
        source file mentions and the table does not carry. Both lists are
        empty; 18 of the disc's 62 configs are registered. Milestone test
        re-run: PASS, 14 screenshots, 22 textures cached, 0 missing, and
        `beacop` shows "You're The Cop" drawn instead of a black screen.
        Survey table in `docs/formats/frontend-screens.md`.
34. [x] Move the menu description to the bottom screen. The blurb --
        `SCROLLING_TEXT`, driven by `tAnimatedBlurb` -- is about ten pixels
        tall in the disc's 480-line frame, which is five on the 3DS top
        screen and unreadable. It is now skipped on the top screen
        (`uirender_hide_object`, along with the `WHITEOUT_BAR` it is wiped
        out with) and the bottom screen is given over to it: a panel with
        the screen's name along the top under the frontend's red rule, the
        line itself wrapped and centred in the game's own FONT_A at a
        19 px line height, and the controls along the bottom. The line is
        read back out of the object every frame rather than caught at the
        `setBlurb` hook, because `tAnimatedBlurb` also prints into it
        directly at the end of its wipe; a change crossfades, which is the
        port's stand-in for a wipe that now animates an off-screen object.
        New in `uirender`: `uirender_draw_wrapped` / `uirender_wrap_height`
        / `uirender_line_height` (word wrap in target pixels, sharing
        `draw_glyph` and the help-character path with the screen renderer,
        but *without* the double-`ScaleX` bug, which a wrap width cannot
        live with), `uirender_object_string` and `uirender_hide_object`.
        Written up in `docs/formats/flailer-ui.md`.
35. [x] No console on the bottom screen. It cannot share the screen with
        citro2d -- `consoleInit` switches the bottom screen to RGB565 while
        citro3d presents BGR8 into the same framebuffer, and the first run
        of the panel came out as two half-width copies of itself under a
        teal dither. The console is gone; the three bring-up overlays it
        carried go to `sdmc:/nfshp2_debug.txt` (opened `"w"`, so each boot
        replaces it) one line per slot and only when the line changes, and
        the two viewer modes get the same panel with their controls on it.
        The only console the port still creates is on the *top* screen, in
        the three paths that are about to exit.
36. [ ] **The full game, from the retail disc.** The user put the PAL
        retail disc in `PS2 Files/Full Game/` on 2026-09-27 and asked for
        the full game rather than the demo: every track and car, the whole
        frontend and saving. `docs/retail.md` has what differs.

        **The first slice is closed: the names carried over.**
        `tools/mdebug.py` reads the demo's procedure table, and
        `tools/retail_match.py` names 9,333 of its 9,669 procedures in
        the stripped retail ELF. `--audit` writes `docs/retail_audit.txt`:
        of the 1,617 functions the port cites, 1,148 are the same, 139
        differ only in offsets, 301 changed and 29 are unmatched.
        `tools/retail_layout.py` maps 91 classes' moved fields into
        `docs/retail_layout.txt`. `zdir_names.py --retail` names 369 of
        the retail directory's 406 entries, and `zdir_extract.py --retail
        --only` takes pieces of the disc into `extracted-retail/`.

        **The second slice is closed: the retail model.**
        `tools/retail_model.py` runs `SLES_507.31` in mipsemu under the
        demo's names, with `e.code`, `e.data` and `e.field` for demo
        addresses and offsets. `track_check` and `loadertable_check` run
        two scripts through one harness: what the port follows as retail
        has it on the retail image and data, the rest on the demo's.
        TrackInfo is retail's 164 bytes (`SignpostGracePeriod` at 128).
        The LoaderTable is retail's 30 slots, with no PhysPredict and
        HeliSheet taking `0x80034800`. `zdir_extract.py --decompress`
        writes a track's `.LZC` out as its expanded `.BUN`, which is how
        the port ships the tracks.

        **The third slice is closed: TrackRoute's retail pass.** Retail's
        Signpost is 12 bytes, with an `AIHint` int32 at 8. The loader
        divides by 12, and InitTrackRoutes marks each DontTake sign's
        route with Flags bit 2. `trackroute_check`'s model follows
        retail, with a scenario over retail TRACKB12's and TRACKB21's
        routes and signs.

        **The fourth slice is closed: the texture pack's retail pass.**
        The header is 84 bytes, with a 64-byte file name, and the pack
        148. GetTextureInfo takes a third argument, AttachTextureTable no
        longer looks each record up, and retail's rename and swap of
        texture names are ported. `texturepack_check` runs on the retail
        image over twelve retail texture files: 131 of 132 mutations
        caught, 1 equivalent.

        **The fifth slice is closed: the difficulty table's retail
        pass.** `DifficultyInfo` is 992 bytes: the demo's position-ratio
        statics moved into it, and the skill distributions gained a set
        for races with no cops. `difficulty_check` is new: it runs the
        loader on the retail image and holds the layout to 68
        instructions in retail's eleven readers. All 24 mutations are
        caught.

        **The sixth slice is closed: the solid list's retail pass.**
        eFixUpTables looks up a ninth texture and fills its palette with a
        falloff ramp (retail's `0x00103260`), and ReconnectSolid gives a
        solid with flag 0x20 a random start. `loadertable_check` runs the
        solid list, the fix-ups and eModel on the retail image, over
        retail's disc: 137 of 139 mutations caught, 2 equivalent.

        **The seventh slice is closed: the sun's retail pass.** Retail's
        Z buffer is 24 bits: StuffSun counts a Z under 2 in 32-bit rects
        that it moves onto the target, draws its first layer at z 1 over
        the sky alone and the rest at the render target's `MaxZ`. The
        glare draws a fixed record that LoaderSun fills, timed in
        RealTimer's ticks. `sun_check` (154 of 154 mutations caught) and
        `sky_check` (93 of 95, 2 equivalent) run on the retail image.

        **The eighth slice is closed: retail's data on the card, in the
        viewer and the frontend (step 4).** The card holds retail's files
        alone. The track viewer takes a track number and names its files
        from it, and ZL/ZR unload one track and load the next: TRACKB12,
        21, 31, 41, 61 and 11 were walked on Azahar. Retail's Flailer
        objects carry a 24-byte name at +16, and `bui.c` and
        `flailer_dump.py` read either layout per object. The title
        screen's logo is in `GLOBAL\DYNTEX.BIN` on retail, which the port
        now loads. The sound banks are retail's, and `audio_pack.py`
        transcodes SPU ADPCM to DSPADPCM frame by frame with no loss:
        every sample of both discs comes back exact, where the old
        re-encode's worst was 22.6 dB.

        **The ninth slice is closed: the boot movies.** The title
        screen plays retail's EA logo and intro off the card with their
        sound, and START skips the intro. `mv3.c` is a native MV3 decoder
        from retail's code, bit-exact to the image on `mv3_check` (92 of
        94 mutations caught, 2 equivalent). `avimovie.c` streams the AVI
        and paces it by the console's tick. The sound is SPU ADPCM stereo
        at 43,617 Hz, whatever its header says. French plays
        `NFSINTRO_FR`, from retail's table. The demo's baked `.M3V` path
        is gone. The movies fill the top screen, as the user asked, with
        the EA TRAX credit kept in frame.

        **The tenth slice is closed: Car's constructor and
        destructor, from retail.** `carinit.c` has `Car::Car`
        (`0x00130a48`), `~Car`, `CloseRenderInfo` and
        `CarReflectEventHandler`, on the demo's layout. Retail's four new
        fields go at the end of `car.h`. Retail's weighted
        `FindClosestPoint` and its `ResetPosition` are in `trackpath.c`.
        The sound, CarDamage, the render info and the event manager are
        seams. `carinit_check` runs the retail image: 247 scenarios, 0
        differ, 168 of 169 mutations caught, 1 equivalent.

        **The eleventh slice is closed: CarRenderInfo, from retail.**
        `carrenderinfo.c` has `Car::InitRenderInfo` (`0x0011dc80`), the
        constructor (`0x0011e860`), the destructor, SwitchSkin,
        UpdateCarReplacementTextures, CreateCarLightFlares and the
        culler's InitPart. They sit on `epositionmarker.c` and on
        GetSkinInfo, GetUsedCarTextureInfo and four eModel methods.
        `carrenderinfo_check` runs the retail image: 321 scenarios, 0
        differ, 161 of 163 mutations caught, 2 equivalent.
        `docs/formats/car-render-info.md`.

        - [ ] `CarRenderInfo::Render` (`0x00120ef8`) and the culler's two
              passes, so that a car draws. The plan is in CONTINUE.md.

        The rest is CONTINUE.md's "The road to the full game": the rest
        of step 6 (Render, so that a car draws), then the retail pass over what is ported (step 10), the
        full frontend (step 16), the saves (step 17) and every track and
        car (step 18).

### The retail frontend

Asked for on 2026-09-28. The user sent seven PCSX2 photos of the retail
PAL frontend and asked for the port's frontend to match them. It comes
ahead of step 6's second slice, which waits on `wip/carrenderinfo`.

- [x] **Retail's title screen.** A select stops the intro and the title
      comes to rest. After four seconds, PRESS START blooms with the
      copyright line. Movie planes draw nothing without a movie.
      `bootflow_check` runs retail's own `TitleScreen` and catches 25 of
      25 mutations.
- [x] **The boot's loading and language screens.** LOADING first, from
      retail's `LoadGlobalChunks`, then `Language Options Pre FE` (PAL),
      then the movies. Retail's `LOADING_FRONTEND` moves on by its load
      callbacks. Retail's `LanguageOptionsScreenBase` serves both
      language screens. `bootflow_check` runs them on the retail image
      and catches 56 of 57 mutations. The remaining one is equivalent.
  - [ ] The speech banks (`hookLoadSpeech` only logs).
  - [ ] The French `LOADING` and `NFS_LOGO_ALPHA` art on the host
        (`hookSwapLogoArt` only logs).
  - [ ] `Language Options`' `tSlideOnScreen` (`0x001ee918`).
- [x] **`BootAutoload` and `ConsiderStartDemoMode` in full.** Retail's
      `BootAutoLoader` and the classes under it (`memcard.c`) check and
      load `settings.db` from `sdmc:/NFSHP2/SAVES`. The popups they speak
      through (`bpopup.c`), with `RenderTextIntoGroup`'s word wrap, draw
      on Azahar. Retail's `ConsiderStartDemoMode` knows the demo disc's
      attract mode and the replay. `bootflow_check` runs all of it on the
      retail image: 46 scenarios and 147 mutations, of which 144 are
      caught and 3 are equivalent.
  - [ ] `ANY_BUTTON_PRESSED` (message 24) from `JoyHandler`.
  - [ ] `OverwriteFred`'s six calls into the frontend. Nothing reads the
        loaded `Fred` yet.
  - [ ] `MemcardSaver`, and the Options screen's manual load.
  - [ ] `DemoModeReplay`'s internals.
  - [ ] `bmenu.c`'s menus recolour the demo's way; retail's
        `FlailerMenuItem` recolour is only the popups'.
- [x] **The main menu's background movie.** MV3's inter frames, bit-exact
      to retail in `mv3_check`, paced by `MoviePlayer::Update`'s rule.
      Retail's `StartMovie`, `UpdateMovie` and `StopMovie` (`0x0016ce30`,
      `0x0016d028` and `0x0016d0a0`) on `PANELMOVIE`, run on the image by
      `bootflow_check`. The main menu's movie loops on Azahar, and
      Cops On's and Options' play.
  - [x] **Full speed.** A worker on another core decodes ahead of the
        picture, and the decode and the conversion are faster, to the
        same values. The main menu runs at 59 FPS on Azahar and its movie
        at 30 fps. Real hardware, and an Old 3DS's core 1, are unmeasured.
  - [ ] `StartDemoMode`'s track, from `BuildDemoTrackList`.
- [x] **The highlight's echo.** A large faded red copy of the current
      item's label, now and then. It is the bloom, `tHighlightAnimation`
      on `ANIMATING_MENUITEM`, which every screen authors off the bottom
      edge. Retail's `CopyFlailerText` copies the item's position, scale
      and Z with its text. The port's copied only the text, so no bloom
      had ever shown. `bui_copy_text` is the whole copy now, and the main
      menu builds, animates and releases retail's four members.
      `bootflow_check`: 190 mutations, 187 caught, 3 equivalent. On
      Azahar a red "Hot Pursuit" grows out of the label and fades, every
      four seconds.
- [x] **Hide "Unlocked Easter Egg"** on the main menu. Retail's
      `NewMainMenu` hides the group (`0x74e404b4`) when it is built and
      again when it is torn down, after `TheEasterEggs`' `Start` and
      `Stop`. Its BACK is a silent veto. `bootflow_check` runs retail's
      `Callback`, `HandleEvent` and `OnTick` on the image
      (`RetailMainMenu`).
  - [ ] `TheEasterEggs`' 78 codes (`0x0031d828`), and `OnTick`'s three
        seconds of "Unlocked" when one is entered.
  - [ ] Attract mode from the main menu (`OnTick`'s
        `ConsiderStartDemoMode`), with message 24 resetting its timer.
        It waits on `StartDemoMode`'s race.
  - [ ] `MakeChallengeCarsAvailable` and `RaceParameters::InitWithDefaults`
        in the constructor.
- [x] **The main menu's highlight bars.** Reported on 2026-09-28: after
      going into a menu and back, the two white bars stayed around Hot
      Pursuit while the highlight moved. The port's `NewMainMenu` had no
      `OnHighlight`, so they never moved on the main menu at all.
      Retail's `OnHighlight` (`0x00216938`) and `HighlightMenuItem`
      (`0x00216880`) now move them to the item's `MI_n_MASK` and set its
      blurb, which shows on the bottom panel.
  - [x] `OnHighlight`'s first call, the bloom's `SetCurrentMenuItem`,
        with the echo.
- [x] **The demo disc's code is out.** Asked for on 2026-09-28: the port
      is the full game, where `TheDemoDiscManager.bActive` is always 0.
      `demodisc.c`, `EXIT_DEMO_DISC`, the loading slideshow, the
      one-movie title, `StartDemoDiscGame` and the demo timeout are
      gone. Attract mode stays, and so does event 2 with its row, so no
      event renumbers. The unused VP6 decoder is deleted too.
- [x] **The jukebox and its EA TRAX box.** "Fever for the Flava" plays
      from the main menu on, as it does on the PS2
      (`docs/formats/jukebox.md`).
  - [x] The music. `jukebox.c` is retail's `cJukeboxPlayer`,
        `cJukeboxCartridge` and `sound::jukebox`, checked by
        `jukebox_check`. `jbstream.c` streams `SOUND\JukeboxM.JBC` off the
        card onto ndsp channel 22, and bsnd gave up that voice. It started
        late at first, only on the Mode Selects, because gameflow's own
        `hooks.jukebox` was never set.
  - [x] The EA TRAX box. It is retail's `tNewSongMonitor`
        (`songmon.c`, `songmon_check`). For five seconds after a tune
        starts, it shows the title, artist and EA GAMES TRAX bottom left,
        over the Help button.
  - [x] Its strips, and every WHITE16X16 strip and mask with them, drawn
        with the GS's MODULATE (`docs/formats/flailer-ui.md`, "Colour").
        Before that, the box's charcoal bars were a faint haze.
  - [ ] The Options' Jukebox screen (the playlist and its volumes).
  - [ ] Real hardware: the stream thread's timing is only seen on Azahar.
- [x] **You're The Cop.** Cops On's second item. Retail's
      `BeACopChallengeSetup` (`0x001b6c68`) is `bsetup.c`, with Players,
      Skill Level and Setup, the arrows class (`0x0024a690`) and
      `tfeSineWave`. `setup_check` runs retail's on the image: 359 ops,
      0 differ; 145 mutations, 142 caught, 3 equivalent. On Azahar the
      arrows pulse either side of the skill, the level wraps, and the
      lines are retail's (`docs/formats/frontend-setup.md`).
  - [ ] `tHelpMenu`: `SetHelpOverride` only logs the four lines.
  - [ ] `mPolice` from Fred+32. The port reads `gf->copsOn`, as
        `bscreens.c` keeps it; the Mode Selects' state belongs in the Fred
        image.
  - [ ] The three car calls in the constructor and SELECT
        (`MakeChallengeCarsAvailable`, `0x00183ec0`'s preload,
        `SetupRaceParametersAfterRaceSetup`), with car select.
- [x] **The Setup screen.** Catch-up, traffic and damage, with arrows on
      the current row and the movie behind. "Be The Cop Setup" is
      `BeTheCopSetup` (`0x001b9248`) on `RaceSetupBaseClass`
      (`0x001b8390`), screen `d1eadbca`, with `tScrollingMenuList`, all in
      `bsetup.c`. `racesetup_check` runs retail's on the image: 398 ops,
      0 differ; 86 mutations, 82 caught, 4 equivalent. On Azahar it
      matches the photo, and RIGHT on Traffic goes to Moderate
      (`docs/formats/frontend-setup.md`, "Be The Cop Setup").
  - [ ] `SetClipToPoly`: `uirender.c` keeps the poly and does not clip.
  - [ ] The other race setups (Single Race, Free Run, Lap KO, Track KO),
        on the same base with other rows.
- On 2026-09-29 the user moved the port back to cars and racing: the
  items below wait unless a race needs them.
- [ ] **Car select** (`bcarsel.c`, `docs/formats/car-select.md`).
  - [x] SC-1, retail's SelectCarScreen and CarSelector as logic and 2D:
        the make's logo and the badge, the row of car icons, "Cars
        Unlocked" and "NFS Points", the unlock box and the popups.
        `carsel_check` runs retail's on the image: 7282 ops, 0 differ;
        201 mutations, 196 caught, 5 equivalent.
  - [x] SC-2, the car on a lit turntable: the camera, the car and its
        reflection, the light, the cover and the platform. `selcam_check`,
        `fecar_check` and `carsel_check` agree with retail; on Azahar it
        matches the user's photo 7 at 60 FPS.
  - [x] SC-3, the nebula behind it.
    - [x] SC-3a, the effect system's data (`acidsys.c`,
          `docs/formats/acidfx.md`): the pools, LoaderTable slot 6, the
          lookups and copies, and the auto emitters. `afx_check` runs
          retail's on the image: 9295 ops, 0 differ; 175 mutations, 172
          caught, 3 equivalent.
    - [x] SC-3b, TriggerEmitter, DoTimeStep and UpdateInterestPoints
          (`acidsys.c`), with hermite_basis. `afx_check`: 14885 ops,
          0 differ; 313 mutations, 310 caught, 3 equivalent. World's
          step runs WorldEffects' on the device.
    - [x] SC-3c, RenderEffects and its draw on the device (`acidsys.c`,
          `georender_draw_sprites`). `afx_check`: 20624 ops, 0 differ;
          394 mutations, 390 caught, 4 equivalent. The race's smoke
          draws on Azahar at 29.4 FPS.
    - [x] SC-3d, the car select's nebula (`bcarsel.c`). `carsel_check`:
          8364 ops, 0 differ; 29 nebula mutations, 28 caught, 1
          equivalent.
- [ ] **The briefing.** "You're The Cop", with its button list over the
      track's picture.
