// replay -- the head of ReplayManager, which GenerateJoyEvents reads, and
// the global that points at it.
//
// ReplayManager is 12468 bytes and not ported; these are its first 116,
// named from the .mdebug entry. The replay records the frame's queued
// events on the way in and, when it is playing back, replaces them, so the
// joystick layer needs its flags and its two integer accessors and nothing
// else. Car's reset needs the snapshot list as well, for
// RegisterInterestingEvent. pReplayManager is NULL until a replay exists,
// and in the port nothing creates one yet.

#ifndef REPLAY_H
#define REPLAY_H

#include <stddef.h>
#include <stdint.h>

typedef struct ReplayManager {
    int32_t ReplayingFlag;           // 0
    int32_t CapturingFlag;           // 4
    int32_t RemoveDataError;         // 8
    int32_t PausedFlag;              // 12
    int32_t SlowMotionFlag;          // 16
    int32_t ReplayPausedThisFrame;   // 20
    int32_t NextFancyDebugTime;      // 24, a Timer
    int32_t FancyReplayInProgress;   // 28
    int32_t FancyJoyEventNumber;     // 32
    int32_t NumFancyJoyEvents;       // 36
    uint8_t FancyJoyEventTable[32];  // 40
    int32_t NextInstantReplaySnapshotTime; // 72, a Timer
    int32_t BeginCapturingLoopCount; // 76
    int32_t EndCapturingLoopCount;   // 80
    int32_t FinishedAllCapturing;    // 84
    int32_t BeginningOfTime;         // 88, a Timer
    int32_t EndOfTime;               // 92, a Timer
    uint32_t pRepeat;                // 96
    // Two bTList<ReplaySnapshot>s: each is a head bNode, Next and Prev as
    // p32 handles. An empty list points at itself.
    uint32_t FreeReplaySnapshotList[2]; // 100
    uint32_t ReplaySnapshotList[2];  // 108
    // ... to 12468.
} ReplayManager;

typedef char replaymanager_layout_check[
    (offsetof(ReplayManager, FancyReplayInProgress) == 28
     && offsetof(ReplayManager, FancyJoyEventTable) == 40
     && offsetof(ReplayManager, pRepeat) == 96
     && offsetof(ReplayManager, ReplaySnapshotList) == 108) ? 1 : -1];

// The head of a ReplaySnapshot, 36180 bytes and not ported: its list node,
// its name, and the total that RegisterInterestingEvent adds to.
typedef struct ReplaySnapshot {
    uint32_t pNext;                  // 0    bNode, a p32 handle
    uint32_t pPrev;                  // 4
    char     Name[32];               // 8
    uint8_t  Unported40[288];        // 40   Time .. SectionInfo
    float    TotalInterestingValue;  // 328
    // ... to 36180.
} ReplaySnapshot;

typedef char replaysnapshot_layout_check[
    (offsetof(ReplaySnapshot, Name) == 8
     && offsetof(ReplaySnapshot, TotalInterestingValue) == 328) ? 1 : -1];

// The demo's gp-23008 (0x00323210); retail's gp-22440 (0x00330148), which
// RaceCoordinator::InitForRace sets to a new 20664-byte ReplayManager.
extern ReplayManager *pReplayManager;

// ReplayManager::GetData (0x0013cac0) and AddData (0x0013cb58). NULL
// aborts: a caller that sets pReplayManager supplies both.
typedef int32_t (*ReplayGetDataFn)(ReplayManager *rm, int32_t bits,
                                   int32_t channel);
typedef void    (*ReplayAddDataFn)(ReplayManager *rm, int32_t value,
                                   int32_t bits, int32_t channel);
extern ReplayGetDataFn gReplayManagerGetData;
extern ReplayAddDataFn gReplayManagerAddData;

int32_t ReplayManager_GetData(ReplayManager *rm, int32_t bits,
                              int32_t channel);
void    ReplayManager_AddData(ReplayManager *rm, int32_t value, int32_t bits,
                              int32_t channel);

// 0x0013c290. While capturing, adds `value` to the total of every snapshot
// named INSTANT_REPLAY. `description` is not read.
void ReplayManager_RegisterInterestingEvent(ReplayManager *rm, float value,
                                            const char *description);

// 0x0013c310. RegisterInterestingEvent(-99, "Invalidate").
void ReplayManager_InvalidateInterestingEvents(ReplayManager *rm);

#endif
