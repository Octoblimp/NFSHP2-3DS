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
   AllocateVoices and FlushQueue (seams, NULL until the speech is
   ported);
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

## The check

`tools/copmanager_check.py` runs retail's code in mipsemu and the port
(`copmgr.c`, and `cop.c`, which it now needs to link) in
`tools/src/copmanager_test.c` on 2291 operations: every track's cop
chunks through the loader, the constructor at each strength, Be A Cop
on and off, the spots' tables, the speaker queue, the pursuit ids and
deletions, the destructor, and the hits on six cars (AI cops, a player
cop, a racer, an AI car) in both branches, with two-car collisions and
amounts at each threshold. 23342 lines, 0 differ.

`--mutate` runs out of the tree through `mutpar`: 156 mutations, 155
caught, and one equivalent. That one turns the AI branch's
`!(table <= amount)` into `table > amount`, which differs only for NaN,
and AddDamage never passes MonitorImpact an amount under 1.0.

The checkers that link `copmgr.c`, `copmanager.c` or
`carcollisionbody.c` still have 0 differ: carmode, collisionbody,
drivecam, drivingchoice, hudanim, hudfeatures, hudrender, nearbycar,
realcontroller, realdriver and trackmap.
