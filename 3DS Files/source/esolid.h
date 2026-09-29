// esolid -- the solid list's loader, from the engine's object at
// 0x00102ff0 .. 0x00103918, and the three table fix-ups eSolid has in
// eModel.obj. LoaderSolidList takes a 0x80034000 chunk, a file's solids,
// and fixes each one's pointers into the chunk where it lies: its strip
// table, its packet, its texture and light material tables, its animation
// tree and its rigid animation. Then it links the solid onto SolidList.
// eFixUpTables is what the loaders' dirty flags come back to after a
// load, through PostLoadFixup.
//
// A 0x80034000 chunk is a 0x34001 header (eSolidListHeader, the file's
// name) and then one container per solid. Each container holds:
//   0x34003  the eSolid, 16-aligned past a filler;
//   0x34004  its eStripEntry table, 16-aligned;
//   0x34005  the strips' VU1 packet, 16-aligned;
//   0x34006  its eTextureTable, unaligned;
//   0x3401d  its eLightMaterialEntry table, 16-aligned;
//   0x34007  its animation tree's nodes, 16-aligned;
//   0x34012  its eRigidAnimation, 16-aligned;
//   0x34011  that animation's labelled frames.
// The loader compares every child's type and leaves any other alone. The
// demo disc's 110 lists hold 1,465 solids, each in a 0x80034002 container
// with the eSolid first; 332 have light materials, 19 a rigid animation
// and 13 an animation tree. None has labelled frames, and none is vertex
// animated. The retail bundles' 352 lists hold 28,504, also each with the
// eSolid first; 1,782 have light materials, 105 a rigid animation and 13
// an animation tree. None has labelled frames, and 90 are vertex
// animated: the waving flag's 15 frames on each of TRACKB61..66.
//
// Where it depends on what is not ported, it goes through a seam:
// GetTextureInfo (TexturePack.obj), elGetLightMaterial (the light lists),
// FixStripSTs and CalcAutoK (the renderer's) and ReconnectAllAnimations
// (the animation loader). A seam left NULL does nothing, and one that
// returns a pointer returns NULL.

#ifndef ESOLID_H
#define ESOLID_H

#include <stddef.h>
#include <stdint.h>

#include "bslotpool.h"
#include "emodel.h"

// eSolidListHeader, 52 bytes: the 0x34001 payload.
typedef struct eSolidListHeader {
    char     Filename[48];                  //  0
    int32_t  InventoryHandle;               // 48
} eSolidListHeader;                         // 52

// eStripEntry, 64 bytes: one strip. The loader moves Data by where the
// packet lies; the rest is the renderer's, and geometry.c reads it from
// the file.
typedef struct eStripEntry {
    int32_t   TextureNumber;                //  0
    uint16_t  TextureWidthScale;            //  4
    uint16_t  TextureHeightScale;           //  6
    uint8_t  *Data;                         //  8
    uint16_t  DataQWordSize;                // 12
    uint16_t  Flags;                        // 14
    float     AABBMin[3];                   // 16
    uint8_t   PolyGroupNumber;              // 28
    uint8_t   NumVerts;                     // 29
    uint8_t   NumPolys;                     // 30
    int8_t    LightMaterialIndex;           // 31
    float     AABBMax[3];                   // 32
    uint32_t  pad;                          // 44
    int16_t   Nx, Ny, Nz, Nt;               // 48
    float     MaterialDensity;              // 56
    int16_t   MipMapK;                      // 60
    uint8_t   MipMapL;                      // 62
    uint8_t   Padding;                      // 63
} eStripEntry;                              // 64

// eTextureTable, 8 bytes: a texture's name and what GetTextureInfo found.
typedef struct eTextureTable {
    uint32_t  NameHash;                     //  0
    void     *pTextureInfo;                 //  4
} eTextureTable;                            //  8

// eLightMaterialEntry, 8 bytes.
typedef struct eLightMaterialEntry {
    uint32_t  NameHash;                     //  0
    void     *LightMaterial;                //  4
} eLightMaterialEntry;                      //  8

// eRigidAnimation, 112 bytes; the loader fills pLabelledFrames.
typedef struct eRigidAnimation {
    uint16_t  NumFrames;                    //  0
    uint8_t   TriggerableFlag;              //  2
    uint8_t   FrameRateScale;               //  3
    uint32_t  NameHash;                     //  4
    uint8_t  *pLabelledFrames;              //  8
    uint32_t  Padding;                      // 12
    char      Name[32];                     // 16
    uint8_t   Matricies[64];                // 48
} eRigidAnimation;                          // 112

// eVertexAnimator, 272 bytes: the solids that share a name and animate
// by swapping, one frame each.
#define EVERTEXANIMATOR_MAX_SOLIDS 64
typedef struct eVertexAnimator {
    bNode     Node;                         //   0
    int32_t   FrameRate;                    //   8
    int32_t   NumSolids;                    //  12
    eSolid   *SolidTable[EVERTEXANIMATOR_MAX_SOLIDS];  //  16
} eVertexAnimator;                          // 272

// An eAnimationTreeNode is 96 bytes. The port has no use for its fields.
#define EANIMATIONTREENODE_SIZE 96u

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char esolid_layout_check[
    (sizeof(eSolidListHeader) == 52 && sizeof(eStripEntry) == 64
     && offsetof(eStripEntry, Data) == 8
     && offsetof(eStripEntry, AABBMax) == 32
     && offsetof(eStripEntry, MipMapK) == 60
     && sizeof(eTextureTable) == 8 && sizeof(eLightMaterialEntry) == 8
     && sizeof(eRigidAnimation) == 112
     && offsetof(eRigidAnimation, pLabelledFrames) == 8
     && sizeof(eVertexAnimator) == 272
     && offsetof(eVertexAnimator, SolidTable) == 16) ? 1 : -1];
#endif

// eVertexAnimatorSlotPool, 0x00322778 (gp-25720): eInitSlotPools' third
// pool, 16 of 272 bytes.
extern BSlotPool *eVertexAnimatorSlotPool;

// The dirty flags, 0x00322840 .. 0x0032284c. The solid loaders set
// eDirtySolids, the texture packs eDirtyTextures, the animation loaders
// eDirtyAnimations; eFixUpTables clears them. eDisableFixUpTables is set
// while the game flow loads a track and cleared when it is done.
extern int32_t eDisableFixUpTables;
extern int32_t eDirtySolids;
extern int32_t eDirtyTextures;
extern int32_t eDirtyAnimations;

// The nine textures eFixUpTables looks up again every time, retail's
// gp-25144 .. gp-25112 (the demo's eight at 0x003227a8 .. 0x003227c4).
// pTextureInfoFalloffRamp is retail's alone, between SpecularFalloff and
// CarSelectEnvMap. The name is the port's: the hash, 0xb9ab56e4, is of a
// name no file on either disc holds, and the texture is made at run time,
// as SHADOWMAP1's is. The renderer reads it after SpecularFalloff.
extern void *pTextureInfoRVMInfo;
extern void *pTextureInfoRVMMask;
extern void *pTextureInfoSolidGrey;
extern void *pTextureInfoFilterGrey;
extern void *pTextureInfoShadowMap1;
extern void *pTextureInfoRadialBlur;
extern void *pTextureInfoSpecularFalloff;
extern void *pTextureInfoFalloffRamp;
extern void *pTextureInfoCarSelectEnvMap;

// The seams.
extern void *(*gGetTextureInfoFn)(uint32_t name_hash, int use_default,
                                  int include_unloaded);
extern void *(*gElGetLightMaterialFn)(uint32_t name_hash);
extern void (*gFixStripSTsFn)(eSolid *solid);
extern void (*gCalcAutoKFn)(eSolid *solid);
extern void (*gReconnectAllAnimationsFn)(void);

// GetTextureInfo(unsigned int, int, int), retail 0x001abf48, through its
// seam. Every call in this unit and eModel's passes 0 for the third.
void *get_texture_info(uint32_t name_hash, int use_default,
                       int include_unloaded);

// elGetLightMaterial(unsigned int), retail 0x00116a30, through its seam.
void *get_light_material(uint32_t name_hash);

// eInitSlotPools' third pool (0x00108a8c). Nothing happens when it is
// already made.
void esolid_init_slot_pool(void);

// eVertexAnimator's deleting destructor, _$_15eVertexAnimator
// (0x00114988): bNode's destructor, which does nothing, then with bit 0
// of `flags` the slot back to eVertexAnimatorSlotPool.
void evertexanimator_delete(eVertexAnimator *va, int32_t flags);

// eSolid::FixStripEntryTable(unsigned char *, int, unsigned char *),
// 0x001038d8: every strip's Data moved by data - base. The size is not
// read.
void esolid_fix_strip_entry_table(eSolid *s, uint8_t *data, int32_t size,
                                  uint8_t *base);

// eSolid::FixTextureTable, 0x0010aa90: every entry's pointer is
// GetTextureInfo of its name, with the default texture for a miss.
void esolid_fix_texture_table(eSolid *s);

// eSolid::FixLightMaterialTable, 0x0010b130: every entry's pointer is
// elGetLightMaterial of its name.
void esolid_fix_light_material_table(eSolid *s);

// LoaderSolidList(bChunk *), 0x00102ff0, and UnloaderSolidList,
// 0x001033b8. Each takes a 0x80034000 chunk and returns 1, and returns 0
// for any other.
int loader_solid_list(uint8_t *chunk);
int unloader_solid_list(uint8_t *chunk);

// eFixUpTables, retail 0x00103e68 (the demo's 0x00103790). Nothing while
// eDisableFixUpTables is set. With solids or textures dirty: with textures
// dirty, every solid's texture table, STs and mip K again; then every
// model's solid and replacement textures, the animations, the nine fixed
// textures and efix_falloff_ramp, and all three flags clear. With only
// animations dirty, the animations. The demo's looked up eight textures
// and made no ramp.
void efix_up_tables(void);

// Retail's 0x00103260, which only eFixUpTables calls; the name is the
// port's. Nothing without pTextureInfoFalloffRamp or its PaletteData.
// Otherwise each of its PaletteSize / 4 entries (the size shifted
// arithmetically) is a grey whose four bytes are all v, where for entry i
// of n
//     s = max(bSin(i / n * 1.57075 + 1.5707965), 0.01)
//     v = (int)(p(s) * 128) & 0xff
// and p is an inlined fast power, the bits of s read as an integer and
// back, to the power 1.0: s with its low six bits rounded. So the ramp
// runs from 128 down to 1. A loop of Width empty passes comes first and
// does nothing.
void efix_falloff_ramp(void);

#endif
