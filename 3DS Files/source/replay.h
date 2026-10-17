// replay -- the replay's ReplaySnapshot, the head of ReplayManager, and the
// global that points at it (TASKS 72).
//
// Retail's replay runs the race again: it restores a snapshot of every
// simulated object and steps the world on the recorded pad events and
// timesteps (brepeat.h). A snapshot is a memory image that each object's
// DoSnapshot moves its fields in and out of, through MoveData, in the same
// order every time.
//
// ReplayManager is 20664 bytes in retail and only its head is here, in
// retail's layout: retail added a word at +12 to the demo's. The joystick
// layer reads its flags and the fancy-joyevent table, Car's reset its
// snapshot list. pReplayManager is NULL until a replay exists, and in the
// port nothing creates one yet (72f).

#ifndef REPLAY_H
#define REPLAY_H

#include <stddef.h>
#include <stdint.h>

#include "brepeat.h"
#include "bvector.h"

typedef struct ReplayManager {
    int32_t ReplayingFlag;           // 0
    int32_t CapturingFlag;           // 4
    int32_t RemoveDataError;         // 8
    int32_t MuteHighlightSoundFlag;  // 12, new in retail; the name is ours
    int32_t PausedFlag;              // 16
    int32_t SlowMotionFlag;          // 20
    int32_t ReplayPausedThisFrame;   // 24
    int32_t NextFancyDebugTime;      // 28, a Timer
    int32_t FancyReplayInProgress;   // 32
    int32_t FancyJoyEventNumber;     // 36
    int32_t NumFancyJoyEvents;       // 40
    uint8_t FancyJoyEventTable[32];  // 44
    int32_t NextInstantReplaySnapshotTime; // 76, a Timer
    int32_t BeginCapturingLoopCount; // 80
    int32_t EndCapturingLoopCount;   // 84
    int32_t FinishedAllCapturing;    // 88
    int32_t BeginningOfTime;         // 92, a Timer
    int32_t EndOfTime;               // 96, a Timer
    uint32_t pRepeat;                // 100, a p32 handle to the bRepeat
    // Two bTList<ReplaySnapshot>s: each is a head bNode, Next and Prev as
    // p32 handles. An empty list points at itself.
    uint32_t FreeReplaySnapshotList[2]; // 104
    uint32_t ReplaySnapshotList[2];  // 112
    // ... to 20664.
} ReplayManager;

typedef char replaymanager_layout_check[
    (offsetof(ReplayManager, FancyReplayInProgress) == 32
     && offsetof(ReplayManager, FancyJoyEventTable) == 44
     && offsetof(ReplayManager, BeginningOfTime) == 92
     && offsetof(ReplayManager, pRepeat) == 100
     && offsetof(ReplayManager, ReplaySnapshotList) == 112) ? 1 : -1];

// ReplaySnapshotSectionInfo, 16 bytes: one level of the section stack.
typedef struct ReplaySectionInfo {
    uint32_t Name;                   // 0, a p32 handle to the name
    uint32_t Object;                 // 4, a p32 handle, NULL for a named one
    uint16_t Number;                 // 8, in the order begun
    uint8_t  NumMoveData;            // 10
    int8_t   ChecksumErrorDetected;  // 11
    int32_t  Size;                   // 12, its first byte, then its length
} ReplaySectionInfo;

#define REPLAY_SNAPSHOT_SECTIONS  16
#define REPLAY_SNAPSHOT_DATA_SIZE 37888

// ReplaySnapshot, 38232 bytes (0x9558). Retail added EndTime at +44 to the
// demo's 36180, and 2048 bytes of data.
typedef struct ReplaySnapshot {
    uint32_t pNext;                  // 0    bNode, a p32 handle
    uint32_t pPrev;                  // 4
    char     Name[32];               // 8
    int32_t  Time;                   // 40   a Timer, WorldTimer at Init
    int32_t  EndTime;                // 44   new: WorldTimer at its end
    int32_t  BeginLoopTime;          // 48   WorldLoopCounter at Init
    int32_t  EndLoopTime;            // 52
    int32_t  MemoryImageLoadedFlag;  // 56
    int8_t   TakingSnapshotFlag;     // 60
    int8_t   RestoringSnapshotFlag;  // 61
    int8_t   TakingChecksumFlag;     // 62
    int8_t   VerifyingChecksumFlag;  // 63
    int8_t   CurrentSectionDepth;    // 64   -1 outside every section
    int8_t   OverflowedFlag;         // 65
    uint16_t CurrentSectionNumber;   // 66
    int32_t  PrintDepth;             // 68
    int32_t  PrintLoopCounter;       // 72
    ReplaySectionInfo SectionInfo[REPLAY_SNAPSHOT_SECTIONS]; // 76
    float    TotalInterestingValue;  // 332
    int32_t  DataPosition;           // 336
    int32_t  SizeofData;             // 340
    uint8_t  Data[REPLAY_SNAPSHOT_DATA_SIZE]; // 344
} ReplaySnapshot;

typedef char replaysnapshot_layout_check[
    (sizeof(ReplaySectionInfo) == 16
     && offsetof(ReplaySnapshot, Name) == 8
     && offsetof(ReplaySnapshot, EndTime) == 44
     && offsetof(ReplaySnapshot, TakingSnapshotFlag) == 60
     && offsetof(ReplaySnapshot, PrintLoopCounter) == 72
     && offsetof(ReplaySnapshot, SectionInfo) == 76
     && offsetof(ReplaySnapshot, TotalInterestingValue) == 332
     && offsetof(ReplaySnapshot, Data) == 344
     && sizeof(ReplaySnapshot) == 38232) ? 1 : -1];

// How many times the snapshots have reached bBreak (0x00250ab0, `break`),
// the debugger's stop: a value whose bytes past those stored are not its
// sign, or a checksum that does not verify. The console carries on.
extern int32_t replay_breaks;

// 0x0013cce8. Names the snapshot and stamps it with WorldTimer and
// WorldLoopCounter; empties it, out of every mode and section.
void ReplaySnapshot_Init(ReplaySnapshot *s, const char *name);

// 0x0013cd60.
void ReplaySnapshot_ChangeName(ReplaySnapshot *s, const char *name);

// 0x0013cd68. bStringHash's: h * 33 + byte, from 0xffffffff.
uint32_t ReplaySnapshot_GetChecksum(ReplaySnapshot *s, const void *data,
                                    int32_t n);

// 0x0013cda0 and 0x0013ce78. The first `stored` bytes of a `size`-byte
// value to the data and back; the rest are its sign (or zeros) both ways.
void ReplaySnapshot_WriteData(ReplaySnapshot *s, const void *data,
                              int32_t stored, int32_t size,
                              int32_t is_signed);
void ReplaySnapshot_ReadData(ReplaySnapshot *s, void *data, int32_t stored,
                             int32_t size, int32_t is_signed);

// 0x0013cf08. By the snapshot's mode: writes the value, reads it back,
// writes its checksum, or verifies that. A `size` of -1 is `stored`.
void ReplaySnapshot_MoveData(ReplaySnapshot *s, void *p, int32_t stored,
                             int32_t size, int32_t is_signed);

// 0x0013d0d0. MoveData, only while checksumming or verifying.
void ReplaySnapshot_VerifyData(ReplaySnapshot *s, void *p, int32_t stored,
                               int32_t size, int32_t is_signed);

// 0x0013d288 and 0x0013d358. A level of the section stack, for `object`.
void ReplaySnapshot_BeginSection(ReplaySnapshot *s, void *object,
                                 const char *name);
void ReplaySnapshot_EndSection(ReplaySnapshot *s);

// The inline overloads, each a jump into MoveData or VerifyData. Retail's
// bool is 4 bytes, and char is signed.
static inline void ReplaySnapshot_BeginNamedSection(ReplaySnapshot *s,
                                                    const char *name)
{
    ReplaySnapshot_BeginSection(s, NULL, name);
}

static inline void ReplaySnapshot_EndNamedSection(ReplaySnapshot *s)
{
    ReplaySnapshot_EndSection(s);
}

static inline void ReplaySnapshot_MoveFloat(ReplaySnapshot *s, float *p)
{
    ReplaySnapshot_MoveData(s, p, 4, -1, 0);
}

static inline void ReplaySnapshot_MoveTimer(ReplaySnapshot *s, int32_t *p)
{
    ReplaySnapshot_MoveData(s, p, 4, -1, 0);
}

static inline void ReplaySnapshot_MoveVector2(ReplaySnapshot *s, bVector2 *p)
{
    ReplaySnapshot_MoveData(s, p, 8, -1, 0);
}

static inline void ReplaySnapshot_MoveVector3(ReplaySnapshot *s, bVector3 *p)
{
    ReplaySnapshot_MoveData(s, p, 12, -1, 0);
}

static inline void ReplaySnapshot_MoveInt(ReplaySnapshot *s, int32_t *p,
                                          int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 4, 1);
}

static inline void ReplaySnapshot_MoveUInt(ReplaySnapshot *s, uint32_t *p,
                                           int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 4, 0);
}

static inline void ReplaySnapshot_MoveShort(ReplaySnapshot *s, int16_t *p,
                                            int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 2, 1);
}

static inline void ReplaySnapshot_MoveUShort(ReplaySnapshot *s, uint16_t *p,
                                             int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 2, 0);
}

static inline void ReplaySnapshot_MoveChar(ReplaySnapshot *s, int8_t *p,
                                           int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 1, 1);
}

static inline void ReplaySnapshot_MoveUChar(ReplaySnapshot *s, uint8_t *p,
                                            int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 1, 0);
}

static inline void ReplaySnapshot_MoveBool(ReplaySnapshot *s, int32_t *p,
                                           int32_t stored)
{
    ReplaySnapshot_MoveData(s, p, stored, 4, 0);
}

static inline void ReplaySnapshot_VerifyFloat(ReplaySnapshot *s, float *p)
{
    ReplaySnapshot_VerifyData(s, p, 4, -1, 0);
}

static inline void ReplaySnapshot_VerifyVector2(ReplaySnapshot *s,
                                                bVector2 *p)
{
    ReplaySnapshot_VerifyData(s, p, 8, -1, 0);
}

static inline void ReplaySnapshot_VerifyVector3(ReplaySnapshot *s,
                                                bVector3 *p)
{
    ReplaySnapshot_VerifyData(s, p, 12, -1, 0);
}

static inline void ReplaySnapshot_VerifyInt(ReplaySnapshot *s, int32_t *p,
                                            int32_t stored)
{
    ReplaySnapshot_VerifyData(s, p, stored, 4, 1);
}

static inline void ReplaySnapshot_VerifyUInt(ReplaySnapshot *s, uint32_t *p,
                                             int32_t stored)
{
    ReplaySnapshot_VerifyData(s, p, stored, 4, 0);
}

static inline void ReplaySnapshot_VerifyShort(ReplaySnapshot *s, int16_t *p,
                                              int32_t stored)
{
    ReplaySnapshot_VerifyData(s, p, stored, 2, 1);
}

static inline void ReplaySnapshot_VerifyUShort(ReplaySnapshot *s,
                                               uint16_t *p, int32_t stored)
{
    ReplaySnapshot_VerifyData(s, p, stored, 2, 0);
}

static inline void ReplaySnapshot_VerifyChar(ReplaySnapshot *s, int8_t *p,
                                             int32_t stored)
{
    ReplaySnapshot_VerifyData(s, p, stored, 1, 1);
}

// 0x0013cb90. The stream's place, its counts and every channel's last
// item: the add side's at the end of capture, else the remove side's.
void bRepeat_DoSnapshot(bRepeat *r, ReplaySnapshot *s, int32_t adding);

// The demo's gp-23008 (0x00323210); retail's gp-22440 (0x00330148), which
// RaceCoordinator::InitForRace sets to a new 20664-byte ReplayManager.
extern ReplayManager *pReplayManager;

// ReplayManager::GetData (0x0013eb88) and AddData (0x0013ec20). NULL
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

// 0x0013e270. While capturing, adds `value` to the total of every snapshot
// named INSTANT_REPLAY. `description` is not read.
void ReplayManager_RegisterInterestingEvent(ReplayManager *rm, float value,
                                            const char *description);

// 0x0013e2f0. RegisterInterestingEvent(-99, "Invalidate").
void ReplayManager_InvalidateInterestingEvents(ReplayManager *rm);

#endif
