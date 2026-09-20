# CONTINUE

Where the next session picks up. Written at the end of Session 15
(2026-09-20). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

Phase 3's task 21 is **done**: cars draw on the top screen out of
`CARS\*\GEOMETRY.BIN` with their own textures, lit, reachable as the third
mode SELECT cycles to. Phases 0-2 are complete except for one stub -- task 16
is still `[~]` and the only thing outstanding in it is 18b's two scrolling
background textures.

Nine cross-checkers pass, plus the table generator:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/gen_bmath_tables.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios,  6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1246 lines, 0 differ
bootflow_check     12 scenarios,  3659 lines, 0 differ
bslotpool_check    17 scenarios,   990 lines, 0 differ   (37/37 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (53/53 mutations caught)
texsrc_check       6 packs, 2 levels, 2952 textures, 0 differ
bui_check          FRONTB.BUN    1395 lines, 0 differ
gen_bmath_tables --check           bmathtab.c is up to date
```

Two mutation runners are kept rather than thrown away:
`python tools/bslotpool_mutate.py` (~20 minutes) and
`python tools/geometry_mutate.py` (~2 minutes; `--full` for all 30 files).

Open tasks: **10** (16 in progress, 22-31 not started).

## Next, in order

1. **Task 16** -- the two scrolling frontend background textures,
   `SCREEN_LINES` and `ROADLINES`, carried over from 18b. That is the whole
   of what is left in 16, and finishing it closes Phase 2. The scroll itself
   is already decoded: `TextureInfo::GetScroll` (`0x00100a60`), `ScrollType`
   at +0x79 and the two speeds and the time step at +0x7C, with
   `tools/texture_convert.py`'s `scroll_uv(t, time)` as the reference.
2. Then **22** (sound/DSP) onwards in order: 23 Camera, 24 TrackRoute/Esp,
   25 car sim, 26 race/cop AI, 27 track render/stream/collision, 28 New3DS
   perf, 29 save/options/sound mix, 30 split-screen scope, 31 final CIA +
   Old3DS/New3DS pass.

**Phase 4 constraint, from the user:** the gameplay HUD is to be designed for
**two screens from the start** -- some readouts on the bottom screen rather
than all stacked on the top one, to keep the view of the road clear. Which
elements go below is not decided; ask first. It is written at the head of
Phase 4 in `TASKS.md` too.

## What not to trust

Ordered roughly by how much time it costs to rediscover.

* **A passing cross-check does not mean the decoder is right.** Session 15
  found two decoder bugs `geometry_check.py` had been passing for four
  sessions, one of them in a field the digest explicitly covers. Both
  implementations were wrong the same way, because the C was written from a
  document that was written from the Python. Independence has to reach back
  to the disc or the ELF -- and look at the output on the emulator too.
* **ST is mirrored two vertices to a quad**, `(S_even, T_even, T_odd,
  S_odd)`, not transposed like XYZ. The cheap check is the S==T rate: 44.43%
  if you have it wrong, 1.68% if you have it right.
* **Skip `0x11` chunk filler a whole entry at a time on `0x00034006` and
  `0x0003401d`.** A byte scan eats the first byte of a table whose first hash
  ends in `0x11` (`TS50_C`: `0x4342fd11`) and shifts every hash in that solid
  by 8 bits, silently. The byte scan is still correct for the header, the
  entry table and the packet blob, checked against their sizes on all 1,461
  solids.
* **The game's T counts down from the image's top row.** A citro3d renderer
  over `texpack_upload` needs `v = 1 - T * scale`; `uirender.c`'s
  `subtex_from_pixels` is the hardware-verified precedent.
* **58 of the 132 texture hashes car geometry refers to are in no pack on the
  disc** -- 9.0% of strips. That is the data, not a bug to chase. Draw those
  strips untextured, the same path the `TextureNumber >= NumTextures`
  sentinel takes.
* **`eSolid.NumTextureTableEntries` (0xAC) is zero on all solids.** Count the
  `0x00034006` chunk instead; `geometry.c` does. `NumLightMaterials` at 0xAE
  is fine.
* **`eSolid.NumPolys` is stale** for 19 of the 1,465 solids. The per-strip
  counts are the truth.
* **`eStripEntry.TextureNumber` can be one past the end** -- 25 strips do
  that, and it means untextured. Range-check it.
* **Normals are 125..127, not 126..127**, and 53 across the car set are
  exactly zero. A zero normal is not the same as "this strip has no normal
  field" (about 17% of strips); check `hasNormals`.
* **`TRACKS\TRACKA12.BUN` has no solid list.** All 1,135 track solids are in
  B12.
* **The GS had no hardware backface culling** -- the VU did it in software,
  and nothing in the data forces a consistent winding. `georender_draw` uses
  `GPU_CULL_NONE` deliberately. Do not "fix" that without evidence from the
  normals.
* **`C2D_CreateScreenTarget` gives no depth buffer**, and `C3D_DepthTest`
  against no depth buffer silently does nothing. `main.c` builds the top
  target with `C3D_RenderTargetCreate(240, 400, GPU_RB_RGBA8,
  GPU_RB_DEPTH24_STENCIL8)` instead.
* **Azahar's X button is `Z` (0x5A) and its Y is `X` (0x58).**
  `%APPDATA%\Azahar\config\qt-config.ini` is the authority; guessing from the
  letter costs a wasted run that looks like a code bug.
* **A screenshot harness must not sleep.** A *faster* boot moves the
  keypresses earlier, not later, and the shot lands on the wrong screen.
  `main.c` logs its mode on every SELECT and `tools/run_azahar_geo.ps1`
  presses-and-confirms against the log.
* **`.gitattributes` / `core.autocrlf=true`**: `TASKS.md` is CRLF and
  `HANDOFF.md`, `CONTINUE.md`, every `.c`/`.h` and every `tools/*.py` except
  `geometry_convert.py` (CRLF) are LF. Read and write with an explicit
  newline; do not let a tool normalise a file.
* **Checkers must not pipe harness stdout.** `subprocess.run` with
  `capture_output=True` deadlocks against a runaway child, and `timeout=`
  cannot rescue it because killing a cygwin-built exe from Windows does not
  reliably close its handles. `geometry_check.py` writes to a file and caps
  the line count; the older checkers still use a pipe and have the same
  latent problem.

## PICA200 notes

* At most **one uniform per instruction**, and only in the **first** source
  slot. `dp3 r3, r2, lightVec` is rejected; `dp3 r3, lightVec, r2` is fine.
* `mad` cannot take a uniform in either slot it leaves over. Spell
  ambient-plus-diffuse as `mul` then `add`.
* A `GPU_BYTE`/`GPU_UNSIGNED_BYTE` attribute is **not** normalised on its way
  in -- it arrives as the plain integer, so scaling is the shader's job.
  Leave an RGBA8 colour unscaled and the whole model saturates to white.
* It is `Mtx_Identity`, not `C3D_Mtx_Identity`.
* `.v.pica` files are already handled by the Makefile -- they compile
  straight to `.shbin.o` plus a `_shbin.h`, no extra target needed.

## Carried over, still open

* Two scrolling textures (`SCREEN_LINES`, `ROADLINES`) in the frontend
  background, from task 18b. This is task 16's remainder.
* **No alpha blending on geometry.** Glass draws opaque. It is not vertex
  alpha -- all 212,408 car vertex colours have the alpha bit set -- so it is
  texture alpha plus a GS blend mode, and the blend state has not been
  recovered from the ELF. Strip `Flags` high bytes seen: `0x4100` on body,
  `0xc100` on the unresolved textures, `0x5000`, `0x0c00`, `0x0000`.
* **Car part transforms** are not decoded, so wheels, mirrors and wipers all
  sit at the origin. `geoview` steps solids one at a time rather than imply
  otherwise. Needed before a car can be driven.
* Light materials (`0x0003401d`) decoded and carried on every strip, read by
  nothing.
* 58 unresolved texture hashes; only `0xece04847` = `WIPER01` named so far.
