// selcam -- SelectCarCameraMover. See selcam.h.
#include "selcam.h"

#include <math.h>
#include <stddef.h>

#include "bmath.h"
#include "camera.h"
#include "carinit.h"
#include "eefpu.h"
#include "emath.h"
#include "realtime.h"

const SelCamSoundFns *gSelCamSound = NULL;
int32_t SelCamNormalizeCount = 0;

// The constants, gp-31184 .. gp-31068.
#define ORBIT_RADIUS      0x1.a66666p+3f  /* 13.2, gp-31184 and gp-31156 */
#define HORIZ_RATE        45000.0f        /* gp-31180, gp-31176 */
#define VERT_RATE         23700.0f        /* gp-31172, gp-31168 */
#define RADIUS_RATE       0x1.1051ecp+4f  /* 17.02, gp-31164, gp-31160 */
#define BOUNCE            0x1.51eb86p-3f  /* 0.165, gp-31152, gp-31140 */
#define TILT_BUMP         0x1.3a92a4p-11f /* 0.0006, gp-31148, gp-31136 */
#define BUMP_MIN          0x1.b645a2p-4f  /* 0.107 */
#define RADIUS_BUMP       0x1.99999ap-1f  /* 0.8, gp-31124, gp-31108 */
#define RADIUS_MAX        15.5f           /* 0x41780000, inline */
#define RADIUS_MIN        0x1.5e6666p+3f  /* 10.95, gp-31116, gp-31088 */
#define VOL_HORIZ         0x1.a36e2ep-14f /* 0.0001, gp-31100 */
#define VOL_VERT          0x1.4f8b58p-13f /* 0.00016, gp-31096 */
#define VOL_RADIUS        0x1.2f1aa0p-3f  /* 0.148, gp-31092 */
#define PITCH_SCALE       0x1.c21c20p-3f  /* 0.21978021, gp-31084 */
#define PITCH_SLOPE       (-0x1.8dd2f0p+0f) /* -1.554, gp-31080 */
#define PITCH_BASE        0x1.c8f5c2p+0f  /* 1.785, gp-31076 */
#define BLEND_STEP        0x1.eb851ep-6f  /* 0.03, gp-31072, gp-31068 */
#define TILT_MAX          0xebab
#define TILT_MIN          0xc34f
#define TILT_RESET        0xc350          /* 50000 */

// Slerp's, gp-29228 .. gp-29220.
#define SLERP_EPS         0x1.99999ap-5f  /* 0.05 */
#define SLERP_PI          0x1.921fb6p+1f
#define SLERP_RAD_TO_BAM  0x1.45f306p+13f /* 10430.378 */

// ------------------------------------------------------------ the sound

static void snd_create(int s)
{
    if (gSelCamSound && gSelCamSound->create) gSelCamSound->create(s);
}

static void snd_destroy(int s)
{
    if (gSelCamSound && gSelCamSound->destroy) gSelCamSound->destroy(s);
}

static void snd_play(int s, float v)
{
    if (gSelCamSound && gSelCamSound->play) gSelCamSound->play(s, v, 0.0f, 0.0f);
}

static void snd_stop(int s)
{
    if (gSelCamSound && gSelCamSound->stop) gSelCamSound->stop(s);
}

// ------------------------------------------------------------ the vtable

static void selcam_destroy_thunk(CameraMover *m)
{
    selcam_destroy((SelectCarCameraMover *)m);
}

static void selcam_update_thunk(CameraMover *m)
{
    selcam_update((SelectCarCameraMover *)m);
}

// GetCarToFollow is the class's own (0x0015fad0), NULL like the base's;
// GetTarget is the base's (0x0015fcb0), the camera's target. cammover.c
// keeps its two to itself.
static void *selcam_get_car_to_follow(CameraMover *m)
{
    (void)m;
    return NULL;
}

static const bVector3 *selcam_get_target(CameraMover *m)
{
    return &m->pCamera->CurrentKey.Target;
}

const CameraMoverVtbl SelectCarCameraMoverVtbl = {
    selcam_destroy_thunk,
    selcam_update_thunk,
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
    selcam_get_car_to_follow,
    selcam_get_target,
};

// ------------------------------------------------- the quaternion helpers

void selcam_quat_multiply(bQuaternion *o, const bQuaternion *a,
                          const bQuaternion *b)
{
    float w = ((a->w * b->w - a->x * b->x) - a->y * b->y) - a->z * b->z;
    float x = ((a->y * b->z - a->z * b->y) + a->w * b->x) + a->x * b->w;
    float y = ((a->z * b->x - a->x * b->z) + a->w * b->y) + a->y * b->w;
    float z = ((a->x * b->y - a->y * b->x) + a->w * b->z) + a->z * b->w;
    o->w = w;
    o->x = x;
    o->y = y;
    o->z = z;
}

void selcam_quat_normalize(bQuaternion *q)
{
    float n = sqrtf(((q->x * q->x + q->y * q->y) + q->z * q->z)
                    + q->w * q->w);
    float w = q->w / n;
    float x = q->x / n;
    float y = q->y / n;
    float z = q->z / n;
    q->w = w;
    q->x = x;
    q->y = y;
    q->z = z;
}

void selcam_slerp(bQuaternion *o, bQuaternion *a, bQuaternion *b, float t)
{
    float c = ((a->w * b->w + a->x * b->x) + a->y * b->y) + a->z * b->z;
    float w0, w1;

    if (c < 0.0f) {
        a->x = -a->x;
        a->y = -a->y;
        a->z = -a->z;
        a->w = -a->w;
        c = -c;
    }
    if (SLERP_EPS < c + 1.0f) {
        if (1.0f - c < SLERP_EPS) {
            w0 = 1.0f - t;
            w1 = t;
        } else {
            uint16_t ang = (uint16_t)(16384 - bASin(c));
            float    angf = (float)(int32_t)ang;
            float    s = bSinBam(ang);
            w0 = bSinBam((uint16_t)ee_trunc_w(angf * (1.0f - t))) / s;
            w1 = bSinBam((uint16_t)ee_trunc_w(angf * t)) / s;
        }
    } else {
        // b at right angles to a, written back.
        float ay = a->y, ax = a->x, aw = a->w, az = a->z;
        b->x = -ay;
        b->y = ax;
        b->z = -aw;
        b->w = az;
        w0 = bSinBam((uint16_t)ee_trunc_w(((0.5f - t) * SLERP_PI)
                                          * SLERP_RAD_TO_BAM));
        w1 = bSinBam((uint16_t)ee_trunc_w((t * SLERP_PI) * SLERP_RAD_TO_BAM));
    }
    // Each lane read back from memory after the one before is stored, as
    // the image does: o may be a or b.
    o->w = w0 * a->w + w1 * b->w;
    o->x = w0 * a->x + w1 * b->x;
    o->y = w0 * a->y + w1 * b->y;
    o->z = w0 * a->z + w1 * b->z;
}

// ------------------------------------------------------ the constructor

static void quat_from_angle(bQuaternion *q, uint16_t angle)
{
    bMatrix4 m;
    eIdentity(&m);
    eRotateX(&m, &m, 0);
    eRotateY(&m, &m, 0x8000);
    eRotateZ(&m, &m, angle);
    bMatrixToQuaternion(q, &m);
}

void selcam_init(SelectCarCameraMover *o, int viewID)
{
    int i;

    camera_mover_init(&o->base, viewID, CM_SELECT_CAR);
    o->base.vtbl = &SelectCarCameraMoverVtbl;
    o->RadiusStats = 5.0f;
    o->Mode = 0;
    o->Blend = 0.0f;
    o->Unused52 = 0;
    o->OffsetStats.x = o->OffsetStats.y = o->OffsetStats.z = 0.0f;
    o->OffsetStats.pad = 0.0f;
    o->OffsetOrbit = o->OffsetStats;
    o->FOVOrbit = 10000;
    o->DesiredVertSpeed = 300.0f;
    o->OrbitRadius = ORBIT_RADIUS;
    o->FOVStats = 10000;
    o->AngleZ = 0;
    o->Unused58 = 0;
    o->TiltStats = 0;
    o->TiltOrbit = 0;
    o->HorizSpeed = 300.0f;
    o->DesiredHorizSpeed = 300.0f;
    o->VertSpeed = 300.0f;
    o->RadiusSpeed = 0.0f;
    o->DesiredRadiusSpeed = 0.0f;
    for (i = 0; i < SELCAM_SND_COUNT; i++) {
        o->Samples[i] = SoundEnabled != 0;
        if (o->Samples[i]) snd_create(i);
    }
}

void selcam_destroy(SelectCarCameraMover *o)
{
    int i;

    o->base.vtbl = &SelectCarCameraMoverVtbl;
    for (i = 0; i < SELCAM_SND_COUNT; i++) {
        if (o->Samples[i]) snd_destroy(i);
    }
    camera_mover_destroy(&o->base);
}

// ------------------------------------------------------------ the setters

void selcam_set_radius_stats(SelectCarCameraMover *o, float r)
{
    o->RadiusStats = r;
}

void selcam_set_offset_stats(SelectCarCameraMover *o, const bVector3 *v)
{
    o->OffsetStats = *v;
}

void selcam_set_offset_orbit(SelectCarCameraMover *o, const bVector3 *v)
{
    o->OffsetOrbit = *v;
}

void selcam_set_fov_stats(SelectCarCameraMover *o, uint16_t fov)
{
    o->FOVStats = fov;
}

void selcam_set_fov_orbit(SelectCarCameraMover *o, uint16_t fov)
{
    o->FOVOrbit = fov;
}

void selcam_set_orientation_stats(SelectCarCameraMover *o, uint16_t angle,
                                  uint16_t tilt)
{
    o->AngleZ = angle;
    o->TiltStats = (uint16_t)-tilt;
    quat_from_angle(&o->QuatStats, angle);
}

void selcam_set_vert_angle_orbit(SelectCarCameraMover *o, uint16_t tilt)
{
    o->TiltOrbit = (uint16_t)-tilt;
}

void selcam_set_desired_radius_speed(SelectCarCameraMover *o, float s)
{
    o->DesiredRadiusSpeed = s;
}

void selcam_set_desired_vert_orbit_speed(SelectCarCameraMover *o, float s)
{
    o->DesiredVertSpeed = s;
}

void selcam_set_desired_horiz_orbit_speed(SelectCarCameraMover *o, float s)
{
    o->DesiredHorizSpeed = s;
}

float selcam_get_mode_param(const SelectCarCameraMover *o)
{
    return o->Blend;
}

void selcam_set_mode(SelectCarCameraMover *o, int32_t mode)
{
    o->Mode = mode;
    if (!SoundEnabled) return;
    if (mode == SELCAM_MODE_STATS) {
        snd_play(SELCAM_SND_OFF, 1.0f);
        snd_stop(SELCAM_SND_ACTIVE);
    } else if (mode == SELCAM_MODE_ORBIT) {
        snd_play(SELCAM_SND_ACTIVE, 0.0f);
        snd_play(SELCAM_SND_ON, 1.0f);
    }
}

// --------------------------------------------------------------- Update

// A speed's step toward its desired value, rate a second, not past it.
static void approach(float *cur, float want, float rate)
{
    float v = *cur;
    if (v < want) {
        v = v + RealTimeElapsed * rate;
        *cur = v;
        if (want < v) *cur = want;
    } else if (want < v) {
        v = v - RealTimeElapsed * rate;
        *cur = v;
        if (v < want) *cur = want;
    }
}

// A bounce's bump: as loud as the speed it hit with, past a floor.
static void bump(float volume)
{
    if (BUMP_MIN < volume && SoundEnabled) snd_play(SELCAM_SND_BUMP, volume);
}

void selcam_update(SelectCarCameraMover *o)
{
    bMatrix4    m, rot;
    bQuaternion q, step;
    bVector3    pos, push;
    float       t, dist;
    Camera     *cam;

    approach(&o->HorizSpeed, o->DesiredHorizSpeed, HORIZ_RATE);
    approach(&o->VertSpeed, o->DesiredVertSpeed, VERT_RATE);
    approach(&o->RadiusSpeed, o->DesiredRadiusSpeed, RADIUS_RATE);

    eIdentity(&m);
    t = 1.0f - (bCosBam((uint16_t)ee_trunc_w(o->Blend * 32768.0f)) + 1.0f)
                   * 0.5f;
    if (1.0f < t) t = 1.0f;
    if (t < 0.0f) t = 0.0f;

    // All the way at the stats view: the orbit starts over from it.
    if (o->Blend == 0.0f) {
        o->TiltOrbit = TILT_RESET;
        o->OrbitRadius = ORBIT_RADIUS;
        quat_from_angle(&o->QuatOrbit, o->AngleZ);
    }
    if (o->Mode == SELCAM_MODE_ORBIT) {
        bMatrix4 spin;
        eIdentity(&spin);
        eRotateZ(&spin, &spin,
                 (uint16_t)ee_trunc_w(o->HorizSpeed * RealTimeElapsed));
        bMatrixToQuaternion(&step, &spin);
        selcam_quat_multiply(&o->QuatOrbit, &step, &o->QuatOrbit);
        int32_t n = SelCamNormalizeCount;
        SelCamNormalizeCount = (int32_t)((uint32_t)n + 1u);
        if (n % 60 == 0) selcam_quat_normalize(&o->QuatOrbit);
    }
    selcam_slerp(&q, &o->QuatStats, &o->QuatOrbit, t);
    bQuaternionToMatrix(&rot, &q);

    pos.x = (o->OffsetOrbit.x - o->OffsetStats.x) * t + o->OffsetStats.x;
    pos.y = (o->OffsetOrbit.y - o->OffsetStats.y) * t + o->OffsetStats.y;
    pos.z = (o->OffsetOrbit.z - o->OffsetStats.z) * t + o->OffsetStats.z;
    pos.pad = (o->OffsetOrbit.pad - o->OffsetStats.pad) * t
              + o->OffsetStats.pad;
    eTranslate(&m, &m, &pos);
    eMulMatrix(&m, &m, &rot);

    if (o->Mode == SELCAM_MODE_ORBIT) {
        float v = o->VertSpeed;
        o->TiltOrbit = (uint16_t)(o->TiltOrbit
                                  + ee_trunc_w(v * RealTimeElapsed));
        if (TILT_MAX < o->TiltOrbit) {
            o->TiltOrbit = TILT_MAX;
            o->VertSpeed = -v * BOUNCE;
            bump(fabsf(o->VertSpeed) * TILT_BUMP);
        }
        if (!(TILT_MIN < o->TiltOrbit)) {
            o->TiltOrbit = TILT_RESET;
            o->VertSpeed = -o->VertSpeed * BOUNCE;
            bump(fabsf(o->VertSpeed) * TILT_BUMP);
        }
    }
    eRotateX(&m, &m,
             (uint16_t)ee_trunc_w((float)(int32_t)o->TiltStats
                                  + t * (float)((int32_t)o->TiltOrbit
                                                - (int32_t)o->TiltStats)));

    if (o->Mode == SELCAM_MODE_ORBIT) {
        float vol;
        o->OrbitRadius = o->OrbitRadius + o->RadiusSpeed * RealTimeElapsed;
        if (RADIUS_MAX < o->OrbitRadius) {
            o->OrbitRadius = RADIUS_MAX;
            o->RadiusSpeed = o->RadiusSpeed * -BOUNCE;
            bump(fabsf(o->RadiusSpeed) * RADIUS_BUMP);
        }
        if (o->OrbitRadius < RADIUS_MIN) {
            o->OrbitRadius = RADIUS_MIN;
            o->RadiusSpeed = o->RadiusSpeed * -BOUNCE;
            bump(fabsf(o->RadiusSpeed) * RADIUS_BUMP);
        }
        // The hum: as loud as the fastest of the three, its pitch falling
        // as the camera backs off.
        vol = fabsf(o->VertSpeed) * VOL_VERT;
        if (vol < fabsf(o->HorizSpeed) * VOL_HORIZ)
            vol = fabsf(o->HorizSpeed) * VOL_HORIZ;
        if (vol < fabsf(o->RadiusSpeed) * VOL_RADIUS)
            vol = fabsf(o->RadiusSpeed) * VOL_RADIUS;
        if (SoundEnabled && gSelCamSound) {
            if (gSelCamSound->set_volume)
                gSelCamSound->set_volume(SELCAM_SND_ACTIVE, vol);
            if (gSelCamSound->set_pitch)
                gSelCamSound->set_pitch(SELCAM_SND_ACTIVE,
                                        ((o->OrbitRadius - RADIUS_MIN)
                                         * PITCH_SCALE * PITCH_SLOPE
                                         + PITCH_BASE) - 1.0f);
        }
    }

    dist = o->RadiusStats + t * (o->OrbitRadius - o->RadiusStats);
    push.x = 0.0f;
    push.y = 0.0f;
    push.z = dist;
    push.pad = 0.0f;
    eTranslate(&m, &m, &push);

    if (o->Mode == SELCAM_MODE_STATS) {
        o->Blend = o->Blend - BLEND_STEP;
        if (o->Blend < 0.0f) o->Blend = 0.0f;
    } else if (o->Mode == SELCAM_MODE_ORBIT) {
        o->Blend = o->Blend + BLEND_STEP;
        if (1.0f < o->Blend) o->Blend = 1.0f;
    }

    cam = o->base.pCamera;
    if (!CameraStopUpdating) {
        cam->CurrentKey.FieldOfView = 4500;
        cam->CurrentKey.TargetDistance = dist;
    }
    camera_set_matrix(cam, &m, RealTimeElapsed);
}
