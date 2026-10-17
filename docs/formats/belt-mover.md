# BeltMover

`BeltMover.obj` (0x00204098 .. 0x002056b4), all of it; `DoSnapshot` came
with the replay, TASKS 72c. Step 11e-6 of the
racer AI, after [AICarController](ai-car-controller.md), whose Think puts
a car on the belt.

Ported to `3DS Files/source/beltmover.{c,h}`. Cross-checked by
`tools/beltmover_check.py` against `tools/src/beltmover_test.c`, with the
retail image (SLES_507.31) running in mipsemu as the oracle.

## The shape of it

A BeltMover is the cheapest mover an AI car can have. It does not
integrate anything. The car rides a **belt**, a QuickSpline through the
points of its driver's DriveTarget, and its place on the belt is a
quadratic in the belt's own clock:

    u(t) = v + t (dv + t ddv)

Here `u` is the spline's parameter, in control points. `t` is the seconds
since the belt was last set (`fTime`). `v`, `dv` and `ddv` are set by
FindCoordinates each time the controller resets the belt, which
AICarController::Think does every think it keeps the car there.

Each frame, Move:

1. advances `fTime` and puts the car on the curve;
2. eases its heading towards the tangent half a second on (a tCubic2D);
3. slides it out of the bend by how hard the belt turns 0.3 s on (a
   second tCubic2D, and an Average of the sideways acceleration);
4. moves it across the belt by a tCubic1D the slide steers.

It then writes the CarState outright, places the four Wheels for drawing
and skids, and tells the controller when the belt drops away under the car.

`Car::SetMovementMode`'s BELT_MOVEMENT arm (mode 6) builds one
([car-modes.md](car-modes.md)). AICarController::Think sends a car there
when WeNeedTheBelt and WeCanHaveTheBelt: an AI car far from every player,
driving fast and straight enough on an ordinary action
([ai-car-controller.md](ai-car-controller.md), "The belt").
CalculateMaxAcceleration asks the belt for the slope
([ai-driving-info.md](ai-driving-info.md)).

## The record, 72 bytes

The mdebug record's names. The port's host record is wider, and
`carmodes.h`'s BELTMOVER_SIZE is `sizeof(BeltMover)`.

| Off | Field | Type |
|----:|-------|------|
| 0 | Mover | `CarMover`: Driver at 0, vptr at 4 |
| 8 | pCar | `Car *` |
| 12 | fTime | `float`, seconds since FindCoordinates |
| 16 | fScale | `float`, control points a metre |
| 20 | pSpline | `QuickSpline *`, EXTRAPOLATED, OVERHAUSER, 20 points |
| 24 | pCubicU | `tCubic1D *`, the offset across the belt |
| 28 | v | `float`, the parameter at fTime 0 |
| 32 | dv | `float`, its rate |
| 36 | ddv | `float`, the `t^2` term |
| 40 | pCubicAng | `tCubic2D *`, the heading, eased |
| 44 | pCubicSlide | `tCubic2D *`, the slide out of a bend |
| 48 | pAvgAccel | `Average *`, 30 samples of sideways acceleration |
| 52 | bSliding | `int32_t` |
| 56 | pWheels[4] | `Wheel *` |

A tCubic1D is the frontend's spline, 48 bytes (`BSpline`), and a tCubic2D
is two of them, 96 bytes (`BSpline2D`); see
[frontend-animation.md](frontend-animation.md).

The mover seeks them with retail's `cPoint::SplineSeek`, which takes two
clamp limits. The tCubic1D form is at 0x001daec8, and the tCubic2D form at
0x001db000 seeks x and then y. The limits gate ClampDerivative and
ClampSecondDerivative, each only when its limit is over 0. Every seek the
mover makes passes 0 for both, so neither clamp ever runs, and banim's
`bspline_seek`, which leaves the clamps out, is the same.

### The table

`_vt$9BeltMover`, 0x002bb090, CarMover's layout:

| Slot | Method | Address |
|-----:|--------|---------|
| 8 | destructor | 0x002043a0 |
| 16 | Move | 0x00204d78 |
| 24 | DoSnapshot | 0x00204468, TASKS 72c: v, dv, ddv, fTime, fScale, bSliding, the three cubics raw (48, 96, 96 bytes), the spline at three floats a point, the Average, the four Wheels |

ClearCalculatedVariables (0x00204460) and DebugScreenPrint (0x002053a0)
are `jr ra`. The port keeps the first, because the constructor calls it.

## The tuning

The `.lit4` pool, gp-27744 to gp-27684, plus the physics' gravity:

| gp | Value | Use |
|---:|------:|-----|
| -27744 | 0.4 | the constructor's yaw rate scale |
| -27740 | 0.3 | the slide cubic's starting durations |
| -27736 | 0.005 | FindClosestParam's tolerance |
| -27732 | 0.899 | the fraction of the desired speed the belt aims at |
| -27728 | 0.4 | the heading cubic's durations |
| -27724 | 0.9 | SlideCoef's lower knee |
| -27720 | 1.1 | its upper knee |
| -27716 | 0.3 | the slide cubic's durations when the slide ends |
| -27712 | 1.6 | the slide's rate when it ends |
| -27708 | 0.1 | AverageAir's step |
| -27704 | 0.1 | AverageAir's scale |
| -27700 | 0.002 | the air that takes the car off the belt |
| -27696 | 2400.5 | Timer::SetTime(0.6), folded: 0.6 s in ticks |
| -27692 | 0.3 | the slide's look-ahead in seconds |
| -27688 | 9.5873795e-05 | BAM to radians (0x38c90fda, a hair under 2π / 65536) |
| -27684 | 0.0001 | the smallest `dt` Move divides by |
| -19912 | 9.8 | gravity |

### The two Graphs

`_GLOBAL_$I$fBeltAccelCoef` (0x002055c8) builds two four-point Graphs, at
gp-16592 and gp-16584, over the points at 0x0031b9d0 and 0x0031b9f0. The
port has them as data:

| Graph | Points |
|-------|--------|
| BeltSlideGraph (not sliding) | (0, 0), (18, 0.1), (22, 0.4), (30, 0.7) |
| BeltSlidingGraph (sliding) | (0, 0), (14.5, 0.4), (16.5, 0.6), (30, 1.0) |

SlideCoef moves points 1 to 3 along x on every call, so the points are
not const, and whatever was last written stays.

fBeltAccelCoef (gp-16600, 1.0) is the same unit's, but only
CalculateMaxAcceleration reads it. It stays in nearbycar.c.

## Construction and destruction

**The constructor**, `__9BeltMoverP3Car` (0x00204098), sets every word
but the Driver, which SetMovementMode's tail stores:

1. `pCar`, `ddv`, `dv`, `v`, `fScale` and `fTime` to 0; `bSliding` to 0;
   the vptr.
2. Five bMallocs, each passing `..\indep\src\beltmover.cpp` and its line,
   on pool 16 (CAR_MEMORY_POOL):
   - line 124: an Average of 30;
   - line 126: a QuickSpline, EXTRAPOLATED, OVERHAUSER, 20 points;
   - line 127: the tCubic1D;
   - line 128: the heading's tCubic2D;
   - line 129: the slide's tCubic2D.

   Each cubic is constructed inline: its four values 0, flags 1, duration
   and arrival threshold 1, state 0. The time and the coefficients are
   left as bMalloc gave them. The first seek is a new one and writes both.
3. The heading cubic starts on the car's velocity along its heading:

        s    = VelocityMagnitude,   a = Angle,   b = Angle + 0x4000
        lat  = s * (AngularVelocity.z * 0.4)
        val  = (s cos a, s sin a)
        dval = (lat cos b, lat sin b)

   SetVal and SetdVal, the tCubic2D's inline pair. The image divides 360
   by nothing on the way (`beql a2,zero ; break`, with a2 holding 360): a
   check the compiler left in, which nothing reaches.
4. The slide cubic's two durations are 0.3, y first.
5. Four Wheels, from Wheel's `new` (bOMalloc on WheelSlotPool). Wheel `i`
   takes the type's `Wheels[i]`, `Tires[i / 2]`, its `Control` and the
   car's CarState.
6. ClearCalculatedVariables.

**The destructor** (0x002043a0):

1. Its own vptr.
2. The Average and the QuickSpline through their destructors (flags 3),
   each when set.
3. The three cubics through `__builtin_delete` (bFree), unchecked.
4. Each Wheel that is set, through its own table's destructor (slot 8,
   flags 3). The pointers are left as they were.
5. `j _$_8CarMover` with this call's flags: the delete is CarMover's.

## The belt

### SetBelt

0x00204990:

1. The across-belt cubic's flags go to 0, so its next aim starts at once.
2. The driver's DriveTarget is resampled (`DriveTarget::Resample`).
3. Its points become the spline's control points, x, y and z, with a w
   of 0. ControlPointsDirty is set after each one.
4. FindCoordinates.

A belt of fewer than two points is set again by Move before it moves.

### FindCoordinates

0x00204718:

    fTime  = 0
    fScale = NumControlPoints / DriveTarget.Length        (the EE's divide)
    i      = FindClosestControlPointFrom(Position, 0)
    v      = FindClosestParam(Position, i, 0.005)
    a, b   = Dot(Position, v)             point less Position, tangent
    normalise b
    dv     = fScale * VelocityMagnitude
    f      = (fScale * GetDesiredSpeed()) * 0.899 - dv
    ddv    = f / GetDesiredTimeToSpeed()   when that is over 0
           = f / 0.5                        otherwise
    max    = fScale * GetMaximumAcceleration()
    if max < ddv:  ddv = max
    else:          ddv = max(ddv, fScale * -20)

GetDesiredTimeToSpeed is read twice, once for the test and once for the
divide.

The across-belt cubic is then aimed at where the car is:

    side = b × (0, 0, 1)
    SetVal(-(a · side));   SetdVal((Velocity · side) * 0.5);   duration 0.5

The heading cubic's two durations are 0.4.

A DriveTarget with no length (no points, or all on one spot) makes
`fScale` the EE's quotient, FLT_MAX. The port divides the same way
(`ee_div`).

### GetPoint, GetDerivative and GetSecondDerivative

0x002053a8, 0x00205458 and 0x002054d8, the belt `t` seconds on:

    u   = t (t ddv + dv) + v
    du  = (t + t) ddv + dv
    P   = spline(u)                    held up to control point 0's z for u < 0
    P'  = spline'(u) * du
    P'' = spline'(u) * (ddv + ddv) + spline''(u) * (du * du)

Each scales all four lanes. GetPoint's floor applies only before the
start: there the extrapolated spline can dip below the first point, and the
car is kept no lower.

### Dot, GetAccelerationDueToGravity and GetMaximumAcceleration

- **Dot** (0x002045b8) answers `(P(t) - pos) · P'(t)` over xyz, leaving
  the difference in `a` and the tangent in `b`, four lanes each.
- **GetAccelerationDueToGravity** (0x00204668) answers 0 for a spline with
  no control points. Otherwise it normalises the tangent at `v` (the
  parameter at the last FindCoordinates, not the car's current one) and
  answers `-9.8 * z`.
- **GetMaximumAcceleration** (0x002046f0) is CalculateMaxAcceleration at
  `dv / fScale`, the car's speed when the belt was set.

## SlideCoef

0x00204a30, given the Average's sideways acceleration:

    sign = accel / |accel|                          (the EE's divide)
    need = (Mass * |accel|) * ((rear.ForceScale + front.ForceScale) * 0.5)
    down = (dv / fScale) * ((FrontDownforce + RearDownforce) * 0.5)
    grip = the two tyres' Dynamic friction, halved, when sliding
           the two Static ones, halved, when not
    hold = (down + 9.8 * Mass) * grip

The Graph is BeltSlidingGraph when sliding and BeltSlideGraph when not,
picked on the flag as it was on the way in. Its points 1, 2 and 3 move to
`hold * 0.9`, `hold * 1.1` and `hold * 1.5`.

The car slides when `hold < need`. When that changes:

- **Starting to slide** sets the slide cubic's durations to 1.
- **Stopping** sets them to 0.3 and multiplies its rate (`dVal`) by 1.6.

The answer is `sign * Graph(need)`.

A belt as straight as a ruler averages no sideways acceleration at all.
The sign is then the EE's 0/0, FLT_MAX, and the Graph's value at 0 is 0.

## AverageAir

0x00204bd8. How far the belt drops away under the car over the next `dt`
seconds:

    g   = (dv / fScale) * ((FrontDownforce + RearDownforce) * 0.5)
    g   = g / Mass + 9.8
    p   = GetPoint(fTime),  d = GetDerivative(fTime)
    pz, dz, last, sum = p.z, d.z, 0, 0
    for i = 1 .. 9:
        s   = (dt * i) * 0.1
        tau = s - last
        z   = tau * (tau * -g + dz) + pz      the car thrown from the last touch
        h   = z - GetPoint(fTime + s).z
        if 0 < h:  sum += h
        else:      last, pz, dz = s, the point's z, GetDerivative's z there
    return sum * 0.1

The throw has no half on its `t^2` term: `tau * (tau * -g + dz)`, as
shipped.

## Move

0x00204d78, through slot 16:

1. **The belt.** A spline of fewer than two points is set again
   (SetBelt).
2. **Leaving the ground.** `old` is the car's position. When
   `AverageAir(0.5) > 0.002`, the controller's OffBeltTimer (AICarController
   +568) is set to 2400 ticks, 0.6 s (`Timer::SetTime`, folded to the
   `cvt.w.s` of 2400.5).
3. **The clock.** `fTime += dt`, and

        speed = (dv + ddv * fTime) / fScale       (the EE's divide)

4. **The heading.** The tangent at `fTime + 0.5` becomes the heading
   cubic's desired value (x and y). The cubic seeks by `dt`, and its value
   replaces the tangent's x and y. The tangent's z and w stay.
5. **The slide.**

        t    = fTime + 0.3
        side = normalise(P'(t) × (0, 0, 1))
        Record(side · P''(t))                  the Average of 30
        k    = speed * (SlideCoef(Average) * 0.3)
        S    = side * k

   S's x and y become the slide cubic's desired value. The cubic seeks by
   `dt`, and its value replaces S's x and y.

   Between the two, the image calls GetddVal on the across-belt cubic at
   `time / duration`, a plain divide, and drops the answer.
6. **The angle.** `Angle = bATan(d.x + S.x, d.y + S.y)`, the heading plus
   the slide. All four lanes of the sum are made, and only two read.
7. **Across the belt.** `side = normalise(P'(fTime) × (0, 0, 1))`. The
   across-belt cubic's desired value is `-slide` (SlideCoef's answer), and
   it seeks by `dt`. Then:

        Position = P(fTime) + side * cubic.Val       all four lanes

   Car::PutFlatOnTrack and CarState::CalculateGeometryPosition follow.
8. **The yaw rate.** AngularVelocity is `(0, 0, Δ)`, where

        Δ = (int16)(newAngle - oldAngle) * 2π/65536 / dt     (the EE's divide)

   The image's fourth word is whatever its stack held. The port stores 0,
   and the checker masks it.
9. **The velocity.** `vel = Position - old`, four lanes, from the position
   after PutFlatOnTrack. When `|dt| <= 0.0001`, `vel` is normalised to
   `speed` (bNormalize). Otherwise each lane is multiplied by `1.0 / dt`.
   Velocity is `vel`. ForwardSpeed and VelocityMagnitude are both `|vel|`.
   MatrixValid is 0.
10. **The wheels.**

        lng = speed - vel · BodyMatrix.v0
        lat = -(vel · BodyMatrix.v1)

    For each wheel `i`, Wheel::SetStateFromCarState runs with these
    arguments:

    - angle: `WheelAngle[i] + WheelAngularVelocity[i] * fTime`;
    - angular velocity: `speed / Wheels[i].Radius`;
    - steering: the driver's Steering for a wheel whose WheelNumber is
      under 2, else 0, through `cvt.w.s`;
    - suspension height: 0.

    `WheelSlip[i]` is `(lng, lat)` and `WheelTractionUsage[i]` is 0. A
    rear wheel (WheelNumber 2 or more) also takes:

    - its Slip as `(lng, lat)`;
    - Slipping as `bSliding`;
    - CurrentSlip as `lng`.
11. **Skids.** When ShouldVisualEffectsBeGenerated and the closest player
    is under 200 m, each wheel's MaybeMakeSkids runs with `dt`.
12. Car::ComputeFakeRPM, and `dt` is returned.

### What the image leaves to the stack

- **`up`'s fourth word.** Both cross products build `up` as three stores
  and leave the fourth word to the stack. The cross product keeps the
  first argument's w, so that word is never read. The port stores 0.
- **AngularVelocity's w.** The image leaves it to the stack.
- **MaybeMakeSkids' second argument.** The skids loop passes `a1` as it
  happens to be. The port's stand-in takes only the wheel and `dt`.

## The seams

The mover sits above the controller and the nearby-car code in the link,
so three function pointers reach it. main.c sets all three at boot with
`beltmover_install_seams()`:

| Seam | Header | Caller |
|------|--------|--------|
| `gBeltMoverCtorFn` | carmodes.h | SetMovementMode's BELT_MOVEMENT arm |
| `gBeltMoverSetBeltFn` | carmodes.h | AICarController::Think, each think it keeps the belt |
| `gBeltMoverGravityFn` | nearbycar.h | CalculateMaxAcceleration, in BELT_MOVEMENT |

`beltmover_install_vtables()` installs the table.

## The checker

`tools/beltmover_check.py` runs the image's constructor, its destructor
through the table, Dot, GetAccelerationDueToGravity, GetMaximumAcceleration,
FindCoordinates, SetBelt, SlideCoef, AverageAir, Move through the table,
GetPoint, GetDerivative, GetSecondDerivative and GetddVal.

These run as shipped beneath them:

- QuickSpline, Average and Graph;
- tCubic1D and tCubic2D;
- bSin, bCos, bATan and bNormalize;
- the start-up code that builds the two Graphs.

### The stand-ins

Both sides stand in for these, and log each call:

- bOMalloc, and Wheel's constructor, SetState, MaybeMakeSkids and its
  destructor (through a fake table);
- DriveTarget::Resample;
- CalculateMaxAcceleration;
- Car::PutFlatOnTrack, which lifts the car by a scripted step, so Move's
  velocity is seen to come from the position after it;
- CarState::CalculateGeometryPosition;
- ShouldVisualEffectsBeGenerated, World::GetDistanceToClosestPlayer and
  ComputeFakeRPM;
- ~CarMover;
- the driver's GetDesiredSpeed (136) and GetDesiredTimeToSpeed (144).

The scripted values are CalculateMaxAcceleration's answer, PutFlatOnTrack's
step, ShouldVisualEffectsBeGenerated and the distance to the closest
player.

### Allocation

The model's bMalloc fills a block with 0xcd. It clears quickspline.cpp's
block, as quickspline_check's does, because the port's QuickSpline clears
its buffer and allocates one point more.

The harness logs host sizes of the Average and the QuickSpline as the
console's.

### The script

The script writes the CarState, the type, the driver's DriveTarget and its
Steering. It pokes the mover's own words, the cubics' fields and the
spline's control points' w, and dumps every word Move writes: the mover,
its five cubics, the Average, the spline's points, both Graphs, the
CarState's position, velocity, yaw, speeds, slips and traction, the
controller's timer and each wheel's slip.

Three things in the car keep reads apart that would otherwise agree:

- The DriveTarget's points carry a w, which SetBelt must not copy.
- The car's ForwardSpeed is a little under its VelocityMagnitude, so a
  read of one for the other shows.
- The car's position has a w, which Move's velocity takes the old
  position's of.

The scenarios cover:

- **Construction:** six cars.
- **Belts:**
  - a straight belt, a hill and a bend of 150 frames;
  - a crest the car leaves, which sets the timer. AverageAir is asked
    every other frame over 0.5 s, Move's, and over 0.7 s, where
    `(dt * i) * 0.1` and `dt * (i * 0.1)` round apart;
  - a belt the car starts behind, over a floor that falls away;
  - a hairpin, where the car is nearest point 3 but point 0 is nearer than
    point 1, so the closest point is the one found from 0;
  - belts of one, two, three and twenty points;
  - 24 random belts.
- **FindCoordinates:**
  - every way to its `ddv`;
  - a most acceleration under the floor, which the floor leaves alone;
  - a most acceleration that ties `ddv` exactly, below the floor. A
    standing car, a scale of 0.5 and a time to speed of 1 make `ddv`
    exact.
- **The EE's divides:**
  - a DriveTarget of no length, so the scale is FLT_MAX;
  - a standing car that wants nothing, whose tangents on the belt's clock
    are all 0, so every normalise divides by 0;
  - a Move at a scale of 0, so the speed is 0/0, FLT_MAX. Wheels of a
    metre and no downforce keep everything after it from overflowing,
    which the EE clamps and the host would not.
- **The fourth lanes:** the spline's w overwritten after SetBelt, so it
  runs through the getters, the cross products, the normalise and the
  car's place.
- **SlideCoef:** the knees and the exact grip either side.
- **Move:**
  - `dt` at and around 0.0001;
  - wheel numbers in and out of order;
  - the skids either side of 200 m;
  - a Move that sets the belt itself.
- **The destructor:** with each pointer cleared.

6049 ops, 34239 lines, 0 differ.

### The mutation pass

277 mutations: 271 caught, 8 of them by crashing the harness, and 6
equivalent.

The constants, the Graphs' points, every helper and every method are
mutated, and so are banim.c's GetddVal and tCubic2D methods. The six that
survive are:

| Mutation | Why it cannot show |
|----------|--------------------|
| cross-z | Every cross product here is against (0, 0, 1), so its z is a zero either way. Only the zero's sign changes, and the zero is added to a nonzero sum or multiplied into another zero. The standing scenario, all zeros, shows no word move. |
| del-vptr | Nothing derives from BeltMover, so its destructor is reached only through its own table, and the vptr already holds it. |
| sb-dirty | SetNumControlPoints has set ControlPointsDirty just before, and nothing in the loop clears it. |
| air-h-le | `h` is exactly 0 only for a `dt` of 0. Every step is then the car's own point, and the touch the else branch records is the one it already has. |
| mv-s-w | Only the sum's x and y are read, by bATan. |
| mv-steer | The steering goes back to 16 bits through `cvt.w.s` and a halfword store, which give the same bits for 65535.0 and -1.0. |

The first pass left 30 alive, and each became a scenario or one of the
six. The fixes:

- A ForwardSpeed apart from VelocityMagnitude, and a w on the car's
  position.
- AverageAir asked every other frame over the crest.
- The hairpin, the two `ddv` ties, the three divides and the w lanes.
