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
    d. [x] No DSP firmware (Session 98). A card without
           `sdmc:/3ds/dspfirm.cdc` has no ndsp, and main.c gives
           `bsound_init` no driver; the race's sound setup then read
           through NULL (`bsnd_patch_id`, unmapped reads on Azahar, a data
           abort on a 3DS). `bsound.c` makes no driver call without one: no
           patch, no voice, no channels, a base pitch and volume of 0, no
           chained part. `bsound_check`'s no-driver run (212 ops, no model)
           passes only with no driver call and no voice; 126 mutations,
           124 caught, 2 equivalent, 0 unexplained.
           On Azahar, `run_azahar_lobby.ps1 -Consoles 2 -Race -NoDsp`
           (no firmware on either card): both copies logged "Sound: ndsp
           unavailable, running silent" and PASS (racing), track 11 with
           4 drivers, GO on seed ceab451a, no unmapped reads.
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
26. [x] Race/event logic, cop AI, pursuit (roadblocks, spike strips) --
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
        `bvector.c` still have 0 differ.

        **11b-2: DrivingChoice's small methods and the walk.**
        `drivingchoice.c` has the small methods, the side tests
        (IsEnoughRoom, the fix-up, GetPreferredSideOfCar), the walk
        (AdvancePoint, GetRoutePointsToUse, the road block's list) and
        FillUpDriveTarget with what it calls. Race::GracePeriodIsActive
        is in `racecore.c`. `drivingchoice_check` runs the image as the
        model: 45 scenarios, 25,798 lines, 0 differ; 240 mutations, 239
        caught, 1 equivalent. Written up in
        `docs/formats/ai-driving-choice.md`. Next is 11b-3,
        BuildDriveTarget and BuildDriveTargetAroundCar.

        **Closed 2026-10-20, at the launch prep.** The race and event logic,
        the cop AI and the pursuits are all in, as retail's (TASKS 73 and
        74), and the user played the game through on a 3DS on 2026-10-19.
        Two inherited pieces are not ported: AnimatedDriver (the driver's
        own animations, and R/C Car's big head in TASKS 50b), whose seams
        stay empty and the race runs without (ported since, TASKS 83,
        2026-10-21), and DeliveryMover, whose
        `car_deliver_me_from_evil` nothing in the port calls.
27. [x] Track rendering/streaming, collision. Task 24's debt is paid:
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

        **Closed 2026-10-20, at the launch prep.** Every track draws,
        streams and collides: TASKS 36's step 18, and the user's playthrough
        on a 3DS on 2026-10-19. What is left of the track's drawing has its
        own tasks: the speed (46), the bridge and the blink (47 and 64) and
        the rigid animations (76).
28. [x] New3DS perf: core2 for background streaming/decode, gate higher
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
        - **The user's playtest on the device, 2026-10-09: heavy scenes
          lag.** On the desert track, near the end, where the yellow neon
          signs point left and the dust/fog effect is, the race slows
          down. It is playable, but more than expected, and a little worse
          with the helicopter in the chase. There are no logs (they were
          wiped). To do soon: run the timing build there (13b-2's
          profiler) and see what costs -- the models in view, the dust and
          fog sprites (`acidsys.c`), the signs, the helicopter's model and
          its light -- then cut by the profile, keeping retail's look.

        **Closed 2026-10-20, at the launch prep.** The New 3DS is the only
        target (6ac29d1), and a race holds 30 FPS on it outside the heaviest
        scenes. Those are TASKS 46.

## Phase 5 -- Polish

29. [x] Save data, options menus, final sound mix pass
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

        **Closed 2026-10-20, at the launch prep.** The saves are on the SD
        card with retail's layout and screens (`memcard.c`, TASKS 52), the
        options are retail's (TASKS 71), and the sound is in full
        (CONTINUE.md's step 14). The rumble and force-feedback group stays
        out, as the 3DS has no motors, and `DoSnapshot` came with the
        replays (TASKS 72).
30. [x] Split-screen/multiplayer scope decision (HP2 supported split-screen;
        not committed to yet -- decide once single-player core is solid)
        Decided on 2026-10-13 at the user's word: "There is no split
        screen or anything on here, so no player two is possible". No
        split screen; Player Names hides Player 2 (TASKS 54).
        Multiplayer is TASKS 37's, one console each.
31. [ ] Final CIA packaging + Old3DS/New3DS compatibility pass
        (Since 2026-10-03 the New 3DS is the target, task 28. Since
        2026-10-05 it is the only one, the user's call: an Old 3DS stops
        at boot with a message (6ac29d1), and the pass checks only that.)
        The HOME Menu banner, sound and icon are TASKS 66's.
        - The Old 3DS message passed on the user's 3DS (2026-10-19).
        - The release candidate (2026-10-20, built from 926d1e1):
          the disc-made icon, banner and siren, version 1.0.0, and
          GPL-3.0 for the port's code (`LICENSE`), all the user's
          picks. The release build was checked for test-only
          changes: none. Open until the user says it is good to go
          and names the GitHub repo; then the v1.0.0 tag and the
          push.

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
36. [x] **The full game, from the retail disc.** The user put the PAL
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

        - [x] `CarRenderInfo::Render` (`0x00120ef8`) and the culler's two
              passes, so that a car draws. Done in CONTINUE.md's step 6
              (`carrender.c`).

        The rest is CONTINUE.md's "The road to the full game": the rest
        of step 6 (Render, so that a car draws), then the retail pass over what is ported (step 10), the
        full frontend (step 16), the saves (step 17) and every track and
        car (step 18).

        **Closed 2026-10-20, at the launch prep.** The full game runs from
        the retail disc: every track and car, the frontend a player reaches,
        and the saves. The user played it through on a 3DS on 2026-10-19.
        What retail still changes is TASKS 75 and 76, and 72h-2c.
        76 and 72h-2c are done since (Sessions 145 and 147).

37. [ ] **Local Wireless (multi-card) play.** Asked for on 2026-10-07. Up to
        eight 3DS consoles (two in the first ask, eight since
        2026-10-14), each with the game and the retail files on its own
        SD card, race each other over local wireless.
        - Each console loads the track, the cars, their textures and the
          music from its own card, so no file data goes over the air.
        - Only small packets go between them, every frame: each car's
          position, rotation, speed and physics vectors; the pad inputs
          (steering, gas, brake); and game events, such as a spike strip
          hit or a cop spawned.
        - Retail's two-player mode is split-screen on one PS2 (task 30).
          Here each player has a console. The two-player paths already
          ported (PlayersByNumber, the two views, the pre-race camera's
          two-player cars) are where the second player would come in,
          driven by the other console's packets.
        - Not started. It comes after the single-player race is whole.
        - 2026-10-13: the user asked for it next, once task 51 (the
          damage) is 100% done.
        - **The design (Session 94): lockstep.** Both consoles run
          retail's own two-player race, the whole simulation on each,
          and only each frame's step and both pads go over the air.
          Each console draws only its own player's view, mirror and
          HUD. Retail's two-player logic then holds on both: the cops,
          busts, positions, and the two players' cars hitting each
          other. Packets stay tiny (well under 100 bytes a frame). The
          cost is determinism: whatever the sound, the drawing or the
          loading's timing feeds into the simulation has to be found and
          kept out. State hashes each frame say where the two part.
          Sending each car's state instead (the first idea above) would
          mean replicating every cop, chopper, munition, NIS and HUD by
          hand.
        - **Testing:** two Azahar instances on this PC, the second a
          portable copy with its own user folder and sdmc (the retail
          data through a junction), both in an `azahar-room.exe` room.
          Joining goes through the GUI's Direct Connect, since the Qt
          build ignores `--multiplayer`, so a script drives it.
        - **The slices, one at a time:**
          - [x] 37a: the link (`wireless.c`). UDS host, scan, join and
                leave; framing; reliable messages, acked and resent;
                per-frame messages that repeat the last few frames
                against loss. A host check runs it over a fake UDS that
                drops, repeats and reorders packets. A config key runs
                a link soak between two Azahars and logs it.
                - Done in Session 95 (`docs/formats/wireless.md`).
                  `wlproto.c` is the protocol: a CRC-16 on each
                  packet, 32 reliable messages in flight with 100 ms
                  resends, and unreliable ones for the next packet.
                  `wireless.c` puts it on UDS. Repeating the last few
                  frames is the race messages' job, so it goes to 37d.
                - `wlproto_check`: 38 scenarios, faults 0; 50
                  mutations, 48 caught, 2 equivalent.
                - The soak (`WirelessTest 1`/`2`,
                  `tools/run_azahar_wireless.ps1`) passed on both
                  sides over 120 s: 3634 and 3642 reliable messages,
                  3590 and 3581 frames, 0 faults, 0 resends.
                - The testing note above holds, with two changes. The
                  copies need no retail data until 37b. The room
                  takes one member per nickname, and the nickname is
                  the console's user name, so the script writes one
                  into each copy's config savegame.
                - 2026-10-14, the user: as many consoles as Download
                  Play takes, up to 8, a race's grid. It takes 8: a UDS
                  network has up to 16 nodes, and Mario Kart 7 races 8
                  over Download Play. So the link is now a star of up to
                  8 (e02c8a9 had 2): the host keeps a link for each
                  client, closes its network once all have come, ejects
                  late or quiet ones, and keeps a lost peer's place. The
                  soak takes `WirelessTestConsoles` and fails unless all
                  were on the network at once. On Azahar (copies A to
                  H): 4 and 5 consoles over 30 s and 8 over 60 s all
                  passed, 0 faults, 0 resends; with 8 the network held
                  all 8 at once.
                - The race side of 8: retail's race has 8 cars, two
                  of them players. A third to eighth human takes an AI
                  racer's car, driven by its console's pad. 37c and 37d
                  work that out.
          - [x] 37b: the lobby. Players 2 on the mode screens becomes
                local wireless: Host or Join, the hosts listed by
                console name, and a lost link handled.
                - [x] 37b-1: where Players lives. Both Mode Selects'
                  Challenge (ChallengeScreen) and the four setups its
                  Setup goes to -- Single Race, Knockout, Lap Knockout,
                  Free Run -- on RaceSetupBaseClass, in bsetup.c.
                  challenge_check (620 ops, 92 mutations, 1 equivalent)
                  and racesetups_check (3142 ops, 74 of 74) against
                  retail; run_azahar_challenge.ps1 walks all four and on
                  to Select Car. Retail's ~FlailerMenuItem puts each
                  label's saved colour back when a screen goes; the port
                  now does too (bmenu_close), which fixed Knockout's
                  Damage drawn gray after Single Race. Then the flow:
                  retail closes the menu before SCREEN_UNACTIVATE and
                  brings a screen back on the item it was left on when
                  its callback answers -1. The port had the menu after
                  the message and always started at 0; it now keeps
                  SavedMenuItemNumber per screen (gameflow.h savedItem)
                  and the order (the closeMenu hook).
                - [x] 37b-2: Players' Local Wireless, the lobby popups,
                  an N-copy Azahar test, and portlang.c.
                  - Done in Session 97 (`docs/formats/lobby.md`). Players
                    2 reads "Local Wireless" on Challenge and the four
                    setups, and goes on to the lobby, the screen "Local
                    Wireless" (`lobby.c`), instead of Select Car2P. The
                    lobby is popups on the memory card's popup screen:
                    Host or Join; the host's list of names with Start;
                    a joiner's search, each race found (Join or Next),
                    and the wait for the host. Start closes the network
                    and tells each client its place and the count; then
                    all go on to Select Car with the link up. Going
                    back, or coming back from car select, takes it
                    down.
                  - `portlang.c`: the port's 14 strings in retail's six
                    languages, IDs from 2000000, answered by
                    `langtab_get`.
                  - lobby_check: 28 scenarios, faults 0; 67 mutations,
                    64 caught, 3 equivalent.
                  - `tools/run_azahar_lobby.ps1` (`-Consoles 2` to `8`),
                    each copy on the retail data through junctions and
                    its own SAVES: with 2, 4 and 8 consoles, every copy
                    reached Select Car, each joiner at its own place (1
                    to 7 of 8).
          - [x] 37c: the setup. The client's car to the host; the
                host's race parameters, seeds and start to the client;
                both load, then a barrier before the race.
                - Done in Session 98 (`docs/formats/netrace.md`).
                  `netrace.c`: each console picks its car; a client
                  sends it (NETRACE_MSG_CAR) and waits on "Wireless
                  Race", BACK taking it back. The host's start on track
                  select builds the race once every car is in: retail's
                  StartRace with the first client as the second player
                  and the rest in AI racers' places (`gFredNetRideFn`),
                  then the race parameters, the driver table, the event,
                  Fred's game type and players, the seed and each place's
                  driver to every client (NETRACE_MSG_SETUP, in pieces).
                  Each console holds at the end of its load
                  (`gTrackFlowHoldRaceFn`) until the host's GO, which
                  carries the seed every console races on. A console
                  lost before the build is raced without; with none left,
                  or the host lost, back to the lobby with a notice.
                - netrace_check: 21 scenarios (2 to 8 consoles, BACK on
                  both sides, consoles lost at every stage, a knockout, a
                  setup from another build, French, no wireless race),
                  faults 0; 158 mutations, 147 caught, 11 equivalent.
                - On Azahar (`run_azahar_lobby.ps1 -Consoles 2 -Race`):
                  both PASS (racing). The host built track 11 with 4
                  drivers at 174 s, the client took it (driver 1), both
                  loaded and held, GO at 178 s, both racing on seed
                  248fe492 at 179-180 s with the same Starting Grid;
                  sound up, no link lost, no unmapped reads. The grid
                  colours the same rows on both: the client's marks
                  player 0's, the host's car, as its own (37d).
                - The link keeps its 30 s patience past GO: the race's
                  first frame (its drawing's preparation, 8.9 s on
                  Azahar) stops each loop as long as a load. The first
                  run gave the 3 s timeout back at GO and each copy timed
                  the other out. 37d gives it back once every console's
                  frames come in.
          - [x] 37c-2: the CPU racers, the host's call (the user,
                2026-10-14). In a race with no cop among the players,
                the host's wireless setup chooses whether there are CPU
                racers and how many: none, or 1 up to 8 less the players
                in the room (8 cars at most).
                - Done in Session 99 (`docs/formats/lobby.md`, "CPU
                  racers"; `docs/formats/netrace.md`, "The build"). The
                  host's list ends with "CPU racers: n" where the setup
                  has AI racers (`lobby_cpu_wish`, `main.c`: Single
                  Race's Opponents, Full Grid as many as fit, One 1,
                  None 0, 0 with the cops; Knockout and Lap Knockout 2;
                  no choice for Free Run and Be A Cop), never more than
                  8 less the consoles; CPU Racers counts one more, none
                  again past the room. Start hands the count on
                  (`LobbyRace.cpu`). The host's build adds the CPU
                  racers to the clients in AI racers' places; they take
                  the front by performance and the players start behind
                  them in place order; a Lap Knockout's laps stay one
                  fewer than the cars.
                - Each console's own car and transmission: the -Race run
                  picks a different car on each client, Manual on the
                  odd ones, and checks the host got each as sent.
                - All cops (2 to 8 CPU racers) is TASKS 61's rule.
                - lobby_check: 34 scenarios, faults 0; 87 mutations, 84
                  caught, 3 equivalent. netrace_check: 25 scenarios,
                  faults 0; 172 mutations, 161 caught, 11 equivalent.
                  fredrace_check: 0 differ.
                - On Azahar (`run_azahar_lobby.ps1 -Consoles 2 -Race
                  -Cpu 2`): both PASS (racing). The host's list showed 7
                  CPU racers alone and 6 with the client in; A counted
                  0, 1, 2, and Start went with 2. The client sent its
                  Vauxhall VX220 (type 35, skin 7) on Manual, the host
                  got it as sent and started with its Opel Speedster
                  on Automatic. Track 11 built with 4 drivers, GO at
                  199 s on seed ced6d9c3, both racing; each Starting
                  Grid has the CPU racers 1 and 2, the host 3, the
                  client 4.
          - [x] 37d: the lockstep race. The host's step each frame and
                both pads, with a frame or two of input delay; each
                console's own view, mirror and HUD.
                - Give the link its own timeout back (setPatience(0))
                  once every console's race frames come in (37c keeps
                  NETRACE_PATIENCE_MS past GO).
                - A frame whose record is not in yet waits without
                  blocking the loop: it draws and pumps the link, and
                  the race does not step (for 37g's pause).
                - Leads (Session 98's survey): dt is wall-clock
                  (`realtime.c` PrepareRealTimestep), so the host's
                  quantised step goes with the pads; the joylog's event
                  list (`joyevent.c` GenerateJoyEvents, port in bits 16
                  to 18) is the place to inject each console's pad;
                  JOYSTICK_PORTS is 2 and players are capped at 2
                  (`playerinit.c`), and AI places are AI_CONTROL
                  (`raceinit.c` racecoordinator_init_cars); the view,
                  mirror and HUD follow player 0 / view 1 in
                  `trackview.c`, `sundraw.c`, `eenvmap.c` and main.c's
                  bottom screen.
                - Done in Sessions 100 and 101
                  (`docs/formats/netstep.md`). `netstep.c` is the
                  lockstep core: the input delay is 3 frames, and
                  the host builds each frame's record from every
                  live place's pad and its own step. main.c runs a
                  frame only once its record is in, waiting up to
                  8 ms and else drawing without stepping; each port
                  reads its place's pad from the record
                  (`joyhid_from_wire`), and the flow's presses go
                  to each place's port (retail's
                  SetScreenFilterPort). Each console shows its own
                  player (`PlayerNetLocal`, `player_shown`,
                  `eViewShowOne`). netstep_check: 20 scenarios,
                  faults 0, 104 of 107 mutations caught (3
                  equivalent); joyhid_check's round trip over every
                  set of keys; every harness 0 differ.
                - On Azahar (`run_azahar_lobby.ps1 -Consoles 2
                  -Race`, which now holds the gas on both for 30 s):
                  both PASS. Every checksum logged matched on both
                  copies, frame 0 to 1200, with no "differs"; each
                  copy showed its own car, mirror and HUD, the same
                  places and minimap, at 28 FPS. Not tried: the
                  pause from either console, which goes to 37f.
                - 37d-2: places past the two players' show player
                  0's view, and their cars are AI for now.
          - [x] 37e: determinism. The per-frame hashes (cars, cops,
                traffic, seeds, the race coordinator) compared, each
                part's hash logged at a mismatch, and every source of
                drift fixed.
                - 37d's first run (track 11, no cops, gas only) had
                  no drift through frame 1200, though the clocks at
                  GO differed. The world's checksum reads only the
                  cars' x + y and WorldTimer, so 37e needs a wider
                  one (each part's) and harder runs: cops, traffic,
                  steering, crashes, a whole race.
                - Leads: `world_calculate_debug_checksum` (worldstep.c)
                  is a per-frame hash already. The world's own seed is
                  drawn from bDefaultSeed in `world_init`, during the
                  load, before GO; in Session 98's runs the client's
                  seed at the hold matched the host's. bDefaultSeed
                  feeds the drawing and the speech as well as the
                  simulation, and cop filler speech waits on playback.
                - Done in Session 102 (`docs/formats/lockhash.md`).
                  `lockhash.c` hashes the world in seven parts after
                  each frame (time, seeds, players, AI racers, cops
                  with the helicopter, traffic, the race) and folds
                  them into netstep's checksum; every 150 frames it
                  logs them, and at the first frame that differs,
                  once a race, the parts and the draws on
                  bDefaultSeed of the 16 frames up to it, each by the
                  address that drew (`bDefaultSeedWatch`). Each
                  console runs every player's logic as retail ran its
                  two, so the one source of drift the code shows is
                  cop filler speech, which waits for the console's
                  own audio: speech,
                  cameras and models' start times now draw on
                  `bViewSeed`, a seed of its own from GO in a
                  wireless race (bDefaultSeed elsewhere, so retail's
                  draws are unchanged). lockhash_check: faults 0, 77
                  mutations, 73 caught, 4 equivalent; the twelve
                  harnesses of the moved draws 0 differ.
                - On Azahar (track 11, 2 laps, 4 cops, 2 consoles,
                  2 CPU racers, gas and steering for 240 s): every
                  part the same as the host's on all 39 frames
                  logged, with both consoles' sound and with only the
                  host's (the client "ndsp unavailable", its speech
                  bank not loaded). Two control runs with bViewSeed
                  left on bDefaultSeed kept in step as well: filler
                  speech needs a chase of a player, and no scripted
                  drive drew one (with no CPU racers, no chase at
                  all), so the speech drift is shown by the code and
                  the harnesses, not on Azahar.
          - [ ] 37f: the end. Results and points on each console, back
                to the lobby or a rematch, and a player leaving
                mid-race. Three slices: 37f-1 the end of lockstep and
                the way back to the lobby, 37f-2 a rematch (Restart
                Race, Next Race), 37f-3 one player leaving mid-race.
                - [x] 37f-1, done in Session 106 (`netstep.md`, "The
                  end"; `lobby.md`, "After the race"; `netrace.md`,
                  "The race's end"). Every console leaves lockstep
                  after the same frame: the one that asks for the
                  end's save (Quit or Next Race after the results), or
                  the one the pause's Quit Race unloads the race in.
                  The host serves its last records until each client
                  has said it stopped, is gone, or 10 s have passed; a
                  client says its stop 30 times and reads nothing
                  more; neither reads past a message of the lobby's
                  (`wl_link_peek`). `netrace_end` gives the link
                  netrace's long patience for each console's save,
                  unload and frontend load, and the frontend comes
                  back to the lobby with the link up (gameflow's
                  `raceReturn` hook): the host's list, open to
                  joiners, each client listed once it says it is
                  back (`LOBBY_MSG_BACK`), Start once all are; a
                  client's wait for the next Start. Once every
                  console is back the link has its own timeout again.
                  netstep_check: 39 scenarios, faults 0, 146 of 148
                  mutations caught (2 equivalent); lobby_check: 71
                  scenarios, 165 of 171 (6 equivalent); netrace_check:
                  28 scenarios, 166 of 177 (11 equivalent);
                  wlproto_check: 51 of 53 (2 equivalent).
                - On Azahar (`run_azahar_lobby.ps1 -Consoles 2 -Race
                  -Quit`): both passed, twice (seeds 441703d1 and
                  7c0a9c9c): the host's pause and Quit Race OK, both
                  stopped on the host's frame (2327, 1924), every
                  client stopped about 1.05 s after the host, both back
                  in the lobby and every console back, the host's
                  Start again, both at Select Car again, every logged
                  frame's parts the same. Presses from someone at the
                  host's window once resumed the pause (A on Resume, as
                  retail); the log now has each lockstep frame's
                  presses and each pause's port and frame.
                - Not tried on Azahar: the end through the results
                  (the race has to finish, and the gas alone does not
                  finish it). The pause's Quit and the results' Quit
                  share everything past the stop.
                - [x] 37f-2, done (Session 107): after the end netrace
                  waits at `NR_ENDED`, goes off once the frontend
                  loads, or holds again for the event's next race (Next
                  Race, Restart Event) and GOes on the host's seed;
                  nothing of netrace's is read or sent while the last
                  race's end is on the link. The event's grid and the
                  raced player's settings the same on every console; a
                  knocked-out player's console shows the other player;
                  `WirelessTestFinish n` finishes a race for Azahar
                  runs. netrace_check: 36 scenarios, faults 0;
                  `--mutate` 194, 182 caught, 12 equivalent.
                  - Restart Race hung on a NULL WorldObject: GCC's
                  strict aliasing at -O3 had dropped the loop that
                  destroys the race's smokeables, so they leaked at
                  every race end and far-away delete. The deletes'
                  list head is a whole CollisionBody and the Makefile
                  has `-fno-strict-aliasing` (a push onto
                  CollisionBodyList kept a stale head too).
                  smokeable_check: 0 differ, the list's mutations
                  caught.
                  - Two Azahars, `-Restart`: both passed on seed
                  0ecec47b, restarted in lockstep and raced again, no
                  unmapped reads; the CPU stages a little faster.
                  - Two Azahars, `-NextRace` (Session 108): both
                  passed on seeds 0e7236cd and 3b4c87d1: the finish on
                  frame 1800, the stop on 3023, each copy's save, race
                  2 loaded and raced in step. Two fixes on the way:
                  the script moves to Yes (the save's question opens
                  on No, as retail), and the race's view of the track
                  lets go in the Begin of unloading
                  (`gTrackFlowViewUnloadFn`); before, the second load
                  aborted on the first race's heap (`bMalloc:
                  8995308 bytes for TRACKS\TRACKB11.LZC`).
                  - [ ] One run of three had a checksum difference
                  nine frames after the test's finish (frame 1809, the
                  time and racers parts: an AI racer's car), every
                  frame after it too. Find it: lockhash now logs each
                  slot's car and, at the frame, its pieces.
                  Session 109: once more in four runs, frame 1809 in
                  the time and players parts, slot 0 alone (the host's
                  car, the AI's after the finish) differing in every
                  CarState piece but rel, its modes the same. So what
                  the AI chose went first. lockhash's cars now have a
                  tenth piece, the driver (its inputs and its target's
                  points), and the script names the frame where the
                  slot's word first differed; the next split will say
                  which.
                  Session 112 (the 37g-3 `-Rejoin 1` run, seed
                  7dbec474): the host's checksum differed from B's at
                  frame 917, with B's first run matching at every
                  frame logged to 900. B, restarted and caught up on
                  the host's records, differed first at frame 450, in
                  the players part (the two players' cars, REAL
                  control, racers and race the same), and netstep's
                  checksum at 980. A replay of the same records on
                  the same build should not differ: find what a
                  player's car reads that is not in the record (the
                  draw, the vertical blank, a console's own state).
                  Session 113: both were the checksum's, not the
                  world's. The sound writes two things between the
                  frames on the real clock, so a catch-up's run of
                  frames left them on other frames: the engine
                  sound's `RedLineSyncRPM`, and a car's
                  `RelCoordMatrix` cache, built by the car sound
                  while `MatrixValid` is 0 and read by nothing until
                  it is set. lockhash leaves both out
                  (`lockhash.md`, "The relative matrix"). A `-Blind
                  1` run had ruled out the draw. `-Rejoin 1` on the
                  fix (seed b2c97ed7): PASS, every part the host's
                  from 0 to 1500.
                  Frame 1809 is still open: a `-NextRace -Drive 30`
                  run on the fix (seeds ca54f485, f20ce80b) passed,
                  every part the host's at all 27 frames logged to the
                  stop on 3033. Two splits in eight runs now.
                  - Session 109, the second race on two Azahars (the
                  user's screenshot of race 2 with the HUD and no
                  track): B's view found no 3.1 MB whole for its
                  tables ("out of memory for the tables"), and the
                  main loop's attach ran in the same pass as the
                  unload and the next load's Begins. Fixed: the attach
                  waits for the next race's coordinator, and a mesh's
                  batches live in its vertex block on the linear heap
                  (`track-render.md`). The Next Race abort on
                  `TEX11LOCATION.BIN` (21 MB free, no 5 MB of it
                  whole): bMalloc's top, the packed copies and pool
                  72's reads, goes to the linear heap
                  (`resource-file.md`), never its last 8 MB, and the
                  card's expanded TRACKB is not the top's.
- Two Azahars, `-NextRace` (Session 109): PASS on
                  both, seeds 494a70f2 and 4529067b, race 2 drawn on
                  both; at each attach no top block live, 5 to 7
                  textures left out at the prepare (52 to 61 with the
                  bundle on the top), 5.4 MB of the main heap free.
                  - Not run: Restart Event on Azahar; the harness
                  covers it. Not seen on the device: the smokeables
                  now freed, and any FPS change from the flag.
                - [x] 37f-3, done (Session 111): the pause's screens
                  are driven by the pad that paused, on every console,
                  so one player's Quit Race ends the race for all, as
                  retail's split screen does. Nothing in the game had
                  to change: the START is in the record on its place's
                  port, and SetScreenFilterPort gives the screens that
                  port on each console (`netstep.md`, "The screens'
                  ports"). `run_azahar_lobby.ps1 -PauseBy 1` has B
                  pause. Before B moves, the host's Down and START
                  must leave B's pause on Resume Race on every copy.
                  Three runs passed: B's Quit (seed dbfe8ce9: paused on
                  frame 991, stopped after 2160, back to the lobby and
                  Select Car), B's Restart (seed 3d51a052: racing
                  again in lockstep), and the host's Quit with B's
                  presses (seed e5574ec8). Every logged frame's parts
                  were the host's. Leaving alone (the others racing
                  on, its car to the AI) is 37g's hand-over.
          - [x] 37g: a console lost mid-race. The user, 2026-10-14:
                when a console disconnects, the whole race pauses and
                tries to reconnect it. The lost console rejoins the
                way it joined before the race (Local Wireless, Join,
                the host's game), and the host knows it by something
                unique to that 3DS and gives it its place back.
                - Lockstep pauses by itself: no record is built
                  without the lost place's pad. 37d keeps the loop
                  drawing and pumping the link while a frame waits,
                  so a pause screen can stand over it.
                - A console that kept its race (only the link
                  dropped) goes on from its last frame. One that
                  restarted needs the race again: the setup, the
                  load, then the records from frame 0 run fast, or
                  a snapshot. Find which.
                - The ID: candidates are CFGU_GenHashConsoleUnique
                  and UDS's node info (its friend code seed), as
                  long as the Azahar copies differ in it.
                - The user, 2026-10-14: if it has not reconnected
                  after 1 minute 30 seconds, the race goes on and the
                  lost player's car is driven by the CPU, as a racer
                  or as a cop, whichever it was. The record the host
                  first builds without the place (its live bit gone)
                  is the frame every console hands that car to the AI.
                - [x] 37g-1: the hold, then the CPU. A lost console
                      holds the race on every console for
                      `WirelessHoldSeconds` (90), under a box that
                      names it and counts down. Then its car is the
                      AI's on the frame of the first record built
                      without it. A client that loses its host holds,
                      then races alone. Done in 2a9b396 (HANDOFF.md,
                      Session 112):
                      - netstep's hold. netstep_check: 47 scenarios,
                        0 faults; 173 mutants, 170 caught, 3
                        equivalent. Nothing goes over a lost link.
                      - The setup carries the console names (version
                        2). main.c draws the box and, for 4 s after
                        the drop, "The CPU drives NAME's car." It
                        mutes the race while held, and hands a pause
                        the lost place held to the lowest live port.
                      - `run_azahar_lobby.ps1 -Race -Lose 1`: B closed,
                        the host held 10 s under the countdown, then
                        handed B's car to the CPU on frame 718, and
                        it passed the host's. `-Lose 0`: B held for
                        the host, then raced alone from frame 773.
                - [x] 37g-2: a console whose link alone dropped is
                      re-peered during the hold and goes on from its
                      last frame. Done in Session 112, continued:
                      - wireless.c: while the race holds for a place,
                        `wireless_set_rejoin` opens the closed network
                        to a lost console. A node with a lost peer's
                        user name (and friend code seed, when both
                        have one) whose place the race still holds
                        takes that peer back with a new link; any
                        other is sent away. A client that lost its
                        host calls `wireless_rejoin` every 2 s: it
                        leaves, scans by the host's MAC and joins
                        again.
                      - netstep.c: the host sends a place on the link
                        again its records, and says it is back ("place
                        p back") once its pads come. A client is back
                        once the host's records come ("the host
                        back"). Either end with the link up but no
                        word waits NETSTEP_BACK_MS (3 s) past its
                        hold. A console taken back that sends no pads
                        (one restarted) has its car go to the CPU
                        then, instead of holding the race for good.
                      - netstep_check: links cut and re-peered in the
                        harness, eight new scenarios, 55 in all, 0
                        faults; 190 mutants, 187 caught, 3 equivalent.
                      - `WirelessTestDropFrame`/`WirelessTestDropMs`
                        make a console deaf from a lockstep frame.
                        `run_azahar_lobby.ps1 -Race -Drop 1` and
                        `-Drop 0` pass on two Azahars: the copy deaf
                        at frame 300 for 5 s, both ends lost the link
                        and held, B back on the host's network on its
                        first try, both saying "back", then racing on
                        in lockstep, every logged frame's parts the
                        same.
                      - The last runs (seeds 01389e7e and 9d768a12):
                        the host says "place 1 back" only once B's pads
                        come, just after B's "the host back" (16 ms
                        with B deaf; with the host deaf, once it hears
                        again). 18 and 17 logged frames the same. Not
                        yet run on real 3DSes.
                - [x] 37g-3: a restarted console rejoins through Local
                      Wireless, then Join, known by its unique ID, and
                      catches up. Done in Session 112, continued (2d84039
                      netstep's half, b8bace6 the rest):
                      - netstep.c: the host keeps every record from GO
                        (delta-coded, a key every 64, 32 KB blocks up to
                        4 MB). `netstep_rejoin` lets a held place back
                        in; its hold starts again for the load; once its
                        pads come the host sends it the records from
                        frame 0, NETSTEP_BURST messages at a time, and
                        builds none until it has caught up. The race
                        stays held on every console meanwhile.
                      - lobby.c: every joiner sends LOBBY_MSG_REJOIN; a
                        racing host's netrace answers LOBBY_MSG_RESUME
                        (place and mode) and the setup again. The
                        console loads from the lobby, no car select;
                        refused in an event's later race.
                      - netrace.c: the host's racingRead peeks the
                        held places' links for REJOIN and the load, then
                        GO on the race's seed; one given up on as it
                        loads is sent off the network (wireless_drop).
                        From RESUME until the place is in step its link
                        has netrace's patience (30 s): the first frame
                        after GO attaches the track for 4 s with no
                        pump, and the host's 3 s timeout dropped it.
                      - main.c: past NETSTEP_BEHIND records the console
                        back runs the race undrawn, its progress every
                        250 ms ("Catching up with the race... N%") over
                        a black top screen, its sound at master volume
                        0 until it is in step. The rest show "NAME is
                        coming back into the race... N%" and mute. The
                        user asked mid-session that it see no overview:
                        from its GO (`g_lockBack`, past its own first
                        NETSTEP_DELAY records) it shows no grid, fly-by
                        or countdown, and is straight back in the race
                        once caught up.
                      - Checks: netstep 67 scenarios, 259 mutants, 253
                        caught; netrace 48 scenarios, 252 mutants, 236
                        caught, 16 equivalent; lobby 80 scenarios, 197
                        mutants, 191 caught, 6 equivalent; faults 0
                        everywhere.
                      - `run_azahar_lobby.ps1 -Race -Rejoin 1` (seed
                        7dbec474): B closed and started again, back in
                        place 1 with the same friend code seed, caught
                        up (frames 3 to 975 in about 6 s, the host's
                        hold 22 s in all), and both raced on. Azahar's
                        host never forgets a station (its EjectClient
                        is a stub), so the restarted copy comes back on
                        a new MAC (sysdata/mac.txt deleted); the game
                        matches name and seed. The user watched it and
                        called it working; the run was not repeated
                        after the last fix (`g_lockBack` kept through
                        frames 0 to 2, built only).
                      - Not the same: B's world after the catch-up
                        differed from the host's from frame 450 (the
                        players part); see 37f-2's open difference.
38. [x] **BUSTED! is flat and static.** The user's Azahar shot of
        2026-10-09: in the bust NIS, BUSTED! sits squashed, its top cut
        off, and never animates. Retail scales it from 5 down to ScaleX
        and fades it in from alpha 0 to 128 over a quarter second
        (NISOverlayManager::Start, 0x00182488; Update, 0x001825f0;
        hudnis.c). Check that Update runs each frame of the NIS, that the
        tracks step (WorldTimeElapsed may be 0 while the world is
        frozen), and how ScaleY reaches the quad. The bottom screen was
        blank during the NIS too; check that against retail. The user
        agreed it comes after step 14, the full audio.
        - Done in Session 82 with no change to the code. Two throwaway
          builds forced a ticket at 20 s of world time on track 12
          (`copmanager_create_pullover` from raceFrame). The overlay's
          Update runs each frame from player_render_hud, and
          WorldTimeElapsed is live there (0.033 s a frame). The scale
          goes 5 to 2 and the alpha 0 to 128, and the text's ScaleX and
          ScaleY follow. With the tracks slowed to 8 s, Azahar's shots
          show it: BUSTED! comes in huge and clear, then shrinks and
          darkens to its place, whole and in proportion
          (`out/busted_zoom_slowed.png`; `out/azahar_t38c`). The squash
          and the cut top were the text drawing that 58f28ab replaced
          (2026-10-11): proportional text at ScaleX once.
        - BUSTED!'s letters sit unevenly ("BU ST ED!"). That is
          retail's: Render (0x001425dc..0x00142854) draws the glyph at
          pen + kerning x ScaleX and moves the pen by ScaleX x (advance
          + kerning x ScaleX), so font a2d444f6's +1 (B U) and +3 (S T)
          pairs open up at scale 2. uirender.c does the same.
        - The bottom screen stays dark through the NIS: the NIS's HUD
          features (0a240000) have none of the bottom screen's items,
          as retail hides its whole HUD then. Left as it is; asked the
          user.
39. [x] **The helicopter's missiles.** Asked for on 2026-10-10, with a
        video of retail for reference: "NFS HP2 for PS2 dodging
        missiles" (https://www.youtube.com/watch?v=VAsYHOw5pyc, 2:18).
        This is 12k-6: FireSalvo (`0x001ea8c0`) is a placeholder in
        `chopperfire.c`, so the bombing run counts its salvos and fires
        nothing. The munitions are Smokeables -- Munition (`0x001be6c8`),
        Rocket (`0x001bf340`), DroppedBomb (`0x001beae0`), SmokeBomb
        (`0x001beb90`) and DroppedSpikes (`0x001bee88`) -- with the
        MunitionEffectsHandler (`0x001bf980` .. `0x001bfad0`) behind the
        seam `gMunitionEffectsDoTimestepFn`. They need the Smokeable base
        (step 14b), which is done (Session 85, `smokeable.c`; slot 216 is
        the OnLifetimeEnd they override). Check the result against the
        video's frames:
        the missiles' look, their trail and what a hit does to the car.
        - The user's note, 2026-10-10: only one helicopter fires
          missiles, the armed one, and only on certain tracks. It also
          drops exploding barrels, some with a spike belt hidden
          inside and some without. Reference:
          https://nfs.fandom.com/wiki/Police_Helicopter_(Armed)_(2002)
          (the page would not load here, in WebFetch or the browser).
        - That matches retail's decode (CONTINUE.md, 12k-6): the
          bombing runs' table (`0x0031a7c8`, five rows of 32 bytes,
          by BombRunType) has the kind at +0 -- 0 a Rocket (the
          missile), 1 a SmokeBomb (the plain barrel), anything else
          DroppedSpikes (the barrel with the belt). Which run a
          helicopter gets, and so which tracks have the missiles,
          comes from the track's data: find where BombRunType is set
          and check that only the armed helicopter's tracks pick row
          kind 0.
        Done in Session 87: `munition.c` ports Munition.obj whole (the
        three classes, ExplodeWarhead, MakeSpikeBelt, the effects
        handler) and `chopperfire.c` FireSalvo, which launches them.
        No track picks the weapon: the chase's behaviours do (0x100
        rockets at 3 or 4 roadblocks, 0x80 belts at 5 or more), and a
        track decides only whether a helicopter comes and its model
        (`docs/formats/munitions.md`). `ForceChopper N` sends it in a
        SkipFE race; Azahar showed rockets, barrels with their smoke
        and flash, a car thrown by a blast, and belts handed to the
        cop manager. `tools/munition_check.py` runs retail's own: 262
        ops, 1038 lines, 0 differ, and 175 of 175 mutations caught.
40. [x] **The radar detection meter.** Asked for on 2026-10-10: the
        bar of lights under the rear-view mirror. The user's
        description: it fills as the car nears a cop, green first and
        then red when close, and flashes yellow when a roadblock or a
        spike strip is set up ahead. This is 12n. The meter itself is
        ported (8m-4c-1, `hudcop.c`, Player::UpdateRadarDetector
        `0x0017be70`; `docs/formats/hud-cop.md`): twelve lights, the
        count lit from the intensity times 11, RadarColours' rows 2
        and 3 (the yellow-green ones) for a flagged cop, the swells
        and the beep. What is missing is
        tCopManager::GetRadarDetectorIntensity (`0x002274a8`), the
        intensity 0 to 1 for the nearest cop in range and the flag for
        its kind. Its seam `gCopManagerGetRadarDetectorIntensityFn` is
        NULL, so the radar reads 0 and nothing lights. Port it with a
        checker against retail, bind it in `main.c`, and check in
        Azahar that the lights climb near a cop and turn yellow for a
        roadblock or spikes ahead.
        Done in Session 83: `copmgr.c`'s
        copmanager_get_radar_detector_intensity, bound in `main.c`.
        The cops that count are a player's and the AI's at a speed
        trap, a roadblock (the flag), on patrol, with a caught
        speeder or guarding a spot; the nearest under 250 m, in
        front and within 250 along the track gives (250 - d) *
        0.004. `tools/copmanager_check.py` runs retail's own and
        catches 25 of 25 mutations. On Azahar (Hot Pursuit quick
        race, 100%, 30 FPS) the lights climbed to six as a cop
        came up ahead, and turned yellow, four lit, with a roadblock
        ahead on the minimap (`48_race-46.png`).
41. [x] **The Starting Grid before the track has loaded.** Asked for
        on 2026-10-11, with an Azahar shot: the Pre Race Stats screen
        (Starting Grid) comes up over a black screen while the race is
        still loading behind it -- "make it to where it doesn't show
        this until it's actually fully loaded". In the quick race run
        of RE-6c-2 the grid sat over black at 41.7 s (Azahar's App 4
        FPS) and still at 46.8 s (App 0 FPS): the first RACING frames
        stall on loading. Retail shows the grid over the flyby
        (the user's photos, 2026-10-07). Find what the first frames
        load (the deferred textures and models, the first sections),
        finish it under the Loading screen before the flow enters
        RACING or before Pre Race Stats is summoned, and check in Azahar
        that the grid appears over a drawn flyby at full frame rate.
        Done in Session 76: the first frame's 9.3 s was the track's
        attach and prepare (`raceAttachTrack`, main.c). A race's frames
        before the attach now draw nothing (`raceHoldsLoadingScreen`),
        so the Loading screen stays up through it, and the streamed
        packs are read in place first. On Azahar the Loading screen
        held at App 0 FPS, then the grid came up over the drawn fly-by
        at 30 FPS.
42. [x] **The Circle Pad in the menus.** Asked for on 2026-10-11 ("add
        it later, I just want it known"): the Circle Pad should move
        through every menu as the D-Pad does, the frontend's screens,
        the pause menu, the end-of-race menus and the rest, so either
        one navigates. The stick already reaches the joystick layer
        as the left analog stick, whose rows raise
        `JOY_EVENT_MENU_ANALOG_LEFT/RIGHT/UP/DOWN` with
        `DigitalRepeat`'s timing (`joyhid_check.py` tests them), but
        nothing in the port handles those events, and menus that read
        `hidKeysDown` see only the D-Pad. Find each menu's input path
        (the Flailer menus' SCROLL handlers, the pause screen, the
        frontend's kDown reads), have the stick's crossings move them
        the same way, keep its repeat no faster than the D-Pad's, and
        check on Azahar that the frontend, the pause menu and the
        results screens all scroll with the Circle Pad.
        Done in Session 80, when the user asked again: every menu goes
        through `flowInput`, so `joyhid_menu_pad` turns the stick into
        one D-pad press per push (past 96, held until under 48, no
        repeat), for `flowInput` only. joyhid_check passes, and 11
        mutations are all caught. On Azahar the stick moved the
        frontend's Cops On Mode Select and a race's pause menu one item
        per push. The results screens take the same path.
        (`docs/formats/joystick.md`)

43. [x] **The cop's buttons on the 3DS.** Asked for on 2026-10-11. In
        Be A Cop, in the cop's car:
        - [x] X, the horn, targets and untargets speeders in range, as
          in retail: `HONK_HORN` goes to `BeACopToggleSirenAndLights`,
          which calls `tPlayerCop::ChangeChaseTarget` (`playercop.c`).
          The user first asked for L, then kept it on X.
        - [x] L calls a roadblock and R the helicopter
          (`joyhid_cop_keys`, retail's TRIANGLE + R2 and TRIANGLE + L2).
          L and R are dropped there, so the cop has no look back or
          e-brake. The D-pad steers again, D-pad Down is still the
          nitro, and ZL and ZR still shift. joyhid_check passes, and 13
          mutations are all caught. This replaced the 2026-10-08 plan of
          the calls on the D-Pad, and then the user's first mapping
          (L target, R boost, ZL heli, ZR roadblock).
        - [x] Every help character (0x80..0x9d) draws the 3DS key that
          does its job (`helpglyph.c`): A, B, X, Y, L, R, ZL, ZR, the
          Circle Pad and the C-Stick come from the port's own sheet
          (`tools/buttons3ds_make.py`, `data/buttons3ds.bin`, retail
          BUTTONSOUT's 26 x 28 cells); the D-pad, START and SELECT keep
          BUTTONSOUT's, and R3 (the boost) is D-pad Down's. Which key
          a face button is follows joyhid's layout: the race's, the
          cop's (X target; the Blurb's "Triangle + L2/R2" become R and
          L) or the menus'. `helpglyph_check`: the map held to
          joyhid.c's own buttons, 6 mutations, all caught.
        - [x] The Blurb's target was the boost's glyph: retail passes
          JoyEvent 126, the horn in retail's numbering, which has
          REPLAY_ERASE_DEMO at 110; the port read it as the demo's 126,
          the nitro. On Azahar the lines read X target, R helicopter,
          L roadblock, D-pad Down boost (shown to the user).
        - The frontend's "Help" mark is a BUTTONSOUT text object
          ('k', the PS2's Circle), not a help character, and the
          port's Circle opens nothing: tHelpMenu is TASKS 48.

        The user asked about a spike strip button, as the PC version
        had one. PS2 retail has none: Be A Cop has only
        BeACopRequestChopper, BeACopRequestRoadBlock and
        BeACopToggleSirenAndLights. Spike strips come laid by
        roadblocks (`CalculateRoadBlockAndSpikeBeltParameters`, the
        roadblock's 0x10 bit).

44. [x] **The bottom screen laid out again.** Asked for on 2026-10-11:
        "A bunch of black empty space. Maybe map in the middle, or
        bottom middle, then you put everything else on top or on the
        sides". Done in Session 80: a band along the top (the live
        split list at the left, moved up when the race position shows,
        the split times in the middle, the lap block, score or Be The
        Cop's panel at the right), and the minimap under it, as big as
        the room allows and centred. The score's event lines draw over
        the map. Checked on Azahar in a Be A Cop race and a Hot Pursuit
        quick race. (`docs/formats/hud-split.md`)

45. [x] **The slight polygon artifacts.** Asked for on 2026-10-12: "Can
        you fix sometimes when there's slight polygon artifact". Seen in
        Session 80's shots: facing the sun, its glare is a flat pale
        blob with a hard, stepped edge, and a ray streak, where retail's
        glare is soft (Coastal Parklands, and the quick race's track).
        Find which layer or pass makes the edge and fix it, then look
        for other artifacts the user may mean. Done in Session 81
        (9e044f3): the sun's quads were drawn with the opaque
        textures' alpha test, GREATER 0x60; retail gives the
        semitransparent textures GEQUAL 0, and the quad now takes its
        test from the texture's pass. The halo and rays fade into the
        sky. (`docs/formats/sun-draw.md`)

46. [ ] **A smooth 30 FPS in busy scenes.** Asked for on 2026-10-12:
        "optimize the game as much as possible so rendering where
        there's a bunch of cars, fog etc. at once wont lag it? I want a
        smooth 30 FPS". It follows the 2026-10-05 GPU plan (lossless
        textures only, timing build first, then indexed meshes and
        early depth) and the desert's lag near the end (2026-10-09).
        Session 81, lossless each: the solid shader in 17 instructions
        where it took 31 (b293a76), the frame to the GPU in parts,
        opt-in with "GpuSends 1" (9e044f3), and the clusters no view
        can show left unsent (bb70171), which halve the envmap's and
        the mirror's triangles. Left: the device's timing at the fog
        and the desert, and the user's word on the envmap a face a
        frame. (`docs/formats/draw-cuts.md`, "TASKS 46")
        Session 88 (TASKS 57): the sends are on by default, with one
        more after the envmap; "GpuSends 0" turns them off. Also left:
        the device's log at track 11's fire with that build, and the
        smoke's quads cut to their texture's non-zero alpha (the
        sprites are fill-bound, 2.3 to 2.5 ms per 100 on the device).
        **The user, 2026-10-14:** the fire's area on track 11 is still
        under 30 (Azahar's frame log in Session 94's You're The Cop
        race: 15.5 FPS, draw 35.7 ms, world 14.6, citro3d GPU 38.2).
        "I want it fully optimized to 30 FPS, along with all similar
        scenarios/areas." Done means a steady 30 at the fire, the
        desert's end, and every other heavy place (fog, smoke, many
        cars, the chopper), still lossless (TASKS 46's rules).
        - [x] Session 128: the blended draws that write no depth test
          for an alpha over 0 (`georender.c` `set_pass`), which is
          exact. It drops 17 to 43% of the smoke's and the dust's
          fragments before their blend. The clusters with no pixel
          centre are 0.3% at most: not worth a cut.
        - [x] Session 128: the timing frame's replays run in a race,
          borrowing the top screen's buffers when VRAM is full, and
          they replay the sprites' stage too, with "alpha test 0 off"
          and "texture unit 1 off".
        - [ ] The device's timing run at the fire and the desert's end
          (`sdmc:/nfshp2_gputiming.txt`, `DebugLog 1`). Its replays
          decide the next cuts: fill, the cost of each draw, the
          textures, and early depth.
          - The first try (2026-10-18, Coastal Parklands, build 03ffcaf)
            stopped at the countdown with an ARM11 data abort: a
            permission fault writing 0x1f000008, in `give_back`'s
            `memcpy` into the top screen's colour buffer. Track 11
            leaves no 768 KB of VRAM, so the replays borrow the top
            screen's buffers, and the CPU may read VRAM but not write
            it (Azahar lets it). The GPU now copies them back from the
            linear heap and the readback is logged: 0 of 96,000 words
            differ on Azahar. To run again on the 3DS.
          - The second try (2026-10-18, build 5679ab6): no crash, and
            the GPU's copy back read "0 colour and 0 depth words of
            96000 differ" on the 3DS. The race was Alpine Trail (track
            42, 2 laps, 3 AI, 4 cops); Coastal Parklands ran only as the
            attract demo, a few seconds on the grid. 49 timing frames.
          - Alpine Trail is bound by the CPU, never the GPU. Of 438
            seconds without a timing frame, 194 were under 28 FPS: in
            112 the CPU was short (C under 30, G 50 to 150), in 0 the
            GPU, and in the other 82 the CPU was at its edge (C 30 to
            35), so some frames missed the vsync. The slow seconds'
            CPU: world 4.9 ms, draw 20.6 (models 6.3, cars 2.9, mirror
            2.3, envmap 2.1, cull 1.9, scenery 1.6); up to 30 ms of
            draw (models 11) on the start straight, x 400 to 700, y
            1400 to 1500, with the grid. The GPU, citro3d's, 14.6 ms.
          - The timing frames' own GPU stages, summed: 24.6 ms on
            average, 41 at most; the models 9.7. Their replays: 8x8
            textures save 32%, a 1-pixel scissor 50% (the fill), 3
            vertices a draw 92% (the vertices), RGB8 for RGBA8 6%, no
            cache clears 2%, alpha test 0 off and unit 1 off nothing.
            Early depth changes the picture in nearly every replay
            (">=" exact in 3 of 49, "<=" by some 28,000 pixels), so it
            is out. With the GPU at half the frame, the next cuts are
            the CPU's: the draw's per-batch work (580 model draws a
            frame where it is slow) and the world.
          - The stutters the user felt were the timing frames: each
            stops the game for 200 to 340 ms, every 10 s or so. With
            no timing frame no frame took over 66 ms. So the next runs
            keep "DebugLog 1" and leave `nfshp2_gputiming.txt` off: the
            frame lines' C and G say which side is short.
          - The draw's per-batch work (Session 128): Azahar's samples of
            Alpine Trail's start put a model's matrices first. The port
            now sends the float uniforms itself (citro3d's words,
            checked word for word over the first 64 sends) and copies
            and compares them with no calls. A batch's clusters are
            tested only against the planes the batch is across. On
            Azahar the models take 12.5 ms from 14.4 and the draw 37.0
            from 39.8; the picture is the same to the pixel
            (`docs/formats/draw-cuts.md`). Still to do: the device's
            numbers for it, and the world step.
          - The ticker and the vtables (Session 128): a second profile
            put `vt_slot`'s search from the front next (6.4%), then
            `bGetTicker`'s two 64-bit divisions (5.4%; the ARM11 has no
            divide). `vt_slot` now looks the address up in buckets. The
            divisions are multiplies by the reciprocal with one
            correction, the same ticks on 106 million host checks
            (`tools/bticker_check.py`). On Azahar the world step takes
            2.8 ms from 3.4; the picture is the same to the pixel.
          - The textures and the sun's read-back (Session 129): a third
            profile put `load_texture`'s scan of the texture list (659
            entries at Alpine Trail's start) and the sun's per-pixel
            `floorf`s next. Every scenery piece and car part looks its
            textures up there each frame. The list is now found through
            2,048 buckets, and each sun rect's columns and rows are
            worked out once. `tools/trackview_cuts_check.py` holds both
            to the old code (137.5 million pixels and 4 million lookups,
            none differ, 14 of 14 mutations caught). On Azahar, seconds
            2 to 8: scenery 1.1 ms from 2.9, cars 5.9 from 8.6, the draw
            31.0 from 36.6. Over the whole race, 6 seconds under 28 FPS
            from 13. The picture is the same to the pixel.
          - The scenery's boxes (Session 130): a fourth profile put
            `scenery_classify_aabb` first among the game's functions
            (5.0%). It now answers "across" as soon as the corners so
            far say so, and `scenery_draw_a_scenery` tests a piece's
            box only once it would be drawn. `tools/scenerycull_check.py`
            holds it to retail (none of 46,687 lines differ, 149 of 150
            mutations caught, 1 equivalent as before). On Azahar's start
            straight the cull takes 2.6 ms from 3.05 and the draw 32.2
            from 32.4; the picture is the same to the pixel.
          - Found in the device log: after the finish, in the post-race
            and the instant replay (rc 7 and 4), the race phase takes
            13.5 ms a frame on average and up to 34. Not a cost (Session
            130, continued): in a replay World::GetTimestep spins until
            the frame is as long as the step the capture logged, so a
            replay plays at the race's own rate. The device's View
            Replay matches its race second by second, 20 FPS where the
            race ran at 20. A faster race makes a faster replay; the
            spin stays. The frame line now times it apart ("waits: ...
            replay") and takes it out of "race".
          - The sound banks' flush (Session 130, continued): each sound's
            start flushed its patch for the DSP, a service call (2.2% of
            the fourth profile). A bank is written once, at its load, so
            it is now flushed once there. To hear on the 3DS: any
            crackle or old sound in an effect would mean a flush missing.
          - The fog's texture (Session 130, continued): the view's two fog
            textures were refilled and flushed every frame, each flush a
            request to GSP's thread. Fractions the same as the last fill's
            now leave the texture as it is, and a new fill works out each
            column once. `tools/georender_cuts_check.py` holds it to the
            old fill; nothing on screen changes.
          - threadguard (Session 130, continued): off unless the config
            says "ThreadGuard 1", at the user's word (2026-10-18). Its
            checks at each of the main loop's marks and every 10 ms on the
            game's core were 1.7 to 2.5% of Azahar's race profiles; the
            crash it was made for was fixed the day it was found (399d67e).
            Off, nothing is watched and the audio workers wait 10 ms on
            their own, as before it.
          - The sampler (Session 130, continued): "CoreSample 1" has a
            thread on the third core count where the draw is every 200 us,
            from bytes the game's thread stores at each stage's and each
            model part's start (`coresample.h`). The device's models stage
            is 10.7 ms for 624 models where it is slow, and nothing yet
            says where in a model that goes.
          - The held-back list's sort (Session 130, continued): the
            entries' indices are sorted, not the 88-byte entries, and
            each entry then moves once (`sort_deferred`). The order is
            qsort's own; `trackview_cuts_check`'s `sort`: 40,000 lists,
            0 differ, 6 of 6 mutations caught (`draw-cuts.md`).
          - Set aside on 2026-10-18 at the user's word, the sort its last
            cut, for TASKS 60 (the damage effects). The items below wait
            for the device.
        - [ ] A device log with "CoreSample 1" and "DebugLog 1", through
          the slow stretch: the `samples, models:` lines say which parts
          of a model to cut next.
        - The desert on the device (2026-10-19, TASKS 79c's log: track
          21, build f1e1f9d, `GPULog 0`). Two stretches under 30, both
          laps alike:
          - x 1010 to 1080, y -780 to -180: 20 FPS, bound by the CPU.
            The draw takes 28 to 32 ms (models 13 to 15, mirror 4 to 6,
            cull 3, 1,000 to 1,100 models in view), the world 5 to 10;
            C 19 to 20 FPS, G 50 to 60.
          - x 1210 to 1470, y 320 to 120: 14 to 18 FPS, bound by the GPU.
            167 to 315 dust particles are on screen, and citro3d's GPU
            time is 35 to 47 ms where it is 12 elsewhere (the sprites
            are fill-bound, as above).
          - By the roadblock (x 1470 to 1620, y -40 to -340): 20 FPS from
            the world's contact rounds (8 to 16 ms, TASKS 79c) with a
            draw of 22 to 28.
        - [ ] The user's word on the envmap a face a frame.

47. [ ] **A brief artifact on the bridge before the finish line.**
        Reported on 2026-10-12, after the user played build bb70171 on
        their 3DS: "the bridge right before the finish line on my
        track ... had an artifact, I had two laps, showed both times.
        It was brief." The user brings the logs on 2026-10-13. The
        track is not named yet (two laps is a Quick Race's count). Ask
        which track and what it looked like (a flash, a gap, a
        stretched or missing triangle). The clusters (bb70171) are new
        that night and decide what is drawn near the screen's edges,
        so a run with "ClusterCull 0" over the same bridge tells
        whether they made it or it was there before; then a capture
        there, as TASKS 45 had.
        - The user's log came on 2026-10-12 (`3DS Files/nfshp2_debug.txt`,
          config "DebugLog 1", so the clusters were on). Two Quick
          Races: track 44 (Fall Winds at Dawn, 2 laps) and then track
          21 (Desert Heat). On track 44 the laps end at about frames
          13,649 and 26,918, at the same place. In the 20 s before
          each, the sun's glare is drawn (its
          4 quads, TASKS 45's change) and the police helicopter is over
          the player on the bridge, about 4 m above the deck (plan 4),
          with its dust on. The log is once a second, so a brief
          artifact itself does not show.
        - Azahar, track 44, gas only, no cops: the bridge drew cleanly
          in every shot. A run with four cops stuck on a fence before
          the bridge. The cull's planes are made again at every change
          of matrix, so they cannot go stale. Still to ask the user
          what it looked like; the helicopter (its searchlight sheet
          and dust) is the first suspect.
        - The same log: track 44 spends about a quarter of the race
          under 22 FPS. In those frames the CPU's ~19 ms and the GPU's
          ~32 ms run one after the other (50.8 ms a frame): TASKS 46's
          "GpuSends 1" is meant to overlap them.
        - [x] Session 128: the helicopter over the bridge. In bb70171
          its bombing run (plan 4) came down there on both laps, but
          `chopper_fire_salvo` was still a stub: the munitions came in
          105de48 that night. So a run then was the helicopter at
          bombing height, some 4 m over the deck and inside the truss,
          with its dust, firing nothing. Today's build fires there, as
          retail does.
          - "ForceChopper" had stopped working since TASKS 72e-1. The
            replay's snapshots (copsnap.c) clear an idle helicopter, its
            word at 960 too, so the forced one stayed in plan 6 at
            0 0 0. `forceChopperTick` sets the word again each frame,
            and "ForceChopper 6" has it follow with no bombing run.
          - Azahar (AC power, 100% speed), track 44, "ForceChopper 1",
            three cops, warped to the last stretch by
            `nfshp2_warp.txt`, gas only: the helicopter came down to
            bombing height over the bridge and its rocket hit the car on
            the deck (the fireball, the blast, the flash, then the crash
            cam at the abutment). The truss, deck and fences drew whole
            in every shot, with the helicopter among the girders.
        - [ ] On the 3DS: the user's next race on track 44 with the
          helicopter, and what the artifact looks like if it is still
          there (a flash, a gap, a stretched or missing triangle).
        - [x] Session 133 (2026-10-18), a likely cause on the device
          alone. The user's run of 792ce27 on track 21 had "the
          road/wall texture ... all staticky for a second" at the start
          and near the end, the same stretch. The prepare puts the
          track's textures in VRAM (2f0a300, 2026-10-08, before all
          three reports) through `C3D_SyncTextureCopy`, which outside a
          frame waits for the GSP's PPF event without clearing it
          first. That event is still set by the transfer before, so
          the call came back while its copy ran, and texpack.c gave the
          linear copy back at once; the next texture's linearAlloc took
          it while the GPU still read it. Azahar's transfers end at
          once, so it never showed there. `upload_chain` now waits for
          citro3d's GX queue to stop (`gxCmdQueueWait`) before the copy
          goes. Waits on the user's next 3DS run.

48. [x] **The help menu (tHelpMenu).** Found on 2026-10-12 with TASKS
        43. The frontend shows a PS2 Circle and "help" bottom left;
        retail's Circle (MENU_HELP) summons tHelpMenu over the screen
        (`FlailerScreenList::JoyHandler`, 0x0016cab0, then 0x0016ca40).
        The port has no tHelpMenu and nothing sends BJOY_MENU_HELP, so
        the mark is dead. Retail: the constructor 0x001e3b88, Summon
        0x001e3c50 and 0x001e3dd8, SplitHelp 0x001e3c98, Reset
        0x001e3db8, Dismiss 0x001e3fa0, Tick 0x001e4028, IsActive
        0x001e4170, SetHelpOverride 0x0016d448 (logs only today), and
        the event tree's SyncHelpMenu. The 3DS key needs choosing (B is
        back and A select; X is free outside car select), and the 'k'
        text then draws that key's icon.
        **The user, 2026-10-16:** "Help button can be mapped to Y by
        default". Y is MENU_SQUARE in `main.c`'s `kBinds` today (car
        select's orbit view, through joyhid's FE layout), so the screens
        that use Square need settling first.
        Done in Session 117 (`helpmenu.c`, docs/formats/help-menu.md).
        - Y slides the HELP panel in over the screen (GLOBALB's
          0x087cd45c, half a second, the backdrop fading from x 320)
          and out again. Each line's buttons draw as 3DS keys. While it
          is coming in or there, the screen, its menu and the popups
          hear nothing. The lines are each screen's HelpMenuItems, or
          the override the setups, car select and the event tree set
          (SetHelpOverride); the event tree's popup turns it off.
        - The keys: Square moved from Y to X (car select's orbit view,
          track select, the event tree, JukeBox, the credits' pause).
          joyhid's frontend layout swaps B and X. The Mode Selects'
          manual transmission is L held, as their help line says (it
          was X).
        - The bottom-left "Help" mark is BUTTONSOUT text ('k'), so
          `uirender.c` now draws a BUTTONSOUT key glyph as the 3DS key:
          Y there.
        - `helpmenu_check`, `joyhid_check` and `helpglyph_check` pass;
          `tools/run_azahar_help.ps1` passes (the main menu, Hot
          Pursuit's Mode Select and Options; A swallowed under it).

49. [x] **The joystick tables are the demo's.** Found on 2026-10-12.
        `scannertab.c` and `joyeventid.h` come from NFSHP2.ELF;
        retail's (SLES_507.31: ScannerConfigTable 0x002dc500, 230 rows
        of 36 bytes, the count at gp-23824; EventNameTable 0x002fa2d0,
        130 entries) differ: REPLAY_ERASE_DEMO at 110 moves every event
        from STEER on up one; a second glyph at +28 for the combos
        ("TRIANGLE + R2" is R2 and Triangle); retail's stick and D-pad
        glyphs (148..154); a D-pad STEER row for the pad configurations
        10..13; configurations 24 and 34 gone; the nitro's name
        "TRIANGLE + R1". FindScannerConfig (0x00155138) also differs.
        Regenerate both files from retail, then check every literal
        event number taken from a retail-only function (the Blurb's
        was one).
        Done in Session 84. `tools/gen_scanner_tables.py` writes both
        files from retail. JoyEvent is retail's: REPLAY_ERASE_DEMO at
        110, and at 133..148 the main menu's code reader's sixteen
        (JOY_EVENT_CHEAT_*, the port's names; JOY_EVENT_COUNT 149).
        Retail's glyphs from 144 are the sticks' directions, the D-pad
        and the wheel's; `helpglyph.c` maps the sticks' to the Circle
        Pad and the C-Stick. Joystick.obj and JoystickPS2.obj follow
        retail as well:
        - A type is believed after 32 reads; the demo's took 10.
        - The frame reads the pads itself, since JoypadReadInVBlank is
          never set. A pad that does not answer reads 0xff throughout
          (`joyhid.c`'s port 1).
        - TypeChangedHandler makes the cars driven from the port let
          go (World.obj's 0x0014e8c8, `realdriver_reset_port_joy_values`).
        - RestoreTypeChangedHandlers (0x001543f0) is bound for the
          replay states and the pause menu's resume.
        - GetJoystickButtonChars (0x001552d0) is ported.
        FindScannerConfig differed only in its address and stride. The
        Blurb's 126 was the one literal. `tools/joystick_check.py` runs
        retail's image: 65,880 ops, 79,028 lines, 0 differ; 266 mutations, 261
        caught, 5 equivalent (`docs/formats/joystick.md`). Not ported:
        rumble, and the code reader (TASKS 50).

50. [x] **The main menu's code reader.** Found on 2026-10-12 with
        TASKS 49. Retail's NewMainMenu constructor (its call at
        0x00216550) hands the reader at 0x0031d7e8 to 0x0024f488, which
        registers one handler (0x0024fa88, on to 0x0024f748) for
        JoyEvents 133..148 on port 0, one per button. The handler keeps
        the last eight presses in a ring (+20, the count at +52, the
        head at +56). Once it has eight, it compares them with each
        code: +12 is the codes, 56 bytes each, and +16 their count. A
        match calls 0x0024f9f8 for the code's group (+40), which clears
        +48 in every code of that group, and goes on to act on the code.
        These are the PS2 game's cheat codes. Decode what each code does
        and where the table comes from, then port it. On the 3DS the
        sixteen buttons are joyhid's DualShock 2 buttons, so a code is
        entered with the 3DS keys mapped to them.
        - [x] **50a, the reader and the 78 codes** (`eastereggs.c`):
              retail's constructor (`0x0024f420`, the image's static
              constructor 99), Start, Stop, the press (`0x0024f748`),
              the clears, the lookups and the five small ones, with the
              table at `0x0031d828` read off the disc. NewMainMenu's
              OnTick half is in `mainMenuTick` (the reader off under the
              help; "Unlocked" and the code's name, FrontendSound 30),
              and `main.c` binds car select's and track select's tests,
              the Begin of unloading's ClearTemporary and `gEggIsOnFn`.
              So the 46 car codes, the 23 track codes and the two bonus
              events work. On the main menu L/ZL/R/ZR are L1/L2/R1/R2,
              X is Square and B Triangle. `eastereggs_check`: 2,084 ops,
              1,999 lines, 0 differ; 83 mutations, 83 caught.
              `run_azahar_cheat.ps1` entered code 46 in Azahar: the
              menu said "Unlocked / Pursuit Corvette Z06 in You're The
              Cop Mode", and You're The Cop's car select went from 1 car
              unlocked of 5 to 2. Write-up:
              `docs/formats/easter-eggs.md`, with every code's 3DS keys.
        - [x] **50b, the render eggs** (`stomper.c`): retail's Stomper
              (`0x0024b918` to `0x0024c420`): StompEntry's Set and
              Clear, the Stomper's Clear, Set, Suspend, Resume and
              ClearSet, InitStomper (InitializeEverything's last) and
              the six render-egg calls, bound in `main.c`; the lists
              for eStomper 8 to 12 entry for entry. The demo's seven
              (1 to 7) only RandomRenderEgg sets, and nothing calls it:
              empty lists. Each frame suspends the egg before the mirror
              and resumes it at the end. Motion Blur calls
              `radialblur_on_off` (RadialBlurOnOff(bool, int), now
              ported and checked). Black & White (and Video Mode) is
              `eAttachBlackAndWhite` (`0x0011a9f0`): retail writes each
              pixel's green into the alpha through FBMSK `0x7fff` and
              draws it back through a grey ramp, so the 3DS copies the
              top screen (`copy_top_screen`, shared with the blur) and
              draws its green over it (`georender_draw_green_quad`),
              after the fog and before the blur, the mirror and the HUD.
              Heavy Fog is the weather query's `WeatherHeavyFog`, R/C
              Car `CarRenderMatrix` at half size, and Chrome Cars the
              environment pass's ALPHA_2, `georender_set_env_replace`.
              R/C Car's big head is AnimatedDriver's (TASKS 83); a
              NIS's black and white (the view's `+116`) waits for the
              NIS player's EnableOverrideRendering. `stomper_check`:
              1,524 ops, 1,736 lines, 0 differ, 0 facts wrong; 92
              mutations, 92 caught. `radialblur_check`: 335 steps, 3,757
              lines, 0 differ; 43 mutations, 43 caught. The port's
              `EggCodes N` config key turns codes on at boot. Azahar,
              track 42: Black & White grey with the mirror and HUD in
              colour (101 frames, none failed), Chrome Cars the map
              alone, R/C Car every car half size. Write-up:
              `docs/formats/stomper.md`.
51. [x] **The damage system (CarDamage).** Found on 2026-10-12 with
        TASKS 39. Nothing made a CarDamage, so `pCarDamage` was NULL on
        every car: no hit dented a car, broke a light or a window, or
        derated the engine, and a munition's blast never wrecked one.
        `docs/formats/car-damage.md` has the whole of it.
  - [x] 51a: the logic. `cardamage.c` ports BodyDamage and CarDamage
        whole: loader slot 17 (`0x34030`), the zones, AddDamage, the item
        levels, ApplyDamage, the environment mapping
        (`esolid_set_environment_mapping`, eModel's), the wreck, the
        repair and the destructor. `main.c` binds the constructor, the
        item parts, the destructor, the A level info, AddModel,
        AddDamage, the wreck and RepairAll. `cardamage_check` runs
        retail's code: 2,446 ops, 13,349 lines, 0 differ, and 132 of 135
        mutations caught, 3 equivalent. `loadertable_check` runs the
        environment mapping on the Viper's and the bus's duplicated
        solids: 6 of 7 new mutations caught, 1 equivalent. On Azahar a
        race ran 66 s at 100% and 28-30 FPS, and the brake lights went
        dark after a crash into the trees.
  - [x] 51b: the renderer reads strip flag `0x100`. The port's GeoBatch
        flags were baked when the car's meshes were built, so a broken
        window kept its environment map. Each batch now keeps its first
        strip, and trackview's `strip_flags` reads its Flags live
        (`geo_strip_flags`) from the engine's own entry table, which
        `esolid_set_environment_mapping` writes. On Azahar the race
        draws as before, at 30 FPS and Speed 100%.
  - [x] 51c: the vertices. DamageVertexFunction dents each vertex by its
        key, darkens it, and shows the scuff strips. The walk
        (`0x00104100`) and eStripData's accessors are in `estripdata.c`,
        and DamageVertexFunction is in `cardamage.c`. The walk ends with
        `gESolidVerticesChangedFn`, which marks each mesh baked from that
        solid dirty. A car's solid that BodyDamage walks bakes editable
        (`geobake.c`), and a dirty one is refreshed at its first draw of
        a frame (`georender_refresh`). cardamage_check: 30,452 lines, 0
        differ, 181 of 184 mutations caught, 3 equivalent. geobake_check
        bakes the 44 cars' 518 solids and changes 1,325,799 vertices
        over 2,072 refreshes with 0 faults; 22 of 23 mutations caught, 1
        equivalent. The bake's working buffers moved to the linear heap:
        on the main heap the player's cop car (CROWNVIC_A2) failed to
        bake in a race and drew as a black shadow (the user's report of
        2026-10-14). On Azahar a You're The Cop race shows the cop car
        whole, "refreshed 4 damaged meshes in 10.9 ms" and 0 bakes
        failed.
  - [x] 51d: Car::DamageAbove (`0x00135280`, `gCarDamageAboveFn`).
        `cardamageabove.c` ports DamageAbove and DamageCap
        (`0x00135490`): every drawn car's fAngleToCamera, and in You're
        The Cop the marker over each suspect, its sides cut by the
        cops' damage. Retail's eDisplayFrame runs RenderCars for views
        0 to 3 in turn, so the mirror's angle is the one the cop HUD's
        trackers read. The port draws the mirror first, so
        `rendercars.c` keeps the mirror's angles and puts them back
        after the player's view (`render_cars_keep_angles`,
        `render_cars_restore_angles`). cardamageabove_check: 1,045
        scenarios, 8,509 lines, 0 differ; 101 of 105 mutations caught,
        4 equivalent. rendercars_check, with frames of both views:
        1,321 scenarios, 22,488 lines, 0 differ; 101 of 104 caught, 3
        equivalent. On Azahar (AC power, Speed 100%) a You're The Cop
        race on track 11 ran at 30 FPS with 0 bakes failed. Green
        markers sat over the suspects, and a tracker marked a car
        behind in the mirror. `run_azahar_coprace.ps1` waits 15 s for
        Hot Pursuit's A, since a late log line had made it press twice
        into a quick race.
52. [x] **Profiles: save, load, and a save prompt after each race.**
        Asked for on 2026-10-12. The profile is retail's one save,
        `settings.db` in `sdmc:/NFSHP2/SAVES` (the folder is made on
        demand). The Options menu's Save/Load saves, loads, and turns
        autosave on or off, as retail's does. The port adds two things.
        Every race's Quit or Next Race goes through "Autosave", even
        with autosave off (`gEndGameAlwaysAskToSave`). The Autosaver
        also asks "create the save?" before it makes the file
        (`saveAskCreate`). So each race ends with a create or overwrite
        question that can be declined. Both were seen on Azahar in
        Session 86: Save, Load and Autosave on Options, and Quit Race's
        overwrite question after a quick race. A Quit from the pause
        menu leaves without a save, as retail's does.
  - [x] The popups say retail's "Memory Card (PS2)" and "MEMORY CARD
        slot 1". The 3DS has an SD card.
        Done in Session 117: `portlang.c`'s `kRetail` puts the SD Card
        in 27 retail IDs in the six languages (the card's name, its
        messages, the Load/Save help lines), with no slot and no reset.
        The two with the KB take it as `%2$d` (`formatPrompt`). The
        port's own "Save your changes to the card?" is
        `PORTLANG_SAVE_CHANGES` in six languages, "SD Card". Checks:
        langtab_check gives 27 with the port's wording, 0 wrong, in each
        language. Azahar: the Display walk PASS, its overwrite popup
        "SD Card", "Overwrite existing game settings on the SD Card?"
        (docs/formats/language-table.md, "The port's wording").
53. [x] **The debug menu.** Asked for on 2026-10-12. A panel in the
        main menu, opened by pressing L + R + D-Pad Up together there,
        or by "DebugMenu 1" in nfshp2_config.txt. It starts any track
        straight away with custom settings, unlocks everything, and
        gives NFS points. It comes after TASKS 39 (the munitions).
        Added on 2026-10-13: Start Debug Race is its own screen with
        Start Race at the top, "Set Save to 100%" completes the career
        without touching the points, and anything that changes the
        save asks whether to save on the way out.
        Done in Session 90 (`docs/formats/debug-menu.md`):
        - FRONTB's Flailer chunk is rebuilt at boot
          (`debugmenu_patch.c`): a hidden fourth main-menu item and
          two screens copied from Be The Cop Setup, Debug Menu (5 rows)
          and Debug Race (12 rows, 7 at once, scrolled).
        - Debug Menu: Start Debug Race, NFS Points, Set Save to 100%,
          Unlock Everything, Lock Everything. Debug Race: Start Race,
          Mode, Track, Time Of Day, Direction, Car, Colour, Opponents,
          Laps, Traffic, Difficulty, Gearbox.
        - B on Debug Menu, or Start Race, with the save changed shows
          the card's popup, "Save your changes to the card?". Yes saves
          on the Autosave screen, No puts the copy taken on entry back,
          and B stays.
        - Checks: debugmenu_check ok, bootflow_check 0 differ. Both
          Azahar walks PASS (`tools/run_azahar_debugmenu.ps1`, and
          with `-Cop`, which saved and put `settings.db` back
          byte for byte).
        - The user saw the popup drawn over the rows on 2026-10-13. The
          screen now hides under it, as the Pause Menu's does.
54. [x] **Text input on the 3DS keyboard.** Asked for on 2026-10-12.
        Anything that asks for typed text uses the 3DS's built-in
        software keyboard (libctru's swkbd applet) in place of a ported
        letter grid. The first is the Options menu's Player Names, the
        `NameEntry` screen (a plain screen in `kScreens[]` for now). Keep
        retail's length limit and allowed characters. Cancel keeps the
        old name. It comes after TASKS 53.
        Added on 2026-10-13: hide Player 2 (no split screen on the 3DS),
        hold the sound while the keyboard is open so it doesn't go wrong
        when it closes, and ask whether to save when leaving with
        anything changed.
        Done in Session 91 (`docs/formats/name-entry.md`):
        - `nameentry.c` is retail's NameEntry (0x0024d408 ..
          0x0024dc70). A on Player 1's name opens swkbd with
          tKeyboard's rules: seven characters, a-z A-Z 0-9 ! . # and
          the space (a filter callback), and the row's blurb as the
          hint. OK writes the name with NameFinalSelect's noise; Cancel
          keeps the old one.
        - Player 2's rows, values, bars and label are hidden, and the
          menu passes over them. Their values stay in the save.
        - The sound: every playing channel paused and the master
          volume at 0 while the applet is open; on a 3DS it fades back
          over 250 ms. Azahar stops the whole console during its
          keyboard dialog, and its audio stretcher then swings slow,
          fast and slow for about three seconds, which was the wrong
          sound. There the hold lasts 3.5 s (`svcGetSystemInfo`
          0x20000 tells Azahar from a 3DS).
        - B with changes asks "Save your changes to the card?". Yes
          saves on the Autosave screen (which asks retail's overwrite
          question when a save exists), No puts the names and genders
          back, and B stays.
        - Azahar walk PASS (`tools/run_azahar_nameentry.ps1`): OK,
          Cancel, gender, no Player 2 row, the sound back after both
          keyboards, and the prompt's stay, yes and no. `settings.db`
          was saved and put back.
55. [x] **A crash dump when the game closes.** Reported on 2026-10-12:
        closing the game from the HOME Menu, or turning the system off
        while it runs, leaves a Luma ARM11 exception dump
        (`3DS Files/crash_dump_00000002.dmp` and `..03.dmp`). The game
        must leave cleanly both ways. It comes after TASKS 39.
        Done in Session 87: both dumps are one data abort, a push onto
        unmapped memory by threadguard's thread (`guard_main` into
        LightLock_Lock, pc 0x0021b818, its stack at 0x0807e728 in the
        heap). exit() frees the heap, and the stacks of the threads
        made from it, before it ends the process, and the guard wakes
        every 10 ms. hangwatch's watchdog (every 250 ms) and the log's
        writer (a 2 s wait) were exposed the same way. Each now has a
        stop that ends and joins it, registered with atexit in
        `main.c`. On Azahar the game leaves through the screen viewer
        and Azahar is back at its list within 3 s; the device is the
        check.
56. [x] **NFS points are not kept.** Reported on 2026-10-12 with the
        debug log (`3DS Files/nfshp2_debug.txt`): a race's NFS points
        said they were saved, but the next run had none. The points
        must add up across races and survive a save and a new boot.
        It comes after TASKS 55.
        Done in Session 87: the save was loaded, then wiped. The
        port pushed the boot screens in the demo's order (0x0016aa40),
        BootAutoload over the language screen, so the card loaded
        first, and choosing a language then ran
        FrontendDatabase::InitWithDefaults on Fred. Retail's
        LaunchFrontendMenus (0x0016f950) pushes BootAutoload before
        the language screen, so the language comes first and the save
        is copied over its defaults. `main.c`'s kBootStages now has
        retail's order. bootflow_check: 96 scenarios, 0 differ, with a
        new PAL row with a save (`palcard`). On Azahar the boot loaded
        a save of 11,000 points, a cop race ended at 11,100, Quit
        saved 11,100, and the next boot loaded that file. The user
        saw the points kept on 2026-10-12.
57. [x] **The fire truck's track lags.** Reported on 2026-10-12: the
        track with the fire truck, its fire, smoke and fog, is a bit
        laggy. Find the track, profile it, and cut the cost there and
        in places like it (TASKS 46's rules: lossless). It comes after
        TASKS 58; then TASKS 53.
        Done in Session 88 (2026-10-13), to be confirmed on the device
        (`docs/formats/draw-cuts.md`, "TASKS 57"):
        - The track is 11 (Coastal Parklands); the fire's emitters are
          at about x -580 to -700, y 145 to 240.
        - The user's log there: 13.8 FPS at worst, GPU-bound (about
          50 ms of GPU against 23 of CPU draw). The GPU only started
          once the whole draw was built, so the two added up.
        - Retail's strips hold float positions and texture
          coordinates, so a smaller vertex would not be exact.
        - The frame now goes to the GPU in parts by default
          (`GpuSends` 1, TASKS 46's opt-in), with one more send
          between the envmap and the mirror. That is about 18 FPS
          expected there where it was 13.8, with the same pixels.
          "GpuSends 0" in nfshp2_config.txt goes back.
        - On Azahar the race ran whole with no hang, and the shots at
          the fire match the run without the sends.
        - Left for TASKS 46: the device's log at the fire with this
          build, the smoke's quads cut to their texture's alpha, and
          the envmap a face a frame (the user's call).
58. [x] **The car goes through things.** Reported on 2026-10-12, while
        watching a scripted cop race on Azahar: the car clips through
        the road, through walls, rails and hills, and through other
        cars. Find why, against retail's collision, and fix it. It
        comes right after TASKS 56, before TASKS 57.
        Closed in Session 87 at the user's word (2026-10-12), with no
        fault found and no code changed (HANDOFF.md, "Session 87,
        continued -- TASKS 58"):
        - The Crown Vic's `_CV` hull covers its body model to a few
          centimetres. The model only reaches past it at the tyres,
          the mirrors and the light bar.
        - Car 0's hull was checked against its track polygons and
          the cars near it every frame, and VClip was run again on
          each of its witnesses. A 70 s gas-only race had no hull
          inside a wall, floor or car, and VClip said "apart" for
          every pair but one, which was out again within the second.
        - Earlier runs flagged only the hull wrapping round the ends of
          wall segments (3 cm), and a car landing behind a rail after a
          jump at 189 km/h.
        - The bumper and in-car views hide the car and draw no dash,
          as retail's render_cars and drive camera do. Their NearZ of
          0.5 and 0.4 m is the image's, so a wall or car within half a
          metre of the eye is cut away there, as in retail.
        If it comes back, the place to look is the rail meshes against
        their wall polygons (retail data), where a scraping car's side
        can show through a rail.
59. [x] **Stereoscopic 3D on the top screen.** Asked for on 2026-10-13.
        Draw the top screen in stereo when the 3D slider is up: each
        eye's view (`gfxSet3D`, `osGet3DSliderState`, a left and right
        render target). The bottom screen has no 3D. The user said it is
        "just a task", for later, when it matters less than what is in
        hand. Mind the frame time: two views of the race at 30 FPS on
        New 3DS.
        - 2026-10-16, the user: it comes before the public launch. "You
          want 3D just move the slider up, you don't, leave it off, its
          not something you configure in-game." No option in any menu:
          the slider alone turns it on and sets its depth.
        - 2026-10-16, the user, later: "I only want 3D enabled on movies
          and in-game, not on menu navigation, title screen or anywhere
          else." The race (its world, NIS and flybys) and the movies get
          two eyes. Every menu, the title, the pause menu, the results
          and the loading screens get one image for both.
        - 59a done, 2026-10-16, checked in Azahar's side by side: the
          race's world is drawn for two eyes (`stereo3d.c`, the shaders'
          `_st` copies, docs/formats/stereo-3d.md). The right eye's far
          trees sit 10-11 px right of the left eye's, the car is on the
          screen's plane, and the HUD and mirror line up in both. The
          pause, the boot flow's 32 screens and slider 0 stay flat.
          The flicker the user saw (a stale LOADING left eye every other
          blank) was two top-screen swaps a frame, fixed in
          `__wrap_C3D_FrameEnd`.
        - 59b done, 2026-10-16: the effects' sprites and the sun take the
          eye's shift for their depth (georender's `screen_for_depth`).
          In Azahar the chimney smoke sits at +10 like its chimney (0
          before). The sun was behind trees or a hill in every test, so
          its shift is not measured.
        - 59c done, 2026-10-16: the five movies that fill the screen
          (the EA and Black Box logos, the intro, the making-of, the
          reward) sit behind it. In Azahar the two pictures are 8 px
          apart at the slider's top. The menus' panel movies, the
          credits' names and every menu stay at 0, and 3D costs the
          movies no frames there (the Black Box logo skipped 107 of 392
          frames in 3D, 104 flat).
        - The user's test on their 3DS, 2026-10-16: "Frame rate is
          pretty much the same. There is flicker on the movies, I think
          remove 3D support for movies. Depth is not comfortable at
          all." Also "if you can make it real good, do it". So 59c is
          taken back, and 59d redoes the race's depth.
        - 59d done, 2026-10-16: nothing comes out of the screen any more
          (the eye's term is `max(1 - convergence / w, 0)`). The
          convergence is a fixed 3 m instead of the car's depth. The
          eyes are 10 px apart at most instead of 12, and the sky is at
          the horizon. In Azahar: the far trees +9, the car +3 to +4,
          the near road 0 to +4 (it was down to -9), the HUD 0. The
          boot walk's 32 shots, the movies among them, are flat.
        - Closed, 2026-10-16, after the user's second test: "Remove 3D
          support entirely, I don't like it." All of TASKS 59's code is
          out. The sources are their b9556b3 selves again, and
          `stereo3d.c`, `stereo3d.h` and docs/formats/stereo-3d.md are
          gone. libctru leaves the top screen's 3D off, so the slider
          does nothing. The design and its Azahar measurements stay in
          git, in b6bd138's docs/formats/stereo-3d.md.
60. [x] **The car's particle effects (Car::TriggerEffect).** Found on
        2026-10-13 with TASKS 51a. `gCarTriggerEffectFn` is never set, so
        `Car::TriggerEffect` (`0x0011e2b8`) is skipped: a broken light,
        window or mirror throws no glass, and a radiator hit or a blown
        tire shows nothing. `cardamage.c` calls it with a `CarEffect` and
        a scale (0.1, 0.4 or 1 for an item's level), `careffects.c` with
        its per-frame effects, and `carrace.c` for each blown tire. Port
        it with a checker, over the particle system it starts.
        - Done in Session 131 (`docs/formats/car-effects.md`):
          `cartriggereffect.c` ports Car::TriggerEffect, and
          `terraineffect.c` ports TerrainEffectEmitters (`0x00222248` ..
          `0x00222594`). That object is the ground's emitters for each
          terrain, made with the World and deleted with it. Car effects 1
          to 5 come from it, and a collision's impacts and scrapes fire it
          through `gTerrainEffectTriggerFn`, so the sparks come too.
          `main.c` sets the four seams; the collision's skips a NULL
          object, which retail does not test.
        - `tools/cartriggereffect_check.py` runs retail's six functions in
          RetailEmu over its own terrain table, `eMulMatrix`, `bIdentity`,
          `bStringHash` and `~bTList<AcidEmitter>`. Over 513 ops (329
          emitter triggers, 92 groups, every list) 0 differ. Of its 56
          mutations, 54 are caught and 2 are equivalent and noted.
        - [x] Seen on the device: glass when a light, window or mirror
          breaks, steam and smoke from a hurt car, a blown tire's burst,
          smoke and dirt from the wheels, and sparks where cars hit or
          scrape. Watch the frame rate where the particles are thick.
          The user, 2026-10-18: "your new thing worked great".
61. [ ] **Cops and racers in one wireless race.** Asked for on 2026-10-14,
        for later or next: over task 37's local wireless, one or more
        players drive cops and the others race, all in the same race.
        - First find what retail's own two-player modes allow, whether
          one player can be a cop and the other a racer, and how a
          human cop's car, controls (Be A Cop's: X target, L roadblock,
          R helicopter), HUD and busts work then. Port that as it is.
        - Then the rest over the same lockstep: each console says which
          side its player is on in the lobby, a cop console gets Be A
          Cop's HUD and buttons, a racer console the racer's, and a bust
          of a human racer counts on both.
        - The user, 2026-10-14: when every player is a cop, CPU racers
          are required, at least 2 and at most 8, the human cops not
          counted in the 8. With no cop among the players, 37c-2's rule.
          A race with both cops and racers among the players: not said
          yet; ask when 61 comes.
        - Comes after 37's slices (37b-2 to 37f), which it builds on.
62. [x] **A message when wireless communication is off.** Asked for on
        2026-10-14: hosting or joining a Local Wireless game with the
        3DS's wireless communication turned off (from the Home Menu)
        shows an error saying it is disabled and must be turned on to
        use the feature.
        - First find how the system tells it: what udsInit, the scan
          or the network's creation return then, or a system state to
          read before trying; and whether Azahar can turn it off for a
          run.
        - Comes right after 37d and before 37e: one task at a time.
        - Done in Session 101 (`docs/formats/lobby.md`, "Wireless
          communication off"). The system says so on the shared page:
          NETWORK_STATE (0x1FF81067) is 7 then (`wireless_radio_off`).
          Host or Join with it off says "Wireless communication is
          turned off. Turn it on from the HOME Menu to play over Local
          Wireless." in the six languages, and UDS is never started; OK
          asks again. The same line wherever local wireless would not
          start or went with it off, when it is turned off under the
          lobby with the link up (hosting, searching, a race found,
          joined, or on a press before the tick), and back from the
          race's setup in place of the race's notice. The old line no
          longer asks about a wireless switch: "Local wireless could
          not start. Please try again."
        - lobby_check: 50 scenarios (16 new), faults 0; 104 mutations,
          101 caught, 3 equivalent. Azahar's NETWORK_STATE is always 2,
          so `WirelessOff 1` in the config takes it as off:
          `run_azahar_lobby.ps1 -Consoles 2 -WirelessOff` passed (host
          and joiner each showed the line, no "wireless: up", OK back
          to Host or Join). Without it, `run_azahar_lobby.ps1 -Consoles 2` still passed: Azahar's state does not read as off.
63. [x] **Local Wireless on the main menu, the settings after Host.**
        Asked for on 2026-10-14: a top-level "Local Wireless" entry, and
        the race's settings chosen once Host is pressed, not before.
        Setting a race up and then picking Players, Local Wireless and
        OK confuses people.
        - The flow: New Main Menu, "Local Wireless", then Host or Join.
          Host goes to the mode: Hot Pursuit or World Racing, then
          Single Race, Knockout, Lap Knockout, Free Run or You're The
          Cop. Then retail's setup screen for that mode, and only then
          the lobby opens to players. Join searches and joins as now,
          and takes the host's settings.
        - Challenge's Players row goes back to 1 alone. There is no
          split screen on the 3DS (TASKS 30), and Local Wireless is no
          longer reached from there.
        - First find how New Main Menu's items are built (retail's
          Flailer screen) and how to add a port item to it in retail's
          style, as bsetup.c's "Local Wireless" label was.
        - Comes right after 37e and before 37f, 37g and 61, which build
          on where the lobby and the setup are: one task at a time.
        - Done in Session 103 (`docs/formats/lobby.md`, "The host's
          setup"; `docs/formats/debug-menu.md`, "The chunk"). The main
          menu's fourth row is Local Wireless, under Options, the debug
          menu's hidden row the fifth: `debugmenu_patch.c` cuts the
          panel's bottom filler to a separator and puts both rows in
          the 113 px it covered, each a copy of Options' row a row
          down. Its highlight shows the lobby's blurb; its select goes
          to the lobby. Host asks "Which mode will you host?", Hot
          Pursuit or World Racing (retail's 10023 and 10022, the last
          one hosted highlighted), sets the cops as the main menu does,
          and goes to retail's Challenge, Players held at Local
          Wireless (`lobby_on_setup`, `wirelessPlayers` only then). Its
          select comes back to the lobby, which pops the setup's screens
          and hosts; BACK from the Challenge asks the mode again.
          LOBBY_MSG_START carries the host's game type and cops, which
          a client puts in Fred before its car select. Players
          elsewhere stays at 1 (the setup hook: pad port 0 only).
          You're The Cop over wireless is TASKS 61's.
        - debugmenu_check ok; lobby_check: 58 scenarios (8 new), faults
          0; 130 mutations, 127 caught, 3 equivalent (26 new, all
          caught). bootflow, bscreens, carsel, challenge, setup,
          racesetup(s), tracksel, netrace: 0 differ / faults 0.
          `run_azahar_lobby.ps1 -Consoles 2 -Race`: both PASS, the
          main menu's Local Wireless, World Racing and the Challenge to
          hosting, B told cops off, GO on one seed, every logged
          frame's parts the same; with `-CopsOn` the same through Hot
          Pursuit, B told cops on, 4 cops in the race.

64. [ ] **The road vanishes for a moment after the first chase starts.**
        Reported on 2026-10-14, after the user played build 4988138 on
        their 3DS (`3DS Files/nfshp2_debug.txt`, "DebugLog 1"): "when I
        first started the race, right by where a cop started chasing
        me, I saw a minor graphical artifact", and then, asked what it
        was: "I meant in the road, it like glitched out for a second,
        like disappeared and came back". "I want all graphical
        artifacts fixed."
        - The race: a Quick Race on track 31 forwards, 2 laps, 3 AI,
          4 cops, car 19 skin 4. The first chase starts at world 54.1 s
          (log line 2804).
        - Where, in the user's words (2026-10-14): not in the jump, "it
          was at the curb turn, right by the traffic cones ... it
          glitched out for a sec and disappeared when drifting". The
          log has that corner at world 58 to 60 s (lines 2919 to
          2997): car 0 from 307 276 to 242 219, braking and steering
          at 58.1 s, one wheel down at 59.1 s, the camera in visible
          zone 23 throughout (no other zone within 70 m of it).
        - "Azahar can't reproduce it, so don't try any tests": the
          cause is the device's own. Session 104's burst capture of the
          jump cam was the wrong place and is gone.
        - The other artifacts, after it: the thin dark line just right
          of the mirror's frame (every Azahar race, top screen x 273,
          y 11 to 44) and the light-blue wedge (Session 37).
        - [x] The mirror's dark line (Session 105): the RVM images start
          at the mask's column 1, so its column 0 kept the view's alpha
          of one and DisplayRVMs' fold drew it dark.
          `display_rvm_images` draws the mask again over that column
          with an alpha of 0 (`docs/formats/camera.md`, "Column 0").
        - [ ] The road's blink: not found from the log and the data
          alone (Sessions 104 and 105). What the corner has, second by
          second (world 57.1 to 62.1 s): the track drew 82, 37, 40, 86,
          104 and 86 pieces but 15061 to 15879 triangles, so the road's
          big pieces were in every sampled frame and the drop was the
          small ones a camera facing open desert culls; the camera
          stayed 1.9 to 2.0 m over the road and the drivable verge
          (`camclear.py`), never near its 0.5 m near plane; no skid
          smoke (0 particles, 0 sprites); 3 cones knocked loose (14 to
          16 dynamic bodies). The road's triangles are 7 to 12 m, its
          baked shadow layer SHD_S20_CHOP3 1.4 to 3 cm over it. The one
          thing on screen only then: the sun, 4 quads from 58.1 to 62.1
          s, its 32 by 32 rect all sky at 59.1 and 60.1 s, alpha 51 at
          60.1 s, the 550 and 600 pixel halo and rays added over the
          road as the drift turned the view to it. TASKS 45 and 47,
          both of the user's earlier artifacts, came with the same
          glare. Ruled out on top: the fog textures, the vertex rings,
          early depth, the mip chains, NaNs in the smokeables' matrices.
          Waits on the user's next look at that corner on their 3DS.
        - [x] Session 133: the VRAM upload's copy, given back before
          the GPU had read it (TASKS 47's note), fixed. The likely
          cause of all three of the user's brief road artifacts.
        - [ ] 2026-10-19: still there on build 6f090e6. The user paused
          right after seeing it ("look where I paused specifically,
          that's the area where I see the road briefly glitch out"):
          log line 9367, the same corner on lap 2, car 0 from 248.9
          219.7 at world 218.956 s to 226.4 212.4 at 219.977 s, slowed
          to 6.6 m/s against the verge (resolve 2.83 ms, 20 rounds).
          Again the sun only then: 4 quads, alpha 51, its rect all sky,
          the second before 0. Nothing else odd in the once-a-second
          lines: 29.5 fps, worst frame 49.9 ms, worst send 2.80 ms, 0
          dropped or failed anywhere. Read again and ruled out (Session
          138): georender's strip and model caches and the cull planes
          they feed, geocull, c3dwrap's patching (it never touches a
          sent part), the command buffer guard, the scenery cull (its
          frustum is the draw's, conservative), the sun's GEQUAL core
          and its depth read-back, the fog texture writes, the GPU
          timing replays (off, GPULog 0).
        - [x] Session 138: the pause's frames. With "DebugLog 1" (and
          "PauseFrames", on by default; since af182fb "PauseLog 1"
          alone, off by default) a race keeps its last 96
          frames at 200 by 120 (a display transfer each frame start,
          before the clear) with each frame's numbers, and a pause
          writes them to `sdmc:/nfshp2_pause_N.bin` (8 a boot) and a
          "pause frame k" log line each. `tools/pause_frames.py` makes
          PNGs, a contact sheet and the frames least like their
          neighbours. On Azahar every 8th picture came out in shifted
          strips until each got a 48 KB page-aligned slot (Azahar's
          surface cache; 62 clean pictures after). Next: the user
          pauses as soon as it blinks and sends the .bin with the log;
          the pictures show what blinks, the numbers whether the CPU
          dropped it.
        - [x] Session 139: found in the pause frames. The user's three
          pauses at the corner (2026-10-19, `nfshp2_pause_1.bin` to
          `_3.bin`, build 049c9e9): the blink is pause 1's frames 77 to
          80 and 83 to 86, and pause 3's 85, 86, 88 and 89. In those
          frames one batch alone changes: the asphalt, ST_NEWROAD4 in
          RD_SECTION20_CHOP3 (texture 3), on the screen's right, shows
          the sea's teal in its exact outline. Its edges, the sand, the
          baked shadows (SHD_S20_CHOP3) and the curb mark stay. The sea
          (WATER, order 1, depth written, alpha blended) is under the
          road everywhere and drawn after it, so the asphalt's colour
          was drawn and its depth lost (Session 140: or not drawn at
          all; the frames cannot tell the two apart). Ruled out on the
          way: the
          cluster cull, a stale cull matrix, the run cache's pass and
          depth state, the alpha test (the asphalt is a gloss texture,
          so it has none), the shadow layer's depth, the texture
          cache, the lean draws' words, the command buffer guard.
        - The cause as Session 139 had it, wrong (Session 140):
          citro3d's `C3D_RenderTargetClear(top,
          C3D_CLEAR_ALL, ...)` is one GX_MemoryFill, the colour on the
          PSC's first fill unit and the depth on the second. For a
          fill with both buffers GSP signals the first unit's end alone
          (3dbrew, "GSP Shared Memory"), and libctru's queue
          (gxqueue.c) hands GSP up to three commands at once and
          ignores PSC1's interrupt. So the view's command list can
          start while the depth fill is still going: a draw early in
          the list keeps its colour and loses its depth to the fill's
          end, which is the buffer's end and the screen's right. It
          needs the list queued right behind the clear. The GPU sends
          made that possible (on by default since b3b9bab, 2026-10-13,
          the day before the first report): with few models to build,
          as when the view swings to the open sea and the sun, the CPU
          queues the list while the GPU is still on the mirror. Azahar's
          fills end at once.
        - [x] The change (4803cfc), which did not fix it: c3dwrap.c
          wraps C3D_FrameBufClear, so
          a clear of both is two fills, each on the first unit, and the
          list queued after waits for both. Every target's clear goes
          through it: the view, the mirror, the envmap faces, the
          frontend's, and citro2d's C2D_TargetClear. A frame's GX queue
          gains up to 8 entries (14 of 32 used before).
        - [x] The user's run past the corner on 4803cfc's CIA
          (2026-10-20): "Unfortunately blink still happens". The fill
          race cannot happen: GSP runs the GX commands in its queue
          one after another (citro3d's FrameEnd queues the list and
          the display transfer together), so no list starts before a
          fill has ended. The two fills stay, as they cost nothing
          seen; c3dwrap.c's comment says they fixed nothing.
        - [x] Session 140, also ruled out: the near plane and the guard
          band (the asphalt's triangles are 8.6 m or more from the
          camera, |x/w| 2.7 at most); the index offset's 28 bits (the
          linear heap ends at 0x27000000); a texture let go of, or a
          model skipped by the command buffer guard (pause 1's log: 0
          evicted, 0 missing, 0 skipped); the alpha test again
          (ST_NEWROAD4's alpha is 252 in every texel, so no test cuts
          it); the early depth test (the game never turns it on). The
          pause notes' tris are the whole mesh's, so they cannot show a
          dropped batch. The camera rebuilt from the logged pose is
          off (IoU 0.31 against the asphalt's pixels), so labels per
          pixel from it are not to be trusted.
        - [x] PauseLog (af182fb): the pause's frames and their .bin need
          "PauseLog 1" in nfshp2_config.txt, 0 when it is not there
          (the user, 2026-10-20). It opens the debug log itself, as
          GPULog does. "PauseFrames" is gone.
        - [ ] Next, two runs past the corner with no new build, each
          with one line added to nfshp2_config.txt: "GpuSends 0" (the
          frame goes to the GPU as one list), then "ClusterCull 0"
          (each batch drawn whole). The sends went on by default the
          day before the first report (b3b9bab), so they are still the
          first suspect, whatever the mechanism. Whichever run has no
          blink names the part.
        - [ ] Then a build that only logs: for the asphalt batch each
          frame, whether render_model reached it, the cull's answer
          (in, part, out), the runs and indices drawn, and the GPU
          state at its draws (depth test and mask, alpha test, blend,
          buffer offset, index registers) from a shadow of the
          registers each send writes; blink frames against good ones.
          No Azahar runs: "Azahar can't reproduce it".

65. [x] **The FPS dip in the same race.** Reported with TASKS 64:
        "there was a minor FPS slowdown too at one point, locate that
        and fix it too". The log's worst second is at world 185.8 to
        186.8 s (lines ~6902 to 6936): 23.1, then 10.7, then 20.2 FPS,
        with every draw part up at once (draw 70.5 ms, mirror 17.3, sky
        13.0, models 15.8, bottom 13.9; citro3d CPU 70.2, GPU 21.3),
        while the chopper was busy (plan 4) and 264 flares were asked
        for, 132 drawn. Find what the frame waited on and fix it, as
        TASKS 46's rules say (lossless).
        - [x] What it waited on, from the log (Session 105): not the
          draw. Each stage with a mid-frame send in it was about 10 ms
          longer (mirror, sky, models, bottom), every other stage as
          before (envmap 2.9, scenery 1.5, cars 3.2, hud 0.9), and the
          counts as in the seconds around it. The same corner on lap 2
          and the chopper as close elsewhere were at the usual rate.
          A send's flush was a request to GSP's thread
          (`GSPGPU_FlushDataCache`), which makes the kernel's call for
          us; GSP slow to answer for those 3 s fits.
        - [x] The sends flush by the kernel's own call
          (`svcFlushProcessDataCache`, `hangwatch.c` `flush_heap`), the
          same work with no wait on GSP. `app.rsf` allows it
          (`FlushProcessDataCache: 84`, checked in the built CIA's
          exheader). A homebrew launcher's 3DSX still asks GSP; a
          failed call goes back to GSP for good; "KernelFlush 0" turns
          it off. Each send is timed: the log's `sends:` line, after
          the cars' (`frame-profiler.md`, "The sends").
        - [x] The next device log: no slow second with the send stages up,
          and the `sends:` line's flush and worst small. The user's log
          of 2026-10-16 (track 16, 3 AI and 4 cops, 278 s) was made with
          the kernel's flush, and it says so ("gpu sends: the linear
          heap flushed by the kernel"). Session 128 read it:
          - The dip's mark is gone. In the dip the sky and the bottom
            screen took 13.0 and 13.9 ms; here they are at most 1.3 and
            2.0 ms, in every second.
          - A send's flush is 0.46 to 0.53 ms a frame, its queue part
            about 0.1.
          - The log's ten worst sends are 3.9 to 10.6 ms, in the queue
            part. Seven of their seconds are at 29 to 30 FPS, and three
            are slow ones (15.1, 23.5 and 26.9 FPS) whose GPU or draw
            was up as well. In every other slow second the worst send
            is under 0.7 ms.
          - The log's slow seconds (48 under 20 FPS) are the GPU's,
            32 to 47 ms, or the draw's CPU, up to 30 ms with 4 cops:
            TASKS 46's.
          - Track 31's corner itself is on the launch checklist's
            hardware list.
66. [x] **Hot Pursuit 2's icon, banner and banner sound.** Asked for on
        2026-10-15: the logo as the icon, a 3D logo that spins as the
        banner (assets for it in the CIA only), and an engine's rev or a
        siren. `tools/make_banner.py` makes all three from the retail
        files into `3DS Files/meta/hp2` (git-ignored); build_cia.ps1
        runs it and the Makefile packs it, or the placeholder without
        it. HANDOFF.md Session 110.
        - [x] The user's first look (a video, 2026-10-15): every picture
          upside down, the background turning with the badge, the
          default chime, and the HOME Menu's cached icon. Fixed:
          textures top row first, the background on a billboard, a
          stereo WAV, publisher Octoblimp, no description, version
          1.0.0. Session 110, continued.
        - [x] The user's next look on their 3DS, after deleting the old
          title in FBI: "It worked perfectly!" (2026-10-15). The badge
          turns in front of the still oval, the siren plays, the icon
          and title are new.
67. [x] **Select Car's car icons are off their boxes.** Reported on
        2026-10-15: a friend testing multiplayer on a 3DS photographed
        it, on the build before Session 112 (the CIA with the working
        graphics, 80b7324). The user: "its not aligned to the box". In
        the row of car icons under the car, the highlight box on the
        first icon and the icon do not line up. The box's left half is
        empty, and the icon starts at the box's middle and runs past its
        right edge. The icons after it look shifted the same way. The
        profile was new ("Cars Unlocked: 7/49", "NFS Points: 0"). The
        photo is `out/carsel_icons_offset_2026-10-15.webp`
        (git-ignored).
        - Check it on Azahar first, from the main menu and from the
          wireless lobby. If only the 3DS shows it, look at the GPU
          (the icons' texture size, rounding); if Azahar shows it too,
          look at the layout (`bcarsel.c`, SC-1's row of icons,
          `docs/formats/car-select.md`).
        - Compare with retail: the user's PCSX2 photos of the retail
          frontend (2026-09-28) and `carsel_check`.
        - [x] Session 128: the layout, in a wireless race only. A Local
          Wireless race has `Fred.NumPlayerCars` 2 for its consoles (the
          host's setup, whose Players reads Local Wireless, and a
          client's `lobbyStarted`), and car select took 2 for retail's
          two pads: on "Select Car", the one-player screen, it ran the
          two-player selector. That row's base is 395 where one
          player's is 377, so the icons stood 18 pixels right of their
          boxes, half an icon, as in the photo. The same selector had
          the two-player camera (the car close, from behind, as in the
          photo), no orbit, no nebula, and the two-player help and
          logos. From the main menu the row was right.
          - `bcarsel.c`'s `consolePlayers()` is 1 in a wireless race
            (the new `wirelessRace` hook, main.c's `netrace_active`),
            and every two-player check in car select reads it.
          - carsel_check passes: 8366 ops, 513647 lines, 0 differ (the
            hook is NULL there, retail's).
          - On Azahar (AC power, 100% speed),
            `run_azahar_lobby.ps1 -Consoles 2`: both copies reached
            Select Car from the lobby, and each showed the one-player
            selector. The car stands whole and side on under the
            nebula, and the highlight box sits edge to edge on the
            Speedster's icon, on the host and on the joiner.
          - Not run on a 3DS. The friend's next wireless test will show
            it; it is on the launch checklist's hardware list.

68. [x] **The main menu's order, and scrolling.** Asked for on
        2026-10-15: "I also want scrolling up and down implemented on
        the main menu if there's too many items to fit at once. Every
        option should be above "Options" except "Debug Menu" so "Local
        Wireless" should be above "Options" not below it".
        - The order: Hot Pursuit, World Racing, Local Wireless, Options,
          then Debug Menu once shown, the only row under Options. A row
          the port adds later goes above Options too.
        - The panel holds five rows (55 px apart, the 45 px masks and
          10 px separators). Past that the rows scroll: the highlight
          moving off the last row shown brings the next one up, and
          likewise at the top.
        - Done before the rest of TASKS 37, then TASKS 67, then career
          (the user's order of the same day).
        - [x] Done in Session 112 (`docs/formats/debug-menu.md`, "The
          main menu's order"). `debugmenu_patch.c` keeps the rows in
          that order and writes each one's label and mask to its slot;
          `bmenu_reorder` sorts the menu the same way, so Up and Down
          go by the rows drawn. A window of five rows follows the
          highlight (`debugmenu_main_show`), and the rows are laid out
          again after each frame's tick, over the slide-in's groups
          (`debugmenu_main_tick`). debugmenu_check (the scroll with 3,
          4 and 5 rows, and a tick after each step; 18 of 18 hand
          mutants) and bmenu_check (the reorder, 0 differ) pass. On
          Azahar: the order, Debug Menu under Options, and, in a test
          build cut to three rows, the window moving down to Options
          and the same three back from Options.

69. [x] **Career, 100%.** Asked for on 2026-10-15: "When you're done
        with this task, work on career, get career 100%, and as long as
        everything's fully implemented, excepting little things like
        working on multiplayer, lmk if its good for a public launch and
        I'll launch it". Career is the two event trees, Championship
        (World Racing's "World Championship") and Hot Pursuit (Hot
        Pursuit's "Ultimate Road Racer"), 32 events each.
        - What the port has: the trees, their state in Fred, the
          unlocks (`eventtree.c`, RE-6a), the event being raced
          (`raceevent.c`), the races an event sets and its cars
          (`eventrace.c`, `fredevent.c`), and the end screens (Reward,
          Events Unlocked, Tourney Standings; `endevent.c`). The flow's
          way back from a race already pops to "View Event Tree" for
          game types 8 and 9.
        - What it lacks: the "View Event Tree" screen itself, retail's
          tEventTreeView (`0x001f5dd0` .. `0x001fbb00`, about 6,000
          instructions, many of them retail-only). It is registered to
          the empty callback, so it draws its chunk and A does
          nothing. Under it are tEventLeaf, tEventGroup, tEventBlurb,
          tParallaxer, tTreeDetails (the event's panel and its
          StartEvent) and tTreeReward with retail's new reward view.
          EventTree's own BuildTree, Update and Render are dead code
          (nothing calls them).
        - [x] 69a: the decode, `docs/formats/event-tree-view.md`: the
          retail layout, every function, the view states, the
          messages, and the Flailer objects, textures and models used.
        - [x] 69b to 69e (Session 114): `eventtreeview.{c,h}`, the
          whole of tEventTreeView, its leaves, groups, blurb,
          parallaxer, details, reward, car logos, track logo and help
          popup, drawn through the renderer's new copy queue
          (`uirender_queue_copy`). No checker against retail yet: it
          was ported by hand and played on Azahar
          (`tools/run_azahar_career.ps1`). Both trees open, the D-pad
          moves between events, A shows the details, Square shows the
          reward, and A starts the event into Select Car with its cars.
          B from Select Car comes back to the details. The Mode
          Selects' rows now write Fred's game type (`setEventTree`).
          Not ported: the reward's turning model (ModelViewer.obj) and
          the help menu (tHelpMenu).
        - [x] 69f: an event end to end on Azahar, in each tree: the
          tree, the event's panel and Select Car are done. Still to
          play: the race, the end screens, and back to the tree; a
          tournament's and a knockout's later races; the result saved
          and the next event open.
          - Done 2026-10-16: Championship event 1, a single race, from
            the tree through Select Car, the race, Events Unlocked, the
            reward, the results, the best times, the End Game Menu and
            the autosave, back to the tree with events 2 and 3
            unlocked. `run_azahar_career.ps1 -Race` drives it, with the
            new off-by-default "TestFinish n" (configitems.h), which
            finishes a lone console's race n seconds after GO. The user
            played the End Game Menu by hand and said it returns fine.
          - Done 2026-10-17 (9e63bc8), all on Azahar with
            `run_azahar_career.ps1 -Race`, which now answers the End Game
            Menu (Next Race, or Quit after the last race) and says Yes to
            each autosave:
            - The save across a reboot. The autosave's question starts on
              No, as retail's does, so A alone skips the save. With Yes,
              the tree after a reboot still has the events opened.
            - Championship event 6, the 3-race Jaguar XKR Tournament: race
              1, Tourney Standings, Next Race, the save. After a reboot
              the tree reopens on event 6, and A resumes at race 2's
              track without car select (retail's resume). Race 3, the
              standings (30 points), Event 6 Passed with Scenic Drive II,
              Quit, the save, back at the tree.
            - Event 2, the time trial: passed with the new off-by-default
              "TestFinishTime s" (the player's lap; 2:00.00 against
              3:05.00). The CL55 AMG was earned and events 4 and 5
              opened. The projected lap (3:54.50) fails it, rightly.
            - Event 5, the race knockout: 3 races, 4 cars down to 2, Next
              Race twice, Event 5 Passed, back at the tree.
            - Hot Pursuit's event 1, the Lotus Elise Delivery (point to
              point, 6 cop cars): Events 2 and 3 unlocked in Ultimate
              Racer, the save, back at the tree.
        - [x] 69g: the rest: the Ultimate event, the unlocks in Quick
          Race and Select Car, Hot Pursuit's Be A Cop events.
          - Done 2026-10-17, all on Azahar with `run_azahar_career.ps1
            -Race`:
            - Hot Pursuit's event 5, the first Be A Cop event: 3
              arrests, Event 5 Passed, the Pursuit Crown Victoria
              unlocked (14 of 49 cars), Pursuit Results, the End Game
              Menu, Quit, the autosave, back at the tree. With
              "TestFinish" on, a Be A Cop race arrests each racer through
              the game's own pullover, and the last arrest wins it.
            - The unlocks: Select Car's "Cars Unlocked: 12/49" is the 7
              cars open from the start, the 3 event cars won (TS50, CL55,
              Elise) and 2 points cars. Quick Race's Select Track locks
              the tracks no event has given yet ("tracksel locked:" in
              the trace), and Scenic Drive II opened after event 6.
            - The Ultimate, event 32, the Hot Pursuit 2 Championship
              Duel. Both trees share it, as retail's do (Fred's
              pUltimateState). The debug menu's new "Open the Ultimates"
              wins every other event of both trees and leaves the two
              Ultimates open (`-OpenUltimates`). The tree then opens on
              retail's popup ("It's time to take the big prize!"); A
              closes it. The duel: 2 Ferrari 360 Spiders, 6 laps of
              Coastal Parklands, Event 32 Passed, the Ferrari 360 Modena
              Challenge unlocked, "Go to the Credits Menu to view your
              Reward Movie", the save, back at the tree. From Hot
              Pursuit's tree the same event shows passed and races again,
              with Tickets in its results.
          - Fixed on the way:
            - The popup's text is in its own object's font and colour
              (FRONTB's narrow face, grey), as retail draws it. In the
              details' white it was unreadable on the bright picture.
            - The bottom screen showed the tree's authoring placeholder
              ("This is The Title of the Event...") under the popup.
            - Long event descriptions lost their end: the translated
              strings' ring held 256 bytes, and the longest is about 360.
            - '@' breaks a line in wrapped text, as it does in all of
              retail's text.
          - Not ported: the reward's turning car model (ModelViewer.obj),
            and the Credits menu the reward text sends the player to
            (verdict list 3).

70. [x] **The bottom screen, reworked before the launch.** Asked for on
        2026-10-16, after a look at the career's details page: "before
        I'll launch the game publicly, the bottom screen has to be
        reworked".
        - With no text to show (the loading screen, the language
          screen, and so on): only the NFSHP2 logo, centred on black.
        - With text to show: make it look nicer and official, like an
          NFSHP2 dialog, reskinned in the retail frontend's art.
        - Drop the screen's name from the top left (for example "VIEW
          EVENT TREE"). The user said the current panel "looks like
          AI".
        - Done in Session 114 (`main.c`, `drawBotDialog`). Played on
          Azahar with `tools/run_azahar_career.ps1`: the language
          screen, the main menu, the Mode Select, the tree, the details,
          the reward and Select Car.

71. [x] **The plain Options screens, before the launch.** Item 3 of the
        2026-10-16 launch verdict. Each of these draws, but A does
        nothing on it (`bgf_plain_screen_callback`), or it is not
        registered at all:
        - [x] 71a: Credits (CreditsScreen 0x001f1f38): Electronic Arts
              and Black Box Games scroll the credits (CreditsScroller,
              screen 39c4c62c). View Intro Movie, The Making of HP2 and
              View Reward Movie play their movies. The reward movie is
              grayed until both Ultimates are won (0x002026f8).
              - Done in Session 116 (`credits.c`, docs/formats/credits.md):
                the menu sliding on over Options, both rolls with their
                $RGB/$FONT markup over the CREDITS_BG slideshow, Y to
                pause, Black Box's logo going on to its roll, and the
                four movies. `tools/run_azahar_credits.ps1` passes.
              - Fixed on the way: GetTranslatedString (`fredTranslate`)
                held 64 bytes, and cut the headings ("Senior Development
                Direc"); it holds 512 now. The text clip
                (`poly_clip_box`) is what keeps the lines in the panel.
              - The card needs REWARD_EN/FR.AVI and MAKEOF_EN.AVI (349
                MB) from the disc for the last two rows. Without them the
                rows go straight back to the menu.
        - [x] 71b: Audio (AudioOptionsScreen): the seven volume
              sliders, Audio Mode, Jukebox, Default Volumes and Default
              Jukebox. Ask to save when it is left with changes.
              - Done in Session 116 (`audiooptions.c`,
                docs/formats/audio-options.md): the sliders easing to their
                volumes, the scrolling list, Audio Mode, JukeBox Music
                (genres, tunes playing as picked, each tune's status, L
                for a genre on or off, the favourite line), both
                Defaults, and the save prompt (Yes to the Autosave
                screen, No puts the options back, B stays).
                `tools/run_azahar_audio.ps1` passes.
              - Audio Mode is Mono / Stereo / Surround, the user's pick of
                2026-10-16: retail's Dolby Pro Logic II plays and shows as
                the 3DS's Surround output. Fixed on the way: Prologic
                skipped `bsnd_set_voice_volume`, so every volume froze in
                that mode.
        - [x] 71c: Display (tDisplayOptionsScreen): Track Map,
              Rearview Mirror, Units, Leaderboard, Jump Cams, Zone Cams
              and Player 1 Options. Player 2's row is hidden.
              - Done in Session 116 (`displayoptions.c`,
                docs/formats/display-options.md): the six settings, Player
                1 Options opening Customize P1 HUD (lookback, camera
                spring, gauges, position, lap info, split time, score),
                and the save prompt over both pages (Yes to the Autosave
                screen, No puts the display and HUD settings back, B
                stays). Player 2 Options and Calibrate display offset are
                hidden, so the list never scrolls.
                `tools/run_azahar_display.ps1` passes.
        - [x] 71d: Controller (JoystickPreConfig): Configuration
              (JoystickConfigScreen). Calibration and Vibration have
              nothing to work on with a 3DS, and Player 2 is hidden.
              **The user, 2026-10-16:** "I would like ZL to be the cop
              boost button ... add icons for ZL, ZR as well ... make
              whatever controls you have now (including ZL for boost) the
              default, and make it user-changeable".
              - [x] The keys as tables (Session 116): `joyhid.c`'s
                `gJoyHidBindings`, a racer's and the cop's, each action on
                one of ten keys (A, B, X, Y, L, R, ZL, ZR, D-pad Up and
                Down) and pressing its configuration 30 button. The
                defaults are the old map with the cop's boost on ZL and
                its shift down on D-pad Down. `joyhid_cop_calls` makes the
                calls from whatever keys hold them, and the help glyphs
                follow the tables. ZL and ZR's icons drawn again, bold and
                the cell's full width. `joyhid_check` and
                `helpglyph_check` pass, with changed bindings too, and an
                ad-hoc pass of 34 mutations was all caught.
              - [x] The remap page: Configuration as a list of the
                actions, Racer and Cop on its arrows, A then a key to
                bind (the key's old action takes the moved one's key),
                the bindings in a file of their own beside settings.db,
                and the save prompt when it is left changed. The
                DualShock picture, Calibration, Vibration and Player 2's
                rows hidden.
                - Done in Session 116 (`joyconfig.c`,
                  docs/formats/controller-config.md): PreConfig with
                  Player 1's Configuration only, the Configuration page
                  with every action's key as its 3DS icon, START stopping
                  a wait, X the shown table's defaults, a bind that would
                  leave the throttle or brake keyless refused, and the
                  save prompt. The keys go in NFSHP2/SAVES/controls.bin
                  (30 bytes) with settings.db and load with it. The
                  bottom hint is two lines, A and B over X (the user,
                  2026-10-16: one line was cut off). `joyhid_check`,
                  `helpglyph_check` and `tools/run_azahar_controller.ps1`
                  pass.
        - [x] 71e: the pause menu's Options ("Pause Options", "Pause
              audio", "Pause display"), View Objective ("Race
              Objective") and View Cop Controls ("Pause BAC controls").
              None of them is in `kScreens[]`, so ChangeToScreen finds no
              screen for them. `screen_registry.py --check-port` missed
              them: pausemenu.c names them through constants.
              - Done in Session 116 (`pauseoptions.c`,
                docs/formats/pause-options.md): the five pages on one
                shared base (the bloom, the value's bloom, the arrows).
                Options changes Damage, Handling, Transmission, Jump and
                Zone Cams at once, through the replay's special events 1
                to 5 applied directly. Audio has the five sliders, put
                into bSound when the page closes, and the mode at once.
                Display has all twelve rows with retail's grays, and
                `Player::CycleHud`, which the HUD hotkey now uses too.
                The objective and the cop's two pages of controls are
                on the blurb screen. START resumes from every page but
                the cop's.
              - Vibration is hidden on Options and the rows under it
                move up. While paused, the bottom screen shows the logo
                instead of black.
              - Tested in Azahar, in a quick race and a SkipFE Be A Cop
                race: every row, every page, B back and START resuming.
                `screen_registry.py --check-port` passes the four
                others. It calls "Pause BAC controls" unregistered on the
                disc, but the name is in the ELF's strings; its
                FlailerScreenConfig is one the tool does not parse.

72. [x] **Replays: the instant replay, the replay after a race, and
        attract mode's.** The user asked on 2026-10-16 whether replays
        work: they do not. main.c's `replayStandIn` is an empty
        ReplayManager that records nothing, and `bRepeat` is not
        ported. So the pause menu's View Replay is always grayed, and
        RCSTATE_INSTANT_REPLAY, RCSTATE_AUTO_REPLAY and the replay demo
        never have anything to play. Porting it means:
        - retail's ReplayManager (its snapshots, interesting events and
          GetData/AddData on bRepeat);
        - the replay cameras;
        - the pause pages' changes recorded as special events
          (pauseoptions.c applies them at once today).
        **The user, 2026-10-16:** "For replay feature, implement that
        after task 59". So it comes right after the stereo 3D slider
        (TASKS 59), before the known bugs and the launch verdict.
        **The user, 2026-10-16, later:** "I want to test the game on
        real hardware once task 59 is 100% done before you continue to
        task 72". So this starts after their report.
        **2026-10-16, later still:** the report came, and 3D is out
        (TASKS 59). So this is next.
        **How retail's replay works** (the survey, 2026-10-16): it plays
        nothing back from a recording of the cars. It runs the race
        again.
        - From GO, `MarkTheBeginningOfTime` takes a 200 KB `bRepeat` (the
          stream of every frame's pad events and timestep) and 17
          snapshots of 38232 bytes, if 835 KB is free.
        - A snapshot is a memory image of every simulated object. 99
          `DoSnapshot` functions move each one's fields in and out
          (`ReplaySnapshot::MoveData`).
        - A replay restores a snapshot and runs the world again on the
          recorded stream. When it catches up with the race, capture
          goes on.
        - So the port's simulation has to be deterministic. Wireless
          lockstep already needs that.
        - The attract mode's replays are such files from the PS2:
          `REPLAY\JUL23\T11BlueElise.bin` and four more, on the retail
          disc.
        The slices, one at a time:
        - [x] 72a. `ReplaySnapshot` and `bRepeat`: the snapshot's image
          (Init, the MoveData family with its sections, the checksums,
          WriteData, ReadData, VerifyData), and the stream's channels
          (PrepareToAddData, AddData, PrepareToRemoveData, RemoveData,
          the locations, its DoSnapshot). The Codeine calls are the PS2
          dev kit's host link, so they do nothing.
          **Done in Session 120:** replay.c and the new brepeat.c, in
          retail's layouts. `replay_check` runs retail's own code: 0
          differ, 186 of 188 mutations caught and 2 equivalent.
        - [x] 72b. The snapshots of the cars and their physics: Car,
          PhysicsCar, RigidBody, Wheel, Suspension, the steering,
          Aerodynamics, Engine, DriveTrain, CarState, CarController,
          CarDamage, BodyDamage, the collision bodies and witnesses, OBB,
          Collision and VCWitness.
          **Done in Session 121:** all of them from retail, and
          TrackPathCoordinate's with them. Car's is the new `carsnap.c`.
          OBB's has no caller in retail and is not ported.
          `carsnap_check` runs retail's beside the port's: 22867 lines,
          0 differ; 100 of 100 mutations caught. The 57 checkers that
          link the changed files pass again.
        - [x] 72c. The drivers and the AI: CarDriver, RealDriver,
          AIDriver, PsychoDriver, TrafficDriver, CopDriver,
          AICarController, the AI plan and its actions, Average and
          PidError, NearbyCarList, DrivingInformation, DrivingLocation,
          DrivingChoice, NearestRoutePointInfo, the route pointers,
          TrackPathCoordinate, Spline, QuickSpline, RealController,
          TrackedController, DriveTarget and the movers.
          **Done in Session 122:** all of them from retail, beside
          each class, in the tables where retail has them; World's and
          tCopManager's pointer moves too. TrackPathCoordinate was
          72b's. DeliveryMover is not ported, so its snapshot is not
          either, and Spline's has no caller in retail.
          `aisnap_check` runs retail's beside the port's: 29602 lines,
          0 differ; 140 of 140 mutations caught. It found RealDriver's
          Port restored signed where retail's is unsigned. The 49
          checkers that link the changed files pass again.
        - [x] 72d. The world and the race, in two:
          - [x] 72d-1. What World and RaceCoordinator call: Race,
            RacingCar, Player, RaceParameters, cPlayerSettings, RideInfo,
            DriverInfo, WorldTime, the joystick, the camera shakers,
            NisManager, TrafficCar, TrafficTeleporter and tTrackGraph.
            **Done in Session 123:** all of them from retail, beside each
            class; Player's is the new `playersnap.c`. AnimatedDriver is
            not ported, so its snapshot is not either. The NIS player's
            seams are not set, so a restored NIS does not load or start.
            `racesnap_check` runs retail's beside the port's: 21743
            lines, 0 differ; 87 of 87 mutations caught. The 23 checkers
            that link the changed files pass again.
            docs/formats/replay.md lists every move.
          - [x] 72d-2. `World::DoSnapshot` (0x0014d148) and
            `RaceCoordinator::DoSnapshot` (0x001498f0). Between them
            they call the above, the cars', Smokeable's and
            VirginSmokeable's. A restore resets the camera shakers. The
            cops' and the chopper's are 72e's.
            **Done in Session 123:** both from retail in `worldsnap.c`,
            with SnapshotCops; SnapshotAllSmokeables and Smokeable's and
            VirginSmokeable's DoSnapshots in `smokesnap.c`; the three
            SnapshotEverythings (the track polygons' bodies, every body,
            the witnesses) in `bodysnap.c`. The cops', the chopper's,
            the clans' and the fern shakers' are seams until 72e or
            their classes. Munition, DroppedBomb and SmokeBomb have
            Smokeable's in slot 16. `worldsnap_check` runs retail's
            beside the port's: 5631 lines, 0 differ; 88 of 88 mutations
            caught. The 121 checkers that link the changed files pass
            again.
        - [x] 72e. The cops: tCopManager, tPursuit, the roadblock's state
          machine, tPlayerCop, tAICop, the spike strips, DroppedSpikes,
          Rocket and Chopper. In three:
          - [x] 72e-1. DroppedSpikes' (0x001bef90) and Rocket's
            (0x001bf910) DoSnapshots, slot 16 of their tables;
            tSpikeStrip's (0x00241898); the Chopper's (0x001e7d08),
            bound to World's `gChopperDoSnapshotFn`.
            **Done in Session 123:** all four from retail in the new
            `copsnap.c`. `copsnap_check` runs retail's beside the
            port's: 4839 lines, 0 differ; 76 of 76 mutations caught.
            The 21 other checkers that link the changed files pass
            again.
          - [x] 72e-2. tPursuit (0x0022a548) with the roadblock's state
            machine (0x0022ce60), and the cops: tCop (0x0022d440),
            tPlayerCop (0x0022d7e8) and tAICop (0x0022dd20).
            **Done in Session 123:** these with the cop manager's
            pursuit, cop and radar trap pointers, the pursuit's history
            and its barrels', all from retail in `copsnap.c`; the cops'
            are slot 32 of their tables. `copsnap_check` runs them
            beside retail's: 10696 lines, 0 differ; 183 of 183 mutations
            caught. The 52 other checkers that link the changed files
            pass again.
          - [x] 72e-3. tCopManager (0x00223b70): the pursuits, the
            strips and the cops, bound to World's
            `gCopManagerDoSnapshotFn`.
            **Done in Session 123:** from retail in the new
            `copmgrsnap.c`, with tSpikeStrip's default constructor
            (0x00241308) in `spikestrip.c`. A restore deletes and makes
            the pursuits and the strips again. `copmgrsnap_check` runs
            it beside retail's: 62527 lines, 0 differ; 89 of 90
            mutations caught, one equivalent. `spikestrip_check` checks
            the constructor. The 21 other checkers that link the changed
            files pass again.
        - [x] 72f. `ReplayManager` in full, in MainLoop in place of
          main.c's stand-in. Checked in Azahar with retail's checksum
          snapshots: a race replayed to where it paused, with every
          checksum agreeing.
          - [x] 72f-1. The class from retail's Replay.obj
            (`0x0013d448`..`0x0013ec98`) in a new `replaymgr.c`: the
            constructor and destructor, the beginning and end of time,
            BeginFrame and EndFrame with every snapshot they take, the
            highlights, the special events' table, Find, Take, Restore
            and Delete, HandleSnapshot and the manager's own snapshot,
            GetData and AddData. A checker runs it beside retail's.
            **Done in Session 123, continued:** all of it from retail
            in `replaymgr.c`, with the joylog's debugging and the
            snapshot times retail added; `replay.h` has the class's
            retail layout, 20664 bytes. `replaymgr_check` runs it
            beside retail's: 17370 lines, 0 differ; 280 mutations, 273
            caught, 7 equivalent. The 189 other checkers that link the
            changed files pass again. main.c still runs its stand-in.
          - [x] 72f-2. In the race: InitForRace's constructor, MainLoop's
            BeginFrame, EndFrame and DoFancyJoylogDebugging, the TICK's
            beginning of time and TheRaceHasFinished's end, in place of
            main.c's stand-in. Then the Azahar run with the checksum
            snapshots.
            **Done in Session 124:** main.c binds the real manager, and
            every race captures. "ReplayCheck 1" (the port's own,
            configitems.h) replays two parts of a race as it goes. On
            Azahar, 502 and 201 frames were replayed, 4 checksum
            snapshots verified in each part, 0 frames off and 0
            sections failed. A career race ran to its end and back to
            the tree. The 190 checkers that link the changed files pass
            again.
        - [x] 72g. The replay states (`RCSTATE_INSTANT_REPLAY`,
          `RCSTATE_AUTO_REPLAY`) and `ReplayScreen` (its timeline, camera
          modes and buttons). This brings the pause menu's View Replay
          and the post-race's highlights.
          - [x] 72g-1. The post-race's highlights: the four seams
            RCSTATE_POSTRACE already calls (BeginRaceHighlights
            `0x0013e308`, BeginNextRaceHighlight `0x0013e318`, and the
            two words retail reads inline) bound to 72f-1's manager.
            The world behind the end screens then replays the race's
            highlights on the demo camera. Checked on Azahar with a
            career race to its end.
            Done in Session 124, continued (`docs/formats/replay.md`,
            72g-1). On Azahar, event 32's end screens replayed loops
            1744 to about 2890 again and again, matching the race on
            every logged loop. The run passed: the autosave, the unload
            and the event tree. The 16 checkers that compile main.c or
            run the replay pass again.
          - [x] 72g-2. `ReplayScreen` from retail (`0x001ebda8` ..
            `0x001ed4e0`): the constructor and destructor, Tick and
            Update, the joystick handlers, the camera movers, the NIS
            watch, the timeline and its flailer bitmap. A checker runs
            it beside retail's.
            Done in Session 124, continued (`docs/formats/replay.md`,
            72g-2). `replayscreen.c` is the class; `replayscreen_check`
            runs it beside retail's (3309 script lines, 29580 output
            lines, 0 differ; 228 mutations, 225 caught, 3 equivalent).
            main.c binds its sound and help seams, and MainLoop updates
            the race coordinator's screen. Nothing makes one until
            72g-3. The 13 checkers that compile the changed files pass
            again.
          - [x] 72g-3. RCStateInstantReplayCallback (`0x0014b568`) with
            the screen, and the pause menu's and End Game Menu's View
            Replay (`gReplayNumInstantReplaySnapshotsFn`, the End Game
            Menu's test). Checked on Azahar: View Replay from the pause
            menu and from the End Game Menu.
            Done in Session 124, continued (`docs/formats/replay.md`,
            72g-3). `rcreplay.c` is the state's handler; `rcreplay_check`
            runs it beside retail's (5649 script lines, 10839 output
            lines, 0 differ; 65 of 65 mutations caught). The pause
            menu's item is enabled once an instant replay is held, and
            the End Game Menu's follows retail's test alone. On Azahar,
            both replayed and START went back to their menu; the career
            run passed. The replay's keys were mapped already (START,
            A, Left/Right, B, X, L, Y, SELECT). The 32 checkers that
            link the changed files pass again.
          - [x] 72g-4. RCStateAutoReplayCallback (`0x0014b848`) and the
            auto replay's four helpers (`0x0014c0f8` .. `0x0014c2d8`),
            for completeness: nothing in retail posts
            RC_REQUEST_AUTO_REPLAY (7), so the state is never entered.
            A checker runs it beside retail's.
            Done in Session 125 (`docs/formats/replay.md`, 72g-4).
            `rcauto.c` is the state's handler and its helpers, in
            `rcstates.c`'s table; main.c binds CleanUpAutoReplay to the
            destructor's seam. `rcauto_check` runs all five beside
            retail's (9513 script lines, 38513 output lines, 0 differ;
            156 of 156 mutations caught). The 41 checkers that link the
            changed files pass again. On Azahar the career run passed,
            the destructor's cleanup included.
          - [x] 72g-5. The replay bar's button icons are the PS2's
            shapes. Show the 3DS keys the replay uses instead (START
            skip, A pause, Left/Right markers, B speed, X camera, L
            target, Y help, SELECT timeline), as `uirender.c` does for
            the help line's icons.
            Done in Session 125, continued (`docs/formats/replay.md`,
            72g-5). `replaybar.c` retouches REPLAYBOTTOM_NEW as it loads
            (`texpack_upload_retouched`): L1, Square, Cross, Triangle and
            Circle become L, B, A, X and Y. The D-pad's two, SELECT and
            START stay retail's. The help's Triangle and Square were the
            menus' B and X; HELPGLYPH_LAYOUT_SCANNERS draws them as X and
            B while a replay is up. `replaybar_check` (18 cases, 0
            differ; 49 of 50 mutations caught, 1 equivalent) and the
            checkers that link the changed files pass. On Azahar the bar
            and the help showed the 3DS keys; the career run passed.
        - [x] 72h. The pause pages' special events (`AddSpecialEvent`),
          and `DemoModeReplay` with the disc's replays for attract mode.
          - [x] 72h-1. The pause pages' special events.
            Done in Session 125, continued (`docs/formats/replay.md`,
            72h-1). `pausereplay.c` is retail's
            HandlePauseMenuReplaySpecialEvents (`0x001703e0`), events 0
            to 6, bound to the manager's HandleSpecialEvent. The Options
            page gives each change to `replaymgr_add_special_event`, as
            retail's setters do, so a replay makes it again on its loop.
            `pausereplay_check` (1848 ops, 0 differ; 44 of 44 mutations
            caught) passes, and so do the six checkers that read the
            changed headers. On Azahar, Damage turned on in the pause
            menu at loop 191 and View Replay made it again at loop 191.
          - [x] 72h-2. `DemoModeReplay` with the disc's replays for
            attract mode. The PS2's float rounding is not the 3DS's, so
            these may drift. Measure it then.
            - [x] 72h-2a. TheDemoModeReplay.
              Done in Session 125, continued (`docs/formats/replay.md`,
              72h-2a). `dmreplay.c` is retail's DemoModeReplay
              (`0x0013ee08` to `0x0013f6c0`): the five files' chunks
              through slot 29, the file's load, ConsiderLaunching,
              Launch, the race's parameters from the replay, the demo's
              snapshots one after another, and the replay screen's
              editing. main.c binds it to the seams that were waiting.
              `dmreplay_check` (4154 ops, 0 differ; 106 of 106 mutations
              caught) passes, and so do loadertable, rcreplay and
              replayscreen. Nothing sets ActiveFlag yet; a SkipFE race on
              Azahar ran as before.
            - [x] 72h-2b. Attract mode from the title.
              Done in Session 126 (`docs/formats/replay.md`, 72h-2b).
              `demomode.c` is StartDemoMode (`0x0016ecd8`),
              BuildDemoTrackList (`0x0016ec10`) and
              FrontendDatabase::StartDemoMode (`0x00184d48`). `rcdemo.c`
              is RCStateAIDemoModeCallback (`0x0014a8c0`) and
              RCStateReplayDemoModeCallback (`0x0014aa38`). The flow's
              three hooks and its loading flags are bound, and the main
              menu considers a demo too. The disc's replays restore once
              each car's AnimatedDriver section is moved
              (`gCarSnapshotRetailDrivers`), but they drift from their
              first frame on the 3DS: every loop's checksum missed, under
              round-to-nearest and round-toward-zero alike. So
              "DemoReplays" (0 by default) keeps them off, and attract
              mode is the AI's race. demomode_check (6648 ops, 0 differ;
              101 of 101 mutations caught), bootflow, rcstates and
              carsnap (106 of 106) pass. On Azahar
              (`run_azahar_attract.ps1`), both PASS. With -Skip, the AI
              demo played on track 11 at 30 FPS under the overlay, timed
              out after two minutes, and the boot stages led back to the
              title. A skipped the next to the main menu, where a third
              started. With -Replays, file 2 restored, reached RACING and
              went to the main menu at its first checksum miss.
            - [x] 72h-2c. The PS2-to-3DS drift: each demo snapshot's
              end against the next start, or checksums. 72h-2b found
              every loop missing from the first, so this waits for TASKS
              73's car physics; then "DemoReplays 1" and
              `tools/run_azahar_attract.ps1 -Replays` measure it again.
              Closed in Session 147 (`docs/formats/replay.md`, "The disc's
              replays on the 3DS"), as far as the 3DS can go. The first
              frame's miss was the checksum: retail's (`0x0014e240`)
              adds the helicopter's x after the cars, and retail's verify
              (`0x0014e300`) sets the manager's +12, now OutOfStepFlag.
              Both are in `worldstep.c`, and `world_check` runs them as
              hooks on the demo image (0 differ; the new mutations
              caught). The restored frame now matches the PS2's byte.
              The step after it misses on every build: "DemoReplayDrift"
              (the port's own, off) plays on and counts, and on file 5
              2838 of 2850 frames missed at round to nearest and 2842 at
              the EE's round toward zero with no denormals, the car off
              the road within 15 s both ways. Matching it would mean the
              EE's adder (one guard bit) and multiplier (sometimes an ulp
              under IEEE's) in software for every float operation of the
              world's step, and PCSX2 does not model the multiplier
              fully either. So "DemoReplays" stays 0, and attract mode is
              the AI race.

73. [x] **The car's retail pass: where 72b found retail and the port
        apart.** The port's car physics is the demo's code. Porting
        retail's DoSnapshots (72b) showed where retail changed the objects
        they move. `carsnap_check` sets each such field the same on both
        sides, so these are not checked yet:
        - [x] PhysicsCar's BottomOut: retail's starts the new FlippedTimer
          when the body is upside down and asks the Car to reset a second
          later (PleaseResetMeLater). The port's is the demo's, which
          never touches it.
          Done in Session 133: BottomOut (`0x00137938`) and
          CheckDampingSuitability (`0x001377d8`) are retail's. A car
          stopped on its roof or side (up axis' z under 0.1) is put back
          after a second; a car moving over 0.8 clears the timer. The
          damping skips a blinking car and one in the air, counts the
          throttle only with a wheel down, sets the collision body's
          ActiveCollisionDetection, and the debug bounce comes after it.
          `physicscar_check` runs both as Python from retail's listings
          in the demo image, 28 BottomOut and 7 x 882 damping cases, 0
          differ; 36 mutations, 35 caught, 1 dead in retail too.
        - [x] CarState::CalculateWheelMatrices: retail reads the y offset
          from WheelInfo's word at 24 and lifts the brake matrix. Done by
          TASKS 74 (`OffsetY`).
        - [x] DriveTrain's gMaxDownShiftOver is 1.2 in retail's data;
          `drivetrain.c` has the demo's 1.1. Found by TASKS 74.
          Done in Session 133, with the rest of retail's SetDesiredGear
          (`0x0018bce0`): in sport shift, with the asked-for gear in, an
          engine sagging under idle + 100 in second or above drops a gear
          and hands back the automatic. And a port bug, the demo's too:
          the crawl arm is first gear's alone (`slti 3`), where the port
          (and drivetrain_check's hand model) had first and second, so
          an automatic in second with the throttle open never dropped to
          first. Both images run in mipsemu agree. drivetrain_check 0
          differ, its 10 new mutations caught.
        - [x] Car::FinishMovement: retail's (`0x00131da8`, 2168 bytes) is
          the demo's (`0x00130480`) with four things added. Done in
          Session 133. **Bug fixed:** DistanceMoved was never added to,
          so the race results' average speed was always 0. Retail adds
          how far the car moved since BeginMovement's vOldPos and saves
          the new one. The replay's interest gets three more events
          for a player's car, every eighth step: GoingSlow (-10, under
          5 while still racing), CloseCops (0.05 for each cop within
          40, above 40) and Speed (the speed / 150). And a smokeable
          collision is worth 2.5, not 5. `carmode_check` runs the
          demo's image with the four hooked in at retail's places: 24
          new cases, 0 differ; FinishMovement's 112 mutations, 106
          caught, 6 equivalent (one new: a NaN speed's Speed event
          hides GoingSlow's -10).
        - [x] Car::TriggerEvents: retail's (`0x001335c0`) reaches the
          event manager, the fern shakers, eModel's rigid animation
          timing and Player::TriggerVisibleDrivingLine, none of them
          ported before. Done in Session 134, all four from retail
          (`docs/formats/event-manager.md`):
          - LoaderTable slot 7 links each track's triggers;
          - the event queue runs at the end of each step;
          - a car driving into a bush hides it, draws it as a world
            object, and fires its leaves (BUSHSHAKE_A, BUSHSHAKE_B);
          - a player's car over 30 in one tells the replay.
          The training line needs TrainingLinesEnabled, which retail
          never sets, so its class stays a NULL seam. Retail reads
          VelocityMagnitude at CarState+900 (the port's 896, the
          layout item below; read by name, so nothing is off).
          `eventmgr_check` runs retail's functions against the port's:
          4 scenarios, 1090 ops, 11687 lines, 0 differ; 134
          mutations, 132 caught, 2 equivalent. The bush stands still
          while its leaves fly: nothing in the port draws a rigid
          animation (TASKS 76).
        - [x] Car::CalcForceParameters (`0x001346f8`): nothing to port.
          It is the PS2 force-feedback wheel's: its calls are
          PortSetForceConditionData, PortSetForcePeriodicData,
          PortPlayShake and PortSetOverallForceGain, and the 3DS has
          no such motors. Its one write to the Car is ForceBuzzTime
          (retail Car+2188), which no code in retail reads (the
          image's other `2188(` loads are a camera table's).
          Checked in Session 134.
        - [x] PhysicsCar::Move: retail's (`0x00137d90`) against the
          demo's (`0x00135c78`). Done in Session 134. Four changes:
          - the launch: a rear wheel with the throttle over 0.8, the
            brake over 0.5 and under 10 mph brakes by mph * 0.05, not
            by the pedal;
          - NFS mode's handbrake extra is 0.5 (the demo's 0.7);
          - a blown tyre is its own wheel's Damage (1 by its bit, else
            0), and Wheel::GetDerivative (`0x001a46b0`) takes
            spin * Damage * 0.1 off the spin's torque. The demo cut all
            four tractions to 0.4 for any blown tyre, and applied
            fTractionBoostOverride otherwise; retail reads that nowhere;
          - the brake-stand's lurch is (bRandomF(0.15) + 0.4) * 4000
            + 0.5 ticks for both lurches, and the start stamp rounds too.
          `physicscar_check` hooks the four into the demo image at
          retail's places: 121 scenarios, 128464 lines, 0 differ; 306
          mutations, 299 caught, 7 equivalent. `wheel_check` models the
          drag: 19 scenarios, 10779 lines, 0 differ; 166 mutations, 156
          caught, 10 equivalent. Twenty other checkers 0 differ (carmode,
          mellowmover, carsnap, car, realdriver, playercop, ...). Left
          for InitSkids: retail's MaybeMakeSkids takes the Car (a1).
        - [x] World::GetTimestep: retail's (`0x0014d718`) is the demo's
          (`0x0014aee8`) with one test more. Done in Session 134. A
          replay in slow motion (SlowMotionFlag, +20) or paused
          (PausedFlag, +16) takes its step without the wait for the
          recorded time, and keeps PreviousTimeToWaste. The port spun up
          to 0.3 s a frame there. `world_check` stubs retail's test into
          the demo image: 32 scenarios, 15164 lines, 0 differ;
          336 mutations, 336 caught (6 new).
        - [x] Wheel::GuessGroundForce: retail's (`0x001a4930`) takes
          the car's collision count. Done in Session 135. IterateForces
          (`0x00138f38`) reads the collision body's NumCollisions once and
          passes it to the four wheels. A wheel dragged backwards under a
          negative torque with no handbrake has its torque cut to 0.15
          only when the car is in no collision. FinalizeGroundForce
          (`0x001a4ee0`) differs only in layout: nothing to port.
          `wheel_check` runs 4 counts through the cut's grid: 0 differ,
          169 mutations, 159 caught, 10 equivalent. `physicscar_check`
          stubs retail's test into the demo image under four braking
          Move scenarios: 125 scenarios, 0 differ; its 4 new mutations
          caught.
        - [x] CarCollisionBody::AddDamage: retail's (`0x001d83d0`)
          scales a hit by 0.013 for CarDamage, where the demo's (and the
          port's) had 0.03. Done in Session 135. Its other change, the
          cop manager's test and two-car argument, was already in the
          seam (copmgr_car_impact, TASKS 51). `collisionbody_check` stubs
          retail's word into the demo image: 81 scenarios, 0 differ; 3
          damage-scale mutations caught.
        - [x] FindWaferNormal: retail's code is the demo's, but its
          WaferBias (gp-17844) is 0, where the demo's is 0.5. Done in
          Session 135: `contact.c`'s WaferBias is 0, so a body on or
          below a wafer's plane gets the normal turned round.
          `collisionbody_check` puts retail's 0 into the demo image and
          probes it before any bias change: 82 scenarios, 0 differ; 7
          wafer mutations caught.
        - [x] The RectPolyhedron constructor: the same code in both, but
          for relocated table addresses. Nothing to port (Session 135).
        - [x] Retail's TerrainTypeInfoTable has another layout. The
          port's is retail's already: TerrainType's pass (Session 31)
          made `terraintype.h` retail's 144 bytes, with
          SkidWidthMultiplier at 20 and DynamicFrictionMultiplier at 36.
          Nothing to port (Session 135).
        - [x] VClip: retail's (`0x001d2390`) restarts a walk that comes
          back to a pair; the demo's (`0x001c8200`), the port's until
          now, does not. Done in Session 135. After each step the pair
          goes in a list, and a pair one of the ten steps before it held
          starts the walk again from a random vertex of each polyhedron
          (World::Random on pCurrentWorld), at most three times, with 80
          steps from each start. That test comes before the status's, so
          a walk of two steps or more mostly ends on a repeat: the
          answer stands, but the witness keeps two random vertices and
          the world's seed moves by two draws, both of which the replays
          snapshot. `vclip_check` puts retail's restart into the demo
          image: 53 scenarios, 0 differ; 301 mutations, 300 caught, 1
          equivalent (20 new). polyhedra and collisionbody (whose models
          take the restart too), carmode, carsnap and loadertable: 0
          differ.
        - [x] Other demo-derived functions retail changed (TASKS 74's
          list): InitSkids. The port has no skid marks: MaybeMakeSkids,
          the SkidSets and the clans that hold them were never ported, so
          there is no demo copy to set retail's beside (Session 135).
          They are TASKS 78, from retail's code.
        - [x] RealDriver's changed functions and the player's input.
          Done in Session 133. Retail's tunables and its steering and
          throttle handlers are the demo's; what changed:
          - The sport shift's first press starts from the car's gear:
            up stops past the top gear, down keeps first. Later
            presses only count.
          - An automatic box's shift buttons go to the player again
            (Player::RerouteJoyEvent, `0x001788b8`): Be A Cop's
            roadblock and helicopter calls for a cop car, zone
            preview and freeze in a race. **Bug fixed:** the reset
            button did nothing. The Player calls (RerouteJoyEvent,
            IsAllowedToReset, SelectedReset) were NULL seams main.c
            never bound.
          - The horn: a racer's holds its headlights on. A cop car
            outside Be A Cop reads CopLights as a word and turns the
            lights on at 2. StartHonkHorn ends in Easter egg 5's
            chopper smoke bomb (`0x001ead40`).
          - NitroAvailable answers no while the car's player watches
            a NIS.
          `realdriver_check` runs the demo's image for the old seams
          and retail's image for the new ones (sport entry, horn,
          nitro, a 2000-step fuzz): 215871 ops, 0 differ; 165
          mutations, 161 caught, 4 equivalent. PlayerSelectedReset
          (`0x00182208`) is in `playernis_check` (a fake camera
          mover per player): 0 differ, 9 new mutations caught.
          Not checked by a tool: `player_reroute_joy_event` (read
          against retail by eye) and the chopper egg (6 lines, by eye).
          Still missing: the zone preview and freeze cameras the
          automatic's shift buttons now ask for (the events arrive,
          nothing handles them yet).
        - [x] Car::ResetToRoutePoint: retail's (`0x00132f20`, 336 bytes)
          takes one more argument than the demo's (`0x00131480`, 252
          bytes). Done in Session 133. Retail first puts the track path
          near the point, by its position and its distance around the
          track (ResetPositionNear, `0x00208848`), so a reset where the
          road crosses itself lands on the right road. The last bool
          sets JustResetFrames to 2, and only the reset button passes
          it. Car::Drive (`0x00131a80`) counts it down after the
          driver's Drive. tPursuit reads it: a blinking player's car
          that has just reset counts as stopped, so the reset button
          no longer shakes off a chase. The port never set it, so it
          did.
          `carmode_check` runs retail's listing as Python over the demo
          image, with a crossing (four path points moved beside the
          route point): 0 differ; 82 mutations, 79 caught, 3 equivalent as before, and Move's flag (mv-reset-just) caught. car_check's
          Drive (4 values of the count), pullover, traffictele and
          realdriver print the flag: 0 differ, their 6 new mutations
          caught. carmode_check had been failing since BottomOut
          (physicscar_check's PleaseResetMeLater stub hid the image's
          from its "later" case); fixed.
        - [x] CarState's layout: retail adds DistanceMoved after
          Odometer, and the fields from TractionUsage to BurnOutAllow move
          on by 4. The port keeps the demo's layout, with DistanceMoved in
          the padding. Nothing to port (Session 135): every reader goes
          by name, the replay's checksums go field by field, and the
          lock hash uses the port's own offsets.
        - [x] CollisionBodyWitness: retail's pCollision is at 108, the
          demo's at 104. Nothing to port (Session 135): none of
          retail's witness functions reads or writes 104, and the
          constructor, destructor, DoSnapshot, SnapshotEverything,
          GetCollision, BeginCollision, EndCollision, HasExpired and the
          Collision's constructor differ from the demo's only in that
          offset.
        - [x] CarCollisionBody's retail fields, with retail's
          TestForContact (`0x001d65f8`). Done in Session 135. Retail has a
          third stamp first, LastCollisionTime (our name) at 260, and
          LastPenetrationTime and LastYawControlCollisionTime at 264 and
          268 (the demo's 260 and 264); TestForContact, the accessors
          (`0x001d8e08` .. `0x001d8e48`), DoSnapshot and the two Car
          accessors agree. The port had the demo's order with the third
          at 268. TestForContact first asks both bodies
          AreCollisionsEnabled (slot 136) and stops if either says no,
          before VClip, and stamps LastCollisionTime on each car it hands
          on in a contact. **Bug fixed:** Player::ChooseToDisplayReset
          (`0x00181f68`) reads the new stamp, so a car spinning or
          slowing hard within 3 s of a crash is in trouble; the port read
          LastPenetrationTime, which only a blinking car's contact
          stamps, so a crash almost never counted. `collisionbody_check`
          stubs retail's test into the demo image and stamps at its
          contact: 83 scenarios, 0 differ; 16 new or rewritten mutations
          caught. car_check reads the offsets from SLES_507.31; car,
          carmode, physicscar, playernis and carsnap 0 differ, and their
          7 timer mutations (5 new or rewritten) are caught.
        It comes after TASKS 72, unless the replays need it sooner. The
        disc's demo replays need it (72h-2b): they miss the checksum from
        their first frame on the 3DS.
        Done in Session 135, in fourteen slices (the last a note).

74. [x] **The AI's retail pass.** Asked for on 2026-10-17, during 72h-2b:
        "I think the AI in general is somewhat stupid sometimes, would
        double-check that it matches the retail code as well". The AI
        was ported from the demo's image, like the car physics (TASKS
        73). `out/retail_syms.txt` marks each demo function retail
        changed, so the first step is that list for the AI's classes
        (the AI car controllers, the drivers, the routes and the
        actions), each changed function read beside the port's. It comes
        right after 72h-2b (done), before 72h-2c.
        Done in Session 127. Of the 327 changed functions in the AI's
        classes, the port already followed retail's in 275. The AI's
        decisions and their constants were retail's already. Of the
        rest:
        - MellowMover, the far cars' mover, is retail's now
          (`docs/formats/mellow-mover.md`). The force-feedback graph
          starts at 0.3. The constructor zeroes gUglyTimestepHack. Move
          brakes with half the e-brake too. UpdateCar draws a wheel no
          higher than its axle's MaxRenderingCompression.
        - CarState::CalculateWheelMatrices is retail's. The brake matrix
          lifts with the suspension, and WheelInfo's word 24 (`OffsetY`)
          pulls each wheel 1 to 7 cm in, on every mover.
        - tCopManager::GetResetDirection (`0x00228ae8`) was never bound,
          so a Be A Cop reset always faced along the route. It is ported
          (`copmgr.c`, `docs/formats/cop-manager.md`).
        - The others change only field offsets, or retail_match paired a
          tiny accessor with the wrong name. RealDriver's are the
          player's input (TASKS 73).
        - CopDriver::CollisionAvoidance, tCopManager's IsSpeedTrapNeeded
          and FindSuitableSpeedTrap, and tPursuit's
          ConsiderForcingAIPullover, AreCarsRacing and IsRacingWithMe are
          dead in retail: no jal or data word reaches them.
        mellowmover_check runs retail's image now (45 scenarios, 0
        differ; 352 mutations, 347 caught, 5 equivalent), and `--demo`
        with the four changes hooked in agrees with it. copmanager_check
        has GetResetDirection (34862 lines, 0 differ; 16 of 16
        mutations caught). carstate, physicscar, cartypeinfo, wheel,
        carmode and 29 more checkers pass with 0 differ.

75. [x] **The rest of the demo-cited functions retail changed.** TASKS
        74's citation check found, outside the AI, functions the port
        cites only by the demo's address whose retail bodies change a
        value, not just an offset:
        - eView's SetupWorldLightContext and CreateViewMatricies, and
          SetupSceneryCullInfo;
        - joyevent's GetJoyEventName,
          DetermineAvailableJoystickConfigurations, FindScannerConfig (two),
          GetJoystickButtonName and ChooseDeadZoneAndHysterysis;
        - cEditText::EnterEditTextMode, NisManager::EnableOverrideRendering,
          the DroppedSpikes constructor, tDisplayOptionsChangeManager::Start
          and bMatrixToQuaternion;
        - 37 changed functions the port cites by neither address, mostly
          the frontend, the debug menus and the editors.
        A paired literal can be an alignment artefact, so each needs
        reading beside the port's. It comes after TASKS 73.

        **Done, Sessions 149 to 151** (2026-10-20: the checklist's last
        retail item, one function at a time).
        - SetupWorldLightContext, done: retail's (`0x00107900`) puts the
          eye 10 back and 4 up, the demo's 9 and 7, and stores its
          look-at from SunPosition in LocalLightPositions, which no VU1
          program reads, where the demo's replaced EnvMapMatrix.
          `eview_check` runs retail's now. The port still does not call
          it: no scenery drawn in place on any track has a lit or
          environment-mapped strip (`docs/formats/eview.md`).
          eCreateLookAtMatrix is the same on both discs.
        - CreateViewMatricies, CalculateViewMatricies and
          SetupMatrixPacks, done: retail's Z table (`0x002c9e20`,
          `ZRanges`) gives each Z buffer mode three Z pairs, PSMZ24's
          half of the 24-bit buffer. The third pair makes a fifth matrix,
          d2, its VUClipScreen2 (a 576-byte frame block) and a third
          pack, and each pack holds WorldClip, a VUClipScreen and
          WorldView transposed. `eview_check` runs retail's three: 2,219
          ops, 17,931 lines, 0 differ; 168 mutations, 167 caught, 1
          equivalent. On the 3DS only the sun's depth read-back changes,
          player 1's quads taking PSMZ24's pair
          (`docs/formats/sun-draw.md`).
        - The fog chain, done in Session 150: retail's
          eAttachDepthIntoAlpha (`0x00118a60`) draws the PSMZ24 buffer's
          bits 8 to 15 into the alpha, 255 past 0xffff, where the demo's
          read a PSMZ16S buffer through two palettes; FogPower is 4.0,
          the demo's 4.6, and CreateFogPalette (`0x00119308`, fpow
          inlined) no longer copies entry 255 over 252 to 254. eAttachFog
          (`0x00119768`) builds its packet in the frame's memory now,
          and GetFogPalette moved; neither changes what the port's do.
          `efog.c` has
          retail's, and `trackview.c` takes the fog's Z from the view's
          target's range, PSMZ24's for player 1. `weather_check` runs
          retail's, with a model GS that draws the depth packet: 76
          scenarios, 4,180 lines, 0 differ; 88 mutations, 83 caught, 5
          equivalent. TRACKB12's fog now leaves 99.2% at 2,000 units
          (the demo's 97.7%) and 90.6% at 4,000 and in the sky
          (`docs/formats/weather-fog.md`). CreateFocusPalette and
          eAttachDepthOfField are the depth of field's, which the port
          does not draw.
        - joyevent, nothing to change: `scannertab.c` was read out of
          retail's disc (TASKS 49), so it has the four value changes:
          130 event names, 230 scanner rows (the demo's 231), and no
          fifth configuration for controller types 83, 115 and 121 (the
          demo's 24, 24 and 34). GetJoystickButtonName falls back to ""
          on both discs. `joystick_check` runs retail's image: 65,880
          ops, 79,028 lines, 0 differ.
        - The rest of the named list, nothing to change.
          SetupSceneryCullInfo and bMatrixToQuaternion are the same on
          both discs: the differences found were a moved global's
          address and two register loads read as literals.
          tDisplayOptionsChangeManager's Start and Different copy and
          compare what the port's do, at retail's Fred offsets.
          EnterEditTextMode, EnableOverrideRendering and the DroppedSpikes
          constructor were listed because an address the port cites for
          something else (`0x00168ea0`, `0x001a8000`, `0x001b5d70`) is the
          demo's for them. The port has no cEditText (TASKS 54's keyboard
          is the 3DS's) and no NIS player, and its Munition.obj is
          retail's. The citations name retail's addresses now.
        - tGlobalBackgroundAnimation, done in Session 151: the blueprint
          behind the menus' grid now drifts, fades and changes texture as
          retail's (`0x002495f0`). The port had drawn the two bitmaps
          where the bundle put them. Retail's start is 160..165 across
          and its drift 50 seconds, the demo's 180..200 and 20.
          `bganim.c`, called from ChangeToScreen and the frontend's tick.
          `bganim_check` runs retail's: 5,173 steps, 7,197 lines, 0
          differ, 15 facts; 46 mutations, 41 caught, 5 equivalent
          (`docs/formats/frontend-background.md`). Seen in Azahar on the
          main menu, setup and options screens.
        - The functions the port cites by neither address, nothing else
          to change. The recount has 33 rows, FrontendDatabase's
          destructor twice:
          - retail's already: the terrain table that CalcForceParameters,
            GetBoomDistToWall and DebugTopology::Render read
            (`terraintypetab.c`, read out of retail's disc), the help
            lines DifferentData's screen configs point at
            (`helpmenu.c`), TrackLockedDisplayer's 0.5, the engine
            ducker's 5, the collision volume's 0.65, and
            PauseDisplayOpts' leaderboard and menu;
          - an offset or a moved global, not a value: FrontendDatabase's
            offsets in its destructor, UserNameOptionsScreen and
            JoystickPreConfig, the vibration flags' address,
            EventTree::BuildTree's byte at 61 (the demo's 34), the
            camera loader the NIS coordinator reads (retail's layout in
            `cameracoord.h`), and RenderHud's 1 to 255;
          - code the port does not have or never runs:
            RainSplash::Respawn (dead on both discs), DemoPoly (a texture
            viewer whose RenderMe stays 0), the route editor's
            CreateNewRoute and RenderRoutes, the hidden Calibrate row's
            DisplayCalibrateOffsetCallback, AnimatedDriver's two (not
            ported, TASKS 26), JoystickPreConfig's re-read when a pad of
            another type is plugged in, bSnd_BankLoad's SPU memory, and
            the IOP and SDK's SOUND_PlayStream, sceDmaPutStallAddr,
            sceIoctl and InitTLBFunctions.
        - Not drawn, on either disc's terms: the depth of field
          (CreateFocusPalette, eAttachDepthOfField). The port never had
          it; it is a feature to add, not a value retail changed.

76. [x] **Rigid animations: the shaken bush, and the rest.** Found in
        TASKS 73's sixth slice. An eModel's rigid animation is its
        solid's keyframed transform, timed by RigidAnimationStartTime
        (`emodelanim.c` has retail's timing). Nothing in the port's
        renderer reads it, so no rigid animation plays:
        - a bush a car drives into is drawn as a world object
          (`fernshaker.c`) whose shake starts the animation, and it
          stands still while its leaves fly;
        - the car's wipers set a start time (`carrender.c`) that
          nothing plays.
        The first step is eModel::Render's (`0x0010c7c8`) animation
        setup, which `trackview.c`'s render_model skips (it draws each
        solid as georender baked it), then which models on the disc
        carry one. It comes after TASKS 73.

        **Done in Session 145** (the user, 2026-10-20: the checklist's
        three retail items before the launch, this one first).
        eModel::Render is `0x0010dc80`, not `0x0010c7c8`. Its setup is
        ported in `emodelanim.c`: SetupRigidAnimation (`0x0010dbd0`),
        GetMatrixAtTime (`0x001a7518`) and SetupVertexAnimation
        (`0x0010db70`), and render_model calls it where Render does, for
        every view. What plays: the wipers, the shaken bush (BUSHSHAKE_A
        and _B), the water wheels and belts on tracks 12/13/15/16, the
        XA_PROP models on 22/23/25/26, the windmills' fans on
        32/33/35/36, and the waving flag on 61..66 (15 vertex frames,
        which `trackview_prepare` now bakes with the track).
        `tools/emodelanim_check.py` runs retail's Render against it: 3113
        steps, 1087 lines, 0 differ; 18 mutations, 17 caught, 1
        equivalent. On Azahar, track 12's view drew up to 1 model a
        frame moved by an animation (frameprof's new "rigid" count),
        with 0 bakes failed and 30 FPS. The flags stand in zone 7 of
        tracks 61..66, which neither 40 s run reached, so they are not
        yet seen moving. Written up in `docs/formats/event-manager.md`.

77. [x] **View Replay says how to leave it.** Asked for on 2026-10-19:
        first B to leave the replay for the menu, then "keep it on START
        then, just make it clear on the replay screen". START is retail's
        SKIP (scannertab.c's 92), which goes back to the menu the replay
        came from, the End Game Menu or the pause menu; retail marks it
        on the bar with an eject symbol alone. Done in Session 135: while
        a ReplayScreen is up, the bottom screen is the panel with "Press
        START to leave the replay and go back to the menu." and the hint
        "START Back to menu, Y Help" (`main.c`'s kReplayNote and
        kReplayHint). The HUD is down in a replay, so the panel loses
        nothing. Not yet seen on a screen.

78. [x] **Skid marks.** Found in TASKS 73's last slice: the port draws
        none. On the PS2 a wheel sliding on the ground lays a trail
        textured by its terrain's SkidTextureName, darkening the road
        (the skid textures, in INGAMEB, are AlphaBits 0x44, plain alpha
        blending, not 0x42 as this entry first said). What retail has,
        all in its own code:
        - Wheel::MaybeMakeSkids (`0x001a5520`), which takes the Car too,
          called from PhysicsCar::Move, BeltMover::Move and
          MellowMover::UpdateCar; the port's wheel_maybe_make_skids is a
          seam no one fills;
        - SkidMaker's MakeSkid and MakeNoSkid, CreateNewSkidSet, the
          SkidSet (`0x001aa8f8` ..: 16-byte segments, eight to a set, in
          a slot pool of 128 kept in least-recently-drawn order) and its
          Render, an ePoly per segment through Render3D;
        - InitSkids, CloseSkids and DeleteThisSkid, and World's seams
          for them (gInitSkidsFn, gCloseSkidsFn);
        - the clans (`0x001ab510` .. `0x001ab9f0`): the cells a set is
          kept in by position, with InitClans, FlushClans (World's
          snapshot), CloseClans, GetClan and RenderClans, which
          eDisplayFrame calls after StuffSun (`0x001132c4`), and
          RenderSkids for each clan.
        The first step is the sets and the clans against retail in
        mipsemu, then MaybeMakeSkids, then the drawing on the 3DS. It
        comes right after TASKS 73.
        - [x] **78a, the sets and the clans** (`skids.{c,h}`):
              SkidSegment .. the clans, retail's 272-byte SkidSet
              with its car, both-views bit and centre, and the 4 m
              test; the World's six seams filled in `main.c`.
              Nothing lays a skid yet. `skids_check` runs retail's
              own code: 5839 ops, 0 differ, 118 of 122 mutations
              caught and 4 equivalent. Write-up:
              `docs/formats/skids.md`.
        - [x] **78b, MaybeMakeSkids** (`skids_maybe_make_skids` in
              `skids.c`, retail's `0x001a5520`): the three movers pass
              their car through `gWheelMaybeMakeSkidsFn`, which main.c
              fills, so sliding wheels lay skid sets in the race now.
              Nothing draws them until 78c. `skids_check` runs
              retail's MaybeMakeSkids too: 8654 ops, 0 differ, all 47
              new mutations caught (165 of 169 caught and 4 equivalent
              in all). Write-up: `docs/formats/skids.md`.
        - [x] **78c, the drawing** (`skids.c`): SkidSet::Render
              (`0x001aacc0`), RenderSkids (`0x001ab248`) and
              RenderClans (`0x001ab810`). trackview.c calls them after
              StuffSun in the player's view, and after the scenery in
              the mirror's. Each quad is an ePoly through Render3D, as
              on the PS2. trackview.c's strip_end joins a strip onto
              the one before it when the texture and matrix match, so
              each run of one texture's quads is one draw. The strip
              store and ring are doubled. `skids_check` runs retail's
              three: 9079 ops, 0 differ, all 39 new mutations caught
              (204 of 208 caught and 4 equivalent in all). Not yet seen
              on a 3DS. Write-up: `docs/formats/skids.md`.

79. [x] **The 2026-10-19 device race: the crash on saving, the wall, and
        the lag by the roadblock.** Asked for on 2026-10-19, ahead of
        78b: the user's Hot Pursuit race on their 3DS lagged hard near
        the end, the car went through a wall in the last lap, and
        saving afterwards crashed in an ARM11 exception (Luma dump).
        - [x] **79a, the crash and the wall.** The collision bodies'
              IDs went past retail's 206 (the munitions' pools are
              bigger than retail's, and smoke bombs were falling). The
              ID table and the pair bits are indexed with no test, so
              the heap was overwritten (the crash came when the track's
              collision tables were freed) and the pair bits aliased: a
              wall's witness was taken to exist and never made. The
              table holds 256 now, an ID past it aborts with the reason
              in `sdmc:/nfshp2_stderr.txt`, and every body maker tests
              `collisionbody_id_available()` first
              (`docs/formats/collision-body.md`). Needs a race on the
              3DS to confirm.
        - [x] **79b, the world's profile.** The log said the world took
              65 ms a frame (10 FPS) from about 250 m before the
              roadblock until the car got past it, and nothing more.
              With `DebugLog 1`, a `world:` line now follows each
              `frame:` line: the step by part, the three slowest cars,
              the witnesses, the contact rounds and VClip's walks
              (`docs/formats/world.md`).
        - [x] **79c, the roadblock's cost.** The user's second race
              (2026-10-19, build f1e1f9d: track 21, Hot Pursuit, 2 laps,
              smoke bombs, a roadblock at about (1622, -334)) "went
              great". The save went through ("Game settings saved
              successfully!") and nothing aborted, so 79a holds on the
              3DS. From about 300 m before the roadblock until it was
              passed, the world took 8 to 16 ms a step (worst 24), where
              the first race had 65. That is the contact rounds: 6 to 16
              a step (most 20), about 0.5 ms each, nearly all VClip's
              walks (up to 347 calls a step, 10 steps each, and a
              restart in nearly every call, as retail has it). They are
              the roadblock's own cars and barrels settling, then the
              player's car against them for 6 s, by retail's rules. The
              65 ms has not come back; 79a's aliased pair bits, which
              could make a pair's witness again and again, are the
              likely cause. With the draw's 22 to 28 ms the frames there
              run at 20 FPS, and the draw is TASKS 46's (this log's
              desert numbers are there).

80. [x] **The zone cameras: the freeze, the preview, the rest of
        zonecameras.cpp, and the radial blur.** Found while TASKS 64
        waited on the device. `playerzone.c` refused zones 1 and 2 as
        dead buttons because their movers were not ported, so the
        player's car hitting a roadblock's police car at over 40 mph
        (`pursuit.c`) never froze the world as retail does.
        - [x] **80a, the Zone Freeze camera** (`zonecam.c`): retail's
              constructor (`0x00160298`), destructor (`0x00161000`),
              `Duration` (3 s) and `Update` (`0x001610a8`), with
              `ConstrainToTopology` and `EnsureEyeAboveGround`, which
              the other zone cameras share. Also new: `Spline`'s
              allocating constructor, `AddControlPoint` and
              `GetDerivative` (`spline.c`), `tCubic3D`'s setters
              (`banim.c`), and `Player::UpdateZoneSound`, which sweeps
              the wind round the listener (`playerzone.c`). The
              constructor passes `CM_STILL`, as retail does.
              `zonecam_check`: 12 scenarios, 1850 ops, 45410 lines, 0
              differ; 99 mutations, 96 caught, 3 equivalent. Passed on
              the user's 3DS on 2026-10-19: "zone freeze works 100%!".
              Write-up: `docs/formats/camera.md`, "The Zone Freeze
              camera".
        - [x] **80b, the Zone Preview camera** (`zonepreview.c`, type
              14): retail's constructor (`0x00161f98`), destructor,
              `Duration`, `Update`, `Render`, `Enable`, `Disable`,
              `FindRoute`, `ViolatesTopology`, `EnsureTopology` and
              `Spline::LinearEstimateLength`, with the route's splines
              (`previewspline.c`), its stops (`previewstops.c`,
              `0x00165a70`) and the comet (`previewcomet.c`). main.c
              binds the four `gZonePreview*Fn`, so zone 2 is no longer
              refused, and `trackview.c` runs `RenderCameraMovers` for
              the main view and the mirror. In a race with the automatic
              gearbox, Shift Up (ZR by default) asks for it. The checks:
              `zonepreview_check` 13 scenarios, 2727 ops, 54646 lines, 0
              differ, 131 mutations, 130 caught, 1 equivalent;
              `previewspline_check` 52 scenarios, 3248 ops, 48851 lines,
              0 differ, 8 facts, 114 mutations, 113 caught, 1
              equivalent; `previewcomet_check` 534 steps, 12442 lines, 0
              differ, 14 facts, 97 mutations, 95 caught, 2 equivalent;
              `previewstops_check` 58 scenarios, 2051 ops, 7846 lines, 0
              differ, 136 mutations, 134 caught, 2 equivalent. The first
              3DS build failed the mover's layout check, which the
              64-bit host skips: the EE's 16-byte bVector3 leaves 4
              bytes at 1068, now named. Seen in Azahar (track 42): the
              camera runs down the road with the comet and the radial
              blur at 30 fps, then drops back behind the car. Not yet on
              the 3DS. Write-ups: `docs/formats/camera.md`, "The Zone
              Preview camera", and `preview-splines.md`,
              `preview-stops.md` and `preview-comet.md`.
        - [x] **80c, the Jumper and Cubic movers**, the rest of
              zonecameras.cpp. Nothing left to port. The zone jumpers
              (types 15 and 16) were already in, as
              `TrackCarCameraMover`s (`playercam.c`). `CubicCameraMover`
              (type 17) is never built in retail: ChangeCameraMover's
              other callers pass constants, and the debug camera's two
              cycles (`0x002b3c60`, `0x002b3c70`) hold types 0 to 4;
              its constructor has no other reference, and its destructor
              and Update only the vtable. `DumpCubic` and
              `ConstrainCubic` have no reference at all. So
              `gCubicCameraMoverFn` stays NULL. Written up in
              `docs/formats/camera.md`, "The player's cameras".
        - [x] **80d, the radial blur** (`radialblur.c`), which the
              nitro, the zones and the replays share: retail's
              `GetPlayerView`, the view's on and off, `RadialBlurOn`,
              `Off`, `Alpha` and the replay screen's on-off
              (`0x0010f0d0` to `0x0010f238`), and the ePolys of
              `DisplayRadialBlur` and `DisplayBlendPrevious`
              (`0x0010f280`, `0x0010f4f0`). `trackview.c` draws them
              after the cars and the alpha lists and before the mirror:
              four quads write a mask into the target's alpha
              (`GEO_BLEND_KEEP`), then the last frame blends in by it
              (`GEO_BLEND_DEST_ALPHA`). The last frame is a
              `GX_TextureCopy` of the top screen into a 256 by 512
              texture, after a send (`hangwatch_gpu_send_now`).
              `radialblur_check`: 323 steps, 4651 lines, 0 differ, 6
              image facts; 41 mutations, 41 caught. Seen in Azahar with
              a test build that forced it on in a SkipFE race (148 of
              150 frames blended, trails at the edges, the HUD and the
              mirror clean); not yet on the 3DS. The nitro is a cop's in
              Be A Cop alone, so in a race it comes with a zone (D-pad
              Down) and in the replays. Write-up:
              `docs/formats/radial-blur.md`.

81. [x] **Track 62: through the road at the chevron corner.** Reported
        on 2026-10-20, while the user drove during a track 62 Azahar run:
        "WELL I WENT THROUGH THE GROUND THAT WAS FUN". Done after TASKS
        76, before 72h-2c.
        - [x] **The trace.** "FallLog 1" (with "DebugLog 1"; off by
              default, `configitems.c`) has `worldstep.c` record each
              step of player 1's car: the step, the move, each contact
              it resolved (the other body's type, a track polygon's
              normal and side, the backup, the crowbar's z, z and vz
              before and after) and the rounds left over at
              `WORLD_MAX_CONTACT_ROUNDS`. `main.c` writes a "fall:" line
              a step. `tools/fall_trace.py BUNDLE LOG` adds the road's
              height under each position, from the bundle's 0x34132
              polygons, and shows the steps around the first one below
              it. `nfshp2_warp.txt` put the car before the corner.
        - [x] **The cause.** At the apex near (-1104, -328) the car hit
              the outer wall, flew up and came down on the chevron signs
              (smokeables). Three steps reached the twentieth round, and
              signs were left overlapping the car. Then Crowbar parted
              car and sign along the line of their centres. The sign's
              centre is above the car's, so the car went 0.43 down
              (frame 538, z 10.753 to 10.415), its centre 0.09 above the
              road's plane. Below the plane, FindWaferNormal with
              retail's `WaferBias` of 0 turns the road's normal down, and
              the road pushes the car on through. The port's step
              reaches the 0.05 s cap in heavy collisions, where the PS2
              runs at 1/30, so bodies end deeper in each other.
        - [x] **The fix** (`contact.c`, the port's own). With
              `CrowbarSparesCars` (1 in the game), Crowbar and Resolve
              leave a car where it is against a smokeable, and the sign
              takes the whole push. `collisionbody_test.c` and
              `carsnap_test.c` set it to 0, retail's Crowbar.
              `collisionbody_check`: 83 scenarios, 0 differ, with a new
              Crowbar against a smokeable either side; the five crowbar
              and resolve mutations caught, `ct_crowbar_spares_always`
              among them. `carsnap_check` and `world_check` 0 differ.
              The same warp in Azahar: the sign pushed 0.31 down, the car
              moved 0.001, and no step was below the road. Not yet on the
              3DS. Write-up: `docs/formats/collision-body.md`, "The
              port's departure (CrowbarSparesCars)".

82. [ ] **A stone wall's brief artifact on track 11.** Reported by the user
        on 2026-10-20, watching the 72h-2c runs on Azahar: "a minor
        graphical artifact on one of the stone walls it collided with
        briefly on the demo". File 5's replay (track 11) played on past
        its misses, and the Elise hit the low stone wall by the yellow
        chevrons some 30 s in, in both runs. The shots, every 15 s, did
        not catch it. What it looked like is still to ask.

        **Parked by the user on 2026-10-20, in Session 148**: "Okay still
        no bueno, so you're done trying to fix it. Move on to another
        task and document this for later." The code is as it was before;
        the work is `docs/parked/tasks82-retail-lod.patch`, made against
        b2c2307 (`git apply` it).
        - **What it is.** The user: "Pixelation much like the road issue
          from before", on "the one right before it entered the tunnel",
          and from their photos, "ITS LIKE FLICKERING". The wall's
          W_WALLSTONE texels draw as blocks a few pixels tall that
          flicker as the camera moves.
        - **Why.** The GS and the PICA pick a mip level differently.
          - Retail's TEX1 has LCM 0 (CreateTextureContext,
            `0x00108cc0`), so the GS's level is log2(1/Q) + K/16: from
            the depth alone, as for a strip facing the camera.
          - K is each strip's own: eSolid::CalcAutoK (`0x0010bfe8`)
            makes it from the strip's normal and MaterialDensity, and
            SetMipMapK (`0x0011c328`) writes its low byte, which VU1
            (entry 0x01e8) stores in TEX1 at 0x30a.
          - The PICA takes the larger screen axis's texel step, so a
            wall or road seen edge on comes out up to four levels
            coarser, and MMin 3 (every track and car texture) is
            NEAREST within a level.
          - solid-geometry.md and texture-pack.md have the formula, the
            storage and track 11's counts.
        - **Tried.**
          - MMag's filter (LINEAR) within a level for MMin 3, trilinear
            then: `nfshp2_wall82b`'s shots show the wall blurred into
            streaks.
          - With that kept, an LOD bias set at draw time to the GS's
            level less the PICA's:
            - geobake bakes a GeoLod per 32-triangle cluster: the ST
              gradients, the normal and log2(MaterialDensity / div);
            - georender sets the bias of each run of clusters within half
              a level of each other, after C3Di_UpdateContext, and
              `RetailLod 0` turns it off.
            Track 11 has 9,015 clusters. Seen face on, the bias is near 0
            (median 0.10 over 5,911 clusters, p5 -1.52, p95 1.02), so the
            units agree. Per cluster and not per batch, because only
            38.3% of a batch's area lies within 25 degrees of its plane.
          - The user watched that build's Azahar run (`nfshp2_wall82c`, 280
            shots) and judged it still bad. That build also biased the
            sky and far mountains, whose textures have no disc levels; the
            patch has the fix (GeoTexture.retailMips, from the disc's
            NumMipMapLevels), which was never run.
        - **If it is picked up.** The gated patch has not been seen. The
          track 21 road/wall static and the bridge artifact, both under
          TASKS 47, may be the same cause; neither is checked.

83. [x] **The drivers in the cars.** Asked for on 2026-10-20, after TASKS
        75 turned it up: "Port the cars' drivers and the depth of field
        before the launch, one at a time, drivers first." Retail draws an
        AnimatedDriver in every car but traffic, once the car is big
        enough on screen, with its animations: the steering, the gear
        change, looking back, driving backwards, the flinch in a crash,
        the pre-race close-up, and R/C Car's big head (`vBoneScale`). The
        port has the seams (`carrender.c`'s `render_driver`, `carmove.c`,
        `carcollisionbody.c`, `cameracoord.c`, `carsnap.c`,
        `trackflow.c`'s `gInitAnimatedDriverFn`) and nothing behind them.
        - [x] **83a, the animations' data.** eAnimation.obj (retail
              `0x001a67f8` .. `0x001a79f0`): LoaderAnimations for the
              0x80034008 chunks (INGAMEB's DRIVER_ANIM01 and
              DRIVER_SHIFT01, PRERACEANIM's two), eFindAnimationSolid,
              eAnimationSolid's keys (16-bit quaternions a node a frame,
              a translation a frame), Slerp, and eAnimation: the model,
              the two solids, PoseMatrixRecursive down the solid's
              0x34007 tree.
        - [x] **83b, AnimatedDriver.** AnimatedDriver.obj (retail
              `0x001a8f50` .. `0x001aa780`): AnimationInfo's table,
              AnimationPlayer, the queue, the steering frame, looking and
              driving backwards, BuildQuaternionTable, InitAnimatedDriver's
              fix-up, InitializeArtwork's three LODs with the character's
              skins, and Car::AssignAnimatedDriver.
        - [x] **83c, the skinned draw.** eAnimation::Render's bones, and
              RenderStrips' DoBlendingOnStrip (`0x0010d778`): each vertex
              between two bones by the weight in its low bytes. On the
              3DS the CPU blends the positions into georender's skin ring
              (16,384 vertices a frame), and georender draws the copy lit
              as a car's batch.
        - [x] **83d, in the race.** The seams set, seen in Azahar: the
              drivers in the grid's close-up and the chase camera, the
              looks back, and the big head. 30 FPS kept.
              **Done 2026-10-21.** `animdriver_check`: 13,662 steps,
              9,866 lines, 0 differ; 6 facts, 0 wrong; 132 mutations, 131
              caught, 1 equivalent. Azahar, track 42: every car but
              traffic has its driver; in the chase view 42 a second pass
              the size test, all at retail's far LOD (a plain model, LOD
              1 needs the car bigger than 999 from behind). The quick
              race's pre-race close-ups pose one. `EggCodes 8` (R/C Car):
              4 posed a frame with the 5.5 head, 0 dropped. 30 FPS after
              the start; the start's first 8 seconds at 20 are the same
              with the driver draw cut out (TASKS 46). The looks back are
              the checker's, not driven in Azahar.

84. [ ] **The depth of field.** The second half of the 2026-10-20 ask,
        after TASKS 83. CreateFocusPalette and eAttachDepthOfField: after
        the fog, retail blurs what is out of focus by each pixel's depth
        (the race camera's focus 15 ahead, depth 65). On the 3DS it is a
        pass over the whole screen, so it has to keep 30 FPS.

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
  - [x] The speech banks. `hookLoadSpeech` loads them
        (`sedwedge_load_localized_speech_files`), with step 14's sound.
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
  - [x] `ANY_BUTTON_PRESSED` (message 24) from `JoyHandler`. `main.c`'s
        `flowInput` sends it for every press or release no popup or
        HELP panel takes, before BACK and the menu (2026-10-20).
  - [ ] `OverwriteFred`'s six calls into the frontend. Nothing reads the
        loaded `Fred` yet.
  - [x] `MemcardSaver`, and the Options screen's manual load (Session
        86). Retail's `MemcardSaver`, `LoadSaveWrapper` ("Phils Load
        Save", the Options menu's Save/Load) and `Autosaver`
        ("Autosave") are in `memcard.c`. `bootflow_check` runs them on
        the retail image: 34 rows; 76 mutations, 75 caught, 1
        equivalent. See task 52.
  - [x] `DemoModeReplay`'s internals (TASKS 72h-2a, `dmreplay.c`).
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
  - [x] `StartDemoMode`'s track, from `BuildDemoTrackList` (TASKS
        72h-2b, `demomode.c`).
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
  - [x] `TheEasterEggs`' 78 codes (`0x0031d828`), and `OnTick`'s three
        seconds of "Unlocked" when one is entered (TASKS 50a).
  - [x] Attract mode from the main menu (`OnTick`'s
        `ConsiderStartDemoMode`), with message 24 resetting its timer.
        `tools/run_azahar_menuwait.ps1`: 50 s of presses on the main
        menu and no demo, then the demo 32 s after the last press
        (2026-10-20).
  - [x] `MakeChallengeCarsAvailable` and `RaceParameters::InitWithDefaults`
        in the constructor: its `challengeCars` and `raceDefaults` hooks.
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
  - [x] The Options' Jukebox screen (the playlist and its volumes),
        in TASKS 71b.
  - [x] Real hardware: the user's playthrough on a 3DS (2026-10-19)
        passed with it.
- [x] **You're The Cop.** Cops On's second item. Retail's
      `BeACopChallengeSetup` (`0x001b6c68`) is `bsetup.c`, with Players,
      Skill Level and Setup, the arrows class (`0x0024a690`) and
      `tfeSineWave`. `setup_check` runs retail's on the image: 359 ops,
      0 differ; 145 mutations, 142 caught, 3 equivalent. On Azahar the
      arrows pulse either side of the skill, the level wraps, and the
      lines are retail's (`docs/formats/frontend-setup.md`).
  - [x] `tHelpMenu` and `SetHelpOverride`: TASKS 48.
  - [ ] `mPolice` from Fred+32. The port reads `gf->copsOn`, as
        `bscreens.c` keeps it; the Mode Selects' state belongs in the Fred
        image.
  - [x] The three car calls in the constructor and SELECT
        (`MakeChallengeCarsAvailable`, `0x00183ec0`'s preload,
        `SetupRaceParametersAfterRaceSetup`), with car select. The last
        was ported in step 12m (`fredrace.c`, `race-start.md`).
- [x] **The Setup screen.** Catch-up, traffic and damage, with arrows on
      the current row and the movie behind. "Be The Cop Setup" is
      `BeTheCopSetup` (`0x001b9248`) on `RaceSetupBaseClass`
      (`0x001b8390`), screen `d1eadbca`, with `tScrollingMenuList`, all in
      `bsetup.c`. `racesetup_check` runs retail's on the image: 398 ops,
      0 differ; 86 mutations, 82 caught, 4 equivalent. On Azahar it
      matches the photo, and RIGHT on Traffic goes to Moderate
      (`docs/formats/frontend-setup.md`, "Be The Cop Setup").
  - [x] `SetClipToPoly`: `uirender.c` cuts each copy to its box
        (MaybeClipPoly, `0x00141808`).
  - [x] The other race setups (Single Race, Free Run, Lap KO, Track KO),
        on the same base with other rows (`bsetup.c`,
        `docs/formats/frontend-setup.md`).
- On 2026-09-29 the user moved the port back to cars and racing: the
  items below wait unless a race needs them.
- [x] **Car select** (`bcarsel.c`, `docs/formats/car-select.md`).
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
- [x] **Select Track** (`btracksel.c`, `docs/formats/track-select.md`).
  - [x] 12m-3c-1, retail's SelectTrackScreen as logic, 2D, the model and
        StartRace. `tracksel_check` runs retail's on the image: 3132
        ops, 0 differ; 171 mutations, 155 caught, 16 equivalent. On
        Azahar it follows car select.
  - [x] 12m-3c-2, the TSELECT.BIN slideshow (main.c's pack hooks and
        `trackSelSyncPictures`). On Azahar it cross-fades from `TRACK11`
        to a TSELECT.BIN picture after four seconds.
  - [x] Y (SQUARE) for the track's speech: the run script sent key 0;
        with Azahar's X (88) the log has "last SQUARE".
- [x] **The briefing.** "You're The Cop", with its button list over the
      track's picture. It is the Blurb over the cop race's fly-by
      (`docs/formats/start-race-screens.md`).
