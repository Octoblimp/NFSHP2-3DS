#ifndef NFSHP2_GEOBAKE_H
#define NFSHP2_GEOBAKE_H

// eSolid geometry baked for the PICA200: what geometry.c decodes, made
// into one indexed mesh a solid, and an editable mesh made to match its
// solid again after CarDamage's walk (estripdata.h). georender.c draws
// the meshes; this half is plain C, with no citro3d, so the host can run
// it (tools/geobake_check.py). The mesh's block is on the linear heap on
// the 3DS and the C heap on the host.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "geocull.h"
#include "geometry.h"

// One vertex as the PICA reads it. 28 bytes.
//
// The field order IS the attribute layout: the PICA walks one vertex by
// consuming the AttrInfo_AddLoader() calls in the order they were made, so
// the struct has to be in that order too and there is nothing that checks
// it. Three floats of position, two of ST, four unsigned bytes of colour,
// three signed bytes of normal, and a pad byte to round the stride to 28.
// The loader takes the normal and the pad as four bytes: the PICA freezes
// when a loader's attributes do not fill its stride.
//
// Both byte fields reach the shader as the plain integer value, 0..255 and
// -128..127 -- the PICA does not normalise an integer attribute -- so the
// colour is scaled by 1/255 and the normal by 1/127, in the uniforms the
// CPU makes for geosolid.v.pica (geosolidunif.c). The colour is what the VIF's V4-5 unpack gave VU1, each
// five bits shifted up three, so 0..248, and the alpha 255 or 0 for the
// unpack's 0x80 or 0.
typedef struct {
    float   pos[3];
    float   st[2];
    uint8_t colour[4];
    int8_t  normal[3];
    uint8_t pad;
} GeoRenderVertex;

// A run of triangles sharing one texture, one eStripEntry Flags and one
// LightMaterialIndex. Strips are sorted by the three when a solid is baked,
// so a solid draws in as many calls as it has distinct ones -- 1 to 34
// across the disc, usually fewer than 12. Within a solid the flags and the
// material never differ between strips of one texture, so the split costs
// nothing. The flags are the bake's, less 0x400 (estripdata.h's
// ESTRIP_HIDDEN), which says whether a strip draws at all and not how:
// eSolid::SetEnvironmentMapping changes 0x100 on every strip of a texture
// afterwards (CarDamage, when a window breaks), so the draw reads
// `strip`'s as they are now (geometry.h's geo_strip_flags).
typedef struct {
    int      first;             // first index in the mesh's ibo
    int      count;             // indices, three a triangle
    int      texture;           // index into the solid's texture table, or -1
    int      strip;             // its first strip in the solid's entry table
    uint16_t flags;             // eStripEntry's: 0x80 lit, 0x100 env mapped
    int8_t   lightMaterial;     // the solid's LightMaterialTable index, or -1
    int      cluster;           // its boxes in the mesh's clusters (geocull.h)
} GeoBatch;

#define GEO_MAX_BATCHES 64

// Where an editable mesh's strips went (georender_bake_editable).
typedef struct GeoMeshEdit GeoMeshEdit;

typedef struct {
    GeoRenderVertex* vbo;               // linearAlloc'd; georender_free owns it
    uint16_t*        ibo;               // in vbo's block, after the vertices
    int              numVerts;
    int              numIndices;
    GeoBatch         batch[GEO_MAX_BATCHES];
    int              numBatches;
    int              numTris;
    int              skippedStrips;     // strips geometry.c could not decode
    float            aabbMin[3];
    float            aabbMax[3];
    // Each batch's boxes, geocull_count(count) from its `cluster`, in vbo's
    // block after the indices; NULL draws every batch whole.
    const GeoCluster* clusters;
    GeoMeshEdit*      edit;             // malloc'd; NULL but for an editable one
} GeoMesh;

// Decodes every strip of `solid` into one indexed mesh on the linear heap:
// each distinct vertex once, 28 bytes, then three 16-bit indices a
// triangle, then the batches' boxes (geocull.h). This is the expensive call -- it replays every VIF packet in
// the solid -- so it belongs at load time, not in a frame.
//
// The disc's largest solid, 911TURBO_A (4,138 triangles), is 4,255
// vertices and 141 KB, where a triangle list took 348 KB.
//
// Returns false only if the allocation fails; a solid whose strips will not
// decode still bakes, with the bad ones counted in skippedStrips. A strip
// whose Flags hold ESTRIP_HIDDEN is left out, as RenderStrips skips it.
bool georender_bake(const GeoSolid* solid, GeoMesh* out);

// The same, for a solid the game changes after the bake: CarDamage's walk
// (estripdata.h) dents its vertices, steps their colours, and shows or
// hides its scuff strips (ESTRIP_SCUFFS) by ESTRIP_HIDDEN. The mesh keeps
// which of its vertices each strip vertex became, and each scuff strip's
// indices, and a scuff strip hidden now is baked as triangles of one
// vertex each, which draw nothing.
bool georender_bake_editable(const GeoSolid* solid, GeoMesh* out);

// An editable mesh made to match its solid again: each strip vertex's
// position and colour read back out of the packet, each scuff strip drawn
// or emptied by its Flags as they are now, and the batches' boxes made
// again. Call it while the GPU is not drawing from the mesh: after
// C3D_FrameBegin, which waits for the last frame, and before C3D_FrameEnd,
// whose flush of the linear heap takes the change to the GPU. False for a
// mesh that is not editable.
bool georender_refresh(const GeoSolid* solid, GeoMesh* mesh);

void georender_free(GeoMesh* mesh);

#endif
