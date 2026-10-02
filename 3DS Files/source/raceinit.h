// raceinit -- the cars and the players a race starts with, from retail.
//
//   RaceCoordinator::InitCars      0x0014a2c8  808 bytes
//   RaceCoordinator::InitPlayers   0x00149cb8  188 bytes
//   AddRacingCar                   0x00149f10  272 bytes
//   CalculateRacerPositions        0x0014a020  680 bytes
//
// RaceCoordinator::InitForRace (0x00149988, step 8d) builds the World and
// then calls InitCars and InitPlayers. InitCars puts the racers on the
// grid in starting order, gives the AI racers their first route, then
// adds the traffic, the cops and the helicopter. InitPlayers gives each
// Player its car. Neither reads the RaceCoordinator.
//
// The callees the port does not have yet are seams below. Each is skipped
// when NULL, and the race goes on without what it would have added.
//
// docs/formats/raceinit.md has the decode.

#ifndef RACEINIT_H
#define RACEINIT_H

#include <stdint.h>

#include "bvector.h"
#include "car.h"
#include "race.h"

// RacerStartLocation, 16 bytes (.mdebug type#5600): one grid slot.
// CalculateRacerPositions writes x, y and z, and AddRacingCar builds a car
// there.
typedef struct RacerStartLocation {
    bVector3 Position;   // 0
} RacerStartLocation;    // 16

// InitCars' grid has eight slots.
#define RACEINIT_GRID_SLOTS 8

// nDefaultMovementMode, retail's gp-22960 (0x0032ff40), 4 in .sdata: the
// movement mode an AI racer starts in, MELLOW_MOVEMENT. AddRacingCar reads
// it, and so does retail's AICarController.
extern int32_t nDefaultMovementMode;

// 0x0014a020. x and y of grid slots 0 to n-1: from the track's starting
// markers when every slot has one, else stepped out along the track path.
// Then each z from the ground, through one TopologyCoordinate for all of
// them. Each probe starts from the height of the slot before, 0 for the
// first. The fourth lane is not written.
void calculate_racer_positions(int32_t n, RacerStartLocation *locs);

// 0x00149f10. A Car for `info` at `loc`, facing along the track path and
// that far around it, under control mode `mode`, on the end of World's
// CarList. An AI racer (AI_CONTROL) starts in nDefaultMovementMode and goes
// on the end of AICarList as well; any other car starts in
// PHYSICS_MOVEMENT.
void add_racing_car(DriverInfo *info, RacerStartLocation *loc,
                    ControlMode mode);

// 0x0014a2c8. The racers on the grid in starting order, the car table,
// the AI racers' first route, then the traffic, the cops and the
// helicopter. docs/formats/raceinit.md has the steps.
void racecoordinator_init_cars(RaceCoordinator *rc);

// 0x00149cb8. Each Player's InitForRace on its car. With AIDemoMode set
// that car is World's CarTable[AICarPos + PlayerNumber], unchecked.
// Otherwise it is the car with the player's number, and a player with no
// car is skipped.
void racecoordinator_init_players(RaceCoordinator *rc);

// -------------------------------------------------------------- the seams
//
//   AddCopCarToRace(DriverInfo *, bool)   0x00227d78
//   Chopper::Chopper()                    0x001e7a90, on bMalloc(976)
//   the egg test                          see below
//
// With gAddCopCarToRaceFn NULL no cop is added, though each cop driver
// still counts towards the helicopter and the Be A Cop call. With
// gChopperCtorFn NULL there is no helicopter, and nothing is allocated
// for one.
typedef void (*AddCopCarToRaceFn)(DriverInfo *info, int32_t beACop);
typedef struct Chopper *(*ChopperCtorFn)(void *mem);
extern AddCopCarToRaceFn gAddCopCarToRaceFn;
extern ChopperCtorFn     gChopperCtorFn;

// Chopper's size in retail, which becomes sizeof when it is ported.
#define CHOPPER_SIZE 976

// The word at +48 + 56n of the table at *(0x0031d7f4), the word at +12 of
// a retail object at 0x0031d7e8 that the demo does not have. Only readers
// are found, and they look like Easter eggs: RandomRenderEgg's neighbour
// reads n = 0 and 1, Player n = 4, InitCars and Chopper's constructor
// n = 5, and EventInfo::GetStatus n = 6 and 7. InitCars builds the
// helicopter with no cops when egg 5 is on, and the Chopper's
// constructor sets its own word 960 then. NULL reads 0, every egg off.
typedef int32_t (*EggIsOnFn)(int32_t n);
extern EggIsOnFn gEggIsOnFn;

// The egg InitCars tests.
#define EGG_HELICOPTER 5

#endif
