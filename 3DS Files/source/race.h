// race -- the corner of Race.obj and RaceParameters that ported code reads
// before either is ported.
//
// Race is 1716 bytes (.mdebug type#1645) and RaceParameters 768
// (type#3457); both are task 26's. PhysicsCar::Move reads one word of
// each -- the race's stage through pCurrentRace, and DamageEnabled through
// BodyDamage::GetVisibleTotalDamage -- RealDriver reads BeACop, the AI's
// route search reads TrackDirection, Car's catchup reads Boost and
// PleaseResetMeLater BeACop and nMaxCops, so this declares those six, the
// two enums, RacingCar, and nothing else. Race
// stays incomplete: nothing in the port allocates one yet, and a partial
// layout would invite something to.
//
// RaceCoordinator (144 bytes, type#4165) is task 26's as well: the state
// machine above the race, from the flyby to the replays and the demos.
// A car's collision body asks it which state it is in, so this declares
// the state, the pointer and the one method, and leaves it incomplete too.

#ifndef RACE_H
#define RACE_H

#include <stddef.h>
#include <stdint.h>

#include "timer.h"

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

// TheRaceParameters.BeACop, retail's 0x0031ab0c (RaceParameters+628; the
// demo's +624). Nonzero when the player is the cop: RealDriver's horn
// toggles the siren through the cop manager then, and its nitro button
// fires the cop's boost, and the Player's constructor takes the cop's NIS
// overlay. 0 from InitWithDefaults; the Be A Cop setup screens set it.
// Retail added the int at +624, which only tCopManager reads.
extern int32_t RaceParametersBeACop;

// TheRaceParameters.nMaxCops, 0x0031277c (RaceParameters+604). How many
// cops the race may have out at once. PleaseResetMeLater compares it
// signed against 0 (`blez`).
extern int32_t RaceParametersMaxCops;

// eTrackDirection, from the .mdebug.
typedef int32_t eTrackDirection;
#define TRACK_DIRECTION_FORWARD  ((eTrackDirection)0)
#define TRACK_DIRECTION_BACKWARD ((eTrackDirection)1)

// TheRaceParameters.TrackDirection, 0x0031252c (RaceParameters+12). Forward
// from InitWithDefaults (`sw zero,12(s2)`). GetNearestRoutePoint reads it
// to tell the traffic that runs with the player from the oncoming.
extern eTrackDirection RaceParametersTrackDirection;

// TheRaceParameters.Boost, 0x00312804 (RaceParameters+740). Nonzero turns
// on the two-player catchup: Car::CalculateNewCatchupMultipliers returns
// before reading anything else when it is 0.
extern int32_t RaceParametersBoost;

// TheRaceParameters.NumDriverInfo, 0x00312814 (RaceParameters+756). The
// race's driver count; InitWithDefaults starts it at 0. InitPhysics reads
// it in the image (`lw s0,10260(v0)`); the port's takes it as an argument,
// and EndGameFlowLoadingTrackSpecific passes this.
extern int32_t RaceParametersNumDriverInfo;

// TheRaceParameters.NumPlayerCars (+48) and .NFSRaceMode (+596), at
// retail's 0x0031a8c8 and 0x0031aaec (RaceParameters is 0x0031a898 there).
// The frontend's setup screens write both as they leave -- You're The Cop's
// select (0x001b74f8) is the first ported -- and the race they start reads
// them. InitWithDefaults (0x001ed5c8) starts both at 1.
extern int32_t RaceParametersNumPlayerCars;
extern int32_t RaceParametersNFSRaceMode;

// TheRaceParameters.AIDemoMode (+24) and .ReplayDemoMode (+28), retail's
// 0x0031a8b0 and 0x0031a8b4: the attract mode's two races, the AI driving
// the player's car and a replay played back. The Player's constructor
// picks the HUD's screen hashes only when both are 0, and InitPlayers takes
// the player's car from World's array instead when AIDemoMode is set.
// InitWithDefaults starts both at 0.
extern int32_t RaceParametersAIDemoMode;
extern int32_t RaceParametersReplayDemoMode;

// ------------------------------------------------------------- RacingCar

struct Car;

// 192 bytes, type#1620: one car's standing in the race. Race keeps one per
// car and Car points at its own at 28. Every field is private in the stab
// and Race.obj's methods write them; the port only reads
// CurrentLapNumberExact so far, which is laps done plus the fraction of the
// current one, and is what the catchup compares.
//
// The eight one-byte fields are type 26, `char`, and the four two-byte
// ones type 28, `short`; their signs are taken from those types. The
// Timer arrays are 5 and 11 long, bounds [0;4] and [0;10].
struct RacingCar {
    struct Car *pCar;                           //   0
    int16_t   CurrentBoundaryRegion;            //   4
    int16_t   HighestBoundaryRegion;            //   6
    int8_t    CurrentLapNumber;                 //   8
    int8_t    NumLapsCompleted;                 //   9
    int8_t    RacePosition;                     //  10
    int8_t    PreviousRacePosition;             //  11
    int8_t    FinishingOrder;                   //  12
    int8_t    CrossedFinishLine;                //  13
    int8_t    CompletedNewLap;                  //  14
    int8_t    CrossedNewBoundary;               //  15
    int16_t   NumLapsLed;                       //  16
    int16_t   FinishReason;                     //  18
    float     CurrentLapNumberExact;            //  20
    float     dCurrentLapNumberExact;           //  24
    float     PreviousDistanceAroundTrack;      //  28
    float     FinishedLapNumberExact;           //  32
    Timer     BoundaryCrossingTimes[5];         //  36
    Timer     RunningTimes[5];                  //  56
    Timer     PreviousRunningTimes[5];          //  76
    Timer     BestRunningTimes[5];              //  96
    Timer     PreviousBestRunningTimes[5];      // 116
    Timer     LapTimes[11];                     // 136
    Timer     RaceTime;                         // 180
    float     TopSpeed;                         // 184
    float     AverageSpeed;                     // 188
};                                              // 192

// One pointer leads, so a 64-bit host moves everything after it by four.
#define RACINGCAR_SLACK ((size_t)(sizeof(void *) - 4))

typedef char racingcar_layout_check[
    (offsetof(struct RacingCar, CurrentBoundaryRegion) == 4 + RACINGCAR_SLACK
     && offsetof(struct RacingCar, NumLapsLed) == 16 + RACINGCAR_SLACK
     && offsetof(struct RacingCar, CurrentLapNumberExact)
            == 20 + RACINGCAR_SLACK
     && offsetof(struct RacingCar, BoundaryCrossingTimes)
            == 36 + RACINGCAR_SLACK
     && offsetof(struct RacingCar, LapTimes) == 136 + RACINGCAR_SLACK
     && offsetof(struct RacingCar, AverageSpeed) == 188 + RACINGCAR_SLACK
     && sizeof(struct RacingCar)
            == ((192 + RACINGCAR_SLACK + sizeof(void *) - 1)
                / sizeof(void *)) * sizeof(void *))
    ? 1 : -1];

// 0x00146ad8, eight bytes: `jr ra; lw v0,28(a1)`. The race is not read,
// so this needs no Race layout; the car's own pointer is the answer.
struct RacingCar *race_get_racing_car(Race *r, struct Car *c);

// ------------------------------------------------------- RaceCoordinator

// RCState, from the .mdebug enum (t1006).
typedef int32_t RCState;
#define RCSTATE_NONE              ((RCState)0)
#define RCSTATE_CAMERA_FLYBY      ((RCState)1)
#define RCSTATE_PRERACE           ((RCState)2)
#define RCSTATE_RACE_IN_PROGRESS  ((RCState)3)
#define RCSTATE_INSTANT_REPLAY    ((RCState)4)
#define RCSTATE_AUTO_REPLAY       ((RCState)5)
#define RCSTATE_PAUSE             ((RCState)6)
#define RCSTATE_POSTRACE          ((RCState)7)
#define RCSTATE_AI_DEMO_MODE      ((RCState)8)
#define RCSTATE_REPLAY_DEMO_MODE  ((RCState)9)
#define NUM_RCSTATES              ((RCState)10)

typedef struct RaceCoordinator RaceCoordinator;

// gp-22720, 0x00323330. NULL in the port until RaceCoordinator exists.
extern RaceCoordinator *pRaceCoordinator;

// RaceCoordinator::GetCurrentState, inlined everywhere as `lw v0,0(a0)`:
// CurrentRCState is the first member.
RCState racecoordinator_get_current_state(const RaceCoordinator *rc);

// 0x00134b00, sixteen bytes: CurrentRCState == RCSTATE_REPLAY_DEMO_MODE.
// The only one of the Is* tests the image keeps out of line.
int32_t racecoordinator_is_replay_demo_mode(const RaceCoordinator *rc);

// IsGameFlowPaused, 0x001680b8 in GameFlow.obj (the demo's 0x001636c8,
// the same code): pRaceCoordinator is set and in RCSTATE_PAUSE. It lives
// here because it reads nothing else, and gameflow.c's boot flow does not
// need the race.
int32_t is_game_flow_paused(void);

#endif
