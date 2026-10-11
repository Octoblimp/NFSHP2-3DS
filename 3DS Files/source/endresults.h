// endresults -- the results a finished race shows: the Race Results screen
// with its stats slideshow and points tally, and the Points Rewards and
// Task Rewards screens. Each is one of endgame.h's classes, made through
// gEndGameScreenCtorFns when its screen comes up.
//
// Race Results (RACE_RESULTS, 60 bytes) lists every car of
// TransientStats in finishing order: its place, its driver (a player's
// name in the player's colour), its car and, in the BEHIND_n column, one
// stat at a time. The column title says which. Every 6 seconds the
// column fades out over half a second and the next stat fades in over
// the next half second. LEFT and RIGHT step through the stats by hand.
// The stats, each only when it applies:
//
//   Time        the winner's race time and everyone else's gap to it
//               ("Arrested" for a car the cops caught, "Eliminated" for
//               every car but the winner of a RaceType 3 race)
//   Points      a tournament's points for each place, 10 6 4 3 2 1
//   Tickets     when the race had cops
//   Best Lap    a lapped race of more than one lap
//   Avg. Speed  in mph or km/h, by the display options' Units
//   Top Speed   the same
//
// Under the list, a one-player race not of GameType 6 shows the points
// tally. "Points Earned:", the bonus for the place, if there is one, and
// "Total Points Earned:" take turns on one line. Each is shown for 5
// seconds and fades out over half a second, and the next comes up at
// full strength. The player's points total stays beside it. A
// two-player race shows each player's points for the race instead.
//
// Points Rewards and Task Rewards (8 bytes each) word-wrap the reward's
// blurb into the shared reward screen, title it, and count the cars
// available: Challenge Mode cars, or You're The Cop cars for a task
// reward unlocked in GameType 7.
//
// What is ported, retail's addresses (SLES_507.31):
//
//   SprintfAndHash's timer twin: a Timer printed  0x001dc500
//   Points Rewards: the blurb's car count         0x001de3a8 .. 0x001de550
//   PointsRewardScreen::PointsRewardScreen        0x001de568
//   TaskRewardScreen::TaskRewardScreen            0x001de6a8
//   the slideshow's column tests                  0x001df3a0 .. 0x001df408
//   tSlideshowStats::tSlideshowStats              0x001df410
//   tSlideshowStats::~tSlideshowStats             0x001df918
//   tSlideshowStats::SetAlphaScale                0x001df970
//   tSlideshowStats::SetupDataset                 0x001dfa00
//   tSlideshowStats::Tick                         0x001dfc28
//   tSlideshowStats::ChangeStats                  0x001dfd40
//   the points tally (no name in the image)       0x001dfdb8 .. 0x001dffe4,
//                                                 0x001e2410 .. 0x001e24e8,
//                                                 0x001e25d0
//   RaceResultsScreen::RaceResultsScreen          0x001dffe8
//   EndGameMenusBase::ShowPointsResults           0x001e0430
//   RaceResultsScreen::Scroll                     0x001e0838
//   RaceResultsScreen::Tick                       0x001e0868
//   bTList<tStatsColumn>::~bTList                 0x001e2180
//   RaceResultsScreen::~RaceResultsScreen         0x001e23b8
//   GetLanguageIDForTaskReward, and the task's    0x0024af40 .. 0x0024afb0
//   reward and game type by its number
//   GetNumPointsRewardsEarned                     0x0024b1b0
//   the car counts                                0x0024b2a0 .. 0x0024b430
//   EventTournamentState::GetPointsForFinishPos   0x00200788
//
// docs/formats/race-results.md has the decode.

#ifndef ENDRESULTS_H
#define ENDRESULTS_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "endgame.h"
#include "timer.h"

// RACE_RESULTS' objects. Each row n (1 to 8) has POS_n, NAME_n, TYPE_n,
// TIME_n and BEHIND_n, by SprintfAndHash.
#define RACE_RESULTS_OBJ_TRACK_NAME   0xf601f2d4u
#define RACE_RESULTS_OBJ_RACE_NUMBER  0xd0ced2e2u
#define RACE_RESULTS_OBJ_TITLE        0x3288a48cu
#define RACE_RESULTS_OBJ_STAT_TITLE   0xee0b838au
#define RACE_RESULTS_ROWS             8
// The points tally: the panel, the line that takes turns (and fades),
// its label and value, the second player's label, and the total (or the
// second player's points).
#define RACE_RESULTS_GROUP_POINTS     0x26c0a2e8u
#define RACE_RESULTS_GROUP_TALLY      0xab0f6086u
#define RACE_RESULTS_OBJ_POINTS_LABEL 0x68a2d5d1u
#define RACE_RESULTS_OBJ_POINTS       0x123d12feu
#define RACE_RESULTS_OBJ_P2_LABEL     0x896f342eu
#define RACE_RESULTS_OBJ_TOTAL        0x27aa4effu

// The reward screen's objects: the blurb's group, the title, and the
// car count's group.
#define END_REWARD_GROUP_BLURB        0x461d42d0u
#define END_REWARD_OBJ_TITLE          0x4703a605u
#define END_REWARD_GROUP_COUNT        0x1a190ea0u

// The strings, FE_ENGLISH's.
#define RR_LANG_EVENT_RESULTS   0x4bcea   // "Event %d Results"
#define RR_LANG_RACE_RESULTS    0x497ca   // "Race Results"
#define RR_LANG_TIME            0x4bceb   // "Time"
#define RR_LANG_POINTS          0x4bce4   // "Points"
#define RR_LANG_TICKETS         0x4bce5   // "Tickets"
#define RR_LANG_BEST_LAP        0x4bce6   // "Best Lap"
#define RR_LANG_AVG_SPEED       0x4bce7   // "Avg. Speed"
#define RR_LANG_TOP_SPEED       0x4bce8   // "Top Speed"
#define RR_LANG_ELIMINATED      0x3ad69   // "Eliminated"
#define RR_LANG_ARRESTED        0x49447   // "Arrested"
#define RR_LANG_POINTS_EARNED   0xef420   // "Points Earned:"
#define RR_LANG_1ST_BONUS       0x495ee   // "1st Place Bonus:"
#define RR_LANG_2ND_BONUS       0x495ef   // "2nd Place Bonus:"
#define RR_LANG_3RD_BONUS       0x495f0   // "3rd Place Bonus:"
#define RR_LANG_NO_BONUS        0x495f5   // "No bonus"
#define RR_LANG_TOTAL_EARNED    0xef422   // "Total Points Earned:"
#define RR_LANG_P1_POINTS       0xef423   // "Player 1 Points:"
#define RR_LANG_P2_POINTS       0xef424   // "Player 2 Points:"
#define END_REWARD_LANG_POINTS_TITLE  0xde4a7  // "POINTS REWARD"
#define END_REWARD_LANG_TASK_TITLE    0xde4a8  // "TASK REWARD"
// "You've earned enough points@to unlock the@%s@in all Challenge Modes!
// @ @Keep playing to unlock more cars!", and without the last line once
// the last points reward is earned.
#define END_REWARD_LANG_POINTS_BLURB      0xe7ef0
#define END_REWARD_LANG_POINTS_BLURB_LAST 0xe7ef1
// "You have %d out of %d cars@available in all Challenge Modes." and
// "... in You're The Cop Mode."
#define END_REWARD_LANG_COUNT             0xea7f4
#define END_REWARD_LANG_COUNT_COP         0xea7f5

// ------------------------------------------------------------ the slideshow

// A stat's kind, tStatsColumn's Data[].Type.
#define STATS_DATA_INT          0   // "%d"
#define STATS_DATA_FLOAT        1   // "%3.f"
#define STATS_DATA_TIMER        2   // a time, blank when unset
#define STATS_DATA_LANGUAGE     3   // a LanguageID, blank for 0
#define STATS_DATA_TIMER_BEHIND 4   // a gap, with its '-'; blank when
                                    // 0x7fffffff

// One stat's row value: an int, a float, a Timer or a LanguageID, by Type.
typedef struct tStatsDatum {
    union {
        int32_t Int;
        float   Float;
        Timer   Time;
    } Value;                       // 0
    int32_t Type;                  // 4  STATS_DATA_*
} tStatsDatum;                     // 8

// tStatsColumn, 76 bytes, bMalloc(76, "tStatsColumn", 0, 16): a stat's
// title and its value for each row. The rows past TransientStats' count
// are never written.
typedef struct tStatsColumn {
    bNode       Node;                         //  0
    int32_t     Title;                        //  8  a LanguageID
    tStatsDatum Data[RACE_RESULTS_ROWS];      // 12
} tStatsColumn;                               // 76

// tSlideshowStats, 24 bytes.
typedef struct tSlideshowStats {
    uint32_t      ScreenHash;     //  0
    bNode         Columns;        //  4  tStatsColumns
    int32_t       AnimTimer;      // 12  RealTimer when the fade began
    int32_t       Refresh;        // 16  the next column is up; the
                                  //     constructor leaves it unwritten
    tStatsColumn *CurrentColumn;  // 20
} tSlideshowStats;                // 24

// ------------------------------------------------------------- the tally

// A line of the tally, 16 bytes, bMalloc(16, "tPointsThingy", 0, 16).
typedef struct tPointsThingy {
    bNode   Node;     //  0
    int32_t Label;    //  8  a LanguageID
    int32_t Points;   // 12
} tPointsThingy;      // 16

// The tally, 28 bytes. The constructor leaves Current unwritten; Start
// sets it.
typedef struct tPointsResults {
    uint32_t       ScreenHash;  //  0
    int32_t        Timer;       //  4  RealTimer when the line went up
    bNode          Lines;       //  8  tPointsThingys
    tPointsThingy *Current;     // 16
    float          TopLeftX;    // 20  the label's, never read
    float          TopLeftY;    // 24
} tPointsResults;               // 28

// ------------------------------------------------------------- the screens

// RaceResultsScreen, 60 bytes, bMalloc(60, "RaceResultsScreen", 0, 16).
typedef struct RaceResultsScreen {
    EndGameMenusBase Base;    //  0
    tSlideshowStats  Stats;   //  8
    tPointsResults   Points;  // 32
} RaceResultsScreen;          // 60

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char endresults_layout_check[
    (sizeof(tStatsDatum) == 8
     && offsetof(tStatsColumn, Title) == 8
     && offsetof(tStatsColumn, Data) == 12
     && sizeof(tStatsColumn) == 76
     && offsetof(tSlideshowStats, Columns) == 4
     && offsetof(tSlideshowStats, AnimTimer) == 12
     && offsetof(tSlideshowStats, CurrentColumn) == 20
     && sizeof(tSlideshowStats) == 24
     && sizeof(tPointsThingy) == 16
     && offsetof(tPointsResults, Lines) == 8
     && offsetof(tPointsResults, Current) == 16
     && sizeof(tPointsResults) == 28
     && offsetof(RaceResultsScreen, Stats) == 8
     && offsetof(RaceResultsScreen, Points) == 32
     && sizeof(RaceResultsScreen) == 60) ? 1 : -1];
#endif

extern const EndGameMenusVTable kRaceResultsVTable;   // 0x002b9058
extern const EndGameMenusVTable kTaskRewardsVTable;   // 0x002b90e8
extern const EndGameMenusVTable kPointsRewardsVTable; // 0x002b9118

// The constructors, gEndGameScreenCtorFns' shape; `data` is not read.
EndGameMenusBase *race_results_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data);
EndGameMenusBase *points_rewards_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data);
EndGameMenusBase *task_rewards_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data);

// Race Results' Scroll (LEFT a stat back, RIGHT one on), Tick (the
// slideshow, then the tally) and destructor.
void race_results_scroll(EndGameMenusBase *m, BScreenMessage msg,
                         BScreenCallbackData *data);
void race_results_tick(EndGameMenusBase *m, BScreenMessage msg,
                       BScreenCallbackData *data);
void race_results_destroy(EndGameMenusBase *m, int32_t flags);

// ShowPointsResults: the tally for one player, the two players' points
// for two, nothing more for any other count; the panel hidden for
// GameType 6. A base method in retail that only Race Results calls, so it
// takes the screen.
void race_results_show_points(RaceResultsScreen *s);

void slideshow_stats_construct(tSlideshowStats *s, uint32_t hash);
void slideshow_stats_destroy(tSlideshowStats *s, int32_t flags);
// Every BEHIND_n's alpha, (int)(f * 128).
void slideshow_stats_set_alpha_scale(tSlideshowStats *s, float f);
// `col` current, and its values and title shown.
void slideshow_stats_setup_dataset(tSlideshowStats *s, tStatsColumn *col);
void slideshow_stats_tick(tSlideshowStats *s);
// 1 the next column, -1 the one before, both round the ends; anything
// else the current one again. The fade starts over.
void slideshow_stats_change_stats(tSlideshowStats *s, int32_t dir);

void points_results_construct(tPointsResults *p, uint32_t hash);
void points_results_start(tPointsResults *p);
void points_results_tick(tPointsResults *p);
void points_results_destroy(tPointsResults *p, int32_t flags);

// 0x001dc500: `t` printed into `buf` by Timer::PrintToString with
// `flags`. Retail rounds a valid time to hundredths into a Timer it never
// reads; the port leaves that out. The Best Lap and Best Total screens
// (RE-3) print with it too.
void end_game_print_timer(char *buf, Timer t, int32_t flags);

// 0x001de4a0: "You have %d out of %d cars..." into the count group, for
// You're The Cop when `cop` is set. 0x001de550: the group emptied.
void end_reward_show_car_count(uint32_t hash, int32_t cop);
void end_reward_clear_car_count(uint32_t hash);

// The counts behind it. 0x001de3a8: Challenge Mode cars available -- the
// unlocked or never locked cars of both kinds (CarUsageType 0 and 1),
// the event rewards the race unlocked (RaceParameters.New784) and, for a
// race event's race, each car reward not yet taken that the event has
// earned. 0x0024b348: the cars of a CarUsageType. 0x0024b380: the cop
// cars available in You're The Cop. 0x0024b430: the cop cars.
int32_t end_reward_num_available_cars(void);
int32_t end_reward_num_cars_of_usage(int32_t usage);
int32_t end_reward_num_cop_cars_available(void);
int32_t end_reward_num_cop_cars(void);

// GetNumPointsRewardsEarned: how many of NFSPointsRewardsArray's rewards
// Fred has earned, whatever their order.
int32_t nfs_get_num_points_rewards_earned(void);
// GetLanguageIDForTaskReward: the end-of-race blurb of the task numbered
// `task`, 0 for none. 0x0024af78 and 0x0024afb0: its reward car and the
// game type it unlocks in, -1 for none.
int32_t nfs_get_language_id_for_task_reward(int32_t task);
int32_t nfs_get_reward_for_task(int32_t task);
int32_t nfs_get_unlocked_game_type_for_task(int32_t task);

// ---------------------------------------------------------------- seams
//
// Shared with other files: startrace.h's gStartRaceTranslateFn and
// gStartRaceTranslateStringFn (the two GetTranslatedStrings, as the
// grid's), fred.h's gIsCarUnlockedFn and cartypeinfo.h's gCurrLanguageFn.
// Each one below does nothing when NULL, and answers 0.

// RenderTextIntoGroup (0x00144ba0), which needs the flow (bpopup.h).
extern void (*gRenderTextIntoGroupFn)(uint32_t screen, uint32_t group,
                                      const char *str);
// The reward speech, RE-5's: RewardCarSpeech (0x00207488) for the car
// a reward unlocked, and PointsScreenSpeech (0x002075b0) with whether
// there was a bonus. The tally never reaches the second (see
// race_results_show_points).
extern void (*gRewardCarSpeechFn)(int32_t carType);
extern void (*gPointsScreenSpeechFn)(int32_t bonus);
// TheRaceEvent's rewards, step 16's: the first byte of reward `i` (0 for
// a car still to take) and 0x00200b30 on it with no state.
extern int32_t (*gRaceEventRewardTypeFn)(int32_t i);
extern int32_t (*gRaceEventRewardEarnedFn)(int32_t i);

#endif
