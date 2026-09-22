# CONTINUE

Where the next session picks up. Written at the end of Session 20
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

Twenty-three cross-checkers pass, plus the table generators:

```bash
python tools/bvector_check.py && python tools/bmath_check.py && python tools/banim_check.py && python tools/bscreens_check.py && python tools/bootflow_check.py && python tools/bslotpool_check.py && python tools/geometry_check.py && python tools/texsrc_check.py && python tools/bui_check.py extracted/FRONTEND/FRONTB.BUN && python tools/sndbank_check.py out/SOUND && python tools/bsnd_check.py out/SOUND && python tools/emath_check.py && python tools/camera_check.py && python tools/trackroute_check.py && python tools/carstate_check.py && python tools/engine_check.py && python tools/cartypeinfo_check.py && python tools/cardriver_check.py && python tools/steering_check.py && python tools/rigidbody_check.py && python tools/suspension_check.py && python tools/wheel_check.py && python tools/drivetrain_check.py && python tools/gen_bmath_tables.py --check && python tools/gen_bsnd_tables.py --check
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
engine_check        8 scenarios,   413 lines, 0 differ   (54 caught, 2 equivalent)
cartypeinfo_check   4 scenarios,   177 lines, 0 differ   (41/41 mutations caught)
cardriver_check     5 scenarios,   118 lines, 0 differ   (48/48 mutations caught)
steering_check      5 scenarios,   873 lines, 0 differ   (43 caught, 1 equivalent)
rigidbody_check    10 scenarios,   935 lines, 0 differ   (75 caught, 2 equivalent)
suspension_check   10 scenarios,  1108 lines, 0 differ   (66 caught, 2 equivalent)
wheel_check        19 scenarios, 10693 lines, 0 differ   (144 caught, 10 equivalent)
drivetrain_check   18 scenarios,   492 lines, 0 differ   (173 caught, 3 equivalent)
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

1. **Task 25**, the car simulation -- part done, and **much bigger than
   the task list said**. Nine slices are closed: `CarState`, `Engine` +
   `Table`, `CarTypeInfo`, `CarDriver` + `DriveTarget`'s layout,
   `Steering` + `TwoWheelAckermanSteering`, `RigidBody`, `Suspension`,
   `Wheel` and `DriveTrain`, each with a checker and a doc under
   `docs/formats/car-*.md` (`RigidBody`'s is `rigid-body.md`).

   The old "178 functions, 16680 bytes" note was wrong by an order of
   magnitude -- it matched a narrow symbol pattern and missed most
   methods. Remeasured by demangling every symbol to its owning class,
   **~48.5 KB across ~168 functions** is still to go:

   ```
   Car 80 funcs 22876 B   DriveTarget (methods) 28 / 8636
   PhysicsCar 16 / 8496   Mellovator 31 / 5420
   MellowMover 13 / 3096
   ```

   At this repo's verification standard that is several sessions, not
   one. **`RigidBody` and `DriveTarget` are prerequisites the task list
   never named** -- `Suspension`, `PhysicsCar` and `Car` all need
   `RigidBody`. Next in order: `DriveTarget`'s 28 methods, `PhysicsCar`,
   `Car`, with `Mellovator` and `MellowMover` last.

   **`DriveTarget`'s methods are the next slice**, and unlike `DriveTrain`
   this one has an object of its own: `.text 0x002086f8`, `0x24d0` long,
   `DriveTarget.obj`. The 528-byte record is already spelled out and
   ARM-compiled in `3DS Files/source/drivetarget.h` -- `CarDriver` embeds
   it at offset 0 -- so the layout is done and what is left is code.

   Three things to know before starting it:

   * **The object is not all DriveTarget.** `OBB` has seven methods in
     it (`OBB::OBB`, `~OBB`, `operator=`, `Render`, `DoNotRender`,
     `DoSnapshot`, `Print`) and the free function `bDoublesBack`
     (`0x00208fa0`) sits in the middle of the run. That is why the
     object is 9424 bytes where the DriveTarget tally is 8636.
   * **The copy constructor is not in it either.**
     `DriveTarget::DriveTarget(DriveTarget const &)` is emitted at
     `0x001da210`, inside `CarCollisionDetect.obj` (`.text 0x001d8770`,
     `0x1bf8` long). The tally of 28 reconciles exactly, and it is worth
     knowing which 28: twenty-six methods in `DriveTarget.obj` (8304
     bytes with the thunk), that copy constructor (332), and the
     `_GLOBAL_$I$__11DriveTarget` static-init thunk at `0x0020ab48`
     (16) -- 8636 between them. So there are **twenty-six functions to
     port**, not twenty-eight.
   * **`Car` is NOT a prerequisite -- this was checked, not assumed.**
     Thirteen of the twenty-six take no `Car *` at all. The other
     thirteen do, and **every one of them reaches `Car` only through
     the `CarState` embedded at byte 64**, which is ported. `Car` is
     2016 bytes with `State:/0263,512,8192` in its `.mdebug` entry --
     bit 512, so byte 64, 1024 bytes -- and the only Car offsets any of
     these methods touch are 64 (passed on as `CarState *`), 96
     (`State.Position`) and 112 (`State.Velocity`). A `Car` stand-in
     whose only live member is a `CarState` is enough for the whole
     class. Two of the three free functions they call are the same
     story: `IsPointAheadOfCar` (`0x001c0e30`) reads only 96 and 112,
     and `CalculateLookAheadDistance` (`0x001c0c20`) is
     `max(State.VelocityMagnitude * 2.0f, 20.0f)` and nothing else.
     `GetMaxLateralAcceleration(Car *)` (`0x00209f30`) does not read
     the car at all -- it is `lui at,0x41f0; mtc1 at,$f0`, a constant
     30.0f in four instructions.

   What is actually blocked, after reading every call site:

   ```
   DoSnapshot      0x00208830  ReplaySnapshot, as ever
   Dump            0x002095f8  Car::WorldToCar -- a tail-jump to
                               CarState::WorldToCar(bVector2*,bVector2*)
                               at 0x001b6ab0, which carstate.c does not
                               have yet. Debug output; port it last.
   AddPointToTarget(bVector3*, DrivingLocation*, bool, Car*)
                   0x00208e60  DrivingLocation::IsClear, which is
                               `lw v0,0(a0); sltiu v0,v0,1` -- one word
                               at offset 0. A two-field stand-in covers
                               it; the class itself is task 26's.
   FillWithCurrentAcceleration
                   0x00209fb0  StraightLinePredict (0x001c3338), which
                               is itself only CarState + Clear +
                               AddPointToTarget, so it can come along.
   ```

   Constants already resolved, so they do not have to be found again
   (`_gp` is `0x00328bf0`):

   ```
   0x00321fa8  Clear's speed epsilon            0.001
   0x00321fc0  CalculateTime's speed epsilon    0.001
   0x00321fc4  CalculateTime's "no time" value  9999999.0
   0x00323a50  look-ahead scale                 2.0
   0x00323a54  look-ahead floor                 20.0
   ```

   And two shapes worth knowing before writing the model:
   `GetAngle` clamps its index up to `NumPoints - 2` but never back up
   to 0, so with `NumPoints` 0 or 1 it indexes `Points[-2]` and
   `Points[-1]` -- a real out-of-bounds read in the shipped game, the
   same flavour as `Table::GetValue`'s. And `SetPoint`'s `bVector2`
   overload builds a stack `bVector3`, sets x, y and z and leaves w
   alone, then the `bVector3` overload copies all sixteen bytes with
   `lqc2`/`sqc2` -- so `Points[i].w` takes whatever was on the stack.

   **`Wheel`'s two seams are wired but nothing installs them.**
   `wheel_install_seams()` points `gWheelFindDrivingSurfaceFn` and
   `gWheelExchangeZForcesFn` at the real methods, and no code in
   `3DS Files/source/` calls it, so they are still `NULL` on hardware.
   That is correct today -- nothing constructs a `Suspension` or a
   `Wheel` yet -- but **whichever slice first builds a car owes that
   call**, before that car's first `ResolveForces`, or every corner
   reports airborne. The seams are a port artifact: at `0x0019bdd4` and
   `0x0019c104` the PS2 build makes two ordinary `jal`s.

   The HUD split is settled, below.
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

  There is a third answer besides "hole" and "equivalent": **the mutation
  itself was badly written.** `(uint16_t)(int16_t)x` on a `uint16_t` field
  is a no-op by C's own rules and could never be caught; a mutation that
  fails to compile because it used `memset` without `<string.h>` was
  rejected by the compiler rather than by the transcript. Both were
  rewritten into the transcription errors they were standing in for.

  Two more shapes of the same mistake turned up in `Wheel`. A mutation
  whose body writes only to **its own parameters** (`lo = hi = value;` in
  an empty function) is three dead stores and cannot be caught by
  anything. And a mutation that writes **the value the target already
  held** -- `gMaxStaticSlip = value` where the call passed 0.5 and
  `gMaxStaticSlip` is 0.5 -- leaves no trace either; the call site had to
  pass 0.375 before the mutation meant anything.
* **A comment claiming a case is covered is not coverage, and it is worse
  than no comment.** `wheel_check.py` and `wheel_test.c` both said vx 0.4
  with a spin of 1.25 put the slip at exactly zero and so reached
  `GuessGroundForce`'s zero-magnitude early-out. `1.25 * 0.32f` is
  0.399999976, so the slip was -2.98e-08 and the guard was never reached
  at all. The mutation that deletes it survived a full pass, and the
  comment was read twice as the reason it could not be a hole. Where a
  case depends on an exact float, compute it rather than asserting it --
  `37.5 * 0.32f` is 12 with nothing left over, and that is the pair that
  works.
* **A mutation can survive because the fixture agrees with itself.**
  Three of `DriveTrain`'s eighteen survivors were that shape: a swap of
  `gShiftUpDetune` for `gShiftDownDetune` where the image ships both at
  0.95, a dropped store of a pedal the constructor had already left at
  the value the store writes, and a clamp to `FIRST_GEAR` of a
  `DesiredGear` the constructor had already set to `FIRST_GEAR`. Nothing
  is wrong with the mutation or with the code -- the input cannot tell
  them apart. Drive the fixture from a value the object would have to go
  out of its way to produce (detunes of 0.8 and 0.6, a pedal at 0.25, a
  gear of fifth) and all three die.
* **A `<` against `<=` needs the two sides equal bit for bit, and
  picking a likely number is not good enough.** `DriveTrain`'s inclusive
  mutants are killed by writing the shift point back as the very RPM the
  object computes, from the same product on both sides, so the compare
  is against itself. Where the fixture cannot be fed back like that the
  value has to be searched for: `94.2477036f` is the only float whose
  product with the rads-to-RPM constant is exactly 900.0f, and both
  neighbours land an ulp away.
* **A mutation nothing reaches is not covered by the scenario next to
  it.** Two of `DriveTrain`'s survivors were in the crossover search,
  which only does work when the torque curve falls hard past its peak --
  every fixture engine crossed over on the first probe or not at all, so
  the search's own branches never ran. Two extra engines, a steep curve
  and an all-zero one for the single case where two sides can be equal,
  killed both. Check that the *shape* of the fixture data exercises the
  loop before concluding the loop is equivalent.
* **An explicit alignment pad cannot be checked by deleting it.** A
  `uint8_t _pad[2]` in front of a pointer is reinstated by the ABI the
  moment it is removed: every following offset, and `sizeof`, come out
  unchanged and the layout assert passes. What pins the field after it is
  the `offsetof` in the assert. Do not read "the pad mutation survived" as
  a coverage hole.
* **A guard can be protecting the read rather than the number.**
  `Table::GetValue` returns `pTable[i]` outright when `i == last`. Delete
  that and the interpolation computes
  `pTable[last] + (pTable[last + 1] - pTable[last]) * 0.0`, because the
  weight is exactly zero there -- the same number, off the back of a load
  one element past the end of the array. A transcript cannot see it and a
  sanitiser build would.
* **An array's extent is part of the layout claim, and offsets do not pin
  it.** Shrink an array, pad behind it, and every following offset *and*
  the total size are unchanged -- the static assert passes. Nine
  CarTypeInfo mutations and one Steering mutation exploited exactly that.
  Print `sizeof` of each array, the element stride, and a width and
  signedness probe per field.
* **A layout is not checked until the ARM build compiles it.** The host
  harness cross-checks *arithmetic*; it is not the target and its structs
  are not the target's. `wheel.h`'s assert was wrapped in
  `#if __SIZEOF_POINTER__ == 4`, so neither toolchain ever compiled it, and
  when `tools/build_cia.ps1` finally did it failed. This port's `bVector4`
  is four-byte aligned where the PS2's was a sixteen-byte quadword, so a
  four-byte gap the PS2 record has before `Wheel::WorldGroundForce` did not
  appear and the handheld's record came out 396 bytes instead of 400. On the
  64-bit host the pointer widening cancelled the gap exactly, so the model
  and the harness agreed on the wrong record. Never guard a layout assert
  with a host test that makes it vanish on the host, and run the ARM build
  before calling a slice with a record in it done.
* **The vtable pointer is at the END of the object in this image.** Old
  g++ ABI. `CarState` has none, `CarDriver`'s is at 556, `Steering`'s at
  8, and every class still to come in task 25 is the same. Looking for it
  at offset 0 will shift every field by four.

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
