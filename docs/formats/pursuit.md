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
asks. Update (`0x00229288`) and the state machines under it are 12h-2's;
the roadblock and helicopter calls are 12i's and 12k's.

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

## The record

Retail's tPursuit is 1600 bytes from the manager's slot pool
(gp-15644), against the demo's 1216. The differences that matter:

- `nPursuitId` (a byte at 1480) is the manager's PursuitsById slot. The
  destructor sets it to -2.
- `pBarricades` (1472) is a BarricadeManager the constructor makes with
  `bMalloc(64, "CopMgr", 0, 16)`.
- The two speakers (1496, 1500) are the cop speech manager's voices,
  with 5 for none.
- `New1556` is 10 from the start; only Update reads it (12h-2).
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

GetSpeedMPHOrKPH gives the chased car's speed in km/h for a player
whose units are metric, and in mph otherwise, including for every AI
car.

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

## The barrels and spike strips

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

Not bound yet:

- `gCopManagerRequestPursuitFn` stays NULL until Update is in (12h-2).
  Until then no cop is granted a chase, and no pursuit is made in a
  race.
- The cop speech manager's calls do nothing while NULL:
  StartPursuitSpeech, JoinPursuitSpeech, CopBackOffSpeech, raiseCrashTow,
  raiseCrash, raiseFlatTire and raiseSuperRequest.
- So does `gPlayerLoadNextNisFn`, the Busted NIS (12l).
- These abort if reached:
  - the helicopter's word at 960 and FollowThisCar (12k);
  - the barrels' delete and the body's fade byte (12i);
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
- RequestPursuit, last: seven configurations, each with 14 asks, then
  the give-up, backup, CopCarPos, each finish reason, Be A Cop with the
  player's cop in four places, and split screen.

22906 operations, 51040 lines, 0 differ.

`--mutate` runs out of the tree through `mutpar`: 265 mutations, 262
caught and three equivalent:

- `super_lt` (`<=` to `<` against 0.001): within 25 of -50 the timer
  less -50 is exact (Sterbenz), so it is a multiple of 2^-18, which
  0.001f is not. Further off, the difference is 25 or more. It never
  equals 0.001f.
- `bar_dtor_free`: the barricades' one caller passes 3.
- `remove_rb_too`: the roadblock's loop runs only while nothing is
  found, so a cop found in Cops skips it either way.

The checkers that link `copmgr.c` still have 0 differ: carmode, cop,
copdriver, copmanager, copmover, drivecam, hudfeatures, hudrender,
raceupdate and trackgraph.
