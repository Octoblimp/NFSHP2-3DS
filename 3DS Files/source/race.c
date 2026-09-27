// race -- see race.h.

#include "race.h"

#include "car.h"

Race   *pCurrentRace;                   // 0x003232f8
int32_t RaceParametersDamageEnabled;    // 0x00312560
int32_t RaceParametersBeACop;           // 0x00312790
int32_t RaceParametersMaxCops;          // 0x0031277c
eTrackDirection RaceParametersTrackDirection; // 0x0031252c
int32_t RaceParametersBoost;            // 0x00312804
int32_t RaceParametersNumDriverInfo;    // 0x00312814
RaceCoordinator *pRaceCoordinator;      // 0x00323330

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
