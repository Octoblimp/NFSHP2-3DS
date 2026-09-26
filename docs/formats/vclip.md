# VClip

`VClip.obj` (0x001c5d90 .. 0x001ca008), 54 functions. The first slice of
task 27's collision work. [CollisionBody](collision-body.md) builds on it
and so does the polyhedron builder, [polyhedra.cpp](polyhedra.md).

Ported to `3DS Files/source/vclip.{c,h}`. Cross-checked by
`tools/vclip_check.py` against `tools/src/vclip_test.c`.

This is Brian Mirtich's V-Clip (MERL TR-97-05), bWare's version. It finds
the closest pair of features of two convex polyhedra by walking a feature
of each towards the other. At every step one feature is tested against the
other's Voronoi region. If it lies outside a bounding plane, the walk steps
across that plane to the neighbour. If it lies inside, the pair is closest.
From one frame to the next the answer barely moves, so starting from last
frame's pair settles in a step or two. The collision bodies keep one
`VCWitness` for each pair of bodies for that reason.

## Features and planes

A polyhedron is three arrays of features plus one shared pool of Voronoi
planes. Each feature points at its own run of planes in the pool. Each
plane is a half-space `n·p >= d` and names the feature across it:

| Feature | Planes | Plane k faces | Neighbour |
|---|---|---|---|
| vertex | one per edge meeting it | along the edge, away from the vertex | that edge |
| edge | four | 0 along the edge from the tail, 1 back from the head, 2 and 3 out of each face | tail, head, face, face |
| face | one per edge round it | inwards, from the face normal crossed with the edge | that edge |

`NumPlanes` is an int8 and the counts are int16s, so a face has at most 127
edges. The record layouts are in `vclip.h`'s head. They are the stabs' to
the byte, and each record that holds a pointer carries a layout assert that
allows for the host's wider pointers.

Three encodings are not what the stab names suggest:

- `CompressedNormal`, `CompressedPlaneDistance` and `CompressedPosition`
  are plain floats.
- `CompressedDirection` really is compressed: three int16s in units of
  2^-13. `NewEdge` multiplies by 8192 and converts with `cvt.w.s`, which
  truncates on the EE. The port calls `ee_trunc_w`. A component of 4.0 or
  more wraps the int16.
- The plane pointers and neighbour pointers of a loaded image are indices.
  A plane is stored as its index in the pool. A neighbour is stored as a
  *feature code*, `(index << 4) | type`, with `0xffffffff` for none.
  `GetFeatureCode` gets the index by multiplying the byte offset by the
  inverse of the record size, which is exact for any feature in its array.
  `ConvertToIndicies` (sic) and `ConvertToPointers` switch between the two
  forms. `MemoryImageLoad` takes a loaded image, sets the counts and
  converts it to pointers.

### Building the planes

`VCPolyhedron::SetVoronoiPlanes` does vertices, then faces, then edges, and
the order matters. An edge's face planes (2 and 3) are copied from its
faces' planes: the reverse of the face's plane for that edge, with its
distance measured at the edge's head. The faces therefore have to be done
first. If a face does not list the edge, the plane is left as it was.

A face's plane for edge e is `n × dir(e)` through e's tail. It is turned
round if the next vertex along the face lies behind it. The next edge comes
from `GetNextEdgeInFace`, and nothing tests it for NULL, so a face whose
edges are not a closed loop crashes the image here.

A vertex's plane for edge e is e's direction if the vertex is e's head, and
the reverse (`0 - x` on each lane) if it is the tail.

## The walk

`VClip(r1, t1, r2, t2)` builds two transforms, `x12` from P1's frame into
P2's and `x21` the other way. It then runs up to 80 steps, each dispatched
on `F1->Type + (F2->Type << 16)`:

| code | check | SwitchState |
|---|---|---|
| 0x00000 | vertex, vertex | 1 |
| 0x10000 | vertex, edge | 1 |
| 0x00001 | edge, vertex → vertex, edge | 2 |
| 0x20000 | vertex, face | 1 |
| 0x00002 | face, vertex → vertex, face | 2 |
| 0x10001 | edge, edge | 1 |
| 0x20001 | edge, face | 1 |
| 0x10002 | face, edge → edge, face | 2 |

Each check takes a "first" and a "second" feature. SwitchState says which
of F1/F2 is first. When it is 2, the transforms and the transformed-feature
buffers are passed swapped. Each check answers 0 if a feature moved, 1 if
the pair is closest and disjoint, and 2 if they touch or penetrate. The
walk returns the first non-zero answer, or the last answer after step 80.

**Face against face has no case.** Code 0x20002 falls through the switch,
the status stays 0, and the call spins out its 80 steps and returns 0 with
nothing changed. A bad `Type` does the same. The walk never steps into a
face-face pair itself: every check moves one feature at a time, and a
face's neighbours are edges. Only a caller that starts from two faces can
reach it. The port does the same.

**The step limit is observable.** The checker's walk scenario starts a
small box on the far side of a hundred-sided wafer. The walk round the rim
takes more than 80 steps, so the first call returns 0 partway round and the
next call carries on from there.

### The checks

- **Vertex–vertex.** Each vertex is tested against the other's planes, and
  the first violated plane moves the other feature. If neither violates
  one, the distance is between the two positions. The answer is 1 above
  1e-5, 2 at or below.
- **Vertex–edge.** The vertex is tested against all four of the edge's
  planes. Then the edge is clipped against the vertex's planes, and a
  neighbour it runs into replaces the vertex. The closest point on the
  edge is the vertex's projection onto the edge's *line*, unclamped: the
  edge's end planes have already put the vertex between the ends.
- **Vertex–face.** The vertex is tested against the face's edge planes. The
  *most* violated one moves the face, not the first. A vertex over the face
  within 1e-4 of its plane is touching. Otherwise, an edge at the vertex
  whose far end is closer to the plane replaces the vertex. If the vertex
  is in front of the face the answer is 1, with the foot of the
  perpendicular as the contact point. If it is behind, it has gone
  through: every face of the other polyhedron is searched for the one the
  vertex is least deep behind. That face becomes the second feature, and
  the answer is 2 if the vertex is still behind it and 1 if it has come
  out in front.
- **Edge–edge.** Each edge is clipped against the other's two vertex planes
  and then, on the *same* clip without a reset, its two face planes. This
  is `SubCheckEdgeEdge`, whose `which` argument says which slot the
  neighbour it finds goes into. If both edges survive, the closest points
  are the textbook segment–segment ones, clamped to the first edge and
  projected unclamped onto the second. Edges within 1e-6 of parallel take
  whichever end of the first edge the offset leans towards.
- **Edge–face.** The edge is clipped against the face's edge planes. If a
  piece survives and crosses the face's plane, the answer is 2. If it
  survives without crossing, the end leading towards the plane decides:
  the clip's neighbour at that end if it has one, otherwise the edge's
  vertex at that end. If the edge is clipped away entirely, each of the
  face's edges is tried with the edge-edge closest points. The nearest one,
  or the region its vertex planes send the edge to, becomes the second
  feature. A penetration found during that search answers 2 and **leaves
  Distance as it was**, the only answer-2 path that does not zero it.

### The clips

`ClipPlanes` narrows `[LambdaMin, LambdaMax]` on the segment Tail→Head, one
plane at a time. It records the plane's neighbour at whichever end moved,
and returns 0 once the interval is empty. When both ends are outside one
plane, *both* neighbours are set to that plane's neighbour, and
`ClipFacePlanes` depends on that.

`ClipVertexPlanes` runs the clip and **ignores its answer**. It then asks,
for each end, whether the segment heads away from that neighbour's vertex
there. An end within √1e-5 of the vertex sets `Penetration`. The optional
`vert` argument stands in for both neighbours' positions. Vertex–edge
passes the vertex, because there the neighbours are the vertex's edges and
have no position.

`ClipFacePlanes` asks the same question of faces, using signed plane
distance against the segment's direction, with a touch band of 1e-4. When
the clip emptied with a face at one end, that face is the fallback answer
if the other end gives nothing.

## Lanes

Every vector here is a VU0 quadword in the original, and the arithmetic
follows the listing lane by lane:

- a dot product is `((x·x' + y·y') + z·z')`, rounded at each step;
- a transform is the ACC chain `((r0·x + r1·y) + r2·z) [+ r3]` over all
  four lanes;
- a negation is `vsub.xyz vf, vf00, vf`, i.e. `0 - x`, which gives +0 for
  +0 where a true negation would give -0.

The fourth lane is carried wherever the original stores it and a reader
could see it: the transformed features' Head and Edge (Edge's w is Head's,
because the subtract is `.xyz` into Head's register), and the contact
points.

Three contact-point stores write a quadword whose fourth lane was never
set. The value is a vertex position assembled on the stack with three
`swc1` and moved with `sqc2`, so the w lane is whatever the frame held.
They are:

- vertex–vertex's two points, and
- vertex–edge's vertex point when it penetrates.

The port writes 0 there. Nothing in the image reads a contact point's w.
The checker presets both w lanes to 7.0 before each VClip and masks exactly
those stores. Every other lane VClip leaves alone is compared, so a stray
w write anywhere else still shows up.

`vcwitness_init` zeroes the contact points' xyz and leaves their w alone,
as the constructor does.

## Development code

- **The Caffeine plots** (`PlotToCaffeine` on the polyhedron and on the
  witness) have no callers. They draw through Espresso's live link, which
  is behind the seams in `espresso.h`. Two quirks are kept:
  - The polyhedron's mesh is sized before its object is tested for NULL.
  - The witness makes both objects and then tests only the first.

  `CreateUserMeshFace` gathers a face's vertices into eight stack words and
  its corners into a four-corner buffer, with no bound on either. The port's
  buffers hold any face (`VC_MESH_FACE_CORNERS`), and the call still passes
  the first four corners.
- **The Print family** does nothing but walk the planes and store the
  polyhedron in `pPrintingPolygon`. `PrintFeature`, `PrintState` and
  `PrintMatrix` are each a bare `jr ra`.
- **The debug switches.** `PrintThisTime` makes VClip print both
  polyhedra. `PlotClosestFeatures` makes it build the two placement
  matrices and then use neither, because the plot call is compiled out.
  Both switches are zero on the disc, and nothing in the image writes them.
- **`DoSnapshot`** is not ported. It needs `ReplaySnapshot`, the same
  dependency that held back `CarState::DoSnapshot`.

## Verification

`tools/vclip_check.py` runs the shipped functions out of `NFSHP2.ELF` in
`tools/mipsemu.py` and the port in the harness. Both follow one script and
the two transcripts are diffed. The records hold pointers, so neither side
can be handed the other's memory. Instead, both build the same polyhedra
through the same public calls, and every feature in the transcript is
named by polyhedron, kind and index. Floats are compared as bits.

The script covers:

- the polyhedron calls: the constructor, both Inits, every New call to and
  past its limit, and the int16 and int8 wraps;
- the Voronoi planes of eight shapes, plus one built a feature at a time in
  the wrong order;
- both Moves and GetNextEdgeInFace;
- feature codes, conversion to indices and back, and memory images;
- all four transform forms, over matrices with junk in the lanes a rotation
  leaves zero;
- the three clips, driven directly, both from a fresh clip and from one
  carried over, including segments that end on, a hair off, or within a
  few ulps of their touch limits;
- exact contacts between unit boxes, boxes turned onto an edge and a
  vertex, and parallel edges;
- a walk longer than the step limit;
- 900 random poses of every pair of shapes from every kind of starting
  pair, with coherent runs where each call starts from the previous
  answer;
- single steps of the walk, one check at a time, set up the way VClip sets
  them up. The walk settles on the same closest pair whichever way a
  single step goes, so part of each check can only be seen this way. The
  steps cover:
  - VV and VF either side of the touch distance;
  - VE, EE and EF penetration, with and without a distance left by an
    earlier call;
  - parallel and near-parallel edges;
  - edges lying exactly parallel to one of a face's octahedral diagonals.
    A diagonal is stored as 5793 × 2^-13, just over unit length, so the
    point on the face edge's line that CheckEdgeFace starts from changes
    its answer;
- the plots, the witness's destructor and the Print walk's one store.

Across 2001 VClips the statuses were 0 ×32, 1 ×1046 and 2 ×923. The 938
single checks returned 0 ×662, 1 ×44 and 2 ×232. 0 lines differ overall.

`--mutate` runs 281 mutations: 280 are caught and 1 is equivalent, with 0
unexplained. The equivalent one drops `GetFeature`'s test for the "none"
code, `0xffffffff`. That code's type nibble is 15, and the switch's default
answers 15 with NULL anyway. The test is the image's, so the port keeps it.
