// cammover -- CameraMover.obj, the base and CM_ORBIT_CAR. See cammover.h.
#include <string.h>

#include "cammover.h"
#include "emath.h"

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

static const char *const MOVER_NAMES[] = {
    "CM_NONE", "CM_DRIVE", "CM_DEBUG_WORLD", "CM_TRACK_ROUTE_EDITOR",
    "CM_ORBIT_CAR", "CM_BUMPER", "CM_REAR_VIEW_MIRROR", "CM_TRACK_CAR",
    "CM_GARAGE", "CM_TRACK_FLY", "CM_MAX", "CM_SELECT_CAR", "CM_STILL",
    "CM_ZONE_FREEZE", "CM_ZONE_PREVIEW", "CM_ZONE_JUMPER", "CM_ZONE_JUMPER2",
    "CM_CUBIC_DAMPER"
};

// Retail's 0x00157578. The original is a chain of eighteen compares, and
// the fall through is retail's "CM_UNKNOWN(?)"; the demo's returned the
// CM_NONE string again.
const char *camera_mover_type_name(CameraMoverType t)
{
    if ((unsigned)t >= sizeof MOVER_NAMES / sizeof MOVER_NAMES[0])
        return "CM_UNKNOWN(?)";
    return MOVER_NAMES[t];
}

// ------------------------------------------------------------- the base

static void base_nothing(CameraMover *m) { (void)m; }
static void base_render(CameraMover *m, eView *view) { (void)m; (void)view; }
static CameraInfo *base_get_camera_info(CameraMover *m) { (void)m; return 0; }
static POV *base_get_pov(CameraMover *m, int index) { (void)m; (void)index; return 0; }
static int base_is_exterior_view(CameraMover *m) { (void)m; return 1; }
static int base_is_looking_back(CameraMover *m) { (void)m; return 0; }
static float base_get_wall_gap(CameraMover *m) { (void)m; return 0.7f; }
static void *base_get_car_to_follow(CameraMover *m) { (void)m; return 0; }

// 0x0015fcb0.
static const bVector3 *base_get_target(CameraMover *m)
{
    return &m->pCamera->CurrentKey.Target;
}

const CameraMoverVtbl CameraMoverBaseVtbl = {
    camera_mover_destroy,
    base_nothing,               // Update
    base_render,
    base_nothing,               // AddJoyHandlers
    base_nothing,               // RemoveJoyHandlers
    base_get_camera_info,
    base_get_pov,
    base_is_exterior_view,
    base_is_looking_back,
    base_get_wall_gap,
    base_nothing,               // ResetState
    camera_mover_enable,
    camera_mover_disable,
    base_get_car_to_follow,
    base_get_target,
};

// Retail's 0x001576e8.
void camera_mover_init(CameraMover *m, int viewID, CameraMoverType type)
{
    eView *v;
    Camera *cam;

    m->vtbl = &CameraMoverBaseVtbl;
    m->Type = type;
    m->ViewID = viewID;
    m->Enabled = 0;
    m->pPlayer = 0;

    if (viewID == -1) {
        m->pView = 0;
        m->pCamera = 0;
        m->CarNotToRender = 0;
        m->RenderDash = 0;
        return;
    }

    // The far plane is set here and the near plane down in Enable, which is
    // an odd place for it but is where the disc puts it.
    v = eGetView(viewID);
    cam = v->pCamera;
    m->pView = v;
    cam->CurrentKey.FarZ = 10000.0f;    /* gp-31292; the demo's was 5000 */
    m->CarNotToRender = cam->CarNotToRender;
    m->RenderDash = cam->RenderDash;
    m->pCamera = cam;
    camera_mover_enable(m);
}

// Retail's 0x00157780. The tail is bTNode's destructor, which only deletes.
void camera_mover_destroy(CameraMover *m)
{
    m->vtbl = &CameraMoverBaseVtbl;
    camera_mover_disable(m);
}

// Retail's 0x001577d8.
void camera_mover_enable(CameraMover *m)
{
    if (m->Enabled)
        return;
    m->Enabled = 1;

    if (!CameraStopUpdating) {
        m->pCamera->CarNotToRender = m->CarNotToRender;
        m->pCamera->RenderDash = m->RenderDash;
    }
    eview_attach_camera_mover(m->pView, &m->Node);
    m->pCamera->CurrentKey.NearZ = 0.5f;
}

// Retail's 0x00157850. Not symmetric with Enable, in two ways that matter. It returns
// immediately when the mover is already disabled -- so a mover that never
// attached, whose pCamera is null, never dereferences it -- and it copies the
// camera's two render flags back INTO the mover before letting go, so a
// disable/enable pair round-trips whatever another mover left on the camera
// in between rather than restoring what this one first saw. And unlike
// Enable it does not consult CameraStopUpdating at all.
void camera_mover_disable(CameraMover *m)
{
    if (!m->Enabled)
        return;
    m->Enabled = 0;
    m->CarNotToRender = m->pCamera->CarNotToRender;
    m->RenderDash = m->pCamera->RenderDash;
    eview_unattach_camera_mover(m->pView, &m->Node);
}

// 0x0015fcd0 and 0x0015fcc0.
const bVector3 *camera_mover_get_position(const CameraMover *m)
{
    return &m->pCamera->CurrentKey.Position;
}

const bVector3 *camera_mover_get_direction(const CameraMover *m)
{
    return &m->pCamera->CurrentKey.Direction;
}

// 0x0015fca0.
void camera_mover_set_player(CameraMover *m, void *player)
{
    m->pPlayer = player;
}

// The first mover on a view's list, or NULL, as both loops below test it:
// the head's next against the head itself.
static CameraMover *first_mover(eView *v)
{
    bNode *n = v->CameraMoverList.next;

    return n != &v->CameraMoverList ? (CameraMover *)n : 0;
}

// Retail's 0x0015ef28. eGetView has no failure, so the NULL view test the
// original makes never fires, and is not kept.
void update_camera_movers(void)
{
    int i;

    for (i = 0; i < EVIEW_NUM_VIEWS; i++) {
        CameraMover *m = first_mover(eGetView(i));

        if (m)
            m->vtbl->Update(m);
    }
}

// Retail's 0x0015eee0.
void render_camera_movers(eView *view)
{
    CameraMover *m = first_mover(view);

    if (m)
        m->vtbl->Render(m, view);
}

// -------------------------------------------------------- CM_ORBIT_CAR
//
// Still the demo's, which camera_check holds it to. Retail changed its
// constructors, its Update and its GetTarget; that pass waits for the car
// selector, the one caller (step 16).

static void orbit_update_thunk(CameraMover *m);
static void orbit_destroy_thunk(CameraMover *m);
static void *orbit_get_car_to_follow(CameraMover *m);
static const bVector3 *orbit_get_target_thunk(CameraMover *m);

// Retail's 0x002b1c50: the base's but for these five and the joystick pair,
// which the port does not register (see orbit_init).
static const CameraMoverVtbl OrbitVtbl = {
    orbit_destroy_thunk,
    orbit_update_thunk,
    base_render,
    base_nothing,               // AddJoyHandlers
    base_nothing,               // RemoveJoyHandlers
    base_get_camera_info,
    base_get_pov,
    base_is_exterior_view,
    base_is_looking_back,
    base_get_wall_gap,
    base_nothing,               // ResetState
    camera_mover_enable,
    camera_mover_disable,
    orbit_get_car_to_follow,
    orbit_get_target_thunk,
};

// 0x00154728.
void orbit_init(OrbitCarCameraMover *o, int viewID, CamCarView *car,
                int joyPort)
{
    camera_mover_init(&o->base, viewID, CM_ORBIT_CAR);
    o->base.vtbl = &OrbitVtbl;

    o->Radius = 5.0f;
    o->AngleH = 26000;
    o->AngleV = 0xf230;             /* 61992 */
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
    o->MaxRadiusVel = 0.4f;
    o->MaxRotationAccel = 24;
    o->FEMode = 0;
    o->ApproachAngleV = 0;
    // Divergence, harmless: the disc's constructor never touches TM, so on
    // the PS2 it holds whatever was in the allocation. Nothing in the object
    // reads it, so clearing it costs nothing and makes the port's state
    // printable.
    memset(&o->TM, 0, sizeof o->TM);
    o->CarToFollow = car;
    o->FollowChopper = 0;
    o->FECarToFollow = 0;
    o->JoyPort = joyPort;
    o->HandlersAdded = 0;

    if (!CameraStopUpdating) {
        o->base.pCamera->CarNotToRender = 0;
        o->base.pCamera->RenderDash = 0;
        o->base.pCamera->CurrentKey.FieldOfView = OrbitInGameFOV;
    }
    // Divergence: the disc ends here with AddJoyHandlers() (0x001549e0),
    // which registers nine handlers and sets HandlersAdded to 1 at
    // 0x00154ac0. The port has no PS2 joystick event bus, so it registers
    // nothing and leaves the flag at 0 -- which is the honest answer to
    // "have the handlers been added". See the ORBIT_JOY_* constants in the
    // header for what the handler did with each of the nine events.
}

// The bounded approach the two rotation speeds use. `cur` steps toward
// `want` by at most `accel`, and snaps when it is already within it.
//
// The original writes this as two branches around an unsigned compare and a
// `movz`, which means the step is taken FIRST and then thrown away if the
// gap was small enough -- so a gap of exactly `accel` lands on `want` rather
// than overshooting.
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

// 0x00154b78.
void orbit_update(OrbitCarCameraMover *o, float elapsed)
{
    bMatrix4 trans, inv, m;
    bVector3 boom;
    Camera *cam = o->base.pCamera;
    float radius;
    uint16_t angleV, angleH;

    // IsGameFlowPaused() is the first thing the original tests; a paused
    // game leaves the camera exactly where it was. The port's caller does
    // that test, because gameflow.c owns the answer.

    eIdentity(&trans);

    if (o->CarToFollow) {
        const bVector3 *p = &o->CarToFollow->GeometryPosition;

        // T(-carPos), with LookHeight taken off z. LookHeight is 0.
        trans.v3.x = -p->x;
        trans.v3.y = -p->y;
        trans.v3.z = -p->z - OrbitLookHeight;

        // The car's own space: translate the world to the car, then rotate
        // by the body matrix's inverse. eMulMatrix(o, a, b) is a then b.
        eTransposeMatrix(&inv, &o->CarToFollow->BodyMatrix);
        eMulMatrix(&m, &trans, &inv);

        // vadd.xyzw at 0x00154d0c, so the fourth lane is in it too.
        m.v3.x = m.v3.x + OrbitBoomOffset.x;
        m.v3.y = m.v3.y + OrbitBoomOffset.y;
        m.v3.z = m.v3.z + OrbitBoomOffset.z;
        m.v3.w = m.v3.w + OrbitBoomOffset.pad;
    } else {
        // No car: orbit the origin, dropped by OrbitTargetHeight. Note that
        // this is the only place OrbitTargetHeight is read, and that the
        // car path uses LookHeight instead -- two separate tweakables for
        // the same idea, one of them zero.
        eIdentity(&m);
        m.v3.z = -OrbitTargetHeight;
    }

    // The boom length. RadiusMultiplier compounds into DesiredRadius every
    // frame it is not exactly 1.0, which is how the zoom buttons work: they
    // set 0.99 or 1.01 and hold it.
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

    // The slow walk to DesiredAngleV, 80 BAMs a frame. The compare is
    // unsigned on the raw u16s, so it does NOT take the short way round: an
    // AngleV of 100 approaching 65000 walks down through zero rather than up.
    // With MinAngleV/MaxAngleV pinning the elevation to the top of the range
    // that never happens in practice.
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

    if (o->MaxAngleV < o->AngleV)
        o->AngleV = o->MaxAngleV;
    if (o->AngleV < o->MinAngleV)
        o->AngleV = o->MinAngleV;

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

    // Into the renderer's frame: a quarter turn about x, then three quarters
    // about y. Together they map the engine's (x forward, z up) onto the
    // view's (x right, y up, z forward).
    eRotateX(&m, &m, 16384);
    eRotateY(&m, &m, 0xc000);

    if (!CameraStopUpdating) {
        // Not behind UseTweakables. TweakOrbitFOV is 8000 BAMs -- about 44
        // degrees -- and it lands on the camera every single frame, so the
        // constructor's InGameFOV of 13020 (about 71 degrees) is overwritten
        // before it is ever used. A debug tweakable that shipped switched on.
        cam->CurrentKey.FieldOfView = OrbitTweakOrbitFOV;
        cam->CurrentKey.TargetDistance = o->Radius;
        cam->CurrentKey.FocalDistance = o->Radius;
        cam->CurrentKey.DepthOfField = 8.0f;
    }

    camera_set_matrix(cam, &m, elapsed);
}

// The disc's Update takes no argument and reads the RealTimeElapsed global
// itself. It also tests IsGameFlowPaused first and returns without touching
// anything; the port leaves that test to the caller, because gameflow.c owns
// the answer and a mover that pulled it in could not be unit-tested.
static void orbit_update_thunk(CameraMover *m)
{
    orbit_update((OrbitCarCameraMover *)m, RealTimeElapsed);
}

// 0x001549c0.
const bVector3 *orbit_get_target(const OrbitCarCameraMover *o)
{
    if (o->CarToFollow)
        return &o->CarToFollow->Position;
    return &o->base.pCamera->CurrentKey.Target;
}

static const bVector3 *orbit_get_target_thunk(CameraMover *m)
{
    return orbit_get_target((const OrbitCarCameraMover *)m);
}

// 0x0015c290.
static void *orbit_get_car_to_follow(CameraMover *m)
{
    return ((OrbitCarCameraMover *)m)->CarToFollow;
}

// 0x00154960. RemoveJoyHandlers first, which has nothing to remove in the
// port, then the depth of field off the camera, then the base's.
void orbit_destroy(OrbitCarCameraMover *o)
{
    o->base.vtbl = &OrbitVtbl;
    if (!CameraStopUpdating) {
        o->base.pCamera->CurrentKey.FocalDistance = 0.0f;
        o->base.pCamera->CurrentKey.DepthOfField = 0.0f;
    }
    camera_mover_destroy(&o->base);
}

static void orbit_destroy_thunk(CameraMover *m)
{
    orbit_destroy((OrbitCarCameraMover *)m);
}

// ---------------------------------------------------------- the setters

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
