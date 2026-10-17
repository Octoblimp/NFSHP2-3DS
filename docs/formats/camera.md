# `Camera.obj` and `CameraMover.obj` -- where the view comes from

Two objects, and they divide the work cleanly. A `Camera` never decides where
it is: it is handed a matrix once a frame and pulls everything else out of it.
A `CameraMover` is what hands it that matrix, and there are eighteen kinds.

    Camera.obj        0x00153a20 .. 0x00154380     2.4 KB
    CameraMover.obj   0x00154380 .. 0x0015c4d0    32.3 KB, of which this
                                                  covers the base class,
                                                  CM_ORBIT_CAR and CM_DRIVE;
                                                  see "Retail's orbit mover"
                                                  and "The drive camera"
    the shake         0x00152860 .. 0x001539f4    the camera half; see
                                                  "The camera shake"

The port is `3DS Files/source/camera.c` and `3DS Files/source/cammover.c`,
cross-checked by `tools/camera_check.py` (an independent model, three of
its mutations equivalent and argued for below) and, for what retail
changed, by `tools/cambase_check.py`, which runs retail's own code (see
"Retail" below). `drivecam.c` has the drive camera, cross-checked by
`tools/drivecam_check.py` on retail's image, and `orbitcam.c` the orbit
camera, cross-checked by `tools/orbit_check.py` on retail's image (see
"Retail's orbit mover"). Most addresses here are the demo's; "Retail",
the orbit mover's retail pass, the shake and the drive camera have
retail's. It sits on
`emath.c`
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
| `0x154bb0` | the `FollowChopper` branch, to `0x154c94` |
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

`Camera` is 448 bytes on the demo disc: three 144-byte `CameraParams` and
four scalars. Retail's is 464, with a fifth scalar; see "Retail".

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
10, `NearZ` at 0.5, `FarZ` at 5000 (10000 on retail), and `LastUpdateTime`
at `0x80000000`.

## The base mover

44 bytes, vtable at offset 40. On the demo disc `Update` is the only
virtual anything calls; retail's vtable has fifteen slots (see "Retail").
The first 8 bytes are the mover's link on its view's list. The
constructor (`0x1544f0`) takes a view id. With -1 it leaves the mover
detached and disabled, with `pView` (20) and `pCamera` (24) both 0.
Otherwise it takes `v = eGetView(id)`, stores it in `pView`, takes
`v->pCamera`, forces that camera's far plane to 5000 (10000 on retail),
copies the camera's
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

This section is the demo's mover, with the demo's addresses. The port
follows retail's now (`orbitcam.c`); "Retail's orbit mover", under
"Retail" below, has what changed. In short: `Update` makes the pause test
itself, follows the chopper, and no longer clamps `AngleV`.

What the constructor ships:

| field | value | |
|-------|-------|--|
| `Radius`, `DesiredRadius` | 5.0 | |
| `MinRadius`, `MaxRadius` | 1.0, 1000.0 | |
| `AngleH` | 26000 | 143 degrees |
| `AngleV`, `DesiredAngleV` | `0xf230` = 62000 | 340.6 degrees |
| `MinAngleV`, `MaxAngleV` | `0xc738` = 51000, `0xf8f4` = 63732 | 280 .. 350 degrees |
| `RadiusMultiplier` | 1.0 | |
| `MaxRadiusVel` | 0.4 | stored, never read |
| `MaxRotationAccel` | 24 | BAMs per frame per frame |
| `FEMode`, `ApproachAngleV` | 0 | |

`Update` at `0x154b78`, in order:

1. `IsGameFlowPaused()` -- returns immediately if so. The demo's port left
   this test to the caller; the retail port makes it.
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
   Retail has no such step.
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
fourfold in a second at 139 FPS, which is what the emulator ran this build at
while its frame limit was off, and 1.8-fold at 60.

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

## Retail

The port follows retail's `Camera`, its `CameraMover` base and its orbit
mover. Retail has no symbols, so the names of what is new are the port's.
`gp` is `0x003358f0` there.

| address | what |
|---------|------|
| `0x00156be0` | `Camera::Camera` |
| `0x00156cd0` | `Camera::Camera(const Camera&)` |
| `0x00156d68` | `Camera::SetCameraMatrix` |
| `0x00156ed8` | the `ClearVelocity` test |
| `0x002fa860` | the JollyRancher feed pointer; null on the disc |
| gp-21808 | `Camera::StopUpdating` (`0x003303c0`) |
| gp-31300, gp-31292 | `10000.0`, the far plane of the two constructors |
| `0x00157578` | `GetCameraMoverTypeName` |
| `0x001576e8` | `CameraMover::CameraMover` |
| `0x00157780` | `CameraMover::~CameraMover` |
| `0x001577d8`, `0x00157850` | `Enable`, `Disable` |
| `0x002b1e50` | `CameraMover`'s vtable |
| `0x0015ef28` | `UpdateCameraMovers` |
| `0x0015eee0` | `RenderCameraMovers` |
| `0x0011b300` | `eMulVector`, under `Position` |
| `0x002dc400` | its `(0, 0, 0, 1)`, written by the static constructor at `0x0011bf70` |

**The record is 464 bytes.** `ClearVelocity` is new at 432, and the four
scalars after it moved up by four: `ElapsedTime` 436, `LastUpdateTime` 440,
`CarNotToRender` 444, `RenderDash` 448. Both constructors clear it. The
only writers of 1 are the destructors of `CM_TRACK_CAR` (`0x001594d4`) and
`CM_TRACK_FLY` (`0x00159e2c`).

**`ClearVelocity`.** After `Target` and before the differences,
`SetCameraMatrix` tests it. When it is set it is cleared and `CurrentKey` is
copied over `PreviousKey`, so that frame's velocity is zero. The camera a
tracking mover leaves behind jumps, and the jump is not a speed. A frozen
camera (`StopUpdating`) keeps the flag, because the function has already
returned.

**The far plane is 10000** in both constructors (gp-31300 for the camera,
gp-31292 for the mover). The demo's was 5000.

**The type names end in `"CM_UNKNOWN(?)"`** (`0x002b1620`) for a type out
of range. The demo's fell through to `"CM_NONE"`.

**The vtable has fifteen slots**, each eight bytes (a this-delta, then the
function) after an eight-byte head:

| offset | slot | the base's |
|--------|------|-----------|
| +12 | the destructor | `0x00157780` |
| +20 | `Update` | nothing |
| +28 | `Render(eView *)` | nothing |
| +36, +44 | `AddJoyHandlers`, `RemoveJoyHandlers` | nothing |
| +52 | `GetCameraInfo` | 0 |
| +60 | `GetPOV(int)` | 0 |
| +68 | `IsExteriorView` | 1 |
| +76 | `IsLookingBack` | 0 |
| +84 | `GetWallGap` | 0.7 (gp-31288) |
| +92 | `ResetState` | nothing |
| +100, +108 | `Enable`, `Disable` | the two above |
| +116 | `GetCarToFollow` | 0 |
| +124 | `GetTarget` | `&pCamera->CurrentKey.Target` |

The destructor puts the base's vtable back, calls `Disable` directly (not
through the vtable), and ends in `bTNode`'s destructor, which only frees.

**The two loops take the first mover on each view only.**
`UpdateCameraMovers` walks the ten views and calls `Update` on the head of
each list; `RenderCameraMovers(view)` calls `Render` on that view's head.
The tail of `UpdateCameraMovers` asks once whether a debug server exists
(`bFunkDoesServerExist`, cached in gp-21764/gp-21768). The shipped game has
none, so the JollyRancher branch never runs. It then hands view 1's eye to
`CameraMoverAddNearbyDebugTopology` (`0x00203e18`), which is empty. The port
keeps neither.

**`eMulVector` adds the vector's x, y and z into a `(0, 0, 0, 1)` kept at
`0x002dc400`** (`vadd.xyz`). So `w` is 1, and a `-0` lane comes in as `+0`.
A static constructor writes that quadword. Retail's image in `mipsemu` runs
no static constructors, so `cambase_check` runs that one (`0x0011bf70`)
itself. Without it `w` is 0, the fourth column never reaches `Position`,
and the negate's fourth lane comes out 1.

### Cross-checked on retail's image

`tools/cambase_check.py` runs retail's own code in `mipsemu`: the
constructors, `SetCameraMatrix`, the mover's constructor and destructor,
`Enable` and `Disable`, every slot of the base vtable, the accessors, the
type names and both loops, over retail's own `eView` table. The only stub
is `bFunkDoesServerExist`, which answers 0. `tools/src/cambase_test.c` runs
the port over the same script. Cameras and movers start from a `0xa5` fill,
so a field one side writes and the other leaves shows. A second vtable,
the base's with `Update`, `Render`, `Enable` and `Disable` replaced by
recorders, shows which mover each loop reached, and whether a destructor
went through the vtable.

    python tools/cambase_check.py            # 7 scenarios, 5624 lines, 0 differ
    python tools/cambase_check.py --mutate   # 61 mutations, 61 caught

`camera_check` keeps its independent model of the same code, updated to
retail's. What it adds is the camera's six setters, which are inline in
the image and have no address to run. It has no mutation that sets
`ClearVelocity` in the constructor: the constructor's two
`SetCameraMatrix` calls clear the flag whatever it held, so only a camera
built while frozen can show it, and `cambase_check` builds one. Its model
of the demo's orbit mover is retired; `orbit_check` runs retail's.

### Retail's orbit mover

`orbitcam.c` is retail's `OrbitCarCameraMover`, which the demo section
above describes as the demo had it. The record is still 208 bytes.

| address | what |
|---------|------|
| `0x00157e48` | `OrbitCarCameraMover::OrbitCarCameraMover(ViewID, Car *, port)` |
| `0x00158080` | the destructor |
| `0x001580e0` | `GetTarget` |
| `0x0015fb18` | `GetCarToFollow` |
| `0x00158100`, `0x001581f8` | `AddJoyHandlers`, `RemoveJoyHandlers` |
| `0x00158298` | `Update` |
| `0x001586c8` | `JoyHandler`; its jump table is `0x002b1630` |
| `0x002b1c50` | the vtable |
| `0x00154140`, `0x001541e8` | `AddJoyHandler`, `RemoveJoyHandler`, the joystick layer's |
| `0x001680b8` | `IsGameFlowPaused` (`race.c`) |
| gp-21720 .. gp-21696 | the nine statics: `UseTweakables`, `TweakRadius`, `TweakAngleH`, `TweakAngleV`, `LookHeight`, `InGameFOV`, `FrontEndFOV`, `TargetHeight`, `TweakOrbitFOV` |
| `0x00334190` | the boom-offset quadword |
| gp-31272 | `0.4`, `MaxRadiusVel` |
| gp-31260, gp-31256 | `0.99` and `1.01`, the zoom multipliers |
| gp-19596 | `RealTimeElapsed`, which the vtable's `Update` passes on |

What changed from the demo:

- **It follows a `Car`.** `GetTarget` is the car's `GeometryPosition`, or
  the camera's `Target` with no car. `GetCarToFollow` hands back the car.
  The next and previous car keys walk the car's own links at 0 and 4.
- **`Update` makes the pause test itself**, through `IsGameFlowPaused`,
  which reads the race coordinator's state. With no coordinator nothing is
  paused.
- **`FollowChopper` is live.** When it is set and the world has a
  `Helicopter` whose `Plan` is below 3 (compared unsigned) or exactly 4,
  the chopper is followed instead of the car. Its `CurrentPos` is the
  point, and its `Matrix` is the body with row 3's x, y and z zeroed but
  its w kept. The chopper path adds **no** boom offset; the car path adds
  it with `vadd.xyzw`, all four lanes. Any other plan, or no helicopter,
  falls back to the car. Event 54 toggles the flag.
- **No `AngleV` clamp.** `AngleV += VRotationSpeed` and the approach walk
  are all there is, so the angle wraps. The constructor still sets
  `MinAngleV` and `MaxAngleV`, but `Update` never reads them. The geometry
  viewer clamps for itself (see "On the emulator").
- **The joystick handlers are real.** `AddJoyHandlers` registers
  `JoyHandler` for events 46 to 54 on `JoyPort`, then sets
  `HandlersAdded`. `RemoveJoyHandlers` takes them off and clears it. Each
  returns at once if the flag already says so. The constructor clears the
  flag and adds them; the destructor removes them.
- **The constructor and destructor write the camera** unless
  `StopUpdating`. The constructor writes `CarNotToRender` = NULL,
  `RenderDash` = 0 and `FieldOfView = InGameFOV`; the destructor writes
  `FocalDistance` = `DepthOfField` = 0. Neither checks for a camera, so
  a detached mover (`ViewID` -1) is only safe to build or destroy while
  frozen. The port keeps that, and the checker does exactly that.
- **`TM` is never written.** The port leaves it alone too, and the checker
  shows the fill pattern on both sides.

The rest is the demo's, and it is confirmed on retail:
- the zoom's exact compare against 1.0
- the speed approach: a step, then a `movz` on a compare of the gap
  against the acceleration, both signed
- the `ApproachAngleV` walk on unsigned halfwords, snapping under 81 and
  stepping by 80
- the tweakables applied only at the rotations
- `TweakOrbitFOV`, `TargetDistance = FocalDistance = Radius` and a depth of
  field of 8.0 written every frame

`tools/orbit_check.py` runs retail's own code in `mipsemu`:
- the constructor, the destructor and `Update`, through retail's vtable
  where the game goes through it
- `GetTarget`, `GetCarToFollow` and the joystick handler, with retail's
  `CameraMover` base, `SetCameraMatrix` and `IsGameFlowPaused` under them

`tools/src/orbit_test.c` runs the port over the same script.
`AddJoyHandler` and `RemoveJoyHandler` are stubbed on both sides to print
their arguments. The script lays out the world, its cars and a chopper in
memory. The scenarios are:
- construction and every vtable slot
- every event from 40 to 60 at five values, in and out of `FEMode`
- the chopper against every plan
- the pause across coordinator states
- the clamps and approaches at their edges
- the tweakables
- three random walks of 200, 800 and 1500 frames

    python tools/orbit_check.py            # 9 scenarios, 3416 ops, 28635 lines, 0 differ
    python tools/orbit_check.py --mutate   # 124 mutations, 119 caught, 5 equivalent

## The camera shake

`shake.c` ports the camera half of the object that follows
`CameraMover.obj` (retail `0x00155948 .. 0x00156b88`, the demo's
`0x00152860 .. 0x001539f4`), with `Car::MaybeCameraShake` and
`Player::IsCameraPOVInCar` (`player.c`). The other half is the pad's
rumble, which is not ported. The addresses are retail's.

| address | what |
|---------|------|
| `0x00155948` | `tEnvelope::GetIndex` |
| `0x001559a8` | `tEnvelope::OutOfRange` |
| `0x001559f0`, `0x00155a40` | `GetSlope(int)`, `GetSlope(float)` |
| `0x00155aa0` | `tEnvelope::GetValue` |
| `0x00155b28` | `tEnvelope::GetIntegral` |
| `0x00156b10` | `tShaker::tShaker`, out of line in retail |
| `0x001562b0` | `tShaker::GetAmplitude` |
| `0x001562e8` | `tShaker::StartShaking` |
| `0x00156320` | `tShaker::Update` |
| `0x00156370` | `tShaker::GetValue` |
| `0x00156400` | `UpdateCameraShakers` |
| `0x00156480` | the shakers' reset; the World constructor and `DoSnapshot` call it |
| `0x00156528`, `0x00156540` | `GetShake`, `IsShakeActive` |
| `0x00156560` | `ApplyCameraShake` |
| `0x001566c0` | `MaybeCameraShake` |
| `0x001346b0` | `Car::MaybeCameraShake` |
| `0x00178808` | `Player::IsCameraPOVInCar` |
| `0x00156958` | `_GLOBAL_$I$bShakeTest`, the static initialiser |
| `0x002fa820` | `CameraShakers[2]`, 32 bytes each |
| `0x002fa7a0` | `ShakeAmplitudePoints`, five |
| gp-21848 | `ShakeAmplitudeEnvelope` |
| gp-21912 | `bShakeTest` |
| `0x002fa6e0` | `vShakeTest`, (0, 0, 0.3) |
| `0x00334080` | `vShakeAccelBias`, (0.7, 0.5, 2) |
| `0x00334090` | `vShakeRotation`, (-1200, 2000, 0) |
| `0x002b13f0` | `fShakeIntensityCoeffs`: 250, 600, 0.08, 0.16, 0.3, 0.7 |

**An envelope** is a list of (time, value) points in time order, straight
between them. `GetValue` is 0 outside `[first, last)`: at the last
point's own time too, whatever its value. `GetIndex` is the last point at
or before `t`, and 0 before the first; a NaN is before no point, so it
gives the last. `GetIntegral` swaps its ends into order, clamps them to
the points, and adds a trapezium for each segment, with both ends read
through `GetValue`. So the last point's value counts as 0. Its first
segment ends at the point after `a`'s, so when `a` is at the last point it
reads one point past the end.

The amplitude envelope runs 1 at 0, 0.7 at 0.1, 0.5 at 0.3, 0.4 at 0.5 and
0 at 1.

**A shaker** holds a vector, an envelope, a clock that runs from 0 to 1, a
duration and a frequency. `StartShaking` stores the vector negated (all
four lanes, `vmulx` by -1), always takes `ShakeAmplitudeEnvelope`, and
starts the clock at 0. `Update` moves the clock on by `dt / duration` and
stops the shaker (the envelope pointer NULL) once the clock is out of the
envelope's range. `GetValue` is a square wave, not a sine: the vector times
the envelope when `trunc(fTime * fFrequency)` is even, and 0 when it is
odd. At 17 steps a shake is on for nine of them.

**`MaybeCameraShake(player, accel)`** does nothing while that player's
camera is in the car. Otherwise it weighs each axis of the acceleration by
`vShakeAccelBias` and takes the length, `(x*x + y*y) + z*z` as VU0 sums
it. Below 250 there is no shake. The length is clamped to 600, and its
place between the two, `f`, sets the amplitude (0.08 to 0.16) and the
duration (0.3 to 0.7 seconds). Nothing happens if the shaker already
shakes at least that hard. In the zone after a long jump
(`Player::nZoneCurrent` 7) the amplitude is 0.8 of that and the duration
1.2 times it. The shaker then starts along the weighed acceleration,
scaled to the amplitude, at 17. `World::DoTimestep` asks
`Car::MaybeCameraShake` of every car before `AICarPos`, unless shakes are
off. Only a car with a player passes on its `PlayerNumber` and
`State.Acceleration`.

**`IsCameraPOVInCar`**: the player has a mover, it is `CM_DRIVE`, its
`GetCameraInfo` is not NULL, it is enabled, and its
`GetPOV(PlayerSettings.DriveCameraPOVIndex)` is a POV of type `POV_INCAR`
(1). The index is a signed byte. The mover is read from the player again
after `GetCameraInfo`.

**`ApplyCameraShake(view, m)`**. Views 1 and 3 (the rear-view mirror) take
player 1's shake, view 2 player 2's, and any other view none. It is new in
retail that nothing happens while `pCurrentWorld->fTimeScale` is below 1,
the jump cam's slow motion. The shake goes into the camera's space through
`m`, as a direction (`w` 0), and lands in the translation row of an
identity matrix, with `w` 1. That matrix turns about x by the sum of the
row's y and z, about y by its x, and about z by the sum of its x and y,
each scaled by `vShakeRotation`, and `m` becomes `m` times it. So the
camera moves by the shake as well as tipping. `vShakeRotation.z` is 0, so
retail never turns about z.

That translation row is the image's stack layout, not an obvious choice:
the frame holds the matrix at sp+16 and `eMulVector`'s output at sp+64,
the same sixteen bytes. So the row turns with each rotation, and each angle
reads it as the rotations before it left it. The turn about x keeps x, so
the y angle reads the shake's own x. The z angle reads an x and a y that
have both moved. The port builds the row in the same place. The two
callers are not ported yet: `DriveCameraMover::Update` (`0x0015df44`) and
`RearViewMirrorCameraMover::Update` (`0x00159100`). `GetShake` has only
this caller, and `IsShakeActive` none in the image.

**`UpdateCameraShakers`** runs once a frame in MainLoop, after
`UpdatePortRumblers` and before `World::DebugDisplay`. A debug switch goes
first: while `bShakeTest` is set, it is cleared and player 1's shaker
starts along `vShakeTest` for 0.6 seconds. Then both clocks run by
`WorldTimeElapsed`.

**Retail against the demo**: the slow-motion test, the Player offsets
(`pCameraMover` 200, the POV byte 36 and `nZoneCurrent` 88, where the
demo's are 180, 32 and 76), and the reset and the `tShaker` constructor
made out of line. Nothing else changed.

**Not ported**: the rumble (`tRumbler`, `PortRumble` and its seven
envelopes). The replay's `SnapshotCameraShakers` (`0x001564d0`) and
`tShaker::DoSnapshot` (`0x00156220`) are TASKS 72d's
([replay.md](replay.md)). Two calls wait:

- The World constructor's reset waits for World's retail pass.
  `world_init` is still the demo's (`world_check` runs the demo's image),
  and retail's constructor also drops `InitParticles` from its list.
- MainLoop's `UpdateCameraShakers` waits for step 8.

The stack garbage in one lane is not kept. `bNormalize` writes three lanes
of `MaybeCameraShake`'s vector and `StartShaking` negates four, so the
image's fourth lane is whatever the stack held. The port's is 0. Nothing
reads it back, since `ApplyCameraShake` zeroes it.

### The shake, cross-checked

`tools/shake_check.py` runs all of the above out of retail's image in
`mipsemu`. That covers the envelope, the shaker, the static initialiser's
share, the reset, `UpdateCameraShakers`, `GetShake`, `IsShakeActive`,
`ApplyCameraShake` over the matrix layer, `MaybeCameraShake` with
`bNormalize`, `Car::MaybeCameraShake` and `IsCameraPOVInCar`.
`tools/src/shake_test.c` runs the port over the same script.

Only the movers' `GetCameraInfo` and `GetPOV` are stubs: they print their
arguments and answer what the script set. The Players, movers, POVs, the
Car and the World are blobs at retail's offsets on the model side and the
port's structs in the harness. Scratch envelopes and shakers start from a
`0xa5` fill. Each envelope carries a sentinel point past its end for
`GetIntegral` to read. The players' shakers print three lanes.

The script reaches two things the shipped data never does:

- **An envelope out of time order**, with a point past the last one's
  time. Only there does clamping `GetIntegral`'s `b` to the last point
  change the sum.
- **`vShakeRotation` moved**, all three lanes, so the turn about z is
  checked too.

    python tools/shake_check.py            # 7 scenarios, 10604 lines, 0 differ
    python tools/shake_check.py --mutate   # 98 mutations, 95 caught, 3 equivalent

The three equivalent mutants:

- **Dropping `MaybeCameraShake`'s NULL-player test.** `IsCameraPOVInCar`
  reads the player first, so no NULL player gets that far, in the image
  or here.
- **Dropping the fourth lane's 0.** That lane is never read.
- **Letting `GetIntegral`'s count run one further.** `b` is clamped to the
  last point's time, so the segment that reads the last point ends at `b`.
  The time test then ends the loop before the count can.

## The drive camera

`CM_DRIVE`, `DriveCameraMover`, is the chase camera a player drives behind,
and `CameraMover.obj`'s biggest class. `drivecam.c` has all of it. Step 7a
ported the members around `Update`, and step 7b ported `Update`
(`0x0015c880`, 6056 bytes) with the helpers only it calls. `camerainfo.h`
lays out the car type's `CameraInfo` and its `POV`s. The addresses are
retail's.

| address | what |
|---------|------|
| `0x002b1dd0` | the vtable; `Render`, the joystick pair, `Enable` and `Disable` are the base's |
| `0x0015c258` | the constructor, 420 bytes |
| `0x0015c400` | the destructor |
| `0x0015c470` | `ResetState` (+92) |
| `0x0015c520`, `0x0015c528` | `SetPOVIndex`, `GetPOV` (+60) |
| `0x0015c138` | `GetTarget` (+124) |
| `0x0015fc20`, `0x0015fbf0` | `GetCameraInfo` (+52), `GetCarToFollow` (+116) |
| `0x0015c7a0` | `IsExteriorView` (+68), new in retail |
| `0x0015c760` | `IsLookingBack` (+76), new |
| `0x0015c838` | `GetWallGap` (+84), new |
| `0x0015c158`, `0x0015c1d0`, `0x0015c218` | `GetCorrectionYaw`, `GetCorrectionPitch`, `GetInCarCorrectionAngle` |
| `0x0015c5a8` | `CalculateLookbackAngle(Car *, Car *, const bMatrix4 *)` |
| `0x0015fbf8` .. `0x0015fc9c` | the inline accessors' out-of-line copies |
| `0x0015c880` | `Update` (+20), 6056 bytes |
| `0x0015c680` | `GetLookbackCar` |
| `0x00157930`, `0x00157b60` | the wall push and the look-at offset `Update` calls, new in retail and unnamed; the port's `camera_wall_offset` and `camera_look_at_offset` |
| `0x00157c60` | new and unnamed: `BumperCameraMover::Update` calls it, and it calls both wall helpers |
| `0x0015c708` | `GetAccelLag`: nothing calls it or points at it |
| `0x0015e028` | `GetBoomDistToWall`, and `DistanceToLineSegment` and `IntersectLineSegments` after it: the same, dead in retail |
| gp-31028 | `0.7`, the wall gap looking ahead |

**The record** is 1008 bytes in retail. Its fields and names are the demo's
`.mdebug` record (864 bytes), and everything from `TheTopologyCoordinate` on
is 144 bytes further on, because retail's `TopologyCoordinate` is 704 bytes
to the demo's 560. So `DisableLag` is at 884 and `PerfectFocus` at 992. The
port's `TopologyCoordinate` is retail's now, so its offsets are the same.
Nothing reads a drive camera in place.

**The constructor** is `(viewID, car, povIndex, lookbackSpeed, disableLag,
lookBack, perfectFocus)`. It runs the base's for `viewID` and `CM_DRIVE`,
zeroes the look back and the boom's last yaw and pitch, and takes the car's
yaw (`State.Angle`) and pitch (`bASin` of `BodyMatrix.v0.z`, masked to 16
bits). It builds the `TopologyCoordinate`, stores the three arguments,
clears the acceleration lag, its twenty samples and its timers, and sets
`CamAdjustMultiplier` and `TouchingGroundFactor` to 1. `lookBack` sets
`DesiredLookBackParam` to 1 or 0. `LastCarSpeed` is `State.ForwardSpeed`,
retail's word at car +960. Step 7a named that word `VelocityMagnitude`.
`Update`'s speed tests read the same word, and they only make sense as the
forward speed. Unless `Camera::StopUpdating` is set, it clears
the camera's `CarNotToRender` and `RenderDash`. A detached mover (view -1)
has no camera, so it can be built only while that flag is set. The
`CameraInfo` is the car
type's, at `CarTypeInfo` +960, unless either of its two counts is 0. Then it
is `CarTypeInfoArray[0]`'s, read through the array's pointer. Four places
build one: `Player::ChangeCameraMover` (7c), `DemoCameraCoordinator::Update`,
the `NisCameraCoordinator` constructor and `ReplayScreen::ChangeCameraMover`.

**The destructor** clears the camera's `CarNotToRender`, `FocalDistance`
and `DepthOfField` unless `StopUpdating` is set, then runs the topology's
destructor and the base's. It reads the camera before it tests the flag.

**`ResetState`** is the constructor's state again, read off `CarToFollow`,
without the arguments' fields. It leaves `AmountToUseYawCorrection` as it
was. It reads `CarToFollow` twice, and the second read is the one
`LastCarSpeed` comes from.

**`GetPOV(index)`** reads the split-screen set in view mode 3 and the
full-screen set otherwise. It returns NULL when `index` is not below that
set's count. The compare is signed, and nothing tests for an index below 0,
so -1 returns a pointer 32 bytes before the set. `GetTarget` is the car's
`GeometryPosition`, or the camera's target while there is no car.

**The three new virtuals** each count a look back only while the mover has
a player whose `PlayerSettings.Lookback` is 0. Retail made that word an int,
where the demo's was the float `LookbackSpeed`. `ResetToDefaults` sets it to
1, and `ToggleLookback` swaps 0 and 1.

- `IsLookingBack` (+76): that test, and `LookBackParam` above 0.
  `Player::DetermineHudFeatures` asks it.
- `IsExteriorView` (+68): there is no POV at `POVIndex`, or it is
  `POV_OUTSIDE`, or `IsLookingBack` would say yes. It calls `GetPOV`
  through the vtable first, before it looks at the player.
- `GetWallGap` (+84): `(1 - p) * 0.7 + p * 3`, where `p` is `LookBackParam`
  when a look back counts and 0 when it does not.

**The corrections** turn an angle between the car and the boom, a signed
BAM, into the correction to apply.

- **Yaw**: `bATan(1, |a| * 0.000261) * -1.9088`, with `a`'s sign. It reads
  `0x8000` as -32768.
- **Pitch**: `-a` within 7 of 0, and `-a / 8` past that.
- **In-car**: `-a` within 1 of 0, and `-a / 2` past that. Nothing calls it.

Pitch and in-car divide toward 0, and both read `0x8000` as +32768, because
the image counts only an angle past `0x8000` as negative. `Update` is the
only caller of the other two.

**`CalculateLookbackAngle(from, to, m)`** says which way `to` lies from
`from` in the frame of `m`'s first two rows. It normalises the difference
of the two `State.Position`s, multiplying by one reciprocal square root, and
dots it with both rows. Each sum is VU0's order, `(x + y) + z`. It returns 0
past 0.7071 along the first row, `0x8000` below -0.7071, `0x4000` when the
second row's dot is below 0, and `0xc000` otherwise. Two cars on one spot
give a NaN, so every compare fails and the answer is `0xc000`. `Update` and
`AnimatedDriver::HandleLookingBackwards` call it.

**The accessors** are plain loads and stores, with two traps in their
names. `LookingBack` (`0x0015fc28`) asks whether a look back is wanted:
`DesiredLookBackParam` above 0. The non-virtual `IsLookingBack`
(`0x0015fc70`) asks whether `DesiredLookBackParam` is exactly 1. The port
calls the two `drive_cam_looking_back` and `drive_cam_look_back_full`. Both
read `DesiredLookBackParam`, where the virtual `IsLookingBack` reads
`LookBackParam`, how far round the camera actually is. `SetLookBack` stores
1 or 0.

**Retail against the demo**: the three new virtuals, the record's larger
`TopologyCoordinate`, `GetTarget` from `GeometryPosition` where the demo
used `Position`, the fallback `CameraInfo` read inline where the demo
called `GetCarTypeInfo(0)`, and `Update`'s walls (below).

**The walls moved.** The demo's `Update` calls `EnforceMinGapToWalls`
(the demo's `0x0015a5d8`), with `GetBoomDistToWall`,
`DistanceToLineSegment` and `IntersectLineSegments` after it. Retail has
no `EnforceMinGapToWalls`. The other three are still in its image, and
nothing calls them or points at them. Retail's `Update` calls two new
functions instead, `0x00157930` and `0x00157b60`, which follow
`CameraMover::ComputeBankedUpVector`. A third new one, `0x00157c60`, is
the bumper camera's: `BumperCameraMover::Update` calls it, it calls the
same two, and its 1008-byte frame has room for a `TopologyCoordinate` of
its own.

**Waiting**: `Player::ChangeCameraMover`, which builds the mover for each
view, is 7c's. Until 7c nothing builds a drive camera.

### `Update`

One frame of the chase camera, in the image's order. `dt` is
`WorldTimeElapsed`. The matrix goes to `SetCameraMatrix` with
`RealTimeElapsed`.

**The car and the look back's rate.** A look back *counts* when the mover
has a player whose `Lookback` is 0, as for the three new virtuals. The car
is `CarToFollow`, unless `CameraFollowDefaultCar` is 0. Then it is the car
whose driver number is `CameraFollowThisCarInstead`, and that number counts
down past each number with no car. At -1 it falls back to `CarToFollow`.
The image calls `bRefreshTweaker` after each step down, to redraw the debug
menu those words live in. The look back comes round at `LookbackSpeed` a
second. The exception is when there is a cop manager, `DesiredLookBackParam`
is exactly 1 and the look back does not count. Then `GetLookbackCar` names
a car to look back at, and a cop turns at 4/3 a second (`1.3333334`).
Otherwise `iLookBackParam` and `iLookBackHeight` are cleared.
`LookBackParam` steps toward `DesiredLookBackParam` by `rate * dt` and
stops on it.

**`GetLookbackCar(car, &isCop)`** asks the cop manager for the cop driving
`car`. If there is one, it returns the car that cop's pursuit chases and
sets `isCop`. A cop with no pursuit gives NULL. If no cop drives `car`, it
asks for the cop chasing `car` and returns that cop's car. With no cop
manager it returns NULL.

**The POV** is `GetPOV(POVIndex)` through the vtable. If there is none, it
calls `SetPOVIndex(0)` and asks again. With `DriveUseTweakables` set, the
`Drive*` words stand in for the POV's lag, angle, maximum angle, height and
lateral offset. An outside POV's lag adds the acceleration lag below, in
full with the tweakables, or scaled by `1 - round` without them, where
`round = 1 - (cos(LookBackParam * 0x8000) + 1) / 2` eases 0 to 1. A negative
acceleration lag also lowers an outside POV by `lag * CamHeightMultiplierD`.

**The acceleration lag.** `CamGlobalMultiplier` is set to 1 at the top of
every call, so every `* gm` in it multiplies by 1.

- The sample is the car's `Acceleration` in car space (by the body's
  transpose), forward part `a.x`. It is `a.x * 0.045`
  (`CamDecelScaleRatio`) when that is below `CamRangeCheckD`, with sign -1.
  It is `a.x * 0.6` (`CamAccelScaleRatio`) when that is above
  `CamRangeCheckA`, with sign 1. Otherwise it is 0, with sign 0.
- Samples go in 60 times a second: `dt * 60` plus the kept fraction, whole
  frames only. Each frame shifts the twenty `CamLastAccel` along and puts
  the new one first.
- **Sign 1**, while `CamCurrentAccel` is not above 0. The lag fires when
  the ten newest samples all reach `CamRangeCheckA` and the ten before
  them all stay at or below it: a step up. Sign -1 is the mirror, with
  `CamRangeCheckD` and `CamCurrentAccel` not below 0. **Sign 0**: any of
  samples 1 to 9 strictly inside the two thresholds clears `CamLagAdjust`.
- When it fires, `CamLagAdjust` is the ten samples' mean times
  `max(0, 1 - |yaw| * CamYawAdjuster)`, with `CarState::GetYaw`'s yaw,
  held between `CamDecelCap` and `CamAccelCap`. The hold timer clears.
  With `DisableLag` set and `ForwardSpeed` above 5, the lag is scaled by
  `CamDisableAdjust`, and by 0.75 more for `DriverMode` 1, and
  `CamAdjustMultiplier` becomes `CamDisableAdjust`. Otherwise
  `CamAdjustMultiplier` is 1.
- **`CamCurrentAccel` chases it**, per 60th (`f = dt * 60`):
  - When `CamLagAdjust` is 0, it goes back toward 0 by
    `CamBackAdjust * f * multiplier`, twice that while above
    `CamBackAdjustQuicker`.
  - When positive, it steps up `CamAdjustment * multiplier * f`, times
    0.3 within 0.4 of the lag, 0.6 within 1, and 1 past that.
  - When negative, under 5 mph (`ForwardSpeed * 2.237`) the lag clears.
    Otherwise it steps down by the full step.
  - A `CamCurrentAccel` already past the lag *holds*. The hold timer runs,
    and past `CamHoldTimeout`, or with the sample's sign 0, the lag clears.
- The boom grows by `CamCurrentAccel * CamLagMultiplier`, fading to
  nothing at `CamSpeedAdjust` mph (500). With `DisableLag` it adds 0.

**The base** takes the world to the car's `GeometryPosition`. Inside, it
turns by the body's transpose, then by `LookBackAngle` unless the look back
counts. With a look-back car, `LookBackAngle` is
`CalculateLookbackAngle(car, lbCar)` first. Outside, it turns by the
heading only. The heading is the nose, swung toward the way the car moves
as it passes 8.32 m/s, and all the way by 13 m/s (`w = (|v| - 8.32) *
0.21276592`, clamped to 0..1). A velocity behind the nose is mirrored
forward first. `bNormalize2To` makes a zero velocity (1, 0), so a car at
rest swings toward +x by the nose's own length.

**A cop's look back** (outside, with a look-back car):

- `want` is the heading less the bearing to that car. Within 45 degrees of
  straight back it is 0, and the rise over the roof is `0.75 * add`, else
  `add`. `add` is 0.4, or 0 in view mode 3, and the target height is
  `Body.Zdim - height` plus that rise.
- `iLookBackParam` goes the short way round. It moves 60000 BAM a second
  times the rate while more than 10000 off, or while the car is past 50 m
  and `want` is not 0. Otherwise it moves 20000. It stops on `want` and is
  masked to 16 bits.
- `iLookBackHeight` steps toward the target height at the rate, and
  `LookBackAngle` is `iLookBackParam`.
- Coming round from just short of 45 degrees to a far car straight back
  wraps `want` to 65536, whose low half is 0, so that step is the slow one.

**The boom, outside.**

- **Yaw.** `TouchingGroundFactor` moves by 0.24316 a frame, down with
  fewer than three wheels on the ground and up otherwise, held to 0..1. The
  yaw is the heading's turn since last frame plus `LastBoomYaw`, then that
  plus `GetCorrectionYaw` of itself times the factor times `dt`.
- **Pitch.** It starts from the body's pitch `p`. While `LookBackAngle`
  is 0, `p` is eased first. In the air (factor 0) a nose-up pitch loses a
  ninth, and a nose-down one loses a third of the way to level. On the
  ground each gains the same. Then `s = LastBoomPitch - p`, and
  `s = LastBoomPitch + GetCorrectionPitch(s) * dt * 25`.
- **Road noise.** `RoadNoiseAmplitude` (250) times
  `GetRoadNoise(Position.xy, dirt)` adds to the pitch.
- `LookBackAngle` then turns the boom unless the look back counts.
- **Inside**, the four boom words are seeded from the car instead.
- **A dead branch.** The image keeps its "in the air" factor as ±1 and
  then tests it against 0. That branch never runs, and the port keeps it.

**A counted look back** swings the boom round behind by `LookBackParam`
`p`, where `t = 1 - p`:

- The height goes to `t * height - 3p`, or `- p` in view mode 3.
- The lag goes to `t * lag + 18p`, or `16p` in view mode 3.
- The pitch goes down by `t * angle + 5200p`, or `3540p` in view mode 3.

**The eye, outside.**

- With a look-back car, the height adds `iLookBackHeight` and the lag is
  2.24.
- The eye is the inverse of the base times the boom times
  `(lag, lat, -height)`.
- The topology's interest box is centred midway between the eye and the
  car. Its radius is half their distance plus 1, and it is given the car's
  velocity.
- The car's position in eye space, `pc`, gives the screen offset
  `-clamp(1 / pc.x, ±1000) * (pc.y, pc.z)`.
- The wall push (below) moves the eye.
- Without a look-back car, an eye inside the car's reach (the larger of
  the car-space box's `|min.x|` and `max.x`, plus 0.7) is lifted onto that
  sphere, and `raise` is the old height over the new.
- The push is taken back into boom space and folded into the height, the
  lateral offset and the lag.

**The matrix.** The boom translates by `(lag, lat, -height)` and pitches
down by `angle + raise * (maxAngle - angle)`. Outside, the matrix is the
look-at offset (below) from the eye to the car's `Position`. Inside, the
eye stays 0.7 over `GetElevation`. A lifted eye's matrix is the inverse of
the lifted one, and an unlifted eye's is the base times the boom. Then it
turns by `eRotateX` 16384 and `eRotateY` `0xc000`, the camera's axes.

Outside, nothing reads that translate and turn, since they come after the
eye. The image still works out the push folded back into boom space,
`raise`, and the turn, and then drops them. The port does the same. Inside,
there is no push and `raise` is 0, so `maxAngle` never counts, whether it
comes from the POV or from `DriveMaxAngle`.

**The camera's words.**

- Unless `StopUpdating` is set:
  - `RenderDash` is cleared.
  - Inside, `CarNotToRender` is the car, and the dash is drawn for
    `POV_INCAR` without a full look back.
  - Outside, `CarNotToRender` is NULL.
  - The field of view is 16384 in-car and on the bumper, and 13020
    outside.
- `NearZ` is 0.4 in-car and 0.5 otherwise, even while stopped.
- Then the shake.
- `TargetDistance` is the camera's current position's distance to the car,
  from before this frame's matrix is set.
- Unless `PerfectFocus` is set, the focal distance is 15 and the depth of
  field 65.
- Then `SetCameraMatrix`. A counted look back leaves `LookBackAngle` 0.
- The image works out the bumper's `|ForwardSpeed|` and drops it.

**The wall push** (`0x00157930`, `camera_wall_offset`):

- It starts with `ConstrainToTopology` from the car's position to the eye
  (two-sided, 0.01, lift 1).
- Then, up to three times, it looks at every polygon in the interest table
  whose terrain the camera may not go through (all but terrains 16, 28,
  29, 30 and 32). A polygon counts when its shaft holds the pushed eye
  within the gap: `GetWallGap` for a polygon flagged 2, 0.7 for the rest.
  Each such polygon pushes along its normal by what is left of the gap,
  and the pushes are averaged.
- A pass that finds none ends it.
- Every sum is a four-lane VU0 add. The fourth lanes carry the planes'
  distances along, and nothing reads them. The result's fourth lane is 0,
  and `Update` multiplies it through the boom's matrix.

**The look-at offset** (`0x00157b60`, `camera_look_at_offset`) builds the
look-at from the eye to the target, up (0, 0, 1), and moves the target in
that frame by the offset times its depth. Then it builds the look-at again
to the moved target. The image passes the mover and never reads it.

**Every float constant** in these three functions was checked bit for bit
against the words the image loads. The heading's `1 / 4.7` is `0.21276592`
(`0x3e59df4f`). The `0.212766` first written here is six units off in the
last place, and no transcript showed it. The tuning words' initial values are
retail's.

### The drive camera, cross-checked

`tools/drivecam_check.py` runs retail's code in `mipsemu`:

- the constructor, the destructor through the vtable, and `ResetState`
- `SetPOVIndex` and every vtable slot but `Render`, `Update` included
- the three corrections, `CalculateLookbackAngle` and the out-of-line
  accessors
- `GetLookbackCar` and the two wall helpers

They run over the base, the `Camera` constructor, `SetCameraMatrix`, the
`eMath` matrices, `bASin`, `bATan`, `bCos`, `bNormalize` and retail's own
`eView` table. `tools/src/drivecam_test.c` runs the port over the same
script.

What `Update` reaches outside the class is stubbed on both sides, and each
stub prints its arguments:

- `TopologyCoordinate`'s constructor and destructor
- `GetCarByDriverNumber`, `bRefreshTweaker`, the cop manager's
  `GetCopByCar` and `GetCopByChase`, and `CarState::GetYaw`
- `GetRoadNoise`
- `SetInterestBBox`, which fills the interest table from a scenario's list
- `GetElevation`, `ConstrainToTopology` and `PointInShaft`, whose distance
  is the plane's, summed in the image's order
- `GetCarSpaceBoundingBox` and `ApplyCameraShake`

What they return is the scenario's. Each of those functions has its own
checker. Every camera, mover, car, car type, player, polygon, cop and
pursuit starts from a `0xa5` fill, so what a call leaves alone shows.

The members around `Update` have eight scenarios, built to reach three
things:

- **The look back.** The players' `Lookback` words take 0, 1, 2 and -1, and
  some of the queries count one.
- **`CalculateLookbackAngle`'s thresholds.** Inputs exactly on ±0.7071 and on
  a 0 side. A search also builds directions within 1e-6 of the threshold,
  where adding the squares in another order, the dots in another order, or
  dividing instead of multiplying by the reciprocal would cross it. It finds
  four inputs for each of the three.
- **`ResetState` against Update's state.** Before most resets the walk
  scribbles distinct words over every field only `Update` writes, standing
  in for frames of `Update`. Without that, those fields are still the
  constructor's 0s and 1s, and dropping any of their resets changes nothing.

`Update` has six more. Each drives four cars frame by frame, simulated in
calm, pulling, braking and airborne spells. Every car has a mover except
in the last scenario, which has one. Before each frame's `Update` it sets
the stubs' answers: the polygons and their planes near the eye, the
elevation, the constrain's nudge, the car-space box and the shake.

- **The edges.** A boom of no length on a car whose `GeometryPosition` is
  its `Position` (the screen offset's 1/0), and a short boom inside the
  car's reach. Speeds of 0, 250, 30 and -4, and a grid of speeds and
  pitches across the heading's 8.32 and 13 m/s. The lag held past its
  timeout at a tenth of a second a frame, with the lag disabled and not,
  and with `CamBackAdjustQuicker` low enough to reach.
- **The chase.** Four cameras on four views, with the POV and the view mode
  moving under them, and POV indices past the end, so `GetPOV` comes back
  NULL.
- **The look back.** Movers whose player counts the look back, the wish to
  look back flipping, in split screen and full.
- **The cops.** One car is a cop chasing another. The chased car is pinned
  at one bearing after another, near and past 50 m, so `iLookBackParam`
  comes round both ways, fast and slow, stops on its target, and wraps,
  including the wrap to 65536. The boom is lowered partway so the rise over
  the roof goes up as well as down. Random scribbles of the mover's words
  are held off while it settles.
- **The tuning.** `DriveUseTweakables` and `CameraFollowDefaultCar` held
  over stretches, `CameraFollowThisCarInstead` counting down past missing
  drivers, `StopUpdating` held over twelve frames, and every `Cam*` word
  and both elapsed times changed at random.
- **The corners.** One outside camera, not looking back, on a car driven
  slowly near the origin through fixed spells. A look back would get in
  the way twice: its round of 1 takes the lag out of the POV's boom, and
  its `LookBackAngle` takes the pitch off the nose. Near the origin, a
  last-place change in the lag survives into the eye: dividing by
  `CamSpeedAdjust` instead of multiplying by its reciprocal, or grouping
  the product another way. Hundreds of metres out, it rounds away.
  `CamLagMultiplier` is 1.37, because at its default of 1 either grouping
  is exact. In turn, it holds:
  - `StopUpdating` over the first frames, while the camera's focus is
    still 0
  - the lag's pull and brake with `DriveUseTweakables` 1 and `DriveLag` 0,
    then 7 and 5, then the POV's words
  - one sample of pull, nine calm and then the pull, so that only the
    twentieth sample holds the lag back
  - the lag disabled
  - `CamSpeedAdjust` under the car's speed
  - two brakes through walking pace with the lag held
  - the nose straight up, where `bASin` gives 16384, on the ground and in
    the air
  - `CameraFollowThisCarInstead` at 0 with no car for driver 0
  - a cop's look back wanted half way, then at a chased car 45 m off at
    50 degrees either side, between the step speeds' distances

  The random scenarios never lined up any of these. Each line they
  reach had already run. The first mutation pass found the twelve
  changes the other scenarios could not see.

Under `gcov -b` over this script, every line and branch of `Update`, the
wall push, the look-at offset and `GetLookbackCar` runs, except for three
groups:

- `GetLookbackCar`'s answer with no cop manager, which `Update` never asks
  for.
- The retail dead branch above.
- Branches the code rules out: a NaN `DesiredLookBackParam`, and a
  look-back car while the look back counts.

    python tools/drivecam_check.py            # 14 scenarios, 45598 ops, 105702 lines, 0 differ
    python tools/drivecam_check.py --mutate   # 493 mutations, 474 caught, 19 equivalent

The nineteen equivalent mutants:

- **The dead boom, ten of them.** After the eye comes one more translate
  by `(lagx, lat, -height)` and one more turn by
  `angle + raise * (maxAngle - angle)`. Outside, nothing reads that
  boom, since the matrix is the look-at from the eye. Inside, the push
  folded back into boom space (`o`) is never worked out, `raise` is 0
  and `lagx` is `lag`. So nothing that only feeds them shows:
  - how `raise` is worked out
  - the lift added to `wall.z`
  - `o`'s matrix, and each of its three folds
  - `lag` for `lagx`
  - `maxAngle` for `maxAngle - angle`
  - `maxAngle` from the POV's `Angle`, or from the POV in place of
    `DriveMaxAngle`, since that turn is the only reader
- **The push's fourth lane, twice**: summing no plane distance into it,
  and not clearing it on the way out. `PointInShaft` reads each probe's x,
  y and z only. The push is stored with pad 0. Without that store, the
  lane would reach only the eye's pad, which the look-at never reads, and
  `o`.
- **Treating `bASin`'s result as signed**, in the constructor and in
  `ResetState`. The port's `bASin` already returns 0..`0xffff`.
- **Dropping the destructor's vtable store.** The base's destructor, next,
  stores its own.
- **Dropping `GetLookbackCar`'s cop-manager test.** `Update` calls it only
  when `pCopManager` is set.
- **Setting the braking spring's `ok` to 1 instead of -1.** It is only
  ever tested against 0.
- **Dropping `!canLB` from the cop's turn to the chased car.** `lbCar` is
  NULL whenever the look back counts.
- **Dropping the pitch's first 16-bit mask.** The correction takes
  `(uint16_t)s`, and `s` is masked again after it.

## The player's cameras

`Player` owns the camera movers. It builds them, retires them, and keeps
up to two in reserve for the zone cameras that come back to the chase
view. The port's versions are in `playercam.c`, apart from `player.c`,
because they build movers. `player.c` goes into harnesses that have no use
for `drivecam.c` and `orbitcam.c`.

| function | retail | bytes |
|----------|--------|-------|
| `ChangeCameraMover(CameraMoverType, bool keep)` | `0x00176ae8` | 2372 |
| `CycleDriveCameraPOVIndex(int)` | `0x001786d0` | |
| `RestoreCameraMover()` | `0x00176948` | |
| `RemoveCameraMovers()` | `0x00177430` | |
| `EnableCameraMovers()` | `0x001774a8` | |
| `DisableCameraMovers()` | `0x00177558` | |

The port's `Player` is retail's 2752 bytes, field for field (see
[player.md](player.md)), so these are both sides' offsets. Retail has a
second saved mover, which the demo lacks:

| field | offset |
|-------|--------|
| `MyCar` | 4 |
| `ViewID` | 24 |
| `PlayerSettings` | 32 |
| `PlayerSettings.DriveCameraPOVIndex` (byte) | 36 |
| `PlayerSettings.CameraSpring` | 40 |
| `pRoute` (the zone preview's) | 136 |
| `pCameraMover` | 200 |
| `pSavedCameraMover` | 204 |
| `pSavedCameraMover2` | 208 |
| `pRVMCameraMover` | 212 |
| `pDemoCameraCoordinator` | 216 |
| `pCountdownCameraCoordinator` | 220 |
| `pNisCameraCoordinator` | 224 |
| `pVisibleDrivingLine` | 228 |
| `pNisManager` | 244 |
| `bLookBack` | 764 |

### `ChangeCameraMover`

In order:

1. **The coordinators are deleted first.** The demo and countdown
   coordinators go through their virtual destructor (vtable at +24, slot
   12, flag 3). The NIS coordinator goes through
   `NisManager::DeleteCameraCoordinator` (`0x001b2b90`) on `pNisManager`.
   Each pointer is cleared. This happens even when the call does nothing
   else.
2. **Same type, nothing more.** If `pCameraMover` is already of `type`,
   return.
3. **The car** is `MyCar`, or when that is NULL `pCurrentWorld`'s
   `CarList.next`. The list's first link is not checked. An empty list's
   first link is `World` itself, which the new mover would take as its
   car.
4. **The old mover is retired.** With `keep`, `pSavedCameraMover` moves to
   `pSavedCameraMover2`, the old mover becomes `pSavedCameraMover`, and it
   is disabled. Without `keep` it is deleted through its virtual
   destructor. `pCameraMover` is cleared either way.
5. **The new mover** is built by type, through the jump table at
   `0x002b3b30`. The switch is unsigned: anything above 17, negatives
   included, lands on the orbit.
6. **Whatever was built gets the player** in `pPlayer` (mover +28).

| type | mover | bMalloc | constructor's arguments |
|------|-------|---------|-------------------------|
| 0 | none | | |
| 1 | `DriveCameraMover(Player)` | 1008 | view, car, the POV byte, 300.9 (gp-30468), `CameraSpring`, 0, 1 |
| 2 | `DebugWorldCameraMover` | 76 | view, the car's position 4 up, `{0, 0, 1}`, port 1 |
| 3 | `TrackRouteEditorCameraMover` | 44 | view, port 1 |
| 4-12 | `OrbitCarCameraMover` | 208 | view, car, port 1 |
| 13 | `ZoneFreezeCameraMover` | 872 | view, car, `pSavedCameraMover` |
| 14 | `ZonePreviewCameraMover` | 1104 | view, `pRoute`, the car's position |
| 15, 16 | `TrackCarCameraMover`, the zone jumpers | 1136 | view, car, the `CameraDataItems` at player +1652, a cleared 560-byte shake, 0 for 15 and 1 for 16 |
| 17 | `CubicCameraMover` | 160 | view, car |
| 18 and up | `OrbitCarCameraMover` | 208 | view, car, port 1 |

The drive camera needs three more steps. `DesiredLookBackParam` (+124)
becomes 1 if `bLookBack` is set, else 0. Then the POV byte goes through
`CycleDriveCameraPOVIndex`, which sets the camera's POV, and the byte is
set to the answer.

The zone freeze is built after step 4. With `keep`, the mover it gets is
the one just saved, and it hands back to that mover when the freeze ends.
The zone preview takes the player's `pRoute`. Once the preview is built,
the route is deleted (`PreviewRoute`'s destructor, flag 3) if there is
one, and `pRoute` is cleared.

The zone jumpers are two paths, 15 at `0x00176ddc` and 16 at
`0x00177200`:

- Type 15 builds a `TrackPathCoordinate` from the route at player +1764
  (`PreviewRoutePoint::GetPosition`), and stores the camera's point at
  player +1696.
- Type 16 builds no path. It reuses that point, raised to at least the
  car's height. Two of the data's fields are set from the car's word at
  +2032.

Both lift the point to the ground under it (`TopologyCoordinate`), fill
the `CameraDataItems` at player +1652, and build the
`TrackCarCameraMover`. `playerzone.c` has both since Session 37, as
`gPlayerJumpCamMoverFn`; "The jump cam's mover" below has what each
writes.

### The POV cycle

`CycleDriveCameraPOVIndex(index)` starts with `index % 4`, as C's
remainder, so -5 is -1. With no mover, a mover that is not the drive
camera, or a drive camera with no `CameraInfo` (vtable +52), that comes
straight back. Otherwise it tries up to four indexes, stepping
`(index + 1) % 4`. An index counts if `GetPOV` (vtable +60) gives a POV
and one of these holds:

- `SkipFE` (gp-23220) is set,
- the car's ride has a dash (`pRideInfo->HasDash`, ride +6), or
- the POV's type is `POV_BUMPER` (0) or `POV_OUTSIDE` (2).

If none counts, the index is 0. That goes to `SetPOVIndex` (`0x0015c520`)
and is returned. The car is read unchecked, so only a player with a car
ever has a drive camera. The dash test is what keeps a car without a
cockpit off the in-car views.

### The rest

- **`RestoreCameraMover`** deletes the current mover, pops
  `pSavedCameraMover` into its place and `pSavedCameraMover2` into that,
  and clears the second. If the restored mover is the drive camera, its
  `DesiredLookBackParam` follows `bLookBack` again. Then it is enabled.
- **`RemoveCameraMovers`** is `ChangeCameraMover(CM_NONE, false)`, then
  deletes both saved movers.
- **`EnableCameraMovers` and `DisableCameraMovers`** walk the same six:
  - the player's mover, and the mirror's, through vtable +100 or +108
  - the demo and the countdown coordinators (`0x00199b90`, `0x00199b48`)
  - the NIS coordinator, through `NisManager`'s enable and disable
    (`0x001b2c20`, `0x001b2bd0`)
  - the driving line, a tail call to `VisibleDrivingLine`'s enable or
    disable (`0x00183208`, `0x00183200`)

  Each is skipped when NULL.

### The seams

The port builds the drive camera and the orbit camera. Every other mover
is a seam: a function pointer, NULL until that class is ported, and
`playercam.c` says so at each one. With the seam NULL nothing is
allocated, so the player is left with no camera, as type 0 leaves it.
These are the seams:

- `gDebugWorldCameraMoverFn`, `gTrackRouteEditorCameraMoverFn`,
  `gZoneFreezeCameraMoverFn`, `gZonePreviewCameraMoverFn` and
  `gCubicCameraMoverFn`, each handed the bMalloc block
- `gPreviewRouteDeleteFn`
- `gPlayerJumpCamMoverFn`, which covers both zone jumpers
- the coordinators' delete, enable and disable
- the NIS manager's three
- the driving line's two

`SkipFE` is `gPlayerCamSkipFE`, which `main.c` points at the flow's
`skipFE`. NULL reads as 0, the value the disc ships.

Step 8 brought the callers: `Player::CleanupAfterRace` (which calls
`RemoveCameraMovers`), `BeginCountdownCameras` and `UpdateNonGameState`.
The camera zones came in Session 37, and `main.c` now sets
`gPlayerJumpCamMoverFn` (`player_jump_cam_mover`) and
`gPreviewRouteDeleteFn` (`preview_route_delete`). The freeze's and the
preview's movers are still NULL.

Step 11g-2c-1 ported the coordinators' base and the countdown's
([camera-coordinator](camera-coordinator.md)). `main.c` now points the
coordinators' delete, enable and disable, and
`gCountdownCameraCoordinatorFn`, at `cameracoord.c`. No bundle on the
retail disc has a `COUNTDOWN_n` camera, so the countdown's coordinator
builds no mover and `UpdateNonGameState` gives the car its drive camera
for the 3-2-1, as retail does.

### Divergences

- **Restoring with nothing saved.** Retail calls `Enable` through a NULL
  mover and would fault. The port does nothing. Retail's two callers,
  `RequestZone` and `ClearZone`, restore when a zone camera is up.
- **The debug-world direction's pad lane** is 0. Retail leaves the lane as
  the stack had it, and the mover never reads it.
- **The two zone jumpers are one seam** with a `second` flag. Retail has
  two paths, and both build the same mover.
- **Every seam and the `SkipFE` pointer are NULL-guarded.** That is the
  port's; retail's calls are direct.

The drive and orbit sizes come from `sizeof`. Both match retail: 1008 and
208.

### Cross-checked on retail's image

`tools/playercam_check.py` runs retail's six functions in `mipsemu` and
`tools/src/playercam_test.c` over `playercam.c`, the same op script to
both, and diffs the transcripts.

On the emulator's side, the Player, four cars, their rides, World and
every coordinator are laid out at retail's offsets. Two pools hold the
movers, one for the new ones and one for those an op plants. Fake
vtables and stubs stand in for the rest:

- `bMalloc`, and each mover's constructor, destructor, `CameraInfo`,
  `GetPOV`, `Enable` and `Disable`
- `SetPOVIndex`
- the coordinators, the NIS manager, the driving line and the route's
  destructor

The zone jumpers are two small thunks planted in the jump table's slots 15
and 16. They call the seam's stub with the second flag and return
through the tail at `0x001773ec`, as the port's seam does. Every stub
prints what it was handed. After each op, both sides print the player and
every live mover: its type, its player and, for a drive camera, its look
back.

The scenarios:

- **Every type** (0-18, 25, -1 and `0x80000000`), with and without keep,
  from the player's car and from World's list, and an empty World.
- **The saves**: keep chains two deep, the zone freeze taking the mover
  just kept, restores down to nothing, and the look back on a restored
  drive camera.
- **The POV cycle** over 14 layouts of POVs and types, with SkipFE and
  the dash both ways, indexes -9..9, the current mover's type changed
  under it, no mover, and the default POVs over stored POV bytes.
- **The coordinators**: the 16 masks of the demo, countdown and NIS
  coordinators and the driving line, through `ChangeCameraMover`'s
  deletes, `Enable` and `Disable`, with and without the mirror's mover.
- **Three random walks** of 300, 800 and 1500 ops over everything.

The walks keep two rules. A player without a car has SkipFE set, since
the cycle reads the car. Nothing asks for the debug world with no car
and an empty list.

    python tools/playercam_check.py            # 7 scenarios, 5277 ops, 162056 lines, 0 differ
    python tools/playercam_check.py --mutate   # 109 mutations, 109 caught, 0 equivalent

Three mutants are caught by crashing the harness: reading the car only
from World, reading World's list the other way, and ignoring SkipFE. Each
reads a NULL car the scenarios keep away from.

## The jump cam's route

`Car::FinishMovement` asks for the jump cam once every eight loops while
the car is in the air, over 30 m/s, the right way round, and with an
average air time of more than 0.5 s and a height of more than 1.5
(`car.md`). The first question is `Player::IsJumpCamAvailable`
(`0x001769e8`):

1. `CleanUpJumpCam` (`0x00176ab0`).
2. On the track whose `SameAsTrackNumber` is 21, the answer is no within
   40 of (1646, -884), as a box test, and no route is built.
3. A `PreviewRoute` 50 out and 75 long from the car, into
   `pJumpCamRoute` (player +1764).
4. The answer is yes if the route has five points or more. If not, the
   route is cleaned up again.

`previewroute.c` is zonecameras.cpp's `PreviewRoute`, the road ahead as
a run of racing route points. The zone preview (type 14) builds its own
through `ZonePreviewCameraMover::FindRoute`, which is not ported.

| `PreviewRoutePoint`, 24 bytes | offset |
|---|---|
| `pRoute`, the route it is on | 0 |
| `pPoint`, the route point | 4 |
| `fLength`, to the next point in 3D | 8 |
| `fOffset`, to the right of the route point | 12 |
| `nLine`, the driving line, -1 for the centre | 16 |
| `fRouteGap`, how far off a route change landed | 20 |

| `PreviewRoute`, 24 bytes, no vtable | offset |
|---|---|
| `pPoints` | 0 |
| `nPoints` | 4 |
| `vTrackDirection`, the car's `PathDirection` | 8 |
| `fDistance`, asked for, then walked | 16 |
| `fOffset`, the car to the right of point 0 | 20 |

These are the route's functions:

- **The constructor** (`0x00164630`) allocates `length / 4` points.
  - The first point is the car's own route point, at the nearer of the
    car class's two driving lines. This needs the car to have a route
    and a route point, within `radius`.
  - Without them, the first point is `ClosestPoint`'s pick.
  - Then it calls `NextPoint` until the points run out, one fails, or
    the walk is longer than `length`.
  - It keeps the count and the walked length. If the first point fails,
    the points are freed and the count is 0.
- **`NextPoint`** (`0x001648a0`) finds the next route point on the same
  route and line.
  - Past the route's end, it uses `ClosestPoint` from the last point's
    place, onto the next racing route ahead.
  - The point before gets the 3D distance between the two as its
    `fLength`, which is also returned.
- **`ClosestDistance`** (`0x00164aa0`) tries the class's two lines,
  `2 * line` and `2 * line + 1`.
  - The first one the route has (`IsValid` or `IsFake`) wins.
  - The centre is used only if neither is there and the point runs the
    car's way.
  - It answers the distance in the XY plane, or 1000000 if nothing was
    measured.
- **`ClosestPoint`** (`0x00164c80`) searches every racing route in the
  manager's order, for the point ahead within the radius.
  - The nearest point wins.
  - The answer is no if the last route's search found nothing, because
    retail keeps that route's answer.
  - On a point-to-point race, it will not step back round the track.
- **`PreviewRoutePoint::GetPosition`** (`0x00164418`, `0x00164428`) is
  the point's place, along the route point and across it.

`tools/prevroute_check.py` runs retail's constructor, destructor,
`NextPoint`, `ClosestDistance`, `ClosestPoint` and `IsJumpCamAvailable`
against the port:

    python tools/prevroute_check.py            # 18 scenarios, 2934 ops, 23375 lines, 0 differ

Its mutation pass catches all 57.

## The jump cam's mover

Both jump cam types build one `TrackCarCameraMover` (`CM_TRACK_CAR`,
1136 bytes, `0x00159130`, vtable `0x002b1ad0`), from the
`CameraDataItems` at player +1652 (164 bytes). The race has no track
cameras, so the jump cam is its only user in the port.

### `Spline`

`spline.c` is spline.cpp's `Spline` (48 bytes): a Catmull-Rom curve
through `bVector3` control points, counted by control point, so 0 is the
first and n-1 the last. What happens outside 0..n-1 depends on the type:

| Type | Outside 0..n-1 |
|---|---|
| CLAMP | held at the first or last point |
| LOOP | wrapped with `bFMod` |
| EXTRAPOLATE | one static point past either end, on the line through the last two |

`GetPoint` (`0x00189948`) takes the four weights for u = t - floor(t),
rounded as retail rounds them. `Evaluate` (`0x00189810`) sums
`c0*P(t-1) + c1*P(t) + c2*P(t+1) + c3*P(t+2)` in that order, on all four
lanes, so a point's pad lane is carried into the result. Only the
constructor over an array, the destructor, `GetControlPoint`, `Evaluate`
and `GetPoint` are ported. Calibration and the length searches have no
caller yet.

### `TrackCarCameraMover`

The constructor copies the `CameraDataItems` and the `CameraShake` (560
bytes). It builds four splines over the copies' arrays:

- the field of view, 32 entries, degrees in x
- the eye, `NumEyeVerts`
- the bank, a BAM in x
- the shake, `NumCVs`

It also builds a focal-distance cubic, from +-(26 to 44) toward 0 over
0.42 s, from `bRandom`'s default seed.

The spring starts at (`SpringXVel`, `SpringYVel`, `SpringYVel`), with the
record's Y twice. Retail tests a static vector first, but only that
vector's initializer ever writes it.

Each `Update` (`0x00159588`) does nothing while the flow is paused.
Otherwise it does these, in order:

1. **The eye.** It goes on the eye spline at the car's share of the
   window from `MinAreaPercent` to `MaxAreaPercent` (or at its own speed
   when not locked to the car). With a wipe, it goes on the line between
   two points, at the car's projection pushed `WipeDistance` along it,
   until the car pulls away.
2. **The look.** It looks at the car, raised and moved sideways by the
   enter compensations and the shake, then sprung (`CalcSpringForce`,
   `0x00159540`).
3. **The field of view.** It comes from the FOV spline at the car's
   share of the `MinPercent`..`MaxPercent` window. An iso one is held at
   a unit's distance.
4. **The bank.** The bank spline rolls the up vector about the way the
   camera looks (`ComputeBankedUpVector`, `0x00157888`).
5. **The focus.** The depth of field stays on the car while the focus
   effects are on. A frozen camera keeps its field of view and focus.

The destructor (`0x00159490`) sets the focal distance and depth of field
to 0 unless the camera is stopped, and sets `ClearVelocity`.

### Types 15 and 16

**Type 15** (`0x00176ddc`) writes the record for a camera beside the
road, ahead of the car.

- **The eye.** It is locked to the car's progress round the track
  (`RatioAroundTrack`, turned round by `TrackDirection`). The progress
  runs from where the car is to a route point near the end of
  `pJumpCamRoute`: n - 1 of n under 6 points, else n - 3. That point's
  ratio comes from a `TrackPathCoordinate` there.
- **The two eye points.**
  - The first is that point's edge of the road whose way from the car
    runs least with the car's velocity. It is a unit up, and at least a
    unit above the ground there.
  - The other is route point 2's opposite edge, a unit up.
  - `EnterHorizComp` is 0.4 for the left edge, -0.4 for the right.
- **The rest.** The field of view is 20 degrees throughout, with no
  bank, `NearClip` 0.5, `FarClip` 10000, `EnterVertComp` 0.2, and the
  other fields 0. The area and the shake bank are left as they were.

**Type 16** (`0x00177200`) starts again from the car's progress. It
changes what 15 left:

- It puts all three eye points at the third, raised to the car's height,
  then above the ground.
- It reverses `EnterHorizComp`.
- It narrows the field of view from 20 by a quarter a step.
- It keeps the focus effects on.

Both end with a shake of nothing with two points, and the mover on the
record. The pad lanes of the eye points and the tables are the stack's
in retail, and 0 in the port.

`tools/trackcarcam_check.py` runs retail's constructor, destructor,
`Update`, the vtable's other slots and `Spline`'s against the port. It
does not compare pad lanes retail leaves as the stack had them.

    python tools/trackcarcam_check.py          # 14 scenarios, 6969 ops, 33697 lines, 0 differ

Its mutation pass catches all 157. Types 15 and 16 are checked with the
zones, below.

## The camera zones

A zone is one of these, each with its camera, a radial blur on the
player's view and a sound:

- a spell of slow or fast time
- a pause
- the jump cam

`Player::nZoneCurrent` (player +88) holds it:

| Zone | What | World | Camera | Sample |
|---|---|---|---|---|
| 1 | freeze | paused for `ZoneFreezeCameraMover::Duration` | 13, keep | Wind |
| 2 | preview | paused for its duration | 14, keep | PreviewZone, at volume 0 |
| 3 | slow motion | 0.333 for 8 s | — | SlomoZone |
| 4 | short slow motion | 0.333 for 2 s | — | SlomoZone |
| 5 | fast | 2 for 4 s | — | Wind |
| 6 | the jump cam | 0.4 for 8 s | 15, keep, not in a replay | SlomoZone at pitch 0.9 |
| 7 | after the jump | 0.4 for 8 s | 16, keep, not in a replay | SlomoZone at pitch 0.9 |

### `RequestZone`

`Player::RequestZone(zone, force, sound, muffle)` (`0x00177c88`) says no:

- while an NIS plays, or in the AI demo
- without `force`, within 5 s of this zone's last start
  (`tAutoZoneTimers[zone]`)
- with `force`, within 0.1 s of `tAutoZoneTimers[0]`, which `ClearZone`
  stamps for the freeze and the preview
- while the race is not racing
- for zone 8 or more, or with two players
- for 6 and 7 with the `JumpCams` setting off, or for 1 to 5 with
  `ZoneCams` off
- if any player is in 3 to 7 (the table at `0x00330798`), after a freeze
  or preview the player is in has been cleared (`0x00330790`)

Otherwise it starts the zone:

1. `tIgnoreNextPovChange` becomes `RealTimer`.
2. Without `force`, the zone's timer becomes `WorldTimer`.
3. The HUD's animations are cleared.
4. The zone's own start runs:
   - **The freeze and the preview** refuse in a replay.
   - **The preview** also refuses a wrong-way car, no route, or a
     camera that `ViolatesTopology`, each with the "MenuWrong" sound. A
     camera that violates it is put back after the sound.
   - **Zone 6** calls `CleanUpJumpCam` after its mover is built, and in
     a replay, where no mover is built.
5. `RadialBlurOn` for the player's view.
6. `nZoneCurrent` and the muffle are set.
7. With `SoundEnabled`, `sound`, and category 0 above silence, the zone's
   sample replaces `pZoneSample`.

`FinishMovement` asks for 6 with `(0, 1, 1)`. It asks for 7 with
`(0, 0, 1)` once `AirTimeSwitch` passes, after `ClearZone(0)`.

### `ClearZone`

`ClearZone(sound)` (`0x00178358`) does nothing outside a zone. Otherwise:

1. `RadialBlurOff`.
2. For the freeze and the preview, `tAutoZoneTimers[0]` is stamped,
   unless `TweakerPauseWorld` holds the world.
3. For those two and the jump cam's zones, `RestoreCameraMover`, outside
   a replay.
4. The world's time scale is reset.
5. The zone moves to `nZonePrevious`, and the muffle goes.
6. `ClearZoneSound` (`0x00178470`, which deletes the sample) if `sound`.
7. `DetermineInputMode`.

`PlayerClearZone` (`0x00177c80`) is `ClearZone(p, 1)`. It is what the
world's pause and time scale call when they run out. `FinishMovement`
clears 6 and 7 when a wheel touches down.

### In the port

`playerzone.c` has all of this. Some of it stays NULL in `main.c`:

- **The freeze and the preview.** Their movers and calls
  (`gZoneFreezeCameraMoverFn`, `gZonePreviewCameraMoverFn`,
  `gZoneFreezeDurationFn` and the three `gZonePreview*Fn`) are NULL.
  While they are, `RequestZone` refuses zones 1 and 2 before anything
  changes, as a dead button.
- **The radial blur and the zone's sound.** `gRadialBlurOn/OffFn` and
  the sample seams are NULL, so the zones are silent and unblurred.
- **The HUD.** It goes while a zone is up, as `DetermineHudFeatures`
  says (`playerhud.c`).

`tools/playerzone_check.py` runs retail's `RequestZone`, `ClearZone`,
`ClearZoneSound`, `PlayerClearZone` and `ChangeCameraMover`'s types 15
and 16 against the port. A current zone outside 0..7 indexes past the
tables on both sides, so it is not tried.

    python tools/playerzone_check.py           # 23 scenarios, 5283 ops, 24580 lines, 0 differ
    python tools/playerzone_check.py --mutate  # 198 mutations, 197 caught, 1 equivalent

The equivalent one is `z-gap-force`. Without `force`, any time under the
0.1 s gap is under the 5 s one too, which has already said no.

### On Azahar

Session 37 tested the jump cam on track 12, with
`sdmc:/nfshp2_warp.txt` (`warp.h`) set to
`4 -1346.1 413.4 -68.5 610 55`. That puts the car on the straight before
the jump the user's lap took at x = -1200. The run held the gas.

- **The zones.** The log's `race: zone` lines show 0 -> 6 at world frame
  442 with the time scale at 0.40, 6 -> 7 at 482, and 7 -> 0 at 525 as
  the car landed.
- **What it looked like.** The camera stood low at the road's edge,
  looking up as the car flew past the covered bridge, with the HUD gone.
  Zone 7 was close on the car. Then the chase camera came back with
  "HUGE AIR +250".
- **The frame rate** stayed at 30 FPS throughout.

## The rear-view mirror

Player 1's mirror is view 3 (`EVIEW_ID_PLAYER1_RVM`) drawn into render
target 7, then put on the screen at the top centre. Slice 11g-2e ports
it. The mover is in `rvmcam.c`, the draw in `trackview.c` and the
target in `georender.c`. The addresses are retail's.

### The mover

`RearViewMirrorCameraMover` (`CM_REAR_VIEW_MIRROR`, 48 bytes, vtable
`0x002b1b50`) looks back out of the player's car.

- **The constructor** (`0x00158f78`) keeps the car. Unless
  `Camera::StopUpdating` is set, it also sets the camera's
  `CarNotToRender` to the car and its `RenderDash` to 0, so the mirror
  never shows the player's own car.
- **`Update`** (`0x00158ff8`) builds the matrix from the car:
  - It moves the world on to the car's `GeometryPosition`.
  - It turns it by the transpose of `BodyMatrix`, given a quarter turn
    about x and then about y.
  - It adds `RVMOffsetInCar`, (0, 0.5, 0), to the translation, in the
    camera's own frame.
  - It sets the field of view to 20000 (110 degrees), the far plane to
    192 and the near plane to 0.75.
  - The view's shake goes on the matrix, and the camera takes it by
    `RealTimeElapsed`.
- **`GetCarToFollow`** (`0x0015fb08`) returns the car.

`Player::SetRearViewMirrorCameraMover` (`0x001767a8`) does nothing for a
player with no mirror view. In a two-player race `RearViewMirrorViewID`
is 0. Otherwise it:

1. deletes the player's mover;
2. deletes the first mover on the view;
3. makes a new one if it is turning the mirror on.

`SetHudFeatures` calls it through `gPlayerSetRearViewMirrorCameraMoverFn`
whenever `HUD_REAR_VIEW_MIRROR` changes. The HUD has that flag while the
driver's `RearViewMirror` is set and the player is not looking back
(`DetermineHudFeatures`). A SkipFE race takes `RearViewMirror` from
`SkipFERearView`, which is 1. A frontend race sets it to 1.

### The view and its target

With a mover on views 1 and 3, `eUpdateViewMode` gives view mode 2.
`MaybeChangeViewMode` then gives view 3 the mirror's 256 by 64 scissor
and makes the view and target 7 active. The cull gives the view a cull
info of its own, and `UpdateCameraMovers` moves it with the others.

Retail's `SetScreenBuffers` (`0x001064c8`) sets target 7 the same in
every video mode. The values below came from running it in mipsemu,
because the targets are `.bss` on the disc:

| Field | Value |
|---|---|
| Size | 256 by 64, PSMCT32 over PSMZ16S |
| `AspectRatioX`, `AspectRatioY` | 1.5, 1.08 |
| `AspectRatio2DX`, `AspectRatio2DY` | 0.8, 0.94 |
| `FovBias` | 1 |
| `BackgroundColour`, `ClearBackground` | `0x80000000` (black, alpha 1), 1 |

`setup_view` sets the same, but its depth is the PICA's 24 bits.
`begin_frame` makes view 3's matrices while it and its target are
active. Retail's `CalculateViewMatricies` makes them for views 0 to 9.

### The draw

Retail draws views 0 to 3 a pass at a time in `eDisplayFrame`. View 3
gets:

- the sky;
- the scenery, the NIS objects and `StuffSun`;
- the clans and the effects;
- no track routes;
- no fog, since `eattach_fog` does views 1 and 2 alone;
- `RenderCars`.

After the cars' alpha lists, `DisplayRVMImages` (`0x0010ec70`) draws the
mirror's frame over the target. It runs for view 3 alone, with both
textures, and with the view and its target active. It marks RVM_MASK
semitransparent, then draws two ePolys with the same corners:

| | V0 | V1 | V2 | V3 |
|---|---|---|---|---|
| x, y | 1, -14 | 257, -14 | 257, 76 | 1, 76 |
| u, v | 1, 0 | 0, 0 | 0, 1 | 1, 1 |

The UVs mirror the image left to right. `ApplyAspectRatio` is 0 and z is
the target's `MaxZ`. Render's half-pixel step and whole pixels put the
quad over x 1 to 256 and y -14 to 76.

Both textures are in `GLOBAL/INGAMEB.BUN`, in the pack at `0xd0b80`:

- **RVM** (`0x0000dbd4`, `pTextureInfoRVMInfo`) is 128 by 64 at 8 bits.
  It is black. Inside the glass its alpha is 0x20, a quarter tint. The
  frame is opaque, and outside it is clear. It blends by its alpha
  (AlphaBits 0x44).
- **RVM_MASK** (`0xcf29d0df`, `pTextureInfoRVMMask`) is also black, with
  an alpha of 1 inside the glass and its frame and 0 outside. It is
  added (AlphaBits 0x48), so it leaves the colour alone. The GS writes
  each fragment's alpha into a PSMCT32 target whatever ALPHA_1 says, so
  this poly leaves the mask's alpha in target 7.

`DisplayRVMs` (`0x0010edc8`) runs with view 0 after the scene, with the
Z writes off and before the HUD's layers (`0x00113af4`). It draws target
7's texture at GS (160, 20) to (352, 84) of the 512 by 448 screen. The
UVs are mirrored again, so the frame reads the right way round, and the
blend is by the target's alpha. The glass shows the view, darkened by a
quarter, and nothing shows outside the frame.

### In the port

- **`trackview_draw_mirror`** draws view 3 whole into a 256 by 64 RGBA8
  texture with a 24-bit depth buffer (`georender_mirror_*`). It runs
  after the envmap's faces and before the top screen. In order, it draws:
  the sky with the Z writes off; the scenery; the solid list;
  `render_cars` and both lists; then `DisplayRVMImages`' two polys
  (`mirror_epoly`). The mask's poly writes its own alpha into the
  target (`set_blend_source_alpha`).
- **Column 0.** The two polys start at x 1, so column 0 keeps the
  view's alpha of one. `display_rvms` puts that column at the mirror's
  right edge, where it showed as a thin dark line (TASKS 64). A third
  poly, the mask with an alpha of 0, covers x 0 to 1, so the column is
  clear like the rest outside the frame.
- **`display_rvms`** comes at the end of `trackview_draw`, before
  citro2d's HUD. It draws the texture at retail's rectangle, taken to
  the top screen's 400 by 240: (125, 10.7) to (275, 45). It blends by
  alpha.
- **The projection.** Retail's puts x at `H AspectRatioX x / z` and y at
  `H AspectRatioY y / z`, in the target's pixels. On the PS2's 4:3
  screen, the 256 by 64 shows in 192 by 64 GS pixels. The HUD takes the
  512 by 448 to the 5:3 top screen, which makes the mirror a quarter
  wider for its height. So the port's projection takes in a quarter
  more across, `1.25 * 128 / (H * 1.5)` at unit depth, and the world in
  the mirror keeps its shape. The cull's half-width, 128 / H, covers it.
- **The frame profiler** has a `mirror` stage and a third `models:` half
  (`frame-profiler.md`).

The sun, the NIS objects and the effects are not drawn into the mirror
yet. Retail's view 3 has them.

### On Azahar

The SkipFE race on track 12 shows the mirror top centre, in its frame.
The image is upright and mirrored:
the road on the car's left shows on the mirror's left. The player's car
is not in it.

The mirror draws 81 to 128 models a frame, 15000 to 17000 command words
and 45000 to 48000 indices. The view draws 225 to 313. On Azahar the
pass takes 3.7 to 5.2 ms of the CPU, and the race holds 29 to 30 FPS.
The device's cost is not measured yet. If it is too much, the fallback
is to draw the mirror every other frame.

### The check

`tools/rvmcam_check.py` with `tools/src/rvmcam_test.c` runs the mover
and `SetRearViewMirrorCameraMover` on retail's image against the port.

    python tools/rvmcam_check.py           # 7 scenarios, 2088 ops, 9863 lines, 0 differ
    python tools/rvmcam_check.py --mutate  # 52 mutations, 51 caught, 1 equivalent

## The still camera

`StillCameraMover` (`CM_STILL`, 112 bytes, vtable `0x002b1850`) looks
from a point at a point. Select Track makes one on view 1 for its
spinning track model (`docs/formats/track-select.md`), and its Tick
writes the eye and the target straight into the mover. The port is
`stillcam.c`. The vtable is the base's but for the destructor and
`Update`. The demo has the same class at `0x0015ae50`.

| Offset | Field |
| --- | --- |
| +44 | never written |
| +48 | the eye, (1, 1, 1) from the constructor |
| +64 | the target, (0, 0, 0) |
| +80 | up, (0, 0, 1) |
| +96 | the field of view (uint16), 6000 |

- **The constructor** (`0x0015e6a0`) runs the base's with `CM_STILL`,
  then writes the three vectors' x, y and z, not their fourth lanes,
  then the vtable and the field of view.
- **The destructor** (`0x0015e718`) puts its own vtable back, then runs
  the base's destructor, which puts the base's in straight after.
- **`Update`** (`0x0015e730`) builds `eCreateLookAtMatrix` from copies
  of the eye, the target and up. Unless `Camera::StopUpdating` is set,
  the field of view goes onto the camera's current key. The camera
  takes the matrix by `RealTimeElapsed`.
- **The setters** `SetFOV` (`0x0015fa80`), `SetUp` (`0x0015fa88`),
  `SetLook` (`0x0015fa98`) and `SetEye` (`0x0015faa8`) copy each vector
  whole, its fourth lane too.

### The check

`tools/selcam_check.py` runs the still mover beside the car select's
camera: the constructor, and the destructor and `Update` through
retail's vtable, with the four setters (ops K, k, u, e, l, p, f, g).

    python tools/selcam_check.py           # 12 scenarios, 4398 ops, 53228 lines, 0 differ
    python tools/selcam_check.py --mutate --only st-...  # 21 mutations, 20 caught, 1 equivalent

The equivalent one, `st-dtor-vtbl`, drops the destructor's own vtable
store: the base's destructor writes its vtable straight after, and
nothing between reads it.

## Divergences from the disc

Each of these is in the source as a comment at the point it happens.

* **The "JollyRancher" debug feed** at the top of `SetCameraMatrix` is not
  ported: if the pointer at `0x2f2870` is non-null the matrix comes from a
  network debug server with its translation row scaled by 0.01. It is null
  unless a debug server answered at boot.
* **`orbit_update` takes `elapsed` as an argument.** The image's `Update`
  reads `RealTimeElapsed` itself. The vtable's `Update` passes it, so the
  game sees the image's behaviour, and the geometry viewer and the
  checker hand in their own.

The demo port's other four are gone with the retail pass. The joystick
handlers are registered through the port's `AddJoyHandler`, `FollowChopper`
follows `World`'s `Helicopter`, `TM` is left as the allocation had it, and
`Update` makes its own `IsGameFlowPaused` test. Nothing builds a chopper
yet (task 26), so `Helicopter` is NULL and the car path is the one taken.

## Cross-check

`tools/camera_check.py` drives `tools/src/camera_test.c` and an independent
Python model -- the model written from the listings, not from the C -- through
four scenarios and diffs the transcripts line by line.

    python tools/camera_check.py            # 4 scenarios, 556 lines, 0 differ
    python tools/camera_check.py --mutate   # 35 mutations, 32 caught,
                                            # 3 equivalent, 0 unexplained

The scenarios are: the constructor and the copy constructor; ten frames of
`SetCameraMatrix` over turning, moving matrices, then the scalars moved, the
field of view wrapped both ways, the fourth column, a velocity clear and a
frozen camera; the type names over -1 .. 18 and a detached mover; and
enable/disable, which covers constructed, disabled, disabled twice,
re-enabled, enabled twice, and both under `StopUpdating`.

Its orbit scenarios went with the retail pass (`orbit_check` runs retail's
mover), and so did four of the seven equivalent mutations, which were the
orbit's. Two mutations that only a mover on a view other than 0 could catch
went to `cambase_check`. Three survive, and each has an argument for why
it must:

| mutation | why it cannot be caught |
|----------|------------------------|
| `fov-delta-signed`, `fov-velocity-rounds`, `fov-delta-reversed` | the six scalar velocities are structurally zero; see above. Every velocity record measures `fov 0`. |

An equivalent mutant left in a mutation list is a test that can never pass, so
the list names them explicitly and the runner reports "0 unexplained" rather
than "3 survived".

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

Since 7c the mover is retail's, following a stand-in `Car` whose
GeometryPosition, Position and BodyMatrix the viewer sets. Retail's
`Update` has no `AngleV` clamp (see "Retail's orbit mover"). So
`cam-elev-clamped` now shows the viewer's own clamp: after each `Update`
it holds `AngleV` to the mover's `MinAngleV` and `MaxAngleV` and stops the
vertical speed there. The viewer also destroys its mover before it builds
the next one, and in `geoview_free`. Each constructor takes nine of
EventNodeSlotPool's 96 nodes for its joystick handlers, and the pool does
not overflow, so about ten car changes would otherwise leave
`bSlotOMalloc` returning NULL. A run with `-Cars 14` (13 rebuilds) on
2026-09-30 drew all fourteen cars at 60 FPS with 0 textures missing. Its
`cam-elev-clamped` is the top-down view, not flipped over, and its zoom
creep measured 0.007/255.

The zoom hold in that script is deliberately short. Azahar ran this build at
about 139 FPS while its frame limit was off, and 1% a frame is a factor of
four in a second there (1.8 at 60 FPS) -- the eye ends up inside the car. That is the mover being per-frame, not the harness being
wrong, and it is the clearest demonstration of the frame-rate coupling that
task 28 has to decide about.

One more thing that script had to learn: Azahar's "Update Available" dialog
takes the foreground on launch and swallows every posted keypress, so a run
that ignores it presses SELECT eight times into a dialog and then reports
that the geometry viewer was never reached. It now closes any visible
top-level window of the emulator process that is not titled "Azahar" before
each attempt. `run_azahar_test.ps1` and `run_azahar_scroll.ps1` had the same
hole and got the same fix.
