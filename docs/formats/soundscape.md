# soundscape -- the track's own sounds

Every track bundle but TRACKA12 carries a sound scape: a 0x80038000 chunk
of reverb areas, looping ambients and one-shot ambients, each over a
SoundArea of ground-plane triangles.

- **Reverb areas** are the tunnels and bridges. While a player's car is
  in one with road above it, the SPU2's reverb is turned up.
- **Looping ambients** are sounds like a campfire, a stream or a log mill.
  Each plays while a camera is in its area and fades in and out. With a
  sound source it is panned towards the source. When the source lies
  inside the area, the ambient is a sound sphere instead, whose volume
  falls off with the cameras' distance from the source.
- **One-shot ambients** are the birds. Each plays on entering its area,
  then every Repeat seconds, give or take, at a varied pitch and azimuth.

Retail has it in SoundScape.obj, `0x001cdde0` .. `0x001cff20`. The port
has it in `soundscape.{c,h}`, and `tools/soundscape_check.py` runs
retail's code against it, together with [choppersound](choppersound.md).

| function | retail |
|---|---|
| SoundArea Initialize / IsPointInArea / AreCamerasInArea | `0x001cdde0` / `0x001cde20` / `0x001cdf30` |
| ReverbArea Initialize | `0x001cdfd0` |
| LoopingAmbient Initialize / ComputeAzimuth | `0x001ce078` / `0x001ce218` |
| LoopingAmbient UpdateUsingArea / UpdateUsingSoundSphere / Update / Mute | `0x001ce2d8` / `0x001ce478` / `0x001ce6b0` / `0x001ce780` |
| OneShotAmbient Initialize / Play / Update / Mute | `0x001ce7a0` / `0x001ce7f8` / `0x001ce9e0` / `0x001ceb20` |
| SoundScape WillSoundRight / FindGoodReverbArea | `0x001ceb40` / `0x001ceb88` |
| sound_scape Update / Mute (jumps) | `0x001cebf0` / `0x001cebf8` |
| SoundScape Update / Mute | `0x001cec00` / `0x001cec38` |
| SetReverbVolume / IsInsideReverbArea / UpdateReverbAreas | `0x001ced40` / `0x001ced88` / `0x001cee60` |
| GetActiveCameras | `0x001cf268` |
| UpdateLoopingAmbient / UpdateOneShotAmbient | `0x001cf478` / `0x001cf4e8` |
| SoundScapeIsInsideTunnel | `0x001cf698` |
| LoaderSoundScape / UnloaderSoundScape | `0x001cf6a8` / `0x001cf838` |
| the static constructor | `0x001cfe98` |

GetActiveCameras is the port's `get_active_cameras` in sound3d.c.

## The chunk

The container is 0x80038000. Each child has the usual 8-byte header, a
type and a size, and the loader steps from one to the next by 8 + size.
Offsets below are from the child's header.

| child | at | what |
|---|---|---|
| 0x00038010, a reverb area | 8 | name, 32 bytes |
| | 40 | Reverb, an int |
| | 44 | the area |
| | then | NumSounds, then that many 40-byte sounds: a sample name of 32 bytes, Period, PeriodError |
| 0x00038020, a looping ambient | 8 | name, 32 bytes |
| | 40 | sample name, 32 bytes |
| | 72, 76 | the fade in and the fade out, seconds |
| | 80 | HasSoundSource, an int |
| | 84, 88 | the sound source, x and y |
| | 92 | SoundSourceDistanceCoeff |
| | 96 | the area |
| 0x00038030, a one-shot ambient | 8 | name, 32 bytes |
| | 40 | sample name, 32 bytes |
| | 72 .. 88 | Repeat, RepeatDeviation, Pitch, PitchDeviation, AzimuthDeviation |
| | 92 | the area |

An area is NumAreaVerts, that many (x, y) float pairs, NumAreaFaces, and
that many faces of three int vertex indices. The records keep pointers
into the chunk for the names and the area. Any other child is skipped.

The retail tracks have at most 18 reverb areas, 19 looping ambients and
43 one-shot ambients. None of their reverb areas has more than one sound.

## The records

| record | retail size | port |
|---|---|---|
| SoundArea | 16 | NumAreaVerts, AreaVerts, NumAreaFaces, AreaFaces |
| SoundDesc | 12 | a sample name, Period, PeriodError; nothing reads one |
| ReverbArea | 124 | Name, Reverb, the area, NumSounds, eight SoundDescs |
| LoopingAmbient | 64 | the names, the fades in ms, IsActive, HasSoundSource, UseSoundSphere, Sample, the area, the source, the coefficient, SoundSphereRadius |
| OneShotAmbient | 244 | the names, Repeat and the deviations, Pitch, IsActive, UpdateOneShotTime, Sample, Sample360Azimuth (a bSample), the area |

The arrays are 32 reverb areas (`0x00317c80`), 32 looping ambients
(`0x00314688`) and 48 one-shot ambients (`0x00314e88`).

## The globals

| global | retail | what |
|---|---|---|
| SoundScapeDataJustLoaded | gp-18088 | set by the loader; the next search clears it |
| SoundScapeNumReverbAreas | gp-18084 | |
| SoundScapeCurrentlyActiveReverbArea | gp-18080 | -1 for none |
| SoundScapeReverbOn | gp-18076 | |
| SoundScapeRain | gp-18072 | only UpdateWeather would set it, and nothing calls that |
| SoundScapeReverbVolume / TargetReverbVolume / ReverbPan | gp-18068 / -18064 / -18060 | |
| SoundScapeNumLoopingAmbient / NumOneShotAmbient | gp-17996 / -18000 | |
| ReverbMode, Delay, Feedback, Level, Depth, each with a Desired twin | gp-18056 .. -18020 | 2 (medium), .65, 1, .85, .75 |
| ReverbModeTable | `0x00317c48` | 0 .. 7, then 0x65 .. 0x69 |

Nothing writes a desired reverb value, so in retail UpdateReverbAreas
never sends a mode or a parameter.

## SoundArea

**IsPointInArea** asks eIsPointInPoly of each face, as a triangle, and
says yes at the first that holds the point. **AreCamerasInArea** takes
the two cameras. It puts each one that is set and whose (x, y) is in the
area in a static pair, and returns the pair with the count.

## The reverb

**WillSoundRight(i, car)** is 0 when i is past the last area. Otherwise
it says whether the car's (x, y) is in area i. **FindGoodReverbArea** is
the first area the car is in, or -1.

**SetReverbVolume(v, car)**: with fewer than two player cars, v becomes
the target. With two, the car's BaseCarSound has its road noise scaled
by 1 + v, if the car and its sound are both there.

**IsInsideReverbArea(cars)** searches when no area is active, when data
has just loaded (which it clears), when car 0 has left the active area,
or when car 1 is set and has left it. The car-1 case marks the area as
the second car's. A search takes car 0's first area. When car 0 is in
none and car 1 is set, it takes car 1's instead, again as the second
car's. The result is the active area. The call returns 1 when the area
is the second car's.

**UpdateReverbAreas** first moves the volume towards the target. The
step is up to 0.333 when rising and 0.05 when falling. A change goes to
the effect volume, with the pan. Then come the mode and parameter
changes. A mode change zeroes the reverb volume through
SetReverbVolume(0, NULL), sends the mode through ReverbModeTable and
turns the reverb off. Each parameter goes as 1 (delay), 2 (feedback),
3 (level) or 4 (depth), on core 0.

Then, if either player is set, it finds the active area. With none
active, a reverb that is on is turned off: SetReverbVolume(0) for each
car, then the flag. With an area, the car is the one the area belongs
to. Three elevations are taken at its (x, y):

- here, at the car's own height;
- top, from 99999;
- under, from top - 2.

There is road over the car when here < top or here <= under. When the
reverb is off and there is road over the car, the pan goes to 0 and
SetReverbVolume(0.85, car) turns it on. When it is on and there is none,
SetReverbVolume(0, car) turns it off.

**SoundScapeIsInsideTunnel** says whether an area is active.
[choppersound](choppersound.md) fades on it.

## LoopingAmbient

**Initialize** reads the fades as whole milliseconds, trunc(s x 1000),
and starts the ambient inactive with no sample. With a sound source
inside its own area it uses the sound sphere, whose radius is the
distance to the farthest vertex.

**ComputeAzimuth(camera)** gives a BAM for where the source lies from
the camera. With d the unit vector from the camera to the source and h
the camera's heading, it is 16384 - bASin(d . h). It is negated (mod
65536) when -d.y x h.x + d.x x h.y < 0.

**Update** first makes the sample if there is none. With the track's
SoundRegion loaded and the sample in it, it takes a copy from bSample's
pool, in category 0. With no sample it does nothing. Then it updates by
the sphere or by the area.

**UpdateUsingArea**:

- **Active, with cameras in the area.** With a source, the sample takes
  the mean of their azimuths. Without a source, nothing changes.
- **Active, with none.** It stops, or fades to 0 over the fade-out, and
  goes inactive.
- **Inactive, with cameras.** It goes active. With sound on it plays at
  0.84, or with a fade-in it plays at 0 and fades to 0.84.
- **Inactive, with none.** A sample still playing at volume 0 is
  stopped.

**UpdateUsingSoundSphere** takes the cameras whose ground distance to
the source is under the radius. With any, the distance is their mean,
and the volume is 2 x (1 - sqrt(2d/r - (d/r)^2)): 2 at the source and 0
at the radius. A sample already playing takes that volume. One that is
not plays at it, with sound on. Either way it takes the cameras' mean
azimuth. With no camera inside, a playing sample is stopped.

**Mute** pauses or resumes the sample.

## OneShotAmbient

**Update** first takes the region's sample if there is none: the
region's own sample, not a copy, in category 0. With AzimuthDeviation
360, Sample360Azimuth copies it, also in category 0. Without the region
or the sample it does nothing. Then:

- **Active, with no camera in the area.** It goes inactive.
- **Active, still with cameras and repeating.** The time runs down by
  the frame's, and it plays again once the time is below 0.
- **Inactive, with cameras.** It plays and goes active.

**Play** starts at Pitch. With a PitchDeviation the pitch moves by a
random float below the deviation, less half of it. The azimuth is
16384 for a deviation of 360, a random int below 0x10000 for any other
deviation that is not 0, and 0 otherwise. With sound on it plays at
0.84 with that azimuth and pitch. For 360, Sample360Azimuth also plays,
at 0xc000. With a Repeat over 0, the next time is Repeat, varied the
same way by RepeatDeviation.

**Mute** pauses or resumes the sample.

## Update and Mute

**Update** does nothing without a race coordinator. Otherwise it runs
UpdateReverbAreas, then each looping ambient's Update, then each
one-shot's, all with GetActiveCameras.

**Mute(on)** pauses or resumes every ambient. A rain sample that is
playing is muted too. Muting also sets the effect volume and pan to 0,
turns the reverb off and leaves no area active.

The static constructor constructs the 48 Sample360Azimuth bSamples.

## The loader and the unloader

The **loader** takes only 0x80038000. It sets DataJustLoaded and leaves
no area active. It sets all three counts to 0 and initializes a record
for each child of the three types. It returns 1.

The **unloader** takes only 0x80038000. It leaves no area active, sets
the reverb and one-shot counts to 0 and clears the rain. Each looping
ambient's sample is stopped and deleted, through bSample's delete with
flags 3. The pointers are left: the next load starts each record over.
The looping count goes to 0 last.

## Who calls it

- bchunkload's slot 21: the loader and the unloader.
- main.c's sound hooks: sound_scape Update and Mute, for sound::Update
  and the mutes. soundscape_init runs once at boot.
- [choppersound](choppersound.md): SoundScapeIsInsideTunnel.

## What the port changes

- **No reverb unit.** The 3DS's bsnd has none. bDriver's
  PlatSetEffectVolume and bEffect's SetMode and SetParameter go through
  three seams, gSoundScapeEffectVolumeFn, ModeFn and ParameterFn. The
  port leaves them NULL, which skips the calls. The reverb areas still
  decide SoundScapeIsInsideTunnel.
- **The bSample is 4 bytes shorter** (see [bsound](bsound.md)), so the
  port's OneShotAmbient is 240 bytes.
- **The loader caps each count** at its array, 32, 32 and 48. Retail
  tests none of them.
- **No track, no region.** Retail reads CurrentTrackInfo's SoundRegion
  with no test. The port finds no region without a track.

## The check

`tools/soundscape_check.py` runs retail's SoundScape.obj and
ChopperSound.obj in mipsemu, with the EE's divide and root. The harness
`tools/src/soundscape_test.c` runs the port's code. Both sides use the
same printing fakes of:

- bSample's constructor, copy, category, play, stop, pause, mute,
  azimuth, volume, pitch, playing flag, GetVolume, Fade and delete
  (retail's through the vptr);
- bSound's region, the region's samples, and bDriver's and bEffect's
  three reverb calls;
- sound's random float and int and the in-game sample;
- GetActiveCameras, Topology's elevation and BaseCarSound's
  ScaleRoadNoise;
- for the chopper, Sound3d's constructor, Update and destructor, and
  bMalloc.

The script covers:

- the wrong type and an empty container, an unknown child, and a last
  record of size 0;
- the points and camera pairs for the areas, and ComputeAzimuth on each
  side and on the line;
- the looping ambients through every branch: no source, a source, the
  sphere, each fade, a missing region or sample, and sound off;
- the one-shots at each deviation, once and repeating, with the time
  reaching exactly 0;
- WillSoundRight past the count, each search of IsInsideReverbArea
  (overlapping areas included), and SetReverbVolume with one player and
  two;
- the smoothing, every mode and parameter, and the reverb under each
  order of elevations;
- Update, Mute, the tunnel test, unloading and loading again;
- every distinct retail track's chunk, loaded and dumped, with four
  tracks walked;
- the chopper's sound (see [choppersound](choppersound.md)).

It matches retail: 4854 ops, 21476 lines, 0 differ.

`--mutate` runs 342 mutations: 270 of soundscape.c and 72 of
choppersound.c. 338 are caught and 4 are equivalent:

- **region-null** removes the port's track test, which retail does not
  have.
- **c-ctor-null** drops ChopperSound's NULL, and both sides' fresh
  records already hold 0 there.
- **iira-m1** only reads area -1, which has no faces.
- **c-mute-on**: bsample_pause takes a bool.

`tools/loadertable_check.py` covers slot 21 as well. The two are called
on a chunk of one empty reverb area, and the area count is checked after
each.
