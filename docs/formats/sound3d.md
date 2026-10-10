# sound3d -- sounds with a place in the world

`Sound3d` is the base of every positional sound in the game: the car's
engine, horn and siren, the chopper and the one-shots. It works out how
far the closest camera is and how fast that distance is changing. From
that it gets a volume (an envelope), a pitch (Doppler) and an azimuth.
What it plays belongs to the derived class. `Sound3dSample` is a Sound3d
over one [bSample](bsound.md). `sound3d_oneshot` keeps a list of them:
sounds played once at a place, which delete themselves when they stop.

Retail has all three in Sound3d.obj, `0x00208ae8` .. `0x00209ea8`, with
SoundScape's GetActiveCameras (`0x001cf268`) beside them. The port has
them in `sound3d.{c,h}`, and `tools/sound3d_check.py` runs retail's code
against it.

| function | retail |
|---|---|
| GetActiveCameras (SoundScape) | `0x001cf268` |
| Sound3d::Sound3d | `0x00208ae8` |
| Sound3d::Activate | `0x00208b28` |
| GetDistToClosestCamera | `0x00208b98` |
| UpdateCamRelativeDistAndVelocity | `0x00208c78` |
| Sound3d::Update(bVector3 *, Sound3dEnvelope *) | `0x00208cf0` |
| ComputeAzimuth | `0x00208df8` |
| ComputeVolume | `0x00208f70` |
| AzimuthToPan / PanToAzimuth | `0x00208fe0` / `0x00209070` |
| GetAzimuth | `0x00209150` |
| Sound3d::~Sound3d | `0x002091a0` |
| sound3d_oneshot Init / Reset / Close | `0x002091d0` / `0x00209208` / `0x00209268` |
| sound3d_oneshot Update / Mute | `0x002092a0` / `0x00209320` |
| sound3d_oneshot Play by name / by sample | `0x00209388` / `0x002093d8` |
| Sound3dSample::Sound3dSample() / (bVector3 *, float) | `0x002094b0` / `0x00209530` |
| Sound3dSample::~Sound3dSample | `0x002095d0` |
| new / delete | `0x00209670` / `0x00209690` |
| UpdateAt / Update(float, unsigned short, float) | `0x002096a0` / `0x002096f8` |
| RemoveSample / SetDeleteWhenDone | `0x002097a8` / `0x002097e8` |
| the list's static constructor | `0x00209da8` |
| ActivateSound / DeactivateSound | `0x00209dc0` / `0x00209e18` |
| SetPosition / SetAzimuth / SetVolume / SetPitch / Mute | `0x00209e38` .. `0x00209e98` |

## The records

Sound3d is 32 bytes and holds no pointers, so it is the same record on
every target:

| offset | field | |
|---|---|---|
| 0 | Activated | a bool, a word wide in this compiler |
| 4 | DopplerIsActive | |
| 8 | Volume | |
| 12 | Pitch | |
| 16 | Azimuth | a BAM, `unsigned short` |
| 20 | SndToCameraVelocity | |
| 24 | SndToCameraDistance | |
| 28 | the vptr | g++ 2.9x puts it after the members |

Sound3dSample is 272 bytes in retail: a list node (0), the Sound3d (8,
so its vptr is at 36), the bSample (40), the envelope (228),
DeleteWhenDone (240, never written), PositionIsDefined (244) and the
position (256). The port's bSample has no vptr and is 4 bytes shorter,
so on the 3DS everything after it sits 4 bytes earlier.

The envelope is three floats: MaxVolAtSource, CutOffDistance and Coeff.
The volume at distance d is

    MaxVolAtSource * (1 - sqrt(2*d*Coeff - (d*Coeff)^2))

out to the cut-off, and 0 past it. With Coeff = 1 / CutOffDistance this
is a quarter circle, and both of Sound3dSample's constructors set it up
that way. The default one uses 1, 200 and 0.005. The placed one uses the
caller's volume, 135 and 1/135.

## The tables

`_vt$7Sound3d` is at `0x002bb2b0` and `_vt$13Sound3dSample` at
`0x002bb358`. Each slot is 8 bytes: a delta, then the function. The
slots are:

| slot | Sound3d | Sound3dSample |
|---|---|---|
| 8 | the destructor | its destructor, delta -8 |
| 16 | Activate | Sound3d's |
| 24 | `__pure_virtual` | Update(float, ushort, float), -8 |
| 32 | `__pure_virtual` | Mute, -8 |
| 40 | `__pure_virtual` | DeactivateSound, -8 |
| 48 | `__pure_virtual` | ActivateSound, -8 |
| 56 | UpdateCamRelativeDistAndVelocity | Sound3d's |
| 64 | | UpdateAt, delta 0 |

UpdateAt's delta is 0 because it is Sound3dSample's own virtual, called
on the Sound3dSample and not on its Sound3d. The port installs both
tables at boot with `sound3d_install_vtables`. Car::UpdateSound calls
slot 24 on a BaseCarSound, whose first base is Sound3d at offset 0.

## Sound3d

**Activate(on)** turns the sound off with DeactivateSound. Turning it on
calls ActivateSound, but only if it was not already on. Either way,
Activated becomes the argument as passed.

**GetActiveCameras** fills a static pair with each player's camera:
eGetView(i + 1)'s when PlayerPlayersByIndex[i] is set, NULL otherwise.
Retail has a fallback to view 1 for when no player is found. But the
count of players found is incremented in a branch delay slot, so it
grows for every slot and the fallback never runs. The port leaves the
fallback out.

**GetDistToClosestCamera** takes the shorter distance to the active
cameras. The search starts from 9e9. If no camera is closer than that,
it measures to view 1's camera instead.

**UpdateCamRelativeDistAndVelocity** divides the change in distance by
the frame's WorldTimeElapsed. It keeps the velocity only when it is
strictly within 80 either way, and it always keeps the distance. On a
frame with no time, the EE's divide gives FLT_MAX, which the clamp
throws out. The port uses `ee_div`, so the same happens on the 3DS.

**Update(pos, envelope)** calls slot 56 through the table. If Doppler is
on, it then sets the pitch to 1 - velocity / SpeedOfSound. SpeedOfSound
is 350, at gp-16480. Next comes the envelope's volume, clamped to at
most 1, or 1 with no envelope. Last comes the azimuth.

**ComputeAzimuth** has two cases:

- With two players or more, it returns CarSoundMultiPlayerAzimuth
  (gp-20464), negated when the first player's camera is the closer one
  in the ground plane. The variable is 0 on the disc and nothing writes
  it.
- Otherwise it works from view 1's camera. It normalizes the ground-plane
  vector to the sound, then takes 16384 minus the BAM asin of its dot
  product with the camera's heading. The sign of the cross product
  decides which side the sound is on. A sound directly above the camera
  divides 0 by 0, which the EE makes FLT_MAX.

**ComputeVolume(pos, cutOff)** builds a unit envelope out to cutOff on
the stack and returns its volume at the closest camera's distance.

**AzimuthToPan** maps the circle onto [-0.5, 0.5]. It splits the circle
into quarters at 16383 (not 16384), scales the remainder by 2^-14 and
halves the result. **PanToAzimuth** maps a pan back: negative pans go to
the last quarter (from 49152), positive pans to the first, and 0 to 0.

## Sound3dSample and the one-shots

Both constructors put the sample at the head of the one-shots' list
(gp-16456, an empty sentinel from the static constructor). The
destructor stops the bSample, unlinks the node, then destroys the
bSample and the Sound3d. With flags & 1, it gives the slot back to the
pool.

**Update(volume, azimuth, pitch)**: if sound is enabled and the sample is
active, it runs Sound3d's Update at the sample's position with its
envelope. It then scales the volume and pitch by the arguments and
passes on Sound3d's azimuth. The azimuth argument is never read. A
volume of exactly 0 stops the sample, whether or not sound is on.
**UpdateAt** first sets the position, then calls Update through the
table.

**SetDeleteWhenDone(on)** sets the bSample's callback to RemoveSample,
with the sample as its data. Off clears both. **RemoveSample** deletes
the sample through slot 8 with flags 3, on a stop event with data to
hand. **SetPitch** stores the pitch but passes pitch - 1 to the bSample,
whose pitch is an offset from 1. **Mute** pauses the bSample.

**sound3d_oneshot:**

- **Init** makes the pool, "Sound3dSampleSlotPool": 30 slots of 272
  bytes with flags 16. Only once.
- **Reset** clears each sample's callback and deletes it, until the list
  is empty.
- **Close** runs Reset, then deletes the pool.
- **Update** calls Update(1, 0, 1) on every sample that is not paused.
- **Mute** calls Mute on every sample.
- **Play(sample, pos, volume, pitch)** returns NULL with sound off.
  Otherwise it:
  1. takes a slot (operator new's result is not tested; the pool grows);
  2. builds the sample at pos with `volume` as the envelope's maximum;
  3. copies the bSample's patch and turns Doppler off;
  4. activates it, which starts it playing;
  5. sets it to delete when done;
  6. calls UpdateAt(pos, volume, 0, pitch) once.
- **Play by name** looks the sample up with GetInGameSample first. A
  name with no sample hands Play a NULL.

sound.c calls Init, Close, Update and Mute through its hooks, and
RaceCoordinator calls Reset as the race ends. The only callers of Play
are collision_sound's glass, foliage, smokeables, the roadblock bust
and the explosions (step 14-6).

## The check

`tools/sound3d_check.py` runs retail's Sound3d.obj in mipsemu, with the
EE's divide, product and root. The harness `tools/src/sound3d_test.c`
runs the port's code, and both sides use the same printing fakes of
bSample, the slot pool and the views. The script covers:

- the tables and the active cameras;
- distances, including the 9e9 fallback, and the velocity clamp;
- frames of no time;
- envelopes inside, at and past the cut-off;
- an azimuth sweep around two headings, the two-player azimuth, and
  azimuth to pan and back across every edge;
- every Sound3dSample method on its own;
- the one-shots from Init to Close.

Two cases are not run:

- ComputeAzimuth with three players, where retail reads past its pair of
  cameras;
- a sum of two FLT_MAX products, which is an infinity on the host and
  FLT_MAX on the EE.
