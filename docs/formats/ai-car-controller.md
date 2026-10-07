# AICarController -- the controller of a car the AI drives

    AICarController.obj    0x00190140 .. 0x00194058
    _vt$15AICarController  0x002b4d90    17 entries (8 bytes each)
    CarController::SetToPhysicsMode    0x001c0100

AICarController is the base of AIDriver's and TrafficDriver's controllers
(steps 11f and on). It keeps four things:

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
| 11e-5 | Think |

This file has 11e-1 and 11e-2. Two slots still wait: DoSnapshot waits on
ReplaySnapshot, and Think is 11e-5's.

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
| 548 | PullOverTimeout |
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
- **ChooseNewAction** (0x00192780) is `jr ra`. AIDriver and TrafficDriver
  choose.

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
  reaches retail's through DrivingChoice::AdvancePoint.

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

The check gives 378 scenarios, 67592 ops, 40802 lines, 0 differ.

Its mutation pass has 226 mutations: 217 caught and 9 equivalent. 11e-2's
share is 100: 96 caught (sp-ret by crashing the harness) and 4 equivalent.

| Mutation | Why it's equivalent |
|----------|---------------------|
| sr-relax, gl-relax | the relaxed switch never reaches a target IsDriveable reads (above) |
| gl-relax0 | SetRoute's switch is overwritten by SetDrivingLine's on every pass before IsDriveable reads it, and with no pass the location isn't read |
| gl-list | the constructor points CurrentNearbyCarList at the controller's own list, and nothing in 11e-1 moves it |
| gp-ahead | GetCarAhead only reads, and retail drops its answer |
| dsd-clamp | `max(100, min(a, 250))` and `min(250, max(a, 100))` differ only for a NaN, which the EE doesn't have |
| dsd-max-args | `max.s`'s two orders differ only for a NaN |
| sp-relaxed, sp-again-relaxed | as gl-relax, for SignPostDecision's two GetNewDrivingLines |

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
  decision into nSignpostIndex with every slot used.
