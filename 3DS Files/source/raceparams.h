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


// ------------------------------------------------- the driver table's methods
//
// The race start's (fredrace.h). Each takes the record, as the image's do;
// every caller passes TheRaceParameters.

// AddDriverInfo, 0x001eda40: a copy of `d` on the end of the table, while
// it has fewer than 14. The image also looks up the ride's SkinInfo and
// drops the answer.
void race_parameters_add_driver_info(RaceParameters *rp, const DriverInfo *d);

// GetDriverInfoByDriverNumber, 0x001edb40: the first driver with that
// number, or NULL. racecoord.h's is the same on TheRaceParameters.
DriverInfo *race_parameters_find_driver(RaceParameters *rp, int32_t number);

// 0x001edc50. Every driver a knockout put out (a rank above 0) comes back:
// a player or an AI racer adds one to its count again, and the rank goes
// to 0. SetupCarsForRace runs it first, before it clears the table.
void race_parameters_restore_eliminated(RaceParameters *rp);

// 0x001edbc8. The driver with that number, unless it is missing or out
// already, goes out at `rank`, and a player or an AI racer takes one off
// its count. The driver, or NULL.
DriverInfo *race_parameters_eliminate_driver(RaceParameters *rp,
                                             int32_t number, int32_t rank);

// 0x001ede08: whether the race would draw six models or more with `ride`
// added. Each driver still in, and then `ride`, counts unless it is
// traffic: one that can be vertex-damaged always, and the rest when no
// earlier one (still in, and not vertex-damageable) has the same
// compressed geometry. The image reads the table one past its end for
// `ride`'s turn, and skips `ride` when that stale record has a rank.
int32_t race_parameters_too_many_models(RaceParameters *rp,
                                        const RideInfo *ride);

// GetLocationNumber (0x001eddb8), the track number over ten, and
// GetLocationIndex (0x001eddd8), the location less one but 4 for the
// sixth: which of a car's five LocationProb weights the race uses.
int32_t race_parameters_get_location_number(const RaceParameters *rp);
int32_t race_parameters_get_location_index(const RaceParameters *rp);

// IsFreeRun, 0x001ee390: a single race of no laps, not Be A Cop.
int32_t race_parameters_is_free_run(const RaceParameters *rp);

#endif
