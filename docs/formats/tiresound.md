# tiresound -- the sound a car's tyres make

Every car with sound has tyres. Its [BaseCarSound](carsound.md) makes
them through the two factories and keeps them as its TireSound. A player
car gets two, one for each side (0 and 1). With two players it gets only
side 0. An AI car gets one, for all four wheels. Each is a
[Sound3d](sound3d.md), and the car sound updates it each sound frame with
its volume, azimuth and Doppler pitch.

- **The player's tyres** make the full set of sounds:
  - road noise, or gravel noise, by the terrain under the wheels;
  - a skid and a squall, from the wheels' slip and traction;
  - the burn-out peel;
  - leaves under the wheels on the autumn tracks;
  - one-shots on metal grates and in potholes;
  - a flop when a wheel lands, and a bottom-out when it lands hard;
  - with a tyre blown, the thump of the rim and its scrape.
- **An AI car's tyres** have only the skid, on road or on dirt, and the
  flop.

Retail has all of it in CarSoundTires.obj, `0x002124d8` .. `0x00214d68`.
The port has it in `tiresound.{c,h}`, and `tools/tiresound_check.py` runs
retail's code against it.

| function | retail |
|---|---|
| BaseTireSound() / ~BaseTireSound / Mute | `0x002124f0` / `0x00214a78` / `0x002125a0` |
| UpdateTireImpact | `0x002125e0` |
| BaseTireSound TriggerTireBlowOut / ScaleRoadNoise (do nothing) | `0x00214a70` / `0x00214a68` |
| TerrainOneShot Init / ~TerrainOneShot / Mute / Update | `0x002127e0` / `0x00214a10` / `0x00212840` / `0x00212860` |
| PlayerTireSound() / ~PlayerTireSound | `0x00212950` / `0x00212cf0` |
| DeactivateSound / ActivateSound (do nothing) | `0x00212e88` / `0x00212e90` |
| SetSamplePitch | `0x00212e98` |
| CalcTireSquallVolumeAndPitch / CalcTireSkidVolumeAndPitch | `0x00212eb0` / `0x00212f80` |
| CalcTireNoiseVolume / CalcTireNoisePitch | `0x002131e0` / `0x002132a0` |
| CalcTireSquallVolume / CalcTireSquallPitch | `0x00213338` / `0x00213440` |
| Mute / Update | `0x002134d8` / `0x002135a0` |
| UpdateSquall / UpdateLeaves | `0x00213c30` / `0x00213dd8` |
| ResetThumperTime / UpdateThumperTires | `0x00213f40` / `0x00213f80` |
| TriggerTireBlowOut / ScaleRoadNoise | `0x00214a00` / `0x002149f8` |
| OpponentTireSound ActivateSound (does nothing) / DeactivateSound | `0x00214890` / `0x00214898` |
| OpponentTireSound Mute / Update / ~OpponentTireSound | `0x002148e0` / `0x00214928` / `0x002149a0` |
| UpdateSkids | `0x00214ad8` |
| tire_sound::CreatePlayerTire / CreateAITire | `0x002141f8` / `0x00214250` |
| tire_sound::TriggerTireBlowOut / ScaleRoadNoise | `0x00214338` / `0x00214360` |
| the static constructor | `0x00214878` |

The module also uses the float templates max, min, clamp and smooth, at
`0x001365e0` .. `0x00136630`. Their max and min are max.s and min.s with
the arguments the other way round. smooth moves a value at most a step
towards its target.

## The records

The bSample is 188 bytes in retail and 4 bytes shorter in the port (see
[bsound](bsound.md)). Everything after a bSample therefore sits earlier
in the port's records. The offsets below are retail's; `tiresound.h`
gives the port's beside them.

The demo's PlayerTireSound held TireFlop, BottomOut and the two touching
flags itself. Retail moved them into BaseTireSound, so that the AI's
tyres flop too. The names are the demo's.

**BaseTireSound** (412 bytes):

| offset | field | |
|---|---|---|
| 0 | the Sound3d | its vptr at 28 |
| 32, 34 | FrontTireTouching, RearTireTouching | u16 flags, 1 to start with |
| 36 | TireFlop | the in-game "TireFlop" |
| 224 | BottomOut | the in-game "BottomOut" |

**TerrainOneShot** (204 bytes):

| offset | field | |
|---|---|---|
| 0 | bFoundSample | |
| 4 | bOnTerrainType | it has played on this crossing |
| 8 | pTimeDelay | a shared delay, or NULL |
| 12 | TerrainSample | |
| 200 | Side | |

**PlayerTireSound** (2744 bytes):

| offset | field | |
|---|---|---|
| 0 | the BaseTireSound | |
| 412 | pCar | |
| 416 | LockedRearPitch | side 1's skid pitch, -1 when not held |
| 420, 424 | CurrSquallPitch, CurrSquallVolume | |
| 428 | Mode | 0, and nothing reads it |
| 432 | Side | |
| 436 | RoadNoiseScale | ScaleRoadNoise's, 1 to start with |
| 440 | PlayThumperSounds | |
| 444 | UpdateThumperTime | seconds to the next thump |
| 448 | PrevShouldMakeRoadNoise | the last on-road answer, kept through puddles |
| 452 | MetalBump | a TerrainOneShot, "MetalBump" |
| 656 | PotHole | a TerrainOneShot, "TireFlop" |
| 860 | FoundLeavesSample | |
| 864 | LeavesNoise | the track region's "Leaves" |
| 1052, 1240 | RoadNoise, DirtNoise | "RoadNoise", "GravelNoise" |
| 1428, 1616 | RoadSkid, DirtSkid | "LongitudinalSkid", "GravelSkid" |
| 1804, 1992 | Squall, DirtSquall | "SquallSkid", "GravelSkid" |
| 2180 | BurnOutPeel | "BurnOutPeel" |
| 2368 | Busted | "TireFlat", the thump |
| 2556 | BustedScrape | "CrashMetalScrape" |

**OpponentTireSound** (804 bytes):

| offset | field | |
|---|---|---|
| 0 | the BaseTireSound | |
| 412 | pCar | |
| 416, 604 | RoadSkid, DirtSkid | "LongitudinalSkid", "GravelSkid" |
| 792 | PrevSkid | the skid sample last used |
| 796, 800 | CurrSkidVolume, TargetSkidVolume | |

The globals:

| gp | name | |
|---|---|---|
| -16244 | PlayerTireSound::fOneShotTimeDelay | the one-shots' shared delay |
| -16232 | (no name; the port's TireNoisePitchScale) | 0.0065 |
| -13344 | (no name; the port's ThumperAzimuthOffset) | a u16, 8192 |

The image holds 0 for the thumper offset. The static constructor sets it
to 8192, an eighth of a turn.

## The tables

All three classes keep Sound3d's slots and add two. Every delta is 0.

| slot | Base (`0x002bc1e8`) | Player (`0x002bc198`) | AI (`0x002bc148`) |
|---|---|---|---|
| 8 | ~BaseTireSound | ~PlayerTireSound | ~OpponentTireSound |
| 16 | Sound3d::Activate | the same | the same |
| 24 | pure (Update) | Update | Update |
| 32 | Mute | Mute | Mute |
| 40 | pure (DeactivateSound) | DeactivateSound (does nothing) | DeactivateSound |
| 48 | pure (ActivateSound) | ActivateSound (does nothing) | ActivateSound (does nothing) |
| 56 | Sound3d's UpdateCamRelativeDistAndVelocity | the same | the same |
| 64 | TriggerTireBlowOut (does nothing) | TriggerTireBlowOut | the Base's |
| 72 | ScaleRoadNoise (does nothing) | ScaleRoadNoise | the Base's |

`tiresound_install_vtables` registers all three at boot.

## Which wheels a side means

A player's tyre has a Side, 0 or 1. Each function picks two wheels by it,
and retail's functions do not agree on which two:

| function | side 0 | side 1 | any other side |
|---|---|---|---|
| UpdateTireImpact | 1 (front), 3 (rear) | 0, 2 | none; -1 is all four |
| TerrainOneShot Update, UpdateLeaves | 0, 1 | 3, 2 | 3, 2 |
| CalcTireSkidVolumeAndPitch | 0, 1 | 2, 3 | 0, 1 |
| CalcTireNoiseVolume, CalcTireNoisePitch | 1, 2 | 0, 3 | none |
| CalcTireSquallVolume | 0, 3 | 1, 2 | 0, 0 |
| Update's terrain, UpdateThumperTires | 1, 2 | 0, 3 | 1, 2 |

Side 0 also adds 0.15 to several pitches, so its two sides sound
slightly apart.

## BaseTireSound

**The constructor** builds the Sound3d and both samples, and sets both
touching flags to 1. It copies "TireFlop" and "BottomOut" from the
in-game samples into category 1. **The destructor** destroys the samples
from the last to the first, then the Sound3d. **Mute** pauses or resumes
both samples.

**UpdateTireImpact(car, side)** watches a front wheel and a rear wheel.
For side -1 it watches the front pair and the rear pair: either wheel of
a pair on the ground counts. A side lands when its front or rear wheel is
on the ground and was not before. Then:

1. impact = (|Velocity.z| x 0.3 + |AngularVelocity.xy| x 0.8) x 0.5.
2. If sound, car sound and road noise are all on, the flop plays at
   min(impact, 1) x the Sound3d's volume, at the Sound3d's azimuth.
3. Past an impact of 0.9, with the same three switches on, the bottom-out
   also plays. Its pitch offset is a random float below 0.7, less 0.4.
   Its volume is impact x the Sound3d's volume x 0.8. A player's
   bottom-out has no category, so the impact is first scaled by the
   jukebox's saved volume for category 0.

It then stores the two flags as the wheels have them.

## TerrainOneShot

**Init(sample, delay, side)**: without a sample it only clears
bFoundSample. Otherwise it stores the delay and side, clears
bOnTerrainType, and copies the sample into category 1.

**Update(car, terrain, volume, azimuth, pitch)** reads the terrain each
of the side's two wheels has crossed this step. If neither crossed
`terrain`, it clears bOnTerrainType. If one did, it plays once on that
crossing: not while bOnTerrainType is set, nor while the shared delay is
above 0. Playing sets bOnTerrainType and the delay to 0.3 seconds. The
azimuth goes in as the pan, as retail has it.

## PlayerTireSound

**The constructor** builds everything and stores the car and side. It
copies the ten in-game samples into category 1, then sets the player's
bottom-out to no category (-1). It looks up "Leaves" in the track's sound
region. With no region, FoundLeavesSample is left as the heap gave it.
It initializes the two one-shots with the shared delay. If sound, car
sound and road noise are on, it starts the road noise at volume 0. It
then sets:

- PrevShouldMakeRoadNoise to 1 and the thumper time to 0;
- the squall volume to 0 and its pitch to 1;
- LockedRearPitch to -1 and RoadNoiseScale to 1.

Last, it turns the sound on.

**The destructor** stops all ten looping samples and flushes the sound
driver. It then destroys the samples from the last to the first, the two
one-shots, and the BaseTireSound.

**SetSamplePitch** sets a sample's pitch as an offset from 1, as bSample
takes it.

**The Calc functions**:

- **CalcTireSkidVolumeAndPitch**: each of the side's two wheels gives its
  slip's length if it is on the ground, counted as 0 below 0.25. t is the
  two wheels' mean.
  - Side 1 reads the rear pair. Below t = 0.01 it lets go of the held
    pitch and returns volume 0. Otherwise the volume is t x 0.3. The
    pitch is t x 0.06, clamped to 1 .. 1.2, worked out once and held
    until the skid stops.
  - Any other side reads the front pair. The volume is t x 0.4, and the
    pitch t x 0.07, clamped to 1 .. 1.25, each frame.
- **CalcTireNoiseVolume** is the mean of the two wheels' |spin| x
  0.0095, a wheel off the ground counting 0, capped at 1.
- **CalcTireNoisePitch** is 0.0065 x the faster wheel's |spin|, plus 0.15
  for side 0.
- **CalcTireSquallVolume** is 0 below 11 m/s. Otherwise m is the mean of
  the two wheels' |traction usage|. The volume is m x 1.975 past
  m = 0.7, capped at 1, so in practice it is 0 or 1.
- **CalcTireSquallPitch** is the speed x 0.01015, plus 0.15 for side 0.
  Retail also reads two wheels' traction usage here, and drops them.
- **CalcTireSquallVolumeAndPitch** stores the squall's pitch and eases
  CurrSquallVolume towards the squall's volume: up 0.075 a frame and
  down 0.15.

**Mute** mutes the base, the ten samples and both one-shots.

**Update(volume, azimuth, pitch)**, slot 24, does nothing while the sound
is off. Otherwise it stores the volume, pitch and azimuth, then:

1. **On road or not.** The side's two wheels are on road when the
   terrain under both makes road noise (TerrainTypeInfoTable's
   ShouldTireMakeRoadSound). A puddle under either keeps the last
   answer.
2. **Leaves and one-shots.** It runs UpdateLeaves at the noise volume x
   volume. It counts the shared delay down by the frame's time, while it
   is above 0. It runs the metal bump on metal grates at 1.3 x volume,
   and the pothole in potholes at 1.5 x volume and 0.8 x pitch.
3. **The thump.** With cobbles under the first wheel, boardwalk under the
   second, or a tyre blown, it runs UpdateThumperTires. Otherwise it
   resets the thumper time. NumBlownTires is a signed byte, so 128 or
   more counts as none.
4. **The flop**, from UpdateTireImpact on the side.
5. **The skid.** It takes CalcTireSkidVolumeAndPitch's volume and pitch.
   Off road, the pitch is 1 (1.15 for side 0). The volume is scaled by
   the volume and clamped to 0 .. 3.5 on road, 0 .. 2.75 off it. The
   skid for the terrain plays, and the other one stops.
6. **The squall**, from UpdateSquall.
7. **The burn-out.** The slip is the rear pair's mean slip.x plus the
   front pair's. On road, with the throttle over 0.2, that slip over 3
   and the car under 30 m/s, the peel plays. Its pitch offset is 0.15 on
   side 0. Its volume is min(slip / 16, 3) x volume. Otherwise the peel
   stops.
8. **The road noise or the gravel.** On road, the road noise takes the
   noise volume x RoadNoiseScale and the noise pitch, and the gravel
   stops. Retail restarts a stopped road noise only while the music
   (category 4) is silent; the constructor has started it already. It
   passes the azimuth as the pan. Off road, the gravel takes the same
   volume at the pitch plus 0.15 for side 0, and the road noise stops.
   Retail starts the gravel with that pitch offset as its pan and a pitch
   offset of 0; the next set gives it the pitch.

**UpdateSquall(onRoad, volume, azimuth, pitch)** plays the squall on road
or the gravel squall off it, and stops the other one. Its volume is
CurrSquallVolume x volume, and the sample's volume moves at most 0.05 a
frame towards it. The pitch passed in is not read.

**UpdateLeaves(volume, azimuth, pitch)**: with the leaves sample found
and autumn leaves, their shoulder, or the autumn road under either of
the side's wheels, it plays the leaves. A playing one gets its pitch as
given, not as an offset from 1, as retail has it. Otherwise it stops
them.

**ResetThumperTime** zeroes the thumper time and stops the scrape.

**UpdateThumperTires** counts the thumper time down. When it runs out:

- below 3 m/s it resets the time;
- otherwise, if one of the side's wheels is on the ground, the thump
  plays at the Sound3d's volume and pitch, if sound, car sound and car
  damage sound are on. Its azimuth is the Sound3d's plus the thumper
  offset (8192, an eighth of a turn) for side 0, or minus it for any
  other side. The next thump is 1.9 m further
  on, but at least 0.035 seconds away.

With a tyre blown, the car on road and a wheel touching, the scrape
plays. Its volume is the Sound3d's volume x speed x 0.04, and its pitch
the Sound3d's pitch x (speed x 0.004 + 1.4). Otherwise the scrape stops.

**TriggerTireBlowOut** sets PlayThumperSounds. Update overwrites it each
frame from the terrain and the blown tyres. **ScaleRoadNoise** stores the
scale.

## OpponentTireSound

**The constructor** is inline in CreateAITire. It builds the base and
both skids and stores the car. It copies "LongitudinalSkid" and
"GravelSkid" into category 0. PrevSkid starts at the road skid, both
skid volumes at 0, and the sound is turned on.

**Update(volume, azimuth, pitch)** does nothing while the sound is off.
Otherwise it stores the volume and azimuth, runs UpdateSkids, and runs
UpdateTireImpact on all four wheels at three quarters of the volume. The
pitch is not stored.

**UpdateSkids** works as follows:

1. It takes the worst slip of the four wheels, each counted as 0 off the
   ground or below 0.25.
2. The car is on dirt when fewer than two wheels are on terrain that
   makes road noise.
3. The target volume is 3.5 x volume on dirt and 5 x volume on road, or
   0 while the worst slip is under 10. The current volume moves at most
   0.35 a frame towards it.
4. The pitch offset is speed x 0.01015 + 0.3 - 1.
5. When the terrain changes, the other skid stops if it was playing.

**Mute** pauses both skids and the base's samples. **DeactivateSound**
stops both skids and PrevSkid.

## tire_sound

**CreatePlayerTire(car, side)** and **CreateAITire(car)** are carsound's
gCreatePlayerTireFn and gCreateAITireFn. Each makes its record with
bMalloc at alignment 16, under the tag "PlayerTireSound" or
"kAITireSound", and returns its Sound3d.

**TriggerTireBlowOut** and **ScaleRoadNoise** are carsound's
gTireSoundTriggerBlowOutFn and gTireSoundScaleRoadNoiseFn. Each calls
slot 64 or 72 on a tyre.

## What the port changes

- **The bSamples are 4 bytes shorter**, as noted above.
- **bSound's Flush does nothing.** Retail's sends the IOP the commands
  queued for it, so the stops reach the driver before the samples go.
  The 3DS driver queues nothing.
- **FoundLeavesSample without a region.** The port's bMalloc zeroes
  memory, so it stays 0 and the leaves never play. Retail would read
  whatever its heap held.

## The check

`tools/tiresound_check.py` runs retail's CarSoundTires.obj in mipsemu,
with the EE's divide, product and root. Sound3d's camera-relative update
runs in the image, and so do the templates and the static constructor.
The harness `tools/src/tiresound_test.c` runs the port's code through
the port's tables. Both sides use the same printing fakes of:

- bSample's constructor, copy, category, play, stop, pause, volume,
  pitch, azimuth and playing flag;
- bSound's regions, category volumes and flush, and the jukebox's saved
  volumes;
- the in-game samples, and sound's random float;
- bMalloc (0xa5-filled, with the size checked against retail's records)
  and delete.

The script, 5042 operations, covers every function above:

- each side, including -1, 2 and -2, and every wheel on and off the
  ground;
- each threshold either side, and exactly on it where the EE's rounding
  allows: the slip's 0.25, the squall's 11 m/s and 0.7, the
  bottom-out's 0.9, the burn-out's throttle, slip and speed, the thump's
  3 m/s and its 0.035 s floor;
- every cap and clamp, inside and past it;
- every terrain the tyres test, puddles kept and lost, and the shared
  delay running, out and exactly out;
- each switch off in turn, missing samples and no track region;
- the AI's skid switching terrain while it plays.

It matches retail: 13994 lines, 0 differ.

`--mutate` runs 447 mutations of tiresound.c and tiresound.h out of the
tree, in parallel. 445 are caught. The other two cannot change what
CalcTireSquallVolume returns: past m = 0.7 its volume is at least 1.38,
so neither a different scale nor a higher cap gets under the cap of 1.
