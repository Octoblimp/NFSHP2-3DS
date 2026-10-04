#pragma once
// The jukebox's sample: the 3DS end of retail's bSampleStream, which
// jukebox.c drives through a JBHost.
//
// A tune on the cartridge is a VAG header then stereo SPU ADPCM, 0x8000-byte
// blocks alternating left and right. Its last pair of blocks carries the
// SPU's end: flag 1 on a frame in each channel, then flag 7 on the next.
// This reads the pairs off the card on a worker thread, decodes them to
// interleaved PCM16 and queues it on its own ndsp channel, which bsnd and the
// boot movies leave alone.
//
// The decoder half builds on the host, for tools/jbstream_check.py, which
// holds it to audio_convert.py's decoder over a tune from the disc.
#include <stdbool.h>
#include <stdint.h>

#include "jukebox.h"

#define JBS_BLOCK    0x8000u                  // one channel's interleave
#define JBS_PAIR     (2u * JBS_BLOCK)
#define JBS_FRAME    16u                      // SPU ADPCM: 16 bytes...
#define JBS_SAMPLES  28u                      // ...for 28 samples
#define JBS_FRAMES   (JBS_BLOCK / JBS_FRAME)  // 2048 frames a block

// ndsp's channel for it: bsnd has 0..21 (BSND_HW_VOICES), the movies 23.
#define JBS_CHANNEL  22

typedef struct {
    int32_t  hist[2][2];      // each channel's last two samples
    uint32_t frame;           // the pair's next frame, 0..JBS_FRAMES
    bool     ended;           // the SPU's end has been reached
} JBSDecoder;

void jbs_decoder_reset(JBSDecoder* d);

// Up to `frames` frames of the pair from where the decoder is, each 28
// stereo samples at out. A frame flagged 7 is not decoded and ends the
// tune; one with bit 0 of its flag set (1, 3) is, and ends it after. Returns
// the samples a channel wrote; the decoder's frame reaches JBS_FRAMES when
// the pair is used up.
uint32_t jbs_decode(JBSDecoder* d, const uint8_t* pair, int16_t* out,
                    uint32_t frames);

#ifdef __3DS__

// Opens the jukebox's host: its sample on JBS_CHANNEL, reading the card
// through gamedata. `volumes` is bSound's category volumes, 16 of them,
// which the sample's category picks from; `log` hears of a retail assert.
const JBHost* jbstream_host(const float* volumes, void (*log)(int line));

// Once a frame on the main thread: the fade moved on, the volume set, and
// what the worker saw handed to the jukebox as the sample's events.
void jbstream_poll(JBPlayer* p);

// What the stream has done since it was made, for the log: the pairs read
// off the card, the stereo samples queued, the ones ndsp handed back
// played, and the channel's volume now.
typedef struct {
    uint32_t pairsRead, samplesQueued, samplesPlayed;
    float    mix;
} JBStreamStats;
void jbstream_stats(JBStreamStats* out);

// The worker's time (step 13b-3), in EE ticks (bGetTicker), summed and
// wrapping: decoding, and reading the card. Read without the lock, which
// the worker holds through its reads, so the game's thread never waits on
// it.
void jbstream_busy(uint32_t* decodeTicks, uint32_t* readTicks);

#endif
