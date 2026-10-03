// eEnvMap's views and cameras -- see eenvmap.h.

#include "eenvmap.h"

#include <math.h>
#include <stddef.h>

#include "cammover.h"
#include "car.h"
#include "emath.h"
#include "eviewmatrix.h"
#include "gameflow.h"
#include "player.h"
#include "realtime.h"
#include "trackflow.h"
#include "world.h"

eView   *EnvMapViews[6];
Camera   EnvMapCameras[6];
int32_t  EnvMapCubeFace[6];
bVector3 EnvMapCentre;
int32_t  EnvMapCentreValid;
bMatrix4 EnvMapFaceMatrix[6];
int32_t  EnableEnvMapViews = 1;                 // gp-21072

// 0x002d6e40, which the static constructor sets: the world's up, +z.
static const bVector3 kUp = { 0.0f, 0.0f, 1.0f, 0.0f };

// Each face's axis (0x002d6e50) and its camera's up (0x002d6f10), in the
// space the view from the camera to the car turns them into: the
// frontend's set and then the race's (0x002d6eb0, 0x002d6f70), picked by
// whether the game is in the frontend. With the camera level, the race's
// faces 0 and 2 look straight up and down, and the light contexts take
// face 2's camera for hack_man_matrix, so the map's +z is the sky.
static const bVector3 kAxis[2][6] = {
    { { -1, 0, 0, 0 }, { 0, 1, 0, 0 }, { 1, 0, 0, 0 },
      { 0, -1, 0, 0 }, { 0, 0, 1, 0 }, { 0, 0, -1, 0 } },
    { { 0, 0, 1, 0 }, { 0, -1, 0, 0 }, { 0, 0, -1, 0 },
      { 0, 1, 0, 0 }, { -1, 0, 0, 0 }, { 1, 0, 0, 0 } },
};
static const bVector3 kFaceUp[2][6] = {
    { { 0, 0, 1, 0 }, { 0, 0, 1, 0 }, { 0, 0, 1, 0 },
      { 0, 0, 1, 0 }, { 1, 0, 0, 0 }, { -1, 0, 0, 0 } },
    { { -1, 0, 0, 0 }, { -1, 0, 0, 0 }, { -1, 0, 0, 0 },
      { -1, 0, 0, 0 }, { 0, 0, -1, 0 }, { 0, 0, 1, 0 } },
};

// Which views draw in a frame (0x002d6fd0), by eFrameCounter over the
// count beside it (gp-24200): with one player's view, modes 1 and 2, faces
// 0 and 5 every frame and 1 to 4 in turn; otherwise one face a frame.
static const uint8_t kSchedule[2][6][6] = {
    { { 1, 1, 0, 0, 0, 1 }, { 1, 0, 1, 0, 0, 1 }, { 1, 0, 0, 1, 0, 1 },
      { 1, 0, 0, 0, 1, 1 } },
    { { 1, 0, 0, 0, 0, 0 }, { 0, 1, 0, 0, 0, 0 }, { 0, 0, 1, 0, 0, 0 },
      { 0, 0, 0, 1, 0, 0 }, { 0, 0, 0, 0, 1, 0 }, { 0, 0, 0, 0, 0, 1 } },
};
static const uint32_t kScheduleFrames[2] = { 4, 6 };

// The cube's faces, as the PICA picks and reads them (OpenGL's rule): the
// axis each looks along, and its camera's up, the opposite of the way its
// texels' t runs, in the mirrored map's space; see eenvmap.h.
static const float kCubeAxis[6][3] = {
    { 1, 0, 0 }, { -1, 0, 0 }, { 0, 1, 0 }, { 0, -1, 0 }, { 0, 0, 1 },
    { 0, 0, -1 },
};
static const float kCubeUp[6][3] = {
    { 0, 1, 0 }, { 0, 1, 0 }, { 0, 0, -1 }, { 0, 0, 1 }, { 0, 1, 0 },
    { 0, 1, 0 },
};

// gp-32468, the views' far plane, and the field of view whose H is 32, so
// a 64 pixel target is 90 degrees across.
#define ENV_FAR_Z 10000.0f
#define ENV_FOV   30180

int eenvmap_init(void)
{
    int i;

    for (i = 0; i < 6; i++) {
        eView         *view = eGetView(EVIEW_ID_ENVMAP_LO + i);
        eRenderTarget *rt   = eGetRenderTarget(8 + i);
        uint32_t       grey = 96u + 16u * (uint32_t)i;

        // TheOnlyEnvMap's constructor, which the static constructors run.
        camera_init(&EnvMapCameras[i]);

        // The render target setup's (0x00106d88): 64 square, at the
        // aspect of a square pixel, with the 2D aspect the player's, and
        // cleared to a grey of its own.
        rt->ID               = 8 + i;
        rt->ScissorX         = 0;
        rt->ScissorY         = 0;
        rt->ScissorW         = 64;
        rt->ScissorH         = 64;
        rt->FrameWidth       = 64;
        rt->FrameHeight      = 64;
        rt->AspectRatioX     = 1.0f;
        rt->AspectRatioY     = 1.0f;
        rt->AspectRatio2DX   = 0.8f;
        rt->AspectRatio2DY   = 0.94f;
        rt->FovBias          = 1.0f;
        rt->BackgroundColour = grey * 0x01010101u;
        rt->ClearBackground  = 1;

        view->Active        = 1;
        EnvMapViews[i]      = view;
        view->pCamera       = &EnvMapCameras[i];
        view->ID            = EVIEW_ID_ENVMAP_LO + i;
        rt->Active          = 1;
        view->pRenderTarget0 = rt;
    }
    return 1;
}

// A look-at's rotation alone: its translation zeroed, as the listing
// stores the four lanes it needs.
static void rotation_only(bMatrix4 *m)
{
    m->v0.w = 0.0f;
    m->v1.w = 0.0f;
    m->v2.w = 0.0f;
    m->v3.x = 0.0f;
    m->v3.y = 0.0f;
    m->v3.z = 0.0f;
    m->v3.w = 1.0f;
}

// A direction in the mirrored map's space back in the world's: z negated
// (D with the mirror's x) through hack_man_matrix's columns.
static void map_to_world(bVector3 *w, const float a[3])
{
    const bMatrix4 *h = &hack_man_matrix;

    w->x   = a[0] * h->v0.x + a[1] * h->v0.y - a[2] * h->v0.z;
    w->y   = a[0] * h->v1.x + a[1] * h->v1.y - a[2] * h->v1.z;
    w->z   = a[0] * h->v2.x + a[1] * h->v2.y - a[2] * h->v2.z;
    w->pad = 0.0f;
}

// The cube face a world direction is nearest: the largest of its three in
// the mirrored map's space, and its sign.
static int32_t cube_face_of(const bVector3 *w)
{
    const bMatrix4 *h = &hack_man_matrix;
    float           r[3];
    int             k = 0, c;

    r[0] = w->x * h->v0.x + w->y * h->v1.x + w->z * h->v2.x;
    r[1] = w->x * h->v0.y + w->y * h->v1.y + w->z * h->v2.y;
    r[2] = -(w->x * h->v0.z + w->y * h->v1.z + w->z * h->v2.z);
    for (c = 1; c < 3; c++) {
        if (fabsf(r[c]) > fabsf(r[k]))
            k = c;
    }
    return 2 * k + (r[k] < 0.0f);
}

void eenvmap_update_cameras(const bVector3 *pos, const bVector3 *target)
{
    static const bVector3 origin = { 0.0f, 0.0f, 0.0f, 0.0f };
    static const bVector3 along  = { 1.0f, 0.0f, 0.0f, 0.0f };
    const uint8_t *active;
    bMatrix4       look1, look2, turn;
    bVector3       axis[6];
    int            set, mode, i;

    // The view down +x from the origin, and the one from the camera to
    // the car; the second is hack_man_matrix until face 2's camera is.
    eCreateLookAtMatrix(&look1, &origin, &along, &kUp);
    rotation_only(&look1);
    eCreateLookAtMatrix(&look2, pos, target, &kUp);
    rotation_only(&look2);
    hack_man_matrix = look2;

    // What turns the first into the second, transposed: the faces' axes
    // times it are the world's directions they look along.
    eTransposeMatrix(&turn, &look1);
    eMulMatrix(&turn, &look2, &turn);
    rotation_only(&turn);
    eTransposeMatrix(&turn, &turn);

    set = !(gTrackFlowGameFlow != NULL
            && gTrackFlowGameFlow->current == BGF_IN_FRONTEND);
    mode = (uint32_t)(eGetCurrentViewMode() - 1) < 2u ? 0 : 1;
    active = kSchedule[mode][eFrameCounter % kScheduleFrames[mode]];

    // Retail's loop does each face whole, the look-at, hack_man_matrix at
    // face 2 and the camera; a camera here needs hack_man_matrix as the
    // loop leaves it, so the cameras are a second loop. A face with no
    // view or camera, before eInitEnvMap, is left alone.
    for (i = 0; i < 6; i++) {
        eView   *view = EnvMapViews[i];
        bVector3 up, dir;

        axis[i].x = axis[i].y = axis[i].z = axis[i].pad = 0.0f;
        if (view == NULL)
            continue;
        view->Active = active[i] != 0;
        if (view->pCamera == NULL)
            continue;
        eMulVector3(&up, &turn, &kFaceUp[set][i]);
        eMulVector3(&dir, &turn, &kAxis[set][i]);
        axis[i] = dir;
        dir.x += target->x;
        dir.y += target->y;
        dir.z += target->z;
        dir.pad += target->pad;
        eCreateLookAtMatrix(&EnvMapFaceMatrix[i], target, &dir, &up);
        if (i == 2)
            hack_man_matrix = EnvMapFaceMatrix[i];
    }

    for (i = 0; i < 6; i++) {
        eView   *view = EnvMapViews[i];
        Camera  *cam;
        bMatrix4 m;
        bVector3 fwd, up;
        int32_t  face;

        if (view == NULL || view->pCamera == NULL)
            continue;
        cam  = view->pCamera;
        face = cube_face_of(&axis[i]);
        EnvMapCubeFace[i] = face;
        map_to_world(&fwd, kCubeAxis[face]);
        map_to_world(&up, kCubeUp[face]);
        fwd.x += target->x;
        fwd.y += target->y;
        fwd.z += target->z;
        eCreateLookAtMatrix(&m, target, &fwd, &up);
        camera_set_matrix(cam, &m, RealTimeElapsed);
        if (!CameraStopUpdating) {
            cam->RenderDash               = 0;
            cam->CurrentKey.FocalDistance = 0.0f;
        }
        cam->CurrentKey.NearZ = 0.5f;
        cam->CurrentKey.FarZ  = ENV_FAR_Z;
        if (!CameraStopUpdating)
            cam->CurrentKey.FieldOfView = ENV_FOV;
    }
    EnvMapCentre      = *target;
    EnvMapCentreValid = 1;
}

void update_environment_map_cameras(void)
{
    const bVector3 *at = NULL;
    eView          *view;
    bVector3        pos, target;

    if (pCurrentWorld != NULL) {
        Car         *car = NULL;
        bNode       *n;

        view = eGetView(1);
        n    = view != NULL ? view->CameraMoverList.next : NULL;
        if (n != NULL && n != &view->CameraMoverList) {
            CameraMover *m = (CameraMover *)n;

            car = (Car *)m->vtbl->GetCarToFollow(m);
        }
        if (car == NULL && PlayerPlayersByIndex[0] != NULL)
            car = PlayerPlayersByIndex[0]->MyCar;
        // Retail takes CarList's first without asking whether there is
        // one.
        if (car == NULL
            && pCurrentWorld->CarList.next != (void *)&pCurrentWorld->CarList)
            car = (Car *)pCurrentWorld->CarList.next;
        if (car != NULL)
            at = &car->State.GeometryPosition;
    }
    // With no world, retail centres on the first FrontEndRenderingCar's
    // position (the list at gp-23656, +32), which is not ported.
    if (at == NULL)
        return;

    view = eGetView(1);
    if (view == NULL || view->pCamera == NULL)
        return;
    pos = view->pCamera->CurrentKey.Position;
    // Plus the vector at 0x002e0260, which is zero.
    target = *at;
    eenvmap_update_cameras(&pos, &target);
}
