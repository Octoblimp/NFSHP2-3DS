// Host harness for 3DS Files/source/camera.c and cammover.c. Prints a
// transcript that tools/camera_check.py diffs line by line against an
// independent model.
//
// Same rules as the other harnesses: every float is a float32 printed with
// %.9g, so a single-ulp disagreement is a changed line rather than something
// a tolerance swallows. The camera is the first thing in the port whose state
// carries from frame to frame -- Previous and Velocity are differences of
// differences -- so the scenarios drive it for runs of frames rather than
// checking one call at a time.
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "camera.h"
#include "cammover.h"
#include "emath.h"

// The clock object's frame step, which the orbit mover's Update thunk reads.
// Defined here rather than linked from realtime.c, which would bring the
// joylog in behind it, and a sixtieth as the mover's own file used to have
// it.
float RealTimeElapsed = 1.0f / 60.0f;

// ------------------------------------------------------------------- output

// All four lanes. The camera's three vectors are bVector3, which is a padded
// quadword, and every VU0 instruction that touches them in SetCameraMatrix
// is .xyzw -- so the pad carries real arithmetic and printing three
// components would hide it.
static void pv3(const char *tag, const bVector3 *v)
{
    printf("  %s %.9g %.9g %.9g %.9g\n", tag, v->x, v->y, v->z, v->pad);
}

static void pmat(const bMatrix4 *m)
{
    printf("    %.9g %.9g %.9g %.9g\n", m->v0.x, m->v0.y, m->v0.z, m->v0.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v1.x, m->v1.y, m->v1.z, m->v1.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v2.x, m->v2.y, m->v2.z, m->v2.w);
    printf("    %.9g %.9g %.9g %.9g\n", m->v3.x, m->v3.y, m->v3.z, m->v3.w);
}

// `withMatrix` is 0 for the velocity key. Nothing on the disc ever writes
// VelocityKey.Matrix -- SetCameraMatrix differences the vectors and the
// scalars and stops -- so those sixteen floats are whatever the allocation
// held, on the PS2 and here, and printing them would make the transcript
// depend on the host's stack.
static void pkey2(const char *tag, const CameraParams *k, int withMatrix)
{
    printf("  key %s\n", tag);
    if (withMatrix)
        pmat(&k->Matrix);
    pv3("pos", &k->Position);
    pv3("dir", &k->Direction);
    pv3("tgt", &k->Target);
    printf("  scal %.9g %.9g %.9g %.9g %.9g fov %u\n",
           k->TargetDistance, k->FocalDistance, k->DepthOfField,
           k->NearZ, k->FarZ, (unsigned)k->FieldOfView);
}

static void pkey(const char *tag, const CameraParams *k)
{
    pkey2(tag, k, 1);
}

static void pcam(const Camera *c)
{
    pkey2("cur", &c->CurrentKey, 1);
    pkey2("prev", &c->PreviousKey, 1);
    pkey2("vel", &c->VelocityKey, 0);
    printf("  cam elapsed %.9g last %08lx dash %d car %d\n",
           c->ElapsedTime, (unsigned long)c->LastUpdateTime, c->RenderDash,
           c->CarNotToRender != 0);
}

static void porbit(const OrbitCarCameraMover *o)
{
    printf("  orb r %.9g dr %.9g h %u v %u dv %u hs %d vs %d dhs %d dvs %d\n",
           o->Radius, o->DesiredRadius, (unsigned)o->AngleH,
           (unsigned)o->AngleV, (unsigned)o->DesiredAngleV,
           o->HRotationSpeed, o->VRotationSpeed,
           o->DesiredHRotationSpeed, o->DesiredVRotationSpeed);
    printf("  orb minr %.9g maxr %.9g minv %u maxv %u mult %.9g accel %d"
           " appr %d fe %d en %d\n",
           o->MinRadius, o->MaxRadius, (unsigned)o->MinAngleV,
           (unsigned)o->MaxAngleV, o->RadiusMultiplier, o->MaxRotationAccel,
           o->ApproachAngleV, o->FEMode, o->base.Enabled);
}

// ------------------------------------------------------------------ the rng
//
// The same LCG as the emath harness, for the same reason: every step is exact
// in float32, so the model reproduces it without caring how its host rounds.

static uint32_t rngState;

static void rseed(uint32_t s)
{
    rngState = s;
}

static float frand(float scale)
{
    float u;

    rngState = rngState * 1103515245u + 12345u;
    u = (float)(int32_t)(rngState >> 8) * (1.0f / 8388608.0f) - 1.0f;
    return u * scale;
}

// A car placed and pointed by the rng. The body matrix is a real rotation --
// built by the engine's own eRotate* so it is orthonormal to the last bit --
// because feeding SetCameraMatrix a sheared matrix would test the arithmetic
// but not the decomposition.
static void rcar(CamCarView *car, uint16_t yaw, uint16_t pitch, float scale)
{
    bMatrix4 id;

    car->GeometryPosition.x = frand(scale);
    car->GeometryPosition.y = frand(scale);
    car->GeometryPosition.z = frand(scale);
    car->GeometryPosition.pad = 0.0f;
    car->Position.x = car->GeometryPosition.x + frand(1.0f);
    car->Position.y = car->GeometryPosition.y + frand(1.0f);
    car->Position.z = car->GeometryPosition.z + frand(1.0f);
    car->Position.pad = 0.0f;

    eIdentity(&id);
    eRotateZ(&car->BodyMatrix, &id, yaw);
    eRotateY(&car->BodyMatrix, &car->BodyMatrix, pitch);
}

// ---------------------------------------------------------------- scenarios

static void scenario_ctor(void)
{
    Camera c;

    printf("scenario ctor\n");
    camera_init(&c);
    pcam(&c);

    // The copy constructor, which resets LastUpdateTime and nothing else.
    // The reset only shows if the source is holding something other than
    // the 0x80000000 the constructor left, so put a real timestamp in
    // first; there is no setter for it because nothing but the frame loop
    // writes it.
    {
        Camera d;

        c.LastUpdateTime = 0x12345678u;
        camera_copy(&d, &c);
        printf("  copied\n");
        pcam(&d);
    }
}

static void scenario_setmatrix(void)
{
    Camera c;
    bMatrix4 m, id;
    int i;

    printf("scenario setmatrix\n");
    camera_init(&c);
    rseed(0x5a5a1234u);

    // A run of real view matrices: a rotation with a translation in row 3,
    // which is what every mover in the game hands over.
    for (i = 0; i < 10; i++) {
        eIdentity(&id);
        eRotateZ(&m, &id, (uint16_t)(i * 4000 + 137));
        eRotateX(&m, &m, (uint16_t)(i * 9001));
        m.v3.x = frand(100.0f);
        m.v3.y = frand(100.0f);
        m.v3.z = frand(100.0f);
        camera_set_matrix(&c, &m, 1.0f / 60.0f);
        printf("  frame %d\n", i);
        pcam(&c);
    }

    // Moving the scalars between frames, which does NOT make the velocity
    // key do anything: the six scalar velocities are zero by construction,
    // because SetCameraMatrix copies the key it is about to difference. The
    // steps below are kept anyway -- they are what proves it, and the
    // CurrentKey and PreviousKey halves of the transcript still move.
    camera_set_target_distance(&c, 25.0f);
    camera_set_focal_distance(&c, 7.5f);
    camera_set_depth_of_field(&c, 3.25f);
    camera_set_near_z(&c, 0.125f);
    camera_set_far_z(&c, 9000.0f);
    camera_set_field_of_view(&c, 200);
    camera_set_matrix(&c, &m, 0.5f);
    printf("  scalars moved\n");
    pcam(&c);

    // 200 -> 65500 would be a wrap if the difference were ever taken across
    // two different values. It is not -- see above -- so what these four
    // steps actually pin down is that the field of view itself moves and
    // that its velocity stays 0 while it does.
    camera_set_field_of_view(&c, 65500);
    camera_set_matrix(&c, &m, 0.5f);
    printf("  fov wrapped\n");
    pcam(&c);
    camera_set_field_of_view(&c, 200);
    camera_set_matrix(&c, &m, 0.25f);
    printf("  fov wrapped back\n");
    pcam(&c);

    // A fractional scale and an odd product, which is what it would take to
    // tell a u16 difference from a signed one and a truncation from a
    // rounding IF the difference were ever non-zero. Kept as the record of
    // the attempt: these two steps are why the three FOV mutations are
    // listed as equivalent in camera_check.py rather than as holes.
    camera_set_field_of_view(&c, 65500);
    camera_set_matrix(&c, &m, 2.0f);
    printf("  fov half step\n");
    pcam(&c);
    camera_set_field_of_view(&c, 201);
    camera_set_matrix(&c, &m, 2.0f);
    printf("  fov half step odd\n");
    pcam(&c);

    // A matrix with something in the fourth column, like the constructor's.
    eIdentity(&m);
    m.v2.w = 100.0f;
    m.v3.z = 1200.0f;
    camera_set_matrix(&c, &m, 1.0f);
    printf("  fourth column\n");
    pcam(&c);

    // And a frozen camera: every one of these must leave it alone.
    CameraStopUpdating = 1;
    eIdentity(&m);
    m.v3.x = 999.0f;
    camera_set_matrix(&c, &m, 1.0f);
    printf("  frozen\n");
    pcam(&c);
    CameraStopUpdating = 0;
}

static void scenario_orbit_init(void)
{
    Camera c;
    OrbitCarCameraMover o;
    CamCarView car;

    printf("scenario orbitinit\n");
    rseed(0x0c0ffee1u);
    rcar(&car, 1000, 2000, 30.0f);

    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 2);
    porbit(&o);
    pcam(&c);
    printf("  type %s\n", camera_mover_type_name(o.base.Type));
    pv3("target", orbit_get_target(&o));

    // ViewID -1 leaves it detached, which is the only way to get a mover
    // with no camera at all.
    {
        OrbitCarCameraMover d;
        CameraMover b;

        camera_mover_init(&b, -1, &c, CM_DRIVE);
        printf("  detached type %s view %d enabled %d camera %d\n",
               camera_mover_type_name(b.Type), b.ViewID, b.Enabled,
               b.pCamera != 0);

        camera_init(&c);
        orbit_init(&d, 3, &c, 0, 0);
        printf("  carless\n");
        porbit(&d);
        pv3("target", orbit_get_target(&d));
    }

    // Every name in the enum, plus the two out-of-range answers.
    {
        int i;

        for (i = -1; i <= 18; i++)
            printf("  name %2d %s\n", i,
                   camera_mover_type_name((CameraMoverType)i));
    }
}

// Enable and Disable are not symmetric and neither one is a plain flag
// write, so they get their own scenario: the two render flags move between
// the mover and the camera in one direction on the way in and the other on
// the way out, the near plane is forced on every enable, and
// CameraStopUpdating stops one of them and not the other.
static void pmover(const char *tag, const CameraMover *m, const Camera *c)
{
    printf("  %s en %d movercar %d moverdash %d camcar %d camdash %d"
           " near %.9g far %.9g\n",
           tag, m->Enabled, m->CarNotToRender != 0, m->RenderDash,
           c->CarNotToRender != 0, c->RenderDash, c->CurrentKey.NearZ,
           c->CurrentKey.FarZ);
}

static void scenario_enable(void)
{
    Camera c;
    CameraMover m;
    int dash1 = 1, dash2 = 2;

    printf("scenario enable\n");

    // A fresh mover takes the camera's flags at construction and pushes them
    // straight back, so nothing appears to move. Then the camera is changed
    // behind its back and disabled, which is what pulls the change in.
    camera_init(&c);
    c.CarNotToRender = &dash1;
    c.RenderDash = 7;
    camera_mover_init(&m, 0, &c, CM_STILL);
    pmover("constructed", &m, &c);

    c.CarNotToRender = 0;
    c.RenderDash = 9;
    camera_mover_disable(&m);
    pmover("disabled", &m, &c);

    // A second disable must do nothing at all, including not picking the
    // camera's flags up a second time.
    c.RenderDash = 11;
    camera_mover_disable(&m);
    pmover("disabled twice", &m, &c);

    // Re-enabling pushes what the mover is now holding, and forces NearZ.
    c.CurrentKey.NearZ = 123.0f;
    camera_mover_enable(&m);
    pmover("re-enabled", &m, &c);

    // Enabling an enabled mover is the early-out, so NearZ stays where the
    // test just put it.
    c.CurrentKey.NearZ = 456.0f;
    camera_mover_enable(&m);
    pmover("enabled twice", &m, &c);

    // Frozen: Enable skips the two flags but still writes NearZ, and Disable
    // ignores the freeze completely.
    camera_mover_disable(&m);
    m.CarNotToRender = &dash2;
    m.RenderDash = 33;
    c.CarNotToRender = 0;
    c.RenderDash = 0;
    c.CurrentKey.NearZ = 789.0f;
    CameraStopUpdating = 1;
    camera_mover_enable(&m);
    pmover("frozen enable", &m, &c);
    c.RenderDash = 44;
    camera_mover_disable(&m);
    pmover("frozen disable", &m, &c);
    CameraStopUpdating = 0;

    // And the orbit mover's own constructor, which clears both flags on the
    // camera and sets the field of view -- unless the camera is frozen.
    {
        OrbitCarCameraMover o;

        camera_init(&c);
        c.CarNotToRender = &dash1;
        c.RenderDash = 5;
        orbit_init(&o, 0, &c, 0, 0);
        printf("  orbit ctor camcar %d camdash %d fov %u handlers %d\n",
               c.CarNotToRender != 0, c.RenderDash,
               (unsigned)c.CurrentKey.FieldOfView, o.HandlersAdded);

        camera_init(&c);
        c.CarNotToRender = &dash1;
        c.RenderDash = 5;
        CameraStopUpdating = 1;
        orbit_init(&o, 0, &c, 0, 0);
        printf("  orbit ctor frozen camcar %d camdash %d fov %u\n",
               c.CarNotToRender != 0, c.RenderDash,
               (unsigned)c.CurrentKey.FieldOfView);
        CameraStopUpdating = 0;
    }
}

static void scenario_orbit_spin(void)
{
    Camera c;
    OrbitCarCameraMover o;
    CamCarView car;
    int i;

    printf("scenario orbitspin\n");
    rseed(0x1eaf00du);
    rcar(&car, 0, 0, 10.0f);
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);

    // Spin left for a while, then right, then stop: the acceleration limiter
    // has to ramp both ways and settle exactly on the desired speed.
    for (i = 0; i < 24; i++) {
        if (i == 0)  orbit_set_desired_h_rotation_speed(&o, ORBIT_JOY_SPEED);
        if (i == 8)  orbit_set_desired_h_rotation_speed(&o, -ORBIT_JOY_SPEED);
        if (i == 16) orbit_set_desired_h_rotation_speed(&o, 0);
        if (i == 4)  orbit_set_desired_v_rotation_speed(&o, 100);
        if (i == 12) orbit_set_desired_v_rotation_speed(&o, -100);

        // Drive the car around underneath it, so the boom has to follow.
        car.GeometryPosition.x = (float)i * 1.5f;
        car.GeometryPosition.y = (float)i * -0.25f;
        car.GeometryPosition.z = 0.5f;
        rcar(&car, (uint16_t)(i * 2731), (uint16_t)(i * 512), 0.0f);
        car.GeometryPosition.x = (float)i * 1.5f;
        car.GeometryPosition.y = (float)i * -0.25f;
        car.GeometryPosition.z = 0.5f;

        orbit_update(&o, 1.0f / 60.0f);
        printf("  spin %d\n", i);
        porbit(&o);
        pkey("cur", &c.CurrentKey);
        pkey2("vel", &c.VelocityKey, 0);
    }
}

static void scenario_orbit_limits(void)
{
    Camera c;
    OrbitCarCameraMover o;
    CamCarView car;
    int i;

    printf("scenario orbitlimits\n");
    rseed(0xfeed5eedu);
    rcar(&car, 12345, 54321, 5.0f);

    // Zoom out until MaxRadius bites, then in until MinRadius does. The
    // multiplier compounds, so this is a geometric walk in both directions.
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);
    orbit_set_max_radius(&o, 12.0f);
    orbit_set_min_radius(&o, 2.0f);
    for (i = 0; i < 40; i++) {
        orbit_set_radius_multiplier(&o, i < 20 ? ORBIT_ZOOM_OUT
                                               : ORBIT_ZOOM_IN);
        orbit_update(&o, 1.0f / 60.0f);
        printf("  zoom %d r %.9g dr %.9g td %.9g fd %.9g\n", i, o.Radius,
               o.DesiredRadius, c.CurrentKey.TargetDistance,
               c.CurrentKey.FocalDistance);
    }

    // A multiplier of exactly 1.0 must not touch DesiredRadius at all.
    orbit_set_radius_multiplier(&o, 1.0f);
    orbit_set_desired_radius(&o, 6.0f);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  held r %.9g dr %.9g\n", o.Radius, o.DesiredRadius);

    // The elevation clamp, walked past both ends.
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);
    orbit_set_desired_v_rotation_speed(&o, 400);
    orbit_set_v_rotation_speed(&o, 400);
    for (i = 0; i < 20; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  up %d v %u\n", i, (unsigned)o.AngleV);
    }
    orbit_set_desired_v_rotation_speed(&o, -400);
    orbit_set_v_rotation_speed(&o, -400);
    for (i = 0; i < 20; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  down %d v %u\n", i, (unsigned)o.AngleV);
    }

    // ApproachAngleV: the 80-BAM walk, from both sides and from a gap small
    // enough to snap. MinAngleV/MaxAngleV are widened so the clamp does not
    // hide what the walk is doing.
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);
    orbit_set_min_angle_v(&o, 0);
    orbit_set_max_angle_v(&o, 65535);
    orbit_set_approach_angle_v(&o, 1);
    orbit_set_angles(&o, 0, 1000);
    orbit_set_desired_angle_v(&o, 1500);
    for (i = 0; i < 10; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  appr up %d v %u\n", i, (unsigned)o.AngleV);
    }
    orbit_set_desired_angle_v(&o, 900);
    for (i = 0; i < 10; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  appr down %d v %u\n", i, (unsigned)o.AngleV);
    }
    // Exactly 80 away, and exactly 81 away: the compare is `< 81`.
    orbit_set_angle_v(&o, 1000);
    orbit_set_desired_angle_v(&o, 1080);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  appr exact80 %u\n", (unsigned)o.AngleV);
    orbit_set_angle_v(&o, 1000);
    orbit_set_desired_angle_v(&o, 1081);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  appr exact81 %u\n", (unsigned)o.AngleV);

    // An inverted elevation window. Nothing on the disc sets one up, but it
    // is the only thing that can tell the clamp's order apart -- max first
    // and then min, so an inverted window ends at MinAngleV -- and the
    // order is what the listing shows at 0x00154e88.
    orbit_set_approach_angle_v(&o, 0);
    orbit_set_min_angle_v(&o, 60000);
    orbit_set_max_angle_v(&o, 1000);
    orbit_set_angle_v(&o, 30000);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  inverted window v %u\n", (unsigned)o.AngleV);

    // The acceleration limiter's own boundary: a gap of exactly accel, one
    // below it, and one above.
    {
        int accel = o.MaxRotationAccel;
        int gaps[3];
        int g;

        gaps[0] = accel - 1; gaps[1] = accel; gaps[2] = accel + 1;
        for (g = 0; g < 3; g++) {
            orbit_set_h_rotation_speed(&o, 0);
            orbit_set_desired_h_rotation_speed(&o, gaps[g]);
            orbit_update(&o, 1.0f / 60.0f);
            printf("  accel +%d -> %d\n", gaps[g], o.HRotationSpeed);
            orbit_set_h_rotation_speed(&o, 0);
            orbit_set_desired_h_rotation_speed(&o, -gaps[g]);
            orbit_update(&o, 1.0f / 60.0f);
            printf("  accel -%d -> %d\n", gaps[g], o.HRotationSpeed);
        }
    }
}

static void scenario_tweakables(void)
{
    Camera c;
    OrbitCarCameraMover o;
    CamCarView car;
    int i;

    printf("scenario tweakables\n");
    rseed(0xabcdef01u);
    rcar(&car, 20000, 3000, 8.0f);

    // With UseTweakables on, the live angles still advance but the matrix is
    // built from the three Tweak* ones instead.
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);
    orbit_set_desired_h_rotation_speed(&o, 500);
    // Off the default 5.0, or the boom length is TweakRadius either way and
    // the switch proves nothing about the radius.
    orbit_set_desired_radius(&o, 3.0f);
    OrbitUseTweakables = 1;
    for (i = 0; i < 4; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  tweak %d\n", i);
        porbit(&o);
        pkey("cur", &c.CurrentKey);
    }
    OrbitUseTweakables = 0;
    for (i = 0; i < 4; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  live %d\n", i);
        porbit(&o);
        pkey("cur", &c.CurrentKey);
    }

    // The field of view the mover writes is TweakOrbitFOV and not InGameFOV,
    // every frame, whatever UseTweakables says. Prove it by putting the
    // constructor's value back by hand and watching Update take it away.
    camera_set_field_of_view(&c, OrbitInGameFOV);
    printf("  fov before %u\n", (unsigned)c.CurrentKey.FieldOfView);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  fov after %u (InGameFOV %u, TweakOrbitFOV %u)\n",
           (unsigned)c.CurrentKey.FieldOfView, (unsigned)OrbitInGameFOV,
           (unsigned)OrbitTweakOrbitFOV);

    // A frozen camera stops the mover writing anything, but the mover's own
    // state still advances.
    CameraStopUpdating = 1;
    camera_set_field_of_view(&c, 111);
    for (i = 0; i < 3; i++)
        orbit_update(&o, 1.0f / 60.0f);
    printf("  frozen fov %u h %u\n", (unsigned)c.CurrentKey.FieldOfView,
           (unsigned)o.AngleH);
    CameraStopUpdating = 0;

    // And the carless path, which is the only reader of OrbitTargetHeight.
    camera_init(&c);
    orbit_init(&o, 0, &c, 0, 0);
    for (i = 0; i < 3; i++) {
        orbit_update(&o, 1.0f / 60.0f);
        printf("  carless %d\n", i);
        pkey("cur", &c.CurrentKey);
    }

    // The boom offset is zero on the disc; move it once to show where it
    // lands, then put it back.
    OrbitBoomOffset.x = 1.0f;
    OrbitBoomOffset.y = 2.0f;
    OrbitBoomOffset.z = 3.0f;
    camera_init(&c);
    orbit_init(&o, 0, &c, &car, 0);
    orbit_update(&o, 1.0f / 60.0f);
    printf("  offset\n");
    pkey("cur", &c.CurrentKey);
    OrbitBoomOffset.x = 0.0f;
    OrbitBoomOffset.y = 0.0f;
    OrbitBoomOffset.z = 0.0f;
}

int main(void)
{
    scenario_ctor();
    scenario_setmatrix();
    scenario_orbit_init();
    scenario_enable();
    scenario_orbit_spin();
    scenario_orbit_limits();
    scenario_tweakables();
    return 0;
}
