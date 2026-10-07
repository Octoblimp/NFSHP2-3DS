# TrafficDriver: the traffic car's controller

`TrafficDriver.obj` (0x0018c380 .. 0x0018d070; the demo's starts at
0x00183f70) and `_vt$13TrafficDriver` (0x002b4730). This is step 11h-2.
SetControlMode builds one for a car under `TRAFFIC_CONTROL`, which is
every car the traffic teleporter puts on the road.

Ported to `3DS Files/source/trafficdriver.{c,h}`, all but DoSnapshot
(0x0018c478), which waits on ReplaySnapshot. Cross-checked by
`tools/trafficdriver_check.py` against `tools/src/trafficdriver_test.c`,
with the image as the oracle.

A TrafficDriver is an AICarController (see
[ai-car-controller](ai-car-controller.md)) with a PsychoDriver (see
[psycho-driver](psycho-driver.md)) for its driver, as an AIDriver is (see
[ai-driver](ai-driver.md)). Unlike AIDriver it does not use
AICarController's Think. It has its own:

- **One frame in twelve.** A traffic car thinks on its own frame: the odd
  frames of twelve whose half is its place among the traffic.
- **Six actions, not ten.** No AvoidRoadBlock, Pass, Draft, NudgeCar or
  Block. The best of the six is kept in one pass: each step is tried while
  the best so far is below its global, and taken when it scores higher.
- **Its own speed.** The action's, but never over 24.59 m/s, nor over
  0.328 m/s for each metre to the next hairpin sign, nor over 10 m/s
  through a sharp bend.
- **Two sets of routes.** It takes routes 50 to 59 or 60 to 69, as
  PickLowNumberedRoutes says.

## The record, 736 bytes

AICarController's 720, then one bool:

| Off | Field | Type |
|----:|-------|------|
| 720 | PickLowNumberedRoutes | int32 bool |
| 724 | (the round-up) | 12 bytes |

The record is rounded up to the quadword that AICarController's
vPreviousLinePoint aligns it to. **Retail's SetControlMode (0x00131410)
bMallocs 736** for it, as for AIDriver. The demo's stab (type#2598, 720
bytes) had a CurrentAction of its own at 704, ahead of the bool. Retail's
methods use AICarController's (532).

The demo's SetControlMode asks 720, and `carmode_check` runs the demo's,
so its malloc hook maps `sizeof(TrafficDriver)` back to 720
(CM_IMG_TRAFFICDRIVER). `carmodes.h`'s TRAFFICDRIVER_SIZE is
`sizeof(TrafficDriver)`. The header's layout check holds only for a 4-byte
pointer.

## The table

`_vt$13TrafficDriver` has seventeen entries, the header included.
TrafficDriver's own slots:

| Slot | Address | Method |
|-----:|---------|--------|
| 8 | 0x0018c418 | destructor |
| 24 | 0x0018c478 | DoSnapshot, NULL in the port |
| 32 | 0x0018c4d8 | Think |
| 80 | 0x0018cb10 | JustReset |
| 112 | 0x0018cae8 | GetRouteNumbersToUse |

Every other slot is AICarController's, in the same place as in
`aicarcontroller_vt`. ChooseNewAction (120) is AICarController's `jr ra`.
Nothing calls it for a traffic car, because Think is TrafficDriver's own.

## The constructor (0x0018c380)

1. AICarController's constructor (0x00190140) on the car, then the vptr.
2. `bMalloc(624, "PsychoDriver", 0, 16)`, and PsychoDriver's constructor
   (0x00139760) on it and the car; it goes into the controller's Driver
   (4).
3. ForceCurrentAction (528) = AIACTION_NONE (11), PickLowNumberedRoutes =
   1, CurrentAction (532) = NULL.
4. SecondsBeforeNextActionEvaluation (524) = `(float)CarIndex x
   -0.0142857153` (gp-30032, -1/70). Car 0's clock starts at -0.0, and
   each later car's 1/70 s further back, so their thinks fall 1/70 s
   apart (for a traffic car the clock is not read; see Think).

`trafficdriver_construct` is `gTrafficDriverCtorFn`'s shape, (memory,
car), and main.c sets the seam at boot.

## The destructor (0x0018c418)

The vptr; the driver, when there is one, through its own table (vptr at
556, slot 8) with flags 3; then a jump to ~AICarController (0x001903a0)
with the caller's flags. The driver pointer is not cleared.

## Think (0x0018c4d8)

1. **PrintAbove.** When CameraFollowDefaultCar (gp-21532) is 0 and the
   car's DriverNumber (`lh 10`) is not CameraFollowThisCarInstead
   (gp-21528), retail calls Car::PrintAbove (0x0018d078) with a string.
   PrintAbove ships empty (`jr ra`), so the port leaves the call out.
2. `secs -= dt`, stored at once.
3. **Whose turn.** For a car whose driver's TheDriverType (car->MyDriver,
   +8) is DRIVER_TYPE_TRAFFIC_CAR (3):
   - `m = WorldLoopCounter % 12`, by `div` and `mfhi`. The remainder
     takes the counter's sign.
   - An even `m` is not a turn.
   - `m >> 1` (arithmetic) is the car's place among the traffic. It is a
     turn when `m < TotalNumCars - TrafficCarPos` (world+28, +40) and
     `CarTable[TrafficCarPos + m]` (world+44) is this car.

   The clock is not read. So six cars share the twelve frames, two frames
   apart, and a negative counter looks below TrafficCarPos.

   For any other driver type, it is a turn when `secs <= 0`.
4. Not a turn: return.
5. DoStickyDecisions (0x00191b30), then `secs += 0.2` (gp-30028).
6. NearbyCarList::BuildArray (0x00193898) on the DrivingInformation's list
   (this+12), the CurrentDrivingLocation (504) and
   AIDriverSecondsToLookAhead (gp-20328, 2.0).
7. GetCurrentTrackRoutePoint(this, NULL) (0x001921f8). When the
   CurrentDrivingLocation is then clear (no route), Think returns.
8. **No action:** a new JustDrive at AIActionJustDriveScore (gp-18272, 0)
   with a lifetime of -1.
9. **An action:** its UpdateStatus (0x001c6a98) with the information, and
   then the cascade, below.
10. **The driving line.** When the CurrentDrivingChoice's (508) Type is a
    driving line (1 to 4, DrivingChoiceTypeIsDrivingLine at 0x0018d038),
    take `line = DrivingChoice::GetDrivingLine(type, car)` (0x00241c20).
    If that is not the location's DrivingLine, SetDrivingLine(loc, line,
    0), and HighlightDrivingLine (0x001cb450) with the location and
    GetMyDriverNumber.
11. ExecuteCurrentAction, by `jal`, not through the table.

### The cascade

`best` is the action's Score (592), or -1 when it is time to change
(`aiplan_time_to_change`, 0x001cab48: Status SUCCESS or FAILURE, or EXPIRED
with CanExpire). The out slots
start as the stack has them: the hit car NULL, the car to avoid NULL,
AvoidCars' seconds 0.0, okay 1, usedPreferred 0, and the DrivingChoice
Cleared (0x00130920).

Each step runs only while `best` is below its global, and it is taken
when its CalculateScore answers more than `best`. To take a step, the
current action is deleted through its table (slot 8, flags 3), a new one
is made by bOMalloc on AIActionSlotPool (inline, no NULL test), and
`best` becomes its Score:

1. **GetUnstuck** (below AIActionGetUnstuckScore, 500), and only when
   more than two seconds have passed since
   LastTimeNonGetUnstuckActionWasCalled (544): `2.0 < (float)(int32)
   (WorldTimer - [544]) x 0.000250000012`. 8000 ticks are exactly 2.0, so
   8001 is the first that passes. New GetUnstuck(s,
   AIActionGetUnstuckLifetime, -1.0), and WorldTimer into 544.
2. **AccidentRecovery** (below 500). New (s, -1.0).
3. **IJustGotHit** (below 400), `aijustgothit_calculate_score(info,
   &hit)`. MaybeHonkAndOrBlinkHeadlights(this, hit, the list), after the
   delete. Then new (s, AIActionIJustGotHitLifetime, hit).
4. **AvoidCars** (below 400), `aiavoidcars_calculate_score(info, &car,
   &choice, &secs, &okay, &used)`. New AvoidCars(s,
   AIActionAvoidCarsLifetime, car, `(float)(uint32)okay`, used, 0). Then
   the choice is copied into the information's MyDrivingChoice
   (this+492), MaybeHonk(this, car, the list), and the car is taken off
   its belt.

   **AIDriver's quirk is here too, and the port keeps it.** The bool
   `okay` goes in as the float seconds (converted unsigned), `used` as
   okay, and 0 as usedPreferred. The seconds AvoidCars gives back are
   never read.
5. **PullOver** (below 600). New PullOver(s, -1.0,
   AIActionPullOverTrafficCarTimeout (gp-18160, -999), CurrentNearbyCarList
   (512), CurrentDrivingLocation (504)). Then the car is taken off its
   belt.
6. **JustDrive** (below AIActionJustDriveScore). New (s, -1.0).

**Off the belt:** a car whose TheMovementMode (car+36) is TRAFFIC_MOVEMENT
(2) is set to MELLOW_MOVEMENT (4) by Car::SetMovementMode (0x00131618).

Each step's global is read afresh, so a step can run even though an
earlier one was taken, if that one's score is still below its global.
Retail then tests the action for NULL and makes a JustDrive. That cannot
happen, since every step replaces the action it deletes. Last comes
~DrivingChoice with flags 2, which does nothing.

Compared with AIDriver's ChooseNewAction, there is no forced type and no
ShouldWeAvoidThisCar. GetUnstuck waits 2 s, not 6, with no "very stuck"
minimum. A step must beat the best so far, not only score 0 or more. And
AvoidCars honks after making its action, not before.

## GetRouteNumbersToUse (0x0018cae8)

With PickLowNumberedRoutes, `*first = 50` and `*last = 59`. Otherwise 60
and 69.

## SetDirection (0x0018d030)

Stores PickLowNumberedRoutes whole. Nothing in retail calls it.

## JustReset (0x0018cb10)

1. If MyDrivingLocation (this+476) has a route, PickLowNumberedRoutes =
   `(uint32)(RouteNumber - 50) < 10`. **The route of MyDrivingLocation,
   not CurrentDrivingLocation**: the two are the same unless something
   has pointed 504 elsewhere.
2. The action, if any, deleted through its table (flags 3).
3. ClearStickyDecisions (0x00191d10).
4. A new JustDrive at AIActionJustDriveScore, lifetime -1.
5. ExecuteCurrentAction.

## ExecuteCurrentAction (0x0018cb98)

1. The action's CalculatePointsToDrive (its table's slot 24) with the
   information.
2. When GetMyDriverNumber is CameraFollowThisCarInstead,
   DriveTargetRenderer::SetTargetToRender (0x001cb600) on
   TheDriveTargetRenderer (0x00314630) with the action's PointsToDrive
   (action+32).
3. CalculateDesiredSpeed, into three floats zeroed first.
4. The driver's SetTarget (its table's slot 64) with the points, then its
   SetDesiredSpeed (slot 56) with the speed, the time, the tolerance and
   the action's AllowedToUseThrottleAndBrake (580).
5. ClearPointsToDrive (0x001caa60).

## CalculateDesiredSpeed (0x0018cc78)

Takes (float *speed, float *time, float *tol). All three are zeroed
first, `most = 24.5865002` (gp-30020) and `give = 0`.

**A hairpin.** When the CurrentDrivingLocation has a route, the location's
point is found by number, and the scan goes from there:

- At each point with a sign (not 255): if its Flags have
  SIGNPOST_HAIRPIN (0x20) and not SIGNPOST_BACKWARDS (0x08), this is the
  hairpin, and the distance is the lengths summed so far.
- Otherwise the point's Length is added and the scan moves on. It stops
  when the sum is 75 m or more (`lui 0x4296`), after 19 points
  (`cvt.w.s(18.75)`: offsets 0 to 18), or at the route's end.
- A start at or past the route's end scans nothing.

With a hairpin, `give = 2` and `most = distance x 0.32782` (gp-30016).
Within 10 m (`distance < 10`), the location takes the sign's route:
SetRoute(loc, the sign's NewRoute, its NewPoint, line 0, not relaxed).
PickLowNumberedRoutes is then `RouteNumber < 60`, or `-1 < 60` (true)
when that route is not loaded.

A route that is not loaded leaves retail's point at `1064 + 112 x
NewPoint` off NULL; the port's is NULL. Nothing reads a point without a
route.

The scan stops short of 75 m, so the most a hairpin allows is under
24.5865 (75 x 0.32782), which is the top speed.

**A bend.** When the action has three points or more (NumPoints, signed,
at action+32), take p0 = Points[0], pm = Points[n / 2] and pn =
Points[n - 1]. `in = pm - p0` and `out = pn - pm` in x and y, each
bNormalized (0x002588a0). When `in . out < 0.639999986` (gp-30012, a turn
of more than about 50 degrees), `most = 10` and `give = 2`. The bend
overrides the hairpin's most, even a smaller one.

**Then:**

- `most = max(most, 10)`.
- With the action's UseDrivingLineSpeed (576): `*speed = most`, `*time =
  0`, `*tol = give`.
- Otherwise the action's DesiredSpeed (564), TimeToGetToDesiredSpeed (568)
  and DesiredSpeedTolerance (572).
- `*speed = min(*speed, most)`.

## In the port

- `trafficdriver_install_vtables` is called from main.c, and main.c sets
  `gTrafficDriverCtorFn = trafficdriver_construct`.
- **The game does not make one yet.** Traffic cars come from the
  TrafficTeleporter (11h-3), which is not ported.

## The checker

`tools/trafficdriver_check.py` runs the image's constructor, destructor,
Think, JustReset, GetRouteNumbersToUse, ExecuteCurrentAction,
CalculateDesiredSpeed and SetDirection in mipsemu. Running under them as
shipped:

- PrintAbove and DrivingChoiceTypeIsDrivingLine;
- DrivingChoice's Clear and destructor;
- DrivingLocation's IsClear, SetRoute, SetDrivingLine and
  SetRelaxedSwitch;
- the route point's GetSignpost and the sign's GetNewRoute and
  GetNewRoutePoint;
- GetMyDriverNumber and bNormalize.

`tools/src/trafficdriver_test.c` runs `trafficdriver.c` with
`drivinglocation.c`, `trackroute.c` and their support. Both sides stand
in for the following, and print each call:

- AICarController's constructor (which sets the car and its vptr) and
  destructor, DoStickyDecisions, ClearStickyDecisions,
  GetCurrentTrackRoutePoint (which leaves the location alone, clears its
  route or puts it on a route) and MaybeHonk;
- PsychoDriver's constructor, which gives the driver a test table whose
  destructor, SetDesiredSpeed and SetTarget print;
- BuildArray, SetMovementMode (which stores the mode), GetDrivingLine (a
  set line), HighlightDrivingLine, SetTargetToRender, UpdateStatus (a set
  Status and CanExpire) and ClearPointsToDrive;
- the six CalculateScores, each answering a set score and writing the outs
  a mask allows;
- the six action constructors, printing their arguments and giving the
  action a test table whose CalculatePointsToDrive fills its points and
  speeds;
- bMalloc and bOMalloc.

The record is printed field by field after each op. So are the location
the driver points at and MyDrivingLocation, and the current action's
type, score and status. Cars, routes, points, signs and actions are
printed by name.

The scenarios:

- the table and the globals, at the start and the end;
- the constructor and destructor with each flag, over junk, at car indices
  from -32768 to 32767; the destructor with no driver, and called directly
  with AICarController's vptr in place;
- GetRouteNumbersToUse and SetDirection;
- whose turn:
  - another driver type's clock at its edges: dt equal to the clock, an
    ulp either side, and -0 against 0;
  - the clock run down;
  - the constructor's stagger;
  - a traffic car over counters -30 to 30 and the extremes, in eighteen
    world layouts, with the car at, past and before the traffic's end;
- the look-ahead, PrintAbove's test, the route found or not;
- no action, at four JustDrive scores;
- the cascade:
  - each status with and without CanExpire;
  - each gate with the current score a point either side of its global,
    and its own score a point either side of that;
  - each global moved;
  - the order, with each step's score the best the later gates see;
  - GetUnstuck's two seconds a tick either side, and wrapped; its stamp;
  - the lifetimes and the timeout;
  - IJustGotHit's car;
  - AvoidCars' okay over every way through the unsigned conversion, and
    each out alone;
  - off the belt in every movement mode;
  - PullOver's list and location;
- the driving line for choice types -1 to 6, the line equal and not, with
  the two locations' lines apart;
- ExecuteCurrentAction:
  - the camera's car;
  - the speeds, the time, the tolerance and the throttle passed through;
- CalculateDesiredSpeed:
  - a clear location;
  - each kind of sign (hairpin, backwards, not a hairpin, cloaked, an
    unloaded route) at each place in the scan;
  - lengths around the 10 m and 75 m edges;
  - the route's end;
  - the take into routes numbered 49 to 70 and the extremes;
  - the bends for 0 to 20 points and past 127;
  - the cosine's edge in 241 steps, and exactly 0.64 (an out of (16,
    sqrt(369)));
  - zero halves;
  - the speeds;
  - a hairpin and a bend together;
- JustReset over route numbers 48 to 69 and the extremes, a clear route,
  each location, with and without an action;
- 400 random rounds.

72743 ops, 31387 lines, 0 differ.

### The mutation pass

230 mutations: 226 caught, 11 of them by crashing the harness, and 4
equivalent.

| Mutation | Why it cannot show |
|----------|--------------------|
| fallback | Every step replaces the action it deletes, so the action is never NULL after the cascade. |
| cs-bend-most | `max(most, 10)` follows, so `min(most, 10)` and 10 both come out at 10. |
| cs-dls-speed | The most is never over 24.5865: the scan stops short of 75 m, and 74.9999924 x 0.32782 is 24.586498. |
| cs-n-unsigned | A DriveTarget has at most 20 points. Past 127 the mutant reads memory before the points, which the two sides do not share; neither finds a bend there. |
