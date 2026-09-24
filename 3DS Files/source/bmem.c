// bmem -- see bmem.h.

#include "bmem.h"

#include <stdio.h>
#include <stdlib.h>

static BMemMallocHook g_malloc;
static BMemFreeHook   g_free;

void *bMalloc(int size, const char *name, int flags, int pool)
{
    void *p;

    if (g_malloc != NULL)
        return g_malloc(size, name, flags, pool);
    // The image's bMalloc cannot fail: bWare asserts inside the bank
    // allocator. A NULL here would be written through at once.
    p = malloc((size_t)size);
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
