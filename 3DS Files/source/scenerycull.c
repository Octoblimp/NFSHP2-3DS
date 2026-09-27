// scenerycull -- see scenerycull.h.

#include "scenerycull.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "eefpu.h"
#include "eframe.h"
#include "emath.h"
#include "race.h"

SceneryDrawInfo SceneryDrawInfoTable[SCENERY_MAX_DRAW_INFOS];

void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                        uint32_t flags);

static void model_render(eModel *m, bMatrix4 *matrix, void *light,
                         uint32_t flags)
{
    if (gEModelRenderFn == NULL) {
        fprintf(stderr, "eModel::Render reached with no seam set\n");
        abort();
    }
    gEModelRenderFn(m, matrix, light, flags);
}

// ---------------------------------------------------------------- the box

// vclipw.xyz against |w|, strict both ways: +x, -x, +y, -y, +z, -z in
// bits 0 to 5.
static uint32_t clipw(const bVector4 *v)
{
    float lim = fabsf(v->w);
    uint32_t f = 0;

    if (lim < v->x)
        f |= 0x01;
    if (v->x < -lim)
        f |= 0x02;
    if (lim < v->y)
        f |= 0x04;
    if (v->y < -lim)
        f |= 0x08;
    if (lim < v->z)
        f |= 0x10;
    if (v->z < -lim)
        f |= 0x20;
    return f;
}

static void vadd(bVector4 *o, const bVector4 *a, const bVector4 *b)
{
    o->x = a->x + b->x;
    o->y = a->y + b->y;
    o->z = a->z + b->z;
    o->w = a->w + b->w;
}

static void vscale(bVector4 *o, const bVector4 *row, float s)
{
    o->x = row->x * s;
    o->y = row->y * s;
    o->z = row->z * s;
    o->w = row->w * s;
}

// The corners are built from the transformed minimum and the three
// transformed edges, in the listing's order: the four of the bottom face
// (min, +dx, +dx+dy, +dy), then each of them +dz. The two faces are read
// out of the clip register separately, and both must be clear for a 2.
int32_t scenery_classify_aabb(const bVector4 *min, const bVector4 *max,
                              const bMatrix4 *clip)
{
    bVector4 c0, c1, c2, c3, ex, ey, ez;
    float dx = max->x - min->x;
    float dy = max->y - min->y;
    float dz = max->z - min->z;
    uint32_t lo, hi, all;

    c0.x = ((clip->v0.x * min->x + clip->v1.x * min->y)
            + clip->v2.x * min->z) + clip->v3.x;
    c0.y = ((clip->v0.y * min->x + clip->v1.y * min->y)
            + clip->v2.y * min->z) + clip->v3.y;
    c0.z = ((clip->v0.z * min->x + clip->v1.z * min->y)
            + clip->v2.z * min->z) + clip->v3.z;
    c0.w = ((clip->v0.w * min->x + clip->v1.w * min->y)
            + clip->v2.w * min->z) + clip->v3.w;
    vscale(&ex, &clip->v0, dx);
    vscale(&ey, &clip->v1, dy);
    vscale(&ez, &clip->v2, dz);

    vadd(&c1, &c0, &ex);
    vadd(&c2, &c0, &ex);
    vadd(&c2, &c2, &ey);
    vadd(&c3, &c0, &ey);
    lo = (clipw(&c0) << 18) | (clipw(&c1) << 12) | (clipw(&c2) << 6)
         | clipw(&c3);

    vadd(&c0, &c0, &ez);
    vadd(&c1, &c1, &ez);
    vadd(&c2, &c2, &ez);
    vadd(&c3, &c3, &ez);
    hi = (clipw(&c0) << 18) | (clipw(&c1) << 12) | (clipw(&c2) << 6)
         | clipw(&c3);

    if (lo == 0 && hi == 0)
        return 2;
    all = lo & (lo >> 6) & (lo >> 12) & (lo >> 18)
          & hi & (hi >> 6) & (hi >> 12) & (hi >> 18) & 0x3f;
    return all == 0;
}

int32_t scenery_is_bounding_box_visible(const bVector3 *min,
                                        const bVector3 *max,
                                        const bMatrix4 *clip)
{
    // The image hands the two bVector3s on as bVector4s; the pad is w and
    // never read.
    return scenery_classify_aabb((const bVector4 *)(const void *)min,
                                 (const bVector4 *)(const void *)max,
                                 clip) != 0;
}

static int32_t classify_box(const SceneryBoundingBox *b,
                            const SceneryCullInfo *ci)
{
    bVector4 mn, mx;

    mn.x = (float)b->BBoxMin[0];
    mn.y = (float)b->BBoxMin[1];
    mn.z = (float)b->BBoxMin[2];
    mn.w = 0.0f;
    mx.x = (float)b->BBoxMax[0];
    mx.y = (float)b->BBoxMax[1];
    mx.z = (float)b->BBoxMax[2];
    mx.w = 0.0f;
    return scenery_classify_aabb(&mn, &mx, &ci->ClipMatrix);
}

// ---------------------------------------------------------------- a section

int32_t scenery_is_visible(ScenerySectionHeader *h, SceneryCullInfo *ci)
{
    if (h->SceneryTreeNodeTable == NULL)
        return 0;
    return classify_box(&h->SceneryTreeNodeTable[0].BBox, ci) != 0;
}

static void add_draw_info(SceneryCullInfo *ci, eModel *m, int32_t cls,
                          bMatrix4 *matrix)
{
    SceneryDrawInfo *d = ci->pCurrentDrawInfo;

    if ((uintptr_t)d < (uintptr_t)ci->pTopDrawInfo) {
        ci->pCurrentDrawInfo = d + 1;
        d->pMatrix = matrix;
        d->pModel = (eModel *)(void *)((uintptr_t)m + (uint32_t)cls);
    }
}

void scenery_draw_a_scenery(ScenerySectionHeader *h, int32_t index,
                            SceneryCullInfo *ci, int32_t cls)
{
    SceneryInstance *s = &h->pSceneryInstance[index];
    SceneryInfo *info;
    eModel *model;
    bMatrix4 *m;
    float dx, dy, dz, r, dot;
    int32_t size, k, lod;

    if (cls == 1) {
        cls = classify_box(&s->BBox, ci);
        if (cls == 0)
            return;
    }

    info = &h->pSceneryInfo[s->SceneryInfoNumber];
    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & 0xff)
        return;

    // The size on the screen: the radius, 4 m more, at the distance from
    // the camera less the same. Behind the camera by more than that is 0.
    dx = s->Position[0] - ci->Position.x;
    dy = s->Position[1] - ci->Position.y;
    dz = s->Position[2] - ci->Position.z;
    r = info->Radius + 4.0f;
    dot = (dx * ci->Direction.x + dy * ci->Direction.y)
          + dz * ci->Direction.z;
    if (dot < -r) {
        size = 0;
    } else {
        float dist = sqrtf((dx * dx + dy * dy) + dz * dz);
        float f1 = dist - r;
        float f0 = ci->H;

        if (r < f1)
            f0 = r * f0 / f1;
        size = ee_trunc_w(f0);
    }
    if (size < 2)
        return;

    // The first LOD the size reaches that has a model.
    model = NULL;
    lod = -1;
    for (k = 0; k < 3; k++) {
        if (size < info->FarClipSize[k])
            continue;
        if (info->pModel[k] == NULL)
            continue;
        model = info->pModel[k];
        lod = k;
        break;
    }
    if (model == NULL)
        return;

    if (s->ExcludeFlags & SCENERY_DRAW_IN_PLACE) {
        add_draw_info(ci, model, cls, NULL);
        return;
    }

    m = (bMatrix4 *)eframe_malloc(sizeof(bMatrix4));
    if (m == NULL)
        return;

    if (info->IsFacadeFlag[lod] != 0) {
        bVector3 pos;

        pos.x = s->Position[0];
        pos.y = s->Position[1];
        pos.z = s->Position[2];
        pos.pad = 0.0f;
        scenery_create_facade_matrix(m, &pos, &ci->Position);
    } else {
        const float q = 1.0f / 16384.0f;

        m->v0.x = (float)s->Rotation[0] * q;
        m->v0.y = (float)s->Rotation[1] * q;
        m->v0.z = (float)s->Rotation[2] * q;
        m->v0.w = 0.0f;
        m->v1.x = (float)s->Rotation[3] * q;
        m->v1.y = (float)s->Rotation[4] * q;
        m->v1.z = (float)s->Rotation[5] * q;
        m->v1.w = 0.0f;
        m->v2.x = (float)s->Rotation[6] * q;
        m->v2.y = (float)s->Rotation[7] * q;
        m->v2.z = (float)s->Rotation[8] * q;
        m->v2.w = 0.0f;
    }
    m->v3.x = s->Position[0];
    m->v3.y = s->Position[1];
    m->v3.z = s->Position[2];
    m->v3.w = 1.0f;
    if ((int32_t)s->ExcludeFlags & ci->ExcludeFlags & SCENERY_RAISE_2M)
        m->v3.z = m->v3.z + 2.0f;

    add_draw_info(ci, model, cls, m);
}

void scenery_cull_brute_force(ScenerySectionHeader *h, SceneryCullInfo *ci)
{
    int32_t i;

    if (!scenery_is_visible(h, ci))
        return;
    for (i = 0; i < h->NumSceneryInstances; i++)
        scenery_draw_a_scenery(h, i, ci, 1);
}

// A node's child codes, read from the node's base: a count past five
// reads on into the next node, as the image does.
static int16_t child_code(const SceneryTreeNode *n, int32_t i)
{
    const int16_t *codes = (const int16_t *)(const void *)
        ((const uint8_t *)n + offsetof(SceneryTreeNode, ChildCodes));

    return codes[i];
}

static SceneryTreeNode *child_node(ScenerySectionHeader *h, int16_t code)
{
    int16_t i = (int16_t)(-(int32_t)code);

    return (SceneryTreeNode *)(void *)
        ((uint8_t *)h->SceneryTreeNodeTable
         + (intptr_t)i * (intptr_t)sizeof(SceneryTreeNode));
}

#define TREE_STACK 64

void scenery_tree_cull(ScenerySectionHeader *h, SceneryCullInfo *ci)
{
    SceneryTreeNode *nodes[TREE_STACK];
    uint8_t classes[TREE_STACK];
    int32_t top = 1;

    nodes[0] = h->SceneryTreeNodeTable;
    classes[0] = 1;
    do {
        SceneryTreeNode *n;
        uint32_t cls;
        int32_t i;

        top--;
        cls = classes[top];
        n = nodes[top];
        if (cls == 1)
            cls = (uint32_t)classify_box(&n->BBox, ci) & 0xff;
        if (cls == 0)
            continue;
        for (i = 0; i < n->NumChildren; i++) {
            int16_t code = child_code(n, i);

            if (code >= 0) {
                scenery_draw_a_scenery(h, code, ci, (int32_t)cls);
            } else {
                nodes[top] = child_node(h, code);
                classes[top] = (uint8_t)cls;
                top++;
            }
        }
    } while (top != 0);
}

void scenery_cull_node_recursive(ScenerySectionHeader *h,
                                 SceneryTreeNode *node, SceneryCullInfo *ci,
                                 uint32_t cls)
{
    int32_t i;

    if (cls == 1)
        cls = (uint32_t)classify_box(&node->BBox, ci);
    if (cls == 0)
        return;
    for (i = 0; i < node->NumChildren; i++) {
        int16_t code = child_code(node, i);

        if (code >= 0)
            scenery_draw_a_scenery(h, code, ci, (int32_t)cls);
        else
            scenery_cull_node_recursive(h, child_node(h, code), ci, cls);
    }
}

// ---------------------------------------------------------------- the views

int32_t scenery_what_sections_should_we_draw(GrandSceneryCullInfo *g,
                                             int16_t *out, int32_t max,
                                             SceneryCullInfo *ci)
{
    eView *view = ci->pView;
    VisibleZone *z;
    int32_t n = 0;

    (void)g;
    z = scenery_find_visible_zone(
        (const bVector2 *)(const void *)&view->pCamera->CurrentKey.Position);
    if (z == NULL) {
        bNode *p;

        for (p = ScenerySectionHeaderList.next;
             p != &ScenerySectionHeaderList; p = p->next) {
            ScenerySectionHeader *h = (ScenerySectionHeader *)(void *)p;

            if (h->SectionNumber < 100 && n < max)
                out[n++] = (int16_t)h->SectionNumber;
        }
    } else {
        const int16_t *secs = (const int16_t *)(const void *)
            ((const uint8_t *)z + offsetof(VisibleZone,
                                           VisibleScenerySections));
        int32_t count = z->NumVisibleScenerySections;
        int32_t s, i;

        // The nineties are drawn from every zone.
        for (s = 90; s < 100; s++) {
            if (ScenerySectionHeaderTable[s] != NULL && n < max)
                out[n++] = (int16_t)s;
        }
        for (i = 0; i < count; i++) {
            int16_t sec = secs[i];

            if (sec >= 0 && ScenerySectionHeaderTable[sec] != NULL && n < max)
                out[n++] = sec;
        }
    }

    if (view->ID == EVIEW_ID_PLAYER1) {
        int32_t zn = z != NULL ? z->ZoneNumber : -1;

        if (zn != CurrentZoneNumber)
            CurrentZoneNumber = zn;
    }
    return n;
}

#define CULL_VIEW_MAX 128

void scenery_cull_view(GrandSceneryCullInfo *g, SceneryCullInfo *ci)
{
    int16_t secs[CULL_VIEW_MAX];
    int32_t n = scenery_what_sections_should_we_draw(g, secs, CULL_VIEW_MAX,
                                                     ci);
    int32_t i;

    for (i = 0; i < n; i++) {
        ScenerySectionHeader *h;

        if (secs[i] < 0)
            continue;
        h = ScenerySectionHeaderTable[secs[i]];
        if (h == NULL || h->SceneryTreeNodeTable == NULL)
            continue;
        scenery_tree_cull(h, ci);
    }
}

#define BATCH_MAX 256

void scenery_batch_cull_views(GrandSceneryCullInfo *g)
{
    int16_t secs[BATCH_MAX];
    int32_t total = 0;
    int32_t v, i;

    // Each view's sections are written after the ones kept so far, and the
    // new ones are packed down onto the end of the list. A section already
    // on it only gets the view's bit.
    for (v = 0; v < g->NumCullInfos; v++) {
        int32_t start = total;
        uint32_t bit = 1u << v;
        int32_t n = scenery_what_sections_should_we_draw(
            g, &secs[total], BATCH_MAX - total, &g->SceneryCullInfos[v]);

        for (i = 0; i < n; i++) {
            int16_t sec = secs[start + i];
            ScenerySectionHeader *h;
            uint32_t seen;

            if (sec < 0 || total >= BATCH_MAX)
                continue;
            h = ScenerySectionHeaderTable[sec];
            seen = h->ViewsVisibleThisFrame;
            if (seen == 0)
                secs[total++] = sec;
            h->ViewsVisibleThisFrame = seen | bit;
        }
    }

    for (i = 0; i < total; i++) {
        ScenerySectionHeader *h;

        if (secs[i] < 0)
            continue;
        h = ScenerySectionHeaderTable[secs[i]];
        if (h->SceneryTreeNodeTable != NULL) {
            for (v = 0; v < g->NumCullInfos; v++) {
                if (h->ViewsVisibleThisFrame & (1u << v))
                    scenery_tree_cull(h, &g->SceneryCullInfos[v]);
            }
        }
        h->ViewsVisibleThisFrame = 0;
    }
}

void scenery_do_culling(GrandSceneryCullInfo *g)
{
    int32_t i;

    g->pCurrentDrawInfo = SceneryDrawInfoTable;
    g->pTopDrawInfo = SceneryDrawInfoTable + SCENERY_MAX_DRAW_INFOS;
    g->pFirstDrawInfo = SceneryDrawInfoTable;

    for (i = 0; i < g->NumCullInfos; i++) {
        SceneryCullInfo *ci = &g->SceneryCullInfos[i];
        Camera *cam = ci->pView->pCamera;

        ci->Position = cam->CurrentKey.Position;
        ci->Direction = cam->CurrentKey.Direction;
        ci->H = ci->pView->H;
    }
    for (i = 0; i < g->NumCullInfos; i++) {
        SceneryCullInfo *ci = &g->SceneryCullInfos[i];

        ci->pFirstDrawInfo = g->pCurrentDrawInfo;
        ci->pCurrentDrawInfo = g->pCurrentDrawInfo;
        ci->pTopDrawInfo = g->pTopDrawInfo;
        scenery_cull_view(g, ci);
        g->pCurrentDrawInfo = ci->pCurrentDrawInfo;
    }
    // The listing ends in a loop of four nops per cull info, which is
    // left out.
}

void scenery_stuff_scenery(GrandSceneryCullInfo *g, eView *view)
{
    int32_t i;

    for (i = 0; i < g->NumCullInfos; i++) {
        SceneryCullInfo *ci = &g->SceneryCullInfos[i];
        SceneryDrawInfo *d;

        if (ci->pView != view)
            continue;
        for (d = ci->pFirstDrawInfo;
             (uintptr_t)d < (uintptr_t)ci->pCurrentDrawInfo; d++) {
            uintptr_t p = (uintptr_t)d->pModel;
            eModel *m = (eModel *)(void *)(p & ~(uintptr_t)3);
            uint32_t flags = (p & 3) == 2 ? 4u : 0u;

            if (d->pMatrix == NULL)
                model_render(m, &eMathIdentityMatrix,
                             view->WorldLightContext, flags);
            else
                model_render(m, d->pMatrix, NULL, flags);
        }
        return;
    }
}

// ---------------------------------------------------------------- the setup

void scenery_setup_cull_info(eView *view, SceneryCullInfo *ci)
{
    const bMatrix4 *clip = view->WorldScreenClipMatrix;
    const bMatrix4 *wv = view->WorldViewMatrix;
    int32_t a = bATan(wv->v0.z, wv->v0.x);
    int32_t mode, flags;
    bMatrix4 m;

    eIdentity(&m);
    eRotateZ(&m, &m, (uint16_t)a);
    mode = eGetCurrentViewMode();
    ci->FacadeMatrix = m;
    ci->ClipMatrix = *clip;
    ci->pView = view;

    flags = 16;
    if (mode == 3 || mode == 4)
        flags = 17;
    if ((uint32_t)view->ID - EVIEW_ID_ENVMAP_LO
        < (uint32_t)(EVIEW_ID_ENVMAP_HI - EVIEW_ID_ENVMAP_LO + 1))
        flags |= 0x102;
    if (RaceParametersTrackDirection == TRACK_DIRECTION_FORWARD)
        flags |= 8;
    if (RaceParametersTrackDirection == TRACK_DIRECTION_BACKWARD)
        flags |= 4;
    ci->ExcludeFlags = flags;
}

void scenery_cull_setup_views(GrandSceneryCullInfo *g, int32_t in_game)
{
    int32_t id;

    g->NumCullInfos = 0;
    if (!in_game)
        return;
    for (id = 1; id < 4; id++) {
        eView *v = eGetView(id);

        if (v->Active != 0 && v->pRenderTarget0->Active != 0)
            scenery_setup_cull_info(v,
                                    &g->SceneryCullInfos[g->NumCullInfos++]);
    }
    if (!EnvironmentMappingEnable)
        return;
    for (id = EVIEW_ID_ENVMAP_LO; id <= EVIEW_ID_ENVMAP_HI; id++) {
        eView *v = eGetView(id);

        if (v->Active != 0 && v->pRenderTarget0->Active != 0)
            scenery_setup_cull_info(v,
                                    &g->SceneryCullInfos[g->NumCullInfos++]);
    }
}
