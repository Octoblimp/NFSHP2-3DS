# race-speech -- what the announcer says about the race

The race's own speech is not the cops' radio
([pursuit-speech](pursuit-speech.md)). It is the announcer at the finish
and after each lap. It also speaks over a knockout, the records, the
tournament standings, an event's result and its reward, a pullover and
Be A Cop's arrests.

Each function adds one SPCH event with `SPCH_AddEventV` (`0x002919d0`,
[spch](spch.md)). The event's parameters are bit flags of the
SPCH1Type enums, and the sentence rules choose on them. Enums are named
in `docs/mdebug_raw_strings.txt`: duringRaceTypeA to D, endRaceTypeA
and B, postGameType, tournamentType, miscType, beCopFinishType,
unlockCarType, unlockHPCarType, unlockCopCarType, unlockTrackType,
eventType, hpEvTreeType and chEvTreeType.

Retail has these in RaceSpeech.obj (`0x00206900` .. `0x00207870`). The
conversions are in Speech's object beside ConvertCarType. The port has
them in `racespeech.{c,h}` and `speechconv.{c,h}`.
`tools/racespeech_check.py` runs retail's code against both.

| function | retail |
|---|---|
| FlipCoinNoReplay | `0x00206900` |
| WeDontWantToSayAnything | `0x00206920` |
| BustedByCops(TransientStatsElement *) | `0x002069f0` |
| BustedByCops(Car *) | `0x00206a00` |
| SpecialLastPlaceSpeech | `0x00206a30` |
| RaceFinishedSpeech | `0x00206ab8` |
| an event's result (no name) | `0x00206bc8` |
| OnePlayerLapSpeech | `0x00206d98` |
| TwoPlayerLapSpeech | `0x00206eb8` |
| LapKnockoutSpeech | `0x00207010` |
| MaybeDoKnockoutRaceOverSpeech | `0x00207018` |
| LapRecordSpeech | `0x002070e8` |
| LapFinishedSpeech | `0x00207198` |
| GetTopTimeFlag | `0x00207270` |
| PostGameLapRecord | `0x00207298` |
| PostGameTimeRecord | `0x00207330` |
| TournamentRaceSpeech | `0x002073f0` |
| an event's reward (no name) | `0x00207450` |
| RewardCarSpeech (no name) | `0x00207488` |
| a track's reward (no name) | `0x00207550` |
| PointsScreenSpeech | `0x002075b0` |
| a pullover (no name) | `0x002075d8` |
| Be A Cop's arrests (no name) | `0x00207648` |
| PlayBustedSpeech | `0x002077b8` |
| SingleP1OrP2, both | `0x002077e0`, `0x00207810` |
| PlayerSingleP1OrP2 | `0x00207840` |
| Speech::ConvertRewardCarType (table `0x0031c300`) | `0x00223328` |
| the event conversions (tables `0x0031c410` .. `0x0031c4e8`) | `0x00223358` .. `0x002233b8` |
| Speech::ConvertTrackNumber (jump table `0x002bce20`) | `0x002233d8` |
| the unlocked track's (jump table `0x002bcf00`) | `0x00223480` |

Not ported:

- **SplitTimeSpeech** (`0x00207268`) is empty. Race::Update's call to it
  is left out.

## The helpers

**The coin.** FlipCoinNoReplay is `bRandom(2) == 0` on the default
seed. Despite its name, it does not check for a replay.

**The player.** SingleP1OrP2 picks one of three flags:

- the first, unless the race has two players;
- the second, for player one's car (`PlayerPlayersByNumber[0]`'s);
- the third, for any other car.

The table version picks one of three tables the same way.
PlayerSingleP1OrP2 picks by the player's number, 0 being player one.

**The replays.** Nothing is said while the coordinator is in
INSTANT_REPLAY (4), POSTRACE (7) or AUTO_REPLAY (5), or in the replay
demo. With no coordinator, nothing counts as a replay.

**WeDontWantToSayAnything** is 1, and nothing is said, when any of these
holds:

- the car has no player;
- the race has no players, or fewer than two racing cars;
- a replay;
- a time trial (race type 2);
- the AI demo (coordinator state 8) or the replay demo (9);
- no race type (0).

Retail reads the coordinator's state without a check for the demos. The
port takes no coordinator as neither demo.

**BustedByCops.** A row is busted when its FinishReason is 2. A car is
busted when the cop manager exists and the car's pullover (by its
CarIndex) is an arrest.

## The finish and the laps

**RaceFinishedSpeech** runs once per player, guarded by
HasHeardRaceOverSpeech. It sets that flag even when it says nothing. Be
A Cop and WeDontWantToSayAnything say nothing. Otherwise:

- **Busted:** event 168 with 512.
- **A knockout** (race type 3 or 4): nothing here.
  MaybeDoKnockoutRaceOverSpeech speaks instead.
- **The last place:** SpecialLastPlaceSpeech.
  - With two cars it always speaks: event 165 with 0 and endRaceTypeB
    8, 16 or 32 (one player, player one, player two).
  - With more cars it speaks on a coin's toss, with 1, 2 or 4.
  - When it says nothing, the place is said instead.
- **Any other place:** event 165 with endRaceTypeA from the place's
  table, and 0.
  - One player: `0x0031ba50`, 1, 8, 0x40, 0x200, 0x1000, 0x8000,
    0x40000 and 0x200000 for places 1 to 8.
  - Player one: `0x0031ba10`, each flag doubled.
  - Player two: `0x0031ba30`, each flag doubled again.

**LapFinishedSpeech** runs as a car completes lap `laps`. It says
nothing when WeDontWantToSayAnything holds, or when there is a lap
record. LapKnockoutSpeech answers 0. Otherwise one of the two builders
fills a DuringRaceSpeech of four flags, and event 160 is said with
TypeA only. TypeB, TypeC and TypeD are filled and dropped, as in retail
and the demo.

**The lap record** (LapRecordSpeech) is event 164 with no parameters.
It is said when all of these hold:

- the car's last lap time equals the race's BestLapTime;
- it is below the first of the track's best laps for the car's class
  and direction;
- that best is set: neither `0x7fffffff` nor 0.

Retail's delay slot zeroes the answer before it tests for 0, so a 0
best never speaks.

**OnePlayerLapSpeech:**

- After the second-to-last lap, TypeD is 1024.
- Otherwise, on a coin's toss or from lap 20, and only with AI cars,
  TypeD is the place:
  - first: 1 or 512 by a second coin;
  - eighth: 128 or 256 by a second coin;
  - second to seventh: `0x0031ba70`'s 2 to 0x40.
- Otherwise TypeA is "start lap n+1", from `0x0031ba88`: 2 up to
  0x80000 after laps 1 to 19, and 0 after lap 20.

**TwoPlayerLapSpeech:**

- **Without AI cars:** the lead is player one's CurrentLapNumberExact
  minus player two's, negated for player two's car. A coin picks the
  table said of either player; otherwise it is the car's own player's.
  TypeC is the table's entry for the first limit at or below the lead.
  The limits, `0x0031bad8`, are 0.5, 0.3, 0.2, 0.1, 0.05, 0.01, -0.1,
  -0.2 and -99999 laps. A NaN lead sets nothing.
- **With AI cars:** TypeB is the place, from a table picked the same
  way (`0x0031bb78`, `0x0031bb98` and `0x0031bbb8`).

**MaybeDoKnockoutRaceOverSpeech** runs once per player, from
FillInRaceOverMessages. It says event 169 with two flags:

- **A lap knockout, or fewer than three racing cars:** 0 when the
  player goes through, 1 when out, and then 0.
- **Otherwise:** 1, then 1 when through, 0 when out.

## After the race

**The records** (PostGameLapRecord, PostGameTimeRecord) come from the
Best Lap Times and Best Total Times screens. Neither speaks for a
busted row, nor in an event tree's race whose event status is not 4,
"placed". Each says event 166:

- **A record below the top** (`place` not 0): GetTopTimeFlag, 64, 128 or
  256 by the player.
- **The top lap:** 512, 1024 or 2048.
- **The top total:** a coin picks 1, 2 or 4, or else 8, 16 or 32.

**TournamentRaceSpeech** comes from the Tourney Standings:

- After a race: event 165 with the place from 0, from `0x0031bc18`
  (the one-player finish flags again), and 0.
- At the end: event 167 with 16384, said only for the winner (`n` 0).

**The event's result** (`0x00206bc8`) comes from the event results
screen (`0x001def38`):

- RaceEvent::GetStatus not 4 says event 168 with 64.
- If the won test at `0x00200c38` says the player has not won,
  nothing is said.
- Otherwise the event's number picks a flag.
  - Numbers 1 to 20 give eventType's A flag: the Hot Pursuit tree's
    table when Fred's GameType is 9, else the championship's.
  - Other numbers give the B flag, from 21.
- Neither flag gives event 168 with 1024.
- Otherwise the event is said with four flags: whether this is the
  player's first win (New2696, which it then sets), A, B, and whether
  the event's word is set.
  - The event is 216 for the Hot Pursuit tree, or whenever B is 2048.
  - It is 217 for the championship.

**The event's reward** (`0x00207450`) has three bytes. Nothing is said
without the won flag or a reward.

- A first byte of 0 makes the second a car type, for RewardCarSpeech.
- Any other first byte makes the second a track and the third its
  direction, for the track's reward.

**RewardCarSpeech** (`0x00207488`) answers 1 when it speaks. The flag is
ConvertRewardCarType's (0 below 0 and from 67) and the event goes by
the car's type:

- a cop car (UsageType 1): event 150;
- a high-performance car: event 149, but types 21 and 22, whose flag is
  128, say event 204 with 1 instead;
- any other car: event 147.

A flag of 0 says nothing.

**The track's reward** (`0x00207550`) is event 151 with the unlocked
track's flag and 2 for direction 1, 1 otherwise. A flag of 0 says
nothing. Tracks are numbered by tens; the second digit 4 to 6 repeats 1
to 3 (the reverse versions).

**PointsScreenSpeech** says event 210 for a finish bonus.

## The cops

**The pullover** (`0x002075d8`, from CreatePullover) says event 206
unless in a replay.

**Be A Cop's arrests** (`0x00207648`) say event 213 with
beCopFinishType, unless in a replay:

| players | missed | winner | arrests | flag |
|---|---|---|---|---|
| 2 | yes | | | 512 |
| 2 | no | 2 | | 0x8000 |
| 2 | no | other | | 0x20000 |
| other | no | | | 1024 |
| other | yes | | 0, 1, 2 | 2048, 4096, 8192 |
| other | yes | | other | 512 |

**PlayBustedSpeech** says event 214 with 1.

## The seams

main.c binds:

- playerhud.h's `gRaceFinishedSpeechFn`, `race_finished_speech`;
- raceupdate.h's `gLapFinishedSpeechFn`, `lap_finished_speech`;
- raceovermsg.h's `gMaybeDoKnockoutRaceOverSpeechFn`;
- endtimes.h's `gPostGameLapRecordFn` and `gPostGameTimeRecordFn`;
- endresults.h's `gRewardCarSpeechFn`, through a wrapper that drops the
  answer, and `gPointsScreenSpeechFn`;
- pullover.h's `gSpeechPulloverEventFn` and `gSpeechBeACopArrestFn`.

Still unbound:

- `gRaceEventUserWonFn` stays NULL until RaceEvent is ported. An event's
  win says nothing.
- `tournament_race_speech`, `race_event_speech` and
  `race_event_reward_speech` wait for their screens (RE-6).
- `play_busted_speech` and BeACopThink's arrest call wait for
  BeACopThink (12m).

## The check

`python tools/racespeech_check.py` runs retail's code on the MIPS model
and the port's on the host (`tools/src/racespeech_test.c`). Both run the
same script.

Logged stubs, answered by the same rule on both sides:

- bRandom, RaceEvent::GetStatus and the won test (each a queue, then an
  answer);
- SPCH_AddEventV;
- GetLastLapTime and GetBestLapTimesTable.

Memory both sides read: the race parameters, the race, the coordinator,
the cop manager, the players, the cars, the car types, Fred's game type
and the event. The harness prints all four DuringRaceSpeech flags of
each builder.

The script covers:

- each conversion over its range;
- WeDontWantToSayAnything's every test;
- every place of fields of 2 to 8, with one and two players and the
  last place's coin;
- the busted car;
- the lap record's times, including the empty time, 0 and negatives;
- every lap of races of 1 to 21 laps;
- the lead at each limit, one float either side, and NaN;
- the knockouts, the records, the tournament and the event numbers 1 to
  34 of each game type;
- every car type's reward by its usage, and every track;
- Be A Cop's arrests;
- 4000 random steps.

Result: 773239 ops, 90612 lines, 0 differ.

The check found one bug: the port spoke a lap record over a 0 best.

The mutation pass makes 516 mutations. Generated ones cover every
table entry, every limit nudged, and each case label of the two track
switches, its flag shifted or either of its tracks dropped. The rest are
hand-written; they cover every test, constant, argument, table choice
and return. 512 are caught and 4 are equivalent:

- The demos' range shortened to state 8: state 9 is already a replay.
- The event tables' bound: retail reads past them, so the script stays
  inside, where the bound is never met.
- ConvertRewardCarType's bound at 66: entry 66 is 0.
- ConvertRewardCarType's bound at -1: the word before the table is 0.

Azahar, from the frontend's Quick Race (seven AI cars, two laps), with a
test-only hook. It said lap 1 and lap 2, finished the player seventh
and logged each event (removed, rebuilt clean). The events and the
library's answer:

- lap 1: event 160 with 0 (the last lap's TypeD);
- lap 2: event 160 with 4;
- the finish: event 165 with 0x40000 (seventh) and 0.

The library took all three. Race Results and Best Lap Times followed.
SkipFE's race has one car, so it rightly says nothing.
