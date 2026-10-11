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

// 0x0031c300, by car type: the car a reward unlocked, for
// SPCH1Type_unlockCarType, unlockHPCarType and unlockCopCarType alike.
static const uint32_t kRewardCarType[67] = {
    0x00001000, 0x00001000, 0x00200000, 0x00200000,     //  0
    0x00000001, 0x00000010, 0x00000010, 0x00002000,     //  4
    0x00002000, 0x00004000, 0x00004000, 0x00008000,     //  8
    0x00008000, 0x00000800, 0x00000800, 0x00000001,     // 12
    0x00000001, 0x00000004, 0x00000004, 0x00040000,     // 16
    0x00000040, 0x00000080, 0x00000080, 0x00000200,     // 20
    0x00000200, 0x00400000, 0x00400000, 0x00080000,     // 24
    0x00080000, 0x00000002, 0x00000002, 0x00000002,     // 28
    0x00000010, 0x00000004, 0x00000020, 0x00010000,     // 32
    0x00010000, 0x00020000, 0x00020000, 0x00100000,     // 36
    0x00100000, 0x00000400, 0x00000400, 0x00000020,     // 40
    0x00000020, 0x00000100, 0x00000100, 0x00000008,     // 44
    0x00000008, 0, 0, 0,                                // 48
    0, 0, 0, 0,                                         // 52
    0, 0, 0, 0,                                         // 56
    0, 0, 0, 0,                                         // 60
    0, 0, 0,                                            // 64
};

int32_t speech_convert_reward_car_type(int32_t carType)
{
    if (carType < 0 || carType >= 67)
        return 0;
    return (int32_t)kRewardCarType[carType];
}

// An event tree's event by its number: 1 to 20 from the first table, 21
// to 34 from the second; the Hot Pursuit tree's at 0x0031c410 and
// 0x0031c460, the championship's at 0x0031c498 and 0x0031c4e8.
static const uint32_t kHotPursuitEventA[20] = {
    0x00001, 0x00002, 0,       0x00008, 0,       0x00020, 0x00040, 0x00080,
    0,       0,       0,       0,       0,       0,       0x08000, 0,
    0x10000, 0,       0x40000, 0x80000,
};
static const uint32_t kHotPursuitEventB[14] = {
    0x001, 0x002, 0x004, 0,     0x010, 0x020, 0,     0,
    0,     0x200, 0x400, 0x800, 0,     0,
};
static const uint32_t kChampionshipEventA[20] = {
    0,       0x00002, 0x00004, 0x00008, 0x00010, 0x00020, 0x00040, 0x00080,
    0x00100, 0,       0x00400, 0x00800, 0x01000, 0x02000, 0x04000, 0x08000,
    0x10000, 0x20000, 0x40000, 0x80000,
};
static const uint32_t kChampionshipEventB[14] = {
    0x001, 0,     0x004, 0x008, 0x010, 0x020, 0x040, 0x080,
    0x100, 0x200, 0x400, 0x800, 0,     0,
};

static int32_t event_bits(const uint32_t *t, int32_t n, int32_t i)
{
    if (i < 0 || i >= n)
        return 0;
    return (int32_t)t[i];
}

int32_t speech_convert_hp_event_a(int32_t number)
{
    return event_bits(kHotPursuitEventA, 20, number - 1);
}

int32_t speech_convert_hp_event_b(int32_t number)
{
    return event_bits(kHotPursuitEventB, 14, number - 21);
}

int32_t speech_convert_championship_event_a(int32_t number)
{
    return event_bits(kChampionshipEventA, 20, number - 1);
}

int32_t speech_convert_championship_event_b(int32_t number)
{
    return event_bits(kChampionshipEventB, 14, number - 21);
}

// The tracks are numbered by tens, the second digit 1 to 6 within each:
// 4 to 6 are 1 to 3 again.
int32_t speech_convert_track_number(int32_t track)
{
    // The jump table at 0x002bce20, by track - 11.
    switch (track) {
    case 11: case 14: return 0x1000;
    case 12: case 15: return 0x2000;
    case 13: case 16: return 0x4000;
    case 21: case 24: return 0x8;
    case 22: case 25: return 0x10;
    case 23: case 26: return 0x20;
    case 31: case 34: return 0x200;
    case 32: case 35: return 0x400;
    case 33: case 36: return 0x800;
    case 41: case 44: return 0x4;
    case 42: case 45: return 0x2;
    case 43: case 46: return 0x1;
    case 61: case 64: return 0x40;
    case 62: case 65: return 0x80;
    case 63: case 66: return 0x100;
    default:          return 0;
    }
}

int32_t speech_convert_unlock_track(int32_t track)
{
    // The jump table at 0x002bcf00, by track - 11.
    switch (track) {
    case 11: case 14: return 0x8000;
    case 12: case 15: return 0x20;
    case 13: case 16: return 0x10000;
    case 21: case 24: return 0x8;
    case 22: case 25: return 0x10;
    case 23: case 26: return 0x800;
    case 31: case 34: return 0x1000;
    case 32: case 35: return 0x2000;
    case 33: case 36: return 0x4000;
    case 41: case 44: return 0x100;
    case 42: case 45: return 0x2;
    case 43: case 46: return 0x20000;
    case 61: case 64: return 0x4;
    case 62: case 65: return 0x200;
    case 63: case 66: return 0x400;
    default:          return 0;
    }
}
