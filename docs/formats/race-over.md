# What a race leaves behind

When a race ends, the frontend database (`Fred`, `0x002fc050`) keeps what
the next screens and the next race need:

- the options changed in the race;
- each player's points;
- the high scores;
- a row of results per car;
- the race event's results;
- the task and points rewards the race earned.

The code is FrontendDatabase's end of a race, `0x00186e08` to
`0x001878b0`, and the rewards' checks in NFSRewards, `0x0024ab90` to
`0x0024b914`. Slice RE-2a ported both in `3DS Files/source/fredend.c`.
The screens that read the results are in [end-game.md](end-game.md)
and [race-results.md](race-results.md).

## When it runs

| Retail | Called by | Port |
|---|---|---|
| `CheckForAbortion`, then `TheRaceIsOver(pCurrentRace)` | `TheRaceHasFinished`, every player through (`rcstates.c`) | `gFEDCheckForAbortionFn`, `gFEDTheRaceIsOverFn` |
| `TheRaceWasQuit` | Quit Race (`rcpost.c`) | `gFEDTheRaceWasQuitFn` |
| `TheRaceWasRestarted` | Restart Race (`rcpost.c`) | `gFEDTheRaceWasRestartedFn` |
| `TheRaceIsLeaving` | the race stage becoming RACING (`racerun.c`) | `gRaceIsLeavingFn` |
| `TransientStats::GetDriver(n)` | POSTRACE's ACTIVATE, for the camera's player | `gTransientStatsGetDriverFn` |
| `IsCarUnlocked(car, gameType)` | the car lists and the Points Rewards test | `gIsCarUnlockedFn` |

## TheRaceIsOver, `0x001875a0`

1. `GetOptionsSetFromRace`.
2. For each racing car that has a player:
   - outside Be A Cop, note the cars of players 0 and 1;
   - when this database's `NumPlayerCars` is 1, `AwardPointsToPlayer`.

   The Be A Cop test reads `Fred.GameType`, not this database's; the
   image has the address.
3. Offer the high scores (`MaybeRecordHighScore`, `0x00186af0`) on
   `ChallengeHighScores`:
   - one player: that player's racing car;
   - two players: the one with the smaller best lap first, compared as
     signed words. A tie offers player 1 first.
4. `TransientStats::Construct` over the race.
5. With a race event (`UseTheRaceEvent`: GameType 4, 8 or 9), its
   `PostResults` (`0x002018f8`).
6. `CheckForTaskAndPointRewards`.

A car's best lap is `GetBestLapTime`: `BestRunningTimes` at
`pCurrentRace`'s `FinishLineBoundaryNumber`.

## TransientStats, at Fred+908

| Offset | Field |
|---:|---|
| 0 | `NumStats` |
| 4 | `PointsRewardEarned`: the points reward's index, or -1 |
| 8 | `TaskRewardEarned`: the task's number, or -1 |
| 12 | eight rows of 100 bytes |

`Construct` (`0x00186ff0`) sets `NumStats` to 0 and then builds a row for
each of the race's racing cars, with no bound. A race never has more than
eight. `GetDriver` (`0x00187080`) gives the first row whose drive number
matches, or NULL.

### A row, `TransientStatsElement::Construct` (`0x00186e08`)

| Offset | Field | From |
|---:|---|---|
| 0 | `FinishPosition` | `RacePosition` (`lb`) |
| 4 | `UniqueDriveNumber` | the car's `DriverNumber` (`lh`) |
| 8 | `FinishReason` | `FinishReason` (`lh`) |
| 12 | `RaceTime` | `RaceTime` |
| 16 | `BestLapTime` | `GetBestLapTime` |
| 20 | `PointsThisRace` | the player's `TotalScore`; 0 for the AI |
| 24 | `PointsTotal` | `Fred.FrontendPlayers[n].AccumulatedPoints`; 0 for the AI |
| 28 | `FinishBonus` | `FigureOutBonusPoints(&Fred, pCurrentRace, rc)`; 0 for the AI |
| 32 | `NumTickets` | `GetNumTickets` with a cop manager, else 0 |
| 36 | `HandlingMode` | the player's `DrivingStyle`; -1 for the AI |
| 40 | `TopSpeed` | see below |
| 44 | `AverageSpeed` | `AverageSpeed` |
| 48 | `BeACopTime` | the cop manager's `fBeACopTime`, for player 0 in Be A Cop; else 0 |
| 52 | `LapTimes[11]` | zeroed, then `[1 .. n]` copied, n below 11 |
| 96 | `NumLapTimes` | `NumLapsCompleted` (`lb`) |

An AI car's top speed loses up to 5%. The cut is `bRandom(1.0)` on
`bDefaultSeed` times `0.05` (gp-30188), and the result is capped at its
type's `Control.SpeedLimiter` with `min.s`. Each AI row moves the seed.

## The options, `GetOptionsSetFromRace` (`0x001870d0`)

- Each of the `PlayerNumPlayers` players, by index, copies its 48 bytes
  of settings into its `FrontendPlayers[n].mPlayerSettings` and into
  `TheRaceParameters.PlayerSettings[n]`.
- `DamageEnabled` goes into the game type's setup:

| GameType | Word |
|---:|---|
| 3 Single Race | `SingleRaceSetupData[6]` |
| 4 Knockout | `RaceKnockoutSetupData[6]` |
| 5 Lap Knockout | `LapKnockoutSetupData[5]` |
| 6 Free Run | `FreeRunSetupData[2]` |
| 7 You're The Cop | `BeTheCopSetupData[4]` |

- The 8 bytes of `GlobalDisplaySettings` go into `Fred`'s
  `DisplayOptionsData` (`0x002fc19c`), whichever database this is.
- `SetAudioDataFromSound(AudioOptionsScreenData, 0)`: the jukebox's
  volumes, without rebuilding the tune list.

## The points

`FigureOutBonusPoints` (`0x00187378`) is 0 in Be A Cop, and for a car
that is not player 0's. Otherwise the field decides whether the place
`p` (`FinishingOrder`) earns anything:

| Racing cars | Earns |
|---:|---|
| 1 | never |
| 2 | p = 1 |
| 3 | p = 1 or 2 (`p - 1` unsigned, at most 1) |
| 4 or more | always |

What it earns is `Player::GetFinishBonus(p)`.

`AwardPointsToPlayer` (`0x00187438`) adds to the player's
`AccumulatedPoints`, in this order:

1. `TotalScore`;
2. the bonus;
3. in Be A Cop, `cvt.w.s` of the cop manager's `fBeACopTime` times 100.
   The time is 0 with no cop manager.

## Abortion, quitting, restarting

- `CheckForAbortion` (`0x00187518`) sets `bRaceWasAborted` (Fred+67368)
  to 1 when either of `PlayerPlayersByIndex[0..1]` is there and has
  `TimeFinishedRacing` 0. Otherwise it is 0.
- `TheRaceWasQuit` (`0x00187800`):
  1. checks abortion and keeps the options;
  2. with a race event: if every player is through, simulates the finish
     and notifies the race (`0x00148f68`, `0x00148ff8`);
  3. posts the results and keeps the event's state (`0x00201fb0`).
- `TheRaceWasRestarted` (`0x00187880`) cycles the race event's results.
- `TheRaceIsLeaving` (`0x00187570`) may discard them.

## The rewards

`Fred` keeps one word per task at +0x106b8 (`TaskRewardStates[10]`) and
one per points reward at +0x106e0 (`PointsRewardStates[18]`). A word is 0
until the reward is earned, and is saved with `Fred`.

### The tasks, `NFSTasks` (`0x0031cfc0`, 10 × 56 bytes)

-1 is "any". MinDamage is a float; any value but -1 asks for a race
without a collision (see below).

| Task | MinDamage | Players | GameType | Opponents | Laps | Skill | Laps led | Cops | In | Car |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0 | 1 | 3 | -1 | 4 | 1 | -1 | -1 | -1 | 16 |
| 2 | 0 | 1 | 3 | -1 | 8 | 1 | -1 | -1 | -1 | 5 |
| 3 | -1 | 1 | 3 | 3 | 2 | 1 | 2 | 1 | 7 | 31 |
| 4 | -1 | 1 | 3 | 7 | 2 | 1 | 2 | 0 | -1 | 44 |
| 5 | -1 | 1 | 3 | 3 | 4 | 1 | 4 | 1 | 7 | 34 |
| 6 | -1 | 1 | 3 | 7 | 4 | 1 | 4 | 0 | -1 | 36 |
| 7 | -1 | 1 | 3 | -1 | 8 | 1 | 8 | 0 | -1 | 24 |
| 8 | -1 | 1 | 4 | -1 | -1 | 1 | -1 | 1 | 7 | 32 |
| 9 | -1 | 1 | 4 | -1 | -1 | 1 | -1 | 0 | -1 | 14 |
| 10 | -1 | 1 | 5 | -1 | -1 | 1 | -1 | 1 | 7 | 33 |

"In" is `UnlockedInGameType`: the game type whose car lists the reward
unlocks in, -1 for all of them. Task n's state is word n - 1.

`NFSTaskParameters::CheckForCompletion` (`0x0024ab90`) compares the task
with the race. Each test is skipped when the task's field is -1, and the
first test that fails returns 0:

| Field | Compared with |
|---|---|
| MinDamage | the player's word at +2540, set at the start and cleared by a collision |
| Players | `TheRaceParameters.NumPlayerCars` |
| GameType | `Fred.GameType` |
| Opponents | `NumAICars` |
| Laps | `NumLapsInRace` |
| Skill | `OpponentStrength` |
| Laps led | the racing car's `NumLapsLed` |
| Cops | `nMaxCops > 0` |

The GameType test has two more parts:

- a Knockout (4) with `Fred.NumPlayerCars` 1 must have fewer than three
  cars in all, and be won (`FinishingOrder` 1);
- a Lap Knockout (5) must be won.

The function works out the car's `GetVisibleTotalDamage` first and then
drops it. A car with no player reads its +2540 word from address 2540,
which is 0, so the port tests for NULL there.

### The points rewards, `NFSPointsRewardsArray` (`0x0031d1f0`, 18 × 12 bytes)

| Index | Points | Car | Index | Points | Car |
|---:|---:|---:|---:|---:|---:|
| 0 | 50,000 | 15 | 9 | 1,000,000 | 26 |
| 1 | 100,000 | 20 | 10 | 1,500,000 | 3 |
| 2 | 150,000 | 28 | 11 | 2,000,000 | 46 |
| 3 | 200,000 | 25 | 12 | 2,500,000 | 1 |
| 4 | 250,000 | 42 | 13 | 3,000,000 | 48 |
| 5 | 300,000 | 23 | 14 | 3,500,000 | 18 |
| 6 | 400,000 | 30 | 15 | 4,000,000 | 8 |
| 7 | 500,000 | 12 | 16 | 4,500,000 | 6 |
| 8 | 750,000 | 40 | 17 | 5,000,000 | 10 |

A reward is reached when the points are not below its own.

### CheckForTaskAndPointRewards, `0x0024b7b0`

1. Both of TransientStats' words become -1.
2. It goes no further with two players, or with no player 0.
3. Outside Hot Pursuit (GameType 2), each task that player 0's racing car
   completed and has not earned gets state 1. `TaskRewardEarned` keeps
   the last one's number.
4. Each points reward that `FrontendPlayers[0].AccumulatedPoints` reached
   and has not earned gets state 1. `PointsRewardEarned` keeps the last
   one's index.

Several rewards can be earned at once. Task 5's race without a collision
also completes task 1, for example, and a big score can pass two points
marks. Every state is set,
but the words keep only the last of each, and the screens show that one.

### IsCarUnlocked, `0x0024b208`

1. A task's reward in this game type: its task's state.
2. You're The Cop (7): 0.
3. An event's reward (`IsCarAnEventReward`, `0x001ff8b8`): the event
   tree's answer (`0x001ff918`).
4. A points reward: its state.
5. Any other car: 0.

`TaskRewardsIsCarUnlocked` (`0x0024aed0`) and
`PointsRewardsIsCarUnlocked` (`0x0024b120`) return the first matching
reward's state, earned or not.

## The port

`fredend.c` takes the database as `f` wherever retail takes `this`. It
writes `Fred` itself where the image does: the display options, the Be A
Cop test, the rows' accumulated points, the reward states and the words.
main.c fills the seams:

| Seam | main.c |
|---|---|
| `gFEDCheckForAbortionFn`, `gFEDTheRaceIsOverFn`, `gFEDTheRaceWasQuitFn`, `gFEDTheRaceWasRestartedFn`, `gRaceIsLeavingFn` | `fed*` wrappers on `Fred`. TheRaceIsOver logs the rows, both words and the points |
| `gTransientStatsGetDriverFn` | `fedTransientStatsGetDriver` on `Fred.TransientStatsTable` |
| `gSetAudioDataFromSoundFn` | `fedAudioFromSound`: `jb_audio_from_sound` with the sound's audio mode |
| `gIsCarUnlockedFn` | `nfs_is_car_unlocked` |
| `gHighScoreMaybeRecordFn` | NULL until RE-3 |
| `gRaceEventPostResultsFn`, `MaybeDiscardResultsFn`, `CycleResultsFn`, `gIsCarAnEventRewardFn`, `gEventTreeIsCarUnlockedFn` | NULL until the race events (step 16) |

Before RE-2a, `TaskRewardEarned` was never set to -1. Its 0 put the Task
Rewards screen on every race's list, and that class's placeholder text
showed. Now the screens appear only when something was earned. Their own
classes are RE-2b's.

## Checking

`tools/fredend_check.py` runs retail's functions in
`retail_model.RetailEmu`, next to `tools/src/fredend_test.c`. The script
covers:

- the rows for player cars, AI cars, Be A Cop, the boundary, the lap
  counts and the seed;
- the options for every game type and number of players;
- the bonus for every field and place;
- abortion, the race's end, quitting and restarting for each kind of race;
- each task's tests one field at a time, and a task of the script's own
  with each test on and off;
- the reward lists over their states;
- the unlocked tests over every car and game type;
- random mixes.

The result is 29034 ops, 57323 lines, 0 differ. `--mutate` catches 164 of
165 mutations. The other is equivalent: a player's number is only ever 0
or 1, so `!= 1` is `== 0`.
