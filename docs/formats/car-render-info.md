# CarRenderInfo, what a car draws with

From retail's `Car.obj`. Step 6 of the cars-and-racing work: one is made for
every car when it is built, and Render (the next slice) draws the car from it.

Ported to `3DS Files/source/carrenderinfo.{c,h}`, with what it needs from
`epositionmarker.{c,h}`, `cartypeinfo.c` (GetSkinInfo,
GetUsedCarTextureInfo) and `emodel.c` (AttachReplacementTextureTable,
RenameTexture, ReplaceLightMaterial, GetBoundingBox).
Cross-checked by `tools/carrenderinfo_check.py` against
`tools/src/carrenderinfo_test.c`.

| Function | Address | Bytes |
|----------|--------:|------:|
| Car::InitRenderInfo(RideInfo *) | 0x0011dc80 | 1536 |
| CarRenderInfo::CarRenderInfo(RideInfo *, Car *) | 0x0011e860 | 4700 |
| CarRenderInfo::~CarRenderInfo | 0x0011fac0 | 928 |
| CarRenderInfo::SwitchSkin(RideInfo *) | 0x0011fe60 | 108 |
| CarRenderInfo::UpdateCarReplacementTextures | 0x0011ff68 | 456 |
| CarRenderInfo::CreateCarLightFlares | 0x00120360 | 632 |
| the part culler's InitPart | 0x0011d580 | 200 |
| the static constructor | 0x00124528 | |

## The record

2352 bytes, where the demo's is 1856. Retail adds the body's pivot (+48),
a broken-light mask (+884), the part culler (+1888, fourteen 32-byte
parts) and `AlphaOverridden` (+2340). The layout, with a compile-time check
of the offsets that matter, is in `carrenderinfo.h`.

The car points at it from +1200 in retail's Car; the port's `car.h` keeps
the demo's offsets (1168 for it), which nothing outside the port reads.

## What the constructor does, in order

1. Every model's constructor (name and solid cleared); the flare list, the
   26 emitter lists and the 28 emitter-position lists made empty; the part
   culler zeroed.
2. The car, the ride, `pAlphaInfo` NULL, `AlphaOverridden` 0, and
   `CarTimebaseStart = bRandom(8)` from the default seed.
3. The type and its skin (`GetSkinInfo(type, skin, 1)`), and SwitchSkin,
   which fills `UsedTextureInfos` with `GetUsedCarTextureInfo(ride, 0)` and
   the five replacements that carry the skin.
4. The damageable table's old names -- the two skins, the six windows, the
   four lamps -- then UpdateCarReplacementTextures, then the dash's and
   the tyres' pairs.
5. The skin's light material, `elGetLightMaterial(skin->LightMaterialNameHash)`.
   Retail reads the skin unguarded; the port asks for material 0 when no
   skin table is loaded.
6. The models by name from the type's `BaseModelName`:
   - the four bodies `_A` to `_D` (a traffic car's are A, A, B and C). A
     car that dents and has an instance index gets `_A<n>` and `_B<n>`,
     its own copies. The third and fourth of a car that is not traffic
     have SKIN1 renamed to SKIN1B. The first three take the damageable
     table (instances 0, 1, 2), the fourth the skin table.
   - the tyres, `_TIRE_FRONT_A..C` and `_TIRE_REAR_A..C` (a traffic car's
     C is its B), a rear with no solid drawing the front's;
   - the brakes (the rear falling back to the front), the wipers, the side
     mirrors, the plates, the scuffs (`_SCUFFS<n>` with an instance), and the
     dash's five: `_DASH`, `_DASH_WHEEL`, `_DASH_WINDOW`, `_SPEED_NEEDLE`,
     `_TACH_NEEDLE`;
   - the wheels' blur, `_WHEEL_BLUR` for both, or `_WHEEL_BLUR_F` and `_R`.

   Each takes its replacement table and instance, and CARSKIN's light
   material is replaced with the skin's in all but the bodies and the blur.
7. The shadow: `_SHADOWFE` in the front end with rendering order 5,
   `_SHADOWIG` in game with 3, and `SHADOWRAMP`.
8. A car in the world: its animated driver, and its body damage's A level
   and models -- the three bodies and the scuffs for a car that dents, the
   scuffs alone (flag 1) for one that does not.
9. `BodyPivot`, the fourth row of the body's solid's pivot matrix, then
   CreateCarLightFlares.
10. The box round the body and its two mirrors, a tenth larger each way.
11. The culler's points: the four wheels, the middles of the left and right
    sides for the blur, the wheels again for the brakes, the front left
    and rear right for the two ends, the middle for underneath, and the
    middle moved along the wheels' plane's normal by the front left's
    radius for the shadow. InitPart normalises the part's planes in the
    shared table where a plane's length is more than 0.01 from 1, so only
    the first render info built changes the table.

InitRenderInfo mallocs 2352 bytes ("CarRenderInfo", 0, 16), constructs,
then makes nine emitter positions from the wheels (the middle, the ends'
and sides' middles, the wheels), one or two more for each of the car's
markers with a known name, in the body's space less its pivot, fetches the
26 emitter lists from AcidFX by their CARFX_ hashes, and sets
`TestRenderInfo` to texture 9024.

## Tables

- **The cull table** (0x002dfd40, 14 × 80). The static constructor
  writes it; the port has it as a constant with its values.
- **The flare directions** (0x002e01f8, 16-byte rows). A flare's direction
  is row `(marker.Param >> 8) & 0xff`. The first six rows are data and the
  static constructor writes the rest, and it gives the eighth an x of 0.95
  (gp-32156). The first run of the checker differed on 318 lines until the
  port had that 0.95. Retail has eleven rows; a larger byte reads on into
  the CARFX_ table and gets pointers for floats, and the port gives it no
  direction.
- **The window textures** (0x002e0380): WINDOW, WINDOW_DAMAGE0..2 by the
  window's damage level.
- **The broken-light bits** (0x002e01a0): 1, 2, 4, 8, and 16 for both brake
  lights at once.

## The box

Retail's box code:

```
bInitializeBoundingBox(&AABBMin, &AABBMax)
for model in Body[0], SideMirrors[0], SideMirrors[1]:
    model.GetBoundingBox(&box_min, &box_max)     // leaves them alone with no solid
    bExpandBoundingBox(&AABBMin, &AABBMax, &box_min, &box_max)
AABBMin -= 0.1, AABBMax += 0.1
```

`box_min` and `box_max` are never initialised: a model with no solid expands
the box by whatever is on the stack, or by the previous model's box. The port
starts them empty, so such a model adds nothing. The checker's model puts the
empty box where retail keeps it on the stack, which is what the port starts
from.

bInitializeBoundingBox copies its empty box from 0x0031fda0, which bmath's
static constructor (0x002598d8) fills with FLT_MAX. The checker's model has
to run that constructor too. Without it the box starts at zero, and the last
ten lines differed.

## The check

`python tools/carrenderinfo_check.py` runs 321 scenarios over 105544 lines
and 0 differ.

Each scenario builds a world: four car types, a skin table, solids with
texture and light-material tables, position markers, and the textures that
are loaded. It then makes a render info by InitRenderInfo, or by the
constructor alone with a car or without one. After that it may switch the
skin, update the damage's textures, make the flares again or destroy the
render info.

After each step both sides print the record field by field. The lists are
walked, then come the solids' tables, the textures' rendering orders, the
model list, the cull table and the random seed.

`--mutate` runs 163 mutations over carrenderinfo.c and the four helpers:
161 are caught and 2 are equivalent.

- `em-attach-apply` drops AttachReplacementTextureTable's second apply.
  ReconnectTextureTable has already applied the table, so the second one
  writes the same pointers.
- `ep-none` drops eFindPositionMarker's two-zeros guard. Every caller here
  asks by a model's type hash, which is never 0.

The first pass left two other survivors, and each one now has a scenario
that catches it:

- the body's solid had a pivot y of 0, so a flare's y could not show
  whether the pivot had been taken off;
- the destructor ran on an alpha info that was never overridden, so the
  flag it clears was already 0.

Two patterns were also fixed after that first pass.

## What is not ported

These go through seams, and a NULL seam is skipped:

- the animated driver (0x00133488 and 0x001334f0);
- BodyDamage's SetALevelBodyDamageInfo and AddModel;
- AcidFX's afxGetEmitters, and AcidEmitter's deleting destructor. The
  destructor aborts when a list holds an emitter, because only the emitter
  seam could have put one there;
- InitCarEffects, apart from the emitter-position pool, which
  `carrenderinfo_init_slot_pools` makes.

`gCarInitRenderInfoFn` is left NULL until the race's cars are built
(step 8). Render (0x00120ef8) and the culler's two passes (0x0011d648 and
0x0011d980) come next.
