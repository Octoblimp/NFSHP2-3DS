// world -- the front of World, the pointer to the current one, and the
// methods of World.obj the port has reached.
//
// World is 5936 bytes and task 26's: it owns the car lists, the collision
// list, the car and position tables, the pause and time-scale state and the
// random seed. Car reads two of its fields -- the car count and the car
// table, which is what CalculateDraftFactor walks to find a car to draft
// behind -- through `pCurrentWorld` at gp-22624, and a Collision joins its
// CollisionList and asks how far the nearest player is.
//
// This is the whole record, straight from the stab (`World:Tt4039=s5936`),
// the collision prediction's OBBs, positions, indices and drive targets
// last. RaceCoordinator::InitForRace allocates one (bMalloc(5936, "World",
// 0, 16)) and constructs it, and CleanupAfterRace destroys it with flags 3;
// neither is ported, so only a harness builds one yet.

#ifndef WORLD_H
#define WORLD_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "drivetarget.h"
#include "obb.h"

struct Car;
struct Chopper;
struct DriverInfo;
struct Race;
struct RaceCoordinator;
struct TrafficTeleporter;

// A bTList is a bList, and a bList is its sentinel node: eight bytes, two
// links.
typedef struct WorldList {
    void *next;
    void *prev;
} WorldList;

#define WORLD_MAX_CARS    14
#define WORLD_MAX_PLAYERS  2

// The collision prediction's boxes per car, and the iterations it records.
#define WORLD_PREDICTION_OBBS       20
#define WORLD_PREDICTION_ITERATIONS 40

typedef struct World {
    WorldList CarList;                          //   0  bTList<Car>
    WorldList AICarList;                        //   8
    WorldList CollisionList;                    //  16  bTList<Collision>
    struct Chopper *Helicopter;                 //  24
    int32_t   TotalNumCars;                     //  28
    int32_t   AICarPos;                         //  32
    int32_t   CopCarPos;                        //  36
    int32_t   TrafficCarPos;                    //  40
    struct Car *CarTable[WORLD_MAX_CARS];       //  44
    uint8_t   _pad100[12];                      // 100  the quadword round-up
    bVector3  CarPositionTable[WORLD_MAX_CARS]; // 112
    // Each player's car's position, stored every DoTimestep, and
    // 9999999 in the first three lanes for a player with no car.
    bVector3  PlayerPositions[WORLD_MAX_PLAYERS];   // 336
    float     PlayerDATs[WORLD_MAX_PLAYERS];        // 368
    uint32_t  WorldRandomSeed;                  // 376
    float     fTimeToRemainPaused;              // 380
    float     PreviousTimeToWaste;              // 384
    float     fTimeScale;                       // 388
    float     fTimeScaleTimer;                  // 392
    void    (*TimeScaleCallback)(int32_t param);    // 396
    int32_t   TimeScaleCallbackParam;           // 400
    struct TrafficTeleporter *Teleporter;       // 404
    uint32_t  CollisionPredictionID;            // 408
    uint32_t  PotentialDriveTargetID;           // 412
    // The AI's collision prediction, kept for the debug views: the boxes
    // it swept this car and the other through, each iteration's positions
    // and box indices, and the drive targets. Nothing in the shipped game
    // records into them -- the four recorders have no callers -- so only
    // the constructor, the destructor and UpdateAIDebugRendering touch
    // them.
    OBB       CollisionPredictionMyOBBs[WORLD_PREDICTION_OBBS];       //  416
    OBB       CollisionPredictionOtherCarOBBs[WORLD_PREDICTION_OBBS]; // 2016
    bVector2  CollisionPredictionMyPositions[WORLD_PREDICTION_ITERATIONS];
                                                                      // 3616
    bVector2  CollisionPredictionOtherCarPositions[WORLD_PREDICTION_ITERATIONS];
                                                                      // 3936
    int8_t    CollisionPredictionMyIndicies[WORLD_PREDICTION_ITERATIONS];
                                                                      // 4256
    int8_t    CollisionPredictionOtherCarIndicies[WORLD_PREDICTION_ITERATIONS];
                                                                      // 4296
    DriveTarget CollisionPredictionMyDriveTarget;                     // 4336
    DriveTarget CollisionPredictionOtherCarDriveTarget;               // 4864
    DriveTarget PotentialDriveTarget;                                 // 5392
    int32_t   CollisionPredictionMaxLoopCounter;                      // 5920
    uint8_t   _pad5924[12];                     // 5924  the quadword round-up
} World;

#define WORLD_SLACK ((size_t)(sizeof(void *) - 4))
#define WORLD_AT(f, n, k) (offsetof(World, f) == (size_t)(n) + (k) * WORLD_SLACK)

typedef char world_layout_check[
    (WORLD_AT(AICarList, 8, 2)
     && WORLD_AT(CollisionList, 16, 4)
     && WORLD_AT(Helicopter, 24, 6)
     && WORLD_AT(TotalNumCars, 28, 7)
     && WORLD_AT(TrafficCarPos, 40, 7)
     && WORLD_AT(CarTable, 44, 7)
     && WORLD_AT(CarPositionTable, 112, 21)
     && WORLD_AT(PlayerPositions, 336, 21)
     && WORLD_AT(PlayerDATs, 368, 21)
     && WORLD_AT(fTimeScaleTimer, 392, 21)
     && WORLD_AT(TimeScaleCallback, 396, 21)
     && WORLD_AT(TimeScaleCallbackParam, 400, 22)
     && WORLD_AT(Teleporter, 404, 23)
     && WORLD_AT(PotentialDriveTargetID, 412, 24)) ? 1 : -1];

// The tail holds OBBs and DriveTargets, whose own pointers move everything
// after them on a 64-bit host, so it is checked where it matters: on the
// 3DS, to the console's offsets and size.
#if UINTPTR_MAX == 0xffffffffu
typedef char world_tail_check[
    (offsetof(World, CollisionPredictionMyOBBs) == 416
     && offsetof(World, CollisionPredictionOtherCarOBBs) == 2016
     && offsetof(World, CollisionPredictionMyPositions) == 3616
     && offsetof(World, CollisionPredictionOtherCarPositions) == 3936
     && offsetof(World, CollisionPredictionMyIndicies) == 4256
     && offsetof(World, CollisionPredictionOtherCarIndicies) == 4296
     && offsetof(World, CollisionPredictionMyDriveTarget) == 4336
     && offsetof(World, CollisionPredictionOtherCarDriveTarget) == 4864
     && offsetof(World, PotentialDriveTarget) == 5392
     && offsetof(World, CollisionPredictionMaxLoopCounter) == 5920
     && sizeof(World) == 5936) ? 1 : -1];
#endif

// gp-22624, 0x00323390. NULL until task 26 builds a World.
extern World *pCurrentWorld;

// 0x0014bbb8. The distance in three dimensions from `p` to the nearer of the
// two PlayerPositions: the VU's difference, its squares summed x, then y,
// then z, and `sqrt.s`; then `min.s`.
float world_get_distance_to_closest_player(const World *w, const bVector3 *p);

// 0x0014bb60, the bVector2 overload: the same on x and y alone, in scalar
// floats.
float world_get_distance_to_closest_player_2d(const World *w,
                                              const bVector2 *p);

// gp-22620, 0x00323394, TweakerPauseWorld: a tweaker switch that holds the
// world still. 0 on the disc.
extern int32_t TweakerPauseWorld;

// ------------------------------------------------------------ the timestep
//
// worldstep.c. Everything here but the distances above: the clock, the
// pause and the time scale, the car table, the checksums, and the step
// itself. It is apart from world.c because world.c links into six checkers
// that have none of the collision system. docs/formats/world.md has the
// decode.

// 0x0014adf0. The scale the step is multiplied by, for `timer` seconds of
// real time, and what to call with `param` when it runs out.
void world_set_time_scale(World *w, float scale, float timer,
                          void (*callback)(int32_t), int32_t param);

// 0x0014ae08. Scale 1, no timer, no pause, no callback.
void world_reset_time_scale(World *w);

// 0x0014ae28. Paused for `seconds` of real time. The pause shares the time
// scale's callback and its parameter.
void world_set_world_paused(World *w, float seconds,
                            void (*callback)(int32_t), int32_t param);

// 0x0014ae38 and 0x0014ae40. Empty.
void world_begin_pause(World *w);
void world_end_pause(World *w);

// 0x0014ae48. Counts the pause down by RealTimeElapsed. When it reaches 0 or
// less, the pause is set to 0 and the callback runs once and is cleared.
void world_update_world_paused(World *w);

// 0x0014aeb0. Paused for some time still, or by the tweaker.
int32_t world_is_world_paused(const World *w);

// 0x0014aee8. The step, in seconds: RealTimeElapsedQuantized converted, or
// the replay's recorded one while it plays back (and recorded while it
// captures), times the time scale, whose timer it counts down. While the
// replay plays back it also burns real time on the ticker until the step
// has taken as long as it did when it was recorded, up to 0.3 s.
// pReplayManager is read with no NULL test.
float world_get_timestep(World *w);

// 0x0014b480. One world step. docs/formats/world.md lists the order.
void world_do_timestep(World *w, float dt);

// 0x0014b050. Once every 128 steps, the far smokeables go. Then every
// dynamic body on CollisionBodyList, taken in list order before any moves,
// is moved through its table's Move (slot 64).
void world_do_timestep_move(World *w, float dt);

// 0x0014b110. The collisions: expired witnesses destroyed, new ones made,
// the contacts found and resolved (earliest first, at most 20 rounds), the
// broken smokeables' pieces tested again, and every Collision on the list
// updated and ended once it has gone quiet.
void world_do_timestep_collisions(World *w, float dt);

// Not in the image. The step's time by part, in EE ticks summed over the
// steps since main.c last logged them, while WorldStepProfOn is set (it is
// with DebugLog 1). The 2026-10-19 device log had a 10 FPS stretch by a
// roadblock with nothing past "world" to say where it went. With the flag
// clear no tick is read, so a harness's scripted ticks are untouched.
enum {
    WSP_COPS,           // the teleporter and the global cop think
    WSP_THINK,          // every car's think
    WSP_DRIVE,          // the players' wheel forces and every car's drive
    WSP_CHOPPER,        // the helicopter's fly
    WSP_BEGIN,          // every car's BeginMovement
    WSP_MOVE,           // the dynamic bodies' moves
    WSP_WITNESSES,      // witnesses expired and made
    WSP_TESTS,          // the first contact tests
    WSP_RESOLVE,        // the contact rounds
    WSP_COLLISIONS,     // the Collisions' updates
    WSP_FINISH,         // every car's FinishMovement
    WSP_EVENTS,         // trigger events and shakes
    WSP_EFFECTS,        // particles, world and terrain effects, engines
    WSP_REST,           // em events to the race update
    WSP_PARTS
};

typedef struct WorldStepProf {
    uint32_t steps;
    uint32_t ticks[WSP_PARTS];
    uint32_t worst;                     // the longest step
    uint32_t think[WORLD_MAX_CARS];     // by CarIndex
    uint32_t drive[WORLD_MAX_CARS];
    uint32_t witnesses;                 // tested in the first pass
    uint32_t rounds;                    // contact rounds
    uint32_t roundsMax;                 // in one step
} WorldStepProf;

extern int32_t       WorldStepProfOn;
extern WorldStepProf WorldStepProfile;

// Not in the image either, and kept whatever the flags. Where the step is,
// for hangwatch's report on a stall (main.c's note): the part (WSP_*, or
// -1 between steps) and the car it is on (its CarIndex, or -1). A
// player's race froze in the step three times on 2026-10-22, and the log
// could say no more than that.
extern volatile int32_t WorldStepPart;
extern volatile int32_t WorldStepCar;

// And a car whose state is not finite. The EE has no NaN or infinity, so
// retail never meets one; the port's IEEE floats can (eefpu.h). At the end
// of each part the cars are looked at, and one with a NaN or an infinity
// in its position, velocity, spin or speed is put back where it last had
// none, at the speed it had there, before the step sorts the car list.
// The last one found is kept here for main.c's log line.
typedef struct WorldStepNaN {
    uint32_t count;                     // cars found, all told
    int32_t  frame;                     // WorldLoopCounter
    int32_t  part;                      // the part it was found after
    int32_t  car;                       // CarIndex
    int32_t  movementMode;
    int32_t  reset;                     // 0: no good place to put it back
    bVector3 position, velocity, spin;  // as found
    bVector3 good;                      // where it went back to
} WorldStepNaN;

extern WorldStepNaN WorldStepNaNs;

// Not in the image. Each step of CarTable[0], player 1's car, while
// WorldFallTraceOn is set ("FallLog 1"): where the move left it and every
// contact of its that was resolved, for main.c's line a step. The user's
// car went through the road on track 62 (2026-10-20), and the log's line
// every 2 s showed only that it had. With the flag clear nothing is read.
#define WORLD_FALL_CONTACTS 6

typedef struct WorldFallContact {
    int32_t round;
    int32_t other;                      // the other body's Type
    float   normalZ;                    // a wafer's face normal's z, else 0
    float   side;                       // the car's centre off that plane
    float   backup;                     // BackupTime
    float   crowbarZ;                   // the car's share of CrowbarVector
    float   zBefore, zAfter;            // the car's position round the resolve
    float   vzBefore, vzAfter;          // and its velocity
} WorldFallContact;

typedef struct WorldFallStep {
    int32_t frame;                      // WorldLoopCounter
    float   dt;
    float   zMoved, vzMoved;            // after the move, before the contacts
    int32_t tested;                     // the car's contacts in the first tests
    int32_t rounds;
    int32_t dropped;                    // the car's, at the twentieth round
    int32_t resolved;                   // the first WORLD_FALL_CONTACTS kept
    WorldFallContact contact[WORLD_FALL_CONTACTS];
} WorldFallStep;

extern int32_t       WorldFallTraceOn;
extern WorldFallStep WorldFallTrace;

// Not in the image either: a replayed frame's miss, for main.c's
// "DemoReplayDrift" log (72h-2c). The checksum, the seed it was folded
// with, and the byte the replay held.
typedef struct WorldVerifyMissed {
    uint32_t checksum;
    uint32_t seed;
    uint32_t expected;
} WorldVerifyMissed;

extern WorldVerifyMissed WorldVerifyMiss;

// 0x0014bce0. Empty.
void world_flush_collisions(World *w);

// 0x0014bc98 and 0x0014bcc0. bRandom on the world's own seed.
int32_t world_random_i(World *w, int32_t range);
float   world_random_f(World *w, float f);

// 0x0014bc18. The signed distance round the track from the nearer player,
// by DAT: TrackPathManager::CompareDistances against each PlayerDAT, and
// the one with the smaller magnitude. Player 1 wins a tie.
float world_get_dat_to_closest_player(const World *w, float dat);

// 0x0014ab08. The car table, from CarList: the players, the AI racers, the
// cops and super cops, then the traffic, each group in list order, and the
// counts and positions between them. Each car's CarIndex is its place.
void world_build_car_table(World *w);

// 0x0014acd8 (retail's 0x0014d508). The car in the table with DriverNumber
// n, or NULL. In world.c.
struct Car *world_get_car_by_number(const World *w, int32_t n);

// 0x0014ada0, GetCarByDriverNumber. The same on pCurrentWorld.
struct Car *world_get_car_by_driver_number(int32_t n);

// The replay's (TASKS 72c), in world.c: a pointer to a car as its
// DriverNumber in one byte, -1 for NULL, found again on a restore.
// Retail's 0x0014d550, and DoCarPointerSnapshot (0x00130910) with the
// arguments the other way round.
struct ReplaySnapshot;
void world_do_pointer_snapshot(const World *w, struct ReplaySnapshot *s,
                               struct Car **pp);
void world_do_car_pointer_snapshot(const World *w, struct Car **pp,
                                   struct ReplaySnapshot *s);

// World::DoSnapshot, retail's 0x0014d148, in worldsnap.c (TASKS 72d-2),
// section "World": the seed, the pause and the time scale (its callback
// as four raw bytes), the players' positions and DATs, and the two IDs.
// A restore then flushes the clans, kills WorldEffects' effects, flushes
// the fern shakers, sets bResetGlare and resets the camera shakers. Then
// the clock's snapshot, the teleporter's and the track graph's (each when
// there is one), every car's, the cops' and the chopper's; on a restore
// every witness eliminated; then the smokeables' and the three
// SnapshotEverythings.
void world_do_snapshot(World *w, struct ReplaySnapshot *s);

// SnapshotCops, 0x00227cd8: the cop manager's snapshot when there is one.
void snapshot_cops(struct ReplaySnapshot *s);

// World's snapshot reaches these, which the port does not have yet; a
// NULL one is skipped. FlushClans (0x001ab650) and FlushFernShakers
// (0x001da1b0) on a restore; tCopManager::DoSnapshot (0x00223b70) and
// Chopper::DoSnapshot (0x001e7d08), which are TASKS 72e.
struct tCopManager;
extern void (*gFlushClansFn)(void);
extern void (*gFlushFernShakersFn)(void);
extern void (*gCopManagerDoSnapshotFn)(struct tCopManager *m,
                                       struct ReplaySnapshot *s);
extern void (*gChopperDoSnapshotFn)(struct Chopper *h,
                                    struct ReplaySnapshot *s);

// 0x0014adc8, CarListCheckFlip: nonzero when a may stay in front of b on
// CarList, which DoTimestep sorts by it -- a's x no greater than b's.
int32_t world_car_list_check_flip(const struct Car *a, const struct Car *b);

// 0x0014bce8. The teleporter places a new traffic car for `info`, and a car
// it places goes on the end of CarList. TrafficTeleporter::PlaceNewCar is
// not ported, and a NULL seam aborts: there is no car without it.
void world_add_traffic_car(World *w, struct DriverInfo *info);

// Retail's 0x0014e240 (the demo's 0x0014b9e0). Each car's checksum folded
// into WorldTimer, times 33 plus the next, and each car's position copied
// into CarPositionTable on the way. Retail then adds the helicopter's x,
// as a word. Then the high half added to the low, and 16 bits kept.
uint16_t world_calculate_debug_checksum(World *w);

// Retail's 0x0014e300 (the demo's 0x0014ba88). The checksum goes through
// the Joylog, and a byte of it (with the seed's low byte) through the
// replay: recorded while it captures, compared while it plays back. A
// mismatch sets the manager's OutOfStepFlag, retail's own, and posts
// RC_SKIP_REPLAY to the race coordinator. pReplayManager is read with no
// NULL test.
void world_verify_debug_checksums(World *w);

// DoTimestepMove's stack array holds 176 bodies (704 bytes), and
// DoTimestepCollisions' holds 8 broken pieces. The image does not check
// either; the port aborts past them.
#define WORLD_MAX_MOVING_BODIES 176
#define WORLD_MAX_BROKEN_PIECES 8

// DoTimestepCollisions' limit on rounds of resolving.
#define WORLD_MAX_CONTACT_ROUNDS 20

// The calls World's step makes into classes the port does not have yet.
// The image makes each of them unconditionally, apart from the
// teleporter's, the helicopter's and the race's, which each sit behind a
// test of their own pointer. Here each call is a pointer, and a NULL one is
// skipped -- all but FinishMovement, which moves a car to where its
// collisions left it, so a step without it is not a step, and a NULL one
// aborts. PlaceNewCar is AddTrafficCar's; a NULL one places no traffic
// car, as raceinit.c's NULL AddCopCarToRace places no cop.
extern void (*gTrafficTeleporterDoTimestepFn)(struct TrafficTeleporter *t,
                                              float dt);    // 0x0020e6f8
extern void (*gGlobalCopThinkFn)(float dt);                 // 0x002139d0
extern void (*gCarDoWheelForcesFn)(struct Car *c);          // 0x00132a10
extern void (*gChopperFlyFn)(struct Chopper *h, float dt);  // 0x001dcfa8
extern void (*gCarFinishMovementFn)(struct Car *c, float dt);   // 0x00130480
extern void (*gCarTriggerEventsFn)(struct Car *c);          // 0x00131a58
extern void (*gCarMaybeCameraShakeFn)(struct Car *c);       // 0x001329e8
extern void (*gCarMaybeRumbleFn)(struct Car *c);            // 0x00132740
extern void (*gServiceParticleGroupsFn)(void);              // 0x001a3990
// AcidEffectSystem::TweakerCheck and DoTimeStep, both on the image's one
// AcidEffectSystem, WorldEffects (0x002e7780).
extern void (*gWorldEffectsTweakerCheckFn)(void);           // 0x00125fe8
extern void (*gWorldEffectsDoTimeStepFn)(float dt);         // 0x00127250
extern void (*gEmProcessAllEventsFn)(void);                 // 0x001b0700
extern void (*gUpdatePlayersGameStateFn)(void);             // 0x0017aa00
extern void (*gServiceFernFlattenersFn)(void);              // 0x001cf428
extern void (*gServiceTweakerDamageFn)(void);               // 0x001ab6e8
extern void (*gServiceTrackRouteEditorFn)(void);            // 0x001bbcd8
extern void (*gRaceUpdateFn)(struct Race *r);               // 0x00146410
extern struct Car *(*gTrafficTeleporterPlaceNewCarFn)(
    struct TrafficTeleporter *t, struct DriverInfo *info);  // 0x0020e7f8
// RaceCoordinator::PostMessage.
extern void (*gRaceCoordinatorPostMessageFn)(struct RaceCoordinator *rc,
                                             int32_t msg,
                                             int32_t param); // 0x00147110

// RCMessage 11, from the .mdebug enum. racecoord.h has them all.
#ifndef RC_SKIP_REPLAY
#define RC_SKIP_REPLAY ((int32_t)11)
#endif

// ------------------------------------------------ the constructor and so on
//
// worldinit.c: the constructor and the destructor, the collision
// prediction's recorders, and the two debug views MainLoop calls.
// docs/formats/world.md has the decode.

// 0x0014a4e8, on memory the caller allocated. The lists empty, the boxes
// without cubes, the drive targets constructed, the clock reset, this
// World current, a seed from bDefaultSeed, the counts 0 and the two IDs 1,
// the time scale reset, the players' positions and DATs 0, no helicopter,
// a new TrafficTeleporter, and then the eleven Init calls. The car table,
// the positions table and the prediction's records are left as they were.
World *world_init(World *w);

// 0x0014a748. The twelve Close calls (CollisionBodyWitness's
// EliminateAllWitnesses fourth), the teleporter destroyed, the clock
// reset, no World current and WorldLoopCounter 100000. Then the members in
// reverse: the drive targets, each box's cube (Other's 19 to 0, then My's),
// every Collision, every bPNode on AICarList and every Car, each unlinked
// and then destroyed with flags 3. bFree last, if flags has bit 0.
void world_destroy(World *w, int32_t flags);

// 0x0014bd30. Each AI racer's controller's DebugDisplay (slot 16), from
// AICarPos up to CopCarPos, with the two read again after each call.
void world_debug_display(World *w);

// 0x0014bdc8. Box k of each car's twenty from mine[k] and other[k], through
// OBB's operator=, which moves a cube across.
void world_collision_prediction_set_obbs(World *w, OBB *mine, OBB *other);

// 0x0014be38 and 0x0014be78. The drive targets copied in, through
// DriveTarget's operator=.
void world_collision_prediction_set_drive_targets(World *w,
                                                  const DriveTarget *mine,
                                                  const DriveTarget *other);
void world_record_potential_drive_target(World *w, const DriveTarget *t);

// 0x0014be80. Iteration i's box indices and positions, and i as the
// highest. No range check.
void world_collision_prediction_record_iteration(World *w, int32_t i,
                                                 int8_t mine_index,
                                                 int8_t other_index,
                                                 const bVector2 *mine,
                                                 const bVector2 *other);

// 0x0014bed0. With TweakerPauseWorld set: every box's cube hidden, and the
// two boxes of the chosen iteration drawn at its positions on the ground,
// if one is chosen and recorded; then one drive target handed to the
// renderer -- the potential one, mine, the other car's, or a car's by its
// driver number, the first of the four switches that is on.
void world_update_ai_debug_rendering(World *w);

// The tweakers UpdateAIDebugRendering reads. None ships switched on.
extern int32_t WhichCollisionPredictionIterationToRender; // gp-22608, -1
extern int32_t WhichCarsRegisteredDriveTargetToRender;    // gp-22604, -1
extern int32_t RenderChosenPotentialDriveTarget;          // gp-22600, 0
extern int32_t RenderMyCarDriveTarget;                    // gp-22596, 0
extern int32_t RenderOtherCarDriveTarget;                 // gp-22592, 0

// The constructor's calls into systems the port does not have, in the
// order it makes them. Each sets up a system's pools and lists, and a NULL
// one is skipped: the World goes on without that system, as the step does
// with its seams.
extern void (*gInitCarEffectsFn)(void);             // 0x0011dbf8
extern void (*gInitClansFn)(void);                  // 0x001a1090
extern void (*gInitSkidsFn)(void);                  // 0x001a0c40
extern void (*gInitParticlesFn)(void);              // 0x001a47a0
extern void (*gInitMunitionsFn)(void);              // 0x001b4660
extern void (*gInitFernFlattenersFn)(void);         // 0x001cf328
extern void (*gInitFernShakersFn)(void);            // 0x001cf9c0
extern void (*gSpawnSmokeablesFn)(void);            // 0x0020bea8
extern void (*gInitTerrainEffectEmittersFn)(void);  // 0x0020e448
extern void (*gInitCopsFn)(void);                   // 0x00213930
extern void (*gInitTrackGraphFn)(void);             // 0x00237c58

// The destructor's, likewise; EliminateAllWitnesses, between
// CleanupTrackGraph and ClearSmokeables, is collisionbody.c's.
extern void (*gCloseTerrainEffectEmittersFn)(void); // 0x0020e488
extern void (*gCleanupCopsFn)(void);                // 0x00213978
extern void (*gCleanupTrackGraphFn)(void);          // 0x00237c88
extern void (*gClearSmokeablesFn)(void);            // 0x0020bfe8
extern void (*gCloseFernShakersFn)(void);           // 0x001cfac8
extern void (*gCloseFernFlattenersFn)(void);        // 0x001cf330
extern void (*gCloseMunitionsFn)(void);             // 0x001b46a8
extern void (*gCloseParticlesFn)(void);             // 0x001a4838
extern void (*gCloseClansFn)(void);                 // 0x001a1118
extern void (*gCloseSkidsFn)(void);                 // 0x001a0cf8
extern void (*gCloseCarEffectsFn)(void);            // 0x0011dcb8

// `new TrafficTeleporter`: the constructor (0x0020e610) on the
// TRAFFICTELEPORTER_SIZE bytes World has just bMalloc'd, returning it; and
// its destructor (0x0020e678) with flags 3. A World has a teleporter from
// its constructor on, and AddTrafficCar needs it, so a NULL constructor
// aborts. A teleporter can only have come from the constructor seam, so
// one to destroy with no destructor seam aborts too.
extern struct TrafficTeleporter *(*gTrafficTeleporterCtorFn)(void *mem);
extern void (*gTrafficTeleporterDestroyFn)(struct TrafficTeleporter *t,
                                           int32_t flags);

// TrafficTeleporter's mdebug size, which becomes sizeof when it is ported.
#define TRAFFICTELEPORTER_SIZE 88

// Car's destructor (0x0012f660), which the destructor calls with flags 3
// on every car left on CarList. A car to destroy with no seam aborts.
extern void (*gCarDestroyFn)(struct Car *c, int32_t flags);

// WorldLoopCounter, gp-20200, 0x00323d08: the world loop's step count,
// 100000 in .sdata (0x000186a0), 0 after ResetWorldTime, and bumped by
// each AdvanceWorldTime that has a step. The clock object owns it. RealDriver
// reads it to space its e-brake replay events eight frames apart.
#include "realtime.h"

#endif
