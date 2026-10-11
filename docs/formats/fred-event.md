# fred-event -- FrontendDatabase's event calls

The frontend's side of the career's events: which tree a game type races,
the event the select screen chose, the cars an event offers, the car a
knockout or a tournament keeps from race to race, the challenge
knockout's event made on the spot, StartRace's event word, the event's
opponents, and the list of the events a race opened.

Retail has this in FrontendDatabase.obj (`0x00183d80` .. `0x00184bd0`,
`0x00185568`), FrontendPlayerInfo's FlushAvailableCars (`0x00187928`),
DataEventSelectScreen's three (`0x001f5d00` .. `0x001f5d50`) and the
list's four (`0x001f72a8` .. `0x001f7458`). The port has it in
`fredevent.{c,h}`. `tools/fredevent_check.py` runs retail's code against
the port.

## The tree

`GetEventTree` (`0x00185568`) answers by Fred's GameType: 8, the World
Championship, races "Championship"; 9, Ultimate Road Racer, races "Hot
Pursuit". Under `bVersionE3` (gp-23224) the names are "Championship E3"
and "Hot Pursuit E3". Any other game has no tree. The lookup is
EventTree.obj's `get_event_tree` by name ([event-tree](event-tree.md)).

## The select screen's choice

Fred's `SelectedEventData` (+356, four words):

| word | what |
|---|---|
| 0 | the tree type the mode select set: 0 Cops Off, 1 Cops On (`SetTreeType`, `0x001f5d50`) |
| 1 | the event chosen in a tree of type 1 |
| 2 | the event chosen in a tree of type 0 |
| 3 | unused |

`GetSelectedEvent(type)` (`0x001f5d00`) gives word 2 for type 0, word 1
for type 1, and 1 for any other. `SetSelectedEvent(type, n)`
(`0x001f5d28`) goes by word 0, not by its `type`: n goes to word 2 when
word 0 is 0, to word 1 when it is 1, and nowhere otherwise.

## The cars

`FlushAvailableCars` (`0x00187928`) hides all 64 of a player's cars
(`CarStatus.nStatus` 0); the skins and the dash stay.

`MakeEventCarsAvailable(tree, event)` (`0x00183d80`, tTreeDetails') flushes
both players, then offers each of the event's cars to both
(`SetCarAvailability`, `0x001878e0`, status 1). The event's `aCars` are
int16 indexes into the tree's car table, whose records are 4 bytes:

| byte | bits | what |
|---|---|---|
| 2 | all | the car type |
| 3 | 0 .. 3 | the skin; 0 offers every skin (-1) |
| 3 | 6 | the dash |

Bytes 0 and 1 are not read. A record at address 0 (no table and index 0)
is skipped, and so is a car whose `&CarTypeInfoArray[type]` is NULL.

`MaybeSetSelectedCarForMultiTrackEvent` (`0x00184318`), StartRace's, runs
only for an event tree's race (`UseTreeEvent`, GameType 8 or 9): the first
player's ride (`GetSelectedRideInfo`, `0x00187af8`) is kept as the
selected event's car (`EventInfo::SetSelectedCar`, the type, the skin and
whether it has a dash), which a knockout or a tournament keeps in its
state.

`ContinueMultiTrackEvent` (`0x001843e8`), tTreeDetails' Continue, gives
the first player the selected event's car back (`GetSelectedCar`, then
`AssignCarOfType`, `0x00187a68`, with the game type) and starts the race
(`StartRace`, `0x00184f68`). Outside an event tree it does nothing.

## The challenge knockout

A challenge knockout (GameType 4) has no tree. StartRace calls
`SetupFakeRaceEventForChallengeKnockout` (`0x001849f0`), which makes
TheRaceEvent ([race-event](race-event.md)) a knockout of its own:

| field | value |
|---|---|
| `pState` | its own `aOldState`, reset as a knockout's (`EventKoState::Reset`) |
| `sName` | "Challenge Race Knockout" |
| `nType` | 3, a race knockout |
| `nInitialPlayers` | Fred's NumPlayerCars |
| `nOpponents`, `nTracks` | the AI cars and the players, less one, as an int16 |
| `nNumber`, `nClass`, `nCars`, `nRewards` | 0 |
| the objective | type 1 (a place), 3 or better, event 0 |

Then the tracks, by the Race Knockout setup's word 5 (Fred +116): 0 picks
them at random, 1 gives every race the race's own track
(`EventTrack::SetFromRace`'s code, inline), anything else leaves them.
Last, `ResetResults`.

`PickRandomTracksForChallengeKnockout` (`0x001846a0`) lists every track 0
.. HighestTrackNumber (gp-21944) that GetTrackInfo has, each direction
whose twin (`SameAsTrackNumber`) IsTrackUnlocked (`0x0024b760`) allows,
as bMalloc'd `tRandomlyPickableTrackInfo` nodes. `RandomizeList`
(`0x00184578`) swaps each place in turn with the one `bRandom(n)` picks.
The race's own track and direction then go to the front, taken from the
list or added there (GetTrackInfo's for its number). The knockout's races
take the list in order, each word written as SetFromRace writes one
([event-race](event-race.md)) but with the track's own time of day and
laps:

| bits | from |
|---|---|
| 0 .. 7 | the track's TrackNumber |
| 9 | the picked direction |
| 10 .. 11 | the race's weather |
| 12 .. 13 | the track's TimeOfDay |
| 14 .. 17 | the laps: 1 for a point to point, else 2 |
| 18 .. 24 | the race's TrafficDensity times 100, truncated, 7 bits |
| 25 .. 31 | the race's TrafficOncoming times 100, truncated |

Bit 8 keeps what the word had.

## The race's

StartRace's event word (`0x001850e0`, TheRaceEvent `bIsLastOpen`): when
Fred uses the race event and has a tree, `IsLastOpen` (`0x00200f98`) on
the tree's event numbered Fred's `nCurrentEvent`. It is 1 only when every
other event of 1 .. 31 in both trees is passed, Hot Pursuit's Ultimate is
locked and this one is not passed.

SetupCarsForRace's opponent `i` (`0x00185a1c`), for a race whose
`OpponentSelect` is 2: the record of the tree's opponent table that the
current event's `aOpponents[i]` indexes, 4 bytes (the car type, the skin,
the skill; [race-start](race-start.md)).

## The events opened

After TheRaceEvent, at `0x0031b7b0`, is the list of the events this race
can open: up to four, each the goal of a tree's event (`EventGoal`, 8
bytes) and the number of the event it opens (32 the Ultimate), then the
count (52 bytes). tTreeDetails::StartEvent (`0x001f7480`) fills it from
the tree view's children before the race.

| function | what |
|---|---|
| `0x001f72a8` | the count 0 |
| `0x001f72b0` | a goal and a number added while there are fewer than four |
| `0x001f7398` | the numbers of the events whose goal TheRaceEvent's state now passes (`RaceEvent::GetStatus` against the goal, `0x002025c8`), and how many; its `max` is not read |
| `0x001f7458` | how many, ShouldSeeRewardScreen's ([end-game](end-game.md)) |

## Wiring

`main.c` binds fredrace.h's seams to these:
`gSetupFakeRaceEventForChallengeKnockoutFn`, `gFredEventWordFn`,
`gFredEventOpponentFn` and `gFredMaybeSetSelectedCarForMultiTrackEventFn`,
and endgame.h's `gRaceEventNumOpenedFn` to `0x001f7458` on
`TheEventsOpened` and TheRaceEvent. GameType 4, 8 and 9 are not reached
yet: the frontend sets only the quick race's and Be A Cop's. The event
tree screen (tTreeDetails, step 16) will call MakeEventCarsAvailable,
ContinueMultiTrackEvent, SetSelectedEvent and StartEvent's list.

## Where the port differs

None of it is visible to the game.

- **The list of tracks.** Retail's is bMalloc'd nodes on a bList; the
  port's is an array in order, room for both directions of 256 tracks and
  the race's own.
- **Past the list.** A knockout of more races than the list has tracks
  takes the list's own head for the rest in retail (on its stack); the
  port stops. Past eight races retail writes into `aRewards`; the port
  stops at eight. The setup's counts are within both.
- **A missing event.** Retail asks IsLastOpen and the opponent's index of
  the bottom of memory for an event number the tree does not have; the
  port's word is 0 and the index 0, which retail's zeros give too.
  `nCurrentEvent` is always the event SetRace set.
- **The bottom of memory.** No car table reads zeros in retail and in the
  port. A knockout or tournament without a state has retail read or write
  its selected car there; ContinueMultiTrackEvent on another event
  assigns retail's stack's leftovers, the port car 0, skin 0, no dash.
  The disc's events have their states.
- **The floats.** The traffic shares are times `100.0f` with eefpu.h's
  `ee_mul`, which rounds to nearest where the R5900's `mul.s` rounds
  toward zero; a share whose product lands just under a whole number
  (0.7f is 69.9999988) is truncated one higher than retail's. The check's
  emulator rounds to nearest too.

## The check

`tools/fredevent_check.py` runs the disc's two trees and four made-up
ones through both sides: the select screen's words; the tree for each
game type, E3 and not; every event's cars (with a made-up car table and
none, with and without CarTypeInfoArray), word, opponents 0 .. 6,
selected car kept and given back, and SetRace with the list of events
opened judged as the event's state moves; the last event open; and 400
challenge knockouts over random tracks, unlock masks, track numbers,
directions, traffic and bRandom answers, with each setup mode. 18963 ops,
43736 lines, 0 differ. All 99 mutations are caught.
