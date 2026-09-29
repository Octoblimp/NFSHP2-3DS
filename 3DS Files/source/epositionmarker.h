// epositionmarker -- the position markers of Ecstasy.obj (retail
// 0x001a7e90 .. 0x001a8000): named points in a model's space that the
// art tools leave in a bundle, for where a car's lights shine from and
// where its smoke and sparks come out.
//
//   eFindPositionMarker   0x001a7f78   124 bytes
//
// The loader that puts a bundle's markers on the list, LoaderPositionMarkers
// (0x001a7e90, chunk 0x34013, loader slot 8), is not ported yet, so the
// list stays empty and a search finds nothing. When it is, it links each
// 32-byte record in place by the bNode at its start, as LoaderSolidList
// does solids.
//
// Cross-check: tools/carrenderinfo_check.py. Write-up:
// docs/formats/car-render-info.md.

#ifndef EPOSITIONMARKER_H
#define EPOSITIONMARKER_H

#include <stddef.h>
#include <stdint.h>

#include "blist.h"

// ePositionMarker, 32 bytes (.mdebug). TypeHash is the hash of the model
// the marker belongs to; Param's second byte is what a car's light flares
// take their direction from.
typedef struct ePositionMarker {
    bNode     Node;                         //  0  on PositionMarkerList
    uint32_t  NameHash;                     //  8
    uint32_t  TypeHash;                     // 12
    float     Position[3];                  // 16
    uint32_t  Param;                        // 28
} ePositionMarker;                          // 32

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char epositionmarker_layout_check[
    (sizeof(ePositionMarker) == 32
     && offsetof(ePositionMarker, NameHash) == 8
     && offsetof(ePositionMarker, Position) == 16
     && offsetof(ePositionMarker, Param) == 28) ? 1 : -1];
#endif

// PositionMarkerList, the demo's 0x00323de0 and retail's gp-19328.
extern bNode PositionMarkerList;

// eFindPositionMarker(unsigned int, unsigned int, ePositionMarker *),
// 0x001a7f78: the next marker after `prev` -- from the list's head when
// it is NULL -- that matches, or NULL. With a name, a marker matches when
// it has that name and that type, or that name and `type` is 0. Without
// one, any marker of that type matches. With neither, NULL at once.
ePositionMarker *eFindPositionMarker(uint32_t name_hash, uint32_t type_hash,
                                     ePositionMarker *prev);

#endif
