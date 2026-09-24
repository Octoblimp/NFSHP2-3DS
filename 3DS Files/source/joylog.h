// joylog -- the three statics of class Joylog that GenerateJoyEvents reads,
// and its two integer accessors (0x0017b920, 0x0017ba60).
//
// Joylog records every queued joystick event into a bRepeat buffer, or
// plays one back, for the PS2 development kit: Joylog::Init (0x0017bb30)
// returns at once unless bPSX2PlatformType is 1, and on a retail console
// it is 0. So on the disc pRepeat stays NULL, GetData answers 0, AddData
// does nothing, and ReplayingFlag is never set. That is the behaviour
// ported. bRepeat itself is not: a caller that sets pRepeat has to supply
// the two accessors below, which is how tools/joystick_check.py drives the
// playback arm of GenerateJoyEvents.

#ifndef JOYLOG_H
#define JOYLOG_H

#include <stdint.h>

extern int32_t Joylog_ReplayingFlag;   // _6Joylog$ReplayingFlag, gp-21256
extern int32_t Joylog_CapturingFlag;   // _6Joylog$CapturingFlag, gp-21252
extern void   *Joylog_pRepeat;         // _6Joylog$pRepeat, gp-21248

// bRepeat::RemoveData and bRepeat::AddData, as Joylog calls them once
// pRepeat is set. NULL aborts.
typedef int32_t (*JoylogGetDataFn)(int32_t bits, int32_t channel);
typedef void    (*JoylogAddDataFn)(int32_t value, int32_t bits,
                                   int32_t channel);
extern JoylogGetDataFn gJoylogRepeatGetData;
extern JoylogAddDataFn gJoylogRepeatAddData;

// 0x0017b920. 0 while pRepeat is NULL.
int32_t Joylog_GetData(int32_t bits, int32_t channel);

// 0x0017ba60. Nothing unless pRepeat is set and CapturingFlag is on.
void Joylog_AddData(int32_t value, int32_t bits, int32_t channel);

#endif
