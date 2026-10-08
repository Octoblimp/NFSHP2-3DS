// cameracoord -- see cameracoord.h.

#include "cameracoord.h"

#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "bprintf.h"
#include "player.h"
#include "racefinish.h"
#include "vtable.h"

CameraLoader TheCameraLoader;                   // 0x00310370
bNode CameraCoordinatorList;                    // gp-19920

CameraMover *(*gBumperCameraMoverFn)(void *mem, int32_t viewID,
                                     struct Car *car, CameraDataItems *cd);
CameraMover *(*gTrackFlyCameraMoverFn)(void *mem, int32_t viewID,
                                       CameraDataItems *cd, struct Car *car);
int32_t (*gTrackFlyCameraMoverIsFinishedFn)(CameraMover *m);

typedef void (*CoordinatorDtorFn)(void *c, int32_t flags);
typedef void (*CoordinatorUpdateFn)(void *c, float dt);

// The size of a shake, which the shakes' chunk is divided by.
#define CAMERA_SHAKE_SIZE 560u

// bStrICmp, 0x002536a8, as terraintype.c has it: both characters folded,
// sign-extended, before either is tested.
static int32_t to_upper(char c)
{
    int32_t v = (int8_t)c;

    if ((uint32_t)(v - 97) < 26u)
        v &= 0x5f;
    return v;
}

static int32_t str_icmp(const char *a, const char *b)
{
    for (;;) {
        int32_t ca = to_upper(*a++);
        int32_t cb = to_upper(*b++);

        if (ca == 0 || cb == 0 || ca != cb)
            return ca - cb;
    }
}

// A chunk's payload: 16-aligned, past the eight-byte header.
static char *payload(uint8_t *chunk)
{
    return (char *)(((uintptr_t)chunk + 23) & ~(uintptr_t)15);
}

// A mover's deleting destructor, by its table with flags 3.
static void delete_mover(CameraMover *m)
{
    m->vtbl->Destroy(m);
    bFree(m);
}

// ------------------------------------------------------------ the loader

void camera_loader_init(CameraLoader *cl)
{
    // 0x00199c80.
    cl->NumHighlightCameras = 0;
    cl->NumPreRaceCameras = 0;
    cl->NumFlyByCameras = 0;
    cl->NumPostRaceCameras = 0;
    memset(cl->NumPlayerNisCameras, 0, sizeof cl->NumPlayerNisCameras);
    cl->NumNisCameras = 0;
    cl->VortexCount = 0;
    cl->TuningVortex.x = 0.0f;
    cl->TuningVortex.y = 0.0f;
    cl->TuningVortex.z = 0.0f;
}

// Appends each child of `type` in `chunk` to `list`, counting in *count.
static void load_list(uint8_t *chunk, uint32_t type, int32_t *count,
                      char **list)
{
    uint8_t *end = chunk + 8 + bchunk_u32(chunk + 4);
    uint8_t *c;

    for (c = chunk + 8; c < end; c += 8 + bchunk_u32(c + 4)) {
        if (bchunk_u32(c) == type) {
            list[*count] = payload(c);
            (*count)++;
        }
    }
}

int camera_loader_load(CameraLoader *cl, uint8_t *chunk)
{
    // 0x00199cd8.
    uint32_t type = bchunk_u32(chunk);

    if (type == CAMERA_CHUNK_HIGHLIGHTS) {
        uint8_t *end = chunk + 8 + bchunk_u32(chunk + 4);
        uint8_t *c;

        cl->NumHighlightCameras = 0;
        for (c = chunk + 8; c < end; c += 8 + bchunk_u32(c + 4)) {
            uint32_t t = bchunk_u32(c);

            if (t == CAMERA_CHUNK_VORTEX) {
                char *v = payload(c);

                memcpy(&cl->TuningVortex, v, 16);
                memcpy(&cl->VortexCount, v + 16, 4);
            } else if (t == CAMERA_CHUNK_HIGHLIGHT) {
                cl->HighlightCameraData[cl->NumHighlightCameras] =
                    payload(c);
                cl->NumHighlightCameras++;
            }
        }
    } else if (type == CAMERA_CHUNK_FLY_BY) {
        cl->NumFlyByCameras = 0;
        load_list(chunk, CAMERA_CHUNK_FLY_BY_CAMERA, &cl->NumFlyByCameras,
                  cl->FlyByCameraData);
    } else if (type == CAMERA_CHUNK_PRE_RACE) {
        cl->NumPreRaceCameras = 0;
        load_list(chunk, CAMERA_CHUNK_PRE_RACE_CAMERA,
                  &cl->NumPreRaceCameras, cl->PreRaceCameraData);
    } else if (type == CAMERA_CHUNK_POST_RACE) {
        cl->NumPostRaceCameras = 0;
        load_list(chunk, CAMERA_CHUNK_POST_RACE_CAMERA,
                  &cl->NumPostRaceCameras, cl->PostRaceCameraData);
    } else if (type == CAMERA_CHUNK_NIS) {
        load_list(chunk, CAMERA_CHUNK_NIS_CAMERA, &cl->NumNisCameras,
                  cl->NisCameraData);
    } else if (type == CAMERA_CHUNK_SHAKES) {
        cl->Shakes = (CameraShake *)(void *)payload(chunk);
        cl->NumCameraShakes =
            (int32_t)(bchunk_u32(chunk + 4) / CAMERA_SHAKE_SIZE);
    } else {
        return 0;
    }
    mark_camera_data_as_needing_to_be_reloaded();
    return 1;
}

int camera_loader_unload(CameraLoader *cl, uint8_t *chunk)
{
    // 0x0019a010.
    uint32_t type = bchunk_u32(chunk);

    if (type == CAMERA_CHUNK_HIGHLIGHTS) {
        cl->NumHighlightCameras = 0;
    } else if (type == CAMERA_CHUNK_FLY_BY) {
        cl->NumFlyByCameras = 0;
    } else if (type == CAMERA_CHUNK_PRE_RACE) {
        cl->NumPreRaceCameras = 0;
    } else if (type == CAMERA_CHUNK_POST_RACE) {
        cl->NumPostRaceCameras = 0;
    } else if (type == CAMERA_CHUNK_NIS) {
        uint8_t *end = chunk + 8 + bchunk_u32(chunk + 4);
        uint8_t *c;
        int32_t last = -1;
        int32_t found = 0;

        for (c = chunk + 8; c < end; c += 8 + bchunk_u32(c + 4)) {
            char *data;
            int32_t k;

            if (bchunk_u32(c) != CAMERA_CHUNK_NIS_CAMERA)
                continue;
            data = payload(c);
            for (k = 0; k < 2; k++) {
                int32_t i;

                for (i = 0; i < cl->NumPlayerNisCameras[k]; i++) {
                    if (cl->PlayerNisCameraData[k][i] == data) {
                        last = k;
                        found++;
                    }
                }
            }
        }
        if (found > 0)
            cl->NumPlayerNisCameras[last] -= found;
    } else if (type == CAMERA_CHUNK_SHAKES) {
        cl->NumCameraShakes = 0;
    } else {
        return 0;
    }
    return 1;
}

CameraShake *camera_loader_find_random_camera_shake(CameraLoader *cl,
                                                    int32_t bank)
{
    // 0x0019a1b8.
    int32_t n = 0;
    int32_t r;
    int32_t i;

    if (bank == 0)
        return NULL;
    for (i = 0; i < cl->NumCameraShakes; i++)
        if (cl->Shakes[i].BankNumber == bank)
            n++;
    if (n == 0)
        return NULL;
    r = bRandomI(n, &bDefaultSeed);
    for (i = 0; i < cl->NumCameraShakes; i++) {
        if (cl->Shakes[i].BankNumber != bank)
            continue;
        if (r == 0)
            return &cl->Shakes[i];
        r--;
    }
    return NULL;
}

char *camera_loader_find_camera_data(CameraLoader *cl, const char *name)
{
    // 0x0019a280. Each camera is read whole for its name.
    int32_t list;

    for (list = 0; list < 4; list++) {
        char **data;
        int32_t n;
        int32_t i;

        if (list == 0) {
            n = cl->NumHighlightCameras;
            data = cl->HighlightCameraData;
        } else if (list == 1) {
            n = cl->NumFlyByCameras;
            data = cl->FlyByCameraData;
        } else if (list == 2) {
            n = cl->NumPreRaceCameras;
            data = cl->PreRaceCameraData;
        } else {
            n = cl->NumPostRaceCameras;
            data = cl->PostRaceCameraData;
        }
        for (i = 0; i < n; i++) {
            CameraDataItems cd;

            camera_data_items_parse(&cd, data[i]);
            if (str_icmp(cd.Name, name) == 0)
                return data[i];
        }
    }
    return NULL;
}

void camera_loader_keep_nis_cameras(int32_t player)
{
    // 0x0019a3e8.
    CameraLoader *cl = &TheCameraLoader;
    int32_t i;

    cl->NumPlayerNisCameras[player] = cl->NumNisCameras;
    for (i = 0; i < CAMERA_LOADER_NIS; i++)
        cl->PlayerNisCameraData[player][i] = cl->NisCameraData[i];
    cl->NumNisCameras = 0;
}

int loader_cameras(uint8_t *chunk)
{
    // 0x0019a398.
    return camera_loader_load(&TheCameraLoader, chunk);
}

int unloader_cameras(uint8_t *chunk)
{
    // 0x0019a3c0.
    return camera_loader_unload(&TheCameraLoader, chunk);
}

// ---------------------------------------------------- CameraDataItems

// The block's next word, as an int or a float, and the cursor past it.
static int32_t next_int(char **p)
{
    int32_t v;

    memcpy(&v, *p, 4);
    *p += 4;
    return v;
}

static float next_float(char **p)
{
    float v;

    memcpy(&v, *p, 4);
    *p += 4;
    return v;
}

CameraDataItems *camera_data_items_parse(CameraDataItems *cd, char *data)
{
    // 0x0019b6b0.
    char *p = data;

    cd->Type = next_int(&p);
    cd->Name = p;
    p += 32;
    if (cd->Type == 0) {
        cd->SpringXVel = next_float(&p);
        cd->SpringYVel = next_float(&p);
        cd->SpringZVel = next_float(&p);
        cd->SpringDamp = next_float(&p);
        cd->SpringConst = next_float(&p);
        cd->LookOffsetX = next_float(&p);
        cd->LookOffsetY = next_float(&p);
        cd->LookOffsetZ = next_float(&p);
        cd->EnterVertComp = next_float(&p);
        cd->EnterHorizComp = next_float(&p);
        cd->LeaveVertComp = next_float(&p);
        cd->LeaveHorizComp = next_float(&p);
        cd->IsLeaveSet = next_int(&p);
        cd->EyeSplineSpeed = next_float(&p);
        cd->LockEyeSpeedToCar = next_int(&p);
        cd->MinAreaPercent = next_float(&p);
        cd->MaxAreaPercent = next_float(&p);
        cd->IsFOVIso = next_int(&p);
        cd->MinPercent = next_float(&p);
        cd->MaxPercent = next_float(&p);
        cd->NumAreaVerts = next_int(&p);
        cd->NumAreaFaces = next_int(&p);
        cd->NumEyeVerts = next_int(&p);
        cd->WipeDistance = next_float(&p);
        cd->WipeAutoDisable = next_int(&p);
        cd->NearClip = next_float(&p);
        cd->FarClip = next_float(&p);
        cd->Backwards = next_int(&p);
        cd->ShakeBankNumber = next_int(&p);
        p += 8;
        cd->LookVerts = NULL;
        cd->LookSplineSpeed = 0.0f;
        cd->NumLookVerts = 0;
        cd->LockLookSpeedToCar = 0;
        cd->FOVTable = (bVector3 *)(void *)p;
        p += 512;
        cd->EyeVerts = (bVector3 *)(void *)p;
        p += cd->NumEyeVerts * 16;
        cd->BankVerts = (bVector3 *)(void *)p;
        p += cd->NumEyeVerts * 16;
        cd->AreaFaces = p;
        p += cd->NumAreaFaces * 16;
        cd->AreaVerts = (bVector2 *)(void *)p;
    } else if (cd->Type == 1 || cd->Type == 2) {
        cd->EyeSplineSpeed = next_float(&p);
        cd->LookSplineSpeed = next_float(&p);
        if (cd->Type == 2)
            cd->FOVSplineSpeed = next_float(&p);
        cd->LockEyeSpeedToCar = next_int(&p);
        cd->LockLookSpeedToCar = next_int(&p);
        cd->MinAreaPercent = next_float(&p);
        cd->MaxAreaPercent = next_float(&p);
        cd->IsFOVIso = next_int(&p);
        cd->MinPercent = next_float(&p);
        cd->MaxPercent = next_float(&p);
        cd->NumAreaVerts = next_int(&p);
        cd->NumAreaFaces = next_int(&p);
        cd->NumEyeVerts = next_int(&p);
        cd->NumLookVerts = next_int(&p);
        cd->NearClip = next_float(&p);
        cd->FarClip = next_float(&p);
        cd->Backwards = next_int(&p);
        p += cd->Type == 1 ? 12 : 8;
        cd->FOVTable = (bVector3 *)(void *)p;
        p += 512;
        cd->EyeVerts = (bVector3 *)(void *)p;
        p += cd->NumEyeVerts * 16;
        cd->BankVerts = (bVector3 *)(void *)p;
        p += cd->NumEyeVerts * 16;
        cd->LookVerts = (bVector3 *)(void *)p;
        p += cd->NumLookVerts * 16;
        cd->AreaFaces = p;
        p += cd->NumAreaFaces * 16;
        cd->AreaVerts = (bVector2 *)(void *)p;
        cd->SpringXVel = 0.0f;
        cd->SpringYVel = 0.0f;
        cd->SpringZVel = 0.0f;
        cd->SpringDamp = 0.0f;
        cd->SpringConst = 0.0f;
        cd->ShakeBankNumber = 0;
    }
    return cd;
}

// ------------------------------------------------------- the coordinators

void cameracoord_static_init(void)
{
    // 0x00192398 in the demo, retail's 0x0019c058.
    CameraCoordinatorList.next = &CameraCoordinatorList;
    CameraCoordinatorList.prev = &CameraCoordinatorList;
    camera_loader_init(&TheCameraLoader);
}

BaseCameraCoordinator *camera_coordinator_init(BaseCameraCoordinator *c,
                                               int32_t viewID)
{
    // 0x00199a98.
    bNode *tail = CameraCoordinatorList.prev;

    tail->next = &c->Node;
    CameraCoordinatorList.prev = &c->Node;
    c->_vtable = BASECAMERACOORDINATOR_VTABLE;
    c->ViewID = viewID;
    c->Node.prev = tail;
    c->Node.next = &CameraCoordinatorList;
    c->pCameraMover = NULL;
    c->NeedToReloadCameraData = 0;
    c->Disabled = 0;
    return c;
}

void camera_coordinator_destroy(BaseCameraCoordinator *c, int32_t flags)
{
    // 0x00199ad8. `j _$_t6bTNode1Z21BaseCameraCoordinator`, bNode's
    // destructor, which is __builtin_delete with bit 0.
    c->_vtable = BASECAMERACOORDINATOR_VTABLE;
    if (c->pCameraMover != NULL)
        delete_mover(c->pCameraMover);
    c->Node.prev->next = c->Node.next;
    c->Node.next->prev = c->Node.prev;
    if (flags & 1)
        bFree(c);
}

void camera_coordinator_delete(void *c)
{
    BaseCameraCoordinator *b = (BaseCameraCoordinator *)c;
    const VtEntry *e = vt_slot(b->_vtable, CAMERACOORDINATOR_VT_DTOR);

    ((CoordinatorDtorFn)e->fn)(vt_this(b, e), 3);
}

void camera_coordinator_disable(void *c)
{
    // 0x00199b48.
    BaseCameraCoordinator *b = (BaseCameraCoordinator *)c;

    if (b->Disabled)
        return;
    b->Disabled = 1;
    if (b->pCameraMover != NULL)
        b->pCameraMover->vtbl->Disable(b->pCameraMover);
}

void camera_coordinator_enable(void *c)
{
    // 0x00199b90.
    BaseCameraCoordinator *b = (BaseCameraCoordinator *)c;

    if (!b->Disabled)
        return;
    b->Disabled = 0;
    if (b->pCameraMover != NULL)
        b->pCameraMover->vtbl->Enable(b->pCameraMover);
}

void mark_camera_data_as_needing_to_be_reloaded(void)
{
    // 0x00199c40.
    bNode *n;

    for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList;
         n = n->next)
        ((BaseCameraCoordinator *)(void *)n)->NeedToReloadCameraData = 1;
}

void update_camera_coordinators(float dt)
{
    // 0x00199bd0.
    bNode *n;

    for (n = CameraCoordinatorList.next; n != &CameraCoordinatorList;
         n = n->next) {
        BaseCameraCoordinator *c = (BaseCameraCoordinator *)(void *)n;

        if (!c->Disabled) {
            const VtEntry *e = vt_slot(c->_vtable,
                                       CAMERACOORDINATOR_VT_UPDATE);

            ((CoordinatorUpdateFn)e->fn)(vt_this(c, e), dt);
        }
    }
}

// ------------------------------------------------------------ the countdown

CountdownCameraCoordinator *countdown_camera_coordinator_init(
    CountdownCameraCoordinator *c, int32_t viewID, struct Player *p)
{
    // 0x0019b130.
    camera_coordinator_init(&c->Base, viewID);
    c->pPlayer = p;
    c->Base._vtable = COUNTDOWNCAMERACOORDINATOR_VTABLE;
    c->CurrentCountdownNumber = -1;
    countdown_camera_coordinator_update(c, 0.0f);
    return c;
}

CountdownCameraCoordinator *countdown_camera_coordinator_construct(
    void *mem, int32_t viewID, struct Player *p)
{
    return countdown_camera_coordinator_init(
        (CountdownCameraCoordinator *)mem, viewID, p);
}

void countdown_camera_coordinator_destroy(CountdownCameraCoordinator *c,
                                          int32_t flags)
{
    // 0x0019b188.
    c->Base._vtable = COUNTDOWNCAMERACOORDINATOR_VTABLE;
    camera_coordinator_destroy(&c->Base, flags);
}

void countdown_camera_coordinator_update(CountdownCameraCoordinator *c,
                                         float dt)
{
    // 0x0019b1a0.
    int32_t n = race_get_countdown_number_to_display(pCurrentRace);
    char name[32];
    char *data;

    (void)dt;
    if (n == c->CurrentCountdownNumber)
        return;
    if (c->Base.pCameraMover != NULL) {
        delete_mover(c->Base.pCameraMover);
        c->Base.pCameraMover = NULL;
    }
    b_snprintf(name, sizeof name, "COUNTDOWN_%d", (int)n);
    data = camera_loader_find_camera_data(&TheCameraLoader, name);
    if (data != NULL && gBumperCameraMoverFn != NULL) {
        CameraDataItems cd;
        void *mem;

        camera_data_items_parse(&cd, data);
        mem = bMalloc(1116, "BumperCameraMover", 0, 16);
        c->Base.pCameraMover = gBumperCameraMoverFn(
            mem, c->Base.ViewID, c->pPlayer->MyCar, &cd);
    }
    c->CurrentCountdownNumber = n;
}

// ------------------------------------------------------------ the fly-by

FlyByCameraCoordinator *flyby_camera_coordinator_init(
    FlyByCameraCoordinator *c, int32_t viewID)
{
    // 0x0019abd8.
    camera_coordinator_init(&c->Base, viewID);
    c->Base._vtable = FLYBYCAMERACOORDINATOR_VTABLE;
    c->CurrVortexCount = TheCameraLoader.VortexCount;
    c->CurrentlyActiveCameraData = -1;
    c->FlyByCameraIndex = 0;
    return c;
}

void *flyby_camera_coordinator_construct(void *mem, int32_t viewID)
{
    return flyby_camera_coordinator_init((FlyByCameraCoordinator *)mem,
                                         viewID);
}

void flyby_camera_coordinator_destroy(FlyByCameraCoordinator *c,
                                      int32_t flags)
{
    // 0x0019ac28.
    c->Base._vtable = FLYBYCAMERACOORDINATOR_VTABLE;
    camera_coordinator_destroy(&c->Base, flags);
}

int32_t flyby_camera_coordinator_is_finished(void *c)
{
    // 0x0019ac40.
    (void)c;
    return TheCameraLoader.NumFlyByCameras == 0;
}

void flyby_camera_coordinator_update(FlyByCameraCoordinator *c, float dt)
{
    // 0x0019ac50.
    int32_t viewID = c->Base.ViewID;
    CameraMover *m;
    CameraDataItems cd;
    int32_t idx;
    int need;

    (void)dt;
    if (c->CurrentlyActiveCameraData == -1
        || c->Base.NeedToReloadCameraData != 0) {
        need = 1;
        c->Base.NeedToReloadCameraData = 0;
    } else {
        m = c->Base.pCameraMover;
        if (m == NULL || m->Type != CM_TRACK_FLY)
            need = 1;
        else
            need = gTrackFlyCameraMoverIsFinishedFn == NULL
                   || gTrackFlyCameraMoverIsFinishedFn(m) != 0;
    }
    if (!need)
        return;

    idx = c->FlyByCameraIndex;
    if (!(idx < TheCameraLoader.NumFlyByCameras)) {
        c->FlyByCameraIndex = 0;
        idx = 0;
    }
    c->CurrVortexCount++;
    camera_data_items_parse(&cd, TheCameraLoader.FlyByCameraData[idx]);
    if (c->Base.pCameraMover != NULL) {
        delete_mover(c->Base.pCameraMover);
        c->Base.pCameraMover = NULL;
    }
    if (gTrackFlyCameraMoverFn != NULL) {
        void *mem = bMalloc(412, "TrackFlyCameraMover", 0, 16);

        c->Base.pCameraMover = gTrackFlyCameraMoverFn(mem, viewID, &cd, NULL);
    }
    idx = c->FlyByCameraIndex;
    c->CurrentlyActiveCameraData = idx;
    c->FlyByCameraIndex = idx + 1;
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$21BaseCameraCoordinator, 0x002b52f8: Update is the pure virtual.
static const VtEntry base_vt[CAMERACOORDINATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(camera_coordinator_destroy),                    //   8  0x00199ad8
    { 0, 0, NULL },                                   //  16  0x002a0550
};

// _vt$26CountdownCameraCoordinator, 0x002b5298.
static const VtEntry countdown_vt[CAMERACOORDINATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(countdown_camera_coordinator_destroy),          //   8  0x0019b188
    E(countdown_camera_coordinator_update),           //  16  0x0019b1a0
};

// _vt$22FlyByCameraCoordinator, 0x002b52c8.
static const VtEntry flyby_vt[CAMERACOORDINATOR_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(flyby_camera_coordinator_destroy),              //   8  0x0019ac28
    E(flyby_camera_coordinator_update),               //  16  0x0019ac50
};

#undef E

void cameracoord_install_vtables(void)
{
    vt_install(BASECAMERACOORDINATOR_VTABLE, base_vt,
               CAMERACOORDINATOR_VT_ENTRIES);
    vt_install(COUNTDOWNCAMERACOORDINATOR_VTABLE, countdown_vt,
               CAMERACOORDINATOR_VT_ENTRIES);
    vt_install(FLYBYCAMERACOORDINATOR_VTABLE, flyby_vt,
               CAMERACOORDINATOR_VT_ENTRIES);
}
