# The records and the lap times

A finished race offers each player's car to the challenge records:
five best total times for every track, car class, direction and lap
count, and five best laps for every track, class and direction. The End
Game screens' Best Lap Times and Best Total Times list the five of the
race's kind, with the ones this race set in their player's colour. The
End Game Menu's View Lap Times goes to Lap Times 1P or 2P, each player's
laps of this race.

The records are `HighScoreTable` and the names `FrontendDatabase`'s
(`0x00186a20` to `0x00186e08`). The screens are End Game classes
([end-game.md](end-game.md)), `0x001ddb80` to `0x001e2388`. Slice RE-3
ported them in `3DS Files/source/highscore.c` and `endtimes.c`.

## The tables

`Fred.ChallengeHighScores` (Fred +1720) is 64000 bytes: 7200
`TotalTimesTable` records, then 800 `LapTimesTable` records at +57600.
A record, `FredHighScore`, is 8 bytes:

| Offset | Field |
|---:|---|
| 0 | `Time`, a packed Timer |
| 4 | `NameIndex`, a short: the name's slot |
| 6 | `CarType`, a short |

`high_score_table_init_stats_tables` (fred.c) sets every time to
`0x7fffffff`. The five of a kind start at its index, fastest first:

- totals: track × 450 + class × 90 + direction × 45 + lap index × 5;
- laps: track × 50 + class × 10 + direction × 5.

The track is its `HighScoreIndex` and the direction is 0 or 1
([race-start.md](race-start.md) has both indexes).
`GetBestTotalTimesTable` (`0x00186d98`) and `GetBestLapTimesTable`
(`0x00186dd0`) add the index to the table.

### The names, Fred +0x100b8

128 names of 12 bytes. `LookupPlayerNameFromTable` (`0x00186a20`)
answers the slot, or NULL from 128 up. `InsertPlayerName`
(`0x00186a50`) walks the slots:

- an empty one (first byte 0): clear its 12 bytes, copy 11 bytes of the
  name whatever its length, and answer it;
- one that matches the name (`bStrCmp`): answer it.

A full table answers -1. A name of twelve letters is stored as eleven,
so it never matches and takes a new slot each time.

## MaybeRecordHighScore, `0x00186af0`

TheRaceIsOver ([race-over.md](race-over.md)) offers each player's racing
car, the one with the better lap first:

1. Clear the player's `BestTotalRecordData` (+2556) and
   `BestLapRecordData` (+2552).
2. If the car ran every lap (`NumLapsCompleted` +9 equals the race's
   `NumLapsInRace` +1604), find the first of the five totals its
   `RaceTime` (+180) is below. The comparison is signed, so 0 and
   negative times place. Make room there, write the time, and fill the
   record. The player's `BestTotalRecordData` points at it.
3. The same for the laps, with `GetBestLapTime`: `BestRunningTimes`
   (+96) at the race's `FinishLineBoundaryNumber` (+1619). A short race
   still offers its lap.

Making room moves the records from the place down one, and the fifth
drops off. Retail copies them through five records on the stack, whose
times it zeroes first. Filling a record writes the car type's `Type`
(+1332) and the slot `InsertPlayerName` gives the player's name, in the
global Fred. A slot of -1 is 0.

The track, direction and lap count are `TheRaceParameters`'. The class
is the car's `CarTypeInfo` `CarClass` (+230), read as a byte. The answer
is the total's place as a byte, 255 for none. TheRaceIsOver drops it.

## Who set a record

`WhichPlayerSetLapTimeRecord` (`0x001ddb80`) and
`WhichPlayerSetTotalTimeRecord` (`0x001ddbc8`) walk
`PlayerPlayersByIndex` up to `NumPlayers`. Each answers the
`PlayerNumber` (+16) of the first player whose record pointer is this
record, or -1.

## Best Lap Times and Best Total Times

Both are 8 bytes, the base alone. Their vtables are `0x002b8ff8` and
`0x002b8fc8`: an empty Scroll, the base's HandleEvent, empty Tick and
Render, and the destructor (`0x001e2388`, `0x001e2370`). The destructor
puts its own vtable back and runs the base's.

The constructors (`0x001ddc10`, `0x001ddfd0`):

1. Run the base's constructor.
2. Find the five records for the track, the first racing car's class,
   the direction and, for the totals, the lap count.
3. Set Race Results' track-name object to
   `GetTheRightTrackLanguageID(CurrentTrackInfo, direction)`.
4. Show rows 1 to 5. Row n's objects are `POS_n`, `NAME_n`, `TYPE_n`
   and `TIME_n`, by SprintfAndHash.
5. Say the record speech, once per list.

A row whose record has no time (0, or `0x7fffffff`) is hidden. Any other
row shows:

| Object | Text |
|---|---|
| `POS_n` | n, `"%2d"` |
| `NAME_n` | the name in the record's slot |
| `TYPE_n` | the car type's short name, through GetTranslatedString by name |
| `TIME_n` | the time (`0x001dc500`), right-aligned |

All four are in `DefaultTextColor`, or, for a record a player set this
race, `PlayerTextColors[player]`.

The first such row sets up the speech:

- the player and the row's place from 0;
- the speech's row of TransientStats: `GetDriver(player == 1)`;
- where the player finished: `GetDriver(player)`'s `FinishPosition`,
  if below 9.

After the rows, the speech is said if the list's flag is clear, a row
was found, the finish is below 4, and the speech's row exists. Best Lap
Times says `PostGameLapRecord` (`0x00207298`) and sets `Zeroed[7]`
(+52). Best Total Times says `PostGameTimeRecord` (`0x00207330`) and
sets `Zeroed[8]` (+56). Both set their flag whether they spoke or not,
so going back to the screen is silent.

## The Lap Times screens

`LAP_TIMES_1P` (`0xc4881cbd`) and `LAP_TIMES_2P` (`0xc4881cde`) share a
callback, `0x001e10f0`:

| Message | Does |
|---|---|
| ACTIVATE | `bMalloc(4, "LapTimesDisplay", 0, 16)`, constructed with the item hash, into `pLapTimesDisplay` (gp-17472) |
| UNACTIVATE | the destructor with flags 3, then NULL |
| anything else | HandleEvent: every message but BACK goes silent |

`LapTimesDisplay` is 4 bytes, the screen hash, with no vtable. Its
constructor (`0x001e0bd0`):

1. Sets the track's name as the best times do.
2. Puts player 0's name, or player 1's if there is no player 0, on
   `NAME_1` (`0x6dbbc830`). With neither, it stops. The name goes
   through a 128-byte buffer and FindFlailerObject's SetString.
3. With two player cars, puts player 1's name on `NAME_2`
   (`0x6dbbc831`). With no player 1, it stops.
4. Takes TransientStats' drivers 0 and 1. With no driver 0, driver 1 is
   the first column and there is no second.
5. Shows laps 1 to 9. Lap n's objects are `LAPNAME_n`, `LAP_n`,
   `P1_LAP_n` and `P2_LAP_n`. `LAP_n` gets n, `"%d"`. Each column gets
   the driver's `LapTimes[n]` (+52), right-aligned, in the lap-record
   colour if it is that driver's best lap, else `DefaultTextColor`. A
   column with no driver, or a lap with no time, is hidden.
6. Hides all four of every lap past the most laps (`NumLapTimes`, +96)
   either driver ran.

A driver's best lap is the first smallest of laps 1 to 9, compared
signed and skipping 0. The lap-record colour (`0x0031a000`, 134, 96, 48,
128) comes from the end game screens' static init (`0x001e1ea0`).

## The port

main.c binds:

| Seam | main.c |
|---|---|
| `gEndGameScreenCtorFns` for BEST_LAP_TIMES and BEST_TOTAL_TIMES | `best_lap_times_construct`, `best_total_times_construct` |
| `kScreens`' Lap Times 1P and 2P | `lap_times_display_callback` |
| `gHighScoreMaybeRecordFn` | `fedMaybeRecordHighScore`, which logs the total's place and whether the lap set a record |
| `gFEDSetRecordTimesToBeatFn` | `fred_set_record_times_to_beat` on `Fred` ([race-start.md](race-start.md)) |
| `gPostGameLapRecordFn`, `gPostGameTimeRecordFn` | `post_game_lap_record`, `post_game_time_record` ([race-speech.md](race-speech.md)) |

`Player`'s `BestLapRecordData` and `BestTotalRecordData` are now
`FredHighScore` pointers. The 3DS layout is unchanged.

Retail reads these unchecked; the port guards them:

- an index outside the table, from a class outside 0 to 4: the port
  finds no records, where retail reads past the table;
- `LookupPlayerNameFromTable` below 0 is NULL, which the rows print as
  "";
- a car with no player: MaybeRecordHighScore writes no pointers and
  fills the name slot with 0;
- WhichPlayer stops at two players and skips an empty one;
- `PlayerTextColors` for a player other than 0 or 1 is
  `DefaultTextColor` (retail's index 2 lands on it; 3 would be the lap
  colour);
- no `pCurrentRace` or first racing car: no records; no
  `pEndGameScreens`: no speech;
- the Lap Times' FindFlailerObject, and the callback's bMalloc, may be
  NULL;
- a lap's time is printed with `"%s"`, where retail uses the time as its
  own format; a time has no '%', so the text is the same.

### A fix in the port's first version

The first version of making room always moved four records from the
place. A record set at place k (from 0) pushed k of the five into the
next kind's first k, which are another class's, direction's or lap
count's records. Retail's copy goes through five on the stack and
never leaves the five. Reading the disassembly found it. Since then,
`records_script`'s "tables' ends" cases show the record on each side
of the five.

## Checking

`tools/endtimes_check.py` runs retail's MaybeRecordHighScore, the name
table, both table lookups, WhichPlayer, both screens and the Lap Times
callback in `retail_model.RetailEmu`, next to
`tools/src/endtimes_test.c` with `endtimes.c`, `highscore.c` and
`bprintf.c`. The stubs print on both sides: the base's constructor, the
Flailer calls, both GetTranslatedStrings, GetTheRightTrackLanguageID,
the timer's text (`endresults_check.py` checks it), the two indexes
(`fredrace_check.py`), the speeches, bMalloc and bFree.

The script covers:

- the names: eleven and twelve letters, empty names, holes and a full
  table;
- the records: each place, ties, a time that beats nothing, a short
  race, each finish line boundary, zeros and negative times, the tables'
  ends with their neighbours shown, a borrowed name and a full name
  table;
- both screens: no records, each place for each player, both players'
  records, the speech's flags, finish places, rows and missing drivers,
  PlayerNumber 2, and the class, track and direction;
- the Lap Times: no player and each, one and two player cars, the
  drivers' laps, and UNACTIVATE with none up and twice;
- 120 random cases of each.

The result is 6019 ops, 36642 lines, 0 differ. `--mutate` catches all
95 mutations.

In Azahar, a test build that finished the race with a 1:00.00 lap
showed the record as "1 Player1 Opel Speedster 1:00.00" in the player's
amber. View Lap Times showed National Forest, Player1 and laps 1 to 8,
and B went back to the End Game Menu.
