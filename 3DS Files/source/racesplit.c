// racesplit -- see racesplit.h.

#include "racesplit.h"

#include "racecore.h"
#include "racefinish.h"
#include "realtime.h"

static const int32_t kFinishReasonIds[6] = {   // 0x002f0bc0
    0x49448, 0x49445, 0x49447, 0x49449, 0xecd12, 0xecd12,
};

// What an out-of-range boundary number reads. Callers only test it.
static Timer sNoTime;

static Timer *boundary_timer(Timer *times, int32_t i)
{
    if (i < 0 || i >= RACE_MAX_BOUNDARIES) {
        sNoTime.PackedTime = 0;
        return &sNoTime;
    }
    return &times[i];
}

Timer *racingcar_get_last_start_line_crossing_time(struct RacingCar *rc)
{
    return boundary_timer(rc->BoundaryCrossingTimes,
                          pCurrentRace->StartLineBoundaryNumber);
}

Timer *racingcar_get_last_lap_time(struct RacingCar *rc)
{
    return boundary_timer(rc->RunningTimes,
                          pCurrentRace->FinishLineBoundaryNumber);
}

Timer *racingcar_get_last_best_lap_time(struct RacingCar *rc)
{
    return boundary_timer(rc->BestRunningTimes,
                          pCurrentRace->FinishLineBoundaryNumber);
}

Timer *racingcar_get_last_previous_best_lap_time(struct RacingCar *rc)
{
    return boundary_timer(rc->PreviousBestRunningTimes,
                          pCurrentRace->FinishLineBoundaryNumber);
}

int32_t racingcar_get_finish_reason_id(int32_t reason)
{
    if (reason < 0 || reason >= 6)
        return 0;
    return kFinishReasonIds[reason];
}

static float time_around_track(Race *r, float lap)
{
    if (r->pTimeAroundTrackTable == NULL)
        return 0.0f;
    return tatt_get_time_around_track(r->pTimeAroundTrackTable, lap);
}

// The ticks since a finished car's RaceTime, less the race's start:
// unsigned, as retail's `subu`s are.
static uint32_t done_for(const Race *r, const struct RacingCar *c)
{
    return (uint32_t)WorldTimer - c->RaceTime.PackedTime
           - r->StartTime.PackedTime;
}

void race_calculate_split_time(Race *r, Timer *out, struct RacingCar *a,
                               struct RacingCar *b)
{
    int a_done = a->FinishReason == RACING_CAR_NORMAL_COMPLETION;
    int b_done = b->FinishReason == RACING_CAR_NORMAL_COMPLETION;
    float tb, ta;
    Timer t;

    if (a_done && b_done) {
        out->PackedTime = b->RaceTime.PackedTime - a->RaceTime.PackedTime;
    } else if (a_done) {
        tb = time_around_track(r, b->FinishedLapNumberExact);
        ta = time_around_track(r, (float)a->NumLapsCompleted);
        timer_set_time(&t, tb - ta);
        out->PackedTime = t.PackedTime - done_for(r, a);
    } else if (b_done) {
        tb = time_around_track(r, (float)b->NumLapsCompleted);
        ta = time_around_track(r, a->FinishedLapNumberExact);
        timer_set_time(&t, tb - ta);
        out->PackedTime = t.PackedTime + done_for(r, b);
    } else {
        tb = time_around_track(r, b->FinishedLapNumberExact);
        ta = time_around_track(r, a->FinishedLapNumberExact);
        timer_set_time(out, tb - ta);
    }
}
