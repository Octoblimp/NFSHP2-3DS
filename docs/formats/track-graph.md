# The track graph

Retail's `TrackGraph.obj` (0x0024dd58 .. 0x0024ef84): the racing routes as
a graph, which the cops search for a roadblock or radar-trap spot so far
ahead of or behind a car. This is step 12e. The demo has the class too, but
retail's edge is eight bytes longer and only retail is ported.

Step 12e also brings the two `coputil.obj` helpers the searches call:
GetForwardTrackDistance (0x00230de8) and IsTeleportLocationClear
(0x00230e18).

Ported to `3DS Files/source/trackgraph.{c,h}` and `coputil.{c,h}`.
Cross-checked by `tools/trackgraph_check.py` against
`tools/src/trackgraph_test.c`, with the retail image (SLES_507.31) running
in mipsemu as the oracle.

DoSnapshot (0x0024e318) is the replay's ([replay.md](replay.md), TASKS
72d), checked by `tools/racesnap_check.py`.

Not ported:

- DebugDump (0x0024e810). Its two loops per vertex only count down, because
  its prints are compiled out.

## The records

| Record | Size | Off | Field |
|--------|-----:|----:|-------|
| tTrackGraphRoadBlockInfo, tTrackGraphSpeedTrapInfo | 12 | 0 | `bNode` on the edge's list |
| | | 8 | nIndexIntoLoadedData: the spot's record in the cops' chunk |
| tTrackGraphVertex | 40 | 0 | `bNode`, never linked or even set |
| | | 8 | pSignpost: the point's sign |
| | | 12, 16 | nRouteNumber, nRoutePointNumber |
| | | 20 | fDistanceAroundTrack, from a TrackPathCoordinate at the point |
| | | 24 | ForwardEdgeIndecies[2], -1 for none |
| | | 32 | BackwardEdgeIndecies[2] |
| tTrackGraphEdge | 48 | 0, 4 | nFromVertex, nToVertex (-1 if the route ran out first) |
| | | 8 | nRouteNumber |
| | | 12, 16 | nFirstRoutePoint, nLastRoutePoint (the To vertex's point) |
| | | 20 | bIsCloaked |
| | | 24 | (retail) the cloaked argument, as bIsCloaked starts out |
| | | 28 | (retail) 1 unless a point on the edge is NoHelisheet |
| | | 32, 40 | the roadblock and radar-trap lists, `bTList`s |
| tTrackGraph | 23216 | 0, 4 | nNumVerticies, nNumEdges |
| | | 8 | bHasCloakedEdge |
| | | 12 | Vertex[100] |
| | | 4012 | Edge[400] |
| | | 23212 | vptr, 0x002bf3d8; slot 8 is the destructor |

The demo's edge is 40 bytes and its graph 20016. Neither retail word at 24
and 28 has a reader in this file; DoSnapshot saves bIsCloaked only where
the word at 24 is set.

Statics:

| gp | Address | What |
|---:|--------:|------|
| -14840 | 0x00331ef8 | TheTrackGraph |
| -14848 | | the roadblock infos' slot pool |
| -14844 | | the radar-trap infos' slot pool |

Each pool has 128 slots of 12 bytes and uses memory pool 16. The
constructor makes both pools, and the destructor deletes both and clears
the two pointers.

## Building it

InitTrackGraph takes a 23216-byte block from `bMalloc(int, int)` in pool 16
and constructs the graph there. World's constructor calls InitTrackGraph
after InitCops. CleanupTrackGraph calls the destructor through the table
with flags 3, then sets the pointer to NULL. World's destructor calls it
after CleanupCops. The port's seams are `gInitTrackGraphFn` and
`gCleanupTrackGraphFn`, which main.c binds.

The constructor:

1. Makes every edge's two lists empty, all 400 of them. It zeroes the
   counts and the flag, and makes the pools.
2. Adds the vertices. It walks routes 0 to 48 only, the racing routes, and
   skips the traffic routes (50 to 69). Each signposted point is a vertex,
   except one whose sign is Backwards and not a Stop. A Cloaked sign on a
   vertex sets bHasCloakedEdge. AddVertex numbers the point by its index in
   the route's table and takes its distance from a TrackPathCoordinate
   built at its position.
3. Adds the edges, one vertex at a time:
   - a Stop that is not Backwards: none;
   - AlwaysTake, or a Backwards Stop: one edge, down the sign's new route
     from the sign's new point;
   - any other sign (Faster, Slower, Equivalent, DontTake, or types 6 and
     7): two edges. The first runs down the vertex's own route from its
     point; the second down the sign's route from the sign's point, cloaked
     if the sign is Cloaked.
4. Sets each vertex's backward edges. Both start at -1. Each edge with a To
   vertex then goes into that vertex's first backward slot if it is free,
   else into the second, so a third edge overwrites the second.
5. Swaps the two backward edges where the second is uncloaked and on the
   same route as the vertex's first forward edge. FindRoadBlock and
   FindSpeedTrap walk back by the first backward edge, which so stays on
   the route.

**AddEdge** walks the route from the first point to the route's end:

- A NoHelisheet point (bit 14) clears the edge's word at 28.
- Each point's roadblock number (bits 8-13) and radar-trap number (bits
  22-27), where not 0x3f, adds an info from the matching pool at the list's
  tail.
- At a later signposted point, GetVertexNumber gives the vertex at that
  route and point. If there is one, it becomes the To vertex, the point
  becomes nLastRoutePoint, and the walk stops.

So both ends of the edge add their spots.

**GetVertexNumber** gives the first vertex that is at the route and point,
or whose sign sends to them. A sign whose own vertex was skipped, a
Backwards non-Stop, still ends edges this way: an edge stops at the point
when some other vertex's sign targets it.

### Dead ends

An edge whose route runs out before a vertex keeps nToVertex -1. Its
nLastRoutePoint is never written, so the 0xcd fill means FindEdge never
returns it. In the backward pass, retail indexes Vertex[-1] for such an
edge. That vertex's backward slots are the graph's nNumEdges and
bHasCloakedEdge, and nNumEdges is never -1, so the edge's number lands in
bHasCloakedEdge. The port does the same.

A sign naming a route that isn't loaded gives an edge with no points.
Retail reads the NULL route's NumPoints (address 16, zero in mipsemu); the
port returns early, which has the same result.

No retail track has either case. The 30 TRACKB bundles give 16 to 42
vertices each. Six have a Cloaked sign; none has a dead end or a sign to a
missing route.

## The searches

**FindEdgeByRouteAndPoint**: the first edge that is not cloaked, is on the
route, and whose first and last points both enclose the point.

**FindRoadBlock**(car, fMin, fMax, forward) and **FindSpeedTrap**:

1. Find the car's edge from its route and point. Car::GetRoute and
   GetRoutePoint run with 1, so an AI controller with no route finds one.
   No route, no point, or no edge returns NULL.
2. Take the car's distance around the track once, from Car+2036.
3. For each info on the edge's list, in order, take the spot from the
   cops' manager (GetRoadBlockFromLoadedDataIndex or
   GetSpeedTrapFromLoadedDataIndex), skipping NULL. Then compute d:
   - forward: GetForwardTrackDistance(spot, car), so the spot is ahead;
   - back: GetForwardTrackDistance(car, spot).

   The spot is taken if `d < fMax && fMin <= d`, so a NaN at either end
   rejects every spot. A roadblock must also pass
   IsTeleportLocationClear(&rb->v2Position).
4. After five edges, return NULL. Otherwise go to the next edge:
   - forward: the To vertex's first forward edge;
   - back: the From vertex's first backward edge.

   -1 returns NULL.

Walking forward from a dead-end edge, retail reads Vertex[-1]'s first
forward edge. That is the word before the graph's block: bMalloc's header.
The port stops instead. The checker makes that word -1 so that retail
stops too. No retail track has such an edge.

**GetForwardTrackDistance**(a, b): `a - b`, plus TheTrackPathManager's
TrackLength when that is below 0. So -0.0 stays -0.0.

**IsTeleportLocationClear**(p) returns 0 in either case below, else 1:

- World::GetDistanceToClosestPlayer, the two-dimensional form, is under
  250;
- one of pCurrentWorld's TotalNumCars cars is under 15 away in x and y.
  The distance is `sqrt.s` of the squares summed x, then y, and the count
  is read again on each pass.

A NaN distance passes both tests.

**UncloakAllEdges** clears each cloaked edge's flag and the Cloaked bit of
its From vertex's sign, in the loaded chunk itself. It then clears
bHasCloakedEdge, even when that held a dead end's number.

## The check

`tools/trackgraph_check.py` builds the graph of every retail track. It
also builds 9 graphs made by hand for the rare paths, and 300 random ones.
Each is checked on:

- the stubs' logs;
- a dump of every vertex, every edge, and both lists with their back
  links;
- the unused edges' lists;
- the signs' flags after uncloaking.

Between the dumps it looks up vertices and edges at and past every route's
ends. It runs about 15000 finds from cars all over each graph, both ways,
over ranges that include NaN and the infinities. On the hand-made loop it
also checks:

- d exactly at fMin and fMax;
- a wrapped distance;
- the fifth edge and the sixth;
- a roadblock refused for a player, then for a car.

It runs GetForwardTrackDistance and IsTeleportLocationClear at their
boundaries, and tears down every way: CleanupTrackGraph and the destructor
with flags 0, 1 and 2.

The run is 325904 ops and 246035 lines, with 0 differ. `--mutate`
catches all 102 of its mutants: 92 in trackgraph.c and 10 in
coputil.c, with none equivalent.
