// carinfo -- see carinfo.h.

#include "carinfo.h"

#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "drivetrain.h"
#include "engine.h"

#define K_SPEED_STEP    1.38888896f     // 0x3fb1c71d, gp-30172: 5 km/h
#define K_SPEED_MAX     138.888901f     // 0x430ae38f, gp-30176: 500 km/h
#define K_RPM_PER_RADS  9.54930401f     // 0x4118c9f3, gp-30168: 60 / 2pi
#define K_DEFAULT_MAX   55.5555573f     // 0x425e38e4, gp-30180: 200 km/h
#define K_DEFAULT_ACCEL 4.0f            // 0x40800000

// `cvt.w.s` of 100.0, plus one, times four: a sample for each step to
// 500 km/h and one more.
#define MAX_SAMPLES 101

#define CARINFO_FILE "..\\indep\\src\\carinfo.cpp"
#define CARINFO_LINE 815
#define CARINFO_POOL 16

// On the 3DS the records are the chunk's own bytes, as on the console. A
// 64-bit host's CarTypeInfo is wider (pCarSpecs is a pointer), and its
// harness lays its chunk out to match.
#if UINTPTR_MAX == 0xffffffffu
typedef char carinfo_record_check[sizeof(CarTypeInfo) == 1376 ? 1 : -1];
typedef char carinfo_skin_check[sizeof(SkinInfo) == 64 ? 1 : -1];
#endif

AccelerationTable TheCarTypeAccelerationTable[CARINFO_NUM_TYPES];

static uint32_t chunk_id(const uint8_t *chunk)
{
    uint32_t id;

    memcpy(&id, chunk, 4);
    return id;
}

void acceleration_table_init(AccelerationTable *a)
{
    int i;

    table_init(&a->mTable, a->Data, 32, 0.0f, K_DEFAULT_MAX);
    for (i = 30; i >= 0; i--)
        a->Data[i] = K_DEFAULT_ACCEL;
    a->Data[31] = 0.0f;
}

void carinfo_static_init(void)
{
    int i;

    // 0x001890c8 (the demo's 0x00181060, which made 66).
    for (i = 0; i < CARINFO_NUM_TYPES; i++)
        acceleration_table_init(&TheCarTypeAccelerationTable[i]);
}

Table *get_acceleration_table(int32_t type)
{
    return &TheCarTypeAccelerationTable[type].mTable;
}

void make_acceleration_table(Table *t, const CarTypeInfo *ct)
{
    const DriveTrainInfo *dt = &ct->DriveTrain;
    const EngineInfo *ei = &ct->Engine;
    // Twelve words each at the frame's base, as the image keeps them.
    float up[12], down[12];
    float split = dt->TorqueSplit;
    float drive, radius, mass, speed, rpm, range;
    float *samples;
    Table torque, accel;
    int32_t gear, n, i;

    drive = (1.0f - split) * dt->FinalDrive[0] + split * dt->FinalDrive[1];
    radius = (1.0f - split) * ct->Wheels[0].Radius
           + split * ct->Wheels[2].Radius;
    mass = ct->Body.Mass;
    // gShiftUpDetune, gp-20548: the drivetrain's own, not a constant.
    drivetrain_calculate_shift_points(dt, ei, up, down, gShiftUpDetune);
    table_init(&torque, ei->TorqueCurveTable, 9, ei->IdleRPM, ei->MaxRPM);
    samples = (float *)bMalloc(MAX_SAMPLES * (int)sizeof(float),
                               CARINFO_FILE, CARINFO_LINE, CARINFO_POOL);

    speed = 0.0f;
    rpm = 0.0f;
    n = 0;
    gear = FIRST_GEAR;
    // First gear's up point at or below 0 starts in second, if there is
    // one; with none there are no samples at all.
    if (up[FIRST_GEAR] <= 0.0f) {
        gear = FIRST_GEAR + 1;
        if (!(gear < dt->NumGears + 2))
            goto sampled;
    }
    for (;;) {
        float a;

        // The step is taken in GetValue's delay slot: the torque is the
        // RPM the step before left, and the ratio the gear's now, so the
        // first sample in a new gear has the old gear's RPM.
        speed += K_SPEED_STEP;
        a = table_get_value(&torque, rpm) * drive;
        a = a * dt->GearRatios[gear];
        a = a / radius;
        a = a / mass;
        samples[n++] = a;
        if (!(speed < K_SPEED_MAX))
            break;
        rpm = speed / radius * drive * dt->GearRatios[gear] * K_RPM_PER_RADS;
        if (up[gear] <= rpm) {
            gear++;
            if (!(gear < dt->NumGears + 2))
                break;
        }
    }
sampled:
    // With no samples -- at most one gear and a MaxRPM at or below 0, which
    // no record on the disc has -- the image zeroes the word before the
    // allocation, bMalloc's own, and builds a Table of no entries with no
    // range, which then reads the allocation unwritten. The port leaves `t`
    // as it was instead.
    if (n == 0)
        return;
    samples[n - 1] = 0.0f;
    table_init(&accel, samples, n, 0.0f, speed);
    range = speed - 0.0f;
    // The count is read again each pass, as the image reads it.
    for (i = 0; i < t->NumEntries; i++) {
        float at = (float)i * range / (float)(t->NumEntries - 1);

        ((float *)t->pTable)[i] = table_get_value(&accel, 0.0f + at);
    }
    table_set_min_max(t, 0.0f, speed);
}

int loader_car_info(uint8_t *chunk)
{
    uint32_t id = chunk_id(chunk);
    int i;

    if (id == CARINFO_CHUNK) {
        CarTypeInfoArray = (const CarTypeInfo *)(void *)
            (((uintptr_t)chunk + 23) & ~(uintptr_t)15);
        for (i = 0; i < CARINFO_NUM_TYPES; i++)
            make_acceleration_table(get_acceleration_table(i),
                                    &CarTypeInfoArray[i]);
        return 1;
    }
    if (id == CARINFO_SKIN_CHUNK) {
        uint32_t size;

        memcpy(&size, chunk + 4, 4);
        SkinInfoTable = (SkinInfo *)(void *)(chunk + 8);
        NumSkinInfo = (int32_t)(size >> 6);
        return 1;
    }
    return 0;
}

int unloader_car_info(uint8_t *chunk)
{
    uint32_t id = chunk_id(chunk);

    if (id == CARINFO_CHUNK) {
        CarTypeInfoArray = NULL;
        return 1;
    }
    if (id == CARINFO_SKIN_CHUNK) {
        SkinInfoTable = NULL;
        NumSkinInfo = 0;
        return 1;
    }
    return 0;
}
