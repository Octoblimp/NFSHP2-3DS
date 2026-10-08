// trackflycam -- TrackFlyCameraMover (CM_TRACK_FLY). The addresses are
// retail's.
//
// The mover flies the camera along an eye spline while it looks along a
// look spline, each at its own speed or, with a car and the record's lock
// set, as far along as the car has got round the track between the
// record's two area percentages. A bank spline rolls the up vector. With a
// car the field of view comes from the record's 32-entry table over its
// two percentages, as TrackCarCameraMover's does; without one it is 13020
// (71.5 degrees). The fly-by camera coordinator builds one with no car, on
// each track's PreRace_01 camera, behind the Starting Grid.
//
// Ported: the constructor (0x00159d08), the destructor (0x00159de8),
// Update (0x00159e98), IsFinished (0x0015a2a0), GetTarget (0x00159e78) and
// GetCarToFollow (0x0015faf8); the vtable is 0x002b1a50.
//
// Written up in docs/formats/camera-coordinator.md, "The fly-by"; checked
// on retail's image by tools/trackflycam_check.py.

#ifndef TRACKFLYCAM_H
#define TRACKFLYCAM_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "cammover.h"
#include "spline.h"
#include "trackcarcam.h"

struct Car;

// 412 bytes, the demo's .mdebug record, which retail's readers agree with
// (FlyByCameraCoordinator's bMalloc is 412).
typedef struct TrackFlyCameraMover {
    CameraMover     base;             // 0
    CameraDataItems CD;               // 44
    Spline          EyeSpline;        // 208
    Spline          BankSpline;       // 256
    Spline          LookSpline;       // 304
    Spline          FOVSpline;        // 352
    float           EyeSplineParam;   // 400
    float           LookSplineParam;  // 404
    struct Car     *CarToFollow;      // 408
} TrackFlyCameraMover;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char trackflycam_layout_check[
    (offsetof(TrackFlyCameraMover, CD) == 44
     && offsetof(TrackFlyCameraMover, EyeSpline) == 208
     && offsetof(TrackFlyCameraMover, FOVSpline) == 352
     && offsetof(TrackFlyCameraMover, EyeSplineParam) == 400
     && offsetof(TrackFlyCameraMover, CarToFollow) == 408
     && sizeof(TrackFlyCameraMover) == 412) ? 1 : -1];
#endif

#define TRACK_FLY_CAMERA_MOVER_SIZE 412

// Retail's 0x002b1a50: the base's, but for the destructor, Update,
// GetCarToFollow and GetTarget.
extern const CameraMoverVtbl TrackFlyCameraMoverVtbl;

// 0x00159d08. A CM_TRACK_FLY mover on `viewID`, with a copy of `cd`, its
// four splines over the copy's arrays (eye and bank over NumEyeVerts, look
// over NumLookVerts, FOV over 32), both parameters at 0, the camera's near
// and far planes the record's, and `car` (which may be NULL) to follow.
// Nothing else of the camera is touched. Returns the mover.
TrackFlyCameraMover *track_fly_camera_mover_init(TrackFlyCameraMover *m,
                                                 int viewID,
                                                 const CameraDataItems *cd,
                                                 struct Car *car);

// 0x00159de8. The camera's focal distance and depth of field to 0, unless
// it is stopped; ClearVelocity set; the four splines; then the base.
void track_fly_camera_mover_destroy(TrackFlyCameraMover *m);

// 0x00159e98. Not paused by the game flow. `dt` is the world's step
// (WorldTimeElapsed), which moves the two parameters at their speeds times
// 25; `elapsed` (RealTimeElapsed) is what SetCameraMatrix is given. The
// camera's target distance is the eye's to the look point, its focal
// distance that but at least 2, and its depth of field 30, each unless the
// camera is stopped.
void track_fly_camera_mover_update(TrackFlyCameraMover *m, float dt,
                                   float elapsed);

// 0x0015a2a0. Both splines run out: each has no speed, or its parameter
// is at its last point.
int track_fly_camera_mover_is_finished(const TrackFlyCameraMover *m);

// 0x00159e78. The car's GeometryPosition, or with no car the camera's
// target.
const bVector3 *track_fly_camera_mover_get_target(
    const TrackFlyCameraMover *m);

#endif
