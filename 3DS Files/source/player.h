// player -- the head of Player, which RealDriver, RealController and Car
// read, and two of the class's statics.
//
// Player is 2480 bytes (.mdebug type#2091) and task 26's. RealDriver needs
// one field of it, PlayerNumber, for the view its nitro blur is drawn in;
// RealController needs bWrongWay at 736, which turns its route prediction
// off; Car's catchup reads PlayerNumber and the other player's MyCar.
// Car::FinishMovement reads nZoneCurrent, the camera zone the player is
// in, and keeps the jump cam's highest point in EyeVerts[2].z. RenderCars
// finds a view's player by ViewID and reads its zone. This names the six
// words up to ViewID, then those three over holes. The
// struct is left open at the end like replay.h's: nothing in the port
// allocates a Player yet, and a partial layout would invite something to.
//
// The holes are the same size on every target. Between 80 and 1600 the
// stab has dozens of pointers (the camera movers, the NIS manager, pRoute,
// the flailers, ...), so a full layout on a 64-bit host would put
// bWrongWay and EyeVerts further along than this does. Nothing on the host
// but a checker's harness builds a Player, and it builds this one. The
// first hole, 20 to 76, has none: ViewID, RearViewMirrorViewID, the 40
// bytes of PlayerSettings, TimeFinishedRacing and FinishAnimationLength.
// Retail keeps ViewID at 24 and nZoneCurrent at 88; the port keeps the
// demo's offsets, as it does for every struct nothing reads in place.

#ifndef PLAYER_H
#define PLAYER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "joystick.h"

struct Car;

struct Player {
    void        (*NisFinishedCallback)(void *);  //    0
    struct Car   *MyCar;                         //    4
    JoystickPort  JoyPort;                       //    8
    int32_t       JoyType;                       //   12
    int32_t       PlayerNumber;                  //   16  0 or 1; the view
    int32_t       ViewID;                        //   20  the eView's ID
    uint8_t       _hole24[52];                   //   24  RearViewMirrorViewID .. FinishAnimationLength
    int32_t       nZoneCurrent;                  //   76  the camera zone, 0 for none
    uint8_t       _hole80[656];                  //   80  nZonePrevious .. ArrestCameraNumbers
    int32_t       bWrongWay;                     //  736
    uint8_t       _hole740[860];                 //  740  bLookBack .. myCD
    bVector3      EyeVerts[3];                   // 1600  the jump cam's
    // ... to 2480.
};

// Two pointers lead, so a 64-bit host moves everything after them by
// eight bytes. The term carries that.
#define PLAYER_SLACK ((size_t)(sizeof(void *) - 4))

typedef char player_layout_check[
    (offsetof(struct Player, JoyPort) == 8 + 2 * PLAYER_SLACK
     && offsetof(struct Player, PlayerNumber) == 16 + 2 * PLAYER_SLACK
     && offsetof(struct Player, ViewID) == 20 + 2 * PLAYER_SLACK
     && offsetof(struct Player, nZoneCurrent) == 76 + 2 * PLAYER_SLACK
     && offsetof(struct Player, bWrongWay) == 736 + 2 * PLAYER_SLACK
     && offsetof(struct Player, EyeVerts) == 1600 + 2 * PLAYER_SLACK)
    ? 1 : -1];

// Player::NumPlayers, 0x003237e0 (gp-21520), and Player::pPlayersByNumber,
// 0x003237d0 (gp-21536), the players by PlayerNumber. Player's constructor
// keeps them; until it is ported, whatever builds the players sets them.
// Car's catchup reads both and tests neither entry for NULL.
extern int32_t        PlayerNumPlayers;
extern struct Player *PlayerPlayersByNumber[2];

// Player::pPlayersByIndex, 0x003237d8 (gp-21528; retail's gp-20928), the
// players in the order they were made. RenderCars tests each entry for
// NULL.
extern struct Player *PlayerPlayersByIndex[2];

#endif
