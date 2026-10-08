// pausemenu -- the pause menu: retail's PAUSE_MAIN module, PauseMenu and
// the "Pause Menu" screen's callback.
//
// START in a race posts REQUEST_PAUSE, and RCSTATE_PAUSE's ACTIVATE
// (rcpost.c) calls EnterPause on ThePauseMenu with the port that asked,
// then changes to "Pause Menu" (PAUSE_MENU in INGAMEB, 0x605d2bf1). The
// screen's callback activates the menu: it grays the items this race has
// no use for and names Resume, Restart and Quit for the kind of race it
// is. Then:
//
//   Resume Race         RequestUnPause(RESUME_RACE), if the player who
//                       paused asked; START does the same
//   Restart             a Yes/No popup; Yes copies each player's settings
//                       into TheRaceParameters and RequestUnPause(RESTART)
//   Options             "Pause Options"
//   View Replay         RequestUnPause(INSTANT_REPLAY)
//   View Objective      "Race Objective", or "Race Objective 2PBAC"
//   View Cop Controls   "Pause BAC controls"
//   Quit Race           a Yes/No popup; Yes is RequestUnPause(QUIT_RACE)
//   Debug               "Debug Menu"; always hidden on the retail disc
//
// BACK does nothing. RCSTATE_PAUSE's UNACTIVATE changes to no screen and
// calls ExitPause.
//
//   ChooseWhoSelectedMenuItem(ScreenCallbackData *)  0x00170560
//   PauseMenu::PauseMenu                         0x00170580
//   PauseMenu::~PauseMenu                        0x001705e0
//   PauseMenu::EnterPause(JoystickPort)          0x00170638
//   PauseMenu::ExitPause                         0x00170720
//   PauseMenu::Activate(unsigned int)            0x00170738
//   PauseMenu::DeActivate                        0x00170958
//   PauseMenu::AllPlayerJoysticksPluggedIn       0x00170968
//   PauseMenu::CheckJoysticks                    0x001709d8
//   PauseMenu::MaybeRestart                      0x001709e0
//   PauseMenu::MaybeQuit                         0x00170b08
//   PauseMenu::MaybeResume(int)                  0x00170c30
//   PauseMenu::MenuCallback                      0x00170c90
//   PauseMenuCallback                            0x00171060
//
// and retail's new tHighlightAnimation::HandleMessage (0x00248ae0), which
// the pause screens share.
//
// HandlePauseMenuReplaySpecialEvents (0x001703e0) is the replay's and is
// not ported. Nor are the screens the menu leads to, yet: Pause Options
// and its two pages (0x00171180 to 0x00173e30), the objective and the cop
// controls (0x00171a28 to 0x00172068) and the debug menu.
//
// docs/formats/pause-menu.md has the decode.

#ifndef PAUSEMENU_H
#define PAUSEMENU_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"
#include "bmenu.h"
#include "bpopup.h"
#include "joystick.h"

struct BGameFlow;
struct BScreenConfig;
struct Player;
struct ReplayManager;

// The eight screens EnterPause gives the pausing port, in its order:
// retail's gp-21104 down to gp-21076, the strings at 0x002b30a8 on.
extern const char kPauseMenuScreen[];           // "Pause Menu"
extern const char kPauseOptionsScreen[];        // "Pause Options"
extern const char kPauseAudioScreen[];          // "Pause audio"
extern const char kPauseDisplayScreen[];        // "Pause display"
extern const char kPauseDebugMenuScreen[];      // "Debug Menu"
extern const char kPauseRaceObjectiveScreen[];  // "Race Objective"
extern const char kPauseRaceObjective2PBACScreen[]; // "Race Objective 2PBAC"
extern const char kPauseBACControlsScreen[];    // "Pause BAC controls"

// PAUSE_MENU in INGAMEB, as FlailerScreenConfig registers it, and its
// items: MENUITEM_1 to MENUITEM_8.
#define PAUSE_MENU_SCREEN          0x605d2bf1u
#define PAUSE_MENU_ITEM_RESUME     0x52e039f3u   // "Resume Race"
#define PAUSE_MENU_ITEM_RESTART    0x52e039f4u   // "Restart"
#define PAUSE_MENU_ITEM_OPTIONS    0x52e039f5u   // "Options"
#define PAUSE_MENU_ITEM_REPLAY     0x52e039f6u   // "View Replay"
#define PAUSE_MENU_ITEM_OBJECTIVE  0x52e039f7u   // "View Objective"
#define PAUSE_MENU_ITEM_COP_CONTROLS 0x52e039f8u // "View Cop Controls"
#define PAUSE_MENU_ITEM_QUIT       0x52e039f9u   // "Quit Race"
#define PAUSE_MENU_ITEM_DEBUG      0x52e039fau   // "Debug"
// ANIMATING_MENUITEM, the text the bloom draws into.
#define PAUSE_MENU_OBJ_BLOOM       0xab671c9au

// POPUP in INGAMEB, the in-race popup: three message lines, two buttons
// and a title.
#define PAUSE_POPUP_SCREEN         0x037f3133u

// The popups' two buttons, Yes and No, the same for both.
#define PAUSE_LANG_YES             0x38273
#define PAUSE_LANG_NO              0x38274

// PauseMenu's State.
#define PAUSE_MENU_STATE_NONE      0   // not paused
#define PAUSE_MENU_STATE_MENU      1   // the menu takes SELECT
#define PAUSE_MENU_STATE_RESTART   2   // the Restart popup is up
#define PAUSE_MENU_STATE_QUIT      3   // the Quit popup is up

// PauseMenu, 56 bytes; ThePauseMenu is racecoord.h's.
typedef struct PauseMenu {
    int32_t        State;               //  0  PAUSE_MENU_STATE_*
    uint32_t       ScreenHash;          //  4  the screen's, from Activate
    JoystickPort   Port;                //  8  the port that paused, -1
    int32_t        OptionsChooser;      // 12  who chose Options
    int32_t        ReplayChooser;       // 16  who chose View Replay
    struct Player *PausingPlayer;       // 20  the player on that port
    BHighlightAnim Highlight;           // 24  the bloom
} PauseMenu;                            // 56

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char pausemenu_layout_check[
    (offsetof(PauseMenu, Port) == 8
     && offsetof(PauseMenu, PausingPlayer) == 20
     && offsetof(PauseMenu, Highlight) == 24
     && sizeof(PauseMenu) == 56) ? 1 : -1];
#endif

// ---------------------------------------------------------------- the class

// The bloom on PAUSE_MENU's ANIMATING_MENUITEM in BloomTargetColor, and
// every field -1 or 0 but the bloom: not paused, on no screen.
PauseMenu *pause_menu_construct(PauseMenu *m);
void pause_menu_destroy(PauseMenu *m, int32_t flags);

// EnterPause: the port, the player on it (player 0 first, then player 1,
// by PlayerNumber), the rumble stopped on both players' pads, and the
// port given to the eight pause screens. ExitPause: not paused, no port,
// no player.
void pause_menu_enter_pause(PauseMenu *m, JoystickPort port);
void pause_menu_exit_pause(PauseMenu *m);

// Activate: the menu on screen `hash`, its items grayed for this race and
// Resume, Restart and Quit named for it. DeActivate: no screen.
void pause_menu_activate(PauseMenu *m, uint32_t hash);
void pause_menu_deactivate(PauseMenu *m);

// IsJoystickPluggedIn over every player's port, ANDed bit by bit, as
// retail does.
int32_t pause_menu_all_player_joysticks_plugged_in(const PauseMenu *m);
void pause_menu_check_joysticks(PauseMenu *m);

// MaybeRestart and MaybeQuit summon the popup and hide the menu.
// MaybeRestart needs every pad in; MaybeQuit asks nothing. MaybeResume
// unpauses when every pad is in and `port` is the pausing player's, and
// answers whether it did.
void pause_menu_maybe_restart(PauseMenu *m);
void pause_menu_maybe_quit(PauseMenu *m);
int32_t pause_menu_maybe_resume(PauseMenu *m, int32_t port);

void pause_menu_menu_callback(PauseMenu *m, BScreenMessage msg,
                              BScreenCallbackData *data);

// ChooseWhoSelectedMenuItem: with two players the port the item came
// from, otherwise player 0's (by index).
int32_t pause_choose_who_selected_menu_item(const BScreenCallbackData *data);

// tHighlightAnimation::HandleMessage (0x00248ae0): TICK animates the
// bloom, an item's HIGHLIGHT moves it there.
void pause_highlight_handle_message(BHighlightAnim *h, BScreenMessage msg,
                                    const BScreenCallbackData *data);

// The FlailerScreenConfig callback for "Pause Menu", in the flow's shape:
// `gf` is not read. ACTIVATE enters the pause first if nothing has.
void pause_menu_callback(struct BGameFlow *gf, BScreenMessage msg,
                         BScreenCallbackData *data);

// ---------------------------------------------------------------- seams
//
// Shared with other files: rcpost.h's gChangeToScreenFn,
// gReplayMuteHighlightsFn and gRestoreTypeChangedHandlersFn, and
// trackflow.h's gSetFlailerScreenVisibilityFn. Each one below does nothing
// when NULL, and answers 0 unless it says otherwise.

// GrayMenuItem (0x0016d198), in retail's argument order: 1 enables the
// item, 0 grays it, 2 grays it and hides it.
extern void (*gGrayMenuItemFn)(uint32_t item, int32_t mode, uint32_t screen);
// SetScreenFilterPort (0x0016d4c8): only `port` drives the screen `name`.
extern void (*gSetScreenFilterPortFn)(const char *name, JoystickPort port);
// PortStopForce (0x0012c240): the pad's rumble off.
extern void (*gPortStopForceFn)(JoystickPort port);
// FlailerScreenList::SummonPopup (0x0016cd68) on TheFlailerScreenList.
extern void (*gSummonPopupFn)(const BPopupConfig *cfg);
// TheFlailerScreenList's pCurrent (+412), the screen up: a popup's parent.
extern const struct BScreenConfig *(*gFlailerCurrentScreenFn)(void);
// GetTranslatedString(int) (0x0021e560).
extern const char *(*gPauseTranslateFn)(int32_t id);
// The animation kit the bloom draws with, its clock the flow's. NULL, or
// a NULL answer, leaves the bloom alone.
extern BAnim *(*gPauseMenuAnimFn)(void);
// ReplayManager's count of instant-replay snapshots (+140), on
// pReplayManager. View Replay is there with one or more.
extern int32_t (*gReplayNumInstantReplaySnapshotsFn)(
    const struct ReplayManager *rm);

#endif
