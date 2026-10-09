// playerinit -- see playerinit.h.

#include "playerinit.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "average.h"
#include "bmem.h"
#include "car.h"
#include "carstate.h"
#include "eefpu.h"
#include "playercam.h"
#include "race.h"
#include "realdriver.h"
#include "realtime.h"
#include "sundraw.h"
#include "topology.h"


struct NisManager *(*gNewNisManagerFn)(void *mem, const char *name,
                                       int32_t number);
struct bSample *(*gGetInGameSampleFn)(const char *name);
struct FlailerObjectChunk *(*gFindFlailerObjectFn)(uint32_t screen,
                                                   uint32_t object,
                                                   int32_t type);
void (*gFlailerChunkGetTopLeftFn)(struct FlailerObjectChunk *o, float *x,
                                  float *y);
void (*gPlayerResetFlailerMovementFn)(struct Player *p);
void (*gPlayerSetHudFeaturesFn)(struct Player *p, uint32_t features);
void (*gSampleDeleteFn)(struct bSample *s);
void (*gVisibleDrivingLineDeleteFn)(struct VisibleDrivingLine *l);
void (*gDeleteNisManagerFn)(struct NisManager *m);
void (*gHudAnimatorDeleteFn)(struct HudAnimator *a);
void (*gPlayerCreateRandomNisArrayFn)(struct Player *p, int32_t type);
int32_t (*gNisManagerIsPlayingFn)(const struct NisManager *m);
void (*gNisManagerStopFn)(struct NisManager *m);
void (*gPlayerSetInputModeFn)(struct Player *p, int32_t mode);

// The allocations' file name, as retail's bMallocs give it.
#define PLAYER_CPP "..\\indep\\src\\player.cpp"

// The HUD's screen hashes, HudScreenHash and NisOverlayHash. One player
// car takes the single screen pair, two take one pair each by number, and
// Be A Cop takes the cop's overlay whatever the rest says.
#define PLAYER_HUD_SINGLE      0xf1f1f8e5u
#define PLAYER_NIS_SINGLE      0x3ea89b7cu
#define PLAYER_HUD_SPLIT_TOP   0xa8eb7af0u
#define PLAYER_NIS_SPLIT_TOP   0xd4d25ee7u
#define PLAYER_HUD_SPLIT_BOT   0x6283be92u
#define PLAYER_NIS_SPLIT_BOT   0xc17316c9u
#define PLAYER_NIS_BE_A_COP    0x3ea89b7cu

// The score display: its screen and its four objects, in the order the
// constructor finds them, and FlailerObjectType's bitmap.
#define PLAYER_SCORE_SCREEN    0x49c15518u
#define PLAYER_SCORE_OBJECT1   0x464ba8eau   // pFlailerScore[1]
#define PLAYER_SCORE_OBJECT0   0xd911beacu   // pFlailerScore[0]
#define PLAYER_SCORE_OBJECT2   0xf7f1cfb3u   // pFlailerScore[2]
#define PLAYER_SCORE_OBJECT3   0xf88dd0b1u   // pFlailerScore[3]
#define PLAYER_FLAILER_BITMAP  2

// SpeedFactor's start, gp-20916.
#define PLAYER_SPEED_FACTOR    0.9f

static struct FlailerObjectChunk *find_score_object(uint32_t object)
{
    if (gFindFlailerObjectFn == NULL)
        return NULL;
    return gFindFlailerObjectFn(PLAYER_SCORE_SCREEN, object,
                                PLAYER_FLAILER_BITMAP);
}

// The object's top, or 0 with no object or no seam.
static float score_object_top(struct FlailerObjectChunk *o)
{
    float x = 0.0f, y = 0.0f;

    if (o != NULL && gFlailerChunkGetTopLeftFn != NULL)
        gFlailerChunkGetTopLeftFn(o, &x, &y);
    return y;
}

struct Player *player_init(struct Player *p, JoystickPort port,
                           int32_t number)
{
    char name[32];
    void *mem;
    int i;

    // The Timers' constructors, in declaration order, then the two
    // members'.
    p->PlayerSettings.BestTotalTimeRecord.PackedTime = 0;
    p->PlayerSettings.BestLapTimeRecord.PackedTime = 0;
    for (i = 0; i < 8; i++)
        p->tAutoZoneTimers[i].PackedTime = 0;
    p->tIgnoreNextPovChange.PackedTime = 0;
    p->tAverageSpeedTimer.PackedTime = 0;
    p->LastTimeCarInTrouble.PackedTime = 0;
    p->TimeToDisplayResetPrompt.PackedTime = 0;
    p->tTroubleSpeedTimer.PackedTime = 0;
    p->RadarTimer.PackedTime = 0;
    topology_init(&p->Topology);
    nisoverlay_init(&p->mFlailerNIS);
    p->LastCrossingTime.PackedTime = 0;
    p->tScoreAnimation.PackedTime = 0;

    // Retail indexes both tables unchecked; a third player would write
    // past them, so the port stops at two.
    if (PlayerNumPlayers < 2)
        PlayerPlayersByIndex[PlayerNumPlayers] = p;
    PlayerNumPlayers++;
    if (number >= 0 && number < 2) {
        PlayerPlayersByNumber[number] = p;
        p->PlayerSettings = RaceParametersPlayerSettings[number];
    }
    p->pOtherPlayer = NULL;
    if (PlayerNumPlayers == 2) {
        PlayerPlayersByIndex[0]->pOtherPlayer = PlayerPlayersByIndex[1];
        PlayerPlayersByIndex[1]->pOtherPlayer = PlayerPlayersByIndex[0];
    }

    p->JoyPort = port;
    p->JoyType = GetJoystickType(port);
    p->PlayerNumber = number;
    p->PlayerInputMode = 0;
    p->TimeFinishedRacing = 0;
    p->FinishAnimationLength = 0;
    p->BestLapRecordData = 0;
    p->BestTotalRecordData = 0;
    p->nZoneCurrent = 0;
    p->nZonePrevious = 0;
    p->pZoneSample = NULL;
    p->bZoneMuffleSound = 0;
    p->fZoneMuffleVolume = 0.0f;
    p->fFreezeZoneDelayTimer = 0.0f;
    for (i = 0; i < 8; i++) {
        p->tAutoZoneTimers[i].PackedTime = 0;
        p->nZoneCredits[i] = 0;
    }

    if (RaceParametersNumPlayerCars != 2) {
        p->ViewID = 1;
        p->RearViewMirrorViewID = 3;
    } else {
        p->ViewID = number == 0 ? 1 : 2;
        p->RearViewMirrorViewID = 0;
    }

    p->pRoute = NULL;
    p->pCameraMover = NULL;
    p->pSavedCameraMover = NULL;
    p->pSavedCameraMover2 = NULL;
    p->pRVMCameraMover = NULL;
    p->pDemoCameraCoordinator = NULL;
    p->pCountdownCameraCoordinator = NULL;
    p->pNisCameraCoordinator = NULL;
    p->pVisibleDrivingLine = NULL;
    p->CurrentHudFeatures = 0;
    p->HudScreenHash = 0;
    p->NisOverlayHash = 0;
    if (!RaceParametersAIDemoMode && !RaceParametersReplayDemoMode) {
        if (RaceParametersNumPlayerCars != 2) {
            p->HudScreenHash = PLAYER_HUD_SINGLE;
            p->NisOverlayHash = PLAYER_NIS_SINGLE;
        } else if (number == 0) {
            p->HudScreenHash = PLAYER_HUD_SPLIT_TOP;
            p->NisOverlayHash = PLAYER_NIS_SPLIT_TOP;
        } else if (number == 1) {
            p->HudScreenHash = PLAYER_HUD_SPLIT_BOT;
            p->NisOverlayHash = PLAYER_NIS_SPLIT_BOT;
        }
    }
    if (RaceParametersBeACop)
        p->NisOverlayHash = PLAYER_NIS_BE_A_COP;
    nisoverlay_set_screen(&p->mFlailerNIS, p->NisOverlayHash);

    // Not pFlailerBigRacePosition2 or pFlailerDebugBacking.
    p->pFlailerSpeedNeedle = NULL;
    p->pFlailerTachNeedle = NULL;
    p->pFlailerTachGear = NULL;
    p->pFlailerTachGradient = NULL;
    p->pFlailerShiftUp = NULL;
    p->pFlailerShiftDown = NULL;
    p->pFlailerRacePosition = NULL;
    p->pFlailerBigRacePosition = NULL;
    p->pFlailerBigRaceExtension = NULL;
    p->pFlailerBigRaceTotal = NULL;
    p->pFlailerLapCounter = NULL;
    p->pFlailerLapTime = NULL;
    p->pFlailerBestLap = NULL;
    p->pFlailerRunningSplitTime = NULL;
    p->pFlailerCompSplitTime = NULL;
    for (i = 0; i < 4; i++)
        p->pFlailerTireForce[i] = NULL;
    p->pFlailerSpeedString = NULL;
    p->pFlailerSpeedString2 = NULL;
    p->pFlailerGearString = NULL;
    p->pFlailerCFPSString = NULL;
    p->pFlailerGFPSString = NULL;
    p->pFlailerPosString = NULL;
    p->pFlailerDistString = NULL;
    p->pFlailerPursuitStar = NULL;
    for (i = 0; i < 4; i++)
        p->pFlailerPursuitLevel[i] = NULL;
    for (i = 0; i < 3; i++)
        p->pFlailerPursuitX[i] = NULL;
    p->pFlailerEventTitle = NULL;
    p->pFlailerEventScore = NULL;
    p->pFlailerScoreTitle = NULL;
    p->pFlailerScoreTotal = NULL;
    p->pFlailerMusicArtist = NULL;
    p->pFlailerMusicTitle = NULL;
    p->pFlailerMusicLabel = NULL;
    p->pFlailerMusicEA = NULL;
    p->pFlailerReticle = NULL;
    p->PositionFlag = 0;
    p->PosChangeTime = 0.0f;
    p->HangTime = 0.0f;
    p->TotalScore = 0;
    p->TopSpeed = 0;
    p->bNewTopSpeed = 0;
    p->fBeginLapNumberExact = 0.0f;
    p->pRouteDisplayer = NULL;
    p->MyCar = NULL;
    p->pTrackMap = NULL;
    p->TimeTrackMapModeChanged = 0;

    // The manager is named for the other player's number.
    if (gNewNisManagerFn != NULL) {
        snprintf(name, sizeof name, "Player%d", (int)(1 - number));
        mem = bMalloc(320, "NisManager", 0, 16);
        p->pNisManager = gNewNisManagerFn(mem, name, number);
    } else {
        p->pNisManager = NULL;
    }
    p->ArrestNisIndex = -1;
    p->NisFinishedCallback = NULL;
    p->NisFinishedCallbackParam = 0;
    p->TicketNisIndex = -1;
    for (i = 0; i < 32; i++) {
        p->TicketNisNumbers[i] = 0;
        p->TicketCameraNumbers[i] = 0;
        p->ArrestNisNumbers[i] = 0;
        p->ArrestCameraNumbers[i] = 0;
    }
    p->nGlueCount = 0;

    // Retail's Average, 16 bytes on the console.
    mem = bMalloc((int)sizeof(Average), PLAYER_CPP, 520, 16);
    p->pAverageSpeedRatio = average_init((Average *)mem, 10);
    p->tAverageSpeedTimer.PackedTime = 0;
    p->fMaxSpeedRatio = 0.0f;
    for (i = 19; i >= 0; i--)
        p->pHudAnimations[i] = NULL;
    p->LastRacePosition = 0;
    p->bCollisionDetected = 0;
    p->fTroubleSpeed = 0.0f;
    // CameraDataItems is 164 bytes in retail and not ported yet. The FOV
    // table is a new[] of 32 entries with nothing to construct.
    p->myCD = (struct CameraDataItems *)bMalloc(164, PLAYER_CPP, 531, 16);
    p->FOVtable = (bVector3 *)bMalloc((int)(32 * sizeof(bVector3)),
                                      PLAYER_CPP, 532, 16);
    p->pJumpCamRoute = NULL;
    p->bWrongWay = 0;
    p->bLookBack = 0;
    p->mAutoReplayState = 0;
    p->mLastAutoReplayTime = 0.0f;
    snprintf(p->strEventScore, sizeof p->strEventScore, "0");
    snprintf(p->strPrevScore, sizeof p->strPrevScore, "0");
    p->bSmokeableHit = 0;
    for (i = 11; i >= 0; i--)
        p->pFlailerRadarLight[i] = NULL;
    for (i = 9; i >= 0; i--)
        p->pFlailerNitrousLight[i] = NULL;
    for (i = 4; i >= 0; i--)
        p->pFlailerDamageLight[i] = NULL;
    for (i = 3; i >= 0; i--)
        p->pFlailerBeTheCopTickets[i] = NULL;
    for (i = 6; i >= 0; i--)
        p->pFlailerTracker[i] = NULL;
    for (i = 7; i >= 0; i--)
        p->baPlaceReached[i] = 0;
    for (i = 0; i < 3; i++) {
        p->pFlailerBeTheCopHelicopter[i] = NULL;
        p->pFlailerBeTheCopRoadblock[i] = NULL;
    }

    p->pRadarBeep = gGetInGameSampleFn != NULL
        ? gGetInGameSampleFn("RadarBeep") : NULL;
    p->RadarTimer.PackedTime = 0;
    p->LastSpeed = 0;
    p->PrevPursuitLevel = 0;
    p->PrevTicketLevel = 0;
    p->LastSpeedSet = 0.0f;
    p->lastCar = NULL;
    p->bSegmentCollisionDetected = 0;
    p->bShownMusicTitle = 0;
    p->pFlailerBeTheCopTime = NULL;
    p->bRadarOffset = 0;
    p->fInitialRadarY = 0.0f;
    p->bPursuitOffset = 0;
    p->fInitialPursuitY = 0.0f;
    p->numCleanLaps = 0;
    p->HasHeardRaceOverSpeech = 0;
    p->New2696 = 0;
    p->SpeedFactor = PLAYER_SPEED_FACTOR;
    // WorldTimer in seconds (gp-30476, 1/4000) and back in ticks, rounded,
    // as Car's ForceBuzzTime is.
    p->LastCrossingTime.PackedTime = (uint32_t)ee_trunc_w(
        (float)WorldTimer * 0.00025f * 4000.0f + 0.5f);
    p->CurrentJukeboxIndex = -1;
    p->DrivingControls &= ~(PLAYER_DC_STEERING | PLAYER_DC_THROTTLE
                            | PLAYER_DC_REVERSE | PLAYER_DC_BRAKE
                            | PLAYER_DC_EBRAKE);
    p->New2540 = 1;
    p->bCheckTopSpeed = 1;

    p->pFlailerScore[1] = find_score_object(PLAYER_SCORE_OBJECT1);
    p->pFlailerScore[0] = find_score_object(PLAYER_SCORE_OBJECT0);
    p->pFlailerScore[2] = find_score_object(PLAYER_SCORE_OBJECT2);
    p->pFlailerScore[3] = find_score_object(PLAYER_SCORE_OBJECT3);
    p->fScoreTop[1] = score_object_top(p->pFlailerScore[1]);
    p->fScoreTop[0] = score_object_top(p->pFlailerScore[0]);
    p->fScoreTop[2] = score_object_top(p->pFlailerScore[2])
                      - p->fScoreTop[0];
    p->fScoreTop[3] = score_object_top(p->pFlailerScore[3])
                      - p->fScoreTop[1];
    p->tScoreAnimation.PackedTime = 0x7fffffffu;
    p->New2736 = 0;
    return p;
}

void player_clean_up_jump_cam(struct Player *p)
{
    if (p->pJumpCamRoute != NULL && gPreviewRouteDeleteFn != NULL)
        gPreviewRouteDeleteFn(p->pJumpCamRoute);
    p->pJumpCamRoute = NULL;
}

void player_destroy(struct Player *p, int32_t flags)
{
    int i;

    if (gPlayerResetFlailerMovementFn != NULL)
        gPlayerResetFlailerMovementFn(p);
    if (gPlayerSetHudFeaturesFn != NULL)
        gPlayerSetHudFeaturesFn(p, 0);
    if (p->pRoute != NULL && gPreviewRouteDeleteFn != NULL)
        gPreviewRouteDeleteFn(p->pRoute);
    if (p->pZoneSample != NULL && gSampleDeleteFn != NULL)
        gSampleDeleteFn(p->pZoneSample);
    if (p->myCD != NULL)
        bFree(p->myCD);
    if (p->FOVtable != NULL)
        bFree(p->FOVtable);
    player_clean_up_jump_cam(p);
    if (p->pVisibleDrivingLine != NULL) {
        if (gVisibleDrivingLineDeleteFn != NULL)
            gVisibleDrivingLineDeleteFn(p->pVisibleDrivingLine);
        p->pVisibleDrivingLine = NULL;
    }
    if (p->pNisManager != NULL && gDeleteNisManagerFn != NULL)
        gDeleteNisManagerFn(p->pNisManager);
    if (p->pAverageSpeedRatio != NULL)
        average_destroy(p->pAverageSpeedRatio, 3);
    for (i = 0; i < 20; i++)
        if (p->pHudAnimations[i] != NULL && gHudAnimatorDeleteFn != NULL)
            gHudAnimatorDeleteFn(p->pHudAnimations[i]);

    PlayerNumPlayers--;
    p->LastSpeed = 0;
    p->PrevPursuitLevel = 0;
    p->PrevTicketLevel = 0;
    if (PlayerNumPlayers >= 0 && PlayerNumPlayers < 2)
        PlayerPlayersByIndex[PlayerNumPlayers] = NULL;
    p->LastSpeedSet = 0.0f;
    if (p->PlayerNumber >= 0 && p->PlayerNumber < 2)
        PlayerPlayersByNumber[p->PlayerNumber] = NULL;
    bResetGlare = 1;
    nisoverlay_destroy(&p->mFlailerNIS, 2);
    topology_destroy(&p->Topology);
    if (flags & 1)
        bFree(p);
}

void player_predetermine_nis_numbers(struct Player *p)
{
    if (gPlayerCreateRandomNisArrayFn != NULL)
        gPlayerCreateRandomNisArrayFn(p, 1);
    p->TicketNisIndex = -1;
    if (gPlayerCreateRandomNisArrayFn != NULL)
        gPlayerCreateRandomNisArrayFn(p, 2);
    p->ArrestNisIndex = -1;
}

void player_init_for_race(struct Player *p, struct Car *c)
{
    c->pPlayer = p;
    p->MyCar = c;
    c->State.DriverMode = p->PlayerSettings.DrivingStyle;
    if (c->TheControlMode == REAL_CONTROL)
        realdriver_set_manual_transmission(
            (RealDriver *)(void *)c->pCarDriver,
            p->PlayerSettings.TransmissionType);
    player_predetermine_nis_numbers(p);
}

void player_cleanup_after_race(struct Player *p)
{
    struct Car *c;

    // AutoPilotOff (0x001788b0) is a bare `jr ra` in retail.
    if (gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(p->PlayerNumber);
    player_remove_camera_movers(p);
    if (p->pNisManager != NULL && gNisManagerIsPlayingFn != NULL
        && gNisManagerIsPlayingFn(p->pNisManager)) {
        if (gNisManagerStopFn != NULL)
            gNisManagerStopFn(p->pNisManager);
        nisoverlay_finish(&p->mFlailerNIS);
    }
    if (gPlayerSetInputModeFn != NULL)
        gPlayerSetInputModeFn(p, 0);
    // Retail stores through MyCar untested.
    c = p->MyCar;
    p->MyCar = NULL;
    if (c != NULL)
        c->pPlayer = NULL;
}
