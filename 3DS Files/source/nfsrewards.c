// nfsrewards -- the reward tables and car select's unlock blurb. See
// nfsrewards.h.

#include "nfsrewards.h"

#include <stddef.h>

#include "bprintf.h"

// NFSTasks (0x0031cfc0), word for word.
const NFSTaskParameters NFSTasks[NFS_NUM_TASKS] = {
    {  1,  0.0f, 1, 3, -1,  4, 1, -1, -1, -1, 16, 49101, 0x000ea601, 0 },
    {  2,  0.0f, 1, 3, -1,  8, 1, -1, -1, -1,  5, 49102, 0x000ea602, 1 },
    {  3, -1.0f, 1, 3,  3,  2, 1,  2,  1,  7, 31, 49103, 0x000ea603, 2 },
    {  4, -1.0f, 1, 3,  7,  2, 1,  2,  0, -1, 44, 49104, 0x000ea604, 3 },
    {  5, -1.0f, 1, 3,  3,  4, 1,  4,  1,  7, 34, 49105, 0x000ea605, 4 },
    {  6, -1.0f, 1, 3,  7,  4, 1,  4,  0, -1, 36, 49106, 0x000ea606, 5 },
    {  7, -1.0f, 1, 3, -1,  8, 1,  8,  0, -1, 24, 49107, 0x000ea607, 6 },
    {  8, -1.0f, 1, 4, -1, -1, 1, -1,  1,  7, 32, 49108, 0x000ea608, 7 },
    {  9, -1.0f, 1, 4, -1, -1, 1, -1,  0, -1, 14, 49109, 0x000ea609, 8 },
    { 10, -1.0f, 1, 5, -1, -1, 1, -1,  1,  7, 33, 49110, 0x000ea60a, 9 },
};

// NFSPointsRewardsArray (0x0031d1f0).
const NFSPointsRewards NFSPointsRewardsArray[NFS_NUM_POINTS_REWARDS] = {
    {   50000, 15,  0 }, {  100000, 20,  1 }, {  150000, 28,  2 },
    {  200000, 25,  3 }, {  250000, 42,  4 }, {  300000, 23,  5 },
    {  400000, 30,  6 }, {  500000, 12,  7 }, {  750000, 40,  8 },
    { 1000000, 26,  9 }, { 1500000,  3, 10 }, { 2000000, 46, 11 },
    { 2500000,  1, 12 }, { 3000000, 48, 13 }, { 3500000, 18, 14 },
    { 4000000,  8, 15 }, { 4500000,  6, 16 }, { 5000000, 10, 17 },
};

// LanguageIDs FormatUnlockBlurbForCar formats with.
#define LANG_POINTS_BLURB        0xbfb8   // "Accumulate %s NFS Points ..."
#define LANG_CHAMPIONSHIP_BLURB  0xc030   // "Complete Championship Event %d ..."
#define LANG_HOT_PURSUIT_BLURB   0xc031   // "Complete Hot Pursuit Event %d ..."

#define GAME_TYPE_BE_A_COP 7

// GetTaskParametersForCar (0x0024ae58).
const NFSTaskParameters* nfs_get_task_parameters_for_car(int32_t carType,
                                                         int32_t gameType)
{
    for (int i = 0; i < NFS_NUM_TASKS; i++) {
        const NFSTaskParameters* t = &NFSTasks[i];
        if (t->UnlockedInGameType != -1 && t->UnlockedInGameType != gameType)
            continue;
        if (t->Reward == carType) return t;
    }
    return NULL;
}

int nfs_is_car_a_task_reward(int32_t carType, int32_t gameType)
{
    return nfs_get_task_parameters_for_car(carType, gameType) != NULL;
}

// GetPointsRewardForCar (0x0024b0c0).
const NFSPointsRewards* nfs_get_points_reward_for_car(int32_t carType)
{
    for (int i = 0; i < NFS_NUM_POINTS_REWARDS; i++)
        if (NFSPointsRewardsArray[i].Reward == carType)
            return &NFSPointsRewardsArray[i];
    return NULL;
}

int nfs_is_car_a_points_reward(int32_t carType)
{
    return nfs_get_points_reward_for_car(carType) != NULL;
}

// GetCarTypeForPointsReward (0x0024b178).
int32_t nfs_get_car_type_for_points_reward(int32_t index)
{
    for (int i = 0; i < NFS_NUM_POINTS_REWARDS; i++)
        if (NFSPointsRewardsArray[i].IndexIntoFred == index)
            return NFSPointsRewardsArray[i].Reward;
    return -1;
}

// 0x0024b468. The separators are the strings at 0x00331e70 (","),
// 0x00331e78 (" ") and 0x00331e80 ("."); the millions are what is left of
// a thousand thousands, as the console's divides leave it.
void nfs_format_points(char* out, int len, int32_t points, int32_t language)
{
    const char* sep = ",";
    int32_t     units, thousands, millions;

    if (language == 1) sep = " ";
    else if (language == 2) sep = ".";
    units     = points % 1000;
    thousands = (points / 1000) % 1000;
    millions  = (points / 1000000) % 1000;
    if (millions != 0)
        b_snprintf(out, (size_t)len, "%d%s%03d%s%03d", (int)millions, sep,
                   (int)thousands, sep, (int)units);
    else if (thousands != 0)
        b_snprintf(out, (size_t)len, "%d%s%03d", (int)thousands, sep,
                   (int)units);
    else if (units != 0)
        b_snprintf(out, (size_t)len, "%d", (int)units);
    else
        b_snprintf(out, (size_t)len, "0");
}

static const char* translate(const NFSRewardHooks* h, int32_t id)
{
    const char* s = h && h->translate ? h->translate(h->user, id) : NULL;
    return s ? s : "";
}

// FormatUnlockBlurbForCar (0x0024b548). The task's blurb goes through
// bSPrintf as the format, with nothing to fill in.
void nfs_format_unlock_blurb_for_car(const NFSRewardHooks* h, char* buf,
                                     int len, int32_t carType,
                                     int32_t gameType, int flag)
{
    const NFSTaskParameters* task;
    const NFSPointsRewards*  reward;
    int32_t                  treeType = 0, eventNumber = 0;

    task = nfs_get_task_parameters_for_car(carType, gameType);
    if (task) {
        b_snprintf(buf, (size_t)len, translate(h, task->CarSelectUnlockBlurb));
        return;
    }
    if (gameType == GAME_TYPE_BE_A_COP && !flag) {
        b_snprintf(buf, (size_t)len,
                   "Be A cop Player 1 -- should not see this message");
        return;
    }
    if (h && h->findEventForCar
        && h->findEventForCar(h->user, carType, &treeType, &eventNumber)) {
        const char* fmt = "Unknown event tree type";
        if (treeType == 0) fmt = translate(h, LANG_CHAMPIONSHIP_BLURB);
        else if (treeType == 1) fmt = translate(h, LANG_HOT_PURSUIT_BLURB);
        // The event's number is a signed byte (its +40).
        b_snprintf(buf, (size_t)len, fmt, (int)(int8_t)eventNumber);
        return;
    }
    reward = nfs_get_points_reward_for_car(carType);
    if (reward) {
        char points[128];
        // The format is translated before the points are written, as
        // retail orders the two.
        const char* fmt = translate(h, LANG_POINTS_BLURB);
        nfs_format_points(points, (int)sizeof(points), reward->RequiredPoints,
                          h && h->language ? h->language(h->user) : 0);
        b_snprintf(buf, (size_t)len, fmt, points);
        return;
    }
    b_snprintf(buf, (size_t)len, "This car should be unlocked");
}
