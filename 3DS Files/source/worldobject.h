// worldobject -- WorldObject, a model placed in the world by a matrix
// (`WorldObject:Tt361=s96`), retail's 0x001cd760 .. 0x001cdd40: the
// constructor and destructor, and InitWorldObjects / CloseWorldObjects,
// which make and empty WorldObjectList's pool. Render and
// RenderWorldObjects, which draw each enabled one after the cars, are the
// renderer's and come with 12j-2b.
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

// InitWorldObjects, 0x001cd918: WorldObjectSlotPool, 128 objects of 96
// bytes in pool 16. The list is not touched.
void init_world_objects(void);

// CloseWorldObjects, 0x001cd948: the destructor with 3 on the list's first
// object until the list is empty, then the pool deleted and cleared. The
// image also tests the first object for NULL, which a list of objects
// never holds (and on which it would spin); the port leaves the test out.
void close_world_objects(void);

// `new (WorldObjectSlotPool) WorldObject(hash, matrix, add_lighting)`:
// bOMalloc from WorldObjectSlotPool and the constructor. Unbound so far:
// its one caller is OBB's debug cube.
extern WorldObject *(*gWorldObjectNewFn)(uint32_t name_hash,
                                         const bMatrix4 *matrix,
                                         int32_t add_lighting);

// The destructor with flags 3: off the list, and back to the pool.
extern void (*gWorldObjectDeleteFn)(WorldObject *o);

#endif
