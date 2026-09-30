// drivecam -- DriveCameraMover. See drivecam.h.
#include "drivecam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "camera.h"
#include "car.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "shake.h"
#include "terraintype.h"
#include "track.h"
#include "world.h"

// ---------------------------------------------------------------- the tuning

int32_t  DriveUseTweakables   = 0;       // gp-21760, 0x003303f0
float    DriveLag             = 7.3f;    // gp-21756
float    DriveHeight          = 2.3f;    // gp-21752
float    DriveLatOffset       = 0.0f;    // gp-21748
uint16_t DriveAngle           = 0;       // gp-21744
uint16_t DriveMaxAngle        = 2000;    // gp-21742

float CamGlobalMultiplier  = 1.0f;       // gp-21636, 0x0033046c
float CamAdjustment        = 0.03f;      // gp-21632
float CamBackAdjust        = 0.012f;     // gp-21628
float CamHoldTimeout       = 2.0f;       // gp-21624
float CamYawAdjuster       = 6.0f;       // gp-21608
float CamAccelScaleRatio   = 0.6f;       // gp-21604
float CamDecelScaleRatio   = 0.045f;     // gp-21600
float CamRangeCheckA       = 0.7f;       // gp-21596
float CamRangeCheckD       = -0.3f;      // gp-21592
float CamLagMultiplier     = 1.0f;       // gp-21588
float CamSpeedAdjust       = 500.0f;     // gp-21580
float CamHeightMultiplierD = 0.2f;       // gp-21564
float CamAccelCap          = 6.0f;       // gp-21560
float CamDecelCap          = -1.0f;      // gp-21556
float CamDisableAdjust     = 0.4f;       // gp-21552
float CamBackAdjustQuicker = 3.0f;       // gp-21548
float RoadNoiseAmplitude   = 250.0f;     // gp-21536

// ---------------------------------------------------------------- the vtable

static void drive_cam_destroy_thunk(CameraMover *m) { drive_cam_destroy(m); }

// Retail's 0x002b1dd0. Render, the joystick pair, Enable and Disable are the
// base's.
const CameraMoverVtbl DriveCameraMoverVtbl = {
    drive_cam_destroy_thunk,
    drive_cam_update,
    camera_mover_render,
    camera_mover_nothing,       // AddJoyHandlers
    camera_mover_nothing,       // RemoveJoyHandlers
    drive_cam_get_camera_info,
    drive_cam_get_pov,
    drive_cam_is_exterior_view,
    drive_cam_is_looking_back,
    drive_cam_get_wall_gap,
    drive_cam_reset_state,
    camera_mover_enable,
    camera_mover_disable,
    drive_cam_get_car_to_follow,
    drive_cam_get_target,
};

// ------------------------------------------------------ the constructor

void drive_cam_init(DriveCameraMover *d, int viewID, struct Car *car,
                    int povIndex, float lookbackSpeed, int disableLag,
                    int lookBack, int perfectFocus)
{
    Camera *cam;
    const CameraInfo *info;
    int i;

    camera_mover_init(&d->base, viewID, CM_DRIVE);
    d->LookBackAngle = 0;
    d->DesiredLookBackParam = 0.0f;
    d->LookBackParam = 0.0f;
    d->iLookBackHeight = 0.0f;
    d->CarToFollow = car;
    d->iLookBackParam = 0;
    d->LastBoomYaw = 0;
    d->base.vtbl = &DriveCameraMoverVtbl;
    d->LastCarYaw = car->State.Angle;
    d->LastCarPitch = (uint16_t)bASin(car->State.BodyMatrix.v0.z);
    d->LastBoomPitch = 0;
    topology_init(&d->TheTopologyCoordinate);
    d->DisableLag = disableLag;
    d->LookbackSpeed = lookbackSpeed;
    d->PerfectFocus = perfectFocus;
    d->DesiredLookBackParam = lookBack ? 1.0f : 0.0f;
    d->DesiredAccelLag = 0.0f;
    d->CurrentAccelLag = 0.0f;
    d->CamCurrentAccel = 0.0f;
    d->CamHoldLagTime = 0.0f;
    d->CamLagAdjust = 0.0f;
    cam = d->base.pCamera;
    for (i = 19; i >= 0; i--)
        d->CamLastAccel[i] = 0.0f;
    d->CamTimeFract = 0.0f;
    d->CamAdjustMultiplier = 1.0f;
    d->LastCarSpeed = car->State.ForwardSpeed;
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->RenderDash = 0;
    }
    drive_cam_set_pov_index(d, povIndex);
    info = &d->CarToFollow->pCarTypeInfo->Camera;
    d->pCameraInfo = info;
    if (info->NumFullScreenPOVs == 0 || info->NumSplitScreenPOVs == 0)
        d->pCameraInfo = &CarTypeInfoArray[0].Camera;
    d->TouchingGroundFactor = 1.0f;
}

// 0x0015c400. The image reads the camera before it tests the flag, as here.
void drive_cam_destroy(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    Camera *cam = m->pCamera;

    m->vtbl = &DriveCameraMoverVtbl;
    if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
        cam->CurrentKey.FocalDistance = 0.0f;
        cam->CurrentKey.DepthOfField = 0.0f;
    }
    topology_destroy(&d->TheTopologyCoordinate);
    camera_mover_destroy(m);
}

void drive_cam_reset_state(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    struct Car *car;
    int i;

    d->LookBackAngle = 0;
    car = d->CarToFollow;
    d->DesiredLookBackParam = 0.0f;
    d->LookBackParam = 0.0f;
    d->iLookBackHeight = 0.0f;
    d->LastCarYaw = car->State.Angle;
    d->iLookBackParam = 0;
    d->LastBoomYaw = 0;
    d->LastCarPitch = (uint16_t)bASin(car->State.BodyMatrix.v0.z);
    car = d->CarToFollow;
    d->LastBoomPitch = 0;
    d->DesiredAccelLag = 0.0f;
    d->CurrentAccelLag = 0.0f;
    d->CamCurrentAccel = 0.0f;
    d->CamHoldLagTime = 0.0f;
    d->CamLagAdjust = 0.0f;
    for (i = 19; i >= 0; i--)
        d->CamLastAccel[i] = 0.0f;
    d->CamTimeFract = 0.0f;
    d->CamAdjustMultiplier = 1.0f;
    d->TouchingGroundFactor = 1.0f;
    d->LastCarSpeed = car->State.ForwardSpeed;
}

// ------------------------------------------------------ the points of view

void drive_cam_set_pov_index(DriveCameraMover *d, int index)
{
    d->POVIndex = index;
}

const POV *drive_cam_get_pov(CameraMover *m, int index)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    const CameraInfo *info;

    if (eGetCurrentViewMode() == 3) {
        info = d->pCameraInfo;
        if (index < info->NumSplitScreenPOVs)
            return &info->SplitScreenPOVArray[index];
        return NULL;
    }
    info = d->pCameraInfo;
    if (index < info->NumFullScreenPOVs)
        return &info->FullScreenPOVArray[index];
    return NULL;
}

const CameraInfo *drive_cam_get_camera_info(CameraMover *m)
{
    return ((DriveCameraMover *)m)->pCameraInfo;
}

void *drive_cam_get_car_to_follow(CameraMover *m)
{
    return ((DriveCameraMover *)m)->CarToFollow;
}

const bVector3 *drive_cam_get_target(CameraMover *m)
{
    struct Car *car = ((DriveCameraMover *)m)->CarToFollow;

    if (car != NULL)
        return &car->State.GeometryPosition;
    return &m->pCamera->CurrentKey.Target;
}

// ------------------------------------------------------ the look back

// Whether the mover's player lets a look back count: it has one, and its
// Lookback setting is 0. The three virtuals below each test this first.
static int lookback_counts(const CameraMover *m)
{
    const struct Player *p = (const struct Player *)m->pPlayer;

    return p != NULL && p->PlayerSettings.Lookback == 0;
}

// GetPOV goes first, through the vtable, as the image's does.
int drive_cam_is_exterior_view(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    const POV *pov = m->vtbl->GetPOV(m, d->POVIndex);
    int counts = lookback_counts(m);

    if (pov == NULL || pov->Type == POV_OUTSIDE)
        return 1;
    return counts && 0.0f < d->LookBackParam;
}

int drive_cam_is_looking_back(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;

    return lookback_counts(m) && 0.0f < d->LookBackParam;
}

float drive_cam_get_wall_gap(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    float p = 0.0f;

    if (lookback_counts(m))
        p = d->LookBackParam;
    return (1.0f - p) * 0.7f + p * 3.0f;
}

// ------------------------------------------------------ the corrections

float drive_cam_get_correction_yaw(uint16_t a)
{
    int32_t s = (int16_t)a;
    int32_t mag = s < 0 ? -s : s;
    float r = (float)bATan(1.0f, (float)mag * 0.000261f) * -1.9088f;

    return s < 0 ? -r : r;
}

// The image reads an angle past 0x8000 as negative, so 0x8000 itself stays
// +32768, which (int16_t) would not give.
static int32_t signed_angle(uint16_t a)
{
    return a > 0x8000 ? (int32_t)a - 65536 : (int32_t)a;
}

int32_t drive_cam_get_correction_pitch(uint16_t a)
{
    int32_t s = signed_angle(a);

    if (s >= -7 && s <= 7)
        return -s;
    return -s / 8;
}

int32_t drive_cam_get_in_car_correction_angle(uint16_t a)
{
    int32_t s = signed_angle(a);

    if (s >= -1 && s <= 1)
        return -s;
    return -s / 2;
}

// Each sum is VU0's, (x + y) + z. The image carries the fourth lane through
// the difference and the scaling, and nothing reads it.
uint16_t calculate_lookback_angle(const struct Car *from,
                                  const struct Car *to, const bMatrix4 *m)
{
    bVector3 d;
    float inv, fwd, side;

    d.x = to->State.Position.x - from->State.Position.x;
    d.y = to->State.Position.y - from->State.Position.y;
    d.z = to->State.Position.z - from->State.Position.z;
    inv = 1.0f / sqrtf((d.x * d.x + d.y * d.y) + d.z * d.z);
    d.x *= inv;
    d.y *= inv;
    d.z *= inv;
    fwd = (m->v0.x * d.x + m->v0.y * d.y) + m->v0.z * d.z;
    side = (m->v1.x * d.x + m->v1.y * d.y) + m->v1.z * d.z;
    if (0.7071f < fwd)
        return 0;
    if (fwd < -0.7071f)
        return 0x8000;
    if (side < 0.0f)
        return 0x4000;
    return 0xc000;
}

// ------------------------------------------------------ the update

struct Car *get_lookback_car(struct Car *car, int32_t *isCop)
{
    struct Car *r = NULL;
    tCop *cop;

    *isCop = 0;
    if (pCopManager == NULL)
        return NULL;
    cop = gCopManagerGetCopByCarFn != NULL
        ? gCopManagerGetCopByCarFn(pCopManager, car) : NULL;
    if (cop != NULL) {
        if (cop->pMyPursuit != NULL) {
            r = cop->pMyPursuit->pChasedCar;
            *isCop = 1;
        }
    } else {
        cop = gCopManagerGetCopByChaseFn != NULL
            ? gCopManagerGetCopByChaseFn(pCopManager, car) : NULL;
        if (cop != NULL)
            r = cop->pMyCar;
    }
    return r;
}

// Every sum here is a VU0 add on four lanes. The fourth lane of the push is
// the stack's until the first average, and nothing reads it but the probe's,
// which PointInShaft does not; the port starts it at 0.
void camera_wall_offset(CameraMover *m, TopologyCoordinate *tc,
                        const bVector3 *from, const bVector3 *eye,
                        bVector3 *out)
{
    bVector3 c = *eye, push, probe, acc;
    int iter, i, n;

    topology_constrain(tc, TOPOLOGY_CONSTRAIN_BY_SCALE, 1, from, &c, 0.01f,
                       1.0f);
    push.x = c.x - eye->x;
    push.y = c.y - eye->y;
    push.z = c.z - eye->z;
    push.pad = c.pad - eye->pad;
    for (iter = 0; iter < 3; iter++) {
        probe.x = eye->x + push.x;
        probe.y = eye->y + push.y;
        probe.z = eye->z + push.z;
        probe.pad = eye->pad + push.pad;
        acc.x = 0.0f;
        acc.y = 0.0f;
        acc.z = 0.0f;
        acc.pad = 0.0f;
        n = 0;
        for (i = 0; i < tc->TotalNumTrackPolygons; i++) {
            const TrackPolygon *tp = tc->TrackPolygonTable[i];
            float dist, gap, k;

            if (TerrainTypeInfoTable[tp->TheTerrainType]
                    .ShouldCameraGoThroughIt)
                continue;
            if (!trackpolygon_point_in_shaft(tp, &probe, &dist))
                continue;
            if (tp->Flags & 2)
                gap = m->vtbl->GetWallGap(m);
            else
                gap = 0.7f;
            if (!(0.0f <= dist) || !(dist < gap))
                continue;
            k = gap - dist;
            acc.x = tp->Normal.x * k + acc.x;
            acc.y = tp->Normal.y * k + acc.y;
            acc.z = tp->Normal.z * k + acc.z;
            acc.pad = tp->PlaneDistance * k + acc.pad;
            n++;
        }
        if (n == 0)
            break;
        {
            float inv = 1.0f / (float)n;

            push.x = acc.x * inv + push.x;
            push.y = acc.y * inv + push.y;
            push.z = acc.z * inv + push.z;
            push.pad = acc.pad * inv + push.pad;
        }
    }
    *out = push;
    out->pad = 0.0f;
}

void camera_look_at_offset(bMatrix4 *out, const bVector3 *eye,
                           const bVector3 *target, const bVector2 *off)
{
    bVector3 up, t, t2;
    bMatrix4 l, li;

    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    eCreateLookAtMatrix(&l, eye, target, &up);
    eInvertTransformationMatrix(&li, &l);
    eMulVector3(&t, &l, target);
    t.y = t.y - t.z * off->y;
    t.x = t.x - t.z * off->x;
    eMulVector3(&t2, &li, &t);
    eCreateLookAtMatrix(out, eye, &t2, &up);
}

// The car the camera follows: CarToFollow, unless CameraFollowDefaultCar
// is cleared, and then the car with CameraFollowThisCarInstead's driver
// number, counting that down past each number with no car. The image
// calls bRefreshTweaker (0x0025d2c8) after each step down, to redraw the
// debug menu the two live in; the port has no menu.
static struct Car *car_to_follow(DriveCameraMover *d)
{
    struct Car *car;

    if (CameraFollowDefaultCar != 0)
        return d->CarToFollow;
    car = world_get_car_by_driver_number(CameraFollowThisCarInstead);
    if (car != NULL)
        return car;
    while (CameraFollowThisCarInstead >= 0) {
        CameraFollowThisCarInstead--;
        car = world_get_car_by_driver_number(CameraFollowThisCarInstead);
        if (car != NULL)
            return car;
    }
    return d->CarToFollow;
}

// The lag: the car's forward acceleration, in car space, sampled sixty
// times a second into CamLastAccel. A spring of ten samples past a
// threshold, and ten before it not, sets CamLagAdjust, and
// CamCurrentAccel chases it. Returns the boom length it adds.
static float accel_lag(DriveCameraMover *d, struct Car *car, float dt)
{
    bMatrix4 t;
    bVector3 a;
    float gm, sample, sum, f, lag, cur, diff, k;
    int32_t sign, ok, n, frame, i;

    CamGlobalMultiplier = 1.0f;
    a = car->State.Acceleration;
    eTransposeMatrix(&t, &car->State.BodyMatrix);
    eMulVector3(&a, &t, &a);
    gm = CamGlobalMultiplier;
    if ((a.x * CamDecelScaleRatio) * gm < CamRangeCheckD * gm) {
        sign = -1;
        sample = a.x * (CamDecelScaleRatio * gm);
    } else if (CamRangeCheckA * gm < (a.x * CamAccelScaleRatio) * gm) {
        sign = 1;
        sample = a.x * (CamAccelScaleRatio * gm);
    } else {
        sample = 0.0f;
        sign = 0;
    }

    f = dt * 60.0f + d->CamTimeFract;
    n = (int32_t)f;
    d->CamTimeFract = f - (float)n;
    for (frame = 0; frame < n; frame++) {
        for (i = 19; i > 0; i--)
            d->CamLastAccel[i] = d->CamLastAccel[i - 1];
        d->CamLastAccel[0] = sample;
        sum = 0.0f;
        ok = 0;
        if (sign == 1) {
            if (!(0.0f < d->CamCurrentAccel)) {
                float lim = CamRangeCheckA * gm;

                sum = sample;
                ok = 1;
                for (i = 1; i < 10; i++) {
                    sum = sum + d->CamLastAccel[i];
                    if (d->CamLastAccel[i] < lim)
                        ok = 0;
                }
                if (ok)
                    for (i = 10; i < 20; i++)
                        if (lim < d->CamLastAccel[i])
                            ok = 0;
            }
        } else if (sign == -1) {
            if (!(d->CamCurrentAccel < 0.0f)) {
                float lim = CamRangeCheckD * gm;

                sum = sample;
                ok = -1;
                for (i = 1; i < 10; i++) {
                    sum = sum + d->CamLastAccel[i];
                    if (lim < d->CamLastAccel[i])
                        ok = 0;
                }
                if (ok)
                    for (i = 10; i < 20; i++)
                        if (d->CamLastAccel[i] < lim)
                            ok = 0;
            }
        } else {
            for (i = 1; i < 10; i++)
                if (d->CamLastAccel[i] < CamRangeCheckA * gm
                    && CamRangeCheckD * gm < d->CamLastAccel[i])
                    d->CamLagAdjust = 0.0f;
        }
        if (!ok)
            continue;
        d->CamLagAdjust = sum * 0.1f;
        k = carstate_get_yaw(&car->State);
        if (k < 0.0f)
            k = -k;
        k = 1.0f - k * CamYawAdjuster;
        if (k < 0.0f)
            k = 0.0f;
        d->CamLagAdjust = d->CamLagAdjust * k;
        if (CamAccelCap * gm < d->CamLagAdjust)
            d->CamLagAdjust = CamAccelCap * gm;
        if (d->CamLagAdjust < CamDecelCap * gm)
            d->CamLagAdjust = CamDecelCap * gm;
        d->CamHoldLagTime = 0.0f;
        if (d->DisableLag != 0 && 5.0f < car->State.ForwardSpeed) {
            if (car->State.DriverMode == 1)
                d->CamLagAdjust = d->CamLagAdjust * 0.75f;
            d->CamAdjustMultiplier = CamDisableAdjust;
            d->CamLagAdjust = d->CamLagAdjust * CamDisableAdjust;
        } else {
            d->CamAdjustMultiplier = 1.0f;
        }
    }

    // CamCurrentAccel toward CamLagAdjust, or back to 0 when that is 0. A
    // lag held past CamHoldTimeout, or once the samples stop, lets go.
    lag = d->CamLagAdjust;
    f = dt * 60.0f;
    if (lag == 0.0f) {
        float step = (CamBackAdjust * f) * d->CamAdjustMultiplier;

        cur = d->CamCurrentAccel;
        if (CamBackAdjustQuicker < cur)
            d->CamCurrentAccel = cur - (step + step);
        else if (0.0f < cur)
            d->CamCurrentAccel = step < cur ? cur - step : 0.0f;
        else if (cur < 0.0f)
            d->CamCurrentAccel = cur < -step ? cur + step : 0.0f;
    } else if (0.0f < lag) {
        cur = d->CamCurrentAccel;
        diff = cur - lag;
        if (0.0f < diff)
            goto hold;
        if (-0.4f < diff)
            d->CamCurrentAccel =
                cur + ((CamAdjustment * d->CamAdjustMultiplier) * f) * 0.3f;
        else if (-1.0f < diff)
            d->CamCurrentAccel =
                cur + ((CamAdjustment * d->CamAdjustMultiplier) * f) * 0.6f;
        else
            d->CamCurrentAccel =
                cur + (CamAdjustment * d->CamAdjustMultiplier) * f;
    } else if (car->State.ForwardSpeed * 2.237f < 5.0f) {
        d->CamLagAdjust = 0.0f;
    } else {
        cur = d->CamCurrentAccel;
        if (cur < lag)
            goto hold;
        d->CamCurrentAccel =
            cur + (-CamAdjustment * d->CamAdjustMultiplier) * f;
    }
    goto slowed;
hold:
    d->CamHoldLagTime = d->CamHoldLagTime + dt;
    if (CamHoldTimeout < d->CamHoldLagTime || sign == 0)
        d->CamLagAdjust = 0.0f;
slowed:
    // Less of it the faster the car goes, none past CamSpeedAdjust mph.
    k = CamSpeedAdjust - car->State.ForwardSpeed * 2.237f;
    if (k < 0.0f)
        k = 0.0f;
    k = k / CamSpeedAdjust;
    if (d->DisableLag != 0)
        return 0.0f;
    return (d->CamCurrentAccel * CamLagMultiplier) * k;
}

void drive_cam_update(CameraMover *m)
{
    DriveCameraMover *d = (DriveCameraMover *)m;
    Camera *cam;
    struct Car *car, *lbCar = NULL;
    const POV *pov;
    bMatrix4 toCar, base, body, boom, e, f;
    bVector3 v, eye;
    bVector2 offs;
    float dt = WorldTimeElapsed;
    float rate, boomLag, round, lag, height, lat, lagx, raise;
    uint16_t angle, maxAngle;
    int32_t canLB, isCop, outside, yaw = 0;

    canLB = lookback_counts(m);
    car = car_to_follow(d);

    // The look back comes round at LookbackSpeed, or 4/3 a second for a cop
    // turning to the car it chases.
    rate = d->LookbackSpeed;
    if (pCopManager != NULL && d->DesiredLookBackParam == 1.0f && !canLB) {
        lbCar = get_lookback_car(car, &isCop);
        if (isCop)
            rate = 1.3333334f;
    } else {
        d->iLookBackParam = 0;
        d->iLookBackHeight = 0.0f;
    }
    if (d->LookBackParam < d->DesiredLookBackParam) {
        d->LookBackParam = d->LookBackParam + rate * dt;
        if (d->DesiredLookBackParam < d->LookBackParam)
            d->LookBackParam = d->DesiredLookBackParam;
    } else if (d->DesiredLookBackParam < d->LookBackParam) {
        d->LookBackParam = d->LookBackParam - rate * dt;
        if (d->LookBackParam < d->DesiredLookBackParam)
            d->LookBackParam = d->DesiredLookBackParam;
    }

    pov = m->vtbl->GetPOV(m, d->POVIndex);
    if (pov == NULL) {
        drive_cam_set_pov_index(d, 0);
        pov = m->vtbl->GetPOV(m, d->POVIndex);
    }

    boomLag = accel_lag(d, car, dt);
    round = 1.0f
        - (bCosBam((uint16_t)(int32_t)(d->LookBackParam * 32768.0f)) + 1.0f)
        * 0.5f;
    if (DriveUseTweakables) {
        lag = DriveLag;
        if (pov->Type == POV_OUTSIDE)
            lag = DriveLag + boomLag;
        angle = DriveAngle;
        maxAngle = DriveMaxAngle;
        height = DriveHeight;
        lat = DriveLatOffset;
    } else {
        if (pov->Type == POV_OUTSIDE)
            lag = pov->Lag + boomLag * (1.0f - round);
        else
            lag = pov->Lag;
        angle = pov->Angle;
        height = pov->Height;
        lat = pov->LatOffset;
        maxAngle = pov->MaxAngle;
    }
    if (pov->Type == POV_OUTSIDE && boomLag < 0.0f)
        height = height + boomLag * CamHeightMultiplierD;

    // base: world to the car's frame, turned to its heading (outside) or
    // to its whole body (inside).
    eIdentity(&toCar);
    toCar.v3.x = -car->State.GeometryPosition.x;
    d->LookBackAngle = (uint16_t)(int32_t)(round * 32768.0f);
    toCar.v3.y = -car->State.GeometryPosition.y;
    toCar.v3.z = -car->State.GeometryPosition.z;
    body = car->State.BodyMatrix;
    if (pov->Type != POV_OUTSIDE) {
        eTransposeMatrix(&boom, &body);
        if (lbCar != NULL)
            d->LookBackAngle = calculate_lookback_angle(car, lbCar, &body);
        if (!canLB)
            eRotateZ(&boom, &boom, d->LookBackAngle);
        eMulMatrix(&base, &toCar, &boom);
    } else {
        // The heading is the nose, swung toward the way the car moves as
        // it passes 8.32 m/s, all the way by 13 m/s. Moving backwards
        // counts forwards. The quirk: bNormalize2To makes a zero velocity
        // (1, 0), so a car at rest swings toward +x by the nose's own
        // length.
        bVector2 vel, dir;
        float dot, w;

        vel.x = car->State.Velocity.x;
        vel.y = car->State.Velocity.y;
        dot = vel.x * body.v0.x + vel.y * body.v0.y;
        if (dot < 0.0f) {
            float s = dot * -2.0f;

            vel.y = vel.y + body.v0.y * s;
            vel.x = vel.x + body.v0.x * s;
        }
        w = (sqrtf(vel.x * vel.x + vel.y * vel.y) - 8.32f) * 0.21276592f;
        if (w < 0.0f)
            w = 0.0f;
        if (1.0f < w)
            w = 1.0f;
        bNormalize2To(&vel, &vel, w);
        dir.y = body.v0.y * (1.0f - w) + vel.y;
        dir.x = body.v0.x * (1.0f - w) + vel.x;
        yaw = bATan(dir.x, dir.y);
        eRotateZ(&base, &toCar, (uint16_t)-yaw);
        if (lbCar != NULL && !canLB) {
            // Round to the chased car, straight back while it is within
            // 45 degrees of the nose, and up over the roof.
            float dx = lbCar->State.Position.x - car->State.Position.x;
            float dy = lbCar->State.Position.y - car->State.Position.y;
            float dist = sqrtf(dx * dx + dy * dy);
            int32_t want = (uint16_t)(yaw - bATan(dx, dy));
            int32_t cur;
            float add = eGetCurrentViewMode() == 3 ? 0.0f : 0.4f;
            float top = car->pCarTypeInfo->Body.Zdim - height;

            if ((uint32_t)(want - 8192) > 0xbfffu) {
                want = 0;
                top = top + add * 0.75f;
            } else {
                top = top + add;
            }
            cur = d->iLookBackParam;
            if (cur < want - 32768)
                want -= 65536;
            if (want + 32768 < cur)
                want += 65536;
            if (cur < want) {
                if (cur + 10000 < want || (50.0f < dist && (want & 0xffff)))
                    d->iLookBackParam =
                        cur + (int32_t)(rate * (dt * 60000.0f));
                else
                    d->iLookBackParam =
                        cur + (int32_t)(rate * (dt * 20000.0f));
                if (want < d->iLookBackParam)
                    d->iLookBackParam = want;
            } else if (want < cur) {
                if (want < cur - 10000 || (50.0f < dist && (want & 0xffff)))
                    d->iLookBackParam =
                        cur - (int32_t)(rate * (dt * 60000.0f));
                else
                    d->iLookBackParam =
                        cur - (int32_t)(rate * (dt * 20000.0f));
                if (d->iLookBackParam < want)
                    d->iLookBackParam = want;
            }
            d->iLookBackParam &= 0xffff;
            if (d->iLookBackHeight < top) {
                d->iLookBackHeight = d->iLookBackHeight + rate * dt;
                if (top < d->iLookBackHeight)
                    d->iLookBackHeight = top;
            } else if (top < d->iLookBackHeight) {
                d->iLookBackHeight = d->iLookBackHeight - rate * dt;
                if (d->iLookBackHeight < top)
                    d->iLookBackHeight = top;
            }
            d->LookBackAngle = (uint16_t)d->iLookBackParam;
        }
    }

    // boom: from the car's frame out to the eye.
    eIdentity(&boom);
    outside = pov->Type == POV_OUTSIDE || (canLB && 0.0f < d->LookBackParam);
    if (pov->Type == POV_OUTSIDE) {
        // The boom's yaw trails the heading, and its pitch the body's,
        // each by a correction a frame; off the ground the yaw's fades.
        uint16_t turn = (uint16_t)(yaw - (uint16_t)d->LastCarYaw);
        uint16_t boomYaw, p;
        int32_t s;
        float air = car->State.nWheelsTouchingGround < 3 ? -1.0f : 1.0f;
        float tg = d->TouchingGroundFactor + air * 0.24316f;

        d->TouchingGroundFactor = tg;
        if (1.0f < tg)
            d->TouchingGroundFactor = 1.0f;
        else if (tg < 0.0f)
            d->TouchingGroundFactor = 0.0f;
        tg = drive_cam_get_correction_yaw(
            (uint16_t)(turn + (uint16_t)d->LastBoomYaw));
        boomYaw = (uint16_t)(turn + (uint16_t)d->LastBoomYaw
                             + (int32_t)((d->TouchingGroundFactor * tg)
                                         * dt));
        eRotateZ(&boom, &boom, boomYaw);
        d->LastBoomYaw = boomYaw;
        d->LastCarYaw = yaw;
        p = (uint16_t)bASin(car->State.BodyMatrix.v0.z);
        if (d->LookBackAngle != 0)
            s = (uint16_t)d->LastBoomPitch - p;
        else if (d->TouchingGroundFactor == 0.0f)
            s = (uint16_t)d->LastBoomPitch
                - (p <= 32767 ? p - p / 9 : p + (0xffff - p) / 3);
        else
            s = (uint16_t)d->LastBoomPitch
                - (p <= 32767 ? p + p / 9 : p - (0xffff - p) / 3);
        s &= 0xffff;
        if (air != 0.0f)
            s = (uint16_t)d->LastBoomPitch
                + (int32_t)(((float)drive_cam_get_correction_pitch(
                                 (uint16_t)s) * dt) * 25.0f);
        else
            s = (uint16_t)d->LastBoomPitch;
        s &= 0xffff;
        {
            bVector2 at;

            at.x = car->State.Position.x;
            at.y = car->State.Position.y;
            eRotateY(&boom, &boom,
                     (uint16_t)(int32_t)((float)s + RoadNoiseAmplitude
                                         * track_get_road_noise(
                                             &at, TERRAIN_TYPE_DIRT)));
        }
        if (!canLB)
            eRotateZ(&boom, &boom, d->LookBackAngle);
        d->LastCarPitch = p;
        d->LastBoomPitch = s;
    } else {
        d->LastBoomYaw = 0;
        d->LastCarYaw = car->State.Angle;
        d->LastCarPitch = (uint16_t)bASin(car->State.BodyMatrix.v0.z);
        d->LastBoomPitch = 0;
    }

    // A look back the player's setting counts swings the boom round
    // behind, longer and lower (higher split-screen).
    raise = 0.0f;
    lagx = lag;
    if (canLB && 0.0f < d->LookBackParam) {
        float p = d->LookBackParam, t = 1.0f - p;
        int vm3 = eGetCurrentViewMode() == 3;

        height = vm3 ? t * height - p : t * height + p * -3.0f;
        lagx = t * lag + p * (vm3 ? 16.0f : 18.0f);
        eRotateY(&boom, &boom,
                 (uint16_t)-(int32_t)(t * (float)angle
                                      + p * (vm3 ? 3540.0f : 5200.0f)));
    }

    // Outside, the eye is kept off the walls and out of the car, and the
    // look-at is turned to hold the car where it would have been on screen.
    offs.x = 0.0f;
    offs.y = 0.0f;
    eye.x = 0.0f;
    eye.y = 0.0f;
    eye.z = 0.0f;
    eye.pad = 0.0f;
    if (outside) {
        bVector3 mid, pc, wall, dv, bmin, bmax;
        bVector4 o;
        float r;

        if (lbCar != NULL && !canLB) {
            height = height + d->iLookBackHeight;
            lagx = 2.24f;
        }
        v.x = lagx;
        v.y = lat;
        v.z = -height;
        v.pad = 0.0f;
        eTranslate(&e, &boom, &v);
        eMulMatrix(&e, &base, &e);
        eInvertTransformationMatrix(&f, &e);
        mid.x = (f.v3.x + car->State.Position.x) * 0.5f;
        mid.y = (f.v3.y + car->State.Position.y) * 0.5f;
        mid.z = (f.v3.z + car->State.Position.z) * 0.5f;
        mid.pad = (f.v3.w + car->State.Position.pad) * 0.5f;
        dv.x = car->State.Position.x - f.v3.x;
        dv.y = car->State.Position.y - f.v3.y;
        dv.z = car->State.Position.z - f.v3.z;
        r = sqrtf((dv.x * dv.x + dv.y * dv.y) + dv.z * dv.z) * 0.5f + 1.0f;
        topology_set_interest_bbox3(&d->TheTopologyCoordinate, &mid, r,
                                    &car->State.Velocity);
        eMulVector3(&pc, &e, &car->State.Position);
        r = 1.0f / pc.x;
        if (r < -1000.0f)
            r = -1000.0f;
        if (1000.0f < r)
            r = 1000.0f;
        r = -r;
        offs.y = r * pc.z;
        offs.x = r * pc.y;
        wall.x = 0.0f;
        wall.y = 0.0f;
        wall.z = 0.0f;
        wall.pad = 0.0f;
        camera_wall_offset(m, &d->TheTopologyCoordinate, &car->State.Position,
                           (const bVector3 *)&f.v3, &wall);
        eye.x = f.v3.x + wall.x;
        eye.y = f.v3.y + wall.y;
        eye.z = f.v3.z + wall.z;
        eye.pad = f.v3.w + wall.pad;
        if (lbCar == NULL) {
            float dist, reach;

            dv.x = car->State.Position.x - eye.x;
            dv.y = car->State.Position.y - eye.y;
            dv.z = car->State.Position.z - eye.z;
            dist = sqrtf((dv.x * dv.x + dv.y * dv.y) + dv.z * dv.z);
            car_get_car_space_bounding_box(car, &bmin, &bmax);
            reach = fabsf(bmin.x);
            if (reach < bmax.x)
                reach = bmax.x;
            reach = reach + 0.7f;
            if (dist < reach) {
                float s = sqrtf(reach * reach
                                - (dv.x * dv.x + dv.y * dv.y));
                float dz = eye.z - car->State.Position.z;

                raise = dz / s;
                eye.z = eye.z + (s - dz);
                wall.z = wall.z + (s - dz);
            }
        }
        eMulVector4(&o, &e, (const bVector4 *)&wall);
        height = height + o.z;
        lat = lat - o.y;
        lagx = lagx - o.x;
    }

    v.x = lagx;
    v.y = lat;
    v.z = -height;
    v.pad = 0.0f;
    eTranslate(&boom, &boom, &v);
    eRotateY(&boom, &boom,
             (uint16_t)-(angle + (int32_t)(raise
                                           * (float)(maxAngle - angle))));
    if (outside) {
        camera_look_at_offset(&f, &eye, &car->State.Position, &offs);
    } else {
        // Inside, the eye only stays 0.7 over the ground.
        float el;
        int lifted = 0;

        eMulMatrix(&e, &base, &boom);
        eInvertTransformationMatrix(&e, &e);
        el = topology_get_elevation(&d->TheTopologyCoordinate,
                                    (const bVector3 *)&e.v3, NULL, NULL,
                                    NULL) + 0.7f;
        if (e.v3.z < el) {
            e.v3.z = el;
            lifted = 1;
        }
        if (lifted)
            eInvertTransformationMatrix(&f, &e);
        else
            eMulMatrix(&f, &base, &boom);
        eRotateX(&f, &f, 16384);
        eRotateY(&f, &f, 0xc000);
    }

    cam = m->pCamera;
    if (!CameraStopUpdating)
        cam->RenderDash = 0;
    if (!outside) {
        if (!CameraStopUpdating)
            cam->CarNotToRender = car;
        if (pov->Type == POV_INCAR && d->DesiredLookBackParam != 1.0f
            && !CameraStopUpdating)
            cam->RenderDash = 1;
    } else if (!CameraStopUpdating) {
        cam->CarNotToRender = NULL;
    }
    // The image works out |ForwardSpeed| for the bumper's and drops it.
    if (pov->Type == POV_INCAR || pov->Type == POV_BUMPER) {
        if (!CameraStopUpdating)
            cam->CurrentKey.FieldOfView = 16384;
    } else if (pov->Type == POV_OUTSIDE) {
        if (!CameraStopUpdating)
            cam->CurrentKey.FieldOfView = 13020;
    }
    cam->CurrentKey.NearZ = pov->Type == POV_INCAR ? 0.4f : 0.5f;
    apply_camera_shake(m->ViewID, &f);
    {
        float dx = cam->CurrentKey.Position.x - car->State.Position.x;
        float dy = cam->CurrentKey.Position.y - car->State.Position.y;
        float dz = cam->CurrentKey.Position.z - car->State.Position.z;
        float dist = sqrtf((dx * dx + dy * dy) + dz * dz);

        if (!CameraStopUpdating)
            cam->CurrentKey.TargetDistance = dist;
    }
    if (!d->PerfectFocus && !CameraStopUpdating) {
        cam->CurrentKey.FocalDistance = 15.0f;
        cam->CurrentKey.DepthOfField = 65.0f;
    }
    camera_set_matrix(cam, &f, RealTimeElapsed);
    if (canLB)
        d->LookBackAngle = 0;
}

// ------------------------------------------------------ the accessors

uint16_t drive_cam_get_lookback_angle(const DriveCameraMover *d)
{
    return d->LookBackAngle;
}

float drive_cam_get_lookback_speed(const DriveCameraMover *d)
{
    return d->LookbackSpeed;
}

void drive_cam_set_lookback_speed(DriveCameraMover *d, float speed)
{
    d->LookbackSpeed = speed;
}

int32_t drive_cam_get_disable_lag(const DriveCameraMover *d)
{
    return d->DisableLag;
}

void drive_cam_set_disable_lag(DriveCameraMover *d, int32_t lag)
{
    d->DisableLag = lag;
}

int drive_cam_looking_back(const DriveCameraMover *d)
{
    return 0.0f < d->DesiredLookBackParam;
}

void drive_cam_set_look_back(DriveCameraMover *d, int on)
{
    d->DesiredLookBackParam = on ? 1.0f : 0.0f;
}

int drive_cam_look_back_full(const DriveCameraMover *d)
{
    return d->DesiredLookBackParam == 1.0f;
}
