// bumpercam -- BumperCameraMover (CM_BUMPER). The addresses are retail's.
//
// The mover flies a camera record in the car's own frame: the eye along the
// eye spline and the look along the look spline, each at its own speed or,
// with the record's lock, as far along as the car has got round the track
// between the record's two area percentages. A bank spline rolls the up
// vector. The road noise under the car shakes the eye, which is held 0.7
// over the ground under it (the mover's own TopologyCoordinate, which is
// never given an interest box), and the field of view comes from the
// record's 32-entry table over its two percentages. The look-at in the
// car's frame is carried into the world by the car's GeometryPosition and
// BodyMatrix. While the race is racing (RaceStage 4), the eye is also kept
// off the walls and out of the car (0x00157c60).
//
// The pre-race coordinator builds one on each of INGAMEB's four pre-race
// cameras, and the countdown coordinator on a COUNTDOWN_n camera, which the
// retail disc does not have.
//
// Ported: the constructor (0x00158800), the destructor (0x00158910),
// IsFinished (0x001589c8), Update (0x00158a68), GetTarget (0x001589a8),
// GetCarToFollow (0x0015fb10) and the wall routine (0x00157c60); the
// vtable is 0x002b1bd0.
//
// Written up in docs/formats/camera-coordinator.md, "The pre-race"; checked
// on retail's image by tools/bumpercam_check.py.

#ifndef BUMPERCAM_H
#define BUMPERCAM_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "cammover.h"
#include "spline.h"
#include "topology.h"
#include "trackcarcam.h"

struct Car;

// 1116 bytes, the coordinators' bMalloc. The offsets are the constructor's
// stores; the names follow TrackFlyCameraMover's, whose fields these are,
// with the TopologyCoordinate at the end.
typedef struct BumperCameraMover {
    CameraMover        base;                  //    0
    CameraDataItems    CD;                    //   44
    Spline             EyeSpline;             //  208
    Spline             BankSpline;            //  256
    float              EyeSplineParam;        //  304
    Spline             LookSpline;            //  308
    float              LookSplineParam;       //  356
    Spline             FOVSpline;             //  360
    struct Car        *CarToFollow;           //  408
    TopologyCoordinate TheTopologyCoordinate; //  412
} BumperCameraMover;                          // 1116

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char bumpercam_layout_check[
    (offsetof(BumperCameraMover, CD) == 44
     && offsetof(BumperCameraMover, EyeSpline) == 208
     && offsetof(BumperCameraMover, BankSpline) == 256
     && offsetof(BumperCameraMover, EyeSplineParam) == 304
     && offsetof(BumperCameraMover, LookSpline) == 308
     && offsetof(BumperCameraMover, LookSplineParam) == 356
     && offsetof(BumperCameraMover, FOVSpline) == 360
     && offsetof(BumperCameraMover, CarToFollow) == 408
     && offsetof(BumperCameraMover, TheTopologyCoordinate) == 412
     && sizeof(BumperCameraMover) == 1116) ? 1 : -1];
#endif

#define BUMPER_CAMERA_MOVER_SIZE 1116

// Retail's 0x002b1bd0: the base's, but for the destructor, Update,
// GetCarToFollow and GetTarget.
extern const CameraMoverVtbl BumperCameraMoverVtbl;

// 0x00158800. A CM_BUMPER mover on `viewID` following `car`, with a copy of
// `cd`, its four splines over the copy's arrays (eye and bank over
// NumEyeVerts, look over NumLookVerts, FOV over 32), both parameters at 0
// and its TopologyCoordinate built. Unless the camera is stopped, the
// camera renders every car and no dash, with a field of view of 13020
// (71.5 degrees); its near and far planes are the record's either way.
BumperCameraMover *bumper_camera_mover_init(BumperCameraMover *m, int viewID,
                                            struct Car *car,
                                            const CameraDataItems *cd);

// The coordinators' gBumperCameraMoverFn: the constructor on `mem`.
CameraMover *bumper_camera_mover_construct(void *mem, int32_t viewID,
                                           struct Car *car,
                                           CameraDataItems *cd);

// 0x00158910. The camera's focal distance and depth of field to 0, unless
// it is stopped; then the TopologyCoordinate, the four splines and the
// base. Unlike TrackFlyCameraMover's, it leaves ClearVelocity alone.
void bumper_camera_mover_destroy(BumperCameraMover *m);

// 0x00158a68. Nothing while IsGameFlowPaused. `dt` is the world's step
// (WorldTimeElapsed), which moves the two parameters at their speeds times
// 25; `elapsed` (RealTimeElapsed) is what SetCameraMatrix is given. The
// camera's target distance is the eye's to the look point, its focal
// distance that but at least 2, and its depth of field 7.5, each unless the
// camera is stopped.
void bumper_camera_mover_update(BumperCameraMover *m, float dt,
                                float elapsed);

// 0x001589c8. Both splines run out: each has no speed, or its parameter
// is at its last point.
int bumper_camera_mover_is_finished(const BumperCameraMover *m);

// The coordinators' gBumperCameraMoverIsFinishedFn.
int32_t bumper_camera_mover_is_finished_fn(CameraMover *m);

// 0x001589a8. The car's GeometryPosition, or with no car the camera's
// target.
const bVector3 *bumper_camera_mover_get_target(const BumperCameraMover *m);

#endif
