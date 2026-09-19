# TASKS

Status flags: `[ ]` not started, `[~]` in progress, `[x]` done, `[!]` blocked.
Numbered IDs are stable -- don't renumber when inserting new tasks.

## Phase 0 -- Project scaffolding & tooling setup

1. [x] `git init` + `.gitignore` (exclude `PS2 Files/`, build artifacts)
2. [x] Copy/adapt NFSU2-3DS's reusable 3DS-side skeleton (Makefile, app.rsf,
       heapcfg.c/.h, source/vp6/, jdlz.c/.h, build_cia.ps1, makerom/
       bannertool/dspenc binaries)
3. [x] Placeholder `main.c` stub; verify full build (`.3dsx`/`.smdh`/`.cia`)
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
10. [~] Identify per-asset formats. Done so far: the `bChunk` container that
        every asset is built from, and the complete chunk-type -> `Loader*()`
        map pulled straight out of `LoaderTable`
        (`docs/formats/bchunk.md`, `tools/chunk_loader_table.py`,
        `tools/bchunk_dump.py`). Still open: the `0x00034005` VU1 geometry
        packets, the `0xb0300001` GS texture pack, the `.MSB`/`.MSH` sample
        bank record layout, and the `0x80010200` Flailer UI chunk.
        **Movies are not VP6**: `MOVIES\*.AVI` are RIFF/AVI with fourcc
        `MV30` (EA's MV3 codec, `MV3Codec`+`Huffman` in the ELF), 512x256.
        The `source/vp6/` decoder copied from NFSU2-3DS does not apply.
11. [x] JDLZ: **HP2 does not use it** -- no `jdlz`/`JDLZ` symbol in the ELF or
        `.MAP`. `.LZC` files are a `COMP`-magic LZSS container handled by
        `LZDecompress()` (`LZCompress.obj`, 0x001aa460). Reimplemented in
        `tools/lzdecompress.py` and validated byte-exact against every raw
        twin in the archive, up to the 15 MB `FRONTEND\FRONTB.BUN`.
        `3DS Files/source/jdlz.c` is therefore dead weight -- replace it with
        a C port of `lzdecompress.py` during Phase 1 task 12.
12. [ ] Conversion tools: `tools/texture_convert.py`, `tools/geometry_convert.py`,
        `tools/audio_convert.py` (DSPADPCM via existing `tools/bin/dspenc.exe`),
        `tools/video_extract.py` -- note this is **MV3-in-AVI**, not VP6/SCHl,
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
16. [ ] Reimplement bWare's menu/UI system once its format is understood
        (working name: `source/bui.c`); `DataEventSelectScreen` (seen in the
        `.mdebug` strings survey) is a concrete first screen-data class
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
