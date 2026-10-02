// racefinish -- Race.obj from retail: what the race coordinator's states
// ask the Race about the countdown and the finish.
//
//   Race::GetCountdownNumberToDisplay     0x001480c0   200 bytes
//   Race::GetCountdownProgress            0x00148188   140 bytes
//   Race::SimulateRaceFinish              0x00148f68   144 bytes
//   Race::NotifyTheRaceIsOver             0x00148ff8   128 bytes
//   Race::AreAllPlayersFinishedRacing     0x001490b0    72 bytes
//   Race::GetMostRecentlyFinishedPlayer   0x001490f8    92 bytes
//
// Step 8f, with rcstates.c. Race::FinishCar (0x001485f0) and RaceEvent's
// RecordResults (0x00201598) are seams. docs/formats/race-coordinator.md
// has the decode.

#ifndef RACEFINISH_H
#define RACEFINISH_H

#include <stdint.h>

#include "race.h"

struct Player;
struct RacingCar;

// eRaceFinishReason, from the .mdebug enum (t1007).
typedef int32_t eRaceFinishReason;
#define RACING_CAR_NOT_FINISHED        ((eRaceFinishReason)0)
#define RACING_CAR_NORMAL_COMPLETION   ((eRaceFinishReason)1)
#define RACING_CAR_ARRESTED            ((eRaceFinishReason)2)
#define RACING_CAR_KNOCKED_OUT         ((eRaceFinishReason)3)
#define RACING_CAR_BE_THE_COP_WON      ((eRaceFinishReason)4)
#define RACING_CAR_BE_THE_COP_LOST     ((eRaceFinishReason)5)

// The number the countdown shows, from WorldTimeFrames:
//   - 4 (the GO) for the first 60 frames after StartGoTimeFrames, then 0
//   - 3, 2 and 1 for each count's length after StartCountdownTimeFrames,
//     then 4
//   - 0 with neither set
// A count is 0.9 s, or 1.0 s when the player is the cop.
int32_t race_get_countdown_number_to_display(const Race *r);

// The countdown's progress, where 1.0 is four counts: three and the GO.
// After StartGoTimeFrames it starts at three counts. Before either is set
// it is 0.
float race_get_countdown_progress(const Race *r);

// FinishCar(i, 0, false, RACING_CAR_NORMAL_COMPLETION) on each racing car
// whose FinishReason is still RACING_CAR_NOT_FINISHED, then
// SortRacingCarsByLeadership. NumRacingCars is re-read only after a car
// is finished.
void race_simulate_race_finish(Race *r);

// RaceEvent::RecordResults for each racing car, in pRacingCars order, with
// its RacePosition. NumRacingCars is re-read every pass.
void race_notify_the_race_is_over(Race *r);

// Whether every player has a TimeFinishedRacing. With no players, yes.
int32_t race_are_all_players_finished_racing(const Race *r);

// The player with the latest TimeFinishedRacing, compared signed, or NULL
// when no player has finished. A tie keeps the earlier player.
struct Player *race_get_most_recently_finished_player(const Race *r);

// ---------------------------------------------------------------- seams

// Race::FinishCar (0x001485f0, 504 bytes, with `0x001473f8` under it), as
// SimulateRaceFinish calls it: the car's index, 0, false and the reason.
// NULL finishes nothing.
extern void (*gRaceFinishCarFn)(Race *r, int32_t index, int32_t a,
                                int32_t b, eRaceFinishReason reason);

// RaceEvent::RecordResults (0x00201598) on TheRaceEvent (0x0031b600):
// the race, the racing car and its position. NULL records nothing.
extern void (*gRaceEventRecordResultsFn)(Race *r, struct RacingCar *rc,
                                         int32_t position);

#endif
