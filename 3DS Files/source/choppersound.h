// choppersound -- ChopperSound.obj: ChopperSound and
// sound::CreateChopperSound (retail 0x00214d68 .. 0x002150d8).
//
// The police helicopter's rotor. A Sound3d over the in-game region's
// "ChopperEngine", placed at the chopper's CurrentPos with an envelope of
// 5 out to 200, its volume, Doppler pitch and azimuth from Sound3d. Under
// a reverb area -- in a tunnel, SoundScapeIsInsideTunnel -- it fades out
// over a second and back in once the camera's car is clear.
//
// The bSample is the region's own, shared and not deleted. Its table is
// chopper.h's CHOPPERSOUND_VTABLE, slot for slot, with Sound3d's Activate
// and UpdateCamRelativeDistAndVelocity.
//
// docs/formats/choppersound.md has the rest; tools/soundscape_check.py
// runs retail's code against this, with soundscape.c.

#ifndef CHOPPERSOUND_H
#define CHOPPERSOUND_H

#include <stddef.h>
#include <stdint.h>

#include "bsound.h"
#include "sound3d.h"

struct Chopper;

typedef struct ChopperSound {
    Sound3d         Sound;              //  0
    struct Chopper *pChopper;           // 32
    BSample        *pChopperSample;     // 36
    int32_t         InSideTunnel;       // 40
    float           TunnelFadeCounter;  // 44
} ChopperSound;                         // 48

#if UINTPTR_MAX == 0xFFFFFFFFu
typedef char choppersound_layout_check[
    (offsetof(ChopperSound, pChopper) == 32
     && offsetof(ChopperSound, InSideTunnel) == 40
     && sizeof(ChopperSound) == 48) ? 1 : -1];
#endif

#define CHOPPERSOUND_VT_ENTRIES 8

// ChopperSoundEnvelope (0x0031be30), from the static constructor
// (0x00215598): 5 at the source, cut off at 200, Coeff .005.
extern Sound3dEnvelope ChopperSoundEnvelope;

// Registers the table. Once at boot.
void choppersound_install_vtables(void);

// 0x00214d68. Sound3d's constructor and the table; with sound on, the
// sample, category 0, stopped if it plays. Out of the tunnel. With sound
// off retail leaves the sample unwritten; the port's is NULL, and a
// missing sample is not asked whether it plays.
void choppersound_construct(ChopperSound *s, struct Chopper *h);
// 0x00214df0, slot 8: the table back, then Sound3d's.
void choppersound_destroy(ChopperSound *s, int32_t flags);

// 0x00214e08. Into a tunnel the counter starts at 1 and runs down by the
// frame's time, the volume scaled by it. Out of one, the counter flips to
// 1 - counter, and the volume is scaled by 1 - counter as it runs down.
void choppersound_adjust_for_tunnel_volume(ChopperSound *s, float *volume);

// 0x00214f30, slot 24. With sound on, activated and a sample: Sound3d's
// Update at the chopper, the tunnel's fade, and the sample set -- or
// played, its pan the azimuth as a float, as retail has it.
void choppersound_update(ChopperSound *s, float volume, uint16_t azimuth,
                         float pitch);
void choppersound_mute(ChopperSound *s, int32_t on);       // 0x00215000, 32
void choppersound_deactivate_sound(ChopperSound *s);       // 0x00215028, 40
void choppersound_activate_sound(ChopperSound *s);         // 0x00215050, 48

// 0x00215098. bMalloc(48, "ChopperSound", 0, 16) and the constructor.
// chopper.h's gCreateChopperSoundFn.
Sound3d *choppersound_create(struct Chopper *h);

#endif
