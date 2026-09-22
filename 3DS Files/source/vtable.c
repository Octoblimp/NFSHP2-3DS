// vtable -- see vtable.h.

#include "vtable.h"

#include <stdio.h>
#include <stdlib.h>

// The image has about sixty vtables and the task-25 classes reach a dozen of
// them, so a flat list searched from the front is enough; a dispatch is a
// handful of compares against a handful of dispatches per car per frame.
#define VT_MAX 96

typedef struct VtTable {
    uint32_t       image;
    const VtEntry *entries;
    int            count;
} VtTable;

static VtTable vt_tables[VT_MAX];
static int     vt_count;

void vt_install(uint32_t image, const VtEntry *entries, int count)
{
    int i;

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
}

void vt_reset(void)
{
    vt_count = 0;
}

const VtEntry *vt_slot(uint32_t image, int slot)
{
    int i, k = VT_SLOT(slot);

    for (i = 0; i < vt_count; i++) {
        if (vt_tables[i].image != image)
            continue;
        if (slot % 8 != 0 || k <= 0 || k >= vt_tables[i].count
            || !vt_tables[i].entries[k].fn)
            break;
        return &vt_tables[i].entries[k];
    }
    fprintf(stderr, "vt_slot: no entry at +%d of the vtable at 0x%08lx\n",
            slot, (unsigned long)image);
    abort();
}
