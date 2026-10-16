#pragma once
#include <stddef.h>
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"

// Options' Controller: retail's JoystickPreConfig ("Joystick PreConfig",
// 0x002400c0 ..) and JoystickConfigScreen ("Joystick Config Port1",
// 0x0023e578 ..), both OptionsScreenBase pages (bscreens.c's
// bscr_optbase_*).
//
// Retail's PreConfig has each player's Configuration, Calibration and
// Vibration/Feedback. The port keeps Player 1's Configuration: a 3DS has
// no second player (the user's word, 2026-10-13), its sticks need no
// calibrating, and it does not vibrate.
//
// Retail's Configuration page shows the pad's configuration, one of a few
// fixed layouts that Left and Right cycle through, each action's button by
// GetButtonChar (0x0023ee48). The port's is where each action's key is
// picked (the user's word, 2026-10-16): the racer's table or the cop's car's
// (joyhid.h's JoyHidBindings), picked on the top line with Left and Right.
// Up, Down, Left and Right move between the actions, A waits for a key and
// the next one pressed is the action's (joyhid_bind: the action that had
// the key takes the moved action's old key), START stops the wait, and X
// puts the table back to the defaults. Steering (the Circle Pad and the
// D-pad's Left and Right) and Pause (START) are fixed, as are the C-Stick's
// throttle and brake. The racer's Zone rows show the shift keys they use,
// alone with an automatic box and with the camera's in the Manual half;
// the cop's show the calls, Roadblock and Helicopter, in their place.
//
// Retail's B saves with autosave on (SaveConfiguration, then the Autosave
// screen); the port's asks when the keys changed (the save prompt, the
// user's word of 2026-10-13): Yes saves on the Autosave screen, No puts
// the keys back, B stays. The keys go in controls.bin beside settings.db
// (main.c). docs/formats/joystick.md.

// FlailerScreenConfig's hashes.
#define JOYPRECONFIG_SCREEN 0x8bd5060bu
#define JOYCONFIG_SCREEN    0xb6657464u

// What the pages need of main.c.
typedef struct {
    void*  user;
    void (*log)(void* user, const char* line);   // the port's log
    void (*noise)(int noise, void* user);         // a BSND_*, fesound_play
    // The text of LanguageID `id` in the language up, as langtab_copy.
    size_t (*text)(void* user, int32_t id, char* out, size_t cap);
} JoyConfigHooks;

void joyconfig_init(const JoyConfigHooks* hooks);

// JoystickPreConfig's and JoystickConfigScreen's Callbacks, for kScreens[].
void joypreconfig_callback(BGameFlow* gf, BScreenMessage msg,
                           BScreenCallbackData* data);
void joyconfig_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data);

// The Configuration page's own keys, before the flow hears them: `down`,
// the keys pressed this frame as JOYHID_* bits (hidKeysDown's, not the
// Circle Pad's menu directions). Answers the keys it took, which the flow
// must not have: X for the defaults, or every key while it waits for one.
// 0 with the page not up, leaving or asking.
uint32_t joyconfig_input(uint32_t down);

// HELPGLYPH_LAYOUT_KEYS while the Configuration page is up with no popup
// over it, so its glyphs name the keys themselves; -1 otherwise. For
// uirender's gUiHelpLayoutFn.
int32_t joyconfig_help_layout(void);

// The bottom screen's body and hint while the Configuration page is up
// with no popup over it, in HELPGLYPH_LAYOUT_KEYS's help characters; NULL
// otherwise.
const char* joyconfig_bottom_body(void);
const char* joyconfig_bottom_hint(void);
