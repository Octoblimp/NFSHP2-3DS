# `Camera.obj` and `CameraMover.obj` -- where the view comes from

Two objects, and they divide the work cleanly. A `Camera` never decides where
it is: it is handed a matrix once a frame and pulls everything else out of it.
A `CameraMover` is what hands it that matrix, and there are eighteen kinds.

    Camera.obj        0x00153a20 .. 0x00154380     2.4 KB
    CameraMover.obj   0x00154380 .. 0x0015c4d0    32.3 KB, of which this
                                                  covers the base class,
                                                  CM_ORBIT_CAR and CM_DRIVE
                                                  but its Update; see "The
                                                  drive camera"
    the shake         0x00152860 .. 0x001539f4    the camera half; see
                                                  "The camera shake"

The port is `3DS Files/source/camera.c` and `3DS Files/source/cammover.c`,
cross-checked by `tools/camera_check.py` (1251 transcript lines, seven of
its mutations equivalent and argued for below) and, for what retail
changed, by `tools/cambase_check.py`, which runs retail's own code (see
"Retail" below). `drivecam.c` has the drive camera, cross-checked by
`tools/drivecam_check.py` on retail's image. Most addresses here are the
demo's; "Retail", the shake and the drive camera have retail's. It sits on
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

## Retail

The port follows retail's `Camera` and `CameraMover` base; the orbit mover
is still the demo's until the car selector needs it (step 16). Retail has
no symbols, so the names of what is new are the port's. `gp` is
`0x003358f0` there.

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
    python tools/cambase_check.py --mutate   # 59 mutations, 59 caught

`camera_check` keeps its independent model of the same code, updated to
retail's. It has no mutation that sets `ClearVelocity` in the constructor:
the constructor's two `SetCameraMatrix` calls clear the flag whatever it
held, so only a camera built while frozen can show it, and `cambase_check`
builds one.

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
envelopes), and the replay's `SnapshotCameraShakers` (`0x001564d0`) and
`tShaker::DoSnapshot` (`0x00156220`). Two calls wait:

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
and `CameraMover.obj`'s biggest class. `drivecam.c` has every member but
`Update` (`0x0015c880`, 6056 bytes) and the helpers only `Update` calls,
which are step 7b's. The vtable's `Update` stays the base's until then, and
it does nothing. `camerainfo.h` lays out the car type's `CameraInfo` and its
`POV`s. The addresses are retail's.

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
| `0x0015c680` | `GetLookbackCar`, 7b's |
| `0x00157930`, `0x00157b60` | the wall helpers `Update` calls, new in retail and unnamed; 7b's |
| `0x00157c60` | new and unnamed: `BumperCameraMover::Update` calls it, and it calls both wall helpers |
| `0x0015c708` | `GetAccelLag`: nothing calls it or points at it |
| `0x0015e028` | `GetBoomDistToWall`, and `DistanceToLineSegment` and `IntersectLineSegments` after it: the same, dead in retail |
| gp-31028 | `0.7`, the wall gap looking ahead |

**The record** is 1008 bytes in retail. Its fields and names are the demo's
`.mdebug` record (864 bytes), and everything from `TheTopologyCoordinate` on
is 144 bytes further on, because retail's `TopologyCoordinate` is 704 bytes
to the demo's 560. So `DisableLag` is at 884 and `PerfectFocus` at 992. The
port's own offsets still differ from there on, since its
`TopologyCoordinate` is the demo's. Nothing reads a drive camera in place.

**The constructor** is `(viewID, car, povIndex, lookbackSpeed, disableLag,
lookBack, perfectFocus)`. It runs the base's for `viewID` and `CM_DRIVE`,
zeroes the look back and the boom's last yaw and pitch, and takes the car's
yaw (`State.Angle`) and pitch (`bASin` of `BodyMatrix.v0.z`, masked to 16
bits). It builds the `TopologyCoordinate`, stores the three arguments,
clears the acceleration lag, its twenty samples and its timers, and sets
`CamAdjustMultiplier` and `TouchingGroundFactor` to 1. `lookBack` sets
`DesiredLookBackParam` to 1 or 0. `LastCarSpeed` is
`State.VelocityMagnitude`. Unless `Camera::StopUpdating` is set, it clears
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
`TopologyCoordinate`, `LastCarSpeed` from `VelocityMagnitude` where the
demo read `ForwardSpeed`, `GetTarget` from `GeometryPosition` where the demo
used `Position`, and the fallback `CameraInfo` read inline where the demo
called `GetCarTypeInfo(0)`.

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

**Waiting**: `Update`, `GetLookbackCar` and the two wall helpers are 7b's.
`Player::ChangeCameraMover`, which builds the mover for each view, is 7c's.
Until 7c nothing builds a drive camera.

### The drive camera, cross-checked

`tools/drivecam_check.py` runs retail's code in `mipsemu`: the constructor,
the destructor through the vtable, `ResetState`, `SetPOVIndex`, every
vtable slot but `Update` and `Render`, the three corrections,
`CalculateLookbackAngle` and the out-of-line accessors. They run over the
base, the `Camera` constructor, `bASin`, `bATan` and retail's own `eView`
table. `tools/src/drivecam_test.c` runs the port over the same script.

Only `TopologyCoordinate`'s constructor and destructor are stubs. They print
which mover called them, and what they would write is left to their own
checker. Every camera, mover, car, car type and player starts from a `0xa5`
fill, so what a call leaves alone shows.

The script is built to reach three things:

- **The look back.** The players' `Lookback` words take 0, 1, 2 and -1, and
  23 of the 393 queries count a look back.
- **`CalculateLookbackAngle`'s thresholds.** Inputs exactly on ±0.7071 and on
  a 0 side. A search also builds directions within 1e-6 of the threshold,
  where adding the squares in another order, the dots in another order, or
  dividing instead of multiplying by the reciprocal would cross it. It finds
  four inputs for each of the three.
- **`ResetState` against Update's state.** Before most resets the walk
  scribbles distinct words over every field only `Update` writes, standing
  in for the frames 7b will run. Without that, those fields are still the
  constructor's 0s and 1s, and dropping any of their resets changes nothing.

    python tools/drivecam_check.py            # 8 scenarios, 2941 ops, 7406 lines, 0 differ
    python tools/drivecam_check.py --mutate   # 149 mutations, 146 caught, 3 equivalent

The three equivalent mutants:

- **Not setting the vtable in the destructor.** The base's destructor, run
  next, sets its own, and nothing reads it in between.
- **Dropping the 16-bit mask on the pitch, in the constructor and in
  `ResetState`.** The image masks `bASin`'s result (`andi 0xffff`), and the
  cast mirrors that, but the port's `bASin` already returns `r & 0xffff`.

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

    python tools/camera_check.py            # 7 scenarios, 1251 lines, 0 differ
    python tools/camera_check.py --mutate   # 59 mutations, 52 caught,
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
