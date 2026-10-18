// terraineffect -- retail's TerrainEffectEmitters (TASKS 60). See
// terraineffect.h; the write-up is docs/formats/car-effects.md, the
// cross-check tools/cartriggereffect_check.py.

#include <stddef.h>
#include <stdint.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bmatrix.h"
#include "bmem.h"
#include "collision.h"
#include "terraineffect.h"

// Where each effect's group name is in a TerrainTypeInfo: the
// constructor's jump table (0x002bcce0).
static const char *group_name(const TerrainTypeInfo *info, int32_t effect)
{
    switch (effect) {
    case 0: return info->DriveOverEmitterGroup;
    case 1: return info->DriveOver2EmitterGroup;
    case 2: return info->SkidSmokeEmitterGroup;
    case 3: return info->TireSpewEmitterGroup;
    case 4: return info->BottomOutEmitterGroup;
    case 5: return info->CollisionImpactEmitterGroup;
    case 6: return info->CollisionScrapeEmitterGroup;
    }
    return NULL;
}

TerrainEffectEmitters *terrain_effect_emitters_construct(
    TerrainEffectEmitters *t)
{
    int32_t effect, terrain;

    for (effect = 0; effect < NUM_TERRAIN_EFFECTS; effect++) {
        for (terrain = 0; terrain < NUM_TERRAIN_TYPES; terrain++) {
            bNode *list = &t->Lists[effect][terrain];

            list->next = list;
            list->prev = list;
        }
    }
    // Terrain-major: a terrain's seven groups, then the next terrain's.
    for (terrain = 0; terrain < NUM_TERRAIN_TYPES; terrain++) {
        const TerrainTypeInfo *info = &TerrainTypeInfoTable[terrain];

        for (effect = 0; effect < NUM_TERRAIN_EFFECTS; effect++) {
            const char *name = group_name(info, effect);

            if (name == NULL || name[0] == '\0')
                continue;
            afx_get_emitters(&t->Lists[effect][terrain], bchunk_hash(name));
        }
    }
    return t;
}

void terrain_effect_emitters_destroy(TerrainEffectEmitters *t,
                                     int32_t flags)
{
    if (t != NULL) {
        bNode *list = &t->Lists[0][0] + NUM_TERRAIN_EFFECTS * NUM_TERRAIN_TYPES;

        // ~bTList<AcidEmitter>(list, 0) on each, the last list first.
        while (list != &t->Lists[0][0]) {
            bNode *n;

            list--;
            for (n = list->next; n != list; n = list->next) {
                n->prev->next = n->next;
                n->next->prev = n->prev;
                acid_emitter_delete((AcidEmitter *)n, 3);
            }
        }
    }
    // __builtin_delete, which is bFree, with no test of the pointer.
    if ((flags & 1) != 0)
        bFree(t);
}

void terrain_effect_emitters_trigger(TerrainEffectEmitters *t,
                                     int32_t effect, int32_t terrain,
                                     float scale, const bVector3 *at,
                                     const bVector3 *velocity)
{
    bNode    *list = &t->Lists[effect][terrain];
    bNode    *n;
    bMatrix4  m;

    if (list->next == list)
        return;
    bIdentity(&m);
    m.v3.x = at->x;
    m.v3.y = at->y;
    m.v3.z = at->z;
    m.v3.w = 1.0f;
    for (n = list->next; n != list; n = n->next) {
        AcidEmitter *e = (AcidEmitter *)n;

        e->LocalWorld        = m;
        e->InheritVelocity.x = velocity->x;
        e->InheritVelocity.y = velocity->y;
        e->InheritVelocity.z = velocity->z;
        e->InheritVelocity.w = 0.0f;
        acid_system_trigger_emitter(&WorldEffects, e, -scale, NULL);
    }
}

void init_terrain_effect_emitters(void)
{
    if (pTerrainEffectEmitters == NULL)
        pTerrainEffectEmitters = terrain_effect_emitters_construct(
            (TerrainEffectEmitters *)bMalloc(
                (int)sizeof(TerrainEffectEmitters), "TerrainEffectEmitters",
                0, 16));
}

void close_terrain_effect_emitters(void)
{
    if (pTerrainEffectEmitters != NULL) {
        terrain_effect_emitters_destroy(
            (TerrainEffectEmitters *)pTerrainEffectEmitters, 3);
        pTerrainEffectEmitters = NULL;
    }
}
