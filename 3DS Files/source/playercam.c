// playercam -- Player's camera functions. See playercam.h.

#include "playercam.h"

#include <stddef.h>

#include "bmem.h"
#include "camerainfo.h"
#include "car.h"
#include "drivecam.h"
#include "orbitcam.h"
#include "player.h"
#include "world.h"

const int *gPlayerCamSkipFE;

void (*gCameraCoordinatorDeleteFn)(void *coord);
void (*gCameraCoordinatorEnableFn)(void *coord);
void (*gCameraCoordinatorDisableFn)(void *coord);
void (*gNisDeleteCameraCoordinatorFn)(struct NisManager *mgr,
                                      struct NisCameraCoordinator *c);
void (*gNisEnableCameraCoordinatorFn)(struct NisManager *mgr,
                                      struct NisCameraCoordinator *c);
void (*gNisDisableCameraCoordinatorFn)(struct NisManager *mgr,
                                       struct NisCameraCoordinator *c);
void (*gVisibleDrivingLineEnableFn)(struct VisibleDrivingLine *l);
void (*gVisibleDrivingLineDisableFn)(struct VisibleDrivingLine *l);
CameraMover *(*gDebugWorldCameraMoverFn)(void *mem, int viewID,
                                         const bVector3 *pos,
                                         const bVector3 *dir,
                                         JoystickPort port);
CameraMover *(*gTrackRouteEditorCameraMoverFn)(void *mem, int viewID,
                                               JoystickPort port);
CameraMover *(*gZoneFreezeCameraMoverFn)(void *mem, int viewID,
                                         struct Car *car,
                                         CameraMover *saved);
CameraMover *(*gZonePreviewCameraMoverFn)(void *mem, int viewID,
                                          struct PreviewRoute *route,
                                          bVector3 *pos);
CameraMover *(*gCubicCameraMoverFn)(void *mem, int viewID, struct Car *car);
void (*gPreviewRouteDeleteFn)(struct PreviewRoute *route);
CameraMover *(*gPlayerJumpCamMoverFn)(struct Player *p, struct Car *car,
                                      int second);

// The drive camera's look-back speed, gp-30468. Retail passes this where
// the demo passed the settings' LookbackSpeed, whose word is now an int.
#define PLAYER_LOOKBACK_SPEED 300.9f

// The joystick port every mover built here takes.
#define PLAYER_CAM_JOY_PORT 1

// The deleting destructor, virtual with flag 3.
static void delete_mover(CameraMover *m)
{
    m->vtbl->Destroy(m);
    bFree(m);
}

static float look_back_param(const struct Player *p)
{
    return p->bLookBack ? 1.0f : 0.0f;
}

void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep)
{
    CameraMover *old;
    struct Car *car;
    void *mem;

    if (p->pDemoCameraCoordinator != NULL) {
        if (gCameraCoordinatorDeleteFn != NULL)
            gCameraCoordinatorDeleteFn(p->pDemoCameraCoordinator);
        p->pDemoCameraCoordinator = NULL;
    }
    if (p->pCountdownCameraCoordinator != NULL) {
        if (gCameraCoordinatorDeleteFn != NULL)
            gCameraCoordinatorDeleteFn(p->pCountdownCameraCoordinator);
        p->pCountdownCameraCoordinator = NULL;
    }
    if (p->pNisCameraCoordinator != NULL) {
        if (gNisDeleteCameraCoordinatorFn != NULL)
            gNisDeleteCameraCoordinatorFn(p->pNisManager,
                                          p->pNisCameraCoordinator);
        p->pNisCameraCoordinator = NULL;
    }

    old = p->pCameraMover;
    if (old != NULL && old->Type == type)
        return;

    // The list's first link, unchecked: an empty list's is World itself.
    car = p->MyCar;
    if (car == NULL)
        car = (struct Car *)pCurrentWorld->CarList.next;

    if (old != NULL) {
        if (keep) {
            p->pSavedCameraMover2 = p->pSavedCameraMover;
            p->pSavedCameraMover = old;
            old->vtbl->Disable(old);
        } else {
            delete_mover(old);
        }
        p->pCameraMover = NULL;
    }

    switch ((uint32_t)type) {
    case CM_NONE:
        break;

    case CM_DRIVE: {
        DriveCameraMover *d = bMalloc((int)sizeof(DriveCameraMover),
                                      "DriveCameraMover(Player)", 0, 16);
        drive_cam_init(d, p->ViewID, car,
                       p->PlayerSettings.DriveCameraPOVIndex,
                       PLAYER_LOOKBACK_SPEED,
                       p->PlayerSettings.CameraSpring, 0, 1);
        p->pCameraMover = &d->base;
        d->DesiredLookBackParam = look_back_param(p);
        p->PlayerSettings.DriveCameraPOVIndex =
            (int8_t)player_cycle_drive_camera_pov_index(
                p, p->PlayerSettings.DriveCameraPOVIndex);
        break;
    }

    // Four metres above the car, looking up the world's z. Retail leaves
    // the direction's pad lane as the stack had it.
    case CM_DEBUG_WORLD:
        if (gDebugWorldCameraMoverFn != NULL) {
            bVector3 pos = car->State.Position;
            bVector3 dir = {0.0f, 0.0f, 1.0f, 0.0f};

            pos.z += 4.0f;
            mem = bMalloc(76, "DebugWorldCameraMover", 0, 16);
            p->pCameraMover = gDebugWorldCameraMoverFn(
                mem, p->ViewID, &pos, &dir, PLAYER_CAM_JOY_PORT);
        }
        break;

    case CM_TRACK_ROUTE_EDITOR:
        if (gTrackRouteEditorCameraMoverFn != NULL) {
            mem = bMalloc(44, "TrackRouteEditorCameraMover", 0, 16);
            p->pCameraMover = gTrackRouteEditorCameraMoverFn(
                mem, p->ViewID, PLAYER_CAM_JOY_PORT);
        }
        break;

    case CM_ZONE_FREEZE:
        if (gZoneFreezeCameraMoverFn != NULL) {
            mem = bMalloc(872, "ZoneFreezeCameraMover", 0, 16);
            p->pCameraMover = gZoneFreezeCameraMoverFn(
                mem, p->ViewID, car, p->pSavedCameraMover);
        }
        break;

    // The preview takes the route, and the player lets go of it.
    case CM_ZONE_PREVIEW:
        if (gZonePreviewCameraMoverFn != NULL) {
            mem = bMalloc(1104, "ZonePreviewCameraMover", 0, 16);
            p->pCameraMover = gZonePreviewCameraMoverFn(
                mem, p->ViewID, p->pRoute, &car->State.Position);
            if (p->pRoute != NULL && gPreviewRouteDeleteFn != NULL)
                gPreviewRouteDeleteFn(p->pRoute);
            p->pRoute = NULL;
        }
        break;

    case CM_ZONE_JUMPER:
    case CM_ZONE_JUMPER2:
        if (gPlayerJumpCamMoverFn != NULL)
            p->pCameraMover = gPlayerJumpCamMoverFn(
                p, car, type == CM_ZONE_JUMPER2);
        break;

    case CM_CUBIC_DAMPER:
        if (gCubicCameraMoverFn != NULL) {
            mem = bMalloc(160, "CubicCameraMover", 0, 16);
            p->pCameraMover = gCubicCameraMoverFn(mem, p->ViewID, car);
        }
        break;

    default: {
        OrbitCarCameraMover *o = bMalloc((int)sizeof(OrbitCarCameraMover),
                                         "OrbitCarCameraMover", 0, 16);
        orbit_init(o, p->ViewID, car, PLAYER_CAM_JOY_PORT);
        p->pCameraMover = &o->base;
        break;
    }
    }

    if (p->pCameraMover != NULL)
        p->pCameraMover->pPlayer = p;
}

// Retail reads the car unchecked, as here: only a player with a car has a
// drive camera.
int player_cycle_drive_camera_pov_index(struct Player *p, int index)
{
    CameraMover *m = p->pCameraMover;
    int tries;

    index %= 4;
    if (m == NULL || m->Type != CM_DRIVE || m->vtbl->GetCameraInfo(m) == NULL)
        return index;

    for (tries = 0; tries < 4; tries++) {
        const POV *pov;

        m = p->pCameraMover;
        pov = m->vtbl->GetPOV(m, index);
        if (pov != NULL
            && ((gPlayerCamSkipFE != NULL && *gPlayerCamSkipFE)
                || p->MyCar->pRideInfo->HasDash
                || pov->Type == POV_BUMPER || pov->Type == POV_OUTSIDE))
            break;
        index = (index + 1) % 4;
    }
    if (tries == 4)
        index = 0;
    drive_cam_set_pov_index((DriveCameraMover *)p->pCameraMover, index);
    return index;
}

void player_restore_camera_mover(struct Player *p)
{
    CameraMover *m;

    if (p->pCameraMover != NULL)
        delete_mover(p->pCameraMover);
    m = p->pSavedCameraMover;
    p->pCameraMover = m;
    p->pSavedCameraMover = p->pSavedCameraMover2;
    p->pSavedCameraMover2 = NULL;
    if (m != NULL && m->Type == CM_DRIVE)
        ((DriveCameraMover *)m)->DesiredLookBackParam = look_back_param(p);
    if (m != NULL)
        m->vtbl->Enable(m);
}

void player_remove_camera_movers(struct Player *p)
{
    player_change_camera_mover(p, CM_NONE, 0);
    if (p->pSavedCameraMover != NULL) {
        delete_mover(p->pSavedCameraMover);
        p->pSavedCameraMover = NULL;
    }
    if (p->pSavedCameraMover2 != NULL) {
        delete_mover(p->pSavedCameraMover2);
        p->pSavedCameraMover2 = NULL;
    }
}

void player_enable_camera_movers(struct Player *p)
{
    if (p->pCameraMover != NULL)
        p->pCameraMover->vtbl->Enable(p->pCameraMover);
    if (p->pRVMCameraMover != NULL)
        p->pRVMCameraMover->vtbl->Enable(p->pRVMCameraMover);
    if (p->pDemoCameraCoordinator != NULL
        && gCameraCoordinatorEnableFn != NULL)
        gCameraCoordinatorEnableFn(p->pDemoCameraCoordinator);
    if (p->pCountdownCameraCoordinator != NULL
        && gCameraCoordinatorEnableFn != NULL)
        gCameraCoordinatorEnableFn(p->pCountdownCameraCoordinator);
    if (p->pNisCameraCoordinator != NULL
        && gNisEnableCameraCoordinatorFn != NULL)
        gNisEnableCameraCoordinatorFn(p->pNisManager,
                                      p->pNisCameraCoordinator);
    if (p->pVisibleDrivingLine != NULL
        && gVisibleDrivingLineEnableFn != NULL)
        gVisibleDrivingLineEnableFn(p->pVisibleDrivingLine);
}

void player_disable_camera_movers(struct Player *p)
{
    if (p->pCameraMover != NULL)
        p->pCameraMover->vtbl->Disable(p->pCameraMover);
    if (p->pRVMCameraMover != NULL)
        p->pRVMCameraMover->vtbl->Disable(p->pRVMCameraMover);
    if (p->pDemoCameraCoordinator != NULL
        && gCameraCoordinatorDisableFn != NULL)
        gCameraCoordinatorDisableFn(p->pDemoCameraCoordinator);
    if (p->pCountdownCameraCoordinator != NULL
        && gCameraCoordinatorDisableFn != NULL)
        gCameraCoordinatorDisableFn(p->pCountdownCameraCoordinator);
    if (p->pNisCameraCoordinator != NULL
        && gNisDisableCameraCoordinatorFn != NULL)
        gNisDisableCameraCoordinatorFn(p->pNisManager,
                                       p->pNisCameraCoordinator);
    if (p->pVisibleDrivingLine != NULL
        && gVisibleDrivingLineDisableFn != NULL)
        gVisibleDrivingLineDisableFn(p->pVisibleDrivingLine);
}
