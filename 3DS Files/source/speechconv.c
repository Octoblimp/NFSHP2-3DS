// speechconv -- the Speech namespace's conversions. See speechconv.h.

#include "speechconv.h"

// 0x0031c1f0, by car type: each racer's racerVehicleExactDescription_t.
static const uint32_t kCarTypeDescription[67] = {
    0x00000001, 0x00000001, 0x00000020, 0x00000020,     //  0
    0x00000001, 0x00000008, 0x00000008, 0x00000002,     //  4
    0x00000002, 0x02000000, 0x02000000, 0x00040000,     //  8
    0x00040000, 0x00080000, 0x00080000, 0x00100000,     // 12
    0x00100000, 0x00000100, 0x00000100, 0x00002000,     // 16
    0x00000400, 0x00000200, 0x20000000, 0x00000080,     // 20
    0x00000080, 0x04000000, 0x04000000, 0x00001000,     // 24
    0x00001000, 0x00400000, 0x00400000, 0x00000002,     // 28
    0x00000010, 0x00000004, 0x00000020, 0x00020000,     // 32
    0x00020000, 0x00010000, 0x00010000, 0x00000010,     // 36
    0x00000010, 0x00008000, 0x00008000, 0x00000800,     // 40
    0x00000800, 0x00000040, 0x00000040, 0x00000004,     // 44
    0x00000004, 0, 0, 0,                                // 48
    0, 0, 0, 0,                                         // 52
    0, 0, 0, 0,                                         // 56
    0, 0, 0, 0,                                         // 60
    0, 0, 0,                                            // 64
};

int32_t speech_convert_car_type(int32_t carType)
{
    if (carType < 0 || carType >= 67)
        return 0;
    return (int32_t)kCarTypeDescription[carType];
}
