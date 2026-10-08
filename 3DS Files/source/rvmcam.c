// rvmcam -- RearViewMirrorCameraMover. See rvmcam.h.

#include "rvmcam.h"

#include <stddef.h>

#include "bmem.h"
#include "camera.h"
#include "car.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "shake.h"

// 0x0015f6d0 sets x and z to 0 and y to 0.5; the pad is the .bss's 0.
bVector3 RVMOffsetInCar = { 0.0f, 0.5f, 0.0f, 0.0f };

// The camera's field of view, far plane and near plane, set each Update:
// 20000, 0x43400000 and 0x3f400000.
#define RVM_FOV   20000
#define RVM_FAR_Z 192.0f
#define RVM_NEAR_Z 0.75f

// A quarter turn, for eRotateX and eRotateY.
#define RVM_QUARTER 16384

// ------------------------------------------------------------ the vtable

static void rvm_destroy_thunk(CameraMover *m)
{
    rvm_camera_mover_destroy((RearViewMirrorCameraMover *)m);
}

static void rvm_update_thunk(CameraMover *m)
{
    rvm_camera_mover_update((RearViewMirrorCameraMover *)m);
}

// 0x0015fb08.
static void *rvm_get_car_to_follow(CameraMover *m)
{
    return ((RearViewMirrorCameraMover *)m)->pCar;
}

// 0x002b1b50. GetTarget is the base's, the camera's target.
const CameraMoverVtbl RearViewMirrorCameraMoverVtbl = {
    rvm_destroy_thunk,
    rvm_update_thunk,
    camera_mover_render,
    camera_mover_nothing,       // AddJoyHandlers
    camera_mover_nothing,       // RemoveJoyHandlers
    camera_mover_get_camera_info,
    camera_mover_get_pov,
    camera_mover_is_exterior_view,
    camera_mover_is_looking_back,
    camera_mover_get_wall_gap,
    camera_mover_nothing,       // ResetState
    camera_mover_enable,
    camera_mover_disable,
    rvm_get_car_to_follow,
    camera_mover_get_target,
};

// ------------------------------------------------------ the constructor

// 0x00158f78. The car is kept whether or not the camera is frozen.
RearViewMirrorCameraMover *rvm_camera_mover_init(RearViewMirrorCameraMover *m,
                                                 int viewID, struct Car *car)
{
    Camera *cam;

    camera_mover_init(&m->base, viewID, CM_REAR_VIEW_MIRROR);
    m->base.vtbl = &RearViewMirrorCameraMoverVtbl;
    m->pCar = car;
    cam = m->base.pCamera;
    if (!CameraStopUpdating)
        cam->CarNotToRender = car;
    if (!CameraStopUpdating)
        cam->RenderDash = 0;
    return m;
}

// 0x00158fe0.
void rvm_camera_mover_destroy(RearViewMirrorCameraMover *m)
{
    m->base.vtbl = &RearViewMirrorCameraMoverVtbl;
    camera_mover_destroy(&m->base);
}

// ---------------------------------------------------------------- Update

// 0x00158ff8. The offset is added to the translation's three lanes one by
// one; its fourth is left as the product made it.
void rvm_camera_mover_update(RearViewMirrorCameraMover *m)
{
    struct Car *car = m->pCar;
    bMatrix4 toCar, body, mat;
    Camera *cam;

    eIdentity(&toCar);
    toCar.v3.x = -car->State.GeometryPosition.x;
    toCar.v3.y = -car->State.GeometryPosition.y;
    toCar.v3.z = -car->State.GeometryPosition.z;
    eTransposeMatrix(&body, &car->State.BodyMatrix);
    eRotateX(&body, &body, RVM_QUARTER);
    eRotateY(&body, &body, RVM_QUARTER);
    eRotateZ(&body, &body, 0);
    eMulMatrix(&mat, &toCar, &body);
    mat.v3.x = mat.v3.x + RVMOffsetInCar.x;
    mat.v3.y = mat.v3.y + RVMOffsetInCar.y;
    mat.v3.z = mat.v3.z + RVMOffsetInCar.z;

    cam = m->base.pCamera;
    if (!CameraStopUpdating)
        cam->CurrentKey.FieldOfView = RVM_FOV;
    cam->CurrentKey.FarZ = RVM_FAR_Z;
    cam->CurrentKey.NearZ = RVM_NEAR_Z;
    apply_camera_shake(m->base.ViewID, &mat);
    camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);
}

// ------------------------------------------------------------ the player

// The deleting destructor, virtual with flag 3.
static void delete_mover(CameraMover *m)
{
    m->vtbl->Destroy(m);
    bFree(m);
}

// 0x001767a8 (Player.obj). The first mover on the view is found as
// UpdateCameraMovers finds it: the list head's next, unless that is the
// head.
void player_set_rear_view_mirror_camera_mover(struct Player *p, uint32_t on)
{
    eView *view;
    bNode *n;
    void *mem;

    if (p->RearViewMirrorViewID == 0)
        return;
    if (p->pRVMCameraMover != NULL) {
        delete_mover(p->pRVMCameraMover);
        p->pRVMCameraMover = NULL;
    }
    view = eGetView(p->RearViewMirrorViewID);
    n = view->CameraMoverList.next;
    if (n != &view->CameraMoverList && n != NULL)
        delete_mover((CameraMover *)n);
    if (on) {
        mem = bMalloc((int)sizeof(RearViewMirrorCameraMover),
                      "RearViewMirrorCameraMover", 0, 16);
        p->pRVMCameraMover = &rvm_camera_mover_init(
            (RearViewMirrorCameraMover *)mem, p->RearViewMirrorViewID,
            p->MyCar)->base;
    }
}
