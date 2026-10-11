// endtimes -- the times a finished race shows: the Best Lap Times and
// Best Total Times screens of the end-game list, and the Lap Times
// screens the End Game Menu's View Lap Times goes to.
//
// Best Lap Times and Best Total Times (8 bytes each, endgame.h's classes)
// list the five records (highscore.h) for the race's track, direction,
// the first racing car's class and, for the totals, the lap count. Each
// row that has a time shows its place, its driver's name, its car and
// the time; the rest are hidden. A row this race set is in its player's
// colour. The first one also says who is in line for the record speech
// (RE-5's), once per list.
//
// Lap Times 1P and Lap Times 2P (LapTimesDisplay, 4 bytes) list each
// player's laps, up to nine, the best one in the lap-record colour. A lap
// row past the most laps either player ran is hidden.
//
// What is ported, retail's addresses (SLES_507.31):
//
//   WhichPlayerSetLapTimeRecord           0x001ddb80
//   WhichPlayerSetTotalTimeRecord         0x001ddbc8
//   BestLapTimes::BestLapTimes            0x001ddc10
//   BestTotalTimes::BestTotalTimes        0x001ddfd0
//   LapTimesDisplay::LapTimesDisplay      0x001e0bd0
//   LapTimesDisplay::~LapTimesDisplay     0x001e10b8
//   LapTimesDisplay::HandleEvent          0x001e10d8
//   the Lap Times screens' callback       0x001e10f0
//   BestTotalTimes::~BestTotalTimes       0x001e2370
//   BestLapTimes::~BestLapTimes           0x001e2388
//
// Slice RE-3. docs/formats/best-times.md has the decode.

#ifndef ENDTIMES_H
#define ENDTIMES_H

#include <stdint.h>

#include "bmenu.h"
#include "endgame.h"
#include "fred.h"

struct BGameFlow;

// BEST_LAP_TIMES' and BEST_TOTAL_TIMES' objects: each row n (1 to 5) has
// POS_n, NAME_n, TYPE_n and TIME_n, by SprintfAndHash, and the track's
// name is Race Results' (endresults.h's RACE_RESULTS_OBJ_TRACK_NAME).
#define BEST_TIMES_ROWS            5
// The Lap Times screens' objects: the players' names, NAME_1 and NAME_2,
// and each lap n (1 to 9) has LAPNAME_n, LAP_n, P1_LAP_n and P2_LAP_n.
#define LAP_TIMES_OBJ_P1_NAME      0x6dbbc830u
#define LAP_TIMES_OBJ_P2_NAME      0x6dbbc831u
#define LAP_TIMES_ROWS             9

extern const EndGameMenusVTable kBestLapTimesVTable;    // 0x002b8ff8
extern const EndGameMenusVTable kBestTotalTimesVTable;  // 0x002b8fc8

// The player number of the player whose record of this race is `e`, -1
// for none.
int32_t which_player_set_lap_time_record(const FredHighScore *e);
int32_t which_player_set_total_time_record(const FredHighScore *e);

// The constructors, gEndGameScreenCtorFns' shape; `data` is not read.
EndGameMenusBase *best_lap_times_construct(void *mem, uint32_t hash,
                                           BScreenCallbackData *data);
EndGameMenusBase *best_total_times_construct(void *mem, uint32_t hash,
                                             BScreenCallbackData *data);
void best_lap_times_destroy(EndGameMenusBase *m, int32_t flags);
void best_total_times_destroy(EndGameMenusBase *m, int32_t flags);

// LapTimesDisplay, 4 bytes, bMalloc(4, "LapTimesDisplay", 0, 16). It has
// no vtable.
typedef struct LapTimesDisplay {
    uint32_t ScreenHash;   // 0
} LapTimesDisplay;         // 4

// gp-17472: the one up, NULL between screens.
extern LapTimesDisplay *pLapTimesDisplay;

LapTimesDisplay *lap_times_display_construct(LapTimesDisplay *d,
                                             uint32_t hash);
// Deletes with flags & 1.
void lap_times_display_destroy(LapTimesDisplay *d, int32_t flags);
// Every message but BACK goes silent; `d` is not read.
void lap_times_display_handle_event(LapTimesDisplay *d, BScreenMessage msg,
                                    BScreenCallbackData *data);
// 0x001e10f0, in the flow's shape: `gf` is not read. ACTIVATE makes the
// display, UNACTIVATE deletes it, everything else is its HandleEvent's.
void lap_times_display_callback(struct BGameFlow *gf, BScreenMessage msg,
                                BScreenCallbackData *data);

// ---------------------------------------------------------------- seams
//
// Shared with other files: startrace.h's gStartRaceTranslateFn and
// gStartRaceTranslateStringFn and cartypeinfo.h's gCurrLanguageFn
// (endresults.c's, through end_game_print_timer). Each one below does
// nothing when NULL.

// The record speech, RE-5's: PostGameLapRecord (0x00207298) and
// PostGameTimeRecord (0x00207330), with the player, the record's place
// from 0 and the row of TransientStats the speech reads.
extern void (*gPostGameLapRecordFn)(int32_t player, int32_t place,
                                    TransientStatsElement *row);
extern void (*gPostGameTimeRecordFn)(int32_t player, int32_t place,
                                     TransientStatsElement *row);

#endif
