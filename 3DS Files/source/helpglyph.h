// helpglyph -- the port's own: the 3DS key a help character names.
//
// Not a port of anything. The game's strings name buttons with help
// characters, 0x80..0x9d (IsHelpCharacter, 0x00141db0), and retail draws
// each from BUTTONSOUT, a sheet of the DualShock 2's buttons
// (RenderHelpCharacter, uirender.c). On the 3DS the same events come from
// other keys -- joyhid.h's layouts, and main.c's own frontend keys -- so
// "Triangle Back" would send a player to the wrong button. This maps a
// help character to the 3DS key that does its job in a layout, drawn from
// the port's own sheet (tools/buttons3ds_make.py, data/buttons3ds.bin),
// or to the BUTTONSOUT glyph that still fits: the D-pad's four, START and
// SELECT.
//
//                    menus (MENU, FE)       a race (RACE, COP): the key
//                                           the player bound to
//     Cross          A                      throttle
//     Triangle       B (main.c's back)      camera
//     Square         X (main.c's)           brake
//     Circle         Y (help)               horn
//     L1 / R1        L / R                  look back / e-brake
//     L2 / R2        ZL / ZR                shift down / up; the cop's
//                                           helicopter / roadblock
//     R3             D-pad Down             nitro boost
//     D-pad Up       D-pad Up               cycle HUD
//     left stick     the Circle Pad (retail's 0x90..0x94)
//     right stick    the C-Stick (retail's 0x95..0x98)
//
// In the menus Triangle is B, Square X and Circle Y because main.c's
// frontend keys are what the menus hear: B pops the screen, X is
// MENU_SQUARE and Y summons the HELP panel (helpmenu.h, 2026-10-16), which
// joyhid's frontend layout matches for car select's scanners. In a race
// the keys are joyhid's gJoyHidBindings, the racer's or the cop's: the
// defaults are joyhid.h's map, and Options' Controller changes them. A
// key draws as its icon, D-pad Up and Down as BUTTONSOUT's; an action on
// no key keeps retail's glyph. In the cop's car the calls are one key
// each whatever the transmission, where retail's manual pad needs
// Triangle with L2 or R2 (970001); helpglyph_rewrite drops the "Triangle
// +" so that line reads as the 3DS's.

#ifndef HELPGLYPH_H
#define HELPGLYPH_H

#include <stddef.h>
#include <stdint.h>

// The sheet's icons, in tools/buttons3ds_make.py's order.
#define HELPGLYPH_3DS_A       0
#define HELPGLYPH_3DS_B       1
#define HELPGLYPH_3DS_X       2
#define HELPGLYPH_3DS_Y       3
#define HELPGLYPH_3DS_L       4
#define HELPGLYPH_3DS_R       5
#define HELPGLYPH_3DS_ZL      6
#define HELPGLYPH_3DS_ZR      7
#define HELPGLYPH_3DS_CPAD    8
#define HELPGLYPH_3DS_CSTICK  9
#define HELPGLYPH_3DS_COUNT   10

// The sheet: 128 x 128 RGBA8, row 0 at the top; icon i's cell is
// ((i % 4) * 26, (i / 4) * 28), 26 x 28 with an advance of 26, as retail
// BUTTONSOUT's cells are.
#define HELPGLYPH_SHEET       128
#define HELPGLYPH_CELL_W      26
#define HELPGLYPH_CELL_H      28
#define HELPGLYPH_COLS        4

// helpglyph_map's answer: an icon of the sheet is HELPGLYPH_ICON + it,
// anything below is the help character whose BUTTONSOUT glyph to draw.
#define HELPGLYPH_ICON        0x100

// A layout for the help characters alone, past joyhid's (JOYHID_LAYOUT_*),
// which joyhid_build never sees: each DualShock button draws the 3DS key
// in its place on the pad -- Cross A, Circle B, Triangle X, Square Y, L1
// L, R1 R, L2 ZL, R2 ZR. Options' Controller page names keys with it
// (joyconfig.h), whatever they do in a layout.
#define HELPGLYPH_LAYOUT_KEYS 4

// What help character `c` (0x80..0x9d) draws as in joyhid layout `layout`
// (JOYHID_LAYOUT_*): HELPGLYPH_ICON + an icon, or a help character for
// BUTTONSOUT -- `c` itself, or a D-pad's for R3 and a binding on D-pad
// Up or Down.
int32_t helpglyph_map(unsigned char c, int32_t layout);

// How joyhid bind key `key` (JOYHID_BIND_*) draws: HELPGLYPH_ICON + an
// icon, D-pad Up's or Down's help character, or -1 for none.
int32_t helpglyph_key(int32_t key);

// The help character that draws joyhid bind key `key` in
// HELPGLYPH_LAYOUT_KEYS, or 0 for none.
unsigned char helpglyph_key_char(int32_t key);

// `s` as the 3DS has it in `layout`, in place: in COP, a Triangle, " + "
// and then L2 or R2 is the one key. Returns the new length.
size_t helpglyph_rewrite(char *s, int32_t layout);

#endif
