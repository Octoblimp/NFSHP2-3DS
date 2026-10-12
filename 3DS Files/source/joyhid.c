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

static const struct {
    uint32_t key;
    uint8_t  button;
    int8_t   pressure;
} kMap[] = {
    { JOYHID_A,      DS2_CROSS,    P_CROSS },
    { JOYHID_B,      DS2_SQUARE,   P_SQUARE },
    { JOYHID_X,      DS2_TRIANGLE, P_TRIANGLE },
    { JOYHID_Y,      DS2_CIRCLE,   P_CIRCLE },
    { JOYHID_L,      DS2_L1,       P_L1 },
    { JOYHID_R,      DS2_R1,       P_R1 },
    { JOYHID_ZL,     DS2_L2,       P_L2 },
    { JOYHID_ZR,     DS2_R2,       P_R2 },
    { JOYHID_DRIGHT, DS2_RIGHT,    P_RIGHT },
    { JOYHID_DLEFT,  DS2_LEFT,     P_LEFT },
    { JOYHID_DUP,    DS2_UP,       P_UP },
    { JOYHID_DDOWN,  DS2_DOWN,     P_DOWN },
    { JOYHID_DDOWN,  DS2_R3,       P_NONE },
    { JOYHID_START,  DS2_START,    P_NONE },
    { JOYHID_SELECT, DS2_SELECT,   P_NONE },
};

int32_t (*gJoyHidRaceLayoutFn)(void);

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

uint32_t joyhid_cop_keys(JoyHidCop *c, uint32_t keys, int32_t on)
{
    uint32_t lr = keys & (JOYHID_L | JOYHID_R);
    uint32_t pressed = lr & ~c->last;

    c->last = lr;
    if (!on) {
        c->step = 0;
        return keys;
    }
    keys &= ~(JOYHID_L | JOYHID_R);
    if (c->step == 0 && pressed != 0) {
        // Both at once: R, the helicopter.
        c->combo = (pressed & JOYHID_R) != 0 ? JOYHID_ZL : JOYHID_ZR;
        c->step = 1;
    }
    if (c->step != 0) {
        keys |= JOYHID_Y;
        if (c->step == 2)
            keys |= c->combo;
        c->step = c->step == 3 ? 0 : c->step + 1;
    }
    return keys;
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

void joyhid_build(const JoyHidState *s, uint8_t buf[32])
{
    uint32_t buttons = 0xffff;   // active low
    uint32_t keys = s->keys;
    size_t i;

    // The race layout: X reads as Y (Circle, the horn) and Y as X.
    if (s->race == JOYHID_LAYOUT_RACE || s->race == JOYHID_LAYOUT_COP)
        keys = swapKeys(keys, JOYHID_X, JOYHID_Y);
    // The frontend's: Y reads as B (Square, as the menus' own Y is) and B
    // as Y, so car select's orbit view is Y's and B only the menus' back.
    if (s->race == JOYHID_LAYOUT_FE)
        keys = swapKeys(keys, JOYHID_B, JOYHID_Y);

    memset(buf, 0, 32);
    buf[1] = 0x79;
    for (i = 0; i < sizeof(kMap) / sizeof(kMap[0]); i++) {
        if (!(keys & kMap[i].key))
            continue;
        buttons &= ~(1u << kMap[i].button);
        if (kMap[i].pressure != P_NONE)
            buf[8 + kMap[i].pressure] = 255;
    }
    buf[2] = (uint8_t)buttons;
    buf[3] = (uint8_t)(buttons >> 8);
    // The DualShock's Y axes are 0 at the top; the 3DS's are +y up.
    buf[4] = axis(s->sx);
    buf[5] = axis(-s->sy);
    buf[6] = axis(s->cx);
    buf[7] = axis(-s->cy);
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
    s.keys = joyhid_cop_keys(&cop, s.keys, s.race == JOYHID_LAYOUT_COP);
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
