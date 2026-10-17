// replaymgr -- ReplayManager's methods, from retail's Replay.obj (TASKS 72f).
//
// The manager records a race and plays it back. From the beginning of time
// (the TICK at RACING) every frame's pad events go into a bRepeat log of
// 0x32000 bytes on four channels, and snapshots of the whole race are taken
// as it goes: an instant replay's every 300 frames, two kept, the older
// turned into one of five highlights when the race found it interesting; a
// lap snapshot each LapSnapshotSpacing seconds, eight kept, the spacing
// doubled and every other one dropped when they run out; and four checksums
// at loop counts a debugger sets. A take can change what it moves (a matrix
// gets its fourth column back), so the capture writes down the loop of
// every snapshot it takes, and a replay takes a dummy one on each of those
// loops to step the same. Capture also takes a dummy every 211 loops, and
// whenever 30 have gone by with none.
//
// A replay restores a snapshot and runs the world on from it, BeginFrame
// marking the frames up to where the capture ended as replayed, so
// GenerateJoyEvents reads the log back instead of the pad.
//
// Retail's names but for IsSnapshotTime and SortSnapshots, which are new in
// retail and ours. docs/formats/replay.md has the decode.

#ifndef REPLAYMGR_H
#define REPLAYMGR_H

#include <stdint.h>

#include "replay.h"

// TheDemoModeReplay's words the manager reaches (0x002f0960): its
// ActiveFlag (+0) is trackflow.h's DemoModeReplayActiveFlag; the log a demo
// replay hands to the manager and back (+52, a p32 handle) and its
// snapshots (+56, a bTList) are these. DemoModeReplay's constructor
// (0x0013ee08) makes the list empty; here two zero words are the list
// before that, and the first use makes it empty. TASKS 72h ports the
// class around them.
extern uint32_t DemoModeReplay_pRepeat;          // 0x002f0994
extern uint32_t DemoModeReplay_SnapshotList[2];  // 0x002f0998

// 0x002f08d8, the demo's ChecksumSnapshotTimes: the four loop counts a
// CHECKSUM<n> snapshot is taken (capturing) or verified (replaying) on.
// -1 is none. DoFancyJoylogDebugging sets them.
extern int32_t ChecksumSnapshotTimes[4];

// HandlePauseMenuReplaySpecialEvents (0x001703e0), which makes a special
// event happen, recorded or replayed (TASKS 72h). NULL does nothing.
extern void (*gReplayHandleSpecialEventFn)(const ReplaySpecialEventInfo *e);

// DemoModeReplay::Service (0x0013f500) on TheDemoModeReplay, given whether
// a snapshot was taken this loop: a tweaker's tool that records the
// attract mode's replays, and does nothing in a game (TASKS 72h). NULL
// does nothing.
extern void (*gDemoModeReplayServiceFn)(int32_t snapshot_this_loop);

// 0x0013d448, on bMalloc(REPLAY_MANAGER_SIZE). Both lists empty, the
// flags and counts clear, LapSnapshotSpacing 15 s, NextFancyDebugTime
// 9999999, the capture's loop counts and LastSnapshotTime -1. The fancy
// table, MaxNumAutoReplaySnapshots and the snapshot times are left as they
// came. With a demo replay active, it takes the demo's log and snapshots
// and makes one free snapshot.
ReplayManager *replaymgr_construct(void *mem);

// 0x0013d5c0. A snapshot whose memory image is loaded (the demo's) goes
// back to TheDemoModeReplay with the log; the rest are freed, then the
// log. Flag 1 frees the manager.
void replaymgr_destroy(ReplayManager *rm, int32_t flags);

// 0x0013d6f8. Once: the capture's loop counts and the beginning and end of
// time stamped now. Then, with 0xd0ad8 bytes free past 32 KB in pool 16,
// the log and seventeen free snapshots: two instant replays, eight laps,
// five highlights.
void replaymgr_mark_the_beginning_of_time(ReplayManager *rm);

// 0x0013d868. Capturing ends at the next frame's end.
void replaymgr_mark_the_end_of_time(ReplayManager *rm);

// 0x0013d880. Whether this frame captures or replays, the snapshots it
// takes, the special events it replays, the checksums, then the demo's
// service.
void replaymgr_begin_frame(ReplayManager *rm);

// 0x0013e008. A captured frame moves the end of capture and time on;
// either flag goes down.
void replaymgr_end_frame(ReplayManager *rm);

// 0x0013e078. The development kit's joylog debugging, which only
// Joylog::ReplayingFlag starts, and nothing sets in a game: fancy pad
// events played in at NextFancyDebugTime with the joylog off, then at the
// capture's end, paused, four checksum loops set and more fancy events,
// and the joylog on again.
void replaymgr_do_fancy_joylog_debugging(ReplayManager *rm);

// 0x0013e308. From the first highlight.
void replaymgr_begin_race_highlights(ReplayManager *rm);

// 0x0013e318. The next highlight restored, wrapping to the first, or with
// none the first lap snapshot, played to the capture's end. With the word
// at +12 set, the replay pauses instead.
void replaymgr_begin_next_race_highlight(ReplayManager *rm);

// 0x0013e3f8. A special event (a pause page's change), made now and, while
// capturing with room, kept for the replay; with no room the capture ends.
void replaymgr_add_special_event(ReplayManager *rm, int32_t type, int32_t a,
                                 int32_t b);

// 0x0013e5c8. The `k`th snapshot named `name`, or NULL.
ReplaySnapshot *replaymgr_find_snapshot(ReplayManager *rm, const char *name,
                                        int32_t k);

// 0x0013e648. The `k`th snapshot, or NULL.
ReplaySnapshot *replaymgr_get_snapshot(ReplayManager *rm, int32_t k);

// 0x0013e690. Every snapshot named `name` moved to the list's end, in the
// order of their BeginLoopTime.
void replaymgr_sort_snapshots(ReplayManager *rm, const char *name);

// 0x0013e748 and 0x0013e790. The first snapshot named `name` restored, or
// deleted; 0 when there is none.
int32_t replaymgr_restore_snapshot_named(ReplayManager *rm, const char *name);
int32_t replaymgr_delete_snapshot_named(ReplayManager *rm, const char *name);

// 0x0013e7d8. Back to the free list's end.
void replaymgr_delete_snapshot(ReplayManager *rm, ReplaySnapshot *s);

// 0x0013e9f0. A snapshot named `name` of the race now, at the list's end;
// NULL before the beginning of time or when it overflowed.
ReplaySnapshot *replaymgr_take_snapshot(ReplayManager *rm, const char *name);

// 0x0013eb38. The race put back as `s` had it.
void replaymgr_restore_snapshot(ReplayManager *rm, ReplaySnapshot *s);

// 0x0013eb88, 0x0013ebe8 and 0x0013ec20. The log's next item while
// replaying, 0 otherwise or after an error; the same masked to its `bits`
// (retail's shift right is logical, so "signed" is a misnomer); and an item
// into the log while capturing, which ends the capture when it nears full.
// The first and last are what replay.h's gReplayManagerGetData and
// gReplayManagerAddData take.
int32_t replaymgr_get_data(ReplayManager *rm, int32_t bits, int32_t channel);
int32_t replaymgr_get_signed_data(ReplayManager *rm, int32_t bits,
                                  int32_t channel);
void replaymgr_add_data(ReplayManager *rm, int32_t value, int32_t bits,
                        int32_t channel);

#endif
