# collisionsound -- the crashes and scrapes

A car that hits a wall, a lamp post or another car makes a
[Collision](collision.md). Each collision asks for a crash sample once it
is a tenth of a second old, and each scrape it reports starts a looping
scrape on a wall. When the collision ends, what is still playing finishes
on a free list. The one-shots go through [sound3d](sound3d.md)'s
sound3d_oneshot: a smokeable knocked over, a car's glass, a busted
roadblock and an explosion.

Retail has all of it in CollisionSounds.obj, `0x001e4658` .. `0x001e5e58`.
The port has it in `collisionsound.{c,h}`, and
`tools/collisionsound_check.py` runs retail's code against it.

| function | retail |
|---|---|
| GetCollisionSoundType | `0x001e4658` |
| CollisionSounds Register / LoadSampleTable / UnRegister | `0x001e4740` / `0x001e47a8` / `0x001e4a78` |
| CalcCollisionScrapeVolume / GetDistanceToCamera / CalcCollisionVolume | `0x001e4b08` / `0x001e4b58` / `0x001e4c28` |
| CalcCollisionAzimuth (returns 0) | `0x001e4cc0` |
| StartScraping / UpdateSample | `0x001e4cc8` / `0x001e4e00` |
| CollisionSounds Update / Mute | `0x001e4ea8` / `0x001e5018` |
| collision_sound Register / UnRegister / Update / Mute (jumps) | `0x001e51a8` .. `0x001e51c0` |
| Reset | `0x001e51c8` |
| CreateSample / ReleaseSample | `0x001e5278` / `0x001e53b0` |
| PlayFoilage / PlayGenericSmokable / PlaySmokeable | `0x001e5470` / `0x001e5508` / `0x001e55a8` |
| PlayGlass / PlayBustRoadBlock / PlayExplosion / PlayScrape | `0x001e5660` / `0x001e5688` / `0x001e56f0` / `0x001e57d0` |
| the static destructor / constructor | `0x001e5d88` / `0x001e5d98` |
| CollisionSample Initialize / ~CollisionSample / delete | `0x001e5da8` / `0x001e5db0` / `0x001e5e50` |

## The records

**CollisionSample** is 196 bytes: a bSample (188 bytes, its vptr at 184
holding CollisionSample's table), then the node of the free list at 188.
The port's bSample is 184 bytes with no vptr (see [bsound](bsound.md)),
so the port's `_vtable` word after it lands at 184 as well. Every sample
comes from a slot pool, "CollisionSampleSounds": 40 slots of 196, flags
16. Initialize copies the bSample it is given. The table has one slot:

| slot | CollisionSample (`0x002b9410`) |
|---|---|
| 8 | ~CollisionSample: the vptr back, Stop, the node's and bSample's destructors, and with flags & 1 the slot back to the pool |

Every delete goes through slot 8 with flags 3. The port registers the
table with `collisionsound_install_vtables` at boot.

**SampleLibrary<3>** is 16 bytes: three bSample pointers and
CurrSampleIndex at 12. Its GetSample steps the index, (index + 1) % 3,
and returns that sample, so a library plays its three in turn.

## The globals

| global | retail | what |
|---|---|---|
| CollisionFoilageSamples | `0x0031a778` | "CrashFoilage01" .. "03" |
| CollisionWoodSamples | `0x0031a788` | "CrashWood01" .. "03" |
| CollisionMetalSamples[3] | `0x0031a798` | small, medium and hard: "CrashMetalSmall", "CrashMetalMedium", "CrashMetalHard", each 01 .. 03 |
| MetalScraping / WoodScraping / GlassBreaking | gp-17240 / -17244 / -17248 | "CrashMetalScrape", "CrashWoodScrape", "CrashGlass01" |
| RegionsLoaded | gp-17236 | the table is in |
| SampleTableLoaded | gp-17264 | 1 in the image; LoadSampleTable sets it, nothing reads it |
| PetrolPumpNameHash / GasPumpNameHash | gp-17272 / -17268 | bStringHash of "CS_PetrolPump" and "CS_GasPump" |
| FreeSampleList | gp-17280 | a bTList of CollisionSamples, at itself from the static constructor |
| the pool | gp-17288 | "CollisionSampleSounds" |

All the samples are the "InGame" region's, each in category 0.

## CollisionSounds

**Register** clears RegionsLoaded, makes the pool if there is none, and
hashes the two pump names if the petrol pump's hash is 0. **UnRegister**
clears RegionsLoaded, deletes every sample on the free list, and deletes
the pool. **LoadSampleTable** sets SampleTableLoaded and loads the
libraries in the order metal small, medium, hard, wood, foliage. Each
name is the stem with "01", its last character set to 1, 2 and 3 in
turn, and each library's index goes back to 0. Then it loads the three
single samples.

**GetCollisionSoundType** takes the wood library for terrain 15 or 16
(wood and cactus walls). Otherwise the impulse picks the metal library:
trunc(TotalImpulseMagnitude x 1/30 x 3), clamped to 0 .. 2. Either way
it is that library's next sample, which can be NULL.

**GetDistanceToCamera** is the distance to view 1's camera, or with two
players or more the nearer of views 1 and 2. VU0 sums the squares as
(x x x + y x y) + z x z.

**CalcCollisionVolume** is 0 at 35 or more from the camera. Nearer, it
is min(TotalImpulseMagnitude x 1/30 x 0.65, 1) x min(35 / d, 1). The
second factor is always 1 inside 35, but retail computes it, on the EE's
divide. **CalcCollisionScrapeVolume** is min(that x CurrentScrapeSpeed x
1/6, 1).

A collision's age is (int)(WorldTimer - CollisionTime) x 0.00025
seconds, signed, so a collision from the future is young.

**StartScraping** waits until the collision is 0.1 s old. A wood or
cactus wall (15, 16) takes WoodScraping, a solid wall (17)
MetalScraping, and any other terrain nothing. Then a pool sample copies
it and becomes the collision's Scrape, and the scrape volume is taken.
With sound on it is set to ComputeAzimuth(CurrentContactPoint), played
at the volume x 1.9, and pitched by a random float below 0.36, less
0.18. With sound off it is made and kept silent.

**UpdateSample**, for a collision with a scrape, sets its volume to
Sound3d's ComputeVolume(CurrentContactPoint, 200) x the scrape volume x
1.9, then its azimuth.

**Update** does nothing without a world. Once the regions have loaded it
sets RegionsLoaded and loads the table. It deletes each free-list sample
that has stopped or is at 0.05 or less. Then for each collision on the
world's list it updates the scrape, if there is one, and asks
CreateSample for a sample if the collision has none.

**Mute** pauses or resumes, in order: both scrapes; each collision's
Sample and Scrape; every sample on the free list; and each wood and
foliage sample that is playing. The metal libraries are left alone.

## collision_sound

Register, UnRegister, Update and Mute jump to CollisionSounds'.
**Reset** deletes every sample on the free list.

**CreateSample(collision)** returns NULL if the collision is under 0.1 s
old, if its type has no sample, or unless its volume is over 0.2.
Otherwise a pool sample copies the type. With sound on it plays at the
volume x 1.9 at a pitch of a random float below 0.6, plus 0.5, less 1,
and then takes the contact point's azimuth. The sample is returned with
sound on or off.

**ReleaseSample(collision)**: a Sample still playing goes on the head of
the free list, and one that has stopped is deleted. A Scrape still
playing fades to 0 over 50 ms and goes on the head too. A Scrape that
has stopped is left alone: its slot comes back only when UnRegister
deletes the pool.

**The one-shots**, each only with sound on except PlayBustRoadBlock:

| call | what plays | volume | pitch |
|---|---|---|---|
| PlayFoilage | the foliage library's next | 1.9 | random(0.6) + 0.5 |
| PlayGenericSmokable | the wood library's next | 2.5 | random(0.6) + 0.5 |
| PlayGlass | GlassBreaking | 1.9 | 1 |
| PlayBustRoadBlock | "FinishLine", in no category (0xffffffff) | 1 | 0.5 |
| PlayExplosion | "Bomb" twice, each heard to 300 at up to 6 | 1 | random(0.6) + 0.5 |

**PlaySmokeable(pos, info)** plays the foliage for a plant (terrain 28)
and the generic crash otherwise, NULL info included. Then for a petrol or
gas pump it plays the explosion and "PreviewZone" at 1.9, pitch 1.

PlayBustRoadBlock first asks bSound for category 0's volume and drops
the answer, and tests the one-shot before it sets the category.
PlayExplosion does not test either one-shot before it writes the
envelope: MaxVolAtSource 6, CutOffDistance 300, Coeff 1/300.

**PlayScrape** starts a scrape with sound on, if the collision has none.

## Who calls it

- sound.c's collision_register, collision_unregister, collision_update
  and collision_mute hooks: main.c's gSoundHooks.
- collision.c's three seams: CreateSample, ReleaseSample and PlayScrape.
- racecoord.c's gCollisionSoundResetFn: Reset.
- pursuit.c's and playernis.c's gCollisionSoundPlayBustRoadBlockFn.
- PlaySmokeable (Smokeable::ConsiderImpulse, SmokeBomb::Move), PlayGlass
  (the car's glass, `0x001b5a08`) and PlayExplosion (Munition) have no
  ported caller yet; they are exported for when those land.

## What the port changes

- **The bSample is 4 bytes shorter**, as noted above.
- **Mute tests the world.** Retail walks pCurrentWorld's collisions
  without a test. The port skips them when there is no world.
- **No static destructor.** Retail's deletes what is left on the free
  list at exit. The 3DS port does not run C++ static destructors.

## The check

`tools/collisionsound_check.py` runs retail's CollisionSounds.obj in
mipsemu, with the EE's divide, product and root. bStrCat, bStrLen,
bStringHash, memset, bNode's destructor and the static constructor run
in the image. The harness `tools/src/collisionsound_test.c` runs the
port's code through the port's table. Both sides use the same printing
fakes of:

- bSample's constructor, destructor, copy, category, play, stop, pause,
  volume, pitch, azimuth, playing flag, GetVolume and Fade;
- bSound's category volume, the in-game samples, sound's random float
  and IsSoundRegionLoadingComplete;
- Sound3d's ComputeVolume and ComputeAzimuth, and sound3d_oneshot's two
  Plays;
- the slot pool (with the slot size checked against retail's 196),
  eGetView and Collision's GetTerrainType.

The script covers every function above: each terrain and impulse bound;
the distance to one camera and two, either nearer, for each count of
players; the volumes at and past 35 and each cap; scrapes and samples
young, old and from the future, quiet, at the 0.2 bound, with sound off
and with a sample missing; each mix of a playing and a stopped Sample
and Scrape released; Update's free list through each of its tests; Mute
with the libraries playing and missing; Reset, UnRegister twice and
Register again; and each one-shot with sound on and off, each smokeable
kind and pump, and a missing one-shot.

It matches retail: 633 ops, 1630 lines, 0 differ.

`--mutate` runs 153 mutations of collisionsound.c out of the tree, in
parallel. All 153 are caught.
