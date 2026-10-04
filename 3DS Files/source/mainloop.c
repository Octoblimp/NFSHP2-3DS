// mainloop -- see mainloop.h.

#include "mainloop.h"

#include "bticker.h"
#include "edisplay.h"
#include "realtime.h"

MainLoopTimingStats MainLoopTiming;
float PreviousCpuFrameTime;
float PreviousGpuFrameTime;
float PreviousCpuFrameRate;
float PreviousGpuFrameRate;

static int32_t last_realtime_frames;

// The floor on both times, gp-32052 (0x3dcccccd), and the immediate 1000.0
// (`lui 0x447a`) the rates divide.
#define MAINLOOP_MIN_FRAME_MS   0.1f
#define MAINLOOP_MS_PER_SEC     1000.0f

// RealTimeFrames counts sixtieths; the numbers are kept when this bit of it
// changes.
#define MAINLOOP_KEEP_BIT       8

// The wait and the GPU's time are read before the frame's difference. The
// CPU's time is floored and divided before the GPU's is floored.
void CalculateFrameRate(void)
{
    float wait = GetWaitForBufferSwapTime();
    float gpu = GetVifTime();
    float cpu = bGetTickerDifference(MainLoopTiming.StartTime,
                                     MainLoopTiming.LimitFrameRate) - wait;
    float cpuRate, gpuRate;

    if (cpu < MAINLOOP_MIN_FRAME_MS)
        cpu = MAINLOOP_MIN_FRAME_MS;
    cpuRate = MAINLOOP_MS_PER_SEC / cpu;
    if (gpu < MAINLOOP_MIN_FRAME_MS)
        gpu = MAINLOOP_MIN_FRAME_MS;
    gpuRate = MAINLOOP_MS_PER_SEC / gpu;
    if ((RealTimeFrames & MAINLOOP_KEEP_BIT)
        != (last_realtime_frames & MAINLOOP_KEEP_BIT)) {
        last_realtime_frames = RealTimeFrames;
        PreviousCpuFrameTime = cpu;
        PreviousGpuFrameTime = gpu;
        PreviousCpuFrameRate = cpuRate;
        PreviousGpuFrameRate = gpuRate;
    }
}

void MaybePrintTiming(void)
{
}
