# CONTINUE

Where the next session picks up. Written at the end of Session 19
(2026-09-21). `HANDOFF.md` is the running narrative; this file is the short
list of what to do next and what not to trust.

## State

**Phases 0-3 are closed.** Cars draw on the top screen out of
`CARS\*\GEOMETRY.BIN` (task 21), the frontend makes the disc's own menu
sounds through a ported `bSnd` over ndsp, and the geometry viewer is now
framed by the shipped `CM_ORBIT_CAR` boom on the ported `Camera` rather than
by a camera of its own -- all three heard or seen on Azahar, not just diffed.

Task 24 closed Phase 3: `TrackRoute.obj` is ported and the track's
centreline, its driving lines and its signposts all load. It is diffed, not
run -- see "Next" below for why, and for what task 27 owes it.

Fourteen cross-checkers pass, plus the table generators:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/sndbank_check.py out/SOUND && python tools/bsnd_check.py out/SOUND && python tools/emath_check.py && python tools/camera_check.py && python tools/trackroute_check.py && python tools/carstate_check.py && python tools/gen_bmath_tables.py --check && python tools/gen_bsnd_tables.py --check
```

```
bvector_check      27 scenarios,  5721 lines, 0 differ   (23/23 mutations caught)
bmath_check        18 scenarios,  6065 lines, 0 differ   (12/12 mutations caught)
banim_check        23 scenarios,  2219 lines, 0 differ
bscreens_check     17 scenarios,  1246 lines, 0 differ
bootflow_check     12 scenarios,  3659 lines, 0 differ
bslotpool_check    17 scenarios,   990 lines, 0 differ   (37/37 mutations caught)
geometry_check     30 files,     42047 lines, 0 differ   (53/53 mutations caught)
texsrc_check       6 packs, 2 levels, 2958 textures, 0 differ
bui_check          FRONTB.BUN    1395 lines, 0 differ
sndbank_check      30 banks,       908 lines, 0 differ   (20000 mutations, 0 disagree)
bsnd_check         12 scenarios,  5157 lines, 0 differ   (25/25 mutations caught)
emath_check         9 scenarios,  2416 lines, 0 differ   (39/39 mutations caught)
camera_check        7 scenarios,  1200 lines, 0 differ   (40 caught, 7 equivalent)
trackroute_check   10 scenarios,   671 lines, 0 differ   (52 caught, 1 equivalent)
carstate_check     10 scenarios,   653 lines, 0 differ   (56 caught, 7 equivalent)
gen_bmath_tables --check           bmathtab.c is up to date
gen_bsnd_tables  --check           bsndtab.c is up to date
```

`texpack_check.py` takes a file and is run per pack; it now also diffs the UV
scroll, offsets and all: `FRONTB.BUN` 2 scrolling textures, `INGAMEB.BUN` 1,
`TEX12LOCATION.BIN` 21, 0 differ.

Two mutation runners are kept rather than thrown away:
`python tools/bslotpool_mutate.py` (~20 minutes) and
`python tools/geometry_mutate.py` (~2 minutes; `--full` for all 30 files).

Both sound checkers want a directory of `.SBK`. Build it first:

```bash
python tools/audio_pack.py extracted/SOUND out/SOUND
```

The emulator's copy lives at `%APPDATA%\Azahar\sdmc\NFSHP2\SOUND` -- that is
the data root `gamedata.c` resolves to on this machine, and the
`.SBK` files go beside the other converted assets. `bsnd_check.py --mutate`
takes about ten minutes; `sndbank_check.py --mutate 20000` takes a couple of
hours.

`camera_check.py --mutate` reports "7 equivalent, 0 unexplained" rather than
"7 survived": the seven are named in the script with an argument each, and
three of them are uncatchable because the disc's velocity record is
structurally zero. See `docs/formats/camera.md`. `trackroute_check.py
--mutate` reads the same way and takes about four minutes.

Open tasks: **7** (25-31). All four the user asked for mid-session are
done and looked at on Azahar: 32 (stretch the frontend to the 3DS's 5:3 top
screen), 33 (the ten unregistered screen names), 34 (the menu description on
the bottom screen, wrapped) and 35 (no console sharing that screen).

The bottom screen is a citro2d target now, not a console. Everything the
console used to show is in `sdmc:/nfshp2_debug.txt`, which is opened `"w"`
and so replaced every boot.

## Next, in order

1. **Task 25**, the car simulation. Phase 4 starts here, and its HUD
   constraint is below -- ask before choosing which readouts go on the
   bottom screen.
2. Then in order: 26 race/cop AI, 27 track render/stream/collision,
   28 New3DS perf, 29 save/options/sound mix, 30 split-screen scope,
   31 final CIA + Old3DS/New3DS pass.
3. **`QuickSpline.obj` (`0x00227e98`) is owed to task 24 and belongs to
   task 27.** `trackroute.c` is diffed but cannot be run for real without
   it: `TrackPathCoordinate::UpdatePosition` (`0x1f5dd0`) is the stub that
   turns a world position into a distance around the track, and
   `SetFirstAndLastPoints`, `Signpost::SetDistances` and
   `TestSignpostConsistency` all go through it. `gTrackPathDistanceFn` is
   the seam -- `NULL` on hardware, a closed-form ramp in the harness. Port
   `QuickSpline`, point the seam at it, and those three become live.
   The CM_TRACK_* movers `cammover.c` left out want the same thing.
4. Whenever a screen class gets ported, take its row in `kScreens[]` off
   `bgf_plain_screen_callback`. Ten of the eighteen are on it -- they draw
   and answer the D-pad and nothing else -- and
   `python tools/screen_registry.py --check-port` lists them, along with
   anything new the port can reach and has not registered. Run it after any
   change to `kScreens[]`: a hash typed by hand is not checked by anything
   else, and a name with no row is a black top screen, not a no-op.

**Phase 4 constraint, from the user:** the gameplay HUD is to be designed for
**two screens from the start** -- readouts on the bottom screen rather than
all stacked on the top one, to keep the view of the road clear.

The split is **decided** (2026-09-21, asked and answered): **bottom screen
takes the minimap, lap/position and objective text; the top keeps the
speedo/tach and the pursuit meter**, because those two are monitored
continuously rather than glanced at and belong in the same eyeline as the
road. Build tasks 25-27's HUD to that from the start rather than making a
top-screen HUD and splitting it later. `uirender.c` (citro2d) is the home
for the bottom-screen widgets; `georender.c` (citro3d) owns the top. Also
at the head of Phase 4 in `TASKS.md`.

## What not to trust

Ordered roughly by how much time it costs to rediscover.

* **A format loaded by casting has no parse step to get wrong -- the struct
  layout *is* the format.** `TrackRoutesLoader` casts the chunk's bytes to
  `TrackRoute *` and registers the pointer; nothing is copied and nothing is
  read field by field. So a field at the wrong offset is not a compile error
  and not a decode failure, it is a route that loads and then reads
  nonsense. Two things follow, and both bit this session: the record's
  `pNext`/`pPrev` are **32-bit slots holding disc garbage**, not host
  pointers, and `sizeof` has to be asserted -- it came out 115760 instead of
  115752 on the 64-bit host and only the harness noticed. Any future
  cast-loaded chunk wants the same assert and the same byte-image model in
  its checker.
* **A `bChunk` header of all zeroes is padding, not a terminator.**
  `bchunk_dump.py` stopped at the first one and so reported 8 chunks in
  TRACKB12.BUN's 9 MB, having given up at the alignment run at `0x7048`
  after five top-level chunks. The real counts are 472 top-level (25
  zero-pad headers among them) and 7076 recursively. `bchunk.c` had always
  skipped them, so the C and the tool disagreed silently. Fixed this session
  -- but the lesson is that the dumper is not the authority, the loader is.
* **The task list can be wrong about what a format even is.** Task 24 asked
  for an "`espEmptyLayer` spline/track-layer format". No such format exists:
  Espresso is bware's live editor RPC protocol and Caffeine is the PC end of
  it, evidenced by `EspressoServer`, the `Caffeine = %d, Espresso = %d`
  version handshake and an `EspressoFunctions` enum of `EF_LoadWorld`-style
  members. Half a day can go into looking for a file format that was never
  a file format. Check the strings and the mdebug enum before believing a
  name in `TASKS.md`.
* **A PARTIAL from `run_azahar_test.ps1` is worth re-running before it is
  worth debugging.** The harness drives Azahar with synthesised keystrokes
  and it can drop one; a dropped A at the main menu walks the rest of the
  script down the wrong branch and the verdict blames the wrong thing. The
  same build went PARTIAL then PASS with nothing changed in between.
* **The Bash tool eats one level of backslash inside a heredoc.** A patch
  script whose replacement string contains a C escape gets a real newline
  instead, the pattern stops matching, and the script cheerfully prints
  "done" having changed nothing -- or worse, having applied half its edits.
  Build the backslash from `chr(92)`, or use the file-editing tool. This cost
  two broken source files this session.

  **Apostrophes go the same way**, which is why `tools/trackroute_check.py`
  was written out with the file-editing tool rather than a heredoc. If a
  script's content has either character in it, do not pipe it through a
  shell.
* **`C3D_FVec` is declared `w, z, y, x`.** `r[i].c[j]` is element
  `(i, 3 - j)`, so a loop that fills `c[0..3]` as though they were columns
  0..3 writes every row backwards. It cost a build this session: the camera's
  view matrix came out transposed *and* mirrored, the eye never left the
  world origin, and the car drew as a black fan of triangles seen from
  inside the bodyshell. Nothing in the cross-check could see it. Use the
  named `.x/.y/.z/.w` fields, or subtract.
* **Azahar shows an "Update Available" dialog on launch** and it swallows
  every `PostMessage` keypress aimed at the emulator window. All three
  `run_azahar_*.ps1` scripts now close any visible top-level window of the
  process that is not titled "Azahar" before they start pressing keys. A run
  that does not is indistinguishable from a dead key binding: the app boots,
  the log looks healthy, and nothing responds.
* **A libctru console and citro2d cannot share a screen.**
  `consoleInit(GFX_BOTTOM, NULL)` switches that screen to RGB565 while
  citro3d goes on presenting BGR8 into the same framebuffer, and the result
  is not a flicker -- it is two half-width copies of the frame under a
  coloured dither, which looks like a render bug in your own code. There is
  no console in the port any more except on the top screen on the way out.
* **`tools/hostbuild.py` is a library, not a CLI.** Running it as a script
  exits 0 and produces nothing. Call `hostbuild.build(tmp, sources, name=...)`.
* **A survivor in a mutation run is not automatically a coverage hole.** Two
  of `bsnd_check.py`'s survived because they were equivalent mutants -- a
  quadrant boundary where both arms compute the same number, and a float that
  rounds identically in double. Work out which before adding scenarios.

* **The emulator harnesses are slow and flaky for a reason that is ours.**
  Once the boot flow's idle timer expires, `bgf_consider_start_demo_mode()`
  traces every frame, because the port's `startDemoMode` hook is a stub that
  never changes state. Two SD writes a frame slows the emulated app enough
  that most `PostMessage` key presses fall inside a single frame and are
  never scanned -- which looks exactly like a dead key binding.
  `run_azahar_scroll.ps1` presses SELECT up to 40 times to get past it. The
  fix belongs in `gameflow.c`, whose transcript `bootflow_check.py` diffs, so
  the Python reference has to move with it.

  It also makes `run_azahar_test.ps1` flaky: two PARTIALs in a row, with
  *different* failure modes, then three PASSes in a row once the machine was
  quiet -- including one at `0a58704` to rule out a regression. Re-run a
  PARTIAL once before believing it; the same failure mode twice is real.
* **A scroll offset is in the *padded* texture's space.** The original
  divides its UVs by the power-of-two allocation and only then adds the
  offset, so a citro3d caller adds it after converting pixels to UVs -- and
  T's sign flips, because `subtex_from_pixels` has already flipped the axis.
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
* **`.gitattributes` / `core.autocrlf=true`**: there is no `.gitattributes`,
  and **every blob in the repo is LF** -- git normalises on commit, so line
  endings never show up in a diff and never need fixing for git's sake. What
  differs is the *working tree*, and the previous note here had it backwards.
  Measured: `TASKS.md`, `HANDOFF.md`, `CONTINUE.md`, every `.c`/`.h` under
  `3DS Files/source/` and `tools/geometry_convert.py` are **CRLF**;
  `tools/*.py` (all the others), `tools/src/*.c`, `README.md` and everything
  under `docs/` are **LF**. Match the neighbour when adding a file, and read
  and write with an explicit newline rather than letting a tool normalise
  one -- not because git minds, but because a whole-file rewrite buries the
  change you actually made when someone reads the working tree.
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

* **The half-texel UV inset.** `RenderSingleFlailerBitmap` insets every
  corner by half a texel of the padded size before adding the scroll offset;
  the port does not. It touches all 397 textures in `FRONTB.BUN` rather than
  the two that scroll, so it wants its own verification pass.
* **`bui.c`'s eight setters are not cross-checked.** `bui_check.py` covers
  the parse path only.
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
