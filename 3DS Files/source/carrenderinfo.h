// carrenderinfo -- CarRenderInfo from retail's Car.obj: what a car draws
// with. One is made for every car when it is built (Car::InitRenderInfo)
// and holds the car's models by name, the replacement tables that paint
// them in its skin and its damage, its light flares, its effect emitters
// and where they sit, and the planes its parts are culled against.
//
//   Car::InitRenderInfo(RideInfo *)             0x0011dc80  1536 bytes
//   CarRenderInfo::CarRenderInfo(RideInfo *, Car *)  0x0011e860  4700
//   CarRenderInfo::~CarRenderInfo                0x0011fac0   928
//   CarRenderInfo::SwitchSkin(RideInfo *)        0x0011fe60   108
//   CarRenderInfo::UpdateCarReplacementTextures  0x0011ff68   456
//   CarRenderInfo::CreateCarLightFlares          0x00120360   632
//   the part culler's InitPart                   0x0011d580   200
//   ~bSList<CarEmitterPosition>                  0x00124b78   116
//   ~bTList<AcidEmitter>                         0x00124bf0   108
//   ~bTList<eLightFlare>                         0x00116f20   108
//
// Render (0x00120ef8) and the culler's two passes (0x0011d648, 0x0011d980)
// are the next slice's. Retail's is 2352 bytes to the demo's 1856: it adds
// the body's pivot, a broken-light mask, the part culler and a flag for
// OverRideAlpha, and the ctor's order is (RideInfo *, Car *) in both.
//
// What is not ported goes through a seam: the animated driver, the body
// damage's two methods, the AcidFX emitters, and the three the eModel and
// eSolid code already has (GetTextureInfo, elGetLightMaterial,
// FixStripSTs). A seam left NULL is skipped, save the AcidEmitter's
// deleting destructor, which aborts when an emitter list holds one: only
// the emitter seam can have put it there.
//
// Cross-check: tools/carrenderinfo_check.py. Write-up:
// docs/formats/car-render-info.md.

#ifndef CARRENDERINFO_H
#define CARRENDERINFO_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bslotpool.h"
#include "bvector.h"
#include "car.h"
#include "cardamage.h"
#include "cartypeinfo.h"
#include "emodel.h"
#include "scenery.h"

// ------------------------------------------------------------ the lists

// bSList's node and list: a singly linked list whose list is its own
// sentinel, Head where a node has its next.
typedef struct bSNode {
    struct bSNode *next;                    //  0
} bSNode;

typedef struct bSList {
    bSNode *Head;                           //  0
    bSNode *Tail;                           //  4
} bSList;

// CarEmitterPosition, 16 bytes, from CarEmitterPositionSlotPool: one place
// on the car, in the body's space less its pivot, that an effect comes
// out of.
typedef struct CarEmitterPosition {
    bSNode    Node;                         //  0
    float     X, Y, Z;                      //  4
} CarEmitterPosition;                       // 16

// eLightFlare, 80 bytes (.mdebug), from eLightFlareSlotPool. The renderer's
// type; the render info makes one for each light a car's markers name.
typedef struct eLightFlare {
    bNode     Node;                         //  0
    uint32_t  NameHash;                     //  8
    int8_t    Enabled;                      // 12
    int8_t    Type;                         // 13
    int16_t   Flags;                        // 14
    char      Name[32];                     // 16
    float     PositionX, PositionY, PositionZ;      // 48
    float     pad0;                         // 60
    float     DirectionX, DirectionY, DirectionZ;   // 64
    float     pad1;                         // 76
} eLightFlare;                              // 80

// ------------------------------------------------------ the part culler

// The fourteen parts, retail's own names (0x002adeb8 on).
enum {
    CULLABLE_CAR_PART_TIRE_FL,
    CULLABLE_CAR_PART_TIRE_FR,
    CULLABLE_CAR_PART_TIRE_RR,
    CULLABLE_CAR_PART_TIRE_RL,
    CULLABLE_CAR_PART_TIRE_BLURS_LEFT,
    CULLABLE_CAR_PART_TIRE_BLURS_RIGHT,
    CULLABLE_CAR_PART_BRAKE_FL,
    CULLABLE_CAR_PART_BRAKE_FR,
    CULLABLE_CAR_PART_BRAKE_RR,
    CULLABLE_CAR_PART_BRAKE_RL,
    CULLABLE_CAR_PART_SIDE_FRONT,
    CULLABLE_CAR_PART_SIDE_REAR,
    CULLABLE_CAR_PART_UNDERNEATH,
    CULLABLE_CAR_PART_SHADOW,
    NUM_CULLABLE_CAR_PARTS
};

// One part's entry in the table at 0x002dfd40, 80 bytes: the directions
// from which it can be seen, up to three, and a fourth vector the culler
// reads beside them. Retail's static constructor (0x00124528) fills it.
// Flag8 is the word at +8, 0 or 1, and only the culler reads it.
typedef struct CarPartCullInfo {
    int32_t      Id;                        //  0
    const char  *Name;                      //  4
    int32_t      Flag8;                     //  8
    int32_t      NumPlanes;                 // 12
    bVector4     Planes[3];                 // 16
    bVector4     Extra;                     // 64
} CarPartCullInfo;                          // 80

// The table itself, shared by every car. Each render info's constructor
// normalises the planes in place (see carrenderinfo_init_part), so only
// the first one built changes it.
extern CarPartCullInfo CarPartCullInfoTable[NUM_CULLABLE_CAR_PARTS];

// One part of a car's culler, 32 bytes: the point it is tested from, and
// three words the culler keeps, which the constructor zeroes.
typedef struct CarPartCullerPart {
    bVector4  Point;                        //  0
    uint32_t  State[4];                     // 16
} CarPartCullerPart;                        // 32

// ---------------------------------------------------------- the record

// Where the emitters and their positions are, by their effect: the
// CARFX_ names at 0x002e02b0, in order. The positions have two more, the
// licence plates.
#define CARRENDERINFO_NUM_EMITTERS          26
#define CARRENDERINFO_NUM_EMITTER_POSITIONS 28

struct CarRenderInfo {
    Car                *pCar;                          //    0
    RideInfo           *pRideInfo;                     //    4
    const CarTypeInfo  *pCarTypeInfo;                  //    8
    uint32_t            pad12;                         //   12
    bVector3            AABBMin;                       //   16
    bVector3            AABBMax;                       //   32
    bVector3            BodyPivot;                     //   48  retail's
    eModel              Body[4];                       //   64
    eModel              Tires[3][2];                   //  160  [lod][front, rear]
    eModel              TireBlur[2];                   //  304
    eModel              Brakes[2];                     //  352
    eModel              Wipers[2];                     //  400
    eModel              SideMirrors[2];                //  448
    eModel              LicensePlates[2];              //  496
    eModel              Scuffs;                        //  544
    eModel              Dashboard;                     //  568
    eModel              DashboardWindow;               //  592
    eModel              DashboardWheel;                //  616
    eModel              SpeedometerNeedle;             //  640
    eModel              TachometerNeedle;              //  664
    UsedCarTextureInfo  UsedTextureInfos;              //  688
    void               *ShadowTexture;                 //  860  TextureInfo *
    void               *ShadowRampTexture;             //  864
    void               *pCarSkinLightMaterial;         //  868
    bNode               LightFlareList;                //  872
    uint32_t            CarTimebaseStart;              //  880
    uint32_t            BrokenLightFlags;              //  884  retail's
    bNode               EmitterList[CARRENDERINFO_NUM_EMITTERS];   //  888
    bSList              EmitterPositionList[CARRENDERINFO_NUM_EMITTER_POSITIONS];
                                                       // 1096
    eReplacementTextureTable SkinReplacementTextureTable[2];     // 1320
    eReplacementTextureTable DamageableSkinReplacementTextureTable[12];
                                                       // 1376
    eReplacementTextureTable DashReplacementTextureTable[1];     // 1712
    eReplacementTextureTable TireReplacementTextureTable[3];     // 1740
    eReplacementTextureTable TireBlurReplacementTextureTable[2]; // 1824
    uint8_t             pad1880[8];                    // 1880
    CarPartCullerPart   PartCuller[NUM_CULLABLE_CAR_PARTS];      // 1888 retail's
    void               *pAlphaInfo;                    // 2336
    int32_t             AlphaOverridden;               // 2340 retail's
    uint8_t             pad2344[8];                    // 2344
};                                                     // 2352

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char carrenderinfo_layout_check[
    (sizeof(CarRenderInfo) == 2352
     && offsetof(CarRenderInfo, AABBMin) == 16
     && offsetof(CarRenderInfo, BodyPivot) == 48
     && offsetof(CarRenderInfo, Body) == 64
     && offsetof(CarRenderInfo, Tires) == 160
     && offsetof(CarRenderInfo, TireBlur) == 304
     && offsetof(CarRenderInfo, LicensePlates) == 496
     && offsetof(CarRenderInfo, Scuffs) == 544
     && offsetof(CarRenderInfo, TachometerNeedle) == 664
     && offsetof(CarRenderInfo, UsedTextureInfos) == 688
     && offsetof(CarRenderInfo, ShadowTexture) == 860
     && offsetof(CarRenderInfo, LightFlareList) == 872
     && offsetof(CarRenderInfo, BrokenLightFlags) == 884
     && offsetof(CarRenderInfo, EmitterList) == 888
     && offsetof(CarRenderInfo, EmitterPositionList) == 1096
     && offsetof(CarRenderInfo, SkinReplacementTextureTable) == 1320
     && offsetof(CarRenderInfo, DamageableSkinReplacementTextureTable) == 1376
     && offsetof(CarRenderInfo, DashReplacementTextureTable) == 1712
     && offsetof(CarRenderInfo, TireReplacementTextureTable) == 1740
     && offsetof(CarRenderInfo, TireBlurReplacementTextureTable) == 1824
     && offsetof(CarRenderInfo, PartCuller) == 1888
     && offsetof(CarRenderInfo, pAlphaInfo) == 2336
     && sizeof(CarEmitterPosition) == 16 && sizeof(eLightFlare) == 80
     && offsetof(eLightFlare, PositionX) == 48
     && offsetof(eLightFlare, DirectionX) == 64
     && sizeof(CarPartCullInfo) == 80 && sizeof(CarPartCullerPart) == 32)
    ? 1 : -1];
#endif

// --------------------------------------------------------- the globals

// CarEmitterPositionSlotPool (gp-23672), 350 slots of 16, which
// InitCarEffects (0x0011db90) makes, and eLightFlareSlotPool (gp-25184),
// 160 of 80, which eInitSlotPools (0x0010a108) makes. The port makes both
// in carrenderinfo_init_slot_pools; the rest of InitCarEffects is not
// ported.
extern BSlotPool *CarEmitterPositionSlotPool;
extern BSlotPool *eLightFlareSlotPool;

// gp-23664. The last InitRenderInfo's GetTextureInfo(9024, 1, 0); Render
// reads it.
extern void *TestRenderInfo;

// The two pools, each made only when it is not. Flags 16 as in retail.
void carrenderinfo_init_slot_pools(void);

// ----------------------------------------------------------- the seams

// Car::AssignAnimatedDriver(char const *), 0x00133488, and
// UnAssignAnimatedDriver, 0x001334f0: the driver's model, for a car not
// of CAR_USAGE_TYPE_TRAFFIC.
extern void (*gCarAssignAnimatedDriverFn)(Car *c, const char *model_name);
extern void (*gCarUnAssignAnimatedDriverFn)(Car *c);

// BodyDamage::SetALevelBodyDamageInfo(char const *), 0x001b4cd8 --
// pALevelBodyDamageInfo = FindBodyDamageInfo(bStringHash(name)) -- and
// BodyDamage::AddModel(eModel *, char const *, int), 0x001b4d10, which
// counts the model in and inits BodyDamageModels[n] with it
// (0x001b4820).
extern void (*gBodyDamageSetALevelInfoFn)(BodyDamage *bd, const char *name);
extern void (*gBodyDamageAddModelFn)(BodyDamage *bd, eModel *m,
                                     const char *name, int32_t flag);

// afxGetEmitters(bTList<AcidEmitter> *, unsigned int), 0x001272e0: every
// emitter of that effect onto the list's tail.
extern void (*gAfxGetEmittersFn)(bNode *list, uint32_t effect_hash);

// AcidEmitter's deleting destructor (0x00124e20), called with 3 on each
// emitter ~bTList<AcidEmitter> takes off.
extern void (*gAcidEmitterDeleteFn)(bNode *emitter, int32_t flags);

// ---------------------------------------------------------- the methods

// CarRenderInfo::CarRenderInfo(RideInfo *, Car *), 0x0011e860, in place
// on `ri`, which it returns. `car` may be NULL (the front end's). What it
// does, in order, is in docs/formats/car-render-info.md.
CarRenderInfo *carrenderinfo_construct(CarRenderInfo *ri, RideInfo *ride,
                                       Car *car);

// CarRenderInfo's deleting destructor, 0x0011fac0: waits for the renderer,
// unassigns the driver, frees the alpha info, empties the lists, and
// uninits every model. With bit 0 of `flags`, bFree(ri).
void carrenderinfo_delete(CarRenderInfo *ri, int32_t flags);

// CarRenderInfo::SwitchSkin(RideInfo *), 0x0011fe60: the ride's textures
// in game, and the five replacements that carry the skin.
void carrenderinfo_switch_skin(CarRenderInfo *ri, RideInfo *ride);

// CarRenderInfo::UpdateCarReplacementTextures, 0x0011ff68: the windows'
// and the lights' textures from the car's breakable-item damage, the
// broken-light mask, and the three bodies' tables reconnected.
void carrenderinfo_update_car_replacement_textures(CarRenderInfo *ri);

// CarRenderInfo::CreateCarLightFlares, 0x00120360: a flare for each of the
// car's markers with a light's name.
void carrenderinfo_create_car_light_flares(CarRenderInfo *ri);

// The part culler's InitPart, 0x0011d580 (the name is the port's): part
// `idx`'s planes in the shared table normalised where their length is
// more than 0.01 from 1, then `point` into the part.
void carrenderinfo_init_part(CarPartCullerPart *culler, int32_t idx,
                             const bVector4 *point);

// Car::InitRenderInfo(RideInfo *), 0x0011dc80: a render info for the car
// from bMalloc(2352, "CarRenderInfo", 0, 16), then its emitter positions,
// its emitters and TestRenderInfo. This is what gCarInitRenderInfoFn is
// set to.
void car_init_render_info(Car *c, RideInfo *ride);

#endif
