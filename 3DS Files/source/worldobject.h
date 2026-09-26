// worldobject -- the front of WorldObject, a model placed in the world by a
// matrix (`WorldObject:Tt361=s96`). Its methods are the renderer's and are
// not ported. OBB's debug cube is the one caller so far: it makes one
// through gWorldObjectNewFn, destroys one through gWorldObjectDeleteFn, and
// writes the Matrix and the Enabled flag itself.

#ifndef WORLDOBJECT_H
#define WORLDOBJECT_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"

typedef struct WorldObject {
    struct WorldObject *next;   //  0  bNode, on WorldObjectList (gp-18720)
    struct WorldObject *prev;   //  4
    void     *pModel;           //  8  eModel*, from its own slot pool
    int32_t   Enabled;          // 12  drawn while nonzero
    int32_t   AddLighting;      // 16
    uint8_t   _pad20[12];       // 20  the quadword round-up
    bMatrix4  Matrix;           // 32
} WorldObject;

#define WORLDOBJECT_SLACK ((size_t)(sizeof(void *) - 4))

typedef char worldobject_layout_check[
    (offsetof(WorldObject, Enabled) == 12 + 3 * WORLDOBJECT_SLACK
     && offsetof(WorldObject, Matrix) == 32 + 3 * WORLDOBJECT_SLACK) ? 1 : -1];

// `new (WorldObjectSlotPool) WorldObject(hash, matrix, add_lighting)`:
// bOMalloc from WorldObjectSlotPool (gp-18712) and the constructor at
// 0x001c35c0, which loads the model named by the hash, copies the matrix
// and sets Enabled if there is one, and puts the object on the end of
// WorldObjectList.
extern WorldObject *(*gWorldObjectNewFn)(uint32_t name_hash,
                                         const bMatrix4 *matrix,
                                         int32_t add_lighting);

// The destructor at 0x001c3688 with flags 3: off the list, and back to the
// pool.
extern void (*gWorldObjectDeleteFn)(WorldObject *o);

#endif
