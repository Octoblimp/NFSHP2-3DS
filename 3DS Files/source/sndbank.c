#include "sndbank.h"

#include <string.h>

// Everything here reads from a buffer the caller owns and bounds-checks every
// field against the buffer's real length first, because a .SBK comes off the
// SD card and a corrupt one must fail rather than walk off the end. The
// checker feeds it 20,000 mutated banks; see tools/sndbank_check.py.

static uint32_t rd32(const uint8_t* p) { return bchunk_u32(p); }
static uint16_t rd16(const uint8_t* p) { return bchunk_u16(p); }

bool sndbank_open(SndBank* b, const uint8_t* buf, size_t size)
{
    memset(b, 0, sizeof(*b));
    if (!buf || size < SNDBANK_HEADER_SIZE) return false;
    if (rd32(buf) != SNDBANK_MAGIC) return false;
    if (rd32(buf + 4) != SNDBANK_VERSION) return false;

    uint32_t count    = rd32(buf + 8);
    uint32_t dataOff  = rd32(buf + 12);
    uint32_t dataSize = rd32(buf + 16);

    // The record table has to fit between the header and the blob, and the
    // blob has to fit in the file. Both products are computed in 64 bits so a
    // count of 0x04000000 cannot wrap the multiply back into range.
    uint64_t need = (uint64_t)SNDBANK_HEADER_SIZE
                  + (uint64_t)count * SNDBANK_PATCH_SIZE;
    if (need > dataOff) return false;
    if ((uint64_t)dataOff + dataSize > size) return false;

    b->buf      = buf;
    b->size     = size;
    b->count    = count;
    b->records  = buf + SNDBANK_HEADER_SIZE;
    b->data     = buf + dataOff;
    b->dataSize = dataSize;
    b->hash     = rd32(buf + 20);
    memcpy(b->name, buf + 24, 8);
    b->name[8] = 0;
    return true;
}

bool sndbank_get(const SndBank* b, uint32_t index, SndPatch* out)
{
    memset(out, 0, sizeof(*out));
    if (index >= b->count) return false;
    const uint8_t* r = b->records + (size_t)index * SNDBANK_PATCH_SIZE;

    memcpy(out->name, r, 32);
    out->name[32]      = 0;
    out->hash          = rd32(r + 0x20);
    out->samples       = rd32(r + 0x24);
    out->dataOff       = rd32(r + 0x28);
    out->dataSize      = rd32(r + 0x2c);
    out->rate          = rd16(r + 0x30);
    out->volume        = rd16(r + 0x32);
    out->effectVolume  = rd16(r + 0x34);
    out->channels      = r[0x36];
    out->looping       = (r[0x37] & SNDBANK_FLAG_LOOP) != 0;

    if (out->channels != 1 && out->channels != 2) return false;
    if ((uint64_t)out->dataOff + out->dataSize > b->dataSize) return false;
    if (out->dataSize % out->channels) return false;

    // 14 samples to an 8-byte DSPADPCM frame. A record whose sample count does
    // not match its byte count is the one corruption the DSP would not notice:
    // it would read the neighbouring patch and play it as noise.
    uint32_t per = out->dataSize / out->channels;
    if (per / 8 != (out->samples + 13) / 14) return false;

    for (int c = 0; c < out->channels; c++)
        for (int i = 0; i < 16; i++)
            out->coefs[c][i] = (int16_t)rd16(r + 0x38 + c * 32 + i * 2);

    out->pcm = b->data + out->dataOff;
    return true;
}

bool sndbank_find(const SndBank* b, uint32_t hash, SndPatch* out)
{
    for (uint32_t i = 0; i < b->count; i++) {
        const uint8_t* r = b->records + (size_t)i * SNDBANK_PATCH_SIZE;
        if (rd32(r + 0x20) == hash) return sndbank_get(b, i, out);
    }
    return false;
}

bool sndbank_find_name(const SndBank* b, const char* name, SndPatch* out)
{
    return sndbank_find(b, bchunk_hash(name), out);
}

const uint8_t* sndbank_channel(const SndPatch* p, int channel, uint32_t* bytes)
{
    if (channel < 0 || channel >= p->channels) return NULL;
    uint32_t per = p->dataSize / p->channels;
    if (bytes) *bytes = per;
    return p->pcm + (size_t)channel * per;
}
