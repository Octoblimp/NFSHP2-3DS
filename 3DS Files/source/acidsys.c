// acidsys -- AcidFXE.obj's effect system, its data half. See acidsys.h.

#include "acidsys.h"

#include <math.h>
#include <string.h>

#include "acidfx.h"
#include "bchunk.h"
#include "bmath.h"
#include "bticker.h"
#include "camera.h"
#include "car.h"
#include "eefpu.h"
#include "emath.h"
#include "eview.h"
#include "texturepack.h"

int32_t (*gAcidGameFlowStateFn)(void);

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

// The seed stepped and its fraction, as TriggerEmitter draws each number.
static float acid_next(uint32_t *seed)
{
    *seed = acid_xorshift(*seed);
    return acid_unit(*seed);
}

// A fraction across a spread of `full` degrees about zero, as a BAM: the
// listing scales the degrees by 65536 and divides the int by 360.
static uint16_t spread_bam(float u, float full, float half)
{
    return (uint16_t)(ee_trunc_w((u * full - half) * 65536.0f) / 360);
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

// ------------------------------------------------------------ the particles

// AcidParticle's deleting destructor (0x0012a348): bNode's destructor,
// which does nothing, then with bit 0 of `flags` the slot to the pool.
static void acid_particle_delete(AcidParticle *p, int32_t flags)
{
    if (flags & 1)
        bSlotFree(AcidParticleSlotPool, p);
}

void acid_system_update_interest_points(AcidEffectSystem *s)
{
    static const int32_t kViews[3] = {
        EVIEW_ID_PLAYER1, EVIEW_ID_PLAYER2, EVIEW_ID_FRONTEND
    };
    int i;

    for (i = 0; i < 3; i++) {
        const Camera *c = eGetView(kViews[i])->pCamera;

        if (c != NULL)
            memcpy(&s->InterestPoints[i], &c->CurrentKey.Position,
                   sizeof s->InterestPoints[i]);
    }
}

// The listing keeps the direction on its stack and writes only x, y and z
// of it on the disc's path, so w is the last eMulVector's, and before the
// first one whatever the stack held. The port starts it at 0, as the
// cross-check's model does, and carries it from particle to particle. It
// reaches x, y and z only as 0 * w, and so only through w's sign or an
// infinity.
void acid_system_trigger_emitter(AcidEffectSystem *s, AcidEmitter *e,
                                 float time_step, void *car)
{
    const AcidEmitterData *d = e->EmitterData;
    AcidActiveGroup *g;
    float ets, ec;
    int close_enough = 0, i;

    if (d == NULL)
        return;
    for (i = 0; i < 3; i++) {
        float dx = e->LocalWorld.v3.x - s->InterestPoints[i].x;
        float dy = e->LocalWorld.v3.y - s->InterestPoints[i].y;
        float dz = e->LocalWorld.v3.z - s->InterestPoints[i].z;

        if (sqrtf(dx * dx + dy * dy + dz * dz) < d->FarClip) {
            close_enough = 1;
            break;
        }
    }
    if (e->RandomSeed == 0) {
        AcidRandomSeed = acid_xorshift(AcidRandomSeed);
        e->RandomSeed = (uint32_t)ee_trunc_w(acid_unit(AcidRandomSeed)
                                             * 2147483648.0f);
    }
    if (!close_enough)
        return;
    if (e->State != ACID_ON && !(time_step < 0.0f))
        return;

    ets = time_step;
    if (0.0f <= time_step) {
        if (e->RemainingCycleTime != 0.0f && e->RemainingCycleTime < ets)
            ets = e->RemainingCycleTime;
    } else {
        ets = -time_step;
    }
    ec = e->EmissionCountdown;
    if (ec < ets) {
        g = e->LastActiveGroup;
        if ((g == NULL || g->Emitter != e || g->pCar != car)
            && !bIsSlotPoolFull(AcidActiveGroupSlotPool)) {
            g = (AcidActiveGroup *)bSlotMalloc(AcidActiveGroupSlotPool);
            g->ParticleList.next = &g->ParticleList;
            g->ParticleList.prev = &g->ParticleList;
            g->pCar = car;
            add_tail(&s->ActiveGroupList, &g->Node);
            g->EmitterData = e->EmitterData;
            g->Emitter = e;
            e->LastActiveGroup = g;
        }
        if (g != NULL) {
            bMatrix4 local_world = e->LocalWorld;
            bMatrix4 local_orientation = e->LocalWorld;
            bMatrix4 rot;
            bVector4 pdir, ppos;
            float num_anim_frames = 1.0f;
            float angle_range = d->InitialAngleRange * 182.04445f; // gp-32104
            float angle = -angle_range * 0.5f;
            float npv = d->NumParticlesVariance * d->NumParticles;
            float spv = d->SpeedVariance * d->Speed;
            float miv = d->MotionInheritVariance * d->MotionInherit;
            float lv = d->LifeVariance * d->Life;
            float full = d->SpreadAngle, half = full * 0.5f;
            float np = d->NumParticles - npv;
            float speed = d->Speed - spv;
            float life = d->Life - lv;
            float mi = d->MotionInherit - miv;
            uint32_t seed = e->RandomSeed;

            local_orientation.v3.x = 0.0f;
            local_orientation.v3.y = 0.0f;
            local_orientation.v3.z = 0.0f;
            local_orientation.v3.w = 1.0f;
            if (d->RandomStartFrame)
                num_anim_frames = (float)(int32_t)(
                    ((uint32_t)1 << ((int8_t)d->ContactSheetW & 31))
                    << ((int8_t)d->ContactSheetH & 31));
            pdir.w = 0.0f;

            while (ec <= ets) {
                float u, px, py, pz, plife, fangle, pspeed, inherit;
                uint32_t anim_frame, pangle;

                ets -= ec;
                if (d->SpreadAsDisc) {
                    uint16_t yaw = spread_bam(acid_next(&seed), full, half);
                    uint16_t spin = spread_bam(acid_next(&seed), 360.0f,
                                               180.0f);

                    pdir.x = bCosBam(spin);
                    pdir.y = bSinBam(spin);
                    pdir.z = 0.0f;
                    eRotateY(&rot, &eMathIdentityMatrix, yaw);
                    eMulVector4(&pdir, &rot, &pdir);
                    eMulVector4(&pdir, &local_orientation, &pdir);
                } else {
                    uint16_t ax = spread_bam(acid_next(&seed), full, half);
                    uint16_t ay = spread_bam(acid_next(&seed), full, half);
                    uint16_t az = spread_bam(acid_next(&seed), full, half);

                    eRotateX(&rot, &eMathIdentityMatrix, ax);
                    eRotateY(&rot, &rot, ay);
                    eRotateZ(&rot, &rot, az);
                    eMulVector4(&pdir, &rot, &local_world.v2);
                }

                u = acid_next(&seed);
                ppos.x = d->VolumeCenter.x
                       + (u * d->VolumeExtent.x - d->VolumeExtent.x * 0.5f);
                u = acid_next(&seed);
                ppos.y = d->VolumeCenter.y
                       + (u * d->VolumeExtent.y - d->VolumeExtent.y * 0.5f);
                u = acid_next(&seed);
                ppos.z = d->VolumeCenter.z
                       + (u * d->VolumeExtent.z - d->VolumeExtent.z * 0.5f);
                ppos.w = 1.0f;
                eMulVector4(&ppos, &local_world, &ppos);
                px = ppos.x;
                py = ppos.y;
                pz = ppos.z;

                anim_frame = (uint32_t)ee_trunc_w(acid_next(&seed)
                                                  * num_anim_frames) & 0xffu;
                plife = life + acid_next(&seed) * lv;
                fangle = angle + acid_next(&seed) * angle_range;
                pspeed = speed + acid_next(&seed) * spv;
                inherit = 0.0f;
                if (mi != 0.0f) {
                    inherit = mi + acid_next(&seed) * miv;
                    if (inherit < 0.0f)
                        inherit = 0.0f;
                    if (!(inherit < 1.0f))
                        inherit = 1.0f;
                    if (!d->MotionLive) {
                        // The velocity and its length, then the direction
                        // scaled by vrsqrt's 1 / sqrt.
                        float vx = pspeed * pdir.x
                                 + inherit * e->InheritVelocity.x;
                        float vy = pspeed * pdir.y
                                 + inherit * e->InheritVelocity.y;
                        float vz = pspeed * pdir.z
                                 + inherit * e->InheritVelocity.z;
                        float len2 = vx * vx + vy * vy + vz * vz;
                        float q;

                        pspeed = sqrtf(len2);
                        q = 1.0f / sqrtf(len2);
                        pdir.x = vx * q;
                        pdir.y = vy * q;
                        pdir.z = vz * q;
                    }
                }
                pangle = (uint32_t)ee_trunc_w(fangle) & 0xfffeu;
                if (d->RandomRotationDirection)
                    pangle |= seed & 1u;
                if (60.0f < plife)
                    plife = 60.0f;

                if (e->DontEmit == 0
                    && !bIsSlotPoolFull(AcidParticleSlotPool)) {
                    AcidParticle *p =
                        (AcidParticle *)bSlotMalloc(AcidParticleSlotPool);
                    float sp = pspeed * 128.0f;

                    if (!(sp < 65535.0f))           // gp-32100
                        sp = 65535.0f;
                    p->Frame = (uint8_t)anim_frame;
                    p->VZ = (int8_t)ee_trunc_w(pdir.z * 127.0f);
                    p->Inherit = (uint8_t)ee_trunc_w(inherit * 255.0f);
                    p->VX = (int8_t)ee_trunc_w(pdir.x * 127.0f);
                    p->VY = (int8_t)ee_trunc_w(pdir.y * 127.0f);
                    p->Speed = (uint16_t)ee_trunc_w(sp);
                    p->Life = (uint16_t)ee_trunc_w(plife * 1024.0f);
                    p->Angle = (int16_t)pangle;
                    p->X = px;
                    p->Y = py;
                    p->Z = pz;
                    add_tail(&g->ParticleList, &p->Node);
                }

                ec = 1.0f / (np + acid_next(&seed) * npv);
                if (240.0f < ec)
                    ec = 240.0f;
                if (ec < 0.0f)
                    ec = 0.0f;
            }
            e->RandomSeed = seed;
            if (g->ParticleList.next == &g->ParticleList) {
                unlink_node(&g->Node);
                acid_active_group_delete(g, 3);
            }
        }
    }
    e->EmissionCountdown = 0.0f <= time_step ? ec - ets : 0.0f;
}

// ctrl's columns 2 and 3 are never written: the listing hands
// hermite_basis whatever its stack held there. The port zeroes them, as
// the cross-check's model does. RenderEffects copies the whole of
// ExtraBasis; which of its columns it uses is SC-3c's to say.
void acid_system_do_time_step(AcidEffectSystem *s, float dt)
{
    uint32_t start = bGetTicker();
    int32_t lifestep = ee_trunc_w(dt * 1024.0f);
    int32_t found = 0;
    bNode *n, *next;

    acid_system_update_interest_points(s);
    for (n = s->AutoEmitterList.next; n != &s->AutoEmitterList; n = next) {
        AcidEmitter *e = (AcidEmitter *)n;
        int32_t st = e->State;
        float rct;

        next = n->next;
        if (st == ACID_ON)
            acid_system_trigger_emitter(s, e, dt, NULL);
        else if (st != ACID_OFF)
            found = 1;
        rct = e->RemainingCycleTime;
        if (rct != 0.0f && (uint32_t)st < 2) {
            rct -= dt;
            if (!(rct <= 0.0f)) {
                e->RemainingCycleTime = rct;
            } else {
                const AcidEmitterData *d = e->EmitterData;
                float cycle, var;

                if (st == ACID_OFF) {
                    var = d->OnCycleVariance;
                    st = ACID_ON;
                    cycle = d->OnCycle;
                } else {
                    var = d->OffCycleVariance;
                    st = ACID_OFF;
                    cycle = d->OffCycle;
                }
                if (cycle != 0.0f) {
                    float w = var * cycle;

                    e->RandomSeed = acid_xorshift(e->RandomSeed);
                    cycle = cycle - w;
                    cycle = cycle + acid_unit(e->RandomSeed) * w;
                    cycle = cycle + rct;
                }
                e->State = st;
                e->RemainingCycleTime = cycle;
                e->EmissionCountdown = 0.0f;
            }
        }
        if (found)
            break;
    }

    if (gAcidGameFlowStateFn != NULL && gAcidGameFlowStateFn() == 3) {
        bMatrix4 ctrl;

        memset(&ctrl, 0, sizeof ctrl);
        for (n = EmitterDataList.next; n != &EmitterDataList; n = n->next) {
            AcidEmitterData *d = (AcidEmitterData *)n;
            float k0 = d->KeyPositions.x * 0.33333334f;     // gp-32096
            float k1 = d->KeyPositions.y * 0.33333334f;
            float k2 = d->KeyPositions.z * 0.33333334f;
            float k3 = d->KeyPositions.w * 0.33333334f;

            ctrl.v0.x = d->Size.x;
            ctrl.v1.x = d->Size.y;
            ctrl.v2.x = d->Size.z;
            ctrl.v3.x = d->Size.w;
            ctrl.v0.y = d->RelativeAngle.x * 182.04445f;    // gp-32092
            ctrl.v1.y = d->RelativeAngle.y * 182.04445f;
            ctrl.v2.y = d->RelativeAngle.z * 182.04445f;
            ctrl.v3.y = d->RelativeAngle.w * 182.04445f;
            hermite_basis(&d->ColourBasis, &d->ColourMatrix, k0, k1, k2, k3);
            hermite_basis(&d->ExtraBasis, &ctrl, k0, k1, k2, k3);
        }
    }

    for (n = s->ActiveGroupList.next; n != &s->ActiveGroupList; n = next) {
        AcidActiveGroup *g = (AcidActiveGroup *)n;
        const AcidEmitterData *d = g->EmitterData;
        int32_t mask = (int32_t)((((uint32_t)1 << ((int8_t)d->ContactSheetW
                                                   & 31))
                                  << ((int8_t)d->ContactSheetH & 31)) - 1u);
        int32_t fpsd = 0;
        float cvx = 0.0f, cvy = 0.0f, cvz = 0.0f;
        float grav = -d->Gravity, drag = d->Drag;
        bNode *pn, *pnext;

        next = n->next;
        if ((int8_t)d->AnimFPS != 0)
            fpsd = ee_trunc_w(1.0f / (float)(int8_t)d->AnimFPS * 1024.0f);
        if (d->MotionLive && g->pCar != NULL && 0.0f < d->MotionInherit) {
            const Car *c = (const Car *)g->pCar;

            cvx = dt * c->State.Velocity.x;
            cvz = dt * c->State.Velocity.z;
            cvy = dt * c->State.Velocity.y;
        }
        for (pn = g->ParticleList.next; pn != &g->ParticleList; pn = pnext) {
            AcidParticle *p = (AcidParticle *)pn;
            int32_t old = (int16_t)p->Life;
            int32_t nl = old - lifestep;
            uint32_t frame;
            float spd, vx, vy, vz, inh, x, y, z, sx, sy, sz, len, inv;

            pnext = pn->next;
            if (nl <= 0) {
                unlink_node(pn);
                acid_particle_delete(p, 3);
                continue;
            }
            frame = p->Frame;
            if (fpsd != 0)
                frame = (uint32_t)(int32_t)((int32_t)frame + old / fpsd
                                            - nl / fpsd) & (uint32_t)mask;
            spd = (float)p->Speed * 0.0078125f * (1.0f / 127.0f); // gp-32088
            vx = (float)p->VX * spd;
            vy = (float)p->VY * spd;
            vz = (float)p->VZ * spd;
            inh = (float)p->Inherit * (1.0f / 255.0f);             // gp-32084
            x = p->X;
            y = p->Y;
            z = p->Z;
            sx = vx < 0.0f ? 1.0f : -1.0f;
            sy = vy < 0.0f ? 1.0f : -1.0f;
            sz = vz < 0.0f ? 1.0f : -1.0f;
            vz = vz + (grav + sz * vz * (vz * drag)) * dt;
            vx = vx + sx * drag * (vx * vx) * dt;
            vy = vy + sy * drag * (vy * vy) * dt;
            z += vz * dt;
            x += vx * dt;
            y += vy * dt;
            if (d->MotionLive) {
                z += cvz * inh;
                x += cvx * inh;
                y += cvy * inh;
            }
            len = sqrtf(vx * vx + vy * vy + vz * vz);
            inv = 1.0f / len;
            p->Frame = (uint8_t)frame;
            p->Life = (uint16_t)nl;
            p->Speed = (uint16_t)ee_trunc_w(len * 128.0f);
            p->X = x;
            p->Y = y;
            p->Z = z;
            p->VZ = (int8_t)ee_trunc_w(vz * inv * 127.0f);
            p->VY = (int8_t)ee_trunc_w(vy * inv * 127.0f);
            p->VX = (int8_t)ee_trunc_w(vx * inv * 127.0f);
        }
        if (g->ParticleList.next == &g->ParticleList) {
            unlink_node(&g->Node);
            acid_active_group_delete(g, 3);
        }
    }
    s->UpdateTime = bGetTickerDifference(start, bGetTicker());
}
