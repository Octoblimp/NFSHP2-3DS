# The sky dome and the sun's data

This is task 27's twenty-sixth slice. It covers two things:

- all of `Sky.obj` (0x0011cc70 .. 0x0011cfdc, 876 bytes), which takes the
  sky dome out of the scenery and draws it first in each view;
- the data half of `Sun.obj` (0x00123d30 .. 0x00123ec0, 400 bytes). This is
  the track's sun chunk, which is slot 14 of the LoaderTable, and the five
  textures the sun is drawn with.

The draw half of Sun.obj is the twenty-seventh slice, and
`docs/formats/sun-draw.md` has it. That is `StuffSun` (0x00123ec0,
1,540 bytes), `StuffSunGlare` (0x001244c8, 1,556 bytes) and the 15
`SunZBuffer`s they read back.

The port is in `3DS Files/source/`:

- `sky.{c,h}`: Sky.obj;
- `sun.{c,h}`: the chunk, its loader and unloader, and the texture lookup.

`tools/sky_check.py` cross-checks both files against
`tools/src/sky_test.c`.

## The dome

A track's sky is an ordinary scenery object named `SKYDOME`
(`bStringHash` 0xbe43edbb). Most tracks have a second object,
`SKYDOME_ENVMAP` (0x72923c81), which the environment-map views draw
instead. Sky.obj keeps two models and two matrices:

| Address | What |
|---|---|
| `0x002dc600` | `SkydomeModel`, 32 bytes |
| `0x002dc620` | `SkydomeLocalWorld`, a `bMatrix4` |
| `0x002dc660` | `SkydomeEnvmapModel` |
| `0x002dc680` | `SkydomeEnvmapLocalWorld` |
| `0x00322c28` | `DrawSky` (gp-24520): 1, and only a tweaker writes it |

**`SkyInitModel(model, matrix, hash)`**, 0x0011cc70, runs these steps.

1. It calls `FindSceneryInstance(hash)`. If there is no such object, it
   UnInits the model, makes the matrix the identity, and returns 0.
2. It calls `model->Init(hash)`.
3. It builds the matrix from the instance. The three rows are the
   instance's nine int16s, each times 2^-14 (0x38800000), with w = 0. The
   fourth row is the instance's position, with w = 1.
4. It calls `FindSceneryInfo(hash)` and UnInits each of the kind's three
   LOD models that is not NULL. After that, the cull finds no solid for
   the kind, so the scenery never draws the dome itself.
5. It returns 1.

The image does not check the kind that step 4 finds. An object with that
name implies a kind with that name, because the kind's first name is the
one the objects are looked up by.

**`SkyLoader`**, 0x0011ce18, is called from EndGameFlowLoadingTrackSpecific.
It runs SkyInitModel for `SKYDOME`, then for `SKYDOME_ENVMAP`. If the
second call returns 0, the envmap model is Init'ed with `SKYDOME`'s name
and given a copy of `SKYDOME`'s matrix. So a track without an envmap dome
shows its main dome in the envmap views, in the same place.

**`SkyUnloader`**, 0x0011ced8, is called from
BeginGameFlowUnloadingTrackSpecific. It UnInits each model and makes each
matrix the identity, in the order sky, then envmap.

**`StuffSky(view)`**, 0x0011cf18, returns early when `DrawSky` is 0. Views
1 to 3 are the players' and the mirror, and they render `SkydomeModel`.
Every other view renders `SkydomeEnvmapModel`. The test is one unsigned
compare, `ID - 1 < 3`, so view 0 and negative IDs go to the envmap. Each
render passes its matrix, no light context, and flags 0.

The static constructor, 0x0011cfb8, clears both models' `Solid` and
`NameHash`. The destructor, 0x0011cf88, runs `~eModel` with flags 2 on the
envmap model first, then on the sky model.

### Where the dome goes in the frame

eDisplayFrame (0x00112a40 .. 0x00112ab8) handles the dome in four steps:

1. it turns the Z writes off with `eSetZWriteState(0)`;
2. it calls StuffSky for views 1 to 9, then attaches what each view put on
   its lists;
3. it turns the Z writes back on;
4. it culls and stuffs the scenery.

So the dome is always behind whatever comes after it, however large it is.
The port does the same thing in `trackview_draw`. It turns Z writes off
with `georender_set_zwrite(false)`, calls StuffSky, draws the deferred
list, and turns Z writes back on. Then the scenery follows. In
`georender.c`, the Z-write switch overrides a pass's own depth write.

## The sun chunk

A track has one chunk of type `0x34202`. Its data, rounded up to the next
16 bytes within the chunk, is one `SunChunkInfoE` of 244 bytes:

| Offset | Field | TRACKB12 |
|---:|---|---|
| 0 | `Version` | 2 |
| 4 | `Position` x, y, z | -16384, 800, 6000 |
| 16 | `CarShadowPosition` x, y, z | the same |
| 28 | `SunLayers[6]` | 36 bytes each |

A `SunLayer` (36 bytes) has these fields:

| Offset | Field |
|---:|---|
| 0 | `Texture` |
| 4 | `AlphaType` |
| 8 | `IntensityScale` |
| 12 | `Size` |
| 16 | `OffsetX` |
| 20 | `OffsetY` |
| 24 | `Colour` (r, g, b, a) |
| 28 | `Angle` |
| 32 | `SweepAngleAmount` |

`Texture` is a `SunTextureType`: CENTER, HALO, MAJORRAYS, MINORRAYS or
RING, which is 0 to 4. `AlphaType` is a `SunAlphaType`: BLEND is 0 and ADD
is 1. Only the draw half reads the layers.

**`LoaderSun`**, 0x00123d30, returns 0 for any chunk of another type. For a
sun chunk, it stores the data pointer in `SunInfo` (gp-24144). It does
this in the delay slot, before it checks the version. If the version is
not 2, it clears `SunInfo` again and zeroes `SunPosition` (0x002dfdf0).
Otherwise, it copies the position to `SunPosition`. Either way it returns
1, so a bad version still counts as loaded.

**`UnloaderSun`**, 0x00123da8, also returns 0 for any other type. For a sun
chunk it clears `SunInfo` and zeroes `SunPosition`.

`SunPosition` is the eView light context's. The port defines it in
`eviewmatrix.c`.

## The sun's textures

**`SunTrackLoader`**, 0x00123de0, is called from
EndGameFlowLoadingTrackSpecific, after `rain_Load`. It fills
`SunTextures[5]` (0x002e76f0) with `GetTextureInfo(hash, 1)` for these
names:

| # | Name | Hash |
|---:|---|---|
| 0 | `SUNCENTER` | 0x47beb4b6 |
| 1 | `SUNHALO` | 0xd4d26c59 |
| 2 | `SUNMAJORRAYS` | 0x1744b82d |
| 3 | `SUNMINORRAYS` | 0xad3c5239 |
| 4 | `SUNRING` | 0xd4d80a65 |

Then it sets each texture's `RenderingOrder` (byte 41) to 7. The image
does not check for NULL. If a name is missing, the lookup gives the
default texture, and the default is the one that gets order 7. Only when
there is no default either is the pointer NULL, and then the image
stores through it. The port skips NULL pointers instead. On TRACKB12,
all five names are in `TEX12LOCATION`.

**`SunTrackUnloader`**, 0x00123ea0, is called from the Begin, before
`SkyUnloader`. It clears the five pointers.

## The cross-check

`tools/sky_check.py` runs Sky.obj and the sun's data half as shipped in
mipsemu, with every callee stubbed. The harness links `sky.c` and `sun.c`
against the same stubs. After each step, both sides dump the following:

- both models' names and solids;
- both matrices, bit for bit;
- `DrawSky`;
- the six LOD models of the two kinds;
- `SunInfo`, as an offset into the chunk;
- `SunPosition`;
- `SunTextures`;
- the rendering order of all six textures.

The scenarios cover:

- either dome, both domes, or neither;
- every mask of each kind's LOD models;
- rotations at the int16 ends, and positions with every kind of float;
- the loader, the unloader and SkyInitModel alone, including orders the
  game never uses;
- StuffSky for view IDs -2 to 10, the int32 ends and 256, with DrawSky
  0, 1, -1 and 2, and with the render seam NULL;
- the sun chunk at every misalignment, with versions 0, 1, 2, 3, -1 and
  0x102, and with the wrong type: one bit off in the low byte, the
  container bit set, and one bit off in the high half;
- the sun's names found, missing with a default, and missing with none.

Results: 45 scenarios, 1,159 lines, 0 differ. Of the 78 mutations, 76 are
caught. The other 2 are equivalent:

- The envmap fallback's matrix copy is a plain store, and `eModel::Init`
  never touches the matrices. So running the copy before the Init looks
  the same.
- The image stores `SunInfo` before the version check, and the bad path
  clears it again. So storing it only on the good path leaves the same
  state.

The checkers the slice changed:

- `trackflow_check` now calls SkyLoader, SunTrackLoader, SunTrackUnloader
  and SkyUnloader directly, not through seams. It has 702 lines, and 0
  differ.
- `loadertable_check` treats slot 14 as ported. Its dump now shows
  SunInfo and SunPosition. A scenario loads and unloads TRACKB12's own
  sun chunk through both tables at each misalignment. It has 41,988
  lines, and 0 differ.

## On the 3DS

In Azahar, TRACKB12 logs these lines:

```
sky: SKYDOME drawn by StuffSky, the envmap views' its own; sun chunk version 2 at -16384 800 6000
sun texture 0: SUNCENTER, order 7
...
track drew 437 of 438 (11 in place, 1 sky), 28841 tris
```

The dome is the first thing on the draw list. The screenshots that look
along the canyon show the mountains and the clouds behind the scenery.
