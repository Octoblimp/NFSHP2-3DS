# `Camera.obj` and `CameraMover.obj` -- where the view comes from

Two objects, and they divide the work cleanly. A `Camera` never decides where
it is: it is handed a matrix once a frame and pulls everything else out of it.
A `CameraMover` is what hands it that matrix, and there are eighteen kinds.

    Camera.obj        0x00153a20 .. 0x00154380     2.4 KB
    CameraMover.obj   0x00154380 .. 0x0015c4d0    32.3 KB, of which this
                                                  covers the base class and
                                                  CM_ORBIT_CAR

The port is `3DS Files/source/camera.c` and `3DS Files/source/cammover.c`,
cross-checked by `tools/camera_check.py` (1200 transcript lines, 47 mutations,
seven of them equivalent and argued for below). It sits on `emath.c`
(`docs/formats/emath.md`), and every matrix convention here is that layer's:
row-major, translation in row 3, a point is a row on the left, angles are
BAMs with 65536 to the turn.

## Where things are

| address | what |
|---------|------|
| `0x153a20` | `Camera::Camera` |
| `0x153b10` | `Camera::Camera(const Camera&)` |
| `0x153ba0` | `Camera::SetCameraMatrix` -- the whole object, really |
| `0x153cb8` | the `vsub.xyzw vf02,vf00,vf02` that negates `Position` |
| `0x2f2870` | the "JollyRancher" debug feed pointer; null on the disc |
| `0x3234b8` | `Camera::StopUpdating`; 0 on the disc |
| `0x154380` | `GetCameraMoverTypeName`, and the eighteen type names |
| `0x1544f0` | `CameraMover::CameraMover` |
| `0x1545e0` | `CameraMover::Enable` |
| `0x154658` | `CameraMover::Disable` |
| `0x154728` | `OrbitCarCameraMover::OrbitCarCameraMover` |
| `0x1549c0` | `OrbitCarCameraMover::GetTarget` |
| `0x1549e0` | `AddJoyHandlers`, nine of them |
| `0x154ac0` | where `HandlersAdded` becomes 1 |
| `0x154b78` | `OrbitCarCameraMover::Update` |
| `0x154bb0` | the `FollowChopper` branch, to `0x154c94`; not ported |
| `0x154d0c` | the `vadd.xyzw` that adds the boom offset |
| `0x154ff0` | `OrbitCarCameraMover::JoyHandler` |
| `0x2950e0` | its nine-entry jump table |
| `0x15c2a0` | the one-line setters, through `0x15c330` |
| `0x3234f8` | the orbit tweakables, through `0x323510` |
| `0x326f10` | the unnamed boom-offset quadword |
| `0x323cdc` | `RealTimeElapsed` |
| gp-31440 | `0.99`, the zoom-in multiplier |
| gp-31436 | `1.01`, the zoom-out multiplier |

`gp` is `0x328bf0` in this image.

## The record

`Camera` is 448 bytes: three 144-byte `CameraParams` and four scalars.

| offset | field | |
|--------|-------|--|
| 0 | `Matrix` | the view matrix, exactly as handed in |
| 64 | `Position` | the eye, world space |
| 80 | `Direction` | unit, the way it looks |
| 96 | `Target` | `Position + Direction * TargetDistance` |
| 112 | `TargetDistance` | |
| 116 | `FocalDistance` | |
| 120 | `DepthOfField` | |
| 124 | `NearZ` | |
| 128 | `FarZ` | |
| 132 | `FieldOfView` | a BAM, so 16384 is a right angle |
| 134 | ten bytes of padding | |

The three copies are `CurrentKey` at 0, `PreviousKey` at 144 and
`VelocityKey` at 288, the last of them per second. Then `ElapsedTime` (432),
`LastUpdateTime` (436), `CarNotToRender` (440) and `RenderDash` (444).

Two parts are never initialised and the port leaves them that way:
`CurrentKey.Pad`, and the whole of `VelocityKey.Matrix` -- `SetCameraMatrix`
differences the three vectors and the six scalars and stops.

## `SetCameraMatrix`, rule by rule

    PreviousKey = CurrentKey                 (a 144-byte bMemCpy, first thing)
    ElapsedTime = elapsed
    CurrentKey.Matrix = *m

    t = transpose(Matrix), with t.v0.w = t.v1.w = t.v2.w = 0
    Position  = -(Matrix.row3 * t)           eMulVector3, so w is forced to 1
    Direction = normalize(t.row2)            the 3D length, an xyzw scale
    Target    = Position + Direction * TargetDistance
    VelocityKey = (CurrentKey - PreviousKey) / elapsed, field by field

Three details that a re-implementation gets wrong by being sensible:

**The fourth column is not cleared, and it reaches `Position`.** Row 3 of the
transpose is the fourth *column* of the matrix, and the three stores above
clear the other three lanes but not that one. `eMulVector3` forces `w` to 1,
so whatever sat in the fourth column is added straight into the eye. The
constructor's matrix has `100.0` there (see below) and the default eye comes
out a hundred units short of where its translation row asks.

**The negate is `vsub.xyzw vf02,vf00,vf02` at `0x153cb8`, and `vf00` is VU0's
constant `(0,0,0,1)`.** So the fourth lane is `1 - w`, not `-w`. `bVector3` is
a padded sixteen-byte quadword and the pad participates: it is stored,
differenced against the previous frame's pad and divided by `elapsed` like
everything else. The port carries all four lanes for that reason. It is a
subtraction, too, not a sign flip: a lane that comes out `+0` stays `+0`,
where `-x` would make it `-0`. The default eye's x and y are `+0` on the
disc; `tools/eview_check.py` caught the port printing `-0` there, through
the static constructor, and the port now writes `0.0f - x`.

**A zero `elapsed` divides by zero.** The velocity record fills with
infinities and the next frame overwrites them. That is the disc's behaviour
and the port's.

## Half the velocity record is dead, structurally

`VelocityKey`'s six scalars -- `TargetDistance`, `FocalDistance`,
`DepthOfField`, `NearZ`, `FarZ`, `FieldOfView` -- are identically zero on the
disc, and nothing can arrange otherwise.

`SetCameraMatrix` copies `CurrentKey` over `PreviousKey` as its very first
act, and afterwards recomputes only four fields: `Matrix`, `Position`,
`Direction`, `Target`. By the time it reaches the six scalar subtractions,
each pair is the same word. Every writer of those six -- the movers, the
setters -- writes *before* the call, never between the copy and the
subtraction.

This is measured rather than argued: all 44 `key vel` records in the
cross-check transcript print `scal 0 0 0 0 0 fov 0`.

The arithmetic is ported anyway, including the u16 wrap on the field of view
(so a camera crossing zero would report the short way round) and the
truncating `cvt.w.s` after it. It is what the instructions say. Three of the
mutations below cannot be caught for exactly this reason, and they are on the
equivalent list with this as their argument.

## The constructor's matrix, and the hundred units of nothing

`Camera::Camera` builds this on the stack and calls `SetCameraMatrix` with it
**twice**, so `CurrentKey` and `PreviousKey` both end up holding it and the
second call differences a key against itself -- which is how the velocity
record starts at zero rather than at garbage:

    1     0     0     0
    0    -1     0     0
    0     0    -1   100
    0     0  1200     1

The `100.0` is in the fourth column, where a transform has no business
putting anything, and by the rule above it lands in `Position`: the default
eye is `(0, 0, 1100)`, not the `(0, 0, 1200)` the translation row asks for.
It is overwritten on the first real frame. The port keeps it.

`FieldOfView` starts at 14075 BAMs (about 77 degrees), `TargetDistance` at
10, `NearZ` at 0.5, `FarZ` at 5000, and `LastUpdateTime` at `0x80000000`.

## The base mover

44 bytes, vtable at offset 40, and `Update` is the only virtual anything
calls. The first 8 bytes are the mover's link on its view's list. The
constructor (`0x1544f0`) takes a view id. With -1 it leaves the mover
detached and disabled, with `pView` (20) and `pCamera` (24) both 0.
Otherwise it takes `v = eGetView(id)`, stores it in `pView`, takes
`v->pCamera`, forces that camera's far plane to 5000, copies the camera's
two render flags, stores the camera in `pCamera` and enables. `Enable`
links the mover onto the head of `pView`'s list (`AttachCameraMover`), and
`Disable` unlinks it (`UnattachCameraMover`). Both of those work the view
mode out again; see `eview.md`.

`Enable` and `Disable` are not symmetric, in three ways:

* Both early-out when the flag is already where they would put it, which is
  why a mover that never attached (null `pCamera`) can be disabled safely.
* `Enable` skips the two render flags while `StopUpdating` is set but still
  forces `NearZ` to 0.5. `Disable` does not test `StopUpdating` at all.
* `Disable` copies the camera's two render flags back *into the mover* before
  letting go. So a disable/enable pair round-trips whatever some other mover
  left on the camera in between, rather than restoring what this one first
  saw.

The far plane is set in the constructor and the near plane in `Enable`, which
is an odd split but is where the disc puts them.

## `CM_ORBIT_CAR`

208 bytes. A boom arm: the eye sits `Radius` from the car at heading `AngleH`
and elevation `AngleV`, in the car's own space, and the two angles drift
toward their desired values at a bounded acceleration. It is what the car
select screen and the replay orbit use.

What the constructor ships:

| field | value | |
|-------|-------|--|
| `Radius`, `DesiredRadius` | 5.0 | |
| `MinRadius`, `MaxRadius` | 1.0, 1000.0 | |
| `AngleH` | 26000 | 143 degrees |
| `AngleV`, `DesiredAngleV` | `0xf230` = 61992 | 340.5 degrees |
| `MinAngleV`, `MaxAngleV` | `0xc738` = 51000, `0xf8f4` = 63732 | 280 .. 350 degrees |
| `RadiusMultiplier` | 1.0 | |
| `MaxRadiusVel` | 0.4 | stored, never read |
| `MaxRotationAccel` | 24 | BAMs per frame per frame |
| `FEMode`, `ApproachAngleV` | 0 | |

`Update` at `0x154b78`, in order:

1. `IsGameFlowPaused()` -- returns immediately if so. The port leaves this
   test to the caller, because `gameflow.c` owns the answer.
2. `T(-GeometryPosition)`, with `LookHeight` (0.0) off z, then multiplied by
   the transpose of the car's `BodyMatrix`. With no car: identity with
   `-TargetHeight` (0.3) in z. Two tweakables for the same idea, and the car
   path uses the one that is zero.
3. Add `OrbitBoomOffset` to the translation row. `vadd.xyzw` at `0x154d0c`,
   so the fourth lane is in it too.
4. `if (RadiusMultiplier != 1.0f) DesiredRadius *= RadiusMultiplier` -- an
   exact compare against 1.0, which is why the zoom buttons write exactly
   `1.0f` on release.
5. `Radius = DesiredRadius`, then both are clamped to `[MinRadius, MaxRadius]`
   by the same two compares in the same order.
6. Both rotation speeds approach their desired values by at most
   `MaxRotationAccel`. The original writes this as a step followed by an
   unsigned compare and a `movz`, so a gap of exactly `accel` lands on the
   target rather than overshooting.
7. `AngleV += VRotationSpeed`, then the optional `ApproachAngleV` walk: 80
   BAMs a frame, snapping when the gap is under 81. The compare is unsigned
   on the raw u16s, so it does *not* take the short way round -- an `AngleV`
   of 100 approaching 65000 walks down through zero. `ApproachAngleV` is 0
   on the disc.
8. Clamp `AngleV` to `[MinAngleV, MaxAngleV]` -- max first, then min.
9. `AngleH += HRotationSpeed`.
10. `eRotateZ(angleH)`, `eRotateY(angleV)`, `eTranslate(radius, 0, 0)`.
11. `eRotateX(16384)` then `eRotateY(0xc000)`: the change of basis from the
    engine's x-forward, z-up world into the renderer's frame.
12. Unless `StopUpdating`: `FieldOfView = TweakOrbitFOV`,
    `TargetDistance = FocalDistance = Radius`, `DepthOfField = 8.0`.
13. `SetCameraMatrix(m, RealTimeElapsed)`.

Three things in that list are worth pulling out.

**The rotation speeds are BAMs per *frame*, not per second.** Nothing in
`Update` is time-scaled except the `elapsed` handed to `SetCameraMatrix`. The
orbit therefore spins faster on a machine that draws more frames. That is the
disc's behaviour on a fixed console; whether the 3DS should keep it is task
28's question, and the zoom has the same shape -- 1% a frame compounds about
fourfold in a second at 139 FPS, which is what the emulator runs this build
at.

**`TweakOrbitFOV` is not behind `UseTweakables`.** It lands on the camera
every single frame, so the constructor's `InGameFOV` of 13020 (about 71
degrees) is overwritten before anything can use it. The view is 8000 BAMs,
about 44 degrees. A debug tweakable that shipped switched on.

**`UseTweakables` swaps only the three live values** -- angle h, angle v,
radius -- at step 10, after all the clamping, so the clamps still run and
still write the fields; they just do not reach the matrix.

### The joystick handler

`JoyHandler` at `0x154ff0` is a nine-way jump on `event - 46`, through the
table at `0x2950e0`. The nine are the **debug camera** events, not the car
select ones: `JOY_EVENT_CARSEL_ORBIT_*` are 35..43 and this mover never sees
them, because the car select screen drives it through the setters instead.

| event | | what it does while held |
|-------|--|------------------------|
| 46 | `DEBUG_CAMERA_ROTATE_RIGHT` | `DesiredHRotationSpeed = -speed` |
| 47 | `DEBUG_CAMERA_ROTATE_LEFT` | `DesiredHRotationSpeed = +speed` |
| 48 | `DEBUG_CAMERA_ROTATE_UP` | `DesiredVRotationSpeed = -speed` |
| 49 | `DEBUG_CAMERA_ROTATE_DOWN` | `DesiredVRotationSpeed = +speed` |
| 50 | `DEBUG_CAMERA_MOVE_CLOSER` | `RadiusMultiplier = 0.99` |
| 51 | `DEBUG_CAMERA_MOVE_FARTHER` | `RadiusMultiplier = 1.01` |
| 52 | `DEBUG_CAMERA_NEXT_CAR` | `CarToFollow = *(CarToFollow + 0)` |
| 53 | `DEBUG_CAMERA_PREV_CAR` | `CarToFollow = *(CarToFollow + 4)` |
| 54 | `DEBUG_CAMERA_FOLLOW_CHOPPER` | toggles `FollowChopper` |

`speed` is 500 BAMs, or 300 when `FEMode` is set. Every held event writes its
rest value on release -- 0 for a speed, *exactly* `1.0f` for the multiplier,
which is what step 4 above tests for. 52 and 53 do nothing while `FEMode` is
set.

Note the signs: "up" asks for a negative vertical speed, so holding up walks
`AngleV` toward `MaxAngleV`, and `AngleV` rising *lowers* the boom. The
geometry viewer's pad is wired the same way for that reason.

## Divergences from the disc

Each of these is in the source as a comment at the point it happens.

* **No joystick event bus**, so `AddJoyHandlers` registers nothing and
  `HandlersAdded` stays 0 -- which is the honest answer to "have the handlers
  been added". The table above is what the 3DS input layer calls directly.
* **`FollowChopper` is not ported.** `0x154bb0..0x154c94` swaps the followed
  car for the police chopper and gates on a mode word at `Player+584`. There
  is no `Chopper` until task 26, so the port always takes the car path.
* **`TM` is cleared by the port's constructor**, where the disc leaves it as
  whatever was in the allocation. Nothing reads it; clearing it makes the
  state printable.
* **The "JollyRancher" debug feed** at the top of `SetCameraMatrix` is not
  ported: if the pointer at `0x2f2870` is non-null the matrix comes from a
  network debug server with its translation row scaled by 0.01. It is null
  unless a debug server answered at boot.
* **`IsGameFlowPaused` and `RealTimeElapsed`** are the caller's business in
  the port: `orbit_update` takes `elapsed` as an argument so the checker can
  drive it.

## Cross-check

`tools/camera_check.py` drives `tools/src/camera_test.c` and an independent
Python model -- the model written from the listings, not from the C -- through
seven scenarios and diffs the transcripts line by line.

    python tools/camera_check.py            # 7 scenarios, 1200 lines, 0 differ
    python tools/camera_check.py --mutate   # 47 mutations, 40 caught,
                                            # 7 equivalent, 0 unexplained

The scenarios are: the constructor and the copy constructor; a hand-built
matrix with a known decomposition; a rotating car through the boom; the zoom
multiplier held and released; the angle clamps, including an inverted
`MinAngleV`/`MaxAngleV` window; the acceleration limiter at gaps of
`accel - 1`, `accel` and `accel + 1`; and enable/disable, which covers
constructed, disabled, disabled twice, re-enabled, enabled twice, and both
under `StopUpdating`.

Seven mutations survive and each one has an argument for why it must:

| mutation | why it cannot be caught |
|----------|------------------------|
| `fov-delta-signed`, `fov-velocity-rounds`, `fov-delta-reversed` | the six scalar velocities are structurally zero; see above. All 44 velocity records measure `fov 0`. |
| `approach-inclusive` (`<` to `<=`) | at a gap of exactly `accel` the step lands exactly on `want`, so both arms agree. The scenario walks `accel-1`, `accel`, `accel+1`. |
| `approach-threshold-80` (`< 81` to `< 80`) | the same argument one layer up: `1000 + 80 == 1080` whether it is snapped to or stepped onto. |
| `radius-clamped-before-copy` | `Radius` is a copy of `DesiredRadius` put through the same two compares in the same order, so clamping either one first gives the same pair. |
| `target-distance-desired` | and for the same reason the two are equal by the time `Update` reads them. The zoom transcript prints both every frame and they never disagree. |

An equivalent mutant left in a mutation list is a test that can never pass, so
the list names them explicitly and the runner reports "0 unexplained" rather
than "7 survived".

## On the emulator

A cross-check proves two implementations of the arithmetic agree. It says
nothing about whether the matrix that comes out points the right way, so the
geometry viewer (`3DS Files/source/geoview.c`, main.c's third SELECT mode)
was rewired to drive the real `Camera` through a real `CM_ORBIT_CAR` mover
instead of its own spherical orbit, and `tools/run_azahar_geo.ps1` now
captures the boom doing each of its jobs.

That was worth doing on the first run, which drew a black fan of triangles
radiating from a point: the eye was at the world origin, inside the bodyshell.
`C3D_FVec` is declared `w, z, y, x` -- in that order -- so `r[i].c[j]` is
element `(i, 3 - j)`, and the loop that transposed the engine matrix into it
was writing every row backwards. A transposed-and-mirrored view matrix still
looks plausible in code review.

With that fixed, and with the engine's view basis (x right, y down, z
forward) turned into citro3d's by negating rows 1 and 2:

| shot | what it shows |
|------|---------------|
| `cam-still` | a 4DR_SEDAN, right way up, framed on its AABB centre |
| `cam-zoom-in` / `cam-zoom-settled` | a held zoom, then 1.5 s after release. Mean absolute difference 0.011/255 -- the camera stopped dead, so `RadiusMultiplier` went back to exactly 1.0. Two frames of the idle spin measure 1.009 and a zoom step measures 2.009, so the test has the power to fail. |
| `cam-zoom-out` | the other multiplier, and the radius clamp holding |
| `cam-orbit-start` / `cam-orbit-held` | 150 ms and 1.4 s into a held pad. The first has barely moved: the acceleration limiter is in the loop. |
| `cam-elev-clamped` | 1.8 s of held elevation stops at `MaxAngleV` instead of tumbling over the top |
| `cam-reset` | B, back to the constructor's angles |

    powershell -File tools/run_azahar_geo.ps1 -Cars 2 -Solids 3

The zoom hold in that script is deliberately short. Azahar runs this build at
about 139 FPS, and 1% a frame is a factor of four in a second -- the eye ends
up inside the car. That is the mover being per-frame, not the harness being
wrong, and it is the clearest demonstration of the frame-rate coupling that
task 28 has to decide about.

One more thing that script had to learn: Azahar's "Update Available" dialog
takes the foreground on launch and swallows every posted keypress, so a run
that ignores it presses SELECT eight times into a dialog and then reports
that the geometry viewer was never reached. It now closes any visible
top-level window of the emulator process that is not titled "Azahar" before
each attempt. `run_azahar_test.ps1` and `run_azahar_scroll.ps1` had the same
hole and got the same fix.
