// emodel -- see emodel.h.

#include "emodel.h"

#include <stddef.h>

#include "bslotpool.h"
#include "esolid.h"

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

        r->pTextureInfo = get_texture_info(r->NewNameHash, 1);
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
