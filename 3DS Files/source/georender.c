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

static int s_uProjection = -1;
static int s_uModelView  = -1;
static int s_uLightVec   = -1;
static int s_uLightClr   = -1;
static int s_uAmbient    = -1;

static C3D_Mtx s_projection;
static C3D_Mtx s_modelView;
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

    s_ready = true;
    return true;
}

void georender_exit(void)
{
    if (!s_ready) {
        return;
    }
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

void georender_draw(const GeoMesh* mesh, C3D_Tex* const* textures,
                    int numTextures)
{
    C3D_BufInfo* buf;
    C3D_TexEnv*  env;
    int          i;

    if (!s_ready || !mesh->vbo || mesh->numVerts <= 0) {
        return;
    }

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

    // The VU did backface culling in software and nothing in the data forces
    // a consistent winding, so culling anything here would drop real
    // triangles. The winding *is* consistent within a strip -- the ADC
    // restart rule in geometry.c sees to that -- but not between the two
    // sides of a car body, which are mirrored. Draw both faces.
    C3D_CullFace(GPU_CULL_NONE);
    C3D_DepthTest(true, GPU_GREATER, GPU_WRITE_ALL);

    for (i = 0; i < mesh->numBatches; i++) {
        const GeoBatch* b   = &mesh->batch[i];
        C3D_Tex*        tex = NULL;

        if (b->count <= 0) {
            continue;
        }
        if (b->texture >= 0 && b->texture < numTextures && textures) {
            tex = textures[b->texture];
        }

        env = C3D_GetTexEnv(0);
        C3D_TexEnvInit(env);
        if (tex) {
            C3D_TexBind(0, tex);
            C3D_TexEnvSrc(env, C3D_Both, GPU_TEXTURE0, GPU_PRIMARY_COLOR, 0);
            C3D_TexEnvFunc(env, C3D_Both, GPU_MODULATE);
        } else {
            // No texture: the vertex colour alone, which is what the 25
            // sentinel strips and any unresolved hash fall back to.
            C3D_TexEnvSrc(env, C3D_Both, GPU_PRIMARY_COLOR, 0, 0);
            C3D_TexEnvFunc(env, C3D_Both, GPU_REPLACE);
        }

        C3D_DrawArrays(GPU_TRIANGLES, b->first, b->count);
    }
}
