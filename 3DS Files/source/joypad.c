// joypad -- see joypad.h.

#include "joypad.h"

#include <string.h>

JoyData PadRingData[JOYSTICK_PORTS][JOYPAD_RING];
int32_t JoystickRingBufferTop;
int32_t JoystickRingBufferBottom;
int32_t JoystickRingBufferPreparedTop;
int32_t JoypadInitialised;
int32_t JoypadReadInVBlank;
int32_t JoypadPortState[JOYSTICK_PORTS];

JoypadReadFn gJoypadRead;

// Retail's 0x0011c950. scePadGetState is 6 (stable) or 2 for a pad libpad
// can read, and the 3DS's always is; a port that answers nothing is 0xff
// throughout, which reads as no controller.
static void read_pads(void)
{
    int32_t next;
    int32_t port;

    if (!JoypadInitialised)
        return;
    next = (JoystickRingBufferTop + 1) & (JOYPAD_RING - 1);
    if (next == JoystickRingBufferBottom)
        return;
    for (port = 0; port < JOYSTICK_PORTS; port++) {
        JoyData *d = &PadRingData[port][JoystickRingBufferTop];

        memset(d, 0, sizeof(*d));
        if (gJoypadRead == NULL || !gJoypadRead(port, (uint8_t *)d->ThePadData))
            memset(d, 0xff, sizeof(*d));
    }
    JoystickRingBufferTop = next;
}

void ReadJoystickData(void)
{
    if (JoypadReadInVBlank)
        read_pads();
}

int32_t IsThereJoystickData(void)
{
    return JoystickRingBufferBottom != JoystickRingBufferPreparedTop;
}

void AdvanceJoystickData(void)
{
    JoystickRingBufferBottom = (JoystickRingBufferBottom + 1)
                               & (JOYPAD_RING - 1);
}

// Retail's 0x0011d058: the mode byte of a good read, else -1.
static int32_t pad_type(const JoyData *d)
{
    const uint8_t *b = (const uint8_t *)d->ThePadData;

    if (b[0] != 0 || b[1] == 0)
        return -1;
    return b[1];
}

void PrepareToGetJoystickData(void)
{
    int32_t port;

    // UpdateLogitechWheels would run here.
    if (!JoypadReadInVBlank)
        read_pads();
    JoystickRingBufferPreparedTop = JoystickRingBufferTop;
    if (JoystickRingBufferBottom == JoystickRingBufferPreparedTop)
        return;
    for (port = 0; port < JOYSTICK_PORTS; port++) {
        int32_t rc = ReadRegularController(port, &JoypadPortState[port]);
        int32_t i = JoystickRingBufferBottom;

        do {
            JoyData *d = &PadRingData[port][i];

            d->RegularControllerType = rc == -1 ? -1 : pad_type(d);
            // GetWheelDevice(port) is NULL: there is no wheel.
            d->LogitechDeviceID = -1;
            i = (i + 1) & (JOYPAD_RING - 1);
        } while (i != JoystickRingBufferPreparedTop);
        // Retail sends a rumble change waiting for the port here
        // (scePadSetActDirect); the 3DS has no motor.
    }
}

const uint32_t *GetJoystickTypeAndData(int32_t port, int32_t *type,
                                       const uint32_t **data2)
{
    int32_t b = JoystickRingBufferBottom;
    JoyData *cur = &PadRingData[port][b];

    *data2 = PadRingData[port][(b - 1) & (JOYPAD_RING - 1)].ThePadData;
    // A wheel (LogitechDeviceID != -1) would answer 21 or 22 here and
    // convert its reading into the DualShock layout in place.
    *type = cur->RegularControllerType;
    return cur->ThePadData;
}

int32_t ReadRegularController(int32_t port, int32_t *state)
{
    (void)port;
    (void)state;
    return 0;
}

void PlatformInitJoystick(void)
{
    int32_t port;

    // scePadInit, the wheel library, and scePadPortOpen on both ports.
    for (port = 0; port < JOYSTICK_PORTS; port++)
        JoypadPortState[port] = 0;
    JoypadInitialised = 1;
}

void PlatformCloseJoystick(void)
{
}
