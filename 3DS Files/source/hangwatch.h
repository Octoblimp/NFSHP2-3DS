// hangwatch -- where the game was when it stopped, and where the GPU's
// time goes.
//
// The first race on a New 3DS XL (2026-10-04) drew one frame and stopped,
// with HOME dead, and the log ends with that frame's line: Azahar never
// stops there, so only the device can say where. Once that was fixed the
// race ran at 8 FPS, with the GPU 113-120 ms a frame (2026-10-05). Two
// things here, both into nfshp2_debug.txt:
//
//   * A watchdog thread, one priority above the main loop's and on its
//     core, so that it runs even when the main thread spins. When no frame
//     has begun for 3 s it logs the marks the main thread passed last, how
//     many it has passed since the frame began (none is a wait, many is a
//     loop), and citro3d's GX queue: how many entries the frame has, how
//     many went to the GPU and how many it finished, and what the rest
//     are. Again at 10 s and every 30 s, and once more if frames come back.
//     Not while the loop waits in aptMainLoop: that is HOME or sleep.
//
//   * The timing frame, every 10 s of a race when the SD card has
//     HANGWATCH_TIMING_FLAG, an empty file, and never otherwise: each one
//     is a hitch of about 150 ms, and the build the user plays has to be
//     smooth (2026-10-05). At the end of each draw stage the commands so
//     far go to the GPU and are waited on, and the frame's line has each
//     stage's GPU time. Two of the stages' command lists, the models' and
//     the first envmap view's, are then copied and sent again onto a
//     target of their own in VRAM that is never shown, several ways: as
//     drawn; with every texture an 8x8 one; with a 1-pixel scissor; with
//     that and 3 vertices a draw; with no texture cache clears; with the
//     PICA's early depth test on, compared either way (13b-4f), each
//     with its target's pixels counted against as drawn's; and with every
//     RGBA8 texture fetched as RGB8. What each takes says what the stage's
//     time is spent on. The frame looks as the others do.
//
// A mark is two stores. Each frame's GX queue is counted too: citro3d's
// holds 32 entries, and the 33rd is svcBreak, so a new most is logged. A
// timing frame's is not counted: each stage's split is an entry more.

#ifndef HANGWATCH_H
#define HANGWATCH_H

#include <stdbool.h>
#include <stdint.h>

#define HANGWATCH_TRAIL 16

// The watchdog, logging through `log` (main.c's logLine).
void hangwatch_start(void (*log)(const char *fmt, ...));

// Ends the watchdog and waits for it, before exit() frees the heap its
// stack is in (main.c's atexit; threadguard.h has the crash).
void hangwatch_stop(void);

// The marks the main thread passed, the last HANGWATCH_TRAIL of them:
// strings that live for the program.
extern const char *volatile HangwatchTrail[HANGWATCH_TRAIL];
extern volatile uint32_t    HangwatchMarks;

static inline void hangwatch_mark(const char *where)
{
    HangwatchTrail[HangwatchMarks % HANGWATCH_TRAIL] = where;
    HangwatchMarks++;
}

// aptMainLoop, marked as the wait it is, and a frame begun after it.
bool hangwatch_main_loop(void);

// The file whose presence at a race's start turns its timing frames on.
#define HANGWATCH_TIMING_FLAG "sdmc:/nfshp2_gputiming.txt"

// Before C3D_FrameBegin, each frame: whether a race is being drawn. The
// first timing frame is 5 s into a race, and the next 10 s after each,
// when the flag file is there.
void hangwatch_gpu_race(bool racing);

// After C3D_FrameBegin: a timing frame starts, when one is due.
void hangwatch_gpu_begin(void);

// The end of a draw stage (`stage` lives for the program): in a timing
// frame the commands so far to the GPU and timed, and the models' and the
// first envmap view's sent again the ways above. A mark otherwise.
void hangwatch_gpu_stage(const char *stage);

// A line into the log, as the watchdog's go.
void hangwatch_log(const char *fmt, ...);

// After C3D_FrameEnd: the frame's GX queue counted, and in a timing frame
// its last commands and the screens' transfers timed, and its line logged.
void hangwatch_gpu_frame_end(void);

// ------------------------------------------------------------ the sends
//
// A race's frame goes to the GPU in parts (TASKS 46). citro3d hands the
// GPU a frame's commands at C3D_FrameEnd, all at once, and C3D_FrameBegin
// waits for them, so the GPU sat idle while the CPU built the draw: on
// the New 3DS XL 12 to 19 ms of CPU and 21 to 40 of GPU a frame, one
// after the other (2026-10-05 logs). Each hangwatch_gpu_send hands it
// what was drawn since the last, so it draws that while the CPU builds the
// rest. The picture is the same: the parts run in order, and the GPU
// keeps its registers from one to the next.
//
// Once a part is sent the GX queue runs, and whatever is added to it next
// goes to the GPU at once. C3D_FrameEnd adds its last list before it
// flushes the data cache, and C2D_TargetClear splits the frame with no
// flush at all: either would hand the GPU words still in the New 3DS's L2
// (04aa510). So a send goes right before each, citro2d flushed first, and
// they find nothing left to split.

// After hangwatch_gpu_begin: whether this frame is sent in parts. Never in
// a timing frame, which splits the frame its own way.
void hangwatch_gpu_sends_begin(bool on);

// The commands drawn since the last send split off, the linear heap
// flushed, as C3D_FrameEnd flushes it, and the list run. Nothing when the
// frame is not sent in parts or nothing was drawn.
void hangwatch_gpu_send(void);

// Right before C3D_FrameEnd: the rest sent, and no more sends until the
// next hangwatch_gpu_sends_begin.
void hangwatch_gpu_sends_end(void);

#endif
