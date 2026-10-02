// racerun -- see racerun.h.

#include "racerun.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>

#include "bmem.h"
#include "car.h"
#include "cardriver.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "eefpu.h"
#include "racecore.h"
#include "realdriver.h"
#include "realtime.h"
#include "replay.h"
#include "timer.h"
#include "trackpath.h"
#include "vtable.h"
#include "world.h"

void (*gRaceIsLeavingFn)(Race *r);

// A Timer never set, or a best never beaten.
#define TIMER_UNSET 0x7fffffffu

// The last lap LapTimes holds; the array is 11 long.
#define RACE_MAX_LAP_TIMES 11

// `max.s` and `min.s` as mipsemu runs them: the first operand unless the
// second is the larger (smaller).
static float max_s(float fs, float ft)
{
    return (fs < ft) ? ft : fs;
}

static float min_s(float fs, float ft)
{
    return (ft < fs) ? ft : fs;
}

// The replay manager's ReplayingFlag. The image reads it through gp-22440
// without a test; the port has no ReplayManager yet and pReplayManager is
// NULL until it does, which is taken as not replaying, as carreset.c does.
static int replaying(void)
{
    return pReplayManager != NULL && pReplayManager->ReplayingFlag != 0;
}

// A start-line time to measure from: set, and not the 0x7fffffff that
// stands for none.
static int timer_is_set(const Timer *t)
{
    return t->PackedTime != 0 && t->PackedTime != TIMER_UNSET;
}

// ------------------------------------------------------------- RacingCar

void racingcar_init(struct RacingCar *rc, Car *car)
{
    int i;

    car->pRacingCar = rc;
    rc->RacePosition = 0;
    rc->PreviousRacePosition = 0;
    rc->FinishingOrder = 0;
    rc->FinishedLapNumberExact = 0.0f;
    rc->pCar = car;
    rc->FinishReason = 0;
    rc->PreviousDistanceAroundTrack =
        car->TheTrackPathCoordinate.RatioAroundTrack * 100.0f;
    for (i = 0; i < RACE_MAX_BOUNDARIES; i++) {
        rc->BoundaryCrossingTimes[i].PackedTime = 0;
        rc->RunningTimes[i].PackedTime = 0;
        rc->PreviousRunningTimes[i].PackedTime = 0;
        rc->BestRunningTimes[i].PackedTime = TIMER_UNSET;
        rc->PreviousBestRunningTimes[i].PackedTime = TIMER_UNSET;
    }
    for (i = 0; i < RACE_MAX_LAP_TIMES; i++)
        rc->LapTimes[i].PackedTime = 0;
    rc->RaceTime.PackedTime = 0;
    rc->TopSpeed = 0.0f;
    rc->AverageSpeed = 0.0f;
    rc->NumLapsCompleted = 0;
    rc->CurrentLapNumber = -1;
    rc->HighestBoundaryRegion = -1;
    rc->CurrentBoundaryRegion = -1;
    racingcar_update_lap_counts(rc);
    rc->NumLapsLed = 0;
}

// The time is stored before it is rounded, and the rounding is to a
// hundredth (gp-31480).
void racingcar_fake_startline_crossing(struct RacingCar *rc)
{
    rc->BoundaryCrossingTimes[0].PackedTime = (uint32_t)WorldTimer;
    timer_round(&rc->BoundaryCrossingTimes[0], 0.01f);
    rc->HighestBoundaryRegion = 0;
    if (RaceParametersPoint2Point != 0) {
        rc->CurrentBoundaryRegion = 0;
        rc->CurrentLapNumber = 0;
    }
}

// d1 is where the car is from the boundary now, d0 where it was, both as
// ComparePercentDistances gives them: signed, the short way round. The
// distance past it is (d1 * TrackLength) * 0.01 (gp-31476), and the
// speed ForwardSpeed. The listing also takes |d1 - d0| and throws it away.
int32_t racingcar_check_boundary_crossing(struct RacingCar *rc,
                                          BoundaryCrossingInfo *info,
                                          float pct, float b)
{
    float d1 = trackpath_compare_percent_distances(&TheTrackPathManager,
                                                   pct, b);
    float d0 = trackpath_compare_percent_distances(
        &TheTrackPathManager, rc->PreviousDistanceAroundTrack, b);
    float past, speed, ago;

    info->CrossedForwards = 0;
    info->CrossedBackwards = 0;
    info->TimeSinceCrossing.PackedTime = 0;
    past = d1 * TheTrackPathManager.TrackLength * 0.01f;
    if (25.0f < fabsf(d1))
        return 0;
    if (d0 < 0.0f && 0.0f <= d1) {
        info->CrossedBackwards = 0;
        info->CrossedForwards = 1;
    } else if (0.0f <= d0 && d1 < 0.0f) {
        info->CrossedForwards = 0;
        info->CrossedBackwards = 1;
    } else {
        return 0;
    }
    speed = rc->pCar->State.ForwardSpeed;
    ago = 0.0f;
    if (1.0f < speed)
        ago = past / speed;
    info->TimeSinceCrossing.PackedTime =
        (uint32_t)ee_trunc_w(ago * 4000.0f + 0.5f);
    return 1;
}

// A forward crossing of a region the car has not reached before is timed:
// t is now less how long ago it was on the line, to a hundredth
// (gp-31472). Measured from the start line's time, it becomes the running
// time to this boundary, the best kept, and at the finish line the lap's
// time. While the replay plays, only a time trial's finish line is timed,
// without the previous and best times.
//
// pCurrentRace is read afresh at each place the listing reads it: the
// boundary, the finish line's number, the count.
void racingcar_update_lap_counts(struct RacingCar *rc)
{
    BoundaryCrossingInfo info;
    Timer t;
    Car *car;
    float pct, old;
    int16_t region;
    int i;

    rc->CrossedFinishLine = 0;
    rc->CompletedNewLap = 0;
    pct = rc->pCar->TheTrackPathCoordinate.RatioAroundTrack * 100.0f;

    for (i = 0; i < pCurrentRace->NumBoundaries; i++) {
        info.TimeSinceCrossing.PackedTime = 0;
        if (!racingcar_check_boundary_crossing(
                rc, &info, pct, pCurrentRace->BoundaryDistances[i]))
            continue;

        if (!info.CrossedForwards) {
            if (i == pCurrentRace->FinishLineBoundaryNumber)
                rc->CurrentLapNumber = (int8_t)(rc->CurrentLapNumber - 1);
            continue;
        }

        if (i == pCurrentRace->FinishLineBoundaryNumber) {
            int8_t lap = (int8_t)(rc->CurrentLapNumber + 1);

            rc->CurrentLapNumber = lap;
            if (rc->NumLapsCompleted < lap) {
                rc->NumLapsCompleted = lap;
                rc->CrossedFinishLine = 1;
            }
        }
        region = (int16_t)(rc->CurrentLapNumber * 5 + i);
        rc->CurrentBoundaryRegion = region;
        if (!(rc->HighestBoundaryRegion < region))
            continue;

        rc->CompletedNewLap = 1;
        rc->HighestBoundaryRegion = region;
        t.PackedTime = (uint32_t)WorldTimer - info.TimeSinceCrossing.PackedTime;
        timer_round(&t, 0.01f);

        if (!replaying()) {
            if (timer_is_set(&rc->BoundaryCrossingTimes[0])) {
                rc->PreviousRunningTimes[i] = rc->RunningTimes[i];
                rc->RunningTimes[i].PackedTime =
                    t.PackedTime - rc->BoundaryCrossingTimes[0].PackedTime;
                rc->PreviousBestRunningTimes[i] = rc->BestRunningTimes[i];
                if ((int32_t)rc->RunningTimes[i].PackedTime
                    < (int32_t)rc->BestRunningTimes[i].PackedTime)
                    rc->BestRunningTimes[i] = rc->RunningTimes[i];
                if (i == pCurrentRace->FinishLineBoundaryNumber
                    && (uint8_t)rc->CurrentLapNumber < RACE_MAX_LAP_TIMES)
                    rc->LapTimes[rc->CurrentLapNumber] = rc->RunningTimes[i];
            }
            rc->BoundaryCrossingTimes[i] = t;
        } else if (RaceParametersRaceType == RACE_TYPE_TIME_TRIAL
                   && i == pCurrentRace->FinishLineBoundaryNumber) {
            if (timer_is_set(&rc->BoundaryCrossingTimes[0]))
                rc->RunningTimes[i].PackedTime =
                    t.PackedTime - rc->BoundaryCrossingTimes[0].PackedTime;
            rc->BoundaryCrossingTimes[i] = t;
        }
    }

    // The speeds, while nothing is replaying. TopSpeed counts only with
    // three wheels or more down. A player's is the fastest ForwardSpeed; an
    // AI car's is what its driver wants, over the catchup's BoostFactor (at
    // least 1), held to the car's speed and to its SpeedLimiter in m/s, and
    // only between 0 and 1000. TopSpeed is written only when it changes.
    if (!replaying()) {
        float rt;

        car = rc->pCar;
        if (car->State.nWheelsTouchingGround >= 3) {
            float top, s;

            if (racingcar_get_player(rc) != NULL) {
                top = rc->TopSpeed;
                s = max_s(top, rc->pCar->State.ForwardSpeed);
            } else {
                CarDriver *d = rc->pCar->pCarDriver;
                const VtEntry *e = vt_slot(d->_vtable,
                                           CARDRIVER_VT_GET_DESIRED_SPEED);
                float want = ((float (*)(void *))e->fn)(vt_this(d, e));

                car = rc->pCar;
                want = want / max_s(1.0f, car->State.BoostFactor);
                want = min_s(want, fabsf(car->State.ForwardSpeed));
                want = min_s(want, car->pCarTypeInfo->Control.SpeedLimiter
                                   * RACE_MPH_TO_MPS);
                top = rc->TopSpeed;
                s = max_s(top, want);
                if (s < 0.0f)
                    s = top;
                else if (1000.0f < s)
                    s = top;
            }
            if (!(s == top))
                rc->TopSpeed = s;
        }
        rt = (float)(int32_t)pCurrentRace->RaceTime.PackedTime * 0.00025f;
        if (0.0f < rt)
            rc->AverageSpeed = car->State.DistanceMoved / rt;
    }

    // The exact lap, and its rate smoothed: a third of the old rate and two
    // thirds of the new (gp-31460, gp-31456), over WorldTimeElapsed.
    old = rc->CurrentLapNumberExact;
    rc->CurrentLapNumberExact = (float)rc->CurrentLapNumber
                              + race_get_lap_number_exact(pCurrentRace, pct);
    rc->FinishedLapNumberExact = rc->CurrentLapNumberExact;
    if (0.0f < WorldTimeElapsed)
        rc->dCurrentLapNumberExact =
            rc->dCurrentLapNumberExact * 0.333f
            + (rc->CurrentLapNumberExact - old) / WorldTimeElapsed * 0.667f;
    rc->PreviousDistanceAroundTrack = pct;
}

struct Player *racingcar_get_player(const struct RacingCar *rc)
{
    if (rc->pCar == NULL)
        return NULL;
    return rc->pCar->pPlayer;
}

// ------------------------------------------------------------------ Race

void race_init(Race *r, eRaceStage stage)
{
    const Car *car;
    int32_t car_class;

    race_add_racing_cars(r);
    race_set_race_stage(r, stage);
    if (RaceParametersBeACop != 0 && RaceParametersNumPlayerCars == 2)
        car = r->RacingCarTable[1].pCar;
    else
        car = r->RacingCarTable[0].pCar;
    car_class = car->pCarTypeInfo->CarClass;
    r->pTimeAroundTrackTable = tatt_construct(
        (TimeAroundTrackTable *)bMalloc((int)sizeof(TimeAroundTrackTable),
                                        "TimeAroundTrackTable", 0, 16),
        car_class);
}

// pCurrentWorld and both bounds are read again on every pass.
void race_add_racing_cars(Race *r)
{
    int32_t i;

    for (i = 0; i < pCurrentWorld->AICarPos; i++)
        race_add_racing_car(r, pCurrentWorld->CarTable[i]);
    for (i = 0; i < pCurrentWorld->CopCarPos - pCurrentWorld->AICarPos; i++)
        race_add_racing_car(
            r, pCurrentWorld->CarTable[pCurrentWorld->AICarPos + i]);
    race_sort_racing_cars_by_leadership(r);
    race_sort_racing_cars_by_leadership(r);
}

void race_add_racing_car(Race *r, Car *c)
{
    int32_t n = r->NumRacingCars;

    racingcar_init(&r->RacingCarTable[n], c);
    n = r->NumRacingCars;
    r->NumRacingCars = n + 1;
    r->pRacingCars[n] = &r->RacingCarTable[n];
}

// The stage is the argument where the listing tests the argument, and
// RaceStage where it reads RaceStage back: the drivers' arms do. The
// traffic's count is taken once, its start in the table on every pass.
void race_set_race_stage(Race *r, eRaceStage stage)
{
    int32_t i, n;

    r->RaceStage = stage;
    if (stage == RACE_STAGE_RACING && gRaceIsLeavingFn != NULL)
        gRaceIsLeavingFn(r);

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        Car *car = rc->pCar;

        if (car->TheControlMode == REAL_CONTROL) {
            RealDriver *d = (RealDriver *)car->pCarDriver;

            if (r->RaceStage == RACE_STAGE_RACING)
                realdriver_disable_start_line_state(d);
            else
                d->StartLineState = 1;
        } else if (car->TheControlMode == AI_CONTROL) {
            CarDriver *d = car->pCarDriver;

            if (r->RaceStage == RACE_STAGE_RACING) {
                d->EBrake = 0.0f;
                d->Throttle = 1.0f;
                d->Brake = 0.0f;
            }
        }
        if (stage == RACE_STAGE_RACING)
            racingcar_fake_startline_crossing(rc);
    }

    if (stage == RACE_STAGE_COUNTDOWN) {
        r->StartGoTimeFrames = 0;
        r->StartCountdownTimeFrames = WorldTimeFrames;
    } else if (stage == RACE_STAGE_RACING) {
        r->StartTime.PackedTime = (uint32_t)WorldTimer;
        timer_round(&r->StartTime, 0.01f);
        r->StartCountdownTimeFrames = 0;
        r->StartGoTimeFrames = WorldTimeFrames;
    }

    if ((uint32_t)(stage - RACE_STAGE_COUNTDOWN) < 2u) {
        n = pCurrentWorld->TotalNumCars - pCurrentWorld->TrafficCarPos;
        for (i = 0; i < n; i++) {
            Car *c = pCurrentWorld->CarTable[pCurrentWorld->TrafficCarPos + i];

            c->RenderingEnabled = 1;
            car_set_movement_mode(c, TRAFFIC_MOVEMENT);
        }
    }
}

// A finished car belongs at its FinishingOrder, so the one above it swaps
// down while its place is further on, and the one below it swaps up while
// its order is ahead of the place it would take. The count is read once
// for the sort and on every pass for the positions.
void race_sort_racing_cars_by_leadership(Race *r)
{
    int32_t last = r->NumRacingCars - 1;
    int32_t n = r->NumRacingCars;
    int32_t i, swaps;

    do {
        swaps = 0;
        for (i = 0; i < last; i++) {
            struct RacingCar *a = r->pRacingCars[i];
            struct RacingCar *b = r->pRacingCars[i + 1];
            int swap;

            if (a->FinishingOrder != 0)
                swap = i + 1 < a->FinishingOrder;
            else if (b->FinishingOrder != 0)
                swap = b->FinishingOrder < i + 2;
            else
                swap = a->FinishedLapNumberExact < b->FinishedLapNumberExact;
            if (swap) {
                r->pRacingCars[i] = b;
                r->pRacingCars[i + 1] = a;
                swaps++;
            }
        }
    } while (swaps != 0);

    if (n <= 0)
        return;
    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        int8_t prev = rc->RacePosition;

        rc->RacePosition = (int8_t)(i + 1);
        rc->PreviousRacePosition = prev;
    }
}
