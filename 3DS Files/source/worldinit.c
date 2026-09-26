// worldinit -- World's constructor and destructor, the collision
// prediction's recorders and the two debug views: the rest of World.obj
// but DoSnapshot and DoPointerSnapshot, which wait on ReplaySnapshot. See
// world.h, and docs/formats/world.md for the decode.

#include "world.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmath.h"
#include "bmem.h"
#include "bplist.h"
#include "carcontroller.h"
#include "collision.h"
#include "collisionbody.h"
#include "realtime.h"
#include "drivetargetrenderer.h"
#include "topology.h"
#include "vtable.h"

int32_t WhichCollisionPredictionIterationToRender = -1;
int32_t WhichCarsRegisteredDriveTargetToRender = -1;
int32_t RenderChosenPotentialDriveTarget;
int32_t RenderMyCarDriveTarget;
int32_t RenderOtherCarDriveTarget;

void (*gInitCarEffectsFn)(void);
void (*gInitClansFn)(void);
void (*gInitSkidsFn)(void);
void (*gInitParticlesFn)(void);
void (*gInitMunitionsFn)(void);
void (*gInitFernFlattenersFn)(void);
void (*gInitFernShakersFn)(void);
void (*gSpawnSmokeablesFn)(void);
void (*gInitTerrainEffectEmittersFn)(void);
void (*gInitCopsFn)(void);
void (*gInitTrackGraphFn)(void);

void (*gCloseTerrainEffectEmittersFn)(void);
void (*gCleanupCopsFn)(void);
void (*gCleanupTrackGraphFn)(void);
void (*gClearSmokeablesFn)(void);
void (*gCloseFernShakersFn)(void);
void (*gCloseFernFlattenersFn)(void);
void (*gCloseMunitionsFn)(void);
void (*gCloseParticlesFn)(void);
void (*gCloseClansFn)(void);
void (*gCloseSkidsFn)(void);
void (*gCloseCarEffectsFn)(void);

struct TrafficTeleporter *(*gTrafficTeleporterCtorFn)(void *mem);
void (*gTrafficTeleporterDestroyFn)(struct TrafficTeleporter *t,
                                    int32_t flags);
void (*gCarDestroyFn)(struct Car *c, int32_t flags);

typedef void (*DebugDisplayFn)(void *self);

static void missing(const char *what)
{
    fprintf(stderr, "world: %s is not ported\n", what);
    abort();
}

static void call(void (*fn)(void))
{
    if (fn != NULL)
        fn();
}

static void empty(WorldList *l)
{
    l->next = l;
    l->prev = l;
}

// A bTList's walk in its destructor: the first node unlinked, then handed
// to `destroy`, until the list is empty. The node's own links are left as
// they were.
static void drain_list(WorldList *head, void (*destroy)(void *node))
{
    WorldList *n;

    while ((n = (WorldList *)head->next) != head) {
        WorldList *next = (WorldList *)n->next;
        WorldList *prev = (WorldList *)n->prev;

        prev->next = next;
        next->prev = prev;
        destroy(n);
    }
}

static void destroy_collision(void *node)
{
    collision_destroy((Collision *)node, 3);
}

static void destroy_car(void *node)
{
    if (gCarDestroyFn == NULL)
        missing("Car's destructor");
    gCarDestroyFn((struct Car *)node, 3);
}

// ~bPNode(3): bNode's destructor, which does nothing, then the pool.
static void destroy_pnode(void *node)
{
    bpnode_free(node);
}

World *world_init(World *w)
{
    struct TrafficTeleporter *t;
    void *mem;
    int k;

    empty(&w->CarList);
    empty(&w->AICarList);
    empty(&w->CollisionList);
    for (k = 0; k < WORLD_PREDICTION_OBBS; k++)
        obb_init(&w->CollisionPredictionMyOBBs[k]);
    for (k = 0; k < WORLD_PREDICTION_OBBS; k++)
        obb_init(&w->CollisionPredictionOtherCarOBBs[k]);
    drivetarget_init(&w->CollisionPredictionMyDriveTarget);
    drivetarget_init(&w->CollisionPredictionOtherCarDriveTarget);
    drivetarget_init(&w->PotentialDriveTarget);

    pCurrentWorld = w;
    ResetWorldTime();
    w->WorldRandomSeed = (uint32_t)bRandomI(0x7fffffff, &bDefaultSeed);
    w->TotalNumCars = 0;
    w->AICarPos = 0;
    w->CopCarPos = 0;
    w->TrafficCarPos = 0;
    w->PotentialDriveTargetID = 1;
    w->CollisionPredictionID = 1;
    world_reset_time_scale(w);
    w->PreviousTimeToWaste = 0.0f;
    memset(w->PlayerPositions, 0, sizeof w->PlayerPositions);
    memset(w->PlayerDATs, 0, sizeof w->PlayerDATs);
    w->Helicopter = NULL;

    if (gTrafficTeleporterCtorFn == NULL)
        missing("TrafficTeleporter's constructor");
    mem = bMalloc(TRAFFICTELEPORTER_SIZE, "TrafficTeleporter", 0, 16);
    t = gTrafficTeleporterCtorFn(mem);
    w->Teleporter = t;

    call(gInitCarEffectsFn);
    call(gInitClansFn);
    call(gInitSkidsFn);
    call(gInitParticlesFn);
    call(gInitMunitionsFn);
    call(gInitFernFlattenersFn);
    call(gInitFernShakersFn);
    call(gSpawnSmokeablesFn);
    call(gInitTerrainEffectEmittersFn);
    call(gInitCopsFn);
    call(gInitTrackGraphFn);
    return w;
}

void world_destroy(World *w, int32_t flags)
{
    int k;

    call(gCloseTerrainEffectEmittersFn);
    call(gCleanupCopsFn);
    call(gCleanupTrackGraphFn);
    cbwitness_eliminate_all();
    call(gClearSmokeablesFn);
    call(gCloseFernShakersFn);
    call(gCloseFernFlattenersFn);
    call(gCloseMunitionsFn);
    call(gCloseParticlesFn);
    call(gCloseClansFn);
    call(gCloseSkidsFn);
    call(gCloseCarEffectsFn);
    if (w->Teleporter != NULL) {
        if (gTrafficTeleporterDestroyFn == NULL)
            missing("TrafficTeleporter's destructor");
        gTrafficTeleporterDestroyFn(w->Teleporter, 3);
    }

    ResetWorldTime();
    pCurrentWorld = NULL;
    WorldLoopCounter = 100000;

    drivetarget_destroy(&w->PotentialDriveTarget);
    drivetarget_destroy(&w->CollisionPredictionOtherCarDriveTarget);
    drivetarget_destroy(&w->CollisionPredictionMyDriveTarget);
    for (k = WORLD_PREDICTION_OBBS - 1; k >= 0; k--)
        obb_destroy(&w->CollisionPredictionOtherCarOBBs[k]);
    for (k = WORLD_PREDICTION_OBBS - 1; k >= 0; k--)
        obb_destroy(&w->CollisionPredictionMyOBBs[k]);
    drain_list(&w->CollisionList, destroy_collision);
    drain_list(&w->AICarList, destroy_pnode);
    drain_list(&w->CarList, destroy_car);
    if (flags & 1)
        bFree(w);
}

void world_debug_display(World *w)
{
    int32_t i;

    for (i = 0; i < w->CopCarPos - w->AICarPos; i++) {
        struct Car *c = w->CarTable[w->AICarPos + i];
        CarController *ctrl = c->pCarController;
        const VtEntry *e;

        if (ctrl == NULL)
            continue;
        e = vt_slot(ctrl->_vtable, CARCONTROLLER_VT_DEBUG_DISPLAY);
        ((DebugDisplayFn)e->fn)(vt_this(ctrl, e));
    }
}

void world_collision_prediction_set_obbs(World *w, OBB *mine, OBB *other)
{
    int k;

    for (k = 0; k < WORLD_PREDICTION_OBBS; k++) {
        obb_assign(&w->CollisionPredictionMyOBBs[k], &mine[k]);
        obb_assign(&w->CollisionPredictionOtherCarOBBs[k], &other[k]);
    }
}

void world_collision_prediction_set_drive_targets(World *w,
                                                  const DriveTarget *mine,
                                                  const DriveTarget *other)
{
    drivetarget_assign(&w->CollisionPredictionMyDriveTarget, mine);
    drivetarget_assign(&w->CollisionPredictionOtherCarDriveTarget, other);
}

void world_record_potential_drive_target(World *w, const DriveTarget *t)
{
    drivetarget_assign(&w->PotentialDriveTarget, t);
}

void world_collision_prediction_record_iteration(World *w, int32_t i,
                                                 int8_t mine_index,
                                                 int8_t other_index,
                                                 const bVector2 *mine,
                                                 const bVector2 *other)
{
    w->CollisionPredictionMyIndicies[i] = mine_index;
    w->CollisionPredictionOtherCarIndicies[i] = other_index;
    w->CollisionPredictionMaxLoopCounter = i;
    w->CollisionPredictionMyPositions[i] = *mine;
    w->CollisionPredictionOtherCarPositions[i] = *other;
}

// The chosen iteration is read again where the listing reads it: after
// the boxes are hidden, and after the first position is put on the
// ground.
static void render_iteration(World *w)
{
    int32_t it;
    bVector3 mine, other;
    int8_t mi, oi;
    int k;

    for (k = 0; k < WORLD_PREDICTION_OBBS; k++) {
        obb_do_not_render(&w->CollisionPredictionMyOBBs[k]);
        obb_do_not_render(&w->CollisionPredictionOtherCarOBBs[k]);
    }
    it = WhichCollisionPredictionIterationToRender;
    if (w->CollisionPredictionMaxLoopCounter < it)
        return;
    mi = w->CollisionPredictionMyIndicies[it];
    oi = w->CollisionPredictionOtherCarIndicies[it];
    get_vector_on_track(&mine, &w->CollisionPredictionMyPositions[it]);
    it = WhichCollisionPredictionIterationToRender;
    get_vector_on_track(&other,
                        &w->CollisionPredictionOtherCarPositions[it]);
    obb_render(&w->CollisionPredictionMyOBBs[mi], &mine);
    obb_render(&w->CollisionPredictionOtherCarOBBs[oi], &other);
}

void world_update_ai_debug_rendering(World *w)
{
    DriveTarget *t;

    if (!TweakerPauseWorld)
        return;
    if (WhichCollisionPredictionIterationToRender >= 0)
        render_iteration(w);

    if (RenderChosenPotentialDriveTarget) {
        t = &w->PotentialDriveTarget;
    } else if (RenderMyCarDriveTarget) {
        t = &w->CollisionPredictionMyDriveTarget;
    } else if (RenderOtherCarDriveTarget) {
        t = &w->CollisionPredictionOtherCarDriveTarget;
    } else if (WhichCarsRegisteredDriveTargetToRender != -1) {
        struct Car *c = world_get_car_by_driver_number(
            WhichCarsRegisteredDriveTargetToRender);

        // The listing reads pCarDriver through the car with no test, so a
        // number no car has reads the word at 44 in low memory. The only
        // renderer the shipped game runs never looks at the target, so the
        // port passes NULL instead.
        t = c != NULL ? (DriveTarget *)(void *)c->pCarDriver : NULL;
    } else {
        return;
    }
    drivetargetrenderer_set_target_to_render(&TheDriveTargetRenderer, t);
}
