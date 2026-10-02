// player -- Player, retail's layout, and the class's statics.
//
// Player is 2752 bytes in retail: RaceCoordinator::InitForRace bMallocs
// that for each player. The demo's is 2480 (.mdebug type#2091), and its
// stab names the fields; retail has no symbols, and the fields it added
// are named by the port. The map comes from lining up the two
// constructors (0x0016ee50 in the demo, 0x001751d8 in retail) and the
// methods that read each field.
//
// Who reads what so far: RealDriver reads PlayerNumber, for the view its
// nitro blur is drawn in; RealController reads bWrongWay, which turns its
// route prediction off; Car's catchup reads PlayerNumber and the other
// player's MyCar. Car::FinishMovement reads nZoneCurrent and keeps the jump
// cam's highest point in EyeVerts[2].z. RenderCars finds a view's player by
// ViewID. The camera shake asks IsCameraPOVInCar. The camera functions in
// playercam.c read the movers, the coordinators, the NIS manager, pRoute,
// pVisibleDrivingLine and bLookBack. playerinit.c is the constructor, the
// destructor and the race's two.
//
// The offsets are asserted where pointers are 4 bytes, as chopper.h does.
// On a 64-bit host every pointer widens and the fields after it move, so
// nothing reads a Player in place there; the checkers' harnesses build
// one by name.

#ifndef PLAYER_H
#define PLAYER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "joystick.h"
#include "nisoverlay.h"
#include "playersettings.h"
#include "timer.h"
#include "topology.h"

struct Average;
struct bSample;
struct CameraDataItems;
struct Car;
struct CameraMover;
struct CountdownCameraCoordinator;
struct DemoCameraCoordinator;
struct FlailerObjectChunk;
struct HudAnimator;
struct NisCameraCoordinator;
struct NisManager;
struct PreviewRoute;
struct RouteDisplayer;
struct TrackMap;
struct VisibleDrivingLine;

// cPlayerSettings is playersettings.h's.

// sDrivingControls (.mdebug type#3497), one bit each.
#define PLAYER_DC_STEERING  0x01u
#define PLAYER_DC_THROTTLE  0x02u
#define PLAYER_DC_REVERSE   0x04u
#define PLAYER_DC_BRAKE     0x08u
#define PLAYER_DC_EBRAKE    0x10u

struct Player {
    void        (*NisFinishedCallback)(void *);  //    0
    struct Car   *MyCar;                         //    4
    JoystickPort  JoyPort;                       //    8
    int32_t       JoyType;                       //   12
    int32_t       PlayerNumber;                  //   16  0 or 1; the view
    // Retail's. With two players the constructor points each one's at the
    // other.
    struct Player *pOtherPlayer;                 //   20
    int32_t       ViewID;                        //   24  the eView's ID
    int32_t       RearViewMirrorViewID;          //   28
    cPlayerSettings PlayerSettings;              //   32
    uint32_t      TimeFinishedRacing;            //   80
    uint32_t      FinishAnimationLength;         //   84
    int32_t       nZoneCurrent;                  //   88  the camera zone, 0 for none
    int32_t       nZonePrevious;                 //   92
    int8_t        nZoneCredits[8];               //   96
    Timer         tAutoZoneTimers[8];            //  104
    struct PreviewRoute *pRoute;                 //  136  the zone preview's route
    struct bSample *pZoneSample;                 //  140
    int32_t       bZoneMuffleSound;              //  144
    float         fZoneMuffleVolume;             //  148
    // A Timer in retail, where the demo had the int bIgnoreNextPovChange:
    // RacingJoyHandler reads and writes it.
    Timer         tIgnoreNextPovChange;          //  152
    float         fFreezeZoneDelayTimer;         //  156
    struct Average *pAverageSpeedRatio;          //  160
    Timer         tAverageSpeedTimer;            //  164
    float         fMaxSpeedRatio;                //  168
    Timer         LastTimeCarInTrouble;          //  172
    Timer         TimeToDisplayResetPrompt;      //  176
    // Retail's two. FillInRaceOverMessages reads the float; RequestZone
    // and ClearZoneSound the Timer.
    float         New180;                        //  180
    Timer         tZoneSoundTimer;               //  184
    uint32_t      DrivingControls;               //  188  PLAYER_DC_*
    int32_t       nGlueCount;                    //  192
    int32_t       PlayerInputMode;               //  196
    struct CameraMover *pCameraMover;            //  200  the player's camera, or NULL
    struct CameraMover *pSavedCameraMover;       //  204  the last one kept
    // Retail's. ChangeCameraMover with `keep` moves pSavedCameraMover here
    // before saving the old mover, and RestoreCameraMover moves it back.
    struct CameraMover *pSavedCameraMover2;      //  208
    struct CameraMover *pRVMCameraMover;         //  212  the rear-view mirror's
    struct DemoCameraCoordinator *pDemoCameraCoordinator;           //  216
    struct CountdownCameraCoordinator *pCountdownCameraCoordinator; //  220
    struct NisCameraCoordinator *pNisCameraCoordinator;             //  224
    struct VisibleDrivingLine *pVisibleDrivingLine; // 228
    int32_t       ArrestNisIndex;                //  232
    int32_t       TicketNisIndex;                //  236
    uint32_t      NisFinishedCallbackParam;      //  240
    struct NisManager *pNisManager;              //  244
    int32_t       TicketNisNumbers[32];          //  248
    int32_t       TicketCameraNumbers[32];       //  376
    int32_t       ArrestNisNumbers[32];          //  504
    int32_t       ArrestCameraNumbers[32];       //  632
    int32_t       bWrongWay;                     //  760
    int32_t       bLookBack;                     //  764  a drive camera starts looking back
    uint32_t      CurrentHudFeatures;            //  768
    uint32_t      HudScreenHash;                 //  772
    uint32_t      NisOverlayHash;                //  776

    // The HUD's Flailer objects, the demo's plus 24.
    struct FlailerObjectChunk *pFlailerSpeedNeedle;        //  780
    struct FlailerObjectChunk *pFlailerTachNeedle;         //  784
    struct FlailerObjectChunk *pFlailerTachGear;           //  788
    struct FlailerObjectChunk *pFlailerTachGradient;       //  792
    uint8_t       FlailerTachPointList[180];     //  796  FlailerTachometerPointList
    struct FlailerObjectChunk *pFlailerRacePosition;       //  976
    struct FlailerObjectChunk *pFlailerBigRacePosition;    //  980
    struct FlailerObjectChunk *pFlailerBigRacePosition2;   //  984
    struct FlailerObjectChunk *pFlailerBigRaceExtension;   //  988
    struct FlailerObjectChunk *pFlailerBigRaceTotal;       //  992
    struct FlailerObjectChunk *pFlailerLapCounter;         //  996
    struct FlailerObjectChunk *pFlailerLapTime;            // 1000
    struct FlailerObjectChunk *pFlailerBestLap;            // 1004
    struct FlailerObjectChunk *pFlailerRunningSplitTime;   // 1008
    struct FlailerObjectChunk *pFlailerCompSplitTime;      // 1012
    struct FlailerObjectChunk *pFlailerTireForce[4];       // 1016
    struct FlailerObjectChunk *pFlailerSpeedString;        // 1032
    struct FlailerObjectChunk *pFlailerSpeedString2;       // 1036
    struct FlailerObjectChunk *pFlailerGearString;         // 1040
    struct FlailerObjectChunk *pFlailerShiftUp;            // 1044
    struct FlailerObjectChunk *pFlailerShiftDown;          // 1048
    struct FlailerObjectChunk *pFlailerCFPSString;         // 1052
    struct FlailerObjectChunk *pFlailerGFPSString;         // 1056
    struct FlailerObjectChunk *pFlailerPosString;          // 1060
    struct FlailerObjectChunk *pFlailerDistString;         // 1064
    struct FlailerObjectChunk *pFlailerDebugBacking;       // 1068
    struct FlailerObjectChunk *pFlailerPursuitStar;        // 1072
    struct FlailerObjectChunk *pFlailerPursuitLevel[4];    // 1076
    struct FlailerObjectChunk *pFlailerPursuitX[3];        // 1092
    int32_t       PrevPursuitLevel;              // 1104
    int32_t       PrevTicketLevel;               // 1108
    struct FlailerObjectChunk *pFlailerTracker[7];         // 1112
    struct FlailerObjectChunk *pFlailerReticle;            // 1140
    struct FlailerObjectChunk *pFlailerEventTitle;         // 1144
    struct FlailerObjectChunk *pFlailerEventScore;         // 1148
    struct FlailerObjectChunk *pFlailerScoreTitle;         // 1152
    struct FlailerObjectChunk *pFlailerScoreTotal;         // 1156
    struct FlailerObjectChunk *pFlailerMusicArtist;        // 1160
    struct FlailerObjectChunk *pFlailerMusicTitle;         // 1164
    struct FlailerObjectChunk *pFlailerMusicLabel;         // 1168
    struct FlailerObjectChunk *pFlailerMusicEA;            // 1172
    struct FlailerObjectChunk *pFlailerRadarLight[12];     // 1176
    struct FlailerObjectChunk *pFlailerNitrousLight[10];   // 1224
    struct FlailerObjectChunk *pFlailerDamageLight[5];     // 1264
    struct FlailerObjectChunk *pFlailerBeTheCopTickets[4]; // 1284
    // The demo's three live-split arrays (36 bytes) are 68 in retail, and
    // nothing ported reads them; the constructor leaves them.
    uint8_t       _flailers1300[68];             // 1300
    struct FlailerObjectChunk *pFlailerBeTheCopTime;       // 1368
    struct FlailerObjectChunk *pFlailerBeTheCopHelicopter[3]; // 1372
    struct FlailerObjectChunk *pFlailerBeTheCopRoadblock[3];  // 1384
    uint8_t       _new1396[8];                   // 1396  retail's; the ctor leaves it

    // The demo's plus 64.
    struct bSample *pRadarBeep;                  // 1404
    Timer         RadarTimer;                    // 1408
    char          strEventTitle[32];             // 1412
    char          strEventScore[32];             // 1444
    char          strPrevScore[32];              // 1476
    float         HangTime;                      // 1508
    float         DriftTime;                     // 1512
    float         PosChangeTime;                 // 1516
    int32_t       PositionFlag;                  // 1520
    int32_t       TotalScore;                    // 1524
    struct TrackMap *pTrackMap;                  // 1528
    uint32_t      TimeTrackMapModeChanged;       // 1532
    struct RouteDisplayer *pRouteDisplayer;      // 1536
    struct HudAnimator *pHudAnimations[20];      // 1540
    int32_t       LastRacePosition;              // 1620
    int32_t       LastSpeed;                     // 1624
    float         LastSpeedSet;                  // 1628
    int32_t       TopSpeed;                      // 1632
    int32_t       bNewTopSpeed;                  // 1636
    int32_t       bCheckTopSpeed;                // 1640
    float         SpeedFactor;                   // 1644
    float         fBeginLapNumberExact;          // 1648
    struct CameraDataItems *myCD;                // 1652  the jump cam's, 164 bytes
    uint8_t       _pad1656[8];                   // 1656  to the quadword
    bVector3      EyeVerts[3];                   // 1664  the jump cam's
    bVector3      BankVerts[3];                  // 1712
    bVector3     *FOVtable;                      // 1760  32 of them
    struct PreviewRoute *pJumpCamRoute;          // 1764
    TopologyCoordinate Topology;                 // 1768
    float         mAutoReplayTimeMarker;         // 2472
    float         mLastAutoReplayTime;           // 2476
    int32_t       mAutoReplayState;              // 2480
    bVector2      PursuitObjectPos[7];           // 2484
    // Retail's: the constructor makes it 1 and UpdateScoring clears it.
    int32_t       New2540;                       // 2540
    int32_t       bCollisionDetected;            // 2544
    int32_t       bSmokeableHit;                 // 2548
    uint32_t      BestLapRecordData;             // 2552
    uint32_t      BestTotalRecordData;           // 2556
    NISOverlayManager mFlailerNIS;               // 2560
    struct Car   *lastCar;                       // 2616
    Timer         LastCrossingTime;              // 2620
    int32_t       bSegmentCollisionDetected;     // 2624
    int32_t       baPlaceReached[8];             // 2628
    int32_t       bShownMusicTitle;              // 2660
    int32_t       CurrentJukeboxIndex;           // 2664
    // The demo's bLiveSplitOffset and fInitialLiveSplitY are gone.
    int32_t       bRadarOffset;                  // 2668
    float         fInitialRadarY;                // 2672
    int32_t       bPursuitOffset;                // 2676
    float         fInitialPursuitY;              // 2680
    int32_t       PursuitOffsetState;            // 2684
    int32_t       numCleanLaps;                  // 2688
    int32_t       HasHeardRaceOverSpeech;        // 2692

    // Retail's, from here to the end. The four objects are the score
    // display's, found in the HUD's screen 0x49c15518, and the four floats
    // their tops as the constructor found them, the second pair less the
    // first.
    int32_t       New2696;                       // 2696
    struct FlailerObjectChunk *pFlailerScore[4]; // 2700
    float         fScoreTop[4];                  // 2716
    // StartScoreAnimation writes it; 0x7fffffff for none yet.
    Timer         tScoreAnimation;               // 2732
    // UpdateHud reads and writes it.
    int32_t       New2736;                       // 2736
    uint8_t       _pad2740[12];                  // 2740  to the quadword
};                                               // 2752

typedef char player_layout_check[
    (sizeof(void *) != 4
     || (offsetof(struct Player, pOtherPlayer) == 20
         && offsetof(struct Player, PlayerSettings) == 32
         && offsetof(struct Player, PlayerSettings.DriveCameraPOVIndex) == 36
         && offsetof(struct Player, nZoneCurrent) == 88
         && offsetof(struct Player, tAutoZoneTimers) == 104
         && offsetof(struct Player, pRoute) == 136
         && offsetof(struct Player, pAverageSpeedRatio) == 160
         && offsetof(struct Player, DrivingControls) == 188
         && offsetof(struct Player, pCameraMover) == 200
         && offsetof(struct Player, pSavedCameraMover2) == 208
         && offsetof(struct Player, pVisibleDrivingLine) == 228
         && offsetof(struct Player, pNisManager) == 244
         && offsetof(struct Player, ArrestCameraNumbers) == 632
         && offsetof(struct Player, bWrongWay) == 760
         && offsetof(struct Player, NisOverlayHash) == 776
         && offsetof(struct Player, FlailerTachPointList) == 796
         && offsetof(struct Player, pFlailerRacePosition) == 976
         && offsetof(struct Player, pFlailerTracker) == 1112
         && offsetof(struct Player, pFlailerBeTheCopTickets) == 1284
         && offsetof(struct Player, pFlailerBeTheCopTime) == 1368
         && offsetof(struct Player, pRadarBeep) == 1404
         && offsetof(struct Player, strEventScore) == 1444
         && offsetof(struct Player, pHudAnimations) == 1540
         && offsetof(struct Player, myCD) == 1652
         && offsetof(struct Player, EyeVerts) == 1664
         && offsetof(struct Player, FOVtable) == 1760
         && offsetof(struct Player, Topology) == 1768
         && offsetof(struct Player, mAutoReplayTimeMarker) == 2472
         && offsetof(struct Player, New2540) == 2540
         && offsetof(struct Player, mFlailerNIS) == 2560
         && offsetof(struct Player, lastCar) == 2616
         && offsetof(struct Player, baPlaceReached) == 2628
         && offsetof(struct Player, HasHeardRaceOverSpeech) == 2692
         && offsetof(struct Player, pFlailerScore) == 2700
         && offsetof(struct Player, New2736) == 2736
         && sizeof(struct Player) == 2752))
    ? 1 : -1];

// Player::IsCameraPOVInCar, retail's 0x00178808 (the demo's 0x00172108;
// only the offsets changed). Whether the player's camera is the drive
// camera, enabled, with a CameraInfo, looking from the POV the settings
// pick, and that POV is POV_INCAR. The camera's own GetCameraInfo and
// GetPOV answer, through its vtable.
int32_t player_is_camera_pov_in_car(const struct Player *p);

// Player::NumPlayers (retail's gp-20920), Player::pPlayersByNumber
// (gp-20936), the players by PlayerNumber, and Player::pPlayersByIndex
// (gp-20928), the players in the order they were made. The constructor
// adds to them and the destructor takes away. Car's catchup reads the
// count and pPlayersByNumber and tests neither entry for NULL; RenderCars
// tests each pPlayersByIndex entry.
extern int32_t        PlayerNumPlayers;
extern struct Player *PlayerPlayersByNumber[2];
extern struct Player *PlayerPlayersByIndex[2];

#endif
