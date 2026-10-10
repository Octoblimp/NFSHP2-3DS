// speechnoise -- SpeechNoise.obj: SpeechNoise (retail 0x002155d8 ..
// 0x00215a5c) and its getInstance (0x001b0188).
//
// The radio around the cop speech: two squelches, one played at random
// as a message starts, and seven bursts of static, one now and then
// while the radio is on. The samples are the in-game region's, looked up
// once the regions are in. The helicopter's noise is retail's too, but
// retail never sets its sample, so it never plays.
//
// Retail has three copies of getInstance, each over its own static; only
// 0x001b0188's (0x003341d0, guarded by gp-19072) is ever called.
//
// docs/formats/speechnoise.md has the rest; tools/speechnoise_check.py
// runs retail's code against this.

#ifndef SPEECHNOISE_H
#define SPEECHNOISE_H

#include <stddef.h>
#include <stdint.h>

#include "bsound.h"

#define SPEECHNOISE_SQUELCHES 2
#define SPEECHNOISE_RADIOS    7

typedef struct SpeechNoise {
    BSample *Helicopter;                        //  0
    BSample *Squelch[SPEECHNOISE_SQUELCHES];    //  4
    BSample *Radio[SPEECHNOISE_RADIOS];         // 12
    int32_t  RadioNoiseOn;                      // 40
    int32_t  RequestSampleLoad;                 // 44
    int32_t  SpeechNoiseMuted;                  // 48
} SpeechNoise;                                  // 52

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char speechnoise_layout_check[
    (offsetof(SpeechNoise, Radio) == 12
     && offsetof(SpeechNoise, RadioNoiseOn) == 40
     && sizeof(SpeechNoise) == 52) ? 1 : -1];
#endif

// 0x001b0188. The one instance, constructed on the first call.
SpeechNoise *speechnoise_get_instance(void);

// 0x002155d8. The flags and the helicopter's sample 0; the squelches and
// the static are left as they are.
void speechnoise_construct(SpeechNoise *n);

// 0x00215610. The in-game region's "RadioNoiseSquelch01" and "02" and
// "RadioNoise01" to "07", each category 6, and the request cleared.
void speechnoise_load_samples(SpeechNoise *n);
// 0x00215770. Asks for LoadSamples once the regions are in.
void speechnoise_request_samples(SpeechNoise *n);
// 0x00215780. Stops the helicopter's noise if there is a sample, and the
// static; the helicopter's sample goes.
void speechnoise_unload_samples(SpeechNoise *n);
// 0x002157c0. The samples once asked for and the regions are in; then,
// with the regions in, not muted and the radio on, a 3% chance of one
// burst of static, at 0.6 to 1.0.
void speechnoise_update(SpeechNoise *n);
// 0x002158a0. Pauses or resumes the static and the helicopter; the
// squelches are left alone.
void speechnoise_mute(SpeechNoise *n, int32_t on);

void    speechnoise_start_helicopter_noise(SpeechNoise *n);  // 0x00215930
void    speechnoise_stop_helicopter_noise(SpeechNoise *n);   // 0x00215958
void    speechnoise_start_radio_noise(SpeechNoise *n);       // 0x002159a0
void    speechnoise_stop_radio_noise(SpeechNoise *n);        // 0x002159b0
int32_t speechnoise_is_radio_noise(const SpeechNoise *n);    // 0x002159b8
// 0x002159c0. One of the two squelches, at random, at full volume.
void    speechnoise_begin_squelch_noise(SpeechNoise *n);
// 0x00215a08. Whether either squelch plays.
int32_t speechnoise_is_squelch_noise_playing(const SpeechNoise *n);

#endif
