# Scenery

`Scenery.obj` (0x0014c3a0 .. 0x0014e734). This is task 27's twentieth slice,
and the first after the car. It covers the track's scenery as it comes off
the disc, and the visible zones that say which of it to draw. This slice is
the data half:

- the loader and the unloader;
- the three finds;
- the zones' lookups;
- the backwards-track flip;
- the facade matrix;
- the statics.

The cull is the next slice: `IsVisible`, the brute-force and tree culls,
`WhatSectionsShouldWeDraw`, `CullView`, `BatchCullViews`, `DoCulling`,
`DrawAScenery`, `StuffScenery` and eDisplayFrame's `SetupSceneryCullInfo`
at 0x0010e370. The debug views come with it: `UpdateCaffeine`,
`RenderBoundary`, `ScrollText` and `HandleTweakingVisibleZones`.
`RenderVisibleZones` is `jr ra` in the image.

Ported to `3DS Files/source/scenery.{c,h}`. Cross-checked by
`tools/scenery_check.py` against `tools/src/scenery_test.c`.

## The chunks

A track's scenery is cut into numbered sections. Each section is one
container, and the zones are one chunk beside them.

| Id | What it holds | Where the records start | Record |
|---|---|---|---|
| `0x80034100` | one section: the four chunks below | | |
| `0x34101` | the section's header | 16-aligned | `ScenerySectionHeader`, 56 bytes |
| `0x34102` | the kinds of object in the section | the payload | `SceneryInfo`, 40 bytes |
| `0x34103` | the objects placed | 16-aligned | `SceneryInstance`, 48 bytes |
| `0x34104` | a tree over the objects, for the cull | the payload | `SceneryTreeNode`, 24 bytes |
| `0x34106` | the visible zones, one chunk for the track | the payload | `VisibleZone`, 288 bytes |

**TRACKB12.** The track has 122 containers, and each holds its children in
the order `0x34101`, `0x34103`, `0x34102`, `0x34104`. There are 94 at an
offset that is 0 mod 16 and 28 at 8 mod 16. A header chunk is 56 bytes,
or 64 with the 8-byte pad the second group needs.

- **Sections.** The 122 numbers run from 11 to 295 in short runs: 11..16,
  21..23, 31..37 and so on. There are 37 below 90, then 99, then 84 from
  111 up. The disc holds them in this order:
  1. 11..85 in order;
  2. the rest, the hundreds and two-hundreds interleaved by tens
     (111..116, 211..219, 121..123, 221..227, ...);
  3. 99, last.
- **Headers.** Every word but `SectionNumber` is 0 on the disc; the loader
  fills in the rest.
- **Kinds.** There are 2108: 2108 name a first LOD, 385 a second and one a
  third. Only 911 first-LOD names are distinct. Every model pointer on the
  disc is 0, and 28 kinds are facades.
- **Objects and tree.** There are 7765 objects, at most 518 in a section,
  and 1967 tree nodes.
- **Flags.** The `ExcludeFlags` seen are 0, 4, 8, 256 and 512. None has
  0x400, the flip's bit.
- **Zones.** The one zone chunk, at 8923932, holds 23 zones.

TRACKA12.BUN is empty. TRACKB12.BUN, 9,111,668 bytes, is loaded whole. No
scenery is streamed by section; `StreamingTexturePack` (0x001a2900) streams
textures.

## The records

**ScenerySectionHeader**, 56 bytes (`.mdebug`):

| Offset | Field | Filled by |
|---|---|---|
| 0 | `bNode` | the list |
| 8 | `SectionNumber` | the disc |
| 12, 16 | `NumPolygonsInMemory`, `NumPolygonsInWorld` | nothing here |
| 20, 24 | `pSceneryInfo`, `NumSceneryInfo` | the loader |
| 28, 32 | `pSceneryInstance`, `NumSceneryInstances` | the loader |
| 36, 40 | `SceneryTreeNodeTable`, `NumSceneryTreeNodes` | the loader |
| 44, 48 | `SceneryTreeGroupNodeTable`, `NumSceneryTreeGroupNodes` | nothing here |
| 52 | `ViewsVisibleThisFrame` | the cull |

**SceneryInfo**, 40 bytes:

| Offset | Field |
|---|---|
| 0 | `NameHash[3]`, one per LOD, 0 for none |
| 12 | `FarClipSize[3]`, int16 |
| 20 | `pModel[3]`, filled by the loader |
| 32 | `IsFacadeFlag[3]` |
| 36 | `Radius` |

**SceneryInstance**, 48 bytes:

| Offset | Field |
|---|---|
| 0 | the box: `BBoxMin[3]`, `BBoxMax[3]`, int16 metres |
| 12 | `SceneryInfoNumber`, the kind |
| 14 | `ExcludeFlags` |
| 16 | `Position[3]` |
| 28 | `Rotation[9]`, three rows in units of 2^-14 |

**SceneryTreeNode**, 24 bytes: a box, `NumChildren`, and five child codes.

**VisibleZone**, 288 bytes:

| Offset | Field |
|---|---|
| 0 | `bNode` |
| 8 | `ZoneNumber` |
| 12 | `Center`, a `bVector2` |
| 20 | `pCaffeineObj`, the editor's |
| 24 | `NumVisibleScenerySections` |
| 28 | `VisibleScenerySections[64]`, int16 |
| 156 | `NumPerimeterPoints` |
| 160 | `PerimeterPoints[16]`, `bVector2` |

## The globals

| Address | Name | What it is |
|---|---|---|
| 0x002f1018 | `ScenerySectionHeaderTable[300]` | the loaded headers by section number |
| gp-22576 | `ScenerySectionHeaderList` | the loaded headers |
| gp-22568 | `VisibleZoneList` | the loaded zones |
| gp-22560 | `pVisibleZoneBoundaryModel` | MARKER_BOUNDARY, drawn along a zone's edge |
| gp-22584 | `CurrentZoneNumber` | **-1** in `.sdata`: no zone yet |
| gp-22544 | `AdvanceFastBlinkSectionNumber` | the debug view's step |
| gp-25728 | `eModelSlotPool` | eInit's pool of 24-byte eModels |

`_GLOBAL_$I$CurrentZoneNumber` (0x0014e718) empties both lists. It is
`__CTOR_LIST__[21]`, and `sinit_run` calls it there.

`_GLOBAL_$D$CurrentZoneNumber` (0x0014e6f0) runs each list's destructor,
zones first. `bTList<T>::~bTList` unlinks each node still on the list and
deletes it: a bNode's deleting destructor is `__builtin_delete`, which is
`bFree`. For a node inside a chunk that is wrong, so the unloaders must have
emptied both lists first.

## The loader

`LoaderScenery(bChunk *)`, 0x0014c3a0.

**A container.** The loader walks the children until it reaches the
container's end. It does not check the order, so a child before the header
writes through a NULL header.

- **Header.** The header is at the payload rounded up to 16. Its slot in
  the table is set. A section below 90 goes to the list's tail and the rest
  to its head. With TRACKB12 loaded in the disc's order, the list runs:
  1. 99, 285, 284, ... 112, 111: the reverse of the disc's order;
  2. 11 up to 85.
- **Kinds.** `pSceneryInfo` is the payload, with no pad, and the count is
  `size / 40`, unsigned.
- **Objects.** `pSceneryInstance` is the payload rounded up to 16, and the
  count is `(size - pad) / 48`, unsigned. A pad larger than the chunk wraps
  the count: an empty objects chunk 8 short of a line gives 89,478,485.
- **Tree.** The tree is at the payload, and the count is `size / 24`.
- **Anything else** is skipped.

A second kinds chunk replaces the first.

After the walk, each LOD with a nonzero name gets a model:

1. `bOMalloc(eModelSlotPool)`;
2. the inline constructor's two stores, NameHash and Solid set to 0;
3. the pointer stored in `pModel[k]`;
4. `eModel::Init(name)`.

A LOD with no name keeps whatever its pointer held on the disc. The flip
comes last, when `TheRaceParameters.TrackDirection` (0x0031252c) is exactly
1. A direction of 2 does not flip. The loader returns 1.

**A zone chunk.** The loader walks `size / 288` zones. Each goes to the
list's tail, and its `pCaffeineObj` is cleared. The loader returns 1.

**Anything else** returns 0.

## The unloader

`UnloaderScenery(bChunk *)`, 0x0014c658.

**A container.** The header is taken from the first child's payload,
rounded up to 16. The unloader does not look anywhere else, so a container
whose first child is not the header unlinks garbage. The header is unlinked
and its table slot cleared. A duplicate section clears the slot even while
the other copy is still on the list. Then each kind's non-NULL model
pointers are destroyed with 3. That includes junk left under a LOD with no
name. The loader's `pModel` is not cleared.

**A zone chunk.** Each of its zones is unlinked. Both paths return 1, and
anything else returns 0.

## The finds

- **FindSceneryInfo(hash)** (0x0014c7a0) walks the list from the head. It
  returns the first kind whose *first* LOD has the name. With 1197 repeats
  on TRACKB12, the list's order decides which copy is found.
- **FindSceneryInstance(hash)** (0x0014c800) returns the first object whose
  kind's first LOD has the name. It reads the kind by the object's
  `SceneryInfoNumber`, unchecked.
- **FindSceneryInstance(section, index)** (0x0014c880) returns NULL when the
  section is not loaded. Otherwise it returns `&pSceneryInstance[index]`,
  with neither number checked.

## The zones

**IsPointInPoly(pt, poly, n)** (0x0014c8b8) is the crossing test:

```
c = 0; j = n - 1
for i in 0 .. n-1:
    if (yi <= y && y < yj) || (yj <= y && y < yi):
        if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            c = !c
    j = i
```

- **Scanline.** Both halves take the lower end and not the upper. A vertex
  on the scanline counts for the edge above it only, and a horizontal edge
  counts for neither.
- **NaN.** A NaN point counts for nothing.
- **Order.** The multiply comes before the divide.
- **n.** An n of 0 or less gives 0.

**FindVisibleZone(pt)** (0x0014c980) returns the first zone on the list
whose perimeter holds the point, and moves that zone to the list's head.
The last zone found is always tried first.

**VisibleZone::FindIndexTo(section)** (0x0014ca10) is the first index below
`NumVisibleScenerySections` holding the section, or -1. The compare is
int16 against int32, so 0x10004 never matches 4.

**FindNextFreeIndex** (0x0014ca58) takes, in order:

1. the first -1 slot;
2. -1 when the count is exactly 64;
3. otherwise the count, which it then raises by 1.

A count past 64 is not caught. It goes on reading into
`NumPerimeterPoints` and the corners, and raises the count again.

**InitVisibleZones** (0x0014cf18) builds MARKER_BOUNDARY's model. Each call
builds a new one without destroying the old. **CloseVisibleZones**
(0x0014cf68) destroys it with 3, if there is one, and clears the pointer.

**HandleJoystickBlinkSection(step)** (0x0014cf90) stores the step only when
it is 1 or -1. **GetCurrentZoneNumber** (0x0014cfb0) reads the global.

## The debug tables

- **IsInTable(table, n, value)** (0x0014cfb8) is the first index holding
  the value, or -1. The compare is int16 against int32.
- **ToggleIsInTable(table, n, max, value)** (0x0014cfe8):
  - A value found is struck out with -1, and n is returned. Toggling -1
    finds the first empty slot and changes nothing.
  - A value that does not fit a short is never found. Each toggle stores
    its low half again.
  - A new value goes in at `n % max`, signed as `div` is. A negative n
    writes below the table, and a full table writes over its oldest
    entry. n + 1 is returned.
  - A max of 0 traps: `div` is guarded by `break`.

## CreateFacadeMatrix

`CreateFacadeMatrix(m, pos, eye)` (0x0014d3f0) turns a facade about z to
face the eye, at `pos`:

```
eRotateZ(m, &eMathIdentityMatrix, bATan(pos.x - eye.x, pos.y - eye.y))
m.row3 = pos, then m.row3.w = 1
```

The row is copied as a quadword, pad and all, and w is then overwritten, so
`pos.pad` never shows.

## FlipObjectsOnBackwardsTrack

`ScenerySectionHeader::FlipObjectsOnBackwardsTrack` (0x0014dcd8) handles
each object with the 0x400 bit:

- Its rotation's rows are expanded: each short times 2^-14, with w 0, and a
  fourth row of (0, 0, 0, 1).
- `eRotateZ(m, m, 0x8000)` turns them half round. The half-turn's sine is
  exactly 0 and its cosine exactly -1, so the x and y columns are negated
  exactly.
- Each entry is stored back as `cvt.w.s(v × 16384)`, truncated to a short.
  -32768 negated is 32768, which the store wraps back to -32768.

After the turn the listing copies the position into the fourth row and
back:

- `lqc2` loads the position's quadword, whose w is Rotation[0..1], into
  the fourth row.
- The row's w is set to 1.
- Only x, y and z are stored back.

The position is unchanged, and the objects turn where they stand.
Rotation[0..1] then get their new values with the rest.

Flipping twice gives back every rotation, including -32768.

## The port

- **eModel.** eModel.obj is the renderer's and is not ported. `eModel::Init`
  and the deleting destructor are the seams `gEModelInitFn` and
  `gEModelDestroyFn`. Both abort when reached unset: a model left unbuilt
  would draw nothing without saying so. `eModelSlotPool` stays NULL until
  the renderer makes it.
- **The handheld.** Every record is the disc's layout, and the loader works
  on the bundle's bytes in place.
- **A 64-bit host.** The header, the kinds and the zones hold pointers, so
  they widen, and the loader's strides are the host's sizes. The harness
  rebuilds a container with those records widened. Each child sits at the
  misalignment the image sees it at, so the pads are the image's, and each
  child's size keeps the disc's residue mod 16.
- **FindIndexTo reaches its shorts from the zone**, not through
  `VisibleScenerySections[i]`. Indexed through the array, GCC at -O2 took
  the array's 64 as a bound on the count: after the loop it could assume
  the count was at most 64, and `== 64` and `>= 64` compiled alike. A
  count past 64 then matched the image by luck. The mutation pass found
  it.

## The checker

```
scenery_check  17 scenarios, 3450 ops, 16724 lines, 0 differ
               2843 models built
```

The script:

- **TRACKB12, forward.**
  - Every one of the 122 sections, then the zones.
  - FindSceneryInfo on all 911 first-LOD names and on misses.
  - FindSceneryInstance by name on 60 of them, and by section and index
    on every section, at the first, last and one-past objects.
  - FindVisibleZone on every zone's centre, corners and edge midpoints,
    and on 200 points scattered over the track.
  - All unloaded in a shuffled order.
- **TRACKB12, again.** Ten sections on a backwards track, and six
  repacked for other alignments.
- **Made-up sections:**
  - sections 0, 89, 90 and 299, and a header alone;
  - junk in the header's words;
  - children in other orders, two kinds chunks, an unknown child, and a
    kinds chunk with a remainder;
  - junk model pointers under LODs with no name;
  - two sections with one number;
  - a pad larger than the objects chunk;
  - chunks that are neither kind, and zone chunks empty and with a
    remainder.
- **The flip.** Nine rotations under four flag words:
  - by the loader on a backwards track, then called again;
  - loaded forward, and with a direction of 2.
- **The rest:**
  - IsPointInPoly's corner cases and 210 random polygons;
  - the zone and table lookups;
  - CreateFacadeMatrix on 52 pairs.

Both sides run `eMathInit` first, as eInit does at boot. Without it
`eMathIdentityMatrix` is zero on both sides, every facade's rotation is
zero, and a mutant that swaps or negates bATan's arguments survives.

No address is printed: a pointer is named by the record it falls on.

The mutation pass:

- **Tally.** 79 mutations: 77 caught, 2 equivalent, 0 unexplained.
- **The two equivalents:**
  - `ld-model-after-init`, the pointer stored after Init rather than
    before. Init is a seam that reads its model and the name, not the
    kind the model is stored in.
  - `fl-row3-w`, the flip's fourth row given a w of 0. The row is turned
    with the rest and never read back.
- **Crashes and hangs.** Eight mutants stop the harness, which counts as
  caught. Six crash it: `ld-type`, `payload16-short`, `ld-header-nopad`,
  `ul-first-child`, `fis-null` and `tt-umod`. Two hang it: `ul-type` and
  `ul-no-unlink` leave a header on the list after its section is
  unloaded, and the next walk of the list never ends.
