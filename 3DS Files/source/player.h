// player -- the head of Player, which RealDriver, RealController and Car
// read, and two of the class's statics.
//
// Player is 2480 bytes (.mdebug type#2091) and task 26's. RealDriver needs
// one field of it, PlayerNumber, for the view its nitro blur is drawn in;
// RealController needs bWrongWay at 736, which turns its route prediction
// off; Car's catchup reads PlayerNumber and the other player's MyCar.
// Car::FinishMovement reads nZoneCurrent, the camera zone the player is
// in, and keeps the jump cam's highest point in EyeVerts[2].z. RenderCars
// finds a view's player by ViewID and reads its zone. The camera shake asks
// IsCameraPOVInCar, which reads pCameraMover and the settings' POV. This
// names the words up to PlayerSettings, then those four over holes. The
// struct is left open at the end like replay.h's: nothing in the port
// allocates a Player yet, and a partial layout would invite something to.
//
// The holes are the same size on every target. Between 80 and 1600 the
// stab has dozens of pointers (the camera movers, the NIS manager, pRoute,
// the flailers, ...), so a full layout on a 64-bit host would put
// bWrongWay and EyeVerts further along than this does. Nothing on the host
// but a checker's harness builds a Player, and it builds this one.
// Retail keeps ViewID at 24, nZoneCurrent at 88 and pCameraMover at 200;
// the port keeps the demo's offsets, as it does for every struct nothing
// reads in place.

#ifndef PLAYER_H
#define PLAYER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "joystick.h"
#include "timer.h"

struct Car;
struct CameraMover;

// cPlayerSettings, 40 bytes (.mdebug type#3426): what the player chose in
// the frontend. The seven one-byte fields are type 2, `char`, which the
// image loads with `lb`; type#31 is a 32-bit bit set and type#1884 twelve
// bytes, the name.
//
// Retail's word at 12 is an int, where the demo's was the float
// LookbackSpeed: ResetToDefaults (0x001edf90) makes it 1 and ToggleLookback
// (0x001ee2d8) turns 0 and 1 into each other and leaves anything else. The
// drive camera counts a look back only while it is 0. Retail's record is
// 48 bytes, with two more words it defaults to 1; the port keeps the
// demo's 40.
typedef struct cPlayerSettings {
    int8_t   PlayersHudState;                    //    0
    int8_t   Rumble;                             //    1
    int8_t   DrivingStyle;                       //    2
    int8_t   TransmissionType;                   //    3
    int8_t   DriveCameraPOVIndex;                //    4  the drive camera's POV
    int8_t   SplitTimeType;                      //    5
    int8_t   PreferredGender;                    //    6
    uint8_t  _pad7;                              //    7
    int32_t  CameraSpring;                       //    8
    int32_t  Lookback;                           //   12  retail's; see above
    uint32_t PreferredHudFeatures;               //   16
    char     PlayerName[12];                     //   20
    Timer    BestTotalTimeRecord;                //   32
    Timer    BestLapTimeRecord;                  //   36
} cPlayerSettings;                               //   40

struct Player {
    void        (*NisFinishedCallback)(void *);  //    0
    struct Car   *MyCar;                         //    4
    JoystickPort  JoyPort;                       //    8
    int32_t       JoyType;                       //   12
    int32_t       PlayerNumber;                  //   16  0 or 1; the view
    int32_t       ViewID;                        //   20  the eView's ID
    int32_t       RearViewMirrorViewID;          //   24
    cPlayerSettings PlayerSettings;              //   28
    uint8_t       _hole68[8];                    //   68  TimeFinishedRacing, FinishAnimationLength
    int32_t       nZoneCurrent;                  //   76  the camera zone, 0 for none
    uint8_t       _hole80[100];                  //   80  nZonePrevious .. PlayerInputMode
    struct CameraMover *pCameraMover;            //  180  the player's camera, or NULL
    uint8_t       _hole184[552];                 //  184  pSavedCameraMover .. ArrestCameraNumbers
    int32_t       bWrongWay;                     //  736
    uint8_t       _hole740[860];                 //  740  bLookBack .. myCD
    bVector3      EyeVerts[3];                   // 1600  the jump cam's
    // ... to 2480.
};

// Two pointers lead, so a 64-bit host moves everything after them by
// eight bytes, and pCameraMover then waits four more for its alignment.
// The multiples of the slack carry that.
#define PLAYER_SLACK ((size_t)(sizeof(void *) - 4))

typedef char player_layout_check[
    (offsetof(struct Player, JoyPort) == 8 + 2 * PLAYER_SLACK
     && offsetof(struct Player, PlayerNumber) == 16 + 2 * PLAYER_SLACK
     && offsetof(struct Player, ViewID) == 20 + 2 * PLAYER_SLACK
     && offsetof(struct Player, PlayerSettings) == 28 + 2 * PLAYER_SLACK
     && offsetof(struct Player, PlayerSettings.DriveCameraPOVIndex)
            == 32 + 2 * PLAYER_SLACK
     && offsetof(struct Player, nZoneCurrent) == 76 + 2 * PLAYER_SLACK
     && offsetof(struct Player, pCameraMover) == 180 + 3 * PLAYER_SLACK
     && offsetof(struct Player, bWrongWay) == 736 + 4 * PLAYER_SLACK
     && offsetof(struct Player, EyeVerts) == 1600 + 4 * PLAYER_SLACK)
    ? 1 : -1];

// Player::IsCameraPOVInCar, retail's 0x00178808 (the demo's 0x00172108;
// only the offsets changed). Whether the player's camera is the drive
// camera, enabled, with a CameraInfo, looking from the POV the settings
// pick, and that POV is POV_INCAR. The camera's own GetCameraInfo and
// GetPOV answer, through its vtable.
int32_t player_is_camera_pov_in_car(const struct Player *p);

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
