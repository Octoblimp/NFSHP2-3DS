#include "texpack.h"

#include <string.h>

// --- finding a pack ------------------------------------------------------

typedef struct {
    const uint8_t* buf;
    uint32_t       skip;
    size_t         hitOff;
    uint32_t       hitSize;
    bool           found;
} PackHunt;

static BChunkAction pack_visitor(uint32_t type, const uint8_t* payload,
                                 uint32_t size, int depth, void* user)
{
    PackHunt* h = (PackHunt*)user;
    (void)depth;
    if (type == TEXPACK_CHUNK) {
        if (h->skip == 0) {
            h->hitOff  = (size_t)(payload - h->buf);
            h->hitSize = size;
            h->found   = true;
            return BCHUNK_STOP;
        }
        h->skip--;
        return BCHUNK_SKIP;      // no packs nested inside a pack
    }
    // Only containers can hold one, and a .BUN nests them several deep.
    return BCHUNK_IS_CONTAINER(type) ? BCHUNK_ENTER : BCHUNK_SKIP;
}

bool texpack_open_nth(TexPack* tp, const uint8_t* buf, size_t off, size_t len,
                      uint32_t skip)
{
    PackHunt hunt = { buf, skip, 0, 0, false };
    bchunk_walk(buf, off, len, pack_visitor, &hunt);
    if (!hunt.found) return false;

    memset(tp, 0, sizeof(*tp));
    tp->buf     = buf;
    tp->packOff = hunt.hitOff - 8;

    uint32_t       sz  = 0;
    const uint8_t* hdr = bchunk_find(buf, hunt.hitOff, hunt.hitSize,
                                     TEXPACK_HEADER_CHUNK, &sz);
    if (hdr) {
        size_t n = sz < sizeof(tp->name) - 1 ? sz : sizeof(tp->name) - 1;
        memcpy(tp->name, hdr, n);
        tp->name[n] = '\0';
    }
    tp->info = bchunk_find(buf, hunt.hitOff, hunt.hitSize,
                           TEXPACK_INFO_CHUNK, &tp->infoSize);
    tp->data = bchunk_find(buf, hunt.hitOff, hunt.hitSize,
                           TEXPACK_DATA_CHUNK, &tp->dataSize);
    if (!tp->info || !tp->data) return false;

    // ImagePlacement and PalettePlacement are relative to the data payload
    // rounded UP to a 128-byte boundary, not to the payload itself:
    //
    //   001008a8  addiu  s2,v0,143      ; v0 + 8 (the payload) + 135
    //   001008b0  and    s2,s2,a3       ; a3 = -128
    //
    // in LoaderTexturePack (0x00100830). The packer fills the gap with 0x11
    // bytes. The game aligns the loaded address; the bundle is loaded at a
    // 128-byte-aligned address, so aligning the offset within the file comes
    // out the same. Without this every texture is rolled sideways by up to
    // 127 bytes.
    {
        size_t pad = (size_t)(-(ptrdiff_t)(tp->data - buf)) & 127u;
        if (pad >= tp->dataSize) return false;
        tp->data     += pad;
        tp->dataSize -= pad;
    }

    tp->count = tp->infoSize / TEXPACK_RECORD_SIZE;
    return tp->count > 0;
}

bool texpack_open(TexPack* tp, const uint8_t* buf, size_t off, size_t len)
{
    return texpack_open_nth(tp, buf, off, len, 0);
}

// --- the TextureInfo record ---------------------------------------------

bool texpack_get(const TexPack* tp, uint32_t index, TexInfo* out)
{
    if (index >= tp->count) return false;
    const uint8_t* r = tp->info + (size_t)index * TEXPACK_RECORD_SIZE;

    memset(out, 0, sizeof(*out));
    out->record = r;
    memcpy(out->name, r + 0x08, 24);
    out->name[24] = '\0';

    out->hash       = bchunk_u32(r + 0x20);
    out->width      = bchunk_u16(r + 0x24);
    out->height     = bchunk_u16(r + 0x26);
    out->bpp        = r[0x28];
    out->palEntries = bchunk_u16(r + 0x2a);
    out->pixelOff   = bchunk_u32(r + 0x30);
    out->clutOff    = bchunk_u32(r + 0x34);
    out->pixelBytes = bchunk_u32(r + 0x38);
    out->clutBytes  = bchunk_u32(r + 0x3c);
    out->sharesWith = bchunk_u32(r + 0x40);
    out->psm        = r[0x4a];

    int levels = (int)(int8_t)r[0x6e] + 1;   // NumMipMapLevels excludes the base
    if (levels < 1) levels = 1;
    if (levels > TEXPACK_MAX_LEVELS) levels = TEXPACK_MAX_LEVELS;
    out->levels = (uint8_t)levels;

    // TextureImageInfo[7] at 0x52: u16 base pointer, u8 TBW, s8 swizzle flag.
    for (int i = 0; i < levels; i++)
        out->swizzled[i] = (int8_t)r[0x52 + i * 4 + 3];

    // The scroll tail. RenderSingleFlailerBitmap reads the type with `lb`, so
    // it is signed; only 0, 1 and 2 occur on this disc.
    out->scrollType = (int8_t)r[0x79];
    out->scrollS    = bchunk_f32(r + 0x7c);
    out->scrollT    = bchunk_f32(r + 0x80);
    out->scrollStep = bchunk_f32(r + 0x84);

    out->mmag = r[0x6f];
    out->mmin = r[0x70];
    return true;
}

float texpack_scroll_axis(float time, float speed, int type, float step)
{
    if (type == 0) return 0.0f;

    // Type 2 steps: time / step truncated back to a whole number of steps.
    // The original divides unguarded and would hand (int) an infinity if a
    // step were zero; none on the disc is, and both this and the converter's
    // scroll_uv() return 0 there rather than invoke undefined behaviour.
    if (type == 2) time = (step != 0.0f) ? (float)(int)(time / step) : 0.0f;

    // The EE's cvt.w.s truncates towards zero, which is what a C cast does.
    float f = time * speed;
    return f - (float)(int)f;
}

void texpack_scroll(const TexInfo* ti, float time, float* outS, float* outT)
{
    if (outS) *outS = texpack_scroll_axis(time, ti->scrollS, ti->scrollType,
                                          ti->scrollStep);
    if (outT) *outT = texpack_scroll_axis(time, ti->scrollT, ti->scrollType,
                                          ti->scrollStep);
}

bool texpack_find(const TexPack* tp, uint32_t hash, TexInfo* out)
{
    for (uint32_t i = 0; i < tp->count; i++) {
        const uint8_t* r = tp->info + (size_t)i * TEXPACK_RECORD_SIZE;
        if (bchunk_u32(r + 0x20) == hash) return texpack_get(tp, i, out);
    }
    return false;
}

bool texpack_level(const TexInfo* ti, int level, uint32_t* outW, uint32_t* outH,
                   uint32_t* outOff, uint32_t* outBytes)
{
    if (level < 0 || level >= (int)ti->levels) return false;
    uint32_t off = 0;
    for (int l = 0; l <= level; l++) {
        uint32_t w = ti->width  >> l;
        uint32_t h = ti->height >> l;
        if (w == 0) w = 1;
        if (h == 0) h = 1;
        uint32_t n = w * h * ti->bpp / 8;
        if (l == level) {
            if (outW)     *outW     = w;
            if (outH)     *outH     = h;
            if (outOff)   *outOff   = off;
            if (outBytes) *outBytes = n;
            return true;
        }
        off += n;
    }
    return false;
}

size_t texpack_decode_size(const TexInfo* ti, int level)
{
    uint32_t w, h;
    if (!texpack_level(ti, level, &w, &h, NULL, NULL)) return 0;
    return (size_t)w * h * 4;
}

// --- the PS2 texture swizzle ---------------------------------------------
//
// A texture whose Is32BitSwizzelled byte is set was uploaded to the GS as a
// PSMCT32 image half as wide -- half as tall again for 8bpp, a quarter for
// 4bpp -- and read back through TEX0 as PSMT8/PSMT4, so the file holds the
// bytes in GS page/block/column order. These two functions are the closed
// form of "where does the GS find texel (x, y)", ported from
// tools/texture_convert.py; the derivation is in docs/formats/texture-pack.md.
//
// The Python side memoises a whole index table per size. Here the arithmetic
// is done per pixel instead: it is a handful of shifts, and a 256x256 table
// would be 256 KB of linear heap we do not have to spend.

static inline uint32_t swizzle_src8(uint32_t x, uint32_t y, uint32_t w)
{
    uint32_t pageY = y >> 6, py = y & 63;
    uint32_t blockY = py >> 4, cy = py & 15;
    uint32_t col = cy >> 2;
    uint32_t swap = ((cy >> 1) & 1) ^ (col & 1);
    uint32_t base = pageY * 64 * w + blockY * 16 * w + col * 4 * w
                  + (cy & 1) * 2 * w + ((cy >> 1) & 1);

    uint32_t pageX = x >> 7, px = x & 127;
    uint32_t blockX = px >> 4, cx = px & 15;
    return base + pageX * 256 + blockX * 32
         + ((cx >> 3) & 1) * 2 + (cx & 1) * 4 + ((cx >> 1) & 1) * 8
         + ((((cx >> 2) & 1) ^ swap)) * 16;
}

// Returns a *nibble* index: byte = n >> 1, low nibble when (n & 1) == 0.
static inline uint32_t swizzle_src4(uint32_t x, uint32_t y, uint32_t w)
{
    uint32_t pageY = y >> 7, py = y & 127;
    uint32_t blockY = py >> 4, cy = py & 15;
    uint32_t col = cy >> 2;
    uint32_t swap = ((cy >> 1) & 1) ^ (col & 1);
    uint32_t base = pageY * 128 * w + col * 8 * w + (cy & 1) * 4 * w
                  + blockY * 64 + ((cy >> 1) & 1);

    uint32_t pageX = x >> 7, px = x & 127;
    uint32_t blockX = px >> 5, cx = px & 31;
    return base + pageX * 512 + blockX * 32 * w
         + ((cx >> 3) & 1) * 2 + ((cx >> 4) & 1) * 4
         + (cx & 1) * 8 + ((cx >> 1) & 1) * 16
         + ((((cx >> 2) & 1) ^ swap)) * 32;
}

// The closed form only holds when the host raster is a whole number of
// PSMCT32 pages wide and a whole number of blocks tall. Every flagged texture
// in the build satisfies this; an unflagged one is plain raster anyway.
static inline bool geometry_closes(uint32_t w, uint32_t h, uint8_t bpp)
{
    return (w % 128) == 0 && (h % (bpp == 8 ? 64u : 128u)) == 0;
}

// --- decoding ------------------------------------------------------------

static inline uint8_t alpha_ps2(uint8_t a)
{
    // 0x80 is fully opaque on the GS, so the byte doubles into 0..255. One
    // texture (OPEL_KMH) carries alpha above that, hence the clamp.
    uint32_t v = (uint32_t)a * 2;
    return (uint8_t)(v > 255 ? 255 : v);
}

bool texpack_decode(const TexPack* tp, const TexInfo* ti, int level,
                    uint8_t* out, size_t outCap)
{
    uint32_t w, h, lvlOff, lvlBytes;
    if (!texpack_level(ti, level, &w, &h, &lvlOff, &lvlBytes)) return false;
    if (w == 0 || h == 0 || lvlBytes == 0) return false;
    if (outCap < (size_t)w * h * 4) return false;

    size_t base = (size_t)ti->pixelOff + lvlOff;
    if (base + lvlBytes > tp->dataSize) return false;
    const uint8_t* px = tp->data + base;

    if (ti->bpp == 32) {
        for (size_t i = 0; i < (size_t)w * h; i++) {
            out[i * 4 + 0] = px[i * 4 + 0];
            out[i * 4 + 1] = px[i * 4 + 1];
            out[i * 4 + 2] = px[i * 4 + 2];
            out[i * 4 + 3] = alpha_ps2(px[i * 4 + 3]);
        }
        return true;
    }
    if (ti->bpp != 4 && ti->bpp != 8) return false;
    if (ti->clutBytes == 0) return false;
    if ((size_t)ti->clutOff + ti->clutBytes > tp->dataSize) return false;

    const uint8_t* clut    = tp->data + ti->clutOff;
    uint32_t       entries = ti->clutBytes / 4;
    if (entries == 0) return false;

    // A PSMT8 CLUT is stored in GS CSM1 order: inside every group of 32,
    // entries 8..15 and 16..23 are the other way round, which is the bit 3 /
    // bit 4 swap below. bWare names the permutation itself --
    // RemapLinearIntoClut8 (0x00118878) is what the engine calls on palettes
    // it *builds*, and all it does is exchange those two quadword pairs. Pack
    // CLUTs never go through it, so they arrive already in that order.
    // A PSMT4 CLUT is linear: its CSM1 region is 8x2 words, with nothing to
    // exchange. See docs/formats/texture-pack.md.
    const bool clut8 = (ti->bpp == 8);

    bool unswizzle = ti->swizzled[level] == 1 && geometry_closes(w, h, ti->bpp);

    for (uint32_t y = 0; y < h; y++) {
        for (uint32_t x = 0; x < w; x++) {
            uint32_t idx;
            if (ti->bpp == 8) {
                uint32_t s = unswizzle ? swizzle_src8(x, y, w) : y * w + x;
                if (s >= lvlBytes) return false;
                idx = px[s];
            } else {
                uint32_t s = unswizzle ? swizzle_src4(x, y, w) : y * w + x;
                if ((s >> 1) >= lvlBytes) return false;
                idx = (px[s >> 1] >> ((s & 1) * 4)) & 0xf;
            }
            if (idx >= entries) idx = 0;
            if (clut8 && (idx & 0x18u) != 0 && (idx & 0x18u) != 0x18u
                && (idx ^ 0x18u) < entries)
                idx ^= 0x18u;          // 8..15 <-> 16..23 in every 32
            uint8_t* d = out + ((size_t)y * w + x) * 4;
            d[0] = clut[idx * 4 + 0];
            d[1] = clut[idx * 4 + 1];
            d[2] = clut[idx * 4 + 2];
            d[3] = alpha_ps2(clut[idx * 4 + 3]);
        }
    }
    return true;
}

// --- mip chains ----------------------------------------------------------

// The smallest power of two >= n, floored at 8 because that is one Morton
// tile and the GPU's minimum texture dimension.
static uint32_t pot_ceil(uint32_t n)
{
    uint32_t p = 8;
    while (p < n) p <<= 1;
    return p;
}

int texpack_chain(const TexInfo* ti, int base, uint32_t* outW, uint32_t* outH)
{
    uint32_t w, h, pw, ph, side;
    int      n = 1;

    if (!texpack_level(ti, base, &w, &h, NULL, NULL)) return 0;
    pw = pot_ceil(w);
    ph = pot_ceil(h);
    // The PICA200's smallest level is 8 texels on the shorter side. The
    // disc's own chains go no further: all 960 levels below the base in
    // TEX12LOCATION are at least 8 on each side.
    for (side = pw < ph ? pw : ph; side > 8 && n < TEXPACK_CHAIN_MAX; side >>= 1)
        n++;
    if (outW) *outW = pw;
    if (outH) *outH = ph;
    return n;
}

uint8_t texpack_cutout_alpha(const uint8_t* rgba, size_t texels)
{
    uint8_t hi = 0;
    for (size_t i = 0; i < texels; i++) {
        uint8_t a = rgba[i * 4 + 3];
        if (a == 0 || a == hi) continue;
        if (hi != 0) return 0;
        hi = a;
    }
    return hi;
}

// --- the format ------------------------------------------------------------

// Whether an (r, g, b, raw PS2 alpha) texel is opaque and gray.
static inline void classify(const uint8_t* c, bool* opaque, bool* gray)
{
    if (c[3] < 0x7f) *opaque = false;          // alpha_ps2() under 254
    if (c[0] != c[1] || c[1] != c[2]) *gray = false;
}

static TexPackFormat format_of(bool opaque, bool gray)
{
    return gray ? (opaque ? TEXPACK_FMT_L8 : TEXPACK_FMT_LA8)
                : (opaque ? TEXPACK_FMT_RGB8 : TEXPACK_FMT_RGBA8);
}

TexPackFormat texpack_format_levels(const TexPack* tp, const TexInfo* ti,
                                    int base, int count)
{
    bool opaque = true, gray = true;
    int  end = base + count < (int)ti->levels ? base + count
                                              : (int)ti->levels;

    if (ti->bpp == 32) {
        for (int l = base; l < end && (opaque || gray); l++) {
            uint32_t w, h, off, bytes;
            if (!texpack_level(ti, l, &w, &h, &off, &bytes)) break;
            size_t at = (size_t)ti->pixelOff + off;
            if (at + bytes > tp->dataSize) break;
            for (size_t i = 0; i < (size_t)w * h; i++)
                classify(tp->data + at + i * 4, &opaque, &gray);
        }
        return format_of(opaque, gray);
    }
    if (ti->bpp != 4 && ti->bpp != 8) return TEXPACK_FMT_RGBA8;
    if ((size_t)ti->clutOff + ti->clutBytes > tp->dataSize)
        return TEXPACK_FMT_RGBA8;

    const uint8_t* clut    = tp->data + ti->clutOff;
    uint32_t       entries = ti->clutBytes / 4;
    if (entries == 0 || entries > 256) return TEXPACK_FMT_RGBA8;

    // Every entry first: most CLUTs are all one kind, and then which of
    // them the levels use does not matter.
    for (uint32_t e = 0; e < entries; e++)
        classify(clut + e * 4, &opaque, &gray);
    if (opaque && gray) return TEXPACK_FMT_L8;

    // Otherwise the entries the levels use. The unswizzle is a permutation
    // of a level's indices, as is the CSM1 swap of the CLUT's, so these are
    // the level's bytes or nibbles in any order, through the same mapping.
    bool used[256] = { false };
    for (int l = base; l < end; l++) {
        uint32_t w, h, off, bytes;
        if (!texpack_level(ti, l, &w, &h, &off, &bytes)) break;
        size_t at = (size_t)ti->pixelOff + off;
        if (at + bytes > tp->dataSize) break;
        const uint8_t* px = tp->data + at;
        for (uint32_t s = 0; s < w * h; s++) {
            uint32_t idx;
            if (ti->bpp == 8) {
                if (s >= bytes) break;
                idx = px[s];
            } else {
                if ((s >> 1) >= bytes) break;
                idx = (px[s >> 1] >> ((s & 1) * 4)) & 0xf;
            }
            if (idx >= entries) idx = 0;
            if (ti->bpp == 8 && (idx & 0x18u) != 0 && (idx & 0x18u) != 0x18u
                && (idx ^ 0x18u) < entries)
                idx ^= 0x18u;
            used[idx] = true;
        }
    }
    opaque = gray = true;
    for (uint32_t e = 0; e < entries; e++)
        if (used[e]) classify(clut + e * 4, &opaque, &gray);
    return format_of(opaque, gray);
}

TexPackFormat texpack_format(const TexPack* tp, const TexInfo* ti, int base)
{
    return texpack_format_levels(tp, ti, base, texpack_chain(ti, base, NULL,
                                                             NULL));
}

size_t texpack_chain_bytes(const TexInfo* ti, int base, TexPackFormat f)
{
    uint32_t pw, ph;
    int      n = texpack_chain(ti, base, &pw, &ph);
    size_t   bytes = 0;

    for (int i = 0; i < n; i++)
        bytes += (size_t)(pw >> i) * (ph >> i) * texpack_format_bytes(f);
    return bytes;
}

// A decoded w x h image into a cw x ch level of format f, its right column
// and bottom row repeated over the rest, as texpack_upload() pads.
static void tile_padded(uint8_t* dst, TexPackFormat f, const uint8_t* rgba,
                        uint32_t w, uint32_t h, uint32_t cw, uint32_t ch)
{
    for (uint32_t y = 0; y < ch; y++) {
        const uint8_t* row = rgba + (size_t)(y < h ? y : h - 1) * w * 4;
        for (uint32_t x = 0; x < cw; x++) {
            const uint8_t* s = row + (size_t)(x < w ? x : w - 1) * 4;
            texpack_texel_put(dst, texpack_tiled_index(x, y, cw), f,
                              ((uint32_t)s[3]) | ((uint32_t)s[2] << 8)
                            | ((uint32_t)s[1] << 16) | ((uint32_t)s[0] << 24));
        }
    }
}

bool texpack_chain_tiled(const TexPack* tp, const TexInfo* ti, int base,
                         uint32_t* const level[], uint8_t* scratch,
                         size_t scratchCap)
{
    uint8_t* bytes[TEXPACK_CHAIN_MAX];
    int      n = texpack_chain(ti, base, NULL, NULL);

    // GPU_RGBA8's (a, b, g, r) is the word on a little-endian host, as on
    // the 3DS.
    for (int i = 0; i < n; i++)
        bytes[i] = (uint8_t*)level[i];
    return texpack_chain_tiled_as(tp, ti, base, TEXPACK_FMT_RGBA8, bytes,
                                  scratch, scratchCap);
}

bool texpack_chain_tiled_as(const TexPack* tp, const TexInfo* ti, int base,
                            TexPackFormat f, uint8_t* const level[],
                            uint8_t* scratch, size_t scratchCap)
{
    uint32_t pw, ph, w, h;
    int      n = texpack_chain(ti, base, &pw, &ph);
    uint8_t  cutout = 0;

    for (int i = 0; i < n; i++) {
        uint32_t cw = pw >> i, ch = ph >> i;

        // The disc's own level where it has one.
        if (base + i < (int)ti->levels
            && texpack_level(ti, base + i, &w, &h, NULL, NULL)
            && w <= cw && h <= ch
            && texpack_decode(tp, ti, base + i, scratch, scratchCap)) {
            if (i == 0) cutout = texpack_cutout_alpha(scratch, (size_t)w * h);
            tile_padded(level[i], f, scratch, w, h, cw, ch);
            continue;
        }
        if (i == 0) return false;

        // Otherwise the 2x2 mean of the level above. The disc's own chains
        // come out that way in colour (within 2-5 of 255 on every level of
        // TEX12LOCATION). A cut-out texture's levels keep its two alphas:
        // of the disc's, 99% of texels with 3 or 4 opaque parents are
        // opaque, 70% with 2, and 0.2% with 1. So half or more is opaque.
        // The four texels under one are four in a row, x then y. A format
        // with no alpha reads 255 there, and stores none of what is made.
        for (uint32_t y = 0; y < ch; y++) {
            for (uint32_t x = 0; x < cw; x++) {
                uint32_t k = texpack_tiled_index(2 * x, 2 * y, 2 * cw);
                uint32_t s[4], d = 0;

                for (int j = 0; j < 4; j++)
                    s[j] = texpack_texel_get(level[i - 1], k + j, f);
                for (int c = 0; c < 32; c += 8) {
                    uint32_t sum = ((s[0] >> c) & 0xff) + ((s[1] >> c) & 0xff)
                                 + ((s[2] >> c) & 0xff) + ((s[3] >> c) & 0xff);
                    uint32_t v = (sum + 2) >> 2;

                    if (c == 0 && cutout)       // alpha is the low byte
                        v = sum >= 2u * cutout ? cutout : 0;
                    d |= v << c;
                }
                texpack_texel_put(level[i], texpack_tiled_index(x, y, cw), f,
                                  d);
            }
        }
    }
    return n > 0;
}

#ifdef __3DS__
#include <3ds.h>
#include <stdlib.h>

// The decode scratch comes from the linear heap, which has megabytes to
// spare once a race has loaded, where the main heap can be down to 1.5 MB
// and that in pieces: six cars' 512x320 skins, 640 KB of scratch each,
// went missing on TRACKB45 with traffic in the race, and those cars drew
// as their reflection alone (2026-10-07). The main heap is the fallback.
// Each caller asks for it after making the texture, so that giving it
// back leaves no hole below the texture.
static void* scratch_alloc(size_t n, bool* linear)
{
    void* p = linearAlloc(n);

    *linear = p != NULL;
    return p != NULL ? p : malloc(n);
}

static void scratch_free(void* p, bool linear)
{
    if (linear) linearFree(p);
    else free(p);
}

GPU_TEXCOLOR texpack_gpu_format(TexPackFormat f)
{
    switch (f) {
    case TEXPACK_FMT_RGB8: return GPU_RGB8;
    case TEXPACK_FMT_LA8:  return GPU_LA8;
    case TEXPACK_FMT_L8:   return GPU_L8;
    default:               return GPU_RGBA8;
    }
}

bool texpack_upload(const TexPack* tp, const TexInfo* ti, int level,
                    C3D_Tex* out)
{
    uint32_t w, h;
    if (!texpack_level(ti, level, &w, &h, NULL, NULL)) return false;
    if (w == 0 || h == 0 || w > 1024 || h > 1024) return false;

    // The GS takes any size; the PICA200 takes powers of two only, and
    // three quarters of FRONTB.BUN is neither (LOADING is 512x184,
    // TOP_BORDER 512x24, ARROWBLK_L 24x24). Refusing those is what left the
    // title screen showing PRESS START on an empty field, so pad instead:
    // the image goes in the top-left of a power-of-two allocation and the
    // rest stays transparent. The caller scales by the image size and takes
    // UVs against out->width/out->height, which are the padded ones.
    uint32_t      aw = pot_ceil(w), ah = pot_ceil(h);
    TexPackFormat f = texpack_format_levels(tp, ti, level, 1);
    bool          linear;

    if (!C3D_TexInit(out, (u16)aw, (u16)ah, texpack_gpu_format(f)))
        return false;
    uint8_t* rgba = (uint8_t*)scratch_alloc((size_t)w * h * 4, &linear);
    if (!rgba) {
        C3D_TexDelete(out);
        return false;
    }
    if (!texpack_decode(tp, ti, level, rgba, (size_t)w * h * 4)) {
        scratch_free(rgba, linear);
        C3D_TexDelete(out);
        return false;
    }

    // The padding repeats the edge texel rather than being cleared, so that
    // GPU_LINEAR at the image's right and bottom edges blends with a copy of
    // itself -- exactly what CLAMP_TO_EDGE did before, and no seam.
    tile_padded((uint8_t*)out->data, f, rgba, w, h, aw, ah);
    C3D_TexFlush(out);
    C3D_TexSetFilter(out, GPU_LINEAR, GPU_LINEAR);
    C3D_TexSetWrap(out, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    scratch_free(rgba, linear);
    return true;
}

bool texpack_upload_chain(const TexPack* tp, const TexInfo* ti, int base,
                          C3D_Tex* out)
{
    return texpack_upload_chain_as(tp, ti, base, texpack_format(tp, ti, base),
                                   out);
}

static bool upload_chain(const TexPack* tp, const TexInfo* ti, int base,
                         TexPackFormat f, C3D_Tex* out, bool vram)
{
    uint32_t pw, ph;
    int      n = texpack_chain(ti, base, &pw, &ph);
    size_t   cap = texpack_decode_size(ti, base);
    uint8_t* level[TEXPACK_CHAIN_MAX];
    uint8_t* build = NULL;
    uint8_t* scratch;
    u32      total = 0;
    bool     ok, linear;

    if (n < 1 || pw > 1024 || ph > 1024 || cap == 0) return false;

    // The made levels are made in the texture itself, from the level
    // above it there: a 512x320 car skin took 1.25 MB of the heap padded
    // and halved beside it, which the heap did not have once a race had
    // loaded, and the car drew without its paint (2026-10-05). One in
    // VRAM is made in a linear copy of itself.
    C3D_TexInitParams p = { (u16)pw, (u16)ph, (u8)(n - 1),
                            texpack_gpu_format(f), GPU_TEX_2D, vram };
    if (!C3D_TexInitWithParams(out, NULL, p)) return false;
    if (vram) {
        total = C3D_TexCalcTotalSize(out->size, out->maxLevel);
        build = (uint8_t*)linearAlloc(total);
        if (!build) {
            C3D_TexDelete(out);
            return false;
        }
    }
    scratch = (uint8_t*)scratch_alloc(cap, &linear);
    if (!scratch) {
        if (build) linearFree(build);
        C3D_TexDelete(out);
        return false;
    }
    for (int i = 0; i < n; i++)
        level[i] = (uint8_t*)C3D_TexGetImagePtr(out, build ? build : out->data,
                                                i, NULL);
    ok = texpack_chain_tiled_as(tp, ti, base, f, level, scratch, cap);
    scratch_free(scratch, linear);
    if (ok && build) {
        // C3D_TexLoadImage's copy into VRAM, the whole chain at once: its
        // levels lie one after another, as they do in the texture.
        GSPGPU_FlushDataCache(build, total);
        C3D_SyncTextureCopy((u32*)build, 0, (u32*)out->data, 0, total, 8);
    }
    if (build) linearFree(build);
    if (!ok) {
        C3D_TexDelete(out);
        return false;
    }
    if (!vram) C3D_TexFlush(out);

    // The record's filters. MMIN 2-5 are GL's NEAREST_MIPMAP_NEAREST,
    // NEAREST_MIPMAP_LINEAR, LINEAR_MIPMAP_NEAREST and
    // LINEAR_MIPMAP_LINEAR; 0 and 1 have no mips on the GS, and take the
    // nearer level's filter between levels here.
    C3D_TexSetFilter(out, ti->mmag ? GPU_LINEAR : GPU_NEAREST,
                     (ti->mmin == 1 || ti->mmin >= 4) ? GPU_LINEAR
                                                      : GPU_NEAREST);
    C3D_TexSetFilterMipmap(out, (ti->mmin == 3 || ti->mmin == 5)
                                    ? GPU_LINEAR : GPU_NEAREST);
    C3D_TexSetWrap(out, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    return true;
}

bool texpack_upload_chain_as(const TexPack* tp, const TexInfo* ti, int base,
                             TexPackFormat f, C3D_Tex* out)
{
    return upload_chain(tp, ti, base, f, out, false);
}

bool texpack_upload_chain_vram(const TexPack* tp, const TexInfo* ti, int base,
                               TexPackFormat f, C3D_Tex* out)
{
    return upload_chain(tp, ti, base, f, out, true);
}
#endif
