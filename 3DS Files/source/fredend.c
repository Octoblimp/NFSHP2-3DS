// fredend -- FrontendDatabase's end of a race; fredend.h has the map.

#include "fredend.h"

#include <stddef.h>

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "eefpu.h"
#include "endgame.h"
#include "fredrace.h"
#include "hudscore.h"
#include "player.h"
#include "racefinish.h"
#include "racerun.h"
#include "racesplit.h"

int32_t (*gHighScoreMaybeRecordFn)(HighScoreTable *t, Race *r,
                                   struct RacingCar *rc);
void (*gSetAudioDataFromSoundFn)(uint8_t *ao, int32_t a);
void (*gRaceEventPostResultsFn)(void);
void (*gRaceEventMaybeDiscardResultsFn)(void);
void (*gRaceEventCycleResultsFn)(void);
int32_t (*gIsCarAnEventRewardFn)(int32_t carType);
int32_t (*gEventTreeIsCarUnlockedFn)(int32_t carType);

// The AI's top speed in the results: up to 5% off (gp-30188).
#define AI_TOP_SPEED_CUT 0.05f

// ------------------------------------------------------- TransientStats

void transient_stats_element_construct(TransientStatsElement *e,
                                       struct RacingCar *rc)
{
    struct Player *p = racingcar_get_player(rc);
    int32_t i;

    e->FinishPosition = rc->RacePosition;
    e->UniqueDriveNumber = rc->pCar->DriverNumber;
    e->FinishReason = rc->FinishReason;
    e->RaceTime = rc->RaceTime;
    e->BestLapTime = *racingcar_get_last_best_lap_time(rc);
    e->TopSpeed = rc->TopSpeed;
    e->AverageSpeed = rc->AverageSpeed;
    if (p == NULL) {
        float r = bRandomF(1.0f, &bDefaultSeed);
        float top = e->TopSpeed;
        float lim;

        top = top - top * (r * AI_TOP_SPEED_CUT);
        e->TopSpeed = top;
        lim = rc->pCar->pCarTypeInfo->Control.SpeedLimiter;
        e->TopSpeed = lim < top ? lim : top;
    }
    e->BeACopTime = 0.0f;
    if (pCopManager != NULL) {
        e->NumTickets = copmanager_get_num_tickets(pCopManager, rc->pCar);
        if (TheRaceParameters.BeACop && p != NULL && p->PlayerNumber == 0)
            e->BeACopTime = pCopManager->fBeACopTime;
    } else
        e->NumTickets = 0;
    if (p != NULL) {
        e->PointsThisRace = p->TotalScore;
        e->PointsTotal =
            Fred.FrontendPlayers[p->PlayerNumber].AccumulatedPoints;
        e->FinishBonus = fred_figure_out_bonus_points(&Fred, pCurrentRace,
                                                      rc);
        e->HandlingMode = p->PlayerSettings.DrivingStyle;
    } else {
        e->PointsThisRace = 0;
        e->HandlingMode = -1;
        e->PointsTotal = 0;
        e->FinishBonus = 0;
    }
    for (i = 0; i < 11; i++)
        e->LapTimes[i].PackedTime = 0;
    e->NumLapTimes = rc->NumLapsCompleted;
    for (i = 1; i <= e->NumLapTimes && i < 11; i++)
        e->LapTimes[i] = rc->LapTimes[i];
}

void transient_stats_construct(TransientStats *ts, Race *r)
{
    int32_t i;

    ts->NumStats = 0;
    for (i = 0; i < r->NumRacingCars; i++) {
        transient_stats_element_construct(&ts->Stats[i], r->pRacingCars[i]);
        ts->NumStats++;
    }
}

TransientStatsElement *transient_stats_get_driver(TransientStats *ts,
                                                  int32_t driver)
{
    int32_t i;

    for (i = 0; i < ts->NumStats; i++)
        if (ts->Stats[i].UniqueDriveNumber == driver)
            return &ts->Stats[i];
    return NULL;
}

// ------------------------------------------------- the frontend database

void fred_get_options_set_from_race(FrontendDatabase *f)
{
    int32_t i;

    for (i = 0; i < PlayerNumPlayers; i++) {
        struct Player *p = PlayerPlayersByIndex[i];

        f->FrontendPlayers[p->PlayerNumber].mPlayerSettings =
            p->PlayerSettings;
        TheRaceParameters.PlayerSettings[p->PlayerNumber] = p->PlayerSettings;
    }
    switch (f->GameType) {
    case 3:
        f->SingleRaceSetupData[6] = TheRaceParameters.DamageEnabled;
        break;
    case 4:
        f->RaceKnockoutSetupData[6] = TheRaceParameters.DamageEnabled;
        break;
    case 5:
        f->LapKnockoutSetupData[5] = TheRaceParameters.DamageEnabled;
        break;
    case 6:
        f->FreeRunSetupData[2] = TheRaceParameters.DamageEnabled;
        break;
    case 7:
        f->BeTheCopSetupData[4] = TheRaceParameters.DamageEnabled;
        break;
    }
    // Fred's own, not f's: the image writes 0x002fc19c.
    Fred.DisplayOptionsData = TheRaceParameters.GlobalDisplaySettings;
    if (gSetAudioDataFromSoundFn != NULL)
        gSetAudioDataFromSoundFn(f->AudioOptionsScreenData, 0);
}

int32_t fred_figure_out_bonus_points(FrontendDatabase *f, Race *r,
                                     struct RacingCar *rc)
{
    struct Player *p;
    int32_t n, place, earns;

    (void)f;
    if (TheRaceParameters.BeACop)
        return 0;
    p = racingcar_get_player(rc);
    if (p == NULL || p->PlayerNumber != 0)
        return 0;
    n = r->NumRacingCars;
    place = rc->FinishingOrder;
    if (n == 1)
        earns = 0;
    else if (n == 2)
        earns = place == 1;
    else if (n == 3)
        earns = (uint32_t)(place - 1) <= 1;
    else
        earns = 1;
    if (!earns)
        return 0;
    return player_get_finish_bonus(p, place);
}

void fred_award_points_to_player(FrontendDatabase *f, Race *r,
                                 struct RacingCar *rc)
{
    struct Player *p = racingcar_get_player(rc);
    FrontendPlayerInfo *fpi;
    int32_t cop = 0;

    if (p == NULL)
        return;
    if (TheRaceParameters.BeACop) {
        float t = 0.0f;

        if (pCopManager != NULL)
            t = pCopManager->fBeACopTime;
        cop = ee_trunc_w(t) * 100;
    }
    // Retail tests the player's record for NULL; it is never.
    fpi = &f->FrontendPlayers[p->PlayerNumber];
    fpi->AccumulatedPoints += p->TotalScore;
    fpi->AccumulatedPoints += fred_figure_out_bonus_points(f, r, rc) + cop;
}

void fred_check_for_abortion(FrontendDatabase *f)
{
    int32_t i;

    f->bRaceWasAborted = 0;
    for (i = 0; i < 2; i++) {
        struct Player *p = PlayerPlayersByIndex[i];

        if (p != NULL && p->TimeFinishedRacing == 0)
            f->bRaceWasAborted = 1;
    }
}

int32_t fred_race_was_aborted(const FrontendDatabase *f)
{
    return f->bRaceWasAborted;
}

void fred_the_race_is_leaving(FrontendDatabase *f)
{
    if (fred_use_the_race_event(f) && gRaceEventMaybeDiscardResultsFn != NULL)
        gRaceEventMaybeDiscardResultsFn();
}

static void maybe_record(FrontendDatabase *f, Race *r, struct RacingCar *rc)
{
    if (gHighScoreMaybeRecordFn != NULL)
        gHighScoreMaybeRecordFn(&f->ChallengeHighScores, r, rc);
}

void fred_the_race_is_over(FrontendDatabase *f, Race *r)
{
    struct Player *p0 = NULL, *p1 = NULL;
    int32_t i;

    fred_get_options_set_from_race(f);
    for (i = 0; i < r->NumRacingCars; i++) {
        struct RacingCar *rc = r->pRacingCars[i];
        struct Player *p = racingcar_get_player(rc);

        if (p == NULL)
            continue;
        // Fred's own GameType, as the image reads it, but f's
        // NumPlayerCars.
        if (Fred.GameType != GAME_TYPE_BE_A_COP) {
            if (p->PlayerNumber == 0)
                p0 = p;
            if (p->PlayerNumber == 1)
                p1 = p;
        }
        if (f->NumPlayerCars == 1)
            fred_award_points_to_player(f, r, rc);
    }
    if (p0 != NULL && p1 == NULL)
        maybe_record(f, r, race_get_racing_car(r, p0->MyCar));
    else if (p0 == NULL && p1 != NULL)
        maybe_record(f, r, race_get_racing_car(r, p1->MyCar));
    else if (p0 != NULL && p1 != NULL) {
        struct RacingCar *rc1 = race_get_racing_car(r, p1->MyCar);
        struct RacingCar *rc0 = race_get_racing_car(r, p0->MyCar);
        int32_t t0 = (int32_t)racingcar_get_last_best_lap_time(rc0)->PackedTime;
        int32_t t1 = (int32_t)racingcar_get_last_best_lap_time(rc1)->PackedTime;

        if (t0 < t1) {
            maybe_record(f, r, rc0);
            maybe_record(f, r, rc1);
        } else {
            maybe_record(f, r, rc1);
            maybe_record(f, r, rc0);
        }
    }
    transient_stats_construct(&f->TransientStatsTable, r);
    if (fred_use_the_race_event(f) && gRaceEventPostResultsFn != NULL)
        gRaceEventPostResultsFn();
    nfs_check_for_task_and_point_rewards(r);
}

void fred_the_race_was_quit(FrontendDatabase *f)
{
    fred_check_for_abortion(f);
    fred_get_options_set_from_race(f);
    if (!fred_use_the_race_event(f))
        return;
    if (race_are_all_players_finished_racing(pCurrentRace)) {
        race_simulate_race_finish(pCurrentRace);
        race_notify_the_race_is_over(pCurrentRace);
    }
    if (gRaceEventPostResultsFn != NULL)
        gRaceEventPostResultsFn();
    if (gRaceEventKeepStateFn != NULL)
        gRaceEventKeepStateFn();
}

void fred_the_race_was_restarted(FrontendDatabase *f)
{
    if (fred_use_the_race_event(f) && gRaceEventCycleResultsFn != NULL)
        gRaceEventCycleResultsFn();
}

// ----------------------------------------------------------- the rewards

int nfs_task_check_for_completion(const NFSTaskParameters *t,
                                  struct RacingCar *rc)
{
    const RaceParameters *rp = &TheRaceParameters;
    int32_t led = rc->NumLapsLed;
    int32_t cops = rp->nMaxCops > 0;
    int32_t gt = Fred.GameType;
    struct Player *p = racingcar_get_player(rc);

    // The image works out rc's car's visible damage here and drops it.
    // With no player it would read New2540 from low memory, a zero.
    if (t->MinDamage != -1.0f && (p == NULL || p->New2540 == 0))
        return 0;
    if (t->NumPlayers != -1 && rp->NumPlayerCars != t->NumPlayers)
        return 0;
    if (t->GameType != -1) {
        if (gt != t->GameType)
            return 0;
        if (gt == 4 && Fred.NumPlayerCars == 1) {
            if (rp->NumPlayerCars + rp->NumAICars >= 3)
                return 0;
            if (rc->FinishingOrder != 1)
                return 0;
        }
        if (gt == 5 && rc->FinishingOrder != 1)
            return 0;
    }
    if (t->NumOpponents != -1 && rp->NumAICars != t->NumOpponents)
        return 0;
    if (t->NumLaps != -1 && rp->NumLapsInRace != t->NumLaps)
        return 0;
    if (t->SkillLevel != -1 && rp->OpponentStrength != t->SkillLevel)
        return 0;
    if (t->NumLapsToLead != -1 && led != t->NumLapsToLead)
        return 0;
    if (t->Cops != -1 && cops != t->Cops)
        return 0;
    return 1;
}

int32_t nfs_get_task_reward_list(const NFSTaskParameters **list,
                                 int32_t *n, struct RacingCar *rc)
{
    int32_t i;

    *n = 0;
    for (i = 0; i < NFS_NUM_TASKS; i++) {
        const NFSTaskParameters *t = &NFSTasks[i];

        if (!nfs_task_check_for_completion(t, rc))
            continue;
        if (Fred.TaskRewardStates[t->IndexIntoFredTaskState] != 0)
            continue;
        list[(*n)++] = t;
    }
    return *n;
}

int32_t nfs_get_points_reward_list(const NFSPointsRewards **list,
                                   int32_t *n, int32_t points)
{
    int32_t i;

    *n = 0;
    for (i = 0; i < NFS_NUM_POINTS_REWARDS; i++) {
        const NFSPointsRewards *pr = &NFSPointsRewardsArray[i];

        if (!nfs_points_reward_check_for_completion(pr, points))
            continue;
        if (Fred.PointsRewardStates[pr->IndexIntoFred] != 0)
            continue;
        list[(*n)++] = pr;
    }
    return *n;
}

void nfs_check_for_task_and_point_rewards(Race *r)
{
    TransientStats *ts = &Fred.TransientStatsTable;
    const NFSTaskParameters *tasks[NFS_NUM_TASKS];
    const NFSPointsRewards *points[NFS_NUM_POINTS_REWARDS];
    struct RacingCar *rc;
    int32_t i, n;

    ts->PointsRewardEarned = -1;
    ts->TaskRewardEarned = -1;
    if (!(PlayerNumPlayers < 2) || PlayerPlayersByNumber[0] == NULL)
        return;
    rc = race_get_racing_car(r, PlayerPlayersByNumber[0]->MyCar);
    if (Fred.GameType != 2) {
        nfs_get_task_reward_list(tasks, &n, rc);
        for (i = 0; i < n; i++) {
            Fred.TaskRewardStates[tasks[i]->IndexIntoFredTaskState] = 1;
            ts->TaskRewardEarned = tasks[i]->TaskNumber;
        }
    }
    nfs_get_points_reward_list(points, &n,
                               Fred.FrontendPlayers[0].AccumulatedPoints);
    for (i = 0; i < n; i++) {
        Fred.PointsRewardStates[points[i]->IndexIntoFred] = 1;
        ts->PointsRewardEarned = points[i]->IndexIntoFred;
    }
}

int32_t nfs_task_rewards_is_car_unlocked(int32_t carType, int32_t gameType)
{
    int32_t i;

    for (i = 0; i < NFS_NUM_TASKS; i++) {
        const NFSTaskParameters *t = &NFSTasks[i];

        if (t->UnlockedInGameType != -1 && gameType != t->UnlockedInGameType)
            continue;
        if (t->Reward != carType)
            continue;
        return Fred.TaskRewardStates[t->IndexIntoFredTaskState] != 0;
    }
    return 0;
}

int32_t nfs_points_rewards_is_car_unlocked(int32_t carType)
{
    int32_t i;

    for (i = 0; i < NFS_NUM_POINTS_REWARDS; i++) {
        const NFSPointsRewards *pr = &NFSPointsRewardsArray[i];

        if (pr->Reward == carType)
            return Fred.PointsRewardStates[pr->IndexIntoFred] != 0;
    }
    return 0;
}

int32_t nfs_is_car_unlocked(int32_t carType, int32_t gameType)
{
    if (nfs_is_car_a_task_reward(carType, gameType))
        return nfs_task_rewards_is_car_unlocked(carType, gameType);
    if (gameType == GAME_TYPE_BE_A_COP)
        return 0;
    if (gIsCarAnEventRewardFn != NULL && gIsCarAnEventRewardFn(carType))
        return gEventTreeIsCarUnlockedFn != NULL
                   ? gEventTreeIsCarUnlockedFn(carType) : 0;
    if (nfs_is_car_a_points_reward(carType))
        return nfs_points_rewards_is_car_unlocked(carType);
    return 0;
}
