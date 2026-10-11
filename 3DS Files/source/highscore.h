// highscore -- the challenge records: what a finished race writes into
// Fred's HighScoreTable, and the table of names beside it.
//
// Every track, car class, direction and lap count has five best total
// times, and every track, class and direction five best laps, fastest
// first (fredrace.h's indexes). A record holds the time, the car's type
// and an index into HighScoreNameTable: 128 names of 12 bytes, each put
// in once and found again by name.
//
// TheRaceIsOver (fredend.c) asks MaybeRecordHighScore for each player's
// car, the one with the better lap first. The Best Lap Times and Best
// Total Times screens (endtimes.c) list the five records of the race's
// kind, and colour the ones this race set by the player's
// BestLapRecordData and BestTotalRecordData.
//
// What is ported, retail's addresses (SLES_507.31):
//
//   FrontendDatabase::LookupPlayerNameFromTable  0x00186a20
//   FrontendDatabase::InsertPlayerName           0x00186a50
//   HighScoreTable::MaybeRecordHighScore         0x00186af0
//   FrontendDatabase::GetBestTotalTimesTable     0x00186d98
//   FrontendDatabase::GetBestLapTimesTable       0x00186dd0
//
// Slice RE-3. docs/formats/best-times.md has the decode.

#ifndef HIGHSCORE_H
#define HIGHSCORE_H

#include <stdint.h>

#include "fred.h"
#include "race.h"

struct RacingCar;

// The records kept for each kind of race, and the names.
#define HIGH_SCORE_RECORDS        5
#define HIGH_SCORE_NUM_NAMES      128
#define HIGH_SCORE_NAME_SIZE      12
// A time no race has set; every record starts with it.
#define HIGH_SCORE_NO_TIME        0x7fffffff

// The name at `i`. Retail answers NULL from 128 up; the port does for
// anything outside 0 to 127, where retail would point before the table.
const char *fred_lookup_player_name_from_table(FrontendDatabase *f,
                                               int32_t i);

// The index of `name`: the first entry that matches it, or else the first
// empty one, which takes 11 bytes of it. -1 when all 128 are taken.
int32_t fred_insert_player_name(FrontendDatabase *f, const char *name);

// The car's race time into the five best totals of the race's kind, if it
// ran every lap, and its best lap into the five best laps, each where it
// beats a record; the records below move down one and the last drops
// off. The name comes from the global Fred. The player's
// BestTotalRecordData and BestLapRecordData point at the records it set,
// NULL for none. The answer is the total's place as a byte, 255 for
// none; TheRaceIsOver drops it.
int32_t high_score_table_maybe_record_high_score(HighScoreTable *t, Race *r,
                                                 struct RacingCar *rc);

// The first of the five records for this track, car class and direction
// (and lap count, for the totals).
FredHighScore *fred_get_best_total_times_table(FrontendDatabase *f,
                                               int32_t track,
                                               int32_t carClass,
                                               int32_t direction,
                                               int32_t laps);
FredHighScore *fred_get_best_lap_times_table(FrontendDatabase *f,
                                             int32_t track,
                                             int32_t carClass,
                                             int32_t direction);

#endif
