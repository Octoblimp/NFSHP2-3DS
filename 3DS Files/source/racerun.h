// racerun -- Race.obj from retail, the race's running half: Race::Init, the
// racing cars it adds and sorts, the stage, and the lap counting under them.
//
//   RacingCar::Init                       0x00146bb0   212 bytes
//   RacingCar::FakeStartlineCrossing      0x00146e08    76 bytes
//   RacingCar::CheckBoundaryCrossing      0x00146e58   372 bytes
//   RacingCar::UpdateLapCounts            0x00146fd0  1064 bytes
//   RacingCar::GetPlayer                  0x001475b8    24 bytes
//   Race::Init                            0x00147960   148 bytes
//   Race::AddRacingCars                   0x00147dc0   196 bytes
//   Race::AddRacingCar                    0x00147e88   100 bytes
//   Race::SetRaceStage                    0x00147ef0   464 bytes
//   Race::SortRacingCarsByLeadership      0x00148218   264 bytes
//
// Step 8d. Race's construction is racecore.c's (8c); RaceCoordinator::
// InitForRace, which makes the Race and calls Init, is 8e's. Timer::Round,
// which the times go through, is timer.c's.
//
// docs/formats/race.md has the decode.

#ifndef RACERUN_H
#define RACERUN_H

#include <stdint.h>

#include "race.h"
#include "timer.h"

struct Car;
struct Player;

// 12 bytes, type#3298: what CheckBoundaryCrossing found.
typedef struct BoundaryCrossingInfo {
    int32_t CrossedForwards;    // 0  bool
    int32_t CrossedBackwards;   // 4  bool
    Timer   TimeSinceCrossing;  // 8  how long ago the car was on it
} BoundaryCrossingInfo;

// mph to m/s, gp-31468 (0x3ee4e0c2): UpdateLapCounts' cap on a top speed
// from the car's SpeedLimiter.
#define RACE_MPH_TO_MPS 0.44702727f

// ------------------------------------------------------------- RacingCar

// 0x00146bb0. Ties the racing car and the car together and starts its
// standing: no position, no finish, every time 0 but the bests
// (0x7fffffff), the lap and both regions -1. PreviousDistanceAroundTrack
// is where the car is, so UpdateLapCounts, run last, sees no crossing.
// CrossedNewBoundary and the two CurrentLapNumberExact fields are not
// written first: UpdateLapCounts reads the old CurrentLapNumberExact and
// dCurrentLapNumberExact as they were.
void racingcar_init(struct RacingCar *rc, struct Car *car);

// 0x00146e08. The race has started: the start line was crossed now, the
// time rounded to a hundredth, and the highest region 0. On a point-to-
// point race the car is in region 0 of lap 0 as well; on a circuit it is
// still behind the line, at -1, until it crosses it.
void racingcar_fake_startline_crossing(struct RacingCar *rc);

// 0x00146e58. Whether the car crossed the boundary at `b` percent between
// PreviousDistanceAroundTrack and `pct`, and which way: forwards from
// behind it to on or past it, backwards the other way, and never when it
// is more than 25 percent from it. On a crossing, TimeSinceCrossing is
// how far past it is over ForwardSpeed, 0 at 1 m/s or less, in ticks.
// Returns 1 on a crossing and zeroes `info` either way.
int32_t racingcar_check_boundary_crossing(struct RacingCar *rc,
                                          BoundaryCrossingInfo *info,
                                          float pct, float b);

// 0x00146fd0. One step of the car's standing. Each boundary crossed moves
// the lap at the finish line and the region, and a region not reached
// before times the boundary. Then the top and average speeds, unless the
// replay is playing, and the exact lap. docs/formats/race.md has the
// rules.
void racingcar_update_lap_counts(struct RacingCar *rc);

// 0x001475b8. The car's Player, or NULL with no car.
struct Player *racingcar_get_player(const struct RacingCar *rc);

// ------------------------------------------------------------------ Race

// 0x00147960. Adds the World's racing cars, sets `stage`, and builds the
// TimeAroundTrackTable for the first car's class -- the second's, under
// BeACop with two player cars.
void race_init(Race *r, eRaceStage stage);

// 0x00147dc0. The World's cars below AICarPos, then those from it up to
// CopCarPos, then the sort, twice.
void race_add_racing_cars(Race *r);

// 0x00147e88. The next RacingCar in the table, initialised for `c`, and
// its pointer in pRacingCars. Nothing checks the count against eight.
void race_add_racing_car(Race *r, struct Car *c);

// 0x00147ef0. The stage, and what each kind of car does on it: a player's
// driver holds at the line until the race starts, and an AI driver is let
// off the brakes when it does. At the start every racing car crosses the
// start line, and at the countdown or the start the traffic is shown and
// put on its rails. The countdown and the start stamp the time.
void race_set_race_stage(Race *r, eRaceStage stage);

// 0x00148218. A bubble sort of pRacingCars, leader first, until a pass
// swaps nothing. A car that has finished sits at its FinishingOrder;
// otherwise the further FinishedLapNumberExact leads. Then each car's
// RacePosition is its place from 1, and PreviousRacePosition the last.
void race_sort_racing_cars_by_leadership(Race *r);

// -------------------------------------------------------------- the seam

// FrontendDatabase::TheRaceIsLeaving (0x00187570), on TheFrontendDatabase
// (0x002fc050), when the stage becomes RACING: the race event's results
// are discarded if the race uses one (UseTheRaceEvent,
// RaceEvent::MaybeDiscardResults). The frontend's race events are task
// 26's. NULL skips it.
extern void (*gRaceIsLeavingFn)(Race *r);

#endif
