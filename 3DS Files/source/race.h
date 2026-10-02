// race -- Race, RacingCar and RaceParameters.
//
// Race is 1716 bytes (.mdebug type#1645, the same in the demo and retail)
// and RaceParameters 788 in retail (the demo's type#3457 is 768).
// PhysicsCar::Move reads one word of each -- the race's stage through
// pCurrentRace, and DamageEnabled through BodyDamage::GetVisibleTotalDamage.
// Race's methods are racecore.c's and RaceParameters' raceparams.c's; this
// file keeps the two accessors everything else uses.
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
#include "playersettings.h"
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

// eTrackDirection, from the .mdebug.
typedef int32_t eTrackDirection;
#define TRACK_DIRECTION_FORWARD  ((eTrackDirection)0)
#define TRACK_DIRECTION_BACKWARD ((eTrackDirection)1)

// RaceTypes, type#1000.
typedef enum RaceTypes {
    RACE_TYPE_NONE          = 0,
    RACE_TYPE_SINGLE_RACE   = 1,
    RACE_TYPE_TIME_TRIAL    = 2,
    RACE_TYPE_LAP_KNOCKOUT  = 3,
    RACE_TYPE_RACE_KNOCKOUT = 4,
    RACE_TYPE_TOURNAMENT    = 5,
} RaceTypes;

// tGlobalDisplaySettings (type#1393), eight bytes: what the player picked
// for the HUD, which RCStateNoneCallback copies from the frontend's on
// RESTART_RACE and NEXT_RACE. The demo's last two were Scoring and
// padding; retail's defaults (0x001ee0a0) fill them from SkipFE's
// EnableJumpCam and EnableZoneCam, the two switches retail took out of
// every race setup's data, so the port names them for those.
typedef struct tGlobalDisplaySettings {
    int8_t RearViewMirror;
    int8_t Units;
    int8_t OnePlayerTrackMapMode;
    int8_t TwoPlayerTrackMapMode;
    int8_t BeTheCopTrackMapMode;
    int8_t LeaderboardMode;
    int8_t JumpCams;                // the demo's Scoring
    int8_t ZoneCams;                // the demo's pad
} tGlobalDisplaySettings;

typedef char global_display_settings_size_check[
    sizeof(tGlobalDisplaySettings) == 8 ? 1 : -1];

// ------------------------------------------------------- RaceParameters

struct DriverInfo;

// RaceParameters, 788 bytes in retail (the demo's type#3457 is 768).
// Retail added the int at 624, which only tCopManager reads, so BeACop and
// everything after it is 4 further on; PlayerSettings grew from 40 bytes
// to 48 each; the demo's pEliminatedDriverTable and NumEliminated are gone
// (DriverInfo carries EliminatedRank instead), and two words follow
// NumDriverInfo: 780, which InitWithDefaults draws from the default seed,
// and 784. The one pointer is the driver table, so the offsets hold where
// pointers are 4 bytes; the checkers' harnesses build one by name.
//
// Who reads what so far: PhysicsCar::Move, DamageEnabled, through
// BodyDamage::GetVisibleTotalDamage. RealDriver BeACop: its horn toggles
// the siren through the cop manager then, its nitro button fires the
// cop's boost, and the Player's constructor takes the cop's NIS overlay.
// The AI's route search TrackDirection, to tell the traffic that runs
// with the player from the oncoming. Car's catchup Boost: 0 returns from
// CalculateNewCatchupMultipliers before anything else is read.
// PleaseResetMeLater BeACop and nMaxCops, signed against 0 (`blez`).
// InitCars TrackNumber's TrackInfo; SetAIDriverModesFromPlayers splits
// the AI field at half of NumAICars; the Player's constructor picks the
// HUD's screen hashes only while AIDemoMode and ReplayDemoMode are both
// 0, and InitPlayers takes the player's car from World's array when
// AIDemoMode is set. Race's constructor takes its lap count from
// NumLapsInRace, 1 when Point2Point is set too, and FigureOutBoundaries a
// finish line apart from the start on a point-to-point race. While a
// replay plays, UpdateLapCounts times only a time trial's finish line.
// The frontend's setup screens write NumPlayerCars and NFSRaceMode as
// they leave -- You're The Cop's select (0x001b74f8) was the first ported.
typedef struct RaceParameters {
    int32_t   TrackNumber;                       //   0  GetTrackInfo's
    int32_t   TrackWeather;                      //   4
    int32_t   TrackTimeOfDay;                    //   8
    eTrackDirection TrackDirection;              //  12
    float     TrafficDensity;                    //  16
    float     TrafficOncoming;                   //  20
    int32_t   AIDemoMode;                        //  24  bool
    int32_t   ReplayDemoMode;                    //  28  bool
    int32_t   RaceType;                          //  32  RaceTypes
    Timer     TimeTrialTime;                     //  36
    int32_t   Point2Point;                       //  40
    int32_t   NumLapsInRace;                     //  44
    int32_t   NumPlayerCars;                     //  48
    int32_t   NumAICars;                         //  52
    int32_t   OpponentSelect;                    //  56
    int8_t    PlayerStartPosition[2];            //  60
    uint8_t   _pad62[2];                         //  62
    int32_t   DamageEnabled;                     //  64  bool
    int32_t   JumpCamsEnabled;                   //  68  bool
    int32_t   ZoneCamsEnabled;                   //  72  bool
    int32_t   TrainingLinesEnabled;              //  76  bool
    int32_t   HasObjective;                      //  80  bool
    char      sObjective[512];                   //  84
    int32_t   NFSRaceMode;                       // 596
    int32_t   EventTreeRace;                     // 600  bool
    int32_t   nMaxCops;                          // 604
    int32_t   bTickets;                          // 608
    int32_t   bRoadBlocks;                       // 612
    int32_t   bSpikeStrips;                      // 616
    int32_t   bHelicopter;                       // 620
    int32_t   New624;                            // 624  retail's
    int32_t   BeACop;                            // 628
    int32_t   BeACopResetTimerAfterArrest;       // 632
    int32_t   nNumTicketsBeforeArrest;           // 636
    int32_t   nNumBeACopRoadBlocks;              // 640
    int32_t   nNumBeACopChoppers;                // 644
    int32_t   CopStrength;                       // 648
    cPlayerSettings PlayerSettings[2];           // 652  what Player copies
    tGlobalDisplaySettings GlobalDisplaySettings; // 748
    int32_t   OpponentStrength;                  // 756
    int32_t   Boost;                             // 760  the catchup
    float     BoostScale[2];                     // 764
    struct DriverInfo *pDriverInfoTable;         // 772
    int32_t   NumDriverInfo;                     // 776
    int32_t   New780;                            // 780  retail's
    int32_t   New784;                            // 784  retail's
} RaceParameters;                                // 788

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char raceparameters_layout_check[
    (offsetof(RaceParameters, TimeTrialTime) == 36
     && offsetof(RaceParameters, PlayerStartPosition) == 60
     && offsetof(RaceParameters, DamageEnabled) == 64
     && offsetof(RaceParameters, sObjective) == 84
     && offsetof(RaceParameters, NFSRaceMode) == 596
     && offsetof(RaceParameters, BeACop) == 628
     && offsetof(RaceParameters, PlayerSettings) == 652
     && offsetof(RaceParameters, GlobalDisplaySettings) == 748
     && offsetof(RaceParameters, Boost) == 760
     && offsetof(RaceParameters, pDriverInfoTable) == 772
     && offsetof(RaceParameters, New784) == 784
     && sizeof(RaceParameters) == 788) ? 1 : -1];
#endif

// TheRaceParameters, retail's 0x0031a898 (the demo's 0x00312520): the race
// the frontend sets up and the race reads. raceparams.h has its methods.
// The image's is zero until _GLOBAL_$I$TheRaceParameters [73] runs
// InitWithDefaults; race.c starts four fields at InitWithDefaults' values,
// as they were when each was its own global, for the harnesses that link
// race.c and never run the constructor.
extern RaceParameters TheRaceParameters;

// The names the port's readers have used since each field was first
// needed, each the field itself.
#define RaceParametersTrackNumber      (TheRaceParameters.TrackNumber)
#define RaceParametersTrackDirection   (TheRaceParameters.TrackDirection)
#define RaceParametersAIDemoMode       (TheRaceParameters.AIDemoMode)
#define RaceParametersReplayDemoMode   (TheRaceParameters.ReplayDemoMode)
#define RaceParametersRaceType         (TheRaceParameters.RaceType)
#define RaceParametersPoint2Point      (TheRaceParameters.Point2Point)
#define RaceParametersNumLapsInRace    (TheRaceParameters.NumLapsInRace)
#define RaceParametersNumPlayerCars    (TheRaceParameters.NumPlayerCars)
#define RaceParametersNumAICars        (TheRaceParameters.NumAICars)
#define RaceParametersDamageEnabled    (TheRaceParameters.DamageEnabled)
#define RaceParametersNFSRaceMode      (TheRaceParameters.NFSRaceMode)
#define RaceParametersMaxCops          (TheRaceParameters.nMaxCops)
#define RaceParametersBeACop           (TheRaceParameters.BeACop)
#define RaceParametersPlayerSettings   (TheRaceParameters.PlayerSettings)
#define RaceParametersGlobalDisplaySettings \
    (TheRaceParameters.GlobalDisplaySettings)
#define RaceParametersBoost            (TheRaceParameters.Boost)
#define RaceParametersDriverInfo       (TheRaceParameters.pDriverInfoTable)
#define RaceParametersNumDriverInfo    (TheRaceParameters.NumDriverInfo)

// RaceParameters::GetDriverInfo(int), 0x001edb28: driver `i`, unchecked.
struct DriverInfo *race_parameters_get_driver_info(int32_t i);

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
