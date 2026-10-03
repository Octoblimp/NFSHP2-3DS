// raceparams -- see raceparams.h.

#include "raceparams.h"

#include <stddef.h>
#include <string.h>

#include "bmath.h"
#include "cartypeinfo.h"
#include "configitems.h"
#include "playersettings.h"

DriverInfo DriverInfoTable[RACE_PARAMETERS_MAX_DRIVERS];   // retail 0x0031abb0

void race_parameters_init_with_defaults(RaceParameters *rp)
{
    memset(rp, 0, sizeof *rp);
    rp->TrackNumber = 11;
    rp->TrackTimeOfDay = 3;
    rp->TrafficOncoming = 0.5f;
    rp->PlayerStartPosition[0] = 7;
    rp->PlayerStartPosition[1] = 8;
    rp->nNumTicketsBeforeArrest = 2;
    rp->Boost = 1;
    rp->BoostScale[1] = 1.0f;
    rp->TrafficDensity = 1.0f;
    rp->NumLapsInRace = 2;
    rp->NumPlayerCars = 1;
    rp->NumAICars = 7;
    rp->NFSRaceMode = 1;
    rp->bTickets = 1;
    rp->bRoadBlocks = 1;
    rp->bSpikeStrips = 1;
    rp->bHelicopter = 1;
    rp->New624 = 1;
    rp->BeACopResetTimerAfterArrest = 1;
    memset(DriverInfoTable, 0, sizeof DriverInfoTable);
    rp->BoostScale[0] = 1.0f;
    rp->pDriverInfoTable = DriverInfoTable;
    player_settings_reset_to_defaults(&rp->PlayerSettings[0]);
    rp->NumDriverInfo = 0;
    player_settings_reset_to_defaults(&rp->PlayerSettings[1]);
    rp->Point2Point = 0;
    global_display_settings_init_with_defaults(&rp->GlobalDisplaySettings);
    rp->TrainingLinesEnabled = 0;
    rp->HasObjective = 0;
    rp->New780 = bRandomI(-1, &bDefaultSeed);
    rp->New784 = 0;
}

void global_display_settings_init_with_defaults(tGlobalDisplaySettings *d)
{
    int32_t skip = config_skip_fe();

    d->RearViewMirror = skip ? (int8_t)(uint8_t)SkipFERearView : 1;
    d->Units = skip ? (int8_t)(uint8_t)SkipFESpeedoMode
        : (int8_t)((gCurrLanguageFn != NULL ? gCurrLanguageFn() : 0) != 0);
    d->TwoPlayerTrackMapMode = 7;
    d->BeTheCopTrackMapMode = 8;
    d->LeaderboardMode = 2;
    d->OnePlayerTrackMapMode = 0;
    d->JumpCams = skip ? (int8_t)(uint8_t)SkipFEEnableJumpCam : 1;
    d->ZoneCams = skip ? (int8_t)(uint8_t)SkipFEEnableZoneCam : 1;
}

// Retail 0x001ee590; the demo's _GLOBAL_$I$TheRaceParameters is
// 0x001e03d8.
void race_parameters_static_init(void)
{
    RaceParameters *rp = &TheRaceParameters;
    int i;

    rp->TimeTrialTime.PackedTime = 0;
    for (i = 0; i < 2; i++) {
        rp->PlayerSettings[i].BestTotalTimeRecord.PackedTime = 0;
        rp->PlayerSettings[i].BestLapTimeRecord.PackedTime = 0;
    }
    race_parameters_init_with_defaults(rp);
    for (i = 0; i < RACE_PARAMETERS_MAX_DRIVERS; i++) {
        DriverInfo *di = &DriverInfoTable[i];

        di->EliminatedRank = 0;
        di->CurrentRideInfo.Type = -1;
        di->CurrentRideInfo.InstanceIndex = 0;
        di->CurrentRideInfo.SkinNumber = 0;
        di->CurrentRideInfo.HasDash = 0;
        di->CurrentRideInfo.CanBeVertexDamaged = 0;
    }
}

void race_parameters_add_driver_info(RaceParameters *rp, const DriverInfo *d)
{
    if (rp->NumDriverInfo >= RACE_PARAMETERS_MAX_DRIVERS)
        return;
    rp->pDriverInfoTable[rp->NumDriverInfo] = *d;
    rp->NumDriverInfo++;
}

DriverInfo *race_parameters_find_driver(RaceParameters *rp, int32_t number)
{
    int32_t i;

    for (i = 0; i < rp->NumDriverInfo; i++)
        if (rp->pDriverInfoTable[i].UniqueDriverNumber == number)
            return &rp->pDriverInfoTable[i];
    return NULL;
}

void race_parameters_restore_eliminated(RaceParameters *rp)
{
    int32_t i;

    for (i = 0; i < rp->NumDriverInfo; i++) {
        DriverInfo *d = &rp->pDriverInfoTable[i];

        if (d->EliminatedRank <= 0)
            continue;
        if (d->TheDriverType == DRIVER_TYPE_PLAYER)
            rp->NumPlayerCars++;
        else if (d->TheDriverType == DRIVER_TYPE_AI_RACER)
            rp->NumAICars++;
        d->EliminatedRank = 0;
    }
}

DriverInfo *race_parameters_eliminate_driver(RaceParameters *rp,
                                             int32_t number, int32_t rank)
{
    DriverInfo *d = race_parameters_find_driver(rp, number);

    if (d == NULL || d->EliminatedRank > 0)
        return d;
    d->EliminatedRank = (int8_t)rank;
    if (d->TheDriverType == DRIVER_TYPE_PLAYER)
        rp->NumPlayerCars--;
    else if (d->TheDriverType == DRIVER_TYPE_AI_RACER)
        rp->NumAICars--;
    return d;
}

// The image reads a CarTypeInfo for any type. The port's only reads the
// 64 there are: a ride of any other type counts as no model and matches
// none.
static const CarTypeInfo *ride_car(const RideInfo *r)
{
    return r->Type >= 0 && r->Type < 64 ? cartypeinfo_get(r->Type) : NULL;
}

int32_t race_parameters_too_many_models(RaceParameters *rp,
                                        const RideInfo *ride)
{
    int32_t n = rp->NumDriverInfo;
    int32_t models = 0;
    int32_t i, j;

    for (i = 0; i <= n; i++) {
        const RideInfo *r;
        const CarTypeInfo *ct;

        // The table has room for 14; past that the port takes no rank.
        if (i < RACE_PARAMETERS_MAX_DRIVERS
            && rp->pDriverInfoTable[i].EliminatedRank > 0)
            continue;
        r = i < n ? &rp->pDriverInfoTable[i].CurrentRideInfo : ride;
        ct = ride_car(r);
        if (ct == NULL || ct->UsageType == CAR_USAGE_TYPE_TRAFFIC)
            continue;
        if (r->CanBeVertexDamaged != 0) {
            models++;
            continue;
        }
        for (j = 0; j < i; j++) {
            const DriverInfo *dj = &rp->pDriverInfoTable[j];
            const CarTypeInfo *cj;

            if (dj->EliminatedRank > 0
                || dj->CurrentRideInfo.CanBeVertexDamaged != 0)
                continue;
            cj = ride_car(&dj->CurrentRideInfo);
            if (cj != NULL && strcmp(ct->CompressedGeometryFilename,
                                     cj->CompressedGeometryFilename) == 0)
                break;
        }
        if (j == i)
            models++;
    }
    return models >= 6;
}

int32_t race_parameters_get_location_number(const RaceParameters *rp)
{
    return rp->TrackNumber / 10;
}

int32_t race_parameters_get_location_index(const RaceParameters *rp)
{
    int32_t loc = race_parameters_get_location_number(rp);

    return loc == 6 ? 4 : loc - 1;
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    return rp->RaceType == RACE_TYPE_SINGLE_RACE && rp->NumLapsInRace == 0
        && rp->BeACop == 0;
}
