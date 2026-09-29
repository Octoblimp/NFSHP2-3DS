#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>

#include "mv3.h"

// Streams the disc's movies, `MOVIES\INTRO\*.AVI`, straight off the card:
// plain RIFF/AVI with an MV30 video stream (mv3.c) and a sound stream, the
// two interleaved in the `movi` list chunk by chunk. The sound's strf says
// 8-bit mono PCM and it is not: it is the SPU's ADPCM, in stereo -- see
// AviSound below. `docs/formats/mv3-video.md` has the container and the
// sound.
//
// Retail's boot movies are 512x256 at 30 fps and every frame is a keyframe,
// so a frame decodes without the ones before it. The player leans on that:
// when the clock has run ahead it reads past the frames it is late for and
// decodes only the one that is due, so the picture keeps time with the
// sound on a slow console instead of drifting behind it.
//
// The menus' movies (MOVIES\*.AVI, 256x384, silent) are mostly inter
// frames, each drawn over the one before, so none can be read past. Those
// are paced as retail paces every movie, MoviePlayer::Update's rule: the
// next frame when it is due, one a call and in order, so a movie that
// falls behind plays slower -- avimovie_step. On the console they are
// decoded on another core, ahead of the picture (AVIMOVIE_SLOTS).
//
// The container and the pacing are free of <3ds.h> and are tested on the
// host (tools/src/mv3_test.c, tools/mv3_check.py). The texture and the ndsp
// channel are the block at the end.

#define AVI_TAG(a, b, c, d) \
    ((uint32_t)(a) | (uint32_t)(b) << 8 | (uint32_t)(c) << 16 | (uint32_t)(d) << 24)

typedef struct {
    uint32_t width, height;          // strf's BITMAPINFOHEADER; height's sign
    int32_t  bmpHeight;              //   kept in bmpHeight
    uint32_t videoCodec;             // biCompression, 'MV30'
    uint32_t scale, rate;            // the video strh: rate / scale a second
    uint32_t frames;                 // the video strh's length
    uint16_t audioFormat;            // WAVEFORMATEX as the file has it, which
    uint16_t audioChannels, audioBits;   //   is not what the stream holds:
    uint32_t audioRate;              //   the player reads none of the four
    int      videoStream, audioStream;   // -1 when absent
    uint32_t moviStart, moviEnd;     // the movi list's payload, as offsets
} AviInfo;

typedef struct {
    uint32_t tag;                    // as the file spells it, '00db' etc.
    uint32_t offset;                 // the payload's file offset
    uint32_t size;
} AviChunk;

// Reads the RIFF header, hdrl and the start of movi. False on anything that
// is not an AVI with one video stream.
bool avi_parse(FILE* f, AviInfo* out);

// The chunk at *pos inside movi, then *pos past it. A `LIST rec ` is walked
// into and JUNK is skipped. False at the end of movi or on a bad chunk.
bool avi_next_chunk(FILE* f, const AviInfo* info, uint32_t* pos, AviChunk* out);

// Which stream a chunk belongs to, from its first two characters, or -1.
int avi_chunk_stream(uint32_t tag);

typedef void (*AviAudioFn)(void* user, FILE* f, const AviChunk* c);

typedef struct {
    FILE*      file;
    AviInfo    info;
    Mv3Codec   codec;
    uint32_t   pos;                  // the next chunk header
    uint32_t   nextFrame;            // the next video chunk's frame number
    int32_t    shown;                // the frame in the planes, -1 before any
    uint32_t   decoded;              // how many frames were decoded
    uint32_t   skipped;              // and how many read past unseen
    bool       ended;                // movi is used up
    int        error;                // mv3_decode's, once a frame fails
    uint8_t*   frameBuf;
    uint32_t   frameCap;
    AviAudioFn audio;                // each audio chunk as it is reached
    void*      audioUser;
    // When set, what reading and decoding the frames cost, in its units.
    uint64_t (*clock)(void);
    uint64_t   readClocks, decodeClocks;
} AviMovie;

// Opens `path` and sizes the codec. Nothing is decoded yet.
bool avimovie_open(AviMovie* m, const char* path);
void avimovie_close(AviMovie* m);

// The frame due at `seconds` into the movie: floor(seconds * rate / scale).
uint32_t avimovie_frame_at(const AviMovie* m, double seconds);
double   avimovie_duration(const AviMovie* m);

// Reads on until frame `target` has been read, handing every audio chunk on
// the way to `audio`, and decodes `target` alone of the frames it passes.
// True when the planes changed. A frame that fails to decode ends the
// movie, with the codec's error in `error`.
bool avimovie_advance(AviMovie* m, uint32_t target);

// MoviePlayer::Update (0x002380a8), as far as the frames go: the next frame
// is decoded when fewer than `target` have been, or when none has yet, and
// never more than one a call. Sound chunks on the way go to `audio`, as in
// avimovie_advance. `changed`, when not NULL, says whether the planes did.
// Returns Update's answer: 0 once the movie is over -- the frame after the
// last came due and movi had no video chunk left -- or a frame failed, and
// 1 until then. Update also answers 0 after 20 s without a frame, which a
// stream off the card never needs, and 1 while its ring buffer waits on
// the disc, which it never does either; neither is here.
int avimovie_step(AviMovie* m, uint32_t target, bool* changed);

// Update's read and decode alone: the next video chunk into the planes,
// frame nextFrame - 1 after it, with sound chunks on the way to `audio`.
// 1, or 0 once movi has no video chunk left (`ended`) or the frame failed
// (`error`). `shown` and `decoded` are left to the caller.
int avimovie_decode_next(AviMovie* m);

// Past the last frame, or stopped by a bad one.
bool avimovie_done(const AviMovie* m);

// -- the sound ---------------------------------------------------------------
//
// Retail's movie sound is PS2 SPU ADPCM -- 16-byte frames of 28 samples, the
// same codec as the sound banks (docs/formats/sound-bank.md) -- in stereo:
// the stream is pairs of blocks, 0x8000 bytes of the left channel and then
// 0x8000 of the right, and each channel's history runs on from its previous
// block. The AVI's chunks cut the stream anywhere, even mid-frame, so bytes
// are held until a whole pair is in and only then decoded.
//
// None of that is in the EE's code -- the IOP fed the SPU -- and it is
// worked out from the data; the rate is the EE's. MoviePlayer::Update
// (0x002380a8) makes the stream's bSample and stores 0xaa66 over its rate
// (0x002381b0), and every rate bSnd hands the SPU goes through
// SOUND_HzToSPU (0x0026d258), so the SPU played the movies at pitch 3722:
// 43617 Hz, for every movie, whatever the strf says.

#define AVISOUND_BLOCK   0x8000              // one channel's run of the stream
#define AVISOUND_PAIR    (2 * AVISOUND_BLOCK)
#define AVISOUND_FRAMES  (AVISOUND_BLOCK / 16)   // SPU frames a block: 2048
#define AVISOUND_SAMPLES 28                  // samples an SPU frame
#define AVISOUND_RATE    0xaa66              // Hz, before the SPU's rounding

typedef struct {
    uint8_t* buf;                // stream bytes in and not yet played out;
    uint32_t len, cap;           //   buf[0] starts a pair
    uint32_t frame;              // the pair's next frame, 0..AVISOUND_FRAMES
    int32_t  hist[2][2];         // each channel's last sample and the one before
    uint32_t pushed;             // bytes in since the start
} AviSound;

// Appends `n` bytes of the stream, or a sound chunk read from `f`. False
// when it could not: out of memory, or a short read.
bool avisound_push(AviSound* s, const void* p, uint32_t n);
bool avisound_read(AviSound* s, FILE* f, const AviChunk* c);

// Frames of each channel that can be decoded now: the rest of every whole
// pair held. A partial pair at the end of a stream never plays.
uint32_t avisound_ready(const AviSound* s);

// Decodes up to `frames` frames of each channel into `out`, left and right
// interleaved (out[2i] left, out[2i+1] right), and returns how many samples
// a channel that made: 28 a frame.
uint32_t avisound_pull(AviSound* s, int16_t* out, uint32_t frames);

void avisound_free(AviSound* s);

// The rate the SPU played at: AVISOUND_RATE through bsnd's round trip.
uint32_t avisound_rate_hz(void);

#ifdef __3DS__
#include <3ds.h>
#include <citro3d.h>

// ndsp's channels 0..22 are bsnd's; the movie's sound is the last one.
#define AVIMOVIE_CHANNEL 23
// The sound goes to ndsp as stereo PCM16, decoded a wave at a time into a
// ring of AVIMOVIE_WAVES buffers that the DSP plays in order: about a
// second queued, so a slow pass of the loop never lets it run dry, in
// 172 KB of linear memory.
#define AVIMOVIE_WAVES       6
#define AVIMOVIE_WAVE_FRAMES 256     // SPU frames a wave: 7168 samples

// A menu movie's frames are read, decoded and converted on another core,
// ahead of the picture, each into a texture slot of its own. Retail's
// Update takes the ring buffer's next frame when one is due, and answers 1
// without one while the ring buffer waits on the disc; the port's takes
// the worker's next slot, and answers 1 while the worker is still on it.
// So the frames stay in order and none is passed over, as before, but a
// slow frame costs the menus no time. Three slots: the one shown, the one
// shown before it, which the GPU may still be drawing from until the next
// call, and the one being filled.
#define AVIMOVIE_SLOTS 3

typedef struct {
    ndspWaveBuf wave;
    int16_t*    pcm;                 // AVIMOVIE_WAVE_FRAMES * 28 * 2 samples
} AviWave;

typedef struct {
    AviMovie movie;
    AviSound snd;
    C3D_Tex  tex;                    // tex.data is the slot shown
    u64      startTick;
    bool     started;                // aviplayer_update has run: the clock is on
    bool     sound;
    AviWave  waves[AVIMOVIE_WAVES];  // a ring, played in order
    uint32_t waveHead, waveCount;
    uint32_t audioSamples;           // queued since the start, a channel
    // What the picture costs, in system ticks: reading and decoding, and
    // converting into the texture, over `calls` drives or updates. With a
    // worker, showTicks is its converting and stepTicks the calls' own.
    u64      stepTicks, showTicks;
    uint32_t calls;

    // The worker, for a movie aviplayer_init opened without sound. Under
    // `lock`: freeSlots, the queue, finished and stop.
    bool       threaded;
    int        workerCore;
    Thread     worker;
    LightLock  lock;
    LightEvent wake;                 // a slot came free, or stop
    void*      slots[AVIMOVIE_SLOTS];     // slots[0] is C3D_TexInit's
    uint32_t   freeSlots;                 // a bit a slot the worker may fill
    uint32_t   freeAt[AVIMOVIE_SLOTS];    // a slot replaced: the call it frees
    int        current;                   // the slot shown, -1 before any
    uint8_t    queueSlot[AVIMOVIE_SLOTS]; // filled slots, in frame order
    uint32_t   queueFrame[AVIMOVIE_SLOTS];
    uint32_t   queueHead, queued;
    bool       finished;             // the worker is done: ended or failed
    bool       stop;
    bool       over;                 // Update has answered 0
    uint32_t   waits;                // calls with a frame due and none ready
} AviPlayer;

// Opens `path` into a fresh RGBA8 texture, shows frame 0 and starts its
// sound; the clock starts here. The texture's sides are the movie's rounded
// up to powers of two, as the GPU needs, with the picture at its top left:
// a 256x384 movie is in a 256x512 texture.
bool aviplayer_open(AviPlayer* p, const char* path);
void aviplayer_close(AviPlayer* p);

// Brings the texture up to the clock, reading past late frames
// (avimovie_advance). True once the movie is over.
bool aviplayer_drive(AviPlayer* p);

// MoviePlayer::InitFile (0x00237ad8): opens `path` as aviplayer_open does
// and leaves the clock off. The first aviplayer_update starts it and shows
// frame 0, as the first Update does. A movie without sound gets its worker
// here, which starts on frame 0 at once.
bool aviplayer_init(AviPlayer* p, const char* path);

// MoviePlayer::Update (0x002380a8): avimovie_step against the clock, or
// the worker's next frame by the same rule, the texture brought up when a
// frame was taken. Update's answer: false once the movie is over, which is
// when FlailerScreenList::UpdateMovie opens it again.
bool aviplayer_update(AviPlayer* p);

// Stops the worker, if there is one, when its frame in hand is done; the
// close does this first. The movie's counts hold still after it.
void aviplayer_halt(AviPlayer* p);
#endif
