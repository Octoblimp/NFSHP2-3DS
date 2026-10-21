// eanim -- retail's eAnimation.obj (0x001a67f8 .. 0x001a7c3c): the bone
// animations of the drivers in the cars (TASKS 83a).
//
// An eAnimationSolid is a bundle's 0x80034008 chunk, in place: a header and
// three tables, a quaternion per bone per frame (four int16s over 32767)
// and a root translation per frame. LoaderAnimations links each onto
// eAnimationSolidList, where eFindAnimationSolid finds it by name.
//
// An eAnimation is an eModel whose solid has an animation tree (eSolid +160:
// a bone per node, with its object-to-bone matrix, its offset from its
// parent and its children) and one or two of those solids to pose it from.
// Render poses the tree from the frame's quaternions, multiplies each bone
// by its object-to-bone matrix, and hands the bones to eModel::RenderStrips,
// which blends each vertex between two of them (see trackview.c's
// render_model_bones). AnimatedDriver (animdriver.h) is the one user.
//
// Free of <3ds.h>: tools/animdriver_check.py runs it next to retail's code
// in mipsemu.

#ifndef EANIM_H
#define EANIM_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bquat.h"
#include "bvector.h"
#include "scenery.h"

#define EANIMATION_CHUNK_ID 0x80034008u

// eAnimationSolid, 96 bytes, the first child chunk's payload at 16 bytes.
typedef struct eAnimationSolid {
    bNode        Node;                      //  0  on eAnimationSolidList
    char         Name[24];                  //  8
    bVector3     BBoxMin;                   // 32
    bVector3     BBoxMax;                   // 48
    uint32_t     NameHash;                  // 64
    uint16_t     NumFrames;                 // 68
    uint16_t     NumNodes;                  // 70
    int32_t      NumRotationKeys;           // 72
    int16_t     *pRotationKeys;             // 76  x, y, z, w; NumFrames a node
    int32_t      NumTranslationKeys;        // 80
    bVector3    *pTranslationKeys;          // 84  one a frame
    void        *pLabelledFrames;           // 88  NULL without the chunk
    uint32_t     Padding;                   // 92
} eAnimationSolid;                          // 96

// eAnimationTreeNode, 96 bytes, an eSolid's 0x34007 chunk.
typedef struct eAnimationTreeNode {
    bMatrix4     ObjectToBoneSpace;         //  0
    float        Translation[3];            // 64  from the parent
    int8_t       ThisNodeIndex;             // 76
    int8_t       ParentNodeIndex;           // 77
    int8_t       FirstChildNodeIndex;       // 78  0 for none
    int8_t       NextChildNodeIndex;        // 79  0 for none
    char         NodeName[16];              // 80
} eAnimationTreeNode;                       // 96

// eAnimationTree, the eSolid's +160 and +164.
typedef struct eAnimationTree {
    int32_t             NumNodes;
    eAnimationTreeNode *pNodes;
} eAnimationTree;

// eAnimation, 80 bytes.
typedef struct eAnimation {
    bNode            Node;                  //  0  on eAnimationList
    eModel           Model;                 //  8
    uint32_t         NameHash1;             // 32
    uint32_t         NameHash2;             // 36
    eAnimationSolid *pAnimationSolid1;      // 40
    eAnimationSolid *pAnimationSolid2;      // 44
    float            FrameNumber1;          // 48
    float            FrameNumber2;          // 52
    float            Weight1;               // 56  of solid 1 over solid 2
    uint32_t         Pad60;                 // 60
    uint64_t         WeightFlags;           // 64  a bit a node: solid 1 alone
    bMatrix4        *pCurrentMatrices;      // 72  the frame's bones
    uint32_t         Pad76;                 // 76
} eAnimation;                               // 80

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char eanim_layout_check[
    (sizeof(eAnimationSolid) == 96
     && offsetof(eAnimationSolid, NameHash) == 64
     && offsetof(eAnimationSolid, pRotationKeys) == 76
     && offsetof(eAnimationSolid, pTranslationKeys) == 84
     && sizeof(eAnimationTreeNode) == 96
     && offsetof(eAnimationTreeNode, FirstChildNodeIndex) == 78
     && sizeof(eAnimation) == 80
     && offsetof(eAnimation, NameHash1) == 32
     && offsetof(eAnimation, Weight1) == 56
     && offsetof(eAnimation, WeightFlags) == 64
     && offsetof(eAnimation, pCurrentMatrices) == 72) ? 1 : -1];
#endif

// eAnimationSolidList, gp-19400, and eAnimationList, gp-19416: empty
// rings at startup (0x001a7c08 and 0x001a71b0).
extern bNode eAnimationSolidList;
extern bNode eAnimationList;

// ------------------------------------------------------- eAnimationSolid

// LoaderAnimations(bChunk *), 0x001a7570. Not 0x80034008: 0. The solid is
// the first child's payload, 16-aligned; the rotation keys the second's,
// the translation keys the third's, and the labelled frames a fourth's
// when there is one. The solid goes on the list's tail, eDirtyAnimations
// is set, and the answer is 1.
int eanim_loader(uint8_t *chunk);

// UnloaderAnimations(bChunk *), 0x001a7688: the solid off the list and
// eDirtyAnimations set, 1; 0 for another chunk.
int eanim_unloader(uint8_t *chunk);

// eFindAnimationSolid(unsigned int), 0x001a76c8: the first on the list
// with the name, or NULL.
eAnimationSolid *eFindAnimationSolid(uint32_t name_hash);

// GetRotation(bQuaternion *, int, float), 0x001a7700: node `node`'s key at
// frame (int)frame, unchecked, each lane over 32767.
void eanimsolid_get_rotation(const eAnimationSolid *s, bQuaternion *q,
                             int32_t node, float frame);

// SetRotation(const bQuaternion *, int, float), 0x001a7790: the key set to
// each lane times 32767, truncated. A frame outside the solid's is 0.
void eanimsolid_set_rotation(eAnimationSolid *s, const bQuaternion *q,
                             int32_t node, float frame);

// GetRotations(bQuaternion *, float), 0x001a7830: every node's at the
// frame, unchecked.
void eanimsolid_get_rotations(const eAnimationSolid *s, bQuaternion *q,
                              float frame);

// GetTranslation(bVector3 *, float), 0x001a78e0: the frame's root
// translation, x, y and z; a frame outside the solid's is 0.
void eanimsolid_get_translation(const eAnimationSolid *s, bVector3 *v,
                                float frame);

// GetBlendedRotations(bQuaternion *, float, float, float, eAnimationSolid *,
// unsigned long), 0x001a7938: for each of this solid's nodes,
// Slerp(out, the other's key at frame2, this one's at frame1, weight) --
// weight 1 for a node whose bit is set in a non-zero `flags`.
void eanimsolid_get_blended_rotations(const eAnimationSolid *s,
                                      bQuaternion *q, float frame1,
                                      float frame2, float weight,
                                      const eAnimationSolid *other,
                                      uint64_t flags);

// ------------------------------------------------------------ eAnimation

// The constructor, 0x001a67f8: on eAnimationList's tail, the model and
// both animations cleared, Weight1 1. The deleting destructor, 0x001a6850:
// off the list, the model's destructor (eModel's, with 2), and with bit 0
// of `flags` the memory freed (bFree).
eAnimation *eanim_construct(eAnimation *a);
void        eanim_destroy(eAnimation *a, int32_t flags);

// Init(unsigned int), 0x001a68a0, and UnInit, 0x001a68a8: the model's.
void eanim_init(eAnimation *a, uint32_t name_hash);
void eanim_uninit(eAnimation *a);

// ReconnectSolid, 0x001a68b0: each named animation looked up again.
void eanim_reconnect_solid(eAnimation *a);

// GetAnimationSolid(unsigned int), 0x001a6900: the solid of either name.
// A name that is neither is taken as the first when that is unnamed, the
// second otherwise, and looked up.
eAnimationSolid *eanim_get_animation_solid(eAnimation *a, uint32_t hash);

// SetAnimation(unsigned int, float), 0x001a6968, and SetBlendedAnimation
// (unsigned int, float, unsigned int, float, float), 0x001a69c0. A name is
// looked up only when it changes.
void eanim_set_animation(eAnimation *a, uint32_t hash, float frame);
void eanim_set_blended_animation(eAnimation *a, uint32_t hash1, float frame1,
                                 uint32_t hash2, float frame2, float weight);

// Render(bMatrix4 *, eLightContext *, unsigned int), 0x001a6a50: the first
// animation's translation and rotations, blended with the second's when
// Weight1 is not 1, into the other Render. Nothing without the first, the
// tree, or a tree of the solids' size.
void eanim_render(eAnimation *a, bMatrix4 *matrix, void *light,
                  uint32_t flags);

// Render(bMatrix4 *, const bVector3 *, const bQuaternion *, eLightContext *,
// unsigned int), 0x001a6b80. A frame matrix of `matrix` moved by the
// translation in its axes; DetermineVisibleStrips; the frame's bones, each
// posed down the tree from the identity and then multiplied by its node's
// ObjectToBoneSpace (eMulMatrix(bone, o2b, bone)); RenderStrips with them.
// A frame malloc that fails draws nothing.
void eanim_render_posed(eAnimation *a, bMatrix4 *matrix,
                        const bVector3 *translation, const bQuaternion *q,
                        void *light, uint32_t flags);

// GetRootTranslation(bVector3 *), 0x001a6da0: the tree's first node's
// Translation, all four lanes, or (0, 0, 0) with the fourth unset.
void eanim_get_root_translation(eAnimation *a, bVector3 *v);

// PoseMatrixRecursive(const bMatrix4 *, const bQuaternion *,
// eAnimationTree *, int), 0x001a6e00. Node `node`'s bone is its quaternion's
// matrix with its Translation, times the parent's; node nBoneScale's rows
// are then scaled by vBoneScale's x, y and z (the R/C Car's big head);
// then each child in turn.
void eanim_pose_matrix_recursive(eAnimation *a, const bMatrix4 *parent,
                                 const bQuaternion *q, eAnimationTree *tree,
                                 int32_t node);

// GetBoundingBox(bVector3 *, bVector3 *), 0x001a6f50: both animations'
// boxes, widened on every side by the largest coordinate of the model's.
void eanim_get_bounding_box(eAnimation *a, bVector3 *mn, bVector3 *mx);

// ReconnectAllAnimations, 0x001a7098: ReconnectSolid on each, in order.
// What eFixUpTables calls through gReconnectAllAnimationsFn.
void eReconnectAllAnimations(void);

// eModel::GetAnimationTree, 0x0010ca80: the solid's +160, or NULL.
eAnimationTree *emodel_get_animation_tree(const eModel *m);

// ------------------------------------------------------------ the seams
//
// eModel::DetermineVisibleStrips(const bMatrix4 *, int, int), 0x0010d390,
// and RenderStrips(bMatrix4 *, eLightContext *, unsigned int, bMatrix4 *),
// 0x0010dd58, are the renderer's. NULL visibility is visible; a NULL draw
// draws nothing. trackview.c binds the draw.
extern int32_t (*gEModelDetermineVisibleStripsFn)(eModel *m,
                                                  const bMatrix4 *matrix,
                                                  int32_t a, int32_t b);
extern void (*gEModelRenderStripsBonesFn)(eModel *m, bMatrix4 *matrix,
                                          void *light, uint32_t flags,
                                          bMatrix4 *bones);

#endif
