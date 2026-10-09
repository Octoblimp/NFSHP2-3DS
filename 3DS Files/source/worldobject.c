// worldobject -- see worldobject.h.

#include "worldobject.h"

#include <stdio.h>
#include <stdlib.h>

#include "scenery.h"

bNode      WorldObjectList = { &WorldObjectList, &WorldObjectList };
BSlotPool *WorldObjectSlotPool;

static void model_init(eModel *m, uint32_t name_hash)
{
    if (gEModelInitFn == NULL) {
        fprintf(stderr, "eModel::Init reached with no seam set\n");
        abort();
    }
    gEModelInitFn(m, name_hash);
}

static void model_destroy(eModel *m, int32_t flags)
{
    if (gEModelDestroyFn == NULL) {
        fprintf(stderr, "~eModel reached with no seam set\n");
        abort();
    }
    gEModelDestroyFn(m, flags);
}

// The model's two stores come before Init, the second in its delay slot;
// pModel is stored after. The tail link is the image's order: the old
// tail's next, the list's prev, then the object's own two.
WorldObject *worldobject_construct(WorldObject *o, uint32_t name_hash,
                                   const bMatrix4 *matrix,
                                   int32_t add_lighting)
{
    eModel *m = (eModel *)bSlotOMalloc(eModelSlotPool);
    bNode  *tail;

    m->NameHash = 0;
    m->Solid = NULL;
    model_init(m, name_hash);
    o->pModel = m;
    if (matrix != NULL) {
        o->Matrix = *matrix;
        o->Enabled = 1;
    } else {
        o->Enabled = 0;
    }
    o->AddLighting = add_lighting;
    tail = WorldObjectList.prev;
    tail->next = &o->Node;
    WorldObjectList.prev = &o->Node;
    o->Node.prev = tail;
    o->Node.next = &WorldObjectList;
    return o;
}

void worldobject_destruct(WorldObject *o, int32_t flags)
{
    bNode *next, *prev;

    if (o->pModel != NULL)
        model_destroy((eModel *)o->pModel, 3);
    next = o->Node.next;
    prev = o->Node.prev;
    prev->next = next;
    next->prev = prev;
    if (flags & 1)
        bSlotFree(WorldObjectSlotPool, o);
}

void init_world_objects(void)
{
    WorldObjectSlotPool = bNewSlotPool((int)sizeof(WorldObject), 128,
                                       "WorldObjectSlotPool", 16);
}

void close_world_objects(void)
{
    while (WorldObjectList.next != &WorldObjectList)
        worldobject_destruct((WorldObject *)(void *)WorldObjectList.next, 3);
    bDeleteSlotPool(WorldObjectSlotPool);
    WorldObjectSlotPool = NULL;
}
