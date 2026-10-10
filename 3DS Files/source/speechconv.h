// speechconv -- the Speech namespace's conversions (retail 0x002232f8 ..
// 0x00223590): the game's values as the speech library's bits, which its
// sentences' rules test. ConvertSpeed (0x00223528) is speechmgr.h's.
//
// docs/formats/pursuit-speech.md has the rest; tools/pursuitspeech_check.py
// runs retail's code against this.

#ifndef SPEECHCONV_H
#define SPEECHCONV_H

#include <stdint.h>

// Speech::ConvertCarType, 0x002232f8: the car's name for the cops,
// racerVehicleExactDescription_t, from the table at 0x0031c1f0; 0 for a
// type below 0 or past 66. Types 49 to 66 are 0 in the table too, and
// most bits belong to two neighbouring types.
int32_t speech_convert_car_type(int32_t carType);

#endif
