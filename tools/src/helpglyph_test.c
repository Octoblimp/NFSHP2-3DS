// Host test for helpglyph.c: the 3DS key each help character draws as.
// tools/helpglyph_check.py builds and runs it.
//
// The race layouts are held to joyhid.c itself: each bound key goes
// through joyhid_build, and the DualShock 2 button it presses must be the
// help character that draws that key, with the default bindings and with
// changed ones. Be A Cop's calls go through joyhid_cop_calls, whose
// Triangle and trigger are the Blurb's "Triangle + L2/R2", which
// helpglyph_rewrite makes the one key. The menus hear main.c's frontend
// keys (A select, B back, Y Square), so they are a table. joyhid_bind and
// joyhid_bindings_valid are held to their promises here too.

#include <stdio.h>
#include <string.h>

#include "helpglyph.h"
#include "joyeventid.h"
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
    { 2,  0x8f, "R3" },
    { 4,  0x82, "Up" },
    { 6,  0x83, "Down" },
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

static const char *const kKeyName[JOYHID_BIND_KEYS] = {
    "A", "B", "X", "Y", "L", "R", "ZL", "ZR", "Up", "Down",
};

static const char *const kActName[JOYHID_ACT_COUNT] = {
    "throttle", "brake", "e-brake", "horn", "camera", "look back",
    "shift up", "shift down", "HUD", "boost", "roadblock", "helicopter",
};

// The help characters of the buttons `keys` and `calls` press in `layout`.
static int pressed(uint32_t keys, uint32_t calls, int32_t layout,
                   unsigned char out[16])
{
    JoyHidState s;
    uint8_t     buf[32];
    uint32_t    buttons;
    int         n = 0;

    memset(&s, 0, sizeof s);
    s.keys = keys;
    s.calls = calls;
    s.race = layout;
    joyhid_build(&s, buf);
    buttons = (uint32_t)buf[2] | ((uint32_t)buf[3] << 8);   // active low
    for (int i = 0; i < NUM_BUTTONS; i++)
        if (!(buttons & (1u << kButtons[i].bit)))
            out[n++] = kButtons[i].help;
    return n;
}

// Every bound key of the layout's table presses one button, which draws
// as that key.
static void race_keys(int32_t layout, const char *name)
{
    const uint8_t *t = layout == JOYHID_LAYOUT_COP ? gJoyHidBindings.cop
                                                   : gJoyHidBindings.racer;
    char what[128];

    for (int32_t a = 0; a < JOYHID_ACT_COUNT; a++) {
        unsigned char help[16];
        int           n;

        if (t[a] == JOYHID_BIND_NONE)
            continue;
        // The calls press nothing of their own (cop_call, below), and in
        // the cop's car L2 and R2 are the calls' help characters, so the
        // gears have none.
        if (a == JOYHID_ACT_ROADBLOCK || a == JOYHID_ACT_HELICOPTER) {
            n = pressed(joyhid_bind_key(t[a]), 0, layout, help);
            snprintf(what, sizeof what, "%s: %s's %s presses nothing", name,
                     kActName[a], kKeyName[t[a]]);
            expect(n, 0, what);
            continue;
        }
        n = pressed(joyhid_bind_key(t[a]), 0, layout, help);
        snprintf(what, sizeof what, "%s: %s's %s presses one button", name,
                 kActName[a], kKeyName[t[a]]);
        expect(n, 1, what);
        if (n != 1)
            continue;
        if (layout == JOYHID_LAYOUT_COP
            && (a == JOYHID_ACT_SHIFTUP || a == JOYHID_ACT_SHIFTDOWN))
            continue;
        snprintf(what, sizeof what, "%s: %s's button 0x%02x draws as %s",
                 name, kActName[a], help[0], kKeyName[t[a]]);
        expect(helpglyph_map(help[0], layout), helpglyph_key(t[a]), what);
    }
}

// The user's map (joyhid.h): the help character each default key draws
// for, in each race layout.
static void defaults(void)
{
    static const struct {
        int32_t       layout;
        uint32_t      key;
        unsigned char help;
        const char   *what;
    } kWant[] = {
        { JOYHID_LAYOUT_RACE, JOYHID_A,     0x86, "RACE: A, throttle" },
        { JOYHID_LAYOUT_RACE, JOYHID_B,     0x88, "RACE: B, brake" },
        { JOYHID_LAYOUT_RACE, JOYHID_X,     0x89, "RACE: X, horn" },
        { JOYHID_LAYOUT_RACE, JOYHID_Y,     0x87, "RACE: Y, camera" },
        { JOYHID_LAYOUT_RACE, JOYHID_L,     0x8a, "RACE: L, look back" },
        { JOYHID_LAYOUT_RACE, JOYHID_R,     0x8b, "RACE: R, e-brake" },
        { JOYHID_LAYOUT_RACE, JOYHID_ZL,    0x8c, "RACE: ZL, shift down" },
        { JOYHID_LAYOUT_RACE, JOYHID_ZR,    0x8d, "RACE: ZR, shift up" },
        { JOYHID_LAYOUT_RACE, JOYHID_DUP,   0x82, "RACE: Up, HUD" },
        { JOYHID_LAYOUT_COP,  JOYHID_A,     0x86, "COP: A, throttle" },
        { JOYHID_LAYOUT_COP,  JOYHID_B,     0x88, "COP: B, brake" },
        { JOYHID_LAYOUT_COP,  JOYHID_X,     0x89, "COP: X, the target" },
        { JOYHID_LAYOUT_COP,  JOYHID_Y,     0x87, "COP: Y, camera" },
        { JOYHID_LAYOUT_COP,  JOYHID_ZL,    0x8f, "COP: ZL, nitro boost" },
        { JOYHID_LAYOUT_COP,  JOYHID_ZR,    0x8d, "COP: ZR, shift up" },
        { JOYHID_LAYOUT_COP,  JOYHID_DDOWN, 0x8c, "COP: Down, shift down" },
        { JOYHID_LAYOUT_COP,  JOYHID_DUP,   0x82, "COP: Up, HUD" },
    };
    unsigned char help[16];
    char          what[128];

    for (size_t i = 0; i < sizeof kWant / sizeof kWant[0]; i++) {
        int n = pressed(kWant[i].key, 0, kWant[i].layout, help);

        snprintf(what, sizeof what, "%s presses it alone", kWant[i].what);
        expect(n == 1 && help[0] == kWant[i].help, 1, what);
    }
    // Nothing else racing: Down presses nothing for a racer, L and R
    // nothing for the cop (the calls), and the D-pad's Left and Right
    // steer in both.
    expect(pressed(JOYHID_DDOWN, 0, JOYHID_LAYOUT_RACE, help), 0,
           "RACE: Down is free");
    expect(pressed(JOYHID_L | JOYHID_R, 0, JOYHID_LAYOUT_COP, help), 0,
           "COP: L and R press nothing");
    // The boost's glyph, R3, is ZL's in the cop's car.
    expect(helpglyph_map(0x8f, JOYHID_LAYOUT_COP), ICON(HELPGLYPH_3DS_ZL),
           "COP: R3 draws as ZL");
    // And a racer's boost is on no key: retail's glyph.
    expect(helpglyph_map(0x8f, JOYHID_LAYOUT_RACE), 0x8f,
           "RACE: R3 is on no key");
}

// Be A Cop's call on `key`: the buttons its second reading holds, which
// are the combo, and the Blurb's line for them rewritten.
static void cop_call(uint32_t key, unsigned char trigger, int32_t icon,
                     const char *name)
{
    JoyHidCop     c;
    unsigned char help[16];
    char          line[8], what[96];
    int           n;
    uint32_t      calls;

    memset(&c, 0, sizeof c);
    (void)joyhid_cop_calls(&c, 0, 1, gJoyHidBindings.cop);
    (void)joyhid_cop_calls(&c, key, 1, gJoyHidBindings.cop);
    calls = joyhid_cop_calls(&c, key, 1, gJoyHidBindings.cop);
    n = pressed(key, calls, JOYHID_LAYOUT_COP, help);
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
    expect(helpglyph_map(trigger, JOYHID_LAYOUT_COP), icon, what);
}

// Changed bindings: the presses and the glyphs both follow.
static void rebound(void)
{
    unsigned char help[16];

    // The racer's throttle on ZR: shift up takes A, ZR's old action's key.
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_THROTTLE, JOYHID_BIND_ZR);
    expect(gJoyHidBindings.racer[JOYHID_ACT_SHIFTUP], JOYHID_BIND_A,
           "bind: the throttle's old key goes to shift up");
    expect(pressed(JOYHID_ZR, 0, JOYHID_LAYOUT_RACE, help) == 1
           && help[0] == 0x86, 1, "bind: ZR is the throttle");
    expect(pressed(JOYHID_A, 0, JOYHID_LAYOUT_RACE, help) == 1
           && help[0] == 0x8d, 1, "bind: A is shift up");
    expect(helpglyph_map(0x86, JOYHID_LAYOUT_RACE), ICON(HELPGLYPH_3DS_ZR),
           "bind: Cross draws as ZR");
    expect(helpglyph_map(0x8d, JOYHID_LAYOUT_RACE), ICON(HELPGLYPH_3DS_A),
           "bind: R2 draws as A");
    // The cop's untouched.
    expect(helpglyph_map(0x86, JOYHID_LAYOUT_COP), ICON(HELPGLYPH_3DS_A),
           "bind: the cop's throttle is still A");

    // The cop's helicopter on D-pad Up: the HUD takes R.
    joyhid_bind(gJoyHidBindings.cop, JOYHID_ACT_HELICOPTER, JOYHID_BIND_DUP);
    expect(gJoyHidBindings.cop[JOYHID_ACT_HUD], JOYHID_BIND_R,
           "bind: the HUD takes R");
    expect(helpglyph_map(0x8c, JOYHID_LAYOUT_COP), 0x82,
           "bind: the helicopter draws as Up");
    expect(helpglyph_map(0x82, JOYHID_LAYOUT_COP), ICON(HELPGLYPH_3DS_R),
           "bind: the HUD draws as R");
    expect(pressed(JOYHID_DUP, 0, JOYHID_LAYOUT_COP, help), 0,
           "bind: Up presses nothing of its own");
    cop_call(JOYHID_DUP, 0x8c, 0x82, "Up, the helicopter");

    // An action onto NONE: its key presses nothing, its glyph is retail's.
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_HORN, JOYHID_BIND_NONE);
    expect(gJoyHidBindings.racer[JOYHID_ACT_HORN], JOYHID_BIND_NONE,
           "bind: the horn on no key");
    expect(pressed(JOYHID_X, 0, JOYHID_LAYOUT_RACE, help), 0,
           "bind: X presses nothing");
    expect(helpglyph_map(0x89, JOYHID_LAYOUT_RACE), 0x89,
           "bind: Circle keeps retail's glyph");
    // A key onto an action whose key is NONE: the old holder gets NONE.
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_HORN, JOYHID_BIND_R);
    expect(gJoyHidBindings.racer[JOYHID_ACT_EBRAKE], JOYHID_BIND_NONE,
           "bind: the e-brake gives R up");
    expect(joyhid_bindings_valid(&gJoyHidBindings), 1,
           "bind: still one key an action");
    // Out of range is no key; a bad action is nothing.
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_HORN, 42);
    expect(gJoyHidBindings.racer[JOYHID_ACT_HORN], JOYHID_BIND_NONE,
           "bind: key 42 is no key");
    {
        JoyHidBindings before = gJoyHidBindings;

        joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_COUNT, JOYHID_BIND_Y);
        joyhid_bind(gJoyHidBindings.cop, -1, JOYHID_BIND_Y);
        expect(memcmp(&before, &gJoyHidBindings, sizeof before) == 0, 1,
               "bind: a bad action changes nothing");
    }
    race_keys(JOYHID_LAYOUT_RACE, "RACE rebound");
    race_keys(JOYHID_LAYOUT_COP, "COP rebound");

    joyhid_default_bindings(&gJoyHidBindings);
    expect(gJoyHidBindings.cop[JOYHID_ACT_BOOST], JOYHID_BIND_ZL,
           "defaults: the cop's boost is ZL");
    expect(gJoyHidBindings.racer[JOYHID_ACT_THROTTLE], JOYHID_BIND_A,
           "defaults: the racer's throttle is A");
}

static void valid(void)
{
    JoyHidBindings b;

    joyhid_default_bindings(&b);
    expect(joyhid_bindings_valid(&b), 1, "valid: the defaults");
    b.cop[JOYHID_ACT_EBRAKE] = JOYHID_BIND_A;
    expect(joyhid_bindings_valid(&b), 0, "valid: A twice");
    joyhid_default_bindings(&b);
    b.racer[JOYHID_ACT_BOOST] = JOYHID_BIND_KEYS;
    expect(joyhid_bindings_valid(&b), 0, "valid: key 10");
    b.racer[JOYHID_ACT_BOOST] = JOYHID_BIND_DDOWN;
    expect(joyhid_bindings_valid(&b), 1, "valid: the racer's boost on Down");
    memset(&b, JOYHID_BIND_NONE, sizeof b);
    expect(joyhid_bindings_valid(&b), 1, "valid: nothing bound");
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
    snprintf(what, sizeof what, "%s: L2 is ZL", name);
    expect(helpglyph_map(0x8c, layout), ICON(HELPGLYPH_3DS_ZL), what);
    snprintf(what, sizeof what, "%s: R2 is ZR", name);
    expect(helpglyph_map(0x8d, layout), ICON(HELPGLYPH_3DS_ZR), what);
    snprintf(what, sizeof what, "%s: R3 is D-pad Down's", name);
    expect(helpglyph_map(0x8f, layout), 0x83, what);

    // Circle has no frontend key of main.c's, so it is joyhid's: the key
    // that presses it in this layout.
    {
        uint32_t      key = layout == JOYHID_LAYOUT_FE ? JOYHID_B : JOYHID_Y;
        int32_t       icon = key == JOYHID_B ? HELPGLYPH_3DS_B
                                             : HELPGLYPH_3DS_Y;
        unsigned char help[16];
        int           n = pressed(key, 0, layout, help);

        snprintf(what, sizeof what, "%s: %s presses Circle", name,
                 key == JOYHID_B ? "B" : "Y");
        expect(n == 1 && help[0] == 0x89, 1, what);
        snprintf(what, sizeof what, "%s: Circle draws as %s", name,
                 key == JOYHID_B ? "B" : "Y");
        expect(helpglyph_map(0x89, layout), ICON(icon), what);
    }
}

// Retail's stick glyphs (joyeventid.h). joyhid_build puts the Circle Pad on
// the DualShock's left stick and the C-Stick on its right.
static const struct {
    int  glyph;
    int  icon;
} kSticks[] = {
    { JOY_LSTICK_UPDOWN,    HELPGLYPH_3DS_CPAD },
    { JOY_LSTICK_UP,        HELPGLYPH_3DS_CPAD },
    { JOY_LSTICK_DOWN,      HELPGLYPH_3DS_CPAD },
    { JOY_LSTICK_LEFTRIGHT, HELPGLYPH_3DS_CPAD },
    { JOY_RSTICK_UPDOWN,    HELPGLYPH_3DS_CSTICK },
    { JOY_RSTICK_UP,        HELPGLYPH_3DS_CSTICK },
    { JOY_RSTICK_DOWN,      HELPGLYPH_3DS_CSTICK },
    { JOY_RSTICK_LEFTRIGHT, HELPGLYPH_3DS_CSTICK },
};

static int is_stick(int c)
{
    for (size_t i = 0; i < sizeof kSticks / sizeof kSticks[0]; i++)
        if (kSticks[i].glyph == c)
            return 1;
    return 0;
}

// What every layout shares: START, SELECT, the D-pad's Left and Right,
// and the rest drawn as retail draws them, the sticks as the 3DS's. (Up,
// Down and R3 are the bindings' in a race; the menus' are checked above.)
static void shared(int32_t layout, const char *name)
{
    char what[96];

    for (int c = 0x80; c <= 0x9d; c++) {
        if ((c >= 0x86 && c <= 0x8d) || c == 0x8f || is_stick(c))
            continue;
        if (c == 0x82 && layout != JOYHID_LAYOUT_MENU
            && layout != JOYHID_LAYOUT_FE)
            continue;
        snprintf(what, sizeof what, "%s: 0x%02x drawn as retail's", name, c);
        expect(helpglyph_map((unsigned char)c, layout), c, what);
    }
    for (size_t i = 0; i < sizeof kSticks / sizeof kSticks[0]; i++) {
        snprintf(what, sizeof what, "%s: stick glyph 0x%02x", name,
                 kSticks[i].glyph);
        expect(helpglyph_map((unsigned char)kSticks[i].glyph, layout),
               ICON(kSticks[i].icon), what);
    }
}

static void keys(void)
{
    for (int32_t k = JOYHID_BIND_A; k <= JOYHID_BIND_ZR; k++)
        expect(helpglyph_key(k), ICON(k), "key: the sheet's icon");
    expect(helpglyph_key(JOYHID_BIND_DUP), 0x82, "key: Up");
    expect(helpglyph_key(JOYHID_BIND_DDOWN), 0x83, "key: Down");
    expect(helpglyph_key(JOYHID_BIND_NONE), -1, "key: none");
    for (int32_t k = 0; k < JOYHID_BIND_KEYS; k++)
        expect(joyhid_key_bind(joyhid_bind_key(k)), k, "key: and back");
    expect(joyhid_key_bind(JOYHID_START), JOYHID_BIND_NONE,
           "key: START is no bind key");
    expect((int32_t)joyhid_bind_key(JOYHID_BIND_NONE), 0, "key: none's bit");
    expect((int32_t)joyhid_bind_key(JOYHID_BIND_KEYS), 0, "key: 10's bit");
    expect((int32_t)joyhid_bind_key(-1), 0, "key: -1's bit");
}

// HELPGLYPH_LAYOUT_KEYS, the Controller page's: each bind key's character
// draws as that key, whatever the bindings say, and R3 (no key) as itself.
static void keys_layout(void)
{
    char what[64];

    for (int32_t k = 0; k < JOYHID_BIND_KEYS; k++) {
        unsigned char c = helpglyph_key_char(k);

        snprintf(what, sizeof what, "KEYS: %s's character", kKeyName[k]);
        expect(c != 0, 1, what);
        snprintf(what, sizeof what, "KEYS: %s draws as itself", kKeyName[k]);
        expect(helpglyph_map(c, HELPGLYPH_LAYOUT_KEYS), helpglyph_key(k),
               what);
    }
    expect(helpglyph_key_char(JOYHID_BIND_NONE), 0, "KEYS: none's character");
    expect(helpglyph_key_char(JOYHID_BIND_KEYS), 0, "KEYS: 10's character");
    expect(helpglyph_key_char(-1), 0, "KEYS: -1's character");
    expect(helpglyph_map(0x8f, HELPGLYPH_LAYOUT_KEYS), 0x8f, "KEYS: R3");
    // Rebinding moves nothing on the page's glyphs.
    joyhid_bind(gJoyHidBindings.racer, JOYHID_ACT_THROTTLE, JOYHID_BIND_ZR);
    expect(helpglyph_map(0x86, HELPGLYPH_LAYOUT_KEYS), ICON(HELPGLYPH_3DS_A),
           "KEYS: Cross is A, rebound or not");
    joyhid_default_bindings(&gJoyHidBindings);
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
    defaults();
    cop_call(JOYHID_L, 0x8d, ICON(HELPGLYPH_3DS_L), "L, the roadblock");
    cop_call(JOYHID_R, 0x8c, ICON(HELPGLYPH_3DS_R), "R, the helicopter");
    rebound();
    valid();
    keys();
    menus(JOYHID_LAYOUT_MENU, "MENU");
    menus(JOYHID_LAYOUT_FE, "FE");
    shared(JOYHID_LAYOUT_MENU, "MENU");
    shared(JOYHID_LAYOUT_RACE, "RACE");
    shared(JOYHID_LAYOUT_COP, "COP");
    shared(JOYHID_LAYOUT_FE, "FE");
    shared(HELPGLYPH_LAYOUT_KEYS, "KEYS");
    keys_layout();
    rewrite();

    if (failures) {
        printf("helpglyph: %d failed\n", failures);
        return 1;
    }
    printf("helpglyph: ok\n");
    return 0;
}
