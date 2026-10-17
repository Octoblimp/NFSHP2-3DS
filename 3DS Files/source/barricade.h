// barricade -- BarricadeManager, a pursuit's roadblock barrels, and the
// plan a roadblock is laid out by.
//
// New in retail (the demo has no such class): 64 bytes that tPursuit's
// constructor makes with bMalloc(64, "CopMgr", 0, 16) and keeps at 1472.
// It holds the collision body ids of up to ten "CS_RoadBlock_Barrel"
// smokeables the roadblock put down, and a fade timer for each.
//
//   0x0024ef88  the constructor: ten -1 ids, ten -1.0 timers
//   0x0024efd8  the destructor: each barrel still there deleted
//   0x0024f0a8  spawns a barrel (12i-2)
//   0x0024f1e0  starts every barrel fading
//   0x0024f268  counts the fades down (tPursuit::Update)
//
// The plan's code follows it in the image, 0x0024fae8 to 0x00250150, also
// new in retail: a ring of words that the manager's layout (pursuit.c)
// fills and then reads back, one item across the road at a time.
//
// The port loads no smokeables yet (the smokeables are their own step), so
// FindSmokeableInfo is a NULL seam that finds nothing: no barrel is ever
// spawned, every id stays -1, and the calls into the smokeables below are
// seams that abort if reached.

#ifndef BARRICADE_H
#define BARRICADE_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

struct CollisionBody;
struct SmokeableInfo;
struct tRoadBlock;

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

// 0x0024f0a8, from the layout for each barrel: the first free slot whose
// FindSmokeableInfo("CS_RoadBlock_Barrel") is found takes a smokeable
// spawned at `pos` and returns its id; -1 when none. Each spawn first
// scales the shared info's mass to 10 and the first three rows of its
// inertia tensor by the same factor. A slot whose find fails is passed
// over and the next free one tried.
int32_t barricademanager_spawn_barrel(BarricadeManager *b,
                                      const bVector3 *pos);

// 0x0024f1e0: each barrel there gets `t` on its fade timer, and the
// collision body of each one CollisionBody::FindCollisionBody finds is
// marked (its byte at 1123 set to 1).
void barricademanager_fade(BarricadeManager *b, float t);

// 0x0024f268, from tPursuit::Update with the frame's seconds: each barrel
// there that is fading counts `dt` down, and one that goes below 0 is
// deleted (as the destructor does) and its slot and timer set back to -1.
void barricademanager_count_down(BarricadeManager *b, float dt);

// 0x0024f358, the replay's (TASKS 72e-2, copsnap.c): in a section of its
// own, each barrel's fade timer and then its id, a short.
struct ReplaySnapshot;
void barricademanager_do_snapshot(BarricadeManager *b,
                                  struct ReplaySnapshot *s);

// The smokeables' side, not ported yet.
//   - 0x0021ef88(id, info): deletes the barrel's smokeable. FindSmokeable
//     Info(bStringHash("CS_RoadBlock_Barrel")) is found for it each time.
//     NULL aborts.
//   - the body's byte at 1123, past the port's CollisionBody. NULL aborts.
//   - FindSmokeableInfo (0x0021f8f8): the loaded info by its name's hash.
//     NULL finds none.
//   - 0x0021ed28(type, info, hash, pos, ang): a smokeable of the info's
//     made on the ground at `pos`, its id or -1. The spawn gives type 0,
//     bStringHash("ROADBLOCK_BARREL") and 0. NULL aborts.
extern void (*gBarricadeDeleteBarrelFn)(int16_t id);
extern void (*gBarricadeMarkBodyFadingFn)(struct CollisionBody *body);
extern struct SmokeableInfo *(*gFindSmokeableInfoFn)(uint32_t hash);
extern int32_t (*gSmokeableSpawnFn)(int32_t type, struct SmokeableInfo *info,
                                    uint32_t hash, const bVector3 *pos,
                                    uint16_t ang);

// Registers the table at 0x002bf448.
void barricade_install_vtables(void);

// ------------------------------------------------------------- the plan

// The plan's items, as the layouts give them. Each one's word follows it
// on the ring: a lane its width (a float's bits), a spike strip its
// segments, a cop car its angle; a gap and a barrel have none.
#define RBPLAN_LANE_LEFT   0    // the escape lane by the road's left edge
#define RBPLAN_LANE_RIGHT  1    // the one by its right edge
#define RBPLAN_SPIKES      2    // a spike strip, 0.65 a segment
#define RBPLAN_COP         3    // a cop car
#define RBPLAN_GAP         4    // 0.8 of road
#define RBPLAN_BARRELS     5    // as many barrels, 3.0 each, as fit
#define RBPLAN_END         6

#define RBPLAN_SIZE  30

// 132 bytes on the layout's stack: a ring of 30 words, one always left
// empty, so 29 fit.
typedef struct RoadBlockPlan {
    int32_t  Head;                  //   0  the next to pop
    int32_t  Tail;                  //   4  the next to push
    uint32_t Data[RBPLAN_SIZE];     //   8
    uint32_t vptr;                  // 128  0x002bf550
} RoadBlockPlan;

#define ROADBLOCKPLAN_VTABLE  0x002bf550u

typedef char roadblockplan_layout_check[
    (offsetof(RoadBlockPlan, Data) == 8 && offsetof(RoadBlockPlan, vptr) == 128
     && sizeof(RoadBlockPlan) == 132) ? 1 : -1];

// 0x00250068 and 0x00250088: empty, and the table put back (nothing to
// free on the stack, so the layout passes 2).
RoadBlockPlan *roadblockplan_construct(RoadBlockPlan *q);
void roadblockplan_destruct(RoadBlockPlan *q, int32_t flags);

// 0x002500b0 and 0x00250100: 0 when full, or empty. Retail's push takes
// the word by pointer.
int32_t roadblockplan_push(RoadBlockPlan *q, uint32_t v);
int32_t roadblockplan_pop(RoadBlockPlan *q, uint32_t *out);

// 0x0024fae8: the road a cop car at `ang` (a BAM across the road) takes,
// |cos| times the manager's widest cop car's Ydim plus |sin| times its
// Xdim.
float roadblock_cop_car_width(uint16_t ang);

// 0x0024fb50: the cop cars' angle, 8192 (45 degrees), into `ang`, and the
// width at it.
float roadblock_cop_car_angle(uint16_t *ang);

// gp-13244: the angle the plan starts its cop cars at, 8192, which a
// static constructor (0x00250150) sets and nothing else writes.
extern uint16_t RoadBlockCopAngle;

// 0x0024fb78. The layout's items sized to the road (rb's fRoadWidth):
// each escape lane `escW`, each cop car its width at RoadBlockCopAngle, a
// gap 0.8, a spike strip 8 segments. Past the road, the last cop car of
// two or more is dropped. Then the cop cars' width at 45 degrees; as many
// barrels as fit, up to 10; the spike strips stretched to the road left
// (3 to 20 segments each) and the rest shared between the lanes, which,
// with two, are moved by the difference of the route point's two widths.
// Pushed: each item with its word, the barrels' item once for each.
void roadblock_build_plan(RoadBlockPlan *q, const int32_t *layout, float escW,
                          const struct tRoadBlock *rb);

#endif
