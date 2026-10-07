# Race::Update

Race.obj's step and the finish, from retail (SLES_507.31). This is step
11g-2b. Before it, a race from the frontend reached RACING's flow
([quick-race.md](quick-race.md)) but stayed at COUNTDOWN, because
`gRaceUpdateFn` was NULL. Now the countdown's GO starts the race, the race
time runs, the laps count, and the cars finish.

| Address | Function | Bytes | Port |
|---------|----------|------:|------|
| `0x001473f8` | RacingCar's race time projection (new, no name) | 328 | `racingcar_project_race_time` |
| `0x00147558` | `RacingCar::GetLastFinishLineCrossingTime` | 24 | racesplit.c |
| `0x00148320` | `Race::MonitorLeadership` | 464 | `race_monitor_leadership` |
| `0x001484f0` | `Race::MaybeSaveGhostCarData` | 240 | `race_maybe_save_ghost_car_data` |
| `0x001485f0` | `Race::FinishCar(int, int, bool, eRaceFinishReason)` | 504 | `race_finish_car` |
| `0x00148940` | `Race::UpdateGhostCar` | 312 | `race_update_ghost_car` |
| `0x00148a78` | `Race::Update` | 1264 | `race_update` |
| `0x00149160` | `Race::GetLeadingUnfinishedCar` | 96 | `race_get_leading_unfinished_car` |
| `0x001491c0` | `Race::GetFinisher` | 68 | `race_get_finisher` |
| `0x00149208` | `Race::GetNextFinishRank` | 68 | `race_get_next_finish_rank` |
| `0x00149250` | `Race::FinishCar(Car *, int, bool, eRaceFinishReason)` | 96 | `race_finish_car_by_car` |
| `0x00176650` | `Player::SetFinishedRacing` | 344 | playerfinish.c |
| `0x001908d8` | AICarController's pull-over (new, 24 bytes) | 24 | `aicarcontroller_force_pull_over` |

The port's files:

- **`3DS Files/source/raceupdate.{c,h}`:** the Race functions.
- **`3DS Files/source/playerfinish.{c,h}`:** Player::SetFinishedRacing.
- **aicarcontroller.h:** the pull-over, an inline.

`tools/raceupdate_check.py` cross-checks them against
`tools/src/raceupdate_test.c`, with the retail image running in mipsemu as
the oracle.

The wiring:

- **`World::DoTimestep`** calls Update once a step through worldstep.c's
  `gRaceUpdateFn`.
- **`SimulateRaceFinish`** ([race-coordinator.md](race-coordinator.md))
  finishes the cars through `gRaceFinishCarFn`.
- **main.c** sets both seams.

## Update

`Race::Update` runs these steps in order:

1. **The countdown's end.** At COUNTDOWN, when
   `GetCountdownNumberToDisplay` is 4 (GO), the stage becomes RACING.
2. **The race time.** At RACING, `RaceTime` is `WorldTimer - StartTime`,
   then `Timer::Round`ed to 0.01 s.
3. **`UpdateGhostCar`.**
4. **The laps.** For each racing car whose `FinishReason` is 0, in
   `pRacingCars` order:
   - `UpdateLapCounts` runs;
   - for a car with a player, a last best lap time (at the finish line's
     boundary) below the race's `BestLapTime` replaces it. Both are
     compared signed.
5. **A forced finish**, when `ForceRaceFinishPosition` is not 0. See
   below.
6. **`SortRacingCarsByLeadership`, then `MonitorLeadership`.**
7. **A lap knockout** (`RaceType` 3). Take each car that crossed the line
   this step with `NumLapsCompleted + RacePosition == NumRacingCars`. Every
   unfinished car after it in `pRacingCars` is finished at its own index
   + 1, blinking, as KNOCKED_OUT.
8. **A time trial** (`RaceType` 2). An unfinished car that crossed the
   line, with a valid last lap time, finishes (position 0, NORMAL) when
   `TimeTrialTime` is not below that lap time. The two are compared
   signed.
9. **The laps led.** An unfinished car that crossed the line in first
   place gets one more `NumLapsLed`, a halfword that wraps.
10. **The finish.** With `NumLapsInRace` not 0, every unfinished car whose
    `NumLapsCompleted` equals it finishes (position 0, NORMAL).
11. **The speech.** Each car still unfinished that crossed the line gets
    `LapFinishedSpeech(car, NumLapsCompleted)`. A car that completed a lap
    without crossing gets `SplitTimeSpeech`, which is `jr ra`, so the port
    leaves it out.

Each loop re-reads `NumRacingCars` and `pRacingCars[i]` on every pass, so
a car finished in one loop is seen as finished by the next.

### The forced finish

`NumRacingCarsFinished` goes back to 0 first. Then the first car in
`pRacingCars` that meets all of these is finished, and the loop stops:

- it is unfinished;
- it has a player;
- that player's `PlayerNumber` is `ForceRaceFinishPlayerNum`.

That car is finished at `ForceRaceFinishPosition`, without blinking, as
NORMAL. The exception is a player who is the player cop: the cop
manager's `GetPlayerCop` has a car, and that car's `pPlayer` is this
player. Then the position is -1, which leaves the order alone. The
reason is the cop's win (5) when the position is below `NumRacingCars`,
and the cop's loss (6) otherwise. Both fields go back to 0 afterwards,
whether or not a car was found.

## FinishCar

`FinishCar(index, position, blink, reason)` works on `pRacingCars[index]`:

1. **The cop's times.**
   - **The cop's win:** `RaceTime` is `WorldTimer - StartTime`, rounded.
   - **The cop's loss:** `RaceTime` is `TimeTrialTime` (signed, in
     seconds) plus 0.01 s, as `Timer::SetTime` stores it (x 4000, + 0.5,
     `cvt.w.s`), and then rounded.
2. **The place.**
   - **`position` 0, for a car that has done the race's laps:** its
     `FinishingOrder` is `GetNextFinishRank`, and its `RaceTime` is its
     last finish line crossing less `StartTime`, unrounded. A car with a
     player then runs `MaybeSaveGhostCarData`.
   - **`position` 0, for any other car:** the next rank, and a projected
     time (below) over `NumLapsInRace`.
   - **A positive `position`:** that is the order, as a byte.
   - **A negative `position`:** the order is left alone.
3. **The record.** In order:
   - `FinishReason` takes the reason;
   - `FinishedLapNumberExact` takes `CurrentLapNumberExact`;
   - `NumRacingCarsFinished` goes up;
   - `TheRaceEvent.RecordResults(this, rc, FinishingOrder)` runs.
4. **A player's car.** `Player::SetFinishedRacing` runs, then
   `Car::SetControlMode(AI_CONTROL)`, which builds an AIDriver for it.
5. **An AI-controlled car pulls over.** Any car whose mode is now
   AI_CONTROL runs the pull-over at 0x001908d8 with
   `AIActionPullOverCrossFinishLineTimeout` (gp-18156, 15.0;
   [ai-driver.md](ai-driver.md)):
   - `ForceCurrentAction` becomes PULL_OVER;
   - `PullOverTimeout` becomes `min.s(old, 15)`.
6. **The blink.** With `blink`, `Car::BlinkBlinkPoof` runs.

`FinishCar(Car *, ...)` finds the car's racing car in `pRacingCars`,
takes `position` 0 as its `RacePosition`, and calls the first. It does
nothing for a car that is not in the race.

### The projected time (0x001473f8)

This function is new in retail, and the demo's `FinishCar` has none of
it. It works out the fraction of the race done, then the race time from
it, and maybe a projected best lap.

**The fraction done.** It is `CurrentLapNumberExact / laps`, with
`div.s`, so laps 0 gives ±FLT_MAX on the EE. The floor is 0.01. The
floor is a branch (`c.lt.s ; bc1f`), not `max.s`, so a NaN is kept.

**The race time.** It is `(WorldTimer - start)` (signed, x 0.00025) over
the fraction, put through `SetTime`, then rounded.

**The best lap.** It is only projected when both of these hold:

- the car has not finished a lap;
- `laps` is over 0.

The time is the ticks since the last start line crossing, over the
fraction, over `laps`. It goes to the last best lap time at the finish
line's boundary (x 4000, + 0.5, `cvt.w.s`), and is rounded.

`pCurrentRace`, not the race passed, gives the boundary numbers. The
image reads past the five-entry arrays for a boundary number out of
[0, 4]. The port's accessors read 0 and write to a spare Timer, as
racesplit.c does.

## The finders

- **`GetLeadingUnfinishedCar`:** of the cars with `FinishingOrder` 0, the
  one with the lowest `RacePosition` that is below `NumRacingCars + 1`.
  The first of equal ones wins. It answers NULL when there is none.
- **`GetFinisher(rank)`:** the first car in `pRacingCars` whose
  `FinishingOrder` equals `rank`, or NULL.
- **`GetNextFinishRank`:** counts up from 1 until `GetFinisher` finds
  nothing.

## MonitorLeadership

This runs for each player in `PlayersByIndex[0 .. NumPlayers)`, skipping
NULL. A player whose `RacePosition` differs from its
`PreviousRacePosition` (call it `prev`) is compared with the car at
`pRacingCars[prev - 1]`, the car now in its old place. Events need all of
these:

- the player's car is over 40 m/s;
- it is within 25 m of that car (`(x² + y²) + z²`, as the VU0 sums it).

Then the replay events are:

- **`GainPosition`:** `4 / position + 1`, when the position went down.
- **`LosePosition`:** `2 / prev`, when it went up.
- **`ClosePass`:** 2.5 as well, when the two speeds are within 7 m/s.

The image indexes `pRacingCars[prev - 1]` unchecked. A `prev` past
`NumRacingCars` reads NULL, and one below 1 reads before the array. The
port skips both. Neither happens once the field is sorted, since
`SortRacingCarsByLeadership` gives every car a place from 1 to n.

## The ghost cars

Retail never makes a ghost: `SetupGhostCars` is empty. So
`pCapturingGhostCar`, `pCapturingGhostCarData` and
`pReplayingGhostCarData` stay NULL, and this code never runs. It is
ported as it is, against a 82080-byte `GhostCarData`: 160 bytes of head
and 1024 samples of 80 bytes.

**`MaybeSaveGhostCarData(rc)`** does nothing unless `rc`'s car is the
capturing car. For that car:

1. The data takes `rc`'s `RaceTime`.
2. It is written to `GhostCarDataFilename` (`host0:...`, the size being
   the head plus the samples taken) when both of these hold:
   - the car has done the race's laps;
   - there is no replaying ghost, or this time is below the replaying
     ghost's (signed) over the same `NumLaps`.
3. The data is freed (`__builtin_delete`).
4. Both capture pointers go back to NULL.

The two `Timer::PrintToString` calls write into the stack for a print
that is compiled out, so the port leaves them out.

**`UpdateGhostCar`** works in two parts:

1. **The capture.** At RACING with a capturing car, the car's
   `BodyMatrix`, with its `Position` as the last row, is added at
   `RaceTime`.
2. **The replay.** With a replaying ghost and a valid `RaceTime`,
   `GetSample(data, &m, &RaceTime)` is asked for the matrix at that time:
   - when it finds one, z drops by 0.5 and the ghost's WorldObject takes
     the matrix and is enabled;
   - when it finds none, the WorldObject is disabled.

The image takes `bSin(time x 43690.668)` (gp-31400) on the way and then
loads -0.5 over the answer, so the bob is dead code. The port leaves the
call out.

## Player::SetFinishedRacing

This runs once: a nonzero `TimeFinishedRacing` returns at once. On the
first call:

1. `TimeFinishedRacing` takes `WorldTimeFrames`.
2. If the car has done the race's laps, three things happen:
   - **The replay event.** Outside You're The Cop, `CrossFinishLine` is
     worth 10, plus 7.5 for each other racing car within 30 m. The count
     includes the car itself, hence the -1.
   - **The speech queue.** With every player finished, `ClearEventQueue`
     runs on the wedge.
   - **The sound.** `TriggerFinishLineSound(player)` runs.
3. `FinishAnimationLength` becomes 360 frames.

The demo's version (0x001700d0, 276 bytes) has no near-car count.

## The constants

| gp | Value | Use |
|---:|------:|-----|
| -31452 | 0.01 | ProjectRaceTime's floor and rounding |
| -31448 | 0.00025 | ticks to seconds |
| -31396, -31408, -31416 | 0.01 | the other roundings |
| -31404, -31412 | 0.00025 | the other tick conversions |
| -31400 | 43690.668 | the dead bob's bSin scale |
| -18156 | 15.0 | AIActionPullOverCrossFinishLineTimeout |

The 40, 25, 7, 30, 4, 2, 2.5, 7.5, 10 and -0.5 are built with `lui`.

## The port's seams

- **`gLapFinishedSpeechFn`:** LapFinishedSpeech.
- **`gSpeechClearEventQueueFn`:** cSEDWedge::ClearEventQueue.
- **`gTriggerFinishLineSoundFn`:** TriggerFinishLineSound.
- **`gGhostCarDataAddSampleFn`, `gGhostCarDataGetSampleFn`:** the ghost
  data's samples.
- **`gBWriteToFileFn`:** bWriteToFile.

All of them stay NULL until speech (task 26), the sound and the ghosts
are ported, and NULL does nothing.

`RegisterInterestingEvent` is called on `pReplayManager` unchecked in the
image. The port tests it, as carfinish.c does, since there is no
ReplayManager yet.

## The checker

`tools/raceupdate_check.py` runs 12 functions as shipped:

- Update, FinishCar (both), the projection, MonitorLeadership,
  MaybeSaveGhostCarData, UpdateGhostCar, the three finders,
  `SimulateRaceFinish` and `SetFinishedRacing`.

Under them, these run as shipped too:

- `GetCountdownNumberToDisplay`, `AreAllPlayersFinishedRacing`,
  `RacingCar::GetPlayer` and the boundary accessors;
- the pull-over, `Timer::SetTime`, `Round` and `bSin`.

These are stood in on both sides, each printing a line:

- **Race:** `UpdateLapCounts` and `SortRacingCarsByLeadership`, which do
  nothing more, and `SetRaceStage`, which sets the stage.
- **Car:** `SetControlMode`, which for AI_CONTROL hands the car a second
  controller (`b<car>`) as the AIDriver would, and `BlinkBlinkPoof`.
- **Replay and results:** `RegisterInterestingEvent`, with the value and
  the name, and `RecordResults`.
- **Speech and sound:** `LapFinishedSpeech`, `ClearEventQueue` and
  `TriggerFinishLineSound`.
- **The ghost data:** `AddSample` and `GetSample`, the latter answering
  the script's matrix.
- **Files and memory:** `bWriteToFile` and `__builtin_delete`.

`PrintToString` is stood in silently.

After each call the dump covers:

- the race and its order;
- the eight racing cars by field;
- the cars' modes and controllers;
- the players' finish times;
- the ghost's WorldObject and both ghost data times.

The scenario families:

- **The finders:** over orders, ties and positions past the field.
- **The projection:** laps -1 to 7 over a best time already set, the
  fraction at its floor an ulp either side, times that wrap, a best lap
  a third of a tick under a half hundredth (SetTime's + 0.5 carries it
  over Round's half), and every pair of boundaries.
- **FinishCar:** every reason x position x laps done x player x blink;
  the cop's times at their edges (two of them, 128140 and 523620, just
  under a whole tick at 20 mod 40 in float32); the pull-over's timeout either side of
  15 under each mode; a second finish; each finish line; by car,
  including a car whose racing car is another's.
- **`SimulateRaceFinish`.**
- **`SetFinishedRacing`:** the 30 m edge an ulp either side, a car that
  z alone takes out of range, You're The Cop, and the other player
  finished or not.
- **MonitorLeadership:** positions and old places, speeds at 40 and 7
  m/s either side, the 25 m edge on each axis, NULL players, and the
  order in `pRacingCars` that differs from the table's.
- **The ghosts:** the save over every capture, replay, time and laps
  case, through FinishCar and through Update; UpdateGhostCar over the
  stage, the capture, the replay, the time's validity and the sample's
  answer.
- **Update:**
  - the countdown at GO's edges, at each stage, for the racer and the
    cop;
  - the best lap, signed, for players and others;
  - the race time;
  - the forced finish over positions, players and seven cop manager
    cases, plus one player with two cars;
  - the lap knockout, the time trial at its edges, and the laps led and
    the finish.
- **A race run:** 60 steps from the countdown to the finish.
- **300 random rounds.**

Result: 997307 ops, 73230 lines, 0 differ.

The mutation pass makes 161 mutations over raceupdate.c, playerfinish.c,
racesplit.c's new accessor and the pull-over. All 161 are caught, 7 of
them by a crash, and none is equivalent. Four survived the first pass
and each needed a scenario:

- **pr-laps0:** a projection over laps 0 writes a saturated best time.
  The field's best times were already 0x7fffffff, so it needed one set.
- **pr-best-half and fc-lost-half:** truncating without the + 0.5 is
  one tick out. Round only shows that across its half, 20 ticks mod 40.
- **pf-near-z:** no car had been brought out of 30 m by z alone.
