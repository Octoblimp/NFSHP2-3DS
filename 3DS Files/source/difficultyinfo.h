// difficultyinfo -- TheDifficultyInfo, the AI's and the catchup's tuning,
// and the chunk loader that fills it.
//
// DifficultyInfo is 744 bytes (.mdebug type#2830) of floats and bytes and
// no pointer, so the record is the same size on every target and the
// loader's straight copy is right on all of them. The image's copy
// (0x002e81c0, in .data) is all zeros until chunk 0x34b00 arrives; the one
// in GLOBALB.BUN (offset 761472) is 744 bytes too.
//
// Only TwoPlayerCatchup has a reader in the port, Car's catchup. The AI's
// tables are laid out from the stab so the offsets are checked, and are
// its task's to read.

#ifndef DIFFICULTYINFO_H
#define DIFFICULTYINFO_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

// type#2803, 28 bytes.
typedef struct SkillLevelEntry {
    float    TakeSignChance[3];                 //  0
    float    CollisionAvoidanceChance;          // 12
    float    SpeedFactor;                       // 16
    float    SlowFactor;                        // 20
    uint8_t  RoutePointVariance;                // 24
    uint8_t  pad;                               // 25
    uint8_t  _pad26[2];                         // 26
} SkillLevelEntry;                              // 28

// type#2809, 180 bytes. BoostScale is three of a 20-byte record the stab
// names by number only (575 in its unit); it is kept as bytes until the AI
// port reads it.
typedef struct NonExplicitModeData {
    uint8_t  BoostScale[3][20];                 //   0
    float    SkillLevelDistribution[3][10];     //  60
} NonExplicitModeData;                          // 180

// type#2824, 12 bytes.
typedef struct MiscData {
    float    RoutePointChangeFrequency;         //  0
    float    BoostCalculationFrequency;         //  4
    float    MaxDistanceForBoost;               //  8
} MiscData;                                     // 12

typedef struct DifficultyInfo {
    bVector2            AIDistanceBoostLoSkill[7];  //   0
    bVector2            AIDistanceBoostHiSkill[7];  //  56
    float               AIPositionBoostLoSkill[16]; // 112
    float               AIPositionBoostHiSkill[16]; // 176
    SkillLevelEntry     AISkillLevel[10];           // 240
    NonExplicitModeData AINonExplicitMode;          // 520
    // The catchup's graph: four knees, the lead in metres against the boost.
    // GLOBALB.BUN's are (-500, 1.08), (-200, 1.03), (-100, 1.01), (-40, 1).
    bVector2            TwoPlayerCatchup[4];        // 700
    MiscData            Misc;                       // 732
} DifficultyInfo;                                   // 744

typedef char difficultyinfo_layout_check[
    (sizeof(SkillLevelEntry) == 28
     && sizeof(NonExplicitModeData) == 180
     && offsetof(DifficultyInfo, AIPositionBoostLoSkill) == 112
     && offsetof(DifficultyInfo, AISkillLevel) == 240
     && offsetof(DifficultyInfo, AINonExplicitMode) == 520
     && offsetof(DifficultyInfo, TwoPlayerCatchup) == 700
     && offsetof(DifficultyInfo, Misc) == 732
     && sizeof(DifficultyInfo) == 744) ? 1 : -1];

#define DIFFICULTYINFO_CHUNK 0x00034b00u

extern DifficultyInfo TheDifficultyInfo;        // 0x002e81c0

// 0x0012e7b0. Chunk 0x34b00: copies 744 bytes from its payload into
// TheDifficultyInfo and answers 1. The chunk's own size is not read, so a
// short chunk's copy runs past it. Any other id answers 0 and copies
// nothing.
int loader_difficulty_info(uint8_t *chunk);

// 0x0012e7f8. Answers whether the chunk is 0x34b00, and does nothing else:
// the table is left as it was.
int unloader_difficulty_info(const uint8_t *chunk);

#endif
