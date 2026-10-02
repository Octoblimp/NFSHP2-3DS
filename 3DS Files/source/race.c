// race -- see race.h.

#include "race.h"

#include "car.h"

Race   *pCurrentRace;                   // retail 0x003301f0
// The image's is zero until [73]; these four are InitWithDefaults' values,
// which the harnesses that link this and not raceparams.c start from.
RaceParameters TheRaceParameters = {      // retail 0x0031a898
    .NumLapsInRace = 2,
    .NumPlayerCars = 1,
    .NumAICars     = 7,
    .NFSRaceMode   = 1,
};
RaceCoordinator *pRaceCoordinator;      // retail 0x00330228

DriverInfo *race_parameters_get_driver_info(int32_t i)
{
    return &TheRaceParameters.pDriverInfoTable[i];
}

eRaceStage race_get_race_stage(const Race *r)
{
    return *(const eRaceStage *)(const void *)r;
}

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    (void)r;
    return c->pRacingCar;
}

RCState racecoordinator_get_current_state(const RaceCoordinator *rc)
{
    return *(const RCState *)(const void *)rc;
}

int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc)
{
    return racecoordinator_get_current_state(rc) == RCSTATE_REPLAY_DEMO_MODE;
}

int32_t is_game_flow_paused(void)
{
    return pRaceCoordinator != NULL
        && racecoordinator_get_current_state(pRaceCoordinator) == RCSTATE_PAUSE;
}
