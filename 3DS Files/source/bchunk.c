#include "bchunk.h"

#include <string.h>

void bchunk_begin(BChunkIter* it, const uint8_t* buf, size_t off, size_t len)
{
    it->base    = buf;
    it->pos     = off;
    it->end     = off + len;
    it->type    = 0;
    it->size    = 0;
    it->payload = NULL;
}

bool bchunk_next(BChunkIter* it)
{
    while (it->pos + 8 <= it->end) {
        uint32_t type = bchunk_u32(it->base + it->pos);
        uint32_t size = bchunk_u32(it->base + it->pos + 4);

        if (type == 0 && size == 0) {
            // Padding between chunks. Not a terminator -- keep walking.
            it->pos += 8;
            continue;
        }
        // A size that runs past the region means the file is truncated or
        // this is not chunk data at all. Either way, stop.
        if (size > it->end - it->pos - 8) return false;

        it->type    = type;
        it->size    = size;
        it->payload = it->base + it->pos + 8;
        it->pos    += 8 + size;
        return true;
    }
    return false;
}

const uint8_t* bchunk_find(const uint8_t* buf, size_t off, size_t len,
                           uint32_t type, uint32_t* outSize)
{
    BChunkIter it;
    bchunk_begin(&it, buf, off, len);
    while (bchunk_next(&it)) {
        if (it.type == type) {
            if (outSize) *outSize = it.size;
            return it.payload;
        }
    }
    return NULL;
}

const uint8_t* bchunk_find_deep(const uint8_t* buf, size_t off, size_t len,
                                uint32_t type, uint32_t* outSize)
{
    BChunkIter it;
    bchunk_begin(&it, buf, off, len);
    while (bchunk_next(&it)) {
        if (it.type == type) {
            if (outSize) *outSize = it.size;
            return it.payload;
        }
        if (BCHUNK_IS_CONTAINER(it.type)) {
            size_t payloadOff = (size_t)(it.payload - buf);
            const uint8_t* hit =
                bchunk_find_deep(buf, payloadOff, it.size, type, outSize);
            if (hit) return hit;
        }
    }
    return NULL;
}

static bool walk_rec(const uint8_t* buf, size_t off, size_t len, int depth,
                     BChunkVisitor visit, void* user)
{
    BChunkIter it;
    bchunk_begin(&it, buf, off, len);
    while (bchunk_next(&it)) {
        BChunkAction act = visit(it.type, it.payload, it.size, depth, user);
        if (act == BCHUNK_STOP) return false;
        if (act == BCHUNK_ENTER && BCHUNK_IS_CONTAINER(it.type)) {
            size_t payloadOff = (size_t)(it.payload - buf);
            if (!walk_rec(buf, payloadOff, it.size, depth + 1, visit, user))
                return false;
        }
    }
    return true;
}

bool bchunk_walk(const uint8_t* buf, size_t off, size_t len,
                 BChunkVisitor visit, void* user)
{
    return walk_rec(buf, off, len, 0, visit, user);
}
