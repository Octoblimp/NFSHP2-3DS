// cartriggereffect -- retail's Car::TriggerEffect (TASKS 60). See
// cartriggereffect.h; the write-up is docs/formats/car-effects.md, the
// cross-check tools/cartriggereffect_check.py.

#include <stddef.h>
#include <stdint.h>

#include "acidsys.h"
#include "bmatrix.h"
#include "carrenderinfo.h"
#include "cartriggereffect.h"
#include "collision.h"
#include "emath.h"
#include "terraineffect.h"

void car_trigger_effect(Car *c, CarEffect effect, float scale,
                        int32_t where, bVector3 *vel)
{
    CarRenderInfo  *ri = c->pRenderInfo;
    bNode          *list;
    bNode          *n;
    const bVector3 *origin;
    int32_t         wheel;
    bMatrix4        body;

    if (ri == NULL || scale == 0.0f || effect == CARFX_NONE
        || c->TheOverrideRenderingPosition.OverrideViewBits != 0)
        return;
    list = &ri->EmitterList[effect];
    if ((uint32_t)(effect - 1) < 5 && pTerrainEffectEmitters != NULL)
        list = &((TerrainEffectEmitters *)pTerrainEffectEmitters)
                    ->Lists[effect - 1][where & 0xffff];
    wheel = 0;
    if ((uint32_t)(effect - CARFX_SKID_SMOKE) < 2 || effect == CARFX_BLOWN_TIRE
        || effect == CARFX_DRIVE_ON_FLAT_TIRE)
        wheel = where >> 16;
    origin = wheel >= 1 && wheel < 9 ? &c->State.Position
                                     : &c->State.GeometryPosition;
    if (vel == NULL)
        vel = &c->State.Velocity;
    body      = c->State.BodyMatrix;
    body.v3.x = origin->x;
    body.v3.y = origin->y;
    body.v3.z = origin->z;
    body.v3.w = 1.0f;

    for (n = list->next; n != list; n = n->next) {
        AcidEmitter *e     = (AcidEmitter *)n;
        bMatrix4     saved = e->LocalWorld;
        bSList      *places;
        bSNode      *p;

        places = wheel != 0
                     ? &ri->EmitterPositionList[wheel]
                     : &ri->EmitterPositionList[e->EmitterData->CarPosition];
        for (p = places->Head; p != (bSNode *)places; p = p->next) {
            const CarEmitterPosition *at = (const CarEmitterPosition *)p;
            bMatrix4                  world;

            // The place goes into the copy, not a fresh matrix, and stays
            // there: the copy put back below keeps the last place.
            saved.v3.x = at->X;
            saved.v3.y = at->Y;
            saved.v3.z = at->Z;
            saved.v3.w = 1.0f;
            eMulMatrix(&world, &saved, &body);
            e->LocalWorld        = world;
            e->InheritVelocity.x = vel->x;
            e->InheritVelocity.y = vel->y;
            e->InheritVelocity.z = vel->z;
            e->InheritVelocity.w = 0.0f;
            acid_system_trigger_emitter(&WorldEffects, e, -scale, c);
        }
        e->LocalWorld = saved;
    }
}
