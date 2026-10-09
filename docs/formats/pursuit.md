# The pursuits (step 12h on)

tPursuit is one car's chase: up to two cops after it, its roadblock and
helicopter, the HUD's pursuit level and the voices on the radio. Retail
keeps it in copmgr.obj, `0x00228fc8` .. `0x0022d338`; the manager makes
one in RequestPursuit and deletes it in PursuitManagement
(`cop-manager.md`). The record and its small records are
`copmanager.h`'s; the code is `pursuit.c`, with retail's new
BarricadeManager in `barricade.c`.

Slice 12h-1 ports the object and how a chase is granted: the
constructor and destructor, the state switch and its timers, the cops
joining and leaving, the speakers, and the one-liners the cops' logic
asks. Slice 12h-2 ports Update (`0x00229288`), each chase's step, and
the state machines under it. Slice 12i-1 ports the roadblock's running
logic: asking for one, watching the chased car get by, and taking it
down. Slice 12i-2 makes the roadblock: the cops for it, its layout
across the road, and its barrels. Slice 12i-3 ports retail's e-brake
stop into RealDriver (see [real-driver](real-driver.md)). The helicopter
is 12k's and the pullover 12l's.

| function | address | port |
|----------|---------|------|
| GetTopSpeed (coputil.obj's) | `0x00231338` | `get_top_speed` |
| tPursuitHistory::tPursuitHistory | `0x0022cee0` | `tpursuithistory_construct` |
| tPursuitHistory::~tPursuitHistory | `0x0022cf68` | `tpursuithistory_destruct` |
| tRoadBlockStateMachine::tRoadBlockStateMachine | `0x0022cc00` | `trbsm_construct` |
| tRoadBlockStateMachine::~tRoadBlockStateMachine | `0x0022cc18` | `trbsm_destruct` |
| tRoadBlockStateMachine::DisbandRoadBlock | `0x0022cdd0` | `trbsm_disband_road_block` |
| tPursuit::tPursuit | `0x00228fc8` | `tpursuit_construct` |
| tPursuit::~tPursuit | `0x00229198` | `tpursuit_destruct` |
| RoadBlockEncounteredRecently | `0x00229dd8` | `tpursuit_road_block_encountered_recently` |
| SelectPrimaryCop | `0x00229ed0` | `tpursuit_select_primary_cop` |
| (a state's seconds) | `0x00229f70` | `tpursuit_state_time` |
| SwitchPursuitState | `0x00229fe8` | `tpursuit_switch_state` |
| DoStateTransition | `0x0022a190` | `tpursuit_do_state_transition` |
| GetSpeedMPHOrKPH | `0x0022a220` | `tpursuit_get_speed_mph_or_kph` |
| ReleaseAllCops | `0x0022a260` | `tpursuit_release_all_cops` |
| (the helicopter let go) | `0x0022a310` | `release_chopper` |
| GetCopSpeaker | `0x0022ab30` | `tpursuit_get_cop_speaker` |
| GetSecondaryCopSpeaker | `0x0022ab70` | `tpursuit_get_secondary_cop_speaker` |
| IsPlayerInvolved | `0x0022bbd8` | `tpursuit_is_player_involved` |
| DisbandRoadBlock | `0x0022c5a0` | `tpursuit_disband_road_block` |
| RemoveCopFromPursuit | `0x0022c740` | `tpursuit_remove_cop_from_pursuit` |
| IsCopInPursuit | `0x0022c920` | `tpursuit_is_cop_in_pursuit` |
| RemovePrimarySpeaker | `0x0022c990` | `tpursuit_remove_primary_speaker` |
| the one-liners | `0x0022d210` .. `0x0022d338` | `tpursuit_add_cop` .. `tpursuit_get_pursuit_level_for_hud` |
| (tCopManager's) NewPursuit | `0x002244e0` | `copmanager_new_pursuit` |
| tCopManager::RequestPursuit | `0x00225078` | `copmanager_request_pursuit` |
| tCopManager::PossibleCallSupervisor | `0x002253e8` | `copmanager_possible_call_supervisor` |
| tCopManager::DeleteRoadBlockSpikeStrips | `0x00227be8` | `copmanager_delete_road_block_spike_strips` |
| BarricadeManager::BarricadeManager | `0x0024ef88` | `barricademanager_construct` |
| BarricadeManager::~BarricadeManager | `0x0024efd8` | `barricademanager_destruct` |
| (start the barrels fading) | `0x0024f1e0` | `barricademanager_fade` |
| tPursuit::Update | `0x00229288` | `tpursuit_update` |
| NotInChasingState | `0x002295c8` | `tpursuit_not_in_chasing_state` (copmanager.c) |
| Level0SubStates | `0x002295d8` | `tpursuit_level0_sub_states` |
| UpdateDriveTargets | `0x0022a360` | `tpursuit_update_drive_targets` |
| DoEarlyChaseCollisionCheck | `0x0022aba0` | `tpursuit_do_early_chase_collision_check` |
| IsChasedCarStoppable | `0x0022bea0` | `tpursuit_is_chased_car_stoppable` |
| ShouldPursuitBeCalledOff | `0x0022c2d0` | `tpursuit_should_pursuit_be_called_off` |
| tRoadBlockStateMachine::Update | `0x0022cdd8` | `trbsm_update` |
| tPursuitHistory::Update | `0x0022cf90` | `tpursuithistory_update` |
| tCopManager::IsCopNearby | `0x00225d30` | `copmanager_is_cop_nearby` |
| tCopManager::DidRecentlyCollideWithCop | `0x002286b8` | `copmanager_did_recently_collide_with_cop` |
| (the barrels' fades counted down) | `0x0024f268` | `barricademanager_count_down` |
| tRoadBlockStateMachine::RequestRoadBlock | `0x0022cc38` | `trbsm_request_road_block` |
| MonitorRoadBlock | `0x0022c390` | `tpursuit_monitor_road_block` |
| RoadBlockDefeated | `0x00229970` | `tpursuit_road_block_defeated` |
| UpdateRoadBlocks | `0x00229b58` | `tpursuit_update_road_blocks` |
| CreateRoadBlock | `0x00229e30` | `tpursuit_create_road_block` |
| CalculateRoadBlockEscapeLaneWidth | `0x0022ca78` | `tpursuit_calculate_road_block_escape_lane_width` |
| tCopManager::CreateRoadBlock | `0x00226298` | `copmanager_create_road_block` |
| (the roadblock laid out) | `0x00226478` | `copmanager_lay_out_road_block` |
| tCopManager::FindCopsForRoadBlock | `0x00226810` | `copmanager_find_cops_for_road_block` |
| (a barrel spawned) | `0x0024f0a8` | `barricademanager_spawn_barrel` (barricade.c) |
| (a cop car's width across the road) | `0x0024fae8` | `roadblock_cop_car_width` (barricade.c) |
| (the cop cars' angle) | `0x0024fb50` | `roadblock_cop_car_angle` (barricade.c) |
| (the plan built) | `0x0024fb78` | `roadblock_build_plan` (barricade.c) |
| (the plan's ring) | `0x00250068` .. `0x00250100` | `roadblockplan_construct` .. `roadblockplan_pop` (barricade.c) |
| (the plan's static constructor) | `0x00250150` | `RoadBlockCopAngle`'s 8192 (barricade.c) |

## The record

Retail's tPursuit is 1600 bytes from the manager's slot pool
(gp-15644), against the demo's 1216. The differences that matter:

- `nPursuitId` (a byte at 1480) is the manager's PursuitsById slot. The
  destructor sets it to -2.
- `pBarricades` (1472) is a BarricadeManager the constructor makes with
  `bMalloc(64, "CopMgr", 0, 16)`.
- The two speakers (1496, 1500) are the cop speech manager's voices,
  with 5 for none.
- `New1556` is 10 from the start. Update counts it down while a tyre
  is blown, and the car can be stopped once it reaches 0.
- `BehaviourFlags` (1588) are the moves the cops may make. The cops'
  flank tests bit 4.

`tPursuitHistory` (1104, 368 bytes) holds thirty velocities and times
and a count. `tRoadBlockStateMachine` (1560, 20 bytes) holds a state,
a timer, the speech flags, a count and its pursuit.

The BarricadeManager holds ten collision body ids (shorts, -1 for
none) and ten fade timers (-1.0 for none), with its table at 0x002bf448.

## Making a pursuit

The constructor (`0x00228fc8`):

- builds the two drive targets, the history and the state machine;
- sets the timers: catch 2, disband 3.5, chopper attack 10, next attack
  12, the roadblock spawn timer 0;
- sets the global `fRoadBlockSpawnTime` (gp-15600) from {20, 15, 10}
  by the manager's difficulty;
- clears the cops, the roadblock, the helicopter, the behaviours and
  the flags, and sets the secondary speaker to none.

With a chased car, it measures the car's top speed. GetTopSpeed starts
at 100 km/h and goes up in steps of 5 km/h, in metres a second. It
stops at the first speed short of 400 km/h where the acceleration
table gives less than the drag (speed squared times Aero.Drag over
Body.Mass). It returns that speed less one step.

The chased car's primary speaker:

- In Be A Cop it is the manager's BeACopId.
- For a player's car the manager reserves one from its queue of four.
- Otherwise it is left as the slot held it.

When the queue is empty, ReserveCopSpeaker returns whatever its caller
left in a2. In the constructor, a2 still holds the first two words of
its stack copy of {20, 15, 10}, so the speaker is 0x41a00000, 20.0f's
bits. The port's `reserve_speaker_in_ctor` returns that. The manager's
other callers keep `copmanager_reserve_cop_speaker`'s 0. In
RemovePrimarySpeaker the queue is never empty, because the reserve
follows a release.

Then it switches to LEVEL3 in the AI demo (RC state 8) and to LEVEL0
otherwise. It sets the chase direction to 1 with its timer at 0.

NewPursuit (`0x002244e0`) takes the slot, constructs it with the id,
and links it at the tail of PursuitList (44) and into PursuitsById
(52). With id -1, retail writes PursuitsById[-1], which is
PursuitList.Prev; the link that follows overwrites it, so the port
skips that write.

The destructor (`0x00229198`):

- releases every cop (ReleaseAllCops);
- for a player's chase, gives both speakers back, the secondary only if
  it is set;
- sets the id to -2;
- deletes the barricades through their table with 3;
- destroys the state machine, the history and the drive targets (near,
  then far);
- frees the slot back to the pool on flags & 1.

The manager's DeletePursuit clears PursuitsById[id] first. With id -1,
that write is PursuitList.Prev = 0.

## The states

| state | seconds | HUD | sub-state | behaviours added | also |
|-------|---------|-----|-----------|------------------|------|
| LEVEL0 | 30 | 1 | NONE | 0x2 | |
| LEVEL1 | 20 | 2 | PURSUIT_FOLLOW | 0x3 | backup called |
| LEVEL2 | 40 | 3 | FOLLOW_OFFSET | 0x7 | backup called, supervisor |
| LEVEL3 | 300 | 4 | FOLLOW_BACKWARDS | 0x20f | backup called, supervisor |
| SPEEDER_CAUGHT | 10 | 0 | | | |
| END_PURSUIT_GIVE_UP | 100000 | 0 | | | see below |

The seconds are retail's table at 0x0031c570, scaled by the race's
length. The length is the track's length times the laps, or the track's
length once for a point-to-point race. It is clamped to 14000..42000.
The seconds are multiplied by `length / 56000 + 0.25`.

Giving up:

- For a player's chase, says CopBackOffSpeech and starts the
  BEAT_THE_COPS score.
- Sets the car's pursuable and radar-trap timers to 999999.
- Releases every cop.

DoStateTransition goes up one level; LEVEL3 and SPEEDER_CAUGHT stay
where they are. It switches only when the state changes. For
END_PURSUIT_GIVE_UP it returns 1 and switches nothing.

PossibleCallSupervisor (`0x002253e8`) runs on entering LEVEL2 or LEVEL3.
It does nothing in the replays, or unless the manager's supervisor
timer is within 0.001 of -50. It also needs roadblocks on and a
player's car chased. Then, one time in two, it asks for the supervisor
in the pursuit's speaker's voice and sets the timer to 7.

GetSpeedMPHOrKPH gives the chased car's ForwardSpeed in km/h for a player
whose units are metric, and in mph otherwise, including for every AI
car. Until 12h-2 the port read VelocityMagnitude (car+964) here; retail
reads car+960, ForwardSpeed. The 12h-1 check had hidden that: its
harness set the one field and the model the other.

## The Update

The manager's Think calls Update (`0x00229288`) once a frame for each
pursuit, and deletes the pursuit when it returns nonzero. In order:

1. The barrels count their fades down by the frame's seconds
   (`0x0024f268`). One that goes below 0 is deleted and its slot freed.
2. `CurrentLandmark` becomes the type of the landmark the chased car is
   in (FindLandmark), or 0.
3. A blown tyre counts `New1556` down.
4. With other than one player, a chased car that has finished ends the
   chase at once.
5. In Be A Cop, only the chase direction, and only with two players.
   Otherwise:
   - The chase's top speed is the most ForwardSpeed seen. Each of its
     cops in COP_MOVEMENT takes it as its mover's base speed (+52).
   - The drive targets are updated, and SelectPrimaryCop runs.
   - In a race of type 3, the chase is over once the car has finished.
   - Called off (below), the chase gives up and is over. Otherwise the
     state timer runs down while a cop is chasing, or from LEVEL3 on.
   - When the timer is out (0 or less), DoStateTransition runs. A
     chase that has given up is over.
6. Still chasing (neither SPEEDER_CAUGHT nor given up) and not over:
   when the car can be stopped, it is pulled over (CreatePullover, with
   1). The chase goes to SPEEDER_CAUGHT, every cop is released, and the
   chase is over.
7. Not over: the roadblock state machine steps, then UpdateRoadBlocks and
   UpdateChopper. That is all in Be A Cop. Otherwise LEVEL0 steps its
   speeches and runs the early check, LEVEL1 runs the early check, a
   chase that has given up returns 1, and the rest return 0.

Level0SubStates (`0x002295d8`) declares the pursuit
(DeclarePursuitSpeech) once the state timer is under 16 s, and asks for
backup (RaiseBackupSpeech) once it is under 3 s. These move the
sub-state from 0 to 1 and then to 2.

ShouldPursuitBeCalledOff (`0x0022c2d0`) never calls off with a tyre
blown, in a point-to-point race, in free run, or in a race of fewer than
4 laps. Otherwise it calls off when the distance left, the laps left
times the track's length, is 2000 or less.

UpdateDriveTargets (`0x0022a360`) feeds the chased car's position to
the two targets. Its float argument is unused.

- The far target gets a new point once its last two points are 20 or
  more apart. Until then the position replaces the last point.
- The near target does the same at more than 1 apart.
- With twenty points, the oldest is dropped before a point is added.
- Between the two, tPursuitHistory::Update (`0x0022cf90`) shifts its
  thirty entries on and puts the car's velocity and the frame's seconds
  first. The count stops at 30. Retail then sums the history in a loop
  whose result nothing reads; the port leaves the loop out.

The roadblock state machine's Update (`0x0022cdd8`) does nothing at
NONE. Otherwise its timer counts down and stops at 0. A machine that
CALLED_FOR_ROAD_BLOCK with the timer at 0 asks for the roadblock
(CreateRoadBlock). If the pursuit then has one, the machine goes to
ROAD_BLOCK_SET.

DoEarlyChaseCollisionCheck (`0x0022aba0`) runs once per chase, for a
player's car, when the car has caused a collision recently:

- At sub-state 0, the car hit only gets BeginPursuitCollisionSpeech.
- Hitting the first cop's car says raisePursuitCopHit, with the
  landmark, and goes to LEVEL2.
- Hitting another cop's car goes to LEVEL2.
- Anything else is traffic: raiseSuspectCrashTraffic, and LEVEL0 goes to
  LEVEL1.

IsChasedCarStoppable (`0x0022bea0`) is never true without tickets,
while the car's pullover is active, once the car is poofed, or once it
has finished. Otherwise:

- In Be A Cop, against the player's cop:
  - It counts as stopped in any of these cases:
    - blinking, and just reset (a player) or within 30 (an AI car);
    - within the capture radius, 10 (11 with two players), and either
      blown and under 0.1 m/s, or upset;
    - within the capture radius and slower than the difficulty's catch
      speed (times 1.5 with two players), with the catch timer
      counted below 0.
  - A stopped car counts only while the player's cop is under 6.7054
    m/s (15 mph).
  - When the timer was not counted, it goes back up, to at most 2.
  - With no player's cop, retail reads through NULL; the port says no.
- Otherwise, stopped when:
  - `New1556` is 0 or less;
  - under 10 mph near a cop, as the catch timer reaches 0, or at 1 or
    less just after hitting a cop. Away from cops or faster, the timer
    is set back to 2. "Near" is a cop within 10 (IsCopNearby) while the
    chase has a first cop, and the car being an AI racer while it has
    none;
  - blown and under 0.1 m/s, or blinking and an AI car or just reset;
  - upset: the body's up axis 0.1 or less, and under 10 mph.

IsCopNearby (`0x00225d30`):

- In Be A Cop: the player's cop within the distance, on the ground
  plane.
- Otherwise: any of the manager's cops within the distance. The cop's
  logic state must be DISABLED, SPEED_TRAP, ROAD_BLOCK,
  DRIVING_ON_PATROL, HOT_PURSUIT or GUARD_LOCATION. A player's cop
  whose NIS is playing does not count.

DidRecentlyCollideWithCop (`0x002286b8`) asks DidTheseCarsCollide of
each of the manager's cops' cars.

The chase direction, in Be A Cop with two players, is the car's
velocity against its route point's direction: 1 along it (0 counts as
along), -1 against. Going the chase's way resets the timer. Otherwise,
after 8 seconds the chase takes the car's direction.

## The cops

RequestPursuit (`0x00225078`) never grants a car that has finished.

In Be A Cop, only the player's cop is granted (one chasing, two for
the roadblock), and each ask makes a new pursuit.

Otherwise, it first walks PursuitList, counting the chases of AI cars
and finding this car's. A car whose chase has given up is refused.
Then the limits are:

| who is chased | cops chasing | cops at the roadblock | granted when |
|---------------|--------------|-----------------------|--------------|
| split screen, a player | 1 | 1 | no cop yet |
| split screen, an AI car | 1 | 0 | no cop yet; a new chase only while no AI car is chased |
| one player, the player | 2 (1 once the World's CopCarPos is 3 or more) | 2 | no cop yet, or under the limit once backup was called |
| one player, an AI car | 1 | 0 | no cop yet; a new chase only while fewer than two AI cars are chased |

The demo disc allowed one AI chase, not two.

A new pursuit gets the first free id and says StartPursuitSpeech. For a
player (the cop's in Be A Cop), it loads the next NIS with the car's
ticket count. A join says JoinPursuitSpeech instead. Either way the
limits are stored, the cop is added and its pursuit set.

ReleaseAllCops (`0x0022a260`) walks Cops by index while it removes
them. RemoveCopFromPursuit moves the second cop into the first's place,
so with two cops only the first is released. This is retail's, and the
port keeps it. Each cop released that is AI-controlled goes back on
patrol. Then the roadblock is disbanded (with no asks) and the
helicopter let go: unless its word at 960 holds it, the manager's
chopper is no longer busy, follows nothing, and is dropped.

DisbandRoadBlock (`0x0022c5a0`):

- Sends both of the roadblock's cops back on patrol. With `b`, a cop
  within 30 of the chased car is asked to join the chase and, if
  granted, set to HOT_PURSUIT.
- When a player is involved: a single player's chase with no secondary
  speaker takes the roadblock's speaker as its secondary; otherwise the
  speaker goes back to the queue.
- Deletes the roadblock's spike strips and fades its barrels over 2
  seconds.
- Drops the roadblock and returns the state machine to none.

RemoveCopFromPursuit looks in Cops first, then in the roadblock's two
places. It clears the cop's pursuit when found, and returns whether it
was. IsCopInPursuit looks in the same places.

SelectPrimaryCop swaps the two cops when the first is more than 30
farther from the chased car than the second.

## The speakers

- GetCopSpeaker: the primary speaker, else the roadblock's, else the
  queue's current one.
- GetSecondaryCopSpeaker: the secondary speaker, else the queue's
  current one.
- IsPlayerInvolved: a player's car is chased, or Be A Cop.

RemovePrimarySpeaker (`0x0022c990`) is called by tAICop::DisableMyCar
when a chasing cop's car is put out within 75 of a player's car:
upset and all but stopped (`b`), or with a tyre blown. It does nothing
for an AI car, or while a roadblock was encountered recently.
Otherwise:

- The primary speaker goes back to the queue.
- The secondary takes its place. With no secondary, the primary
  becomes none when fewer than two cops are chasing, and a newly
  reserved speaker otherwise.
- Then raiseCrashTow (2 in 10), raiseCrash, or raiseFlatTire, each
  with the old speaker and the new one.

RoadBlockEncounteredRecently (`0x00229dd8`) is true:

- when any of the chased car's tyres is blown;
- when the roadblock spawn timer is past the spawn time less 4. The
  spawn time is doubled while a helicopter is requested.

## The roadblocks (12i-1)

Update calls UpdateRoadBlocks (`0x00229b58`) through
`gPursuitUpdateRoadBlocksFn`, after the roadblock state machine has
stepped. In order:

1. With a roadblock and a blown tyre, the roadblock is disbanded (with
   1). In Be A Cop, when the chased car is an AI racer's, the player's
   cop first says the spike strip burst it (`0x0020b460`, with 0).
2. With a roadblock still there that MonitorRoadBlock says the car has
   got by, the roadblock is passed with 1.
3. With a roadblock still there, its disband timer counts down by the
   frame's seconds. Until it reaches 0 or less, Update stops here. Then
   it is set to 0, and the roadblock is passed with 0 when the car has
   left it behind. That means the forward track distance (a less b,
   plus the track's length when below 0) is more than 0.8 of the
   track's length (gp-27064). With the chase direction 1, a is 100
   past the roadblock and b is the car. Otherwise a is 100 past the car
   and b is the roadblock. So the car is 100 to 100 plus a fifth of the
   track past the roadblock, the chase's way. Otherwise Update stops
   here. A roadblock passed here goes straight on to step 5.
4. With no roadblock at step 3, including one steps 1 and 2 took down,
   in Be A Cop the spawn timer is set to 0. Otherwise it counts down by
   the frame's seconds and stops at 0.
5. With still no roadblock and behaviour bit 8, a roadblock is asked
   for (RequestRoadBlock). In Be A Cop it is always asked for.
   Otherwise roadblocks must be on, the tyres whole, a player involved
   and the spawn timer 0 or less.

Passing a roadblock sets the spawn timer to the manager's
fRoadBlockSpawnTime. Without a blown tyre, RoadBlockDefeated runs with
the same `b`. Then the roadblock is disbanded (with 1). Step 5's "no
roadblock" always holds: each earlier step either stops Update or
leaves no roadblock.

MonitorRoadBlock (`0x0022c390`) says no with a tyre blown. For a
player's car, it looks for the first of the roadblock's two cops whose
car the chased car has hit:

- A car under REAL_CONTROL gets RealDriver::ForceEBrakeStop for 5 s,
  through `gRealDriverForceEBrakeStopFn`. Since 12i-3 that holds the
  e-brake for up to 5 s while the car is faster than 20 mph.
- An AI_CONTROL car in PHYSICS_MOVEMENT or MELLOW_MOVEMENT has its
  PsychoDriver's EBrakeTimer set to 4 s.
- Above 40 mph either way (17.881 m/s, gp-26948), when the player's
  zone request (1, 0, 1, 1, `0x00177c88`) agrees, the bust sound plays
  at the car (`0x001e5688`).

Only the first such cop counts. Then, to have got by, the car must be
within the road's width of the roadblock's spot, on the ground plane.
It must also be more than 5 past it, the chase's way. "Past" is the
car's distance along the roadblock's route point's direction, less the
roadblock's own.

RoadBlockDefeated (`0x00229970`) acts only when a player is involved:

- When a player's car's chase should be called off
  (ShouldPursuitBeCalledOff), the chase gives up.
- Otherwise the roadblock-failed speech runs (`0x0022b3f8`, with `b`).
  - A player's car scores DODGE_ROADBLOCK.
  - When the player's own car (MyCar, which need not be the chased
    one) goes faster than 20 m/s within 20 of the first cop's car, in
    3D, the replay keeps it: RegisterInterestingEvent, 10 s,
    "DodgeRoadblock". Retail calls it with no test. The port skips it
    while `pReplayManager` is NULL.
  - Outside Be A Cop, a chase in LSS_FOLLOW_BACKWARDS waits longer for
    the next roadblock: the spawn timer gets another
    fRoadBlockSpawnTime, and behaviour bit 0x20 is set. This happens
    in a 2-lap race, or (other lap counts) when World::Random(3) is
    below 2 with New624 set. A point-to-point race counts as 1 lap.
  - Retail reads DemoDiscManager.bActive first, and with it set skips
    the lap test. The port has no demo disc.

Whether or not a player is involved, it then sets a behaviour bit by
the roadblock count:

| count | bits set |
|-------|----------|
| 5 or more | 0x80 |
| under 3 | 0x40 |
| 3 or 4, with bHelicopter | 0x110 |

RequestRoadBlock (`0x0022cc38`) is the state machine's, and acts only
at NONE:

- The first time (speech flag 1 clear), the cop's speaker asks for a
  spike strip (behaviour bit 0x10, `0x0020b2f0`) or a roadblock
  (`0x0020b140`), and the flag is set. Later asks speak only in Be A
  Cop: request another roadblock (`0x0020b190`). Each takes 1 while the
  supervisor's timer is within 0.001 of 0 (gp-26944).
- In Be A Cop, behaviour bit 8 is cleared and one of the manager's Be A
  Cop roadblocks is used up. With none left, dispatch says none is
  available (`0x0020b7e8`, BeACopId) and the machine stays at NONE.
- Otherwise the machine goes to CALLED_FOR_ROAD_BLOCK, with 8 s on its
  timer. When the timer runs out it calls CreateRoadBlock (below).

## Making a roadblock (12i-2)

CreateRoadBlock (`0x00229e30`) is tPursuit's:

1. With one roadblock cop allowed (nMaxRoadBlockCops 1), behaviour bit
   0x10 (a spike strip) is set first.
2. It asks the manager for a roadblock, passing the chase's direction,
   and keeps what comes back, NULL included.
3. When there is one, the disband timer is set to 3.5 and the roadblock
   count goes up.
4. With a player involved, the roadblock reserves a cop speaker, and
   RoadBlockSetSpeech (`0x0022b5d0`) speaks.

The manager's CreateRoadBlock (`0x00226298`) returns NULL when:

- no roadblock data is loaded, or roadblocks are off;
- FindCopsForRoadBlock finds fewer than nMaxRoadBlockCops cops;
- tTrackGraph::FindRoadBlock finds no spot. It looks 600 to half the
  track's length from the chased car, ahead for a chase direction of
  exactly 1.0 and behind for any other.

Otherwise the layout places the cops. Each cop placed is the
roadblock's and gets tAICop::SetRoadBlock with its index (0 or 1). With
bit 0x10, AddSpikeStrip (`0x002276d0`, 12j) lays the strip from the
belt's position less its vector to the position plus it. It takes the
record's index and a time of -1.

FindCopsForRoadBlock (`0x00226810`) clears both of its slots, then goes
through the manager's AI cops in order and stops once it has `n`. A cop
counts when:

- it is settled (its logic state is the desired one);
- it is 250 m or more from every player, on the ground plane;
- it wants limbo (but is not held there, LSS_LIMBO_DISABLED) or a radar
  trap. The jump table at `0x002bd1e0` takes no other state.

The escape lane (`0x0022ca78`) is 3.75 wide for the first roadblock,
then 3.5, 3.0 and 2.75 for the fourth on. The manager's difficulty adds
0.5, 0 or -0.25 (`0x002bd450`).

### The layout

The layout (`0x00226478`) picks a list of items across the road from
its left edge: 0 the left lane, 1 the right lane, 2 a spike strip, 3 a
cop, 4 a gap, 5 barrels, and 6 the end. The lists are at `0x0031e938`
to `0x0031ea18`.

A spike strip goes in with bit 0x10 or one cop. Then the record's
spike side (its bits) picks the list. A side of 0 is chosen with
World::Random(2): nonzero gives 1, the left.

| roadblock | side 1 | side 2 |
|-----------|--------|--------|
| one cop | 0 2 3 | 3 2 1 |
| strip, Random(4) is 0 | 3 2 3 1 | 0 3 2 3 |
| strip, bSpikeStrips and Random(2) is 0 | 0 2 3 5 3 | 3 5 3 2 1 |
| strip, otherwise | 0 2 3 4 3 | 3 4 3 2 1 |
| no strip, bSpikeStrips | 0 3 5 3 1 | |
| no strip | 0 3 4 3 1 | |

The plan (`0x0024fb78`) sizes the items to the roadblock's road width
in two passes. Pass 1 sums the items:

- a lane is the escape lane's width;
- a gap is 0.8;
- a strip is 8 segments of 0.65;
- a cop is its car's width across the road (`0x0024fae8`): |cos| of
  its angle times the manager's largest cop car length, plus |sin|
  times its width. The angle starts at RoadBlockCopAngle, 8192 (45
  degrees), which the plan's static constructor sets;
- barrels are nothing yet.

Then the room left is shared out:

1. Wider than the road by more than one car, with two cops or more,
   the last cop goes.
2. The cars are turned to 45 degrees (`0x0024fb50`). Each adds its
   width there less its width at the start angle, which is nothing
   while RoadBlockCopAngle is 8192.
3. Barrels fill the room left, 3 each, when more than 3 is left. There
   are at most 10.
4. Spike strips take the room left in segments of 0.65: n + 8 in all,
   where n is the room's (truncated). No room (n of 0) keeps the 8.
   Otherwise the total is held between 3 and 20 segments per strip.
5. What is left is shared between the lanes. With both lanes, the
   difference of the route point's two widths moves to the wider side:
   - the left wider: from the right lane, or the right lane is closed
     (0), the left getting nothing more;
   - the right wider: from the left lane, or the left is closed and the
     right lane is doubled (retail's).

Pass 2 puts the items in a ring of 30 words (29 used; retail's push
says 0 when it is full, and nothing reads it):

- a lane and its width;
- a gap;
- a strip and its share of the segments, the remainder to the last;
- a cop and its angle, for each cop still kept;
- a barrels word for each barrel.

The layout walks the ring along the roadblock's L (across the road),
from the route point less its LeftWidth:

- A lane moves on by its width. The escape lane's spot is half the
  width past that (retail's: past the lane, not at its middle).
- A gap moves on 0.8.
- A strip moves on its segments times 0.65. The belt's spot is its
  middle, and the belt's vector half its length along L.
- A cop moves on its car's width at its angle, and its spot is the
  middle. The first faces L's angle plus the angle, the second L's
  angle plus 0x8000 less it.
- A barrel moves on 3. It is spawned at its middle, put on the track
  (get_vector_on_track).

The layout returns the cops placed.

## The barrels and spike strips

A barrel's spawn (`0x0024f0a8`) takes the first free slot:

1. FindSmokeableInfo looks up "CS_RoadBlock_Barrel". With none, the
   slot is skipped, so no barrel spawns.
2. The info's mass is scaled to 10. The first three rows of its inertia
   tensor (all four lanes, VU0) are scaled with it.
3. The smokeable is spawned (`0x0021ed28`): type 0, the hash of
   "ROADBLOCK_BARREL", the spot, angle 0.
4. Its id goes in the slot and is returned. With no free slot, -1.

The port has no smokeables yet, so FindSmokeableInfo is NULL: a
roadblock stands without barrels until the smokeables step.

The BarricadeManager's destructor deletes each barrel still there
through the smokeables (`0x0021ef88`), then frees itself on flags & 1.
Fade gives each barrel the time and marks its collision body as fading
(the byte at 1123). DeleteRoadBlockSpikeStrips (`0x00227be8`) calls
BlinkBlinkPoof on each spike strip in the manager's list whose
roadblock id (24) matches.

## Seams

Bound in `main.c` since 12h-1:

- `gPursuitRemoveCopFromPursuitFn`, to RemoveCopFromPursuit, for
  tAICop::ClearPursuit;
- `gPursuitRemovePrimarySpeakerFn`, to RemovePrimarySpeaker;
- the two tables, through `pursuit_install_vtables` and
  `barricade_install_vtables`.

Bound since 12h-2: `gCopManagerRequestPursuitFn`, to
`copmanager_request_pursuit`, and `gPursuitUpdateFn`, to
`tpursuit_update`. Cops now start chases in a race, and each chase runs
its Update.

Bound since 12i-1: `gPursuitUpdateRoadBlocksFn`, to
`tpursuit_update_road_blocks`. A chase now asks for roadblocks.

Bound since 12i-2: `gPursuitCreateRoadBlockFn`, to
`tpursuit_create_road_block`. An asked-for roadblock is now made: its
cops are sent to their spots (SetRoadBlock), with no barrels (no
smokeables) and no spike strip (12j).

Not bound yet:

- The cop speech manager's calls do nothing while NULL:
  StartPursuitSpeech, JoinPursuitSpeech, CopBackOffSpeech, raiseCrashTow,
  raiseCrash, raiseFlatTire and raiseSuperRequest. Update's speeches do
  the same: DeclarePursuitSpeech, RaiseBackupSpeech,
  BeginPursuitCollisionSpeech, raisePursuitCopHit and
  raiseSuspectCrashTraffic. The roadblocks' speeches do the same:
  raiseSpikeStripTireBlow, the roadblock-failed speech,
  raiseRequestAnotherRoadblock, raiseSpikeStripRequest,
  raiseRoadblockRequest and raiseDispatchRoadBlockNA. So does
  RoadBlockSetSpeech, `gPursuitRoadBlockSetSpeechFn`, and the bust
  sound (CollisionSound::PlayBustRoadBlock).
- AddSpikeStrip, `gCopManagerAddSpikeStripFn`, lays nothing while NULL
  (12j).
- FindSmokeableInfo, `gFindSmokeableInfoFn`, finds nothing while NULL,
  so no barrel spawns. The smokeables' spawn, `gSmokeableSpawnFn`,
  aborts if reached. Both wait for the smokeables step.
- RealDriver::ForceEBrakeStop, `gRealDriverForceEBrakeStopFn`, does
  nothing while NULL. `main.c` binds it since 12i-3, which ported
  retail's float timer into RealDriver.
- Update's later slices do nothing while NULL: CreatePullover (12l)
  and UpdateChopper (12k). So a caught car is not pulled over.
- So does `gPlayerLoadNextNisFn`, the Busted NIS (12l).
- These abort if reached:
  - the helicopter's word at 960 and FollowThisCar (12k);
  - the barrels' delete and the body's fade byte (the smokeables
    step);
  - BlinkBlinkPoof (12j).

  Nothing makes a helicopter, a barrel or a spike strip before then.

## The check

`tools/pursuit_check.py` runs retail's code in mipsemu and the port in
`tools/src/pursuit_test.c` on the same script. The script builds:

- a manager, with its speaker queue and slot pool;
- six cars (two players), with their type info, ride info and racing
  car;
- eight cops (two of them players' cops), four roadblocks, six spike
  strips, two helicopters and sixteen collision bodies.

The acceleration table, the drive targets, the scores and the cops'
patrol and state setters are logging stand-ins on both sides, as are
the speech calls, the NIS, the helicopter's calls, the barrel delete
and the fade byte. bRandom and bStringHash run as shipped. The ops
cover:

- GetTopSpeed for eight tables, including a NaN, an infinity, -0 and a
  cut at exactly 100 km/h, with zero, negative and NaN drag and a zero
  mass;
- the constructor at each difficulty, in Be A Cop, for a player, an AI
  car and none, in the AI demo, with the supervisor armed and with an
  empty speaker queue;
- the state times for each table entry over thirteen race lengths,
  including the clamps' edges, NaN and the infinities;
- every state switch each way, and straight to LEVEL2 with nothing set;
- the supervisor's gates: 7 RC states, 7 timers, roadblocks on and off,
  and 4 seeds;
- the give-up on each car, the transitions, and the speeds in each unit;
- ReleaseAllCops over nine cop layouts and three helicopter states, and
  with a roadblock, its cop far and near;
- DisbandRoadBlock over chased car, Be A Cop, players, secondary
  speaker, room in the queue and `b`. Also nine distances to the
  chased car, a cop only in the roadblock's second place, and an empty
  roadblock;
- RemoveCopFromPursuit and IsCopInPursuit on 18 layouts, including NULL
  and a cop in both places;
- RemovePrimarySpeaker and RoadBlockEncounteredRecently over the
  blown-tyre bits, helicopter state and timer edges;
- SelectPrimaryCop at its 30 boundary;
- the speakers and every one-liner;
- deleting pursuits, with and without room for the speakers, with
  barrels in the first and last places, and with id -1;
- the spike strips by roadblock id, and the barrels' fade with NaN and
  huge times;
- the Update's parts:
  - NotInChasingState over every state;
  - Level0SubStates at the 16 and 3 edges;
  - the call-off over each gate and the 2000 edge;
  - the roadblock machine over state, timer, frame and roadblock;
  - the barrels counting down through NaN, -0 and huge times;
  - 33 history updates;
  - both drive targets at their 20 and 1 edges, full and from empty,
    then 40 frames on;
  - the early check over 15 layouts;
- IsCopNearby over every logic state, NIS, distance edges and Be A Cop,
  and DidRecentlyCollideWithCop over seven collision sets;
- IsChasedCarStoppable:
  - each gate;
  - about 30 setups beside a slow car, including the 10 mph and 0.1 m/s
    edges, the up-axis edge, blinking and NaN;
  - with no first cop;
  - Be A Cop at each difficulty, with one and two players, at the
    radius and the 30 m edges;
- then Update frame by frame (the movers, targets, cops and manager
  dumped each frame):
  - the timer out, to exactly 0, and given up;
  - the barrels;
  - split screen and finish reasons;
  - a blown tyre, race type 3, and the call-off;
  - the top speed;
  - caught in four states;
  - the roadblock called and set;
  - the early check by state;
  - the landmarks;
  - Be A Cop with the chase direction at the dot product's 0 edge;
- RequestPursuit: seven configurations, each with 14 asks, then
  the give-up, backup, CopCarPos, each finish reason, Be A Cop with the
  player's cop in four places, and split screen;
- the roadblocks, last (12i-1). Each car has a PsychoDriver block (its
  e-brake timer dumped), each roadblock a route point. The replay
  manager, the zone request, World::Random and the new speeches are
  logging stand-ins. UpdateRoadBlocks runs unstubbed, and
  GetForwardTrackDistance is coputil's copy:
  - RequestRoadBlock over the states, the speech flag, five behaviour
    sets, seven supervisor timers around 0.001 (NaN, the infinity),
    and four Be A Cop roadblock counts, each in and out of Be A Cop,
    and the three speakers;
  - MonitorRoadBlock over 13 spots by five chase directions, around
    the width and the 5 edge. Then a diagonal road at four widths, a
    roadblock off its route point's line, and a blown tyre. Then nine
    control and movement modes by three collision pairs, the 40 mph
    edge by three zone answers, missing cops, and an AI car's chase;
  - RoadBlockDefeated for four chased cars and Be A Cop, nine
    roadblock counts with the helicopter on and off, the call-off near
    a 4-lap race's end, the replay event's speed, distance and height
    edges, the player's own car, and 13 follow-backwards cases over
    laps, point-to-point, New624 and the random answer;
  - UpdateRoadBlocks with no roadblock (the timer's edges, -0 and a
    zero frame), a blown tyre in and out of Be A Cop, a cop near enough
    to join the chase, got by, and the disband timer by distance and
    chase direction (including 2.0);
- the roadblock's making (12i-2). World::GetDistanceToClosestPlayer
  (a scripted distance per car), FindRoadBlock (a scripted
  roadblock), SetRoadBlock, get_vector_on_track (a scripted height),
  FindSmokeableInfo, the smokeables' spawn, AddSpikeStrip and
  RoadBlockSetSpeech are logging stand-ins. The plan's code, the
  barrels' spawn, bScaleAdd, bToPolar, bSin and bCos run as shipped,
  and the plan's static constructor runs once:
  - the escape lane over seven roadblock counts (-1 and the largest
    int too) and the three difficulties;
  - the cop car's width at 12 angles for five car sizes (zero, NaN and
    negative too), and the 45-degree angle;
  - the plan for the ten layouts and 22 others (none, lanes alone, one
    to three cops, two and three strips, two barrels' items, gaps
    alone, items past 6 and below 0, a ring that fills), on ten road
    widths (0 and NaN too) by seven splits of the route point. Also
    four escape lanes (0, -1 and 1e-7 too), five starting angles, and
    six roads around exactly 3 to spare for barrels (less than 0 too);
  - FindCopsForRoadBlock for five counts and four manager sizes,
    distances around 250 (NaN and the infinities too), every desired
    state by five sub-states, unsettled cops, and mixed lists;
  - the barrels' spawn with and without the info, all ten slots and
    an eleventh, three ids, and six masses and tensors (NaN, a tiny
    and a huge mass too);
  - the layout over eight behaviour and cop-count sets, the four spike
    sides, bSpikeStrips and six random answers. Then escape lanes by
    count and difficulty, five roads (NaN too), the barrels' slots full
    and no info;
  - the manager's CreateRoadBlock over ten flag, cop-count and
    direction sets (NaN, 0 and just over 1 too), a diagonal road, no
    data, roadblocks off, a cop too near, no spot, and a NaN track;
  - tPursuit's for two chased cars and Be A Cop, four cop-count and
    flag sets, with and without a spot, followed backwards, and twice.

58562 operations, 86269 lines, 0 differ.

`--mutate` runs out of the tree through `mutpar`: 691 mutations, 683
caught and eight equivalent:

- `super_lt` (`<=` to `<` against 0.001): within 25 of -50 the timer
  less -50 is exact (Sterbenz), so it is a multiple of 2^-18, which
  0.001f is not. Further off, the difference is 25 or more. It never
  equals 0.001f.
- `bar_dtor_free`: the barricades' one caller passes 3.
- `remove_rb_too`: the roadblock's loop runs only while nothing is
  found, so a cop found in Cops skips it either way.
- `ur_req_has_rb` (UpdateRoadBlocks' request without its roadblock
  test): every earlier step either returns or takes the roadblock
  down, so the test always sees NULL.
- `plan_full_ret` (push's answer changed): its one caller, the builder,
  never reads it (`0x0024ff14` to `0x0024ffe8`).
- `plan_pop_mod` (pop's wrap taken out): a plan is filled once from
  empty before it is read, so the head never passes 29.
- `bp_diff_lt` and `bp_neg_lt` (the lanes' moves tested against the
  other lane): with both lanes in the layout, each is the escape lane
  plus the same share there, so the two are equal.

At 12i-2, four older mutations matched more than once (`ctor_disband`,
`disband_pi`, `super_eps` and `super_lt`). Each now quotes enough
around it to be unique, and each is caught or equivalent as before.

The checkers that link `copmgr.c` still have 0 differ: carmode, cop,
copdriver, copmanager, copmover, drivecam, hudfeatures, hudrender,
raceupdate and trackgraph (12h-1). After 12h-2, cop and copdriver, the
other two that link `pursuit.c`, still have 0 differ.
After 12i-1, cop, copdriver and psychodriver (whose e-brake note
moved) still have 0 differ. After 12i-2, cop and copdriver still have
0 differ.
