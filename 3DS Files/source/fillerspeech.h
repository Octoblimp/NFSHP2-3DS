// fillerspeech -- the chase's filler speech (retail 0x002315d0 ..
// 0x00231d70): what the cops and the helicopter say on the radio when the
// player's chase has been quiet a while. tCopManager's TimeBasedSpeech
// calls SayFillerSpeech with its SpeechFillerCookie, which remembers the
// banks already said.
//
// Nine filler classes, FillerSpeechBanks (0x0031c658) in this order, each
// with its bank (a bit of the cookie), its weight, its test and its
// speech:
//
//   | bank | class            | weight | when                          |
//   |------|------------------|--------|-------------------------------|
//   |    1 | ChopperLocation  |      4 | the helicopter near, a landmark |
//   |    2 | ChopperTraffic   |      4 | the helicopter near, traffic over 0.9 |
//   |    4 | ChopperMisc      |      4 | the helicopter near           |
//   |    8 | CopLocation      |      2 | a cop within 65, a landmark   |
//   |   32 | CopTacticMisc    |      2 | a cop within 65, not Be A Cop |
//   |   64 | CopSpeed         |      2 | a cop within 65, over 100     |
//   |  128 | CopReckless      |      2 | a cop within 65, 80 mph or more |
//   |  256 | CopDirection     |      2 | a cop within 65               |
//   |   16 | TacticHit        |      5 | two speakers, a cop within 40 |
//
// docs/formats/pursuit-speech.md has the rest; tools/fillerspeech_check.py
// runs retail's code against this.

#ifndef FILLERSPEECH_H
#define FILLERSPEECH_H

#include <stdint.h>

#include "copmanager.h"

// tPursuit::IsCopNearChasedCar, 0x0022bb28: one of the chase's cops' cars
// within `dist` of the chased car, in three dimensions.
int32_t tpursuit_is_cop_near_chased_car(const tPursuit *p, float dist);

// TryFillerSpeech, 0x002315d0: the banks not in the cookie whose test
// passes, one picked by bRandom over their weights, said, and its bank
// added to the cookie. 0 when none can be said.
int32_t try_filler_speech(tPursuit *p, uint32_t *cookie);

// SayFillerSpeech, 0x00231760: TryFillerSpeech, and when nothing can be
// said, the cookie emptied and again.
void say_filler_speech(tPursuit *p, uint32_t *cookie);

#endif
