// cardamage -- see cardamage.h.

#include "cardamage.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmem.h"
#include "carrenderinfo.h"
#include "cartypeinfo.h"
#include "collisionsound.h"
#include "eefpu.h"
#include "epositionmarker.h"
#include "race.h"

#define ZONE_SCALE      0.0078125f      // `lui at,0x3c00`, 1/128
#define TOTAL_SCALE     0.000244140625f // `lui at,0x3980`, 2^-12
#define APPLY_TOLERANCE 0.02f           // gp-29024, 0x0032e790
#define MIN_HIT         0.05f           // gp-29020, 0x0032e794
#define MIN_BREAK       0.2f            // gp-29016, 0x0032e798
#define WRECK_IMPACT    9999.0f         // gp-29012, 0x0032e79c

// Retail makes both empty in BodyDamage.obj's static constructor
// (0x001b5440); a constant initialiser does the same.
bNode BodyDamageInfoList = { &BodyDamageInfoList, &BodyDamageInfoList };
bNode BodyDamageList = { &BodyDamageList, &BodyDamageList };

void (*gBodyDamageVertexWalkFn)(BodyDamageModel *m);

// 0x00313b80, as the disc has it. The levels' thresholds are the zone's
// visible damage; the effects are CarEffect's BREAK_* from the side
// mirrors (12) to the right rear window (25), and the radiator's steam.
const BreakableCarItemInfo BreakableCarItemInfos[CARDAMAGE_ITEMS] = {
    {  0, 0x05f63788u, { 0.0f, 0.25f, 0.5f,  0.75f }, 0, 12 },
    {  1, 0xc52bf01bu, { 0.0f, 0.25f, 0.5f,  0.75f }, 0, 13 },
    {  2, 0x725758bfu, { 0.0f, 0.25f, 0.5f,  0.75f }, 0, 14 },
    {  3, 0x494ed280u, { 0.0f, 0.25f, 0.5f,  0.75f }, 0, 15 },
    {  4, 0xa7e6ea53u, { 0.0f, 0.25f, 0.35f, 0.5f  }, 0, 16 },
    {  5, 0xa532fc46u, { 0.0f, 0.25f, 0.35f, 0.5f  }, 0, 17 },
    {  6, 0xd947f346u, { 0.0f, 0.25f, 0.45f, 0.65f }, 0, 18 },
    {  7, 0x02b52399u, { 0.0f, 0.25f, 0.45f, 0.65f }, 0, 19 },
    {  8, 0x7b220ddfu, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 20 },
    {  9, 0x1b0763a0u, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 21 },
    { 10, 0xe7e4ef49u, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 22 },
    { 11, 0x4cdebfcau, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 23 },
    { 12, 0x60f8b13cu, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 24 },
    { 13, 0x0ab88f5du, { 0.0f, 0.25f, 0.5f,  0.75f }, 1, 25 },
    { 14, 0x68100815u, { 0.0f, 0.7f,  0.85f, 0.95f }, 0,  6 },
};

// 0x00313d60: the car types with no windows to break, and the levels
// they lose (items 8 to 12).
static const struct {
    int32_t  Type;
    uint32_t Mask;
} kNoWindows[3] = {
    { 0x13, 0x03ff0000u },
    { 0x14, 0x03ff0000u },
    { 0x1f, 0x03ff0000u },
};

// 0x00313d78: the effect's scale by the level an item rose to.
static const float kEffectScale[4] = { 0.0f, 0.1f, 0.4f, 1.0f };

// 0x00124d38: item i's level in a word of them.
static uint32_t item_level(uint32_t word, int32_t item)
{
    return (word >> (2 * item)) & 3u;
}

// ---------------------------------------------------------- the infos

int loader_body_damage(uint8_t *chunk)
{
    BodyDamageInfo *info;
    bNode *last;

    if (bchunk_u32(chunk) != BODY_DAMAGE_ID)
        return 0;
    info = (BodyDamageInfo *)(void *)(chunk + 8);
    last = BodyDamageInfoList.prev;
    last->next = &info->Node;
    info->Node.prev = last;
    BodyDamageInfoList.prev = &info->Node;
    info->Node.next = &BodyDamageInfoList;
    info->pKeys = (uint32_t *)(void *)(info + 1);
    info->pVertexIndices = NULL;
    return 1;
}

int unloader_body_damage(uint8_t *chunk)
{
    BodyDamageInfo *info;

    if (bchunk_u32(chunk) != BODY_DAMAGE_ID)
        return 0;
    info = (BodyDamageInfo *)(void *)(chunk + 8);
    info->Node.prev->next = info->Node.next;
    info->Node.next->prev = info->Node.prev;
    return 1;
}

BodyDamageInfo *find_body_damage_info(uint32_t name_hash)
{
    bNode *n;

    for (n = BodyDamageInfoList.next; n != &BodyDamageInfoList; n = n->next) {
        BodyDamageInfo *info = (BodyDamageInfo *)(void *)n;

        if (info->NameHash == name_hash)
            return info;
    }
    return NULL;
}

// ------------------------------------------------------- the body damage

// GetModelNumVertices, 0x00104290: the solid's NumVerts, 0 without one.
static int32_t model_num_vertices(const eModel *m)
{
    const eSolid *s = (const eSolid *)m->Solid;

    return s != NULL ? s->NumVerts : 0;
}

// BodyDamageModel::CallDamageVertexFunction. GetModelNumVertices is
// called and not kept.
static void model_call_vertex_function(BodyDamageModel *m)
{
    if (m->pBodyDamageInfo == NULL)
        return;
    m->RepeatCount = 0;
    m->KeyNum = 0;
    if (gBodyDamageVertexWalkFn != NULL)
        gBodyDamageVertexWalkFn(m);
}

static void model_init(BodyDamageModel *m, BodyDamage *b, eModel *model,
                       const char *name, int32_t polys_only)
{
    BodyDamageInfo *info;

    m->pBodyDamageInfo = NULL;
    m->pBodyDamage = b;
    m->DamagePolysOnly = polys_only;
    m->pModel = model;
    m->NumVertices = model_num_vertices(model);
    if (m->NumVertices == 0)
        return;
    info = find_body_damage_info(bchunk_hash(name));
    m->pBodyDamageInfo = info;
    if (info == NULL)
        return;
    if (m->NumVertices != info->NumVertices) {
        m->pBodyDamageInfo = NULL;
        return;
    }
    model_call_vertex_function(m);
}

// The name is the car's and is not kept.
void bodydamage_construct(BodyDamage *b, const char *name)
{
    bNode *last = BodyDamageList.prev;

    (void)name;
    last->next = &b->Node;
    b->Node.prev = last;
    BodyDamageList.prev = &b->Node;
    b->Node.next = &BodyDamageList;
    memset(b->CompressedDamageAmounts, 0, BODYDAMAGE_ZONES);
    memset(b->CompressedAppliedDamageAmounts, 0, BODYDAMAGE_ZONES);
    b->CompressedTotalDamage = 0;
    b->CompressedTotalAppliedDamage = 0;
    b->NumBodyDamageModels = 0;
    b->pALevelBodyDamageInfo = NULL;
}

void bodydamage_destruct(BodyDamage *b)
{
    bodydamage_repair_all(b);
    b->Node.prev->next = b->Node.next;
    b->Node.next->prev = b->Node.prev;
}

void bodydamage_set_alevel_info(BodyDamage *b, const char *name)
{
    b->pALevelBodyDamageInfo = find_body_damage_info(bchunk_hash(name));
}

void bodydamage_add_model(BodyDamage *b, eModel *m, const char *name,
                          int32_t polys_only)
{
    int32_t n = b->NumBodyDamageModels;

    b->NumBodyDamageModels = n + 1;
    model_init(&b->BodyDamageModels[n], b, m, name, polys_only);
}

void bodydamage_set_damage(BodyDamage *b, int32_t zone, float amount)
{
    uint8_t *p = &b->CompressedDamageAmounts[zone];
    int32_t v;

    if (1.0f < amount)
        amount = 1.0f;
    if (amount < 0.0f)
        amount = 0.0f;
    v = ee_trunc_w(amount * 128.0f);
    b->CompressedTotalDamage =
        (uint16_t)(b->CompressedTotalDamage + v - *p);
    *p = (uint8_t)v;
}

void bodydamage_repair_all(BodyDamage *b)
{
    int32_t i;

    for (i = 0; i < BODYDAMAGE_ZONES; i++)
        bodydamage_set_damage(b, i, 0.0f);
    b->CompressedTotalDamage = 0;
    bodydamage_apply_damage(b);
}

// The point over the box, as 0..1 each way, and the eighth it falls in
// each way, clamped to 0..7. The four triangles the box's diagonals make
// are the sides: 1-8 at the far x, counting down; 9-16 at the near y; 16-23
// at the near x; 24-31 at the far y. Zone 0 is never one.
int32_t bodydamage_get_zone(const BodyDamage *b, const float *at)
{
    const BodyDamageInfo *info = b->pALevelBodyDamageInfo;
    float u, v;
    int32_t iu, iv;

    if (info == NULL)
        return -1;
    u = ee_div(at[0] - info->BBoxMin.x, info->BBoxMax.x - info->BBoxMin.x);
    v = ee_div(at[1] - info->BBoxMin.y, info->BBoxMax.y - info->BBoxMin.y);
    iu = ee_trunc_w(u * 8.0f);
    iv = ee_trunc_w(v * 8.0f);
    if (iu < 0)
        iu = 0;
    if (iv < 0)
        iv = 0;
    if (7 < iv)
        iv = 7;
    if (7 < iu)
        iu = 7;
    if (!(v < u)) {
        if (!(1.0f - v < u))
            return iv + 16;
        return iu + 24;
    }
    if (!(1.0f - v < u))
        return 16 - iu;
    return 8 - iv;
}

// The same zone, by the demo's code, which retail keeps for this.
float bodydamage_get_damage_amount(const BodyDamage *b, const float *at)
{
    int32_t zone;

    if (b->pALevelBodyDamageInfo == NULL)
        return 0.0f;
    zone = bodydamage_get_zone(b, at);
    return (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;
}

float bodydamage_get_visible_damage_amount_at(const BodyDamage *b,
                                              const float *at)
{
    if (RaceParametersDamageEnabled == 0)
        return 0.0f;
    return bodydamage_get_damage_amount(b, at);
}

float bodydamage_get_visible_damage_amount(const BodyDamage *b,
                                           int32_t zone)
{
    if (RaceParametersDamageEnabled == 0)
        return 0.0f;
    return (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;
}

uint8_t bodydamage_get_compressed_visible_damage_amount(const BodyDamage *b,
                                                        int32_t zone)
{
    if (RaceParametersDamageEnabled == 0)
        return 0;
    return b->CompressedDamageAmounts[zone];
}

float bodydamage_get_visible_total_damage(const BodyDamage *b)
{
    if (RaceParametersDamageEnabled == 0)
        return 0.0f;
    // `lhu`, `mtc1`, `cvt.s.w`: the halfword is widened unsigned and then
    // converted as a signed word, which for 16 bits is the same thing.
    return (float)(int32_t)b->CompressedTotalDamage * TOTAL_SCALE;
}

void bodydamage_apply_damage(BodyDamage *b)
{
    float applied =
        (float)(int32_t)b->CompressedTotalAppliedDamage * TOTAL_SCALE;
    float visible = bodydamage_get_visible_total_damage(b);
    uint16_t total;
    int32_t i;

    if (visible == applied)
        return;
    if (!(APPLY_TOLERANCE < fabsf(bodydamage_get_visible_total_damage(b)
                                  - applied))
        && bodydamage_get_visible_total_damage(b) != 0.0f)
        return;
    for (i = 0; i < b->NumBodyDamageModels; i++)
        model_call_vertex_function(&b->BodyDamageModels[i]);
    total = 0;
    for (i = 0; i < BODYDAMAGE_ZONES; i++) {
        uint8_t v = bodydamage_get_compressed_visible_damage_amount(b, i);

        b->CompressedAppliedDamageAmounts[i] = v;
        total = (uint16_t)(total + v);
    }
    b->CompressedTotalAppliedDamage = total;
}

void bodydamage_set_environment_mapping(BodyDamage *b, uint32_t hash,
                                        int32_t on)
{
    int32_t i;

    for (i = 0; i < b->NumBodyDamageModels; i++)
        emodel_set_environment_mapping(b->BodyDamageModels[i].pModel, hash,
                                       on);
}

// -------------------------------------------------------- the car damage

CarDamage *cardamage_construct(void *mem, Car *c)
{
    CarDamage *d = (CarDamage *)mem;
    int32_t i;

    bodydamage_construct(&d->TheBodyDamage, c->pCarTypeInfo->BaseModelName);
    d->BreakableCarItemDamageAmounts = 0;
    d->AppliedBreakableCarItemDamageAmounts = 0;
    d->pCar = c;
    d->CarBaseNameHash = bchunk_hash(c->pCarTypeInfo->BaseModelName);
    for (i = CARDAMAGE_ITEMS - 1; i >= 0; i--)
        d->ItemZones[i] = -1;
    return d;
}

void cardamage_destroy(CarDamage *d, int32_t flags)
{
    d->BreakableCarItemDamageAmounts = 0;
    cardamage_apply_damage(d);
    bodydamage_destruct(&d->TheBodyDamage);
    if (flags & 1)
        bFree(d);
}

void cardamage_find_item_parts(CarDamage *d)
{
    int32_t i;

    for (i = 0; i < CARDAMAGE_ITEMS; i++) {
        ePositionMarker *m;

        d->ItemZones[i] = -1;
        m = eFindPositionMarker(BreakableCarItemInfos[i].PositionHash,
                                d->CarBaseNameHash, NULL);
        if (m != NULL)
            d->ItemZones[i] =
                (int8_t)bodydamage_get_zone(&d->TheBodyDamage, m->Position);
    }
}

void cardamage_add_damage(CarDamage *d, const bVector3 *at, float amount)
{
    float part;
    int32_t zone, i;

    if (RaceParametersDamageEnabled == 0 || amount < MIN_HIT)
        return;
    zone = bodydamage_get_zone(&d->TheBodyDamage, &at->x);
    if (zone < 0)
        return;
    cardamage_add_zone(d, zone, amount, amount);
    part = amount * 0.5f;
    for (i = 1; i < 5; i++) {
        cardamage_add_zone(d, (zone + i) & 31, part, amount);
        cardamage_add_zone(d, (zone - i) & 31, part, amount);
        part *= 0.5f;
    }
    cardamage_apply_damage(d);
}

uint32_t cardamage_compute_item_states(const CarDamage *d)
{
    uint32_t states = 0;
    int32_t i, k, type;

    for (i = 0; i < CARDAMAGE_ITEMS; i++) {
        const float *t = BreakableCarItemInfos[i].Threshold;
        float v;

        if (d->ItemZones[i] < 0)
            continue;
        v = bodydamage_get_visible_damage_amount(&d->TheBodyDamage,
                                                 d->ItemZones[i]);
        k = 3;
        if (v < t[3])
            for (k = 2; k > 0 && v < t[k]; k--)
                ;
        states |= (uint32_t)k << (2 * i);
    }
    type = d->pCar->pRideInfo->Type;
    for (i = 0; i < 3; i++)
        if (kNoWindows[i].Type == type)
            states &= ~kNoWindows[i].Mask;
    return states;
}

void cardamage_add_zone(CarDamage *d, int32_t zone, float amount,
                        float impact)
{
    BodyDamage *b = &d->TheBodyDamage;
    float old = (float)b->CompressedDamageAmounts[zone] * ZONE_SCALE;
    float now = old + amount;
    uint32_t states;
    int32_t i;

    // `max.s` with 0, then `min.s` with 1.
    if (now < 0.0f)
        now = 0.0f;
    if (1.0f < now)
        now = 1.0f;
    if (old == now)
        return;
    bodydamage_set_damage(b, zone, now);
    states = cardamage_compute_item_states(d);
    if (states == d->BreakableCarItemDamageAmounts)
        return;
    // Too light a hit to break anything: the zone as it was.
    if (impact < MIN_BREAK) {
        bodydamage_set_damage(b, zone, old);
        return;
    }
    for (i = 0; i < CARDAMAGE_ITEMS; i++) {
        uint32_t level = item_level(states, i);
        int32_t fx;

        if (level == item_level(d->BreakableCarItemDamageAmounts, i))
            continue;
        if (level == 1)
            collision_sound_play_glass(&d->pCar->State.Position);
        fx = BreakableCarItemInfos[i].Effect;
        if (fx != 0 && gCarTriggerEffectFn != NULL)
            gCarTriggerEffectFn(d->pCar, (CarEffect)fx, kEffectScale[level],
                                0, NULL);
    }
    d->BreakableCarItemDamageAmounts = states;
}

void cardamage_rethink_damage(CarDamage *d)
{
    d->BreakableCarItemDamageAmounts = cardamage_compute_item_states(d);
    cardamage_apply_damage(d);
}

void cardamage_apply_damage(CarDamage *d)
{
    int32_t i;

    bodydamage_apply_damage(&d->TheBodyDamage);
    if (d->BreakableCarItemDamageAmounts
        == d->AppliedBreakableCarItemDamageAmounts)
        return;
    for (i = 0; i < CARDAMAGE_ITEMS; i++) {
        uint32_t level = item_level(d->BreakableCarItemDamageAmounts, i);

        if (level == item_level(d->AppliedBreakableCarItemDamageAmounts, i))
            continue;
        if (BreakableCarItemInfos[i].EnvMapped)
            bodydamage_set_environment_mapping(
                &d->TheBodyDamage, BreakableCarItemInfos[i].PositionHash,
                level == 0);
        d->AppliedBreakableCarItemDamageAmounts =
            (d->AppliedBreakableCarItemDamageAmounts & ~(3u << (2 * i)))
            | level << (2 * i);
    }
    carrenderinfo_update_car_replacement_textures(d->pCar->pRenderInfo);
}

void cardamage_wreck(CarDamage *d)
{
    int32_t i;

    for (i = 0; i < BODYDAMAGE_ZONES; i++)
        cardamage_add_zone(d, i, 1.0f, WRECK_IMPACT);
    cardamage_rethink_damage(d);
}

void cardamage_repair_all(CarDamage *d)
{
    bodydamage_repair_all(&d->TheBodyDamage);
    cardamage_rethink_damage(d);
}
