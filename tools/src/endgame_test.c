// Drives endgame.c for tools/endgame_check.py. A script of ops, one per
// line, fields split on '|':
//
//   fred|GT|CARS|AUTO|PTS|TASK  Fred's GameType, NumPlayerCars, Autosave
//                      and the TransientStats' two reward words
//   rp|TYPE|P2P|LAPS|CARS|TREE|COP  TheRaceParameters' RaceType,
//                      Point2Point, NumLapsInRace, NumPlayerCars,
//                      EventTreeRace and BeACop
//   ev|NUMBER|TYPE|NREW|WORD  TheRaceEvent's nNumber, type, nRewards and
//                      word at +120
//   evf|STATUS|ADV|FELL|OPENED|ANOTHER  what the event's calls answer
//   rtest|MASK         reward i's test answers bit i of MASK
//   unlock|V           what IsCarUnlocked answers
//   replay|ON|MUTE     a ReplayManager or none, and its word at +12
//   cur|NAME           the screen up: a name from the list below, -1 none
//   probe|ON           Tourney Standings' class the probe or the bare base
//   egs|TYPE           a new EndGameScreens on a block of 0xcd
//   egsdtor|FLAGS      its destructor
//   build, next, remove|NAME, advance, atroot, back, current, resume,
//   suspend, autodone, setcb   its members
//   insname|NAME|POS   a node named NAME put before node POS, unprinted
//   t|I                test I, in the order of the model's TESTS
//   base|HASH          a bare EndGameMenusBase on a block of 0xcd
//   bh|MSG|ITEM|PORT|PARAM|NOISE  the base's HandleEvent on it
//   bdtor|FLAGS        the base's destructor on it; with no 1 in FLAGS,
//                      the vtable it left
//   cb|MSG|ITEM|PORT|PARAM|NOISE  the screens' callback
//   menu|HASH|PARAM    a new EndGameMenu on a block of 0xcd
//   mh|MSG|ITEM|PORT|PARAM|NOISE  its HandleEvent
//   mstate|S           its State
//   mdtor|FLAGS        its destructor, as bdtor's
//   labels             InitLabels into fifteen words of 0x5a
//   restart|T|M|S      MaybeRestart
//   find|HASH          FindItem
//   fire               the callback SetAutosaveCompletionCallback was given
//   dump               the list, pEndGameScreens, the instance and the menu
//
// Every call out of endgame.c prints what it was asked, as the model's
// stubs at retail's addresses do.
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "banim.h"
#include "bmem.h"
#include "bplist.h"
#include "bpopup.h"
#include "endgame.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "gameflow.h"
#include "pausemenu.h"
#include "race.h"
#include "racecoord.h"
#include "rcpost.h"
#include "replay.h"
#include "trackflow.h"

// What endgame.c reads that the linked files do not define. fred.c,
// race.c and fredrace.c would bring most of the game with them, so their
// globals are here, and fredrace.c's UseTheRaceEvent with them, as
// fredrace_check checks it.
FrontendDatabase Fred;
RaceParameters TheRaceParameters;
RaceEvent TheRaceEvent;
int32_t (*gIsCarUnlockedFn)(int32_t carType, int32_t gameType);
int32_t (*gRaceEventGetStatusFn)(void);
int32_t (*gRaceEventIsThereAnotherRaceFn)(void);

int32_t fred_use_the_race_event(const FrontendDatabase *f)
{
    int32_t t = f->GameType;

    return t == 4 || (t >= 8 && t < 10);
}

RaceCoordinator *pRaceCoordinator;
ReplayManager *pReplayManager;
void (*gChangeToScreenFn)(const char *name, int32_t push);
int32_t (*gReplayMuteHighlightsFn)(const struct ReplayManager *rm);
void (*gSetFlailerScreenVisibilityFn)(uint32_t screen, int visibility);
void (*gGrayMenuItemFn)(uint32_t item, int32_t mode, uint32_t screen);
void (*gSummonPopupFn)(const BPopupConfig *cfg);
const struct BScreenConfig *(*gFlailerCurrentScreenFn)(void);

#define NUM_SLOTS  4096
#define SLOT_SIZE  256
#define NUM_NODES  4096

static const char *const kNames[] = {
    "Points Rewards", "Task Rewards", "Events Unlocked", "Reward menu",
    "Race Results", "Tourney Standings", "Best Lap Times",
    "Best Total Times", "Autosave", "Be The Cop Results 1P",
    "Be The Cop Results 2P", "Lap Times 1P", "Lap Times 2P",
    "End Game Menu", "Nothing", "Pause Menu",
};
#define NUM_NAMES ((int)(sizeof kNames / sizeof kNames[0]))

static RaceCoordinator rcMem;
static ReplayManager rmMem;
static int32_t replayMute;
static uint64_t slots[NUM_SLOTS][SLOT_SIZE / 8];
static uint8_t slotUsed[NUM_SLOTS];
static bPNode nodes[NUM_NODES];
static uint8_t nodeUsed[NUM_NODES];
static char nameBufs[NUM_NAMES][32];
static BScreenConfig curCfg;
static int32_t screenUp;
static BAnim theAnim;
static char trBuf[32];
static int32_t evStatus, evAdvanced, evFell, evOpened, evAnother;
static uint32_t rtestMask;
static int32_t unlockAnswer;
static void (*autosaveCb)(void);
static EndGameScreens *egs;
static EndGameMenusBase *obj;

static int64_t num(const char *s)
{
    return strtoll(s, NULL, 0);
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
    exit(4);
}

static void print_label(const void *p)
{
    int s = slot_of(p);

    if (p == NULL)
        printf("NULL");
    else if (s >= 0)
        printf("m%d+%d", s, (int)((const uint8_t *)p - (const uint8_t *)slots[s]));
    else
        printf("?");
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p = slot_alloc();

    printf("  malloc %d %s %d %d m%d\n", size, name, flags, pool,
           slot_of(p));
    return p;
}

void bFree(void *p)
{
    int s = slot_of(p);

    printf("  delete ");
    print_label(p);
    printf("\n");
    if (s >= 0)
        slotUsed[s] = 0;
}

static bPNode *node_alloc(void)
{
    int i;

    for (i = 0; i < NUM_NODES; i++)
        if (!nodeUsed[i]) {
            nodeUsed[i] = 1;
            return &nodes[i];
        }
    fprintf(stderr, "out of nodes\n");
    exit(4);
}

bPNode *bpnode_malloc(void)
{
    bPNode *n = node_alloc();

    printf("  pmalloc %d\n", (int)(n - nodes));
    return n;
}

void bpnode_free(void *p)
{
    bPNode *n = p;

    printf("  pfree %d\n", (int)(n - nodes));
    nodeUsed[n - nodes] = 0;
}

// ------------------------------------------------------------ the stubs

static void change_to_screen(const char *name, int32_t push)
{
    printf("  change %s %d\n", name != NULL ? name : "NULL", (int)push);
}

static void visibility(uint32_t screen, int v)
{
    printf("  vis %08x %d\n", (unsigned)screen, v);
}

void flailer_set_visibility(uint32_t screen, uint32_t object, int32_t v)
{
    printf("  objvis %08x %08x %d\n", (unsigned)screen, (unsigned)object,
           (int)v);
}

void flailer_set_language_id(uint32_t screen, uint32_t object,
                             uint32_t languageId)
{
    printf("  lang %08x %08x %x\n", (unsigned)screen, (unsigned)object,
           (unsigned)languageId);
}

static void gray(uint32_t item, int32_t mode, uint32_t screen)
{
    printf("  gray %08x %d %08x\n", (unsigned)item, (int)mode,
           (unsigned)screen);
}

static const char *translate(int32_t id)
{
    printf("  tr %x\n", (unsigned)id);
    snprintf(trBuf, sizeof trBuf, "T%x", (unsigned)id);
    return trBuf;
}

static const struct BScreenConfig *current_screen(void)
{
    return screenUp ? &curCfg : NULL;
}

static void summon(const BPopupConfig *c)
{
    printf("  summon %d %x %s %08x %s %x %x %x %d %d %d %d %d %d %d %x\n",
           (int)c->numButtons, (unsigned)c->flags,
           c->parent == NULL ? "NULL" : c->parent == &curCfg ? "cur" : "?",
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

static int32_t mute_highlights(const struct ReplayManager *rm)
{
    return rm == &rmMem ? replayMute : -99;
}

static void set_autosave_cb(void (*cb)(void))
{
    printf("  setcb\n");
    autosaveCb = cb;
}

void racecoordinator_post_message(RaceCoordinator *rc, RCMessage msg,
                                  int32_t param)
{
    printf("  post %s %d %d\n", rc == &rcMem ? "rc" : "?", (int)msg,
           (int)param);
}

static int32_t ev_status(void)
{
    printf("  status\n");
    return evStatus;
}

static int32_t ev_reward_test(int32_t i)
{
    printf("  rtest %d\n", (int)i);
    return i >= 0 && i < 32 ? (int32_t)((rtestMask >> i) & 1) : 0;
}

static int32_t ev_advanced(void)
{
    printf("  advanced\n");
    return evAdvanced;
}

static int32_t ev_fell(void)
{
    printf("  fell\n");
    return evFell;
}

static int32_t ev_opened(void)
{
    printf("  opened\n");
    return evOpened;
}

static void ev_keep(void)
{
    printf("  keep\n");
}

static void ev_restart(void)
{
    printf("  restartev\n");
}

static int32_t ev_another(void)
{
    printf("  another\n");
    return evAnother;
}

static int32_t is_unlocked(int32_t carType, int32_t gameType)
{
    printf("  unlocked %d %d\n", (int)carType, (int)gameType);
    return unlockAnswer;
}

// The bloom's offset in retail's EndGameMenu, 12.
static void print_hl(const BHighlightAnim *h)
{
    int s = slot_of(h);
    size_t off = s >= 0 ? (size_t)((const uint8_t *)h
                                   - (const uint8_t *)slots[s]) : 0;

    if (s >= 0 && off == offsetof(EndGameMenu, Highlight))
        printf("m%d+12", s);
    else
        print_label(h);
}

void banim_highlight_init(BAnim *a, BHighlightAnim *h, uint32_t screen,
                          uint32_t textObject, int32_t targetColor)
{
    printf("  hl_init %s ", a == &theAnim ? "anim" : "?");
    print_hl(h);
    printf(" %08x %08x %x\n", (unsigned)screen, (unsigned)textObject,
           (unsigned)targetColor);
}

void banim_highlight_set_item(BAnim *a, BHighlightAnim *h, uint32_t item)
{
    printf("  hl_item %s ", a == &theAnim ? "anim" : "?");
    print_hl(h);
    printf(" %08x\n", (unsigned)item);
}

void banim_highlight_animate(BAnim *a, BHighlightAnim *h)
{
    printf("  hl_anim %s ", a == &theAnim ? "anim" : "?");
    print_hl(h);
    printf("\n");
}

// --------------------------------------------------------- the probe class
//
// Tourney Standings' class, when `probe|1`: the bare base with Scroll,
// Tick and Render that say so.

static void probe_say(const char *what, EndGameMenusBase *m,
                      BScreenMessage msg)
{
    printf("  %s ", what);
    print_label(m);
    printf(" %d\n", (int)msg);
}

static void probe_scroll(EndGameMenusBase *m, BScreenMessage msg,
                         BScreenCallbackData *data)
{
    (void)data;
    probe_say("scroll", m, msg);
}

static void probe_tick(EndGameMenusBase *m, BScreenMessage msg,
                       BScreenCallbackData *data)
{
    (void)data;
    probe_say("tick", m, msg);
}

static void probe_render(EndGameMenusBase *m, BScreenMessage msg,
                         BScreenCallbackData *data)
{
    (void)data;
    probe_say("render", m, msg);
}

static const EndGameMenusVTable kProbeVTable = {
    probe_scroll,
    endgame_menus_base_handle_event,
    probe_tick,
    probe_render,
    endgame_menus_base_destroy,
};

static EndGameMenusBase *probe_ctor(void *mem, uint32_t hash,
                                    BScreenCallbackData *data)
{
    EndGameMenusBase *m = endgame_menus_base_construct(mem, hash);

    (void)data;
    m->vt = &kProbeVTable;
    return m;
}

// ------------------------------------------------------------ the dumps

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

static const char *vt_name(const EndGameMenusVTable *vt)
{
    return vt == &kEndGameMenusBaseVTable ? "base"
           : vt == &kEndGameMenuVTable ? "menu"
           : vt == &kProbeVTable ? "probe" : "?";
}

static int node_index(const bNode *n)
{
    const bPNode *p = (const bPNode *)n;

    return p >= nodes && p < nodes + NUM_NODES ? (int)(p - nodes) : -1;
}

static void dump_egs(void)
{
    const bNode *n;
    int i = 0, cur = -2;

    if (egs == NULL) {
        printf("  egs none\n");
        return;
    }
    printf("  egs %d %08x %d [", (int)egs->ScreensEnabled,
           (unsigned)egs->LatestConstructed, (int)egs->ContinueRaceType);
    for (n = egs->ScreenList.next; n != &egs->ScreenList; n = n->next, i++) {
        printf("%s%s", i ? "," : "", (const char *)((const bPNode *)n)->Object);
        if (n == egs->CurrentScreen)
            cur = i;
    }
    if (egs->CurrentScreen == &egs->ScreenList)
        cur = -1;
    printf("] cur %d z", cur);
    for (i = 0; i < 12; i++)
        printf(" %x", (unsigned)egs->Zeroed[i]);
    printf("\n");
    (void)node_index;
}

static void dump_menu(const char *what, const EndGameMenusBase *b)
{
    const EndGameMenu *m = (const EndGameMenu *)b;
    const bNode *n;
    int i;

    printf("  %s ", what);
    print_label(b);
    printf(" %s %08x", vt_name(b->vt), (unsigned)b->ScreenHash);
    if (b->vt == &kEndGameMenuVTable) {
        printf(" state %d labels", (int)m->State);
        for (i = 0; i < 15; i++)
            printf(" %x", (unsigned)m->Labels[i]);
        printf(" items");
        for (n = m->Items.next; n != &m->Items; n = n->next) {
            const EndGameMenuItem *it = (const EndGameMenuItem *)n;

            printf(" ");
            print_label(it);
            printf("/%x/%08x/%d", (unsigned)it->Label, (unsigned)it->Hash,
                   (int)it->Kind);
        }
    }
    printf("\n");
}

static void dump(void)
{
    dump_egs();
    printf("  pegs ");
    print_label(pEndGameScreens);
    printf("\n");
    if (pEndGameMenuInstance == NULL)
        printf("  inst NULL\n");
    else if (!slotUsed[slot_of(pEndGameMenuInstance)])
        printf("  inst freed\n");
    else
        dump_menu("inst", pEndGameMenuInstance);
    if (obj == NULL)
        printf("  obj NULL\n");
    else if (!slotUsed[slot_of(obj)])
        printf("  obj freed\n");
    else
        dump_menu("obj", obj);
}

static int name_index(int64_t i)
{
    return i < 0 || i >= NUM_NAMES ? 0 : (int)i;
}

int main(int argc, char **argv)
{
    static char line[512];
    FILE *sc;
    int i;

    if (argc < 2) {
        fprintf(stderr, "usage: endgame_test script\n");
        return 2;
    }
    sc = fopen(argv[1], "r");
    if (sc == NULL)
        return 2;

    for (i = 0; i < NUM_NAMES; i++)
        snprintf(nameBufs[i], sizeof nameBufs[i], "%s", kNames[i]);
    pRaceCoordinator = &rcMem;
    pReplayManager = &rmMem;
    gChangeToScreenFn = change_to_screen;
    gSetFlailerScreenVisibilityFn = visibility;
    gGrayMenuItemFn = gray;
    gSummonPopupFn = summon;
    gFlailerCurrentScreenFn = current_screen;
    gReplayMuteHighlightsFn = mute_highlights;
    gEndGameTranslateFn = translate;
    gEndGameMenuAnimFn = the_anim;
    gSetAutosaveCompletionCallbackFn = set_autosave_cb;
    gRaceEventGetStatusFn = ev_status;
    gRaceEventRewardTestFn = ev_reward_test;
    gRaceEventStatusAdvancedFn = ev_advanced;
    gRaceEventStatusFellFn = ev_fell;
    gRaceEventNumOpenedFn = ev_opened;
    gRaceEventKeepStateFn = ev_keep;
    gRaceEventRestartFn = ev_restart;
    gRaceEventIsThereAnotherRaceFn = ev_another;
    gIsCarUnlockedFn = is_unlocked;

    while (fgets(line, sizeof line, sc)) {
        char *arg[16];
        const char *op;
        BScreenCallbackData data;
        int n = 0;
        char *t;

        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        printf("> %s\n", line);
        for (t = strtok(line, "|"); t && n < 16; t = strtok(NULL, "|"))
            arg[n++] = t;
        op = arg[0];
        if (!strcmp(op, "fred")) {
            Fred.GameType = (int32_t)num(arg[1]);
            Fred.NumPlayerCars = (int32_t)num(arg[2]);
            Fred.Autosave = (int32_t)num(arg[3]);
            Fred.TransientStatsTable.PointsRewardEarned = (int32_t)num(arg[4]);
            Fred.TransientStatsTable.TaskRewardEarned = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "rp")) {
            TheRaceParameters.RaceType = (int32_t)num(arg[1]);
            TheRaceParameters.Point2Point = (int32_t)num(arg[2]);
            TheRaceParameters.NumLapsInRace = (int32_t)num(arg[3]);
            TheRaceParameters.NumPlayerCars = (int32_t)num(arg[4]);
            TheRaceParameters.EventTreeRace = (int32_t)num(arg[5]);
            TheRaceParameters.BeACop = (int32_t)num(arg[6]);
        } else if (!strcmp(op, "ev")) {
            TheRaceEvent.nNumber = (int16_t)num(arg[1]);
            TheRaceEvent.nType = (int16_t)num(arg[2]);
            TheRaceEvent.nRewards = (int16_t)num(arg[3]);
            TheRaceEvent.bIsLastOpen = (int32_t)num(arg[4]);
        } else if (!strcmp(op, "evf")) {
            evStatus = (int32_t)num(arg[1]);
            evAdvanced = (int32_t)num(arg[2]);
            evFell = (int32_t)num(arg[3]);
            evOpened = (int32_t)num(arg[4]);
            evAnother = (int32_t)num(arg[5]);
        } else if (!strcmp(op, "rtest")) {
            rtestMask = (uint32_t)num(arg[1]);
        } else if (!strcmp(op, "unlock")) {
            unlockAnswer = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "replay")) {
            pReplayManager = num(arg[1]) ? &rmMem : NULL;
            replayMute = (int32_t)num(arg[2]);
        } else if (!strcmp(op, "cur")) {
            int64_t k = num(arg[1]);

            screenUp = k >= 0;
            curCfg.name = screenUp ? nameBufs[name_index(k)] : NULL;
        } else if (!strcmp(op, "probe")) {
            gEndGameScreenCtorFns[END_GAME_CLASS_TOURNEY_STANDINGS] =
                num(arg[1]) ? probe_ctor : NULL;
        } else if (!strcmp(op, "egs")) {
            void *mem = slot_alloc();

            egs = endgame_screens_construct(mem, (int32_t)num(arg[1]));
            if (egs != mem)
                printf("  ctor returned another\n");
        } else if (!strcmp(op, "egsdtor")) {
            if (egs != NULL) {
                int32_t f = (int32_t)num(arg[1]);

                endgame_screens_destroy(egs, f);
                if (!(f & 1))
                    slotUsed[slot_of(egs)] = 0;
                egs = NULL;
            }
        } else if (egs == NULL
                   && (!strcmp(op, "build") || !strcmp(op, "next")
                       || !strcmp(op, "remove") || !strcmp(op, "advance")
                       || !strcmp(op, "atroot") || !strcmp(op, "back")
                       || !strcmp(op, "current") || !strcmp(op, "resume")
                       || !strcmp(op, "suspend")
                       || !strcmp(op, "autodone") || !strcmp(op, "setcb")
                       || !strcmp(op, "insname"))) {
            printf("  no egs\n");
        } else if (!strcmp(op, "build")) {
            endgame_screens_build_screen_list(egs);
        } else if (!strcmp(op, "next")) {
            const char *s = endgame_screens_get_next_screen(egs);

            printf("  = %s\n", s != NULL ? s : "NULL");
        } else if (!strcmp(op, "remove")) {
            endgame_screens_remove_screen(egs, nameBufs[name_index(num(arg[1]))]);
        } else if (!strcmp(op, "advance")) {
            endgame_screens_advance_screen(egs);
        } else if (!strcmp(op, "atroot")) {
            printf("  = %d\n", (int)endgame_screens_at_root(egs));
        } else if (!strcmp(op, "back")) {
            endgame_screens_move_back_screen(egs);
        } else if (!strcmp(op, "current")) {
            const char *s = endgame_screens_get_current_screen(egs);

            printf("  = %s\n", s != NULL ? s : "NULL");
        } else if (!strcmp(op, "resume")) {
            endgame_screens_resume(egs);
        } else if (!strcmp(op, "suspend")) {
            endgame_screens_suspend(egs);
        } else if (!strcmp(op, "autodone")) {
            endgame_screens_autosave_completed(egs);
        } else if (!strcmp(op, "setcb")) {
            endgame_screens_set_autosave_callback(egs);
        } else if (!strcmp(op, "insname")) {
            bPNode *nd = node_alloc();
            bNode *at = egs->ScreenList.next;
            int64_t pos = num(arg[2]);

            while (pos-- > 0 && at != &egs->ScreenList)
                at = at->next;
            nd->Object = nameBufs[name_index(num(arg[1]))];
            nd->Node.next = at;
            nd->Node.prev = at->prev;
            at->prev->next = &nd->Node;
            at->prev = &nd->Node;
        } else if (!strcmp(op, "t")) {
            static int32_t (*const tests[])(void) = {
                endgame_should_see_btc_results_1p,
                endgame_should_see_btc_results_2p,
                endgame_should_see_reward_menu,
                endgame_should_see_points_reward_screen,
                endgame_should_see_events_unlocked,
                endgame_should_see_task_reward_screen,
                endgame_should_see_race_results,
                endgame_should_see_tourney,
                endgame_should_see_best_lap_times,
                endgame_should_see_best_total_times,
                endgame_should_auto_save,
                endgame_should_see_end_game,
                endgame_is_not_game_type_6,
            };

            printf("  = %d\n", (int)tests[num(arg[1])]());
        } else if (!strcmp(op, "base")) {
            void *mem = slot_alloc();

            obj = endgame_menus_base_construct(mem, (uint32_t)num(arg[1]));
            if (obj != mem)
                printf("  ctor returned another\n");
        } else if (!strcmp(op, "bh")) {
            data_from(&data, arg + 2);
            endgame_menus_base_handle_event(obj, (BScreenMessage)num(arg[1]),
                                            &data);
            print_data(&data);
        } else if (!strcmp(op, "bdtor")) {
            int32_t f = (int32_t)num(arg[1]);

            endgame_menus_base_destroy(obj, f);
            if (!(f & 1)) {
                printf("  left %s\n", vt_name(obj->vt));
                slotUsed[slot_of(obj)] = 0;
            }
            obj = NULL;
        } else if (!strcmp(op, "cb")) {
            data_from(&data, arg + 2);
            endgame_screen_callback(NULL, (BScreenMessage)num(arg[1]), &data);
            print_data(&data);
        } else if (!strcmp(op, "menu")) {
            void *mem = slot_alloc();

            memset(&data, 0, sizeof data);
            data.param = (int32_t)num(arg[2]);
            obj = endgame_menu_construct(mem, (uint32_t)num(arg[1]), &data);
            if (obj != mem)
                printf("  ctor returned another\n");
            print_data(&data);
        } else if (!strcmp(op, "mh")) {
            data_from(&data, arg + 2);
            endgame_menu_handle_event(obj, (BScreenMessage)num(arg[1]), &data);
            print_data(&data);
        } else if (!strcmp(op, "mstate")) {
            ((EndGameMenu *)obj)->State = (int32_t)num(arg[1]);
        } else if (!strcmp(op, "mdtor")) {
            int32_t f = (int32_t)num(arg[1]);

            endgame_menu_destroy(obj, f);
            if (!(f & 1)) {
                printf("  left %s\n", vt_name(obj->vt));
                slotUsed[slot_of(obj)] = 0;
            }
            obj = NULL;
        } else if (!strcmp(op, "labels")) {
            int32_t buf[15];

            memset(buf, 0x5a, sizeof buf);
            endgame_menu_init_labels((EndGameMenu *)obj, buf);
            printf("  labels");
            for (i = 0; i < 15; i++)
                printf(" %x", (unsigned)buf[i]);
            printf("\n");
        } else if (!strcmp(op, "restart")) {
            endgame_menu_maybe_restart((EndGameMenu *)obj,
                                       (int32_t)num(arg[1]),
                                       (int32_t)num(arg[2]),
                                       (int32_t)num(arg[3]));
        } else if (!strcmp(op, "find")) {
            EndGameMenuItem *it =
                endgame_menu_find_item((EndGameMenu *)obj,
                                       (uint32_t)num(arg[1]));

            printf("  = ");
            print_label(it);
            printf("\n");
        } else if (!strcmp(op, "fire")) {
            void (*cb)(void) = autosaveCb;

            autosaveCb = NULL;
            if (cb != NULL)
                cb();
            else
                printf("  no cb\n");
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
