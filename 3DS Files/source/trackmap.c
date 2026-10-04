// trackmap -- TrackMap, the minimap; see trackmap.h.

#include "trackmap.h"

#include <math.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bprintf.h"
#include "cammover.h"
#include "drivecam.h"
#include "emath.h"
#include "esolid.h"
#include "eview.h"
#include "race.h"
#include "realtime.h"

TrackMapModeInformation TrackMapModeInfo[TRACKMAP_NUM_MODES];
TrackMapMarkerColour    TrackMapMarkerInfo[TRACKMAP_NUM_MARKER_COLOURS];

// What InitTrackMapModeInfo stores, mode by mode. It writes every field
// one at a time and leaves the padding alone; nothing reads the padding.
static const TrackMapModeInformation kModes[TRACKMAP_NUM_MODES] = {
    // 0, 3D
    { 0xd5da, {0}, 200.0f, 92, 228, 190.0f, 190.0f, 92, 240, 139.0f, 91.2864f,
      0.441781f, 0.202055f, 0, {0}, 0.09589f, 0.024999f, 0.134995f, 1, 1, 1, 0, 1.0f, 1, 1, {0} },
    // 1, 3D no rotation
    { 0xd5da, {0}, 200.0f, 92, 228, 190.0f, 190.0f, 92, 240, 139.0f, 91.2864f,
      0.441781f, 0.202055f, 0, {0}, 0.09589f, 0.03499f, 0.169987f, 0, 1, 1, 0, 1.0f, 1, 1, {0} },
    // 2, 2D
    { 0xffff, {0}, 200.0f, 72, 243, 130.0f, 130.0f, 72, 243, 100.0f, 100.0f,
      0.33f, 0.33f, 0, {0}, 0.1f, 0.039982f, 0.18498f, 1, 1, 1, 0, 1.0f, 1, 1, {0} },
    // 3, 2D no rotation
    { 0xffff, {0}, 200.0f, 72, 243, 130.0f, 130.0f, 72, 243, 100.0f, 100.0f,
      0.33f, 0.33f, 0, {0}, 0.1f, 0.03998f, 0.194978f, 0, 1, 1, 0, 1.0f, 1, 1, {0} },
    // 4, fixed
    { 0xffff, {0}, 200.0f, 79, 256, 130.0f, 130.0f, 79, 218, 1000.0f, 1000.0f,
      1.0f, 1.0f, 0, {0}, 0.07f, 0.044977f, 0.149972f, 0, 0, 0, 0, 1.0f, 1, 0, {0} },
    // 5, maximum size
    { 0xffff, {0}, 200.0f, 320, 243, 262.0f, 262.0f, 320, 243, 1000.0f, 1000.0f,
      1.0f, 1.0f, 0, {0}, 0.06f, 0.03f, 0.095f, 0, 0, 1, 0, 0.29f, 1, 0, {0} },
    // 6, off: all zeros, written as such
    { 0x0000, {0}, 0.0f, 0, 0, 0.0f, 0.0f, 0, 0, 0.0f, 0.0f,
      0.0f, 0.0f, 0, {0}, 0.0f, 0.0f, 0.0f, 0, 0, 0, 0, 0.0f, 0, 0, {0} },
    // 7, two players
    { 0xffff, {0}, 200.0f, 83, 245, 130.0f, 130.0f, 83, 245, 140.0f, 140.0f,
      1.0f, 1.0f, 0, {0}, 0.07f, 0.044977f, 0.149972f, 0, 0, 0, 0, 1.0f, 1, 0, {0} },
    // 8, Be The Cop, small: as fixed
    { 0xffff, {0}, 200.0f, 79, 256, 130.0f, 130.0f, 79, 218, 1000.0f, 1000.0f,
      1.0f, 1.0f, 0, {0}, 0.07f, 0.044977f, 0.149972f, 0, 0, 0, 0, 1.0f, 1, 0, {0} },
    // 9, Be The Cop, large: as maximum size
    { 0xffff, {0}, 200.0f, 320, 243, 262.0f, 262.0f, 320, 243, 1000.0f, 1000.0f,
      1.0f, 1.0f, 0, {0}, 0.06f, 0.03f, 0.095f, 0, 0, 1, 0, 0.29f, 1, 0, {0} },
    // 10, Be The Cop, targeting: as 2D, zooming to keep the pursued car
    { 0xffff, {0}, 200.0f, 72, 243, 130.0f, 130.0f, 72, 243, 100.0f, 100.0f,
      0.33f, 0.33f, 1, {0}, 0.1f, 0.039982f, 0.18498f, 1, 1, 1, 0, 1.0f, 1, 1, {0} },
};

static const TrackMapMarkerColour kMarkerColours[TRACKMAP_NUM_MARKER_COLOURS] = {
    { 172, 53, 0 }, { 75, 85, 255 }, { 0, 0, 255 }, { 0, 100, 0 },
    { 0, 0, 128 }, { 128, 128, 0 }, { 172, 53, 0 }, { 0, 64, 122 },
    { 0, 0, 192 },
};

void trackmap_init_mode_info(void)
{
    memcpy(TrackMapModeInfo, kModes, sizeof TrackMapModeInfo);
    memcpy(TrackMapMarkerInfo, kMarkerColours, sizeof TrackMapMarkerInfo);
}

void trackmap_construct(TrackMap *m, TrackInfo *track, Car *car,
                        Player *player)
{
    char name[16];

    m->SufficientDataToRenderMe = 1;
    m->PreviousTime = 0;
    if (track == NULL || car == NULL || player == NULL) {
        m->SufficientDataToRenderMe = 0;
        return;
    }

    trackmap_init_mode_info();
    m->CarToTrack = car;
    m->PlayerToTrack = player;
    m->CurrentlyDisplayedMode = 6;
    m->PreviousTime = (uint32_t)WorldTimer;
    m->CurrentTrack = track;
    m->CurrentlyPursuedCar = NULL;
    m->CurrentMode = 6;
    m->PreviousCameraDirection.x = 0.0f;
    m->PreviousCameraDirection.y = 0.0f;
    m->CurrentCameraSpeed.x = 0.0f;
    m->CurrentCameraSpeed.y = 0.0f;

    // The map is the only one asked for without the default texture.
    b_snprintf(name, sizeof name, "TRACK%d_MAP", track->TrackNumber);
    m->TrackMapTexture = get_texture_info(bchunk_hash(name), 0, 0);
    if (m->TrackMapTexture == NULL)
        m->SufficientDataToRenderMe = 0;
    m->CarMarkerNonrotatingTexture =
        get_texture_info(bchunk_hash("CAR_MARKER"), 1, 0);
    m->CarMarkerRotatingTexture =
        get_texture_info(bchunk_hash("CAR_MARKERB"), 1, 0);
    m->OverlayTexture = get_texture_info(bchunk_hash("TRACKMAPFRAME"), 1, 0);
    m->UnderlayTexture = get_texture_info(bchunk_hash("MAPBACK"), 1, 0);
    m->StartFinishLineTexture =
        get_texture_info(bchunk_hash("START_LINE"), 1, 0);
    m->RoadblockTexture = get_texture_info(bchunk_hash("BKGBMP"), 1, 0);

    if (m->CarMarkerNonrotatingTexture == NULL
        || m->CarMarkerRotatingTexture == NULL
        || m->OverlayTexture == NULL || m->UnderlayTexture == NULL)
        m->SufficientDataToRenderMe = 0;
    // A loop draws its start line.
    if (TheRaceParameters.Point2Point == 0 && m->StartFinishLineTexture == NULL)
        m->SufficientDataToRenderMe = 0;

    eIdentity(&m->MapRotationMatrix);
    eRotateZ(&m->MapRotationMatrix, &m->MapRotationMatrix,
             m->CurrentTrack->TrackMapCalibrationRotation);
}

TrackMap *trackmap_new(TrackInfo *track, Car *car, Player *player)
{
    TrackMap *m = bMalloc((int)sizeof(TrackMap), "TrackMap", 0, 16);

    trackmap_construct(m, track, car, player);
    return m;
}

void trackmap_delete(TrackMap *m)
{
    bFree(m);
}

void eval_cubic(float *x, float *v, float target, float t)
{
    float x0 = *x, v0 = *v;
    float d = target - x0;
    float a = (v0 - d) - d;
    float b = ((d + d) + d - v0) - v0;

    *x = ((a * t + b) * t + v0) * t + x0;
    *v = (((a + a) + a) * t + (b + b)) * t + v0;
}

int32_t trackmap_get_angle(TrackMap *m, uint16_t *angle)
{
    bVector3 dir;
    float t, x, y;

    if (TrackMapModeInfo[m->CurrentlyDisplayedMode].HasRotation == 0) {
        *angle = 0x8000;
        return 1;
    }
    if (trackmap_get_camera_direction(m, &dir) == 0)
        return 0;

    // GetCameraDirection may have started the ease: read it after.
    t = (float)(int32_t)((uint32_t)WorldTimer - m->PreviousTime) * 0.00025f;
    t = t * 0.9f;
    x = m->PreviousCameraDirection.x;
    y = m->PreviousCameraDirection.y;
    eval_cubic(&x, &m->CurrentCameraSpeed.x, dir.x, t);
    eval_cubic(&y, &m->CurrentCameraSpeed.y, dir.y, t);
    m->PreviousCameraDirection.x = x;
    m->PreviousCameraDirection.y = y;
    m->PreviousTime = (uint32_t)WorldTimer;
    *angle = (uint16_t)(bATan(y, x) - 32768);
    return 1;
}

// The first mover on the view's list, as eView's own loops find it.
static CameraMover *first_mover(eView *v)
{
    bNode *n = v->CameraMoverList.next;

    return n != &v->CameraMoverList ? (CameraMover *)n : NULL;
}

int32_t trackmap_get_camera_direction(TrackMap *m, bVector3 *dir)
{
    CameraMover *mover = first_mover(eGetView(m->PlayerToTrack->ViewID));

    if (mover == NULL || mover->Type != CM_DRIVE) {
        if (race_get_race_stage(pCurrentRace) != RACE_STAGE_RACING) {
            dir->x = m->CarToTrack->State.BodyMatrix.v0.x;
            dir->y = m->CarToTrack->State.BodyMatrix.v0.y;
        } else {
            dir->x = m->PreviousCameraDirection.x;
            dir->y = m->PreviousCameraDirection.y;
        }
        return 1;
    }

    {
        const Camera *cam = mover->pCamera;
        bMatrix4 r;

        dir->x = cam->CurrentKey.Direction.x;
        dir->y = cam->CurrentKey.Direction.y;
        dir->z = cam->CurrentKey.Direction.z;
        eIdentity(&r);
        eRotateZ(&r, &r, ((DriveCameraMover *)mover)->LookBackAngle);
        eMulVector3(dir, &r, dir);
    }
    if (fabsf(m->PreviousCameraDirection.x) <= 0.001f
        && fabsf(m->PreviousCameraDirection.y) <= 0.001f) {
        m->PreviousCameraDirection.x = dir->x;
        m->PreviousTime = (uint32_t)WorldTimer;
        m->PreviousCameraDirection.y = dir->y;
    }
    return 1;
}

void trackmap_get_car_uv_position(TrackMap *m, bVector2 *out,
                                  const bVector3 *pos)
{
    const TrackInfo *t = m->CurrentTrack;
    bVector3 v;

    v.x = pos->x;
    v.y = -pos->y;
    v.z = 1.0f;
    v.x = v.x - t->TrackMapCalibrationUpperLeft.x;
    v.y = v.y + t->TrackMapCalibrationUpperLeft.y;
    v.x = v.x / t->TrackMapCalibrationMapWidthMetres;
    v.y = v.y / t->TrackMapCalibrationMapWidthMetres;
    eMulVector3(&v, &m->MapRotationMatrix, &v);
    out->x = v.x;
    out->y = v.y;
}

void trackmap_get_box_on_map(TrackMap *m, const bVector2 *centre,
                             float forward, float backward, float left,
                             float right, uint16_t angle, bVector2 out[4])
{
    bMatrix4 r, t;
    bVector3 c, corner[4];
    int i;

    (void)m;
    eIdentity(&r);
    eRotateZ(&r, &r, angle);
    c.x = centre->x;
    c.y = centre->y;
    c.z = 0.0f;
    eCreateTranslationMatrix(&t, &c);
    eMulMatrix(&t, &r, &t);

    corner[0].x = right;
    corner[0].y = forward;
    corner[1].x = -left;
    corner[1].y = forward;
    corner[2].x = -left;
    corner[2].y = -backward;
    corner[3].x = right;
    corner[3].y = -backward;
    for (i = 0; i < 4; i++) {
        corner[i].z = 0.0f;
        eMulVector3(&corner[i], &t, &corner[i]);
        out[i].x = corner[i].x;
        out[i].y = corner[i].y;
    }
}
