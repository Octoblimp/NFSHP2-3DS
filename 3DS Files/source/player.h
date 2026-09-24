// player -- the head of Player, which RealDriver and RealController read.
//
// Player is 2480 bytes (.mdebug type#2091) and task 26's. RealDriver needs
// one field of it, PlayerNumber, for the view its nitro blur is drawn in;
// RealController needs bWrongWay at 736, which turns its route prediction
// off. This names the five words up to PlayerNumber, then jumps to
// bWrongWay over a hole. The struct is left open at the end like
// replay.h's: nothing in the port allocates a Player yet, and a partial
// layout would invite something to.
//
// The hole is 716 bytes on every target. Between 20 and 736 the stab has
// at least ten pointers (the camera movers, the NIS manager, pRoute, ...),
// so a full layout on a 64-bit host would put bWrongWay further along than
// this does. Nothing on the host but a checker's harness builds a Player,
// and it builds this one.

#ifndef PLAYER_H
#define PLAYER_H

#include <stddef.h>
#include <stdint.h>

#include "joystick.h"

struct Car;

struct Player {
    void        (*NisFinishedCallback)(void *);  //  0
    struct Car   *MyCar;                         //  4
    JoystickPort  JoyPort;                       //  8
    int32_t       JoyType;                       // 12
    int32_t       PlayerNumber;                  // 16  0 or 1; the view
    uint8_t       _hole20[716];                  // 20  ViewID .. ArrestCameraNumbers
    int32_t       bWrongWay;                     // 736
    // ... to 2480.
};

// Two pointers lead, so a 64-bit host moves everything after them by
// eight bytes. The term carries that.
#define PLAYER_SLACK ((size_t)(sizeof(void *) - 4))

typedef char player_layout_check[
    (offsetof(struct Player, JoyPort) == 8 + 2 * PLAYER_SLACK
     && offsetof(struct Player, PlayerNumber) == 16 + 2 * PLAYER_SLACK
     && offsetof(struct Player, bWrongWay) == 736 + 2 * PLAYER_SLACK)
    ? 1 : -1];

#endif
