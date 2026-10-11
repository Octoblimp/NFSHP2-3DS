# race-event -- the event being raced

When the player starts one of the career's events
([event-tree](event-tree.md)), or a challenge knockout, the event is
copied into one global, `TheRaceEvent` (`0x0031b600`), and pointed at its
state in Fred. The race reads the event's type and counts, records each
racer's finish into it, and the end of the race posts the results into the
state, judges the state against the event's objective, and asks whether a
knockout or a tournament has another race.

Retail has this in RaceEvent.obj: `0x00200ac8` .. `0x00200c38`,
`0x00200e30`, `0x00201478` and `0x002014e8` .. `0x002026f0`. The port has
it in `raceevent.{c,h}`, its functions prefixed `raceevent_`.
`tools/raceevent_check.py` runs retail's code against the port.

## The record

RaceEvent is 432 bytes in retail; the demo's was 376, without
`aSavedState` and the word at 120. It is zeroed BSS with no constructor.

| offset | field | what |
|---|---|---|
| 0 | `pTree` | the event's tree |
| 4 | `pState` | the event's state in Fred |
| 8 | `aOldState[16]` | the state before the race |
| 24 | `aSavedState[16]` | the state when the race left the grid |
| 40 | `sName[32]` | |
| 72 | `sRewardName[32]` | |
| 104 | `nNumber` | the event's number, 1 .. 32 |
| 106 | `nType` | eEventType |
| 108 | `nClass`, `nCars`, `nTracks`, `nRewards`, `nOpponents` | int16 each |
| 118 | `nInitialPlayers` | the players at the event's start |
| 120 | `bIsLastOpen` | StartRace's: the one event left (`0x00200f98`) |
| 124 | `Objective` | an EventGoal |
| 132 | `aCars[20]` | 4 bytes each |
| 212 | `aTracks[8]` | EventTrack, 4 bytes, which `EventTrack::SetRace` (`0x001fec20`) puts into TheRaceParameters |
| 244 | `aRewards[8]` | EventReward, 8 bytes |
| 308 | `aOpponents[7]` | 4 bytes each |
| 336 | `aResults[8]` | EventResult, 12 bytes: the place (1 .. 8, 0 none), the time, the finish reason |

## The types

Every one of RaceEvent's jump tables puts the event types into four
groups, and the state's kind follows the group (the sizes are
`0x00200e30`'s):

| group | types | state | size |
|---|---|---|---|
| rank | race (0), lap knockout (2) | EventRankState | 1 |
| time | time trial (1), point to point (5), Be A Cop (6) | EventTimeState | 4 |
| knockout | race knockout (3) | EventKoState | 16 |
| tournament | tournament (4) | EventTournamentState | 16 |

Types 7 and up take each table's default: a state of 1 byte, status
untried, nothing posted, no reward and no win. `GetRankState`,
`GetTournamentState`, `GetKoState` and `GetTimeState` (`0x00201858` ..
`0x002018c0`) answer `pState` for their group and NULL for the others.
`IsMultiTrack` (`0x00201478`) is the knockout and the tournament.

## The racers

A result is kept by racer index. The players are driver numbers 0 and 1,
the AI 100 on, and `RacerIndexFromDriverNumber` (`0x00201558`) puts the AI
after the event's first players: index `n` for a player, `nInitialPlayers
+ n - 100` for the AI. `DriverNumberFromRacerIndex` (`0x00201578`) is the
inverse. A racer is in the race (`0x00201668`, `0x00201698`) when
TheRaceParameters has the driver and the driver has no `EliminatedRank`.
It is eliminated (`0x002016d0`, `0x00201708`) in a race knockout race
(RaceType 4) when the knockout state gives it a rank.

`GetLastPlace` (`0x00201738`) and `GetFirstPlace` (`0x002017c8`) answer the
racer still in with the highest, or the lowest, place; 0 when there is
none.

## A race

- **The grid.** StartRace resets the state unless the event is in progress
  (`ResetState`, `0x00202698`), sets the race's track by the race index
  over the track count, and for a knockout's later races takes the players'
  starting positions from the knockout state (`0x00200598`). A tournament
  in progress starts the player at its rank in points (`UserRank`,
  `0x00200768`). SetupCarsForRace takes each knocked-out driver out at its
  rank (`GetRank`, `0x00200220`, read from `pState` itself, not through
  GetKoState).
- **The start.** When the race leaves the grid (Race stage RACING),
  `FrontendDatabase::TheRaceIsLeaving` (`0x00187570`) calls
  `MaybeDiscardResults` (`0x00201a80`), which copies the state into
  `aSavedState`.
- **Each finish.** `RecordResults` (`0x00201598`), from `Race::FinishCar`
  and `NotifyTheRaceIsOver` for every car, writes the racer's place, its
  time and its finish reason. The time is the car's best lap
  (`0x00147588`) in a time trial (RaceType 2) and its race time otherwise;
  in Be A Cop it is the cop manager's `fBeACopTime` (`SetTime`,
  `0x00136dd0`).
- **The end.** `PostResults` (`0x002018f8`), from TheRaceIsOver and
  TheRaceWasQuit, does nothing when the race was aborted. Otherwise a rank
  state takes the player's place, a time state its time, and a knockout
  state the last place's rank (and the first place's too when the field is
  under three), then every racer's place as its next start position. A
  tournament state adds each placed racer's points (10, 6, 4, 3, 2, 1, 0,
  0, gp-16648).
- **A restart.** `CycleResults` (`0x00201ac0`), from TheRaceWasRestarted,
  copies the state into `aOldState`, unless a knockout or tournament has
  another race, and then puts `aSavedState` back: the race is run again
  from where it started.

## The status

`GetStatus` (`0x00202658`) judges the state against the objective, and
`GetOldStatus` (`0x00202678`) judges `aOldState`. Both go through
`0x00202528`, which takes any state; `0x002025c8` takes a goal instead.
The answers are eventtree.c's: untried (1), in progress (2), failed (3) or
passed (4).

The End Game Menu compares the two:

- `StatusAdvanced` (`0x00201db8`): the status went up, or stayed and the
  result got better. A rank or time counts as better when it is set and
  the old one was not, or when it is lower. A knockout compares the
  player's rank (only for an event tree's race); a tournament the player's
  rank in points, once the event is past in progress.
- `StatusFell` (`0x00201bd8`): the status went down (but not from failed),
  or stayed and the result got worse, by the same rules.
- `KeepState` (`0x00201fb0`): when the status fell, `aOldState` goes back
  into the state. The menu's Quit and Restart Race call it, and so does
  TheRaceWasQuit.
- `Restart` (`0x00201b38`), the menu's Restart Event: the state into
  `aOldState` unless there is another race or the status fell, then the
  state and the results reset, every driver back in, the grid recalculated
  and the event's first track set.

## Several races

`GetRaceIndex` (`0x00202010`) and `GetRaceCount` (`0x00202088`) are a
knockout's races so far and its `nOpponents`, or a tournament's races so far
and its `nTracks`; other events answer 0 and 1.

`IsThereAnotherRace` (`0x00202420`): a knockout counts the players still in
(over Fred's `NumPlayerCars`), less one when the last place is a player,
and has another race while that is over 0 and the field is at least three.
A tournament has one while the next race index is within the count.

`SetupNextRace` (`0x002020b8`), from `FrontendDatabase::SetupNextRace`
(`0x00184270`) on RCSTATE NEXT_RACE, copies player one's 48 bytes of
`mPlayerSettings` into TheRaceParameters. A knockout then knocks out its
last place at that place; both kinds recalculate the grid and set the next
track.

`CalcStartingPositions` (`0x002022c0`), which
`FrontendDatabase::CalculateStartingPositions` calls first, does nothing on
an event's first race. After that a knockout starts each racer still in at
its place in the last race, and a tournament at its rank in points.

## The rewards

`RewardEarned` (`0x00200b30`) takes a reward and a state (NULL is the
event's own): 0 below failed, and otherwise the result against the
reward's `nData`, as eventtree.c judges an EventInfo's.
`AnyRewardEarned` (`0x00200ac8`) asks it of every reward. The End Game
Menu tests each reward against `aOldState`, to find one the race has just
earned; the Challenge Mode count asks it with the event's state for each
reward of type 0, a car.

`UserWon` (`0x00200c38`), the race speech's: at failed or above, a rank,
knockout or tournament event is won in first place, and a time event when
the time beats every reward's `nData`.

## Where the port is wired

main.c binds each seam to a wrapper on TheRaceEvent:

- `fredrace.h`: GetStatus, ResetState, GetRaceIndex, KoStartPosition,
  TournamentUserRank, DriverEliminated, EliminatedRank,
  StartingPositions and IsThereAnotherRace.
- `fredend.h`: PostResults, MaybeDiscardResults (`raceevent_save_state`)
  and CycleResults.
- `endgame.h`: RewardTest (`aOldState`), StatusAdvanced, StatusFell,
  KeepState and Restart.
- `endresults.h`: RewardType (the reward's first byte) and RewardEarned.
- `racespeech.h`: UserWon. `racefinish.h`: RecordResults.
- `startrace.h`: GetRaceCount and GetTournamentState.
- `rcstates.h`: `gFEDSetupNextRaceFn`, SetupNextRace when Fred uses the
  race event (GameType 4, 8 or 9).

Every call but RecordResults sits behind `UseTheRaceEvent` or an event
type. Until RE-6c copies an event in (`EventTree::SetRace`, the fake
challenge knockout, `gEventTrackSetRaceOnFn`), TheRaceEvent stays zeroed
and its state NULL. The events the race opened (`0x001f7458`) and the
tree's event word are RE-6c's too.

## Where the port differs

None of it is visible to the game.

- **The pointers.** `pTree` and `pState` are native pointers, so the
  layout check holds on the 3DS only.
- **A NULL state.** Retail reads the bottom of memory, zeros in the image;
  the port reads 16 zero bytes. Retail also writes through it (ResetState,
  PostResults, CycleResults, KeepState); the port does not write. The
  seams that read the knockout or tournament state answer 0 for NULL.
- **A result past the eight.** Retail writes a racer index outside 0 .. 7
  into the next object (`0x0031b7b0`); the port drops it.
- **The tracks.** Retail traps on its divide when the event has no tracks,
  and reads past `aTracks` for an index outside it; the port sets no
  track.
- **The rewards.** Retail reads any reward under `nRewards`, past the
  array's eight when the count runs over; the port stops at the end.
- **Be A Cop.** Retail reads `fBeACopTime` through a NULL cop manager; the
  port's time is 0.
- **A tournament's points.** Retail reads past the points table for a
  place over 8, which no race gives.

## The check

`tools/raceevent_check.py` runs every type (and two past the tables), the
racer indexes, the results, the places, knockout and tournament flows
from their first race to their last, the statuses, another race, the
rewards and 900 random runs through both sides: 84260 ops, 59927 lines,
0 differ. Of 170 mutations, 158 are caught and 12 are equivalent by
construction, each with its reason in the script.
