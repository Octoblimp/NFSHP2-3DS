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

#include "geobake.h"
#include "geocull.h"
#include "geometry.h"

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
    GEO_BLEND_SUBTRACT,         // 0x42, Cd - Cs * As
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

// Loads the shader and describes the vertex layout. Call once, after
// C3D_Init. Safe to call again; the second call is a no-op.
bool georender_init(void);
void georender_exit(void);

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

// A run of georender_draw_mask and georender_draw_lit calls with nothing
// else drawn between them (step 13b-4): the models eModel::Render draws as
// the cull hands them over. In a run georender sends only what changed
// since its last draw. The program, the attributes and the uniforms that
// change with the camera, the light and the fog go once; the cull mode
// once; the model-view when it changes; a mesh's vertex buffer as the one
// register of where it starts; the pass when the next batch's differs;
// the combiner and the ST scale when they differ; and the texture when it
// is another. The screen quads, the strips, the lit batches and the
// envmap's fold set their own state, and the run's next draw sends its
// whole state after them. Outside a
// run every draw sends its whole state, as before. A batch draws the same
// either way. A lit batch, or georender_set_light, _set_fog,
// _set_depth_range or _set_zwrite, makes the run forget what it sent.
void georender_run_begin(void);
void georender_run_end(void);

// The run forgets what it sent, so its next draw sends its whole state:
// for hangwatch's timing frame, which marks citro3d's whole state changed
// after each list it times (hangwatch.h).
void georender_forget(void);

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
// `L->env` and the sphere map has been folded, the strip again with the
// map: added under the fresnel's alpha, or for a gloss map under the
// frame's, which the first pass left there.
void georender_draw_lit(const GeoMesh* mesh, const GeoTexture* textures,
                        int numTextures, int b, const GeoLighting* L);

// --------------------------------------------------- the environment map

// The map the environment passes read. Retail's eEnvMap draws six views
// round the car into render targets 8 to 13, and eCreateEnvMapPrims
// (0x00118810) folds them into a sphere map on target 14, which the VU1
// reads by the reflection. Here the six views draw into a cube's faces,
// `size` on a side, in the space the environment pass turns the reflection
// into (see eenvmap.h), and the fold reads the cube by direction instead of
// each view's target by its u and v. The sphere map is 16 bits a texel,
// 5551, as retail's PSMCT16 targets are, and `mapSize` on a side; the
// cube is RGBA8, as wide as its faces' D24S8 depth (see georender.c).
//
// `fold` is the fold's triangles, GEO_FOLD_GRID_VERTS a grid, in the order
// of the sample table's ten grids (eenvmap.h): each vertex where it lands
// on the map, in clip space, and the direction the cube is read at.
#define GEO_FOLD_GRIDS      10
#define GEO_FOLD_GRID_VERTS 150

typedef struct {
    float pos[2];
    float dir[3];
} GeoFoldVertex;

bool georender_envmap_init(int size, int mapSize, const GeoFoldVertex* fold);

// Face `face` of the cube, +X to -Z as GPU_TEXFACE counts them, cleared to
// `clear` (red in the top byte, as RGBA8) and its
// depth to the far plane's, and with `draw` bound to be drawn on, with a
// 90 degree projection. Call it between C3D_FrameBegin and the top
// screen's C3D_FrameDrawOn.
void georender_envmap_face(int face, uint32_t clear, bool draw);

// Whether face `face` has been cleared or drawn.
bool georender_envmap_face_done(int face);

// eCreateEnvMapPrims: the grids of the views in `views` (bit i for view
// i, as eEnvMap counts them) folded into the sphere map. CreateEnvMap
// (0x00118150) draws each view's grid but face 2's, and CreateBackEnvMap
// (0x00118498) face 2's four back grids. Each strip is RGBAQ (96, 96, 96,
// 64) under the target's texel, modulated, and ALPHA_1 0x44 blends it over
// what the map held: half the view's texel at 0.75, and half the map. The
// map is cleared once, when it is first folded, and never again; retail
// never clears target 14. Call it after the faces and before the top
// screen's C3D_FrameDrawOn.
void georender_envmap_fold(unsigned views);

// Whether the sphere map has been folded, which the environment passes
// wait for.
bool georender_envmap_ready(void);

// A sphere map the environment passes bind in place of the folded one,
// and which they need not wait for; NULL gives the folded one back. The
// frontend's elSetupLightContext points the cars' lighting at
// CARSELECTENVMAP instead of target 14.
void georender_set_env_texture(const C3D_Tex* tex);

// The rear-view mirror's target, retail's target 7: a texture `width` by
// `height` in VRAM, RGBA8 as target 7's PSMCT32 is, with a depth buffer
// of its own. False when there is no room; true again for the same size.
bool georender_mirror_init(int width, int height);

// The mirror's target cleared to `clear` (red in the top byte, as RGBA8)
// and its depth to the far plane's, and bound to be drawn on. Call it
// between C3D_FrameBegin and the top screen's C3D_FrameDrawOn. False when
// there is no target.
bool georender_mirror_begin(uint32_t clear);

// The mirror's texture, for the top screen to draw; NULL until the mirror
// has drawn into it.
const C3D_Tex* georender_mirror_texture(void);

// A quad in the mirror target's pixels, x right to its width and y down to
// its height, as georender_draw_quad draws one on the top screen, but with
// no depth test and no alpha test. With `sourceAlpha` the target's alpha
// takes the quad's, as the GS writes a fragment's alpha under any ALPHA_1;
// the colour blends by `blend` either way.
bool georender_draw_mirror_quad(const GeoRenderVertex v[4],
                                const GeoTexture* gt, uint8_t blend,
                                bool sourceAlpha);

// eSetZWriteState(int), 0x001029c0: with it off, nothing drawn writes the
// depth buffer, whatever its texture's pass says. eDisplayFrame turns it
// off for the sky. It starts on.
void georender_set_zwrite(bool on);

// ------------------------------------------------------------------ the fog

// The fog's fraction of the colour kept, by the view's depth u = (far - d)
// / (far - near), 0 at the far plane and 1 at the near: GEO_FOG_STEPS
// steps, the fraction at each step's start and the last's end, and
// straight between, as the PICA's own fog lookup has it. It is a texture
// of GEO_FOG_TEX_W by 8, A8, which texture unit 1 reads at an s each
// vertex hands over, so the fog does not ride on the depth buffer. The
// PICA's fog reads the depth the buffer is given, and its W-buffer, which
// that wants, is too coarse for a plate on a car's body.
#define GEO_FOG_STEPS 128
#define GEO_FOG_TEX_W 256

typedef struct {
    C3D_Tex tex;
    // The fractions the texture was last filled with, once `filled`.
    bool    filled;
    float   keep[GEO_FOG_STEPS + 1];
} GeoFog;

// Fills `fog` with `keep`, its texture made the first time and kept for
// good. Fractions the same to the bit as the last fill's leave it as it
// is. Call it after C3D_FrameBegin, which waits for the GPU to be done
// with the last frame, and before the draws that take it. False when there
// is no memory.
bool georender_fog_fill(GeoFog* fog, const float keep[GEO_FOG_STEPS + 1]);

// The view's near and far planes, from which the draws find u.
void georender_set_depth_range(float near, float far);

// The fog the draws after it take: `fog` in `colour` (red in the low byte),
// or none for NULL. The blends that add to the frame or take from it fog
// to black instead; see set_blend.
void georender_set_fog(const GeoFog* fog, uint32_t colour);

// ------------------------------------------------------- the screen quads

// How many screen quads a frame can draw. The sun and its glare are 12,
// the tach a few, and the minimap up to trackview.h's
// TRACKVIEW_FLAILER_POLYS.
#define GEO_QUAD_RING 192

// One quad in the top screen's pixels, x right to 400 and y down to 240,
// drawn as a strip in the order given -- ePoly::Render's, for
// trackview.c's render_epoly. The texture modulates the vertex colour on
// the GS's scale, where 0x80 is 1.0; `blend` is a GeoBlend; the alpha test
// is the register block's that the texture's mode picks: GREATER 0x60
// unless `gt`'s pass has none, as a semitransparent texture's (the sun's)
// does. With a `depth` of 0 or more, the Z-buffer's, the
// quad draws where that is GEQUAL to the buffer's; with -1, everywhere.
// It never writes the depth. The vertices go into a ring on
// the linear heap, which georender_quads_rewind starts again once the GPU
// is done with the last frame, and which C3D_FrameEnd(0) flushes with the
// rest of the heap. False when the ring is full or there is no texture.
bool georender_draw_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                         uint8_t blend, float depth);
// The same for a Flailer poly over the HUD, on a screen `width` by
// `height`, citro2d's mapping: blended as citro2d blends, with neither
// the alpha test nor the depth test, as the rest of the HUD draws. The
// caller flushes citro2d first and runs C2D_Prepare after.
bool georender_draw_hud_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                             float width, float height);
// The same with a w for each vertex, for the GS's STQ: each `pos` is
// (x w, y w, w) for the screen's (x, y), and the ST interpolates over the
// quad as the GS's S / Q and T / Q do, with w = 1 / Q. `blend` is a
// GeoBlend and `alphaTest` the main target's test, both the poly's
// texture's.
bool georender_draw_hud_quad_w(const GeoRenderVertex v[4],
                               const GeoTexture* gt, uint8_t blend,
                               bool alphaTest, float width, float height);
void georender_quads_rewind(void);

// ------------------------------------------------------------- the strips

// How many strip vertices a frame can draw, in a ring of their own that
// georender_quads_rewind starts again with the quads'.
#define GEO_STRIP_RING 8192

// A strip eBeginStrip (retail 0x00110488) built: `n` vertices in a
// model's space, drawn as a triangle strip with the camera
// georender_set_camera last gave. The colour, alpha too, is the GS's,
// where 0x80 is 1.0, and the texture modulates it; the pass is the
// texture's, with the main target's tests, as georender_draw_mask draws
// a batch. False when the ring is full, or for no texture.
bool georender_draw_strip(const GeoRenderVertex* v, int n,
                          const GeoTexture* gt);

// ------------------------------------------------------------ the sprites

// How many sprites a frame can draw, in a ring of their own that
// georender_quads_rewind starts again with the quads': the effect system's
// particle pool is 1000 (afxInit).
#define GEO_SPRITE_RING 1000

// The sprites one of RenderEffects' packets holds (retail 0x00128da0):
// `n` quads in the top screen's pixels, x right to 400 and y down to 240,
// four corners each in the packet's order, -,- / +,- / -,+ / +,+, so each
// four are a strip. Each corner's z is its Z-buffer depth, in (0, 1). They
// draw in one call as two triangles each. The colour is the GS's, 0x80 for
// 1.0, and the texture modulates it; the pass is the texture's, with the
// main target's tests, as a strip's. PRIM 0x54 has no fog, so none is laid
// on. False when the ring is full, or for no texture.
bool georender_draw_sprites(const GeoRenderVertex* v, int n,
                            const GeoTexture* gt);

#endif
