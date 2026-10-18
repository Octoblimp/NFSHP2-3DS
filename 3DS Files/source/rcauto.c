// rcauto -- the race coordinator's auto replay. TASKS 72g-4; rcauto.h has
// the map and docs/formats/replay.md the decode.
#include "rcauto.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "cammover.h"
#include "car.h"
#include "player.h"
#include "playercam.h"
#include "previewroute.h"
#include "race.h"
#include "rcpost.h"
#include "rcstates.h"
#include "realtime.h"
#include "replay.h"
#include "replaymgr.h"
#include "trackcarcam.h"
#include "trackflow.h"
#include "trackpath.h"

// The pool everything comes from, and the allocations' lines.
#define RC_POOL            16
#define RC_LINE_ROUTE      2504
#define RC_LINE_CD         2516
#define RC_LINE_FOV        2517
#define RC_LINE_BANK       2524
#define RC_LINE_EYE        2525

// The letterbox bars, which show over the replay.
#define RC_AUTO_BARS_SCREEN 0x49c15518u

// How many times the replay runs before it skips.
#define RC_AUTO_REWINDS    3

// The route: 100 out from the car.
#define RC_AUTO_ROUTE_RADIUS 100.0f
#define RC_AUTO_ROUTE_POINTS 5

// The camera: eye points 5 above the road, a 40 degree FOV, the clip
// planes (gp-31372 for the far one) and the look's vertical push
// (gp-31368).
#define RC_AUTO_EYE_HEIGHT 5.0f
#define RC_AUTO_FOV        40.0f
#define RC_AUTO_NEAR_CLIP  0.5f
#define RC_AUTO_FAR_CLIP   5000.0f
#define RC_AUTO_VERT_COMP  0.2f

// ---------------------------------------------------------- the helpers

static void screen_visibility(uint32_t screen, int visibility)
{
    if (gSetFlailerScreenVisibilityFn != NULL)
        gSetFlailerScreenVisibilityFn(screen, visibility);
}

// The camera mover's deleting destructor.
static void delete_mover(void *m)
{
    CameraMover *cm = (CameraMover *)m;

    cm->vtbl->Destroy(cm);
    bFree(cm);
}

// The highlight car's place. Retail reads it unchecked; with no car, the
// low memory a NULL reads, which is 0.
static bVector3 car_place(const struct Car *car)
{
    bVector3 zero = {0.0f, 0.0f, 0.0f, 0.0f};

    return car != NULL ? car->State.Position : zero;
}

// A mover on the view following `car`: a shake of nothing with two
// points, and the record. Retail's shake is a 560-byte stack record.
static void *make_mover(RaceCoordinator *rc, struct Car *car)
{
    CameraShake shake;
    void *mem;

    memset(&shake, 0, sizeof shake);
    shake.NumCVs = 2;
    mem = bMalloc(RC_AUTO_MOVER_SIZE, RC_AUTO_MOVER_NAME, 0, RC_POOL);
    return track_car_camera_mover_init((TrackCarCameraMover *)mem,
                                       rc->mViewID, car,
                                       (CameraDataItems *)rc->mpCD, &shake,
                                       1);
}

// The eye and bank points from the route: each point's place on the
// road's left edge or on the route's line, lifted 5, and a flat bank. The
// bank's pad lane is the stack's in retail; here it is 0.
static void route_verts(RaceCoordinator *rc, int32_t left)
{
    PreviewRoute *r = (PreviewRoute *)rc->mpRoute;
    int32_t i;

    for (i = 0; i < r->nPoints; i++) {
        const PreviewRoutePoint *pt = &r->pPoints[i];
        bVector3 *bank = &((bVector3 *)rc->mpBankVerts)[i];
        bVector3 o;

        preview_route_point_get_position_at(
            pt, &o, 0.0f, left ? -pt->pPoint->LeftWidth : 0.0f);
        bank->x = 0.0f;
        bank->y = 0.0f;
        bank->z = 0.0f;
        bank->pad = 0.0f;
        o.z = o.z + RC_AUTO_EYE_HEIGHT;
        ((bVector3 *)rc->mpEyeVerts)[i] = o;
    }
}

// A rewind: the snapshot restored, the mover deleted, the eye points made
// again (the road's left edge the first time, the route's line the
// second), the look's sideways push flipped or cleared, and a new mover on
// the second highlight car.
static void rewind(RaceCoordinator *rc, int32_t first)
{
    CameraDataItems *cd;

    replaymgr_restore_snapshot_named(pReplayManager,
                                     first ? RC_AUTO_INSTANT_REPLAY
                                           : RC_AUTO_SNAPSHOT);
    if (rc->mpCameraMover != NULL)
        delete_mover(rc->mpCameraMover);
    route_verts(rc, first);
    cd = (CameraDataItems *)rc->mpCD;
    if (first)
        cd->EnterHorizComp = -cd->EnterHorizComp;
    else
        cd->EnterHorizComp = 0.0f;
    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar2);
}

// Retail hands its third TrackPathCoordinate rc+60: mIncidentPoint's word
// and mIncidentCoord's x, read as a bVector2. Nothing reads the result.
static void incident_place(const RaceCoordinator *rc, bVector2 *o)
{
    uint32_t bits = (uint32_t)(uintptr_t)rc->mIncidentPoint;

    memcpy(&o->x, &bits, sizeof bits);
    o->y = rc->mIncidentCoord.x;
}

// --------------------------------------------------------- the methods

void racecoordinator_set_up_auto_replay(RaceCoordinator *rc,
                                        struct Car *car, struct Car *car2,
                                        int32_t viewID)
{
    rc->mpHighlightCar = car;
    rc->mpHighlightCar2 = car2;
    rc->mViewID = viewID;
    rc->mIncidentPoint = car_get_route_point(car, 1);
    rc->mIncidentCoord = car->State.Position;
}

void racecoordinator_clean_up_auto_replay(RaceCoordinator *rc)
{
    if (rc->mpCameraMover != NULL)
        delete_mover(rc->mpCameraMover);
    rc->mpCameraMover = NULL;
    if (rc->mpCD != NULL)
        bFree(rc->mpCD);
    rc->mpCD = NULL;
    if (rc->mpFOVtable != NULL)
        bFree(rc->mpFOVtable);
    rc->mpFOVtable = NULL;
    if (rc->mpRoute != NULL)
        preview_route_destroy((PreviewRoute *)rc->mpRoute, 3);
    rc->mpRoute = NULL;
    if (rc->mpBankVerts != NULL)
        bFree(rc->mpBankVerts);
    rc->mpBankVerts = NULL;
    if (rc->mpEyeVerts != NULL)
        bFree(rc->mpEyeVerts);
    rc->mpEyeVerts = NULL;
}

int32_t racecoordinator_check_auto_replay_cam(RaceCoordinator *rc)
{
    TrackPathCoordinate final, start;
    PreviewRoute *r;
    void *mem;
    float length;

    racecoordinator_clean_up_auto_replay(rc);
    trackpath_coord_init_at(&final, (const bVector2 *)&rc->mFinalPosition);
    trackpath_coord_init_at(&start, (const bVector2 *)&rc->mStartPosition);
    length = final.DistanceAroundTrack - start.DistanceAroundTrack;
    mem = bMalloc(RC_AUTO_ROUTE_SIZE, RC_AUTO_FILE, RC_LINE_ROUTE, RC_POOL);
    r = preview_route_init((PreviewRoute *)mem, rc->mpHighlightCar,
                           RC_AUTO_ROUTE_RADIUS, length);
    rc->mpRoute = r;
    if (r == NULL || r->nPoints < RC_AUTO_ROUTE_POINTS) {
        racecoordinator_clean_up_auto_replay(rc);
        return 0;
    }
    return 1;
}

void racecoordinator_set_up_auto_replay_cam(RaceCoordinator *rc)
{
    TrackPathCoordinate final, start, incident;
    CameraDataItems *cd;
    PreviewRoute *r;
    bVector3 *fov;
    bVector2 at;
    int32_t i;

    rc->mpCD = bMalloc(RC_AUTO_CD_SIZE, RC_AUTO_FILE, RC_LINE_CD, RC_POOL);
    rc->mpFOVtable = bMalloc(RC_AUTO_FOV_ENTRIES * (int)sizeof(bVector3),
                             RC_AUTO_FILE, RC_LINE_FOV, RC_POOL);
    cd = (CameraDataItems *)rc->mpCD;
    cd->IsFOVIso = 0;
    cd->Type = 0;
    cd->Name = NULL;
    trackpath_coord_init_at(&final, (const bVector2 *)&rc->mFinalPosition);
    trackpath_coord_init_at(&start, (const bVector2 *)&rc->mStartPosition);
    incident_place(rc, &at);
    trackpath_coord_init_at(&incident, &at);

    r = (PreviewRoute *)rc->mpRoute;
    rc->mpBankVerts = bMalloc(r->nPoints * (int)sizeof(bVector3),
                              RC_AUTO_FILE, RC_LINE_BANK, RC_POOL);
    rc->mpEyeVerts = bMalloc(r->nPoints * (int)sizeof(bVector3),
                             RC_AUTO_FILE, RC_LINE_EYE, RC_POOL);
    cd->NumEyeVerts = r->nPoints;
    for (i = 0; i < r->nPoints; i++) {
        const PreviewRoutePoint *pt = &r->pPoints[i];
        bVector3 *bank = &((bVector3 *)rc->mpBankVerts)[i];
        bVector3 o;

        preview_route_point_get_position_at(pt, &o, 0.0f,
                                            pt->pPoint->RightWidth);
        bank->x = 0.0f;
        bank->y = 0.0f;
        bank->z = 0.0f;
        bank->pad = 0.0f;
        o.z = o.z + RC_AUTO_EYE_HEIGHT;
        ((bVector3 *)rc->mpEyeVerts)[i] = o;
    }

    if (RaceParametersTrackDirection == 0) {
        cd->MinAreaPercent = cd->MinPercent = start.RatioAroundTrack;
        cd->MaxAreaPercent = cd->MaxPercent = final.RatioAroundTrack;
    } else {
        cd->MinAreaPercent = cd->MinPercent = 1.0f - start.RatioAroundTrack;
        cd->MaxAreaPercent = cd->MaxPercent = 1.0f - final.RatioAroundTrack;
    }
    cd->FarClip = RC_AUTO_FAR_CLIP;
    cd->LockEyeSpeedToCar = 1;
    cd->FOVTable = (bVector3 *)rc->mpFOVtable;
    cd->NearClip = RC_AUTO_NEAR_CLIP;
    cd->EyeSplineSpeed = 0.0f;
    cd->LookSplineSpeed = 0.0f;
    cd->FOVSplineSpeed = 0.0f;
    cd->LockLookSpeedToCar = 0;
    cd->Backwards = 0;
    fov = (bVector3 *)rc->mpFOVtable;
    for (i = 0; i < RC_AUTO_FOV_ENTRIES; i++) {
        fov[i].x = RC_AUTO_FOV;
        fov[i].y = 0.0f;
        fov[i].z = 0.0f;
        fov[i].pad = 0.0f;
    }
    cd->EyeVerts = (bVector3 *)rc->mpEyeVerts;
    cd->EnterVertComp = RC_AUTO_VERT_COMP;
    cd->WipeAutoDisable = 0;
    cd->BankVerts = (bVector3 *)rc->mpBankVerts;
    cd->NumLookVerts = 0;
    cd->LookVerts = NULL;
    cd->SpringXVel = 0.0f;
    cd->SpringYVel = 0.0f;
    cd->SpringZVel = 0.0f;
    cd->SpringDamp = 0.0f;
    cd->SpringConst = 0.0f;
    cd->LookOffsetX = 0.0f;
    cd->LookOffsetY = 0.0f;
    cd->LookOffsetZ = 0.0f;
    cd->LeaveVertComp = 0.0f;
    cd->LeaveHorizComp = 0.0f;
    cd->IsLeaveSet = 0;
    cd->WipeDistance = 0.0f;

    rc->mpCameraMover = make_mover(rc, rc->mpHighlightCar);
}

// ------------------------------------------------------ RCSTATE_AUTO_REPLAY

// THE_PRESENT kept and the incident found; any failure goes back to the
// race.
static int32_t auto_replay_activate(RaceCoordinator *rc)
{
    ReplayManager *rm = pReplayManager;
    int32_t i;

    if (replaymgr_take_snapshot(rm, RC_AUTO_THE_PRESENT) == NULL)
        return 0;
    rc->mFinalPosition = car_place(rc->mpHighlightCar);
    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_SNAPSHOT))
        return 0;
    if (!replaymgr_restore_snapshot_named(rm, RC_AUTO_INSTANT_REPLAY))
        return 0;
    rc->mStartPosition = car_place(rc->mpHighlightCar);
    if (!racecoordinator_check_auto_replay_cam(pRaceCoordinator))
        return 0;
    screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_VISIBLE);
    rc->mNumRewinds = 0;
    for (i = 0; i < PlayerNumPlayers; i++)
        player_disable_camera_movers(PlayerPlayersByIndex[i]);
    racecoordinator_set_up_auto_replay_cam(rc);
    return 1;
}

// At the capture's end, the next rewind, or the skip after the third.
static void auto_replay_tick(RaceCoordinator *rc)
{
    if ((int32_t)((uint32_t)pReplayManager->EndCapturingLoopCount
                  - (uint32_t)WorldLoopCounter) > 0)
        return;
    rc->mNumRewinds++;
    if (rc->mNumRewinds >= RC_AUTO_REWINDS) {
        racecoordinator_send_message(rc, RC_SKIP, 0);
        return;
    }
    rewind(rc, rc->mNumRewinds == 1);
}

int32_t rc_state_auto_replay_callback(RaceCoordinator *rc, RCMessage msg,
                                      int32_t param)
{
    int32_t i;

    (void)param;
    switch (msg) {
    case RC_ACTIVATE:
        if (!auto_replay_activate(rc))
            racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);
        return 1;
    case RC_UNACTIVATE:
        replaymgr_restore_snapshot_named(pReplayManager,
                                         RC_AUTO_THE_PRESENT);
        replaymgr_delete_snapshot_named(pReplayManager,
                                        RC_AUTO_THE_PRESENT);
        screen_visibility(RC_AUTO_BARS_SCREEN, FLAILER_SCREEN_INVISIBLE);
        racecoordinator_clean_up_auto_replay(rc);
        for (i = 0; i < PlayerNumPlayers; i++)
            player_enable_camera_movers(PlayerPlayersByIndex[i]);
        if (gRestoreTypeChangedHandlersFn != NULL)
            gRestoreTypeChangedHandlersFn();
        return 1;
    case RC_TICK:
        auto_replay_tick(rc);
        return 1;
    case RC_SKIP:
        racecoordinator_change_state(rc, RCSTATE_RACE_IN_PROGRESS);
        return 1;
    case RC_TAKE_AUTOSNAPSHOT:
        return 1;
    default:
        return 0;
    }
}
