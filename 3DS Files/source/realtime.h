// realtime -- the clock object: the video mode, the real clock and the
// world clock (0x001992a0 .. 0x00199678, 1 KB), and the eighteen globals
// they keep at 0x00323cc8 .. 0x00323d0c.
//
//   FrameCounter                gp-20264  0x00323cc8  frames since boot
//   CurrentVideoMode            gp-20260  0x00323ccc  VIDEO_MODE, 1 = NTSC
//   RealTimer                   gp-20256  0x00323cd0  1/4000 s
//   RealTime                    gp-20252  0x00323cd4  sixtieths, as below
//   RealTimeFrames              gp-20248  0x00323cd8  sixtieths
//   RealTimeElapsed             gp-20244  0x00323cdc  the step, in seconds
//   RealTimeElapsedQuantized    gp-20240  0x00323ce0  the step, in 1/3600 s
//   RealTimeElapsedFrame        gp-20236  0x00323ce4  under a sixtieth, left
//   RealTimeElapsedError        gp-20232  0x00323ce8  the step's rounding
//   RealLoopCounter             gp-20228  0x00323cec  AdvanceRealTime calls
//   WorldTimer                  gp-20224  0x00323cf0  1/4000 s
//   WorldTimeSeconds            gp-20220  0x00323cf4  WorldTimer in seconds
//   WorldTime                   gp-20216  0x00323cf8  sixtieths, as below
//   WorldTimeFrames             gp-20212  0x00323cfc  sixtieths
//   WorldTimeElapsed            gp-20208  0x00323d00  the step, in seconds
//   WorldTimeElapsedFrame       gp-20204  0x00323d04  under a sixtieth, left
//   WorldLoopCounter            gp-20200  0x00323d08  AdvanceWorldTime steps
//   NeedToPrepareWorldTimestep  gp-20196  0x00323d0c  set by Advance only
//
// Each starts at the image's .sdata value. Most are 0, but CurrentVideoMode,
// RealTime, RealTimeFrames, WorldTime, WorldTimeFrames and
// NeedToPrepareWorldTimestep start at 1, WorldTimeSeconds at 1.0, and
// WorldLoopCounter at 100000. WorldTimer starts at 0 and not at 4000, so
// until the World's constructor calls ResetWorldTime, the seconds and the
// ticks disagree.
//
// MainLoop (0x0012dbd0) prepares the real step at the top of a frame from
// the ticker. It prepares the world's step from World::GetTimestep in a
// race, from 0 while the flow, the world or the replay is paused, and from
// the real step when there is no race. It advances both at the frame's end.
// The port's main loop does the same, with no race yet, and with BOOT_DT as
// the ticker's measure. InitDisplaySystem sets the video mode. The port
// keeps the image's NTSC.
//
// WorldTimeDoSnapshot (0x001995d8) is not ported: it waits on
// ReplaySnapshot, like every DoSnapshot.
//
// Cross-check: tools/realtime_check.py. Write-up: docs/formats/realtime.md.

#ifndef REALTIME_H
#define REALTIME_H

#include <stdint.h>

extern int32_t FrameCounter;
extern int32_t CurrentVideoMode;
extern int32_t RealTimer;
extern int32_t RealTime;
extern int32_t RealTimeFrames;
extern float   RealTimeElapsed;
extern int32_t RealTimeElapsedQuantized;
extern float   RealTimeElapsedFrame;
extern float   RealTimeElapsedError;
extern int32_t RealLoopCounter;
extern int32_t WorldTimer;
extern float   WorldTimeSeconds;
extern int32_t WorldTime;
extern int32_t WorldTimeFrames;
extern float   WorldTimeElapsed;
extern float   WorldTimeElapsedFrame;
extern int32_t WorldLoopCounter;
extern int32_t NeedToPrepareWorldTimestep;

// VIDEO_MODE.
#define MODE_PAL  0
#define MODE_NTSC 1

// 0x001992a0.
int32_t GetVideoMode(void);

// 0x001992a8. Returns the mode it replaces.
int32_t SetVideoMode(int32_t mode);

// 0x001992b8. `q * (1/3600)`, the constant a gp word, 0x3991a2b4.
float GetRealTimeElapsedFromQuantized(int32_t q);

// 0x001992d0. `(int)(seconds * 3600 + 0.5)`, both constants immediates.
int32_t GetQuantizedRealTimeElapsed(float seconds);

// 0x00199300. The frame's real step, from `seconds` as the ticker measured
// it. Replaying a joylog, the step is the log's instead.
void PrepareRealTimestep(float seconds);

// 0x00199410. The real clock forward by the prepared step.
void AdvanceRealTime(void);

// 0x001994a8. The world clock back to its first second.
void ResetWorldTime(void);

// 0x001994f8.
void PrepareWorldTimestep(float seconds);

// 0x00199508. The world clock forward by the prepared step, unless it is 0.
void AdvanceWorldTime(void);

#endif
