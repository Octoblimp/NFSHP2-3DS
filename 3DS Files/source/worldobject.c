// worldobject -- see worldobject.h.

#include "worldobject.h"

#include <stdio.h>
#include <stdlib.h>

#include "camera.h"
#include "eframe.h"
#include "elight.h"
#include "emath.h"
#include "emodel.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "scenery.h"
#include "scenerycull.h"

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

static void model_render(eModel *m, bMatrix4 *matrix, void *light)
{
    if (gEModelRenderFn == NULL) {
        fprintf(stderr, "eModel::Render reached with no seam set\n");
        abort();
    }
    gEModelRenderFn(m, matrix, light, 0);
}

// eModel::IsVisible(bMatrix4 *), 0x0010cea8, whose one caller so far is
// here.
static int32_t model_is_visible(const eModel *m, const bMatrix4 *matrix)
{
    const eSolid *s = (const eSolid *)m->Solid;
    bMatrix4      clip;

    if (s == NULL)
        return 0;
    eMulMatrix(&clip, matrix, eGetCurrentView()->WorldScreenClipMatrix);
    return scenery_classify_aabb(&s->AABBMin, &s->AABBMax, &clip) != 0;
}

// The model is read again for the draw. The light context's block is
// taken after the matrix's, so it fails alone.
void worldobject_render(WorldObject *o, eView *view)
{
    bMatrix4      *m;
    eLightContext *lc;
    bVector4       eye;
    const Camera  *cam;

    if (eview_get_pixel_size_sphere(
            view, (const bVector3 *)(const void *)&o->Matrix.v3, 20.0f) < 2)
        return;
    if (!model_is_visible((const eModel *)o->pModel, &o->Matrix))
        return;
    m = (bMatrix4 *)eframe_malloc(64);
    if (m == NULL)
        return;
    *m = o->Matrix;
    if (o->AddLighting == 0) {
        model_render((eModel *)o->pModel, m, NULL);
        return;
    }
    lc = (eLightContext *)eframe_malloc(288);
    if (lc == NULL)
        return;
    cam = view->pCamera;
    eye.x = cam->CurrentKey.Position.x;
    eye.y = cam->CurrentKey.Position.y;
    eye.z = cam->CurrentKey.Position.z;
    eye.w = 1.0f;
    el_setup_light_context(lc, m, view->WorldViewMatrix, &eye, view);
    model_render((eModel *)o->pModel, m, lc);
}

void render_world_objects(eView *view)
{
    bNode *n;

    for (n = WorldObjectList.next; n != &WorldObjectList; n = n->next) {
        WorldObject *o = (WorldObject *)(void *)n;

        if (o->Enabled != 0)
            worldobject_render(o, view);
    }
}
