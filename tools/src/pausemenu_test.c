// Drives pausemenu.c for tools/pausemenu_check.py. A script of ops, one
// per line, fields split on '|':
//
//   player|I|PORT|NUM|SEED  player I's JoyPort and PlayerNumber, and its
//                      PlayerSettings filled from SEED
//   bynum|A|B          PlayersByNumber[0] and [1], players by index, -1 NULL
//   byidx|N|A|B        NumPlayers and PlayersByIndex[0] and [1]
//   pset|SEED          TheRaceParameters.PlayerSettings filled from SEED
//   plug|PORT|V        what IsJoystickPluggedIn(PORT) answers (default 1)
//   rp|CARS|OBJ|TREE|COP  NumPlayerCars, HasObjective, EventTreeRace and
//                      BeACop
//   free|V, fin|V      what IsFreeRun and AreAllPlayersFinishedRacing answer
//   replay|COUNT|MUTE  the replay's snapshot count and its word at +12
//   rc|PORT            pRaceCoordinator's PausedJoystickPort
//   cur|N              the Flailer's current screen: 0 none, 1 the one up
//   pm|STATE|HASH|PORT|OPT|REP|PLAYER  ThePauseMenu's fields
//   ctor               the constructor, over 0xcd bytes
//   dtor|FLAGS         the destructor
//   enter|PORT, exit, activate|HASH, deactivate, plugged, check, restart,
//   quit, resume|PORT  the class's members on ThePauseMenu
//   who|PORT           ChooseWhoSelectedMenuItem, the data's port PORT
//   menu|MSG|ITEM|PORT|PARAM|NOISE  MenuCallback
//   cb|MSG|ITEM|PORT|PARAM|NOISE    PauseMenuCallback
//   hl|MSG|ITEM        tHighlightAnimation::HandleMessage on the bloom
//   dump               ThePauseMenu and TheRaceParameters.PlayerSettings
//
// Every call out of pausemenu.c prints what it was asked, as the model's
// stubs at retail's addresses do.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "banim.h"
#include "bmem.h"
#include "flailer.h"
#include "joyevent.h"
#include "pausemenu.h"
#include "player.h"
#include "race.h"
#include "racecoord.h"
#include "racefinish.h"
#include "raceparams.h"
#include "rcpost.h"
#include "rcstates.h"
#include "replay.h"
#include "trackflow.h"

#define NUM_PLAYERS 4
#define NUM_PORTS   8

// What pausemenu.c reads.
Race *pCurrentRace;
RaceCoordinator *pRaceCoordinator;
RaceParameters TheRaceParameters;
struct PauseMenu *ThePauseMenu;
ReplayManager *pReplayManager;
int32_t PlayerNumPlayers;
struct Player *PlayerPlayersByNumber[2];
struct Player *PlayerPlayersByIndex[2];
void (*gChangeToScreenFn)(const char *name, int32_t push);
int32_t (*gReplayMuteHighlightsFn)(const struct ReplayManager *rm);
void (*gRestoreTypeChangedHandlersFn)(void);
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);

static uint64_t raceMem[64];
static RaceCoordinator rcMem;
static ReplayManager rmMem;
static PauseMenu pmMem;
static struct Player players[NUM_PLAYERS];
static int32_t plugged[NUM_PORTS];
static int32_t freeRun, finished, replayCount, replayMute;
static int32_t screenUp;
static uint64_t curScreen[4];
static BAnim theAnim;
static char trBuf[32];

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
}

static struct Player *player_at(int64_t i)
{
    return i < 0 ? NULL : &players[i];
}

static int player_index(const struct Player *p)
{
    int i;

    for (i = 0; i < NUM_PLAYERS; i++)
        if (p == &players[i])
            return i;
    return p == NULL ? -1 : 99;
}

static void fill(void *dst, size_t n, uint32_t seed)
{
    uint8_t *b = dst;
    size_t i;

    for (i = 0; i < n; i++)
        b[i] = (uint8_t)(seed + i * 7);
}

// ------------------------------------------------------------ the stubs

static void gray(uint32_t item, int32_t mode, uint32_t screen)
{
    printf("  gray %08x %d %08x\n", (unsigned)item, (int)mode,
           (unsigned)screen);
}

static void filter(const char *name, JoystickPort port)
{
    printf("  filter %s %d\n", name, (int)port);
}

static void stop_force(JoystickPort port)
{
    printf("  stopforce %d\n", (int)port);
}

static void change_to_screen(const char *name, int32_t push)
{
    printf("  change %s %d\n", name, (int)push);
}

static void visibility(uint32_t screen, int v)
{
    printf("  vis %08x %d\n", (unsigned)screen, v);
}

static const char *translate(int32_t id)
{
    printf("  tr %x\n", (unsigned)id);
    snprintf(trBuf, sizeof trBuf, "T%x", (unsigned)id);
    return trBuf;
}

static const struct BScreenConfig *current_screen(void)
{
    return screenUp ? (const struct BScreenConfig *)curScreen : NULL;
}

static void summon(const BPopupConfig *c)
{
    printf("  summon %d %x %s %08x %s %x %x %x %d %d %d %d %d %d %d %x\n",
           (int)c->numButtons, (unsigned)c->flags,
           c->parent == NULL ? "NULL"
           : c->parent == (const struct BScreenConfig *)curScreen ? "cur"
           : "?",
           (unsigned)c->screen, c->message != NULL ? c->message : "NULL",
           (unsigned)c->button[0], (unsigned)c->button[1],
           (unsigned)c->button[2], (int)c->buttonParam[0],
           (int)c->buttonParam[1], (int)c->buttonParam[2],
           (int)c->cancelParam, (int)c->startButton, (int)c->joyPort,
           (int)c->timeout, (unsigned)c->title);
}

static BAnim *the_anim(void)
{
    return &theAnim;
}

static int32_t num_snapshots(const struct ReplayManager *rm)
{
    return rm == &rmMem ? replayCount : -99;
}

static int32_t mute_highlights(const struct ReplayManager *rm)
{
    return rm == &rmMem ? replayMute : -99;
}

static void restore(void)
{
    printf("  restore\n");
}

void racecoordinator_request_unpause(RaceCoordinator *rc,
                                     UnPauseReasonType reason)
{
    printf("  unpause %s %d\n", rc == &rcMem ? "rc" : "?", (int)reason);
}

int32_t IsJoystickPluggedIn(JoystickPort port)
{
    printf("  isplug %d\n", (int)port);
    return port >= 0 && port < NUM_PORTS ? plugged[port] : 0;
}

int32_t race_are_all_players_finished_racing(const Race *r)
{
    printf("  finished %s\n", r == (const Race *)raceMem ? "race" : "?");
    return finished;
}

int32_t race_parameters_is_free_run(const RaceParameters *rp)
{
    printf("  freerun %s\n", rp == &TheRaceParameters ? "rp" : "?");
    return freeRun;
}

void flailer_set_language_id(uint32_t screen, uint32_t object,
                             uint32_t languageId)
{
    printf("  lang %08x %08x %x\n", (unsigned)screen, (unsigned)object,
           (unsigned)languageId);
}

// The bloom's offset in retail's PauseMenu, 24; a 64-bit host has it at 32.
static int hl_off(const BHighlightAnim *h)
{
    return h == &ThePauseMenu->Highlight
           ? 24 : (int)((const char *)h - (const char *)ThePauseMenu);
}

void banim_highlight_init(BAnim *a, BHighlightAnim *h, uint32_t screen,
                          uint32_t textObject, int32_t targetColor)
{
    printf("  hl_init %s %d %08x %08x %x\n", a == &theAnim ? "anim" : "?",
           hl_off(h), (unsigned)screen, (unsigned)textObject,
           (unsigned)targetColor);
}

void banim_highlight_set_item(BAnim *a, BHighlightAnim *h, uint32_t item)
{
    printf("  hl_item %s %d %08x\n", a == &theAnim ? "anim" : "?",
           hl_off(h), (unsigned)item);
}

void banim_highlight_animate(BAnim *a, BHighlightAnim *h)
{
    printf("  hl_anim %s %d\n", a == &theAnim ? "anim" : "?", hl_off(h));
}

void bFree(void *p)
{
    printf("  delete %s\n", p == ThePauseMenu ? "pm" : "?");
}

// ------------------------------------------------------------ the ops

static void data_from(BScreenCallbackData *d, char **arg)
{
    d->itemHash = (uint32_t)num(arg[0]);
    d->port = (int32_t)num(arg[1]);
    d->param = (int32_t)num(arg[2]);
    d->noise = (int32_t)num(arg[3]);
}

static void print_data(const BScreenCallbackData *d)
{
    printf("  data %08x %d %d %d\n", (unsigned)d->itemHash, (int)d->port,
           (int)d->param, (int)d->noise);
}

static void dump(void)
{
    const PauseMenu *m = ThePauseMenu;
    const uint8_t *b = (const uint8_t *)TheRaceParameters.PlayerSettings;
    int i;

    printf("  pm %d %08x %d %d %d %d\n", (int)m->State,
           (unsigned)m->ScreenHash, (int)m->Port, (int)m->OptionsChooser,
           (int)m->ReplayChooser, player_index(m->PausingPlayer));
    printf("  pset");
    for (i = 0; i < (int)sizeof TheRaceParameters.PlayerSettings; i++)
        printf("%s%02x", i % 48 ? "" : " ", b[i]);
    printf("\n");
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: pausemenu_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    pCurrentRace = (Race *)raceMem;
    pRaceCoordinator = &rcMem;
    pReplayManager = &rmMem;
    ThePauseMenu = &pmMem;
    for (i = 0; i < NUM_PORTS; i++)
        plugged[i] = 1;
    gGrayMenuItemFn = gray;
    gSetScreenFilterPortFn = filter;
    gPortStopForceFn = stop_force;
    gSummonPopupFn = summon;
    gFlailerCurrentScreenFn = current_screen;
    gPauseTranslateFn = translate;
    gPauseMenuAnimFn = the_anim;
    gReplayNumInstantReplaySnapshotsFn = num_snapshots;
    gChangeToScreenFn = change_to_screen;
    gReplayMuteHighlightsFn = mute_highlights;
    gRestoreTypeChangedHandlersFn = restore;
    gSetFlailerScreenVisibilityFn = visibility;

    while (fgets(line, sizeof line, sc)) {
        char *arg[16];
        const char *op;
        BScreenCallbackData data;
        PauseMenu *m = ThePauseMenu;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 16; t = strtok(NULL, "|"))
            arg[n++] = t;
        op = arg[0];
        if (!strcmp(op, "player")) {
            struct Player *p = &players[num(arg[1])];

            p->JoyPort = (JoystickPort)num(arg[2]);
            p->PlayerNumber = (int32_t)num(arg[3]);
            fill(&p->PlayerSettings, sizeof p->PlayerSettings,
                 (uint32_t)num(arg[4]));
        } else if (!strcmp(op, "bynum")) {
            PlayerPlayersByNumber[0] = player_at(num(arg[1]));
            PlayerPlayersByNumber[1] = player_at(num(arg[2]));
        } else if (!strcmp(op, "byidx")) {
            PlayerNumPlayers = (int32_t)num(arg[1]);
            PlayerPlayersByIndex[0] = player_at(num(arg[2]));
            PlayerPlayersByIndex[1] = player_at(num(arg[3]));
        } else if (!strcmp(op, "pset")) {
            fill(TheRaceParameters.PlayerSettings,
                 sizeof TheRaceParameters.PlayerSettings,
                 (uint32_t)num(arg[1]));
        } else if (!strcmp(op, "plug")) {
            plugged[num(arg[1])] = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "rp")) {
            TheRaceParameters.NumPlayerCars = (int32_t)num(arg[1]);
            TheRaceParameters.HasObjective = (int32_t)num(arg[2]);
            TheRaceParameters.EventTreeRace = (int32_t)num(arg[3]);
            TheRaceParameters.BeACop = (int32_t)num(arg[4]);
        } else if (!strcmp(op, "free")) {
            freeRun = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "fin")) {
            finished = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "replay")) {
            replayCount = (int32_t)num(arg[1]);
            replayMute = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "rc")) {
            rcMem.PausedJoystickPort = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "cur")) {
            screenUp = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "pm")) {
            m->State = (int32_t)num(arg[1]);
            m->ScreenHash = (uint32_t)num(arg[2]);
            m->Port = (JoystickPort)num(arg[3]);
            m->OptionsChooser = (int32_t)num(arg[4]);
            m->ReplayChooser = (int32_t)num(arg[5]);
            m->PausingPlayer = player_at(num(arg[6]));
        } else if (!strcmp(op, "ctor")) {
            memset(m, 0xcd, sizeof *m);
            if (pause_menu_construct(m) != m)
                printf("  ctor returned another\n");
        } else if (!strcmp(op, "dtor")) {
            pause_menu_destroy(m, (int32_t)num(arg[1]));
        } else if (!strcmp(op, "enter")) {
            pause_menu_enter_pause(m, (JoystickPort)num(arg[1]));
        } else if (!strcmp(op, "exit")) {
            pause_menu_exit_pause(m);
        } else if (!strcmp(op, "activate")) {
            pause_menu_activate(m, (uint32_t)num(arg[1]));
        } else if (!strcmp(op, "deactivate")) {
            pause_menu_deactivate(m);
        } else if (!strcmp(op, "plugged")) {
            printf("  = %d\n",
                   (int)pause_menu_all_player_joysticks_plugged_in(m));
        } else if (!strcmp(op, "check")) {
            pause_menu_check_joysticks(m);
        } else if (!strcmp(op, "restart")) {
            pause_menu_maybe_restart(m);
        } else if (!strcmp(op, "quit")) {
            pause_menu_maybe_quit(m);
        } else if (!strcmp(op, "resume")) {
            printf("  = %d\n",
                   (int)pause_menu_maybe_resume(m, (int32_t)num(arg[1])));
        } else if (!strcmp(op, "who")) {
            memset(&data, 0, sizeof data);
            data.port = (int32_t)num(arg[1]);
            printf("  = %d\n", (int)pause_choose_who_selected_menu_item(&data));
        } else if (!strcmp(op, "menu")) {
            data_from(&data, arg + 2);
            pause_menu_menu_callback(m, (BScreenMessage)num(arg[1]), &data);
            print_data(&data);
        } else if (!strcmp(op, "cb")) {
            data_from(&data, arg + 2);
            pause_menu_callback(NULL, (BScreenMessage)num(arg[1]), &data);
            print_data(&data);
        } else if (!strcmp(op, "hl")) {
            memset(&data, 0, sizeof data);
            data.itemHash = (uint32_t)num(arg[2]);
            pause_highlight_handle_message(&m->Highlight,
                                           (BScreenMessage)num(arg[1]),
                                           &data);
        } else if (!strcmp(op, "dump")) {
            dump();
        } else {
            fprintf(stderr, "unknown op %s\n", op);
            return 3;
        }
    }
    fclose(sc);
    return 0;
}
