// carrenderinfo -- see carrenderinfo.h.

#include "carrenderinfo.h"

#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "bmem.h"
#include "epositionmarker.h"
#include "esolid.h"
#include "eview.h"
#include "gameflow.h"
#include "texturepack.h"
#include "trackflow.h"

BSlotPool *CarEmitterPositionSlotPool;
BSlotPool *eLightFlareSlotPool;
void      *TestRenderInfo;

void (*gCarAssignAnimatedDriverFn)(Car *c, const char *model_name);
void (*gCarUnAssignAnimatedDriverFn)(Car *c);
void (*gBodyDamageSetALevelInfoFn)(BodyDamage *bd, const char *name);
void (*gBodyDamageAddModelFn)(BodyDamage *bd, eModel *m, const char *name,
                              int32_t flag);
void (*gAfxGetEmittersFn)(bNode *list, uint32_t effect_hash);
void (*gAcidEmitterDeleteFn)(bNode *emitter, int32_t flags);

// 0x002dfd40 as the static constructor (0x00124528) leaves it.
CarPartCullInfo CarPartCullInfoTable[NUM_CULLABLE_CAR_PARTS] = {
    { CULLABLE_CAR_PART_TIRE_FL, "CULLABLE_CAR_PART_TIRE_FL", 0, 3,
      { { -0.01f, -1.0f, 0.0f, 0.0f }, { 0.08f, 0.15f, 1.0f, 0.0f },
        { -1.0f, 0.0f, 2.0f, 0.0f } },
      { 0.1f, 0.0f, 0.05f, 0.0f } },
    { CULLABLE_CAR_PART_TIRE_FR, "CULLABLE_CAR_PART_TIRE_FR", 0, 3,
      { { -0.01f, 1.0f, 0.0f, 0.0f }, { 0.08f, -0.15f, 1.0f, 0.0f },
        { -1.0f, 0.0f, 2.0f, 0.0f } },
      { 0.1f, 0.0f, 0.05f, 0.0f } },
    { CULLABLE_CAR_PART_TIRE_RR, "CULLABLE_CAR_PART_TIRE_RR", 0, 3,
      { { 0.01f, 1.0f, 0.0f, 0.0f }, { -0.08f, -0.15f, 1.0f, 0.0f },
        { 0.447214f, 0.0f, 0.335f, 0.0f } },
      { 0.1f, 0.0f, 0.05f, 0.0f } },
    { CULLABLE_CAR_PART_TIRE_RL, "CULLABLE_CAR_PART_TIRE_RL", 0, 3,
      { { 0.01f, -1.0f, 0.0f, 0.0f }, { -0.08f, 0.15f, 1.0f, 0.0f },
        { 0.447214f, 0.0f, 0.335f, 0.0f } },
      { 0.1f, 0.0f, 0.05f, 0.0f } },
    { CULLABLE_CAR_PART_TIRE_BLURS_LEFT, "CULLABLE_CAR_PART_TIRE_BLURS_LEFT",
      1, 1, { { 0.0f, -1.0f, 0.0f, 0.0f } }, { 0.0f, 0.0f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_TIRE_BLURS_RIGHT, "CULLABLE_CAR_PART_TIRE_BLURS_RIGHT",
      1, 1, { { 0.0f, 1.0f, 0.0f, 0.0f } }, { 0.0f, 0.0f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_BRAKE_FL, "CULLABLE_CAR_PART_BRAKE_FL", 1, 2,
      { { 0.22f, -1.0f, 0.0f, 0.0f }, { -0.22f, -1.0f, 0.0f, 0.0f } },
      { 0.0f, 0.05f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_BRAKE_FR, "CULLABLE_CAR_PART_BRAKE_FR", 1, 2,
      { { 0.22f, 1.0f, 0.0f, 0.0f }, { -0.22f, 1.0f, 0.0f, 0.0f } },
      { 0.0f, 0.05f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_BRAKE_RR, "CULLABLE_CAR_PART_BRAKE_RR", 1, 2,
      { { 0.22f, 1.0f, 0.0f, 0.0f }, { -0.22f, 1.0f, 0.0f, 0.0f } },
      { 0.0f, 0.05f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_BRAKE_RL, "CULLABLE_CAR_PART_BRAKE_RL", 1, 2,
      { { 0.22f, -1.0f, 0.0f, 0.0f }, { -0.22f, -1.0f, 0.0f, 0.0f } },
      { 0.0f, 0.05f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_SIDE_FRONT, "CULLABLE_CAR_PART_SIDE_FRONT", 0, 1,
      { { -1.0f, 0.0f, 0.0f, 0.0f } }, { 0.0f, 0.0f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_SIDE_REAR, "CULLABLE_CAR_PART_SIDE_REAR", 0, 1,
      { { 1.0f, 0.0f, 0.0f, 0.0f } }, { 0.0f, 0.0f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_UNDERNEATH, "CULLABLE_CAR_PART_UNDERNEATH", 1, 2,
      { { -0.07f, 0.0f, 1.0f, 0.0f }, { 0.07f, 0.0f, 1.0f, 0.0f } },
      { 0.05f, 0.05f, 0.0f, 0.0f } },
    { CULLABLE_CAR_PART_SHADOW, "CULLABLE_CAR_PART_SHADOW", 1, 1,
      { { 0.0f, 0.0f, -1.0f, 0.0f } }, { 0.0f, 0.0f, 0.0f, 0.0f } },
};

// The CARFX_ names of 0x002e02b0, whose hashes InitCarEffects fills in
// beside them; the emitter lists are in this order.
static const char *const kCarFxNames[CARRENDERINFO_NUM_EMITTERS] = {
    "CARFX_NONE", "CARFX_DRIVE_OVER", "CARFX_DRIVE_OVER2",
    "CARFX_SKID_SMOKE", "CARFX_TIRE_SPEW", "CARFX_BOTTOM_OUT",
    "CARFX_DAM_RADIATOR", "CARFX_DAM_ENGINE", "CARFX_BLOWN_TIRE",
    "CARFX_DRIVE_ON_FLAT_TIRE", "CARFX_NITRO", "CARFX_EXHAUST_SMOKE",
    "CARFX_BREAK_SIDE_MIRROR_LEFT", "CARFX_BREAK_SIDE_MIRROR_RIGHT",
    "CARFX_BREAK_LICENSE_PLATE_FRONT", "CARFX_BREAK_LICENSE_PLATE_RIGHT",
    "CARFX_BREAK_HEADLIGHT_LEFT", "CARFX_BREAK_HEADLIGHT_RIGHT",
    "CARFX_BREAK_BRAKELIGHT_LEFT", "CARFX_BREAK_BRAKELIGHT_RIGHT",
    "CARFX_BREAK_WINDSHIELD", "CARFX_BREAK_WINDOW_REAR",
    "CARFX_BREAK_WINDOW_LEFT_FRONT", "CARFX_BREAK_WINDOW_LEFT_REAR",
    "CARFX_BREAK_WINDOW_RIGHT_FRONT", "CARFX_BREAK_WINDOW_RIGHT_REAR",
};

// 0x002e01f8, sixteen bytes a row: a flare's direction by the second byte
// of its marker's Param. Retail has eleven; a larger byte reads on into the
// CARFX_ table and gets pointers for floats, and the port gives it no
// direction. The first six are data. The static constructor (0x00124528)
// writes the rest, and gives the eighth an x of 0.95 (gp-32156).
#define NUM_FLARE_DIRECTIONS 11
static const float kFlareDirections[NUM_FLARE_DIRECTIONS][3] = {
    {  1.0f,  0.0f, 0.0f }, { -1.0f, 0.0f, 0.0f },
    {  0.0f,  1.0f, 0.0f }, {  0.0f, -1.0f, 0.0f },
    {  1.0f,  0.0f, 0.0f }, {  0.0f,  1.0f, 0.0f },
    {  0.0f,  0.0f, 0.0f }, { 0.95f,  0.0f, 0.0f },
    {  0.0f,  0.0f, 0.0f }, {  0.0f,  0.0f, 0.0f },
    {  0.0f,  0.0f, 0.0f },
};

// 0x002e0380: a window's texture by its damage level, 0 to 3.
static const uint32_t kWindowDamageHashes[4] = {
    0x834b8017u,    // WINDOW
    0x0a155545u,    // WINDOW_DAMAGE0
    0x0a155546u,    // WINDOW_DAMAGE1
    0x0a155547u,    // WINDOW_DAMAGE2
};

// 0x002e01a0: BrokenLightFlags' bits, the four lamps then both brake
// lights together.
static const uint32_t kBrokenLightBits[5] = { 1, 2, 4, 8, 16 };

// Marker names (bStringHash of the upper-case name).
#define H_WINDOW_FRONT              0x7b220ddfu
#define H_WINDOW_REAR               0x1b0763a0u
#define H_WINDOW_LEFT_FRONT         0xe7e4ef49u
#define H_WINDOW_LEFT_REAR          0x4cdebfcau
#define H_WINDOW_RIGHT_FRONT        0x60f8b13cu
#define H_WINDOW_RIGHT_REAR         0x0ab88f5du
#define H_CARSKIN                   0xd6d6080au
#define H_SHADOWRAMP                0xbadb4475u
#define H_FLARE_HEADLIGHT_RIGHT     0x4ae7f96fu
#define H_FLARE_HEADLIGHT_LEFT      0xacec665cu
#define H_FLARE_BRAKELIGHT_RIGHT    0x5f09c5e2u
#define H_FLARE_BRAKELIGHT_LEFT     0x7efcf06fu
#define H_FLARE_BRAKELIGHT_MIDDLE   0x34970013u
#define H_FLARE_REVERSELIGHT_RIGHT  0x944e5339u
#define H_FLARE_REVERSELIGHT_LEFT   0xbea9aee6u
#define H_COPLIGHTRED               0x1e4150b4u
#define H_COPLIGHTBLUE              0xe662c161u
#define H_COPLIGHTWHITE             0xb4348dbau
#define H_HEADLIGHT_RIGHT           0xa532fc46u
#define H_HEADLIGHT_LEFT            0xa7e6ea53u
#define H_LICENSE_PLATE_FRONT       0x725758bfu
#define H_LICENSE_PLATE_REAR        0x494ed280u
#define H_ENGINE                    0x59a55db5u
#define H_RADIATOR                  0x68100815u
#define H_SIDE_MIRROR_LEFT          0x05f63788u
#define H_SIDE_MIRROR_RIGHT         0xc52bf01bu
#define H_BRAKELIGHT_RIGHT          0x02b52399u
#define H_BRAKELIGHT_LEFT           0xd947f346u
#define H_EXHAUST                   0xa5b28001u
#define H_EXHAUST_LEFT              0xa2799c2bu
#define H_EXHAUST_RIGHT             0xf21be91eu

// TestRenderInfo's texture, an unnamed hash.
#define TEST_RENDER_INFO_HASH       9024u

// bSPrintf into the 64 bytes at the bottom of the frame, then
// bStringHash, as every name here is made. The longest is a 31-character
// model name and "_LICENSE_PLATE_FRONT".
static uint32_t hashf(char *buf, const char *fmt, ...)
{
    va_list ap;

    va_start(ap, fmt);
    vsnprintf(buf, 64, fmt, ap);
    va_end(ap);
    return bchunk_hash(buf);
}

void carrenderinfo_init_slot_pools(void)
{
    if (CarEmitterPositionSlotPool == NULL)
        CarEmitterPositionSlotPool = bNewSlotPool(
            sizeof(CarEmitterPosition), 350, "CarEmitterPositionSlotPool", 16);
    if (eLightFlareSlotPool == NULL)
        eLightFlareSlotPool = bNewSlotPool(sizeof(eLightFlare), 160,
                                           "eLightFlareSlotPool", 16);
}

// ------------------------------------------------------------ the lists

// A position onto a bSList's tail. The list is its own sentinel: a node's
// next ends at it, and an empty list's Tail is the list.
static void slist_add_tail(bSList *l, bSNode *n)
{
    n->next = (bSNode *)(void *)l;
    l->Tail->next = n;
    l->Tail = n;
}

static CarEmitterPosition *new_emitter_position(bSList *l, float x, float y,
                                                float z)
{
    CarEmitterPosition *p = bSlotOMalloc(CarEmitterPositionSlotPool);

    slist_add_tail(l, &p->Node);
    p->X = x;
    p->Y = y;
    p->Z = z;
    return p;
}

static void node_add_tail(bNode *list, bNode *n)
{
    bNode *tail = list->prev;

    n->next = list;
    n->prev = tail;
    tail->next = n;
    list->prev = n;
}

static void node_unlink(bNode *n)
{
    n->prev->next = n->next;
    n->next->prev = n->prev;
}

// ------------------------------------------------------ the part culler

void carrenderinfo_init_part(CarPartCullerPart *culler, int32_t idx,
                             const bVector4 *point)
{
    CarPartCullInfo *info = &CarPartCullInfoTable[idx];
    int32_t k;

    for (k = 0; k < info->NumPlanes; k++) {
        bVector4 *p = &info->Planes[k];
        float d = (p->x * p->x + p->y * p->y) + p->z * p->z;

        if (0.01f < fabsf(1.0f - sqrtf(d))) {
            float s = 1.0f / sqrtf(d);

            p->x *= s;
            p->y *= s;
            p->z *= s;
            p->w *= s;
        }
    }
    culler[idx].Point = *point;
}

// ---------------------------------------------------- the skin and damage

void carrenderinfo_switch_skin(CarRenderInfo *ri, RideInfo *ride)
{
    const UsedCarTextureInfo *u = &ri->UsedTextureInfos;

    ri->pRideInfo = ride;
    cartypeinfo_get_used_car_texture_info(&ri->UsedTextureInfos, ride, 0);
    ri->TireReplacementTextureTable[0].OldNameHash = u->MappedSkinHash;
    ri->TireReplacementTextureTable[0].NewNameHash = u->ReplaceSkinHash;
    ri->DamageableSkinReplacementTextureTable[1].OldNameHash =
        u->MappedSkinBHash;
    ri->DamageableSkinReplacementTextureTable[1].NewNameHash =
        u->ReplaceSkinBHash;
    ri->SkinReplacementTextureTable[0].OldNameHash = u->MappedSkinHash;
    ri->SkinReplacementTextureTable[0].NewNameHash = u->ReplaceSkinHash;
    ri->SkinReplacementTextureTable[1].OldNameHash = u->MappedSkinBHash;
    ri->SkinReplacementTextureTable[1].NewNameHash = u->ReplaceSkinBHash;
    ri->DamageableSkinReplacementTextureTable[0].OldNameHash =
        u->MappedSkinHash;
    ri->DamageableSkinReplacementTextureTable[0].NewNameHash =
        u->ReplaceSkinHash;
}

// 0x00124d38 on the car's damage: item i's level, the two bits at 2i.
static uint32_t item_damage_level(const CarRenderInfo *ri, int32_t item)
{
    if (ri->pCar == NULL || ri->pCar->pCarDamage == NULL)
        return 0;
    return (ri->pCar->pCarDamage->BreakableCarItemDamageAmounts
            >> (2 * item)) & 3;
}

void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri)
{
    eReplacementTextureTable *t = ri->DamageableSkinReplacementTextureTable;
    int32_t i;

    // The six windows, WINDOW_FRONT (8) on, are entries 2 to 7.
    for (i = 0; i < 6; i++)
        t[2 + i].NewNameHash = kWindowDamageHashes[item_damage_level(ri, 8 + i)];

    // The four lamps, HEADLIGHT_LEFT (4) on, are entries 8 to 11: whole
    // below level 2, their _DAMAGE0 texture from it.
    ri->BrokenLightFlags = 0;
    for (i = 0; i < 4; i++) {
        if (item_damage_level(ri, 4 + i) < 2) {
            t[8 + i].NewNameHash = t[8 + i].OldNameHash;
        } else {
            t[8 + i].NewNameHash = i < 2
                ? ri->UsedTextureInfos.ReplaceHeadlightHash[2]
                : ri->UsedTextureInfos.ReplaceBrakelightHash[2];
            ri->BrokenLightFlags |= kBrokenLightBits[i];
        }
    }
    if ((ri->BrokenLightFlags & kBrokenLightBits[2])
        && (ri->BrokenLightFlags & kBrokenLightBits[3]))
        ri->BrokenLightFlags |= kBrokenLightBits[4];

    emodel_reconnect_texture_table(&ri->Body[0]);
    emodel_reconnect_texture_table(&ri->Body[1]);
    emodel_reconnect_texture_table(&ri->Body[2]);
}

// ------------------------------------------------------------ the flares

void carrenderinfo_create_car_light_flares(CarRenderInfo *ri)
{
    ePositionMarker *m = NULL;
    uint32_t model;

    if (ri->pCarTypeInfo == NULL)
        return;
    model = bchunk_hash(ri->pCarTypeInfo->BaseModelName);
    while ((m = eFindPositionMarker(0, model, m)) != NULL) {
        eLightFlare *f;
        int32_t type;
        int16_t flags = 0;
        uint32_t dir;

        switch (m->NameHash) {
        case H_FLARE_HEADLIGHT_RIGHT:
        case H_FLARE_HEADLIGHT_LEFT:     type = 0; break;
        case H_FLARE_BRAKELIGHT_RIGHT:
        case H_FLARE_BRAKELIGHT_LEFT:
        case H_FLARE_BRAKELIGHT_MIDDLE:  type = 1; break;
        case H_FLARE_REVERSELIGHT_RIGHT:
        case H_FLARE_REVERSELIGHT_LEFT:  type = 2; break;
        case H_COPLIGHTRED:              type = 4; flags = 1; break;
        case H_COPLIGHTBLUE:             type = 5; flags = 1; break;
        case H_COPLIGHTWHITE:            type = 6; break;
        case H_HEADLIGHT_RIGHT:          type = 7; break;
        case H_HEADLIGHT_LEFT:           type = 8; break;
        default:                         continue;
        }

        dir = (m->Param >> 8) & 0xff;
        f = bSlotOMalloc(eLightFlareSlotPool);
        f->Type = (int8_t)type;
        f->Enabled = 1;
        f->Name[0] = 0;
        f->NameHash = m->NameHash;
        f->Flags = flags;
        f->PositionX = m->Position[0] - ri->BodyPivot.x;
        f->PositionY = m->Position[1] - ri->BodyPivot.y;
        f->PositionZ = m->Position[2] - ri->BodyPivot.z;
        f->pad0 = 0.0f;
        f->pad1 = 0.0f;
        if (dir < NUM_FLARE_DIRECTIONS) {
            f->DirectionX = kFlareDirections[dir][0];
            f->DirectionY = kFlareDirections[dir][1];
            f->DirectionZ = kFlareDirections[dir][2];
        } else {
            f->DirectionX = f->DirectionY = f->DirectionZ = 0.0f;
        }
        node_add_tail(&ri->LightFlareList, &f->Node);
    }
}

// ------------------------------------------------------ the constructor

static void init_model(eModel *m, uint32_t name_hash)
{
    emodel_init(m, name_hash);
}

// eModel's constructor, n times.
static void clear_models(eModel *m, int32_t n)
{
    int32_t i;

    for (i = 0; i < n; i++) {
        m[i].NameHash = 0;
        m[i].Solid = NULL;
    }
}

// eModel's destructor with `flags` -- 0 or 2, so never the slot -- over
// an array, last first.
static void delete_models(eModel *m, int32_t n, int32_t flags)
{
    int32_t i;

    for (i = n - 1; i >= 0; i--)
        emodel_delete(&m[i], flags);
}

// A rear part with no solid of its own draws the front's.
static void fall_back(eModel *rear, uint32_t front_hash)
{
    if (rear->Solid == NULL) {
        emodel_uninit(rear);
        emodel_init(rear, front_hash);
    }
}

static void wheel_vector(bVector4 *v, const WheelInfo *w)
{
    v->x = w->PositionX;
    v->y = w->PositionY;
    v->z = w->PositionZ;
    v->w = w->Radius;
}

static void mid4(bVector4 *d, const bVector4 *a, const bVector4 *b)
{
    d->x = (a->x + b->x) * 0.5f;
    d->y = (a->y + b->y) * 0.5f;
    d->z = (a->z + b->z) * 0.5f;
    d->w = (a->w + b->w) * 0.5f;
}

CarRenderInfo *carrenderinfo_construct(CarRenderInfo *ri, RideInfo *ride,
                                       Car *car)
{
    char buf[64];
    const CarTypeInfo *ct;
    const SkinInfo *skin;
    const UsedCarTextureInfo *u = &ri->UsedTextureInfos;
    const char *name;
    uint32_t light_material;
    int traffic;
    int32_t dmg_instance = 0, skin_instance = 0;
    int32_t i;
    uint32_t fa, fb, fc, ra, rb, rc;
    bVector3 box_min, box_max;
    bVector4 w[4], t4, t5, c, a, b, n;
    float s;

    // The models' constructors, each clearing its name and solid, from
    // Body to the tachometer's needle.
    clear_models(ri->Body, 4);
    clear_models(&ri->Tires[0][0], 6);
    clear_models(ri->TireBlur, 2);
    clear_models(ri->Brakes, 2);
    clear_models(ri->Wipers, 2);
    clear_models(ri->SideMirrors, 2);
    clear_models(ri->LicensePlates, 2);
    clear_models(&ri->Scuffs, 1);
    clear_models(&ri->Dashboard, 1);
    clear_models(&ri->DashboardWindow, 1);
    clear_models(&ri->DashboardWheel, 1);
    clear_models(&ri->SpeedometerNeedle, 1);
    clear_models(&ri->TachometerNeedle, 1);
    ri->LightFlareList.next = ri->LightFlareList.prev = &ri->LightFlareList;
    for (i = 0; i < CARRENDERINFO_NUM_EMITTERS; i++)
        ri->EmitterList[i].next = ri->EmitterList[i].prev = &ri->EmitterList[i];
    for (i = 0; i < CARRENDERINFO_NUM_EMITTER_POSITIONS; i++)
        ri->EmitterPositionList[i].Head = ri->EmitterPositionList[i].Tail =
            (bSNode *)(void *)&ri->EmitterPositionList[i];
    memset(ri->PartCuller, 0, sizeof ri->PartCuller);

    ri->pCar = car;
    ri->pAlphaInfo = NULL;
    ri->AlphaOverridden = 0;
    ri->pRideInfo = ride;
    ri->CarTimebaseStart = (uint32_t)bRandomI(8, &bDefaultSeed);

    ct = cartypeinfo_get(ride->Type);
    skin = cartypeinfo_get_skin_info(ride->Type, ride->SkinNumber, 1);
    ri->pCarTypeInfo = ct;
    carrenderinfo_switch_skin(ri, ri->pRideInfo);
    name = ct->BaseModelName;
    traffic = ct->UsageType == CAR_USAGE_TYPE_TRAFFIC;

    {
        eReplacementTextureTable *t = ri->DamageableSkinReplacementTextureTable;

        t[0].OldNameHash = u->MappedSkinHash;
        t[1].OldNameHash = u->MappedSkinBHash;
        t[2].OldNameHash = H_WINDOW_FRONT;
        t[3].OldNameHash = H_WINDOW_REAR;
        t[4].OldNameHash = H_WINDOW_LEFT_FRONT;
        t[5].OldNameHash = H_WINDOW_LEFT_REAR;
        t[6].OldNameHash = H_WINDOW_RIGHT_FRONT;
        t[7].OldNameHash = H_WINDOW_RIGHT_REAR;
        for (i = 0; i < 4; i++)
            t[8 + i].OldNameHash = u->MappedLightHash[i];
    }
    carrenderinfo_update_car_replacement_textures(ri);
    ri->TireReplacementTextureTable[1].OldNameHash = u->MappedTireHash;
    ri->DashReplacementTextureTable[0].OldNameHash = u->MappedDashSkinHash;
    ri->DashReplacementTextureTable[0].NewNameHash = u->ReplaceDashSkinHash;
    ri->TireReplacementTextureTable[1].NewNameHash = u->ReplaceTireHash;
    ri->TireReplacementTextureTable[2].OldNameHash = u->MappedTireBlurHash;
    ri->TireReplacementTextureTable[2].NewNameHash = u->ReplaceTireBlurHash;

    // Retail reads the skin unguarded; with no skin table loaded the port
    // has none, and asks for material 0.
    light_material = skin != NULL ? skin->LightMaterialNameHash : 0;
    ri->pCarSkinLightMaterial = get_light_material(light_material);

    // The four bodies, A to D -- a traffic car's are A, A, B and C. The
    // two whole ones of a car that dents are its instance's own.
    for (i = 0; i < 4; i++) {
        eModel *m = &ri->Body[i];
        int letter = 'A' + i;

        if (traffic)
            letter = i == 0 ? 'A' : 'A' + i - 1;
        if (ri->pRideInfo->CanBeVertexDamaged && ri->pRideInfo->InstanceIndex
            && i < 2)
            init_model(m, hashf(buf, "%s_%c%d", name, letter,
                                ri->pRideInfo->InstanceIndex));
        else
            init_model(m, hashf(buf, "%s_%c", name, letter));
        if (i >= 2 && !traffic)
            emodel_rename_texture(m, u->MappedSkinHash, u->MappedSkinBHash);
        if (i < 3)
            emodel_attach_replacement_texture_table(
                m, ri->DamageableSkinReplacementTextureTable, 12,
                dmg_instance++);
        else
            emodel_attach_replacement_texture_table(
                m, ri->SkinReplacementTextureTable, 2, skin_instance++);
    }

    // The tyres, three levels of detail front and rear; a traffic car's
    // third is its second.
    fa = hashf(buf, "%s_TIRE_FRONT_A", name);
    fb = hashf(buf, "%s_TIRE_FRONT_B", name);
    fc = hashf(buf, "%s_TIRE_FRONT_C", name);
    ra = hashf(buf, "%s_TIRE_REAR_A", name);
    rb = hashf(buf, "%s_TIRE_REAR_B", name);
    rc = hashf(buf, "%s_TIRE_REAR_C", name);
    if (traffic) {
        fc = fb;
        rc = rb;
    }
    init_model(&ri->Tires[0][0], fa);
    init_model(&ri->Tires[1][0], fb);
    init_model(&ri->Tires[2][0], fc);
    init_model(&ri->Tires[0][1], ra);
    init_model(&ri->Tires[1][1], rb);
    init_model(&ri->Tires[2][1], rc);
    fall_back(&ri->Tires[0][1], fa);
    fall_back(&ri->Tires[1][1], fb);
    fall_back(&ri->Tires[2][1], fc);
    for (i = 0; i < 3; i++)
        emodel_attach_replacement_texture_table(
            &ri->Tires[i][0], ri->TireReplacementTextureTable, 3, i);
    for (i = 0; i < 3; i++)
        emodel_attach_replacement_texture_table(
            &ri->Tires[i][1], ri->TireReplacementTextureTable, 3, 3 + i);
    for (i = 0; i < 3; i++)
        emodel_replace_light_material(&ri->Tires[i][0], H_CARSKIN,
                                      light_material);
    for (i = 0; i < 3; i++)
        emodel_replace_light_material(&ri->Tires[i][1], H_CARSKIN,
                                      light_material);

    // The brakes, wipers and side mirrors in the skin; the plates keep
    // their own textures.
    fa = hashf(buf, "%s_BRAKE_FRONT", name);
    ra = hashf(buf, "%s_BRAKE_REAR", name);
    init_model(&ri->Brakes[0], fa);
    init_model(&ri->Brakes[1], ra);
    fall_back(&ri->Brakes[1], fa);
    emodel_attach_replacement_texture_table(
        &ri->Brakes[0], ri->SkinReplacementTextureTable, 2, skin_instance++);
    emodel_attach_replacement_texture_table(
        &ri->Brakes[1], ri->SkinReplacementTextureTable, 2, skin_instance++);
    emodel_replace_light_material(&ri->Brakes[0], H_CARSKIN, light_material);
    emodel_replace_light_material(&ri->Brakes[1], H_CARSKIN, light_material);

    fa = hashf(buf, "%s_WIPER_LEFT", name);
    ra = hashf(buf, "%s_WIPER_RIGHT", name);
    init_model(&ri->Wipers[0], fa);
    init_model(&ri->Wipers[1], ra);
    emodel_attach_replacement_texture_table(
        &ri->Wipers[0], ri->SkinReplacementTextureTable, 2, skin_instance++);
    emodel_attach_replacement_texture_table(
        &ri->Wipers[1], ri->SkinReplacementTextureTable, 2, skin_instance++);
    emodel_replace_light_material(&ri->Wipers[0], H_CARSKIN, light_material);
    emodel_replace_light_material(&ri->Wipers[1], H_CARSKIN, light_material);

    fa = hashf(buf, "%s_SIDE_MIRROR_LEFT", name);
    ra = hashf(buf, "%s_SIDE_MIRROR_RIGHT", name);
    init_model(&ri->SideMirrors[0], fa);
    init_model(&ri->SideMirrors[1], ra);
    emodel_attach_replacement_texture_table(
        &ri->SideMirrors[0], ri->SkinReplacementTextureTable, 2,
        skin_instance++);
    emodel_attach_replacement_texture_table(
        &ri->SideMirrors[1], ri->SkinReplacementTextureTable, 2,
        skin_instance++);
    emodel_replace_light_material(&ri->SideMirrors[0], H_CARSKIN,
                                  light_material);
    emodel_replace_light_material(&ri->SideMirrors[1], H_CARSKIN,
                                  light_material);

    fa = hashf(buf, "%s_LICENSE_PLATE_FRONT", name);
    ra = hashf(buf, "%s_LICENSE_PLATE_REAR", name);
    init_model(&ri->LicensePlates[0], fa);
    init_model(&ri->LicensePlates[1], ra);
    emodel_replace_light_material(&ri->LicensePlates[0], H_CARSKIN,
                                  light_material);
    emodel_replace_light_material(&ri->LicensePlates[1], H_CARSKIN,
                                  light_material);

    if (ri->pRideInfo->InstanceIndex)
        init_model(&ri->Scuffs, hashf(buf, "%s_SCUFFS%d", name,
                                      ri->pRideInfo->InstanceIndex));
    else
        init_model(&ri->Scuffs, hashf(buf, "%s_SCUFFS", name));

    // The dash, for the in-car view.
    fa = hashf(buf, "%s_DASH", name);
    fb = hashf(buf, "%s_DASH_WHEEL", name);
    fc = hashf(buf, "%s_DASH_WINDOW", name);
    ra = hashf(buf, "%s_SPEED_NEEDLE", name);
    rb = hashf(buf, "%s_TACH_NEEDLE", name);
    init_model(&ri->Dashboard, fa);
    init_model(&ri->DashboardWheel, fb);
    init_model(&ri->DashboardWindow, fc);
    init_model(&ri->SpeedometerNeedle, ra);
    init_model(&ri->TachometerNeedle, rb);
    emodel_attach_replacement_texture_table(
        &ri->Dashboard, ri->DashReplacementTextureTable, 1, 0);
    emodel_attach_replacement_texture_table(
        &ri->DashboardWheel, ri->DashReplacementTextureTable, 1, 1);
    emodel_replace_light_material(&ri->Dashboard, H_CARSKIN, light_material);
    emodel_replace_light_material(&ri->DashboardWheel, H_CARSKIN,
                                  light_material);
    emodel_replace_light_material(&ri->DashboardWindow, H_CARSKIN,
                                  light_material);

    // The wheels' blur, one for both ends or one for each.
    fa = hashf(buf, "%s_WHEEL_BLUR", name);
    init_model(&ri->TireBlur[0], fa);
    init_model(&ri->TireBlur[1], fa);
    if (ri->TireBlur[0].Solid == NULL) {
        fb = hashf(buf, "%s_WHEEL_BLUR_F", name);
        emodel_uninit(&ri->TireBlur[0]);
        emodel_init(&ri->TireBlur[0], fb);
    }
    if (ri->TireBlur[1].Solid == NULL) {
        fb = hashf(buf, "%s_WHEEL_BLUR_R", name);
        emodel_uninit(&ri->TireBlur[1]);
        emodel_init(&ri->TireBlur[1], fb);
    }
    emodel_attach_replacement_texture_table(
        &ri->TireBlur[0], ri->TireReplacementTextureTable, 3, 6);
    emodel_attach_replacement_texture_table(
        &ri->TireBlur[1], ri->TireReplacementTextureTable, 3, 7);

    // The shadow: the front end's in the front end, drawn later there.
    {
        int fe = gTrackFlowGameFlow != NULL
            && gTrackFlowGameFlow->current == BGF_IN_FRONTEND;

        ri->ShadowTexture = get_texture_info(
            hashf(buf, fe ? "%s_SHADOWFE" : "%s_SHADOWIG", name), 0, 0);
        ri->ShadowRampTexture = get_texture_info(H_SHADOWRAMP, 0, 0);
        if (ri->ShadowTexture != NULL)
            ((TextureInfo *)ri->ShadowTexture)->RenderingOrder = fe ? 5 : 3;
    }

    // A car in the world has a driver, and bodies that dent.
    if (ri->pCar != NULL) {
        if (gCarAssignAnimatedDriverFn != NULL)
            gCarAssignAnimatedDriverFn(ri->pCar, name);
        if (ri->pCar != NULL && ri->pCar->pCarDamage != NULL) {
            BodyDamage *bd = &ri->pCar->pCarDamage->TheBodyDamage;

            snprintf(buf, sizeof buf, "%s_A", name);
            if (gBodyDamageSetALevelInfoFn != NULL)
                gBodyDamageSetALevelInfoFn(bd, buf);
            if (ride->CanBeVertexDamaged) {
                static const char *const kBodyFmt[3] = {
                    "%s_A", "%s_B", "%s_C"
                };

                for (i = 0; i < 3; i++) {
                    snprintf(buf, sizeof buf, kBodyFmt[i], name);
                    if (gBodyDamageAddModelFn != NULL)
                        gBodyDamageAddModelFn(bd, &ri->Body[i], buf, 0);
                }
                snprintf(buf, sizeof buf, "%s_SCUFFS", name);
                if (gBodyDamageAddModelFn != NULL)
                    gBodyDamageAddModelFn(bd, &ri->Scuffs, buf, 0);
            } else {
                snprintf(buf, sizeof buf, "%s_SCUFFS", name);
                if (gBodyDamageAddModelFn != NULL)
                    gBodyDamageAddModelFn(bd, &ri->Scuffs, buf, 1);
            }
        }
    }

    // The body's pivot, the fourth row of its solid's pivot matrix.
    {
        const eSolid *solid = ri->Body[0].Solid;

        ri->BodyPivot.x = solid != NULL ? solid->PivotMatrix.v3.x : 0.0f;
        ri->BodyPivot.y = solid != NULL ? solid->PivotMatrix.v3.y : 0.0f;
        ri->BodyPivot.z = solid != NULL ? solid->PivotMatrix.v3.z : 0.0f;
    }

    carrenderinfo_create_car_light_flares(ri);

    // The box round the body and its mirrors, a tenth larger each way.
    // Retail's box for each model is uninitialised stack that a model with
    // no solid leaves alone; the port's starts empty, so such a model
    // adds nothing.
    bInitializeBoundingBox3(&ri->AABBMin, &ri->AABBMax);
    bInitializeBoundingBox3(&box_min, &box_max);
    emodel_get_bounding_box(&ri->Body[0], &box_min, &box_max);
    bExpandBoundingBox3Box(&ri->AABBMin, &ri->AABBMax, &box_min, &box_max);
    emodel_get_bounding_box(&ri->SideMirrors[0], &box_min, &box_max);
    bExpandBoundingBox3Box(&ri->AABBMin, &ri->AABBMax, &box_min, &box_max);
    emodel_get_bounding_box(&ri->SideMirrors[1], &box_min, &box_max);
    bExpandBoundingBox3Box(&ri->AABBMin, &ri->AABBMax, &box_min, &box_max);
    ri->AABBMin.x -= 0.1f;
    ri->AABBMin.y -= 0.1f;
    ri->AABBMin.z -= 0.1f;
    ri->AABBMax.x += 0.1f;
    ri->AABBMax.y += 0.1f;
    ri->AABBMax.z += 0.1f;

    // The culler's points: the wheels, the middles of each side, the
    // middle of the car, and the shadow's below it along the normal of
    // the wheels' plane.
    for (i = 0; i < 4; i++)
        wheel_vector(&w[i], &ct->Wheels[i]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_FL, &w[0]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_FR, &w[1]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_RR, &w[2]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_RL, &w[3]);
    mid4(&t4, &w[0], &w[3]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_BLURS_LEFT,
                            &t4);
    mid4(&t5, &w[1], &w[2]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_TIRE_BLURS_RIGHT,
                            &t5);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_BRAKE_FL, &w[0]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_BRAKE_FR, &w[1]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_BRAKE_RR, &w[2]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_BRAKE_RL, &w[3]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_SIDE_FRONT,
                            &w[0]);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_SIDE_REAR, &w[2]);
    mid4(&c, &t4, &t5);
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_UNDERNEATH, &c);

    a.x = w[0].x - w[1].x;
    a.y = w[0].y - w[1].y;
    a.z = w[0].z - w[1].z;
    a.w = w[0].w - w[1].w;
    b.x = w[1].x - w[2].x;
    b.y = w[1].y - w[2].y;
    b.z = w[1].z - w[2].z;
    b.w = w[1].w - w[2].w;
    n.x = a.y * b.z - b.y * a.z;
    n.y = a.z * b.x - b.z * a.x;
    n.z = a.x * b.y - b.x * a.y;
    n.w = a.w;
    s = 1.0f / sqrtf((n.x * n.x + n.y * n.y) + n.z * n.z);
    n.x *= s;
    n.y *= s;
    n.z *= s;
    n.w *= s;
    c.x += n.x * ct->Wheels[0].Radius;
    c.y += n.y * ct->Wheels[0].Radius;
    c.z += n.z * ct->Wheels[0].Radius;
    c.w += n.w * ct->Wheels[0].Radius;
    carrenderinfo_init_part(ri->PartCuller, CULLABLE_CAR_PART_SHADOW, &c);
    return ri;
}

// ------------------------------------------------------- the destructor

void carrenderinfo_delete(CarRenderInfo *ri, int32_t flags)
{
    int32_t i;

    if (gEWaitUntilRenderingDoneFn != NULL)
        gEWaitUntilRenderingDoneFn();
    if (ri->pCar != NULL && gCarUnAssignAnimatedDriverFn != NULL)
        gCarUnAssignAnimatedDriverFn(ri->pCar);
    if (ri->pAlphaInfo != NULL) {
        bFree(ri->pAlphaInfo);
        ri->AlphaOverridden = 0;
    }

    // ~bSList<CarEmitterPosition>, last list first: each position off
    // the head and back to its pool.
    for (i = CARRENDERINFO_NUM_EMITTER_POSITIONS - 1; i >= 0; i--) {
        bSList *l = &ri->EmitterPositionList[i];
        bSNode *sentinel = (bSNode *)(void *)l;

        while (l->Head != sentinel) {
            bSNode *n = l->Head;

            if (l->Tail == n)
                l->Tail = sentinel;
            l->Head = n->next;
            bSlotFree(CarEmitterPositionSlotPool, n);
        }
    }

    // ~bTList<AcidEmitter>: each emitter unlinked and deleted with 3.
    for (i = CARRENDERINFO_NUM_EMITTERS - 1; i >= 0; i--) {
        bNode *l = &ri->EmitterList[i];

        while (l->next != l) {
            bNode *n = l->next;

            node_unlink(n);
            if (gAcidEmitterDeleteFn == NULL)
                abort();
            gAcidEmitterDeleteFn(n, 3);
        }
    }

    // ~bTList<eLightFlare>: each flare back to its pool.
    while (ri->LightFlareList.next != &ri->LightFlareList) {
        bNode *n = ri->LightFlareList.next;

        node_unlink(n);
        bSlotFree(eLightFlareSlotPool, n);
    }

    // The models, last declared first.
    emodel_delete(&ri->TachometerNeedle, 2);
    emodel_delete(&ri->SpeedometerNeedle, 2);
    emodel_delete(&ri->DashboardWheel, 2);
    emodel_delete(&ri->DashboardWindow, 2);
    emodel_delete(&ri->Dashboard, 2);
    emodel_delete(&ri->Scuffs, 2);
    delete_models(ri->LicensePlates, 2, 0);
    delete_models(ri->SideMirrors, 2, 0);
    delete_models(ri->Wipers, 2, 0);
    delete_models(ri->Brakes, 2, 0);
    delete_models(ri->TireBlur, 2, 0);
    delete_models(&ri->Tires[0][0], 6, 0);
    delete_models(ri->Body, 4, 0);

    if (flags & 1)
        bFree(ri);
}

// ------------------------------------------------------ InitRenderInfo

void car_init_render_info(Car *c, RideInfo *ride)
{
    CarRenderInfo *ri;
    const CarTypeInfo *ct;
    const WheelInfo *w;
    ePositionMarker *m = NULL;
    uint32_t model;
    int32_t i;

    ri = carrenderinfo_construct(
        bMalloc(sizeof(CarRenderInfo), "CarRenderInfo", 0, 16), ride, c);
    c->pRenderInfo = ri;
    ct = c->pCarTypeInfo;
    w = ct->Wheels;
    model = bchunk_hash(ct->BaseModelName);

    // Nine positions from the wheels: the middle, the middles of the
    // front, the back and each side, and the wheels.
    new_emitter_position(&ri->EmitterPositionList[0], 0.0f, 0.0f, 0.0f);
    new_emitter_position(&ri->EmitterPositionList[1],
                         (w[0].PositionX + w[1].PositionX) * 0.5f,
                         (w[0].PositionY + w[1].PositionY) * 0.5f,
                         (w[0].PositionZ + w[1].PositionZ) * 0.5f);
    new_emitter_position(&ri->EmitterPositionList[2],
                         (w[3].PositionX + w[2].PositionX) * 0.5f,
                         (w[3].PositionY + w[2].PositionY) * 0.5f,
                         (w[3].PositionZ + w[2].PositionZ) * 0.5f);
    new_emitter_position(&ri->EmitterPositionList[3],
                         (w[0].PositionX + w[3].PositionX) * 0.5f,
                         (w[0].PositionY + w[3].PositionY) * 0.5f,
                         (w[0].PositionZ + w[3].PositionZ) * 0.5f);
    new_emitter_position(&ri->EmitterPositionList[4],
                         (w[1].PositionX + w[2].PositionX) * 0.5f,
                         (w[1].PositionY + w[2].PositionY) * 0.5f,
                         (w[1].PositionZ + w[2].PositionZ) * 0.5f);
    for (i = 0; i < 4; i++)
        new_emitter_position(&ri->EmitterPositionList[5 + i], w[i].PositionX,
                             w[i].PositionY, w[i].PositionZ);

    // The rest from the car's markers, in the body's space less its pivot;
    // a lamp goes on its pair's list and its own.
    while ((m = eFindPositionMarker(0, model, m)) != NULL) {
        int32_t l0 = -1, l1 = -1;
        float x, y, z;

        switch (m->NameHash) {
        case H_LICENSE_PLATE_FRONT: l0 = 26; break;
        case H_LICENSE_PLATE_REAR:  l0 = 27; break;
        case H_ENGINE:              l0 = 9;  break;
        case H_EXHAUST:
        case H_EXHAUST_LEFT:
        case H_EXHAUST_RIGHT:       l0 = 10; break;
        case H_RADIATOR:            l0 = 11; break;
        case H_WINDOW_FRONT:        l0 = 12; break;
        case H_WINDOW_REAR:         l0 = 13; break;
        case H_WINDOW_LEFT_FRONT:   l0 = 14; break;
        case H_WINDOW_LEFT_REAR:    l0 = 15; break;
        case H_WINDOW_RIGHT_FRONT:  l0 = 16; break;
        case H_WINDOW_RIGHT_REAR:   l0 = 17; break;
        case H_HEADLIGHT_LEFT:      l0 = 18; l1 = 20; break;
        case H_HEADLIGHT_RIGHT:     l0 = 18; l1 = 21; break;
        case H_BRAKELIGHT_LEFT:     l0 = 19; l1 = 22; break;
        case H_BRAKELIGHT_RIGHT:    l0 = 19; l1 = 23; break;
        case H_SIDE_MIRROR_LEFT:    l0 = 24; break;
        case H_SIDE_MIRROR_RIGHT:   l0 = 25; break;
        default: break;
        }
        x = m->Position[0] - ri->BodyPivot.x;
        y = m->Position[1] - ri->BodyPivot.y;
        z = m->Position[2] - ri->BodyPivot.z;
        if (l0 >= 0)
            new_emitter_position(&ri->EmitterPositionList[l0], x, y, z);
        if (l1 >= 0)
            new_emitter_position(&ri->EmitterPositionList[l1], x, y, z);
    }

    for (i = 0; i < CARRENDERINFO_NUM_EMITTERS; i++)
        if (gAfxGetEmittersFn != NULL)
            gAfxGetEmittersFn(&ri->EmitterList[i],
                              bchunk_hash(kCarFxNames[i]));

    TestRenderInfo = get_texture_info(TEST_RENDER_INFO_HASH, 1, 0);
}
