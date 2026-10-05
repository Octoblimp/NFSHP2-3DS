// acidsys -- AcidFXE.obj's effect system, its data half. See acidsys.h.

#include "acidsys.h"

#include <string.h>

#include "bchunk.h"
#include "eefpu.h"
#include "texturepack.h"

BSlotPool       *AcidParticleSlotPool;
BSlotPool       *AcidActiveGroupSlotPool;
BSlotPool       *AcidEmitterSlotPool;
int32_t          NumAcidEmitters;
bNode            EmitterDataList = { &EmitterDataList, &EmitterDataList };
uint32_t         AcidRandomSeed = 0x23985727u;
AcidEffectSystem FrameEffects;
AcidEffectSystem WorldEffects;

// ---------------------------------------------------------------- helpers

static void add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    tail->next = n;
    list->prev = n;
    n->next = list;
    n->prev = tail;
}

static void add_head(bNode *list, bNode *n)
{
    bNode *head = list->next;

    list->next = n;
    head->prev = n;
    n->next = head;
    n->prev = list;
}

static void unlink_node(bNode *n)
{
    bNode *next = n->next;
    bNode *prev = n->prev;

    prev->next = next;
    next->prev = prev;
}

// The xorshift AddAutoEmitter steps both seeds with, inline there.
static uint32_t acid_xorshift(uint32_t x)
{
    x ^= x << 17;
    x ^= x >> 13;
    x ^= x << 5;
    return x;
}

// A seed's low 31 bits as a fraction, [0, 1].
static float acid_unit(uint32_t x)
{
    return (float)(int32_t)(x & 0x7fffffffu) * 0x1p-31f;
}

// bStrNCpy, 0x002535a0: up to n bytes, stopping after the terminator.
static void b_strncpy(char *dst, const char *src, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        dst[i] = src[i];
        if (src[i] == '\0')
            break;
    }
}

// A pack's header, at the chunk's payload rounded up to 16.
static uint8_t *pack_header(uint8_t *chunk)
{
    return (uint8_t *)(((uintptr_t)chunk + 23u) & ~(uintptr_t)15u);
}

// ------------------------------------------------------------- the object

void acid_static_init(void)
{
    EmitterDataList.prev = &EmitterDataList;
    EmitterDataList.next = &EmitterDataList;
    acid_system_construct(&FrameEffects);
    acid_system_construct(&WorldEffects);
}

void afx_init(void)
{
    AcidParticleSlotPool = bNewSlotPool((int)sizeof(AcidParticle), 1000,
                                        "AcidParticleSlotPool", 16);
    AcidActiveGroupSlotPool = bNewSlotPool((int)sizeof(AcidActiveGroup), 400,
                                           "AcidActiveGroupSlotPool", 16);
    AcidEmitterSlotPool = bNewSlotPool((int)sizeof(AcidEmitter), 600,
                                       "AcidEmitterSlotPool", 16);
    AcidParticleSlotPool->flags &= ~BSP_OVERFLOW_IF_FULL;
    AcidParticleSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;
    AcidActiveGroupSlotPool->flags &= ~BSP_OVERFLOW_IF_FULL;
    AcidActiveGroupSlotPool->flags &= ~BSP_ZERO_ALLOCATED_MEMORY;
}

void afx_close(void)
{
    acid_system_kill_all_active_effects(&FrameEffects);
    acid_system_kill_all_active_effects(&WorldEffects);
    bDeleteSlotPool(AcidParticleSlotPool);
    bDeleteSlotPool(AcidActiveGroupSlotPool);
    AcidParticleSlotPool = NULL;
    AcidActiveGroupSlotPool = NULL;
}

int loader_acid_fx(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);
    uint8_t *h;
    uint32_t n;

    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)
        return 1;
    if (type == ACID_CHUNK_DATAS) {
        AcidEmitterData *d;

        h = pack_header(chunk);
        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)
            return 1;
        n = *(uint32_t *)(h + 12);
        d = (AcidEmitterData *)(h + 16);
        for (; n != 0; n--, d++)
            afx_add_emitter_data(d);
        return 1;
    }
    if (type == ACID_CHUNK_EMITTERS) {
        AcidEmitter *e;

        h = pack_header(chunk);
        if (*(int32_t *)(h + 8) != ACID_EMITTERS_VERSION)
            return 1;
        n = *(uint32_t *)(h + 12);
        e = (AcidEmitter *)(h + 16);
        for (; n != 0; n--, e++) {
            acid_emitter_set_emitter_data_hash(e, e->EmitterDataNameHash);
            acid_system_add_auto_emitter(&WorldEffects, e);
        }
        return 1;
    }
    return 0;
}

int unloader_acid_fx(uint8_t *chunk)
{
    uint32_t type = bchunk_u32(chunk);
    uint8_t *h;
    uint32_t n;

    if (type == ACID_CHUNK_A || type == ACID_CHUNK_B)
        return 1;
    if (type == ACID_CHUNK_DATAS) {
        AcidEmitterData *d;

        h = pack_header(chunk);
        if (*(int32_t *)(h + 8) != ACID_DATAS_VERSION)
            return 1;
        n = *(uint32_t *)(h + 12);
        d = (AcidEmitterData *)(h + 16);
        for (; n != 0; n--, d++)
            afx_remove_emitter_data(d);
        return 1;
    }
    if (type == ACID_CHUNK_EMITTERS) {
        AcidEmitter *e;

        h = pack_header(chunk);
        if (*(int32_t *)(h + 8) != ACID_EMITTERS_VERSION)
            return 1;
        n = *(uint32_t *)(h + 12);
        e = (AcidEmitter *)(h + 16);
        for (; n != 0; n--, e++)
            acid_system_remove_auto_emitter(&WorldEffects, e);
        return 1;
    }
    return 0;
}

void afx_track_loader(void)
{
}

void afx_track_unloader(void)
{
}

void afx_update_textures(void)
{
    bNode *n;

    for (n = EmitterDataList.next; n != &EmitterDataList; n = n->next) {
        AcidEmitterData *d = (AcidEmitterData *)n;
        TextureInfo *t = (TextureInfo *)d->Texture;

        if (t == NULL || t->NameHash != d->TextureNameHash)
            d->Texture = GetTextureInfo(d->TextureNameHash, 0, 0);
    }
}

void afx_add_emitter_data(AcidEmitterData *d)
{
    add_tail(&EmitterDataList, &d->Node);
}

void afx_remove_emitter_data(AcidEmitterData *d)
{
    unlink_node(&d->Node);
}

AcidEmitterData *afx_get_emitter_data(uint32_t name_hash, uint32_t group_hash,
                                      AcidEmitterData *after)
{
    bNode *n;

    if (name_hash == 0 && group_hash == 0)
        return NULL;
    n = after != NULL ? after->Node.next : EmitterDataList.next;
    for (; n != &EmitterDataList; n = n->next) {
        AcidEmitterData *d = (AcidEmitterData *)n;

        if (name_hash == 0) {
            if (d->GroupNameHash == group_hash)
                return d;
        } else if (group_hash == 0) {
            if (d->NameHash == name_hash)
                return d;
        } else if (d->NameHash == name_hash
                   && d->GroupNameHash == group_hash) {
            return d;
        }
    }
    return NULL;
}

AcidEmitter *afx_get_emitter(uint32_t name_hash, uint32_t group_hash,
                             AcidEmitter *after)
{
    bNode *list = &WorldEffects.AutoEmitterList;
    bNode *n;

    if (name_hash == 0 && group_hash == 0)
        return NULL;
    n = after != NULL ? after->Node.next : list->next;
    for (; n != list; n = n->next) {
        AcidEmitter *e = (AcidEmitter *)n;
        AcidEmitterData *d = e->EmitterData;

        if (name_hash != 0) {
            if (group_hash == 0) {
                if (d != NULL && d->NameHash == name_hash)
                    return e;
                continue;
            }
            if (e->NameHash != name_hash)
                continue;
        }
        if (d != NULL && d->GroupNameHash == group_hash)
            return e;
    }
    return NULL;
}

AcidEmitter *afx_copy_emitter(const AcidEmitter *src)
{
    AcidEmitter *e = (AcidEmitter *)bSlotOMalloc(AcidEmitterSlotPool);

    if (e != NULL)
        memset(&e->NameHash, 0, sizeof *e - offsetof(AcidEmitter, NameHash));
    NumAcidEmitters++;
    if (e == NULL)
        return NULL;
    e->NameHash = bchunk_hash(src->Name);
    b_strncpy(e->Name, src->Name, 63);
    e->Name[63] = '\0';
    acid_emitter_set_emitter_data(e, src->EmitterData);
    e->LocalWorld = src->LocalWorld;
    return e;
}

void afx_get_emitters(bNode *list, uint32_t group_hash)
{
    AcidEmitter *e = NULL;

    while ((e = afx_get_emitter(0, group_hash, e)) != NULL) {
        AcidEmitter *c = afx_copy_emitter(e);

        if (c != NULL)
            add_tail(list, &c->Node);
    }
}

void afx_delete_emitters(bNode *list)
{
    while (list->next != list) {
        bNode *n = list->next;

        unlink_node(n);
        acid_emitter_delete((AcidEmitter *)n, 3);
    }
}

int32_t acid_emitter_set_emitter_data(AcidEmitter *e, AcidEmitterData *d)
{
    if (d == NULL)
        return 0;
    e->EmitterData = d;
    return 1;
}

int32_t acid_emitter_set_emitter_data_hash(AcidEmitter *e, uint32_t hash)
{
    return acid_emitter_set_emitter_data(e,
                                         afx_get_emitter_data(hash, 0, NULL));
}

void acid_emitter_delete(AcidEmitter *e, int32_t flags)
{
    NumAcidEmitters--;
    if (flags & 1)
        bSlotFree(AcidEmitterSlotPool, e);
}

void acid_active_group_delete(AcidActiveGroup *g, int32_t flags)
{
    g->Emitter = NULL;
    g->EmitterData = NULL;
    while (g->ParticleList.next != &g->ParticleList) {
        bNode *p = g->ParticleList.next;

        unlink_node(p);
        bSlotFree(AcidParticleSlotPool, p);
    }
    if (flags & 1)
        bSlotFree(AcidActiveGroupSlotPool, g);
}

// ------------------------------------------------------------- the system

void acid_system_construct(AcidEffectSystem *s)
{
    s->ActiveGroupList.next = &s->ActiveGroupList;
    s->ActiveGroupList.prev = &s->ActiveGroupList;
    s->AutoEmitterList.next = &s->AutoEmitterList;
    s->AutoEmitterList.prev = &s->AutoEmitterList;
    s->CurrentEmitter = NULL;
    s->SelectEmitterIndex = 0;
    s->DebugStats = 0;
    s->CreateEmitterMaxScript = 0;
    s->pad = 0;
    s->PrintEmitterList = 0;
    s->PrintNearbyEmitters = 0;
    s->OnlyShowCurrentEmitter = 0;
    s->NumAutoEmitters = 0;
    s->NumVisibleParticles = 0;
    s->RenderTime = 0.0f;
    s->UpdateTime = 0.0f;
}

void acid_system_tweaker_check(AcidEffectSystem *s)
{
    (void)s;
}

void acid_system_add_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    if (e->RandomSeed == 0) {
        AcidRandomSeed = acid_xorshift(AcidRandomSeed);
        e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)
                                             * 2147483648.0f);
    }
    if (e->EmitterData == NULL || e->State == ACID_DISABLED) {
        e->State = ACID_DISABLED;
        add_tail(&s->AutoEmitterList, &e->Node);
    } else if ((uint32_t)e->State < 2) {
        const AcidEmitterData *d = e->EmitterData;
        float cycle, var;

        if (e->State != ACID_OFF) {
            cycle = d->OnCycle;
            var = d->OnCycleVariance;
        } else {
            cycle = d->OffCycle;
            var = d->OffCycleVariance;
        }
        if (cycle != 0.0f) {
            float w = var * cycle;

            e->RandomSeed = acid_xorshift(e->RandomSeed);
            cycle = cycle - w;
            cycle = cycle + acid_unit(e->RandomSeed) * w;
        }
        add_head(&s->AutoEmitterList, &e->Node);
        e->RemainingCycleTime = cycle;
        e->EmissionCountdown = 0.0f;
    } else {
        if (e->State != ACID_LIBRARY)
            e->State = ACID_DISABLED;
        add_tail(&s->AutoEmitterList, &e->Node);
    }
    s->NumAutoEmitters++;
}

void acid_system_remove_auto_emitter(AcidEffectSystem *s, AcidEmitter *e)
{
    unlink_node(&e->Node);
    s->NumAutoEmitters--;
}

void acid_system_kill_all_active_effects(AcidEffectSystem *s)
{
    while (s->ActiveGroupList.next != &s->ActiveGroupList) {
        bNode *g = s->ActiveGroupList.next;

        unlink_node(g);
        acid_active_group_delete((AcidActiveGroup *)g, 3);
    }
}
