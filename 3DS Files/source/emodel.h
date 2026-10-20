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
// an animation that starts running; LoaderSolidList (esolid.c) fills the
// pointers, and everything else is the renderer's.
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

// eModel::ReconnectSolid, retail 0x0010c5e8 (the demo's 0x0010b2c0). The
// solid is looked up again by name. Only when it has changed is it
// stored, and then the animation start time is cleared, and set to 0xc000
// when the new solid has a rigid animation whose byte at +2 is 0. Retail
// then ORs bRandom(256) from bDefaultSeed into it when the solid has flag
// 0x20, the waving flag's.
void emodel_reconnect_solid(eModel *m);

// eReplacementTextureTable, 28 bytes: one texture a model draws in place
// of one of its solid's. ReplaceIndex has a slot for each of 16 instances
// of the model, by its ReplacementTextureInstanceIndex: the index in the
// solid's texture table of the one it replaces, or -1.
typedef struct eReplacementTextureTable {
    uint32_t  OldNameHash;                  //  0
    uint32_t  NewNameHash;                  //  4
    void     *pTextureInfo;                 //  8
    int8_t    ReplaceIndex[16];             // 12
} eReplacementTextureTable;                 // 28

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char emodel_replacement_check[
    (sizeof(eReplacementTextureTable) == 28
     && offsetof(eReplacementTextureTable, ReplaceIndex) == 12) ? 1 : -1];
#endif

// eModel::ReconnectTextureTable, 0x0010b330. Each replacement's texture
// is looked up again, with the default for a miss, and its slot for this
// instance is the first entry of the solid's table with the old name, or
// -1. Then ApplyReplacementTextureTable.
void emodel_reconnect_texture_table(eModel *m);

// eModel::ApplyReplacementTextureTable, 0x0010b528: each replacement
// whose slot for this instance is not -1 is written into that entry of
// the solid's table.
void emodel_apply_replacement_texture_table(eModel *m);

// eModel::AttachReplacementTextureTable(eReplacementTextureTable *, int,
// int), retail 0x0010c798: the table, its length and this model's
// instance are stored and the table reconnected. With a solid, the table
// is applied a second time and the solid's STs fixed.
void emodel_attach_replacement_texture_table(eModel *m,
                                             eReplacementTextureTable *t,
                                             int32_t count, int32_t instance);

// eModel::RenameTexture(unsigned int, unsigned int), retail 0x0010c7f0:
// the first entry of the solid's texture table named `old_hash` is
// renamed and given GetTextureInfo of the new name, with the default for
// a miss. 1 when one was, 0 when none was or there is no solid.
int32_t emodel_rename_texture(eModel *m, uint32_t old_hash,
                              uint32_t new_hash);

// eSolid::ReplaceLightMaterial(unsigned int, eLightMaterial *), retail
// 0x0010c4b0: every entry of the light material table named `old_hash`
// points at `material`.
void esolid_replace_light_material(eSolid *s, uint32_t old_hash,
                                   void *material);

// eModel::ReplaceLightMaterial(unsigned int, unsigned int), retail
// 0x0010cac0, and the eSolid overload it jumps to (0x0010c4e0): with a
// solid, elGetLightMaterial of the new name -- looked up whether or not an
// entry has the old one -- into every entry that does.
void emodel_replace_light_material(eModel *m, uint32_t old_hash,
                                   uint32_t new_hash);

// eModel::GetBoundingBox(bVector3 *, bVector3 *), retail 0x0010c9a8, and
// eSolid's (0x0010bd38): with a solid, its box's x, y and z into the two
// corners, whose fourth words are left alone. Without one, nothing.
void emodel_get_bounding_box(const eModel *m, bVector3 *mn, bVector3 *mx);

// eModel::SetEnvironmentMapping(unsigned int, int), retail 0x0010cae0:
// esolid.h's esolid_set_environment_mapping on the model's solid, if it
// has one. CarDamage takes a window's off when it breaks.
void emodel_set_environment_mapping(eModel *m, uint32_t hash, int32_t on);

// ReconnectAllModels, 0x0010b7b0: every model on ModelList gets its solid
// and its replacements again, and its solid's STs fixed.
void emodel_reconnect_all_models(void);

// eModel's deleting destructor, _$_6eModel (0x00114918): UnInit, bNode's
// destructor (which does nothing without bit 0), then with bit 0 of
// `flags` the slot back to eModelSlotPool. The unloaders pass 3. This is
// the function gEModelDestroyFn stands for.
void emodel_delete(eModel *m, int32_t flags);

// eInitSlotPools' second pool (0x00108a70): eModelSlotPool, 5000 models
// of 24 bytes. The other five are the renderer's and are not made here.
// Nothing happens when the pool is already made.
void emodel_init_slot_pool(void);

// ---------------------------------------- the rigid animation's timing
//
// emodelanim.c: these three read WorldTimeFrames, which nothing else here
// does. RigidAnimationStartTime keeps a start in its low 14 bits, in
// WorldTimeFrames; bit 0x4000 loops the animation and bit 0x8000 marks a
// start as set, so a field of 0 is an animation not started. The
// animation runs NumFrames * FrameRateScale sixtieths, where
// SetRigidAnimationFrameNumber counts two to a frame whatever the scale.

// eModel::GetRigidAnimation, 0x0010c8f0: the solid's rigid animation, or
// NULL for no solid or none.
struct eRigidAnimation *emodel_get_rigid_animation(const eModel *m);

// eModel::GetRigidAnimationTime, 0x0010dae8. -1 for a start of 0.
// Otherwise the frames since the start, mod 0x4000: for a looping
// animation that mod NumFrames * FrameRateScale (both read signed), and
// for any other that, or -1 once it is not under it. The model must have
// a solid with an animation.
int32_t emodel_get_rigid_animation_time(const eModel *m);

// eModel::SetRigidAnimationFrameNumber(int), 0x0010c910: a start of
// WorldTimeFrames less twice the frame, low 14 bits, with bit 0x8000 and
// not 0x4000.
void emodel_set_rigid_animation_frame_number(eModel *m, int32_t frame);

// ---------------------------------------- the animations eModel::Render plays
//
// eModel::Render (0x0010dc80) sets these up before the strips: a rigid
// animation moves the model by a matrix a frame, and a vertex animation
// swaps the model's solid for the frame's. The port's renderer
// (trackview.c's render_model) calls emodel_setup_animation where Render
// does. Cross-check: tools/emodelanim_check.py.

// eRigidAnimation::GetMatrixAtTime(bMatrix4 *, int), 0x001a7518: the
// matrix of frame (time / FrameRateScale) % NumFrames, both signed, from
// the frames that follow the 48-byte header. No blend between frames.
void erigidanimation_get_matrix_at_time(const struct eRigidAnimation *a,
                                        bMatrix4 *out, int32_t time);

// eModel::SetupRigidAnimation(bMatrix4 *), 0x0010dbd0. An animation that
// has run its course (GetRigidAnimationTime's -1) has its start cleared
// and draws in `matrix`. Otherwise 64 bytes of eframe_malloc take the
// frame's matrix times `matrix` (bMulMatrix(out, matrix, out)), and that
// is what the model draws in. A frame malloc that fails draws in `matrix`.
bMatrix4 *emodel_setup_rigid_animation(eModel *m, bMatrix4 *matrix);

// eModel::SetupVertexAnimation, 0x0010db70: the solid becomes the frame's
// one of its vertex animator's, at FrameRate frames a second from the
// start's low 14 bits: ((WorldTimeFrames - start) * FrameRate / 60) mod
// NumSolids, signed, then mod again unsigned.
void emodel_setup_vertex_animation(eModel *m);

// eModel::Render's setup, before DetermineVisibleStrips: for a model with
// a solid, SetupRigidAnimation when the solid has a rigid animation and
// the start is not 0, then SetupVertexAnimation when the solid (the one
// after that) has a vertex animator. The matrix to draw in comes back; a
// model with no solid gets `matrix` back and Render draws nothing.
bMatrix4 *emodel_setup_animation(eModel *m, bMatrix4 *matrix);

#endif
