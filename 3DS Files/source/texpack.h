#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bchunk.h"

// TexturePack (chunk 0xb0300001) -- the GS texture atlas every UI bitmap and
// every car/track skin comes out of. Format: docs/formats/texture-pack.md.
// This is a C port of the decode half of tools/texture_convert.py, and
// tools/src/texpack_test.c checks the two against each other pixel for pixel
// over a whole pack, so this file is not trusted on inspection alone.
//
// No <3ds.h> above: everything down to texpack_decode() is plain C and builds
// on the host. Only texpack_upload() at the bottom is 3DS-only.

#define TEXPACK_CHUNK        0xb0300001u
#define TEXPACK_HEADER_CHUNK 0x30300002u
#define TEXPACK_INFO_CHUNK   0x30300003u
#define TEXPACK_DATA_CHUNK   0x30300004u

#define TEXPACK_RECORD_SIZE  164
#define TEXPACK_MAX_LEVELS   7

typedef struct {
    const uint8_t* buf;        // the file the pack lives in
    size_t         packOff;    // offset of the 0xb0300001 header
    const uint8_t* info;       // 0x30300003 payload -- the TextureInfo table
    uint32_t       infoSize;
    const uint8_t* data;       // 0x30300004 payload -- CLUTs and pixels
    uint32_t       dataSize;
    uint32_t       count;      // textures in the table
    char           name[20];   // pack name from 0x30300002 ("HUD", "TRACK", ...)
} TexPack;

typedef struct {
    const uint8_t* record;     // the 164-byte TextureInfo itself
    char           name[25];
    uint32_t       hash;       // bStringHash(name) -- the lookup key
    uint16_t       width;
    uint16_t       height;
    uint8_t        bpp;        // 4, 8 or 32
    uint8_t        psm;        // 0x00 PSMCT32, 0x13 PSMT8, 0x14 PSMT4
    uint16_t       palEntries;
    uint32_t       pixelOff;   // into the 0x30300004 blob
    uint32_t       pixelBytes; // the whole mip chain
    uint32_t       clutOff;
    uint32_t       clutBytes;
    uint32_t       sharesWith; // hash of the texture whose pixels these are, or 0
    uint8_t        levels;     // NumMipMapLevels + 1, so always >= 1
    // One TextureImageInfo per level. The swizzle flag is per level and they
    // genuinely differ within a chain, so decoding has to consult this array
    // rather than the record's level-0 copy at 0x55.
    int8_t         swizzled[TEXPACK_MAX_LEVELS];

    // The UV animation in the record's tail: ScrollType at 0x79, the two
    // speeds at 0x7c and 0x80 and the time step at 0x84. 27 of the disc's
    // texture records scroll; see texpack_scroll().
    int8_t         scrollType;
    float          scrollS;
    float          scrollT;
    float          scrollStep;

    // The GS's TEX1 filters, MMAG at 0x6f and MMIN at 0x70: MMAG 0 nearest,
    // 1 linear; MMIN 0 and 1 the same with no mips, 2-5 nearest/linear
    // within a level and nearest/linear between levels, GL-style. Every
    // track texture on the disc has MMAG 1 and MMIN 3.
    uint8_t        mmag;
    uint8_t        mmin;
} TexInfo;

// Finds the first texture pack at or below buf[off, off+len) and fills `tp`.
// Bundles nest their packs inside other containers, so this searches the tree.
bool texpack_open(TexPack* tp, const uint8_t* buf, size_t off, size_t len);

// As texpack_open(), but skips the first `skip` packs -- a .BUN can hold more
// than one. Returns false once there are no more.
bool texpack_open_nth(TexPack* tp, const uint8_t* buf, size_t off, size_t len,
                      uint32_t skip);

bool texpack_get(const TexPack* tp, uint32_t index, TexInfo* out);

// Looks a texture up by bStringHash of its name, which is how Flailer bitmaps
// and fonts reference their art. Returns false if this pack has no such hash.
bool texpack_find(const TexPack* tp, uint32_t hash, TexInfo* out);

// Geometry of one mip level. Levels are packed base-first with no padding,
// each halving both dimensions; summing them reproduces pixelBytes exactly.
bool texpack_level(const TexInfo* ti, int level, uint32_t* outW, uint32_t* outH,
                   uint32_t* outOff, uint32_t* outBytes);

// Decodes one mip level into `out` as RGBA8888, 4 bytes per pixel, row 0 at
// the top. `outCap` is in bytes and must be at least width * height * 4 for
// that level. Returns false if the level does not exist or does not fit.
//
// Alpha is converted off the PS2's 0..128 scale by doubling and clamping,
// matching the converter.
bool texpack_decode(const TexPack* tp, const TexInfo* ti, int level,
                    uint8_t* out, size_t outCap);

// Bytes texpack_decode() needs for a level, or 0 if there is no such level.
size_t texpack_decode_size(const TexInfo* ti, int level);

// TextureInfo::GetScroll (0x00100a60) for one axis: the fraction to add to a
// texture coordinate at `time` seconds. Type 0 does not scroll; type 1 runs
// continuously; type 2 quantises the time to whole `step` intervals first, so
// it jumps rather than slides. The result is always the fractional part, so a
// caller can add it to a coordinate and let GPU_REPEAT wrap.
//
// The offset is in the *padded* texture's normalised space -- the original
// divides its UVs by the power-of-two allocation size before adding this, and
// so must a citro3d caller over texpack_upload().
float texpack_scroll_axis(float time, float speed, int type, float step);

// Both axes at once, in the order RenderSingleFlailerBitmap (0x00140538)
// reads them. The signs are the PS2's: S grows rightwards and T downwards,
// so a renderer whose v counts up from the bottom subtracts *outT.
void texpack_scroll(const TexInfo* ti, float time, float* outS, float* outT);

// --- mip chains for the PICA200 ---
//
// A chain starts at the disc's level `base`, padded to a power of two on
// each side as texpack_upload() pads, and halves down to 8 texels on the
// shorter side. Level i is the disc's level base + i where the pack has
// it, and the 2x2 mean of level i - 1 where it does not.
#define TEXPACK_CHAIN_MAX 8

// The padded size of the chain's first level and how many levels it has,
// or 0 if the texture has no level `base`.
int texpack_chain(const TexInfo* ti, int base, uint32_t* outW, uint32_t* outH);

// The one nonzero alpha of an RGBA8888 image whose alphas are all 0 or
// that value -- a cut-out, such as a fence -- or 0 for any other image.
uint8_t texpack_cutout_alpha(const uint8_t* rgba, size_t texels);

// Where texel (x, y) of a w-wide level is in the PICA200's layout: 8x8
// tiles, row by row, and Morton order inside each.
static inline uint32_t texpack_tiled_index(uint32_t x, uint32_t y, uint32_t w)
{
    uint32_t m = (x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2)
               | ((x & 4) << 2) | ((y & 4) << 3);
    return ((y >> 3) * (w >> 3) + (x >> 3)) * 64 + m;
}

// The whole chain, in that layout as GPU_RGBA8 takes it: one word a texel,
// (a, b, g, r) from its low byte. level[i] is where level i goes, (w >> i)
// x (h >> i) of the padded size. A level the disc lacks is made from the
// one above it where it already is in level[i - 1], so the only other
// memory is `scratch`, texpack_decode_size(ti, base) bytes, for the disc's
// levels as they decode. A made level of a cut-out keeps its two alphas.
bool texpack_chain_tiled(const TexPack* tp, const TexInfo* ti, int base,
                         uint32_t* const level[], uint8_t* scratch,
                         size_t scratchCap);

// --- the format a chain is stored in ---
//
// Every texel decodes to RGBA8888, but most textures need less of it: one
// whose texels are all opaque needs no alpha, and one whose texels are all
// gray needs one colour. texpack_format() picks the smallest of four
// PICA200 formats that holds the texels exactly, and the chain is stored in
// it. The levels made for the chain are 2x2 means, which keep a texture
// opaque and gray. On the disc this is a fifth off a track's textures and a
// quarter off the cars' (2026-10-08), with nothing different on screen.
//
// Opaque is a decoded alpha of 254 or 255, the PS2's 0x7f or 0x80 doubled:
// most of the disc's opaque art has 0x7f. Without an alpha channel the
// PICA200 reads 255, which is one step in 255 where it is blended at all.
typedef enum {
    TEXPACK_FMT_RGBA8,          // GPU_RGBA8: a texel is (a, b, g, r)
    TEXPACK_FMT_RGB8,           // GPU_RGB8: (b, g, r), alpha 255
    TEXPACK_FMT_LA8,            // GPU_LA8: (a, l), red, green and blue l
    TEXPACK_FMT_L8              // GPU_L8: (l), alpha 255
} TexPackFormat;

static inline uint32_t texpack_format_bytes(TexPackFormat f)
{
    return f == TEXPACK_FMT_RGBA8 ? 4u
         : f == TEXPACK_FMT_RGB8  ? 3u
         : f == TEXPACK_FMT_LA8   ? 2u : 1u;
}

// Texel i of a level stored in format f, as the PICA200 reads it: one word,
// (r << 24) | (g << 16) | (b << 8) | a.
static inline uint32_t texpack_texel_get(const uint8_t* lvl, uint32_t i,
                                         TexPackFormat f)
{
    const uint8_t* p = lvl + (size_t)i * texpack_format_bytes(f);
    uint32_t       l;

    switch (f) {
    case TEXPACK_FMT_RGBA8:
        return p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)
             | ((uint32_t)p[3] << 24);
    case TEXPACK_FMT_RGB8:
        return 0xffu | ((uint32_t)p[0] << 8) | ((uint32_t)p[1] << 16)
             | ((uint32_t)p[2] << 24);
    case TEXPACK_FMT_LA8:
        l = p[1];
        return p[0] | (l << 8) | (l << 16) | (l << 24);
    default:
        l = p[0];
        return 0xffu | (l << 8) | (l << 16) | (l << 24);
    }
}

// And its store: the word's red is a gray format's l.
static inline void texpack_texel_put(uint8_t* lvl, uint32_t i,
                                     TexPackFormat f, uint32_t t)
{
    uint8_t* p = lvl + (size_t)i * texpack_format_bytes(f);

    switch (f) {
    case TEXPACK_FMT_RGBA8:
        p[0] = (uint8_t)t;
        p[1] = (uint8_t)(t >> 8);
        p[2] = (uint8_t)(t >> 16);
        p[3] = (uint8_t)(t >> 24);
        break;
    case TEXPACK_FMT_RGB8:
        p[0] = (uint8_t)(t >> 8);
        p[1] = (uint8_t)(t >> 16);
        p[2] = (uint8_t)(t >> 24);
        break;
    case TEXPACK_FMT_LA8:
        p[0] = (uint8_t)t;
        p[1] = (uint8_t)(t >> 24);
        break;
    default:
        p[0] = (uint8_t)(t >> 24);
        break;
    }
}

// The format for the disc's levels `base` to `base + count - 1`, those of
// them the texture has: the four channels unless every texel the decode
// reads from them is opaque, or gray. An index the CLUT has no entry for
// reads entry 0, as in texpack_decode().
TexPackFormat texpack_format_levels(const TexPack* tp, const TexInfo* ti,
                                    int base, int count);

// The format for the chain from `base`: the disc's levels it takes.
TexPackFormat texpack_format(const TexPack* tp, const TexInfo* ti, int base);

// The bytes the chain from `base` takes in format f, or 0.
size_t texpack_chain_bytes(const TexInfo* ti, int base, TexPackFormat f);

// texpack_chain_tiled() in format f: level[i] is (w >> i) x (h >> i)
// texels of texpack_format_bytes(f) each. RGBA8 is texpack_chain_tiled().
bool texpack_chain_tiled_as(const TexPack* tp, const TexInfo* ti, int base,
                            TexPackFormat f, uint8_t* const level[],
                            uint8_t* scratch, size_t scratchCap);

#ifdef __3DS__
#include <citro3d.h>

// The GPU_TEXCOLOR of a format.
GPU_TEXCOLOR texpack_gpu_format(TexPackFormat f);

// Decodes level `level` and uploads it as a C3D_Tex in the format
// texpack_format_levels() picks for it, tiling into the 3DS's 8x8 Morton
// order on the way. The texture is allocated here and belongs to the caller
// (C3D_TexDelete).
//
// The PICA200 only takes power-of-two dimensions and most of these textures
// are not: 292 of FRONTB.BUN's 397, and LOADING (512x184) and TOP_BORDER
// (512x24) on the title screen. So the allocation is rounded up to the next
// power of two in each axis and the image sits in its top-left corner. The
// caller must therefore size the quad from TexInfo's width/height and take
// its UVs against out->width/out->height, which are the padded ones.
// Anything above 1024 in either axis is still refused.
bool texpack_upload(const TexPack* tp, const TexInfo* ti, int level,
                    C3D_Tex* out);

// As texpack_upload(), with the whole chain from level `base` in one
// texture of format f and the record's MMAG/MMIN filters. A third larger
// than level `base` alone, in the linear heap; the heap takes only what
// texpack_upload() takes, the decoded level.
bool texpack_upload_chain_as(const TexPack* tp, const TexInfo* ti, int base,
                             TexPackFormat f, C3D_Tex* out);

// As texpack_upload_chain_as(), into VRAM, which the CPU does not write:
// the chain is built in a linear copy, which the GPU's transfer engine
// copies over whole (C3D_SyncTextureCopy) before the copy is given back.
// Outside a frame only: inside one, citro3d queues the transfer for the
// frame's end. The linear heap lends the chain's size for the while.
bool texpack_upload_chain_vram(const TexPack* tp, const TexInfo* ti, int base,
                               TexPackFormat f, C3D_Tex* out);

// texpack_upload_chain_as() in the format texpack_format() picks.
bool texpack_upload_chain(const TexPack* tp, const TexInfo* ti, int base,
                          C3D_Tex* out);
#endif
