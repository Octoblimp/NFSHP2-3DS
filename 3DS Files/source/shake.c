// shake -- see shake.h.

#include "shake.h"

#include <math.h>
#include <stddef.h>

#include "car.h"
#include "eefpu.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "replay.h"
#include "world.h"

// ---------------------------------------------------------------- tEnvelope

int32_t tenvelope_get_index(const tEnvelope *e, float t)
{
    int32_t i = 0;

    while (i < e->nPoints && !(t < e->pPoints[i].fTime))
        i++;
    return i > 0 ? i - 1 : 0;
}

int32_t tenvelope_out_of_range(const tEnvelope *e, float t)
{
    return t < e->pPoints[0].fTime
        || e->pPoints[e->nPoints - 1].fTime <= t;
}

float tenvelope_get_slope_at(const tEnvelope *e, int32_t i)
{
    const sEnvelopePoint *p;

    if (i < 0 || i > e->nPoints - 2)
        return 0.0f;
    p = &e->pPoints[i];
    return (p[1].fValue - p[0].fValue) / (p[1].fTime - p[0].fTime);
}

float tenvelope_get_slope(const tEnvelope *e, float t)
{
    if (tenvelope_out_of_range(e, t))
        return 0.0f;
    return tenvelope_get_slope_at(e, tenvelope_get_index(e, t));
}

float tenvelope_get_value(const tEnvelope *e, float t)
{
    const sEnvelopePoint *p;
    float s;
    int32_t i;

    if (tenvelope_out_of_range(e, t))
        return 0.0f;
    i = tenvelope_get_index(e, t);
    s = tenvelope_get_slope_at(e, i);
    p = &e->pPoints[i];
    return p->fValue + s * (t - p->fTime);
}

float tenvelope_get_integral(const tEnvelope *e, float a, float b)
{
    float sum = 0.0f;
    float x0, x1, v;
    int32_t i;

    if (b < a) {
        float t = a;
        a = b;
        b = t;
    }
    if (a < e->pPoints[0].fTime)
        a = e->pPoints[0].fTime;
    if (e->pPoints[e->nPoints - 1].fTime < b)
        b = e->pPoints[e->nPoints - 1].fTime;

    x0 = a;
    i = tenvelope_get_index(e, a) + 1;
    for (;;) {
        x1 = e->pPoints[i].fTime;
        if (b < x1)
            x1 = b;
        v = tenvelope_get_value(e, x0);
        i++;
        v = v + (tenvelope_get_value(e, x1) - v) * 0.5f;
        sum = sum + (x1 - x0) * v;
        x0 = x1;
        if (!(x0 < b) || i >= e->nPoints)
            return sum;
    }
}

// ------------------------------------------------------------------ tShaker

void tshaker_init(tShaker *s)
{
    s->fDuration = 1.0f;
    s->fFrequency = 17.0f;
    s->vShake.x = 0.0f;
    s->vShake.y = 0.0f;
    s->vShake.z = 0.0f;
    s->pAmplitude = NULL;
    s->fTime = 0.0f;
}

float tshaker_get_amplitude(const tShaker *s)
{
    if (s->pAmplitude == NULL)
        return 0.0f;
    return tenvelope_get_value(s->pAmplitude, s->fTime);
}

// VU0's vmulx by -1, on every lane.
void tshaker_start_shaking(tShaker *s, const bVector3 *v, float duration,
                           float frequency)
{
    s->vShake.x = v->x * -1.0f;
    s->vShake.y = v->y * -1.0f;
    s->vShake.z = v->z * -1.0f;
    s->vShake.pad = v->pad * -1.0f;
    s->fFrequency = frequency;
    s->pAmplitude = &ShakeAmplitudeEnvelope;
    s->fDuration = duration;
    s->fTime = 0.0f;
}

void tshaker_update(tShaker *s, float dt)
{
    if (s->pAmplitude == NULL)
        return;
    s->fTime = s->fTime + dt / s->fDuration;
    if (tenvelope_out_of_range(s->pAmplitude, s->fTime))
        s->pAmplitude = NULL;
}

void tshaker_get_value(const tShaker *s, bVector3 *out)
{
    float a = 0.0f;

    if (!(ee_trunc_w(s->fTime * s->fFrequency) & 1) && s->pAmplitude != NULL)
        a = tenvelope_get_value(s->pAmplitude, s->fTime);
    out->x = s->vShake.x * a;
    out->y = s->vShake.y * a;
    out->z = s->vShake.z * a;
    out->pad = s->vShake.pad * a;
}

// Whether it shakes goes as a word of the stack; the envelope is always
// ShakeAmplitudeEnvelope, so a restore needs no more than that.
void tshaker_do_snapshot(tShaker *sh, ReplaySnapshot *s)
{
    int32_t shaking = sh->pAmplitude != NULL;

    ReplaySnapshot_MoveBool(s, &shaking, 1);
    if (s->RestoringSnapshotFlag)
        sh->pAmplitude = shaking != 0 ? &ShakeAmplitudeEnvelope : NULL;
    ReplaySnapshot_MoveVector3(s, &sh->vShake);
    ReplaySnapshot_MoveFloat(s, &sh->fTime);
    ReplaySnapshot_MoveFloat(s, &sh->fDuration);
    ReplaySnapshot_MoveFloat(s, &sh->fFrequency);
}

// ------------------------------------------------------------ the globals

tShaker  CameraShakers[2];                  // 0x002fa820
int32_t  bShakeTest;                        // gp-21912
bVector3 vShakeTest;                        // 0x002fa6e0

sEnvelopePoint ShakeAmplitudePoints[5] = {  // 0x002fa7a0
    { 0.0f, 1.0f }, { 0.1f, 0.7f }, { 0.3f, 0.5f }, { 0.5f, 0.4f },
    { 1.0f, 0.0f },
};
tEnvelope ShakeAmplitudeEnvelope;           // gp-21848

bVector3 vShakeAccelBias;                   // 0x00334080
bVector3 vShakeRotation;                    // 0x00334090

const float fShakeIntensityCoeffs[6] = {    // 0x002b13f0
    250.0f, 600.0f, 0.08f, 0.16f, 0.3f, 0.7f,
};

// The debug shake's duration (gp-31320), and the zone's two scales
// (gp-31316, gp-31312).
#define SHAKE_TEST_DURATION   0.6f
#define SHAKE_ZONE_AMPLITUDE  0.8f
#define SHAKE_ZONE_DURATION   1.2f
#define SHAKE_FREQUENCY      17.0f

void shake_static_init(void)
{
    int32_t i;

    // Three lanes of each vector; the fourth stays the .bss's 0.
    vShakeTest.x = 0.0f;
    vShakeTest.y = 0.0f;
    vShakeTest.z = 0.3f;                    // gp-31308
    vShakeRotation.x = -1200.0f;
    vShakeRotation.y = 2000.0f;
    vShakeRotation.z = 0.0f;
    vShakeAccelBias.x = 0.7f;               // gp-31304
    vShakeAccelBias.y = 0.5f;
    vShakeAccelBias.z = 2.0f;
    ShakeAmplitudeEnvelope.pPoints = ShakeAmplitudePoints;
    ShakeAmplitudeEnvelope.nPoints = 5;
    for (i = 0; i < 2; i++)
        tshaker_init(&CameraShakers[i]);
}

void reset_camera_shakers(void)
{
    int32_t i;

    for (i = 0; i < 2; i++)
        tshaker_init(&CameraShakers[i]);
}

void snapshot_camera_shakers(ReplaySnapshot *s)
{
    int32_t i;

    for (i = 0; i < 2; i++)
        tshaker_do_snapshot(&CameraShakers[i], s);
}

void update_camera_shakers(void)
{
    int32_t i;

    if (bShakeTest) {
        bShakeTest = 0;
        tshaker_start_shaking(&CameraShakers[0], &vShakeTest,
                              SHAKE_TEST_DURATION, SHAKE_FREQUENCY);
    }
    for (i = 0; i < 2; i++)
        tshaker_update(&CameraShakers[i], WorldTimeElapsed);
}

void get_shake(int32_t i, bVector3 *out)
{
    tshaker_get_value(&CameraShakers[i], out);
}

int32_t is_shake_active(int32_t i)
{
    return CameraShakers[i].pAmplitude != NULL;
}

// The shake in the camera's space is written into the rotation's own
// translation row, as the image does (its frame has the matrix at sp+16
// and eMulVector's output at sp+64). So the tip moves the camera too, and
// the y and z angles read that row after the rotations before them have
// turned it.
void apply_camera_shake(int32_t view, bMatrix4 *m)
{
    bVector3 shake;
    bVector4 v;
    bMatrix4 rot;
    int32_t i;

    if (pCurrentWorld->fTimeScale < 1.0f)
        return;
    if (view == EVIEW_ID_PLAYER1 || view == EVIEW_ID_PLAYER1_RVM)
        i = 0;
    else if (view == EVIEW_ID_PLAYER2)
        i = 1;
    else
        return;

    get_shake(i, &shake);
    v.x = shake.x;
    v.y = shake.y;
    v.z = shake.z;
    v.w = 0.0f;
    bIdentity(&rot);
    eMulVector4(&rot.v3, m, &v);
    rot.v3.w = 1.0f;
    eRotateX(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.x
                                              * (rot.v3.z + rot.v3.y)));
    eRotateY(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.y * rot.v3.x));
    eRotateZ(&rot, &rot, (uint16_t)ee_trunc_w(vShakeRotation.z
                                              * (rot.v3.x + rot.v3.y)));
    eMulMatrix(m, m, &rot);
}

void maybe_camera_shake(int32_t player, const bVector3 *accel)
{
    struct Player **pp = &PlayerPlayersByNumber[player];
    const float *k = fShakeIntensityCoeffs;
    tShaker *s = &CameraShakers[player];
    bVector3 a, v;
    float len, f, amplitude, duration;

    if (player_is_camera_pov_in_car(*pp))
        return;

    // The length is VU0's: (x*x + y*y) + z*z.
    a.x = vShakeAccelBias.x * accel->x;
    a.y = vShakeAccelBias.y * accel->y;
    a.z = vShakeAccelBias.z * accel->z;
    len = sqrtf((a.x * a.x + a.y * a.y) + a.z * a.z);
    if (len < k[0])
        return;
    if (k[1] < len)
        len = k[1];
    f = (len - k[0]) / (k[1] - k[0]);
    amplitude = k[2] + f * (k[3] - k[2]);
    if (!(tshaker_get_amplitude(s) < amplitude))
        return;
    duration = k[4] + f * (k[5] - k[4]);
    if (*pp != NULL && (*pp)->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP) {
        amplitude = amplitude * SHAKE_ZONE_AMPLITUDE;
        duration = duration * SHAKE_ZONE_DURATION;
    }
    // bNormalize writes three lanes, and StartShaking takes four: the
    // image's fourth is whatever the stack held. Nothing reads it back
    // (ApplyCameraShake zeroes it), so the port's is 0.
    v.pad = 0.0f;
    bNormalize3To(&v, &a, amplitude);
    tshaker_start_shaking(s, &v, duration, SHAKE_FREQUENCY);
}

void car_maybe_camera_shake(Car *c)
{
    if (c->pPlayer != NULL)
        maybe_camera_shake(c->pPlayer->PlayerNumber, &c->State.Acceleration);
}
