#include "trackview.h"

#include <malloc.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <3ds.h>

#include "acidsys.h"
#include "bchunk.h"
#include "bchunkload.h"
#include "cammover.h"
#include "cardamage.h"
#include "carrenderinfo.h"
#include "eefpu.h"
#include "eanim.h"
#include "eenvmap.h"
#include "efocus.h"
#include "efog.h"
#include "eframe.h"
#include "elight.h"
#include "elightflare.h"
#include "emath.h"
#include "emodel.h"
#include "epoly.h"
#include "esolid.h"
#include "eview.h"
#include "eviewmatrix.h"
#include "fecar.h"
#include "frameprof.h"
#include "gamedata.h"
#include "capture.h"
#include "coresample.h"
#include "hangwatch.h"
#include "radialblur.h"
#include "scenery.h"
#include "skids.h"
#include "sky.h"
#include "stomper.h"
#include "sun.h"
#include "sundraw.h"
#include "texpack.h"
#include "texturepack.h"
#include "trackflow.h"
#include "trackroute.h"
#include "weatherman.h"
#include "worldobject.h"

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

// VRAM a texture upload leaves behind. The render targets are all made at
// boot (main.c: the screens', the envmap's and the mirror's), so the rest
// of VRAM's 6 MB is the textures' but for this.
#define VRAM_RESERVE (512u * 1024u)

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
static const eZRange*  s_zRange = &ZRanges[1]; // the view's target's
static bool            s_envFace;   // drawing into the environment map
static bool            s_mirrorView; // drawing into the rear-view mirror

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

// The Flailer polys handed to ePoly::Render since trackview_draw_flailer_
// polys last ran: TrackMap's, which eDisplayFrame makes after the HUD's
// Flailer layers (Player::RenderTrackMap, from 0x00113c38) and attaches
// at its end. They wait here for the screen the minimap is on.
typedef struct {
    ePoly        poly;
    TextureInfo* info;
    int32_t      z;             // the GS Z's order; see flailer_z
} FlailerPoly;

static FlailerPoly s_flailer[TRACKVIEW_FLAILER_POLYS];
static int         s_numFlailer;
static int         s_flailerDropped;

// The fog: its fractions for the view's palette, by depth, one for the
// scenery and one for the sky and the sun; the colour; and the planes the
// last frame's view was between. See fog_attach.
static GeoFog     s_fog;
static GeoFog     s_skyFog;
static bool       s_fogOn;
static uint32_t   s_fogColour;
static float      s_depthNear = TRACK_NEAR;
static float      s_depthFar  = TRACK_FAR;

// The GS's screen is 4096 pixels across with the target in the middle.
#define GS_CENTRE 2048.0f

static void render_epoly(ePoly* p, TextureInfo* info, int flags);
static void render_epoly_3d(ePoly* p, TextureInfo* info, bMatrix4* m,
                            int flags);
static void free_blur_previous(void);
static void free_grey_copy(void);
static void free_focus_copies(void);
static void transfer_zbuffer_rect(uint8_t* dst, int x, int y, int w, int h);
static float depth_of_gs_z(float g);
static void target_to_screen(float x, float y, int targetW, int targetH,
                             float aspX, float aspY, float* sx, float* sy);

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

// The list's entries are found by their TextureInfo in open-addressed
// buckets, not by a scan of the list from the front: the scan was a
// profile's 1.7% (TASKS 46). load_texture puts a TextureInfo in the list
// once, so the entry found is the one the scan found.
static unsigned tex_bucket(const TextureInfo* info)
{
    return ((uint32_t)(uintptr_t)info * 2654435761u)
           >> (32 - TRACKVIEW_TEX_BUCKET_BITS);
}

static TrackTex* find_texture(TrackView* v, const TextureInfo* info)
{
    unsigned h;

    for (h = tex_bucket(info); v->texBucket[h] != 0;
         h = (h + 1) & (TRACKVIEW_TEX_BUCKETS - 1)) {
        int k = v->texBucket[h] - 1;

        if (k < v->numTextures && v->texture[k].info == info) {
            return &v->texture[k];
        }
    }
    return NULL;
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

// A bake's or an upload's time onto its total, and onto the longest's.
static void add_ticks(TrackView* v, uint64_t* total, uint64_t t0)
{
    uint64_t d = svcGetSystemTick() - t0;

    *total += d;
    if (d > v->worstTicks) {
        v->worstTicks = d;
    }
}

// The prepare's uploads go to VRAM while it has room, and the rest to the
// linear heap. VRAM is the faster for the GPU to read, and the linear heap
// is what the race runs short of (Session 52). citro3d copies into VRAM
// with the GPU's transfer engine, which a frame queues for its end
// (texpack_upload_chain_vram), and the prepare runs between frames.
static bool vram_room(const TrackView* v, size_t bytes)
{
    return v->vramOk && vramSpaceFree() >= bytes + VRAM_RESERVE;
}

static bool in_vram(const C3D_Tex* tex)
{
    uintptr_t a = (uintptr_t)tex->data;

    return a >= OS_VRAM_VADDR && a < OS_VRAM_VADDR + OS_VRAM_SIZE;
}

static bool upload_now(TrackView* v, const TrackTex* t, C3D_Tex* out,
                       int fmt, bool single);

// The pixels `t`'s TextureInfo points at now, at `t->level`, into `out`:
// the mip chain, or with `single` the one level when the chain will not
// fit. The chain is in the smallest format that holds its texels
// (texpack_format), which is one a flipbook's frames each have their own
// of. `fmt` is that format when the caller has it, or -1: finding it is a
// pass over every texel.
static bool upload_texture(TrackView* v, const TrackTex* t, C3D_Tex* out,
                           int fmt, bool single)
{
    uint64_t t0 = svcGetSystemTick();
    bool     ok = upload_now(v, t, out, fmt, single);

    v->uploads++;
    add_ticks(v, &v->uploadTicks, t0);
    if (v->prepared) {
        size_t len = strlen(v->lateNames);

        if (len + 28 < sizeof v->lateNames) {
            snprintf(v->lateNames + len, sizeof v->lateNames - len, "%s%.24s",
                     len ? " " : "", t->info->DebugName);
        }
    }
    return ok;
}

static bool upload_now(TrackView* v, const TrackTex* t, C3D_Tex* out,
                       int fmt, bool single)
{
    TexPack       tp;
    TexInfo       e;
    uint32_t      w, h;
    uint8_t       tilable = t->info->TilableUV;
    TexPackFormat f;
    size_t        bytes;

    if (!texture_source(t->info, &tp, &e)
        || !texpack_level(&e, t->level, &w, &h, NULL, NULL)) {
        return false;
    }
    f     = fmt >= 0 ? (TexPackFormat)fmt : texpack_format(&tp, &e, t->level);
    bytes = texpack_chain_bytes(&e, t->level, f);
    if (vram_room(v, bytes)
        && texpack_upload_chain_vram(&tp, &e, t->level, f, out)) {
        v->vramTextures++;
        v->vramKB += (uint32_t)(bytes >> 10);
    } else if (!texpack_upload_chain_as(&tp, &e, t->level, f, out)) {
        if (!single || !texpack_upload(&tp, &e, t->level, out)) {
            return false;
        }
        v->unchainedTextures++;
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

// A texture whose TextureInfo had no pixels yet is tried again once it
// has them: loader_texture_pack writes ImageData into a record that the
// tables may already point at. So is one the cache let go of, and one
// that found no room, from its retryAt on. One that had pixels and would
// not upload for another reason is not tried again until it is forgotten.
static bool retry_texture(const TrackView* v, const TrackTex* t)
{
    return !t->valid && t->info->ImageData != NULL
           && (t->ownImage == NULL || t->evicted
               || (t->retryAt != 0 && v->cacheClock >= t->retryAt));
}

// ------------------------------------------------------- the texture cache
//
// The linear heap holds what the race draws, and on a big map with many
// cars it can run short: a texture that would not fit was uploaded at a
// smaller mip level, or not at all, and never tried again. Now room is
// made first, at the full size, by letting go of the textures drawn
// longest ago: the prepare's guesses that nothing drew first, then the
// least recently drawn. A texture let go of keeps its pixels in its pack,
// in the main heap, and is uploaded again the next time it is asked for:
// its slots let go of it too, so follow_table resolves them again before
// the model draws (retry_texture).
//
// A texture drawn this frame or the last is never let go of: the GPU may
// still read it. begin_frame, and the frontend's draw, move the clock. One
// that found no room even so is tried again a second later, when the view
// has moved on.
#define CACHE_KEEP_FRAMES  2u
#define CACHE_RETRY_FRAMES 30u

static void touch(TrackView* v, TrackTex* t)
{
    t->lastUse = v->cacheClock;
}

static bool evictable(const TrackView* v, const TrackTex* t)
{
    return t->valid && t->lastUse + CACHE_KEEP_FRAMES <= v->cacheClock;
}

// `t`'s pixels let go of: its own chain and its flipbook frames', and the
// solids' slots that draw it.
static void evict(TrackView* v, TrackTex* t)
{
    int i, k;

    C3D_TexDelete(&t->own);
    for (i = 0; i < v->numFrames;) {
        if (v->frame[i].owner == t) {
            C3D_TexDelete(&v->frame[i].tex);
            v->frame[i] = v->frame[--v->numFrames];
        } else {
            i++;
        }
    }
    for (i = 0; i < v->numSolids + v->numOther; i++) {
        TrackSolid* r = &v->info[i];

        if (!r->slot || !r->tex) {
            continue;
        }
        for (k = 0; k < v->solid[i].numTextures; k++) {
            if (r->tex[k] == t) {
                r->slot[k].tex = NULL;
            }
        }
    }
    memset(&t->own, 0, sizeof t->own);
    memset(&t->tex, 0, sizeof t->tex);
    t->valid   = false;
    t->evicted = true;
    v->evictedTextures++;
}

// The texture in the linear heap drawn longest ago let go of. False when
// none may go. One in VRAM gives the linear heap nothing back.
static bool evict_lru(TrackView* v)
{
    TrackTex* lru = NULL;
    int       i;

    for (i = 0; i < v->numTextures; i++) {
        TrackTex* t = &v->texture[i];

        if (evictable(v, t) && !in_vram(&t->own)
            && (!lru || t->lastUse < lru->lastUse)) {
            lru = t;
        }
    }
    if (!lru) {
        return false;
    }
    evict(v, lru);
    return true;
}

// Room for `bytes` on top of TEX_RESERVE, made by letting go of the
// textures drawn longest ago. False when what may go is not enough; what
// went has gone.
static bool make_room(TrackView* v, size_t bytes)
{
    while (linearSpaceFree() < bytes + TEX_RESERVE) {
        if (!evict_lru(v)) {
            return false;
        }
    }
    return true;
}

// `t` into `out` as upload_texture puts it, with room made for the chain.
// Room by the count is not room in one piece: the heap's holes may each be
// too small for it. So the least recently drawn go, one at a time, until
// it goes in; its one level alone is the last resort. `t` must not be one
// that may go, and `out` must not be in v->frame, which evict compacts.
static bool upload_room(TrackView* v, const TrackTex* t, C3D_Tex* out,
                        int fmt)
{
    bool ok = upload_texture(v, t, out, fmt, false);

    while (!ok && evict_lru(v)) {
        ok = upload_texture(v, t, out, fmt, false);
    }
    return ok || upload_texture(v, t, out, fmt, true);
}

static TrackTex* load_texture(TrackView* v, const TextureInfo* info)
{
    TrackTex* t = find_texture(v, info);
    TexPack   tp;
    TexInfo   e;
    uint32_t  w = 0, h = 0;
    int       level;
    int       fmt = -1;
    size_t    bytes = 0;

    if (t && !retry_texture(v, t)) {
        touch(v, t);
        return t;
    }
    if (!t) {
        unsigned b;

        if (v->numTextures >= TRACKVIEW_MAX_TEXTURES) {
            return NULL;
        }
        // The list is never past half the buckets, so one is empty.
        for (b = tex_bucket(info); v->texBucket[b] != 0;
             b = (b + 1) & (TRACKVIEW_TEX_BUCKETS - 1)) {
        }
        t = &v->texture[v->numTextures++];
        v->texBucket[b] = (uint16_t)v->numTextures;
    }
    memset(t, 0, sizeof *t);
    t->info       = info;
    t->uvScale[0] = 1.0f;
    t->uvScale[1] = 1.0f;
    if (!texture_source(info, &tp, &e)) {
        v->missingTextures++;
        return t;
    }
    t->ownImage = info->ImageData;

    // The largest level whose chain leaves the reserve behind, in the
    // format it is stored in. A track's textures at level 0 are 34-42 MB
    // with their chains as RGBA8, and 29-34 MB so (2026-10-08). The cache
    // makes room for level 0 first; a smaller level is the last resort.
    for (level = 0; level < (int)e.levels; level++) {
        if (!texpack_level(&e, level, &w, &h, NULL, NULL)) {
            continue;
        }
        fmt   = (int)texpack_format(&tp, &e, level);
        bytes = texpack_chain_bytes(&e, level, (TexPackFormat)fmt);
        if (linearSpaceFree() >= bytes + TEX_RESERVE || vram_room(v, bytes)
            || (level == 0 && make_room(v, bytes))) {
            break;
        }
    }
    if (level >= (int)e.levels) {
        v->missingTextures++;
        t->retryAt = v->cacheClock + CACHE_RETRY_FRAMES;
        return t;
    }
    t->level = (uint8_t)level;
    if (!upload_room(v, t, &t->own, fmt)) {
        v->missingTextures++;
        t->retryAt = v->cacheClock + CACHE_RETRY_FRAMES;
        return t;
    }
    touch(v, t);
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
    // The solid's own textures are in use first: making room for one it
    // lacks lets go of none it is about to draw.
    for (k = 0; k < s->numTextures; k++) {
        if (r->tex[k]) {
            touch(v, r->tex[k]);
        }
    }
    for (k = 0; k < s->numTextures; k++) {
        const TextureInfo* info = table_texture(s, k);
        const TrackTex*    t    = r->tex[k];

        // A retried texture another solid made valid is taken up too.
        if (t ? t->info != info
                    || (t->valid ? r->slot[k].tex != &t->tex
                                 : retry_texture(v, t))
              : info != NULL) {
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
            C3D_Tex tex;

            // One drawn of late has room made, as load_texture's do.
            if (v->numFrames >= TRACKVIEW_MAX_FRAMES
                || !(evictable(v, t) ? upload_texture(v, t, &tex, -1, true)
                                     : upload_room(v, t, &tex, -1))) {
                v->frameFails++;
                continue;
            }
            f          = &v->frame[v->numFrames++];
            f->tex     = tex;
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
                float p = r->mesh.vbo[r->mesh.ibo[k]].pos[c];

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
    uint64_t    t0;

    if (r->baked || r->failed) {
        return;
    }
    t0 = svcGetSystemTick();
    v->bakes++;
    if (!(index >= v->numSolids
          && bodydamage_walks_solid((const eSolid*)v->solid[index].header)
              ? georender_bake_editable(&v->solid[index], &r->mesh)
              : georender_bake(&v->solid[index], &r->mesh))) {
        r->failed = true;
        v->bakesFailed++;
        add_ticks(v, &v->bakeTicks, t0);
        return;
    }
    r->baked = true;
    v->bakedSolids++;
    v->bakedTris     += r->mesh.numTris;
    v->skippedStrips += r->mesh.skippedStrips;
    batch_centres(r);
    add_ticks(v, &v->bakeTicks, t0);
    // Its textures' uploads are timed as uploads.
    resolve_textures(v, index);
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
    t->lastUse = v->cacheClock;
    if (t->stamp != v->frameStamp) {
        t->stamp    = v->frameStamp;
        t->firstUse = v->texUses++;
    }
}

static void defer(TrackView* v, int solid, int batch, const bMatrix4* lv,
                  const C3D_Mtx* mv, const TrackTex* t, const void* light,
                  uint16_t flags, const GeoRenderVertex* vbo)
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
    d->vbo       = vbo;
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
    d->sprites = -1;
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

// The most vertices strips joined into one draw take: see strip_join.
#define STRIP_JOIN_MAX 1024

// A texture's own list draws its strips in the order they came, so a strip
// with the texture and the matrix of the one just before it can go on the
// end of that one, for one draw instead of two. The join repeats that
// strip's last corner and this one's first, and the first once more after
// an odd count, which keeps this one's winding. Every triangle across the
// join has a corner twice and so no area. The skid marks' quads, an ePoly
// each as on the PS2, come this way by the hundred.
static bool strip_join(TrackView* v, const TrackTex* t, const C3D_Mtx* mv)
{
    const int        n = s_strip.n;
    TrackDeferred*   last;
    TrackStrip*      ls;
    GeoRenderVertex* o;
    int              pad;

    if (t->sorted || v->numDeferred == 0 || n < 3) {
        return false;
    }
    last = &v->deferred[v->numDeferred - 1];
    if (last->strip < 0 || last->strip != v->numStrips - 1) {
        return false;
    }
    ls  = &v->strips[last->strip];
    pad = (ls->count & 1) ? 3 : 2;
    if (ls->tex != t || ls->count < 3
        || ls->first + ls->count != v->numStripVerts
        || ls->count + pad + n > STRIP_JOIN_MAX
        || v->numStripVerts + pad + n > TRACKVIEW_MAX_STRIP_VERTS
        || memcmp(&last->modelView, mv, sizeof *mv) != 0) {
        return false;
    }
    o    = &v->stripVerts[v->numStripVerts];
    o[0] = o[-1];
    o[1] = s_strip.v[0];
    if (pad == 3) {
        o[2] = s_strip.v[0];
    }
    memcpy(o + pad, s_strip.v, (size_t)n * sizeof s_strip.v[0]);
    v->numStripVerts += pad + n;
    ls->count = (uint16_t)(ls->count + pad + n);
    v->stripsJoined++;
    return true;
}

// eEndStrip (0x00110608) puts the packet on its texture's list, with the
// strip's matrix, or on the alpha list when the texture has
// ApplyAlphaSorting, keyed by the first vertex's z through the view's
// WorldViewMatrix -- the vertex as it is, not through the strip's matrix.
// Here a strip may join the one before it instead (strip_join).
static void strip_end(void)
{
    TrackView*     v = s_draw;
    TrackTex*      t = s_strip.tex;
    TrackStrip*    s;
    TrackDeferred* d;
    bMatrix4       localView;
    C3D_Mtx        mv;
    const float*   p;

    s_strip.tex = NULL;
    if (v == NULL || t == NULL) {
        return;
    }
    note_use(v, t);
    eMulMatrix(&localView, &s_strip.m, s_worldView);
    to_c3d(&localView, &mv);
    if (strip_join(v, t, &mv)) {
        return;
    }
    s        = &v->strips[v->numStrips];
    s->tex   = t;
    s->first = (uint16_t)v->numStripVerts;
    s->count = (uint16_t)s_strip.n;
    memcpy(&v->stripVerts[v->numStripVerts], s_strip.v,
           (size_t)s_strip.n * sizeof s_strip.v[0]);
    v->numStripVerts += s_strip.n;

    d = &v->deferred[v->numDeferred++];
    memset(d, 0, sizeof *d);
    d->modelView = mv;
    p        = s_strip.v[0].pos;
    d->depth = p[0] * s_worldView->v0.z + p[1] * s_worldView->v1.z
             + p[2] * s_worldView->v2.z + s_worldView->v3.z;
    d->order  = t->order;
    d->sorted = t->sorted;
    d->texUse = t->firstUse;
    d->seq    = v->deferredSeq++;
    d->strip  = (int16_t)v->numStrips++;
    d->sprites = -1;
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

// ------------------------------------------------------------ the effects

// The sprites RenderEffects (retail 0x00128da0) hands eAttachDirectData, a
// group's packet at a time, decoded as they come: the packet is in the
// frame memory. One view draws at a time, so one store does; begin_view
// empties it. The particle pool is 1000 (afxInit) and the groups' 400.
#define SPRITE_MAX      1000
#define SPRITE_SET_MAX  400

typedef struct {
    const TrackTex* tex;
    uint16_t        first;      // in s_spriteCorners, four a sprite
    uint16_t        count;      // sprites
} SpriteSet;

static GeoRenderVertex s_spriteCorners[SPRITE_MAX * 4];
static SpriteSet       s_spriteSets[SPRITE_SET_MAX];
static int             s_numSprites;
static int             s_numSpriteSets;

// A corner's depth: its Z is the scenery's GS Z shifted down acidz (see
// acid_system_render_effects), so shifted back it is a GS Z in the units
// depth_of_gs_z takes. One nearer than the scenery reaches passes against
// anything, as on the GS; the clip volume wants the depth inside (0, 1).
static float sprite_depth(uint32_t z)
{
    float d = depth_of_gs_z((float)(z << (acidz & 31)));

    if (d < 0.0f || d > 1.0f - 1.0f / 65536.0f) {
        return 1.0f - 1.0f / 65536.0f;
    }
    return d < 1e-7f ? 1e-7f : d;
}

// eAttachDirectData (0x00110378), for RenderEffects' packets alone: the
// packet goes on its texture's list of the current target, or on the
// alpha list at depth z when the texture has ApplyAlphaSorting. Here it is
// a deferred item like a strip's, in the attach loops' order. The tag must
// be RenderEffects': NLOOP sprites with EOP, PRE with PRIM 0x54, a REGLIST
// of 10 (PRIM, RGBAQ, then ST and XYZ2 four times). Each sprite is 20
// words: RGBAQ at 2 (R in the low byte, Q 1 at 3), and corner i's S and T
// at 4 + 4i and 5 + 4i, its XYZ2 at 6 + 4i (x the low 16 bits and y the
// high, both 12.4 on the GS's screen) and its Z at 7 + 4i.
static void attach_direct_data(void* texture, float z, void* data,
                               uint16_t qwc)
{
    TrackView*      v  = s_draw;
    eRenderTarget*  rt = s_quadTarget;
    const uint32_t* w  = (const uint32_t*)data;
    TrackTex*       t;
    TrackDeferred*  d;
    SpriteSet*      set;
    float           offX, offY;
    uint32_t        n, i;
    int             c;

    if (v == NULL || rt == NULL || texture == NULL || w == NULL) {
        return;
    }
    n = w[0] & 0x7fffu;
    if ((w[0] >> 15) != 1u || w[1] != 0xa42a4000u || w[2] != 0x42424210u
        || w[3] != 0x42u || n == 0 || qwc != n * 5u + 1u) {
        v->spritesRefused++;
        return;
    }
    if (s_numSprites + (int)n > SPRITE_MAX || s_numSpriteSets >= SPRITE_SET_MAX
        || v->numDeferred >= TRACKVIEW_MAX_DEFERRED) {
        v->spritesDropped += (int)n;
        return;
    }
    t = load_texture(v, (const TextureInfo*)texture);
    if (t == NULL || !t->valid) {
        v->spritesDropped += (int)n;
        return;
    }

    offX = GS_CENTRE - (float)(rt->ScissorW >> 1);
    offY = GS_CENTRE - (float)(rt->ScissorH >> 1);
    set        = &s_spriteSets[s_numSpriteSets];
    set->tex   = t;
    set->first = (uint16_t)(s_numSprites * 4);
    set->count = (uint16_t)n;
    for (i = 0; i < n; i++) {
        const uint32_t*  sp = w + 4 + i * 20;
        GeoRenderVertex* q  = &s_spriteCorners[(s_numSprites + (int)i) * 4];

        memset(q, 0, 4 * sizeof *q);
        for (c = 0; c < 4; c++) {
            uint32_t xyz = sp[6 + 4 * c];
            float    x   = (float)(xyz & 0xffffu) * 0.0625f - offX;
            float    y   = (float)(xyz >> 16) * 0.0625f - offY;

            target_to_screen(x, y, rt->ScissorW, rt->ScissorH,
                             rt->AspectRatioX, rt->AspectRatioY,
                             &q[c].pos[0], &q[c].pos[1]);
            q[c].pos[2] = sprite_depth(sp[7 + 4 * c]);
            memcpy(&q[c].st[0], &sp[4 + 4 * c], sizeof(float));
            memcpy(&q[c].st[1], &sp[5 + 4 * c], sizeof(float));
            q[c].colour[0] = (uint8_t)sp[2];
            q[c].colour[1] = (uint8_t)(sp[2] >> 8);
            q[c].colour[2] = (uint8_t)(sp[2] >> 16);
            q[c].colour[3] = (uint8_t)(sp[2] >> 24);
        }
    }
    s_numSprites += (int)n;

    note_use(v, t);
    d = &v->deferred[v->numDeferred++];
    memset(d, 0, sizeof *d);
    d->depth   = z;
    d->order   = t->order;
    d->sorted  = t->sorted;
    d->texUse  = t->firstUse;
    d->seq     = v->deferredSeq++;
    d->strip   = -1;
    d->sprites = (int16_t)s_numSpriteSets++;
    if (t->sorted) {
        v->deferredSorted++;
    }
}

static void draw_sprites(TrackView* v, const TrackDeferred* d)
{
    const SpriteSet* s = &s_spriteSets[d->sprites];
    GeoTexture       gt;

    gt.tex        = (C3D_Tex*)&s->tex->tex;
    gt.uvScale[0] = s->tex->uvScale[0];
    gt.uvScale[1] = s->tex->uvScale[1];
    gt.pass       = s->tex->pass;
    if (georender_draw_sprites(&s_spriteCorners[s->first], s->count, &gt)) {
        v->spritesDrawn += s->count;
    } else {
        v->spritesDropped += s->count;
    }
}

// eDisplayFrame's RenderEffects (0x001134a4's loop): FrameEffects', then
// WorldEffects', for the view s_draw draws, onto its first target.
static void render_effects(eView* view)
{
    s_quadTarget         = view->pRenderTarget0;
    gEAttachDirectDataFn = attach_direct_data;
    acid_system_render_effects(&FrameEffects, view);
    acid_system_render_effects(&WorldEffects, view);
    gEAttachDirectDataFn = NULL;
    s_quadTarget         = NULL;
}

// ------------------------------------------------------------- the lighter

// RenderStrips' flags for one batch (0x0010dd58): the strips' own as they
// are now, read from the batch's first strip, with 4 when the texture holds
// a gloss map in its alpha, less what the call takes away. The strips' own
// change after the bake: a car's broken window loses 0x100 to CarDamage
// (eSolid::SetEnvironmentMapping, on every strip of its texture), and a
// repair gives it back. Render flags bit 0 takes the environment pass away, as does
// EnableEnvMap off, and bit 1 the lighter; a model drawn with no light
// context loses both, and 0x40, the road's specular. 0x200, a strip that
// crosses the screen's edge, is VU1's clipping, which the PICA does
// itself. Into the environment map, the environment pass is left out too:
// on the PS2 it read the last frame's sphere map, but here it would read
// the cube being drawn.
static uint16_t strip_flags(const GeoSolid* s, const GeoBatch* b,
                            const TrackTex* t, const void* light,
                            uint32_t flags)
{
    uint16_t f      = geo_strip_flags(s, b->strip, b->flags);
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

// The mesh a batch of `r` draws from: its own, or with `vbo` a copy of it
// that draws the posed vertices there, each batch whole, since the boxes
// its clusters hold are the bind pose's.
static const GeoMesh* mesh_for(const TrackSolid* r,
                               const GeoRenderVertex* vbo, GeoMesh* copy)
{
    if (vbo == NULL) {
        return &r->mesh;
    }
    *copy          = r->mesh;
    copy->vbo      = (GeoRenderVertex*)vbo;
    copy->clusters = NULL;
    return copy;
}

static void draw_lit_batch(TrackView* v, int solid, int batch,
                           const void* light, uint16_t f,
                           const GeoRenderVertex* vbo)
{
    TrackSolid* r     = &v->info[solid];
    uint32_t    words = gpuCmdBufOffset;
    GeoLighting L;
    GeoMesh     posed;

    CoreSamplePart = CS_PART_LIT;
    lighting_for(&L, (const eLightContext*)light, &v->solid[solid],
                 r->mesh.batch[batch].lightMaterial, f);
    georender_draw_lit(mesh_for(r, vbo, &posed), r->slot,
                       r->slot ? v->solid[solid].numTextures : 0, batch, &L);
    FrameProfDraw.models[s_envFace ? 1 : s_mirrorView ? 2 : 0]
                        [FRAMEPROF_M_LIT_WORDS] += gpuCmdBufOffset - words;
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
    // The walk's changes, which the draws this frame all see: the GPU runs
    // none of them before C3D_FrameEnd.
    if (r->dirty && r->mesh.edit != NULL) {
        uint64_t t0 = svcGetSystemTick();

        georender_refresh(&v->solid[i], &r->mesh);
        free(r->centre);
        batch_centres(r);
        r->dirty = false;
        v->refreshes++;
        v->refreshTicks += svcGetSystemTick() - t0;
    }
    if (m->pReplacementTextureTable != NULL) {
        emodel_apply_replacement_texture_table(m);
    }
    follow_table(v, i);
    return i;
}

// eModel::Render (0x0010dc80) returns at once for a model with no solid,
// then sets up the rigid and vertex animation (emodel_setup_animation) and
// the strips' visibility and has RenderStrips put each strip on a list:
// the frame's alpha list when its texture has ApplyAlphaSorting, its
// texture's own otherwise. The port draws a solid as georender baked it,
// in the matrix the animation and the cull gave -- the animation's frame,
// local to world, then the view's -- and draws at once
// only what the attach loops would draw first anyway: the order-0 textures
// that are not sorted. The rest wait for trackview_draw. A lit or
// environment-mapped batch draws alone, with the light context.
//
// With `bones`, RenderStrips' last argument, the model is an
// eAnimation's (eanim.c): no rigid or vertex animation, and each vertex
// posed by the bones into the skin ring (skin_mesh), which its batches
// draw from.

// x, y and z through `m` with a w of 1, as eMulVector (0x0011b2c0) takes
// a bVector4: a bMatrix4 multiplies the row vector on its left.
static void skin_point(float out[3], const bMatrix4* m, float x, float y,
                       float z)
{
    out[0] = x * m->v0.x + y * m->v1.x + z * m->v2.x + m->v3.x;
    out[1] = x * m->v0.y + y * m->v1.y + z * m->v2.y + m->v3.y;
    out[2] = x * m->v0.z + y * m->v1.z + z * m->v2.z + m->v3.z;
}

// DoBlendingOnStrip (0x0010d778) and its vertex (0x0010d660), on the
// baked mesh's vertices into the skin ring: each position's low bytes
// are two bones and a weight, bone A in x's, B in y's and the weight in
// z's, and the position goes through as it is, those bytes and all. A
// weight of 0 is A's matrix alone and 1 B's; any other w is A's by
// 1 - w / 256 and B's by w / 256. The normal stays the bind pose's, as
// retail's VU1 lights it. Retail reads its bones unchecked; a bone past
// the tree's here leaves the vertex where the bind pose has it. NULL when
// the ring is full.
static const GeoRenderVertex* skin_mesh(const GeoMesh* mesh,
                                        const bMatrix4* bones, int numBones)
{
    GeoRenderVertex* out = georender_skin_alloc(mesh->numVerts);
    int              i;

    if (out == NULL) {
        return NULL;
    }
    for (i = 0; i < mesh->numVerts; i++) {
        const GeoRenderVertex* s = &mesh->vbo[i];
        GeoRenderVertex*       d = &out[i];
        uint32_t               bits[3];
        uint32_t               a, b, weight;
        float                  pa[3], pb[3], w, keep;

        *d = *s;
        memcpy(bits, s->pos, sizeof bits);
        a      = bits[0] & 0xffu;
        b      = bits[1] & 0xffu;
        weight = bits[2] & 0xffu;
        if (weight == 0) {
            if ((int)a < numBones) {
                skin_point(d->pos, &bones[a], s->pos[0], s->pos[1],
                           s->pos[2]);
            }
        } else if (weight == 1) {
            if ((int)b < numBones) {
                skin_point(d->pos, &bones[b], s->pos[0], s->pos[1],
                           s->pos[2]);
            }
        } else if ((int)a < numBones && (int)b < numBones) {
            w    = (float)weight * (1.0f / 256.0f);
            keep = 1.0f - w;
            skin_point(pa, &bones[a], s->pos[0], s->pos[1], s->pos[2]);
            skin_point(pb, &bones[b], s->pos[0], s->pos[1], s->pos[2]);
            d->pos[0] = pb[0] * w + pa[0] * keep;
            d->pos[1] = pb[1] * w + pa[1] * keep;
            d->pos[2] = pb[2] * w + pa[2] * keep;
        }
    }
    return out;
}

static void draw_model(eModel* m, bMatrix4* matrix, void* light,
                       uint32_t flags, const bMatrix4* bones)
{
    TrackView*  v = s_draw;
    TrackSolid* r;
    bMatrix4    localView;
    C3D_Mtx     mv;
    uint64_t    now = 0, lit = 0;
    uint16_t    f[GEO_MAX_BATCHES];
    int         i, b, numTextures, held = 0, indices = 0;
    const GeoRenderVertex* vbo = NULL;
    const GeoMesh*         mesh;
    GeoMesh                posed;
    // The frame profiler's counts (frameprof.h): the view's, the envmap's
    // or the mirror's.
    uint32_t*   prof = FrameProfDraw.models[s_envFace    ? 1
                                            : s_mirrorView ? 2 : 0];
    uint32_t    words;
    bool        inPlace = matrix == &eMathIdentityMatrix;
    bMatrix4*   given = matrix;

    if (!v || m->Solid == NULL) {
        return;
    }
    // Where the model's time goes, for the sampler (coresample.h): each
    // part's start, and none once the model is done.
    CoreSamplePart = CS_PART_SOLID;
    words = gpuCmdBufOffset;
    // A vertex animation's frame is a solid of its own, baked like any.
    if (bones == NULL) {
        matrix = emodel_setup_animation(m, matrix);
    }
    i = model_solid(v, m);
    if (i < 0) {
        CoreSamplePart = CS_PART_NONE;
        return;
    }
    r = &v->info[i];
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        v->cmdSkipped++;
        CoreSamplePart = CS_PART_NONE;
        return;
    }
    if (bones != NULL) {
        const eAnimationTree* tree = emodel_get_animation_tree(m);

        CoreSamplePart = CS_PART_SKIN;
        vbo = skin_mesh(&r->mesh, bones, tree ? tree->NumNodes : 0);
        if (vbo == NULL) {
            v->skinsDropped++;
            CoreSamplePart = CS_PART_NONE;
            return;
        }
        v->skinned++;
    }
    mesh = mesh_for(r, vbo, &posed);
    CoreSamplePart = CS_PART_MATRIX;
    eMulMatrix(&localView, matrix, s_worldView);
    to_c3d(&localView, &mv);
    numTextures = r->slot ? v->solid[i].numTextures : 0;
    CoreSamplePart = CS_PART_BATCHES;
    for (b = 0; b < r->mesh.numBatches && b < GEO_MAX_BATCHES; b++) {
        const GeoBatch* gb = &r->mesh.batch[b];
        int             k  = gb->texture;
        TrackTex*       t  = (r->tex && k >= 0 && k < numTextures) ? r->tex[k]
                                                                 : NULL;

        if (gb->count <= 0) {
            continue;
        }
        // RenderStrips' 16 leaves out the strips whose texture has
        // ApplyAlphaSorting, and its 8 the others: the frontend draws a
        // car's solid strips and its alpha ones in two calls.
        if (flags & ((t && t->info && t->info->ApplyAlphaSorting) ? 16u
                                                                   : 8u)) {
            continue;
        }
        if (t) {
            note_use(v, t);
        }
        indices += gb->count;
        f[b] = strip_flags(&v->solid[i], gb, t, light, flags);
        if (!t || (t->order == 0 && !t->sorted)) {
            if (f[b] & 0x180) {
                lit |= (uint64_t)1 << b;
            } else {
                now |= (uint64_t)1 << b;
            }
        } else {
            defer(v, i, b, &localView, &mv, t, light, f[b], vbo);
            held++;
        }
    }
    prof[FRAMEPROF_M_MODELS]++;
    prof[FRAMEPROF_M_RIGID] += matrix != given;
    prof[FRAMEPROF_M_VERTEX] +=
        ((const eSolid*)m->Solid)->pVertexAnimator != NULL;
    prof[FRAMEPROF_M_NOW] += (uint32_t)__builtin_popcountll(now);
    prof[FRAMEPROF_M_LIT] += (uint32_t)__builtin_popcountll(lit);
    prof[FRAMEPROF_M_HELD] += (uint32_t)held;
    prof[FRAMEPROF_M_INDICES] += (uint32_t)indices;
    if (now || lit) {
        georender_set_camera(&s_proj, &mv);
    }
    if (now) {
        georender_draw_mask(mesh, r->slot, numTextures, now);
    }
    for (b = 0; lit != 0; b++, lit >>= 1) {
        if (lit & 1u) {
            draw_lit_batch(v, i, b, light, f[b], vbo);
        }
    }
    prof[FRAMEPROF_M_WORDS] += gpuCmdBufOffset - words;
    v->drawn++;
    v->drawnTris += r->mesh.numTris;
    if (inPlace) {
        v->drawnInPlace++;
    }

    // The frame after a jump says what it drew, by name, for the log: '*'
    // marks an object drawn where it stands.
    if (v->listFrame) {
        size_t len = strlen(v->drawList);

        if (len + 32 < sizeof v->drawList) {
            snprintf(v->drawList + len, sizeof v->drawList - len, "%s%.24s%s",
                     len ? " " : "", ((const eSolid*)m->Solid)->Name,
                     inPlace ? "*" : "");
        }
    }
    CoreSamplePart = CS_PART_NONE;
}

static void render_model(eModel* m, bMatrix4* matrix, void* light,
                         uint32_t flags)
{
    draw_model(m, matrix, light, flags, NULL);
}

// eanim.h's gEModelRenderStripsBonesFn: RenderStrips with the bones
// (0x0010dd58), which eAnimation::Render calls for a posed model.
static void render_model_bones(eModel* m, bMatrix4* matrix, void* light,
                               uint32_t flags, bMatrix4* bones)
{
    if (bones != NULL) {
        draw_model(m, matrix, light, flags, bones);
    }
}

// ---------------------------------------------------------------- preparing

// What trackview_prepare's uploads past the models' leave free: of the
// linear heap, on top of TEX_RESERVE, and of the texture table. A texture
// a race draws is never the one that goes short for one it might.
#define PREPARE_RESERVE (6u * 1024u * 1024u)
#define PREPARE_SLOTS   128

// Every frame a flipbook's record can show, uploaded as follow_flipbooks
// would the first time it showed it: frame k shows frame k + n's pixels,
// for every n (UpdateTextureAnimations). Only the records a solid uses
// and that are up already.
static void prepare_flipbooks(TrackView* v)
{
    bNode* n;
    int    i, j, k, f;

    for (n = TextureAnimPackList.next; n != &TextureAnimPackList;
         n = n->next) {
        const TextureAnimPack* p = (const TextureAnimPack*)(void*)n;

        for (i = 0; i < p->NumTextureAnims; i++) {
            const TextureAnim* a = &p->TextureAnimTable[i];

            if (!a->Valid) {
                continue;
            }
            for (k = 0; k < a->NumFrames; k++) {
                TrackTex* t =
                    find_texture(v, a->TextureAnimTable[k].pTextureInfo);

                if (!t || !t->valid) {
                    continue;
                }
                for (j = 0; j < a->NumFrames; j++) {
                    const TextureAnimEntry* e = &a->TextureAnimTable[j];
                    TextureInfo             src;
                    TrackTex                tt;
                    TrackFrame*             fr;

                    if (e->OriginalImageData == t->ownImage
                        && e->OriginalPaletteData == t->ownPalette) {
                        continue;
                    }
                    for (f = 0; f < v->numFrames; f++) {
                        if (v->frame[f].owner == t
                            && v->frame[f].image == e->OriginalImageData
                            && v->frame[f].palette == e->OriginalPaletteData) {
                            break;
                        }
                    }
                    if (f < v->numFrames) {
                        continue;
                    }
                    // The record as it will be when it shows frame j: a
                    // copy, so nothing the game reads is touched.
                    src             = *t->info;
                    src.ImageData   = e->OriginalImageData;
                    src.PaletteData = e->OriginalPaletteData;
                    tt              = *t;
                    tt.info         = &src;
                    if (v->numFrames >= TRACKVIEW_MAX_FRAMES
                        || !upload_texture(v, &tt,
                                           &v->frame[v->numFrames].tex,
                                           -1, true)) {
                        v->frameFails++;
                        continue;
                    }
                    fr          = &v->frame[v->numFrames++];
                    fr->owner   = t;
                    fr->image   = e->OriginalImageData;
                    fr->palette = e->OriginalPaletteData;
                    v->frameUploads++;
                }
            }
        }
    }
}

// A record that is one of a flipbook's frames. Only the ones a solid
// uses are uploaded, with every frame they show (prepare_flipbooks): one
// made valid besides would have follow_flipbooks upload its frames too.
static bool in_flipbook(const TextureInfo* info)
{
    const bNode* n;
    int          i, k;

    for (n = TextureAnimPackList.next; n != &TextureAnimPackList;
         n = n->next) {
        const TextureAnimPack* p = (const TextureAnimPack*)(const void*)n;

        for (i = 0; i < p->NumTextureAnims; i++) {
            const TextureAnim* a = &p->TextureAnimTable[i];

            for (k = 0; k < a->NumFrames; k++) {
                if (a->TextureAnimTable[k].pTextureInfo == info) {
                    return true;
                }
            }
        }
    }
    return false;
}

typedef struct {
    const TextureInfo* info;
    uint32_t           bytes;       // its chain at level 0 as RGBA8
} PrepareTex;

static int prepare_cmp(const void* a, const void* b)
{
    uint32_t x = ((const PrepareTex*)a)->bytes;
    uint32_t y = ((const PrepareTex*)b)->bytes;

    return x < y ? -1 : x > y;
}

void trackview_prepare(TrackView* v)
{
    bNode*      n;
    int         k, numCands = 0, maxCands = 0;
    PrepareTex* cand;

    // Each model as eModel::Render's first draw of it makes it: the solid
    // baked, the replacement table applied, the textures up. Every LOD of
    // every car, its tires, mirrors, plates and dash, and its damage's.
    // Their textures are the first into VRAM: the ones drawn the most.
    v->vramOk = true;
    for (n = ModelList.next; n != &ModelList; n = n->next) {
        eModel*                m  = (eModel*)(void*)n;
        const eVertexAnimator* va = m->Solid ? (const eVertexAnimator*)
            ((const eSolid*)m->Solid)->pVertexAnimator : NULL;

        (void)model_solid(v, m);
        v->preparedModels++;
        // And every frame of a vertex animation, which Render swaps in.
        for (k = 0; va != NULL && k < va->NumSolids; k++) {
            eModel frame = *m;

            frame.Solid = va->SolidTable[k];
            (void)model_solid(v, &frame);
        }
    }
    prepare_flipbooks(v);

    // Then the rest of every pack's textures that have pixels: what a
    // replacement table (a traffic car's next skin), a rename (lights,
    // damage) or a first draw (the HUD's, the sun's, the effects')
    // reaches later. The smallest first, so that what the room leaves out
    // is the fewest: sized as RGBA8, which is never less than they take.
    for (n = TexturePackList.next; n != &TexturePackList; n = n->next) {
        maxCands += ((const TexturePack*)(void*)n)->NumTextures;
    }
    cand = maxCands ? (PrepareTex*)malloc((size_t)maxCands * sizeof *cand)
                    : NULL;
    for (n = TexturePackList.next; cand && n != &TexturePackList;
         n = n->next) {
        const TexturePack* p = (const TexturePack*)(void*)n;

        for (k = 0; k < p->NumTextures && numCands < maxCands; k++) {
            const TextureInfo* info = &p->pTextureInfo[k];
            TexPack            tp;
            TexInfo            e;

            if (info->ImageData == NULL || find_texture(v, info)
                || in_flipbook(info) || !texture_source(info, &tp, &e)) {
                continue;
            }
            cand[numCands].info  = info;
            cand[numCands].bytes =
                (uint32_t)texpack_chain_bytes(&e, 0, TEXPACK_FMT_RGBA8);
            numCands++;
        }
    }
    if (numCands > 1) {
        qsort(cand, (size_t)numCands, sizeof *cand, prepare_cmp);
    }
    for (k = 0; k < numCands; k++) {
        const TrackTex* t;

        if (v->numTextures >= TRACKVIEW_MAX_TEXTURES - PREPARE_SLOTS
            || (linearSpaceFree()
                    < cand[k].bytes + TEX_RESERVE + PREPARE_RESERVE
                && !vram_room(v, cand[k].bytes))) {
            v->preparedSkipped++;
            v->preparedSkippedKB += cand[k].bytes >> 10;
            continue;
        }
        t = load_texture(v, cand[k].info);
        if (t && t->valid) {
            v->preparedTextures++;
        }
    }
    free(cand);
    v->vramOk       = false;
    v->prepared     = true;
    v->lateNames[0] = '\0';
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

// Whether INGAMEB's solid lists are in: see load_shared_packs.
static bool s_sharedSolids;

// The packs in the bundles the UI already holds, GLOBALB.BUN and
// INGAMEB.BUN: the boot and LOADING_TRACK_COMMON's, loaded before anything
// of the track's. Slot 2's loader is offered every top-level chunk and
// takes the packs and flipbooks; the rest of those bundles is the UI's.
//
// Slot 4's, LoaderSolidList, takes INGAMEB's three solid lists, in the
// file's order among the packs: eLabInGame's (SPIKEBELT_00, the markers,
// ROADBLOCK_BARREL, SMOKEBOMB, ...) and the two of drivers. GLOBALB has
// none. The loader moves each strip's data pointer on by where the data
// is, and the port keeps INGAMEB for the session where retail reads it
// afresh, so the lists go in once, with the first track, and stay. Each
// track's eFixUpTables points their texture tables at its packs again.
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
            } else if (!s_sharedSolids) {
                loader_solid_list(c);
            }
        }
    }
    if (v->numShared > 0) {
        s_sharedSolids = true;
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
//
// The mirror's target, 7, is SetScreenBuffers' too (0x001064c8), the same
// in every video mode: 256 by 64, PSMCT32 over PSMZ16S, its aspect ratios
// 1.5 and 1.08, and cleared to 0x80000000, black with an alpha of 1.0.
// MaybeChangeViewMode gives it its scissor in view mode 2.
static void setup_view(void)
{
    eRenderTarget* rt = eGetRenderTarget(1);
    eRenderTarget* rvm = eGetRenderTarget(7);

    MainDraw0Context->ScissorW = ScreenWidth;
    MainDraw0Context->ScissorH = ScreenHeight;
    rt->AspectRatioX   = 1.0f;
    rt->AspectRatioY   = 1.08f;
    rt->AspectRatio2DX = 0.8f;
    rt->AspectRatio2DY = 0.94f;
    // The PICA's depth buffer is 24 bits, as PSMZ24's is, so the sun draws
    // at a MaxZ of 16777215.
    rt->ZBufferMode    = GS_PSMZ24;
    rvm->FrameWidth       = TRACKVIEW_MIRROR_W;
    rvm->FrameHeight      = TRACKVIEW_MIRROR_H;
    rvm->AspectRatioX     = 1.5f;
    rvm->AspectRatioY     = 1.08f;
    rvm->AspectRatio2DX   = 0.8f;
    rvm->AspectRatio2DY   = 0.94f;
    rvm->FovBias          = 1.0f;
    rvm->BackgroundColour = 0x80000000u;
    rvm->ClearBackground  = 1;
    // Its depth is the PICA's 24 bits here, as player 1's is.
    rvm->ZBufferMode      = GS_PSMZ24;
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
    gEModelRenderStripsBonesFn = render_model_bones;
    gEPolyRenderFn  = render_epoly;
    gEPolyRender3DFn = render_epoly_3d;
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
    gEModelRenderStripsBonesFn = render_model_bones;
    gEPolyRenderFn  = render_epoly;
    gEPolyRender3DFn = render_epoly_3d;
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
        if (gEModelRenderStripsBonesFn == render_model_bones) {
            gEModelRenderStripsBonesFn = NULL;
        }
        if (gEPolyRenderFn == render_epoly) {
            gEPolyRenderFn = NULL;
        }
        if (gEPolyRender3DFn == render_epoly_3d) {
            gEPolyRender3DFn = NULL;
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
        // Their textures go with the track, and the radial blur's last
        // frame, the black and white's copy and the depth of field's
        // copies and half target with it.
        s_numFlailer     = 0;
        s_flailerDropped = 0;
        free_blur_previous();
        free_grey_copy();
        free_focus_copies();
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

// compare_deferred for sort_deferred's indices, into s_sortBase.
static const TrackDeferred* s_sortBase;

static int compare_deferred_at(const void* pa, const void* pb)
{
    return compare_deferred(&s_sortBase[*(const uint16_t*)pa],
                            &s_sortBase[*(const uint16_t*)pb]);
}

// The entries in compare_deferred's order, as qsort of the entries left
// them, for less: qsort sorts their indices, two bytes each, not the
// entries, 92 (TASKS 46). What qsort compares and moves follows only
// from the count and the answers, so the indices end in the order the
// entries did, a NaN depth's too. Then each entry moves once: a cycle of
// the order at a time, through one held aside.
static void sort_deferred(TrackView* v)
{
    static uint16_t order[TRACKVIEW_MAX_DEFERRED];
    int             n = v->numDeferred, i;

    for (i = 0; i < n; i++) {
        order[i] = (uint16_t)i;
    }
    s_sortBase = v->deferred;
    qsort(order, (size_t)n, sizeof order[0], compare_deferred_at);
    // order[i] is the entry that goes to i; one in place is i.
    for (i = 0; i < n; i++) {
        TrackDeferred held;
        int           j, k;

        if (order[i] == i) {
            continue;
        }
        held = v->deferred[i];
        for (j = i; (k = order[j]) != i; j = k) {
            v->deferred[j] = v->deferred[k];
            order[j]       = (uint16_t)j;
        }
        v->deferred[j] = held;
        order[j]       = (uint16_t)j;
    }
}

// With `alpha` false, AttachSolidPolys alone: the unsorted batches draw
// and the sorted ones stay for a later call. With it true, both lists.
static void draw_deferred(TrackView* v, bool alpha)
{
    int i, kept = 0;

    sort_deferred(v);
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
        if (d->sprites >= 0) {
            draw_sprites(v, d);
            continue;
        }
        r = &v->info[d->solid];
        georender_set_camera(&s_proj, &d->modelView);
        if (d->flags & 0x180) {
            draw_lit_batch(v, d->solid, d->batch, d->light, d->flags,
                           d->vbo);
        } else {
            GeoMesh posed;

            georender_draw_mask(mesh_for(r, d->vbo, &posed), r->slot,
                                r->slot ? v->solid[d->solid].numTextures : 0,
                                (uint64_t)1 << d->batch);
        }
    }
    v->numDeferred = kept;
}

// ---------------------------------------------------------------- the sun

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

// The table Render takes a Flailer poly's z into (0x002c9e70), 29 of 32
// set. Its GS Z is MaxZ less the entry, but for a z of 20 to 24, whose Z
// is the entry; z 0 to 15, the minimap's, are 10 to 25 under MaxZ, so a
// higher z draws under a lower.
static const uint8_t kFlailerZ[32] = {
    10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
    5, 6, 7, 8, 5, 4, 3, 2, 1, 1, 2, 3, 4, 0, 0, 0,
};

// The order of a z's GS Z, with MaxZ as 65536; only the order is wanted.
// Render indexes the table unchecked, so a z past it reads what follows;
// here it is the table's last, 0, and on top of everything.
static int32_t flailer_z(float z)
{
    int32_t i = ee_trunc_w(z);

    if (i < 0 || i > 31) {
        i = 31;
    }
    if ((uint32_t)(i - 20) < 5u) {
        return kFlailerZ[i];
    }
    return 65536 - kFlailerZ[i];
}

static void queue_flailer(const ePoly* p, TextureInfo* info)
{
    FlailerPoly* f;

    if (s_numFlailer >= TRACKVIEW_FLAILER_POLYS) {
        s_flailerDropped++;
        return;
    }
    f       = &s_flailer[s_numFlailer++];
    f->poly = *p;
    f->info = info;
    f->z    = flailer_z(p->Vertices[0].z);
}

// A SunPoly's own ALPHA_1, where any other poly takes its texture's. C is
// As in every one StuffSun makes; the radial blur's are A - A, which
// leaves the colour, and C Ad (radialblur.h).
static uint8_t poly_blend(const ePoly* p)
{
    if (p->AlphaA == EPOLY_ALPHA_CS && p->AlphaD == EPOLY_ALPHA_CD) {
        if (p->AlphaB == EPOLY_ALPHA_CS) {
            return GEO_BLEND_KEEP;
        }
        if (p->AlphaB == EPOLY_ALPHA_CD) {
            return p->AlphaC == EPOLY_ALPHA_AD ? GEO_BLEND_DEST_ALPHA
                                               : GEO_BLEND_ALPHA;
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

// ePoly::Render's strip on the top screen, V0, V1, V3, V2, for a poly in
// `rt`'s pixels: each vertex where the GS puts it, with its UVs and colour.
// `mid` gets their mean.
static void epoly_screen(ePoly* p, const eRenderTarget* rt,
                         GeoRenderVertex q[4], float mid[2])
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    float                halfW = (float)(rt->ScissorW >> 1);
    float                off   = GS_CENTRE - halfW;
    int                  i;

    mid[0] = 0.0f;
    mid[1] = 0.0f;
    memset(q, 0, 4u * sizeof *q);
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
        mid[0] += x * 0.25f;
        mid[1] += y * 0.25f;
        target_to_screen(x, y, rt->ScissorW, rt->ScissorH, rt->AspectRatioX,
                         rt->AspectRatioY, &q[i].pos[0], &q[i].pos[1]);
        q[i].st[0] = p->UVs[n][0] / w;
        q[i].st[1] = p->UVs[n][1] / w;
        memcpy(q[i].colour, p->Colours[n], 4);
    }
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
    eRenderTarget*  rt = s_quadTarget;
    TrackView*      v  = s_draw;
    TrackTex*       t;
    GeoTexture      gt;
    GeoRenderVertex q[4];
    float           depth, mid[2];
    uint8_t         blend;
    bool            drawn;

    // `flags` keeps the packet in the poly's frame memory, for a poly
    // drawn again unchanged; nothing here needs it.
    (void)flags;
    if (info == NULL) {
        return;
    }
    // The minimap's, for whichever screen it is on.
    if (p->Flailer) {
        queue_flailer(p, info);
        return;
    }
    if (v == NULL || rt == NULL) {
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
    epoly_screen(p, rt, q, mid);

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
    v->sunAt[0] = mid[0];
    v->sunAt[1] = mid[1];
    v->sunAlpha = p->Colours[0][3];
}

// ePoly::Render3D (retail 0x0010ff88), for the light flares: the poly in
// the matrix's space, a strip of V0, V1, V3, V2. It goes where eEndStrip's
// packet goes, the texture's list or the alpha sort by V0's z, so here it
// is a strip of four. Its last argument is not read.
static void render_epoly_3d(ePoly* p, TextureInfo* info, bMatrix4* m,
                            int flags)
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    int                  i;

    (void)flags;
    if (info == NULL || !strip_begin(info, 4, m)) {
        return;
    }
    for (i = 0; i < 4; i++) {
        const int k = kStrip[i];
        bVector3  at;

        at.x   = p->Vertices[k].x;
        at.y   = p->Vertices[k].y;
        at.z   = p->Vertices[k].z;
        at.pad = 0.0f;
        strip_add_vertex(&at);
        strip_add_colour((uint32_t)p->Colours[k][0]
                         | (uint32_t)p->Colours[k][1] << 8
                         | (uint32_t)p->Colours[k][2] << 16
                         | (uint32_t)p->Colours[k][3] << 24);
        strip_add_uv(p->UVs[k][0], p->UVs[k][1]);
    }
    strip_end();
}

// Render's packet for each queued poly, as render_epoly has it -- the
// texture's blend, and its alpha test unless it is semitransparent -- but
// for the position: the minimap's polys set ApplyAspectRatio, which
// scales the Flailer's 640 by 480 to the target's pixels, 512 by 448 on
// the PS2; here the target is `width` by `height`. Each vertex's ST is
// the GS's S / Q and T / Q, carried across the quad by a w of 1 / Q.
// The port's move and scale go first, in the 640 by 480.
void trackview_draw_flailer_polys(TrackView* v, float width, float height,
                                  float scale, float dx, float dy)
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    int   order[TRACKVIEW_FLAILER_POLYS];
    float sx = width / 640.0f, sy = height / 480.0f;
    int   n = s_numFlailer, i, j, k;

    v->flailerPolys  = 0;
    v->flailerFailed = s_flailerDropped;
    s_numFlailer     = 0;
    s_flailerDropped = 0;
    if (!v->loaded) {
        v->flailerFailed += n;
        return;
    }

    // The lowest Z first: the GS's GEQUAL leaves the highest on top, and
    // of two at one Z, the later.
    for (i = 0; i < n; i++) {
        for (j = i; j > 0 && s_flailer[order[j - 1]].z > s_flailer[i].z; j--) {
            order[j] = order[j - 1];
        }
        order[j] = i;
    }

    for (i = 0; i < n; i++) {
        const FlailerPoly* f = &s_flailer[order[i]];
        const ePoly*       p = &f->poly;
        TrackTex*          t;
        GeoTexture         gt;
        GeoRenderVertex    q[4];
        uint8_t            blend;

        if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
            v->cmdSkipped++;
            v->flailerFailed++;
            continue;
        }
        t = load_texture(v, f->info);
        if (t == NULL || !t->valid) {
            v->flailerFailed++;
            continue;
        }
        gt.tex        = &t->tex;
        gt.uvScale[0] = t->uvScale[0];
        gt.uvScale[1] = t->uvScale[1];
        gt.pass       = t->pass;

        memset(q, 0, sizeof q);
        for (k = 0; k < 4; k++) {
            const int m  = kStrip[k];
            float     qq = p->UVs[m][2];
            float     w  = qq > 0.0f ? 1.0f / qq : 1.0f;
            float     d  = qq > 0.0f ? qq : 1.0f;

            q[k].pos[0] = (p->Vertices[m].x * scale + dx) * sx * w;
            q[k].pos[1] = (p->Vertices[m].y * scale + dy) * sy * w;
            q[k].pos[2] = w;
            q[k].st[0]  = p->UVs[m][0] / d;
            q[k].st[1]  = p->UVs[m][1] / d;
            memcpy(q[k].colour, p->Colours[m], 4);
        }
        blend = f->info->IsAnySemitransparencyFlag ? t->pass.blend
                                                   : GEO_BLEND_NONE;
        if (georender_draw_hud_quad_w(q, &gt, blend, !t->pass.noAlphaTest,
                                      width, height)) {
            v->flailerPolys++;
        } else {
            v->flailerFailed++;
        }
    }
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
// The x's bits and the y's land apart, so the word is the x's part plus
// the y's.
static uint32_t tiled_x(int x)
{
    uint32_t by = (uint32_t)x;

    return (by >> 3) * (240u / 8u) * 64u
         + (((by & 1u) << 1) | ((by & 2u) << 2) | ((by & 4u) << 3));
}

static uint32_t tiled_y(int y)
{
    uint32_t bx = (uint32_t)(239 - y);

    return (bx >> 3) * 64u
         + ((bx & 1u) | ((bx & 2u) << 1) | ((bx & 4u) << 2));
}

static uint32_t tiled_index(int x, int y)
{
    return tiled_x(x) + tiled_y(y);
}

// The GS's Z for a depth the PICA wrote. The PICA's is the Z-buffer's,
// the view's depth d as near (far - d) / ((far - near) d): 1 at the near
// plane, 0 at the far. The GS's is the same hyperbola from the range's
// ZMin to its ZMax -- floats from 2 to 4, whose mantissas are the Z: 16
// up to 0x0ff000, or to PSMZ24's 0x800000.
static float gs_z_of_depth(const eZRange* r, float t)
{
    const float zmin = (r->ZMin - 2.0f) * 4194304.0f;
    const float zmax = (r->ZMax - 2.0f) * 4194304.0f;

    return zmin + (zmax - zmin) * t;
}

// The Z as retail's 24-bit buffer holds it, which the fog reads (efog.c)
// and the sun's rects too, 32 bits a pixel of which StuffSun takes the low
// 24; all it asks is whether they are under 2. What the clear left, and
// the sky did not write, is 0.
static uint32_t gs_z24(float z)
{
    return z >= 16777215.0f ? 0xffffffu : (uint32_t)z;
}

// And for the fog's u, the view's depth as (far - d) / (far - near), whose
// Z-buffer depth is near u / d, in the view's target's range: player 1's
// is PSMZ24's, 16 to 0x800000.
static uint32_t gs_z_of(float u)
{
    float d = s_depthFar - u * (s_depthFar - s_depthNear);

    return gs_z24(gs_z_of_depth(s_zRange,
                                d > 0.0f ? s_depthNear * u / d : 1.0f));
}

static uint32_t gs_z(uint32_t d24)
{
    if (d24 == 0) {
        return 0;
    }
    return gs_z24(gs_z_of_depth(s_zRange, (float)d24 / 16777215.0f));
}

// gs_z_of_depth backwards: the PICA's depth whose GS Z is g, or -1 for a
// Z at or past the nearest the scenery reaches, which passes against
// anything. A Z under the farthest is the depth 0, which only the clear
// has.
static float depth_of_gs_z(float g)
{
    const float zmin = (s_zRange->ZMin - 2.0f) * 4194304.0f;
    const float zmax = (s_zRange->ZMax - 2.0f) * 4194304.0f;
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
        uint32_t z = sky ? 0 : gs_z_of(u);

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

        v->fogKeep[k] = efog_keep(palette, mode, gs_z_of(u));
    }
    v->fogSkyKeep = efog_keep(palette, mode, 0);
}

// eAttachDepthOfField's seams (efocus.h): where the image builds a view's
// pass, view 1's palette as the plan its passes draw (efocus_plan); and
// where it builds the blur's, the blur. The draw is depth_of_field's, once
// the frame is drawn. The 3DS has no view 2 to draw.
static EFocusPlan s_focusPlan;
static bool       s_focusPlanned;       // view 1's pass, this frame
static bool       s_focusBlurred;       // and the blur's

static void focus_attach(eView* view, const uint32_t* palette,
                         const EFocusBand* band)
{
    if (view->ID != EVIEW_ID_PLAYER1 || s_draw == NULL) {
        return;
    }
    efocus_plan(palette, band, &s_focusPlan);
    s_focusPlanned = true;
}

static void focus_blur(void)
{
    s_focusBlurred = true;
}

// eDisplayFrame's fog (0x001138ac), which the PS2 lays over the frame once
// it is drawn; see efog.h. Its palette depends on nothing drawn, so here
// it is made first, and georender lays it on as each thing is drawn. The
// depth of field after it, from the same test, whose palette depends on
// nothing drawn either: its plan here, its passes in depth_of_field.
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
    gEFogAttachFn  = fog_attach;
    gEDofAttachFn  = focus_attach;
    gEDofBlurFn    = focus_blur;
    s_focusPlanned = false;
    s_focusBlurred = false;
    if (InGameFlag && eattach_depth_into_alpha()) {
        eattach_fog();
        eattach_depth_of_field();
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

// A sun rect's pixels, read back; the count of them under 2, the sky's.
// A pixel's place on the screen is its column's and its row's
// (target_to_screen), and its word is the two's parts added (tiled_x and
// tiled_y), so each column and row is worked out once a rect, not once a
// pixel (TASKS 46): the same floats, floors and clamps, and the same
// words. A column or row off the target is -1.
static int32_t s_sunCol[SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE];
static int32_t s_sunRow[SUN_ZBUFFER_SIZE * SUN_ZBUFFER_SIZE];

static int read_sun_rect(const SunRect* q, const uint32_t* depth)
{
    int sky = 0;
    int i, j;

    // StuffSun keeps the rect on the target; a target under 33 across
    // does not, and none of what is off it counts.
    for (i = 0; i < q->w; i++) {
        int   px = q->x + i;
        float sx, sy;
        int   ix;

        if (px < 0 || px >= q->targetW) {
            s_sunCol[i] = -1;
            continue;
        }
        target_to_screen((float)px + 0.5f, 0.5f, q->targetW, q->targetH,
                         q->aspX, q->aspY, &sx, &sy);
        ix          = (int)floorf(sx);
        ix          = ix < 0 ? 0 : ix > 399 ? 399 : ix;
        s_sunCol[i] = (int32_t)tiled_x(ix);
    }
    for (j = 0; j < q->h; j++) {
        int   py = q->y + j;
        float sx, sy;
        int   iy;

        if (py < 0 || py >= q->targetH) {
            s_sunRow[j] = -1;
            continue;
        }
        target_to_screen(0.5f, (float)py + 0.5f, q->targetW, q->targetH,
                         q->aspX, q->aspY, &sx, &sy);
        iy          = (int)floorf(sy);
        iy          = iy < 0 ? 0 : iy > 239 ? 239 : iy;
        s_sunRow[j] = (int32_t)tiled_y(iy);
    }
    for (j = 0; j < q->h; j++) {
        for (i = 0; i < q->w; i++) {
            uint32_t z = 0xffffffu;

            if (s_sunCol[i] >= 0 && s_sunRow[j] >= 0) {
                z = gs_z(depth[s_sunCol[i] + s_sunRow[j]] & 0xffffffu);
                if (z < 2) {
                    sky++;
                }
            }
            q->dst[j * q->w + i] = z;
        }
    }
    return sky;
}

void trackview_read_depth(TrackView* v, C3D_RenderTarget* target)
{
    const uint32_t* depth;
    int             r;

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
        v->sunSky += read_sun_rect(&s_sunRects[r], depth);
        v->sunRects++;
    }
    s_numSunRects = 0;
}

void trackview_capture_names(const TrackView* v)
{
    int i;

    for (i = 0; i < v->numTextures; i++) {
        const TrackTex* t = &v->texture[i];

        capture_note("tex %p (data %p, %dx%d, level %d) %s",
                     (const void*)&t->tex, t->tex.data, t->tex.width,
                     t->tex.height, t->level,
                     t->info ? t->info->DebugName : "?");
    }
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
    eView* rvm  = eGetView(EVIEW_ID_PLAYER1_RVM);
    int    i;

    // The GPU is done with the last frame by now, so the screen quads'
    // ring starts again, before any view of this one draws a quad.
    georender_quads_rewind();
    v->cacheClock++;
    eSwapFrameMallocBuffers();
    MaybeChangeViewMode();
    // AttachDrawEnvironment's second context out of the frontend
    // (0x0010ac50): its ALPHA_2 from EnvPassAlphaA .. D (eview.h). The two
    // the game sets are the default, which adds the environment pass, and
    // Chrome Cars', A = B and D = 0, which is the pass alone.
    georender_set_env_replace(EnvPassAlphaA == EnvPassAlphaB
                              && EnvPassAlphaD == 0);
    if (EnableEnvMapViews) {
        update_environment_map_cameras();
    }
    eview_set_max_z(view->pRenderTarget0);
    eview_calculate_view_matrices(view, 0.0f, 0.0f, 0.0f);
    // The mirror's, while it has a mover and so its target.
    if (rvm->Active && rvm->pRenderTarget0->Active) {
        eview_set_max_z(rvm->pRenderTarget0);
        eview_calculate_view_matrices(rvm, 0.0f, 0.0f, 0.0f);
    }
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
    hangwatch_gpu_stage("the cull");
    FRAMEPROF_STAMP(FRAMEPROF_CULL);
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
    s_numSprites       = 0;
    s_numSpriteSets    = 0;
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
    static const char* const kFace[6] = {
        "envmap view 0", "envmap view 1", "envmap view 2",
        "envmap view 3", "envmap view 4", "envmap view 5",
    };
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
    capture_offscreen(true);
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
        s_zRange     = eview_z_range(view->pRenderTarget0);
        begin_view(v);
        drawn = v->drawn;

        georender_set_zwrite(false);
        hangwatch_mark("an envmap view's sky");
        StuffSky(view);
        draw_deferred(v, true);
        georender_set_zwrite(true);
        hangwatch_mark("an envmap view's scenery");
        georender_run_begin();
        scenery_stuff_scenery(&v->cull, view);
        georender_run_end();
        hangwatch_mark("an envmap view's lists");
        draw_deferred(v, false);
        draw_deferred(v, true);

        v->envFaces++;
        v->envDrawn += v->drawn - drawn;
        views |= 1u << i;
        hangwatch_gpu_stage(kFace[i]);
    }
    s_envFace = false;
    s_draw    = NULL;
    hangwatch_mark("the envmap's fold begun");
    georender_envmap_fold(views);
    capture_offscreen(false);
    hangwatch_gpu_stage("the envmap's fold");
}

// ------------------------------------------------------ the rear-view mirror

bool trackview_mirror_init(void)
{
    return georender_mirror_init(TRACKVIEW_MIRROR_W, TRACKVIEW_MIRROR_H);
}

// ePoly::Render for a poly in the mirror's target, as render_epoly has it
// for the top screen's: the half pixel past the middle, the GS's whole
// pixels, the strip's V0, V1, V3, V2 and the blend for a semitransparent
// texture alone. The target is the texture's own pixels here. `mask` has
// the fragment's alpha go into the target as the GS's does, which
// DisplayRVMs blends the mirror by.
static void mirror_epoly(TrackView* v, const ePoly* p, TextureInfo* info,
                         bool mask)
{
    static const uint8_t kStrip[4] = { 0, 1, 3, 2 };
    const float          halfW = (float)(TRACKVIEW_MIRROR_W >> 1);
    const float          offX  = GS_CENTRE - halfW;
    const float          offY  = GS_CENTRE - (float)(TRACKVIEW_MIRROR_H >> 1);
    TrackTex*            t;
    GeoTexture           gt;
    GeoRenderVertex      q[4];
    int                  i;

    t = load_texture(v, info);
    if (t == NULL || !t->valid) {
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
    memset(q, 0, sizeof q);
    for (i = 0; i < 4; i++) {
        const int n = kStrip[i];
        float     x = p->Vertices[n].x;
        float     y = p->Vertices[n].y;

        if (halfW < x) {
            x += -0.5f;
        }
        q[i].pos[0] = floorf(x + offX) - offX;
        q[i].pos[1] = floorf(y + offY) - offY;
        q[i].st[0]  = p->UVs[n][0] / p->UVs[n][2];
        q[i].st[1]  = p->UVs[n][1] / p->UVs[n][2];
        memcpy(q[i].colour, p->Colours[n], 4);
    }
    georender_draw_mirror_quad(q, &gt,
                               info->IsAnySemitransparencyFlag
                                   ? t->pass.blend : GEO_BLEND_NONE,
                               mask);
}

// DisplayRVMImages (retail 0x0010ec70), for view 3 alone: with both of
// its textures, it marks RVM_MASK semitransparent, and for the view and
// its target active draws two polys over the target from (1, -14) to
// (257, 76), mirrored left to right, at the target's MaxZ. RVM is the
// frame and the glass's tint, black with a quarter's alpha inside;
// RVM_MASK, added, leaves the colour and writes the alpha: 1 inside the
// glass and its frame, 0 past them.
static void display_rvm_images(TrackView* v, eRenderTarget* rt)
{
    static const float kXY[4][2] = {
        { 1.0f, -14.0f }, { 257.0f, -14.0f }, { 257.0f, 76.0f },
        { 1.0f, 76.0f },
    };
    static const float kUV[4][2] = {
        { 1.0f, 0.0f }, { 0.0f, 0.0f }, { 0.0f, 1.0f }, { 1.0f, 1.0f },
    };
    TextureInfo* frame = (TextureInfo*)pTextureInfoRVMInfo;
    TextureInfo* mask  = (TextureInfo*)pTextureInfoRVMMask;
    ePoly        p;
    int          i;

    if (frame == NULL || mask == NULL) {
        return;
    }
    mask->IsAnySemitransparencyFlag = 1;
    epoly_init(&p);
    p.ApplyAspectRatio = 0;
    for (i = 0; i < 4; i++) {
        p.Vertices[i].x = kXY[i][0];
        p.Vertices[i].y = kXY[i][1];
        p.Vertices[i].z = rt->MaxZ;
        p.UVs[i][0]     = kUV[i][0];
        p.UVs[i][1]     = kUV[i][1];
    }
    mirror_epoly(v, &p, frame, false);
    mirror_epoly(v, &p, mask, true);

    // The images start at column 1, so column 0 keeps the view's alpha of
    // one, and DisplayRVMs' fold shows it as a dark line down the mirror's
    // right edge (TASKS 64). The mask again over that column, with an
    // alpha of 0, as it leaves past the frame.
    for (i = 0; i < 4; i++) {
        p.Vertices[i].x = (i == 1 || i == 2) ? 1.0f : 0.0f;
        p.Colours[i][3] = 0;
    }
    mirror_epoly(v, &p, mask, true);
}

// View 3's share of eDisplayFrame, into target 7: retail's loop draws its
// sky, scenery and cars with view 0's and the others' (0x00112a38 ..
// 0x0011363c), without the fog (eattach_fog's views are 1 and 2) or the
// track routes, then DisplayRVMImages after the cars' alpha lists. Here
// the view is drawn whole before the top screen is, as the envmap's are.
// Its sun and effects are not drawn into it yet.
//
// Retail's projection puts x at H AspectRatioX x / z and y at H
// AspectRatioY y / z in the target's pixels, and DisplayRVMs shows the
// 256 by 64 in 192 by 64 GS pixels of a 4:3 screen. The top screen's HUD
// takes the PS2's 512 by 448 to 400 by 240, which is 5:3: the mirror is a
// quarter wider for its height there than on the PS2's screen, and so
// takes in a quarter more across, for the world in it to keep its shape.
void trackview_draw_mirror(TrackView* v)
{
    eView*         view = eGetView(EVIEW_ID_PLAYER1_RVM);
    eRenderTarget* rt   = view->pRenderTarget0;
    uint32_t       bg, a, clear;
    uint32_t       profCars[FRAMEPROF_C_COUNT];
    float          tanx, tany;
    int            drawn;

    v->mirrorDrawn  = false;
    v->mirrorModels = 0;
    if (!v->loaded || !FrameMemoryBuffer[0]) {
        return;
    }
    if (!v->frameBegun) {
        begin_frame(v);
    }
    if (view->pCamera == NULL || !view->Active || !rt->Active
        || view->H <= 0.0f) {
        return;
    }
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        return;
    }
    // The GS's 0xAABBGGRR, with 0x80 for an alpha of one.
    bg    = rt->BackgroundColour;
    a     = (bg >> 24) * 2u;
    clear = (bg & 0xffu) << 24 | (bg >> 8 & 0xffu) << 16
          | (bg >> 16 & 0xffu) << 8 | (a > 0xffu ? 0xffu : a);
    if (!georender_mirror_begin(clear)) {
        return;
    }
    // eDisplayFrame makes each view current before its chain (0x001131fc).
    eSetCurrentView(view);
    s_draw       = v;
    s_mirrorView = true;
    v->listFrame = false;
    capture_offscreen(true);
    georender_set_light(0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f);
    georender_set_fog(NULL, 0);

    tanx = 1.25f * (float)rt->ScissorW * 0.5f / (view->H * rt->AspectRatioX);
    tany = (float)rt->ScissorH * 0.5f / (view->H * rt->AspectRatioY);
    Mtx_Persp(&s_proj, 2.0f * atanf(tany), tanx / tany, view->NearZ,
              view->FarZ, false);
    s_worldView = view->WorldViewMatrix;
    s_zRange    = eview_z_range(view->pRenderTarget0);
    begin_view(v);
    drawn = v->drawn;

    georender_set_zwrite(false);
    hangwatch_mark("the mirror's sky");
    StuffSky(view);
    draw_deferred(v, true);
    georender_set_zwrite(true);
    hangwatch_mark("the mirror's scenery");
    georender_run_begin();
    scenery_stuff_scenery(&v->cull, view);
    georender_run_end();
    // RenderClans (0x001132c4) for the mirror too: retail's chain makes
    // the call for every view. The PS2 draws the mirror after the player's
    // view and the port before it, so the sets the mirror sees go to the
    // head of SkidSetList first.
    hangwatch_mark("the mirror's skids");
    render_clans(view->WorldScreenClipMatrix, view);
    // RenderCameraMovers (0x0011333c) for the mirror too: its mover's,
    // which draws nothing.
    render_camera_movers(view);
    // RenderWorldObjects (0x001cdb20) for the mirror too: the spike
    // strips' belts. The mirror has no sun, so they follow the scenery.
    // Then the tunnels' light flares (0x00116778), which wait on the
    // lists.
    hangwatch_mark("the mirror's world objects");
    georender_run_begin();
    render_world_objects(view);
    georender_run_end();
    el_render_world_light_flares(view);
    draw_deferred(v, false);
    hangwatch_mark("the mirror's cars");
    // The frame profiler's car parts are the player's view's: the mirror
    // has its own stage.
    memcpy(profCars, FrameProfDraw.cars, sizeof profCars);
    georender_run_begin();
    // Retail draws the mirror's cars after the player's view's, so their
    // fAngleToCamera is the one the trackers read: trackview_draw puts it
    // back (render_cars_keep_angles).
    render_cars_keep_angles();
    render_cars(view);
    draw_deferred(v, false);
    draw_deferred(v, true);
    georender_run_end();
    memcpy(FrameProfDraw.cars, profCars, sizeof profCars);
    display_rvm_images(v, rt);

    v->mirrorModels = v->drawn - drawn;
    v->mirrorDrawn  = true;
    s_draw          = NULL;
    s_mirrorView    = false;
    capture_offscreen(false);
    hangwatch_gpu_stage("the mirror");
}

// ---------------------------------------------------------- the radial blur

// DisplayBlendPrevious's last frame (radialblur.h). The PS2 reads its other
// screen buffer; here the view's colour is copied after its blend and
// before its mirror and the HUD, which so leave no trails. Made at the
// blur's first frame, kept to the track's end.

static C3D_Tex s_blurPrev;
static bool    s_blurPrevMade;
static bool    s_blurPrevNoHeap;        // the linear heap had no 512 KB
static bool    s_blurPrevFull;          // the last frame's view is in it

static void free_blur_previous(void)
{
    if (s_blurPrevMade) {
        C3D_TexDelete(&s_blurPrev);
    }
    memset(&s_blurPrev, 0, sizeof s_blurPrev);
    s_blurPrevMade   = false;
    s_blurPrevNoHeap = false;
    s_blurPrevFull   = false;
}

// The top screen's colour as the GPU will have drawn it, into `tex`, made
// the first time in the linear heap and filtered by `filter`. The screen's
// buffer is 240 by 400 in 50 rows of 30 tiles, and the texture 256 by 512,
// so the copy leaves two tiles at the end of each row; its columns run up
// the screen and its rows across it (capture.c's tiled_index). What is
// drawn so far is sent first, whether the frame goes in parts or not, and
// the copy queued after waits for it, as what is sent after waits for the
// copy. False when the buffer is not the top screen's, or the heap had no
// 512 KB, which `noHeap` keeps. With `depth`, its depth buffer, D24S8, in
// place of its colour: tiled as the colour is, its top byte G as a texel,
// its middle B and its low A.
#define TOP_TILE_ROW (240 / 8 * 64 * 4)           // bytes
#define TOP_TILE_GAP ((256 - 240) / 8 * 64 * 4)

static bool copy_top_buffer(C3D_Tex* tex, bool* made, bool* noHeap,
                            GPU_TEXTURE_FILTER_PARAM filter, bool depth)
{
    C3D_FrameBuf* fb = C3D_GetFrameBuf();
    void*         src;

    if (fb == NULL || fb->colorBuf == NULL || fb->width != 240
        || fb->height != 400 || fb->colorFmt != GPU_RB_RGBA8) {
        return false;
    }
    src = fb->colorBuf;
    if (depth) {
        if (fb->depthBuf == NULL
            || fb->depthFmt != GPU_RB_DEPTH24_STENCIL8) {
            return false;
        }
        src = fb->depthBuf;
    }
    if (!*made) {
        if (*noHeap || !C3D_TexInit(tex, 256, 512, GPU_RGBA8)) {
            memset(tex, 0, sizeof *tex);
            *noHeap = true;
            return false;
        }
        C3D_TexSetFilter(tex, filter, filter);
        C3D_TexSetWrap(tex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
        *made = true;
    }
    hangwatch_gpu_send_now();
    GX_TextureCopy((u32*)src, GX_BUFFER_DIM(TOP_TILE_ROW / 16, 0),
                   (u32*)tex->data,
                   GX_BUFFER_DIM(TOP_TILE_ROW / 16, TOP_TILE_GAP / 16),
                   240u * 400u * 4u, 8);
    return true;
}

static bool copy_top_screen(C3D_Tex* tex, bool* made, bool* noHeap,
                            GPU_TEXTURE_FILTER_PARAM filter)
{
    return copy_top_buffer(tex, made, noHeap, filter, false);
}

// The GS reads its other buffer bilinear.
static void copy_blur_previous(void)
{
    s_blurPrevFull = copy_top_screen(&s_blurPrev, &s_blurPrevMade,
                                     &s_blurPrevNoHeap, GPU_LINEAR);
}

// DisplayRadialBlur and DisplayBlendPrevious (0x0010f280, 0x0010f4f0) for
// the view, after its scene, the cars and the alpha lists, and before its
// mirror: the four quads' mask into the target's alpha, then the last
// frame by it, each drawn as ePoly::Render draws it; then the view kept
// for the next frame. The last frame's UVs are the PS2's buffer's pixels
// over 512; here they are put on the top screen as the vertices are, and
// from there into the copy, whose columns run up the screen and rows
// across it (capture.c's tiled_index).
static void display_radial_blur(TrackView* v, eView* view)
{
    eRenderTarget*  rt = view->pRenderTarget0;
    TextureInfo*    info;
    TrackTex*       t;
    GeoTexture      gt;
    GeoRenderVertex q[4];
    ePoly           polys[4];
    ePoly           prev;
    float           mid[2];
    uint8_t         blend;
    int             n, i;

    n = radialblur_mask_polys(view, polys);
    if (n == 0) {
        s_blurPrevFull = false;
        return;
    }
    info = (TextureInfo*)view->pBlendMask;
    t    = load_texture(v, info);
    if (t == NULL || !t->valid
        || gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        v->blurFailed++;
        s_blurPrevFull = false;
        return;
    }
    gt.tex        = &t->tex;
    gt.uvScale[0] = t->uvScale[0];
    gt.uvScale[1] = t->uvScale[1];
    gt.pass       = t->pass;
    // Render blends a semitransparent texture alone; RADIALBLUR is one.
    blend = info->IsAnySemitransparencyFlag ? poly_blend(&polys[0])
                                            : GEO_BLEND_NONE;
    for (i = 0; i < n; i++) {
        epoly_screen(&polys[i], rt, q, mid);
        georender_draw_quad(q, &gt, blend,
                            depth_of_gs_z((float)ee_trunc_w(
                                polys[i].Vertices[0].z)));
    }

    if (s_blurPrevFull && radialblur_previous_poly(view, &prev)) {
        epoly_screen(&prev, rt, q, mid);
        for (i = 0; i < 4; i++) {
            float sx, sy;

            target_to_screen(q[i].st[0] * 512.0f, q[i].st[1] * 512.0f,
                             rt->ScissorW, rt->ScissorH, rt->AspectRatioX,
                             rt->AspectRatioY, &sx, &sy);
            q[i].st[0] = (240.0f - sy) / 256.0f;
            q[i].st[1] = sx / 512.0f;
        }
        memset(&gt, 0, sizeof gt);
        gt.tex              = &s_blurPrev;
        gt.uvScale[0]       = 1.0f;
        gt.uvScale[1]       = 1.0f;
        gt.pass.noAlphaTest = true;
        georender_draw_quad(q, &gt, poly_blend(&prev),
                            depth_of_gs_z((float)ee_trunc_w(
                                prev.Vertices[0].z)));
        v->blurBlends++;
    }
    copy_blur_previous();
}

// ------------------------------------------------------ the black and white

// The view's colour for eAttachBlackAndWhite's draw back, copied as the
// blur's last frame is, but read texel for texel, as the GS's sprites
// read it. Made at the egg's first frame, kept to the track's end.
static C3D_Tex s_greyCopy;
static bool    s_greyCopyMade;
static bool    s_greyCopyNoHeap;        // the linear heap had no 512 KB

static void free_grey_copy(void)
{
    if (s_greyCopyMade) {
        C3D_TexDelete(&s_greyCopy);
    }
    memset(&s_greyCopy, 0, sizeof s_greyCopy);
    s_greyCopyMade   = false;
    s_greyCopyNoHeap = false;
}

// eAttachBlackAndWhite (retail 0x0011a9f0), the main chain's last, while a
// track is up (InGameFlag): with ForceBlackAndWhite, the Black & White
// egg's (stomper.h), or a player view's NisBlackAndWhite, each player view
// with the egg, or Active with an Active target and its own flag, is drawn
// over again as its green (eview.h). After the fog, before the blur, the
// mirror and the HUD, which stay in colour. The top screen is view 1's,
// and the 3DS has no view 2 to draw.
static void black_and_white(TrackView* v, eView* view)
{
    static const float kX[4] = { 0.0f, 400.0f, 0.0f, 400.0f };
    static const float kY[4] = { 0.0f, 0.0f, 240.0f, 240.0f };
    eRenderTarget*  rt = view->pRenderTarget0;
    GeoTexture      gt;
    GeoRenderVertex q[4];
    int             i;

    if (!InGameFlag
        || (!ForceBlackAndWhite
            && !eGetView(EVIEW_ID_PLAYER1)->NisBlackAndWhite
            && !eGetView(EVIEW_ID_PLAYER2)->NisBlackAndWhite)) {
        return;
    }
    if (!ForceBlackAndWhite
        && (!view->Active || rt == NULL || !rt->Active
            || !view->NisBlackAndWhite)) {
        return;
    }
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS
        || !copy_top_screen(&s_greyCopy, &s_greyCopyMade, &s_greyCopyNoHeap,
                            GPU_NEAREST)) {
        v->greyFailed++;
        return;
    }
    memset(&gt, 0, sizeof gt);
    gt.tex              = &s_greyCopy;
    gt.uvScale[0]       = 1.0f;
    gt.uvScale[1]       = 1.0f;
    gt.pass.noAlphaTest = true;
    memset(q, 0, sizeof q);
    for (i = 0; i < 4; i++) {
        q[i].pos[0] = kX[i];
        q[i].pos[1] = kY[i];
        q[i].st[0]  = (240.0f - kY[i]) / 256.0f;
        q[i].st[1]  = kX[i] / 512.0f;
        memset(q[i].colour, 0x80, 4);
    }
    if (georender_draw_green_quad(q, &gt)) {
        v->greyDrawn++;
    } else {
        v->greyFailed++;
    }
}

// ------------------------------------------------------ the depth of field

// The depth buffer's copy, read texel for texel, and the colour's, read
// bilinear as the GS's jitter passes read the frame: made at the first
// frame with a blur, kept to the track's end.
static C3D_Tex s_focusDepth;
static bool    s_focusDepthMade;
static bool    s_focusDepthNoHeap;
static C3D_Tex s_focusColour;
static bool    s_focusColourMade;
static bool    s_focusColourNoHeap;

static void free_focus_copies(void)
{
    if (s_focusDepthMade) {
        C3D_TexDelete(&s_focusDepth);
    }
    if (s_focusColourMade) {
        C3D_TexDelete(&s_focusColour);
    }
    memset(&s_focusDepth, 0, sizeof s_focusDepth);
    memset(&s_focusColour, 0, sizeof s_focusColour);
    s_focusDepthMade    = false;
    s_focusDepthNoHeap  = false;
    s_focusColourMade   = false;
    s_focusColourNoHeap = false;
    georender_focus_free();
}

// eAttachDepthOfField's draw for view 1 (retail 0x00119f70, efocus.h),
// after the fog and before the black and white, so the mirror and the HUD
// stay sharp: the plan fog_frame made into the frame's alpha, read from
// the depth buffer's copy; then the frame's copy at each jitter into the
// half target, the first in its place where retail clears it to black and
// adds each; then the half target back over the frame by that alpha. The
// jitter is retail's sixteenths of a PS2 pixel, here on the 400 by 240,
// and each sample's far edges are the frame's, where the copy's texture
// runs on past them. The plan reads the depth by the race's Z range, 16 to
// 0x800000; a frame in another is left sharp, and counted.
static void depth_of_field(TrackView* v)
{
    static const float kX[4] = { 0.0f, 400.0f, 0.0f, 400.0f };
    static const float kY[4] = { 0.0f, 0.0f, 240.0f, 240.0f };
    static const float kU[4] = { 0.0f, (float)GEO_FOCUS_SIZE, 0.0f,
                                 (float)GEO_FOCUS_SIZE };
    const EFocusPlan*  p = &s_focusPlan;
    GeoRenderVertex    q[4];
    int                samples, n, i;

    if (!s_focusPlanned || !s_focusBlurred || p->Count == 0) {
        return;
    }
    if ((s_zRange->ZMin - 2.0f) * 4194304.0f != 16.0f
        || s_zRange->ZMax != 4.0f
        || gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS
        || !copy_top_buffer(&s_focusDepth, &s_focusDepthMade,
                            &s_focusDepthNoHeap, GPU_NEAREST, true)
        || !copy_top_buffer(&s_focusColour, &s_focusColourMade,
                            &s_focusColourNoHeap, GPU_LINEAR, false)) {
        v->focusFailed++;
        return;
    }

    memset(q, 0, sizeof q);
    for (i = 0; i < 4; i++) {
        q[i].pos[0] = kX[i];
        q[i].pos[1] = kY[i];
        q[i].st[0]  = (240.0f - kY[i]) / 256.0f;
        q[i].st[1]  = kX[i] / 512.0f;
        memset(q[i].colour, 0xff, 4);
    }
    for (n = 0; n < p->Count; n++) {
        if (!georender_draw_focus_step(q, &s_focusDepth, &p->Step[n],
                                       p->At[n])) {
            v->focusFailed++;
            return;
        }
    }

    if (!georender_focus_begin()) {
        v->focusFailed++;
        return;
    }
    samples = FocusJitterSamples < 0 ? 0
            : FocusJitterSamples > 6 ? 6 : FocusJitterSamples;
    for (n = 0; n < (samples > 0 ? samples : 1); n++) {
        float jx = 0.0f, jy = 0.0f;

        if (samples > 0) {
            jx = (float)FocusJitter[n][0] * (400.0f / 512.0f / 16.0f);
            jy = (float)FocusJitter[n][1] * (240.0f / 448.0f / 16.0f);
        }
        for (i = 0; i < 4; i++) {
            float sx = jx + (400.0f - jx) * kU[i] / (float)GEO_FOCUS_SIZE;
            float sy = jy + (240.0f - jy) * kY[i] / 240.0f;

            q[i].pos[0] = kU[i];
            q[i].pos[1] = kY[i];
            q[i].st[0]  = (240.0f - sy) / 256.0f;
            q[i].st[1]  = sx / 512.0f;
        }
        // No samples is the clear alone: black.
        if (!georender_draw_focus_sample(q, &s_focusColour,
                                         samples > 0 ? (uint8_t)JitterBlend
                                                     : 0,
                                         n > 0)) {
            georender_focus_end();
            v->focusFailed++;
            return;
        }
    }
    georender_focus_end();

    for (i = 0; i < 4; i++) {
        q[i].pos[0] = kX[i];
        q[i].pos[1] = kY[i];
        q[i].st[0]  = kX[i] / 400.0f;
        q[i].st[1]  = kY[i] / (float)GEO_FOCUS_SIZE;
    }
    if (georender_draw_focus_blur(q)) {
        v->focusDrawn++;
    } else {
        v->focusFailed++;
    }
}

// DisplayRVMs (retail 0x0010edc8), for view 0 after its scene and before
// the HUD: target 7 at GS (160, 20) to (352, 84) of the 512 by 448, its
// UVs mirrored left to right, blended by the alpha DisplayRVMImages left.
// The top screen has the 512 by 448 as its 400 by 240.
static void display_rvms(TrackView* v)
{
    static const float kX[4] = { 160.0f, 352.0f, 160.0f, 352.0f };
    static const float kY[4] = { 20.0f, 20.0f, 84.0f, 84.0f };
    static const float kS[4] = { 1.0f, 0.0f, 1.0f, 0.0f };
    static const float kT[4] = { 0.0f, 0.0f, 1.0f, 1.0f };
    const C3D_Tex*  tex = georender_mirror_texture();
    GeoTexture      gt;
    GeoRenderVertex q[4];
    int             i;

    if (!v->mirrorDrawn || tex == NULL) {
        return;
    }
    if (gpuCmdBufSize - gpuCmdBufOffset < CMDBUF_GUARD_WORDS) {
        return;
    }
    memset(&gt, 0, sizeof gt);
    gt.tex        = (C3D_Tex*)tex;
    gt.uvScale[0] = 1.0f;
    gt.uvScale[1] = 1.0f;
    memset(q, 0, sizeof q);
    for (i = 0; i < 4; i++) {
        q[i].pos[0] = kX[i] * (400.0f / 512.0f);
        q[i].pos[1] = kY[i] * (240.0f / 448.0f);
        q[i].st[0]  = kS[i];
        q[i].st[1]  = kT[i];
        memset(q[i].colour, 0x80, 4);
    }
    georender_draw_quad(q, &gt, GEO_BLEND_ALPHA, -1.0f);
}

void trackview_draw(TrackView* v)
{
    eView*   view = eGetView(EVIEW_ID_PLAYER1);
    float    tanx, fovy;
    uint32_t profSince;

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

    // eDisplayFrame makes each view current before its chain (0x001131fc):
    // WorldObject::Render culls by the current view's clip matrix.
    eSetCurrentView(view);
    s_draw        = v;
    s_worldView   = view->WorldViewMatrix;
    s_zRange      = eview_z_range(view->pRenderTarget0);
    v->drawn        = 0;
    v->drawnTris    = 0;
    v->drawnInPlace = 0;
    v->skinned      = 0;
    v->skinsDropped = 0;
    v->cmdSkipped   = 0;
    v->stripsDrawn  = 0;
    v->stripsDropped = 0;
    v->stripsJoined  = 0;
    v->spritesDrawn   = 0;
    v->spritesDropped = 0;
    v->spritesRefused = 0;
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
    hangwatch_mark("the sky begun");
    georender_run_begin();
    StuffSky(view);
    draw_deferred(v, true);
    georender_run_end();
    georender_set_zwrite(true);
    v->skyDrawn    = v->drawn;
    hangwatch_gpu_stage("the sky");
    FRAMEPROF_STAMP(FRAMEPROF_SKY);

    georender_set_fog(s_fogOn ? &s_fog : NULL, s_fogColour);
    // eModel::Render for each model draws only through georender, so it
    // is one run (georender_run_begin).
    hangwatch_mark("the models begun");
    georender_run_begin();
    scenery_stuff_scenery(&v->cull, view);
    georender_run_end();
    hangwatch_gpu_stage("the models");
    hangwatch_gpu_send();
    FRAMEPROF_STAMP(FRAMEPROF_MODELS);

    // Then StuffSun (0x00112ecc), after DrawNisObjects, which has nothing
    // to draw here. Its quads draw at once; see render_epoly. Then
    // RenderClans (0x001132c4), the skid marks, with the view's
    // WorldScreenClipMatrix: their quads go on their textures' lists, as
    // strips, and draw with the scenery's list below. Then
    // RenderWorldObjects (0x001cdb20, after RenderPlayers): the spike
    // strips' belts. Then the tunnels' light flares
    // (eRenderWorldLightFlares, 0x00116778) and the effects
    // (RenderEffects, FrameEffects' and WorldEffects'), which wait on the
    // lists, and the scenery's chain ends with AttachSolidPolys alone
    // (0x001134a4).
    v->sunQuads       = 0;
    v->sunQuadsFailed = 0;
    georender_set_fog(s_fogOn ? &s_skyFog : NULL, s_fogColour);
    s_quadTarget = view->pRenderTarget0;
    hangwatch_mark("the sun begun");
    StuffSun(view);
    s_quadTarget = NULL;
    georender_set_fog(s_fogOn ? &s_fog : NULL, s_fogColour);
    hangwatch_mark("the skids begun");
    render_clans(view->WorldScreenClipMatrix, view);
    // RenderCameraMovers (0x0011333c), every view's, after the track
    // routes: the Zone Preview's comet, whose quads go through
    // gEPolyRender3DFn as the skids' do.
    hangwatch_mark("the camera movers begun");
    render_camera_movers(view);
    hangwatch_mark("the world objects begun");
    georender_run_begin();
    render_world_objects(view);
    georender_run_end();
    el_render_world_light_flares(view);
    render_effects(view);
    georender_run_begin();
    draw_deferred(v, false);
    georender_run_end();
    hangwatch_gpu_stage("the sun and the scenery's list");
    FRAMEPROF_STAMP(FRAMEPROF_SCENERY);

    // The cars' chain (0x0011363c): RenderCars for the view, and its
    // AttachSolidPolys. Then AttachAlphaPolys (0x001137cc) draws the
    // scenery's alpha list and the cars' together. RenderFrontEndCars
    // draws nothing in a race.
    // The sky, the scenery's list and these draw only through georender,
    // so each is a run too.
    hangwatch_mark("the cars begun");
    georender_run_begin();
    render_cars(view);
    // The mirror's angles over these, as retail's order leaves them.
    render_cars_restore_angles();
    profSince = bGetTicker();
    draw_deferred(v, false);
    draw_deferred(v, true);
    georender_run_end();
    FRAMEPROF_CAR_PART(FRAMEPROF_C_LISTS, &profSince);
    hangwatch_gpu_stage("the cars and the alpha lists");
    FRAMEPROF_STAMP(FRAMEPROF_CARS);
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
    // The depth of field, the fog's chain's last (0x001138ac), then the
    // main chain's black and white (0x00113900), then the radial blur,
    // then the mirror, after the view's scene and before the HUD
    // (0x00113a54 and 0x00113a64, then 0x00113af4). The render eggs are
    // put back between the blur and the mirror (0x00113a90) and set again
    // at the frame's end (0x00113d7c), after the HUD's EndFrame; here at
    // trackview_draw's, before the HUD, which reads nothing they stomp.
    depth_of_field(v);
    black_and_white(v, view);
    display_radial_blur(v, view);
    SuspendRenderEggs();
    display_rvms(v);
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
    ResumeRenderEggs();
}

// ------------------------------------------------------------ the frontend

bool trackview_attach_frontend(TrackView* v)
{
    if (v->loaded) {
        return true;
    }
    if (!engine_ready(v)) {
        return false;
    }
    v->solid   = (GeoSolid*)calloc(TRACKVIEW_MAX_OTHER, sizeof *v->solid);
    v->info    = (TrackSolid*)calloc(TRACKVIEW_MAX_OTHER, sizeof *v->info);
    v->texture = (TrackTex*)calloc(TRACKVIEW_MAX_TEXTURES, sizeof *v->texture);
    if (!v->solid || !v->info || !v->texture) {
        free(v->solid);
        free(v->info);
        free(v->texture);
        v->solid   = NULL;
        v->info    = NULL;
        v->texture = NULL;
        snprintf(v->note, sizeof v->note, "out of memory for the tables");
        return false;
    }
    v->numSolids = 0;
    v->frontend  = true;
    v->attached  = true;
    setup_view();
    v->loaded = true;
    snprintf(v->note, sizeof v->note, "frontend");
    return true;
}

// The other solids, the textures and the flipbook frames, all of them,
// to be found again as they are drawn. Only the frontend's view does
// this: a track's solids keep pointers into the textures.
static void forget_all(TrackView* v)
{
    int i;

    for (i = v->numSolids; i < v->numSolids + v->numOther; i++) {
        forget_solid(&v->info[i]);
    }
    for (i = 0; i < v->numTextures; i++) {
        if (v->texture[i].valid) {
            C3D_TexDelete(&v->texture[i].own);
        }
    }
    for (i = 0; i < v->numFrames; i++) {
        C3D_TexDelete(&v->frame[i].tex);
    }
    v->numOther    = 0;
    v->numTextures = 0;
    v->numFrames   = 0;
    memset(v->texBucket, 0, sizeof v->texBucket);
}

void trackview_forget_later(TrackView* v)
{
    if (v->loaded && v->frontend) {
        v->forgetPending = true;
    }
}

void trackview_free_later(TrackView* v)
{
    if (v->loaded && v->frontend) {
        v->freePending = true;
    }
}

void trackview_frame_begun(TrackView* v)
{
    int i;

    if (!v->loaded) {
        return;
    }
    if (v->frontend && (v->freePending || v->forgetPending)) {
        forget_all(v);
        v->forgetPending = false;
    }
    if (v->frontend && v->freePending) {
        free(v->solid);
        free(v->info);
        free(v->texture);
        memset(v, 0, sizeof *v);
        return;
    }
    for (i = v->numSolids; i < v->numSolids + v->numOther; i++) {
        if (v->info[i].dirty && v->info[i].mesh.edit == NULL) {
            forget_solid(&v->info[i]);
        }
    }
}

void trackview_solid_changed(TrackView* v, const void* solid)
{
    int i;

    if (!v->loaded || v->info == NULL) {
        return;
    }
    for (i = v->numSolids; i < v->numSolids + v->numOther; i++) {
        if (v->solid[i].header == (const uint8_t*)solid
            && other_is(&v->solid[i], (const eSolid*)solid)
            && v->info[i].baked) {
            v->info[i].dirty = true;
        }
    }
}

bool trackview_draw_frontend(TrackView* v, void (*render)(void*),
                             void* user)
{
    eView*          view = eGetView(EVIEW_ID_PLAYER1);
    const TrackTex* env  = NULL;
    float           tanx, fovy;

    if (!v->loaded || !v->frontend || !FrameMemoryBuffer[0]) {
        return false;
    }

    // eDisplayFrame's start: new frame memory, the view mode and view 1's
    // matrices from its camera, which SelectCarCameraMover moves. The
    // frontend culls nothing.
    georender_quads_rewind();
    v->cacheClock++;
    eSwapFrameMallocBuffers();
    MaybeChangeViewMode();
    // The frontend's ALPHA_2 is its own, 72, whatever EnvPassAlpha says.
    georender_set_env_replace(false);
    eview_set_max_z(view->pRenderTarget0);
    eview_calculate_view_matrices(view, 0.0f, 0.0f, 0.0f);

    // The race's projection; see trackview_draw.
    tanx = (float)view->pRenderTarget0->ScissorW * 0.5f / view->H;
    fovy = 2.0f * atanf(tanx * 240.0f / 400.0f);
    Mtx_PerspTilt(&s_proj, fovy, 400.0f / 240.0f, view->NearZ, view->FarZ,
                  false);
    georender_set_light(0.0f, 0.0f, 1.0f, 0.0f, 0.0f, 0.0f, 1.0f);

    // The seams the race's view sets too, and lets go of when it is freed.
    gEModelRenderFn = render_model;
    gEModelRenderStripsBonesFn = render_model_bones;
    gEPolyRender3DFn = render_epoly_3d;
    gEStripFns      = kStripFns;
    gExStripFns     = kExStripFns;
    s_draw        = v;
    s_worldView   = view->WorldViewMatrix;
    s_zRange      = eview_z_range(view->pRenderTarget0);
    v->drawn        = 0;
    v->drawnTris    = 0;
    v->drawnInPlace = 0;
    v->skinned      = 0;
    v->skinsDropped = 0;
    v->cmdSkipped   = 0;
    v->stripsDrawn  = 0;
    v->stripsDropped = 0;
    v->stripsJoined  = 0;
    v->spritesDrawn   = 0;
    v->spritesDropped = 0;
    v->spritesRefused = 0;
    begin_view(v);
    georender_set_fog(NULL, 0);
    georender_set_depth_range(view->NearZ, view->FarZ);
    georender_set_zwrite(true);

    // elSetupLightContext's frontend branch points the environment map at
    // CARSELECTENVMAP (pTextureInfoCarSelectEnvMap, eFixUpTables') where
    // the race's is target 14.
    if (pTextureInfoCarSelectEnvMap != NULL) {
        env = load_texture(v, (const TextureInfo*)pTextureInfoCarSelectEnvMap);
    }
    georender_set_env_texture(env && env->valid ? &env->tex : NULL);

    // 0x00112c1c: the cars, their solid strips; view 0's Flailer layers
    // 24 to 20 (drawn already); RenderFlailerModels' RENDER, the effects
    // (the nebula's, FrameEffects') and AttachSolidPolys. Then the
    // reflections, the cars' alpha strips, AttachSolidPolys and
    // AttachAlphaPolys.
    georender_run_begin();
    render_front_end_cars(view, 1, 0, 1, 0);
    if (render != NULL) {
        render(user);
    }
    render_effects(view);
    draw_deferred(v, false);
    render_front_end_cars(view, 0, 1, 1, 1);
    render_front_end_cars(view, 1, 0, 0, 1);
    draw_deferred(v, false);
    draw_deferred(v, true);
    georender_run_end();
    s_draw = NULL;
    georender_set_env_texture(NULL);

    // eDisplayFrame's end: the flipbooks' next frames.
    UpdateTextureAnimations();
    follow_flipbooks(v);

    // As trackview_draw leaves it for citro2d.
    C3D_AlphaTest(false, GPU_ALWAYS, 0);
    C3D_AlphaBlend(GPU_BLEND_ADD, GPU_BLEND_ADD, GPU_SRC_ALPHA,
                   GPU_ONE_MINUS_SRC_ALPHA, GPU_SRC_ALPHA,
                   GPU_ONE_MINUS_SRC_ALPHA);
    if ((int)gpuCmdBufOffset > v->cmdPeakWords) {
        v->cmdPeakWords = (int)gpuCmdBufOffset;
    }
    eFrameCounter++;
    return true;
}
