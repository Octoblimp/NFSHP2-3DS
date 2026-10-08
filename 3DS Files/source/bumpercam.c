// bumpercam -- BumperCameraMover. See bumpercam.h.

#include "bumpercam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "camera.h"
#include "car.h"
#include "drivecam.h"
#include "eefpu.h"
#include "emath.h"
#include "race.h"
#include "realtime.h"
#include "terraintype.h"
#include "track.h"

// The splines' TableSize, as the constructor gives it.
#define BUMPER_SPLINE_TABLE 16384

// gp-31244, gp-31240, gp-31236, 0x40f00000 and gp-31276: the road noise's
// share, the eye's height over the ground, the degrees' scale, the depth of
// field and the eye's room round the car.
#define BUMPER_NOISE_SCALE  0.877f
#define BUMPER_EYE_LIFT     0.7f
#define BUMPER_DEG_TO_BAM   182.044449f
#define BUMPER_DOF          7.5f
#define BUMPER_CAR_ROOM     0.7f
#define BUMPER_FOV_START    13020

// ------------------------------------------------------------ the vtable

static void bumper_destroy_thunk(CameraMover *m)
{
    bumper_camera_mover_destroy((BumperCameraMover *)m);
}

// The vtable's Update takes no argument; the mover reads the two clocks.
static void bumper_update_thunk(CameraMover *m)
{
    bumper_camera_mover_update((BumperCameraMover *)m, WorldTimeElapsed,
                               RealTimeElapsed);
}

// 0x0015fb10.
static void *bumper_get_car_to_follow(CameraMover *m)
{
    return ((BumperCameraMover *)m)->CarToFollow;
}

static const bVector3 *bumper_get_target_thunk(CameraMover *m)
{
    return bumper_camera_mover_get_target((const BumperCameraMover *)m);
}

const CameraMoverVtbl BumperCameraMoverVtbl = {
    bumper_destroy_thunk,
    bumper_update_thunk,
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
    bumper_get_car_to_follow,
    bumper_get_target_thunk,
};

// ------------------------------------------------------------ the lanes

// VU0's: all four lanes, and the dot product as (x*x + y*y) + z*z.
static void v_add(bVector3 *o, const bVector3 *a, const bVector3 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->pad = a->pad + b->pad;
}

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

BumperCameraMover *bumper_camera_mover_init(BumperCameraMover *m, int viewID,
                                            struct Car *car,
                                            const CameraDataItems *cd)
{
    Camera *cam;

    camera_mover_init(&m->base, viewID, CM_BUMPER);
    m->base.vtbl = &BumperCameraMoverVtbl;
    m->CD = *cd;
    spline_init(&m->EyeSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.EyeVerts, BUMPER_SPLINE_TABLE);
    spline_init(&m->BankSpline, SPLINE_CLAMP, m->CD.NumEyeVerts,
                m->CD.BankVerts, BUMPER_SPLINE_TABLE);
    m->EyeSplineParam = 0.0f;
    spline_init(&m->LookSpline, SPLINE_CLAMP, m->CD.NumLookVerts,
                m->CD.LookVerts, BUMPER_SPLINE_TABLE);
    m->LookSplineParam = 0.0f;
    spline_init(&m->FOVSpline, SPLINE_CLAMP, 32, m->CD.FOVTable,
                BUMPER_SPLINE_TABLE);
    m->CarToFollow = car;
    topology_init(&m->TheTopologyCoordinate);
    cam = m->base.pCamera;
    if (!CameraStopUpdating)
        cam->CarNotToRender = NULL;
    if (!CameraStopUpdating)
        cam->RenderDash = 0;
    if (!CameraStopUpdating)
        cam->CurrentKey.FieldOfView = BUMPER_FOV_START;
    cam->CurrentKey.NearZ = m->CD.NearClip;
    cam->CurrentKey.FarZ = m->CD.FarClip;
    return m;
}

CameraMover *bumper_camera_mover_construct(void *mem, int32_t viewID,
                                           struct Car *car,
                                           CameraDataItems *cd)
{
    return &bumper_camera_mover_init((BumperCameraMover *)mem, viewID, car,
                                     cd)->base;
}

void bumper_camera_mover_destroy(BumperCameraMover *m)
{
    Camera *cam = m->base.pCamera;

    m->base.vtbl = &BumperCameraMoverVtbl;
    if (!CameraStopUpdating)
        cam->CurrentKey.FocalDistance = 0.0f;
    if (!CameraStopUpdating)
        cam->CurrentKey.DepthOfField = 0.0f;
    topology_destroy(&m->TheTopologyCoordinate);
    spline_destroy(&m->FOVSpline, 2);
    spline_destroy(&m->LookSpline, 2);
    spline_destroy(&m->BankSpline, 2);
    spline_destroy(&m->EyeSpline, 2);
    camera_mover_destroy(&m->base);
}

const bVector3 *bumper_camera_mover_get_target(const BumperCameraMover *m)
{
    if (m->CarToFollow != NULL)
        return &m->CarToFollow->State.GeometryPosition;
    return &m->base.pCamera->CurrentKey.Target;
}

int bumper_camera_mover_is_finished(const BumperCameraMover *m)
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

int32_t bumper_camera_mover_is_finished_fn(CameraMover *m)
{
    return bumper_camera_mover_is_finished((const BumperCameraMover *)m);
}

// ------------------------------------------------------------- Update

// How far round the track the car is, 0 to 1 the way the race runs.
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
                        float area, float dt)
{
    float last = (float)(n - 1);

    if (lock)
        param = last * area;
    else
        param = param + speed * dt * 25.0f;
    if (last < param)
        param = last;
    return param;
}

// 0x00157c60, with the race racing. The eye of `mat` is moved off the walls
// by camera_wall_offset (round the car's GeometryPosition, through a
// coordinate of its own) and, if that leaves it within the car's half-width
// and 0.7 of the car, lifted on to that sphere. The look-at from there is
// turned to keep the car where `mat` had it on screen, back into `mat`.
static void bumper_keep_off_walls(BumperCameraMover *m, bMatrix4 *mat,
                                  struct Car *car)
{
    const bVector3 *geo = &car->State.GeometryPosition;
    TopologyCoordinate tc;
    bMatrix4 inv;
    bVector3 eye, mid, d, o, wall, bmin, bmax;
    bVector2 off;
    float r, dist, reach;

    eInvertTransformationMatrix(&inv, mat);
    eye.x = inv.v3.x;
    eye.y = inv.v3.y;
    eye.z = inv.v3.z;
    eye.pad = inv.v3.w;
    mid.x = geo->x * 0.5f + eye.x * 0.5f;
    mid.y = geo->y * 0.5f + eye.y * 0.5f;
    mid.z = geo->z * 0.5f + eye.z * 0.5f;
    mid.pad = geo->pad * 0.5f + eye.pad * 0.5f;
    v_sub(&d, geo, &eye);
    r = sqrtf(v_dot(&d, &d)) * 0.5f + 0.5f;
    topology_init(&tc);
    topology_set_interest_bbox3(&tc, &mid, r, NULL);
    eMulVector3(&o, mat, geo);
    off.x = o.x / o.z;
    off.y = o.y / o.z;
    camera_wall_offset(&m->base, &tc, geo, &eye, &wall);
    v_add(&eye, &eye, &wall);
    v_sub(&d, &eye, geo);
    dist = sqrtf(v_dot(&d, &d));
    car_get_car_space_bounding_box(car, &bmin, &bmax);
    reach = fabsf(bmin.x);
    if (reach < bmax.x)
        reach = bmax.x;
    reach = reach + BUMPER_CAR_ROOM;
    if (dist < reach)
        eye.z = geo->z + sqrtf(reach * reach - (d.x * d.x + d.y * d.y));
    camera_look_at_offset(mat, &eye, geo, &off);
    topology_destroy(&tc);
}

// The eye and the look point are in the car's frame, as the records have
// them. The road noise's fourth lane is the stack's in the image, never
// written; the port's is 0.
void bumper_camera_mover_update(BumperCameraMover *m, float dt,
                                float elapsed)
{
    CameraDataItems *cd = &m->CD;
    struct Car *car = m->CarToFollow;
    Camera *cam;
    bVector3 eye, noise, look, bank, up, fov, d;
    bVector2 at;
    bMatrix4 toCar, body, world, look_at, mat;
    float pct, area, span, elev, dist, focal;
    uint16_t fovBam;

    if (is_game_flow_paused())
        return;

    // The area's share has a floor and no ceiling.
    pct = track_percent(car);
    area = (pct - cd->MinAreaPercent)
           / (cd->MaxAreaPercent - cd->MinAreaPercent);
    if (area < 0.0f)
        area = 0.0f;
    m->EyeSplineParam = step_param(m->EyeSplineParam, cd->LockEyeSpeedToCar,
                                   cd->EyeSplineSpeed, cd->NumEyeVerts, area,
                                   dt);
    m->LookSplineParam = step_param(m->LookSplineParam,
                                    cd->LockLookSpeedToCar,
                                    cd->LookSplineSpeed, cd->NumLookVerts,
                                    area, dt);

    // The world into the car's frame: off its GeometryPosition, then turned
    // by its BodyMatrix's transpose.
    eIdentity(&toCar);
    toCar.v3.x = -car->State.GeometryPosition.x;
    toCar.v3.y = -car->State.GeometryPosition.y;
    toCar.v3.z = -car->State.GeometryPosition.z;
    eTransposeMatrix(&body, &car->State.BodyMatrix);
    eMulMatrix(&world, &toCar, &body);

    // The eye, shaken by the road under the car and held over the ground.
    spline_get_point(&m->EyeSpline, &eye, m->EyeSplineParam);
    at.x = car->State.Position.x;
    at.y = car->State.Position.y;
    noise.x = track_get_road_noise(&at, TERRAIN_TYPE_DIRT)
              * BUMPER_NOISE_SCALE;
    at.y = at.y - 1.0f;
    noise.y = track_get_road_noise(&at, TERRAIN_TYPE_DIRT)
              * BUMPER_NOISE_SCALE;
    at.y = at.y + 2.0f;
    noise.z = track_get_road_noise(&at, TERRAIN_TYPE_DIRT)
              * BUMPER_NOISE_SCALE;
    noise.pad = 0.0f;
    v_add(&eye, &eye, &noise);
    elev = topology_get_elevation(&m->TheTopologyCoordinate, &eye, NULL, NULL,
                                  NULL) + BUMPER_EYE_LIFT;
    if (eye.z < elev)
        eye.z = elev;

    spline_get_point(&m->LookSpline, &look, m->LookSplineParam);
    spline_get_point(&m->BankSpline, &bank, m->EyeSplineParam);
    camera_mover_compute_banked_up_vector(&m->base, &up, &eye, &look,
                                          (uint16_t)ee_trunc_w(bank.x));
    eCreateLookAtMatrix(&look_at, &eye, &look, &up);
    eMulMatrix(&mat, &world, &look_at);

    span = (pct - cd->MinPercent) / (cd->MaxPercent - cd->MinPercent);
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
        fovBam = (uint16_t)ee_trunc_w(fov.x * BUMPER_DEG_TO_BAM);
    }
    cam = m->base.pCamera;
    if (!CameraStopUpdating)
        cam->CurrentKey.FieldOfView = fovBam;

    v_sub(&d, &eye, &look);
    dist = sqrtf(v_dot(&d, &d));
    // max.s, against 2.
    focal = dist < 2.0f ? 2.0f : dist;
    if (!CameraStopUpdating)
        cam->CurrentKey.TargetDistance = dist;
    if (!CameraStopUpdating)
        cam->CurrentKey.FocalDistance = focal;
    if (!CameraStopUpdating)
        cam->CurrentKey.DepthOfField = BUMPER_DOF;

    if (race_get_race_stage(pCurrentRace) == RACE_STAGE_RACING)
        bumper_keep_off_walls(m, &mat, car);
    camera_set_matrix(cam, &mat, elapsed);
}
