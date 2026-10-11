// pursuit -- tPursuit, one car's chase, with its history and roadblock
// state machine. The struct and its records are copmanager.h's; this is
// copmgr.obj's tPursuit code from retail (SLES_507.31).
//
// The manager makes a pursuit in RequestPursuit, from its slot pool, and
// deletes it (copmgr.c) through the table at 0x002bd460. RequestPursuit
// and the two calls under it are tCopManager's, but are here with what
// they make, so copmgr.c's harnesses need none of this; IsCopNearby and
// DidRecentlyCollideWithCop are here with IsChasedCarStoppable for the
// same reason. Making a roadblock (12i-2) and the helicopter (12k) are
// seams.

#ifndef PURSUIT_H
#define PURSUIT_H

#include <stdint.h>

#include "copmanager.h"

struct Car;
struct Player;

// gp-15600, 0x00331c00: how long a roadblock takes to spawn, set by each
// pursuit's constructor from {20, 15, 10} by the manager's difficulty.
extern float fRoadBlockSpawnTime;

// GetTopSpeed(Car *), 0x00231338 (coputil.obj's, here with its one
// caller, the constructor): from 100 km/h up in steps of 5 km/h
// (in metres a second), the first speed short of 400 km/h at which the
// car's acceleration table gives less than the drag, speed squared times
// Aero.Drag over Body.Mass, less one step. 400 less a step when none is.
float get_top_speed(struct Car *car);

// ------------------------------------------------- the small records

// tPursuitHistory's constructor (0x0022cee0): the table, thirty zero
// velocities and times, nCount 0. Its destructor (0x0022cf68) puts the
// table back and frees nothing a pursuit owns.
tPursuitHistory *tpursuithistory_construct(tPursuitHistory *h);
void tpursuithistory_destruct(tPursuitHistory *h, int32_t flags);

// tRoadBlockStateMachine's constructor (0x0022cc00), destructor
// (0x0022cc18) and DisbandRoadBlock (0x0022cdd0): State back to none.
tRoadBlockStateMachine *trbsm_construct(tRoadBlockStateMachine *s,
                                        tPursuit *p);
void trbsm_destruct(tRoadBlockStateMachine *s, int32_t flags);
void trbsm_disband_road_block(tRoadBlockStateMachine *s);

// ------------------------------------------------------- tPursuit

// 0x00228fc8. The two drive targets, the history, the state machine and
// the barricades are built; the timers start at retail's values,
// fRoadBlockSpawnTime is set by the manager's difficulty, and the chased
// car (if any) gives its top speed and, as a player's, a cop speaker.
// Then SwitchPursuitState to LEVEL3 in the AI demo, LEVEL0 otherwise.
tPursuit *tpursuit_construct(tPursuit *p, int8_t id, struct Car *car);

// 0x00229198: every cop released, a player's speakers given back, the id
// set to -2, the barricades deleted through their table, and the slot
// freed back to PursuitSlotPool on flags & 1.
void tpursuit_destruct(tPursuit *p, int32_t flags);

// SwitchPursuitState, 0x00229fe8: the state, its timer from the table at
// 0x0031c570 scaled by the race's length, and each state's HUD level,
// sub-state and behaviours. LEVEL2 and LEVEL3 may call the supervisor;
// END_PURSUIT_GIVE_UP backs the cops off and releases them.
void tpursuit_switch_state(tPursuit *p, ePursuitState s);

// 0x00229f70: `f` times the race's length (the track times the laps, or
// once point to point) clamped to 14000..42000, over 56000, plus a
// quarter.
float tpursuit_state_time(float f);

// DoStateTransition, 0x0022a190: up a level (LEVEL3 stays), and 1 with
// nothing switched for END_PURSUIT_GIVE_UP.
int32_t tpursuit_do_state_transition(tPursuit *p);

// GetSpeedMPHOrKPH, 0x0022a220: the chased car's ForwardSpeed (retail's
// car+960) in the player's units, mph for an AI car.
float tpursuit_get_speed_mph_or_kph(const tPursuit *p);

// ReleaseAllCops, 0x0022a260. Retail walks Cops by index while removing
// them, and RemoveCopFromPursuit moves the second down into the first's
// place, so of two cops only the first is released.
void tpursuit_release_all_cops(tPursuit *p);

// 0x0022a310: the helicopter let go, unless its word at 960 holds it:
// bChopperBusy off, FollowThisCar(NULL), ECS_NO_CHOPPER and no
// pChopper. Nothing with no helicopter. tPlayerCop's Think's.
void tpursuit_release_chopper(tPursuit *p);

// DisbandRoadBlock, 0x0022c5a0: the roadblock's cops back on patrol (and
// with `b`, those within 30 of the chased car asked to join the chase),
// its speaker passed on or given back, its spike strips and barrels
// gone, and the state machine back to none.
void tpursuit_disband_road_block(tPursuit *p, int32_t b);

// RemoveCopFromPursuit, 0x0022c740: the cop out of Cops (the second moved
// down when the first goes) or else out of the roadblock; 1 if found,
// when the cop's pursuit is cleared too.
int32_t tpursuit_remove_cop_from_pursuit(tPursuit *p, tCop *c);

// 0x0022c920: the cop is in Cops or the roadblock.
int32_t tpursuit_is_cop_in_pursuit(const tPursuit *p, const tCop *c);

// RemovePrimarySpeaker, 0x0022c990: a player's chase loses its primary
// cop's voice to the secondary's, or a new one; then the wreck's speech,
// a tow one time in five (`b`) or a flat tyre.
void tpursuit_remove_primary_speaker(tPursuit *p, int32_t b);

// RoadBlockEncounteredRecently, 0x00229dd8.
int32_t tpursuit_road_block_encountered_recently(const tPursuit *p);

// SelectPrimaryCop, 0x00229ed0: the two cops swapped when the second is
// more than 30 nearer the chased car.
void tpursuit_select_primary_cop(tPursuit *p);

// GetCopSpeaker (0x0022ab30) and GetSecondaryCopSpeaker (0x0022ab70).
uint32_t tpursuit_get_cop_speaker(const tPursuit *p);
uint32_t tpursuit_get_secondary_cop_speaker(const tPursuit *p);

// IsPlayerInvolved, 0x0022bbd8: the chased car is a player's, or Be A Cop.
int32_t tpursuit_is_player_involved(const tPursuit *p);

// The one-liners, 0x0022d210 to 0x0022d338.
void     tpursuit_add_cop(tPursuit *p, tCop *c);
int32_t  tpursuit_get_num_cops(const tPursuit *p);
int32_t  tpursuit_get_pursuit_id(const tPursuit *p);
eRoadBlockState tpursuit_get_road_block_state(const tPursuit *p);
float    tpursuit_get_chase_direction(const tPursuit *p);
eChopperState tpursuit_get_chopper_state(const tPursuit *p);
int32_t  tpursuit_is_pursuit_over(const tPursuit *p);
int32_t  tpursuit_has_called_for_backup(const tPursuit *p);
int32_t  tpursuit_is_backup_needed(const tPursuit *p);
tCop    *tpursuit_get_other_cop(const tPursuit *p, const tCop *c);
int32_t  tpursuit_is_primary_car(const tPursuit *p, const struct Car *car);
int32_t  tpursuit_is_primary(const tPursuit *p, const tCop *c);
int32_t  tpursuit_is_behaviour_allowed(const tPursuit *p, uint32_t a);
void     tpursuit_disallow_all_behaviours(tPursuit *p);
void     tpursuit_disallow_behaviour(tPursuit *p, uint32_t a);
void     tpursuit_allow_behaviour(tPursuit *p, uint32_t a);
int32_t  tpursuit_get_current_landmark(const tPursuit *p);
int32_t  tpursuit_get_pursuit_level_for_hud(const tPursuit *p);

// --------------------------------------------------------- the Update

// tPursuit::Update, 0x00229288, from the manager's PursuitManagement each
// frame; nonzero when the pursuit is over and is to be deleted. In order:
//   - the barrels' fades count down, and the chased car's landmark is
//     looked up again;
//   - a car with a blown tyre counts New1556 down;
//   - with more than one player, a car that has finished ends it;
//   - in Be A Cop with two players, the chase direction follows the car's
//     velocity along its route, flipping after 8 s against it;
//   - outside Be A Cop: the car's top speed so far goes to every cop car
//     on its CopMover, the drive targets are updated and the primary cop
//     chosen; a finished car ends a race of type 3; the chase is called
//     off near the end of a long race (ShouldPursuitBeCalledOff), and the
//     state's timer runs while there are cops (or from LEVEL3 on), taking
//     the next state at 0;
//   - while still chasing, a car the cops can stop is pulled over: the
//     pullover (12l), SPEEDER_CAUGHT and every cop released;
//   - the roadblock state machine, UpdateRoadBlocks and the
//     helicopter (12k); then, outside Be A Cop, LEVEL0's speeches and the
//     early collision check through LEVEL1, and END_PURSUIT_GIVE_UP is
//     over.
int32_t tpursuit_update(tPursuit *p);

// Level0SubStates, 0x002295d8: the pursuit declared (sub-state 0 to 1)
// under 16 s left at LEVEL0, and backup called (1 to 2) under 3.
void tpursuit_level0_sub_states(tPursuit *p);

// ShouldPursuitBeCalledOff, 0x0022c2d0: never with a blown tyre, point to
// point, a free run or under 4 laps; else when the laps left, less the
// car's RacingCar word at 32, come to 2000 or less round the track.
int32_t tpursuit_should_pursuit_be_called_off(const tPursuit *p);

// UpdateDriveTargets, 0x0022a360. The chased car's position goes on the
// end of the far target, as a new point once the last two are 20 apart
// (the first dropped at 20 points), else over the last; then the history
// takes its velocity; then the near target the same, every 1.0. Retail's
// float argument is never read: the history gets WorldTimeElapsed.
void tpursuit_update_drive_targets(tPursuit *p, float dt);

// tPursuitHistory's Update, 0x0022cf90: the velocities and times moved
// down a place, `vel` and `dt` put first, nCount up to 30. Retail then
// sums the times from the newest until they reach 0.65 (gp-15596) and
// returns `pos` through `out`; the sum is never used, and UpdateDriveTargets
// drops `out`.
void tpursuithistory_update(tPursuitHistory *h, bVector2 *out,
                            const bVector2 *pos, const bVector2 *vel,
                            float dt);

// tRoadBlockStateMachine's Update, 0x0022cdd8: the timer down to 0 while
// there is a state, and a called-for roadblock made (CreateRoadBlock,
// 12i-2) once it is 0, the state ROAD_BLOCK_SET if one was.
void trbsm_update(tRoadBlockStateMachine *s);

// DoEarlyChaseCollisionCheck, 0x0022aba0: the first time a player's car
// hits something in the chase. Before the pursuit is declared the
// collision speech; else hitting the primary cop's car, or any cop's,
// goes to LEVEL2 (the first with its speech), and anything else is
// traffic: its speech, and LEVEL1 from LEVEL0.
void tpursuit_do_early_chase_collision_check(tPursuit *p);

// IsChasedCarStoppable, 0x0022bea0: whether the cops have caught the car,
// never without tickets, while it is pulled over, poofed or finished. In
// Be A Cop the player's cop must be slower than 15 mph when the car is
// blinking (a player's on its reset frames, an AI one within 30), or
// within the capture radius (10, 11 with two players) and has a blown
// tyre and stopped, is on its side under 10 mph, or held under the
// difficulty's speed until fCatchCarTimer runs out (which climbs back to
// 2 s otherwise). Elsewhere: New1556 run out; under 10 mph with a cop near
// (or, with none, an AI racer) until fCatchCarTimer runs out, or in its
// last second with a cop just hit; a blown tyre and stopped; blinking but
// for a player off its reset frames; or on its side under 10 mph.
int32_t tpursuit_is_chased_car_stoppable(tPursuit *p);

// tCopManager's IsCopNearby (0x00225d30) and DidRecentlyCollideWithCop
// (0x002286b8), here with their one caller. IsCopNearby: in Be A Cop the
// player's cop within `d` (none here is not); else any cop wanting to be
// disabled, on a trap, a roadblock, patrol, a chase or a guard, whose car
// is not a player's in a NIS. DidRecentlyCollideWithCop: DidTheseCarsCollide
// with any cop's car.
int32_t copmanager_is_cop_nearby(tCopManager *m, struct Car *car, float d);
int32_t copmanager_did_recently_collide_with_cop(tCopManager *m,
                                                 struct Car *car);

// ------------------------------------------------------ the roadblocks

// tRoadBlockStateMachine's RequestRoadBlock, 0x0022cc38: with no state,
// the cops' first call for a roadblock (a spike strip's with behaviour
// 0x10) or, in Be A Cop, the call for another, each with the supervisor's
// timer at 0 as its bool. Be A Cop also takes the behaviour 8 away and
// spends one of the manager's roadblocks, or says there is none and
// calls nothing. Otherwise CALLED_FOR_ROAD_BLOCK, 8 s on its timer.
void trbsm_request_road_block(tRoadBlockStateMachine *s);

// MonitorRoadBlock, 0x0022c390: 1 once the chased car, its tyres whole,
// is within the roadblock's road width of its spot and more than 5 m
// past it along the road (its route point's direction, by
// fChaseDirection). A player's car that hits one of the roadblock's cops
// first is braked: a RealDriver's ForceEBrakeStop for 5 s, an AI car's
// e-brake timer (PsychoDriver's, under physics or mellow movement) 4 s;
// and above 40 mph, if the player's zone 1 is granted, the bust sound.
int32_t tpursuit_monitor_road_block(tPursuit *p);

// RoadBlockDefeated(bool), 0x00229970: when a player is in the chase,
// either the chase given up (a player's car, ShouldPursuitBeCalledOff)
// or the failed speech, a player's DODGE ROADBLOCK score (and a replay
// event if it got by the first cop within 20 m above 20 m/s), and, while
// the cops follow backwards outside Be A Cop, a longer wait for the next
// roadblock and behaviour 0x20 on a two-lap race or, two times in three,
// with New624. Then the behaviours by nRoadblockCount: 0x40 under three,
// 0x80 from five, 0x110 between with the helicopter on.
void tpursuit_road_block_defeated(tPursuit *p, int32_t b);

// UpdateRoadBlocks, 0x00229b58. A roadblock goes on a blown tyre (with
// the tyre speech for an AI car in Be A Cop), once MonitorRoadBlock says
// it was got by, or when its disband timer has run out and the car is
// more than 0.8 of the track past it; each but the tyre is defeated (with
// a whole tyre) and starts the spawn timer again. With none, the spawn
// timer runs down (held at 0 in Be A Cop), and with behaviour 8 the
// pursuit asks for one: always in Be A Cop, else with roadblocks on, the
// tyres whole, a player in the chase and the timer out.
void tpursuit_update_road_blocks(tPursuit *p);

// --------------------------------------- tCopManager's, making pursuits

// Retail's 0x002244e0: a pursuit of `car` out of PursuitSlotPool, built
// with the id and linked at the tail of PursuitList, under that id in
// PursuitsById. (With -1, retail's PursuitsById[-1] is PursuitList.Prev,
// which the link that follows overwrites.)
tPursuit *copmanager_new_pursuit(tCopManager *m, int32_t id,
                                 struct Car *car);

// RequestPursuit, 0x00225078: whether `c` may chase `car`, which a
// finished car never is. In Be A Cop only the player's cop may, and each
// ask makes a new pursuit. Otherwise a car already given up on is
// refused; split screen allows one cop on a car (a second AI car's chase
// only while no other AI car has one); one player allows the player two
// cops (one once the World's CopCarPos reaches 3), the second only when
// the first called for backup, and the AI cars one cop each, while fewer
// than two other AI cars are chased. A new pursuit starts its speech and,
// for a player, loads the next NIS (gPlayerLoadNextNisFn); a join says
// so. The cop is added either way, with the chase's limits, and its
// pursuit set. Returns 1 when granted.
int32_t copmanager_request_pursuit(tCopManager *m, tCop *c, struct Car *car);

// PossibleCallSupervisor, 0x002253e8: outside the replays, when the
// supervisor timer sits at -50 (within 0.001), roadblocks are on and a
// player is chased, one time in two the supervisor is asked for in the
// pursuit's speaker's voice, and the timer set to 7.
void copmanager_possible_call_supervisor(tCopManager *m, tPursuit *p);

// Player::LoadNextNis(Car *, Car *, int), 0x001761e8, the Busted NIS's
// (12l). NULL loads nothing.
extern void (*gPlayerLoadNextNisFn)(struct Player *pl, struct Car *chased,
                                    struct Car *cop, int32_t tickets);

// ------------------------------------- tCopManager's, making roadblocks

// CreateRoadBlock, 0x00229e30, which Update reaches through
// gPursuitCreateRoadBlockFn: a pursuit with one roadblock cop takes the
// spike strip behaviour 0x10 first. The manager's roadblock is kept in
// pRoadBlock, NULL or not; a roadblock gets 3.5 s on the disband timer
// and counts, and with a player in the chase reserves a cop speaker and
// has RoadBlockSetSpeech said.
void tpursuit_create_road_block(tPursuit *p);

// CalculateRoadBlockEscapeLaneWidth, 0x0022ca78: by the roadblocks made
// so far, 3.75, 3.5, 3.0 and then 2.75, plus 0.5, 0 or -0.25 by the
// manager's difficulty.
float tpursuit_calculate_road_block_escape_lane_width(const tPursuit *p);

// Retail's 0x00226298, the manager's CreateRoadBlock: with the roadblock
// data and roadblocks on, and exactly as many cops found as the pursuit
// may put in a roadblock, the track graph's spot between 600 m and half
// the track ahead (backwards for any direction but 1.0). Its laid-out
// cops are set to it in turn, and with behaviour 0x10 the spike strip
// across the belt (AddSpikeStrip, with the record's index and -1). NULL
// for none.
tRoadBlock *copmanager_create_road_block(tCopManager *m, tPursuit *p,
                                         float dir);

// FindCopsForRoadBlock, 0x00226810 (whose stab says tRoadBlock *, for the
// two-cop buffer it clears): up to `n` AI cops, settled in their state and
// 250 m or more from every player, in limbo (not held there) or at a
// radar trap. Returns how many.
int32_t copmanager_find_cops_for_road_block(tCopManager *m, tCop **out,
                                            int32_t n);

// Retail's 0x00226478: the layout picked -- with a spike strip or one cop,
// by the record's spike side (a random one for none), a random strip in
// the middle one time in four and, with spike strips on, barrels one time
// in two of the rest; else barrels with spike strips on, or none --
// planned (barricade.h) and walked from the road's left edge: the escape
// lane, the spike belt's middle and half-length, each cop's spot and
// heading, each barrel spawned on the ground. Returns the cops placed.
int32_t copmanager_lay_out_road_block(tCopManager *m, tRoadBlock *rb,
                                      tPursuit *p);

// RoadBlockSetSpeech (0x0022b5d0), tPursuit's: main.c binds
// tpursuit_road_block_set_speech (pursuitspeech.h); NULL says nothing.
// AddSpikeStrip (0x002276d0), the spike strips'
// (12j): NULL lays none.
extern void (*gPursuitRoadBlockSetSpeechFn)(tPursuit *p);
extern void (*gCopManagerAddSpikeStripFn)(tCopManager *m, const bVector2 *a,
                                          const bVector2 *b, int32_t id,
                                          float t);


// ---------------------------------------------------------- the seams

// The cop speech manager's (gp-15624, speechmgr.h): NULL says nothing.
//   - StartPursuitSpeech (0x0022afb8), JoinPursuitSpeech (0x0022b288) and
//     CopBackOffSpeech (0x0022b788), tPursuit's own: main.c binds
//     pursuitspeech.h's.
//   - raiseCrashTow (0x0020aa90), raiseCrash (0x0020a9b0), raiseFlatTire
//     (0x0020aa00), each with the old and new speakers, and
//     raiseSuperRequest (0x0020b4b0): main.c binds speechmgr.h's.
extern void (*gPursuitStartSpeechFn)(tPursuit *p);
extern void (*gPursuitJoinSpeechFn)(tPursuit *p);
extern void (*gPursuitBackOffSpeechFn)(tPursuit *p);
extern void (*gSpeechRaiseCrashTowFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseCrashFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseFlatTireFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseSuperRequestFn)(uint32_t speaker);

// Update's speeches, the same: DeclarePursuitSpeech (0x0022ad30),
// RaiseBackupSpeech (0x0022acc0) and BeginPursuitCollisionSpeech
// (0x0022aef8, with the car hit), tPursuit's own; raisePursuitCopHit
// (0x0020a3e0, the speaker and the landmark) and raiseSuspectCrashTraffic
// (0x0020b758, the speaker and 0). main.c binds pursuitspeech.h's and
// speechmgr.h's.
extern void (*gPursuitDeclareSpeechFn)(tPursuit *p);
extern void (*gPursuitRaiseBackupSpeechFn)(tPursuit *p);
extern void (*gPursuitBeginCollisionSpeechFn)(tPursuit *p, struct Car *hit);
extern void (*gSpeechRaisePursuitCopHitFn)(uint32_t speaker, int32_t where);
extern void (*gSpeechRaiseSuspectCrashTrafficFn)(uint32_t speaker,
                                                 int32_t b);

// What Update reaches; NULL does nothing.
//   - tCopManager::CreatePullover (0x00226f30), 12l: the caught car
//     pulled over, with 1.
//   - CreateRoadBlock (0x00229e30): main.c binds
//     tpursuit_create_road_block.
//   - UpdateRoadBlocks (0x00229b58): main.c binds
//     tpursuit_update_road_blocks.
//   - UpdateChopper (0x00229678), 12k.
extern void (*gCopManagerCreatePulloverFn)(tCopManager *m, tPursuit *p,
                                           struct Car *car, int32_t b);
extern void (*gPursuitCreateRoadBlockFn)(tPursuit *p);
extern void (*gPursuitUpdateRoadBlocksFn)(tPursuit *p);
extern void (*gPursuitUpdateChopperFn)(tPursuit *p);

// The roadblocks' speeches, the same: raiseSpikeStripTireBlow
// (0x0020b460, Be A Cop's id and 0), RoadblockFailedSpeech (0x0022b3f8,
// tPursuit's own, with RoadBlockDefeated's bool), raiseRequestAnother-
// Roadblock (0x0020b190), raiseSpikeStripRequest (0x0020b2f0) and
// raiseRoadblockRequest (0x0020b140), each with the speaker and the
// supervisor's bool, and raiseDispatchRoadBlockNA (0x0020b7e8, Be A Cop's
// id). main.c binds pursuitspeech.h's and speechmgr.h's.
extern void (*gSpeechRaiseSpikeStripTireBlowFn)(uint32_t speaker, int32_t b);
extern void (*gPursuitRoadblockFailedSpeechFn)(tPursuit *p, int32_t b);
extern void (*gSpeechRaiseRequestAnotherRoadblockFn)(uint32_t speaker,
                                                     int32_t b);
extern void (*gSpeechRaiseSpikeStripRequestFn)(uint32_t speaker, int32_t b);
extern void (*gSpeechRaiseRoadblockRequestFn)(uint32_t speaker, int32_t b);
extern void (*gSpeechRaiseDispatchRoadBlockNAFn)(uint32_t speaker);

// collision_sound::PlayBustRoadBlock (0x001e5688), at the chased car's
// position: task 29's sounds. NULL is silent.
extern void (*gCollisionSoundPlayBustRoadBlockFn)(const bVector3 *pos);

// Retail's RealDriver::ForceEBrakeStop(float) (0x0013b558): the e-brake
// held on for `t` seconds while the car is faster than 20 mph. main.c
// binds realdriver_force_ebrake_stop (12i-3); NULL does not brake.
struct RealDriver;
extern void (*gRealDriverForceEBrakeStopFn)(struct RealDriver *d, float t);

// The helicopter (12k): its word at 960, and FollowThisCar (0x001e7f80).
// Nothing sets pChopper before then; NULL aborts.
extern int32_t (*gChopperNew960Fn)(struct Chopper *c);
extern void    (*gChopperFollowThisCarFn)(struct Chopper *c, struct Car *car);

// Registers the tables at 0x002bd460 and 0x002bd470.
void pursuit_install_vtables(void);

#endif
