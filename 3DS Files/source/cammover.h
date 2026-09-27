// cammover -- CameraMover.obj (0x00154380 .. 0x0015c4d0), in part.
//
// A CameraMover decides where a Camera goes. There are eighteen kinds on the
// disc (the enum below is the complete list, lifted from
// GetCameraMoverTypeName at 0x154380) and one base class with a virtual
// Update that each of them overrides.
//
// This file ports the base and CM_ORBIT_CAR. The rest are deliberately left:
// CM_DRIVE, CM_BUMPER and CM_REAR_VIEW_MIRROR need Car and its wheels
// (task 25), CM_TRACK_CAR and CM_TRACK_FLY need a route that can answer
// "how far around the lap is this" -- TrackRoute is ported now, but that
// answer waits on QuickSpline.obj, which task 27 owes it -- the
// CM_ZONE_* ones need the streaming world (task 27), and CM_DEBUG_WORLD,
// CM_MAX and CM_TRACK_ROUTE_EDITOR are development tools that were left in
// the build. CM_ORBIT_CAR comes first because it is the one the car select
// and the replay orbit use, and because it needs nothing but a matrix and a
// position -- which is exactly what the geometry viewer already has.
//
// Written up with addresses in docs/formats/camera.md. Checked by
// tools/camera_check.py.
#ifndef CAMMOVER_H
#define CAMMOVER_H

#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "camera.h"
#include "eview.h"

// GetCameraMoverTypeName, 0x00154380. The numbering is the disc's.
typedef enum CameraMoverType {
    CM_NONE = 0,
    CM_DRIVE,
    CM_DEBUG_WORLD,
    CM_TRACK_ROUTE_EDITOR,
    CM_ORBIT_CAR,
    CM_BUMPER,
    CM_REAR_VIEW_MIRROR,
    CM_TRACK_CAR,
    CM_GARAGE,
    CM_TRACK_FLY,
    CM_MAX,
    CM_SELECT_CAR,
    CM_STILL,
    CM_ZONE_FREEZE,
    CM_ZONE_PREVIEW,
    CM_ZONE_JUMPER,
    CM_ZONE_JUMPER2,
    CM_CUBIC_DAMPER
} CameraMoverType;

const char *camera_mover_type_name(CameraMoverType t);

// What the orbit mover reads out of a Car. The original dereferences a
// `Car *` at three fixed offsets, all of them inside the embedded CarState:
//
//     Car + 80    CarState::GeometryPosition   where the body is drawn
//     Car + 96    CarState::Position           where the physics thinks it is
//     Car + 144   CarState::BodyMatrix         the body's orientation
//
// It follows the rendering position and returns the physics one as the
// target, which is a one-frame difference nothing seems to mind. `Car`
// arrives in task 25; until then a mover points at one of these.
typedef struct CamCarView {
    bVector3 GeometryPosition;
    bVector3 Position;
    bMatrix4 BodyMatrix;
} CamCarView;

// ------------------------------------------------------------ the base class
//
// 44 bytes on the disc, vtable pointer at offset 40. The port keeps the
// fields and replaces the vtable with one function pointer, because Update is
// the only virtual anything here calls.
//
// The constructor takes a view id, as the disc's does, and the Camera is the
// view's: eGetView(id)->pCamera. A mover is a bTNode, so enabling it puts it
// on the head of its view's list by its Node, which is what the view mode and
// the projection read.
typedef struct CameraMover CameraMover;

// The offsets are the disc's, from the .mdebug record for CameraMover
// (44 bytes); 40 is the vtable this replaces.
struct CameraMover {
    bNode           Node;           // 0   on pView's CameraMoverList
    CameraMoverType Type;           // 8
    int             ViewID;         // 12
    int             Enabled;        // 16
    eView          *pView;          // 20
    Camera         *pCamera;        // 24
    void           *pPlayer;        // 28
    void           *CarNotToRender; // 32
    int             RenderDash;     // 36
    void          (*Update)(CameraMover *);
};

// 0x001544f0. A ViewID of -1 leaves the mover detached and disabled; any
// other value takes the view and its camera, sets the camera's far plane to
// 5000, and enables the mover, which sets the near plane to 0.5. The view
// must have its camera by then: eInitViews gives views 0 to 3 theirs.
void camera_mover_init(CameraMover *m, int viewID, CameraMoverType type);

// 0x001545e0 / 0x00154658. Neither is a no-op while CameraStopUpdating is
// set, and they do not treat it the same way. Enable skips the two render
// flags it would push at the camera but still forces the near plane to 0.5;
// Disable does not test the flag at all, and pulls both render flags back
// off the camera on its way out. Both early-out when the flag is already
// where they would put it. Enable attaches the mover to its view and
// Disable unattaches it, each after the flags.
void camera_mover_enable(CameraMover *m);
void camera_mover_disable(CameraMover *m);

// ---------------------------------------------------------- CM_ORBIT_CAR
//
// 208 bytes. A boom arm: the camera sits `Radius` away from the car at
// heading `AngleH` and elevation `AngleV`, in the car's own space, and the
// two angles drift toward their desired values at a bounded acceleration.
typedef struct OrbitCarCameraMover {
    CameraMover base;

    float    Radius;                 // 44
    uint16_t AngleH;                 // 48
    uint16_t AngleV;                 // 50
    uint16_t DesiredAngleV;          // 52
    int      HRotationSpeed;         // 56  BAMs per frame, not per second
    int      VRotationSpeed;         // 60
    int      DesiredHRotationSpeed;  // 64
    int      DesiredVRotationSpeed;  // 68
    float    DesiredRadius;          // 72
    float    MaxRadius;              // 76
    float    MinRadius;              // 80
    uint16_t MinAngleV;              // 84
    uint16_t MaxAngleV;              // 86
    float    RadiusMultiplier;       // 88
    float    MaxRadiusVel;           // 92  stored, never read
    int      MaxRotationAccel;       // 96
    int      FEMode;                 // 100
    int      ApproachAngleV;         // 104
    bMatrix4 TM;                     // 112 never written, never read
    CamCarView *CarToFollow;         // 176
    int      FollowChopper;          // 180 see the note on orbit_update
    void    *FECarToFollow;          // 184
    int      JoyPort;                // 188
    int      HandlersAdded;          // 192
} OrbitCarCameraMover;

// The eight file-scope statics at 0x3234f8..0x323510, with the values the
// disc ships. `UseTweakables` is the debug switch that swaps the live angles
// for the three Tweak* ones; it is 0. `TweakOrbitFOV` is NOT behind that
// switch -- see the note on orbit_update.
extern int      OrbitUseTweakables;    // 0x3234f8, 0
extern float    OrbitTweakRadius;      // 0x3234fc, 5.0
extern uint16_t OrbitTweakAngleH;      // 0x323500, 26000
extern uint16_t OrbitTweakAngleV;      // 0x323502, 62000
extern float    OrbitLookHeight;       // 0x323504, 0.0
extern uint16_t OrbitInGameFOV;        // 0x323508, 13020
extern uint16_t OrbitFrontEndFOV;      // 0x32350a, 6000
extern float    OrbitTargetHeight;     // 0x32350c, 0.3
extern uint16_t OrbitTweakOrbitFOV;    // 0x323510, 8000

// The unnamed quadword at 0x326f10, in CameraMover.obj's .bss. It is added to
// the orbit matrix's translation row every frame, and the only thing that
// ever writes it is the object file's own static initialiser, which stores
// 0.0 into its x. A debug hook that was left switched on and set to nothing.
extern bVector3 OrbitBoomOffset;

// `RealTimeElapsed` at 0x323cdc: seconds since the last frame. The clock
// object owns it (realtime.c), and PrepareRealTimestep writes it at the top
// of each frame. The disc's Update reads it directly; orbit_update takes it
// as an argument so the checker can drive it.
#include "realtime.h"

// 0x00154728. `car` may be null, in which case the mover orbits the origin.
void orbit_init(OrbitCarCameraMover *o, int viewID, CamCarView *car,
                int joyPort);

// 0x00154b78. Runs one frame: approach the desired rotation speeds, advance
// and clamp the angles, build the boom matrix, and hand it to the camera.
//
// `elapsed` is what the original reads from the global RealTimeElapsed and
// passes straight to Camera::SetCameraMatrix. Nothing else in Update is
// time-scaled: the rotation speeds are BAMs per *frame*, so the orbit spins
// faster on a machine that draws more of them. That is the disc's behaviour
// and the port keeps it; whether the 3DS should is a question for task 28.
//
// Not ported, and the only branch of Update that is not: `FollowChopper`
// (0x00154bb0..0x00154c94) swaps the followed car for the police Chopper,
// taking its matrix from Chopper::GetMatrix and gating on a mode word at
// Player+584 being 0, 1, 2 or 4. There is no Chopper yet -- it is task 26 --
// so the port asserts nothing about the flag and always takes the car path.
void orbit_update(OrbitCarCameraMover *o, float elapsed);

// 0x001549c0. The car's physics position, or the camera's own target when
// there is no car.
const bVector3 *orbit_get_target(const OrbitCarCameraMover *o);

// The one-line setters clustered at 0x15c2a0..0x15c330. Plain stores; they are
// here because the joystick handler and the frontend both go through them.
void orbit_set_radius(OrbitCarCameraMover *o, float r);
void orbit_set_desired_radius(OrbitCarCameraMover *o, float r);
void orbit_set_min_radius(OrbitCarCameraMover *o, float r);
void orbit_set_max_radius(OrbitCarCameraMover *o, float r);
void orbit_set_radius_multiplier(OrbitCarCameraMover *o, float m);
void orbit_set_angles(OrbitCarCameraMover *o, uint16_t h, uint16_t v);
void orbit_set_angle_v(OrbitCarCameraMover *o, uint16_t v);
void orbit_set_desired_angle_v(OrbitCarCameraMover *o, uint16_t v);
void orbit_set_min_angle_v(OrbitCarCameraMover *o, uint16_t v);
void orbit_set_max_angle_v(OrbitCarCameraMover *o, uint16_t v);
void orbit_set_h_rotation_speed(OrbitCarCameraMover *o, int s);
void orbit_set_v_rotation_speed(OrbitCarCameraMover *o, int s);
void orbit_set_desired_h_rotation_speed(OrbitCarCameraMover *o, int s);
void orbit_set_desired_v_rotation_speed(OrbitCarCameraMover *o, int s);
void orbit_set_max_rotation_accel(OrbitCarCameraMover *o, int a);
void orbit_set_approach_angle_v(OrbitCarCameraMover *o, int a);

// OrbitCarCameraMover::JoyHandler, 0x00154ff0. It is a nine-way jump on
// `event - 46` through the table at 0x2950e0, and the nine are the DEBUG
// camera events rather than the car-select ones -- JOY_EVENT_CARSEL_ORBIT_*
// are 35..43 and this mover never sees them, because the car select screen
// drives it through the setters above instead:
//
//   46 DEBUG_CAMERA_ROTATE_RIGHT   DesiredHRotationSpeed = -speed
//   47 DEBUG_CAMERA_ROTATE_LEFT    DesiredHRotationSpeed = +speed
//   48 DEBUG_CAMERA_ROTATE_UP      DesiredVRotationSpeed = -speed
//   49 DEBUG_CAMERA_ROTATE_DOWN    DesiredVRotationSpeed = +speed
//   50 DEBUG_CAMERA_MOVE_CLOSER    RadiusMultiplier = 0.99
//   51 DEBUG_CAMERA_MOVE_FARTHER   RadiusMultiplier = 1.01
//   52 DEBUG_CAMERA_NEXT_CAR       CarToFollow = *(CarToFollow + 0)
//   53 DEBUG_CAMERA_PREV_CAR       CarToFollow = *(CarToFollow + 4)
//   54 DEBUG_CAMERA_FOLLOW_CHOPPER FollowChopper = !FollowChopper
//
// Every one of the six held ones writes its rest value on release -- 0 for
// a speed, exactly 1.0f for the multiplier -- and 52/53 are ignored while
// FEMode is set. The speed is 500 BAMs a frame, or 300 when FEMode is set.
//
// The signs are worth keeping: "up" asks for a NEGATIVE vertical speed, so
// holding up walks AngleV toward MaxAngleV, and AngleV rising lowers the
// boom.
#define ORBIT_JOY_SPEED     500
#define ORBIT_JOY_SPEED_FE  300
#define ORBIT_ZOOM_IN       0x1.fae1480000000p-1f   /* 0.99, gp-31440 */
#define ORBIT_ZOOM_OUT      0x1.028f5c0000000p+0f  /* 1.01, gp-31436 */

#endif
