// highscore -- the challenge records; highscore.h has the map.

#include "highscore.h"

#include <stddef.h>
#include <string.h>

#include "car.h"
#include "cartypeinfo.h"
#include "fredrace.h"
#include "player.h"
#include "racerun.h"
#include "racesplit.h"

// ------------------------------------------------------------- the names

const char *fred_lookup_player_name_from_table(FrontendDatabase *f,
                                               int32_t i)
{
    if (i < 0 || i >= HIGH_SCORE_NUM_NAMES)
        return NULL;
    return (const char *)&f->HighScoreNameTable[HIGH_SCORE_NAME_SIZE * i];
}

int32_t fred_insert_player_name(FrontendDatabase *f, const char *name)
{
    uint8_t *slot = f->HighScoreNameTable;
    int32_t i;

    for (i = 0; i < HIGH_SCORE_NUM_NAMES; i++, slot += HIGH_SCORE_NAME_SIZE) {
        if (slot[0] == 0) {
            // bMemSet, then bMemCpy of 11 bytes whatever the name's
            // length; the player's name is 12 bytes, so they are its.
            memset(slot, 0, HIGH_SCORE_NAME_SIZE);
            memcpy(slot, name, HIGH_SCORE_NAME_SIZE - 1);
            return i;
        }
        if (strcmp(name, (const char *)slot) == 0)
            return i;
    }
    return -1;
}

// ------------------------------------------------------------- the tables

static int32_t total_index(int32_t track, int32_t carClass, int32_t direction,
                           int32_t laps)
{
    int32_t i = high_score_table_get_total_times_index(track, carClass,
                                                       direction, laps);

    return i >= 0 && i <= FRED_NUM_TOTAL_TIMES - HIGH_SCORE_RECORDS ? i : -1;
}

static int32_t lap_index(int32_t track, int32_t carClass, int32_t direction)
{
    int32_t i = high_score_table_get_lap_times_index(track, carClass,
                                                     direction);

    return i >= 0 && i <= FRED_NUM_LAP_TIMES - HIGH_SCORE_RECORDS ? i : -1;
}

// Retail adds the index unchecked; a car class outside 0 to 4 would land
// outside the table. The port answers NULL there.
FredHighScore *fred_get_best_total_times_table(FrontendDatabase *f,
                                               int32_t track,
                                               int32_t carClass,
                                               int32_t direction,
                                               int32_t laps)
{
    int32_t i = total_index(track, carClass, direction, laps);

    return i < 0 ? NULL : &f->ChallengeHighScores.TotalTimesTable[i];
}

FredHighScore *fred_get_best_lap_times_table(FrontendDatabase *f,
                                             int32_t track,
                                             int32_t carClass,
                                             int32_t direction)
{
    int32_t i = lap_index(track, carClass, direction);

    return i < 0 ? NULL : &f->ChallengeHighScores.LapTimesTable[i];
}

// ------------------------------------------------------------- the records

// Where `time` goes in the five records from `e`, -1 if it beats none.
// Both are read signed.
static int32_t find_place(const FredHighScore *e, Timer time)
{
    int32_t i;

    for (i = 0; i < HIGH_SCORE_RECORDS; i++)
        if ((int32_t)time.PackedTime < (int32_t)e[i].Time.PackedTime)
            return i;
    return -1;
}

// Records k to 3 of the five from `e` down one, the last dropped. Retail
// copies them through five on the stack, whose times it zeroes first.
static void make_room(FredHighScore *e, int32_t k)
{
    memmove(&e[k + 1], &e[k], (size_t)(HIGH_SCORE_RECORDS - 1 - k) * sizeof *e);
}

// The car's type and its player's name, the name put in the global Fred.
// A name that does not fit is 0. Retail reads the car's player
// unchecked; the port leaves a car with none at 0.
static void fill_record(FredHighScore *e, const struct Car *car)
{
    int32_t n = 0;

    e->CarType = (int16_t)car->pCarTypeInfo->Type;
    if (car->pPlayer != NULL)
        n = fred_insert_player_name(&Fred,
                                    car->pPlayer->PlayerSettings.PlayerName);
    e->NameIndex = (int16_t)(n > -1 ? n : 0);
}

// Retail writes the player's words unchecked; TheRaceIsOver only asks for
// a player's car. The port skips them for a car with no player.
int32_t high_score_table_maybe_record_high_score(HighScoreTable *t, Race *r,
                                                 struct RacingCar *rc)
{
    struct Player *p = racingcar_get_player(rc);
    const RaceParameters *rp = &TheRaceParameters;
    const struct Car *car = rc->pCar;
    int32_t track = rp->TrackNumber;
    int32_t dir = rp->TrackDirection;
    int32_t cls = car->pCarTypeInfo->CarClass;
    int32_t placed = -1;
    int32_t i, k;
    Timer best;

    if (p != NULL) {
        p->BestTotalRecordData = NULL;
        p->BestLapRecordData = NULL;
    }
    i = total_index(track, cls, dir, rp->NumLapsInRace);
    if (rc->NumLapsCompleted == r->NumLapsInRace && i >= 0) {
        FredHighScore *e = &t->TotalTimesTable[i];

        k = find_place(e, rc->RaceTime);
        if (k >= 0) {
            placed = k;
            make_room(e, k);
            e[k].Time = rc->RaceTime;
            fill_record(&e[k], car);
            if (p != NULL)
                p->BestTotalRecordData = &e[k];
        }
    }
    i = lap_index(track, cls, dir);
    best = *racingcar_get_last_best_lap_time(rc);
    if (i >= 0) {
        FredHighScore *e = &t->LapTimesTable[i];

        k = find_place(e, best);
        if (k >= 0) {
            make_room(e, k);
            e[k].Time = best;
            fill_record(&e[k], car);
            if (p != NULL)
                p->BestLapRecordData = &e[k];
        }
    }
    return placed & 0xff;
}
