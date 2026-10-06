# DrivingChoice -- which way round the traffic an AI car goes

    0x00241c00  DrivingChoice::GetChoiceType(int)
    0x00241c20  DrivingChoice::GetDrivingLine(DrivingChoiceType, Car *)
    0x00241cf8  DrivingChoice::SetChoice(DrivingChoiceType, Car *, bool)
    0x001cacc8  DrivingChoice::SetChoice(DrivingLocation *)
    0x00245370  DrivingChoice::SetChoice(DrivingChoice *)
    0x002453e0  DrivingChoice::Clear
    0x00245328  DrivingChoice::IsDrivingLine(DrivingChoiceType)
    0x00245318  DrivingChoice::IsSideOfCar(DrivingChoiceType)
    0x00241d40  DrivingChoice::IsValid(DrivingLocation *, NearbyCarList *)
    0x00241e30  DrivingChoice::IsEqualTo(DrivingChoice *)
    0x00242b08  DrivingChoice::IsEnoughRoom(NearbyCar *, NearbyCarList *)
    0x00243160  DrivingChoice::FixupCarToExcludeFromCollisionPrediction(
                    Car *, bool, NearbyCarList *)
    0x002432e8  DrivingChoice::GetPreferredSideOfCar(NearbyCar *,
                    NearbyCarList *, DrivingLocation *)
    0x00243568  DrivingChoice::FillUpDriveTarget(DriveTarget *,
                    DrivingLocation *, NearbyCarList *,
                    MovementWithRespectToLine, bool)
    0x002437e8  DrivingChoice::AddToDriveTarget(float, DrivingLocation *,
                    FuturePoint *, DriveTarget *)
    0x002438b0  DrivingChoice::GetSpeedBackToLine(NearbyCarList *,
                    DrivingLocation *, MovementWithRespectToLine)
    0x00243988  DrivingChoice::ReduceCurrentL(float *, ...)
    0x00244588  AdvancePoint (the walk's, unnamed in retail)
    0x00244768  FuturePointList::Add
    0x002447c0  GetRoutePointsToUse (unnamed in retail)
    0x00244c88  the road-block list: the route's points up to one
    0x001492b0  Race::GracePeriodIsActive(Car *)
    0x00241ea0  DrivingChoice::BuildDriveTarget(DriveTarget *,
                    DrivingLocation *, NearbyCarList *, float, float,
                    MovementWithRespectToLine)
    0x00243aa8  DrivingChoice::BuildDriveTargetAroundCar(DriveTarget *,
                    NearbyCarList *, float, DrivingLocation *)
    0x00243f70  DrivingChoice::MakeDriveTargetParallelToCar (retail's also
                    takes the walk's list)
    0x00244ea0  DoSmoothOffsetChange (retail's takes the walk's list)
    0x002442c0  the clearance beside a car (retail's own)
    0x00244d80  the walk's closest point ahead (retail's own)
    0x002455b0  how far a lateral is off the road
    0x00241ff8  DrivingChoice::IsDriveable(DriveTarget *, bool, float *,
                    Car **, float *, DrivingLocation *, NearbyCarList *,
                    float, float, float, MovementWithRespectToLine)
    0x002428d0  DrivingChoice::TryChoice (static), MakeNewChoice's one try
    0x00242170  DrivingChoice::MakeNewChoice(DriveTarget *,
                    DrivingLocation *, NearbyCarList *, float, float,
                    bool *, bool)
    0x00242c20  DrivingChoice::TryToDriveAroundCar(DriveTarget *, bool *,
                    NearbyCar *, DrivingLocation *, NearbyCarList *,
                    float, float, float, bool)

Steps 11b-2, 11b-3 and 11b-4b of the racer AI. A DrivingChoice is the third part of an AI
car's DrivingInformation (`ai-driving-info.md`): one of the four driving
lines, or one side of a car ahead. Each frame the controller turns its
choice into a DriveTarget (`car-drive-target.md`), the points it steers
at. For a line, FillUpDriveTarget walks the route ahead of the target's
last point and puts a point on the line at each one. On the way it eases
the car back towards the line at a speed that depends on how fast the car
is going. For a side, BuildDriveTargetAroundCar puts a point beside the
car, with room to pass, eases out to it over the points before, and then
follows the line again.

The port is `3DS Files/source/drivingchoice.{c,h}`, with the grace period
in `racecore.c`. AICarController's record, as much of it as these reach,
is in `aicarcontroller.h`.

Choosing the choice itself is step 11b-4b: IsDriveable, TryChoice,
MakeNewChoice and TryToDriveAroundCar. They build and score a target for
each choice they try, and ask CarCollisionPredict (11b-4a,
`ai-collision-predict.md`) which car it runs into.

DoSnapshot (0x00241b88) is the replay's, and GetTextDescription
(0x00241c38) is a debug string.

## The records

DrivingChoice, 12 bytes:

| Off | Field | |
|----:|-------|-|
| 0 | Type | CHOICE_NONE 0, CHOICE_DRIVING_LINE_0..3 1..4, CHOICE_LEFT_SIDE_OF_CAR 5, CHOICE_RIGHT_SIDE_OF_CAR 6 |
| 4 | pCar | the car to pass, for a side |
| 8 | UseExtraLateralDistance | a bool in a word |

FuturePoint, 20 bytes, is one point of the route ahead as the walk finds it:

| Off | Field | |
|----:|-------|-|
| 0 | nRouteNumber | |
| 4 | nPointNumber | |
| 8 | nLine | the driving line there |
| 12 | fOffset | the lateral offset to add to the line there |
| 16 | bCrossedSignpost | the walk took a sign to reach it |

FuturePointList is a count followed by twenty FuturePoints, 404 bytes in
all. The list lives on the stack of whoever walks. Add has no bound of its
own; its callers stop at twenty.

MovementWithRespectToLine has five values:

- TOWARDS_LINE 0
- PARALLEL_TO_LINE 1
- TOWARDS_LEFT_SIDE_OF_TRACK 2
- TOWARDS_RIGHT_SIDE_OF_TRACK 3
- NONE 4

AICarController offsets read here:

| Off | Field |
|----:|-------|
| 504 | CurrentDrivingLocation |
| 508 | CurrentDrivingChoice |
| 516 | CarToExcludeFromCollisionPrediction |
| 532 | CurrentAction (an AIAction, its Type at 588) |

## The constants

| Value | Where | Use |
|------:|-------|-----|
| -0.001 | gp-26600 | IsEnoughRoom: on the road below this amount out of bounds |
| 5.0 | `lui 0x40a0` | the room's margin, and a traffic car's nearness to its line |
| 1.0 | `lui 0x3f80` | near the line, for the bend rule; ReduceCurrentL's edge |
| 50.0 | `lui 0x4248` | far ahead, for the bend rule |
| 0.12 | gp-26592 | a bend's curvature |
| 26.8216362 | gp-26588 | 60 mph in m/s |
| 29.5038013 | gp-26584 | 66 mph in m/s |
| 0.25, 0.5 | `lui 0x3e80`, `0x3f00` | the speeds back to the line |
| -10.0 | `lui 0xc120` | how far past the target's end the walk starts |
| 5 | | the fewest points the walk finds |
| 12.0 | gp-22256 | StartOfRaceGracePeriod |
| 0.5 | gp-22252 | TimeBetweenCarsForGracePeriodExit |
| 4.0 | `lui 0x4080` | UseExtraLateralDistance's extra clearance |
| 5.0 | `lui 0x40a0` | off the road too far to pass; the speed to drive alongside |
| 3 | | the wheels on the ground to drive alongside |
| 0.7071 | gp-26580 | cos 45: heading the same way, to drive alongside |
| -999999, 999999 | gp-26576, gp-26572 | no edge, alongside on a traffic route |
| 1e14 | gp-26568 | the search's first best distance |
| 1/24 | gp-26564 | the search's step: a point skipped per 24 m, less two |
| 2.0, 1.5, 6.0 | `lui 0x4000`, `0x3fc0`, `0x40c0` | the least clearance: any car, a player, a slow car |
| 0 | gp-15152 | AITrafficTuningMode: traffic passes on the other side |
| 20.0 | gp-15120 | AISlowCarSpeed |
| 10.0 | gp-15116 | AISlowTrafficSpeed |
| 99999 | gp-26628, -26620, -26608, -26596 | no hit yet |
| 1.2 | gp-26624 | a preferred choice's score |
| 0.1 | gp-26616 | how much sooner the way round may be hit than the current choice |
| 0.001 | gp-26612, gp-26604 | a score of -1, give or take |
| 20.0 | gp-15136 | TryToDriveAroundCarMinSpeedForDrivingLine |
| 1 | gp-20136 | AICarControllerNumDrivingLinesToConsider |

AITrafficTuningMode, AISlowCarSpeed, AISlowTrafficSpeed and the last two
are `.sdata` words that nothing writes. The names are the
port's; retail has no symbols. AIActionGetUnstuck reads AISlowCarSpeed
too. gp-15124 is a debug word, 0, that gates a loop doing nothing (see
below).

## The small methods

GetChoiceType is `line % 2 + 1`, a signed remainder:

- even lines are DRIVING_LINE_0, odd lines DRIVING_LINE_1;
- line -1 is CHOICE_NONE;
- line -2 is DRIVING_LINE_0 again.

GetDrivingLine is the car type's CarClass (a signed byte at CarTypeInfo
230) times two, plus `type - 1`.

SetChoice stores the three fields only when they agree: a line with no car,
or a side with a car. Anything else leaves the choice as it was. The two
other SetChoices go through it: the location's line's type with no car, or
another choice's three fields. Clear zeroes all three.

IsValid:

- **A line.** The location must not be clear.
  - A racing route (number below 50, compared unsigned so a clear
    location's -1 fails): the route's line for this car (GetDrivingLine
    with the list's car) must have flag 1 or flag 2 set.
  - A traffic route (50 to 69): only DRIVING_LINE_0 is valid.
  - Any other number fails.
- **A side.** The car must be on the nearby list.
- **NONE.** Never valid.

IsEqualTo compares the types. For a side it also compares the cars.

## Room beside a car

IsEnoughRoom:

- A line always has room, and NONE never does.
- For a side, the other car's GetAmountOutOfBounds is asked first.
  - At -0.001 or more, it is off the road, and there is room.
  - Otherwise its route point is asked for. Room is both cars' half
    lengths plus 5 m, and the car's lateral offset across that point is
    measured.
  - Left: there is room when `-LeftWidth < lat - room`.
  - Right: there is room when `lat + room < RightWidth`.

Retail's GetRoutePoint takes a bool, 1 here, that only AICarController's
override reads. The port's `car_get_route_point` has no bool until step
11e.

FixupCarToExcludeFromCollisionPrediction sets the controller's
CarToExcludeFromCollisionPrediction:

1. A line stores NULL. NONE stores nothing.
2. A side with `check` false stores NULL.
3. A side with `check` true starts from "keep the car out of the
   prediction". If the other car is traffic and coming the other way (the
   dot product of the two bodies' x axes is negative), two things undo
   that:
   - its own choice is a side of this car, and the mirror of this one
     (its left against this right, or its right against this left);
   - its current action is PULL_OVER and this choice is the left.

   An absent action counts as NONE.
4. With nothing undone and room beside the car (IsEnoughRoom on its list
   entry), the choice's car is stored. Otherwise nothing is stored.

GetPreferredSideOfCar returns 1 for the left of the entry's car, 0 for the
right. The image never reads its `this`.

1. **The offsets.** The other car's point is FindClosestPointAhead from
   the location's point, or the location's point when none is ahead. The
   other car's offset is its lateral across that point less the line's
   offset there. The car's own offset is measured the same way, across
   the location's point.
2. **The rules, first match wins.**
   - A traffic car passes a car whose offset is under 5 m on the right.
   - With both offsets within 1 m, the other more than 50 m ahead
     (`nc->Position.y`) and the line bending (|GetCurrentCurvatureOfDrivingLine|
     of 0.12 or more), it takes the inside: right for a positive curvature,
     left otherwise.
   - Otherwise it takes the side away from the other car's offset.
3. **The room check.** The chosen side flips when it has no room within
   the road's width at the other car's point (half lengths plus 5 m, as
   above).

## The walk along the route

AdvancePoint moves the walk (route, point, number, offset, crossed, line)
on by one point:

1. **A point with a sign.** The controller's SignPostDecision is asked
   about the sign. It is handed the line by address, which it may change,
   and the controller's location.
   - Before asking, the old line's offset at the point is read.
   - If the sign is taken, the walk moves to the sign's new route and
     point, with `crossed` set. The new offset keeps the car where it
     was laterally: the old point's position on the old line, measured
     across the new point, less the new line's offset there. Returns 1.
2. **Otherwise.** The next point on the route, with offset 0 and `crossed`
   clear. Past the route's last point the result is 0.

The port asks the controller through `gAISignPostDecisionFn` until
AICarController is ported (11e).

GetRoutePointsToUse fills the list with the points to drive past the
target's last one, and sets `*currentL`, where the target ends across the
line:

1. **The count.** It is set to 0.
2. **The start.** With an empty target, the walk starts at the location.
   Otherwise it starts at the target's last point's route and point, on
   that point's line.
   - A racer whose target ends on a traffic route walks its own route
     from the location instead.
   - The walk is advanced until the last target point is less than 10 m
     past the walk's point, measured along the point's direction. If the
     route ends first, the list stays empty.
3. **Where the target ends.** For an empty target this is the car's
   lateral across the walk's point. Otherwise it is the last target point
   across its own route point, or across the walk's point when that has
   none (GetRouteAndRoutePoint fails on a point number of -1). The
   location's line's offset at the walk's point is taken off.
4. **The first two points.** The walk's point is added, then the next one.
   Neither is marked crossed, whatever the walk did.
5. **The rest.** Points are added until the distance runs out. The
   distance starts as the straight line from the car to the walk's point,
   and each point's Length is added before it is passed. The walk stops at
   twenty points, at the route's end, or once the distance passes
   CalculateLookAheadDistance with five points found.

The road-block list (0x00244c88) is the location's route's points from the
location's point up to a given point, on the location's line, offset 0. It
stops at twenty.

## Filling the target

GetSpeedBackToLine:

| Case | Speed |
|------|------:|
| PARALLEL_TO_LINE | 0 |
| towards either side of the track, or the car under TRAFFIC_CONTROL | 0.5 |
| in the start's grace period | 0 |
| speed at most 60 mph | 0 |
| at most 66 mph | 0.25 |
| faster, in a relaxed line switch | 0.25 |
| faster | 0.5 |

Race::GracePeriodIsActive: a car numbered 101 to 149 has its grace cut by
`(n - 100) * 0.5` s. The race's elapsed time, `(WorldTimer - StartTime) /
4000` s, is in the grace period while it is no more than 12 s less that
cut.

ReduceCurrentL:

1. **The move.**
   - Towards the right side, `amount` is added to L.
   - Towards the left side, it is taken off.
   - Otherwise L moves towards 0 by `amount`, stopping at 0.
2. **The clamp.** L is kept within the road, relative to the line's offset
   at the point: `min(hi - off, max(L, lo - off))`, with the EE's `min.s`
   and `max.s`.
   - With `inside`, the bounds are 1 m and the car's half length in from
     each edge.
   - Without it, the bounds are the edges themselves.

AddToDriveTarget places the point at its route point's position, with L
plus the point's line offset as the lateral. It adds the point to the
target with its route, number and line, and with the speed check on. The
location is not read.

FillUpDriveTarget:

1. **The early outs.** It does nothing for a NULL location, target or list,
   or for a clear location. It stores the location's point's terrain type
   in the target's TType (in the delay slot of the next test), then
   stops if the target is full.
2. **The walk.** It walks with GetRoutePointsToUse and takes the speed back
   to the line.
3. **The offsets.** For each point it eases L with ReduceCurrentL, on the
   location's line, then adds the point's offset. Towards the line, a
   crossed sign caps the speed at 0.25 from there on.
4. **The points.** It adds each point with AddToDriveTarget. In
   WilliamsAITuningMode, towards the line, every L is 0.
5. **The exclusion.** It finishes with a choice set from the location and
   a fix-up with `check` false. For a line choice that clears the car to
   exclude.

## Building the target

BuildDriveTarget (0x00241ea0) starts from a copy of my car's own target,
emptied by `Clear(me, 0)`. Then:

- **Not valid** (IsValid): FillUpDriveTarget with the movement asked
  for, inside the edges. It returns 0.
- **A driving line:** a copy of the location, its line set to the one
  GetDrivingLine gives for the choice, then FillUpDriveTarget. It
  returns 1.
- **A side of a car:** BuildDriveTargetAroundCar, and its answer.

Every way ends with FixupCarToExcludeFromCollisionPrediction(me, 0).
The two floats it takes are never read.

### Round a car

BuildDriveTargetAroundCar (0x00243aa8) walks the route as
GetRoutePointsToUse does, which also gives the current L, and finds the
walk's point closest ahead of the car. With none, or with the car 5 m or
more off the road there, it fills up parallel to the line, inside the
edges, and returns 0. Otherwise:

1. **The clearance**, from the function below, plus 4 m when the
   choice's UseExtraLateralDistance is set.
2. **The side:** -1 for LEFT_SIDE_OF_CAR, else +1. A traffic car flips
   it while AITrafficTuningMode is set.
3. **The room:** side times (my half size + its apparent half size +
   clearance).
4. **The passing L:** the car's lateral at the point, plus the room,
   plus the point's offset, held 1 m and my half size inside each edge.
5. **The point beside the car:** that lateral, at the car's distance
   along the point.
6. **The way out:** DoSmoothOffsetChange from the current L to the
   passing L less the line's offset, inside the edges.
7. **The point itself,** on the walk point's route, number and line,
   which LastPointToScore then names.
8. **Alongside:** if the car is a player that is no cop, or is traffic
   while I am not, MakeDriveTargetParallelToCar with the room as its
   side.
9. **The rest:** FillUpDriveTarget parallel to the line, inside the
   edges. It returns 1.

### The closest point ahead

0x00244d80 is retail's own. It starts at an index, taken as 0 when
negative. A point counts when the position is behind it along its
direction (strictly), and the nearest point that counts wins, the first
on a tie. After each point it skips one point for every 24 m of
distance, less two, so a far point jumps over those a car could not be
near. With none ahead it gives -1.

FindClosestPointAhead, which the walk itself uses, is a different
function.

### The clearance

0x002442c0 is retail's own, the clearance wanted beside a car:

- **The gap there is** across the walk: my lateral at its first point
  and the car's at its own point, each less its line's offset and plus
  the point's offset, apart, less both half sizes. With no points, or
  none ahead of the car, it is 0. With no entry the answer is 0.
- **The least gap** is 2 m when I am traffic. Otherwise it is 6 m
  beside a slow car (at most AISlowTrafficSpeed for traffic and
  AISlowCarSpeed for anything else, in either direction), 1.5 m beside
  a player and 2 m beside the rest.

The answer is the larger of the two, so the room asked for is never less
than the room already there.

### The way out

DoSmoothOffsetChange (0x00244ea0) eases the target from one L to another
over the walk's points up to two short of the index, of which there must
be at least two. Each point's L grows with its distance from the first,
measured on each point's line, so the last of them reaches the new L.
No point goes past the new L either way. Each L is then put on its line
with the point's offset added, held 1 m and my half size inside the
edges (or just at them, when not inside), and added with its route,
number and line. It stops when
the target is full.

The slope's divide is the EE's. The first and last points can be in one
place (the same point twice, or a sign's route starting at the sign).
The EE gives FLT_MAX there, which sends every point but the first to the
new L. IEEE's 0/0 would be a NaN.

### Alongside

MakeDriveTargetParallelToCar (0x00243f70) does nothing unless:

- both cars go faster than 5 m/s;
- the other has at least three wheels on the ground;
- their velocities point within 45 degrees of each other.

From the other car's first point (GetFirstPoint) to the end of its own
target, while mine has room, it adds that point's lateral plus the side.
Each is held:

- on a racing route, inside the point's edges;
- on a traffic route, inside the road of my walk: its point closest
  ahead of the route point, whose edges are measured across the route
  point. Each search starts where the last one ended. With no point
  ahead there is no edge.

Each is held 1 m and my half size inside its edges. It goes in on the
other's route, number and line, with AddPointToTarget's check against my
car. That check refuses a point that doubles back, or one behind my car
while the target has fewer than two points.

## Choosing a new choice

### IsDriveable

IsDriveable (0x00241ff8) asks whether a choice can be driven for
`maxTime` seconds without running into anyone:

1. **The answers start** as a score of -1, no car hit, and a hit at 99999.
2. **The target** comes from BuildDriveTarget, with the movement asked for.
   A target that is not built is not driveable, and its score stays -1.
3. **The score** is EstimateScore's for my car. At -1 or below the
   choice is not driveable. Otherwise:
   - a preferred choice's score is multiplied by 1.2, and its car is
     left out of the prediction (the controller's
     CarToExcludeFromCollisionPrediction);
   - any other choice leaves no car out.
4. **The hit** is WhoWillThisDriveTargetHit's, looking `maxTime` ahead.
   The choice is driveable when that hit is later than `maxTime`. A
   target that hits nothing reports 99999, so with `maxTime` at 99999
   nothing is driveable.
5. **Every call**, driveable or not, adds one to the world's
   PotentialDriveTargetID.

The score is tested before the 1.2. A preferred choice scoring between
-1 and -1/1.2 is driveable, but its score ends up below -1.

The first and third floats are never read.

### TryChoice

TryChoice (0x002428d0) is MakeNewChoice's one try. It is static in
retail. It keeps a running best and a way round, both owned by the
caller.

1. **Traffic in AITrafficTuningMode** tries only a side of a racer or of
   a player's car. Any other choice returns 0, and nothing is written.
2. **The hit** starts as no car at 99999. Then IsDriveable runs, towards
   the line. If the choice is driveable and its score beats the best
   score:
   - `*found` is set;
   - the choice and its target become the best;
   - the best's out becomes 0;
   - the score becomes the best score.
3. **The answer** is whether the choice scored: a score more than 0.001
   from -1.
4. **The way round.** A side of the car in the way, without extra
   lateral distance, also becomes the way round when it is preferred.
   Its choice, its target and its hit time are kept.

### MakeNewChoice

MakeNewChoice (0x00242170) picks the choice afresh.

1. **The current choice** is the choice itself when it is valid.
   Otherwise it is the location's line.
2. **With `tryCurrent`, it is tried first.**
   - It is preferred when it is the side GetPreferredSideOfCar gives for
     its car (on the list).
   - It is tried with no car in the way.
   - Its score (the best score, so -1 unless it was found), its hit time
     and its hit car are kept. The hit car becomes the car in the way.
   - A preferred current choice that hit its own car is the way round
     itself, with the target it built.
3. **The lines.** If nothing is found, the first
   AICarControllerNumDrivingLinesToConsider lines are tried, skipping the
   current one, until one is found.
4. **The sides.** If still nothing is found, every car the AI cares about
   (AIDoWeCareAboutThisCar) is tried, found or not.
   - Its left side is tried as preferred when GetPreferredSideOfCar says
     left. Its right side is tried as preferred otherwise.
   - Either is skipped when it is the current choice.
   - If neither scored and the car is coming the other way (the two
     velocities' dot product is negative), the preferred side is tried
     again, with extra lateral distance, as preferred.
5. **The outcome.**
   - **Found:** the best choice, its target, and the best's out (0).
   - **The way round:** if it is valid and the current choice's hit time,
     less 0.1, is no later than the way round's. The way round's choice
     and target are taken, and the out is 1.
   - **Never reached:** the current choice when its score is off -1. That
     score is -1 unless the current choice was found, and then the first
     arm is taken. This arm would build the current choice parallel to
     the line, with an out of 0.
   - **Otherwise:** the location's line, FillUpDriveTarget parallel to
     the line and inside the edges, an out of 0, and 0 returned.
6. **The fix-up** (FixupCarToExcludeFromCollisionPrediction) runs with the
   out as its check.

Without `tryCurrent` the current choice's hit time is 99999. There is no
car in the way then, so no way round is ever set.

### TryToDriveAroundCar

TryToDriveAroundCar (0x00242c20) gets past one car on the list:

1. **The setup.**
   - The side is GetPreferredSideOfCar's for the entry.
   - The target is saved.
   - The current choice is the choice, when it has a type.
   - "Fast" means either car is going faster than
     TryToDriveAroundCarMinSpeedForDrivingLine (20 m/s).
2. **The current choice** is tried with `tryCurrent` when all of these
   hold:
   - it is not a line, unless fast;
   - it is valid;
   - it is not a side, or it is a side of this car.

   It is preferred when it is the preferred side. If driveable, it is
   kept, and the out is whether it was preferred.
3. **The lines.** When fast, the first
   AICarControllerNumDrivingLinesToConsider lines are tried, skipping
   the current one. The first that is driveable is taken, with an out of
   0.
4. **The sides.** The preferred side is tried as preferred, then the
   other side as not preferred. Each is skipped when it is the current
   choice, or when not fast and IsEnoughRoom says there is no room. The
   first that is driveable is taken, with an out of 1 or 0.
5. **Nothing driveable.** The current choice is built parallel to the
   line if it is still valid; otherwise the location's line is. The out
   is left as the caller had it, and 0 is returned.
6. **The fix-up** runs with the out.

Before each IsDriveable the target is put back from the saved copy.
BuildDriveTarget then copies my car's own target over all of it before
reading it. The restores only matter if the target handed in were my
car's own, and retail's callers hand in their action's target (at +32).

## Divergences

Each one is written down where it happens in the source:

- **A missing route at the target's end.** When the target's last point's
  route is not filed, the image reads the Type at address 12 and walks on
  from address 1064. The port leaves the list empty.
- **The road-block list for a clear location.** The image walks from point
  -1 of route -1 up to the end point's index, counted from address 0. The
  port leaves the list empty.
- **FillUpDriveTarget's own DrivingChoice.** The image's is not
  initialised, and SetChoice leaves it so for a negative odd line. The
  port's starts as Clear leaves one.
- **AddToDriveTarget's w.** GetPosition writes x, y and z, and
  AddPointToTarget copies all sixteen bytes, so the image's w is whatever
  was on the stack. The port's is 0 (STACK-W, as in `car-drive-target.md`).
- **`route_numbered`.** The image has no bound above on the route number.
  The port uses `trmgr_get_route`'s bound.
- **BuildDriveTargetAroundCar's entry.** The image reads the car from
  the list's entry with no test. BuildDriveTarget only calls it once
  IsValid has found the car on the list. The port takes a missing entry
  as a car not on the route ahead.
- **DoSmoothOffsetChange's, MakeDriveTargetParallelToCar's and
  BuildDriveTargetAroundCar's w.** Each is STACK-W, as with
  AddToDriveTarget.
- **MakeNewChoice's current choice.** The image never clears it, so a
  location whose line gives CHOICE_NONE (a negative odd line) leaves it
  as the stack had it. The port's starts as Clear leaves one.
- **EstimateScore's distances**, which IsDriveable reaches choice after
  choice in one frame, are static in the port. Retail's are on its stack
  (`car-drive-target.md`).

Retail also tests a debug word (gp-15124, 0) in BuildDriveTargetAroundCar.
When it is set, a loop at 0x002452b0 counts down the walk's points and
does nothing else. The port leaves it out.

## Cross-check

`tools/drivingchoice_check.py` runs the retail image in mipsemu as the
model, against `tools/src/drivingchoice_test.c`, the port over the same
script.

Beneath the functions above, the image runs everything as shipped:

- NearbyCarList::GetNearbyCar;
- DrivingLocation's IsClear and AreWeInARelaxedSwitch;
- GetCurrentCurvatureOfDrivingLine;
- FindClosestPointAhead;
- the route point's GetPosition and GetSignpost;
- the sign's GetNewRoute and GetNewRoutePoint;
- CalculateLookAheadDistance;
- DriveTarget's Assign, Clear, AddPointToTarget, GetRouteAndRoutePoint,
  GetFirstPoint and EstimateScore;
- CarCollisionPredict (`ai-collision-predict.md`) and
  AIDoWeCareAboutThisCar;
- IsPointAheadOfCar and bNormalize2.

The model runs with the EE's divide. The script divides by zero at five
sites, and the checker stops if any other site takes the EE's path:

- DoSmoothOffsetChange's slope (0x00245050);
- WillIHitThisCar's two steps along a leg of 0 (0x001e65ec, 0x001e65f4);
- EstimateScore's two for a car at rest (0x0021d204, 0x00258914).

EstimateScore keeps its twenty distances on its stack, and a stale pick
reads them (`car-drive-target.md`). The port keeps them static. The model
saves the 80 bytes when EstimateScore returns and puts them back when it
is next entered, so the two read the same words.

Three stubs print a line each, so both sides must ask the same questions
in the same order:

- SignPostDecision answers the script's take-or-not and line.
- Car::GetRoutePoint answers the script's point.
- Car::GetAmountOutOfBounds answers the script's amount.

The grace period's two globals start as the image's data has them, so
`racecore.c`'s initialisers are compared too.

There are sixteen kinds of scenario here. CarCollisionPredict's four are
in its own document.

| Scenario | What it covers |
|----------|----------------|
| s_small | the small methods over every type, line and car class worth trying, negative and huge lines among them |
| s_valid | IsValid over routes numbered 0 to 49, 50 to 69, 70 and up, negative and past 99 |
| s_room | IsEnoughRoom, the fix-up and the preferred side, beside cars on and off the road, facing either way |
| s_bend | the preferred side on smooth routes, both ways round: curvatures from 0.09 to 0.3, offsets either side of 1 m and 5 m, and a car past the route's last point |
| s_walk | AdvancePoint across signs taken and not; GetRoutePointsToUse from empty targets, from targets ending on every route, and from a racer's target ending on a traffic route with no point number; the road-block list |
| s_fill | FillUpDriveTarget for every movement, inside the edges or not, with the tuning mode on and off, signs taken at no speed, and NULL arguments |
| s_speed | GetSpeedBackToLine either side of 60 and 66 mph, and the grace period's edges |
| s_reduce | ReduceCurrentL either side of every bound |
| s_around | BuildDriveTarget for a line, a side and neither, round cars of every kind on and off the road and past a sign, with the traffic tuning mode on and off and the slow speeds moved |
| s_pieces | the closest point ahead from anywhere and any start, the clearance beside cars either side of each slow speed, the way out to every index either way, and alongside a car level with mine |
| s_sign_pass | round a car just past a sign onto a route a metre or two to one side, so the walk's points there carry an offset |
| s_back | the way out over a walk that doubles back, and alongside a car on a traffic route whose own target runs back down the walk |
| s_choose | the four choosers among four other cars (ahead on the line, oncoming, alongside, stopped, off the road), each with a box and a target of its own: from every choice, with the current one tried first and not, the lines to consider, the speed for them either side of what matters, and the traffic tuning mode on and off |
| s_jam | MakeNewChoice and TryToDriveAroundCar in a jam: a car just ahead in my lane under 5 m/s or not, one oncoming in the next lane, and the current choice mostly a side of the car ahead. My car sometimes backs at under 1 m/s, so that a preferred score falls below -1, and the longest times take in 0 and 99999 |
| s_pass | MakeNewChoice going past oncoming cars at 15 to 50 m/s, so that one swerve fits its corners and the other does not |
| s_tie | the way round's `<=`: a current choice that hits at exactly 0.1f and a way round that hits at once (see below) |

Step 11b-3's script ran 71 scenarios, 46212 ops and 79543 lines, with 0
differ. CarCollisionPredict's checks are in the same checker
(`ai-collision-predict.md`); with them, step 11b-4a's ran 98 scenarios and
97,604 lines. Step 11b-4b's runs 231 scenarios, 105,136 ops and 151,404
lines, still 0 differ.

s_tie is one scenario, built rather than drawn. With nothing found,
MakeNewChoice goes round the car in the way when the current choice's hit,
less 0.1, is no later than the way round's. `<=` and `<` part only where
the two are one float, and no drawn scenario met that. The 59th s_jam from
seed 11, with every longest time 99999 so that nothing is driveable, comes
close at its third MakeNewChoice: the current choice hits the oncoming car
0.083 s on, and the way round hits at once. Car 2's speed was then bisected
over its floats until the current choice's hit was 0.1f exactly. That is
0x40cab904 (0x40cab903 works too, and the floats either side do not). The
scenario stops after that call.

The mutation pass has 741 mutations: 730 caught (27 of them by a crash or
a hang) and 11 equivalent, with 0 unexplained.

DrivingChoice's share up to 11b-3 is 385 mutations: every constant, every
comparison's sense and bound, each store, each field read, the grace
period's initialisers, the three globals and the EE's divide. 383 are
caught, 22 of them by a crash or a hang. CarCollisionPredict's 207 are all
caught (`ai-collision-predict.md`).

Step 11b-4b's share is 149 mutations over IsDriveable, TryChoice,
MakeNewChoice, TryToDriveAroundCar and EstimateScore's static distances.
140 are caught, one by a crash. The first pass left 19 alive:

- s_jam caught four of them (id-ok-lt, mn-round, mn-round-target,
  mn-line-pref) once its cars had route points.
- s_tie caught mn-rle.
- A hundred s_choose scenarios caught mn-opp-side, mn-opp-extra and
  mn-opp-pref. With 24, the oncoming car never had both sides fail and
  its wider way round win.
- s_pass caught mn-tried-or.
- ta-pref-left and ta-cur-pref fell to the full script.

The other 8, and the two from before, are equivalent:

- `fx-its-side` drops the side-of-car test on the oncoming car's choice.
  The two tests it guards accept only LEFT and RIGHT, so every other
  type fails them anyway.
- `sm-full` drops DoSmoothOffsetChange's test for a full target.
  AddPointToTarget refuses a point then, and nothing else is written.
- `tc-hittime-init` changes TryChoice's first store to the hit time.
  IsDriveable's first lines store DC_NO_HIT there again before anything
  reads it.
- `mn-line-way` hands TryChoice no car in the way for a line choice.
  TryChoice reads that car only after its side-of-car test, and a line
  returns there.
- `tc-scored` makes "scored" `|score + 1| < 0.001` instead of `<=`. The
  two part only where |score + 1| is 0.00100000005f (0x3a83126f). For a
  score from -2 to -0.5 the subtraction is exact (Sterbenz), so
  |score + 1| is a multiple of 2^-24. That float is 8589935 / 2^33, an
  odd mantissa at 2^-33, so no such score reaches it. Any other score is
  at least 0.5 from -1, and a NaN fails both.
- `mn-third` drops MakeNewChoice's third arm. That arm needs the current
  choice's score off -1, and the score is bestScore read straight after
  the current try. TryChoice moves it only when it sets found, and then
  the first arm is taken.
- `ta-saved` and the four restores (`ta-cur-restore`, `ta-line-restore`,
  `ta-first-restore`, `ta-second-restore`) touch the saved copy of the
  target. Each restore is followed at once by IsDriveable, whose
  BuildDriveTarget first copies the driver's own target over all 528
  bytes. Retail's callers hand in their action's target (+32), never the
  driver's, so the copy is never read.
