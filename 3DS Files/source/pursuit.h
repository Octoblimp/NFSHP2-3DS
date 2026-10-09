// pursuit -- tPursuit, one car's chase, with its history and roadblock
// state machine. The struct and its records are copmanager.h's; this is
// copmgr.obj's tPursuit code from retail (SLES_507.31).
//
// The manager makes a pursuit in RequestPursuit, from its slot pool, and
// deletes it (copmgr.c) through the table at 0x002bd460. RequestPursuit
// and the two calls under it are tCopManager's, but are here with what
// they make, so copmgr.c's harnesses need none of this. Update (0x00229288)
// and the state machines under it are 12h-2's; the roadblock and chopper
// calls are 12i's.

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

// GetSpeedMPHOrKPH, 0x0022a220: the chased car's speed in the player's
// units, mph for an AI car.
float tpursuit_get_speed_mph_or_kph(const tPursuit *p);

// ReleaseAllCops, 0x0022a260. Retail walks Cops by index while removing
// them, and RemoveCopFromPursuit moves the second down into the first's
// place, so of two cops only the first is released.
void tpursuit_release_all_cops(tPursuit *p);

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


// ---------------------------------------------------------- the seams

// The cop speech manager's (gp-15624), not ported: NULL says nothing.
//   - StartPursuitSpeech (0x0022afb8), JoinPursuitSpeech (0x0022b288) and
//     CopBackOffSpeech (0x0022b788), tPursuit's own.
//   - raiseCrashTow (0x0020aa90), raiseCrash (0x0020a9b0), raiseFlatTire
//     (0x0020aa00), each with the old and new speakers, and
//     raiseSuperRequest (0x0020b4b0).
extern void (*gPursuitStartSpeechFn)(tPursuit *p);
extern void (*gPursuitJoinSpeechFn)(tPursuit *p);
extern void (*gPursuitBackOffSpeechFn)(tPursuit *p);
extern void (*gSpeechRaiseCrashTowFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseCrashFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseFlatTireFn)(uint32_t was, uint32_t now);
extern void (*gSpeechRaiseSuperRequestFn)(uint32_t speaker);

// The helicopter (12k): its word at 960, and FollowThisCar (0x001e7f80).
// Nothing sets pChopper before then; NULL aborts.
extern int32_t (*gChopperNew960Fn)(struct Chopper *c);
extern void    (*gChopperFollowThisCarFn)(struct Chopper *c, struct Car *car);

// Registers the tables at 0x002bd460 and 0x002bd470.
void pursuit_install_vtables(void);

#endif
