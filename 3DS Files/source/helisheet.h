// helisheet -- HeliSheet.obj (retail 0x001eb6a8 .. 0x001ebd9c): the
// track's sheet of ground polygons the police helicopter flies over, slot
// 23 of the LoaderTable, and the query that finds the sheet's height
// under a point.
//
// Retail rebuilt the demo's sheet. Its chunk is a container, 0x80034800,
// of two children:
//   - 0x34801, 536 bytes: the HeliSheet below, in place;
//   - 0x34802: the polygons, from the next 16 in it, 64 bytes each.
// The loader points TheHeliSheet at the first child's data and the sheet's
// Polys at the second's, and works the count out from the second's size.
// The file already holds the count and a stale pointer; both are written
// over. Nothing is copied, so the unloader only forgets the sheet.
//
// Every track has one: 397 to 1246 polygons, a few triangles and the rest
// quads, each with a byte of flag bits the helicopter reads back.
//
// FindZValue (0x001ebad8) looks first at the three polygons it last found,
// then from the bucket of the point's x. There are 256 buckets across the
// sheet's x range; the polygons are in order of their least x, and each
// bucket holds the first that starts in it or later. From there it runs
// forward while a polygon starts at or before x, then back from the one
// before while one could still reach it (MaxWidth). The polygon found goes
// to the front of the three.
//
// Not here: HeliPoly::Init (0x001eb770) and the sheet's bucket builder
// (0x001eb978), which nothing in the image calls -- the tool that made the
// files ran them; and the demo's constructor and destructor, which retail
// dropped.
//
// Cross-check: tools/helisheet_check.py. Write-up: docs/formats/helisheet.md.

#ifndef HELISHEET_H
#define HELISHEET_H

#include <stdint.h>

#include "bvector.h"

#define HELISHEET_CHUNK_ID   0x80034800u
#define HELISHEET_BUCKETS    256

// A polygon, 64 bytes: three or four corners, 16 apart. The corners' fourth
// words carry the rest: the least x in the first's, the greatest in the
// second's, the corner count and the flag bits in the third's.
typedef struct HeliPoly {
    float    P0[3];         //  0
    float    MinX;          // 12
    float    P1[3];         // 16
    float    MaxX;          // 28
    float    P2[3];         // 32
    int8_t   NumPoints;     // 44
    uint8_t  Flags;         // 45
    uint8_t  _pad46[2];     // 46
    float    P3[3];         // 48
    uint32_t _pad60;        // 60
} HeliPoly;

// The sheet, 536 bytes in the chunk.
typedef struct HeliSheet {
    int16_t  NumPolys;                      //  0
    int16_t  Recent[3];                     //  2  the last found, newest first
    uint32_t Polys;                         //  8  HeliPoly *, a p32 slot
    float    MinX;                          // 12
    float    MaxX;                          // 16
    float    MaxWidth;                      // 20  the widest polygon in x
    int16_t  Bucket[HELISHEET_BUCKETS];     // 24
} HeliSheet;

typedef char helipoly_size_check[sizeof(HeliPoly) == 64 ? 1 : -1];
typedef char helisheet_size_check[sizeof(HeliSheet) == 536 ? 1 : -1];

// TheHeliSheet (retail gp-17128): the loaded track's, or NULL.
extern HeliSheet *TheHeliSheet;

// LoaderHeliSheet (0x001ebd20) and UnloaderHeliSheet (0x001ebd80): 1 for a
// 0x80034800 chunk, else 0.
int loader_heli_sheet(uint8_t *chunk);
int unloader_heli_sheet(uint8_t *chunk);

// HeliSheet::FindZValue(bVector2 *, float *, unsigned int *), 0x001ebad8:
// 1 when a polygon holds the point, with its height there in *z and its
// flag bits in *flags (each skipped when NULL); 0 and neither written when
// none does or the sheet is empty.
int32_t helisheet_find_z_value(HeliSheet *s, const bVector2 *pt, float *z,
                               uint32_t *flags);

#endif
