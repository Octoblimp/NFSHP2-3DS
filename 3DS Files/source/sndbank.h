#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "bchunk.h"

// .SBK -- the port's sound bank, one per disc SOUND/*.MSH + .MSB pair.
// Format and why it exists: docs/formats/sound-bank.md, "The port's .SBK".
// Built by tools/audio_pack.py; this is the read half, and
// tools/sndbank_check.py diffs it field for field against an independent
// Python reader over all 30 banks, so it is not trusted on inspection alone.
//
// The audio inside is Nintendo DSPADPCM, which is what the 3DS DSP reads. The
// ARM11 never touches a sample: bsnd.c hands the bytes and the coefficients
// below straight to an ndsp channel.
//
// No <3ds.h> here -- the whole file builds on the host.

#define SNDBANK_MAGIC        0x314b4253u   // 'SBK1'
#define SNDBANK_VERSION      1u
#define SNDBANK_HEADER_SIZE  32
#define SNDBANK_PATCH_SIZE   128
#define SNDBANK_FLAG_LOOP    0x01

typedef struct {
    const uint8_t* buf;
    size_t         size;
    const uint8_t* records;    // count * SNDBANK_PATCH_SIZE
    const uint8_t* data;       // the DSPADPCM blob
    uint32_t       dataSize;
    uint32_t       count;
    uint32_t       hash;       // bStringHash of the bank name
    char           name[9];    // "COMMON", "INGAME", "NEWE911", ...
} SndBank;

typedef struct {
    char           name[33];   // "CopSiren01", "MenuSelect", ...
    uint32_t       hash;       // bStringHash(name) -- the lookup key
    uint32_t       samples;    // per channel
    uint32_t       dataOff;    // into the bank's blob
    uint32_t       dataSize;   // both channels together
    uint16_t       rate;       // Hz, the MSH's Pitch
    uint16_t       volume;     // 0..0x7fff, the MSH's Volume
    uint16_t       effectVolume;
    uint8_t        channels;   // 1, or 2 for a joined stereo pair
    bool           looping;    // the whole buffer is the loop body
    int16_t        coefs[2][16];
    const uint8_t* pcm;        // channel-major: all of ch0, then all of ch1
} SndPatch;

bool sndbank_open(SndBank* b, const uint8_t* buf, size_t size);

// Both getters validate the record and return false on a bank that does not
// hold together, rather than handing back a patch that points outside it.
bool sndbank_get(const SndBank* b, uint32_t index, SndPatch* out);
bool sndbank_find(const SndBank* b, uint32_t hash, SndPatch* out);
bool sndbank_find_name(const SndBank* b, const char* name, SndPatch* out);

// One channel's frames. NULL if `channel` is out of range.
const uint8_t* sndbank_channel(const SndPatch* p, int channel, uint32_t* bytes);
