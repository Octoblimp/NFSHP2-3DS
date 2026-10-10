# sedwedge -- cSEDWedge, between the speech library and bSound

cSEDWedge loads the speech's files into the speech library
([spch](spch.md)). Each update, it plays the best pending event on
channel 0: SPCH_Choose and SPCH_Play hand each chosen clip back as a bank
and an offset. The wedge turns each clip into a bSegment of
`<language>DAT.PCK`. PlaySentence then hands the segments to the
bSampleChain as one sentence ([bsound](bsound.md)), which streams them off
the card ([bsndstream](bsndstream.md)).

Retail has it in sedwedge.obj (`indep/src/speech/sedwedge.cpp`),
`0x002056f0` .. `0x00206760`, with bSegment at `0x002761d0` ..
`0x00276564`. Sound.obj makes the wedge and loads and unloads its files.
The port has all of it in `sedwedge.{c,h}`, and `tools/sedwedge_check.py`
runs retail's code against it.

| function | retail |
|---|---|
| LoadDataFile | `0x002056f0` |
| AddSentencePart | `0x002057d8` |
| cSEDWedge (the constructor) | `0x00205888` |
| S_AbortMessage, S_DebugPrint, S_TimerGetTick | `0x00205998`, `0x002059d0`, `0x00205a00` |
| S_TestSentenceRule, S_SetSentenceRule | `0x00205a18`, `0x00205a20` |
| S_SentencePartRequest, S_SampleCallback, S_WriteEVLog | `0x00205a28`, `0x00205a58`, `0x00205ae0` |
| Initialize | `0x00205ae8` |
| Fade, Mute, Cleanup | `0x00205da8`, `0x00205e00`, `0x00205e58` |
| GetEventPending, QueueSentenceEvent | `0x00205f48`, `0x00205f90` |
| PlaySentence, StopSentence, ClearEventQueue | `0x00205fd8`, `0x00206140`, `0x00206190` |
| Update | `0x002061e8` |
| bSegment: constructor, Initialize, Cleanup, GetOffset, GetSize | `0x002761d0`, `0x00276388`, `0x00276470`, `0x00276500`, `0x00276538` |
| Sound.obj: the wedge's creation (in InitializeSoundDriver) | `0x001ae754` |
| Sound.obj: LoadLocalizedSpeechFiles, UnLoadLocalizedSpeechFiles | `0x001ae4d8`, `0x001ae5e8` |

Not ported, because nothing calls them: the destructor (the wedge is never
deleted), isPlaying and IsPlaying (`0x00206720`, `0x00206740`, the same
code), and bSegment's empty destructor.

## The files

They are under `SOUND/SPEECH/`, and the language's name begins each one:

- **EVENTS.EVT**, the event dat, the same for every language ([spch](spch.md)).
- **`<language>BAN.PCK`**, the banks, with a 16-byte entry for each:
  - word 0 is the count in the first entry, and the bank's handle once
    the wedge has added it;
  - word 1 is the bank's offset in the BAN file;
  - word 3 is the bank's base in the DAT file.

  [spch](spch.md) has the layout.
- **`<language>DAT.PCK`**, the clips' audio. ENGLISHDAT.PCK is 303 MB.
  Each clip is a 48-byte VAG header and then SPU ADPCM.
- **`<language>HDR.pck`** is named, but nothing reads it. It is not on
  the disc.

The languages are English, French, German, Italian and Spanish. The game's
sixth language, Swedish, gets English. The two after that get nothing.

## The records

**bSegment**, 276 bytes, is one clip:

| at | what |
|---|---|
| 0 | the name, 256 bytes: `Segment`, or `<Not Initialized>` |
| 256 | initialized |
| 260 | the clip's offset in the DAT file, at its VAG header |
| 264 | the clip's size, header and all |
| 268 | always 0 |
| 272 | Initialize's flags, always 0 |

**cSEDWedge**, 2180 bytes on the PS2, has its vtable at 2176. The port's
record has none, but the other offsets are the same, and sedwedge.h's
layout check holds them on the 3DS.

| at | what |
|---|---|
| 0 | m_pInitialized |
| 4, 8 | the BAN file, twice: m_pBankFile and m_SpeechBank |
| 12 | the number of banks |
| 16 | the game number, 0 |
| 20 | the bank pointer memory the library is handed |
| 24 | EVENTS.EVT, loaded whole |
| 28 | the DAT file's bFile |
| 32 | the DAT file's name, 32 bytes |
| 64 | the library's ext vecs |
| 68 | ten bSegments |
| 108 | the number of segments queued |
| 112 | the sentence's sample, a bSampleChain |
| 116 | the slot, NULL, and never read |
| 120 | the status |
| 124 | the event log's buffer, 2048 bytes |
| 2172 | the pause state |

**The status** is one of these values:

- 1, idle;
- 2, a sentence playing;
- 32, the sentence's sample has stopped. The sample's callback sets it
  with event 8, and the next update makes it 1 again.

Update and the mutes also test for 8, which nothing sets.

**The statics:**

| gp offset | what |
|---|---|
| -16544 | m_pInstance, the wedge the callbacks use; the constructor sets it |
| -16548 | the clock in milliseconds, a float |
| -19016 | Sound.obj's wedge |
| -19044 | Sound.obj's slot, never set |

## The functions

- **The constructor** sets the status to idle. It clears the pause, the
  bank count, the bank memory, the ext vecs, the events, the sample, the
  initialized flag and the DAT's bFile. It also zeroes the clock and makes
  this wedge m_pInstance.
- **Initialize(events, hdr, dat, ban, slot)** runs these steps in order:
  1. It sets the game number to 0 and keeps the slot.
  2. It takes the BAN whole (bGetFile, pool 16), and reads the count from
     the first word.
  3. It opens the DAT and copies its name.
  4. It brings the library up (SPCH_Init) with the part request, game 0
     and the data rate for 22050 Hz, 16 bits, mono.
  5. It takes the bank pointer memory for 2000 banks and hands it to the
     library.
  6. It sets the abort, print and tick vectors, then the event log (2048
     bytes) and the rule callbacks.
  7. It loads EVENTS.EVT and resolves it. A failure in either sets
     initialized to 0 and returns 0.
  8. It asks for the dat's info, which it does not use.
  9. It adds each bank at its offset in the BAN file and writes the
     handle over the entry's first word.
  10. If there is no chain sample yet, it makes one, at 24000 Hz.
  11. It makes ten segments.
  12. It clears the event queue twice and unmutes.
  13. It sets initialized to 1 and returns 1.
- **AddSentencePart(bank, offset, size)**, from SPCH_Play's requests,
  ignores a bank outside the table. Otherwise it cleans up the next
  segment and fills it: the bank's DAT base plus `offset`, and `size`.
- **Update** runs only when the wedge is initialized and not paused:
  1. It sets the clock to `RealTimeFrames * (1/60) * 1000`, in that order,
     in floats.
  2. It makes a stopped status (32) idle.
  3. If the status is idle (or 8), and channel 0 has an event pending, it
     calls QueueSentenceEvent and then PlaySentence.
- **QueueSentenceEvent(channel)** calls SPCH_Choose and SPCH_Play. Their
  requests come back through AddSentencePart.
- **PlaySentence** runs these steps:
  1. A playing or stopped sentence is stopped and made idle.
  2. If there are segments, it gives the chain category 6 (the speech's)
     and its callback.
  3. It empties bSound's path, because the DAT name is a whole path.
  4. It adds each segment to the chain, past its 48-byte header: from
     `offset + 48` for `size - 48` bytes. The last segment starts the
     chain.
  5. It puts the path back, empties the segments and sets the status to
     playing.

  The channel and the volume are not used.
- **The sample's callback (S_SampleCallback)** handles two events:
  - event 4, the stream's start, plays the chain at 1.0 if SoundEnabled
    and the speech are on, then sets its volume to 1 either way;
  - event 8 marks the sentence stopped.
- **StopSentence** stops the chain and makes the wedge idle.
- **ClearEventQueue** empties the library's queue, and stops a sentence
  that is not idle. The finish calls it once every player is finished.
- **Fade**, with SoundEnabled, stops a playing or stopped sentence; the
  fade is ignored.
- **Mute(on)** pauses or resumes a playing or stopped sentence, and keeps
  `on` either way.
- **Cleanup**, if the wedge is initialized, runs these steps:
  1. It takes the library down.
  2. It closes the DAT.
  3. It frees the BAN (zeroing the count), the events, the bank memory and
     the segments.
  4. It stops the chain, which is kept for the next Initialize.
- **GetEventPending**, **QueueSentenceEvent**, **PlaySentence**,
  **StopSentence** and **ClearEventQueue** do nothing unless initialized
  is exactly 1, and return 0. Update runs whenever initialized is not 0.
- **The clock (S_TimerGetTick)** is the clock cut to a whole millisecond.
- **The rule test** passes nothing. The rule set, the print and the event
  log's write do nothing.

**Sound.obj:**

- **InitializeSoundDriver** ends by making the wedge: bMalloc(2180, 388,
  16), then the constructor, then it is kept at gp-19016.
- **LoadLocalizedSpeechFiles(language)**, with SoundEnabled, does nothing
  for a language past the table. Otherwise it names the language's HDR,
  BAN and DAT. With the speech on, it initializes the wedge on
  `Sound\Speech\Events.evt` and them. The gameflow calls it when the
  speech comes in or the language changes.
- **UnLoadLocalizedSpeechFiles**, with SoundEnabled, cleans the wedge up.

## What the port changes

- **A missing BAN.** The port's bGetFile stops the game on a missing
  file, as retail's assert does. Initialize asks for the BAN's size
  first. If there is none, it returns 0 and initialized stays 0. This
  happens after the game number and the slot are set. So a card without
  `SOUND/SPEECH` plays no speech.
- **A full pool.** Retail constructs the chain on whatever the pool
  answers. The port's Initialize returns 0 there, with initialized 0.
- **More than ten parts.** Retail writes past its ten segments, over the
  count. The port drops the extra parts. No sentence has more than five
  phrases.
- **The DAT name** ends at byte 31 of its 32. Retail ends it at byte 32,
  the ext vecs' first byte, which it then writes over.
- **The path** that PlaySentence puts back is the port's sound path, the
  card's SOUND directory, where retail puts back "sound\\".
- **The abort message** goes to stderr, where retail sends it to the
  debug channel.
- **Load and unload** do nothing when there is no wedge.

main.c binds sound's `sed_create` and `sed_update`, the gameflow's
`loadSpeech` and `unloadSpeech`, and playerfinish's
`gSpeechClearEventQueueFn`.

## The check

`tools/sedwedge_check.py` runs retail's sedwedge.obj, bSegment and
Sound.obj's load and unload in RetailEmu, over printing fakes. The fakes
cover:

- bFile's Open, FileSize, Read, Close and GetFile, over a few made-up
  files;
- bMalloc and the frees;
- the speech library's calls;
- the chain sample's calls;
- bSound's SetPath.

The script covers:

- the constructor over a filled record;
- everything asked of a wedge that is not loaded;
- Initialize with the events missing, ResolveData failing, the BAN
  missing, the pool full, bGetFile answering nothing over a stale count,
  and in full, twice;
- clips in and out of the banks' range, by hand and through SPCH_Play,
  up to ten;
- updates in every status, at clocks where other float orders would
  round differently;
- play, stop, clear, fade and mute in each state;
- the sample's events;
- a segment cleaned up by hand, and the rule callbacks;
- the initialized flag at 0 and at 7;
- each language and past them, with the sound and the speech off.

The port's own paths (the missing BAN and the full pool) are written into
the model by hand. Retail would stop at both. The check answers 300 ops,
1329 lines, 0 differ. Of 195 mutations, 193 are caught and 2 are
equivalent:

- the tick's cast, because on the host a negative float converts the
  same both ways;
- the size of the wedge's own bMalloc, which is the host's.
