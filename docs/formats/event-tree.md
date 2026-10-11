# event-tree -- the career's events and what they unlock

The career is two event trees, Championship and Hot Pursuit, of 32 events
each. An event needs a goal of another event passed before it opens, and
its rewards are cars and tracks. The trees decide which of those are
locked: Quick Race's track pick, the Select Car screen's padlocks and the
unlock blurbs all ask them.

Retail has this in EventTree.obj (`0x001fd130` .. `0x00202cfc`). The port
has it in `eventtree.{c,h}`, without the 3D tree the frontend draws
(BuildTree, the leaves, Update and Render, the view's neighbours), which
goes with the tree's screen. `tools/eventtree_check.py` runs retail's
code against the port.

## The chunk

FRONTB.BUN holds one EventTree chunk (`0x80034a00`) per tree. Its
children:

| id | what | record |
|---|---|---|
| `1` | the name, "Championship" or "Hot Pursuit" | |
| `0x34a01` | the cars an event can give the player | 4 bytes |
| `0x34a02` | the tracks | 4 bytes |
| `0x34a03` | the goals, EventGoal | 8 bytes |
| `0x34a04` | the rewards, EventReward | 8 bytes |
| `0x34a05` | the events, EventInfo | 188 bytes |
| `0x34a06` | the opponents | 4 bytes |

The tree points into the chunk; nothing is copied. On the disc:

| tree | events | cars | tracks | goals | rewards (car, track) | opponents |
|---|---|---|---|---|---|---|
| Championship | 32 | 25 | 68 | 33 | 21 (8, 13) | 132 |
| Hot Pursuit | 32 | 30 | 56 | 38 | 21 (11, 10) | 59 |

An event's arrays (`aCars`, `aTracks`, `aGoals`, `aRewards`,
`aOpponents`) index the tree's tables. Only the first n of each are set;
the rest is the tool's garbage. A count can run past its array into the
next one, and retail's reads do, so the port's do too.

**EventGoal** (8 bytes): `nType` (1 rank, 2 time, 3 points), `nEvent`,
the event in the same tree whose result it needs, and `nData`, the result.

**EventReward** (8 bytes; the demo's 4 had no `nData`): `nType` 0 is a car
(`nValue1` the car type), 1 a track (`nValue1` the track, `nValue2` its
direction). `nData` is the result that earns it: the place, the time, or
the points rank.

**EventInfo** (188 bytes) is in `eventtree.h` with its offsets. Retail's
first two words are pointers, `pTree` and `pState`, which the loader
fills in (see the port's differences below). `nObjective` is a goal of the
tree, the one the event's own result is judged against. The title and
description strings are 70000 + n and 70064 + n.

## The state

An event's progress is a few bytes of Fred: `ChampionshipState` and
`HotPursuitState`, 256 bytes each. `CalcStatePointers` (`0x001fe988`)
deals them out: first the events whose state is at least the alignment (4)
bytes, each rounded up to it, then the rest packed. The 32nd event, the
Ultimate, is shared. The first tree to deal sets `Fred.pUltimateState`,
and the second points its Ultimate at the same bytes.

The state's kind is the event's type:

| type | state | size | holds |
|---|---|---|---|
| race (0), lap knockout (2) | EventRankState | 1 | the place, 0 untried |
| time trial (1), point to point (5), Be A Cop (6) | EventTimeState | 4 | the time, 0 or `0x7fffffff` untried |
| race knockout (3) | EventKoState | 16 | eight 4-bit places once out, eight 4-bit start positions, the car (int16), skin, dash, a seed |
| tournament (4) | EventTournamentState | 16 | eight drivers' points, the car, skin, dash, a seed |

Retail's knockout and tournament states are 16 bytes; the demo's were 8
and 12. A tournament gives 10, 6, 4, 3, 2, 1, 0, 0 points (gp-16648).
Unlocking a state writes a passing result: place 1, a time of
`(int)4000.5f`, a knockout's places 1 .. n in grid order, or a
tournament's points with driver i placed i + 1 in every race.

## The status

`GetStatus` (`0x002010b8`) answers locked (0), untried (1), in progress
(2), failed (3) or passed (4). With a goal, it judges the event's state
against that goal. With none, the event is first checked for being open:

- the Ultimate is locked until every event 1 .. 31 of both trees is
  passed;
- any other event with goals is locked until one of them is passed
  (`EventGoal::Passed`, `0x001fffb0`: the goal's event passes against the
  goal);

and then judged against its objective. `UnlockAllEvents` (gp-16720) makes
everything passed; nothing sets it. Egg 6 opens the Championship's 31st
event and egg 7 Hot Pursuit's: where its goals would leave it locked, it
is untried.

A rank passes at or under the goal's place (unsigned), a time at or under
the goal's time (signed). A knockout is untried before any driver has a
place, and in progress until the player (driver 0) has one; that place is
then judged. A tournament is in progress until the races so far (the
points against what a race gives the field) reach its count of tracks, and
then the player's rank in points is judged.

`IsLastOpen` (`0x00200f98`) is 1 when this is the one event left: every
other event 1 .. 31 of both trees is passed, Hot Pursuit's Ultimate is
still locked, and this one is not passed. StartRace asks it.

## The rewards

`RewardEarned` (`0x002009d0`) is 0 while the event is below failed, and
otherwise the result against the reward's `nData`. Over one tree:

- `IsCarUnlocked` (`0x001ff360`): the first reward that is the car is
  earned; 0 when no reward is the car;
- `IsTrackUnlocked` (`0x001ff5c8`): the same for a track and direction,
  but 1 when no reward is it;
- `CarIsAReward`, `TrackIsAReward` and the `FindEvent...` pair: is it, and
  whose.

Over every tree, in the loader's order (`bList` at gp-16712):
`IsCarAnEventReward` (`0x001ff8b8`), `EventTreeIsCarUnlocked`
(`0x001ff918`), `FindEventThatCarIsARewardFor` (`0x001ff9d8`),
`IsTrackAnEventReward` (`0x001ffaa8`) and `EventTreeIsTrackUnlocked`
(`0x001ffb18`). The first tree that has the car or track decides; a track
no tree has is unlocked. `0x001ff978` counts the cars 0 .. 63 that are a
reward and earned. `LockEvents` and `UnlockEvents` reset, or pass, every
tree.

## The loader

`LoaderEventTree` (`0x001ffc40`) links a new tree at the end of the list
and walks the chunk's children. The name goes through `SetName`
(`0x001fdef8`), which makes "Hot Pursuit" type 1 and `gHotPursuitTree`
(gp-16696), "Championship" type 0 and `gChampionshipTree` (gp-16700),
each "... E3" under `bVersionE3`. The events' child sets the events, each
pointed back at the tree, and deals the tree's state out of Fred.
`UnloaderEventTree` (`0x001ffe80`) clears the two trees' words and
gp-16704, which nothing reads, and deletes every tree.

The loader is slot 24 of the retail chunk loader table
([loader-table](loader-table.md)).

## Where the port is wired

- `quickrace.c`'s `is_track_unlocked` asks `is_track_an_event_reward` and
  `event_tree_is_track_unlocked_any` ([quick-race](quick-race.md)).
- `fredend.c`'s car status asks `is_car_an_event_reward` and
  `event_tree_is_car_unlocked_any`.
- main.c's unlock blurb asks `find_event_that_car_is_a_reward_for` for the
  event's tree and number.
- `fredrace.c`'s StartRace puts `event_trees_num_cars_unlocked` into
  RaceParameters' New784.
- main.c logs the trees after FRONTB's load: "frontres: FRONTB loaded; 2
  event trees, 0 reward cars earned" on a new save.

RaceEvent, the races an event sets and the tree's screens come after
(RE-6b .. RE-6d).

## Where the port differs

None of it is visible to the game.

- **The pointers.** An EventInfo is the chunk's own 188-byte record, so
  on a 64-bit host its first two words cannot hold pointers. The port
  keeps a handle for the tree (its slot in a table of eight, plus 1) and
  the state's offset from `&Fred`; 0 is NULL in both.
  `Fred.pUltimateState` holds the same offset.
- **The constructor.** Retail stores a vector whose fourth word is
  whatever was on its stack into `vCenter`, and leaves the opponents'
  table and the words at 116 .. 127 as the heap had them. The port clears
  the record first, so all of them are 0.
- **A bad name.** A tree whose name is neither tree's is deleted by
  retail's loader, which then carries on writing the chunk's later
  children into the freed tree. The port stops filling it. The disc's two
  names are both known.
- **The finish string.** Retail indexes its table of place strings
  (`0x002baed8`) with any place. The places are 1 .. 8 and a knockout's at
  most 15; past the table's 16 the port gives "". The buffer
  (`0x003342f0`) is 64 bytes, and the port never writes past it.
- **A tournament.** Retail traps on its divide when the count of
  opponents makes the field's points 0; the port answers 0. The points
  past eighth place are other data in retail, zeros in the image, and 0
  in the port; nothing reads that far.
- **No tree.** `GetEventNumber` on a NULL tree reads its count from the
  bottom of memory in retail; the port finds nothing. A tree without a
  name compares with the bottom of memory in retail, a 0 in the image, so
  the port's is "".

## The check

`tools/eventtree_check.py` runs the disc's two trees and ten made-up
ones (every event type, empty and overfull tables, garbage counts) through
both sides: 22401 ops, 28129 lines, 0 differ. Of 264 mutations, 255 are
caught and 9 are equivalent by construction, each with its reason in the
script.
