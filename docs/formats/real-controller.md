# RealController -- the controller a human's car is given

    0x00224388  TrackedController::TrackedController(Car *)
    0x002243d8  TrackedController::~TrackedController
    0x002243f0  TrackedController::Think(float)
    0x002244e0  TrackedController::SetCurrentRoute(TrackRoute *, TrackRoutePoint *)
    0x00224500  TrackedController::GetCurrentRoute
    0x00224530  TrackedController::FindWhereIAm
    0x00224660  TrackedController::JustReset                      jr ra
    0x00224668  TrackedController::GetAmountOutOfBounds
    0x00224730  TrackedController::GetAcceleration
    0x00224738  TrackedController::GetCurrentRoutePoint
    0x00224740  RealController::RealController(Car *)
    0x00224840  RealController::~RealController
    0x002249a0  RealController::PlayerDriveLineNumber
    0x002249b8  RealController::RouteDeltaPredict
    0x00224c60  RealController::ComboPredict
    0x00224db8  RealController::Think(float)
    0x00224ff8  RealController::CalculateLateralPostionAndVelocityWRTDrivingLine
    0x001c1458  DriveTargetRenderer::DestroyTargetMarkers
    0x001c14c0  DriveTargetRenderer::SetTargetToRender(DriveTarget *)

`Car::SetControlMode(REAL_CONTROL)` builds a RealController. The
controller builds the RealDriver that reads the pad, and every frame it
hands that driver a DriveTarget. The target is where the car will be if it
keeps its current lateral speed relative to the driving line for its
class. The pad does not steer by it. The driver's own code reads the
target, and so does the drive target renderer when the camera follows this
car.

TrackedController is RealController's base. It keeps the car's place on
the route network: the point it is on, refreshed every 0.1 s, and the car's
acceleration over that time. `Car::GetTrackedAcceleration` reads that
acceleration, and it is all car.c reads of the controller.

The port is `3DS Files/source/realcontroller.{c,h}`, with TrackedController's
record in `carcontroller.h` so that car.c can reach `Acceleration`. The
renderer's flag-off path is in `drivetargetrenderer.{c,h}`. `main.c`
installs both tables at boot and sets `gRealControllerCtorFn`, and
`REALCONTROLLER_SIZE` is now `sizeof(RealController)`. It is cross-checked
by `tools/realcontroller_check.py` against `tools/src/realcontroller_test.c`,
with the image running in mipsemu as the oracle.

The two DoSnapshots (the demo's 0x00224458 and 0x002248c8, retail's
0x0023a0f0 and 0x0023a560) came with the replay, TASKS 72c. The tracked
one moves the CarController, the route point by route and index, and
three floats; RealController's empties the driving line's spline when
taking or restoring, then moves the offset, its Average and the previous
route points, and the TrackedController's goes last. Not ported: the renderer's flag-on path, which
builds WorldObjects.

## The records

TrackedController, `Tt2611=s36`:

| Off | Field |
|----:|-------|
| 0 | CarController: pCar, Driver, vptr |
| 12 | RoutePoint |
| 16 | TimeBeforeUpdate |
| 20 | Acceleration |
| 24 | PrevSpeed |
| 28 | pCaffeineObj, 64 bits: the editor handle, kept as a pointer and the word after it |

RealController, `Tt2673=s84`:

| Off | Field |
|----:|-------|
| 0 | TrackedController |
| 36 | PreviousLateralOffsetFromLine |
| 40 | LateralVelocityWRTLineAverage (`Average *`) |
| 44 | NumPreviousRoutePoints |
| 48 | PreviousRoutePoints, four NearestRoutePointInfo |
| 80 | DrivingLineSpline (`QuickSpline *`) |

On a 64-bit host the fields after the base sit at 64, 72, 80, 88 and 152,
and the record is 160 bytes. The header asserts every offset.

## TrackedController

**The constructor** runs CarController's constructor and zeroes RoutePoint,
Acceleration and both words of pCaffeineObj. It stores the vptr and then
calls FindWhereIAm with a `jal`, not through the table. It leaves
TimeBeforeUpdate and PrevSpeed for FindWhereIAm to write. It does not set
the driver; RealController's constructor does that.

**Think** subtracts dt from TimeBeforeUpdate and stores the result. While
that is still above 0 it returns. Once it is not:

    Acceleration = (VelocityMagnitude - PrevSpeed) / (0.1 - TimeBeforeUpdate)

The divisor is the period that just ended: 0.1 plus the overshoot. Then
FindWhereIAm runs **through the table** (slot 72). Think does not reset
PrevSpeed itself; FindWhereIAm does. The three 0.1s are separate pool
entries, one per function: gp-27292, -27288 and -27284.

**FindWhereIAm** first searches the current point's own route with
`FindClosestPoint(route, pos, 24, 34, DistanceAroundTrack)`. Flags 34 are
`TRFIND_POSTED_ONLY | TRFIND_BY_TRACK_DISTANCE`, and the distance is the
car's `TheTrackPathCoordinate.DistanceAroundTrack`. It drops the result if
the car is more than 5 outside that point's road. If there is then no
point, it asks `GetNearestRoutePoint(ALL_RACING_ROUTES, 34)`. The
countdown and PrevSpeed are reset whatever happened.

The out-of-bounds sum is shared with GetAmountOutOfBounds, and each has it
inline:

    f = (pos.x - P.x) * Dir.y - (pos.y - P.y) * Dir.x
    0 < f ?  f - RightWidth  :  -(f + LeftWidth)

It is negative inside the road. **GetAmountOutOfBounds** reaches the point
through the table's GetCurrentRoutePoint and answers 0 with no point.

**SetCurrentRoute does not read the route.** It sets the countdown back to
0.1, stores the point and takes the car's speed. **GetCurrentRoute** is the
manager's slot for the point's own RouteNumber, or NULL with no point.

## RealController's lifetime

**The constructor** runs TrackedController's constructor, zeroes the
lateral offset and stores the vptr. It then makes three bMallocs on pool
16:

| Size | Name | What |
|-----:|------|------|
| 640 | RealDriver | the pad's driver, into CarController::Driver |
| 24 | AverageInRealController | an Average over 8 |
| 40 | QuickSplineInRealController | QuickSpline(EXTRAPOLATED, OVERHAUSER, 4), then SetNumControlPoints(0) |

It then sets NumPreviousRoutePoints to 0 and **zeroes only the first two**
of the four route points: the loop counts from 1 down to 0.
NumPreviousRoutePoints is 0, so nothing reads the other two before they are
written.

**The destructor** stores the vptr. It destroys the driver through the
driver's own table (slot 8), then the Average, then the spline, each with
flags 3 and each skipped if NULL, and none cleared afterwards. Last it runs
`~TrackedController` with the caller's flags.

**PlayerDriveLineNumber** is the car's CarClass shifted left by one: the
driving line for the class.

## Think

Think is slot 32. In order:

1. A DriveTarget on the stack, constructed.
2. TrackedController's Think, called directly.
3. GetCurrentRoute and GetCurrentRoutePoint, both through the table.
4. `dt = max(dt, 0.001)`, as `max.s`.
5. If `pPlayer->bWrongWay` is 0 (Car+24, then Player+736):
   - one GetNextRoutePointAhead into a copy of the route and point, whose
     result nothing reads;
   - with a route and a point, CalculateLateral. If that returns 1, then:
     with ForwardSpeed at least 10, RouteDeltaPredict and then
     BlendWithCurrentAcceleration; otherwise StraightLinePredict.
6. If nothing was predicted: with ForwardSpeed at least 10,
   FillWithCurrentAcceleration; otherwise StraightLinePredict.
7. The driver's SetTarget, through its table.
8. If the car's DriverNumber equals CameraFollowThisCarInstead, the
   renderer's SetTargetToRender.
9. With `DoSpeedDifferencePrinting` set and a point, the image passes
   VelocityMagnitude less the line's speed to Car::PrintAbove as a double.
   PrintAbove is empty in the retail build, and in car.c, so only the flag
   is ported.

**The blend in step 5 does nothing.** BlendWithCurrentAcceleration's
second test returns at once for a car with a Player, and Think has
already read through pPlayer for bWrongWay. So a human's target is never
blended, and the call is dead in the shipped game. The port keeps it.

GetCurrentRoute is the manager's slot for the point's own RouteNumber. So a
point whose route the manager does not hold gives a route of NULL and a
point that is not NULL. Step 5's test then sends Think to step 6.

CameraFollowThisCarInstead is -1 on the disc, so step 8 does not run in a
normal race. SetTargetToRender tests `RenderDriveTargetPoints` (0x003242c8)
first, and that is 0 on the disc. With the flag off, the renderer only
destroys its markers if it has any. The port has that path. The flag-on
path aborts.

## CalculateLateral

`CalculateLateralPostionAndVelocityWRTDrivingLine`, typo included, fits a
spline through up to four points on the driving line. It returns the car's
signed distance from the spline and the running mean of that distance's
rate of change.

1. **The points kept from earlier calls**, oldest first. Only the ones
   IsValid accepts are used. Each is placed on the line with
   `GetPosition(point, 0, lineOffset)`.
2. **Then on from the newest kept point**, one GetNextRoutePointAhead
   past it, or from `p` if there is no valid newest point. This carries on
   while there is room and the step stays valid.

   With none kept, the image tests `prev[-1]`. That is the eight bytes
   before the array: the Average's pointer and the count of 0, which is
   never valid. The port tests the count instead, with the same answer.
3. **Fewer points than the spline's MinControlPoints**: offset 0, velocity
   the Average's current mean, return 0.
4. Otherwise the points become the spline's control points, with w = 0 and
   the dirty flag set on each. `FindClosestParam(position, 0, 0.1)` finds
   the nearest point on the spline. The offset is the plane distance to
   it, negated when the line lies against the body matrix's second row.
   `(offset - previous) / dt` goes into the Average, and the mean comes
   back as the velocity.
5. **Keep `p` as the newest point**, unless it already is. When all four
   are full, the rest shift down one. When at least one point is kept, a
   NULL route returns before it is stored. With none kept the code would
   store a NULL route, but it never gets that far: IsValid refuses a NULL
   route, so there are no points and step 3 has already returned.

The line's offset at a point is read at the image's own byte offsets: `lh`
at `48 + 2 * line`, shifted left 8 and scaled by 2^-16, which is Q8. The
speed is `lbu` at `90 + line`. A line past the table reads the next field,
as the image does, rather than past a C array.

## RouteDeltaPredict

This walks ahead from `p` until it has used up the look-ahead distance or
the target holds 20 points. At each step it adds the driving line's point,
shifted sideways by `pos`, and moves `pos` on by `vel`:

    step = ((np - prev) . prev.Direction) / VelocityMagnitude
    pos  = pos + vel * step
    vel  = vel < 0 ? vel + step : vel - step      lateral speed decays towards 0
    lat  = lineOffset(np) + pos
    lat  = max(lat, half - LeftWidth)             max.s
    lat  = min(RightWidth - half, lat)            min.s
    AddPointToTarget(GetPosition(np, 0, lat), route, index, line, unchecked)
    travelled += prev.Length

`half` is half the car-space bounding box's y extent. If the walk runs off
the end, the target is cleared and StraightLinePredict starts again. A NULL
route with a point is an end too. GetNextRoutePointAhead leaves both as they
are, and only the route's half of the test catches it. The distance test
comes after the add, and it is strict.

Three things are as the compiler has them:

- **The line number is converted as unsigned.** A `bltz` guards the
  `srl`/`or`/`add.s` fix-up, and `cvt.w.s` converts it back each pass. For
  a class of 0 to 4 the round trip is exact.
- **The point's index** is the byte distance times 0xb6db6db7, shifted
  left 12 and arithmetic right 16: bits 4 to 19 of the product, 7's inverse
  applied to a multiple of 16.
- **The route number is `lb` at 10**: RouteNumber's low byte,
  sign-extended.

**Each point's pad is garbage on the console.** `GetPosition(bVector3)`
stores all four VU0 lanes, and the fourth comes from two stack words (12(sp)
and 44(sp)) that the function never sets. `trpoint_get_position3` leaves the
pad alone, so the port's pad is the car position's (STACK-W, as in
`drivetarget.h`). Nothing reads a target point's pad.

## ComboPredict

**No `jal` in the image reaches it, and it is not virtual.** It is ported
anyway, because it is small and whole, and its fall-through is what showed
the DriveTarget bug below. It runs RouteDeltaPredict when all four of these
hold:

- the car's normalised velocity against the point's direction is past 0.99
  (gp-27280);
- |vel| < 6;
- |pos| < 12;
- the line's speed at the point, times 0.7 (gp-27276), is below
  VelocityMagnitude.

Otherwise it runs FillWithCurrentAcceleration.

## What the image check found in DriveTarget

**FillWithCurrentAcceleration's first test was the wrong way round, in the
port and in `drivetarget_check.py`'s model both.** The image is:

    0020a074  mul.s  $f0,$f0,$f1        |Velocity| * 0.75
    0020a078  c.lt.s $f0,$f2            < |Acceleration| ?
    0020a080  bc1f   0x0020a098         no: integrate
    0020a088  jal    StraightLinePredict

The acceleration is trusted only while it stays under three quarters of the
speed. Past that, a straight line is used. The port and the model had
the opposite, and agreed with each other, so drivetarget_check passed and
its `fi-dominates-flipped` mutant was killed for the wrong reason. The
first ComboPredict that fell through, with no acceleration at all, showed
fifteen points in the image and one in the port.

Both sides are fixed, and the model's comment says how the error was found.
Every `fi` fixture was re-derived so that it reaches the branch its label
names. Two fixtures are new: `fi still`, a car with no speed and no
acceleration, which integrates until the twenty-point wall stops it, and
`fi ratio over`. The wall is no longer redundant: without it, `fi still`
never ends. So `fi-no-wall` is caught now, and its EQUIVALENT argument is
gone. See `car-drive-target.md`.

The lesson belongs in CONTINUE.md's list. **A model written from the
disassembly can share a misreading with the port.** A check that runs the
image cannot. Most of task 25's checkers are models.

## Checking it

    python tools/realcontroller_check.py
    python tools/realcontroller_check.py --mutate

```
realcontroller_check  14096 ops, 25318 lines, 0 differ
                      140 mutations, 129 caught, 11 equivalent, 0 unexplained
```

The model runs the image's own code for everything beneath the two
classes: CarController, RealDriver and CarDriver, DriveTarget's methods,
the AI route helpers, TrackRoute's search, Average, QuickSpline and bMath.
The harness links the port's. Only the edges are stood in for on both
sides:

- bMalloc logs its name, size, flags and pool and hands out blocks from
  one heap. The harness maps each of the port's sizes to the image's:
  RealDriver 640, Average 24, QuickSpline 40, and the spline's buffer 16
  less.
- The joystick calls exit, because a controller in these scenarios never
  reaches the pad.
- SetMovementMode and RadialBlurOff log their arguments.

Car, CarTypeInfo, Player and the collision body are poisoned with a fill
byte and only the fields the script sets are real, so a read of anything
else shows up as a difference. The routes live in one arena, laid out the
same way on both sides, as airoute_check lays them out.

**What is not compared.** A DriveTarget point's pad: see RouteDeltaPredict
above, and STACK-W in `drivetarget.h`.

The scenarios:

- both tables, slot by slot;
- the constructors over two fills, on a route and off every one;
- TrackedController's methods, and its Think across the update period;
- every path of FindWhereIAm, and GetAmountOutOfBounds either side of both
  widths;
- FindWhereIAm on a traffic lane of known width: exactly 5 past it, just
  past that, inside and outside the radius, on both sides;
- PlayerDriveLineNumber;
- RouteDeltaPredict over targets already holding 0 to 20 points, every
  exit (a NULL route with a point among them), both clamps, and a
  signposted branch onto routes 9 and 11;
- ComboPredict either side of each of its four tests, with accelerations
  either side of FillWithCurrentAcceleration's bar;
- CalculateLateral over its history filling and shifting, invalid points,
  NULL routes, and the too-few-points exit before and after the Average is
  fed;
- Think down a 48-point S-curve, wrong way, at speeds either side of 10
  and at exactly 10 with nothing predicted, fast, off the end of a route,
  off every route, on a point whose route the manager does not hold, with
  the camera on it, with printing on, and at dt either side of the floor;
- every vtable slot on both classes;
- the destructor with each of its three pointers cleared, under each
  flag.

### What the mutation pass found

The first pass left nineteen survivors. Eight were gaps in the script, and
each has a fixture now. The other eleven are equivalent.

**The gaps:**

- **FindWhereIAm's drop, three mutants, and its radius.** network()'s
  routes have random widths. When the drop fired, the fallback over the
  racing routes found the same point again, so dropping it or not came to
  the same thing. A traffic lane 14 wide on each side now sits beside a
  racing route. The fallback cannot return the lane's own point, so a drop
  shows. The car stands exactly 5 past the width, 5.5 past, 18 away and 4
  past, 22 away, and 26 away, on each side.
- **RouteDeltaPredict's route test.** A NULL route with a point is the only
  case it decides, and nothing passed one.
- **Think's route test.** It takes a point whose route the manager does not
  hold. With the history kept from the frames before, CalculateLateral
  would fit it, and RouteDeltaPredict would then end on the NULL route.
- **Fill at a ForwardSpeed of exactly 10.** Every frame at exactly 10 had
  predicted.
- **CalculateLateral's too-few exit after feeding.** Every earlier exit
  came before the Average had been fed, so its mean was 0 either way.

**The eleven equivalents**, each argued in the checker's `EQUIVALENT`:

- **Slot 72 through the table or called directly.** No class overrides
  FindWhereIAm. The only three tables that hold it, TrackedController's,
  RealController's and CopDriver's (0x00298d68), all hold 0x00224530.
- **The constructor's SetNumControlPoints(0), and CalculateLateral's
  per-point dirty flag.** QuickSpline has already done both, in Setup and
  in SetNumControlPoints.
- **The destructor's vptr.** `~TrackedController` stores its own before
  anything reads it.
- **RouteDeltaPredict's look-ahead test.** The look-ahead is at least
  AIDriverDefaultLookAhead, 20.0.
- **The Clear at the end of the route.** StraightLinePredict starts with
  the same Clear, and a second Clear writes the same three fields.
- **The line's unsigned round trip.** It is exact for every line below
  2^24.
- **MinControlPoints.** An EXTRAPOLATED spline's is 2.
- **Think's unread GetNextRoutePointAhead.** It writes only its own copy.
- **The blend.** See Think.
- **The renderer's guard.** DestroyTargetMarkers makes the same test.

The first pass ran from a copy of the tree, because the harness links
`drivetarget.c` and DriveTarget's own pass was mutating that file at the
time. Every checker finds its sources from its own path, so a copy of
`tools/`, `3DS Files/source/`, the ELF and the two bundles it reads is
enough.

