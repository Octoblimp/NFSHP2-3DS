// bmem -- see bmem.h.

#include "bmem.h"

#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static BMemMallocHook g_malloc;
static BMemFreeHook   g_free;

void *(*gBMemTopAllocFn)(size_t size, size_t align);
int   (*gBMemTopFreeFn)(void *p);
void (*gBMemNoteFn)(void *p, int size, const char *name);
void (*gBMemForgetFn)(void *p);
void (*gBMemFailFn)(int size, const char *name);

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
    // takes a memalign block back as it takes malloc's. A top block goes
    // to the top's own heap first (bmem.h), and to malloc's only when
    // that has no room.
    p = NULL;
    if ((pool & 8) != 0 && gBMemTopAllocFn != NULL)
        p = gBMemTopAllocFn((size_t)size, align > 8 ? align : 8);
    if (p == NULL)
        p = align > 8 ? memalign(align, (size_t)size) : malloc((size_t)size);
    if (p == NULL) {
        fprintf(stderr, "bMalloc: %d bytes for %s\n", size, name);
        if (gBMemFailFn != NULL)
            gBMemFailFn(size, name);
        abort();
    }
    // Zeroed, as the PS2's pools come to it: the image reads some blocks
    // before it writes them. CarRenderInfo's constructor reconnects the
    // bodies' texture tables while its eModels' constructors have cleared
    // only their names and solids, so NumReplacementTextures is whatever
    // the block held, and a heap block that held anything sends
    // emodel_reconnect_texture_table off through a stale pointer.
    memset(p, 0, (size_t)size);
    if (gBMemNoteFn != NULL)
        gBMemNoteFn(p, size, name);
    return p;
}

void bFree(void *p)
{
    if (g_free != NULL) {
        g_free(p);
        return;
    }
    if (gBMemForgetFn != NULL && p != NULL)
        gBMemForgetFn(p);
    if (gBMemTopFreeFn != NULL && p != NULL && gBMemTopFreeFn(p))
        return;
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
