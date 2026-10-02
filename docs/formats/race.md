# `Race` -- the race itself, its boundaries and the lap-time table

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

## Where things are

| retail | what |
|--------|------|
| `0x001467a0` | `TimeAroundTrackTable::TimeAroundTrackTable(int)`, 840 bytes |
| `0x00146ae8` | `TimeAroundTrackTable::GetTimeTableEntry(float, float *)`, 164 bytes |
| `0x00146b90` | `TimeAroundTrackTable::GetTimeAroundTrack(float)`, 32 bytes |
| `0x00146c88` | `RacingCar::UnInit`, `jr ra` |
| `0x001475e8` | `Race::Race`, 244 bytes |
| `0x001476e0` | `Race::~Race`, 236 bytes |
| `0x001479f8` | `Race::AddBoundaryPosition(char *, bVector2 *, float)`, 292 bytes |
| `0x00147b20` | `Race::FigureOutBoundaries`, 568 bytes |
| `0x00147d58` | `Race::GetLapNumberExact(float)`, 104 bytes |
| `0x001485e0` | `Race::SetupGhostCars`, empty |
| `0x001493b8` | `RacingCar::RacingCar`, 272 bytes |
| `0x001494c8` | `TimeAroundTrackTable::~TimeAroundTrackTable`, 28 bytes |
| gp-22272 | `pCurrentRace`, `0x003301f0` (the demo's was `0x003232f8`) |
| gp-31484 | 1/180, `0x3bb60b61` |
| gp-31444 | 0.01, `0x3c23d70a` |
| `0x002af498` .. `0x002af528` | the seven marker names (below) |

The `TheRaceParameters` (`0x0031a898`) words read here:

| offset | what |
|--------|------|
| +12 | `TrackDirection`, 0 forward |
| +40 | `Point2Point` |
| +44 | `NumLapsInRace`, 2 by default |

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
