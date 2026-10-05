// fecar -- see fecar.h.

#include "fecar.h"

#include <stddef.h>

#include "bmem.h"
#include "emath.h"
#include "scenerycull.h"

bNode FrontEndRenderingCarList = { &FrontEndRenderingCarList,
                                   &FrontEndRenderingCarList };

int32_t FrontEndCarForceFlag8;
int32_t FrontEndCarForceFlag16;

// gp-23688 and gp-23680: the levels of detail a car and its tyres draw
// at, by whether it is a reflection.
static const int32_t s_car_lod[2] = { 0, 1 };
static const int32_t s_tire_lod[2] = { 0, 1 };

void fecar_init(FrontEndRenderingCar *f, RideInfo *ride, int32_t view_id)
{
    bNode *tail;
    int i;

    f->Ride.Type = -1;
    f->Ride.CanBeVertexDamaged = 0;
    f->Ride.InstanceIndex = 0;
    f->Ride.SkinNumber = 0;
    f->Ride.HasDash = 0;
    f->pRenderInfo = NULL;
    fecar_reinit(f, ride);
    f->Position.x = 0.0f;
    f->ViewID = view_id;
    f->Position.z = 0.0f;
    f->Position.y = 0.0f;
    eIdentity(&f->BodyMatrix);
    for (i = 0; i < 4; i++)
        eIdentity(&f->TireMatrices[i]);
    for (i = 0; i < 4; i++)
        eIdentity(&f->BrakeMatrices[i]);
    f->Unused632 = 1;
    tail = FrontEndRenderingCarList.prev;
    tail->next = &f->Node;
    FrontEndRenderingCarList.prev = &f->Node;
    f->Node.prev = tail;
    f->Node.next = &FrontEndRenderingCarList;
    f->pModel = NULL;
    f->Enabled = 1;
    f->Reflection = 0;
    f->Headlights = 0;
    f->CopLights = 0;
}

void fecar_reinit(FrontEndRenderingCar *f, RideInfo *ride)
{
    if (f->pRenderInfo != NULL) {
        carrenderinfo_delete(f->pRenderInfo, 3);
        f->pRenderInfo = NULL;
    }
    if (ride != NULL) {
        f->Ride = *ride;
        f->pRenderInfo = carrenderinfo_construct(
            bMalloc(sizeof(CarRenderInfo), "CarRenderInfo", 0, 16),
            &f->Ride, NULL);
    }
}

void fecar_delete(FrontEndRenderingCar *f, int32_t flags)
{
    if (gEWaitUntilRenderingDoneFn != NULL)
        gEWaitUntilRenderingDoneFn();
    if (f->pRenderInfo != NULL) {
        carrenderinfo_delete(f->pRenderInfo, 3);
        f->pRenderInfo = NULL;
    }
    if (f->pModel != NULL) {
        emodel_delete(f->pModel, 3);
        f->pModel = NULL;
    }
    f->Node.prev->next = f->Node.next;
    f->Node.next->prev = f->Node.prev;
    if (flags & 1)
        bFree(f);
}

void render_front_end_car(CarRenderInfo *ri, eView *view,
                          bVector3 *position, bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          int32_t unused, int32_t reflection, uint32_t flags,
                          uint32_t forced_lights)
{
    int32_t car_lod = s_car_lod[reflection];
    int32_t tire_lod = s_tire_lod[reflection];
    int32_t old_car = ForceCarLOD;
    int32_t old_tire = ForceTireLOD;

    (void)unused;
    ForceCarLOD = car_lod;
    ForceTireLOD = tire_lod;
    carrenderinfo_render(ri, view, position, body_matrix, tire_matrices,
                         brake_matrices, flags, forced_lights);
    if (ForceCarLOD == car_lod)
        ForceCarLOD = old_car;
    if (ForceTireLOD == tire_lod)
        ForceTireLOD = old_tire;
}

void render_front_end_cars(eView *view, int32_t cars, int32_t reflections,
                           int32_t pass8, int32_t pass16)
{
    int32_t mode = eGetCurrentViewMode();
    bNode *n;

    for (n = FrontEndRenderingCarList.next; n != &FrontEndRenderingCarList;
         n = n->next) {
        FrontEndRenderingCar *f = (FrontEndRenderingCar *)n;
        CarRenderInfo *ri = f->pRenderInfo;
        bMatrix4 tires[4], brakes[4];
        bVector3 mn = { 0.0f, 0.0f, 0.0f, 0.0f };
        bVector3 mx = { 0.0f, 0.0f, 0.0f, 0.0f };
        bVector3 pos;
        uint32_t flags, forced;
        int i;

        if (ri == NULL || f->Enabled == 0 || f->ViewID != view->ID)
            continue;
        if (f->Reflection) {
            if (mode != 1 || !reflections)
                continue;
            flags = 17;
        } else {
            if (!cars)
                continue;
            flags = 0;
        }
        if (!pass8)
            flags |= 8;
        if (!pass16)
            flags |= 16;
        if (FrontEndCarForceFlag8)
            flags |= 8;
        if (FrontEndCarForceFlag16)
            flags |= 16;
        if (f->pModel != NULL) {
            if (gEModelRenderFn != NULL)
                gEModelRenderFn(f->pModel, &f->BodyMatrix, NULL, flags);
            continue;
        }

        // Retail's box corners are its stack's when the body has no
        // solid; the port's are 0.
        emodel_get_bounding_box(&ri->Body[0], &mn, &mx);
        pos = f->Position;
        pos.x = f->Position.x - (mn.x + (mx.x - mn.x) * 0.5f);
        for (i = 0; i < 4; i++) {
            tires[i] = f->TireMatrices[i];
            brakes[i] = f->BrakeMatrices[i];
        }
        forced = 0;
        if (!f->Reflection) {
            forced = f->Headlights ? 3 : 0;
            if (f->CopLights)
                forced |= 8;
        }
        render_front_end_car(ri, view, &pos, &f->BodyMatrix, tires, brakes,
                             f->Unused632, f->Reflection, flags, forced);
    }
}
