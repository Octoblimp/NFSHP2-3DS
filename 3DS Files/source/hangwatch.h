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
//     that and 3 vertices a draw; and with no texture cache clears. What
//     each takes says what the stage's time is spent on. The frame looks
//     as the others do.
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

#endif
