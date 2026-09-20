#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// bWare's chunk container -- the format every HP2 asset file is built from.
// See docs/formats/bchunk.md. There is no file header: the first 8 bytes of
// a .BIN/.BUN are already the first chunk.
//
// This is deliberately free of <3ds.h> so the same code can be exercised on
// the host by tools/src/texpack_test.c; the decoders it feeds are the part
// worth testing against tools/texture_convert.py's output.

typedef struct {
    uint32_t type;
    uint32_t size;   // payload only -- the 8-byte header is not counted
} BChunkHeader;

// Bit 31 of Type marks a chunk whose payload is itself a chunk sequence.
#define BCHUNK_IS_CONTAINER(t) (((t) & 0x80000000u) != 0)

typedef struct {
    const uint8_t* base;     // start of the region being walked
    size_t         end;      // one past its last byte
    size_t         pos;      // offset of the next header
    uint32_t       type;     // current chunk, valid after bchunk_next()
    uint32_t       size;
    const uint8_t* payload;
} BChunkIter;

// Walks the chunk sequence in buf[off, off+len).
void bchunk_begin(BChunkIter* it, const uint8_t* buf, size_t off, size_t len);

// Advances to the next chunk. Returns false at the end of the region or on
// a header that would run past it -- a truncated file stops cleanly rather
// than walking off the buffer.
//
// A Type == 0, Size == 0 header is inter-chunk padding, not a terminator, so
// this skips it and keeps going. Containers are *not* descended into; call
// bchunk_begin() on the payload to do that.
bool bchunk_next(BChunkIter* it);

// Finds the first chunk of `type` directly inside buf[off, off+len), without
// descending into containers. Returns its payload and stores the payload size
// in *outSize, or NULL if there is none.
const uint8_t* bchunk_find(const uint8_t* buf, size_t off, size_t len,
                           uint32_t type, uint32_t* outSize);

// Same, but searches the whole tree depth-first, descending into containers.
const uint8_t* bchunk_find_deep(const uint8_t* buf, size_t off, size_t len,
                                uint32_t type, uint32_t* outSize);

// What a bchunk_walk() visitor asks the walk to do next.
typedef enum {
    BCHUNK_SKIP = 0,   // do not descend into this chunk
    BCHUNK_ENTER,      // descend (only meaningful for a container)
    BCHUNK_STOP,       // end the walk
} BChunkAction;

typedef BChunkAction (*BChunkVisitor)(uint32_t type, const uint8_t* payload,
                                      uint32_t size, int depth, void* user);

// Depth-first walk of every chunk in buf[off, off+len), containers included.
// The visitor decides whether each container is entered, which is what lets a
// caller enumerate (say) every texture pack in a bundle without also paying
// to walk the geometry. Returns false if a visitor asked to stop.
bool bchunk_walk(const uint8_t* buf, size_t off, size_t len,
                 BChunkVisitor visit, void* user);

// bStringHash (0x0023b280) -- the one string hash the engine uses, for
// texture names, font names, archive paths and the English text table alike.
// A djb2 variant seeded with -1 rather than 5381; see tools/bhash.py.
static inline uint32_t bchunk_hash(const char* s)
{
    uint32_t h = 0xffffffffu;
    while (*s) h = h * 33u + (uint32_t)(unsigned char)*s++;
    return h;
}

// Reads a little-endian word out of a payload. The PS2 is little-endian and
// so is the ARM11, so these exist for alignment safety, not byte order: chunk
// payloads are 16-byte aligned but their inner records are not all 4-aligned.
static inline uint32_t bchunk_u32(const uint8_t* p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

static inline uint16_t bchunk_u16(const uint8_t* p)
{
    return (uint16_t)((uint32_t)p[0] | ((uint32_t)p[1] << 8));
}

static inline float bchunk_f32(const uint8_t* p)
{
    union { uint32_t u; float f; } c;
    c.u = bchunk_u32(p);
    return c.f;
}

// The mirrors, for the few fields the game writes back into a loaded chunk
// (menu item colours, object positions). Same alignment-safe byte-at-a-time
// form as the readers.
static inline void bchunk_put_u32(uint8_t* p, uint32_t v)
{
    p[0] = (uint8_t)v;         p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16); p[3] = (uint8_t)(v >> 24);
}

static inline void bchunk_put_f32(uint8_t* p, float f)
{
    union { uint32_t u; float f; } c;
    c.f = f;
    bchunk_put_u32(p, c.u);
}
