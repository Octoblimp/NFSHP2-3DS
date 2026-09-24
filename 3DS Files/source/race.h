// race -- the corner of Race.obj and RaceParameters that ported code reads
// before either is ported.
//
// Race is 1716 bytes (.mdebug type#1645) and RaceParameters 768
// (type#3457); both are task 26's. PhysicsCar::Move reads one word of
// each -- the race's stage through pCurrentRace, and DamageEnabled through
// BodyDamage::GetVisibleTotalDamage -- RealDriver reads BeACop and the AI's
// route search reads TrackDirection, so this declares those four, the two
// enums, and nothing else. The struct stays incomplete: nothing in
// the port allocates a Race yet, and a partial layout would invite
// something to.

#ifndef RACE_H
#define RACE_H

#include <stdint.h>

// eRaceStage, from the .mdebug enum (the same in every unit that has it).
typedef int32_t eRaceStage;
#define RACE_STAGE_NONE       ((eRaceStage)0)
#define RACE_STAGE_FLYBY      ((eRaceStage)1)
#define RACE_STAGE_PRERACE    ((eRaceStage)2)
#define RACE_STAGE_COUNTDOWN  ((eRaceStage)3)
#define RACE_STAGE_RACING     ((eRaceStage)4)

typedef struct Race Race;

// gp-22776, 0x003232f8. Move dereferences it without a NULL test, twice
// per sub-step, so a car must not be moved before a race exists.
extern Race *pCurrentRace;

// Race::GetRaceStage, inlined at every call site as `lw v0,0(v1)`:
// RaceStage is the first member.
eRaceStage race_get_race_stage(const Race *r);

// TheRaceParameters.DamageEnabled, 0x00312560 (RaceParameters+64). 0 from
// InitWithDefaults (0x001df4a8, `sw zero,64(s2)`); the frontend's race
// setup is what turns it on, and that setup is task 26's too.
extern int32_t RaceParametersDamageEnabled;

// TheRaceParameters.BeACop, 0x00312790 (RaceParameters+624). Nonzero when
// the player is the cop: RealDriver's horn toggles the siren through the
// cop manager then, and its nitro button fires the cop's boost. 0 from
// InitWithDefaults; the Be A Cop setup screens set it.
extern int32_t RaceParametersBeACop;

// eTrackDirection, from the .mdebug.
typedef int32_t eTrackDirection;
#define TRACK_DIRECTION_FORWARD  ((eTrackDirection)0)
#define TRACK_DIRECTION_BACKWARD ((eTrackDirection)1)

// TheRaceParameters.TrackDirection, 0x0031252c (RaceParameters+12). Forward
// from InitWithDefaults (`sw zero,12(s2)`). GetNearestRoutePoint reads it
// to tell the traffic that runs with the player from the oncoming.
extern eTrackDirection RaceParametersTrackDirection;

#endif
