#include "bsnd.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

// The port of bDriverPS2.o. Every function below names the address it came
// from; docs/formats/sound-driver.md is the writeup and tools/bsnd_check.py is
// the differ. Nothing here includes <3ds.h> -- the ndsp half is at the bottom,
// behind __3DS__, and is the only code in this file no checker can reach.

// -- units -------------------------------------------------------------------

// The EE's `sra` of a signed product, which truncates toward zero only because
// GetPanFromAzimuth adds (1 << 14) - 1 to a negative numerator first.
static int32_t trunc14(int32_t x)
{
    return (x < 0 ? x + 16383 : x) >> 14;
}

uint32_t bsnd_hz_to_spu(uint32_t hz)
{
    // SOUND_HzToSPU, 0x002528b8: (hz << 12) / 48000, unsigned, truncating.
    return (uint32_t)(((uint64_t)hz << 12) / 48000u);
}

uint32_t bsnd_spu_to_hz(uint32_t spu)
{
    // The other way, which the SPU did in hardware and ndsp needs spelled
    // out. 22050 Hz becomes 1881 and comes back 22042: eight hertz flat, a
    // little over half a cent, and audible only next to the original. What is
    // not acceptable is skipping the round trip, because then the port and
    // the disc would be a different distance apart on every patch.
    return (uint32_t)(((uint64_t)spu * 48000u) >> 12);
}

int8_t bsnd_pan_from_azimuth(uint16_t azimuth)
{
    // GetPanFromAzimuth, 0x0024f688. Four quadrants, each a truncating scale
    // of the distance from the nearest of ahead/behind onto +-127. Note that
    // behind (0x8000) comes out centred, not reversed: this is a pan, and a
    // stereo pair cannot say "behind".
    int32_t az = azimuth;
    if (azimuth <= 0x4000) return (int8_t)trunc14(az * 127);
    if (azimuth > 0xbfff)  return (int8_t)trunc14((0x10000 - az) * -127);
    if ((int16_t)azimuth < 0) return (int8_t)trunc14((az - 0x8000) * -127);
    return (int8_t)trunc14((0x8000 - az) * 127);
}

uint16_t bsnd_azimuth_from_pan(int8_t pan)
{
    // GetAzimuthFromPan, 0x0024f7e0. The constant is the float32 of 16384/127
    // (0x003222f4, and its negation next to it), and both multiplies are
    // mul.s: computed in double instead, pan 127 comes out 16383.99993 and
    // truncates to 16383 rather than rounding up inside the float to 16384.
    // cvt.w.s truncates because the EE runtime leaves FCR31 in chop mode,
    // which is what makes a C cast mean what C says it means.
    const float k = 129.00787353515625f;
    float f = (pan >= 0) ? (float)pan * k : 65536.0f - (float)pan * -k;
    return (uint16_t)(int32_t)f;
}

void bsnd_volumes_from_pan(const BsndDriver* d, uint16_t* left, uint16_t* right,
                           uint16_t volume, int8_t pan)
{
    // GetVolumesFromPan, 0x0024d928. One table, read from both ends, and a
    // 32-bit product shifted down by the table's 14 fractional bits. Mono and
    // "not initialised yet" both collapse the pan (0x0024d94c).
    int32_t idx;
    if (d->mode < BSND_MODE_STEREO) pan = 0;

    // The original does not clamp, so pan -128 reads bsnd_pan_table[-1]: two
    // bytes of whatever the linker put below 0x00317d00. It never happens,
    // because GetPanFromAzimuth cannot return -128 and bSnd_VoicePlay turns a
    // -128 argument into the patch's own pan before it gets here -- but a
    // caller that got it wrong would read out of bounds rather than be told.
    // The port clamps. docs/formats/sound-driver.md records the divergence.
    if (pan < -127) pan = -127;

    idx = pan + 127;
    *left  = (uint16_t)(((int32_t)volume * bsnd_pan_table[idx]) >> 14);
    *right = (uint16_t)(((int32_t)volume * bsnd_pan_table[254 - idx]) >> 14);
}

int bsnd_find_free_channels(const BsndDriver* d, unsigned first, unsigned last,
                            unsigned count)
{
    // SOUND_FindFreeSPUChannels, 0x002520c0. A run of adjacent channels, not
    // any `count` of them: a stereo patch is two SPU voices and the low driver
    // addressed them as `voice` and `voice + 1`. Scanning backwards when
    // last < first is in the original and the engine never asks for it.
    int step, i, run = 0;

    if (first >= d->voices) return -2;
    if (last >= d->voices) return -3;
    step = (last < first) ? -1 : 1;

    for (i = (int)first; i != (int)last + step; i += step) {
        // Free means key status 0 and nothing else. The original also accepts
        // status 1 when its `allowLocked` argument is set, but bSnd_VoicePlay
        // passes false (0x00248dc8) and no code on this disc ever writes a 1.
        if (d->lock[i] == 0 && d->key[i] == BSND_KEY_OFF) {
            if ((unsigned)++run == count)
                return (step > 0) ? i + 1 - (int)count : i;
        } else {
            run = 0;
        }
    }
    return -1;
}

// -- driver ------------------------------------------------------------------

static void* host_alloc(size_t n) { return malloc(n); }
static void  host_free(void* p)   { free(p); }

void bsnd_init(BsndDriver* d, const BsndSink* sink, unsigned voices)
{
    unsigned i;
    memset(d, 0, sizeof(*d));
    d->sink = sink;
    d->alloc = host_alloc;
    d->release = host_free;
    d->voices = (voices && voices <= BSND_PS2_VOICES) ? voices : BSND_MAX_VOICES;
    // bSnd_Initialize ends with bSnd_SetStereo (0x00246028).
    d->mode = BSND_MODE_STEREO;
    for (i = 0; i < BSND_PS2_VOICES; i++) {
        d->voice[i].streamChannel = -1;
        d->voice[i].patch = BSND_PATCH_NONE;
    }
}

void bsnd_close(BsndDriver* d)
{
    unsigned i;
    for (i = 0; i < d->voices; i++) bsnd_voice_stop(d, (uint16_t)i);
    for (i = 0; i < BSND_MAX_BANKS; i++)
        if (d->bankSlot[i].used) {
            if (d->bankSlot[i].image) d->release(d->bankSlot[i].image);
            memset(&d->bankSlot[i], 0, sizeof(d->bankSlot[i]));
        }
    d->patchCount = 0;
}

void bsnd_set_mode(BsndDriver* d, uint8_t mode) { d->mode = mode; }

void bsnd_set_load_path(BsndDriver* d, const char* path)
{
    // bSnd_SetLoadPath, 0x00246c70.
    size_t n = path ? strlen(path) : 0;
    if (n >= sizeof(d->path)) n = sizeof(d->path) - 1;
    if (n) memcpy(d->path, path, n);
    d->path[n] = 0;
}

// -- banks -------------------------------------------------------------------

static int slot_of(const BsndDriver* d, const char* name)
{
    // FindBank, 0x0024e820, by hash rather than by strcmp.
    uint32_t h = bchunk_hash(name);
    int i;
    for (i = 0; i < BSND_MAX_BANKS; i++)
        if (d->bankSlot[i].used && d->bankSlot[i].hash == h) return i;
    return -1;
}

bool bsnd_bank_loaded(const BsndDriver* d, const char* name)
{
    return slot_of(d, name) >= 0;   // bSnd_GetIsBankLoaded, 0x002477c0
}

bool bsnd_bank_register(BsndDriver* d, const char* name, uint8_t* image,
                        size_t size, bool owned)
{
    int i;
    BsndBankSlot* s;

    if (!name || !image) return false;
    if (slot_of(d, name) >= 0) return true;      // already loaded, as bSnd does

    for (i = 0; i < BSND_MAX_BANKS; i++)
        if (!d->bankSlot[i].used) break;
    if (i == BSND_MAX_BANKS) return false;

    s = &d->bankSlot[i];
    if (!sndbank_open(&s->bank, image, size)) return false;

    s->image = owned ? image : NULL;
    s->hash = bchunk_hash(name);
    // SOUND_BANK_INFO::StartPatch/EndPatch: patch ids run flat across every
    // loaded bank, so an id survives a lookup in one bank being used against
    // the table in another. Unloading does not compact them -- see
    // bsnd_bank_unload.
    s->first = d->patchCount;
    s->count = (uint16_t)s->bank.count;
    s->used = true;
    d->patchCount = (uint16_t)(d->patchCount + s->count);
    return true;
}

bool bsnd_bank_load(BsndDriver* d, const char* name)
{
    // bSnd_BankLoad, 0x00246d68. The disc read an .MSH into main RAM and DMA'd
    // the .MSB into SPU RAM; here one .SBK holds both halves and the DSP reads
    // it in place, so the whole load is an fread into a buffer the DSP can see.
    char file[sizeof(d->path) + 32];
    FILE* f;
    long size;
    uint8_t* buf;

    if (!name) return false;
    if (slot_of(d, name) >= 0) return true;
    if (snprintf(file, sizeof(file), "%s/%s.SBK", d->path, name) < 0)
        return false;

    f = fopen(file, "rb");
    if (!f) return false;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return false; }
    size = ftell(f);
    if (size <= 0 || fseek(f, 0, SEEK_SET) != 0) { fclose(f); return false; }

    buf = (uint8_t*)d->alloc((size_t)size);
    if (!buf) { fclose(f); return false; }
    if (fread(buf, 1, (size_t)size, f) != (size_t)size) {
        fclose(f);
        d->release(buf);
        return false;
    }
    fclose(f);

    if (!bsnd_bank_register(d, name, buf, (size_t)size, true)) {
        d->release(buf);
        return false;
    }
    return true;
}

bool bsnd_bank_unload(BsndDriver* d, const char* name)
{
    // bSnd_BankUnload, 0x00247410, which also stops every voice the bank owns
    // -- ClearBank at 0x0024e428 walks the voice table doing exactly this,
    // because the samples are about to stop existing.
    int i = slot_of(d, name);
    unsigned v;
    BsndBankSlot* s;

    if (i < 0) return false;
    s = &d->bankSlot[i];

    for (v = 0; v < d->voices; v++) {
        uint16_t p = d->voice[v].patch;
        if (p != BSND_PATCH_NONE && p >= s->first && p < s->first + s->count)
            bsnd_voice_stop(d, (uint16_t)v);
    }

    if (s->image) d->release(s->image);
    memset(s, 0, sizeof(*s));

    // Ids are not compacted and patchCount is not lowered: a reload would then
    // reuse ids that a caller might still be holding. The gap simply stays,
    // which is what StartPatch/EndPatch let the original do too.
    return true;
}

// -- patches -----------------------------------------------------------------

static const BsndBankSlot* slot_for_patch(const BsndDriver* d, uint16_t id)
{
    int i;
    for (i = 0; i < BSND_MAX_BANKS; i++) {
        const BsndBankSlot* s = &d->bankSlot[i];
        if (s->used && id >= s->first && id < (uint16_t)(s->first + s->count))
            return s;
    }
    return NULL;
}

uint16_t bsnd_patch_id(const BsndDriver* d, const char* bank, const char* patch)
{
    // bSnd_GetPatchID, 0x0024d730: the bank by name, then the patch by name
    // inside it. 0xfffa for either miss, which is the value bSnd_VoicePlay
    // tests for before it turns it into its own 0xfffe.
    int i = bank ? slot_of(d, bank) : -1;
    uint32_t h;
    uint32_t k;
    const BsndBankSlot* s;

    if (i < 0 || !patch) return BSND_PATCH_NONE;
    s = &d->bankSlot[i];
    h = bchunk_hash(patch);
    for (k = 0; k < s->bank.count; k++) {
        SndPatch p;
        if (sndbank_get(&s->bank, k, &p) && p.hash == h)
            return (uint16_t)(s->first + k);
    }
    return BSND_PATCH_NONE;
}

bool bsnd_patch_get(const BsndDriver* d, uint16_t id, SndPatch* out)
{
    const BsndBankSlot* s = slot_for_patch(d, id);
    if (!s) return false;
    return sndbank_get(&s->bank, (uint32_t)(id - s->first), out);
}

unsigned bsnd_patch_channels(const BsndDriver* d, uint16_t id)
{
    // bSnd_GetPatchChannels, 0x0024baf8 -- GetChannelNum(LoopChannel) + 1 on
    // the disc, and the .SBK's own `channels` here, because audio_pack.py
    // joined the pair at build time. sndbank_check.py is what ties the two
    // together.
    SndPatch p;
    return bsnd_patch_get(d, id, &p) ? p.channels : 0;
}

// -- voices ------------------------------------------------------------------

static void voice_start(BsndDriver* d, unsigned ch, const SndPatch* p,
                        unsigned chanIdx, uint32_t rate)
{
    const uint8_t* data;
    uint32_t bytes = 0;

    data = sndbank_channel(p, (int)chanIdx, &bytes);
    if (!data) return;
    d->key[ch] = BSND_KEY_ON;
    if (d->sink && d->sink->start)
        d->sink->start(d->sink->user, ch, data, bytes, p->samples,
                       p->coefs[chanIdx], rate, p->looping);
}

uint16_t bsnd_voice_play_pan(BsndDriver* d, const char* bank, const char* patch,
                             uint32_t rate, uint16_t volume, int8_t pan,
                             uint16_t voice)
{
    // 0x00247a28: a pan is turned into an azimuth and forgotten about. -128
    // stays -128, because GetAzimuthFromPan of it is 0x8000 -- behind -- and
    // 0x8000 comes back out of GetPanFromAzimuth as centre, which is the
    // patch's own pan on every record here anyway.
    return bsnd_voice_play(d, bank, patch, rate, volume,
                           bsnd_azimuth_from_pan(pan), voice);
}

uint16_t bsnd_voice_play(BsndDriver* d, const char* bank, const char* patch,
                         uint32_t rate, uint16_t volume, uint16_t azimuth,
                         uint16_t voice)
{
    // bSnd_VoicePlay, 0x00247f00, non-streaming path. The streaming path above
    // it (bank name "STREAMS") drove the IOP's CD reader and has no port.
    uint16_t id;
    SndPatch p;
    unsigned channels, n;
    uint32_t adsr;
    int8_t pan;

    // 0x00247fac, before anything else is looked at: where the sound is comes
    // in as an azimuth and becomes a pan straight away. -128 is not reachable
    // from any azimuth, which is what makes it usable as the "patch's own"
    // sentinel further down (0x00248f20).
    pan = bsnd_pan_from_azimuth(azimuth);

    id = bsnd_patch_id(d, bank, patch);
    if (id == BSND_PATCH_NONE) return BSND_NO_PATCH;   // 0x00248d2c
    if (!bsnd_patch_get(d, id, &p)) return BSND_NO_PATCH;
    channels = p.channels;

    if (voice == BSND_VOICE_ALLOC) {
        int got = bsnd_find_free_channels(d, 0, d->voices - 1, channels);
        if (got < 0) return BSND_NO_PATCH;             // 0x00248dec
        voice = (uint16_t)got;
    }
    // The original only bounds-checks this for stereo (0x00248e08), so a mono
    // patch played on voice 200 wrote 80 bytes past the voice table. The port
    // checks both. docs/formats/sound-driver.md records the divergence.
    if ((unsigned)voice + channels > d->voices) return BSND_BAD_VOICE;

    if (rate == BSND_RATE_PATCH) rate = p.rate;        // 0x00248e68
    if (volume == BSND_VOLUME_PATCH) volume = p.volume;
    // The rate the DSP is actually given is the one that survives the SPU
    // pitch register, so the port is out of tune by exactly as much as the
    // PS2 was and not by a different amount.
    rate = bsnd_spu_to_hz(bsnd_hz_to_spu(rate));

    // 0x00248fe8 reads the patch's own ADSR and falls back to this when it is
    // zero (0x00248ffc) -- and it is zero in all 469 records on the disc, so
    // this is what every one of them plays with. Attack 26, release 10, by
    // GetAttack/GetRelease at 0x0024d688/0x0024d6e0. audio_pack.py refuses to
    // build a bank whose records say otherwise, which is why .SBK does not
    // carry the field.
    adsr = 0x1a00000au;

    for (n = 0; n < channels; n++) {
        BsndVoice* v = &d->voice[voice + n];
        int8_t chanPan;
        uint16_t l, r;

        // A stereo patch is hard-panned, one voice a side (0x00248ef4); a mono
        // one takes the caller's pan, or the patch's when the caller passed
        // the -128 sentinel (0x00248f30).
        if (channels == 2) chanPan = (n == 0) ? -127 : 127;
        else chanPan = (pan == BSND_PAN_PATCH) ? BSND_PATCH_PAN : pan;

        bsnd_volumes_from_pan(d, &l, &r, volume, chanPan);
        // 0x00248f7c hands those two volumes to GetVolumesFromAzimuth when the
        // azimuth is non-zero -- but that function returns at its first
        // instruction unless the driver is in Prologic (0x0024f8d0), so in
        // stereo an azimuth reaches the mix only through the pan above. What
        // it does change is Type, which becomes 4 instead of the loop flag.

        v->pan = chanPan;
        // LoopChannel as the original rebuilds it: the loop bit, plus the
        // channel count in the high nibble (0x00249200). Everything that asks
        // a voice how wide it is reads this back through GetChannelNum.
        v->loopChannel = (uint8_t)((p.looping ? 1u : 0u)
                                   | ((unsigned)(channels - 1) << 4));
        v->streamChannel = -1;
        v->paused = 0;
        v->pitch = rate;
        v->volume = volume;
        v->effectVolume = p.effectVolume;
        v->azimuth = azimuth;
        v->type = azimuth ? 4u : (uint16_t)((p.looping ? 1u : 0u) + 1u);
        v->adsr = adsr;
        v->volL = l;
        v->volR = r;
        v->patch = id;

        voice_start(d, voice + n, &p, n, rate);
        if (d->sink && d->sink->mix) d->sink->mix(d->sink->user, voice + n, l, r);
    }
    return voice;
}

// How many channels a voice occupies, from its own LoopChannel -- the loop
// bound every setter below shares (GetChannelNum, 0x0024e660, plus one).
static unsigned voice_width(const BsndDriver* d, uint16_t voice)
{
    unsigned w;
    if (voice >= d->voices) return 0;
    w = (unsigned)(d->voice[voice].loopChannel >> 4) + 1u;
    if ((unsigned)voice + w > d->voices) w = d->voices - voice;
    return w;
}

void bsnd_voice_stop(BsndDriver* d, uint16_t voice)
{
    // bSnd_VoiceStop, 0x00249e10, plus ClearVoice at 0x0024e4c8.
    unsigned w = voice_width(d, voice), n;
    for (n = 0; n < w; n++) {
        unsigned ch = voice + n;
        if (d->sink && d->sink->stop) d->sink->stop(d->sink->user, ch);
        d->key[ch] = BSND_KEY_OFF;
        memset(&d->voice[ch], 0, sizeof(d->voice[ch]));
        d->voice[ch].streamChannel = -1;
        d->voice[ch].patch = BSND_PATCH_NONE;
    }
}

void bsnd_voice_pause(BsndDriver* d, uint16_t voice)
{
    unsigned w = voice_width(d, voice), n;          // bSnd_VoicePause, 0x00249c18
    for (n = 0; n < w; n++) {
        d->voice[voice + n].paused = 1;
        if (d->sink && d->sink->pause)
            d->sink->pause(d->sink->user, voice + n, true);
    }
}

void bsnd_voice_resume(BsndDriver* d, uint16_t voice)
{
    unsigned w = voice_width(d, voice), n;          // bSnd_VoiceResume, 0x00249d08
    for (n = 0; n < w; n++) {
        d->voice[voice + n].paused = 0;
        if (d->sink && d->sink->pause)
            d->sink->pause(d->sink->user, voice + n, false);
    }
}

bool bsnd_voice_paused(const BsndDriver* d, uint16_t voice)
{
    // bSnd_GetIsVoicePaused, 0x0024a210.
    return voice < d->voices && d->voice[voice].paused != 0;
}

bool bsnd_channel_busy(const BsndDriver* d, uint16_t voice)
{
    // bSnd_GetIsChannelBusy, 0x0024a0e8: the key status, not the voice table,
    // because a one-shot goes quiet without anyone telling the voice.
    return voice < d->voices && d->key[voice] != BSND_KEY_OFF;
}

void bsnd_set_voice_volume(BsndDriver* d, uint16_t voice, uint16_t volume)
{
    // bSnd_SetVoiceVolume, 0x0024a8d0. Prologic has its own path in the
    // original and does not pan; here it simply leaves the mix alone.
    unsigned w = voice_width(d, voice), n;
    if (d->mode == BSND_MODE_PROLOGIC) return;
    for (n = 0; n < w; n++) {
        BsndVoice* v = &d->voice[voice + n];
        uint16_t l, r;
        // The original skips a voice whose StreamChannel is not -1 (0x0024a94c):
        // a stream's volume is the IOP's business.
        if (v->streamChannel != -1) continue;
        bsnd_volumes_from_pan(d, &l, &r, volume, v->pan);
        v->volume = volume;
        v->volL = l;
        v->volR = r;
        if (d->sink && d->sink->mix) d->sink->mix(d->sink->user, voice + n, l, r);
    }
}

void bsnd_set_voice_pan(BsndDriver* d, uint16_t voice, int8_t pan)
{
    // bSnd_SetVoicePan, 0x0024a530.
    unsigned w = voice_width(d, voice), n;
    for (n = 0; n < w; n++) {
        BsndVoice* v = &d->voice[voice + n];
        uint16_t l, r;
        if (v->streamChannel != -1) continue;
        bsnd_volumes_from_pan(d, &l, &r, v->volume, pan);
        v->pan = pan;
        v->volL = l;
        v->volR = r;
        if (d->sink && d->sink->mix) d->sink->mix(d->sink->user, voice + n, l, r);
    }
}

void bsnd_set_voice_volume_pan(BsndDriver* d, uint16_t voice, uint16_t volume,
                               int8_t pan)
{
    // bSnd_SetVoiceVolumePan, 0x0024ab40 -- one lookup instead of two, which
    // matters because setting them separately passes through an intermediate
    // mix the original never sends.
    unsigned w = voice_width(d, voice), n;
    for (n = 0; n < w; n++) {
        BsndVoice* v = &d->voice[voice + n];
        uint16_t l, r;
        if (v->streamChannel != -1) continue;
        bsnd_volumes_from_pan(d, &l, &r, volume, pan);
        v->volume = volume;
        v->pan = pan;
        v->volL = l;
        v->volR = r;
        if (d->sink && d->sink->mix) d->sink->mix(d->sink->user, voice + n, l, r);
    }
}

void bsnd_set_voice_pitch(BsndDriver* d, uint16_t voice, uint32_t hz)
{
    // bSnd_SetVoicePitch, 0x0024a410. The original converts once outside the
    // loop and stores the Hz, not the register value, so a later read gives
    // back what the caller asked for; the port stores what it will actually
    // play, because the round trip is the thing the checker is watching.
    unsigned w = voice_width(d, voice), n;
    uint32_t played = bsnd_spu_to_hz(bsnd_hz_to_spu(hz));
    for (n = 0; n < w; n++) {
        d->voice[voice + n].pitch = played;
        if (d->sink && d->sink->rate)
            d->sink->rate(d->sink->user, voice + n, played);
    }
}

uint16_t bsnd_get_voice_volume(const BsndDriver* d, uint16_t voice)
{
    return voice < d->voices ? d->voice[voice].volume : 0;   // 0x0024afd8
}

int8_t bsnd_get_voice_pan(const BsndDriver* d, uint16_t voice)
{
    return voice < d->voices ? d->voice[voice].pan : 0;      // 0x0024b100
}

uint32_t bsnd_get_voice_pitch(const BsndDriver* d, uint16_t voice)
{
    return voice < d->voices ? d->voice[voice].pitch : 0;    // 0x0024af78
}

void bsnd_lock_channels(BsndDriver* d, uint16_t first, uint16_t count)
{
    unsigned n;                                    // bSnd_LockChannels, 0x0024a278
    for (n = 0; n < count && first + n < d->voices; n++) d->lock[first + n] = 1;
}

void bsnd_unlock_channels(BsndDriver* d, uint16_t first, uint16_t count)
{
    unsigned n;                                  // bSnd_UnlockChannels, 0x0024a378
    for (n = 0; n < count && first + n < d->voices; n++) d->lock[first + n] = 0;
}

void bsnd_update(BsndDriver* d)
{
    // bSound::updateCompletedVoices, 0x0025bcf8. The SPU raised a bit in
    // SOUND_SPUKeyStatus when a voice ran out; ndsp has to be asked. Without
    // this the allocator would hand out 24 channels and then never another.
    unsigned i;
    if (!d->sink || !d->sink->playing) return;
    for (i = 0; i < d->voices; i++) {
        if (d->key[i] == BSND_KEY_OFF) continue;
        if (d->voice[i].paused) continue;
        if (d->sink->playing(d->sink->user, i)) continue;
        if (d->sink->stop) d->sink->stop(d->sink->user, i);
        d->key[i] = BSND_KEY_OFF;
        memset(&d->voice[i], 0, sizeof(d->voice[i]));
        d->voice[i].streamChannel = -1;
        d->voice[i].patch = BSND_PATCH_NONE;
    }
}

// -- the 3DS half ------------------------------------------------------------

#ifdef __3DS__
#include <3ds.h>

#include "gamedata.h"

// One ndsp channel per voice, and one waveBuf per channel because every patch
// is a single buffer: a one-shot plays it once, and a looping patch loops the
// whole thing, which is what audio_pack.py dropped the SPU lead-in to make
// possible (docs/formats/sound-bank.md).
static ndspWaveBuf gWave[BSND_MAX_VOICES];
static ndspAdpcmData gAdpcm[BSND_MAX_VOICES];
static bool gNdspReady;

static void hw_start(void* user, unsigned ch, const uint8_t* data,
                     uint32_t bytes, uint32_t samples, const int16_t* coefs,
                     uint32_t rate, bool looping)
{
    ndspWaveBuf* w = &gWave[ch];
    (void)user;
    if (ch >= BSND_MAX_VOICES) return;

    ndspChnReset(ch);
    ndspChnSetInterp(ch, NDSP_INTERP_LINEAR);
    ndspChnSetRate(ch, (float)rate);
    ndspChnSetFormat(ch, NDSP_FORMAT_ADPCM);
    ndspChnSetAdpcmCoefs(ch, (u16*)coefs);

    // Every patch starts on a frame boundary with no history, because the
    // encoder was handed the whole patch as one block.
    memset(&gAdpcm[ch], 0, sizeof(gAdpcm[ch]));
    memset(w, 0, sizeof(*w));
    w->data_vaddr = data;
    w->nsamples = samples;
    w->adpcm_data = &gAdpcm[ch];
    w->looping = looping;
    DSP_FlushDataCache(data, bytes);
    ndspChnWaveBufAdd(ch, w);
}

static void hw_stop(void* user, unsigned ch)
{
    (void)user;
    if (ch < BSND_MAX_VOICES) {
        ndspChnWaveBufClear(ch);
        gWave[ch].status = NDSP_WBUF_DONE;
    }
}

static void hw_mix(void* user, unsigned ch, uint16_t left, uint16_t right)
{
    float mix[12];
    (void)user;
    if (ch >= BSND_MAX_VOICES) return;
    memset(mix, 0, sizeof(mix));
    // The table's full scale is 16383, and volume comes in at up to 0x7fff,
    // so a patch recorded near full can land above 1.0. Clamping here rather
    // than scaling keeps quiet sounds at the relative level the disc set.
    mix[0] = left / 16383.0f;
    mix[1] = right / 16383.0f;
    if (mix[0] > 1.0f) mix[0] = 1.0f;
    if (mix[1] > 1.0f) mix[1] = 1.0f;
    ndspChnSetMix(ch, mix);
}

static void hw_rate(void* user, unsigned ch, uint32_t hz)
{
    (void)user;
    if (ch < BSND_MAX_VOICES) ndspChnSetRate(ch, (float)hz);
}

static void hw_pause(void* user, unsigned ch, bool paused)
{
    (void)user;
    if (ch < BSND_MAX_VOICES) ndspChnSetPaused(ch, paused);
}

static bool hw_playing(void* user, unsigned ch)
{
    (void)user;
    return ch < BSND_MAX_VOICES && ndspChnIsPlaying(ch);
}

static const BsndSink kNdspSink = {
    hw_start, hw_stop, hw_mix, hw_rate, hw_pause, hw_playing, NULL
};

static void* hw_alloc(size_t n) { return linearAlloc(n); }
static void  hw_free(void* p)   { linearFree(p); }

bool bsnd_hw_init(BsndDriver* d)
{
    char path[GAMEDATA_MAX_PATH];

    bsnd_init(d, &kNdspSink, BSND_HW_VOICES);
    d->alloc = hw_alloc;
    d->release = hw_free;

    if (R_FAILED(ndspInit())) {
        d->sink = NULL;          // silent, but every call above still works
        return false;
    }
    gNdspReady = true;
    ndspSetOutputMode(NDSP_OUTPUT_STEREO);

    if (gamedata_path("SOUND", path, sizeof(path)))
        bsnd_set_load_path(d, path);
    return true;
}

void bsnd_hw_close(BsndDriver* d)
{
    bsnd_close(d);
    if (gNdspReady) {
        ndspExit();
        gNdspReady = false;
    }
}
#endif
