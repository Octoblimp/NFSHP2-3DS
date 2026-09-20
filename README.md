# NFSHP2-3DS

A homebrew port of **Need for Speed: Hot Pursuit 2** (PS2 version) to the Nintendo 3DS,
using devkitARM/libctru/citro2d/citro3d. Sibling project to
[NFSU2-3DS](../NFSU2-3DS) (NFS Underground 2 → 3DS); see `HANDOFF.md` for how
this project's engine (bWare, not NFSU2's engine) differs.

Goal: the real game, via decompiled PS2 code reimplemented in C and real
extracted assets -- not a reimagining.

## Layout

- `PS2 Files/` -- the original PS2 dump (`NFSHP2.ELF`, `NFSHP2.MAP`,
  `ZDIR.BIN`/`ZZDATA.BIN` asset archive, `IRX243/` IOP modules). Not
  distributed; gitignored. You must supply your own legally-obtained dump.
- `3DS Files/` -- the devkitARM project. Build with `tools/build_cia.ps1`
  (handles the space-in-path `subst` workaround) or `make`/`make cia` directly
  from a space-free path.
- `tools/` -- Python RE/asset-pipeline scripts, `stabs_dump.py`, vendored
  `makerom`/`bannertool`/`dspenc` build tools.
- `docs/formats/` -- reverse-engineered file format writeups, filled in as
  the asset pipeline (Phase 1) progresses.
- `HANDOFF.md` -- session-by-session engineering log. Read this first.
- `TASKS.md` -- numbered task list with status.

## Building

```powershell
powershell -ExecutionPolicy Bypass -File tools/build_cia.ps1
```

Requires `DEVKITPRO`/`DEVKITARM` set up (standard devkitPro 3DS install).
Produces `3DS Files/NFSHP2-3DS.3dsx` and `.cia`.

## Preparing the data

The `.cia`/`.3dsx` ships engine-only -- the extracted disc is 273 MB, so the
game reads it off the SD card. Extract the archive, then bake the intro movie:

```powershell
python tools/zdir_extract.py "PS2 Files/ZDIR.BIN" "PS2 Files/ZZDATA.BIN" extracted/ --decompress
python tools/video_extract.py extracted/MOVIES/INTRO/EALOGO_EN.AVI out/
python tools/movie_bake.py out/EALOGO_EN extracted/MOVIES/INTRO/EALOGO_EN.M3V
```

`video_extract.py` decodes MV3 by running the PS2's own decoder under an
emulator, which costs about five seconds a frame -- 90 frames, so give it
seven minutes. It only has to happen once.

Copy `extracted/` to the SD card as `sdmc:/3ds/NFSHP2-3DS/data` or
`sdmc:/NFSHP2`, or point `nfshp2_config.txt` at wherever you put it. Only
`GLOBAL/`, `FRONTEND/`, `LANGUAGES/` and `MOVIES/INTRO/EALOGO_EN.M3V` are
needed to reach the main menu -- about 22 MB.

## Status

Phase 2 (boot flow and frontend menus) complete: the port boots the way the
PS2 game boots -- `BootAutoload`, the title screen with the EA logo movie
playing into its movie plane, `PRESS START`, then the main menu, navigable on
the D-pad, with the real textures, fonts and translated strings in any of the
eight shipped languages. See `TASKS.md` for the current phase and
`HANDOFF.md` for how each format was cracked.
