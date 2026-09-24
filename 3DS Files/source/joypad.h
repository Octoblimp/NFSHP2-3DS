// joypad -- the platform half of the joystick: JoystickPS2.obj's ring of
// pad reads (0x0011d150 .. 0x0011da60 in NFSHP2.ELF), with the 3DS's
// buttons where the PS2 had libpad.
//
// The PS2 reads both pads from its vertical-blank interrupt, ReadJoystick-
// Data into a 32-deep ring per port, so a frame that runs long does not
// drop a press; the main loop then drains every read since the last frame
// through GenerateJoyEvents. The ring, the drain and the type-and-data
// lookup are ported as they are. What changes is the read: the 3DS has no
// vblank handler here, so main.c calls ReadJoystickData itself once a frame
// just before GenerateJoyEvents, and the read is gJoypadRead, which builds
// the DualShock 2's 32 bytes out of the 3DS's buttons (joyhid.c). Every
// scanner and every config row downstream then works unchanged.
//
// The DualShock 2 buffer, as ScannerConfigTable's bit numbers read it:
//
//     byte 0     0 on a good read
//     byte 1     the mode: 0x79 is a DualShock 2 in pressure mode
//     bytes 2-3  the sixteen buttons, active low (bit 16 SELECT .. 31 SQUARE)
//     bytes 4-7  right stick X, Y, left stick X, Y; 128 is the centre
//     bytes 8-19 the twelve pressures, 0 released .. 255 hard
//
// Not ported: the Logitech wheel layer (UpdateLogitechWheels,
// GetWheelDevice and ConvertLogitechToDualShock) -- the 3DS has no wheel,
// so LogitechDeviceID is always -1 -- and the joystick monkey, a debug
// feature the retail build never turns on.
//
// See docs/formats/joystick.md.

#ifndef JOYPAD_H
#define JOYPAD_H

#include <stddef.h>
#include <stdint.h>

#include "joystick.h"

// 84 bytes, PadRingData[2][32] at 0x002de480.
typedef struct JoyData {
    uint32_t ThePadData[8];            // 0, the 32-byte buffer
    int32_t  Bytes;                    // 32, never written
    int32_t  RegularControllerType;    // 36
    int32_t  LogitechDeviceID;         // 40, -1 for no wheel
    uint8_t  LogitechDescription[24];  // 44
    uint8_t  LogitechPosition[16];     // 68
} JoyData;

typedef char joydata_layout_check[
    (sizeof(JoyData) == 84 && offsetof(JoyData, LogitechDeviceID) == 40
     && offsetof(JoyData, LogitechPosition) == 68) ? 1 : -1];

#define JOYPAD_RING 32

extern JoyData PadRingData[JOYSTICK_PORTS][JOYPAD_RING];  // 0x002de480
extern int32_t JoystickRingBufferTop;                     // gp-24328
extern int32_t JoystickRingBufferBottom;                  // gp-24324
extern int32_t JoystickRingBufferPreparedTop;             // gp-24320
extern int32_t JoypadInitialised;                         // gp-24316
extern int32_t JoypadPortState[JOYSTICK_PORTS];           // gp-24296

// scePadRead's place: fill the 32-byte buffer for one port. NULL leaves it
// zero, which ReadRegularController reads as nothing plugged in.
typedef void (*JoypadReadFn)(int32_t port, uint8_t *buf);
extern JoypadReadFn gJoypadRead;

// 0x0011d150. One read of both ports into the ring, unless the ring is
// full or the pads were never opened.
void ReadJoystickData(void);

// 0x0011d200 / 0x0011d218.
int32_t IsThereJoystickData(void);
void    AdvanceJoystickData(void);

// 0x0011d230. Fixes how far this frame will drain, and works out the
// controller type of every read up to there.
void PrepareToGetJoystickData(void);

// 0x0011d360. The read at the bottom of the ring for `port`, the one
// before it through `data2`, and its type through `type`.
const uint32_t *GetJoystickTypeAndData(int32_t port, int32_t *type,
                                       const uint32_t **data2);

// 0x0011d420, the PS2's libpad state machine. What it answers once a pad
// has settled is the mode byte if the read was good, and -1 otherwise;
// the 3DS pad is always settled, so that is all this does.
int32_t ReadRegularController(int32_t port, const JoyData *d, int32_t *state);

// 0x0011d9e0 / 0x0011da60. Open the pads; closing does nothing.
void PlatformInitJoystick(void);
void PlatformCloseJoystick(void);

#endif
