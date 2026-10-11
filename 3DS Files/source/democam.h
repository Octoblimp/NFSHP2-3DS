// democam -- CameraCoordinator.obj's DemoCameraCoordinator (0x0019a440 ..
// 0x0019abd8), the near-plane test it asks (0x001044c8, no symbol) and
// Player::BeginDemoCameras' coordinator.
//
// The demo camera is what the race shows after the finish. The race
// coordinator's POSTRACE builds one on view 1 for the car of the player
// who finished best, and with two players a player who has finished gets
// one on the other's car until that one finishes too. It puts one of the
// track's highlight cameras on the car: the first, in the bundle's order,
// whose area holds the car and which faces the way the car is going. A
// highlight is kept while its area still holds the car, at least 56 frames
// of world time each time it changes. A camera that comes too near a car
// (2 m, or 5 m for one just built) or whose near plane cuts the car's box
// is not used, and with no highlight to show the coordinator gives the car
// a drive camera, a random POV of the car's, looking back every other
// time.
//
// Retail plays the race's replay under it. The port has no replay yet, so
// it shows the live race: the AI cars drive on and the player's car
// brakes to a stop.
//
// PostRaceCameraCoordinator (0x0019b280 .. 0x0019b4ac, 176 bytes, table
// 0x002b5280) is in the image but nothing builds it: no call and no
// pointer reaches its constructor. It is not ported.
//
// Written up in docs/formats/camera-coordinator.md, "The demo camera", and
// checked on retail's image by tools/democam_check.py.
#ifndef DEMOCAM_H
#define DEMOCAM_H

#include <stddef.h>
#include <stdint.h>

#include "camera.h"
#include "cameracoord.h"
#include "cammover.h"
#include "trackcarcam.h"

struct Car;
struct Player;

// DemoCameraCoordinator, 52 bytes (the demo's type#2341, retail's the
// same; bMalloc'd by its three makers).
typedef struct DemoCameraCoordinator {
    BaseCameraCoordinator Base;          //  0
    struct Car  *pCar;                   // 28  the car it shows
    int32_t      DefaultCameraLookback;  // 32  the last drive camera's
    int32_t      DefaultCameraPOV;       // 36  the last drive camera's
    int32_t      CurrentCameraStartTime; // 40  WorldTimeFrames; unset
                                         //     until the first camera
    int32_t      CurrentlyActiveCameraData; // 44  a highlight, or -1
    int32_t      CurrVortexCount;        // 48
} DemoCameraCoordinator;

#if UINTPTR_MAX == 0xffffffffu
typedef char democoord_layout_check[
    (offsetof(DemoCameraCoordinator, pCar) == 28
     && offsetof(DemoCameraCoordinator, CurrentCameraStartTime) == 40
     && offsetof(DemoCameraCoordinator, CurrVortexCount) == 48
     && sizeof(DemoCameraCoordinator) == 52) ? 1 : -1];
#endif

// _vt$21DemoCameraCoordinator.
#define DEMOCAMERACOORDINATOR_VTABLE 0x002b52e0u

// How many frames of world time a camera is kept before it is looked at
// again.
#define DEMO_CAMERA_MIN_FRAMES 56

// What Update builds: TrackCarCameraMover's constructor (0x00159130) on
// 1136 bytes of bMalloc's, with the coordinator's view, the car, the
// camera's data, a shake and 1 for the focus effects (trackcarcam.c), and
// DriveCameraMover's (0x0015c258) on 1008, with the view, the car, the POV,
// the look-back speed, disableLag, lookBack and perfectFocus (drivecam.c).
// The Bumper and TrackFly movers come through cameracoord.h's seams. With
// a constructor NULL nothing is allocated and nothing is built.
extern CameraMover *(*gTrackCarCameraMoverFn)(void *mem, int32_t viewID,
                                              struct Car *car,
                                              const CameraDataItems *cd,
                                              const CameraShake *shake,
                                              int32_t focusEffects);
extern CameraMover *(*gDriveCameraMoverFn)(void *mem, int32_t viewID,
                                           struct Car *car, int32_t pov,
                                           float lookbackSpeed,
                                           int32_t disableLag,
                                           int32_t lookBack,
                                           int32_t perfectFocus);

// 0x001044c8, which has no symbol (the name is the port's). Whether the
// race view's near plane cuts the car's box: the car's eight corners
// (GetCarSpaceBoundingBox's, from min to max, x slowest and z fastest) go
// through the car's matrix (BodyMatrix with Position as its last row) and
// the camera's, and the near plane is the camera's NearZ scaled by
// tan(aBaselineFovZ / 2) / tan(FieldOfView / 2), as CreateViewMatricies
// scales it for views 1 and 2. 1 when two corners next to each other in
// that order are on either side of it; a corner on the plane is on
// neither.
int32_t camera_near_plane_cuts_car(const Camera *cam, struct Car *car);

// 0x0019a440. The base's constructor, the car, the demo table, the
// loader's VortexCount, no camera (-1), and 0 for the POV and the
// look-back. The start time is left as it was. No Update.
DemoCameraCoordinator *demo_camera_coordinator_init(
    DemoCameraCoordinator *c, int32_t viewID, struct Car *car);

// The constructor as rcstates.c's gDemoCameraCoordinatorCtorFn calls it,
// on the 52 bytes it bMallocs.
void *demo_camera_coordinator_construct(void *mem, int32_t viewID,
                                        struct Car *car);

// 0x0019a4a0: the demo table, then the base's destructor.
void demo_camera_coordinator_destroy(DemoCameraCoordinator *c,
                                     int32_t flags);

// 0x0019a9d0. Whether the car's x and y are in one of the camera's area
// faces (eIsPointInPoly on each three corners, in order).
int32_t demo_camera_coordinator_will_look_good(DemoCameraCoordinator *c,
                                               const CameraDataItems *cd,
                                               struct Car *car);

// 0x0019a988. The same on a camera's raw block, parsed first.
int32_t demo_camera_coordinator_will_look_good_data(
    DemoCameraCoordinator *c, char *data, struct Car *car);

// 0x0019aad8. The first highlight camera, in the loader's order, that
// faces the way the car is going and will look good, or -1. A camera
// faces it when its Backwards is set exactly when the car is going
// backwards: the track run backwards (TrackDirection 1) or the car facing
// the wrong way, but not both. IsFacingWrongWay is asked twice for each
// camera.
int32_t demo_camera_coordinator_find_good_looking_highlight_camera(
    DemoCameraCoordinator *c, struct Car *car);

// 0x0019a4b8. dt is unread. The reload mark is cleared.
//
// With no mover or the mark set, a highlight is looked for. Otherwise,
// once the camera has been up 56 frames, a highlight still holding the car
// is kept, and in any other case one is looked for; with the drive camera
// up and none found nothing changes. Then, with a highlight up for 56
// frames, the camera showing is bad when it is within 2 m of any car of
// the World's or its near plane cuts the car (both asked).
//
// Nothing more happens unless one was looked for or the camera is bad.
// The mover is deleted. A highlight found, with the camera not bad, is
// built (the vortex count up one; type 0 a TrackCarCameraMover with a
// shake of nothing on two points, after FindRandomCameraShake draws on the
// camera's bank for nothing; type 1 a BumperCameraMover; type 2 a
// TrackFlyCameraMover), disabled, updated once and looked at: within 5 m
// of a car, or its near plane cutting the car, and it is deleted;
// otherwise it is the coordinator's, enabled, and the camera is that
// highlight. In every other case the car gets a drive camera: a random
// POV of the car's full-screen ones (split-screen in view mode 3), one on
// if it is the last one's, the look-back flipped; the camera is -1. Either
// way the start time is WorldTimeFrames.
void demo_camera_coordinator_update(DemoCameraCoordinator *c, float dt);

// Player::BeginDemoCameras (0x00176868). Nothing if the player has a demo
// coordinator. Otherwise the player's mover goes (ChangeCameraMover to
// CM_NONE) and a coordinator is built on the player's view for `car`, or
// the player's own when it is NULL. rcstates.c's gPlayerBeginDemoCamerasFn.
void player_begin_demo_cameras(struct Player *p, struct Car *car);

// The table, into vtable.h's registry. main.c calls it at boot.
void democam_install_vtables(void);

#endif
