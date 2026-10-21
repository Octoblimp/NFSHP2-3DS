// eanim -- see eanim.h.

#include "eanim.h"

#include <math.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "eefpu.h"
#include "eframe.h"
#include "emath.h"
#include "emodel.h"
#include "esolid.h"
#include "selcam.h"
#include "stomper.h"

bNode eAnimationSolidList = { &eAnimationSolidList, &eAnimationSolidList };
bNode eAnimationList = { &eAnimationList, &eAnimationList };

int32_t (*gEModelDetermineVisibleStripsFn)(eModel *m, const bMatrix4 *matrix,
                                           int32_t a, int32_t b);
void (*gEModelRenderStripsBonesFn)(eModel *m, bMatrix4 *matrix, void *light,
                                   uint32_t flags, bMatrix4 *bones);

// gp-29216 .. gp-29204: 1/32767 (0x38000100) for the three that read a
// key, and 32767 for SetRotation.
#define KEY_SCALE     0x1.0002p-15f
#define KEY_UNSCALE   32767.0f

// Render's stack holds 42 quaternions (sp+16 .. sp+688), the drivers'
// bones. The port draws nothing for a bigger tree rather than run off it.
#define EANIM_MAX_NODES 42

static uint8_t *next_chunk(uint8_t *c)
{
    return c + 8 + bchunk_u32(c + 4);
}

static void list_add_tail(bNode *list, bNode *n)
{
    bNode *last = list->prev;

    last->next = n;
    list->prev = n;
    n->next = list;
    n->prev = last;
}

// ------------------------------------------------------- eAnimationSolid

int eanim_loader(uint8_t *chunk)
{
    eAnimationSolid *s;
    uint8_t         *end, *c;

    if (bchunk_u32(chunk) != EANIMATION_CHUNK_ID)
        return 0;
    end = next_chunk(chunk);
    c = chunk + 8;
    s = (eAnimationSolid *)(((uintptr_t)c + 23) & ~(uintptr_t)15);
    c = next_chunk(c);
    s->pRotationKeys = (int16_t *)(void *)(c + 8);
    c = next_chunk(c);
    s->pTranslationKeys = (bVector3 *)(void *)(c + 8);
    // Retail then reads each translation key into the stack and back, a
    // byte swap compiled away; nothing changes.
    c = next_chunk(c);
    if (c != end)
        s->pLabelledFrames = c + 8;
    // Looked up and not used.
    (void)eFindAnimationSolid(s->NameHash);
    eDirtyAnimations = 1;
    list_add_tail(&eAnimationSolidList, &s->Node);
    return 1;
}

int eanim_unloader(uint8_t *chunk)
{
    eAnimationSolid *s;

    if (bchunk_u32(chunk) != EANIMATION_CHUNK_ID)
        return 0;
    // Retail takes the solid at chunk + 16, where the loader's is for a
    // 16-aligned chunk; the loader's address is the same there and right
    // for any other.
    s = (eAnimationSolid *)(((uintptr_t)chunk + 31) & ~(uintptr_t)15);
    eDirtyAnimations = 1;
    s->Node.prev->next = s->Node.next;
    s->Node.next->prev = s->Node.prev;
    return 1;
}

eAnimationSolid *eFindAnimationSolid(uint32_t name_hash)
{
    bNode *n;

    for (n = eAnimationSolidList.next; n != &eAnimationSolidList;
         n = n->next) {
        if (((eAnimationSolid *)(void *)n)->NameHash == name_hash)
            return (eAnimationSolid *)(void *)n;
    }
    return NULL;
}

static void get_key(const int16_t *k, bQuaternion *q)
{
    q->w = (float)k[3] * KEY_SCALE;
    q->x = (float)k[0] * KEY_SCALE;
    q->y = (float)k[1] * KEY_SCALE;
    q->z = (float)k[2] * KEY_SCALE;
}

void eanimsolid_get_rotation(const eAnimationSolid *s, bQuaternion *q,
                             int32_t node, float frame)
{
    int32_t i = s->NumFrames * node + ee_trunc_w(frame);

    get_key(s->pRotationKeys + i * 4, q);
}

void eanimsolid_set_rotation(eAnimationSolid *s, const bQuaternion *q,
                             int32_t node, float frame)
{
    int32_t  f = ee_trunc_w(frame);
    int16_t *k;

    if (f < 0 || f >= s->NumFrames)
        f = 0;
    k = s->pRotationKeys + (s->NumFrames * node + f) * 4;
    k[0] = (int16_t)ee_trunc_w(q->x * KEY_UNSCALE);
    k[1] = (int16_t)ee_trunc_w(q->y * KEY_UNSCALE);
    k[2] = (int16_t)ee_trunc_w(q->z * KEY_UNSCALE);
    k[3] = (int16_t)ee_trunc_w(q->w * KEY_UNSCALE);
}

void eanimsolid_get_rotations(const eAnimationSolid *s, bQuaternion *q,
                              float frame)
{
    int32_t node, base = 0;

    for (node = 0; node < s->NumNodes; node++) {
        get_key(s->pRotationKeys + (base + ee_trunc_w(frame)) * 4, &q[node]);
        base += s->NumFrames;
    }
}

void eanimsolid_get_translation(const eAnimationSolid *s, bVector3 *v,
                                float frame)
{
    int32_t f = ee_trunc_w(frame);

    if (f < 0 || f >= s->NumFrames)
        f = 0;
    v->x = s->pTranslationKeys[f].x;
    v->y = s->pTranslationKeys[f].y;
    v->z = s->pTranslationKeys[f].z;
}

void eanimsolid_get_blended_rotations(const eAnimationSolid *s,
                                      bQuaternion *q, float frame1,
                                      float frame2, float weight,
                                      const eAnimationSolid *other,
                                      uint64_t flags)
{
    int32_t node;

    for (node = 0; node < s->NumNodes; node++) {
        bQuaternion a, b;
        float       t = weight;

        get_key(s->pRotationKeys
                    + (s->NumFrames * node + ee_trunc_w(frame1)) * 4, &a);
        get_key(other->pRotationKeys
                    + (other->NumFrames * node + ee_trunc_w(frame2)) * 4, &b);
        if (flags != 0 && ((flags >> (node & 63)) & 1))
            t = 1.0f;
        // Slerp (0x001a7280) is selcam.c's.
        selcam_slerp(&q[node], &b, &a, t);
    }
}

// ------------------------------------------------------------ eAnimation

eAnimation *eanim_construct(eAnimation *a)
{
    list_add_tail(&eAnimationList, &a->Node);
    a->Model.NameHash = 0;
    a->Model.Solid = NULL;
    a->Weight1 = 1.0f;
    a->NameHash1 = 0;
    a->NameHash2 = 0;
    a->pAnimationSolid1 = NULL;
    a->pAnimationSolid2 = NULL;
    a->FrameNumber1 = 0.0f;
    a->FrameNumber2 = 0.0f;
    a->WeightFlags = 0;
    a->pCurrentMatrices = NULL;
    return a;
}

void eanim_destroy(eAnimation *a, int32_t flags)
{
    a->Node.prev->next = a->Node.next;
    a->Node.next->prev = a->Node.prev;
    emodel_delete(&a->Model, 2);
    if (flags & 1)
        bFree(a);
}

void eanim_init(eAnimation *a, uint32_t name_hash)
{
    emodel_init(&a->Model, name_hash);
}

void eanim_uninit(eAnimation *a)
{
    emodel_uninit(&a->Model);
}

void eanim_reconnect_solid(eAnimation *a)
{
    if (a->NameHash1 != 0)
        a->pAnimationSolid1 = eFindAnimationSolid(a->NameHash1);
    if (a->NameHash2 != 0)
        a->pAnimationSolid2 = eFindAnimationSolid(a->NameHash2);
}

eAnimationSolid *eanim_get_animation_solid(eAnimation *a, uint32_t hash)
{
    if (hash == a->NameHash1)
        return a->pAnimationSolid1;
    if (hash == a->NameHash2)
        return a->pAnimationSolid2;
    if (a->NameHash1 == 0) {
        a->NameHash1 = hash;
        a->pAnimationSolid1 = eFindAnimationSolid(hash);
        return a->pAnimationSolid1;
    }
    a->NameHash2 = hash;
    a->pAnimationSolid2 = eFindAnimationSolid(hash);
    return a->pAnimationSolid2;
}

void eanim_set_animation(eAnimation *a, uint32_t hash, float frame)
{
    if (a->NameHash1 != hash) {
        a->NameHash1 = hash;
        a->pAnimationSolid1 = eFindAnimationSolid(hash);
    }
    a->FrameNumber1 = frame;
    a->Weight1 = 1.0f;
}

void eanim_set_blended_animation(eAnimation *a, uint32_t hash1, float frame1,
                                 uint32_t hash2, float frame2, float weight)
{
    if (a->NameHash1 != hash1) {
        a->NameHash1 = hash1;
        a->pAnimationSolid1 = eFindAnimationSolid(hash1);
    }
    a->FrameNumber1 = frame1;
    a->Weight1 = weight;
    if (a->NameHash2 != hash2) {
        a->NameHash2 = hash2;
        a->pAnimationSolid2 = eFindAnimationSolid(hash2);
    }
    a->FrameNumber2 = frame2;
}

eAnimationTree *emodel_get_animation_tree(const eModel *m)
{
    if (m->Solid == NULL)
        return NULL;
    return (eAnimationTree *)(void *)&((eSolid *)m->Solid)
        ->AnimationTreeNumNodes;
}

void eanim_render(eAnimation *a, bMatrix4 *matrix, void *light,
                  uint32_t flags)
{
    bVector3        t;
    bQuaternion     q[EANIM_MAX_NODES];
    eAnimationTree *tree;
    eAnimationSolid *s1 = a->pAnimationSolid1, *s2;

    if (s1 == NULL)
        return;
    eanimsolid_get_translation(s1, &t, a->FrameNumber1);
    tree = emodel_get_animation_tree(&a->Model);
    if (tree == NULL || tree->NumNodes != s1->NumNodes)
        return;
    if (tree->NumNodes > EANIM_MAX_NODES)
        return;
    // Retail waits out 42 loops of nops here, for the FPU.
    if (a->Weight1 == 1.0f) {
        eanimsolid_get_rotations(s1, q, a->FrameNumber1);
    } else {
        s2 = a->pAnimationSolid2;
        if (s2 == NULL || tree->NumNodes != s2->NumNodes)
            return;
        eanimsolid_get_blended_rotations(s1, q, a->FrameNumber1,
                                         a->FrameNumber2, a->Weight1, s2,
                                         a->WeightFlags);
    }
    eanim_render_posed(a, matrix, &t, q, light, flags);
}

void eanim_render_posed(eAnimation *a, bMatrix4 *matrix,
                        const bVector3 *translation, const bQuaternion *q,
                        void *light, uint32_t flags)
{
    bMatrix4       *frame, turn, ident;
    bVector3        v;
    eAnimationTree *tree;
    int32_t         i;

    frame = (bMatrix4 *)eframe_malloc(64);
    if (frame == NULL)
        return;
    *frame = *matrix;
    turn = *matrix;
    turn.v3.x = 0.0f;
    turn.v3.y = 0.0f;
    turn.v3.z = 0.0f;
    eMulVector3(&v, &turn, translation);
    frame->v3.x = matrix->v3.x + v.x;
    frame->v3.y = matrix->v3.y + v.y;
    frame->v3.z = matrix->v3.z + v.z;
    frame->v3.w = 1.0f;
    if (gEModelDetermineVisibleStripsFn != NULL
        && gEModelDetermineVisibleStripsFn(&a->Model, frame, 1, 1) == 0)
        return;
    tree = emodel_get_animation_tree(&a->Model);
    if (tree == NULL)
        return;
    a->pCurrentMatrices =
        (bMatrix4 *)eframe_malloc((uint32_t)tree->NumNodes << 6);
    if (a->pCurrentMatrices == NULL)
        return;
    eIdentity(&ident);
    eanim_pose_matrix_recursive(a, &ident, q, tree, 0);
    for (i = 0; i < tree->NumNodes; i++)
        eMulMatrix(&a->pCurrentMatrices[i], &tree->pNodes[i].ObjectToBoneSpace,
                   &a->pCurrentMatrices[i]);
    if (gEModelRenderStripsBonesFn != NULL)
        gEModelRenderStripsBonesFn(&a->Model, frame, light, flags,
                                   a->pCurrentMatrices);
}

void eanim_get_root_translation(eAnimation *a, bVector3 *v)
{
    eAnimationTree *tree = emodel_get_animation_tree(&a->Model);

    if (tree != NULL && tree->NumNodes != 0) {
        // A quadword: the indices are the fourth lane.
        memcpy(v, tree->pNodes[0].Translation, 16);
    } else {
        // The fourth lane is the stack's.
        v->x = 0.0f;
        v->y = 0.0f;
        v->z = 0.0f;
    }
}

void eanim_pose_matrix_recursive(eAnimation *a, const bMatrix4 *parent,
                                 const bQuaternion *q, eAnimationTree *tree,
                                 int32_t node)
{
    bMatrix4           *m;
    eAnimationTreeNode *n;
    int32_t             child;

    if (node >= tree->NumNodes)
        return;
    m = &a->pCurrentMatrices[node];
    n = &tree->pNodes[node];
    bQuaternionToMatrix(m, &q[node]);
    m->v3.x = n->Translation[0];
    m->v3.y = n->Translation[1];
    m->v3.z = n->Translation[2];
    eMulMatrix(m, m, parent);
    if (node == nBoneScale) {
        m->v0.x *= vBoneScale[0];
        m->v0.y *= vBoneScale[0];
        m->v0.z *= vBoneScale[0];
        m->v0.w *= vBoneScale[0];
        m->v1.x *= vBoneScale[1];
        m->v1.y *= vBoneScale[1];
        m->v1.z *= vBoneScale[1];
        m->v1.w *= vBoneScale[1];
        m->v2.x *= vBoneScale[2];
        m->v2.y *= vBoneScale[2];
        m->v2.z *= vBoneScale[2];
        m->v2.w *= vBoneScale[2];
    }
    for (child = n->FirstChildNodeIndex; child != 0;
         child = tree->pNodes[child].NextChildNodeIndex)
        eanim_pose_matrix_recursive(a, m, q, tree, child);
}

static float max_s(float a, float b)
{
    return b > a ? b : a;
}

void eanim_get_bounding_box(eAnimation *a, bVector3 *mn, bVector3 *mx)
{
    bVector3 lo, hi;
    float    r;

    if (a->pAnimationSolid1 == NULL)
        return;
    bInitializeBoundingBox3At(mn, mx, &a->pAnimationSolid1->BBoxMin);
    bExpandBoundingBox3(mn, mx, &a->pAnimationSolid1->BBoxMax);
    if (a->pAnimationSolid2 != NULL) {
        bExpandBoundingBox3(mn, mx, &a->pAnimationSolid2->BBoxMin);
        bExpandBoundingBox3(mn, mx, &a->pAnimationSolid2->BBoxMax);
    }
    lo.x = lo.y = lo.z = 0.0f;
    hi.x = hi.y = hi.z = 0.0f;
    emodel_get_bounding_box(&a->Model, &lo, &hi);
    r = max_s(fabsf(lo.x), fabsf(lo.y));
    r = max_s(r, fabsf(lo.z));
    r = max_s(r, fabsf(hi.x));
    r = max_s(r, fabsf(hi.y));
    r = max_s(r, fabsf(hi.z));
    mn->x = mn->x - r;
    mn->y = mn->y - r;
    mn->z = mn->z - r;
    mx->x = mx->x + r;
    mx->y = mx->y + r;
    mx->z = mx->z + r;
}

void eReconnectAllAnimations(void)
{
    bNode *n;

    for (n = eAnimationList.next; n != &eAnimationList; n = n->next)
        eanim_reconnect_solid((eAnimation *)(void *)n);
}
