#pragma once
#include <stdint.h>

#include "banim.h"
#include "bmenu.h"

// tPopupMenu, and the three FlailerScreenList functions that own the two
// of them: a box over the current screen with a message, up to three
// buttons, a title, and a bloom on the highlighted button. The memory card
// is its only caller on the boot path -- every "Checking for Memory Card
// (PS2)..." and every Yes/No the card asks is one (memcard.h).
//
// Retail's, SLES_507.31, and every address here is retail's. The demo has
// the class too, but its FlailerMenuItem recolours differently.
//
// The popup does not replace the screen it covers. FlailerScreenList keeps
// two of them beside pCurrent: its Tick ticks both whether or not they are
// up, and its JoyHandler hands a pad event to a popup that is up before
// the screen hears of it. What the popup has to say goes to the callback of
// the screen that summoned it, as BMSG_POPUP_*.
//
// Written up in docs/formats/boot-flow.md, "The memory card". Like
// gameflow.c this is free of <3ds.h>: the Flailer side is BAnimHooks.

typedef struct BGameFlow BGameFlow;
struct BScreenConfig;

#define BPOPUP_COUNT 2

// The popup screen the memory card uses, in FRONTB.BUN, and its objects.
#define BPOPUP_SCREEN_MEMCARD 0x0ce3f7ceu
#define BPOPUP_OBJ_BUTTON1    0xe0105663u   // "Yes"
#define BPOPUP_OBJ_BUTTON2    0xe0105664u   // "No"
#define BPOPUP_OBJ_BUTTON3    0xe0105665u   // on no screen on this disc
#define BPOPUP_OBJ_TITLE      0x85eda094u
#define BPOPUP_OBJ_BLOOM      0xab671c9au   // ANIMATING_MENUITEM
// The message's text objects: nine of them on the memory card's screen,
// one line each.
#define BPOPUP_GROUP_MESSAGE  0x5d6dd123u

// PopupConfig's Flags.
#define BPOPUP_HORIZONTAL   0x01   // left/right move the highlight
#define BPOPUP_CANCELABLE   0x02   // BACK dismisses with CancelParam
#define BPOPUP_BUTTONS_BELOW 0x04  // the buttons go under the message
#define BPOPUP_NO_SELECT    0x08   // SELECT and START do not dismiss
#define BPOPUP_KEEP_VISIBLE 0x10   // Dismiss leaves the screen up

// PopupConfig, 72 bytes, copied whole into the popup by Summon. The
// memory card's two builders leave CancelParam, DismissParam and PopupID
// unwritten -- stack garbage in the original, which no path on the boot
// reads -- and the port zeroes them.
typedef struct {
    int32_t                     numButtons;      // +0
    uint32_t                    flags;           // +4
    // +8, a FlailerScreen*: the screen whose callback hears the popup.
    const struct BScreenConfig* parent;
    uint32_t                    screen;          // +12, PopupScreenHash
    const char*                 message;         // +16
    int32_t                     button[3];       // +20: language IDs
    int32_t                     buttonParam[3];  // +32
    int32_t                     cancelParam;     // +44
    int32_t                     dismissParam;    // +48
    int32_t                     startButton;     // +52
    int32_t                     joyPort;         // +56, -1 takes any pad
    int32_t                     timeout;         // +60, read by nothing
    int32_t                     popupID;         // +64, read by nothing
    int32_t                     title;           // +68: a language ID
} BPopupConfig;

// FlailerMenuItem, retail's, as far as a popup's three use it: no menu, so
// no neighbours. State is BMENU_ENABLED | BMENU_HIGHLIGHTED.
typedef struct {
    uint32_t state;        // +8
    uint32_t hash;         // +12
    int32_t  id;           // +16
    uint32_t savedColor;   // +28
    int32_t  joyPort;      // +32
    uint32_t screen;       // +36
} BPopupItem;

// tPopupMenu. The +offsets are the original's.
typedef struct {
    int32_t        active;       // +0
    BPopupConfig   cfg;          // +4
    BPopupItem     items[3];     // +76, +80, +84: BUTTON1..3
    // +88: the parent's callback, taken at Summon. `parentName` is the
    // port's, for the transcript.
    void (*callback)(BGameFlow* gf, BScreenMessage msg,
                     BScreenCallbackData* data);
    const char*    parentName;
    uint32_t       current;      // +92: the highlighted button
    float          phase;        // +104
    BHighlightAnim highlight;    // +108
    // The port's trace, not the popup's state: Tick animates the bloom on
    // every frame, and the transcript says so once a Summon.
    int            tracedAnimate;
} BPopup;

// FlailerScreenList's constructor, for both popups (0x0016b478 each).
void bpopup_init(BGameFlow* gf);

// SummonPopup (0x0016cd68): into the first popup that is not up. Returns
// its index, or -1 with both up.
int bpopup_summon(BGameFlow* gf, const BPopupConfig* cfg);

// DismissPopup (0x0016cdc0): popup `i`, if it is up, with its config's
// JoyPort and DismissParam.
void bpopup_dismiss(BGameFlow* gf, int i);

// IsAnyPopupActive (0x0016ca08).
int bpopup_any_active(const BGameFlow* gf);

// FlailerScreenList::Tick's share (0x0016cca8): tPopupMenu::Tick on both
// popups, up or not. bgf_frame calls it after the screen's own tick.
void bpopup_tick(BGameFlow* gf);

// FlailerScreenList::JoyHandler's share (0x0016cab0): the event goes to
// every popup that is up and listening to `port`. Returns 1 if one took
// it, in which case the screen must not hear of it -- a popup takes every
// event, pressed or not, whatever it does with it.
int bpopup_joy(BGameFlow* gf, int port, int joyEvent, int pressed);

// RenderTextIntoGroup (0x00144ba0): `str` word-wrapped into the text
// objects of `group` on `screen`, one line each in file order, the rest
// hidden. Breaks at a space, a tab or '@', and '@' is a line break. Returns
// (int)(TopLeftY + scaled height) of the first line left unused -- or of the
// last line, with every one used -- or 0 if the text ran out of lines.
int bpopup_render_text_into_group(BGameFlow* gf, uint32_t screen,
                                  uint32_t group, const char* str);
