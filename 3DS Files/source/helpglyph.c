// helpglyph -- the port's own: the 3DS key a help character names. See
// helpglyph.h.

#include "helpglyph.h"

#include <string.h>

#include "joyhid.h"

// The help characters, by the DualShock 2 button they draw (BUTTONSOUT's
// glyphs through retail's table at 0x002f09c0, uirender.c's kHelpGlyph).
enum {
    HC_START    = 0x80,
    HC_SELECT   = 0x81,
    HC_DDOWN    = 0x83,
    HC_CROSS    = 0x86,
    HC_TRIANGLE = 0x87,
    HC_SQUARE   = 0x88,
    HC_CIRCLE   = 0x89,
    HC_L1       = 0x8a,
    HC_R1       = 0x8b,
    HC_L2       = 0x8c,
    HC_R2       = 0x8d,
    HC_R3       = 0x8f,
    HC_LSTICK   = 0x90,
    HC_RSTICK   = 0x91,
    HC_STICK    = 0x98,     // BUTTONSOUT's 'c', the stick
};

#define ICON(i) (HELPGLYPH_ICON + (i))

int32_t helpglyph_map(unsigned char c, int32_t layout)
{
    int32_t race = layout == JOYHID_LAYOUT_RACE || layout == JOYHID_LAYOUT_COP;

    switch (c) {
    case HC_CROSS:
        return ICON(HELPGLYPH_3DS_A);
    case HC_TRIANGLE:
        return ICON(race ? HELPGLYPH_3DS_Y : HELPGLYPH_3DS_B);
    case HC_SQUARE:
        return ICON(race ? HELPGLYPH_3DS_B : HELPGLYPH_3DS_Y);
    case HC_CIRCLE:
        if (race)
            return ICON(HELPGLYPH_3DS_X);
        return ICON(layout == JOYHID_LAYOUT_FE ? HELPGLYPH_3DS_B
                                               : HELPGLYPH_3DS_Y);
    case HC_L1:
        return ICON(HELPGLYPH_3DS_L);
    case HC_R1:
        return ICON(HELPGLYPH_3DS_R);
    case HC_L2:
        return ICON(layout == JOYHID_LAYOUT_COP ? HELPGLYPH_3DS_R
                                                : HELPGLYPH_3DS_ZL);
    case HC_R2:
        return ICON(layout == JOYHID_LAYOUT_COP ? HELPGLYPH_3DS_L
                                                : HELPGLYPH_3DS_ZR);
    case HC_R3:
        return HC_DDOWN;
    case HC_LSTICK:
    case HC_STICK:
        return ICON(HELPGLYPH_3DS_CPAD);
    case HC_RSTICK:
        return ICON(HELPGLYPH_3DS_CSTICK);
    default:
        // The D-pad, START, SELECT, and the rest as retail draws them.
        return c;
    }
}

size_t helpglyph_rewrite(char *s, int32_t layout)
{
    static const char kCombo[] = { (char)HC_TRIANGLE, ' ', '+', ' ' };
    size_t n = strlen(s), i = 0;

    if (layout != JOYHID_LAYOUT_COP)
        return n;
    while (i + sizeof kCombo < n) {
        unsigned char next = (unsigned char)s[i + sizeof kCombo];

        if (memcmp(s + i, kCombo, sizeof kCombo) == 0
            && (next == HC_L2 || next == HC_R2)) {
            memmove(s + i, s + i + sizeof kCombo, n - i - sizeof kCombo + 1);
            n -= sizeof kCombo;
        } else {
            i++;
        }
    }
    return n;
}
