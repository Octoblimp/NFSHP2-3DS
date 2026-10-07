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

This file has 11e-1. Two slots still wait: DoSnapshot waits on
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
| 652 | aStickyDecisions, eight words; bit 0 says a slot is in use |
| 684 | TakenSignpostIndex: retail's own, the sign whose route the car took (-1 none) |
| 688 | TakenSignpostTimer: retail's own, set when GetCurrentTrackRoutePoint takes a sign's route |
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
- GetCarAhead and HighlightDrivingLine.

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

The check gives 156 scenarios, 24485 ops, 15468 lines, 0 differ.

Its mutation pass has 126 mutations: 121 caught and 5 equivalent.

| Mutation | Why it's equivalent |
|----------|---------------------|
| sr-relax, gl-relax | the relaxed switch never reaches a target IsDriveable reads (above) |
| gl-relax0 | SetRoute's switch is overwritten by SetDrivingLine's on every pass before IsDriveable reads it, and with no pass the location isn't read |
| gl-list | the constructor points CurrentNearbyCarList at the controller's own list, and nothing in 11e-1 moves it |
| gp-ahead | GetCarAhead only reads, and retail drops its answer |

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

Not scripted:

- a find on a controller with retail's own table and a clear location
  (slot 112 is `__pure_virtual`);
- a route number over 99;
- FindClosestTrackRoute finding a route through drivingchoice_check's
  table, whose SetCurrentRoute is no one's;
- GeneratePointsToFulfillAction's second CalculatePointsToDrive on a NULL
  action.
