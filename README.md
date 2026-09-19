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

## Status

Phase 0 (project scaffolding) in progress: build skeleton boots to a
diagnostic stub screen. See `TASKS.md` for current phase and next steps.
