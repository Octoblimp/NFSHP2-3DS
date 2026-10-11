// fredrace -- FrontendDatabase's race start. fredrace.h has the overview
// and docs/formats/race-start.md the decode.

#include "fredrace.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "cartypeinfo.h"
#include "characterinfo.h"
#include "configitems.h"
#include "difficultyinfo.h"
#include "eefpu.h"
#include "playersettings.h"
#include "raceparams.h"
#include "track.h"

void (*gSetupFakeRaceEventForChallengeKnockoutFn)(FrontendDatabase *f);
int32_t (*gRaceEventGetStatusFn)(void);
int32_t (*gRaceEventIsThereAnotherRaceFn)(void);
void (*gRaceEventResetStateFn)(void);
int32_t (*gRaceEventGetRaceIndexFn)(void);
void (*gEventTrackSetRaceFn)(int32_t index, RaceParameters *rp);
int32_t (*gRaceEventKoStartPositionFn)(int32_t player);
int32_t (*gRaceEventTournamentUserRankFn)(void);
int32_t (*gFredEventWordFn)(FrontendDatabase *f);
int32_t (*gRaceEventDriverEliminatedFn)(int32_t number);
int32_t (*gRaceEventEliminatedRankFn)(int32_t number);
void (*gRaceEventStartingPositionsFn)(void);
const uint8_t *(*gFredEventOpponentFn)(FrontendDatabase *f, int32_t i);
void (*gFredMaybeSetSelectedCarForMultiTrackEventFn)(FrontendDatabase *f);
void (*gDemoModeReplayStartRaceFn)(void);
int32_t (*gEventRewardCarsUnlockedFn)(void);
int32_t (*gFredGameFlowStateFn)(void);
void (*gFredChangeGameFlowFn)(int32_t state);

// GameFlowState's two StartRace asks for, as the image writes them.
#define FLOW_UNLOADING_FRONTEND   2
#define FLOW_IN_FRONTEND          3
#define FLOW_LOADING_TRACK_COMMON 4

// --------------------------------------------------------- the game types

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
}

int32_t fred_is_challenge_game(const FrontendDatabase *f)
{
    return f->GameType >= 3 && f->GameType < 8;
}

int32_t fred_is_event_game(const FrontendDatabase *f)
{
    return f->GameType >= 8 && f->GameType < 10;
}

RideInfo *fpi_get_selected_ride_info(FrontendPlayerInfo *p, int32_t gameType)
{
    return &p->RideInfoByGameMode[gameType];
}

// The image reads a CarTypeInfo for any type, -1 too: a ride no draw
// filled reads 1376 bytes before the array. The port answers 5 for a type
// outside the 64, which no comparison here takes as lower.
static int32_t valid_type(int32_t type)
{
    return type >= 0 && type < 64;
}

static int32_t car_class(int32_t type)
{
    return valid_type(type) ? cartypeinfo_get(type)->CarClass : 5;
}

int32_t fpi_get_selected_car_class(FrontendPlayerInfo *p)
{
    return car_class(fpi_get_selected_ride_info(p, Fred.GameType)->Type);
}

// --------------------------------------------------------- the drivers

void ride_info_init(RideInfo *r, int32_t type, int32_t skin, int32_t dash,
                    int32_t vertexDamage)
{
    r->CanBeVertexDamaged = (int8_t)vertexDamage;
    r->Type = type;
    r->SkinNumber = (int8_t)skin;
    r->HasDash = (int8_t)dash;
    r->InstanceIndex = 0;
}

void driver_info_init(DriverInfo *d, int32_t unique, DriverType type,
                      const RideInfo *ride, int32_t character, int32_t skill,
                      int32_t startPos)
{
    // The ride's own constructor runs first (-1 and four 0 bytes), and the
    // copy then covers it.
    d->CurrentRideInfo.Type = -1;
    d->CurrentRideInfo.CanBeVertexDamaged = 0;
    d->CurrentRideInfo.InstanceIndex = 0;
    d->CurrentRideInfo.SkinNumber = 0;
    d->CurrentRideInfo.HasDash = 0;
    d->UniqueDriverNumber = (int8_t)unique;
    d->StartingPosition = (int8_t)startPos;
    d->TheDriverType = type;
    d->EliminatedRank = 0;
    d->CurrentRideInfo = *ride;
    d->CharacterNumber = (int8_t)character;
    d->pCharacterInfo = get_character_info(character);
    d->SkillLevel = (int8_t)skill;
}

int32_t car_type_info_get_random_skin(const CarTypeInfo *ct)
{
    if (ct->UsageType == CAR_USAGE_TYPE_COP)
        return cartypeinfo_get_skin_number(ct, 0);
    if (ct->NumAvailableSkins == 0)
        return 0;
    return ct->AvailableSkins[bRandomI(ct->NumAvailableSkins, &bDefaultSeed)];
}

// CarTypeInfoIterator (0x00189130 and its Next) as GenerateRandomRideInfo
// inlines it: from `*i` on, the next car of the usage with geometry, of the
// class unless that is -1, and with a skin; NULL past the 64th.
static const CarTypeInfo *next_car(int32_t *i, int32_t usage,
                                   int32_t carClass)
{
    while (*i < 64) {
        const CarTypeInfo *ct = cartypeinfo_get((*i)++);

        if (ct->UsageType != usage || ct->GeometryFilename[0] == 0)
            continue;
        if (carClass != -1 && ct->CarClass != carClass)
            continue;
        if (cartypeinfo_get_num_skins(ct) > 0)
            return ct;
    }
    return NULL;
}

// LocationProb holds five floats. A track below 10 has location -1, and
// the image reads the word before them, which the port's record holds too.
static float location_prob(const CarTypeInfo *ct, int32_t loc)
{
    float p;

    memcpy(&p, (const uint8_t *)ct + offsetof(CarTypeInfo, LocationProb)
               + 4 * loc, 4);
    return p;
}

int32_t generate_random_ride_info(RideInfo *r, int32_t usage,
                                  int32_t carClass)
{
    const CarTypeInfo *ct;
    int32_t loc = race_parameters_get_location_index(&TheRaceParameters);
    int32_t i = 0;
    float total = 0.0f;
    float pick;

    while ((ct = next_car(&i, usage, carClass)) != NULL)
        total += location_prob(ct, loc);
    if (fabsf(total) <= 0.001f)
        return 0;

    pick = bRandomF(total, &bDefaultSeed);
    i = 0;
    while ((ct = next_car(&i, usage, carClass)) != NULL) {
        pick -= location_prob(ct, loc);
        if (pick <= 0.0f) {
            r->SkinNumber = (int8_t)car_type_info_get_random_skin(ct);
            r->Type = ct->Type;
            r->CanBeVertexDamaged = 0;
            r->InstanceIndex = 0;
            r->HasDash = 0;
            return 1;
        }
    }
    return 0;
}

// bStrICmp (0x002536a8) on the two names.
static int32_t to_upper(int32_t c)
{
    int32_t v = (uint8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

static int32_t str_icmp(const char *a, const char *b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca == 0 || cb == 0 || ca != cb)
            return ca - cb;
    }
}

int32_t pick_character_number_that_isnt_racing(int32_t *list, int32_t n,
                                               int32_t gender)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        const CharacterInfo *ci;
        int32_t male;

        if (list[i] == -1)
            continue;
        if (gender != -1) {
            // The image reads the body's name off whatever GetCharacterInfo
            // answers; the port's NULL, past the loaded characters, fits
            // no gender.
            ci = get_character_info(list[i]);
            if (ci == NULL)
                continue;
            male = str_icmp(ci->BodyTypeName, "MALE") == 0;
            if (male ? gender != 0 : gender != 1)
                continue;
        }
        {
            int32_t c = list[i];

            list[i] = -1;
            return c;
        }
    }
    return 0;
}

int32_t pick_cop_character_number(int32_t track)
{
    const TrackInfo *t = track_get_info(TheRaceParameters.TrackNumber);
    const CharacterInfo *ci;
    uint32_t hash;

    (void)track;
    hash = t != NULL ? t->CopCharacterNameHash : 0;
    if (hash == 0)
        hash = bchunk_hash("Cop");
    ci = get_character_info_from_name_hash(hash);
    return ci != NULL ? ci->CharacterNumber : -1;
}

int32_t are_there_any_cars_of_type(int32_t type)
{
    int32_t i;

    for (i = 0; i < TheRaceParameters.NumDriverInfo; i++) {
        const DriverInfo *d = race_parameters_get_driver_info(i);

        if (d->EliminatedRank == 0 && d->CurrentRideInfo.Type == type)
            return 1;
    }
    return 0;
}

static int32_t paint_type(int32_t type, int32_t skin)
{
    const SkinInfo *s = cartypeinfo_get_skin_info(type, skin, 1);

    // The table's first entry stands in for a missing skin; only an empty
    // table answers NULL here, which the image would read through.
    return s != NULL ? s->PaintType : 0;
}

int32_t are_there_any_cars_of_colour(int32_t type, int32_t skin)
{
    int32_t paint = paint_type(type, skin);
    int32_t i;

    for (i = 0; i < TheRaceParameters.NumDriverInfo; i++) {
        const DriverInfo *d = race_parameters_get_driver_info(i);

        if (d->EliminatedRank != 0)
            continue;
        if (paint_type(d->CurrentRideInfo.Type,
                       d->CurrentRideInfo.SkinNumber) == paint)
            return 1;
    }
    return 0;
}

int32_t pick_unused_skin(int32_t type)
{
    const CarTypeInfo *ct = cartypeinfo_get(type);
    int32_t skin = 1;
    int32_t tries;

    for (tries = 0; tries < 100; tries++) {
        skin = car_type_info_get_random_skin(ct);
        if (!are_there_any_cars_of_colour(type, skin))
            break;
    }
    return skin;
}

// --------------------------------------------------------- the records

int32_t high_score_table_get_unique_track_index(int32_t track)
{
    const TrackInfo *t = track_get_info(track);

    if (t == NULL || t->IsValid == 0)
        return 0;
    return t->HighScoreIndex;
}

int32_t high_score_table_get_unique_lap_index(int32_t laps)
{
    static const int8_t lapCounts[9] = { 1, 2, 3, 4, 5, 6, 7, 8, 10 };
    int32_t i;

    for (i = 0; i < 9; i++)
        if (laps == lapCounts[i])
            return i;
    return 0;
}

int32_t high_score_table_get_total_times_index(int32_t track,
                                               int32_t carClass,
                                               int32_t direction,
                                               int32_t laps)
{
    return high_score_table_get_unique_track_index(track) * 450
         + high_score_table_get_unique_lap_index(laps) * 5
         + (direction != 0) * 45 + carClass * 90;
}

int32_t high_score_table_get_lap_times_index(int32_t track, int32_t carClass,
                                             int32_t direction)
{
    return high_score_table_get_unique_track_index(track) * 50
         + carClass * 10 + (direction != 0) * 5;
}

void fred_set_record_times_to_beat(FrontendDatabase *f, int32_t player)
{
    RaceParameters *rp = &TheRaceParameters;
    cPlayerSettings *ps = &rp->PlayerSettings[player];
    int32_t track = rp->TrackNumber;
    // The player's ride is `f`'s, for the global Fred's game type.
    const RideInfo *ride =
        fpi_get_selected_ride_info(&f->FrontendPlayers[player], Fred.GameType);
    int32_t laps = rp->NumLapsInRace;
    int32_t dir = rp->TrackDirection;
    int32_t cls = car_class(ride->Type);

    if (laps != 0)
        ps->BestTotalTimeRecord = f->ChallengeHighScores.TotalTimesTable[
            high_score_table_get_total_times_index(track, cls, dir, laps)].Time;
    ps->BestLapTimeRecord = f->ChallengeHighScores.LapTimesTable[
        high_score_table_get_lap_times_index(track, cls, dir)].Time;
}

void fred_set_all_record_times_to_beat(FrontendDatabase *f)
{
    int32_t p;

    for (p = 0; p < TheRaceParameters.NumPlayerCars; p++)
        fred_set_record_times_to_beat(f, p);
}

// --------------------------------------------------------- the race start

static float pull_away(const DriverInfo *d)
{
    const CarTypeInfo *ct;
    float perf = 0.0f;
    int32_t k;

    if (!valid_type(d->CurrentRideInfo.Type))
        return 0.0f;
    ct = cartypeinfo_get(d->CurrentRideInfo.Type);
    for (k = 0; k < 9; k++)
        if (ct->Engine.TorqueCurveTable[k] > perf)
            perf = ct->Engine.TorqueCurveTable[k];
    perf = perf / ct->Body.Mass;
    perf = perf * ct->DriveTrain.GearRatios[2];
    perf = perf * ct->DriveTrain.FinalDrive[1];
    return perf / ct->Wheels[3].Radius;
}

void fred_calculate_starting_positions(FrontendDatabase *f)
{
    RaceParameters *rp = &TheRaceParameters;
    DriverInfo *list[RACE_PARAMETERS_MAX_DRIVERS];
    float perf[RACE_PARAMETERS_MAX_DRIVERS];
    int32_t n = 0;
    int32_t i, j;

    if (fred_use_the_race_event(f) && gRaceEventStartingPositionsFn != NULL)
        gRaceEventStartingPositionsFn();

    for (i = 0; i < rp->NumDriverInfo && n < RACE_PARAMETERS_MAX_DRIVERS;
         i++) {
        DriverInfo *d = race_parameters_get_driver_info(i);

        if (d->EliminatedRank != 0 || d->StartingPosition != 0)
            continue;
        if (d->TheDriverType >= DRIVER_TYPE_TRAFFIC_CAR
            || d->TheDriverType <= DRIVER_TYPE_NONE)
            continue;
        list[n++] = d;
    }
    for (i = 0; i < n; i++)
        perf[i] = pull_away(list[i]);

    // n passes of a bubble sort, the quickest first; equals keep order.
    for (i = 0; i < n; i++) {
        for (j = 0; j < n - 1; j++) {
            if (perf[j] < perf[j + 1]) {
                DriverInfo *t = list[j];
                float p = perf[j];

                list[j] = list[j + 1];
                perf[j] = perf[j + 1];
                list[j + 1] = t;
                perf[j + 1] = p;
            }
        }
    }

    for (i = 0; i < n; i++) {
        int32_t pos;

        for (pos = 1; pos < 9; pos++) {
            for (j = 0; j < rp->NumDriverInfo; j++)
                if (race_parameters_get_driver_info(j)->StartingPosition
                    == pos)
                    break;
            if (j == rp->NumDriverInfo)
                break;
        }
        list[i]->StartingPosition = (int8_t)pos;
    }
}

// A driver SetupCarsForRace has added: a knockout's eliminated driver
// takes its rank and leaves the count; the rest add one to it.
static void count_driver(FrontendDatabase *f, int32_t number, int32_t *count)
{
    if (fred_use_the_race_event(f) && gRaceEventDriverEliminatedFn != NULL
        && gRaceEventDriverEliminatedFn(number)) {
        int32_t rank = gRaceEventEliminatedRankFn != NULL
                     ? gRaceEventEliminatedRankFn(number) : 0;

        race_parameters_eliminate_driver(&TheRaceParameters, number, rank);
        return;
    }
    (*count)++;
}

static const uint8_t kNoOpponent[4];

// SetupCarsForRace's AI racer `i`, into `ride` and `*skill`.
static void choose_ai_ride(FrontendDatabase *f, int32_t i, int32_t minClass,
                           int32_t maxClass, int32_t *firstGen,
                           int32_t *secondGen, RideInfo *ride,
                           int32_t *skill)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t type, attempt;

    if (rp->OpponentSelect == 2) {
        const uint8_t *rec = gFredEventOpponentFn != NULL
                           ? gFredEventOpponentFn(f, i) : NULL;
        int32_t skin;

        if (rec == NULL)
            rec = kNoOpponent;
        skin = (int8_t)rec[1];
        if (skin < 0)
            skin = pick_unused_skin(rec[0]);
        ride->SkinNumber = (int8_t)skin;
        ride->Type = rec[0];
        ride->InstanceIndex = 0;
        ride->HasDash = 0;
        ride->CanBeVertexDamaged = 0;
        *skill = rec[2];
        return;
    }

    {
        float r = bRandomF(1.0f, &bDefaultSeed);
        const float *cdf = TheDifficultyInfo.AINonExplicitMode
            .SkillLevelDistribution[rp->nMaxCops < 1][rp->OpponentStrength];
        int32_t k;

        *skill = -1;
        for (k = 0; k < 10; k++) {
            if (r <= cdf[k]) {
                *skill = k;
                break;
            }
        }
        if (*skill == -1)
            *skill = 0;
    }

    type = ForceAllAICarsToBeThisType;
    if (type != -1 || rp->OpponentSelect == 1) {
        if (type == -1)
            type = fpi_get_selected_ride_info(&Fred.FrontendPlayers[0],
                                              f->GameType)->Type;
        ride->SkinNumber = (int8_t)pick_unused_skin(type);
        ride->Type = type;
        ride->InstanceIndex = 0;
        ride->HasDash = 0;
        ride->CanBeVertexDamaged = 0;
        return;
    }

    for (attempt = 0; attempt < 500; attempt++) {
        int32_t gens = 0;
        int32_t ok;

        do {
            int32_t cls;

            if (!*firstGen) {
                *firstGen = 1;
                cls = minClass;
            } else if (!*secondGen) {
                *secondGen = 1;
                cls = maxClass;
            } else {
                cls = bRandomI(maxClass - minClass + 1, &bDefaultSeed)
                    + minClass;
            }
            generate_random_ride_info(ride, CAR_USAGE_TYPE_RACING, cls);
            if (ride->Type == -1)
                generate_random_ride_info(ride, CAR_USAGE_TYPE_RACING, -1);
            gens++;
        } while (gens < 1001
                 && race_parameters_too_many_models(rp, ride));

        ok = 1;
        if (attempt < 100 && are_there_any_cars_of_type(ride->Type))
            ok = 0;
        if (attempt < 200
            && are_there_any_cars_of_colour(ride->Type, ride->SkinNumber))
            ok = 0;
        if (ok)
            break;
    }
}

void fred_setup_cars_for_race(FrontendDatabase *f)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t list[8];
    int32_t minClass, maxClass;
    int32_t firstGen = 0, secondGen = 0;
    int32_t numAI, numTraffic, numCops;
    int32_t count, i;
    DriverInfo d;
    RideInfo ride;

    race_parameters_restore_eliminated(rp);
    bSetRandomSeed((uint32_t)rp->New780, &bDefaultSeed);
    for (i = 7; i >= 0; i--)
        list[i] = i;

    if (rp->NumPlayerCars + rp->NumAICars + rp->nMaxCops >= 9) {
        rp->nMaxCops = 8 - (rp->NumPlayerCars + rp->NumAICars);
        if (rp->nMaxCops < 0)
            rp->nMaxCops = 0;
    }
    rp->NumDriverInfo = 0;

    if (rp->AIDemoMode == 0) {
        int32_t numPlayers = rp->NumPlayerCars;

        count = 0;
        for (i = 0; i < numPlayers; i++) {
            FrontendPlayerInfo *p = &Fred.FrontendPlayers[i];
            int32_t c = pick_character_number_that_isnt_racing(
                list, 8, p->mPlayerSettings.PreferredGender);
            RideInfo *sel;

            if (rp->BeACop != 0 && i == 0)
                c = pick_cop_character_number(rp->TrackNumber);
            sel = fpi_get_selected_ride_info(p, Fred.GameType);
            sel->CanBeVertexDamaged = 1;
            driver_info_init(&d, i, DRIVER_TYPE_PLAYER, sel, c, -2,
                             rp->PlayerStartPosition[i]);
            race_parameters_add_driver_info(rp, &d);
            count_driver(f, i, &count);
        }
        rp->NumPlayerCars = count;
    }

    if (rp->AIDemoMode != 0) {
        minClass = maxClass = bRandomI(5, &bDefaultSeed);
    } else if (rp->NumPlayerCars == 1) {
        minClass = maxClass = car_class(fpi_get_selected_ride_info(
            &Fred.FrontendPlayers[0], f->GameType)->Type);
    } else {
        int32_t c0 = car_class(fpi_get_selected_ride_info(
            &Fred.FrontendPlayers[0], f->GameType)->Type);
        int32_t c1 = car_class(fpi_get_selected_ride_info(
            &Fred.FrontendPlayers[1], f->GameType)->Type);

        minClass = c1 < c0 ? c1 : c0;
        maxClass = c1 < c0 ? c0 : c1;
    }

    numAI = rp->NumAICars;
    count = 0;
    for (i = 0; i < numAI; i++) {
        int32_t c = pick_character_number_that_isnt_racing(list, 8, -1);
        int32_t skill = -1;

        ride.Type = -1;
        ride.InstanceIndex = 0;
        ride.SkinNumber = 0;
        ride.HasDash = 0;
        ride.CanBeVertexDamaged = 0;
        choose_ai_ride(f, i, minClass, maxClass, &firstGen, &secondGen,
                       &ride, &skill);
        driver_info_init(&d, i + 100, DRIVER_TYPE_AI_RACER, &ride, c, skill,
                         0);
        race_parameters_add_driver_info(rp, &d);
        count_driver(f, i + 100, &count);
    }
    rp->NumAICars = count;

    numTraffic = fabsf(rp->TrafficDensity) <= 0.001f ? 0 : 6;
    for (i = 0; i < numTraffic; i++) {
        int32_t tries;

        ride.Type = -1;
        ride.InstanceIndex = 0;
        ride.SkinNumber = 0;
        ride.HasDash = 0;
        ride.CanBeVertexDamaged = 0;
        for (tries = 0; tries < 100; tries++) {
            generate_random_ride_info(&ride, CAR_USAGE_TYPE_TRAFFIC, -1);
            ride.SkinNumber = -1;
            if (!are_there_any_cars_of_type(ride.Type))
                break;
        }
        driver_info_init(&d, i + 50, DRIVER_TYPE_TRAFFIC_CAR, &ride, -1, -1,
                         0);
        race_parameters_add_driver_info(rp, &d);
    }

    // The cops drive the cop car nearest the slowest class racing (every
    // driver so far, traffic too, and no class above 5); the first wins a
    // tie, and with no cop car the type stays -1.
    {
        int32_t lowest = 5;

        for (i = 0; i < rp->NumDriverInfo; i++) {
            int32_t c = car_class(
                race_parameters_get_driver_info(i)->CurrentRideInfo.Type);

            if (c < lowest)
                lowest = c;
        }

        numCops = rp->nMaxCops;
        for (i = 0; i < numCops; i++) {
            int32_t ch = pick_cop_character_number(rp->TrackNumber);
            int32_t best = -1, bestClass = 0;
            int32_t t;

            for (t = 0; t < 64; t++) {
                const CarTypeInfo *ct = cartypeinfo_get(t);
                int32_t dBest, dThis;

                if (ct->UsageType != CAR_USAGE_TYPE_COP
                    || ct->GeometryFilename[0] == 0)
                    continue;
                if (best == -1) {
                    best = t;
                    bestClass = ct->CarClass;
                    continue;
                }
                dBest = lowest - bestClass;
                if (dBest < 0)
                    dBest = -dBest;
                dThis = lowest - ct->CarClass;
                if (dThis < 0)
                    dThis = -dThis;
                if (dThis < dBest) {
                    best = t;
                    bestClass = ct->CarClass;
                }
            }
            ride_info_init(&ride, best, 1, 0, 0);
            driver_info_init(&d, i + 10, DRIVER_TYPE_COP, &ride, ch, -1, 0);
            race_parameters_add_driver_info(rp, &d);
        }
    }

    fred_calculate_starting_positions(f);
}

void fred_start_race(FrontendDatabase *f)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t p;

    if (f->GameType == 4) {
        TheRaceEvent.nInitialPlayers = (int16_t)f->NumPlayerCars;
        if (gSetupFakeRaceEventForChallengeKnockoutFn != NULL)
            gSetupFakeRaceEventForChallengeKnockoutFn(f);
    }
    if (fred_use_the_race_event(f)) {
        int32_t status = gRaceEventGetStatusFn != NULL
                       ? gRaceEventGetStatusFn() : 0;

        if (status != 2 && gRaceEventResetStateFn != NULL)
            gRaceEventResetStateFn();
    } else {
        TheRaceEvent.nInitialPlayers = (int16_t)f->NumPlayerCars;
    }

    if (fred_use_the_race_event(f)) {
        int32_t index = gRaceEventGetRaceIndexFn != NULL
                      ? gRaceEventGetRaceIndexFn() : 0;
        int32_t tracks = TheRaceEvent.nTracks;

        // The image's divide traps on an event with no tracks.
        if (gEventTrackSetRaceFn != NULL && tracks != 0)
            gEventTrackSetRaceFn(index % tracks, rp);
        if (TheRaceEvent.nType == 3
            && (gRaceEventGetRaceIndexFn != NULL
                ? gRaceEventGetRaceIndexFn() : 0) != 0) {
            int32_t s0 = gRaceEventKoStartPositionFn != NULL
                       ? gRaceEventKoStartPositionFn(0) : 0;
            int32_t s1;

            rp->PlayerStartPosition[0] = (int8_t)s0;
            s1 = gRaceEventKoStartPositionFn != NULL
               ? gRaceEventKoStartPositionFn(1) : 0;
            rp->PlayerStartPosition[1] = (int8_t)s1;
        }
        if (TheRaceEvent.nType == 4
            && (gRaceEventGetStatusFn != NULL ? gRaceEventGetStatusFn() : 0)
               == 2)
            rp->PlayerStartPosition[0] = (int8_t)(
                gRaceEventTournamentUserRankFn != NULL
                ? gRaceEventTournamentUserRankFn() : 0);
    }

    TheRaceEvent.bIsLastOpen = 0;
    if (fred_use_the_race_event(f) && gFredEventWordFn != NULL)
        TheRaceEvent.bIsLastOpen = gFredEventWordFn(f);

    if (fred_is_challenge_game(f) || f->GameType == 2) {
        for (p = 0; p < rp->NumPlayerCars; p++) {
            int32_t cls = car_class(fpi_get_selected_ride_info(
                &Fred.FrontendPlayers[p], Fred.GameType)->Type);

            rp->BoostScale[p] = TheDifficultyInfo.AINonExplicitMode
                .BoostScale[rp->OpponentStrength][cls];
        }
    } else if (!fred_is_event_game(f) && f->GameType == 1) {
        rp->BoostScale[1] = 1.0f;
        rp->BoostScale[0] = 1.0f;
    }

    if (MaximumNumAICars < rp->NumAICars)
        rp->NumAICars = MaximumNumAICars;
    if (rp->NumAICars + rp->NumPlayerCars >= 9)
        rp->NumAICars = 8 - rp->NumPlayerCars;
    if (rp->Point2Point == 0) {
        const TrackInfo *t = track_get_info(rp->TrackNumber);

        if (t != NULL && t->Point2Point != 0)
            rp->Point2Point = 1;
    }

    fred_setup_cars_for_race(f);

    rp->GlobalDisplaySettings = f->DisplayOptionsData;
    rp->PlayerSettings[0] = Fred.FrontendPlayers[0].mPlayerSettings;
    rp->PlayerSettings[1] = Fred.FrontendPlayers[1].mPlayerSettings;

    if (fred_is_event_game(f)) {
        const DriverInfo *d = race_parameters_find_driver(rp, 0);

        if (d != NULL && d->CurrentRideInfo.HasDash != 0)
            rp->PlayerSettings[0].DriveCameraPOVIndex = 3;
    }

    fred_set_all_record_times_to_beat(f);
    // ChooseHudTextures (0x001ee388) is an empty function.
    if (gFredMaybeSetSelectedCarForMultiTrackEventFn != NULL)
        gFredMaybeSetSelectedCarForMultiTrackEventFn(f);
    if (gDemoModeReplayStartRaceFn != NULL)
        gDemoModeReplayStartRaceFn();

    rp->EventTreeRace = Fred.GameType == 8 || Fred.GameType == 9;
    rp->New784 = gEventRewardCarsUnlockedFn != NULL
               ? gEventRewardCarsUnlockedFn() : 0;

    if (gFredChangeGameFlowFn != NULL) {
        int32_t state = gFredGameFlowStateFn != NULL
                      ? gFredGameFlowStateFn() : 0;

        gFredChangeGameFlowFn(state == FLOW_IN_FRONTEND
                              ? FLOW_UNLOADING_FRONTEND
                              : FLOW_LOADING_TRACK_COMMON);
    }
    f->bRaceWasAborted = 0;
}

void fred_start_skip_fe_game(FrontendDatabase *f)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t track = TrackSelectedInConfigFile;
    int32_t diff = SkipFEDifficulty;

    if (track == -1)
        track = 12;
    f->NumPlayerCars = SkipFENumPlayerCars;
    rp->TrackNumber = track;
    rp->TrackTimeOfDay = 3;
    rp->TrafficDensity = SkipFETrafficDensity;
    rp->TrafficOncoming = SkipFETrafficOncoming;
    rp->RaceType = SkipFERaceType;
    rp->NumLapsInRace = SkipFENumLaps;
    rp->NumPlayerCars = SkipFENumPlayerCars;
    rp->NumAICars = SkipFENumAICars;
    rp->nMaxCops = SkipFEMaxCops;
    rp->bTickets = SkipFETickets;
    rp->bRoadBlocks = SkipFERoadBlocks;
    rp->bHelicopter = SkipFEHelicopter;
    rp->bSpikeStrips = SkipFESpikeStrips;
    rp->New624 = SkipFENew624;
    rp->TrackWeather = 0;
    rp->TrackDirection = 0;
    rp->EventTreeRace = 0;
    rp->BeACop = SkipFEBeACop;
    if (rp->BeACop != 0)
        rp->TimeTrialTime.PackedTime = (uint32_t)(int32_t)1200000.5f;

    rp->PlayerStartPosition[1] = (int8_t)((uint8_t)SkipFENumAICars + 2);
    rp->PlayerStartPosition[0] = (int8_t)((uint8_t)SkipFENumAICars + 1);
    rp->PlayerSettings[1].DriveCameraPOVIndex = (int8_t)PlayerSkipFEPOVIndex;
    rp->PlayerSettings[0].DriveCameraPOVIndex = (int8_t)PlayerSkipFEPOVIndex;
    rp->OpponentStrength = diff;
    rp->CopStrength = diff;
    rp->BoostScale[0] = TheDifficultyInfo.AINonExplicitMode
        .BoostScale[diff][car_class(DefaultPlayer1CarType)];
    rp->BoostScale[1] = TheDifficultyInfo.AINonExplicitMode
        .BoostScale[diff][car_class(DefaultPlayer2CarType)];

    // The image jumps into StartRace on the global Fred, not `f`.
    fred_start_race(&Fred);
}

// ---------------------------------------------------- the challenge setup

// bStrNCpy (0x002535a0): up to `n` bytes, the NUL among them; no NUL is
// added when `src` is longer.
static void b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

static const char *translate(int32_t id)
{
    const char *s = gFredTranslateFn != NULL ? gFredTranslateFn(id) : NULL;

    return s != NULL ? s : "NOT TRANSLATED PROPERLY";
}

// 0x002b4220, copied to the stack and read with the setting unchecked.
static const float kSetupTrafficDensity[4] = { 0.33f, 0.667f, 1.0f, 0.0f };

void fred_setup_race_parameters_after_race_setup(FrontendDatabase *f)
{
    RaceParameters *rp = &TheRaceParameters;
    int32_t players = f->NumPlayerCars;
    int32_t police = f->MainMenuOpts[1];
    int32_t strength = Fred.ChallengeScreenData[3];
    int32_t ai = 0, traffic = 0, boost = 1, select = 0, damage = 1;
    int32_t beACop = 0, tickets = 2, roadBlocks = 0, choppers = 0;
    int32_t resetTimer = 1, seconds = 0, most;
    const int32_t *d;

    switch (Fred.GameType) {
    case 3:                                     // single race
        d = f->SingleRaceSetupData;
        // [0] the opponents, [1] the same with the cops, for one player;
        // two players with the cops race alone. 1 is one AI and 2 the
        // full grid: 7 for one player and 2 for two, 3 and none with the
        // cops. Any other player count reads [0] and has no grid.
        {
            int32_t opponents = d[0];

            if (players == 1)
                opponents = police ? d[1] : d[0];
            else if (players == 2 && police)
                opponents = 0;
            if (opponents == 1)
                ai = 1;
            else if (opponents == 2) {
                if (police)
                    ai = players == 1 ? 3 : 0;
                else
                    ai = players == 1 ? 7 : players == 2 ? 2 : 0;
            }
        }
        traffic = police ? d[5] : d[4];
        damage = d[6];
        boost = d[3];
        select = d[2];
        break;
    case 4:                                     // race knockout
    case 5:                                     // lap knockout
        d = Fred.GameType == 4 ? f->RaceKnockoutSetupData
                               : f->LapKnockoutSetupData;
        // [0] is one player's field without the cops, taken as it is.
        if (police)
            ai = players == 1 ? 3 : players == 2 ? 2 : 0;
        else
            ai = players == 1 ? d[0] : 2;
        traffic = police ? d[4] : d[3];
        damage = Fred.GameType == 4 ? d[6] : d[5];
        boost = d[2];
        select = d[1];
        break;
    case 6:                                     // free run
        d = f->FreeRunSetupData;
        traffic = police ? d[1] : d[0];
        damage = d[2];
        boost = 0;
        break;
    case GAME_TYPE_BE_A_COP:
        d = f->BeTheCopSetupData;
        strength = Fred.ChallengeScreenData[4];
        police = 1;
        beACop = 1;
        roadBlocks = 3;
        choppers = 3;
        ai = players == 1 ? 4 : 0;
        tickets = players == 1 ? 0 : 2;
        traffic = d[3];
        damage = d[4];
        boost = d[2];
        select = d[1];
        // The clock: two players get five minutes and keep it after an
        // arrest; one gets 2:30, 2:05 or 1:50 by the difficulty, reset by
        // each arrest.
        if (players != 1) {
            resetTimer = 0;
            seconds = 300;
        } else
            seconds = strength == 1 ? 125 : strength == 2 ? 110 : 150;
        break;
    }

    most = (int32_t)(8u - (uint32_t)players);   // pminw, signed
    if (ai > most)
        ai = most;

    rp->nMaxCops = police ? (beACop ? 2 : 6) : 0;
    rp->bHelicopter = 1;
    rp->New624 = police;
    rp->NumAICars = ai;
    rp->TrafficDensity = (uint32_t)traffic < 4u
                       ? kSetupTrafficDensity[traffic] : 0.0f;
    rp->PlayerStartPosition[0] = (int8_t)(uint8_t)(ai + 1);
    rp->PlayerStartPosition[1] = (int8_t)(uint8_t)(ai + 2);
    rp->Boost = boost;
    rp->CopStrength = strength;
    rp->OpponentSelect = select;
    rp->DamageEnabled = damage != 0;
    rp->nNumBeACopRoadBlocks = roadBlocks;
    rp->nNumBeACopChoppers = choppers;
    rp->nNumTicketsBeforeArrest = tickets;
    rp->BeACopResetTimerAfterArrest = resetTimer;
    rp->ZoneCamsEnabled = Fred.DisplayOptionsData.ZoneCams != 0;
    rp->JumpCamsEnabled = Fred.DisplayOptionsData.JumpCams != 0;
    rp->bRoadBlocks = police;
    rp->bSpikeStrips = police;
    rp->TrafficOncoming = 0.5f;
    rp->OpponentStrength = strength;
    rp->BeACop = beACop;
    rp->TrainingLinesEnabled = 0;
    if (beACop) {
        rp->HasObjective = 1;
        b_strncpy(rp->sObjective, translate(0x000ecd11),
                  (int32_t)sizeof rp->sObjective);
        rp->TimeTrialTime.PackedTime =
            (uint32_t)ee_trunc_w((float)seconds * 4000.0f + 0.5f);
    } else {
        rp->TimeTrialTime.PackedTime = 0;
        rp->HasObjective = 0;
        rp->sObjective[0] = '\0';
    }
}
