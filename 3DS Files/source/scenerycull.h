// scenerycull -- the second part of Scenery.obj (0x0014d460 .. 0x0014e59c),
// the cull: which of the loaded scenery each view draws this frame, and in
// what matrix. With it come the two functions beside eModel's methods that
// it calls, ClassifyAABB (0x0010b940) and IsBoundingBoxVisible
// (0x0010bb10), and eDisplayFrame's SetupSceneryCullInfo (0x0010e370,
// retail's 0x0010f858, the same but for one global's address).
//
// A frame's cull runs in three steps, all from eDisplayFrame:
//
//   1. SetupSceneryCullInfo fills one SceneryCullInfo per view that draws:
//      the view's clip matrix, a turn about z for the facades, and the
//      flags of the objects it leaves out. scenery_cull_setup_views is that
//      loop, as eDisplayFrame has it inline.
//   2. DoCulling walks the sections each view can see (the visible zone's
//      list, or every section with no zone) and each section's tree, and
//      appends a SceneryDrawInfo to SceneryDrawInfoTable for every object
//      that is in the frustum and big enough on the screen: a model, its
//      class, and a matrix from the frame malloc.
//   3. StuffScenery hands one view's run of the table to eModel::Render.
//
// A box's class is ClassifyAABB's: 0 outside, 1 across the frustum's edge,
// 2 inside. A node or object inside needs no more tests, and the class
// rides in the low two bits of the draw info's model pointer so that
// Render can skip the clipping.
//
// eModel::Render is the renderer's and is the seam gEModelRenderFn, which
// aborts when reached unset. The port's renderer is citro3d's, so its view
// matrices are the port's own; see docs/formats/scenery.md.

#ifndef SCENERYCULL_H
#define SCENERYCULL_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "eview.h"
#include "scenery.h"

// SceneryDrawInfo, 8 bytes (.mdebug type#3664). pModel's low two bits are
// the class the object was drawn in: 1 across the frustum, 2 inside. The
// matrix is NULL for an object drawn where it stands (flag 0x200).
typedef struct SceneryDrawInfo {
    eModel   *pModel;                       //  0  with the class in bits 0-1
    bMatrix4 *pMatrix;                      //  4
} SceneryDrawInfo;

// SceneryCullInfo, 208 bytes (.mdebug type#3670): one view's cull.
typedef struct SceneryCullInfo {
    bMatrix4          FacadeMatrix;         //   0  unread by the cull
    bMatrix4          ClipMatrix;           //  64  world to clip, row vectors
    eView            *pView;                // 128
    int32_t           ExcludeFlags;         // 132
    SceneryDrawInfo  *pFirstDrawInfo;       // 136
    SceneryDrawInfo  *pCurrentDrawInfo;     // 140
    SceneryDrawInfo  *pTopDrawInfo;         // 144
    uint32_t          pad0[3];              // 148
    bVector3          Position;             // 160  the camera's
    bVector3          Direction;            // 176  the camera's, unit
    float             H;                    // 192  the view's focal length
    uint32_t          pad1[3];              // 196
} SceneryCullInfo;                          // 208

#define SCENERY_MAX_CULL_INFOS 10

// GrandSceneryCullInfo, 2096 bytes (.mdebug type#3676): the frame's cull.
// eDisplayFrame keeps it on its stack.
typedef struct GrandSceneryCullInfo {
    SceneryCullInfo   SceneryCullInfos[SCENERY_MAX_CULL_INFOS];   //    0
    int32_t           NumCullInfos;         // 2080
    SceneryDrawInfo  *pFirstDrawInfo;       // 2084
    SceneryDrawInfo  *pCurrentDrawInfo;     // 2088
    SceneryDrawInfo  *pTopDrawInfo;         // 2092
} GrandSceneryCullInfo;                     // 2096

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char scenerycull_layout_check[
    (sizeof(SceneryDrawInfo) == 8
     && sizeof(SceneryCullInfo) == 208
     && offsetof(SceneryCullInfo, pView) == 128
     && offsetof(SceneryCullInfo, pTopDrawInfo) == 144
     && offsetof(SceneryCullInfo, Position) == 160
     && offsetof(SceneryCullInfo, H) == 192
     && sizeof(GrandSceneryCullInfo) == 2096
     && offsetof(GrandSceneryCullInfo, NumCullInfos) == 2080) ? 1 : -1];
#endif

// GrandSceneryCullInfo::SceneryDrawInfoTable, 0x002e8cd8: 4200 entries,
// which end where ScenerySectionHeaderTable starts.
#define SCENERY_MAX_DRAW_INFOS 4200
extern SceneryDrawInfo SceneryDrawInfoTable[SCENERY_MAX_DRAW_INFOS];

// The ExcludeFlags bits the cull reads from an object.
#define SCENERY_DRAW_IN_PLACE   0x0200      // no matrix: drawn where it is
#define SCENERY_RAISE_2M        0x0100      // with the view's 0x100, 2 m up

// eModel::Render(bMatrix4 *, eLightContext *, unsigned int), 0x0010c7c8.
// `flags` is 4 for an object inside the frustum, and 0 otherwise.
extern void (*gEModelRenderFn)(eModel *m, bMatrix4 *matrix, void *light,
                               uint32_t flags);

// ClassifyAABB(const bVector4 *, const bVector4 *, const bMatrix4 *),
// 0x0010b940. The box's eight corners through `clip` and VU0's vclipw
// against each: 2 when every corner is inside, 0 when all eight are
// outside one plane, and 1 otherwise. A corner exactly on a plane is
// inside. Only x, y and z of the corners are read.
int32_t scenery_classify_aabb(const bVector4 *min, const bVector4 *max,
                              const bMatrix4 *clip);

// IsBoundingBoxVisible(bVector3 *, bVector3 *, bMatrix4 *), 0x0010bb10:
// ClassifyAABB is not 0.
int32_t scenery_is_bounding_box_visible(const bVector3 *min,
                                        const bVector3 *max,
                                        const bMatrix4 *clip);

// ScenerySectionHeader::IsVisible(SceneryCullInfo *), 0x0014d890: the root
// node's box is not outside. 0 for a section with no tree.
int32_t scenery_is_visible(ScenerySectionHeader *h, SceneryCullInfo *ci);

// ScenerySectionHeader::DrawAScenery(int, SceneryCullInfo *, int),
// 0x0014d460. `cls` 1 classifies the object's own box first; anything
// else is taken as the class.
void scenery_draw_a_scenery(ScenerySectionHeader *h, int32_t index,
                            SceneryCullInfo *ci, int32_t cls);

// CullBruteForce(SceneryCullInfo *), 0x0014d948: every object, if the
// section is visible. Nothing calls it.
void scenery_cull_brute_force(ScenerySectionHeader *h, SceneryCullInfo *ci);

// TreeCull(SceneryCullInfo *), 0x0014d9c0: the tree from its first node,
// on a stack of 64 with no test for more.
void scenery_tree_cull(ScenerySectionHeader *h, SceneryCullInfo *ci);

// CullNodeRecursive(SceneryTreeNode *, SceneryCullInfo *, unsigned int),
// 0x0014db70: TreeCull by recursion. Nothing calls it from outside.
void scenery_cull_node_recursive(ScenerySectionHeader *h,
                                 SceneryTreeNode *node, SceneryCullInfo *ci,
                                 uint32_t cls);

// GrandSceneryCullInfo::WhatSectionsShouldWeDraw(short *, int,
// SceneryCullInfo *), 0x0014df98. At most `max` into `out`; the count.
int32_t scenery_what_sections_should_we_draw(GrandSceneryCullInfo *g,
                                             int16_t *out, int32_t max,
                                             SceneryCullInfo *ci);

// CullView(SceneryCullInfo *), 0x0014e110: up to 128 sections.
void scenery_cull_view(GrandSceneryCullInfo *g, SceneryCullInfo *ci);

// BatchCullViews, 0x0014e1b0: each section once for all the views, through
// ViewsVisibleThisFrame. Nothing calls it.
void scenery_batch_cull_views(GrandSceneryCullInfo *g);

// DoCulling, 0x0014e398.
void scenery_do_culling(GrandSceneryCullInfo *g);

// StuffScenery(eView *), 0x0014e4b0: the first cull info of `view`, to
// Render.
void scenery_stuff_scenery(GrandSceneryCullInfo *g, eView *view);

// SetupSceneryCullInfo(eView *, SceneryCullInfo &), 0x0010e370 (retail's
// 0x0010f858).
void scenery_setup_cull_info(eView *view, SceneryCullInfo *ci);

// eDisplayFrame's loop over the views, inline at 0x00112d3c: NumCullInfos
// is zeroed, and with InGameFlag set each of views 1..3 that is Active and
// whose first render target's word at 8 is set gets a cull info, then
// each of 4..9 the same way when EnvironmentMappingEnable is.
void scenery_cull_setup_views(GrandSceneryCullInfo *g, int32_t in_game);

#endif
