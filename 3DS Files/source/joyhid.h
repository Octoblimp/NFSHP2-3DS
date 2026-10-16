// joyhid -- the 3DS's buttons as a DualShock 2, for joypad.c's gJoypadRead.
//
// The joystick layer is the PS2's from end to end: 231 ScannerConfigTable
// rows read bits of a DualShock 2's 32-byte buffer and raise the game's
// events. Rather than a second table for the 3DS, this builds that buffer
// out of hidKeysHeld and the two sticks, in pressure mode (0x79, type 121),
// so every row and every user configuration works unchanged and the
// options screen's five layouts still mean what they say.
//
// The menus' map, 3DS -> DualShock 2, and what configuration 30 (the
// default for type 121) makes of it:
//
//     A          Cross     menu select
//     B          Square    menu square
//     X          Triangle  menu back
//     Y          Circle    menu help
//     -- in the frontend, with no race, B and Y swap: Y is Square, car
//        select's orbit view, as main.c's own menu keys have Y as Square
//        and B as back.
//     L / R      L1 / R1
//     ZL / ZR    L2 / R2
//     D-pad      D-pad     menus
//     D-pad Down also R3   nothing in a menu reads R3
//     START      START
//     SELECT     SELECT
//     Circle Pad left stick   menu analog
//
// While a race runs (the RACE and COP layouts) ten keys -- A, B, X, Y, L,
// R, ZL, ZR and D-pad Up and Down -- press what the player bound them to
// (JoyHidBindings, one table for a racer and one for the cop's car), and
// each action presses its configuration 30 button. The defaults:
//
//     action        button        racer     cop
//     throttle      Cross         A         A
//     brake         Square        B         B
//     e-brake       R1            R         --
//     horn / siren  Circle        X         X (the target)
//     camera        Triangle      Y         Y (on release; the combos)
//     look back     L1            L         --
//     shift up      R2            ZR        ZR
//     shift down    L2            ZL        D-pad Down
//     cycle HUD     D-pad Up      D-pad Up  D-pad Up
//     nitro boost   R3            --        ZL
//     roadblock     Triangle+R2   --        L
//     helicopter    Triangle+L2   --        R
//
// The user's map: the horn on X (2026-10-09), the cop's calls on L and R
// (2026-10-11), the cop's boost on ZL (2026-10-16), and every key
// changeable (Options' Controller). Racing or not, D-pad Left and Right
// steer, START pauses, SELECT is SELECT, the Circle Pad is the left stick
// (steering) and the C-Stick the right (alternate throttle up, brake
// down). Camera held with shift down or up is retail's combo, the zone
// freeze and zoom.
//
// A and B are throttle and brake because they sit next to each other, as
// Cross and Square do; the price is that the scanners' "back" is X, the
// Triangle, and not B (main.c's frontend keys take B as back). The twelve
// pressure bytes read 255 for a held button and 0 otherwise -- the 3DS's
// buttons are digital. ZL, ZR and the C-Stick exist only on a New 3DS; an
// Old 3DS reads them as never pressed and centred, which leaves the
// D-pad's digital steer and automatic gears.
//
// See docs/formats/joystick.md.

#ifndef JOYHID_H
#define JOYHID_H

#include <stdint.h>

// libctru's KEY_* bits, for the host build that has no 3ds.h; joyhid.c
// holds them to the real ones on the 3DS.
#define JOYHID_A      (1u << 0)
#define JOYHID_B      (1u << 1)
#define JOYHID_SELECT (1u << 2)
#define JOYHID_START  (1u << 3)
#define JOYHID_DRIGHT (1u << 4)
#define JOYHID_DLEFT  (1u << 5)
#define JOYHID_DUP    (1u << 6)
#define JOYHID_DDOWN  (1u << 7)
#define JOYHID_R      (1u << 8)
#define JOYHID_L      (1u << 9)
#define JOYHID_X      (1u << 10)
#define JOYHID_Y      (1u << 11)
#define JOYHID_ZL     (1u << 14)
#define JOYHID_ZR     (1u << 15)

// The stick reading at which a DualShock 2 axis reaches 0 or 255. The
// Circle Pad's nominal reach is 156 but a worn one, or a diagonal, falls
// short of it, and the menus' analog rows want 8 or 248 before they fire.
#define JOYHID_STICK_FULL 144

// DualShock 2 buttons as bits of bytes 2-3 (pressed is 1 here; the buffer
// has them active low): the three a Be A Cop call presses.
#define JOYHID_DS2_L2       (1u << 8)
#define JOYHID_DS2_R2       (1u << 9)
#define JOYHID_DS2_TRIANGLE (1u << 12)

typedef struct JoyHidState {
    uint32_t keys;      // hidKeysHeld()
    int32_t  cx, cy;    // the Circle Pad, +y up
    int32_t  sx, sy;    // the C-Stick, +y up; 0 on an Old 3DS
    int32_t  race;      // a JOYHID_LAYOUT_*
    uint32_t calls;     // JOYHID_DS2_* bits, joyhid_cop_calls's
} JoyHidState;

// The layouts gJoyHidRaceLayoutFn answers.
#define JOYHID_LAYOUT_MENU 0    // the map above
#define JOYHID_LAYOUT_RACE 1    // the racer's bindings
#define JOYHID_LAYOUT_COP  2    // the cop's bindings and calls
#define JOYHID_LAYOUT_FE   3    // B and Y swapped: Y Square, car select's
                                // orbit view (bcarsel.c), as kBinds has Y

// The layout, asked once a reading; NULL is always MENU. main.c's answers
// RACE while the race coordinator is in RACE_IN_PROGRESS, and COP then in
// a Be A Cop race when player 1's car is the player cop's; FE when there
// is no race coordinator.
extern int32_t (*gJoyHidRaceLayoutFn)(void);

// ----------------------------------------------------------- the bindings

// What a key does in a race, each the configuration 30 button it presses.
#define JOYHID_ACT_THROTTLE   0     // Cross
#define JOYHID_ACT_BRAKE      1     // Square
#define JOYHID_ACT_EBRAKE     2     // R1
#define JOYHID_ACT_HORN       3     // Circle
#define JOYHID_ACT_CAMERA     4     // Triangle
#define JOYHID_ACT_LOOKBACK   5     // L1
#define JOYHID_ACT_SHIFTUP    6     // R2
#define JOYHID_ACT_SHIFTDOWN  7     // L2
#define JOYHID_ACT_HUD        8     // D-pad Up
#define JOYHID_ACT_BOOST      9     // R3
#define JOYHID_ACT_ROADBLOCK  10    // Triangle + R2, a call (COP only)
#define JOYHID_ACT_HELICOPTER 11    // Triangle + L2, a call (COP only)
#define JOYHID_ACT_COUNT      12

// The keys a race lets the player bind, in the order of the help sheet's
// first eight icons (helpglyph.h's HELPGLYPH_3DS_*), then D-pad Up and
// Down.
#define JOYHID_BIND_A      0
#define JOYHID_BIND_B      1
#define JOYHID_BIND_X      2
#define JOYHID_BIND_Y      3
#define JOYHID_BIND_L      4
#define JOYHID_BIND_R      5
#define JOYHID_BIND_ZL     6
#define JOYHID_BIND_ZR     7
#define JOYHID_BIND_DUP    8
#define JOYHID_BIND_DDOWN  9
#define JOYHID_BIND_KEYS   10
#define JOYHID_BIND_NONE   0xff     // the action has no key

// The key each action is on: one table for a racer (RACE) and one for the
// cop's car (COP). A key is on at most one action of a table.
typedef struct JoyHidBindings {
    uint8_t racer[JOYHID_ACT_COUNT];
    uint8_t cop[JOYHID_ACT_COUNT];
} JoyHidBindings;

// The bindings joyhid_build and helpglyph read; the defaults until a
// save's controls file says otherwise (main.c).
extern JoyHidBindings gJoyHidBindings;

// The map at the top of this file.
void joyhid_default_bindings(JoyHidBindings *b);

// 1 if every entry of `b` is a JOYHID_BIND_* or NONE and no key is on two
// actions of a table: what a file read back must be before it is used.
int32_t joyhid_bindings_valid(const JoyHidBindings *b);

// `action` onto `key` (or NONE) in `table`. An action that had `key`
// takes `action`'s old key, so a table stays one key an action.
void joyhid_bind(uint8_t table[JOYHID_ACT_COUNT], int32_t action,
                 int32_t key);

// The JOYHID_* bit of bind key `k`, 0 for NONE or anything else.
uint32_t joyhid_bind_key(int32_t k);

// The bind key of a single JOYHID_* bit, or JOYHID_BIND_NONE.
int32_t joyhid_key_bind(uint32_t key);

// Be A Cop's calls, kept from one reading to the next.
typedef struct JoyHidCop {
    uint32_t last;      // the call keys as held at the last reading
    uint32_t combo;     // JOYHID_DS2_L2 or R2, while a call runs
    int32_t  step;      // 0 idle, else the call's next reading, 1 to 3
} JoyHidCop;

// One reading's calls, with `on` for the COP layout and `table` the cop's
// bindings: the DualShock buttons to add to the reading (JoyHidState's
// `calls`). A new press of the roadblock's key calls it, and of the
// helicopter's the helicopter, over three readings: Triangle; Triangle
// and R2 or L2, retail's combo; Triangle alone, so the trigger lets go
// behind Triangle's veto and shifts nothing. Triangle lets go on the
// reading after, which raises the camera change; the request's handler
// holds that off for a second, as it does for the combo pressed by hand.
// Both at once is the helicopter, and a press during a call is not kept.
// With `on` 0 nothing is added and only what is held is noted, so a key
// held into the COP layout calls nothing.
uint32_t joyhid_cop_calls(JoyHidCop *c, uint32_t keys, int32_t on,
                          const uint8_t table[JOYHID_ACT_COUNT]);

// The Circle Pad in the menus (TASKS 42), kept from one reading to the
// next: the D-pad direction it holds, or 0.
typedef struct JoyHidMenuPad {
    uint32_t held;      // JOYHID_DUP, DDOWN, DLEFT or DRIGHT, or 0
} JoyHidMenuPad;

// The stick reading past which the Circle Pad presses a D-pad direction
// in the menus, and the one under which it lets go. The gap keeps a
// stick resting near the edge from pressing over and over.
#define JOYHID_MENU_PRESS   96
#define JOYHID_MENU_RELEASE 48

// One reading of the Circle Pad (+y up) as the menus' D-pad: the
// direction newly pressed, or 0. The farther axis picks the direction
// once the stick is past JOYHID_MENU_PRESS on it, and that direction is
// held until its axis falls under JOYHID_MENU_RELEASE, so a push is one
// press, as the D-pad's is, with no repeat while it is held.
uint32_t joyhid_menu_pad(JoyHidMenuPad *p, int32_t cx, int32_t cy);

// The DualShock 2 buffer for one reading: the menus' map in MENU and FE,
// gJoyHidBindings' racer or cop table and `calls` in RACE and COP.
void joyhid_build(const JoyHidState *s, uint8_t buf[32]);

// The buffer again from bytes 2 to 7 of one joyhid_build made, as a
// wireless race's lockstep sends a pad (netstep.h): the buttons and the
// sticks, with each pressure byte 255 where its button is down. So
// from_wire(build's bytes 2 to 7) is build's buffer.
void joyhid_from_wire(const uint8_t six[6], uint8_t buf[32]);

// gJoypadRead: port 0 is the console and answers 1; port 1 answers 0,
// nothing plugged in (joypad.c fills its read with 0xff, as retail's
// failed scePadRead is). Reads hidKeysHeld, so it wants hidScanInput to
// have run this frame; the cop's calls go through joyhid_cop_calls with
// the cop's table.
int32_t joyhid_read(int32_t port, uint8_t *buf);

// gJoypadRead = joyhid_read.
void joyhid_install(void);

#endif
