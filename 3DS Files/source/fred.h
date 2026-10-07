// fred -- Fred, the frontend database, its constructor and its defaults.
//
// FrontendDatabase is 0x114e0 bytes in retail (the demo's type#880 is
// 70592): every setup screen's data, the audio and display options, the
// event trees' states, the high scores and the two players' cars,
// characters and settings. The memory card saves it whole (memcard.c), so
// the record holds no host pointer -- pUltimateState is the image's word
// -- and its offsets are the image's on every host. The setup screens,
// the jukebox and the memory card still reach it as bytes, through
// fred_bytes(); they may, since a character type aliases anything.
//
// Retail's static constructor (_GLOBAL_$I$Fred, sinit's [34]) runs
// FrontendDatabase's constructor (0x001836a0), which only sets the members
// that have constructors of their own. InitFred (0x00183820) is
// InitializeEverything's, after LoadGlobalChunks, and runs
// InitWithDefaults (0x00183830), which the frontend runs again once a
// language is chosen; a memory card's save loads over what it leaves.

#ifndef FRED_H
#define FRED_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"
#include "characterinfo.h"
#include "playersettings.h"
#include "race.h"
#include "timer.h"

#define FRED_NUM_CAR_TYPES   64
#define FRED_MAX_SKINS       10
#define FRED_NUM_GAME_MODES  11
#define FRED_NUM_TOTAL_TIMES 7200
#define FRED_NUM_LAP_TIMES   800
#define FRED_NUM_STATS       8

// eCarStatus: 0 available; 3 is the constructor's and a car nobody may
// pick. The others come from CarTypeInfo's lock statuses.
#define CAR_STATUS_AVAILABLE 0
#define CAR_STATUS_HIDDEN    3

// GameTypes, the .mdebug enum, as far as the port reads them.
#define GAME_TYPE_BE_A_COP   7

// CarStatus, 24 bytes: whether a player may take the car, and which of
// its skins. Ten skins are kept; nSkins counts every one offered.
typedef struct CarStatus {
    int32_t nStatus;                             //  0  eCarStatus
    uint8_t aSkins[FRED_MAX_SKINS];              //  4  read with `lbu`
    uint8_t _pad14[2];                           // 14
    int32_t nSkins;                              // 16
    int32_t bDashAvailable;                      // 20
} CarStatus;                                     // 24

// FrontendPlayerInfo, 1744 bytes in retail (the demo's 1784): one player's
// cars, character and settings, and the ride each game mode starts with.
typedef struct FrontendPlayerInfo {
    CarStatus       aCarStatus[FRED_NUM_CAR_TYPES];      //    0
    CharacterInfo   mCharacterInfo;                      // 1536
    cPlayerSettings mPlayerSettings;                     // 1604
    RideInfo        RideInfoByGameMode[FRED_NUM_GAME_MODES]; // 1652
    int32_t         AccumulatedPoints;                   // 1740
} FrontendPlayerInfo;                                    // 1744

// A high score: the time and who set it, in what.
typedef struct FredHighScore {
    Timer   Time;                                // 0
    int16_t NameIndex;                           // 4
    int16_t CarType;                             // 6
} FredHighScore;                                 // 8

typedef struct HighScoreTable {
    FredHighScore TotalTimesTable[FRED_NUM_TOTAL_TIMES]; //     0
    FredHighScore LapTimesTable[FRED_NUM_LAP_TIMES];     // 57600
} HighScoreTable;                                        // 64000

// TransientStatsElement, 100 bytes in retail (the demo's 48 ends at
// AverageSpeed). Retail's constructor sets the two Timers and the eleven
// at 52, so 52 .. 96 are lap times; the words at 48 and 96 are new.
typedef struct TransientStatsElement {
    int32_t FinishPosition;                      //  0
    int32_t UniqueDriveNumber;                   //  4
    int32_t FinishReason;                        //  8
    Timer   RaceTime;                            // 12
    Timer   BestLapTime;                         // 16
    int32_t PointsThisRace;                      // 20
    int32_t PointsTotal;                         // 24
    int32_t FinishBonus;                         // 28
    int32_t NumTickets;                          // 32
    int32_t HandlingMode;                        // 36
    float   TopSpeed;                            // 40
    float   AverageSpeed;                        // 44
    int32_t New48;                               // 48
    Timer   LapTimes[11];                        // 52
    int32_t New96;                               // 96
} TransientStatsElement;                         // 100

typedef struct TransientStats {
    int32_t NumStats;                            //   0
    int32_t PointsRewardEarned;                  //   4
    int32_t TaskRewardEarned;                    //   8
    TransientStatsElement Stats[FRED_NUM_STATS]; //  12
} TransientStats;                                // 812

typedef struct FrontendDatabase {
    int32_t  SomeStupidFieldForMemcard;          //      0
    int32_t  Autosave;                           //      4
    int32_t  ChallengeScreenData[5];             //      8  bsetup.h's
    int32_t  MainMenuOpts[2];                    //     28  [1] mPolice
    int32_t  SingleRaceSetupData[7];             //     36
    int32_t  BeTheCopSetupData[5];               //     64  bsetup.h's
    int32_t  FreeRunSetupData[3];                //     84
    int32_t  RaceKnockoutSetupData[7];           //     96
    int32_t  LapKnockoutSetupData[6];            //    124
    uint8_t  AudioOptionsScreenData[176];        //    148  jukebox.h's
    int32_t  DisplayCalibrationData[2];          //    324
    tGlobalDisplaySettings DisplayOptionsData;   //    332
    int32_t  SelectTrackScreenData[4];           //    340
    int32_t  SelectedEventData[4];               //    356
    int32_t  SelectedLanguage;                   //    372
    int32_t  DesiredControllerConfig[2];         //    376
    int32_t  DemoModeStatus;                     //    384
    int32_t  SavedSizeofFred;                    //    388
    uint8_t  ChampionshipState[256];             //    392
    uint8_t  HotPursuitState[256];               //    648
    uint32_t pUltimateState;                     //    904  the image's
    TransientStats TransientStatsTable;          //    908
    HighScoreTable ChallengeHighScores;          //   1720
    uint8_t  HighScoreNameTable[1536];           //  65720
    uint8_t  RewardStates[112];                  //  67256  task, points
    int32_t  bRaceWasAborted;                    //  67368
    int32_t  GameType;                           //  67372  GameTypes
    int32_t  nCurrentEvent;                      //  67376
    int32_t  NumPlayerCars;                      //  67380
    FrontendPlayerInfo FrontendPlayers[2];       //  67384
    int32_t  New70872;                           //  70872
    int32_t  Checksum;                           //  70876
} FrontendDatabase;                              //  70880

typedef char frontenddatabase_layout_check[
    (offsetof(FrontendDatabase, AudioOptionsScreenData) == 148
     && offsetof(FrontendDatabase, DisplayOptionsData) == 332
     && offsetof(FrontendDatabase, SavedSizeofFred) == 388
     && offsetof(FrontendDatabase, TransientStatsTable) == 908
     && offsetof(FrontendDatabase, ChallengeHighScores) == 1720
     && offsetof(FrontendDatabase, HighScoreNameTable) == 0x100b8
     && offsetof(FrontendDatabase, bRaceWasAborted) == 0x10728
     && offsetof(FrontendDatabase, GameType) == 0x1072c
     && offsetof(FrontendDatabase, NumPlayerCars) == 0x10734
     && offsetof(FrontendDatabase, FrontendPlayers) == 0x10738
     && offsetof(FrontendDatabase, Checksum) == 0x114dc
     && sizeof(FrontendDatabase) == 0x114e0
     && offsetof(FrontendPlayerInfo, mCharacterInfo) == 1536
     && offsetof(FrontendPlayerInfo, mPlayerSettings) == 1604
     && offsetof(FrontendPlayerInfo, RideInfoByGameMode) == 1652
     && sizeof(FrontendPlayerInfo) == 1744
     && sizeof(TransientStats) == 812
     && sizeof(HighScoreTable) == 64000) ? 1 : -1];

// Fred, retail's 0x002fc050.
extern FrontendDatabase Fred;

// Fred as the byte image the card saves and bsetup.c's FRED_* offsets
// index.
uint8_t *fred_bytes(void);

// ---------------------------------------------------------------- the seams

// DataAudioOptionsScreen::InitWithDefaults (0x001ef1c8) on Fred+148, the
// jukebox's (jukebox.h); NULL leaves the bytes as they are.
extern void (*gFredAudioOptionsDefaultsFn)(uint8_t *ao);

// GetTranslatedString(int) (0x0021e560), as a NUL-terminated string; NULL,
// or a NULL answer, is the image's "NOT TRANSLATED PROPERLY".
extern const char *(*gFredTranslateFn)(int32_t id);

// IsCarUnlocked (0x0024b208): the task, event and points rewards, none of
// which is ported. NULL answers 0, locked, which is what a new database
// answers for every car the rewards hold.
extern int32_t (*gIsCarUnlockedFn)(int32_t carType, int32_t gameType);

// The calibration's start, gp-16896 and gp-16892: where the screen was
// when the calibration's defaults were taken.
extern int32_t DisplayCalibrationOriginalX;
extern int32_t DisplayCalibrationOriginalY;

// --------------------------------------------------------- the methods

// _GLOBAL_$I$Fred, 0x00187c58, sinit's [34]: FrontendDatabase's
// constructor (0x001836a0) on Fred. The audio list's 32 entries lose
// their first three bytes and the byte at 323 is cleared; the eight stats'
// Timers, both high score tables' Times and both settings' records are 0;
// every car is CAR_STATUS_HIDDEN with no skins and no dash, and every
// game mode's ride is type -1 with its four bytes 0.
void fred_static_init(void);

// InitFred, 0x00183820.
void init_fred(void);

// FrontendDatabase::InitWithDefaults, 0x00183830.
void fred_init_with_defaults(FrontendDatabase *f);

// FrontendDatabase::MakeChallengeCarsAvailable, 0x00183af8. Each valid car
// type's status for both players from its lock statuses and
// IsCarUnlocked, with all its skins and no dash. You're The Cop (game
// type 7) gives the first player only the cops and the second only the
// rest; any other game gives both players the same.
void fred_make_challenge_cars_available(FrontendDatabase *f);

// FrontendPlayerInfo::SetCharacterInfo(int), 0x00187ce0, and the pointer
// one under it (0x00187d10): GetCharacterInfo(i), copied in when there is
// one.
void fpi_set_character_info_index(FrontendPlayerInfo *p, int32_t i);
void fpi_set_character_info(FrontendPlayerInfo *p, const CharacterInfo *ci);

// FrontendPlayerInfo::SetCarAvailability, 0x001878e0. Skin -1 offers every
// skin the car has (0x00187b08), any other that one alone.
void fpi_set_car_availability(FrontendPlayerInfo *p, int32_t status,
                              int32_t type, int32_t skin, int32_t dash);

// FrontendPlayerInfo::GetCarStatus, 0x00187958: the word at 24 x `type`
// in the record, the car's nStatus, with no range test. StartQuickRace
// asks it of a type of -1 when GenerateRandomRideInfo finds no car, and
// reads the 24 bytes before the record, as the image does.
int32_t fpi_get_car_status(const FrontendPlayerInfo *p, int32_t type);

// FrontendPlayerInfo::AssignCarOfType, 0x00187a68, through BuildRideInfo
// (0x001879b8): the mode's ride is the car with `skin` if the car offers
// it, else its first skin, and the dash only if asked for, offered and
// the car has one.
void fpi_assign_car_of_type(FrontendPlayerInfo *p, int32_t mode,
                            int32_t type, uint32_t skin, int32_t dash);

// FrontendPlayerInfo::SetDefaultCarType, 0x00187a78: every game mode's.
void fpi_set_default_car_type(FrontendPlayerInfo *p, int32_t type,
                              uint32_t skin, int32_t dash);

// HighScoreTable::InitStatsTables, 0x00186708. The first sixteen tracks
// that are their own high score track are numbered 0 .. 15 (any after
// them 0), the rest take their twin's; then every time is 0x7fffffff,
// with the names and cars 0.
void high_score_table_init_stats_tables(HighScoreTable *t);

// The setup screens' data defaults InitWithDefaults calls, each on its own
// block: DataSingleRaceSetup (0x001b8af0), DataFreeRunSetup (0x001b8ca0),
// the race knockout's (0x001b9218), the lap knockout's (0x001b8f38),
// DataSelectTrackScreen (0x0019dd78, track 11's twin and time of day),
// DataEventSelectScreen (0x001f5ce8) and the display calibration's
// (0x001f4ad8).
void data_single_race_setup_defaults(int32_t *d);
void data_free_run_setup_defaults(int32_t *d);
void data_race_knockout_setup_defaults(int32_t *d);
void data_lap_knockout_setup_defaults(int32_t *d);
void data_select_track_screen_defaults(int32_t *d);
void data_event_select_screen_defaults(int32_t *d);
void data_display_calibration_defaults(int32_t *d);

#endif
