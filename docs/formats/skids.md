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

The drawing (78c) is called from `trackview.c`'s view; see "The drawing"
below.

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

## The drawing

Retail's `eDisplayFrame` calls `RenderClans(view->WorldScreenClipMatrix,
view)` (`0x001ab810`) for each view, after `StuffSun` and before
`RenderHudIntercepts`. The port's `trackview.c` calls `render_clans` from
the same place in the player's view. The rear-view mirror's view calls it
after its scenery, since the port draws no sun there. The PS2 draws the
mirror after the player's view and the port draws it before, so the sets
the mirror sees reach the head of `SkidSetList` first.

**RenderClans** walks `ClanList`, keeping each clan's next before it
draws. It skips a clan when `eView::GetPixelSize(&BBoxMin, &BBoxMax)`
(`0x001076f8`) is under 11, or when `IsBoundingBoxVisible(&BBoxMin,
&BBoxMax, clip)` is 0. That function is at `0x0010ce80`, and it is
ClassifyAABB not 0. A clan drawn more than 300 ticks after its stamp
(`(int)(WorldTime - LastUpdateTime) > 300`) is stamped again and moved
to the list's head. Then it calls RenderSkids on the clan.

**RenderSkids(clan, clip, view)** (`0x001ab248`) draws nothing in a view
whose byte 6 is set. The byte is read with `lb`, so any nonzero value
counts. `NisManager::EnableOverrideRendering` sets it for the view a NIS
takes over; the port's eView calls it `OverrideRendering`. The NIS player
isn't ported, so the byte stays 0. For each set on the clan's list:

1. **Visible**: `IsBoundingBoxVisible` of the set's box. With a car, the
   result is ANDed with bit `ID & 31` (an `srlv`) of the car's
   `VisibleViewBits`.
2. **Size**: `d` is the distance from the set's Centre to the camera's
   `CurrentKey.Position`, `sqrt((dx*dx + dy*dy) + dz*dz)`. Then
   `eView::GetPixelSize(1.0, d)` (`0x001075b8`), an int, becomes the float
   `px`. The set is skipped unless `4 < px`.
3. **Fade**: 0 past 10 pixels. Otherwise
   `(u8)(int)(256 - (px - 4) * 42.666668)`, from gp-29148, `0x422aaaab`.
   For 5 to 10 pixels the fade is 213, 170, 128, 85, 42 and 0.
4. `SkidSet::Render(set, fade)` draws the set, which then moves to
   `SkidSetList`'s head.

**SkidSet::Render(set, fade)** (`0x001aacc0`) draws nothing when the set's
terrain has no skid texture. It builds one ePoly on the stack with
`__5ePoly`. Then, for each pair of segments i and i + 1:

- V0 and V3 are segment i's two ends, from GetEndPoints (`pos + delta`
  and `pos - delta`), and V1 and V2 are segment i + 1's. Each corner is
  0.05 higher (gp-29156, `0x3d4ccccd`).
- V0 and V3 take segment i's alpha, and V1 and V2 take segment i + 1's.
  The alpha is `(intensity < fade ? 0 : intensity - fade) >> 1`, so a
  full mark's 255 is 127, close to the GS's 1.0.
- The colours stay the constructor's 0x80 grey.
- `ePoly::Render3D(texture, eMathIdentityMatrix, 0)` draws the quad: a
  strip of V0, V1, V3, V2 in world space, on the texture's list.

The four skid textures are in INGAMEB. They are semitransparent with
AlphaBits 0x44, `(Cs - Cd) * As + Cd`: plain alpha blending, which
darkens the road by the mark's alpha.

**On the 3DS**, each quad reaches `trackview.c`'s `render_epoly_3d` as a
strip of four on the texture's list. With up to 128 sets of 7 quads,
that would be hundreds of draws. Instead, `strip_end` joins a strip onto
the one before it when all of these hold:

- the strip has the same texture and matrix as the one before it;
- the one before it is the last thing on that list;
- the texture is not alpha-sorted.

Degenerate triangles fill the joins, and they keep each strip's winding.
Each run of one texture's quads is then one draw. The view's strip store
now holds 4096 vertices (it was 2048), and georender's strip ring holds
8192 a frame (it was 4096). The race log's "strips" line counts the
joins.

## The check

`tools/skids_check.py` runs retail's functions in mipsemu
(`retail_model.RetailEmu`, IEEE rounding and the EE's division by zero)
and the port's in the host harness. Both sides stub the slot pools (lowest
free slot first, `0xcd` or cleared by the pool's flags), bPNode's nodes
and `GetTextureInfo`, and for MaybeMakeSkids `GetElevation`, which
answers the two heights the op gives in turn. For the drawing they also
stub these:

- `IsBoundingBoxVisible`, which answers 1, 0, or a value from a hash of
  the box.
- The two `GetPixelSize`s: the distance one answers the view's H over
  the distance, truncated; the box one answers a set number or a value
  from a hash.
- `ePoly::Render3D`, which prints the texture, the matrix, the four
  corners, their alphas and a hash of the poly's other bytes.
- The ePoly destructor, which the port doesn't call.

Each stub prints what it is given. `bStringHash`, the bounding box
functions, the list destructors, `bRotateVector`, `bNormalize` and the
ePoly constructor run as shipped. The harness has its own
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
- **draw** (78c): on the sets so far, each set at fades either side of
  the intensities; views whose focal lengths put the sets at every pixel
  size; the views' IDs past 31 and below 0, against cars only some views
  see; a NIS's view, with the byte 1, 0x80 and 0xff; the clans' pixel
  test either side of 11 and boxes out of view; and the clans drawn 300
  and 301 ticks after their stamps.
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
  height under each edge. Then one view draws it all.
- **random**: 1500 ops of four cars driving with eight makers, odd
  steps, turns, terrains, views and the occasional flush and delete.
  Every 50 ops a view near one of the cars draws, with a random focal
  length, ID and tests.

On retail's image: 9079 ops, 79162 lines, 0 differ. 761 of the ops are
MaybeMakeSkids calls, and 593 of those lay a skid. The drawing runs
RenderClans 104 times, RenderSkids alone 15 times and SkidSet::Render
alone 168 times. Of the 5036 sets measured, 866 are over 4 pixels, and
1708 quads are drawn. Before 78b the same run without the wheels was
5839 ops, 2653 skids, 1329 sets and 74 clans made. Every instruction of
the 78a functions runs but the destructors' paths with bit 0 of the
flags clear, which no caller takes.

The mutation pass (`--mutate`) makes 208 changes to `skids.c`: 47 in
MaybeMakeSkids and 39 in the drawing. 204 are caught, all 86 of those
among them, and 4 are equivalent:

- `ct-centre`: the constructor ends in AddSegment, which sets the centre
  from the box whatever it was;
- `as-normal-1`: LastNormal is read only with two segments or more, and
  the second segment's way is written over the first's;
- `ms-reread`: MakeSkid's new-set path is reached only with the maker
  still holding the set, since one that finished itself on a turn
  answered 0 and returned;
- `is-texnull`: the nine terrains without a skid texture are never
  anything but NULL.
