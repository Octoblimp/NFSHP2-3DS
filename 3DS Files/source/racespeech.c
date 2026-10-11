// racespeech -- the race's own speech. See racespeech.h.

#include "racespeech.h"

#include "bmath.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "fredrace.h"
#include "highscore.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racesplit.h"
#include "spch.h"
#include "speechconv.h"

int32_t (*gRaceEventUserWonFn)(void);

// RaceEvent::GetStatus's 4: the player placed in the event (endgame.c
// tests it too).
#define RACE_EVENT_PLACED 4

// endRaceTypeA, a car's finishing place from 1: one player's (0x0031ba50),
// player one's (0x0031ba10) and player two's (0x0031ba30).
static const uint32_t kFinishSingle[8] = {
    0x000001, 0x000008, 0x000040, 0x000200,
    0x001000, 0x008000, 0x040000, 0x200000,
};
static const uint32_t kFinishOne[8] = {
    0x000002, 0x000010, 0x000080, 0x000400,
    0x002000, 0x010000, 0x080000, 0x400000,
};
static const uint32_t kFinishTwo[8] = {
    0x000004, 0x000020, 0x000100, 0x000800,
    0x004000, 0x020000, 0x100000, 0x800000,
};

// 0x0031ba70, duringRaceTypeD: one player's place from 2 to 7.
static const uint32_t kLapPlace[6] = {
    0x02, 0x04, 0x08, 0x10, 0x20, 0x40,
};

// 0x0031ba88, duringRaceTypeA: start lap 2 to 20 after lap 1 to 19, and
// nothing after lap 20.
static const uint32_t kLapStart[20] = {
    0x00002, 0x00004, 0x00008, 0x00010, 0x00020,
    0x00040, 0x00080, 0x00100, 0x00200, 0x00400,
    0x00800, 0x01000, 0x02000, 0x04000, 0x08000,
    0x10000, 0x20000, 0x40000, 0x80000, 0,
};

// 0x0031bad8: the lead over the other player, in laps, that each of
// duringRaceTypeC's lines needs, the biggest first.
static const float kGapLimit[9] = {
    0.5f, 0.3f, 0.2f, 0.1f, 0.05f, 0.01f, -0.1f, -0.2f, -99999.0f,
};

// duringRaceTypeC by kGapLimit's line: said of either player (0x0031bb00),
// of player one (0x0031bb28) and of player two (0x0031bb50).
static const uint32_t kGapEither[9] = {
    0x0000001, 0x0000040, 0x0000008, 0x0008000, 0x0000200,
    0x0001000, 0x0040000, 0x0080000, 0x0400000,
};
static const uint32_t kGapOne[9] = {
    0x0000002, 0x0000080, 0x0000010, 0x0010000, 0x0000400,
    0x0002000, 0x0040000, 0x0100000, 0x0800000,
};
static const uint32_t kGapTwo[9] = {
    0x0000004, 0x0000020, 0x0000100, 0x0000800, 0x0004000,
    0x0020000, 0x0040000, 0x0200000, 0x1000000,
};

// duringRaceTypeB, a player's place from 1: of either (0x0031bb78), of
// player one (0x0031bb98) and of player two (0x0031bbb8).
static const uint32_t kPlaceEither[8] = {
    0x000001, 0x000008, 0x000040, 0x000200,
    0x001000, 0x008000, 0x040000, 0x200000,
};
static const uint32_t kPlaceOne[8] = {
    0x000002, 0x000010, 0x000080, 0x000400,
    0x002000, 0x010000, 0x080000, 0x400000,
};
static const uint32_t kPlaceTwo[8] = {
    0x000004, 0x000020, 0x000100, 0x000800,
    0x004000, 0x020000, 0x100000, 0x800000,
};

// 0x0031bc18, endRaceTypeA: a tournament place from 0. The eight words
// after it are 0, as the port answers past it.
static const uint32_t kTournamentPlace[8] = {
    0x000001, 0x000008, 0x000040, 0x000200,
    0x001000, 0x008000, 0x040000, 0x200000,
};

// Entry `i` of an `n`-entry table. Retail indexes each unchecked, by a
// place or a lap the race keeps in range; the port answers 0 outside.
static uint32_t at(const uint32_t *t, int32_t n, int32_t i)
{
    return (uint32_t)i < (uint32_t)n ? t[i] : 0;
}

// FlipCoinNoReplay: bRandom of 2 from the default seed, true on 0.
static int32_t flip_coin(void)
{
    return bRandomI(2, &bDefaultSeed) == 0;
}

// SingleP1OrP2's two: `single` unless the race has two players, then
// `one` for player one's car and `two` for any other.
static uint32_t single_p1_or_p2(const struct Car *car, uint32_t single,
                                uint32_t one, uint32_t two)
{
    if (TheRaceParameters.NumPlayerCars != 2)
        return single;
    return car == PlayerPlayersByNumber[0]->MyCar ? one : two;
}

static const uint32_t *single_p1_or_p2_table(const struct Car *car,
                                             const uint32_t *single,
                                             const uint32_t *one,
                                             const uint32_t *two)
{
    if (TheRaceParameters.NumPlayerCars != 2)
        return single;
    return car == PlayerPlayersByNumber[0]->MyCar ? one : two;
}

// PlayerSingleP1OrP2: the same by the player's number.
static uint32_t player_single_p1_or_p2(int32_t player, uint32_t single,
                                       uint32_t one, uint32_t two)
{
    if (TheRaceParameters.NumPlayerCars != 2)
        return single;
    return player == 0 ? one : two;
}

// The replays and the replay demo: the coordinator's states 4, 7 and 5,
// or IsReplayDemoMode. No coordinator is none.
static int32_t replaying(void)
{
    const RaceCoordinator *rc = pRaceCoordinator;
    RCState s;

    if (rc == NULL)
        return 0;
    s = rc->CurrentRCState;
    if (s == RCSTATE_INSTANT_REPLAY || s == RCSTATE_POSTRACE
        || s == RCSTATE_AUTO_REPLAY)
        return 1;
    return racecoordinator_is_replay_demo_mode(rc) != 0;
}

static int32_t race_event_status(void)
{
    return gRaceEventGetStatusFn != NULL ? gRaceEventGetStatusFn() : 0;
}

// WeDontWantToSayAnything: not a player's car, no players, fewer than two
// cars, a replay, a time trial, the AI or replay demo, or no race type.
// Retail reads the coordinator's state unchecked for the demos; the port
// takes no coordinator as neither.
static int32_t we_dont_want_to_say_anything(const struct Car *car)
{
    const RaceCoordinator *rc;

    if (car->pPlayer == NULL || TheRaceParameters.NumPlayerCars == 0
        || pCurrentRace->NumRacingCars < 2)
        return 1;
    if (replaying())
        return 1;
    if (TheRaceParameters.RaceType == RACE_TYPE_TIME_TRIAL)
        return 1;
    rc = pRaceCoordinator;
    if (rc != NULL
        && (uint32_t)(rc->CurrentRCState - RCSTATE_AI_DEMO_MODE) < 2u)
        return 1;
    return TheRaceParameters.RaceType == RACE_TYPE_NONE;
}

// BustedByCops(TransientStatsElement*): the row finished arrested.
static int32_t row_busted_by_cops(const TransientStatsElement *row)
{
    return row->FinishReason == 2;
}

// BustedByCops(Car*): the cops' pullover of the car is an arrest.
static int32_t busted_by_cops(const struct Car *car)
{
    return pCopManager != NULL
           && pCopManager->CarPullovers[car->CarIndex].bArrest != 0;
}

// SpecialLastPlaceSpeech: of two cars, lost; of more, placed last on a
// coin's toss. 1 if said.
static int32_t special_last_place_speech(const struct Car *car)
{
    uint32_t b;

    if (pCurrentRace->NumRacingCars == 2) {
        b = single_p1_or_p2(car, 0x08, 0x10, 0x20);
    } else {
        if (flip_coin())
            return 0;
        b = single_p1_or_p2(car, 0x01, 0x02, 0x04);
    }
    spch_add_event_v(165, 2, 0, b);
    return 1;
}

void race_finished_speech(struct Car *car, int32_t reason)
{
    const uint32_t *t;
    int32_t pos;

    (void)reason;
    if (car->pPlayer->HasHeardRaceOverSpeech != 0)
        return;
    if (TheRaceParameters.BeACop == 0 && !we_dont_want_to_say_anything(car)) {
        if (busted_by_cops(car)) {
            spch_add_event_v(168, 1, 512);
        } else if ((uint32_t)(TheRaceParameters.RaceType
                              - RACE_TYPE_LAP_KNOCKOUT) >= 2u) {
            pos = car->pRacingCar->RacePosition;
            if (pos != pCurrentRace->NumRacingCars
                || !special_last_place_speech(car)) {
                t = single_p1_or_p2_table(car, kFinishSingle, kFinishOne,
                                          kFinishTwo);
                spch_add_event_v(165, 2, at(t, 8, pos - 1), 0);
            }
        }
    }
    car->pPlayer->HasHeardRaceOverSpeech = 1;
}

void race_event_speech(struct Player *p, TransientStatsElement *row)
{
    int32_t first, n, hp;
    int32_t a = 0, b = 0;
    int32_t word;

    if (p == NULL || row == NULL)
        return;
    if (race_event_status() != RACE_EVENT_PLACED) {
        spch_add_event_v(168, 1, 64);
        return;
    }
    if (gRaceEventUserWonFn == NULL || gRaceEventUserWonFn() == 0)
        return;
    first = p->New2696 == 0;
    if (first)
        p->New2696 = 1;
    n = TheRaceEvent.nNumber;
    hp = Fred.GameType == 9;
    if ((uint32_t)(n - 1) < 20u)
        a = hp ? speech_convert_hp_event_a(n)
               : speech_convert_championship_event_a(n);
    else
        b = hp ? speech_convert_hp_event_b(n)
               : speech_convert_championship_event_b(n);
    if (a == 0 && b == 0) {
        spch_add_event_v(168, 1, 1024);
        return;
    }
    word = TheRaceEvent.bIsLastOpen != 0;
    if (b == 2048)
        spch_add_event_v(216, 4, first, a, 2048, word);
    else
        spch_add_event_v(hp ? 216 : 217, 4, first, a, b, word);
}

// OnePlayerLapSpeech. The last lap; else, on a coin's toss or after lap
// 19, the place when the race has AI cars; else the lap.
void one_player_lap_speech(DuringRaceSpeech *d, struct Car *car,
                           int32_t laps)
{
    int32_t pos;

    if (laps == TheRaceParameters.NumLapsInRace - 1) {
        d->TypeD = 1024;
        return;
    }
    if ((flip_coin() || laps >= 20) && TheRaceParameters.NumAICars > 0) {
        pos = car->pRacingCar->RacePosition;
        if (pos == 1)
            d->TypeD = flip_coin() ? 1 : 512;
        else if (pos == 8)
            d->TypeD = flip_coin() ? 128 : 256;
        else
            d->TypeD = at(kLapPlace, 6, pos - 2);
        return;
    }
    d->TypeA = at(kLapStart, 20, laps - 1);
}

// TwoPlayerLapSpeech. With no AI cars, the car's lead over the other
// player's, in laps; with them, its place.
void two_player_lap_speech(DuringRaceSpeech *d, struct Car *car,
                           int32_t laps)
{
    struct Car *one = PlayerPlayersByNumber[0]->MyCar;
    struct Car *two = PlayerPlayersByNumber[1]->MyCar;
    int32_t is_one = car == one;
    const uint32_t *t;
    float gap;
    int32_t i;

    (void)laps;
    if (TheRaceParameters.NumAICars == 0) {
        gap = one->pRacingCar->CurrentLapNumberExact
              - two->pRacingCar->CurrentLapNumberExact;
        if (!is_one)
            gap = -gap;
        t = flip_coin() ? kGapEither : is_one ? kGapOne : kGapTwo;
        for (i = 0; i < 9; i++)
            if (kGapLimit[i] <= gap) {
                d->TypeC = t[i];
                return;
            }
        return;
    }
    t = flip_coin() ? kPlaceEither : is_one ? kPlaceOne : kPlaceTwo;
    d->TypeB = at(t, 8, car->pRacingCar->RacePosition - 1);
}

// LapKnockoutSpeech: nothing.
static int32_t lap_knockout_speech(struct Car *car, int32_t laps)
{
    (void)car;
    (void)laps;
    return 0;
}

void maybe_do_knockout_race_over_speech(struct Player *p, int32_t advances)
{
    if (p == NULL || p->HasHeardRaceOverSpeech != 0)
        return;
    if (TheRaceParameters.RaceType == RACE_TYPE_LAP_KNOCKOUT
        || pCurrentRace->NumRacingCars < 3)
        spch_add_event_v(169, 2, advances ? 0 : 1, 0);
    else
        spch_add_event_v(169, 2, 1, advances ? 1 : 0);
    p->HasHeardRaceOverSpeech = 1;
}

// LapRecordSpeech: the lap just run is the race's best and beats the
// track's best lap for the car's class, a record that is set: neither
// the empty time nor 0 (retail's delay slot zeroes the answer before it
// tests for 0). 1 if said.
static int32_t lap_record_speech(struct Car *car)
{
    int32_t t = (int32_t)racingcar_get_last_lap_time(car->pRacingCar)
                    ->PackedTime;
    const FredHighScore *best = fred_get_best_lap_times_table(
        &Fred, TheRaceParameters.TrackNumber, car->pCarTypeInfo->CarClass,
        TheRaceParameters.TrackDirection);
    int32_t top;

    if (t != (int32_t)pCurrentRace->BestLapTime.PackedTime)
        return 0;
    top = (int32_t)best->Time.PackedTime;
    if (t >= top || top == 0 || top == HIGH_SCORE_NO_TIME)
        return 0;
    spch_add_event_v(164, 0);
    return 1;
}

void lap_finished_speech(struct Car *car, int32_t laps)
{
    DuringRaceSpeech d = { 0, 0, 0, 0 };

    if (we_dont_want_to_say_anything(car) || lap_record_speech(car))
        return;
    if (TheRaceParameters.RaceType == RACE_TYPE_LAP_KNOCKOUT
        && lap_knockout_speech(car, laps))
        return;
    if (TheRaceParameters.NumPlayerCars == 2)
        two_player_lap_speech(&d, car, laps);
    else
        one_player_lap_speech(&d, car, laps);
    spch_add_event_v(160, 1, d.TypeA);
}

// GetTopTimeFlag: postGameType's top time.
static uint32_t get_top_time_flag(int32_t player)
{
    return player_single_p1_or_p2(player, 64, 128, 256);
}

// Not for a busted car, nor an event tree's race not placed in.
static int32_t record_speech_wanted(const TransientStatsElement *row)
{
    if (row_busted_by_cops(row))
        return 0;
    return TheRaceParameters.EventTreeRace == 0
           || race_event_status() == RACE_EVENT_PLACED;
}

void post_game_lap_record(int32_t player, int32_t place,
                          TransientStatsElement *row)
{
    uint32_t a;

    if (!record_speech_wanted(row))
        return;
    if (place != 0)
        a = get_top_time_flag(player);
    else
        a = player_single_p1_or_p2(player, 512, 1024, 2048);
    spch_add_event_v(166, 1, a);
}

void post_game_time_record(int32_t player, int32_t place,
                           TransientStatsElement *row)
{
    uint32_t a;

    if (!record_speech_wanted(row))
        return;
    if (place != 0)
        a = get_top_time_flag(player);
    else if (flip_coin())
        a = player_single_p1_or_p2(player, 1, 2, 4);
    else
        a = player_single_p1_or_p2(player, 8, 16, 32);
    spch_add_event_v(166, 1, a);
}

void tournament_race_speech(int32_t b, int32_t n)
{
    if (b)
        spch_add_event_v(165, 2, at(kTournamentPlace, 8, n), 0);
    else if (n == 0)
        spch_add_event_v(167, 1, 16384);
}

void race_event_reward_speech(struct Player *p, int32_t won,
                              const uint8_t *reward)
{
    (void)p;
    if (!won || reward == NULL)
        return;
    if (reward[0] == 0)
        reward_car_speech(reward[1]);
    else
        reward_track_speech(reward[1], reward[2]);
}

int32_t reward_car_speech(int32_t carType)
{
    const CarTypeInfo *cti = cartypeinfo_get(carType);
    int32_t v = speech_convert_reward_car_type(carType);
    uint32_t ev;

    if (cti->UsageType == CAR_USAGE_TYPE_COP) {
        ev = 150;
    } else if (cti->HighPerformance != 0) {
        if (v == 128) {
            spch_add_event_v(204, 1, 1);
            return 1;
        }
        ev = 149;
    } else {
        ev = 147;
    }
    if (v == 0)
        return 0;
    spch_add_event_v(ev, 1, v);
    return 1;
}

int32_t reward_track_speech(int32_t track, int32_t direction)
{
    int32_t v = speech_convert_unlock_track(track);

    if (v == 0)
        return 0;
    spch_add_event_v(151, 2, v, direction == 1 ? 2 : 1);
    return 1;
}

void points_screen_speech(int32_t bonus)
{
    if (bonus)
        spch_add_event_v(210, 0);
}

void pullover_speech(void)
{
    if (!replaying())
        spch_add_event_v(206, 0);
}

void be_a_cop_arrest_speech(int32_t players, int32_t missed, int32_t winner,
                            int32_t arrests)
{
    int32_t v;

    if (replaying())
        return;
    if (players == 2) {
        if (missed)
            v = 512;
        else
            v = winner == 2 ? 0x8000 : 0x20000;
    } else if (!missed) {
        v = 1024;
    } else {
        switch (arrests) {
        case 0:  v = 2048; break;
        case 1:  v = 4096; break;
        case 2:  v = 8192; break;
        default: v = 512;  break;
        }
    }
    spch_add_event_v(213, 1, v);
}

void play_busted_speech(void)
{
    spch_add_event_v(214, 1, 1);
}
