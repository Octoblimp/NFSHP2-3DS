# The cop manager (step 12a)

tCopManager is retail's copmgr.obj, `0x002235f8` .. `0x00228fc8`. It
owns the cops, their pursuits, the roadblock and radar-trap spots, the
pulled-over cars and Be A Cop's counters. Slice 12a ports its record,
its chunks, its building and teardown, and the hit test the car's
collisions call. The cops themselves, and the manager's CreateCop and
AddCopCarToRace that make them, are `cops.md`'s (12b on).

| function | address | port |
|----------|---------|------|
| LoaderCops | `0x00227dc0` | `copmgr_loader` |
| UnloaderCops | `0x00227e78` | `copmgr_unloader` |
| tCopManager::tCopManager | `0x002235f8` | `copmanager_construct` |
| tCopManager::~tCopManager | `0x002239e8` | `copmanager_destruct` |
| InitCops | `0x00227c58` | `copmgr_init_cops` |
| CleanupCops | `0x00227ca0` | `copmgr_cleanup_cops` |
| InitRoadBlockStructures | `0x00225ec8` | `copmanager_init_road_block_structures` |
| InitSpeedTrapStructures | `0x002269a8` | `copmanager_init_speed_trap_structures` |
| GetRoadBlockFromLoadedDataIndex | `0x00226448` | `copmanager_get_road_block_from_loaded_data_index` |
| GetSpeedTrapFromLoadedDataIndex | `0x00226bb0` | `copmanager_get_speed_trap_from_loaded_data_index` |
| GetBaseSpeedTrapSpawnTime | `0x00224958` | `copmanager_get_base_speed_trap_spawn_time` |
| GetCurrentCopSpeaker | `0x002254e8` | `copmanager_get_current_cop_speaker` |
| NextCopSpeaker | `0x00225550` | `copmanager_next_cop_speaker` |
| ReserveCopSpeaker | `0x002255b8` | `copmanager_reserve_cop_speaker` |
| ReleaseCopSpeaker | `0x00225610` | `copmanager_release_cop_speaker` |
| FindLandmark | `0x00228a58` | `copmgr_find_landmark` |
| (new) a free pursuit id | `0x002244a0` | `copmanager_find_free_pursuit_id` |
| (new) delete a pursuit | `0x00224560` | `copmanager_delete_pursuit` |
| GetCopByCar | `0x00224f70` | `copmanager_get_cop_by_car` |
| MonitorImpact | `0x00228310` | `copmanager_monitor_impact` |
| CarCollisionBody::AddDamage's tail | `0x001d84c4` | `copmgr_car_impact` |
| GlobalCopThink | `0x00227cf8` | `copmgr_global_cop_think` (12f) |
| Think | `0x002246d0` | `copmanager_think` |
| TimeBasedSpeech | `0x00225660` | `copmanager_time_based_speech` |
| SetNextSpeechFillerGap | `0x00225780` | `copmanager_set_next_speech_filler_gap` |
| SupervisorActivate | `0x00225308` | `copmanager_supervisor_activate` |
| PursuitManagement | `0x00225bd0` | `copmanager_pursuit_management` |
| FindPlayerPursuit | `0x002257e0` | `copmanager_find_player_pursuit` |
| MonitorPullovers | `0x00226e70` | `copmanager_monitor_pullovers` |
| ReclaimPatrollers | `0x00224e00` | `copmanager_reclaim_patrollers` |
| tPursuit::NotInChasingState | `0x002295c8` | `tpursuit_not_in_chasing_state` (copmanager.c) |
| tPursuit::AboutToSaySomething | `0x0022b9e8` | `tpursuit_about_to_say_something` (copmanager.c) |

All are in `copmgr.c`, declared in `copmgr.h`. The records and the
small queries the HUD, cameras and AI already used stay in
`copmanager.h` and `copmanager.c`, which many checkers link.

## The record

Retail's manager is 10516 bytes, the demo's 10472 (`.mdebug`
type#5615). Retail added a word at the front, six pursuit slots and a
word after PursuitList, and four words near the end. `copmanager.h` has
the whole layout with a compile-time check of each offset on a 32-bit
target. The parts:

| offset | field | |
|-------:|-------|-|
| 0 | `nBeACopNumRoadBlocks` | the demo's 10456 |
| 4 .. 12 | `nNumAICops`, `nNumCops`, `nPlayerCopIndex` | -1 for no player cop |
| 16 | `Cops[7]` | |
| 44 | `PursuitList` | bTList, its own node the sentinel |
| 52 | `PursuitsById[6]` | retail's; tPursuit's byte at 1480 |
| 76 | `New76` | a pursuit the destructor deletes first |
| 80 | `SpikeStripList` | |
| 88 | `CarPullovers[8]` | 28 bytes each |
| 316, 320 | `nNumRoadBlocks`, `RoadBlocks[64]` | 120 bytes each |
| 8000 | `RealRoadBlockIndexFromDataIndex[64]` | -1 for a record left out |
| 8256, 8260 | `nNumSpeedTraps`, `SpeedTraps[64]` | 28 bytes each |
| 10052 | `RealSpeedTrapIndexFromDataIndex[64]` | |
| 10308 | `CopSpeakers` | Deque<unsigned, 4> |
| 10336 .. 10352 | `BeACopId`, the speech timers, `SpeechFillerCookie` | |
| 10356, 10388 | `fPursuableTimer[8]`, `fSpeedTrapSpawnTimer[8]` | |
| 10420 | `fCarDamage[14]` | Be A Cop's suspect damage, by CarIndex |
| 10476 | `nDifficultyLevel` | 0, 1 or 2, from CopStrength |
| 10480 .. 10500 | Be A Cop's time, counters, and two new words | |
| 10504, 10508 | `fMaxCopCarXdim`, `fMaxCopCarYdim` | retail's: the first cop's car's size by 1.1, from `0x002276a0` (`cops.md`) |
| 10512 | vptr | `0x002bd280`; slot 8 the destructor |

The slot pools are statics: PursuitSlotPool (1600-byte slots, six),
CopSlotPool (96, six; retail's tAICop) and SpikeStripSlotPool (2304,
ten), at gp-15644, gp-15640 and gp-15636. `pCopManager` is gp-15620,
`0x00331bec`.

## The chunks

LoaderCops is bundle slot 15 (`loader-table.md`). It takes the container
`80034500` and keeps a pointer into each of its children, which the
manager reads in place:

| child | static | record | size |
|-------|--------|--------|-----:|
| `34510` | SpeedTrapData (gp-15652) | RadarTrapInfo: a name, a centre, Be A Cop's two spawn flags | 32 |
| `34520` | RoadblockData (gp-15648) | RoadblockInfo: a name, a centre, a bitfield word | 28 |
| `34530` | LandmarkData (gp-15656) | Landmark: up to six vertices, a type, an uncloak flag | 60 |

Each child is a count then its records. Other ids are passed over. The
unloader clears what the loader set, and a container with no children
leaves all three as they were. Every retail track has the container,
with 20 to 39 radar traps, 43 to 62 roadblock spots (under the 64
slots) and 0 to 34 landmarks.

The roadblock word's bits, low first: the direction (0 both, 1 forward
only, 2 reverse only, 3 never), the spike side (2 bits), the difficulty
(2 bits) and the road closure flag (1 bit).

## Building

InitCops builds a manager when `nMaxCops` is above 0: a Hot Pursuit
race, or SkipFE with `SkipFEMaxCops`. The constructor, in retail's
order:

1. the vptr, the two lists empty, the speaker queue empty;
2. the three slot pools;
3. PursuitsById cleared from the top, New76 and bChopperBusy 0;
4. InitRoadBlockStructures, then InitSpeedTrapStructures;
5. no cops, no player cop (-1);
6. speakers 0 to 3 pushed at the head, so the queue reads 3, 2, 1, 0;
7. the speech timers (0, -50 and 12), then the speech manager's
   AllocateVoices and FlushQueue (seams, bound to
   [speechmgr](speechmgr.md));
8. each pullover cleared, except `bShouldDisplayBustedText`, which
   retail leaves;
9. each radar trap's spawn timer from GetBaseSpeedTrapSpawnTime: 15,
   30 or 45 s by the race's length (under 15 km, under 30 km, more),
   plus up to as much again at random; 1 s in the AI demo and
   `SkipFETimeUntilCopsAppear` with SkipFE;
10. fCarDamage cleared;
11. Be A Cop's speaker reserved, its roadblock and chopper counts, and
    its time (the packed time over 4000);
12. the difficulty from CopStrength;
13. the rest cleared. InitRoadClosures (`0x00228ae0`) is empty.

InitRoadBlockStructures keeps a record when its direction suits the
race, a racing route passes near it, the road there is at least 9 m
wide (the point's two widths), and the topology covers it. A kept spot
is moved onto the middle of the road at the record's distance along the
route point, and takes the road's direction and its right, the
track-map icon's angle, and its distance around the track.

InitSpeedTrapStructures keeps each record the topology covers. Retail
does not test its route search: when it misses, the result's slot on
the stack still holds the previous trap's point, or whatever was there
for the first. The port starts it at NULL and takes a heading of 0 for
none. The checker's model clears that stack slot so both run the same.

## Teardown

CleanupCops runs the destructor through the table with flags 3. The
destructor deletes New76, then each pursuit in the list, through
`0x00224560` (unlink, free the id, the pursuit's own destructor with
flags 3). Then each cop's destructor, then each spike strip, unlinked
first. The three pools are deleted and set to NULL. Bit 0 frees the
manager.

## The hits

Retail's AddDamage differs from the demo's at its end. The demo calls
`MonitorImpact(car, amount)` for any hit. Retail's tail (`0x001d84c4`)
skips hits under 1.0, then scans the body's collisions until one is
between two cars, and calls `MonitorImpact(car, amount, twoCar)`.
Retail passes the third argument though the mangled name keeps
`(Car *, float)`. The port's seam takes the body, so
`gCopManagerMonitorImpactFn` is `copmgr_car_impact`, and AddDamage
calls it when a manager exists.

MonitorImpact (`0x00228310`):

- **Be A Cop.** Only the car the player's cop is chasing counts. In a
  one-player race it must be within 50 m of the cop's car. A hit under
  5 does nothing. A hit of `fDisablingImpactMagnitudeTable[level]` or
  more (40, 60 or 75) wrecks it: fCarDamage is 1. A smaller one adds
  `amount x scale`, at most 1, to the damage, which stops at 1. The
  scale is `{100, 4, 2.5}[level] x 0.005`, or 0.01 in split screen.
- **Otherwise.** Only a car in COP_CONTROL counts. A two-car hit counts
  half as hard again. A hit at the table's value or more, on a car an
  AI cop drives (its slot 16, IsAIControlled, says 1), disables that
  car once the cop's grace timer (tAICop's word at 32) has run out.
  tAICop::Think counts the timer down; a teleport sets it to 3 s. The
  disable is tAICop::DisableMyCar (`0x00230ac8`, `cops.md`), the seam
  `gAICopDisableMyCarFn`, which `main.c` binds to `cop.c`'s; only an
  AI cop can reach it.

Retail reads the player's cop as `Cops[nPlayerCopIndex]` with no test of
-1; the port finds none.

## Think (12f)

World's step calls GlobalCopThink every frame (`gGlobalCopThinkFn`,
which `main.c` binds). It runs the manager's Think if there is one.
Then, while the track graph has a cloaked edge, it looks at the world's
cars before CopCarPos (the players and the racers). The first of them
inside a landmark with IsUncloakTrigger (FindLandmark) uncloaks every
edge (`trackgraph.md`). The frame's seconds are passed but not read.

Think runs, in this order:

1. TimeBasedSpeech, SupervisorActivate and PursuitManagement.
2. In Be A Cop, ReclaimPatrollers. Otherwise SpawnSpeedTraps, then,
   once the race clock has started (its packed time above 0, signed),
   each of the eight fPursuableTimers above 0 down by WorldTimeElapsed,
   clamped at 0.
3. MonitorSpikeBelts and MonitorPullovers.
4. Each of the nNumCops cops' Think, slot 24 of its table.
5. In Be A Cop, BeACopThink.

RenderDebugInfo (`0x00227c48`) and `0x00224498`, which Think also
calls, are empty.

- **The replay test.** TimeBasedSpeech and SupervisorActivate return
  at once in RC states 4 (instant replay), 5 (automatic replay), 7
  (post-race) and 9 (the replay demo, tested out of line at
  `0x001369a8`).
- **TimeBasedSpeech.** With the speech manager playing, or no pursuit,
  TimeSinceLastSpeech goes to 0. Otherwise it counts up by
  WorldTimeElapsed. Once it is past MaxSpeechGapTime, the player's
  pursuit (FindPlayerPursuit) says its filler. That needs a pursuit,
  fSupervisorTimer not above 0, AboutToSaySomething false and
  NotInChasingState false. The count goes back to 0 either way, and
  after a filler SetNextSpeechFillerGap draws the next gap: 9 plus
  bRandom(3.0) on bDefaultSeed, 4 more in Be A Cop.
- **AboutToSaySomething** is true when any of these holds:
  fRoadBlockSpawnTimer is above 8; the pursuit is at LEVEL0; it is at
  LEVEL2 with fPursuitStateTimer under 13; the chased car's
  BlownTireBits (a signed byte) is nonzero; the pursuit's roadblock
  is under 150 from the car, on x and y alone; the chopper is
  CHOPPER_REQUESTED.
  **NotInChasingState** is SPEEDER_CAUGHT or END_PURSUIT_GIVE_UP.
- **SupervisorActivate.** A positive fSupervisorTimer counts down. The
  frame it reaches 0 or below, it is set to 0, and the first pursuit
  of a player's car that the supervisor can open (`0x0022aaf0`) gets
  SuperInitiates. Only one does.
- **PursuitManagement** runs each pursuit's Update (`0x00229288`) and
  deletes (`0x00224560`) any that says it is over. It takes the next
  link before the update.
- **FindPlayerPursuit.** In Be A Cop it is the player's cop's
  pMyPursuit, or NULL for index -1 or no cop. Otherwise it is the
  first pursuit whose chased car has a pPlayer.
- **MonitorPullovers.** Each active pullover not in its NIS counts
  fHoldTimer down by WorldTimeElapsed, and ends (EndPullover,
  `0x00225878`) while the timer is below 0.
- **ReclaimPatrollers.** Each of the nNumAICops cops asked for
  LS_DRIVING_ON_PATROL that is not within 250 of a player is sent to
  LS_LIMBO. The distance is World::GetDistanceToClosestPlayer's
  bVector2 form, `0x0014e3e8`.

Later slices port what Think reaches, and until then each is a seam
that does nothing (or returns 0) while NULL:

| what | address | seam | slice |
|------|---------|------|-------|
| tPursuit::Update | `0x00229288` | `gPursuitUpdateFn` | 12h |
| the supervisor's test | `0x0022aaf0` | `gPursuitCanSupervisorInitiateFn` | 12h |
| SuperInitiates, SayFillerSpeech | `0x0022b908`, `0x00231760` | `gPursuitSuperInitiatesFn`, `gSayFillerSpeechFn` | speech |
| the speech manager's previousSedPlaybackState | gp-15624 + 1452 | `gCopSpeechPlaybackStateFn` | 14-9, bound ([speechmgr](speechmgr.md)) |
| SpawnSpeedTraps | `0x00224a20` | `gCopManagerSpawnSpeedTrapsFn` | 12j-1, bound (below) |
| MonitorSpikeBelts | `0x00227758` | `gCopManagerMonitorSpikeBeltsFn` | 12j-2a, bound (below) |
| EndPullover | `0x00225878` | `gCopManagerEndPulloverFn` | 12l, bound ([pullover](pullover.md)) |
| BeACopThink | `0x00227f30` | `gCopManagerBeACopThinkFn` | 12m-2, bound ([cops](cops.md), "BeACopThink") |

tPursuit's fields from 1104 on are 380 bytes further on in retail than
in the demo; the chopper's state is 384 further on. `copmanager.h` has
PursuitState (1484), nHUDPursuitLevel (1492), fPursuitStateTimer
(1524), fRoadBlockSpawnTimer (1532) and ChopperState (1580).

## Radar traps (12j-1)

SpawnSpeedTraps (`0x00224a20`, `copmanager_spawn_speed_traps`) sends a
cop out of limbo to a radar trap ahead of a racer. `main.c` binds
`gCopManagerSpawnSpeedTrapsFn` to it, so Think runs it every frame
outside Be A Cop.

It counts the pursuits, then takes the racing cars in order. It passes
over a car that is NULL, has a FinishReason, or whose fPursuableTimer
is above 0 (or NaN). For each other car:

1. A fSpeedTrapSpawnTimer above 0 counts down by WorldTimeElapsed, and
   the car waits.
2. It rolls World::Random over the difficulty's range: 2, 1.5 or 1
   (`0x002bd180`). A roll above 1 loses, and the car waits 10, 5 or 1 s
   (`0x002bd170`). On the hardest level the roll never loses.
3. A car in a chase wants a trap when the chase has no cops, or has
   called for backup and has fewer than nMaxChaseCops.
4. A car not in a chase, with two or more chases on and no player, does
   not want one.
5. Any other car needs one of three things:
   - its split to the leader later than -15 s. The split comes from
     CalculateSplitTime, from 0. The -15 s is Timer::SetTime's packed
     -59999, compared signed;
   - the leader finished;
   - World::Random(20) returning 19.

   Without any of them, the car waits 1 s. With one, a free run or a
   player's car wants a trap. An AI racer wants one when its share of
   the arrest count is under its share of the race run:
   - the share of the arrest count is its tickets over
     nNumTicketsBeforeArrest + 1;
   - the share of the race run is FinishedLapNumberExact over the
     race's laps (1 for point to point).

A car that wants a trap takes the first AI cop in limbo and ready
(FindCopForSpeedTrap, `0x00224838`: desired LS_LIMBO, sub-state
LSS_LIMBO_READY). Then it takes the track graph's radar trap ahead
(FindSpeedTrap, 250 m to half the track's length, forward). If the trap
has no cop and IsTeleportLocationClear passes its spot, the cop's
SetSpeedTrap teleports it there and asks for LS_SPEED_TRAP
(`cops.md`). The car waits 20 s. SpawnSpeedTraps returns there, so it
places at most one trap a frame. Without a cop or a free trap, the
car's timer stays where it was, and it tries again on the next frame.

## Spike strips (12j-2a)

`spikestrip.c` has retail's tSpikeStrip (`0x00241308` to `0x00241ae0`)
and the two manager methods that drive it, AddSpikeStrip and
MonitorSpikeBelts. `worldobject.c` has the WorldObject they are built
from (`0x001cd760` to `0x001cd948`). `main.c` binds:

- `gCopManagerAddSpikeStripFn`, so a roadblock with bit 0x10 lays its
  strip (`pursuit.md`);
- `gSpikeStripBlinkBlinkPoofFn`, so DeleteRoadBlockSpikeStrips ends
  the strip when its roadblock goes;
- `gCopManagerMonitorSpikeBeltsFn`, so Think watches the strips;
- `gInitWorldObjectsFn` and `gCloseWorldObjectsFn`, so the track's load
  and unload make and empty WorldObjectSlotPool (128 objects of 96
  bytes).

**AddSpikeStrip** (`0x002276d0`) takes 2304 bytes from
SpikeStripSlotPool, builds the strip there and puts it at the head of
SpikeStripList. A roadblock passes its record's index and a lifetime of
-1, so its strip never runs out and stays until the roadblock goes.

**The strip.** Its layout is in `copmanager.h`: the links, the two ends,
the roadblock's id, the blink flag and timer, the lifetime, the count
and twenty belt pieces. Each piece (`0x002419f8`, 112 bytes) is a
WorldObject of the model SPIKEBELT_00 with a table after it. It is
built with no matrix, so it is off, and goes on WorldObjectList's tail.
The constructor (`0x00241378`) builds all twenty in order, then calls
Init (`0x002414e8`):

1. The id, the ends and the lifetime are stored. Each end is put on the
   road (GetVectorOnTrack).
2. The length is `sqrt((dx*dx + dy*dy) + dz*dz)`, the VU's order. The
   direction is the end less the start, times `1 / length` (the EE's
   divide).
3. The count is the length times 20/13 (`0x3fc4ec4f`), truncated: one
   piece for each 0.65. Above 20 it is 20.
4. The pieces run from 0.65 past the start, 0.65 apart. Each one's
   matrix has the rows: the direction, up x direction normalised (the
   side), direction x side, and the point with w 1. Each is turned on.

Ends that meet on the road divide by zero the EE's way (FLT_MAX), so
the direction is 0 and the count 0. Pieces past the count, the blink
flag and its timer are left as they were; the game's pool zero-fills.

**Update** (`0x002417b8`) returns nonzero when the strip is done:

- Blinking: the timer counts down by WorldTimeElapsed, each piece below
  the count is flipped on or off, and the strip is done once the timer
  is at or below 0.
- Otherwise a lifetime above 0 counts down, and at 0 or below
  BlinkBlinkPoof (`0x00241880`) starts the blink: the flag set, two
  seconds on the timer.

The destructor (`0x00241430`) runs the twenty pieces' destructors
through their tables, last first. Each takes its model back (flags 3)
and leaves WorldObjectList. With bit 0 the strip's slot goes back.

**MonitorSpikeBelts** (`0x00227758`) reads TotalNumCars once. Then for
each strip, the next one read first:

1. The strip's Update. A strip that is done is unlinked and destroyed
   through its table with 3.
2. Otherwise each car of the world's table is tested if it is within
   250 of a player (on the ground plane), not blinking, and within 40
   of the strip's middle.
3. For each wheel on the ground, the wheel's point is its WheelMatrix
   times the body's matrix with the position, row 3. Its move is the
   velocity times WorldTimeElapsed, x and y. If the move crosses the
   strip (DoSegmentsIntersect, `0x00230f00`), the wheel's bit is set.
4. If BlownTireBits holds all those bits, nothing happens. Otherwise
   Car::TriggerTireBlowOut blows them. A car with none blown before
   then reacts:
   - An AI racer, outside Be A Cop, is forced to pull over within 3 s,
     and its controller's ForceBoost gets 0.4. In Be A Cop ForceBoost
     gets 0.3, 0.4 or 0.5 by difficulty (`0x002bd238`).
   - Any other car with a player, above 20 forward, requests the short
     slow-motion zone (4, unforced, with the sound, muffled).
   - In Be A Cop, the player's own cop car is pulled over and scores
     BLEW YOUR TIRES; a racer being chased scores the player BLEW THE
     TIRES.
   - Outside it, a player's car or an AI racer that is not being chased
     is pulled over.

The pull-over is CreatePullover, `pursuit.h`'s seam, which `main.c`
binds since 12l ([pullover](pullover.md)).

**DoSegmentsIntersect** (`0x00230f00`, `coputil.c`) takes p, d, q and
e: the segments p to p + d and q to q + e. Two cross products tell which
side of p's line q and q + e lie; if their product is above 0 (or NaN),
the answer is 0. Then the same for p and p + d against q's line. So
segments on one line count as crossing even when apart, as retail's do.

The default constructor (`0x00241308`) and DoSnapshot (`0x00241898`)
are the replay's.

## Drawing the strips (12j-2b)

The pieces are drawn as WorldObjects. `worldobject.c` has Render
(`0x001cd998`) and RenderWorldObjects (`0x001cdb20`).

**RenderWorldObjects** walks WorldObjectList in order and renders each
object whose Enabled is not 0. It reads the next link after each.

**Render** draws nothing when:

1. the object is under 2 pixels across: GetPixelSize (`0x00107600`)
   of the matrix's position, with radius 20, is below 2;
2. eModel::IsVisible (`0x0010cea8`) fails. That needs a solid, and
   ClassifyAABB of the solid's box through the matrix times the
   *current* view's WorldScreenClipMatrix (not the view passed in)
   must not be 0.

Otherwise the matrix is copied into 64 bytes of frame memory and the
model is drawn there with flags 0:

- when AddLighting is 0, with no light context;
- otherwise with a 288-byte light context, also from frame memory. It
  is set up (elSetupLightContext) for the copy, the view's
  WorldViewMatrix and the eye: the camera's CurrentKey position, with
  w 1.

If either block fails, nothing draws. The light context's block is
taken after the matrix's, so it can fail alone.

**Where.** eDisplayFrame's per-view chain makes the view current
(`0x001131fc`), then runs:

1. StuffSun;
2. the clans, the debug draws and the camera movers;
3. the players;
4. RenderWorldObjects (`0x0011334c`);
5. the flailers, the light flares and the effects.

`trackview.c` matches that:

- `trackview_draw` sets the current view, then draws the world objects
  after StuffSun and before `render_effects`.
- `trackview_draw_mirror` does the same after the mirror's scenery,
  since the mirror has no sun.

**The model.** SPIKEBELT_00 is in INGAMEB.BUN's first solid list,
eLabInGame, with the markers, SMOKEBOMB, ROCKET, ROADBLOCK_BARREL, the
bush shakes and TICKETBOOK. The bundle has two more lists, of drivers.
The port had only loaded INGAMEB's texture packs.

`load_shared_packs` now offers its other chunks to LoaderSolidList.
The loader moves each strip's data pointer by where the data sits, so
loading a second time would move it again. INGAMEB stays resident, so
the lists are loaded once, with the first track, and stay. Each track's
eFixUpTables points their texture tables at its packs again.

A test build laid three strips ahead of the player in Azahar. The log
read "world objects 60 (45 on), spike strips 3". The red and white
belts lay across the road and the spikes stood upright. 30 FPS held.
The one hitch in that run was the minimap's textures uploading, not the
belts. `main.c`'s race log now counts the world objects (and how many
are on) and the strips.

## The check

`tools/copmanager_check.py` runs retail's code in mipsemu and the port
(`copmgr.c`, and `cop.c`, which it now needs to link) in
`tools/src/copmanager_test.c` on 2291 operations: every track's cop
chunks through the loader, the constructor at each strength, Be A Cop
on and off, the spots' tables, the speaker queue, the pursuit ids and
deletions, the destructor, and the hits on six cars (AI cops, a player
cop, a racer, an AI car) in both branches, with two-car collisions and
amounts at each threshold.

12f adds Think and what it runs:

- every AboutToSaySomething branch at its boundaries, with NaN and the
  infinities;
- FindPlayerPursuit both ways;
- TimeBasedSpeech in each RC state, with the speech manager busy and
  each reason not to speak;
- SupervisorActivate's timer and its first-eligible pursuit;
- PursuitManagement deleting some pursuits, then all;
- eight pullovers;
- ReclaimPatrollers around 250;
- Think with Be A Cop on and off, the race clock signed, and the
  pursuable timers;
- GlobalCopThink on the made chunk whose landmarks L1 and L3 uncloak.

12j-1 adds SpawnSpeedTraps and FindCopForSpeedTrap:

- FindCopForSpeedTrap over each cop's logic states;
- the cars passed over;
- the spawn timer, and the roll at each difficulty;
- the split one packed tick either side of -59999, the leader finished,
  and Random(20);
- a free run (with odd values), a player's car, and an AI racer's grid
  of tickets and laps;
- the chases' cops and backup, with one, two and three chases;
- a cop or trap missing, a trap taken, the spot not clear, and the next
  car getting the trap;
- Think with the real SpawnSpeedTraps;
- a fuzz of 300 per number of chases, from seed 12101.

World::Random's two forms take queued answers on both sides. The split,
the free run, FindSpeedTrap and IsTeleportLocationClear are stand-ins
that print their arguments. SetSpeedTrap and FindCopForSpeedTrap run
for real, and the cars' moves and resets print.

The cops' Think, the pursuits' Update and the other seams are logging
stand-ins on both sides. 87402 operations, 33602 lines, 0 differ.

`--mutate` runs out of the tree through `mutpar`: 363 mutations, 358
caught, and five equivalent:

- One turns the AI branch's `!(table <= amount)` into `table > amount`.
  That differs only for NaN, and AddDamage never passes MonitorImpact
  an amount under 1.0.
- Two are a NaN timer less the frame's seconds: it is the same NaN,
  stored back (fSupervisorTimer, fPursuableTimer).
- One clamps a pursuable timer at `<= 0`: a timer above 0, less the
  frame's seconds, is never -0.0.
- One starts SpawnSpeedTraps's split at 1, not 0. The split is only
  compared with -15 s (-59999 packed), which is below both.

Two mutations had gone stale since 12h-1 renamed `replaying` to
`copmanager_replaying`, so their patterns were not found. 12j-1 fixed
them, and both are caught.

The checkers that link `copmgr.c`, `copmanager.c` or
`carcollisionbody.c` still have 0 differ: carmode, collisionbody,
drivecam, drivingchoice, hudanim, hudfeatures, hudrender, nearbycar,
realcontroller, realdriver and trackmap.

### The spike strips' check (12j-2a)

`tools/spikestrip_check.py` runs retail's strip, its pieces,
WorldObject, InitWorldObjects and CloseWorldObjects, AddSpikeStrip and
MonitorSpikeBelts in mipsemu. The port runs in
`tools/src/spikestrip_test.c`, which links `spikestrip.c`,
`worldobject.c` and `vtable.c`.

The stand-ins log and answer by the same rule on both sides:

- the slot pools, with a fill byte the script sets;
- eModel's Init and destructor;
- GetVectorOnTrack, from a queue or a rule;
- the distance to the closest player, IsBlinking, eMulMatrix and
  DoSegmentsIntersect, from a queue;
- TriggerTireBlowOut, RequestZone, StartScore, IsBeingPursued and
  CreatePullover;
- a controller table whose ForceBoost logs.

ForcePullOver and bStringHash run as shipped. The script covers:

- world objects built with and without a matrix, destroyed with each
  flag, and the pool made and emptied;
- sixteen strips laid over geometry chosen for the count's rounding,
  the 20 cap, ends that meet, belts straight up and straight down, and
  lengths whose sum rounds by its order;
- two strips from a pool that was not zero-filled;
- lifetimes of 0, below 0, NaN, infinite and tiny, through the blink
  to the end;
- every MonitorSpikeBelts filter at its boundary, each wheel, bits
  already blown, and each reaction in and out of Be A Cop at each
  difficulty.

638 operations, 3193 lines, 0 differ. `--mutate`: 116 mutations, 115
caught, one equivalent. That one divides the plain way: it differs from
the EE's divide only for a zero length, where the count is 0 either way.

12j-2b adds Render and RenderWorldObjects. Five more stand-ins, logged
and answered the same way:

- GetPixelSize, from a queue;
- eGetCurrentView;
- ClassifyAABB, from a queue;
- elSetupLightContext;
- eModel::Render.

The script gives each side two views with cameras, world-view and clip
matrices, four solids and a 4 KB frame arena, then covers:

- unlit and lit objects (AddLighting 1 and -3), and one with no solid;
- pixel sizes at 1, 2, -5, 0, 3, INT_MAX and INT_MIN;
- ClassifyAABB answering 0, 1, 2 and -1;
- the current view not the one drawn;
- frame memory with room for neither block, one or both, at each
  boundary, with the fail amount wrapping;
- RenderWorldObjects over objects with Enabled 0, 2, -1 and 1.

742 operations, 6337 lines, 0 differ. 32 more mutations, all caught.

DoSegmentsIntersect is a stand-in there and is checked on its own in
`tools/trackgraph_check.py`. Segments are crossed, touched at an end,
laid end to end, along one line and side by side, and made tiny,
infinite and NaN, each both ways round. 240 more are set a rounding off
the other's line, and 250 are random. 326426 operations, 246557 lines, 0 differ. Its 20
mutations are all caught, including a double-width product (an
underflow to 0) and the NaN branch on each side.
