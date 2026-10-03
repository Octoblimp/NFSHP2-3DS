// realtime -- see realtime.h.

#include "realtime.h"

#include "eefpu.h"
#include "joylog.h"
#include "timer.h"

int32_t FrameCounter;
int32_t CurrentVideoMode           = MODE_NTSC;
int32_t RealTimer;
int32_t RealTime                   = 1;
int32_t RealTimeFrames             = 1;
float   RealTimeElapsed;
int32_t RealTimeElapsedQuantized;
float   RealTimeElapsedFrame;
float   RealTimeElapsedError;
int32_t RealLoopCounter;
int32_t WorldTimer;
float   WorldTimeSeconds           = 1.0f;
int32_t WorldTime                  = 1;
int32_t WorldTimeFrames            = 1;
float   WorldTimeElapsed;
float   WorldTimeElapsedFrame;
int32_t WorldLoopCounter           = 100000;
int32_t NeedToPrepareWorldTimestep = 1;

// A real step is quantised to 1/3600 s: gp-29848, 0x3991a2b4, and the
// immediate 3600.0 (`lui 0x4561`).
#define REALTIME_QUANTUM          0.000277777785f
#define REALTIME_QUANTA_PER_SEC   3600.0f

// The ticker's measure is scaled by 1.0167 (gp-29844, 0x3f82233a) and then
// held to a window: 1/50 s to 0.06 s on PAL (gp-29840, gp-29836), and 1/60 s
// to 0.05 s on NTSC (gp-29832, gp-29828). NTSC's ceiling is 0x3d4cccce, one
// ulp above the float nearest 0.05, and so is spelled 0.050000004f.
#define REALTIME_TICKER_SCALE     1.0167f
#define REALTIME_PAL_MIN          0.02f
#define REALTIME_PAL_MAX          0.06f
#define REALTIME_NTSC_MIN         0.0166666675f
#define REALTIME_NTSC_MAX         0.050000004f

// Both clocks count sixtieths (the immediate 60.0) and give back a
// remainder of whole sixtieths at 0x3c888889 (gp-29820 and gp-29812, the
// same word twice). Timer ticks are 0.00025 s (gp-29824, gp-29816 and
// gp-29808, one word three times).
#define REALTIME_FRAMES_PER_SEC   60.0f
#define REALTIME_SECS_PER_FRAME   0.0166666675f
#define REALTIME_SECS_PER_TICK    0.000250000012f

// The joylog's two channels for the step: the quantised step in 8 bits on
// channel 2, and the low four bits of the loop count on channel 4.
#define REALTIME_LOG_STEP_BITS    8
#define REALTIME_LOG_STEP_CHANNEL 2
#define REALTIME_LOG_LOOP_BITS    4
#define REALTIME_LOG_LOOP_CHANNEL 4

int32_t GetVideoMode(void)
{
    return CurrentVideoMode;
}

int32_t SetVideoMode(int32_t mode)
{
    int32_t old = CurrentVideoMode;

    CurrentVideoMode = mode;
    return old;
}

float GetRealTimeElapsedFromQuantized(int32_t q)
{
    return (float)q * REALTIME_QUANTUM;
}

int32_t GetQuantizedRealTimeElapsed(float seconds)
{
    return ee_trunc_w(seconds * REALTIME_QUANTA_PER_SEC + 0.5f);
}

// The loop count is read before anything else. Replaying, the step comes
// back out of the log, and the loop count's four bits are read and dropped.
// Otherwise the step is scaled and clamped, and then quantised. What the
// quantised step loses in whole ticks is carried into the next frame's
// step as RealTimeElapsedError. The window is `max.s` and then `min.s`,
// written here as compares, since a measured step is never a NaN.
void PrepareRealTimestep(float seconds)
{
    int32_t loop = RealLoopCounter & 15;
    int32_t q;

    if (Joylog_ReplayingFlag != 0) {
        q = Joylog_GetData(REALTIME_LOG_STEP_BITS, REALTIME_LOG_STEP_CHANNEL);
        (void)Joylog_GetData(REALTIME_LOG_LOOP_BITS, REALTIME_LOG_LOOP_CHANNEL);
    } else {
        float lo, hi;
        Timer t;

        seconds = seconds * REALTIME_TICKER_SCALE + RealTimeElapsedError;
        if (GetVideoMode() == MODE_PAL) {
            lo = REALTIME_PAL_MIN;
            hi = REALTIME_PAL_MAX;
        } else {
            lo = REALTIME_NTSC_MIN;
            hi = REALTIME_NTSC_MAX;
        }
        if (seconds < lo)
            seconds = lo;
        if (hi < seconds)
            seconds = hi;
        q = GetQuantizedRealTimeElapsed(seconds);
        timer_set_time(&t, GetRealTimeElapsedFromQuantized(q));
        RealTimeElapsedError = seconds - (float)(int32_t)t.PackedTime
                                         * REALTIME_SECS_PER_TICK;
        Joylog_AddData(q, REALTIME_LOG_STEP_BITS, REALTIME_LOG_STEP_CHANNEL);
        Joylog_AddData(loop, REALTIME_LOG_LOOP_BITS, REALTIME_LOG_LOOP_CHANNEL);
    }
    RealTimeElapsedQuantized = q;
    RealTimeElapsed = GetRealTimeElapsedFromQuantized(q);
}

// Whole sixtieths out of the running remainder, and at least one a frame
// (`movn`): so RealTime counts frames when they come faster than sixty a
// second. The timer takes the step itself, through Timer::SetTime.
void AdvanceRealTime(void)
{
    float acc = RealTimeElapsedFrame + RealTimeElapsed;
    int32_t n = ee_trunc_w(acc * REALTIME_FRAMES_PER_SEC);
    Timer t;

    RealTimeFrames = (int32_t)((uint32_t)RealTimeFrames
                               + (uint32_t)(n != 0 ? n : 1));
    RealTime = RealTimeFrames;
    RealTimeElapsedFrame = acc - (float)n * REALTIME_SECS_PER_FRAME;
    timer_set_time(&t, RealTimeElapsed);
    RealTimer = (int32_t)((uint32_t)RealTimer + t.PackedTime);
    RealLoopCounter = (int32_t)((uint32_t)RealLoopCounter + 1u);
}

// One second in: the ticks are `cvt.w.s` of 4000.5 (gp-29404, SetTime's
// rounding folded in; the demo's was the immediate 4000.0), and the
// seconds are those ticks times 0.00025. The prepare flag is left alone.
void ResetWorldTime(void)
{
    int32_t ticks = ee_trunc_w(4000.5f);

    WorldTimeFrames = 1;
    WorldTimer = ticks;
    WorldTime = 1;
    WorldTimeElapsed = 0.0f;
    WorldTimeElapsedFrame = 0.0f;
    WorldLoopCounter = 0;
    WorldTimeSeconds = (float)ticks * REALTIME_SECS_PER_TICK;
}

void PrepareWorldTimestep(float seconds)
{
    WorldTimeElapsed = seconds;
    NeedToPrepareWorldTimestep = 0;
}

// The flag is set first, in the branch's delay slot, so a step of 0 sets
// it too and changes nothing else. Unlike the real clock's, the frame count
// takes no minimum of one. The step is used up.
void AdvanceWorldTime(void)
{
    float acc;
    int32_t n;
    Timer t;

    NeedToPrepareWorldTimestep = 1;
    if (WorldTimeElapsed == 0.0f)
        return;
    acc = WorldTimeElapsedFrame + WorldTimeElapsed;
    n = ee_trunc_w(acc * REALTIME_FRAMES_PER_SEC);
    WorldTimeFrames = (int32_t)((uint32_t)WorldTimeFrames + (uint32_t)n);
    WorldTime = WorldTimeFrames;
    WorldTimeElapsedFrame = acc - (float)n * REALTIME_SECS_PER_FRAME;
    timer_set_time(&t, WorldTimeElapsed);
    WorldTimer = (int32_t)((uint32_t)WorldTimer + t.PackedTime);
    WorldTimeElapsed = 0.0f;
    WorldLoopCounter = (int32_t)((uint32_t)WorldLoopCounter + 1u);
    WorldTimeSeconds = (float)WorldTimer * REALTIME_SECS_PER_TICK;
}
