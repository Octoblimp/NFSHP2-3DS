// fernshaker -- see fernshaker.h.

#include "fernshaker.h"

#include <math.h>
#include <stdint.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bmem.h"
#include "eefpu.h"
#include "emodel.h"
#include "esolid.h"
#include "realtime.h"

FernShakerInfo *pFernShakerInfoTable;
int32_t         NumFernShakerInfos;
BSlotPool      *FernShakerSlotPool;
bNode           FernShakerList = { &FernShakerList, &FernShakerList };

// The .sdata floats at gp-28288 and gp-28284: metres a second to miles an
// hour, and the shake's growth per mile an hour past five.
static const float FernSpeedToMph   = 2.23f;
static const float FernShakePerMph  = 0.04f;

// new[]'s cookie: the count at the block's start, the array 16 bytes on.
#define FERN_INFO_COOKIE 16

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->prev = tail;
    n->next = list;
}

static void unlink_node(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// The instance's place: three rows of its rotation in units of 2^-14,
// w 0, and its position with w 1.
static void instance_matrix(bMatrix4 *m, const SceneryInstance *inst)
{
    const float k = 1.0f / 16384.0f;
    bVector4   *row[3];
    int32_t     i;

    row[0] = &m->v0;
    row[1] = &m->v1;
    row[2] = &m->v2;
    for (i = 0; i < 3; i++) {
        row[i]->x = (float)inst->Rotation[3 * i] * k;
        row[i]->y = (float)inst->Rotation[3 * i + 1] * k;
        row[i]->z = (float)inst->Rotation[3 * i + 2] * k;
        row[i]->w = 0.0f;
    }
    m->v3.x = inst->Position[0];
    m->v3.y = inst->Position[1];
    m->v3.z = inst->Position[2];
    m->v3.w = 1.0f;
}

// ------------------------------------------------------- FernShakerInfo

void fern_shaker_info_init(FernShakerInfo *info, const char *animation,
                           const char *group)
{
    info->RigidAnimationNameHash = bchunk_hash(animation);
    info->EmitterGroupNameHash = bchunk_hash(group);
    afx_get_emitters(&info->EmitterList, info->EmitterGroupNameHash);
}

void fern_shaker_info_destroy(FernShakerInfo *info, int32_t flags)
{
    bNode *list = &info->EmitterList, *n;

    // ~bTList<AcidEmitter>(list, 2).
    for (n = list->next; n != list; n = list->next) {
        unlink_node(n);
        acid_emitter_delete((AcidEmitter *)n, 3);
    }
    // __builtin_delete, which is bFree.
    if ((flags & 1) != 0)
        bFree(info);
}

// ------------------------------------------------------------ the module

void init_fern_shakers(void)
{
    uint8_t *block;
    int32_t  i;

    FernShakerSlotPool = bNewSlotPool((int)sizeof(FernShaker), 32,
                                      "FernShakerSlotPool", 16);
    NumFernShakerInfos = 2;
    block = (uint8_t *)bMalloc(FERN_INFO_COOKIE
                               + 2 * (int)sizeof(FernShakerInfo),
                               "FernShakerInfoTable", 0, 16);
    *(int32_t *)(void *)block = 2;
    pFernShakerInfoTable = (FernShakerInfo *)(void *)(block
                                                      + FERN_INFO_COOKIE);
    for (i = 0; i < 2; i++) {
        bNode *l = &pFernShakerInfoTable[i].EmitterList;

        l->next = l;
        l->prev = l;
    }
    fern_shaker_info_init(&pFernShakerInfoTable[0], "BUSHSHAKE_A",
                          "BUSHSHAKE_A");
    fern_shaker_info_init(&pFernShakerInfoTable[1], "BUSHSHAKE_B",
                          "BUSHSHAKE_B");
}

void flush_fern_shakers(void)
{
    while (FernShakerList.next != &FernShakerList) {
        bNode *n = FernShakerList.next;

        unlink_node(n);
        fern_shaker_destroy((FernShaker *)n, 3);
    }
}

void close_fern_shakers(void)
{
    if (pFernShakerInfoTable != NULL) {
        uint8_t        *block = (uint8_t *)pFernShakerInfoTable
                                - FERN_INFO_COOKIE;
        FernShakerInfo *info = pFernShakerInfoTable
                               + *(int32_t *)(void *)block;

        while (info != pFernShakerInfoTable) {
            info--;
            fern_shaker_info_destroy(info, 0);
        }
        // __builtin_vec_delete, which is bFree.
        bFree(block);
    }
    pFernShakerInfoTable = NULL;
    NumFernShakerInfos = 0;
    flush_fern_shakers();
    bDeleteSlotPool(FernShakerSlotPool);
    FernShakerSlotPool = NULL;
}

// ----------------------------------------------------------- FernShaker

FernShaker *fern_shaker_construct(FernShaker *s, uint32_t code)
{
    uint32_t              section = code >> 16;
    ScenerySectionHeader *h;
    SceneryInstance      *inst;
    eModel               *model;
    bMatrix4              m;
    int32_t               i;

    h = section < SCENERY_MAX_SECTIONS ? ScenerySectionHeaderTable[section]
                                       : NULL;
    s->StartTime = WorldTimeFrames;
    s->SceneryCode = code;
    s->pSceneryInstance = NULL;
    s->pWorldObject = NULL;
    s->pFernShakerInfo = NULL;
    if (h == NULL || h->pSceneryInstance == NULL)
        return s;
    inst = &h->pSceneryInstance[code & 0xffffu];
    model = h->pSceneryInfo[inst->SceneryInfoNumber].pModel[0];
    if (model == NULL || emodel_get_rigid_animation(model) == NULL)
        return s;
    instance_matrix(&m, inst);
    s->pSceneryInstance = inst;
    s->pWorldObject = worldobject_construct(
        (WorldObject *)bSlotOMalloc(WorldObjectSlotPool), model->NameHash,
        &m, 0);
    s->pSceneryInstance->ExcludeFlags |= 0x10;
    for (i = 0; i < NumFernShakerInfos; i++) {
        FernShakerInfo *info = &pFernShakerInfoTable[i];

        if (info->RigidAnimationNameHash
            == emodel_get_rigid_animation(model)->NameHash) {
            s->pFernShakerInfo = info;
            break;
        }
    }
    return s;
}

void fern_shaker_destroy(FernShaker *s, int32_t flags)
{
    if (s->pSceneryInstance != NULL) {
        s->pSceneryInstance->ExcludeFlags &= 0xffef;
        if (s->pWorldObject != NULL)
            worldobject_destruct(s->pWorldObject, 3);
    }
    if ((flags & 1) != 0)
        bSlotFree(FernShakerSlotPool, s);
}

void fern_shaker_shake(FernShaker *s, const bVector3 *vel)
{
    const SceneryInstance *inst = s->pSceneryInstance;
    eModel                *model;
    const eRigidAnimation *anim;
    float                  speed, shake;
    bNode                 *list, *n;
    bMatrix4               m;

    if (inst == NULL)
        return;
    model = (eModel *)s->pWorldObject->pModel;
    anim = emodel_get_rigid_animation(model);
    if (anim == NULL)
        return;
    // `vmul.xyz ; vaddy.x ; vaddz.x`, then the root.
    speed = sqrtf((vel->x * vel->x + vel->y * vel->y) + vel->z * vel->z)
            * FernSpeedToMph;
    if (!(5.0f < speed))
        return;
    if (emodel_get_rigid_animation_time(model) < 0) {
        int32_t frame = 0;

        if (30.0f < speed)
            frame = ee_trunc_w((float)(int16_t)anim->NumFrames * 0.5f);
        s->StartTime = WorldTimeFrames;
        emodel_set_rigid_animation_frame_number(model, frame);
    }
    // max.s with 0, then min.s with 1.
    shake = (speed - 5.0f) * FernShakePerMph;
    if (shake < 0.0f)
        shake = 0.0f;
    if (1.0f < shake)
        shake = 1.0f;
    if (!(0.0f < shake) || s->pFernShakerInfo == NULL)
        return;
    instance_matrix(&m, inst);
    list = &s->pFernShakerInfo->EmitterList;
    for (n = list->next; n != list; n = n->next) {
        AcidEmitter *e = (AcidEmitter *)n;

        e->LocalWorld = m;
        e->InheritVelocity.x = vel->x;
        e->InheritVelocity.y = vel->y;
        e->InheritVelocity.z = vel->z;
        e->InheritVelocity.w = 0.0f;
        acid_system_trigger_emitter(&WorldEffects, e, -shake, NULL);
    }
}

void shake_fern(uint32_t code, const bVector3 *vel)
{
    FernShaker *s;
    bNode      *n, *next;

    for (n = FernShakerList.next; n != &FernShakerList; n = next) {
        next = n->next;
        if ((int32_t)((uint32_t)WorldTimeFrames
                      - (uint32_t)((FernShaker *)n)->StartTime)
            >= FERN_SHAKER_LIFETIME) {
            unlink_node(n);
            fern_shaker_destroy((FernShaker *)n, 3);
        }
    }
    for (n = FernShakerList.next; n != &FernShakerList; n = n->next)
        if (((FernShaker *)n)->SceneryCode == code)
            break;
    if (n != &FernShakerList) {
        s = (FernShaker *)n;
    } else {
        if (bIsSlotPoolFull(FernShakerSlotPool))
            return;
        s = fern_shaker_construct(
            (FernShaker *)bSlotMalloc(FernShakerSlotPool), code);
        add_tail(&FernShakerList, &s->Node);
    }
    fern_shaker_shake(s, vel);
}

void flatten_fern(uint32_t code)
{
    (void)code;
}
