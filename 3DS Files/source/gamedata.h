#pragma once
#include <stdbool.h>
#include <stddef.h>

// Where the game's data lives at runtime.
//
// The disc is 273MB extracted, so it does not go in the RomFS: the CIA/.3dsx
// ships engine-only and reads the data from a directory on the SD card, the
// same arrangement NFSU2-3DS uses. This module decides which directory that
// is, once, and hands out paths inside it.
//
// Resolution order, first hit wins:
//   1. nfshp2_config.txt, looked for next to the executable and then in
//      sdmc:/3ds/NFSHP2-3DS/. Its first non-empty, non-'#' line is the data
//      directory. A relative path there is relative to sdmc:/.
//   2. sdmc:/3ds/NFSHP2-3DS/data
//   3. sdmc:/NFSHP2
// A directory only counts when GLOBAL/GLOBALB.BUN is actually in it, so a
// stale config file falls through to a working default instead of leaving
// the game pointed at nothing.

#define GAMEDATA_CONFIG  "nfshp2_config.txt"
#define GAMEDATA_MAX_PATH 256

// A file every extract has, used to recognise a real data directory.
#define GAMEDATA_SENTINEL "GLOBAL/GLOBALB.BUN"

// Finds the data directory. Safe to call more than once; the answer is
// cached. Returns false when no candidate holds the sentinel, in which case
// gamedata_root() returns the last candidate tried, for an error message.
bool gamedata_init(void);

// The resolved directory, with no trailing slash. Never NULL after
// gamedata_init(), and "" before it.
const char* gamedata_root(void);

// Joins `rel` (a '/'-separated path inside the data directory) onto the root.
// Returns `out`, or NULL if it would not fit.
char* gamedata_path(const char* rel, char* out, size_t cap);

// Whether a path inside the data directory exists.
bool gamedata_exists(const char* rel);
