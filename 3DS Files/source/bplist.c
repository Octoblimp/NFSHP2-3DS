// bplist -- see bplist.h.

#include "bplist.h"

#include <stdio.h>
#include <stdlib.h>

BSlotPool *bPNodeSlotPool;

void bplist_init(int32_t n)
{
    if (bPNodeSlotPool == NULL)
        bPNodeSlotPool = bNewSlotPool((int)sizeof(bPNode), n,
                                      "bPNode SlotPool", 16);
}

void bplist_close(void)
{
    if (bPNodeSlotPool != NULL) {
        bDeleteSlotPool(bPNodeSlotPool);
        bPNodeSlotPool = NULL;
    }
}

bPNode *bpnode_malloc(void)
{
    if (bPNodeSlotPool == NULL)
        bplist_init(32);
    return (bPNode *)bSlotOMalloc(bPNodeSlotPool);
}

void bpnode_free(void *p)
{
    if (bPNodeSlotPool == NULL) {
        fprintf(stderr, "bplist: a bPNode freed with no pool\n");
        abort();
    }
    bSlotFree(bPNodeSlotPool, p);
}
