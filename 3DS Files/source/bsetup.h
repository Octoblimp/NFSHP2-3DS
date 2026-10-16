#pragma once
#include <stdint.h>

#include "banim.h"
#include "gameflow.h"

// The race setup screens: what a Mode Select leads to before car select.
//
// This slice is "You're The Cop", retail's BeACopChallengeSetup
// (0x001b6c68 .. 0x001b7748), the screen Cops On Mode Select's second item
// opens: Players, Skill Level and Setup. With it come the two small classes
// the setup screens share, from the frontend animation kit's object file:
//
//   tfeSineWave   0x0024a5c0   a value that swings between two bounds
//   the arrows    0x0024a690   the pair of bitmaps either side of the value
//                              being changed, pulsing, following its Y
//
// The arrows class is retail's own (the demo drew its two arrows by hand in
// every screen) and has no name in the image; the port calls it BArrows.
//
// The second slice is You're The Cop's Setup, "Be The Cop Setup": retail's
// BeTheCopSetup (0x001b9248) on RaceSetupBaseClass (0x001b8390), the base
// of every race setup, with its scroller:
//
//   tScrollingMenuList  0x0024a888 on  the rows' Y animations and the up and
//                                      down arrows, a window of seven rows
//
// The third is Cops Off's Challenge, retail's ChallengeScreen (0x001b5f38
// .. 0x001b6c68): Players, Race Type, Skill Level and Setup. Its Setup leads
// to the other four on RaceSetupBaseClass -- SingleRaceSetup (0x001b87d0),
// FreeRunSetup (0x001b8b20), LapKnockoutSetup (0x001b8cb8) and
// TrackKnockoutSetup (0x001b8f60), "Knockout Setup" -- all on the one
// Flailer screen Be The Cop Setup has.
//
// Addresses are retail's, SLES_507.31. Written up in
// docs/formats/frontend-setup.md. Like bscreens.c this is free of <3ds.h>:
// every Flailer call goes out through BSetupHooks under the name of the
// function retail calls, and the animation kit is banim.c, so
// tools/setup_check.py, tools/racesetup_check.py, tools/challenge_check.py
// and tools/racesetups_check.py can run retail's code in mipsemu next to
// this.

// FlailerScreenConfig's hash for "ChallengeBeACop", and the objects on it.
#define BSETUP_SCREEN_BEACOP       0xe55f1297u
#define BSETUP_OBJ_PLAYERS_VALUE   0x164eb99au   // "One Player" / "Two Players"
#define BSETUP_OBJ_SKILL_VALUE     0x53a607f5u   // "Beginner" .. "Expert"
#define BSETUP_OBJ_LEFT_ARROW      0xd1cda594u
#define BSETUP_OBJ_RIGHT_ARROW     0x9345e4a7u

// Fred, the frontend database (0x002fc050), as the byte image the memory
// card saves whole (BMC_SAVE_SIZE). These are the fields the setup screens
// read and write, at retail's offsets.
//
// ChallengeScreenData is 20 bytes in retail, 16 in the demo: the fifth word
// is new, and You're The Cop's skill level moved into it. The demo's
// InitWithDefaults sets the first four; retail's also clears the fifth.
#define FRED_CHALLENGE_SCREEN   8        // DataChallengeScreen, 20 bytes
#define FRED_MAIN_MENU_BEACOP   28       // MainMenuOpts.BeACop
#define FRED_MAIN_MENU_POLICE   32       // MainMenuOpts.mPolice
#define FRED_GAME_TYPE          0x1072c  // GameType
#define FRED_NUM_PLAYER_CARS    0x10734  // NumPlayerCars

// GameTypes, the .mdebug enum: the challenge's race types, and You're The
// Cop's. The Mode Selects write the others.
#define FRED_CHALLENGE_GAME_SINGLE_RACE   3
#define FRED_CHALLENGE_GAME_KNOCKOUT      4
#define FRED_CHALLENGE_GAME_LAP_KNOCKOUT  5
#define FRED_CHALLENGE_GAME_FREE_RUN      6
#define FRED_CHALLENGE_GAME_BE_A_COP      7

typedef struct BChallengeData {
    int32_t numPlayers;       // +0   mNumPlayers, 1 or 2
    int32_t challengeMode;    // +4   mChallengeMode
    int32_t raceMode;         // +8   mRaceMode, RaceParameters.NFSRaceMode
    int32_t skillLevel;       // +12  mSkillLevel, the Challenge screen's
    int32_t beACopSkill;      // +16  retail's: You're The Cop's, 0..2
} BChallengeData;

// DataChallengeScreen::InitWithDefaults (0x001b5e10): 1, 3, 1, 1, 0.
void bsetup_challenge_defaults(BChallengeData* d);
// The 20 bytes at Fred+8, little-endian as the PS2 kept them.
void bsetup_challenge_load(BChallengeData* d, const uint8_t* fred);
void bsetup_challenge_save(const BChallengeData* d, uint8_t* fred);

// DataBeTheCopSetup, Fred+64: 20 bytes in retail, 32 in the demo, whose
// last three words (mZoneCams, mJumpCams, mTrainingCams) are gone. Be The
// Cop Setup changes the last three of these five.
#define FRED_BE_THE_COP_SETUP   64

typedef struct BBeTheCopData {
    int32_t opponentGrid;     // +0   mOpponentGrid
    int32_t opponentType;     // +4   mOpponentType
    int32_t catchup;          // +8   mBoost, "Catch-up": 0 off, 1 on
    int32_t traffic;          // +12  mTraffic, 0..3: minimum .. off
    int32_t damage;           // +16  mDamage, 0 off, 1 on
} BBeTheCopData;

// 0x001b93e0, which FrontendDatabase::InitWithDefaults (0x00183830) calls
// on Fred+64: 2, 0, 1, 0, 1. Catch-up on, traffic minimum, damage on.
void bsetup_btc_defaults(BBeTheCopData* d);
// Fred's two setup blocks at their defaults, as InitWithDefaults leaves
// them before a memory card loads over it: Fred+8 and Fred+64.
void bsetup_fred_defaults(uint8_t* fred);

// The other four setups' blocks, fred.h's SingleRaceSetupData (7 words),
// FreeRunSetupData (3), RaceKnockoutSetupData (7) and LapKnockoutSetupData
// (6); fred.c sets their defaults. Each screen copies its block in whole
// and writes it back whole.
#define FRED_SINGLE_RACE_SETUP    36
#define FRED_FREE_RUN_SETUP       84
#define FRED_RACE_KNOCKOUT_SETUP  96
#define FRED_LAP_KNOCKOUT_SETUP   124

// Everything the setup screens do outside the animation kit. Every hook is
// optional: a missing one does nothing and answers 0.
typedef struct BSetupHooks {
    void* user;

    // FindFlailerObject (0x00143d50): non-zero if `screen` has an object
    // called `object` of `type` (BANIM_TYPE_*, 0 any).
    int (*findObject)(void* user, uint32_t screen, uint32_t object, int type);
    // The three chunk calls the arrows make on the bitmaps they found:
    // FlailerBitmapChunk::SetAlpha(alpha, -1), all four corners (0x001411d8);
    // FlailerObjectChunk::SetCenterY (0x00140930), which puts the top at
    // y - GetHeightFloat() / 2; and ::SetVisibility (0x00140728), 1 visible.
    void (*setBitmapAlpha)(void* user, uint32_t screen, uint32_t object,
                           int alpha);
    void (*setBitmapCenterY)(void* user, uint32_t screen, uint32_t object,
                             float y);
    void (*setBitmapVisible)(void* user, uint32_t screen, uint32_t object,
                             int visible);

    // FlailerGetCenterY (0x00144860): the bounding box's middle, as
    // FlailerGetCenter (0x001447e0) works it out, in ints.
    int32_t (*getCenterY)(void* user, uint32_t screen, uint32_t object);
    // FlailerGetBoundingBox (0x00144280), any type: left and top are the
    // top left truncated, right and bottom add GetWidth and GetHeight. A
    // missing object leaves `box` as it was.
    void (*getBoundingBox)(void* user, uint32_t screen, uint32_t object,
                           int32_t box[4]);
    // FlailerSetTopLeftY (0x00144458), the int one.
    void (*setTopLeftY)(void* user, uint32_t screen, uint32_t object,
                        int32_t y);
    // FlailerGetTopLeftX (0x00144140), the float one.
    float (*getTopLeftX)(void* user, uint32_t screen, uint32_t object);
    // FlailerSetLanguageID (0x001449a8) and FlailerSetVisibility (0x00144968,
    // 1 visible).
    void (*setLanguageID)(void* user, uint32_t screen, uint32_t object,
                          int languageID);
    void (*setVisible)(void* user, uint32_t screen, uint32_t object,
                       int visible);
    // FlailerPrintf (0x00143e70), already formatted: the text object's
    // string. The opponent count's "%d" (0x00330f98).
    void (*printText)(void* user, uint32_t screen, uint32_t object,
                      const char* str);
    // GrayMenuItem (0x0016d198), whose arguments retail passes as (item,
    // mode, screen). BScrGrayMode's modes: 1 enables, 0 grays, 2 hides.
    void (*grayMenuItem)(void* user, uint32_t screen, uint32_t item,
                         int mode);
    // GrayMenuItem(char*, int, int, int) (0x0016d2a8): the same, on the
    // Flailer screen `screen` of the screen list's node called `name`
    // rather than the current one's.
    void (*grayMenuItemNamed)(void* user, const char* name, uint32_t screen,
                              uint32_t item, int mode);

    // FlailerGetTopLeftY (0x00144168), which FlailerObjectChunk::GetTopLeft
    // (0x00140978) answers the same for an object found; 0 for a missing
    // one. And FlailerObjectChunk::SetTopLeftY (0x00140a48), the float one,
    // on an object the scroller found.
    float (*getTopLeftY)(void* user, uint32_t screen, uint32_t object);
    void (*setObjectTopLeftY)(void* user, uint32_t screen, uint32_t object,
                              float y);
    // FlailerSetClipToPoly (0x00144358) and FlailerObjectChunk::
    // SetClipToPoly (0x00140a70): ClipToPoly (+76) = `poly`, and on a text
    // object FORMAT_CLIP too.
    void (*setClipToPoly)(void* user, uint32_t screen, uint32_t object,
                          uint32_t poly);
    // FlailerSetAlpha (0x001448e8): any type. A text object's alpha, or all
    // four of a bitmap's corners.
    void (*setAlpha)(void* user, uint32_t screen, uint32_t object,
                     int alpha);

    // IsJoystickPluggedIn (0x001542f0). The 3DS has port 0 and no other.
    int (*isJoystickPluggedIn)(void* user, int port);

    // FlailerScreenList::StartMovie (0x0016ce30): bgf_start_movie.
    void (*startMovie)(void* user, const char* path);
    // SetHelpOverride (0x0016d448): the list's +400, and gp-17344 set so
    // the help menu rebuilds. `lines` is 0-terminated, or NULL to clear.
    void (*setHelpOverride)(void* user, const int32_t* lines);

    // Three FrontendDatabase calls that belong to car select and the race
    // it starts, and come with them:
    //   MakeChallengeCarsAvailable (0x00183af8), the cars a challenge may
    //     use, through IsCarUnlocked and SetCarAvailability;
    //   0x00183ec0, retail's, a jump to 0x00194898: a VisibleCarSet for the
    //     player, the first car's RideInfo, and CarLoader's Load and
    //     BeginLoading, so car select's car is on its way;
    //   SetupRaceParametersAfterRaceSetup (0x001862b0).
    void (*makeChallengeCarsAvailable)(void* user);
    void (*preloadCars)(void* user);
    void (*setupRaceParametersAfterRaceSetup)(void* user);

    // TheRaceParameters (0x0031a898): the two fields You're The Cop writes
    // as it leaves, NumPlayerCars (+48) and NFSRaceMode (+596).
    void (*setRaceParameters)(void* user, int32_t numPlayerCars,
                              int32_t nfsRaceMode);

    void (*trace)(void* user, const char* line);
} BSetupHooks;

// ------------------------------------------------------------ tfeSineWave

// 16 bytes, the constructor's three floats and a phase that starts at 0.
// Step adds rate * dt and takes 6.283 (gp-26468) off once it passes it;
// the value is lo + (hi - lo) * (bSin(phase) + 1) / 2.
typedef struct BSineWave {
    float lo, hi, rate, phase;
} BSineWave;

#define BSINE_WRAP 6.283f

void    bsine_init(BSineWave* w, float lo, float hi, float rate);
void    bsine_step(BSineWave* w, float dt);
float   bsine_val(const BSineWave* w);
int32_t bsine_val_int(const BSineWave* w);

// ----------------------------------------------------------------- arrows

// 32 bytes in retail: the screen, the two bitmaps (pointers there, found
// once by the constructor; here their hashes and whether they were
// there), the object they follow (0 hides them), and the pulse,
// tfeSineWave(0, 128, 10): alpha 0 to 128 about 1.6 times a second.
typedef struct BArrows {
    uint32_t  screen;        // +0
    uint32_t  left, right;   // +4, +8
    int       hasLeft, hasRight;
    uint32_t  follow;        // +12
    BSineWave pulse;         // +16
} BArrows;

typedef struct BSetup BSetup;

// 0x0024a690: finds the two bitmaps (type 2), then Set(0).
void barrows_init(BSetup* s, BArrows* r, uint32_t screen, uint32_t left,
                  uint32_t right);
// 0x0024a860: follow `object`, and show or hide the pair to match.
void barrows_set(BSetup* s, BArrows* r, uint32_t object);
// HandleEvent (0x0024a868): SCREEN_TICK is Tick (0x0024a730), anything else
// nothing. Tick steps the pulse by RealTimeElapsed; while it follows
// something, each arrow gets the pulse's alpha and the object's centre Y.
// Then the visibility again (0x0024a800).
void barrows_event(BSetup* s, BArrows* r, BScreenMessage msg);

// --------------------------------------------------- BeACopChallengeSetup

// The 720 bytes, cut to what the code reads. Retail news one on
// SCREEN_ACTIVATE and keeps it at gp-18784; so does this, in BSetup.
typedef struct BBeACopSetup {
    int            live;
    uint32_t       screen;       // +0
    BChallengeData data;         // +4, a copy of Fred's
    uint32_t       current;      // +28, CurrentMenuItem
    BSelSet        sel;          // +32, MenuSelectionSet
    BBlurb         blurb;        // +180, mBlurbyText
    BSlideAnim     slideIn;      // +600, mSlideIn
    BHighlightAnim highlight;    // +620, mHighlightAnimation
    BHighlightAnim change;       // +652, mSelectionChangeAnimation
    BExitAnim      exit;         // +684, mExitScreenAnimation (a pointer)
    int            exitActive;
    BArrows        arrows;       // +688
} BBeACopSetup;

// ------------------------------------------------------- ChallengeScreen

// "Challenge" (0x001b5e30 .. 0x001b6c68), which both Mode Selects' Challenge
// items open: Players, Race Type (Single Race, Knockout, Lap Knockout, Free
// Run), Skill Level and Setup. Retail's is 720 bytes, the demo's 688: the
// data grew to 20 bytes, and the two arrow bitmaps became the arrows class.
#define BSETUP_SCREEN_CHALLENGE      0x2d62cfe2u
#define BSETUP_OBJ_RACE_TYPE_VALUE   0x15dd325eu   // "Single Race" .. "Free Run"

typedef struct BChallengeScreen {
    int            live;
    BChallengeData data;           // +0, a copy of Fred's
    uint32_t       screen;         // +20, ScreenHash
    int32_t        gameTypeIndex;  // +24, into ChallengeGameTypes; -1 none
    uint32_t       current;        // +28, CurrentMenuItem
    BSelSet        sel;            // +32, MenuSelectionSet
    BBlurb         blurb;          // +180, mBlurbyText
    BSlideAnim     slideIn;        // +600, mSlideIn
    BHighlightAnim highlight;      // +620, mHighlightAnimation
    BHighlightAnim change;         // +652, mSelectionChangeAnimation
    BExitAnim      exit;           // +684, mExitScreenAnimation (a pointer)
    int            exitActive;
    BArrows        arrows;         // +688
} BChallengeScreen;

// ------------------------------------------------------ tScrollingMenuList

// A menu longer than its window: every item and value object is an
// element whose Y eases (tCubic1D, 0.5 s) toward where it should be, and
// when the highlight leaves the window every element moves by the same
// amount. The window is MENUITEM_1's Y to MENUITEM_7's, and the two arrows
// that say there is more show only for 8 items or more, so on Be The Cop
// Setup's three nothing moves: each tick puts every element back where it
// was authored.
//
// tMenuAnimElement (0x00249c78), 64 bytes: the node, SavedY (+8), YAnim
// (+12) and the chunk (+60, its name here). The list mallocs one per
// object; the port keeps them in the list, as many as Audio Options adds
// (26, audiooptions.c).
#define BSCROLL_MAX_ELEMENTS 32

typedef struct BMenuAnimElement {
    uint32_t object;   // +60, Obj
    float    savedY;   // +8
    BSpline  yAnim;    // +12
} BMenuAnimElement;

// 56 bytes in retail.
typedef struct BScrollList {
    uint32_t         screen;            // +0
    BMenuAnimElement elements[BSCROLL_MAX_ELEMENTS];   // +4, Elements
    int              numElements;
    float            top, bottom;       // +12, +16, the visible area
    int32_t          currentMask;       // +20, -1 until the first highlight
    BSineWave        arrowAnimator;     // +24, (0, 128, 10)
    uint32_t         upArrow;           // +40
    uint32_t         downArrow;         // +44
    uint32_t         clipPoly;          // +48
    int32_t          numMenuItemsToScroll;   // +52
} BScrollList;

// tScrollingMenuList for the screens that are not RaceSetupBaseClass's
// (Audio Options): the constructor (0x00249de0, `first` and `last` the
// items whose Ys bound the window), AddObjects (0x00249ff8), the
// destructor (0x00249ed0), HandleEvent (0x0024a480) and
// GetCurrentMenuMask (0x0024a368). The caller sets numMenuItemsToScroll,
// as retail's constructors do after AddObjects.
void     bscroll_init(BSetup* s, BScrollList* l, uint32_t screen,
                      uint32_t first, uint32_t last, uint32_t up,
                      uint32_t down, uint32_t clip);
void     bscroll_add_objects(BSetup* s, BScrollList* l,
                             const uint32_t* objects, int n);
void     bscroll_release(BSetup* s, BScrollList* l);
void     bscroll_event(BSetup* s, BScrollList* l, BScreenMessage msg,
                       const BScreenCallbackData* data);
uint32_t bscroll_current_mask(const BScrollList* l);

// ------------------------------------------------------ RaceSetupBaseClass

// ChangeableItem, 44 bytes in retail (40 in the demo; +40 is new): one row
// of a setup screen. Change and Refresh are pointers to member functions
// there, called on the screen with (direction, &value) and (value, text).
typedef struct BRaceSetup BRaceSetup;
typedef int (*BSetupChangeFn)(BSetup* s, BRaceSetup* r, int32_t dir,
                              int32_t* value);
typedef void (*BSetupRefreshFn)(BSetup* s, BRaceSetup* r, int32_t value,
                                uint32_t text);

typedef struct BChangeable {
    uint32_t        menuItem;     // +8, MENUITEM_<i+1>, by BuildMenu
    uint32_t        changeText;   // +12, the value's text object
    int32_t         languageID;   // +16, the item's label
    int32_t*        value;        // +20
    BSetupChangeFn  change;       // +24, answers whether it changed
    BSetupRefreshFn refresh;      // +32
    int32_t         blurbID;      // +40, the line under the menu
} BChangeable;

// Retail's BuildMenu fills eight rows at most: its three tables are eight.
#define BRACESETUP_MAX_ROWS 8

// The screen hash -- all five setups are the one Flailer screen, under five
// names -- and the objects every setup screen names.
#define BSETUP_SCREEN_BE_THE_COP_SETUP 0xd1eadbcau
#define BSETUP_SCREEN_RACE_SETUP       0xd1eadbcau
#define BSETUP_OBJ_UP_ARROW            0xedf2e4eeu
#define BSETUP_OBJ_DOWN_ARROW          0x20d73d01u
#define BSETUP_OBJ_CLIP_POLY           0xc67cfb4au

// The id each class's Callback passes BaseCallback (0x001b7b20), which
// news that class on ACTIVATE.
#define BSETUP_RACE_SINGLE        100   // SingleRaceSetup, 792 bytes
#define BSETUP_RACE_FREE_RUN      101   // FreeRunSetup, 776
#define BSETUP_RACE_LAP_KNOCKOUT  102   // LapKnockoutSetup, 788
#define BSETUP_RACE_KNOCKOUT      103   // TrackKnockoutSetup, 792
#define BSETUP_RACE_BE_THE_COP    104   // BeTheCopSetup, 784

// RaceSetupBaseClass (0x001b8390), 764 bytes in retail, and the five on it,
// each with its Fred block copied in at +764. Only one is alive at a time
// -- the class's static pInstance (gp-18780) -- so the port keeps one, and
// `kind` says which, for the destructor UNACTIVATE calls through the
// vtable.
typedef struct BRaceSetup {
    int            live;
    uint32_t       screen;         // +0
    BChangeable    rows[BRACESETUP_MAX_ROWS];   // +4, Changeables
    int            numRows;
    uint32_t       current;        // +12, CurrentMenuItemHash
    BSelSet        sel;            // +16, mSelectionSet
    BSlideAnim     slideIn;        // +164, mEnterScreenAnimation
    BHighlightAnim highlight;      // +184, mHighlightAnimation
    BHighlightAnim change;         // +216, mSelectionChangeAnimation
    BExitAnim      exit;           // +248, mExitScreenAnimation (a pointer)
    int            exitActive;
    BScrollList    scroller;       // +252, mMenuScroller
    BArrows        arrows;         // +308
    BBlurb         blurb;          // +340
    int            kind;           // BSETUP_RACE_*
    union {
        BBeTheCopData btc;         // +764, BeTheCopSetup's Data
        int32_t       data[7];     // +764, the other four's Fred block
    };
} BRaceSetup;

struct BSetup {
    BGameFlow*       gf;
    BSetupHooks      hooks;
    // The port's: 1 while the host of a Local Wireless race sets it up
    // (TASKS 63, lobby_on_setup), the other players on consoles of their
    // own. Players is then always "2", which reads Local Wireless, its
    // line says up to eight consoles, and a select goes back to the lobby
    // (lobby.h) where retail's goes to the two-pad car select. bsetup_init
    // leaves it 0, retail's, which is what the checks run.
    int              wirelessPlayers;
    BBeACopSetup     beACop;
    BChallengeScreen challenge;
    BRaceSetup       race;
};

// Installs `s` as the module's instance and clears it. `hooks` may be NULL.
// The kit is gf->anim, and the clock gf's.
void bsetup_init(BSetup* s, BGameFlow* gf, const BSetupHooks* hooks);
// That instance, or NULL before bsetup_init: the arrows' hooks, for the
// other screens that have a pair (nameentry.c).
BSetup* bsetup_instance(void);

// BeACopChallengeSetup::Callback (0x001b6f18), for kScreens[].
void bsetup_beacop_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);

// ChallengeScreenCallback (0x001b6bd0), for kScreens[].
void bsetup_challenge_callback(BGameFlow* gf, BScreenMessage msg,
                               BScreenCallbackData* data);

// BeTheCopSetup::Callback (0x001b93d8), BaseCallback (0x001b7b20) with 104:
// "Be The Cop Setup", for kScreens[].
void bsetup_btc_callback(BGameFlow* gf, BScreenMessage msg,
                         BScreenCallbackData* data);

// The other four Callbacks, BaseCallback with 100 .. 103: "Single Race
// Setup" (0x001b8ae8), "Free Run Setup" (0x001b8c98), "Lap Knockout Setup"
// (0x001b8f30) and "Knockout Setup" (0x001b9210), for kScreens[].
void bsetup_single_race_callback(BGameFlow* gf, BScreenMessage msg,
                                 BScreenCallbackData* data);
void bsetup_free_run_callback(BGameFlow* gf, BScreenMessage msg,
                              BScreenCallbackData* data);
void bsetup_lap_knockout_callback(BGameFlow* gf, BScreenMessage msg,
                                  BScreenCallbackData* data);
void bsetup_knockout_callback(BGameFlow* gf, BScreenMessage msg,
                              BScreenCallbackData* data);
