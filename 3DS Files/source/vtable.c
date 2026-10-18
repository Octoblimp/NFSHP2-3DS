// vtable -- see vtable.h.

#include "vtable.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// The image has about sixty vtables, kept in a flat list in the order they
// are installed and found through vt_buckets below.
#define VT_MAX 96

typedef struct VtTable {
    uint32_t       image;
    const VtEntry *entries;
    int            count;
} VtTable;

static VtTable vt_tables[VT_MAX];
static int     vt_count;

// vt_slot's way in: the tables by their address, open addressed, each
// bucket a table's place in vt_tables plus one and 0 for none. The search
// from the front was a few per cent of a race's CPU (TASKS 46): the
// physics and the AI dispatch through it many times a car a frame.
#define VT_BUCKETS 256

static uint8_t vt_buckets[VT_BUCKETS];

static unsigned vt_bucket(uint32_t image)
{
    return (unsigned)((image >> 3) * 2654435761u >> 24) & (VT_BUCKETS - 1);
}

void vt_install(uint32_t image, const VtEntry *entries, int count)
{
    unsigned h;
    int      i;

    for (i = 0; i < vt_count; i++) {
        if (vt_tables[i].image == image) {
            vt_tables[i].entries = entries;
            vt_tables[i].count   = count;
            return;
        }
    }
    if (vt_count == VT_MAX) {
        fprintf(stderr, "vt_install: more than %d vtables\n", VT_MAX);
        abort();
    }
    vt_tables[vt_count].image   = image;
    vt_tables[vt_count].entries = entries;
    vt_tables[vt_count].count   = count;
    vt_count++;
    for (h = vt_bucket(image); vt_buckets[h] != 0;
         h = (h + 1) & (VT_BUCKETS - 1)) {
    }
    vt_buckets[h] = (uint8_t)vt_count;
}

void vt_reset(void)
{
    vt_count = 0;
    memset(vt_buckets, 0, sizeof vt_buckets);
}

const VtEntry *vt_slot(uint32_t image, int slot)
{
    int      k = VT_SLOT(slot);
    unsigned h;

    for (h = vt_bucket(image); vt_buckets[h] != 0;
         h = (h + 1) & (VT_BUCKETS - 1)) {
        const VtTable *t = &vt_tables[vt_buckets[h] - 1];

        if (t->image != image)
            continue;
        if (slot % 8 != 0 || k <= 0 || k >= t->count || !t->entries[k].fn)
            break;
        return &t->entries[k];
    }
    fprintf(stderr, "vt_slot: no entry at +%d of the vtable at 0x%08lx\n",
            slot, (unsigned long)image);
    abort();
}

const VtEntry *vt_table(uint32_t image, int *count)
{
    int i;

    for (i = 0; i < vt_count; i++) {
        if (vt_tables[i].image == image) {
            *count = vt_tables[i].count;
            return vt_tables[i].entries;
        }
    }
    *count = 0;
    return NULL;
}
