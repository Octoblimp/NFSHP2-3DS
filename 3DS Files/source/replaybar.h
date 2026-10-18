// replaybar -- the port's own: the replay bar's PS2 buttons as the 3DS's.
//
// Not a port of anything. ReplayScreen's bar, the bitmap at (0, 394) of
// screen 0x60befaed, is one texture: REPLAYBOTTOM_NEW, 640 x 88 in
// INGAMEB.BUN, a symbol for each of the replay's events over the
// DualShock 2 button that raises it. The events come from the scanners
// (scannertab.c's 92..103) through joyhid's menu layout, which a replay
// keeps (main.c's joyhidRaceLayout), so five of the buttons are other
// keys on the 3DS:
//
//     columns    symbol           event              DS2        3DS
//     16..39     Player 1/2       CAMERA_TARGET      L1         L
//     62..89     <<               PREVIOUS_MARKER    Left       Left
//     107..131   1/2 >            PLAYBACK_SPEED     Square     B
//     153..177   stop / play      PAUSE              Cross      A
//     196..221   camera           CAMERA_ANGLE       Triangle   X
//     241..265   ?                HELP               Circle     Y
//     281..309   >>               NEXT_MARKER        Right      Right
//     325..354   dot / dot        HIDE_TIMELINE      SELECT     SELECT
//     373..399   eject            SKIP               START      START
//
// When uirender uploads the texture, replaybar_retouch wipes those five
// buttons to the bar's grey and draws the 3DS key in each place from
// helpglyph.h's sheet, as the help line draws them. The D-pad's two,
// SELECT and START stay retail's, as helpglyph keeps BUTTONSOUT's: they
// fit the 3DS as they are. With one player, ReplayScreen shows
// REPLAYBOTTOM_BLANK over the first 52 columns, the L with them, as
// retail hides its L1.

#ifndef REPLAYBAR_H
#define REPLAYBAR_H

#include <stddef.h>
#include <stdint.h>

// bStringHash("REPLAYBOTTOM_NEW"), and its size.
#define REPLAYBAR_TEX_HASH 0xba7fcb6au
#define REPLAYBAR_TEX_W    640
#define REPLAYBAR_TEX_H    88

// The keys drawn, in the bar's order: L, B, A, X, Y.
#define REPLAYBAR_KEYS     5

// Retouches `rgba`, the texture's w x h texels as RGBA8 rows from the
// top, in place, from `sheet`, helpglyph.h's (HELPGLYPH_SHEET squared
// RGBA8 texels, rows from the top) of `sheetSize` bytes. Each key's
// columns are wiped on the grey band's rows with a copy of a bare column
// beside them, and the key's icon is laid over them, blended by its
// alpha; every alpha stays the bar's. Returns 1 when it did, and 0,
// changing nothing, for any other size or a missing or short sheet.
int32_t replaybar_retouch(uint8_t *rgba, uint32_t w, uint32_t h,
                          const uint8_t *sheet, size_t sheetSize);

#endif
