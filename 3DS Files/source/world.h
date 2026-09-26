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
// So this is the record up to PotentialDriveTargetID and no further, straight
// from the stab (`World:Tt4039=s5936`). The collision prediction's OBBs,
// positions, indices and drive targets are the rest. It is never allocated
// by the port until task 26 finishes it; a harness builds one.

#ifndef WORLD_H
#define WORLD_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

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
    // 416 CollisionPredictionMyOBBs onwards: task 26.
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

// 0x0014acd8. The car in the table with DriverNumber n, or NULL.
struct Car *world_get_car_by_number(const World *w, int32_t n);

// 0x0014ada0, GetCarByDriverNumber. The same on pCurrentWorld.
struct Car *world_get_car_by_driver_number(int32_t n);

// 0x0014adc8, CarListCheckFlip: nonzero when a may stay in front of b on
// CarList, which DoTimestep sorts by it -- a's x no greater than b's.
int32_t world_car_list_check_flip(const struct Car *a, const struct Car *b);

// 0x0014bce8. The teleporter places a new traffic car for `info`, and a car
// it places goes on the end of CarList. TrafficTeleporter::PlaceNewCar is
// not ported, and a NULL seam aborts: there is no car without it.
void world_add_traffic_car(World *w, struct DriverInfo *info);

// 0x0014b9e0. Each car's checksum folded into WorldTimer, times 33 plus
// the next, and each car's position copied into CarPositionTable on the
// way. Then the high half added to the low, and 16 bits kept.
uint16_t world_calculate_debug_checksum(World *w);

// 0x0014ba88. The checksum goes through the Joylog, and a byte of it
// (with the seed's low byte) through the replay: recorded while it
// captures, compared while it plays back. A mismatch posts RC_SKIP_REPLAY
// to the race coordinator. pReplayManager is read with no NULL test.
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
// aborts. PlaceNewCar is AddTrafficCar's, and aborts the same way.
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
extern void (*gRainTimeStepFn)(float dt);                   // 0x00128c08
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

// RCMessage 11, from the .mdebug enum.
#define RC_SKIP_REPLAY 11

// WorldLoopCounter, gp-20200, 0x00323d08: the world loop's step count,
// 100000 in .sdata (0x000186a0), 0 after ResetWorldTime, and bumped by
// each AdvanceWorldTime that has a step. The clock object owns it. RealDriver
// reads it to space its e-brake replay events eight frames apart.
#include "realtime.h"

#endif
