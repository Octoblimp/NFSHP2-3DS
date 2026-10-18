// demomode -- attract mode's race, from retail.
//
//   BuildDemoTrackList__Fv                  0x0016ec10  200 bytes
//   StartDemoMode__Fv                       0x0016ecd8  120 bytes
//   FrontendDatabase::StartDemoMode(int)    0x00184d48  152 bytes
//
// TASKS 72h-2b. Half a minute idle on the title or the main menu, and
// ConsiderStartDemoMode (gameflow.c) loads one of TheDemoModeReplay's
// files (dmreplay.h) and then calls StartDemoMode, which picks a track and
// sets up a race of four AI cars on it. StartRace (fredrace.c) then puts
// the replay's own race over it, and the race coordinator's demo states
// (rcdemo.h) play it. On the 3DS there is no replay to load unless
// "DemoReplays 1" (configitems.h), and the race is the AI's. The first two
// are frontend.cpp's.
// docs/formats/replay.md has the decode.

#ifndef DEMOMODE_H
#define DEMOMODE_H

#include <stdint.h>

#include "fred.h"

// eDemoModeStatus (t879), Fred.DemoModeStatus: how the last demo ended.
// LaunchFrontendMenus sends a skipped one to the main menu.
#define DEMO_MODE_NO_STATUS  0
#define DEMO_MODE_TIMEDOUT   1
#define DEMO_MODE_SKIPPED    2

#define DEMO_MODE_MAX_TRACKS 32

// DemoableTracks (0x002fb288) and NumDemoableTracks (gp-21168): the
// circuit tracks, built once. BuildDemoTrackList's static `built`
// (gp-21164) and StartDemoMode's static `count` (gp-21160), the next pick,
// are here for the checker.
extern int32_t DemoableTracks[DEMO_MODE_MAX_TRACKS];
extern int32_t NumDemoableTracks;
extern int32_t DemoTrackListBuilt;
extern int32_t DemoTrackCount;

// gp-23104 and gp-23096: the demo race's direction, 0, and how long the
// AI demo runs, 120 seconds. BeginDemoModeTimeout, between them, is
// gameflow.h's beginDemoModeTimeout.
extern int32_t TrackDirectionForDemoMode;
extern float   DemoModeTimeout;

// 0x0016ec10. Once: TrackSelectedInConfigFile (configitems.h) alone when
// it is not -1; else every track from 1 to HighestTrackNumber that
// GetTrackInfo has and that is not point to point, up to 32.
void demomode_build_track_list(void);

// 0x0016ecd8. The list built, its track at `count` (a remainder of the
// list's length) taken, `count` moved on 7, and the database's
// StartDemoMode. Retail stops the movie first, which the port's
// ConsiderStartDemoMode does before it calls the host; retail's demo disc
// takes track 12, and the port has no demo disc. Retail traps on an empty
// list (a divide by zero); the port takes the table's first word.
void demomode_start(void);

// 0x00184d48. TheRaceParameters for an AI demo on `track`: time of day 3,
// TrackDirectionForDemoMode, traffic 1.0 and 0.5, four cops with every
// weapon, no weather, a race of type 1 with no laps, no player cars and
// four AI, New624 set, no event tree and no cop roadblocks or choppers.
// The database's GameType is 1 and its DemoModeStatus NO_STATUS; then
// StartRace through gDemoModeStartRaceFn, on Fred. Retail's `this` is
// never read: it writes Fred, and its one caller passes Fred.
void fred_start_demo_mode(int32_t track);

// FrontendDatabase::StartRace (0x00184f68), the tail-jump. NULL starts
// nothing.
extern void (*gDemoModeStartRaceFn)(FrontendDatabase *f);

#endif
