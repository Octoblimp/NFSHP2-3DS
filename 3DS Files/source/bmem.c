// bmem -- see bmem.h.

#include "bmem.h"

#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>

static BMemMallocHook g_malloc;
static BMemFreeHook   g_free;

// bMalloc(int, int)'s alignment, 0x0023ef98.
static size_t pool_alignment(int pool)
{
    if (pool & 0x40)
        return 128;
    if (pool & 0x20)
        return 64;
    return (pool & 0x10) ? 32 : 4;
}

void *bMalloc(int size, const char *name, int flags, int pool)
{
    size_t align = pool_alignment(pool);
    void  *p;

    if (g_malloc != NULL)
        return g_malloc(size, name, flags, pool);
    // The image's bMalloc cannot fail: bWare asserts inside the bank
    // allocator. A NULL here would be written through at once. free()
    // takes a memalign block back as it takes malloc's.
    p = align > 8 ? memalign(align, (size_t)size) : malloc((size_t)size);
    if (p == NULL) {
        fprintf(stderr, "bMalloc: %d bytes for %s\n", size, name);
        abort();
    }
    return p;
}

void bFree(void *p)
{
    if (g_free != NULL) {
        g_free(p);
        return;
    }
    free(p);
}

void bSetMemoryHooks(BMemMallocHook m, BMemFreeHook f)
{
    if (m == NULL || f == NULL) {
        g_malloc = NULL;
        g_free = NULL;
        return;
    }
    g_malloc = m;
    g_free = f;
}
