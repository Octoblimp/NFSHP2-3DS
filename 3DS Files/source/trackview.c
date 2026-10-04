#include "trackview.h"

#include <malloc.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "bchunk.h"
#include "bchunkload.h"
#include "carrenderinfo.h"
#include "eefpu.h"
#include "eenvmap.h"
#include "efog.h"
#include "eframe.h"
#include "elight.h"
#include "emath.h"
#include "emodel.h"
#include "epoly.h"
#include "esolid.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "gamedata.h"
#include "scenery.h"
#include "sky.h"
#include "sun.h"
#include "sundraw.h"
#include "texpack.h"
#include "texturepack.h"
#include "trackflow.h"
#include "trackroute.h"
#include "weatherman.h"

// The track's files, named from its number as the game names them from
// RaceParameters.TrackNumber (retail 0x0031a898, the demo's 0x00312520).
// BeginGameFlowLoadingTrackSpecific (retail 0x001690a0) loads
// TRACKS\TRACKB%d.LZC and names it .BUN once expanded; the port ships it
// expanded.
#define TRACK_BUNDLE_FORMAT "TRACKS/TRACKB%d.BUN"

// The texture files, in the order LoadingTrackSpecificPart4 (retail
// 0x00168f98) has them loaded, after the track bundle. Of the 415 names
// the demo TRACKB12's solids' tables hold, TEX12LOCATION.BIN has 350,
// INGAMEB.BUN 12 and TEX12TRACK.BIN 4, and 49 are in no pack on the disc
// and are given the default.
static const char* const kTexFormats[TRACKVIEW_NUM_TEXFILES] = {
    "TRACKS/TEX%dTRACK.BIN",
    "TRACKS/TEX%dLOCATION.BIN",
};

#define PAD_DEAD     24             // circle pad noise floor
#define PAD_FULL     156.0f
#define LOOK_SPEED   1.6f           // radians a second on a held button
#define PITCH_LIMIT  1.5f
#define SPEED_MIN    1.875f
#define SPEED_MAX    480.0f
#define EYE_HEIGHT   2.5f           // above the road, a chase camera's height

// Linear heap a texture upload has to leave behind: the command buffers,
// the render targets' own allocations and the UI's later uploads come out
// of the same heap, and a level-0 upload that takes the last of it is
// worse than a level-1 one that does not.
#define TEX_RESERVE  (6u * 1024u * 1024u)

// The fields of view the camera is given. 9102 is aBaselineFovZ, 50
// degrees, which is the one the near plane is scaled against, so the near
// plane comes out as the camera's own.
#define TRACK_FOV    9102
#define TRACK_NEAR   0.5f           // CameraMover's defaults
#define TRACK_FAR    5000.0f

// The engine's view space is +y down and +z forward, citro3d's +y up and
// -z forward. See geoview.c, where this was found the hard way.
#define VIEW_FLIP_Y  (-1.0f)
#define VIEW_FLIP_Z  (-1.0f)

// GPUCMD_Add drops a command that does not fit rather than failing, and
// the frame's end still needs room to close the list, so a draw is left
// out once less than this is free -- 32 KB, a few dozen draws' worth.
#define CMDBUF_GUARD_WORDS 8192u

static TrackView*      s_draw;      // the viewer StuffScenery draws for
static C3D_Mtx         s_proj;
static const bMatrix4* s_worldView;
static bool            s_envFace;   // drawing into the environment map

// A Z rect StuffSun asked for, and the target it is in the pixels of.
typedef struct {
    uint32_t* dst;
    int       x, y, w, h;
    int       targetW, targetH;
    float     aspX, aspY;
} SunRect;

static eRenderTarget* s_quadTarget;     // the view StuffSun draws for
static SunRect        s_sunRects[NUM_SUN_ZBUFFERS];
static int            s_numSunRects;

// The fog: its fractions for the view's palette, by depth, one for the
// scenery and one for the sky and the sun; the colour; and the planes the
// last frame's view was between. See fog_attach.
static GeoFog     s_fog;
static GeoFog     s_skyFog;
static bool       s_fogOn;
static uint32_t   s_fogColour;
static float      s_depthNear = TRACK_NEAR;
static float      s_depthFar  = TRACK_FAR;

static void render_epoly(ePoly* p, TextureInfo* info, int flags);
static void transfer_zbuffer_rect(uint8_t* dst, int x, int y, int w, int h);
static float depth_of_gs_z(float g);

// ------------------------------------------------------------------ helpers

static void to_c3d(const bMatrix4* m, C3D_Mtx* out)
{
    const float* row = &m->v0.x;
    int          i, c;

    // Transposed, because bMatrix4 multiplies a row vector on its left and
    // C3D_Mtx a column vector on its right, with rows 1 and 2 negated for
    // the change of view space, and C3D_FVec's lanes stored w, z, y, x.
    for (i = 0; i < 4; i++) {
        float sign = (i == 1) ? VIEW_FLIP_Y : (i == 2) ? VIEW_FLIP_Z : 1.0f;
        for (c = 0; c < 4; c++) {
            out->r[i].c[3 - c] = sign * row[c * 4 + i];
        }
    }
}

static uint8_t* read_bundle(const char* path, size_t* outLen, bool* outLinear,
                            bool preferLinear)
{
    FILE*    f = fopen(path, "rb");
    long     len;
    uint8_t* buf;
    size_t   got = 0;

    if (!f) {
        return NULL;
    }
    fseek(f, 0, SEEK_END);
    len = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (len <= 0) {
        fclose(f);
        return NULL;
    }

    // A bundle's chunks load at their own 16-byte residue -- a payload is
    // found by rounding up from its header -- and the disc reads a bundle
    // to a 128-byte boundary, so the buffer is aligned the same way and
    // every offset in the file keeps its residue in memory.
    //
    // The track bundle takes the linear heap first: the frontend's three
    // bundles hold 17.6 MB of the 28 MB malloc heap resident, and 9.1 MB
    // more does not fit in what is left. The texture files are smaller and
    // take the malloc heap first, to leave the linear heap to the uploads.
    *outLinear = preferLinear;
    buf = preferLinear ? (uint8_t*)linearMemAlign((size_t)len, 128)
                       : (uint8_t*)memalign(128, (size_t)len);
    if (!buf) {
        *outLinear = !preferLinear;
        buf = preferLinear ? (uint8_t*)memalign(128, (size_t)len)
                           : (uint8_t*)linearMemAlign((size_t)len, 128);
    }
    if (!buf) {
        fclose(f);
        return NULL;
    }
    while (got < (size_t)len) {
        size_t n = fread(buf + got, 1, (size_t)len - got, f);

        if (n == 0) {
            break;
        }
        got += n;
    }
    fclose(f);
    if (got != (size_t)len) {
        if (*outLinear) {
            linearFree(buf);
        } else {
            free(buf);
        }
        return NULL;
    }
    *outLen = (size_t)len;
    return buf;
}

// geo_open walks the bundle in file order, so the solids come out sorted
// by where their headers are and a model's Solid can be found by bisection.
static int find_solid(const TrackView* v, const void* solid)
{
    uintptr_t key = (uintptr_t)solid;
    int       lo = 0, hi = v->numSolids - 1;

    while (lo <= hi) {
        int       mid = (lo + hi) / 2;
        uintptr_t h   = (uintptr_t)v->solid[mid].header;

        if (h == key) {
            return mid;
        }
        if (h < key) {
            lo = mid + 1;
        } else {
            hi = mid - 1;
        }
    }
    return -1;
}

// ------------------------------------------------------------- the textures

static TrackTex* find_texture(TrackView* v, const TextureInfo* info)
{
    int i;

    for (i = 0; i < v->numTextures; i++) {
        if (v->texture[i].info == info) {
            return &v->texture[i];
        }
    }
    return NULL;
}

static uint32_t pow2_at_least(uint32_t n)
{
    uint32_t p = 8;

    while (p < n) {
        p <<= 1;
    }
    return p;
}

// What decides where and how a strip draws: see trackview_draw and
// georender.h's GeoBlend.
static GeoPass texture_pass(const TextureInfo* info)
{
    GeoPass p;

    p.blend        = GEO_BLEND_NONE;
    p.noDepthWrite = info->bWriteZ == 0;
    p.noAlphaTest  = info->IsAnySemitransparencyFlag
                  || info->GlossMapInAlpha;
    if (info->IsAnySemitransparencyFlag) {
        switch (info->AlphaBits) {
        case 0x48: p.blend = GEO_BLEND_ADD;      break;
        case 0x42: p.blend = GEO_BLEND_SUBTRACT; break;
        case 0x0a: p.blend = GEO_BLEND_NONE;     break;
        default:   p.blend = GEO_BLEND_ALPHA;    break;
        }
    }
    return p;
}

// A TextureInfo's pixels where the loader or a flipbook left them, at
// ImageData and PaletteData, in the shape texpack.c decodes: the record
// for the geometry, and a data range from the lower of the two. The
// record's placements are offsets into its pack's blob, and not used.
static bool texture_source(const TextureInfo* info, TexPack* tp, TexInfo* e)
{
    const uint8_t* image   = info->ImageData;
    const uint8_t* palette = info->PaletteData;
    const uint8_t* lo;
    const uint8_t* hi;

    memset(tp, 0, sizeof *tp);
    tp->info     = (const uint8_t*)info;
    tp->infoSize = TEXPACK_RECORD_SIZE;
    tp->count    = 1;
    if (!image || !texpack_get(tp, 0, e)) {
        return false;
    }
    lo = image;
    hi = image + e->pixelBytes;
    if (e->bpp != 32) {
        if (!palette) {
            return false;
        }
        lo = palette < lo ? palette : lo;
        hi = palette + e->clutBytes > hi ? palette + e->clutBytes : hi;
    }
    tp->data     = lo;
    tp->dataSize = (uint32_t)(hi - lo);
    e->pixelOff  = (uint32_t)(image - lo);
    e->clutOff   = e->bpp != 32 ? (uint32_t)(palette - lo) : 0;
    return true;
}

// The pixels `t`'s TextureInfo points at now, at `t->level`, into `out`.
static bool upload_texture(const TrackTex* t, C3D_Tex* out)
{
    TexPack  tp;
    TexInfo  e;
    uint32_t w, h;
    uint8_t  tilable = t->info->TilableUV;

    if (!texture_source(t->info, &tp, &e)
        || !texpack_level(&e, t->level, &w, &h, NULL, NULL)
        || !texpack_upload(&tp, &e, t->level, out)) {
        return false;
    }

    // Road and verge textures repeat thousands of times along a strip --
    // ST reaches 2,299 in TRACKB12 -- so the wrap is the texture's own and
    // not texpack_upload's clamp. CreateTextureContext (0x0010a160) makes
    // the GS's CLAMP register from TilableUV: WMS is 1, clamped, unless bit
    // 0 is set, and WMT the same from bit 1. A padded axis cannot repeat,
    // and keeps the clamp; one tilable texture in the track's packs is
    // padded.
    C3D_TexSetWrap(out,
                   ((tilable & 1) && w == out->width) ? GPU_REPEAT
                                                      : GPU_CLAMP_TO_EDGE,
                   ((tilable & 2) && h == out->height) ? GPU_REPEAT
                                                       : GPU_CLAMP_TO_EDGE);
    return true;
}

static TrackTex* load_texture(TrackView* v, const TextureInfo* info)
{
    TrackTex* t = find_texture(v, info);
    TexPack   tp;
    TexInfo   e;
    uint32_t  w = 0, h = 0;
    int       level;

    if (t) {
        return t;
    }
    if (v->numTextures >= TRACKVIEW_MAX_TEXTURES) {
        return NULL;
    }
    t = &v->texture[v->numTextures++];
    memset(t, 0, sizeof *t);
    t->info       = info;
    t->uvScale[0] = 1.0f;
    t->uvScale[1] = 1.0f;
    if (!texture_source(info, &tp, &e)) {
        v->missingTextures++;
        return t;
    }

    // The largest level that leaves the reserve behind. The whole track at
    // level 0 is 28.9 MB as RGBA8, which a New 3DS has room for and an Old
    // one, with the bundle resident beside it, does not.
    for (level = 0; level < (int)e.levels; level++) {
        uint32_t bytes;

        if (!texpack_level(&e, level, &w, &h, NULL, NULL)) {
            continue;
        }
        bytes = pow2_at_least(w) * pow2_at_least(h) * 4u;
        if (linearSpaceFree() >= bytes + TEX_RESERVE) {
            break;
        }
    }
    if (level >= (int)e.levels) {
        v->missingTextures++;
        return t;
    }
    t->level = (uint8_t)level;
    if (!upload_texture(t, &t->own)) {
        v->missingTextures++;
        return t;
    }
    t->tex        = t->own;
    t->ownImage   = t->image   = info->ImageData;
    t->ownPalette = t->palette = info->PaletteData;
    t->valid      = true;
    if (level > 0) {
        v->reducedTextures++;
    }

    // The image is in the top-left of a power-of-two allocation; see
    // georender.h. A level's image is the level's own size.
    t->uvScale[0] = (float)w / (float)t->own.width;
    t->uvScale[1] = (float)h / (float)t->own.height;

    // AddTexturesSorted (0x00107ee8) has eight lists and indexes them with
    // the order unchecked. The disc's orders are all 0 to 7; the port
    // clamps anything past.
    t->pass   = texture_pass(info);
    t->order  = info->RenderingOrder < 8 ? info->RenderingOrder : 7;
    t->sorted = info->ApplyAlphaSorting != 0;
    return t;
}

// The names in the solids' tables that no pack has, every solid's and not
// only the baked ones': eFixUpTables asked for each with use_default, and
// GetTextureInfo gave it the default texture, or NULL with no GLOBALB.
static void count_defaulted(TrackView* v)
{
    int i, k, j;

    for (i = 0; i < v->numSolids; i++) {
        const GeoSolid* s = &v->solid[i];

        for (k = 0; k < s->numTextures; k++) {
            const uint8_t*     entry = s->textureTable + (size_t)k * 8;
            uint32_t           hash  = bchunk_u32(entry);
            const TextureInfo* info  =
                (const TextureInfo*)(uintptr_t)bchunk_u32(entry + 4);

            if (info && info->NameHash == hash) {
                continue;
            }
            for (j = 0; j < v->defaultedHashes; j++) {
                if (v->defaulted[j] == hash) {
                    break;
                }
            }
            if (j == v->defaultedHashes
                && v->defaultedHashes < TRACKVIEW_MAX_TEXTURES) {
                v->defaulted[v->defaultedHashes++] = hash;
            }
        }
    }
}

// Entry k of a solid's texture table: the TextureInfo eFixUpTables put
// beside the name, or a replacement written over it since.
static const TextureInfo* table_texture(const GeoSolid* s, int k)
{
    return (const TextureInfo*)(uintptr_t)bchunk_u32(
        s->textureTable + (size_t)k * 8 + 4);
}

static void resolve_slot(TrackView* v, TrackSolid* r, int k,
                         const TextureInfo* info)
{
    TrackTex* t = info ? load_texture(v, info) : NULL;

    memset(&r->slot[k], 0, sizeof r->slot[k]);
    r->tex[k]             = t;
    r->slot[k].uvScale[0] = 1.0f;
    r->slot[k].uvScale[1] = 1.0f;
    if (t && t->valid) {
        r->slot[k].tex        = &t->tex;
        r->slot[k].uvScale[0] = t->uvScale[0];
        r->slot[k].uvScale[1] = t->uvScale[1];
        r->slot[k].pass       = t->pass;
    }
}

// Each of a solid's textures is the TextureInfo eFixUpTables put in its
// table beside the name.
static void resolve_textures(TrackView* v, int index)
{
    const GeoSolid* s = &v->solid[index];
    TrackSolid*     r = &v->info[index];
    int             k;

    if (s->numTextures <= 0) {
        return;
    }
    r->slot = (GeoTexture*)calloc((size_t)s->numTextures, sizeof *r->slot);
    r->tex  = (TrackTex**)calloc((size_t)s->numTextures, sizeof *r->tex);
    if (!r->slot || !r->tex) {
        free(r->slot);
        free(r->tex);
        r->slot = NULL;
        r->tex  = NULL;
        return;
    }
    for (k = 0; k < s->numTextures; k++) {
        resolve_slot(v, r, k, table_texture(s, k));
    }
}

// RenderStrips (retail 0x0010dd58) applies the model's replacement table
// to its solid's, then reads each strip's TextureInfo from the solid's
// table as it draws. So a slot follows its entry: a car's skin, its damage
// and its lights are entries that change between frames.
static void follow_table(TrackView* v, int index)
{
    const GeoSolid* s = &v->solid[index];
    TrackSolid*     r = &v->info[index];
    int             k;

    if (!r->slot || !r->tex) {
        return;
    }
    for (k = 0; k < s->numTextures; k++) {
        const TextureInfo* info = table_texture(s, k);
        const TrackTex*    t    = r->tex[k];

        if (t ? t->info != info : info != NULL) {
            resolve_slot(v, r, k, info);
        }
    }
}

// UpdateTextureAnimations moves each flipbook's records to other frames'
// pixels. A texture showing pixels it has not shown before uploads them,
// once, at its own level, and the slots draw whatever it shows now. One
// that will not upload keeps what it showed.
static void follow_flipbooks(TrackView* v)
{
    int i, k;

    for (i = 0; i < v->numTextures; i++) {
        TrackTex*      t = &v->texture[i];
        const uint8_t* image;
        const uint8_t* palette;
        TrackFrame*    f = NULL;

        if (!t->valid) {
            continue;
        }
        image   = t->info->ImageData;
        palette = t->info->PaletteData;
        if (image == t->image && palette == t->palette) {
            continue;
        }
        t->image   = image;
        t->palette = palette;
        if (image == t->ownImage && palette == t->ownPalette) {
            t->tex = t->own;
            continue;
        }
        for (k = 0; k < v->numFrames && !f; k++) {
            if (v->frame[k].owner == t && v->frame[k].image == image
                && v->frame[k].palette == palette) {
                f = &v->frame[k];
            }
        }
        if (!f) {
            if (v->numFrames >= TRACKVIEW_MAX_FRAMES
                || !upload_texture(t, &v->frame[v->numFrames].tex)) {
                v->frameFails++;
                continue;
            }
            f          = &v->frame[v->numFrames++];
            f->owner   = t;
            f->image   = image;
            f->palette = palette;
            v->frameUploads++;
        }
        t->tex = f->tex;
    }
}

// The centre of each batch's box, which is what the alpha pass sorts on.
// GetAABBZDepth (0x0010b888) takes a strip's; a batch is every strip of one
// texture, so this is the box round all of them.
static void batch_centres(TrackSolid* r)
{
    int b, k, c;

    r->centre = calloc((size_t)(r->mesh.numBatches > 0 ? r->mesh.numBatches : 1),
                       sizeof *r->centre);
    if (!r->centre) {
        return;
    }
    for (b = 0; b < r->mesh.numBatches; b++) {
        const GeoBatch* gb = &r->mesh.batch[b];
        float           mn[3] = { 1e30f, 1e30f, 1e30f };
        float           mx[3] = { -1e30f, -1e30f, -1e30f };

        if (gb->count <= 0) {
            continue;
        }
        for (k = gb->first; k < gb->first + gb->count; k++) {
            for (c = 0; c < 3; c++) {
                float p = r->mesh.vbo[k].pos[c];

                mn[c] = p < mn[c] ? p : mn[c];
                mx[c] = p > mx[c] ? p : mx[c];
            }
        }
        for (c = 0; c < 3; c++) {
            r->centre[b][c] = 0.5f * (mn[c] + mx[c]);
        }
    }
}

static void bake_solid(TrackView* v, int index)
{
    TrackSolid* r = &v->info[index];

    if (r->baked || r->failed) {
        return;
    }
    if (!georender_bake(&v->solid[index], &r->mesh)) {
        r->failed = true;
        return;
    }
    r->baked = true;
    v->bakedSolids++;
    v->bakedTris     += r->mesh.numTris;
    v->skippedStrips += r->mesh.skippedStrips;
    resolve_textures(v, index);
    batch_centres(r);
}

// ------------------------------------------------------------ other solids

// A solid that is not the track's: a car's, from CarLoader's chunks, or a
// copy eDuplicateSolid made. Its GeoSolid is over the eSolid in place, and
// it goes in v->solid and v->info past the track's. A solid freed and
// another loaded at its address is told apart by what it points at.
static bool other_is(const GeoSolid* g, const eSolid* s)
{
    return g->nameHash == s->NameHash
        && g->numStrips == s->NumStrips
        && g->stripEntries == (const uint8_t*)s->StripEntryTable
        && g->packet == (const uint8_t*)s->StripEntryDataStart
        && g->textureTable == (const uint8_t*)s->pTextureTable;
}

static void forget_solid(TrackSolid* r)
{
    georender_free(&r->mesh);
    free(r->slot);
    free(r->tex);
    free(r->centre);
    memset(r, 0, sizeof *r);
}

static bool open_other(TrackView* v, int i, const eSolid* s)
{
    int rc;

    forget_solid(&v->info[i]);
    rc = geo_open_in_place(s, s->StripEntryTable, s->StripEntryDataStart,
                           s->SizeofStripEntryData, s->pTextureTable,
                           s->NumTextureTableEntries, s->LightMaterialTable,
                           &v->solid[i]);
    if (rc != GEO_OK) {
        v->info[i].failed = true;
        v->otherFailed++;
        return false;
    }
    return true;
}

static int find_other(TrackView* v, const eSolid* s)
{
    int i, end = v->numSolids + v->numOther;

    for (i = v->numSolids; i < end; i++) {
        if (v->solid[i].header != (const uint8_t*)s) {
            continue;
        }
        if (!other_is(&v->solid[i], s) && !open_other(v, i, s)) {
            return -1;
        }
        return v->info[i].failed ? -1 : i;
    }
    if (v->numOther >= TRACKVIEW_MAX_OTHER) {
        v->otherDropped++;
        return -1;
    }
    v->numOther++;
    return open_other(v, i, s) ? i : -1;
}

// ------------------------------------------------------------ eModel::Render

// eActiveTexture's place in the frame: AddTexturesSorted (0x00107ee8) keeps
// the textures of one RenderingOrder in the order the frame first used them,
// except that one sharing an earlier one's pImageParent goes straight after
// it (pStackedActiveTexture). The port does not stack them.
static void note_use(TrackView* v, TrackTex* t)
{
    if (t->stamp != v->frameStamp) {
        t->stamp    = v->frameStamp;
        t->firstUse = v->texUses++;
    }
}

static void defer(TrackView* v, int solid, int batch, const bMatrix4* lv,
                  const C3D_Mtx* mv, const TrackTex* t, const void* light,
                  uint16_t flags)
{
    static const float none[3];
    TrackDeferred*     d;
    const float*       c;

    if (v->numDeferred >= TRACKVIEW_MAX_DEFERRED) {
        v->deferredDropped++;
        return;
    }
    d = &v->deferred[v->numDeferred];
    c = v->info[solid].centre ? v->info[solid].centre[batch] : none;
    d->modelView = *mv;
    d->light     = light;
    d->flags     = flags;
    // GetAABBZDepth: the centre through the local and view matrices, and
    // its z. A bMatrix4 multiplies the row vector on its left.
    d->depth  = c[0] * lv->v0.z + c[1] * lv->v1.z + c[2] * lv->v2.z + lv->v3.z;
    d->solid  = (uint16_t)solid;
    d->batch  = (uint8_t)batch;
    d->order  = t->order;
    d->sorted = t->sorted;
    d->texUse = t->firstUse;
    d->seq    = v->deferredSeq++;
    d->strip  = -1;
    v->numDeferred++;
    if (t->sorted) {
        v->deferredSorted++;
    }
}

// ------------------------------------------------------------- the strips

// The most vertices one strip takes here. exBeginStrip (0x00110848) takes
// 96, and the shadows' strips are fewer.
#define STRIP_MAX 128

// The strip being built: eBeginStrip (0x00110488) lays out a VU1 packet
// for `n` vertices, and eAddVertex (0x00110790), eAddColour (0x001107e0)
// and eAddUV (0x001107f8) each fill their own area of it, with a count of
// their own. The ex set (0x00110848 ..) keeps the same three in a table
// and hands them to the e set at its end.
static struct {
    TrackTex*       tex;
    bMatrix4        m;
    int             n, nv, nc, nuv;
    GeoRenderVertex v[STRIP_MAX];
} s_strip;

// eBeginStrip's packet comes from the frame memory, and 0 is none left;
// here it is the view's strip store and its lists. A texture that would
// not upload is no strip either.
static int32_t strip_begin(void* texture, int32_t n, bMatrix4* m)
{
    TrackView* v = s_draw;
    TrackTex*  t;

    s_strip.tex = NULL;
    if (v == NULL || texture == NULL || m == NULL || n < 0 || n > STRIP_MAX
        || v->numStrips >= TRACKVIEW_MAX_STRIPS
        || v->numStripVerts + n > TRACKVIEW_MAX_STRIP_VERTS
        || v->numDeferred >= TRACKVIEW_MAX_DEFERRED) {
        if (v != NULL) {
            v->stripsDropped++;
        }
        return 0;
    }
    t = load_texture(v, (const TextureInfo*)texture);
    if (t == NULL || !t->valid) {
        return 0;
    }
    memset(s_strip.v, 0, (size_t)n * sizeof s_strip.v[0]);
    s_strip.tex = t;
    s_strip.m   = *m;
    s_strip.n   = n;
    s_strip.nv  = s_strip.nc = s_strip.nuv = 0;
    return 1;
}

// exBeginStrip: at most 96. Its end cuts the strip into runs of as many
// as one packet holds, each starting on the last two of the one before;
// drawn whole, the triangles are the same.
static int32_t ex_strip_begin(void* texture, int32_t n, bMatrix4* m)
{
    if (!(n < 97)) {
        return 0;
    }
    return strip_begin(texture, n, m);
}

static void strip_add_vertex(const bVector3* p)
{
    if (s_strip.tex && s_strip.nv < s_strip.n) {
        GeoRenderVertex* q = &s_strip.v[s_strip.nv++];

        q->pos[0] = p->x;
        q->pos[1] = p->y;
        q->pos[2] = p->z;
    }
}

// The GS's RGBA, red in the low byte.
static void strip_add_colour(uint32_t c)
{
    if (s_strip.tex && s_strip.nc < s_strip.n) {
        GeoRenderVertex* q = &s_strip.v[s_strip.nc++];

        q->colour[0] = (uint8_t)c;
        q->colour[1] = (uint8_t)(c >> 8);
        q->colour[2] = (uint8_t)(c >> 16);
        q->colour[3] = (uint8_t)(c >> 24);
    }
}

static void strip_add_uv(float s, float t)
{
    if (s_strip.tex && s_strip.nuv < s_strip.n) {
        GeoRenderVertex* q = &s_strip.v[s_strip.nuv++];

        q->st[0] = s;
        q->st[1] = t;
    }
}

// eEndStrip (0x00110608) puts the packet on its texture's list, with the
// strip's matrix, or on the alpha list when the texture has
// ApplyAlphaSorting, keyed by the first vertex's z through the view's
// WorldViewMatrix -- the vertex as it is, not through the strip's matrix.
static void strip_end(void)
{
    TrackView*     v = s_draw;
    TrackTex*      t = s_strip.tex;
    TrackStrip*    s;
    TrackDeferred* d;
    bMatrix4       localView;
    const float*   p;

    s_strip.tex = NULL;
    if (v == NULL || t == NULL) {
        return;
    }
    note_use(v, t);
    s        = &v->strips[v->numStrips];
    s->tex   = t;
    s->first = (uint16_t)v->numStripVerts;
    s->count = (uint16_t)s_strip.n;
    memcpy(&v->stripVerts[v->numStripVerts], s_strip.v,
           (size_t)s_strip.n * sizeof s_strip.v[0]);
    v->numStripVerts += s_strip.n;

    d = &v->deferred[v->numDeferred++];
    memset(d, 0, sizeof *d);
    eMulMatrix(&localView, &s_strip.m, s_worldView);
    to_c3d(&localView, &d->modelView);
    p        = s_strip.v[0].pos;
    d->depth = p[0] * s_worldView->v0.z + p[1] * s_worldView->v1.z
             + p[2] * s_worldView->v2.z + s_worldView->v3.z;
    d->order  = t->order;
    d->sorted = t->sorted;
    d->texUse = t->firstUse;
    d->seq    = v->deferredSeq++;
    d->strip  = (int16_t)v->numStrips++;
    if (t->sorted) {
        v->deferredSorted++;
    }
}

static const eStripFns kStripFns = {
    strip_begin, strip_add_vertex, strip_add_colour, strip_add_uv, strip_end,
};
static const eStripFns kExStripFns = {
    ex_strip_begin, strip_add_vertex, strip_add_colour, strip_add_uv,
    strip_end,
};

static void draw_strip(TrackView* v, const TrackDeferred* d)
{
    const TrackStrip* s = &v->strips[d->strip];
    GeoTexture        gt;

    gt.tex        = (C3D_Tex*)&s->tex->tex;
    gt.uvScale[0] = s->tex->uvScale[0];
    gt.uvScale[1] = s->tex->uvScale[1];
    gt.pass       = s->tex->pass;
    georender_set_camera(&s_proj, &d->modelView);
    if (georender_draw_strip(&v->stripVerts[s->first], s->count, &gt)) {
        v->stripsDrawn++;
    }
}

// ------------------------------------------------------------- the lighter

// RenderStrips' flags for one batch (0x0010dd58): the strips' own, with 4
// when the texture holds a gloss map in its alpha, less what the call
// takes away. Render flags bit 0 takes the environment pass away, as does
// EnableEnvMap off, and bit 1 the lighter; a model drawn with no light
// context loses both, and 0x40, the road's specular. 0x200, a strip that
// crosses the screen's edge, is VU1's clipping, which the PICA does
// itself. Into the environment map, the environment pass is left out too:
// on the PS2 it read the last frame's sphere map, but here it would read
// the cube being drawn.
static uint16_t strip_flags(const GeoBatch* b, const TrackTex* t,
                            const void* light, uint32_t flags)
{
    uint16_t f      = b->flags;
    uint16_t remove = 0;

    if (t && t->info && t->info->GlossMapInAlpha) {
        f |= 4;
    }
    if (EnableEnvMap == 0 || (flags & 1u) || s_envFace) {
        remove |= 0x100;
    }
    if (flags & 2u) {
        remove |= 0x80;
    }
    if (light == NULL) {
        remove |= 0x1c0;
    }
    return (uint16_t)(f & ~remove);
}

// A batch's inputs to geolit.v.pica, from the model's eLightContext and
// its strips' eLightMaterial, as RenderStrips sends them to VU1 with each
// strip (see georender.h's GeoLighting and docs/formats/light.md). The
// material is the strips' entry in the solid's LightMaterialTable, which
// FixLightMaterialTable and ReplaceLightMaterial fill, or the default for
// an index past it; its DMA data is the race's or the frontend's by
// InGameFlag. A gloss map's strips take the gloss power and maximum for
// their specular, and its alpha from the sun's.
static void lighting_for(GeoLighting* L, const eLightContext* lc,
                         const GeoSolid* s, int material, uint16_t f)
{
    const eLightMaterial*    m = NULL;
    const eLightMaterialDma* d;
    const float*             dir = &lc->LocalDirectionMatrix.v0.x;
    const float*             clr = &lc->LocalColourMatrix.v0.x;
    const float*             env = &lc->EnvMapMatrix.v0.x;
    double                   p, bias;
    int                      i, c;

    if (material >= 0 && material < s->numLightMaterials
        && s->lightMaterialTable) {
        m = (const eLightMaterial*)(uintptr_t)bchunk_u32(
            s->lightMaterialTable + (size_t)material * 8 + 4);
    }
    if (m == NULL) {
        m = el_get_default_light_material();
    }
    d = InGameFlag ? &m->igDmaData : &m->feDmaData;

    memset(L, 0, sizeof *L);
    L->lit   = (f & 0x80) != 0;
    L->env   = (f & 0x100) != 0;
    L->gloss = (f & 4) != 0;

    // LocalDirectionMatrix has the lights' directions as its columns, and
    // LocalColourMatrix their colours as its rows, the ambient last.
    for (i = 0; i < 3; i++) {
        for (c = 0; c < 3; c++) {
            L->lightDir[i][c] = dir[c * 4 + i];
        }
        L->difClr[i][0]  = clr[i * 4 + 0] * d->DiffuseR;
        L->difClr[i][1]  = clr[i * 4 + 1] * d->DiffuseG;
        L->difClr[i][2]  = clr[i * 4 + 2] * d->DiffuseB;
        L->specClr[i][0] = clr[i * 4 + 0] * d->SpecularR;
        L->specClr[i][1] = clr[i * 4 + 1] * d->SpecularG;
        L->specClr[i][2] = clr[i * 4 + 2] * d->SpecularB;
    }
    L->ambient[0] = clr[12];
    L->ambient[1] = clr[13];
    L->ambient[2] = clr[14];
    L->ambient[3] = L->gloss ? d->GlossAlphaMin : clr[15];
    if (L->gloss) {
        L->specClr[0][3] = d->GlossAlphaRange;
    }
    L->eye[0] = lc->LocalEyePosition.x;
    L->eye[1] = lc->LocalEyePosition.y;
    L->eye[2] = lc->LocalEyePosition.z;
    L->eye[3] = 1.0f;

    // The fast pow's maximum as its fast log2: the bias is bits(max) less
    // p bits(1), so this is bits(max) / 2^23 - 127, and -127 for none.
    p    = L->gloss ? d->GlossPower : d->SpecularPower;
    bias = L->gloss ? d->GlossBias : d->SpecularBias;
    L->powParams[0] = (float)p;
    L->powParams[1] = (float)((bias + p * 1065353216.0 - 1065353216.0)
                              / 8388608.0);
    L->powParams[2] = d->SpecularMinDot;
    L->powParams[3] = d->CBVMix;

    // EnvMapMatrix's columns: a reflection times it, x and z negated, is
    // in the map's space, which geolit mirrors in x to read the cube.
    for (c = 0; c < 3; c++) {
        float sign = c == 1 ? 1.0f : -1.0f;

        L->envCol[c][0] = sign * env[0 * 4 + c];
        L->envCol[c][1] = sign * env[1 * 4 + c];
        L->envCol[c][2] = sign * env[2 * 4 + c];
    }
    L->fresnel[0] = d->FresnelMid / 128.0f;
    L->fresnel[1] = d->FresnelHalf / 128.0f;
    L->fresnel[2] = 128.0f / 255.0f;
}

static void draw_lit_batch(TrackView* v, int solid, int batch,
                           const void* light, uint16_t f)
{
    TrackSolid* r = &v->info[solid];
    GeoLighting L;

    lighting_for(&L, (const eLightContext*)light, &v->solid[solid],
                 r->mesh.batch[batch].lightMaterial, f);
    georender_draw_lit(&r->mesh, r->slot,
                       r->slot ? v->solid[solid].numTextures : 0, batch, &L);
}

// The solid an eModel draws, baked, with its table followed: the track's,
// or another's (see find_other). -1 for none.
static int model_solid(TrackView* v, eModel* m)
{
    TrackSolid* r;
    int         i;

    if (m->Solid == NULL) {
        return -1;
    }
    i = find_solid(v, m->Solid);
    if (i < 0) {
        i = find_other(v, (const eSolid*)m->Solid);
        if (i < 0) {
            return -1;
        }
    }
    r = &v->info[i];
    if (!r->baked) {
        bake_solid(v, i);
        if (!r->baked) {
            return -1;
        }
    }
    if (m->pReplacementTextureTable != NULL) {
        emodel_apply_replacement_texture_table(m);
    }
    follow_table(v, i);
    return i;
}

// eModel::Render (0x0010c7c8) returns at once for a model with no solid,
// then sets up the rigid and vertex animation and the strips' visibility
// and has RenderStrips (0x0010c8a0) put each strip on a list: the frame's
// alpha list when its texture has ApplyAlphaSorting, its texture's own
// otherwise. The port draws a solid as georender baked it, in the matrix
// the cull gave -- local to world, then the view's -- and draws at once
// only what the attach loops would draw first anyway: the order-0 textures
// that are not sorted. The rest wait for trackview_draw. A lit or
// environment-mapped batch draws alone, with the light context.
static void render_model(eModel* m, bMatrix4* matrix, void* light,
                         uint32_t flags)
{
    TrackView*  v = s_draw;
    TrackSolid* r;
    bMatrix4    localView;
    C3D_Mtx     mv;
    uint64_t    now = 0, lit = 0;
    uint16_t    f[GEO_MAX_BATCHES];
    int         i, b, numTextures;

    if (!v || m->Solid == NULL) {
        return;
    }
    i = model_solid(v, m);
    if (i < 0) {
        return;
    }
    r = &v->info[i];
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        v->cmdSkipped++;
        return;
    }
    eMulMatrix(&localView, matrix, s_worldView);
    to_c3d(&localView, &mv);
    numTextures = r->slot ? v->solid[i].numTextures : 0;
    for (b = 0; b < r->mesh.numBatches && b < GEO_MAX_BATCHES; b++) {
        const GeoBatch* gb = &r->mesh.batch[b];
        int             k  = gb->texture;
        TrackTex*       t  = (r->tex && k >= 0 && k < numTextures) ? r->tex[k]
                                                                 : NULL;

        if (gb->count <= 0) {
            continue;
        }
        if (t) {
            note_use(v, t);
        }
        f[b] = strip_flags(gb, t, light, flags);
        if (!t || (t->order == 0 && !t->sorted)) {
            if (f[b] & 0x180) {
                lit |= (uint64_t)1 << b;
            } else {
                now |= (uint64_t)1 << b;
            }
        } else {
            defer(v, i, b, &localView, &mv, t, light, f[b]);
        }
    }
    if (now || lit) {
        georender_set_camera(&s_proj, &mv);
    }
    if (now) {
        georender_draw_mask(&r->mesh, r->slot, numTextures, now);
    }
    for (b = 0; lit != 0; b++, lit >>= 1) {
        if (lit & 1u) {
            draw_lit_batch(v, i, b, light, f[b]);
        }
    }
    v->drawn++;
    v->drawnTris += r->mesh.numTris;
    if (matrix == &eMathIdentityMatrix) {
        v->drawnInPlace++;
    }

    // The frame after a jump says what it drew, by name, for the log: '*'
    // marks an object drawn where it stands.
    if (v->listFrame) {
        size_t len = strlen(v->drawList);

        if (len + 32 < sizeof v->drawList) {
            snprintf(v->drawList + len, sizeof v->drawList - len, "%s%.24s%s",
                     len ? " " : "", ((const eSolid*)m->Solid)->Name,
                     matrix == &eMathIdentityMatrix ? "*" : "");
        }
    }
}

// ------------------------------------------------------------------ loading

bool trackview_init(TrackView* v, int track)
{
    int i;

    memset(v, 0, sizeof *v);
    v->speed = 30.0f;
    v->track = track;
    snprintf(v->bundleName, sizeof v->bundleName, TRACK_BUNDLE_FORMAT, track);
    for (i = 0; i < TRACKVIEW_NUM_TEXFILES; i++) {
        snprintf(v->texName[i], sizeof v->texName[i], kTexFormats[i], track);
        v->hasTexFile[i] = gamedata_exists(v->texName[i]);
    }
    v->hasBundle = gamedata_exists(v->bundleName);
    if (!v->hasBundle) {
        snprintf(v->note, sizeof v->note, "no %s", v->bundleName);
        return false;
    }
    snprintf(v->note, sizeof v->note, "not loaded");
    return true;
}

// The disc's tracks are TRACKB11 to TRACKB66: a location, then which of
// its six. Retail's has locations 1 to 4 and 6; the demo's TRACKB12 alone.
#define TRACK_FIRST 11
#define TRACK_LAST  66

int trackview_next_track(int track, int step)
{
    char name[TRACKVIEW_NAME_MAX];
    int  n = track;
    int  i;

    for (i = 0; i <= TRACK_LAST - TRACK_FIRST; i++) {
        n += step;
        if (n > TRACK_LAST) {
            n = TRACK_FIRST;
        } else if (n < TRACK_FIRST) {
            n = TRACK_LAST;
        }
        if (n % 10 < 1 || n % 10 > 6) {
            continue;
        }
        if (n == track) {
            break;
        }
        snprintf(name, sizeof name, TRACK_BUNDLE_FORMAT, n);
        if (gamedata_exists(name)) {
            return n;
        }
    }
    return track;
}

bool trackview_switch(TrackView* v, int track)
{
    uint8_t* shared[TRACKVIEW_MAX_SHARED];
    size_t   sharedLen[TRACKVIEW_MAX_SHARED];
    int      numShared = v->numShared;
    bool     ok;
    int      i;

    for (i = 0; i < numShared; i++) {
        shared[i]    = v->shared[i];
        sharedLen[i] = v->sharedLen[i];
    }
    trackview_free(v);
    ok = trackview_init(v, track);
    for (i = 0; i < numShared; i++) {
        trackview_share_bundle(v, shared[i], sharedLen[i]);
    }
    return ok && trackview_load(v);
}

bool trackview_share_bundle(TrackView* v, uint8_t* data, size_t len)
{
    if (!data || v->numShared >= TRACKVIEW_MAX_SHARED) {
        return false;
    }
    v->shared[v->numShared]    = data;
    v->sharedLen[v->numShared] = len;
    v->numShared++;
    return true;
}

// How far whole top-level chunks run from `data`. LoadChunks stops only on
// reaching the end it is given exactly, so it is given this.
static size_t whole_chunks(const uint8_t* data, size_t len)
{
    const uint8_t* c   = data;
    const uint8_t* end = data + len;

    while (c + 8 <= end) {
        uint32_t size = bchunk_u32(c + 4);

        if (size > (uint32_t)(end - c) - 8u) {
            break;
        }
        c += 8 + size;
    }
    return (size_t)(c - data);
}

// The packs in the bundles the UI already holds, GLOBALB.BUN and
// INGAMEB.BUN: the boot and LOADING_TRACK_COMMON's, loaded before anything
// of the track's. Slot 2's loader is offered every top-level chunk and
// takes the packs and flipbooks; the rest of those bundles is the UI's.
static void load_shared_packs(TrackView* v)
{
    int i;

    for (i = 0; i < v->numShared; i++) {
        uint8_t* c   = v->shared[i];
        uint8_t* end = c + whole_chunks(c, v->sharedLen[i]);

        for (; c < end; c += 8 + bchunk_u32(c + 4)) {
            if (v->numSharedChunks < TRACKVIEW_MAX_SHARED_CHUNKS
                && loader_texture_pack(c)) {
                v->sharedChunk[v->numSharedChunks++] = c;
            }
        }
    }
}

// The track's texture files, after its bundle: each is a ResourceFile,
// loaded whole through LoadChunks and followed by PostLoadFixup, which
// BeginGameFlowLoadingTrackSpecific's eDisableFixUpTables keeps from
// fixing the tables up until the End of loading does.
static void load_texture_files(TrackView* v)
{
    char   path[GAMEDATA_MAX_PATH];
    bNode* n;
    int    i;

    for (i = 0; i < TRACKVIEW_NUM_TEXFILES; i++) {
        if (!v->hasTexFile[i]
            || !gamedata_path(v->texName[i], path, sizeof path)) {
            continue;
        }
        v->texData[i] = read_bundle(path, &v->texLen[i], &v->texLinear[i],
                                    false);
        if (!v->texData[i]) {
            continue;
        }
        v->texChunkLen[i] = whole_chunks(v->texData[i], v->texLen[i]);
        load_chunks(v->texData[i], (int32_t)v->texChunkLen[i]);
        post_load_fixup();
    }
    for (n = TexturePackList.next; n != &TexturePackList; n = n->next) {
        v->numPacks++;
    }
    for (n = TextureAnimPackList.next; n != &TextureAnimPackList;
         n = n->next) {
        v->numAnims += ((TextureAnimPack*)(void*)n)->NumTextureAnims;
    }
}

// BeginGameFlowUnloadingTrackSpecific's FindResourceFile(3) and
// UnloadResourceFile, over the viewer's three files. FindResourceFile walks
// ResourceFileList from its tail, so the newest goes first: TEX<n>LOCATION,
// TEX<n>TRACK, the bundle. ~ResourceFile (0x0018fa50) is UnloadChunks, the
// bFree, then PostLoadFixup.
static TrackView* s_unloading;

static void* find_track_file(int type)
{
    TrackView* v = s_unloading;
    int        i;

    (void)type;
    for (i = TRACKVIEW_NUM_TEXFILES - 1; i >= 0; i--) {
        if (v->texData[i]) {
            return &v->texData[i];
        }
    }
    return v->data ? (void*)&v->data : NULL;
}

static void unload_track_file(void* file)
{
    TrackView* v = s_unloading;

    if (file == (void*)&v->data) {
        unload_chunks(v->data, (int32_t)v->chunkLen);
        if (v->dataLinear) {
            linearFree(v->data);
        } else {
            free(v->data);
        }
        v->data = NULL;
        v->len  = 0;
    } else {
        int i = (int)((uint8_t**)file - v->texData);

        unload_chunks(v->texData[i], (int32_t)v->texChunkLen[i]);
        if (v->texLinear[i]) {
            linearFree(v->texData[i]);
        } else {
            free(v->texData[i]);
        }
        v->texData[i] = NULL;
    }
    post_load_fixup();
}

// The shared bundles' packs, which the game keeps for the next race; the
// viewer takes them out again, in the reverse order.
static void unload_shared_packs(TrackView* v)
{
    int i;

    for (i = v->numSharedChunks - 1; i >= 0; i--) {
        unloader_texture_pack(v->sharedChunk[i]);
    }
    v->numSharedChunks = 0;
}

// The bundle's top level as LoadChunks will walk it, loading nothing: how
// far whole chunks run, and the scenery's sections and zones for the note.
// The walk stops only on reaching its end exactly, so a file cut short in
// a chunk would take it past the buffer; it is given what the chunks
// cover, which on a whole file is all of it.
static size_t count_chunks(TrackView* v)
{
    uint8_t* c   = v->data;
    uint8_t* end = v->data + v->len;

    while (c + 8 <= end) {
        uint32_t type = bchunk_u32(c);
        uint32_t size = bchunk_u32(c + 4);

        if (size > (uint32_t)(end - c) - 8u) {
            break;
        }
        if (type == SCENERY_CONTAINER_ID) {
            v->numSections++;
        } else if (type == VISIBLE_ZONE_ID) {
            v->numZones += (int)(size / sizeof(VisibleZone));
            v->zoneChunk = c;
        }
        c += 8 + size;
    }
    return (size_t)(c - v->data);
}

static void set_camera(TrackView* v, float dt)
{
    bVector3 eye, target, up;
    bMatrix4 m;
    float    cp = cosf(v->pitch);

    eye.x    = v->pos[0];
    eye.y    = v->pos[1];
    eye.z    = v->pos[2];
    eye.pad  = 0.0f;
    target.x = eye.x + cp * cosf(v->yaw);
    target.y = eye.y + cp * sinf(v->yaw);
    target.z = eye.z + sinf(v->pitch);
    target.pad = 0.0f;
    up.x = 0.0f;
    up.y = 0.0f;
    up.z = 1.0f;
    up.pad = 0.0f;
    eCreateLookAtMatrix(&m, &eye, &target, &up);
    camera_set_matrix(&Player1Camera, &m, dt);
}

// A stop is a point on racing route 1, a twenty-fourth of the way round
// apart: on the road, at its elevation plus an eye, looking along it.
// Zone centres were the first try and are not on the road -- the object
// nearest one is as often a tree's reflection under a lake as the ground,
// and four of the first five stops came out under the water.
static void jump_to_stop(TrackView* v, int stop)
{
    TrackRoute*      r = trmgr_get_route(&TheTrackRouteManager, TRACKVIEW_ROUTE);
    TrackRoutePoint* p;
    int              i;

    if (!r || r->NumPoints <= 0 || v->numStops <= 0) {
        return;
    }
    stop = ((stop % v->numStops) + v->numStops) % v->numStops;
    i    = (int)((int64_t)stop * r->NumPoints / v->numStops);
    p    = troute_get_point(r, i);
    v->stop   = stop;
    v->pos[0] = p->Position.x;
    v->pos[1] = p->Position.y;
    v->pos[2] = p->Elevation + EYE_HEIGHT;
    v->yaw    = atan2f(p->Direction.y, p->Direction.x);
    v->pitch  = -0.08f;
    v->listPending = true;
}

// SetScreenBuffers' share (0x00105b78): the frame's scissor on
// MainDraw0Context, and player 1's aspect ratios -- the image's NTSC pair,
// VIDEO_MODE 1. MaybeChangeViewMode cuts player 1's scissor from the frame's
// and makes view 1 active; with nothing on any mover list the mode is 0,
// which draws player 1 alone, as 1 does.
static void setup_view(void)
{
    eRenderTarget* rt = eGetRenderTarget(1);

    MainDraw0Context->ScissorW = ScreenWidth;
    MainDraw0Context->ScissorH = ScreenHeight;
    rt->AspectRatioX   = 1.0f;
    rt->AspectRatioY   = 1.08f;
    rt->AspectRatio2DX = 0.8f;
    rt->AspectRatio2DY = 0.94f;
    // The PICA's depth buffer is 24 bits, as PSMZ24's is, so the sun draws
    // at a MaxZ of 16777215.
    rt->ZBufferMode    = GS_PSMZ24;
    MaybeChangeViewMode();
}

// Back to what trackview_init left: the tables and the bundle freed. An
// attached bundle is the flow's, and stays where it is.
static void drop_bundle(TrackView* v)
{
    free(v->solid);
    free(v->info);
    free(v->texture);
    v->solid     = NULL;
    v->info      = NULL;
    v->texture   = NULL;
    v->numSolids = 0;
    if (v->attached) {
        v->attached = false;
    } else if (v->data && v->dataLinear) {
        linearFree(v->data);
    } else {
        free(v->data);
    }
    v->data = NULL;
    v->len  = 0;
}

// eInitEngine's shares that nothing else has needed yet: the model pool,
// and the frame memory the view matrices and the cull's object matrices
// come out of. eframe_malloc does not know a buffer that failed from one
// that was never made, so a failed one is freed again, which leaves every
// frame allocation returning NULL.
static bool engine_ready(TrackView* v)
{
    emodel_init_slot_pool();
    esolid_init_slot_pool();
    if (!FrameMemoryBuffer[0]) {
        eAllocateFrameMallocBuffers(EFRAME_INIT_SIZE);
        if (!FrameMemoryBuffer[0] || !FrameMemoryBuffer[1]) {
            eFreeFrameMallocBuffers();
            snprintf(v->note, sizeof v->note, "no frame memory");
            return false;
        }
    }
    if (!eModelSlotPool) {
        snprintf(v->note, sizeof v->note, "no eModelSlotPool");
        return false;
    }
    return true;
}

// The viewer's tables over v->data, and its solids found in it, in order.
static bool open_solids(TrackView* v)
{
    int rc, i;

    v->solid   = (GeoSolid*)calloc(TRACKVIEW_MAX_SOLIDS + TRACKVIEW_MAX_OTHER,
                                   sizeof *v->solid);
    v->info    = (TrackSolid*)calloc(TRACKVIEW_MAX_SOLIDS + TRACKVIEW_MAX_OTHER,
                                     sizeof *v->info);
    v->texture = (TrackTex*)calloc(TRACKVIEW_MAX_TEXTURES, sizeof *v->texture);
    if (!v->solid || !v->info || !v->texture) {
        snprintf(v->note, sizeof v->note, "out of memory for the tables");
        return false;
    }

    rc = geo_open(v->data, v->len, &v->list, v->solid, TRACKVIEW_MAX_SOLIDS);
    if (rc != GEO_OK) {
        snprintf(v->note, sizeof v->note, "geo_open: %s", geo_error(rc));
        return false;
    }
    v->numSolids = v->list.numSolids;
    for (i = 1; i < v->numSolids; i++) {
        if ((uintptr_t)v->solid[i].header <= (uintptr_t)v->solid[i - 1].header) {
            snprintf(v->note, sizeof v->note, "solids out of order at %d", i);
            return false;
        }
    }
    return true;
}

// Once the track is in: the solids the models were linked to, the names
// GetTextureInfo defaulted, and every model's solid baked.
static void bake_models(TrackView* v)
{
    bNode* n;
    int    i;

    for (n = SolidList.next; n != &SolidList; n = n->next) {
        v->linkedSolids++;
    }
    count_defaulted(v);

    for (n = ModelList.next; n != &ModelList; n = n->next) {
        eModel* m = (eModel*)(void*)n;

        v->numModels++;
        if (m->Solid == NULL) {
            v->modelsWithoutSolid++;
            continue;
        }
        i = find_solid(v, m->Solid);
        if (i >= 0) {
            bake_solid(v, i);
        }
    }
}

bool trackview_load(TrackView* v)
{
    char     path[GAMEDATA_MAX_PATH];
    uint64_t t0 = osGetTime();

    if (v->loaded || !v->hasBundle) {
        return v->loaded;
    }
    if (!engine_ready(v)) {
        return false;
    }

    if (!gamedata_path(v->bundleName, path, sizeof path)) {
        snprintf(v->note, sizeof v->note, "path too long");
        return false;
    }
    v->data = read_bundle(path, &v->len, &v->dataLinear, true);
    if (!v->data) {
        snprintf(v->note, sizeof v->note, "cannot read %s", v->bundleName);
        return false;
    }
    if (!open_solids(v)) {
        drop_bundle(v);
        return false;
    }

    // The game's order. The shared bundles' packs are in first; then
    // BeginGameFlowLoadingTrackSpecific sets eDisableFixUpTables and loads
    // the bundle -- a ResourceFile: the whole of it through the
    // LoaderTable, then PostLoadFixup -- and LoadingTrackSpecificPart4 the
    // two texture files the same way; and the End of loading clears it and
    // runs eFixUpTables once over everything, before starting the track's
    // systems. The models find their solids by name as LoaderScenery makes
    // them, and the bundle has its solid lists first. The seams are
    // eInitEngine's to set; they are set here too so that the viewer does
    // not depend on the order main() does things in.
    if (!gEModelInitFn) {
        gEModelInitFn = emodel_init;
    }
    if (!gEModelDestroyFn) {
        gEModelDestroyFn = emodel_delete;
    }
    if (!gGetTextureInfoFn) {
        gGetTextureInfoFn = texturepack_get_texture_info;
    }
    load_shared_packs(v);
    eDisableFixUpTables = 1;
    gEModelRenderFn = render_model;
    gEPolyRenderFn  = render_epoly;
    gEStripFns      = kStripFns;
    gExStripFns     = kExStripFns;
    gETransferZBufferRectFn = transfer_zbuffer_rect;
    v->chunkLen = count_chunks(v);
    load_chunks(v->data, (int32_t)v->chunkLen);
    post_load_fixup();
    load_texture_files(v);
    EndGameFlowLoadingTrackSpecific();
    bake_models(v);

    camera_set_field_of_view(&Player1Camera, TRACK_FOV);
    camera_set_near_z(&Player1Camera, TRACK_NEAR);
    camera_set_far_z(&Player1Camera, TRACK_FAR);
    setup_view();
    {
        TrackRoute* r = trmgr_get_route(&TheTrackRouteManager, TRACKVIEW_ROUTE);

        v->numStops = (r && r->NumPoints > 0) ? TRACKVIEW_STOPS : 0;
    }
    jump_to_stop(v, 0);
    set_camera(v, 1.0f / 60.0f);

    v->loaded = true;
    v->loadMs = (int)(osGetTime() - t0);
    snprintf(v->note, sizeof v->note, "%d sections, %d zones, %d ms",
             v->numSections, v->numZones, v->loadMs);
    return true;
}

bool trackview_attach(TrackView* v, uint8_t* data, size_t len)
{
    uint64_t t0 = osGetTime();

    if (v->loaded) {
        return true;
    }
    if (!data || !engine_ready(v)) {
        return false;
    }
    v->data     = data;
    v->len      = len;
    v->attached = true;
    if (!open_solids(v)) {
        drop_bundle(v);
        return false;
    }
    gEModelRenderFn = render_model;
    gEPolyRenderFn  = render_epoly;
    gEStripFns      = kStripFns;
    gExStripFns     = kExStripFns;
    gETransferZBufferRectFn = transfer_zbuffer_rect;
    v->chunkLen = count_chunks(v);
    bake_models(v);
    setup_view();

    v->loaded = true;
    v->loadMs = (int)(osGetTime() - t0);
    snprintf(v->note, sizeof v->note, "%d sections, %d zones, attached",
             v->numSections, v->numZones);
    return true;
}

void trackview_free(TrackView* v)
{
    int i;

    // The Begin of unloading closes what the End started and hands the
    // track's files back through the two seams. Nothing is chunk-loaded
    // unless the load got as far as `loaded`. The viewer is not a game
    // flow state, so the Begin is run with no flow: it does not move the
    // flow on or unload the frontend's speech.
    if (v->loaded && !v->attached) {
        void* (*find)(int)     = gFindResourceFileFn;
        void  (*unload)(void*) = gUnloadResourceFileFn;
        BGameFlow* flow        = gTrackFlowGameFlow;

        s_unloading           = v;
        gFindResourceFileFn   = find_track_file;
        gUnloadResourceFileFn = unload_track_file;
        gTrackFlowGameFlow    = NULL;
        BeginGameFlowUnloadingTrackSpecific();
        // Back to the resource system's (main.c), which the car loader
        // and the race coordinator unload through too.
        gFindResourceFileFn   = find;
        gUnloadResourceFileFn = unload;
        gTrackFlowGameFlow    = flow;
        s_unloading           = NULL;
    }
    if (v->loaded) {
        v->linkedSolids = 0;
        if (gEModelRenderFn == render_model) {
            gEModelRenderFn = NULL;
        }
        if (gEPolyRenderFn == render_epoly) {
            gEPolyRenderFn = NULL;
        }
        if (gEStripFns.Begin == strip_begin) {
            memset(&gEStripFns, 0, sizeof gEStripFns);
        }
        if (gExStripFns.Begin == ex_strip_begin) {
            memset(&gExStripFns, 0, sizeof gExStripFns);
        }
        if (gETransferZBufferRectFn == transfer_zbuffer_rect) {
            gETransferZBufferRectFn = NULL;
        }
        s_numSunRects = 0;
    }
    if (v->info) {
        for (i = 0; i < v->numSolids + v->numOther; i++) {
            forget_solid(&v->info[i]);
        }
    }
    unload_shared_packs(v);
    if (v->texture) {
        for (i = 0; i < v->numTextures; i++) {
            if (v->texture[i].valid) {
                C3D_TexDelete(&v->texture[i].own);
            }
        }
    }
    for (i = 0; i < v->numFrames; i++) {
        C3D_TexDelete(&v->frame[i].tex);
    }
    drop_bundle(v);
    memset(v, 0, sizeof *v);
}

// -------------------------------------------------------------------- input

static float pad_axis(int raw)
{
    if (raw > PAD_DEAD || raw < -PAD_DEAD) {
        float f = (float)raw / PAD_FULL;

        return f > 1.0f ? 1.0f : f < -1.0f ? -1.0f : f;
    }
    return 0.0f;
}

void trackview_input(TrackView* v, uint32_t kDown, uint32_t kHeld, int cpx,
                     int cpy, float dt)
{
    float fx, fy, cp, fwd[3], right[3], step;
    int   i;

    if (!v->loaded) {
        return;
    }

    if (kDown & KEY_DUP) {
        v->speed = v->speed * 2.0f > SPEED_MAX ? SPEED_MAX : v->speed * 2.0f;
    }
    if (kDown & KEY_DDOWN) {
        v->speed = v->speed * 0.5f < SPEED_MIN ? SPEED_MIN : v->speed * 0.5f;
    }
    if (kDown & KEY_DRIGHT) {
        jump_to_stop(v, v->stop + 1);
    }
    if (kDown & KEY_DLEFT) {
        jump_to_stop(v, v->stop - 1);
    }

    // The face buttons are the right stick the handheld does not have.
    if (kHeld & KEY_Y) v->yaw += LOOK_SPEED * dt;
    if (kHeld & KEY_A) v->yaw -= LOOK_SPEED * dt;
    if (kHeld & KEY_X) v->pitch += LOOK_SPEED * dt;
    if (kHeld & KEY_B) v->pitch -= LOOK_SPEED * dt;
    if (v->pitch > PITCH_LIMIT) v->pitch = PITCH_LIMIT;
    if (v->pitch < -PITCH_LIMIT) v->pitch = -PITCH_LIMIT;

    cp       = cosf(v->pitch);
    fwd[0]   = cp * cosf(v->yaw);
    fwd[1]   = cp * sinf(v->yaw);
    fwd[2]   = sinf(v->pitch);
    // Looking down +x in a right-handed world with z up, the right is -y:
    // that is where eCreateLookAtMatrix puts view +x.
    right[0] = sinf(v->yaw);
    right[1] = -cosf(v->yaw);
    right[2] = 0.0f;

    fx   = pad_axis(cpx);
    fy   = pad_axis(cpy);
    step = v->speed * dt;
    for (i = 0; i < 3; i++) {
        v->pos[i] += (fwd[i] * fy + right[i] * fx) * step;
    }
    if (kHeld & KEY_R) v->pos[2] += step;
    if (kHeld & KEY_L) v->pos[2] -= step;

    set_camera(v, dt);
}

// --------------------------------------------------------------------- draw

// The two attach loops' order. AttachSolidPolys (0x0010a7f0) goes first
// and draws every texture's own list, the textures in RenderingOrder and,
// within one, in the order the frame met them; AttachAlphaPolys
// (0x0010a4c0) then draws the alpha list as SortAlphaKeys leaves it --
// RenderingOrder up and, within one, the farthest first, ties the last
// added first, since the list is built back to front from a stable radix
// sort. A texture's own list keeps its strips in the order they came.
static int compare_deferred(const void* pa, const void* pb)
{
    const TrackDeferred* a = (const TrackDeferred*)pa;
    const TrackDeferred* b = (const TrackDeferred*)pb;

    if (a->sorted != b->sorted) {
        return a->sorted ? 1 : -1;
    }
    if (a->order != b->order) {
        return a->order < b->order ? -1 : 1;
    }
    if (!a->sorted) {
        if (a->texUse != b->texUse) {
            return a->texUse < b->texUse ? -1 : 1;
        }
        return a->seq < b->seq ? -1 : a->seq > b->seq;
    }
    if (a->depth != b->depth) {
        return a->depth > b->depth ? -1 : 1;
    }
    return a->seq > b->seq ? -1 : a->seq < b->seq;
}

// With `alpha` false, AttachSolidPolys alone: the unsorted batches draw
// and the sorted ones stay for a later call. With it true, both lists.
static void draw_deferred(TrackView* v, bool alpha)
{
    int i, kept = 0;

    qsort(v->deferred, (size_t)v->numDeferred, sizeof v->deferred[0],
          compare_deferred);
    for (i = 0; i < v->numDeferred; i++) {
        const TrackDeferred* d = &v->deferred[i];
        TrackSolid*          r;

        if (d->sorted && !alpha) {
            v->deferred[kept++] = *d;
            continue;
        }
        if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
            v->cmdSkipped++;
            continue;
        }
        if (d->strip >= 0) {
            draw_strip(v, d);
            continue;
        }
        r = &v->info[d->solid];
        georender_set_camera(&s_proj, &d->modelView);
        if (d->flags & 0x180) {
            draw_lit_batch(v, d->solid, d->batch, d->light, d->flags);
        } else {
            georender_draw_mask(&r->mesh, r->slot,
                                r->slot ? v->solid[d->solid].numTextures : 0,
                                (uint64_t)1 << d->batch);
        }
    }
    v->numDeferred = kept;
}

// ---------------------------------------------------------------- the sun

// The GS's screen is 4096 pixels across with the target in the middle.
#define GS_CENTRE 2048.0f

// A target pixel's place on the top screen: the view's projection, which
// has the cull's width across 400 pixels and square pixels. The PS2's y is
// AspectRatioY times its x, so both come off here.
static void target_to_screen(float x, float y, int targetW, int targetH,
                             float aspX, float aspY, float* sx, float* sy)
{
    float k = 400.0f / (float)targetW;

    *sx = 200.0f + (x - (float)(targetW >> 1)) * k / aspX;
    *sy = 120.0f + (y - (float)(targetH >> 1)) * k / aspY;
}

// A SunPoly's own ALPHA_1, where any other poly takes its texture's. C is
// As in every one StuffSun makes.
static uint8_t poly_blend(const ePoly* p)
{
    if (p->AlphaA == EPOLY_ALPHA_CS && p->AlphaD == EPOLY_ALPHA_CD) {
        if (p->AlphaB == EPOLY_ALPHA_CD) {
            return GEO_BLEND_ALPHA;
        }
        if (p->AlphaB == EPOLY_ALPHA_ZERO) {
            return GEO_BLEND_ADD;
        }
    }
    if (p->AlphaA == EPOLY_ALPHA_ZERO && p->AlphaB == EPOLY_ALPHA_CS
        && p->AlphaD == EPOLY_ALPHA_CD) {
        return GEO_BLEND_SUBTRACT;
    }
    return GEO_BLEND_NONE;
}

// ePoly::Render (retail 0x0010fa68), for the quads StuffSun and
// StuffSunGlare make; epoly.h has what it does. The PS2 puts the packet on
// its texture's list, or on the alpha sort by V0's z, and draws it with
// the rest; the sun's textures are order 7, the last list, so here it is
// drawn at once, after the scenery. Each vertex's GS Z is its z, which the
// GS tests GEQUAL. The sun's and the glare's four are always one: MaxZ,
// past any Z the scenery writes, which draws with no depth test; or the
// sun's first layer's 1, which here draws at the PICA's depth for it, the
// clear's 0, and so only over the sky.
static void render_epoly(ePoly* p, TextureInfo* info, int flags)
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    eRenderTarget*       rt = s_quadTarget;
    TrackView*           v  = s_draw;
    TrackTex*            t;
    GeoTexture           gt;
    GeoRenderVertex      q[4];
    float                halfW, off, depth, mx = 0.0f, my = 0.0f;
    uint8_t              blend;
    bool                 drawn;
    int                  i;

    // `flags` keeps the packet in the poly's frame memory, for a poly
    // drawn again unchanged; nothing here needs it.
    (void)flags;
    if (info == NULL || v == NULL || rt == NULL) {
        return;
    }
    if (p->SunPoly) {
        p->ApplyAspectRatio = 0;
    }
    t = load_texture(v, info);
    if (t == NULL || !t->valid) {
        v->sunQuadsFailed++;
        return;
    }
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        v->cmdSkipped++;
        return;
    }
    gt.tex        = &t->tex;
    gt.uvScale[0] = t->uvScale[0];
    gt.uvScale[1] = t->uvScale[1];
    gt.pass       = t->pass;

    halfW = (float)(rt->ScissorW >> 1);
    off   = GS_CENTRE - halfW;
    memset(q, 0, sizeof q);
    for (i = 0; i < 4; i++) {
        const int n = kStrip[i];
        float     x = p->Vertices[n].x;
        float     y = p->Vertices[n].y;
        float     w = p->UVs[n][2] != 0.0f ? p->UVs[n][2] : 1.0f;

        if (p->ApplyAspectRatio) {
            x *= rt->AspectRatio2DX;
            y *= rt->AspectRatio2DY;
        } else if (halfW < x) {
            x += -0.5f;
        }
        // XYZ2 is 12.4 fixed point on the GS's screen, and Render drops
        // the fraction.
        x = floorf(x + off) - off;
        y = floorf(y + (GS_CENTRE - (float)(rt->ScissorH >> 1)))
          - (GS_CENTRE - (float)(rt->ScissorH >> 1));
        mx += x * 0.25f;
        my += y * 0.25f;
        target_to_screen(x, y, rt->ScissorW, rt->ScissorH, rt->AspectRatioX,
                         rt->AspectRatioY, &q[i].pos[0], &q[i].pos[1]);
        q[i].st[0] = p->UVs[n][0] / w;
        q[i].st[1] = p->UVs[n][1] / w;
        memcpy(q[i].colour, p->Colours[n], 4);
    }

    // Render turns the blend on for a semitransparent texture alone.
    if (!info->IsAnySemitransparencyFlag) {
        blend = GEO_BLEND_NONE;
    } else if (p->SunPoly) {
        blend = poly_blend(p);
    } else {
        blend = t->pass.blend;
    }
    // Every fragment of a screen quad has the one depth, where its Z says.
    depth = depth_of_gs_z((float)ee_trunc_w(p->Vertices[0].z));
    drawn = georender_draw_quad(q, &gt, blend, depth);
    if (!drawn) {
        v->sunQuadsFailed++;
        return;
    }
    v->sunQuads++;
    v->sunAt[0] = mx;
    v->sunAt[1] = my;
    v->sunAlpha = p->Colours[0][3];
}

// eTransferZBufferRect (0x00110610): the PS2 puts the rect on a queue that
// runs once the frame is drawn, and so here, where trackview_read_depth
// reads it at the next frame's start.
static void transfer_zbuffer_rect(uint8_t* dst, int x, int y, int w, int h)
{
    eRenderTarget* rt = s_quadTarget;
    SunRect*       r;

    if (rt == NULL || s_numSunRects >= NUM_SUN_ZBUFFERS || w <= 0 || h <= 0
        || w * h > SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE) {
        return;
    }
    r = &s_sunRects[s_numSunRects++];
    r->dst     = (uint32_t*)(void*)dst;
    r->x       = x;
    r->y       = y;
    r->w       = w;
    r->h       = h;
    r->targetW = rt->ScissorW;
    r->targetH = rt->ScissorH;
    r->aspX    = rt->AspectRatioX;
    r->aspY    = rt->AspectRatioY;
    if (s_draw) {
        s_draw->sunRectX = x;
        s_draw->sunRectY = y;
    }
}

// A top-screen pixel's word in the 240 by 400 buffers citro3d renders to:
// the screen on its side, its x down the buffer and its y across from the
// right, in 8 by 8 tiles in rows of 30, and each tile in Morton order.
static uint32_t tiled_index(int x, int y)
{
    uint32_t bx = (uint32_t)(239 - y);
    uint32_t by = (uint32_t)x;
    uint32_t m  = (bx & 1u) | ((by & 1u) << 1) | ((bx & 2u) << 1)
                | ((by & 2u) << 2) | ((bx & 4u) << 2) | ((by & 4u) << 3);

    return ((by >> 3) * (240u / 8u) + (bx >> 3)) * 64u + m;
}

// The GS's Z for a depth the PICA wrote. The PICA's is the Z-buffer's,
// the view's depth d as near (far - d) / ((far - near) d): 1 at the near
// plane, 0 at the far. The GS's is the same hyperbola from ZMin to ZMax --
// floats in [2, 4), whose mantissas are the Z, 16 and 0x0ff000.
static float gs_z_of_depth(float t)
{
    const float zmin = (ZMin - 2.0f) * 4194304.0f;
    const float zmax = (ZMax - 2.0f) * 4194304.0f;

    return zmin + (zmax - zmin) * t;
}

// And for the fog's u, the view's depth as (far - d) / (far - near), whose
// Z-buffer depth is near u / d.
static float gs_z_of(float u)
{
    float d = s_depthFar - u * (s_depthFar - s_depthNear);

    return gs_z_of_depth(d > 0.0f ? s_depthNear * u / d : 1.0f);
}

// The fog's palette is looked up by the Z as a PSMZ16S read gives it,
// where past 0xffff is taken as 0xffff.
static uint16_t gs_z16(float z)
{
    return z >= 65535.0f ? 0xffffu : (uint16_t)z;
}

// And the sun's rects by the Z as retail's transfer gives it, 32 bits a
// pixel of which StuffSun takes the low 24; all it asks is whether they
// are under 2. What the clear left, and the sky did not write, is 0.
static uint32_t gs_z24(float z)
{
    return z >= 16777215.0f ? 0xffffffu : (uint32_t)z;
}

static uint32_t gs_z(uint32_t d24)
{
    if (d24 == 0) {
        return 0;
    }
    return gs_z24(gs_z_of_depth((float)d24 / 16777215.0f));
}

// gs_z_of_depth backwards: the PICA's depth whose GS Z is g, or -1 for a
// Z at or past the nearest the scenery reaches, which passes against
// anything. A Z under the farthest is the depth 0, which only the clear
// has.
static float depth_of_gs_z(float g)
{
    const float zmin = (ZMin - 2.0f) * 4194304.0f;
    const float zmax = (ZMax - 2.0f) * 4194304.0f;
    float       t    = (g - zmin) / (zmax - zmin);

    if (!(t < 1.0f)) {
        return -1.0f;
    }
    return t <= 0.0f ? 0.0f : t;
}

// ------------------------------------------------------------------ the fog

// The fog's fractions: step j for the view's depth j / GEO_FOG_STEPS, as
// u = (far - d) / (far - near). The fraction is efog_keep's for the GS's Z
// there, or for a Z of 0 for the sky's -- the dome leaves the Z as the
// clear did, and the sun draws where the dome shows. False when the fog's
// texture could not be made.
static bool fog_fill(GeoFog* fog, const uint32_t* palette,
                     const FogModeInfo* mode, bool sky)
{
    float keep[GEO_FOG_STEPS + 1];
    int   j;

    for (j = 0; j <= GEO_FOG_STEPS; j++) {
        float    u = (float)j / (float)GEO_FOG_STEPS;
        uint16_t z = sky ? 0 : gs_z16(gs_z_of(u));

        keep[j] = efog_keep(palette, mode, z);
    }
    return georender_fog_fill(fog, keep);
}

// eAttachFog's seam, where the image builds the fog's sprite: the one
// view's palette as the fog's fractions. A palette the fog cannot be, a
// colour by a fraction, is left off, and counted, as is one whose texture
// could not be made.
static void fog_attach(eView* view, const uint32_t* palette,
                       const FogModeInfo* mode)
{
    static const float at[TRACKVIEW_FOG_SAMPLES] = {
        250.0f, 500.0f, 1000.0f, 2000.0f, 4000.0f
    };
    TrackView* v = s_draw;
    uint32_t   colour;
    int        k;

    if (view->ID != EVIEW_ID_PLAYER1 || v == NULL) {
        return;
    }
    v->fogViews++;
    if (!efog_colour(palette, mode, &colour)) {
        v->fogUnfit++;
        return;
    }
    if (!fog_fill(&s_fog, palette, mode, false)
        || !fog_fill(&s_skyFog, palette, mode, true)) {
        v->fogUnfit++;
        return;
    }
    s_fogColour = colour;
    s_fogOn     = true;
    for (k = 0; k < TRACKVIEW_FOG_SAMPLES; k++) {
        float u = (s_depthFar - at[k]) / (s_depthFar - s_depthNear);

        v->fogKeep[k] = efog_keep(palette, mode, gs_z16(gs_z_of(u)));
    }
    v->fogSkyKeep = efog_keep(palette, mode, 0);
}

// eDisplayFrame's fog (0x00113420), which the PS2 lays over the frame once
// it is drawn; see efog.h. Its palette depends on nothing drawn, so here
// it is made first, and georender lays it on as each thing is drawn.
static void fog_frame(TrackView* v, eView* view)
{
    const WeatherQuery* q = &CachedWeatherQueries[view->ID];
    int                 k;

    s_fogOn     = false;
    s_fogColour = 0;
    v->fogViews = 0;
    v->fogUnfit = 0;
    for (k = 0; k < TRACKVIEW_FOG_SAMPLES; k++) {
        v->fogKeep[k] = 1.0f;
    }
    v->fogSkyKeep = 1.0f;
    s_depthNear   = view->NearZ;
    s_depthFar    = view->FarZ;
    gEFogAttachFn = fog_attach;
    if (InGameFlag && eattach_depth_into_alpha()) {
        eattach_fog();
    }
    v->fogOn     = s_fogOn;
    v->fogMode   = efog_view_mode(view);
    v->fogColour = s_fogColour;
    v->fogAmount = q->Fog;
    v->fogStart  = q->FogStart;
    v->fogRegion = q->RegionR;
    v->fogHits   = (q->Region0 != NULL) + (q->Region1 != NULL)
                 + (q->Region2 != NULL);
    v->fogFrame  = eFrameCounter;
}

// The probe: the colour and depth words at 15 screen points, five across
// and three down, for a check of tiled_index against a screenshot.
static void probe(TrackView* v, const C3D_RenderTarget* target)
{
    const uint32_t* colour = (const uint32_t*)target->frameBuf.colorBuf;
    const uint32_t* depth  = (const uint32_t*)target->frameBuf.depthBuf;
    size_t          at     = 0;
    int             i;

    at += (size_t)snprintf(v->probe, sizeof v->probe, "probe");
    for (i = 0; i < 15 && at < sizeof v->probe; i++) {
        int      x = 40 + (i % 5) * 80;
        int      y = 30 + (i / 5) * 90;
        uint32_t n = tiled_index(x, y);

        at += (size_t)snprintf(v->probe + at, sizeof v->probe - at,
                               " %d,%d %08lx/%08lx", x, y,
                               (unsigned long)(colour ? colour[n] : 0),
                               (unsigned long)(depth ? depth[n] : 0));
    }
}

void trackview_read_depth(TrackView* v, C3D_RenderTarget* target)
{
    const uint32_t* depth;
    int             r, i, j;

    v->sunRects = 0;
    v->sunSky   = 0;
    if (target == NULL || target->frameBuf.depthBuf == NULL
        || target->frameBuf.width != 240 || target->frameBuf.height != 400) {
        s_numSunRects = 0;
        return;
    }
    if (v->probePending) {
        v->probePending = false;
        probe(v, target);
    }
    depth = (const uint32_t*)target->frameBuf.depthBuf;
    for (r = 0; r < s_numSunRects; r++) {
        const SunRect* q = &s_sunRects[r];

        for (j = 0; j < q->h; j++) {
            for (i = 0; i < q->w; i++) {
                int      px = q->x + i;
                int      py = q->y + j;
                uint32_t z  = 0xffffffu;

                // StuffSun keeps the rect on the target; a target under
                // 33 across does not, and none of what is off it counts.
                if (px >= 0 && py >= 0 && px < q->targetW
                    && py < q->targetH) {
                    float sx, sy;
                    int   ix, iy;

                    target_to_screen((float)px + 0.5f, (float)py + 0.5f,
                                     q->targetW, q->targetH, q->aspX,
                                     q->aspY, &sx, &sy);
                    ix = (int)floorf(sx);
                    iy = (int)floorf(sy);
                    ix = ix < 0 ? 0 : ix > 399 ? 399 : ix;
                    iy = iy < 0 ? 0 : iy > 239 ? 239 : iy;
                    z  = gs_z(depth[tiled_index(ix, iy)] & 0xffffffu);
                    if (z < 2) {
                        v->sunSky++;
                    }
                }
                q->dst[j * q->w + i] = z;
            }
        }
        v->sunRects++;
    }
    s_numSunRects = 0;
}

// The environment views' clip volume ends 32 out (gp-24208): the cull's
// matrices, which eDisplayFrame makes again before it (0x00113020), have
// it as their e_farz.
#define ENV_CLIP_FAR 32.0f

// eDisplayFrame's start, for the views there are: new frame memory, the
// view mode, UpdateEnvironmentMapCameras (0x00112a34) when
// EnableEnvMapViews is set, each view's matrices, a cull info per view,
// and the cull. The matrices the cull hands Render live in the frame
// memory, and the draw is done with them before the next swap.
static void begin_frame(TrackView* v)
{
    eView* view = eGetView(EVIEW_ID_PLAYER1);
    int    i;

    // The GPU is done with the last frame by now, so the screen quads'
    // ring starts again, before any view of this one draws a quad.
    georender_quads_rewind();
    eSwapFrameMallocBuffers();
    MaybeChangeViewMode();
    if (EnableEnvMapViews) {
        update_environment_map_cameras();
    }
    eview_set_max_z(view->pRenderTarget0);
    eview_calculate_view_matrices(view, 0.0f, 0.0f, 0.0f);
    for (i = 0; i < 6; i++) {
        eView* ev = EnvMapViews[i];

        if (ev != NULL && ev->pCamera != NULL) {
            eview_calculate_view_matrices(ev, 0.0f, 0.0f, ENV_CLIP_FAR);
        }
    }
    scenery_cull_setup_views(&v->cull, InGameFlag);
    scenery_do_culling(&v->cull);
    v->drawInfos = 0;
    for (i = 0; i < v->cull.NumCullInfos; i++) {
        v->drawInfos += (int)(v->cull.SceneryCullInfos[i].pCurrentDrawInfo
                              - v->cull.SceneryCullInfos[i].pFirstDrawInfo);
    }
    v->frameBegun = true;
}

// A new texture order for a view: the frame's first use of each texture
// starts again, and so do the lists.
static void begin_view(TrackView* v)
{
    v->numDeferred     = 0;
    v->deferredSeq     = 0;
    v->deferredSorted  = 0;
    v->deferredDropped = 0;
    v->numStrips       = 0;
    v->numStripVerts   = 0;
    v->texUses         = 0;
    if (++v->frameStamp == 0) {
        v->frameStamp = 1;
    }
}

// A point of eCreateEnvMapPrims' strips (0x00118810) for the fold. On the
// map, it is where the GS puts it: s and t across target 14's 256 pixels,
// cut to a whole pixel as the strip's XYZ2 is, and moved half a pixel, as
// the PICA takes a pixel's colour at its centre where the GS takes it at
// its corner. The texel is the cube's, by the grid's direction mirrored as
// the cube is (see eenvmap.h); a back grid's is face 2's at its u and v,
// whose direction create_ref_sample_table's face 2 gives.
static GeoFoldVertex fold_vertex(const EnvMapRefSample* e, int g)
{
    GeoFoldVertex o;
    float         px = (float)(int)(e->s * 256.0f - 128.0f + 2048.0f)
                       - 1920.0f;
    float         py = (float)(int)(e->t * 256.0f - 128.0f + 2048.0f)
                       - 1920.0f;

    o.pos[0] = (px + 0.5f) / 128.0f - 1.0f;
    o.pos[1] = 1.0f - (py + 0.5f) / 128.0f;
    if (g < 6) {
        o.dir[0] = -e->x;
        o.dir[1] = e->y;
        o.dir[2] = e->z;
    } else {
        o.dir[0] = -(1.0f - 2.0f * e->u);
        o.dir[1] = 2.0f * e->v - 1.0f;
        o.dir[2] = -1.0f;
    }
    return o;
}

// Each grid's 5 by 5 quads as two triangles each, in the strips' order.
bool trackview_envmap_init(void)
{
    GeoFoldVertex* mesh = (GeoFoldVertex*)malloc(
        GEO_FOLD_GRIDS * GEO_FOLD_GRID_VERTS * sizeof(GeoFoldVertex));
    GeoFoldVertex* o    = mesh;
    bool           ok;
    int            g, r, c;

    if (mesh == NULL) {
        return false;
    }
    for (g = 0; g < GEO_FOLD_GRIDS; g++) {
        EnvMapRefSample (*T)[ENVMAP_SAMPLE_SIDE] = EnvMapRefSampleTable[g];

        for (r = 0; r < 5; r++) {
            for (c = 0; c < 5; c++) {
                GeoFoldVertex a = fold_vertex(&T[r][c], g);
                GeoFoldVertex b = fold_vertex(&T[r + 1][c], g);
                GeoFoldVertex d = fold_vertex(&T[r][c + 1], g);
                GeoFoldVertex e = fold_vertex(&T[r + 1][c + 1], g);

                *o++ = a;
                *o++ = b;
                *o++ = d;
                *o++ = b;
                *o++ = d;
                *o++ = e;
            }
        }
    }
    ok = georender_envmap_init(64, 256, mesh);
    free(mesh);
    return ok;
}

// The environment views' share of eDisplayFrame: each active one's sky,
// with the Z writes off and its matrices' own projection (0x00112e78),
// and its scenery (0x00113168), with no fog. Retail does the views a pass
// at a time with the players'; here each face is drawn whole before the
// top screen is. The cars are not drawn into them -- RenderCars runs for
// views 1 to 3 alone. Then eCreateEnvMapPrims (0x00113594) folds the
// views drawn into the sphere map. A face whose view is not active keeps
// what it last drew, as retail's target does, and is not folded; one that
// has never drawn is cleared to its target's grey.
void trackview_draw_envmap(TrackView* v)
{
    unsigned views = 0;
    int      i;

    if (!v->loaded || !FrameMemoryBuffer[0]) {
        return;
    }
    begin_frame(v);
    v->envFaces = 0;
    v->envDrawn = 0;
    if (!EnableEnvMapViews || !EnvMapCentreValid) {
        return;
    }
    s_draw      = v;
    s_envFace   = true;
    v->listFrame = false;
    georender_set_light(0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f);
    georender_set_fog(NULL, 0);
    for (i = 0; i < 6; i++) {
        eView*         view = EnvMapViews[i];
        eRenderTarget* rt;
        uint32_t       grey, clear;
        int            face, drawn;

        if (view == NULL || view->pCamera == NULL) {
            continue;
        }
        rt    = view->pRenderTarget0;
        face  = EnvMapCubeFace[i];
        grey  = rt->BackgroundColour & 0xffu;
        clear = grey << 24 | grey << 16 | grey << 8 | 0xffu;
        if (!view->Active || !rt->Active) {
            if (!georender_envmap_face_done(face)) {
                georender_envmap_face(face, clear, false);
            }
            continue;
        }
        if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
            continue;
        }
        georender_envmap_face(face, clear, true);
        Mtx_Persp(&s_proj, C3D_AngleFromDegrees(90.0f), 1.0f, view->NearZ,
                  view->FarZ, false);
        s_worldView  = view->WorldViewMatrix;
        begin_view(v);
        drawn = v->drawn;

        georender_set_zwrite(false);
        StuffSky(view);
        draw_deferred(v, true);
        georender_set_zwrite(true);
        scenery_stuff_scenery(&v->cull, view);
        draw_deferred(v, false);
        draw_deferred(v, true);

        v->envFaces++;
        v->envDrawn += v->drawn - drawn;
        views |= 1u << i;
    }
    s_envFace = false;
    s_draw    = NULL;
    georender_envmap_fold(views);
}

void trackview_draw(TrackView* v)
{
    eView* view = eGetView(EVIEW_ID_PLAYER1);
    float  tanx, fovy;

    if (!v->loaded || !FrameMemoryBuffer[0]) {
        return;
    }

    // The frame's start, unless trackview_draw_envmap has made it.
    if (!v->frameBegun) {
        begin_frame(v);
    }
    v->frameBegun = false;

    // The top screen's width is the cull's: the cull's half-width at unit
    // depth is half the scissor over H, and the height follows from 5:3.
    tanx = (float)view->pRenderTarget0->ScissorW * 0.5f / view->H;
    fovy = 2.0f * atanf(tanx * 240.0f / 400.0f);
    Mtx_PerspTilt(&s_proj, fovy, 400.0f / 240.0f, view->NearZ, view->FarZ,
                  false);
    // Prelit: the vertex colour and nothing else.
    georender_set_light(0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f);

    s_draw        = v;
    s_worldView   = view->WorldViewMatrix;
    v->drawn        = 0;
    v->drawnTris    = 0;
    v->drawnInPlace = 0;
    v->cmdSkipped   = 0;
    v->stripsDrawn  = 0;
    v->stripsDropped = 0;
    v->listFrame    = v->listPending;
    v->listPending  = false;
    if (v->listFrame) {
        v->drawList[0] = 0;
    }
    begin_view(v);
    // The fog, which georender lays on by the view's depth between its
    // planes. The depth buffer is the Z-buffer's.
    fog_frame(v, view);
    georender_set_depth_range(view->NearZ, view->FarZ);

    // eDisplayFrame's sky (0x00112a38 .. 0x00112b0c): the Z writes off,
    // StuffSky for the view, and what it put on the lists attached and
    // drawn before any of the scenery. Then the Z writes back on.
    georender_set_fog(s_fogOn ? &s_skyFog : NULL, s_fogColour);
    georender_set_zwrite(false);
    StuffSky(view);
    draw_deferred(v, true);
    georender_set_zwrite(true);
    v->skyDrawn    = v->drawn;

    georender_set_fog(s_fogOn ? &s_fog : NULL, s_fogColour);
    scenery_stuff_scenery(&v->cull, view);

    // Then StuffSun (0x00112ecc), after DrawNisObjects, which has nothing
    // to draw here. Its quads draw at once; see render_epoly. Then the
    // scenery's chain ends with AttachSolidPolys alone (0x001134a4).
    v->sunQuads       = 0;
    v->sunQuadsFailed = 0;
    georender_set_fog(s_fogOn ? &s_skyFog : NULL, s_fogColour);
    s_quadTarget = view->pRenderTarget0;
    StuffSun(view);
    s_quadTarget = NULL;
    georender_set_fog(s_fogOn ? &s_fog : NULL, s_fogColour);
    draw_deferred(v, false);

    // The cars' chain (0x0011363c): RenderCars for the view, and its
    // AttachSolidPolys. Then AttachAlphaPolys (0x001137cc) draws the
    // scenery's alpha list and the cars' together. RenderFrontEndCars
    // draws nothing in a race.
    render_cars(view);
    draw_deferred(v, false);
    draw_deferred(v, true);
    if (v->listFrame) {
        v->probePending = true;
    }
    s_draw = NULL;

    // eDisplayFrame's end (0x00113cd4), once the frame is on its way: the
    // flipbooks' next frames, for the next frame to draw.
    UpdateTextureAnimations();
    follow_flipbooks(v);

    // citro2d draws the bottom screen next and sets only what it needs:
    // the alpha test is put back off and the blend back to its own, and
    // the fog off.
    georender_set_fog(NULL, 0);
    C3D_AlphaTest(false, GPU_ALWAYS, 0);
    C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA,
                   GPU_ONE_MINUS_SRC_ALPHA, GPU_SRC_ALPHA,
                   GPU_ONE_MINUS_SRC_ALPHA);
    if ((int)gpuCmdBufOffset > v->cmdPeakWords) {
        v->cmdPeakWords = (int)gpuCmdBufOffset;
    }
    if (FrameMallocFailed) {
        v->frameMallocFails++;
    }
    // eDisplayFrame's very end (0x00113d2c): the frame is counted.
    eFrameCounter++;
}
