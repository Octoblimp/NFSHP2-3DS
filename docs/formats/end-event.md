# end-event -- the career's end-game screens

The screens in the end-game list ([end-game](end-game.md)) that come from
the career's events and Be A Cop. They are Tourney Standings after a
tournament's race, the Reward menu (the event passed or failed, and what
it earned), Events Unlocked (the events the race opened), and the two
You're The Cop results.

Retail has these in EndGameScreens.obj: the constructors at `0x001dd5d0`,
`0x001def38`, `0x001df180`, `0x001e0898` and `0x001e0a10`, the Reward
menu's helpers at `0x001de788`, `0x001dea88` and `0x001dead8`, and the
destructors at `0x001e2340` .. `0x001e2510`. The port has them in
`endevent.{c,h}`. `tools/endevent_check.py` runs retail's code against
the port.

Each class is 8 bytes: an EndGameMenusBase (the screen's hash and the
vtable). Each vtable keeps the base's HandleEvent and adds only its own
destructor. BeTheCopResults2P also has its own Render (`0x001e0bc8`),
which is empty like the base's.

| class | vtable | the list's class |
|---|---|---|
| TourneyStandingsScreen | `0x002b9028` | `END_GAME_CLASS_TOURNEY_STANDINGS` |
| EventRewardScreen | `0x002b9088` | `END_GAME_CLASS_REWARD_MENU` |
| EventsUnlockedScreen | `0x002b90b8` | `END_GAME_CLASS_EVENTS_UNLOCKED` |
| BeTheCopResults1P | `0x002b8f98` | `END_GAME_CLASS_BTC_RESULTS_1P` |
| BeTheCopResults2P | `0x002b8f68` | `END_GAME_CLASS_BTC_RESULTS_2P` |

Three of the screens say their speech once per list. Each one has a flag
in the screens' list (EndGameScreens, `pEndGameScreens`, gp-17628):

| word | flag |
|---|---|
| +32 (`Zeroed[2]`) | Events Unlocked's |
| +36 (`Zeroed[3]`) | the Reward menu's |
| +48 (`Zeroed[6]`) | Tourney Standings' |

## Tourney Standings

The constructor first sets the track's name and the race's number, as
Race Results does (`0x001dc5d8`). Unless Fred uses the race event
(`UseTheRaceEvent`, GameType 4, 8 or 9) and TheRaceEvent is a
tournament (type 4), that is all it does.

Otherwise it gives each of `pCurrentRace`'s racing cars a
`TourneyPoints` (20 bytes, `bMalloc(20, "TourneyPoints", 0, 16)`):

| offset | what |
|---|---|
| 0 | the bNode |
| 8 | the racing car |
| 12 | its points: the state's byte at the car's racer index |
| 16 | its rank: `RacerRank` (`0x00200710`) at that index |

The racer index is `RacerIndexFromDriverNumber` on the car's
DriverNumber. The list is sorted by bList::Sort (`0x00250550`), a bubble
sort that swaps every pair the test (`0x001dd5c0`) does not call in
order. The test is `a.rank < b.rank`, so two cars on one rank swap for
ever and the sort never ends. RacerRank breaks ties by the index, so in a
race only two cars on one racer index can tie.

Row k (1 .. 8) has the objects `POS_k`, `NAME_k`, `TYPE_k`, `RACE_k` and
`TOTAL_k`, by SprintfAndHash. In the list's order, each car's row is:

| object | text |
|---|---|
| POS | `%2d`, k |
| NAME | a player driver's: the PlayerName of the player in the world's car with that UniqueDriverNumber (`GetCarByDriverNumber`); the AI's: DriverInfo::GetName |
| TYPE | the ride's car type, CarTypeInfo::GetShortName, translated by name |
| RACE | `GetPointsForFinishPos(place - 1)` for the place in TheRaceEvent's results at the racer index, or "DNF" with no place |
| TOTAL | the points |

A row past `NumRacingCars` would be hidden. The rows left after the list
are hidden too. A car with a player (`RacingCar::GetPlayer`) gets that
player's colour (`PlayerTextColors[PlayerNumber]`); any other car is
`DefaultTextColor`. Retail indexes the colours unchecked, so player
number 2 reads the next table, which is DefaultTextColor. The first car
with a player says the tournament speech (`0x002073f0`) if the flag is
0: whether the event is over (status FAILED or PASSED) and the row
number. Then the flag is set to 1, whether or not the speech was said.
The nodes are bFree'd at the end (the bTList's destructor, `0x001e21f8`).

## The Reward menu

The constructor reads `AnyRewardEarned`. If the flag is 0, it says the
speech, and then it sets the flag. The speech is the event's
(`0x00206bc8`, the player by number 0, the first driver's row) when the
event is not passed, is the Ultimate (32), or is a bonus event (31) that
was not the last open. Otherwise it is the reward's (`0x00207450`): the
player, whether one was earned, and the first reward, or NULL without
rewards.

The blurb (`0x001dead8`) is rendered into END_REWARD_GROUP_BLURB. The
title, `EVENT %d PASSED` (`0xde4a4`) or `EVENT %d FAILED` (`0xde4a5`), is
printed with the event's number. For a first reward that is a car, when
the status advanced and the reward is earned (against no old state), the
count of cars unlocked is shown (`0x001de4a0`, not the cop's). Otherwise
it is cleared (`0x001de550`).

### The blurb's id (`0x001de788`)

| test, in order | id |
|---|---|
| event 30 passed | the tree's: Championship `0xe30d5`, Ultimate Road Racer `0xe30d6`, else 0 |
| event 32 passed | `0xe32c4` |
| event 31 passed | the tree's: `0xe32c5`, `0xe32c6`, else 0 |
| a time trial, timed, not Be A Cop | failed `0xe09c0`; earned `0xe09c1`; else `0xe09c6` |
| point to point, timed, not Be A Cop, not a time trial | failed `0xe09c2`; earned `0xe09c3`; else `0xe09c7` |
| Be A Cop | passed `0xe09c4`, else `0xe09c5` |
| failed | `0xe30d3` |
| by the player's place, earned or not | 1st `0xe30d0`/`0xe30da`, 2nd `0xe30d1`/`0xe30db`, 3rd `0xe30d2`/`0xe30dc`, else `0xe30d4`/`0xe30dd` |

"Timed" is a TimeTrialTime that is neither 0 nor `0x7fffffff`. "Passed"
is status 4 and "earned" is AnyRewardEarned.

The player's place (`0x001dea88`) takes a driver number in a1. Every
call passes 0. A tournament gives its UserRank. Anything else gives the
driver's TransientStats row's FinishPosition.

### The blurb (`0x001dead8`)

Every text is made whatever the id. These are the first driver's best lap
and total time (`0x001dc500`), and the time to beat (an objective of type
2, else empty). They are also the place and the place needed (an
objective of type 1, else 0), each as the name `0xee48 + n` ("0th" ..
"8th", then a 0 at `0x002b9178`). The last is the first reward's name,
read whatever `nRewards` says. A car is its short name. A track is the
track's name in its direction and "track" (`0xe09bf`). The id's format
takes:

| ids | arguments |
|---|---|
| `0xe09c0`, `0xe09c2` | the lap or total, the time to beat |
| `0xe09c1`, `0xe09c3` | the lap or total, the reward |
| `0xe09c4`, `0xe30d0` .. `0xe30d2`, `0xe30d4` | the reward |
| `0xe09c6`, `0xe09c7` | the lap or total |
| `0xe30d3` | the place, the place needed |
| any other | none |

## Events Unlocked

The constructor asks GetStatus and drops the answer. Then it lists the
events the race opened ([fred-event](fred-event.md), `0x001f7398` with 8)
and takes a blurb by the count (3 for more) and the tree:

| count | Championship | Ultimate Road Racer |
|---|---|---|
| 1 | `0xde2b0` | `0xde2b2` |
| 2 | `0xde2b4` | `0xde2b5` |
| 3 | `0xde2b1` | `0xde2b3` |

Any other GameType has blurb 0 and keeps the count as it is. The switch
on the count has no breaks. One event formats the blurb three times and
two events twice, each over the last with the same format, the event
numbers as its arguments. With no event, or four or more outside a
tree, nothing is formatted and the buffer is shown unwritten. The title
is "EVENTS UNLOCKED" (`0xde2b6`). If the flag is 0, the event speech is
said (the player by index 0, the first driver's row) and the flag is set.
The car count is cleared.

## You're The Cop

Both set the track's name (GetTheRightTrackLanguageID on
CurrentTrackInfo and the race's direction).

1P, on the first driver's row: when it finished WON (4), the time bonus
group is shown. It has the seconds left (BeACopTime cut to a whole number
by cvt.w.s) and their bonus, 100 a second. Otherwise the group is hidden
and the bonus is 0. Then come the race's points, the points plus the
bonus, and the career's total.

2P, on the first two drivers' rows (the cop, the speeder):

| first | second | blurbs |
|---|---|---|
| WON (4) | LOST (5) | `0xecd1c`, `0xecd1f` |
| LOST | COMPLETED (1) or WON | `0xecd1d`, `0xecd1e` |
| LOST | LOST | `0xecd25`, `0xecd26` |
| any other pair | | unchanged |

Then each side's race points.

## Where the port differs

- **Ties.** The sort's test is `<=`, so cars on one rank keep the list's
  order and the sort ends.
- **NULL reads.** Retail reads through a NULL world car or player for a
  player's name; the port's name is "". A NULL racing car or car is left
  off the list. A car without a driver or a ride is shown but not written.
- **Indexes.** A racer index past the state's 16 bytes has no points and
  rank 0. One past the eight results has no place. A place outside 0 .. 9
  has name 0. A player number outside 0 and 1 is DefaultTextColor.
- **Buffers.** The blurb's texts are cut to their buffers (16 bytes, the
  reward's 128), where retail writes past them. A reward that is neither
  a car nor a track is empty, and so is Events Unlocked's unwritten
  buffer.
- **No list.** With no `pEndGameScreens` the screens say no speech;
  retail reads it unchecked.
- **The place's driver.** `event_reward_user_rank` takes the driver as
  retail's does.

## Wiring

`main.c` puts the five constructors in `gEndGameScreenCtorFns`. Be A
Cop's results come up after its races. The event screens need GameType 4,
8 or 9, which the event tree's screen (step 16) will start.
