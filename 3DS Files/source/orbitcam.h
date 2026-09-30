// orbitcam -- OrbitCarCameraMover (CM_ORBIT_CAR), the boom arm the car
// select, the replay orbit and Player::ChangeCameraMover's default use.
// CameraMover.obj's; the addresses are retail's.
//
// This is step 7c, the retail pass: the constructor (0x00157e48), the
// destructor (0x00158080), GetTarget (0x001580e0), GetCarToFollow
// (0x0015fb18), AddJoyHandlers (0x00158100), RemoveJoyHandlers
// (0x001581f8), Update (0x00158298) and JoyHandler (0x001586c8).
//
// Retail against the demo:
// - The mover follows a Car. The demo's port followed a stand-in with the
//   three CarState words it reads.
// - GetTarget is the car's GeometryPosition, where the demo's was its
//   Position.
// - Update returns at once while IsGameFlowPaused. The demo's port left
//   that to its caller.
// - FollowChopper follows World's Helicopter while its Plan is one of
//   the four flying ones, with Chopper::IsActive and GetMatrix inlined.
//   The demo called GetMatrix, and read the Plan at the demo Chopper's
//   584.
// - The clamp of AngleV to MinAngleV and MaxAngleV is gone, so nothing
//   in the class reads those two any more. Whoever sets the speeds keeps
//   the elevation in range.
//
// Written up in docs/formats/camera.md, "The orbit camera"; checked on
// retail's image by tools/orbit_check.py.

#ifndef ORBITCAM_H
#define ORBITCAM_H

#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "cammover.h"
#include "joyevent.h"

struct Car;

// 208 bytes. A boom arm: the camera sits `Radius` away from the car at
// heading `AngleH` and elevation `AngleV`, in the car's own space, and the
// two rotation speeds ramp toward their desired values at a bounded
// acceleration.
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
    uint16_t MinAngleV;              // 84  stored, never read
    uint16_t MaxAngleV;              // 86  stored, never read
    float    RadiusMultiplier;       // 88
    float    MaxRadiusVel;           // 92  stored, never read
    int      MaxRotationAccel;       // 96
    int      FEMode;                 // 100
    int      ApproachAngleV;         // 104
    bMatrix4 TM;                     // 112 never written, never read
    struct Car *CarToFollow;         // 176
    int      FollowChopper;          // 180
    void    *FECarToFollow;          // 184 stored, never read
    JoystickPort JoyPort;            // 188
    int      HandlersAdded;          // 192
} OrbitCarCameraMover;

// The file-scope statics at gp-21720 .. gp-21696, with the values the
// disc ships (the demo's are the same). `UseTweakables` is the debug
// switch that swaps the live angles and radius for the three Tweak* ones;
// it is 0. `TweakOrbitFOV` is NOT behind that switch: see orbit_update.
extern int      OrbitUseTweakables;    // gp-21720, 0
extern float    OrbitTweakRadius;      // gp-21716, 5.0
extern uint16_t OrbitTweakAngleH;      // gp-21712, 26000
extern uint16_t OrbitTweakAngleV;      // gp-21710, 62000
extern float    OrbitLookHeight;       // gp-21708, 0.0
extern uint16_t OrbitInGameFOV;        // gp-21704, 13020
extern uint16_t OrbitFrontEndFOV;      // gp-21702, 6000
extern float    OrbitTargetHeight;     // gp-21700, 0.3
extern uint16_t OrbitTweakOrbitFOV;    // gp-21696, 8000

// The unnamed quadword at 0x00334190 (the demo's 0x326f10). It is added to
// the car path's matrix translation row every frame, and the only thing
// that ever writes it is the object file's own static initialiser, which
// stores 0.0 into its x. A debug hook left switched on and set to nothing.
extern bVector3 OrbitBoomOffset;

// The vtable, retail's 0x002b1c50: the base's but for the destructor,
// Update, the joystick pair, GetCarToFollow and GetTarget.
extern const CameraMoverVtbl OrbitCarCameraMoverVtbl;

// 0x00157e48. `car` may be NULL, and the mover orbits the origin. Unless
// CameraStopUpdating is set, the camera draws every car and no dash, at
// InGameFOV. It ends with AddJoyHandlers. TM is left as it was, as the
// image leaves it.
void orbit_init(OrbitCarCameraMover *o, int viewID, struct Car *car,
                JoystickPort joyPort);

// 0x00158080. RemoveJoyHandlers, then the camera's focal distance and
// depth of field back to 0 unless CameraStopUpdating is set, then the
// base's.
void orbit_destroy(OrbitCarCameraMover *o);

// 0x00158298. Runs one frame: approach the desired rotation speeds, step
// the angles, build the boom matrix, and hand it to the camera. Nothing
// while IsGameFlowPaused.
//
// `elapsed` is what the image reads from RealTimeElapsed and passes
// straight to SetCameraMatrix; the vtable's Update passes it. Nothing
// else in Update is time-scaled: the rotation speeds are BAMs per frame.
void orbit_update(OrbitCarCameraMover *o, float elapsed);

// 0x001580e0. The car's GeometryPosition, or the camera's target.
const bVector3 *orbit_get_target(const OrbitCarCameraMover *o);

// 0x00158100 and 0x001581f8. Register JoyHandler for the nine
// DEBUG_CAMERA events on JoyPort, or take them off, once each way.
void orbit_add_joy_handlers(OrbitCarCameraMover *o);
void orbit_remove_joy_handlers(OrbitCarCameraMover *o);

// 0x001586c8. A nine-way jump on `event - 46` through the table at
// 0x002b1630. The nine are the DEBUG camera events. The car select drives
// the mover through the setters below instead.
//
//   46 DEBUG_CAMERA_ROTATE_RIGHT   DesiredHRotationSpeed = -speed
//   47 DEBUG_CAMERA_ROTATE_LEFT    DesiredHRotationSpeed = +speed
//   48 DEBUG_CAMERA_ROTATE_UP      DesiredVRotationSpeed = -speed
//   49 DEBUG_CAMERA_ROTATE_DOWN    DesiredVRotationSpeed = +speed
//   50 DEBUG_CAMERA_MOVE_CLOSER    RadiusMultiplier = 0.99
//   51 DEBUG_CAMERA_MOVE_FARTHER   RadiusMultiplier = 1.01
//   52 DEBUG_CAMERA_NEXT_CAR       the car after CarToFollow
//   53 DEBUG_CAMERA_PREV_CAR       the car before it
//   54 DEBUG_CAMERA_FOLLOW_CHOPPER FollowChopper = !FollowChopper
//
// Each of the six held ones writes its rest value on release: 0 for a
// speed, exactly 1.0f for the multiplier. 52 and 53 step through World's
// car list, past its head, while FEMode is clear, and read CarToFollow
// without testing it. The speed is 500 BAMs a frame, or 300 with FEMode.
//
// "Up" asks for a NEGATIVE vertical speed, so holding up walks AngleV up,
// and AngleV rising lowers the boom.
void orbit_joy_handler(JoystickPort port, JoyEvent ev, uint8_t value,
                       void *obj);

#define ORBIT_JOY_SPEED     500
#define ORBIT_JOY_SPEED_FE  300
#define ORBIT_ZOOM_IN       0x1.fae148p-1f   /* 0.99, gp-31260 */
#define ORBIT_ZOOM_OUT      0x1.028f5cp+0f   /* 1.01, gp-31256 */

// The setters, inline in the image. The car select and the geometry
// viewer drive the mover through these.
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

#endif
