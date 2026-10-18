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
its retail layout, 20664 bytes. main.c has run it in the race since
72f-2, below.

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

## 72f-2: the manager in the race

main.c binds retail's manager where its stand-in was. Every race now
captures as retail's does.

### Where the race reaches it

- RaceCoordinator's constructor (InitForRace) makes it with
  `replaymgr_construct`. Its destructor deletes it with
  `replaymgr_destroy` after the race and the world are gone.
- The coordinator's TICK at RACING marks the beginning of time
  (MarkTheBeginningOfTime). The log is made, and the capture starts, if
  there is memory for it. RACE_IN_PROGRESS's TICK reads BeginningOfTime
  through an accessor retail inlines; main.c keeps it.
- TheRaceHasFinished marks the end of time (MarkTheEndOfTime).
- GetData and AddData are the manager's. GenerateJoyEvents's pad events
  and World::VerifyDebugChecksums's byte (channel 2) go into the log
  while capturing and come out of it while replaying.
- RealDriver's E-brake and the chopper's fire register interesting
  events (RegisterInterestingEvent), which weigh the instant replays.
- VerifyDebugChecksums posts RC_SKIP_REPLAY through the coordinator's
  PostMessage (`gRaceCoordinatorPostMessageFn`) when a replayed frame
  comes out differently. Nothing bound that seam before, since nothing
  replayed.

### MainLoop's frame

main.c's `raceFrame`, in MainLoop's order:

1. The coordinator's TICK, then the flow's service.
2. The players' input modes, then DoFancyJoylogDebugging.
3. With the flow paused (the coordinator in PAUSE), the world steps by 0
   and there is no replay frame.
4. Otherwise BeginFrame decides whether this frame captures or replays.
   A replay paused this frame (the replay screen's pause, or three
   frames in four of its slow motion) prepares a step of 0 and still
   reads the events. Any other frame steps the world as before.
   EndFrame then moves the capture on.

### Memory

The log is 0x32000 bytes. Each snapshot is 38232 bytes, and up to 17
are made as they are needed. MarkTheBeginningOfTime asks for 0xd0ad8
bytes (the log and all 17) free past 32 KB, or it captures nothing.
With the port's 48 MB heap, the races in Azahar capture with room to
spare: 0 bakes failed. Most of a snapshot is unused. In the runs below,
a race snapshot holds 2.5 to 3.3 KB and a checksum 5.7 to 6.4 KB.

### Not bound yet

- The special events' handler (`gReplayHandleSpecialEventFn`, retail's
  HandlePauseMenuReplaySpecialEvents) and DemoModeReplay::Service
  (`gDemoModeReplayServiceFn`) are NULL until 72h.
- RCSTATE_AUTO_REPLAY's handler is 72g-4's. Nothing in retail posts
  RC_REQUEST_AUTO_REPLAY, so the state is never entered.
  RCSTATE_INSTANT_REPLAY's handler is 72g-3's.

### ReplayCheck, the port's own test

"ReplayCheck 1" in `sdmc:/nfshp2_config.txt`, with "DebugLog 1", plays
two parts of each race back as the race goes. main.c's
`replayCheckTick` and `replayCheckFrame` do it. Each round sets
retail's four checksum loops (ChecksumSnapshotTimes), waits for them to
be taken, then restores a snapshot from before them:

- Round 1: checksums 600 to 900 loops into the capture, 100 apart. It
  restores the last lap snapshot before the first one.
- Round 2: checksums 30 to 120 loops on, 30 apart. It restores the
  older instant replay, as View Replay will.

Each replay runs on to where the capture had got to. Every frame
compares the world's checksum byte from the log, and each checksum
snapshot is verified against the race. Capture then goes on. Each
round logs:

- the frames replayed;
- the checksum snapshots verified;
- the frames whose checksum differed (RC_SKIP_REPLAY);
- the snapshot sections that did not verify, by name
  (`gReplayChecksumBreakFn`, the port's own, called by MoveData);
- every snapshot held;
- the slowest BeginFrame while capturing.

On Azahar (2026-10-17), a SkipFE race with the gas held:

| round | restored | replayed | frames | checksums verified | frames off | sections failed |
|-------|----------|----------|--------|--------------------|------------|-----------------|
| 1 | LAP_SNAPSHOT, loop 428 | 428..930 | 502 | 4 | 0 | 0 |
| 2 | INSTANT_REPLAY, loop 879 | 879..1080 | 201 | 4 | 0 | 0 |

There were 0 breaks in all. The slowest BeginFrame took 2.97 ms, the
lap snapshot at loop 0. An earlier run, before the frame and checksum
counts were logged, also had 0 frames off and 0 failed sections over
loops 405..930 and 859..1080. The race between the snapshots is the
same on every replay, so 72g's View Replay can start from any of them.

## 72g-1: the post-race's highlights

RCSTATE_POSTRACE (`rcpost.c`) already called four seams, but nothing
bound them, so the world behind the end screens stood still on the
race's last frame. main.c now binds them to the manager:

- `gReplayBeginRaceHighlightsFn`: BeginRaceHighlights (`0x0013e308`),
  on the state's ACTIVATE.
- `gReplayBeginNextRaceHighlightFn`: BeginNextRaceHighlight
  (`0x0013e318`), on its TICK once WorldLoopCounter reaches the current
  highlight's end. The state then makes the demo camera again.
- `gReplayEndCurrentHighlightTimeFn` and `gReplayMuteHighlightsFn`:
  EndCurrentHighlightTime and MuteHighlightSoundFlag, words 160 and 12
  of the manager. Retail reads them inline, as do the End Game Menu and
  the pause menu. Two accessors in main.c return them.

The world now replays the race's highlights behind the end screens, as
retail's does. The rules are the ones in "The highlights" above.

The instant-replay state and View Replay came in 72g-3.

On Azahar (2026-10-17), `run_azahar_career.ps1 -Race -FinishSeconds 40
-FinishPlace 1` played event 32 (Coastal Parklands) with the gas held:

- The race moved from loop 1146 and finished past loop 3494.
- Behind the results, the Reward menu and the best times, the world
  played loops 1744 to about 2890 and then went back to 1744. It played
  them twice over, and was on a third pass when the save came.
- The replay is the race. Car 0 was at 186.4 -752.7 on loop 1744
  replayed and at 189.6 -752.2 on loop 1748 live; at 350.7 -912.2 on loop
  2106 replayed and at 349.7 -913.8 on loop 2108 live. The second and
  third passes were the same to the 0.1 on every logged loop.
- The end screens showed the player's car in the demo camera's shots, at
  29.9 FPS.
- PASS: the autosave, the unload and the event tree followed, with 0
  bakes failed and stderr empty.

## 72g-2: ReplayScreen

`replayscreen.c` is retail's ReplayScreen (`0x001ebda8` .. `0x001ed4e0`):
the screen over an instant replay, with its timeline, its markers, its
camera modes and its buttons. RCStateInstantReplayCallback makes one
(72g-3). MainLoop's `raceFrame` updates the race coordinator's screen
(word 44) after UpdatePlayersNonGameState, as retail does at
`0x0012f58c`.

### The class

It is 584 bytes. The demo's class was 248 bytes and had one list of
markers. Retail has two lists of 16:

- `LapMarkers` at 40, for the laps and the instant replay.
- `HighlightMarkers` at 300, for the demo's snapshots.

Word 28 is new as well. It holds the RealLoopCounter of the last event
handled, so the screen handles one event a loop.

- **The constructor** (`0x001ebda8`):
  - It shows the screen `0x60befaed`.
  - It sets the timeline's span from the manager's BeginningOfTime and
    EndOfTime, in seconds. The span is at least a second.
  - It places the timeline at the TIMELINE bitmap's X, with the bitmap's
    width. Without the bitmap it uses 10 and 100.
  - It builds the markers, finds the three demo indicators, adds the
    handlers for events 99 to 110 on both ports, and makes the camera.
  - It shows ONE_PLAYER_ONLY when there is one player, and unmutes the
    replay's sound.
- **The markers** (`0x001ec0c0`). Retail's symbols call this the
  constructor; its callers say otherwise. Every marker is hidden first.
  To build, it then walks the manager's snapshots in order:
  - `LAP_SNAPSHOT` takes `LAP_MARKERn`, with n counting the laps from 1.
  - The first `INSTANT_REPLAY` takes `INSTANT_REPLAY_MARKER`, on the lap
    list.
  - `DEMO_MODE_SNAPSHOT` takes `HIGHLIGHT_MARKERn`.
  - `HIGHLIGHT_SNAPSHOT` takes nothing.

  A marker whose object is missing still takes its slot. It is not shown
  or placed, and its times stay whatever the slot held before;
  PREVIOUS_MARKER and NEXT_MARKER read them all the same.
- **Placing the markers.** A lap marker sits at its snapshot's
  beginning. A demo marker is a bar from its snapshot's beginning to its
  end: 8 high, at y 40, colored `0x80f08020`. Retail also has a green bar
  at y 46 (`0x50a040c0`) for a `HIGHLIGHT_SNAPSHOT`. That branch never
  runs, because the list holds only demo snapshots.
- **Update** (`0x001ec858`) does these things in order:
  - It builds the markers again and places the time marker at
    WorldTimer.
  - It prints the player's number.
  - For a cop (usage 1), it hides the lap and the place. Otherwise:
    - The lap shows as `n/laps` unless the race has one lap or is point
      to point.
    - The place shows as `pos/cars` when two or more cars race. With two
      players, a cop who is the other player does not count.
  - It shows the race's time. For finish reasons 2 and 3 it shows the
    reason's text instead.
  - It blinks the three demo indicators: shown for 11 of every 24
    frames.
  - It makes the camera again when there is none, or when the NIS
    starts or stops.
- **Tick** (`0x001ec768`) handles the end of the capture:
  - When the capture's end is reached (EndCapturingLoopCount less
    WorldLoopCounter is 0 or less, in a subtraction that wraps), it
    pauses the replay and notes RealTimer.
  - With the end screens up, after more than 4 seconds paused there, it
    posts `RC_SKIP_REPLAY`.
  - During a demo test, it pauses unless the test goes on.

### The buttons

Events 99 to 110 come through `JoyHandlerBridge`. While the help is up,
only HELP is heard.

| Event | What it does |
|---|---|
| 99 SKIP | MenuUpDown; posts `RC_SKIP_REPLAY` |
| 100 PAUSE | MenuUpDown; pauses, or resumes if the capture is not at its end |
| 101 PREVIOUS_MARKER | MenuLeftRight; posts `RC_MOVE_REPLAY` to the last lap marker begun more than a second ago. Unpauses and stops watching the NIS |
| 102 NEXT_MARKER | The same, to the first lap marker not begun yet |
| 103 PLAYBACK_SPEED | MenuUpDown; paused, it resumes in slow motion, else it toggles slow motion |
| 104 CAMERA_ANGLE | The next CameraMode of 4, the camera made again, frontend sound 3 |
| 105 CAMERA_TARGET | With exactly two players, the other one's car; frontend sound 5 |
| 106 HELP | Summons or dismisses the help (`ReplayScreenHelpIDs`, 802250 .. 802257). Then pauses while it is up, unless the capture has ended |
| 107 HIDE_TIMELINE | Swaps the screen for `0xddce04a3` and back; frontend sound 5 |
| 108 MARK_DEMO | Without a disc in the drive: the demo disc's timeouts to 32767 and a recording begun, or ended on release |
| 109 TEST_DEMO | When a test can run: begins one, or ends the demo; unpauses |
| 110 ERASE_DEMO | On a press during a demo snapshot, WantToBeRecordingSnapshot 1; on release, 0 |

In a demo snapshot, PREVIOUS_MARKER and NEXT_MARKER call
ServiceDemoMode instead.

The retail disc always answers that it is in the drive, so MARK_DEMO
is a tweaker's button.

### The cameras

- CameraMode 0 is a DemoCameraCoordinator.
- CameraMode 1 is a DriveCameraMover at POV 1.
- CameraMode 2 is the same looking back, at 300.9.
- CameraMode 3 is the bumper, at POV 0.

While the player's NIS plays, the NIS manager's coordinator replaces
the camera. The blur is on in a zone, or with the nitro under
REAL_CONTROL.

### The seams

main.c binds these:

- The common region's samples and MakeFrontendSound.
- The help: `g_help`'s IsActive, and 0x0016ca40's toggle on a press.

These stay NULL:

- The radial blur. The race does not draw retail's blur
  (`gRadialBlurOnFn`).
- The disc test. NULL answers 1, the disc in the drive.
- TheDemoModeReplay's seven calls, and its three words, which nothing
  sets yet. Both wait for 72h.

## 72g-3: the instant replay

`rcreplay.c` is retail's RCStateInstantReplayCallback (`0x0014b568`, 736
bytes), the handler for RCSTATE_INSTANT_REPLAY (4). `rcstates.c` puts it
in the state table. View Replay, on the pause menu and on the End Game
Menu, posts `RC_START_REPLAY`, which changes to this state.

### The messages

| Message | What it does |
|---|---|
| ACTIVATE, from the end screens | `pEndGameScreens` is set. It restores the first `LAP_SNAPSHOT`, the race from its start. When there is none, it queues a change back to POSTRACE and makes the screen all the same. |
| ACTIVATE, from the pause | It takes `THE_PRESENT` and restores the first `INSTANT_REPLAY`. When either fails, it changes back to PAUSE and makes no screen. |
| UNACTIVATE | Deletes the screen (destructor flags 3), mutes the sound, turns every player's camera movers back on and puts the joystick's type-changed handlers back. |
| TICK | Ticks the screen. |
| SKIP_REPLAY | From the end screens, back to POSTRACE. From the pause, it restores `THE_PRESENT`, deletes it and changes back to PAUSE. |
| TAKE_AUTOSNAPSHOT | Nothing; answered 1. |
| MOVE_REPLAY | Restores the snapshot posted as the param (the screen's PREVIOUS_MARKER and NEXT_MARKER), then makes the screen's camera again. |
| anything else | Answered 0. |

Making the screen turns every player's camera movers off first. Then it
picks the player the replay follows, from the pause menu's
ReplayChooser:

- 1: player 1.
- -1: the player who finished best. That is the lowest FinishPosition in
  TransientStats, the first of a tie, and its UniqueDriveNumber is used.
  It is player 0 when no player has a stats element.
- anything else: player 0.

Then come 584 bytes from pool 16, named "ReplayScreen", and the
constructor. Retail picks the player before the allocation, and so does
the port.

The port differs from retail in two tests. Retail reads ThePauseMenu
unchecked, and the port answers player 0 without one. Retail also makes
the camera again on MOVE_REPLAY with no screen test, and the port tests.

### View Replay

- **The pause menu.** main.c binds `gReplayNumInstantReplaySnapshotsFn`
  to the manager's word 140. The item is enabled while the manager holds
  an instant replay and MuteHighlightSoundFlag is clear. The first
  instant replay is taken when the capture begins, after the countdown.
  Then one comes every 300 WorldTimeFrames, and two are kept ("The
  snapshots" above). The replay begins at the older one, so it goes back
  5 to 10 seconds, and Tick pauses it at the capture's end, the moment
  of the pause.
- **The End Game Menu.** main.c's own test, `gEndGameReplayViewableFn`,
  is gone. Retail's test decides: MuteHighlightSoundFlag clear.

With "DebugLog 1", main.c's race lines now add the manager's state every
60 world frames: "race: replay log L, capturing C, replaying R, paused
P, loops B..E at W, snapshots: instant I, laps L, highlights H".

### On Azahar

Both runs were on 2026-10-17.

**From the pause menu:** `run_azahar_quickrace.ps1 -HoldFirst -HoldPlan
"65:60,0:1,77:0.45" -Presses "71:1.5,71:1.5,71:1.5,65:8,90:5,65:3,65:5,77:5,77:4"`.
START is held as a step of the plan because a short press was lost at
55% speed.

- Two instant replays were held when START paused the race. Three downs
  reached View Replay (item 4), and A changed to state 4.
- The replay screen came up with the timeline, Player1, the time and the
  place. It played to the capture's end, where Tick paused it.
- START (SKIP) restored the present and brought the pause menu back.
  START then resumed the race where the car had been before the replay.
- In an earlier run the pause came during the countdown. There the item
  stayed grayed, with no instant replay yet, as it should.

**From the End Game Menu:** `run_azahar_career.ps1 -Race -FinishSeconds
40 -FinishPlace 1 -ViewReplay` played event 32.

- The menu had 4 rows: Restart Race, View Replay, View Lap Times and
  Quit.
- View Replay replayed from world frame 1133, the lap snapshot, with
  car 0 driving the race again.
- START went back to state 7 and the End Game Menu, and the highlights
  went on behind it.
- Quit, the autosave and the tree followed. PASS.

Two script changes came with this. `run_azahar_quickrace.ps1` gained
`-HoldFirst`, which holds the plan before the presses. In
`run_azahar_career.ps1`, `-ViewReplay` does the steps above. Its event
start now counts the Select Car lines once the log has caught up,
because the tree's A can start the event at once.

### The keys

The replay's events (99 to 110) need no new code. `scannertab.c`'s
entries 92 to 103 hold for every configuration and read the DS2's
buttons, and `joyhid.c`'s map gives each a 3DS key:

| Event | DS2 | 3DS |
|---|---|---|
| SKIP | Start | START |
| PAUSE | Cross | A |
| PREVIOUS_MARKER, NEXT_MARKER | Left, Right | Left, Right |
| SPEED | Square | B |
| CAMERA_ANGLE | Triangle | X |
| CAMERA_TARGET | L1 | L |
| HELP | Circle | Y |
| HIDE_TIMELINE | Select | SELECT |
| MARK_DEMO, TEST_DEMO, ERASE_DEMO | R2, L2, R1 | ZR, ZL, R |

The last three are the demo recorder's. MARK_DEMO does nothing while
the disc is in, which on a retail PS2 is always, and the port leaves its
disc test NULL to the same end. TEST_DEMO and ERASE_DEMO need a demo
replay, which 72h brings.

### Not done here

- The replay bar's button icons are retail's PS2 shapes (72g-5).
- RCSTATE_AUTO_REPLAY is 72g-4's, below.

The two camera constructors, the NIS coordinators and the coordinator's
delete are the race's seams already bound.

## 72g-4: the auto replay

`rcauto.c` is retail's auto replay, ported for completeness:
RCStateAutoReplayCallback (`0x0014b848`, 1176 bytes), the handler for
RCSTATE_AUTO_REPLAY (5), and its four helpers. `rcstates.c` puts it in
the state table. main.c binds CleanUpAutoReplay to
`gRCCleanUpAutoReplayFn`, which the coordinator's destructor calls.

| retail | bytes | what |
|---|---|---|
| RCStateAutoReplayCallback `0x0014b848` | 1176 | the state |
| SetUpAutoReplay `0x0014c0f8` | 80 | the two highlight cars, the view and the incident |
| CleanUpAutoReplay `0x0014c148` | 168 | frees the camera |
| CheckAutoReplayCam `0x0014c1f0` | 232 | the route |
| SetUpAutoReplayCam `0x0014c2d8` | 952 | the camera |

Retail never enters the state. RACE_IN_PROGRESS changes to it on
RC_REQUEST_AUTO_REPLAY (7), but nothing posts that message. Nothing
calls SetUpAutoReplay either, and nothing takes the AUTO_REPLAY_SNAPSHOT
that ACTIVATE restores. So there is nothing to see on Azahar, and the
checker is the test.

The auto replay would show an incident again three times. The camera
flies along the road beside it, and the letterbox bars (flailer screen
`0x49c15518`) are up. SetUpAutoReplay keeps the two highlight cars and
the view. The first car's route point (Car::GetRoutePoint with 1) is
the incident point, and its place the incident's.

### The messages

| Message | What it does |
|---|---|
| ACTIVATE | Takes `THE_PRESENT` and keeps the highlight car's place as the final position. Restores `AUTO_REPLAY_SNAPSHOT`, then `INSTANT_REPLAY`, and keeps the car's place there as the start. CheckAutoReplayCam, called on `pRaceCoordinator`, then asks for a route between the two. If any of these fails, it changes back to RACE_IN_PROGRESS. Otherwise the bars show, the rewinds go to 0, every player's camera movers go off, and SetUpAutoReplayCam makes the camera. |
| UNACTIVATE | Restores `THE_PRESENT` and deletes it, hides the bars and cleans up. Then it turns the camera movers back on and puts the joystick's type-changed handlers back. |
| TICK | Waits for the replay to reach the capture's end (the manager's word 84 against WorldLoopCounter), then counts a rewind. The first restores `INSTANT_REPLAY`. The camera then flies along the road's left edge, following the second highlight car, with the look's sideways push flipped. The second restores `AUTO_REPLAY_SNAPSHOT`, and the camera flies along the route's line with no push. The third sends SKIP. |
| SKIP | Changes to RACE_IN_PROGRESS. |
| TAKE_AUTOSNAPSHOT | Nothing; answered 1. |
| anything else | Answered 0. |

### The camera

CheckAutoReplayCam cleans up first. Then it makes a PreviewRoute (24
bytes) from the highlight car. The route reaches 100 out, and it is as
long as the track runs from the start to the final position (the
difference of their TrackPathCoordinates' DistanceAroundTrack). The
answer is 1 when the route has 5 points or more. Otherwise it cleans up
again and answers 0.

SetUpAutoReplayCam builds a CameraDataItems record (164 bytes) by hand:

- An eye point 5 above the road's right edge at each of the route's
  points, each with a flat bank.
- An FOV table of 32 entries, all 40 degrees.
- The percentages from the start to the final position
  (RatioAroundTrack), or 1 minus each when the track runs backwards.
- Clip planes of 0.5 and 5000, and a vertical push of 0.2 on the look.
- The eye's speed locked to the car's. No look points, springs or
  offsets.

Then a TrackCarCameraMover (1136 bytes) on the view follows the
highlight car, with an empty shake of two control points. Retail leaves
the record's area fields, its EnterHorizComp and its ShakeBankNumber as
bMalloc gives them, and so does the port.

Everything comes from pool 16. The mover is named "TrackCarCameraMover".
The other allocations are named for racecoordinator.cpp, at these lines:
2504 (the route), 2516 (the record), 2517 (the FOV table), 2524 (the
banks) and 2525 (the eyes).

CleanUpAutoReplay deletes the mover (flags 3), the record, the FOV
table, the route (flags 3), the banks and the eyes. Each pointer is NULL
after. The constructor zeroes all six, so the destructor's call frees
nothing in a race.

### Two oddities kept

- ACTIVATE checks the route on `pRaceCoordinator`, not on the
  coordinator it runs on, and SetUpAutoReplayCam then reads its own.
  In a race they are the same coordinator.
- SetUpAutoReplayCam makes a third TrackPathCoordinate from rc+60, read
  as a place: mIncidentPoint's word and mIncidentCoord's x. Nothing
  reads it. The port hands it the same two words.

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

## The checker for 72g-2

`tools/replayscreen_check.py` runs retail's ReplayScreen beside the
port's, on `tools/src/replayscreen_test.c`.

Run real on retail's side: bStrCmp, bSPrintf and bStringHash, which
name and hash the markers. Recorded, as lines both sides print:

- bMalloc and bFree;
- the flailer's calls: the screens' visibility, the objects found, their
  visibility, place, size and color, the printed text and the language
  IDs;
- the NIS's and the cameras' constructors and destructors, and the
  blur;
- PostMessage, GetRacingCar, Timer::PrintToString and
  GetFinishReasonID;
- the sounds, the mute, the help, the disc test, the joystick's
  handlers and the seven DemoModeReplay calls.

The script covers these cases:

- The constructor over each mix of the times, the timeline's object, a
  missing object and the number of players.
- Every camera mode, the blur's zone, control and nitro, and the NIS
  coming and going.
- The markers from nine lists of snapshots: names one letter off, 15
  laps and two instant replays, 16 demo snapshots, objects missing, and
  stale lists built again.
- Update over the races, the players and the finishes, and the demo's
  indicators at the blink's edges, negative frames included.
- Tick at the capture's end, at the 4 seconds' edge and with the demo
  test, with the counters wrapping.
- Every event in each state it tests: out of range, twice in a loop,
  with the help up, and through the bridge.
- The timeline's positions, Pause and the destructor with each camera
  up. Then 900 random steps.

The run is 3309 script lines and 29580 output lines; none differ. One
fix came of it: the port subtracted the loop counters as signed ints,
and retail's `subu` wraps.

228 mutations: 225 caught, 3 equivalent.

- Two are the green bar's y and color, for a `HIGHLIGHT_SNAPSHOT`
  that the highlight list never holds.
- One drops Tick's PausedFlag test before the skip. The first test has
  paused the replay whenever the capture has ended.

    python tools/replayscreen_check.py
    python tools/replayscreen_check.py --mutate [--only a,b]
    python tools/replayscreen_check.py --dump out/replayscreen

## The checker for 72g-3

`tools/rcreplay_check.py` runs retail's RCStateInstantReplayCallback
beside the port's, on `tools/src/rcreplay_test.c`. These are recorded as
lines both sides print:

- the manager's TakeSnapshot, RestoreSnapshot by name and by pointer,
  and DeleteSnapshot;
- ChangeState, and the camera movers off and on;
- TransientStats::GetDriver and bMalloc;
- ReplayScreen's constructor, destructor, Tick and ChangeCameraMover;
- the mute, and the type-changed handlers put back.

The script covers these cases:

- Every message, in and out of range, with the end screens up and not
  and a screen up and not.
- ACTIVATE over each answer of the snapshots, from the end screens and
  from the pause.
- Each chooser, and no pause menu.
- The best finisher over random drivers and finishes, then ties and
  order.
- UNACTIVATE, TICK, SKIP_REPLAY and MOVE_REPLAY.
- Two full flows. Then 1500 random steps.

Three differences are made equal by hand:

- Retail reads ThePauseMenu unchecked. The model's NULL reads low
  memory, which is 0, so both sides answer player 0.
- The script never sends MOVE_REPLAY without a screen.
- A snapshot posted as the param is a word in retail and a pointer
  truncated to one in the port. Both print it as the snapshot's label.

The run is 5649 script lines and 10839 output lines; none differ. One
fix came of it. The port first made the screen with
`replayscreen_construct(bMalloc(...), replay_player())`, and C leaves
that argument order open. Retail asks for the driver first, and the
port now does too.

65 mutations, all caught. `tools/src/rcstates_test.c` stubs the new
handler, which `rcstates.c`'s table names; `rcstates_check` still puts
its own in state 4.

    python tools/rcreplay_check.py
    python tools/rcreplay_check.py --mutate [--only a,b]
    python tools/rcreplay_check.py --dump out/rcreplay

## The checker for 72g-4

`tools/rcauto_check.py` runs retail's five functions beside the port's,
on `tools/src/rcauto_test.c`. These are recorded as lines both sides
print:

- the manager's TakeSnapshot, RestoreSnapshot by name and
  DeleteSnapshot;
- ChangeState, SendMessage and the bars' visibility;
- the camera movers off and on, and the type-changed handlers put back;
- Car::GetRoutePoint, PreviewRoute's constructor and destructor, and
  PreviewRoutePoint::GetPosition;
- TrackPathCoordinate's constructor from a place;
- bMalloc and bFree;
- TrackCarCameraMover's constructor, with the whole record, its FOV
  table, eyes and banks, and the shake; and its destructor.

The script covers these cases:

- Every message, in and out of range.
- SetUpAutoReplay with each car, view and route point.
- CleanUpAutoReplay over all 64 mixes of the six objects, on both
  coordinators.
- CheckAutoReplayCam over each answer of the constructor, point count
  and owner.
- SetUpAutoReplayCam over each route length, direction and pair of
  TrackPathCoordinates.
- ACTIVATE over each answer of the three snapshots and the route, from
  both `pRaceCoordinator`s.
- TICK across the capture's end, through the rewinds, with each push,
  and with nothing to rewind into.
- Four whole replays. Then 2500 random steps.

These differences are made equal by hand:

- Retail deletes the mover through its vtable with flags 3. The port
  calls the mover's Destroy and then bFree. The model's stub at the
  destructor (`0x00159490`) prints the destroy, and the free for the 1
  bit.
- Retail frees the record and the FOV table with `__builtin_delete` and
  `__builtin_vec_delete`. Both jump to bFree, which the model stubs.
- The fourth lane of the bank points and the FOV entries is the stack's
  in retail and 0 in the port. Neither side prints it, nor the eye
  points' fourth lane.
- The TrackPathCoordinates' destructors are retail's alone. The model's
  stub prints nothing.
- Retail reads a NULL highlight car's place from low memory, which the
  model zeroes. The port answers 0.
- The third TrackPathCoordinate's x is a model address in retail and a
  host pointer's low word in the port. Both print TP for the route
  point.
- No call that would read through NULL is made, on either side. These
  are a rewind with no route, record or arrays, and ACTIVATE on another
  `pRaceCoordinator` with no route on this one ("unsafe"). The camera
  set up with no route prints "no route".

The run is 9513 script lines and 38513 output lines; none differ. 156
mutations, all caught. `tools/src/rcstates_test.c` stubs the new
handler, which `rcstates.c`'s table names.

    python tools/rcauto_check.py
    python tools/rcauto_check.py --mutate [--only a,b]
    python tools/rcauto_check.py --dump out/rcauto

## Not yet

- `FlushClans` (0x001ab650) and `FlushFernShakers` (0x001da1b0): the port
  has neither the clans nor the fern shakers yet.
- `AnimatedDriver::DoSnapshot` (0x001a9770): AnimatedDriver is not
  ported, so its snapshot is not either.
