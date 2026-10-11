// stillcam -- StillCameraMover. See stillcam.h.

#include "stillcam.h"

#include <stddef.h>

#include "camera.h"
#include "emath.h"
#include "realtime.h"

// ------------------------------------------------------------ the vtable

static void still_destroy_thunk(CameraMover *m)
{
    still_camera_mover_destroy((StillCameraMover *)m);
}

static void still_update_thunk(CameraMover *m)
{
    still_camera_mover_update((StillCameraMover *)m);
}

// The base's (0x0015fcf8), which cammover.c keeps to itself.
static void *still_get_car_to_follow(CameraMover *m)
{
    (void)m;
    return NULL;
}

// 0x002b1850.
const CameraMoverVtbl StillCameraMoverVtbl = {
    still_destroy_thunk,
    still_update_thunk,
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
    still_get_car_to_follow,
    camera_mover_get_target,
};

// ------------------------------------------------------ the constructor

// 0x0015e6a0.
StillCameraMover *still_camera_mover_init(StillCameraMover *m, int viewID)
{
    camera_mover_init(&m->base, viewID, CM_STILL);
    m->Eye.x = 1.0f;
    m->Eye.y = 1.0f;
    m->Eye.z = 1.0f;
    m->Look.x = 0.0f;
    m->Look.y = 0.0f;
    m->Look.z = 0.0f;
    m->Up.x = 0.0f;
    m->Up.y = 0.0f;
    m->Up.z = 1.0f;
    m->base.vtbl = &StillCameraMoverVtbl;
    m->FOV = 6000;
    return m;
}

// 0x0015e718.
void still_camera_mover_destroy(StillCameraMover *m)
{
    m->base.vtbl = &StillCameraMoverVtbl;
    camera_mover_destroy(&m->base);
}

// ---------------------------------------------------------------- Update

// 0x0015e730.
void still_camera_mover_update(StillCameraMover *m)
{
    bVector3 eye = m->Eye, look = m->Look, up = m->Up;
    uint16_t fov = m->FOV;
    bMatrix4 mat;

    eCreateLookAtMatrix(&mat, &eye, &look, &up);
    if (!CameraStopUpdating)
        m->base.pCamera->CurrentKey.FieldOfView = fov;
    camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);
}

// ----------------------------------------------------------- the setters

void still_camera_mover_set_fov(StillCameraMover *m, uint16_t fov)
{
    m->FOV = fov;
}

void still_camera_mover_set_up(StillCameraMover *m, const bVector3 *v)
{
    m->Up = *v;
}

void still_camera_mover_set_look(StillCameraMover *m, const bVector3 *v)
{
    m->Look = *v;
}

void still_camera_mover_set_eye(StillCameraMover *m, const bVector3 *v)
{
    m->Eye = *v;
}
