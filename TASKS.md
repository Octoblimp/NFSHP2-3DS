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
12. [~] Conversion tools. Done: `tools/texture_convert.py` -- walks any file
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
        Still to write: `tools/video_extract.py` -- note this is **MV3-in-AVI**, not VP6/SCHl,
        so it needs a port of `MV3Codec::DecompressFrameShared()` +
        `Huffman::Decompress()` rather than `source/vp6/ea_demux.c`.
        Also port `tools/lzdecompress.py` to C for the runtime.
13. [ ] Confirm asset delivery: external SD-card game directory (matching
        NFSU2-3DS), not ROMFS, given 273MB source archive size

## Phase 2 -- Boot flow & frontend menus (first milestone)

14. [ ] Decompile boot/logo sequence driver; look for a `BootFlowManager`-
        equivalent class in the recovered `.mdebug` type info
15. [ ] Reimplement as `kVideoStages[]`-style table in `main.c` (pattern
        already proven in NFSU2-3DS)
16. [~] Reimplement bWare's menu/UI system (working name: `source/bui.c`).
        **The format is no longer the blocker** -- `0x80010200` is fully
        decoded (`docs/formats/flailer-ui.md`): 76 screens across the three
        bundles, each a list of `FlailerBitmapChunk`/`FlailerTextChunk`
        objects carrying position, scale, per-corner RGBA, UVs, a font hash
        and a render layer, plus the `FE_*.BIN` string table their text
        really comes from (`docs/formats/language-table.md`). What is left is
        the C side: load the chunk, resolve texture/font hashes, draw layers
        0..28 through citro2d. Note `FlailerMenu`/`FlailerMenuItem` never
        appear on disc -- navigation and highlight behaviour live in the
        frontend C++ and still have to be decompiled.
        `DataEventSelectScreen` (seen in the `.mdebug` strings survey) is a
        concrete first screen-data class
17. [ ] Wire hid input -> menu navigation, citro2d text, citro3d backgrounds
18. [ ] Milestone acceptance: EA logo -> publisher logos -> legal/PSA
        screens -> main menu, real assets, navigable on 3DS controls

## Phase 3 -- Core engine systems

19. [ ] Math/vector/quaternion/matrix (`bMath`, `bVector`, `bQuaternion`, `bMatrix`)
20. [ ] Memory/slot-pool allocator (`bSlotPool`/`bNewSlotPool`) on top of `heapcfg.c`
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
