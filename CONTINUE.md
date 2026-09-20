# CONTINUE

Where the next session picks up. Written at the end of Session 12
(2026-09-20). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

Phases 0-2 are complete: the frontend boots, plays the EA logo, reaches the
main menu, walks into all three screens it leads to, and animates doing it.
Phase 3 is open at task 20 -- **task 19, the bware math library, is done**.

All six cross-checkers pass, plus the table generator:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/gen_bmath_tables.py --check
```

```
bvector_check      27 scenarios, 5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios, 6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios, 2219 lines, 0 differ
bscreens_check     17 scenarios, 1246 lines, 0 differ
bootflow_check     12 scenarios, 3659 lines, 0 differ
bui_check          FRONTB.BUN     1395 lines, 0 differ
gen_bmath_tables --check           bmathtab.c is up to date
```

Open tasks: **12** (16 in progress, 20-31 not started).

## Task 20 -- the immediate next thing

`bSlotPool` / `SlotPool` / `SlotPoolManager`, `0x0023f508`-`0x00240198`,
3216 bytes, 34 symbols. It sits directly below `bVector.obj` in `.text`, and
`3DS Files/source/heapcfg.c` is the floor it lands on.

```bash
python tools/mipsdis.py --addr 0x23f508 --count 804     # whole object
```

Three layers, and the decode should follow them:

* **free functions** `0x0023f508`-`0x0023f638` -- thin forwarders,
  `bNewSlotPool`, `bMalloc`, `bFree` (two overloads each of malloc and free),
  `bGetSlotNumber`, `bGetSlot`, `bIsSlotPoolFull`, `bCountFreeSlots`,
  `bCountTotalSlots`. Most are 8-32 bytes; start here, they name the members.
* **`SlotPool`** `0x0023f638`-`0x0023fd18` -- the real work.
  `NewSlotPool`, `FlushSlotPool`, `ExpandSlotPool` (`0x0023f760`),
  `CleanupExpandedSlotPools` (`0x0023f820`, 520 B, the largest),
  `Malloc` (`0x0023fa28`), `FastMalloc` (`0x0023faf8`), `Free`, and the
  array overloads `Malloc(int, void**)` (`0x0023fb50`) / `Free(void*, void*)`.
* **`SlotPoolManager`** `0x0023fd18`-`0x00240070` -- ctor/dtor, the
  new/delete pair that registers pools on a list, `PrintAllSlotPools` and a
  manager-wide `CleanupExpandedSlotPools`. Plus
  `_GLOBAL_$I$`/`_GLOBAL_$D$` at `0x00240070`/`0x00240080` -- a static
  manager instance built at load time.

The struct layout is **already recovered** and does not need to be inferred
from the code. `docs/mdebug_structs.txt:10445`:

```
struct SlotPool, 52 bytes
  +0   bTNode<SlotPool> base (the first named field starts at byte 8)
  +8   NextSlotPool      SlotPool*
  +12  DebugName         const char*
  +16  FreeSlots         (free-list head)
  +20  Flags             SlotPoolFlags
  +24  NumAllocatedSlots
  +28  MostNumAllocatedSlots
  +32  MemoryPool
  +36  NumSlots
  +40  SlotSize
  +44  TotalNumSlots
  +48  Slots
```

`bTList<SlotPool>` and `bTNode<SlotPool>` destructors are in the object
(`0x00240090`, `0x00240190`), so the pool list is the engine's intrusive
template list, not a hand-rolled one. Check whether `bTList` is already
decoded anywhere before re-reading it.

Things to settle while decoding, because they change the port:

* `MostNumAllocatedSlots` is a high-water mark, which means this allocator was
  instrumented. Find out whether `PrintAllSlotPools` is compiled in or
  stubbed in the retail build before porting a debug path nobody calls.
* `ExpandSlotPool` + `CleanupExpandedSlotPools` mean pools **grow**, and the
  cleanup is 520 bytes -- the most complicated thing in the object. Whatever
  it does with the expanded blocks is the part to get exactly right; a
  3DS-side pool that leaks expansions will die slowly.
* `FastMalloc` next to `Malloc` suggests one skips a check the other makes.
  Diff them rather than assuming.

Then the usual shape: `3DS Files/source/bslotpool.c`/`.h`, LF line endings,
hook-driven, no `<3ds.h>`; `tools/src/bslotpool_test.c` driving the C;
`tools/bslotpool_check.py` an independent Python model written from the
disassembly, **not** from the C, diffed line for line to "N scenarios, M
lines, 0 differ"; then mutate it and confirm the diff count moves.

This one is integer and pointer work, so float determinism is not the
difficulty for once -- the difficulty is that an allocator's cross-check has
to compare *sequences* of operations, not single calls. Model the pool as a
byte array with an index-based free list so the Python side can print the same
slot numbers the C does, and drive both with the same scripted
malloc/free/expand/flush sequence.

## After task 20

In order: 21 VU1 geometry to citro3d (survey work already done in
`docs/formats/solid-geometry.md`), 22 sound/DSP, 23 Camera, 24 TrackRoute/Esp,
25 car sim, 26 race/cop AI, 27 track render/stream/collision, 28 New3DS perf,
29 save/options/sound mix, 30 split-screen scope, 31 final CIA +
Old3DS/New3DS pass.

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
* A mutation runner must scan output for the line containing `differ`, not
  take line 1 -- a mutation that leaves a variable unused makes `hostbuild`
  print `compiler warnings:` first, and the runner will report `?` for a
  mutation it actually caught.
* `tools/build_cia.ps1` maps a space-free `subst` drive, because the devkitPro
  Makefile template breaks on paths with spaces.
