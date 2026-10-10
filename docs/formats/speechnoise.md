# speechnoise -- the radio's squelch and static

SpeechNoise is the radio around the cop speech. It has two squelches, one
of which plays at random as a message starts. It also has seven bursts of
static, one of which plays now and then while the radio is on. The
samples are the in-game region's, and they are looked up once the regions
are in.

Retail has it in SpeechNoise.obj, `0x002155d8` .. `0x00215a5c`, with its
getInstance at `0x001b0188`. The port has it in `speechnoise.{c,h}`, and
`tools/speechnoise_check.py` runs retail's code against it.

| function | retail |
|---|---|
| getInstance | `0x001b0188` |
| SpeechNoise / ~SpeechNoise | `0x002155d8` / `0x002155f0` |
| LoadSamples / RequestSamples / UnLoadSamples | `0x00215610` / `0x00215770` / `0x00215780` |
| Update / Mute | `0x002157c0` / `0x002158a0` |
| Start- / StopHelicopterNoise | `0x00215930` / `0x00215958` |
| Start- / StopRadioNoise / IsRadioNoise | `0x002159a0` / `0x002159b0` / `0x002159b8` |
| BeginSquelchNoise / IsSquelchNoisePlaying | `0x002159c0` / `0x00215a08` |

## The record

**SpeechNoise** is 52 bytes:

| at | what |
|---|---|
| 0 | Helicopter, a bSample |
| 4 | Squelch[2]: "RadioNoiseSquelch01" and "02" |
| 12 | Radio[7]: "RadioNoise01" .. "07" |
| 40 | RadioNoiseOn |
| 44 | RequestSampleLoad |
| 48 | SpeechNoiseMuted |

**The instance.** getInstance builds a static at `0x003341d0` on its
first call, guarded by gp-19072, and registers the destructor with atexit.
Retail has two more copies of getInstance (`0x0020bd80` and `0x0020bea8`),
each over its own static, from other objects that inline the header.
Nothing calls them.

**The helicopter's sample** is never set: LoadSamples does not look one
up. The demo's LoadSamples is 32 bytes longer. So the helicopter's noise
never plays, though speech::mgr_t's helicopter action still asks for it.

## The functions

- **The constructor** clears the radio flag, the request, the helicopter's
  sample and the mute. The squelches and the static are left as they are.
- **LoadSamples** takes bSound's "InGame" region and, from it, the two
  squelches and the seven bursts in that order. Each gets category 6,
  the speech's. Then the request is cleared.
- **RequestSamples** sets the request. LoadSoundRegionsInGame calls it.
- **UnLoadSamples** stops the helicopter's noise if it has a sample, turns
  the radio off and clears the helicopter's sample. UnLoadSoundRegions
  calls it.
- **Update**, from sound::Update:
  1. With a request and the regions in (IsSoundRegionLoadingComplete), it
     loads the samples.
  2. While the regions are still loading, while muted or with the radio
     off, it stops there.
  3. A draw of `random(1.0) < 0.03` (gp-27372) plays one burst. The volume
     is `random(0.4) + 0.6` (gp-27368, gp-27364), and the burst is
     `random int(7)`, skipped if missing. It plays at pan 0, pitch 1.0.
  The randoms are sound's own (`0x001af9c0`, `0x001af9a0`).
- **Mute(on)** stores `on`, then pauses or resumes each burst there is,
  0 to 6, and the helicopter's sample if there is one. The squelches are
  not paused.
- **StartHelicopterNoise** plays the helicopter's sample, if there is one,
  at 1.0, pan 0, pitch 0. **StopHelicopterNoise** stops it if there is one
  and it plays.
- **StartRadioNoise** and **StopRadioNoise** set and clear the radio flag.
  **IsRadioNoise** answers it.
- **BeginSquelchNoise** plays squelch `random int(2)` at 1.0, pan 0,
  pitch 0, without a test for a missing one.
- **IsSquelchNoisePlaying** answers whether the first squelch plays, or
  else the second.

## Who calls it

- sound.c, through its hooks, bound in main.c: RequestSamples from
  LoadSoundRegionsInGame, UnLoadSamples from UnLoadSoundRegions, Update
  from sound::Update and Mute from sound::Mute (with speech on).
- speech::mgr_t (step 14-9) turns the radio on and off, and stops the
  helicopter's noise in its update and FlushQueue. Its actions
  (`0x0020be0c`, `0x0020be64`) begin the squelch and start the
  helicopter's noise ([speechmgr](speechmgr.md)).

## What the port changes

- **A missing squelch.** IsSquelchNoisePlaying does not ask whether a
  missing squelch plays, where retail does. The port's bsample_is_playing
  would read through NULL. BeginSquelchNoise hands a missing one to
  bsample_play, as retail does. The port's bsample_play skips it.
- getInstance does not register the destructor, which frees nothing.

## The check

`tools/speechnoise_check.py` runs retail's SpeechNoise.obj, with
Sound.obj's IsSoundRegionLoadingComplete, over printing fakes:
bSound's Region, bRegion's Sample, bSample's SetCategory, Play, Pause,
Stop and IsPlaying, and the sound's randoms and its loading flag. The
script covers:

- the instance and its guard;
- the constructor over a filled record;
- updates while loading, with the radio off, muted, and on with the draw
  at, under and over 3%;
- the samples asked for while loading and once in, with the region and
  some samples missing;
- each burst;
- mutes with and without the helicopter's sample;
- the helicopter's noise with its sample playing, stopped and missing;
- each squelch, present and missing, and IsSquelchNoisePlaying in every
  case;
- unloads.

The harness's IsPlaying complains if it is asked of a missing sample. It
answers 175 ops, 433 lines, 0 differ. Of 67 mutations, all 67 are caught.
