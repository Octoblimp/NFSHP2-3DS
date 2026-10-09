# The cops (step 12b on)

The cops themselves are retail's cop.obj, `0x0022d3f8` on: tCop, the
base, and its two kinds, tPlayerCop (Be A Cop's, on the player's own
car) and tAICop (its own car, which a CopDriver drives). The manager
that holds them is `cop-manager.md`'s. Slice 12b ports the records, the
constructors and destructors, the small setters, the zone permissions
and DisableMyCar, and the manager's CreateCop and AddCopCarToRace.
Slice 12d adds tAICop's drive target, which CopDriver steers along.
Slice 12g-1 adds tAICop's Think: its state changes, its movement modes,
and the logic of the three states that hold still (limbo, disabled and
guarding a place), with the manager's ResetAllDamage. Slice 12g-2 adds
the radar traps', roadblocks' and patrols' logic, with the moves that put
a cop on its spot and the tests for whom it chases, and two more of
`coputil.obj`. The hot pursuit and caught speeder logics, DoSnapshot and
the pursuits are the later slices.

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
| tAICop::IsNearPursuitTarget | `0x00230bf8` | `taicop_is_near_pursuit_target` |
| tAICop::InitializeDriveTarget | `0x00230638` | `taicop_initialize_drive_target` |
| tAICop::UpdateDriveTarget | `0x002307d0` | `taicop_update_drive_target` |
| tAICop::IsAIControlled | `0x00230d60` | 1, in the table |
| tPlayerCop::IsAIControlled | `0x00230d98` | 0, in the table |
| InitZonePermissionTable | `0x0022f770` | `init_zone_permission_table` |
| RequestZonePermission | `0x0022f810` | `request_zone_permission` |
| GetZoneFromSubState | `0x0022f850` | `get_zone_from_sub_state` |
| tCopManager::CreateCop | `0x002272e8` | `copmanager_create_cop` |
| (new) the cop cars' largest size | `0x002276a0` | `copmanager_calculate_max_cop_car_dimensions` |
| AddCopCarToRace | `0x00227d78` | `copmgr_add_cop_car_to_race` |
| tAICop::Think | `0x0022df88` | `taicop_think`, in the table |
| tAICop::HandleStateTransitions | `0x0022e1f0` | `taicop_handle_state_transitions` |
| tAICop::MovementModeTransitions | `0x0022e578` | `taicop_movement_mode_transitions` |
| (new) hold position | `0x00230a60` | `taicop_hold_position` |
| tAICop::DoLimboLogic | `0x00230570` | `taicop_do_limbo_logic` |
| tAICop::DoDisabledLogic | `0x002305c8` | `taicop_do_disabled_logic` |
| tAICop::DoGuardLocationLogic | `0x00230bf0` | `taicop_do_guard_location_logic` |
| tPlayerCop::Think | `0x0022d5c8` | the seam `gPlayerCopThinkFn`, in the table |
| ResetAllDamage | `0x00228750` | `copmanager_reset_all_damage` |
| Car::GetNumWheelsOnGround | `0x001cad80` | `num_wheels_on_ground`, static in `cop.c` |
| tAICop::Teleport | `0x0022de70` | `taicop_teleport` |
| tAICop::SetSpeedTrap | `0x0022ded8` | `taicop_set_speed_trap` |
| tAICop::SetRoadBlock | `0x0022df18` | `taicop_set_road_block` |
| tAICop::InitSpeedTrapLogic | `0x0022e798` | `taicop_init_speed_trap_logic` |
| tAICop::DoSpeedTrapLogic | `0x0022e838` | `taicop_do_speed_trap_logic` |
| tAICop::IsValidPursuitTarget | `0x0022ea88` | `taicop_is_valid_pursuit_target` |
| tAICop::InitRoadBlockLogic | `0x0022ebc0` | `taicop_init_road_block_logic` |
| tAICop::DoRoadBlockLogic | `0x0022ec38` | `taicop_do_road_block_logic` |
| tAICop::CanPatrollerSeeThisCar | `0x0022ed68` | `taicop_can_patroller_see_this_car` |
| tAICop::DoDrivingOnPatrolLogic | `0x0022ee50` | `taicop_do_driving_on_patrol_logic` |
| CanTeleport | `0x00230ff0` | `can_teleport`, in `coputil.c` |
| CarCausedRecentCollision | `0x00231118` | `car_caused_recent_collision`, in `coputil.c` |

The cop.obj functions are in `cop.c`, declared in `cop.h`; the three
manager ones are in `copmgr.c`. `copdriver.c` has CopDriver, the
controller an AI cop's car gets (12d; see [cop-driver.md](cop-driver.md)),
and CopMover, the mover a cop car rides away from the players (12c; see
[cop-mover.md](cop-mover.md)).

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

**The sub-states.** The demo's `.mdebug` (L52663) lists NONE, then
PURSUIT_FOLLOW at 1 through CAUGHTSPEEDER_WAITING at 14. Retail has
two more values at 1 and 2, so every name after NONE is two higher:

| value | name |
|------:|------|
| 0 | NONE |
| 1 | not named yet |
| 2 | PATROL_ONCOMING: patrolling on a route against the traffic |
| 3 | PURSUIT_FOLLOW |
| 4 | FOLLOW_OFFSET |
| 5 | LOW_SPEED_CLOSE_FOLLOW |
| 6 | FOLLOW_BACKWARDS |
| 7 | FLANK |
| 8 | BUMP |
| 9 | BLOCK |
| 10 | GET_AHEAD |
| 11 | ACQUIRE |
| 12 | STOP |
| 13 | LIMBO_DISABLED |
| 14 | LIMBO_READY |
| 15 | CAUGHTSPEEDER_TICKETING |
| 16 | CAUGHTSPEEDER_WAITING |

The evidence: DoHotPursuitLogic (0x0022ff58) jumps through a table at
0x002bd670 by sub-state - 3, and its entries are the pursuit logics in
the enum's order, DoPursuitFollowLogic first and DoPursuitStopLogic
tenth. HandleStateTransitions enters limbo with 13 (from DISABLED) or 14,
and a caught speeder with 15. Patrol's InitializeDriveTarget takes the
oncoming routes in 2. Every value in the port was checked against
retail; only the names moved.

The tables: tCop's at `0x002bd6e8`, tPlayerCop's at `0x002bd6c0` and
tAICop's at `0x002bd698`. Slot 8 is the destructor, 16 IsAIControlled,
24 Think and 32 DoSnapshot. tCop's last three are `__pure_virtual`.
DoSnapshot still aborts as not ported; nothing in a race reaches it yet.

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

## The drive target

A tAICop keeps a route point in `RouteInfo` (76: the route, 80: the
point). CopDriver steers along the drive target its car's driver builds
from it: twenty points down the route ([cop-driver.md](cop-driver.md)).

**IsNearPursuitTarget** is 1 when the cop has a pursuit and its car is
less than 20 m from the chased car (`sqrt(dx^2 + dy^2) < 20`). Without a
pursuit it is 0.

**InitializeDriveTarget** clears RouteInfo, then finds a route point by
the logic state *asked for*:

- **LS_DRIVING_ON_PATROL.** In LSS_PATROL_ONCOMING, the nearest point on
  the oncoming traffic routes (GetNearestRoutePoint, flags 2, distance
  0). It is kept if it is within the road across the car's own route
  point (`Car::GetRoutePoint(1)`). How far across is
  `(p - rp) . (Dir.y, -Dir.x)`, the two products taken apart. Below 0
  its size must be within LeftWidth, otherwise within RightWidth. A NaN
  passes. If the point is not kept, in any other sub-state, or when
  nothing was found, it is the nearest point on all the racing routes.
- **LS_HOT_PURSUIT.** By the sub-state. BLOCK and GET_AHEAD take the chased
  car's route and route point (`GetRoute(1)`, `GetRoutePoint(1)`),
  ACQUIRE the cop's own car's. Any other leaves RouteInfo clear.
- Any other state leaves it clear.

**UpdateDriveTarget(pos, keep).** With keep 0, the route point is first
moved up to `pos`. Each test asks whether pos is past the point:
`(pos - point) . Direction > 0`. Each pass steps to the next point
(GetNextRoutePoint, which can cross to a linked route). At the end of a
route there is no next point, so the point stays. At most ten steps are
taken: the tests passed are counted, and after the tenth no more steps
are taken.

If exactly ten passed (the tenth step taken, and the point it reached
not passed), InitializeDriveTarget runs and the walk starts again, once.
More than ten, which happens when stuck on a route's last point, does
not start it again.

Then the driver's drive target is cleared (`Clear(NULL, 0)`) and
filled. From the route point on, up to twenty points are added, stopping
early past a route's end. Each point is `GetPosition` at `MyDLOffset.x`
along and `MyDLOffset.y` across. With a driving line chosen
(`nDrivingLineIndex` not -1), that line's offset at the point is added
to the across distance. Each is added with the route's number as a byte
and the point's number in the route, driving line 0, no check and no
car. With keep 0 the target's first point is then set to `pos`, in x
and y.

## Think

The manager's Think (`cop-manager.md`) calls each cop's Think through its
table, slot 24, once a frame. tPlayerCop's is Be A Cop's (12m), so its
entry calls `gPlayerCopThinkFn` when that is bound.

**tAICop::Think:**

1. The grace timer at 32 counts down while above 0 (it can end below 0).
2. If the camera follows this car (`CameraFollowThisCarInstead` is its
   DriverNumber), the drive target renderer is pointed at the car's
   drive target (`0x001cb600`).
3. MovementModeTransitions.
4. On its side or roof (the body's up vector, `BodyMatrix.v2.z`, at or
   below 0.1) and below 10 mph (`VelocityMagnitude x 2.237`): DisableMyCar
   with 1. Then, with any tire blown (`BlownTireBits`): DisableMyCar with
   0. Both can happen in one frame. The flag only matters in a chase of a
   player within 75 m, where it goes to RemovePrimarySpeaker.
5. The sub-state's timer counts down and stops at 0. A NaN stays.
6. If the state asked for is not the state, HandleStateTransitions from
   one to the other, and the state becomes the one asked for.
7. The state's logic: limbo, disabled and guard below, and radar trap,
   roadblock and patrol in the next section (12g-2). Hot pursuit and
   caught speeder go through `gAICopDo...LogicFn`, which do nothing
   while NULL (12g-3).
8. The offset at 48 eases toward `MyDLOffset`: each part steps by its
   sign times its rate (64: 6 a second across, 68: 3 along) times the
   frame's time, or takes the rest of the way when that is nearer
   (`|rest| < |step|`). Both rates are set back to 6 and 3 afterwards,
   so a logic can change them for one frame only.

A part already in place divides 0 by 0. On the EE that is FLT_MAX, and
FLT_MAX times the rate is FLT_MAX again (the EE has no infinity: an
overflowing `mul.s` gives FLT_MAX by its sign). Times a frame of 0 it is
0, where IEEE's infinity times 0 is a NaN. The port spells the divide
`ee_div` and both products `ee_mul` (`eefpu.h`), so the part stays put
either way.

**MovementModeTransitions** switches a cop's car between COP_MOVEMENT,
the cheap mover it uses away from the players (`cop-mover.md`), and the
others. It does nothing with no mover (limbo) or when DISABLED is asked
for.

- *Not in COP_MOVEMENT* (physics, or mellow after a jump): the time in
  physics mode (84) goes up by the frame. While it is below 0 (or NaN),
  nothing else happens. Then the switch's delay (88) is reset to 0.1 s if
  the car is unsettled: fewer than four wheels down, or skidding (its
  velocity's heading, `bToPolar`, more than 1820 BAM (10 degrees) off the
  car's angle either way, at above 17.88109 m/s), or spinning (the
  angular velocity's length above 1). The delay counts down, and at 0
  or below it is set to 0 and the car goes back to COP_MOVEMENT.
- *In COP_MOVEMENT:* the time in physics mode goes to 0. If the cop
  mover says the car is in the air (`bIsAirborne`, 112), its upward speed
  is held to 2 m/s, `VelocityMagnitude` is taken again, `MatrixValid` is
  cleared and the delay set to 0.1 s. The car goes to MELLOW_MOVEMENT,
  and its driver to automatic, no brake, full throttle, no e-brake,
  straight wheels, and SetDesiredSpeed(forward speed, 0.5 s, tolerance 0,
  allowed) through its table.

1820 is gp-13336, a u16 that a static initializer
(`_GLOBAL_$I$fNearFollowDistances`, `0x00230d00`) sets at start-up; the
image itself holds 0 there. The difference is taken as a 16-bit angle,
signed, and its size compared unsigned, so -32768 counts as 32768.

**HandleStateTransitions(from, to)** sets the sub-state's timer to 0,
then:

| leaving | does |
|---------|------|
| DISABLED | ResetAllDamage |
| LIMBO | collisions back on, the car drawn, COP_MOVEMENT, ResetAllDamage |
| SPEED_TRAP | ClearSpeedTrap |

| entering | does |
|----------|------|
| LIMBO | ClearPursuit; off the map, siren off, lights 0; no mover; the driver parked; collisions off; not drawn. Sub-state LIMBO_DISABLED with a 1 s timer from DISABLED, otherwise LIMBO_READY |
| DISABLED | ClearSpeedTrap, ClearPursuit; the driver disabled; sub-state NONE; siren broken, lights 1, off the map; MELLOW_MOVEMENT; the car's driver to throttle 0, brake 0.3, e-brake 1, both gears automatic, straight wheels, then SetDesiredSpeed(0, 10 s, tolerance 0) |
| SPEED_TRAP | ResetAllDamage, then InitSpeedTrapLogic |
| ROAD_BLOCK | ResetAllDamage, then InitRoadBlockLogic |
| DRIVING_ON_PATROL | ClearPursuit; off the map; InitializeDriveTarget, then UpdateDriveTarget from the car's place with keep 0; the driver patrolling; lights 0, siren off |
| HOT_PURSUIT | lights 2; the driver in pursuit; PURSUIT_FOLLOW asked for; siren 1; on the map; sub-state NONE |
| CAUGHT_SPEEDER | the pursuit set to NULL (not ClearPursuit: the pursuit keeps the cop); the driver parked; sub-state CAUGHTSPEEDER_TICKETING; lights 1; on the map; siren off |
| GUARD_LOCATION | ClearSpeedTrap, ClearPursuit, ResetAllDamage; the driver parked; lights 0; sub-state NONE; off the map; siren off |

The lights are a word store at 2056, as the constructor's, so the three
bytes after `CopLights` go to 0 too. The two Init logics are in the next
section.

**Holding still.** Retail's `0x00230a60` clears the car's driver's drive
target (`Clear(NULL, 0)`, when there is a driver) and adds the car's own
place as its one point: route -1, point -1, driving line -1, no check, no
car. Retail adds the point without testing the driver. DoLimboLogic
holds, then turns LIMBO_DISABLED into LIMBO_READY once the timer is
exactly 0. DoDisabledLogic holds, then asks for LIMBO once no player is
within 250 m (`0x0014e3e8`, which a NaN also passes). DoGuardLocationLogic
only holds.

**ResetAllDamage** (`copmgr.c`) makes a car whole: FixBlownTires
(`0x00135120`: the rumble timer, `BlownTireBits` and `NumBlownTires` to
0), `fTractionBoostOverride` 1, the manager's `fCarDamage[CarIndex]` 0,
the CarDamage repaired if the car has one (`0x001b5c20`, through
`gCarDamageRepairAllFn`), and, for a player's car (REAL_CONTROL), the
RealDriver's e-brake stop let off. Retail's ForceEBrakeStop
(`0x0013b558`) takes a float and stores it at 580; the call passes 0.
The port's has been retail's since 12i-3 (see
[real-driver](real-driver.md)).

## Radar traps, roadblocks and patrols

**Putting a cop on its spot.** Teleport(pos, heading) does nothing
without a car. Otherwise it puts the car in COP_MOVEMENT, then
Car::ResetToPosition to (x, y, 0) at speed 0 and that heading.

- SetSpeedTrap points the cop and the trap (`cop`, 0) at each other,
  teleports to the trap's spot and heading, and asks for SPEED_TRAP.
- SetRoadBlock(roadblock, pursuit, i) sets the pursuit (tCop's setter,
  not ClearPursuit) and keeps i (`nMyRoadBlockIndex`, 40). Then it
  teleports to the roadblock's spot i and heading i, and asks for
  ROAD_BLOCK.

The roadblock record's `bVector4 pos` and `int ang` (the .mdebug's, at
8 and 24) are read as two spots of x and y, and two u16 headings, one
for each cop. `copmanager.h` names them `CopPos[2]` and `CopAng[2]`.
The record's size and its other offsets are unchanged.

**The Init logics.** Both park the car: sub-state NONE, off the map,
forward speed 0, the CopDriver PARKED, and the velocity and its
magnitude 0. Retail stores the zero velocity with `sqc2`, so its w comes
from the stack; the port leaves w alone. Then:

- InitSpeedTrapLogic clears the pursuit first, then parks. It sets the
  sub-state's timer to 15 s, `MatrixValid` to 0, the lights to 0 and
  the siren off.
- InitRoadBlockLogic keeps its pursuit. It parks, then sets the lights
  to 1, `MatrixValid` to 0 and the siren off.

**Back to the spot.** A cop more than 1 cm from its spot (gp-26908 and
gp-26900, 0.01) or more than 100 BAM off its heading is put back, if
CanTeleport allows it. The heading's difference is a signed 16-bit
angle, and its size is what counts. A NaN position passes neither test.

**DoSpeedTrapLogic** holds still. Once the sub-state's timer is at or
below 0 and no player is within 250 m (a NaN distance passes), it asks
for LIMBO and stops. While the timer runs the distance isn't asked.
Otherwise it goes back to the trap's spot if it must, then searches with
the flag 1 for every car.

**DoRoadBlockLogic** holds still. With a pursuit that has a roadblock, it
goes back to its spot there, re-reading its index for the teleport. Then,
with or without one, it sets the grace timer at 32 to 3 s. It does not
search: the pursuit that called the roadblock does the chasing.

**DoDrivingOnPatrolLogic** sets `MyDLOffset` and the eased offset at 48
to 0, then UpdateDriveTarget from the car's place with keep 0. With no
player within 250 m it asks for LIMBO and stops. Otherwise it searches,
with CanPatrollerSeeThisCar's answer as each car's flag.

**The search** is inline in both logics. It walks CarTable up to
`CopCarPos`: the players' and racers' cars, which come before the cops'.
The count is read once. A car within 45 m of the cop's in x and y, and
2.5 m in z, is a target when IsValidPursuitTarget(car, flag) says so. If
tCopManager::RequestPursuit (`0x00225078`) then grants it, the cop asks
for HOT_PURSUIT. The walk goes on to the end either way.

**IsValidPursuitTarget(car, flag)**, in order:

1. 0 for Be A Cop's car (the player cop's, when there is one).
2. 0 for a car being pulled over (its pullover record's `bActive`, by
   `CarIndex`).
3. 0 while its pursuable timer (`fPursuableTimer[CarIndex]`) is above 0.
4. 1 for a car that caused a recent collision.
5. 0 when the flag is 0.
6. 1 above 80 mph either way (`|ForwardSpeed x 2.237|`).
7. Otherwise, whether a pursuit already chases it (IsBeingPursued).

**CanPatrollerSeeThisCar(car)**: the car is within 50 m in x and y, and
moving. It must also be at least 20 m on from the cop along its own way
of travel: its unit velocity, dotted with the line from the cop to it,
is 20 or more. So a patrol sees a car that has passed it, or that it
follows.

**CanTeleport(car, dest)** (`coputil.c`) is 0 when a player is within
250 m (two-dimensional) of the car, or of `dest`. It is also 0 when any
other of the world's `TotalNumCars` cars (read once) is within 15 m of
the car. That is the car's own place, not `dest`. Otherwise it is 1.

**CarCausedRecentCollision(car)** (`coputil.c`) walks the car's collisions
this frame in order. `NumCollisions` is read at each step. For each
two-car one it takes the other car (the first of the pair unless that is
this car):

- no other car ends the walk with NULL;
- a stopped one (forward speed exactly 0) is the answer;
- so is one in front (Car::IsCarInFront within 8192 BAM) going forward
  (0 or more) slower than this car.

Past the last collision it is NULL.

Sub-state 1 is still unnamed: none of these logics use it.

## The chase

The hot pursuit logic (`0x0022ff58`) runs a cop in LS_HOT_PURSUIT. Its
sub-states are the ten from PURSUIT_FOLLOW (3) to STOP (12). The chased
car is the pursuit's `pChasedCar` (16); retail reads it without testing
the pursuit. Each call:

1. A sub-state asked for last time becomes the sub-state. The one
   before is kept as `old`; each sub-logic sets itself up when `old`
   differs.
2. The gap round the track is TrackPathManager::CompareDistances
   (`0x00208598`) of the cop's DistanceAroundTrack against the chased
   car's. It is above 0 with the cop ahead.
   - 450 m or more either way: ReturnToPatrol, then ClearPursuit, and
     nothing else.
   - 180 m or more behind (-180 counts): ask for ACQUIRE.
   - Otherwise, 6 m or more ahead with the chased car at 20 mph or more
     (signed, `ForwardSpeed x 2.237`): ask for FOLLOW_BACKWARDS if its
     velocity runs against its route point's way (Car::GetRoutePoint),
     else BLOCK.
3. The sub-state's logic runs. A sub-logic asks for its next sub-state;
   it takes over on the next call.

Some terms the sub-logics share:

- *Primary*: the pursuit's `Cops[0]` (28). The other cop is `Cops[1]`.
- *Distance*: the two cars apart in x and y.
- *Level*: tCopManager's `nDifficultyLevel` (10476) for a player's car;
  2 for any other.
- *At the offset*: the eased offset (`New48`) within 1 cm of
  `MyDLOffset`, in x and then y.
- *Angle off*: bToPolar of the chased car to the cop's car, less the
  chased car's heading, as a signed 16-bit angle, made positive. It is
  0 with the cop dead ahead and 32768 dead behind. The polar's distance
  comes too.

**ReturnToPatrol** (`0x00230cb0`) asks for DRIVING_ON_PATROL. It sets
the sub-state outright to PATROL_RACING, above 30 mph (13.410818 m/s,
gp-26860), else PATROL_ONCOMING.

**GetBestFlankSide(car)** (`0x00230248`) answers -1 (left), 1 (right)
or 0. It first calls Car::GetRoute(1) on the chased car and ignores the
answer, then takes Car::GetRoutePoint(1). It works out the chased car's
place across that point:
`(x - px) * dy - (y - py) * dx`.

- *Left* is free when `-LeftWidth - lateral <= -3`.
- *Right* is free when `3 <= RightWidth - lateral`.

The cop's car is put in the chased car's frame (CarState::WorldToCar,
`0x001c0b18`).

1. If the cop is behind it (x below 0), a free left answers -1. If it
   is level or ahead, a free right answers 1.
2. Otherwise, a cop within 2.5 m to either side answers 0.
3. Otherwise, a free right answers 1 and a free left -1, else 0.

**The sub-logics:**

- **PURSUIT_FOLLOW** (`0x0022f8d8`). On the way in: 3 s on the timer,
  and in line behind, 6.5 m for the primary and 13 m for the other.
  - At 21 m or further: the timer is set to 3 s again, and the cop
    stays behind, the other cop 2.5 m to the side. Nothing else.
  - A back offset of 0 is set again.
  - A flank is tried when all of these hold:
    - World::Random(float) of 3, 2 or 1 (by the level) draws under 1;
    - the timer is exactly 0;
    - the two cars didn't knock (DidTheseCarsCollide);
    - GetBestFlankSide finds a side.
  - The other cop's zone must then allow it: no other cop, or one with
    no car, always does. FOLLOW_OFFSET's zone for that side goes to
    RequestZonePermission against the zone the other cop holds. The
    side is kept (`fFlankSide`, 72) and FOLLOW_OFFSET asked for.
  - Either way, a chased car under 20 mph either way asks for
    LOW_SPEED_CLOSE_FOLLOW.
- **FOLLOW_OFFSET** (`0x0022f1d8`). 2 s on the way in. 6.5 m behind,
  3 m out on the flank side.
  - A best side that is not the flank side asks for PURSUIT_FOLLOW.
  - Then, with the timer at 0 and the offset reached:
    - a knock sets 2 s again;
    - otherwise FLANK, within 135 degrees of the chased car's nose or
      within 15 m (the polar's distance);
    - else PURSUIT_FOLLOW.
- **LOW_SPEED_CLOSE_FOLLOW** (`0x0022fb68`). On the way in, 6 m behind
  in line. Above 20 mph either way it asks for PURSUIT_FOLLOW. Under
  5 mph and within 10 m it asks for STOP.
- **FOLLOW_BACKWARDS** (`0x0022f000`).
  - Within 20 m, the primary keeps 6.5 m back. When its timer is 0 it
    takes the best side and a World::Random(3) draw. It sidles over
    that share of the side (1, 0.5 or 0.25), for 1.25 s.
  - Further off, the primary drops both offsets.
  - The other cop keeps 13 m back within 20 m (else 0), and 2.5 m to
    the side.
  - Under 5 mph either way and within 10 m, it asks for STOP.
  - Then, above 1 m/s along its route point's way, it asks for
    PURSUIT_FOLLOW.
- **FLANK** (`0x0022f398`). On the way in: level (back offset 0), 3 m
  out on the flank side, 2.25 s.
  - A best side that is not the flank side asks for FOLLOW_OFFSET, and
    nothing else.
  - A cop within 90 degrees of the chased car's nose picks by the
    pursuit's behaviour bit 4 (`BehaviourFlags`, 1588):
    - a player's car, bit clear: GET_AHEAD;
    - a player's car, bit set: BUMP, but GET_AHEAD for the primary when
      World::Random(15) draws under 2;
    - another car, bit set: GET_AHEAD on that draw, else BUMP;
    - another car, bit clear: nothing.
  - Then, with the timer at 0 and the offset reached, the timer is set
    to 2.25 s again. A cop past 90 degrees that is also at 135 or more
    asks for FOLLOW_OFFSET.
- **BUMP** (`0x0022f598`). 1.75 s on the way in. The cop swings in on
  the flank side: the side offset is `|t - 0.875| x 2 / 1.75` of 3 m,
  in to 0 at half time and back out. The back offset is 0, and both
  pull rates (`New64` and `New68`) are 100.
  - With the timer at 0 it asks for FLANK, and nothing else.
  - With CopStrength not 2 (`TheRaceParameters`, 648) and a knock: a
    knock before the last quarter (the timer at 0.4375 or more) asks
    for FLANK.
  - A knock later shoves the chased car first. The way from the cop's
    car to it is normalised, all four lanes as the VU0 does, and times
    7, 10 or 15 by the level. Unless the chased car has no movement,
    its collision body goes to physics mode (slot 112, NULL), then
    takes the impulse at 0 (slot 128). Then the cop asks for FLANK.
- **BLOCK** (`0x0022fc20`). On the way in, no driving line (-1). No
  offsets, both pull rates 100.
  - A cop behind (a gap below 0) asks for PURSUIT_FOLLOW.
  - Otherwise, it asks for FOLLOW_BACKWARDS when all three hold: the
    chased car is above 20 mph by its `VelocityMagnitude`; it is going
    against its route point's way; and it is more than 20 m off.
  - Either way, under 20 mph either way and more than 10 m off asks for
    LOW_SPEED_CLOSE_FOLLOW.
- **GET_AHEAD** (`0x0022fee0`). Only on the way in: back offset 0, no
  driving line, and a side offset of the cop's own place across its own
  route point.
- **ACQUIRE** (`0x0022fdb0`). On the way in: driving line 0, no offsets.
  Within 180 m (a gap above -180) it asks for PURSUIT_FOLLOW.
- **STOP** (`0x0022fe28`). On the way in: no offsets, 0.5 s. Once the
  timer is at or below 0, a chased car above 5 mph either way, or more
  than 10 m off, asks for LOW_SPEED_CLOSE_FOLLOW.

The shares, pushes and draws are three tables the sub-logics copy to the
stack: `0x002bd5a0` (1, 0.5, 0.25), `0x002bd5f0` (7, 10, 15) and
`0x002bd628` (3, 2, 1).

**The other cop's zone.** Retail reads the other cop's flank side at
+72 whatever the cop. For Be A Cop's 52-byte tPlayerCop that is past its
end. The port reads it from AI cops only, and takes 0 for the player's.
The side only counts in FOLLOW_OFFSET, FLANK, BUMP and GET_AHEAD. A
player's cop is never in those.

**DoCaughtSpeederLogic** (`0x002303c8`) holds still. Only in WAITING
(16) does it go on:

- with no player within 250 m (a NaN distance counts) it asks for
  LIMBO;
- else, with its timer exactly 0, ReturnToPatrol.

Then it searches with the flag 0. TICKETING (15) does nothing but hold.

**DidTheseCarsCollide(a, b)** (`0x00231268`, `coputil.c`) walks a's
collisions this frame. `NumCollisions` is read at each step. For each
two-car one it takes the other car (the first of the pair unless that
is a). It is 1 at the first that is b, and 0 when the walk ends.

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

GetZoneFromSubState gives a pursuit sub-state's zone: pursuit follow
4; follow offset 3, or 5 when `side` is not below 0; flank, bump and
get ahead 1, or 2; block 0; the rest 6.

## Seams

Not ported yet, so NULL, and each aborts where retail would call it:
tPursuit::RemoveCopFromPursuit (`gPursuitRemoveCopFromPursuitFn`) and
RemovePrimarySpeaker (`gPursuitRemovePrimarySpeakerFn`), 12h and 12i;
CarDamage's wreck (`gCarDamageWreckFn`) and repair
(`gCarDamageRepairAllFn`), which no car reaches while CarDamage isn't
built.

Not ported yet, and doing nothing while NULL: tPlayerCop's Think
(`gPlayerCopThinkFn`), 12m. tCopManager::RequestPursuit
(`gCopManagerRequestPursuitFn`, 12h) grants nothing while NULL, so a
search finds no chase. The hot pursuit and caught speeder logics (12g-3)
are now called straight from Think, but no cop reaches them before 12h.

`main.c` binds `gAICopDisableMyCarFn` to `cop_disable_my_car`,
`gCopMoverCtorFn` (COP_MOVEMENT's mover, 12c), `gCopDriverCtorFn`
(COP_CONTROL's controller, 12d), and since 12g-1 `gAddCopCarToRaceFn`.
So a race with cops makes their cars. Each starts in limbo and stays
there: not drawn, parked, not colliding, off the map. Since 12i-2 a
roadblock calls its cops out of limbo (`pursuit.md`). Since 12j-1 the
manager's SpawnSpeedTraps sends a ready one to a radar trap ahead of a
racer (`cop-manager.md`). Since 12j-2a a roadblock with spikes lays its
strip, and a car whose wheels cross it has those tires blown
(`cop-manager.md`, "Spike strips").
A Hot Pursuit quick race in Azahar runs at 30 fps with its four, as it
did before 12g-2.

## The check

`tools/cop_check.py` runs retail's code in mipsemu and the port in
`tools/src/cop_test.c` on 756972 operations:

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
  with RemovePrimarySpeaker moving the cop;
- the drive target (12d):
  - IsNearPursuitTarget about 20 m, from two places, and with NaN,
    infinite and -0 positions;
  - InitializeDriveTarget in every state asked for and every pursuit
    sub-state. That covers the oncoming point kept or not, at, just
    inside and just past both widths (a negative and a zero width
    among them), and cars with no route;
  - UpdateDriveTarget keeping its point (keep 1, 2 and -1) and walking
    it. The walk runs on, just short of and just past each point, past
    a route's end, across a link, and round a loop. It covers the
    restart at exactly ten by each answer, every driving line, and
    random runs;
- Think (12g-1), on an AI cop with a rigged car (a CopDriver, a cop
  mover and a collision body, and a NullDriver as the car's driver):
  - HandleStateTransitions for every pair of states from -1 to 9;
  - MovementModeTransitions in every mode, at the edges of each test:
    the wheels, the skid angle swept through 1820 both ways and at
    -32768, the speed one bit either side, spins of every direction,
    the delay counting down, and in the air;
  - Think: the grace timer, the camera, on its roof and blown tires in
    four states (one bit either side of 0.1 and of 10 mph, NaN), in a
    chase of a player near by, the sub-state's timer with NaN, -0 and
    the infinities, each state staying and coming from limbo, limbo's
    wait, disabled's 250 m, the offset's easing (a part in place, rates
    of 0, negative and FLT_MAX, frames of 0 and below 0, the tie between
    the step and the rest), tPlayerCop's through the table, a cop's life
    from limbo through patrol, a chase and disabled, and 400 random runs;
- the radar traps, roadblocks and patrols (12g-2), on Think's rig in a
  world of four cars:
  - Teleport, SetSpeedTrap and SetRoadBlock, with and without a car, at
    each spot and both cops' places;
  - IsValidPursuitTarget through each test in turn, with flags of 0, 1,
    2 and -1. That covers speeds one bit either side of 80 mph, both
    ways, and NaN; pullovers whose `bActive` sits in other bytes;
    pursuable timers of every sign, the smallest and NaN; and the player
    cop's car and a missing one;
  - CarCausedRecentCollision over tables of collisions: none, not two-car,
    a missing car, stopped (0 and -0), in front or not, slower, backing;
  - CanPatrollerSeeThisCar on a grid one bit either side of 20 m and 50 m;
  - CanTeleport at 250 m from either side and at 15 m, with every count;
  - the two Init logics, with and without a pursuit;
  - DoSpeedTrapLogic's timer (NaN, -0 and the smallest among them) with
    distances at 250 m from either side. Its spot is tested at 1 cm,
    exactly and either side, and its heading either side of 100 BAM and
    at -32768. The search covers its 45 m and 2.5 m, the target test,
    the manager's answer, and counts from 0 to 4 and -1;
  - DoRoadBlockLogic with no pursuit, no roadblock, and both spots;
  - DoDrivingOnPatrolLogic's 250 m, and whom it sees, granted or not;
  - each through Think, and 300 random runs;
- the chase (12g-3), on the same rig. A2 is the chased car, at the
  origin on a route point of its own; cop 1 is an AI cop in A3, and
  cop 2 the player's:
  - ReturnToPatrol one bit either side of 30 mph, and at 0, backing
    and NaN;
  - GetBestFlankSide on 720 cases: lanes either side of each width,
    the cop either side of the car and of 2.5 m, and NaN;
  - the way in, with gaps either side of 450 m, -180 m and 6 m, both
    ways, with and without a track length (so CompareDistances wraps),
    speeds either side of 20 mph, and both ways along the route;
  - each sub-logic on the way in and staying. That covers each test
    one bit either side and with NaN; the draws (World::Random's
    answers queued by the script); the other cop's zone for each
    sub-state and side, as primary and not, with no car, and as the
    player's cop; knocks or none; the behaviour bit; each level; and
    CopStrength 0 to 2. Bumps are run with the chased car moving and
    not;
  - DoCaughtSpeederLogic in TICKETING, WAITING and two other
    sub-states, at 250 m (one bit under, and NaN), with its timer at 0,
    -0 and 1, and its search granted or not;
  - both logics through Think, and 500 random runs.

Think's world adds stand-ins for the drive target renderer, the
collisions' on and off, ForceEBrakeStop, the distance to the nearest
player (an answer the script sets, or a queue of them), the CarDamage
repair, tPlayerCop's Think and the NullDriver's SetDesiredSpeed, each
logged. 12g-2 adds the world's car
count and table, each car's collisions (GetCollision,
IsTwoCarCollision and GetCollidingCars on a table the script sets),
Car::IsCarInFront's answers, Car::ResetToPosition, and RequestPursuit's
answer. 12g-3 adds:

- World::Random's int and float answers, each a queue the script sets;
- CarState::WorldToCar's answers, a queue too;
- the chased car's collision body's physics mode and impulse, through
  its table, logged;
- a granted RequestPursuit puts the cop in U4 as its primary.

CompareDistances, bToPolar and DidTheseCarsCollide run as shipped, on
TheTrackPathManager's track length. The model runs with `eediv`,
`eesqrt` and `eemul`, and gp-13336 set to 1820 as the start-up code
would.

The drive target's world is three routes of real points, in retail's
layout (a 1064-byte header, then 112-byte points). Each car has a
driver. Four stand-ins answer by rules the script sets:

- GetNearestRoutePoint: a queue of answers, each the return and the
  route and point it leaves;
- GetNextRoutePoint: a point on, or off a route's end, point 0 of the
  route it links to, or NULL;
- Car::GetRoute and Car::GetRoutePoint: a route and point per car.

DriveTarget's Clear and AddPointToTarget are logged.
TrackRoutePoint::GetPosition runs as shipped.

93019 lines, 0 differ. `--mutate`: 724 mutations, 719 caught, and
five equivalent:

- tAICop's destructor storing its own table, which tCop's overwrites
  straight after;
- UpdateDriveTarget's restart at `n >= 10` for `n == 10`. The loop's top
  only sees n at 0 or 10;
- DoLimboLogic's `timer == 0` as `<= 0`: Think has just stopped the
  timer at 0, and HandleStateTransitions only sets 0 or 1;
- GetBestFlankSide's last tests in either order. The fall-through comes
  with left not free (behind) or right not free, never both free;
- PURSUIT_FOLLOW's zone as FLANK's. Zones 1 and 3, and 2 and 5, have
  the same column in the permission table.

`copmanager_check` links `cop.c` too (33602 lines, 0 differ). Its
harness, and copmover's (which links all of `copdriver.c`), stand in
for the drive target's, CopDriver's and Think's calls with ones that
abort if reached. Since 12g-2, copmanager's also stands in for
CanTeleport and CarCausedRecentCollision that way, and copdriver's and
trackgraph's for the collision calls `coputil.c` now makes. Since 12g-3,
copmanager's also stands in for World::Random(int), WorldToCar,
CompareDistances and DidTheseCarsCollide. Since 12j-1, cop's and
pursuit's harnesses stand in for the SpawnSpeedTraps calls they lack
with ones that abort: the split, Timer::SetTime and FindSpeedTrap in
both, the free run in cop's, and IsTeleportLocationClear and
SetSpeedTrap in pursuit's. carmode (which now maps CopDriver's host size back to 76),
copdriver, copmover, collisionbody, drivecam, drivingchoice, hudanim,
hudfeatures, hudrender, nearbycar, realcontroller, realdriver, trackmap,
raceupdate, hudcop, hudscore, aidriver, aicarcontroller, beltmover,
carinit, physcomp, physicscar, raceinit, racecore, racerun, airoute,
cardriver, drivetarget, trafficcar, trafficdriver and traffictele all
have 0 differ.
