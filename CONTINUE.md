# CONTINUE

Where the next session picks up. Written at the end of Session 13
(2026-09-20). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

Phases 0-2 are complete: the frontend boots, plays the EA logo, reaches the
main menu, walks into all three screens it leads to, and animates doing it.
Phase 3 is open at task 21 -- **task 20, the slot-pool allocator, is done**.

All seven cross-checkers pass, plus the table generator:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/gen_bmath_tables.py --check
```

```
bvector_check      27 scenarios, 5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios, 6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios, 2219 lines, 0 differ
bscreens_check     17 scenarios, 1246 lines, 0 differ
bootflow_check     12 scenarios, 3659 lines, 0 differ
bslotpool_check    17 scenarios,  990 lines, 0 differ   (37/37 mutations caught)
bui_check          FRONTB.BUN     1395 lines, 0 differ
gen_bmath_tables --check           bmathtab.c is up to date
```

The slot-pool mutation runner is kept, unlike the earlier ones:
`python tools/bslotpool_mutate.py` (~20 minutes, one build per mutation).

Open tasks: **11** (16 in progress, 21-31 not started).

## Task 21 -- the immediate next thing

**Rendering: VU1 geometry submission -> citro3d.** Unlike every task before
it, the format work is already finished and verified -- the job is a port,
not a decode.

`docs/formats/solid-geometry.md` has the whole thing: the `0x80034000` chunk
tree, `eSolid` (192 bytes), `eStripEntry` (64 bytes), and the VU1 packet's
VIF UNPACK replay with its transposed XYZ/ST, its RGBA5551 colours, its
signed-byte normals, the ADC suppression bitfield and the winding rule that
follows from it. `tools/geometry_convert.py` already reads all of it and has
been checked against the shipped data itself, not against a second
implementation:

* every decoded vertex of all 1,465 solids falls inside its own solid's AABB;
* the ADC rule reproduces `eStripEntry.NumPolys` for all 22,280 strips;
* the normals come out unit length;
* the winding agrees with the per-vertex normals on 99.65% of triangles, the
  remainder being concave corners where a smoothed normal genuinely
  disagrees with its face.

That makes this task's cross-check unusually strong, and it should be split
in two:

**21a, the decoder.** `3DS Files/source/geometry.c`/`.h`: the chunk tree, the
strip table, the VIF replay, and a triangle list per strip with position, ST,
colour and normal. Written from `docs/formats/solid-geometry.md`, never from
`geometry_convert.py`. Then `tools/src/geometry_test.c` drives it and
`tools/geometry_check.py` diffs the transcript against the Python, which is
the independent side for once because it came first and was validated against
the disc. Mutate it afterwards -- `tools/bslotpool_mutate.py` is the template
now, and this one is worth keeping too.

Things to settle while writing it, because they change the port:

* **Memory.** 1,135 solids in `TRACKS\TRACKB12.BUN` alone, and the 3DS has
  nothing like the headroom to hold them all decoded. Decide early whether
  the decoder streams a strip at a time into a reusable buffer or bakes whole
  solids, and size it against `g_heapInfo` rather than guessing. This is the
  first caller `bslotpool.c` was ported for: fixed-size slots, a known count,
  an expansion chain when an estimate is wrong.
* **`NumPolys` in the `eSolid` header is stale** for 19 of the 1,465 solids.
  The per-strip counts are the truth. Anything that preallocates from the
  header field will be wrong on those 19 and right everywhere else, which is
  the worst failure mode available.
* **Chunk payloads are front-padded with `0x11` to a 16-byte boundary**, so
  `0x00034003` is sometimes 204 bytes rather than 192. Skip the filler run
  before reading any struct; `docs/formats/bchunk.md` has the rule.
* **The GS has no hardware backface culling** -- the VU did it. Nothing in
  the data forces a consistent winding, so decide what citro3d's cull mode
  should be and prove it against the normals rather than by eye.

**21b, the citro3d submission path.** Vertex format, the shader, the texture
binding through the `0xb0300001` packs (`docs/formats/texture-pack.md`,
hashes resolved with `tools/bhash.py`), the light materials at `0x0003401d`,
and a draw. `uirender.c` is the closest thing to a precedent in the tree but
it is citro2d; this is the first real citro3d work in the project.

The cheapest first milestone is one car rendered on the top screen from
`CARS\*\GEOMETRY.BIN`, reachable from the existing viewer mode, because a
single car is one solid list and needs no streaming decision to display.

## After task 21

In order: 22 sound/DSP, 23 Camera, 24 TrackRoute/Esp, 25 car sim, 26 race/cop
AI, 27 track render/stream/collision, 28 New3DS perf, 29 save/options/sound
mix, 30 split-screen scope, 31 final CIA + Old3DS/New3DS pass.

Task 16 (`bui.c`/`uirender.c`) is still `[~]`; 18b's two scrolling textures
below are the outstanding part of it.

## Carried over, still open

* Two scrolling textures (`SCREEN_LINES`, `ROADLINES`, via
  `TextureInfo::GetScroll` `0x00100a60`) are not animated. Filed under 18b but
  they belong to the renderer: `uirender.c` would offset the UVs.
* `0xab671c9a` and `0x1042eac3`, the two bloom text objects, are still
  uncracked. `tools/bhash_crack.py` is dictionary-bound, not compute-bound, at
  these lengths.
* `bSinTable`'s generator is unidentified. Not blocking -- the table is
  embedded verbatim and `gen_bmath_tables.py --check` holds it to the ELF --
  but it is the one thing in the math library that is copied rather than
  understood. A two-parameter fit lands within 1 LSB on an angular step
  31 ppm short of `2*pi/512`, which no plausible constant produces.

## What not to trust in the new code

* **The slot pool has no safety checks, on purpose.** `bSlotFree` does no
  NULL test, no ownership test and no double-free test, because the ROM
  does none; a double free corrupts the free list silently and drives
  `numAllocatedSlots` negative, which then makes `bSlotMallocN` size an
  expansion from an accounting figure that lies. `bGetSlotNumber` divides
  *unsigned*, so a pointer below the slot array comes back as 357913939,
  not -2. And `bFlushSlotPool` on a pool that has expanded strands every
  expanded slot -- it is safe only where the original calls it, on a chain
  one long inside `NewSlotPool`.

* **`bSlerp` assumes unit quaternions.** The 0.05 epsilon is the only thing
  keeping `bASin`'s argument inside the 209-entry `bASinTable`; an
  unnormalised input reads past the end of the table rather than returning a
  wrong angle. Callers must normalise. Said in `bquat.h`, `bquat.c` and
  `docs/formats/bmath.md`, repeated here because it will be forgotten.
* **The quaternion `bNormalize` deliberately diverges** from the PS2: it uses
  a true reciprocal square root where VU0 uses a hardware estimate. Anything
  comparing against a PS2 capture will see last-bit differences there and
  nowhere else in the library.
* **Two quaternion-to-matrix routines ship and both are needed.**
  `bQuaternionGetMatrix` and `bQuaternionToMatrix` differ only in the order
  the squares are summed, so they disagree in the last float32 bit, and both
  have callers. Do not collapse them.
* `bExpandBoundingBox` (`0x00240f80`) feeds uninitialised stack into the `w`
  lane on the PS2. The port operates on x/y/z only and says so; it is not a
  faithful reproduction and cannot be.
* Four cases the cross-check deliberately does not cover -- zero `len`, zero
  quaternion, singular matrix, non-unit slerp -- because the EE FPU has no
  infinities or NaNs and comparing IEEE behaviour against hardware that cannot
  produce it proves nothing. Listed at the top of `tools/src/bvector_test.c`.

## Environment reminders

* **Heredocs mangle backslashes.** Write anything large with the `Write` tool
  and run it with `python <path>`, using `C:/...` forward-slash paths (Python
  on Windows cannot open `/c/...`).
* **There is no `.gitattributes`, and `core.autocrlf` is `true` here.** The
  repo stores LF, so the per-file convention below describes how the files
  were *written*, not anything git enforces -- a fresh clone on Windows would
  check every one of them out as CRLF and the convention would quietly stop
  being true. Worth pinning with a `.gitattributes` before anyone else clones
  this; left alone so far because adding one renormalises the whole tree in
  one commit and that should not ride along with a task.
* **Line endings are per file.** `gameflow.*` and `TASKS.md` are CRLF;
  everything else -- `bscreens.*`, `banim.*`, `bui.*`, `bmath.*`, `bvector.*`,
  `bmatrix.*`, `bquat.*`, `main.c`, `uirender.*`, `tools/*.py`,
  `tools/src/*.c`, `HANDOFF.md`, the docs -- is LF. Patch scripts should
  detect and restore, not assume.
* **Build host harnesses through `tools/hostbuild.py`.** It carries three
  workarounds for this machine: `-nostdinc` plus explicit `-isystem` paths
  because devkitPro's cygwin gcc cannot find its own `/usr/include`;
  compile-then-link in two steps because a one-shot build pulls cygwin's
  `libcmain.o` and fails on `WinMain`; and `-ffp-contract=off` so the host
  cannot fuse a multiply-add that the EE does not fuse.
* **gcc evaluates arguments right to left here.** Do not call a function
  inside a `printf` alongside the out-params it writes.
* **A mutation runner must not read its verdict off line 1.** `hostbuild`
  prints `compiler warnings:` first and keeps going, so line 1 is the
  compiler's; the last line is whatever stderr trailed off with. Scan for
  the line containing `differ`, and for failures the line starting
  `harness failed`. `tools/bslotpool_mutate.py` is the worked example.
  While there: a crashed harness reports cygwin's `signal << 8`, so 2816
  is SIGSEGV, and a mutation that leaves a variable unused is caught by
  `-Wall` rather than by the checker -- that is a defective mutation, not
  a result.
* `tools/build_cia.ps1` maps a space-free `subst` drive, because the devkitPro
  Makefile template breaks on paths with spaces.
