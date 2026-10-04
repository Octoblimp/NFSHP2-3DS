// mainloop -- MainLoop's frame profiler (step 13b-2): the ten ticks it
// stamps through a frame, and CalculateFrameRate, which turns two of them
// into the frame rates Player::DisplayDebugInfo prints.
//
//   CalculateFrameRate    retail 0x0012f090   demo 0x0012db20
//   MaybePrintTiming      retail 0x0012f088   demo 0x0012db18 (`jr ra`)
//
//   MainLoopTiming        0x002f0058          demo 0x002e8198, 40 bytes
//   PreviousCpuFrameTime  gp-23248 0x0032fe20 demo gp-23816
//   PreviousGpuFrameTime  gp-23244 0x0032fe24 demo gp-23812
//   PreviousCpuFrameRate  gp-23240 0x0032fe28 demo gp-23808
//   PreviousGpuFrameRate  gp-23236 0x0032fe2c demo gp-23804
//   last_realtime_frames  gp-13416 0x00332488 CalculateFrameRate's static
//
// All start at 0 in the image.
//
// MainLoop (0x0012f378) reads bGetTicker at each phase's end and stores it
// in MainLoopTiming, from StartTime at the top of the frame to
// LimitFrameRate after the wait for the vertical blank. CalculateFrameRate
// then takes:
//
//   cpu = bGetTickerDifference(StartTime, LimitFrameRate)
//         - GetWaitForBufferSwapTime()       (ms, at least 0.1, gp-32052)
//   gpu = GetVifTime()                       (ms, at least 0.1)
//
// and 1000 / each as the rates. It keeps all four only when bit 3 of
// RealTimeFrames has changed since it last kept them: every eight
// sixtieths, so the numbers on screen hold still long enough to read.
//
// Retail's CalculateFrameRate adds a loop the demo's has not: with
// DoScreenPrintf (gp-23064) set and a World, it calls 0x00132620 for each
// of the World's cars. That function's prints are compiled out. It reads
// the race and calls DisplayCullingStats (0x0010cea0, `return 0`) and
// Race::GetRacingCar, and changes nothing, so the port leaves the loop out,
// as carfinish.c leaves out the same tail in Car::FinishMovement.
//
// MaybePrintTiming is empty in both images, and so is PrintTimingStat
// (0x0012d7a0 in the demo, with no caller): the per-phase print was
// compiled out. The port's own per-phase log line is main.c's.
//
// Cross-check: tools/mainloop_check.py. Write-up:
// docs/formats/frame-profiler.md.

#ifndef MAINLOOP_H
#define MAINLOOP_H

#include <stdint.h>

// One tick at the end of each phase of MainLoop, in its order. The names
// are the struct's own (mdebug type 3247).
typedef struct MainLoopTimingStats {
    uint32_t StartTime;             //  0
    uint32_t ServiceGameFlow;       //  4
    uint32_t GenerateJoyEvents;     //  8
    uint32_t WorldDoTimestep;       // 12
    uint32_t MenuSystemTick;        // 16
    uint32_t UpdateCameraMovers;    // 20
    uint32_t UpdateSound;           // 24
    uint32_t DisplayFrame;          // 28
    uint32_t ServiceFileSystem;     // 32
    uint32_t LimitFrameRate;        // 36
} MainLoopTimingStats;

extern MainLoopTimingStats MainLoopTiming;
extern float PreviousCpuFrameTime;
extern float PreviousGpuFrameTime;
extern float PreviousCpuFrameRate;
extern float PreviousGpuFrameRate;

// 0x0012f090.
void CalculateFrameRate(void);

// 0x0012f088: empty.
void MaybePrintTiming(void);

#endif
