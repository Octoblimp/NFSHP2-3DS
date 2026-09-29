// epositionmarker -- see epositionmarker.h.

#include "epositionmarker.h"

#include <stddef.h>

// Retail makes it empty in a static constructor (_GLOBAL_$I$
// FrameMemoryBufferSize, 0x001a8170); a constant initialiser does the same.
bNode PositionMarkerList = { &PositionMarkerList, &PositionMarkerList };

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
