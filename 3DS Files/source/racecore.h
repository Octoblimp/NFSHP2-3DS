// racecore -- Race.obj from retail: the Race itself, its lap boundaries,
// RacingCar's constructor, and the table of how long a lap takes.
//
//   TimeAroundTrackTable::TimeAroundTrackTable(int)   0x001467a0  840 bytes
//   TimeAroundTrackTable::GetTimeTableEntry           0x00146ae8  164 bytes
//   TimeAroundTrackTable::GetTimeAroundTrack          0x00146b90   32 bytes
//   RacingCar::UnInit                                 0x00146c88    8 bytes
//   Race::Race                                        0x001475e8  244 bytes
//   Race::~Race                                       0x001476e0  236 bytes
//   Race::AddBoundaryPosition                         0x001479f8  292 bytes
//   Race::FigureOutBoundaries                         0x00147b20  568 bytes
//   Race::GetLapNumberExact                           0x00147d58  104 bytes
//   Race::SetupGhostCars                              0x001485e0   12 bytes
//   Race::GracePeriodIsActive                         0x001492b0  112 bytes
//   RacingCar::RacingCar                              0x001493b8  272 bytes
//   TimeAroundTrackTable::~TimeAroundTrackTable       0x001494c8   28 bytes
//
// Step 8c is the construction: a Race made and destroyed, with its
// boundaries and lap count. Race::Init, which adds the racing cars, sets
// the stage and builds the TimeAroundTrackTable, is step 8d's, with
// RacingCar::Init and the lap counting under it.
//
// docs/formats/race.md has the decode.

#ifndef RACECORE_H
#define RACECORE_H

#include <stdint.h>

#include "bvector.h"
#include "race.h"

// ------------------------------------------------------ TimeAroundTrackTable

// Eight bytes, the stab's type 1607, whose name and fields the stabs do not
// keep: the names here are the port's. One per 1/256 of a lap.
typedef struct TimeTableEntry {
    float Rate;     // 0  laps a second over this part of the lap
    float Time;     // 4  seconds from the line to the part's start
} TimeTableEntry;

#define TATT_ENTRIES 256

// 2052 bytes, type#1609. How long a car of one class takes to get from the
// start line to any point of a lap, measured along the racing routes'
// driving line for that class at the speeds the line was tuned for. Race::
// Init builds one for the first player's car.
typedef struct TimeAroundTrackTable {
    float          TotalTimeAroundTrack;        // 0
    TimeTableEntry EntryTable[TATT_ENTRIES];    // 4
} TimeAroundTrackTable;                         // 2052

// 0x001467a0. For every racing route (TheTrackRouteManager's first list)
// whose driving line 2 * car_class is valid or fake: each pair of its
// points, offset onto that line, gives a rate -- the part of a lap between
// them over the time the line's speed takes -- for the entry the first
// point is in, if that entry has none yet. Then every entry without one
// takes the one before's, 1/180 for the first, and the times add up from
// the line. GetLapNumberExact is pCurrentRace's, not a race of its own.
TimeAroundTrackTable *tatt_construct(TimeAroundTrackTable *t,
                                     int32_t car_class);

// 0x001494c8. Nothing to undo; with flags & 1 the table is freed.
void tatt_destroy(TimeAroundTrackTable *t, int32_t flags);

// 0x00146ae8. The entry `lap`'s fraction is in, a negative lap taken as
// 0. With `time` set, the time from the line to `lap`, whole laps
// included: TotalTimeAroundTrack for each, the entry's Time, and the rest
// of the way into the entry at its Rate.
TimeTableEntry *tatt_get_time_table_entry(TimeAroundTrackTable *t, float lap,
                                          float *time);

// 0x00146b90. That time.
float tatt_get_time_around_track(TimeAroundTrackTable *t, float lap);

// ------------------------------------------------------------- RacingCar

// 0x001493b8. The Timers zeroed -- the five arrays, the lap times and the
// race time -- and nothing else.
struct RacingCar *racingcar_construct(struct RacingCar *rc);

// 0x00146c88, `jr ra`.
void racingcar_uninit(struct RacingCar *rc);

// ------------------------------------------------------------------ Race

// 0x001475e8. The eight RacingCars built, pCurrentRace this one, the
// stage NONE, the lap count TheRaceParameters' (1 on a point-to-point
// race), every counter and pointer zeroed, BestLapTime 0x7fffffff, and the
// boundaries found. pRacingCars and GhostCarDataFilename are not written.
Race *race_construct(Race *r);

// 0x001476e0. Each racing car's UnInit; the replaying ghost car's data
// freed and, only then, its WorldObject destroyed; the capturing ghost
// car's data and the TimeAroundTrackTable freed; pCurrentRace NULL; and
// with flags & 1 the race freed.
void race_destroy(Race *r, int32_t flags);

// 0x00147b20. Up to five boundaries, from the track's position markers
// where it has them: the start line, three splits a third of a lap apart
// and, on a point-to-point race, a finish line. Without a marker a split
// goes 33 and 66 past the start and the finish 95; split 3 has no default
// and is left out. On a backward track the splits come in the other order.
// Without Point2Point the finish line is the start line.
void race_figure_out_boundaries(Race *r);

// 0x001479f8. Adds boundary `name`: at its marker's place around the track
// when there is one, else at `dist` (taken 100 less when over 100) when
// that is not negative, else not at all (-1). Returns its number. `pos`
// gets the marker's position, or zero.
int32_t race_add_boundary_position(Race *r, const char *name, bVector2 *pos,
                                   float dist);

// 0x00147d58. How far round a lap `pct` percent of the way round the track
// is, from the finish line: in [0, 1) for a percentage in range.
float race_get_lap_number_exact(Race *r, float pct);

// 0x001485e0, empty in retail: no ghost car is made.
void race_setup_ghost_cars(Race *r);

// StartOfRaceGracePeriod (gp-22256, 12.0) and
// TimeBetweenCarsForGracePeriodExit (gp-22252, 0.5). Only
// GracePeriodIsActive reads them, and nothing writes them.
extern float StartOfRaceGracePeriod;
extern float TimeBetweenCarsForGracePeriodExit;

// 0x001492b0. Whether the race's start is no more than the grace period
// ago, in WorldTimer's ticks at 0.00025 s. The period is 12 s, but a car
// numbered 101 to 149 has half a second less for each number past 100:
// 11.5 s for 101, none from 124 on. DrivingChoice's GetSpeedBackToLine
// asks it, and so do AIActionAvoidCars, AIActionPass, AIActionGetUnstuck
// and AICarController::SignPostDecision.
int race_grace_period_is_active(const Race *r, const struct Car *car);

// ------------------------------------------------------------ the replay's
//
// TASKS 72d. RaceCoordinator::DoSnapshot takes pCurrentRace's.

struct ReplaySnapshot;

// RacingCar::DoSnapshot, 0x00146c90, section "RacingCar": the two
// boundary regions, the seven lap and place bytes, NumLapsLed and
// FinishReason, the four floats; and in a time trial the first boundary
// crossing, then the crossing and the running time at pCurrentRace's
// finish line, its number unchecked. The car, CrossedNewBoundary and
// the rest of the Timers are not saved.
void racing_car_do_snapshot(struct RacingCar *rc, struct ReplaySnapshot *s);

// Race::DoSnapshot, 0x001477d0, section "Race": RaceStage's first byte,
// the two frame counts, StartTime and RaceTime, NumRacingCars checked,
// the finished count and DetectedOneCarRemaining in a byte; then for each
// racing car its RacingCar and, in a signed byte, which table entry its
// place in pRacingCars points at, which is pointed at again in every
// mode. NumLapsInRace is checked last.
void race_do_snapshot(Race *r, struct ReplaySnapshot *s);

// -------------------------------------------------------------- the seam
//
// The WorldObject destructor (0x001cd828, flags 3) is worldobject.h's
// gWorldObjectDeleteFn. With it NULL, the replaying ghost car's
// WorldObject is not destroyed; nothing in retail makes one.

#endif
