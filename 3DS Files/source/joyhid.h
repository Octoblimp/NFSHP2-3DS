// joyhid -- the 3DS's buttons as a DualShock 2, for joypad.c's gJoypadRead.
//
// The joystick layer is the PS2's from end to end: 231 ScannerConfigTable
// rows read bits of a DualShock 2's 32-byte buffer and raise the game's
// events. Rather than a second table for the 3DS, this builds that buffer
// out of hidKeysHeld and the two sticks, in pressure mode (0x79, type 121),
// so every row and every user configuration works unchanged and the
// options screen's five layouts still mean what they say.
//
// The map, 3DS -> DualShock 2, and what configuration 30 (the default for
// type 121) makes of it:
//
//     A          Cross     menu select, throttle
//     B          Square    menu square, brake
//     X          Triangle  menu back, camera (on release), combo modifier
//     Y          Circle    menu help, horn
//     -- while a race runs, X and Y swap: X is Circle, the horn (a cop
//        car's lights and siren), and Y is Triangle, the camera and the
//        combo modifier. The user asked for the horn on X (2026-10-09);
//        the menus, the pause screen and the rest keep the layout above.
//     L / R      L1 / R1   look back / e-brake
//     ZL / ZR    L2 / R2   shift down / up; with X (Y racing) held, zone
//                          and pursuit
//     D-pad      D-pad     menus, digital steer; Up cycles the HUD
//     D-pad Down also R3   nitro -- nothing in a menu reads R3
//     -- in a Be A Cop race, in the cop's car, D-pad Left and Right stop
//        steering (the Circle Pad steers) and call the helicopter and the
//        roadblock, retail's TRIANGLE + L2 and TRIANGLE + R2 (12m-3, the
//        user's plan of 2026-10-08); see joyhid_cop_keys.
//     START      START
//     SELECT     SELECT
//     Circle Pad left stick   steering, menu analog
//     C-Stick    right stick  alternate throttle (up) and brake (down)
//
// A and B are throttle and brake because they sit next to each other, as
// Cross and Square do; the price is that "back" in the frontend is X, the
// Triangle, and not B. The twelve pressure bytes read 255 for a held button
// and 0 otherwise -- the 3DS's buttons are digital. ZL, ZR and the C-Stick
// exist only on a New 3DS; an Old 3DS reads them as never pressed and
// centred, which leaves the D-pad's digital steer and automatic gears.
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

typedef struct JoyHidState {
    uint32_t keys;      // hidKeysHeld()
    int32_t  cx, cy;    // the Circle Pad, +y up
    int32_t  sx, sy;    // the C-Stick, +y up; 0 on an Old 3DS
    int32_t  race;      // a JOYHID_LAYOUT_*; any but MENU swaps X and Y
} JoyHidState;

// The layouts gJoyHidRaceLayoutFn answers.
#define JOYHID_LAYOUT_MENU 0    // the map above
#define JOYHID_LAYOUT_RACE 1    // X and Y swapped: X the horn
#define JOYHID_LAYOUT_COP  2    // the race's, and the D-pad's cop calls

// The layout, asked once a reading; NULL is always MENU. main.c's answers
// RACE while the race coordinator is in RACE_IN_PROGRESS, and COP then in
// a Be A Cop race when player 1's car is the player cop's.
extern int32_t (*gJoyHidRaceLayoutFn)(void);

// Be A Cop's D-pad, kept from one reading to the next.
typedef struct JoyHidCop {
    uint32_t last;      // D-pad Left and Right as held at the last reading
    uint32_t combo;     // JOYHID_ZL or JOYHID_ZR, while a call runs
    int32_t  step;      // 0 idle, else the call's next reading, 1 to 3
} JoyHidCop;

// One reading's keys, with `on` for the COP layout. A new press of D-pad
// Left calls the helicopter and one of Right the roadblock, over three
// readings: Y (the race layout's Triangle); Y and ZL or ZR, the combo;
// Y alone, so the trigger lets go behind Triangle's veto and shifts
// nothing. Triangle lets go on the reading after, which raises the camera
// change; the request's handler holds that off for a second, as it does
// for the combo pressed by hand. D-pad Left and Right are dropped, so they
// do not steer, and a press during a call is not kept. With `on` 0 the
// keys pass unchanged and only what is held is noted, so a key held into
// the COP layout calls nothing.
uint32_t joyhid_cop_keys(JoyHidCop *c, uint32_t keys, int32_t on);

// The DualShock 2 buffer for one reading.
void joyhid_build(const JoyHidState *s, uint8_t buf[32]);

// gJoypadRead: port 0 is the console, port 1 is left empty (all zero,
// which ReadRegularController answers -1 for -- nothing plugged in).
// Reads hidKeysHeld, so it wants hidScanInput to have run this frame.
void joyhid_read(int32_t port, uint8_t *buf);

// gJoypadRead = joyhid_read.
void joyhid_install(void);

#endif
