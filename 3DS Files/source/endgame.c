// endgame -- the end of a race; endgame.h has the map.

#include "endgame.h"

#include <string.h>

#include "bmem.h"
#include "bplist.h"
#include "bpopup.h"
#include "flailer.h"
#include "fred.h"
#include "fredrace.h"
#include "gameflow.h"
#include "nfsrewards.h"
#include "pausemenu.h"
#include "race.h"
#include "racecoord.h"
#include "rcpost.h"
#include "replay.h"
#include "trackflow.h"

const char kEndGamePointsRewardsScreen[] = "Points Rewards";
const char kEndGameTaskRewardsScreen[] = "Task Rewards";
const char kEndGameEventsUnlockedScreen[] = "Events Unlocked";
const char kEndGameRewardMenuScreen[] = "Reward menu";
const char kEndGameRaceResultsScreen[] = "Race Results";
const char kEndGameTourneyStandingsScreen[] = "Tourney Standings";
const char kEndGameBestLapTimesScreen[] = "Best Lap Times";
const char kEndGameBestTotalTimesScreen[] = "Best Total Times";
const char kEndGameAutosaveScreen[] = "Autosave";
const char kEndGameBTCResults1PScreen[] = "Be The Cop Results 1P";
const char kEndGameBTCResults2PScreen[] = "Be The Cop Results 2P";
const char kEndGameLapTimes1PScreen[] = "Lap Times 1P";
const char kEndGameLapTimes2PScreen[] = "Lap Times 2P";
const char kEndGameMenuScreen[] = "End Game Menu";

EndGameScreens *pEndGameScreens;
EndGameMenusBase *pEndGameMenuInstance;

EndGameScreenCtor gEndGameScreenCtorFns[END_GAME_NUM_CLASSES];
const char *(*gEndGameTranslateFn)(int32_t id);
BAnim *(*gEndGameMenuAnimFn)(void);
void (*gSetAutosaveCompletionCallbackFn)(void (*cb)(void));
int32_t (*gEndGameReplayViewableFn)(void);
int32_t (*gRaceEventRewardTestFn)(int32_t i);
int32_t (*gRaceEventStatusAdvancedFn)(void);
int32_t (*gRaceEventStatusFellFn)(void);
int32_t (*gRaceEventNumOpenedFn)(void);
void (*gRaceEventKeepStateFn)(void);
void (*gRaceEventRestartFn)(void);

// Everything here is bMalloc'd in pool 16.
#define END_GAME_POOL 16

// GrayMenuItem's modes, as pausemenu.c's.
#define GRAY_ENABLE 1
#define GRAY_HIDE   2

// The popup's Flags: left and right move between OK and Cancel, and BACK
// is Cancel.
#define END_GAME_POPUP_FLAGS (BPOPUP_HORIZONTAL | BPOPUP_CANCELABLE)

// The menu's items on END_GAME_MENU, MENUITEM_1 to MENUITEM_6 (retail's
// copy of 0x002b8f08).
static const uint32_t kMenuItems[END_GAME_MENU_NUM_ITEMS] = {
    END_GAME_MENU_ITEM_1,     END_GAME_MENU_ITEM_1 + 1,
    END_GAME_MENU_ITEM_1 + 2, END_GAME_MENU_ITEM_1 + 3,
    END_GAME_MENU_ITEM_1 + 4, END_GAME_MENU_ITEM_1 + 5,
};

// ------------------------------------------------------------- the seams

static BAnim *anim(void)
{
    return gEndGameMenuAnimFn != NULL ? gEndGameMenuAnimFn() : NULL;
}

static void change_to_screen(const char *name, int32_t push)
{
    if (gChangeToScreenFn != NULL)
        gChangeToScreenFn(name, push);
}

static void set_screen_visibility(uint32_t screen, int visibility)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, visibility);
}

static void gray_menu_item(uint32_t item, int32_t mode, uint32_t screen)
{
    if (gGrayMenuItemFn != NULL)
        gGrayMenuItemFn(item, mode, screen);
}

static const char *translate(int32_t id)
{
    return gEndGameTranslateFn != NULL ? gEndGameTranslateFn(id) : NULL;
}

static const struct BScreenConfig *current_screen(void)
{
    return gFlailerCurrentScreenFn != NULL ? gFlailerCurrentScreenFn()
                                           : NULL;
}

static void set_autosave_completion_callback(void (*cb)(void))
{
    if (gSetAutosaveCompletionCallbackFn != NULL)
        gSetAutosaveCompletionCallbackFn(cb);
}

// PostMessage on pRaceCoordinator, which retail passes without a test:
// the screens are up only at the end of a race.
static void post(RCMessage msg, int32_t param)
{
    racecoordinator_post_message(pRaceCoordinator, msg, param);
}

static int32_t race_event_status(void)
{
    return gRaceEventGetStatusFn != NULL ? gRaceEventGetStatusFn() : 0;
}

static int32_t race_event_reward_test(int32_t i)
{
    return gRaceEventRewardTestFn != NULL ? gRaceEventRewardTestFn(i) : 0;
}

static int32_t race_event_status_advanced(void)
{
    return gRaceEventStatusAdvancedFn != NULL ? gRaceEventStatusAdvancedFn()
                                              : 0;
}

static int32_t race_event_status_fell(void)
{
    return gRaceEventStatusFellFn != NULL ? gRaceEventStatusFellFn() : 0;
}

static int32_t race_event_num_opened(void)
{
    return gRaceEventNumOpenedFn != NULL ? gRaceEventNumOpenedFn() : 0;
}

static void race_event_keep_state(void)
{
    if (gRaceEventKeepStateFn != NULL)
        gRaceEventKeepStateFn();
}

static void race_event_restart(void)
{
    if (gRaceEventRestartFn != NULL)
        gRaceEventRestartFn();
}

static int32_t is_car_unlocked(int32_t carType, int32_t gameType)
{
    return gIsCarUnlockedFn != NULL ? gIsCarUnlockedFn(carType, gameType)
                                    : 0;
}

// --------------------------------------------------------------- the tests

int32_t endgame_should_see_btc_results_1p(void)
{
    return TheRaceParameters.BeACop && Fred.NumPlayerCars == 1;
}

int32_t endgame_should_see_btc_results_2p(void)
{
    return TheRaceParameters.BeACop && Fred.NumPlayerCars == 2;
}

// An event tree's race, when it is one of the two last events (31 with
// its word clear, or 32), when one of its rewards does not pass its test
// once the event is far enough on (status 3), or, for an event with no
// rewards, when the race took the event on. The count is read again on
// each pass, as retail does.
int32_t endgame_should_see_reward_menu(void)
{
    const RaceEventFields *ev = &TheRaceEventFields;
    int32_t i;

    if (!fred_use_tree_event(&Fred))
        return 0;
    if (ev->Number == 32)
        return 1;
    if (ev->Number == 31 && ev->EventWord == 0)
        return 1;
    for (i = 0; i < ev->NumRewards; i++)
        if (race_event_status() >= 3 && race_event_reward_test(i) == 0)
            return 1;
    if (ev->NumRewards != 0)
        return 0;
    if (race_event_status() < 3)
        return 0;
    return race_event_status_advanced();
}

// The points reward this race earned, if any, when its car is unlocked
// for GameType 3. Retail answers IsCarUnlocked as it is.
int32_t endgame_should_see_points_reward_screen(void)
{
    int32_t reward = Fred.TransientStatsTable.PointsRewardEarned;

    if (reward == -1)
        return 0;
    return is_car_unlocked(nfs_get_car_type_for_points_reward(reward), 3);
}

int32_t endgame_should_see_events_unlocked(void)
{
    if (!fred_use_tree_event(&Fred))
        return 0;
    if (race_event_status() != 4)
        return 0;
    if (!race_event_status_advanced())
        return 0;
    return race_event_num_opened() > 0;
}

int32_t endgame_should_see_task_reward_screen(void)
{
    return Fred.TransientStatsTable.TaskRewardEarned != -1;
}

int32_t endgame_should_see_race_results(void)
{
    int32_t t = Fred.GameType;

    if (TheRaceParameters.BeACop || t == 6)
        return 0;
    if (t == 8 || t == 9)
        return TheRaceEventFields.Type != 1;
    return 1;
}

int32_t endgame_should_see_tourney(void)
{
    int32_t t = Fred.GameType;

    if (TheRaceParameters.BeACop)
        return 0;
    if (t == 8 || t == 9)
        return TheRaceEventFields.Type == 4;
    return 0;
}

int32_t endgame_should_see_best_lap_times(void)
{
    const RaceParameters *rp = &TheRaceParameters;

    if (rp->BeACop || Fred.GameType == 6 || rp->Point2Point != 0)
        return 0;
    return rp->NumLapsInRace != 1;
}

int32_t endgame_should_see_best_total_times(void)
{
    int32_t t = Fred.GameType;

    if (TheRaceParameters.BeACop || t == 6)
        return 0;
    if (t == 8 || t == 9)
        return TheRaceEventFields.Type != 1;
    return 1;
}

int32_t endgame_should_auto_save(void)
{
    return Fred.Autosave != 0;
}

int32_t endgame_should_see_end_game(void)
{
    return 1;
}

int32_t endgame_is_not_game_type_6(void)
{
    return Fred.GameType != 6;
}

// ---------------------------------------------------------------- the list

// bPList<char>::AddTail: a node from the pool with the name on it.
static void add_screen(EndGameScreens *s, const char *name)
{
    bPNode *n = bpnode_malloc();
    bNode *head = &s->ScreenList;

    n->Object = (void *)name;
    n->Node.next = head;
    n->Node.prev = head->prev;
    head->prev->next = &n->Node;
    head->prev = &n->Node;
}

// bPList<char>::Remove: unlinked and given back to the pool.
static void remove_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
    bpnode_free(n);
}

static const char *node_name(const bNode *n)
{
    return (const char *)((const bPNode *)n)->Object;
}

void endgame_screens_build_screen_list(EndGameScreens *s)
{
    if (endgame_should_see_points_reward_screen())
        add_screen(s, kEndGamePointsRewardsScreen);
    if (endgame_should_see_task_reward_screen())
        add_screen(s, kEndGameTaskRewardsScreen);
    if (endgame_should_see_events_unlocked())
        add_screen(s, kEndGameEventsUnlockedScreen);
    if (endgame_should_see_reward_menu())
        add_screen(s, kEndGameRewardMenuScreen);
    if (endgame_should_see_btc_results_1p())
        add_screen(s, kEndGameBTCResults1PScreen);
    if (endgame_should_see_btc_results_2p())
        add_screen(s, kEndGameBTCResults2PScreen);
    if (endgame_should_see_race_results())
        add_screen(s, kEndGameRaceResultsScreen);
    if (endgame_should_see_tourney())
        add_screen(s, kEndGameTourneyStandingsScreen);
    if (endgame_should_see_best_lap_times())
        add_screen(s, kEndGameBestLapTimesScreen);
    if (endgame_should_see_best_total_times())
        add_screen(s, kEndGameBestTotalTimesScreen);
    if (endgame_should_see_end_game())
        add_screen(s, kEndGameMenuScreen);
}

void endgame_screens_reset_all_screen_counters(EndGameScreens *s)
{
    (void)s;
}

EndGameScreens *endgame_screens_construct(void *mem, int32_t continueType)
{
    EndGameScreens *s = (EndGameScreens *)mem;

    s->ContinueRaceType = continueType;
    s->ScreenList.next = &s->ScreenList;
    s->ScreenList.prev = &s->ScreenList;
    pEndGameScreens = s;
    endgame_screens_build_screen_list(s);
    endgame_screens_reset_all_screen_counters(s);
    s->CurrentScreen = s->ScreenList.next;
    s->ScreensEnabled = 0;
    memset(s->Zeroed, 0, sizeof s->Zeroed);
    return s;
}

void endgame_screens_destroy(EndGameScreens *s, int32_t flags)
{
    if (s->ScreensEnabled)
        change_to_screen(NULL, 0);
    pEndGameScreens = NULL;
    while (s->ScreenList.next != &s->ScreenList)
        remove_node(s->ScreenList.next);
    if (flags & 1)
        bFree(s);
}

const char *endgame_screens_get_next_screen(const EndGameScreens *s)
{
    const bNode *n = s->CurrentScreen->next;

    return n == &s->ScreenList ? NULL : node_name(n);
}

void endgame_screens_remove_screen(EndGameScreens *s, const char *name)
{
    bNode *n;

    for (n = s->ScreenList.next; n != &s->ScreenList; n = n->next)
        if (strcmp(node_name(n), name) == 0) {
            remove_node(n);
            return;
        }
}

void endgame_screens_advance_screen(EndGameScreens *s)
{
    bNode *n = s->CurrentScreen->next;

    if (n != &s->ScreenList)
        s->CurrentScreen = n;
}

int32_t endgame_screens_at_root(const EndGameScreens *s)
{
    return s->CurrentScreen == s->ScreenList.next;
}

void endgame_screens_move_back_screen(EndGameScreens *s)
{
    if (s->CurrentScreen != s->ScreenList.next)
        s->CurrentScreen = s->CurrentScreen->prev;
}

// Retail reads the head's word at +8 for an empty list, the
// EndGameScreens' own CurrentScreen; the list is never empty, as the End
// Game Menu is always on it.
const char *endgame_screens_get_current_screen(const EndGameScreens *s)
{
    if (s->CurrentScreen == &s->ScreenList)
        return NULL;
    return node_name(s->CurrentScreen);
}

void endgame_screens_constructed(EndGameScreens *s)
{
    (void)s;
}

void endgame_screens_resume(EndGameScreens *s)
{
    const char *cur;

    if (s == NULL || s->ScreensEnabled)
        return;
    s->ScreensEnabled = 1;
    cur = endgame_screens_get_current_screen(s);
    if (cur != NULL && strcmp(cur, kEndGameAutosaveScreen) == 0) {
        endgame_screens_advance_screen(s);
        endgame_screens_remove_screen(s, kEndGameAutosaveScreen);
        change_to_screen(kEndGameAutosaveScreen, 1);
        endgame_screens_set_autosave_callback(s);
    } else {
        change_to_screen(endgame_screens_get_current_screen(s), 1);
    }
    set_screen_visibility(END_GAME_LETTERBOX_SCREEN, FLAILER_SCREEN_VISIBLE);
}

void endgame_screens_suspend(EndGameScreens *s)
{
    if (s == NULL || !s->ScreensEnabled)
        return;
    s->ScreensEnabled = 0;
    change_to_screen(NULL, 0);
    set_screen_visibility(END_GAME_LETTERBOX_SCREEN,
                          FLAILER_SCREEN_INVISIBLE);
}

void endgame_screens_autosave_completed(EndGameScreens *s)
{
    endgame_screens_advance_screen(s);
    change_to_screen(endgame_screens_get_current_screen(s), 0);
}

// 0x001e25e8, which retail calls with no test of pEndGameScreens.
static void autosave_completed_bridge(void)
{
    if (pEndGameScreens != NULL)
        endgame_screens_autosave_completed(pEndGameScreens);
}

void endgame_screens_set_autosave_callback(EndGameScreens *s)
{
    (void)s;
    set_autosave_completion_callback(autosave_completed_bridge);
}

// --------------------------------------------------------------- the base

static void nothing(EndGameMenusBase *m, BScreenMessage msg,
                    BScreenCallbackData *data)
{
    (void)m;
    (void)msg;
    (void)data;
}

const EndGameMenusVTable kEndGameMenusBaseVTable = {
    nothing,
    endgame_menus_base_handle_event,
    nothing,
    nothing,
    endgame_menus_base_destroy,
};

EndGameMenusBase *endgame_menus_base_construct(EndGameMenusBase *m,
                                               uint32_t hash)
{
    const EndGameScreens *s = pEndGameScreens;

    m->vt = &kEndGameMenusBaseVTable;
    m->ScreenHash = hash;
    flailer_set_visibility(m->ScreenHash, END_GAME_OBJ_PREVIOUS,
                           s == NULL || endgame_screens_at_root(s)
                               ? FLAILER_OBJECT_INVISIBLE
                               : FLAILER_OBJECT_VISIBLE);
    return m;
}

// SELECT: the next screen up, or, when it is the Autosave screen, that
// taken off the list and up with the autosave's callback to go on. The
// screens and their list come and go together, so pEndGameScreens is
// there whenever one of them is up; the port tests it all the same, here
// and at each BACK.
static void base_select(void)
{
    EndGameScreens *s = pEndGameScreens;
    const char *next;

    if (s == NULL)
        return;
    next = endgame_screens_get_next_screen(s);
    if (next != NULL && strcmp(next, kEndGameAutosaveScreen) == 0) {
        endgame_screens_remove_screen(s, next);
        endgame_screens_advance_screen(s);
        change_to_screen(next, 0);
        endgame_screens_set_autosave_callback(s);
        return;
    }
    endgame_screens_advance_screen(s);
    change_to_screen(next, 0);
}

// BACK: the screen before up, with the cancel noise, unless this is the
// first; silent then.
static void base_back(BScreenCallbackData *data)
{
    EndGameScreens *s = pEndGameScreens;
    const char *was;

    data->noise = 0;
    if (s == NULL) {
        data->param = 0;
        return;
    }
    was = endgame_screens_get_current_screen(s);
    endgame_screens_move_back_screen(s);
    if (endgame_screens_get_current_screen(s) != was) {
        data->noise = BSND_MENU_CANCEL;
        change_to_screen(endgame_screens_get_current_screen(s), 0);
    }
    data->param = 0;
}

void endgame_menus_base_handle_event(EndGameMenusBase *m, BScreenMessage msg,
                                     BScreenCallbackData *data)
{
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        base_select();
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        base_back(data);
        break;
    case BMSG_MENUITEM_PAD_UP:
    case BMSG_MENUITEM_PAD_DOWN:
        data->noise = 0;
        break;
    case BMSG_MENUITEM_PAD_LEFT:
    case BMSG_MENUITEM_PAD_RIGHT:
        m->vt->Scroll(m, msg, data);
        break;
    case BMSG_SCREEN_TICK:
        m->vt->Tick(m, msg, data);
        break;
    case BMSG_SCREEN_RENDER:
        m->vt->Render(m, msg, data);
        break;
    default:
        break;
    }
}

void endgame_menus_base_destroy(EndGameMenusBase *m, int32_t flags)
{
    m->vt = &kEndGameMenusBaseVTable;
    if (flags & 1)
        bFree(m);
}

// ------------------------------------------------------------ the callback

// The classes by screen name, in the callback's order, each with
// retail's size and allocation name.
typedef struct EndGameClass {
    const char *Screen;
    int32_t     Class;
    int32_t     Size;
    const char *AllocName;
} EndGameClass;

static const EndGameClass kClasses[] = {
    { kEndGamePointsRewardsScreen, END_GAME_CLASS_POINTS_REWARDS, 8,
      "Points Rewards" },
    { kEndGameTaskRewardsScreen, END_GAME_CLASS_TASK_REWARDS, 8,
      "Task Rewards" },
    { kEndGameEventsUnlockedScreen, END_GAME_CLASS_EVENTS_UNLOCKED, 8,
      "Events Unlocked" },
    { kEndGameRewardMenuScreen, END_GAME_CLASS_REWARD_MENU, 8,
      "EventRewardScreen" },
    { kEndGameRaceResultsScreen, END_GAME_CLASS_RACE_RESULTS, 60,
      "RaceResultsScreen" },
    { kEndGameTourneyStandingsScreen, END_GAME_CLASS_TOURNEY_STANDINGS, 8,
      "TourneyStandingsScreen" },
    { kEndGameBestLapTimesScreen, END_GAME_CLASS_BEST_LAP_TIMES, 8,
      "BestLapTimes" },
    { kEndGameBestTotalTimesScreen, END_GAME_CLASS_BEST_TOTAL_TIMES, 8,
      "BestTotalTimes" },
    { kEndGameMenuScreen, END_GAME_CLASS_MENU, 112, "EndGameMenu" },
    { kEndGameBTCResults1PScreen, END_GAME_CLASS_BTC_RESULTS_1P, 8,
      "BeACopResults1P" },
    { kEndGameBTCResults2PScreen, END_GAME_CLASS_BTC_RESULTS_2P, 8,
      "BeACopResults2P" },
};
#define NUM_CLASSES ((int)(sizeof(kClasses) / sizeof(kClasses[0])))

// ACTIVATE: the class of the screen that came up, by its name. A screen
// with no class leaves the instance as it was.
static void construct_class(BScreenCallbackData *data)
{
    const struct BScreenConfig *cfg = current_screen();
    const char *name = cfg != NULL ? cfg->name : NULL;
    int i;

    if (name == NULL)
        return;
    for (i = 0; i < NUM_CLASSES; i++) {
        const EndGameClass *c = &kClasses[i];
        void *mem;

        if (strcmp(name, c->Screen) != 0)
            continue;
        mem = bMalloc(c->Size, c->AllocName, 0, END_GAME_POOL);
        if (c->Class == END_GAME_CLASS_MENU)
            pEndGameMenuInstance =
                endgame_menu_construct(mem, data->itemHash, data);
        else if (gEndGameScreenCtorFns[c->Class] != NULL)
            pEndGameMenuInstance =
                gEndGameScreenCtorFns[c->Class](mem, data->itemHash, data);
        else
            pEndGameMenuInstance = endgame_menus_base_construct(
                (EndGameMenusBase *)mem, data->itemHash);
        return;
    }
}

void endgame_screen_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data)
{
    EndGameMenusBase *m = pEndGameMenuInstance;

    (void)gf;
    if (msg == BMSG_SCREEN_ACTIVATE) {
        construct_class(data);
        if (pEndGameScreens != NULL)
            endgame_screens_constructed(pEndGameScreens);
    } else if (msg == BMSG_SCREEN_UNACTIVATE) {
        if (m != NULL)
            m->vt->Destroy(m, 3);
        pEndGameMenuInstance = NULL;
    } else if (m != NULL) {
        m->vt->HandleEvent(m, msg, data);
    }
}

// ---------------------------------------------------------------- the menu

const EndGameMenusVTable kEndGameMenuVTable = {
    nothing,
    endgame_menu_handle_event,
    nothing,
    nothing,
    endgame_menu_destroy,
};

// The items' tests, 0x001e11a8 .. 0x001e12b0.
static int32_t has_next_race(void)
{
    return fred_is_multi_track(&Fred) && fred_is_there_another_race(&Fred);
}

static int32_t has_restart_race(void)
{
    int32_t t = Fred.GameType;

    if (t == 8 || t == 9)
        return fred_is_multi_track(&Fred);
    return 1;
}

static int32_t has_restart_event(void)
{
    return fred_is_multi_track(&Fred) || fred_use_the_race_event(&Fred);
}

// The replay's word at +12 clear. Retail reads it through pReplayManager
// with no test, since InitForRace always makes one; a NULL one reads as
// no replay to view. The port's ReplayManager is a stand-in until the
// replay is ported, and gEndGameReplayViewableFn says so.
static int32_t has_view_replay(void)
{
    const struct ReplayManager *rm = pReplayManager;

    if (rm == NULL)
        return 0;
    if (gEndGameReplayViewableFn != NULL && gEndGameReplayViewableFn() == 0)
        return 0;
    return gReplayMuteHighlightsFn == NULL || gReplayMuteHighlightsFn(rm) == 0;
}

static int32_t has_lap_times(void)
{
    return !TheRaceParameters.BeACop;
}

static void add_item(EndGameMenu *m, int32_t label, int32_t kind)
{
    EndGameMenuItem *it = (EndGameMenuItem *)bMalloc(20, "EndGameMenuItem",
                                                     0, END_GAME_POOL);
    bNode *head = &m->Items;

    it->Node.next = head;
    it->Node.prev = head->prev;
    head->prev->next = &it->Node;
    head->prev = &it->Node;
    it->Label = label;
    it->Kind = kind;
    it->Hash = 0;
}

EndGameMenusBase *endgame_menu_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data)
{
    EndGameMenu *m = (EndGameMenu *)mem;
    uint32_t screen;
    BAnim *a;
    bNode *n;
    int32_t placed;

    endgame_menus_base_construct(&m->Base, hash);
    m->Base.vt = &kEndGameMenuVTable;
    if ((a = anim()) != NULL)
        banim_highlight_init(a, &m->Highlight, hash, END_GAME_MENU_OBJ_BLOOM,
                             (int32_t)BANIM_BLOOM_COLOR);
    else
        memset(&m->Highlight, 0, sizeof m->Highlight);
    m->Items.next = &m->Items;
    m->Items.prev = &m->Items;
    endgame_menu_init_labels(m, m->Labels);
    data->param = 0;

    if (has_next_race())
        add_item(m, m->Labels[10], END_GAME_ITEM_NEXT_RACE);
    if (has_restart_race())
        add_item(m, m->Labels[1], END_GAME_ITEM_RESTART_RACE);
    if (has_restart_event())
        add_item(m, m->Labels[4], END_GAME_ITEM_RESTART_EVENT);
    if (has_view_replay())
        add_item(m, m->Labels[13], END_GAME_ITEM_VIEW_REPLAY);
    if (has_lap_times())
        add_item(m, m->Labels[14], END_GAME_ITEM_LAP_TIMES);
    add_item(m, m->Labels[7], END_GAME_ITEM_QUIT);

    // Each item on the next MENUITEM, named and enabled; the MENUITEMs
    // left over hidden.
    screen = m->Base.ScreenHash;
    placed = 0;
    for (n = m->Items.next; n != &m->Items; n = n->next) {
        EndGameMenuItem *it = (EndGameMenuItem *)n;
        uint32_t item;

        if (placed >= END_GAME_MENU_NUM_ITEMS)
            continue;
        item = kMenuItems[placed++];
        it->Hash = item;
        flailer_set_language_id(screen, item, (uint32_t)it->Label);
        gray_menu_item(item, GRAY_ENABLE, m->Base.ScreenHash);
    }
    for (; placed < END_GAME_MENU_NUM_ITEMS; placed++)
        gray_menu_item(kMenuItems[placed], GRAY_HIDE, m->Base.ScreenHash);
    flailer_set_language_id(m->Base.ScreenHash, END_GAME_MENU_OBJ_TITLE,
                            (uint32_t)m->Labels[0]);
    return &m->Base;
}

// The fifteen LanguageIDs: [0] the title; [1] .. [3] Restart Race, its
// message and its popup's title; [4] .. [6] Restart Event's; [7] .. [9]
// Quit's; [10] .. [12] Next Race's; [13] View Replay; [14] View Lap Times.
void endgame_menu_init_labels(EndGameMenu *m, int32_t *labels)
{
    const RaceParameters *rp = &TheRaceParameters;

    (void)m;
    memset(labels, 0xff, 15 * sizeof labels[0]);
    labels[10] = 0x4baf2;
    labels[11] = 0x382d5;
    labels[12] = 0x382d4;
    labels[13] = 0x30d43;
    labels[14] = 0x4bd49;
    labels[4] = 0x30d4d;
    labels[5] = 0x38280;
    labels[6] = 0x38286;
    if (rp->EventTreeRace) {
        labels[1] = 0x30d45;
        labels[2] = 0x38271;
        labels[3] = 0x3827c;
        labels[0] = fred_is_multi_track(&Fred)
                        && fred_is_there_another_race(&Fred)
                    ? 0x30da4 : 0x30da6;
        if (Fred.GameType == 9) {
            labels[7] = 0x38338;
            labels[8] = 0x38339;
        } else {
            labels[7] = 0x3833a;
            labels[8] = 0x3833b;
        }
        labels[9] = 0x38287;
    } else if (rp->BeACop) {
        labels[0] = 0x30da5;
        labels[1] = 0x30d51;
        labels[2] = 0x38281;
        labels[3] = 0x38285;
        labels[7] = 0x30d52;
        labels[8] = 0x38282;
        labels[9] = 0x38283;
    } else {
        labels[0] = 0x30da4;
        labels[1] = 0x30d45;
        labels[2] = 0x38271;
        labels[3] = 0x3827c;
        labels[7] = 0x30d46;
        labels[8] = 0x38272;
        labels[9] = 0x3827b;
    }
}

// Retail leaves DismissParam and PopupID unwritten; nothing on this path
// reads either, and the port zeroes them.
void endgame_menu_maybe_restart(EndGameMenu *m, int32_t title,
                                int32_t message, int32_t state)
{
    BPopupConfig cfg;

    memset(&cfg, 0, sizeof cfg);
    cfg.numButtons = 2;
    cfg.flags = END_GAME_POPUP_FLAGS;
    cfg.button[0] = END_GAME_LANG_OK;
    cfg.button[1] = END_GAME_LANG_CANCEL;
    cfg.button[2] = 0;
    cfg.title = title;
    cfg.message = translate(message);
    cfg.parent = current_screen();
    cfg.screen = END_GAME_POPUP_SCREEN;
    cfg.buttonParam[0] = 1;
    cfg.buttonParam[1] = 0;
    cfg.buttonParam[2] = 0;
    cfg.cancelParam = 0;
    cfg.startButton = 1;
    cfg.joyPort = -1;
    cfg.timeout = 0;
    if (gSummonPopupFn != NULL)
        gSummonPopupFn(&cfg);
    m->State = state;
    set_screen_visibility(m->Base.ScreenHash, FLAILER_SCREEN_INVISIBLE);
}

EndGameMenuItem *endgame_menu_find_item(EndGameMenu *m, uint32_t hash)
{
    bNode *n;

    for (n = m->Items.next; n != &m->Items; n = n->next)
        if (((EndGameMenuItem *)n)->Hash == hash)
            return (EndGameMenuItem *)n;
    return NULL;
}

// 0x001e1950 .. 0x001e19c8: what an item does, and what the popups' OK
// goes on to.
static void select_item(EndGameMenu *m, const EndGameMenuItem *it)
{
    const int32_t *l = m->Labels;

    switch (it->Kind) {
    case END_GAME_ITEM_NEXT_RACE:
        endgame_menu_maybe_restart(m, l[12], l[11],
                                   END_GAME_MENU_STATE_NEXT_RACE);
        break;
    case END_GAME_ITEM_RESTART_RACE:
        endgame_menu_maybe_restart(m, l[3], l[2],
                                   END_GAME_MENU_STATE_RESTART_RACE);
        break;
    case END_GAME_ITEM_RESTART_EVENT:
        endgame_menu_maybe_restart(m, l[6], l[5],
                                   END_GAME_MENU_STATE_RESTART_EVENT);
        break;
    case END_GAME_ITEM_VIEW_REPLAY:
        post(RC_START_REPLAY, 0);
        break;
    case END_GAME_ITEM_LAP_TIMES:
        change_to_screen(TheRaceParameters.NumPlayerCars == 1
                             ? kEndGameLapTimes1PScreen
                             : kEndGameLapTimes2PScreen,
                         1);
        break;
    case END_GAME_ITEM_QUIT:
        endgame_menu_maybe_restart(m, l[9], l[8], END_GAME_MENU_STATE_QUIT);
        break;
    default:
        break;
    }
}

// The Autosave screen's callbacks: Quit's and Next Race's.
static void quit_race(void)
{
    post(RC_QUIT_RACE, 0);
}

static void next_race(void)
{
    post(RC_NEXT_RACE, 1);
}

// The popup's answer: OK goes on, through the Autosave screen for Quit and
// Next Race when the game autosaves; Cancel shows the menu again.
static void popup_dismissed(EndGameMenu *m, const BScreenCallbackData *data)
{
    switch (m->State) {
    case END_GAME_MENU_STATE_QUIT:
        if (data->param == 0)
            break;
        if (fred_use_the_race_event(&Fred))
            race_event_keep_state();
        if (endgame_should_auto_save()) {
            change_to_screen(kEndGameAutosaveScreen, 0);
            set_autosave_completion_callback(quit_race);
        } else {
            quit_race();
        }
        return;
    case END_GAME_MENU_STATE_RESTART_RACE:
        if (data->param == 0)
            break;
        if (fred_use_the_race_event(&Fred))
            race_event_keep_state();
        post(RC_RESTART_RACE, 0);
        return;
    case END_GAME_MENU_STATE_RESTART_EVENT:
        if (data->param == 0)
            break;
        race_event_restart();
        post(RC_NEXT_RACE, 0);
        return;
    case END_GAME_MENU_STATE_NEXT_RACE:
        if (data->param == 0)
            break;
        if (endgame_should_auto_save() && !race_event_status_fell()) {
            change_to_screen(kEndGameAutosaveScreen, 0);
            set_autosave_completion_callback(next_race);
        } else {
            next_race();
        }
        return;
    default:
        return;
    }
    set_screen_visibility(m->Base.ScreenHash, FLAILER_SCREEN_VISIBLE);
}

// tHighlightAnimation::HandleMessage (0x00248ae0).
static void highlight_handle_message(BHighlightAnim *h, BScreenMessage msg,
                                     const BScreenCallbackData *data)
{
    BAnim *a;

    if (msg == BMSG_SCREEN_TICK) {
        if ((a = anim()) != NULL)
            banim_highlight_animate(a, h);
    } else if (msg == BMSG_MENUITEM_HIGHLIGHT) {
        if ((a = anim()) != NULL)
            banim_highlight_set_item(a, h, data->itemHash);
    }
}

void endgame_menu_handle_event(EndGameMenusBase *b, BScreenMessage msg,
                               BScreenCallbackData *data)
{
    EndGameMenu *m = (EndGameMenu *)b;
    EndGameMenuItem *it;
    EndGameScreens *s;
    const char *was;

    highlight_handle_message(&m->Highlight, msg, data);
    switch (msg) {
    case BMSG_MENUITEM_SELECT:
        it = endgame_menu_find_item(m, data->itemHash);
        if (it != NULL && (uint32_t)it->Kind < END_GAME_MENU_NUM_ITEMS)
            select_item(m, it);
        break;
    case BMSG_SCREEN_BACK_BUTTON:
        // As the base's, but the noise is left as it is.
        s = pEndGameScreens;
        if (s != NULL) {
            was = endgame_screens_get_current_screen(s);
            endgame_screens_move_back_screen(s);
            if (endgame_screens_get_current_screen(s) != was)
                change_to_screen(endgame_screens_get_current_screen(s), 0);
        }
        data->param = 0;
        break;
    case BMSG_POPUP_DISMISS:
        popup_dismissed(m, data);
        break;
    default:
        break;
    }
}

// The items freed, the bloom's destructor (nothing), and the base's.
void endgame_menu_destroy(EndGameMenusBase *b, int32_t flags)
{
    EndGameMenu *m = (EndGameMenu *)b;

    m->Base.vt = &kEndGameMenuVTable;
    while (m->Items.next != &m->Items) {
        bNode *n = m->Items.next;

        n->prev->next = n->next;
        n->next->prev = n->prev;
        bFree(n);
    }
    endgame_menus_base_destroy(b, flags);
}
