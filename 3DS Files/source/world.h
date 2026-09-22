// world -- the front of World, and the pointer to the current one.
//
// World is 5936 bytes and task 26's: it owns the car lists, the collision
// list, the car and position tables, the pause and time-scale state and the
// random seed. Car reads two of its fields -- the car count and the car
// table, which is what CalculateDraftFactor walks to find a car to draft
// behind -- through `pCurrentWorld` at gp-22624.
//
// So this is the record up to the end of CarTable and no further, straight
// from the stab (`World:Tt4039=s5936`). It is never allocated by the port
// until task 26 finishes it; a harness builds one to hold the table.

#ifndef WORLD_H
#define WORLD_H

#include <stddef.h>
#include <stdint.h>

// A bTList is a bList, and a bList is its sentinel node: eight bytes, two
// links.
typedef struct WorldList {
    void *next;
    void *prev;
} WorldList;

#define WORLD_MAX_CARS 14

typedef struct World {
    WorldList CarList;                     //  0  bTList<Car>
    WorldList AICarList;                   //  8
    WorldList CollisionList;               // 16
    struct Chopper *Helicopter;            // 24
    int32_t   TotalNumCars;                // 28
    int32_t   AICarPos;                    // 32
    int32_t   CopCarPos;                   // 36
    int32_t   TrafficCarPos;               // 40
    struct Car *CarTable[WORLD_MAX_CARS];  // 44
    // 100 CarPositionTable onwards: task 26.
} World;

#define WORLD_SLACK ((size_t)(sizeof(void *) - 4))
#define WORLD_AT(f, n, k) (offsetof(World, f) == (size_t)(n) + (k) * WORLD_SLACK)

typedef char world_layout_check[
    (WORLD_AT(AICarList, 8, 2)
     && WORLD_AT(CollisionList, 16, 4)
     && WORLD_AT(Helicopter, 24, 6)
     && WORLD_AT(TotalNumCars, 28, 7)
     && WORLD_AT(TrafficCarPos, 40, 7)
     && WORLD_AT(CarTable, 44, 7)) ? 1 : -1];

// gp-22624, 0x00323390. NULL until task 26 builds a World.
extern World *pCurrentWorld;

#endif
