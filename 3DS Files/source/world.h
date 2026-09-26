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

// WorldLoopCounter, gp-20200, 0x00323d08: the world loop's step count,
// 100000 in .sdata (0x000186a0), 0 after ResetWorldTime, and bumped by
// each AdvanceWorldTime that has a step. The clock object owns it. RealDriver
// reads it to space its e-brake replay events eight frames apart.
#include "realtime.h"

#endif
