// eSolid geometry on the PICA200. See georender.h for the shape of it and
// docs/formats/solid-geometry.md for the format this consumes.

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "georender.h"
#include "geofold_shbin.h"
#include "geolit_shbin.h"
#include "geosolid_shbin.h"

// --------------------------------------------------------------- the shader

static DVLB_s*         s_dvlb;
static shaderProgram_s s_program;
static C3D_AttrInfo    s_attr;
static bool            s_ready;
static bool            s_zwrite = true;

// The fog georender_set_fog last gave, the blend set_blend last set, and
// the colour last handed to the fog's stage for the two; and the planes
// georender_set_depth_range gave, for the fog's distance.
static const GeoFog*   s_fog;
static uint32_t        s_fogColour;
static uint8_t         s_blend = GEO_BLEND_NONE;
static uint32_t        s_fogApplied;
static float           s_fogNear = 1.0f;
static float           s_fogFar  = 2.0f;

// What texture unit 1 holds with the fog off. citro3d's C3D_TexBind reads
// the type of what a unit past 0 is given, so NULL there is a read of
// address 12; no stage reads this one.
static C3D_Tex         s_noFogTex;

static int s_uProjection = -1;
static int s_uModelView  = -1;
static int s_uLightVec   = -1;
static int s_uLightClr   = -1;
static int s_uAmbient    = -1;
static int s_uUvScale    = -1;
static int s_uFogRow     = -1;

static C3D_Mtx s_projection;
static C3D_Mtx s_modelView;

// What a run (georender_run_begin) has sent, which its next draw need not
// send again. run_forget clears it all.
static struct {
    bool           on;
    bool           bound;       // s_program, s_attr and the frame's uniforms
    C3D_Mtx        projection;  // which they were sent for
    bool           mvSet;
    C3D_Mtx        modelView;
    bool           bufSet;      // citro3d's buffers, sent with a draw
    u32            bufBase;     // the base buffer 0's offset is from
    bool           culled;      // C3D_CullFace(GPU_CULL_NONE)
    bool           passSet;
    GeoPass        pass;
    int            combiner;    // -1 unknown; 0 the colour; 1, 2 the texture
    const C3D_Tex* tex;         // texture unit 0's; NULL unknown
    bool           uvSet;
    float          uvScale[2];
} s_run;

static void run_forget(void)
{
    bool on = s_run.on;

    memset(&s_run, 0, sizeof s_run);
    s_run.on       = on;
    s_run.combiner = -1;
}

void georender_run_begin(void)
{
    s_run.on = true;
    run_forget();
}

void georender_run_end(void)
{
    // A run writes buffer 0's offset itself (bind_mesh), so citro3d's
    // copy is stale: marked changed, it is sent again before its next
    // draw, and the GPU's matches it.
    if (s_run.bufSet) {
        C3D_GetBufInfo();
    }
    s_run.on = false;
    run_forget();
}

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
static int s_lFogRow     = -1;

// The environment map: the cube, each face as a 2D texture of its own, a
// target over each, and the faces that have been cleared or drawn, a bit
// each.
static C3D_Tex           s_envTex;
static C3D_TexCube       s_envCube;
static C3D_Tex           s_envFaceTex[6];
static C3D_RenderTarget* s_envFace[6];
static unsigned          s_envDone;

// The sphere map, retail's target 14, and a target over it; the fold's
// program and its triangles; and whether the map has been cleared, and
// folded.
static C3D_Tex           s_sphereTex;
static C3D_RenderTarget* s_sphere;
static DVLB_s*           s_foldDvlb;
static shaderProgram_s   s_foldProgram;
static C3D_AttrInfo      s_foldAttr;
static GeoFoldVertex*    s_fold;
static bool              s_sphereCleared;
static bool              s_sphereFolded;
// A texture the environment passes take in place of the sphere map, as
// the car select's CARSELECTENVMAP, or NULL.
static const C3D_Tex*    s_envOverride;

static void free_envmap(void);
static void set_fog_row(int id, const C3D_Mtx* projection);

// The screen quads' ring, and the top screen's pixels as clip space.
static GeoRenderVertex* s_quads;
static int              s_numQuads;
// The strips' ring, and the vertices of it the frame has used.
static GeoRenderVertex* s_strips;
static int              s_numStripVerts;
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
    s_lFogRow     = LIT_UNIFORM("fogRow");
#undef LIT_UNIFORM

    s_foldDvlb = DVLB_ParseFile((u32*)geofold_shbin, geofold_shbin_size);
    if (!s_foldDvlb) {
        return false;
    }
    shaderProgramInit(&s_foldProgram);
    shaderProgramSetVsh(&s_foldProgram, &s_foldDvlb->DVLE[0]);
    AttrInfo_Init(&s_foldAttr);
    AttrInfo_AddLoader(&s_foldAttr, 0, GPU_FLOAT, 2);   // the map's point
    AttrInfo_AddLoader(&s_foldAttr, 1, GPU_FLOAT, 3);   // the cube's

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
    s_uFogRow     = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "fogRow");

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
    s_strips = (GeoRenderVertex*)linearAlloc(GEO_STRIP_RING
                                             * sizeof(GeoRenderVertex));
    s_numStripVerts = 0;
    // Both rings are on the linear heap, which C3D_FrameEnd(0) flushes
    // whole before the GPU runs the frame's commands, so a quad or a
    // strip is not flushed when it is written. A flush of each was a
    // call to the GSP service, a strip's 4 to 30 vertices at a time.
    if (!C3D_TexInit(&s_noFogTex, 8, 8, GPU_A8)) {
        return false;
    }
    memset(s_noFogTex.data, 0xff, s_noFogTex.size);
    GSPGPU_FlushDataCache(s_noFogTex.data, s_noFogTex.size);

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
    linearFree(s_strips);
    s_strips = NULL;
    C3D_TexDelete(&s_noFogTex);
    free_envmap();
    shaderProgramFree(&s_foldProgram);
    DVLB_Free(s_foldDvlb);
    s_foldDvlb = NULL;
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
    s_run.bound   = false;
}

// The program, the vertex buffer and the uniforms, which every batch of a
// mesh shares. In a run the program, the attributes and the uniforms that
// change only with the camera, the light and the fog go once, and the
// model-view when it changes. Every mesh's buffer has the same layout, so
// after the run's first, a mesh's buffer is where it starts: one register
// in place of citro3d's twelve buffers.
static void bind_mesh(const GeoMesh* mesh)
{
    C3D_BufInfo* buf;

    if (!s_run.bound
        || memcmp(&s_run.projection, &s_projection, sizeof s_projection)) {
        C3D_BindProgram(&s_program);
        C3D_SetAttrInfo(&s_attr);
        C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &s_projection);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightVec,
                      s_lightVec[0], s_lightVec[1], s_lightVec[2], 0.0f);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightClr,
                      s_lightClr[0], s_lightClr[1], s_lightClr[2], 1.0f);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uAmbient,
                      s_ambient, s_ambient, s_ambient, 1.0f);
        set_fog_row(s_uFogRow, &s_projection);
        s_run.bound      = s_run.on;
        s_run.projection = s_projection;
    }

    if (s_run.bufSet) {
        GPUCMD_AddWrite(GPUREG_ATTRIBBUFFER0_OFFSET,
                        osConvertVirtToPhys(mesh->vbo) - s_run.bufBase);
    } else {
        buf = C3D_GetBufInfo();
        BufInfo_Init(buf);
        BufInfo_Add(buf, mesh->vbo, sizeof(GeoRenderVertex), 4, 0x3210);
        // citro3d sends these with the next draw (draw_batch), and only
        // then can a write of the offset follow them.
        s_run.bufBase = buf->base_paddr;
    }
    if (!s_run.mvSet
        || memcmp(&s_run.modelView, &s_modelView, sizeof s_modelView)) {
        C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uModelView, &s_modelView);
        s_run.mvSet     = s_run.on;
        s_run.modelView = s_modelView;
    }
}

// A batch's combiner: its texture, or the vertex colour alone. With `gs`
// the texture modulates as the GS's does, Ct * Cv >> 7: the shaders hand
// the colour over as c / 255, so the colour is doubled, and the alpha not,
// because the packs' alpha was doubled when they were uploaded. With
// `cached`, in a run, only what differs from the last batch's is sent.
static void set_combiner(const GeoTexture* gt, int uvScale, bool gs,
                         bool cached)
{
    int         combiner = gt ? (gs ? 2 : 1) : 0;
    float       u        = gt ? gt->uvScale[0] : 1.0f;
    float       v        = gt ? gt->uvScale[1] : 1.0f;
    C3D_TexEnv* env;

    if (gt && (!cached || s_run.tex != gt->tex)) {
        C3D_TexBind(0, gt->tex);
        s_run.tex = cached ? gt->tex : NULL;
    }
    if (!cached || !s_run.uvSet || s_run.uvScale[0] != u
        || s_run.uvScale[1] != v) {
        C3D_FVUnifSet(GPU_VERTEX_SHADER, uvScale, u, v, 0.0f, 1.0f);
        s_run.uvSet      = cached;
        s_run.uvScale[0] = u;
        s_run.uvScale[1] = v;
    }
    if (cached && s_run.combiner == combiner) {
        return;
    }
    s_run.combiner = cached ? combiner : -1;
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    if (gt) {
        C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
        if (gs) {
            C3D_TexEnvScale(env, C3D_RGB, GPU_TEVSCALE_2);
        }
    } else {
        // No texture: the vertex colour alone, which is what the 25
        // sentinel strips and any unresolved hash fall back to.
        C3D_TexEnvSrc(env, C3D_Both, GPU_PRIMARY_COLOR, 0, 0);
        C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
    }
}

// One batch: its combiner and the draw.
static void draw_batch(const GeoBatch* b, const GeoTexture* gt, bool gs)
{
    set_combiner(gt, s_uUvScale, gs, s_run.on);
    C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
    s_run.bufSet = s_run.on;
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
    s_run.passSet = false;

    for (i = 0; i < mesh->numBatches; i++) {
        const GeoBatch* b = &mesh->batch[i];

        if (b->count > 0) {
            draw_batch(b, batch_texture(b, textures, numTextures), false);
        }
    }
}

// The fog is the last combiner stage's, before the blend, where the PS2's
// came after the frame was done. For a blend over the frame the two are
// the same. A blend that adds to the frame, or takes from it, would add or
// take the fog's colour again, so those two take black: what they add then
// fades by the fog's fraction, as it does on the PS2 with the frame under
// it. The stage is the colour before it, by the fraction texture unit 1
// reads, and the fog's colour by the rest, as the PICA's own fog was; the
// alpha passes. Stage 5 is the fog's alone: the draws set the stages
// before it.
static void apply_fog_colour(void)
{
    C3D_TexEnv* env;
    uint32_t    c;

    if (s_fog == NULL) {
        return;
    }
    c = s_blend == GEO_BLEND_ADD || s_blend == GEO_BLEND_SUBTRACT
            ? 0u : s_fogColour;
    if (c == s_fogApplied) {
        return;
    }
    env = C3D_GetTexEnv(5);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_RGB, GPU_PREVIOUS, GPU_CONSTANT, GPU_TEXTURE1);
    C3D_TexEnvOpRgb(env, GPU_TEVOP_RGB_SRC_COLOR, GPU_TEVOP_RGB_SRC_COLOR,
                    GPU_TEVOP_RGB_SRC_ALPHA);
    C3D_TexEnvFunc(env, C3D_RGB, GPU_INTERPOLATE);
    C3D_TexEnvColor(env, 0xff000000u | c);
    s_fogApplied = c;
}

void georender_set_fog(const GeoFog* fog, uint32_t colour)
{
    run_forget();
    s_fog        = fog && fog->tex.data ? fog : NULL;
    s_fogColour  = colour & 0xffffffu;
    s_fogApplied = ~0u;
    if (s_fog == NULL) {
        if (s_noFogTex.data) {
            C3D_TexBind(1, &s_noFogTex);
        }
        C3D_TexEnvInit(C3D_GetTexEnv(5));
        return;
    }
    C3D_TexBind(1, (C3D_Tex*)&s_fog->tex);
    apply_fog_colour();
}

void georender_set_depth_range(float near, float far)
{
    if (far > near && near > 0.0f) {
        s_fogNear = near;
        s_fogFar  = far;
    }
    s_run.bound = false;
}

// The fog's s for the view's depth u, where texture unit 1 reads step j's
// fraction at u = j / GEO_FOG_STEPS: texel j's middle.
static float fog_s(float u)
{
    return (u * (float)GEO_FOG_STEPS + 0.5f) / (float)GEO_FOG_TEX_W;
}

// For a projection whose w is the view's depth d: u = (far - d) / (far -
// near), so s is d by a, plus b, and the row is w's row by a, plus b in
// w, the view-space position's being 1.
static void set_fog_row(int id, const C3D_Mtx* projection)
{
    float a = (fog_s(0.0f) - fog_s(1.0f)) / (s_fogFar - s_fogNear);
    float b = fog_s(0.0f) - a * s_fogFar;
    const C3D_FVec* w = &projection->r[3];

    C3D_FVUnifSet(GPU_VERTEX_SHADER, id, a * w->x, a * w->y, a * w->z,
                  a * w->w + b);
}

// Every row of the texture is the same, so a texel's byte is its column's
// fraction: step j's for column j, and the last step's past it. The PICA
// lays a texture out in 8 by 8 tiles, here one row of them, each in Morton
// order, x in the even bits.
bool georender_fog_fill(GeoFog* fog, const float keep[GEO_FOG_STEPS + 1])
{
    uint8_t* p;
    int      k, m;

    if (!fog->tex.data) {
        if (!C3D_TexInit(&fog->tex, GEO_FOG_TEX_W, 8, GPU_A8)) {
            memset(&fog->tex, 0, sizeof fog->tex);
            return false;
        }
        C3D_TexSetFilter(&fog->tex, GPU_LINEAR, GPU_LINEAR);
        C3D_TexSetWrap(&fog->tex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    }
    p = (uint8_t*)fog->tex.data;
    for (k = 0; k < GEO_FOG_TEX_W / 8; k++) {
        for (m = 0; m < 64; m++) {
            int   x = k * 8 + ((m & 1) | (m >> 1 & 2) | (m >> 2 & 4));
            float f = keep[x < GEO_FOG_STEPS ? x : GEO_FOG_STEPS];

            f = f < 0.0f ? 0.0f : f > 1.0f ? 1.0f : f;
            p[k * 64 + m] = (uint8_t)(f * 255.0f + 0.5f);
        }
    }
    GSPGPU_FlushDataCache(p, fog->tex.size);
    return true;
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
    if (!s_run.culled) {
        C3D_CullFace(GPU_CULL_NONE);
        s_run.culled = s_run.on;
    }
    // In a run the pass the last batch set holds.
    if (s_run.passSet) {
        last = s_run.pass;
        set  = true;
    }

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
    s_run.passSet = s_run.on && set;
    s_run.pass    = last;
}

void georender_set_zwrite(bool on)
{
    s_zwrite      = on;
    s_run.passSet = false;
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

    // geolit's program and uniforms replace what a run has sent.
    run_forget();
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
    set_fog_row(s_lFogRow, &s_projection);
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
    const C3D_Tex*       sphere;

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
        set_combiner(gt, s_lUvScale, true, false);
        C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
    } else {
        georender_draw_mask(mesh, textures, numTextures, (uint64_t)1 << bi);
    }
    sphere = s_envOverride ? s_envOverride
           : georender_envmap_ready() ? &s_sphereTex : NULL;
    if (!L->env || !sphere) {
        return;
    }

    // The environment pass: the strip again, the sphere map under the
    // colour the shader gives, added to the frame. It meets the depth the strip left
    // and writes none, and leaves the frame's alpha alone, which for a
    // gloss map is what it is added under.
    if (!L->lit) {
        bind_lit(mesh, L);
    }
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lEnvPass,  true);
    C3D_BoolUnifSet(GPU_VERTEX_SHADER, s_lGlossEnv, L->gloss);
    C3D_TexBind(0, (C3D_Tex*)sphere);
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

    if (s_sphere) {
        C3D_RenderTargetDelete(s_sphere);
        s_sphere = NULL;
    }
    if (s_sphereTex.data) {
        C3D_TexDelete(&s_sphereTex);
    }
    memset(&s_sphereTex, 0, sizeof s_sphereTex);
    if (s_fold) {
        linearFree(s_fold);
        s_fold = NULL;
    }
    s_sphereCleared = false;
    s_sphereFolded  = false;
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
// own depth buffer over each face; then the sphere map, with a target of
// no depth, and the fold's triangles in linear memory. The sphere map is
// 16 bits a texel, as retail's PSMCT16 targets are. The cube is RGBA8:
// the PICA is given a colour buffer as wide as its depth buffer, as the
// top screen's RGBA8 and D24S8 are. A New 3DS XL's GPU stopped at a
// 5551 face's first draw over D24S8 depth (2026-10-05); that pair is the
// suspect.
// Six faces of 64 are 96 KB of colour and 96 KB of depth, and a map of
// 256 is 128 KB.
bool georender_envmap_init(int size, int mapSize, const GeoFoldVertex* fold)
{
    C3D_TexInitParams p = { (u16)size, (u16)size, 0, GPU_RGBA8,
                            GPU_TEX_CUBE_MAP, true };
    size_t            n = GEO_FOLD_GRIDS * GEO_FOLD_GRID_VERTS
                          * sizeof(GeoFoldVertex);
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

    // Read bilinear and clamped, as TEX1_1 and CLAMP_1 have the GS read
    // the map.
    if (!C3D_TexInitVRAM(&s_sphereTex, (u16)mapSize, (u16)mapSize,
                         GPU_RGBA5551)) {
        memset(&s_sphereTex, 0, sizeof s_sphereTex);
        free_envmap();
        return false;
    }
    s_sphere = C3D_RenderTargetCreateFromTex(&s_sphereTex, GPU_TEXFACE_2D, 0,
                                             -1);
    s_fold   = (GeoFoldVertex*)linearAlloc(n);
    if (!s_sphere || !s_fold) {
        free_envmap();
        return false;
    }
    C3D_TexSetFilter(&s_sphereTex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(&s_sphereTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    memcpy(s_fold, fold, n);
    GSPGPU_FlushDataCache(s_fold, n);
    return true;
}

bool georender_envmap_face_done(int face)
{
    return face >= 0 && face < 6 && (s_envDone & (1u << face)) != 0;
}

bool georender_envmap_ready(void)
{
    return s_sphereFolded;
}

void georender_set_env_texture(const C3D_Tex* tex)
{
    s_envOverride = tex;
}

void georender_envmap_fold(unsigned views)
{
    // eCreateEnvMapPrims' order: CreateEnvMap for each view but 2, then
    // CreateBackEnvMap's four grids if view 2 drew.
    static const uint8_t kOrder[9] = { 0, 1, 3, 4, 5, 6, 7, 8, 9 };
    C3D_BufInfo*         buf;
    C3D_TexEnv*          env;
    int                  i;

    if (!s_ready || !s_sphere || !s_fold || (views & 0x3fu) == 0) {
        return;
    }
    run_forget();
    if (!s_sphereCleared) {
        C3D_RenderTargetClear(s_sphere, C3D_CLEAR_COLOR, 0, 0);
        s_sphereCleared = true;
    }
    C3D_FrameDrawOn(s_sphere);

    C3D_BindProgram(&s_foldProgram);
    C3D_SetAttrInfo(&s_foldAttr);
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, s_fold, sizeof(GeoFoldVertex), 2, 0x10);

    // The texel by the strips' colour, the GS's modulate with a colour
    // under 0x80, so not doubled; and the strips' alpha alone, as TEXA's
    // TA1 is 0x80 and every texel of a face has its alpha bit.
    C3D_TexBind(0, &s_envTex);
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_RGB, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_RGB, GPU_MODULATE);
    C3D_TexEnvSrc(env, C3D_Alpha, GPU_PRIMARY_COLOR, 0, 0);
    C3D_TexEnvFunc(env, C3D_Alpha, GPU_REPLACE);
    for (i = 1; i < 6; i++) {
        C3D_TexEnvInit(C3D_GetTexEnv(i));
    }

    // ALPHA_1 0x44, (Cs - Cd) As + Cd, leaving the map's alpha, which no
    // pass reads. PRIM 0x54 has no fog, which stage 5 had; no depth, and
    // no alpha test.
    s_blend = GEO_BLEND_ALPHA;
    C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA,
                   GPU_ONE_MINUS_SRC_ALPHA, GPU_ZERO, GPU_ONE);
    C3D_CullFace(GPU_CULL_NONE);
    C3D_DepthTest(false, GPU_ALWAYS, GPU_WRITE_COLOR);
    C3D_AlphaTest(false, GPU_ALWAYS, 0);
    for (i = 0; i < 9; i++) {
        int g = kOrder[i];

        if (views & 1u << (g < 6 ? g : 2)) {
            C3D_DrawArrays(GPU_TRIANGLES, g * GEO_FOLD_GRID_VERTS,
                           GEO_FOLD_GRID_VERTS);
        }
    }
    s_fogApplied = ~0u;
    apply_fog_colour();
    s_sphereFolded = true;
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
    s_numQuads      = 0;
    s_numStripVerts = 0;
}

static bool draw_screen_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                             const C3D_Mtx* screen, uint8_t blend,
                             bool alphaTest, float depth)
{
    GeoRenderVertex* dst;
    C3D_BufInfo*     buf;
    C3D_TexEnv*      env;

    if (!s_ready || !s_quads || s_numQuads >= GEO_QUAD_RING || !gt
        || !gt->tex) {
        return false;
    }
    // Its own program, buffer, uniforms and state: in a run, the next
    // draw sends its whole state again.
    run_forget();
    dst = &s_quads[s_numQuads * 4];
    memcpy(dst, v, 4u * sizeof *dst);

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

    // Every fragment at `depth`: the Z-buffer's map with a scale of 0 and
    // the depth as its offset. The fog's distance is the view's depth
    // there, u = (far - d) / (far - near) for d = near far / (near + z
    // (far - near)); with no depth, the near plane's.
    if (depth >= 0.0f) {
        float u = depth * s_fogFar
                  / (s_fogNear + depth * (s_fogFar - s_fogNear));

        C3D_DepthMap(true, 0.0f, depth);
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uFogRow, 0.0f, 0.0f, 0.0f,
                      fog_s(u));
    } else {
        C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uFogRow, 0.0f, 0.0f, 0.0f,
                      fog_s(1.0f));
    }

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
    C3D_DepthTest(true, depth >= 0.0f ? GPU_GEQUAL : GPU_ALWAYS,
                  GPU_WRITE_COLOR);
    C3D_DrawArrays(GPU_TRIANGLE_STRIP, s_numQuads * 4, 4);
    s_numQuads++;
    if (depth >= 0.0f) {
        C3D_DepthMap(true, -1.0f, 0.0f);
    }

    // What draws next sets its own combiner, but not always its scale.
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_1);
    return true;
}

bool georender_draw_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                         uint8_t blend, float depth)
{
    return draw_screen_quad(v, gt, &s_screen, blend, true, depth);
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
    return draw_screen_quad(v, gt, &screen, GEO_BLEND_ALPHA, false, -1.0f);
}

bool georender_draw_hud_quad_w(const GeoRenderVertex v[4],
                               const GeoTexture* gt, uint8_t blend,
                               bool alphaTest, float width, float height)
{
    C3D_Mtx screen;
    int     i;

    for (i = 1; i < 6; i++) {
        C3D_TexEnvInit(C3D_GetTexEnv(i));
    }
    // The shader's position is (x w, y w, w, 1). The screen's matrix M
    // takes (x, y, 0, 1), so this one is M with its third column moved to
    // the fourth's place and nothing left in the fourth: it gives
    // M (x w, y w, 0, w), which the divide by w puts at (x, y), and the
    // interpolation is perspective-correct by w.
    Mtx_OrthoTilt(&screen, 0.0f, width, height, 0.0f, 1.0f, -1.0f, true);
    for (i = 0; i < 4; i++) {
        screen.r[i].z = screen.r[i].w;
        screen.r[i].w = 0.0f;
    }
    return draw_screen_quad(v, gt, &screen, blend, alphaTest, -1.0f);
}

// ------------------------------------------------------------- the strips

bool georender_draw_strip(const GeoRenderVertex* v, int n, const GeoTexture* gt)
{
    GeoRenderVertex* dst;
    C3D_BufInfo*     buf;
    C3D_TexEnv*      env;

    if (!s_ready || !s_strips || n < 3 || !gt || !gt->tex
        || s_numStripVerts + n > GEO_STRIP_RING) {
        return false;
    }
    run_forget();
    dst = &s_strips[s_numStripVerts];
    memcpy(dst, v, (size_t)n * sizeof *dst);

    C3D_BindProgram(&s_program);
    C3D_SetAttrInfo(&s_attr);
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, s_strips, sizeof(GeoRenderVertex), 4, 0x3210);

    // The vertex colour and nothing else, as the screen quads have it.
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uProjection, &s_projection);
    C3D_FVUnifMtx4x4(GPU_VERTEX_SHADER, s_uModelView,  &s_modelView);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightVec, 0.0f, 0.0f, 1.0f, 0.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uLightClr, 0.0f, 0.0f, 0.0f, 1.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uAmbient,  1.0f, 1.0f, 1.0f, 1.0f);
    C3D_FVUnifSet(GPU_VERTEX_SHADER, s_uUvScale,
                  gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);
    set_fog_row(s_uFogRow, &s_projection);

    // The colour and its alpha are the GS's, 0x80 for 1.0, so the
    // combiner doubles both, as it does for the screen quads.
    C3D_TexBind(0, gt->tex);
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_2);

    C3D_CullFace(GPU_CULL_NONE);
    set_pass(gt->pass);
    C3D_DrawArrays(GPU_TRIANGLE_STRIP, s_numStripVerts, n);
    s_numStripVerts += n;

    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_1);
    return true;
}
