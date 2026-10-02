#pragma once
#include <stdint.h>

// ChooseLoadableTextures (retail 0x001ee3c0; the demo's 0x001e0240 makes
// no ThirdPerson): the names of the HUD textures a car's gauges are drawn
// with, hashed. Two
// callers: LoadHudTextures (trackflow.c), which streams them into the HUD
// pack before a race, and Player::SetHudFeatures (0x001796b0), which binds
// them. Decompiled in docs/formats/track-flow.md.

// tLoadableHudTextures, 16 bytes in retail: the demo's three words and the
// third-person gauge's. A 0 Tach is a car whose gauges are one picture.
typedef struct tLoadableHudTextures {
    uint32_t Speedo;        // 0   <base>_MPH or <base>_KMH
    uint32_t Tach;          // 4   <base>_TACH, or 0 when integrated
    uint32_t Shadow;        // 8   OVERLAY_<base> or OVERLAY_GENERIC
    uint32_t ThirdPerson;   // 12  3RDPERSON_<MaxRPM>
} tLoadableHudTextures;

// eUnitsSetting, tGlobalDisplaySettings.Units' values.
#define UNITS_MPH 0
#define UNITS_KPH 1

// `car` indexes CarTypeInfoArray unchecked, as everywhere. A units value
// that is neither leaves the Speedo the 3RDPERSON_ name's hash.
void ChooseLoadableTextures(int32_t car, int32_t units,
                            tLoadableHudTextures *t);
