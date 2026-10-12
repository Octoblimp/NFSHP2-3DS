// eSolid geometry on the PICA200. See georender.h for the shape of it and
// docs/formats/solid-geometry.md for the format this consumes.

#include <math.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "georender.h"
#include "capture.h"
#include "c3dwrap.h"
#include "configitems.h"
#include "geofold_shbin.h"
#include "geosolid_shbin.h"
#include "geocull.h"
#include "geosolidunif.h"
#include "hangwatch.h"

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

// The alpha test georender last set, for a numbered draw to put back
// (capture.h).
static bool            s_atOn;
static int             s_atRef;

// geosolid.v.pica's uniforms: what set_model makes for a model, and the
// light's colour and the ambient, over 255 (geosolidunif.h).
static int s_uMvp        = -1;
static int s_uFogModel   = -1;
static int s_uLightModel = -1;
static int s_uLightClr   = -1;
static int s_uAmbient    = -1;
static int s_uUvScale    = -1;

static C3D_Mtx s_projection;
static C3D_Mtx s_modelView;

// What a run (georender_run_begin) has sent, which its next draw need not
// send again. run_forget clears it all.
static struct {
    bool           on;
    bool           bound;       // s_program, s_attr and the frame's uniforms
    bool           lit;         // s_litProgram and s_attr (bind_lit)
    bool           strip;       // the strips' program, light and combiner
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

    // The strips leave the first stage's scale at 2 for the strips after
    // them (bind_strips). What draws next sets its own combiner, but not
    // always its scale.
    if (s_run.strip) {
        C3D_TexEnvScale(C3D_GetTexEnv(0), C3D_Both, GPU_TEVSCALE_1);
    }
    memset(&s_run, 0, sizeof s_run);
    s_run.on       = on;
    s_run.combiner = -1;
}

void georender_forget(void)
{
    run_forget();
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

// geolit.v.pica, the lit strips' and the environment passes': the second
// DVLE of geosolid's shbin (Makefile).
static shaderProgram_s s_litProgram;
static int s_lMvp        = -1;
static int s_lFogModel   = -1;
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

// The rear-view mirror's target, retail's target 7: its texture in VRAM,
// a target over it with a depth buffer of its own, and its size.
static C3D_Tex           s_mirrorTex;
static C3D_RenderTarget* s_mirror;
static int               s_mirrorW;
static int               s_mirrorH;
static bool              s_mirrorDrawn;

static void free_envmap(void);
static void free_mirror(void);
static void fog_row(const C3D_Mtx* projection, float row[4]);
// The view's side planes in the space of the model set_model set last,
// which every mesh draws in: the batches' clusters are tested against them
// (geocull.h).
static GeoCullPlanes s_cull;
static void set_model(int mvp, int fogModel, int light,
                      const C3D_Mtx* projection, const C3D_Mtx* modelView,
                      const float fog[4], const float lightVec[3]);
static void set_unlit(void);

// The screen quads' ring, and the top screen's pixels as clip space.
static GeoRenderVertex* s_quads;
static int              s_numQuads;
// The strips' ring, and the vertices of it the frame has used.
static GeoRenderVertex* s_strips;
static int              s_numStripVerts;
// The sprites' ring, six vertices a sprite, and the sprites drawn from it.
static GeoRenderVertex* s_sprites;
static int              s_numSprites;
static C3D_Mtx          s_screen;
// The screen's mapping with a vertex's z as its depth: z row (0, 0, -1,
// 0), which C3D_DepthMap's default scale of -1 turns back into z.
static C3D_Mtx          s_spriteScreen;
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
    if (!s_dvlb || s_dvlb->numDVLE < 2) {
        return false;
    }
    shaderProgramInit(&s_program);
    shaderProgramSetVsh(&s_program, &s_dvlb->DVLE[0]);

    shaderProgramInit(&s_litProgram);
    shaderProgramSetVsh(&s_litProgram, &s_dvlb->DVLE[1]);
#define LIT_UNIFORM(name) \
    shaderInstanceGetUniformLocation(s_litProgram.vertexShader, name)
    s_lMvp        = LIT_UNIFORM("mvp");
    s_lFogModel   = LIT_UNIFORM("fogModel");
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

    s_foldDvlb = DVLB_ParseFile((u32*)geofold_shbin, geofold_shbin_size);
    if (!s_foldDvlb) {
        return false;
    }
    shaderProgramInit(&s_foldProgram);
    shaderProgramSetVsh(&s_foldProgram, &s_foldDvlb->DVLE[0]);
    AttrInfo_Init(&s_foldAttr);
    AttrInfo_AddLoader(&s_foldAttr, 0, GPU_FLOAT, 2);   // the map's point
    AttrInfo_AddLoader(&s_foldAttr, 1, GPU_FLOAT, 3);   // the cube's

    s_uMvp        = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "mvp");
    s_uFogModel   = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "fogModel");
    s_uLightModel = shaderInstanceGetUniformLocation(s_program.vertexShader,
                                                     "lightModel");
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
    // The normal is loaded as four bytes, the pad its w, which neither
    // shader reads: the PICA freezes when a loader's attributes do not
    // fill its stride (3dbrew's GPU/Pitfalls), and three would leave 27
    // of the 28. Azahar draws either way; a New 3DS XL stopped at the
    // first draw (2026-10-05).
    AttrInfo_AddLoader(&s_attr, 3, GPU_BYTE,          4);   // normal, pad

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
    s_sprites = (GeoRenderVertex*)linearAlloc(GEO_SPRITE_RING * 6u
                                              * sizeof(GeoRenderVertex));
    s_numSprites = 0;
    s_spriteScreen = s_screen;
    s_spriteScreen.r[2].x = 0.0f;
    s_spriteScreen.r[2].y = 0.0f;
    s_spriteScreen.r[2].z = -1.0f;
    s_spriteScreen.r[2].w = 0.0f;
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
    linearFree(s_sprites);
    s_sprites = NULL;
    C3D_TexDelete(&s_noFogTex);
    free_envmap();
    free_mirror();
    shaderProgramFree(&s_foldProgram);
    DVLB_Free(s_foldDvlb);
    s_foldDvlb = NULL;
    shaderProgramFree(&s_litProgram);
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

// A batch is an indexed triangle list: its triangles in the strips' order,
// three 16-bit indices each into the mesh's vertices. A vertex goes in
// once however many triangles and strips share it -- the same position,
// ST, colour and normal, byte for byte -- so the PICA fetches it once, and
// its post-vertex cache (which C3D_DrawElements clears after each draw)
// shades a corner the last few triangles had once. The shipped strips are
// mostly runs of separate quads cut by ADC restarts, so a GPU strip saves
// little: TRACKB12's 133,795 triangles are 401,385 vertices as a list and
// 335,909 as strips joined by degenerates, but 176,505 indexed, and with a
// cache of 4 the GPU shades 1.70 a triangle where the list shaded 3. The
// draw order of the triangles is the list's.
typedef struct {
    GeoRenderVertex* vert;      // malloc'd, the entries' NumVerts summed
    int32_t*         slot;      // the hash's: a vertex, or -1
    uint32_t         mask;      // its size less 1, a power of two
    int              n;
} VertexSet;

static uint32_t vertex_hash(const GeoRenderVertex* v)
{
    const uint8_t* p = (const uint8_t*)v;
    uint32_t       h = 2166136261u;
    size_t         i;

    for (i = 0; i < sizeof *v; i++) {
        h = (h ^ p[i]) * 16777619u;
    }
    return h;
}

// The index of a vertex the same as `v`, which is added if there is none.
static int vertex_index(VertexSet* s, const GeoRenderVertex* v)
{
    uint32_t h = vertex_hash(v) & s->mask;

    while (s->slot[h] >= 0) {
        if (!memcmp(&s->vert[s->slot[h]], v, sizeof *v)) {
            return s->slot[h];
        }
        h = (h + 1) & s->mask;
    }
    s->vert[s->n] = *v;
    s->slot[h]    = s->n;
    return s->n++;
}

bool georender_bake(const GeoSolid* solid, GeoMesh* out)
{
    StripOrder*    order;
    GeoStrip*      strip;
    VertexSet      set     = { 0 };
    uint16_t*      idx;
    int            numTris = 0;
    int            cap     = 0;
    int            n       = 0;
    int            i;
    int            at      = 0;
    size_t         vbytes;
    size_t         ibytes;
    int            numClusters = 0;
    uint32_t       size;

    memset(out, 0, sizeof *out);
    for (i = 0; i < 3; i++) {
        out->aabbMin[i] = solid->aabbMin[i];
        out->aabbMax[i] = solid->aabbMax[i];
    }
    if (solid->numStrips <= 0) {
        return true;
    }

    // NumVerts and NumPolys from the entry table are the header's, so the
    // buffers can be sized without decoding anything: no more vertices than
    // the strips have, and three indices a triangle.
    for (i = 0; i < solid->numStrips; i++) {
        GeoStripEntry entry;

        if (geo_strip_entry(solid, i, &entry) != GEO_OK) {
            continue;
        }
        if (entry.numPolys > 0) {
            cap += entry.numVerts;
        }
        numTris += entry.numPolys;
    }
    if (numTris <= 0 || cap <= 0) {
        return true;
    }

    for (size = 1; size < 2u * (uint32_t)cap; size <<= 1) {
    }
    order    = (StripOrder*)malloc((size_t)solid->numStrips * sizeof *order);
    strip    = (GeoStrip*)malloc(sizeof *strip);
    set.vert = (GeoRenderVertex*)malloc((size_t)cap * sizeof *set.vert);
    set.slot = (int32_t*)malloc((size_t)size * sizeof *set.slot);
    idx      = (uint16_t*)malloc((size_t)numTris * 3u * sizeof *idx);
    if (!order || !strip || !set.vert || !set.slot || !idx) {
        free(order);
        free(strip);
        free(set.vert);
        free(set.slot);
        free(idx);
        return false;
    }
    memset(set.slot, 0xff, (size_t)size * sizeof *set.slot);
    set.mask = size - 1u;

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
    }

    qsort(order, (size_t)n, sizeof *order, order_cmp);

    for (i = 0; i < n; i++) {
        GeoBatch* batch;
        int       local[GEO_MAX_STRIP_VERTS];
        int       t, c;

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

        // The entry's NumVerts and NumPolys sized the buffers; a strip that
        // decodes to more than they claimed would run past the end. It
        // never happens -- the cross-check compares them on all 18,848
        // strips -- but the buffers are the one thing here that cannot be
        // allowed to depend on that holding. Nor can a 16-bit index.
        if (at + 3 * strip->numTris > numTris * 3
            || set.n + strip->numVerts > cap
            || set.n + strip->numVerts > 65536) {
            out->skippedStrips++;
            continue;
        }
        for (c = 0; c < strip->numVerts; c++) {
            local[c] = -1;
        }
        for (t = 0; t < strip->numTris; t++) {
            for (c = 0; c < 3; c++) {
                int v = strip->tri[t][c];

                if (local[v] < 0) {
                    GeoRenderVertex r;

                    put_vertex(&r, strip, v);
                    local[v] = vertex_index(&set, &r);
                }
                idx[at++] = (uint16_t)local[v];
            }
            batch->count += 3;
            out->numTris++;
        }
    }

    // The vertices, then the indices from the next 16 bytes, then the
    // batches' boxes, in one block.
    for (i = 0; i < out->numBatches; i++) {
        out->batch[i].cluster = numClusters;
        numClusters += geocull_count(out->batch[i].count);
    }
    vbytes   = ((size_t)set.n * sizeof(GeoRenderVertex) + 15u) & ~(size_t)15u;
    ibytes   = ((size_t)at * sizeof *idx + 3u) & ~(size_t)3u;
    out->vbo = set.n > 0 ? (GeoRenderVertex*)linearAlloc(
                               vbytes + ibytes
                               + (size_t)numClusters * sizeof(GeoCluster))
                         : NULL;
    if (out->vbo) {
        GeoCluster* clusters = (GeoCluster*)((uint8_t*)out->vbo + vbytes
                                             + ibytes);

        memcpy(out->vbo, set.vert, (size_t)set.n * sizeof *set.vert);
        out->ibo = (uint16_t*)((uint8_t*)out->vbo + vbytes);
        memcpy(out->ibo, idx, (size_t)at * sizeof *idx);
        out->numVerts   = set.n;
        out->numIndices = at;
        for (i = 0; i < out->numBatches; i++) {
            const GeoBatch* b = &out->batch[i];

            geocull_build(set.vert[0].pos,
                          (int)(sizeof(GeoRenderVertex) / sizeof(float)),
                          idx + b->first, b->count, clusters + b->cluster);
        }
        out->clusters = numClusters > 0 ? clusters : NULL;
    }

    free(order);
    free(strip);
    free(set.vert);
    free(set.slot);
    free(idx);
    if (!out->vbo && set.n > 0) {
        memset(out, 0, sizeof *out);
        return false;
    }
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

// Buffer 0 at `vbo`. Every buffer the run draws from has the same layout,
// so once a draw has sent citro3d's buffers, one register moves buffer 0
// to any other: in place of citro3d's twelve buffers.
static void bind_buffer(const void* vbo)
{
    C3D_BufInfo* buf;

    if (s_run.bufSet) {
        GPUCMD_AddWrite(GPUREG_ATTRIBBUFFER0_OFFSET,
                        osConvertVirtToPhys(vbo) - s_run.bufBase);
        return;
    }
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, vbo, sizeof(GeoRenderVertex), 4, 0x3210);
    // citro3d sends these with the next draw, and only then can a write of
    // the offset follow them: the draw sets s_run.bufSet.
    s_run.bufBase = buf->base_paddr;
}

// The program, the vertex buffer and the uniforms, which every batch of a
// mesh shares. In a run the program, the attributes and the uniforms that
// change only with the camera, the light and the fog go once, and the
// model-view when it changes; a mesh's buffer is bind_buffer's one
// register.
static void bind_mesh(const GeoMesh* mesh)
{
    if (!s_run.bound
        || memcmp(&s_run.projection, &s_projection, sizeof s_projection)) {
        float lightClr[4], ambientClr[4];

        C3D_BindProgram(&s_program);
        C3D_SetAttrInfo(&s_attr);
        geosolid_colours(s_lightClr[0], s_lightClr[1], s_lightClr[2],
                         s_ambient, lightClr, ambientClr);
        c3d_unif_vec(s_uLightClr, lightClr);
        c3d_unif_vec(s_uAmbient,  ambientClr);
        s_run.bound      = s_run.on;
        s_run.lit        = false;
        s_run.strip      = false;
        // The model's products are of the projection, the light and the
        // fog's planes too, any of which may be why this is here.
        s_run.mvSet      = false;
        s_run.projection = s_projection;
    }

    bind_buffer(mesh->vbo);
    if (!s_run.mvSet
        || memcmp(&s_run.modelView, &s_modelView, sizeof s_modelView)) {
        float fog[4];

        fog_row(&s_projection, fog);
        set_model(s_uMvp, s_uFogModel, s_uLightModel, &s_projection,
                  &s_modelView, fog, s_lightVec);
        s_run.mvSet     = s_run.on;
        s_run.modelView = s_modelView;
    }
}

static void apply_fog_colour(void);
static void set_blend(uint8_t blend);

static void alpha_test(bool on, int ref)
{
    s_atOn  = on;
    s_atRef = ref;
    C3D_AlphaTest(on, on ? GPU_GREATER : GPU_ALWAYS, ref);
}

// A draw of `count` vertices from `first`, or, with an index buffer, of
// the `count` indices from `first`: a mesh's batch (georender_bake).
static void issue(GPU_Primitive_t prim, int first, int count,
                  const uint16_t* ibo)
{
    if (ibo != NULL) {
        C3D_DrawElements(prim, count, C3D_UNSIGNED_SHORT, ibo + first);
    } else {
        C3D_DrawArrays(prim, first, count);
    }
}

// A numbered draw (capture.h): its colour is its number, red the low byte,
// green the high and blue 0x55, as the first stage's constant with no fog
// after it and no blend. The alpha is the draw's own, so a cut-out cuts as
// it does, and one that blends is cut to where its alpha shows. Then what
// it changed is put back as the next draw expects to find it.
static void draw_id(GPU_Primitive_t prim, int first, int count,
                    const uint16_t* ibo, const C3D_Tex* tex,
                    const char* what)
{
    int         id      = capture_next_id();
    bool        blended = s_blend != GEO_BLEND_NONE;
    C3D_TexEnv* env     = C3D_GetTexEnv(0);
    int         i;

    capture_note("%d %s; %s, first %d, %d verts; tex %p (data %p, %dx%d); "
                 "blend %d, alpha test %d/%02x; view %.2f %.2f %.2f",
                 id, HangwatchTrail[(HangwatchMarks - 1u) % HANGWATCH_TRAIL],
                 what, first, count, (const void*)tex,
                 tex ? tex->data : NULL, tex ? tex->width : 0,
                 tex ? tex->height : 0, s_blend, s_atOn, s_atRef,
                 (double)s_modelView.r[0].w, (double)s_modelView.r[1].w,
                 (double)s_modelView.r[2].w);
    C3D_TexEnvSrc(env, C3D_RGB, GPU_CONSTANT, 0, 0);
    C3D_TexEnvOpRgb(env, GPU_TEVOP_RGB_SRC_COLOR, GPU_TEVOP_RGB_SRC_COLOR,
                    GPU_TEVOP_RGB_SRC_COLOR);
    C3D_TexEnvFunc(env, C3D_RGB, GPU_REPLACE);
    C3D_TexEnvScale(env, C3D_RGB, GPU_TEVSCALE_1);
    C3D_TexEnvColor(env, 0xff550000u | ((uint32_t)id & 0xffffu));
    for (i = 1; i < 6; i++) {
        C3D_TexEnvInit(C3D_GetTexEnv(i));
    }
    C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_ONE, GPU_ZERO, GPU_ONE,
                   GPU_ZERO);
    if (blended) {
        C3D_AlphaTest(true, GPU_GREATER, 0x08);
    }
    issue(prim, first, count, ibo);

    s_run.combiner = -1;
    s_run.passSet  = false;
    s_run.strip    = false;
    s_fogApplied   = ~0u;
    set_blend(s_blend);
    alpha_test(s_atOn, s_atRef);
}

static void draw_prims(GPU_Primitive_t prim, int first, int count,
                       const uint16_t* ibo, const C3D_Tex* tex,
                       const char* what)
{
    if (capture_ids_on()) {
        draw_id(prim, first, count, ibo, tex, what);
        return;
    }
    if (capture_lod0_on() && tex != NULL && tex->maxLevel > 0) {
        // Unit 0's texture with its chain cut to level 0, sent again for
        // this draw and as it was for the next.
        C3D_Tex* t    = (C3D_Tex*)tex;
        u8       keep = t->maxLevel;

        t->maxLevel = 0;
        C3D_TexBind(0, t);
        issue(prim, first, count, ibo);
        t->maxLevel = keep;
        C3D_TexBind(0, t);
        return;
    }
    issue(prim, first, count, ibo);
}

static void draw_arrays(GPU_Primitive_t prim, int first, int count,
                        const C3D_Tex* tex, const char* what)
{
    draw_prims(prim, first, count, NULL, tex, what);
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
        c3d_unif_set(uvScale, u, v, 0.0f, 1.0f);
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

// A mesh's batch, less what the view cannot show (geocull.h): whole when
// its box is inside the view, not at all when it is outside, and otherwise
// each run of its clusters that are not outside as a draw. Whether anything
// was drawn: citro3d sends the buffers with a draw, and until one has gone
// bind_buffer cannot move them by their one register.
static bool draw_shown(const GeoMesh* mesh, const GeoBatch* b,
                       const C3D_Tex* tex, const char* what)
{
    const GeoCluster* k;
    bool              drawn = false;
    int               start = -1;
    int               n, i;

    if (mesh->clusters == NULL || !ConfigClusterCull) {
        draw_prims(GPU_TRIANGLES, b->first, b->count, mesh->ibo, tex, what);
        return true;
    }
    k = mesh->clusters + b->cluster;
    switch (geocull_box(&s_cull, k)) {
    case GEOCULL_OUT:
        return false;
    case GEOCULL_IN:
        draw_prims(GPU_TRIANGLES, b->first, b->count, mesh->ibo, tex, what);
        return true;
    }
    n = geocull_count(b->count) - 1;
    for (i = 0; i <= n; i++) {
        int first, end;

        if (i < n && geocull_box(&s_cull, &k[1 + i]) != GEOCULL_OUT) {
            if (start < 0) {
                start = i;
            }
            continue;
        }
        if (start < 0) {
            continue;
        }
        first = start * GEO_CLUSTER_INDICES;
        end   = i * GEO_CLUSTER_INDICES < b->count
              ? i * GEO_CLUSTER_INDICES : b->count;
        draw_prims(GPU_TRIANGLES, b->first + first, end - first, mesh->ibo,
                   tex, what);
        drawn = true;
        start = -1;
    }
    return drawn;
}

// One batch: its combiner and the draw.
static void draw_batch(const GeoMesh* mesh, const GeoBatch* b,
                       const GeoTexture* gt, bool gs)
{
    set_combiner(gt, s_uUvScale, gs, s_run.on);
    if (draw_shown(mesh, b, gt ? gt->tex : NULL, "batch")) {
        s_run.bufSet = s_run.on;
    }
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
            draw_batch(mesh, b, batch_texture(b, textures, numTextures),
                       false);
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
static void fog_row(const C3D_Mtx* projection, float row[4])
{
    float a = (fog_s(0.0f) - fog_s(1.0f)) / (s_fogFar - s_fogNear);
    float b = fog_s(0.0f) - a * s_fogFar;
    const C3D_FVec* w = &projection->r[3];

    row[0] = a * w->x;
    row[1] = a * w->y;
    row[2] = a * w->z;
    row[3] = a * w->w + b;
}

// A model drawn through `projection` and `modelView`, with the fog's
// view-space row `fog` and the light towards `lightVec` in view space
// (NULL for none): geosolid_model's products, into the uniforms `mvp`,
// `fogModel` and `light`, any of which may be -1 (TASKS 46). They are made
// again only when what they are made of changes, since the strips set
// them for each draw; each uniform is still handed over every time, as a
// program's constants may have taken its register since (c3dwrap.c).
static void set_model(int mvp, int fogModel, int light,
                      const C3D_Mtx* projection, const C3D_Mtx* modelView,
                      const float fog[4], const float lightVec[3])
{
    static struct {
        bool          valid;
        float         p[4][4], mv[4][4], fog[4], light[3];
        GeoSolidModel out;
    } c;
    float p[4][4], mv[4][4], l[3] = { 0.0f, 0.0f, 0.0f };
    int   i;

    for (i = 0; i < 4; i++) {
        p[i][0]  = projection->r[i].x;
        p[i][1]  = projection->r[i].y;
        p[i][2]  = projection->r[i].z;
        p[i][3]  = projection->r[i].w;
        mv[i][0] = modelView->r[i].x;
        mv[i][1] = modelView->r[i].y;
        mv[i][2] = modelView->r[i].z;
        mv[i][3] = modelView->r[i].w;
    }
    if (lightVec != NULL) {
        memcpy(l, lightVec, sizeof l);
    }
    if (!c.valid || memcmp(c.p, p, sizeof p) || memcmp(c.mv, mv, sizeof mv)
        || memcmp(c.fog, fog, sizeof c.fog)
        || memcmp(c.light, l, sizeof l)) {
        geosolid_model((const float(*)[4])p, (const float(*)[4])mv, fog, l,
                       &c.out);
        geocull_planes((const float(*)[4])c.out.mvp, &s_cull);
        memcpy(c.p, p, sizeof p);
        memcpy(c.mv, mv, sizeof mv);
        memcpy(c.fog, fog, sizeof c.fog);
        memcpy(c.light, l, sizeof l);
        c.valid = true;
    }
    if (mvp >= 0) {
        for (i = 0; i < 4; i++) {
            c3d_unif_vec(mvp + i, c.out.mvp[i]);
        }
    }
    c3d_unif_vec(fogModel, c.out.fog);
    c3d_unif_vec(light, c.out.light);
}

// The vertex colour and nothing else: no light, and an ambient of one.
static void set_unlit(void)
{
    float lightClr[4], ambientClr[4];

    geosolid_colours(0.0f, 0.0f, 0.0f, 1.0f, lightClr, ambientClr);
    c3d_unif_vec(s_uLightClr, lightClr);
    c3d_unif_vec(s_uAmbient,  ambientClr);
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

// set_blend's colour, with the target's alpha the fragment's own: the GS
// writes a fragment's alpha into a PSMCT32 target whatever ALPHA_1 says,
// and the mirror's target is read again by it.
static void set_blend_source_alpha(uint8_t blend)
{
    GPU_BLENDEQUATION eq  = GPU_BLEND_ADD;
    GPU_BLENDFACTOR   src = GPU_ONE;
    GPU_BLENDFACTOR   dst = GPU_ZERO;

    set_blend(blend);
    switch (blend) {
    case GEO_BLEND_ALPHA:
        src = GPU_SRC_ALPHA;
        dst = GPU_ONE_MINUS_SRC_ALPHA;
        break;
    case GEO_BLEND_ADD:
        src = GPU_SRC_ALPHA;
        dst = GPU_ONE;
        break;
    case GEO_BLEND_SUBTRACT:
        eq  = GPU_BLEND_REVERSE_SUBTRACT;
        src = GPU_SRC_ALPHA;
        dst = GPU_ONE;
        break;
    default:
        break;
    }
    C3D_AlphaBlend(eq, GPU_BLEND_ADD, src, dst, GPU_ONE, GPU_ZERO);
}

static bool same_pass(GeoPass a, GeoPass b)
{
    return a.blend == b.blend && a.noDepthWrite == b.noDepthWrite
           && a.noAlphaTest == b.noAlphaTest;
}

static void set_pass(GeoPass pass)
{
    set_blend(pass.blend);
    C3D_DepthTest(true, GPU_GEQUAL,
                  pass.noDepthWrite || !s_zwrite ? GPU_WRITE_COLOR
                                                 : GPU_WRITE_ALL);
    // AREF 0x30, doubled with the packs' alpha.
    if (pass.noAlphaTest) {
        alpha_test(false, 0);
    } else {
        alpha_test(true, 0x60);
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
        if (!set || !same_pass(pass, last)) {
            set_pass(pass);
            last = pass;
            set  = true;
        }
        draw_batch(mesh, b, gt, true);
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

// geolit's program, the mesh's vertices, and the batch's light.
//
// One shbin holds geolit and geosolid (Makefile), so the switch between
// them sends no shader code, and the uniforms they share are in the same
// registers. c3d_unif_* sends only what the GPU does not hold, and most of
// a car's batches share their light. In a run the buffers, the cull, the
// pass, the combiner and the texture stand; what bind_mesh and the strips
// keep of the uniforms they send is forgotten, so they go through the
// cache again (step 13b-5).
static void bind_lit(const GeoMesh* mesh, const GeoLighting* L)
{
    float fog[4];
    int   i;

    s_run.bound = false;
    s_run.mvSet = false;
    s_run.uvSet = false;
    s_run.strip = false;
    if (!s_run.lit) {
        C3D_BindProgram(&s_litProgram);
        C3D_SetAttrInfo(&s_attr);
        s_run.lit = s_run.on;
    }
    bind_buffer(mesh->vbo);

    // geosolid's products, the light's direction left out: the lighter's
    // lights are its own, in the model's space already.
    fog_row(&s_projection, fog);
    set_model(s_lMvp, s_lFogModel, -1, &s_projection, &s_modelView, fog,
              s_lightVec);
    for (i = 0; i < 3; i++) {
        c3d_unif_vec(s_lLightDir + i, L->lightDir[i]);
        c3d_unif_vec(s_lDifClr + i,   L->difClr[i]);
        c3d_unif_vec(s_lSpecClr + i,  L->specClr[i]);
        c3d_unif_vec(s_lEnvCol + i,   L->envCol[i]);
    }
    c3d_unif_vec(s_lAmbient,   L->ambient);
    c3d_unif_vec(s_lEye,       L->eye);
    c3d_unif_vec(s_lPowParams, L->powParams);
    c3d_unif_vec(s_lFresnel,   L->fresnel);
    c3d_unif_bool(s_lEnvPass,  false);
    c3d_unif_bool(s_lGlossEnv, false);
    if (!s_run.culled) {
        C3D_CullFace(GPU_CULL_NONE);
        s_run.culled = s_run.on;
    }
}

void georender_draw_lit(const GeoMesh* mesh, const GeoTexture* textures,
                        int numTextures, int bi, const GeoLighting* L)
{
    static const GeoPass opaque;
    const GeoBatch*      b;
    const GeoTexture*    gt;
    C3D_TexEnv*          env;
    const C3D_Tex*       sphere;
    GeoPass              pass;
    bool                 drawn;

    if (!s_ready || !mesh->vbo || bi < 0 || bi >= mesh->numBatches
        || mesh->batch[bi].count <= 0) {
        return;
    }
    b  = &mesh->batch[bi];
    gt = batch_texture(b, textures, numTextures);

    // The strip, with the lighter's colour or its own. In a run, the pass
    // and the combiner go only when they differ from the last batch's.
    if (L->lit) {
        bind_lit(mesh, L);
        pass = gt ? gt->pass : opaque;
        if (!s_run.passSet || !same_pass(pass, s_run.pass)) {
            set_pass(pass);
            s_run.passSet = s_run.on;
            s_run.pass    = pass;
        }
        set_combiner(gt, s_lUvScale, true, s_run.on);
        if (draw_shown(mesh, b, gt ? gt->tex : NULL, "lit")) {
            s_run.bufSet = s_run.on;
        }
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
    c3d_unif_bool(s_lEnvPass,  true);
    c3d_unif_bool(s_lGlossEnv, L->gloss);
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
    alpha_test(false, 0);
    // The strip's own clusters again: the same matrix, so the same ones.
    drawn = draw_shown(mesh, b, sphere, "env pass");
    // Its combiner, texture and pass are no batch's.
    s_run.combiner = -1;
    s_run.tex      = NULL;
    s_run.passSet  = false;
    if (drawn) {
        s_run.bufSet = s_run.on;
    }
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
// 16 bits a texel, as retail's PSMCT16 targets are. The cube is RGBA8
// over D24S8 depth, the top screen's pair. It was RGBA5551 until a New
// 3DS XL stopped at a face's first draw (2026-10-05). The stop was not
// the pair: it was the first draw through geosolid, where the PICA
// freezes on two faults Azahar draws through, the vertex stride
// (georender_init) and output components the shader left unwritten
// (geosolid.v.pica). A 5551 face waits on a device run.
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
    alpha_test(false, 0);
    for (i = 0; i < 9; i++) {
        int g = kOrder[i];

        if (views & 1u << (g < 6 ? g : 2)) {
            draw_arrays(GPU_TRIANGLES, g * GEO_FOLD_GRID_VERTS,
                        GEO_FOLD_GRID_VERTS, &s_envTex, "fold");
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

// --------------------------------------------------------------- the mirror

static void free_mirror(void)
{
    if (s_mirror) {
        C3D_RenderTargetDelete(s_mirror);
        s_mirror = NULL;
    }
    if (s_mirrorTex.data) {
        C3D_TexDelete(&s_mirrorTex);
    }
    memset(&s_mirrorTex, 0, sizeof s_mirrorTex);
    s_mirrorW     = 0;
    s_mirrorH     = 0;
    s_mirrorDrawn = false;
}

// RGBA8 over D24S8, the cube's faces' pair: 64 KB of each at 256 by 64.
// Read bilinear and clamped, as the target's TextureInfo has the GS read
// it (MMag 1, MMin 2).
bool georender_mirror_init(int width, int height)
{
    if (s_mirror) {
        return s_mirrorW == width && s_mirrorH == height;
    }
    if (!s_ready) {
        return false;
    }
    if (!C3D_TexInitVRAM(&s_mirrorTex, (u16)width, (u16)height, GPU_RGBA8)) {
        memset(&s_mirrorTex, 0, sizeof s_mirrorTex);
        return false;
    }
    s_mirror = C3D_RenderTargetCreateFromTex(&s_mirrorTex, GPU_TEXFACE_2D, 0,
                                             GPU_RB_DEPTH24_STENCIL8);
    if (!s_mirror) {
        free_mirror();
        return false;
    }
    C3D_TexSetFilter(&s_mirrorTex, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(&s_mirrorTex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    s_mirrorW = width;
    s_mirrorH = height;
    return true;
}

bool georender_mirror_begin(uint32_t clear)
{
    if (!s_ready || !s_mirror) {
        return false;
    }
    C3D_RenderTargetClear(s_mirror, C3D_CLEAR_ALL, clear, 0);
    C3D_FrameDrawOn(s_mirror);
    s_mirrorDrawn = true;
    return true;
}

const C3D_Tex* georender_mirror_texture(void)
{
    return s_mirrorDrawn ? &s_mirrorTex : NULL;
}

// ------------------------------------------------------- the screen quads

void georender_quads_rewind(void)
{
    s_numQuads      = 0;
    s_numStripVerts = 0;
    s_numSprites    = 0;
}

static bool draw_screen_quad(const GeoRenderVertex v[4], const GeoTexture* gt,
                             const C3D_Mtx* screen, uint8_t blend,
                             bool alphaTest, float depth, bool sourceAlpha)
{
    GeoRenderVertex* dst;
    C3D_BufInfo*     buf;
    C3D_TexEnv*      env;
    // The fog's row: a constant, the near plane's unless `depth` says.
    float            fog[4] = { 0.0f, 0.0f, 0.0f, fog_s(1.0f) };

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

    set_unlit();
    c3d_unif_set(s_uUvScale, gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);

    // Every fragment at `depth`: the Z-buffer's map with a scale of 0 and
    // the depth as its offset. The fog's distance is the view's depth
    // there, u = (far - d) / (far - near) for d = near far / (near + z
    // (far - near)); with no depth, the near plane's.
    if (depth >= 0.0f) {
        float u = depth * s_fogFar
                  / (s_fogNear + depth * (s_fogFar - s_fogNear));

        C3D_DepthMap(true, 0.0f, depth);
        fog[3] = fog_s(u);
    }
    set_model(s_uMvp, s_uFogModel, s_uLightModel, screen, &s_identity, fog,
              NULL);

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
        alpha_test(true, 0x60);
    } else {
        alpha_test(false, 0);
    }
    if (sourceAlpha) {
        set_blend_source_alpha(blend);
    } else {
        set_blend(blend);
    }
    C3D_DepthTest(true, depth >= 0.0f ? GPU_GEQUAL : GPU_ALWAYS,
                  GPU_WRITE_COLOR);
    draw_arrays(GPU_TRIANGLE_STRIP, s_numQuads * 4, 4, gt->tex, "quad");
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
    return draw_screen_quad(v, gt, &s_screen, blend, !gt->pass.noAlphaTest,
                            depth, false);
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
    return draw_screen_quad(v, gt, &screen, GEO_BLEND_ALPHA, false, -1.0f,
                            false);
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
    return draw_screen_quad(v, gt, &screen, blend, alphaTest, -1.0f, false);
}

bool georender_draw_mirror_quad(const GeoRenderVertex v[4],
                                const GeoTexture* gt, uint8_t blend,
                                bool sourceAlpha)
{
    C3D_Mtx screen;

    if (!s_mirror) {
        return false;
    }
    // A texture's rows are its own, not a screen's turned on its side.
    Mtx_Ortho(&screen, 0.0f, (float)s_mirrorW, (float)s_mirrorH, 0.0f, 1.0f,
              -1.0f, false);
    return draw_screen_quad(v, gt, &screen, blend, false, -1.0f, sourceAlpha);
}

// ------------------------------------------------------------- the strips

// The strips' program, buffer, light and combiner. In a run the strips
// after the first keep them, and send only their texture, uniforms and
// pass where they differ from the last strip's: a car's shadow is some
// eighteen strips (step 13b-5). What bind_mesh and bind_lit keep of the
// program and the uniforms goes; the buffers stand.
static void bind_strips(void)
{
    C3D_TexEnv* env;

    s_run.bound    = false;
    s_run.lit      = false;
    s_run.mvSet    = false;
    s_run.uvSet    = false;
    s_run.combiner = -1;
    C3D_BindProgram(&s_program);
    C3D_SetAttrInfo(&s_attr);
    bind_buffer(s_strips);

    // The vertex colour and nothing else, as the screen quads have it.
    set_unlit();

    // The colour and its alpha are the GS's, 0x80 for 1.0, so the
    // combiner doubles both, as it does for the screen quads.
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_2);

    if (!s_run.culled) {
        C3D_CullFace(GPU_CULL_NONE);
        s_run.culled = s_run.on;
    }
    s_run.strip = s_run.on;
}

bool georender_draw_strip(const GeoRenderVertex* v, int n, const GeoTexture* gt)
{
    GeoRenderVertex* dst;
    float            fog[4];

    if (!s_ready || !s_strips || n < 3 || !gt || !gt->tex
        || s_numStripVerts + n > GEO_STRIP_RING) {
        return false;
    }
    dst = &s_strips[s_numStripVerts];
    memcpy(dst, v, (size_t)n * sizeof *dst);

    if (!s_run.strip) {
        bind_strips();
    }
    fog_row(&s_projection, fog);
    set_model(s_uMvp, s_uFogModel, s_uLightModel, &s_projection,
              &s_modelView, fog, NULL);
    c3d_unif_set(s_uUvScale, gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);
    if (!s_run.on || s_run.tex != gt->tex) {
        C3D_TexBind(0, gt->tex);
        s_run.tex = s_run.on ? gt->tex : NULL;
    }
    if (!s_run.passSet || !same_pass(gt->pass, s_run.pass)) {
        set_pass(gt->pass);
        s_run.passSet = s_run.on;
        s_run.pass    = gt->pass;
    }
    draw_arrays(GPU_TRIANGLE_STRIP, s_numStripVerts, n, gt->tex, "strip");
    s_numStripVerts += n;
    s_run.bufSet = s_run.on;

    // Out of a run, nothing keeps the strips' combiner: what draws next
    // sets its own, but not always its scale.
    if (!s_run.on) {
        C3D_TexEnvScale(C3D_GetTexEnv(0), C3D_Both, GPU_TEVSCALE_1);
    }
    return true;
}

// ------------------------------------------------------------ the sprites

bool georender_draw_sprites(const GeoRenderVertex* v, int n,
                            const GeoTexture* gt)
{
    GeoRenderVertex* dst;
    C3D_BufInfo*     buf;
    C3D_TexEnv*      env;
    float            fog[4] = { 0.0f, 0.0f, 0.0f, fog_s(1.0f) };
    int              first = s_numSprites * 6;
    int              i;

    if (!s_ready || !s_sprites || n <= 0 || !gt || !gt->tex
        || s_numSprites + n > GEO_SPRITE_RING) {
        return false;
    }
    run_forget();
    // A strip of four is the triangles 0 1 2 and 2 1 3.
    dst = &s_sprites[first];
    for (i = 0; i < n; i++, v += 4, dst += 6) {
        dst[0] = v[0];
        dst[1] = v[1];
        dst[2] = v[2];
        dst[3] = v[2];
        dst[4] = v[1];
        dst[5] = v[3];
    }

    C3D_BindProgram(&s_program);
    C3D_SetAttrInfo(&s_attr);
    buf = C3D_GetBufInfo();
    BufInfo_Init(buf);
    BufInfo_Add(buf, s_sprites, sizeof(GeoRenderVertex), 4, 0x3210);

    // The vertex colour and nothing else, as the screen quads have it.
    set_unlit();
    set_model(s_uMvp, s_uFogModel, s_uLightModel, &s_spriteScreen,
              &s_identity, fog, NULL);
    c3d_unif_set(s_uUvScale, gt->uvScale[0], gt->uvScale[1], 0.0f, 1.0f);
    // No fog: unit 1 keeps all of the colour for the draw.
    if (s_fog != NULL && s_noFogTex.data) {
        C3D_TexBind(1, &s_noFogTex);
    }

    // As the screen quads' and the strips': the GS's 0x80 is 1.0.
    C3D_TexBind(0, gt->tex);
    env = C3D_GetTexEnv(0);
    C3D_TexEnvInit(env);
    C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
    C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_2);

    C3D_CullFace(GPU_CULL_NONE);
    set_pass(gt->pass);
    draw_arrays(GPU_TRIANGLES, first, n * 6, gt->tex, "sprites");
    s_numSprites += n;

    if (s_fog != NULL) {
        C3D_TexBind(1, (C3D_Tex*)&s_fog->tex);
    }
    C3D_TexEnvScale(env, C3D_Both, GPU_TEVSCALE_1);
    return true;
}
