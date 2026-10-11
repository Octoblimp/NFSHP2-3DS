// speechconv -- the Speech namespace's conversions (retail 0x002232f8 ..
// 0x00223590): the game's values as the speech library's bits, which its
// sentences' rules test. ConvertSpeed (0x00223528) is speechmgr.h's.
//
// docs/formats/pursuit-speech.md and race-speech.md have the rest;
// tools/pursuitspeech_check.py and racespeech_check.py run retail's code
// against this.

#ifndef SPEECHCONV_H
#define SPEECHCONV_H

#include <stdint.h>

// Speech::ConvertCarType, 0x002232f8: the car's name for the cops,
// racerVehicleExactDescription_t, from the table at 0x0031c1f0; 0 for a
// type below 0 or past 66. Types 49 to 66 are 0 in the table too, and
// most bits belong to two neighbouring types.
int32_t speech_convert_car_type(int32_t carType);

// 0x00223328 (no name): the car a reward unlocked, for RewardCarSpeech,
// from the table at 0x0031c300; 0 below 0 or past 66, and for 49 to 66.
int32_t speech_convert_reward_car_type(int32_t carType);

// 0x00223358 and 0x00223378 (no names), the Hot Pursuit tree's (GameType
// 9), and 0x00223398 and 0x002233b8, the championship's: an event's
// number as the event speech's bits, 1 to 20 by the first of each pair,
// 21 to 34 by the second. Retail indexes its tables unchecked; the port
// answers 0 outside them.
int32_t speech_convert_hp_event_a(int32_t number);
int32_t speech_convert_hp_event_b(int32_t number);
int32_t speech_convert_championship_event_a(int32_t number);
int32_t speech_convert_championship_event_b(int32_t number);

// Speech::ConvertTrackNumber, 0x002233d8, for the Select Track screen
// (14-10d), and 0x00223480 (no name), for a track a reward unlocked
// (SPCH1Type_unlockTrackType): the track's bits by its number, 11 to 66;
// 0 for any other.
int32_t speech_convert_track_number(int32_t track);
int32_t speech_convert_unlock_track(int32_t track);

#endif
