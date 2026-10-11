// stillcam -- StillCameraMover (CM_STILL), a camera that looks from a
// point at a point. CameraMover.obj's; the addresses are retail's.
//
// Ported: the constructor (0x0015e6a0), the destructor (0x0015e718),
// Update (0x0015e730) and the four setters (0x0015fa80 .. 0x0015fab4). The
// vtable is 0x002b1850: the base's but for the destructor and Update.
//
// Select Track makes one on view 1 for its spinning track model, and its
// Tick writes the eye and the target straight in (btracksel.c). The
// demo has the same class at 0x0015ae50.
//
// Written up in docs/formats/camera.md, "The still camera"; checked on
// retail's image by tools/selcam_check.py.

#ifndef STILLCAM_H
#define STILLCAM_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "cammover.h"

// 112 bytes, as Select Track's bMalloc asks.
typedef struct StillCameraMover {
    CameraMover base;       //  0
    int32_t     Pad44;      // 44  never written
    bVector3    Eye;        // 48  (1, 1, 1) from the constructor
    bVector3    Look;       // 64  (0, 0, 0)
    bVector3    Up;         // 80  (0, 0, 1)
    uint16_t    FOV;        // 96  6000
    uint16_t    Pad98[7];   // 98
} StillCameraMover;          // 112

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char stillcam_layout_check[
    (offsetof(StillCameraMover, Eye) == 48
     && offsetof(StillCameraMover, FOV) == 96
     && sizeof(StillCameraMover) == 112) ? 1 : -1];
#endif

extern const CameraMoverVtbl StillCameraMoverVtbl;

// 0x0015e6a0. The constructor writes the vectors' x, y and z, not their
// fourth lanes.
StillCameraMover *still_camera_mover_init(StillCameraMover *m, int viewID);

// 0x0015e718: the vtable back, then the base's destructor.
void still_camera_mover_destroy(StillCameraMover *m);

// 0x0015e730: eCreateLookAtMatrix from the eye, the target and up; the
// field of view onto the camera unless Camera::StopUpdating is set; and
// the matrix to the camera by RealTimeElapsed.
void still_camera_mover_update(StillCameraMover *m);

// SetFOV (0x0015fa80), SetUp (0x0015fa88), SetLook (0x0015fa98) and
// SetEye (0x0015faa8). Each vector is copied whole, its fourth lane too.
void still_camera_mover_set_fov(StillCameraMover *m, uint16_t fov);
void still_camera_mover_set_up(StillCameraMover *m, const bVector3 *v);
void still_camera_mover_set_look(StillCameraMover *m, const bVector3 *v);
void still_camera_mover_set_eye(StillCameraMover *m, const bVector3 *v);

#endif
