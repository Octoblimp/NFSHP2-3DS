// joypad -- see joypad.h.

#include "joypad.h"

#include <string.h>

JoyData PadRingData[JOYSTICK_PORTS][JOYPAD_RING];
int32_t JoystickRingBufferTop;
int32_t JoystickRingBufferBottom;
int32_t JoystickRingBufferPreparedTop;
int32_t JoypadInitialised;
int32_t JoypadPortState[JOYSTICK_PORTS];

JoypadReadFn gJoypadRead;

void ReadJoystickData(void)
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
        if (gJoypadRead)
            gJoypadRead(port, (uint8_t *)d->ThePadData);
    }
    JoystickRingBufferTop = next;
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

void PrepareToGetJoystickData(void)
{
    int32_t i;
    int32_t port;

    // UpdateLogitechWheels would run here.
    JoystickRingBufferPreparedTop = JoystickRingBufferTop;
    i = JoystickRingBufferBottom;
    if (i == JoystickRingBufferPreparedTop)
        return;
    do {
        for (port = 0; port < JOYSTICK_PORTS; port++) {
            JoyData *d = &PadRingData[port][i];

            d->RegularControllerType =
                ReadRegularController(port, d, &JoypadPortState[port]);
            // GetWheelDevice(port) is NULL: there is no wheel.
            d->LogitechDeviceID = -1;
        }
        i = (i + 1) & (JOYPAD_RING - 1);
    } while (i != JoystickRingBufferPreparedTop);
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

int32_t ReadRegularController(int32_t port, const JoyData *d, int32_t *state)
{
    const uint8_t *b = (const uint8_t *)d->ThePadData;

    (void)port;
    (void)state;
    if (b[0] != 0 || b[1] == 0)
        return -1;
    return b[1];
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
