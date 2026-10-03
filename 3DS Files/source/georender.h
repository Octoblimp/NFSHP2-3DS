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
// geosolid.v.pica. The colour is what the VIF's V4-5 unpack gave VU1, each
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
// nothing.
typedef struct {
    int      first;             // first vertex in the buffer
    int      count;             // vertices, always a multiple of 3
    int      texture;           // index into the solid's texture table, or -1
    uint16_t flags;             // eStripEntry's: 0x80 lit, 0x100 env mapped
    int8_t   lightMaterial;     // the solid's LightMaterialTable index, or -1
} GeoBatch;

#define GEO_MAX_BATCHES 64

// How a strip's colour meets the frame's. The GS blends with its ALPHA_1
// register, which CreateTextureContext (0x00109f48) takes whole from
// TextureInfo's AlphaBits. Every texture on the disc that is not
// semitransparent has AlphaBits 0x0a, Cs, which is no blend at all, so
// the port blends only the semitransparent ones. The disc's textures use
// four equations, out of (A - B) * C + D with A, B and D from {Cs, Cd, 0}:
typedef enum {
    GEO_BLEND_NONE,             // not semitransparent, or AlphaBits 0x0a: Cs
    GEO_BLEND_ALPHA,            // 0x44, (Cs - Cd) * As + Cd
    GEO_BLEND_ADD,              // 0x48, Cs * As + Cd: bulbs, the sun
    GEO_BLEND_SUBTRACT,         // 0x42, Cd - Cs * As: the skid marks
} GeoBlend;

// A texture's fragment state, for georender_draw_mask. Zero is an opaque
// strip that writes depth and is alpha-tested, which is what a texture no
// pack holds gets.
//
// The two flags are the attach loops' mode (retail's 0x0010bb20 and
// 0x0010b838): bit 1 is bWriteZ, and bit 0 is IsAnySemitransparencyFlag
// or GlossMapInAlpha. The mode picks one of the render target's four
// register blocks, at 240 + 224 * mode, that UpdateGifTags (0x00104ec0)
// builds. The blocks differ only in ZBUF's mask and TEST_1: modes 0 and
// 2 test alpha GREATER than AREF 0x30, and 1 and 3 GEQUAL 0, which
// always passes. So a gloss map in alpha, which is mostly below 0x30 on
// a road's edge, is never a cut-out.
typedef struct {
    uint8_t blend;              // GeoBlend
    bool    noDepthWrite;       // TextureInfo's bWriteZ clear
    bool    noAlphaTest;        // semitransparent, or GlossMapInAlpha
} GeoPass;

// One entry of a solid's texture table, resolved. `uvScale` is the image's
// size over the allocation's, because texpack_upload() pads to a power of
// two and puts the image in the top-left -- so a 512x320 skin in a 512x512
// allocation needs (1.0, 0.625) here. It goes to the shader as a uniform per
// batch; see geosolid.v.pica.
typedef struct {
    C3D_Tex* tex;               // NULL when the hash resolved to nothing
    float    uvScale[2];
    GeoPass  pass;              // georender_draw_mask's; georender_draw's is fixed
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

// The batches whose bit is set in `mask`, bit i for batch i, each with its
// texture's pass rather than georender_draw's one state, and with the test
// the PS2's main render target gives every strip: TEST_1 as UpdateGifTags
// (0x00104ec0) builds it, depth GEQUAL, and alpha GREATER than 0x30 of the
// GS's 0x80 -- 0x60 here, where the packs' alpha is doubled on the way in.
// A batch with no texture draws opaque. The texture modulates the vertex
// colour as the GS's does, Ct * Cv >> 7, so 0x80 is 1.0 and the colour can
// double the texture; with no texture the colour is drawn as it is.
void georender_draw_mask(const GeoMesh* mesh, const GeoTexture* textures,
                         int numTextures, uint64_t mask);

// ---------------------------------------------------------- the lit strips

// One lit batch's inputs to geolit.v.pica, from the model's eLightContext
// and the strip's eLightMaterial, in the solid's own space. trackview.c's
// lighting_for fills it; see there for where each comes from.
typedef struct {
    float lightDir[3][4];       // to each of the three lights
    float difClr[3][4];         // each one's colour times the diffuse scale
    float specClr[3][4];        // and the specular; [0][3] the gloss range
    float ambient[4];           // and in [3] the alpha before the gloss
    float eye[4];
    float powParams[4];         // p, fast log2 of the maximum, 0.1, CBV/255
    float envCol[3][4];         // EnvMapMatrix's columns, x and z negated
    float fresnel[4];           // FresnelMid/128, FresnelHalf/128, 128/255
    bool  lit;                  // flags & 0x80: the lighter's colour
    bool  env;                  // flags & 0x100: and the environment pass
    bool  gloss;                // flags & 4: the texture's alpha is a gloss map
} GeoLighting;

// Batch `b` of `mesh` with its texture's pass, as georender_draw_mask draws
// it, but with the colour the lighter makes when `L->lit`, and then, when
// `L->env` and there is an environment map, the strip again with the map:
// added under the fresnel's alpha, or for a gloss map under the frame's,
// which the first pass left there.
void georender_draw_lit(const GeoMesh* mesh, const GeoTexture* textures,
                        int numTextures, int b, const GeoLighting* L);

// --------------------------------------------------- the environment map

// The map the environment passes read. Retail's eEnvMap draws six views
// round the car into render targets 8 to 13 and eCreateEnvMapPrims
// (0x00118810) folds them into a sphere map, which the VU1 reads by the
// reflection. The PICA reads a cube map by the reflection itself, so here
// the six views draw straight into a cube's faces, `size` on a side, in the
// space the environment pass turns the reflection into; see eenvmap.h.
bool georender_envmap_init(int size);

// Face `face` of the map, +X to -Z as GPU_TEXFACE counts them, cleared to
// `clear` (red in the top byte) and its depth to the far plane's, and with
// `draw` bound to be drawn on, with a 90 degree projection. Call it between
// C3D_FrameBegin and the top screen's C3D_FrameDrawOn.
void georender_envmap_face(int face, uint32_t clear, bool draw);

// Whether face `face` has been cleared or drawn, and whether all six have,
// which the environment passes wait for.
bool georender_envmap_face_done(int face);
bool georender_envmap_ready(void);

// eSetZWriteState(int), 0x001029c0: with it off, nothing drawn writes the
// depth buffer, whatever its texture's pass says. eDisplayFrame turns it
// off for the sky. It starts on.
void georender_set_zwrite(bool on);

// The fog the draws after it take: the PICA's, by `lut` and in `colour`
// (red in the low byte), or none for a NULL `lut`. The blends that add to
// the frame or take from it fog to black instead; see set_blend. The LUT
// is uploaded when it is bound, so one that changes is bound again.
void georender_set_fog(C3D_FogLut* lut, uint32_t colour);

// ------------------------------------------------------- the screen quads

// How many screen quads a frame can draw. The sun and its glare are 12.
#define GEO_QUAD_RING 64

// One quad in the top screen's pixels, x right to 400 and y down to 240,
// drawn as a strip in the order given -- ePoly::Render's, for
// trackview.c's render_epoly. The texture modulates the vertex colour on
// the GS's scale, where 0x80 is 1.0; `blend` is a GeoBlend; the alpha test
// is the main target's. With `depthTest` the quad draws where its depth,
// which the caller's depth map gives, is GEQUAL to the buffer's; without,
// everywhere. It never writes the depth. The vertices go into a ring on
// the linear heap, which georender_quads_rewind starts again once the GPU
// is done with the last frame. False when the ring is full or there is no
// texture.
bool georender_draw_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                         uint8_t blend, bool depthTest);
void georender_quads_rewind(void);

#endif
