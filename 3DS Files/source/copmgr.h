// copmgr -- tCopManager's building and running: retail's copmgr.obj.
//
// copmanager.h has the records and the small queries; this has the cop
// chunks' loader, the manager's constructor and destructor, InitCops and
// CleanupCops, the roadblock and speed-trap tables built from the chunks,
// the speakers' queue and the landmark search. docs/formats/cop-manager.md
// has the layout and the order things happen in.

#ifndef COPMGR_H
#define COPMGR_H

#include <stdint.h>

#include "bslotpool.h"
#include "copmanager.h"

// tCopManager's slot pools, gp-15644, gp-15640 and gp-15636: made by the
// constructor and deleted by the destructor, which sets each to NULL.
extern BSlotPool *PursuitSlotPool;
extern BSlotPool *CopSlotPool;
extern BSlotPool *SpikeStripSlotPool;

// Their slots, retail's sizeof(tPursuit), sizeof(tAICop) and
// sizeof(tSpikeStrip).
#define TPURSUIT_SLOT_SIZE     1600
#define TAICOP_SLOT_SIZE       96   // cop.h checks it on the console
#define TSPIKESTRIP_SLOT_SIZE  2304

// LoaderCops, 0x00227dc0, and UnloaderCops, 0x00227e78: the container
// 0x80034500. Each child sets, or clears, its static -- 0x34510 the
// speed traps, 0x34520 the roadblocks, 0x34530 the landmarks -- and other
// ids are passed over. 1 for the container, 0 for anything else.
int copmgr_loader(uint8_t *chunk);
int copmgr_unloader(uint8_t *chunk);

// tCopManager::tCopManager, 0x002235f8: `m` is fresh bMalloc memory.
// Nothing is cleared that retail does not clear.
tCopManager *copmanager_construct(tCopManager *m);

// tCopManager::~tCopManager, 0x002239e8. Bit 0 of `flags` frees `m`.
// Slot 8 of the manager's table.
void copmanager_destruct(tCopManager *m, int32_t flags);

#define TCOPMANAGER_VT_DTOR  8

// InitCops, 0x00227c58: a manager when RP.nMaxCops > 0. CleanupCops,
// 0x00227ca0: its destructor through its table, flags 3.
void copmgr_init_cops(void);
void copmgr_cleanup_cops(void);

// InitRoadBlockStructures (0x00225ec8) and InitSpeedTrapStructures
// (0x002269a8): the spots from the chunks that are on a route, have
// topology, and (roadblocks) suit the direction and are 9 m wide.
void copmanager_init_road_block_structures(tCopManager *m);
void copmanager_init_speed_trap_structures(tCopManager *m);

// 0x00226448 and 0x00226bb0: the spot made from the chunk's i-th record,
// or NULL when it was left out. `i` is not range checked.
tRoadBlock *copmanager_get_road_block_from_loaded_data_index(tCopManager *m,
                                                             int32_t i);
tSpeedTrap *copmanager_get_speed_trap_from_loaded_data_index(tCopManager *m,
                                                             int32_t i);

// GetBaseSpeedTrapSpawnTime, 0x00224958: seconds until the next radar
// trap, 15, 30 or 45 by the race's length plus up to as much again at
// random; 1 in the AI demo, SkipFETimeUntilCopsAppear with SkipFE.
float copmanager_get_base_speed_trap_spawn_time(tCopManager *m);

// The speakers' queue: GetCurrentCopSpeaker (0x002254e8, 0 when empty),
// NextCopSpeaker (0x00225550, the head to the back), ReserveCopSpeaker
// (0x002255b8, takes the head) and ReleaseCopSpeaker (0x00225610, puts one
// back at the tail unless full). Reserving from an empty queue returns
// whatever retail's a2 held; the port returns 0.
uint32_t copmanager_get_current_cop_speaker(tCopManager *m);
void     copmanager_next_cop_speaker(tCopManager *m);
uint32_t copmanager_reserve_cop_speaker(tCopManager *m);
void     copmanager_release_cop_speaker(tCopManager *m, uint32_t v);

// FindLandmark, 0x00228a58: the first landmark whose area holds `pos`,
// or NULL. LandmarkData must be there.
Landmark *copmgr_find_landmark(const bVector2 *pos);

// Retail's 0x002244a0: the first free PursuitsById slot, or -1.
int32_t copmanager_find_free_pursuit_id(const tCopManager *m);

// Retail's 0x00224560: unlinks `p`, frees its id, and runs its
// destructor through its table with flags 3. NULL does nothing.
void copmanager_delete_pursuit(tCopManager *m, tPursuit *p);

// DeleteRoadBlockSpikeStrips, 0x00227be8: each spike strip of the
// roadblock with loaded-data index `i` blinks away (BlinkBlinkPoof,
// 0x00241880, 12j; NULL aborts).
void copmanager_delete_road_block_spike_strips(tCopManager *m, int32_t i);
extern void (*gSpikeStripBlinkBlinkPoofFn)(tSpikeStrip *s);

// GetCopByCar, 0x00224f70: the first of the nNumCops cops driving `c`,
// or NULL. Each of them is read without a test.
tCop *copmanager_get_cop_by_car(tCopManager *m, struct Car *c);

// MonitorImpact, 0x00228310: a hit of `amount` on `c`. In Be A Cop, a hit
// of 5 or more on the car the player's cop is chasing, within 50 m (or in
// split screen), adds to its fCarDamage, which a hit of the difficulty's
// fDisablingImpactMagnitudeTable or more fills. Otherwise a hit as hard
// as that on an AI cop's car -- half as hard again in a two-car collision
// -- disables the car once its New32 has run out. Retail reads the
// player's cop from Cops[nPlayerCopIndex] with no test of the index; the
// port finds none for -1.
void copmanager_monitor_impact(tCopManager *m, struct Car *c, float amount,
                               int32_t twoCar);

// CarCollisionBody::AddDamage's last part (0x001d84c4), the seam
// gCopManagerMonitorImpactFn: below 1 nothing, else MonitorImpact, told
// whether any of the body's collisions is two cars'. The caller has
// tested the manager.
struct CarCollisionBody;
void copmgr_car_impact(tCopManager *m, struct CarCollisionBody *b,
                       float amount);

// fDisablingImpactMagnitudeTable, 0x0031c560: by nDifficultyLevel, the
// hit that disables an AI cop's car or wrecks Be A Cop's suspect.
extern float fDisablingImpactMagnitudeTable[3];

// tAICop::DisableMyCar(bool), 0x00230ac8: cop.c's taicop_disable_my_car,
// which main.c binds. Reached by MonitorImpact only with an AI cop; NULL
// aborts.
extern void (*gAICopDisableMyCarFn)(tCop *cop, int32_t b);

// ResetAllDamage, 0x00228750: `car` made whole -- its blown tires fixed,
// its fCarDamage 0, fTractionBoostOverride 1, its CarDamage repaired, and
// a player's RealDriver let off its e-brake stop. The repair is
// CarDamage's 0x001b5c20 (BodyDamage::RepairAllDamage, then
// RethinkDamage), not ported: gCarDamageRepairAllFn, which aborts NULL
// where retail would call it. No port car has a CarDamage yet.
void copmanager_reset_all_damage(tCopManager *m, struct Car *car);
extern void (*gCarDamageRepairAllFn)(void *damage);

// CreateCop, 0x002272e8. Be A Cop (`beACop` nonzero): a tPlayerCop on
// the world's first car, after the AI cops, and that car to the first
// radar trap flagged for the race's direction, if one is. Otherwise a
// tAICop out of CopSlotPool for `info`. Either way nNumCops goes up.
struct DriverInfo;
void copmanager_create_cop(tCopManager *m, struct DriverInfo *info,
                           int32_t beACop);

// Retail's 0x002276a0: fMaxCopCarXdim and fMaxCopCarYdim, the first
// cop's car's width and length by 1.1.
void copmanager_calculate_max_cop_car_dimensions(tCopManager *m);

// AddCopCarToRace, 0x00227d78, the seam gAddCopCarToRaceFn: with
// nMaxCops above 0, CreateCop and then 0x002276a0.
void copmgr_add_cop_car_to_race(struct DriverInfo *info, int32_t beACop);

// The cop speech manager (gp-15624), not ported: AllocateVoices
// (0x0020a288) and FlushQueue (0x0020a230). NULL seams do nothing.
extern void (*gCopSpeechAllocateVoicesFn)(void);
extern void (*gCopSpeechFlushQueueFn)(void);

// ------------------------------------------------------------ Think

// GlobalCopThink, 0x00227cf8, the seam gGlobalCopThinkFn (World's step):
// the manager's Think if there is one. Then, while the track graph has a
// cloaked edge, the first of the world's cars before CopCarPos (the
// players and the racers) inside a landmark with IsUncloakTrigger
// uncloaks every edge. TheTrackGraph and LandmarkData must be there.
void copmgr_global_cop_think(float dt);

// tCopManager::Think, 0x002246d0, in order: TimeBasedSpeech,
// SupervisorActivate, PursuitManagement; in Be A Cop ReclaimPatrollers,
// else SpawnSpeedTraps and, once the race clock has started, the eight
// fPursuableTimers down by the frame's seconds to 0; MonitorSpikeBelts,
// MonitorPullovers, each cop's Think through its table, and in Be A Cop
// BeACopThink. RenderDebugInfo (0x00227c48) and 0x00224498 are empty.
void copmanager_think(tCopManager *m);

// TimeBasedSpeech, 0x00225660. Outside the replays and the post-race,
// with the speech manager quiet and a pursuit on, TimeSinceLastSpeech
// counts up; past MaxSpeechGapTime, the player's pursuit, when the
// supervisor and the pursuit have nothing to say and it is still a
// chase, says its filler and the gap is drawn again. Each other way the
// count goes back to 0.
void copmanager_time_based_speech(tCopManager *m);

// SetNextSpeechFillerGap, 0x00225780: 9 s plus bRandom(3) on bDefaultSeed,
// 4 more in Be A Cop.
void copmanager_set_next_speech_filler_gap(tCopManager *m);

// The test TimeBasedSpeech, SupervisorActivate and PossibleCallSupervisor
// open with: an instant or automatic replay, the post-race, or (out of
// line, 0x001369a8) the replay demo.
int32_t copmanager_replaying(void);

// SupervisorActivate, 0x00225308. Outside the replays and the post-race,
// fSupervisorTimer counts down from above 0; the frame it reaches 0, the
// first pursuit of a player's car that the supervisor can open, does.
void copmanager_supervisor_activate(tCopManager *m);

// PursuitManagement, 0x00225bd0: each pursuit's Update, and those that
// say they are over deleted (0x00224560).
void copmanager_pursuit_management(tCopManager *m);

// FindPlayerPursuit, 0x002257e0: in Be A Cop the player's cop's pursuit
// (NULL for no cop), else the first pursuit of a player's car.
tPursuit *copmanager_find_player_pursuit(tCopManager *m);

// MonitorPullovers, 0x00226e70: each active pullover not in its NIS
// counts fHoldTimer down, and ends (EndPullover) once it is below 0.
void copmanager_monitor_pullovers(tCopManager *m);

// ReclaimPatrollers, 0x00224e00, Be A Cop's: an AI cop out on patrol 250
// or more from both players (World::GetDistanceToClosestPlayer, the
// two-dimensional form) is sent to LS_LIMBO.
void copmanager_reclaim_patrollers(tCopManager *m);

// What Think reaches that later slices port. NULL seams do nothing, and
// return 0.
//   - tPursuit::Update (0x00229288): nonzero when the pursuit is over.
//     main.c binds tpursuit_update (pursuit.h).
//   - 0x0022aaf0, the supervisor's test: the chased car can be told
//     (GetExactDescription is not -1) and the pursuit is at LEVEL2 or 3.
//   - SuperInitiates (0x0022b908) and SayFillerSpeech (0x00231760), the
//     speech manager's.
//   - The speech manager's previousSedPlaybackState, its word at 1452.
//   - SpawnSpeedTraps (0x00224a20) and MonitorSpikeBelts (0x00227758),
//     12j; EndPullover (0x00225878), 12l; BeACopThink (0x00227f30), 12m.
extern int32_t (*gPursuitUpdateFn)(tPursuit *p);
extern int32_t (*gPursuitCanSupervisorInitiateFn)(tPursuit *p);
extern void    (*gPursuitSuperInitiatesFn)(tPursuit *p);
extern void    (*gSayFillerSpeechFn)(tPursuit *p, uint32_t *cookie);
extern int32_t (*gCopSpeechPlaybackStateFn)(void);
extern void    (*gCopManagerSpawnSpeedTrapsFn)(tCopManager *m);
extern void    (*gCopManagerMonitorSpikeBeltsFn)(tCopManager *m);
extern void    (*gCopManagerEndPulloverFn)(tCopManager *m, int32_t i);
extern void    (*gCopManagerBeACopThinkFn)(tCopManager *m);

// Registers tCopManager's table, 0x002bd280.
void copmgr_install_vtables(void);

#endif
