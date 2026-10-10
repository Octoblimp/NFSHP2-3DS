# The speech's stream

The cops' and the dispatcher's speech is streamed off the disc, a clip at a
time. On the PS2 the IOP read it: bSnd_VoicePlay's "_STREAM" and "_CHAIN"
paths hand it a chain of file parts (docs/formats/sound-driver.md, "Streams
and the queue"), and SOUND_PlayStream and SOUND_ChainStreams play them on
one SPU voice, one after another. On the 3DS, `3DS Files/source/bsndstream.c`
does the IOP's half. It is checked by `tools/bsndstream_check.py`.

## ENGLISHDAT.PCK

`SOUND/SPEECH/ENGLISHDAT.PCK` (303,441,517 bytes on the retail disc;
FRENCHDAT and GERMANDAT are the other languages) is the speech's clips:

- The first 256 bytes are a header of the file's own. The first clip
  starts at byte 256.
- There are 10,126 clips, each at a multiple of 256 bytes, with zeros
  between one clip's end and the next.
- Each clip is a VAG: a 48-byte header ("VAGp", then big-endian words:
  the data's size at +12 and the rate at +16), then the data.
- Every clip is mono SPU ADPCM at 24000 Hz: 16-byte frames of 28 samples.
- Every frame's flag byte is 0. No clip marks its own end, so a part ends
  at its size.

The speech's banks (ENGLISHBAN.PCK, docs/formats/spch.md) give each clip's
offset and size. bSampleChain hands those to the driver, so a part's
offset is the clip's first data byte and its size the data's.

## The decoder

`bss_decode` is the SPU's decoder, run on the ARM11, and it builds on the
host too:

- A frame's first byte is the predictor (high nibble) and the shift (low
  nibble). Its second byte is the flag. Its other 14 bytes are 28
  nibbles, low nibble first.
- Each sample is the nibble shifted into the top of a 16-bit word, shifted
  right by the shift, plus `(f0·h1 + f1·h2 + 32) >> 6`. The result is
  clamped to 16 bits. The predictor pairs are Sony's, scaled by 64:
  (0, 0), (60, 0), (115, −52), (98, −55) and (122, −60).
- A predictor above 4 is taken as 0, as the SPU does, rather than read past
  the table.
- A frame flagged 7 is not decoded, and ends the part. A frame flagged 1
  is decoded, then ends it. These are `audio_convert.py`'s rules.
- The history (the last two samples) carries across calls, and across a
  chain's parts, as the SPU's did. A new stream starts from silence.

The checker holds the decoder to `audio_convert.decode_adpcm`. It uses 48
windows of ENGLISHDAT.PCK and 64 made-up inputs, which have every
predictor and the end flags. Each input is handed to the decoder in random
runs of frames. Result: 112 inputs, 0 differ.

## The worker

The driver's sink hands `bsndstream_play` the channel, the parts and the
rate. Then:

1. `bsndstream_play` stops whatever stream was playing and sets the
   channel up as a patch's is: linear interpolation, the rate, and mono
   PCM16 rather than DSPADPCM. The driver sets the mix straight after.
2. The worker thread does the reading, so the game's frame never waits on
   the card. Its priority is one above the game's thread, as the jukebox's
   worker's is. It wakes when a stream starts, and every 10 ms.
3. It keeps eight waves queued on the channel. Each wave holds 128 frames:
   3584 samples, 149 ms at 24 kHz. Each read off the card is 2 KB.
4. Each part opens its file. A part in the same file as the one before
   keeps the file open, which is the speech's case. The worker seeks to
   the part's offset and reads up to its size: to the file's end when the
   size is 0. A frame cut short by either is dropped.
5. A part that cannot be opened or sought is skipped.
6. Paths: one with a ':' is the card's own. Any other is under the game's
   data directory, with '\' read as '/'.

`bsndstream_playing` is true from `bsndstream_play` until the last part's
last wave has played, or the stream is stopped. The sink's `hw_playing`
answers with it for the stream's channel rather than with
`ndspChnIsPlaying`, because ndsp can run dry between two waves while the
worker reads. So bsnd_update does not free the voice in mid-sentence.

A patch started on the stream's channel stops the stream first, and so
does a stop on that channel. Stopping clears the channel's waves and
waits up to 20 ms for the DSP to let go of the one it was reading.

When the worker or its buffers cannot be had, every call is a no-op and
the speech is silent.
