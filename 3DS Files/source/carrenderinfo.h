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
// Render (0x00120ef8) and the culler's pass (0x0011d980) are carrender.c's,
// at the end of this header. Retail's is 2352 bytes to the demo's 1856: it adds
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
#include "elight.h"
#include "emodel.h"
#include "eviewmatrix.h"
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

// eLightFlare (elight.h), from eLightFlareSlotPool: the render info makes
// one for each light a car's markers name.

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

// CarRenderInfo::UpdateTextureInfo(eReplacementTextureTable *), 0x0011fed0:
// the entry's texture looked up again by its NewNameHash, the default
// standing in for a missing one.
void carrenderinfo_update_texture_info(CarRenderInfo *ri,
                                       eReplacementTextureTable *t);

// CarRenderInfo::UpdateSkinTextures, 0x0011ff08: UpdateTextureInfo on the
// five entries SwitchSkin renames -- both skin entries, the first two
// damageable ones and the first tyre one.
void carrenderinfo_update_skin_textures(CarRenderInfo *ri);

// Car::SwitchSkin(unsigned int), 0x0011e588, in this object on the disc:
// the ride's SkinNumber set, then CarRenderInfo's SwitchSkin and
// UpdateSkinTextures. TrafficTeleporter repaints a traffic car with it.
void car_switch_skin(Car *c, uint32_t skin);

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

// ============================================================== Render
//
// carrender.c: CarRenderInfo::Render and what it calls of Car.obj's own.
//
//   CarRenderInfo::Render                         0x00120ef8  9840 bytes
//   CarRenderInfo::UpdateLightStateTextures       0x00120130   560
//   CarRenderInfo::CalculateTireBlur(int)         0x00120ea8    76
//   the part culler's pass                        0x0011d980   528
//   sh_Setup(bVector3 *)                          0x00120d60   324
//   convex_hull(bVector3 *, int &, Topo..., f, f) 0x001209f8   512
//   smooth_shadow_corners(int)                    0x00120c00   352
//   ch2d(float **, int)                           0x00120980   120
//   make_chain(float **, int, cmp)                0x00120850   300
//   cmpl / cmph                                   0x001207a8 / 0x00120828
//
// Render draws one car: its light flares, the driver, two shadows (a hull
// of the collision body cast along the sun, and a 4x4 grid under the box
// laid on the ground), the body at its level of detail, the mirrors, the
// plates, the scuffs, the four tyres and their blur, the brakes and the
// wipers. Retail's order and its frame memory are kept exactly: every
// matrix and light context it hands on comes from eframe_malloc, taken in
// the same order and the same sizes, and a failed one skips what it was
// for. What it is in docs/formats/car-render-info.md.
//
// What the renderer draws with goes through seams, each skipped when
// NULL: eModel::Render (scenerycull.h's gEModelRenderFn), the two strip
// builders, the light flares and the animated driver. The light context
// is eviewmatrix.h's gElSetupLightContextFn.

// CarRenderMatrix, 0x002e0270: a tweakable the body's matrix is
// multiplied by. InitCarEffects (0x0011db90) sets it to eIdentity; the
// port starts it there.
extern bMatrix4 CarRenderMatrix;

// Retail's switches, all tweakables nothing in the game changes.
extern int32_t EnableEnvMap;                // gp-25040, 1
extern int32_t PrintQueryLightMat;          // gp-23712, 0
extern int32_t QueryLightMat;               // gp-24224: 1 around the light
                                            // context when the above is set;
                                            // nothing reads it
extern int32_t CarPartCullerNormalise;      // gp-23768, 0: normalise each
                                            // plane before the test
extern int32_t ForceHeadlights;             // gp-23760, 0
extern int32_t ForceBrakelights;            // gp-23756, 0
extern int32_t ForceReverselights;          // gp-23752, 0
extern int32_t ForceCoplights;              // gp-23748, 0
extern int32_t ForceRenderDriver;           // gp-23744, 0: no pixel test
extern int32_t ForceCarLOD;                 // gp-23696, -1
extern int32_t ForceTireLOD;                // gp-23692, -1

// FancyCarShadowEdgeMult (gp-23764, 1.1): how far the hull shadow's soft
// edge reaches past the hull, which Render sets from the sun each time.
// CarShadowElevationFE (gp-23740, 0.01): the grid's height in the front
// end.
extern float FancyCarShadowEdgeMult;
extern float CarShadowElevationFE;

// The cop lights' patterns, one byte a frame: the headlights' wig-wag by
// frame & 15 (0x002e01e8); red, blue and white by frame & 7 while the
// car's CopLights is 2 (gp-23736, -23728, -23720); and otherwise by
// (frame >> 1) & 15 (0x002e01b8, 0x002e01c8, 0x002e01d8, retail's).
extern uint8_t CopLightsHeadlights[16];
extern uint8_t CopLightsRed[8];
extern uint8_t CopLightsBlue[8];
extern uint8_t CopLightsWhite[8];
extern uint8_t CopLightsRedSlow[16];
extern uint8_t CopLightsBlueSlow[16];
extern uint8_t CopLightsWhiteSlow[16];

// 0x002ad0e8: the pixel sizes below which each level of detail gives way
// to the next.
extern const float CarLodPixelSizes[4];

// The hull shadow's statics: the light's direction and one over its z
// (sh_Setup's, gp-13420), the ground's normal and the point under the car
// (Render's), and the three point arrays -- the collision body's points
// cast onto the ground, their hull, and the hull with its corners cut --
// with the hull's pointers. Retail does not bound the arrays; the port
// casts at most HULL_MAX_POINTS points.
#define HULL_MAX_POINTS 64
extern float     cs_OneOverZ;
extern bVector3  cs_lightV;                        // 0x00332920
extern bVector3  hull_Normal;                      // 0x00332930
extern bVector3  hull_Origin;                      // 0x00332940
extern bVector3  hullVertArray3[3 * HULL_MAX_POINTS];  // 0x00332950
extern bVector3  hullVertArray2[HULL_MAX_POINTS];  // 0x00333550
extern bVector3  hullVertArray1[HULL_MAX_POINTS];  // 0x00333950
extern bVector3 *hullVertPointers[HULL_MAX_POINTS + 1];  // 0x00333d50

// ---------------------------------------------------------- the seams

// The strip builders, eBeginStrip (0x00110488), eAddVertex (0x001107d0),
// eAddColour (0x001107e0), eAddUV (0x001107f8) and eEndStrip
// (0x00110608), and the ex set (0x00110848, 0x001109f8, 0x00110a40,
// 0x00110a68, 0x00110878). Begin's nonzero is a strip begun; a NULL Begin
// is none.
typedef struct eStripFns {
    int32_t (*Begin)(void *texture, int32_t num_vertices, bMatrix4 *m);
    void    (*AddVertex)(const bVector3 *v);
    void    (*AddColour)(uint32_t colour);
    void    (*AddUV)(float u, float v);
    void    (*End)(void);
} eStripFns;
extern eStripFns gEStripFns;
extern eStripFns gExStripFns;

// eRenderLightFlare(eView *, eLightFlare *, bMatrix4 *, float),
// 0x001164f0.
extern void (*gERenderLightFlareFn)(eView *view, eLightFlare *flare,
                                    bMatrix4 *local_world, float intensity);

// AnimatedDriver::Render(bMatrix4 *, eLightContext *, unsigned int, int),
// 0x001a9a30, and GetLengthOfQueuedAnimations, 0x001a9fb8. NULL draws
// nothing and has nothing queued.
extern void (*gAnimatedDriverRenderFn)(AnimatedDriver *d, bMatrix4 *m,
                                       eLightContext *lc, uint32_t flags,
                                       int32_t lod);
extern int32_t (*gAnimatedDriverQueuedFn)(AnimatedDriver *d);

// ---------------------------------------------------------- the methods

// CarRenderInfo::Render(eView *, bVector3 const *, bMatrix4 const *,
// bMatrix4 *, bMatrix4 *, unsigned int, unsigned int), 0x00120ef8. The
// car at `position` with `body_matrix`'s rotation; four tyre and four
// brake matrices in the car's space; flags for every model; and the
// forced lights, 1 2 4 8 for head, brake, reverse and cop.
void carrenderinfo_render(CarRenderInfo *ri, eView *view,
                          const bVector3 *position,
                          const bMatrix4 *body_matrix,
                          bMatrix4 *tire_matrices, bMatrix4 *brake_matrices,
                          uint32_t extra_render_flags,
                          uint32_t forced_lights);

// 0x00120130: the four lamps' textures -- head and brake, lit or not --
// swapped in where they are not broken, and the bodies' tables
// reconnected when one changed.
void carrenderinfo_update_light_state_textures(CarRenderInfo *ri);

// 0x00120ea8: |wheel's angular velocity| * 0.02 held to [0, 1], 0 with no
// car.
float carrenderinfo_calculate_tire_blur(const CarRenderInfo *ri,
                                        int32_t wheel);

// The part culler's pass, 0x0011d980: for each of the fourteen parts,
// State[2] is whether `eye` (car space) is on the seen side of its planes
// -- any of them for a Flag8 of 0, all for 1, always otherwise -- and
// State[1] or State[0] counts it.
void carrenderinfo_cull_parts(CarPartCullerPart *culler,
                              const bVector3 *eye);

// sh_Setup, 0x00120d60: cs_lightV from the sun's shadow position (or
// (-16384, 0, 7000) with no sun) to `pos`, lowered to 4600 BAMs off
// straight down when it is steeper, and cs_OneOverZ.
void car_shadow_setup(const bVector3 *pos);

// convex_hull, 0x001209f8: the hull of *count points into hullVertArray2,
// each at z and dropped onto the ground plus `lift`; a point the ground
// is not found under, or that is more than 4 off z or 1.5 off the plane
// through hull_Origin, is dropped. *count is what is left.
void car_shadow_convex_hull(bVector3 *pts, int32_t *count,
                            TopologyCoordinate *tc, float z, float lift);

// smooth_shadow_corners, 0x00120c00: each of hullVertArray2's n corners
// into three in hullVertArray3, a third of the way along each edge and
// one between. Returns 3n.
int32_t car_shadow_smooth_corners(int32_t n);

// ch2d, 0x00120980: Andrew's monotone chain on P[0..n-1], the hull's
// pointers first in P; P needs room for n + 1. Returns the hull's count.
int32_t car_shadow_ch2d(bVector3 **P, int32_t n);

// ========================================================== RenderCars
//
// rendercars.c: RenderCars and the two Car helpers only it calls, both
// new in retail.
//
//   RenderCars(eView *)                           0x00124060   580 bytes
//   whether the car blinks in a view              0x00133190   120
//   the tyres' and the brakes' matrices           0x00135fb8   296
//
// eDisplayFrame calls RenderCars for each view before the front end's
// cars. Retail's differs from the demo's (0x00123468) three ways: the
// in-car dashboard is gone, the two helpers take the override into
// account, and a view whose player is in the jump cam draws no damage
// above the cars.

// Car::DamageAbove(bVector3 *, bVector3 *), 0x00135280, with the camera's
// eye and direction: cardamageabove.c (TASKS 51d), and NULL skips it.
extern void (*gCarDamageAboveFn)(Car *c, bVector3 *eye, bVector3 *direction);

// 0x00133190: 0 in a view with the override, else Car::IsBlinking or the
// override's blinking bit for the view.
int32_t car_is_blinking_in_view(Car *c, int32_t view_id);

// 0x00135fb8: the four tyre and four brake matrices for a view. With the
// override they are identities placed at the car type's wheels, and
// otherwise the car's own WheelMatrix and BrakeMatrix.
void car_get_render_wheel_matrices(Car *c, bMatrix4 *tires,
                                   bMatrix4 *brakes, int32_t view_id);

// RenderCars(eView *), 0x00124060: every car in pCurrentWorld's CarList
// but the camera's CarNotToRender, up to 99, that is enabled, not poofed
// and visible in the view, and not in a blink's off frame. Each is drawn
// at its override where the view has one, then gets its damage above.
void render_cars(eView *view);

// The port's, not retail's. eDisplayFrame runs RenderCars for views 0 to
// 3 in turn (0x00113668 to 0x001136f0), so the mirror's (3) comes after
// the player's (1), and the fAngleToCamera DamageAbove leaves, which the
// cop HUD's trackers read, is the mirror's. The port draws the mirror
// first. keep_angles makes the next render_cars note each angle it leaves,
// and restore_angles, after the player's view, puts them back, as
// retail's order leaves them. Kept angles live within one frame
// (eFrameCounter).
void render_cars_keep_angles(void);
void render_cars_restore_angles(void);

#endif
