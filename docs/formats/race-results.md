# Race Results and the reward screens

The first screens after a race are the rewards it earned, then Race
Results. Race Results lists every car in finishing order with one stat
at a time beside it. Under it is the points tally. Points Rewards and
Task Rewards each tell of a car unlocked. All three are classes of the
End Game screens ([end-game.md](end-game.md)), made by the screens'
callback when their screen comes up. They read what TheRaceIsOver left
in Fred ([race-over.md](race-over.md)).

The code is retail's `0x001dc500` to `0x001e25d0`, with the counts and
tasks in NFSRewards (`0x0024af40` to `0x0024b430`). Slice RE-2b ported
it in `3DS Files/source/endresults.c`.

## Race Results, `0x001dffe8`

A `RaceResultsScreen` is 60 bytes, `bMalloc(60, "RaceResultsScreen", 0,
16)`:

| Offset | Field |
|---:|---|
| 0 | `EndGameMenusBase` (the screen hash and the vtable) |
| 8 | `tSlideshowStats`, 24 bytes: the hash, the columns' `bTList` (+4), `AnimTimer` (+12), `Refresh` (+16), `CurrentColumn` (+20) |
| 32 | the points tally, 28 bytes: the hash, `Timer` (+4), the lines' `bTList` (+8), `Current` (+16), `TopLeftX` and `TopLeftY` (+20, +24) |

The vtable is at `0x002b9058`: Scroll `0x001e0838`, the base's
HandleEvent, Tick `0x001e0868`, an empty Render, and the destructor
`0x001e23b8`.

The constructor:

1. Runs the base's constructor, then makes the slideshow and the tally.
2. Sets the track's name and race number (`0x001dc5d8`, adding 0).
3. Sets the title. A tree event's race (GameType 8 or 9) gets "Event %d
   Results" printed with the event's `Number` (`+104`, a short). Any
   other race gets "Race Results".
4. Shows the rows, one per TransientStats row, up to 8. Row n's
   objects are `POS_n`, `NAME_n`, `TYPE_n`, `TIME_n` and `BEHIND_n`, by
   SprintfAndHash. For each row:
   - the car comes from `GetCarByNumber(row's UniqueDriveNumber)`, and
     the driver from the car;
   - POS, NAME, TYPE and TIME are made visible;
   - POS gets `"%2d"` of the place;
   - NAME gets a player's name in the player's colour (`PlayerTextColors`,
     by `PlayerNumber`), or an AI's `DriverInfo::GetName` in
     `DefaultTextColor`;
   - all five objects take the colour;
   - TYPE gets the car's short name through
     `GetTranslatedString(const char *)`;
   - TIME is right-aligned. TIME itself stays empty: the stats go in
     BEHIND.
5. Hides rows `NumStats + 1` to 8.
6. Runs ShowPointsResults (`0x001e0430`).
7. Shows "previous" (`0xaf6f1cdc`) unless the list is at its first
   screen.

Scroll steps the slideshow: PAD_LEFT one column back, PAD_RIGHT one on.
Tick runs the slideshow's tick, then the tally's.

### The slideshow, `tSlideshowStats`

Each column is a `tStatsColumn`, 76 bytes, `bMalloc(76, "tStatsColumn",
0, 16)`: a `bNode`, the title's LanguageID (+8), then 8 rows of {value,
type} (+12). The columns, each only when its test passes:

| Column | When | Each row |
|---|---|---|
| Time | always | see below |
| Points | `ShouldSeeTourney` | `GetPointsForFinishPos(place - 1)`: 10 6 4 3 2 1 0 0 |
| Tickets | `nMaxCops > 0` | `NumTickets` |
| Best Lap | not point to point, and `NumLapsInRace` not 1 | `BestLapTime` |
| Avg. Speed | always | `AverageSpeed` × 2.237 (mph), or × 3.6 (km/h) by the Units option |
| Top Speed | always | `TopSpeed`, the same |

The Time column:

- in a RaceType 3 race, every row but the first is "Eliminated";
- otherwise a car the cops caught (FinishReason 2) is "Arrested";
- the first row has its race time;
- every other row has its time minus the first row's, as a gap.

A row's value is printed into its `BEHIND_n` by type. The text format
option 64 is right alignment.

| Type | Printed |
|---:|---|
| 0, int | `"%d"`, right-aligned |
| 1, float | `"%3.f"`, right-aligned |
| 2, time | `Timer::PrintToString` (flags 0) when valid, right-aligned; else `""` |
| 3, language | the LanguageID when not 0, else `""`; then right alignment cleared |
| 4, gap | `PrintToString` with the minus flag (1) unless `0x7fffffff`, right-aligned; else `""` |

A valid time is one that is neither 0 nor `0x7fffffff`. A gap of 0 is
still printed. The column's title goes in `0xee0b838a`.

The fades run on RealTimer, 4000 ticks a second, from `AnimTimer`:

| Seconds | Does |
|---|---|
| to 5 | `Refresh` cleared, alpha 128 |
| 5 to 5.5 | alpha `(1 - 2(t - 5)) × 128`, truncated |
| 5.5 to 6 | the next column put up once (wrapping to the first), then alpha `2(t - 5.5) × 128` |
| 6 on | `AnimTimer` restarted |

The alpha goes on `BEHIND_1` to `BEHIND_8`. `Refresh` is only cleared
while shown, so if the first tick comes after 5.5 seconds, `Refresh`
still has the constructor's leftover value. A scroll puts the column up
at once, clears `Refresh` and restarts the clock. Left from the first
column goes to the last.

### The points tally

ShowPointsResults first asks the GameType 6 test. A GameType 6 race
hides the tally's groups (`0x26c0a2e8`, `0xab0f6086`) and stops there.
Otherwise it shows both groups and sets the screens' first speech flag
(`+24`). Then, by `NumPlayerCars`:

- **One player.** It reads driver 0's row and adds the lines (each
  `bMalloc(16, "tPointsThingy", 0, 16)`):
  - "Points Earned:" with `PointsThisRace`;
  - when `FinishBonus` is not 0, the place's bonus, labelled "1st Place
    Bonus:", "2nd Place Bonus:", "3rd Place Bonus:" or "No bonus";
  - "Total Points Earned:" with the bonus plus the race's points.

  `PointsTotal` goes in `0x27aa4eff`, and the first line is put up.
- **Two players.** Player 1's row puts "Player 1 Points:" and its
  `PointsThisRace` in the tally's line (`0x68a2d5d1`, `0x123d12fe`).
  Player 2's puts "Player 2 Points:" and its points in `0x896f342e` and
  `0x27aa4eff`. A player with no row has both objects hidden. The
  two-player path never starts the tally.

Points are printed with `FormatPoints`, which puts in the language's
thousands separator. Each line is shown for 5 seconds, then fades out
over half a second (`FlailerSetGroupAlpha` on `0xab0f6086`). After 5.5
seconds the next line (wrapping) comes up at 128 and the clock
restarts. With fewer than two lines it stays still.

The tally then tests the speech flag it has just set, so
`PointsScreenSpeech` (`0x002075b0`) never plays from Race Results.

The destructor frees the tally's lines and the columns, from the head
of each list, then runs the base's destructor.

## Points Rewards, `0x001de568`, and Task Rewards, `0x001de6a8`

Both are 8 bytes: the base, with vtables `0x002b9118` and `0x002b90e8`.
Each has empty Scroll, Tick and Render, and a destructor that goes back
to the base's.

**Points Rewards** takes the car of `PointsRewardEarned`
(`GetCarTypeForPointsReward`). Its blurb is "You've earned enough
points to unlock the %s in all Challenge Modes!", followed by "Keep
playing to unlock more cars!" until all 18 points rewards are earned.
The %s is the car's short name, through `GetTranslatedString(const char
*)`. The blurb is word-wrapped into `0x461d42d0` by RenderTextIntoGroup.
The car's speech (`0x00207488`) plays once, on the screens' first flag
(`+24`). The title (`0x4703a605`) is "POINTS REWARD", and the count is
the Challenge Mode one.

**Task Rewards** takes the task of `TaskRewardEarned`. Its blurb is the
task's `EndOfRaceUnlocked` string. Retail prints the string with itself
as the format; no string has a '%', so the port copies it. The speech
for the task's reward car plays once, on the second flag (`+28`). The
title is "TASK REWARD". The count is the You're The Cop one when the
task unlocks in GameType 7, else the Challenge Mode one.

GetNumPointsRewardsEarned (`0x0024b1b0`) counts how many of the 18
rewards' states in Fred are not 0, whatever their order.

### The count, `0x001de3a8`

"You have %d out of %d cars available in all Challenge Modes."
(`0xea7f4`) or "... in You're The Cop Mode." (`0xea7f5`) is
word-wrapped into `0x1a190ea0`. The counts run over all 64 car types:

| Count | Cars |
|---|---|
| available (`0x001de3a8`'s first) | usage 0 and usage 1 cars that are unlocked (`IsCarUnlocked(i, -1)`), or else have `InitialLockStatus` 0; plus `New784`; plus, for a race event (GameType 4, 8 or 9), each reward of type 0 that passes `ShouldSeeRewardMenu` and is earned (`0x00200b30`) |
| of | the usage 0 cars plus the usage 1 cars |
| cop available | usage 1 cars whose `BeACopLockStatus` is 0, or is 1 and `IsCarUnlocked(i, 7)` |
| cop of | the usage 1 cars |

`0x001de550` clears the count to `""`.

## The port

main.c binds `gEndGameScreenCtorFns` for RACE_RESULTS, POINTS_REWARDS
and TASK_REWARDS. `gRenderTextIntoGroupFn` is
`bpopup_render_text_into_group` on the flow. The race event's rewards
(`gRaceEventRewardTypeFn`, `gRaceEventRewardEarnedFn`) stay NULL until
step 16. main.c binds the two speeches (`gRewardCarSpeechFn`,
`gPointsScreenSpeechFn`) to RewardCarSpeech and PointsScreenSpeech
([race-speech.md](race-speech.md)).

Retail reads these unchecked; the port guards them:

- a row whose car is not in the world, or has no driver: the port
  leaves the row as it is;
- a one-player race with no row for driver 0: retail puts its own list
  head up as a tally line; the port shows nothing;
- more than 8 rows: retail writes past the column; the port stops at 8;
- the points table: retail reads round it for any place. The bytes from
  7 before it to 32 after it are 0, as the port answers.

## Checking

`tools/endresults_check.py` runs all of the above in
`retail_model.RetailEmu`, next to `tools/src/endresults_test.c`, with
`nfsrewards.c`, `timer.c` and `bprintf.c`. The stubs are the base, the
end game's tests, the Flailer calls, RenderTextIntoGroup, both
GetTranslatedStrings, the car lookups, IsCarUnlocked, the event's reward
test, the speeches, bMalloc and bFree. The harness prints the two lists'
nodes at retail's sizes (76 and 16), as a 64-bit host makes them wider.

The script covers:

- the timer's text in six languages;
- the rewards' count over Fred's states;
- every task;
- the car counts over usage, locks and unlocks;
- both reward screens over every reward and both speech flags;
- Race Results over every column's test, knockouts, arrests, tourneys,
  units, a tree event's title, every bonus place, one and two players,
  GameType 6, the fades through two cycles, scrolls both ways, RealTimer
  wrapping, and 150 random races.

The result is 6455 ops, 45145 lines, 0 differ. `--mutate` catches all
144 mutations.
