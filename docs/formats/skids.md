# skids -- the skid marks' sets and clans

Retail's `Skids.obj`, SkidSegment .. the clans (0x001aa788 .. 0x001abaa0),
TASKS 78. The demo has the same objects (0x0019f..) without the parts
marked *retail's* below.

Ported to `3DS Files/source/skids.{c,h}`. Cross-checked by
`tools/skids_check.py` against `tools/src/skids_test.c`.

TASKS 78 comes in three slices:

- **78a**: the sets, the clans, the pools and lists, and the world's
  calls into them.
- **78b**: `Wheel::MaybeMakeSkids`, which decides when a wheel slides and
  gives its `SkidMaker` the point (below, "MaybeMakeSkids").
- **78c**: the drawing, `SkidSet::Render`, `RenderSkids` and
  `RenderClans`.

## The records

`SkidSegment`, 16 bytes, is one point of a trail:

| Offset | Field | |
|---|---|---|
| 0 | Position | 3 floats, the point on the ground |
| 12 | DeltaPosition | 3 int8s, the half-width across the trail, times 64 |
| 15 | Intensity | uint8, 0..255 |

`SetPoints` stores each lane of the half-width times 64 through `cvt.w.s`
(a truncation on the EE, `ee_trunc_w` in the port) and keeps the low byte.
A half-width of 2 m or more wraps. `GetPoints` and `GetEndPoints` divide by
64 again; neither writes a pad.

`SkidSet` is retail's 272 bytes, the demo's 256 and three fields more:

| Offset | Field | |
|---|---|---|
| 0 | Node | on SkidSetList |
| 16 | LastNormal | the last pair's unit way |
| 32 | LastSegmentLength | |
| 36 | pCar | *retail's*: the car the trail is under |
| 40 | bVisibleToBothPlayers | *retail's*: see below |
| 44 | pClan | |
| 48 | pClanNode | its bPNode on the clan's list |
| 52 | pSkidMaker | NULL once the set is finished |
| 56 | TheTerrainType | |
| 64 | Position | the first point |
| 80 | BBoxMax | |
| 96 | BBoxMin | |
| 112 | SkidSegments[8] | |
| 240 | NumSkidSegments | |
| 256 | Centre | *retail's*: the box's middle, which RenderSkids measures to |

The names of retail's three are the port's: the stripped ELF has none.
`bVisibleToBothPlayers` is bits 1 and 2 of the car's `VisibleViewBits`
(players 1 and 2, `eview.h`), both set, when the set is made. A NULL car is
the port's addition: retail reads the car whatever it is, and no caller
passes none.

`Clan`, 80 bytes: a node on ClanList, a `bPList<SkidSet>` of its sets, the
hash, `LastUpdateTime` (a WorldTime), and the first set's first point and
the box round all its sets.

## Laying a trail

`SkidMaker::MakeSkid(car, pos, delta, terrain, intensity)`:

1. *Retail's*: nothing at all when the point is more than 4 m from the
   car's `GeometryPosition` (`Car+80`). Exactly 4 m is laid.
2. A maker with no set gets a new one at the point.
3. Otherwise the point goes on the maker's set if the car's both-views bit
   and the terrain are the set's and `AddSegment` takes it.
4. If not, the set is finished, and a new one starts from its last point
   with its last half-width and its last intensity (the byte back over
   255), and takes this point. The trail goes on without a gap.

`SkidSet::AddSegment(pos, delta, intensity)` returns 1 when the set is
full and nothing was added, else 0. With a segment already there it
measures the way from the last point: `step` is its length and the way is
scaled by `vrsqrt`'s 1/length, which is FLT_MAX for a step of nothing, so
that way is zero. Then, with two segments or more:

- `turn = 1 - dot(way, LastNormal)`. Over **0.2** (about 37 degrees) the
  set is finished and the point is dropped: AddSegment answers 0, so
  MakeSkid lays nothing this time and the next point starts a fresh set.
- The point *moves the last one* instead of adding one when the last
  pair's length plus this step is under **0.25 m**, or the turn is under
  **0.002** (about 3.6 degrees) -- unless the two together are over
  **3 m**. A merge adds the step to `LastSegmentLength`.

Otherwise a segment is added (1 back when there are already 8), with
`LastNormal` the way from the second segment on and `LastSegmentLength`
the step. Either way the point's half-width and intensity (times 255,
truncated) are set, the set's box grows by a cube of half-side `step`
about the point, the clan's box grows by the set's, and the centre is the
box's middle.

A step of nothing on a set of one adds a second segment at the same place
with a zero `LastNormal`; the next point's turn is then 1 and ends the
set. The script has both.

`MakeNoSkid` finishes the maker's set, if it has one. Finishing is
`FinishedAddingSkids`: the maker and the set let go of each other, and the
set stays where it is to be drawn.

## The pools and the lists

`InitSkids` makes `SkidSetSlotPool`, 128 sets in memory pool 16, the first
time, and clears its overflow flag, so the pool never grows. A new set
when the pool is full frees the set at `SkidSetList`'s tail first.
`CreateNewSkidSet` puts each new set on the list's head; `RenderSkids`
(78c) moves each set it draws there, so the tail is the set least
recently seen. A set its maker still holds is finished by its destructor
(`MakeNoSkid`), and taken off its clan's list.

The clans cut the ground into 64 m squares. `GetClan(pos)` hashes the
point as `((y >> 22) << 16) + ((x >> 22) & 0xffff)` with
`x = (int)(pos.x * 65536)` and the same for y, both through `cvt.w.s`, so
a coordinate past 32768 m saturates into the last square. A clan of that
hash moves to `ClanList`'s head and is stamped with WorldTime. Otherwise a
new one goes on the head from `ClanSlotPool` (40, memory pool 16), with
the slot cleared; when the pool is full the clan at the tail goes first,
with every set on it. The new clan's stamp is the cleared slot's 0.

`InitSkids` also looks up each terrain's `SkidTextureName` through
`GetTextureInfo(bStringHash(name), 1, 0)` into `SkidTextureInfo[33]`:
SKID_ROAD, SKID_DIRT, SKID_GRASS and SKID_SAND for 24 terrains, none for
9. It clears the two debug switches the demo calls `PlotSkidsInCaffeine`
and `PlotSkidPointsInCaffeine`, which nothing reads.

`CloseSkids` deletes the set pool and forgets the textures; `CloseClans`
flushes every clan and deletes theirs. The World's destructor closes the
clans first, which deletes every set, and then the skids.

## The world's calls

The seams were there before this slice, empty; `main.c` fills them:

| Seam | Caller | Function |
|---|---|---|
| `gInitClansFn`, `gInitSkidsFn` | World's constructor (`worldinit.c`) | `init_clans`, `init_skids` |
| `gCloseClansFn`, `gCloseSkidsFn` | World's destructor | `close_clans`, `close_skids` |
| `gFlushClansFn` | `World::DoSnapshot` (`worldsnap.c`) | `flush_clans` |
| `gSkidSetFinishedAddingFn` | `~Wheel`'s SkidMaker (`physcomp.c`) | `skidset_finished_adding_seam` |
| `gWheelMaybeMakeSkidsFn` (78b) | `wheel_maybe_make_skids` (`wheel.c`), from each mover | `skids_maybe_make_skids` |

Nothing is drawn until 78c.

## MaybeMakeSkids

Retail's `Wheel::MaybeMakeSkids` is at `0x001a5520` (the demo's,
`0x0019b2d0`, took the time step alone). Its callers are PhysicsCar::Move
(`0x00138c84`), BeltMover::Move (`0x0020533c`) and MellowMover's
UpdateCar (`0x00219cb4`). Each passes the wheel in `a0`, the mover's car
in `a1` (`lw a1,84(s3)`, `lw a1,8(s2)` and `lw a1,44(s1)`, the same car
whose ShouldVisualEffectsBeGenerated gated the loop) and the step in
`f12`, which the function never reads. It is Wheel.obj's, but the port
writes it in `skids.c`, beside the makers it feeds, as
`skids_maybe_make_skids(Wheel *, Car *, float)`, and wheel.c reaches it
through the `gWheelMaybeMakeSkidsFn` seam. This keeps the skid pools out
of every checker that links wheel.c.

The wheel's fields are at retail's offsets: WI 12, CS 24, WorldMatrix
112 (the place is its row 3, at 160), Velocity 240, Terrain 336,
Slipping 340, TouchingGround 341, ZForce 344, TractionUsage 360, and the
SkidMaker at 384. WheelInfo's Width is at 16 and WheelNumber at 20. The
car's BlownTireBits is at 2124 in retail's Car (the port's field).

1. **Hard**: `8 < ZForce * TractionUsage`.
2. **Blown**: the car's BlownTireBits read with `lb`, so it is a signed
   byte, shifted right by WheelNumber (`srav`), bit 0.
3. A skid needs `(Slipping || hard) && TouchingGround && !blown` and the
   speed in the plane, `sqrt(vx*vx + vy*vy)`, over 1. Otherwise
   **MakeNoSkid** on the wheel's maker, and return.
4. **Across** is `(-vy, vx, 0)`, made a unit vector on VU0: the squared
   length `(x*x + y*y) + z*z`, then `vrsqrt` and a broadcast multiply
   (`ee_div(1, sqrtf)` in the port). Its fourth word is the stack's,
   multiplied along. Nothing reads it.
5. **Ahead** is `bRotateVector(WorldMatrix, (0, 1, 0))` (`0x001a5488`),
   and `d = |ahead . across|`: 0 when the wheel rolls straight, 1 when it
   goes broadside.
6. **The half-width** is `Width * SkidWidthMultiplier[Terrain]`, times
   `max(d, 0.5)` (a NaN `d` stays NaN), times 0.5. `bNormalize`
   (`0x00258958`, the port's `bNormalize3To`) scales Across to it. The
   terrain record is read straight from `TerrainTypeInfoTable` (0x00318c00,
   144 bytes each), not through Wheel's table pointer.
7. **The edges**, A = place + Across and B = place - Across, as whole
   quads. Each height comes from `GetElevation(CS->pTopologyCoordinate,
   edge, NULL, NULL, NULL)`, which is `gTopologyGetElevationFn` in the
   port. With no seam the height is 0.
8. **The point** is `(place.x, place.y, (hA + hB) * 0.5)`. Its fourth
   word is the stack's. Across.z becomes `hA * 0.5 - hB * 0.5`, and
   Across is scaled to the half-width again.
9. **The intensity** is `d`, times 1/3 (gp-29264, `0x3eaaaaab`) when the
   wheel is not Slipping, so only pressing. It is 0 on a puddle (terrain
   4). On any other terrain it is raised to at least 0.3 (gp-29260,
   `0x3e99999a`).
10. **MakeSkid** on the wheel's maker with the car, the point, Across as
    the half-width, the wheel's Terrain and the intensity.

MakeSkid then drops the point when it is over 4 m from the car's
GeometryPosition, as above.

## The check

`tools/skids_check.py` runs retail's functions in mipsemu
(`retail_model.RetailEmu`, IEEE rounding and the EE's division by zero)
and the port's in the host harness. Both sides stub the slot pools (lowest
free slot first, `0xcd` or cleared by the pool's flags), bPNode's nodes
and `GetTextureInfo`, and for MaybeMakeSkids `GetElevation`, which
answers the two heights the op gives in turn. Each stub prints what it is
given. `bStringHash`, the bounding box functions, the list destructors,
`bRotateVector` and `bNormalize` run as shipped. The harness has its own
copy of wheel.c's `bRotateVector`, because it does not link wheel.c;
wheel_check holds wheel.c's copy to the image. The four wheels sit at
retail's offsets on the model side, with their WheelInfos and CarStates,
and the cars' blown tires at 2124. After
every op both sides hash the whole state -- each maker's set, the pools,
SkidSetList in order with every set and segment, ClanList in order with
every clan and its sets, the textures and the switches -- and print it
every 100 ops.

The script:

- **basics**: init twice, a straight trail in 0.1 m steps through merges,
  full sets and new sets from the last point, and steps of nothing on sets
  of one and of two.
- **curves**: circles of radius 2 to 40 m in steps of 0.3 to 1.2 m, some
  under the straight limit, some between, the tightest past the turn
  limit.
- **breaks**: a right angle, terrain changes, the car leaving and
  rejoining each player's view, points at and past 4 m from the car on
  each axis, no car, intensities and half-widths past a byte, and
  `DeleteThisSkid`.
- **clans**: the squares' edges on both sides of 0, saturation, 48
  squares against the 40 clans with makers still holding sets in the
  evicted ones, and a found clan's stamp.
- **set pool**: 150 short legs in one square against the 128 sets.
- **flush**: `FlushClans`, closing twice, reopening.
- **wheels** (78b): MaybeMakeSkids' gates one at a time, each on its
  edge: ZForce * TractionUsage at 8 and just past it, and both signs;
  off the ground; speeds of 1 and just over; this wheel's blown bit,
  another's, and the top bit under the signed shift. Then a wheel rolling
  straight while pressing, a drift to broadside and back on tilted
  ground, every terrain at 45 degrees, pitch and roll, edges far apart in
  height, no width, and four wheels on two cars.
- **wheel random**: 300 steps of two cars sliding about, each step both
  of a car's wheels, with odd grip, a few blown tires and the ground's
  height under each edge.
- **random**: 1500 ops of four cars driving with eight makers, odd
  steps, turns, terrains, views and the occasional flush and delete.

On retail's image: 8654 ops, 56726 lines, 0 differ. 761 of the ops are
MaybeMakeSkids calls, and 593 of those lay a skid. Before 78b the same
run without the wheels was 5839 ops, 2653 skids, 1329 sets and 74 clans
made. Every instruction of the 78a functions runs but GetEndPoints
(78c's) and the destructors' paths with bit 0 of the flags clear, which
no caller takes. The mutation pass (`--mutate`) makes 169 changes to
`skids.c`, 47 of them in MaybeMakeSkids: 165 caught (all 47 of those),
and 4 equivalent:

- `ct-centre`: the constructor ends in AddSegment, which sets the centre
  from the box whatever it was;
- `as-normal-1`: LastNormal is read only with two segments or more, and
  the second segment's way is written over the first's;
- `ms-reread`: MakeSkid's new-set path is reached only with the maker
  still holding the set, since one that finished itself on a turn
  answered 0 and returned;
- `is-texnull`: the nine terrains without a skid texture are never
  anything but NULL.
