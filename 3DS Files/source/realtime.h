// realtime -- the two clocks AdvanceRealTime (0x00199410) keeps as globals.
//
//   RealTimer     gp-20256, 0x00323cd0   1/4000 s, Timer::SetTime's unit
//   FrameCounter  gp-20264, 0x00323cc8   frames since boot
//
// gameflow.c advances both, in its own record, as the boot flow's port
// did before anything else needed them. The joystick layer reads them as
// the globals they are, so main.c copies the pair across once a frame
// before GenerateJoyEvents. Both are compared signed (`slt`).

#ifndef REALTIME_H
#define REALTIME_H

#include <stdint.h>

extern int32_t RealTimer;
extern int32_t FrameCounter;

#endif
