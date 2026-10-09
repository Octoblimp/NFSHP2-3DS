// elight -- the database half of eLight.obj (0x00114f38 .. 0x00117460):
// the loader and unloader of the light packs, light flares and light
// materials (LoaderTable slot 5), the query that finds the lights near a
// point, and elSetupLightContext, which turns them into the eLightContext
// the VU1 lighter reads for each model it draws. Also vAABBTree's leaf
// query (0x001b9cd0 .. 0x001ba0a0), which nothing else in the port uses
// yet.
//
// A track's bundle holds one light pack (0x80034015): a header, an AABB
// tree over the lights, and the lights, 96 bytes each. Every leaf of the
// tree lists the lights whose spheres reach into it. The track's flares
// (0x80034019) are a second list, drawn by eRenderWorldLightFlares
// (elightflare.h). GLOBALB.BUN starts with the light materials (0x3401e):
// 49 of them, 320 bytes each, one per kind of surface -- car paint, glass,
// chrome, rubber -- with two sets of numbers, one for the frontend and one
// in game.
//
// Written up with addresses in docs/formats/light.md.

#ifndef ELIGHT_H
#define ELIGHT_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"
#include "bmatrix.h"
#include "bvector.h"
#include "eviewmatrix.h"

// eLight, 96 bytes (.mdebug type#4497).
typedef struct eLight {
    char     Name[32];                  //  0
    uint32_t NameHash;                  // 32
    uint8_t  Type;                      // 36  0 ambient, 2 point
    uint8_t  AttenuationType;           // 37
    uint8_t  Shape;                     // 38
    uint8_t  State;                     // 39
    uint32_t ExcludeNameHash;           // 40
    uint32_t Colour;                    // 44  R, G, B bytes from the bottom
    float    PositionX;                 // 48
    float    PositionY;                 // 52
    float    PositionZ;                 // 56
    float    Size;                      // 60  the radius it reaches
    float    DirectionX;                // 64
    float    DirectionY;                // 68
    float    DirectionZ;                // 72
    float    Intensity;                 // 76
    float    FarStart;                  // 80  full strength inside this
    float    FarEnd;                    // 84
    float    Falloff;                   // 88
    uint32_t pad;                       // 92
} eLight;

// vAABB, 48 bytes (type#2613). A parent's NumChildren is the count of
// ChildrenIndicies, which index the tree's NodeArray; a leaf's is minus
// the count, and its indices are into the pack's LightArray.
typedef struct vAABB {
    float    PositionX;                 //  0  the centre
    float    PositionY;                 //  4
    float    PositionZ;                 //  8
    int16_t  ParentIndex;               // 12
    int16_t  NumChildren;               // 14
    float    ExtentX;                   // 16  half the size
    float    ExtentY;                   // 20
    float    ExtentZ;                   // 24
    int16_t  ChildrenIndicies[10];      // 28
} vAABB;

// vAABBTree, 16 bytes (type#2328); the nodes follow it in the chunk.
typedef struct vAABBTree {
    vAABB   *NodeArray;                 //  0
    int16_t  NumLeafNodes;              //  4
    int16_t  NumParentNodes;            //  6
    int16_t  TotalNodes;                //  8
    int16_t  Depth;                     // 10
    uint32_t pad1;                      // 12
} vAABBTree;

// eLightPack, 28 bytes (type#4522): the 0x34016 child, which the loader
// fills in from the other two.
typedef struct eLightPack {
    bNode      Node;                    //  0
    uint32_t   Version;                 //  8  1
    vAABBTree *LightTree;               // 12
    uint32_t   NumTreeNodes;            // 16
    eLight    *LightArray;              // 20
    uint32_t   NumLights;               // 24
} eLightPack;

// eLightFlarePackHeader, 64 bytes (type#4560).
typedef struct eLightFlarePackHeader {
    bNode    Node;                      //  0
    uint32_t Version;                   //  8  1
    uint32_t NameHash;                  // 12
    char     Name[32];                  // 16
    uint32_t NumLightFlares;            // 48
    uint32_t pad;                       // 52
    bNode    LightFlareList;            // 56
} eLightFlarePackHeader;

// eLightFlare, 80 bytes (type#4543).
typedef struct eLightFlare {
    bNode    Node;                      //  0
    uint32_t NameHash;                  //  8
    int8_t   Enabled;                   // 12
    int8_t   Type;                      // 13
    uint16_t Flags;                     // 14
    char     Name[32];                  // 16
    float    PositionX;                 // 48
    float    PositionY;                 // 52
    float    PositionZ;                 // 56
    uint32_t pad0;                      // 60
    float    DirectionX;                // 64
    float    DirectionY;                // 68
    float    DirectionZ;                // 72
    uint32_t pad1;                      // 76
} eLightFlare;

// eLightMaterialData, 80 bytes (type#4591).
typedef struct eLightMaterialData {
    float SpecularPower;                //  0
    float SpecularMax;                  //  4
    float SpecularPowerScale;           //  8
    float SpecularMaxScale;             // 12
    float DiffuseColourScaleR;          // 16
    float DiffuseColourScaleG;          // 20
    float DiffuseColourScaleB;          // 24
    float FresnelMin;                   // 28
    float SpecularColourScaleR;         // 32
    float SpecularColourScaleG;         // 36
    float SpecularColourScaleB;         // 40
    float FresnelMax;                   // 44
    float GlossMapPower;                // 48
    float GlossMapMax;                  // 52
    float GlossMapPowerScale;           // 56
    float GlossMapMaxScale;             // 60
    float GlossMapAlphaMin;             // 64
    float GlossMapAlphaMax;             // 68
    float CBVMix;                       // 72
    uint32_t pad2;                      // 76
} eLightMaterialData;

// The sixteen words BuildDmaData makes from an eLightMaterialData, which
// the renderer sends to VU1 with each strip that uses the material. The
// powers are for the VU1's fast pow: m * x^p is the float whose bits are
// p * bits(x) + Bias.
typedef struct eLightMaterialDma {
    float SpecularPower;                //  0  SpecularPower * Scale
    float SpecularBias;                 //  4  bits(max) - p * 0x3f800000
    float SpecularMinDot;               //  8  0.1
    float CBVMix;                       // 12  CBVMix / 255
    float DiffuseR, DiffuseG, DiffuseB; // 16
    float FresnelMid;                   // 28  (Min + (Max - Min) / 2) * 128
    float SpecularR, SpecularG, SpecularB;  // 32
    float FresnelHalf;                  // 44  (Max - Min) / 2 * -128
    float GlossPower;                   // 48
    float GlossBias;                    // 52
    float GlossAlphaMin;                // 56
    float GlossAlphaRange;              // 60  Max - Min
} eLightMaterialDma;

// eLightMaterial, 320 bytes (type#4326).
typedef struct eLightMaterial {
    bNode              Node;            //   0
    uint32_t           NameHash;        //   8
    char               Name[20];        //  12
    eLightMaterialData feData;          //  32
    eLightMaterialData igData;          // 112
    eLightMaterialDma  feDmaData;       // 192
    eLightMaterialDma  igDmaData;       // 256
} eLightMaterial;

// eLightQuery, 96 bytes (type#2692).
#define ELIGHTQUERY_MAX_LIGHTS 10
typedef struct eLightQuery {
    eLight *Lights[ELIGHTQUERY_MAX_LIGHTS];         //  0
    float   Influences[ELIGHTQUERY_MAX_LIGHTS];     // 40
    float   AmbientR;                               // 80
    float   AmbientG;                               // 84
    float   AmbientB;                               // 88
    float   LightScale;                             // 92
} eLightQuery;

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char elight_layout_check[
    (sizeof(eLight) == 96 && offsetof(eLight, Colour) == 44
     && offsetof(eLight, FarStart) == 80
     && sizeof(vAABB) == 48 && offsetof(vAABB, ChildrenIndicies) == 28
     && sizeof(vAABBTree) == 16 && sizeof(eLightPack) == 28
     && sizeof(eLightFlarePackHeader) == 64
     && offsetof(eLightFlarePackHeader, LightFlareList) == 56
     && sizeof(eLightFlare) == 80
     && sizeof(eLightMaterialData) == 80 && sizeof(eLightMaterialDma) == 64
     && sizeof(eLightMaterial) == 320
     && offsetof(eLightMaterial, igData) == 112
     && offsetof(eLightMaterial, igDmaData) == 256
     && sizeof(eLightQuery) == 96
     && offsetof(eLightQuery, AmbientR) == 80) ? 1 : -1];
#endif

// The three lists, gp-24272, gp-24264 and gp-24256, empty until a bundle
// is loaded; and the default material, gp-24248, which points at a zeroed
// static (0x002d5a00) until GLOBALB's "Default" (hash 0x2c420d64) loads.
extern bNode eLightFlarePackList;
extern bNode eLightPackList;
extern bNode eLightMaterialList;
extern eLightMaterial *eDefaultLightMaterial;

// SunDir (0x002d5bf0), SunColour (0x002d5c00) and the ambient override
// (0x002d5be0), from the static initializer _GLOBAL_$I$LightTypeStrings
// (0x00117098): (-0.74, 0, 0.55), (80, 80, 80) and (0, 0, 0).
extern bVector4 elSunDir;
extern bVector4 elSunColour;
extern bVector4 elAmbientOverride;

// main.c points gElSetupLightContextFn and gElGetLightMaterialFn here.

// elInit (0x00116a70), the part of it the port has: the default material
// zeroed. The rest fills two static light contexts nothing ported reads.
void el_init(void);

// LoaderLightList (0x00114f38) and UnloaderLightList (0x001151e0),
// LoaderTable slot 5: 0x80034015, 0x80034019, 0x3401c and 0x3401e.
int loader_light_list(uint8_t *chunk);
int unloader_light_list(uint8_t *chunk);

// eLightMaterial::BuildDmaData (0x00116828 for one set, 0x001169f8 for
// both).
void el_build_dma_data(eLightMaterialDma *out, const eLightMaterialData *d);
void el_build_material_dma_data(eLightMaterial *m);

// elGetLightMaterial (0x00116a30): the loaded material with this hash, or
// the default. elGetDefaultLightMaterial (0x00116a68).
eLightMaterial *el_get_light_material(uint32_t name_hash);
eLightMaterial *el_get_default_light_material(void);

// vAABB::Contains (0x001b9cd0): strictly inside the box.
int vaabb_contains(const vAABB *b, float x, float y, float z);

// vAABBTree::QueryLeaf (0x001b9fd8) and QueryLeafHelper (0x001b9ed8): the
// first leaf, depth first, whose box holds the point, or NULL.
vAABB *vaabbtree_query_leaf(const vAABBTree *t, float x, float y, float z);

// QueryLightDatabase (0x00115370). Up to ten point lights whose spheres
// hold pos go into q->Lights with their influences, and the number found is
// returned. The ambient lights that hold it set q's ambient colour and
// LightScale.
int query_light_database(eLightQuery *q, const bVector3 *pos);

// elSetupLightContext (0x00115978), what eviewmatrix.h's
// gElSetupLightContextFn points at. -1 without lc or local_world, else 1.
// In the frontend the lights are the frontend's: with car select up,
// `view`'s set of elSelectCarLights, turned out of the view's space by its
// WorldViewMatrix; otherwise elFrontEndLightDir and elFrontEndLightColour.
// Either way the sunlight intensity is 1.
int el_setup_light_context(eLightContext *lc, const bMatrix4 *local_world,
                           const bMatrix4 *hack, const bVector4 *eye,
                           eView *view);

// CurrentGameFlowState == 3 (IN_FRONTEND), which takes the frontend's
// lights instead of the world's. NULL, or a zero return, takes the
// world's.
extern int (*gElInFrontendFn)(void);

// IsCarSelectScreenActive (0x00198418), which picks the car-select
// screen's lights out of the frontend's. NULL answers 0.
extern int (*gElCarSelectActiveFn)(void);

// The car-select screen's lights: three directions in the view's space,
// their colours, and the ambient. Colours run 0 .. 255, where 128 is 1.0
// on the GS's scale. SetSelectCarLighting fills them.
typedef struct eSelectCarLights {
    struct {
        bVector4 Colour;                //  0 + 32i
        bVector4 Direction;             // 16 + 32i
    } Light[3];
    bVector4 Ambient;                   // 96
    bVector4 pad;                       // 112  never written
} eSelectCarLights;

// [0] at 0x002d5f70, for every view but 2; [1] at 0x002d5ff0, for view 2,
// the second player's. Zero until SetSelectCarLighting runs.
extern eSelectCarLights elSelectCarLights[2];

// The frontend's lights away from car select, from the static initializer:
// directions (0, -5, 5), (4.3, 2.5, 2.5) and (-4.3, 2.5, 2.5) (0x002d5b70)
// and colours 128, 64 and 64 with no ambient (0x002d5ba0). Unlike the car
// select's, the directions are in the world's space.
extern bVector4 elFrontEndLightDir[3];
extern bVector4 elFrontEndLightColour[4];

// SetSelectCarLighting (0x001157c0): view 2's set when `view_id` is 2,
// else the other. A `locked` car, one whose status is 2, gets the dark
// set, whose colours and ambient are all black. Otherwise the three lights' colours are
// 80, 64 and (128, 128, 180), each lane plus `bright` * 30 and at most
// 255, with an ambient of 32. Retail fills the colours' w lanes from its
// stack; elSetupLightContext never reads them, and the port writes 0.
void el_set_select_car_lighting(int32_t view_id, int32_t locked,
                                float bright);

#endif
