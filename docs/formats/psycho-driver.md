# PsychoDriver: the AI's driver

`PsychoDriver.obj` (0x00139700 .. 0x0013a6ac and 0x0013ab68 .. 0x0013ad84),
with its start-up code `_GLOBAL_$I$PidProportionalData` (0x0013ab68) and
`_vt$12PsychoDriver` (0x002aec50). AIDrivingInfo.obj's two SteerStraight
functions (0x001cd148, 0x001cd1d8) come with it, as only its
CalcSteerToPoint calls them. This is step 11f-1. AIDriver's constructor
and TrafficDriver's each bMalloc one (624 bytes) and build it on their car.

Ported to `3DS Files/source/psychodriver.{c,h}`, all but DoSnapshot
(0x00139980), which waits on ReplaySnapshot. Cross-checked by
`tools/psychodriver_check.py` against `tools/src/psychodriver_test.c`, with
the image as the oracle.

From then on the AICarController talks to it through CarDriver's table:
SetTarget with the action's points, SetDesiredSpeed with the speed it
wants. Car::Drive calls its Drive once a step. Drive turns the target and
the speed into CarDriver's input record:

- a steering angle, from PID loops on the car's heading, its velocity's
  heading and its speed;
- a throttle and a brake;
- a gear.

Retail's class is not the demo's. It dropped these from the demo:

- the line predictor: RunLinePredict, MaxSpeedAlongPath, DoSpeedPredict,
  MaxSpeedFromCar and MaxSpeedToTarget;
- the CarPredictInfo at 564;
- CurrentPhysicsMode.

It added a speed tolerance, an e-brake timer and a direction latch. Drive's
gear logic and CalcThrottleAndBrake are new.

## The record, 624 bytes

CarDriver's 560 (see [car-driver](car-driver.md)), the vptr at 556, then:

| Off | Field | Type |
|----:|-------|------|
| 560 | pCar | Car * |
| 564 | SteerToPoint | bVector2, where Drive steers |
| 572 | MaxThrottle | float, 1.0; nothing reads it |
| 576 | DesiredSpeed | float, signed: below 0 reverses |
| 580 | TimeToGetToDesiredSpeed | float, counted down by Drive |
| 584 | DesiredSpeedTolerance | float |
| 588 | AllowedToUseThrottleAndBrake | a bool word |
| 592 | EBrakeTimer | float |
| 596 | | four bytes nothing touches |
| 600 | DirectionLatch | a bool word |
| 604 | pBodyError | PidError *, "Phsycho Body Pid" |
| 608 | pHeadingError | PidError *, "Phsycho Heading Pid" |
| 612 | pVelocityError | PidError *, "Phsycho Velocity Pid" |
| 616 | | eight bytes of round-up |

The names are spelt "Phsycho" in the image. A PidError is 40 bytes: two
Averages and two floats (see [average](average.md)).

On the host, pCar and the three pointers are eight bytes wide. The header's
`PSYCHODRIVER_SLACK` checks each later offset against the console's plus
the slack.

### The table

`_vt$12PsychoDriver` has CarDriver's twenty-one slots. Its own entries:

| Slot | Function | Address |
|-----:|----------|---------|
| 8 | ~PsychoDriver | 0x001398e8 |
| 16 | Drive | 0x00139c48 |
| 24 | DoSnapshot | 0x00139980, NULL in the port |
| 48 | SetLowGear | 0x0013acd8 |
| 56 | SetDesiredSpeed | 0x00139968 |
| 64 | SetTarget | 0x0013a3e0 |
| 72 | SetSteerToPoint | 0x0013ad10 |
| 80 | GetDriverNumber | 0x0013ac80 |
| 88, 96, 104 | StartHonkHorn, StopHonkHorn, IsHonking | 0x0013a638, 0x0013a658, 0x0013a678 |
| 120 | ZeroSteeringMemory | 0x00139b28 |
| 128 | ClearSteeringMemory | 0x00139b68 |
| 136 | GetDesiredSpeed | 0x0013acf0 |
| 144 | GetDesiredTimeToSpeed | 0x0013ace8 |
| 160 | GetSteerToPoint | 0x0013ad00 |

The joy handlers (32, 40), MaxSpeedToTarget (112) and SetPhysicsMode (152)
are CarDriver's.

## The tuning

The start-up code (0x0013ab68) sets fPsychoCounterDiff (gp-13408) to
0.000958738 and builds seven Tables over the image's data:

| Table | Over | Points | Read by |
|-------|------|-------:|---------|
| PidProportionalTable | 0 .. 160 | 10 | Drive, kp |
| PidDerivativeTable | 0 .. 160 | 10 | Drive, kd |
| PidIntegralTable | 0 .. 160 | 10 | Drive, ki |
| PidSteerToTable | 0 .. 160 | 10 | CalcSteerToPoint, the distance on |
| PsychoSteeringRangeTable | 0 .. 160 | 10 | Drive, the wheel's range |
| PsychoSteeringSpeedTable | 0 .. 160 | 10 | Drive, the wheel's rate |
| PsychoSteeringCurveTable | 0 .. 1 | 6 | nothing |

Each table is read by the car's speed: the signed speed `spd` in Drive,
the ForwardSpeed in CalcSteerToPoint.

Four arrays of five floats (0x002aecf8 .. 0x002aed40) are indexed by
GetMovementIndex. They are PsychoSteeringProportionalWeight,
...IntegralWeight, ...DerivativeWeight and
PsychoDriverSteerToPointSecondsAhead. Only indices 3 and 4, the "fixed"
ones, are ever read.

The constants Drive reads through gp are in `psychodriver.c` with their
bits. They include the 20 mph of the e-brake (8.940545) and the pedal's
floor of -0.94.

## Construction and destruction

**The constructor** (0x00139760) runs these steps:

1. CarDriver's constructor, inline.
2. pCar.
3. DirectionLatch and AllowedToUseThrottleAndBrake are set to 1.
4. Steering, the speed, its time, its tolerance and the e-brake timer are
   set to 0.
5. The vptr, and MaxThrottle 1.0.
6. The three PidErrors, in order. Each is a `bMalloc(40, name, 0, 16)`
   with Averages of 15 and 5 slots; the velocity's has 6 and 3.
7. ZeroSteeringMemory and ZeroThrottleMemory, called rather than
   dispatched.
8. The steer-to point is set to (0, 0).

**The destructor** (0x001398e8) runs these steps:

1. It stores the vptr.
2. It destroys each PidError that is set, with flags 3: the body's, then
   the heading's, then the velocity's.
3. It calls StopHonkHorn.
4. It tail-calls ~CarDriver with its own flags.

## The small methods

- **SetDesiredSpeed(speed, time, tolerance, allowed)** stores all four.
  Retail's takes the tolerance, which the demo's did not.
- **SetTarget(t)** returns for a NULL target. It also returns for a count
  outside 0 .. 20, read signed (`lb`). Otherwise it is
  DriveTarget::operator= into the driver's own target, then Resample.
- **The horn**: the car's BaseCarSound's StartHonkHorn, StopHonkHorn and
  IsHonking when the car has one, and IsHonking is 0 without. Unlike
  RealDriver's, there is no UsageType test.
- **GetDriverNumber** is the car's DriverNumber (`lh`).
- **SetLowGear** sets DesiredGear -1.
- **StepOnItJeeves** (no caller) sets EBrake 0, Throttle 1 and Brake 0.
- **SetMaxThrottle** (no caller) and **SetEBrakeTimer** (0x0013ad08, no
  caller) store their float. Drive's countdown is the only other store to
  the timer, so the e-brake never comes on in the game.
- **GetSteerToPoint** and **SetSteerToPoint** read and write the point.
  The setter stores y first.

0x0013a630 is eight bytes that store a zero through the third argument.
Nothing reaches it by `jal` or by a data word, so it is not ported.

## GetError and the memories

**GetError(&head, &vel)** (0x00139a68) runs these steps:

1. It takes the bearing `ang`: bATan of the steer-to point less the car's
   position.
2. `head` is RadianWrap(Angle - ang). The subtraction is a `subu` cut to
   16 bits.
3. At a ForwardSpeed of 1 or more, `vel` is RadianWrap of the velocity's
   bATan less `ang`. Below that, `vel` is `head`.
4. It returns `ang`.

**RadianWrap** (0x00139700) is the BAM times 9.58738e-05, less 6.28318
above 3.14159. Its test for below -3.14159 never passes, as the angle
comes in unsigned.

The memories:

- **ZeroSteeringMemory** is Reset(0) on the body's and the heading's
  PidErrors.
- **ClearSteeringMemory** is GetError, then Reset of the body's to
  `head` and the heading's to `vel`.
- **ZeroThrottleMemory** (0x00139bb0) is Reset(0) on the velocity's.
- **ClearThrottleMemory** (0x00139bc0, no caller) is Reset to
  |DesiredSpeed| less VelocityMagnitude.

## GetMovementIndex

GetMovementIndex (0x00139be0) is a jump table (0x002aec10) on
MovementMode - 1:

| MovementMode | Index |
|--------------|------:|
| PHYSICS | 1 |
| MELLOW, under TRAFFIC_CONTROL | 4 |
| MELLOW, otherwise | 0 |
| COP | 2 |
| BELT | 0 |
| TRAFFIC, DELIVERY, anything out of range | 3 |

Indices 3 and 4 are the **fixed** ones (`addiu -3 ; sltiu 2`). Their PID
weights, steer-to distance and steering range come from the arrays rather
than the speed tables.

## CalcSteerToPoint

CalcSteerToPoint (0x0013a438) first takes the distance on:

- With a fixed index it is max(15, ForwardSpeed x SecondsAhead[idx]).
- Otherwise it is PidSteerToTable at ForwardSpeed, x 1.2 for DriverMode 1.

The point then depends on the target:

- With under two target points, the car steers straight ahead. Under
  5 m/s forward that is SteerStraightVector3D: max(5, dist) along the
  heading. Otherwise it is SteerStraightVelocity3D: along the velocity
  (bNormalize to that length).
- Otherwise the point is DriveTarget::InterpolatePoint at the distance.

Only x and y are kept. The SteerStraight functions add all four VU lanes.
The heading's w is a stack word the image never writes, so the checker
compares x, y and z.

## CalcThrottleAndBrake

CalcThrottleAndBrake (0x0013a548) works on the velocity's PidError. It
reads MaxThrottle nowhere.

1. If |(|DesiredSpeed| - VelocityMagnitude)| is not more than the
   tolerance, both pedals are 0.
2. Otherwise `c = (cur x 0.1 + dd x 0.01) + total x 0.02`. `cur` is the
   current error, `dd` the derivative's mean clamped to +-2, and `total`
   the integral's total. `c` is clamped to +-0.25.
3. `f = (Throttle - Brake) + c` is clamped to -0.94 .. 1.
4. A negative `f` is a brake of -f; otherwise `f` is the throttle.

## Drive

Drive (0x00139c48) runs these steps:

1. **The start.** steerDeg is Steering as degrees, signed past 180.
   `dtc` is max(dt, 0.0001). `spd` is VelocityMagnitude, negated when
   ForwardSpeed is below 0.
2. **The point.** CalcSteerToPoint. A point more than 200 m off counts up
   the unread `warned_already` (gp-22576).
3. **The wheels.** `front` is set if wheel 0 or 1 touches, `rear` if wheel
   2 or 3. The steps below need the movement index and GetError's `h` and
   `v`.
4. **The steering**, with a front wheel down:
   - Record `h` into the body's PidError and `v` into the heading's, with
     dt.
   - If a collision of the car's dynamic body is a two-car one,
     ClearSteeringMemory goes through the table, once.
   - **The swap** is set when `h x v < 0`, or when |v - h| is over
     fPsychoCounterDiff and 2|v| < |h|.
   - The PID is the body's when swapped or under 5 m/s forward, else the
     heading's.
   - The steer is `(-cur x kp - dd x kd) - total x ki`, with `dd` clamped
     to +-0.5. A fixed index takes the weights' kp, ki and kd. Otherwise
     they come from the tables at `spd`: kd x 1.2 for DriverMode 1, else
     ki x 0.5.
5. With no front wheel down, the steer is -GetYawAlways.
6. **The clamp.** The steer is clamped to +-pi/4 and kept as `copy`.
7. **The speed's error** is |DesiredSpeed| - VelocityMagnitude. When
   |time left| is over 0.001 it becomes error / time x 0.3. It is recorded
   into the velocity's PidError with dt.
8. **The gears.**
   - No rear wheel down: gear 1, no pedals, ZeroThrottleMemory.
   - |DesiredSpeed| < 2: gear -1, brake 1.
   - Forwards (DesiredSpeed > 0): the latch clears under -7 m/s and sets
     over -2. The gear is -1. Latched, CalcThrottleAndBrake. Unlatched,
     brake 0.5 and steer -copy.
   - Backwards: the latch clears over 7 m/s and sets under 2. Latched,
     steer -copy, CalcThrottleAndBrake and gear 0. Unlatched, brake 1 and
     gear -1.
9. **The wheel**, with a front wheel down:
   - maxA is 45, or for a fixed index the range table at `spd` clamped
     to 0 .. 45.
   - `cur = steerDeg / maxA` and `des = steer / (maxA x 0.017453294)`.
     `des` is clamped to +-1 when fixed and not swapped.
   - Unless swapped on a speed-table index, the step `des - cur` is
     limited to the speed table at `spd` x 0.5 x dtc. That rate is
     doubled when the wheel is heading back towards the middle.
   - `out = (cur + step) x maxA`, times the type's Control.Steering when
     fixed.
10. With no front wheel down, `out` is steer x 57.29578.
11. **The time left** counts down by dt, floored at 0.
12. **The pedals.** Throttle and Brake are stored if allowed, else both
    are 0.
13. **The e-brake.** The timer counts down by dt. While it is above 0 and
    |spd| is over 20 mph (8.940545), it sets EBrake 1 with no throttle or
    brake. Otherwise EBrake is 0.
14. **The output.** DesiredGear is the gear. Steering is `cvt.w.s` of
    out x 65536, `div` by 360. `cvt.w.s` saturates, which the checker
    reaches with a steering ratio in the thousands.

## The seams

- `gBaseCarSoundStartHonkHornFn` and `...StopHonkHornFn` are
  realdriver.h's. `gBaseCarSoundIsHonkingFn` is psychodriver.h's. All
  three are NULL until BaseCarSound is ported, and a NULL one is the
  no-sound answer.
- `psychodriver_static_init` is sinit.c's entry [16].
  `psychodriver_install_vtables` is called from main.c.

AIDriver (11f-2, [ai-driver](ai-driver.md)) builds one for each AI
racer. No car gets one in the game yet: the SkipFE race has no AI racers
until 11g.

## The checker

`tools/psychodriver_check.py` runs the image's methods in mipsemu:

- RadianWrap;
- the constructor, and the destructor through the table;
- SetDesiredSpeed, SetTarget and GetError;
- the four memories and GetMovementIndex;
- Drive, through the table;
- CalcSteerToPoint and CalcThrottleAndBrake;
- the horn, the getters and the setters;
- the two SteerStraight functions.

These run as shipped beneath them:

- ~CarDriver and ~DriveTarget;
- Average, and PidError's Record, Reset and destructor;
- Table;
- bATan, bSinCos and bNormalize;
- the start-up code.

### The stand-ins

Both sides stand in for these, and log each call:

- bMalloc and the frees;
- DriveTarget's constructor, Clear, operator=, Resample and
  InterpolatePoint (a scripted point);
- CollisionBody::GetCollision and Collision::IsTwoCarCollision
  (scripted);
- CarState::GetYawAlways (scripted);
- BaseCarSound's three horn calls (scripted).

The port's CarDriver keeps the demo's table address, so vptrs are printed
by name. A PidError's host size is logged as the console's 40.

### The script

The script covers each area:

- **The tables** at every grid point, an ulp either side, and past the
  ends.
- **RadianWrap** at its edges.
- **SteerStraight** with a -0 z and a vertical velocity.
- **Construction and destruction** with each flag and each PidError
  missing.
- **The small methods.**
- **GetError** about 1 m/s.
- **The memories.**
- **GetMovementIndex** over every mode pair.
- **CalcSteerToPoint** at the target's counts and the speeds' edges.
- **CalcThrottleAndBrake** at the tolerance's and the clamps' edges.

It then drives:

- a run of steps;
- every combination of wheels down;
- collisions;
- the gears about every latch edge;
- the time about 0.001;
- the e-brake about 20 mph and running out;
- the wheel about 180 degrees, dt under 0.0001, and a time left of -0;
- the swap, and its tests met exactly (|v - h| at the counter's diff,
  2|v| = |h|);
- no forward speed;
- 200 m;
- no front wheel down, in each gear;
- a fixed index at up to 175 m/s;
- steering ratios to 40000;
- 150 random drives.

The order of the sums in the steer and in `des` shows only where it moves
the wheel across a BAM. `rounding_drive`'s steps were found by searching
its seeds for ones where it does: three on a fixed index with a steering
ratio of hundreds, and one (15632, of about 15000 tried) on a speed-table
index.

55673 ops, 49373 lines, 0 differ.

### The mutation pass

247 mutations: 238 caught, 3 of them by crashing the harness, and 9
equivalent.

| Mutation | Why it cannot show |
|----------|--------------------|
| rw-le | No BAM is 3.14159 radians exactly: 32767 is 3.141497 and 32768 is 3.1415927. |
| rw-dead | The angle comes in unsigned, so the add below -3.14159 never runs. |
| ni-steer | cardriver_init has already zeroed Steering. |
| ni-zs, ni-zt | The PidErrors are fresh from pid_error_init, which leaves exactly what Reset(0) stores. |
| dd-vt | Nothing derives from PsychoDriver, nothing dispatches before ~CarDriver, and ~CarDriver stores its own vptr. |
| dr-fwd | A DesiredSpeed of 0 has already gone to the \|DesiredSpeed\| < 2 branch. |
| dr-rate-dbl1, dr-rate-dbl2 | With `des == cur` the step is 0 whatever the rate. |

The first pass left 11 alive. Five became equivalents, and the other six
became the "in the air", "fast and fixed", "huge steering" and
"rounding" scenarios. A time left of -0 in a step of 0 then caught
dr-tfloor, first listed as equivalent: the countdown's -0 is not below
0, so it is stored as it is.
