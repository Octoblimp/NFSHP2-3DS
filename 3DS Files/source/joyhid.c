// joyhid -- see joyhid.h.

#include "joyhid.h"

#include <string.h>

#include "joypad.h"

#ifdef __3DS__
#include <3ds.h>

typedef char joyhid_key_check[
    (JOYHID_A == KEY_A && JOYHID_B == KEY_B && JOYHID_SELECT == KEY_SELECT
     && JOYHID_START == KEY_START && JOYHID_DRIGHT == KEY_DRIGHT
     && JOYHID_DLEFT == KEY_DLEFT && JOYHID_DUP == KEY_DUP
     && JOYHID_DDOWN == KEY_DDOWN && JOYHID_R == KEY_R && JOYHID_L == KEY_L
     && JOYHID_X == KEY_X && JOYHID_Y == KEY_Y && JOYHID_ZL == KEY_ZL
     && JOYHID_ZR == KEY_ZR) ? 1 : -1];
#endif

// The sixteen buttons, as bits of bytes 2-3 (ScannerConfigTable's shift
// less 16), and the twelve pressures, as bytes after byte 8.
enum {
    DS2_SELECT, DS2_L3, DS2_R3, DS2_START,
    DS2_UP, DS2_RIGHT, DS2_DOWN, DS2_LEFT,
    DS2_L2, DS2_R2, DS2_L1, DS2_R1,
    DS2_TRIANGLE, DS2_CIRCLE, DS2_CROSS, DS2_SQUARE,
};
enum {
    P_RIGHT, P_LEFT, P_UP, P_DOWN, P_TRIANGLE, P_CIRCLE, P_CROSS, P_SQUARE,
    P_L1, P_R1, P_L2, P_R2, P_NONE = -1,
};

typedef char joyhid_ds2_check[
    (JOYHID_DS2_L2 == 1u << DS2_L2 && JOYHID_DS2_R2 == 1u << DS2_R2
     && JOYHID_DS2_TRIANGLE == 1u << DS2_TRIANGLE) ? 1 : -1];

// Each button's pressure byte, by DS2_*.
static const int8_t kPressure[16] = {
    [DS2_SELECT] = P_NONE, [DS2_L3] = P_NONE, [DS2_R3] = P_NONE,
    [DS2_START] = P_NONE, [DS2_UP] = P_UP, [DS2_RIGHT] = P_RIGHT,
    [DS2_DOWN] = P_DOWN, [DS2_LEFT] = P_LEFT, [DS2_L2] = P_L2,
    [DS2_R2] = P_R2, [DS2_L1] = P_L1, [DS2_R1] = P_R1,
    [DS2_TRIANGLE] = P_TRIANGLE, [DS2_CIRCLE] = P_CIRCLE,
    [DS2_CROSS] = P_CROSS, [DS2_SQUARE] = P_SQUARE,
};

// The menus' map.
static const struct {
    uint32_t key;
    uint8_t  button;
} kMap[] = {
    { JOYHID_A,      DS2_CROSS },
    { JOYHID_B,      DS2_SQUARE },
    { JOYHID_X,      DS2_TRIANGLE },
    { JOYHID_Y,      DS2_CIRCLE },
    { JOYHID_L,      DS2_L1 },
    { JOYHID_R,      DS2_R1 },
    { JOYHID_ZL,     DS2_L2 },
    { JOYHID_ZR,     DS2_R2 },
    { JOYHID_DRIGHT, DS2_RIGHT },
    { JOYHID_DLEFT,  DS2_LEFT },
    { JOYHID_DUP,    DS2_UP },
    { JOYHID_DDOWN,  DS2_DOWN },
    { JOYHID_DDOWN,  DS2_R3 },
    { JOYHID_START,  DS2_START },
    { JOYHID_SELECT, DS2_SELECT },
};

// A race's keys that no binding moves.
static const struct {
    uint32_t key;
    uint8_t  button;
} kFixed[] = {
    { JOYHID_DRIGHT, DS2_RIGHT },
    { JOYHID_DLEFT,  DS2_LEFT },
    { JOYHID_START,  DS2_START },
    { JOYHID_SELECT, DS2_SELECT },
};

// The button each JOYHID_ACT_* presses; the calls press theirs through
// joyhid_cop_calls, so here they are none.
#define DS2_NONE 0xff
static const uint8_t kActionButton[JOYHID_ACT_COUNT] = {
    [JOYHID_ACT_THROTTLE]   = DS2_CROSS,
    [JOYHID_ACT_BRAKE]      = DS2_SQUARE,
    [JOYHID_ACT_EBRAKE]     = DS2_R1,
    [JOYHID_ACT_HORN]       = DS2_CIRCLE,
    [JOYHID_ACT_CAMERA]     = DS2_TRIANGLE,
    [JOYHID_ACT_LOOKBACK]   = DS2_L1,
    [JOYHID_ACT_SHIFTUP]    = DS2_R2,
    [JOYHID_ACT_SHIFTDOWN]  = DS2_L2,
    [JOYHID_ACT_HUD]        = DS2_UP,
    [JOYHID_ACT_BOOST]      = DS2_R3,
    [JOYHID_ACT_ROADBLOCK]  = DS2_NONE,
    [JOYHID_ACT_HELICOPTER] = DS2_NONE,
};

// The JOYHID_* bit of each JOYHID_BIND_*.
static const uint32_t kBindKey[JOYHID_BIND_KEYS] = {
    JOYHID_A, JOYHID_B, JOYHID_X, JOYHID_Y, JOYHID_L, JOYHID_R,
    JOYHID_ZL, JOYHID_ZR, JOYHID_DUP, JOYHID_DDOWN,
};

// The map in joyhid.h.
#define N JOYHID_BIND_NONE
#define DEFAULTS {                                      \
    .racer = {                                          \
        [JOYHID_ACT_THROTTLE]   = JOYHID_BIND_A,        \
        [JOYHID_ACT_BRAKE]      = JOYHID_BIND_B,        \
        [JOYHID_ACT_EBRAKE]     = JOYHID_BIND_R,        \
        [JOYHID_ACT_HORN]       = JOYHID_BIND_X,        \
        [JOYHID_ACT_CAMERA]     = JOYHID_BIND_Y,        \
        [JOYHID_ACT_LOOKBACK]   = JOYHID_BIND_L,        \
        [JOYHID_ACT_SHIFTUP]    = JOYHID_BIND_ZR,       \
        [JOYHID_ACT_SHIFTDOWN]  = JOYHID_BIND_ZL,       \
        [JOYHID_ACT_HUD]        = JOYHID_BIND_DUP,      \
        [JOYHID_ACT_BOOST]      = N,                    \
        [JOYHID_ACT_ROADBLOCK]  = N,                    \
        [JOYHID_ACT_HELICOPTER] = N,                    \
    },                                                  \
    .cop = {                                            \
        [JOYHID_ACT_THROTTLE]   = JOYHID_BIND_A,        \
        [JOYHID_ACT_BRAKE]      = JOYHID_BIND_B,        \
        [JOYHID_ACT_EBRAKE]     = N,                    \
        [JOYHID_ACT_HORN]       = JOYHID_BIND_X,        \
        [JOYHID_ACT_CAMERA]     = JOYHID_BIND_Y,        \
        [JOYHID_ACT_LOOKBACK]   = N,                    \
        [JOYHID_ACT_SHIFTUP]    = JOYHID_BIND_ZR,       \
        [JOYHID_ACT_SHIFTDOWN]  = JOYHID_BIND_DDOWN,    \
        [JOYHID_ACT_HUD]        = JOYHID_BIND_DUP,      \
        [JOYHID_ACT_BOOST]      = JOYHID_BIND_ZL,       \
        [JOYHID_ACT_ROADBLOCK]  = JOYHID_BIND_L,        \
        [JOYHID_ACT_HELICOPTER] = JOYHID_BIND_R,        \
    },                                                  \
}
static const JoyHidBindings kDefaults = DEFAULTS;
JoyHidBindings gJoyHidBindings = DEFAULTS;
#undef DEFAULTS
#undef N

int32_t (*gJoyHidRaceLayoutFn)(void);

void joyhid_default_bindings(JoyHidBindings *b)
{
    *b = kDefaults;
}

static int32_t table_valid(const uint8_t t[JOYHID_ACT_COUNT])
{
    uint32_t used = 0;
    int32_t  a;

    for (a = 0; a < JOYHID_ACT_COUNT; a++) {
        if (t[a] == JOYHID_BIND_NONE)
            continue;
        if (t[a] >= JOYHID_BIND_KEYS || (used & 1u << t[a]))
            return 0;
        used |= 1u << t[a];
    }
    return 1;
}

int32_t joyhid_bindings_valid(const JoyHidBindings *b)
{
    return table_valid(b->racer) && table_valid(b->cop);
}

void joyhid_bind(uint8_t table[JOYHID_ACT_COUNT], int32_t action,
                 int32_t key)
{
    uint8_t old;
    int32_t a;

    if (action < 0 || action >= JOYHID_ACT_COUNT)
        return;
    if (key < 0 || key >= JOYHID_BIND_KEYS)
        key = JOYHID_BIND_NONE;
    old = table[action];
    if (key != JOYHID_BIND_NONE)
        for (a = 0; a < JOYHID_ACT_COUNT; a++)
            if (a != action && table[a] == key)
                table[a] = old;
    table[action] = (uint8_t)key;
}

int32_t joyhid_bind_keeps_drive(const uint8_t table[JOYHID_ACT_COUNT],
                                int32_t action, int32_t key)
{
    uint8_t t[JOYHID_ACT_COUNT];

    memcpy(t, table, sizeof t);
    joyhid_bind(t, action, key);
    return t[JOYHID_ACT_THROTTLE] != JOYHID_BIND_NONE
        && t[JOYHID_ACT_BRAKE] != JOYHID_BIND_NONE;
}

static const uint8_t kFileMagic[4] = { 'H', 'P', '2', 'K' };

void joyhid_bindings_pack(const JoyHidBindings *b,
                          uint8_t out[JOYHID_FILE_SIZE])
{
    memcpy(out, kFileMagic, sizeof kFileMagic);
    out[4] = JOYHID_FILE_VERSION;
    out[5] = JOYHID_ACT_COUNT;
    memcpy(out + 6, b->racer, JOYHID_ACT_COUNT);
    memcpy(out + 6 + JOYHID_ACT_COUNT, b->cop, JOYHID_ACT_COUNT);
}

int32_t joyhid_bindings_unpack(const uint8_t *in, uint32_t n,
                               JoyHidBindings *b)
{
    JoyHidBindings got;

    if (in == NULL || n != JOYHID_FILE_SIZE
        || memcmp(in, kFileMagic, sizeof kFileMagic) != 0
        || in[4] != JOYHID_FILE_VERSION || in[5] != JOYHID_ACT_COUNT)
        return 0;
    memcpy(got.racer, in + 6, JOYHID_ACT_COUNT);
    memcpy(got.cop, in + 6 + JOYHID_ACT_COUNT, JOYHID_ACT_COUNT);
    if (!joyhid_bindings_valid(&got))
        return 0;
    *b = got;
    return 1;
}

uint32_t joyhid_bind_key(int32_t k)
{
    return k >= 0 && k < JOYHID_BIND_KEYS ? kBindKey[k] : 0;
}

int32_t joyhid_key_bind(uint32_t key)
{
    int32_t k;

    for (k = 0; k < JOYHID_BIND_KEYS; k++)
        if (kBindKey[k] == key)
            return k;
    return JOYHID_BIND_NONE;
}

// `keys` with keys `a` and `b` read as each other.
static uint32_t swapKeys(uint32_t keys, uint32_t a, uint32_t b)
{
    uint32_t ab = keys & (a | b);

    keys &= ~(a | b);
    if (ab & a)
        keys |= b;
    if (ab & b)
        keys |= a;
    return keys;
}

// -JOYHID_STICK_FULL .. +JOYHID_STICK_FULL onto 0 .. 255, 128 the centre.
static uint8_t axis(int32_t v)
{
    int32_t a = 128 + v * 128 / JOYHID_STICK_FULL;

    return (uint8_t)(a < 0 ? 0 : a > 255 ? 255 : a);
}

uint32_t joyhid_cop_calls(JoyHidCop *c, uint32_t keys, int32_t on,
                          const uint8_t table[JOYHID_ACT_COUNT])
{
    uint32_t road = joyhid_bind_key(table[JOYHID_ACT_ROADBLOCK]);
    uint32_t heli = joyhid_bind_key(table[JOYHID_ACT_HELICOPTER]);
    uint32_t held = keys & (road | heli);
    uint32_t pressed = held & ~c->last;
    uint32_t calls = 0;

    c->last = held;
    if (!on) {
        c->step = 0;
        return 0;
    }
    if (c->step == 0 && pressed != 0) {
        // Both at once: the helicopter.
        c->combo = (pressed & heli) != 0 ? JOYHID_DS2_L2 : JOYHID_DS2_R2;
        c->step = 1;
    }
    if (c->step != 0) {
        calls = JOYHID_DS2_TRIANGLE;
        if (c->step == 2)
            calls |= c->combo;
        c->step = c->step == 3 ? 0 : c->step + 1;
    }
    return calls;
}

uint32_t joyhid_menu_pad(JoyHidMenuPad *p, int32_t cx, int32_t cy)
{
    int32_t  ax = cx < 0 ? -cx : cx;
    int32_t  ay = cy < 0 ? -cy : cy;
    uint32_t was = p->held;

    if (p->held == JOYHID_DLEFT || p->held == JOYHID_DRIGHT) {
        if (ax < JOYHID_MENU_RELEASE)
            p->held = 0;
    } else if (p->held != 0) {
        if (ay < JOYHID_MENU_RELEASE)
            p->held = 0;
    }
    if (p->held == 0) {
        if (ax >= ay && ax > JOYHID_MENU_PRESS)
            p->held = cx < 0 ? JOYHID_DLEFT : JOYHID_DRIGHT;
        else if (ay > ax && ay > JOYHID_MENU_PRESS)
            p->held = cy < 0 ? JOYHID_DDOWN : JOYHID_DUP;
    }
    return p->held != was ? p->held : 0;
}

// The buttons a race's keys press, by `table`'s bindings, as bits (1
// pressed).
static uint32_t race_buttons(uint32_t keys,
                             const uint8_t table[JOYHID_ACT_COUNT])
{
    uint32_t down = 0;
    size_t   i;
    int32_t  a;

    for (a = 0; a < JOYHID_ACT_COUNT; a++)
        if (kActionButton[a] != DS2_NONE
            && (keys & joyhid_bind_key(table[a])))
            down |= 1u << kActionButton[a];
    for (i = 0; i < sizeof(kFixed) / sizeof(kFixed[0]); i++)
        if (keys & kFixed[i].key)
            down |= 1u << kFixed[i].button;
    return down;
}

void joyhid_build(const JoyHidState *s, uint8_t buf[32])
{
    uint32_t keys = s->keys;
    uint32_t down = 0;
    size_t i;

    if (s->race == JOYHID_LAYOUT_RACE || s->race == JOYHID_LAYOUT_COP) {
        down = race_buttons(keys, s->race == JOYHID_LAYOUT_COP
                                      ? gJoyHidBindings.cop
                                      : gJoyHidBindings.racer);
        down |= s->calls & 0xffff;
    } else {
        // The frontend's: X reads as B (Square, as the menus' own X is)
        // and B as X (Triangle, the menus' back), so car select's orbit
        // view is X's and Y stays Circle, the help.
        if (s->race == JOYHID_LAYOUT_FE)
            keys = swapKeys(keys, JOYHID_B, JOYHID_X);
        for (i = 0; i < sizeof(kMap) / sizeof(kMap[0]); i++)
            if (keys & kMap[i].key)
                down |= 1u << kMap[i].button;
    }

    memset(buf, 0, 32);
    buf[1] = 0x79;
    for (i = 0; i < 16; i++)
        if ((down & 1u << i) && kPressure[i] != P_NONE)
            buf[8 + kPressure[i]] = 255;
    // Active low.
    buf[2] = (uint8_t)~down;
    buf[3] = (uint8_t)(~down >> 8);
    // The DualShock's Y axes are 0 at the top; the 3DS's are +y up.
    buf[4] = axis(s->sx);
    buf[5] = axis(-s->sy);
    buf[6] = axis(s->cx);
    buf[7] = axis(-s->cy);
}

void joyhid_from_wire(const uint8_t six[6], uint8_t buf[32])
{
    uint32_t buttons = (uint32_t)six[0] | (uint32_t)six[1] << 8;
    size_t i;

    memset(buf, 0, 32);
    buf[1] = 0x79;
    memcpy(buf + 2, six, 6);
    for (i = 0; i < 16; i++)
        if (!(buttons & 1u << i) && kPressure[i] != P_NONE)
            buf[8 + kPressure[i]] = 255;
}

int32_t joyhid_read(int32_t port, uint8_t *buf)
{
#ifdef __3DS__
    static JoyHidCop cop;
    JoyHidState s;
    circlePosition cp;
    circlePosition cs;

    if (port != 0)
        return 0;
    hidCircleRead(&cp);
    hidCstickRead(&cs);
    s.keys = hidKeysHeld();
    s.cx = cp.dx;
    s.cy = cp.dy;
    s.sx = cs.dx;
    s.sy = cs.dy;
    s.race = gJoyHidRaceLayoutFn != NULL ? gJoyHidRaceLayoutFn()
                                         : JOYHID_LAYOUT_MENU;
    s.calls = joyhid_cop_calls(&cop, s.keys, s.race == JOYHID_LAYOUT_COP,
                               gJoyHidBindings.cop);
    joyhid_build(&s, buf);
    return 1;
#else
    (void)port;
    (void)buf;
    return 0;
#endif
}

void joyhid_install(void)
{
    gJoypadRead = joyhid_read;
}
