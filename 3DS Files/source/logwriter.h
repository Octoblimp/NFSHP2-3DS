// logwriter -- nfshp2_debug.txt, written by a thread of its own.
//
// Every line used to go to the SD card as it was logged, flushed, from the
// main loop. On a New 3DS XL (2026-10-05) the race's once-a-second lines
// cost that second's frame 50-60 ms, and while the card was slow 150-240
// ms, and once 1.2 s: the hitches the user felt, each one a log line. An
// emulator writes them in no time, so Azahar never showed it.
//
// Now a line is copied into a ring and the writer thread puts it on the
// card and flushes, on a core of its own where there is one. The main
// loop only waits when the ring is full, which a race's few KB a second
// never makes it. The file still has every line, in order; what the card
// has not got yet when the app is killed is the last moment's.

#ifndef LOGWRITER_H
#define LOGWRITER_H

#include <stddef.h>
#include <stdio.h>

// The writer, over `f` (already open). With no thread, lines are written
// in place, as before.
void logwriter_start(FILE *f);

// One line's bytes into the ring, its newline included. Any thread.
void logwriter_put(const char *s, size_t n);

// Waits until everything put so far is on the card.
void logwriter_drain(void);

#endif
