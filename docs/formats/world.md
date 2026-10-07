# World -- the clock, the car table, the step and the debug views

    0x0014a4e8 .. 0x0014c38c    World.obj
    0x0014a4e8, 0x0014a748      the constructor and destructor (worldinit.c)
    0x0014ab08 .. 0x0014bd2c    the clock, the car table, the step (worldstep.c)
    0x0014bd30 .. 0x0014c030    DebugDisplay, the recorders, the AI views
                                (worldinit.c)
    0x0014bb60, 0x0014bbb8      GetDistanceToClosestPlayer (world.c)
    0x00238328                  bList::Sort (blist.c)
    0x002383f8 .. 0x0023849c    the bPNode pool (bplist.c)
    0x0020a840 .. 0x0020ab48    OBB's methods (obb.c)
    0x001c1210                  GetVectorOnTrack (track.c)
    gp-22624 (0x00323390)       pCurrentWorld
    gp-22620 (0x00323394)       TweakerPauseWorld
    gp-22608 .. gp-22592        the AI debug views' five tweakers

World owns everything that moves in a race: the car lists, the collision
list, the car table and the per-player positions. It also keeps the pause,
the time scale and a random seed of its own. Every frame the game loop asks
it for the step (GetTimestep) and then takes one (DoTimestep). The step
thinks every car, moves every body, resolves every contact, and services
the effects, the events and the race.

The port is `3DS Files/source/worldstep.c` (the step) and `worldinit.c`
(the constructor, the destructor and the debug views), with the two
distance methods in `world.c`, the list sort in `blist.c`, the bPNode pool
in `bplist.c` and OBB in `obb.c`. `tools/world_check.py` cross-checks them
against `tools/src/world_test.c`, with the image running in mipsemu as the
oracle. `bslotpool_check` checks the bPNode pool and `track_check`
GetVectorOnTrack. Still to come are DoSnapshot (0x0014a910) and
DoPointerSnapshot (0x0014ad20), which wait on ReplaySnapshot.

## The record

`World:Tt4039=s5936`, all of it in `world.h`. RaceCoordinator::InitForRace
allocates one (`bMalloc(5936, "World", 0, 16)`) and constructs it, and
CleanupAfterRace destroys it with flags 3. Neither is ported yet.

| Offset | Field | What it holds |
|-------:|-------|---------------|
| 0 | CarList | bTList<Car>: every car, sorted by x each step |
| 8 | AICarList | bTList<Car> |
| 16 | CollisionList | bTList<Collision> |
| 24 | Helicopter | Chopper*, or NULL |
| 28 | TotalNumCars | the table's length |
| 32 | AICarPos | where the AI racers start (= the player count) |
| 36 | CopCarPos | where the cops start |
| 40 | TrafficCarPos | where the traffic starts |
| 44 | CarTable[14] | Car* |
| 112 | CarPositionTable[14] | bVector3, written by CalculateDebugChecksum |
| 336 | PlayerPositions[2] | bVector3, written by DoTimestep |
| 368 | PlayerDATs[2] | float, the players' distance around the track |
| 376 | WorldRandomSeed | Random's seed |
| 380 | fTimeToRemainPaused | seconds of real time |
| 384 | PreviousTimeToWaste | the replay's wait, carried over |
| 388 | fTimeScale | the step's multiplier |
| 392 | fTimeScaleTimer | seconds of real time left at that scale |
| 396 | TimeScaleCallback | void (*)(int) |
| 400 | TimeScaleCallbackParam | its argument |
| 404 | Teleporter | TrafficTeleporter* |
| 408 | CollisionPredictionID | |
| 412 | PotentialDriveTargetID | |
| 416 | CollisionPredictionMyOBBs[20] | OBB, this car's swept boxes |
| 2016 | CollisionPredictionOtherCarOBBs[20] | OBB, the other car's |
| 3616 | CollisionPredictionMyPositions[40] | bVector2, one per iteration |
| 3936 | CollisionPredictionOtherCarPositions[40] | bVector2 |
| 4256 | CollisionPredictionMyIndicies[40] | signed byte: the box to draw |
| 4296 | CollisionPredictionOtherCarIndicies[40] | signed byte |
| 4336 | CollisionPredictionMyDriveTarget | DriveTarget |
| 4864 | CollisionPredictionOtherCarDriveTarget | DriveTarget |
| 5392 | PotentialDriveTarget | DriveTarget |
| 5920 | CollisionPredictionMaxLoopCounter | the last iteration recorded |

The fields from 416 on are for the debug views, and nothing in the shipped
game fills them: the four recorders have no callers. `Indicies` is the
stab's spelling. The OBBs and DriveTargets hold pointers, so on a 64-bit
host the tail moves; `world.h` checks its offsets only on the 3DS.

## The clock

- **SetTimeScale** (0x0014adf0) stores scale, timer, callback and
  parameter. **ResetTimeScale** (0x0014ae08) sets the scale to 1, zeroes
  the timer, the pause and the parameter, and clears the callback.
- **SetWorldPaused** (0x0014ae28) stores the pause, the callback and the
  parameter. The pause and the time scale share the one callback.
- **UpdateWorldPaused** (0x0014ae48): if the pause is above 0 it loses
  RealTimeElapsed. If that leaves it at 0 or below, it is set to 0 and a
  callback runs once, gets its parameter, and is cleared (the parameter
  too).
- **IsWorldPaused** (0x0014aeb0): pause above 0, or TweakerPauseWorld.
- **BeginPause** and **EndPause** are empty.
- **GetTimestep** (0x0014aee8) reads pReplayManager without a NULL test:
  1. While the replay plays back, the quantized step is the replay's
     (GetData, 8 bits, channel 1). Otherwise it is
     RealTimeElapsedQuantized, which the replay records while it captures.
  2. `real` = GetRealTimeElapsedFromQuantized of that.
  3. While the replay plays back (read again through the pointer), the
     wait is `min.s(0.3, max.s((real - RealTimeElapsed) +
     PreviousTimeToWaste, 0))`, and it is stored back. If the wait is above
     0, the game spins on bGetTicker until bGetTickerDifference from the
     first reading, times 0.001, reaches it. Replays play back at the
     speed they were recorded at.
  4. If the time scale's timer is above 0, it loses `real`. At 0 or below
     it becomes 0, the scale becomes 1, and a callback runs once and is
     cleared (callback first, then the parameter).
  5. The step is `real * fTimeScale`.

## The car table

**BuildCarTable** (0x0014ab08) zeroes the four counts and walks CarList
four times. The first walk adds the players (driver type 1), and then
AICarPos is the count so far. The second adds the AI racers (2), and then
CopCarPos is set; the third adds the cops and super cops (4 and 5), and then
TrafficCarPos. The fourth adds the traffic (3). A car of any other type is
left out. TotalNumCars is written after every car added. Each car's
CarIndex then becomes its place in the table. The listing ends by walking
AICarList and doing nothing with it. The image does not check the 14; the
port aborts past them.

- **GetCarByNumber** (0x0014acd8): the first car in the table with that
  DriverNumber (a signed half), or NULL. **GetCarByDriverNumber**
  (0x0014ada0) does the same on pCurrentWorld.
- **CarListCheckFlip** (0x0014adc8): `a.x <= b.x`, on State.Position.
- **bTList<Car>::Sort** (0x0014c030) is a jump to **bList::Sort**
  (0x00238328). That is a bubble sort: a pair out of order has its second
  node unlinked and put back in front of the first, and the passes repeat
  until one moves nothing. The unlinked node's links are poisoned with 11
  and then written over; the port leaves the poison out.
- **AddTrafficCar** (0x0014bce8) asks the teleporter to place a car for
  the DriverInfo (PlaceNewCar), and puts a car it gets on the end of
  CarList. It does not rebuild the table.

## The small things

- **Random** (0x0014bc98, 0x0014bcc0): bRandom, int and float, on
  WorldRandomSeed.
- **GetDATToClosestPlayer** (0x0014bc18): CompareDistances(PlayerDAT[0],
  dat) and CompareDistances(PlayerDAT[1], dat) on TheTrackPathManager, and
  whichever has the smaller magnitude. A tie goes to player 1.
- **FlushCollisions** (0x0014bce0) is empty.

## The checksums

**CalculateDebugChecksum** (0x0014b9e0) starts from WorldTimer. For each
car in the table it takes the car's own checksum (0x00130ee0), copies the
car's position into CarPositionTable, and makes the sum `sum * 33 +
checksum`. It returns `((sum >> 16) + sum) & 0xffff`.

**VerifyDebugChecksums** (0x0014ba88) runs it, and then:

1. While the Joylog replays, reads 16 bits on channel 3 and ignores them.
   Otherwise it records the checksum there.
2. The byte is `((c >> 8) + c + (seed & 0xff)) & 0xff`.
3. While the replay captures, it records the byte (8 bits, channel 2).
   Otherwise, while it plays back, it reads the recorded byte. On a
   mismatch it posts RC_SKIP_REPLAY (11) to the race coordinator, and the
   replay is abandoned.

## The step

**DoTimestepMove** (0x0014b050): when `(WorldLoopCounter + 77) & 127` is
0, DeleteFarAwaySmokeableCollisionBodies. Then every body on
CollisionBodyList with Dynamic set is copied into a 176-entry array on the
stack, and each is moved through its table's slot 64 (Move) with the step.
The copy is taken first because a move can re-sort the list.

**DoTimestepCollisions** (0x0014b110):

1. MaybePrintAllCollisionBodies.
2. Every witness that HasExpired is destroyed (flags 3); the next link is
   read first.
3. Every body that is Dynamic and ActiveCollisionDetection gets
   MaybeCreateWitnesses.
4. A contact list on the stack is filled by every witness's
   TestForContact.
5. Up to 20 rounds while the list is not empty. The head contact is
   resolved. Every other contact on either body, if that body is dynamic,
   is removed (RemoveContacts). Then the bodies to look at again are
   gathered into an 8-entry array. A smokeable (type 1) whose
   BreakingStrength is -1 breaks (Smokeable::Break) and contributes its
   pieces. Any other body contributes itself if it is dynamic and active.
   Each of them gets MaybeCreateWitnesses. Then every witness is tested
   again once for each gathered body it has on it.
6. After 20 rounds, whatever contacts are left are unlinked and destroyed
   unresolved.
7. Every Collision on the World's list is updated, and ended when
   Update says it has gone quiet. The next link is read first.
8. The list's destructor runs; by now it is always empty.

**DoTimestep** (0x0014b480), in order:

1. VerifyDebugChecksums.
2. Each player's car's position and DAT into PlayerPositions and
   PlayerDATs. A player slot that is NULL gets 9999999 in x, y, z and the
   DAT, and its fourth lane is left alone.
3. The teleporter's DoTimestep, if there is a teleporter; GlobalCopThink.
4. Think, for the AI racers, then the traffic, then the players, then the
   cops. Each loop reads the counts again after every car.
5. DoWheelForces for the players; Drive for every car; the helicopter's
   Fly, if there is one; BeginMovement for every car.
6. DoTimestepMove, then DoTimestepCollisions.
7. FinishMovement for every car. Then TriggerEvents for every car within
   100 of a player.
8. Unless the race coordinator is in INSTANT_REPLAY, POSTRACE or
   AUTO_REPLAY, or in replay demo mode: MaybeCameraShake for each player,
   and MaybeRumble unless the same test, made again, now says otherwise.
   pRaceCoordinator is read with no NULL test.
9. ServiceParticleGroups; the world effects' TweakerCheck and DoTimeStep.
10. TriggerCarTerrainEffects, with the distance, for every car within 150
    of a player whose ShouldVisualEffectsBeGenerated says so; then
    FakeEngineTask for every car.
11. emProcessAllEvents; CarList sorted by CarListCheckFlip;
    UpdatePlayersGameState; rain_TimeStep; ServiceFernFlatteners;
    ServiceTweakerDamage; ServiceTrackRouteEditor; and Race::Update, if
    there is a race ([race-update.md](race-update.md)).

## The constructor and the destructor

**The constructor** (0x0014a4e8) works on memory its caller allocated:

1. The three lists are made empty, the forty boxes get no cube, and the
   three drive targets are constructed, in the record's order.
2. pCurrentWorld is this World, and ResetWorldTime runs.
3. WorldRandomSeed is `bRandom(0x7fffffff)` on bDefaultSeed.
4. TotalNumCars and the three positions are 0, CollisionPredictionID and
   PotentialDriveTargetID are 1, ResetTimeScale runs (which clears the
   pause too), PreviousTimeToWaste is 0, and so are both players'
   positions and DATs. There is no helicopter.
5. A TrafficTeleporter: `bMalloc(88, "TrafficTeleporter", 0, 16)` and its
   constructor.
6. Eleven calls set up the systems a race needs: InitCarEffects,
   InitClans, InitSkids, InitParticles, InitMunitions,
   InitFernFlatteners, InitFernShakers, SpawnSmokeables,
   InitTerrainEffectEmitters, InitCops and InitTrackGraph.

The car table, CarPositionTable and the prediction's records are left as
they were. Constructing over a live World tears nothing down first.

**The destructor** (0x0014a748):

1. Twelve calls close the systems: CloseTerrainEffectEmitters,
   CleanupCops, CleanupTrackGraph, CollisionBodyWitness's
   EliminateAllWitnesses, ClearSmokeables, CloseFernShakers,
   CloseFernFlatteners, CloseMunitions, CloseParticles, CloseClans,
   CloseSkids and CloseCarEffects. That is not quite the constructor's
   order reversed: the terrain effects, the cops and the track graph close
   in the order they opened, and the clans close before the skids.
2. The teleporter, if there is one, is destroyed with flags 3.
3. ResetWorldTime runs, pCurrentWorld is NULL, and WorldLoopCounter is
   100000, its value in .sdata.
4. The members go in reverse: the three drive targets (the potential one,
   the other car's, this car's), then each box's cube (the other car's 19
   down to 0, then this car's), then the lists. CollisionList's
   Collisions are destroyed with flags 3, AICarList's bPNodes go back to
   their pool, and CarList's Cars are destroyed with flags 3. Each list's
   destructor unlinks its first node and destroys it until the list is
   empty, and leaves the node's own links as they were.
5. bFree, if flags has bit 0.

## The collision prediction and the debug views

The AI's collision prediction was meant to leave its working here for the
debug views: the boxes it swept both cars through, each iteration's
positions and box indices, and the drive targets it weighed. None of the
four recorders has a caller in the shipped game:

- **CollisionPredictionSetOBBs** (0x0014bdc8): for k from 0 to 19, this
  car's box k from `mine[k]`, then the other car's from `other[k]`, each
  through OBB's operator=, which moves a cube across.
- **CollisionPredictionSetDriveTargets** (0x0014be38) and
  **RecordPotentialDriveTarget** (0x0014be78) copy drive targets in
  through DriveTarget's operator=.
- **CollisionPredictionRecordIteration** (0x0014be80): iteration i's two
  box indices, then i as CollisionPredictionMaxLoopCounter (not the larger
  of i and the last), then its two positions. There is no range check.

MainLoop calls the two views:

- **DebugDisplay** (0x0014bd30) calls DebugDisplay (vtable slot 16) on each
  AI racer's controller: `CarTable[AICarPos + i]` while
  `i < CopCarPos - AICarPos`, with both read again after every call. A car
  with no controller is skipped.
- **UpdateAIDebugRendering** (0x0014bed0) does nothing unless
  TweakerPauseWorld is set. If WhichCollisionPredictionIterationToRender
  is 0 or more, all forty cubes are hidden. Then, unless
  CollisionPredictionMaxLoopCounter is less than the chosen iteration,
  that iteration's two boxes are drawn at its two positions, each put on
  the ground by GetVectorOnTrack. The box indices and this car's position
  come from one reading of the chosen iteration. The other car's position
  comes from a second reading, made after the first GetVectorOnTrack.
  After that, the first of four switches that is on picks the drive
  target for the DriveTargetRenderer: RenderChosenPotentialDriveTarget
  the potential one, RenderMyCarDriveTarget this car's,
  RenderOtherCarDriveTarget the other car's, and
  WhichCarsRegisteredDriveTargetToRender, when it is not -1, the car with
  that driver number, whose pCarDriver (Car+44) is handed over as the
  target. With none on, nothing is handed over. None of the five tweakers
  ships switched on.

**GetVectorOnTrack** (0x001c1210) puts a point on the ground with a
TopologyCoordinate of its own and GetElevation at (x, y, 0). The result is
(x, y, the height), and its fourth lane is not written. `in` is read twice
for y.

## OBB

`OBB:Tt3937=s80`: a Position, the three axes A0 to A2 (bVector3, all four
lanes used), the three half-lengths a0 to a2, and WorldObj, a debug cube
(WorldObject*) or NULL. Its methods are the last seven in DriveTarget.obj:

- **The constructor** (0x0020a8c0) sets WorldObj to NULL. **The
  destructor** (0x0020a8d0) deletes the cube, if there is one, and leaves
  the pointer.
- **operator=** (0x0020a840) copies the axes, all four lanes, and the
  half-lengths, but not the Position. The destination's cube is deleted if
  it has one, and the source's moves to the destination, so the source is
  left without one. A box assigned to itself loses its cube.
- **Render** (0x0020a9e0) builds a matrix from the three axes, each scaled
  in all four lanes by twice its half-length, and puts it through
  eMulMatrix with an identity. The fourth row is the identity's, with x,
  y and z replaced by the position. The first time, it makes the cube,
  `new (WorldObjectSlotPool) WorldObject(bStringHash("DEBUG_CUBE"), NULL,
  false)`, without testing what bOMalloc returned. Every time, it writes
  the cube's matrix and enables it.
- **DoNotRender** (0x0020ab28) disables the cube, if there is one.
  **Print** (0x0020ab40) is empty. **DoSnapshot** (0x0020a928) waits on
  ReplaySnapshot.

The multiply by the identity is m × I, and I × m is not quite the same:
every column of I × m picks up the identity's fourth row times zero, a
+0, so an axis that is -0 in one lane and negative in the others keeps
its -0 only in m × I.

## The bPNode pool

`bPNode:Tt118=s12` is a bNode with a pointer to the object it lists. A
bPList<T> lists objects that cannot be linked themselves, or that are on
another list already: World's AICarList holds the AI racers this way while
CarList holds every car. The nodes come from a slot pool of their own,
behind the last four functions of bList.obj:

- **bPListInit** (0x002383f8) makes "bPNode SlotPool" in memory pool 16
  unless there is one already. InitializeEverything asks for 1536 nodes
  and then 2048, so the second call does nothing.
- **bPListClose** (0x00238430) deletes the pool and forgets it. Nothing
  calls it.
- **bPNode::Malloc** (0x00238458) makes a pool of 32 first if there is
  none, then takes a node with bOMalloc.
- **bPNode::Free** (0x00238488) gives it back with bFree. With no pool,
  the listing reaches a `break`, and the port aborts.

## The port

Everything the step calls outside World.obj that the port does not have
is a seam in `world.h`: the teleporter, the cops, the helicopter, the
effects, the events, the rain, the race and five Car methods. A NULL
seam is skipped, except FinishMovement, which aborts. A NULL PlaceNewCar
places no traffic car, as a NULL AddCopCarToRace places no cop: Quick
Race asks for traffic (TrafficDensity 0.33), and until TrafficTeleporter
is ported (11h) its race runs without (see [quick-race](quick-race.md)).
Smokeable::Break and DeleteFarAwaySmokeableCollisionBodies are
`smokeable.h`'s: Break aborts when NULL and is reached, and the delete is
skipped.

The constructor's and destructor's calls out are seams too. The eleven
Init calls, and the eleven Close calls that are not EliminateAllWitnesses
(`collisionbody.c` has that one), are skipped when NULL. The
TrafficTeleporter's constructor aborts when NULL, because a World has a
teleporter from its constructor on and AddTrafficCar needs it. The
teleporter's destructor and Car's abort when there is something to
destroy and no seam. WorldObject's new and delete are `obb.c`'s seams:
with no new, Render draws nothing, and a cube to delete with no delete
aborts. RaceCoordinator is not ported, so nothing constructs a World yet.

The port departs from the listing in one place. UpdateAIDebugRendering
reads the car's pCarDriver with no NULL test, so a driver number that no
car has reads the word at 44 in low memory. The only renderer the shipped
game runs never looks at its target, so the port passes NULL. The
checker's emulated low memory is zero there, so the two agree.

## The check

The script covers the clock and the pause with and without callbacks,
NaNs and infinities; the step with the replay off, capturing and playing
back, with scripted ticker readings; the car table over every mix of
types, including cars of none; the sort; the traffic car; the checksums
through every combination of the Joylog's and the replay's flags;
the move's schedule; the collisions through expiry, creation, rounds that
run out, smokeables that break and collisions that end; and the step in
every race state. A random walk mixes them all.

The stubs are the same on both sides and simple: a witness's destroy and a
collision's End unlink the node and then zero both of its links, so a
port that walks a list through a node it has already freed reads NULL and
falls over rather than carrying on through a stale link. MaybeCameraShake
can change the race coordinator's state, which the shake test reads, from
inside the loop, which is what shows the test is made again before each
car's rumble and not only once. The clock is driven through a NaN,
and through the ticker readings either side of exactly 0.3 s of wait, the
replay's checksum byte through a match and a mismatch in each lane, and
GetDistanceToClosestPlayer through a player at the origin.

The constructor runs with seven values of bDefaultSeed, the edges among
them, and again over a World that has one. The destructor runs over lists
of several lengths, boxes with and without cubes, flags with and without
bit 0, and no teleporter. Each stub that destroys a node logs its links
and then zeroes them. Boxes are assigned from none, from a cube, both
ways at once, and to themselves. They are rendered at signed zeros, at
huge and tiny scales, and with axes that are -0 in one lane and negative
in the rest, the one shape that tells m × I from I × m. The recorders
take indices with high bits and positions that are NaN and infinite. A
controller's DebugDisplay can move AICarPos and CopCarPos from inside the
call, and GetVectorOnTrack can change the iteration to render, which is
what shows both are read again.

    32 scenarios, 2742 ops, 15110 lines, 0 differ; 85 steps
    328 mutations, 328 caught, 0 equivalent, 0 unexplained

Of the constructor slice's 128 mutations, the first pass left one:
`render mul order`, which swaps eMulMatrix's operands. No box had the
shape above until the rerun.
