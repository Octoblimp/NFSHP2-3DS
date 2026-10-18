// demomode -- attract mode's race. TASKS 72h-2b; demomode.h has the map
// and docs/formats/replay.md the decode.
#include "demomode.h"

#include <stddef.h>

#include "configitems.h"
#include "race.h"
#include "track.h"

int32_t DemoableTracks[DEMO_MODE_MAX_TRACKS];
int32_t NumDemoableTracks;
int32_t DemoTrackListBuilt;
int32_t DemoTrackCount;

int32_t TrackDirectionForDemoMode = 0;
float   DemoModeTimeout = 120.0f;

void (*gDemoModeStartRaceFn)(FrontendDatabase *f);

// What the demo race's cars and cops are.
#define DEMO_TIME_OF_DAY      3
#define DEMO_TRAFFIC_DENSITY  1.0f
#define DEMO_TRAFFIC_ONCOMING 0.5f
#define DEMO_MAX_COPS         4
#define DEMO_RACE_TYPE        1
#define DEMO_NUM_AI_CARS      4
#define DEMO_GAME_TYPE        1

// How far the pick moves on each time.
#define DEMO_TRACK_STEP       7

// Retail's addu, which wraps.
static int32_t add32(int32_t a, int32_t b)
{
    return (int32_t)((uint32_t)a + (uint32_t)b);
}

void demomode_build_track_list(void)
{
    int32_t n, i;

    if (DemoTrackListBuilt != 0)
        return;
    if (TrackSelectedInConfigFile != -1) {
        DemoableTracks[0] = TrackSelectedInConfigFile;
        NumDemoableTracks = 1;
    } else {
        n = 0;
        for (i = 1; i <= HighestTrackNumber; i++) {
            const TrackInfo *t = track_get_info(i);

            if (t != NULL && t->Point2Point == 0 && n < DEMO_MODE_MAX_TRACKS)
                DemoableTracks[n++] = i;
        }
        NumDemoableTracks = n;
    }
    DemoTrackListBuilt = 1;
}

void demomode_start(void)
{
    int32_t count, track;

    demomode_build_track_list();
    count = DemoTrackCount;
    DemoTrackCount = add32(count, DEMO_TRACK_STEP);
    track = NumDemoableTracks != 0
                ? DemoableTracks[count % NumDemoableTracks]
                : DemoableTracks[0];
    fred_start_demo_mode(track);
}

void fred_start_demo_mode(int32_t track)
{
    RaceParameters *rp = &TheRaceParameters;

    rp->TrackNumber = track;
    rp->New624 = 1;
    Fred.GameType = DEMO_GAME_TYPE;
    rp->TrackTimeOfDay = DEMO_TIME_OF_DAY;
    rp->TrackDirection = (eTrackDirection)TrackDirectionForDemoMode;
    rp->TrafficDensity = DEMO_TRAFFIC_DENSITY;
    rp->TrafficOncoming = DEMO_TRAFFIC_ONCOMING;
    rp->nMaxCops = DEMO_MAX_COPS;
    rp->TrackWeather = 0;
    rp->EventTreeRace = 0;
    rp->RaceType = DEMO_RACE_TYPE;
    rp->AIDemoMode = 1;
    rp->NumPlayerCars = 0;
    rp->NumLapsInRace = 0;
    rp->NumAICars = DEMO_NUM_AI_CARS;
    rp->bTickets = 1;
    rp->bRoadBlocks = 1;
    rp->bSpikeStrips = 1;
    rp->bHelicopter = 1;
    rp->nNumBeACopRoadBlocks = 0;
    rp->nNumBeACopChoppers = 0;
    Fred.DemoModeStatus = DEMO_MODE_NO_STATUS;
    if (gDemoModeStartRaceFn != NULL)
        gDemoModeStartRaceFn(&Fred);
}
