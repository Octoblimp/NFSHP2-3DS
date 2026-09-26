// obb -- OBB, the oriented box World's collision prediction keeps twenty of
// for each car. Its methods are the last seven in DriveTarget.obj,
// 0x0020a840 .. 0x0020ab48. DoSnapshot (0x0020a928) waits on ReplaySnapshot.
// docs/formats/world.md has the decode.

#ifndef OBB_H
#define OBB_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "worldobject.h"

// `OBB:Tt3937=s80`.
typedef struct OBB {
    bVector3     Position;   //  0  never copied by operator=
    bVector3     A0;         // 16  the axes
    bVector3     A1;         // 32
    bVector3     A2;         // 48
    float        a0;         // 64  the half-lengths along them
    float        a1;         // 68
    float        a2;         // 72
    WorldObject *WorldObj;   // 76  the debug cube Render makes, or NULL
} OBB;

typedef char obb_layout_check[
    (offsetof(OBB, a2) == 72 && offsetof(OBB, WorldObj) == 76
     + ((sizeof(void *) - 4) & 4)) ? 1 : -1];

// 0x0020a8c0. No cube yet.
OBB *obb_init(OBB *o);

// 0x0020a8d0, without the delete: the cube goes, if there is one.
void obb_destroy(OBB *o);

// 0x0020a840, operator=(OBB &). The axes (all four lanes of each) and the
// half-lengths are copied and the Position is not. The destination's cube
// is destroyed, and the source's cube moves to the destination: the source
// is left without one.
OBB *obb_assign(OBB *dst, OBB *src);

// 0x0020a9e0. The box drawn as the DEBUG_CUBE model: each axis scaled by
// twice its half-length (all four lanes) and put through eMulMatrix with an
// identity, and `pos` written into the fourth row's first three lanes. The
// cube is made the first time, and enabled every time.
void obb_render(OBB *o, const bVector3 *pos);

// 0x0020ab28. The cube, if there is one, is disabled.
void obb_do_not_render(OBB *o);

// 0x0020ab40. Empty.
void obb_print(OBB *o);

// bStringHash("DEBUG_CUBE").
#define OBB_DEBUG_CUBE_HASH 0x1786e724u

#endif
