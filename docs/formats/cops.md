# The cops (step 12b on)

The cops themselves are retail's cop.obj, `0x0022d3f8` on: tCop, the
base, and its two kinds, tPlayerCop (Be A Cop's, on the player's own
car) and tAICop (its own car, which a CopDriver drives). The manager
that holds them is `cop-manager.md`'s. Slice 12b ports the records, the
constructors and destructors, the small setters, the zone permissions
and DisableMyCar, and the manager's CreateCop and AddCopCarToRace.
Think, DoSnapshot and the pursuit logic are the later slices.

| function | address | port |
|----------|---------|------|
| tCop::tCop(int) | `0x0022d3f8` | `tcop_construct` |
| tCop::~tCop | `0x0022d418` | `tcop_destruct` |
| tCop::SetPursuit | `0x0022d530` | `tcop_set_pursuit` |
| tCop::SetDesiredLogicState | `0x0022d538` | `tcop_set_desired_logic_state` |
| tCop::SetDesiredLogicSubState | `0x0022d540` | `tcop_set_desired_logic_sub_state` |
| tPlayerCop::tPlayerCop(Car *, int) | `0x0022d548` | `tplayercop_construct` |
| tPlayerCop::~tPlayerCop | `0x0022d5b0` | `tplayercop_destruct` |
| tAICop::tAICop(DriverInfo *, int) | `0x0022db20` | `taicop_construct` |
| tAICop::~tAICop | `0x0022dcc0` | `taicop_destruct` |
| tAICop::operator new | `0x00230d78` | `taicop_new` |
| tAICop::operator delete | `0x00230d68` | `taicop_delete` |
| tAICop::ClearPursuit | `0x0022e510` | `taicop_clear_pursuit` |
| tAICop::ClearSpeedTrap | `0x0022e558` | `taicop_clear_speed_trap` |
| tAICop::DisableMyCar(bool) | `0x00230ac8` | `taicop_disable_my_car` |
| tAICop::IsAIControlled | `0x00230d60` | 1, in the table |
| tPlayerCop::IsAIControlled | `0x00230d98` | 0, in the table |
| InitZonePermissionTable | `0x0022f770` | `init_zone_permission_table` |
| RequestZonePermission | `0x0022f810` | `request_zone_permission` |
| GetZoneFromSubState | `0x0022f850` | `get_zone_from_sub_state` |
| tCopManager::CreateCop | `0x002272e8` | `copmanager_create_cop` |
| (new) the cop cars' largest size | `0x002276a0` | `copmanager_calculate_max_cop_car_dimensions` |
| AddCopCarToRace | `0x00227d78` | `copmgr_add_cop_car_to_race` |

The cop.obj functions are in `cop.c`, declared in `cop.h`; the three
manager ones are in `copmgr.c`. `copdriver.h` has CopDriver's record
for 12d, and CopMover, the mover a cop car rides away from the players
(12c, `copdriver.c`; see [cop-mover.md](cop-mover.md)).

## The records

| record | size | where |
|--------|-----:|-------|
| tCop | 32 | `copmanager.h`: the pursuit, the car, the number, the logic states and sub-states, the vptr at 28 |
| tPlayerCop | 52 | tCop, the two previous selections and their timers, the cop lights' last state |
| tAICop | 96 | tCop, then the grace timer (32), the radar trap (36), the roadblock (40), the sub-state's timer (44), the driving line's offset (56), the flank side (72), the route point (76), the time in physics mode (84), the mode switch's delay (88) and the driving line (92) |
| CopDriver | 76 | a TrackedController (36), the state, the sub-state, the stuck and backing-up timers, the patrol speed, the cop's number, the steering target and the car class |

The demo's tAICop is 76 bytes (`.mdebug` t1614). Retail added the
grace timer at 32, the two words at 48 and the two at 64 (6 and 3 from
the constructor). Each record has a compile-time check of its offsets on
a 32-bit target.

The tables: tCop's at `0x002bd6e8`, tPlayerCop's at `0x002bd6c0` and
tAICop's at `0x002bd698`. Slot 8 is the destructor, 16 IsAIControlled,
24 Think and 32 DoSnapshot. tCop's last three are `__pure_virtual`.
Think and DoSnapshot abort as not ported until 12f and 12g.

## Making the cops

Race setup (`raceinit.c`) calls AddCopCarToRace once for each cop in
the race's driver list, then once more with Be A Cop, after the car
table is built. AddCopCarToRace does nothing unless `nMaxCops` is above
0. Otherwise it calls CreateCop, then `0x002276a0`.

CreateCop:

- **An AI cop.** A tAICop out of CopSlotPool (96-byte slots), built
  for the driver as cop number `nNumAICops`, into `Cops[nNumAICops]`.
  `nNumAICops` goes up.
- **Be A Cop.** A tPlayerCop (`bMalloc(52, 16)`, which has no name; the
  port names it for its diagnostics) on `CarTable[0]`, the player's car.
  It goes into `Cops[nNumAICops]` and `nPlayerCopIndex` takes that
  index, but `nNumAICops` stays, so an AI cop made after it would
  overwrite it. Race setup makes it last. The player's car then goes to
  the first radar trap flagged for the race's direction (bit 0 forward,
  bit 1 reversed), facing the trap's angle less 32000, at speed 0, if
  any trap has the flag.
- Either way `nNumCops` goes up.

`0x002276a0` sets `fMaxCopCarXdim` and `fMaxCopCarYdim` to `Cops[0]`'s
car's width and length by 1.1. Each call reads the first cop's car, so
the values are set by the first cop and kept.

tAICop's constructor, in retail's order:

1. tCop's: the number, no pursuit, LS_INVALID. Then roadblock 0, no
   route point, the sub-state's timer 0, and tAICop's table.
2. The car: `bMalloc(2208, "Car (cop)", 0, CAR_MEMORY_POOL)`, built
   for the driver at the origin, angle 0, distance -1. It goes on the end
   of the world's CarList.
3. The weight. The car type's mass goes to `fCopMassTable[level]`
   (`0x0031c5b8`: 1.5, 1.75, 2.0), and the inertia's first three rows
   are scaled with it, all four lanes. The scale is `table / mass`, and
   the mass is stored as `mass x scale`, so it can land one bit off the
   table. The type is shared, so a second cop of the same type scales
   by about 1.
4. COP_CONTROL, which makes a CopDriver. The driver is parked and takes
   the cop's number.
5. No mover (eNO_MOVEMENT), and the car isn't drawn.
6. LS_LIMBO asked for; the time in physics mode, the two words at 48,
   the driving line's offset, the flank side, the mode switch's delay and
   the driving line all 0; 6 and 3 at 64 and 68.
7. The car off the track map, its siren off, and its cop lights off
   (retail stores a word at 2056).
8. The zone table filled afresh, and the grace timer 0.

`pMySpeedTrap` and the logic sub-states are left as they were.

The destructors: tCop's frees the record with bit 0 of its flags.
tPlayerCop's passes its flags to tCop's. tAICop's calls tCop's with 0,
then hands the slot back to CopSlotPool with bit 0. Neither frees the
car, which the world owns.

## DisableMyCar

tAICop::DisableMyCar(b), which MonitorImpact calls through
`gAICopDisableMyCarFn` when a hard hit lands on an AI cop's car:

1. Nothing in LS_LIMBO or LS_DISABLED.
2. The car's damage wrecked, if it has a CarDamage (`0x001b5bc8`, all
   32 parts by 1.0).
3. With no pursuit, LS_DISABLED is asked for and that is all.
4. If the chased car is a player's and within 75 m, the pursuit's
   primary speaker is removed with `b`, which can move the cop to
   another pursuit. Retail reads the chased car with no NULL test.
5. If the pursuit's chased car is a player's, that player's radar traps
   wait 10 s longer (`fSpeedTrapSpawnTimer[CarIndex]`).
6. ClearPursuit, then LS_DISABLED asked for.

ClearPursuit calls tPursuit::RemoveCopFromPursuit and sets the pursuit
to NULL. ClearSpeedTrap clears the trap's cop and the cop's trap.

## The zones

The cops share the space around a suspect in six zones. The table
(`nZonePermissionTable`, `0x0031c5c8`) is six by six;
`RequestZonePermission(a, b)` reads `[b][a]`, and zone 6 is always
allowed. InitZonePermissionTable fills it:

| b \ a | 0 | 1 | 2 | 3 | 4 | 5 |
|------:|---|---|---|---|---|---|
| 0 | 0 | 0 | 0 | 0 | 1 | 0 |
| 1 | 1 | 0 | 1 | 0 | 1 | 1 |
| 2 | 1 | 1 | 0 | 1 | 1 | 0 |
| 3 | 1 | 0 | 1 | 0 | 1 | 1 |
| 4 | 1 | 1 | 1 | 1 | 0 | 1 |
| 5 | 1 | 1 | 0 | 1 | 1 | 0 |

GetZoneFromSubState gives a pursuit sub-state's zone: low-speed close
follow 4; follow backwards 3, or 5 when `side` is not below 0; block,
get ahead and stop 1, or 2; acquire 0; the rest 6.

## Seams

Not ported yet, so NULL, and each aborts where retail would call it:
tPursuit::RemoveCopFromPursuit (`gPursuitRemoveCopFromPursuitFn`) and
RemovePrimarySpeaker (`gPursuitRemovePrimarySpeakerFn`), 12h and 12i;
CarDamage's wreck (`gCarDamageWreckFn`), which no car reaches while
CarDamage isn't built.

`main.c` binds `gAICopDisableMyCarFn` to `cop_disable_my_car`, and
`gCopMoverCtorFn` (COP_MOVEMENT's mover, 12c). It does not bind
`gAddCopCarToRaceFn` yet: COP_CONTROL needs CopDriver's constructor
(12d), and a cop on the road needs Think. Until then race
setup passes the cops over, as it did before.

## The check

`tools/cop_check.py` runs retail's code in mipsemu and the port in
`tools/src/cop_test.c` on 1012 operations:

- the zones: the table, every request in 0..6 both ways, on a garbled
  table, and every sub-state with eight sides (NaN, -0 and the
  infinities among them);
- AddCopCarToRace at each strength on four car types, with no cops
  allowed, and CreateCop on its own with a NULL driver;
- Be A Cop in four directions on six sets of radar traps, after AI
  cops, and as the first cop;
- each constructor and destructor alone, through the tables;
- the setters, ClearPursuit and ClearSpeedTrap;
- DisableMyCar in every logic state, with and without damage, near and
  far at the 75 m edge from both sides, on players' and AI cars, and
  with RemovePrimarySpeaker moving the cop.

2565 lines, 0 differ. `--mutate`: 139 mutations, 138 caught, and one
equivalent: tAICop's destructor storing its own table, which tCop's
overwrites straight after.

`copmanager_check` now links `cop.c` too (23342 lines, 0 differ), and
carmode, collisionbody, drivecam, drivingchoice, hudanim, hudfeatures,
hudrender, nearbycar, realcontroller, realdriver, trackmap, raceupdate,
hudcop, hudscore and aidriver still have 0 differ.
