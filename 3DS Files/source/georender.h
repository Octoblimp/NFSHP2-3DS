#ifndef NFSHP2_GEORENDER_H
#define NFSHP2_GEORENDER_H

// eSolid geometry on the PICA200: takes what geometry.c decodes and draws it
// with citro3d.
//
// geometry.c is the format half and knows nothing about the 3DS; this is the
// hardware half and knows nothing about VIF. The seam between them is
// GeoStrip, a plain triangle list with position, ST, colour and normal.
//
// What the PS2 did and what happens here are the same operations in the same
// order, just on different silicon. VU1 transformed and lit a strip and
// kicked it to the GS; here the vertex shader in geosolid.v.pica transforms
// and lights, and the PICA200 rasterises. The one thing the GS did that the
// PICA does not is nothing at all -- the GS has no hardware backface culling
// and the VU did it in software, so the cull mode here is a decision this
// module makes rather than one the data carries. See georender_bake.

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include <citro3d.h>

#include "geometry.h"

// One vertex as the PICA reads it. 28 bytes.
//
// The field order IS the attribute layout: the PICA walks one vertex by
// consuming the AttrInfo_AddLoader() calls in the order they were made, so
// the struct has to be in that order too and there is nothing that checks
// it. Three floats of position, two of ST, four unsigned bytes of colour,
// three signed bytes of normal, and a pad byte to round the stride to 28.
//
// Both byte fields reach the shader as the plain integer value, 0..255 and
// -128..127 -- the PICA does not normalise an integer attribute -- so the
// shader scales the colour by 1/255 and the normal by 1/127. See
// geosolid.v.pica.
typedef struct {
    float   pos[3];
    float   st[2];
    uint8_t colour[4];
    int8_t  normal[3];
    uint8_t pad;
} GeoRenderVertex;

// A run of triangles sharing one texture. Strips are sorted by TextureNumber
// when a solid is baked, so a solid draws in as many calls as it has distinct
// textures -- 1 to 28 across the disc, usually fewer than 12.
typedef struct {
    int first;                  // first vertex in the buffer
    int count;                  // vertices, always a multiple of 3
    int texture;                // index into the solid's texture table, or -1
} GeoBatch;

#define GEO_MAX_BATCHES 32

// One entry of a solid's texture table, resolved. `uvScale` is the image's
// size over the allocation's, because texpack_upload() pads to a power of
// two and puts the image in the top-left -- so a 512x320 skin in a 512x512
// allocation needs (1.0, 0.625) here. It goes to the shader as a uniform per
// batch; see geosolid.v.pica.
typedef struct {
    C3D_Tex* tex;               // NULL when the hash resolved to nothing
    float    uvScale[2];
} GeoTexture;

typedef struct {
    GeoRenderVertex* vbo;               // linearAlloc'd; georender_free owns it
    int              numVerts;
    GeoBatch         batch[GEO_MAX_BATCHES];
    int              numBatches;
    int              numTris;
    int              skippedStrips;     // strips geometry.c could not decode
    float            aabbMin[3];
    float            aabbMax[3];
} GeoMesh;

// Loads the shader and describes the vertex layout. Call once, after
// C3D_Init. Safe to call again; the second call is a no-op.
bool georender_init(void);
void georender_exit(void);

// Decodes every strip of `solid` into one triangle-list vertex buffer on the
// linear heap. This is the expensive call -- it replays every VIF packet in
// the solid -- so it belongs at load time, not in a frame.
//
// Memory is 28 bytes per vertex and three vertices per triangle, so the
// disc's largest solid (911TURBO_A, 4,139 triangles) takes 348 KB. Nothing
// is shared between strips in the source data, so an indexed draw would save
// nothing here.
//
// Returns false only if the allocation fails; a solid whose strips will not
// decode still bakes, with the bad ones counted in skippedStrips.
bool georender_bake(const GeoSolid* solid, GeoMesh* out);
void georender_free(GeoMesh* mesh);

// Both matrices, because the shader lights in view space and so needs the
// view-space position as well as the clip-space one.
void georender_set_camera(const C3D_Mtx* projection, const C3D_Mtx* modelView);

// Direction *towards* the light, in view space, and the two colours. The
// direction is normalised here so a caller can pass whatever it has.
void georender_set_light(float x, float y, float z,
                         float r, float g, float b,
                         float ambient);

// `textures` is the solid's texture table already resolved, one entry per
// eTextureTable entry, with a NULL `tex` for any hash that could not be
// found -- which is not an unusual case: 13 of the 142 hashes the car
// geometry refers to are in no pack on the disc. A batch whose texture is
// -1, out of range, or NULL draws with vertex colour alone rather than being
// skipped.
void georender_draw(const GeoMesh* mesh, const GeoTexture* textures,
                    int numTextures);

#endif
