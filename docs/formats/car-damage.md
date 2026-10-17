# cardamage -- dents, broken lights and windows

Every racer and cop car carries a CarDamage. It keeps how hard each side
of the car has been hit, as 32 zones round the car's outline, and the
level of fifteen breakable items: the mirrors, the plates, the lights,
the six windows and the radiator. A hit that raises an item's level
plays the glass and triggers the item's effect, and the car's render info
swaps in the item's broken texture. A window that breaks loses its
environment mapping. The vertices of the body follow the zones' damage:
they dent, darken, and show the scuffs.

Retail has it in BodyDamage.obj and CarDamage.obj, `0x001b4760` ..
`0x001b5c50`. The port has it in `cardamage.{c,h}`. eSolid's environment
mapping is in `esolid.c`, and eModel's is in `emodel.c`. The walk over a
model's vertices and eStripData's accessors are in `estripdata.c`.
`tools/cardamage_check.py` runs retail's code against the port, and
`tools/loadertable_check.py` runs the environment mapping.
`tools/geobake_check.py` checks the renderer's side of the vertices.

| function | retail |
|---|---|
| LoaderBodyDamage / UnloaderBodyDamage (slot 17) | `0x001b4760` / `0x001b47b0` |
| FindBodyDamageInfo | `0x001b47e8` |
| BodyDamageModel::Init / CallDamageVertexFunction | `0x001b4820` / `0x001b4b50` |
| DamageVertexFunction, and the static that calls it | `0x001b48d0`, `0x001b48b0` |
| BodyDamage::BodyDamage / ~BodyDamage | `0x001b4ba0` / `0x001b4c10` |
| SetALevelBodyDamageInfo / AddModel | `0x001b4cd8` / `0x001b4d10` |
| SetDamage / RepairAllDamage | `0x001b4d48` / `0x001b4dc0` |
| the zone of a point (new in retail) | `0x001b4e10` |
| GetDamageAmount | `0x001b4f10` |
| GetVisibleDamageAmount (point, zone), GetCompressedVisibleDamageAmount, GetVisibleTotalDamage | `0x001b5030` .. `0x001b50c8` |
| BodyDamage::ApplyDamage / SetEnvironmentMapping | `0x001b5108` / `0x001b5250` |
| CarDamage::CarDamage / ~CarDamage | `0x001b54b0` / `0x001b5538` |
| the item parts (new) | `0x001b5598` |
| CarDamage::AddDamage | `0x001b56b0` |
| the item levels (new) / the damage to one zone (new) | `0x001b57a0` / `0x001b58c8` |
| RethinkDamage / ApplyDamage | `0x001b5a78` / `0x001b5aa8` |
| the wreck (new) / RepairAll (new) | `0x001b5bc8` / `0x001b5c20` |
| eSolid::SetEnvironmentMapping / eModel's | `0x00104070` / `0x0010cae0` |
| CallDamageVertexFunctionForEveryVertex | `0x00104100` |
| eStripData's GetElementXYZ, GetElementRGBA, GetNumVerts, GetXYZ, SetXYZ | `0x0011bf98`, `0x0011c180`, `0x0011c248`, `0x0011c2b8`, `0x0011c338` |

"New" marks code the demo does not have. The demo found the items by
marker on every hit. Retail finds them once, when the car is built, and
keeps the zone each one is in.

## The records

**BodyDamageInfo** is chunk `0x00034030`, one per body and scuff model
in a car's `GEOMETRY.BIN` (`VIPERGTS_A`, `VIPERGTS_B`, ...). The chunk
is its 8-byte header, the 84-byte info, and `NumKeys` words. The info
stays in the chunk:

| off | field | |
|---|---|---|
| 0 | `Node` | on BodyDamageInfoList (gp-18832) |
| 8 | `Name[32]` | |
| 40 | `NameHash` | bStringHash of the name; FindBodyDamageInfo looks for it |
| 44 | `BBoxMin` | x, y: the box the zones are laid round |
| 52 | `BBoxMax` | |
| 60 | `Center` | |
| 68 | `NumVertices` | must be the model's own count |
| 72 | `NumKeys` | |
| 76 | `pKeys` | the loader points it at the words after the info |
| 80 | `pVertexIndices` | the loader clears it |

A key covers a run of vertices: bits 0-2 are the run's length less one,
3-7 the zone, 8-13 the colour step, and 14-31 the dent (z, y, x, six
signed bits each). The loader puts the info on the list's tail. The
unloader takes it off. Both answer 1 for a `0x34030` chunk and 0 for
anything else.

**BodyDamageModel** (28 bytes) is a model whose vertices follow the
damage: the body damage at 0, the eModel at 4, its info at 8 (NULL when
it has none or the counts differ), its vertex count at 12,
`DamagePolysOnly` at 16, and the walk's `RepeatCount` and `KeyNum` at 20
and 24.

**BodyDamage** (196 bytes):

| off | field | |
|---|---|---|
| 0 | `Node` | on BodyDamageList (gp-18824) |
| 8 | `CompressedDamageAmounts[32]` | each zone, 128 whole |
| 40 | `CompressedTotalDamage` | u16, their sum: 4096 is every zone whole |
| 42 | `CompressedAppliedDamageAmounts[32]` | what the vertices were last moved to |
| 74 | `CompressedTotalAppliedDamage` | |
| 76 | `NumBodyDamageModels` | |
| 80 | `BodyDamageModels[4]` | no bound check in retail's AddModel |
| 192 | `pALevelBodyDamageInfo` | the `<car>_A` info, whose box gives the zones |

**CarDamage** is 228 bytes. The demo's was 212; retail added `ItemZones`.

| off | field | |
|---|---|---|
| 0 | `pCar` | |
| 4 | `CarBaseNameHash` | the car type's BaseModelName, for the markers |
| 8 | `TheBodyDamage` | |
| 204 | `BreakableCarItemDamageAmounts` | each item's level, two bits at 2i |
| 208 | `AppliedBreakableCarItemDamageAmounts` | the levels the textures show |
| 212 | `ItemZones[15]` | each item's zone, or -1 |

## The zones

A point of the car's frame goes to a zone by its x and y over the A
level info's box:

```
u = (x - min.x) / (max.x - min.x)      iu = trunc(8u), clamped 0..7
v = (y - min.y) / (max.y - min.y)      iv = trunc(8v), clamped 0..7

v >= u, 1 - v >= u   near x   iv + 16    16..23
v >= u, 1 - v <  u   far y    iu + 24    24..31
v <  u, 1 - v >= u   near y   16 - iu     9..16
v <  u, 1 - v <  u   far x    8 - iv      1..8
```

The box's diagonals split it into four triangles, eight zones to a side.
Zone 16 can come from two sides, and no point gets zone 0. The divides
are the PS2's (`ee_div`), so a box with no width gives the largest float
and not a NaN. Without an info the zone is -1.

## A hit

`AddDamage(at, amount)` does nothing with damage off for the race
(`TheRaceParameters.DamageEnabled`), for an amount under 0.05, or where
there is no zone. Otherwise the zone takes the amount. The four zones on
either side take a half, a quarter, an eighth and a sixteenth of it,
wrapping round 32. Each of those nine calls carries the whole amount as
its impact. Then ApplyDamage.

The damage to one zone (`0x001b58c8`) clamps the zone's new damage to
0..1 and does nothing if that is no change. Otherwise it sets the zone
and works out the item levels again. If they have not changed, that is
all. If they have and the impact is under 0.2, the zone goes back to what
it was: a light hit cannot break anything. Otherwise, for each item
whose level changed, the glass plays if the new level is 1, and the
item's effect triggers with the scale for the new level (0, 0.1, 0.4 or
1). Then the levels are kept.

## The items

The table is at `0x00313b80`, 32 bytes an item. An item's level is the
highest of 1, 2 and 3 whose threshold its zone's visible damage has
reached, and 0 below the first. The 0 threshold is never read.

| item | marker | thresholds 1 / 2 / 3 | env mapped | effect |
|---|---|---|---|---|
| 0 | `05f63788` | 0.25 / 0.5 / 0.75 | | BREAK_SIDE_MIRROR_LEFT |
| 1 | `c52bf01b` | 0.25 / 0.5 / 0.75 | | BREAK_SIDE_MIRROR_RIGHT |
| 2 | `725758bf` | 0.25 / 0.5 / 0.75 | | BREAK_LICENSE_PLATE_FRONT |
| 3 | `494ed280` | 0.25 / 0.5 / 0.75 | | BREAK_LICENSE_PLATE_RIGHT |
| 4 | `a7e6ea53` | 0.25 / 0.35 / 0.5 | | BREAK_HEADLIGHT_LEFT |
| 5 | `a532fc46` | 0.25 / 0.35 / 0.5 | | BREAK_HEADLIGHT_RIGHT |
| 6 | `d947f346` | 0.25 / 0.45 / 0.65 | | BREAK_BRAKELIGHT_LEFT |
| 7 | `02b52399` | 0.25 / 0.45 / 0.65 | | BREAK_BRAKELIGHT_RIGHT |
| 8 | `7b220ddf` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDSHIELD |
| 9 | `1b0763a0` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDOW_REAR |
| 10 | `e7e4ef49` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDOW_LEFT_FRONT |
| 11 | `4cdebfca` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDOW_LEFT_REAR |
| 12 | `60f8b13c` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDOW_RIGHT_FRONT |
| 13 | `0ab88f5d` | 0.25 / 0.5 / 0.75 | yes | BREAK_WINDOW_RIGHT_REAR |
| 14 | `68100815` | 0.7 / 0.85 / 0.95 | | DAM_RADIATOR |

The car types `0x13`, `0x14` and `0x1f` have no windows to break
(`0x00313d60`): their levels lose items 8 to 12 (mask `0x03ff0000`).

The item parts (`0x001b5598`) find each item's marker in the car's model
by `eFindPositionMarker(marker, CarBaseNameHash, NULL)` and keep the
zone of its position, or -1. The car's init calls it once the render
info has set the A level info.

## ApplyDamage

**The body's** moves the vertices when the visible total damage (the
total over 4096, or 0 with damage off) has gone more than 0.02 from the
applied total, or has gone back to 0. It walks every model and then
copies the visible amounts into the applied ones. With damage off those
are all 0.

**The car's** calls the body's. If the levels are the applied ones, that
is all. Otherwise, for each item whose level changed, a window
(env mapped) gets its environment mapping back at level 0 and loses it
above, and the applied bits take the new level. Then
`UpdateCarReplacementTextures` gives the render info the broken lights'
and windows' textures.

**The environment mapping.** A car's body textures are named by the
windows' marker hashes: the Viper's A and B bodies have textures
`7b220ddf`, `1b0763a0`, `e7e4ef49` and `60f8b13c`.
`eSolid::SetEnvironmentMapping(hash, on)` sets strip flag `0x100` on
each strip whose texture has that name, or clears it. The texture is
the strip's first byte, read signed (`lb`). eModel's does it to its
solid if it has one, and BodyDamage's to every model's. The second and
later cars of a type draw copies of the solids (`eDuplicateSolid`), each
with its own strip table, so one car's broken window leaves the other
cars' alone.

## The vertices

**The walk** (`CallDamageVertexFunctionForEveryVertex`, `0x00104100`)
goes over the model's solid strip by strip, and over each strip's
vertices in order. It uses eStripData's accessors (`0x0011bf98` ..
`0x0011c398`), which find a vertex's x, y, z and RGBA where the VIF's
unpacks keep them in the strip's VU1 packet. So the walk changes the
packet the renderer draws from. For each vertex it reads the position
and calls the function with:
- the caller's pointer and the vertex's number over the whole solid;
- the position (a copy, written back after the call) and the colour in
  the packet;
- a NULL, and the strip's Flags & `0x800`.

A scuff strip (Flags `0x800`) with any vertex that shows loses `0x400`,
the flag RenderStrips skips a strip by. A scuff strip with none gets it.
A strip of no vertices still has its flags handled, and a model with no
solid is skipped. The vertex counter is reset once for each walk.

**DamageVertexFunction** (`0x001b48d0`, called through `0x001b48b0`).
The vertex's key is the info's KeyNum-th. RepeatCount counts the
vertices that have had it, up to the key's low three bits. The zone's
damage since the last walk (visible less applied) does two things:
- It moves the vertex by the key's dent: each of x, y and z by its six
  bits times 0.02 times the difference.
- It steps the colour. R, G and B each go down by trunc(8 step ×
  visible) / 8 less the same of the applied, which is a whole step of
  `0x421` off the halfword. The subtraction can carry into the next
  channel, and it wraps.

A repair takes both back, and with `DamagePolysOnly` neither happens. A
scuff's alpha is on above half the zone's damage (trunc(256 v) ≥ 129).
The vertex shows with any damage at all.

## The wreck, the repair and the destructor

The wreck (`0x001b5bc8`, what a munition's blast or a cop's wreck does)
gives every zone 1.0 with an impact of 9999, so everything breaks, and
then RethinkDamage: the levels worked out again and applied.
RepairAll (`0x001b5c20`, the cop manager's ResetAllDamage) sets every
zone and the total to 0, applies the body, and rethinks. The destructor
sets the levels to 0 and applies them, so the textures and the
environment mapping go back. Then it repairs the body, takes it off its
list, and frees the CarDamage with flags & 1.

## The marker over the car

You're The Cop shows the cops' damage on each suspect as a marker over
the car. RenderCars calls `Car::DamageAbove` (`0x00135280`) for every car
it drew, with the camera's eye and direction, unless the view's player is
in the jump cam. Only DamageAbove calls `Car::DamageCap` (`0x00135490`).

**DamageAbove** works out the car's `fAngleToCamera` (Car +2192) first,
whatever else happens. With `n` the unit way from the car to the eye, as
the VU adds it, the angle is `(direction · n + 1) × 0.5`. It is negated
when z of `direction × n` (`vopmula`/`vopmsub`) is at or above 0. A car
straight ahead of the camera is 0, one beside it ±0.5, one behind ±1.
Player::DrawTracker draws the cop HUD's tracker for cars within ±0.5
([hud-cop](hud-cop.md)). Until 51d the seam was NULL, so the angle stayed
0 and every tracker sat at the screen's middle.

The angle a car keeps is the last view's to draw it. eDisplayFrame runs
RenderCars for views 0 to 3 in turn (`0x00113668` to `0x001136f0`), each
render target the view has, and the mirror is view 3. So with the mirror
up, a car the mirror draws keeps the mirror's angle, and the trackers
show the cars within 50 that the mirror looks at, behind the player. A car
only the player's view draws keeps that view's. The port draws the mirror
first, so `rendercars.c` keeps the mirror's angles and puts them back
after the player's view ([car-render-info](car-render-info.md), "Where
the port differs").

Then it draws the marker only when all of these hold:
- neither player has a NIS playing;
- `TheRaceParameters.BeACop` is set;
- the race coordinator's state is 3, the race in progress (retail does
  not test the pointer);
- there is a cop manager;
- the car is an AI racer (driver type 2), or has a Player and is not a
  cop (UsageType 1).

The distance from the eye, times 0.005 (gp-31836) and held to 0 .. 1,
goes to DamageCap. So does whether `tCopManager::IsBeingPursued` finds a
pursuit for the car, and the cop manager's `fCarDamage[CarIndex]`
(+10420).

**DamageCap** draws an upside-down pyramid on `WHITE16X16_NOALPHA`
through `ePoly::Render3D`:
- **The size.** It is `s = 2 × distance + 0.05` (gp-31832), so a far car's
  marker is bigger. In an instant replay or after the race it is 0.1
  (gp-31828), though DamageAbove never calls it then.
- **The points.** They are ObjectPoints 0 .. 4: the point at the origin
  and the square's corners at (±3, 0, 3) and (0, ±3, 3), each times `s`
  in all four lanes.
- **The matrix.** It comes from the frame memory (64 bytes; none, and
  nothing is drawn). It is `DamageAboveMatrix × local`, where `local` is
  the body matrix's three rows with the position and 1 as the fourth.
  DamageAboveMatrix halves the points and lifts them 1, so the point is 1
  over the car's origin and the square 1.5 × `s` over that.
- **The poly.** Its UVs are (0,0), (0,1), (1,1), (1,0), and its alpha
  equation is the constructor's.

The colours are the GS's, red in the low byte, and 0x80 is 1.0, so
the white texture saturates:

| when | word | on screen |
|------|------|-----------|
| a side, no cop on the car | `0xff00aa00` | green |
| a side, pursued | `0xffcc0000` | blue |
| the damaged part, no cop | `0xff005599` | orange |
| the damaged part, pursued | `0xff995500` | light blue |

With no damage (`c.eq.s` with 0, so -0 too), each side is one poly: the
point, a corner, the next corner, and the point again. With damage, the
edges are the corners less the point, made unit by the first edge's
length `len`. Each side is then two polys:
- the damaged part, from the point to `len × damage` along its two edges;
- the rest, from there to the square, in the side's colour.

Damage over 1 reaches past the square, and damage below 0 reaches below
the point. Last comes the square on top, in the side's colour. Render3D
draws each poly as the strip V0, V1, V3, V2, so the first, degenerate
triangle of a whole side draws nothing. The port's strips are not
culled, so every side shows from both faces, as on the GS.

A frame of `n` suspects draws at most 9 × `n` strips of four in each
view, out of trackview's 256.

## In the port

`main.c` binds `carinit.h`'s, `collisionbody.h`'s, `cop.h`'s and
`copmgr.h`'s seams to `cardamage.c`: the constructor, the item parts and
the destructor, SetALevelBodyDamageInfo and AddModel, AddDamage, the
wreck and RepairAll. Every racer and cop now has a CarDamage, so hits
derate the engine (physicscar), smoke and steam (careffects) and break
the lights and windows (carrenderinfo).

**The renderer's environment mapping** (51b). Retail's RenderStrips
(`0x0010dd58`) reads each strip's Flags as it draws. The port bakes a
solid's strips into batches of one texture, flags and material
(`georender.c`), so the bake's flags would keep a broken window's map.
Each batch keeps its first strip (`GeoBatch.strip`), and trackview's
`strip_flags` reads that strip's Flags from the solid's entry table as
they are now (`geometry.h`'s `geo_strip_flags`). A car's solids are
opened over the engine's own table (`geo_open_in_place` on
`StripEntryTable`), the one `esolid_set_environment_mapping` writes.
Every strip of a batch has the batch's texture, and SetEnvironmentMapping
changes every strip of a texture, so one strip speaks for the batch.

**The renderer's vertices** (51c). The walk and DamageVertexFunction are
in `estripdata.c` and `cardamage.c`. The port draws a solid from one
indexed mesh baked out of its packet (`geobake.c`), so after a walk the
mesh has to be made to match again:
- **The bake.** A car's solid that a BodyDamageModel with an info walks
  (`bodydamage_walks_solid`) bakes editable (`georender_bake_editable`).
  The mesh keeps which of its vertices each strip vertex became, and each
  scuff strip's indices. A scuff strip hidden at the bake (all 711 are,
  on the disc) is baked as triangles of one vertex, which draw nothing.
- **The seam.** The walk ends with `gESolidVerticesChangedFn`. main.c
  binds it to `trackview_solid_changed` for the race's view and the
  frontend's, which marks each mesh baked from that solid dirty.
- **The refresh.** A dirty editable mesh is refreshed at its first draw
  of a frame (`georender_refresh`):
  - every strip vertex's position and colour is read back out of the
    packet;
  - each scuff strip's indices are put back, or emptied, by its Flags;
  - the batches' boxes are made again.
  C3D_FrameBegin has waited for the GPU by then, and the frame's sends
  and C3D_FrameEnd flush the linear heap. Any other dirty mesh is let go
  at the frame's start (`trackview_frame_begun`), and bakes again when it
  next draws.
- **The merged vertices.** The bake keeps one vertex for strip vertices
  that are the same byte for byte. On the disc's 115 solids with a
  BodyDamageInfo, the 107,961 strip vertices it merges have the same key
  and scuff flag as the vertex they merge with. The walk changes them
  alike, so one mesh vertex can stand for all of them.
- **The heap.** A car's body is baked at its first draw, in the race.
  By then the main heap's largest free block can be 64 KB, and a body's
  bake needs a few hundred KB of working buffers. Before Session 93's
  fix, CROWNVIC_A, its copy CROWNVIC_A2 and TS50_A failed to bake, so
  the player's cop car drew only its shadow and wheels. The working
  buffers and the edit now come from the linear heap (`scratch_alloc`),
  which has about 11 MB free in a race. The race's stats line counts
  the bakes that fail ("N bakes failed"); a failed solid never draws.

`cardamageabove.c` ports DamageAbove and DamageCap (51d), and `main.c`
binds `gCarDamageAboveFn` to it. Its one addition is a NULL test on the
race coordinator before the state is read. Retail would read the word at
address 0, which is not 3 either.

`Car::TriggerEffect` (`0x0011e2b8`, `gCarTriggerEffectFn`) is not
ported, so the effects are skipped (TASKS 60). The replay's DoSnapshots,
BodyDamage's (retail's 0x001b4c58) and CarDamage's (0x001b5638), are
ported since TASKS 72b, and `carsnap_check` runs them against retail.

## The check

`tools/cardamage_check.py` runs retail's code in RetailEmu: the loader,
the unloader and the find, BodyDamage and CarDamage whole, over
BodyDamageInfoList and BodyDamageList as the static constructor leaves
them, and the image's own item table, window-less types and effect
scales. What CarDamage calls out of the object is stubbed in the model
and stood in for in the harness (`tools/src/cardamage_test.c`), and both
print the call: eFindPositionMarker, PlayGlass, TriggerEffect,
UpdateCarReplacementTextures, eModel::SetEnvironmentMapping and the
delete. The walk and eStripData's accessors are retail's own on one side
and `estripdata.c` on the other. Each strip's packet is the same 1,024
seeded bytes on both, and both dump each vertex and each packet's bytes
through retail's GetXYZ and GetElementRGBA. The port's
`gESolidVerticesChangedFn` prints the solid in the harness. The model
prints it from the walk's epilogue (`0x00104260`), from where the walk
keeps it at 44(sp), which it stores before its test for no solid.

The script covers:
- the list over loads, unloads and finds;
- models whose counts match, do not, are 0, have no solid, or name no
  info;
- a 13 by 13 grid of zones and the box's diagonals, edges and corners,
  and a box with no width, 0 / 0 included;
- SetDamage out of range and at the byte's edges;
- ApplyDamage either side of 0.02, back at 0, and left small on the way
  down;
- items found and missing, and a hit on a car with no info;
- each zone stepped through every threshold in 128ths;
- the wreck, the repair and the destructor;
- 700 random hits, zones and repairs over five cars;
- the vertices:
  - strips of every count from none to 30, in and past the groups of
    four, scuff strips and a hidden one, under a body and a polys-only
    model;
  - keys with dents and without, colour steps up and down that wrap, and
    each repeat count;
  - zones at the alpha's 64 and 65 of 128 and full, with the damage on
    and off, the repair, and the seam off;
  - then random keys and strips under random damage.

The vertex dumps see 1,160 positions, 1,887 colours, 161 alphas alone and
69 strips' flags change. It runs 3,206 ops for 30,452 lines, 0 differ. Of
its 184 mutations, 181 are caught and 3 are equivalent:
- the unread 0 threshold;
- an item with no zone reading the byte before the zones, which is a
  pointer's top byte and 0 on both machines;
- FindItemParts' reset to -1, which only a marker that went away between
  two calls could show.

`tools/loadertable_check.py` runs eModel::SetEnvironmentMapping on the
retail image over the Viper's and the bus's duplicated solids. It prints
every strip's flags (`sf`) in each solid dump. The windows go off and
on, a texture the bus has none of, a hash that names nothing, a model
with no solid, and a solid of four strips of one texture are all
covered, and the original solids stay as they were. Of its 7 new
mutations, 6 are caught and 1 is equivalent (a texture number past 127).

`tools/geobake_check.py` builds `geobake.c` on the host with
`geometry.c`, `geocull.c` and `estripdata.c` (`tools/src/geobake_test.c`).
It bakes every solid of the 44 cars' `GEOMETRY.BIN`, 518 solids and
16,789 strips:
- With every scuff strip shown, the editable bake is the plain bake, byte
  for byte, and a refresh before any change changes nothing.
- Then, three times over, it moves and recolours each strip vertex in the
  packet by a hash of what it holds, so merged vertices change alike, and
  shows or hides each scuff strip at random. After the refresh the mesh
  must draw what an editable bake of the changed solid draws, at each
  index the same vertex, in the same batches, with the same boxes.
- The triangles it draws (none of whose corners share an index) must be
  the plain bake's, in order and vertex for vertex.

It changes 1,325,799 vertices over 2,072 refreshes, with 0 faults. Of its
23 mutations, 22 are caught. The last, georender_free not freeing the
edit, is a leak the harness cannot see.

`tools/cardamageabove_check.py` runs DamageAbove and DamageCap on the
retail image, with bStringHash, ePoly's constructor and eMulMatrix as
shipped, against `cardamageabove.c` in `tools/src/cardamageabove_test.c`.
IsNisPlaying, IsBeingPursued, GetTextureInfo and Render3D are stubs on
both sides and print what they are asked. Render3D's prints each vertex's
x, y and z, the colours, the u and v, and the matrix. After each call
both print the angle and the frame memory's position, failure and
amount. The script covers:
- each gate on its own: the players' NISes, BeACop, the ten states and
  more, no coordinator, no cop manager, and every driver type with and
  without a player and a cop's UsageType;
- the angle with the eye ahead, behind, to each side, above and below;
- the distance either side of 200 along each axis;
- every car index's damage, pursued or not;
- damage at 0, -0, the smallest floats, 1, past 1 and below 0;
- no texture, and the frame memory too short by one, exactly enough,
  and absent;
- random points and matrices with their pads;
- DamageCap alone in every state, for the replay's size;
- 500 random calls.

Every float is finite, since a NaN's bits differ between the host and
the model. It runs 1,045 scenarios for 8,509 lines, 0 differ, with 4,687
polys drawn in all four colours. Of its 105 mutations, 101 are caught and
4 are equivalent: the edges', the points' and the pads' fourth lane,
which Render3D never reads, and the distance's floor at 0, which a
square root never goes below.
