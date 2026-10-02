// raceparams -- RaceParameters' defaults and its static constructor.
//
// TheRaceParameters is race.c's, for the many harnesses that read a field
// of it; what sets it up lives here, so that they do not link the player
// settings, the SkipFE words and the language behind these.

#ifndef RACEPARAMS_H
#define RACEPARAMS_H

#include <stdint.h>

#include "car.h"
#include "race.h"

// The race's drivers, retail's 0x0031abb0 (the demo's DriverInfoTable):
// fourteen DriverInfos straight after TheRaceParameters, whose
// pDriverInfoTable InitWithDefaults points here. The port's DriverInfo
// keeps the demo's order (car.h), so this is 14 of the port's records,
// not 336 of the image's bytes.
#define RACE_PARAMETERS_MAX_DRIVERS 14
extern DriverInfo DriverInfoTable[RACE_PARAMETERS_MAX_DRIVERS];

// RaceParameters::InitWithDefaults, 0x001ed5c8. All 788 bytes 0, then
// TrackNumber 11, TimeOfDay 3, TrafficOncoming 0.5 and TrafficDensity 1,
// the start positions 7 and 8, two tickets before an arrest, Boost on
// with both scales 1, two laps, one player against seven, and NFSRaceMode,
// the cops' four and the new one at 624 and the reset after an arrest all
// 1. The driver table is cleared and pointed at with no drivers, both
// player settings reset, the display settings defaulted, and the word at
// 780 drawn from the default seed with bRandom(-1) -- the seed is the one
// thing it changes outside the record.
void race_parameters_init_with_defaults(RaceParameters *rp);

// 0x001ee0a0, tGlobalDisplaySettings' defaults: under SkipFE the rear
// view, the units, the jump cams and the zone cams are the SkipFE words'
// low bytes; otherwise the mirror and both cams are on, and the units are
// 1 for any language but the first (gCurrLanguageFn, 0 while unset). The
// three track maps are 0, 7 and 8 and the leaderboard 2.
void global_display_settings_init_with_defaults(tGlobalDisplaySettings *d);

// _GLOBAL_$I$TheRaceParameters, 0x001ee590, sinit's [73]: the Timers'
// constructors (TimeTrialTime and both settings' two records 0), then
// InitWithDefaults, then the 14 DriverInfos' (0x00188610 inlined): no
// rank, the ride's type -1 and its four bytes 0. The rest of each driver
// is what InitWithDefaults' clear left.
void race_parameters_static_init(void);

#endif
