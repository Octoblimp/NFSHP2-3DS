// zonecam -- zonecameras.cpp's movers, in part: ZoneFreezeCameraMover
// (CM_ZONE_FREEZE), the freeze zone's camera. The addresses are retail's.
//
// A freeze zone stops the world for three seconds while the camera swings
// half round the player's car and back. The constructor lays out the
// swing: 32 eye points on a circle of 8 about the car, 2 above the ground
// it will be at a frame on, a little more than two thirds of a turn from
// where the camera is now, with 32 look points on a circle of 0.1 at 1.2,
// each eye pushed out of the walls and up off the ground. Update then
// blends from the camera onto the eye spline for 0.4 s, runs along both
// splines for 2 s, and blends back onto the camera's own course for the
// last 0.6 s, with the radial blur up during the blends and the zone's
// wind sample swept round the listener.
//
// Ported: the constructor (0x00160298), the destructor (0x00161000),
// Duration (0x00161098) and Update (0x001610a8), and the two free
// functions they share with the other zone cameras, ConstrainToTopology
// (0x0015fd80) and EnsureEyeAboveGround (0x00160048). The vtable is
// 0x002b20d0: the base's but for the destructor and Update. The Zone
// Preview is zonepreview.c's, and the zone jumpers are TrackCarCameraMovers
// (playercam.c). The file's other two, DumpCubic (0x0015fd78) and
// ConstrainCubic (0x001600d8), have no caller in retail and are not ported.
//
// Written up in docs/formats/camera.md, "The Zone Freeze camera"; checked
// on retail's image by tools/zonecam_check.py.

#ifndef ZONECAM_H
#define ZONECAM_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"
#include "bvector.h"
#include "cammover.h"
#include "spline.h"
#include "topology.h"

struct Car;

// 872 bytes, as Player::ChangeCameraMover's bMalloc asks; the names are
// the demo's .mdebug record's (728 bytes there, its TopologyCoordinate 560).
typedef struct ZoneFreezeCameraMover {
    CameraMover        base;            //   0
    float              fTime;           //  44  seconds since the freeze
    float              fTanFov;         //  48  of the camera's field of view
    BSpline3D         *pEyeBlendIn;     //  52  camera to the eye spline
    BSpline3D         *pEyeBlendOut;    //  56  eye spline to the camera
    BSpline3D         *pLookBlendIn;    //  60  the same for the look point
    BSpline3D         *pLookBlendOut;   //  64
    BSpline           *pFocusPull;      //  68  the eye's distance, 1 always
    Spline             EyeSpline;       //  72
    Spline             LookSpline;      // 120
    TopologyCoordinate Topology;        // 168
} ZoneFreezeCameraMover;                 // 872

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char zonecam_layout_check[
    (offsetof(ZoneFreezeCameraMover, fTime) == 44
     && offsetof(ZoneFreezeCameraMover, pFocusPull) == 68
     && offsetof(ZoneFreezeCameraMover, EyeSpline) == 72
     && offsetof(ZoneFreezeCameraMover, LookSpline) == 120
     && offsetof(ZoneFreezeCameraMover, Topology) == 168
     && sizeof(ZoneFreezeCameraMover) == 872) ? 1 : -1];
#endif

extern const CameraMoverVtbl ZoneFreezeCameraMoverVtbl;

// 0x0015fd80. eWAYS and eSIDES: 1 is both ways and both sides. A move from
// `from` to `to` constrained by rotation, then by scale, each 0.7 off a
// polygon (gp-30892) with a lift of 1, from both sides only with `sides`
// 1; with `ways` 1, the move back from `to` to `from` the same, which moves
// `from`. 1 when any of them crossed a polygon.
int32_t zone_constrain_to_topology(TopologyCoordinate *tc, bVector3 *from,
                                   bVector3 *to, int32_t ways,
                                   int32_t sides);

// 0x00160048. The interest box 10 about the eye, and an eye less than
// `clearance` above or below the ground there is put `clearance` above it.
void zone_ensure_eye_above_ground(TopologyCoordinate *tc, bVector3 *eye,
                                  float clearance);

// 0x00160298. `saved` is the mover the player had, which says whether the
// camera was outside the car; `car` is the player's. Every point is taken
// a frame on, by WorldTimeElapsed. The five blends are bMalloc'd
// (zonecameras.cpp lines 573, 590, 610, 626 and 635), their coefficients
// and parameters left as the heap had them. The camera's two render flags
// come off unless Camera::StopUpdating is set.
ZoneFreezeCameraMover *zone_freeze_camera_mover_init(ZoneFreezeCameraMover *m,
                                                     int viewID,
                                                     struct Car *car,
                                                     CameraMover *saved);

// 0x00161000: the vtable back, RadialBlurOff for the player, the blends
// freed, then the TopologyCoordinate, both splines and the base.
void zone_freeze_camera_mover_destroy(ZoneFreezeCameraMover *m);

// 0x00161098: 3 seconds, which the world's pause takes too.
float zone_freeze_camera_mover_duration(void);

// 0x001610a8. Nothing while the game flow is paused; else a RealTimeElapsed
// step along the swing, the matrix to the camera by the same, the field of
// view unless Camera::StopUpdating is set, and with SoundEnabled the zone
// sample's azimuth, pitch and volume.
void zone_freeze_camera_mover_update(ZoneFreezeCameraMover *m);

// For Player::ChangeCameraMover's seam (playercam.h): the constructor on
// its 872 bytes.
CameraMover *zone_freeze_camera_mover_new(void *mem, int viewID,
                                          struct Car *car,
                                          CameraMover *saved);

#endif
