# AICarController -- the controller of a car the AI drives

    AICarController.obj    0x00190140 .. 0x00194058
    _vt$15AICarController  0x002b4d90    17 entries (8 bytes each)
    CarController::SetToPhysicsMode    0x001c0100

AICarController is the base of AIDriver's and TrafficDriver's controllers
(steps 11f and on; AIDriver is in [ai-driver](ai-driver.md),
TrafficDriver in [traffic-driver](traffic-driver.md)). It keeps
four things:

- the car's DrivingInformation: its nearby cars, where on the route it is,
  and the choice it drives by;
- the AIAction it is carrying out (`docs/formats/ai-action.md`);
- the timers and Averages its Think reads;
- the signpost decisions.

DrivingChoice (`docs/formats/ai-driving-choice.md`) and the actions read
and write it.

The port is `3DS Files/source/aicarcontroller.{c,h}`. It is cross-checked
by `tools/aicarcontroller_check.py` against
`tools/src/aicarcontroller_test.c`, with the retail image running in
mipsemu as the oracle.

Step 11e ports it in slices:

| Slice | What |
|-------|------|
| 11e-0 | the Average at retail's size (`docs/formats/average.md`) |
| 11e-1 | the record, the constructor and destructor, the table, the route methods, JustReset, the action's interruption and points, the physics mode, the line speed, the boosts and the small accessors |
| 11e-2 | the signposts and sticky decisions |
| 11e-3 | the belt, glue and boost decisions |
| 11e-4 | the honking and ExecuteCurrentAction |
| 11e-5 | Think, with Timer::CountDown and Race::CanAICarsStartDriving |

This file has 11e-1 to 11e-5. One slot still waits: DoSnapshot, on
ReplaySnapshot. Think calls BeltMover::SetBelt through carmodes.h's
`gBeltMoverSetBeltFn`, which main.c points at beltmover.c's (11e-6,
[belt-mover.md](belt-mover.md)); a harness that leaves it NULL makes Think
abort rather than go on.

## The record, 720 bytes

The offsets agree with the demo's stab (type#1344, 704 bytes) up to
aStickyDecisions at 652. Retail makes that array eight words where the
demo had six. Two words of retail's own follow it. pDeltaLineSpeed and
vPreviousLinePoint move from 676 and 688 to 692 and 704.

| Off | Field |
|----:|-------|
| 0 | CarController: pCar, Driver, vptr |
| 12 | MyCurrentDrivingInformation: the NearbyCarList (464 bytes), then the DrivingLocation at 476 and the DrivingChoice at 492 |
| 504 | CurrentDrivingLocation, pointing at its own (476) |
| 508 | CurrentDrivingChoice, pointing at its own (492) |
| 512 | CurrentNearbyCarList, pointing at its own (12) |
| 516 | CarToExcludeFromCollisionPrediction |
| 520 | LastTrackRouteNumber, a byte |
| 524 | SecondsBeforeNextActionEvaluation |
| 528 | ForceCurrentAction (11 none) |
| 532 | CurrentAction |
| 536 | LastRoutePointLookaheadSwitch, a Timer |
| 540 | CurrentRoutePointLookahead |
| 544 | LastTimeNonGetUnstuckActionWasCalled |
| 548 | PullOverTimeout (a finishing car's pull-over takes it down to 15; [race-update.md](race-update.md)) |
| 552, 556 | BrakeStandTimer, BrakeStandTimerStart |
| 560 | BrakeStanding, a bool |
| 564 | LastBoostCalculationTime |
| 568 | OffBeltTimer |
| 572 | RealPhysicsTimer |
| 576 | ProgressTimer |
| 580 | pProgress, an Average of 10 |
| 584 | fLastProgress |
| 588 | pGlueCar |
| 592, 596 | GlueOnTimer, GlueOffTimer |
| 600 | nGlueOffReason |
| 604 | fCurrentGlueTimeBias |
| 608 | sGlueDebug, 32 chars |
| 640 | bBoostAllowed |
| 644 | pCatchupPlayer |
| 648 | nSignpostIndex |
| 652 | aStickyDecisions, eight words (below) |
| 684 | TakenSignpostIndex: retail's own, the AIHint 2 sign whose route the car took (-1 none) |
| 688 | TakenSignpostTimer: retail's own, set to 10000 ticks when GetCurrentTrackRoutePoint takes an AIHint 1 sign's route |
| 692 | pDeltaLineSpeed, an Average of 5 |
| 696 | 8 bytes of padding |
| 704 | vPreviousLinePoint, a quadword |

## The table

| Slot | Method | Retail |
|-----:|--------|--------|
| 8 | destructor | 0x001903a0 |
| 16 | DebugDisplay | 0x00191138 |
| 24 | DoSnapshot (ReplaySnapshot) | 0x00190438 |
| 32 | Think (11e-5) | 0x00191148 |
| 40 | SetCurrentRoute | 0x00190670 |
| 48 | GetCurrentRoute | 0x00190708 |
| 56 | GetCurrentRoutePoint | 0x00190760 |
| 64 | GetAmountOutOfBounds | 0x001907b8 |
| 72 | FindWhereIAm | 0x00192f10 |
| 80 | JustReset | 0x00190850 |
| 88 | SetToPhysicsMode | 0x00193650 |
| 96 | ForceBoost | 0x00193758 |
| 104 | ReleaseBoost | 0x00193780 |
| 112 | GetRouteNumbersToUse | pure |
| 120 | ChooseNewAction | 0x00192780, `jr ra` |
| 128 | GeneratePointsToFulfillAction | 0x00192668 |

The port keys the table by the demo's address (carcontroller.h's
AICARCONTROLLER_VTABLE), which car.c and the checkers already test
against. `main.c` installs it.

## The constructor and destructor

**The constructor** (0x00190140) runs CarController's constructor and then
the members' own:

- each nearby entry's car is NULL, MyCar is the car, and the list is
  emptied;
- the location, the choice and the information are Cleared;
- every Timer is zeroed;
- bit 0 of each sticky decision is cleared.

Then the body sets:

- SecondsBeforeNextActionEvaluation to the car's index (`lh` at 8) times
  -1/140, so each car's first evaluation is staggered;
- no forced action (11) and no current action;
- LastTrackRouteNumber -1;
- the three Current pointers to the controller's own;
- ProgressTimer 1.5 s from now;
- the two Averages, bMalloc'd from the car pool as "Progress Average" (10
  slots) and "DeltaLineSPeed Average" (5);
- vPreviousLinePoint zero;
- the boost allowed, no catch-up player;
- PullOverTimeout 1e7;
- BrakeStanding set;
- nSignpostIndex from Signpost::GetIndex at the car's distance round the
  track;
- no taken signpost.

fLastProgress, fCurrentGlueTimeBias, sGlueDebug, the sticky decisions'
other bits and the Driver are not written.

**The destructor** (0x001903a0) deletes the current action through its
own table (flags 3). It then destroys each Average there is, and finishes
with CarController's destructor and the flags.

## The route

**SetCurrentRoute(r, p)** (0x00190670) does nothing without both a route
and a point. Otherwise it sets LastTrackRouteNumber to the old route's
number (-1 with none). It then asks GetNewDrivingLine for a line, relaxed,
and sets the location to the new route and point on that line, relaxed.

**GetCurrentRoute(find)** and **GetCurrentRoutePoint(find)** (0x00190708
and 0x00190760) answer the location's route and point. With `find` set and
the location clear, they first call FindWhereIAm through the table. They
then test IsClear again and drop the answer.

Retail's Car::GetRoute and Car::GetRoutePoint (0x00131740, 0x00131770)
pass a flag through, which the demo's didn't. The port gives
`car_get_route` and `car_get_route_point` an `int find`. Every caller
passes 1, but IsFacingWrongWay, which passes 0. The other controllers
(RealController's tracked, the NullController) take the flag and ignore
it.

**GetAmountOutOfBounds** (0x001907b8) is 0 with the location clear.
Otherwise it takes `f`, the car's offset across the point's direction
(`dx * dir.y - dy * dir.x`):

- `f - RightWidth` when `f` is positive;
- `-(f + LeftWidth)` otherwise.

The answer is negative inside the road.

**FindWhereIAm** (0x00192f10) Clears the location. It asks
GetRouteNumbersToUse for the first and last route numbers, and runs
FindClosestTrackRoute over them. Retail tests the control mode against 3
here, but both arms make the same call.

**FindClosestTrackRoute(first, last)** (0x00190900) looks for the nearest
point. It searches routes `first` to `last` of the route manager's table,
skipping a NULL slot, and a number below 0 by `bltz`. Each route's point
comes from FindClosestPoint, within 999999, with flags 3 (ahead and
posted). Its distance is the 3D length from the car to the point's
GetPosition.

The search runs in two passes:

1. only the routes whose stretch holds the car's distance round the track
   (DistanceIsWithinRoute);
2. if nothing was found, any route.

A route that is the location's own is passed over. A tie keeps the first
found (`c.lt.s`). With a route and point found, it calls SetCurrentRoute
through the table. Otherwise it Clears the location inline.

Nothing checks the top end: a number over 99 reads on past the manager's
table.

**GetNewDrivingLine(r, p, relaxed, &line, highlight)** (0x00192488) builds
a DriveTarget, a DrivingChoice and a DrivingLocation on its stack. It sets
`*line` to line 0's driving line, and sets the location to `r`, `p` and
that line, with `relaxed`.

With a route and a point, it tries the choices for lines 1 to
AICarControllerNumDrivingLinesToConsider in turn. For each one, it sets
the location to that choice's line, with `relaxed`, and calls IsDriveable
with:

- the controller's nearby list;
- AIDriverAvoidCarsImpactTimeThreshold;
- MOVEMENT_TOWARDS_LINE.

The first driveable one gives `*line` and the answer 1. Otherwise the
answer is 0, with `*line` still line 0's. Then, when `highlight` is not
NULL, that location's line is highlighted with my driver number.

**The relaxed switch can't be seen.** `relaxed` reaches only the stack's
own location, and IsDriveable hands that location to BuildDriveTarget:

- for a valid line choice, BuildDriveTarget works from a copy set to the
  choice's line with no switch;
- for an invalid one, the target is thrown away and IsDriveable answers 0,
  whatever it holds.

So whether the switch is relaxed never reaches a target IsDriveable reads.
GetSpeedBackToLine's relaxed arm (0.25 m a point, against 0.5) never runs
from here. The checker's s_relax drives exactly that case, and the
mutations that flip the switch are equivalent.

## JustReset and the small methods

**JustReset** (0x00190850) does five things:

1. sets SecondsBeforeNextActionEvaluation as the constructor does;
2. zeroes vPreviousLinePoint;
3. calls the driver's ZeroSteeringMemory (CarDriver slot 120);
4. clears the sticky decisions;
5. finds the signpost again.

The small methods:

- **GetMyDriverNumber** (0x001908f0) is the car's DriverNumber.
- **ClearStickyDecisions** (0x00191d10) clears bit 0 of each of the eight
  sticky decisions.
- **SteerStraightAhead** (0x00192848) hands the driver's SetSteerToPoint
  (slot 72) the point one metre ahead of the car, along its heading
  (`bCosBam` and `bSinBam` of the angle).
- **DebugDisplay** (0x00191138) does nothing.
- **AboutToFly** (0x00191130) answers 0.
- **ChooseNewAction** (0x00192780) is `jr ra`. AIDriver's chooses (see
  [ai-driver](ai-driver.md)); TrafficDriver keeps this one and never
  calls it, as its Think is its own (see [traffic-driver](traffic-driver.md)).

## The action

**InterruptAction** (0x00192788):

- **With no forced action:** it asks ChooseNewAction for type 11. NULL
  answers NULL. The new action is kept only when there is a current action
  and that one scores less. Otherwise the new one is deleted, and the
  answer is NULL.
- **With a forced action:** it answers ChooseNewAction's action for that
  type, and the force is dropped.

**GeneratePointsToFulfillAction(a)** (0x00192668):

1. It looks up the car ahead (GetCarAhead) and drops the answer.
2. It calls the action's CalculatePointsToDrive on the information.
3. If the action's points won't carry it out, it deletes the current
   action and NULLs it. ChooseNewAction then gives a type 2 (Draft) action
   into CurrentAction, and that action's points are calculated. Nothing
   tests the second answer, or a NULL action.
4. When the choice is a driving line other than the location's, the
   location takes that line, not relaxed, and is highlighted with my
   driver number.

**GetCurrentActionType** (0x00194000) is the current action's type, or 11
with none. **ForceMyCurrentAction** (0x00194020) stores the type.

## The physics mode

**SetToPhysicsMode(car)** (0x00193650) works on the controller's own car:

1. Off the belt (mode 6), it sets OffBeltTimer 2 s from now.
2. It picks the mode: nDefaultMovementMode, or physics when `car` (the
   argument) is a player's.
3. When that mode isn't the car's own, it calls SetMovementMode.
4. When the mode is physics, it sets RealPhysicsTimer 3 s from now.

Retail's **CarController::SetToPhysicsMode** (0x001c0100) changed from the
demo's. It still ignores its argument and leaves a car in physics or
mellow alone. Any other car now goes to physics when it is a player's, and
to mellow otherwise; the demo's always went to mellow. Car::SetToPhysicsMode
(0x00131800) inlines the same test for a car with no controller.

The port has this as `carcontroller_physics_or_mellow(car)`, which both of
those call. carmode_check's mutations follow it.

**GetCurrentDrivingLineSpeed** (0x001936f0) is 0 with the location clear.
Otherwise it is the byte at `90 + line` of the location's point, as a
float. For line -1 that byte is the last offset's high byte. Car's
GetDrivingLineSpeed reaches it through the seam
`gAICarControllerGetCurrentDrivingLineSpeedFn`, which main.c points at
`aicarcontroller_line_speed_seam`.

The remaining small methods:

- **ForceBoost(f)** and **ReleaseBoost** (0x00193758, 0x00193780) call the
  base's, then disallow or allow the boost again.
- **SetOffBeltTimer(s)** (0x00194028) sets OffBeltTimer `s` from now.
- **The exclusion** (0x00193fe0 get, 0x00193fe8 set) and
  **GetCurrentDrivingLocation** (0x00193ff8) are plain accessors.

## The signposts

A signpost (`docs/formats/track-route.md`) marks a junction: at its point,
the road branches on to its NewRoute and NewPoint, and its Sign says what
the AI makes of it. The controller decides each sign once, a little before
it gets there, and keeps the decision until it is 10 m past it. The
decisions live in the eight sticky words:

| Bits | What |
|-----:|------|
| 0 | the slot is in use |
| 1 | the sign is taken |
| 2-7 | the driving line to take it on |
| 8-15 | the sign's index, a byte |
| 16-31 | kept as they were |

nSignpostIndex (648) is the next sign to decide, an index into
SignpostArray.

**FindSignpostIndex** (0x00191d40) steps nSignpostIndex on while its sign's
Distance is below my car's distance round the track. Those are plain
compares, not CompareDistances. It stops at the first sign that isn't
behind, or at 0 when it steps past NumSignposts (`slt`, signed).

**GetStickyIndex** (0x00191d90) answers the first slot not in use, or -1.

**DoStickyDecisions** (0x00191b30) runs in two passes.

1. **The drop.** Each decision in use is dropped when its sign is more than
   10 m behind me: `10 < CompareDistances(mine, sign)`. Dropping it clears
   bit 0 only. When its sign is TakenSignpostIndex, that goes back to -1.
2. **The look-ahead.** The car looks AIDriverSecondsToLookAhead times its
   speed times 1.1 (gp-29840) ahead. That is clamped to no less than 100 m
   and no more than 250, as `min(250, max(a, 100))`.

Then, while a slot is free, it takes the sign at nSignpostIndex. `d` is
CompareDistances(sign, mine):

- `d < 0`, behind me: step on;
- `d < ahead`: SignPostDecision on it, with a line of -1 and the
  controller's location, then step on;
- otherwise stop.

Stepping on wraps at NumSignposts, as in FindSignpostIndex. A sign that
already has a decision answers from its slot and uses none. So with no
sign past the look-ahead and a slot free, retail goes round the signs for
ever. The checker always puts a sign past it.

**SignPostDecision(s, &line, loc)** (0x00191de0) answers whether the car
takes sign `s`, and on which line. DrivingChoice::AdvancePoint reaches it
through drivingchoice.h's seam, `gAISignPostDecisionFn`, which main.c
points at `aicarcontroller_sign_post_decision`.

1. **The early outs.** A Backwards sign, or a Cloaked one that isn't
   AlwaysTake, is not taken. `*line` is the kept line: line 0's
   (CarClass x 2) with the location clear, else the location's own. Nothing
   is stored.
2. **A decision already made.** A slot in use with this sign's index
   answers from the slot: bits 2-7 into `*line`, and bit 1.
3. **The decision.** First it notes the free slot (GetStickyIndex). Then:
   - AlwaysTake is taken.
   - Every other sign is never taken inside the sign grace period. The
     period is GetTrackInfo(TrackNumber)'s SignpostGracePeriod (+128). At
     -1 the car must be out of Race::GracePeriodIsActive. Anything else is
     a time in seconds: the car must be past it, `g < RaceTime x 0.00025`
     (gp-29836, ticks to seconds).
   - Past the grace period, Equivalent is taken on World::Random(1) < 0.5,
     and DontTake never.
   - The rest (Faster, Slower, Stop and the unnamed 6 and 7) draw r =
     World::Random(1) against the TakeSignChance of the driver's skill.
     The skill byte is read signed (`lb`) and clamped to 0..9
     (`pmaxw`, `pminw`). Then:

| Draw | Takes |
|------|-------|
| r <= chance[0] | Slower |
| r <= chance[1] | Faster |
| r <= chance[2] | none |
| over all three | Faster |

   That is a switch through the table at 0x002b4cb0, cases 2, 1, 3 and 0.
   A Stop sign is never taken, but it still draws.

   A sign not taken sets `*line` to the location's DrivingLine as it is.
   Unlike the early outs, there is no IsClear test.

   A taken sign other than AlwaysTake asks GetNewDrivingLine (relaxed) for
   the sign's route and point, into `*line`. If no line is driveable, the
   sign is not taken after all. If it is driveable and the sign's AIHint is
   2, TakenSignpostIndex becomes the sign's index.
4. **AlwaysTake's line.** A taken sign whose line is still negative (from
   the caller's -1) asks GetNewDrivingLine again, and keeps whatever it
   gives.
5. **The range check.** A line that isn't 0 or 1 (`sltiu 2`, unsigned)
   becomes the kept line.
6. **The store.** It writes into the slot noted at the start: bit 0 set,
   bit 1 the answer, bits 2-7 the line's low six bits, bits 8-15 the
   sign's index.

   With every slot in use, the slot is -1 and retail's `652 + 4 x -1` is
   nSignpostIndex. The decision goes there, and the next sign to decide
   becomes a sticky word. The port does the same. AdvancePoint and
   GetCurrentTrackRoutePoint can get there; DoStickyDecisions can't, as it
   stops with no slot free.

**GetCurrentTrackRoutePoint(car)** (0x001921f8) moves the location on
along its route and takes the signs it passes. Its argument isn't read.

1. With the location clear, it calls FindWhereIAm (slot 72) and returns.
2. **Off the road.** `f` is my car's offset across the location's point
   (as GetAmountOutOfBounds has it), with a margin of the list's
   MyHalfSizeL. If `RightWidth < f - margin` or `f + margin < -LeftWidth`,
   it calls FindWhereIAm and returns.
3. **The new point.** It asks FindClosestPointAhead from the location's
   point. With none, the car is at the end, and it uses the route's last
   point. The location takes the new point.
4. **The signs.** It goes over the route's points from the old one to the
   new one, both included. Each point with a sign gets SignPostDecision,
   with a line of -1 and the location. On a take:
   - LastTrackRouteNumber becomes the location's route's number, -1 with
     it clear;
   - the location takes the sign's route, point and line, relaxed;
   - an AIHint 1 sign sets TakenSignpostTimer.PackedTime to 10000
     (gp-29832, 10000.5 through `cvt.w.s`), a span of 2.5 s;
   - the loop stops.

   A sign not taken has its GetNewRoute asked for and the answer dropped.
5. At the end with no sign taken, it calls FindWhereIAm.

## The belt, the glue and the boost

Retail calls only some of these. Think (11e-5) asks WeNeedTheBelt and
WeCanHaveTheBelt. ExecuteCurrentAction (11e-4) calls DecideBoostFactor,
which calls CalculateDistanceAndPositionBoost. WeHaveTheGlue is called
only by the other glue functions.

WeHaveTheBelt, WeNeedTheGlue, WeCanHaveTheGlue, GlueOn, GlueOff and
GetGlueSpeed have no callers at all: no `jal` reaches them, and no word
in the image holds their addresses. So the glue never runs in the game.
The port has all eleven, checked, for whoever calls them.

The unit's globals:

| Global | What |
|--------|------|
| gp-20344 | bBeltMover, 1 |
| gp-20336 | the glue's Graph: the two points at 0x00310108, (-20, 0.1) and (20, -0.1), built by `_GLOBAL_$I$sRankHeadings` (0x00193f00) |
| gp-20132 | the catchup's off switch (`CarControllerDisableCatchup`), 0 |
| gp-20296 | nLastGlueReason, the last no WeCanHaveTheGlue gave |

### The belt

**WeHaveTheBelt** (0x00190af8) answers whether the car's TheMovementMode
is the belt's. **WeNeedTheBelt** (0x00190b10) answers bBeltMover, and
doesn't read the controller.

**WeCanHaveTheBelt** (0x00190b20) answers 1 unless one of these holds,
tested in this order:
- the drive target has fewer than 3 points;
- the race coordinator is in AIDemoMode (8);
- OffBeltTimer or RealPhysicsTimer is running;
- ForwardSpeed is under 5 m/s, or no wheel touches the ground;
- there is no action, or the action is PullOver, GetUnstuck,
  AccidentRecovery, AvoidRoadBlock or IJustGotHit;
- the driver is careful (skill -2);
- a player is within 120 m (World::GetDistanceToClosestPlayer);
- the race clock is under 30 s.

The race clock is the race's RaceTime, read as a signed word, times
0.00025.

### The glue

The glue holds an AI car beside a player's at about the player's speed.

**WeHaveTheGlue** (0x00190c78) answers whether pGlueCar is set.
**WeNeedTheGlue** (0x00190c88) answers 0.

**WeCanHaveTheGlue(p)** (0x00190c90) answers whether the car may glue
itself to player `p`'s car, or keep the glue it has. With the glue on, the
player asked about is the glued car's, not `p`. Each no stores its reason
in nLastGlueReason (4 is no one's):

| Reason | No because |
|-------:|------------|
| 1 | there is no action |
| 2 | the action's Type is PullOver (6) or later, compared signed |
| 3 | the player's speed ratio (Player::GetSpeedRatio, the mean of pAverageSpeedRatio) is under 0.94 |
| 5 | the cars are too far apart |
| 6 | their speeds differ too much |
| 7 | their headings differ too much |
| 8 | GlueOnTimer has run out |
| 9 | GlueOffTimer is still running |
| 10 | the player is ahead of me in the race |

Reasons 1 to 3 are tested first. Then:
- the distance is between the cars' positions;
- the speed difference is `|their VelocityMagnitude - mine|`;
- the heading is the dot of the two velocities, each normalised by the
  VU0. `vrsqrt` divides by zero for a car standing still, which the EE
  answers with FLT_MAX, so that car's direction is 0.

With the glue on:
- **GlueOnTimer run out:** GlueOffTimer is set to 20 s, and the answer is
  no (8).
- Otherwise it is held within 60 m (5), 10 m/s (6) and a dot of 0.5 (7).

Without the glue:
- **GlueOffTimer still running:** no (9).
- Otherwise it is taken within 30 m (5), 6 m/s (6) and a dot of 0.7 (7),
  and only when the player isn't ahead (10): its car's RacePosition is no
  smaller than mine.

Each limit itself passes: the tests are `60 < d` and `dot < 0.5`, so
exactly 60 m, or a dot of exactly 0.5, holds.

**GlueOn(p)** (0x00190f38) does nothing with the glue already on.
Otherwise it:
- counts the player's nGlueCount (192) up;
- sets GlueOnTimer to 7 s;
- glues on to the player's car;
- sets fCurrentGlueTimeBias to 0.2.

Retail then asks the race for both cars' RacingCars and reads neither.

**GlueOff** (0x00190fb8) does nothing with the glue off. Otherwise it
clears pGlueCar and counts the glued car's player's nGlueCount down. It
leaves both timers alone.

**GetGlueSpeed** (0x00190ff8) is the speed to drive at, glued. When
either car has no RacingCar, it answers the driver's GetDesiredSpeed
(slot 136). Otherwise:

1. **The gap.** `gap` is the distance between the cars, negative when the
   glued car is ahead in the race.
2. **The time bias.** `gap -= fCurrentGlueTimeBias x their speed`.
3. **The factor.** `f = (graph(gap) + 1) + (my speed - theirs) x -0.05 /
   (gap x (gap x 0.01) + 1)`. `graph` is the glue Graph: +0.1 with the
   glued car 20 m ahead, -0.1 with it 20 m behind, flat past the ends.
4. **The answer.** `f` is clamped to 0.9-1.1, and the answer is `f` times
   the glued car's speed.

### The boost

**CalculateDistanceAndPositionBoost(me, them, &dist, &pos)** (0x00192c78)
works out two boosts from TheDifficultyInfo (`difficulty-info.md`), both
zeroed first.

1. With the race parameters' Boost off, it stops there.
2. **The laps.** `laps` is my CurrentLapNumberExact less theirs. In a cop
   race (BeACop, or SkipFE with SkipFEBeACop) the laps are brought within
   half a lap: `laps - floor(laps + 0.5)`. The floor is `cvt.w.s`, less
   one when that rounded up.
3. **The distance.** `ahead` is the track's length times `laps`. Past
   MaxDistanceForBoost (988, as `!(ahead <= max)`) both boosts stay 0.
4. **The distance boost.** Each of the two seven-point Graphs (the low
   skill's at 0 and the high's at 56) gives its value at `ahead`. A Linear
   from skill 0 to 9 between those two gives `dist` at the driver's skill (a
   negative skill as 0).
5. **The speed term.** `dist` gains `(my speed - theirs) x -0.005 /
   (ahead x (ahead x 0.01) + 1)`, clamped to within 0.05 either way.
6. **The position boost.** `diff` is their RacePosition less mine. The
   index is `diff + 7` for `diff` of 0 or more, else `diff + 8`, so 0 to 7
   for 8 to 1 behind and 7 to 15 for level to 8 ahead. A Linear from 0 to
   9 between the two position-boost rows' entries (112 and 176) gives
   `pos` at the clamped skill.

**DecideBoostFactor** (0x001928f0) sets the car's BoostFactor (992). It
does nothing at all for a car with no RacingCar, with bBoostAllowed (640)
clear, or with a player.

1. **What it reads first.** `allowed` is whether the action has
   AllowedToUseBoost set (no action, no boost). `early` is whether the race
   clock is under 30 s.
2. **The frequency.** It returns unless BoostCalculationFrequency (984) is
   under `(WorldTimer - LastBoostCalculationTime)` in seconds. The
   difference is a signed word.
3. LastBoostCalculationTime becomes WorldTimer, and pCatchupPlayer is
   cleared.
4. **The catchup.** It runs only with the catchup on, outside AIDemoMode
   and with NumPlayerCars over 0:
   - With `allowed` clear, BoostFactor is set to 1 and it returns.
   - In the first 30 s the factor stays 1.
   - After that, with one player, that player is the catchup
     player, and the boosts are taken against its RacingCar.
   - With two, the target is picked below.
   - In both cases the factor is `(dist + 1) + pos x BoostScale[the
     player's PlayerNumber]`. With no players, or more than two, it is 1.
5. **The speed ratio.** With `allowed` and a catchup player, the factor is
   multiplied by `max((ratio - 1) x t + 1, slow)`:
   - `slow` is the clamped skill's SlowFactor (368 + 28 x skill + 20).
   - The factor changes only when Player::CatchupAllowed(slow) passes:
     the player's speed-ratio Average is full (as many samples as slots)
     and `slow` is under its fMaxSpeedRatio (168).
   - `ratio` is the player's speed ratio.
   - `t` is a two-entry Table from skill 0 to 9, at the skill. Its row is
     PositionRatioOverOne's (240) for a ratio of 1 or more, else
     PositionRatioUnderOne's (304), by the player's RacePosition, place 1
     first. Retail adds `232 + 8 x place` or `296 + 8 x place`, so place 0
     reads the row before each table.
6. BoostFactor is set to the factor.

**The two-player target.**
1. The leader is the player with the smaller RacePosition, player 0 when
   level; the other is the trailer.
2. `n` starts at NumAICars / 2.
3. It is counted up once if the leader's place is no further back than
   `n`, and once more if the trailer's place is no further back than the
   new `n`.
4. An AI car placed past `n` catches up to the trailer; the rest catch up
   to the leader.

The pCatchupPlayer and BoostScale are that player's.

PrintBoostCalculationForAllCars and PrintBoostCalculationForThisCar
(gp-20128, gp-20124) are read, but their prints are gone from retail.

## The horn and ExecuteCurrentAction

### The horn

**MaybeHonkAndOrBlinkHeadlights(car, list)** (0x00192fa8) decides whether
my car honks, flashes its lights or both at `car`, a car about me. `list`
is the nearby-car list the caller is working through.

1. **The gates.** It returns for a cop's or a traffic car's `car` (its
   CarTypeInfo's UsageType less 1, unsigned, under 2). It returns unless
   the race coordinator is in AIDemoMode (state 8) or `car` is REAL
   controlled, so in a race only the players' cars are honked at.
2. **The car's entry.** GetNearbyCar finds `car` in my own list
   (CurrentNearbyCarList). An AI car (control 2) goes on only if
   DoWeCareAboutThisCar(entry, list) passes, and it answers 0 for a NULL
   entry. A traffic car (3) goes on with no test. Any other control
   returns.
3. **The draws**, in this order, each World::Random on pCurrentWorld:
   - `on = (R(0.4) + 0.3) - 0.2`;
   - `off = (R(0.2) + 0.15) - 0.1`;
   - `second = (R(0.4) + 0.3) - 0.2`;
   - `two = R(1) < 0.5`.
4. **The chance**, by the entry's closing speed `vy` (its Velocity.y):
   - over 50 m/s, 1, with `two` set and `second` 0.6 longer;
   - else, for my traffic driver (DriverType 3) and `vy` under -3, 1;
   - else, for a `car` with a player, 0.75;
   - else 0.075 with under 6 cars in `list`, or 0.05.
5. `honk = R(1) < chance`. Only with `honk` is the blink drawn: `blink =
   R(1) < 0.9` over 50 m/s, else `R(1) < 0.5`. Without it `blink` is 0, so
   a car never flashes without honking.
6. It ends in my car's HonkAndOrBlinkHeadlights(on, off, second, blink,
   honk, two), which takes the request only once the last one's cycle is
   over (`car.md`).

The demo's HonkAndOrBlinkHeadlights took two durations and ran the first
twice. Retail's third, `second`, is the second on phase's, and the car
stores it at 2088. The port's car.c takes it as retail does.

### ExecuteCurrentAction

**ExecuteCurrentAction** (0x001932e8) hands the current action to my
driver.

1. The driver's SetTarget (slot 64) gets the action's PointsToDrive.
2. DecideBoostFactor runs.
3. **The speed.** The driver's SetDesiredSpeed (slot 56) takes a speed,
   a time to reach it, a tolerance and whether the throttle and brake may
   be used. They come from the first of these that holds:

   | Case | Speed | Time | Tolerance | Allowed |
   |------|-------|------|-----------|---------|
   | the location clear | 0 | 0 | 0 | 1 |
   | SuperEasyAI (gp-20120, retail's alone) | 15 | 0 | 10 | 1 |
   | BoringAIForCameraTuningOn (gp-22580) | the location's point's line speed | 0 | 0 | 1 |
   | the action's UseDrivingLineSpeed (576) clear | the action's DesiredSpeed (564) | 568 | 572 | 580 |
   | otherwise | the line speed below | 0 | 572 | 580 |

4. ClearPointsToDrive empties the action's target: NumPoints and Length
   0, both pick times 0 and LastPointToScore -1.

**The line speed** is a route point's DrivingLineSpeeds byte for the
location's line (90 + line, so line -1 reads the byte before):

- With a sign taken (TakenSignpostIndex not -1), it is the byte of the
  sign's GetNewRoutePoint, with no SpeedFactor. Retail also asks
  CompareDistances for the sign's distance from my car and drops the
  answer.
- Else, while TakenSignpostTimer is set, it is 99999.
- Else it comes from the point CurrentRoutePointLookahead (540) on from
  the location's:
  - **The look-ahead.** For a skill of 0 to 9 (unsigned, so a careful
    driver's -2 never draws), once more than RoutePointChangeFrequency
    (980) seconds have passed since LastRoutePointLookaheadSwitch (536),
    the look-ahead is drawn again: `v` is the skill's RoutePointVariance
    byte (392 + 28 x skill) plus 1, the look-ahead `Random(2v) - v`
    (World::Random(int), 0 to 2v - 1), and the switch's time becomes
    WorldTimer.
  - The point's index is the location's point number plus the
    look-ahead, clamped to the route's first and last points (`pmaxw`
    with 0, then `pminw`).
  - A speed of 0.001 or less (as `fabsf`) is read as 30.
  - The speed is multiplied by the skill's SpeedFactor (368 + 28 x skill
    + 16), with the skill unclamped: -2 reads PositionRatioUnderOne's
    float at 328.

Then, on this way alone, a cop race (BeACop, or SkipFE with
SkipFEBeACop) takes 0.75 of it, and the car's BoostFactor (992)
multiplies it. The sign's and the timer's speeds are scaled the same way.

The look-ahead's draw and SuperEasyAI are retail's alone.
RoutePointChangeFrequency and RoutePointVariance are read nowhere else
(`difficulty-info.md`).

## Think

**Think(dt)** (0x00191148, slot 32) is the controller's frame. It is
the caller of two methods new in retail, Timer::CountDown and
Race::CanAICarsStartDriving (`race.md`).

1. **Before the start.** Until Race::CanAICarsStartDriving says yes, the
   car waits:
   - before the pre-race (RaceStage under 2, signed `slti`), it stands:
     SetDesiredSpeed(0, 0, 0, 1);
   - from the pre-race on, it runs the brake stand (below).
   Then SteerStraightAhead, and Think returns.
2. **The progress check.** This runs with an action that isn't a
   PullOver, while ProgressTimer (576) runs, on the step CountDown runs
   it out:
   - ProgressTimer is set to 1.5 s again.
   - pProgress (580, ten slots) records the car's speed round the track:
     TrackLength x |its RacingCar's dCurrentLapNumberExact|, the lap rate.
   - PleaseResetMeLater is called when the car isn't blinking, the ring
     is full, its mean is under 0.2 m/s and no player is within 50 m
     (World::GetDistanceToClosestPlayer, `<`). So a car stuck for 15 s
     out of sight is put back.
3. **The timers.**
   - **RealPhysicsTimer** (572), on the step it runs out: with under 4
     wheels down it gets 1 s again, else the car goes back to
     nDefaultMovementMode.
   - **OffBeltTimer** (568), while it runs: a car on the belt goes back
     to nDefaultMovementMode, and the timer counts down.
   - GlueOnTimer, GlueOffTimer and TakenSignpostTimer count down.
4. **The debug reset.** It runs for the camera's car
   (CameraFollowThisCarInstead), with ResetThisCarsPosition (gp-20320)
   set. The switch is cleared, and Car::DebugSetPosition puts the car at
   (-890, -332, -78), at speed 0 and angle ThisCarsResetAngle (gp-13390,
   a halfword).
   - Retail calls bRefreshTweaker, a call to the host, in between; the
     port has no host.
   - DoScreenPrintf and DoSpeedDifferencePrinting reach only
     BeltMover::DebugScreenPrint and Car::PrintAbove, which ship empty.
5. **The turn.** SecondsBeforeNextActionEvaluation (524) comes down by
   `dt`, and my list's NumCarsInArray, MyHalfSizeL and MyHalfSizeD are
   cleared. Whose turn it is depends on my DriverType:
   - **An AI racer (2):** my turn when `WorldLoopCounter % 8` (C's
     signed remainder) is under CopCarPos - AICarPos, and the World's
     CarTable at AICarPos plus it is my car.
   - **A traffic car (3):** the same with `% 6`, TotalNumCars -
     TrafficCarPos and TrafficCarPos.
   - **Anyone else:** my turn once SecondsBeforeNextActionEvaluation is
     0 or less. Retail compares it with the list's MyHalfSizeL, just
     cleared.

   So the racers think one a frame, eight frames round, and the traffic
   six. When it isn't my turn and I have an action, Think goes between
   thinks (below) and returns.
6. **The think.**
   1. SecondsBeforeNextActionEvaluation gets 0.1 more.
   2. DoStickyDecisions runs, then BuildArray, then
      GetCurrentTrackRoutePoint. BuildArray is handed the greatest of
      AIActionPassMaxTimeAheadToMakeAttempt,
      AIDriverAvoidCarsImpactTimeThreshold and AIDriverSecondsToLookAhead,
      which it doesn't read.
   3. **A clear location:** SteerStraightAhead, SetDesiredSpeed(0, 0, 0,
      1), and Think returns with the list still full.
   4. **The action** (below), then ExecuteCurrentAction.
   5. **The belt.** When WeNeedTheBelt and WeCanHaveTheBelt, the car goes
      to BELT_MOVEMENT if it isn't there, and BeltMover::SetBelt runs on
      its mover. Otherwise a car on the belt goes back to
      nDefaultMovementMode.
   6. **The render.** The camera's car hands TheDriveTargetRenderer's
      SetTargetToRender its CarDriver, cast as a DriveTarget. Nothing reads
      it while RenderDriveTargetPoints is off.
   7. The list's NumCarsInArray, MyHalfSizeL and MyHalfSizeD are cleared
      again.

### The action

The think's action comes from the first of these that holds:

- **BoringAIForCameraTuningOn (gp-22580).**
  - No action: a new JustDrive.
  - A JustDrive: its own CalculatePointsToDrive runs.
  - Any other action: it is deleted, and ChooseNewAction(JustDrive)
    replaces it.

  That is all; the points aren't generated.
- **No action:** `new AIActionJustDrive(AIActionJustDriveScore, -1)`.
  The slot comes from AIActionSlotPool by bOMalloc. AIActionJustDriveScore
  is gp-18272, 0.
- **Otherwise:** UpdateStatus runs.
  - A done action (a success, a failure, or expired where it can expire)
    is deleted, and ChooseNewAction(none) gives the next.
  - Else InterruptAction may answer one to take its place.

Then GeneratePointsToFulfillAction runs on the action.

### Between thinks

This runs only for a choice beside a car (5 and 6) whose car has a
player.
1. BuildArray runs.
2. When GetNearbyCar finds the choice's car in my list:
   BuildDriveTarget(choice, target, location, list, 0, 0, TowardsLine),
   then the driver's SetTarget (64), then the render as above.

The target is a DriveTarget on the stack, built and destroyed around it.

### The brake stand

The brake stand keeps three fields:
- BrakeStanding (560), whether the car is on the brakes;
- BrakeStandTimer (552), the phase's length;
- BrakeStandTimerStart (556), the phase's start.

It runs like this:
1. When BrakeStandTimer isn't running, BrakeStanding is a coin flip:
   bRandom(2) on bDefaultSeed.
2. Else BrakeStanding flips once the phase's length in seconds is less
   than the seconds since its start (WorldTimer less the start, signed).
3. On either, a new phase is drawn:
   - on the brakes, bRandom(0.25) + 0.35 s;
   - off them, bRandom(1) + 1.5 s.
   The start becomes WorldTimer.
4. SetDesiredSpeed(100 on the brakes, else 0; 0, 0, 1).

SetRaceStage clears an AI driver's EBrake only on RACING (`race.md`), so
the brake stand asks for speed while the car is still held.

## Checking it

    python tools/aicarcontroller_check.py
    python tools/aicarcontroller_check.py --mutate

This is its own checker, not part of drivingchoice_check. It imports
drivingchoice_check's world: the cars, routes, signs, list and test tables,
the stubs and every op. The harness's world is
`tools/src/drivingchoice_world.inc`, split out of `drivingchoice_test.c`.

The checker adds '%' ops. They build a controller in place of a car's own
controller, then call its methods as shipped, both directly and through
the table. Everything beneath those methods runs as shipped too:

- the Average;
- Signpost::GetIndex;
- the route manager's table, DistanceIsWithinRoute, FindClosestPoint and
  GetPosition;
- the location, choice and information;
- IsDriveable and everything beneath it;
- GetCarAhead and HighlightDrivingLine;
- from 11e-2, SignPostDecision wherever it is reached: the harness points
  drivingchoice.h's seam at the port's, as main.c does, and the model
  reaches retail's through DrivingChoice::AdvancePoint;
- from 11e-3, the Graph, Linear and Table, World::GetDistanceToClosestPlayer,
  Race::GetRacingCar and the coordinator's state. The model builds the
  glue's Graph with the image's own start-up code;
- from 11e-4, the car's HonkAndOrBlinkHeadlights and
  UpdateHeadlightsAndHorn, DoWeCareAboutThisCar, GetNearbyCar,
  TrackRoute::GetPointNumber, Signpost::GetNewRoutePoint, CompareDistances
  and AIAction::ClearPointsToDrive;
- from 11e-5, Timer::CountDown, Race::CanAICarsStartDriving,
  NearbyCarList::BuildArray, AIAction::UpdateStatus, Average::Record,
  Car::IsBlinking, bRandom's two over bDefaultSeed, and a new
  AIActionJustDrive: its constructor, its tests, its
  CalculatePointsToDrive and its destructor.

The stand-ins each print a line:

- bMalloc hands out 64-byte blocks filled with 0xa5. The port's Average
  record, 24 bytes on a 64-bit host, prints as retail's 16.
- bFree.
- Car::SetMovementMode.
- A test driver table, with SetSteerToPoint and ZeroSteeringMemory added.
- A test controller table (TVT). The harness copies the port's own
  installed table into it, and the model copies retail's. Only
  GetRouteNumbersToUse (the script's numbers) and ChooseNewAction (the
  script's queue of fake actions) are replaced.
- The fake actions' table, whose destructor and CalculatePointsToDrive
  print.
- drivingchoice_check's controller table, whose GetCurrentRoutePoint and
  GetAmountOutOfBounds answer the script. The model now leaves
  Car::GetRoutePoint and GetAmountOutOfBounds unstubbed, so that a built
  controller is reached through its own table.
- World::Random (0x0014e548), answering the script's queue, then 0.
- GetTrackInfo (0x00153420), answering a TrackInfo of the script's. Its
  SignpostGracePeriod is -1 until the script sets it.
- The test driver table's GetDesiredSpeed (136), answering the script's
  speed for the car.
- From 11e-4, the test driver table's SetDesiredSpeed (56), SetTarget (64),
  StartHonkHorn (88), StopHonkHorn (96) and IsHonking (104), the last
  answering the script's flag for the car.
- World::Random(int) (0x0014e520), answering the float's queue as words,
  so the two draw in turn from one queue.
- From 11e-5:
  - bOMalloc (0x00257c80), answering drivingchoice_check's action block,
    where Think's new JustDrive goes;
  - BeltMover::SetBelt (0x00204990), with the mover;
  - Car::DebugSetPosition (0x00133338), with the car, the place, the
    speed and the angle;
  - DriveTargetRenderer::SetTargetToRender (0x001cb600);
  - bRefreshTweaker (0x0025d2c8), a call to the host, silent;
  - the fake actions' HasBeenAccomplished (40), HasFailed (48) and
    HasExpired (56), answering the script's.

The 11e-3 ops fill the rest as memory: the players and their speed-ratio
Averages, the RacingCars, the race parameters' fields, TheDifficultyInfo
and the World's PlayerPositions. WeCanHaveTheGlue's two `vrsqrt` divide
by zero for a car standing still. drivingchoice_check's Model now keeps
the divides it allows in a class attribute, `OK_DIVS`, which this
checker's Model extends with those two (`GLUE_DIVS`).

The scenarios:

- **s_build (40):** the constructor over signs, distances and indices, the
  small methods, the sticky decisions and vPreviousLinePoint, both
  SetToPhysicsModes over every mode with and without a player, and the
  destructor with and without an action.
- **s_where (30):** SetCurrentRoute, the getters with and without the find,
  out of bounds, FindWhereIAm and FindClosestTrackRoute. They run over
  ranges either side of the routes, the car moved off the road or up and
  down, and two routes that tie for closest (%cp copies one route's points
  over another's).
- **s_line (16):** GetNewDrivingLine over each count of lines, with no
  route or point, highlighted or not.
- **s_action (30):** InterruptAction forced and not, over scores either
  way, and GeneratePointsToFulfillAction answered both ways.
- **s_relax (40):** GetNewDrivingLine and SetCurrentRoute where the switch
  would decide. My car is off its line and past 29.5 m/s, the grace period
  is over, and slower cars sit ahead on or near the line.

11e-2's, from their own random seed:

- **s_signdec (60):** SignPostDecision on every Sign and flag, inside and
  past the grace period (the race's, or the track's at the first clock
  past it and either side). Draws land at and either side of the chance
  row the skill clamps to, and an Equivalent's at 0.5. It runs over
  decisions for the sign and not, every slot used and not, lines of -1, 0,
  1 and past, and the location at a point or clear.
- **s_sticky (50):** FindSignpostIndex, GetStickyIndex and
  DoStickyDecisions. Decisions are dropped exactly 10 m past their sign
  and either side. The look-ahead sits at its clamps and between, with
  seconds of 1, 2 and 3. Signs lie behind me, at me and exactly the
  look-ahead on. The index wraps, the track has a length or none, and a
  taken sign's decision is forgotten with it.
- **s_trackpoint (30):** GetCurrentTrackRoutePoint on the walk world: my
  car about a sign's point, on the road, near an edge or off it, and the
  location clear.
- **s_trackpoint_edge (30):** the same on a straight road along x, so the
  car's offset is -y exactly. The car sits exactly the half length past
  either edge and an ulp either side, behind the location's point, and
  past the last point with a sign taken there or not.
- **s_signindex (20):** FindSignpostIndex from each sign, with the car
  before, at, between and past the signs, so where it wraps decides; and
  GetStickyIndex over every kind of word.
- **s_takechance (20):** the draw by skill alone, at and either side of
  each chance, with the chances rising strictly or two of them equal.
- **s_sticky's edge (12):** the look-ahead at its 250 m clamp and the first
  sign just inside it, so a clamp of 249 stops short.

11e-3's, from their own random seed. Each round of the first three fails
at most one test, chosen at random, with every other test passing
(`gate_picker`). A fifth of the rounds instead pass each test on their
own.

- **s_belt (40):** WeCanHaveTheBelt's eleven tests. The speed is set at
  5 m/s and an ulp under, the players at 120 m and an ulp either side, and
  the race clock a tick either side of 30 s and negative. WeHaveTheBelt
  runs over the modes, and WeNeedTheBelt over bBeltMover.
- **s_glue (60):** WeCanHaveTheGlue, held and taken.
  - The distance, speed gap and heading sit at their edges and just past.
  - A heading is exact when both cars run along an axis at powers of two.
    The player's car takes a unit vector whose x is the edge and whose
    squares sum to 1, so the normalise leaves it.
  - A speed gap is exact with one car's speed 0.
  - Some cars stand still, and the action types run from -1 to 11.
  - GlueOn and GlueOff run with the glue on and off, and GetGlueSpeed
    with and without both RacingCars.
- **s_boost (60):** DecideBoostFactor and
  CalculateDistanceAndPositionBoost over eleven early outs.
  - The race has one player or two.
  - The frequency sits at its edge (2000 ticks for 0.5 s), with the timer
    behind and ahead.
  - The cop race's half-lap fold and the speed ratio's rows are covered.
- **s_boost's catchup (30):** two players, with every early out passed and
  MaxDistanceForBoost 1e9. NumAICars runs from 0 to 9 and every place is
  drawn from 1 to 8, ties among them, so the split falls each side of
  each car.

11e-4's, from their own random seed:

- **s_honk (60):** MaybeHonkAndOrBlinkHeadlights, six to eleven rounds on
  my car among one to five others. Each round fails at most one of its
  early outs (`gate_picker`): the car's usage, the race state or its
  control, my control, the car missing from my list (or past its count)
  and DoWeCareAboutThisCar's edge, which falls exactly at `-(D + half
  size + bias)`.
  - The closing speed sits at 50 and -3 m/s and an ulp either side, with
    my driver a traffic car's or not, the car a player's or not and the
    list's count round 6.
  - Each draw lands at its chance and an ulp either side.
  - The last request's whole cycle lies a tick either side of the time
    since it started, so the new one is taken or dropped.
  - Three rounds in ten then run UpdateHeadlightsAndHorn with the driver
    honking or not.
- **s_lights (30):** HonkAndOrBlinkHeadlights and UpdateHeadlightsAndHorn
  on their own: each phase's edge a tick either side, the clock behind the
  stamp, every flag at 0, 1 and past, and now and then a player's car.
- **s_execute (80):** ExecuteCurrentAction over three routes and up to
  four signs, down each of its ways: the location clear, SuperEasyAI,
  BoringAIForCameraTuningOn, the action's own speed, a taken sign, the
  sign timer and the line's speed.
  - The skill runs from -13 to 21, and the line from -1 to 21.
  - RoutePointChangeFrequency lies a tick either side of the time since
    the switch, with that time negative too.
  - The look-ahead is drawn to land the point before the first, at either
    end and past the last.
  - The speed byte is 0, 1, 30 or 255, and TheDifficultyInfo is filled
    with floats, so a skill off the table reads something.
  - The race is a cop race or not, and a fifth of the rounds let
    DecideBoostFactor set the BoostFactor to 1 first.

11e-5's, from their own random seed:

- **s_think (120):** Think frame after frame on my car among the walk
  world's others, five to ten rounds each.
  - A fifth of the rounds come before the start: standing, or the brake
    stand with its timer a tick either side of the time since its start,
    not running, or past it.
  - The rest race:
    - the progress check with its timer a tick either side of running
      out, the ring one sample short of full and full, its mean at 0.2
      and an ulp either side, and a player at 50 m and either side;
    - every timer a tick either side of running out, at 0x7fffffff and
      negative;
    - the debug reset for the camera's car or another;
    - an AI racer's and a traffic car's turn, with the loop counter at
      each remainder and the CarTable's slot mine or not, and anyone
      else's on its clock either side of 0;
    - between thinks beside a player's car or not;
    - the location clear;
    - each action's way to done, interrupted, and
      BoringAIForCameraTuningOn's three.
  - Half the racing rounds are the belt's, failing at most one of
    WeCanHaveTheBelt's eleven tests (`gate_picker`), so the belt is
    taken, kept, refused and left.
  - Half the rounds that start with no action think again at once, so
    the JustDrive just made meets InterruptAction with a fact scored at
    its own score (0) or just past it.
  - Sign 0 always lies 300 to 2000 m ahead and the rest behind me, so
    DoStickyDecisions ends.
- **s_tcd (6):** Timer::CountDown over steps of every size and sign, on
  timers a tick either side of running out, wrapping, at 0x7fffffff and
  not running.
- **s_cas (1):** Race::CanAICarsStartDriving at every stage, in a cop
  race or not.

The check gives 865 scenarios, 173272 ops, 170252 lines, 0 differ.

Its mutation pass has 654 mutations: 639 caught and 15 equivalent.
- 11e-2's share is 100: 96 caught (sp-ret by crashing the harness) and 4
  equivalent.
- 11e-3's is 181: 177 caught (5 by crashing the harness) and 4
  equivalent.
- 11e-4's is 115, all caught (mh-list and eca-clear by crashing the
  harness). They cover car.c's HonkAndOrBlinkHeadlights and
  UpdateHeadlightsAndHorn too.
- 11e-5's is 132: 130 caught (cas-cop-or, th-start, th-stand-return and
  ta-int-set by crashing the harness) and 2 equivalent. They cover
  timer.c's CountDown and race.c's CanAICarsStartDriving too.
- ct-glue and ct-catchup carry a line of context, as GlueOff and
  DecideBoostFactor repeat their lines. dbf-freq-u carries one too, as
  ExecuteCurrentAction's look-ahead repeats its cast. Since 11e-5,
  ct-progress, gl-list, eca-sds-order and eca-freq-u carry one, as Think
  repeats their lines.

| Mutation | Why it's equivalent |
|----------|---------------------|
| sr-relax, gl-relax | the relaxed switch never reaches a target IsDriveable reads (above) |
| gl-relax0 | SetRoute's switch is overwritten by SetDrivingLine's on every pass before IsDriveable reads it, and with no pass the location isn't read |
| gl-list | the constructor points CurrentNearbyCarList at the controller's own list, and nothing in 11e-1 moves it |
| gp-ahead | GetCarAhead only reads, and retail drops its answer |
| dsd-clamp | `max(100, min(a, 250))` and `min(250, max(a, 100))` differ only for a NaN, which the EE doesn't have |
| dsd-max-args | `max.s`'s two orders differ only for a NaN |
| sp-relaxed, sp-again-relaxed | as gl-relax, for SignPostDecision's two GetNewDrivingLines |
| wcb-race-le, dbf-early-le | the race clock is whole ticks, and none rounds to 30 s exactly: 120000 ticks is 30.000002 and 119999 is 29.99975 |
| dbf-ratio-allowed | pCatchupPlayer is cleared before the catchup and set only past its `!allowed` return |
| dbf-ratio-over | at a ratio of exactly 1 the row's value is multiplied by 0 |
| bt-extra | BuildDriveTarget never reads its two floats |
| bt-move | between thinks the target is built only once GetNearbyCar has found the choice's car, so IsValid passes and BuildDriveTargetAroundCar fills up parallel to the line whatever the movement |

Some things the checker found along the way:

- **The collision box.** IsDriveable reaches CarCollisionPredict's
  WillIHitThisCar, which needs each car's pDynamicCollisionBody. Every car
  of the route world is now boxed (drivingchoice_check's `boxed`).
- **A half-clear location.** A location with a route and no point is a
  state the game never makes. IsClear tests only the route, so the getters
  and the line speed would read the NULL point. The script doesn't make
  one.
- **Route 0's number.** The walk world numbers its routes at random, so
  slot 0, the first one FindClosestTrackRoute takes past its `bltz`, was
  never filled. `number_zero` files route 0 under number 0 a quarter of
  the time, and its signs with it.
- **The grace gate.** track.h and topology.md said SignpostGracePeriod
  gated "a 0x400 signpost". It gates every sign but AlwaysTake.
- **AIHint 1.** track-route.md said only AIHint 2 is tested. 1 is tested
  too, by GetCurrentTrackRoutePoint, which sets TakenSignpostTimer.
- **No NaN.** mipsemu's EE FPU has no NaN or infinity: 0x7fc00000 is a
  huge number, so a NaN speed's look-ahead is 250 there, where an IEEE FPU
  gives a NaN.
- **CatchupAllowed's argument.** Player::CatchupAllowed(f) (0x001811f8)
  compares `f`, DecideBoostFactor's SlowFactor, against fMaxSpeedRatio.
  The port's first try compared the speed ratio's mean.
- **The glue is never called.** No `jal` reaches WeCanHaveTheGlue, GlueOn,
  GlueOff or GetGlueSpeed, and no word in the image holds their addresses
  (above).
- **The action type is signed.** WeCanHaveTheGlue's PullOver test is
  signed, so a type of -1 goes on to the speed ratio.
- **Retail's car offsets.** BuildArray reads a car's RenderingEnabled as
  a byte at 1192 (`lb`) and Car::IsPoofed the word at 2160, past the
  demo's 1160 and 2120. The model reads retail's; the port's Car keeps
  its own layout.
- **The JustDrive's score.** It is read only when a later think's
  InterruptAction compares it, so a JustDrive made one think and
  compared the next is what tells its score.

Not scripted:

- a find on a controller with retail's own table and a clear location
  (slot 112 is `__pure_virtual`);
- a route number over 99;
- FindClosestTrackRoute finding a route through drivingchoice_check's
  table, whose SetCurrentRoute is no one's;
- GeneratePointsToFulfillAction's second CalculatePointsToDrive on a NULL
  action;
- a NaN speed (above);
- DoStickyDecisions with no sign past the look-ahead (it loops for ever),
  or with a used decision's sign past the table;
- DoStickyDecisions or FindSignpostIndex after SignPostDecision stored a
  decision into nSignpostIndex with every slot used;
- the glue with no player, or with the glued car's player gone (retail
  reads through both);
- GetGlueSpeed with the glue off (it reads pGlueCar's RacingCar);
- from 11e-5, ChooseNewAction answering NULL where Think goes on to the
  action's points or its execution (both read through it);
- a CarTable slot before the table (a negative loop counter's remainder);
- a choice beside a car of NULL (retail reads address 24);
- a sign within the look-ahead when Think runs DoStickyDecisions, which
  11e-2's scenarios cover;
- BuildArray with no list owner.
