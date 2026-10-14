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
`0x001b5c50`. The port has it in `cardamage.{c,h}`; eSolid's environment
mapping is in `esolid.c` and eModel's in `emodel.c`.
`tools/cardamage_check.py` runs retail's code against the port, and
`tools/loadertable_check.py` runs the environment mapping.

| function | retail |
|---|---|
| LoaderBodyDamage / UnloaderBodyDamage (slot 17) | `0x001b4760` / `0x001b47b0` |
| FindBodyDamageInfo | `0x001b47e8` |
| BodyDamageModel::Init / CallDamageVertexFunction | `0x001b4820` / `0x001b4b50` |
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

## The wreck, the repair and the destructor

The wreck (`0x001b5bc8`, what a munition's blast or a cop's wreck does)
gives every zone 1.0 with an impact of 9999, so everything breaks, and
then RethinkDamage: the levels worked out again and applied.
RepairAll (`0x001b5c20`, the cop manager's ResetAllDamage) sets every
zone and the total to 0, applies the body, and rethinks. The destructor
sets the levels to 0 and applies them, so the textures and the
environment mapping go back. Then it repairs the body, takes it off its
list, and frees the CarDamage with flags & 1.

## In the port

`main.c` binds `carinit.h`'s, `collisionbody.h`'s, `cop.h`'s and
`copmgr.h`'s seams to `cardamage.c`: the constructor, the item parts and
the destructor, SetALevelBodyDamageInfo and AddModel, AddDamage, the
wreck and RepairAll. Every racer and cop now has a CarDamage, so hits
derate the engine (physicscar), smoke and steam (careffects) and break
the lights and windows (carrenderinfo).

Still to come (TASKS 51):
- **The renderer's environment mapping** (51b). The port's GeoBatch
  flags are baked when the car's meshes are built, so the strip flag
  that CarDamage clears is not yet read.
- **The vertices** (51c). DamageVertexFunction dents each vertex by its
  key, darkens it, and shows the scuff strips. The port's solids are GPU
  meshes, so the walk is a seam, `gBodyDamageVertexWalkFn`, skipped
  while NULL. The walk's position in each model (RepeatCount, KeyNum)
  is still reset as retail does.
- **Car::DamageAbove** (`0x00135280`, `gCarDamageAboveFn`), skipped
  while NULL.

`Car::TriggerEffect` (`0x0011e2b8`, `gCarTriggerEffectFn`) is not
ported, so the effects are skipped (TASKS 60). The replay's DoSnapshot
waits on the ReplayManager.

## The check

`tools/cardamage_check.py` runs retail's code in RetailEmu: the loader,
the unloader and the find, BodyDamage and CarDamage whole, over
BodyDamageInfoList and BodyDamageList as the static constructor leaves
them, and the image's own item table, window-less types and effect
scales. What CarDamage calls out of the object is stubbed in the model
and stood in for in the harness (`tools/src/cardamage_test.c`), and both
print the call: eFindPositionMarker, PlayGlass, TriggerEffect,
UpdateCarReplacementTextures, eModel::SetEnvironmentMapping, the vertex
walk and the delete.

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
- 700 random hits, zones and repairs over five cars.

It runs 2,446 ops for 13,349 lines, 0 differ. Of its 135 mutations, 132
are caught and 3 are equivalent:
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
