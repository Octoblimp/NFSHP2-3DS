// replay -- the head of ReplayManager, which GenerateJoyEvents reads, and
// the global that points at it.
//
// ReplayManager is 12468 bytes and not ported; these are its first 72,
// named from the .mdebug entry. The replay records the frame's queued
// events on the way in and, when it is playing back, replaces them, so the
// joystick layer needs its flags and its two integer accessors and nothing
// else. pReplayManager is NULL until a replay exists, and in the port
// nothing creates one yet.

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
    // ... to 12468.
} ReplayManager;

typedef char replaymanager_layout_check[
    (offsetof(ReplayManager, FancyReplayInProgress) == 28
     && offsetof(ReplayManager, FancyJoyEventTable) == 40) ? 1 : -1];

extern ReplayManager *pReplayManager;   // gp-23008, 0x00323210

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

#endif
