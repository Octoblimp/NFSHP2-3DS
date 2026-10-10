# enginesound -- the sound an engine makes

Every car with sound has an engine. Its [BaseCarSound](carsound.md)
makes it through the two factories and keeps it as its EngineSound. Both
kinds are [Sound3d](sound3d.md)s, and the car sound updates them each
sound frame with its volume, azimuth and Doppler pitch.

- **The player's engine** is EA's granular engine. It plays twelve
  patches from the car's own region, each a loop at a few RPMs. Two
  tables on the disc say how loud each patch is at each RPM. The
  throttle crossfades between the "l" (load) and "c" (coast) sets, and
  the camera's timbre between the "e" (engine) and "x" (exhaust) patches
  of each set. Nitro, gear changes and the music each add their part.
- **An AI car's engine** is one sample. Its pitch follows a running mean
  of the car's RPM, and on the start line it revs at random.

Retail has both in CarSoundEngine.obj, `0x0020fad0` .. `0x00212470`.
The port has them in `enginesound.{c,h}`, and
`tools/enginesound_check.py` runs retail's code against it.

| function | retail |
|---|---|
| VoiceAttr Play / Stop / SetVolume | `0x0020fad0` / `0x0020fb78` / `0x0020fb98` |
| VoiceAttr SetPitch / SetAzimuth | `0x0020fc18` / `0x0020fc48` |
| PlayerEngineSound() / ~PlayerEngineSound | `0x0020fc70` / `0x0020fe70` |
| Init | `0x0020ffc0` |
| DeactivateSound / ActivateSound / Mute | `0x00210400` / `0x00210408` / `0x00210410` |
| DetuneToLinear (never called) | `0x00210518` |
| ResolveTables / RampThrottle | `0x002105d0` / `0x002106c8` |
| UpdateGearShiftEffect / UpdateToRedLineRPM | `0x00210788` / `0x00210880` |
| UpdateNitroEffect / UpdateEngineDucker | `0x00210950` / `0x00210b48` |
| UpdateEngine | `0x00210bf8` |
| UpdateBlownRodDamage / UpdateCarDamage (never called) | `0x002110a0` / `0x00211188` |
| Update / Set | `0x00211390` / `0x002116d8` |
| AIEngineSound() / Update / Mute | `0x002117c8` / `0x002118a0` / `0x00211a80` |
| GetEngineSampleName | `0x00211a90` |
| ComputeRPMPitchShift / ComputeStartLineRPMPitchShift | `0x00211b10` / `0x00211c40` |
| AI DeactivateSound / ActivateSound | `0x00211d58` / `0x00211d60` |
| engine_sound::CreatePlayerEngine / CreateAIEngine | `0x00211d90` / `0x00211de0` |
| ~AIEngineSound | `0x00212418` |

The smooth, min, max and clamp templates the module uses sit at
`0x002122e0` .. `0x002123b8`, with the float ones at `0x001365e0` ..
`0x00136630`.

## The records

The bSample is 188 bytes in retail and 4 bytes shorter in the port (see
[bsound](bsound.md)). Everything after a bSample therefore sits earlier
in the port's records. The offsets below are retail's; `enginesound.h`
gives the port's beside them.

**PlayerEngineSound** (7176 bytes):

| offset | field | |
|---|---|---|
| 0 | the Sound3d | its vptr at 28 |
| 32 | pCar | |
| 36 | CurrThrottle | 0 .. 255, from RampThrottle |
| 40, 44 | RedLineRPMOffset, TopGearRPMOffset | the car's |
| 48, 236 | NitroStartSample, NitroLoopSample | |
| 424 | pDriveTrain | never written |
| 428 | GearShiftVolumeScale | |
| 432 | GearShiftingUp | |
| 436 | UpdateBlownRodTime | only the uncalled damage code reads it |
| 440 | bHandle | not used |
| 444 | Volume | 0 .. 127 |
| 448 | Ratio | the throttle, 0 .. 127 |
| 452, 454, 456 | Doppler, Azim, Seperation | u16s; Doppler is not read |
| 458 | Timbre | a signed byte |
| 459 | HighestPatch | |
| 460, 462, 464 | ControllerLevel, ControllerLevelTarget, CurrentLevel | the RPM as a level, 0 .. 440 |
| 468, 472 | BendRange, BassAdd | the car's |
| 476 | POVTimbre[4] | each drive camera's Timbre |
| 484 | IsStereo | |
| 488 | EngineBackfireBuildup | only the damage code reads it |
| 492 | CurrentRPM | |
| 496, 500 | fEngineDuckerThrottleTime, fEngineDuckerVolumeScale | |
| 504 | left[16] | VoiceAttrs, 200 bytes each |
| 3704 | right[16] | |
| 6904 | delay[16] | frames until the right voice starts |
| 6920 | definitions[2] | engine.ctb's and engine.ltb's |
| 6928 | RPMdef | never written |
| 6932 | engineSample[12] | 20 bytes each |
| 7172 | CurrAudioMode | |

A **VoiceAttr** (200 bytes) holds the voice's last volume (s16), bend
(s16), pitch (float) and azimuth (u16), then its bSample at 12. A call
that changes none of these is dropped.

An **EngineSample** (20 bytes) holds:

- bnkID, -1 until Init finds the patch, then 1;
- patchtype (s16), 1 for an "x" patch;
- isEnabled (s16), 1, and nothing clears it;
- sample, NULL, and nothing sets it;
- detune, in cents;
- volume, a float.

**AIEngineSound** (268 bytes):

| offset | field | |
|---|---|---|
| 0 | the Sound3d | |
| 32 | pCar | |
| 36 | EngineSample | the bSample |
| 224 | EnginePitchBase | -0.4 .. 0, set once |
| 228 | StartLineTargetPitch | -1 until the first rev |
| 232 | StartLineCurrPitch | |
| 236 | RPMAverage | an [Average](average.md) of twenty |
| 252 | CurrGear | |
| 256 | GearFrames | updates since the last gear change |
| 260 | SmoothRPM | |
| 264 | GearVolumeScale | |

The demo's AIEngineSound was 256 bytes. Retail added the last three
fields, which have no names in the debug data; the names are the port's.

`LastPlayerEngineSound` (gp-16268) is the last player engine made. It is
written, and nothing reads it.

## The tables

Both classes keep Sound3d's slots. Every delta is 0.

| slot | Player (`0x002bbfc0`) | AI (`0x002bbf80`) |
|---|---|---|
| 8 | ~PlayerEngineSound | ~AIEngineSound |
| 16 | Sound3d::Activate | Sound3d::Activate |
| 24 | Update | Update |
| 32 | Mute | Mute |
| 40 | DeactivateSound (does nothing) | DeactivateSound |
| 48 | ActivateSound (does nothing) | ActivateSound |
| 56 | Sound3d's UpdateCamRelativeDistAndVelocity | the same |

`enginesound_install_vtables` registers both at boot.

## engine.ctb and engine.ltb

`sound\engine.ctb` holds the coast set and `sound\engine.ltb` the load
set. Each is 6504 bytes. Init reads both with bGetFile at alignment 16.

Each file starts with an EngineDef, 360 bytes:

| offset | field | |
|---|---|---|
| 0 | id | "CRDl" |
| 4 | ver | 2 |
| 5 | resolved | 0 on the disc |
| 6, 7 | startevent, controllerpercent | |
| 8 .. 31 | the low and high random targets | levels, ranges and attack times; not read |
| 32 | patchnum[8] | each slot's patch, -1 for none |
| 40 | event[16] | 16 bytes each, all zero, not read |
| 296 | pvoltable[8] | each slot's volume table |
| 328 | pbendtable[8] | each slot's bend table, not read |

The slots map to the twelve patches like this:

| slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| engine.ctb | 6 | 7 | 8 | -1 | 9 | 10 | 11 | -1 |
| engine.ltb | 0 | 1 | 2 | -1 | 3 | 4 | 5 | -1 |

After the header come six blocks of 1024 bytes, one for each slot with a
patch: 512 bytes of volume, then 512 of bend. Each byte is a signed
value for one level. Only levels 0 .. 440 are read.

Each table pointer is stored as an offset from the pointer's own
address. ResolveTables adds that address to each pointer once and sets
`resolved`. A slot with no patch has offset 0, so it points at its own
field.

The patches are named from the car's SoundInfo.Prefix and these suffixes:

| patch | 0 .. 5 | 6 .. 11 |
|---|---|---|
| names | lelo lemd lehi lxlo lxmd lxhi | ceid cemd cehi cxid cxmd cxhi |

So the "l" patches are the load set and the "c" patches the coast set.
The second letter is "e" or "x", and an "x" patch has patchtype 1. The
last two letters are lo/id, md or hi.

**CrossFade** (`0x0031bc80`) gives 128 bytes of fade gain, from 0 at
index 0 up to 127. UpdateEngine indexes it with 127 - Timbre. Timbre is
a signed byte, and a car's POV timbre can be below 0, so retail can read
up to 128 bytes on either side of the table. The port carries
`0x0031bc00` .. `0x0031bd7f` as the image has them, so it reads the same
bytes.

## PlayerEngineSound

**The constructor** builds the Sound3d, the two nitro samples and all 32
voices, and sets every patch to off with volume 1. It stores the car and
the car's RPM, and sets both volume scales to 1 and the other state to
0. It then:

1. runs Init;
2. copies "NitroStart" and "NitroLoop" from the in-game samples into
   category 2;
3. turns the sound on.

**The destructor** stops the voices of all twelve patches. It frees both
tables and destroys the voices from the last to the first, then the
nitro samples, then the Sound3d.

**Init** does nothing with sound off. Otherwise:

1. It stops the six menu sounds in "common" ("MenuStart" ..
   "MenuWrong"). It then runs the sound driver three times, with a
   16 ms busy wait between each run, so that the menu voices are freed
   before the engine locks its own.
2. It reads the car's SoundInfo: the four POV timbres, BendRange,
   BaseAdd, and the red-line and top-gear offsets. It sets IsStereo and
   takes the audio mode.
3. For each patch in turn, it sets the detune, volume and patchtype. It
   then looks up Prefix + suffix in the region named after the car's
   BaseName. A missing patch ends Init there.
4. A patch that is found gets bnkID 1. It is copied into both its
   voices, in category 2. The "l" patches lock their left voice, and
   their right voice too with one player.
5. It reads both tables and runs ResolveTables.

**DeactivateSound** and **ActivateSound** do nothing. The engine is
always on.

**Mute(on)**: when unmuting into a new audio mode, it stops every voice,
so that UpdateEngine restarts them in the new mode. Otherwise it pauses
or resumes all 24 voices. Either way it then pauses or resumes the nitro
samples and takes the audio mode.

**ResolveTables** turns each table's offsets into addresses, unless the
table is already resolved. It zeroes Volume and ControllerLevel. It then
sets HighestPatch to one past the last of the sixteen slots that has a
patch. Retail's test reads the wrong slot: patchnum[0] of the first
table for slots 0 .. 7, and patchnum[1] of the second for slots 8 .. 15.
With the disc's tables HighestPatch is therefore 16.

**RampThrottle** makes CurrThrottle follow the pedal (0 .. 255). Going
up, it moves half the gap a frame and snaps to 255 from 254. Going down,
it moves an eighth of the gap and snaps to 0 below 9. The result is
clamped to 0 .. 255.

**UpdateGearShiftEffect** acts only in physics movement. It notes a
shift up when the current gear is below the desired gear, and clears
the flag when it is above. While shifting up with the RPM over 1500 and
the clutch disengaging or engaging, the target volume is the clutch
position, but at least 0.4. Otherwise the target is 1. The scale moves
at most 0.2 a frame towards the target.

**UpdateToRedLineRPM(rpm)** makes the engine's sound reach the red line
in every gear from second up, whatever the shift point. In physics
movement, from gear 2 up, it multiplies the RPM by:

    (RedLineRPM + RedLineRPMOffset) / min(red line, the next gear's shift-up RPM)

In top gear it adds TopGearRPMOffset. The result is capped at MaxRPM
times the same ratio. The RPM is also written to the car's
State.RedLineSyncRPM.

**UpdateNitroEffect(volume, azimuth, pitch)**, in physics movement:

- When the engine's NitroFlag first goes on, it plays the start and the
  loop at 2.5 x volume. The azimuth goes in as the pan, as retail has
  it.
- While the loop plays, let f be a quarter of the seconds since the
  boost began. It sets the loop's pitch to pitch x (f + 0.5). Past
  f = 0.8 (3.2 seconds), it fades the volume by 5 x (f - 0.8).
- When the flag goes off, it stops the loop.

**UpdateEngineDucker** acts only while the music (category 4) is over
0.05. While the throttle is under 0.5, it resets the timer and brings
the scale back towards 1. Otherwise it adds the frame's time to the
timer, and after 5 seconds brings the scale towards 0.75. Either way the
scale moves at most 0.008 a frame.

**UpdateEngine** first runs UpdateGearShiftEffect and sets all three
levels to ControllerLevelTarget. It then goes through each slot below
HighestPatch. Slots 0 .. 7 are the coast table's and 8 .. 15 the load
table's. A slot is skipped if it has no patch or its patch was not
found. For each other slot:

1. **Pitch.** b = the level x 127 / 440, as a signed byte. The pitch is
   (BassAdd + detune + ((b - 64) x BendRange >> 6)) / 1200.
2. **Volume.** v is the slot's table at the level, x Volume >> 7. The
   throttle crossfade then gives v x CrossFade[Ratio] >> 7 for a load
   slot, and v x CrossFade[127 - Ratio] >> 7 for a coast slot.
3. **Silence.** If v is now 0, it stops both voices if the left one is
   playing, and moves on to the next slot.
4. **Boost and timbre.** v is multiplied by 5/4 (>> 2) and capped at
   127. The timbre crossfade then gives v x CrossFade[Timbre] >> 7 for
   an "x" patch, and v x CrossFade[127 - Timbre] >> 7 for an "e" patch.
5. **Scale.** The final volume is v x GearShiftVolumeScale x
   fEngineDuckerVolumeScale x the patch's volume, x 1.3 in mono.
6. **Azimuths.** The left voice goes at Azim - Seperation and the right
   at Azim + Seperation.

If the left voice is not playing, it starts it at that volume and pitch
and sets the slot's delay to 2. In stereo, once the right voice is not
playing and the delay has run out, it starts the right voice too.
Otherwise it counts the delay down as a byte, so the delay wraps after
-128. A disabled patch has its voices stopped, but nothing ever disables
one. Both voices then get the volume (at least 0), azimuth and pitch.
Each voice moves its volume at most 15 a call, and a stopped voice
fades out over the frames after.

**Update(volume, azimuth, pitch)**, slot 24, does nothing while the sound
is off or sound or car sound is off. Otherwise:

1. It runs RampThrottle.
2. It takes the car's RPM, or TestRPM once that is off 100, less the
   car's IdleOffset. It scales that with UpdateToRedLineRPM.
   CurrentRPM then moves towards it by at most 270 a frame going up and
   650 going down.
3. It runs UpdateEngineDucker and UpdateNitroEffect.
4. The level is CurrentRPM / MaxRPM x 440, capped at 440.
5. The POV is the player's drive camera, or 0 for a car with no player.
   In an instant replay, the post-race, the auto replay and the replay
   demo, the POV is -1. The facing is then the dot of the camera's
   direction with the car's heading.
6. It sets the stereo state from the azimuth and the audio mode:

   | azimuth | mode | IsStereo | Seperation | Azim |
   |---|---|---|---|---|
   | 0 | 1 | 1 | 8000 | 0 |
   | 0 | 2 | 1 | 6000 | 0 |
   | any other | any | 0 | 0 | the azimuth |

   The azimuth is 0 only from the car's own camera. In mono (mode 0),
   and from any other camera, each patch plays one voice where the car
   is.
7. It runs Set, then UpdateEngine. It also works out the distance to
   the camera for Set, which ignores it.

**Set(volume, ratio, throttle, dist2, doppler, azimuth, facing, pov)**
stores:

- the level target (from ratio);
- doppler >> 4;
- Ratio, which is throttle + (throttle >> 5), capped at 127, and 0
  below 4;
- the volume.

Timbre is the POV's own timbre, or for POV -1, 44 + facing x 60 (or
facing x 30 when the facing is below 0). It is capped at 127. Set does
not read the distance or the azimuth.

## AIEngineSound

**The constructor** builds the Sound3d, the sample and an Average of
twenty. It sets:

- the start-line pitch to 0, and its target to -1;
- CurrGear to -1 and GearFrames to 10;
- SmoothRPM to 1000 and the gear volume scale to 1;
- EnginePitchBase to minus a random float below 0.4.

It then copies GetEngineSampleName's in-game sample into category 0.

**The destructor** destroys the Average (flags 2), the sample and the
Sound3d.

**GetEngineSampleName** writes "AIEngine0" into a static buffer and adds
the car's SoundInfo.AIEngineNumber to the digit. A traffic car (usage
type 2) keeps "AIEngine0".

**Update(volume, azimuth, pitch)** does nothing while the sound is off.
The car is on the start line if the race is in its pre-race or countdown
stage and the car is below 5 mph (2.237 mph per m/s).

- On the start line, the pitch comes from
  ComputeStartLineRPMPitchShift, and the volume moves at most 0.075 a
  frame.
- Otherwise the pitch comes from ComputeRPMPitchShift. The volume is
  scaled by GearVolumeScale. Below 75 km/h it is scaled again by
  0.5 + 0.5 x km/h / 75. The volume moves at most 0.3 a frame.

A sample that is not playing is started at that volume, if sound
and car sound are on. The sample's pitch is EnginePitchBase + shift x
pitch - 1, and its azimuth is the one given.

**ComputeRPMPitchShift** works as follows:

1. A change of gear refills the Average with the current RPM and resets
   GearFrames.
2. It records the RPM.
3. SmoothRPM moves towards the mean. For the six updates after a gear
   change, the step is 12, 25, 50, 100, 200 and then 400 RPM, and the
   volume scale is 0.8, 0.6, 0.4, 0.4, 0.4 and then 0.8. After that the
   step is 5000 and the scale 1.
4. It returns SmoothRPM x 0.0002 (`0x3951b718`).

**ComputeStartLineRPMPitchShift** idles at 0.3. The first call sets both
the pitch and the target to 0.3. The pitch rises at up to 0.15 a frame
and falls at up to 0.08. At the idle, and on every frame of a fall,
there is a 4% chance (sound's random float below 4 of 100) that the
target becomes 1. Once the pitch reaches 1, the target goes back to 0.3.

**Mute** pauses the sample. **DeactivateSound** stops it.
**ActivateSound** plays it at volume 0, if sound and car sound are on.

## engine_sound

**CreatePlayerEngine** and **CreateAIEngine** are carsound's
gCreatePlayerEngineFn and gCreateAIEngineFn. Each makes its record with
bMalloc under the tag "PlayerEngineSound" or "AIEngineSound", at
alignment 16, and returns its Sound3d. The player's also sets
LastPlayerEngineSound.

## What retail leaves out

Nothing calls three of the module's functions, and the port does not
have them:

- **DetuneToLinear(cents)** turns cents into a 4096-based ratio: an
  octave at a time, then through CentsToPitch.
- **UpdateCarDamage** sums the car's fifteen damage values. At 50 or
  more it runs **UpdateBlownRodDamage**. At 26 or more it builds
  EngineBackfireBuildup from the throttle. When the throttle drops
  below half with the buildup over 100000, it may play a backfire.

## What the port changes

- **The voice budget.** ndsp gives the game 22 voices, where the PS2 had
  48. Retail's player engine locks twelve voices with one player (both
  of each "l" patch) and takes up to eight more for the "c" patches.
  That is twenty of the 3DS's twenty-two. So the port plays the
  player's engine as retail does in mono, audio mode 0: one voice per
  patch at the car's azimuth, 1.3 times as loud, locking only the six
  left voices. `ENGINESOUND_RETAIL_VOICES` at 1 brings back retail's
  pairs and lets the checker run them.
- **The tables keep their offsets.** A 32-bit field cannot hold a host
  address. ResolveTables only marks each table, and each read adds the
  field's own address to its offset.
- **The bSamples are 4 bytes shorter**, as noted above.
- **A missing patch.** Init then stops before reading the tables. The
  port's bMalloc zeroes memory, so the definitions stay NULL and
  HighestPatch stays 0, and UpdateEngine plays nothing. Retail would
  read whatever its heap held.

## The check

`tools/enginesound_check.py` runs retail's CarSoundEngine.obj in
mipsemu, with the EE's divide, product and root. Sound3d's constructor,
destructor and Activate, Average and the templates run in the image
too. The harness `tools/src/enginesound_test.c` runs the port's code
through the port's tables. Both sides use the same printing fakes of:

- bSample, bSound's regions, update and category volumes;
- the in-game samples, and sound's random float and audio mode;
- bMalloc (0xa5-filled, with the size checked against retail's records)
  and delete;
- the ticker, eGetView, IsReplayDemoMode and DriveTrain::GetState;
- bGetFile, which serves the disc's own ENGINE.CTB and ENGINE.LTB.

The harness is built twice. With `ENGINESOUND_RETAIL_VOICES` at 1 it
runs against the model as it is. At 0 it runs against the model in
mono, where retail's GetAudioMode answers 0 and the player count is
never 1.

The script, 1024 operations, covers every function above:

- each crossfade's ends and the Timbre beyond them;
- the volume's cap, negative tables and the voices' 15-step smoothing;
- the right voices' delay and its wrap;
- every audio mode, replay state and POV;
- the nitro's start, hold, fade and stop;
- the ducker either side of its music and throttle limits;
- the AI's gear-change settling and the start line's revs, with the
  dice either side of 4.

Both builds match retail: 6355 and 6234 lines, 0 differ.

`--mutate` runs 384 mutations of enginesound.c out of the tree, in
parallel, on the mono build first. Those that survive it run again on
the retail-voices build. All 384 are caught.
