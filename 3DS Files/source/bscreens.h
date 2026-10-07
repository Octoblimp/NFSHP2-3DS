#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "banim.h"
#include "gameflow.h"

// The three screens the main menu leads to.
//
// NewMainMenu::HandleEvent routes its three items at "Cops On Mode Select",
// "Cops Off Mode Select" and "Options" (gameflow.c). All three are real
// screens in FRONTEND\FRONTB.BUN with real MENUITEM_n objects, and until now
// none of them was registered, so the menu was a dead end. This is the port
// of their behaviour, decompiled in docs/formats/frontend-screens.md with an
// address for every rule here:
//
//   CopsOnModeSelect    0x00203d28 ctor, 0x00203f50 HandleEvent
//   CopsOffModeSelect   0x002043d0 ctor, 0x002045f8 HandleEvent
//   tOptionsScreen      0x001e09d0 ctor, 0x001e0ac0 HandleEvent,
//                       on OptionsScreenBase 0x001e53d0 / 0x001e56c0
//
// Like bui.c, bmenu.c and gameflow.c this is free of <3ds.h>: everything
// that touches a screen, a movie, the menu or the race goes through
// BScreensHooks, so tools/bscreens_check.py can drive it on the host and
// diff it against a second implementation.
//
// What is NOT here is the drawing. Each of these screens owns a small
// animation kit -- tSlideAnimation, tSlideInAnimation, tSlideOutAnimation,
// tHighlightAnimation, tAnimatedBlurb, SelectionSet -- which moves Flailer
// objects along cubic splines. That kit is banim.c, and each screen embeds
// one of everything it uses. The kit needs to be able to ask the bundle
// which MENUITEM_i_GROUPs a screen defines, so bscr_set_anim_hooks has to
// be called for the animations to have anything to move; with no hooks the
// screens still work, and every animation is simply over on the first
// frame.

// FlailerScreenConfig hashes, recovered by tools/screen_registry.py. As
// everywhere in this port the registry name and the authored name are two
// different strings: "Cops On Mode Select" against COPS_ON_MODE_SELECT.
#define BSCR_SCREEN_COPS_ON_MODE_SELECT   0x5b35f533u
#define BSCR_SCREEN_COPS_OFF_MODE_SELECT  0x033e7771u
#define BSCR_SCREEN_OPTIONS               0x95ad096bu   // bhash("OPTIONS")

// bStringHash("MENUITEM_n"). Consecutive because bStringHash is incremental
// and only the last character moves; gameflow.h names the first three.
#define BSCR_ITEM_MENUITEM(n)  (0x52e039f2u + (uint32_t)(n))

// bStringHash("MI_n_MASK"), the bitmap behind each label. These are 33^5
// apart -- five characters follow the digit -- which is how they were
// cracked. SelectionSet keeps its current item as one of these, and
// FlailerGetBoundingBox on one of them is what positions the two brackets.
#define BSCR_MI_MASK(n)  (0x6e34e350u + (uint32_t)((n) - 1) * 39135393u)

#define BSCR_OBJ_MI_UNDERSCORE  0x32c91daeu  // bracket under the current item
#define BSCR_OBJ_MI_OVERSCORE   0xc671680cu  // and over it

// tAnimatedBlurb's text object, and the bitmap it is clipped to. Neither
// name is an ELF literal -- they were cracked from the hash -- and every
// screen in FRONTB.BUN that has a blurb carries the same authoring
// placeholder in SCROLLING_TEXT: "This text will scroll sideways across the
// screen. The string has to be really long to make it work." Its LanguageID
// is 0 on disc, which is what NewText replaces.
#define BSCR_OBJ_SCROLLING_TEXT    0x75980cf0u
#define BSCR_OBJ_SCROLL_TEXT_CLIP  0x5e11b599u

// The bar tAnimatedBlurb wipes the old line out with, and MENUITEM_n_GROUP's
// sibling for the two brackets. Both were cracked from their hashes:
// WHITEOUT_BAR is the fadeout half of the blurb and UNDERSCORE_GROUP is what
// StartChangeToScreen (0x00203ec8) appends to the exit animation so the
// brackets leave with the items.
#define BSCR_OBJ_WHITEOUT_BAR      0x70a404ecu
#define BSCR_GROUP_UNDERSCORE      0x97bf4b25u

// The spare text objects tHighlightAnimation draws its scaled copy into.
// Neither hash has been cracked -- a seven-character exhaustive sweep and a
// 35,700-name compositional dictionary both came up empty -- so they are
// carried as the numbers the ELF has. Every frontend screen passes the first
// with BloomTargetColor; OptionsScreenBase (0x001e53d0) builds a second one
// on top with colour -1, which leaves the copy whatever colour it came with.
#define BSCR_OBJ_BLOOM_TEXT        0xab671c9au
#define BSCR_OBJ_BLOOM_TEXT_2      0x1042eac3u

// Where the two brackets sit relative to the current item's bounding box.
// CopsOn/CopsOffModeSelect::SetupHighlight (0x00204160, 0x002047c8) use the
// float overload of FlailerSetTopLeftY and the two globals UnderscoreOffset
// (-3.0f) and OverscoreOffset (6.0f, subtracted); OptionsScreenBase's
// HandleHighlight (0x001e55a0) uses the int overload and no underscore
// offset at all. Three pixels, and nothing but the two call sites explains
// them, so both are spelled out rather than averaged.
#define BSCR_UNDER_MODE_SELECT   (-3.0f)
#define BSCR_OVER_MODE_SELECT    (-6.0f)
#define BSCR_UNDER_OPTIONS       (0.0f)
#define BSCR_OVER_OPTIONS        (-6.0f)

// GameTypes, the two the Mode Selects write into Fred.GameType (0x00304580).
#define BSCR_FRED_EXPRESS_GAME     2   // Quick Race
#define BSCR_FRED_ULTIMATE_GAME    8   // World Championship
#define BSCR_FRED_HOTPURSUIT_GAME  9   // Ultimate Road Racer

// GrayMenuItem (0x00168498) mode. The name is a misnomer for two of the
// three: only mode 0 leaves the item on screen.
typedef enum {
    BSCR_GRAY_DISABLE = 0,   // clear ENABLED; the item stays drawn, grayed
    BSCR_GRAY_ENABLE  = 1,   // set ENABLED and make the object VISIBLE
    BSCR_GRAY_HIDE    = 2,   // clear ENABLED and make the object INVISIBLE
} BScrGrayMode;

// Everything these screens do to the outside world. All of it is optional.
typedef struct {
    void* user;

    // GrayMenuItem (0x00168498). `screen` is never 0 here: the one caller
    // passes its own hash.
    void (*grayMenuItem)(void* user, uint32_t screen, uint32_t item,
                         BScrGrayMode mode);

    // tAnimatedBlurb::NewText (0x00232ef0): the LanguageID of the sentence
    // that describes the highlighted item.
    void (*setBlurb)(void* user, uint32_t screen, int blurbId);

    // SetupHighlight's other half: FlailerGetBoundingBox on the MI_n_MASK
    // bitmap, then MI_UNDERSCORE to box.bottom + `under` and MI_OVERSCORE to
    // box.top + `over`. The two deltas are the caller's because the Mode
    // Selects and the Options screen do not use the same ones -- see
    // the BSCR_UNDER_* / BSCR_OVER_* pairs above.
    void (*moveBrackets)(void* user, uint32_t screen, uint32_t mask,
                         float under, float over);

    // FlailerScreenList::StartMovie (0x0016ce30) / StopMovie (0x0016d0a0),
    // which are bgf_start_movie and bgf_stop_movie: the host's hooks call
    // them on the flow.
    void (*startMovie)(void* user, const char* path);
    void (*stopMovie)(void* user);

    void (*jukebox)(void* user, int start);          // sound::jukebox::Start
    void (*displayOptionsStart)(void* user);         // 0x001e0508

    // StartQuickRace (0x00216c18, quickrace.h), with the transmission
    // button's state the screen keeps. It stops the panel movie, fills
    // TheRaceParameters and starts the race.
    void (*startQuickRace)(void* user, int transmission);
} BScreensHooks;

// How long each screen takes to leave used to be a constant here, worked
// out by hand from the groups FRONTB.BUN defines: 0.25s on Cops On, 0.20s
// on Cops Off, 0.40s on Options. It is no longer written down anywhere,
// because banim's tSlideOutAnimation asks the bundle which
// MENUITEM_i_GROUPs exist and takes the longest of their durations --
// SplineBaseDuration + i * SplineDeltaDuration, both 0.05f (gp-15932,
// gp-15928). The three numbers now come out rather than going in, which is
// the whole reason to have ported the kit. What they come out as with no
// animation hooks installed is zero, and a zero-length exit finishes on the
// first tick.

// The object each screen's Callback news on SCREEN_ACTIVATE and deletes on
// SCREEN_UNACTIVATE, cut down to the fields anything outside the animation
// kit reads. The original keeps one pointer per class in a file-static
// (`_16CopsOnModeSelect$pInstance` and friends); so does this.
typedef struct {
    bool           live;
    uint32_t       screen;        // +0, the Flailer screen hash
    uint32_t       currentMask;   // SelectionSet::CurrentObject
    int            blurb;         // the last id handed to tAnimatedBlurb
    int            transmission;  // +624 on the Mode Selects; see below

    // The animation kit, in the order the constructors build it. The
    // original news each of these separately and keeps a pointer; the port
    // embeds them, so `exitActive` stands in for the null check on +620.
    BSelSet        sel;           // +4    IndicatorMode 1, MI_n_MASK table
    BBlurb         blurbAnim;     // +152  SCROLLING_TEXT and WHITEOUT_BAR
    BHighlightAnim bloom;         // +568  the copy that scales and fades
    BHighlightAnim bloom2;        // Options only; see BSCR_OBJ_BLOOM_TEXT_2
    bool           hasBloom2;
    BSlideAnim     slideIn;       // +600  built and started on activate
    BExitAnim      exit;          // +620 on the Mode Selects, +92 on Options
    bool           exitActive;

    // How many times the screen's OnTick ran. Nothing in the game reads
    // this; it is here because CopsOnModeSelect::HandleEvent calls OnTick
    // TWICE for one SCREEN_TICK and CopsOffModeSelect calls it once, and a
    // counter is the only way to hold that difference still in a test.
    int            tickCount;
} BScreenInstance;

typedef struct {
    BGameFlow*      gf;
    BScreensHooks   hooks;

    // One BAnim for the module, because RealTimer and RealTimeElapsed are
    // one global each. It is re-slaved to gf's copy at the top of every
    // callback rather than ticked here, so the two cannot drift.
    BAnim           anim;

    BScreenInstance copsOn;
    BScreenInstance copsOff;
    BScreenInstance options;

    // The frontend globals these screens write. BGameFlow already carries
    // the one NewMainMenu writes (`copsOn`, 0x002f3fdc).
    int beACop;          // Fred.MainMenuOpts.BeACop      0x002f3fd8
    int gameType;        // Fred.GameType                 0x00304580
    int numPlayerCars;   // Fred.NumPlayerCars            0x00304588
    int eventTreeType;   // SetTreeType(&Fred.SelectedEventData, n)
    int boost;           // TheRaceParameters.Boost       0x00312804

    // GetVideoMode() (0x001992a0). MODE_PAL = 0, MODE_NTSC = 1, and on NTSC
    // the Options screen hides its Languages item.
    int videoMode;
} BScreens;

// Installs `s` as the module's instance -- the port's `pInstance` -- and
// clears it. `hooks` may be NULL. Call before bgf_service() reaches any of
// these screens; main() does it next to bgf_init().
void bscr_init(BScreens* s, BGameFlow* gf, const BScreensHooks* hooks);

// Hands the animation kit its window onto the bundle. Separate from
// bscr_init because the two layers answer to different parts of main():
// these hooks are FlailerObjectChunk operations and belong with bui.c,
// while BScreensHooks is the game. May be NULL, and may be called before or
// after bscr_init as long as it is before the first screen activates.
void bscr_set_anim_hooks(BScreens* s, const BAnimHooks* hooks);

// The three FlailerScreenConfig callbacks, to put in kScreens[].
void bscr_cops_on_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data);    // 0x00204338
void bscr_cops_off_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);   // 0x00204988
void bscr_options_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data);    // 0x001e0d18

// CopsOnModeSelect::JoyHandler (0x00205040) and its twin: the one button
// either Mode Select listens for itself is
// JOY_EVENT_MAIN_MENU_SELECT_TRANSMISSION (23), and all it does is remember
// whether the button is down. StartQuickRace hands that straight to
// cPlayerSettings::TransmissionType, so holding it while picking Quick Race
// is how a player asks for the other gearbox.
#define BSCR_JOY_SELECT_TRANSMISSION 23
void bscr_joy(BScreens* s, int port, int joyEvent, int pressed);

