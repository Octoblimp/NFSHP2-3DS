// hangwatch -- where the game was when it stopped.
//
// The first race on a New 3DS XL (2026-10-04) drew one frame and stopped,
// with HOME dead, and the log ends with that frame's line: Azahar never
// stops there, so only the device can say where. Two things here say it,
// both into nfshp2_debug.txt:
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
//   * The GPU check, for the first frames that draw the race. At the end
//     of each draw stage the commands so far go to the GPU, the linear
//     heap flushed first as C3D_FrameEnd flushes it, and are waited on
//     for 2 s at most. The log has each stage's GPU time, or the stage the
//     GPU did not finish.
//
// A mark is two stores; nothing here changes what is drawn. Each frame's
// GX queue is counted too: citro3d's holds 32 entries, and the 33rd is
// svcBreak, so a new most is logged. A checked frame's is not counted:
// each stage's split is an entry more.

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

// Check the GPU at each stage of the next `frames` frames.
void hangwatch_gpu_arm(int frames);

// After C3D_FrameBegin: a checked frame starts, while armed.
void hangwatch_gpu_begin(void);

// The end of a draw stage (`stage` lives for the program): the commands
// so far to the GPU and waited on, in a checked frame. A mark otherwise.
void hangwatch_gpu_stage(const char *stage);

// In the draw check's first frame, while each draw goes to the GPU
// alone: when georender's probe and its look at the meshes run.
bool hangwatch_per_draw(void);

// A line into the log, as the watchdog's go.
void hangwatch_log(const char *fmt, ...);

// After C3D_FrameEnd: the frame's GX queue counted, and in a checked
// frame its last commands and the screens' transfers waited on.
void hangwatch_gpu_frame_end(void);

#endif
