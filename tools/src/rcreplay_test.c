// Drives rcreplay.c for tools/rcreplay_check.py. A script of ops, one per
// line, fields split on '|':
//
//   rc|EGS|SCREEN      pRaceCoordinator's pEndGameScreens (1 set, 0 NULL)
//                      and pReplayScreen (1 an old screen, SCR; 0 NULL)
//   players|N          PlayerNumPlayers
//   player|I|NUMBER    player I's PlayerNumber
//   pmenu|ON|CHOOSER   ThePauseMenu set or NULL, and its ReplayChooser
//   driver|N|ON|FP|UDN what TransientStats::GetDriver answers for driver
//                      number N (0..3): NULL, or an element with that
//                      FinishPosition and UniqueDriveNumber
//   ans|TAKE|LAP|IR|PRESENT  what TakeSnapshot answers (1 snapshot S0, 0
//                      NULL), and RestoreSnapshot by each name
//   msg|MSG|PARAM      the state's callback, on pRaceCoordinator
//   move|K             RC_MOVE_REPLAY with snapshot K's address as param
//   dump               pRaceCoordinator's pReplayScreen
//   tag|TEXT           nothing: a heading in the transcript
//
// Every call out of rcreplay.c prints what it was asked, as the model's
// stubs at retail's addresses do.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "fred.h"
#include "pausemenu.h"
#include "player.h"
#include "playercam.h"
#include "racecoord.h"
#include "rcpost.h"
#include "rcreplay.h"
#include "rcstates.h"
#include "replay.h"
#include "replaymgr.h"
#include "replayscreen.h"

#define NUM_SNAPS   4
#define NUM_DRIVERS 4

// ------------------------------------------------------- the globals

ReplayManager *pReplayManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByIndex[2];
struct PauseMenu *ThePauseMenu;
void (*gSoundMuteFn)(int32_t on);
const TransientStatsElement *(*gTransientStatsGetDriverFn)(
    int32_t driverNumber);
void (*gRestoreTypeChangedHandlersFn)(void);

static ReplayManager rmMem;
static RaceCoordinator rcMem;
static PauseMenu pmMem;
static struct Player players[2];
static ReplaySnapshot snaps[NUM_SNAPS];
static TransientStatsElement drivers[NUM_DRIVERS];
static int driverOn[NUM_DRIVERS];
static uint8_t screenMem[REPLAY_SCREEN_SIZE];
static uint8_t oldScreen[16];
static uint8_t egsMem[16];

static int ansTake, ansLap, ansIR, ansPresent;

static const char *label(const void *p)
{
    static char buf[4][32];
    static int k;
    char *b = buf[k++ & 3];
    int i;

    if (p == NULL)
        return "NULL";
    if (p == screenMem)
        return "M";
    if (p == oldScreen)
        return "SCR";
    if (p == &rmMem)
        return "RM";
    if (p == &rcMem)
        return "RC";
    for (i = 0; i < 2; i++)
        if (p == &players[i]) {
            snprintf(b, 32, "P%d", i);
            return b;
        }
    for (i = 0; i < NUM_SNAPS; i++)
        if ((uint32_t)(uintptr_t)p == (uint32_t)(uintptr_t)&snaps[i]) {
            snprintf(b, 32, "S%d", i);
            return b;
        }
    snprintf(b, 32, "%d", (int)(int32_t)(intptr_t)p);
    return b;
}

// ------------------------------------------------------- the stubs

void *bMalloc(int size, const char *name, int flags, int pool)
{
    printf("  malloc %d %s %d %d\n", size, name, flags, pool);
    return screenMem;
}

ReplaySnapshot *replaymgr_take_snapshot(ReplayManager *rm, const char *name)
{
    printf("  take %s %s\n", label(rm), name);
    return ansTake ? &snaps[0] : NULL;
}

int32_t replaymgr_restore_snapshot_named(ReplayManager *rm, const char *name)
{
    printf("  restore %s %s\n", label(rm), name);
    if (strcmp(name, "LAP_SNAPSHOT") == 0)
        return ansLap;
    if (strcmp(name, "INSTANT_REPLAY") == 0)
        return ansIR;
    if (strcmp(name, "THE_PRESENT") == 0)
        return ansPresent;
    return 0;
}

int32_t replaymgr_delete_snapshot_named(ReplayManager *rm, const char *name)
{
    printf("  delete %s %s\n", label(rm), name);
    return 0;
}

void replaymgr_restore_snapshot(ReplayManager *rm, ReplaySnapshot *s)
{
    printf("  restore %s %s\n", label(rm), label(s));
}

ReplayScreen *replayscreen_construct(void *mem, int32_t playerNumber)
{
    printf("  screen ctor %s %d\n", label(mem), (int)playerNumber);
    return (ReplayScreen *)mem;
}

void replayscreen_destroy(ReplayScreen *s, int32_t flags)
{
    printf("  screen dtor %s %d\n", label(s), (int)flags);
}

void replayscreen_tick(ReplayScreen *s)
{
    printf("  screen tick %s\n", label(s));
}

void replayscreen_change_camera_mover(ReplayScreen *s)
{
    printf("  screen camera %s\n", label(s));
}

void player_disable_camera_movers(struct Player *p)
{
    printf("  disable %s\n", label(p));
}

void player_enable_camera_movers(struct Player *p)
{
    printf("  enable %s\n", label(p));
}

void racecoordinator_change_state(RaceCoordinator *rc, RCState state)
{
    printf("  change %s %d\n", label(rc), (int)state);
}

static void mute(int32_t on)
{
    printf("  mute %d\n", (int)on);
}

static const TransientStatsElement *get_driver(int32_t n)
{
    printf("  driver %d\n", (int)n);
    if (n < 0 || n >= NUM_DRIVERS || !driverOn[n])
        return NULL;
    return &drivers[n];
}

static void type_handlers(void)
{
    printf("  type handlers\n");
}

// ------------------------------------------------------- the script

static int field(char **f, int n, int i)
{
    return i < n ? (int)strtol(f[i], NULL, 0) : 0;
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
    if (strcmp(f[0], "rc") == 0) {
        rcMem.pEndGameScreens =
            field(f, n, 1) ? (struct EndGameScreens *)egsMem : NULL;
        rcMem.pReplayScreen = field(f, n, 2) ? oldScreen : NULL;
    } else if (strcmp(f[0], "players") == 0) {
        PlayerNumPlayers = field(f, n, 1);
    } else if (strcmp(f[0], "player") == 0) {
        players[field(f, n, 1)].PlayerNumber = field(f, n, 2);
    } else if (strcmp(f[0], "pmenu") == 0) {
        ThePauseMenu = field(f, n, 1) ? &pmMem : NULL;
        pmMem.ReplayChooser = field(f, n, 2);
    } else if (strcmp(f[0], "driver") == 0) {
        int k = field(f, n, 1);

        driverOn[k] = field(f, n, 2);
        drivers[k].FinishPosition = field(f, n, 3);
        drivers[k].UniqueDriveNumber = field(f, n, 4);
    } else if (strcmp(f[0], "ans") == 0) {
        ansTake = field(f, n, 1);
        ansLap = field(f, n, 2);
        ansIR = field(f, n, 3);
        ansPresent = field(f, n, 4);
    } else if (strcmp(f[0], "msg") == 0) {
        int32_t r = rc_state_instant_replay_callback(
            &rcMem, (RCMessage)field(f, n, 1), field(f, n, 2));

        printf("  -> %d\n", (int)r);
    } else if (strcmp(f[0], "move") == 0) {
        int32_t r = rc_state_instant_replay_callback(
            &rcMem, RC_MOVE_REPLAY,
            (int32_t)(intptr_t)&snaps[field(f, n, 1)]);

        printf("  -> %d\n", (int)r);
    } else if (strcmp(f[0], "dump") == 0) {
        printf("  screen %s\n", label(rcMem.pReplayScreen));
    } else {
        printf("  unknown op %s\n", f[0]);
    }
}

int main(int argc, char **argv)
{
    static char line[1024];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: rcreplay_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < 2; i++)
        PlayerPlayersByIndex[i] = &players[i];
    pReplayManager = &rmMem;
    ThePauseMenu = &pmMem;
    gSoundMuteFn = mute;
    gTransientStatsGetDriverFn = get_driver;
    gRestoreTypeChangedHandlersFn = type_handlers;

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
