// topology -- TopologyCoordinate, size only.
//
// `Car` embeds a TopologyCoordinate by value at offset 1280, so Car's layout
// cannot be stated without this record's size and its pointer count. The
// class itself belongs to task 27 (track collision and streaming): eleven
// methods, none of them ported, and `wheel.c` already reaches the one it
// needs -- GetElevation -- through the `gTopologyGetElevationFn` seam rather
// than through a definition.
//
// So this header states the layout and nothing else. The fields are the
// .mdebug ones (`TopologyCoordinate (size=560)`), spelled out rather than
// left as an opaque blob for one reason: `TrackPolygonTable` is 128
// *pointers*, and on a 64-bit host that array alone grows the record by 512
// bytes. A blob would have made Car's size assert agree with the wrong
// number on the host and right only on ARM, which is the failure `wheel.h`'s
// `_pad2` already cost this port once.
//
// Task 27 should replace the members below with the real ones and delete
// this notice. Nothing outside the layout asserts depends on the names.

#ifndef TOPOLOGY_H
#define TOPOLOGY_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

// 13TrackPolygon, 1632 in the .mdebug type table. Opaque here; the table
// below only ever holds pointers to it.
typedef struct TrackPolygon TrackPolygon;

#define TOPOLOGY_MAX_POLYGONS 128

typedef struct TopologyCoordinate {
    bVector2      InterestBBoxMin;                       // 0
    bVector2      InterestBBoxMax;                       // 8
    bVector2      CachedBBoxMin;                         // 16
    bVector2      CachedBBoxMax;                         // 24
    TrackPolygon *TrackPolygonTable[TOPOLOGY_MAX_POLYGONS]; // 32
    int32_t       TotalNumTrackPolygons;                 // 544
    int32_t       NumTrackPolygons;                      // 548
    int32_t       NumVerticalTrackPolygons;              // 552
    int32_t       NumUpsideDownTrackPolygons;            // 556
} TopologyCoordinate;                                    // 560

// 560 on the handheld. On a 64-bit host the 128 pointers widen and nothing
// else does, so every offset past the table shifts by exactly 128 slack
// units and the size follows.
#define TOPOLOGY_SLACK ((size_t)(sizeof(void *) - 4))
#define TOPOLOGY_SIZEOF ((size_t)(560 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK))

#ifndef TOPOLOGY_NO_ASSERT
typedef char topology_layout_check[
    (offsetof(TopologyCoordinate, InterestBBoxMin)  == 0
     && offsetof(TopologyCoordinate, InterestBBoxMax) == 8
     && offsetof(TopologyCoordinate, CachedBBoxMin)   == 16
     && offsetof(TopologyCoordinate, CachedBBoxMax)   == 24
     && offsetof(TopologyCoordinate, TrackPolygonTable) == 32
     && offsetof(TopologyCoordinate, TotalNumTrackPolygons)
        == 544 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumTrackPolygons)
        == 548 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumVerticalTrackPolygons)
        == 552 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && offsetof(TopologyCoordinate, NumUpsideDownTrackPolygons)
        == 556 + TOPOLOGY_MAX_POLYGONS * TOPOLOGY_SLACK
     && sizeof(TopologyCoordinate) == TOPOLOGY_SIZEOF) ? 1 : -1];
#endif

#endif // TOPOLOGY_H
