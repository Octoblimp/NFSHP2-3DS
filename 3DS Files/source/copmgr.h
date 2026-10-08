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
#define TAICOP_SLOT_SIZE       96
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

// tAICop::DisableMyCar(bool), 0x00230ac8, not ported. Reached by
// MonitorImpact only with an AI cop; NULL aborts.
extern void (*gAICopDisableMyCarFn)(tCop *cop, int32_t b);

// The cop speech manager (gp-15624), not ported: AllocateVoices
// (0x0020a288) and FlushQueue (0x0020a230). NULL seams do nothing.
extern void (*gCopSpeechAllocateVoicesFn)(void);
extern void (*gCopSpeechFlushQueueFn)(void);

// Registers tCopManager's table, 0x002bd280.
void copmgr_install_vtables(void);

#endif
