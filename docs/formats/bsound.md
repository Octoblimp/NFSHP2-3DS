# bSound -- samples, regions and voices

bSound is EA's sample library. It sits between the game and the bSnd
voice layer ([sound-driver](sound-driver.md)). Every sound the race makes
is a **bSample**: the engines, sirens, horns, tyres, collisions, the world
and the speech. A bSample names a patch in a bank. It keeps its own volume,
pan, pitch, fade and category. It takes a voice when it plays and gives
the voice back when it stops. A **bRegion** is a loaded bank with one
bSample per patch in it. **bSound** is the one instance that owns the
regions, and **bVoiceMgr** keeps track of which sample holds which channel.

Retail has the library at `0x002716f8` .. `0x0027c730`
(src/bSample.cpp and src/bSound.cpp). The port has it in
`bsound.{c,h}`. `tools/bsound_check.py` runs retail's own code in mipsemu
against the port, both over the same scripted fake driver. The library is
-O0 code, so the port follows it statement by statement, quirks included.

| function | retail |
|---|---|
| bRegion::bRegion(const char*) | `0x002716f8` |
| bRegion::~bRegion | `0x00271840` |
| bRegion::Sample(char*) | `0x002719b8` |
| bSample::bSample / bSample(char) | `0x00272ff0` / `0x00273098` |
| bSample::~bSample | `0x00273148` |
| bSample::Initialize (copy, callback, name+bank) | `0x00273210` / `0x00273280` / `0x002732c0` |
| bSample::LockVoice | `0x00273388` |
| bSample::SetPan / CalcPan | `0x00273648` / `0x002736c8` |
| bSample::SetPitch / CalcPitch | `0x00273738` / `0x00273850` |
| bSample::SetScaleVolume / GetScaledVolume | `0x00273be8` / `0x00273c80` |
| bSample::SetVolume / CalcVolume / GetVolume | `0x00273d50` / `0x00273ed8` / `0x00273f58` |
| bSample::Play(char*, uint, uint) / Play(float, float, float) | `0x00273ff8` / `0x00274080` |
| bSample::IsPlaying / Pause / Stop | `0x00274410` / `0x00274488` / `0x00274618` |
| bSample::Mute / Fade / GetChannels / Update | `0x002747a0` / `0x00274868` / `0x00274960` / `0x00274a98` |
| bSound::bSound / Initialize / Update | `0x002776c0` / `0x00277820` / `0x002778f8` |
| bSound::Region / LoadRegion / UnloadRegion | `0x00277a18` / `0x00277b00` / `0x00277c00` |
| bSound::SetCategoryVolume / SetPath / SetMode | `0x00277cb0` / `0x00277e38` / `0x00278190` |
| bSound::updatePendingRegions | `0x00277f38` |
| bVoiceMgr::Initialize / GetVoice / ReleaseVoice / Update | `0x0027ac80` / `0x0027ad00` / `0x0027af48` / `0x0027b2f0` |

## The objects

**bSample** is 188 bytes. Samples come from a slot pool of 255
("bSoundSamples", gp-13816), which clears each slot when it hands it out.
A class can also hold one by value, and then the constructor runs on
storage the owner provides.

| offset | field | |
|---:|---|---|
| 0 | rate | the rate CalcPitch scales, for a sample with a type |
| 4 | nearEndNotified | set once event 4 has been raised |
| 12 | voice | the bVoice it holds, or NULL |
| 16, 20 | offset, size | Play(char*, ...)'s |
| 24 | currentVolume | |
| 28 | scaleVolume | |
| 32, 36 | fadeTarget, fadeAdjust | the fade's target and its step per update |
| 40, 44 | currentPan, currentPitch | |
| 48, 52 | callback, callbackData | |
| 56, 88 | name, bankName | 32 bytes each, 31 characters copied |
| 120 | volumeBeforeMuting | u16 |
| 124, 128 | muted, paused | |
| 132 | category | 0..15 |
| 136 | type | s8: 0 for a bank's patch |
| 140, 144 | voiceLock, voiceLockPlaying | |
| 148 | sampleId | bSnd_GetPatchID's, 0xfffa when there is none |
| 184 | vtable | |

The constructor leaves five fields alone: the fade target, the callback's
word, the muting volume, the locked-playing flag and the rate. A pool slot
comes back cleared. A sample held by value keeps whatever its owner put
there.

**bRegion** is 64 bytes, from a pool of 32 ("bSoundRegions"). It holds a
name of up to 32 characters and a vector of its samples, in the bank's
patch order. Its constructor makes one type-0 sample per patch. Its
destructor deletes them front first, then unloads the bank.

**bSound** is 456 bytes at `0x00336900`, and gp-13696 points at it. It
holds the common region (+4), the status (+8, 1 once Initialize has run),
16 category volumes (+12), the client's callback and word (+76, +80), one
pending region's name (+84, 256 bytes), the pending count (+340), the
regions (+344) and the path (+392, 63 characters).

**bVoiceMgr** keeps 48 records of 8 bytes at `0x00327c88`: a channel
number and the sample that holds it.

## Loading a region

`LoadRegion(name)` starts the bank's load, then looks at the pending
count. So a second region asked for while one is pending is read in, and
then refused with 0. When the count is 0 the name is made pending and
the call answers 1. Each `Update` checks the pending name: once
`bSnd_GetIsBankLoaded` says the bank is in, it makes the bRegion,
remembers it as the common region when it is named "common", appends it,
clears the pending slot and calls the client with event 2.

`UnloadRegion` deletes the first region of that name. It does not clear
the common region pointer when the common region is the one unloaded.

A name with no region still goes to the vector's `erase`, as NULL, and
that does something (see the next section): with room past the count, the
last region drops out of the vector without being deleted. The game's
only caller, UnLoadSoundRegions (`0x001af420`), unloads only the names it
has recorded loading, but a region still pending when it runs has no
bRegion yet.

## The vectors

The regions (+344 in bSound) and each region's samples (+40) are
`bFragmentedVector<T*>`s: a list of fragments, each a block of slots that
never moves. `GrowArrayTo(n)` adds one fragment for the slots missing;
bSound::Initialize asks for 16 regions that way. `pushBack` on a full
vector grows it to twice its slots (1 when empty), so a region's samples
take fragments of 1, 1, 2, 4, 8 and so on. Fresh slots are whatever
bMalloc gives.

The fragments are invisible from outside, but two other things are not:

- **`find`** looks at every slot of every fragment, the ones past the
  count included, and answers the first match or -1. Slots past the count
  keep what was last in them.
- **`eraseAt(i)`** (`0x00279b10`) moves every slot from `i` up down by
  one, across fragments, and leaves the last slot as it was. The count
  goes down even when `i` was past it. An index past the last slot is
  warned about and changes nothing.

So `erase(NULL)`, which UnloadRegion makes for a name with no region,
finds the first empty slot past the count, as long as the vector hasn't
been full since it last grew, and the count goes down by one. On an empty
vector the count goes to -1. From then on the vector is broken: the next
`pushBack` writes before the first slot, and anything that loops over the
count (`Region(name)` among them) runs on past every fragment and never
returns.

## Playing

`Play(volume, pan, pitch)` runs in this order:

1. If the sample has a voice: it gives up when that voice is 0xfffa (a
   LockVoice that failed), and stops the voice if its channel is busy.
2. If it has none: it asks GetChannels (0 gives up), locks that many
   channels from the top down, and takes a record from the voice manager.
3. It stores the volume, pan and pitch, computes the pitch, the volume and
   the pan in that order, and calls bSnd_VoicePlay.
4. It sets voiceLockPlaying and clears paused.

The voice manager's `GetVoice` first looks for a record already holding
that channel. It takes that record from its old sample and gives it to the
new one. Otherwise it gives out the first empty record.

`Stop` clears voiceLockPlaying and stops the channel. Unless the voice is
locked, it then unlocks the channels and gives the record back. Either
way the client and the sample's own callback get event 8, and paused is
cleared.

The voice manager's `Update` goes over every held record. A record whose
channel has gone quiet is stopped, except when its sample locked the voice
and is not playing on it. Then every held sample gets its own Update.

`GetChannels` answers the patch's channel count. A bank whose name starts
with `_` is a stream instead: `_STREAMS` and `_MOVIE` count as stereo,
`_STREAM` as mono, and any other `_` bank gets 0.

## Volume, pan and pitch

- **The scaled volume** is the patch's volume (16383 for a sample with a
  type) times its category's volume, times the reciprocal of 16383 as the
  compiler rounded it (`0x1.0004p-14`), times scaleVolume.
- **CalcVolume** is volume times the scaled volume times 16383, truncated
  and then saturated by sign as the EE does.
- **SetVolume** does nothing without a voice: the volume isn't even
  remembered.
- **GetPitch** answers currentVolume. SetCategoryVolume depends on that: it
  sets each playing sample of the category to `GetPitch()`, which re-applies
  the volume it already has under the new category.
- **CalcPan** is pan times 255, truncated to a signed byte.

**CalcPitch** takes the patch's rate (or `rate` for a sample with a type)
and scales it by a ratio:

- The semitone is the pitch truncated into a signed byte. If it is 7 or
  more either way, the pitch is clamped to ±7.0.
- Between −2 and +2 octaves the ratio comes from a 257-entry table at
  `0x00327a80`: `4096·2^((i−128)/64)`, a 64th of an octave per step. It
  is read one step high, so pitch 0 reads 4140 rather than 4096 and plays
  18.75 cents sharp. Pitch +2.0 reads the word past the end of the table,
  which is the padding before the voice records and is always 0.
- Outside that range the ratio is the octave's power of two (a 16-entry
  table at `0x00327a38`) plus a straight line towards the next octave. The
  slope comes from the octave above when rising and the octave below when
  falling.

## Fades and the stream poll

`Fade(volume, ms)` does nothing without a voice. Under 33 ms it sets the
volume straight to `scaled·volume`. Otherwise:

- the target is `volume·scaled`;
- the step is `(target − current) / (ms · 0.0599880)`, one step per
  Update, which runs at 60 updates a second.

The target is in scaled terms and the current volume is not, so a fade
towards 1.0 of a quiet patch steps down to it.

`Update` only does anything while a fade is in progress. It steps the
volume and stops at the target. Then, still inside the fade, it asks
the driver whether the voice's stream is still going (`0x00263090`), and
raises event 4 once if it is and the sample has a callback. So a stream
that isn't fading never raises event 4.

## The speech's samples

The speech plays through two bSamples of its own, both of type 1, so
CalcPitch scales the sample's own rate rather than a patch's.

- **bSampleStream::SetSampleRate** (`0x00280340`) sets that rate.
  `bsample_set_rate`.
- **bSampleChain** is what cSEDWedge::Initialize builds inline at
  `0x00205cb4`: a pool sample made with bSample(1), its bank and name
  both "_STREAM", and LockVoice, so it keeps its voice for good. The
  wedge sets the rate (24000) after. `bsample_chain_new`.
- **AddToChain** (`0x00206760`) takes a file, an offset, a size and
  whether this is the last part. A part that is not the last is queued:
  CalcPitch, CalcVolume and CalcPan at the sample's current three, then
  the driver's 7-word overload (`0x00260d98`) on the "_CHAIN" bank,
  which lets the driver choose the voice. The last part is played by
  name, offset and size, which ends the queue and plays it.
  `bsample_chain_add`.
- **Play with an offset or a size** goes through the overload that
  takes a part of a file (`0x00260ce8`). `bsnd_voice_play_part`.

The driver's side, "_STREAM", "_CHAIN" and PlayChain, is in
docs/formats/sound-driver.md, "Streams and the queue".

## The port

The port is retail's code over bsnd.c. These things differ:

- bSound's `driver` is the port's own field, standing in for retail's
  bSnd globals.
- `bsound_init` is the constructor and Initialize together. It runs
  bSnd_Initialize's half already done, since bsnd_hw_init has done it.
- The bFragmentedVectors are each one growing block. Everything outside
  can see is retail's: find over every slot, the erase above, the
  doubling. bmem's bMalloc clears what it hands out, as a fresh heap is.
- An erase on an empty vector does nothing, where retail's count goes to
  -1 and the next region lookup never returns.
- Play gives up when all 48 records are held. Retail asserts and carries
  on into a NULL voice. 48 locked runs cannot happen on 22 channels.
- The debug output is left out: bSound::Printf, the voice manager's
  allocation log, and the asserts.

Not ported, because nothing calls them: GetPan (which reads the
event-4 flag), GetSampleVolume (which reads the callback), GetFlags and
IsLooping. Event 4 is `BSOUND_SAMPLE_STREAM_ACTIVE`: retail's poll asks
whether the stream is still going, not whether it is near its end.
