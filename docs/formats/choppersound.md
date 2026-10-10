# choppersound -- the helicopter's rotor

The police helicopter's rotor is a [Sound3d](sound3d.md) over the in-game
region's "ChopperEngine". It is placed at the chopper's CurrentPos and
takes its volume, Doppler pitch and azimuth from Sound3d. Under a reverb
area, a tunnel by [soundscape](soundscape.md)'s SoundScapeIsInsideTunnel,
it fades out over a second, and back in once the camera's car is clear.

Retail has it in ChopperSound.obj, `0x00214d68` .. `0x002150d8`. The port
has it in `choppersound.{c,h}`, and `tools/soundscape_check.py` runs
retail's code against it.

| function | retail |
|---|---|
| ChopperSound / ~ChopperSound | `0x00214d68` / `0x00214df0` |
| AdjustForTunnelVolume | `0x00214e08` |
| Update / Mute / DeactivateSound / ActivateSound | `0x00214f30` / `0x00215000` / `0x00215028` / `0x00215050` |
| sound::CreateChopperSound | `0x00215098` |
| the static constructor | `0x00215598` |

## The record

**ChopperSound** is 48 bytes:

| at | what |
|---|---|
| 0 | the Sound3d, 32 bytes, its vptr at 28 |
| 32 | pChopper |
| 36 | pChopperSample, the region's own bSample, shared and never deleted |
| 40 | InSideTunnel |
| 44 | TunnelFadeCounter |

Its table, `_vt$12ChopperSound` at `0x002bc2a8`, is chopper.h's
CHOPPERSOUND_VTABLE:

| slot | function |
|---|---|
| 8 | ~ChopperSound |
| 16 | Sound3d's Activate (`0x00208b28`) |
| 24 | Update |
| 32 | Mute |
| 40 | DeactivateSound |
| 48 | ActivateSound |
| 56 | Sound3d's UpdateCamRelativeDistAndVelocity (`0x00208c78`) |

The port registers it with `choppersound_install_vtables` at boot.

**ChopperSoundEnvelope** (`0x0031be30`), from the static constructor:
MaxVolAtSource 5, CutOffDistance 200, Coeff 0.005.

## The functions

**The constructor** runs Sound3d's, sets pChopper and the table. With
sound on it takes the in-game sample "ChopperEngine", sets category 0,
and stops the sample if it is playing. It starts out of the tunnel with
the counter at 0. **The destructor** puts the table back and runs
Sound3d's with the same flags.

**AdjustForTunnelVolume(volume)**:

- **Going in.** The counter starts at 1.
- **Inside.** The counter runs down by the frame's time while it is
  over 0, and the volume is scaled by it, kept at 0 or over. Once the
  counter has run out, the volume is 0.
- **Coming out.** With the counter run out, it goes back to 1 and the
  volume is 0. Otherwise the volume is scaled by the counter, which
  then flips to 1 - counter.
- **Outside.** While the counter is over 0 it runs down, and the volume
  is scaled by 1 - counter.

**Update(volume, azimuth, pitch)** ignores its arguments. It works only
with sound on, the sound activated and a sample. Sound3d's Update runs
at the chopper's CurrentPos with the envelope, then the tunnel adjusts
Sound3d's volume. A sample that is playing takes the volume, the
azimuth and the pitch less 1. One that is not plays at the volume, with
the azimuth as a float for its pan, and the pitch less 1.

**Mute(on)** pauses the sample with on != 0. **DeactivateSound** stops
it. **ActivateSound** plays it as Update does. Each acts only with
sound on and a sample.

**CreateChopperSound(chopper)** is bMalloc(48, "ChopperSound", 0, 16)
and the constructor.

## Who calls it

- main.c sets chopper.h's gCreateChopperSoundFn to choppersound_create.
  Chopper's constructor calls it.
- chopper.c, through the table: Activate, Update (from UpdateSound, with
  1, 0, 1), Mute, and the destructor with flags 3. sound.c calls
  Chopper's UpdateSound and Mute only while there is a helicopter.

## What the port changes

- **The sample is NULL with sound off.** Retail leaves it unwritten.
  Retail's constructor also asks IsPlaying of a missing sample. The
  port does not, because bsample_is_playing would read through NULL.
- **The bSample is 4 bytes shorter** (see [bsound](bsound.md)). The
  record holds only a pointer to it, so its layout is unchanged.

## The check

`tools/soundscape_check.py` runs ChopperSound.obj with SoundScape.obj
(see [soundscape](soundscape.md)), with Sound3d's constructor, Update
and destructor, the in-game sample and bMalloc as printing fakes. The
table is dumped on both sides. The script covers:

- CreateChopperSound, and the constructor with sound on and off, with
  the sample playing and missing;
- the destructor, over a changed table;
- AdjustForTunnelVolume through every branch, with the counter over,
  at and under 0;
- Update playing and not, in and out of a tunnel, with sound off,
  deactivated and with no sample, at azimuths up to 32768;
- Mute with 0, 1 and 5, DeactivateSound and ActivateSound, with sound
  on and off.

The 72 mutations of choppersound.c are among the 342 of
`soundscape_check.py --mutate`. 70 are caught, and two are equivalent:

- **c-ctor-null**: the constructor's NULL, since both sides' fresh
  records already hold 0 there.
- **c-mute-on**: `on` for `on != 0`, since bsample_pause takes a bool.
