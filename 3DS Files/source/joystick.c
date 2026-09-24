// joystick -- see joystick.h.

#include "joystick.h"

uint8_t CurrentJoystickTypes[JOYSTICK_PORTS];   // 0x00323448

int32_t GetJoystickType(JoystickPort port)
{
    return CurrentJoystickTypes[port];
}

int32_t IsJoystickTypeWheel(JoystickPort port)
{
    switch (GetJoystickType(port)) {
    case 21:
    case 22:
    case 35:
        return 1;
    default:
        return 0;
    }
}

int32_t DoesJoystickHaveStiffThrottle(JoystickPort port)
{
    switch (GetJoystickType(port)) {
    case 83:
    case 115:
    case 121:
        return 1;
    default:
        return 0;
    }
}
