// threadguard -- a tripwire over the audio workers' thread blocks.
//
// The device's race-end crash of 2026-10-11 (crash_dump_00000001.dmp, build
// 8afa111): the speech stream's worker woke from LightEvent_WaitTimeout and
// returned to 0x7fc00000. Its saved registers, the frames above them, the
// top of its stack and the start of its TLS were all that one word, over
// 1152 bytes and more -- the default NaN the VFP gives for any float result
// from a NaN or 0/0. The worker and the jukebox's are integer code, so
// something else wrote a float array there while the worker slept, and
// Azahar never does it.
//
// So both workers' blocks are watched. A check samples each block one word
// in sixteen for that NaN, and a sample that finds one is followed up: a
// run of eight or more is the bug, wherever it came from.
//
// The workers used to wake on a 10 ms timeout of their own, and a worker
// that wakes onto the run jumps to it at once, before any check could see
// it -- the first try at this guard reported a planted run only as far as
// its third line (2026-10-12). So the guard has a thread of its own above
// the workers, and it is their clock: every 10 ms it checks, and then
// signals their wake events, so no worker leaves its wait unchecked. The
// game's own signals go through threadguard_signal, which checks first. A
// worker waits threadguard_wait_ns(): 10 ms as before when the guard's
// thread did not start, a second otherwise, the guard's ticks being the
// real ones.
//
// The main loop checks at its hangwatch marks too (main.c's frameMark), so
// a run seen there is placed between two marks: after the last clean check,
// by the one that saw it.
//
// On a hit the run's words in each block are first turned into the address
// of a function that sleeps forever, so a worker that wakes returns into
// that and parks, rather than jumping to the NaN while the report is
// written. Then the report goes to stderr (sdmc:/nfshp2_stderr.txt) -- the
// run's extent, the words either side of it, the marks -- and the game
// aborts.
//
// A check costs a few hundred reads.

#ifndef THREADGUARD_H
#define THREADGUARD_H

#include <stdint.h>
#include <stdio.h>
#include <3ds.h>

// A worker made by threadCreate and the event it waits on, watched until
// forgotten. `name` lives for the program. The first starts the guard's
// thread.
void threadguard_watch(const char* name, Thread t, LightEvent* wake);
void threadguard_forget(Thread t);

// After the mark `where` (a string that lives for the program).
void threadguard_check(const char* where);

// LightEvent_Signal, after a check.
void threadguard_signal(LightEvent* wake, const char* where);

// The workers' wait.
int64_t threadguard_wait_ns(void);

// Ends the guard's thread and waits for it; no other starts after. Before
// exit() frees the heap its stack is in (main.c's atexit): a tick after
// that was the data abort of crash_dump_00000002 and 3 (2026-10-12), on
// closing from HOME and on powering off.
void threadguard_stop(void);

// main.c's: the game's state, for the report.
extern void (*threadguard_note)(FILE* f);

#endif
