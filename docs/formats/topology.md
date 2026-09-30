# `Track.obj` and `TerrainType.obj` -- the ground under the car

Every car asks the track two questions every frame: how high the ground is
under each wheel, and whether the move it is about to make goes through a
wall. `Track.obj` answers both. It carries the collision surface as four
chunks -- a quadtree, its leaf squares, packed polygons, and an index table --
builds float polygons from them on demand into a reference-counted pool, and
gives every car a `TopologyCoordinate`: a cached window onto the polygons
near it. The same object also owns the track's named position markers, the
table of every track and the loaded one's entry, and the road noise the
tyres feel. `TerrainType.obj` is the 33-entry table that every polygon's
terrain number indexes.

    Track.obj          retail 0x001513c8 .. 0x00153984    9.4 KB
                       (demo 0x0014e7d0 .. 0x001509d4, 8.5 KB)
    TerrainType.obj    demo 0x001ca078 .. 0x001ca178      256 B, and its table
                       TerrainTypeInfoTable 0x00310a90, 33 x 140 bytes
                       (retail 0x001d4428, its table 0x00318c00, 33 x 144)

The port is `3DS Files/source/track.c` and `topology.h`/`track.h` for
`Track.obj`, and `terraintype.c`/`terraintype.h` with the generated
`terraintypetab.c` for `TerrainType.obj`. `track.c` is retail's but for
road noise, which reads `TerrainTypeInfo` and so stays the demo's until
the terrain table has its own retail pass. `tools/track_check.py` runs the
image itself in mipsemu as the oracle: 16779 ops and 10306 transcript
lines on the retail image and 1254 ops and 1073 lines on the demo one, 0
differ. Its mutation pass has 314 mutations, 308 caught and 6 argued
equivalent. It also checks the first of Car's methods to
call in here, which are in `cartrack.c` and written up in `car.md`.
`tools/gen_terrain_table.py` writes the table out of the ELF, and
`--check` confirms it is current.

## Where things are

| retail | demo | what |
|--------|------|------|
| `0x001513c8` / `0x00151450` | `0x0014e7d0` / `0x0014e858` | `GetNumTrackPositionMarkers` (hash / name) |
| `0x00151408` / `0x00151478` | `0x0014e810` / `0x0014e880` | `GetTrackPositionMarker` (hash / name) |
| `0x001514a8` | `0x0014e8b0` | `TrackPolygon::TrackPolygon` |
| `0x00151770` | `0x0014eb78` | `TrackPolygon::~TrackPolygon` |
| `0x001517d8` | `0x0014ebe0` | `TrackPolygon::PointInShaft` |
| `0x00151990` | `0x0014ed98` | `TrackPolygon::SegmentIntersects` |
| `0x00151a88` | `0x0014ee90` | `TrackPolygon::TestSegmentToPoly` |
| `0x00151c28` / `0x00151c70` | `0x0014f030` / `0x0014f068` | `TopologyCoordinate` constructor / destructor |
| `0x00151cd0` | `0x0014f0c8` | `ClearInterestBBox` |
| `0x00151d30` | `0x0014f120` | `SetInterestBBox` |
| `0x00136e00` | `0x00134f28` | `SetInterestBBox(bVector3)`, emitted in `Car.obj` |
| `0x00152070` | `0x0014f418` | `GetElevation` |
| `0x00152558` | `0x0014f7e8` | `HasTopology` |
| `0x001525a0` | `0x0014f830` | `TopologyCoordinate::SegmentIntersects` |
| `0x001528b0` | `0x0014f920` | `ConstrainToTopology` |
| `0x00152b10` | `0x0014fb80` | `TopologyTree::TopologyTree` |
| `0x00152b48` / `0x00152b98` | `0x0014fbb8` / `0x0014fc00` | `InitTree` / `CloseTree` |
| `0x00152c10` / `0x00152d30` | `0x0014fc78` / `0x0014fd98` | `TopologyTree::Loader` / `Unloader` |
| `0x00152db0` | `0x0014fe18` | `GetSquareCorner` |
| `0x00152e08` | `0x0014fe70` | `GetSquare` |
| `0x00152f38` | `0x0014ffa0` | `GetIntersectingPolygons` |
| `0x001530a8` | `0x00150110` | `FlushUnusedTrackPolygons` |
| `0x00153148` / `0x001531e8` | `0x001501b0` / `0x00150250` | `AssignTrackPolygon` / `UnAssignTrackPolygon` |
| `0x001531f8` | `0x00150260` | `BuildTrackPolygons`, rewritten |
| `0x001533c8` | `0x00150420` | `RemoveTrackPolygons` |
| `0x00153420` | `0x00150478` | `GetTrackInfo` |
| `0x00153458` / `0x00153498` | `0x001504b0` / `0x001504f0` | `GetRoadNoiseGridValue` / `GetRoadNoise` (the port's is the demo's) |
| `0x00153608` / `0x00153718` | `0x00150660` / `0x00150770` | `LoaderTrackGeometry` / `UnloaderTrackGeometry` |
| `0x001538b0` | `0x00150908` | `_GLOBAL_$D$TrackPositionMarkerList` -- not ported, below |
| `0x001538e0` | `0x00150938` | `_GLOBAL_$I$TrackPositionMarkerList` |
| `0x00153978` | `0x001509c8` | `TrackPolygon::__dl`, the slot free |
| `0x001cb350` | `0x001c1210` | `GetVectorOnTrack` |
| `0x001d4428` / `0x001d4498` | `0x001ca078` / `0x001ca0e8` | `MatchTerrainType` (name / hash; the port's is the demo's) |
| `0x001d44d0` | `0x001ca120` | `_GLOBAL_$I$TerrainTypeInfoTable` |

Retail's `Track.obj` also has eight bytes at `0x00153970`, `j 0x00151d30`
and its delay slot, that nothing jumps or calls to: another emitted copy
of a `SetInterestBBox` overload.

| global | retail | demo |
|--------|--------|------|
| `TheTopologyTree` | `0x002f9498` | `0x002f14c8` |
| `RoadNoiseTable[16]` | `0x002f94c8` | `0x002f14f0` |
| `TopologyTiming[10]` | -- | `0x002f1530` |
| `TrackPositionMarkerList` | `0x00330310` | `0x00323410` |
| `TopologyTimingIndex` | -- | `0x00323418` |
| `TopologyTreeUnused[2]` | `0x00330318` (gp-21976) | -- |
| `TrackPolygonSlotPool` | `0x0033032c` | `0x00323424` |
| `CurrentTrackInfo` / `TrackInfoTable` | `0x00330330` / `0x00330334` | `0x00323428` / `0x0032342c` |
| `HighestTrackNumber` / `LoadedTrackNumber` | `0x00330338` / `0x0033033c` | `0x00323430` / `0x00323434` |

## The chunks

`LoaderTrackGeometry` takes seven types. It handles three itself and hands
everything else to `TopologyTree::Loader` as a tail call.
`tools/chunk_loader_table.py` reports only the first two; `bchunk.md` says
why. The counts are retail TRACKB12's.

| type | record | TRACKB12 | what |
|------|--------|----------|------|
| `0x00034200` | `TrackInfo`, 164 (demo 160) | 1 | the loaded track's own entry |
| `0x00034201` | `TrackInfo`, 164 (demo 160) | (GLOBALB) 66 (demo 63) | every track |
| `0x00034146` | `TrackPositionMarker`, 24 | 20 | named points |
| `0x00034130` | `TopologyTreeNode`, 8 | 386 | the quadtree |
| `0x00034131` | `TopologyTreeSquare`, 12 | 646 | its leaves |
| `0x00034132` | `TopologyTreePolygon`, 32 | 15098 (demo 15708) | the surface |
| `0x00034133` | `uint16_t` | 22276 (demo 23082) | polygon numbers, sliced by the squares |

All seven are used in place, and none is copied. The node and square
tables start at the first 16-byte boundary past the chunk header, so their
counts are what is left of the chunk after that pad. In retail TRACKB12
the node chunk is 3088 bytes with no pad (the demo's was 3092 with 4), and
the square chunk 7760 with 8.
The polygon chunk is **read-write**: the loader writes -1 into every
polygon's `TrackPolygonNumber`, and building a TrackPolygon writes its slot
number back. The marker chunk is read-write too, since the loader links its
records into a list in place.

## The records

**`TopologyTreePolygon`**, 32 bytes, the packed form:

| offset | field | |
|-------:|-------|---|
| 0 | `UsedByNeighbourFlag` | set while a build has it listed |
| 1 | `MaxMinBits` | which vertex gives each bound: min x, min y, max x, max y, two bits each from the low end |
| 2 | `Type` | the terrain |
| 3 | `Flags` | below |
| 4 | `ZBase` | whole units |
| 6 | `TrackPolygonNumber` | its TrackPolygon's slot, or -1 |
| 8 | `VerticesX[4]` | eighths |
| 16 | `VerticesY[4]` | eighths |
| 24 | `VerticesZ[4]` | 1/256ths above `ZBase` |

The code reads the vertices through Q16: x is `(v << 13) / 65536` and z is
`((v << 8) + (ZBase << 16)) / 65536`. The z sum is added as words before it
is converted, so it wraps, and it rounds once rather than twice. The port
spells both shifts on unsigned words, since C defines a left shift of a
negative value only that way. Since x and y are int16 eighths, **the world
spans only +-4096**, although the quadtree covers +-16384.

A triangle's fourth vertex is data. `GetElevation`'s edges are 0-1, 1-2
and 3-0, and 2-3 only for a quad, so a triangle is closed by its fourth
vertex. That is normally its third. A fourth vertex that is not the third
makes the closing edge 3-0 instead of 2-0. The checker's world has
triangles like that. TRACKB12 does not. An edge of zero length crosses to
0, so a quad with one is never strictly inside anything.

| bit | flag | TRACKB12 |
|-----|------|----------|
| 0 | `INFINITELY_HIGH` -- `GetElevation` keeps looking for a higher surface | |
| 1 | `VERTICAL` -- a wall | |
| 2 | `Z_TIMES_FOUR` -- z scaled by four after unpacking | |
| 3 | `UPSIDE_DOWN` -- a ceiling | |
| 4 | `QUAD` | |

Retail TRACKB12's flags, as values: 0 ×4874, 1 ×159, 8 ×282, 16 ×5213, 17
×591, 18 ×196, 22 ×3664 and 24 ×119. Most of its walls (22, a quad wall
with z times four) are tall. No polygon on it is both vertical and upside
down. Its terrains: ROAD 3918, WOOD_WALL 2556, GRASS 2534, DIRT_SHOULDER
2317, DIRT 1383, DIRTROAD 1016, SOLID_WALL 918, ROCK 163, MULCH 80,
SIDEWALK 76, PUDDLE 66, POTHOLE 24, DEEP_WATER 23, METAL_GRATE 16 and NONE
8. GetElevation reads the terrain as a signed byte, so a number past 127
would come out negative. None is.

**`TopologyTreeSquare`**, 12 bytes: a centre and a slice
`[FirstPolygonIndex, +NumPolygons)` of the index table. On TRACKB12 the
largest square lists 119 polygons, so no one square fills the 160 a
coordinate holds. Square 0 is a sentinel, empty and centred at (999999,
999999). No node can reach it, since a child number of 0 means none.

**`TopologyTreeNode`**, 8 bytes: four child numbers, where 0 means none.
Above the leaves a child is a node, and at level 1 it is a square.

**`TopologyTree`**, 44 bytes in retail (the demo's 40): the four tables and
their counts, a word at 32 that only the constructor writes, and the
list head of every built TrackPolygon at 36.

**`TrackPolygon`**, 128 bytes (`.mdebug`), the float form:
- the list node;
- the reference count, the vertex count, the flags and the terrain;
- `pPolygon`, which points back at the packed record;
- `pCollisionBody`, which the constructor zeroes and then leaves to others;
- the 2D bounding box;
- four `bVector3` vertices, 16-aligned;
- the normal and the plane distance.

The normal is the cross of the first two edges out of vertex 0, times
`1/sqrt` of its length squared. `GetNormal` hands out its address as a
`bVector3 *`, so a four-lane read of it picks up `PlaneDistance` as the
pad, and `GetElevation`'s copy-out does exactly that.

**`TopologyCoordinate`**, 704 bytes in retail (the demo's 560): an interest
box, a cached box, a table of 160 TrackPolygon pointers (the demo's 128),
the four counts at 672, the last polygon `GetElevation` found at 688, and
three words at 692 that only the constructor writes. Car embeds one at
+1312 (the demo's +1280).

## The tree and the pool

**`GetSquare`** walks ten levels down from a 32768-unit root at -16384, so
a square is 32 units. When a child is empty, it can instead take the
node's nearest non-empty child. That child is scored by the distance from
the point to the corner of the quadrant just chosen, and the distance is
the same for all four, so "nearest" is **the first non-empty child**. With
no non-empty child at all, the pick stays -1, and the image indexes the
table with it. The port does the same, and the checker's malformed tree
runs that path.

**`BuildTrackPolygons`** was rewritten for retail. It walks **every
square under the box**, a row at a time from the bottom left: y from the
square corner at or below the box's minimum, x likewise, each stepping by
32 while it is at or below the box's maximum. So a box that ends exactly
on a square's edge takes in the row or column beyond it. The walk runs
only when -32768 < min and max < 32767 on both axes; a box that reaches
either bound gathers nothing, since the grid's Q16 corner would overflow.
A box just inside the bounds walks nearly 2048 squares a side.
The demo looked only at the squares under the box's four corners, so a
wide box missed the ones between.
`GetIntersectingPolygons` takes each listed polygon whose box touches the
query box, with touching included, and marks it `UsedByNeighbourFlag` so
that a second square does not list it again. The build clears the marks as
it assigns. The cap, 160 from `SetInterestBBox`, is over all the squares.

**The pool** is 1024 slots of TrackPolygon. `InitTree` makes it with neither
`OVERFLOW_IF_FULL` nor `ZERO_ALLOCATED_MEMORY`, and in retail also zeroes
`TopologyTreeUnused[2]`, two words nothing in `Track.obj` reads.
`InitTree` is called from `EndGameFlowLoadingTrackSpecific`.
`AssignTrackPolygon` returns the existing TrackPolygon when the packed
record has a slot number. Otherwise it builds one, appends it to the
tree's list, oldest first, and takes a reference either way. `UnAssign`
drops the count by one and does nothing else, so a TrackPolygon outlives
its last user. When the pool is full, `Assign` calls
**`FlushUnusedTrackPolygons`**, which walks the list oldest first and
destroys every polygon with a zero count, **at most 101** per flush. A
flush that frees nothing calls `bBreak`, the debugger's stop. The next
build then lands in a NULL slot. The port has no debugger to stop in, and
carries on to the same NULL. `CloseTree` destroys everything still listed
before it deletes the pool. In the game every allocated polygon is listed,
so the pool's "deleted while not empty" warning cannot fire.

Slot **numbers** are what the image and the port share. A host slot is 144
bytes against the image's 128, because two pointers widen.

## `SetInterestBBox`

The interest box is `pos +- r`. If the cached box still contains it,
nothing happens. Otherwise the table is released, the last polygon is
forgotten, and a new cached box is built:
- with no velocity, `pos +- (r + 0.5)`;
- with one, that box and the same box round `pos + vel * s` together.
  `s` starts at 0.15 and is multiplied by 0.75 after each try, and the
  fifth try uses 0, the box with no look-ahead. The first box whose
  diagonal is under 28.8 stands, and so does the fifth whatever its size.

The demo started `s` at 0.5, halved it over up to ten tries and wanted a
diagonal under 32. The build over that box then fills the table in
**three passes**:

1. everything neither vertical nor upside down, which becomes
   `NumTrackPolygons`, the part `GetElevation` searches;
2. if pass 1 left anything out, the vertical ones;
3. if the first two together still left anything out, the upside-down
   ones.

A polygon both vertical and upside down is placed by pass 2 **and** by
pass 3, so it is in the table twice. When it is the only thing pass 1 left
out, pass 2 fills the count and pass 3 does not run at all.

Retail stores `NumUpsideDownTrackPolygons` as what pass 3 placed. The
demo stored (everything placed) - (vertical), which with the usual
all-floor build came out as the total. Nothing in `Track.obj` reads it
back.

The `bVector3` overload (`0x00136e00`) is eight bytes that the compiler
emitted in `Car.obj`: `j 0x00151d30`, with the registers as they came, so
only x and y of each vector are read. It is `topology_set_interest_bbox3`
in `track.c`.

## `GetElevation`

**The last polygon comes first.** When the coordinate has one and (x, y)
is strictly inside it, its plane at (x, y) is the answer at once, with
its terrain and normal. The height of `pt` does not matter, and neither
does the interest box. So a probe under a bridge that the call before
found the car on gets the bridge. A hit strictly inside, on a polygon not
flagged `INFINITELY_HIGH`, becomes the last polygon. A miss keeps the one
there was, and `SetInterestBBox`'s rebuild and `ClearInterestBBox` forget
it. The demo had no last polygon.

The inside test takes the largest of -1 and each edge's cross, and stops at
the first that is positive. Below 0 is strictly inside, and 0 is on an
edge. The largest is `max.s`, which keeps what it had when the cross is not
a number, so a point that is not a number is strictly inside anything.

Otherwise the point must be in the interest box, which is rebuilt 8 round
it if not. The ground under `pt` is then found in two passes over the
floors:

- the first looks for a surface below `pt.z + 1`;
- the second, only if the first found nothing, looks at any height.

A polygon counts when (x, y) is inside its box and not outside any edge.
Its plane at (x, y) must also be above everything the pass has accepted so
far. A hit strictly inside, on a polygon not flagged `INFINITELY_HIGH`,
ends the pass at once. A hit on an edge, or on a flagged polygon, is
remembered and raises the floor for the rest of the pass. With no surface
at all, the result is `pt.z`, the terrain 1, the normal (0, 0, -1) with its
fourth lane unwritten, and `found` 0.

A hit at table index 5 or later **moves to the front**, so that a car
standing on one polygon finds it first next frame. `HasTopology` probes
from z = 99999.1015625, where the first pass accepts any surface. Probing
from 0 instead would change which polygon is hit, and so what moves and
what becomes the last polygon.

The demo's call timed itself, into `TopologyTiming[10]`. Retail's does not.

`GetElevation` divides by the normal's z, and the constructor divides by the
normal's length. Neither division is guarded. The EE returns `FLT_MAX` for a
zero divisor where ARM returns infinity, so the port would need `ee_div`
here if a track had a collinear polygon or a floor standing on its edge.
Only floors are searched, so only a floor becomes the last polygon.
TRACKB12 has neither, and the checker counts all 15098 to show it.

## Segments and `ConstrainToTopology`

`TrackPolygon::SegmentIntersects` tests that the two ends lie strictly on
opposite sides of the plane, interpolates the crossing (all four lanes), and
checks that the crossing is in the polygon's shaft. So a move that ends
exactly on a plane crosses nothing. `TestSegmentToPoly` puts a box reject in
front of that test and a nearest-so-far behind it. It returns 1, and lowers
`*best`, only for a crossing **strictly** nearer than `*best`. Unless the
test is two-sided, it also requires the move to go against the normal, which
means starting on the side the polygon faces.

`TopologyCoordinate::SegmentIntersects` stops at the first crossing.
`ConstrainToTopology` walks the whole table and keeps the nearest. The walk
starts from a "nothing yet" best of 999999. The call returns 0, with `to`
untouched, unless the best crossing is nearer than the move is long. So a
move that crosses nothing returns 0, unless it is longer than 999999, in
which case it goes on to read the flags of a NULL polygon. The image does
that, and so does the port. Nothing moves that far. The two types:

- **`BY_ROTATION`** (0): against a wall, cut the move to end `dist` short
  of the crossing, and lift its end by `lift` times the fraction of the move
  that was cut. Against a floor, put the end `dist` above the plane at its
  (x, y); against a ceiling, `dist` below.
- **`BY_SCALE`** (1): cut the move to end `dist` short of the crossing, and
  keep its direction.

Any other type returns 1 and moves nothing. The two paths that rebuild `to`
from `from` do it in four lanes, so `to`'s pad comes back as
`from.pad + (to.pad - from.pad)`, rounded. The port does the same sum.

## Markers

A 24-byte `TrackPositionMarker` is a list node, a name hash, a parameter
and a 2D position. The loader links every record into
`TrackPositionMarkerList` in chunk order. The count and the i-th lookups
walk the list for a hash, and the named forms hash first. TRACKB12's twenty
markers, named by hashing the ELF's strings:

| hash | name | count |
|------|------|------:|
| `0x8e55c895` | `ForwardStartingPosition` | 8 |
| `0x8f90f7bf` | `BackwardStartingPosition` | 8 |
| `0x6a56b90a` | `ForwardStartLine` | 1 |
| `0xeec70374` | `BackwardStartLine` | 1 |
| `0xe5fae1cf` | `SplitTimeBoundary1` | 1 |
| `0xe5fae1d0` | `SplitTimeBoundary2` | 1 |

## Track info

`TrackInfo` is retail's 164 bytes, with no pointers. The demo's is 160.
Retail's `GetTrackInfo` (0x00153420) and `LoaderTrackGeometry`
(0x00153608) step by 164, and the port reads retail's discs. It holds:
- the name and location;
- `IsValid`, `TrackNumber`, `SameAsTrackNumber` and `Point2Point`;
- the time of day, the language IDs, the length, and the cop and super-cop
  names;
- the map calibration, the elevation range, the difficulty;
- retail's `SignpostGracePeriod` at 128, which the demo does not have;
- the sound region, at 132 (the demo's 128).

`SignpostGracePeriod`'s one reader is retail's
`AICarController::SignPostDecision` (0x00191efc). At -1 it keeps the demo's
test, `Race::GracePeriodIsActive`. Anything else is a race time the AI must
be past before it takes a `0x400` signpost. Every retail track has -1 but
T23, T26, T42 and T45, which have 0.

Retail GLOBALB's `0x34201` has 66 entries, and 30 are named: 11-16, 21-26,
31-36, 41-46 and 61-66, the five locations' three tracks and their three
variants. The variants point `SameAsTrackNumber` at their base track (14 to
11, 34 to 31, and so on). TRACKB12's `0x34200` is "National Forest T12",
number 12. The demo's had 63 entries, 21 of them named.

`GetTrackInfo(i)` counts from 1 and returns NULL out of range or for an
entry with no name. **On load, the loader clears entry 54**, whatever it
holds, so the game can never offer it. On this disc it is already empty.

## Road noise

`GetRoadNoiseGridValue(x, y)` hashes a grid point into
`RoadNoiseTable[16]`, using `x*y*11 + (x+1)*(y+1)*13` in wrapping
arithmetic. The values lie in [-0.5, 0.5], and one of them is 0.
`GetRoadNoise` scales the point by the terrain's
`RoadNoiseGridSpacingInverse` and floors it. The floor is spelled as
`cvt.w.s` plus a correction when the truncation went the wrong way. The
four corners are weighted in the listing's order and summed left to right,
and the result is scaled by `RoadNoiseScale`. Most terrains space the grid
at 1. SIDEWALK uses 1.1 and COBBLESTONE 3. NONE, ROAD and everything from
ROAD_AUTUMN on have a scale of 0. This is the demo's. Retail's steps
through its 144-byte `TerrainTypeInfo`.

## TerrainType

`TerrainTypeInfoTable` is data. Each of the demo's 140-byte records holds:
- the name and its hash;
- the type, two booleans and a skid texture;
- the road-noise grid and scale;
- three friction multipliers, a collision priority, a force, a debug colour;
- seven emitter groups, each with a pair of speed or force bounds.

The ELF holds 0 for every `NameHash`, and the static initialiser fills them
in with `bStringHash`. `MatchTerrainType(hash)` therefore finds nothing
before boot has run it. `MatchTerrainType(name)` compares ignoring case with
the engine's `bStrICmp`, which folds only a-z, and returns NONE for NULL or
no match. The port keeps its own static copy of that compare. On a 64-bit
host the nine pointers widen and take two alignment pads, and
`terraintype.h` counts the slack. Retail's records are 144 bytes, and
their retail pass is still to come.

## What is not ported

- **`_GLOBAL_$D$TrackPositionMarkerList`** (`0x001538b0`). It runs at exit,
  which the handheld never reaches, and it would `bFree` every marker, all
  of which live in chunk memory.
- **The dispatch into these loaders.** The port has no `LoaderTable` yet,
  so nothing calls `track_loader_geometry` outside the checker. The call to
  `InitTree` in `EndGameFlowLoadingTrackSpecific` is also unported.
- **Most of the callers.** Car's `FindFlatOnTrackPosition`,
  `PutFlatOnTrack`, `AverageAir` and `BeginMovement` are ported, and so is
  the `SetInterestBBox(bVector3)` wrapper. The rest of Car's calls are not.
  `TrackPolygonCollisionBody`, which is what `pCollisionBody` points at,
  is ported: see [CollisionBody](collision-body.md).

## Checking it

    python tools/track_check.py
    python tools/track_check.py --mutate
    python tools/gen_terrain_table.py --check

The harness is `tools/src/track_test.c`. The model is the image: every
`Track.obj` function except the exit-time teardown runs as shipped, with
bWare's slot pool, `bVector` and `bStringHash` under it. Every float
crosses as its bits.

There are two images. Nearly everything runs on the retail image
(`tools/retail_model.py`), over retail data. Road noise and the two
`MatchTerrainType`s read the demo's `TerrainTypeInfo`, so they run on the
demo image until the terrain table's retail pass. The same harness
answers both scripts. On the retail image the model also runs bmatrix's
static initialiser (`0x0025afa8`), which puts (0, 0, 0, 1) at
`0x00320a60`. Retail's `bMulMatrix(bVector3)` adds the vector to it to
get the w of 1 that applies the translation row, so without it
`AverageAir` samples the ground round the origin. The scenarios are:

- **the pure functions**, on retail: `GetSquareCorner` and the noise grid;
- **the track info tables** and their loader, including entry 54's clear,
  with retail GLOBALB's and TRACKB12's own info chunks;
- **the markers**;
- **a synthetic world**, run through every TopologyTree, TrackPolygon and
  TopologyCoordinate entry point. It has floors, one of them terrain 200,
  quads, triangles with a fourth vertex of their own, a bridge over a
  floor, walls, ceilings, a wall that is also a ceiling, and
  `INFINITELY_HIGH` and `Z_TIMES_FOUR` polygons. It also has a square
  past 160 polygons, a floor in each of the row and the column only a box
  ending on a square's edge reaches, and a lone far square with a flat
  floor under its sloped one. Builds go out to the bounds either side.
  The last polygon is set by hits and forgotten by clears and rebuilds.
  It is also poked into a coordinate with an empty table, for each
  standalone polygon in turn. The far square's two floors go into a table
  of their own, in both orders, for the first pass's ceiling;
- **a malformed tree** for `GetSquare`'s nearest-with-nothing path;
- **a car set on the ground.** `FindFlatOnTrackPosition` and
  `PutFlatOnTrack` run over a world of slopes, a gap on each axis, a
  cliff and ground with nothing under it. The `bVector3`
  `SetInterestBBox` runs here too, and so do `AverageAir` and
  `BeginMovement`;
- **retail TRACKB12 itself.** The run is driven along its squares until
  the pool has flushed several times, then filled on purpose to hit the
  101-at-a-time cap. Last, ninety cars are set down 1.5 above the
  centroids of random floor polygons;
- **on the demo image,** the bilinear noise for every terrain, under
  retail TRACKB12's route as well, and both `MatchTerrainType`s.

After the run, the checker requires that no division in `Track.obj` took
the EE's divide-by-zero path.

The mutation pass takes about ten minutes. Six mutants are argued equivalent
in `EQUIVALENT`. The two `air-` ones are Car's and are in `car.md`. The
other four are these:

- **`flush-resume`.** After a delete, the flush resumes from the head
  instead of from the node before. Every node up to that one was already
  walked with a non-zero count, and nothing in the loop changes a count, so
  the walk comes back to the same node with the same tally.
- **`icmp-diff`.** The compare returns `ca != cb` instead of `ca - cb`. Its
  only caller tests the result against 0, and on sign-extended chars the
  two are 0 together.
- **`flat-terrain-null`.** `FindFlatOnTrackPosition` passes NULL for the
  terrain instead of a local. Nothing reads the local, and
  `GetElevation`'s only use of the pointer is the store.
- **`inside-early-out`.** The inside test goes on past the first edge
  when it is already outside it. `track_max` never lowers `m` and never
  makes it a NaN, so the check after the next edge returns a value that
  is positive too. Every caller tests only the sign.

Several details of this object are visible only at the edge of their input
range, and the scenarios probe each at the input where it shows:
- a coordinate whose collision-body word is set before the constructor
  runs;
- a best distance exactly equal to a crossing's;
- a negative clearance, the one input where Constrain's box margin
  matters;
- a clearance past 999999;
- a noise coordinate past 2^24, where an integer minus one rounds;
- `HasTopology` over a floor at height 0 beneath one at 100;
- a box that reaches -32768 or 32767 exactly, and one a step inside;
- a look-ahead either side of 28.8, one exactly 28.8 (the float just
  under 192 from 0, with no radius), and one that no try fits;
- a surface between 0.5 and 1 above the probe, listed first;
- a point that is not a number, which is inside the last polygon;
- a terrain past 127.
