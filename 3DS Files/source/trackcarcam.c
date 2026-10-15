// trackcarcam -- TrackCarCameraMover. See trackcarcam.h.

#include "trackcarcam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "camera.h"
#include "car.h"
#include "eefpu.h"
#include "emath.h"
#include "race.h"
#include "realtime.h"

// The splines' TableSize, as the constructor gives it.
#define TRACK_CAR_SPLINE_TABLE 16384

// gp-31232, gp-31228, gp-31216 and gp-31212.
#define TRACK_CAR_WIPE_FAR    1000000.0f
#define TRACK_CAR_FOCAL_TIME  0.42f
#define TRACK_CAR_DEG_TO_BAM  182.044449f
#define TRACK_CAR_FOCAL_SPEED 6.27f

// ------------------------------------------------------------ the vtable

static void track_car_destroy_thunk(CameraMover *m)
{
    track_car_camera_mover_destroy((TrackCarCameraMover *)m);
}

// The vtable's Update takes no argument; the mover reads the two clocks.
static void track_car_update_thunk(CameraMover *m)
{
    track_car_camera_mover_update((TrackCarCameraMover *)m, WorldTimeElapsed,
                                  RealTimeElapsed);
}

// 0x0015fb00.
static void *track_car_get_car_to_follow(CameraMover *m)
{
    return ((TrackCarCameraMover *)m)->CarToFollow;
}

static const bVector3 *track_car_get_target_thunk(CameraMover *m)
{
    return track_car_camera_mover_get_target((const TrackCarCameraMover *)m);
}

const CameraMoverVtbl TrackCarCameraMoverVtbl = {
    track_car_destroy_thunk,
    track_car_update_thunk,
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
    track_car_get_car_to_follow,
    track_car_get_target_thunk,
};

// ------------------------------------------------------------ the lanes

// VU0's: all four lanes, and the dot products as (x*x + y*y) + z*z.
static void v_sub(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x - b->x;
    o->y = a->y - b->y;
    o->z = a->z - b->z;
    o->pad = a->pad - b->pad;
}

static void v_add(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->pad = a->pad + b->pad;
}

static void v_scale(bVector3 *o, const bVector3 *a, float k)
{
    o->x = a->x * k;
    o->y = a->y * k;
    o->z = a->z * k;
    o->pad = a->pad * k;
}

static float v_dot(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// ------------------------------------------------------ the constructor

TrackCarCameraMover *track_car_camera_mover_init(
    TrackCarCameraMover *m, int viewID, struct Car *car,
    const CameraDataItems *cd, const CameraShake *shake, int focusEffects)
{
    BSpline *c = &m->FocalDistCubic;
    Camera *cam;
    int32_t r;

    camera_mover_init(&m->base, viewID, CM_TRACK_CAR);
    m->base.vtbl = &TrackCarCameraMoverVtbl;
    m->CD = *cd;
    m->TheCameraShake = *shake;
    spline_init(&m->FOVSpline, SPLINE_CLAMP, 32, m->CD.FOVTable,
                TRACK_CAR_SPLINE_TABLE);
    spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.EyeVerts, TRACK_CAR_SPLINE_TABLE);
    spline_init(&m->BankSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.BankVerts, TRACK_CAR_SPLINE_TABLE);
    spline_init(&m->ShakeSpline, SPLINE_CLAMP, m->TheCameraShake.NumCVs,
                m->TheCameraShake.CV, TRACK_CAR_SPLINE_TABLE);
    m->EyeSplineParam = 0.0f;
    m->ShakeSplineParam = 0.0f;
    c->val = 0.0f;
    c->flags = 1;
    m->CarToFollow = car;
    c->arrivalThreshold = 1.0f;
    m->FocusEffects = focusEffects;
    c->dval = 0.0f;
    c->valDesired = 0.0f;
    c->dvalDesired = 0.0f;
    c->duration = 1.0f;
    c->state = 0;
    cam = m->base.pCamera;
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->RenderDash = 0;
    }
    m->Look = car->State.Position;
    // The pad lane of the spring's two vectors is not written.
    m->SpringVelocity.x = m->CD.SpringXVel;
    m->SpringVelocity.y = m->CD.SpringYVel;
    m->SpringVelocity.z = m->CD.SpringYVel;
    m->SpringConstant = m->CD.SpringConst;
    m->DampingConstant = m->CD.SpringDamp;
    m->SpringDisplacement.x = 0.0f;
    m->SpringDisplacement.y = 0.0f;
    m->SpringDisplacement.z = 0.0f;
    m->WipeStart = m->CD.EyeVerts[0];
    m->WipeEnd = m->CD.EyeVerts[m->CD.NumEyeVerts - 1];
    m->WipeDistApart = TRACK_CAR_WIPE_FAR;
    cam->CurrentKey.NearZ = m->CD.NearClip;
    m->WipeTrackingHalted = 0;
    cam->CurrentKey.FarZ = m->CD.FarClip;
    c->flags = 1;
    c->duration = TRACK_CAR_FOCAL_TIME;
    // The focal cubic's start, then its seek to 0: SetVal and Seek,
    // inlined, each asking for a rebuild if the value moved.
    r = bRandomI(19, bViewSeed) + 26;
    if (bRandomI(2, bViewSeed) != 0)
        r = -r;
    c->val = (float)r;
    if (c->val != c->valDesired)
        c->state = 2;
    c->valDesired = 0.0f;
    if (c->val != 0.0f)
        c->state = 2;
    if (!m->FocusEffects && !CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = 0.0f;
        cam->CurrentKey.DepthOfField = 0.0f;
    }
    return m;
}

void track_car_camera_mover_destroy(TrackCarCameraMover *m)
{
    Camera *cam = m->base.pCamera;

    m->base.vtbl = &TrackCarCameraMoverVtbl;
    if (!CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = 0.0f;
        cam->CurrentKey.DepthOfField = 0.0f;
    }
    cam->ClearVelocity = 1;
    spline_destroy(&m->ShakeSpline, 2);
    spline_destroy(&m->BankSpline, 2);
    spline_destroy(&m->EyeSpline, 2);
    spline_destroy(&m->FOVSpline, 2);
    camera_mover_destroy(&m->base);
}

void track_car_camera_mover_calc_spring_force(const TrackCarCameraMover *m,
                                              bVector3 *o,
                                              const bVector3 *displacement,
                                              const bVector3 *velocity)
{
    bVector3 d, s;

    v_scale(&d, velocity, m->DampingConstant);
    v_scale(&s, displacement, m->SpringConstant);
    v_add(o, &d, &s);
}

const bVector3 *track_car_camera_mover_get_target(
    const TrackCarCameraMover *m)
{
    if (m->CarToFollow != NULL)
        return &m->CarToFollow->State.GeometryPosition;
    return &m->base.pCamera->CurrentKey.Target;
}

// ------------------------------------------------------------- Update

// A compensation: the record's entry value, or with IsLeaveSet the way
// from it to the leave value by `t`, times the distance and the tangent
// of half the field of view.
static float compensation(const CameraDataItems *cd, float enter,
                          float leave, float t, float dist, uint16_t half)
{
    float tanHalf;

    if (cd->IsLeaveSet) {
        float c = enter + t * (leave - enter);

        tanHalf = bSinBam(half) / bCosBam(half);
        return c * dist * tanHalf;
    }
    tanHalf = bSinBam(half) / bCosBam(half);
    return enter * dist * tanHalf;
}

void track_car_camera_mover_update(TrackCarCameraMover *m, float dt,
                                   float elapsed)
{
    CameraDataItems *cd = &m->CD;
    BSpline *c = &m->FocalDistCubic;
    struct Car *car;
    Camera *cam;
    bVector3 up, eye, fov, toEye, shake, side, off, dir, force, bank;
    bMatrix4 mat;
    float pct, area, span, dist, comp, focal, ratio;
    uint16_t fovBam, half;

    if (is_game_flow_paused())
        return;
    car = m->CarToFollow;
    cam = m->base.pCamera;
    ratio = car->TheTrackPathCoordinate.RatioAroundTrack;
    if (RaceParametersTrackDirection == 0)
        pct = ratio * 100.0f * 0.01f;
    else
        pct = (100.0f - ratio * 100.0f) * 0.01f;

    area = (pct - cd->MinAreaPercent)
           / (cd->MaxAreaPercent - cd->MinAreaPercent);
    if (area < 0.0f)
        area = 0.0f;
    if (1.0f < area)
        area = 1.0f;
    // The up vector's pad lane is the stack's.
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;

    if (cd->WipeDistance == 0.0f) {
        float last = (float)(cd->NumEyeVerts - 1);

        if (cd->LockEyeSpeedToCar)
            m->EyeSplineParam = last * area;
        else
            m->EyeSplineParam =
                m->EyeSplineParam + cd->EyeSplineSpeed * dt * 25.0f;
        if (last < m->EyeSplineParam)
            m->EyeSplineParam = last;
        spline_get_point(&m->EyeSpline, &eye, m->EyeSplineParam);
    } else {
        if (!m->WipeTrackingHalted) {
            bVector3 d, v, s, n;
            float a;

            v_sub(&d, &m->WipeEnd, &m->WipeStart);
            v_sub(&v, &car->State.Position, &m->WipeStart);
            a = v_dot(&d, &v) / v_dot(&d, &d);
            if (1.0f < a)
                a = 1.0f;
            if (a < 0.0f)
                a = 0.0f;
            v_scale(&s, &d, a);
            v_add(&eye, &m->WipeStart, &s);
            // bNormalize writes three lanes; the fourth is the stack's.
            n.pad = 0.0f;
            bNormalize3To(&n, &d, cd->WipeDistance);
            v_add(&eye, &eye, &n);
        } else {
            eye = cam->CurrentKey.Position;
        }
        if (cd->WipeAutoDisable) {
            bVector3 d;

            v_sub(&d, &car->State.Position, &eye);
            dist = sqrtf(v_dot(&d, &d));
            if (m->WipeDistApart < dist)
                m->WipeTrackingHalted = 1;
            m->WipeDistApart = dist;
        }
    }

    span = (pct - cd->MinPercent) / (cd->MaxPercent - cd->MinPercent);
    if (span < 0.0f)
        span = 0.0f;
    if (1.0f < span)
        span = 1.0f;
    spline_get_point(&m->FOVSpline, &fov, span * 31.0f);
    v_sub(&toEye, &eye, &car->State.Position);
    dist = sqrtf(v_dot(&toEye, &toEye));
    if (dist < 1.0f)
        dist = 1.0f;
    if (cd->IsFOVIso)
        fovBam = (uint16_t)(bATan(dist, fov.x * 0.25f) << 1);
    else
        fovBam = (uint16_t)ee_trunc_w(fov.x * TRACK_CAR_DEG_TO_BAM);
    if (!CameraStopUpdating)
        cam->CurrentKey.FieldOfView = fovBam;

    m->ShakeSplineParam =
        m->ShakeSplineParam + m->TheCameraShake.Speed * dt;
    if ((float)(m->TheCameraShake.NumCVs - 1) < m->ShakeSplineParam)
        m->ShakeSplineParam = (float)(m->TheCameraShake.NumCVs - 1);
    spline_get_point(&m->ShakeSpline, &shake, m->ShakeSplineParam);

    // Up by the vertical compensation less the shake's y, then sideways
    // by the horizontal one and the shake's x.
    m->Look = car->State.Position;
    half = (uint16_t)(fovBam >> 1);
    comp = compensation(cd, cd->EnterVertComp, cd->LeaveVertComp, area, dist,
                        half);
    m->Look.z = m->Look.z + (comp - shake.y);
    comp = compensation(cd, cd->EnterHorizComp, cd->LeaveHorizComp, area,
                        dist, half);
    v_scale(&toEye, &toEye, 1.0f / dist);
    // vopmula / vopmsub: toEye x up, the pad lane toEye's.
    side.x = toEye.y * up.z - up.y * toEye.z;
    side.y = toEye.z * up.x - up.z * toEye.x;
    side.z = toEye.x * up.y - up.x * toEye.y;
    side.pad = toEye.pad;
    v_scale(&side, &side, comp + shake.x);
    m->Look.x = m->Look.x + side.x;
    m->Look.y = m->Look.y + side.y;
    off.x = cd->LookOffsetX;
    off.y = cd->LookOffsetY;
    off.z = cd->LookOffsetZ;
    off.pad = 0.0f;
    eMulVector3(&off, &car->State.BodyMatrix, &off);
    v_add(&m->Look, &m->Look, &off);

    // The spring: the look point becomes the eye plus the unit way to it
    // plus the spring's displacement.
    v_sub(&dir, &m->Look, &eye);
    v_scale(&dir, &dir, 1.0f / sqrtf(v_dot(&dir, &dir)));
    track_car_camera_mover_calc_spring_force(m, &force,
                                             &m->SpringDisplacement,
                                             &m->SpringVelocity);
    v_sub(&m->SpringVelocity, &m->SpringVelocity, &force);
    v_add(&m->SpringDisplacement, &m->SpringDisplacement,
          &m->SpringVelocity);
    v_add(&dir, &dir, &m->SpringDisplacement);
    v_add(&m->Look, &eye, &dir);

    spline_get_point(&m->BankSpline, &bank, m->EyeSplineParam);
    camera_mover_compute_banked_up_vector(&m->base, &up, &eye, &m->Look,
                                          (uint16_t)ee_trunc_w(bank.x));
    eCreateLookAtMatrix(&mat, &eye, &m->Look, &up);

    {
        bVector3 d;

        v_sub(&d, &car->State.Position, &eye);
        dist = sqrtf(v_dot(&d, &d));
    }
    if (!CameraStopUpdating)
        cam->CurrentKey.TargetDistance = dist;
    cam->CurrentKey.NearZ = 0.5f;
    c->dvalDesired = c->val * TRACK_CAR_FOCAL_SPEED;
    bspline_seek(c, dt);
    focal = dist + c->val;
    if (focal < 2.0f)
        focal = 2.0f;
    if (m->FocusEffects && !CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = focal + c->val;
        cam->CurrentKey.DepthOfField = 7.5f;
    }
    camera_set_matrix(cam, &mat, elapsed);
}
