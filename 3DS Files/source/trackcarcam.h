// trackcarcam -- TrackCarCameraMover (CM_TRACK_CAR), with the two records it
// is built from, CameraDataItems and CameraShake. The addresses are
// retail's.
//
// The mover flies the camera along an eye spline while it looks at a car:
// how far along comes from how far round the track the car has got
// between the record's two percentages (or from a speed, or from a wipe
// between two points), the field of view from a 32-entry spline over the
// same span, the look point is pushed up and sideways by the record's
// compensations and the shake, then sprung, and a bank spline rolls the
// up vector. The jump cam (player types 15 and 16) is its only user in the
// port; the record's area and look splines are the track cameras', which
// the race does not have.
//
// Ported: the constructor (0x00159130), the destructor (0x00159490),
// Update (0x00159588), CalcSpringForce (0x00159540), GetTarget
// (0x00159520) and GetCarToFollow (0x0015fb00); the vtable is 0x002b1ad0.
//
// Written up in docs/formats/camera.md, "The jump cam's mover"; checked on
// retail's image by tools/trackcarcam_check.py.

#ifndef TRACKCARCAM_H
#define TRACKCARCAM_H

#include <stddef.h>
#include <stdint.h>

#include "banim.h"
#include "bvector.h"
#include "cammover.h"
#include "spline.h"

struct Car;

// 164 bytes, the demo's .mdebug record, which retail's readers agree
// with. The constructor copies it whole (0x0019bab8); the arrays stay the
// owner's.
typedef struct CameraDataItems {
    int32_t   Type;              // 0
    char     *Name;              // 4
    int32_t   IsFOVIso;          // 8
    float     MinPercent;        // 12
    float     MaxPercent;        // 16
    float     EyeSplineSpeed;    // 20
    float     LookSplineSpeed;   // 24
    float     FOVSplineSpeed;    // 28
    int32_t   LockEyeSpeedToCar; // 32
    int32_t   LockLookSpeedToCar;// 36
    float     MinAreaPercent;    // 40
    float     MaxAreaPercent;    // 44
    float     NearClip;          // 48
    float     FarClip;           // 52
    int32_t   Backwards;         // 56
    bVector3 *FOVTable;          // 60  32 of them, degrees in x
    int32_t   NumAreaVerts;      // 64
    bVector2 *AreaVerts;         // 68
    int32_t   NumAreaFaces;      // 72
    void     *AreaFaces;         // 76
    int32_t   NumEyeVerts;       // 80
    bVector3 *EyeVerts;          // 84
    bVector3 *BankVerts;         // 88  roll, as a BAM, in x
    int32_t   NumLookVerts;      // 92
    bVector3 *LookVerts;         // 96
    float     SpringXVel;        // 100
    float     SpringYVel;        // 104
    float     SpringZVel;        // 108
    float     SpringDamp;        // 112
    float     SpringConst;       // 116
    float     LookOffsetX;       // 120
    float     LookOffsetY;       // 124
    float     LookOffsetZ;       // 128
    float     EnterVertComp;     // 132
    float     EnterHorizComp;    // 136
    float     LeaveVertComp;     // 140
    float     LeaveHorizComp;    // 144
    int32_t   IsLeaveSet;        // 148
    float     WipeDistance;      // 152
    int32_t   WipeAutoDisable;   // 156
    int32_t   ShakeBankNumber;   // 160
} CameraDataItems;

// 560 bytes, the .mdebug record.
typedef struct CameraShake {
    char     ShakeName[32];      // 0
    int32_t  BankNumber;         // 32
    float    Speed;              // 36  control points a second, over 25
    int32_t  NumCVs;             // 40
    int32_t  Pad;                // 44
    bVector3 CV[32];             // 48
} CameraShake;

// 1136 bytes, retail's bMalloc in ChangeCameraMover. The names from 48 to
// 832 are the demo's .mdebug record's; retail rearranged the rest, and the
// names there are the port's.
typedef struct TrackCarCameraMover {
    CameraMover     base;                // 0
    uint8_t         _pad44[4];           // 44
    bVector3        Look;                // 48
    bVector3        SpringVelocity;      // 64
    bVector3        SpringDisplacement;  // 80
    float           SpringConstant;      // 96
    float           DampingConstant;     // 100
    CameraDataItems CD;                  // 104
    uint8_t         _pad268[4];          // 268
    CameraShake     TheCameraShake;      // 272
    Spline          FOVSpline;           // 832
    Spline          EyeSpline;           // 880
    Spline          BankSpline;          // 928
    Spline          ShakeSpline;         // 976
    float           EyeSplineParam;      // 1024
    float           ShakeSplineParam;    // 1028
    uint8_t         _pad1032[8];         // 1032
    bVector3        WipeStart;           // 1040
    bVector3        WipeEnd;             // 1056
    int32_t         WipeTrackingHalted;  // 1072
    float           WipeDistApart;       // 1076
    struct Car     *CarToFollow;         // 1080
    BSpline         FocalDistCubic;      // 1084  a tCubic1D
    int32_t         FocusEffects;        // 1132
} TrackCarCameraMover;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char trackcarcam_layout_check[
    (sizeof(CameraDataItems) == 164 && sizeof(CameraShake) == 560
     && sizeof(Spline) == 48 && sizeof(BSpline) == 48
     && offsetof(TrackCarCameraMover, CD) == 104
     && offsetof(TrackCarCameraMover, TheCameraShake) == 272
     && offsetof(TrackCarCameraMover, FOVSpline) == 832
     && offsetof(TrackCarCameraMover, EyeSplineParam) == 1024
     && offsetof(TrackCarCameraMover, WipeStart) == 1040
     && offsetof(TrackCarCameraMover, CarToFollow) == 1080
     && offsetof(TrackCarCameraMover, FocalDistCubic) == 1084
     && sizeof(TrackCarCameraMover) == 1136) ? 1 : -1];
#endif

// Retail's 0x002b1ad0: the base's, but for the destructor, Update,
// GetCarToFollow and GetTarget.
extern const CameraMoverVtbl TrackCarCameraMoverVtbl;

// 0x00159130. A CM_TRACK_CAR mover on `viewID`, following `car`, with
// copies of `cd` and `shake`, its four splines over the copies' arrays
// (FOV over 32 entries, eye and bank over NumEyeVerts, shake over NumCVs),
// and the look point on the car. The spring starts at (SpringXVel,
// SpringYVel, SpringYVel), the record's Y twice: retail tests a static
// vector first (0x00334170), but only its initializer ever writes it, so
// it is always zero and the record's speeds always win. The focal
// distance's cubic starts at +-(26 to 44), toward 0 over 0.42 s, from
// bRandom's default seed. With `focusEffects` 0 the camera's focal
// distance and depth of field go to 0. Returns the mover.
TrackCarCameraMover *track_car_camera_mover_init(
    TrackCarCameraMover *m, int viewID, struct Car *car,
    const CameraDataItems *cd, const CameraShake *shake, int focusEffects);

// 0x00159490. The camera's focal distance and depth of field to 0, unless
// it is stopped; ClearVelocity set, so the next key's velocity is zero;
// the four splines; then the base.
void track_car_camera_mover_destroy(TrackCarCameraMover *m);

// 0x00159588. Nothing while the game flow is paused. `dt` is the world's
// step (WorldTimeElapsed), which moves the eye, the shake and the focal
// cubic; `elapsed` (RealTimeElapsed) is what SetCameraMatrix is given.
void track_car_camera_mover_update(TrackCarCameraMover *m, float dt,
                                   float elapsed);

// 0x00159540. velocity * damping + displacement * spring, on four lanes.
void track_car_camera_mover_calc_spring_force(const TrackCarCameraMover *m,
                                              bVector3 *o,
                                              const bVector3 *displacement,
                                              const bVector3 *velocity);

// 0x00159520. The car's GeometryPosition, or with no car the camera's
// target.
const bVector3 *track_car_camera_mover_get_target(
    const TrackCarCameraMover *m);

#endif
