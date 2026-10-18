// Drives replayscreen.c for tools/replayscreen_check.py. A script of ops,
// one per line, fields split on '|':
//
//   rm|PAUSED|SLOW|ENDCAP|BEGIN|END  pReplayManager's PausedFlag,
//                      SlowMotionFlag, EndCapturingLoopCount,
//                      BeginningOfTime and EndOfTime
//   time|WLC|WT|RLC|RTF|RT  WorldLoopCounter, WorldTimer, RealLoopCounter,
//                      RealTimeFrames and RealTimer
//   race|LAPS|CARS|TIME|P2P  pCurrentRace's NumLapsInRace, NumRacingCars
//                      and RaceTime, and TheRaceParameters.Point2Point
//   players|N          PlayerNumPlayers
//   player|I|ZONE|CTRL|USAGE|NITRO|NIS|LAPS|POS|REASON  player I's
//                      nZoneCurrent; its car's TheControlMode and the
//                      UsageType of its CarTypeInfo; what NitroActive and
//                      IsNisPlaying answer for it; and its RacingCar's
//                      NumLapsCompleted, RacePosition and FinishReason
//   objs|MASK          the objects FindFlailerObject finds: bit i, kObjs[i]
//   objx|I|X|W         object I's X and the width CalculateWidthFloat
//                      answers for it, both float bits
//   snaps|SPEC         the manager's snapshots: NAME:TIME:END split on ';',
//                      NAME an index into kSnapNames; '-' for none
//   dmr|WANT|REC|PLAY  TheDemoModeReplay's three words; REC and PLAY 1 for
//                      a snapshot, 0 for none
//   ans|HELP|TOGGLE|CD|CANTEST|GOESON|NIS  what the help's IsActive and its
//                      toggle, bIsThereACDInTheDrive, CanTestDemoMode, the
//                      demo test's goes-on and CreateNisCameraCoordinator
//                      (0 NULL, else the player's) answer
//   egs|ON             pRaceCoordinator's pEndGameScreens set or NULL
//   ctor|PN            a ReplayScreen on a new block of 0xcd
//   dtor|FLAGS, markers|BUILD, watch, stopnis, has, change, tick, update,
//   add|PORT, remove|PORT, joy|PORT|EV|VALUE, bridge|PORT|EV|VALUE,
//   posx|T, bmpos|OBJ|T, pause|ON  its members; T float bits, OBJ -1 NULL
//   dump               the screen and the words it writes elsewhere
//   tag|TEXT           nothing: a heading in the transcript
//
// Every call out of replayscreen.c prints what it was asked, as the
// model's stubs at retail's addresses do.
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "cammover.h"
#include "car.h"
#include "cartypeinfo.h"
#include "democam.h"
#include "flailer.h"
#include "player.h"
#include "playercam.h"
#include "playerhud.h"
#include "playernis.h"
#include "race.h"
#include "racecoord.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realdriver.h"
#include "realtime.h"
#include "replay.h"
#include "replaymgr.h"
#include "replayscreen.h"
#include "timer.h"
#include "trackflow.h"

// What replayscreen.c reads that the linked files do not define.
ReplayManager *pReplayManager;
RaceCoordinator *pRaceCoordinator;
Race *pCurrentRace;
RaceParameters TheRaceParameters;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
int32_t RealTimer, RealTimeFrames, RealLoopCounter, WorldTimer;
int32_t WorldLoopCounter;
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
void (*gSoundMuteReplayFn)(int32_t on);
struct NisCameraCoordinator *(*gNisCreateCameraCoordinatorFn)(
    NisManager *m, int32_t view);
void (*gNisDeleteCameraCoordinatorFn)(struct NisManager *mgr,
                                      struct NisCameraCoordinator *c);
void (*gCameraCoordinatorDeleteFn)(void *coord);
void *(*gDemoCameraCoordinatorCtorFn)(void *mem, int32_t a,
                                      struct Car *car);
CameraMover *(*gDriveCameraMoverFn)(void *mem, int32_t viewID,
                                    struct Car *car, int32_t pov,
                                    float lookbackSpeed, int32_t disableLag,
                                    int32_t lookBack, int32_t perfectFocus);
int32_t (*gCurrLanguageFn)(void);

#define NUM_SLOTS  256
#define SLOT_SIZE  1024
#define NUM_OBJS   44
#define MAX_SNAPS  40

typedef char replayscreen_test_slot_check[
    (sizeof(ReplayScreen) <= SLOT_SIZE && sizeof(CameraMover) <= SLOT_SIZE)
        ? 1 : -1];

// The objects, in the model's order: the twelve named, then LAP_MARKER1
// to 16 and HIGHLIGHT_MARKER1 to 16.
static const char *const kObjNames[12] = {
    "TIMELINE", "TIME_MARKER", "INSTANT_REPLAY_MARKER", "DEMO_PLAYING",
    "DEMO_RECORDING", "DEMO_WANT_RECORDING", "ONE_PLAYER_ONLY", "LAP",
    "LAP_LABEL", "PLACE", "PLACE_LABEL", "TIME",
};
static const uint32_t kObjHashes[12] = {
    0xbd2bc882u, 0xb8e8186fu, 0xadaa0f01u, 0xacf8f0b5u, 0xd32490beu,
    0x4b53438fu, 0xc9b7f0c0u, 0x6486623bu, 0x51072bf1u, 0x3405c44eu,
    0x98071aa4u, 0x15e0f0a8u,
};

static const char *const kSnapNames[] = {
    "LAP_SNAPSHOT", "HIGHLIGHT_SNAPSHOT", "DEMO_MODE_SNAPSHOT",
    "INSTANT_REPLAY", "LAP_SNAPSHOT2", "INSTANT_REPLAY ", "",
    "DEMO_MODE_SNAPSHOt", "PURSUIT", "lap_snapshot",
};
#define NUM_SNAP_NAMES ((int)(sizeof kSnapNames / sizeof kSnapNames[0]))

static uint32_t objHash[NUM_OBJS];
static char objName[NUM_OBJS][24];
static struct FlailerObjectChunk objs[NUM_OBJS];
static float objWidth[NUM_OBJS];
static uint64_t objMask;

static ReplaySnapshot snaps[MAX_SNAPS];
static int32_t numSnaps;

static ReplayManager rmMem;
static RaceCoordinator rcMem;
static Race raceMem;
static struct Player players[2];
static struct Car cars[2];
static CarTypeInfo carTypes[2];
static struct RacingCar racingCars[2];
static uint64_t drivers[2][4];
static uint64_t nisManagers[2][4];
static uint64_t nisCoords[2][4];
static uint64_t endGameScreens[4];
static int32_t nitroAnswer[2], nisAnswer[2];

static int32_t ansHelp, ansToggle, ansCD, ansCanTest, ansGoesOn, ansNis;

static uint64_t slots[NUM_SLOTS][SLOT_SIZE / 8];
static uint8_t slotUsed[NUM_SLOTS];
static ReplayScreen *screen;

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static float fbits(uint32_t b)
{
    float f;

    memcpy(&f, &b, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t b;

    memcpy(&b, &f, 4);
    return b;
}

// ------------------------------------------------------------ the blocks

static int slot_of(const void *p)
{
    const uint8_t *b = (const uint8_t *)slots;
    const uint8_t *q = (const uint8_t *)p;

    if (q < b || q >= b + sizeof slots)
        return -1;
    return (int)((q - b) / SLOT_SIZE);
}

static void *slot_alloc(void)
{
    int i;

    for (i = 0; i < NUM_SLOTS; i++)
        if (!slotUsed[i]) {
            slotUsed[i] = 1;
            memset(slots[i], 0xcd, SLOT_SIZE);
            return slots[i];
        }
    fprintf(stderr, "out of slots\n");
    exit(3);
}

static int index_of(const void *p, const void *base, size_t size, int n)
{
    const uint8_t *b = (const uint8_t *)base;
    const uint8_t *q = (const uint8_t *)p;

    if (q < b || q >= b + size * (size_t)n || (size_t)(q - b) % size)
        return -1;
    return (int)((size_t)(q - b) / size);
}

static const char *label(const void *p)
{
    static char bufs[8][32];
    static int k;
    char *b = bufs[k++ & 7];
    int i;

    if (p == NULL)
        return "NULL";
    if ((i = slot_of(p)) >= 0) {
        snprintf(b, 32, "m%d+%d", i,
                 (int)((const uint8_t *)p - (const uint8_t *)slots[i]));
        return b;
    }
    if ((i = index_of(p, objs, sizeof objs[0], NUM_OBJS)) >= 0)
        snprintf(b, 32, "o%d", i);
    else if ((i = index_of(p, snaps, sizeof snaps[0], MAX_SNAPS)) >= 0)
        snprintf(b, 32, "S%d", i);
    else if ((i = index_of(p, players, sizeof players[0], 2)) >= 0)
        snprintf(b, 32, "P%d", i);
    else if ((i = index_of(p, cars, sizeof cars[0], 2)) >= 0)
        snprintf(b, 32, "car%d", i);
    else if ((i = index_of(p, racingCars, sizeof racingCars[0], 2)) >= 0)
        snprintf(b, 32, "rc%d", i);
    else if ((i = index_of(p, drivers, sizeof drivers[0], 2)) >= 0)
        snprintf(b, 32, "D%d", i);
    else if ((i = index_of(p, nisManagers, sizeof nisManagers[0], 2)) >= 0)
        snprintf(b, 32, "N%d", i);
    else if ((i = index_of(p, nisCoords, sizeof nisCoords[0], 2)) >= 0)
        snprintf(b, 32, "NC%d", i);
    else if (p == (const void *)&raceMem)
        snprintf(b, 32, "R");
    else if (p == (const void *)&rcMem)
        snprintf(b, 32, "RC");
    else if (p == (const void *)&rmMem)
        snprintf(b, 32, "RM");
    else if (p == (const void *)ReplayScreenHelpIDs)
        snprintf(b, 32, "HELP");
    else
        snprintf(b, 32, "?");
    return b;
}

// A word as retail's 32-bit pointer: a snapshot's label, else the number.
static const char *word_label(int32_t w)
{
    static char b[32];
    int i;

    for (i = 0; i < MAX_SNAPS; i++)
        if (w == (int32_t)(intptr_t)&snaps[i]) {
            snprintf(b, sizeof b, "S%d", i);
            return b;
        }
    snprintf(b, sizeof b, "%d", w);
    return b;
}

static const char *hash_name(uint32_t h)
{
    static char b[16];
    int i;

    for (i = 0; i < NUM_OBJS; i++)
        if (objHash[i] == h)
            return objName[i];
    if (h == 0x18b2dbc8u)
        return "PLAYER_NUMBER";
    if (h == 0xd53d9dbeu)
        return "TIME_LABEL";
    if (h == REPLAY_SCREEN_HASH)
        return "SCREEN";
    if (h == REPLAY_SCREEN_HIDDEN_HASH)
        return "HIDDEN";
    snprintf(b, sizeof b, "0x%08x", h);
    return b;
}

// ------------------------------------------------------------ the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = slot_alloc();

    printf("malloc %d %s %d %d -> %s\n", size, name, flags, pool, label(p));
    return p;
}

void bFree(void *p)
{
    int i = slot_of(p);

    printf("free %s\n", label(p));
    if (i >= 0)
        slotUsed[i] = 0;
}

static void screen_visibility(uint32_t s, int v)
{
    printf("screen %s %d\n", hash_name(s), v);
}

static void mute_replay(int32_t on)
{
    printf("mute %d\n", on);
}

struct FlailerObjectChunk *flailer_find_object(uint32_t s, uint32_t o,
                                               int32_t type)
{
    struct FlailerObjectChunk *found = NULL;
    int i;

    for (i = 0; i < NUM_OBJS; i++)
        if (objHash[i] == o && (objMask >> i & 1)) {
            found = &objs[i];
            break;
        }
    printf("find %s %s %d -> %s\n", hash_name(s), hash_name(o), (int)type,
           label(found));
    return found;
}

float flailerbitmap_width_float(struct FlailerBitmapChunk *b)
{
    int i = index_of(b, objs, sizeof objs[0], NUM_OBJS);

    printf("widthf %s\n", label(b));
    return i >= 0 ? objWidth[i] : 0.0f;
}

void flailerobject_set_visibility(struct FlailerObjectChunk *o, int32_t v)
{
    printf("vis %s %d\n", label(o), v);
}

void flailerobject_set_top_left_x(struct FlailerObjectChunk *o, float x)
{
    printf("x %s 0x%08x\n", label(o), bitsf(x));
}

void flailerobject_set_top_left_y(struct FlailerObjectChunk *o, float y)
{
    printf("y %s 0x%08x\n", label(o), bitsf(y));
}

void flailerobject_set_width(struct FlailerObjectChunk *o, float w)
{
    printf("w %s 0x%08x\n", label(o), bitsf(w));
}

void flailerobject_set_height(struct FlailerObjectChunk *o, float h)
{
    printf("h %s 0x%08x\n", label(o), bitsf(h));
}

void flailerbitmap_set_color(struct FlailerBitmapChunk *b, uint32_t c)
{
    printf("color %s 0x%08x\n", label(b), c);
}

int32_t flailer_printf(uint32_t s, uint32_t o, const char *fmt, ...)
{
    char buf[256];
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    printf("printf %s %s %s [%s]\n", hash_name(s), hash_name(o), fmt, buf);
    return 0;
}

void flailer_set_language_id(uint32_t s, uint32_t o, uint32_t id)
{
    printf("langid %s %s 0x%x\n", hash_name(s), hash_name(o), id);
}

int32_t player_is_nis_playing(const struct Player *p)
{
    int i = index_of(p, players, sizeof players[0], 2);

    printf("nis %s\n", label(p));
    return i >= 0 ? nisAnswer[i] : 0;
}

int32_t realdriver_nitro_active(RealDriver *d)
{
    int i = index_of(d, drivers, sizeof drivers[0], 2);

    printf("nitro %s\n", label(d));
    return i >= 0 ? nitroAnswer[i] : 0;
}

static struct NisCameraCoordinator *nis_create(NisManager *m, int32_t view)
{
    int i = index_of(m, nisManagers, sizeof nisManagers[0], 2);
    void *c = ansNis && i >= 0 ? (void *)nisCoords[i] : NULL;

    printf("nis create %s %d -> %s\n", label(m), view, label(c));
    return c;
}

static void nis_delete(struct NisManager *m, struct NisCameraCoordinator *c)
{
    printf("nis delete %s %s\n", label(m), label(c));
}

static void coord_delete(void *c)
{
    printf("coord delete %s\n", label(c));
    bFree(c);
}

static void *demo_coord(void *mem, int32_t a, struct Car *car)
{
    printf("democoord %s %d %s\n", label(mem), a, label(car));
    return mem;
}

static void mover_destroy(CameraMover *m)
{
    printf("mover dtor %s\n", label(m));
}

static CameraMoverVtbl moverVtbl;

static CameraMover *drive_mover(void *mem, int32_t viewID, struct Car *car,
                                int32_t pov, float speed, int32_t lag,
                                int32_t lookBack, int32_t focus)
{
    CameraMover *m = mem;

    printf("drive %s %d %s %d 0x%08x %d %d %d\n", label(mem), viewID,
           label(car), pov, bitsf(speed), lag, lookBack, focus);
    m->vtbl = &moverVtbl;
    return m;
}

static void radial_blur(int32_t on)
{
    printf("blur %d\n", on);
}

struct RacingCar *race_get_racing_car(Race *r, struct Car *c)
{
    int i = index_of(c, cars, sizeof cars[0], 2);
    struct RacingCar *rc = i >= 0 ? &racingCars[i] : NULL;

    printf("racingcar %s %s -> %s\n", label(r), label(c), label(rc));
    return rc;
}

void timer_print_to_string(const Timer *t, char *buf, int32_t flags,
                           int32_t language)
{
    (void)language;
    printf("timer %u %d\n", t->PackedTime, flags);
    snprintf(buf, 16, "T%u", t->PackedTime);
}

int32_t racingcar_get_finish_reason_id(int32_t reason)
{
    printf("finishid %d\n", reason);
    return 0x1000 + reason;
}

ReplaySnapshot *replaymgr_get_snapshot(ReplayManager *rm, int32_t k)
{
    (void)rm;
    return k >= 0 && k < numSnaps ? &snaps[k] : NULL;
}

void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    printf("post %s %d %s\n", label(rc), (int)msg, word_label(param));
}

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    printf("addjoy %d %d %s %s\n", (int)port, (int)ev,
           fn == replayscreen_joy_handler_bridge ? "bridge" : "?",
           label(obj));
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    printf("remjoy %d %d\n", (int)port, (int)ev);
}

static void play_sample(const char *name, float volume)
{
    printf("sample %s 0x%08x\n", name, bitsf(volume));
}

static void frontend_sound(int32_t event)
{
    printf("fesound %d\n", event);
}

static int32_t help_active(void)
{
    printf("helpactive\n");
    return ansHelp;
}

static int32_t help_toggle(const int32_t *lines, int32_t value)
{
    int i;

    printf("helptoggle %s %d [", label(lines), value);
    for (i = 0; i < 9; i++)
        printf("%s%d", i ? " " : "", lines[i]);
    printf("]\n");
    return ansToggle;
}

static int32_t is_cd(void)
{
    printf("cd\n");
    return ansCD;
}

static int32_t dmr_can_test(void)
{
    printf("dmr cantest\n");
    return ansCanTest;
}

static void dmr_begin_test(void)
{
    printf("dmr begintest\n");
}

static int32_t dmr_goes_on(void)
{
    printf("dmr goeson\n");
    return ansGoesOn;
}

static void dmr_service(int32_t forward)
{
    printf("dmr service %d\n", forward);
}

static void dmr_end(void)
{
    printf("dmr end\n");
}

static void dmr_begin_rec(void)
{
    printf("dmr beginrec\n");
}

static void dmr_end_rec(int32_t keep)
{
    printf("dmr endrec %d\n", keep);
}

static int32_t language(void)
{
    return 0;
}

// ------------------------------------------------------------ the ops

static void set_snaps(char *spec)
{
    char *t;

    numSnaps = 0;
    if (!strcmp(spec, "-"))
        return;
    // The line's own fields are split already.
    for (t = strtok(spec, ";"); t && numSnaps < MAX_SNAPS;
         t = strtok(NULL, ";")) {
        ReplaySnapshot *s = &snaps[numSnaps++];
        int n = 0, tm = 0, end = 0;

        sscanf(t, "%d:%d:%d", &n, &tm, &end);
        memset(s->Name, 0, sizeof s->Name);
        if (n >= 0 && n < NUM_SNAP_NAMES)
            snprintf(s->Name, sizeof s->Name, "%s", kSnapNames[n]);
        s->Time = tm;
        s->EndTime = end;
    }
}

static void dump_marker(const ReplayScreenMarker *m)
{
    printf(" [0x%08x 0x%08x %s %s]", bitsf(m->BeginTime), bitsf(m->EndTime),
           label(m->pObject), label(m->pSnapshot));
}

static void dump(void)
{
    const ReplayScreen *s = screen;
    int i;

    printf("screen 0x%08x 0x%08x %d %d %d %d %d %d %d\n",
           bitsf(s->BeginningOfTime), bitsf(s->EndOfTime),
           s->TimelinePositionX, s->TimelineWidthX, s->HideTimeline,
           s->PlayerNumber, s->CameraMode, s->LastJoyLoop,
           s->ReplayEndedTime);
    printf("laps %d", s->NumLapMarkers);
    for (i = 0; i < s->NumLapMarkers && i < REPLAY_SCREEN_MAX_MARKERS; i++)
        dump_marker(&s->LapMarkers[i]);
    printf("\nhighlights %d", s->NumHighlightMarkers);
    for (i = 0; i < s->NumHighlightMarkers && i < REPLAY_SCREEN_MAX_MARKERS;
         i++)
        dump_marker(&s->HighlightMarkers[i]);
    printf("\nobjs %s %s %s %s\n", label(s->pTimeMarkerBitmap),
           label(s->pDemoModeIndicator[0]), label(s->pDemoModeIndicator[1]),
           label(s->pDemoModeIndicator[2]));
    printf("cams %s %s %s\n", label(s->pDriveCameraMover),
           label(s->pDemoCameraCoordinator),
           label(s->pNisCameraCoordinator));
    printf("words %d %d %d %d %d\n", pReplayManager->PausedFlag,
           pReplayManager->SlowMotionFlag,
           DemoModeReplay_WantToBeErasingSnapshot,
           DemoDiscManager_InactiveTimeout, DemoDiscManager_TotalTimeout);
}

int main(int argc, char **argv)
{
    static char line[1024];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: replayscreen_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < 12; i++) {
        objHash[i] = kObjHashes[i];
        snprintf(objName[i], sizeof objName[i], "%s", kObjNames[i]);
    }
    for (i = 0; i < 16; i++) {
        snprintf(objName[12 + i], sizeof objName[12 + i], "LAP_MARKER%d",
                 i + 1);
        snprintf(objName[28 + i], sizeof objName[28 + i],
                 "HIGHLIGHT_MARKER%d", i + 1);
        objHash[12 + i] = bchunk_hash(objName[12 + i]);
        objHash[28 + i] = bchunk_hash(objName[28 + i]);
    }
    for (i = 0; i < 2; i++) {
        PlayerPlayersByNumber[i] = &players[i];
        players[i].MyCar = &cars[i];
        players[i].pNisManager = (struct NisManager *)nisManagers[i];
        cars[i].pCarTypeInfo = &carTypes[i];
        cars[i].pCarDriver = (CarDriver *)drivers[i];
    }
    moverVtbl.Destroy = mover_destroy;
    pReplayManager = &rmMem;
    pRaceCoordinator = &rcMem;
    pCurrentRace = &raceMem;
    gSetFlailerScreenVisibilityFn = screen_visibility;
    gSoundMuteReplayFn = mute_replay;
    gNisCreateCameraCoordinatorFn = nis_create;
    gNisDeleteCameraCoordinatorFn = nis_delete;
    gCameraCoordinatorDeleteFn = coord_delete;
    gDemoCameraCoordinatorCtorFn = demo_coord;
    gDriveCameraMoverFn = drive_mover;
    gCurrLanguageFn = language;
    gReplayScreenPlaySampleFn = play_sample;
    gReplayScreenFrontendSoundFn = frontend_sound;
    gReplayScreenHelpActiveFn = help_active;
    gReplayScreenToggleHelpFn = help_toggle;
    gReplayScreenIsThereACDFn = is_cd;
    gReplayScreenRadialBlurFn = radial_blur;
    gDemoModeReplayCanTestFn = dmr_can_test;
    gDemoModeReplayBeginTestFn = dmr_begin_test;
    gDemoModeReplayTestGoesOnFn = dmr_goes_on;
    gDemoModeReplayServiceDemoModeFn = dmr_service;
    gDemoModeReplayEndDemoModeFn = dmr_end;
    gDemoModeReplayBeginRecordingFn = dmr_begin_rec;
    gDemoModeReplayEndRecordingFn = dmr_end_rec;

    while (fgets(line, sizeof line, sc)) {
        char *arg[16];
        const char *op;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 16; t = strtok(NULL, "|"))
            arg[n++] = t;
        op = arg[0];
        if (!strcmp(op, "tag")) {
            // a heading in the transcript
        } else if (!strcmp(op, "rm")) {
            rmMem.PausedFlag = (int32_t)num(arg[1]);
            rmMem.SlowMotionFlag = (int32_t)num(arg[2]);
            rmMem.EndCapturingLoopCount = (int32_t)num(arg[3]);
            rmMem.BeginningOfTime = (int32_t)num(arg[4]);
            rmMem.EndOfTime = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "time")) {
            WorldLoopCounter = (int32_t)num(arg[1]);
            WorldTimer = (int32_t)num(arg[2]);
            RealLoopCounter = (int32_t)num(arg[3]);
            RealTimeFrames = (int32_t)num(arg[4]);
            RealTimer = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "race")) {
            raceMem.NumLapsInRace = (int32_t)num(arg[1]);
            raceMem.NumRacingCars = (int32_t)num(arg[2]);
            raceMem.RaceTime.PackedTime = (uint32_t)num(arg[3]);
            TheRaceParameters.Point2Point = (int32_t)num(arg[4]);
        } else if (!strcmp(op, "players")) {
            PlayerNumPlayers = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "player")) {
            i = (int)num(arg[1]);
            players[i].nZoneCurrent = (int32_t)num(arg[2]);
            cars[i].TheControlMode = (ControlMode)num(arg[3]);
            carTypes[i].UsageType = (int32_t)num(arg[4]);
            nitroAnswer[i] = (int32_t)num(arg[5]);
            nisAnswer[i] = (int32_t)num(arg[6]);
            racingCars[i].NumLapsCompleted = (int8_t)num(arg[7]);
            racingCars[i].RacePosition = (int8_t)num(arg[8]);
            racingCars[i].FinishReason = (int16_t)num(arg[9]);
        } else if (!strcmp(op, "objs")) {
            objMask = (uint64_t)strtoull(arg[1], NULL, 0);
        } else if (!strcmp(op, "objx")) {
            i = (int)num(arg[1]);
            objs[i].X = fbits((uint32_t)num(arg[2]));
            objWidth[i] = fbits((uint32_t)num(arg[3]));
        } else if (!strcmp(op, "snaps")) {
            set_snaps(arg[1]);
        } else if (!strcmp(op, "dmr")) {
            DemoModeReplay_WantToBeErasingSnapshot = (int32_t)num(arg[1]);
            DemoModeReplay_pCurrentRecordingSnapshot =
                num(arg[2]) ? &snaps[MAX_SNAPS - 1] : NULL;
            DemoModeReplay_pCurrentPlayingSnapshot =
                num(arg[3]) ? &snaps[MAX_SNAPS - 2] : NULL;
        } else if (!strcmp(op, "ans")) {
            ansHelp = (int32_t)num(arg[1]);
            ansToggle = (int32_t)num(arg[2]);
            ansCD = (int32_t)num(arg[3]);
            ansCanTest = (int32_t)num(arg[4]);
            ansGoesOn = (int32_t)num(arg[5]);
            ansNis = (int32_t)num(arg[6]);
        } else if (!strcmp(op, "egs")) {
            rcMem.pEndGameScreens =
                num(arg[1]) ? (void *)endGameScreens : NULL;
        } else if (!strcmp(op, "ctor")) {
            screen = replayscreen_construct(slot_alloc(),
                                            (int32_t)num(arg[1]));
            printf("-> %s\n", label(screen));
        } else if (!strcmp(op, "dtor")) {
            replayscreen_destroy(screen, (int32_t)num(arg[1]));
        } else if (!strcmp(op, "markers")) {
            replayscreen_setup_markers(screen, (int32_t)num(arg[1]));
        } else if (!strcmp(op, "watch")) {
            printf("-> %d\n", replayscreen_should_watch_nis(screen));
        } else if (!strcmp(op, "stopnis")) {
            replayscreen_stop_watching_nis(screen);
        } else if (!strcmp(op, "has")) {
            printf("-> %d\n", replayscreen_has_camera_mover(screen));
        } else if (!strcmp(op, "change")) {
            replayscreen_change_camera_mover(screen);
        } else if (!strcmp(op, "tick")) {
            replayscreen_tick(screen);
        } else if (!strcmp(op, "update")) {
            replayscreen_update(screen);
        } else if (!strcmp(op, "add")) {
            replayscreen_add_joy_handlers(screen, (JoystickPort)num(arg[1]));
        } else if (!strcmp(op, "remove")) {
            replayscreen_remove_joy_handlers(screen,
                                             (JoystickPort)num(arg[1]));
        } else if (!strcmp(op, "joy")) {
            replayscreen_joy_handler(screen, (JoystickPort)num(arg[1]),
                                     (JoyEvent)num(arg[2]),
                                     (uint8_t)num(arg[3]));
        } else if (!strcmp(op, "bridge")) {
            replayscreen_joy_handler_bridge((JoystickPort)num(arg[1]),
                                            (JoyEvent)num(arg[2]),
                                            (uint8_t)num(arg[3]), screen);
        } else if (!strcmp(op, "posx")) {
            printf("-> %d\n", replayscreen_timeline_position_x(
                                  screen, fbits((uint32_t)num(arg[1]))));
        } else if (!strcmp(op, "bmpos")) {
            i = (int)num(arg[1]);
            replayscreen_set_bitmap_position(
                screen,
                i < 0 ? NULL : (struct FlailerBitmapChunk *)&objs[i],
                fbits((uint32_t)num(arg[2])));
        } else if (!strcmp(op, "pause")) {
            replayscreen_pause(screen, (int32_t)num(arg[1]));
        } else if (!strcmp(op, "dump")) {
            dump();
        } else {
            printf("unknown op %s\n", op);
        }
    }
    return 0;
}
