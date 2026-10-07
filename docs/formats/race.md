# `Race` -- the race itself, its boundaries, the lap-time table and the lap counting

A `Race` is what counts the laps. `RaceCoordinator::InitForRace` makes one
before the cars, and it lives as long as the race does. The constructor
sets `pCurrentRace`, finds the track's lap boundaries, and zeroes the eight
`RacingCar`s it holds. `Race::Init` (step 8d) then adds the racing cars,
sets the stage, and builds a `TimeAroundTrackTable` for the first player's
car.

Step 8c is the construction: the constructor and destructor, the
boundaries, `GetLapNumberExact`, `RacingCar`'s constructor, and the
`TimeAroundTrackTable`'s four functions. The port is `3DS
Files/source/racecore.c`/`racecore.h`. `race.h` now declares the whole
`Race`, and `race.c` adds `TheRaceParameters`' `Point2Point` and
`NumLapsInRace`.

`tools/racecore_check.py` runs the retail image itself in RetailEmu as the
oracle: 9 scenarios, 6097 ops, 18698 transcript lines, 0 differ. Of its
161 mutations, 158 are caught, one of them by crashing the harness, and
3 are equivalent by construction.
Before the run it compiles `racecore.h` with devkitARM and asserts
`Race`'s and `TimeAroundTrackTable`'s layout.

Step 8d is the race's running half: `Race::Init` and what it calls. They
add the racing cars, set the stage, count the laps, time the boundaries
and order the field. The port is `3DS Files/source/racerun.c`/`racerun.h`,
with `Timer::Round` and `RoundSeconds` in `timer.c`. `race.h` adds the
`RaceTypes` enum and `TheRaceParameters`' `RaceType`.

`tools/racerun_check.py` runs them as shipped in RetailEmu: SCEN
scenarios, OPS ops, LINES transcript lines, 0 differ. Of its TOTAL
mutations, CAUGHT are caught, CRASHED of them by crashing the harness and
HUNG by hanging it, and EQUIV are equivalent by construction. Before the
run it compiles `racerun.h` with devkitARM and asserts
`BoundaryCrossingInfo`'s layout and `RacingCar`'s size.

## Where things are

| retail | what |
|--------|------|
| `0x001467a0` | `TimeAroundTrackTable::TimeAroundTrackTable(int)`, 840 bytes |
| `0x00146ae8` | `TimeAroundTrackTable::GetTimeTableEntry(float, float *)`, 164 bytes |
| `0x00146b90` | `TimeAroundTrackTable::GetTimeAroundTrack(float)`, 32 bytes |
| `0x00146bb0` | `RacingCar::Init(Car *)`, 212 bytes (8d) |
| `0x00146c88` | `RacingCar::UnInit`, `jr ra` |
| `0x00146e08` | `RacingCar::FakeStartlineCrossing`, 76 bytes (8d) |
| `0x00146e58` | `RacingCar::CheckBoundaryCrossing(BoundaryCrossingInfo *, float, float)`, 372 bytes (8d) |
| `0x00146fd0` | `RacingCar::UpdateLapCounts`, 1064 bytes (8d) |
| `0x001475b8` | `RacingCar::GetPlayer`, 24 bytes (8d) |
| `0x001475e8` | `Race::Race`, 244 bytes |
| `0x001476e0` | `Race::~Race`, 236 bytes |
| `0x00147960` | `Race::Init(eRaceStage)`, 148 bytes (8d) |
| `0x001479f8` | `Race::AddBoundaryPosition(char *, bVector2 *, float)`, 292 bytes |
| `0x00147b20` | `Race::FigureOutBoundaries`, 568 bytes |
| `0x00147d58` | `Race::GetLapNumberExact(float)`, 104 bytes |
| `0x00147dc0` | `Race::AddRacingCars`, 196 bytes (8d) |
| `0x00147e88` | `Race::AddRacingCar(Car *)`, 100 bytes (8d) |
| `0x00147ef0` | `Race::SetRaceStage(eRaceStage)`, 464 bytes (8d) |
| `0x00148218` | `Race::SortRacingCarsByLeadership`, 264 bytes (8d) |
| `0x00149078` | `Race::CanAICarsStartDriving`, new in retail (11e-5) |
| `0x001485e0` | `Race::SetupGhostCars`, empty |
| `0x001493b8` | `RacingCar::RacingCar`, 272 bytes |
| `0x001494c8` | `TimeAroundTrackTable::~TimeAroundTrackTable`, 28 bytes |
| `0x001a3cf0` | `Timer::CountDown(float)`, new in retail (11e-5) |
| `0x001a3d70` | `Timer::RoundSeconds(float)`, 180 bytes, the demo's `0x00199af8` (8d) |
| `0x001a3e28` | `Timer::Round(float)`, 80 bytes, new in retail (8d) |
| gp-22272 | `pCurrentRace`, `0x003301f0` (the demo's was `0x003232f8`) |
| gp-31484 | 1/180, `0x3bb60b61` |
| gp-31444 | 0.01, `0x3c23d70a` |
| gp-31480, -31476, -31472, -31440 | 0.01 again, for `FakeStartlineCrossing`, `CheckBoundaryCrossing`, `UpdateLapCounts` and `SetRaceStage` |
| gp-31468 | 0.44702727, `0x3ee4e0c2`: mph to m/s |
| gp-31464, gp-29388 | 0.00025, seconds a tick |
| gp-31460, gp-31456 | 0.333 and 0.667, the lap rate's smoothing |
| gp-22120 | `pCurrentWorld` |
| gp-22440 | `pReplayManager`; its word 0 is `ReplayingFlag`, read without a test |
| gp-19576, -19564, -19560 | `WorldTimer`, `WorldTimeFrames`, `WorldTimeElapsed` |
| `0x002af498` .. `0x002af528` | the seven marker names (below) |

The `TheRaceParameters` (`0x0031a898`) words read here:

| offset | what |
|--------|------|
| +12 | `TrackDirection`, 0 forward |
| +32 | `RaceType`, `0x0031a8b8` (8d) |
| +40 | `Point2Point` |
| +44 | `NumLapsInRace`, 2 by default |
| +48 | `NumPlayerCars` (8d) |
| +628 | `BeACop` (8d) |

`RaceType` is the `RaceTypes` enum (type#1000): 0 none, 1 single race, 2
time trial, 3 lap knockout, 4 race knockout, 5 tournament. Only the time
trial is tested here. `InitWithDefaults` starts it at 0.

These callees are ported already: the two `TrackPathCoordinate`
constructors, `UpdatePosition` and `ComparePercentDistances` (`0x002085e8`,
[track-path.md](track-path.md)), `TrackRoutePoint::GetPosition`
(`0x001c1390`), and the track's position markers
(`GetTrackPositionMarker`, `0x00151478`).

The one seam is the `WorldObject` destructor (`0x001cd828`, flags 3),
which is `worldobject.h`'s `gWorldObjectDeleteFn`. Nothing in retail makes
the replaying ghost car's `WorldObject`, so it does not matter that the
seam is NULL.

## `Race`, 1716 bytes

The layout is the demo's (.mdebug type#1645).

| offset | what |
|--------|------|
| 0 | `RaceStage` |
| 4 | `StartGoTimeFrames` |
| 8 | `StartCountdownTimeFrames` |
| 12, 16, 20 | `StartTime`, `RaceTime`, `BestLapTime`: `Timer`s |
| 24 | `NumRacingCars` |
| 28 | `NumRacingCarsFinished` |
| 32 | `DetectedOneCarRemaining` |
| 36 | `RacingCarTable[8]`, 192 bytes each |
| 1572 | `pRacingCars[8]` |
| 1604 | `NumLapsInRace` |
| 1608, 1612 | `ForceRaceFinishPosition`, `ForceRaceFinishPlayerNum` |
| 1616 | `NumBoundaries`, a short |
| 1618, 1619 | `StartLineBoundaryNumber`, `FinishLineBoundaryNumber`: signed bytes |
| 1620 | `BoundaryDistances[5]`, percentages round the track |
| 1640, 1648 | `StartLinePosition`, `FinishLinePosition`: `bVector2`s |
| 1656 | `pReplayingGhostCarData` |
| 1660 | `pReplayingGhostCarWorldObject` |
| 1664 | `pCapturingGhostCar` |
| 1668 | `pCapturingGhostCarData` |
| 1672 | `GhostCarDataFilename[40]` |
| 1712 | `pTimeAroundTrackTable` |

## The constructor and the destructor

`RacingCar::RacingCar` zeroes the `Timer`s and nothing else: the five
arrays of five at 36 to 132, `LapTimes[11]` at 136, and `RaceTime` at
180.

`Race::Race` runs in this order:
1. It zeroes the three `Timer`s and builds the eight `RacingCar`s.
2. It sets `pCurrentRace` to this race and `RaceStage` to 0.
3. `NumLapsInRace` is `TheRaceParameters`' count, or 1 when that count and
   `Point2Point` are both non-zero.
4. It zeroes the force fields, `StartTime` and `RaceTime` again, the three
   counts, the four ghost-car pointers, the two frame counts and both line
   positions.
5. `BestLapTime` is `0x7fffffff`. Then `FigureOutBoundaries`, and
   `pTimeAroundTrackTable` is NULL.

It never writes `pRacingCars` or `GhostCarDataFilename`.

`Race::~Race`:
1. It calls `UnInit` on each racing car below `NumRacingCars`. That does
   nothing.
2. When `pReplayingGhostCarData` is set, it is freed. Only inside that
   test, when the `WorldObject` is set too, the `WorldObject` is destroyed
   with flags 3. A `WorldObject` without its data is left alone.
3. It frees `pCapturingGhostCarData` when set. The table, when set, gets
   its destructor with flags 3.
4. `pCurrentRace` is NULL. With flags & 1 the race is freed.

## The boundaries

A boundary is a percentage round the track. `AddBoundaryPosition(name,
pos, dist)` adds one:
1. When `dist` is over 100 it takes 100 off. `pos` is zeroed.
2. When the track has a marker `name` (index 0), the boundary is the
   marker's place: a `TrackPathCoordinate` at the marker's position, and
   its ratio times 100. `pos` gets the marker's position.
3. Otherwise, when `dist` is 0 or more, the boundary is `dist`.
4. Otherwise nothing is added, and the answer is -1.

The answer is the new boundary's number, `NumBoundaries` before the add.
Nothing checks the count against 5. A sixth boundary would land on
`StartLinePosition`.

`FigureOutBoundaries` starts with `NumBoundaries` at 0. The start line is
`B[s]`, with s the start's number:

| forward (`TrackDirection` 0) | anything else |
|------------------------------|---------------|
| `ForwardStartLine`, 5 | `BackwardStartLine`, 5 |
| `SplitTimeBoundary1`, B[s] + 33 | `SplitTimeBoundary3`, -1 |
| `SplitTimeBoundary2`, B[s] + 66 | `SplitTimeBoundary2`, B[s] + 33 |
| `SplitTimeBoundary3`, -1 | `SplitTimeBoundary1`, B[s] + 66 |
| `ForwardFinishLine`, B[s] + 95, on a `Point2Point` race only | `BackwardFinishLine`, B[s] + 95, the same |

So split 3 is a boundary only when the track has a marker for it. The
start's position is `StartLinePosition`. With `Point2Point`, the finish's
number and position are the finish line's. Without it, they are the
start's. `Point2Point` is read once.

The start is always boundary 0, because the count was just reset and 5 is
not negative. The finish is -1 only when it has no marker and B[0] + 95 is
negative, which needs a start marker whose percentage is below -95. `B[-1]` is then the
four bytes before the array, `NumBoundaries` and the two numbers, read as
a float. The port reads the boundaries through the race's bytes so it does
the same.

`GetLapNumberExact(pct)` is how far round a lap `pct` percent round the
track is, measured from the finish line. It is
`ComparePercentDistances(pct, B[finish])`, plus 100 when that is below 0,
times 0.01.

## `TimeAroundTrackTable`, 2052 bytes

This table holds how long a car of one class takes from the line to any
point of a lap. It is `TotalTimeAroundTrack` and then 256 entries, one per
1/256 of a lap. An entry is eight bytes, the stabs' type 1607. The stabs
keep neither its name nor its fields' names, so `TimeTableEntry`, `Rate`
and `Time` are the port's. `Rate` is laps a second over that part of the
lap, and `Time` is the seconds from the line to the part's start.

The constructor, with `car_class` n, reads driving line 2n:
1. It zeroes the entries and the total.
2. It goes through each route on `TheTrackRouteManager`'s racing list
   (+0) whose line 2n's flags (route +40 + 48 · 2n) are valid or fake. One
   `TrackPathCoordinate`, built with no position, serves the route. For
   each point k up to the second-to-last:
   1. The line's offsets at points k and k + 1 are the halfword at +48 +
      2 · 2n, shifted left 8 and times 2^-16. `GetPosition(d = 0, offset)`
      puts each point on the line.
   2. `UpdatePosition` to each point, and `GetLapNumberExact` of
      `pCurrentRace` at its ratio times 100, give lap0 and lap1. The race
      is the current one, not one of the table's own.
   3. When lap1 - lap0 is over 0.5, lap0 has wrapped and gets 1 added.
      Otherwise, when lap0 - lap1 is over 0.5, lap1 gets 1 added.
   4. The rate is (lap1 - lap0) / (distance / speed). The distance is the
      straight line between the two points. The speed is point k's byte at
      +90 + 2n, shifted left 16 and times 2^-16.
   5. The rate goes into the entry lap0 is in, when it is positive and the
      entry has none yet.
3. Then it walks the entries in order. Each one's `Time` is the time so
   far. An entry with no rate takes the one before's, and 1/180 (a lap in
   three minutes) for the first. Each entry adds (1/256) / rate. The total
   is the sum.

`GetTimeTableEntry(lap, time)`:
- A negative lap counts as 0.
- The entry is `EntryTable[trunc(frac · 256)]`, with `frac` the lap's
  fractional part.
- With `time` set, it gets the whole laps times the total, plus the
  entry's `Time`, plus (frac - slot/256) / `Rate`.

`GetTimeAroundTrack` is that time. The destructor has nothing to undo,
and with flags & 1 it frees the table.

The image truncates with `cvt.w.s`, which the port does with `eefpu.h`'s
`ee_trunc_w`. A lap of 2^31 or more, or a NaN, would index outside the
table in both.

## `RacingCar`, 192 bytes

The layout is the demo's (.mdebug type#1620). The one-byte fields are
`char` and the two-byte ones `short`, so all of them are signed.

| offset | what |
|--------|------|
| 0 | `pCar` |
| 4, 6 | `CurrentBoundaryRegion`, `HighestBoundaryRegion`: shorts |
| 8 | `CurrentLapNumber` |
| 9 | `NumLapsCompleted` |
| 10, 11 | `RacePosition`, `PreviousRacePosition` |
| 12 | `FinishingOrder`, 0 until the car finishes |
| 13, 14, 15 | `CrossedFinishLine`, `CompletedNewLap`, `CrossedNewBoundary` |
| 16 | `NumLapsLed`, a short |
| 18 | `FinishReason`, a short |
| 20, 24 | `CurrentLapNumberExact`, `dCurrentLapNumberExact` |
| 28 | `PreviousDistanceAroundTrack`, a percentage |
| 32 | `FinishedLapNumberExact` |
| 36 | `BoundaryCrossingTimes[5]` |
| 56 | `RunningTimes[5]` |
| 76 | `PreviousRunningTimes[5]` |
| 96 | `BestRunningTimes[5]` |
| 116 | `PreviousBestRunningTimes[5]` |
| 136 | `LapTimes[11]` |
| 180 | `RaceTime` |
| 184, 188 | `TopSpeed`, `AverageSpeed` |

The `Timer`s are ticks of 1/4000 s. A region is `CurrentLapNumber * 5 +
i` for boundary i, so every lap has five, whether or not the race has
five boundaries.

`BoundaryCrossingInfo` (type#3298, 12 bytes) is what
`CheckBoundaryCrossing` hands back: `CrossedForwards` (0),
`CrossedBackwards` (4) and `TimeSinceCrossing` (8, a `Timer`).

These are the retail `Car` offsets 8d reads:

| retail | what |
|--------|------|
| +12 | `pCarTypeInfo`. Its byte 230 is `CarClass`, and +800 `SpeedLimiter`, in mph. |
| +24 | `pPlayer` |
| +28 | `pRacingCar` |
| +32 | `TheControlMode`: 1 real, 2 AI |
| +44 | `pCarDriver`: `Throttle` +532, `Brake` +536, `EBrake` +540, the vtable +556, a `RealDriver`'s `StartLineState` +572 |
| +940 | `DistanceMoved`, `State` +876 (below) |
| +956 | `nWheelsTouchingGround` |
| +960 | `ForwardSpeed` |
| +992 | `BoostFactor` |
| +1192 | `RenderingEnabled`, a byte |
| +2032 | `TheTrackPathCoordinate`'s `RatioAroundTrack` (+16) |

Retail's `CarState` has a float the demo's lacks, at +876 after
`Odometer`. Retail's `FinishMovement` (`0x00131da8`) adds to it how far
`Position` moved since `vOldPos`, and `UpdateLapCounts` divides it by the
race time. The port calls it `DistanceMoved` and keeps it in the record's
spare tail, at 1012 (`carstate.h`), so that every demo offset holds. The
port's `FinishMovement` is still the demo's and does not add to it, so
`AverageSpeed` stays 0 in the game until `FinishMovement` has its retail
pass.

## `Race::Init` and the racing cars

`Race::Init(stage)`:
1. `AddRacingCars`, then `SetRaceStage(stage)`.
2. The car is `RacingCarTable[1]`'s under `BeACop` with `NumPlayerCars`
   2, and `RacingCarTable[0]`'s otherwise. Its `CarClass` builds the
   `TimeAroundTrackTable`, on `bMalloc(2052, "TimeAroundTrackTable", 0,
   16)`, into `pTimeAroundTrackTable`.

`AddRacingCars` adds the World's (gp-22120) `CarTable` entries below
`AICarPos`, which are the players' cars. Then it adds the `CopCarPos -
AICarPos` from `AICarPos` on, the AI racers. The World and both bounds
are read again on every pass. Then it sorts the field twice.

`AddRacingCar(car)` runs `RacingCar::Init` on `RacingCarTable[n]`, with n
the count, then counts it and points `pRacingCars[n]` at it. Nothing
checks the count against 8.

`SetRaceStage(stage)`:
1. `RaceStage` is `stage`. On `RACING` (4), `FrontendDatabase::
   TheRaceIsLeaving` (`0x00187570`, on `0x002fc050`) is told, which drops
   the race event's results when the race uses one. That is the port's
   one seam, `gRaceIsLeavingFn`.
2. For each racing car:
   - A real driver has `RealDriver::DisableStartLineState` (`0x0013b360`)
     when `RaceStage` is `RACING`. Otherwise its `StartLineState` is 1,
     which holds it at the line.
   - An AI driver, when `RaceStage` is `RACING`, gets `EBrake` 0,
     `Throttle` 1 and `Brake` 0, in that order.
   - On `RACING`, `FakeStartlineCrossing`.

   The two drivers' tests read `RaceStage` back, and the rest test the
   argument. The port does the same, though the two are equal.
3. On `COUNTDOWN` (3), `StartGoTimeFrames` is 0 and
   `StartCountdownTimeFrames` is `WorldTimeFrames`. On `RACING`,
   `StartTime` is `WorldTimer` rounded to a hundredth,
   `StartCountdownTimeFrames` is 0 and `StartGoTimeFrames` is
   `WorldTimeFrames`.
4. On either, each traffic car, from `TrafficCarPos` up to `TotalNumCars`,
   gets `RenderingEnabled` 1 and `SetMovementMode(TRAFFIC_MOVEMENT)`
   (`0x00131618`, mode 2). The count is taken once, and the test is
   `(unsigned)(stage - 3) < 2`.

## Counting the laps

`RacingCar::Init(car)`:
1. The car's `pRacingCar` is this, and `pCar` is the car.
2. `RacePosition`, `PreviousRacePosition`, `FinishingOrder`,
   `FinishedLapNumberExact` and `FinishReason` are 0.
3. `PreviousDistanceAroundTrack` is where the car is: its ratio round the
   track times 100.
4. The boundary, running and previous running times are 0, and the best
   and previous best 0x7fffffff. `LapTimes`, `RaceTime`, `TopSpeed` and
   `AverageSpeed` are 0.
5. `NumLapsCompleted` is 0, and `CurrentLapNumber` and both regions -1.
6. `UpdateLapCounts`, which finds no crossing since the car has not
   moved. Then `NumLapsLed` is 0.

It leaves `CrossedNewBoundary`, `CurrentLapNumberExact` and
`dCurrentLapNumberExact` alone, so `UpdateLapCounts` smooths the rate from
whatever they held.

`FakeStartlineCrossing` is the start. `BoundaryCrossingTimes[0]` is
`WorldTimer` rounded to a hundredth, and `HighestBoundaryRegion` is 0. On
a `Point2Point` race, `CurrentBoundaryRegion` and `CurrentLapNumber` are 0
too. On a circuit the car is still behind the line in lap -1. Its first
forward crossing makes lap 0 and region 0, which is not above the
highest, so that crossing is not timed again.

`CheckBoundaryCrossing(info, pct, b)`:
1. d1 is `ComparePercentDistances(pct, b)`, and d0 the same from
   `PreviousDistanceAroundTrack`: signed, the short way round. `info`'s
   three words are 0.
2. With |d1| over 25 there is no crossing.
3. d0 below 0 with d1 0 or more is a forward crossing. d0 0 or more with
   d1 below 0 is a backward one. Anything else is none, so a car that
   stopped exactly on the boundary can only cross it backward.
4. On a crossing, `TimeSinceCrossing` is how long ago the car was on it,
   in ticks: `(int)(past / ForwardSpeed * 4000 + 0.5)`. past is d1 times
   `TrackLength` (`TheTrackPathManager` +0) times 0.01, the metres past
   it. At 1 m/s or slower the time is 0. The listing also works out
   |d1 - d0| and drops it.
5. The answer is 1 on a crossing and 0 otherwise.

`UpdateLapCounts`:
1. `CrossedFinishLine` and `CompletedNewLap` are 0. pct is the car's
   ratio times 100.
2. Each boundary i below `NumBoundaries` is checked. On a crossing:
   - Backward: at the finish line, `CurrentLapNumber` goes down by one.
     Nothing else happens.
   - Forward:
     1. At the finish line, `CurrentLapNumber` goes up by one. When that
        passes `NumLapsCompleted`, `NumLapsCompleted` takes it and
        `CrossedFinishLine` is 1.
     2. `CurrentBoundaryRegion` is the region. Unless it is above
        `HighestBoundaryRegion`, that is all.
     3. `CompletedNewLap` (byte 14) is 1, at any new region and not only
        at a lap's end, and the region is the highest. t is `WorldTimer`
        less `TimeSinceCrossing`, rounded to a hundredth.
     4. With no replay playing: when `BoundaryCrossingTimes[0]` is set,
        neither 0 nor 0x7fffffff, `RunningTimes[i]` is t less it. Its old
        value goes to `PreviousRunningTimes[i]`. `BestRunningTimes[i]`,
        after it is copied to `PreviousBestRunningTimes[i]`, takes the
        running time when that is lower, signed. At the finish line,
        when `CurrentLapNumber` as an unsigned byte is below 11,
        `LapTimes[lap]` takes it too. Then `BoundaryCrossingTimes[i]` is
        t.
     5. While a replay plays, only a time trial's (`RaceType` 2) finish
        line is timed: `RunningTimes[i]` as above when the start is set,
        without the previous or best times, then
        `BoundaryCrossingTimes[i]`.

   `pCurrentRace` is read again at every place the listing reads it.
3. While no replay plays, the speeds. With three wheels or more on the
   ground, `TopSpeed` may change:
   - For a player's car (`GetPlayer` not NULL), s is the larger of
     `TopSpeed` and `ForwardSpeed`.
   - For any other, the driver's `GetDesiredSpeed` (vtable slot 136,
     `cardriver.h`'s `CARDRIVER_VT_GET_DESIRED_SPEED`) is divided by
     `BoostFactor`, taken as at least 1. It is then held to |
     `ForwardSpeed`| and to `SpeedLimiter` in m/s. s is the larger of
     `TopSpeed` and that, but falls back to `TopSpeed` when it is below
     0 or over 1000.

   `TopSpeed` is written only when s differs from it. Then, with the
   race's `RaceTime` (signed) above 0 seconds, `AverageSpeed` is
   `DistanceMoved` over it, whatever the wheels.
4. `CurrentLapNumberExact` and `FinishedLapNumberExact` are
   `CurrentLapNumber` plus `GetLapNumberExact(pct)`. With
   `WorldTimeElapsed` above 0, `dCurrentLapNumberExact` is itself times
   0.333 plus the change in `CurrentLapNumberExact` over
   `WorldTimeElapsed` times 0.667. `PreviousDistanceAroundTrack` is pct.

`GetPlayer` is the car's `pPlayer`, or NULL with no car.

## The sort

`SortRacingCarsByLeadership` is a bubble sort of `pRacingCars`, passed
over until a pass swaps nothing. For a at index i and b at i + 1:
- When a has finished (`FinishingOrder` not 0), they swap when a's order
  is beyond its place, i + 1.
- Otherwise, when b has finished, they swap when b's order is ahead of
  its place, i + 2.
- Otherwise they swap when b's `FinishedLapNumberExact` is further than
  a's. A NaN never swaps.

Then, when there are cars, each one's `PreviousRacePosition` takes its
`RacePosition`, which becomes its place from 1. The count is read once
for the sort and on every pass for the positions.

The sort ends only when the finishing orders are distinct and within 1 ..
n. Two cars with one order, or an order past the field, swap forever.
`FinishCar` (`0x001485f0`, [race-update.md](race-update.md)) is what
gives out the orders.

## `Timer::Round`

`Timer::RoundSeconds(f)` is the demo's code at a new address:
1. q is the time in seconds (the ticks, signed, times 0.00025) over f.
2. q is floored. `cvt.w.s` truncates, and 1 comes off when the result is
   above q. Then 1 is added when the fraction left is a half or more, so
   q rounds half up.
3. x is that times f times 4000, in ticks. It is ceiled the same way:
   truncated, and 1 added when that is below x.
4. The answer is those ticks times 0.00025.

`Timer::Round(f)` is new in retail. It stores `(int)(RoundSeconds(f) *
4000 + 0.5)`. To a hundredth, a time goes to a multiple of 40 ticks, and
the ceiling makes up for `f * 4000` not being exact. The truncations are
`eefpu.h`'s `ee_trunc_w`, which saturates as the EE does.

## `Timer::CountDown` and `Race::CanAICarsStartDriving`

Both are new in retail, and AICarController::Think is their caller
(`ai-car-controller.md`). The port's are `timer_count_down` (timer.c)
and `race_can_ai_cars_start_driving` (race.c). aicarcontroller_check
tests them.

`Timer::CountDown(dt)` counts a running timer down by `dt` seconds:
1. A timer of 0 or 0x7fffffff isn't running and is left alone.
2. Otherwise `(int)(dt * 4000)` ticks come off it, truncated with no
   rounding (`ee_trunc_w`), by a wrapping `subu`.
3. A result negative as a signed word becomes 0.
4. It answers whether the timer is still running (IsValid), so a step
   that lands on 0x7fffffff answers 0 too.

`Race::CanAICarsStartDriving()` answers whether `RaceStage` is `RACING`
(4). In a cop race (TheRaceParameters' BeACop, `0x0031ab0c`, not 0), it
also answers yes from the pre-race (2) on, so the cops roll before the
racers.

## The checker

`tools/racecore_check.py` runs everything above in RetailEmu against
`tools/src/racecore_test.c`. Retail's `TrackPathCoordinate` constructors
and destructor, `ComparePercentDistances`, `GetPosition` and `bScaleAdd`
run as shipped. The stubs:
- `UpdatePosition` gives both distance and ratio from a hash of the
  position, over a track one unit long. The hash is anywhere in 2^-7 to
  2^9 of either sign, or, with `S umode 1`, in [0, 1) as a real track's
  would be.
- `GetTrackPositionMarker` matches by name.
- `__builtin_delete` and the `WorldObject` destructor print what they are
  given.

The Race and the table are filled with 0xa5 before they are built, so a
field left alone shows. The script lays out eight markers and four routes
on the racing list at retail's offsets.

- N, F: the constructor and `FigureOutBoundaries` over every marker set,
  direction, `Point2Point` and lap count.
- SN, A: `AddBoundaryPosition` at each count up to 8.
- SF, SB, L: `GetLapNumberExact` from every finish number, -1 among them.
- G, D, C: the destructor over every set of pointers and flags.
- P, PL, PT, Q, T, E, E0, TA, TD: the table over random routes, classes and
  boundaries, then looked up. These scenarios keep `Point2Point` at 0 and
  leave the boundaries alone, so every lap the table sees is a number
  below 2^31.

The three equivalent mutants are stores that are written again before
they can be read.

`tools/racerun_check.py` runs step 8d's functions in RetailEmu against
`tools/src/racerun_test.c`. Retail's `GetLapNumberExact`,
`ComparePercentDistances` and the `TimeAroundTrackTable` constructor with
its `TrackPathCoordinate` run as shipped under them. The stubs print what
they are given: `bMalloc` (which hands back the table), `SetMovementMode`,
`DisableStartLineState`, `TheRaceIsLeaving`, `UpdatePosition`
(racecore_check's hash) and the drivers' `GetDesiredSpeed`. That last sits
at a made-up address in a vtable the script owns, behind a this-adjustment
it sets. The Race, the Cars and their records are filled with 0xa5 first.

- TR, TS: `Round` and `RoundSeconds` over the ends of the clock, the
  halves and random times and steps.
- K: `CheckBoundaryCrossing` from everywhere to everywhere.
- RI, F, U, P: a few cars driven round for hundreds of steps, now and then
  backward, through the replay's and the time trial's arms.
- AC, A, G: `AddRacingCars` and `SetRaceStage` over the World's counts and
  every stage.
- I: `Race::Init` over the routes, the classes and the two-player cop.
- O: the sort over unfinished cars, NaNs among them, and finished ones
  at the front in any order.
- Two races the way the game runs one, then the edge cases: a car on a
  boundary exactly, an unset start, laps below 0 and at 10, the top
  speed's window, and finished cars anywhere in the sort.

Its two equivalent mutants are a store that `UpdateLapCounts` writes again,
and `TopSpeed`'s only-when-it-changes test. s is either `TopSpeed` itself
or larger, so the store it skips would write back the same bits.
