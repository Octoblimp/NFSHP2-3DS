# The drivers in the cars

Retail's `AnimatedDriver.obj` (0x001a8f50 .. 0x001aa6c8) and
`eAnimation.obj` (0x001a67f8 .. 0x001a7c3c): a driver in every car but
traffic, posed from bone animations and skinned on the vector unit. The
port had the seams for them (`carrender.c`'s `render_driver`, `carmove.c`,
`carcollisionbody.c`, `cameracoord.c`, `carsnap.c`) and nothing behind
them until TASKS 83.

Ported to `3DS Files/source/animdriver.{c,h}` and `eanim.{c,h}`, both free
of `<3ds.h>`. `bchunkload.c` loads the animations in slot 12, `main.c` sets
the seams, and `trackview.c`'s `render_model_bones` does the skinning.

Checked by `tools/animdriver_check.py` against
`tools/src/animdriver_test.c`. Retail's AnimatedDriver code and eAnimation's
keys, pose and render run in mipsemu next to the port. Only the view mode,
the look-back car and angle, and the renderer's visibility and draws are
stubbed. 6 facts are read from the image without running it: the wiggle
table, the three blackball tables, the gear change's bones, and
DRIVER_ANIM01's hash. `--mutate` changes the port 132 ways: 131 are
caught, and the last (`qt_full`) is equivalent, for the reason the script
gives.

## The animations: chunk 0x80034008

The bundles hold four: INGAMEB's `DRIVER_ANIM01` (262 frames) and
`DRIVER_SHIFT01` (31), and PRERACEANIM's `DRIVER_PRERACEG02` and
`DRIVER_PRERACEG14`. Each is a chunk of three or four children:

| Child | Payload |
|---|---|
| 1 | the eAnimationSolid, 96 bytes, 16-aligned |
| 2 | rotation keys: x, y, z, w as int16 over 32767, NumFrames a node |
| 3 | translation keys: a bVector3 (16 bytes) a frame, the root's |
| 4 | labelled frames, when there is one |

| Off | Field | |
|---|---|---|
| 0 | bNode | on eAnimationSolidList (gp-19400) |
| 8 | Name | 24 bytes |
| 32 | BBoxMin, BBoxMax | |
| 64 | NameHash | bchunk_hash of the upper-case name |
| 68 | NumFrames | u16 |
| 70 | NumNodes | u16, 42 for the drivers |
| 72 | NumRotationKeys, pRotationKeys | |
| 80 | NumTranslationKeys, pTranslationKeys | |
| 88 | pLabelledFrames | |

A node's key at a frame is `pRotationKeys[(NumFrames * node + (int)frame)
* 4]`. GetRotation and GetRotations read it unchecked. SetRotation and
GetTranslation take frame 0 for a frame outside the solid's.

The unloader (0x001a7688) takes the solid off the list at chunk+16. The
port uses the loader's aligned address, which is the same for a
16-aligned chunk.

## The bone tree: an eSolid's 0x34007

The driver's model has an animation tree at eSolid +160 and +164: NumNodes
and 96-byte nodes. Each node has its ObjectToBoneSpace matrix, a
translation from its parent, its own, parent's, first child's and next
sibling's indices (0 for none), and a 16-byte name.

PoseMatrixRecursive (0x001a6e00) poses node n as its quaternion's matrix
with its translation, times its parent's. Node `nBoneScale` then has its
rows scaled by `vBoneScale`, which is the R/C Car's big head; the stomper
sets them to 15 and 5.5. Then it poses each child. Render (0x001a6b80)
multiplies each bone by its node's ObjectToBoneSpace and hands the bones to
eModel::RenderStrips.

## The skinning

RenderStrips with bones (0x0010dd58) copies each strip to frame memory, and
DoBlendingOnStrip (0x0010d778) rewrites its positions. The low bytes of a
position's three floats are the vertex's bone A (x), bone B (y) and weight
(z). The helper (0x0010d660) computes:

- weight 0: M[A]·v;
- weight 1: M[B]·v;
- otherwise, with w = weight / 256, M[A]·v·(1 − w) + M[B]·v·w.

v is (x, y, z, 1) with the raw floats; the result's w is zeroed; the
normals are left alone.

On the 3DS the CPU does the same blend into a ring of its own
(`georender_skin_alloc`, 16,384 vertices a frame). georender then draws the
copy lit, as a car's batch, from a GeoMesh whose clusters are NULL. A
driver's solid has 903 to 2,749 vertices. A full ring skips the driver and
counts it in the debug log's "unposed".

## AnimatedDriver, 144 bytes

| Off | Field | |
|---|---|---|
| 0 | pCar | |
| 4 | pAnimations[3] | an eAnimation a LOD, when its solid has a tree |
| 16 | pModels[3] | a plain eModel a LOD otherwise |
| 28 | pSteeringFrame | a 48-byte BSpline |
| 32 | pCharacterInfo | |
| 36 | SkinReplacementTextureTable[2] | body, head |
| 92 | ShiftAnimationNameHash | `DRIVER_SHIFT01` |
| 96 | SteeringWiggleNumber | |
| 100 | DisableRenderingFlag | |
| 104 | LookingBackwardsFlag, DrivingBackwardsFlag | bytes |
| 108 | CurrentLookingBackwardsType | |
| 112 | AnimationPlayers[2] | 16 bytes each |

Car::AssignAnimatedDriver (0x00133488) makes one for each car whose
CarTypeInfo's UsageType is not 2, which is traffic. InitializeArtwork reads
the character's BodyTypeInfo: three model names, one a LOD, and the body
and head skins chosen by the character's skin numbers as replacement
textures.

## The table, 0x003111f8

| Type | Solid | Begin | Frames | Pause | Interrupt | Blend | Combine |
|---|---|---|---|---|---|---|---|
| 1 STEERING | DRIVER_ANIM01 | 15 | 30 | | | | |
| 2 IDLE | DRIVER_ANIM01 | 231 | 30 | | | | yes |
| 3 DRIVING_BACKWARDS | DRIVER_ANIM01 | 61 | 30 | 75 | 1 | yes | |
| 4 LOOKING_BACKWARDS_LEFT | DRIVER_ANIM01 | 111 | 20 | 121 | 1 | yes | yes |
| 5 LOOKING_BACKWARDS_RIGHT | DRIVER_ANIM01 | 91 | 20 | 101 | 1 | yes | yes |
| 6 COLLISION_LIGHT | DRIVER_ANIM01 | 211 | 20 | | 2 | yes | |
| 7..10 COLLISION_FRONT, RIGHT, LEFT, BACK | DRIVER_ANIM01 | 131, 151, 171, 191 | 20 | | 3 | yes | |
| 11 GEAR_CHANGE | DRIVER_SHIFT01 | 1 | 30 | | 1 | yes | |
| 12, 13 PRERACEG02, G14 | Driver_PreRaceG02, G14 | 0 | the solid's | | | | |

InitAnimatedDriver (0x001a9238) hashes each name in upper case and finds
its solid. A row without a solid gets 0 frames, and a row that begins at 0
takes the solid's frame count. While AnimatedDriverNeedsFixup is set (a
track load sets it, `trackflow.c`), the combined rows' keys are rewritten once as relative
to frame 30, the straight-ahead pose: conj(q30) · qf, normalised.

## The players

A player runs one row. Time is WorldTime, two ticks a frame. Begin sets
the start (now plus a delay), the end (2 × NumFrames later), and the
pause. A row with a pause holds its pause frame until it is released, with
an end 100,000 ticks off. A pause of -1 loops instead.

- **QueueAnimation** (0x001a9ef8) starts the row on a player that has
  ended, delayed until the other one ends. So a row queued behind a held
  pause waits for its release. It is refused for a blackballed row, when
  neither player has ended, or when one ends more than 100,000 ticks away.
- **Release** lets a paused row play out from its frame. A row that is not
  running is cancelled.
- **GetFrameNumber** is `Begin + (now − start) / 2`, wrapped by NumFrames
  for a loop and capped at the pause frame.

## The steering frame

CalculateSteeringFrameNumber (0x001aa0a0) maps the car's steering, s = the
CarDriver's u16 / 65536, to frame `30 + 150·s` for s below 0.5, and
`30 − 150·(1 − s)` otherwise. It adds the wiggle table's entry for
`(WorldTime − SteeringWiggleNumber) % 62`, clamps to 15..45, and aims the
spline there. The frame drawn is the spline's value, eased over 0.1
seconds.

## BuildQuaternionTable (0x001aa2f0)

1. It handles looking and driving backwards, when their flags are set.
2. It poses every bone from DRIVER_ANIM01 at the steering frame, with the
   root translation; without that solid, the translation is zeroed.
3. With no player running, it queues IDLE every 120th loop and stops.
4. A blended row eases in over its first 5 frames (w = 0.2 · (in + 1)) and
   out over its last 5 (w = 0.2 · out).
5. The gear change slerps only bones 30, 31 and 32 (gp-19216) towards
   DRIVER_SHIFT01.
6. Otherwise, at w = 0 it stops. A combined row multiplies each bone by
   its key (relative to frame 30 after the fix-up). At w = 1 the row's keys
   replace the bones. Anything else slerps towards them by w.

## Looking back, driving back, collisions

- **Looking back** (BeginLookingBackwards 0x001a9c40) picks a side each
  frame. With another car to look at, it uses the angle to it: 0 for none,
  0x4000 or 0x8000 for right, 0xc000 for left, and any other angle keeps
  the last side. Without one, it uses the steering: above 10° and below
  180° is left, above 180° and below 350° is right, and anything else
  keeps the last side. The other side's animation is released.
- **Driving backwards** holds DRIVING_BACKWARDS at its pause frame until
  the car stops reversing.
- **BeginCollision** (0x001a9e28) cancels both players and queues the
  flinch for its side, unless a running row may not be interrupted by that
  strength. A blackballed flinch becomes COLLISION_LIGHT.

## Blackballed rows

Some rows would put an arm through the car:

- by car type (0x00311428, 21 pairs);
- types 11 and 2 under a roof, outside view mode 1 (0x003114d0);
- for a cop's character, one whose body type starts "Co" (0x003114e0, 8
  pairs).

## The pre-race waves

The pre-race camera coordinator calls BeginAPreRaceAnimation (0x0019c078)
on each car it picks: QueueRandomAnimations(12, 13, 2), two of the waves
that are not blackballed, in a random order. Retail draws on bDefaultSeed.
The port uses `bViewSeed`, so a lockstep race keeps the draw off the
world's seed.

## Drawing

`carrender.c`'s render_driver draws the driver, except in view 3, when the
car's DriverRenderingEnabled is set and it is bigger on screen than 50
(open top), or 75 (100 in view mode 3) with a roof. It uses LOD 1 close
up and LOD 2 otherwise, and needs to be closer when seen from behind:
bigger than 999 (300 with an animation queued), against 300 (150) from
anywhere else. The driver sits at the car type's DriverRenderingOffset.
OverrideAnimatedDriverLOD draws LOD 2 at 1.

The drivers' LOD 2 solids have no tree, so they are plain models: the
chase camera, which sees every car from behind, draws them unposed, and
only the close-ups pose a driver. R/C Car's ForceRenderDriver and
OverrideAnimatedDriverLOD pose every driver on screen. In Azahar on track
42 that is 4 a frame near the start, with no room lost in the skin ring.
