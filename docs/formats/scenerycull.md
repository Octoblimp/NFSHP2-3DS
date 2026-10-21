# Scenery cull

This is task 27's twenty-first slice: the cull half of `Scenery.obj`
(0x0014d460 .. 0x0014e59c), which picks what each view draws this frame
from the loaded scenery. `scenery.md` covers the data half. The slice
also takes in the functions the cull calls and the loop that calls it:

- `ClassifyAABB` (0x0010b940) and `IsBoundingBoxVisible` (0x0010bb10),
  which sit beside eModel's methods;
- `SetupSceneryCullInfo` (0x0010e370, retail's 0x0010f858, the same but
  for one global's address), and eDisplayFrame's loop over the
  views (0x00112d18 .. 0x00112df0), which the image has inline;
- Ecstasy.obj's frame malloc (0x0019d9e0 .. 0x0019db2c);
- the table of views, with `eGetView` and `eGetCurrentViewMode`.

That is 17 functions and 4,608 bytes, plus the 216-byte slice of
eDisplayFrame.

The debug views stay behind: `UpdateCaffeine`, `RenderBoundary`,
`ScrollText` and `HandleTweakingVisibleZones`. They draw the editor's
overlays, and nothing on a retail disc reaches them.

The port is in `3DS Files/source/`:

- `scenerycull.{c,h}`: the cull;
- `eframe.{c,h}`: the frame malloc;
- `eview.{c,h}`: the 128-byte eView and its table.

`tools/scenerycull_check.py` cross-checks it against
`tools/src/scenerycull_test.c`.

## A frame's cull

eDisplayFrame runs the cull in three steps.

1. **The setup.** Each view that draws gets one `SceneryCullInfo` from
   `SetupSceneryCullInfo`. The info holds the view's world-to-clip matrix,
   a turn about z for the facades, and the flags of the objects the view
   leaves out.
2. **`DoCulling`.** For each view, it walks the sections the view can see
   and the tree over each section. Every object that is in the frustum and
   big enough on the screen goes on `SceneryDrawInfoTable` as one
   `SceneryDrawInfo`: a model, the box's class, and a matrix from the frame
   malloc.
3. **`StuffScenery`.** This runs once per render target, and hands the
   view's run of the table to `eModel::Render`.

A box's class is ClassifyAABB's: 0 for outside, 1 for across the edge of
the frustum, 2 for inside. A node or object that is inside needs no more
tests. The class rides in the low two bits of the draw info's model
pointer, and Render reads it there: a class of 2 renders with flag 4,
which lets it skip clipping.

## The records

These layouts come from `.mdebug`.

**SceneryCullInfo**, 208 bytes:

| Offset | Field | Set by |
|---|---|---|
| 0 | `FacadeMatrix` | the setup; unread by the cull |
| 64 | `ClipMatrix`, world to clip, row vectors | the setup |
| 128 | `pView` | the setup |
| 132 | `ExcludeFlags` | the setup |
| 136, 140, 144 | `pFirstDrawInfo`, `pCurrentDrawInfo`, `pTopDrawInfo` | DoCulling |
| 160 | `Position`, the camera's | DoCulling |
| 176 | `Direction`, the camera's | DoCulling |
| 192 | `H`, the view's focal length in pixels | DoCulling |

**GrandSceneryCullInfo**, 2096 bytes, on eDisplayFrame's stack at sp+16:
ten `SceneryCullInfos`, then `NumCullInfos` at 2080 and the table's first,
current and top pointers at 2084, 2088 and 2092.

**SceneryDrawInfo**, 8 bytes: `pModel` plus the class, and `pMatrix`.
`pMatrix` is NULL for an object drawn where it stands.

**eView**, 128 bytes. The cull reads these fields:

| Offset | Field |
|---|---|
| 0 | `ID` |
| 4 | `Active`, a byte |
| 8 | `H` |
| 48 | `pRenderTarget0`; the loop reads the word at its 8, `Active` |
| 56 | `pCamera`, whose `CurrentKey` holds `Position` at 64 and `Direction` at 80 |
| 68 | `WorldViewMatrix` |
| 80 | `WorldScreenClipMatrix` |
| 108 | `WorldLightContext` |

`eview.h` has the whole record.

## The globals

| Address | Name | What it is |
|---|---|---|
| 0x002ab230 | `eViews[10]` | the views, 1280 bytes; `TextureDownloader` follows at 0x002ab730 |
| 0x002e8cd8 | `SceneryDrawInfoTable[4200]` | the frame's draws; ends where `ScenerySectionHeaderTable` starts |
| 0x00322898 | `CurrentViewMode` | 3 and 4 are the split screens |
| 0x00323628 | `InGameFlag` | the loop culls nothing while it is 0 |
| 0x00323758 | `EnvironmentMappingEnable` | 1 in `.sdata` |
| 0x00323da0 .. 0x00323df4 | the frame malloc's | see below |

The views by ID:

- view 0 is the frontend's;
- views 1 to 3 are the players';
- views 4 to 9 are the environment maps.

## ClassifyAABB

This is all VU0 macro code.

**The corners.** The box's minimum goes through the matrix as
`((r0·x + r1·y) + r2·z) + r3`. The three edges are the first three rows,
scaled by the box's extents. The corners are sums of the two, in the
listing's order:

- the bottom face: min, then +x, then +x+y, then +y;
- the top face: each of those plus the z edge.

Only the corners' x, y and z are read. The w lanes of the two input
vectors can hold anything.

**The flags.** `vclipw.xyz` tests each corner against its |w|, strictly,
and sets six flags: +x, −x, +y, −y, +z and −z in bits 0 to 5. A corner
exactly on a plane is inside. The clip register keeps the last four
corners' flags at shifts 18, 12, 6 and 0. The listing reads it once
after each face, so each face's four corners are read separately.

**The result:**

- 2 when both faces' flags are all clear;
- 0 when one flag is set on all eight corners, so that the box is wholly
  beyond one plane;
- 1 otherwise, including a box beyond two planes but not wholly beyond
  either.

A NaN compares false, so a NaN coordinate is inside.

`IsBoundingBoxVisible` returns whether ClassifyAABB's class is not 0.

## DrawAScenery

`DrawAScenery(index, info, class)` handles one object.

1. **The class.** A class of 1 classifies the object's own box first
   (int16 metres, converted to float), and returns if the result is 0.
   Any other class is taken as it is: 0, 3 and 5 as well as 2.
2. **The exclusion.** The object is skipped if its `ExcludeFlags`, ANDed
   with the view's, has anything in the low byte.
3. **The size on the screen.** Take r = `Radius` + 4 m, and the
   camera-to-object vector d.
   - If d·Direction < −r, the object is behind the camera and its size
     is 0.
   - Otherwise, with dist = |d| and f1 = dist − r, the size is
     `trunc(H · r / f1)`, or `trunc(H)` when f1 is not more than r.

   The listing's order of operations is kept: `(dx·Dx + dy·Dy) + dz·Dz`,
   `sqrt((dx² + dy²) + dz²)` and `(r · H) / f1`. The truncation is
   `cvt.w.s` with the EE's saturation. A size below 2 is not drawn.
4. **The LOD.** This is the first k with size ≥ `FarClipSize[k]` whose
   `pModel[k]` is not NULL. A NULL model is skipped, not taken as the end.
   With no such k, nothing is drawn.
5. **Drawn in place.** An object with flag 0x200 goes on the table with a
   NULL matrix, and Render draws it with the identity.
6. **The matrix.** Otherwise the frame malloc gives 64 bytes. If it has
   none, the object is not drawn.
   - For a facade LOD (`IsFacadeFlag[k]`), `CreateFacadeMatrix` turns the
     object to the camera.
   - For any other LOD, the rotation's three rows are scaled by 2^-14,
     with w = 0.

   The fourth row is the position, with w = 1. When the object's flags
   and the view's share 0x100, the position is raised 2 m.
7. **The table.** The draw info is written only while
   `pCurrentDrawInfo < pTopDrawInfo`. A full table drops the object, but
   its matrix has already been taken from the frame malloc.

The frame malloc is inline here: `pos + 64 < end`, unsigned. On failure it
sets `FrameMallocFailed` and adds 64 to `FrameMallocFailAmount`. It does
not count `FrameMallocAllocNum` on either path.

## The trees

A node's child code of 0 or more is an object's index. A negative code is
a node: −code, counted from the section's first node.

The codes are read from the node's base, and there are five slots. A
`NumChildren` above five reads on into the next node's box. The port reads
them the same way.

- **`TreeCull`** starts at node 0 with class 1. It uses a stack of 64
  nodes and their classes, with no test for overflow. A node of class 1
  is classified. A node of class 0 is dropped. Otherwise each child that
  is an object is drawn with the node's class, and each child that is a
  node is pushed with it. So the children of a node that is inside are
  never tested.
- **`CullNodeRecursive`** does the same by recursion. Nothing calls it
  from outside the object.
- **`IsVisible`** returns 0 for a section with no tree. Otherwise it
  returns whether node 0's box is not outside.
- **`CullBruteForce`** does nothing unless the section is visible. Then
  it draws every object with class 1. Nothing calls it.

Neither tree cull checks for a missing tree. `CullView` and
`BatchCullViews` never hand them a section without one.

## The sections a view draws

**`WhatSectionsShouldWeDraw(out, max, info)`** writes at most `max`
section numbers, and returns the count. It depends on the visible zone
that holds the view's camera, from `FindVisibleZone`:

- **With no zone,** every section on `ScenerySectionHeaderList` numbered
  below 100 is drawn, in the list's order.
- **With a zone:**
  1. every loaded section from 90 to 99;
  2. then each section on the zone's list that is 0 or more and loaded.
     The list's own order is kept, duplicates included.
- **For view ID 1,** `CurrentZoneNumber` becomes the zone's number, or −1
  with no zone.

**`CullView`** takes up to 128 sections and tree-culls each one that has a
tree.

**`BatchCullViews`** culls each section once for all the views.

1. Each view's sections are written after the ones kept so far, into an
   array of 256.
2. A section not yet seen this frame is packed onto the end of the list.
   Every section gets the view's bit in `ViewsVisibleThisFrame`.
3. Then each listed section is tree-culled for every view whose bit it
   has, and its bits are cleared.

Nothing calls BatchCullViews either.

## DoCulling and StuffScenery

**`DoCulling`** runs in this order:

1. It points the grand info at the whole table: first and current at
   D[0], and top at D[4200].
2. It copies each view's camera position, direction and `H` into its info.
3. It culls each view in turn, each starting where the one before it
   ended.

The listing ends with a delay loop of four nops per cull info. The port
leaves it out.

**`StuffScenery(view)`** finds the first cull info whose `pView` is
`view`, and returns after drawing it. It renders each draw info on that
info's run of the table:

- the model with its class bits cleared;
- flag 4 when the class is 2, and 0 otherwise;
- for a matrix of NULL, `eMathIdentityMatrix` and the view's
  `WorldLightContext`;
- for any other matrix, that matrix and a NULL light context.

## SetupSceneryCullInfo and the views

**`SetupSceneryCullInfo(view, info)`** fills in an info:

- **`FacadeMatrix`** is the identity turned about z by
  `bATan(wv.v0.z, wv.v0.x)`, where wv is the view's `WorldViewMatrix`;
- **`ClipMatrix`** is a copy of `WorldScreenClipMatrix`;
- **`pView`** is the view;
- **`ExcludeFlags`** is built from the table below.

| Flag | When |
|---|---|
| 0x10 | always |
| 0x01 | view mode 3 or 4, the split screens |
| 0x102 | view ID 4 to 9, an environment map (unsigned compare) |
| 0x08 | a forward track |
| 0x04 | a backwards track |

The flags match against the objects' own `ExcludeFlags` (see
`DrawAScenery`). TRACKB12's objects carry only 0, 4, 8, 256 and 512.

- An object with 4 is left out on a backwards track, and one with 8 on a
  forward track.
- An object with 256 (0x100) is raised 2 m in the environment maps.
- An object with 512 (0x200) is drawn in place.

**eDisplayFrame's loop** runs as follows:

1. It zeroes `NumCullInfos`, in a delay slot.
2. With `InGameFlag` set, it goes through views 1 to 3. Each one that is
   `Active` and whose first render target's `Active` is set gets the
   next info.
3. When `EnvironmentMappingEnable` is set, it does the same for views 4
   to 9.
4. `DoCulling` follows, then a `StuffScenery` per render target.

`scenery_cull_setup_views` is the loop.

## The frame malloc

The allocator has two buffers, and it swaps them once a frame.
`eInitEngine` asks for 2,621,440 bytes.

| Address | Name |
|---|---|
| 0x00323da0 | `FrameMemoryBufferSize` |
| 0x00323da4, 0x00323da8 | `CurrentBufferPos`, `CurrentBufferEnd` |
| 0x00323dac | `PrintFrameMalloc` |
| 0x00323db0 | `FrameMallocAllocNum` |
| 0x00323db4 .. 0x00323dbc | `FrameMallocFailed`, `FrameMallocFailAmount`, `FrameMallocMaxFailAmount` |
| 0x00323de8 | `FrameMemoryBuffer[2]` |
| 0x00323df0 | `FrameMemoryBufferAmountUsed[2]` |

- **`eAllocateFrameMallocBuffers(size)`** allocates each buffer as
  `(size >> 5) << 4` bytes, with `bMalloc(n, "eFrameMallocBuffer0", 0, 16)`
  and then "...1". It sets the size to `size >> 1`, which is 2 more than
  the allocation when size is 100. It then sets the position to the
  first buffer, the end to that plus the size, and the count to 0.
- **`eSwapFrameMallocBuffers`** does, in order:
  1. keeps the largest `FailAmount` of a failed frame;
  2. shifts the amount used;
  3. makes the other buffer current, with its end;
  4. clears the failure.
- **`eFreeFrameMallocBuffers`** frees both buffers and zeroes the
  buffers, the size, the position, the end and the count.
- **`eGetSizeofFrameMallocBuffers(&used)`** stores the two frames' use in
  `used` and returns `size << 1`.

**Alignment.** Every frame block is 16-aligned. The buffers are, and
every size taken from them is a multiple of 16. That matters on the EE:
VU0's `sqc2` drops an address's low four bits. A matrix written through a
misaligned pointer would land 16 bytes early in the image, but not in the
port. The checker keeps every position it sets 16-aligned for this reason.

## The port

- **eModel::Render** is the renderer's. It is the seam `gEModelRenderFn`,
  which aborts when reached unset. The citro3d renderer will set it.
- **The views** are the image's layout, and the matrices are pointers to
  the renderer's. On the handheld the port's renderer fills
  `WorldViewMatrix` and `WorldScreenClipMatrix`. The cull needs the clip
  matrix in the image's convention: row vectors, and clip space where
  inside is |x|, |y|, |z| ≤ |w|.
- **A 64-bit host.** The records hold pointers, so they widen. The ILP32
  layouts are checked under `UINTPTR_MAX == 0xFFFFFFFF`. A draw info's
  class goes into the pointer's low bits as the image puts it there, since
  every eModel is at least 4-aligned.
- **The view IDs' compare** is unsigned, as the listing's `sltiu` is. An
  ID of −1 or 0x80000004 is not an environment map.
- **No disagreement** between the image and the port was found.

## The checker

```
scenerycull_check  9 scenarios, 7273 ops, 46687 lines, 0 differ
                   11623 draws, 7205 renders
```

`mipsemu` runs the shipped functions out of NFSHP2.ELF. It runs
eDisplayFrame's loop in place, from 0x00112d18 to a stub at the
`DoCulling` call, with the grand info at s7.

- **Stubs.** In the model, `eModel::Render`, `bMalloc` and `bFree` are
  stubbed, and each stub prints its call.
- **Sections.** Both sides build the sections straight from the script,
  not through the loader, which `scenery_check` has already checked.
- **Tree guards.** Each tree is followed by two zeroed nodes. A child
  count past five, or a code one past the last node, reads those.

The script:

- **The frame malloc.** Buffers of 256, 100 and 2,621,440 bytes; swaps
  after frames that failed and that did not; the size query; the free.
- **ClassifyAABB:**
  - boxes inside, across, and beyond each plane, beyond two at once, and
    on a plane exactly;
  - a w that grows with x, and a negative w;
  - junk in the w lanes, and NaN and infinities;
  - edges one rounding either side of a plane;
  - sums whose order moves a corner across a plane: the minimum's four
    terms, and the far corner's two edges;
  - a sheared matrix;
  - 1,500 random boxes through random matrices, and 800 through
    perspective views.
- **DrawAScenery.** Every branch:
  - the class given as 0 to 6;
  - each exclusion bit against ten view flag words;
  - objects behind the camera, at −r exactly, and at distances around
    each LOD's clip;
  - H small, zero, negative and huge;
  - a NULL middle LOD, and kinds with no model;
  - facades at LOD 0 and LOD 1;
  - the frame malloc with a block ending exactly at the end, which is
    refused because the compare is strict; one byte short of it; and a
    position already past the end;
  - sizes that one rounding puts either side of the 2 or of a far clip:
    the dot product's order, the distance's, `r * H / f1` against
    `r * (H / f1)`, and f1 equal to r;
  - a full table and one slot short;
  - 300 random objects around twelve perspective cameras.
- **The trees.**
  - A nested tree with nodes inside, across and outside, and an outside
    node under an inside one.
  - A child count of seven.
  - A chain 31 deep.
  - A code into the guard, and a root that is outside.
  - Each run through TreeCull, CullNodeRecursive from several nodes and
    classes, IsVisible and CullBruteForce, under the identity and a
    perspective clip.
- **The sections:**
  - WhatSectionsShouldWeDraw with no zones and with three, including
    sections that are unloaded, negative, 0 and in the nineties, at seven
    limits, for view IDs 1, 2 and 3;
  - the camera outside every zone;
  - CullView, BatchCullViews over one, two and three infos with shared
    sections, DoCulling, and StuffScenery for views that have an info,
    views that do not, and one view with two.
- **The setup.** SetupSceneryCullInfo over ten view IDs (including −1
  and 0x80000004), seven view modes and four track directions, plus ten
  first rows for the facade's turn. The loop runs with each view's two
  `Active`s varied, with and without the environment maps and
  `InGameFlag`.
- **TRACKB12.**
  - All 122 sections and 23 zones.
  - One or two views at each zone's centre and at twelve random points
    over the track, 2 m above the nearest object, looking in random
    directions, forward and backwards, in one and two player modes.
  - DoCulling and StuffScenery from each, with BatchCullViews on some.

No address is printed. A pointer is named by what it falls on, as the
harness's head lists. Floats are compared as bits.

The mutation pass:

- **Tally.** 148 mutations: 147 caught, 1 equivalent, 0 unexplained.
- **Crashes and hangs.** Seven of the catches stop the harness: six crash
  it and one hangs it. They are the tree's codes read wrong, a NULL
  section or tree dereferenced, and the views' count left unzeroed. The
  checker's timeout is 60 s.
- **The equivalent one.** The facade's position given the object's y for
  its z. CreateFacadeMatrix writes the position into the matrix's last
  row, but DrawAScenery writes the object's position over that row
  straight after, so z reaches nothing.
- **Rounding.** Six survived the first pass: the sums' and the quotient's
  orders, and `r <= f1` for `r < f1`. Each reassociation is exact on
  most inputs, so the script now has one case for each, found by search,
  where the other order rounds across a plane, the 2 or a far clip.
  Every one agrees with the image's order.
