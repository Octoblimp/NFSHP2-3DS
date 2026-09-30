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
// IsCameraPOVInCar, which reads pCameraMover and the settings' POV. The
// camera functions in playercam.c read the movers, the coordinators, the
// NIS manager, pRoute, pVisibleDrivingLine and bLookBack. This names the
// words up to PlayerSettings, then those over holes, to the demo's 2480
// bytes. Player's constructor is task 26's.
//
// The holes are the same size on every target. Between 80 and 1600 the
// stab has dozens more pointers (the flailers, ...), so a full layout on a
// 64-bit host would put bWrongWay and EyeVerts further along than this
// does. Nothing on the host but a checker's harness builds a Player, and
// it builds this one. Retail keeps ViewID at 24, nZoneCurrent at 88 and
// pCameraMover at 200; the port keeps the demo's offsets, as it does for
// every struct nothing reads in place.
//
// Retail has one camera word the demo lacks, at 208: a second saved
// mover. ChangeCameraMover with `keep` moves pSavedCameraMover into it
// before saving the old mover, and RestoreCameraMover moves it back. It
// goes at the end here, as car.h's new fields do, so every demo offset
// above still holds.

#ifndef PLAYER_H
#define PLAYER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "joystick.h"
#include "timer.h"

struct Car;
struct CameraMover;
struct CountdownCameraCoordinator;
struct DemoCameraCoordinator;
struct NisCameraCoordinator;
struct NisManager;
struct PreviewRoute;
struct VisibleDrivingLine;

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
    uint8_t       _hole80[44];                   //   80  nZonePrevious .. tAutoZoneTimers
    struct PreviewRoute *pRoute;                 //  124  the zone preview's route
    uint8_t       _hole128[52];                  //  128  pZoneSample .. PlayerInputMode
    struct CameraMover *pCameraMover;            //  180  the player's camera, or NULL
    struct CameraMover *pSavedCameraMover;       //  184  the last one kept
    struct CameraMover *pRVMCameraMover;         //  188  the rear-view mirror's
    struct DemoCameraCoordinator *pDemoCameraCoordinator;           //  192
    struct CountdownCameraCoordinator *pCountdownCameraCoordinator; //  196
    struct NisCameraCoordinator *pNisCameraCoordinator;             //  200
    struct VisibleDrivingLine *pVisibleDrivingLine; // 204
    uint8_t       _hole208[12];                  //  208  ArrestNisIndex .. NisFinishedCallbackParam
    struct NisManager *pNisManager;              //  220
    uint8_t       _hole224[512];                 //  224  TicketNisNumbers .. ArrestCameraNumbers
    int32_t       bWrongWay;                     //  736
    int32_t       bLookBack;                     //  740  a drive camera starts looking back
    uint8_t       _hole744[856];                 //  744  CurrentHudFeatures .. myCD
    bVector3      EyeVerts[3];                   // 1600  the jump cam's
    uint8_t       _hole1648[832];                // 1648  BankVerts .. the end

    // Retail's (at 208); see above.
    struct CameraMover *pSavedCameraMover2;      // 2480  the one kept before that
};

// Two pointers lead, so a 64-bit host moves everything after them by
// eight bytes. Each pointer after that adds four more, and pRoute,
// pCameraMover and pNisManager wait four more for their alignment. The
// multiples of the slack carry that.
#define PLAYER_SLACK ((size_t)(sizeof(void *) - 4))
#define PLAYER_AT(f, n, k) \
    (offsetof(struct Player, f) == (size_t)(n) + (k) * PLAYER_SLACK)

typedef char player_layout_check[
    (PLAYER_AT(JoyPort, 8, 2)
     && PLAYER_AT(PlayerNumber, 16, 2)
     && PLAYER_AT(ViewID, 20, 2)
     && PLAYER_AT(PlayerSettings, 28, 2)
     && PLAYER_AT(PlayerSettings.DriveCameraPOVIndex, 32, 2)
     && PLAYER_AT(PlayerSettings.CameraSpring, 36, 2)
     && PLAYER_AT(nZoneCurrent, 76, 2)
     && PLAYER_AT(pRoute, 124, 3)
     && PLAYER_AT(pCameraMover, 180, 5)
     && PLAYER_AT(pSavedCameraMover, 184, 6)
     && PLAYER_AT(pRVMCameraMover, 188, 7)
     && PLAYER_AT(pDemoCameraCoordinator, 192, 8)
     && PLAYER_AT(pCountdownCameraCoordinator, 196, 9)
     && PLAYER_AT(pNisCameraCoordinator, 200, 10)
     && PLAYER_AT(pVisibleDrivingLine, 204, 11)
     && PLAYER_AT(pNisManager, 220, 13)
     && PLAYER_AT(bWrongWay, 736, 14)
     && PLAYER_AT(bLookBack, 740, 14)
     && PLAYER_AT(EyeVerts, 1600, 14)
     && PLAYER_AT(pSavedCameraMover2, 2480, 14)
     && sizeof(struct Player) == (size_t)2484 + 15 * PLAYER_SLACK)
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
