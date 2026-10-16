// helpmenu -- retail's tHelpMenu: the HELP panel a frontend screen's help
// key summons, and FlailerScreenList's part in it.
//
// The panel is GLOBALB's help screen (0x087cd45c): a backdrop, the HELP
// title and eight rows, each a column of buttons (x 69) and one of text
// (x 190). Each row is a translated line such as "Cross Enter game mode":
// SplitHelp puts its leading help characters in the buttons column and
// the rest in the text. A screen's lines are its FlailerScreenConfig's
// HelpMenuItems (helpmenu_screen_lines), unless the screen up gave the
// list its own (SetHelpOverride): the setups, car select and the event
// tree change theirs as they go.
//
// The panel slides between x 650, off the right, and x 53 along a
// tCubic1D of half a second, and fades its backdrop as it goes. The screen
// is shown once it passes x 640 coming in, and hidden once it passes it
// going out. While it is anywhere on its way in or in place, the list
// gives no other event to the popups, the screen or its menu: the help
// key alone does anything, and it sends the panel out again.
//
//   tHelpMenu::tHelpMenu                         0x001e3b88
//   tHelpMenu::Summon(FlailerScreenNode *)       0x001e3c50
//   IsHelpSpace(int)                             0x001e3c68
//   tHelpMenu::SplitHelp(int, char *, char *, int) 0x001e3c98
//   tHelpMenu::Reset                             0x001e3db8  (empty)
//   0x001e3dd0, the help turned off               (gp-17344 = 0)
//   tHelpMenu::Summon(int *)                     0x001e3dd8
//   tHelpMenu::Dismiss                           0x001e3fa0
//   tHelpMenu::Tick                              0x001e4028
//   tHelpMenu::IsActive                          0x001e4170
//   SetHelpOverride(int *)                       0x0016d448
//   FlailerScreenList::JoyHandler's help         0x0016cab0, 0x0016ca40
//
// On the 3DS the help key is Y (the user, 2026-10-16), retail's Circle.
// docs/formats/help-menu.md has the decode.

#ifndef HELPMENU_H
#define HELPMENU_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"

// The help screen in GLOBALB, and its objects.
#define HELPMENU_SCREEN        0x087cd45cu
#define HELPMENU_OBJ_BACKDROP  0x7830fd99u   // the fade's one object
#define HELPMENU_OBJ_ANCHOR    0x49b30391u   // the group's place, x 53
#define HELPMENU_GROUP         0x3c86db48u   // everything that slides
#define HELPMENU_OBJ_BUTTONS   0x8c92aa9au   // row i's buttons, + i
#define HELPMENU_OBJ_TEXT      0xeacf0330u   // row i's text, + i
#define HELPMENU_ROWS          8

// The slide's two ends (gp-0x6e44 and 53), and where the panel counts as
// on the screen.
#define HELPMENU_X_OUT         650.0f
#define HELPMENU_X_IN          53.0f
#define HELPMENU_X_SHOWN       640.0f

// SplitHelp's buffers in Summon.
#define HELPMENU_LINE          128

typedef struct HelpMenuHooks {
    void *user;
    // GetTranslatedString (0x0021e560). NULL, or a NULL answer, reads "".
    const char *(*translate)(void *user, int32_t id);
    // SoundEnabled (gp-23056).
    int (*soundEnabled)(void *user);
    // The common region's "MenuSelect" at pitch 1, MakeFrontendSound's
    // event 5.
    void (*playSelect)(void *user);
    // SetFlailerScreenVisibility (0x0014cbf8), retail's enum: 0 visible,
    // 1 invisible.
    void (*setScreenVisibility)(void *user, uint32_t screen,
                                int32_t visibility);
    // The animation kit the backdrop's fade goes through. NULL, or a NULL
    // answer, leaves the alpha alone.
    BAnim *(*anim)(void *user);
} HelpMenuHooks;

typedef struct HelpMenu {
    uint32_t       screen;     //  0  HELPMENU_SCREEN
    int32_t        shown;      // 16  the slide was short of 640 last tick
    BSpline        slide;      // 20  the tCubic1D, bMalloc'd in retail
    BAnimAlpha     fade;       // 28  the feAlphaAnimation's one element
    int32_t        haveFade;   //     retail's pointer at 28 is not NULL
    int32_t        summons;    // 32  Summons with the help on
    // FlailerScreenList's: +400, SetHelpOverride's lines, and gp-17344,
    // whether a summon does anything.
    const int32_t *override;
    int32_t        enabled;
    HelpMenuHooks  hooks;
} HelpMenu;

// tHelpMenu::tHelpMenu, and the list's part: the slide out at 650, half a
// second, no summons, the help on and no override. `anim` is the kit the
// backdrop's authored alpha is read through; NULL has no fade.
void helpmenu_construct(HelpMenu *h, const HelpMenuHooks *hooks,
                        BAnim *anim);

// Summon(int *): with the help on, one more summons, and with lines, the
// select sound, the slide in to 53 and each row printed and shown up to
// the first 0, the rest hidden. Dismiss: the slide out to 650, and the
// sound if anything was ever summoned.
void helpmenu_summon(HelpMenu *h, const int32_t *lines);
void helpmenu_dismiss(HelpMenu *h);

// FUN_0016ca40, the help key on a press: Summon(lines) when the panel is
// not active, else Dismiss.
void helpmenu_toggle(HelpMenu *h, const int32_t *lines);

// IsActive: the slide's target is short of 640, so the panel is coming in
// or there.
int helpmenu_is_active(const HelpMenu *h);

// Tick, after the screen's: the screen shown or hidden as the slide
// crosses 640 (once anything was summoned), the group moved to the slide's
// x, the backdrop faded from 320 on, and the slide stepped by `dt`.
void helpmenu_tick(HelpMenu *h, float dt);

// SetHelpOverride: the lines the help key shows instead of the screen's,
// NULL for the screen's own, and the help on. 0x001e3dd0: the help off,
// until the next override; a summon then does nothing.
void helpmenu_set_override(HelpMenu *h, const int32_t *lines);
void helpmenu_disable(HelpMenu *h);

// Reset (0x001e3db8), which UnlaunchFrontendMenus calls: nothing.
void helpmenu_reset(HelpMenu *h);

// The lines the help key shows: the override, or else `screenLines`.
const int32_t *helpmenu_lines(const HelpMenu *h,
                              const int32_t *screenLines);

// IsHelpCharacter (0x00141db0): 0x80..0x9d but 0x92, the apostrophe.
int helpmenu_is_help_character(unsigned char c);
// IsHelpSpace (0x001e3c68): space, tab or the terminator.
int helpmenu_is_help_space(int c);

// SplitHelp on the translated `line`, into two buffers of `n` bytes: its
// leading run of help characters, help spaces and '+' into `buttons`
// (spaces dropped, '+' as " + "), the rest into `text`, at most `n` - 2
// characters of it. Retail would read past the end of a line of nothing
// but buttons, and bounds no buttons; this stops at both.
void helpmenu_split(const char *line, char *buttons, char *text, size_t n);

// The FlailerScreenConfig HelpMenuItems of the screen named `name`, as
// the port registers it, 0-terminated; NULL for a screen with none. The
// 3DS's own: Joystick PreConfig has the one row the port shows, and the
// port's Controller page (Joystick Config Port1) none, as its keys are
// on the bottom screen.
const int32_t *helpmenu_screen_lines(const char *name);

#endif
