// orbitcam -- OrbitCarCameraMover. See orbitcam.h.
#include "orbitcam.h"

#include <stddef.h>

#include "camera.h"
#include "car.h"
#include "chopper.h"
#include "emath.h"
#include "race.h"
#include "realtime.h"
#include "world.h"

// ------------------------------------------------------------ the statics

int      OrbitUseTweakables = 0;
float    OrbitTweakRadius   = 5.0f;
uint16_t OrbitTweakAngleH   = 26000;
uint16_t OrbitTweakAngleV   = 62000;
float    OrbitLookHeight    = 0.0f;
uint16_t OrbitInGameFOV     = 13020;
uint16_t OrbitFrontEndFOV   = 6000;
float    OrbitTargetHeight  = 0.3f;
uint16_t OrbitTweakOrbitFOV = 8000;

bVector3 OrbitBoomOffset = { 0.0f, 0.0f, 0.0f, 0.0f };

// ------------------------------------------------------------ the vtable

static void orbit_destroy_thunk(CameraMover *m)
{
    orbit_destroy((OrbitCarCameraMover *)m);
}

// The vtable's Update takes no argument and reads RealTimeElapsed itself.
static void orbit_update_thunk(CameraMover *m)
{
    orbit_update((OrbitCarCameraMover *)m, RealTimeElapsed);
}

static void orbit_add_joy_handlers_thunk(CameraMover *m)
{
    orbit_add_joy_handlers((OrbitCarCameraMover *)m);
}

static void orbit_remove_joy_handlers_thunk(CameraMover *m)
{
    orbit_remove_joy_handlers((OrbitCarCameraMover *)m);
}

// 0x0015fb18.
static void *orbit_get_car_to_follow(CameraMover *m)
{
    return ((OrbitCarCameraMover *)m)->CarToFollow;
}

static const bVector3 *orbit_get_target_thunk(CameraMover *m)
{
    return orbit_get_target((const OrbitCarCameraMover *)m);
}

// Retail's 0x002b1c50.
const CameraMoverVtbl OrbitCarCameraMoverVtbl = {
    orbit_destroy_thunk,
    orbit_update_thunk,
    camera_mover_render,
    orbit_add_joy_handlers_thunk,
    orbit_remove_joy_handlers_thunk,
    camera_mover_get_camera_info,
    camera_mover_get_pov,
    camera_mover_is_exterior_view,
    camera_mover_is_looking_back,
    camera_mover_get_wall_gap,
    camera_mover_nothing,       // ResetState
    camera_mover_enable,
    camera_mover_disable,
    orbit_get_car_to_follow,
    orbit_get_target_thunk,
};

// ------------------------------------------------------ the constructor

// 0x00157e48. The image reads CameraStopUpdating again after the dash,
// which nothing between could have changed.
void orbit_init(OrbitCarCameraMover *o, int viewID, struct Car *car,
                JoystickPort joyPort)
{
    Camera *cam;

    camera_mover_init(&o->base, viewID, CM_ORBIT_CAR);
    o->base.vtbl = &OrbitCarCameraMoverVtbl;

    o->Radius = 5.0f;
    o->AngleH = 26000;
    o->AngleV = 0xf230;             /* 62000 */
    o->DesiredAngleV = 0xf230;
    o->HRotationSpeed = 0;
    o->VRotationSpeed = 0;
    o->DesiredHRotationSpeed = 0;
    o->DesiredVRotationSpeed = 0;
    o->DesiredRadius = 5.0f;
    o->MaxRadius = 1000.0f;
    o->MinRadius = 1.0f;
    o->MinAngleV = 0xc738;          /* 51000 */
    o->MaxAngleV = 0xf8f4;          /* 63732 */
    o->RadiusMultiplier = 1.0f;
    o->MaxRadiusVel = 0.4f;         /* gp-31272 */
    o->MaxRotationAccel = 24;
    o->FEMode = 0;
    o->ApproachAngleV = 0;
    o->CarToFollow = car;
    o->FollowChopper = 0;
    o->FECarToFollow = NULL;
    o->JoyPort = joyPort;

    cam = o->base.pCamera;
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->RenderDash = 0;
        cam->CurrentKey.FieldOfView = OrbitInGameFOV;
    }
    o->HandlersAdded = 0;
    orbit_add_joy_handlers(o);
}

// 0x00158080.
void orbit_destroy(OrbitCarCameraMover *o)
{
    Camera *cam;

    o->base.vtbl = &OrbitCarCameraMoverVtbl;
    orbit_remove_joy_handlers(o);
    cam = o->base.pCamera;
    if (!CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = 0.0f;
        cam->CurrentKey.DepthOfField = 0.0f;
    }
    camera_mover_destroy(&o->base);
}

// ------------------------------------------------------------ the frame

// The bounded approach the two rotation speeds use. `cur` steps toward
// `want` by at most `accel`, and snaps when it is already within it.
//
// The image writes this as two branches around a signed compare and a
// `movz`: the step is taken FIRST and thrown away if the gap was small
// enough, so a gap of exactly `accel` lands on `want`.
static int approach(int cur, int want, int accel)
{
    int diff, stepped;

    if (cur < want) {
        diff = want - cur;
        stepped = cur + accel;
    } else {
        diff = cur - want;
        stepped = cur - accel;
    }
    return accel < diff ? stepped : want;
}

// T(-pos) with LookHeight taken off z, then into the followed body's own
// space by its matrix's transpose. eMulMatrix(o, a, b) is a then b.
static void orbit_follow(bMatrix4 *m, const bVector3 *pos,
                         const bMatrix4 *body)
{
    bMatrix4 trans, inv;

    eIdentity(&trans);
    trans.v3.x = -pos->x;
    trans.v3.y = -pos->y;
    trans.v3.z = -pos->z - OrbitLookHeight;
    eTransposeMatrix(&inv, body);
    eMulMatrix(m, &trans, &inv);
}

// 0x00158298.
void orbit_update(OrbitCarCameraMover *o, float elapsed)
{
    bMatrix4 m;
    bVector3 boom;
    Camera *cam;
    float radius;
    uint16_t angleV, angleH;
    int followed = 0;

    if (is_game_flow_paused())
        return;

    // The chopper, while it flies: Chopper::IsActive, inlined. The Plan
    // compare is unsigned. The image also tests &Matrix for NULL, which
    // it never is. The body is its matrix with the translation cleared,
    // and there is no boom offset on this path.
    if (o->FollowChopper) {
        const struct Chopper *h = pCurrentWorld->Helicopter;

        if (h != NULL && ((uint32_t)h->Plan < (uint32_t)CHOPPLAN_START_CHASE
                          || h->Plan == CHOPPLAN_BOMBING_RUN)) {
            bMatrix4 body = h->Matrix;

            body.v3.x = 0.0f;
            body.v3.y = 0.0f;
            body.v3.z = 0.0f;
            orbit_follow(&m, &h->CurrentPos, &body);
            followed = 1;
        }
    }

    if (!followed) {
        if (o->CarToFollow != NULL) {
            const CarState *s = &o->CarToFollow->State;

            orbit_follow(&m, &s->GeometryPosition, &s->BodyMatrix);
            // vadd.xyzw, so the fourth lane is in it too.
            m.v3.x = m.v3.x + OrbitBoomOffset.x;
            m.v3.y = m.v3.y + OrbitBoomOffset.y;
            m.v3.z = m.v3.z + OrbitBoomOffset.z;
            m.v3.w = m.v3.w + OrbitBoomOffset.pad;
        } else {
            // No car: orbit the origin, dropped by TargetHeight, the only
            // reader of it. The car path takes LookHeight off instead.
            eIdentity(&m);
            m.v3.z = -OrbitTargetHeight;
        }
    }

    // The boom length. RadiusMultiplier compounds into DesiredRadius every
    // frame it is not exactly 1.0, which is how the zoom works: hold 0.99
    // or 1.01 there.
    if (o->RadiusMultiplier != 1.0f)
        o->DesiredRadius = o->DesiredRadius * o->RadiusMultiplier;

    o->Radius = o->DesiredRadius;
    if (o->DesiredRadius < o->MinRadius)
        o->Radius = o->MinRadius;
    if (o->MaxRadius < o->Radius)
        o->Radius = o->MaxRadius;

    if (o->DesiredRadius < o->MinRadius)
        o->DesiredRadius = o->MinRadius;
    if (o->MaxRadius < o->DesiredRadius)
        o->DesiredRadius = o->MaxRadius;

    o->HRotationSpeed = approach(o->HRotationSpeed, o->DesiredHRotationSpeed,
                                 o->MaxRotationAccel);
    o->VRotationSpeed = approach(o->VRotationSpeed, o->DesiredVRotationSpeed,
                                 o->MaxRotationAccel);

    o->AngleV = (uint16_t)(o->AngleV + o->VRotationSpeed);

    // The walk to DesiredAngleV, 80 BAMs a frame. The compare is unsigned
    // on the raw halfwords, so it does not take the short way round.
    if (o->ApproachAngleV) {
        if (o->AngleV < o->DesiredAngleV) {
            if ((int)(o->DesiredAngleV - o->AngleV) < 81)
                o->AngleV = o->DesiredAngleV;
            else
                o->AngleV = (uint16_t)(o->AngleV + 80);
        } else {
            if ((int)(o->AngleV - o->DesiredAngleV) < 81)
                o->AngleV = o->DesiredAngleV;
            else
                o->AngleV = (uint16_t)(o->AngleV - 80);
        }
    }

    o->AngleH = (uint16_t)(o->AngleH + o->HRotationSpeed);

    if (OrbitUseTweakables) {
        angleH = OrbitTweakAngleH;
        angleV = OrbitTweakAngleV;
        radius = OrbitTweakRadius;
    } else {
        angleH = o->AngleH;
        angleV = o->AngleV;
        radius = o->Radius;
    }

    eRotateZ(&m, &m, angleH);
    eRotateY(&m, &m, angleV);
    boom.x = radius;
    boom.y = 0.0f;
    boom.z = 0.0f;
    eTranslate(&m, &m, &boom);

    // Into the renderer's frame: a quarter turn about x, then three
    // quarters about y, which map the engine's (x forward, z up) onto the
    // view's (x right, y up, z forward).
    eRotateX(&m, &m, 16384);
    eRotateY(&m, &m, 0xc000);

    cam = o->base.pCamera;
    if (!CameraStopUpdating) {
        // TweakOrbitFOV, 8000 BAMs (about 44 degrees), lands on the camera
        // every frame, so the constructor's InGameFOV is gone before it is
        // drawn with. A debug tweakable that shipped switched on.
        cam->CurrentKey.FieldOfView = OrbitTweakOrbitFOV;
        cam->CurrentKey.TargetDistance = o->Radius;
        cam->CurrentKey.FocalDistance = o->Radius;
        cam->CurrentKey.DepthOfField = 8.0f;
    }

    camera_set_matrix(cam, &m, elapsed);
}

// 0x001580e0.
const bVector3 *orbit_get_target(const OrbitCarCameraMover *o)
{
    if (o->CarToFollow != NULL)
        return &o->CarToFollow->State.GeometryPosition;
    return &o->base.pCamera->CurrentKey.Target;
}

// ------------------------------------------------------------ the joystick

// 0x00158100.
void orbit_add_joy_handlers(OrbitCarCameraMover *o)
{
    JoyEvent ev;

    if (o->HandlersAdded)
        return;
    for (ev = JOY_EVENT_DEBUG_CAMERA_ROTATE_RIGHT;
         ev <= JOY_EVENT_DEBUG_CAMERA_FOLLOW_CHOPPER; ev++)
        AddJoyHandler(o->JoyPort, ev, orbit_joy_handler, o);
    o->HandlersAdded = 1;
}

// 0x001581f8.
void orbit_remove_joy_handlers(OrbitCarCameraMover *o)
{
    JoyEvent ev;

    if (!o->HandlersAdded)
        return;
    for (ev = JOY_EVENT_DEBUG_CAMERA_ROTATE_RIGHT;
         ev <= JOY_EVENT_DEBUG_CAMERA_FOLLOW_CHOPPER; ev++)
        RemoveJoyHandler(o->JoyPort, ev);
    o->HandlersAdded = 0;
}

// The car after (or before) `car` in World's list, stepping past the
// list's head, which is the World itself: CarList is its first member.
static struct Car *orbit_step_car(struct Car *car, int back)
{
    CarNode *n = back ? car->Link.prev : car->Link.next;

    if (n == (CarNode *)(void *)pCurrentWorld)
        n = back ? n->prev : n->next;
    return (struct Car *)(void *)n;
}

// 0x001586c8.
void orbit_joy_handler(JoystickPort port, JoyEvent ev, uint8_t value,
                       void *obj)
{
    OrbitCarCameraMover *o = obj;
    int speed = o->FEMode ? ORBIT_JOY_SPEED_FE : ORBIT_JOY_SPEED;

    (void)port;
    switch (ev) {
    case JOY_EVENT_DEBUG_CAMERA_ROTATE_RIGHT:
        o->DesiredHRotationSpeed = value ? -speed : 0;
        break;
    case JOY_EVENT_DEBUG_CAMERA_ROTATE_LEFT:
        o->DesiredHRotationSpeed = value ? speed : 0;
        break;
    case JOY_EVENT_DEBUG_CAMERA_ROTATE_UP:
        o->DesiredVRotationSpeed = value ? -speed : 0;
        break;
    case JOY_EVENT_DEBUG_CAMERA_ROTATE_DOWN:
        o->DesiredVRotationSpeed = value ? speed : 0;
        break;
    case JOY_EVENT_DEBUG_CAMERA_MOVE_CLOSER:
        o->RadiusMultiplier = value ? ORBIT_ZOOM_IN : 1.0f;
        break;
    case JOY_EVENT_DEBUG_CAMERA_MOVE_FARTHER:
        o->RadiusMultiplier = value ? ORBIT_ZOOM_OUT : 1.0f;
        break;
    case JOY_EVENT_DEBUG_CAMERA_NEXT_CAR:
        if (!o->FEMode && value)
            o->CarToFollow = orbit_step_car(o->CarToFollow, 0);
        break;
    case JOY_EVENT_DEBUG_CAMERA_PREV_CAR:
        if (!o->FEMode && value)
            o->CarToFollow = orbit_step_car(o->CarToFollow, 1);
        break;
    case JOY_EVENT_DEBUG_CAMERA_FOLLOW_CHOPPER:
        if (value)
            o->FollowChopper = !o->FollowChopper;
        break;
    default:
        break;
    }
}

// ------------------------------------------------------------ the setters

void orbit_set_radius(OrbitCarCameraMover *o, float r) { o->Radius = r; }
void orbit_set_desired_radius(OrbitCarCameraMover *o, float r) { o->DesiredRadius = r; }
void orbit_set_min_radius(OrbitCarCameraMover *o, float r) { o->MinRadius = r; }
void orbit_set_max_radius(OrbitCarCameraMover *o, float r) { o->MaxRadius = r; }
void orbit_set_radius_multiplier(OrbitCarCameraMover *o, float m) { o->RadiusMultiplier = m; }
void orbit_set_angle_v(OrbitCarCameraMover *o, uint16_t v) { o->AngleV = v; }
void orbit_set_desired_angle_v(OrbitCarCameraMover *o, uint16_t v) { o->DesiredAngleV = v; }
void orbit_set_min_angle_v(OrbitCarCameraMover *o, uint16_t v) { o->MinAngleV = v; }
void orbit_set_max_angle_v(OrbitCarCameraMover *o, uint16_t v) { o->MaxAngleV = v; }
void orbit_set_h_rotation_speed(OrbitCarCameraMover *o, int s) { o->HRotationSpeed = s; }
void orbit_set_v_rotation_speed(OrbitCarCameraMover *o, int s) { o->VRotationSpeed = s; }
void orbit_set_desired_h_rotation_speed(OrbitCarCameraMover *o, int s) { o->DesiredHRotationSpeed = s; }
void orbit_set_desired_v_rotation_speed(OrbitCarCameraMover *o, int s) { o->DesiredVRotationSpeed = s; }
void orbit_set_max_rotation_accel(OrbitCarCameraMover *o, int a) { o->MaxRotationAccel = a; }
void orbit_set_approach_angle_v(OrbitCarCameraMover *o, int a) { o->ApproachAngleV = a; }

void orbit_set_angles(OrbitCarCameraMover *o, uint16_t h, uint16_t v)
{
    o->AngleH = h;
    o->AngleV = v;
}
