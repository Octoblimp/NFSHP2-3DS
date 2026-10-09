# HeliSheet (chunk `0x80034800`)

`TheHeliSheet` (retail gp-17128) is the track's sheet of ground polygons
that the police helicopter flies over. The helicopter asks it for the
ground's height under a point, and for that polygon's flag bits. It is
slot 23 of the LoaderTable (the demo's 24). The port has it in
`helisheet.{c,h}` (12k-1), cross-checked by `tools/helisheet_check.py`.

Retail's ELF is stripped. The names are the demo's (`HeliSheet.obj`), and
the retail code is `0x001eb6a8` .. `0x001ebd9c`.

## The chunk

The demo's chunk was `0x00034800`. Retail made it a container of two
children:

| offset | what |
|---:|---|
| 0 | `0x80034800`, the container's size |
| 8 | `0x00034801`, 536 |
| 16 | the HeliSheet, 536 bytes, in place |
| 552 | `0x00034802`, the polygons' size with their pad |
| 560 | pad to the next 16 bytes in memory, then 64 bytes a polygon |

Each track's bundle has one. The tracks on the card hold 24 different
containers, with 397 (TRACKB12) to 1,246 (TRACKB63) polygons. Of 16,490
polygons, 318 are triangles and the rest quads.

## The loader

```
LoaderHeliSheet(chunk)          0x001ebd20
    if chunk->id != 0x80034800: return 0
    d = chunk + 8                       // the first child
    TheHeliSheet = d + 8
    v = d + d->size                     // 8 short of the second's header
    p = (v + 31) & ~15                  // its data, up to 16
    size = *(v + 12) - (p - (v + 16))   // its size, less the pad
    TheHeliSheet->Polys = p
    TheHeliSheet->NumPolys = size >> 6
    return 1

UnloaderHeliSheet(chunk)        0x001ebd80
    if chunk->id != 0x80034800: return 0
    TheHeliSheet = NULL
    return 1
```

- **The pad is the memory's.** The polygons start at the next 16 bytes
  in memory, not in the file. The port loads every bundle 128-aligned, so
  the two are the same. On each track, the count the loader works out
  equals the count already in the file.
- **The file's pointer and count are written over.** The file holds a
  stale `Polys` and the count. Nothing is copied, so the unloader only
  forgets the sheet.
- The port keeps `Polys` as a p32 slot (`p32.h`), so the 64-bit harness
  can run the same code.

## The records

`HeliSheet`, 536 bytes:

| offset | field | |
|---:|---|---|
| 0 | `int16 NumPolys` | the loader's |
| 2 | `int16 Recent[3]` | the last polygons found, newest first |
| 8 | `HeliPoly *Polys` | the loader's |
| 12 | `float MinX` | the sheet's x range |
| 16 | `float MaxX` | |
| 20 | `float MaxWidth` | the widest polygon in x |
| 24 | `int16 Bucket[256]` | for each 256th of the x range, the first polygon that starts in it or later |

`HeliPoly`, 64 bytes. There are four corners, 16 bytes apart; a
triangle's fourth is unused. The fourth word of each of the first three
corners carries the rest:

| offset | field |
|---:|---|
| 0 | `float P0[3]` |
| 12 | `float MinX`, the least corner x |
| 16 | `float P1[3]` |
| 28 | `float MaxX`, the greatest |
| 32 | `float P2[3]` |
| 44 | `int8 NumPoints`, 3 or 4 |
| 45 | `uint8 Flags` |
| 48 | `float P3[3]` |

The polygons are sorted by `MinX`.

The flag byte is four 2-bit fields: bits 0-1, 2-3, 4-5 and 6-7, each 0,
1, 2 or 3. 12,202 polygons have none set.

## FindZValue -- 0x001ebad8

```
HeliSheet::FindZValue(bVector2 *pt, float *z, unsigned *flags)
```

It returns 1 when a polygon holds the point. It then writes the height
there to `*z` and the polygon's flags to `*flags`, skipping either one
when it is NULL. Otherwise it returns 0 and writes neither, and the same
goes for an empty sheet.

1. **The three most recent.** `Recent[0]`, `[1]` and `[2]` are tried in
   order.
2. **The bucket.** The bucket number is
   `(x - MinX) / (MaxX - MinX) * 256`, truncated (`cvt.w.s`) and clamped
   to 0..255. The search starts at `Bucket[b]` and runs forward while a
   polygon's `MinX <= x`.
3. **Back from there.** Then it runs back from the polygon before the
   start, while `x - MaxWidth <= MinX`.
4. **To the front.** The polygon found goes to `Recent[0]`. The ones
   ahead of its old slot move down one, and the last one drops off when
   the polygon was not one of the three.

The image reads the count and the recent three with `lh`. A recent
index that is out of range is used as it is.

### PointInPoly -- 0x001eb6a8

A point outside `[MinX, MaxX]` is outside. Otherwise each edge is taken
in turn, from corner `i` to corner `(i + 1) % n`. A point with
`(b.y - a.y)(x - a.x) - (b.x - a.x)(y - a.y) > 0` is to the edge's left,
and outside. A corner or a point on an edge is inside. A point with a
NaN coordinate fails every edge test, so it is inside any polygon whose x
range it passes. A NaN x passes every range test, so the first of the
recent three holds it.

A count of 0 or less holds every point in the x range. A count over 4
reads its corners on into the next polygon.

### ZValue -- 0x001eb840

This gives the height of the polygon's plane at the point.

- **A triangle's plane is its own.**
- **A quad is split** on the diagonal from P2 to P0. Let
  `side = (P0.y - P2.y)(x - P2.x) - (P0.x - P2.x)(y - P2.y)`. With
  `side <= 0` the half is P0 P1 P2; otherwise, NaN included, it is
  P2 P3 P0.

The normal is the cross product of the two edges from the half's first
corner. The image uses `vopmula`/`vopmsub` here, whose products round as
the FPU's do. The normal is scaled by the VU's reciprocal root of
`(x*x + y*y) + z*z`, which is `1.0f / sqrtf(...)` exactly. The plane goes
through P0 whichever half it is, so the result is
`(P0 . n - (n.x * x + n.y * y)) / n.z`.

### Not ported

HeliPoly::Init (`0x001eb770`) and the sheet's bucket builder
(`0x001eb978`) are not ported. Nothing in the image calls either one;
the tool that made the files ran them. The demo's constructor and
destructor are not ported either, since retail dropped them.

## Who asks

All of FindZValue's callers are the Chopper's (12k):

- FindUnobstructedSpot;
- EndChaseLogic;
- HangoutNearHere;
- BombRunLogic;
- HighLevelPlanning;
- TestLocation;
- two calls in the unplaced code after CalcChopperRotation
  (`0x001e9f94`, `0x001ea24c`), one of them MoveChopper's.

The race log's `world objects` line ends with the sheet's polygon count.

## Checking it

    python tools/helisheet_check.py
    python tools/helisheet_check.py --mutate [--only a,b]

The model runs retail's LoaderHeliSheet, UnloaderHeliSheet and FindZValue
as shipped, with nothing stubbed. The harness runs `helisheet.c` over
the same script.

**The cases.**

- **Every container on the card**, loaded at its file's misalignment.
  For each one:
  - every polygon's centre;
  - for every 9th polygon, its corners, its edges' midpoints and a quad's
    diagonal;
  - 160 random points over the sheet and a margin;
  - points at and past its ends.
- **Runs over the recent three**: hits in each slot, misses, NULL
  outputs, NaNs and infinities.
- **The first container at the other misalignments.** The loader's pad
  changes, and with it the count.
- **Edits.**
  - A recent index of -1 and one past the end.
  - Counts of 0, 5, 3 and -2 corners.
  - Buckets that start past the point, or before the sheet.
  - No `MaxWidth`, an empty sheet, and the wrong id.
- **Each of the search's edges, on a sheet edited so that only that edge
  decides the answer** (the first three containers):
  - the last bucket, against the one before it;
  - a point at a polygon's `MinX`, at the start of the forward run;
  - a point `MaxWidth` past a polygon's `MinX`, at the end of the
    backward run;
  - a polygon past the end that holds every point, which the backward
    run must not reach.

The result is 54,570 ops and 38,140 lines, with 0 differ. All 50
mutations are caught.

`tools/loadertable_check.py` checks slot 23 too: the claims through both
tables, and the unloader on a bare chunk.
