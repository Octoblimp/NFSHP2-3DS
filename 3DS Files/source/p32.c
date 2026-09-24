// p32 -- see p32.h. Empty on a 32-bit target, where the header's casts are
// the whole implementation.

#include "p32.h"

#if UINTPTR_MAX != 0xffffffffu

#include <stdio.h>
#include <stdlib.h>

// A PhysicsCar is fourteen objects on one list; a harness scenario that
// builds a few systems and their components stays far below this.
#define P32_MAX 4096

static const void *p32_table[P32_MAX];
static uint32_t    p32_count;

uint32_t p32_of(const void *p)
{
    uint32_t i;

    if (p == NULL)
        return 0;
    for (i = 0; i < p32_count; i++) {
        if (p32_table[i] == p)
            return i + 1;
    }
    if (p32_count == P32_MAX) {
        fprintf(stderr, "p32_of: more than %d handles\n", P32_MAX);
        abort();
    }
    p32_table[p32_count] = p;
    return ++p32_count;
}

void *p32_ptr(uint32_t h)
{
    if (h == 0)
        return NULL;
    if (h > p32_count) {
        fprintf(stderr, "p32_ptr: handle %lu was never handed out\n",
                (unsigned long)h);
        abort();
    }
    return (void *)p32_table[h - 1];
}

void p32_reset(void)
{
    p32_count = 0;
}

#endif
