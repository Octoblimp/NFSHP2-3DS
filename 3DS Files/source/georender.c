// eSolid geometry on the PICA200. See georender.h for the shape of it and
// docs/formats/solid-geometry.md for the format this consumes.

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "georender.h"
#include "geolit_shbin.h"
#include "geosolid_shbin.h"

// --------------------------------------------------------------- the shader

static DVLB_s*         s_dvlb;
static shaderProgram_s s_program;
static C3D_AttrInfo    s_attr;
static bool            s_ready;
static bool            s_zwrite = true;

// The fog georender_set_fog last gave, the blend set_blend last set, and
// the colour last handed to the PICA for the two.
static C3D_FogLut*     s_fogLut;
static uint32_t        s_fogColour;
static uint8_t         s_blend = GEO_BLEND_NONE;
static uint32_t        s_fogApplied;

static int s_uProjection = -1;
static int s_uModelView  = -1;
static int s_uLightVec   = -1;
static int s_uLightClr   = -1;
static int s_uAmbient    = -1;
static int s_uUvScale    = -1;

static C3D_Mtx s_projection;
static C3D_Mtx s_modelView;

// geolit.v.pica, the lit strips' and the environment passes'.
static DVLB_s*         s_litDvlb;
static shaderProgram_s s_litProgram;
static int s_lProjection = -1;
static int s_lModelView  = -1;
static int s_lUvScale    = -1;
static int s_lLightDir   = -1;
static int s_lDifClr     = -1;
static int s_lSpecClr    = -1;
static int s_lAmbient    = -1;
static int s_lEye        = -1;
static int s_lPowParams  = -1;
static int s_lEnvCol     = -1;
static int s_lFresnel    = -1;
static int s_lEnvPass    = -1;
static int s_lGlossEnv   = -1;

// The environment map: the cube, each face as a 2D texture of its own, a
// target over each, and the faces that have been cleared or drawn, a bit
// each.
static C3D_Tex           s_envTex;
static C3D_TexCube       s_envCube;
static C3D_Tex           s_envFaceTex[6];
static C3D_RenderTarget* s_envFace[6];
static unsigned          s_envDone;

static void free_envmap(void);

// The screen quads' ring, and the top screen's pixels as clip space.
static GeoRenderVertex* s_quads;
static int              s_numQuads;
static C3D_Mtx          s_screen;
static C3D_Mtx          s_identity;
static float   s_lightVec[3] = { 0.0f, 0.0f, 1.0f };
static float   s_lightClr[3] = { 1.0f, 1.0f, 1.0f };
static float   s_ambient      = 0.35f;

bool georender_init(void)
{
    if (s_ready) {
        return true;
    }

    s_dvlb = DVLB_ParseFile((u32*)geosolid_shbin, geosolid_shbin_size);
    if (!s_dvlb) {
        return false;
    }
    shaderProgramInit(&s_program);
    shaderProgramSetVsh(&s_program, &s_dvlb->DVLE[0]);

    s_litDvlb = DVLB_ParseFile((u32*)geolit_shbin, geolit_shbin_size);
    if (!s_litDvlb) {
        return false;
    }
    shaderProgramInit(&s_litProgram);
    shaderProgramSetVsh(&s_litProgram, &s_litDvlb->DVLE[0]);
#define LIT_UNIFORM(name) \
    shaderInstanceGetUniformLocation(s_litProgram.vertexShader, name)
    s_lProjection = LIT_UNIFORM("projection");
    s_lModelView  = LIT_UNIFORM("modelView");
    s_lUvScale    = LIT_UNIFORM("uvScale");
    s_lLightDir   = LIT_UNIFORM("lightDir");
    s_lDifClr     = LIT_UNIFORM("difClr");
    s_lSpecClr    = LIT_UNIFORM("specClr");
    s_lAmbient    = LIT_UNIFORM("ambient");
    s_lEye        = LIT_UNIFORM("eye");
    s_lPowParams  = LIT_UNIFORM("powParams");
    s_lEnvCol     = LIT_UNIFORM("envCol");
    s_lFresnel    = LIT_UNIFORM("fresnel");
    s_lEnvPass    = LIT_UNIFORM("envPass");
    s_lGlossEnv   = LIT_UNIFORM("glossEnv");
#undef LIT_UNIFORM

    s_uProjection = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "projection");
    s_uModelView  = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "modelView");
    s_uLightVec   = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "lightVec");
    s_uLightClr   = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "lightClr");
    s_uAmbient    = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "ambientClr");
    s_uUvScale    = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "uvScale");

    // The order here is the shader's v0..v3 and the order of the fields in
    // GeoRenderVertex; the two have to agree and there is nothing that
    // checks it for us.
    AttrInfo_Init(&s_attr);
    AttrInfo_AddLoader(&s_attr, 0, GPU_FLOAT,         3);   // position
    AttrInfo_AddLoader(&s_attr, 1, GPU_FLOAT,         2);   // ST
    AttrInfo_AddLoader(&s_attr, 2, GPU_UNSIGNED_BYTE, 4);   // colour
    AttrInfo_AddLoader(&s_attr, 3, GPU_BYTE,          3);   // normal

    Mtx_Identity(&s_projection);
    Mtx_Identity(&s_modelView);
    Mtx_Identity(&s_identity);

    // citro2d's own mapping for the top screen: x right to 400 and y down
    // to 240, at a depth in the middle of the clip volume.
    Mtx_OrthoTilt(&s_screen, 0.0f, 400.0f, 240.0f, 0.0f, 1.0f, -1.0f, true);
    s_quads = (GeoRenderVertex*)linearAlloc(GEO_QUAD_RING * 4u
                                            * sizeof(GeoRenderVertex));
    s_numQuads = 0;

    s_ready = true;
    return true;
}

void georender_exit(void)
{
    if (!s_ready) {
        return;
    }
    linearFree(s_quads);
    s_quads = NULL;
    free_envmap();
    shaderProgramFree(&s_litProgram);
    DVLB_Free(s_litDvlb);
    s_litDvlb = NULL;
    shaderProgramFree(&s_program);
    DVLB_Free(s_dvlb);
    s_dvlb  = NULL;
    s_ready = false;
}

// ---------------------------------------------------------------- the bake

// Strips are baked in texture order so that a solid draws in one call per
// distinct texture rather than one per strip -- and within a texture by
// flags and light material, which a batch has one of. eSolid does not store them
// that way, so this is a pass over the entry table first -- which is cheap,
// because eStripEntry carries NumVerts, NumPolys and TextureNumber and none
// of them need the packet replayed to read. See the note in
// docs/formats/solid-geometry.md about the entry table being a redundant
// copy of the packet header; this is what that redundancy buys.
typedef struct {
    int      texture;
    int      strip;
    uint16_t flags;
    int8_t   lightMaterial;
} StripOrder;

static int order_cmp(const void* a, const void* b)
{
    const StripOrder* x = (const StripOrder*)a;
    const StripOrder* y = (const StripOrder*)b;

    if (x->texture != y->texture) {
        return x->texture < y->texture ? -1 : 1;
    }
    if (x->flags != y->flags) {
        return x->flags < y->flags ? -1 : 1;
    }
    if (x->lightMaterial != y->lightMaterial) {
        return x->lightMaterial < y->lightMaterial ? -1 : 1;
    }
    // Ties keep file order, so a solid bakes the same way every time.
    return x->strip < y->strip ? -1 : (x->strip > y->strip ? 1 : 0);
}

static void put_vertex(GeoRenderVertex* dst, const GeoStrip* s, int v)
{
    const GeoVertex* src = &s->vert[v];
    uint8_t          rgba[4];
    int              i;

    for (i = 0; i < 3; i++) {
        dst->pos[i] = src->pos[i];
    }
    dst->st[0] = src->st[0];
    dst->st[1] = src->st[1];

    geo_unpack_colour(src->colour, rgba);
    // RGBA5551 widened as the VIF's V4-5 unpack widens it, c << 3, which is
    // what the GS's modulate and the lighter's CBVMix both count in: 0x80
    // is 1.0 to the GS, so a full 248 nearly doubles a texture.
    dst->colour[0] = (uint8_t)(rgba[0] << 3);
    dst->colour[1] = (uint8_t)(rgba[1] << 3);
    dst->colour[2] = (uint8_t)(rgba[2] << 3);
    dst->colour[3] = rgba[3] ? 255u : 0u;

    if (s->hasNormals) {
        for (i = 0; i < 3; i++) {
            dst->normal[i] = src->normal[i];
        }
    } else {
        // 17% of strips carry no normal field. Facing the viewer is the
        // least wrong constant: it makes them fully lit rather than black.
        dst->normal[0] = 0;
        dst->normal[1] = 0;
        dst->normal[2] = 127;
    }
    dst->pad = 0;
}

bool georender_bake(const GeoSolid* solid, GeoMesh* out)
{
    StripOrder*    order;
    GeoStrip*      strip;
    int            numTris = 0;
    int            n       = 0;
    int            i;
    int            at      = 0;

    memset(out, 0, sizeof *out);
    for (i = 0; i < 3; i++) {
        out->aabbMin[i] = solid->aabbMin[i];
        out->aabbMax[i] = solid->aabbMax[i];
    }
    if (solid->numStrips <= 0) {
        return true;
    }

    order = (StripOrder*)malloc((size_t)solid->numStrips * sizeof *order);
    strip = (GeoStrip*)malloc(sizeof *strip);
    if (!order || !strip) {
        free(order);
        free(strip);
        return false;
    }

    // NumPolys from the entry table is the triangle count, so the buffer can
    // be sized exactly without decoding anything.
    for (i = 0; i < solid->numStrips; i++) {
        GeoStripEntry entry;

        if (geo_strip_entry(solid, i, &entry) != GEO_OK) {
            out->skippedStrips++;
            continue;
        }
        // TextureNumber is one past the end on 25 strips across the disc --
        // the untextured sentinel. Normalise it to -1 here so the draw does
        // not have to know about it.
        order[n].texture = (entry.textureNumber >= 0
                            && entry.textureNumber < solid->numTextures)
                         ? entry.textureNumber : -1;
        order[n].strip   = i;
        order[n].flags   = entry.flags;
        order[n].lightMaterial = (int8_t)entry.lightMaterial;
        n++;
        numTris += entry.numPolys;
    }
    if (numTris <= 0) {
        free(order);
        free(strip);
        return true;
    }

    qsort(order, (size_t)n, sizeof *order, order_cmp);

    out->vbo = (GeoRenderVertex*)linearAlloc((size_t)numTris * 3u
                                             * sizeof(GeoRenderVertex));
    if (!out->vbo) {
        free(order);
        free(strip);
        return false;
    }

    for (i = 0; i < n; i++) {
        GeoBatch* batch;
        int       t;

        if (geo_decode_strip(solid, order[i].strip, strip) != GEO_OK) {
            out->skippedStrips++;
            continue;
        }

        // A new batch whenever the texture, the flags or the material
        // changes, which after the sort is once per distinct three. The cap
        // is a guard, not a limit that the data reaches: the most on the
        // disc is 34, TRN_SECTION40B's in TRACKB46.
        if (out->numBatches == 0
            || out->batch[out->numBatches - 1].texture != order[i].texture
            || out->batch[out->numBatches - 1].flags != order[i].flags
            || out->batch[out->numBatches - 1].lightMaterial
                   != order[i].lightMaterial) {
            if (out->numBatches >= GEO_MAX_BATCHES) {
                break;
            }
            batch = &out->batch[out->numBatches++];
            batch->first   = at;
            batch->count   = 0;
            batch->texture = order[i].texture;
            batch->flags   = order[i].flags;
            batch->lightMaterial = order[i].lightMaterial;
        }
        batch = &out->batch[out->numBatches - 1];

        for (t = 0; t < strip->numTris; t++) {
            int c;

            // The entry's NumPolys sized the buffer; a strip that decodes to
            // more than it claimed would run past the end. It never happens
            // -- the cross-check compares the two on all 18,848 strips --
            // but the buffer is the one thing here that cannot be allowed to
            // depend on that holding.
            if (at + 3 > numTris * 3) {
                break;
            }
            for (c = 0; c < 3; c++) {
                put_vertex(&out->vbo[at++], strip, strip->tri[t][c]);
            }
            batch->count += 3;
            out->numTris++;
        }
    }
    out->numVerts = at;

    free(order);
    free(strip);
    return true;
}

void georender_free(GeoMesh* mesh)
{
    if (mesh->vbo) {
        linearFree(mesh->vbo);
    }
    memset(mesh, 0, sizeof *mesh);
}

// ---------------------------------------------------------------- the draw

void georender_set_camera(const C3D_Mtx* projection, const C3D_Mtx* modelView)
{
    s_projection = *projection;
    s_modelView  = *modelView;
}

void georender_set_light(float x, float y, float z,
                         float r, float g, float b, float ambient)
{
    float len = sqrtf(x * x + y * y + z * z);

    if (len < 1e-6f) {
        x = 0.0f;
        y = 0.0f;
        z = 1.0f;
        len = 1.0f;
    }
    s_lightVec[0] = x / len;
    s_lightVec[1] = y / len;
    s_lightVec[2] = z / len;
    s_lightClr[0] = r;
    s_lightClr[1] = g;
    s_lightClr[2] = b;
    s_ambient     = ambient;
}

// The program, the vertex buffer and the uniforms, which every batch of a
// mesh shares.
static void bind_mesh(const GeoMesh* mesh)
{
    C3D_BufInfo* buf;

    C3D_BindProgram(&s_program);
    C3D_SetAttrInfo(&s_attr);

    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, mesh->vbo, sizeof(GeoRenderVertex), 4, 0x3210);

    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &s_projection);
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uModelView,  &s_modelView);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightVec,
                  s_lightVec[0], s_lightVec[1], s_lightVec[2], 0.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightClr,
                  s_lightClr[0], s_lightClr[1], s_lightClr[2], 1.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uAmbient,
                  s_ambient, s_ambient, s_ambient, 1.0f);
}

// A batch's combiner: its texture, or the vertex colour alone. With `gs`
// the texture modulates as the GS's does, Ct * Cv >> 7: the shaders hand
// the colour over as c / 255, so the colour is doubled, and the alpha not,
// because the packs' alpha was doubled when they were uploaded.
static void set_combiner(const GeoTexture* gt, int uvScale, bool gs)
{
    C3D_TexEnv* env = C3D_GetTexEnv(0);

    C3D_TexEnvInit(env);
    if (gt) {
        C3D_TexBind(0, gt->tex);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, uvScale,
                      gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);
        C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
        if (gs) {
            C3D_TexEnvScale(env, C3D_RGB, GPU_TEVSCALE_2);
        }
    } else {
        // No texture: the vertex colour alone, which is what the 25
        // sentinel strips and any unresolved hash fall back to.
        C3D_FVUnifSet(GPU_VERTEX_SHADER, uvScale, 1.0f, 1.0f, 0.0f, 1.0f);
        C3D_TexEnvSrc(env, C3D_Both, GPU_PRIMARY_COLOR, 0, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
    }
}

// One batch: its combiner and the draw.
static void draw_batch(const GeoBatch* b, const GeoTexture* gt, bool gs)
{
    set_combiner(gt, s_uUvScale, gs);
    C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
}

static const GeoTexture* batch_texture(const GeoBatch* b,
                                       const GeoTexture* textures,
                                       int numTextures)
{
    if (b->texture >= 0 && b->texture < numTextures && textures
        && textures[b->texture].tex) {
        return &textures[b->texture];
    }
    return NULL;
}

void georender_draw(const GeoMesh* mesh, const GeoTexture* textures,
                    int numTextures)
{
    int i;

    if (!s_ready || !mesh->vbo || mesh->numVerts <= 0) {
        return;
    }
    bind_mesh(mesh);

    // The VU did backface culling in software and nothing in the data forces
    // a consistent winding, so culling anything here would drop real
    // triangles. The winding *is* consistent within a strip -- the ADC
    // restart rule in geometry.c sees to that -- but not between the two
    // sides of a car body, which are mirrored. Draw both faces.
    C3D_CullFace(GPU_CULL_NONE);
    C3D_DepthTest(true, GPU_GREATER,
                  s_zwrite ? GPU_WRITE_ALL : GPU_WRITE_COLOR);

    for (i = 0; i < mesh->numBatches; i++) {
        const GeoBatch* b = &mesh->batch[i];

        if (b->count > 0) {
            draw_batch(b, batch_texture(b, textures, numTextures), false);
        }
    }
}

// The PICA's fog comes before its blend, where the PS2's came after the
// frame was done. For a blend over the frame the two are the same. A blend
// that adds to the frame, or takes from it, would add or take the fog's
// colour again, so those two take black: what they add then fades by the
// fog's fraction, as it does on the PS2 with the frame under it.
static void apply_fog_colour(void)
{
    uint32_t c;

    if (s_fogLut == NULL) {
        return;
    }
    c = s_blend == GEO_BLEND_ADD || s_blend == GEO_BLEND_SUBTRACT
            ? 0u : s_fogColour;
    if (c != s_fogApplied) {
        C3D_FogColor(c);
        s_fogApplied = c;
    }
}

void georender_set_fog(C3D_FogLut* lut, uint32_t colour)
{
    s_fogLut    = lut;
    s_fogColour = colour & 0xffffffu;
    if (lut == NULL) {
        C3D_FogGasMode(GPU_NO_FOG, GPU_PLAIN_DENSITY, false);
        C3D_FogLutBind(NULL);
        return;
    }
    C3D_FogGasMode(GPU_FOG, GPU_PLAIN_DENSITY, false);
    C3D_FogLutBind(lut);
    s_fogApplied = ~0u;
    apply_fog_colour();
}

// The GS's ALPHA_1 equations as the PICA's blend unit writes them. The
// PICA's reverse subtract is the destination less the source.
static void set_blend(uint8_t blend)
{
    s_blend = blend;
    apply_fog_colour();
    switch (blend) {
    case GEO_BLEND_ALPHA:
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA,
                       GPU_ONE_MINUS_SRC_ALPHA, GPU_SRC_ALPHA,
                       GPU_ONE_MINUS_SRC_ALPHA);
        break;
    case GEO_BLEND_ADD:
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA, GPU_ONE,
                       GPU_SRC_ALPHA, GPU_ONE);
        break;
    case GEO_BLEND_SUBTRACT:
        C3D_AlphaBlend(GPU_BLEND_REVERSE_SUBTRACT, GPU_BLEND_REVERSE_SUBTRACT,
                       GPU_SRC_ALPHA, GPU_ONE, GPU_SRC_ALPHA, GPU_ONE);
        break;
    default:
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_ONE, GPU_ZERO,
                       GPU_ONE, GPU_ZERO);
        break;
    }
}

static void set_pass(GeoPass pass)
{
    set_blend(pass.blend);
    C3D_DepthTest(true, GPU_GEQUAL,
                  pass.noDepthWrite || !s_zwrite ? GPU_WRITE_COLOR
                                                 : GPU_WRITE_ALL);
    // AREF 0x30, doubled with the packs' alpha.
    if (pass.noAlphaTest) {
        C3D_AlphaTest(false, GPU_ALWAYS, 0);
    } else {
        C3D_AlphaTest(true, GPU_GREATER, 0x60);
    }
}

void georender_draw_mask(const GeoMesh* mesh, const GeoTexture* textures,
                         int numTextures, uint64_t mask)
{
    static const GeoPass opaque;
    GeoPass              last = opaque;
    bool                 set  = false;
    int                  i;

    if (!s_ready || !mesh->vbo || mesh->numVerts <= 0 || mask == 0) {
        return;
    }
    bind_mesh(mesh);
    C3D_CullFace(GPU_CULL_NONE);

    for (i = 0; i < mesh->numBatches && i < 64; i++) {
        const GeoBatch*   b = &mesh->batch[i];
        const GeoTexture* gt;
        GeoPass           pass;

        if (!(mask & ((uint64_t)1 << i)) || b->count <= 0) {
            continue;
        }
        gt   = batch_texture(b, textures, numTextures);
        pass = gt ? gt->pass : opaque;
        if (!set || pass.blend != last.blend
            || pass.noDepthWrite != last.noDepthWrite
            || pass.noAlphaTest != last.noAlphaTest) {
            set_pass(pass);
            last = pass;
            set  = true;
        }
        draw_batch(b, gt, true);
    }
}

void georender_set_zwrite(bool on)
{
    s_zwrite = on;
}

// ---------------------------------------------------------- the lit strips

static void set_vec(int id, const float v[4])
{
    C3D_FVUnifSet(GPU_VERTEX_SHADER, id, v[0], v[1], v[2], v[3]);
}

// geolit's program, the mesh's vertices, and the batch's light.
static void bind_lit(const GeoMesh* mesh, const GeoLighting* L)
{
    C3D_BufInfo* buf;
    int          i;

    C3D_BindProgram(&s_litProgram);
    C3D_SetAttrInfo(&s_attr);
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, mesh->vbo, sizeof(GeoRenderVertex), 4, 0x3210);

    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_lProjection, &s_projection);
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_lModelView,  &s_modelView);
    for (i = 0; i < 3; i++) {
        set_vec(s_lLightDir + i, L->lightDir[i]);
        set_vec(s_lDifClr + i,   L->difClr[i]);
        set_vec(s_lSpecClr + i,  L->specClr[i]);
        set_vec(s_lEnvCol + i,   L->envCol[i]);
    }
    set_vec(s_lAmbient,   L->ambient);
    set_vec(s_lEye,       L->eye);
    set_vec(s_lPowParams, L->powParams);
    set_vec(s_lFresnel,   L->fresnel);
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lEnvPass,  false);
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lGlossEnv, false);
    C3D_CullFace(GPU_CULL_NONE);
}

void georender_draw_lit(const GeoMesh* mesh, const GeoTexture* textures,
                        int numTextures, int bi, const GeoLighting* L)
{
    static const GeoPass opaque;
    const GeoBatch*      b;
    const GeoTexture*    gt;
    C3D_TexEnv*          env;

    if (!s_ready || !mesh->vbo || bi < 0 || bi >= mesh->numBatches
        || mesh->batch[bi].count <= 0) {
        return;
    }
    b  = &mesh->batch[bi];
    gt = batch_texture(b, textures, numTextures);

    // The strip, with the lighter's colour or its own.
    if (L->lit) {
        bind_lit(mesh, L);
        set_pass(gt ? gt->pass : opaque);
        set_combiner(gt, s_lUvScale, true);
        C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
    } else {
        georender_draw_mask(mesh, textures, numTextures, (uint64_t)1 << bi);
    }
    if (!L->env || !georender_envmap_ready()) {
        return;
    }

    // The environment pass: the strip again, the map under the colour the
    // shader gives, added to the frame. It meets the depth the strip left
    // and writes none, and leaves the frame's alpha alone, which for a
    // gloss map is what it is added under.
    if (!L->lit) {
        bind_lit(mesh, L);
    }
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lEnvPass,  true);
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lGlossEnv, L->gloss);
    C3D_TexBind(0, &s_envTex);
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_RGB, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_RGB, GPU_MODULATE);
    C3D_TexEnvScale(env, C3D_RGB, GPU_TEVSCALE_2);
    C3D_TexEnvSrc(env, C3D_Alpha, GPU_PRIMARY_COLOR, 0, 0);
    C3D_TexEnvFunc(env, C3D_Alpha, GPU_REPLACE);

    // Added, so it fogs to black; see apply_fog_colour.
    s_blend = GEO_BLEND_ADD;
    apply_fog_colour();
    if (L->gloss) {
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_DST_ALPHA, GPU_ONE,
                       GPU_ZERO, GPU_ONE);
    } else {
        C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA, GPU_ONE,
                       GPU_ZERO, GPU_ONE);
    }
    C3D_DepthTest(true, GPU_GEQUAL, GPU_WRITE_COLOR);
    C3D_AlphaTest(false, GPU_ALWAYS, 0);
    C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
}

// --------------------------------------------------- the environment map

static void free_envmap(void)
{
    int f;

    for (f = 0; f < 6; f++) {
        if (s_envFace[f]) {
            C3D_RenderTargetDelete(s_envFace[f]);
            s_envFace[f] = NULL;
        }
    }
    if (s_envTex.cube == &s_envCube) {
        C3D_TexDelete(&s_envTex);
    }
    memset(&s_envTex, 0, sizeof s_envTex);
    s_envDone = 0;
}

// The cube in VRAM, where the GPU can draw on it, and a target with its
// own depth buffer over each face. Six faces of 64 are 96 KB of colour and
// as much of depth.
bool georender_envmap_init(int size)
{
    C3D_TexInitParams p = { (u16)size, (u16)size, 0, GPU_RGBA8,
                            GPU_TEX_CUBE_MAP, true };
    int               f;

    if (s_envFace[0]) {
        return true;
    }
    if (!C3D_TexInitWithParams(&s_envTex, &s_envCube, p)) {
        memset(&s_envTex, 0, sizeof s_envTex);
        return false;
    }
    // C3D_RenderTargetCreateFromTex asks whether the texture's data is in
    // VRAM, and a cube's data is its C3D_TexCube, so a target is made over
    // a 2D texture that is the face's image.
    for (f = 0; f < 6; f++) {
        s_envFaceTex[f]        = s_envTex;
        s_envFaceTex[f].data   = s_envCube.data[f];
        s_envFaceTex[f].param &= ~GPU_TEXTURE_MODE(7);
        s_envFace[f] = C3D_RenderTargetCreateFromTex(
            &s_envFaceTex[f], GPU_TEXFACE_2D, 0, GPU_RB_DEPTH24_STENCIL8);
        if (!s_envFace[f]) {
            free_envmap();
            return false;
        }
    }
    C3D_TexSetFilter(&s_envTex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(&s_envTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    s_envDone = 0;
    return true;
}

bool georender_envmap_face_done(int face)
{
    return face >= 0 && face < 6 && (s_envDone & (1u << face)) != 0;
}

bool georender_envmap_ready(void)
{
    return s_envDone == 0x3fu;
}

void georender_envmap_face(int face, uint32_t clear, bool draw)
{
    if (!s_ready || face < 0 || face >= 6 || !s_envFace[face]) {
        return;
    }
    C3D_RenderTargetClear(s_envFace[face], C3D_CLEAR_ALL, clear, 0);
    if (draw) {
        C3D_FrameDrawOn(s_envFace[face]);
    }
    s_envDone |= 1u << face;
}

// ------------------------------------------------------- the screen quads

void georender_quads_rewind(void)
{
    s_numQuads = 0;
}

static bool draw_screen_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                             const C3D_Mtx* screen, uint8_t blend,
                             bool alphaTest, bool depthTest)
{
    GeoRenderVertex* dst;
    C3D_BufInfo*     buf;
    C3D_TexEnv*      env;

    if (!s_ready || !s_quads || s_numQuads >= GEO_QUAD_RING || !gt
        || !gt->tex) {
        return false;
    }
    dst = &s_quads[s_numQuads * 4];
    memcpy(dst, v, 4u * sizeof *dst);
    GSPGPU_FlushDataCache(dst, 4u * sizeof *dst);

    C3D_BindProgram(&s_program);
    C3D_SetAttrInfo(&s_attr);
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, s_quads, sizeof(GeoRenderVertex), 4, 0x3210);

    // The vertex colour and nothing else: no light, and an ambient of one.
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, screen);
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uModelView,  &s_identity);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightVec, 0.0f, 0.0f, 1.0f, 0.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightClr, 0.0f, 0.0f, 0.0f, 1.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uAmbient,  1.0f, 1.0f, 1.0f, 1.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uUvScale,
                  gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);

    // The GS's modulate is Ct * Cv >> 7, so a vertex colour of 0x80 is 1.0
    // and 0xff nearly 2. The shader hands the colour over 255, so the
    // combiner doubles it; the alpha the same, over the packs' alpha, which
    // texpack_upload has doubled already.
    C3D_TexBind(0, gt->tex);
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_2);

    C3D_CullFace(GPU_CULL_NONE);
    if (alphaTest) {
        C3D_AlphaTest(true, GPU_GREATER, 0x60);
    } else {
        C3D_AlphaTest(false, GPU_ALWAYS, 0);
    }
    set_blend(blend);
    C3D_DepthTest(true, depthTest ? GPU_GEQUAL : GPU_ALWAYS, GPU_WRITE_COLOR);
    C3D_DrawArrays(GPU_TRIANGLE_STRIP, s_numQuads * 4, 4);
    s_numQuads++;

    // What draws next sets its own combiner, but not always its scale.
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_1);
    return true;
}

bool georender_draw_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                         uint8_t blend, bool depthTest)
{
    return draw_screen_quad(v, gt, &s_screen, blend, true, depthTest);
}

bool georender_draw_hud_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                             float width, float height)
{
    C3D_Mtx screen;
    int     i;

    // citro2d's stages after the first are still set for its own images.
    // Here they pass the first stage's colour through; citro2d sets 1 to
    // 3 again at its next draw after C2D_Prepare, and C2D_Prepare 4 and 5.
    for (i = 1; i < 6; i++) {
        C3D_TexEnvInit(C3D_GetTexEnv(i));
    }
    Mtx_OrthoTilt(&screen, 0.0f, width, height, 0.0f, 1.0f, -1.0f, true);
    return draw_screen_quad(v, gt, &screen, GEO_BLEND_ALPHA, false, false);
}
