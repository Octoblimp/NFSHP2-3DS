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
// Addresses are retail's, SLES_507.31. Written up in
// docs/formats/frontend-setup.md. Like bscreens.c this is free of <3ds.h>:
// every Flailer call goes out through BSetupHooks under the name of the
// function retail calls, and the animation kit is banim.c, so
// tools/setup_check.py can run retail's code in mipsemu next to this.

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
#define FRED_MAIN_MENU_POLICE   32       // MainMenuOpts.mPolice
#define FRED_GAME_TYPE          0x1072c  // GameType
#define FRED_NUM_PLAYER_CARS    0x10734  // NumPlayerCars

// GameTypes, the .mdebug enum. The Mode Selects write the others.
#define FRED_CHALLENGE_GAME_BE_A_COP  7

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
    // GrayMenuItem (0x0016d198), whose arguments retail passes as (item,
    // mode, screen). BScrGrayMode's modes: 1 enables, 0 grays, 2 hides.
    void (*grayMenuItem)(void* user, uint32_t screen, uint32_t item,
                         int mode);

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

struct BSetup {
    BGameFlow*   gf;
    BSetupHooks  hooks;
    BBeACopSetup beACop;
};

// Installs `s` as the module's instance and clears it. `hooks` may be NULL.
// The kit is gf->anim, and the clock gf's.
void bsetup_init(BSetup* s, BGameFlow* gf, const BSetupHooks* hooks);

// BeACopChallengeSetup::Callback (0x001b6f18), for kScreens[].
void bsetup_beacop_callback(BGameFlow* gf, BScreenMessage msg,
                            BScreenCallbackData* data);
