# The replay's snapshots (TASKS 72)

Retail replays a race by running it again. A snapshot is a memory image
of every simulated object. A replay restores one, then runs the world on
the recorded pad stream (`bRepeat`) until it catches up. Each class has a
`DoSnapshot` that moves its fields in and out of the snapshot in a fixed
order. One call serves all four modes, by the flags at +60 .. +63 of
`ReplaySnapshot`:

- taking a snapshot;
- restoring it;
- taking a checksum;
- verifying a checksum.

`ReplaySnapshot` and `bRepeat` are 72a's (`replay.{c,h}`, `brepeat.{c,h}`,
`tools/replay_check.py`). The cars and their physics are 72b's
([car.md](car.md), "The replay's snapshot", `tools/carsnap_check.py`).
The drivers and the AI are 72c's (each class's page,
`tools/aisnap_check.py`). This page lists 72d's.

## How the lists read

Each line is one move, in order. The kinds are `replay.h`'s helpers:

| kind | what moves |
|------|------------|
| int N, uint N | N bytes of an int; a restore sign-extends an int and zero-extends a uint |
| short N, char N | the same, for a 16- and an 8-bit field |
| bool | one byte; a restore makes it 0 or 1 |
| float, timer | four bytes |
| data N | N bytes as they are: an enum's first byte, a whole array |
| verify int N, verify float | only the checksum sees it; a restore leaves it |

A section is `BeginNamedSection`; the image's "named" end
(`EndNamedSection`) is noted where retail uses it.

## 72d-1: the race's setup, the clock and the race

### RideInfo, 0x00188518, section "RideInfo"

`Type` data 1, `SkinNumber` char 1, `HasDash` char 1.

### DriverInfo, 0x00188690, section "DriverInfo"

`EliminatedRank`, `UniqueDriverNumber`, `SkillLevel`, `StartingPosition`
char 1 each; `TheDriverType` data 1; the ride; `CharacterNumber` char 1.
A restore whose character is not -1 looks its `pCharacterInfo` up again
(`GetCharacterInfo`).

That is retail's layout's order: the rank at 0, the number, skill and
start at 1, 3 and 4, the type at 8 and the ride at 12. The character (at
2) comes last. The port's DriverInfo keeps the demo's order (car.h).

### cPlayerSettings, 0x001ee030, section "cPlayerSettings"

`DrivingStyle`, `TransmissionType`, `PreferredGender`, char 1 each.

### RaceParameters, 0x001ed6f8, section "RaceParameters"

1. `TrackNumber` int 1.
2. `TrackWeather`, `TrackTimeOfDay`, `TrackDirection` data 1.
3. `TrafficDensity`, `TrafficOncoming` float.
4. `RaceType` data 1, `TimeTrialTime` timer.
5. `Point2Point`, `NumLapsInRace`, `NumPlayerCars`, `NumAICars` int 1.
6. `OpponentSelect` data 1.
7. `PlayerStartPosition[0]` and `[1]` char 1.
8. `DamageEnabled` bool.
9. `GlobalDisplaySettings.JumpCams` and `.ZoneCams` char 1. The demo
   moved its two bools, `JumpCamsEnabled` and `ZoneCamsEnabled`, here.
10. `TrainingLinesEnabled` bool.
11. `TrafficOncoming`'s first byte again (data 1), as the demo's does.
12. `HasObjective` bool, `NFSRaceMode` data 1.
13. `nMaxCops`, `bTickets`, `bRoadBlocks`, `bSpikeStrips`, `bHelicopter`,
    `New624`, `BeACop`, `BeACopResetTimerAfterArrest`,
    `nNumTicketsBeforeArrest`, `nNumBeACopRoadBlocks`,
    `nNumBeACopChoppers` int 1.
14. `CopStrength` data 1.
15. Both players' settings, then `OpponentStrength` data 1.
16. `Boost` int 1, `BoostScale[0]` and `[1]` float.
17. `NumDriverInfo` int 4, then that many drivers from
    `pDriverInfoTable`.

### WorldTimeDoSnapshot, 0x001a36c0, section "WorldTime", named end

`WorldTimer` data 4, `WorldTimeSeconds` float, `WorldLoopCounter`,
`WorldTimeFrames` and `WorldTime` int 4, `WorldTimeElapsed` verify float,
`WorldTimeElapsedFrame` float.

### JoystickDoSnapshot, 0x001544f8, section "Joystick"

`CurrentJoystickTypes`, data 2.

### SnapshotCameraShakers, 0x001564d0, and tShaker, 0x00156220

There is no section. For each of the two shakers:

1. Whether `pAmplitude` is set, as a bool.
2. `vShake` as a vector.
3. `fTime`, `fDuration` and `fFrequency` as floats.

A restore points a shaking one at `ShakeAmplitudeEnvelope`, the only
envelope there is, and the rest at NULL.

### NisManager, 0x001b11f8, section "NisManager"

A restore stops the animation (`StopAnimating`) first. Then:

1. `StartTime`, `EndTime`, `NisNumber` int 4.
2. `PlayerCar` and `OtherCar`, each as its driver number in one byte
   (World's pointer move, 72c).
3. `Playing` and `CamNumber` int 1.
4. `OtherCarMovementModeBeforeNIS` and `PlayerCarMovementModeBeforeNIS`
   data 1.

If a restore leaves the NIS playing, it loads the NIS when it is not the
one loaded: `Load`, then `EnsureNisIsLoaded`, which services the
resources until the load is done. Then it starts the animation. The
port's NIS player is `nismanager.h`'s seams, which the game does not set
yet ([nis.md](nis.md)), so there a restore does neither.

### TrafficCar, 0x00167a60, section "TrafficCar"

The table's slot 24. `Position` data 8; `Angle`, `Speed`, `Pitch` and
`Roll` float; then CarMover's, which is an empty `jr ra`.

### TrafficTeleporter, 0x00222780, section "TrafficTeleporter"

`TimeUntilTeleport` float, `LastCar` uint 4.

### tTrackGraph, 0x0024e318

There is no section. `bHasCloakedEdge` bool. Then, for each of
`nNumEdges` edges, `bIsCloaked` bool, but only where the edge's
`bCloakable` word (at 24) is set.

### RacingCar, 0x00146c90, section "RacingCar", named end

1. `CurrentBoundaryRegion` and `HighestBoundaryRegion` short 2.
2. `CurrentLapNumber`, `NumLapsCompleted`, `RacePosition`,
   `PreviousRacePosition`, `FinishingOrder`, `CrossedFinishLine` and
   `CompletedNewLap` char 1. `CrossedNewBoundary` is not moved.
3. `NumLapsLed` and `FinishReason` short 2.
4. `CurrentLapNumberExact`, `dCurrentLapNumberExact`,
   `PreviousDistanceAroundTrack` and `FinishedLapNumberExact` float.
5. In a time trial (`RaceType` 2), three timers:
   `BoundaryCrossingTimes[0]`, then `BoundaryCrossingTimes` and
   `RunningTimes` at the race's `FinishLineBoundaryNumber`. That is
   `pCurrentRace`'s signed byte. At -1 or 5 it reaches the neighbouring
   word, as retail does.

### Race, 0x001477d0, section "Race"

1. `RaceStage` data 1.
2. `StartGoTimeFrames` and `StartCountdownTimeFrames` int 4.
3. `StartTime` and `RaceTime` timer.
4. `NumRacingCars` verify int 1, `NumRacingCarsFinished` int 1,
   `DetectedOneCarRemaining` bool.
5. For each racing car: its RacingCar, then `pRacingCars[i]` as its index
   in `RacingCarTable`, char 1. The image gets the index by dividing the
   byte offset by 192 with a multiply; the port counts records, which are
   wider on a 64-bit host.
6. `NumLapsInRace` verify int 1.

`BestLapTime` is not moved.

### Player, 0x00175db0, section "Player", named end

`playersnap.c`, apart from player.c, as carsnap.c is from car.c: it
reaches the NIS manager, the average and SetInputMode.

1. `TimeFinishedRacing` int 4, `FinishAnimationLength` int 2,
   `nZoneCurrent` int 1.
2. `nZoneCredits` data 8, `tAutoZoneTimers` data 32.
3. `nGlueCount` int 1.
4. The speed ratio's Average (72c).
5. `tAverageSpeedTimer` timer, `fMaxSpeedRatio` float.
6. `LastTimeCarInTrouble` and `TimeToDisplayResetPrompt` timer.
7. `fTroubleSpeed` float, `tTroubleSpeedTimer` timer.
8. `DrivingControls` data 4.
9. `ArrestNisIndex` and `TicketNisIndex` int 4.
10. `NisFinishedCallback` data 4: the function's address. A replay is
    only played back by the build that took it.
11. `NisFinishedCallbackParam` int 4.
12. The NisManager.
13. `bWrongWay`, `bLookBack` and `bZoneMuffleSound` bool.
14. A restore calls `SetInputMode(0)`.
15. `fFreezeZoneDelayTimer` float.

## The checker

`tools/racesnap_check.py` runs retail's code beside the port's, on
`tools/src/racesnap_test.c`. It shares carsnap_check's layout parser,
fills and cycle. Each record is filled, then put through five passes:

1. taken;
2. restored over other values;
3. checksummed;
4. verified;
5. verified again after a change.

The snapshot and the objects are dumped after each pass.

These run real on both sides: ReplaySnapshot, the snapshots, Average's,
and World's pointer move. These are recorded, each as a line both sides
print:

- `GetCharacterInfo`, a place in a block called `chars`;
- the NIS player's `Load`, `ServiceResourceLoading`, `StopAnimating`
  and `StartAnimating`;
- `SetInputMode`.

The globals are set by ops of their own on both sides: the clock's seven
words, the joystick types, the shakers and their envelope,
`TheRaceParameters`, `pCurrentWorld` and `pCurrentRace`.

The scenarios cover these cases:

- drivers with a character, with none (-1) and with -128;
- race setups with 3, 0 and 14 drivers;
- shakers pointing at the envelope, at NULL and elsewhere;
- a playing NIS already loaded, one not loaded, one stopped, and a
  `Playing` word whose byte is 0;
- the traffic car through its table and directly;
- graphs with 12, 16 and 0 edges, with `bCloakable` words of 0x100 and
  0x80000000 among them;
- racing cars in and out of a time trial, at finish lines 2, -1, 5 and 1;
- races with 3, 8 and 0 cars, their `pRacingCars` shuffled and repeated;
- a player with its average and its NIS manager.

The run is 5785 script lines and 21743 output lines; none differ.
All 87 of 87 mutations are caught.

    python tools/racesnap_check.py
    python tools/racesnap_check.py --mutate [--only a,b]

## Not yet

- 72d-2: `World::DoSnapshot` (0x0014a910) and
  `RaceCoordinator::DoSnapshot` (0x001498f0), which call all of the
  above.
- `AnimatedDriver::DoSnapshot` (0x001a9770): AnimatedDriver is not
  ported, so its snapshot is not either.
