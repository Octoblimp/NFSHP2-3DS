// race -- see race.h.

#include "race.h"

#include "car.h"

Race   *pCurrentRace;                   // 0x003232f8
int32_t RaceParametersDamageEnabled;    // 0x00312560
int32_t RaceParametersBeACop;           // retail 0x0031ab0c
int32_t RaceParametersMaxCops;          // 0x0031277c
eTrackDirection RaceParametersTrackDirection; // 0x0031252c
int32_t RaceParametersBoost;            // 0x00312804
int32_t RaceParametersNumDriverInfo;    // retail 0x0031aba0
int32_t RaceParametersTrackNumber;      // retail 0x0031a898
DriverInfo *RaceParametersDriverInfo;   // retail 0x0031ab9c
int32_t RaceParametersNumPlayerCars = 1;  // retail 0x0031a8c8
int32_t RaceParametersNFSRaceMode   = 1;  // retail 0x0031aaec
int32_t RaceParametersAIDemoMode;       // retail 0x0031a8b0
int32_t RaceParametersReplayDemoMode;   // retail 0x0031a8b4
RaceCoordinator *pRaceCoordinator;      // 0x00323330

DriverInfo *race_parameters_get_driver_info(int32_t i)
{
    return &RaceParametersDriverInfo[i];
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
