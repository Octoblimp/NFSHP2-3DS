// epositionmarker -- see epositionmarker.h.

#include "epositionmarker.h"

#include <stddef.h>

#include "bchunk.h"

#define POSITION_MARKERS_ID 0x00034013u

// Retail makes it empty in a static constructor (_GLOBAL_$I$
// FrameMemoryBufferSize, 0x001a8170); a constant initialiser does the same.
bNode PositionMarkerList = { &PositionMarkerList, &PositionMarkerList };

// The records start at the payload rounded up to 16, past the tools'
// filler; the count is what is left of the size over a record. On the
// 3DS a record is the disc's 32 bytes (the layout check above), and a
// host checker lays its records out at the host's size.
static ePositionMarker *first_marker(uint8_t *chunk, uint32_t *n)
{
    uint8_t *data =
        (uint8_t *)(((uintptr_t)chunk + 23u) & ~(uintptr_t)15u);

    *n = (bchunk_u32(chunk + 4) - (uint32_t)(data - (chunk + 8)))
         / (uint32_t)sizeof(ePositionMarker);
    return (ePositionMarker *)(void *)data;
}

int loader_position_markers(uint8_t *chunk)
{
    ePositionMarker *m;
    uint32_t i, n;

    if (bchunk_u32(chunk) != POSITION_MARKERS_ID)
        return 0;
    m = first_marker(chunk, &n);
    for (i = 0; i < n; i++, m++) {
        bNode *last = PositionMarkerList.prev;

        last->next = &m->Node;
        PositionMarkerList.prev = &m->Node;
        m->Node.prev = last;
        m->Node.next = &PositionMarkerList;
    }
    return 1;
}

int unloader_position_markers(uint8_t *chunk)
{
    ePositionMarker *m;
    uint32_t n;

    if (bchunk_u32(chunk) != POSITION_MARKERS_ID)
        return 0;
    m = first_marker(chunk, &n);
    for (; n != 0; n--, m++) {
        bNode *next = m->Node.next, *prev = m->Node.prev;

        prev->next = next;
        next->prev = prev;
    }
    return 1;
}

ePositionMarker *eFindPositionMarker(uint32_t name_hash, uint32_t type_hash,
                                     ePositionMarker *prev)
{
    bNode *n;

    if (name_hash == 0 && type_hash == 0)
        return NULL;
    n = prev != NULL ? prev->Node.next : PositionMarkerList.next;
    for (; n != &PositionMarkerList; n = n->next) {
        ePositionMarker *m = (ePositionMarker *)(void *)n;

        if (name_hash != 0) {
            if (m->NameHash == name_hash
                && (m->TypeHash == type_hash || type_hash == 0))
                return m;
        } else if (m->TypeHash == type_hash) {
            return m;
        }
    }
    return NULL;
}
