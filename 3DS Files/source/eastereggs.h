// eastereggs -- TheEasterEggs, the main menu's code reader, and its 78
// cheat codes (TASKS 50).
//
// New in retail (the demo has no such class), and unnamed: the ELF has no
// symbols for it, so every name here is the port's. There is one object,
// at 0x0031d7e8, which retail's __CTOR_LIST__ entry 99 builds (0x0024fa60;
// the demo's list, which sinit.c follows, has no such entry, so main.c
// calls eastereggs_construct after sinit_run). Its codes are the table at
// 0x0031d828.
//
//   0x0024f420  the constructor: the table and its 78, the flags zeroed
//   0x0024f460  the destructor (the static one, 0x0024fa50, at exit)
//   0x0024f488  Start: a handler for each of the pad's sixteen button
//               events, 133..148 on port 0 (NewMainMenu's constructor)
//   0x0024f610  Stop: the sixteen taken back (NewMainMenu's destructor)
//   0x0024f700  every code not kept turned off
//               (BeginGameFlowUnloadingTrackSpecific)
//   0x0024f748  a button pressed, through the handler 0x0024fa88
//   0x0024f8f0  the ring emptied
//   0x0024f8f8  a car's code (VisibleCarSet's constructor)
//   0x0024f930  a track's code (SelectableTrackManager::BuildList)
//   0x0024f9a0  a code's On, by its type and parameter
//   0x0024f9f8  every code of a group turned off
//   0x0024fa70  code n's On (inline at its readers: raceinit.h's EggIsOn)
//   0x0024faa8  the code just entered's LanguageID, its flag cleared
//               (inline in NewMainMenu::OnTick)
//   0x0024fab8  JustEntered; 0x0024fac0 IsActive; 0x0024fac8 Enable;
//               0x0024fad8 Disable (OnTick has its own stores)
//
// Not ported: 0x0024f968, a walk over the codes whose body is empty (a
// debug print compiled out), which OnTick calls when gp-16120 is set; and
// 0x0024fa48, the action a type-0 code calls with its Param, which is a
// bare `jr ra`.
//
// A code is eight presses of L1, L2, R1, R2, D-pad Left and Right, Square
// and Triangle: events 133..140, as joyeventid.h names them. On the main
// menu the 3DS keys for them are L, ZL, R, ZR, Left, Right, X and B
// (joyhid's frontend layout). What a code does is its Type:
//   0  egg n = Param, a race's: 0..4 and 8 the render eggs, 6 and 7 the
//      bonus events; 5, the pet helicopter, has no presses
//   1  car type Param, in every mode but You're The Cop
//   2  car type Param, in You're The Cop
//   3  track Param, forward
//   4  track Param, backward
// docs/formats/easter-eggs.md lists the 78. Nothing is saved: the codes
// live in memory, so they last until the game is turned off, and those
// not kept are off again after each race.
//
// tools/eastereggs_check.py runs retail's code on the same scripts.

#ifndef EASTEREGGS_H
#define EASTEREGGS_H

#include <stddef.h>
#include <stdint.h>

#include "joyevent.h"

#define EASTEREGGS_CODE_LENGTH 8
#define EASTEREGGS_NUM_CODES   78
#define EASTEREGGS_VTABLE      0x002bf470u

// The code types.
#define EASTEREGG_TYPE_EGG        0
#define EASTEREGG_TYPE_CAR        1
#define EASTEREGG_TYPE_COP_CAR    2
#define EASTEREGG_TYPE_TRACK      3
#define EASTEREGG_TYPE_TRACK_BACK 4

typedef struct EasterEggCode {
    JoyEvent Buttons[EASTEREGGS_CODE_LENGTH]; //  0  the presses, in order
    int32_t  Type;                            // 32  EASTEREGG_TYPE_*
    int32_t  Param;                           // 36
    // Entering a code first turns off every code of its group; 0 is none.
    // Group 1 is the five render eggs that cannot be on together.
    int32_t  Group;                           // 40
    int32_t  LanguageID;                      // 44  the name under "Unlocked"
    int32_t  On;                              // 48
    int32_t  Kept;                            // 52  0: off after each race
} EasterEggCode;                              // 56

typedef char eastereggcode_layout_check[
    (offsetof(EasterEggCode, Type) == 32
     && offsetof(EasterEggCode, LanguageID) == 44
     && offsetof(EasterEggCode, Kept) == 52
     && sizeof(EasterEggCode) == 56) ? 1 : -1];

typedef struct EasterEggs {
    int32_t        Active;      //  0  presses are read
    int32_t        JustEntered; //  4  a code matched since the last look
    int32_t        LanguageID;  //  8  that code's
    EasterEggCode *Codes;       // 12
    uint32_t       NumCodes;    // 16
    // The last presses: Count of them from Head, each slot (Head + i) & 7.
    JoyEvent       Ring[EASTEREGGS_CODE_LENGTH]; // 20
    uint32_t       Count;       // 52
    uint32_t       Head;        // 56
    uint32_t       vptr;        // 60  EASTEREGGS_VTABLE
} EasterEggs;                   // 64

// The pointer is 8 bytes on the 64-bit host, so only a 32-bit build
// checks the offsets after it.
#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char eastereggs_layout_check[
    (offsetof(EasterEggs, Codes) == 12 && offsetof(EasterEggs, Ring) == 20
     && offsetof(EasterEggs, Count) == 52
     && offsetof(EasterEggs, vptr) == 60
     && sizeof(EasterEggs) == 64) ? 1 : -1];
#endif

// 0x0031d7e8 and 0x0031d828.
extern EasterEggs    TheEasterEggs;
extern EasterEggCode TheEasterEggCodes[EASTEREGGS_NUM_CODES];

// 0x0024f420. Leaves the ring's slots as they were.
EasterEggs *eastereggs_construct(EasterEggs *e);

// 0x0024f488 and 0x0024f610.
void eastereggs_start(EasterEggs *e);
void eastereggs_stop(EasterEggs *e);

// 0x0024f8f0: Count to 0. Head stays.
void eastereggs_reset(EasterEggs *e);

// 0x0024f748, the handler's body; `port` and `value` are unread (every
// event is a press, Scanner_DigitalDown's). With the reader inactive the
// press is dropped. A press that finds the ring full empties it instead
// of going in. The eighth press compares the ring, from Head, with each
// code in turn: the first that matches has its group turned off, is
// turned on, sets JustEntered and LanguageID, and empties the ring.
// With no match the oldest press goes: Head on by one, Count back to 7.
void eastereggs_on_button(EasterEggs *e, JoystickPort port, JoyEvent ev,
                          uint8_t value);

// 0x0024fa88: the JoyHandler Start registers, `obj` the object.
void eastereggs_joy_handler(JoystickPort port, JoyEvent ev, uint8_t value,
                            void *obj);

// 0x0024f700: every code with Kept 0 turned off.
void eastereggs_clear_temporary(EasterEggs *e);

// 0x0024f9f8: every code of `group` turned off; group 0 does nothing.
void eastereggs_clear_group(EasterEggs *e, int32_t group);

// 0x0024f9a0: the On of the first code of that type and parameter, or 0.
int32_t eastereggs_is_on(EasterEggs *e, int32_t type, int32_t param);

// 0x0024f8f8: car type `car`'s code, type 2 if `cop` else 1.
int32_t eastereggs_car_on(EasterEggs *e, int32_t car, int32_t cop);

// 0x0024f930: track `track`'s code, type 4 if `backward` else 3.
int32_t eastereggs_track_on(EasterEggs *e, int32_t track, int32_t backward);

// 0x0024fa70: code n's On, unchecked.
int32_t eastereggs_egg_on(const EasterEggs *e, int32_t n);

// 0x0024faa8: LanguageID, with JustEntered cleared.
int32_t eastereggs_take_language_id(EasterEggs *e);

// 0x0024fab8, 0x0024fac0, 0x0024fac8 and 0x0024fad8.
int32_t eastereggs_just_entered(const EasterEggs *e);
int32_t eastereggs_is_active(const EasterEggs *e);
void    eastereggs_enable(EasterEggs *e);
void    eastereggs_disable(EasterEggs *e);

#endif
