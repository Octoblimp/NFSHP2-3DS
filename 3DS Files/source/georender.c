// eSolid geometry on the PICA200. See georender.h for the shape of it and
// docs/formats/solid-geometry.md for the format this consumes.

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "georender.h"
#include "geosolid_shbin.h"

// --------------------------------------------------------------- the shader

static DVLB_s*         s_dvlb;
static shaderProgram_s s_program;
static C3D_AttrInfo    s_attr;
static bool            s_ready;
static bool            s_zwrite = true;

static int s_uProjection = -1;
static int s_uModelView  = -1;
static int s_uLightVec   = -1;
static int s_uLightClr   = -1;
static int s_uAmbient    = -1;
static int s_uUvScale    = -1;

static C3D_Mtx s_projection;
static C3D_Mtx s_modelView;

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
    shaderProgramFree(&s_program);
    DVLB_Free(s_dvlb);
    s_dvlb  = NULL;
    s_ready = false;
}

// ---------------------------------------------------------------- the bake

// Strips are baked in texture order so that a solid draws in one call per
// distinct texture rather than one per strip. eSolid does not store them
// that way, so this is a pass over the entry table first -- which is cheap,
// because eStripEntry carries NumVerts, NumPolys and TextureNumber and none
// of them need the packet replayed to read. See the note in
// docs/formats/solid-geometry.md about the entry table being a redundant
// copy of the packet header; this is what that redundancy buys.
typedef struct {
    int texture;
    int strip;
} StripOrder;

static int order_cmp(const void* a, const void* b)
{
    const StripOrder* x = (const StripOrder*)a;
    const StripOrder* y = (const StripOrder*)b;

    if (x->texture != y->texture) {
        return x->texture < y->texture ? -1 : 1;
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
    // RGBA5551 widened the way the rest of the project widens it: c * 255/31
    // is exact at both ends, unlike a shift.
    dst->colour[0] = (uint8_t)(rgba[0] * 255 / 31);
    dst->colour[1] = (uint8_t)(rgba[1] * 255 / 31);
    dst->colour[2] = (uint8_t)(rgba[2] * 255 / 31);
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

        // A new batch whenever the texture changes, which after the sort is
        // once per distinct texture. The cap is a guard, not a limit that
        // the data reaches: the largest table on the disc has 28 entries.
        if (out->numBatches == 0
            || out->batch[out->numBatches - 1].texture != order[i].texture) {
            if (out->numBatches >= GEO_MAX_BATCHES) {
                break;
            }
            batch = &out->batch[out->numBatches++];
            batch->first   = at;
            batch->count   = 0;
            batch->texture = order[i].texture;
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

// One batch: its texture, or the vertex colour alone, and the draw.
static void draw_batch(const GeoBatch* b, const GeoTexture* gt)
{
    C3D_TexEnv* env = C3D_GetTexEnv(0);

    C3D_TexEnvInit(env);
    if (gt) {
        C3D_TexBind(0, gt->tex);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uUvScale,
                      gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);
        C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
    } else {
        // No texture: the vertex colour alone, which is what the 25
        // sentinel strips and any unresolved hash fall back to.
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uUvScale,
                      1.0f, 1.0f, 0.0f, 1.0f);
        C3D_TexEnvSrc(env, C3D_Both, GPU_PRIMARY_COLOR, 0, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
    }
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
            draw_batch(b, batch_texture(b, textures, numTextures));
        }
    }
}

// The GS's ALPHA_1 equations as the PICA's blend unit writes them. The
// PICA's reverse subtract is the destination less the source.
static void set_blend(uint8_t blend)
{
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
}

void georender_draw_mask(const GeoMesh* mesh, const GeoTexture* textures,
                         int numTextures, uint32_t mask)
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
    C3D_AlphaTest(true, GPU_GREATER, 0x60);

    for (i = 0; i < mesh->numBatches && i < 32; i++) {
        const GeoBatch*   b = &mesh->batch[i];
        const GeoTexture* gt;
        GeoPass           pass;

        if (!(mask & (1u << i)) || b->count <= 0) {
            continue;
        }
        gt   = batch_texture(b, textures, numTextures);
        pass = gt ? gt->pass : opaque;
        if (!set || pass.blend != last.blend
            || pass.noDepthWrite != last.noDepthWrite) {
            set_pass(pass);
            last = pass;
            set  = true;
        }
        draw_batch(b, gt);
    }
}

void georender_set_zwrite(bool on)
{
    s_zwrite = on;
}

// ------------------------------------------------------- the screen quads

void georender_quads_rewind(void)
{
    s_numQuads = 0;
}

bool georender_draw_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                         uint8_t blend)
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
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &s_screen);
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
    C3D_AlphaTest(true, GPU_GREATER, 0x60);
    set_blend(blend);
    C3D_DepthTest(true, GPU_ALWAYS, GPU_WRITE_COLOR);
    C3D_DrawArrays(GPU_TRIANGLE_STRIP, s_numQuads * 4, 4);
    s_numQuads++;

    // What draws next sets its own combiner, but not always its scale.
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_1);
    return true;
}
