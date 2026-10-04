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
#include "eefpu.h"
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

// --------------------------------------------------------- the map (8m-6b)

void trackmap_map_to_screen(TrackMap *m, ePoly *poly, bVector3 *p0,
                            bVector3 *p1, bVector3 *p2, bVector3 *p3)
{
    const TrackMapModeInformation *info =
        &TrackMapModeInfo[m->CurrentlyDisplayedMode];
    bVector3 *p[4];
    bMatrix4 tilt;
    float h;
    int i;

    p[0] = p0;
    p[1] = p1;
    p[2] = p2;
    p[3] = p3;
    eIdentity(&tilt);
    eRotateX(&tilt, &tilt, info->AngleX);
    for (i = 0; i < 4; i++)
        eMulVector3(p[i], &tilt, p[i]);

    // Retail loads X and Y unsigned.
    h = info->H;
    for (i = 0; i < 4; i++) {
        poly->Vertices[i].x =
            p[i]->x * h / (p[i]->z + h) + (float)(uint16_t)info->X;
        poly->Vertices[i].y =
            p[i]->y * h / (p[i]->z + h) + (float)(uint16_t)info->Y;
    }
    for (i = 0; i < 4; i++) {
        if (0.0f < p[i]->z)
            poly->Colours[i][3] = (uint8_t)ee_trunc_w(
                (1.0f - p[i]->z / (info->Height * 0.666666687f)) * 128.0f);
        else
            poly->Colours[i][3] = 128;
    }
}

int32_t get_side_of_line(const bVector2 *a, const bVector2 *b,
                         const bVector2 *p)
{
    float dx = b->x - a->x;
    float dy = b->y - a->y;
    float ex = p->x - a->x;
    float ey = p->y - a->y;
    float c = ex * dy + ey * -dx;

    if (0.0f < c)
        return 1;
    if (c < 0.0f)
        return -1;
    return 0;
}

void calculate_centroid_of_quad(bVector2 *out, const bVector2 q[4])
{
    const float third = 0.333333343f;
    float ax = ((q[0].x + q[1].x) + q[2].x) * third;
    float ay = ((q[0].y + q[1].y) + q[2].y) * third;
    float bx = ((q[0].x + q[2].x) + q[3].x) * third;
    float by = ((q[0].y + q[2].y) + q[3].y) * third;

    out->y = (ay + by) * 0.5f;
    out->x = (ax + bx) * 0.5f;
}

// Retail's buffers hold eight points, which a convex quad clipped to a box
// never passes. A point past the eighth is dropped here; retail would
// write it over the next buffer.
#define CLIP_POINTS 8

// EmitPoint, 0x001bca08: a member, but it reads nothing of the map.
static void emit_point(const bVector2 *pt, const bVector3 *uv, uint8_t alpha,
                       bVector2 *pts, bVector3 *uvs, uint8_t *alphas,
                       int32_t *count)
{
    int32_t n = *count;

    if (n >= CLIP_POINTS)
        return;
    pts[n] = *pt;
    uvs[n] = *uv;
    alphas[n] = alpha;
    *count = n + 1;
}

void trackmap_clip_polygon(TrackMap *m, ePoly *poly, TextureInfo *tex,
                           int32_t layer)
{
    const TrackMapModeInformation *info =
        &TrackMapModeInfo[m->CurrentlyDisplayedMode];
    bVector2 clip[4];
    bVector2 pts[CLIP_POINTS], outPts[CLIP_POINTS];
    bVector3 uvs[CLIP_POINTS], outUVs[CLIP_POINTS];
    uint8_t  alphas[CLIP_POINTS], outAlphas[CLIP_POINTS];
    float    hw, hh, cx, cy, z;
    int32_t  n, count, k, prev, i, j, top, start, last;

    // The box's corners, clockwise on the screen from the top left.
    hh = info->ClippingHeight * 0.5f;
    hw = info->ClippingWidth * 0.5f;
    cx = (float)(uint16_t)info->ClippingX;
    cy = (float)(uint16_t)info->ClippingY;
    clip[0].x = cx - hw;
    clip[0].y = cy - hh;
    clip[1].x = cx + hw;
    clip[1].y = cy - hh;
    clip[2].x = cx + hw;
    clip[2].y = cy + hh;
    clip[3].x = cx - hw;
    clip[3].y = cy + hh;

    for (i = 0; i < 4; i++) {
        pts[i].x = poly->Vertices[i].x;
        pts[i].y = poly->Vertices[i].y;
        uvs[i].x = poly->UVs[i][0];
        uvs[i].y = poly->UVs[i][1];
        uvs[i].z = poly->UVs[i][2];
        alphas[i] = poly->Colours[i][3];
    }

    // Sutherland-Hodgman: against the line from corner k to corner k - 1,
    // the side GetSideOfLine calls -1 is out.
    n = 4;
    count = 0;
    prev = 3;
    for (k = 0; k < 4; k++) {
        count = 0;
        j = n - 1;
        for (i = 0; i < n; i++) {
            int in_i = get_side_of_line(&clip[k], &clip[prev], &pts[i]) != -1;
            int in_j = get_side_of_line(&clip[k], &clip[prev], &pts[j]) != -1;

            if (in_j)
                emit_point(&pts[j], &uvs[j], alphas[j], outPts, outUVs,
                           outAlphas, &count);
            if (in_i != in_j) {
                const bVector2 *a = &clip[k], *b = &clip[prev];
                float lx = b->x - a->x, ly = b->y - a->y;
                float dx = pts[j].x - pts[i].x;
                float t = ((pts[i].y - a->y) * lx - (pts[i].x - a->x) * ly)
                        / (dx * ly - (pts[j].y - pts[i].y) * lx);
                bVector2 ip;
                bVector3 iuv;
                uint8_t  ia;

                ip.x = pts[i].x + t * dx;
                ip.y = pts[i].y + t * (pts[j].y - pts[i].y);
                iuv.x = uvs[i].x + t * (uvs[j].x - uvs[i].x);
                iuv.y = uvs[i].y + t * (uvs[j].y - uvs[i].y);
                iuv.z = uvs[i].z + t * (uvs[j].z - uvs[i].z);
                iuv.pad = 0.0f;
                ia = (uint8_t)ee_trunc_w((float)alphas[i]
                     + t * (float)((int32_t)alphas[j] - (int32_t)alphas[i]));
                emit_point(&ip, &iuv, ia, outPts, outUVs, outAlphas, &count);
            }
            j = i;
        }
        n = count;
        prev = k;
        memcpy(pts, outPts, (size_t)n * sizeof pts[0]);
        memcpy(uvs, outUVs, (size_t)count * sizeof uvs[0]);
        memcpy(alphas, outAlphas, (size_t)count);
    }

    // The top point, the leftmost of those within 0.001 of the top.
    top = 0;
    for (i = 1; i < count; i++) {
        if (outPts[i].y < outPts[top].y)
            top = i;
        else if (fabsf(outPts[i].y - outPts[top].y) <= 0.001f
                 && outPts[i].x < outPts[top].x)
            top = i;
    }

    // Quads fanned from it, each sharing its last point with the next. The
    // last quad of an odd count repeats its last point.
    z = (float)layer;
    start = 1;
    while (start < count - 1) {
        ePoly out;
        int   s, c;

        epoly_init(&out);
        out.Flailer = 1;
        out.Vertices[0].x = outPts[top].x;
        out.Vertices[0].y = outPts[top].y;
        out.Vertices[0].z = z;
        out.UVs[0][0] = outUVs[top].x;
        out.UVs[0][1] = outUVs[top].y;
        out.UVs[0][2] = outUVs[top].z;
        for (c = 0; c < 3; c++)
            out.Colours[0][c] = poly->Colours[0][c];
        out.Colours[0][3] = outAlphas[top];
        last = start;
        for (s = 1; s < 4; s++) {
            int32_t idx;

            last = start + s - 1;
            if (!(last < count))
                last = count - 1;
            idx = top + last;
            if (!(idx < count))
                idx -= count;
            out.Vertices[s].x = outPts[idx].x;
            out.Vertices[s].y = outPts[idx].y;
            out.Vertices[s].z = z;
            out.UVs[s][0] = outUVs[idx].x;
            out.UVs[s][1] = outUVs[idx].y;
            out.UVs[s][2] = outUVs[idx].z;
            for (c = 0; c < 3; c++)
                out.Colours[s][c] = poly->Colours[s][c];
            out.Colours[s][3] = outAlphas[idx];
        }
        start = last;
        if (gEPolyRenderFn != NULL)
            gEPolyRenderFn(&out, tex, 0);
    }
}

void trackmap_draw_over_or_under_lay(TrackMap *m, TextureInfo *tex,
                                     int32_t layer)
{
    const TrackMapModeInformation *info =
        &TrackMapModeInfo[m->CurrentlyDisplayedMode];
    ePoly poly;
    float z = (float)layer, hw, hh, cx, cy;
    int i;

    if (info->HasBorder == 0)
        return;
    epoly_init(&poly);
    for (i = 0; i < 4; i++)
        poly.Vertices[i].z = z;
    hh = info->ClippingHeight * 0.5f;
    hw = info->ClippingWidth * 0.5f;
    cx = (float)(uint16_t)info->ClippingX;
    cy = (float)(uint16_t)info->ClippingY;
    poly.Vertices[0].x = cx - hw;
    poly.Vertices[0].y = cy - hh;
    poly.Vertices[1].x = cx + hw;
    poly.Vertices[1].y = cy - hh;
    poly.Vertices[2].x = cx + hw;
    poly.Vertices[2].y = cy + hh;
    poly.Vertices[3].x = cx - hw;
    poly.Vertices[3].y = cy + hh;
    if (info->IsDrawn == 0)
        return;
    poly.Flailer = 1;
    if (gEPolyRenderFn != NULL)
        gEPolyRenderFn(&poly, tex, 0);
}

void trackmap_draw_map(TrackMap *m, bVector2 *centre, bVector2 outer[4],
                       uint16_t angle)
{
    const TrackMapModeInformation *info =
        &TrackMapModeInfo[m->CurrentlyDisplayedMode];
    ePoly    poly;
    bVector2 carUV, box[4];
    bVector3 p[4];
    float    fwd, back, side, hw, hh;
    int      i;

    if (info->IsDrawn == 0)
        return;
    epoly_init(&poly);
    carUV.x = 0.0f;
    carUV.y = 0.0f;
    trackmap_get_car_uv_position(m, &carUV, &m->CarToTrack->State.Position);

    if (info->HasScrolling != 0) {
        if (info->ZoomToKeepPursuedCarInView != 0
            && m->CurrentlyPursuedCar != NULL) {
            // Far enough to take in the pursued car, and a tenth more.
            const bVector3 *a = &m->CarToTrack->State.Position;
            const bVector3 *b = &m->CurrentlyPursuedCar->State.Position;
            float dy = a->y - b->y;
            float dx = a->x - b->x;
            float dist = sqrtf(dx * dx + dy * dy);

            fwd = dist / m->CurrentTrack->TrackMapCalibrationMapWidthMetres
                * (info->Width / info->ClippingWidth) + 0.1f;
            back = fwd;
            side = fwd;
        } else {
            back = info->ViewDistanceBackward;
            fwd = info->ViewDistanceForward;
            side = (fwd + back) * 0.5f;
        }
        m->CurrentViewDistanceForward = fwd;
        m->CurrentViewDistanceBackward = back;
        trackmap_get_box_on_map(m, &carUV, fwd, back, side, side, angle, box);
        trackmap_get_box_on_map(m, &carUV, fwd * 1.2f, back * 1.2f,
                                side * 1.2f, side * 1.2f, angle, outer);
    } else {
        for (i = 0; i < 4; i++) {
            box[i].x = (i == 1 || i == 2) ? 1.0f : 0.0f;
            box[i].y = (i >= 2) ? 1.0f : 0.0f;
            outer[i] = box[i];
        }
    }
    for (i = 0; i < 4; i++) {
        poly.UVs[i][0] = box[i].x;
        poly.UVs[i][1] = box[i].y;
    }
    calculate_centroid_of_quad(centre, box);

    // The map's Width by Height about the origin, at z 0.
    hw = info->Width * 0.5f;
    hh = info->Height * 0.5f;
    p[0].x = -hw;
    p[0].y = -hh;
    p[1].x = hw;
    p[1].y = -hh;
    p[2].x = hw;
    p[2].y = hh;
    p[3].x = -hw;
    p[3].y = hh;
    for (i = 0; i < 4; i++)
        p[i].z = 0.0f;
    trackmap_map_to_screen(m, &poly, &p[0], &p[1], &p[2], &p[3]);
    for (i = 0; i < 4; i++)
        poly.Colours[i][3] =
            (uint8_t)ee_trunc_w((float)poly.Colours[i][3] * info->Alpha);

    // u, v and q over the depth, for the GS's perspective-correct UVs.
    for (i = 0; i < 4; i++) {
        float r = 1.0f / (p[i].z + info->H);

        poly.UVs[i][0] *= r;
        poly.UVs[i][1] *= r;
        poly.UVs[i][2] *= r;
    }
    trackmap_clip_polygon(m, &poly, m->TrackMapTexture, 14);
}
