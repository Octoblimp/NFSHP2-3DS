// racesplit -- Race.obj from retail: the split times and the RacingCar
// accessors the HUD times laps with.
//
//   RacingCar::GetFinishReasonId              0x00146788    24 bytes
//   RacingCar::GetLastStartLineCrossingTime   0x00147540    24 bytes
//   RacingCar::GetLastLapTime                 0x00147570    24 bytes
//   RacingCar::GetBestLapTime                 0x00147588    24 bytes
//   RacingCar::GetPreviousBestLapTime         0x001475a0    24 bytes
//   Race::CalculateSplitTime                  0x001487e8   344 bytes
//
// Step 8m-3, with hudrender.c. docs/formats/hud-render.md has the decode.

#ifndef RACESPLIT_H
#define RACESPLIT_H

#include <stdint.h>

#include "race.h"
#include "timer.h"

// The car's BoundaryCrossingTimes at pCurrentRace's
// StartLineBoundaryNumber, a signed byte. Retail reads outside the array
// for a number out of [0, 4]; the port hands back a Timer of 0, which
// every caller takes as unset.
Timer *racingcar_get_last_start_line_crossing_time(struct RacingCar *rc);

// The car's RunningTimes at the race's FinishLineBoundaryNumber, the same
// way.
Timer *racingcar_get_last_lap_time(struct RacingCar *rc);

// BestRunningTimes and PreviousBestRunningTimes at the finish line, the
// same way.
Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc);
Timer *racingcar_get_last_previous_best_lap_time(struct RacingCar *rc);

// A FinishReason's string id, from the six words at 0x002f0bc0 (0x49448
// "finished", 0x49445, 0x49447, 0x49449 and 0xecd12 twice). Retail has no
// bound; the port's is 0 outside them.
int32_t racingcar_get_finish_reason_id(int32_t reason);

// How far b is behind a, in Timer ticks:
//
//   both finished (FinishReason 1): b's RaceTime less a's
//   a finished:   the time around the track from b's FinishedLapNumberExact
//                 back to a's NumLapsCompleted, through Timer::SetTime,
//                 less how long a has been done: WorldTimer - a's RaceTime
//                 - the race's StartTime
//   b finished:   from b's NumLapsCompleted back to a's
//                 FinishedLapNumberExact, plus how long b has been done
//   neither:      from b's FinishedLapNumberExact back to a's
//
// Each pair asks tatt_get_time_around_track about b's lap first. A race
// without a TimeAroundTrackTable takes 0 for each, where retail reads
// through NULL.
void race_calculate_split_time(Race *r, Timer *out, struct RacingCar *a,
                               struct RacingCar *b);

#endif
