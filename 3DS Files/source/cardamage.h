// cardamage -- CarDamage and BodyDamage (retail 0x001b4760 .. 0x001b5c50):
// how hard each side of a car has been hit, and what breaks.
//
// BodyDamage keeps the car's damage as 32 zones round its outline, a byte
// each out of 128. The zones are laid round the box of the car's
// BodyDamageInfo (chunk 0x34030, one per body and scuff model in the
// car's GEOMETRY.BIN), eight to a side. A hit damages the zone it lands
// in and, halved each step, the four on either side.
//
// CarDamage is the car's. Retail changed it from the demo's: the demo's
// breakable items were found by marker on every hit, and retail's are
// found once (FindItemParts) and kept as zones. Each of the fifteen items
// has a level, 0 to 3, two bits of BreakableCarItemDamageAmounts, from its
// zone's damage against its thresholds. A level that rises plays the
// glass and triggers the item's effect; a hit too light to break anything
// leaves the zone as it was. ApplyDamage takes the levels to the render
// info's replacement textures (the broken lights and windows) and to the
// windows' environment mapping.
//
//   LoaderBodyDamage / Unloader            0x001b4760 / 0x001b47b0
//   FindBodyDamageInfo                     0x001b47e8
//   BodyDamageModel::Init                  0x001b4820
//   DamageVertexFunction, and its wrapper  0x001b48d0, 0x001b48b0
//   BodyDamageModel::CallDamageVertexFunction  0x001b4b50
//   BodyDamage::BodyDamage / ~BodyDamage   0x001b4ba0 / 0x001b4c10
//   SetALevelBodyDamageInfo, AddModel      0x001b4cd8, 0x001b4d10
//   SetDamage, RepairAllDamage             0x001b4d48, 0x001b4dc0
//   the zone of a point (new in retail)    0x001b4e10
//   GetDamageAmount(bVector2 *)            0x001b4f10
//   the GetVisible* and GetCompressed*     0x001b5030 .. 0x001b50c8
//   BodyDamage::ApplyDamage                0x001b5108
//   BodyDamage::SetEnvironmentMapping      0x001b5250
//   CarDamage::CarDamage / ~CarDamage      0x001b54b0 / 0x001b5538
//   the item parts (new)                   0x001b5598
//   CarDamage::AddDamage (new)             0x001b56b0
//   the item levels (new)                  0x001b57a0
//   the damage to one zone (new)           0x001b58c8
//   RethinkDamage, ApplyDamage             0x001b5a78, 0x001b5aa8
//   the wreck (new), RepairAll (new)       0x001b5bc8, 0x001b5c20
//
// The vertices: ApplyDamage walks each model's (estripdata.h), and
// DamageVertexFunction dents and darkens the body's by each zone's damage
// since the last walk and shows the scuffs where there is any. The walk
// changes the solid's packet and strip flags; the port's renderer bakes
// meshes from them and takes the change after the walk (trackview.c).
//
// Not here: the replay's DoSnapshot (no ReplayManager yet).
//
// Cross-check: tools/cardamage_check.py. Write-up:
// docs/formats/car-damage.md.

#ifndef CARDAMAGE_H
#define CARDAMAGE_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bvector.h"
#include "car.h"                // Car, and the CarDamage forward name
#include "emodel.h"

#define BODYDAMAGE_ZONES   32
#define BODYDAMAGE_MODELS  4
#define CARDAMAGE_ITEMS    15

// BodyDamageInfo, 84 bytes (.mdebug), in place in the 0x34030 chunk's
// payload. The loader points pKeys at the words after it: a key a vertex
// on the disc, bits 0-2 the run's length less one, 3-7 the zone, 8-13 the
// colour step and 14-31 the dent, z y x, signed six bits each.
typedef struct BodyDamageInfo {
    bNode     Node;                         //  0  on BodyDamageInfoList
    char      Name[32];                     //  8
    uint32_t  NameHash;                     // 40
    bVector2  BBoxMin;                      // 44
    bVector2  BBoxMax;                      // 52
    bVector2  Center;                       // 60
    int32_t   NumVertices;                  // 68
    int32_t   NumKeys;                      // 72
    uint32_t *pKeys;                        // 76
    int32_t  *pVertexIndices;               // 80
} BodyDamageInfo;                           // 84

struct BodyDamage;

// BodyDamageModel, 28 bytes (.mdebug): a model whose vertices follow the
// damage, and where the walk over them is.
typedef struct BodyDamageModel {
    struct BodyDamage *pBodyDamage;         //  0
    eModel         *pModel;                 //  4
    BodyDamageInfo *pBodyDamageInfo;        //  8  NULL: not dented
    int32_t         NumVertices;            // 12
    int32_t         DamagePolysOnly;        // 16
    int32_t         RepeatCount;            // 20
    int32_t         KeyNum;                 // 24
} BodyDamageModel;                          // 28

// BodyDamage, 196 bytes (.mdebug type#2378). The amounts are bytes, 128
// whole; the totals their sums, so 4096 is every zone whole. "Applied" is
// what the vertices were last moved to.
typedef struct BodyDamage {
    bNode     Node;                                         //   0
    uint8_t   CompressedDamageAmounts[BODYDAMAGE_ZONES];     //   8
    uint16_t  CompressedTotalDamage;                         //  40
    uint8_t   CompressedAppliedDamageAmounts[BODYDAMAGE_ZONES]; // 42
    uint16_t  CompressedTotalAppliedDamage;                  //  74
    int32_t   NumBodyDamageModels;                           //  76
    BodyDamageModel BodyDamageModels[BODYDAMAGE_MODELS];     //  80
    BodyDamageInfo *pALevelBodyDamageInfo;                   // 192
} BodyDamage;                                                // 196

// CarDamage. The demo's was 212 bytes (type#2955); retail's constructor
// and its new code add ItemZones, the zone of each breakable item or -1,
// and its bMalloc asks for 228 (carinit.h's CARDAMAGE_SIZE).
struct CarDamage {
    Car       *pCar;                                      //   0
    uint32_t   CarBaseNameHash;                           //   4
    BodyDamage TheBodyDamage;                             //   8
    uint32_t   BreakableCarItemDamageAmounts;             // 204
    uint32_t   AppliedBreakableCarItemDamageAmounts;      // 208
    int8_t     ItemZones[CARDAMAGE_ITEMS];                // 212
};                                                        // 228

// The pointers move offsets on a 64-bit host; the check is for the
// handheld, where the layout is the image's.
#if UINTPTR_MAX == 0xffffffffu
typedef char cardamage_layout_check[
    (sizeof(BodyDamageInfo) == 84
     && offsetof(BodyDamageInfo, NameHash) == 40
     && offsetof(BodyDamageInfo, BBoxMin) == 44
     && offsetof(BodyDamageInfo, NumVertices) == 68
     && offsetof(BodyDamageInfo, pKeys) == 76
     && sizeof(BodyDamageModel) == 28
     && offsetof(BodyDamage, CompressedDamageAmounts) == 8
     && offsetof(BodyDamage, CompressedTotalDamage) == 40
     && offsetof(BodyDamage, CompressedAppliedDamageAmounts) == 42
     && offsetof(BodyDamage, CompressedTotalAppliedDamage) == 74
     && offsetof(BodyDamage, NumBodyDamageModels) == 76
     && offsetof(BodyDamage, BodyDamageModels) == 80
     && offsetof(BodyDamage, pALevelBodyDamageInfo) == 192
     && sizeof(BodyDamage) == 196
     && offsetof(CarDamage, TheBodyDamage) == 8
     && offsetof(CarDamage, BreakableCarItemDamageAmounts) == 204
     && offsetof(CarDamage, ItemZones) == 212
     && sizeof(CarDamage) == 228) ? 1 : -1];
#endif

// One of the fifteen breakable items, 32 bytes at 0x00313b80: its index,
// the hash of its marker, the damage at which it reaches each level (the
// first unused), whether its texture loses its environment mapping when
// it breaks, and the CarEffect it triggers.
typedef struct BreakableCarItemInfo {
    int32_t   Index;                        //  0
    uint32_t  PositionHash;                 //  4
    float     Threshold[4];                 //  8
    int32_t   EnvMapped;                    // 24
    int32_t   Effect;                       // 28
} BreakableCarItemInfo;                     // 32

extern const BreakableCarItemInfo BreakableCarItemInfos[CARDAMAGE_ITEMS];

// BodyDamageInfoList (gp-18832) and BodyDamageList (gp-18824), each empty
// at boot as retail's static constructor leaves them.
extern bNode BodyDamageInfoList;
extern bNode BodyDamageList;

// ---------------------------------------------------------- the infos

// Loader slot 17. The chunk's info is put on BodyDamageInfoList's tail,
// its keys pointed at and its vertex indices cleared; the unloader takes
// it off. 1 for a 0x34030 chunk, 0 for anything else.
#define BODY_DAMAGE_ID 0x00034030u

int loader_body_damage(uint8_t *chunk);
int unloader_body_damage(uint8_t *chunk);

// The first info on the list with that name hash, or NULL.
BodyDamageInfo *find_body_damage_info(uint32_t name_hash);

// ------------------------------------------------------- the body damage

void  bodydamage_construct(BodyDamage *b, const char *name);
void  bodydamage_destruct(BodyDamage *b);

// pALevelBodyDamageInfo = FindBodyDamageInfo(bStringHash(name)).
void  bodydamage_set_alevel_info(BodyDamage *b, const char *name);

// The next of BodyDamageModels (no bound, as retail has none): this body
// damage, the model, `polys_only`, and its solid's vertex count. With
// vertices, the info named `name` if its count is the same, and then the
// walk once, which hides the scuffs. With `polys_only` the walk leaves the
// positions and colours alone and does only the scuffs' alpha and flags.
void  bodydamage_add_model(BodyDamage *b, eModel *m, const char *name,
                           int32_t polys_only);

// Port's, for the renderer: whether a model of a body damage on
// BodyDamageList walks `s`, having an info.
int32_t bodydamage_walks_solid(const eSolid *s);

// The zone's byte to `amount` clamped to 0..1, times 128 and truncated,
// and the total by the difference.
void  bodydamage_set_damage(BodyDamage *b, int32_t zone, float amount);

// Every zone to 0, the total to 0, then ApplyDamage.
void  bodydamage_repair_all(BodyDamage *b);

// The zone a point of the car's frame falls in, by its x and y over the
// A level info's box, eight to a side; -1 without an info.
int32_t bodydamage_get_zone(const BodyDamage *b, const float *at);

// That zone's damage, 0 without an info.
float bodydamage_get_damage_amount(const BodyDamage *b, const float *at);

// The same with damage on for the race (TheRaceParameters.DamageEnabled),
// and 0 without.
float bodydamage_get_visible_damage_amount_at(const BodyDamage *b,
                                              const float *at);
float bodydamage_get_visible_damage_amount(const BodyDamage *b,
                                           int32_t zone);
uint8_t bodydamage_get_compressed_visible_damage_amount(const BodyDamage *b,
                                                        int32_t zone);

// 0x001b50c8. With damage on for the race, the compressed total as a
// fraction of 4096 -- `lui at,0x3980`, 2^-12 -- and otherwise 0.
float bodydamage_get_visible_total_damage(const BodyDamage *b);

// The models walked and the applied amounts made the visible ones, when
// the visible total has moved more than 0.02 from the applied one, or has
// gone back to 0.
void  bodydamage_apply_damage(BodyDamage *b);

// eModel::SetEnvironmentMapping on every model's.
void  bodydamage_set_environment_mapping(BodyDamage *b, uint32_t hash,
                                         int32_t on);

// -------------------------------------------------------- the car damage

CarDamage *cardamage_construct(void *mem, Car *c);

// The levels to 0 and applied, the body damage destroyed, and with
// flags & 1 the memory freed.
void  cardamage_destroy(CarDamage *d, int32_t flags);

// Each item's zone from its marker in the car's model, or -1.
void  cardamage_find_item_parts(CarDamage *d);

// A hit at `at`, in the car's frame, of `amount`: nothing with damage off
// or below 0.05, or off the info's zones. Otherwise the amount to the
// zone, half to the zones either side, a quarter to the next, down to a
// sixteenth four away; then ApplyDamage.
void  cardamage_add_damage(CarDamage *d, const bVector3 *at, float amount);

// Each item's level from its zone's visible damage, two bits at 2i, with
// the windows (8 to 12) whole on the three cars that have none.
uint32_t cardamage_compute_item_states(const CarDamage *d);

// `amount` more damage to a zone, by a hit of `impact`. A change that
// would move an item's level is undone when the impact is below 0.2;
// otherwise each item whose level changed plays the glass if it is now 1
// and triggers its effect, scaled by the new level, and the levels are
// kept.
void  cardamage_add_zone(CarDamage *d, int32_t zone, float amount,
                         float impact);

void  cardamage_rethink_damage(CarDamage *d);
void  cardamage_apply_damage(CarDamage *d);

// Every zone whole by an impact of 9999, so everything breaks.
void  cardamage_wreck(CarDamage *d);
void  cardamage_repair_all(CarDamage *d);

#endif
