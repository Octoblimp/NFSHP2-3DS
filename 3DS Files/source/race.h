// race -- Race, RacingCar and the corner of RaceParameters that ported code
// reads.
//
// Race is 1716 bytes (.mdebug type#1645, the same in the demo and retail)
// and RaceParameters 768 (type#3457). PhysicsCar::Move reads one word of
// each -- the race's stage through pCurrentRace, and DamageEnabled through
// BodyDamage::GetVisibleTotalDamage -- RealDriver reads BeACop, the AI's
// route search reads TrackDirection, Car's catchup reads Boost and
// PleaseResetMeLater BeACop and nMaxCops. RaceParameters is declared a
// field at a time, as each is needed. Race's methods are racecore.c's;
// this file keeps the two accessors everything else uses.
//
// RaceCoordinator (144 bytes, type#4165) is task 26's as well: the state
// machine above the race, from the flyby to the replays and the demos.
// A car's collision body asks it which state it is in, so this declares
// the state, the pointer and the one method, and leaves it incomplete too.

#ifndef RACE_H
#define RACE_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "timer.h"

// eRaceStage, from the .mdebug enum (the same in every unit that has it).
typedef int32_t eRaceStage;
#define RACE_STAGE_NONE       ((eRaceStage)0)
#define RACE_STAGE_FLYBY      ((eRaceStage)1)
#define RACE_STAGE_PRERACE    ((eRaceStage)2)
#define RACE_STAGE_COUNTDOWN  ((eRaceStage)3)
#define RACE_STAGE_RACING     ((eRaceStage)4)

typedef struct Race Race;

// Retail's gp-22272 (0x003301f0; the demo's 0x003232f8). Race's constructor
// sets it and the destructor clears it. Move dereferences it without a
// NULL test, twice per sub-step, so a car must not be moved before a race
// exists.
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

// TheRaceParameters.NumDriverInfo, retail's 0x0031aba0 (RaceParameters+776;
// the demo's +756 at 0x00312814). The race's driver count; InitWithDefaults
// starts it at 0. InitPhysics reads it in the image (`lw s0,10260(v0)`);
// the port's takes it as an argument, and EndGameFlowLoadingTrackSpecific
// passes this.
extern int32_t RaceParametersNumDriverInfo;

// TheRaceParameters.TrackNumber, retail's 0x0031a898 (RaceParameters+0):
// the track the race is on, as GetTrackInfo numbers them. InitCars looks
// up its TrackInfo.
extern int32_t RaceParametersTrackNumber;

// TheRaceParameters' DriverInfos, retail's 0x0031ab9c (RaceParameters+772):
// the race's drivers, NumDriverInfo of them, 24 bytes apart in retail.
// AddDriverInfo (0x001eda40) fills it as the frontend sets the race up;
// nothing in the port does yet, so it is NULL and the count 0.
extern struct DriverInfo *RaceParametersDriverInfo;

// RaceParameters::GetDriverInfo(int), 0x001edb28: driver `i`, unchecked.
struct DriverInfo *race_parameters_get_driver_info(int32_t i);

// TheRaceParameters.NumPlayerCars (+48) and .NFSRaceMode (+596), at
// retail's 0x0031a8c8 and 0x0031aaec (RaceParameters is 0x0031a898 there).
// The frontend's setup screens write both as they leave -- You're The Cop's
// select (0x001b74f8) is the first ported -- and the race they start reads
// them. InitWithDefaults (0x001ed5c8) starts both at 1.
extern int32_t RaceParametersNumPlayerCars;
extern int32_t RaceParametersNFSRaceMode;

// TheRaceParameters.NumAICars (+52), retail's 0x0031a8cc: how many AI
// racers the race has. SetAIDriverModesFromPlayers splits the AI field at
// half of it. InitWithDefaults starts it at 7 (`sw t2,52(s0)`).
extern int32_t RaceParametersNumAICars;

// TheRaceParameters.AIDemoMode (+24) and .ReplayDemoMode (+28), retail's
// 0x0031a8b0 and 0x0031a8b4: the attract mode's two races, the AI driving
// the player's car and a replay played back. The Player's constructor
// picks the HUD's screen hashes only when both are 0, and InitPlayers takes
// the player's car from World's array instead when AIDemoMode is set.
// InitWithDefaults starts both at 0.
extern int32_t RaceParametersAIDemoMode;
extern int32_t RaceParametersReplayDemoMode;

// TheRaceParameters.Point2Point (+40) and .NumLapsInRace (+44), retail's
// 0x0031a8c0 and 0x0031a8c4. Race's constructor takes its lap count from
// the second, and makes it 1 when both are set; FigureOutBoundaries adds
// a finish line apart from the start only on a point-to-point race.
// InitWithDefaults starts them at 0 and 2.
extern int32_t RaceParametersPoint2Point;
extern int32_t RaceParametersNumLapsInRace;

// RaceTypes, type#1000.
typedef enum RaceTypes {
    RACE_TYPE_NONE          = 0,
    RACE_TYPE_SINGLE_RACE   = 1,
    RACE_TYPE_TIME_TRIAL    = 2,
    RACE_TYPE_LAP_KNOCKOUT  = 3,
    RACE_TYPE_RACE_KNOCKOUT = 4,
    RACE_TYPE_TOURNAMENT    = 5,
} RaceTypes;

// TheRaceParameters.RaceType (+32), retail's 0x0031a8b8. While a replay
// plays, UpdateLapCounts times only a time trial's finish line.
// InitWithDefaults starts it at RACE_TYPE_NONE.
extern int32_t RaceParametersRaceType;

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

// 0x00146ad8, eight bytes: `jr ra; lw v0,28(a1)`. The race is not read;
// the car's own pointer is the answer.
struct RacingCar *race_get_racing_car(Race *r, struct Car *c);

// ------------------------------------------------------------------ Race

struct GhostCarData;
struct WorldObject;
struct TimeAroundTrackTable;

#define RACE_MAX_RACING_CARS 8
#define RACE_MAX_BOUNDARIES  5

// 1716 bytes, type#1645. StartGoTimeFrames and StartCountdownTimeFrames
// are type 30, `long`. The boundaries are where a lap is timed from: the
// start line, up to three splits and, on a point-to-point race, a finish
// line of its own, each as a percentage of the way around the track
// (FigureOutBoundaries). The two ghost car pairs are never set in retail,
// whose SetupGhostCars is empty; the destructor still frees them.
struct Race {
    eRaceStage        RaceStage;                        //    0
    int32_t           StartGoTimeFrames;                //    4
    int32_t           StartCountdownTimeFrames;         //    8
    Timer             StartTime;                        //   12
    Timer             RaceTime;                         //   16
    Timer             BestLapTime;                      //   20
    int32_t           NumRacingCars;                    //   24
    int32_t           NumRacingCarsFinished;            //   28
    int32_t           DetectedOneCarRemaining;          //   32  bool
    struct RacingCar  RacingCarTable[RACE_MAX_RACING_CARS]; //   36
    struct RacingCar *pRacingCars[RACE_MAX_RACING_CARS];    // 1572
    int32_t           NumLapsInRace;                    // 1604
    int32_t           ForceRaceFinishPosition;          // 1608
    int32_t           ForceRaceFinishPlayerNum;         // 1612
    int16_t           NumBoundaries;                    // 1616
    int8_t            StartLineBoundaryNumber;          // 1618
    int8_t            FinishLineBoundaryNumber;         // 1619
    float             BoundaryDistances[RACE_MAX_BOUNDARIES]; // 1620
    bVector2          StartLinePosition;                // 1640
    bVector2          FinishLinePosition;               // 1648
    struct GhostCarData *pReplayingGhostCarData;        // 1656
    struct WorldObject  *pReplayingGhostCarWorldObject; // 1660
    struct Car          *pCapturingGhostCar;            // 1664
    struct GhostCarData *pCapturingGhostCarData;        // 1668
    char              GhostCarDataFilename[40];         // 1672
    struct TimeAroundTrackTable *pTimeAroundTrackTable; // 1712
};                                                      // 1716

// The image's offsets hold on a 32-bit target. A 64-bit host widens every
// pointer and RacingCar with them, and nothing reads a Race as bytes.
#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char race_layout_check[
    (offsetof(struct Race, RacingCarTable) == 36
     && offsetof(struct Race, pRacingCars) == 1572
     && offsetof(struct Race, NumLapsInRace) == 1604
     && offsetof(struct Race, NumBoundaries) == 1616
     && offsetof(struct Race, StartLineBoundaryNumber) == 1618
     && offsetof(struct Race, FinishLineBoundaryNumber) == 1619
     && offsetof(struct Race, BoundaryDistances) == 1620
     && offsetof(struct Race, StartLinePosition) == 1640
     && offsetof(struct Race, FinishLinePosition) == 1648
     && offsetof(struct Race, pReplayingGhostCarData) == 1656
     && offsetof(struct Race, GhostCarDataFilename) == 1672
     && offsetof(struct Race, pTimeAroundTrackTable) == 1712
     && sizeof(struct Race) == 1716) ? 1 : -1];
#endif

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

// Retail's gp-22216, 0x00330228 (the demo's gp-22720). racecoord.c defines
// the struct; InitForRace sets this and trackflow.c clears it.
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
