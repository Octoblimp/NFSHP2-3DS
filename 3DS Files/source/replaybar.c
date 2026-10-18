// replaybar -- the port's own: the replay bar's PS2 buttons as the 3DS's.
// See replaybar.h.

#include "replaybar.h"

#include "helpglyph.h"

// The grey band between the bar's two dark lines (rows 28 and 61), which
// the buttons sit on, and the top row of an icon's cell: its art, rows
// 3..25, then covers the PS2 face buttons' rows 33..55.
#define BAND_TOP    29
#define BAND_BOTTOM 60
#define CELL_TOP    30

// Each key: the columns wiped, a bare column of the band to the left of
// the button, whose texel of each row is copied over them, and the icon
// with the left edge of its cell, centred on the PS2 button's columns.
static const struct {
    uint16_t x0, x1;
    uint16_t bare;
    uint8_t  icon;
    uint16_t cellX;
} kKeys[REPLAYBAR_KEYS] = {
    {  14,  41,   8, HELPGLYPH_3DS_L,  15 },    // L1
    { 105, 133, 100, HELPGLYPH_3DS_B, 106 },    // Square
    { 151, 179, 145, HELPGLYPH_3DS_A, 152 },    // Cross
    { 194, 223, 188, HELPGLYPH_3DS_X, 196 },    // Triangle
    { 239, 267, 232, HELPGLYPH_3DS_Y, 240 },    // Circle
};

int32_t replaybar_retouch(uint8_t *rgba, uint32_t w, uint32_t h,
                          const uint8_t *sheet, size_t sheetSize)
{
    int k;

    if (rgba == NULL || w != REPLAYBAR_TEX_W || h != REPLAYBAR_TEX_H
        || sheet == NULL
        || sheetSize < (size_t)HELPGLYPH_SHEET * HELPGLYPH_SHEET * 4)
        return 0;
    for (k = 0; k < REPLAYBAR_KEYS; k++) {
        uint32_t ix = (uint32_t)(kKeys[k].icon % HELPGLYPH_COLS)
                      * HELPGLYPH_CELL_W;
        uint32_t iy = (uint32_t)(kKeys[k].icon / HELPGLYPH_COLS)
                      * HELPGLYPH_CELL_H;
        uint32_t x, y;

        for (y = BAND_TOP; y <= BAND_BOTTOM; y++) {
            const uint8_t *s = rgba + ((size_t)y * w + kKeys[k].bare) * 4;

            for (x = kKeys[k].x0; x <= kKeys[k].x1; x++) {
                uint8_t *d = rgba + ((size_t)y * w + x) * 4;

                d[0] = s[0];
                d[1] = s[1];
                d[2] = s[2];
                d[3] = s[3];
            }
        }
        for (y = 0; y < HELPGLYPH_CELL_H; y++) {
            for (x = 0; x < HELPGLYPH_CELL_W; x++) {
                const uint8_t *s =
                    sheet + ((size_t)(iy + y) * HELPGLYPH_SHEET + ix + x) * 4;
                uint8_t *d = rgba + ((size_t)(CELL_TOP + y) * w
                                     + kKeys[k].cellX + x) * 4;
                uint32_t a = s[3];
                int c;

                if (a == 0)
                    continue;
                for (c = 0; c < 3; c++)
                    d[c] = (uint8_t)((s[c] * a + d[c] * (255u - a) + 127u)
                                     / 255u);
            }
        }
    }
    return 1;
}
