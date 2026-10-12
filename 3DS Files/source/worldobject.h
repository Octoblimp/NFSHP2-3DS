// worldobject -- WorldObject, a model placed in the world by a matrix
// (`WorldObject:Tt361=s96`), retail's 0x001cd760 .. 0x001cdd40: the
// constructor and destructor, InitWorldObjects / CloseWorldObjects, which
// make and empty WorldObjectList's pool, and Render / RenderWorldObjects,
// which draw each enabled one. eDisplayFrame draws them in each player
// view and the rear-view mirror, after StuffSun and before the effects;
// trackview.c makes that call.
//
// The callers so far: the spike strips (spikestrip.h), whose twenty belt
// pieces are WorldObjects built in place inside the strip; and OBB's debug
// cube, which makes one through gWorldObjectNewFn, destroys one through
// gWorldObjectDeleteFn, and writes the Matrix and the Enabled flag itself.

#ifndef WORLDOBJECT_H
#define WORLDOBJECT_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bslotpool.h"

typedef struct WorldObject {
    bNode     Node;             //  0  bTNode<WorldObject>, on WorldObjectList
    void     *pModel;           //  8  eModel*, from eModelSlotPool
    int32_t   Enabled;          // 12  drawn while nonzero
    int32_t   AddLighting;      // 16
    uint8_t   _pad20[12];       // 20  the quadword round-up
    bMatrix4  Matrix;           // 32
} WorldObject;                  // 96

#define WORLDOBJECT_SLACK ((size_t)(sizeof(void *) - 4))

typedef char worldobject_layout_check[
    (offsetof(WorldObject, Enabled) == 12 + 3 * WORLDOBJECT_SLACK
     && offsetof(WorldObject, Matrix) == 32 + 3 * WORLDOBJECT_SLACK) ? 1 : -1];

// WorldObjectList, bTList<WorldObject> at gp-18120 (0x00331228): every
// WorldObject built, in the order built. Its static initialiser points it
// at itself; the port's definition does the same.
extern bNode WorldObjectList;

// WorldObjectSlotPool, gp-18112: where `new WorldObject` takes its 96
// bytes. NULL outside a track.
extern BSlotPool *WorldObjectSlotPool;

// WorldObject::WorldObject(unsigned int, bMatrix4 *, bool), 0x001cd760. An
// eModel from eModelSlotPool, its NameHash and Solid cleared and then
// eModel::Init with the name (scenery.h's gEModelInitFn, which aborts when
// unset). With a matrix, the matrix is copied, all sixteen words, and the
// object Enabled; without one, Enabled is 0 and Matrix is left as it was.
// AddLighting is stored, and the object goes on WorldObjectList's tail.
WorldObject *worldobject_construct(WorldObject *o, uint32_t name_hash,
                                   const bMatrix4 *matrix,
                                   int32_t add_lighting);

// _$_11WorldObject, 0x001cd828. The model, if there is one, through
// gEModelDestroyFn with 3; the object off WorldObjectList; bTNode's
// destructor, which does nothing; and with bit 0 of `flags` the slot back
// to WorldObjectSlotPool (__dl__11WorldObject, 0x001cdd38).
void worldobject_destruct(WorldObject *o, int32_t flags);

// GetNameHash, 0x001cd8a0: the model's NameHash.
uint32_t worldobject_get_name_hash(WorldObject *o);

// DoesArtExist(unsigned int), 0x001cd8d0, static. An eModel on the stack,
// its NameHash and Solid cleared, through Init with the name: whether it
// found a solid. The model is then destroyed with 2, which takes it off
// ModelList and frees nothing. Smokeable asks it of its pieces' names.
int32_t worldobject_does_art_exist(uint32_t name_hash);

// InitWorldObjects, 0x001cd918: WorldObjectSlotPool, 128 objects of 96
// bytes in pool 16. The list is not touched.
void init_world_objects(void);

// CloseWorldObjects, 0x001cd948: the destructor with 3 on the list's first
// object until the list is empty, then the pool deleted and cleared. The
// image also tests the first object for NULL, which a list of objects
// never holds (and on which it would spin); the port leaves the test out.
void close_world_objects(void);

struct eView;

// WorldObject::Render(eView *), 0x001cd998. Nothing for an object under 2
// pixels across (GetPixelSize of the matrix's position, radius 20) or out
// of sight (eModel::IsVisible, 0x0010cea8: a solid, and ClassifyAABB of
// its box through the matrix and the *current* view's
// WorldScreenClipMatrix not 0). The matrix is copied to frame memory and
// the model drawn there (eModel::Render, scenerycull.h's gEModelRenderFn,
// which aborts when unset) with flags 0: with no light context when
// AddLighting is 0, else with one from frame memory too, set up for the
// copy, the view's WorldViewMatrix and its camera's position with w 1.
// Frame memory running out draws nothing.
void worldobject_render(WorldObject *o, struct eView *view);

// RenderWorldObjects(eView *), 0x001cdb20: Render for each Enabled object
// on WorldObjectList, in order, the next read after each.
void render_world_objects(struct eView *view);

// `new (WorldObjectSlotPool) WorldObject(hash, matrix, add_lighting)`:
// bOMalloc from WorldObjectSlotPool and the constructor. Unbound so far:
// its one caller is OBB's debug cube.
extern WorldObject *(*gWorldObjectNewFn)(uint32_t name_hash,
                                         const bMatrix4 *matrix,
                                         int32_t add_lighting);

// The destructor with flags 3: off the list, and back to the pool.
extern void (*gWorldObjectDeleteFn)(WorldObject *o);

#endif
