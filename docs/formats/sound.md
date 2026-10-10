# sound -- the game's sound module

`sound` is the game's own layer over [bSound](bsound.md). It brings the
driver up and loads the "common" bank, then loads and unloads the banks
each part of the game needs (the regions, by name). It runs the per-frame
update in its fixed order and lowers every volume when a zone, the
post-race or a speech asks for it. It also mutes everything for the pause
menu and the replays. Retail has it as Sound.obj, `0x001ae018` ..
`0x001afbc0`: the namespace `sound` and the free functions around it. The
port has it in `sound.{c,h}`, and `tools/sound_check.py` runs retail's
code against it.

| function | retail |
|---|---|
| UpdateVolumeMuffler | `0x001ae110` |
| GetInGameSample / GetFrontEndSample | `0x001ae280` / `0x001ae2d8` |
| the region loader | `0x001ae340` |
| SoundDriverCallback | `0x001ae3c8` |
| InitializeSoundDriver | `0x001ae608` |
| LoadSoundRegionsInGame / LoadSoundRegionsFrontEnd | `0x001ae798` / `0x001ae9a0` |
| RealIsSoundRegionLoadingComplete / IsSoundRegionLoadingComplete | `0x001af290` / `0x001af2e8` |
| the region poll | `0x001af308` |
| UnLoadSoundRegions | `0x001af420` |
| sound::Update | `0x001af4c0` |
| ScaleCategoryVolumes | `0x001af638` |
| MuteCarSounds | `0x001af6f8` |
| PlayCommonRegionSample | `0x001af760` |
| sound::Mute / sound::MuteReplay | `0x001af850` / `0x001af940` |
| the two random helpers | `0x001af9a0` / `0x001af9c0` |
| sound::SetAudioMode / GetAudioMode | `0x001af9e0` / `0x001afa10` |
| TriggerFinishLineSound | `0x001afb38` |

The jukebox half of `sound::jukebox` lives in [jukebox](jukebox.md):
Start, Stop, SetSelection, the saved volumes and DefaultCategoryVolumes.
TriggerTimerWarningSound (`0x001afb80`) is hudrender.c's. The localized
speech files (`0x001ae4d8` / `0x001ae5e8`) and the wedge's creation are
`sedwedge.c`'s ([sedwedge](sedwedge.md)). Two things are not ported:

- GetFrontEndSample, which nothing calls;
- `0x001afa18`, a 0.7 the FlailerSlider's constructor asks for.

## The statics

| retail | port | |
|---|---|---|
| `0x003139a8` | `region[4]` | four slots of 36 bytes: a name of 32 and whether bSound has said it is in |
| gp-19012 | `inGameRegion` | GetInGameSample's region, looked up once |
| gp-19000 | `frontEndRegion` | GetFrontEndSample's |
| gp-19020 | `commonLoaded` | |
| gp-19064, gp-19060 | `done`, `doneParam` | what the poll calls once the regions are in |
| gp-19056, gp-19052 | `loading`, `loadStart` | the ticker when the load was asked for |
| gp-18900 | `lastUpdate` | sound::Update's 8 ms gate |
| gp-19036, gp-19032 | `muffleCurrent`, `muffleTarget` | 1.0, 1.0 |
| gp-18896 | `lastScale` | -1.0 |
| gp-19068 | `seed` | the module's own random seed |
| gp-18892 | `audioMode` | 1, stereo |
| gp-16552 | `speechEnabled` | 1 |
| gp-18904 | `printVoiceUsage` | a debug flag nothing sets |

## Loading regions

**The loader** (`0x001ae340`) builds `"sound\" NAME ".msh"` and asks
bFileExists. If the file is missing, the screen flashes blue (0, 0, 250)
for a second with "Cannot Find Sound Region", and nothing else happens.
If the file is there, the loader calls bSound::LoadRegion(NAME). On the
3DS, the file test is main.c's `sndFileExists`, which maps that path to
`<card>/SOUND/NAME.SBK`.

**The callback** (`0x001ae3c8`) is bSound's client. It does nothing for
any event except 2, a region in. On event 2:

1. If the region is CommonRegion, `commonLoaded` is set.
2. Every slot with the region's name is marked loaded.
3. The first slot that is named and not loaded gets SetPath("sound\") and
   the loader.

bSound holds only one pending region, so the regions come in one at a
time. Each arrival asks for the next.

**InitializeSoundDriver** (`0x001ae608`) runs at boot. It does nothing
with SoundEnabled off. Otherwise:

1. It seeds the module's random from the default seed (bRandom(-1)).
2. bSound::Initialize(callback, 0, 256, 50, 16, 1, 1, 0x10000).
3. SetAudioMode(1).
4. The SPU2 reverb is turned off (bEffect::SetType(1), PlatSetEffectVolume).
   bsnd has no reverb.
5. SetPath, then the loader on "common".
6. While bSound is up and "common" is not in, it loops: bServiceFileSystem,
   then bSound::Update once each VBlank.
7. With MusicEnabled on, it loads the jukebox cartridge
   `SOUND\JukeboxM.JBC`. The demo disc's launcher picked
   JukeboxMDemoDisk.JBC here instead.
8. It creates the cSEDWedge and sets DefaultCategoryVolumes.

Retail's wait in step 6 has no end if "common" cannot come. The port
also stops when bSound has nothing pending, so a card without COMMON.SBK,
or a 3DS without ndsp, boots silent instead of hanging. The VBlank is a
counter that main.c's hook moves on each time the wait asks.

**LoadSoundRegionsInGame** (`0x001ae798`) and **LoadSoundRegionsFrontEnd**
(`0x001ae9a0`) both store `done(param)`, set `loading` and note the
ticker. They do that even with SoundEnabled off, so the poll still calls
`done`. With sound on, both then:

- clear the two sample regions and DelayedStart's count;
- call the jukebox's SetSelection, the racing list 4 or the menu list 5;
- empty the four slots.

The frontend fills slot 0 with "FrontEnd", calls the loader and clears
the jukebox's mute. The in-game load clears the mute first, then fills
the slots in this order:

1. "InGame".
2. The track's SoundRegion (CurrentTrackInfo +132), when there is a track.
   An empty name still takes the slot.
3. For drivers 0 and 1 (GetDriverInfoByDriverNumber), the car type's Sound
   (CarTypeInfos +816). A driver is skipped if it is missing, its
   EliminatedRank (a signed byte) is above 0, or the name is empty. A name
   already in a slot is not added again.

It then calls the loader on slot 0, and finally collision_sound::Register,
SpeechNoise::RequestSamples and sound3d_oneshot::Init.

**The poll** (`0x001af308`) is sound::Update's first call. It does nothing
unless `loading` is set.

- **Replaying a joylog:** it reads one bit on channel 5. If the recording
  had the regions in, it waits for them the same way as the boot wait.
  This keeps the replay's frames lined up.
- **Otherwise:** it records whether the regions are in, as one bit on
  channel 5.

After twenty seconds from `loadStart` (`difference × 0.001 > 20`), the
screen flashes orange (128, 84, 0) for half a second with "Hang loading
sound", and the load counts as done. Once the load is done, `loading` is
cleared and `done(param)` is called once.

Retail asks for no more regions after a missing one. The port has
`SoundHooks.skip_missing` for this, and main.c sets it. A region that
cannot come in (no file, no ndsp, no room) is then taken as in, and the
next one is asked for. The menus and races don't sit for twenty seconds
on a card short a bank. The checker runs with it at 0.

**UnLoadSoundRegions** (`0x001af420`) does nothing with sound off.
Otherwise it calls collision_sound::UnRegister, SpeechNoise::UnLoadSamples,
the speech queue's flush and sound3d_oneshot::Close. Then it unloads every
named slot, last first, and clears the slots, the two sample regions and
DelayedStart. "common" is never one of the slots, so it stays loaded.

## sound::Update

`0x001af4c0`, once a frame:

1. The poll, even with sound off.
2. With sound on, and more than 8 ms since the last pass, the gate is
   passed and the pass is noted. Retail reads the difference once before
   the sound test too and throws it away.
3. The speech manager's update, cSEDWedge::Update and the jukebox's
   Update.
4. If the game is not paused, not in the frontend (GameFlowState 3) and
   not muted:
   - UpdateCarSounds;
   - DelayedStart's count: if it is above 0, the world's step
     (WorldTimeElapsed) is taken off. If the result is below 0, the
     jukebox's Start(0) runs and the count goes back to 0;
   - collision_sound, sound3d_oneshot, sound_scape and SpeechNoise
     updates;
   - Chopper::UpdateSound, if the world has a helicopter.
5. bSound::Update, then the muffler.
6. PrintVoiceUsage, if the debug flag is set (it then clears it).

## The muffler

UpdateVolumeMuffler (`0x001ae110`) moves `muffleCurrent` towards a target
by a step (`smooth<float>`, `0x00136630`). A player is in a muffling zone
when its bZoneMuffleSound (+144) and nZoneCurrent (+88) are both set; the
volume is the first such player's fZoneMuffleVolume (+148). Retail keeps
taking a volume while it is still -1, so a first volume of -1 can be
replaced by a later player's, even one not in a zone.

| case | target | step |
|---|---|---|
| not muted, pRaceCoordinator in state 7 (post-race) | 0.5 | 0.1 |
| not muted, a player in a muffling zone | the zone's volume | 0.05 |
| not muted, the speech manager playing a SED (+1452) | 0.95 in a race, 0.3 in the frontend | 0.1 |
| anything else | 1.0 | 0.2 |

When the value moves, ScaleCategoryVolumes(v, false) runs.

**ScaleCategoryVolumes** (`0x001af638`) does nothing unless the scale has
changed since the last call; the scale is stored either way. It sets
categories 0, 1, 2, 5 and 4 to their saved volumes (`0x00313878`, in that
order) times the scale. The speech category, 6, gets its saved volume,
times the scale only when asked.

## Muting

**sound::Mute** (`0x001af850`) does nothing with sound off. Otherwise it
stores the jukebox's mute. With music on, it pauses or unpauses the
jukebox; a music category turned down to 0 or below stays paused, even
when unmuting. With speech on, the speech manager and SpeechNoise are
muted. Then come sound_scape, MuteCarSounds, sound3d_oneshot,
collision_sound and the chopper, in that order. **MuteReplay**
(`0x001af940`) does the same without the jukebox and speech: the mute
flag, the cars, the one-shots, the collisions, the scapes and the
chopper. **MuteCarSounds** walks the world's car list and calls each
car's pBaseCarSound (+2132) virtual Mute (vtable +32), skipping cars
without one. Retail reads pCurrentWorld in Mute and MuteReplay without a
test.

## The rest

- **GetInGameSample** looks up the "InGame" region once and returns its
  sample by name.
- **PlayCommonRegionSample** plays the common region's sample as a menu
  effect (category 3) at the volume given.
- **TriggerFinishLineSound** plays InGame's "FinishLine" at 1.0.
- **The random helpers** draw from the module's seed.
- **SetAudioMode** passes the mode to bSound::SetMode and keeps it;
  GetAudioMode returns the kept mode.

## The 3DS

main.c owns a SoundModule and binds the SoundHooks:

- the game flow's state and pause, WorldTimeElapsed and a counting
  VBlank;
- the card test, the race coordinator's state, the players' zones, the
  track's and the drivers' car sounds;
- the chopper and the Joylog;
- the card's `SOUND` directory as the path.

Each module's hooks stay NULL until its step binds them. The collision
sounds, the scapes, the car sounds, the one-shots and the speech noise
([speechnoise](speechnoise.md)) are bound. The speech manager and the SED
wedge are not yet.

The frontend's InitFrontendSounds / UnInitFrontendSounds and the menu
sounds (fesound.c) take their samples from these regions. The
FrontendSoundEvent table they use is retail's, `0x002fb098`. The
gameflow loads the frontend's regions before the car selector and
unloads them after it.

## The checker

`tools/sound_check.py` runs retail's Sound.obj in RetailEmu and sound.c
in a host harness (`tools/src/sound_test.c`) over the same script. bSound
is a fake on both sides: a queue of pending regions that the script lets
in by update, by hand or by a raw callback event. The fakes also cover
bRegion::Sample, the jukebox's calls, every module behind SoundHooks
(including each car's Mute through a real vtable on retail's side),
bFileExists, the flashes, the file service and its VBlank, the Joylog and
the drivers. Every one of them prints a line. The script covers:

- the driver up and down, and the wait at every pace;
- the in-game load with every pair of drivers, and the frontend load;
- the regions arriving in every order, and the poll under a recording, a
  replay and the hang;
- the 8 ms gate, DelayedStart, every case of the muffler, and muting under
  each music volume;
- the samples, the random helpers and the mode.
