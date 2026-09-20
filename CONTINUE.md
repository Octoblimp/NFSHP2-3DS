# CONTINUE

Where the next session picks up. Written at the end of Session 14
(2026-09-20). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

Phases 0-2 are complete: the frontend boots, plays the EA logo, reaches the
main menu, walks into all three screens it leads to, and animates doing it.
Phase 3 is open at task 21, which is **half done -- 21a, the geometry
decoder, is finished and verified; 21b, the citro3d submission path, is
written and compiling but not yet on screen.**

All nine cross-checkers pass, plus the table generator:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/gen_bmath_tables.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios,  6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1246 lines, 0 differ
bootflow_check     12 scenarios,  3659 lines, 0 differ
bslotpool_check    17 scenarios,   990 lines, 0 differ   (37/37 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (51/51 mutations caught)
bui_check          FRONTB.BUN    1395 lines, 0 differ
gen_bmath_tables --check           bmathtab.c is up to date
```

Two mutation runners are kept rather than thrown away:
`python tools/bslotpool_mutate.py` (~20 minutes) and
`python tools/geometry_mutate.py` (~2 minutes; `--full` for all 30 files).

Open tasks: **11** (16 and 21 in progress, 22-31 not started).

## Task 21b -- the immediate next thing

**One car on the top screen, from `CARS\*\GEOMETRY.BIN`, reachable from the
existing viewer mode.** A single car is one solid list and needs no
streaming decision, which is why it is the cheapest first milestone.

Everything below it is already written and builds for ARM:

* `3DS Files/source/geometry.c`/`.h` -- the decoder. `geo_open` indexes a
  buffer, `geo_strip_entry` reads one 64-byte entry, `geo_strip_begin` /
  `geo_decode_next` walk a solid's strips in one pass. Nothing allocates.
* `3DS Files/source/geosolid.v.pica` -- transform plus one directional light
  in view space.
* `3DS Files/source/georender.c`/`.h` -- `georender_init`, `georender_bake`
  (one solid -> one linear-heap triangle list, strips sorted by
  `TextureNumber` so a solid draws in one call per texture),
  `georender_set_camera`, `georender_set_light`, `georender_draw`.

What is left:

1. **Wire it into `main.c`.** `C3D_Init` and the `C3D_RenderTarget` already
   exist there (line ~869); the viewer loop is at ~1049. Needs a depth
   buffer -- the existing target is `C2D_CreateScreenTarget`, which may not
   have one, so check before assuming `C3D_DepthTest` does anything.
2. **Textures.** Each `eTextureTable` entry is `{NameHash, ptr}`; resolve the
   hash with `texpack_find` and upload with `texpack_upload`, which already
   hands back a `C3D_Tex`. Note `texpack_upload` pads to a power of two and
   the image sits in the top-left, so UVs must be taken against the
   *padded* `out->width`/`out->height`, not `TexInfo`'s. That interacts with
   the ST values, which are 0..1 against the unpadded image.
3. **Which pack.** The car textures are not in `GEOMETRY.BIN`; find the
   `0xb0300001` pack that holds them (`docs/formats/texture-pack.md`,
   `tools/bhash.py` to resolve names).
4. **Light materials** at `0x0003401d` are still unused -- `lightMaterial`
   is decoded and carried on every strip but nothing reads it yet.

## What not to trust

* **`eSolid.NumTextureTableEntries` (0xAC) is zero on all 1,411 solids.**
  Count the `0x00034006` chunk instead; `geometry.c` does. `NumLightMaterials`
  at 0xAE is fine.
* **`eSolid.NumPolys` is stale** for 19 of the 1,465 solids. The per-strip
  counts are the truth.
* **`eStripEntry.TextureNumber` can be one past the end** -- 25 strips do
  that, and it means untextured. Range-check it.
* **Normals are 125..127, not 126..127**, and 53 across the car set are
  exactly zero. A zero normal is not the same as "this strip has no normal
  field" (about 17% of strips); check `hasNormals`.
* **`TRACKS\TRACKA12.BUN` has no solid list.** All 1,135 track solids are in
  B12.
* **Chunk payloads are front-padded with `0x11`** to a 16-byte boundary, so
  `0x00034003` is sometimes 204 bytes rather than 192. `docs/formats/bchunk.md`
  has the rule.
* **The GS had no hardware backface culling** -- the VU did it in software,
  and nothing in the data forces a consistent winding. `georender_draw` uses
  `GPU_CULL_NONE` deliberately. Do not "fix" that without evidence from the
  normals.
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

## PICA200 notes, from writing the first shader here

* At most **one uniform per instruction**, and only in the **first** source
  slot. `dp3 r3, r2, lightVec` is rejected; `dp3 r3, lightVec, r2` is fine.
* `mad` cannot take a uniform in either slot it leaves over. Spell
  ambient-plus-diffuse as `mul` then `add`.
* It is `Mtx_Identity`, not `C3D_Mtx_Identity`.
* `.v.pica` files are already handled by the Makefile -- they compile
  straight to `.shbin.o` plus a `_shbin.h`, no extra target needed.

## After task 21

In order: 22 sound/DSP, 23 Camera, 24 TrackRoute/Esp, 25 car sim, 26
race/cop AI, 27 track render/stream/collision, 28 New3DS perf, 29
save/options/sound mix, 30 split-screen scope, 31 final CIA + Old3DS/New3DS
pass.

**Phase 4 constraint, from the user:** the gameplay HUD is to be designed for
**two screens from the start** -- some readouts on the bottom screen rather
than all stacked on the top one, to keep the view of the road clear. Which
elements go below is not decided; ask first. It is written at the head of
Phase 4 in `TASKS.md` too.

Task 16 (`bui.c`/`uirender.c`) is still `[~]`; 18b's two scrolling textures
are the outstanding part of it.

## Carried over, still open

* Two scrolling textures (`SCREEN_LINES`, `ROADLINES`) in the frontend
  background, from task 18b.
* Light materials (`0x0003401d`) decoded but unused.
