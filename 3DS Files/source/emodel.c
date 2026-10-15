// emodel -- see emodel.h.

#include "emodel.h"

#include <stddef.h>

#include "bmath.h"
#include "bslotpool.h"
#include "esolid.h"

// eSolid's Flags bit 0x20, retail's alone and named by the port: the
// eSolidFlags enum ends at 0x10 in the demo's stab. Retail's discs set it
// only with ESOLID_VERTEX_ANIMATION, on the 90 frames of TRACKB61..66's
// waving flag, and ReconnectSolid is its one reader.
#define SOLID_RANDOM_START  0x0020u

void *eFindSolid(uint32_t name_hash)
{
    bNode *n;

    for (n = SolidList.next; n != &SolidList; n = n->next) {
        if (((eSolid *)(void *)n)->NameHash == name_hash)
            return n;
    }
    return NULL;
}

void emodel_reconnect_solid(eModel *m)
{
    eSolid *solid;

    if (m->NameHash == 0)
        return;
    solid = (eSolid *)eFindSolid(m->NameHash);
    if (solid == m->Solid)
        return;
    m->Solid = solid;
    // The store is in the branch's delay slot, so it happens for a NULL
    // solid as well.
    m->RigidAnimationStartTime = 0;
    if (solid == NULL)
        return;
    if (solid->pRigidAnimation == NULL)
        return;
    if ((int8_t)solid->pRigidAnimation[2] != 0)
        return;
    m->RigidAnimationStartTime = (int16_t)0xc000;
    // Retail's: a solid so flagged starts at one of 256 times, drawn from
    // the default seed, so that its copies do not move as one (the view
    // seed in a wireless race: bmath.h).
    if (!(solid->Flags & SOLID_RANDOM_START))
        return;
    m->RigidAnimationStartTime = (int16_t)(
        (uint16_t)m->RigidAnimationStartTime
        | (uint16_t)bRandomI(256, bViewSeed));
}

void emodel_reconnect_texture_table(eModel *m)
{
    int i;

    for (i = 0; i < (int8_t)m->NumReplacementTextures; i++) {
        eReplacementTextureTable *r =
            (eReplacementTextureTable *)m->pReplacementTextureTable + i;
        int8_t *slot =
            &r->ReplaceIndex[(int8_t)m->ReplacementTextureInstanceIndex];
        eSolid *s;
        int k;

        r->pTextureInfo = get_texture_info(r->NewNameHash, 1, 0);
        *slot = -1;
        s = (eSolid *)m->Solid;
        if (s == NULL)
            continue;
        for (k = 0; k < s->NumTextureTableEntries; k++) {
            if (((eTextureTable *)s->pTextureTable)[k].NameHash
                == r->OldNameHash) {
                *slot = (int8_t)k;
                break;
            }
        }
    }
    emodel_apply_replacement_texture_table(m);
}

void emodel_apply_replacement_texture_table(eModel *m)
{
    eSolid *s = (eSolid *)m->Solid;
    eTextureTable *table;
    eReplacementTextureTable *r;
    int i;

    if (s == NULL)
        return;
    table = (eTextureTable *)s->pTextureTable;
    r = (eReplacementTextureTable *)m->pReplacementTextureTable;
    for (i = 0; i < (int8_t)m->NumReplacementTextures; i++) {
        int k = r[i].ReplaceIndex[(int8_t)m->ReplacementTextureInstanceIndex];

        if (k >= 0)
            table[k].pTextureInfo = r[i].pTextureInfo;
    }
}

void emodel_attach_replacement_texture_table(eModel *m,
                                             eReplacementTextureTable *t,
                                             int32_t count, int32_t instance)
{
    m->pReplacementTextureTable = t;
    m->NumReplacementTextures = (uint8_t)count;
    m->ReplacementTextureInstanceIndex = (uint8_t)instance;
    emodel_reconnect_texture_table(m);
    if (m->Solid == NULL)
        return;
    // Reconnecting has applied it already; this is the image's second go.
    emodel_apply_replacement_texture_table(m);
    if (gFixStripSTsFn != NULL)
        gFixStripSTsFn((eSolid *)m->Solid);
}

int32_t emodel_rename_texture(eModel *m, uint32_t old_hash,
                              uint32_t new_hash)
{
    eSolid *s = (eSolid *)m->Solid;
    eTextureTable *table;
    int k;

    if (s == NULL)
        return 0;
    table = (eTextureTable *)s->pTextureTable;
    for (k = 0; k < s->NumTextureTableEntries; k++) {
        if (table[k].NameHash == old_hash) {
            table[k].NameHash = new_hash;
            table[k].pTextureInfo = get_texture_info(new_hash, 1, 0);
            return 1;
        }
    }
    return 0;
}

void esolid_replace_light_material(eSolid *s, uint32_t old_hash,
                                   void *material)
{
    eLightMaterialEntry *e = (eLightMaterialEntry *)s->LightMaterialTable;
    int n;

    for (n = s->NumLightMaterials; n > 0; n--, e++) {
        if (e->NameHash == old_hash)
            e->LightMaterial = material;
    }
}

void emodel_replace_light_material(eModel *m, uint32_t old_hash,
                                   uint32_t new_hash)
{
    eSolid *s = (eSolid *)m->Solid;

    if (s == NULL)
        return;
    esolid_replace_light_material(s, old_hash, get_light_material(new_hash));
}

void emodel_set_environment_mapping(eModel *m, uint32_t hash, int32_t on)
{
    if (m->Solid != NULL)
        esolid_set_environment_mapping((eSolid *)m->Solid, hash, on);
}

void emodel_get_bounding_box(const eModel *m, bVector3 *mn, bVector3 *mx)
{
    const eSolid *s = (const eSolid *)m->Solid;

    if (s == NULL)
        return;
    mn->x = s->AABBMin.x;
    mn->y = s->AABBMin.y;
    mn->z = s->AABBMin.z;
    mx->x = s->AABBMax.x;
    mx->y = s->AABBMax.y;
    mx->z = s->AABBMax.z;
}

void emodel_reconnect_all_models(void)
{
    bNode *n;

    for (n = ModelList.next; n != &ModelList; n = n->next) {
        eModel *m = (eModel *)(void *)n;

        emodel_reconnect_solid(m);
        emodel_reconnect_texture_table(m);
        if (m->Solid != NULL && gFixStripSTsFn != NULL)
            gFixStripSTsFn((eSolid *)m->Solid);
    }
}

void emodel_init(eModel *m, uint32_t name_hash)
{
    bNode *last;

    m->NameHash = name_hash;
    m->pReplacementTextureTable = NULL;
    m->NumReplacementTextures = 0;
    m->RigidAnimationStartTime = 0;
    if (name_hash == 0)
        return;
    emodel_reconnect_solid(m);
    last = ModelList.prev;
    last->next = &m->Node;
    ModelList.prev = &m->Node;
    m->Node.next = &ModelList;
    m->Node.prev = last;
}

void emodel_uninit(eModel *m)
{
    bNode *prev, *next;

    if (m->NameHash == 0)
        return;
    prev = m->Node.prev;
    next = m->Node.next;
    m->NumReplacementTextures = 0;
    prev->next = next;
    next->prev = prev;
    m->Solid = NULL;
    m->NameHash = 0;
    m->pReplacementTextureTable = NULL;
    m->RigidAnimationStartTime = 0;
}

void emodel_delete(eModel *m, int32_t flags)
{
    emodel_uninit(m);
    // ~bTNode<eModel> is ~bNode with 0, which deletes nothing.
    if (flags & 1)
        bSlotFree(eModelSlotPool, m);
}

void emodel_init_slot_pool(void)
{
    if (eModelSlotPool != NULL)
        return;
    eModelSlotPool = bNewSlotPool((int)sizeof(eModel), 5000,
                                  "eModelSlotPool", 16);
}
