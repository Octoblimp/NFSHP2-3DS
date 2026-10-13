// endgame -- the end of a race: retail's END_GAME_SCREENS module. The
// list of screens a finished race shows (EndGameScreens), the class every
// one of them is (EndGameMenusBase), the End Game Menu, and the callback
// all their FlailerScreenConfigs share.
//
// TheRaceHasFinished (rcstates.c) makes the EndGameScreens: BuildScreenList
// asks each ShouldSee test in turn and lists the names of the screens that
// pass, in this order --
//
//   Points Rewards         a points reward was earned (CheckForTaskAndPoint
//                          Rewards) and its car is unlocked
//   Task Rewards           a task reward was earned
//   Events Unlocked        an event tree's race opened new events
//   Reward menu            an event tree's rewards
//   Be The Cop Results 1P  Be A Cop, one player
//   Be The Cop Results 2P  Be A Cop, two players
//   Race Results           not Be A Cop or GameType 6, nor an event tree's
//                          race whose RaceEvent Type is 1
//   Tourney Standings      an event tree's tournament (Type 4)
//   Best Lap Times         a lapped race that is not Be A Cop or GameType 6
//   Best Total Times       as Race Results
//   End Game Menu          always
//
// -- and RCSTATE_POSTRACE's ACTIVATE (rcpost.c) resumes it: the first
// screen comes up with the letterbox bars (screen 0x49c15518). Its
// UNACTIVATE suspends it, and RaceCoordinator's destructor deletes it.
//
// Every one of those screens has the callback 0x001dd278. ACTIVATE makes
// the class for the screen that came up, by its name; UNACTIVATE deletes
// it; every other message goes to the class's HandleEvent. The base's
// HandleEvent walks the list: SELECT to the next screen, BACK to the one
// before. The End Game Menu is the end of the list:
//
//   Next Race         a multi-track event with another race: a popup, then
//                     RC_NEXT_RACE with 1, through the autosave if any
//   Restart Race      not an event tree's single-track race: a popup,
//                     then RC_RESTART_RACE
//   Restart Event     a multi-track race or a race event's: a popup, then
//                     the event set back to its first race and RC_NEXT_RACE
//   View Replay       RC_START_REPLAY, when the replay has its race
//   View Lap Times    not Be A Cop: "Lap Times 1P" or "Lap Times 2P"
//   Quit Race         a popup, then RC_QUIT_RACE, through the autosave if
//                     any
//
// What is ported, retail's addresses (SLES_507.31):
//
//   ShouldSee... (the tests above)          0x001dc6e8 .. 0x001dcac0
//   EndGameScreens::BuildScreenList         0x001dcae0
//   EndGameScreens::ResetAllScreenCounters  0x001dcd20  (empty)
//   EndGameScreens::EndGameScreens          0x001dcd28
//   EndGameScreens::~EndGameScreens         0x001dcda8
//   EndGameScreens::GetNextScreen           0x001dce18
//   EndGameScreens::RemoveScreen(char *)    0x001dce40
//   EndGameScreens::AdvanceScreen           0x001dcec8
//   EndGameScreens::AtRoot                  0x001dcee8
//   EndGameScreens::MoveBackScreen          0x001dcf00
//   EndGameScreens::GetCurrentScreen        0x001dcf20
//   EndGameScreens::Constructed             0x001dcf30  (empty)
//   EndGameScreens::ResumeScreens           0x001dcf38
//   EndGameScreens::SuspendScreens          0x001dcfe8
//   EndGameScreens::AutosaveCompletedCallback 0x001dd038
//   EndGameScreens::SetAutosaveCallback     0x001dd070, and its bridge
//                                           0x001e25e8
//   EndGameMenusBase::EndGameMenusBase      0x001dd080
//   EndGameMenusBase::HandleEvent           0x001dd0f0
//   EndGameMenusBase::~EndGameMenusBase     0x001e2558
//   the screens' callback                   0x001dd278
//   EndGameMenu: its six items' tests       0x001e11a8 .. 0x001e12b0
//   EndGameMenu::EndGameMenu                0x001e12b8
//   EndGameMenu::InitLabels                 0x001e15f0
//   EndGameMenu::MaybeRestart               0x001e1858, and its four
//                                           callers 0x001e1818 .. 0x001e1848
//   EndGameMenu::FindItem                   0x001e1918
//   the items' actions                      0x001e1950 .. 0x001e19c8
//   EndGameMenu::HandleEvent                0x001e19e0
//   EndGameMenu::~EndGameMenu               0x001e2270
//
// The other screens' classes are not ported here: each is a constructor
// in gEndGameScreenCtorFns, and with none the screen gets a bare
// EndGameMenusBase, which only walks the list. The Autosave screen is not
// ported either; nothing on the retail disc lists it.
//
// docs/formats/end-game.md has the decode.

#ifndef ENDGAME_H
#define ENDGAME_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"
#include "blist.h"
#include "bmenu.h"

struct BGameFlow;

// The screens' names, retail's gp-17624 .. gp-17572 (0x002b8c98 on).
extern const char kEndGamePointsRewardsScreen[];    // "Points Rewards"
extern const char kEndGameTaskRewardsScreen[];      // "Task Rewards"
extern const char kEndGameEventsUnlockedScreen[];   // "Events Unlocked"
extern const char kEndGameRewardMenuScreen[];       // "Reward menu"
extern const char kEndGameRaceResultsScreen[];      // "Race Results"
extern const char kEndGameTourneyStandingsScreen[]; // "Tourney Standings"
extern const char kEndGameBestLapTimesScreen[];     // "Best Lap Times"
extern const char kEndGameBestTotalTimesScreen[];   // "Best Total Times"
extern const char kEndGameAutosaveScreen[];         // "Autosave"
extern const char kEndGameBTCResults1PScreen[];     // "Be The Cop Results 1P"
extern const char kEndGameBTCResults2PScreen[];     // "Be The Cop Results 2P"
extern const char kEndGameLapTimes1PScreen[];       // "Lap Times 1P"
extern const char kEndGameLapTimes2PScreen[];       // "Lap Times 2P"
extern const char kEndGameMenuScreen[];             // "End Game Menu"

// The screens in INGAMEB, as FlailerScreenConfig registers them. The four
// reward screens share one.
#define END_GAME_REWARDS_SCREEN        0x7e420558u
#define END_GAME_RACE_RESULTS_SCREEN   0xab049b2bu   // RACE_RESULTS
#define END_GAME_TOURNEY_SCREEN        0x0532b6ffu   // TOURNEY_STANDINGS
#define END_GAME_BEST_LAP_SCREEN       0xacb2a4cau   // BEST_LAP_TIMES
#define END_GAME_BEST_TOTAL_SCREEN     0xf5a3cf51u   // BEST_TOTAL_TIMES
#define END_GAME_MENU_SCREEN           0x1a64e903u   // END_GAME_MENU
#define END_GAME_BTC_1P_SCREEN         0x67eb8d12u
#define END_GAME_BTC_2P_SCREEN         0x67eb8d33u
#define END_GAME_LAP_TIMES_1P_SCREEN   0xc4881cbdu
#define END_GAME_LAP_TIMES_2P_SCREEN   0xc4881cdeu
// The letterbox bars over every end-game screen.
#define END_GAME_LETTERBOX_SCREEN      0x49c15518u

// Every end-game screen's "previous" prompt, hidden on the first screen.
#define END_GAME_OBJ_PREVIOUS          0xaf6f1cdcu
// END_GAME_MENU's title, its bloom and its six items, MENUITEM_1 to 6.
#define END_GAME_MENU_OBJ_TITLE        0x5964eab1u
#define END_GAME_MENU_OBJ_BLOOM        0xab671c9au
#define END_GAME_MENU_ITEM_1           0x52e039f3u
#define END_GAME_MENU_NUM_ITEMS        6
// The in-race popup, and its two buttons here: OK and Cancel.
#define END_GAME_POPUP_SCREEN          0x037f3133u
#define END_GAME_LANG_OK               0x38277
#define END_GAME_LANG_CANCEL           0x38278

// ---------------------------------------------------------------- the list

// EndGameScreens, 72 bytes: a bPList of names and the node of the screen
// up. Every word from 24 on is zeroed. The screens' classes use four of
// them as once-only flags for the end-of-race speech: Zeroed[0] (24) is
// set by the Race Results points tally and the Points Rewards screen,
// Zeroed[1] (28) by the Task Rewards screen (endresults.c), Zeroed[7]
// (52) by Best Lap Times and Zeroed[8] (56) by Best Total Times
// (endtimes.c). Nothing reads the rest.
typedef struct EndGameScreens {
    int32_t   ScreensEnabled;      //  0  between Resume and Suspend
    int32_t   LatestConstructed;   //  4  never written
    int32_t   ContinueRaceType;    //  8  eContinueRaceType, never read
    bNode     ScreenList;          // 12  bPNodes, each a screen's name
    bNode    *CurrentScreen;       // 20  a node of ScreenList
    int32_t   Zeroed[12];          // 24  the speech flags, and the rest
} EndGameScreens;                  // 72

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char endgamescreens_layout_check[
    (offsetof(EndGameScreens, ScreenList) == 12
     && offsetof(EndGameScreens, CurrentScreen) == 20
     && sizeof(EndGameScreens) == 72) ? 1 : -1];
#endif

// gp-17628: the one there is, which the constructor sets and the
// destructor clears. The screens' classes reach it through here.
extern EndGameScreens *pEndGameScreens;

// The tests, in BuildScreenList's order.
int32_t endgame_should_see_points_reward_screen(void);  // 0x001dc850
int32_t endgame_should_see_task_reward_screen(void);    // 0x001dc910
int32_t endgame_should_see_events_unlocked(void);       // 0x001dc898
int32_t endgame_should_see_reward_menu(void);           // 0x001dc758
int32_t endgame_should_see_btc_results_1p(void);        // 0x001dc6e8
int32_t endgame_should_see_btc_results_2p(void);        // 0x001dc720
int32_t endgame_should_see_race_results(void);          // 0x001dc928
int32_t endgame_should_see_tourney(void);               // 0x001dc990
int32_t endgame_should_see_best_lap_times(void);        // 0x001dc9f0
int32_t endgame_should_see_best_total_times(void);      // 0x001dca40
int32_t endgame_should_auto_save(void);                 // 0x001dcaa8
int32_t endgame_should_see_end_game(void);              // 0x001dcab8
// 0x001dcac0: GameType is not 6. ShowPointsResults' (RE-2).
int32_t endgame_is_not_game_type_6(void);

// The constructor on `mem` (bMalloc(72, "EndGameScreens", 0, 16)): the
// list built, the first screen current, not enabled. The destructor
// changes to no screen if enabled, gives the nodes back and deletes the
// list with flags & 1. gEndGameScreensCtorFn and gEndGameScreensDestroyFn
// in shape.
EndGameScreens *endgame_screens_construct(void *mem, int32_t continueType);
void endgame_screens_destroy(EndGameScreens *s, int32_t flags);

void endgame_screens_build_screen_list(EndGameScreens *s);
void endgame_screens_reset_all_screen_counters(EndGameScreens *s);
// The name after the current one, NULL at the end.
const char *endgame_screens_get_next_screen(const EndGameScreens *s);
// The first node named `name` unlinked and given back; none, nothing.
void endgame_screens_remove_screen(EndGameScreens *s, const char *name);
// The next node current, unless at the end.
void endgame_screens_advance_screen(EndGameScreens *s);
// Whether the first node is current.
int32_t endgame_screens_at_root(const EndGameScreens *s);
// The node before current, unless at the first.
void endgame_screens_move_back_screen(EndGameScreens *s);
// The current node's name. An empty list has none, NULL.
const char *endgame_screens_get_current_screen(const EndGameScreens *s);
void endgame_screens_constructed(EndGameScreens *s);

// ResumeScreens: once, the current screen up -- the Autosave screen
// pushed instead, if it is current -- and the letterbox bars shown.
// SuspendScreens: once, no screen and no bars. Both do nothing for NULL
// (rcpost.h's gEndGameScreensResumeFn and gEndGameScreensSuspendFn).
void endgame_screens_resume(EndGameScreens *s);
void endgame_screens_suspend(EndGameScreens *s);

// The autosave's end: the next screen up. SetAutosaveCallback hands it to
// SetAutosaveCompletionCallback, on pEndGameScreens.
void endgame_screens_autosave_completed(EndGameScreens *s);
void endgame_screens_set_autosave_callback(EndGameScreens *s);

// ---------------------------------------------------------------- the classes

struct EndGameMenusBase;

// The virtual functions, in retail's vtable order: Scroll (+8), HandleEvent
// (+16), Tick (+24), Render (+32) and the destructor (+40). Scroll has
// PAD_LEFT and PAD_RIGHT, Tick TICK and Render RENDER.
typedef void (*EndGameMenuFn)(struct EndGameMenusBase *m, BScreenMessage msg,
                              BScreenCallbackData *data);
typedef struct EndGameMenusVTable {
    EndGameMenuFn Scroll;
    EndGameMenuFn HandleEvent;
    EndGameMenuFn Tick;
    EndGameMenuFn Render;
    void (*Destroy)(struct EndGameMenusBase *m, int32_t flags);
} EndGameMenusVTable;

// EndGameMenusBase, 8 bytes; retail has its vtable second.
typedef struct EndGameMenusBase {
    uint32_t                  ScreenHash;  // 0
    const EndGameMenusVTable *vt;          // 4
} EndGameMenusBase;

extern const EndGameMenusVTable kEndGameMenusBaseVTable;  // 0x002b9148

// The base's constructor: the "previous" prompt shown unless the list is
// at its first screen. Its HandleEvent: SELECT to the next screen (the
// Autosave screen taken off the list and pushed, if it is next), BACK to
// the one before, PAD_UP and PAD_DOWN silent, and PAD_LEFT, PAD_RIGHT,
// TICK and RENDER to Scroll, Tick and Render. Its destructor deletes with
// flags & 1.
EndGameMenusBase *endgame_menus_base_construct(EndGameMenusBase *m,
                                               uint32_t hash);
void endgame_menus_base_handle_event(EndGameMenusBase *m, BScreenMessage msg,
                                     BScreenCallbackData *data);
void endgame_menus_base_destroy(EndGameMenusBase *m, int32_t flags);

// The callback's classes, by the screen's name, each with retail's size
// and allocation name. The End Game Menu is this file's; the rest are
// gEndGameScreenCtorFns'.
enum {
    END_GAME_CLASS_POINTS_REWARDS,
    END_GAME_CLASS_TASK_REWARDS,
    END_GAME_CLASS_EVENTS_UNLOCKED,
    END_GAME_CLASS_REWARD_MENU,
    END_GAME_CLASS_RACE_RESULTS,
    END_GAME_CLASS_TOURNEY_STANDINGS,
    END_GAME_CLASS_BEST_LAP_TIMES,
    END_GAME_CLASS_BEST_TOTAL_TIMES,
    END_GAME_CLASS_MENU,
    END_GAME_CLASS_BTC_RESULTS_1P,
    END_GAME_CLASS_BTC_RESULTS_2P,
    END_GAME_NUM_CLASSES
};

// A class's constructor on `mem`, for the screen `hash`; `data` is the
// ACTIVATE's.
typedef EndGameMenusBase *(*EndGameScreenCtor)(void *mem, uint32_t hash,
                                               BScreenCallbackData *data);

// gp-17568: the class of the screen up, NULL between screens.
extern EndGameMenusBase *pEndGameMenuInstance;

// 0x001dd278, in the flow's shape: `gf` is not read.
void endgame_screen_callback(struct BGameFlow *gf, BScreenMessage msg,
                             BScreenCallbackData *data);

// ---------------------------------------------------------------- the menu

// The items' kinds, in the order the constructor tries them.
#define END_GAME_ITEM_NEXT_RACE      0
#define END_GAME_ITEM_RESTART_RACE   1
#define END_GAME_ITEM_RESTART_EVENT  2
#define END_GAME_ITEM_VIEW_REPLAY    3
#define END_GAME_ITEM_LAP_TIMES      4
#define END_GAME_ITEM_QUIT           5

// EndGameMenu's State: the popup up, by the item it asks about. The
// constructor leaves it unwritten; only a popup's dismiss reads it.
#define END_GAME_MENU_STATE_RESTART_RACE   0
#define END_GAME_MENU_STATE_RESTART_EVENT  1
#define END_GAME_MENU_STATE_QUIT           2
#define END_GAME_MENU_STATE_NEXT_RACE      3

// An item, 20 bytes, bMalloc(20, "EndGameMenuItem", 0, 16).
typedef struct EndGameMenuItem {
    bNode     Node;    //  0
    int32_t   Label;   //  8  a LanguageID
    uint32_t  Hash;    // 12  its MENUITEM, 0 until placed
    int32_t   Kind;    // 16  END_GAME_ITEM_*
} EndGameMenuItem;     // 20

// EndGameMenu, 112 bytes.
typedef struct EndGameMenu {
    EndGameMenusBase Base;        //   0
    int32_t          State;       //   8  END_GAME_MENU_STATE_*
    BHighlightAnim   Highlight;   //  12  the bloom
    int32_t          Labels[15];  //  44  LanguageIDs, InitLabels'
    bNode            Items;       // 104  EndGameMenuItems
} EndGameMenu;                    // 112

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char endgamemenu_layout_check[
    (offsetof(EndGameMenu, State) == 8
     && offsetof(EndGameMenu, Highlight) == 12
     && offsetof(EndGameMenu, Labels) == 44
     && offsetof(EndGameMenu, Items) == 104
     && sizeof(EndGameMenu) == 112
     && sizeof(EndGameMenuItem) == 20) ? 1 : -1];
#endif

extern const EndGameMenusVTable kEndGameMenuVTable;  // 0x002b8f38

// The constructor: the bloom on the menu's ANIMATING_MENUITEM, the labels
// for this kind of race, and an item for each kind this race has, on
// MENUITEM_1 on in order; the items left over hidden and the title named.
// `data`'s param is cleared.
EndGameMenusBase *endgame_menu_construct(void *mem, uint32_t hash,
                                         BScreenCallbackData *data);
void endgame_menu_init_labels(EndGameMenu *m, int32_t *labels);
// The OK/Cancel popup, `title` and `message` LanguageIDs; the menu hidden
// under it and State `state`.
void endgame_menu_maybe_restart(EndGameMenu *m, int32_t title,
                                int32_t message, int32_t state);
// The item on MENUITEM `hash`, NULL for none.
EndGameMenuItem *endgame_menu_find_item(EndGameMenu *m, uint32_t hash);
void endgame_menu_handle_event(EndGameMenusBase *m, BScreenMessage msg,
                               BScreenCallbackData *data);
void endgame_menu_destroy(EndGameMenusBase *m, int32_t flags);

// ---------------------------------------------------------------- seams
//
// Shared with other files: rcpost.h's gChangeToScreenFn, trackflow.h's
// gSetFlailerScreenVisibilityFn, pausemenu.h's gGrayMenuItemFn,
// gSummonPopupFn and gFlailerCurrentScreenFn, fred.h's gIsCarUnlockedFn
// and fredrace.h's gRaceEventGetStatusFn and
// gRaceEventIsThereAnotherRaceFn. Each one below does nothing when NULL,
// and answers 0 unless it says otherwise.

// The classes this file does not port, by END_GAME_CLASS_*. NULL makes a
// bare EndGameMenusBase.
extern EndGameScreenCtor gEndGameScreenCtorFns[END_GAME_NUM_CLASSES];
// GetTranslatedString(int) (0x0021e560), for the popup's message.
extern const char *(*gEndGameTranslateFn)(int32_t id);
// The animation kit the bloom draws with. NULL, or a NULL answer, leaves
// the bloom alone.
extern BAnim *(*gEndGameMenuAnimFn)(void);
// SetAutosaveCompletionCallback (0x00247d98): what to call when the
// Autosave screen is done.
extern void (*gSetAutosaveCompletionCallbackFn)(void (*cb)(void));
// The port's: non-zero, Quit and Next Race go through the Autosave screen
// with autosave off too, so the end of a race always asks before it saves.
// 0 is retail's, which goes there only with Fred.Autosave on.
extern int32_t gEndGameAlwaysAskToSave;
// The port's: whether View Replay has a replay to go to. A 0 leaves the
// item off; NULL is retail's, which only reads the ReplayManager.
extern int32_t (*gEndGameReplayViewableFn)(void);
// TheRaceEvent's (0x0031b600) calls, none named in the image:
//   0x00200b30(ev, i, ev+8)  reward `i` tested against the event's state
//   0x00201db8               GetOldStatus against GetStatus: the race
//                            took the event on
//   0x00201bd8               GetOldStatus against GetStatus: the race
//                            set the event back
//   0x001f7458(ev+432, ev)   the events the race opened (0x001f7398)
//   0x00201fb0               the state kept, when 0x00201bd8 says so
//   0x00201b38               the event set back to its first race
extern int32_t (*gRaceEventRewardTestFn)(int32_t i);
extern int32_t (*gRaceEventStatusAdvancedFn)(void);
extern int32_t (*gRaceEventStatusFellFn)(void);
extern int32_t (*gRaceEventNumOpenedFn)(void);
extern void (*gRaceEventKeepStateFn)(void);
extern void (*gRaceEventRestartFn)(void);

#endif
