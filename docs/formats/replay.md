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
them, with the smokeables and the collision bodies (72d-2). Then 72e's,
the cops: the munitions, the spike strip and the chopper (72e-1); the
pursuit and the cops (72e-2); the cop manager, which takes them all
(72e-3). Last, 72f-1's ReplayManager, which captures the race into the
log and takes, restores and deletes the snapshots.

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

The port has no clans, no fern shakers, and no cop manager's snapshot
yet: those three are calls through `gFlushClansFn`,
`gFlushFernShakersFn` and `gCopManagerDoSnapshotFn` (world.h), skipped
while NULL. The chopper's is `gChopperDoSnapshotFn`, bound in 72e-1; 72e
binds the cops'.

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
DroppedSpikes (0x001bef90) and Rocket (0x001bf910) have their own
(72e-1, below).

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

## 72e-1: the munitions, the spike strip and the chopper

`copsnap.c` holds them, a file of its own as worldsnap.c is: each reaches
its class's own functions and the other classes' snapshots, which a
checker records rather than runs.

### DroppedSpikes, 0x001bef90, section "DroppedSpikes", with the object

1. `DeploySpikes` bool.
2. Smokeable's (72d-2).

Slot 16 of its table.

### Rocket, 0x001bf910, section "Rocket", with the object

1. `Yaw` float.
2. `Target`, through World's car pointer (`DoCarPointerSnapshot`,
   0x00130910, on `pCurrentWorld`).
3. Smokeable's.

Slot 16 of its table.

### tSpikeStrip, 0x00241898, section "tSpikeStrip"

1. `v2Start` and `v2End` data 8.
2. `nRoadBlockID` int 4.
3. `fLifetime` float.
4. A restore lays the strip again: `Init` (0x002414e8) with the two ends,
   the roadblock and the lifetime just read. Init leaves the blink alone.
5. `bIsBlinking` bool, `fBlinkTimer` float.

The cop manager's snapshot (72e-3) calls it for each strip.

### Chopper, 0x001e7d08, section "Chopper"

World's calls it through `gChopperDoSnapshotFn`, which main.c now binds.

1. A restore takes the chopper out of the world first
   (`RemoveChopperFromWorld`).
2. `Plan` data 1.
3. If the plan is `CHOPPLAN_EATING_DONUTS` (6), nothing more moves; taking
   or restoring clears the variables (`ClearVariables`). The test reads
   the whole word, so a restore into a plan whose upper bytes are set
   does not see 6 and goes on.
4. Otherwise: `TimeUntilThink` float; `CurrentCar` through World's car
   pointer; `MoveMode` data 1.
5. `ChopperRoute`, `TargetRoute` and `OldCarRoute`, each through
   `TheTrackRouteManager`'s route pointer (0x001c2b30), followed by its
   point (`ChopperPoint`, `TargetPoint`, `OldCarPoint`) through the point
   pointer within that route (0x001c2bc8).
6. `TP`, TrackPathCoordinate's (72b).
7. `CurrentPos` data 12, `Matrix` as a matrix, `Speed` float,
   `Acceleration` data 8.
8. `Roll`, `DesiredRoll`, `Yaw`, `Pitch`, `DesiredPitch`, `RotRate`,
   `ZVelocity` and `GroundZ` float.
9. `EmitDust` bool, then `TargetDistance` float.
10. The bombing run: `BombRunType` data 1, `NumSalvosReleased` int 4,
    `TimeUntilNextSalvo` float, `NextLauncher` int 4, `Timeout` and
    `StuckTime` float, `TotalSalvos` int 4.

## 72e-2: the pursuit and the cops

These are in `copsnap.c` too. The cop manager's snapshot (72e-3) calls
tPursuit's for each pursuit and slot 32 of each cop's table.

### The cop manager's pointers

A pursuit, a cop or a radar trap is moved as a number, and a restore
finds it again in the manager (`pCopManager`):

- A pursuit (0x002245b8) is its `nPursuitId` as a char 1, or -1 for
  none. A restore reads it into -1 and takes `PursuitsById` at it, or
  NULL when it is below 0; it does not look at the pursuit it held.
- A cop (0x00224648) is its `nCopNumber` as an int 1, or -1; a restore
  takes `Cops` at it, or NULL.
- A radar trap (0x002243f8) is its index in `SpeedTraps` as an int 1, or
  -1; a restore takes that trap, or NULL.

A roadblock's pointer (0x00224358) is 72c's, in `copmanager.c`.

### tPursuit, 0x0022a548, section "tPursuit", with the object

1. `nPursuitId` verify char 1.
2. `pChasedCar` through World's car pointer.
3. `pRoadBlock` through the manager's roadblock pointer. While there is
   one: its `CopSpeaker` uint 4, then its two cops through the cop
   pointer.
4. `PrimaryCopSpeaker` and `SecondaryCopSpeaker` uint 4.
5. `nMaxChaseCops`, `nMaxRoadBlockCops` and `nRoadblockCount` int 4.
6. The chopper as an int 4, 1 while `pChopper` is set. A restore sets
   `pChopper` to the world's `Helicopter` when it reads 1, else NULL.
7. `fChopperAttackTimer` and `fChopperNextAttackTime` float;
   `ChopperState` data 1.
8. `nNumCops` int 4, then that many of `Cops` through the cop pointer.
9. `PursuitState`, `PursuitSubState` and `CurrentLandmark` data 1.
10. `fPursuitStateTimer`, `fRoadBlockSpawnTimer`,
    `fRoadBlockDisbandTimer`, `fCatchCarTimer`, `fChaseDirection`,
    `fChaseDirectionTimer` and the float at 1556, in that order.
11. `bAlreadyJoined`, `bAlreadyBeenHit` and `bAlreadyCalledForBackup`
    bool.
12. `fChasedCarTopSpeed` float; `BehaviourFlags` uint 4;
    `nHUDPursuitLevel` int 1.
13. `FarDriveTarget`, then `NearDriveTarget`: DriveTarget's (72c).
14. While the chased car has a player: the history (tPursuitHistory,
    0x0022d180), `nCount` int 1, then for each of the 30 its velocity as
    a vector 2 and its time as a float.
15. The roadblock state machine (0x0022ce60), with no section: `State`
    data 1, `fStateTimer` float, `SpeechFlags` and `nRoadBlockCount`
    int 4. Every mode sets its `pPursuit` back to this pursuit.
16. The barrels (BarricadeManager, 0x0024f358), a named section
    "BarricadeManager": for each of the ten, `fFadeTimer` float, then
    `nBarrel` short 2.

### tCop, 0x0022d440, section "tCop", named end

Both cops' call it first.

1. `pMyCar` through World's car pointer.
2. `pMyPursuit` through the manager's pursuit pointer. Then, in every
   mode, the pursuit is dropped if it no longer holds the cop
   (`IsCopInPursuit`, 0x0022c920) or its id is below 0.
3. `LogicState`, `LogicSubState`, `DesiredLogicState` and
   `DesiredLogicSubState` data 1, in that order.

### tPlayerCop, 0x0022d7e8, section "tPlayerCop", with the object

1. tCop's.
2. For each of the two: `nPrevSelection` int 1, then
   `fPrevSelectionTimer` float.
3. `bPrevCopLightState` bool.

Slot 32 of its table.

### tAICop, 0x0022dd20, section "tCop", with the object

Retail names its section as the base's.

1. tCop's.
2. `pMySpeedTrap` through the manager's radar trap pointer.
3. `nMyRoadBlockIndex` int 1.
4. `fSecondsInPhysicsMode` and `fMovementModeSwitchDelay` float;
   `nDrivingLineIndex` int 4.
5. `fSubStateTimer`, the two floats at 48, `MyDLOffset`'s x and y, the
   floats at 64 and 68, and `fFlankSide`, float each.
6. `RouteInfo`'s route and point through `TheTrackRouteManager`'s
   pointers, as the chopper's are.
7. A restore gives the radar trap its cop back (`cop` set to this one).
8. The float at 32 (the hit grace timer).

Slot 32 of its table.

## 72e-3: the cop manager

`copmgrsnap.c` has tCopManager's, a file of its own: it deletes and makes
the pursuits and the strips a restore needs, and reaches the pursuits',
the cops' and the strips' snapshots. World's SnapshotCops calls it
through `gCopManagerDoSnapshotFn`, which main.c binds. Retail's
VerifyMoveDataInSync calls between the parts ("After tPursuits" and the
rest) reach an empty function and are left out.

### tCopManager, 0x00223b70, section "tCopManager"

1. `nNumAICops`, `nNumRoadBlocks` and `nNumSpeedTraps` verify int 4.
2. A restore empties both cops of each roadblock below the count and the
   cop of each radar trap below its count. The cops' own snapshots give
   them back.
3. The pursuits: their count (TraversebList, `0x00250428`, given NULL)
   as an unsigned char 1. A restore deletes every pursuit on the list
   (DeletePursuit, `0x00224560`, first to last) and, for each one it
   reads, takes an id as a char 1 and makes a pursuit with it and no car
   (NewPursuit, `0x002244e0`). Otherwise each pursuit's `nPursuitId` as
   a char 1. Then each pursuit's own (72e-2), first to last.
4. The cops: slot 32 of each cop's table, for each below `nNumCops`.
5. The spike strips: their count as an int 4. A restore unlinks and
   destroys every strip (slot 8 of its table, with 3), then for each one
   it reads builds a strip from `SpikeStripSlotPool` with the default
   constructor (`0x00241308`) and puts it at the head of the list. Then
   each strip's own (72e-1), first to last.
6. For each of the eight pullovers: `bActive`, `bPlayNIS` and `bArrest`
   bool; `fHoldTimer` float; `nNumTickets` char 1; `nCopIndex` int 4.
7. `bChopperBusy` bool.
8. The speakers' ring (`CopSpeakers`, a Deque of four uints): each id
   as a uint 4, back to front, then 6. Taking, and either checksum,
   turns the ring a whole time round, each id from the tail to the head,
   until the id that was at the head comes round again; an empty ring
   moves only the 6. A restore empties the ring and pushes each id it
   reads at the head until the 6.
9. For each car up to the world's `CopCarPos`: `fPursuableTimer`, then
   `fSpeedTrapSpawnTimer`, float.
10. In Be A Cop (`TheRaceParameters.BeACop` not 0): the fourteen of
    `fCarDamage`, then `fBeACopTime`, float.
11. `bBeACopAlreadySaidLookOutForSpeeders` and the bool at 10488;
    `nBeACopNumRoadBlocks`, `nBeACopNumChopperAttacks` and
    `nBeACopNumArrestsMade` int 4.

## 72f-1: the replay manager

`replaymgr.c` has retail's ReplayManager, from Replay.obj
(`0x0013d448`..`0x0013ec98`). It captures a race into the log, takes the
snapshots a replay starts from, and plays the log back. `replay.h` has
its retail layout, 20664 bytes. main.c still runs its stand-in until
72f-2.

### The layout

| offset | field |
|--------|-------|
| 0 .. 24 | ReplayingFlag, CapturingFlag, RemoveDataError, MuteHighlightSoundFlag, PausedFlag, SlowMotionFlag, ReplayPausedThisFrame |
| 28 | NextFancyDebugTime |
| 32, 36, 40 | FancyReplayInProgress, FancyJoyEventNumber, NumFancyJoyEvents |
| 44 | FancyJoyEventTable, 32 bytes |
| 76 | NextInstantReplaySnapshotTime |
| 80, 84 | BeginCapturingLoopCount, EndCapturingLoopCount |
| 88 | FinishedAllCapturing |
| 92, 96 | BeginningOfTime, EndOfTime |
| 100 | pRepeat, the log (a p32) |
| 104, 112 | the free snapshots' list, the snapshots' list |
| 120 .. 136 | MaxNumSnapshots, MaxNumInstantReplaySnapshots, MaxNumAutoReplaySnapshots, MaxNumLapSnapshots, MaxNumHighlightSnapshots |
| 140 .. 148 | NumInstantReplaySnapshots, NumLapSnapshots, NumHighlightSnapshots |
| 152 | LapSnapshotSpacing, a float |
| 156, 160 | NextHighlightNumber, EndCurrentHighlightTime |
| 164 | LastSnapshotTime |
| 168, 172 | NumSnapshotsTaken, SnapshotTimeCursor |
| 176 | SnapshotTimeTable, 4096 loops |
| 16560, 16564 | NumSpecialEvents, LastSpecialEventNumber |
| 16568 | SpecialEventTable, 256 of 16 bytes: Type, LoopCount, A, B |

### Making and unmaking

- The constructor (`0x0013d448`) empties both lists and sets
  LastSnapshotTime and the capture's two loops to -1,
  LapSnapshotSpacing to 15 and NextFancyDebugTime to 9999999. The rest
  is 0, but for MaxNumAutoReplaySnapshots, which it leaves. In a demo
  replay it takes TheDemoModeReplay's log and snapshots (`0x002f0960`)
  and makes one free snapshot.
- The destructor (`0x0013d5c0`). A snapshot whose memory image was
  loaded (a demo's) goes back to the demo, with the log. The others and
  the free ones are freed, then the log, then the manager with flag 1.
- MarkTheBeginningOfTime (`0x0013d6f8`) runs once. The capture begins
  and ends at this loop and this time. With less than 0xd0ad8 bytes
  free past 32 KB in pool 16 it stops there, without a log, and nothing
  captures. Otherwise it makes a 0x32000-byte log with four channels:
  - 0: 8-bit repeat counts;
  - 1: 4-bit, answering 1 on an error;
  - 2: no repeats;
  - 3: 8-bit.

  Then the limits: 17 snapshots, 2 instant replays, 8 laps and 5
  highlights. All 17 snapshots are made, free.
- MarkTheEndOfTime (`0x0013d868`): the capture is over.

### A frame

- BeginFrame (`0x0013d880`). Without a log nothing captures or replays.
  - A demo replay replays.
  - The loop at the capture's end replays when paused. Otherwise it
    captures, until the capture is over.
  - A loop from the capture's beginning up to its end replays.

  Capturing, it takes the instant replay and the lap snapshots.
  Replaying, a pause pauses the frame, and slow motion pauses three
  frames in four of RealLoopCounter. Then this loop's special events.
  Then the dummy snapshot and the checksum, both ways. Last,
  DemoModeReplay::Service (`0x0013f500`), told whether a snapshot is on
  this loop.
- EndFrame (`0x0013e008`). Capturing, the end moves on to the next loop,
  and the end of time to the world's timer plus this frame's step
  (Timer::SetTime). Replaying, both flags clear.
- IsSnapshotTime (`0x0013d9b8`, new in retail) looks for the loop in the
  snapshot times. The search starts at the cursor (the last one found)
  when that time is before the loop, else at 0.
- The dummy snapshot (`0x0013da20`) is taken and deleted at once.
  Replaying, it comes on each loop the capture took a snapshot on, but
  not on a paused frame or the loop last taken or restored. Capturing,
  it comes every 211th loop, and once more than 30 loops have passed
  since the last snapshot.
- The instant replays (`0x0013daf0`) come every 300 of
  WorldTimeFrames. With both held, the older one goes. It stays as a
  highlight when its interest is above 0 and above the highlight it
  would replace; otherwise it is deleted. That highlight is the first
  one ending after the instant replay begins, or else the least
  interesting. But the walk sets none at each empty slot, so with a
  slot free only an overlapping highlight is replaced; otherwise the
  instant replay takes the free slot.
- The checksums (`0x0013dd00`, `0x0013dd88`) come on the loops in
  ChecksumSnapshotTimes (`0x002f08d8`), as "CHECKSUM0" .. "CHECKSUM3".
  - Capturing, a checksum snapshot goes at the list's end. A second of
    the same name is a bBreak.
  - Replaying, on a frame that is not paused, the one of that name is
    verified against the race now.
- The lap snapshots (`0x0013ded8`) come when NumLapSnapshots spacings
  have gone by since the beginning of time (ticks times 0.00025). With
  all eight taken, the spacing doubles and every other one goes, the
  first kept.

### The joylog's debugging, `0x0013e078`

FancyReplayInProgress is a state:

- 0 waits for the joylog's replay to reach the loop before
  NextFancyDebugTime. It then loads the first 24 pad events.
- 1 turns the joylog off.
- 2 waits for the capture's end while paused. Then it moves
  NextFancyDebugTime 211 loops on, deletes the four checksums, sets
  their loops to this one plus 1, 52, 105 and 158, and loads the second
  13 pad events.
- 3 waits for the events to run out, then turns the joylog back on.

### The highlights, `0x0013e308` and `0x0013e318`

BeginRaceHighlights starts at the first. Each next one restores the
highlight and plays it to the loop it ended on; after the last it wraps
to the first. With no highlight, the first lap snapshot plays to the
capture's end; with neither, the end is 0. With MuteHighlightSoundFlag
set it pauses instead, the highlight ending on the next loop.

### The special events, `0x0013e3f8` and `0x0013e4b0`

AddSpecialEvent keeps an event (its type, this loop and two words) from
the beginning of time until the capture is over, only with a log. Once
256 are kept, the next one ends the capture. Every event goes to the handler
(`HandlePauseMenuReplaySpecialEvents`, `0x001703e0`) as it happens.
Replaying, CheckForSpecialEvents starts at the last event looked at. It
walks back past every event not before this loop, then on through those
up to it, handling each one on it. A handler can add events; the count
is read again after each.

### The snapshots

- FindSnapshot (`0x0013e5c8`) finds the k-th snapshot of a name.
  GetSnapshot (`0x0013e648`) finds the k-th of any name.
- SortSnapshots (`0x0013e690`) takes those of a name out and sorts them
  by BeginLoopTime (bList::Sort's bubble sort), then puts them back at
  the list's end.
- RestoreSnapshotNamed (`0x0013e748`) and DeleteSnapshotNamed
  (`0x0013e790`) act on the first of a name and answer whether there
  was one. DeleteSnapshot (`0x0013e7d8`) moves a snapshot to the free
  list's end.
- HandleSnapshot (`0x0013e808`). "REPLAY_MANAGER_STATE" is the manager's
  own. Any other takes the race's setup (RaceParameters), the log, the
  pads (JoystickDoSnapshot) and RaceCoordinator's. The log's add side is
  taken while a snapshot or a checksum is taken at the capture's end;
  otherwise it is the remove side.
- The manager's own (`0x0013e8d8`), section "ReplayManager":
  1. BeginCapturingLoopCount, EndCapturingLoopCount and
     NumSnapshotsTaken, int 4.
  2. Each snapshot time, int 4.
  3. NumSpecialEvents, int 4.
  4. Each event, data 16.

  A restore reads each count before the table it counts.
- TakeSnapshot (`0x0013e9f0`) works only after the beginning of time.
  The snapshot comes from the free list (made if there is none) and goes
  to the list's end. On the loop at the capture's end, the loop goes in
  the snapshot times while there is room. A snapshot that overflowed is
  deleted, and the answer is NULL.
- RestoreSnapshot (`0x0013eb38`) clears the log's error.
  LastSnapshotTime becomes the loop restored.

### The log

- GetData (`0x0013eb88`) answers 0 unless replaying without an error. A
  log error stays until a restore.
- GetSignedData (`0x0013ebe8`) shifts left with sllv, then right with
  srlv, a logical shift. The value is cut to its bits but not
  sign-extended. The port keeps retail's shifts.
- AddData (`0x0013ec20`) works only while capturing. With fewer than 68
  bits left, the capture ends.

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

## The checker for 72e-1

`tools/copsnap_check.py` runs retail's code beside the port's, on
`tools/src/copsnap_test.c`, with the five passes and a sixth with no
flags set.

These run real on both sides: ReplaySnapshot and the four functions
above. These are recorded, each as a line both sides print: Smokeable's
snapshot, World's car pointer, the route manager's route and point
pointers, TrackPathCoordinate's snapshot, the strip's `Init` and the
chopper's `RemoveChopperFromWorld` and `ClearVariables`. Each line ends
with the section and where the data stands (`DataPosition`), so a move
swapped with a recorded call shows.

The scenarios cover these cases:

- spikes deploying and not, restored over a word of 0x101 or 0x100;
- rockets with a target, with none, and restored onto none; one with no
  world;
- strips blinking and not, restored over a word of 0x10001 or 0x10000;
- choppers in pursuit, starting a chase and ending one, and eating
  donuts twice; restores into plans of 0x302, 0x206 and 0x100, whose low
  byte alone is replaced; matrices of all three codes; each route and
  point pointer set, NULL, and changed by the restore.

The run is 1256 script lines and 4839 output lines; none differ. All 76
of 76 mutations are caught. Source checks hold munition.c's DroppedSpikes
and Rocket tables to the new snapshots in slot 16, and main.c to binding
the chopper's.

    python tools/copsnap_check.py
    python tools/copsnap_check.py --stubs
    python tools/copsnap_check.py --mutate [--only a,b]

## The checker for 72e-2

The same checker and harness. These run real on both sides too: the
three pointers of the manager, the history, the state machine, the
barrels and the four functions above. Recorded as well: World's plain
pointer, the manager's roadblock pointer, `IsCopInPursuit` (which says
what the script set) and DriveTarget's snapshot.

The scenarios cover these cases:

- a cop manager with cops 0, 1 and 4 and pursuits with ids 0, 3, 2 and
  one gone (-2), the gone one not in `PursuitsById`;
- pursuits chasing a player and not, with a roadblock and its cops (both,
  one, none) and without one, a chopper and none, from none to four
  pointers changed by the restore, and none to two chase cops, some
  NULL;
- cops whose pursuit holds them, does not, is gone, and goes before the
  restore finds it by its id; none at all;
- AI cops at each radar trap and at none, the trap's cop before and
  after, routes and points changed by the restore.

The run is 2789 script lines and 10696 output lines; none differ. All
183 of 183 mutations are caught. Source checks hold cop.c's tPlayerCop
and tAICop tables to the new snapshots in slot 32.

## The checker for 72e-3

`tools/copmgrsnap_check.py` runs retail's beside the port's, on
`tools/src/copmgrsnap_test.c`, with the same five passes. ReplaySnapshot
and the function run real on both sides. Recorded, as lines both sides
print: the pursuits' and the strips' snapshots, the two cops' (through
tables the harness installs at retail's addresses), the strip's
destructor and default constructor, DeletePursuit (which unlinks the
pursuit), NewPursuit (a pursuit `P<n>` at the list's tail) and the pool
(a strip `S<n>`). Each line ends with where the data stands.

The scenarios cover these cases:

- none to four pursuits, ids from -1 to 5, restored over none to four;
- none to three strips, restored over none to three;
- one to four cops, the player's and the AI's, in different orders;
- none, one, two, five and 64 roadblocks and radar traps, each with a
  cop past the count that a restore must keep;
- speaker rings full at heads 0 and 1, empty, partly filled, and with
  every id the same;
- `CopCarPos` 0, 3, 5, 7 and 8; Be A Cop 0, 1 and 2.

The run is 3207 script lines and 62527 output lines; none differ. 90
mutations: 89 caught, one equivalent. That one moves the id's write
before the push while the ring turns; a take never writes into the id,
so the push sees the same one. A source check holds main.c to binding
`gCopManagerDoSnapshotFn`. `tools/spikestrip_check.py` checks the
strip's default constructor.

    python tools/copmgrsnap_check.py
    python tools/copmgrsnap_check.py --stubs
    python tools/copmgrsnap_check.py --mutate [--only a,b]

## The checker for 72f-1

`tools/replaymgr_check.py` runs retail's ReplayManager beside the
port's, on `tools/src/replaymgr_test.c`.

Run real on both sides: ReplaySnapshot, bRepeat, the p32 handles and
Timer::SetTime. Recorded, as lines both sides print:

- bMalloc, bFree, bCountFreeMemory and bBreak;
- the setup's, the pads' and the coordinator's snapshots. Each moves
  the data on by a set amount, and the script can make the next one of
  a name overflow;
- the special events' handler, which the script can have add one;
- DemoModeReplay::Service.

The scenarios cover these cases:

- no beginning of time; too little memory for the log, and just enough;
- a demo replay's log and three snapshots, handed over and back;
- 520 captured frames: instant replays of set interest, laps thinned
  twice, checksums (one twice), special events and snapshots that
  overflow;
- 330 replayed frames: slow motion and a pause over a checksum, a log
  error, and an event a handler adds;
- the highlights, the lists and the sort;
- the manager's own snapshot, and the snapshot times full, out of order
  and searched from cursors;
- the joylog's debugging's four states;
- a log filled to its last bits, and 257 special events;
- a capture of dummies only, one allowed no instant replays, and each
  of the highlights' choices.

The run is 10161 script lines and 17370 output lines; none differ. 280
mutations: 273 caught, 7 equivalent.

- Two are DataPosition's zeroing in a take and a checksum; Init has
  zeroed it already.
- One is the section's name, a pointer kept only for printing.
- Two are in IsSnapshotTime. With the cursor 0 the search starts at 0
  either way. And the cursor's own entry is before the loop, so it is
  never the match.
- One stops the highlights' walk at NumHighlightSnapshots. Every later
  step would only set none again.
- One turns the overlap test in the replace condition into `<=`. With a
  slot free, a highlight is picked only by the strict overlap test; with
  none free, it goes anyway.

    python tools/replaymgr_check.py
    python tools/replaymgr_check.py --mutate [--only a,b]

## Not yet

- `FlushClans` (0x001ab650) and `FlushFernShakers` (0x001da1b0): the port
  has neither the clans nor the fern shakers yet.
- `AnimatedDriver::DoSnapshot` (0x001a9770): AnimatedDriver is not
  ported, so its snapshot is not either.
