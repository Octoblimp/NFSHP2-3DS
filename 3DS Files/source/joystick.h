// joystick -- which kind of controller is in each port.
//
// The PS2 build knows a set of controller type codes, among them steering
// wheels, and the driving code treats a wheel differently: PhysicsCar::Move
// skips its burn-out logic for a player on a wheel. The handheld has one
// controller and it is not a wheel, so on the 3DS every entry here stays
// 0, a code IsJoystickTypeWheel answers false for, and the burn-out is
// reachable as it is for a pad.

#ifndef JOYSTICK_H
#define JOYSTICK_H

#include <stdint.h>

// 12JoystickPort, a plain index. RealDriver's constructor stores -1.
typedef int32_t JoystickPort;

#define JOYSTICK_PORTS 2

// gp-22440, 0x00323448: one byte per pad port, two in all -- the symbol is
// 2 bytes, and the 6 after it up to bShakeTest are alignment. The input
// system writes a type code per port; nothing in the port does yet.
extern uint8_t CurrentJoystickTypes[JOYSTICK_PORTS];

// 0x00151320. `lbu v0,0(a0+CurrentJoystickTypes)`, no bounds check -- a
// port of -1 reads the byte before the table.
int32_t GetJoystickType(JoystickPort port);

// 0x0011db70. True for the three wheel codes, 21, 22 and 35. The switch
// the compiler built also tests 65, 83, 115 and 121, and every one of
// those arms returns false.
int32_t IsJoystickTypeWheel(JoystickPort port);

// 0x0011daf8. True for 83, 115 and 121 -- the pads whose analog pedal
// travels a quarter as far, which RealDriver's throttle and reverse
// handlers read four times over. Its only two callers.
int32_t DoesJoystickHaveStiffThrottle(JoystickPort port);

#endif
