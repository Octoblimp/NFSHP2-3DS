// fredend -- FrontendDatabase's end of a race: what Fred keeps of a race
// when it is over, quit or restarted, and the task and points rewards it
// earns (RE-2a).
//
// What is ported, retail's addresses (SLES_507.31):
//
//   TransientStatsElement::Construct    0x00186e08   488 bytes
//   TransientStats::Construct           0x00186ff0   144 bytes
//   TransientStats::GetDriver           0x00187080    76 bytes
//   GetOptionsSetFromRace               0x001870d0   680 bytes
//   FigureOutBonusPoints                0x00187378   188 bytes
//   AwardPointsToPlayer                 0x00187438   220 bytes
//   CheckForAbortion                    0x00187518    72 bytes
//   RaceWasAborted                      0x00187560    16 bytes
//   TheRaceIsLeaving                    0x00187570    48 bytes
//   TheRaceIsOver                       0x001875a0   544 bytes
//   TheRaceWasQuit                      0x00187800   124 bytes
//   TheRaceWasRestarted                 0x00187880    48 bytes
//   NFSTaskParameters::CheckForCompletion 0x0024ab90 508 bytes
//   GetTaskRewardList                   0x0024ad90   200 bytes
//   NFSPointsRewards::CheckForCompletion 0x0024afe8   16 bytes
//   GetPointsRewardList                 0x0024aff8   200 bytes
//   CheckForTaskAndPointRewards         0x0024b7b0   356 bytes
//   TaskRewardsIsCarUnlocked            0x0024aed0   108 bytes
//   PointsRewardsIsCarUnlocked          0x0024b120    88 bytes
//   IsCarUnlocked                       0x0024b208   148 bytes
//
// The race coordinator calls CheckForAbortion and then TheRaceIsOver when
// every player has finished (rcstates.c), TheRaceWasQuit when the race is
// quit and TheRaceWasRestarted when it starts again (rcpost.c). The end
// of the race's screens (endgame.c) read what TheRaceIsOver leaves:
// TransientStats' rows and the two rewards' words. IsCarUnlocked is
// fred.h's gIsCarUnlockedFn, which the car lists and the end of the race
// ask.
//
// HighScoreTable::MaybeRecordHighScore (0x00186af0) is highscore.c's
// (RE-3), and the race events are step 16's: both go through the seams
// at the bottom. docs/formats/race-over.md has the decode.

#ifndef FREDEND_H
#define FREDEND_H

#include <stdint.h>

#include "fred.h"
#include "nfsrewards.h"
#include "race.h"

struct RacingCar;

// ------------------------------------------------------- TransientStats

// 0x00186e08: one car's row. FinishPosition is RacePosition, the drive
// number the car's DriverNumber, the race and best lap times and the
// speeds the RacingCar's. An AI car's top speed loses bRandom(1.0) of
// 5% on bDefaultSeed, capped at its type's SpeedLimiter. With a cop
// manager, the car's tickets, and in Be A Cop the first player's time
// at +48 and a non-player's points and mode cleared at once. A player's
// row has its score, its accumulated points, its finish bonus and its
// DrivingStyle; anyone else's 0, 0, 0 and -1. LapTimes[1 .. n] are the
// car's, n its NumLapsCompleted up to 10, which New96 keeps.
void transient_stats_element_construct(TransientStatsElement *e,
                                       struct RacingCar *rc);

// 0x00186ff0: NumStats 0, then a row for each of the race's racing cars.
// The rewards' words are not touched; CheckForTaskAndPointRewards sets
// them.
void transient_stats_construct(TransientStats *ts, Race *r);

// 0x00187080: the row whose UniqueDriveNumber is `driver`, NULL if none.
TransientStatsElement *transient_stats_get_driver(TransientStats *ts,
                                                  int32_t driver);

// ------------------------------------------------- the frontend database

// 0x001870d0: each player's settings back into Fred's FrontendPlayers and
// TheRaceParameters, the damage switch into the game type's setup data
// (3 SingleRace, 4 RaceKnockout, 5 LapKnockout, 6 FreeRun, 7 BeTheCop),
// the display settings into Fred, and the audio options from the sound
// (jukebox.h's SetAudioDataFromSound, through the seam).
void fred_get_options_set_from_race(FrontendDatabase *f);

// 0x00187378: none in Be A Cop or for a car that is not the first
// player's; otherwise GetFinishBonus for its RacePosition when the field
// earns one: never alone, first of two, the top two of three, any place
// of more.
int32_t fred_figure_out_bonus_points(FrontendDatabase *f, Race *r,
                                     struct RacingCar *rc);

// 0x00187438: a player car's score, finish bonus and, in Be A Cop, the
// cop manager's time in whole seconds times 100, onto its player's
// AccumulatedPoints.
void fred_award_points_to_player(FrontendDatabase *f, Race *r,
                                 struct RacingCar *rc);

// 0x00187518: bRaceWasAborted, 1 when a player has not finished.
void fred_check_for_abortion(FrontendDatabase *f);

// 0x00187560.
int32_t fred_race_was_aborted(const FrontendDatabase *f);

// 0x00187570: the race event's results discarded, when there is one.
void fred_the_race_is_leaving(FrontendDatabase *f);

// 0x001875a0: the options kept; points awarded with Fred's NumPlayerCars
// 1; the high scores offered, the better lap first with two players;
// TransientStats built; the race event's results posted; the rewards
// checked.
void fred_the_race_is_over(FrontendDatabase *f, Race *r);

// 0x00187800: abortion checked and the options kept; with a race event,
// the race finished for everyone if every player is through, its results
// posted and its state kept.
void fred_the_race_was_quit(FrontendDatabase *f);

// 0x00187880: the race event's results cycled, when there is one.
void fred_the_race_was_restarted(FrontendDatabase *f);

// ----------------------------------------------------------- the rewards

// 0x0024ab90: whether the race met the task. Each of NumPlayers,
// GameType, NumOpponents, NumLaps, SkillLevel, NumLapsToLead and Cops is
// -1 for any; a RaceKnockout alone with under three cars, and a
// LapKnockout, must be won. MinDamage, when set, asks only that the
// player never hit anything (New2540): retail works out the car's
// visible damage and drops it.
int nfs_task_check_for_completion(const NFSTaskParameters *t,
                                  struct RacingCar *rc);

// 0x0024ad90: the tasks completed and not yet earned, into `list`.
int32_t nfs_get_task_reward_list(const NFSTaskParameters **list,
                                 int32_t *n, struct RacingCar *rc);

// 0x0024afe8.
static inline int nfs_points_reward_check_for_completion(
    const NFSPointsRewards *p, int32_t points)
{
    return !(points < p->RequiredPoints);
}

// 0x0024aff8: the points rewards reached and not yet earned.
int32_t nfs_get_points_reward_list(const NFSPointsRewards **list,
                                   int32_t *n, int32_t points);

// 0x0024b7b0: both rewards' words -1; then, with one player, its car's
// new task rewards (not in a GameType 2 race) and the first player's new
// points rewards are marked in Fred's RewardStates, the last of each
// kept in the words.
void nfs_check_for_task_and_point_rewards(Race *r);

// 0x0024aed0: the first task whose reward is `carType` in `gameType` (or
// in any), earned or not; 0 when no task has it.
int32_t nfs_task_rewards_is_car_unlocked(int32_t carType, int32_t gameType);

// 0x0024b120: the first points reward that is `carType`, earned or not.
int32_t nfs_points_rewards_is_car_unlocked(int32_t carType);

// 0x0024b208: a task's reward by its task; in You're The Cop (7) nothing
// else; an event's reward by its event tree (the seams below); a points
// reward by its points. Any other car is locked.
int32_t nfs_is_car_unlocked(int32_t carType, int32_t gameType);

// ------------------------------------------------------------- the seams

// The event trees' IsCarAnEventReward (0x001ff8b8) and
// EventTreeIsCarUnlocked (0x001ff918), step 16's. NULL answers 0.
extern int32_t (*gIsCarAnEventRewardFn)(int32_t carType);
extern int32_t (*gEventTreeIsCarUnlockedFn)(int32_t carType);

// HighScoreTable::MaybeRecordHighScore (0x00186af0), highscore.c's.
// Its answer is dropped.
extern int32_t (*gHighScoreMaybeRecordFn)(HighScoreTable *t, Race *r,
                                          struct RacingCar *rc);

// SetAudioDataFromSound (0x001eef60) on Fred's AudioOptionsScreenData,
// with 0 (jukebox.h).
extern void (*gSetAudioDataFromSoundFn)(uint8_t *ao, int32_t a);

// TheRaceEvent's (0x0031b600) PostResults (0x002018f8),
// MaybeDiscardResults (0x00201a80) and CycleResults (0x00201ac0). The
// state kept (0x00201fb0) is endgame.h's gRaceEventKeepStateFn.
extern void (*gRaceEventPostResultsFn)(void);
extern void (*gRaceEventMaybeDiscardResultsFn)(void);
extern void (*gRaceEventCycleResultsFn)(void);

#endif
