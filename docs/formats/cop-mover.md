# CopMover

The CopMover half of retail's `copdriver.obj` (0x001a0dd8 .. 0x001a1ce0, and
the inline accessors at 0x001a32f0 .. 0x001a3344). Only `DoSnapshot`
(0x001a0f20) is left out; it waits on the replay with every other class's.
This is step 12c: the mover a cop car rides when no player is near enough
for physics. CopDriver (12d), the other half of the file, drives it.

Ported to `3DS Files/source/copdriver.{c,h}`. Cross-checked by
`tools/copmover_check.py` against `tools/src/copmover_test.c`, with the
retail image (SLES_507.31) running in mipsemu as the oracle.

## The shape of it

A cop car on this mover is not simulated. The mover keeps a velocity,
a heading and a speed, and eases them towards what the CopDriver asks
for. It works in one of two states:

- **eCMS_STEERING (0).** A speed along a heading. The heading turns
  towards the one wanted, at a rate the speed sets; the speed brakes or
  accelerates towards the one wanted.
- **eCMS_TRANSLATING (1).** A velocity, eased towards the one wanted.
  The change is split along the car's velocity and across it. The heading
  follows the velocity. CopDriver asks for this state only at 13.41 m/s
  (30 mph, gp-29464) or more.

The velocity is kept to the ground under the car. The car is then set on
five samples of the ground's height, tipped to their slopes. After that the
mover writes the CarState outright: the position, the velocity, the body
matrix, no spin, the steering, and the four wheels turning at the speed,
on the road, with nothing on them.

`Car::SetMovementMode`'s COP_MOVEMENT arm (mode 5) builds one through
`gCopMoverCtorFn` ([car-modes.md](car-modes.md)). main.c points that seam at
`copmover_construct`, and `COPMOVER_SIZE` is `sizeof(CopMover)`.

## The record, 128 bytes

The demo's `.mdebug` record (t2698) is 112 bytes. Retail added sixteen
bytes at 64. Its constructor and Move use the first word, `New64`; the
other three are never read or written.

| Off | Field | Type |
|----:|-------|------|
| 0 | Mover | `CarMover`: Driver at 0, vptr at 4 |
| 8 | pCar | `Car *` |
| 12 | _pad12 | the image's padding to the quadword; the port's bVector3 is word-aligned, so it is spelled out |
| 16 | v3Velocity | `bVector3` |
| 32 | v2TransverseAccel | `bVector2`, the across part of the change, m/s/s |
| 40 | aFacingAngle | `u16`, BAM |
| 42 | aDesiredFacingAngle | `u16` |
| 44 | fSpeed | `float`, along the heading |
| 48 | fDesiredSpeed | `float` |
| 52 | fBaseMaxSpeed | `float`, 84.935 m/s (190 mph) from the constructor |
| 56 | fMaxBrakingAccel | `float`, 40 |
| 60 | fMaxThrottleAccel | `float`, by car type |
| 64 | New64 | `float`, the braking ramp (retail's) |
| 68 | New68[3] | never touched (retail's) |
| 80 | v3DesiredVelocity | `bVector3` |
| 96 | v3GroundNormal | `bVector3` |
| 112 | bIsAirborne | `int` |
| 116 | State | `eCopMoverState` |
| 120 | _pad120[2] | to the sixteen |

`_vt$8CopMover` is at 0x002b5a08, in CarMover's layout:

| Slot | Entry |
|-----:|-------|
| 8 | the destructor, 0x001a0e88 |
| 16 | Move, 0x001a1030 |
| 24 | DoSnapshot, 0x001a0f20 (TASKS 72c); New68 and pCar are not saved |

## The tuning

The .lit4 pool, gp-29508 .. gp-29472, and the constants the code builds
with `lui`.

| Where | Bits | Value | Use |
|------:|------|------:|-----|
| gp-29508 | 42a9ded0 | 84.93518 | fBaseMaxSpeed, 190 mph |
| gp-29504, -29500 | 3e99999a | 0.3 | Brake shows past this share of fMaxBrakingAccel (each state reads its own) |
| gp-29496 | 49742400 | 1e6 | the lowest sample's start |
| gp-29492 | c9742400 | -1e6 | the highest sample's start |
| gp-29488 | 46230eac | 10435.668 | a slope to BAM |
| gp-29484 | c60ca000 | -9000 | how the turn limit falls with speed |
| gp-29480, -29476 | 463b8000 | 12000 | the turn limit at a stand-still, BAM |
| gp-29472 | 3e99999a | 0.3 | the turn rate's gain |
| `lui` | 42200000 | 40 | fMaxBrakingAccel |
| `lui` | 420c0000 | 35 | the most across, m/s/s |
| `lui` | 43160000 | 150 | the most its change, m/s/s/s |
| `lui` | 40800000 | 4 | the most taken off into the ground, m/s |
| `lui` | 40000000 | 2 | the most the five samples may span, m |
| `lui` | 47800000 | 65536 | a direction to Q16, for bFixATan |
| integer | | 21845 | the most the heading turns, BAM/s: `0x780000 / 360` |

**The top speed by strength.** The table at 0x002b5808 is added to
fBaseMaxSpeed by `tCopManager::nDifficultyLevel`: -4.4703 (10 mph),
-2.2351 (5 mph) and 0.

**ResetMaxThrottleAccel** (0x001a0ea0) sets fMaxThrottleAccel by the car
type's `Type`. Any other type leaves it as it was.

| Type | fMaxThrottleAccel |
|-----:|------------------:|
| 4 | 11.25 |
| 31 | 12.75 |
| 32, 33 | 15.0 |
| 34 | 14.25 |

## The constructor

`__8CopMoverP3Car` (0x001a0dd8) sets every word except the Driver (which
SetMovementMode's tail stores) and 68 to 79, in this order:

1. The vptr and the car.
2. The car's velocity, which is also the velocity wanted.
3. Steering.
4. The car's forward speed and heading, each also the one wanted.
5. A top speed of 84.935 and ResetMaxThrottleAccel.
6. Braking at 40, no sideways acceleration, the ground straight up, on the
   ground, and the ramp at 0.

The normal's fourth word is a word off the image's stack. The port's is
0, and the check doesn't compare it.

The destructor stores its own vptr, then calls ~CarMover with its flags.

## Move

`CopMover::Move(dt)`, 0x001a1030, returns dt.

1. **The ground.** `GetElevation` at the car's position, for the normal
   only. With no polygon found, the normal is (0, 0, 1). Its fourth word
   is the stack again, and 0 on the port.
2. The heading, the speed and the velocity are read back from the
   CarState, so whatever moved the car since the last frame counts.
3. **The limits.** The top speed is `fBaseMaxSpeed` plus the strength's
   offset. The most the throttle can give is
   `fMaxThrottleAccel - fMaxThrottleAccel / top x |fSpeed|`, which falls
   to nothing at the top speed. fDesiredSpeed is held to the top speed.
   bIsAirborne and the car's NitroEffectFlag are cleared.
4. The state's step (below). Any state but 0 and 1 does nothing here.
5. **Moved.** Position += velocity x dt, all four lanes.
6. **Sat on the ground**, unless the step left it in the air. The ground's
   height is sampled at the car and a metre each way along x and y, in
   that order: (0, 0), (+1, 0), (-1, 0), (0, +1), (0, -1).
   - If the highest and lowest are 2 m apart or less, the car sits on
     them. The slopes are `((e1 - e0) - (e2 - e0)) / 2` and the same for
     y, each times 10435.668 and truncated to BAM. The height is the
     centre sample plus the rear right wheel's radius, less that wheel's
     height, plus the centre of gravity's height. The body matrix is
     `RotateY(RotateX(RotateZ(I, heading), y slope), -x slope)`, and the
     geometry position is the position less the centre of gravity, all
     four lanes.
   - Otherwise the car is in the air and keeps its height and matrix.
7. `CalculateGeometryPosition`; no angular velocity; the steering angle
   from the driver.
8. **The wheels.** Each turns at `fSpeed / radius` and on by that times
   dt, at no suspension height, on the ground, on TERRAIN_DEFAULT, with
   no slip, traction use or load. All four bottom-out values are cleared
   for each wheel, as the image does.
9. `CalculateWheelMatrices` and `ComputeFakeRPM`.

**Held to the ground.** Both states end the same way. The velocity's x and
y are set, and its dot with the ground's normal is taken. Up to 4 m/s of
that is taken off along the normal. If there was more than 4, the car is
in the air.

**Min and max.** The image's `min.s` and `max.s` keep the first operand
unless the second compares below (or above). So a NaN in either operand
gives the first. The port's `min_f` and `max_f` are written that way. With
a NaN height in a sample, the highest and lowest pass it over unless it is
the last sample.

### STEERING

1. CalculateFacingAngle, and the CarState's heading.
2. The change wanted is `a = (fDesiredSpeed - fSpeed) / dt`.
3. **Braking**, when a is below 0:
   - The ramp `New64` climbs 2 a second, to 1.
   - a is held to `fMaxBrakingAccel x New64`.
   - The driver's Brake becomes `|a| / fMaxBrakingAccel`, from the a
     before it was held. That happens once |a| is past 0.3 of
     fMaxBrakingAccel, or once the ramp is full; until then Brake is left
     as it was.
4. **Otherwise** the ramp goes back to 0. Past the throttle's most, a is
   held to it and NitroEffectFlag is set. Brake is 0.
5. `fSpeed += a x dt`, held to the top speed both ways, and the
   CarState's forward speed.
6. The velocity is `fSpeed` along the heading (`bCos`, `bSin` of the BAM),
   held to the ground, with the z it had. The CarState's velocity, its
   magnitude, and the matrix marked stale.

### TRANSLATING

1. `dv = (v3DesiredVelocity - v3Velocity) / dt` in x and y. Its part
   along the velocity is `l = (dv . u) u`, where `u = v / |v|` (divided
   the EE's way).
2. The rest, `dv - l`, is the transverse accel, held to 35. Its change
   from last frame, over dt, is held to 150; if it was held, the accel is
   last frame's plus that change times dt.
3. **Braking** (the along part points back): the ramp, l held to it, and
   Brake shown as STEERING does it, but from the held value. **Otherwise**
   the ramp is cleared, Brake is 0, and past the throttle's most l is held
   to it with NitroEffectFlag set.
4. `v += (l + transverse) x dt` in x and y, held to the ground. If |v| is
   past the top speed, all four lanes are scaled to it.
5. The CarState's velocity and magnitude. The forward speed is |v|, and
   the matrix is marked stale.
6. **The heading follows.** The velocity's direction comes from the VU's
   `vrsqrt`, i.e. `0 + 1 / sqrt(v . v)` divided the EE's way. Its x and y
   are taken times 65536, truncated, and given to bFixATan for the heading
   wanted. Then CalculateFacingAngle, and the CarState's heading.

**A stand-still.** With a zero velocity, `u` is FLT_MAX by FLT_MAX. On the
EE every product saturates. On an IEEE host the products overflow to
infinity and then NaN, so the car's position goes NaN. The mipsemu oracle
is IEEE, and the port matches it there.

The case should not come up in play. CopDriver asks for TRANSLATING only
at 13.41 m/s or more, and it asks for a velocity a little faster than the
car's own. The check still covers it ("translate", with the wanted
velocity at 0 for 20 frames).

## CalculateFacingAngle

0x001a1bd0, `(max_speed, dt)`. It returns the turn rate in BAM a second.

1. **The limit.** Going forwards it is
   `-9000 / max_speed x |fSpeed| + 12000` (divided the EE's way), so
   12000 BAM (66 degrees) at a stand-still and 3000 at the top speed.
   Backing up, it is always 12000.
2. `d` is the wanted heading less the heading, as a signed 16-bit
   difference. Past the limit, d is scaled to it.
3. The rate is `d x |fSpeed| x 0.3`, held to 21845 both ways.
4. The step is rate x dt, but no more than d. The heading moves by the
   step, truncated.

## The accessors

GetTransverseAccel, IsAirborne, SetMaxThrottleAccel, SetMaxBrakeAccel,
SetBaseMaxSpeed, GetMaxSpeed (the base, not the strength's top),
SetDesiredVelocity (it copies the vector and zeroes z), SetDesiredSpeed,
SetDesiredAngle and SetState.

## The check

`tools/copmover_check.py` runs retail's code in mipsemu under its own bSin,
bCos, bFixATan and eIdentity, eRotateX/Y/Z. GetElevation, the CarState's
four wheel and geometry calls, ComputeFakeRPM and ~CarMover are stubs. The
script has 12535 operations:

- the constructor on 12 car types, ResetMaxThrottleAccel, and the
  accessors;
- CalculateFacingAngle over 11 speeds, 12 heading pairs, 5 top speeds and
  2 dts;
- STEERING:
  - accelerating at each strength;
  - braking hard and gently;
  - reversing;
  - big dts;
  - over the top speed, with the base set to 30, 0 and -5;
  - no ground found;
  - into the ground;
  - steps up and down;
  - a steep plane;
- TRANSLATING:
  - at each strength, down to a stand-still;
  - from rest;
  - hard turns;
  - the brake limits;
  - into the ground;
  - a step;
- states 2, -1 and 7, and twelve random runs of 25 frames;
- the edges:
  - ground at ±500 m;
  - a NaN height in a middle sample and in the last;
  - a slope where the two ways of taking it round apart;
  - exactly 4 m/s into the ground;
  - braking at exactly 0.3, and gently with the ramp full;
  - reversing to a stop;
  - the car moved between frames;
  - TRANSLATING past the top speed;
  - a denormal velocity;
  - a centre of gravity with a fourth word;
- the destructor through the table and directly over another vptr.

30782 lines, 0 differ. `--mutate`: 188 mutations, 173 caught and 15
equivalent. Thirteen are `<` against `<=` where the two meet. In each of
those, the scale at the meeting point is exactly 1, the value is already
the limit, or the sign rules it out. The other two:

- the two writes in the ground hold swapped, which are independent;
- the sample point's fourth word, which GetElevation doesn't read.
