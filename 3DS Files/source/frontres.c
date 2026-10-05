// frontres -- see frontres.h.
#include "frontres.h"

#include <malloc.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bchunkload.h"

#define SOLID_LIST_ID   0x80034000u
#define FRONTRES_CHUNKS 64      // FRONTB has 21 top-level chunks

// The chunks loaded, in file order: where each one is (the solid list's
// copy for that one) and its size with its header.
static uint8_t *s_chunk[FRONTRES_CHUNKS];
static int32_t  s_size[FRONTRES_CHUNKS];
static int      s_num;
static uint8_t *s_copy;         // the solid list's copy's allocation
static bool     s_loaded;

bool frontres_load(uint8_t *data, size_t len)
{
    size_t o;

    if (s_loaded) {
        return true;
    }
    if (data == NULL) {
        return false;
    }
    s_num = 0;
    for (o = 0; o + 8 <= len && s_num < FRONTRES_CHUNKS;) {
        uint32_t id   = bchunk_u32(data + o);
        size_t   size = 8 + (size_t)bchunk_u32(data + o + 4);
        uint8_t *at   = data + o;

        if (size > len - o) {
            break;
        }
        // A fresh copy, as far into its first 128 bytes as the chunk is
        // into its 128 in the file, so that what the chunk aligns inside
        // itself stays aligned.
        if (id == SOLID_LIST_ID && s_copy == NULL) {
            size_t skew = (uintptr_t)at & 127u;

            s_copy = (uint8_t *)memalign(128, skew + size);
            if (s_copy == NULL) {
                return false;
            }
            memcpy(s_copy + skew, at, size);
            at = s_copy + skew;
        }
        s_chunk[s_num]  = at;
        s_size[s_num++] = (int32_t)size;
        o += size;
    }

    // ResourceFile's load: LoadChunks over the file, then PostLoadFixup.
    for (int i = 0; i < s_num; i++) {
        load_chunks(s_chunk[i], s_size[i]);
    }
    post_load_fixup();
    s_loaded = true;
    return true;
}

void frontres_unload(void)
{
    if (!s_loaded) {
        return;
    }
    // UnloadChunks walks the file backwards (TraverseChunksBackwards).
    for (int i = s_num - 1; i >= 0; i--) {
        unload_chunks(s_chunk[i], s_size[i]);
    }
    free(s_copy);
    s_copy   = NULL;
    s_num    = 0;
    s_loaded = false;
    post_load_fixup();
}

bool frontres_loaded(void)
{
    return s_loaded;
}
