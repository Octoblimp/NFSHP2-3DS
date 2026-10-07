// difficultyinfo -- TheDifficultyInfo, the AI's and the catchup's tuning,
// and the chunk loader that fills it.
//
// DifficultyInfo is retail's 992 bytes of floats and bytes and no pointer,
// so the record is the same size on every target and the loader's straight
// copy is right on all of them. The image's copy (0x002f0080, in .data) is
// all zeros until chunk 0x34b00 arrives; the one in retail GLOBALB.BUN is
// 992 bytes too.
//
// The demo's is 744 bytes (.mdebug type#2830). Retail's ELF has no .mdebug,
// so its layout is taken from its readers (docs/formats/difficulty-info.md
// lists each instruction) and the names are the demo's. Retail made two
// changes:
//   - PositionRatioOverOne and PositionRatioUnderOne are new at 240. They
//     are the demo's statics fPositionRatioOverOne (0x00307fe0) and
//     fPositionRatioUnderOne (0x00308020), which DecideBoostFactor read,
//     moved into the chunk, in the same order and with retuned values.
//   - SkillLevelDistribution gained a second set, for races with no cops:
//     SetupCarsForRace indexes it by TheRaceParameters.nMaxCops < 1.
// Everything else is the demo's, 128 bytes on from AISkillLevel and 248
// from TwoPlayerCatchup.
//
// Car's catchup, FredRace's opponent set-up, AICarController and AIDriver
// read it. main.c's boot walk of GLOBALB hands the chunk to the loader, as
// retail's LoadGlobalChunks does through slot 25.

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

// type#2809 in the demo, 180 bytes; retail's is 300. BoostScale is three
// of a 20-byte record the stab names by number only (575 in its unit).
// StartRace and StartDemoDiscGame read it as five floats, by
// OpponentStrength and then a byte of the driver's. SkillLevelDistribution
// is [cops][OpponentStrength][skill]: [0] with cops, [1] with none.
typedef struct NonExplicitModeData {
    float    BoostScale[3][5];                  //   0
    float    SkillLevelDistribution[2][3][10];  //  60
} NonExplicitModeData;                          // 300

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
    // Per race position, 1 to 8: a two-knee Table over skill 0 to 9. The
    // first is for a car whose ratio is 1 or more, the second for one
    // under 1.
    float               PositionRatioOverOne[8][2]; // 240
    float               PositionRatioUnderOne[8][2];// 304
    SkillLevelEntry     AISkillLevel[10];           // 368
    NonExplicitModeData AINonExplicitMode;          // 648
    // The catchup's graph: four knees, the lead in metres against the boost.
    // GLOBALB.BUN's are (-500, 1.08), (-200, 1.03), (-100, 1.01), (-40, 1),
    // in the demo's and in retail's.
    bVector2            TwoPlayerCatchup[4];        // 948
    MiscData            Misc;                       // 980
} DifficultyInfo;                                   // 992

typedef char difficultyinfo_layout_check[
    (sizeof(SkillLevelEntry) == 28
     && sizeof(NonExplicitModeData) == 300
     && offsetof(NonExplicitModeData, SkillLevelDistribution) == 60
     && sizeof(MiscData) == 12
     && offsetof(DifficultyInfo, AIDistanceBoostHiSkill) == 56
     && offsetof(DifficultyInfo, AIPositionBoostLoSkill) == 112
     && offsetof(DifficultyInfo, AIPositionBoostHiSkill) == 176
     && offsetof(DifficultyInfo, PositionRatioOverOne) == 240
     && offsetof(DifficultyInfo, PositionRatioUnderOne) == 304
     && offsetof(DifficultyInfo, AISkillLevel) == 368
     && offsetof(DifficultyInfo, AINonExplicitMode) == 648
     && offsetof(DifficultyInfo, TwoPlayerCatchup) == 948
     && offsetof(DifficultyInfo, Misc) == 980
     && sizeof(DifficultyInfo) == 992) ? 1 : -1];

#define DIFFICULTYINFO_CHUNK 0x00034b00u

extern DifficultyInfo TheDifficultyInfo;        // 0x002f0080

// 0x0012ff68 (the demo's 0x0012e7b0). Chunk 0x34b00: copies 992 bytes
// from its payload into TheDifficultyInfo and answers 1. The chunk's own
// size is not read, so a short chunk's copy runs past it: the demo's
// 744-byte chunk loads with the 248 bytes after it. Any other id answers
// 0 and copies nothing.
int loader_difficulty_info(uint8_t *chunk);

// 0x0012ffb0 (the demo's 0x0012e7f8). Answers whether the chunk is
// 0x34b00, and does nothing else: the table is left as it was.
int unloader_difficulty_info(const uint8_t *chunk);

#endif
