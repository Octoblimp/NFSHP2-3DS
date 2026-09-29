// rendercars -- RenderCars and the two Car helpers only it calls: see
// carrenderinfo.h.

#include "carrenderinfo.h"

#include <math.h>

#include "camera.h"
#include "emath.h"
#include "eview.h"
#include "player.h"
#include "realtime.h"
#include "world.h"

void (*gCarDamageAboveFn)(Car *c, bVector3 *eye, bVector3 *direction);

// srav: the shift is the ID's low five bits.
static uint32_t view_bit(uint32_t bits, int32_t view_id)
{
    return (bits >> ((uint32_t)view_id & 31u)) & 1u;
}

int32_t car_is_blinking_in_view(Car *c, int32_t view_id)
{
    const OverrideRenderingPosition *o = &c->TheOverrideRenderingPosition;

    if (view_bit(o->OverrideViewBits, view_id))
        return 0;
    if (car_is_blinking(c))
        return 1;
    return view_bit(o->BlinkingViewBits, view_id) ? 1 : 0;
}

void car_get_render_wheel_matrices(Car *c, bMatrix4 *tires,
                                   bMatrix4 *brakes, int32_t view_id)
{
    int32_t i;

    if (view_bit(c->TheOverrideRenderingPosition.OverrideViewBits, view_id)) {
        for (i = 0; i < 4; i++) {
            const WheelInfo *w;

            eIdentity(&tires[i]);
            eIdentity(&brakes[i]);
            // The wheel's first quadword, Radius and all, then w = 1.
            w = &c->pCarTypeInfo->Wheels[i];
            tires[i].v3.x = w->PositionX;
            tires[i].v3.y = w->PositionY;
            tires[i].v3.z = w->PositionZ;
            tires[i].v3.w = 1.0f;
            brakes[i].v3.x = w->PositionX;
            brakes[i].v3.y = w->PositionY;
            brakes[i].v3.z = w->PositionZ;
            brakes[i].v3.w = 1.0f;
        }
        return;
    }
    for (i = 0; i < 4; i++) {
        tires[i] = c->State.WheelMatrix[i];
        brakes[i] = c->State.BrakeMatrix[i];
    }
}

// The view's player -- the first of pPlayersByIndex whose ViewID it is --
// in the jump cam or just after it.
static int view_in_jump_cam(const eView *view)
{
    Player *p = PlayerPlayersByIndex[0];

    if (p == NULL)
        return 0;
    if (view->ID != p->ViewID) {
        p = PlayerPlayersByIndex[1];
        if (p == NULL || view->ID != p->ViewID)
            return 0;
    }
    return p->nZoneCurrent == PLAYER_ZONE_JUMP_CAM
        || p->nZoneCurrent == PLAYER_ZONE_AFTER_JUMP;
}

void render_cars(eView *view)
{
    Camera *camera;
    Car *car, *hidden;
    int32_t left = 99;

    if (pCurrentWorld == NULL)
        return;
    camera = view->pCamera;
    hidden = (Car *)camera->CarNotToRender;

    // Retail reads pCurrentWorld again for every test, after whatever the
    // car's calls did. CarList is the World's first field.
    for (car = (Car *)pCurrentWorld->CarList.next;
         car != (Car *)&pCurrentWorld->CarList;
         car = (Car *)car->Link.next) {
        OverrideRenderingPosition *o = &car->TheOverrideRenderingPosition;
        bMatrix4 tires[4], brakes[4];
        int32_t draw, over;

        if (car == hidden || left <= 0 || !car->RenderingEnabled)
            continue;
        // xori: IsPoofed's word with its low bit flipped.
        draw = car_is_poofed(car) ^ 1;
        // A blinking car shows on odd frames, unless the world is paused.
        if (car_is_blinking_in_view(car, view->ID)
            && !(fabsf(WorldTimeElapsed) <= 0.001f))
            draw = (int32_t)(eFrameCounter & 1u);
        if (!view_bit(o->VisibleViewBits, view->ID))
            draw = 0;
        if (!draw)
            continue;

        left--;
        car_get_render_wheel_matrices(car, tires, brakes, view->ID);
        over = (int32_t)view_bit(o->OverrideViewBits, view->ID);
        carrenderinfo_render(car->pRenderInfo, view,
                             over ? &o->GeometryPosition
                                  : &car->State.GeometryPosition,
                             over ? &o->BodyMatrix : &car->State.BodyMatrix,
                             tires, brakes, 0, 0);
        if (!view_in_jump_cam(view) && gCarDamageAboveFn != NULL)
            gCarDamageAboveFn(car, &camera->CurrentKey.Position,
                              &camera->CurrentKey.Direction);
    }
}
