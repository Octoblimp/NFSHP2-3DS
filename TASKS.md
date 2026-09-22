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

25. [~] Car simulation (recovered car-state struct layout from `.mdebug`).
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
        scenarios, 177 lines, 0 differ; 41 mutations, 41 caught).
        **`CarDriver.obj` plus `DriveTarget`'s layout**
        (`docs/formats/car-driver.md`, `tools/cardriver_check.py`; 5
        scenarios, 118 lines, 0 differ; 48 mutations, 48 caught).
        **`Steering.obj` + `TwoWheelAckermanSteering.obj`**
        (`docs/formats/car-steering.md`, `tools/steering_check.py`; 5
        scenarios, 873 lines, 0 differ; 44 mutations, 43 caught, 1
        equivalent). **`RigidBody.obj`**
        (`docs/formats/rigid-body.md`, `tools/rigidbody_check.py`; 10
        scenarios, 935 lines, 0 differ; 77 mutations, 75 caught, 2
        equivalent). **`Suspension.obj` plus `Wheel`'s layout**
        (`docs/formats/car-suspension.md`, `tools/suspension_check.py`; 10
        scenarios, 1108 lines, 0 differ; 68 mutations, 66 caught, 2
        equivalent). **`Wheel.obj`** (`docs/formats/car-wheel.md`,
        `tools/wheel_check.py`; 19 scenarios, 10693 lines, 0 differ; 154
        mutations, 144 caught, 10 equivalent, 0 unexplained).
        **`DriveTrain`** (`docs/formats/car-drivetrain.md`,
        `tools/drivetrain_check.py`; 18 scenarios, 492 lines, 0 differ;
        176 mutations, 173 caught, 3 equivalent, 0 unexplained).

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
        | DriveTarget (methods) | 28 | 8636 |
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
        the CarState slice.
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
        ~~Wheel~~, ~~DriveTrain~~ (all done), then DriveTarget's
        methods, PhysicsCar, Car, with Mellovator and MellowMover last.

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

        **DriveTarget's 28 methods are next.** `DriveTarget.obj` is real
        -- `.text 0x002086f8`, `0x24d0` -- but it is not all DriveTarget:
        seven `OBB` methods and the free function `bDoublesBack`
        (`0x00208fa0`) are in it too, which is why the object is 9424
        bytes against a DriveTarget tally of 8636. The copy constructor
        is emitted elsewhere again, at `0x001da210` in
        `CarCollisionDetect.obj`. Twenty-six methods in the object plus
        that one is twenty-seven, not twenty-eight: **reconcile the
        count before planning the slice.** The 528-byte record is
        already in `3DS Files/source/drivetarget.h` and ARM-compiled, so
        the layout is done. Twelve methods take no `Car *` and depend
        only on ported code -- ctor, dtor, `operator=`, `GetAngle`,
        `ShiftLeft`, `ShiftRight`, both `SetPoint`s,
        `RecalculateLength`, `CalculateTime`, `GetFirstPoint(CarState
        *)` and `GetRouteAndRoutePoint` -- and are where to start, since
        `Car` itself is the last slice in the order.

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

        That leaves ~48.5 KB across ~168 functions still to go.
26. [ ] Race/event logic, cop AI, pursuit (roadblocks, spike strips) --
        `HotPursuitEvent` already seen in the `.mdebug` strings survey
27. [ ] Track rendering/streaming, collision. Carries a debt from task 24:
        `QuickSpline.obj` (`0x00227e98`) is what turns a world position
        into a distance around the track, and until it is ported
        `trackpath.c`'s `TrackPathCoordinate::UpdatePosition` is a stub
        and `gTrackPathDistanceFn` stays `NULL` on hardware. Three
        TrackRoute entry points need it: `SetFirstAndLastPoints`,
        `Signpost::SetDistances`, `TestSignpostConsistency`.
28. [ ] New3DS perf: core2 for background streaming/decode, gate higher
        fidelity behind the New3DS speedup flag

## Phase 5 -- Polish

29. [ ] Save data, options menus, final sound mix pass
30. [ ] Split-screen/multiplayer scope decision (HP2 supported split-screen;
        not committed to yet -- decide once single-player core is solid)
31. [ ] Final CIA packaging + Old3DS/New3DS compatibility pass

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
