// cardamage -- the layouts of CarDamage and BodyDamage, and the one method
// of either that the physics reads.
//
// Both classes belong to the damage system (the model swaps, the
// breakable items, the replay snapshot), which is not ported. What is
// here is what the .mdebug type info and BodyDamage's constructor
// (0x001aae38) say about the layout, and GetVisibleTotalDamage
// (0x001ab490), which PhysicsCar::Move calls to derate the speed
// limiter. Nothing else in the port constructs or writes either yet.

#ifndef CARDAMAGE_H
#define CARDAMAGE_H

#include <stddef.h>
#include <stdint.h>

#include "car.h"                // Car, and the CarDamage forward name

// 28 bytes, type#2376. Its members are the damage models' render side and
// are left as bytes until that side is ported.
typedef struct BodyDamageModel {
    uint8_t _bytes[28];
} BodyDamageModel;

#define BODYDAMAGE_AMOUNTS 16
#define BODYDAMAGE_MODELS  4

// 196 bytes, type#2378. The type info starts at 8; the constructor shows
// what 0..7 are, a bNode it links into the list at gp-19496. The links
// are the list's, so they are 32-bit slots here as in RigidBody.
typedef struct BodyDamage {
    uint32_t pNext;                                       //   0  bNode
    uint32_t pPrev;                                       //   4
    uint16_t CompressedDamageAmounts[BODYDAMAGE_AMOUNTS];  //   8
    uint16_t CompressedTotalDamage;                       //  40
    uint16_t CompressedAppliedDamageAmounts[BODYDAMAGE_AMOUNTS]; // 42
    uint16_t CompressedTotalAppliedDamage;                //  74
    int32_t  NumBodyDamageModels;                         //  76
    BodyDamageModel BodyDamageModels[BODYDAMAGE_MODELS];  //  80
    const void *pALevelBodyDamageInfo;                    // 192
} BodyDamage;                                             // 196

// 212 bytes, type#2955.
struct CarDamage {
    Car       *pCar;                                      //   0
    uint32_t   CarBaseNameHash;                           //   4
    BodyDamage TheBodyDamage;                             //   8
    uint32_t   BreakableCarItemDamageAmounts;             // 204
    uint32_t   AppliedBreakableCarItemDamageAmounts;      // 208
};                                                        // 212

// The two pointers are at the front of CarDamage and at the end of
// BodyDamage, so a 64-bit host moves some offsets and not others. The
// check is for the handheld, where the layout is the image's.
#if UINTPTR_MAX == 0xffffffffu
typedef char cardamage_layout_check[
    (offsetof(BodyDamage, CompressedDamageAmounts) == 8
     && offsetof(BodyDamage, CompressedTotalDamage) == 40
     && offsetof(BodyDamage, CompressedAppliedDamageAmounts) == 42
     && offsetof(BodyDamage, CompressedTotalAppliedDamage) == 74
     && offsetof(BodyDamage, NumBodyDamageModels) == 76
     && offsetof(BodyDamage, BodyDamageModels) == 80
     && offsetof(BodyDamage, pALevelBodyDamageInfo) == 192
     && sizeof(BodyDamage) == 196
     && offsetof(CarDamage, TheBodyDamage) == 8
     && offsetof(CarDamage, BreakableCarItemDamageAmounts) == 204
     && sizeof(CarDamage) == 212) ? 1 : -1];
#endif

// 0x001ab490. With damage on for the race, the compressed total as a
// fraction of 4096 -- `lui at,0x3980`, 2^-12 -- and otherwise 0.
float bodydamage_get_visible_total_damage(const BodyDamage *b);

#endif
