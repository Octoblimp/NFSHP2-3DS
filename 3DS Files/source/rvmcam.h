// rvmcam -- RearViewMirrorCameraMover (CM_REAR_VIEW_MIRROR) and
// Player::SetRearViewMirrorCameraMover. The addresses are retail's.
//
// The mirror's mover looks back out of the player's car. Its matrix moves
// the world on to the car's GeometryPosition and turns it by the
// transpose of the car's BodyMatrix, given a quarter turn about x and then
// about y; RVMOffsetInCar is then added to the matrix's translation, in
// the camera's own frame. The camera's field of view is 20000 (110
// degrees), the near plane 0.75 and the far plane 192. The matrix is
// shaken as the view's and given to the camera by RealTimeElapsed.
//
// Player 1 owns one, on view 3 (EVIEW_ID_PLAYER1_RVM), while the HUD has
// the mirror: Player::SetHudFeatures calls SetRearViewMirrorCameraMover
// whenever HUD_REAR_VIEW_MIRROR changes. With a mover on views 1 and 3,
// eUpdateViewMode gives view mode 2, which turns the mirror's target on.
//
// Ported: the constructor (0x00158f78), the destructor (0x00158fe0),
// Update (0x00158ff8), GetCarToFollow (0x0015fb08), the static init that
// sets RVMOffsetInCar (0x0015f6d0) and Player::SetRearViewMirrorCameraMover
// (0x001767a8); the vtable is 0x002b1b50.
//
// Written up in docs/formats/camera.md, "The rear-view mirror"; checked on
// retail's image by tools/rvmcam_check.py.

#ifndef RVMCAM_H
#define RVMCAM_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "cammover.h"

struct Car;
struct Player;

// 48 bytes (.mdebug: the base, then pCar).
typedef struct RearViewMirrorCameraMover {
    CameraMover  base;      //  0
    struct Car  *pCar;      // 44
} RearViewMirrorCameraMover;  // 48

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char rvmcam_layout_check[
    (offsetof(RearViewMirrorCameraMover, pCar) == 44
     && sizeof(RearViewMirrorCameraMover) == 48) ? 1 : -1];
#endif

// The camera's place in the car's frame, 0x00334180: (0, 0.5, 0).
extern bVector3 RVMOffsetInCar;

extern const CameraMoverVtbl RearViewMirrorCameraMoverVtbl;

// 0x00158f78. The camera stops drawing the car, and its dash, unless
// Camera::StopUpdating is set.
RearViewMirrorCameraMover *rvm_camera_mover_init(RearViewMirrorCameraMover *m,
                                                 int viewID, struct Car *car);

// 0x00158fe0: the vtable back, then the base's destructor.
void rvm_camera_mover_destroy(RearViewMirrorCameraMover *m);

// 0x00158ff8. Not held by the game's pause.
void rvm_camera_mover_update(RearViewMirrorCameraMover *m);

// 0x001767a8. Nothing for a player with no mirror view. Otherwise the
// player's mirror mover is deleted, and then the first mover on the
// mirror's view, whoever's it is; with `on`, a new one is made on that
// view for the player's car.
void player_set_rear_view_mirror_camera_mover(struct Player *p, uint32_t on);

#endif
