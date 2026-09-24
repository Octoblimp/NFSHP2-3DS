// race -- see race.h.

#include "race.h"

Race   *pCurrentRace;                   // 0x003232f8
int32_t RaceParametersDamageEnabled;    // 0x00312560
int32_t RaceParametersBeACop;           // 0x00312790
eTrackDirection RaceParametersTrackDirection; // 0x0031252c

eRaceStage race_get_race_stage(const Race *r)
{
    return *(const eRaceStage *)(const void *)r;
}
