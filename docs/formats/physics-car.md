# PhysicsCar

`PhysicsCar.obj` (0x00134c50 .. 0x001374d8), minus `DoSnapshot`, which
waits on the replay. Part of task 25, after every component it owns:
[RigidBody](rigid-body.md), [Steering](car-steering.md),
[Wheel](car-wheel.md), [Suspension](car-suspension.md),
[Engine](car-engine.md), [DriveTrain](car-drivetrain.md),
[Aerodynamics](aerodynamics.md), and the [PhysicsSystem](physics-system.md)
that steps them.

Ported to `3DS Files/source/physicscar.{c,h}`. Cross-checked by
`tools/physicscar_check.py` against `tools/src/physicscar_test.c`, with the
shipped image as the oracle.

## The shape of it

A PhysicsCar is what drives a Car while the car is being simulated rather
than scripted. `Car::SetMovementMode`'s MM_PHYSICS arm allocates 116 bytes
and constructs one. It owns a RigidBody, a TwoWheelAckermanSteering, four
Wheels, four Suspensions, an Engine, a DriveTrain and an Aerodynamics. All
of those except the steering and the aerodynamics are components of the
PhysicsSystem it carries, so the integrator steps them as one 50-float
state vector. The CarState it reads at construction and writes back every
step is the Car's own, `&car->State`.

Most of the object is orchestration: which component is asked what, in
which order, with whose output. The arithmetic it drives belongs to the
components. Its own arithmetic is small: the axle load split, the damping
test, the yaw boost, the brake split, and the five-pass force iteration.

## Layout

116 bytes on the PS2. Two bases, so two vptrs.

| Off | Field | Type |
|----:|-------|------|
| 0 | Mover.Driver | `CarDriver *` |
| 4 | *(Mover vtable)* | pointer |
| 8 | Vehicle | `PhysicsSystem` (a PhysicsVehicle), vptr at 20 |
| 24 | pBody | `RigidBody *` |
| 28 | pSteering | `Steering *`, a TwoWheelAckermanSteering |
| 32 | pSuspension[4] | `Suspension *` |
| 48 | pWheel[4] | `Wheel *` |
| 64 | pEngine | `Engine *` |
| 68 | pDriveTrain | `DriveTrain *` |
| 72 | pAerodynamics | `Aerodynamics *` |
| 76 | CTI | `const CarTypeInfo *` |
| 80 | State | `CarState *`, `&pCar->State` |
| 84 | pCar | `Car *` |
| 88 | BrakeStandTimer | `Timer` |
| 92 | BrakeStandTimerStart | `Timer` |
| 96 | BrakeStanding | `int32_t`, a bool |
| 100 | ThrottleReleased | `int32_t`, a bool |
| 104 | LurchsLeft | `int32_t` |
| 108 | FrictionBoost | `float` |
| 112 | YawControlMultiplier | `float` |

The names are the mdebug record's, except for the two bases, which it
leaves unnamed. Every pointer widens the host struct by four bytes. The
header asserts each offset as `PS2 offset + k * slack`, where k counts the
pointers ahead of the field plus CarMover's tail padding.

### Four tables

| Table | Address | Entries |
|-------|---------|---------|
| `_vt$8CarMover` | 0x002923e0 | dtor 0x00134c58, Move `__pure_virtual`, DoSnapshot 0x0012f1e8 (`jr ra`) |
| `_vt$10PhysicsCar` | 0x00292708 | dtor 0x001357a8, Move 0x00135c78, DoSnapshot 0x00135580 |
| `_vt$10PhysicsCar$14PhysicsVehicle` | 0x002926e8 | the same dtor, ComputeAuxiliaries 0x00135828, ResolveForces 0x00136cc8 |
| `_vt$14PhysicsVehicle` | 0x00292728 | `~PhysicsVehicle` (a `j` to ~PhysicsSystem), PhysicsSystem's own two |

Every entry of the vehicle table carries a delta of -8, so the PhysicsVehicle
pointer the integrator calls through arrives as the PhysicsCar. In the port
the delta is `-offsetof(PhysicsCar, Vehicle)`: -8 on the 3DS, -16 on the
64-bit host. DoSnapshot is a NULL entry until the replay is ported;
`vt_slot` aborts on a NULL entry.

## The constructor

0x00135240. Every field is written. The order matters, because the
component list's order is the state vector's order:

1. CarMover's vptr, then the PhysicsSystem, then PhysicsVehicle's vptr.
2. The fields, then both vptrs again, this time as PhysicsCar's.
3. The RigidBody, added to the list, then its IsHP (from the argument
   CTI's HighPerformance) and its SpeedLimiter (through the field).
4. The steering. It is inlined in the image and is `ackerman_init` here.
5. For each corner, a Wheel then a Suspension, both constructed before
   either is added. The wheel gets `Tires[i / 2]` and the suspension gets
   `Suspension[i / 2]`. Only the front two suspensions get the steering.
6. The sway bars, 0 with 1 and 2 with 3.
7. The Engine, added, then its IsHP. Then the DriveTrain, added.
8. The Aerodynamics, which is inlined in the image and is not a component.
9. Calibrate, InitializeStateFromCar and ComputeAuxiliaries, called
   directly rather than through the tables.
10. YawControlMultiplier 1, ThrottleReleased 1, LurchsLeft 2 and
    BrakeStanding 1.

## The destructor

0x001357a8. Both vptrs go back to PhysicsCar's. The steering is destroyed
through its own table with flags 3, and the Aerodynamics is given back to
its pool without a null check. Then ~PhysicsVehicle runs with flags 0,
which destroys every component the system owns. Last is ~CarMover with the
caller's flags, which frees the 116 bytes.

## Calibrate

0x00135690. The body is calibrated about the CTI's centre of gravity and its
inertia tensor recomputed. Then the static load is split between the axles:

```
cog   = UseNewSuspensionCalibration ? CTI.CenterOfGravity.x : 0
a     = Wheels[0].PositionX - cog,   b = Wheels[3].PositionX - cog
rear  = (a / (a - b)) * 0.5,         front = 0.5 - rear
load  = Mass * 9.8 + AutoBalanceDownforce * downforce(ForwardSpeed)
```

Each front Suspension is calibrated with `load * front` and each rear one
with `load * rear`. Then all four Wheels are calibrated.

## ComputeAuxiliaries and BottomOut

0x00135828 runs the system's own ComputeAuxiliaries, then BottomOut, then
**ResolveForces through the vehicle's vptr**, slot 24.

BottomOut (0x00135970) does three things:

- It applies a penalty impulse at every corner whose suspension sits
  exactly on its bump stop (`c.eq.s`), and adds the magnitude into
  `WheelBottomOutMagnitude`.
- It fires the debug bounce, 25 up at the centre of mass. That happens
  only when `TriggerBounce` is set and the car is player-controlled
  (`REAL_CONTROL`), and it clears the trigger.
- It damps the car if CheckDampingSuitability asks for it.

CheckDampingSuitability (0x00135878) returns one of three answers:

- **No damping** if the throttle is over 0.3.
- **No damping** if the speed or the spin is over 0.7.
- **No damping** if the body is tipped more than 0.25 on either axis (the
  z of R.v0 or R.v1).
- **Damp** (P, L and every wheel's spin times 0.95) if the speed or the
  spin is over 0.25.
- **Stop dead** (P, L and every wheel's spin set to zero) otherwise.

If any of them fired, UglyTimestepHack is cleared and the system's
ComputeAuxiliaries runs again.

## YawFrictionBoost

0x00135b70, a free function called only from Move:

```
base    = |tilt| + 1                      (*tilt is replaced by |tilt|)
control = yawControl + (driverMode ? postCollisionBoost * NFS : NFS)
handbrake over 0.5 and |yaw| under 20 degrees: return base
t       = Low + (High - Low) * ((speed - LowSpeed) / (HighSpeed - LowSpeed))
return base + min(|yaw| * control * t, MaxYawBonus)
```

`t` is not clamped at either end, so a speed outside the band extrapolates.

## GetBrakeSettings

0x00135c20. Wheels 0 and 1 get `BrakeBias * 2`. Wheels 2 and 3 get
`(1 - BrakeBias) * 2`, which the image computes in double (`fptodp`,
`dpsub`, `dpadd`, `dptofp`) and rounds back once. The port does the same
in C doubles.

## InitializeStateFromCar

0x00136bb8. The body takes the CarState's position, matrix, velocity and
angular velocity. Each corner's Suspension takes its state, and each Wheel
its angle and spin. The engine's spin is `RPM * pi/30`, unless TestRPM
holds something other than its shipped 100, in which case that is used as
the RPM. The drivetrain gets clutch 1, the CarState's gear as both current
and desired, and the clutch engaged.

## ResolveForces

0x00136cc8:

1. It reads the ticker (t0) and bumps the resolve counter.
2. It calls the body's ResolveForces through its table. That is `jr ra`,
   but the call is made.
3. It resolves the aerodynamics. The downforce that comes back is fed to
   each Suspension's first pass times 0.25 when UseMagicForce is set, and
   as 0 otherwise.
4. It reads the ticker again and **discards** the result.
5. It runs IterateForces. IterateTime is measured from t0, not from the
   discarded read.
6. It runs each Suspension's second pass, then JumpStabilizer. ResolveTime
   is measured from t0 too.

## IterateForces

0x00136df8. The tyre forces, solved against what the body's acceleration
makes of them:

```
GuessClutchTorque; each wheel GuessGroundForce
local = R^T * ForceAccumulator          (bMulMatrixVec3, w forced to 1)
5 times:
    acc = local, yaw = 0
    each wheel:  f = its horizontal ground force in the car frame
                 acc += f               (vadd.xyzw)
                 yaw = (yaw + rest.x * f.y) - rest.y * f.x
    a   = acc.xy / Mass
    yaw = yaw / (1 / I_body_inv[2][2])
    each wheel neither slipping nor locked:
                 ModifyGroundForce(a.x - yaw * rest.y, a.y + yaw * rest.x)
    ModifyClutchTorque
each wheel FinalizeGroundForce(i); FinalizeClutchTorque
```

`rest` is each Suspension's RestPosition. The call the listing makes is
`bMulMatrixVector`, RigidBody.obj's private one. That is an 8-byte `j` to
bMulMatrixVec3.

A wheel that is locked but not slipping is one whose lock outlived the
frame that set it. CheckForBrakeLock sets Slipping whenever it locks, and
GuessGroundForce skips it only when the contact patch has no velocity (or
no slip and no lateral velocity). Such a wheel keeps the force it guessed.

## UpdateCar

0x00137038 copies the simulation back into the CarState. `dt` is not read.

- **Position, velocity and angular velocity** are copied as whole quads,
  pad lane included. The geometry position is recomputed, MatrixValid is
  cleared, and VelocityMagnitude is the body speed's `sqrt`.
- **Angle** is `bFixATan2` of the forward axis's x and y, each scaled by
  65536 and truncated by `cvt.w.s` (eefpu.h's `ee_trunc_w`).
- **SteeringAngle** is the driver's. **ForwardSpeed** is the velocity
  dotted with the forward axis.
- **Each wheel's** spin, angle, traction usage, slip, z force and terrain
  are copied, and so is its touching-ground flag. Its road noise is copied
  only while it touches the ground. The suspension height is clamped to
  MaxRenderingCompression by adding the (non-positive) difference.
- **Throttle** is `Throttle * ThrottleOverride`. Also written are the
  current gear, whether the clutch is engaged, and the RPM as
  `w * 30/pi`.
- **SkidLeft/SkidRight** are the worse slip of each side's two corners
  (3 and 0 on the left, 2 and 1 on the right), over SkidNormalize, capped
  at 1.
- **TractionUsage** is the four wheels' mean. Then the wheel matrices are
  recomputed.

## Move

0x00135c78, slot 16 of the Mover's table, once a frame with the frame's
`dt`. It returns `dt`.

1. **SetBoost** with the car's BoostFactor, then **Calibrate**.
2. **The pedals are tidied**, in the driver's own fields. With the throttle
   over both the brake and the handbrake, a brake or a handbrake under 0.5
   is dropped to 0. Otherwise a throttle under 0.5 is.
3. **The controls go in.** SetSteering gets the driver's BAM and the engine
   the throttle. SetSportGear's answer is dropped. A driver's NitroFlag
   lights the engine's and stamps NitroBoostTimer with the world time, then
   DecrementNitro runs either way. The driver's NitroFlag is cleared, its
   DesiredGear becomes SetDesiredGear's answer and its SportGear the
   gearbox's.
4. **MotionDamping** is off with the throttle over 0.3, or with all four
   wheels down and `|R.v0.z|` over 0.15; on otherwise.
5. **The friction boost** starts as FrictionBoost, times NFSAdjust (0.85) in
   NFS mode. WheelBottomOutMagnitude is cleared, 3 down to 0.
6. **The burn-out**, below, for a REAL_CONTROL car whose port is not a
   wheel (IsJoystickTypeWheel: types 21, 22 and 35).
7. **YawControlMultiplier** winds down at 20 a second to 0.5 while the
   handbrake is at 0.5 or more, and back up at 1 a second to 1.
8. **Each wheel's brakes and traction**, below.
9. **The aerodynamics** get the throttle, and a ground effect of a quarter
   per wheel down.
10. **MaxMomentZ** is the CTI's MaxZMomentAcc in NFS mode. In HP mode it is
    MaxZMomentAccExtreme, and when that is 0 it becomes 20 while the car
    yaws more than 0.1 against its spin (`yaw * L.z < 0`).
11. **The speed limiter** is off (0) under nitro, 60 with a blown tyre, and
    otherwise the CTI's times `1 - 0.03 * VisibleTotalDamage`. The damage
    test is on `pCar != NULL`, after pCar has been used a dozen times.
12. **The sub-steps**, below.
13. The dyno's three display timers count down by WorldTimeElapsed while
    they are positive and the dyno is on. Then **UpdateCar(dt)**, and
    MaybeMakeSkids(dt) on every wheel if the car's visual effects are
    generated (it is rendering, not poofed, and not traffic).

### The burn-out

A running burn-out (BurnOutState 1 or 2) counts BurnOutTime down by
WorldTimeElapsed. It ends when the time runs out, when `|yaw|` passes
BurnOutYawCancel (0.3), or when every wheel's AppliedTorque has been under
BurnOutCancelTorqueValue (1) for longer than BurnOutAllowTime (1/6 s). A
wheel over it resets that allowance to 0. Nothing else happens that frame.

A new one needs HP mode, the wheel straight (BAM 0), a speed strictly
between 0 and BurnOutMaxSpeed (15 mph), `|yaw|` under BurnOutYawMax
(pi/16), and a wheel over BurnOutTorqueValue (1.5). The rear pair is looked
at first:

| Over 1.5 | Wheel | State |
|----------|-------|-------|
| 2 or 3, and w3 < w2 | 2 | 1 |
| 2 or 3, otherwise (a tie too) | 3 | 2 |
| 0 or 1, and w0 < w1 | 1 | 1 |
| 0 or 1, otherwise | 0 | 2 |

The state is stored before the car's IsBlinking is asked, so a blinking car
keeps the new state with the old BurnOutTime and BurnOutTraction. Otherwise:

```
t     = min((AppliedTorque - 1.5) / (3 - 1.5), 1)       BurnOutTorqueValueClip 3
tr    = 0.4, times 1.25 unless both rear terrains' StaticFrictionMultiplier is 1
BurnOutTime     = BurnOutMinTime (1)
BurnOutTraction = tr + (mph / 15) * (1 - t) * (1 - tr)
```

State 1 multiplies wheels 0 and 3's traction boost by BurnOutTraction, and
state 2 wheels 1 and 2's.

### The brakes and the traction, per wheel

```
Brake  = driver.Brake * BrakeSettings[i]       while racing, or brake-standing
                                               on wheels 0 and 1; else 0
eb     = driver.EBrake * EBrakeSettings[i]     {0, 0, 1, 1}
         NFS mode: + 0.7 over 0.2
         HP mode:  + 0.5 over 0.2 with |yaw| over 0.3 and under 80 mph
TractionBoost = boost, times BurnOutTraction on the burning pair,
                times 0.4 with any tyre blown, else times the override if set
```

BrakeSettings is {1, 1, 0.6, 0.6} in .data at 0x002e8550 -- not
GetBrakeSettings's answer, which nothing in Move asks for. At wheel 2 the
boost itself is multiplied, for wheel 2 and wheel 3 both, by
`ym * (YawFrictionBoost(...) - 1) + 1`, with wheel 2's handbrake, the
speed's magnitude and the post-collision yaw boost.

**One blown tyre cuts all four.** The per-wheel test is `(1 << i) != 0`,
which always holds, so any bit of BlownTireBits takes the 0.4, and the
traction override is never applied to a car with a blown tyre. After the
loop a damage boost override goes through SetBoost unless a tyre is blown.

### The sub-steps

```
n    = cvt.w.s(dt / MaximumTimeStep) + 1        MaximumTimeStep 0.0044
step = dt / n
```

The `+ 1` comes after the truncation, so a `dt` of exactly n steps takes
n + 1, and the add wraps as `addiu` does. Each sub-step:

1. With the dyno on, or before the race, SpeedDebugX and SpeedDebugR take
   the body's X and R.
2. UglyTimestepHack = step, IntegrateEuler(step), and R is orthonormalised
   in place. The debug prints are no-ops in the port.
3. Before the race: the brake-stand. In it: the dyno, or with the dyno off
   the dyno's idle (all three times 1, nothing on show, the start time now).

### The brake-stand

From PRERACE on, the front brakes hold the car. A throttle over 0.5, after
a release and with a lurch left, lets it go for a random time: `(r + lo) *
4000` ticks, where r is bRandomF(lo) and lo is 0.25 for the first lurch and
0.5 for the second. The constructor gives two. The brakes come back when the
timer runs out or the throttle is let go. While the car is brake-standing,
the body's momentum P is zeroed every sub-step: three words are stored, and
the fourth is stack.

### The dyno

SpeedDebugInfo, off in the shipped build. Under 0.8 mph it resets. Past 60
and past 100 mph it stamps the time since the start and shows it for 30
seconds. Until the quarter mile is timed, it adds the distance from the
saved X to the body's. Past 400.5 m it stamps the time and the speed. Then
the body is put back at the saved X, at the height it reached, so the car
runs on the spot.

## The small ones

- **SetBoost** (0x00137340) puts the catch-up multiplier into the engine,
  the body, the aerodynamics and every wheel, and sets the aerodynamics'
  draft to `1 - Car.DraftFactor`.
- **JumpStabilizer** (0x001373a0) applies a moment against the spin when
  fewer than two wheels are down. The moment is `-Mass *
  JumpStabilization(|w|) * w`, all four lanes.
- **SetFrictionBoost** (0x001374c8) is `jr ra ; swc1 $f12,108(a0)`.
- **The static initialiser** (0x00137438, `__CTOR_LIST__[15]`) builds
  JumpStabilization from (0, 0), (0.4, 0), (2, 20) in .bss. It also sets
  YawLockThreshold to five degrees.

## Uninitialised stack, and the port's choice

The image leaves words of stack in six places, and each time the port
writes zero:

| Where | What |
|-------|------|
| BottomOut, the bounce | the w lanes of the impulse and of its point |
| BottomOut, stop dead | the fourth word of the quad copied into P and L |
| RigidBody::ComputeAuxiliaries | the w of the quad that clears both accumulators and carries gravity, and gravity's point's w |
| Aerodynamics::ResolveForces | the drag point's w |
| PhysicsSystem::IntegrateEuler | the three derivative slots RigidBody never writes |
| Move, the brake-stand | the fourth word of the quad that zeroes P |

All but the integrator's only reach w lanes, which nothing reads back into
an xyz lane. The integrator's reaches RigidBodyState's tail padding: it
advances all 32 of the body's words in place, and the body's
GetDerivative writes only 29 of them. The port clears the integrator's
array (see [PhysicsSystem](physics-system.md#integrateeuler)).

## Cross-check

```
python tools/physicscar_check.py            # 106 scenarios, 102908 lines, 0 differ
python tools/physicscar_check.py --mutate   # 263 mutations, 257 caught, 6 equivalent
```

**The oracle is the shipped code.** Every other class in the car has a
checker that models its arithmetic in Python. PhysicsCar cannot sensibly
be modelled that way: a model of its orchestration would be a second port
of the whole car. It would agree with the first for the same reasons the
first was wrong.

So `mipsemu.Emu(ieee=True)` loads NFSHP2.ELF and runs PhysicsCar's
constructor, both integrators, UpdateCar and the direct calls straight
from the instruction stream. That includes every component method they
reach, the VU0 macro code in the matrix library, and the soft-float
doubles. It runs them on a Car and a CarDriver laid out in emulated
memory. The harness does the same with the port, and both print every
field of every object the car owns.

The dump is generated from the port's headers, and every offset is checked
against the mdebug record before anything runs. The terrain, the allocator
and the ticker are stubbed identically on both sides, and so are the skids
(MaybeMakeSkids logs its wheel and dt). The race is a zeroed block whose
first word is the stage, and the driver a RealDriver so Move can read its
Port. The joystick table and BodyDamage are the ported ones, checked
directly. The model zeroes the image's uninitialised words (the table
above) on the instruction before each is first read, which is what the
port's choice amounts to.

**Move starts from a framed car.** The Ackerman matrices are zero out of
the constructor, and the constructor frames the wheels from them, so a car
already moving when it reaches its first Move has front wheels with no
frame. The game's cars reach Move from rest. These scenarios start at
speed, so both sides set the steering and run ComputeAuxiliaries once
first.

The four CTI records come from GLOBALB.BUN: the Corvette, the BMW M5 cop,
the fire truck, and CORVETTEHP, the first record with HighPerformance set.

### What running the shipped code found

**Wheel::GetLateralForce's curve scale is 12, not 11.** `lui at,0x4140` is
12.0. The port and wheel_check's model both read it as 11, so they agreed
with each other and wheel_check passed. Every tyre-curve index came out
11/12 of the image's. The first sign was a driven wheel's AppliedTorque
one ulp off in the constructor's dump. The path back went through
ModifyClutchTorque, the differential's acceleration, the rear wheels'
GroundForce[0] and GuessGroundForce's lateral force, to the index. Fixed in
wheel.c and in wheel_check's model, which now has a mutation for it
([Wheel](car-wheel.md)).

**Wheel::CheckTerrain refreshes the wheel's terrain.** The `move` read
as a NULL terrain out-parameter is the fifth argument; `a2` arrives holding
the wheel's own `Terrain`, and GetElevation writes through it. Caught while
re-reading raw words to plan this oracle; the port, the model and the
stand-in now all agree with the image ([Wheel](car-wheel.md)).

**IntegrateEuler writes RigidBodyState's padding.** RigidBody's own
checker documented the three words as never moved, which is true of
GetState and SetState but not of the integrator.

**A car sitting in gear divides zero by zero.** DriveTrain splits the
clutch torque across each pair by `w / (w + w')`. Both wheels of a driven
pair standing still make that 0/0, and so does the front pair of any
rear-drive car, which is split too with a torque of 0. The EE answers
FLT_MAX, signed by the XOR of the signs; the clamp turns that into the small
share and the car sits still. IEEE answers NaN, and the NaN goes on through
AppliedTorque, the wheels and the body: every car on the grid would vanish
on its first frame. mipsemu's `eediv` now divides by zero the EE's way and
records each `div.s` that does. The two share divides in ApplyClutchTorque
are the only ones any scenario reaches. The port spells them with
`ee_div` from eefpu.h, and drivetrain_check has an `ac still` scenario and a
mutation for it ([DriveTrain](car-drivetrain.md)).

**The joystick table is two bytes.** CurrentJoystickTypes is one byte per
port, and GetJoystickType reads it with `lbu` and no bounds check. The six
bytes after it up to bShakeTest are alignment.

**Three w lanes were stack.** RigidBody's and Aerodynamics' ports had
already chosen zero for them. They only showed up once both components ran
together under an integrator that carried the lanes from step to step.

### What the mutation pass found

The first pass left 16 of 263 mutants alive. Six are equivalent, each for
a reason checked in the image (the `EQUIVALENT` table has them):
~PhysicsSystem restores the vtable a dropped store would have; the rear
brake split rounds the same in float as in the image's double for all 2^32
inputs; RigidBody::ResolveForces and SetSliderValue are empty; ResolveTime
and IterateTime are never read; and UpdateCar never reads `dt`. The other
ten were holes in the scenarios:

- **Locked and gripping is out of a scenario's reach.** The first force
  pass comes after IntegrateEuler has moved the body on the constructor's
  derivative, so by then no contact patch is still. The exception is the
  front pair before its first frame, and there CarMatrix is zero, which
  makes ModifyGroundForce's correction zero too. `s_lock` stills the
  patches by hand and calls IterateForces directly.
- **The first frame hides the yaw boost.** VelocityMagnitude is 0 until
  UpdateCar has run, so on a scenario's first frame YawFrictionBoost's
  speed ramp is 0, and so is its bonus. The collision boost was multiplied
  by zero in every scenario that had one. `mv-collided-hp-slide` slides
  into a second frame.
- **`atq` of all zeros writes nothing.** The two lull scenarios kept the
  torques the constructor's Calibrate left, which are over
  BurnOutCancelTorqueValue, so neither lulled. They now use small torques.
- **Gear 1 is NEUTRAL.** SetSportGear refuses it, and that was the only
  SportGear any scenario asked for. SPORT_SHIFT had never been asked for,
  and it is the only request SetDesiredGear can answer with something
  else: AUTOMATIC, after ten seconds in the gear it chose.
- **The nitro lasts four seconds**, longer than any scenario ran.
- **The burn-out's pairs** were only tried with both wheels over
  BurnOutTorqueValue, or both under.
- **Three wheels down** comes from UpdateCar, not from `touch`. A tilted
  car at 0.875 lands on three after one frame.
- **The dyno's restart** had only ever happened at WorldTimer 0.
