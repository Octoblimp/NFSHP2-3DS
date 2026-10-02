# `RaceCoordinator::InitCars` and `InitPlayers` -- the grid

`RaceCoordinator::InitForRace` (`0x00149988`, step 8d) builds the World
and then hands it its cars. `InitCars` puts the racers on the grid in
starting order and gives the AI racers their first route. Then it adds
the traffic, the cops and the helicopter. `InitPlayers` hands each
`Player` the car it drives. Neither reads the `RaceCoordinator` itself.
Everything they need is in `TheRaceParameters` and the World.

The port is `3DS Files/source/raceinit.c`/`raceinit.h`. Everything there
is retail's. `race.c` adds the driver array and `GetDriverInfo`, and
`car.h`'s `DriverInfo` gains retail's rank byte. `tools/raceinit_check.py`
runs the retail image itself in RetailEmu as the oracle: 32 scenarios,
3280 ops, 13317 transcript lines, 0 differ. All 123 of its mutations are
caught, five of them by crashing the harness. Before the run it compiles
`car.h` and `raceinit.h` with devkitARM and asserts `DriverInfo`'s and
`RacerStartLocation`'s layout.

## Where things are

| retail | what |
|--------|------|
| `0x0014a2c8` | `RaceCoordinator::InitCars`, 808 bytes |
| `0x00149cb8` | `RaceCoordinator::InitPlayers`, 188 bytes |
| `0x00149f10` | `AddRacingCar(DriverInfo *, RacerStartLocation *, ControlMode)`, 272 bytes |
| `0x0014a020` | `CalculateRacerPositions(int, RacerStartLocation *)`, 680 bytes |
| `0x001edb28` | `RaceParameters::GetDriverInfo(int)` |
| `0x0031a898` | `TheRaceParameters` |
| `0x00314438` | `TheTrackRouteManager`, its routes at +16 + 4n |
| `0x002af898` | `"ForwardStartingPosition"` |
| `0x002af8b0` | `"BackwardStartingPosition"` |
| `0x0031d7f4` | the egg table's pointer (below) |
| gp-22120 | `pCurrentWorld` (world.h's gp-22624 is the demo's) |
| gp-22960 | `nDefaultMovementMode`, 4 (`MELLOW_MOVEMENT`) in .sdata |
| gp-20920 | `Player::NumPlayers` |
| gp-20928 | `Player::pPlayersByIndex[2]` |

The `TheRaceParameters` words read here:

| offset | what |
|--------|------|
| +0 | `TrackNumber` |
| +12 | `TrackDirection`, 0 forward |
| +24 | `AIDemoMode` |
| +628 | `BeACop` |
| +772 | the `DriverInfo` array (the demo's was at +756) |
| +776 | `NumDriverInfo` |

These callees are ported already: `Car`'s constructor (`car_construct`,
[car.md](car.md)), `SetControlMode` and `SetMovementMode`, World's
`BuildCarTable`, `GetCarByNumber` and `AddTrafficCar`, the two
`TrackPathCoordinate` constructors and `UpdatePosition`, the
`TopologyCoordinate` and `GetElevation` ([topology.md](topology.md)), the
track's position markers and `GetTrackInfo`,
`NearestRoutePointInfo::IsValid` (`0x001cd408`), `bATan`, and
`Player::InitForRace` ([player.md](player.md)).

The seams, NULL until their classes are ported:

| retail | what |
|--------|------|
| `0x00227d78` | `AddCopCarToRace(DriverInfo *, bool)`, `gAddCopCarToRaceFn` |
| `0x001e7a90` | `Chopper::Chopper()` on `bMalloc(976)`, `gChopperCtorFn` |
| the egg table | `gEggIsOnFn` |

With `gAddCopCarToRaceFn` NULL no cop is added, but each cop driver still
counts towards the helicopter and the Be A Cop call. With
`gChopperCtorFn` NULL there is no helicopter, and nothing is allocated for
one. With `gEggIsOnFn` NULL every egg reads 0.

## `DriverInfo`, 24 bytes

`GetDriverInfo` indexes the array at +772 by 24. The demo's record was 20
bytes. The port keeps the demo's fields where they were and adds retail's
new byte at the end, so the record is 24 bytes here too, but its fields
are not at retail's offsets.

| retail | port | what |
|--------|------|------|
| byte 0 | byte 20 | `EliminatedRank`, new. Above 0, InitCars and InitForRace skip the driver |
| byte 1 | byte 0 | `UniqueDriverNumber`, what `GetCarByNumber` and `GetDriverInfoByDriverNumber` match |
| byte 4 | byte 3 | `StartingPosition`, signed (`lb`) |
| word 8 | word 4 | `TheDriverType`: 1 player, 2 AI racer, 3 traffic, 4 cop, 5 super cop |

`CharacterNumber` and `SkillLevel` are retail's bytes 2 and 3, the
port's 1 and 2. Everything reads these by name, so nothing is owed until
a record is read in place. `0x001edbc8` sets the rank from
`EventKoState::GetRank` as `SetupCarsForRace` builds the next round.

## `CalculateRacerPositions(n, locs)`

A `RacerStartLocation` is 16 bytes (.mdebug type#5600): one `bVector3`.
The function writes x, y and z of slots 0 to n-1, and never the fourth
lane. It works in three steps.

1. **The markers.** It hashes `"ForwardStartingPosition"` when
   `TrackDirection` is 0, and `"BackwardStartingPosition"` otherwise. When
   the track has at least n markers of that name, slot i takes x and y
   from the first marker whose `Param` (word 12) is i, at +16 and +20. One
   slot with no such marker spoils the lot. The slots before it are
   written over in step 2.
2. **The fallback**, when the markers are spoiled or too few. A
   `TrackPathCoordinate` built with no position steps along the path with
   `UpdatePosition(d, 0)` for d = 10, 20 and so on to 100. Then slot i
   takes x and y from the coordinate after `UpdatePosition(100 + 17 *
   (i / 2), side)`. The side is 3 for an even i and -3 for an odd one.
3. **The heights.** One `TopologyCoordinate` serves every slot. Each slot's
   z is first set to the height of the slot before (0 for slot 0), and
   then to `GetElevation` at the slot, with no terrain, normal or found
   flag asked for. The coordinate is destroyed at the end.

## `AddRacingCar(info, loc, mode)`

1. It builds a `TrackPathCoordinate` at `loc`'s x and y (`0x002086f0`).
2. The heading is `bATan` of the coordinate's path direction, x then y,
   as an unsigned short.
3. The car is `Car(bMalloc(2208, "Car", 0, 16), info, &loc->Position,
   heading, DistanceAroundTrack)`. Then `SetControlMode(mode)`.
4. `SetMovementMode` takes `nDefaultMovementMode` for an AI racer
   (`AI_CONTROL`, 2) and `PHYSICS_MOVEMENT` (1) for anything else.
5. The car goes on the end of World's `CarList`.
6. An AI racer also goes on the end of `AICarList`, through a `bPNode`
   (`0x00250680`) with the car at +8.
7. The coordinate's destructor is a bare flag test: nothing to port.

The port allocates `sizeof(Car)`, which is 2192, not 2208 (car.md).

## `InitCars`

1. `CalculateRacerPositions(8, locs)` into eight slots on the stack.
2. **The racers.** For each position from 1 to 8, it takes the first
   driver whose `EliminatedRank` is 0 or below and whose
   `StartingPosition` is that position. A player gets
   `AddRacingCar(info, &locs[position - 1], REAL_CONTROL)` and an AI racer
   the same with `AI_CONTROL`. A driver of any other type takes the
   position and adds nothing. So does a position no driver has.
3. `BuildCarTable`.
4. **The AI racers' first route.** When `GetTrackInfo(TrackNumber)`'s
   `OverrideStartingRouteForAI` (word 124) is 0 or above, the start is
   that route of `TheTrackRouteManager`, at its first point (the route
   +1064). Then for each car from `CarTable[AICarPos]` up to
   `CopCarPos`, it takes the car's controller (+40):
   - For the first car, when the start fails `IsValid`, it makes three
     virtual calls: `FindWhereIAm` (slot +76), then `GetCurrentRoute(1)`
     (+52) and `GetCurrentRoutePoint(1)` (+60). Their answers become the
     start. That car is given no route.
   - Every other car, and the first one when the start is valid, gets
     `SetCurrentRoute(route, point)` (+44).

   Retail's `GetCurrentRoute` and `GetCurrentRoutePoint` take a flag the
   demo's do not. `AICarController`'s runs `FindWhereIAm` first when the
   flag is set and its driving location is clear.
5. **The traffic and the cops**, from every driver, knocked out or not.
   Traffic goes to `AddTrafficCar`. A cop or a super cop is counted, and
   goes to `AddCopCarToRace(info, 0)`. Then `BuildCarTable` again.
6. **The helicopter.** When there were cops, or egg 5 is on, it is
   `Chopper(bMalloc(976, "Chopper", 0, 16))` into World's `Helicopter`
   (+24).
7. With cops and `BeACop`, it calls `AddCopCarToRace(NULL, 1)`.

### The egg table

The egg is the word at +48 + 56n of the table at `*(0x0031d7f4)`. That is
the word at +12 of a retail object at `0x0031d7e8`, which the demo does
not have. Only readers turn up, and they look like Easter eggs:

- n = 0 and 1: `RandomRenderEgg`'s neighbour
- n = 4: `Player`
- n = 5: `InitCars` and `Chopper`'s constructor, which sets its own word
  960 then
- n = 6 and 7: `EventInfo::GetStatus`

## `InitPlayers`

For each player by index:
- With `AIDemoMode`, the car is World's `CarTable[AICarPos +
  PlayerNumber]`, unchecked.
- Otherwise it is `GetCarByNumber(PlayerNumber)`, and a player with no car
  is skipped.

Then `Player::InitForRace` on that car.

## Where the port differs

None of these can be seen in the transcript:
- Retail leaves the start route unset when the track has no override, and
  `IsValid` reads whatever is on the stack. The port zeroes it, and
  `IsValid` fails on it. The checker's model zeroes the emulator's stack
  before each call, so the two agree.
- Retail leaves the slots' fourth lanes unset. The port zeroes them.
- With an override that names a NULL route, retail's point is 1064. The
  port's is NULL.
- `GetTrackInfo`'s answer is read unchecked in both.

## Seams wired in main.c

`main.c` now sets `gCarInitRenderInfoFn` to `car_init_render_info` and
`gCarRenderInfoDestroyFn` to `carrenderinfo_delete`, after making the two
slot pools `carrenderinfo_init_slot_pools` makes. So a car `InitCars`
builds gets its render info. The sound, `CarDamage` and the event
manager's seams stay NULL until they are ported.

## The checker

`tools/raceinit_check.py` runs the four functions in RetailEmu against
`tools/src/raceinit_test.c`. Every callee is a stub on both sides, and
each answer is a hash of its arguments, so a wrong argument shows up in
what follows it. The stubs print what they are called with, and after
each call the harness prints the World's two lists, its car table and
helicopter, and the nine slots.

- C: `CalculateRacerPositions` on a buffer of nine, with markers, a
  direction and n from -1 to 8.
- A: `AddRacingCar` with each control mode.
- I: `InitCars` on drivers of every type, rank and position, with and
  without an override, cops, the egg and the seams.
- J: `InitPlayers` with none, one or two players, with and without
  `AIDemoMode`.

The `CarController`'s fake vtable gives `SetCurrentRoute` and
`GetCurrentRoutePoint` a this-delta of 4, so a call that skips the
adjustment is caught. The other two slots have a delta of 0, so dropping
their adjustment cannot be seen, and the mutations leave them alone.
