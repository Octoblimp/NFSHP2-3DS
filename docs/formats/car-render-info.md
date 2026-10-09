# CarRenderInfo, what a car draws with

From retail's `Car.obj`. Step 6 of the cars-and-racing work: one is made for
every car when it is built. Render draws the car from it, and RenderCars
calls Render for every car in the world; both have their own sections below.

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
| Car::SwitchSkin(unsigned int) | 0x0011e588 | 56 |
| CarRenderInfo::SwitchSkin(RideInfo *) | 0x0011fe60 | 108 |
| CarRenderInfo::UpdateTextureInfo(eReplacementTextureTable *) | 0x0011fed0 | 56 |
| CarRenderInfo::UpdateSkinTextures | 0x0011ff08 | 96 |
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

`python tools/carrenderinfo_check.py` runs 327 scenarios over 108561 lines
and 0 differ.

Each scenario builds a world: four car types, a skin table, solids with
texture and light-material tables, position markers, and the textures that
are loaded. It then makes a render info by InitRenderInfo, or by the
constructor alone with a car or without one. After that it may switch the
skin (CarRenderInfo's SwitchSkin, or Car::SwitchSkin with the ride's
skin byte set first), update the damage's textures, make the flares again
or destroy the render info.

After each step both sides print the record field by field. The lists are
walked, then come the solids' tables, the textures' rendering orders, the
model list, the cull table and the random seed.

`--mutate` runs 175 mutations over carrenderinfo.c and the four helpers:
173 are caught and 2 are equivalent.

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
(step 8).

## Render

`carrender.c` has Render and the parts of Car.obj that it calls:

| Retail | Address | Bytes | Port |
|---|---|---|---|
| CarRenderInfo::Render | 0x00120ef8 | 9840 | `carrenderinfo_render` |
| UpdateLightStateTextures | 0x00120130 | 560 | `carrenderinfo_update_light_state_textures` |
| CalculateTireBlur(int) | 0x00120ea8 | 76 | `carrenderinfo_calculate_tire_blur` |
| the part culler's pass | 0x0011d980 | 528 | `carrenderinfo_cull_parts` |
| sh_Setup | 0x00120d60 | 324 | `car_shadow_setup` |
| convex_hull | 0x001209f8 | 512 | `car_shadow_convex_hull` |
| smooth_shadow_corners | 0x00120c00 | 352 | `car_shadow_smooth_corners` |
| ch2d | 0x00120980 | 120 | `car_shadow_ch2d` |
| make_chain | 0x00120850 | 300 | `make_chain` |
| cmpl, cmph | 0x001207a8, 0x00120828 | | `cmp_low`, `cmp_high` |

The culler has a second function, at 0x0011d648. Nothing calls it and it is
not ported.

### What Render does

This is Render's order, and it is retail's:

1. It takes the car's size on screen, in pixels, for a sphere of 3. In view
   mode 3 the size is multiplied by 0.7. Under 4 pixels nothing is drawn.
2. It takes four blocks of frame memory: a 288-byte light context and three
   64-byte matrices. It asks for all four before it tests any. If one is
   missing it draws nothing.
3. The local-to-world matrix is the body's matrix times CarRenderMatrix,
   placed at the car's position. The box goes through
   `scenery_classify_aabb`, and a car that is off screen stops here.
4. It sets up the light context from the camera, then updates the lights'
   textures (see below). It asks for the skin's info and never uses what
   comes back.
5. It picks the level of detail from `CarLodPixelSizes` (120, 45, 20 and
   0): each level down is used if the size is under its bound and that
   body exists. A car that is in the air, with its underside in view,
   stays at level 2 or better. The `ForceCarLOD` and `ForceTireLOD`
   tweakables override the levels.
6. When player one's camera, raised by 0.5, is inside the car's box, nothing
   is drawn. That is view 1, level 0, closer than 4.
7. The two biased matrices come next: the body's lifted by 0.01, and an
   identity at the position. Both are biased by dist / dist, which is 1, or
   NaN when the camera is on the car. Then the culler runs with the eye in
   the car's frame.
8. The light flares, then the animated driver: views other than 3, and only
   when the car renders its driver.
9. The shadows. The hull shadow is the collision body's points cast along
   the sun onto the ground, their hull, and the hull with its corners
   smoothed. It is drawn below level 3, not in the front end, and not in
   view 3. The grid shadow is a 4x4 grid under the box, laid on the ground.
10. The body is drawn at its level. Below level 2 come the panels whose
    damage is under 2, and the plates. The mirrors come below level 3, while
    their culler part is in view and their damage is under 2. The scuffs come
    below level 2.
11. The tyres, below level 3. A front wheel turned between 6 and 354
    degrees is drawn whatever the culler says. The left tyres are the right
    tyres turned round. The blur is drawn with a copy of the tyres' light
    contexts, with its alpha at +60 in each copy. That happens below tyre
    level 2, not in the front end, and only for wheels whose blur is over
    0.1.
12. The brakes, below level 2. The left brakes are the right brakes
    mirrored in y.
13. The wipers, while they run, over 40 pixels.

Every matrix and light context that Render hands on comes from
`eframe_malloc`. The calls come in retail's order and at retail's sizes, and
when one fails, what it was for is skipped. The renderer is reached through
seams, each of them skipped when NULL: eModel::Render (`gEModelRenderFn`),
the two strip builders (`gEStripFns`, `gExStripFns`), the light flares
(`gERenderLightFlareFn`, bound to elightflare.c's eRenderLightFlare, see
[light-flare](light-flare.md)) and the animated driver.

### Where the port differs

- **The hull's arrays.** Retail does not bound them. The port casts at most
  `HULL_MAX_POINTS` (64) points, which is more than any car's collision
  body has.
- **CopLights.** It is a word in retail's Car and an `int8_t` in the port.
  Render only compares it with 0 and 2.
- **DriverInfo.** Retail keeps `TheDriverType` at +8 and the port keeps it
  at +4. Render reads it by name.
- **Retail's GetBoundingBox call.** Its results are never read, so the port
  does not make it.
- **CarRenderInfo's `OpenTop`.** It is CarTypeInfo's byte at 231
  (`car-type-info.md`).

### The check

`python tools/carrender_check.py` runs Render on retail's image in mipsemu
against the port in a host harness. Every call below Render that is not
ported is a stub, and each stub prints a line with its arguments on both
sides. Each scenario builds a world first: a car and its driver, its
damage, the collision body, the camera and view, the sun, the ground, the
render info's solids, the culler's table, and the frame memory. After
Render, both sides dump the frame pointer, the culler's parts, the damage,
the wipers' state and the three hull arrays.

It ran 697 directed and random scenarios over 197394 lines, and 0 differed.
Every stub is reached: 6383 model renders and 406 driver renders, flares
in 231 scenarios, and strips in 484. All 21 models are drawn.

Two mistakes in the checker's first run made 4384 lines differ, and
neither was the port's:

- **Unaligned frame memory.** Retail uses `lq` and `sq` on frame memory, so
  an unaligned frame position does something else on the PS2. In the game
  it is always 16-aligned, and the scenarios now keep it so.
- **Zero-extended stub values.** A stub that handed back -1 zero-extended
  in v0 passed retail's `slti`. The stubs now sign-extend what they return.

`--mutate` runs 304 mutations over carrender.c. 301 are caught and 3 are
equivalent:

- `chain_i` starts make_chain's loop at 1. The first pass then tests V[1]
  against itself. The cross product is 0 for every finite point, so the
  pass swaps V[1] with itself.
- `hs_seg_len` gives the edge's last strip n corners rather than what is
  left. smooth_shadow_corners gives three points a corner, so what is left
  is n as well.
- `lf_brake_forced` drops base_rear from the forced brake lights. base_rear
  is 0 or 0.7, so both values clamp to 1.

The first pass left ten more survivors, and each one now has a scenario:

- **The culler's normalise.** The extras were too short to matter. Extras
  as long as the eye's reach now decide the side.
- **cmpl's y and make_chain's collinear test.** The body was never square
  to the axes. A square car in a sun straight along x or y now puts points
  on a shared x, and three on a line.
- **The hull's and the grid's 4.** Their ground was never steeper than
  their plane test allowed. Steep ground whose normal matches its slope now
  reaches them.
- **The hull shadow's fade.** It was only reached below 45 pixels. A
  forced level 2 from further in now reaches it.
- **The driver's 100 in mode 3, and the 0.9 behind the car.** The driver
  now gets a size of exactly 101, and a camera 45 degrees off behind.
- **QueryLightMat's set.** The light context's line now prints the flag.
- **The camera inside the car's 4.** No box was long enough for the camera
  to be inside it at 3 to 4 away. A longer box now is.

With them it runs 740 scenarios over 211648 lines, and 0 differ.

## RenderCars

`rendercars.c` has RenderCars and the two helpers of Car's that only it
calls:

| Retail | Address | Bytes | Port |
|---|---|---|---|
| RenderCars(eView *) | 0x00124060 | 580 | `render_cars` |
| whether the car blinks in a view | 0x00133190 | 120 | `car_is_blinking_in_view` |
| the tyres' and the brakes' matrices | 0x00135fb8 | 296 | `car_get_render_wheel_matrices` |

eDisplayFrame calls RenderCars once for each view. After it come the front
end's cars, RenderFrontEndCars (0x00123d28) twice a view. Only the car
selector and tCarModelViewer make a FrontEndRenderingCar, so that pair
waits for the car selector (step 16). In a race the list is empty.

### What RenderCars does

RenderCars does nothing when there is no world. Otherwise it walks the
world's CarList. It skips the camera's CarNotToRender, a car whose
RenderingEnabled byte is 0, and every car once 99 have been drawn. For each
car left:

1. `draw` is IsPoofed's word with its low bit flipped (`xori`), so any
   value but 1 draws.
2. If the car blinks in the view, and the world is not paused, `draw`
   becomes the frame counter's low bit. Paused means `|WorldTimeElapsed|`
   is 0.001 or less. A car blinks in a view when the override does not hold
   that view, and either Car::IsBlinking says so or the override's blinking
   bit for the view is set. A NaN step is not paused.
3. If the override's visible bit for the view is clear, `draw` is 0. Every
   bit is taken by the view's ID shifted by its low five bits, as `srav`
   takes it.
4. A car that draws counts towards the 99. Its four tyre and four brake
   matrices are built on the stack. In a view the override holds, they are
   identities placed at the car type's four wheels, with w = 1. Otherwise
   they are copies of CarState's WheelMatrix and BrakeMatrix.
5. Render gets the override's position and body matrix in a view it holds,
   and CarState's GeometryPosition and BodyMatrix in the others. The flags
   and the forced lights are both 0.
6. The view's player is the first of `pPlayersByIndex` whose ViewID the
   view's ID is. If that player's camera zone is 6 or 7 (the jump cam and
   just after it), nothing more is drawn for the car. Otherwise DamageAbove
   gets the camera's eye and direction.

The loop's test reads `pCurrentWorld` again each time, after whatever the
car's calls did, and so does the port.

Retail's RenderCars is not the demo's (0x00123468). The demo draws the
in-car dashboard for the camera's own car. It blinks the cars and places
the wheels without looking at the override, and it draws the damage above
the cars in every view.

### Where the port differs

- **DamageAbove** (0x00135280) is `gCarDamageAboveFn`, and NULL skips it.
  It calls DamageCap (0x00135490) and asks the race coordinator, the cop
  manager and IsBeingPursued, so it is ported with the cops (step 12).
- **Player** is still a partial layout. RenderCars reads ViewID and
  nZoneCurrent, which retail keeps at 24 and 88, and the port keeps them at
  20 and 76, by name.

### The check

`python tools/rendercars_check.py` runs RenderCars on retail's image in
mipsemu against the port in a host harness. 0x00133190, 0x00135fb8 and
eIdentity run as shipped. IsPoofed, IsBlinking, Render and DamageAbove are
stubs on both sides, and each prints its arguments. Render's stub also
prints all eight matrices, since they are on the stack.

Any of the four stubs can move `pCurrentWorld` onto a later car at its k-th
call. Nothing in the game does that yet; it shows that both sides read it
again for each test.

The scenarios cover:

- no world and an empty list;
- every car flag in eight views, among them 31, 32, 33 and -1. Each flag
  word has random bits, and the neighbours of the view's bit are set the
  other way;
- the blink's timing: the step at 0 and -0, at 0.001 and the floats either
  side of it, a NaN and both infinities, against six frame counters;
- the camera's own car, 98 to 128 cars, and cars that don't draw among the
  first 99;
- each way of finding the view's player, over seven zones;
- a NULL render info, and one shared by two cars;
- 400 random calls.

It ran 1272 scenarios over 20075 lines, and 0 differed on the first run.
They reach 3684 renders, 974 of them at the override, and 3492 damage
calls. Six calls hit the cap of 99. The world moves in 27.

`--mutate` runs 89 mutations over `rendercars.c`, and all 89 are caught.
Two of them crash the harness: `rc_null_world` and `rc_next_prev`. The
four on the cap are the narrowest, at 16 and 24 lines, and only the cap's
scenarios catch them: 98, 100, `<` for `<=`, and counting a car before it
draws.
