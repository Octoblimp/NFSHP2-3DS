# carsound -- the sound a car makes

Every car with sound has a `BaseCarSound`. It is a [Sound3d](sound3d.md)
at the car's position, and it owns the car's other sounds:

- the horn, which every car has;
- the siren, on cop cars only (UsageType 1);
- the engine and the tyres, from steps 14-4 and 14-5;
- the splashes and the tyre pop, which are shared bSamples of the
  in-game region.

The player's sound adds the wind, an echo off cars going the other way,
and its own envelope. The AI's has a shorter envelope, and only the
closest few AI cars sound at all.

Retail has all of this in CarSounds.obj, `0x0018d0a8` .. `0x0018f800`,
with `HornSound3d` and `SirenSound3d`. The port has it in
`carsound.{c,h}`, and `tools/carsound_check.py` runs retail's code
against it.

| function | retail |
|---|---|
| GetPOVVolume | `0x0018d0a8` |
| BaseCarSound::BaseCarSound / ~BaseCarSound | `0x0018d140` / `0x0018d258` |
| BaseCarSound::Update / UpdateSirenSound | `0x0018d340` / `0x0018d3f8` |
| GetHornSample / TriggerSplash / UpdateSplash | `0x0018d480` / `0x0018d488` / `0x0018d4a0` |
| Mute / TriggerTireBlowOut / ScaleRoadNoise | `0x0018d550` / `0x0018d650` / `0x0018d6e8` |
| InSoundSphere | `0x0018d750` |
| StartHonkHorn / StopHonkHorn / IsHonking | `0x0018d780` / `0x0018d7c0` / `0x0018d800` |
| DeactivateSound / ActivateSound | `0x0018d830` / `0x0018d8d8` |
| GetSplashSample | `0x0018d950` |
| BasePlayerCarSound::BasePlayerCarSound / ~ | `0x0018d9a0` / `0x0018db78` |
| BasePlayerCarSound::Update / Mute / GetHornSample | `0x0018dbf0` / `0x0018dd10` / `0x0018dda0` |
| GetEngineReflectionSample | `0x0018de00` |
| CalcWindVolume / CalcWindPitch | `0x0018de68` / `0x0018dea0` |
| UpdateEngineReflection / UpdateDynamicBodyReflections | `0x0018deb0` / `0x0018e018` |
| UpdateTopologyReflections (never called) | `0x0018e3b8` |
| BaseAICarSound::BaseAICarSound / ~ / Update | `0x0018e6e8` / `0x0018e7e8` / `0x0018e800` |
| MaybeInsertCarSound / MaybeActivateCarSound / UpdateCarSounds | `0x0018e8b0` / `0x0018e970` / `0x0018ea18` |
| sound::CreatePlayerCarSound / AICarSound / AICopCarSound | `0x0018eb28` / `0x0018eb70` / `0x0018ebb8` |
| GetReverbTopologyCoordinate | `0x0018ec00` |
| the static constructor | `0x0018f0f8` |
| HornSound3d ActivateSound / DeactivateSound / ChooseHornSample | `0x0018f160` / `0x0018f188` / `0x0018f190` |
| HornSound3d Mute / Update / ~ | `0x0018f208` / `0x0018f218` / `0x0018f2b0` |
| SirenSound3d UpdateMode / SirenSound3d() | `0x0018f300` / `0x0018f388` |
| SirenSound3d ActivateSound / DeactivateSound | `0x0018f4d0` / `0x0018f508` |
| SirenSound3d SetSirenBroken / Mute / Update | `0x0018f520` / `0x0018f528` / `0x0018f548` |
| SirenSound3d ~ / GetBrokenSirenPitch | `0x0018f710` / `0x0018f7a0` |

## The records

BaseCarSound is 80 bytes. After its Sound3d it holds only pointers and
words, so it is the same record on the 3DS:

| offset | field | |
|---|---|---|
| 0 | the Sound3d | its vptr at 28 |
| 32 | pCar | |
| 36, 40 | SplashLeft, SplashRight | a level, from TriggerSplash |
| 44, 48 | SplashLeftTimer, SplashRightTimer | frames to the next splash |
| 52 | HornSound | |
| 56 | SirenSound | cop cars only |
| 60 | EngineSound | |
| 64 | TireSoundBlowOut | the in-game "TirePop1" |
| 68, 72 | TireSound[2] | by side |
| 76 | pSoundEnvelope | |

The other records each hold one or more bSamples. Retail's bSample is
188 bytes with its vptr at 184. The port's has no vptr, so it is 4 bytes
shorter, and everything after a bSample sits 4 bytes earlier per sample.
The offsets below are retail's:

- **BasePlayerCarSound** (288): BaseCarSound;
  ReverbTopologyCoordinate (80); EngineReflectionLeft and Right (84, 88);
  CheckForReflected (92); WindSample (96); PlayerAzimuth (284, a u16).
- **BaseAICarSound** (80): BaseCarSound alone.
- **HornSound3d** (224): Sound3d; HornSample (32); DetunePitch (220).
- **SirenSound3d** (616): Sound3d; SirenSampleTable[3] (32);
  CurrentSiren (596); SwitchSirenTime (600); IsSirenBroken (604);
  BrokenSirenPitchTarget (608); CurrBrokenSirenPitch (612).

The TopologyCoordinate is retail's 704 bytes, made with bMalloc under
the tag `..\indep\src\carsounds.cpp`, line 773.

## The globals

| name | where | value |
|---|---|---|
| CarSoundEnabled | gp-20456 | 1 |
| CarDamageSoundEnabled | gp-20460 | 1 |
| RoadNoiseEnabled | gp-16248 | 1 (CarSoundTires.obj's) |
| MaxActiveCarSounds | gp-20400 | 3, or 6 with one player |
| NumClosestCarSounds | gp-20396 | |
| ClosestCarSounds[6] | `0x003100c0` | |
| BasePlayerCarSoundEnvelope | `0x00310070` | 1.3, 260, 1/260 |
| BaseAICarSoundEnvelope | `0x00310080` | 1.3, 130, 1/130 |
| POVVolumeTable[4][3] | `0x00310090` | see GetPOVVolume |
| ReflectionAzimuth | gp-13392 | 16384, a quarter turn |
| HornCounter, SirenCounter | gp-20436, gp-20440 | 0 |

Nothing writes the three switches. The static constructor fills both
envelopes, each a quarter circle out to its cut-off. The demo disc had
both out to 200.

## The tables

Each class keeps Sound3d's slots and adds nothing, except that the car
sounds add GetHornSample at 64. Every delta is 0, since the Sound3d is
at offset 0 in all five.

| slot | Base (`0x002b4968`) | Player (`0x002b4920`) | AI (`0x002b48d8`) | Horn (`0x002b4898`) | Siren (`0x002b49b0`) |
|---|---|---|---|---|---|
| 8 | ~BaseCarSound | ~BasePlayerCarSound | ~BaseAICarSound | ~HornSound3d | ~SirenSound3d |
| 16 | Sound3d::Activate | " | " | " | " |
| 24 | Update | Player's Update | AI's Update | Horn's Update | Siren's Update |
| 32 | Mute | Player's Mute | Base's Mute | Horn's Mute | Siren's Mute |
| 40 | DeactivateSound | Base's | Base's | Horn's | Siren's |
| 48 | ActivateSound | Base's | Base's | Horn's | Siren's |
| 56 | Sound3d's UpdateCamRelative... | " | " | " | " |
| 64 | GetHornSample (NULL) | Player's | Base's | | |

`carsound_install_vtables` registers all five at boot.

## The module

**GetPOVVolume(car, type)** reads the car's player's drive camera POV
(int8 at Player+36), or POV 0 for a car with no player. Each row of the
table is one POV:

| POV | column 0 (engine) | column 1 (wind) | column 2 (tyres) |
|---|---|---|---|
| 0 | 0.8 | 1.0 | 0.75 |
| 1 | 0.9 | 0.9 | 0.85 |
| 2 | 1.0 | 0.75 | 1.0 |
| 3 | 1.25 | 0.4 | 0.9 |

Type 0 reads column 0, type 1 column 2 and type 2 column 1. Any other
type gives 1.

**The three Create functions** are Car's constructor's. Each makes its
record with bMalloc, under the tag "PlayerCarSound" or "AICarSound", at
alignment 16. The cop's is the AI's: the siren comes from the car's
usage type, not from the function.

**UpdateCarSounds** runs once a sound frame, from sound::Update. With no
world it does nothing. Otherwise it:

1. sets MaxActiveCarSounds to 3 with two players, 6 with one;
2. runs Car::UpdateSound on every car, which calls slot 24 with
   (1, 0, 1);
3. clears the first MaxActiveCarSounds entries of the closest list, and
   the count;
4. passes every non-player car to MaybeInsertCarSound;
5. passes every non-player car to MaybeActivateCarSound.

**MaybeInsertCarSound** skips a sound outside the sound sphere. Otherwise
it takes the first empty entry and counts it. When the list is full, it
replaces the first entry that is strictly further off. It does not move
the others down, so the list is not kept in order.

**MaybeActivateCarSound** turns the sound on if it is in the list, and
off if not.

## BaseCarSound

**The constructor** builds the Sound3d, then:

- stores the car and zeroes both splashes and both timers;
- puts the three splash samples and "TirePop1" in category 0;
- sets the engine and tyres to NULL;
- for a cop car, makes a SirenSound3d ("SirenSound", 616 bytes); for any
  other car, sets the siren to NULL.

The horn is left to the derived constructors.

**The destructor** deletes the horn, engine, siren and both tyres
through slot 8 with flags 3, skipping a NULL. It then runs Sound3d's
destructor with the caller's flags.

**Update(volume, azimuth, pitch)** runs Sound3d's Update at the car's
position with the record's envelope. It scales the volume and pitch by
the arguments and never reads the azimuth. It then:

1. passes the result to the horn's Update;
2. runs UpdateSirenSound if there is a siren;
3. runs UpdateSplash for the left side, then the right, at the sound's
   volume.

**UpdateSirenSound**: while the car sound is on, it hands the car's
siren mode (Car+2104) to the siren's UpdateMode. While the car sound is
off, it turns the siren off. Either way it then passes the car sound's
volume, azimuth and pitch to the siren's Update.

**UpdateSplash(volume, splash, timer)** counts the timer down by one.
With no splash pending it stops there. A splash asked for while the
timer is still running is dropped. Otherwise it:

1. plays one of the three splash samples at random, at volume x level
   and pan -1, if sound, car sound and road noise are all on;
2. sets the timer to 10;
3. clears the splash.

So a side splashes at most once in ten sound frames. Car's effects call
**TriggerSplash** (careffects.c).

**Mute(on)** pauses or resumes the horn, engine, siren and tyres
through slot 32, then the three splash samples.

**TriggerTireBlowOut** plays "TirePop1" at the sound's volume, its
azimuth as a float and its pitch, if sound, car sound and damage sound
are all on. It then calls each tyre's TriggerBlowOut. **ScaleRoadNoise**
calls each tyre's own.

**InSoundSphere** is true when the sound is strictly within 130 of the
camera.

**StartHonkHorn** and **StopHonkHorn** turn the horn on and off, and
**IsHonking** reads it. All three do nothing, or return 0, unless sound
and car sound are both on. The player's driver honks with the horn
button; see [joystick](joystick.md).

**DeactivateSound** turns off the horn, the engine and the tyres, but not
the siren. UpdateSirenSound turns that off. **ActivateSound** turns on
the engine and the tyres, but not the horn.

**GetSplashSample(i)** builds "Splash1" + i. With -1, it picks i with
sound's random int below 3.

## BasePlayerCarSound

**The constructor** runs BaseCarSound's, then:

1. builds the wind sample and the TopologyCoordinate;
2. zeroes both reflections and sets CheckForReflected;
3. takes the player's envelope;
4. copies "Wind" into the wind sample, category 0 (nothing ever plays
   it);
5. makes the horn from GetHornSample, called directly and not through
   the table;
6. makes the engine and tyre 0, and tyre 1 with one player only;
7. sets the split-screen azimuth: the first player's car is panned left
   (-CarSoundMultiPlayerAzimuth) and the second's right, 0 with one
   player;
8. turns the sound on.

**The destructor** stops the wind sample. It then destroys and frees
the TopologyCoordinate (its destructor with flags 3), destroys the wind
sample and runs BaseCarSound's destructor.

**Update** runs BaseCarSound's Update, then:

1. replaces the azimuth with PlayerAzimuth;
2. updates the engine at volume x POV type 0, and each tyre at volume x
   POV type 1;
3. runs UpdateEngineReflection;
4. clears the player's zone sound once it is held and nZoneCurrent is
   0, so a tunnel's sound goes once the car has left it.

**Mute** runs BaseCarSound's Mute. It then pauses the wind sample, both
reflection samples and the player's zone sample, if there is one.

**GetHornSample** looks up Prefix + "Horn" in the region named after the
car's BaseName: the car's own horn. Retail builds the name with bStrCat.

**GetEngineReflectionSample(i)** builds "Reflection0" + (1 + i). With -1
it picks between the two at random.

**CalcWindVolume(f)** is (POV type 2 x f) x 0.012. **CalcWindPitch(f)**
is f x 0.008. Nothing calls either.

**UpdateEngineReflection(volume)** plays the echoes that the last frame
found. For each side marked, it plays a random reflection sample at
speed x 0.03 x volume, with pitch speed x 0.015 - 1, if sound and car
sound are on. The left side's goes to -ReflectionAzimuth and the
right's to +ReflectionAzimuth. Each mark is then cleared. Below 50 km/h
(13.888889 m/s) it sets CheckForReflected. At or above it, it runs
UpdateDynamicBodyReflections.

**UpdateDynamicBodyReflections** asks the collision system for the
bodies within 9 of the car's body. It walks them from first's next up
to last; when first is the list head, the head's own word is the next.
It skips a body when:

- it is the car's own body;
- its terrain type is a plant;
- its 3D distance is over 9 (VU0's order of sums);
- its ground-plane speed relative to the car's is not over 13.888889.

For each body left, it steps both the car and the body on by
WorldTimeElapsed. It takes:

- d, the normalized line between them after the step;
- e, the normalized line between them now;
- the car's normalized heading.

If the dots of e and d with the heading have strictly opposite signs,
the body passes the car's nose this frame. Its side of the car then gets
an echo next frame: left when its car-local x is negative, right
otherwise.

## BaseAICarSound

**The constructor** runs BaseCarSound's, then takes the AI's envelope.
It makes the engine, then the horn, then tyre 0. The horn comes from
BaseCarSound's GetHornSample, which is NULL, so every AI horn is
ChooseHornSample's.

**Update**: when the sound is off (not among the closest), it only
updates its distance through slot 56 and stops. When the sound is on,
it runs BaseCarSound's Update at volume x 1.5, then updates the engine
and tyre 0 at the result.

## HornSound3d

**The constructor** builds the Sound3d and the sample. It copies the
given sample, or ChooseHornSample's when there is none, into category 0,
with DetunePitch 1. **ChooseHornSample** hands out "Horn01", "Horn02"
and "Horn03" in turn, game-wide, through HornCounter.

**ActivateSound** plays the sample from the start if sound is on.
**DeactivateSound** stops it. **Mute** pauses it.

**Update**, while on, sets the sample's volume and azimuth, and its pitch
to DetunePitch x pitch - 1 (bSample's pitch is an offset from 1).

## SirenSound3d

**The constructor** builds the three samples, then:

1. sets SwitchSirenTime to 17;
2. copies "CopSiren01" .. "03" from the "InGame" region, category 0;
3. advances SirenCounter (mod 3) and starts on the new value, so each
   cop starts on the siren after the last cop's;
4. sets the broken pitch and its target to 1, not broken.

**The destructor** destroys the samples from the last to the first.

**UpdateMode(mode)**: mode 0 turns the siren off, and any other mode
turns it on. While on, mode 4 (SIREN_MODE_BROKEN) marks it broken and
any other mode clears that.

**ActivateSound** plays the current siren if sound is on.
**DeactivateSound** stops it. **Mute** pauses it. **SetSirenBroken**
stores its argument.

**Update(volume, azimuth, pitch)** first turns the siren off if the
volume is exactly 0. While the siren is on, it:

1. takes the frame's time off SwitchSirenTime;
2. if that is now below 0, stops the current siren, resets the time to
   17 and moves on to the next of the three;
3. sets the current siren's volume if it is playing; otherwise resets
   the time to 17 and plays it, if sound is on;
4. multiplies the pitch by GetBrokenSirenPitch when the siren is broken;
5. sets the sample's pitch to pitch - 1 and its azimuth.

**GetBrokenSirenPitch**: once the pitch has reached its target, the
target becomes 0.1 plus a random float below 0.9. The pitch then steps
towards it by at most 0.03 a frame, using sound.c's smooth.

## What the port adds

Retail reads some pointers without testing them. The port tests:

- the engine, in Mute, Deactivate and both Updates;
- the AI's tyre 0, in its Update;
- a car's pBaseCarSound, in UpdateCarSounds.

The engines and tyres are steps 14-4 and 14-5. Until each step binds its
factory, it stays NULL, and the car sounds make no engine or tyre. The
tyres' TriggerBlowOut and ScaleRoadNoise are hooks in the same way.

## The check

`tools/carsound_check.py` runs retail's CarSounds.obj in mipsemu, with
the EE's divide, product and root. The harness
`tools/src/carsound_test.c` runs the port's code through the port's
tables. Both sides use the same printing fakes of:

- Sound3d's Update and UpdateCamRelativeDistAndVelocity;
- bSample, the regions and the in-game samples;
- sound's random helpers, bMalloc and delete;
- the TopologyCoordinate, the engine and tyre factories (probe sounds
  that print every slot), Player::ClearZoneSound and Car::WorldToCar;
- the collision bodies.

The script covers every function above, on every kind of car: the
player alone and in split screen, the AI, cop, traffic and super cop,
with and without tyres. It also covers:

- the siren through every mode, a switch, a silent frame and the broken
  pitch;
- splashes inside and outside the ten-frame gap;
- reflections at and around 50 km/h, with bodies past and not past the
  nose;
- the closest list by hand and through UpdateCarSounds, with one and two
  players and no world.

Retail's AI Update reads TireSound[0] without a test, so the script
never updates an active AI car that has no tyres.

`--mutate` runs the mutation list against carsound.c out of the tree, in
parallel, with retail's transcript cached.
