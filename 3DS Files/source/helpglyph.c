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
    HC_DUP      = 0x82,
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
    // Retail's sticks (joyeventid.h's JOY_LSTICK_* and JOY_RSTICK_*): the
    // left's up-down, up, down and left-right, then the right's four.
    HC_LSTICK   = 0x90,
    HC_APOS     = 0x92,     // the apostrophe, not a help character
    HC_LSTICK_LAST = 0x94,
    HC_RSTICK   = 0x95,
    HC_RSTICK_LAST = 0x98,
};

#define ICON(i) (HELPGLYPH_ICON + (i))

typedef char helpglyph_bind_check[
    (HELPGLYPH_3DS_A == JOYHID_BIND_A && HELPGLYPH_3DS_B == JOYHID_BIND_B
     && HELPGLYPH_3DS_X == JOYHID_BIND_X && HELPGLYPH_3DS_Y == JOYHID_BIND_Y
     && HELPGLYPH_3DS_L == JOYHID_BIND_L && HELPGLYPH_3DS_R == JOYHID_BIND_R
     && HELPGLYPH_3DS_ZL == JOYHID_BIND_ZL
     && HELPGLYPH_3DS_ZR == JOYHID_BIND_ZR) ? 1 : -1];

int32_t helpglyph_key(int32_t key)
{
    if (key >= JOYHID_BIND_A && key <= JOYHID_BIND_ZR)
        return ICON(key);   // the sheet's first eight are the bind keys'
    if (key == JOYHID_BIND_DUP)
        return HC_DUP;
    if (key == JOYHID_BIND_DDOWN)
        return HC_DDOWN;
    return -1;
}

typedef char helpglyph_layout_check[
    (HELPGLYPH_LAYOUT_KEYS != JOYHID_LAYOUT_MENU
     && HELPGLYPH_LAYOUT_KEYS != JOYHID_LAYOUT_RACE
     && HELPGLYPH_LAYOUT_KEYS != JOYHID_LAYOUT_COP
     && HELPGLYPH_LAYOUT_KEYS != JOYHID_LAYOUT_FE) ? 1 : -1];

// HELPGLYPH_LAYOUT_KEYS: the bind keys' buttons, by JOYHID_BIND_*.
static const unsigned char kKeyChar[JOYHID_BIND_KEYS] = {
    HC_CROSS, HC_CIRCLE, HC_TRIANGLE, HC_SQUARE, HC_L1, HC_R1, HC_L2, HC_R2,
    HC_DUP, HC_DDOWN,
};

unsigned char helpglyph_key_char(int32_t key)
{
    return key >= 0 && key < JOYHID_BIND_KEYS ? kKeyChar[key] : 0;
}

// The action whose button help character `c` draws in a race, or -1.
static int32_t race_action(unsigned char c, int32_t cop)
{
    switch (c) {
    case HC_CROSS:    return JOYHID_ACT_THROTTLE;
    case HC_SQUARE:   return JOYHID_ACT_BRAKE;
    case HC_CIRCLE:   return JOYHID_ACT_HORN;
    case HC_TRIANGLE: return JOYHID_ACT_CAMERA;
    case HC_L1:       return JOYHID_ACT_LOOKBACK;
    case HC_R1:       return JOYHID_ACT_EBRAKE;
    case HC_R3:       return JOYHID_ACT_BOOST;
    case HC_DUP:      return JOYHID_ACT_HUD;
    // The cop's lines name L2 and R2 for the calls (helpglyph_rewrite).
    case HC_L2:  return cop ? JOYHID_ACT_HELICOPTER : JOYHID_ACT_SHIFTDOWN;
    case HC_R2:  return cop ? JOYHID_ACT_ROADBLOCK : JOYHID_ACT_SHIFTUP;
    default:          return -1;
    }
}

int32_t helpglyph_map(unsigned char c, int32_t layout)
{
    if (layout == JOYHID_LAYOUT_RACE || layout == JOYHID_LAYOUT_COP) {
        int32_t cop = layout == JOYHID_LAYOUT_COP;
        int32_t a = race_action(c, cop);

        if (a >= 0) {
            const uint8_t *t = cop ? gJoyHidBindings.cop
                                   : gJoyHidBindings.racer;
            int32_t g = helpglyph_key(t[a]);

            // An action on no key keeps retail's glyph.
            return g >= 0 ? g : c;
        }
    } else if (layout == HELPGLYPH_LAYOUT_KEYS) {
        int32_t k;

        for (k = JOYHID_BIND_A; k <= JOYHID_BIND_ZR; k++)
            if (kKeyChar[k] == c)
                return ICON(k);   // the sheet's first eight
    } else {
        switch (c) {
        case HC_CROSS:
            return ICON(HELPGLYPH_3DS_A);
        case HC_TRIANGLE:
            return ICON(HELPGLYPH_3DS_B);
        case HC_SQUARE:
            return ICON(HELPGLYPH_3DS_Y);
        case HC_CIRCLE:
            return ICON(layout == JOYHID_LAYOUT_FE ? HELPGLYPH_3DS_B
                                                   : HELPGLYPH_3DS_Y);
        case HC_L1:
            return ICON(HELPGLYPH_3DS_L);
        case HC_R1:
            return ICON(HELPGLYPH_3DS_R);
        case HC_L2:
            return ICON(HELPGLYPH_3DS_ZL);
        case HC_R2:
            return ICON(HELPGLYPH_3DS_ZR);
        case HC_R3:
            return HC_DDOWN;
        default:
            break;
        }
    }
    if (c >= HC_LSTICK && c <= HC_LSTICK_LAST && c != HC_APOS)
        return ICON(HELPGLYPH_3DS_CPAD);
    if (c >= HC_RSTICK && c <= HC_RSTICK_LAST)
        return ICON(HELPGLYPH_3DS_CSTICK);
    // The D-pad, START, SELECT, and the rest as retail draws them.
    return c;
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
