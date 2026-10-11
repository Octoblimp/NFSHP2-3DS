# event-race -- the races an event sets

When the player starts an event of a tree, tTreeDetails::StartEvent
(`0x001f6a84`) calls `EventTree::SetRace`, which copies the event into
TheRaceEvent ([race-event](race-event.md)) and sets TheRaceParameters for
it: the race type, the time to beat, the cops, the opponents and the
objective's text. StartRace and `RaceEvent::SetupNextRace` then put each
race's track into the race parameters through `EventTrack::SetRace`.

Retail has this in EventTree.obj: `0x001f5d58` .. `0x001f60e8` (the
description) and `0x001fec20` .. `0x001ff360`. The port has it in
`eventrace.{c,h}`. `tools/eventrace_check.py` runs retail's code against
the port.

## EventTrack

An event's tracks are 4-byte words in the tree's table
([event-tree](event-tree.md)), read little-endian:

| bits | field | RaceParameters |
|---|---|---|
| 0 .. 7 | the track | `TrackNumber` |
| 8 | unused; SetFromRace keeps it | |
| 9 | the direction | `TrackDirection` |
| 10 .. 11 | the weather | `TrackWeather` |
| 12 .. 13 | the time of day | `TrackTimeOfDay` |
| 14 .. 17 | the laps | `NumLapsInRace` |
| 18 .. 24 | the traffic's density, in hundredths | `TrafficDensity` |
| 25 .. 31 | its oncoming share, in hundredths | `TrafficOncoming` |

`EventTrack::SetRace` (`0x001fec20`) sets those seven, the two shares as
`n * 0.01f`, and `Point2Point` from the track's TrackInfo (GetTrackInfo,
`0x00153420`) when it has one; without one, `Point2Point` stays as it
was.

`EventTrack::SetFromRace` (`0x001fed30`), which nothing in retail calls,
writes the fields back into the word. The two shares are times `100.0f`,
truncated (`cvt.w.s`): the density keeps 7 bits, and the oncoming share
whatever of its word the shift by 25 leaves.

## EventTree::SetRace

`0x001fee20`, for event `e` of a tree:

1. The tree's current event (`+92`) becomes `e`, and Fred's
   `nCurrentEvent` (`+0x10730`) its number.
2. TheRaceEvent gets the event's name (32 bytes), its state into
   `aOldState` (the state's size), `pTree`, `pState`, the number, type,
   class and counts, `nInitialPlayers` 1, the opponents, and the
   objective, the tree's goal `nObjective`. The cars, tracks, rewards and
   opponents are copied from the tree's tables through the event's
   indexes.
3. The reward's name, `sRewardName`, is the first reward's:
   - "No reward" when there are none;
   - a car's (type 0) name: the car's FullName id (GetShortName,
     `0x00187eb8`) translated;
   - a track's (type 1): its language id for the reward's direction
     (GetTheRightTrackLanguageID, `0x001dc5a8`: the TrackInfo's `+72`
     forward, `+76` reverse, 0 otherwise) translated;
   - anything else, "Unhandled type".

   The two fixed strings and the car's name also go through
   GetTranslatedString(const char *) (`0x0021e508`). The car's and the
   track's are copied with bStrNCpy's 32, the others with bStrCpy.
4. The objective's text: the event's description (string
   `mDescriptionString`, 70064 + n) through FormatEventDescription into
   `sObjective`, 512 bytes. `HasObjective` is 1.
5. The results are reset, `nNumTicketsBeforeArrest` is 2, `TimeTrialTime`
   0 and `BeACop` 0.
6. By the event's type:

   | type | RaceType | also |
   |---|---|---|
   | race (0) | 1 | |
   | time trial (1) | 2 | `TimeTrialTime` the objective's `nData` |
   | lap knockout (2) | 3 | |
   | race knockout (3) | 4 | a new seed on the first race; `New780` the seed |
   | tournament (4) | 5 | the same, from the tournament's state |
   | point to point (5) | 1 | `Point2Point` 1, `TimeTrialTime` the objective's `nData` |
   | Be A Cop (6) | 1 | `BeACop` 1, no tickets, `BeACopResetTimerAfterArrest` 0, `TimeTrialTime` the objective's `nData` |
   | any other | 1 | |

   A knockout's first race is its race index 0; a tournament's is when
   the points so far are under what one race gives the field
   ([event-tree](event-tree.md), "The state").
7. For every type: one player car; `nMaxCops` 6 in Hot Pursuit's tree and
   0 in the Championship's; `NumAICars` the opponents; `OpponentSelect`
   and `CopStrength` the event's; the cops' options, the EventInfo's bytes
   52 .. 58 (road blocks, helicopter, spike strips, tickets, `New624`, and
   Be A Cop's road blocks and choppers); training lines off;
   `DamageEnabled` when the EventInfo's byte 184 is not 0; the player's
   start position the opponents + 1; and both `BoostScale` words the
   event's `fOpponentBoostScale`.

## The description

An event's description has `$` tokens, from the table at `0x0031b200`.
`GetEventDescriptionToken` (`0x001f5d58`) answers the first whose name
starts the text (bStrNCmp over the name's length), and
`FormatEventDescriptionToken` (`0x001f5dd0`) makes its text:

| token | text |
|---|---|
| `$TARGET_TIME` | the objective's time, when its goal is a time (type 2): Timer::PrintToString, its leading spaces skipped, through bSPrintf as the format; otherwise "zz:zz" |
| `$NUM_LAPS` | the laps of the event's first track, "%d" |
| `$NUM_OPPONENTS` | the opponents, "%d" |
| `$NUM_RACES` | the event's count of races, "%d" |
| `$EVENTS_UNLOCKED` | "events x,y,z are Unlocked!" |
| `$COMPLETION_TIME` | "ff:ggg" |
| `$EVENT_UNLOCKED` | "event x is unlocked" |
| `$TRACK_NAME` | "TRACK_NAME_HERE" |

The last four are placeholders, printed as they are.
`FormatEventDescription` (`0x001f5f88`) copies the text while fewer than
n characters are out, each token replaced by its text (made into a
64-byte buffer), and then writes the NUL.

## Where the port is wired

- main.c binds fredrace.h's `gEventTrackSetRaceFn` (StartRace's, for the
  event's race index) to `event_track_set_race` on that track of
  TheRaceEvent's eight, and raceevent.h's `gEventTrackSetRaceOnFn`
  (SetupNextRace's and Restart's) to it directly.
- `gEventRaceTranslateFn` is GetTranslatedString(int) on a 1024-byte
  buffer of its own, as a description can run past the others' 256;
  `gEventRaceTranslateStringFn` is the car select's
  GetTranslatedString(const char *).
- Nothing calls `event_tree_set_race` yet: the tree's screen, whose
  StartEvent does, is step 16's (the full frontend). Until then
  TheRaceEvent stays zeroed, and StartRace sets no track for an event
  without tracks, so a quick race is unchanged.

## Where the port differs

None of it is visible to the game.

- **The copies.** Retail copies every entry under the event's counts,
  past TheRaceEvent's arrays (20 cars, 8 tracks, 8 rewards, 7 opponents)
  when a count runs over; the port stops at each array's end. The disc's
  counts are all within them.
- **The reward's name.** bStrNCpy copies 32 characters and no NUL from a
  name that long, and bStrCpy runs on; the port keeps 31 and the NUL.
- **A NULL table, state or TrackInfo.** Retail reads the bottom of
  memory, zeros in the image; the port reads zeros, and a NULL TrackInfo's
  language id is 0. A knockout or tournament with a NULL state has
  retail write its seed there and read it back; the port leaves `New780`
  as it was.
- **The description's end.** When the text fills the buffer, retail's
  NUL goes one past it, into `NFSRaceMode` (`rp+596`) for the objective;
  the port's text is retail's cut one short. A size of 0 or less writes
  nothing (retail writes the NUL at `dst[0]`).
- **The floats.** SetFromRace's multiply is eefpu.h's `ee_mul`, which
  clamps as the R5900 does but rounds to nearest where `mul.s` rounds
  toward zero, so a share of 0.29 can come back as 29 where retail's
  gives 28. Nothing calls SetFromRace. The check's emulator rounds to
  nearest too.

## The check

`tools/eventrace_check.py` runs the disc's two trees and four made-up
ones through both sides: every event set with descriptions of every
token, with the trees' states filled, tournaments on a race's boundary,
names up to and past 31 characters and texts that fill the objective;
the tokens, 400 track words and 400 words written back; and the
description at sizes 1 .. 512. 7337 ops, 13534 lines, 0 differ. Of 136
mutations, 134 are caught and 2 are equivalent by construction, each with
its reason in the script.
