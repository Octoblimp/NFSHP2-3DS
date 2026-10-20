// zonecam -- zonecameras.cpp's movers. See zonecam.h.

#include "zonecam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "bmatrix.h"
#include "bmem.h"
#include "camera.h"
#include "car.h"
#include "carinit.h"
#include "eefpu.h"
#include "emath.h"
#include "player.h"
#include "playerzone.h"
#include "race.h"
#include "realdriver.h"
#include "realtime.h"

// The allocations' file name, as retail's bMalloc gives it.
#define ZONECAMERAS_CPP "..\\indep\\src\\zonecameras.cpp"

// ConstrainToTopology's distance off a polygon, gp-30892.
#define ZONE_WALL_GAP        0.7f

// The swing: 32 points, 0.67 of a turn (gp-30876) from 0.15 of one
// (gp-30872) past the camera, in steps of 1/31 (gp-30880); the eye on a
// circle of 8 at 2 above the car, the look point on one of 0.1 (gp-30868)
// at 1.2 (gp-30864); the interest box 8.7 about each look point
// (gp-30860). Below 0.01 m/s (gp-30888) the car's heading, not its
// velocity, points the circle; a nose within 0.001 (gp-30884) of straight
// up takes the roof's.
#define ZF_POINTS            32
#define ZF_STEP              0.032258063f
#define ZF_SWEEP             0.67f
#define ZF_LEAD              0.15f
#define ZF_EYE_RADIUS        8.0f
#define ZF_EYE_HEIGHT        2.0f
#define ZF_LOOK_RADIUS       0.1f
#define ZF_LOOK_HEIGHT       1.2f
#define ZF_LOOK_BOX          8.7f
#define ZF_MOVING            0.01f
#define ZF_UPRIGHT           0.001f

// The blends: in over 0.4 s (gp-30856, -30852, -30840 for the focus pull),
// out over the last 0.6 (gp-30844, -30836), from 2.4 s (gp-30824); the
// spline's tangent scaled by 0.4 (gp-30848) against its length in points.
#define ZF_BLEND_IN          0.4f
#define ZF_BLEND_OUT         0.6f
#define ZF_BLEND_OUT_AT      2.4f
#define ZF_TANGENT           0.4f

// The radial blur's alpha, 0.84 of full (gp-30828, -30816), up over the
// blend in at 2.5 a second and down over the blend out at 1/0.6
// (gp-30820); the sample's sweep, a turn in degrees to radians
// (gp-30808) and a quarter turn on (gp-30812).
#define ZF_BLUR              0.84f
#define ZF_BLUR_IN_RATE      2.5f
#define ZF_BLUR_OUT_RATE     1.6666666f
#define ZF_DEG_TO_RAD        0.017453294f
#define ZF_QUARTER_TURN      1.5707965f

#define ZF_DURATION          3.0f

// ------------------------------------------------------------ the vtable

static void zf_destroy_thunk(CameraMover *m)
{
    zone_freeze_camera_mover_destroy((ZoneFreezeCameraMover *)m);
}

static void zf_update_thunk(CameraMover *m)
{
    zone_freeze_camera_mover_update((ZoneFreezeCameraMover *)m);
}

// The base's (0x0015fcf8), which cammover.c keeps to itself.
static void *zf_get_car_to_follow(CameraMover *m)
{
    (void)m;
    return NULL;
}

// 0x002b20d0.
const CameraMoverVtbl ZoneFreezeCameraMoverVtbl = {
    zf_destroy_thunk,
    zf_update_thunk,
    camera_mover_render,
    camera_mover_nothing,       // AddJoyHandlers
    camera_mover_nothing,       // RemoveJoyHandlers
    camera_mover_get_camera_info,
    camera_mover_get_pov,
    camera_mover_is_exterior_view,
    camera_mover_is_looking_back,
    camera_mover_get_wall_gap,
    camera_mover_nothing,       // ResetState
    camera_mover_enable,
    camera_mover_disable,
    zf_get_car_to_follow,
    camera_mover_get_target,
};

// ---------------------------------------------------------- the helpers

int32_t zone_constrain_to_topology(TopologyCoordinate *tc, bVector3 *from,
                                   bVector3 *to, int32_t ways,
                                   int32_t sides)
{
    int twoSided = sides == 1;
    int32_t r;

    r = topology_constrain(tc, TOPOLOGY_CONSTRAIN_BY_ROTATION, twoSided,
                           from, to, ZONE_WALL_GAP, 1.0f) != 0;
    r |= topology_constrain(tc, TOPOLOGY_CONSTRAIN_BY_SCALE, twoSided,
                            from, to, ZONE_WALL_GAP, 1.0f) != 0;
    if (ways == 1) {
        r |= topology_constrain(tc, TOPOLOGY_CONSTRAIN_BY_ROTATION, twoSided,
                                to, from, ZONE_WALL_GAP, 1.0f) != 0;
        r |= topology_constrain(tc, TOPOLOGY_CONSTRAIN_BY_SCALE, twoSided,
                                to, from, ZONE_WALL_GAP, 1.0f) != 0;
    }
    return r;
}

void zone_ensure_eye_above_ground(TopologyCoordinate *tc, bVector3 *eye,
                                  float clearance)
{
    float ground;

    topology_set_interest_bbox3(tc, eye, 10.0f, NULL);
    ground = topology_get_elevation(tc, eye, NULL, NULL, NULL);
    if (ground - clearance < eye->z && eye->z < ground + clearance)
        eye->z = ground + clearance;
}

// `vopmula.xyz ACC,vfA,vfB` / `vopmsub.xyz vfD,vfB,vfA`, A cross B. Each
// destination is A's register, so the w lane is A's.
static void cross3(bVector4 *o, const bVector4 *a, const bVector4 *b)
{
    float x = a->y * b->z - b->y * a->z;
    float y = a->z * b->x - b->z * a->x;
    float z = a->x * b->y - b->x * a->y;

    o->x = x;
    o->y = y;
    o->z = z;
    o->w = a->w;
}

// a*k + b and a - b, on all four lanes, as VU0's vmulx/vadd and vsub.
static void scale_add(bVector3 *o, const bVector3 *a, float k,
                      const bVector3 *b)
{
    o->x = a->x * k + b->x;
    o->y = a->y * k + b->y;
    o->z = a->z * k + b->z;
    o->pad = a->pad * k + b->pad;
}

static void scale(bVector3 *o, const bVector3 *a, float k)
{
    o->x = a->x * k;
    o->y = a->y * k;
    o->z = a->z * k;
    o->pad = a->pad * k;
}

static void sub(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x - b->x;
    o->y = a->y - b->y;
    o->z = a->z - b->z;
    o->pad = a->pad - b->pad;
}

// The spline's last parameter, as the image works it out inline at every
// use: n for a loop, n - 1 for the two that end, else 0.
static float spline_last(const Spline *s)
{
    if (s->Type == SPLINE_LOOP)
        return (float)s->NumControlPoints;
    if (s->Type == SPLINE_CLAMP || s->Type == SPLINE_EXTRAPOLATE)
        return (float)(s->NumControlPoints - 1);
    return 0.0f;
}

// A tCubic3D as the constructor makes each one: every value 0, the
// duration `d`, arriving at 1, idle and free to run. The coefficients and
// the parameter are not written.
static BSpline3D *new_blend(float d, int line)
{
    BSpline3D *b = (BSpline3D *)bMalloc((int)sizeof(BSpline3D),
                                        ZONECAMERAS_CPP, line, 16);
    BSpline *lane[3];
    int i;

    lane[0] = &b->x;
    lane[1] = &b->y;
    lane[2] = &b->z;
    for (i = 0; i < 3; i++) {
        lane[i]->val = 0.0f;
        lane[i]->dval = 0.0f;
        lane[i]->valDesired = 0.0f;
        lane[i]->dvalDesired = 0.0f;
        lane[i]->arrivalThreshold = 1.0f;
        lane[i]->state = 0;
        lane[i]->duration = d;
        lane[i]->flags = 0;
    }
    return b;
}

static struct Player *zf_player(const ZoneFreezeCameraMover *m)
{
    return (struct Player *)m->base.pPlayer;
}

// RadialBlurAlpha (0x0010f238), the player's from and to alphas.
static void zf_blur(const ZoneFreezeCameraMover *m, float to)
{
    if (gRadialBlurAlphaFn != NULL)
        gRadialBlurAlphaFn(zf_player(m)->PlayerNumber, 0.0f, to);
}

// ------------------------------------------------------ the constructor

ZoneFreezeCameraMover *zone_freeze_camera_mover_init(ZoneFreezeCameraMover *m,
                                                     int viewID,
                                                     struct Car *car,
                                                     CameraMover *saved)
{
    Camera *cam;
    bMatrix4 frame, inv;
    bVector4 rel4, side;
    bVector3 eye, look, local, pt, at, from, p, dp, dv;
    bVector2 heading;
    float sign, d, dir, start, last;
    uint16_t fov;
    int i;

    // CM_STILL, 12, as the image passes it, not CM_ZONE_FREEZE; nothing
    // reads a mover's type back but for CM_DRIVE and CM_BUMPER.
    camera_mover_init(&m->base, viewID, CM_STILL);
    m->fTime = 0.0f;
    m->base.vtbl = &ZoneFreezeCameraMoverVtbl;
    spline_init_alloc(&m->EyeSpline, SPLINE_EXTRAPOLATE, 100, 16384);
    spline_init_alloc(&m->LookSpline, SPLINE_EXTRAPOLATE, 100, 16384);
    topology_init(&m->Topology);

    // The car's frame a frame on: x the way it goes, flat; z up.
    bIdentity(&frame);
    if (ZF_MOVING < car->State.VelocityMagnitude) {
        heading.x = car->State.Velocity.x;
        heading.y = car->State.Velocity.y;
    } else if (fabsf(1.0f - car->State.BodyMatrix.v0.z) <= ZF_UPRIGHT) {
        heading.x = -car->State.BodyMatrix.v2.x;
        heading.y = -car->State.BodyMatrix.v2.y;
    } else {
        heading.x = car->State.BodyMatrix.v0.x;
        heading.y = car->State.BodyMatrix.v0.y;
    }
    bNormalize2(&heading, &heading);
    frame.v0.x = heading.x;
    frame.v0.y = heading.y;
    cross3(&frame.v1, &frame.v2, &frame.v0);
    frame.v3.x = car->State.Velocity.x * WorldTimeElapsed
                 + car->State.Position.x;
    frame.v3.y = car->State.Velocity.y * WorldTimeElapsed
                 + car->State.Position.y;
    frame.v3.z = car->State.Velocity.z * WorldTimeElapsed
                 + car->State.Position.z;
    frame.v3.w = car->State.Velocity.pad * WorldTimeElapsed
                 + car->State.Position.pad;

    // The camera a frame on.
    cam = m->base.pCamera;
    scale_add(&eye, &cam->VelocityKey.Position, WorldTimeElapsed,
              &cam->CurrentKey.Position);
    scale_add(&look, &cam->VelocityKey.Target, WorldTimeElapsed,
              &cam->CurrentKey.Target);

    // Where the eye is round the car, and which way it is going round:
    // the swing goes on that way, and from the car's other side for a
    // camera inside it.
    eInvertTransformationMatrix(&inv, &frame);
    bMulMatrixVec3(&local, &inv, &eye);
    sign = saved->vtbl->IsExteriorView(saved) ? 1.0f : -1.0f;
    scale(&local, &local, sign);
    rel4.x = cam->VelocityKey.Position.x - car->State.Velocity.x;
    rel4.y = cam->VelocityKey.Position.y - car->State.Velocity.y;
    rel4.z = cam->VelocityKey.Position.z - car->State.Velocity.z;
    rel4.w = 0.0f;
    bMulMatrixVec4(&rel4, &inv, &rel4);
    {
        bVector4 l4;

        l4.x = local.x;
        l4.y = local.y;
        l4.z = local.z;
        l4.w = local.pad;
        cross3(&side, &frame.v2, &l4);
    }
    d = rel4.x * side.x + rel4.y * side.y;
    d = d + rel4.z * side.z;
    dir = (0.0f <= d ? 1.0f : -1.0f) * sign;
    start = (float)bATan(local.x, local.y) * (1.0f / 65536.0f)
            + dir * ZF_LEAD;

    for (i = 0; i < ZF_POINTS; i++) {
        float a = start + (float)i * ZF_STEP * dir * ZF_SWEEP;
        uint16_t bam = (uint16_t)ee_trunc_w(a * 65536.0f);
        float s = bSinBam(bam), c = bCosBam(bam);

        pt.x = c * ZF_LOOK_RADIUS;
        pt.y = s * ZF_LOOK_RADIUS;
        pt.z = ZF_LOOK_HEIGHT;
        pt.pad = 0.0f;
        eMulVector3(&at, &frame, &pt);
        spline_add_control_point(&m->LookSpline, &at);
        pt.x = c * ZF_EYE_RADIUS;
        pt.y = s * ZF_EYE_RADIUS;
        pt.z = ZF_EYE_HEIGHT;
        eMulVector3(&from, &frame, &pt);
        topology_set_interest_bbox3(&m->Topology, &at, ZF_LOOK_BOX, NULL);
        zone_constrain_to_topology(&m->Topology, &at, &from, 1, 1);
        zone_ensure_eye_above_ground(&m->Topology, &from, 1.0f);
        spline_add_control_point(&m->EyeSpline, &from);
    }

    // In: from the camera, at its speed relative to the car, onto the
    // splines' starts, at their speeds.
    spline_get_point(&m->EyeSpline, &p, 0.0f);
    spline_get_derivative(&m->EyeSpline, &dp, 0.0f);
    sub(&dv, &cam->VelocityKey.Position, &car->State.Velocity);
    last = spline_last(&m->EyeSpline);
    scale(&dp, &dp, last * 0.5f * ZF_TANGENT);
    scale(&dv, &dv, ZF_BLEND_IN);
    m->pEyeBlendIn = new_blend(ZF_BLEND_IN, 573);
    bspline3d_set_val(m->pEyeBlendIn, &eye);
    bspline3d_set_dval(m->pEyeBlendIn, &dv);
    bspline3d_set_val_desired(m->pEyeBlendIn, &p);
    bspline3d_set_dval_desired(m->pEyeBlendIn, &dp);

    spline_get_point(&m->LookSpline, &p, 0.0f);
    spline_get_derivative(&m->LookSpline, &dp, 0.0f);
    sub(&dv, &cam->VelocityKey.Target, &car->State.Velocity);
    last = spline_last(&m->LookSpline);
    scale(&dp, &dp, last * 0.5f * ZF_TANGENT);
    scale(&dv, &dv, ZF_BLEND_IN);
    m->pLookBlendIn = new_blend(ZF_BLEND_IN, 590);
    bspline3d_set_val(m->pLookBlendIn, &look);
    bspline3d_set_dval(m->pLookBlendIn, &dv);
    bspline3d_set_val_desired(m->pLookBlendIn, &p);
    bspline3d_set_dval_desired(m->pLookBlendIn, &dp);

    // Out: from the splines' ends back onto the camera's course as it was.
    last = spline_last(&m->EyeSpline);
    spline_get_point(&m->EyeSpline, &p, last);
    spline_get_derivative(&m->EyeSpline, &dp, last);
    scale(&dp, &dp, last * 0.5f * ZF_TANGENT);
    scale(&dv, &cam->VelocityKey.Position, ZF_BLEND_OUT);
    m->pEyeBlendOut = new_blend(ZF_BLEND_OUT, 610);
    bspline3d_set_val(m->pEyeBlendOut, &p);
    bspline3d_set_dval(m->pEyeBlendOut, &dp);
    bspline3d_set_val_desired(m->pEyeBlendOut, &eye);
    bspline3d_set_dval_desired(m->pEyeBlendOut, &dv);

    last = spline_last(&m->LookSpline);
    spline_get_point(&m->LookSpline, &p, last);
    spline_get_derivative(&m->LookSpline, &dp, last);
    scale(&dp, &dp, last * 0.5f * ZF_TANGENT);
    scale(&dv, &cam->VelocityKey.Target, ZF_BLEND_OUT);
    m->pLookBlendOut = new_blend(ZF_BLEND_OUT, 626);
    bspline3d_set_val(m->pLookBlendOut, &p);
    bspline3d_set_dval(m->pLookBlendOut, &dp);
    bspline3d_set_val_desired(m->pLookBlendOut, &look);
    bspline3d_set_dval_desired(m->pLookBlendOut, &dv);

    // The focus pull: 1, going to 1.
    m->pFocusPull = (BSpline *)bMalloc((int)sizeof(BSpline), ZONECAMERAS_CPP,
                                       635, 16);
    m->pFocusPull->flags = 0;
    m->pFocusPull->state = 2;
    m->pFocusPull->valDesired = 1.0f;
    m->pFocusPull->arrivalThreshold = 1.0f;
    m->pFocusPull->val = 1.0f;
    m->pFocusPull->duration = ZF_BLEND_IN;
    m->pFocusPull->dval = 0.0f;
    m->pFocusPull->dvalDesired = 0.0f;

    fov = cam->CurrentKey.FieldOfView;
    m->fTanFov = bSinBam(fov) / bCosBam(fov);
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->RenderDash = 0;
    }
    return m;
}

CameraMover *zone_freeze_camera_mover_new(void *mem, int viewID,
                                          struct Car *car,
                                          CameraMover *saved)
{
    return &zone_freeze_camera_mover_init((ZoneFreezeCameraMover *)mem,
                                          viewID, car, saved)->base;
}

// ------------------------------------------------------- the destructor

void zone_freeze_camera_mover_destroy(ZoneFreezeCameraMover *m)
{
    m->base.vtbl = &ZoneFreezeCameraMoverVtbl;
    if (gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(zf_player(m)->PlayerNumber);
    bFree(m->pEyeBlendIn);
    bFree(m->pEyeBlendOut);
    bFree(m->pLookBlendIn);
    bFree(m->pLookBlendOut);
    bFree(m->pFocusPull);
    topology_destroy(&m->Topology);
    spline_destroy(&m->LookSpline, 2);
    spline_destroy(&m->EyeSpline, 2);
    camera_mover_destroy(&m->base);
}

float zone_freeze_camera_mover_duration(void)
{
    return ZF_DURATION;
}

// --------------------------------------------------------------- Update

void zone_freeze_camera_mover_update(ZoneFreezeCameraMover *m)
{
    float old, t, blur, out;
    bVector3 up, eye, look, d;
    bMatrix4 mat;
    BSpline *focus;
    int32_t fov;

    if (is_game_flow_paused())
        return;
    old = m->fTime;
    t = old + RealTimeElapsed;
    blur = 0.0f;
    out = 0.0f;
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    eye.pad = 0.0f;
    look.pad = 0.0f;
    m->fTime = t;

    if (t < ZF_BLEND_IN) {
        bspline3d_seek(m->pEyeBlendIn, RealTimeElapsed);
        bspline3d_seek(m->pLookBlendIn, RealTimeElapsed);
        bspline3d_get_val(m->pEyeBlendIn, &eye);
        bspline3d_get_val(m->pLookBlendIn, &look);
        zone_constrain_to_topology(&m->Topology, &look, &eye, 0, 0);
        blur = m->fTime * ZF_BLUR_IN_RATE;
        zf_blur(m, blur * ZF_BLUR);
    } else if (ZF_BLEND_OUT_AT < t) {
        if (old <= ZF_BLEND_OUT_AT) {
            focus = m->pFocusPull;
            focus->valDesired = 1.0f;
            focus->duration = zone_freeze_camera_mover_duration() - m->fTime;
            if (focus->val != 1.0f)
                focus->state = 2;
        }
        bspline3d_seek(m->pEyeBlendOut, RealTimeElapsed);
        bspline3d_seek(m->pLookBlendOut, RealTimeElapsed);
        bspline3d_get_val(m->pEyeBlendOut, &eye);
        bspline3d_get_val(m->pLookBlendOut, &look);
        zone_constrain_to_topology(&m->Topology, &look, &eye, 0, 0);
        blur = (zone_freeze_camera_mover_duration() - m->fTime)
               * ZF_BLUR_OUT_RATE;
        zf_blur(m, blur * ZF_BLUR);
        out = 1.0f - blur;
    } else {
        float u = (t - ZF_BLEND_IN) * 0.5f;

        spline_get_point(&m->EyeSpline, &eye, spline_last(&m->EyeSpline) * u);
        spline_get_point(&m->LookSpline, &look,
                         spline_last(&m->LookSpline) * u);
        blur = 1.0f;
    }

    // The focus pull draws the eye in along the line of sight and the
    // field of view in with it.
    focus = m->pFocusPull;
    bspline_seek(focus, RealTimeElapsed);
    sub(&d, &eye, &look);
    scale_add(&eye, &d, focus->val, &look);
    fov = bATan(focus->val, m->fTanFov);
    if (!CameraStopUpdating)
        m->base.pCamera->CurrentKey.FieldOfView = (uint16_t)fov;
    eCreateLookAtMatrix(&mat, &eye, &look, &up);
    camera_set_matrix(m->base.pCamera, &mat, RealTimeElapsed);

    // The wind goes once round the listener, its pitch up and back down.
    if (SoundEnabled) {
        uint16_t az = (uint16_t)ee_trunc_w(
            m->fTime / zone_freeze_camera_mover_duration() * 65536.0f);
        float a = m->fTime / zone_freeze_camera_mover_duration() * 360.0f
                  * ZF_DEG_TO_RAD + ZF_QUARTER_TURN;
        float pitch = bSinF(a) * 0.5f + 0.5f;

        player_update_zone_sound(zf_player(m), out + out, blur, az, pitch);
    }
}
