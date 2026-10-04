// nfsrewards -- the cars Challenge Mode and You're The Cop unlock: retail's
// two reward tables and what car select says about a locked car (step 16,
// SC-1).
//
// What is ported, retail's addresses (SLES_507.31):
//
//   NFSTasks                   0x0031cfc0  ten tasks, a car each
//   NFSPointsRewardsArray      0x0031d1f0  eighteen points totals, a car each
//   GetTaskParametersForCar    0x0024ae58  and IsCarATaskReward 0x0024aeb0
//   GetPointsRewardForCar      0x0024b0c0  and IsCarAPointsReward 0x0024b100
//   the points' text           0x0024b468  no name in the image
//   FormatUnlockBlurbForCar    0x0024b548
//
// The event trees (World Racing's championship and Hot Pursuit's) are not
// ported. The blurb asks for a car's event through a hook; with none, a car
// is no event's reward, and the blurb goes on to the points.

#ifndef NFSREWARDS_H
#define NFSREWARDS_H

#include <stdint.h>

#define NFS_NUM_TASKS           10
#define NFS_NUM_POINTS_REWARDS  18

// NFSTaskParameters (56 bytes, docs/mdebug_structs.txt). UnlockedInGameType
// is the GameTypes value the car is unlocked for, -1 for any.
typedef struct NFSTaskParameters {
    int32_t TaskNumber;             //  0
    float   MinDamage;              //  4
    int32_t NumPlayers;             //  8
    int32_t GameType;               // 12
    int32_t NumOpponents;           // 16
    int32_t NumLaps;                // 20
    int32_t SkillLevel;             // 24
    int32_t NumLapsToLead;          // 28
    int32_t Cops;                   // 32
    int32_t UnlockedInGameType;     // 36
    int32_t Reward;                 // 40  CarType
    int32_t CarSelectUnlockBlurb;   // 44  a LanguageID
    int32_t EndOfRaceUnlocked;      // 48  a LanguageID
    int32_t IndexIntoFredTaskState; // 52
} NFSTaskParameters;

// NFSPointsRewards (12 bytes).
typedef struct NFSPointsRewards {
    int32_t RequiredPoints;         //  0
    int32_t Reward;                 //  4  CarType
    int32_t IndexIntoFred;          //  8
} NFSPointsRewards;

extern const NFSTaskParameters NFSTasks[NFS_NUM_TASKS];
extern const NFSPointsRewards  NFSPointsRewardsArray[NFS_NUM_POINTS_REWARDS];

// The first task whose reward is `carType` in `gameType`, a task for any
// game type matching every one; NULL when there is none.
const NFSTaskParameters* nfs_get_task_parameters_for_car(int32_t carType,
                                                         int32_t gameType);
int nfs_is_car_a_task_reward(int32_t carType, int32_t gameType);

const NFSPointsRewards* nfs_get_points_reward_for_car(int32_t carType);
int nfs_is_car_a_points_reward(int32_t carType);

// 0x0024b468: a points total with its thousands split, by `language`'s
// separator -- a space in French (1), a dot in German (2), a comma in the
// rest: 1,500,000 or 50,000 or 750 or 0.
void nfs_format_points(char* out, int len, int32_t points, int32_t language);

typedef struct NFSRewardHooks {
    void* user;
    // GetTranslatedString(int); NULL or a missing row reads as "".
    const char* (*translate)(void* user, int32_t id);
    // TheLanguageManager's CurrLanguage.
    int32_t (*language)(void* user);
    // IsCarAnEventReward and FindEventThatCarIsARewardFor (0x001ff8b8,
    // 0x001ff9d8), over the event trees: nonzero when `carType` is an
    // event's reward, with the tree's type (0 the championship, 1 Hot
    // Pursuit) and the event's number.
    int (*findEventForCar)(void* user, int32_t carType, int32_t* treeType,
                           int32_t* eventNumber);
} NFSRewardHooks;

// FormatUnlockBlurbForCar (0x0024b548): how `carType` is unlocked, into
// `buf`. `flag` is the unlock box's last argument; a You're The Cop car that
// is no task's reward says so only when it is 0.
void nfs_format_unlock_blurb_for_car(const NFSRewardHooks* h, char* buf,
                                     int len, int32_t carType,
                                     int32_t gameType, int flag);

#endif
