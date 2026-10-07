// quickrace -- the Mode Selects' Quick Race. quickrace.h has the overview
// and docs/formats/quick-race.md the decode.

#include "quickrace.h"

#include <stddef.h>
#include <string.h>

#include "bmath.h"
#include "cartypeinfo.h"
#include "configitems.h"
#include "fred.h"
#include "fredrace.h"
#include "playersettings.h"
#include "race.h"
#include "raceparams.h"
#include "track.h"

int32_t gNumEventTrees;
int32_t (*gEventTreeTrackIsARewardFn)(int32_t tree, int32_t track,
                                      int32_t direction);
int32_t (*gEventTreeIsTrackUnlockedFn)(int32_t tree, int32_t track,
                                       int32_t direction);
void (*gQuickRaceStopMovieFn)(void);

// Fred.GameType's express game, which StartQuickRace sets.
#define GAME_TYPE_EXPRESS 2

// --------------------------------------------------------- the track locks

static int32_t tree_track_is_a_reward(int32_t tree, int32_t track,
                                      int32_t direction)
{
    return gEventTreeTrackIsARewardFn != NULL
           ? gEventTreeTrackIsARewardFn(tree, track, direction) : 0;
}

int32_t is_track_an_event_reward(int32_t track, int32_t direction)
{
    int32_t tree;

    for (tree = 0; tree < gNumEventTrees; tree++)
        if (tree_track_is_a_reward(tree, track, direction))
            return 1;
    return 0;
}

int32_t event_tree_is_track_unlocked(int32_t track, int32_t direction)
{
    int32_t tree;

    for (tree = 0; tree < gNumEventTrees; tree++) {
        if (!tree_track_is_a_reward(tree, track, direction))
            continue;
        if (gEventTreeIsTrackUnlockedFn == NULL)
            return 0;
        return gEventTreeIsTrackUnlockedFn(tree, track, direction) != 0;
    }
    return 1;
}

int32_t is_track_unlocked(int32_t track, int32_t direction)
{
    if (is_track_an_event_reward(track, direction))
        return event_tree_is_track_unlocked(track, direction);
    return 1;
}

// --------------------------------------------------------- the race

// The image's list is a bNode a candidate, bMalloc'd on pool 16 and freed
// as it returns. Track numbers are bytes, so no table lists more than 256
// tracks a direction; a candidate past the end is dropped.
#define EXPRESS_MAX_CANDIDATES 512

void pick_track_number_for_express_game(ExpressTrack *out)
{
    static ExpressTrack list[EXPRESS_MAX_CANDIDATES];
    int32_t n = 0;
    int32_t i;

    if (TrackSelectedInConfigFile >= 0) {
        out->Track = TrackSelectedInConfigFile;
        out->Direction = 0;
        return;
    }
    for (i = 0; i <= HighestTrackNumber; i++) {
        const TrackInfo *ti = track_get_info(i);
        int32_t direction;

        if (ti == NULL)
            continue;
        for (direction = 0; direction < 2; direction++) {
            if (!is_track_unlocked(ti->SameAsTrackNumber, direction))
                continue;
            if (n < EXPRESS_MAX_CANDIDATES) {
                list[n].Track = ti->TrackNumber;
                list[n].Direction = direction;
                n++;
            }
        }
    }

    // The image's bRandom traps on its divide when nothing is unlocked.
    if (n == 0) {
        out->Track = 0;
        out->Direction = 0;
        return;
    }
    *out = list[bRandomI(n, &bDefaultSeed)];
}

void start_quick_race(int32_t transmission)
{
    RaceParameters *rp = &TheRaceParameters;
    FrontendDatabase *f = &Fred;
    FrontendPlayerInfo *p0 = &f->FrontendPlayers[0];
    const TrackInfo *ti;
    ExpressTrack pick;
    int32_t cops;

    race_parameters_init_with_defaults(rp);
    if (gQuickRaceStopMovieFn != NULL)
        gQuickRaceStopMovieFn();
    cops = f->MainMenuOpts[1];
    f->GameType = GAME_TYPE_EXPRESS;
    f->NumPlayerCars = 1;
    pick_track_number_for_express_game(&pick);

    // The image reads the record with no test: a track the config file
    // names that the table lacks reads low memory there. The port reads 0.
    ti = track_get_info(pick.Track);
    rp->TrackNumber = pick.Track;
    rp->TrackDirection = (eTrackDirection)pick.Direction;
    rp->TrackTimeOfDay = ti != NULL ? ti->TimeOfDay : 0;
    rp->NumAICars = cops != 0 ? 3 : 7;
    rp->Point2Point = ti != NULL ? ti->Point2Point : 0;
    rp->PlayerStartPosition[0] = (int8_t)((uint8_t)rp->NumAICars + 1);
    rp->BoostScale[1] = 1.0f;
    rp->nMaxCops = cops != 0 ? 4 : 0;
    rp->nNumTicketsBeforeArrest = cops != 0 ? 2 : 0;
    rp->TrafficDensity = 0.33f;
    rp->TrafficOncoming = 0.5f;
    rp->BoostScale[0] = 1.0f;
    rp->CopStrength = 1;
    rp->RaceType = 1;
    rp->NumLapsInRace = 2;
    rp->EventTreeRace = 0;
    rp->OpponentStrength = 1;
    rp->Boost = 1;
    rp->NumPlayerCars = 1;
    rp->bRoadBlocks = cops;
    rp->bSpikeStrips = cops;
    rp->New624 = cops;
    rp->bHelicopter = cops;
    rp->nNumBeACopRoadBlocks = 0;
    rp->nNumBeACopChoppers = 0;
    rp->bTickets = cops;
    rp->HasObjective = 0;
    rp->sObjective[0] = 0;
    rp->TrainingLinesEnabled = 0;

    fred_make_challenge_cars_available(f);
    if (TrackSelectedInConfigFile >= 0) {
        fpi_set_car_availability(p0, CAR_STATUS_AVAILABLE,
                                 DefaultPlayer1CarType, -1, 1);
        fpi_assign_car_of_type(p0, f->GameType, DefaultPlayer1CarType,
                               (uint32_t)DefaultPlayer1SkinIndex, 0);
    } else {
        RideInfo ride;

        memset(&ride, 0, sizeof ride);
        ride.Type = -1;
        do {
            generate_random_ride_info(&ride, CAR_USAGE_TYPE_RACING, -1);
        } while (fpi_get_car_status(p0, ride.Type) != CAR_STATUS_AVAILABLE);
        fpi_assign_car_of_type(p0, f->GameType, ride.Type,
                               (uint32_t)(int32_t)ride.SkinNumber, 0);
    }
    p0->mPlayerSettings.TransmissionType = (int8_t)(transmission != 0);
    fred_start_race(f);
}
