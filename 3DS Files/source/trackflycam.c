// trackflycam -- TrackFlyCameraMover. See trackflycam.h.

#include "trackflycam.h"

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
#define TRACK_FLY_SPLINE_TABLE 16384

// gp-31192, 0x41f00000 and 13020: the degrees' scale, the depth of field
// and the field of view with no car.
#define TRACK_FLY_DEG_TO_BAM   182.044449f
#define TRACK_FLY_DOF          30.0f
#define TRACK_FLY_FOV_NO_CAR   13020

// ------------------------------------------------------------ the vtable

static void track_fly_destroy_thunk(CameraMover *m)
{
    track_fly_camera_mover_destroy((TrackFlyCameraMover *)m);
}

// The vtable's Update takes no argument; the mover reads the two clocks.
static void track_fly_update_thunk(CameraMover *m)
{
    track_fly_camera_mover_update((TrackFlyCameraMover *)m, WorldTimeElapsed,
                                  RealTimeElapsed);
}

// 0x0015faf8.
static void *track_fly_get_car_to_follow(CameraMover *m)
{
    return ((TrackFlyCameraMover *)m)->CarToFollow;
}

static const bVector3 *track_fly_get_target_thunk(CameraMover *m)
{
    return track_fly_camera_mover_get_target((const TrackFlyCameraMover *)m);
}

const CameraMoverVtbl TrackFlyCameraMoverVtbl = {
    track_fly_destroy_thunk,
    track_fly_update_thunk,
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
    track_fly_get_car_to_follow,
    track_fly_get_target_thunk,
};

// ------------------------------------------------------------ the lanes

// VU0's: all four lanes, and the dot product as (x*x + y*y) + z*z.
static void v_sub(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x - b->x;
    o->y = a->y - b->y;
    o->z = a->z - b->z;
    o->pad = a->pad - b->pad;
}

static float v_dot(const bVector3 *a, const bVector3 *b)
{
    return (a->x * b->x + a->y * b->y) + a->z * b->z;
}

// ------------------------------------------------------ the constructor

TrackFlyCameraMover *track_fly_camera_mover_init(TrackFlyCameraMover *m,
                                                 int viewID,
                                                 const CameraDataItems *cd,
                                                 struct Car *car)
{
    Camera *cam;

    camera_mover_init(&m->base, viewID, CM_TRACK_FLY);
    m->base.vtbl = &TrackFlyCameraMoverVtbl;
    m->CD = *cd;
    spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.EyeVerts, TRACK_FLY_SPLINE_TABLE);
    spline_init(&m->BankSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.BankVerts, TRACK_FLY_SPLINE_TABLE);
    spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumLookVerts,
                m->CD.LookVerts, TRACK_FLY_SPLINE_TABLE);
    spline_init(&m->FOVSpline, SPLINE_CLAMP, 32, m->CD.FOVTable,
                TRACK_FLY_SPLINE_TABLE);
    cam = m->base.pCamera;
    m->EyeSplineParam = 0.0f;
    m->LookSplineParam = 0.0f;
    cam->CurrentKey.NearZ = m->CD.NearClip;
    m->CarToFollow = car;
    cam->CurrentKey.FarZ = m->CD.FarClip;
    return m;
}

void track_fly_camera_mover_destroy(TrackFlyCameraMover *m)
{
    Camera *cam = m->base.pCamera;

    m->base.vtbl = &TrackFlyCameraMoverVtbl;
    if (!CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = 0.0f;
        cam->CurrentKey.DepthOfField = 0.0f;
    }
    cam->ClearVelocity = 1;
    spline_destroy(&m->FOVSpline, 2);
    spline_destroy(&m->LookSpline, 2);
    spline_destroy(&m->BankSpline, 2);
    spline_destroy(&m->EyeSpline, 2);
    camera_mover_destroy(&m->base);
}

const bVector3 *track_fly_camera_mover_get_target(
    const TrackFlyCameraMover *m)
{
    if (m->CarToFollow != NULL)
        return &m->CarToFollow->State.GeometryPosition;
    return &m->base.pCamera->CurrentKey.Target;
}

int track_fly_camera_mover_is_finished(const TrackFlyCameraMover *m)
{
    int eyeDone = 0, lookDone = 0;

    if (m->CD.EyeSplineSpeed == 0.0f
        || (float)(m->CD.NumEyeVerts - 1) <= m->EyeSplineParam)
        eyeDone = 1;
    if (m->CD.LookSplineSpeed == 0.0f
        || (float)(m->CD.NumLookVerts - 1) <= m->LookSplineParam)
        lookDone = 1;
    return eyeDone ? lookDone : 0;
}

// ------------------------------------------------------------- Update

// How far round the track the car is, 0 to 1 the way the race runs.
// Retail works it out twice, the same way, each time from the car.
static float track_percent(const struct Car *car)
{
    float ratio = car->TheTrackPathCoordinate.RatioAroundTrack;

    if (RaceParametersTrackDirection == 0)
        return ratio * 100.0f * 0.01f;
    return (100.0f - ratio * 100.0f) * 0.01f;
}

// A parameter's step: locked to the car's share of the area, or on at its
// speed, then held at the spline's last point. No floor.
static float step_param(float param, int32_t lock, float speed, int32_t n,
                        const struct Car *car, float area, float dt)
{
    float last = (float)(n - 1);

    if (lock && car != NULL)
        param = last * area;
    else
        param = param + speed * dt * 25.0f;
    if (last < param)
        param = last;
    return param;
}

void track_fly_camera_mover_update(TrackFlyCameraMover *m, float dt,
                                   float elapsed)
{
    CameraDataItems *cd = &m->CD;
    struct Car *car = m->CarToFollow;
    Camera *cam = m->base.pCamera;
    bVector3 eye, look, bank, up, fov, d;
    bMatrix4 mat;
    float area = 0.0f, dist, focal;

    // The area's share has a floor and no ceiling.
    if (car != NULL) {
        area = (track_percent(car) - cd->MinAreaPercent)
               / (cd->MaxAreaPercent - cd->MinAreaPercent);
        if (area < 0.0f)
            area = 0.0f;
    }
    m->LookSplineParam = step_param(m->LookSplineParam,
                                    cd->LockLookSpeedToCar,
                                    cd->LookSplineSpeed, cd->NumLookVerts,
                                    car, area, dt);
    m->EyeSplineParam = step_param(m->EyeSplineParam, cd->LockEyeSpeedToCar,
                                   cd->EyeSplineSpeed, cd->NumEyeVerts, car,
                                   area, dt);

    spline_get_point(&m->EyeSpline, &eye, m->EyeSplineParam);
    spline_get_point(&m->LookSpline, &look, m->LookSplineParam);
    spline_get_point(&m->BankSpline, &bank, m->EyeSplineParam);
    camera_mover_compute_banked_up_vector(&m->base, &up, &eye, &look,
                                          (uint16_t)ee_trunc_w(bank.x));
    eCreateLookAtMatrix(&mat, &eye, &look, &up);

    if (car != NULL) {
        float span = (track_percent(car) - cd->MinPercent)
                     / (cd->MaxPercent - cd->MinPercent);
        uint16_t fovBam;

        if (span < 0.0f)
            span = 0.0f;
        if (1.0f < span)
            span = 1.0f;
        spline_get_point(&m->FOVSpline, &fov, span * 31.0f);
        if (cd->IsFOVIso) {
            v_sub(&d, &eye, &car->State.Position);
            dist = sqrtf(v_dot(&d, &d));
            if (dist < 1.0f)
                dist = 1.0f;
            fovBam = (uint16_t)(bATan(dist, fov.x * 0.25f) << 1);
        } else {
            fovBam = (uint16_t)ee_trunc_w(fov.x * TRACK_FLY_DEG_TO_BAM);
        }
        if (!CameraStopUpdating)
            cam->CurrentKey.FieldOfView = fovBam;
    } else if (!CameraStopUpdating) {
        cam->CurrentKey.FieldOfView = TRACK_FLY_FOV_NO_CAR;
    }

    v_sub(&d, &eye, &look);
    dist = sqrtf(v_dot(&d, &d));
    // max.s, against 2.
    focal = dist < 2.0f ? 2.0f : dist;
    if (!CameraStopUpdating) {
        cam->CurrentKey.TargetDistance = dist;
        cam->CurrentKey.FocalDistance = focal;
        cam->CurrentKey.DepthOfField = TRACK_FLY_DOF;
    }
    camera_set_matrix(cam, &mat, elapsed);
}
