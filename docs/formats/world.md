# World -- the clock, the car table and the step

    0x0014a4e8 .. 0x0014c38c    World.obj
    0x0014ab08 .. 0x0014bce0    the methods ported here (worldstep.c)
    0x0014bb60, 0x0014bbb8      GetDistanceToClosestPlayer (world.c)
    0x00238328                  bList::Sort (blist.c)
    gp-22624 (0x00323390)       pCurrentWorld
    gp-22620 (0x00323394)       TweakerPauseWorld

World owns everything that moves in a race: the car lists, the collision
list, the car table and the per-player positions. It also keeps the pause,
the time scale and a random seed of its own. Every frame the game loop asks
it for the step (GetTimestep) and then takes one (DoTimestep). The step
thinks every car, moves every body, resolves every contact, and services
the effects, the events and the race.

The port is `3DS Files/source/worldstep.c`, with the two distance methods
in `world.c` and the list sort in `blist.c`. `tools/world_check.py`
cross-checks them against `tools/src/world_test.c`, with the image running
in mipsemu as the oracle. Still to come are the constructor, the
destructor, the collision prediction and the debug rendering (task 26's
next slice), and DoPointerSnapshot, which is the replay's.

## The record

`World:Tt4039=s5936`. `world.h` names it up to PotentialDriveTargetID, at
412. The rest is the collision prediction's OBBs, positions, indices and
drive targets, which come with the constructor.

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
    there is a race.

## The port

Everything the step calls outside World.obj that the port does not have
is a seam in `world.h`: the teleporter, the cops, the helicopter, the
effects, the events, the rain, the race and five Car methods. A NULL
seam is skipped, except FinishMovement and PlaceNewCar, which abort.
Smokeable::Break and DeleteFarAwaySmokeableCollisionBodies are
`smokeable.h`'s: Break aborts when NULL and is reached, and the delete is
skipped.

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

    24 scenarios, 2173 ops, 12963 lines, 0 differ; 85 steps
    200 mutations, 200 caught, 0 equivalent, 0 unexplained
