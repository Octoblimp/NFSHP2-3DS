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
`tools/aisnap_check.py`). This page lists 72d's: the race's own
classes (72d-1), then World's and RaceCoordinator's, which take all of
them, with the smokeables and the collision bodies (72d-2).

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
| verify data N | the same, for N bytes |

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

## 72d-2: the world, the coordinator, the smokeables and the bodies

`worldsnap.c` holds World's, RaceCoordinator's and SnapshotCops;
`smokesnap.c` the smokeables'; `bodysnap.c` the three SnapshotEverythings.
Each is a file of its own, as carsnap.c is: they reach the pools, the
constructors and the other classes' snapshots, which a checker records
rather than runs.

### RaceCoordinator, 0x001498f0, section "RaceCoordinator"

World's (`pCurrentWorld`), then Race's (`pCurrentRace`), then each of the
`PlayerNumPlayers` players' (`PlayerPlayersByIndex`). The coordinator
itself moves nothing.

### World, 0x0014d148, section "World"

1. `WorldRandomSeed` uint 4.
2. `fTimeToRemainPaused`, `fTimeScale` and `fTimeScaleTimer` float.
   `PreviousTimeToWaste`, between the first two, is not moved.
3. `TimeScaleCallback` data 4: the function's address, as Player's
   callback. `TimeScaleCallbackParam` int 4.
4. `PlayerPositions[0]` and `[1]` data 12, `PlayerDATs[0]` and `[1]`
   float.
5. `CollisionPredictionID` and `PotentialDriveTargetID` uint 4.
6. A restore throws away what a snapshot cannot carry: `FlushClans`, the
   world's effects (`KillAllActiveEffects` on `WorldEffects`),
   `FlushFernShakers`, then `bResetGlare = 1` and `ResetCameraShakers`.
7. The clock (`WorldTimeDoSnapshot`), the teleporter if there is one,
   `TheTrackGraph` if there is one, and every car in `CarTable` up to
   `TotalNumCars`.
8. `SnapshotCops`, then the chopper if there is one.
9. A restore eliminates every witness (`EliminateAllWitnesses`); the last
   step makes them again.
10. `SnapshotAllSmokeables`, then TrackPolygonCollisionBody's,
    CollisionBody's and CollisionBodyWitness's SnapshotEverything.

The port has no clans, no fern shakers, and no cop manager's or chopper's
snapshot yet: those four are calls through `gFlushClansFn`,
`gFlushFernShakersFn`, `gCopManagerDoSnapshotFn` and
`gChopperDoSnapshotFn` (world.h), skipped while NULL. 72e binds the cops'
and the chopper's.

### SnapshotCops, 0x00227cd8

tCopManager's snapshot, when `pCopManager` is set. No section.

### SnapshotAllSmokeables, 0x0021fb30, section "AllSmokeables"

1. `AwakeSmokeablesCount` int 4.
2. Taking: each virgin smokeable in `CollisionBodyList` as its spawner's
   index in `pSmokeableSpawners`, short 2, then its own snapshot (slot 16
   of its table); short 2 of -1 ends the list. Then each other smokeable:
   its ID ushort 2, its info's `NameHash` uint 4, its model's name hash
   (`WorldObject::GetNameHash` on `TheWorldObject`) uint 4, the low byte
   of its smoke type (slot 208, `GetSmokeType`) data 1, then its own
   snapshot; -1 again ends the list.
3. Restoring: `DeleteSmokeableCollisionBodies` first. Then each virgin is
   made again from `VirginSmokeableSlotPool` on its spawner, and each
   other smokeable by `CreateSmokeable(type, ID, FindSmokeableInfo(info
   hash), name hash)`, each followed by its own snapshot.

The image moves the type into the low byte of a stack word whose upper
three bytes it never sets, and passes the whole word; the port's word
starts at 0. The ID goes zero-extended.

### VirginSmokeable, 0x00220128, section "VirginSmokeable"

StaticCollisionBody's (72b).

### Smokeable, 0x002208a0, section "Smokeable", with the object

1. DynamicCollisionBody's (72b).
2. `Awake` and `Blinking` char 1.
3. Its info's `NameHash` verify uint 4.
4. `AnchorStrength` and `BreakingStrength` float.
5. `TimeAwoken`, then `TimeCreated`, then `TimeLastCarContact`, timer.
6. `GroundRaise` float.
7. The spawner as its index, short 2 (-1 for none). A restore looks the
   spawner up again (`GetSmokeableSpawner`). The image reads the restored
   index from a stack short that a snapshot moving nothing leaves as it
   was; the port's is 0.
8. The rigid body (72b).
9. Taking or restoring: `UpdatePosition`.
10. `BBoxMin` and `BBoxMax` verify data 8.

Munition, DroppedBomb and SmokeBomb have Smokeable's in their tables;
DroppedSpikes (0x001bef90) and Rocket (0x001bf910) have their own, which
are 72e's.

### TrackPolygonCollisionBody::SnapshotEverything, 0x001d8980, section "AllTrackPolygonCollisionBodies"

1. `TheCollisionStats.NumTrackPolygonCollisionBodies` verify int 4.
2. Taking: each track polygon's body in `CollisionBodyList` as its
   polygon's index in `TheTopologyTree.pPolygonTable` ushort 2 and its ID
   ushort 2, then its own snapshot; 0xffff ends the list.
3. Restoring: each is made again from
   `TrackPolygonCollisionBodySlotPool` on the same polygon with the same
   ID, then its own snapshot.

### CollisionBody::SnapshotEverything, 0x001d6e70, section "AllCollisionBodies"

Every body's ID, in list order, verify ushort 2: only the checksum sees
the list.

### CollisionBodyWitness::SnapshotEverything, 0x001d6208, section "AllCollisionBodyWitnesses"

1. `TheCollisionStats.NumCollisionBodyWitnesses` int 2. A restore reads
   it into a count of its own and leaves the stats.
2. Taking: each witness as its two bodies' IDs, int 2 each, then its own
   snapshot (72b).
3. Restoring: for each, the two IDs, the bodies found by them
   (`FindCollisionBody`), a witness made again from
   `CollisionBodyWitnessSlotPool` on them, then its own snapshot.

## The checker for 72d-1

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

## The checker for 72d-2

`tools/worldsnap_check.py` runs retail's code beside the port's, on
`tools/src/worldsnap_test.c`, the same way: the five passes and a sixth
with no flags set.

These run real on both sides: ReplaySnapshot and the nine functions
above. These are recorded, each as a line both sides print:

- every snapshot they reach that another task checks: the clock's, the
  teleporter's, the track graph's, the cars', the cops', the chopper's,
  the race's, the players', the static and dynamic bodies', the rigid
  body's and the witnesses';
- the restore's flushes, the effects' kill and the shakers' reset, with
  `bResetGlare` as it is then;
- the three pools' allocations, which make objects both sides name alike
  (V0, T0, W0, and S0 for `CreateSmokeable`'s);
- the constructors, `CreateSmokeable`, `UpdatePosition`, the lookups of
  spawner, spawner index, info and body, and `GetNameHash`;
- the bodies' tables, through a recording table whose slot 208
  (`GetSmokeType`) answers the hash of the object's name.

The scenarios cover these cases:

- a virgin smokeable;
- smokeables with a spawner, with none, and with one restored over none;
- every smokeable over a list of three virgins, three smokeables (one
  whose info no lookup finds, one whose ID is -2), a track polygon's body
  and a car's; then a shorter list and an empty one;
- track polygons' bodies over lists of three, one and none;
- the bodies' checksum with an ID changed;
- witnesses three, one (a count word of 0x10001, of which two bytes
  move) and none, with IDs of 200 and -5;
- a world with three cars, a teleporter, a chopper, a graph and the cops;
  one with none of them; one with a chopper and no teleporter or cops;
- the coordinator with one player, two and none;
- the cops with a manager and without.

The run is 1752 script lines and 5631 output lines; none differ. All 88
of 88 mutations are caught. A source check holds smokeable.c's two tables
to the new snapshots in slot 16.

    python tools/worldsnap_check.py
    python tools/worldsnap_check.py --stubs
    python tools/worldsnap_check.py --mutate [--only a,b]

## Not yet

- 72e: tCopManager's (0x00223b70) and the chopper's (0x001e7d08)
  snapshots, and DroppedSpikes' and Rocket's.
- `FlushClans` (0x001ab650) and `FlushFernShakers` (0x001da1b0): the port
  has neither the clans nor the fern shakers yet.
- `AnimatedDriver::DoSnapshot` (0x001a9770): AnimatedDriver is not
  ported, so its snapshot is not either.
