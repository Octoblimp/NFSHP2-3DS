// emodel -- the list half of eModel.obj (0x0010b1f8 .. 0x0010b330) and
// eModel's deleting destructor beside it (0x00114918): how a model finds
// its solid by name, and how it is put on and taken off ModelList.
//
// An eModel is a name and a pointer. Init stores the name, looks the solid
// up on SolidList by it, and puts the model on ModelList; a model whose
// solid is not loaded yet keeps a NULL Solid and is reconnected later by
// the loader that brings it. The solid is the eSolid in the bundle, in
// place: LoaderSolidList links each one onto SolidList by the bNode at its
// start, and the eSolid's NameHash at +8 is what eFindSolid compares.
//
// Render, the strips and the replacement textures are the renderer's and
// are not here. The port's renderer draws an eSolid from what geometry.c
// decodes of it; see trackview.c for the one user.

#ifndef EMODEL_H
#define EMODEL_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "eview.h"
#include "scenery.h"

// eSolid, 192 bytes (.mdebug type#3247), as it sits in the bundle. The
// list half reads NameHash and pRigidAnimation, whose byte at +2 is 0 for
// an animation that starts running; LoaderSolidList fills the pointers,
// and everything else is the renderer's.
typedef struct eSolid {
    bNode     Node;                         //   0  on SolidList
    uint32_t  NameHash;                     //   8
    uint32_t  Version;                      //  12
    char      Name[24];                     //  16
    uint32_t  ExternalRigidAnimationNameHash;   //  40
    void     *pVertexAnimator;              //  44
    uint16_t  Flags;                        //  48
    uint16_t  StripFlags;                   //  50
    int16_t   NumStrips;                    //  52
    int16_t   NumPolys;                     //  54
    int16_t   NumVerts;                     //  56
    int16_t   NumOriginalVerts;             //  58
    uint32_t  SizeofStripEntryData;         //  60
    bVector4  AABBMin;                      //  64
    bVector4  AABBMax;                      //  80
    bMatrix4  PivotMatrix;                  //  96
    int32_t   AnimationTreeNumNodes;        // 160  eAnimationTree
    void     *pAnimationTreeNodes;          // 164
    uint8_t  *pRigidAnimation;              // 168
    int16_t   NumTextureTableEntries;       // 172
    int16_t   NumLightMaterials;            // 174
    void     *StripEntryTable;              // 176
    void     *StripEntryDataStart;          // 180
    void     *pTextureTable;                // 184
    void     *LightMaterialTable;           // 188
} eSolid;                                   // 192

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char emodel_layout_check[
    (sizeof(eSolid) == 192 && offsetof(eSolid, NameHash) == 8
     && offsetof(eSolid, AABBMin) == 64 && offsetof(eSolid, PivotMatrix) == 96
     && offsetof(eSolid, pRigidAnimation) == 168
     && offsetof(eSolid, LightMaterialTable) == 188) ? 1 : -1];
#endif

// eFindSolid(unsigned int), 0x0010b1f8: the first eSolid on SolidList
// with that name, or NULL.
void *eFindSolid(uint32_t name_hash);

// eModel::Init(unsigned int), 0x0010b230. The name is stored and the
// replacement table cleared; a name of 0 stops there. Otherwise the solid
// is reconnected and the model goes on ModelList's tail.
void emodel_init(eModel *m, uint32_t name_hash);

// eModel::UnInit, 0x0010b288. A model with a name comes off ModelList and
// is cleared; one without is left alone.
void emodel_uninit(eModel *m);

// eModel::ReconnectSolid, 0x0010b2c0. The solid is looked up again by
// name. Only when it has changed is it stored, and then the animation
// start time is cleared, and set to 0xc000 when the new solid has a rigid
// animation whose byte at +2 is 0.
void emodel_reconnect_solid(eModel *m);

// eModel's deleting destructor, _$_6eModel (0x00114918): UnInit, bNode's
// destructor (which does nothing without bit 0), then with bit 0 of
// `flags` the slot back to eModelSlotPool. The unloaders pass 3. This is
// the function gEModelDestroyFn stands for.
void emodel_delete(eModel *m, int32_t flags);

// eInitSlotPools' second pool (0x00108a70): eModelSlotPool, 5000 models
// of 24 bytes. The other five are the renderer's and are not made here.
// Nothing happens when the pool is already made.
void emodel_init_slot_pool(void);

#endif
