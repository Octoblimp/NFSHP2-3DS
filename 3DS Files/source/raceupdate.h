// raceupdate -- Race.obj from retail: the race's step, and how a car
// finishes it.
//
//   RacingCar::ProjectRaceTime (new)          0x001473f8   328 bytes
//   Race::MonitorLeadership                   0x00148320   464 bytes
//   Race::MaybeSaveGhostCarData               0x001484f0   240 bytes
//   Race::FinishCar(int, int, bool, reason)   0x001485f0   504 bytes
//   Race::UpdateGhostCar                      0x00148940   312 bytes
//   Race::Update                              0x00148a78  1264 bytes
//   Race::GetLeadingUnfinishedCar             0x00149160    96 bytes
//   Race::GetFinisher                         0x001491c0    68 bytes
//   Race::GetNextFinishRank                   0x00149208    68 bytes
//   Race::FinishCar(Car *, int, bool, reason) 0x00149250    96 bytes
//
// Step 11g-2b. World::DoTimestep calls Update once a step (worldstep.c's
// gRaceUpdateFn), and SimulateRaceFinish finishes the cars through
// gRaceFinishCarFn; main.c sets both. Player::SetFinishedRacing is
// playerfinish.c's, GetLastFinishLineCrossingTime racesplit.c's, and
// AICarController's pull-over (0x001908d8) aicarcontroller.h's. Retail
// has no name for 0x001473f8, which the demo does not have; the port's is
// for what it does. The DoSnapshots are not ported.
//
// docs/formats/race-update.md has the decode.

#ifndef RACEUPDATE_H
#define RACEUPDATE_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "race.h"
#include "racefinish.h"
#include "timer.h"

struct Car;

// ---------------------------------------------------------- GhostCarData

// 82080 bytes, type#359: one lap of a car, sampled. Retail never makes
// one -- SetupGhostCars is empty -- so the race's two ghost car pointers
// stay NULL and the code below that reads them never runs; it is ported
// as it is. The samples are 80 bytes each, 1024 of them.
#define GHOSTCAR_MAX_SAMPLES 1024
#define GHOSTCAR_SAMPLE_BYTES 80

struct GhostCarData {
    int32_t  VersionNumber;                     //   0
    Timer    RaceTime;                          //   4  SetRaceTime's
    int32_t  NumLaps;                           //   8
    int16_t  CarType;                           //  12
    int16_t  SkinNumber;                        //  14
    int32_t  NumSamples;                        //  16
    int32_t  CurrentSampleNumber;               //  20
    Timer    LastSampleTime;                    //  24
    int32_t  Pad1;                              //  28
    char     WinnerName[128];                   //  32
    uint8_t  Samples[GHOSTCAR_MAX_SAMPLES][GHOSTCAR_SAMPLE_BYTES]; // 160
};                                              // 82080

typedef char ghostcardata_layout_check[
    (offsetof(struct GhostCarData, NumSamples) == 16
     && offsetof(struct GhostCarData, Samples) == 160
     && sizeof(struct GhostCarData) == 82080) ? 1 : -1];

// ------------------------------------------------------------- RacingCar

// 0x001473f8, new in retail: the race time of a car that finishes before
// its last lap, from how far round it is. The fraction of the race done
// is CurrentLapNumberExact over `laps` (at least 0.01), and the time is
// the race's so far over that fraction, from `start`, rounded to a
// hundredth. A car that has not finished a lap also gets a lap time
// projected the same way into its BestRunningTimes at the finish line,
// from its last start line crossing. pCurrentRace gives the boundary
// numbers, not the race the time is from.
void racingcar_project_race_time(struct RacingCar *rc, int32_t laps,
                                 const Timer *start);

// ------------------------------------------------------------------ Race

// 0x00148a78. One step of the race:
//   - the countdown's GO starts the race (SetRaceStage(RACING));
//   - while racing, RaceTime is WorldTimer from the start, to a hundredth;
//   - the ghost cars;
//   - each unfinished car's laps, and the players' best lap;
//   - a forced finish (ForceRaceFinishPosition, for the player
//     ForceRaceFinishPlayerNum), as the cop's win or loss when that player
//     is the player cop;
//   - the sort, and the leadership's replay events;
//   - a lap knockout's knockouts, a time trial's finish, the laps led;
//   - every car that has done the laps finished;
//   - each unfinished car's lap speech.
void race_update(Race *r);

// 0x00148320. For each player whose position changed: when the car is
// over 40 m/s and within 25 m of the car now in its old place, a replay
// event -- GainPosition, 4/position + 1, or LosePosition, 2/its old
// position -- and ClosePass, 2.5, when their speeds are within 7 m/s.
void race_monitor_leadership(Race *r);

// 0x001484f0. Nothing unless `rc` is the car the ghost data is captured
// from. Then the data takes the car's RaceTime, is written to
// GhostCarDataFilename when the car has done the race's laps and there is
// no ghost replaying or this one beat it over the same laps, and is freed.
void race_maybe_save_ghost_car_data(Race *r, struct RacingCar *rc);

// 0x00148940. While racing, the capturing car's body matrix (its
// position in the last row) is added at RaceTime. With a ghost
// replaying and a valid RaceTime, its WorldObject is shown at the sample
// for the time, half a metre lower, or hidden when there is none.
void race_update_ghost_car(Race *r);

// 0x001485f0. Finishes pRacingCars[index]:
//   - the cop's win times it from the start, the cop's loss at the time
//     trial's time and a hundredth;
//   - `position` 0 places it next: a car that has done the race's laps
//     at its last finish line crossing (and a player's ghost data saved),
//     any other with a projected time; a positive `position` places it
//     there, and a negative one leaves its order alone;
//   - then the count, `reason`, the lap it finished on, the race event's
//     results, and a player's finish and AI control;
//   - an AI-controlled car pulls over within 15 s, and `blink` blinks it
//     out.
void race_finish_car(Race *r, int32_t index, int32_t position,
                     int32_t blink, eRaceFinishReason reason);

// 0x00149250. FinishCar for the car's racing car, `position` 0 taken as
// its RacePosition. Nothing for a car not in the race.
void race_finish_car_by_car(Race *r, struct Car *car, int32_t position,
                            int32_t blink, eRaceFinishReason reason);

// 0x00149160. The unfinished car (FinishingOrder 0) with the lowest
// RacePosition below NumRacingCars + 1, the first of equals; NULL for
// none.
struct RacingCar *race_get_leading_unfinished_car(Race *r);

// 0x001491c0. The first racing car whose FinishingOrder is `rank`, or
// NULL.
struct RacingCar *race_get_finisher(Race *r, int32_t rank);

// 0x00149208. The lowest rank from 1 that no car has finished at.
int32_t race_get_next_finish_rank(Race *r);

// --------------------------------------------------------------- the seams

// LapFinishedSpeech (0x00207198): the in-race speech when a car crosses
// the line, with its laps done. Task 26's speech. NULL says nothing.
// SplitTimeSpeech (0x00207268), which Update calls for a car that
// completed a lap without crossing the line, is `jr ra` and left out.
extern void (*gLapFinishedSpeechFn)(struct Car *car, int32_t laps);

// GhostCarData::AddSample (0x001b46a0) and GetSample (0x001b43f0). NULL
// adds nothing and finds no sample; retail never reaches either.
extern void (*gGhostCarDataAddSampleFn)(struct GhostCarData *d,
                                        const bMatrix4 *m, Timer *t);
extern int32_t (*gGhostCarDataGetSampleFn)(struct GhostCarData *d,
                                           bMatrix4 *m, Timer *t);

// bWriteToFile (0x002549c8): the name, the data and its size. NULL writes
// nothing.
extern void (*gBWriteToFileFn)(const char *name, void *data, int32_t size);

#endif
