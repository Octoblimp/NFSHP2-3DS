#pragma once
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"

// Options' Display: retail's tDisplayOptionsScreen (0x001f33b8 ..
// 0x001f3f1c, "Display Options" in kScreens) and the Customize P1 HUD page
// it opens (tCustomizeHUDScreen, 0x001f3f20 .. 0x001f49c4). Both are
// OptionsScreenBase pages (bscreens.c's bscr_optbase_*).
//
// Display Options sets Fred.DisplayOptionsData: the track map (3D
// Rotation, 3D Standard, 2D Rotation, 2D Standard, Fixed, Off), the rear
// view mirror, mph or km/h, the leaderboard (Off or On), the jump cams and
// the Zone cams, each with Left and Right; then Customize P1 HUD. Retail's
// Customize P2 HUD and Calibrate display offset rows are hidden: no second
// player on a 3DS (the user's word, 2026-10-13), and the offset is a TV's.
//
// Customize P1 HUD sets Fred.FrontendPlayers[0]'s cPlayerSettings: the
// lookback (Lookback or Bird's Eye), the acceleration camera, the gauges,
// the position, the lap info, the split time (Race Leader, Lap Record,
// Best Lap, Last Lap, Off) and the score. B goes back to Display Options.
//
// Retail's B on Display Options writes the page's copy into Fred and, with
// autosave on and anything changed since Options opened the page (the
// calibration, the display settings and both players' settings, as
// tDisplayOptionsChangeManager::Different compares them), saves on the
// Autosave screen. The port asks instead, with autosave on or off (the save
// prompt, the user's word of 2026-10-13): Yes saves there, No puts all four
// back as they were, B stays. docs/formats/display-options.md.

// FlailerScreenConfig's hashes. Customize P2 HUD is the same screen.
#define DISPLAYOPTS_SCREEN 0x8bc68340u
#define CUSTOMHUD_SCREEN   0x28891a22u

// What the pages need of main.c.
typedef struct {
    void*  user;
    void (*log)(void* user, const char* line);   // the port's log
} DisplayOptionsHooks;

void displayopts_init(const DisplayOptionsHooks* hooks);

// tDisplayOptionsChangeManager::Start, which Options calls on picking
// Display: Fred's calibration, display settings and both players' settings
// as they are, for B to compare against.
void displayopts_start(void);

// tDisplayOptionsScreen::Callback (0x001f3ec0), for kScreens[].
void displayopts_callback(BGameFlow* gf, BScreenMessage msg,
                          BScreenCallbackData* data);
// tCustomizeHUDScreen::CallbackP1 (0x001f4960), for kScreens[].
void customhud_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data);
