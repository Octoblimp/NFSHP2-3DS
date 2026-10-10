#pragma once
// The speech's stream: the 3DS end of bSnd's mono stream, which bsnd.c's
// sink hands a chain of parts -- what SOUND_PlayStream and
// SOUND_ChainStreams were handed on the PS2.
//
// SOUND/SPEECH/ENGLISHDAT.PCK is VAG clips back to back: a 48-byte header,
// then mono SPU ADPCM, 16-byte frames of 28 samples, at 24000 Hz. The
// driver's parts start past a header and stop at the clip's end. This reads
// them off the card on a worker thread, decodes them to PCM16 and queues it
// on the voice's own ndsp channel, one part straight after another, so a
// sentence plays as one sound.
//
// The decoder half builds on the host, for tools/bsndstream_check.py, which
// holds it to audio_convert.py's decoder over clips from the disc.
#include <stdbool.h>
#include <stdint.h>

#include "bsnd.h"

#define BSS_FRAME    16u      // SPU ADPCM: 16 bytes...
#define BSS_SAMPLES  28u      // ...for 28 samples

typedef struct {
    int32_t hist[2];          // the last two samples
    bool    ended;            // the part's SPU end has been reached
} BssDecoder;

// Clears the history too: a stream starts from silence.
void bss_decoder_reset(BssDecoder* d);

// Up to `frames` frames at `in`, 28 samples each to `out`. A frame flagged
// 7 is not decoded and ends the part; one flagged 1 is, and ends it after --
// audio_convert.py's rule. Returns the frames decoded.
uint32_t bss_decode(BssDecoder* d, const uint8_t* in, uint32_t frames,
                    int16_t* out);

#ifdef __3DS__

// Makes the worker and its buffers. False when either cannot be had, in
// which case every call below is a no-op and a stream is silent.
bool bsndstream_init(void);
void bsndstream_exit(void);

// The parts on ndsp channel `ch`, one after another, at `rate`, from the
// card: a path with a ':' is the card's own, any other is under the data
// directory, '\' or '/'. Whatever was streaming stops first.
void bsndstream_play(unsigned ch, const BsndStreamPart* parts,
                     unsigned count, uint32_t rate);

// Stops the stream if `ch` is its channel.
void bsndstream_stop(unsigned ch);

// Whether `ch` is the stream's channel and the chain still has audio to be
// heard: true from bsndstream_play until the last part's last sample has
// played or the stream is stopped.
bool bsndstream_playing(unsigned ch);

// Whether the stream is on `ch` at all, playing or not.
bool bsndstream_owns(unsigned ch);

// For the log: parts opened, bytes read and samples queued since init.
typedef struct {
    uint32_t parts, bytes, samples;
} BssStats;
void bsndstream_stats(BssStats* out);

#endif
