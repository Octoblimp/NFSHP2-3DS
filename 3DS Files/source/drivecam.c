// drivecam -- DriveCameraMover, the small members. See drivecam.h.
#include "drivecam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "camera.h"
#include "car.h"
#include "cartypeinfo.h"
#include "player.h"

// ---------------------------------------------------------------- the vtable

static void drive_cam_destroy_thunk(CameraMover *m) { drive_cam_destroy(m); }

// Retail's 0x002b1dd0. Render, the joystick pair, Enable and Disable are the
// base's. Update is the base's too until 7b ports retail's (0x0015c880).
const CameraMoverVtbl DriveCameraMoverVtbl = {
    drive_cam_destroy_thunk,
    camera_mover_nothing,       // Update, 7b's
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
    d->LastCarSpeed = car->State.VelocityMagnitude;
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
    d->LastCarSpeed = car->State.VelocityMagnitude;
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
