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

#ifdef __3DS__
#include <citro3d.h>

// Decodes level `level` and uploads it as a C3D_Tex in GPU_RGBA8, tiling into
// the 3DS's 8x8 Morton order on the way. The texture is allocated here and
// belongs to the caller (C3D_TexDelete).
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
#endif
