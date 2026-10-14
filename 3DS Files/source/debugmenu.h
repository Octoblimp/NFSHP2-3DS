#pragma once
#include <stddef.h>
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"

// The port's own debug menu (TASKS 53, 2026-10-13). Retail has none in the
// frontend: its "Debug Menu" (INGAMEB d4742cd7, PauseDebugMenu) is a pause
// screen of in-race toggles that the disc never reaches. This one is a
// fourth item on the main menu, "Debug Menu", hidden until the player
// presses L + R + D-Pad Up together there, or "DebugMenu 1" is in the
// config file (configitems.h). It leads to two lists in Be The Cop Setup's
// look. Debug Menu: the NFS points, the save set to 100%, everything
// unlocked or locked, and Start Debug Race, which leads to Debug Race: any
// race on any track with any car. Leaving with the save changed asks
// whether to save it. docs/formats/debug-menu.md.
//
// Two halves. debugmenu_patch.c rebuilds FRONTB's Flailer chunk at boot,
// with the item and the two screens added, and is free of <3ds.h> so the
// host can check it. debugmenu.c is the screens' callbacks.

// bStringHash of the names the port gives what it adds.
#define DEBUGMENU_SCREEN      0xd98ab71eu   // "PORT_DEBUG_MENU"
#define DEBUGMENU_RACE_SCREEN 0xd98d6284u   // "PORT_DEBUG_RACE"
#define DEBUGMENU_ITEM_HIDDEN 0xd988c438u   // "PORT_DEBUG_ITEM"
#define DEBUGMENU_MASK_HIDDEN 0xd98aa6b5u   // "PORT_DEBUG_MASK"
#define DEBUGMENU_FILL        0xd986f130u   // "PORT_DEBUG_FILL"
// The screen both are copied from: Be The Cop Setup.
#define DEBUGMENU_SOURCE      0xd1eadbcau
// Debug Menu's rows; Debug Race has all seven and scrolls.
#define DEBUGMENU_ROWS        5
// The second screen's ChangeToScreen name (the first's is gameflow.h's
// BGF_DEBUG_MENU_NAME).
#define DEBUGMENU_RACE_NAME   "Port Debug Race"

// FRONTB's Flailer chunk rebuilt: every chunk of it in order, with three
// objects added to NEW_MAIN_MENU (the item, its mask and a filler, all
// invisible) and the two debug screens after the last screen. `data` is the
// whole bundle; the answer is a malloc'd chunk stream holding the one
// Flailer container, for bui_open, or NULL if the bundle is not retail's
// FRONTB. Its objects stay in file order, which flailer_object_index
// needs, and 4-aligned, which flailer_add_project does.
uint8_t* debugmenu_patch_frontend(const uint8_t* data, size_t len,
                                  size_t* outLen);

// The item shown: MENUITEM_4 and MI_4_MASK written over the two hidden
// names, the three objects made visible and the main menu's bottom filler
// cut to a separator above them. 1 the first time, 0 after, or with no
// patched chunk. The main menu must be entered again for its menu and its
// SelectionSet to find the item.
int debugmenu_reveal(void);
int debugmenu_revealed(void);

// What the screen needs of main.c.
typedef struct {
    void* user;
    // bmenu_set_active_item on the current screen's menu.
    void (*setActiveItem)(void* user, uint32_t itemHash);
    // FrontendDatabase::StartRace on Fred, then the port's log line, as car
    // select's start does.
    void (*startRace)(void* user);
    // A line for the port's log: what was done, and the save prompt's
    // answer.
    void (*log)(void* user, const char* line);
} DebugMenuHooks;

void debugmenu_init(const DebugMenuHooks* hooks);

// The "Port Debug Menu" screen (BGF_DEBUG_MENU_NAME) and the "Port Debug
// Race" one (DEBUGMENU_RACE_NAME), registered in main.c's kScreens.
void debugmenu_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data);
void debugmenu_race_callback(BGameFlow* gf, BScreenMessage msg,
                             BScreenCallbackData* data);

// The help line under the current row, for the bottom screen's hint.
#define DEBUGMENU_HINT "Left/Right change   A select   B back"
