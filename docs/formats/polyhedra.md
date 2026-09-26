# Polyhedra

`polyhedra.cpp` (0x00205058 .. 0x00206440). Task 27's tenth slice, between
[VClip](vclip.md) and CollisionBody. It holds the convex polyhedra the
collision bodies hand to VClip, the loader for the collision volumes on the
disc, and four debug tests.

Ported to `3DS Files/source/polyhedra.{c,h}`. Cross-checked by
`tools/polyhedra_check.py` against `tools/src/polyhedra_test.c`.

| Kind | Size | What it is | Made by |
|---|---|---|---|
| `RectPolyhedron` | 2800 | an axis-aligned box, from its six bounds | CarCollisionBody and Smokeable, when no volume is named for them |
| `CubePolyhedron` | 2800 | the same record, a box of ±size/2 | TestCubes |
| `WaferPolyhedron` | 992 | a track polygon, as a solid of no thickness | TrackPolygonCollisionBody |
| `PipelinePolyhedron` | 96 | a collision volume from the art pipeline, in place in its chunk | the chunk loader |

Each kind is a `VCPolyhedron` with its arrays behind it. The Rect and Wafer
builders lay the features out from ten tables at 0x00313a08 .. 0x00313c48,
which give the neighbour each Voronoi plane faces, in plane order. The
planes themselves are left to `SetVoronoiPlanes`. The plane order is
vclip.h's:

- a vertex's planes face its edges;
- an edge's planes face its tail, then its head, then its two faces;
- a face's planes face the edges round it.

## RectPolyhedron

The constructor (0x00205058) takes `xmax, xmin, ymax, ymin, zmax, zmin`. It
does not sort them, so inverted and inside-out bounds are built as given.

- **Vertices.** Vertex i sits at the bounds picked by i's bits: bit 0 picks
  x, bit 1 y and bit 2 z, and a clear bit picks the max. Each vertex takes
  three planes, facing the edges `RectEdgesNearVertices[i]`.
- **Faces.** Face i faces along axis i/2, +1 for even i and -1 for odd.
  Its distance comes through a jump table at 0x0029f250: `xmax, -xmin,
  ymax, -ymin, zmax, -zmin`. The minus is `neg.s`, a true negation, so a +0
  minimum gives a -0 distance. The Wafer's reversals go through the VU and
  do not work that way. Each face takes four planes, facing
  `RectEdgesNearFaces[i]`.
- **Edges.** Edge i runs from `RectVerticesNearEdges[i][0]` (its tail) to
  `[i][1]` (its head), between the faces `RectFacesNearEdges[i]`. Its
  direction is head - tail, scaled by `1/extent`, where extent is the box's
  size along the first axis the edge's difference is non-zero on. The
  factor is multiplied through, not divided lane by lane. A proper box
  therefore gets ±1 on one axis. An edge whose ends coincide, on a box that
  is flat along an axis, has no such axis. Its direction is left at zero,
  so nothing divides by a zero extent.
- **The pool** is 96 planes, handed out in order: vertices 0..23, faces
  24..47, edges 48..95.

`NewEdge` stores the direction in units of 2^-13 and truncates it (see
[VClip](vclip.md)). One ulp short of 1.0 is stored as 8191, not 8192, so
the extent's rounding shows.

**CubePolyhedron** has an inline constructor, in TestCubes at 0x00205a1c.
It builds a Rect of `hi = size * 0.5` and `lo = (-size) * 0.5` on every
axis. A cube of size +0 has hi +0 and lo -0. A negative size gives an
inside-out box.

The Rect's and the Cube's destructors (0x00206418, 0x00206410) are both
VCPolyhedron's.

## WaferPolyhedron

`Init` (0x00205470) takes a TrackPolygon and an origin. It builds the
polygon's corners, its edges, and two faces: one each way up.

- **Triangle or quad.** The polygon is a triangle when corners 2 and 3 are
  `bEqual3` within 0.001 (gp-27804). The polygon's `NumVertices` is not
  read. bEqual3 fails only when a lane differs by *more* than the
  tolerance, so corners exactly 0.001 apart still make a triangle. Of
  TRACKB12's 15708 polygons, 6752 are triangles by this test.
- **Arrays.** 3 or 4 vertices and as many edges, two faces, and
  `2·nv + 4·ne + 8` planes: 22 for a triangle and 32 for a quad. Each face
  takes four planes whether it uses them or not, which is where the 8 comes
  from. A triangle's faces leave their fourth planes unused.
- **Vertices.** Each vertex is its corner less the origin, over all four
  lanes. NewVertex reads three of them. Each takes two planes, facing the
  edges `WaferEdgesNearVertices[i]`, or `TriWaferEdgesNearVertices[i]` for
  a triangle.
- **Distance.** d is `n·(corner 0 - origin)`, summed `((x + y) + z)`. The
  polygon's own PlaneDistance is not used for it, so the faces are right
  for any origin.
- **Faces.** Face 0 is the polygon's normal quadword with distance d. Face
  1 is `vf00 - n` on all four lanes. On the normal's three lanes that is
  0 - x, which gives +0 for a +0. The fourth lane is PlaneDistance (the
  TrackPolygon keeps it at +124, the normal's w), so face 1 gets
  1 - PlaneDistance there, and NewFace never reads it. Face 1's distance is
  -d, a true negation. Both faces take edges 0 .. nf-1 in order;
  `WaferEdgesNearFaces`'s two rows are the same.
- **Edges.** Edge i runs between the vertices `WaferVerticesNearEdges[i]`
  (`TriWaferVerticesNearEdges[i]` for a triangle), between the faces
  `WaferFacesNearEdges[i]`. A triangle reads the face pairs one row down:
  its edges 0, 1 and 2 take rows 1, 2 and 3. Its closing edge, 0 to 2, is
  then the quad's closing edge, 0 to 3, and runs the other way round the
  faces. The direction is head - tail times `0 + 1/√len²`. That is `vrsqrt`,
  then `vaddq.x` from vf00, with len² summed `((x·x + y·y) + z·z)`. The
  0 + would only matter for a -0, and 1/√ is never -0.

`TriWaferEdgesNearVertices` and `TriWaferVerticesNearEdges` each have a
fourth row of zeros that nothing reads.

The Wafer's destructor is VCPolyhedron's, at 0x001cebc0 in
`CollisionBody.obj`.

## Collision volumes

The art pipeline's volumes arrive in chunk 0x80034020. It is in each car's
`GEOMETRY.BIN`, in `INGAMEB.BUN` and in the track bundles. The container
holds groups of five chunks:

| Chunk | Holds | Record on the disc |
|---|---|---|
| 0x34021 | the PipelinePolyhedron | 96 |
| 0x34024 | vertices | 20 |
| 0x34023 | edges | 12 |
| 0x34022 | faces | 24 |
| 0x34025 | Voronoi planes | 24 |

Each record array starts on the first 16-byte boundary at or after its
chunk's payload, and the pad in front of it counts in the chunk's size. The
pads are laid out for where the container lies on the disc. The image just
takes `(chunk + 8 + 15) & ~15`, so a container moved to another 16-byte
residue has to be repacked first. The checker does that for its moved
copies.

The header record carries:

- the name's bStringHash at +48;
- the name at +52;
- `CenterOfGravityFixed` at +84, which is 0 on the disc;
- eight zero bytes at +88.

The tool leaves junk in the link, the four array pointers and the maxima,
and the loader overwrites all of it. The array records hold plane indices
and feature codes, VClip's memory-image form.

The disc has 43 volumes:

- one per car, fourteen in all;
- CS_SMOKEBOMB and CS_Rocket in INGAMEB;
- 27 in TRACKB12, the track's props (billboards, barrels and the like).

**LoaderCollisionVolumes** (0x00205c00) answers 0 for any chunk but
0x80034020. Otherwise it takes each group of five in turn and **does not
look at their ids**. It assumes the header, vertices, edges, faces and
planes, in that order. For each group it:

1. links the header onto the tail of `PipelinePolyhedronList`;
2. runs `MemoryImageLoad` on each array's aligned start, with the record
   count `(size - pad) / record`;
3. runs `SetVoronoiPlanes`.

It then answers 1. An empty container answers 1 and loads nothing.

**UnloaderCollisionVolumes** (0x00205db0) also answers 0 for any other
chunk. It walks every child and does test the id. Each 0x34021 is unlinked
and handed to `MemoryImageUnload`. The loader and unloader therefore
disagree about a group whose header has some other id. The loader loads it
and the unloader skips it, so it stays in the list.

MemoryImageUnload only closes the polyhedron. A loaded volume is not
dynamically allocated, so that deletes its Caffeine object if it has one,
and does nothing else. The arrays stay as pointers, so a container unloaded
in place is not fit to load again.

**FindPipelinePolyhedron** (0x00205e68) walks the list from the head and
answers the first volume with the hash, or NULL. A container loaded twice
answers with its first copy. When a centre of gravity is given and the
volume's is not fixed yet, the volume is moved there first. A NULL cog, or
a volume already fixed, leaves it where it is.

**MoveCenterOfGravity** (0x00205ed0) offsets by `vf00 - cog`: 0 - x on
three lanes, and 1 - w on the fourth, which nothing reads. It moves every
vertex, moves every face's distance by `n·offset`, rebuilds the Voronoi
planes and sets `CenterOfGravityFixed` to 1. Find calls it once per volume.
A direct call moves the volume again.

**The list.** `PipelinePolyhedronList` (0x00324a30) is a bTList head,
statically linked to itself.

- `_GLOBAL_$I$` (0x002063f8) links it to itself again. Run with volumes
  listed, it forgets them, and they still point at the head.
- `_GLOBAL_$D$` (0x002063e8), through `~bTList<PipelinePolyhedron>`
  (0x00206378), unlinks each volume still listed and destroys it with
  flags 3. That frees memory that lives in a chunk. The console never runs
  its static destructors.

## The tests

Nothing calls these four. They are ported because they are in the image.

- **TestCubes** (0x00205860) runs these steps, with a bGetTicker between
  steps (eight in all). It throws every result away.
  1. It draws two sizes from bRandom(100) and two angles from bRandom(360)
     times DEG. It takes each cosine as `sin(a + HALF_PI)`. m1 turns about
     z by the first angle and m2 about x by the second. Each lane of the
     two translations is bRandom(200) - 100, and their w lanes are never
     set.
  2. It builds cubes of the two sizes on the stack.
  3. It builds a third cube of the second size in a 2800-byte bMalloc and
     deletes it with flags 3, unused. The `NULL` test around the delete
     never fails: the image's bMalloc asserts in bWare's allocator rather
     than return NULL.
  4. It sets up a witness on the two stack cubes and VClips.
  5. It moves the first cube 30 along x and VClips again.
  6. It destroys the witness and both cubes with flags 2.
- **InitVoronoiClip** (0x00205bc0) loops forever. Each pass reseeds with
  `TestCounter + 1000000`, runs TestCubes and adds 1 to TestCounter.
  TestCounter (0x00324a28) is 5248 on the disc. The add is an `addiu`,
  which wraps at 2^31. The port adds as unsigned, because `++` on an
  int32_t would be undefined there.
- **RandomLocation** (0x00205f90) builds a turn and a position:
  - the turn: three rows of bRandom(1) on each lane with w 0, a last row of
    (0, 0, 0, 1), then eOrthonormalizeMatrix in place;
  - the position: each lane bRandom(50) - 25, with w 1.0.
- **TestVClipRepeatability** (0x00206140) runs DIABLO_CV against itself
  1,000,000 times. The outer count is `lui 0xf ; ori 0x423f` (999999),
  tested with `slt` after the increment. Each pass:
  1. draws a pair of random poses, re-drawn until VClip stops answering 2;
  2. runs a fresh witness on another random pair, then on the first pair.
     This is the inner loop, a do-while whose counter starts at 0 and is
     tested after a decrement, so it runs once.

  Nothing is compared.

The two gp constants are not quite what their names say. DEG is 0x3c8efa36
and HALF_PI is 0x3fc90fdc. Each is one ulp above the float nearest π/180
and π/2.

## Verification

`tools/polyhedra_check.py` runs the shipped functions out of `NFSHP2.ELF` in
`tools/mipsemu.py`, and the port in the harness. Both follow one script,
and the two transcripts are diffed. Polyhedra are named, not printed as
addresses:

- rN, wN: the script's Rect and Wafer slots;
- Vk.j: container k's volume j;
- p1, p2: a witness's two polyhedra;
- #n: the nth bMalloc.

Floats are compared as bits.

Neither side can be handed the other's memory, so the disc chunks are
widened for the host. The harness rebuilds each container with the host's
record sizes and pads for its placement, and the loader's strides are the
host's own. The model loads the disc bytes as they are.

The script covers:

- the ten tables and the three gp constants;
- Rects over:
  - proper, inverted and inside-out boxes;
  - uneven, thin, flat and large boxes;
  - bounds at +0 and -0, and far from the origin;
- Cubes of every sign, including ±0;
- the destructors' flags;
- Wafers over:
  - every one of TRACKB12's 15708 polygons, as the image's TrackPolygon
    constructor builds them. The first forty are dumped in full and the
    rest are folded into a CRC32 each. Every fifth has an origin near
    corner 0, with junk in its w lane;
  - made-up quads and triangles, including corners either side of bEqual's
    0.001 on each axis, pads that differ and nothing else, junk w lanes,
    and -0 normals;
  - three quads whose first edge is one of the rare vectors where
    `x + (y + z)` rounds len² differently, by enough to move a truncated
    direction lane. About one random vector in 7,000 is one, and no track
    edge is;
- the loader and unloader over:
  - every collision volume on the disc, at the disc's alignment;
  - a car's container repacked for the other three residues, and TRACKB12
    repacked at 4;
  - containers made to be wrong: an empty one, a wrong top id, a header
    with another id, and one with an Espresso object;
  - a car's container with one vertex's y set to -0. No volume on the disc
    has a -0 anywhere, and MoveCenterOfGravity's `0 - x` only parts from
    `-x` on a +0 cog lane added to a -0;
- Find:
  - with and without a centre of gravity;
  - three times on one volume, and with -0 in the cog;
  - on a name listed twice, on one not listed, and on hash 0;
- MoveCenterOfGravity;
- the list's static initialiser, re-run with a volume listed, and its
  destructor;
- RandomLocation, and TestCubes over twelve seeds;
- InitVoronoiClip, stopped at the first ticker after a given number of
  tests, from TestCounter 5248, 0, -1000000 and 2^31 - 2;
- TestVClipRepeatability, with the outer count patched down to 0, 2 and
  5, and from a seed whose first pair of poses penetrates and is drawn
  again.

The tests throw every result away, so the checker compares their calls
instead. That covers:

- the witness constructor, with both polyhedra dumped;
- VClip's arguments and the witness it leaves;
- the destructors, with TestCubes's heap cube dumped as it goes;
- bGetTicker, bMalloc and bFree.

Two lane sets are stack junk in the image, so only three lanes are printed
for them: TestCubes's translations, and the contact points. The Rect
constructor never writes the link, so a witness's stack cubes print theirs
as "-".

Two things surfaced while it was being built:

- **mipsemu zero-extends a call's arguments.** The image's `lw` sign-extends
  and its `bnel` compares whole registers. Find of a hash with the top bit
  set therefore missed in the model until the checker passed arguments
  sign-extended.
- **TestCounter's add** is described above.

```
polyhedra_check  55 scenarios, 15907 ops, 64560 lines, 0 differ
                 15708 TRACKB12 polygons (6752 triangles), 93 volume dumps
                 VClip statuses 1 x70, 2 x4
```

`--mutate` runs 184 mutations: 172 are caught and 12 are equivalent,
with 0 unexplained. The 12 are:

- five writes to a fourth lane nothing reads:
  - the Rect's and the Wafer's vertex pads (NewVertex reads three lanes);
  - the Wafer faces' normal pads (NewFace reads three lanes and takes the
    distance apart);
  - the cog offset's pad (MoveVertex and MoveFace read three lanes);
- RandomLocation's rows' w lanes and its last row, three writes.
  eOrthonormalizeMatrix reads only the first two rows' x, y and z, and
  writes all sixteen lanes;
- reading WaferEdgesNearFaces's row 0 for both faces: the two rows are the
  same;
- the `0 +` after the Wafer's `1/√`, which only changes a -0;
- scaling a Rect edge of no length by its zero extent. Its direction is
  stored as int16s, and it comes out 0 on both machines: NaN on the host,
  which `ee_trunc_w` stores as 0, and 0 on the EE, which has no NaN;
- TestCubes's `NULL` test on the heap cube, which bMalloc never fails.

Three mutants survived the first pass and needed cases of their own:

- len²'s grouping;
- the cog's `-x`;
- dropping the second pose's re-draw in TestVClipRepeatability.

The witnesses were hunted the way VClip's were: float32 arithmetic in
numpy for the edge vectors, and the harness alone, with no emulator, for
the seeds. The first penetrating first pair came at the 2,291st seed tried.
The Cube's `0 - size·0.5` needed a cube of size 0, which was added before
the first pass.

One constant is checked by reading instead: TestVClipRepeatability's outer
count. A million VClips is beyond the emulator. The model asserts the
listing's `lui`/`ori` words before it patches them down, and the port
spells the same 999999.
