// democam -- see democam.h.

#include "democam.h"

#include <math.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "car.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "playercam.h"
#include "race.h"
#include "realtime.h"
#include "vtable.h"
#include "world.h"

CameraMover *(*gTrackCarCameraMoverFn)(void *mem, int32_t viewID,
                                       struct Car *car,
                                       const CameraDataItems *cd,
                                       const CameraShake *shake,
                                       int32_t focusEffects);
CameraMover *(*gDriveCameraMoverFn)(void *mem, int32_t viewID,
                                    struct Car *car, int32_t pov,
                                    float lookbackSpeed, int32_t disableLag,
                                    int32_t lookBack, int32_t perfectFocus);

// What a camera must stay clear of every car by: the one showing, and one
// just built.
#define DEMO_CAMERA_NEAR_SHOWN 2.0f
#define DEMO_CAMERA_NEAR_BUILT 5.0f

// The drive camera's look-back speed (0x43960000).
#define DEMO_CAMERA_LOOKBACK_SPEED 300.0f

// eGetCurrentViewMode's split screen, whose POVs the drive camera picks
// from.
#define DEMO_CAMERA_SPLIT_VIEW_MODE 3

// A mover's deleting destructor, by its table with flags 3.
static void delete_mover(CameraMover *m)
{
    m->vtbl->Destroy(m);
    bFree(m);
}

// Whether the camera is within `d` of any of the World's cars. Retail
// reads pCurrentWorld unchecked; the sum is the VU's, x and y first.
static int camera_near_a_car(const Camera *cam, float d)
{
    const bVector3 *eye = &cam->CurrentKey.Position;
    World *w = pCurrentWorld;
    struct Car *car;

    for (car = (struct Car *)w->CarList.next;
         (void *)car != (void *)&w->CarList;
         car = (struct Car *)car->Link.next) {
        const bVector3 *p = &car->State.Position;
        float x = eye->x - p->x, y = eye->y - p->y, z = eye->z - p->z;

        if (sqrtf(x * x + y * y + z * z) < d)
            return 1;
    }
    return 0;
}

// --------------------------------------------------------- the near plane

int32_t camera_near_plane_cuts_car(const Camera *cam, struct Car *car)
{
    // 0x001044c8.
    bMatrix4 world, m;
    bVector3 min, max, corner[8], v;
    float plane, tb, tf, last = 0.0f, z;
    uint16_t half;
    int32_t i;

    world.v0 = car->State.BodyMatrix.v0;
    world.v1 = car->State.BodyMatrix.v1;
    world.v2 = car->State.BodyMatrix.v2;
    world.v3.x = car->State.Position.x;
    world.v3.y = car->State.Position.y;
    world.v3.z = car->State.Position.z;
    world.v3.w = 1.0f;
    eMulMatrix(&m, &world, &cam->CurrentKey.Matrix);
    car_get_car_space_bounding_box(car, &min, &max);
    plane = cam->CurrentKey.NearZ;
    for (i = 0; i < 8; i++) {
        corner[i].x = (i & 4) ? max.x : min.x;
        corner[i].y = (i & 2) ? max.y : min.y;
        corner[i].z = (i & 1) ? max.z : min.z;
        corner[i].pad = 0.0f;
    }
    half = (uint16_t)(aBaselineFovZ >> 1);
    tb = bSinBam(half) / bCosBam(half);
    half = (uint16_t)(cam->CurrentKey.FieldOfView >> 1);
    tf = bSinBam(half) / bCosBam(half);
    plane = plane * tb / tf;
    for (i = 0; i < 8; i++) {
        eMulVector3(&v, &m, &corner[i]);
        z = v.z - plane;
        if (i > 0 && z * last < 0.0f)
            return 1;
        last = z;
    }
    return 0;
}

// ----------------------------------------------------- the demo camera

DemoCameraCoordinator *demo_camera_coordinator_init(
    DemoCameraCoordinator *c, int32_t viewID, struct Car *car)
{
    // 0x0019a440.
    camera_coordinator_init(&c->Base, viewID);
    c->Base._vtable = DEMOCAMERACOORDINATOR_VTABLE;
    c->pCar = car;
    c->CurrVortexCount = TheCameraLoader.VortexCount;
    c->CurrentlyActiveCameraData = -1;
    c->DefaultCameraLookback = 0;
    c->DefaultCameraPOV = 0;
    return c;
}

void *demo_camera_coordinator_construct(void *mem, int32_t viewID,
                                        struct Car *car)
{
    return demo_camera_coordinator_init((DemoCameraCoordinator *)mem,
                                        viewID, car);
}

void demo_camera_coordinator_destroy(DemoCameraCoordinator *c,
                                     int32_t flags)
{
    // 0x0019a4a0.
    c->Base._vtable = DEMOCAMERACOORDINATOR_VTABLE;
    camera_coordinator_destroy(&c->Base, flags);
}

int32_t demo_camera_coordinator_will_look_good(DemoCameraCoordinator *c,
                                               const CameraDataItems *cd,
                                               struct Car *car)
{
    // 0x0019a9d0. The faces are three ints and a pad each; their corners
    // are not bounded.
    const bVector2 *pt = (const bVector2 *)(const void *)&car->State.Position;
    const int32_t *face = (const int32_t *)cd->AreaFaces;
    int32_t i;

    (void)c;
    for (i = 0; i < cd->NumAreaFaces; i++, face += 4) {
        bVector2 tri[3];

        tri[0] = cd->AreaVerts[face[0]];
        tri[1] = cd->AreaVerts[face[1]];
        tri[2] = cd->AreaVerts[face[2]];
        if (eIsPointInPoly(pt, tri, 3))
            return 1;
    }
    return 0;
}

int32_t demo_camera_coordinator_will_look_good_data(
    DemoCameraCoordinator *c, char *data, struct Car *car)
{
    // 0x0019a988.
    CameraDataItems cd;

    camera_data_items_parse(&cd, data);
    return demo_camera_coordinator_will_look_good(c, &cd, car);
}

int32_t demo_camera_coordinator_find_good_looking_highlight_camera(
    DemoCameraCoordinator *c, struct Car *car)
{
    // 0x0019aad8.
    int32_t i;

    for (i = 0; i < TheCameraLoader.NumHighlightCameras; i++) {
        CameraDataItems cd;
        int reversed, backwards = 0;

        camera_data_items_parse(&cd, TheCameraLoader.HighlightCameraData[i]);
        reversed = RaceParametersTrackDirection == 1;
        if (!car_is_facing_wrong_way(car))
            backwards = reversed;
        if (car_is_facing_wrong_way(car) && !reversed)
            backwards = 1;
        if ((backwards != 0) == (cd.Backwards != 0)
            && demo_camera_coordinator_will_look_good(c, &cd, car))
            return i;
    }
    return -1;
}

// Highlight `idx` built for the car, or NULL for a type with no mover
// (retail's would read through NULL) or a NULL constructor.
static CameraMover *build_highlight(DemoCameraCoordinator *c, int32_t idx,
                                    struct Car *car)
{
    int32_t viewID = c->Base.ViewID;
    CameraDataItems cd;
    void *mem;

    c->CurrVortexCount++;
    camera_data_items_parse(&cd, TheCameraLoader.HighlightCameraData[idx]);
    switch (cd.Type) {
    case 0: {
        CameraShake shake;

        // The shake it draws is not used: the bank's draw only moves the
        // seed on.
        camera_loader_find_random_camera_shake(&TheCameraLoader,
                                               cd.ShakeBankNumber);
        memset(&shake, 0, sizeof shake);
        shake.NumCVs = 2;
        if (gTrackCarCameraMoverFn == NULL)
            return NULL;
        mem = bMalloc(1136, "TrackCarCameraMover", 0, 16);
        return gTrackCarCameraMoverFn(mem, viewID, car, &cd, &shake, 1);
    }
    case 1:
        if (gBumperCameraMoverFn == NULL)
            return NULL;
        mem = bMalloc(1116, "BumperCameraMover", 0, 16);
        return gBumperCameraMoverFn(mem, viewID, car, &cd);
    case 2:
        if (gTrackFlyCameraMoverFn == NULL)
            return NULL;
        mem = bMalloc(412, "TrackFlyCameraMover", 0, 16);
        return gTrackFlyCameraMoverFn(mem, viewID, &cd, car);
    default:
        return NULL;
    }
}

// The drive camera on the car: a random POV of its own, one on if it is
// the last one's, and the look-back flipped.
static void build_drive_camera(DemoCameraCoordinator *c, struct Car *car)
{
    const CarTypeInfo *ti = car->pCarTypeInfo;
    int32_t n, pov = 0;

    n = eGetCurrentViewMode() == DEMO_CAMERA_SPLIT_VIEW_MODE
        ? ti->Camera.NumSplitScreenPOVs : ti->Camera.NumFullScreenPOVs;
    if (n > 0)
        pov = bRandomI(n, &bDefaultSeed);
    if (pov == c->DefaultCameraPOV && n > 0)
        pov = (pov + 1) % n;
    c->DefaultCameraPOV = pov;
    c->DefaultCameraLookback = c->DefaultCameraLookback == 0;
    if (gDriveCameraMoverFn != NULL) {
        void *mem = bMalloc(1008, "DriveCameraMover(DCC)", 0, 16);

        c->Base.pCameraMover = gDriveCameraMoverFn(
            mem, c->Base.ViewID, car, c->DefaultCameraPOV,
            DEMO_CAMERA_LOOKBACK_SPEED, 1, c->DefaultCameraLookback, 0);
    }
}

void demo_camera_coordinator_update(DemoCameraCoordinator *c, float dt)
{
    // 0x0019a4b8.
    struct Car *car = c->pCar;
    CameraMover *m = c->Base.pCameraMover;
    int32_t reload = c->Base.NeedToReloadCameraData;
    int32_t idx = -1;
    int look = 0, bad = 0;

    (void)dt;
    c->Base.NeedToReloadCameraData = 0;
    if (m == NULL || reload != 0) {
        idx = demo_camera_coordinator_find_good_looking_highlight_camera(
            c, car);
        look = 1;
    } else if (WorldTimeFrames - c->CurrentCameraStartTime
               >= DEMO_CAMERA_MIN_FRAMES) {
        int32_t active = c->CurrentlyActiveCameraData;

        if (active == -1
            || !demo_camera_coordinator_will_look_good_data(
                   c, TheCameraLoader.HighlightCameraData[active], car)) {
            idx = demo_camera_coordinator_find_good_looking_highlight_camera(
                c, car);
            look = 1;
            if (c->CurrentlyActiveCameraData == -1 && idx == -1)
                look = 0;
        }
    }

    m = c->Base.pCameraMover;
    if (c->CurrentlyActiveCameraData != -1 && m != NULL
        && WorldTimeFrames - c->CurrentCameraStartTime
           >= DEMO_CAMERA_MIN_FRAMES) {
        bad = camera_near_a_car(m->pCamera, DEMO_CAMERA_NEAR_SHOWN);
        if (camera_near_plane_cuts_car(m->pCamera, c->pCar))
            bad = 1;
    }
    if (!look && !bad)
        return;

    if (c->Base.pCameraMover != NULL) {
        delete_mover(c->Base.pCameraMover);
        c->Base.pCameraMover = NULL;
    }
    if (idx != -1 && !bad) {
        CameraMover *n = build_highlight(c, idx, car);

        if (n != NULL) {
            int good;

            n->vtbl->Disable(n);
            n->vtbl->Update(n);
            good = !camera_near_a_car(n->pCamera, DEMO_CAMERA_NEAR_BUILT);
            if (camera_near_plane_cuts_car(n->pCamera, c->pCar))
                good = 0;
            if (good) {
                c->Base.pCameraMover = n;
                n->vtbl->Enable(n);
                c->CurrentlyActiveCameraData = idx;
                c->CurrentCameraStartTime = WorldTimeFrames;
                return;
            }
            delete_mover(n);
        }
    }
    build_drive_camera(c, car);
    c->CurrentlyActiveCameraData = -1;
    c->CurrentCameraStartTime = WorldTimeFrames;
}

// ---------------------------------------------------------------- Player

void player_begin_demo_cameras(struct Player *p, struct Car *car)
{
    // 0x00176868.
    void *mem;

    if (p->pDemoCameraCoordinator != NULL)
        return;
    player_change_camera_mover(p, CM_NONE, 0);
    if (car == NULL)
        car = p->MyCar;
    mem = bMalloc(52, "DemoCameraCoordinator", 0, 16);
    p->pDemoCameraCoordinator = (struct DemoCameraCoordinator *)
        demo_camera_coordinator_init((DemoCameraCoordinator *)mem,
                                     p->ViewID, car);
}

// ------------------------------------------------------------- the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$21DemoCameraCoordinator, 0x002b52e0.
static const VtEntry demo_vt[CAMERACOORDINATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(demo_camera_coordinator_destroy),               //   8  0x0019a4a0
    E(demo_camera_coordinator_update),                //  16  0x0019a4b8
};

#undef E

void democam_install_vtables(void)
{
    vt_install(DEMOCAMERACOORDINATOR_VTABLE, demo_vt,
               CAMERACOORDINATOR_VT_ENTRIES);
}
