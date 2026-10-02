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
