// scenery -- the first part of Scenery.obj (0x0014c3a0 .. 0x0014e734): the
// track's scenery as it comes off the disc, and the visible zones that say
// which of it to draw.
//
// A track's scenery is cut into numbered sections. Each is a 0x80034100
// container of four chunks: a header (0x34101), the kinds of object in it
// (0x34102, SceneryInfo: up to three LOD models by name hash), the objects
// placed (0x34103, SceneryInstance: a kind, a box, a position and a
// rotation) and a tree over the objects for the cull (0x34104). The loader
// fills the header's pointers in place, builds each kind's models, and puts
// the header on ScenerySectionHeaderList and in ScenerySectionHeaderTable.
// A visible zone is a polygon on the ground with the list of sections that
// can be seen from inside it; the zones are one chunk (0x34106) of 288-byte
// records. TRACKB12 has 122 sections and 23 zones.
//
// This slice is the data half: the loader and unloader, the three finds,
// the zones' lookups, the backwards-track flip and the facade matrix. The
// cull, DrawAScenery, StuffScenery and the debug views (UpdateCaffeine,
// RenderBoundary, ScrollText, HandleTweakingVisibleZones) are the next.
// RenderVisibleZones is `jr ra` in the image.
//
// eModel is the renderer's (eModel.obj), which the port does not have:
// eModel::Init and its deleting destructor are the two seams below. The
// loader takes each model from eModelSlotPool and zeroes NameHash and Solid
// first, as the image's inline constructor does.
//
// On the handheld every record here is the disc's layout, so the loader
// works on the bundle's bytes. On a 64-bit host the pointers widen, and the
// loader's strides are the host's sizes: tools/src/scenery_test.c widens a
// container before handing it over, as polyhedra_test.c does.
//
// docs/formats/scenery.md has the decode.

#ifndef SCENERY_H
#define SCENERY_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bslotpool.h"
#include "bvector.h"

// eModel, 24 bytes (.mdebug type#3267). Only what the loader touches is
// named here; eModel.obj is the renderer's.
typedef struct eModel {
    bNode     Node;                         //  0  on the model list
    uint32_t  NameHash;                     //  8
    void     *Solid;                        // 12  eSolid *
    void     *pReplacementTextureTable;     // 16
    uint8_t   NumReplacementTextures;       // 20
    uint8_t   ReplacementTextureInstanceIndex;  // 21
    int16_t   RigidAnimationStartTime;      // 22
} eModel;                                   // 24

// eModelSlotPool, 0x00322770 (gp-25728). eInit makes it; the port's
// renderer does not, so it is NULL until something sets it.
extern BSlotPool *eModelSlotPool;

// eModel::Init(unsigned int), 0x0010b230, and the deleting destructor
// _$_6eModel, 0x00114918, which the unloaders call with 3. Both abort when
// reached unset: a model left unbuilt would draw nothing without saying so.
extern void (*gEModelInitFn)(eModel *m, uint32_t name_hash);
extern void (*gEModelDestroyFn)(eModel *m, int32_t flags);

// SceneryBoundingBox, 12 bytes: two corners in whole metres.
typedef struct SceneryBoundingBox {
    int16_t BBoxMin[3];                     //  0
    int16_t BBoxMax[3];                     //  6
} SceneryBoundingBox;                       // 12

// SceneryInfo, 40 bytes on the disc: one kind of object.
typedef struct SceneryInfo {
    uint32_t  NameHash[3];                  //  0  per LOD, 0 for none
    int16_t   FarClipSize[3];               // 12
    int16_t   Dummy;                        // 18
    eModel   *pModel[3];                    // 20  the loader's
    uint8_t   IsFacadeFlag[3];              // 32
    uint8_t   Dummy2;                       // 35
    float     Radius;                       // 36
} SceneryInfo;                              // 40

// SceneryInstance, 48 bytes: one object placed. The rotation is three rows
// in units of 2^-14.
typedef struct SceneryInstance {
    SceneryBoundingBox BBox;                //  0
    int16_t   SceneryInfoNumber;            // 12
    uint16_t  ExcludeFlags;                 // 14
    float     Position[3];                  // 16
    int16_t   Rotation[9];                  // 28
    uint16_t  Pad;                          // 46
} SceneryInstance;                          // 48

// ExcludeFlags' bit for an object turned round on a backwards track.
#define SCENERY_FLIP_ON_BACKWARDS 0x0400

// SceneryTreeNode, 24 bytes. A child code is an instance or a node; the
// cull (the next slice) reads them.
typedef struct SceneryTreeNode {
    SceneryBoundingBox BBox;                //  0
    int16_t   NumChildren;                  // 12
    int16_t   ChildCodes[5];                // 14
} SceneryTreeNode;                          // 24

// ScenerySectionHeader, 56 bytes on the disc, where every word but
// SectionNumber is 0 and the loader fills the pointers and counts.
typedef struct ScenerySectionHeader {
    bNode             Node;                     //  0
    int32_t           SectionNumber;            //  8
    int32_t           NumPolygonsInMemory;      // 12
    int32_t           NumPolygonsInWorld;       // 16
    SceneryInfo      *pSceneryInfo;             // 20
    int32_t           NumSceneryInfo;           // 24
    SceneryInstance  *pSceneryInstance;         // 28
    int32_t           NumSceneryInstances;      // 32
    SceneryTreeNode  *SceneryTreeNodeTable;     // 36
    int32_t           NumSceneryTreeNodes;      // 40
    void             *SceneryTreeGroupNodeTable;    // 44
    int32_t           NumSceneryTreeGroupNodes; // 48
    uint32_t          ViewsVisibleThisFrame;    // 52
} ScenerySectionHeader;                         // 56

// The chunk ids.
#define SCENERY_CONTAINER_ID 0x80034100u
#define SCENERY_HEADER_ID    0x00034101u
#define SCENERY_INFO_ID      0x00034102u
#define SCENERY_INSTANCE_ID  0x00034103u
#define SCENERY_TREE_ID      0x00034104u
#define VISIBLE_ZONE_ID      0x00034106u

// ScenerySectionHeaderTable, 0x002f1018: 300 slots by section number.
#define SCENERY_MAX_SECTIONS 300
extern ScenerySectionHeader *ScenerySectionHeaderTable[SCENERY_MAX_SECTIONS];

// ScenerySectionHeaderList, 0x003233c0 (gp-22576). Sections below 90 are
// added at the tail and the rest at the head.
extern bNode ScenerySectionHeaderList;

// VisibleZone, 288 bytes on the disc.
#define VISIBLE_ZONE_MAX_SECTIONS 64
#define VISIBLE_ZONE_MAX_POINTS   16
typedef struct VisibleZone {
    bNode     Node;                             //   0
    int32_t   ZoneNumber;                       //   8
    bVector2  Center;                           //  12
    void     *pCaffeineObj;                     //  20  the editor's
    int32_t   NumVisibleScenerySections;        //  24
    int16_t   VisibleScenerySections[VISIBLE_ZONE_MAX_SECTIONS];  //  28
    int32_t   NumPerimeterPoints;               // 156
    bVector2  PerimeterPoints[VISIBLE_ZONE_MAX_POINTS];           // 160
} VisibleZone;                                  // 288

// VisibleZoneList, 0x003233c8 (gp-22568). FindVisibleZone moves the zone
// it finds to the front.
extern bNode VisibleZoneList;

// pVisibleZoneBoundaryModel, 0x003233d0 (gp-22560): MARKER_BOUNDARY, which
// RenderBoundary draws along a zone's edge.
extern eModel *pVisibleZoneBoundaryModel;

// CurrentZoneNumber, 0x003233b8 (gp-22584), -1 until the cull finds a
// zone, and AdvanceFastBlinkSectionNumber, 0x003233e0 (gp-22544). The cull
// and the debug view write them.
extern int32_t CurrentZoneNumber;
extern int32_t AdvanceFastBlinkSectionNumber;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char scenery_layout_check[
    (sizeof(eModel) == 24 && sizeof(SceneryBoundingBox) == 12
     && sizeof(SceneryInfo) == 40 && offsetof(SceneryInfo, pModel) == 20
     && offsetof(SceneryInfo, Radius) == 36
     && sizeof(SceneryInstance) == 48
     && offsetof(SceneryInstance, Rotation) == 28
     && sizeof(SceneryTreeNode) == 24
     && sizeof(ScenerySectionHeader) == 56
     && offsetof(ScenerySectionHeader, SceneryTreeGroupNodeTable) == 44
     && sizeof(VisibleZone) == 288
     && offsetof(VisibleZone, NumPerimeterPoints) == 156
     && offsetof(VisibleZone, PerimeterPoints) == 160) ? 1 : -1];
#endif

// _GLOBAL_$I$CurrentZoneNumber, 0x0014e718: both lists empty.
void scenery_static_init(void);

// _GLOBAL_$D$CurrentZoneNumber, 0x0014e6f0: each list's destructor, zones
// first. A node still on a list is unlinked and handed to bFree, which is
// wrong for a node inside a chunk; the unloaders empty both lists first.
void scenery_static_close(void);

// LoaderScenery, 0x0014c3a0. A 0x80034100 container or a 0x34106 zone
// chunk; anything else is not its, and it returns 0.
int32_t scenery_loader(uint8_t *chunk);

// UnloaderScenery, 0x0014c658. A container's header must be its first
// chunk: the unloader looks for it there and nowhere else.
int32_t scenery_unloader(uint8_t *chunk);

// FindSceneryInfo(unsigned int), 0x0014c7a0: the first kind in the list
// whose first LOD is `name_hash`, or NULL.
SceneryInfo *scenery_find_info(uint32_t name_hash);

// FindSceneryInstance(unsigned int), 0x0014c800: the first object whose
// kind's first LOD is `name_hash`, or NULL.
SceneryInstance *scenery_find_instance_by_hash(uint32_t name_hash);

// FindSceneryInstance(int, int), 0x0014c880. NULL for a section that is
// not loaded; `index` is not checked.
SceneryInstance *scenery_find_instance(int32_t section, int32_t index);

// IsPointInPoly, 0x0014c8b8: the crossing test, 1 inside and 0 out.
int32_t scenery_is_point_in_poly(const bVector2 *pt, const bVector2 *poly,
                                 int32_t n);

// FindVisibleZone, 0x0014c980.
VisibleZone *scenery_find_visible_zone(const bVector2 *pt);

// VisibleZone::FindIndexTo, 0x0014ca10, and FindNextFreeIndex, 0x0014ca58.
int32_t visible_zone_find_index_to(const VisibleZone *z, int32_t section);
int32_t visible_zone_find_next_free_index(VisibleZone *z);

// InitVisibleZones, 0x0014cf18, and CloseVisibleZones, 0x0014cf68.
void scenery_init_visible_zones(void);
void scenery_close_visible_zones(void);

// HandleJoystickBlinkSection, 0x0014cf90, and GetCurrentZoneNumber,
// 0x0014cfb0.
void scenery_handle_joystick_blink_section(int32_t step);
int32_t scenery_get_current_zone_number(void);

// IsInTable, 0x0014cfb8, and ToggleIsInTable, 0x0014cfe8.
int32_t scenery_is_in_table(const int16_t *table, int32_t n, int32_t value);
int32_t scenery_toggle_is_in_table(int16_t *table, int32_t n, int32_t max,
                                   int32_t value);

// CreateFacadeMatrix, 0x0014d3f0: turned about z to face `eye`, at `pos`.
void scenery_create_facade_matrix(bMatrix4 *m, const bVector3 *pos,
                                  const bVector3 *eye);

// ScenerySectionHeader::FlipObjectsOnBackwardsTrack, 0x0014dcd8.
void scenery_flip_objects_on_backwards_track(ScenerySectionHeader *h);

#endif
