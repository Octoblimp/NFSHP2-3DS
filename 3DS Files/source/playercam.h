// playercam -- Player's camera functions: ChangeCameraMover, the POV cycle,
// and the four small ones around them. The addresses are retail's.
//
// This is step 7d: ChangeCameraMover (0x00176ae8), CycleDriveCameraPOVIndex
// (0x001786d0), RestoreCameraMover (0x00176948), RemoveCameraMovers
// (0x00177430), EnableCameraMovers (0x001774a8) and DisableCameraMovers
// (0x00177558). They sit apart from player.c because they build movers,
// and player.c goes into harnesses that have no use for drivecam.c and
// orbitcam.c.
//
// ChangeCameraMover builds the drive camera and the orbit camera itself.
// Every other mover is a seam: a constructor the port does not have yet,
// behind a function pointer that is NULL until its class is ported. With
// the seam NULL nothing is allocated and the player is left with no
// camera, as type 0 leaves it. The two zone jumpers (types 15 and 16,
// TrackCarCameraMover over the jump cam's route) are one seam for the
// whole case, since all of it waits on PreviewRoute and CameraDataItems.
// The camera coordinators, the NIS manager and the driving line are seams
// too.
//
// Movers are deleted as retail deletes them, through the virtual
// destructor, so the orbit's joystick handlers come off: the vtable's
// Destroy, then bFree.
//
// Written up in docs/formats/camera.md, "The player's cameras"; checked on
// retail's image by tools/playercam_check.py.

#ifndef PLAYERCAM_H
#define PLAYERCAM_H

#include <stdint.h>

#include "bvector.h"
#include "cammover.h"
#include "joystick.h"

struct Car;
struct NisCameraCoordinator;
struct NisManager;
struct Player;
struct PreviewRoute;
struct VisibleDrivingLine;

// 0x00176ae8. Delete the demo, countdown and NIS coordinators, then, unless
// the player's mover is already `type`, retire it and build the new one.
// With `keep` the old mover is disabled and saved, and the one saved
// before it moves back to pSavedCameraMover2; without `keep` it is
// deleted. The car is the player's, or the first on World's CarList.
// Types 4-12, and anything above 17 taken unsigned, build the orbit
// camera. Whatever is built gets the player.
void player_change_camera_mover(struct Player *p, CameraMoverType type,
                                int keep);

// 0x001786d0. `index` mod 4, as C's remainder, then the first index from
// there, stepping mod 4, whose POV the drive camera has. Unless SkipFE is
// set or the car has a dash, only POV_BUMPER and POV_OUTSIDE count. If none
// does, 0. That goes to SetPOVIndex and comes back. With no drive camera,
// or one with no CameraInfo, the index mod 4 comes straight back.
int player_cycle_drive_camera_pov_index(struct Player *p, int index);

// 0x00176948. Delete the current mover and pop the saved one, which looks
// back if bLookBack says so when it is a drive camera. Then Enable it.
// Retail calls Enable through NULL when nothing was saved; the port does
// nothing.
void player_restore_camera_mover(struct Player *p);

// 0x00177430. ChangeCameraMover(0, 0), then delete both saved movers.
void player_remove_camera_movers(struct Player *p);

// 0x001774a8 and 0x00177558. The player's mover and the mirror's, the
// demo and countdown coordinators, the NIS coordinator and the driving
// line.
void player_enable_camera_movers(struct Player *p);
void player_disable_camera_movers(struct Player *p);

// SkipFE (gp-23220), which main.c points at the flow's skipFE. NULL reads
// as 0, the value the disc ships.
extern const int *gPlayerCamSkipFE;

// ---------------------------------------------------------------- the seams

// The coordinators' virtual destructor with flag 3 (their vtable is at
// +24), BaseCameraCoordinator::Enable (0x00199b90) and Disable
// (0x00199b48).
extern void (*gCameraCoordinatorDeleteFn)(void *coord);
extern void (*gCameraCoordinatorEnableFn)(void *coord);
extern void (*gCameraCoordinatorDisableFn)(void *coord);

// NisManager's DeleteNisCameraCoordinator (0x001b2b90),
// EnableNisCameraCoordinator (0x001b2c20) and DisableNisCameraCoordinator
// (0x001b2bd0).
extern void (*gNisDeleteCameraCoordinatorFn)(struct NisManager *mgr,
                                             struct NisCameraCoordinator *c);
extern void (*gNisEnableCameraCoordinatorFn)(struct NisManager *mgr,
                                             struct NisCameraCoordinator *c);
extern void (*gNisDisableCameraCoordinatorFn)(struct NisManager *mgr,
                                              struct NisCameraCoordinator *c);

// Retail's VisibleDrivingLine Enable and Disable (thunks at 0x00183208 and
// 0x00183200 onto 0x00161720 and 0x001617a0). They add or remove the
// line's AcidEmitters, a member at +60.
extern void (*gVisibleDrivingLineEnableFn)(struct VisibleDrivingLine *l);
extern void (*gVisibleDrivingLineDisableFn)(struct VisibleDrivingLine *l);

// The constructors, each called on bMalloc(size, name, 0, 16). Each
// returns the mover it built, as retail's constructors return `this`.
extern CameraMover *(*gDebugWorldCameraMoverFn)(       // 76, 0x0015b268
    void *mem, int viewID, const bVector3 *pos, const bVector3 *dir,
    JoystickPort port);
extern CameraMover *(*gTrackRouteEditorCameraMoverFn)( // 44, 0x0015c010
    void *mem, int viewID, JoystickPort port);
extern CameraMover *(*gZoneFreezeCameraMoverFn)(       // 872, 0x00160298
    void *mem, int viewID, struct Car *car, CameraMover *saved);
extern CameraMover *(*gZonePreviewCameraMoverFn)(      // 1104, 0x00161f98
    void *mem, int viewID, struct PreviewRoute *route, bVector3 *pos);
extern CameraMover *(*gCubicCameraMoverFn)(            // 160, 0x0015e7b0
    void *mem, int viewID, struct Car *car);

// PreviewRoute's virtual destructor with flag 3 (0x00164848), for the
// route the zone preview was built from.
extern void (*gPreviewRouteDeleteFn)(struct PreviewRoute *route);

// Types 15 and 16 whole, `second` telling them apart: the jump cam's
// CameraDataItems, eyes, banks and field-of-view table off pJumpCamRoute,
// then TrackCarCameraMover (1136 bytes, 0x00159130). Returns the mover.
extern CameraMover *(*gPlayerJumpCamMoverFn)(struct Player *p,
                                             struct Car *car, int second);

#endif
