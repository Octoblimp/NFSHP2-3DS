#pragma once
#include <stdint.h>

#include "bmenu.h"
#include "gameflow.h"

// Options' Player Names: retail's NameEntry (0x0024d408 .. 0x0024dc70),
// "NameEntry" in kScreens. Four rows, Player 1's name and gender and
// Player 2's. A on a name opens a keyboard, and Left and Right on a gender
// switch it between Male and Female. Retail's B saves on the Autosave
// screen when anything changed and autosave is on; the port's asks first,
// with autosave on or off (the user's word, 2026-10-13): Yes saves there,
// No puts the names and genders back, and B stays.
//
// Retail's keyboard is tKeyboard (0x0024c458 .. 0x0024d2f0): a letter grid
// drawn on the screen, three rows of fourteen, moved over with the pad.
// The port uses the 3DS's own keyboard instead (TASKS 54, the user's
// request of 2026-10-12), with tKeyboard's rules kept: seven characters,
// from its two maps' set, and the name written with
// cPlayerSettings::SetName. The grid's objects stay hidden, as they are in
// retail until the keyboard opens. docs/formats/name-entry.md.
//
// Each player's rows answer only that player's pad, as retail's do. The
// 3DS has one pad and no split screen, so the port hides Player 2's rows
// and the menu passes over them (the user's word, 2026-10-13). Player 2's
// name and gender stay in the save as retail keeps them.

// FlailerScreenConfig's hash for "NameEntry".
#define NAMEENTRY_SCREEN 0x617a4e0au

// tKeyboard's StringLength + 1: the cursor stops at 6, and the EditBuffer
// is eight bytes with its last always 0.
#define NAMEENTRY_MAX_CHARS 7

// What the screen needs of main.c.
typedef struct {
    void* user;
    // The keyboard, over `name` (NAMEENTRY_MAX_CHARS at most, `size`
    // bytes): 1 with the typed name in `name` when the player confirmed it,
    // 0 with `name` as it was when they cancelled. `hint` is the row's
    // blurb, in the game's own encoding (Latin-1).
    int (*keyboard)(void* user, const char* hint, char* name, int size);
    // A line for the port's log.
    void (*log)(void* user, const char* line);
} NameEntryHooks;

void nameentry_init(const NameEntryHooks* hooks);

// Whether tKeyboard can type `c`: its DefaultMap and ShiftMap
// (0x0031d750, 0x0031d780) are a-z, A-Z, 0-9, '!', '.', '#' and the
// space, with '(' and ')' as its delete and done keys.
int nameentry_char_ok(int c);

// NameEntry::Callback (0x0024dbd8), for kScreens[].
void nameentry_callback(BGameFlow* gf, BScreenMessage msg,
                        BScreenCallbackData* data);
