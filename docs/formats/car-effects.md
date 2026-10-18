# The car's and the ground's particle bursts (TASKS 60)

A car's bursts of particles start in two places in retail, both ported
here and both checked against the retail image:

- **`Car::TriggerEffect`** (`0x0011e2b8`, 720 bytes; the demo's
  `0x0011e328`), in `3DS Files/source/cartriggereffect.c`. It is
  `car.h`'s `gCarTriggerEffectFn`, which was never set before TASKS 60,
  so every call was skipped. It is a Car method, but it is not in Car.obj:
  it is compiled with the effect system's code, after the render info.
- **`TerrainEffectEmitters`** (`0x00222248` .. `0x00222594`), in
  `3DS Files/source/terraineffect.c`: the ground's own emitters for each
  terrain. The World makes it and deletes it (`worldinit.c`'s
  `gInitTerrainEffectEmittersFn` and `gCloseTerrainEffectEmittersFn`),
  and a collision fires its impacts and scrapes through `collision.c`'s
  `gTerrainEffectTriggerFn`.

Both fire emitters on WorldEffects with `TriggerEmitter`
([acidfx](acidfx.md)), as a burst: the step they pass is the scale,
negated.

## Who calls TriggerEffect

| Caller | Effects | Scale | `where` |
|---|---|---|---|
| `cardamage.c`, a part breaking | 6 radiator, 7 engine, 12..25 the mirrors, plates, lights and windows | 0.1, 0.4 or 1 for the part's level | 0 |
| `careffects.c`, each frame | 1 and 2 drive-over, 5 bottom-out | by speed or impact | the terrain |
| `careffects.c`, each frame | 3 skid smoke, 4 tire spew | by slip | wheel << 16, plus the terrain |
| `careffects.c`, each frame | 9 driving on a flat, 10 nitro, 11 exhaust smoke | | the wheel << 16 for 9 |
| `carrace.c`, a tire blown | 8 | 1 | `0x50000 + i * 0x10000` |

## Car::TriggerEffect

`TriggerEffect(Car *c, CarEffect fx, float scale, int where, bVector3
*vel)`; `car.h` names the last argument `pos`, but it is the velocity the
particles inherit.

1. Nothing for a car with no render info (`Car+1200` in retail), a scale
   that equals 0 (so -0 too, but not a NaN), `CARFX_NONE`, or a car whose
   rendering position is overridden (`OverrideViewBits`, `Car+1296`, not
   0).
2. The list is the render info's `EmitterList[fx]` (at 888). For effects 1
   to 5, while `pTerrainEffectEmitters` is set, it is that object's list
   for effect `fx - 1` and terrain `where & 0xffff`. Neither index is
   tested.
3. The wheel is `where >> 16` (signed) for effects 3, 4, 8 and 9, else 0.
4. The origin is the state's `Position` for a wheel of 1 to 8, and its
   `GeometryPosition` otherwise (wheel 0 and wheels 9 and up alike). The
   car's matrix is its `BodyMatrix` with the origin as its fourth row and
   1 in that row's w.
5. The velocity is `vel`, or the state's `Velocity` when it is NULL.
6. For each emitter on the list, a copy of its `LocalWorld` is taken. Its
   places are the render info's `EmitterPositionList[wheel]` (at 1096), or
   for wheel 0 the list its data names (`EmitterData->CarPosition`). For
   each place, the copy's fourth row becomes (X, Y, Z, 1), the emitter's
   `LocalWorld` becomes `copy * matrix` (`eMulMatrix`), its
   `InheritVelocity` becomes the velocity's three lanes and 0, and it is
   fired with `-scale` and the car.
7. The copy goes back into the emitter's `LocalWorld`, so an emitter with
   any places keeps the last one in its fourth row. The next call puts a
   place there before it multiplies again, so this changes nothing, but the
   port keeps it.

## TerrainEffectEmitters

1848 bytes, `bMalloc(1848, "TerrainEffectEmitters", 0, 16)`: one
`bTList<AcidEmitter>` for each of 7 effects and 33 terrains, effect-major
(264 bytes an effect).

| Effect | The terrain's group (`TerrainTypeInfo`) | Fired by |
|---|---|---|
| 0 | `DriveOverEmitterGroup` (60) | TriggerEffect 1 |
| 1 | `DriveOver2EmitterGroup` (72) | TriggerEffect 2 |
| 2 | `SkidSmokeEmitterGroup` (84) | TriggerEffect 3 |
| 3 | `TireSpewEmitterGroup` (96) | TriggerEffect 4 |
| 4 | `BottomOutEmitterGroup` (108) | TriggerEffect 5 |
| 5 | `CollisionImpactEmitterGroup` (120) | a collision's impact |
| 6 | `CollisionScrapeEmitterGroup` (132) | a collision's scrape |

- **The constructor** (`0x00222248`) empties all 231 lists. Then for each
  terrain in turn, and each of its seven effects, a group whose name is
  not NULL or empty gets `afxGetEmitters(list, bStringHash(name))`: copies
  of every one of WorldEffects' auto emitters of that group. Retail's
  table names 92 groups.
- **The deleting destructor** (`0x002223b0`) runs `~bTList<AcidEmitter>`
  on each list from the last to the first, which unlinks each emitter from
  the head and deletes it with 3. Then, with bit 0 of the flags, it calls
  `__builtin_delete`, which is `bFree`, with no NULL test.
- **TriggerEffect** (`0x00222438`, `(effect, terrain, scale, at,
  velocity)`): nothing for an empty list. Otherwise each emitter's
  `LocalWorld` becomes the identity moved to `at` (w 1), its
  `InheritVelocity` becomes the velocity's three lanes and 0, and it is
  fired with `-scale` and no car. There is no test of the scale here.
- **InitTerrainEffectEmitters** (`0x00222530`) makes one at
  `pTerrainEffectEmitters` (gp-15816) unless one is there.
  **CloseTerrainEffectEmitters** (`0x00222570`) deletes it with 3 and
  clears the pointer.

The image's `Collision::AddImpulse` calls TriggerEffect on the pointer
with no test. The port's seam (`main.c`'s `terrainEffectTrigger`) skips
the call while the pointer is NULL, outside a World.

## The check

`tools/cartriggereffect_check.py` runs retail's Car::TriggerEffect and all
five TerrainEffectEmitters functions in RetailEmu, over retail's own
terrain table, `eMulMatrix`, `bIdentity`, `bStringHash` and
`~bTList<AcidEmitter>`. `tools/src/cartriggereffect_test.c` runs the port
over the same script. TriggerEmitter, afxGetEmitters (which gives a list 0
to 2 emitters by the group's hash), the emitter's deleting destructor,
bMalloc and `__builtin_delete` are stubbed on both sides and print their
arguments. TriggerEmitter's line includes the emitter's `LocalWorld` and
`InheritVelocity`, and after each call a hash of every emitter's two
fields is printed, so a copy put back wrong is caught.

The script covers:

- every gate;
- each of the car's lists, with wheels 0 to 9, 12 and 27, both positions
  and both velocities;
- a turned body with values that are not exact in binary;
- a NaN scale;
- the 92 groups;
- effects 1 to 5 over all 33 terrains through TriggerEffect;
- all 231 lists through the terrain trigger, scale 0 among them;
- close twice, make again, and the destructor with no free, on NULL, and
  both.

Result: 511 ops, 329 emitter triggers, 0 differ. The mutations are listed
in the checker, each with what it changes, and every one is caught.
