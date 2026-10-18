// Drives demomode.c and rcdemo.c for tools/demomode_check.py. A script of
// ops, one per line, fields split on '|':
//
//   info|I|ON|P2P      what GetTrackInfo answers for track I (0..63): NULL,
//                      or an entry whose Point2Point byte is P2P
//   list|BUILT|NUM|COUNT|CONFIG|HIGHEST  BuildDemoTrackList's `built`,
//                      NumDemoableTracks, StartDemoMode's `count`,
//                      TrackSelectedInConfigFile and HighestTrackNumber;
//                      DemoableTracks is filled with 900 + i
//   fill|SEED          TheRaceParameters' first 652 bytes, each word
//                      SEED + its offset; Fred's GameType and
//                      DemoModeStatus SEED + 1 and SEED + 2
//   dir|D              TrackDirectionForDemoMode
//   build              BuildDemoTrackList
//   start              StartDemoMode
//   fred|TRACK         FrontendDatabase::StartDemoMode
//   race|ON|TIME       pCurrentRace set or NULL, and its RaceTime
//   timeout|BITS       DemoModeTimeout, as a float's bits
//   cam|ON             pRaceCoordinator's pDemoCameraCoordinator, CAM or
//                      NULL
//   goes|ANS           what TheDemoModeReplay's TestGoesOn answers
//   ai|MSG|PARAM       the AI demo's callback, on the coordinator
//   rd|MSG|PARAM       the replay demo's
//   move|K             the replay demo's RC_MOVE_REPLAY with snapshot K's
//                      address as param
//   tag|TEXT           nothing: a heading in the transcript
//
// Every call out of the two files prints what it was asked, as the
// model's stubs at retail's addresses do.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "configitems.h"
#include "demomode.h"
#include "dmreplay.h"
#include "fred.h"
#include "joyevent.h"
#include "playercam.h"
#include "race.h"
#include "racecoord.h"
#include "rcdemo.h"
#include "rcpost.h"
#include "rcstates.h"
#include "replay.h"
#include "replaymgr.h"
#include "track.h"
#include "trackflow.h"

#define NUM_INFOS 64
#define NUM_SNAPS 4
#define PARAMS_DUMPED 652

// ------------------------------------------------------- the globals

RaceParameters TheRaceParameters;
FrontendDatabase Fred;
int32_t TrackSelectedInConfigFile;
int32_t HighestTrackNumber;
Race *pCurrentRace;
ReplayManager *pReplayManager;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
void (*gCameraCoordinatorDeleteFn)(void *coord);
void (*gRestoreTypeChangedHandlersFn)(void);

static TrackInfo infos[NUM_INFOS];
static int infoOn[NUM_INFOS];
static ReplayManager rmMem;
static RaceCoordinator rcMem;
static Race raceMem;
static ReplaySnapshot snaps[NUM_SNAPS];
static uint8_t camMem[64];
static int ansGoes;

static const char *label(const void *p)
{
    static char buf[4][32];
    static int k;
    char *b = buf[k++ & 3];
    int i;

    if (p == NULL)
        return "NULL";
    if (p == &rcMem)
        return "RC";
    if (p == &rmMem)
        return "RM";
    if (p == camMem)
        return "CAM";
    if (p == &Fred)
        return "FRED";
    if (p == (const void *)racecoordinator_joystick_handler)
        return "H";
    for (i = 0; i < NUM_SNAPS; i++)
        if ((uint32_t)(uintptr_t)p == (uint32_t)(uintptr_t)&snaps[i]) {
            snprintf(b, 32, "S%d", i);
            return b;
        }
    snprintf(b, 32, "%d", (int)(int32_t)(intptr_t)p);
    return b;
}

// ------------------------------------------------------- the stubs

TrackInfo *track_get_info(int i)
{
    printf("  track info %d\n", i);
    if (i < 0 || i >= NUM_INFOS || !infoOn[i])
        return NULL;
    return &infos[i];
}

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    printf("  add joy %d %d %s %s\n", (int)port, (int)ev,
           label((const void *)fn), label(obj));
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    printf("  remove joy %d %d\n", (int)port, (int)ev);
}

void racecoordinator_joystick_handler(JoystickPort port, JoyEvent ev,
                                      uint8_t value, void *obj)
{
    (void)port;
    (void)ev;
    (void)value;
    (void)obj;
    printf("  joystick handler never\n");
}

void racecoordinator_resume_demo_cameras(RaceCoordinator *rc)
{
    printf("  resume %s\n", label(rc));
}

void racecoordinator_suspend_demo_cameras(RaceCoordinator *rc)
{
    printf("  suspend %s\n", label(rc));
}

void racecoordinator_change_state(RaceCoordinator *rc, RCState state)
{
    printf("  change %s %d\n", label(rc), (int)state);
}

void racecoordinator_send_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    printf("  send %s %d %d\n", label(rc), (int)msg, (int)param);
}

void dmreplay_begin_demo_mode(void)
{
    printf("  begin demo\n");
}

void dmreplay_end_demo_mode(void)
{
    printf("  end demo\n");
}

int32_t dmreplay_test_goes_on(void)
{
    printf("  goes on\n");
    return ansGoes;
}

void replaymgr_restore_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    printf("  restore %s %s\n", label(rm), label(s));
}

static void screen_visibility(uint32_t screen, int visibility)
{
    printf("  vis %08x %d\n", (unsigned)screen, visibility);
}

static void camera_delete(void *coord)
{
    printf("  camera delete %s\n", label(coord));
}

static void type_handlers(void)
{
    printf("  type handlers\n");
}

static void start_race(FrontendDatabase *f)
{
    printf("  start race %s\n", label(f));
}

// ------------------------------------------------------- the dumps

static void dump_list(void)
{
    int i;

    printf("  built %d num %d count %d config %d highest %d\n",
           (int)DemoTrackListBuilt, (int)NumDemoableTracks,
           (int)DemoTrackCount, (int)TrackSelectedInConfigFile,
           (int)HighestTrackNumber);
    printf("  tracks");
    for (i = 0; i < DEMO_MODE_MAX_TRACKS; i++)
        printf(" %d", (int)DemoableTracks[i]);
    printf("\n");
}

static void dump_params(void)
{
    const uint8_t *b = (const uint8_t *)&TheRaceParameters;
    int off;

    for (off = 0; off < PARAMS_DUMPED; off += 4) {
        uint32_t w;

        memcpy(&w, b + off, 4);
        printf("  rp %d %08x\n", off, (unsigned)w);
    }
    printf("  gametype %d status %d\n", (int)Fred.GameType,
           (int)Fred.DemoModeStatus);
}

static void dump_rc(void)
{
    printf("  cam %s status %d\n", label(rcMem.pDemoCameraCoordinator),
           (int)Fred.DemoModeStatus);
}

// ------------------------------------------------------- the script

static int field(char **f, int n, int i)
{
    return i < n ? (int)strtoll(f[i], NULL, 0) : 0;
}

static void op(char *line)
{
    char *f[16];
    int n = 0;
    char *s = line;

    while (n < 16) {
        f[n++] = s;
        s = strchr(s, '|');
        if (s == NULL)
            break;
        *s++ = 0;
    }
    if (strcmp(f[0], "tag") == 0)
        return;
    if (strcmp(f[0], "info") == 0) {
        int k = field(f, n, 1);

        infoOn[k] = field(f, n, 2);
        infos[k].Point2Point = (int8_t)field(f, n, 3);
    } else if (strcmp(f[0], "list") == 0) {
        int i;

        DemoTrackListBuilt = field(f, n, 1);
        NumDemoableTracks = field(f, n, 2);
        DemoTrackCount = field(f, n, 3);
        TrackSelectedInConfigFile = field(f, n, 4);
        HighestTrackNumber = field(f, n, 5);
        for (i = 0; i < DEMO_MODE_MAX_TRACKS; i++)
            DemoableTracks[i] = 900 + i;
    } else if (strcmp(f[0], "fill") == 0) {
        uint8_t *b = (uint8_t *)&TheRaceParameters;
        uint32_t seed = (uint32_t)field(f, n, 1);
        int off;

        for (off = 0; off < PARAMS_DUMPED; off += 4) {
            uint32_t w = seed + (uint32_t)off;

            memcpy(b + off, &w, 4);
        }
        Fred.GameType = (int32_t)(seed + 1);
        Fred.DemoModeStatus = (int32_t)(seed + 2);
    } else if (strcmp(f[0], "dir") == 0) {
        TrackDirectionForDemoMode = field(f, n, 1);
    } else if (strcmp(f[0], "build") == 0) {
        demomode_build_track_list();
        dump_list();
    } else if (strcmp(f[0], "start") == 0) {
        demomode_start();
        dump_list();
        dump_params();
    } else if (strcmp(f[0], "fred") == 0) {
        fred_start_demo_mode(field(f, n, 1));
        dump_params();
    } else if (strcmp(f[0], "race") == 0) {
        pCurrentRace = field(f, n, 1) ? &raceMem : NULL;
        raceMem.RaceTime.PackedTime = (uint32_t)field(f, n, 2);
    } else if (strcmp(f[0], "timeout") == 0) {
        uint32_t bits = (uint32_t)field(f, n, 1);

        memcpy(&DemoModeTimeout, &bits, 4);
    } else if (strcmp(f[0], "cam") == 0) {
        rcMem.pDemoCameraCoordinator = field(f, n, 1) ? camMem : NULL;
    } else if (strcmp(f[0], "goes") == 0) {
        ansGoes = field(f, n, 1);
    } else if (strcmp(f[0], "ai") == 0) {
        int32_t r = rc_state_ai_demo_mode_callback(
            &rcMem, (RCMessage)field(f, n, 1), field(f, n, 2));

        printf("  -> %d\n", (int)r);
        dump_rc();
    } else if (strcmp(f[0], "rd") == 0) {
        int32_t r = rc_state_replay_demo_mode_callback(
            &rcMem, (RCMessage)field(f, n, 1), field(f, n, 2));

        printf("  -> %d\n", (int)r);
        dump_rc();
    } else if (strcmp(f[0], "move") == 0) {
        int32_t r = rc_state_replay_demo_mode_callback(
            &rcMem, RC_MOVE_REPLAY,
            (int32_t)(intptr_t)&snaps[field(f, n, 1)]);

        printf("  -> %d\n", (int)r);
        dump_rc();
    } else {
        printf("  unknown op %s\n", f[0]);
    }
}

int main(int argc, char **argv)
{
    static char line[1024];
    FILE *sc;

    if (argc < 2) {
        fprintf(stderr, "usage: demomode_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    pReplayManager = &rmMem;
    gSetFlailerScreenVisibilityFn = screen_visibility;
    gCameraCoordinatorDeleteFn = camera_delete;
    gRestoreTypeChangedHandlersFn = type_handlers;
    gDemoModeStartRaceFn = start_race;

    while (fgets(line, sizeof line, sc)) {
        size_t len = strlen(line);

        while (len && (line[len - 1] == '\n' || line[len - 1] == '\r'))
            line[--len] = 0;
        if (!len)
            continue;
        printf("> %s\n", line);
        op(line);
    }
    fclose(sc);
    return 0;
}
