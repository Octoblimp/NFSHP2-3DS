# CONTINUE

Where the next session picks up. Written at the end of Session 11
(2026-09-20). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

Working tree clean at `51d9b30`. Phases 0-2 are complete: the frontend boots,
plays the EA logo, reaches the main menu, walks into all three screens it
leads to, and animates doing it. Phase 3 is open at task 19.

All four cross-checkers pass:

```bash
python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN
```

```
banim_check        23 scenarios, 2219 lines, 0 differ
bscreens_check     17 scenarios, 1246 lines, 0 differ
bootflow_check     12 scenarios, 3659 lines, 0 differ
bui_check          FRONTB.BUN     1395 lines, 0 differ
```

Open tasks: **13** (19 in progress, 20-31 not started).

## Task 19 -- the immediate next thing

The bware math library is **decoded but not written**. The decode is in
`docs/formats/bmath.md` with an address for every rule. Do not re-disassemble
what is already in there.

Done: all 19 functions of `bMath.obj`, all 38 of `bVector.obj`, all 7 of
`bMatrix.obj`, 3 of 9 in `bQuaternion.obj`.

### 1. Finish the `bQuaternion` decode (7 functions, ~1.3 KB)

```bash
python tools/mipsdis.py --addr 0x2411f0 --count 630     # whole object
```

| function | address | size |
|----------|---------|------|
| `bSlerp(bQuaternion*, const bQuaternion*, const bQuaternion*, float)` | `0x00241570` | 384 B, uses VU0 |
| `bConjugate` | `0x002416f0` | 52 B |
| `bLength` | `0x00241728` | 44 B |
| `bNormalize` | `0x00241758` | 60 B |
| `bMult` | `0x00241798` | 100 B |
| `bQuaternionToMatrix` | `0x00241800` | 192 B |
| `bMatrixToQuaternion` | `0x002418c0` | 732 B |

`bMatrixToQuaternion` is probably the same Shepperd branch as the
`bQuaternion(const bMatrix4&)` constructor at `0x002411f0` (already decoded,
including the `next[] = {1,2,0}` table at `0x002a3060`) -- but it is 732 bytes
against the constructor's 704, so confirm rather than assume.

### 2. Write the modules

Four pairs under `3DS Files/source/`, LF line endings, hook-driven style, no
`<3ds.h>`:

* `bvector.h` -- the `bVector2/3/4`, `bFixVector2/3` types; everything else
  includes it
* `bmath.c` / `.h` -- scalar, random, trig, the four data tables
* `bvector.c` / `.h`
* `bmatrix.c` / `.h`
* `bquat.c` / `.h` -- includes `bmatrix.h`

Embed `bSinTable` verbatim (513 `s16` from `0x00315928`); it does not
regenerate from any model tried. The two atan tables do regenerate exactly as
`(int)(atan(i/s) * 10430.3779296875)`, but embed them anyway so the port does
not depend on the host `libm`. `bASinTable` is 192 x 8 bytes from
`0x003152a0`.

Extraction one-liner:

```bash
python -c "import struct,sys; sys.path.insert(0,'tools'); import mipsdis; print(struct.unpack('<513h', mipsdis.Elf().read(0x315928,1026)))"
```

### 3. Verify before you build on it

**`bMulMatrix(out, m1, m2)` is decoded as `out = m2 * m1`** -- right to left.
That came out of the COP2 macro-mode encodings, not from a caller. Find one
caller that does something geometrically obvious and check the order before
writing code against it. If it is backwards, it is backwards everywhere.

### 4. Harness, checker, mutation test

The usual shape: `tools/src/bmath_test.c` driving the C, `tools/bmath_check.py`
as an independent Python model written from the disassembly (not from the C),
diffed line for line to "N scenarios, M lines, 0 differ". Float determinism is
the whole difficulty -- the Python side must round to float32 after **every**
operation. Then mutate a constant or two and confirm the diff count moves; a
cross-check that cannot fail proves nothing.

### 5. Fold `banim_bsin` out

`3DS Files/source/banim.c` carries a private copy of `bSin`. Once `bmath.c`
exists, delete it and call the real one. `banim_check.py` imports `bsin` too --
it will need the same treatment, and `bscreens_check.py` imports
`banim_check` wholesale, so run all three after.

`tCubic1D` stays where it is. It is `Point.obj`, game code, not bware -- the
Session 10 handoff said otherwise at one point and was corrected.

## After task 19

In order: 20 `bSlotPool` (`0x0023f508`-`0x00240198`, already adjacent to the
code just read, and `heapcfg.c` is the floor it sits on), 21 VU1 geometry to
citro3d (survey work already done in `docs/formats/solid-geometry.md`), 22
sound/DSP, 23 Camera, 24 TrackRoute/Esp, 25 car sim, 26 race/cop AI, 27 track
render/stream/collision, 28 New3DS perf, 29 save/options/sound mix, 30
split-screen scope, 31 final CIA + Old3DS/New3DS pass.

## Carried over, still open

* Two scrolling textures (`SCREEN_LINES`, `ROADLINES`, via
  `TextureInfo::GetScroll` `0x00100a60`) are not animated. Filed under 18b but
  they belong to the renderer: `uirender.c` would offset the UVs.
* `0xab671c9a` and `0x1042eac3`, the two bloom text objects, are still
  uncracked. `tools/bhash_crack.py` is dictionary-bound, not compute-bound, at
  these lengths.
* `bSinTable`'s generator is unidentified. Not blocking -- the table is
  embedded -- but it is the one thing in the math library that is copied
  rather than understood.

## Environment reminders

* **Heredocs mangle backslashes.** Write anything large with the `Write` tool
  and run it with `python <path>`, using `C:/...` forward-slash paths (Python
  on Windows cannot open `/c/...`).
* **Line endings are per file.** `gameflow.*` and `TASKS.md` are CRLF;
  everything else -- `bscreens.*`, `banim.*`, `bui.*`, `main.c`,
  `uirender.*`, `tools/*.py`, `tools/src/*.c`, `HANDOFF.md`, the docs -- is
  LF. Patch scripts should detect and restore, not assume.
* **Build host harnesses through `tools/hostbuild.py`**; gcc invoked from Git
  Bash cannot find its own `/usr/include`, and the script retries via the
  msys2 login shell.
* **gcc evaluates arguments right to left here.** Do not call a function
  inside a `printf` alongside the out-params it writes.
* `tools/build_cia.ps1` maps a space-free `subst` drive, because the devkitPro
  Makefile template breaks on paths with spaces.
