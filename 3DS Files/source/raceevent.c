// raceevent -- RaceEvent, the event being raced. See raceevent.h; the
// decode is docs/formats/race-event.md.

#include "raceevent.h"

#include <string.h>

#include "car.h"
#include "copmanager.h"
#include "fred.h"
#include "fredend.h"
#include "fredrace.h"
#include "racesplit.h"
#include "raceparams.h"
#include "timer.h"

RaceEvent TheRaceEvent;

void (*gEventTrackSetRaceOnFn)(const EventTrack *t, RaceParameters *rp);

// What a NULL state reads as: the bottom of memory, zeros in retail.
static const uint8_t kNoState[16];

enum { GROUP_RANK, GROUP_TIME, GROUP_KO, GROUP_TOURNAMENT, GROUP_NONE };

static int group(const RaceEvent *ev)
{
    switch (ev->nType) {
    case EVENT_RACE:
    case EVENT_LAP_KNOCKOUT:
        return GROUP_RANK;
    case EVENT_TIME_TRIAL:
    case EVENT_POINT2POINT:
    case EVENT_BE_A_COP:
        return GROUP_TIME;
    case EVENT_RACE_KNOCKOUT:
        return GROUP_KO;
    case EVENT_TOURNAMENT:
        return GROUP_TOURNAMENT;
    default:
        return GROUP_NONE;
    }
}

static const uint8_t *rd(const uint8_t *s)
{
    return s != NULL ? s : kNoState;
}

static int32_t rd32(const uint8_t *s)
{
    uint32_t v;

    memcpy(&v, rd(s), 4);
    return (int32_t)v;
}

// An EventTimeState's time that counts: neither 0 nor 0x7fffffff.
static int time_set(int32_t t)
{
    return t != 0 && t != 0x7fffffff;
}

// The reward by index, NULL from nRewards on. Retail reads any index under
// nRewards, past aRewards' eight when the count runs over; the port stops
// at the array's end.
static const EventReward *reward(const RaceEvent *ev, int32_t i)
{
    if (i >= ev->nRewards || i < 0 || i >= 8)
        return NULL;
    return &ev->aRewards[i];
}

int32_t raceevent_get_state_size(const RaceEvent *ev)
{
    switch (group(ev)) {
    case GROUP_TIME:
        return 4;
    case GROUP_KO:
    case GROUP_TOURNAMENT:
        return 16;
    default:
        return 1;
    }
}

int32_t raceevent_is_multi_track(const RaceEvent *ev)
{
    return (uint32_t)((uint16_t)ev->nType - 3) < 2u;
}

int32_t raceevent_race_was_aborted(const RaceEvent *ev)
{
    (void)ev;
    return fred_race_was_aborted(&Fred);
}

void raceevent_reset_results(RaceEvent *ev)
{
    int32_t i;

    for (i = 0; i < 8; i++)
        memset(&ev->aResults[i], 0, sizeof ev->aResults[0]);
}

int32_t raceevent_racer_index_from_driver_number(const RaceEvent *ev,
                                                 int32_t n)
{
    return n < 100 ? n : ev->nInitialPlayers + n - 100;
}

int32_t raceevent_driver_number_from_racer_index(const RaceEvent *ev,
                                                 int32_t i)
{
    return i < ev->nInitialPlayers ? i : i - (ev->nInitialPlayers - 100);
}

// Retail writes the result at any index; past the eight it lands in the
// next object (0x0031b7b0). The port drops it.
void raceevent_record_results(RaceEvent *ev, Race *race,
                              struct RacingCar *rc, int32_t pos)
{
    int32_t idx = raceevent_racer_index_from_driver_number(
        ev, rc->pCar->DriverNumber);
    int32_t reason = rc->FinishReason;
    Timer t;

    (void)race;
    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL)
        t = *racingcar_get_last_best_lap_time(rc);
    else
        t = rc->RaceTime;
    if (TheRaceParameters.BeACop)
        timer_set_time(&t, pCopManager != NULL ? pCopManager->fBeACopTime
                                               : 0.0f);
    if ((uint32_t)idx < 8u) {
        ev->aResults[idx].nPosition = pos;
        ev->aResults[idx].Time = t;
        ev->aResults[idx].nFinishReason = reason;
    }
}

int32_t raceevent_racer_in_the_race(const RaceEvent *ev, int32_t i)
{
    return raceevent_driver_in_the_race(
        ev, raceevent_driver_number_from_racer_index(ev, i));
}

int32_t raceevent_driver_in_the_race(const RaceEvent *ev, int32_t n)
{
    const DriverInfo *d = race_parameters_find_driver(&TheRaceParameters, n);

    (void)ev;
    return d != NULL && d->EliminatedRank == 0;
}

int32_t raceevent_racer_eliminated(const RaceEvent *ev, int32_t i)
{
    if (TheRaceParameters.RaceType != RACE_TYPE_RACE_KNOCKOUT)
        return 0;
    return ko_state_get_rank(rd(ev->pState), i) != 0;
}

int32_t raceevent_driver_eliminated(const RaceEvent *ev, int32_t n)
{
    return raceevent_racer_eliminated(
        ev, raceevent_racer_index_from_driver_number(ev, n));
}

int32_t raceevent_get_last_place(const RaceEvent *ev)
{
    int32_t i, best = 0, at = 0;

    for (i = 0; i < 8; i++) {
        if (!raceevent_racer_in_the_race(ev, i))
            continue;
        if (best < ev->aResults[i].nPosition) {
            best = ev->aResults[i].nPosition;
            at = i;
        }
    }
    return at;
}

int32_t raceevent_get_first_place(const RaceEvent *ev)
{
    int32_t i, best = 8, at = 0;

    for (i = 0; i < 8; i++) {
        if (!raceevent_racer_in_the_race(ev, i))
            continue;
        if (ev->aResults[i].nPosition < best) {
            best = ev->aResults[i].nPosition;
            at = i;
        }
    }
    return at;
}

uint8_t *raceevent_get_rank_state(const RaceEvent *ev)
{
    return group(ev) == GROUP_RANK ? ev->pState : NULL;
}

uint8_t *raceevent_get_tournament_state(const RaceEvent *ev)
{
    return group(ev) == GROUP_TOURNAMENT ? ev->pState : NULL;
}

uint8_t *raceevent_get_ko_state(const RaceEvent *ev)
{
    return group(ev) == GROUP_KO ? ev->pState : NULL;
}

uint8_t *raceevent_get_time_state(const RaceEvent *ev)
{
    return group(ev) == GROUP_TIME ? ev->pState : NULL;
}

void raceevent_post_results(RaceEvent *ev)
{
    uint8_t *s = ev->pState;
    const EventResult *r = ev->aResults;
    int32_t i, k;

    if (raceevent_race_was_aborted(ev))
        return;
    if (s == NULL)
        return;
    switch (group(ev)) {
    case GROUP_RANK:
        s[0] = (uint8_t)r[0].nPosition;
        break;
    case GROUP_TIME:
        memcpy(s, &r[0].Time.PackedTime, 4);
        break;
    case GROUP_KO:
        k = raceevent_get_last_place(ev);
        ko_state_set_rank(s, k, r[k].nPosition);
        if (TheRaceParameters.NumPlayerCars + TheRaceParameters.NumAICars
            < 3) {
            k = raceevent_get_first_place(ev);
            ko_state_set_rank(s, k, r[k].nPosition);
        }
        for (i = 0; i < 8; i++)
            ko_state_set_start_position(s, i, r[i].nPosition);
        break;
    case GROUP_TOURNAMENT:
        // gp-16648's points by place; retail reads past the table for a
        // place over 8, which no race gives.
        for (i = 0; i < 8; i++) {
            if (r[i].nPosition != 0)
                s[i] = (uint8_t)(s[i] + tournament_state_points_for_finish_pos(
                                            r[i].nPosition - 1));
        }
        break;
    default:
        break;
    }
}

void raceevent_save_state(RaceEvent *ev)
{
    memcpy(ev->aSavedState, rd(ev->pState),
           (size_t)raceevent_get_state_size(ev));
}

// Retail writes through a NULL state into the bottom of memory; the port
// does not write.
static void put_state(RaceEvent *ev, const uint8_t *from)
{
    if (ev->pState != NULL)
        memcpy(ev->pState, from, (size_t)raceevent_get_state_size(ev));
}

void raceevent_cycle_results(RaceEvent *ev)
{
    if (!raceevent_is_multi_track(ev)
        || !raceevent_is_there_another_race(ev))
        memcpy(ev->aOldState, rd(ev->pState),
               (size_t)raceevent_get_state_size(ev));
    put_state(ev, ev->aSavedState);
}

void raceevent_restart(RaceEvent *ev)
{
    if (!raceevent_is_there_another_race(ev) && !raceevent_status_fell(ev))
        memcpy(ev->aOldState, rd(ev->pState),
               (size_t)raceevent_get_state_size(ev));
    raceevent_reset_state(ev);
    raceevent_reset_results(ev);
    race_parameters_restore_eliminated(&TheRaceParameters);
    race_parameters_reset_start_positions(&TheRaceParameters);
    fred_calculate_starting_positions(&Fred);
    if (gEventTrackSetRaceOnFn != NULL)
        gEventTrackSetRaceOnFn(&ev->aTracks[0], &TheRaceParameters);
}

int32_t raceevent_status_fell(const RaceEvent *ev)
{
    int32_t old = raceevent_get_old_status(ev);
    int32_t cur = raceevent_get_status(ev);
    const uint8_t *s;
    int32_t o, n;

    if (cur < old)
        return old != EVENT_FAILED;
    if (old != cur)
        return 0;
    switch (group(ev)) {
    case GROUP_RANK:
        if ((s = raceevent_get_rank_state(ev)) == NULL)
            return 0;
        o = ev->aOldState[0];
        if (o == 0)
            return 0;
        n = s[0];
        if (n == 0)
            return 1;
        return o < n;
    case GROUP_TIME:
        if ((s = raceevent_get_time_state(ev)) == NULL)
            return 0;
        o = rd32(ev->aOldState);
        if (!time_set(o))
            return 0;
        n = rd32(s);
        if (!time_set(n))
            return 1;
        return o < n;
    case GROUP_KO:
        if (!fred_use_tree_event(&Fred))
            return 0;
        if ((s = raceevent_get_ko_state(ev)) == NULL)
            return 0;
        o = ko_state_get_rank(ev->aOldState, 0);
        n = ko_state_get_rank(s, 0);
        if (o == 0)
            return n != 0;
        if (n == 0)
            return 0;
        return o < n;
    case GROUP_TOURNAMENT:
        if ((s = raceevent_get_tournament_state(ev)) == NULL)
            return 0;
        if (old < 2)
            return 0;
        return (uint32_t)tournament_state_user_rank(ev->aOldState)
               < (uint32_t)tournament_state_user_rank(s);
    default:
        return 0;
    }
}

int32_t raceevent_status_advanced(const RaceEvent *ev)
{
    int32_t old = raceevent_get_old_status(ev);
    int32_t cur = raceevent_get_status(ev);
    const uint8_t *s;
    int32_t o, n;

    if (old != cur)
        return old < cur;
    switch (group(ev)) {
    case GROUP_RANK:
        if ((s = raceevent_get_rank_state(ev)) == NULL)
            return 0;
        n = s[0];
        if (n == 0)
            return 0;
        o = ev->aOldState[0];
        if (o == 0)
            return 1;
        return n < o;
    case GROUP_TIME:
        if ((s = raceevent_get_time_state(ev)) == NULL)
            return 0;
        n = rd32(s);
        if (!time_set(n))
            return 0;
        o = rd32(ev->aOldState);
        if (!time_set(o))
            return 1;
        return n < o;
    case GROUP_KO:
        if (!fred_use_tree_event(&Fred))
            return 0;
        if ((s = raceevent_get_ko_state(ev)) == NULL)
            return 0;
        o = ko_state_get_rank(ev->aOldState, 0);
        n = ko_state_get_rank(s, 0);
        if (n == 0)
            return o != 0;
        if (o == 0)
            return 0;
        return n < o;
    case GROUP_TOURNAMENT:
        if ((s = raceevent_get_tournament_state(ev)) == NULL)
            return 0;
        if (cur < 3)
            return 0;
        if (old < 2)
            return 1;
        return (uint32_t)tournament_state_user_rank(s)
               < (uint32_t)tournament_state_user_rank(ev->aOldState);
    default:
        return 0;
    }
}

void raceevent_keep_state(RaceEvent *ev)
{
    if (raceevent_status_fell(ev))
        put_state(ev, ev->aOldState);
}

int32_t raceevent_get_race_index(const RaceEvent *ev)
{
    if (ev->nType == EVENT_RACE_KNOCKOUT)
        return ev->pState != NULL ? ko_state_get_race_index(ev->pState) : 0;
    if (ev->nType == EVENT_TOURNAMENT)
        return ev->pState != NULL
                   ? tournament_state_get_race_index(ev->pState,
                                                     ev->nOpponents)
                   : 0;
    return 0;
}

int32_t raceevent_get_race_count(const RaceEvent *ev)
{
    if (ev->nType == EVENT_RACE_KNOCKOUT)
        return ev->nOpponents;
    if (ev->nType == EVENT_TOURNAMENT)
        return ev->nTracks;
    return 1;
}

// The track of the race to come, the race index over the track count.
// Retail traps on a count of 0 and reads past aTracks for an index outside
// it; the port sets no track.
static void set_next_track(RaceEvent *ev)
{
    int32_t idx = raceevent_get_race_index(ev), k;

    if (ev->nTracks == 0)
        return;
    k = idx % ev->nTracks;
    if (k < 0 || k >= 8 || gEventTrackSetRaceOnFn == NULL)
        return;
    gEventTrackSetRaceOnFn(&ev->aTracks[k], &TheRaceParameters);
}

int32_t raceevent_setup_next_race(RaceEvent *ev)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t k;

    if (!raceevent_is_there_another_race(ev))
        return 0;
    rp->PlayerSettings[0] = Fred.FrontendPlayers[0].mPlayerSettings;
    if (ev->nType == EVENT_RACE_KNOCKOUT) {
        k = raceevent_get_last_place(ev);
        race_parameters_eliminate_driver(
            rp, raceevent_driver_number_from_racer_index(ev, k),
            ev->aResults[k].nPosition);
        raceevent_calc_starting_positions(ev);
        set_next_track(ev);
    } else if (ev->nType == EVENT_TOURNAMENT) {
        raceevent_calc_starting_positions(ev);
        set_next_track(ev);
    }
    return 1;
}

int32_t raceevent_calc_starting_positions(RaceEvent *ev)
{
    RaceParameters *rp = &TheRaceParameters;
    const uint8_t *ts;
    DriverInfo *d;
    int32_t i;

    if (ev->nType == EVENT_RACE_KNOCKOUT) {
        if (raceevent_get_race_index(ev) == 0)
            return 0;
        rp->PlayerStartPosition[0] = (int8_t)ev->aResults[0].nPosition;
        rp->PlayerStartPosition[1] = (int8_t)ev->aResults[1].nPosition;
        for (i = 0; i < 8; i++) {
            d = race_parameters_find_driver(
                rp, raceevent_driver_number_from_racer_index(ev, i));
            if (d != NULL && d->EliminatedRank == 0)
                d->StartingPosition = (int8_t)ev->aResults[i].nPosition;
        }
        return 1;
    }
    if (ev->nType == EVENT_TOURNAMENT) {
        if (raceevent_get_race_index(ev) == 0)
            return 0;
        ts = rd(raceevent_get_tournament_state(ev));
        rp->PlayerStartPosition[0] = (int8_t)tournament_state_user_rank(ts);
        for (i = 0; i < 8; i++) {
            d = race_parameters_find_driver(
                rp, raceevent_driver_number_from_racer_index(ev, i));
            if (d != NULL && d->EliminatedRank == 0)
                d->StartingPosition =
                    (int8_t)tournament_state_racer_rank(ts, i);
        }
        return 1;
    }
    return 0;
}

int32_t raceevent_is_there_another_race(const RaceEvent *ev)
{
    int32_t i, n = 0;

    if (ev->nType == EVENT_RACE_KNOCKOUT) {
        for (i = 0; i < Fred.NumPlayerCars; i++) {
            if (raceevent_driver_in_the_race(ev, i))
                n++;
        }
        if ((uint32_t)raceevent_driver_number_from_racer_index(
                ev, raceevent_get_last_place(ev)) <= 1u)
            n--;
        if (n <= 0)
            return 0;
        return TheRaceParameters.NumPlayerCars + TheRaceParameters.NumAICars
               >= 3;
    }
    if (ev->nType == EVENT_TOURNAMENT)
        return raceevent_get_race_index(ev) + 1
               <= raceevent_get_race_count(ev);
    return 0;
}

int32_t raceevent_get_status_of(const RaceEvent *ev, const uint8_t *state)
{
    const uint8_t *s = rd(state);

    switch (group(ev)) {
    case GROUP_RANK:
        return rank_state_get_status(s, &ev->Objective);
    case GROUP_TIME:
        return time_state_get_status(s, &ev->Objective);
    case GROUP_KO:
        return ko_state_get_status(s, &ev->Objective);
    case GROUP_TOURNAMENT:
        return tournament_state_get_status(s, &ev->Objective, ev->nTracks,
                                           ev->nOpponents);
    default:
        return EVENT_UNTRIED;
    }
}

int32_t raceevent_get_status_goal(const RaceEvent *ev,
                                  const EventGoal *goal)
{
    const uint8_t *s = rd(ev->pState);

    switch (group(ev)) {
    case GROUP_RANK:
        return rank_state_get_status(s, goal);
    case GROUP_TIME:
        return time_state_get_status(s, goal);
    case GROUP_KO:
        return ko_state_get_status(s, goal);
    case GROUP_TOURNAMENT:
        return tournament_state_get_status(s, goal, ev->nTracks,
                                           ev->nOpponents);
    default:
        return EVENT_UNTRIED;
    }
}

int32_t raceevent_get_status(const RaceEvent *ev)
{
    return raceevent_get_status_of(ev, ev->pState);
}

int32_t raceevent_get_old_status(const RaceEvent *ev)
{
    return raceevent_get_status_of(ev, ev->aOldState);
}

void raceevent_reset_state(RaceEvent *ev)
{
    if (ev->pState == NULL)
        return;
    switch (group(ev)) {
    case GROUP_RANK:
        rank_state_reset(ev->pState);
        break;
    case GROUP_TIME:
        time_state_reset(ev->pState);
        break;
    case GROUP_KO:
        ko_state_reset(ev->pState);
        break;
    case GROUP_TOURNAMENT:
        tournament_state_reset(ev->pState);
        break;
    default:
        break;
    }
}

int32_t raceevent_reward_earned(const RaceEvent *ev, int32_t i,
                                const uint8_t *state)
{
    const EventReward *r;
    const uint8_t *s = state != NULL ? state : ev->pState;

    if ((r = reward(ev, i)) == NULL)
        return 0;
    if (raceevent_get_status_of(ev, s) < EVENT_FAILED)
        return 0;
    s = rd(s);
    switch (group(ev)) {
    case GROUP_RANK:
        return !(r->nData < (int32_t)s[0]);
    case GROUP_TIME:
        return !(r->nData < rd32(s));
    case GROUP_KO:
        return !(r->nData < ko_state_get_rank(s, 0));
    case GROUP_TOURNAMENT:
        return !((uint32_t)r->nData
                 < (uint32_t)tournament_state_user_rank(s));
    default:
        return 0;
    }
}

int32_t raceevent_any_reward_earned(const RaceEvent *ev)
{
    int32_t i;

    for (i = 0; i < ev->nRewards; i++) {
        if (raceevent_reward_earned(ev, i, NULL))
            return 1;
    }
    return 0;
}

int32_t raceevent_user_won(const RaceEvent *ev)
{
    const uint8_t *s;
    int32_t i, t;

    if (raceevent_get_status_of(ev, ev->pState) < EVENT_FAILED)
        return 0;
    s = rd(ev->pState);
    switch (group(ev)) {
    case GROUP_RANK:
        return s[0] == 1;
    case GROUP_TIME:
        // Retail reads every reward under nRewards; the port stops at the
        // array's end.
        t = rd32(s);
        for (i = 0; i < ev->nRewards && i < 8; i++) {
            if (ev->aRewards[i].nData < t)
                return 0;
        }
        return 1;
    case GROUP_KO:
        return ko_state_get_rank(s, 0) == 1;
    case GROUP_TOURNAMENT:
        return tournament_state_user_rank(s) == 1;
    default:
        return 0;
    }
}
