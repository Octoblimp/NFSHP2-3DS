// sound3d -- Sound3d, the record only.
//
// Thirty-two bytes and no pointers, so it is the same record on every
// target. Every positional sound in the game derives from it -- the car's
// engine, horn and siren, the 3D effects -- and it is task 29's.
//
// Car reaches it once: UpdateSound calls `Update` on the BaseCarSound at
// Car+1952, and BaseCarSound's first base is Sound3d at offset 0
// (`BaseCarSound:Tt824=s80!1,020,3181`), so the vptr Car reads at +28 of
// the BaseCarSound is this record's. BaseCarSound itself stays opaque until
// task 29 brings it.

#ifndef SOUND3D_H
#define SOUND3D_H

#include <stddef.h>
#include <stdint.h>

typedef struct Sound3d {
    int32_t  Activated;             //  0  bool, a word wide in this compiler
    int32_t  DopplerIsActive;       //  4  bool
    float    Volume;                //  8
    float    Pitch;                 // 12
    uint16_t Azimuth;               // 16
    uint8_t  _pad18[2];             // 18
    float    SndToCameraVelocity;   // 20
    float    SndToCameraDistance;   // 24
    uint32_t _vtable;               // 28  `$vf3181:47,224`
} Sound3d;                          // 32

typedef char sound3d_layout_check[
    (offsetof(Sound3d, Azimuth) == 16
     && offsetof(Sound3d, SndToCameraVelocity) == 20
     && offsetof(Sound3d, _vtable) == 28
     && sizeof(Sound3d) == 32) ? 1 : -1];

// _vt$12BaseCarSound. Slot 24 is BaseCarSound::Update(float, unsigned
// short, float), overriding Sound3d's.
#define BASECARSOUND_VTABLE        0x00297dc8u
#define BASEPLAYERCARSOUND_VTABLE  0x00297d80u
#define BASEAICARSOUND_VTABLE      0x00297d38u

#define SOUND3D_VT_UPDATE 24

#endif
