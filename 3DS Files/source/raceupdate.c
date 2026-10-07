// raceupdate -- see raceupdate.h. Step 11g-2b.

#include "raceupdate.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "aicarcontroller.h"
#include "aidriver.h"
#include "bmem.h"
#include "car.h"
#include "copmanager.h"
#include "eefpu.h"
#include "player.h"
#include "playerfinish.h"
#include "racerun.h"
#include "racesplit.h"
#include "realtime.h"
#include "replay.h"
#include "worldobject.h"

void (*gLapFinishedSpeechFn)(struct Car *car, int32_t laps);
void (*gGhostCarDataAddSampleFn)(struct GhostCarData *d, const bMatrix4 *m,
                                 Timer *t);
int32_t (*gGhostCarDataGetSampleFn)(struct GhostCarData *d, bMatrix4 *m,
                                    Timer *t);
void (*gBWriteToFileFn)(const char *name, void *data, int32_t size);

// A hundredth of a second, the step every race time is rounded to:
// gp-31396, gp-31408, gp-31416 and gp-31452. ProjectRaceTime keeps
// gp-31452 in one register as its floor on the fraction of the race done
// as well.
#define RACE_ROUND_SECONDS 0.01f

// A tick, in seconds: gp-31404, gp-31412 and gp-31448.
#define RACE_TICK_SECONDS 0.00025f

// MonitorLeadership's fences: a car under 40 m/s or over 25 m from the
// car it passed makes no event, and ClosePass wants the two within
// 7 m/s. Each is built with `lui`.
#define LEAD_MIN_SPEED 40.0f
#define LEAD_MAX_DISTANCE 25.0f
#define LEAD_CLOSE_SPEED 7.0f

// The ghost replaying is drawn this much lower (`lui 0xbf00`).
#define GHOST_DROP -0.5f

// The image calls RegisterInterestingEvent on pReplayManager without a
// test, as carfinish.c's finish does. The port tests it: there is no
// ReplayManager yet.
static void interesting(float value, const char *what)
{
    if (pReplayManager != NULL)
        ReplayManager_RegisterInterestingEvent(pReplayManager, value, what);
}

// `vsub.xyzw ; vmul.xyz ; vaddy.x ; vaddz.x ; sqrt.s`: (x*x + y*y) + z*z,
// left to right, of a - b.
static float distance(const bVector3 *a, const bVector3 *b)
{
    float dx = a->x - b->x;
    float dy = a->y - b->y;
    float dz = a->z - b->z;

    return sqrtf((dx * dx + dy * dy) + dz * dz);
}

// ------------------------------------------------------------- RacingCar

void racingcar_project_race_time(struct RacingCar *rc, int32_t laps,
                                 const Timer *start)
{
    float n = (float)laps;
    float done = ee_div(rc->CurrentLapNumberExact, n);
    float s;
    Timer t;
    Timer *best;

    if (done < RACE_ROUND_SECONDS)
        done = RACE_ROUND_SECONDS;
    s = (float)(int32_t)((uint32_t)WorldTimer - start->PackedTime)
        * RACE_TICK_SECONDS;
    timer_set_time(&t, s / done);
    rc->RaceTime = t;
    timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);
    if (rc->NumLapsCompleted != 0 || laps <= 0)
        return;

    // Out of [0, 4], the image reads and writes past the arrays; the
    // accessors read 0 and write to a Timer nothing reads.
    s = (float)(int32_t)((uint32_t)WorldTimer
                         - racingcar_get_last_start_line_crossing_time(rc)
                               ->PackedTime)
        * RACE_TICK_SECONDS;
    s = s / done;
    s = s / n;
    best = racingcar_get_last_best_lap_time(rc);
    best->PackedTime = (uint32_t)ee_trunc_w(s * 4000.0f + 0.5f);
    timer_round(racingcar_get_last_best_lap_time(rc), RACE_ROUND_SECONDS);
}

// ------------------------------------------------------------------ Race

void race_monitor_leadership(Race *r)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++) {
        struct Player *p = PlayerPlayersByIndex[i];
        struct RacingCar *rc;
        Car *mine, *other;
        int32_t pos, prev;
        float speed, other_speed;

        if (p == NULL)
            continue;
        rc = p->MyCar->pRacingCar;
        pos = rc->RacePosition;
        prev = rc->PreviousRacePosition;
        if (pos == prev)
            continue;
        // The car now in the old place. Positions run from 1 to
        // NumRacingCars once the field is sorted; the image reads through
        // NULL for an old place past them, and before pRacingCars for one
        // below 1. The port stops at either.
        if (r->NumRacingCars < prev || prev < 1)
            continue;
        other = r->pRacingCars[prev - 1]->pCar;
        mine = rc->pCar;
        speed = mine->State.VelocityMagnitude;
        if (!(LEAD_MIN_SPEED < speed))
            continue;
        other_speed = other->State.VelocityMagnitude;
        if (!(distance(&mine->State.Position, &other->State.Position)
              < LEAD_MAX_DISTANCE))
            continue;
        if (pos < prev)
            interesting(ee_div(4.0f, (float)pos) + 1.0f, "GainPosition");
        else
            interesting(2.0f / (float)prev, "LosePosition");
        if (fabsf(speed - other_speed) < LEAD_CLOSE_SPEED)
            interesting(2.5f, "ClosePass");
    }
}

// GhostCarData::GetSize, inline: the head and the samples taken.
static int32_t ghost_size(const struct GhostCarData *d)
{
    return (int32_t)sizeof(struct GhostCarData)
           - (GHOSTCAR_MAX_SAMPLES - d->NumSamples) * GHOSTCAR_SAMPLE_BYTES;
}

// Timer::PrintToString runs on the car's time and the replaying ghost's,
// into the stack, for a print that is compiled out. The port leaves both
// out.
void race_maybe_save_ghost_car_data(Race *r, struct RacingCar *rc)
{
    struct GhostCarData *d;
    int save;

    if (rc->pCar != r->pCapturingGhostCar)
        return;
    d = r->pCapturingGhostCarData;
    d->RaceTime = rc->RaceTime;
    if (r->pReplayingGhostCarData == NULL) {
        save = 1;
    } else {
        Timer best = r->pReplayingGhostCarData->RaceTime;

        save = (int32_t)rc->RaceTime.PackedTime < (int32_t)best.PackedTime;
        if (r->pReplayingGhostCarData->NumLaps != r->NumLapsInRace)
            save = 0;
    }
    if (rc->NumLapsCompleted != r->NumLapsInRace)
        save = 0;
    if (save && gBWriteToFileFn != NULL)
        gBWriteToFileFn(r->GhostCarDataFilename, d, ghost_size(d));
    // `__builtin_delete`, which is bFree, unchecked.
    bFree(r->pCapturingGhostCarData);
    r->pCapturingGhostCar = NULL;
    r->pCapturingGhostCarData = NULL;
}

void race_update_ghost_car(Race *r)
{
    bMatrix4 m;

    if (r->RaceStage == RACE_STAGE_RACING && r->pCapturingGhostCar != NULL) {
        const Car *c = r->pCapturingGhostCar;
        Timer t = r->RaceTime;

        m = c->State.BodyMatrix;
        memcpy(&m.v3, &c->State.Position, sizeof m.v3);
        if (gGhostCarDataAddSampleFn != NULL)
            gGhostCarDataAddSampleFn(r->pCapturingGhostCarData, &m, &t);
    }
    if (r->pReplayingGhostCarData == NULL || !timer_is_valid(&r->RaceTime))
        return;
    // The image takes bSin of the time (x 43690.668, gp-31400) here and
    // loads -0.5 over the answer before it is read, so the ghost does not
    // bob. The port leaves the call out.
    if (gGhostCarDataGetSampleFn != NULL
        && gGhostCarDataGetSampleFn(r->pReplayingGhostCarData, &m,
                                    &r->RaceTime)) {
        m.v3.z = m.v3.z + GHOST_DROP;
        r->pReplayingGhostCarWorldObject->Matrix = m;
        r->pReplayingGhostCarWorldObject->Enabled = 1;
    } else {
        r->pReplayingGhostCarWorldObject->Enabled = 0;
    }
}

void race_finish_car(Race *r, int32_t index, int32_t position,
                     int32_t blink, eRaceFinishReason reason)
{
    struct RacingCar *rc = r->pRacingCars[index];
    struct Player *p = racingcar_get_player(rc);
    Car *car = rc->pCar;

    if (reason == RACING_CAR_BE_THE_COP_WON) {
        rc->RaceTime.PackedTime =
            (uint32_t)WorldTimer - r->StartTime.PackedTime;
        timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);
    } else if (reason == RACING_CAR_BE_THE_COP_LOST) {
        float s = (float)(int32_t)TheRaceParameters.TimeTrialTime.PackedTime
                  * RACE_TICK_SECONDS + RACE_ROUND_SECONDS;

        rc->RaceTime.PackedTime = (uint32_t)ee_trunc_w(s * 4000.0f + 0.5f);
        timer_round(&rc->RaceTime, RACE_ROUND_SECONDS);
    }

    if (position == 0) {
        if (rc->NumLapsCompleted == r->NumLapsInRace) {
            rc->FinishingOrder = (int8_t)race_get_next_finish_rank(r);
            rc->RaceTime.PackedTime =
                racingcar_get_last_finish_line_crossing_time(rc)->PackedTime
                - r->StartTime.PackedTime;
            if (p != NULL)
                race_maybe_save_ghost_car_data(r, rc);
        } else {
            rc->FinishingOrder = (int8_t)race_get_next_finish_rank(r);
            racingcar_project_race_time(rc, r->NumLapsInRace,
                                        &r->StartTime);
        }
    } else if (position > 0) {
        rc->FinishingOrder = (int8_t)position;
    }

    rc->FinishReason = (int16_t)reason;
    rc->FinishedLapNumberExact = rc->CurrentLapNumberExact;
    r->NumRacingCarsFinished++;
    if (gRaceEventRecordResultsFn != NULL)
        gRaceEventRecordResultsFn(r, rc, rc->FinishingOrder);
    if (p != NULL) {
        player_set_finished_racing(p);
        car_set_control_mode(car, AI_CONTROL);
    }
    if (car->TheControlMode == AI_CONTROL)
        aicarcontroller_force_pull_over(
            (AICarController *)(void *)car->pCarController,
            AIActionPullOverCrossFinishLineTimeout);
    if (blink)
        car_blink_blink_poof(car);
}

void race_finish_car_by_car(Race *r, struct Car *car, int32_t position,
                            int32_t blink, eRaceFinishReason reason)
{
    struct RacingCar *rc = car->pRacingCar;
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        if (r->pRacingCars[i] != rc)
            continue;
        if (position == 0)
            position = rc->RacePosition;
        race_finish_car(r, i, position, blink, reason);
        return;
    }
}

struct RacingCar *race_get_leading_unfinished_car(Race *r)
{
    int32_t best = r->NumRacingCars + 1;
    struct RacingCar *lead = NULL;
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];

        if (rc->FinishingOrder != 0)
            continue;
        if (rc->RacePosition < best) {
            best = rc->RacePosition;
            lead = rc;
        }
    }
    return lead;
}

struct RacingCar *race_get_finisher(Race *r, int32_t rank)
{
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        if (r->pRacingCars[i]->FinishingOrder == rank)
            return r->pRacingCars[i];
    }
    return NULL;
}

int32_t race_get_next_finish_rank(Race *r)
{
    int32_t rank = 1;

    while (race_get_finisher(r, rank) != NULL)
        rank++;
    return rank;
}

// --------------------------------------------------------------- Update

// The forced finish: the player numbered ForceRaceFinishPlayerNum, if
// still racing, at ForceRaceFinishPosition -- or, when that player is the
// player cop, as the cop's win (a position below NumRacingCars) or loss,
// with its order left alone. NumRacingCarsFinished starts again from 0.
static void force_finish(Race *r)
{
    int32_t pos = r->ForceRaceFinishPosition;
    int32_t i;

    r->NumRacingCarsFinished = 0;
    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        struct Player *p;
        tCop *cop;
        int32_t at = pos;
        eRaceFinishReason why = RACING_CAR_NORMAL_COMPLETION;

        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)
            continue;
        p = racingcar_get_player(rc);
        if (p == NULL || p->PlayerNumber != r->ForceRaceFinishPlayerNum)
            continue;
        cop = copmanager_get_player_cop(pCopManager);
        if (cop != NULL && cop->pMyCar != NULL
            && cop->pMyCar->pPlayer == p) {
            at = -1;
            why = pos < r->NumRacingCars ? RACING_CAR_BE_THE_COP_WON
                                         : RACING_CAR_BE_THE_COP_LOST;
        }
        race_finish_car(r, i, at, 0, why);
        break;
    }
    r->ForceRaceFinishPosition = 0;
    r->ForceRaceFinishPlayerNum = 0;
}

// A lap knockout: a car that crossed the line with its laps and its place
// adding up to the field knocks out every unfinished car behind it, each
// at its own place.
static void lap_knockout(Race *r)
{
    int32_t i, j;

    for (i = 0; i < r->NumRacingCars; i++) {
        const struct RacingCar *rc = r->pRacingCars[i];

        if (!rc->CrossedFinishLine
            || rc->NumLapsCompleted + rc->RacePosition != r->NumRacingCars)
            continue;
        for (j = i + 1; j < r->NumRacingCars; j++) {
            if (r->pRacingCars[j]->FinishReason == RACING_CAR_NOT_FINISHED)
                race_finish_car(r, j, j + 1, 1, RACING_CAR_KNOCKED_OUT);
        }
    }
}

// A time trial: an unfinished car that crossed the line with a lap time
// set and no longer than the time trial's finishes. Both are signed.
static void time_trial(Race *r)
{
    int32_t i;

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        int32_t limit;

        if (!rc->CrossedFinishLine
            || rc->FinishReason != RACING_CAR_NOT_FINISHED)
            continue;
        limit = (int32_t)TheRaceParameters.TimeTrialTime.PackedTime;
        if (!timer_is_valid(racingcar_get_last_lap_time(rc)))
            continue;
        if (!(limit < (int32_t)racingcar_get_last_lap_time(rc)->PackedTime))
            race_finish_car(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);
    }
}

void race_update(Race *r)
{
    int32_t i;

    if (r->RaceStage == RACE_STAGE_COUNTDOWN
        && race_get_countdown_number_to_display(r) == 4)
        race_set_race_stage(r, RACE_STAGE_RACING);
    if (r->RaceStage == RACE_STAGE_RACING) {
        r->RaceTime.PackedTime =
            (uint32_t)WorldTimer - r->StartTime.PackedTime;
        timer_round(&r->RaceTime, RACE_ROUND_SECONDS);
    }
    race_update_ghost_car(r);

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];

        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)
            continue;
        racingcar_update_lap_counts(rc);
        if (rc->pCar->pPlayer != NULL
            && (int32_t)racingcar_get_last_best_lap_time(rc)->PackedTime
                   < (int32_t)r->BestLapTime.PackedTime)
            r->BestLapTime = *racingcar_get_last_best_lap_time(rc);
    }
    if (r->ForceRaceFinishPosition != 0)
        force_finish(r);
    race_sort_racing_cars_by_leadership(r);
    race_monitor_leadership(r);

    if (TheRaceParameters.RaceType == RACE_TYPE_LAP_KNOCKOUT)
        lap_knockout(r);
    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL)
        time_trial(r);

    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];

        if (rc->FinishReason == RACING_CAR_NOT_FINISHED
            && rc->CrossedFinishLine && rc->RacePosition == 1)
            rc->NumLapsLed = (int16_t)(rc->NumLapsLed + 1);
    }
    if (r->NumLapsInRace != 0) {
        for (i = 0; i < r->NumRacingCars; i++) {
            struct RacingCar *rc = r->pRacingCars[i];

            if (rc->FinishReason == RACING_CAR_NOT_FINISHED
                && rc->NumLapsCompleted == r->NumLapsInRace)
                race_finish_car(r, i, 0, 0, RACING_CAR_NORMAL_COMPLETION);
        }
    }
    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];

        if (rc->FinishReason != RACING_CAR_NOT_FINISHED)
            continue;
        if (rc->CrossedFinishLine && gLapFinishedSpeechFn != NULL)
            gLapFinishedSpeechFn(rc->pCar, rc->NumLapsCompleted);
    }
}
