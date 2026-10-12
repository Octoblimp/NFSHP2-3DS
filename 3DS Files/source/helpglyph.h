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
//                    menus (MENU, FE)   race (RACE)   Be A Cop (COP)
//     Cross          A                  A             A
//     Triangle       B (main.c's back)  Y             Y
//     Square         Y (main.c's)       B             B
//     Circle         as joyhid has it:  X (the horn)  X (the target)
//                    Y in MENU, B in FE
//     L1 / R1        L / R              L / R         L / R
//     L2 / R2        ZL / ZR            ZL / ZR       R / L (the
//                                                     helicopter, the
//                                                     roadblock)
//     R3             D-pad Down, the nitro's (joyhid's double of R3)
//     left stick     the Circle Pad (0x90, and 0x98, BUTTONSOUT's stick)
//     right stick    the C-Stick (0x91)
//
// In the menus Triangle is B and Square Y because main.c's frontend keys
// are what the menus hear: B pops the screen and Y is MENU_SQUARE, which
// joyhid's frontend layout matches for car select's scanners. In the cop's
// car L and R are the calls whatever the transmission, where retail's
// manual pad needs Triangle with L2 or R2 (970001); helpglyph_rewrite
// drops the "Triangle +" so that line reads as the 3DS's.

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

// What help character `c` (0x80..0x9d) draws as in joyhid layout `layout`
// (JOYHID_LAYOUT_*): HELPGLYPH_ICON + an icon, or a help character for
// BUTTONSOUT -- `c` itself but for R3, which is D-pad Down's.
int32_t helpglyph_map(unsigned char c, int32_t layout);

// `s` as the 3DS has it in `layout`, in place: in COP, a Triangle, " + "
// and then L2 or R2 is the one key. Returns the new length.
size_t helpglyph_rewrite(char *s, int32_t layout);

#endif
