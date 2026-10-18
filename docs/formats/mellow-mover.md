# MellowMover

`MellowMover.obj` (0x00206448 .. 0x002086f8): MellowMover and the
Mellovator it drives. The two `DoSnapshot`s came with the replay, TASKS
72c. Part of task 25, after [PhysicsCar](physics-car.md), whose bases
and table layout it shares.

Ported to `3DS Files/source/mellowmover.{c,h}`. Cross-checked by
`tools/mellowmover_check.py` against `tools/src/mellowmover_test.c`. The
oracle is retail's image since TASKS 74 (retail's object is 0x00219628 ..
0x0021b910). The addresses below are the demo's; retail's four changes
are in [Retail's changes](#retails-changes-tasks-74).

## The shape of it

A MellowMover is the cheap car. A PhysicsCar integrates a RigidBody, four
Suspensions, four Wheels, an Engine and a DriveTrain as one 50-float state.
A MellowMover's PhysicsSystem holds two components, a RigidBody and a
Mellovator, and the Mellovator does the rest in closed form:

- **The suspension** is a spring, damper and sway-bar force, from a ground
  query each step.
- **The engine** is two table lookups.
- **The gearbox** is a pair of shift tables.
- **The tyres** are a linear slip model inside a friction circle.

The Mellovator's state is the four wheels' angular velocities and nothing
else, so the system's state is the body's 29 floats plus 4.
`Car::SetMovementMode` builds one for the cars the game does not need to
simulate properly: traffic, and AI cars far from the camera.

The four Wheels are not components. They exist so the car has something
to render and skid with. UpdateCar places them from the Mellovator's
answers, and nothing integrates them.

## Layouts

### Mellovator, 448 bytes

A PhysicsComponent: bNode and vptr in the first twelve bytes. Its
constructor never calls PhysicsComponent's. It stores its own vptr and
leaves the links to the pool's zeroed slot and to AddComponent.

| Off | Field | Type |
|----:|-------|------|
| 0 | pNext, pPrev | bNode |
| 8 | *(vtable)* | pointer |
| 12 | pBody | `RigidBody *` |
| 16 | CTI | `const CarTypeInfo *` |
| 20 | TC | `TopologyCoordinate *`, the CarState's |
| 24 | State | `MellovatorState`, `ww[4]` in rad/s |
| 40 | SuspensionPosition[4] | `float` |
| 56 | SuspensionVelocity[4] | `float` |
| 72 | SuspensionForce[4] | `float` |
| 88 | TouchingGround[4] | `int32_t`, a bool |
| 104 | WheelForce[4] | `bVector2`, body frame |
| 136 | WheelSlip[4] | `bVector2`, longitudinal and lateral |
| 168 | bSlipping[4] | `int32_t`, a bool |
| 184 | BrakeLocked[4] | `int32_t`, a bool |
| 200 | GroundPenetration[4] | `float` |
| 216 | *(8 bytes nothing reads)* | |
| 224 | GroundNormal[4] | `bVector3` |
| 288 | RPM | `float` |
| 292 | CurrentGear | `Gear` |
| 296 | Throttle, Brake | `float` |
| 304 | Steering | `uint16_t`, a BAM (`sh` / `lhu`) |
| 308 | DesiredGear | `Gear` |
| 312 | CurrentBoost, CurrentFrictionBoost | `float` |
| 320 | RestLoad[4] | `float` |
| 336 | TorqueCurve, EngineBraking | `Table` each |
| 376 | ShiftUpRPM[9], ShiftDownRPM[9] | `float` |

### MellowMover, 64 bytes

| Off | Field | Type |
|----:|-------|------|
| 0 | Mover | `CarMover`: Driver at 0, vptr at 4 |
| 8 | Vehicle | `PhysicsSystem` (a PhysicsVehicle), vptr at 20 |
| 24 | pBody | `RigidBody *` |
| 28 | pMellovator | `Mellovator *` |
| 32 | pAerodynamics | `Aerodynamics *` |
| 36 | CTI | `const CarTypeInfo *` |
| 40 | State | `CarState *` |
| 44 | pCar | `Car *` |
| 48 | pWheels[4] | `Wheel *` |

The mdebug record names every field except the two bases and pMellovator,
which it lists among the methods. On the host each pointer widens a record
by four bytes and each Table by four more. The headers assert every offset
as `PS2 offset + k * slack`.

### Three tables

| Table | Address | Entries |
|-------|---------|---------|
| `_vt$10Mellovator` | 0x0029f2c8 | the empty header, dtor 0x002085d0, GetSize 0x002086b8, GetState() 0x002086b0, GetState(float *) 0x00208688, SetState(float *) 0x00208660, ResolveForces 0x00207cb8, GetDerivative 0x00207460, ComputeAuxiliaries 0x002076a8 |
| `_vt$11MellowMover` | 0x0029f330 | the empty header, dtor 0x00206608, Move 0x00206b28, DoSnapshot 0x002066e0 |
| `_vt$11MellowMover$14PhysicsVehicle` | 0x0029f310 | the empty header, the same dtor, ComputeAuxiliaries 0x00206cb8, ResolveForces 0x00206d30, all at delta -8 |

Each entry is eight bytes: a delta, an index and the function. The
vehicle table's delta turns the PhysicsVehicle pointer back into the
MellowMover. On the host it is `-offsetof(MellowMover, Vehicle)`.

MellowMover's DoSnapshot (retail 0x002198c8, the demo's 0x002066e0) is
slot 24 since TASKS 72c: a section begun with the object, then the
RigidBody, the Mellovator, the Aerodynamics, the four Wheels and
CarMover's (nothing). The Mellovator's DoSnapshot (retail 0x0021a3d8, the
demo's 0x002071b8) is not in its table at all: the nine entries end at
ComputeAuxiliaries, and MellowMover's calls it directly. Its gears and its
grounded and locked flags go as signed low bytes.

## Mellovator

### Construction and destruction

The constructor is at 0x00207048. The image first runs three bVector array
constructors, each a four-pass loop of nops that stores nothing. Then it
writes:

1. The vptr.
2. TorqueCurve over the engine's nine torque entries and EngineBraking over
   its three, both from IdleRPM to MaxRPM.
3. The CTI, and the shift points at scale 1.
4. pBody and TC, CurrentBoost 1 and CurrentGear FIRST_GEAR.

Everything else is the pool's zeroes.

The destructor, 0x002085d0, stores the vptr, calls
`~PhysicsComponent(this, 0)`, and frees to MellovatorSlotPool when
`flags & 1`.

### Calibrate

0x002073a0. It splits the car's weight, plus the aero's balance downforce,
between the axles and halves it across each:

```
cog   = UseNewSuspensionCalibration ? CTI.CenterOfGravity.x : 0
a     = Wheels[0].PositionX - cog,   b = Wheels[3].PositionX - cog
load  = Mass * 9.8 + AutoBalanceDownforce * downforce
rear  = (a / (a - b)) * 0.5,         front = 0.5 - rear
RestLoad[3], [2] = load * rear;  RestLoad[1], [0] = load * front
```

This is PhysicsCar's split, into four floats instead of four Suspensions.

### The state

SetState(ffff) (0x00207418) stores the four speeds, then clears
BrakeLocked and SuspensionPosition in one loop. The virtual GetState and
SetState copy `ww` as two doublewords, and GetSize is 4.

### GetDerivative

0x00207460. A locked wheel's derivative is 0. For any other wheel:

```
rear only:  rpm   = RPM / CurrentBoost
            tq    = Throttle * TorqueCurve(rpm) - (1 - Throttle) * EngineBraking(rpm)
            tq    = 0 if Throttle < 0.05 and RPM == IdleRPM exactly
            drive = (tq * FinalDrive[1]) * (GearRatios[CurrentGear] * 0.5)
brake = Brake * (min(ww, 20) * -0.5)
k1, k2 = 1, 1.25;  boost over 1:  k2 = ((b - 1) * 2.5 + 1) * 1.25,  k1 = (b - 1) * 3 + 1
g     = MellowForceFeedbackGraph(|body velocity|),  over k1 * k2 on the rears
d     = ((drive * k1 + brake) - WheelForce.x * g) * 124.99999
```

The final drive is always `FinalDrive[1]`. The scale is 0x42f9ffff, one ulp
under 125.

### ComputeAuxiliaries

0x002076a8. It works in this order:

1. **The suspension forces**, below.
2. **The brake locks.** With the brake over 0.95, a wheel under 30 rad/s
   either way stops dead and locks. With the brake under 0.2, every lock
   lets go.
3. **The engine speed**, from the rear axle:
   `w = (FinalDrive[1] * (ww[2] + ww[3])) * 15/pi`, and
   `rpm = w * GearRatios[gear]`, where `gear` is the gear at entry.
4. **The box.**
   - For AUTOMATIC, a car below first is put in first *without* the RPM
     following. It shifts up while `gear - 1 < NumGears` and ShiftUpRPM is
     under the RPM. It shifts down while it is above first and the RPM is
     under ShiftDownRPM. The RPM is recomputed after each shift.
   - For REVERSE, the RPM is taken through GearRatios[0] and the gear
     becomes REVERSE.
   - Any other request leaves the gear where it is.
5. **The RPM is clamped** to [IdleRPM, MaxRPM].

### ComputeSuspensionForces

0x002078f0 opens with GetGroundHeightAndWheelPos (0x00207bb8). For each
wheel, that takes the hub relative to the centre of gravity, rotates it
into the world by R, adds X, and asks the topology for the height and the
normal under it. The hub is the VU0 sum
`(0 - CoG) + wheel record`, all four lanes.

Then, for each wheel:

```
c  = GroundNormal . R.v2
x  = c < 0.001 ? -100 : (height - hub.z) / c;   x += Radius
x under BumpStop[1]:  position BumpStop[1], off the ground, penetration 0
x over  BumpStop[0]:  position BumpStop[0], on it, penetration x - BumpStop[0]
otherwise:            position x, on it, penetration 0
v  = (p - old) / max(UglyTimestepHack, 0.0001)
f  = RestLoad + p * (Stiffness * (max(p, 0) * Progression + 1))
     + v * Damping[v <= 0 ? 1 : 0]
     + SwayBarStiffness * (p - position[partner])       partners 1 0 3 2
f  = max(f, 0), and 0 off the ground
```

The sway bar reads its partner as it stands. So wheels 1 and 3 see 0 and 2
already updated, and 0 and 2 see 1 and 3 from the last call.

### ResolveForces

0x00207cb8. Each wheel's hub goes into world space by bMulMatrixVec3, and
bSlipping is cleared. For a wheel on the ground:

```
W     = body velocity + (-w.z * r.y, w.z * r.x)       yaw rate alone
h     = bATan(R.v0) * pi/32768, plus the steering on a front wheel
lng   = W.x * sin(h + pi/2) + W.y * sin(h)
lat   = -W.x * sin(h) + W.y * sin(h + pi/2)
slip  = lng - ww * Radius;   WheelSlip = (slip, lat)
grip  = 1, or FrictionBoost * 0.25 once |(slip, lat)| passes FrictionBoost * 0.05
bSlipping when |(slip, lat)| is over 6
F     = against (slip, lat) by grip * SuspensionForce * 1.25,
        turned back into the body by the steering alone
```

An airborne wheel's F is (0, 0). Every wheel then takes
`F.z = SuspensionForce` and goes into the world by R. A wheel on the ground
then gets three more adjustments:

- **The friction circle.** The world xy is cut to
  `SuspensionForce * 1000 * FrictionBoost`.
- **The boost.** The xy is scaled by `(boost - 1) * 2.5 + 1` above a boost
  of 1.
- **The hold.** With the wheel locked, or with the brake over 0.4 and the
  body under 0.1 m/s, the slope's pull `-R.v2.xy * SuspensionForce / R.v2.z`
  is cancelled outright. Inside the circle it is cancelled in proportion to
  `|R.v1.x|` and `|R.v1.y|`, that is, to how far the body is banked.

Every wheel, grounded or not, applies its force at the hub. WheelForce
keeps the body-frame F.

### BottomOut

0x00208278. It looks only at wheels with a GroundPenetration over 0:

```
p  = R * (hub + (0, 0, SuspensionPosition))
k  = -(PointVelocity(p) . GroundNormal)
k over 0:  k = (k * gGroundPenaltyImpulse) * Mass
           impulse k * GroundNormal (all four lanes) at p
           WheelBottomOutMagnitude[i] += k;  total += k
```

It returns the total.

## MellowMover

### Construction

0x00206448, behind `__nw__11MellowMoverUi` (0x002086d0), which is
MellowMoverSlotPool's bOMalloc. It runs in this order:

1. CarMover's vptr, the PhysicsSystem, and PhysicsVehicle's vptr, as in
   PhysicsCar.
2. The fields, then both vptrs as MellowMover's.
3. A RigidBody from its pool, added to the list.
4. A Mellovator on the CarState's topology coordinate, added to the list.
   So the state vector is body then wheels.
5. An Aerodynamics, inlined, and not a component. Then the body's
   SpeedLimiter.
6. **Calibrate, before the wheels exist.** It does not touch them.
7. Four Wheels on `Tires[i / 2]`, placed from the *Car's* CarState rather
   than the `cs` argument.
8. InitializeStateFromCar, then ComputeAuxiliaries.

### Destruction

0x00206608 works in this order:

1. Both vptrs.
2. `__dl__12AerodynamicsPv`, with no null check.
3. Each non-NULL wheel through its own table with flags 3. The pointers
   are left as they were.
4. `~PhysicsVehicle(0)`, which takes the body and the Mellovator with it.
5. `~CarMover(0)`.
6. The pool's free when `flags & 1`.

### Calibrate and InitializeStateFromCar

Calibrate (0x00206790) calibrates the body about the CTI's centre of
gravity and recomputes its inertia tensor. Then it gives the Mellovator
its rest loads at the downforce the car's `ForwardSpeed` makes. That is
`pCar->State`, not `State`.

InitializeStateFromCar (0x002067e0) copies the driver's throttle, brake,
steering and desired gear into the Mellovator. It sets the body from the
CarState and the wheel speeds from WheelAngularVelocity, then runs
ComputeAuxiliaries through the vehicle's vptr.

### ComputeAuxiliaries and ResolveForces

ComputeAuxiliaries (0x00206cb8) runs the system's own ComputeAuxiliaries.
If BottomOut pushed anything, it runs it again. Then it calls ResolveForces
through the vehicle's vptr.

ResolveForces (0x00206d30) calls the Mellovator's ResolveForces through its
vptr, then the aerodynamics with no downforce out, then JumpStabilizer. The
body's own ResolveForces is empty, and is not called.

### SetBoost

0x00206d78 writes:

- The aero's boost, from the Car's own BoostFactor, not from `f`.
- The aero's draft, `1 - DraftFactor`, the Car's.
- The body's catch-up multiplier, `f`.
- The Mellovator's friction boost: `f`, times 0.7 when the Car's
  DriverMode is 1 and its ForwardSpeed is over 30 mph.
- The Mellovator's boost, `f`.

### JumpStabilizer

0x00206e20. It reads the Car's own CarState, not the body: the wheel
count, the velocity and `B`, the BodyMatrix. With fewer than two wheels
down, it applies `-Mass * MellowJumpStabilization(|w|) * w` as a moment,
all four lanes, where `w` is the body's angular velocity.

With none down and `B.v2.z` strictly over 0.1, it applies two more:

- **Yaw.** `h` is the velocity with z zeroed and w kept, normalised by
  `vrsqrt`. The moment is `h x B.v0`, rescaled by bNormalize3To to
  `Mass * ((h . B.v0 - 1) * 100)`.
- **Level.** `s` is `(0, 0, 1) x B.v0`, normalised. The moment is
  `s x B.v1`, rescaled to `Mass * ((s . B.v1 - 1) * 100)`.

The image stores three words of the up vector and leaves the fourth to the
stack at sp+60. It reaches the moment's w lane through the cross product.
The port writes zero there, and the checker's model zeroes sp+60 to match.

### Move

0x00206b28, at +16 in the Mover's table. It returns `dt`.

1. The ticker is read, and the reading discarded.
2. Calibrate.
3. The driver's throttle, brake, steering and gear go into the Mellovator,
   and its throttle into the aero. The aero's ground effect is a quarter
   per wheel down. WheelBottomOutMagnitude is cleared, 3 down to 0.
4. SetBoost with the car's BoostFactor.
5. The sub-steps:
   `n = cvt.w.s(dt / MaxiMellowTimeStep) + 1` with MaxiMellowTimeStep
   0.0084, and `step = dt / n`. Each one sets UglyTimestepHack, runs
   IntegrateEuler(step) and orthonormalises R in place. The ticker
   difference and the debug print do nothing in the port.
6. UpdateCar(dt).

### UpdateCar

0x00206878 copies the body and the Mellovator back.

- **Position, velocity and angular velocity** are copied as whole quads,
  pad lane included, and R as the BodyMatrix. The geometry position is recomputed, MatrixValid is
  cleared, and VelocityMagnitude is the speed's `sqrt`.
- **Angle** is bATan of R.v0's x and y. ClutchEngaged is 1, both skids 0,
  and ForwardSpeed is the velocity dotted with R.v0.
- **Each wheel's angle** is advanced by `dt * ww` here, since nothing
  integrates it. The front wheels take the driver's steering, through a
  float and back. Each wheel is placed with its spin and suspension
  position.
- **Each wheel's slip, slipping flag and ground contact** are copied into
  the CarState and the Wheel. Traction usage is 0, and the z force is the
  suspension force.
- **Skids** are made if the car's visual effects are generated.
- **The gear and the RPM** go in last.

## The static initialiser

0x00208420, `_GLOBAL_$I$MellowForceFeedbackGraph`. It builds
MellowForceFeedbackGraph from (0, 0.4) and (20, 0.5) (retail's (0, 0.3)), and
MellowJumpStabilization from (0, 0), (0.1, 0) and (2, 20). The second
graph's data sits at 0x00313c48 in .data; the initialiser overwrites every
word of it.

## Retail's changes (TASKS 74)

The demo's MellowMover.obj and retail's are the same instruction for
instruction but in four places, all ported:

- **The force-feedback graph** starts at (0, 0.3), not (0, 0.4). Retail's
  .lit4 word gp-27252 is 0x3e99999a.
- **The constructor zeroes gUglyTimestepHack** before it builds the
  Mellovator (0x00219628, in the delay slot of that bOMalloc). The demo
  leaves the last mover's step there, so a new car's first suspension
  velocity divided by another car's step.
- **Move brakes with the e-brake too**: the Mellovator's Brake is
  `max.s(Brake, EBrake * 0.5)` (0x00219da4 .. 0x00219db8). The demo's takes
  Brake alone, so the e-brake did nothing to a mellow car.
- **UpdateCar draws each wheel no higher than its axle's
  MaxRenderingCompression** (CTI + 588 + 32 * (i / 2), `c.lt.s ; bc1tl
  mov.s`, 0x00219bec .. 0x00219bfc). The demo's passes the Mellovator's
  compression as it is, and a hard landing pushed the tyre into the arch.

Under UpdateCar, CarState::CalculateWheelMatrices(int) changed too (retail
0x001c0d78, the demo's 0x001b6d10). Retail's lifts the BrakeMatrix with the
suspension as it does the WheelMatrix, and adds WheelInfo's word 24
(`OffsetY` in the port) to both matrices' y. Retail's car data fills that
word: it pulls each wheel of the first 49 records 1 to 7 cm in, and is 0 in
the last 15. The demo's lifts only the WheelMatrix and reads no word 24.
The port's `carstate.c` is retail's, so the brake calipers now follow the
wheel and the wheels sit where retail's do, on every mover.

The checkers whose oracle is the demo image get retail's behaviour through
hooks that do what retail's instructions do at the same point:
`physicscar_check.retail_wheel_matrices` (on 0x001b6de8) and
`mellowmover_check.retail_mellow` (the feedback word, 0x00206500,
0x00206b98 and 0x00206a04). `mellowmover_check --demo` runs the demo image
with them and must agree with the retail run line for line. It does, and
each hook taken out alone breaks between 90 and 17,118 lines.

## What the checker found

**The .lit4 pool is not always the nearest float.** The half-pi at gp-27744
is 0x3fc90fdc, one ulp above the float nearest pi/2, 0x3fc90fdb. The
difference is small, but it feeds `bSin`, which truncates to a BAM. A
heading that lands a hair under a BAM boundary in IEEE lands on it in the
image, and the tyre forces go one BAM apart. The port's first BAM-to-radian
constant was the same mistake the other way, a decimal a digit short. The
checker now reads all eighteen constants back out of the pool and
compares them with the literal and the comment beside it.

**A level car divides zero by zero.** JumpStabilizer's level moment is
`bNormalize3To(s x R.v1, k)`. For a car whose side axis is already level,
both the vector and `k` are zero, and bNormalize3To's first divide
(0x00240274, `sqrt(n) / len`) is 0/0. The EE answers FLT_MAX, and its
reciprocal scales the zero vector to zero. IEEE answers NaN, which reached
the body's angular momentum, and the harness died of it in the first
airborne scenario. bNormalize3To now divides with `ee_div`. mipsemu's
`eediv_pcs` shows this site and JumpStabilizer's own `vrsqrt` as the only
divides by zero any scenario reaches. `vrsqrt` was already spelled with
`ee_div`.

## What the checker covers

`tools/mellowmover_check.py` runs retail's MellowMover.obj itself in
mipsemu, the way `physicscar_check` runs PhysicsCar. It covers the
constructor, Move and its sub-steps, the three tables and the direct
calls, on a Car, a RealDriver and a CarTypeInfo laid out in emulated
memory, at retail's offsets. The harness, `tools/src/mellowmover_test.c`,
runs the port on the same records. Both print every field of every object
the mover owns: 45 scenarios, 64,984 lines, 0 differ, on retail's image and
on the demo's with the hooks (`--demo`). The six scenarios TASKS 74 added
are the e-brake's four (`c0-ebrake`, `c0-ebrake-over`, `c33-ebrake-under`,
`c65-ebrake-lock`) and two on a car 0 whose MaxRenderingCompression every
wheel passes (`c0-mrc-move`, `c0-mrc-bottom`).

### Records the shipped data does not have

The records are PhysicsCar's four (cars 0, 33, 65 and 1) plus three more,
each there because the shipped data hides something:

- **Car 34.** The Mellovator reads only `FinalDrive[1]`, and 61 of the 66
  records have two equal final drives. Car 34 is one of the five that do
  not (34 and 47 to 50).
- **Car 0 with CenterOfGravity.y = 0.0625.** CoG.y is 0 in all 66
  records, and the hub is `(0 - CoG) + wheel` in every lane.
- **Car 0 with both droop stops at -2.** The shipped stops are -0.10 to
  -0.15. A wheel with its back to the ground is given `-100 + Radius`, and
  with a stop that close, any constant under -1 lands on it the same way.

The old calibration (`UseNewSuspensionCalibration` 0) is tried on car 0.
Twenty-one records have CoG.x = 0, car 65 among them, and for those the
two calibrations are the same.

### States set up by hand

- **The shift points.** A probe in a fixed gear reads the RPM the box will
  see, and that RPM is made the shift point. The neighbour that could shift
  the car back is cleared, so only the test's strictness decides.
- **The grip knee.** The friction boost is searched, in float, for the one
  whose knee, `boost * 0.05`, is a grounded wheel's slip magnitude
  exactly.
- **ResolveForces clears bSlipping.** All four flags are set first, and
  the two wheels off the ground must come back clear.
- **A frame under the suspension's floor.** Move sets UglyTimestepHack to
  its step before each integration, so a 0.00005 s frame is the only way
  under the 0.0001 floor. The car starts 3 cm above its rest height, so its
  suspension is moving on that step. At rest `p - old` is 0 and the floor
  cannot show.
- **A CarState that is not the Car's.** The constructor takes one, and a
  scenario that passes the Car's own cannot tell `State` from
  `pCar->State`. `c0-apart` passes a copy with a different ForwardSpeed.
  - **`State`**: InitializeStateFromCar, UpdateCar, BottomOut's magnitudes,
    and Move's ground effect and clear.
  - **The Car's**: the constructor's wheels, Calibrate's downforce,
    SetBoost and JumpStabilizer.

  In the game the two are one. The constructor's only caller is
  SetMovementMode's MELLOW_MOVEMENT arm (0x0012fe84), which passes
  `car + 64`, the Car's own State. The port reads each from where the
  image does anyway, so a caller that ever passes another stays correct.

### The mutation pass

352 mutations, 347 caught, 5 equivalent, 0 unexplained, against
retail's image since TASKS 74. Its six new ones (no e-brake, the full
e-brake, gUglyTimestepHack kept, no MaxRenderingCompression clamp, the
clamp as a floor, and the demo's feedback point) are all caught. The
first pass left 28 alive. Twenty-three were holes in the scenarios, closed by the
records and setups above. Five are equivalent, each for a reason
checked in the image:

- **Three pad lanes.** The hub's w lane and F's go only to
  bMulMatrixVec3 (0x002427b0), which stores 1.0 over w before the multiply,
  and to GetElevation (0x0014f418), which reads x, y and z.
- **The Mellovator destructor's vptr store.** `~PhysicsComponent`
  (0x00192438) stores its own before anything reads it.
- **The damping test at v == 0.** `v * Damping[k]` is a zero for either
  `k`, and `f` is RestLoad plus a product, never a negative zero, so a
  zero of either sign leaves it.
