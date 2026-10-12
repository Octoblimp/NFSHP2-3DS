// Host test for helpglyph.c: the 3DS key each help character draws as.
// tools/helpglyph_check.py builds and runs it.
//
// The race layouts are held to joyhid.c itself: each 3DS key goes through
// joyhid_build, and the DualShock 2 button it presses must be the help
// character that draws that key. Be A Cop's L and R go through
// joyhid_cop_keys, whose Triangle and trigger are the Blurb's "Triangle +
// L2/R2", which helpglyph_rewrite makes the one key. The menus hear
// main.c's frontend keys (A select, B back, Y Square), so they are a table.

#include <stdio.h>
#include <string.h>

#include "helpglyph.h"
#include "joyhid.h"
#include "joypad.h"

// joyhid_install's, from joypad.c, which this does not link.
JoypadReadFn gJoypadRead;

static int failures;

#define ICON(i) (HELPGLYPH_ICON + (i))

static void expect(int32_t got, int32_t want, const char *what)
{
    if (got != want) {
        printf("FAIL %s: got 0x%x, want 0x%x\n", what, (unsigned)got,
               (unsigned)want);
        failures++;
    }
}

// The help characters of the DualShock 2's buttons, by their bit in bytes
// 2-3 of the pad buffer (joyhid.c's DS2_* order).
static const struct {
    int           bit;
    unsigned char help;
    const char   *name;
} kButtons[] = {
    { 8,  0x8c, "L2" },
    { 9,  0x8d, "R2" },
    { 10, 0x8a, "L1" },
    { 11, 0x8b, "R1" },
    { 12, 0x87, "Triangle" },
    { 13, 0x89, "Circle" },
    { 14, 0x86, "Cross" },
    { 15, 0x88, "Square" },
};
#define NUM_BUTTONS ((int)(sizeof kButtons / sizeof kButtons[0]))

// The help characters of the buttons `keys` press in `layout`.
static int pressed(uint32_t keys, int32_t layout, unsigned char out[8])
{
    JoyHidState s;
    uint8_t     buf[32];
    uint32_t    buttons;
    int         n = 0;

    memset(&s, 0, sizeof s);
    s.keys = keys;
    s.race = layout;
    joyhid_build(&s, buf);
    buttons = (uint32_t)buf[2] | ((uint32_t)buf[3] << 8);   // active low
    for (int i = 0; i < NUM_BUTTONS; i++)
        if (!(buttons & (1u << kButtons[i].bit)))
            out[n++] = kButtons[i].help;
    return n;
}

static void race_keys(int32_t layout, const char *name)
{
    static const struct {
        uint32_t key;
        int32_t  icon;
        const char *name;
    } kKeys[] = {
        { JOYHID_A,  HELPGLYPH_3DS_A,  "A" },
        { JOYHID_B,  HELPGLYPH_3DS_B,  "B" },
        { JOYHID_X,  HELPGLYPH_3DS_X,  "X" },
        { JOYHID_Y,  HELPGLYPH_3DS_Y,  "Y" },
        { JOYHID_L,  HELPGLYPH_3DS_L,  "L" },
        { JOYHID_R,  HELPGLYPH_3DS_R,  "R" },
        { JOYHID_ZL, HELPGLYPH_3DS_ZL, "ZL" },
        { JOYHID_ZR, HELPGLYPH_3DS_ZR, "ZR" },
    };
    char what[96];

    for (size_t i = 0; i < sizeof kKeys / sizeof kKeys[0]; i++) {
        unsigned char help[8];
        int           n = pressed(kKeys[i].key, layout, help);

        // In the cop's car L and R are the calls and ZL and ZR stand in
        // for nothing on their own; the calls are checked below.
        if (layout == JOYHID_LAYOUT_COP
            && (kKeys[i].key & (JOYHID_L | JOYHID_R | JOYHID_ZL
                                | JOYHID_ZR)))
            continue;
        snprintf(what, sizeof what, "%s: %s presses one button", name,
                 kKeys[i].name);
        expect(n, 1, what);
        if (n != 1)
            continue;
        snprintf(what, sizeof what, "%s: %s's button 0x%02x draws as %s",
                 name, kKeys[i].name, help[0], kKeys[i].name);
        expect(helpglyph_map(help[0], layout), ICON(kKeys[i].icon), what);
    }
}

// Be A Cop's call on `key`: the buttons its second reading holds, which
// are the combo, and the Blurb's line for them rewritten.
static void cop_call(uint32_t key, unsigned char trigger, int32_t icon,
                     const char *name)
{
    JoyHidCop     c;
    unsigned char help[8];
    char          line[8], what[96];
    int           n;
    uint32_t      keys;

    memset(&c, 0, sizeof c);
    (void)joyhid_cop_keys(&c, 0, 1);
    (void)joyhid_cop_keys(&c, key, 1);
    keys = joyhid_cop_keys(&c, key, 1);
    n = pressed(keys, JOYHID_LAYOUT_COP, help);
    snprintf(what, sizeof what, "COP: %s's combo is two buttons", name);
    expect(n, 2, what);
    if (n == 2) {
        snprintf(what, sizeof what, "COP: %s's combo is Triangle and 0x%02x",
                 name, trigger);
        expect((help[0] == 0x87 && help[1] == trigger)
               || (help[1] == 0x87 && help[0] == trigger), 1, what);
    }
    line[0] = (char)0x87;
    line[1] = ' ';
    line[2] = '+';
    line[3] = ' ';
    line[4] = (char)trigger;
    line[5] = 0;
    snprintf(what, sizeof what, "COP: \"Triangle + 0x%02x\" is one key",
             trigger);
    expect((int32_t)helpglyph_rewrite(line, JOYHID_LAYOUT_COP), 1, what);
    expect((unsigned char)line[0], trigger, what);
    snprintf(what, sizeof what, "COP: 0x%02x draws as %s", trigger, name);
    expect(helpglyph_map(trigger, JOYHID_LAYOUT_COP), ICON(icon), what);
}

static void menus(int32_t layout, const char *name)
{
    char what[96];

    snprintf(what, sizeof what, "%s: Cross is A, select", name);
    expect(helpglyph_map(0x86, layout), ICON(HELPGLYPH_3DS_A), what);
    snprintf(what, sizeof what, "%s: Triangle is B, back", name);
    expect(helpglyph_map(0x87, layout), ICON(HELPGLYPH_3DS_B), what);
    snprintf(what, sizeof what, "%s: Square is Y, MENU_SQUARE", name);
    expect(helpglyph_map(0x88, layout), ICON(HELPGLYPH_3DS_Y), what);
    snprintf(what, sizeof what, "%s: L1 is L", name);
    expect(helpglyph_map(0x8a, layout), ICON(HELPGLYPH_3DS_L), what);
    snprintf(what, sizeof what, "%s: R1 is R", name);
    expect(helpglyph_map(0x8b, layout), ICON(HELPGLYPH_3DS_R), what);
    snprintf(what, sizeof what, "%s: R2 is ZR", name);
    expect(helpglyph_map(0x8d, layout), ICON(HELPGLYPH_3DS_ZR), what);

    // Circle has no frontend key of main.c's, so it is joyhid's: the key
    // that presses it in this layout.
    {
        uint32_t      key = layout == JOYHID_LAYOUT_FE ? JOYHID_B : JOYHID_Y;
        int32_t       icon = key == JOYHID_B ? HELPGLYPH_3DS_B
                                             : HELPGLYPH_3DS_Y;
        unsigned char help[8];
        int           n = pressed(key, layout, help);

        snprintf(what, sizeof what, "%s: %s presses Circle", name,
                 key == JOYHID_B ? "B" : "Y");
        expect(n == 1 && help[0] == 0x89, 1, what);
        snprintf(what, sizeof what, "%s: Circle draws as %s", name,
                 key == JOYHID_B ? "B" : "Y");
        expect(helpglyph_map(0x89, layout), ICON(icon), what);
    }
}

// What every layout shares: the D-pad, START, SELECT and the rest drawn
// as retail draws them, R3 as D-pad Down, the sticks as the 3DS's.
static void shared(int32_t layout, const char *name)
{
    char what[96];

    for (int c = 0x80; c <= 0x9d; c++) {
        int32_t want = c;

        if ((c >= 0x86 && c <= 0x8d) || c == 0x8f || c == 0x90 || c == 0x91
            || c == 0x98)
            continue;
        snprintf(what, sizeof what, "%s: 0x%02x drawn as retail's", name, c);
        expect(helpglyph_map((unsigned char)c, layout), want, what);
    }
    snprintf(what, sizeof what, "%s: R3 is D-pad Down's", name);
    expect(helpglyph_map(0x8f, layout), 0x83, what);
    snprintf(what, sizeof what, "%s: the left stick is the Circle Pad", name);
    expect(helpglyph_map(0x90, layout), ICON(HELPGLYPH_3DS_CPAD), what);
    expect(helpglyph_map(0x98, layout), ICON(HELPGLYPH_3DS_CPAD), what);
    snprintf(what, sizeof what, "%s: the right stick is the C-Stick", name);
    expect(helpglyph_map(0x91, layout), ICON(HELPGLYPH_3DS_CSTICK), what);
}

static void rewrite(void)
{
    // 970001, retail's manual cop pad, every language's.
    static const char kPad[] =
        "Be on the lookout for speeders!@Arrest four speeders in time to "
        "earn bonus points.@ \x89 target/untarget speeders within range@ "
        "\x87 + \x8c call helicopter backup@ \x87 + \x8d call for "
        "roadblock@ \x8f activate nitrous boost";
    static const char kWant[] =
        "Be on the lookout for speeders!@Arrest four speeders in time to "
        "earn bonus points.@ \x89 target/untarget speeders within range@ "
        "\x8c call helicopter backup@ \x8d call for "
        "roadblock@ \x8f activate nitrous boost";
    static const char *kKept[] = {
        "\x87 + ",          // nothing after it
        "\x87 + x",         // not a trigger
        "\x87 \x8c",        // not the combo
        "\x87 + \x8a",      // L1
    };
    char s[512];

    snprintf(s, sizeof s, "%s", kPad);
    expect((int32_t)helpglyph_rewrite(s, JOYHID_LAYOUT_COP),
           (int32_t)strlen(kWant), "COP: 970001's length");
    expect(strcmp(s, kWant) == 0, 1, "COP: 970001 as the 3DS's");

    for (int32_t layout = JOYHID_LAYOUT_MENU; layout <= JOYHID_LAYOUT_FE;
         layout++) {
        if (layout == JOYHID_LAYOUT_COP)
            continue;
        snprintf(s, sizeof s, "%s", kPad);
        expect((int32_t)helpglyph_rewrite(s, layout), (int32_t)strlen(kPad),
               "only COP rewrites");
        expect(strcmp(s, kPad) == 0, 1, "only COP rewrites");
    }
    for (size_t i = 0; i < sizeof kKept / sizeof kKept[0]; i++) {
        snprintf(s, sizeof s, "%s", kKept[i]);
        (void)helpglyph_rewrite(s, JOYHID_LAYOUT_COP);
        expect(strcmp(s, kKept[i]) == 0, 1, "COP keeps what is no combo");
    }
    snprintf(s, sizeof s, "\x87 + \x87 + \x8d");
    (void)helpglyph_rewrite(s, JOYHID_LAYOUT_COP);
    expect(strcmp(s, "\x87 + \x8d") == 0, 1, "COP: one combo a match");
}

int main(void)
{
    race_keys(JOYHID_LAYOUT_RACE, "RACE");
    race_keys(JOYHID_LAYOUT_COP, "COP");
    cop_call(JOYHID_L, 0x8d, HELPGLYPH_3DS_L, "L, the roadblock");
    cop_call(JOYHID_R, 0x8c, HELPGLYPH_3DS_R, "R, the helicopter");
    menus(JOYHID_LAYOUT_MENU, "MENU");
    menus(JOYHID_LAYOUT_FE, "FE");
    shared(JOYHID_LAYOUT_MENU, "MENU");
    shared(JOYHID_LAYOUT_RACE, "RACE");
    shared(JOYHID_LAYOUT_COP, "COP");
    shared(JOYHID_LAYOUT_FE, "FE");
    rewrite();

    if (failures) {
        printf("helpglyph: %d failed\n", failures);
        return 1;
    }
    printf("helpglyph: ok\n");
    return 0;
}
