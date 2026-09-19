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
6. [ ] Ghidra project import of `NFSHP2.ELF` (MIPS R3000/R5900); check
       whether a community PS2 EE processor extension is needed. Cross-check
       a few decompiled accessor functions against `docs/mdebug_structs.txt`
       offsets to validate the stab-scan output before relying on it heavily.
7. [x] `HANDOFF.md`, `TASKS.md`, `README.md` created

## Phase 1 -- Asset extraction pipeline

8. [ ] Reverse-engineer `ZDIR.BIN` directory format (index into `ZZDATA.BIN`)
       -- start from `bFile.obj`/`bFileE.obj`/`QueuedFile.obj` in `NFSHP2.MAP`
9. [ ] `tools/zdir_extract.py` -- extract all entries from `ZZDATA.BIN`
10. [ ] Identify per-asset formats (GS textures, VU1 geometry, bWare UI
        format if any, SPU ADPCM audio, VP6/SCHl boot movies); write findings
        to `docs/formats/*.md` as each is cracked
11. [ ] Confirm whether HP2 actually uses JDLZ compression (check `.symtab`/
        `.MAP` for `jdlz`/`JDLZ`/`bDecompress`-named symbols) before relying
        on the copied `source/jdlz.c`
12. [ ] Conversion tools: `tools/texture_convert.py`, `tools/geometry_convert.py`,
        `tools/audio_convert.py` (DSPADPCM via existing `tools/bin/dspenc.exe`),
        `tools/video_extract.py` (VP6/SCHl, reusing `source/vp6/ea_demux.c` logic)
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
