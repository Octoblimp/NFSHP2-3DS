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

// CarLanguageInfo, 0x0030d578 in the image's data: 50 rows of 28 bytes.
// The first, for car type -1, is the one FindCarLanguageInfo falls back
// on. The comments are the short names in English.
const CarSpecs CarLanguageInfoTable[CARINFO_NUM_LANGUAGE_INFO] = {
    {  -1,  42002,  43002,  43102,  44002,  41100,  41300 },  // Corvette
    {   0,  42002,  43002,  43102,  44002,  41100,  41300 },  // Corvette
    {   2,  42003,  43003,  43103,  44003,  41101,  41301 },  // Viper
    {   4,  42004,  43004,  43104,  44004,  41102,  41302 },  // Crown Vic
    {   5,  42006,  43006,  43106,  44006,  41103,  41303 },  // CLK-GTR
    {   7,  42007,  43007,  43107,  44007,  41104,  41304 },  // F1
    {   9,  42008,  43008,  43108,  44008,  41105,  41305 },  // F1 LM
    {  11,  42009,  43009,  43109,  44009,  41106,  41306 },  // Mustang
    {  13,  42010,  43010,  43110,  44010,  41107,  41307 },  // TS50
    {  15,  42011,  43011,  43111,  44011,  41108,  41308 },  // HSV
    {  17,  42012,  43012,  43112,  44012,  41109,  41309 },  // Carrera GT
    {  19,  42013,  43013,  43113,  44013,  41110,  41310 },  // M5
    {  20,  42014,  43014,  43114,  44014,  41111,  41311 },  // Z8
    {  21,  42015,  43015,  43115,  44015,  41112,  41312 },  // Spider
    {  23,  42016,  43016,  43116,  44016,  41113,  41313 },  // F50
    {  27,  42017,  43017,  43117,  44017,  41114,  41314 },  // XKR
    {  29,  42018,  43018,  43118,  44018,  41115,  41315 },  // V12 Vanquish
    {  31,  42019,  43019,  43119,  44019,  41116,  41316 },  // M5 Cop
    {  32,  42020,  43020,  43120,  44020,  41117,  41317 },  // Murc. Cop
    {  33,  42021,  43021,  43121,  44021,  41118,  41318 },  // Corvette Cop
    {  34,  42022,  43022,  43122,  44022,  41119,  41319 },  // Mustang Cop
    {  35,  42023,  43023,  43123,  44023,  41120,  41320 },  // VX220
    {  37,  42024,  43024,  43124,  44024,  41121,  41321 },  // Speedster
    {  39,  42025,  43025,  43125,  44025,  41122,  41322 },  // 911 Turbo
    {  41,  42026,  43026,  43126,  44026,  41123,  41323 },  // Elise
    {  43,  42027,  43027,  43127,  44027,  41124,  41324 },  // CL55 AMG
    {  45,  42028,  43028,  43128,  44028,  41125,  41325 },  // Diablo
    {  47,  42029,  43029,  43129,  44029,  41126,  41326 },  // Murcielago
    {  25,  42041,  43041,  43141,  44041,  41127,  41327 },  // Barchetta
    {   1,  42002,  43002,  43102,  44002,  41200,  41400 },  // Corvette
    {   3,  42003,  43003,  43103,  44003,  41201,  41401 },  // Viper
    {   6,  42006,  43006,  43106,  44006,  41202,  41402 },  // CLK-GTR
    {   8,  42007,  43007,  43107,  44007,  41203,  41403 },  // F1
    {  10,  42008,  43008,  43108,  44008,  41204,  41404 },  // F1 LM
    {  12,  42009,  43009,  43109,  44009,  41205,  41405 },  // Mustang
    {  14,  42010,  43010,  43110,  44010,  41206,  41406 },  // TS50
    {  16,  42011,  43011,  43111,  44011,  41207,  41407 },  // HSV
    {  18,  42012,  43012,  43112,  44012,  41208,  41408 },  // Carrera GT
    {  24,  42016,  43016,  43116,  44016,  41212,  41412 },  // F50
    {  28,  42017,  43017,  43117,  44017,  41213,  41413 },  // XKR
    {  30,  42018,  43018,  43118,  44018,  41214,  41414 },  // V12 Vanquish
    {  36,  42023,  43023,  43123,  44023,  41215,  41415 },  // VX220
    {  38,  42024,  43024,  43124,  44024,  41216,  41416 },  // Speedster
    {  40,  42025,  43025,  43125,  44025,  41217,  41417 },  // 911 Turbo
    {  42,  42026,  43026,  43126,  44026,  41218,  41418 },  // Elise
    {  44,  42027,  43027,  43127,  44027,  41219,  41419 },  // CL55 AMG
    {  46,  42028,  43028,  43128,  44028,  41220,  41420 },  // Diablo
    {  48,  42029,  43029,  43129,  44029,  41221,  41421 },  // Murcielago
    {  26,  42041,  43041,  43141,  44041,  41222,  41422 },  // Barchetta
    {  22,  42042,  43042,  43142,  44042,  41211,  41411 },  // Modena
};

const CarSpecs *find_car_language_info(int32_t type)
{
    int i;

    // 0x00187e80: the first row whose type matches, else the first row.
    for (i = 0; i < CARINFO_NUM_LANGUAGE_INFO; i++)
        if (CarLanguageInfoTable[i].CarType == type)
            return &CarLanguageInfoTable[i];
    return &CarLanguageInfoTable[0];
}

void init_car_info(void)
{
    int i;

    // 0x00188d08. Every type's pCarSpecs, over the records in
    // CarTypeInfoArray, which LoadGlobalChunks has pointed at GLOBALB's.
    // Retail then tail-calls 0x00188ca8, which asks GetNumSkins
    // (0x001884b8) of each type with a GeometryFilename and drops the
    // answer: nothing to port.
    for (i = 0; i < CARINFO_NUM_TYPES; i++)
        ((CarTypeInfo *)&CarTypeInfoArray[i])->pCarSpecs =
            find_car_language_info(i);
}
