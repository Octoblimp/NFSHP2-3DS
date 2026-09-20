#pragma once
#include <stdbool.h>
#include <stdint.h>

#include "bui.h"

// Flailer menus -- the behaviour half of the UI, which is not on disc.
//
// bui.c gives you a screen's objects. This turns a screen into something
// navigable the way the game does: find the text objects called MENUITEM_0
// through MENUITEM_15, track which one is current, recolour them as they
// highlight and gray out, and route pad events through the same three
// levels the engine does (screen, menu, item).
//
// Everything here is decompiled rather than invented; docs/formats/
// flailer-menu.md names an address for each rule. Like bui.c this is free
// of <3ds.h> so tools/bmenu_check.py can drive it on the host.
//
// What is deliberately NOT here: per-screen decoration. On the real disc a
// screen's own C++ callback does that -- NEW_MAIN_MENU pulses the
// highlighted label through tHighlightAnimation -- and the generic
// AlignBar() the engine ships is never called by anything. bmenu_align_bar()
// is offered for ports that want it, and does nothing unless you hand it a
// way to measure objects.

#define BMENU_MAX_ITEMS 16

// FlailerMenuItem::State. The constructor sets ENABLED, so items start
// selectable and unhighlighted.
#define BMENU_ENABLED      0x1
#define BMENU_HIGHLIGHTED  0x2

// ScreenMessage, verbatim from the .mdebug type info. Only the values this
// module can send are named; the rest belong to the screen list.
typedef enum {
    BMSG_NONE = 0,
    BMSG_MENUITEM_SELECT = 1,
    BMSG_MENUITEM_ACTIVATE = 2,
    BMSG_MENUITEM_UNACTIVATE = 3,
    BMSG_MENUITEM_HIGHLIGHT = 4,
    BMSG_MENUITEM_UNHIGHLIGHT = 5,
    BMSG_MENUITEM_PAD_LEFT = 6,
    BMSG_MENUITEM_PAD_RIGHT = 7,
    BMSG_MENUITEM_PAD_UP = 8,
    BMSG_MENUITEM_PAD_DOWN = 9,
    BMSG_MENUITEM_SQUARE = 10,
    BMSG_SCREEN_ACTIVATE = 11,
    BMSG_SCREEN_UNACTIVATE = 12,
    BMSG_SCREEN_START_BUTTON = 13,
    BMSG_SCREEN_SELECT_BUTTON = 14,
    BMSG_SCREEN_L1 = 15,
    BMSG_SCREEN_R1 = 16,
    BMSG_SCREEN_BACK_BUTTON = 17,
    BMSG_SCREEN_TICK = 18,
    BMSG_SCREEN_RENDER = 19,
} BScreenMessage;

// JoyEvent, same source. These are the sixteen in MenuJoyEvents
// (0x002f3030) plus the two analog-vertical ones the menu also accepts.
typedef enum {
    BJOY_NULL = 0,
    BJOY_SCROLL_UP = 3,
    BJOY_SCROLL_DOWN = 4,
    BJOY_SCROLL_LEFT = 5,
    BJOY_SCROLL_RIGHT = 6,
    BJOY_START = 7,
    BJOY_SELECT = 8,
    BJOY_MENU_SELECT = 9,
    BJOY_MENU_CANCEL = 10,
    BJOY_MENU_BACK = 11,
    BJOY_MENU_HELP = 12,
    BJOY_MENU_L1 = 13,
    BJOY_MENU_L2 = 14,
    BJOY_MENU_R1 = 15,
    BJOY_MENU_R2 = 16,
    BJOY_MENU_SQUARE = 17,
    BJOY_ANALOG_LEFT = 18,
    BJOY_ANALOG_RIGHT = 19,
    BJOY_ANALOG_UP = 20,
    BJOY_ANALOG_DOWN = 21,
} BJoyEvent;

// FrontendSoundEvent, the handful the menu system raises itself.
typedef enum {
    BSND_NONE = 0,
    BSND_MENU_LEFT = 1,
    BSND_MENU_RIGHT = 2,
    BSND_MENU_UP = 3,
    BSND_MENU_DOWN = 4,
    BSND_MENU_SELECT = 5,
    BSND_MENU_CANCEL = 6,
    BSND_MENU_START = 7,
} BFrontendSound;

// ScreenCallbackData, 16 bytes in the original and the same four fields
// here. `param` and `noise` are the callback's reply channel: writing
// `param` consumes the event, writing `noise` picks the sound.
typedef struct {
    uint32_t itemHash;
    int32_t  port;
    int32_t  param;
    int32_t  noise;
} BScreenCallbackData;

typedef struct BMenu BMenu;

// The screen's behaviour, the `Callback` every Flailer* class carries.
typedef void (*BMenuCallback)(BMenu* m, BScreenMessage msg,
                              BScreenCallbackData* data, void* user);

// Optional: hands bmenu_align_bar() the rendered size of an object. Return
// false if the object cannot be measured. uirender.c can supply this; the
// host test does not have to.
typedef bool (*BMenuMeasureFn)(void* user, uint32_t objectIndex,
                               float* w, float* h);

// Optional: MakeFrontendSound. Called with data.noise after each callback
// that the engine follows with one, so a port can hook audio later.
typedef void (*BMenuSoundFn)(int soundEvent, void* user);

typedef struct {
    uint32_t itemHash;     // bhash("MENUITEM_n")
    int32_t  itemID;       // n, not the position in the list
    uint32_t object;       // absolute BUI object index of the text chunk
    uint32_t state;        // BMENU_*
    uint32_t savedColor;   // the authored Color, for un-highlighting
} BMenuItem;

struct BMenu {
    BUI*       ui;
    BUIScreen* screen;

    BMenuItem items[BMENU_MAX_ITEMS];
    int       numItems;
    int       current;         // index into items[], or -1 when empty

    int32_t   highlightBar;    // object index of HIGHLIGHT_BAR, or -1

    BMenuCallback  callback;
    void*          user;
    BMenuMeasureFn measure;
    void*          measureUser;
    BMenuSoundFn   sound;

    // The engine's globals, per-menu here so a viewer can experiment. The
    // defaults are the values the PS2 image actually ships with.
    int32_t  filterPort;       // -1: any port
    bool     looping;          // LoopingMenuScrollMode, 1 on disc
    bool     ignoreJoystick;   // IgnoreJoystick, 0 on disc
    uint32_t highlightColor;   // 0x004080 -- HighlightR/G/B = 128/64/0
    uint32_t grayedColor;      // 0x181818 -- GrayedR/G/B = 24
};

// Discovers MENUITEM_0..15 and the HIGHLIGHT_BAR bitmap on `screen`, and
// fills in the defaults above. `callback` may be NULL. Returns false only
// if the arguments are unusable; a screen with no menu items is a valid
// menu with zero items, exactly as in the original.
bool bmenu_open(BMenu* m, BUI* ui, BUIScreen* screen,
                BMenuCallback callback, void* user);

// FlailerScreen::Activate's tail: sends MENUITEM_ACTIVATE to every item,
// selects `startItem` (an index into the list, clamped to the head), then
// highlights the first enabled item at or after it.
void bmenu_activate(BMenu* m, int startItem);

// Sends MENUITEM_UNACTIVATE to every item and drops the highlight.
void bmenu_unactivate(BMenu* m);

// One pad event through all three levels. `pressed` false is ignored, as
// every JoyHandler in the chain does. Returns true if anything acted on it.
bool bmenu_joy(BMenu* m, int port, BJoyEvent ev, bool pressed);

// GrayMenuItem: clears or sets BMENU_ENABLED on the item with this ItemID
// (the n in MENUITEM_n) and recolours it. Graying the current item does not
// move the selection -- navigation simply skips it next time.
bool bmenu_set_item_enabled(BMenu* m, int itemID, bool enabled);

// The current item, or NULL.
const BMenuItem* bmenu_current(const BMenu* m);

// Item by ItemID, or NULL.
const BMenuItem* bmenu_find(const BMenu* m, int itemID);

// AlignBar (0x00164e70), which the original never calls. Needs `measure`;
// without it this returns false and changes nothing.
bool bmenu_align_bar(BMenu* m);
