// barricade -- BarricadeManager, a pursuit's roadblock barrels.
//
// New in retail (the demo has no such class): 64 bytes that tPursuit's
// constructor makes with bMalloc(64, "CopMgr", 0, 16) and keeps at 1472.
// It holds the collision body ids of up to ten "CS_RoadBlock_Barrel"
// smokeables the roadblock put down, and a fade timer for each.
//
//   0x0024ef88  the constructor: ten -1 ids, ten -1.0 timers
//   0x0024efd8  the destructor: each barrel still there deleted
//   0x0024f0a8  spawns a barrel (12i)
//   0x0024f1e0  starts every barrel fading
//   0x0024f268  counts the fades down (tPursuit::Update, 12h-2)
//
// Nothing in the port spawns a barrel before 12i, so every id stays -1
// and the two calls into the smokeables below are seams that abort.

#ifndef BARRICADE_H
#define BARRICADE_H

#include <stddef.h>
#include <stdint.h>

struct CollisionBody;

#define BARRICADE_MAX_BARRELS  10

typedef struct BarricadeManager {
    int16_t  nBarrel[BARRICADE_MAX_BARRELS];    //  0  collision body ids, -1 none
    float    fFadeTimer[BARRICADE_MAX_BARRELS]; // 20  -1.0 while not fading
    uint32_t vptr;                              // 60  0x002bf448
} BarricadeManager;                             // 64

#define BARRICADEMANAGER_VTABLE   0x002bf448u
#define BARRICADEMANAGER_VT_DTOR  8

typedef char barricademanager_layout_check[
    (offsetof(BarricadeManager, fFadeTimer) == 20
     && offsetof(BarricadeManager, vptr) == 60
     && sizeof(BarricadeManager) == 64) ? 1 : -1];

// 0x0024ef88.
BarricadeManager *barricademanager_construct(BarricadeManager *b);

// 0x0024efd8: each id that is not -1 goes to the smokeables' delete
// (0x0021ef88) with the "CS_RoadBlock_Barrel" SmokeableInfo, found again
// for each one; then __builtin_delete on flags & 1.
void barricademanager_destruct(BarricadeManager *b, int32_t flags);

// 0x0024f1e0: each barrel there gets `t` on its fade timer, and the
// collision body of each one CollisionBody::FindCollisionBody finds is
// marked (its byte at 1123 set to 1).
void barricademanager_fade(BarricadeManager *b, float t);

// The smokeables' side, not ported before 12i; NULL aborts.
//   - 0x0021ef88(id, info): deletes the barrel's smokeable. FindSmokeable
//     Info(bStringHash("CS_RoadBlock_Barrel")) is found for it each time.
//   - the body's byte at 1123, past the port's CollisionBody.
extern void (*gBarricadeDeleteBarrelFn)(int16_t id);
extern void (*gBarricadeMarkBodyFadingFn)(struct CollisionBody *body);

// Registers the table at 0x002bf448.
void barricade_install_vtables(void);

#endif
