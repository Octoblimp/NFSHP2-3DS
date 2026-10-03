// Transcript harness for CarTypeInfo. Cross-checked by
// tools/cartypeinfo_check.py, which models the same behaviour from the
// disassembly without reading this file.
//
// Build and run via tools/cartypeinfo_check.py; every line printed here is
// compared against the model's, line for line.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bchunk.h"
#include "bmath.h"
#include "cartypeinfo.h"
#include "langtab.h"

// ------------------------------------------------------------- the layout

// Writes a value at a PS2 offset, so the host struct's named fields can be
// read back and shown to land on the same bytes.
static void poke_f(void *base, size_t off, float v)
{
    memcpy((unsigned char *)base + off, &v, 4);
}

static void poke_i(void *base, size_t off, int32_t v)
{
    memcpy((unsigned char *)base + off, &v, 4);
}

static void scenario_layout(void)
{
    printf("[layout]\n");
    printf("sizeof_host %zu\n", sizeof(CarTypeInfo));
    printf("slack %zu\n", CARTYPEINFO_SLACK);

#define OFF(f) printf("off %-34s %zu\n", #f, offsetof(CarTypeInfo, f))
    OFF(CarTypeName); OFF(BaseModelName); OFF(GeometryFilename);
    OFF(CompressedGeometryFilename); OFF(DashGeometryFilename);
    OFF(CompressedDashGeometryFilename); OFF(ManufacturerName);
    OFF(HeadlightPosition); OFF(HeadlightFOV); OFF(HighPerformance);
    OFF(NumAvailableSkins); OFF(CarClass); OFF(OpenTop);
    OFF(DriverRenderingOffset);
    OFF(InCarSteeringWheelRenderingOffset); OFF(CenterOfGravity);
    OFF(Wheels); OFF(Tires); OFF(Body); OFF(Suspension); OFF(DriveTrain);
    OFF(Engine); OFF(Aero); OFF(Control); OFF(Sound); OFF(Camera);
    OFF(HudInfo); OFF(LocationProb); OFF(Type); OFF(UsageType);
    OFF(InitialLockStatus); OFF(BeACopLockStatus); OFF(AvailableSkins);
    OFF(Dummy); OFF(DefaultSkinNumber); OFF(pCarSpecs);
#undef OFF

    printf("size WheelInfo %zu\n", sizeof(WheelInfo));
    printf("size TireInfo %zu\n", sizeof(TireInfo));
    printf("size SuspensionInfo %zu\n", sizeof(SuspensionInfo));
    printf("size DriveTrainInfo %zu\n", sizeof(DriveTrainInfo));
    printf("size RigidBodyInfo %zu\n", sizeof(RigidBodyInfo));
    printf("size AeroInfo %zu\n", sizeof(AeroInfo));
    printf("size ControlInfo %zu\n", sizeof(ControlInfo));
    printf("size EngineInfo %zu\n", sizeof(EngineInfo));
    printf("size CarSpecs %zu\n", sizeof(CarSpecs));

    // Offsets of fields *inside* the nested records, measured from the top
    // of CarTypeInfo, so a wrong nested layout shows up even where the
    // outer offset is right.
    printf("noff %-24s %zu\n", "Wheels[2].Radius",
           offsetof(CarTypeInfo, Wheels) + 2 * sizeof(WheelInfo)
               + offsetof(WheelInfo, Radius));
    printf("noff %-24s %zu\n", "Tires[1].ForceScale",
           offsetof(CarTypeInfo, Tires) + sizeof(TireInfo)
               + offsetof(TireInfo, ForceScale));
    printf("noff %-24s %zu\n", "Body.InertiaTensor",
           offsetof(CarTypeInfo, Body)
               + offsetof(RigidBodyInfo, InertiaTensor));
    printf("noff %-24s %zu\n", "Suspension[1].Damping1",
           offsetof(CarTypeInfo, Suspension) + sizeof(SuspensionInfo)
               + offsetof(SuspensionInfo, Damping) + 4);
    printf("noff %-24s %zu\n", "Suspension[0].BumpStop1",
           offsetof(CarTypeInfo, Suspension)
               + offsetof(SuspensionInfo, BumpStop) + 4);
    printf("noff %-24s %zu\n", "DriveTrain.GearRatios5",
           offsetof(CarTypeInfo, DriveTrain)
               + offsetof(DriveTrainInfo, GearRatios) + 5 * 4);
    printf("noff %-24s %zu\n", "Engine.MomentOfInertia",
           offsetof(CarTypeInfo, Engine)
               + offsetof(EngineInfo, MomentOfInertia));
    printf("noff %-24s %zu\n", "Control.SpeedLimiter",
           offsetof(CarTypeInfo, Control)
               + offsetof(ControlInfo, SpeedLimiter));

    // How long every array member is. An array's *extent* is part of the
    // layout claim just as much as its offset, and the offsets alone do
    // not pin it: shortening Wheels to three and putting 32 bytes of
    // padding after it leaves every following offset where it was. So
    // measure the extents too.
#define ARR(f) printf("arr %-28s %zu\n", #f, \
                      sizeof(((CarTypeInfo *)0)->f))
    ARR(CarTypeName); ARR(BaseModelName); ARR(GeometryFilename);
    ARR(CompressedGeometryFilename); ARR(DashGeometryFilename);
    ARR(CompressedDashGeometryFilename); ARR(ManufacturerName);
    ARR(Wheels); ARR(Tires); ARR(Suspension); ARR(Sound); ARR(Camera);
    ARR(HudInfo); ARR(LocationProb); ARR(AvailableSkins); ARR(Dummy);
#undef ARR
#define NARR(t, f) printf("arr %-28s %zu\n", #t "." #f, \
                          sizeof(((t *)0)->f))
    NARR(WheelInfo, Padding);
    NARR(TireInfo, dummy);
    NARR(SuspensionInfo, Damping);
    NARR(SuspensionInfo, BumpStop);
    NARR(DriveTrainInfo, FinalDrive);
    NARR(DriveTrainInfo, GearRatios);
    NARR(RigidBodyInfo, InertiaTensor);
    NARR(ControlInfo, dummy);
    NARR(EngineInfo, TorqueCurveTable);
    NARR(EngineInfo, EngineBrakingTable);
#undef NARR

    // Poke at PS2 offsets, read through the named fields.
    CarTypeInfo *ct = calloc(1, sizeof(CarTypeInfo));

    memcpy((unsigned char *)ct + 0, "CIVIC", 6);
    memcpy((unsigned char *)ct + 192, "HONDA", 6);
    poke_f(ct, 208, 1.25f); poke_f(ct, 212, -2.5f); poke_f(ct, 216, 7.5f);
    poke_f(ct, 224, 55.0f);
    // Four bytes, retail's lb at 228, 229, 230 and 231.
    ((signed char *)ct)[228] = 1; ((signed char *)ct)[229] = 7;
    ((signed char *)ct)[230] = 3; ((signed char *)ct)[231] = -2;
    poke_f(ct, 272, 0.125f); poke_f(ct, 276, 0.25f); poke_f(ct, 280, -0.5f);
    poke_f(ct, 288 + 2 * 32 + 12, 0.34f);   // Wheels[2].Radius
    poke_f(ct, 416 + 32 + 8, 4.5f);         // Tires[1].ForceScale
    poke_f(ct, 480 + 0, 1400.0f);           // Body.Mass
    poke_f(ct, 480 + 16 + 5 * 4, 900.0f);   // Body.InertiaTensor row1.y
    poke_f(ct, 560 + 32 + 8 + 4, 6.0f);     // Suspension[1].Damping[1]
    poke_f(ct, 560 + 20 + 4, 11.0f);        // Suspension[0].BumpStop[1]
    poke_i(ct, 624 + 24, 6);                // DriveTrain.NumGears
    poke_f(ct, 624 + 32 + 5 * 4, 0.85f);    // DriveTrain.GearRatios[5]
    poke_f(ct, 688 + 12, 0.35f);            // Engine.MomentOfInertia
    poke_f(ct, 752 + 8, 120.0f);            // Aero.RearDownforce
    poke_f(ct, 768 + 32, 62.5f);            // Control.SpeedLimiter
    poke_i(ct, 1332, 9); poke_i(ct, 1336, 2);
    poke_i(ct, 1340, 1); poke_i(ct, 1344, 0);
    ((signed char *)ct)[1348 + 0] = 3;
    ((signed char *)ct)[1348 + 4] = -7;
    ((signed char *)ct)[1348 + 9] = 120;
    poke_i(ct, 1364, 5);

    printf("read CarTypeName %s\n", ct->CarTypeName);
    printf("read ManufacturerName %s\n", ct->ManufacturerName);
    printf("read HeadlightPosition %.9g %.9g %.9g\n",
           ct->HeadlightPosition.x, ct->HeadlightPosition.y,
           ct->HeadlightPosition.z);
    printf("read HeadlightFOV %.9g\n", ct->HeadlightFOV);
    printf("read HighPerformance %d\n", ct->HighPerformance);
    printf("read NumAvailableSkins %d\n", ct->NumAvailableSkins);
    printf("read CarClass %d\n", ct->CarClass);
    printf("read OpenTop %d\n", ct->OpenTop);
    printf("read CenterOfGravity %.9g %.9g %.9g\n",
           ct->CenterOfGravity.x, ct->CenterOfGravity.y,
           ct->CenterOfGravity.z);
    printf("read Wheels2Radius %.9g\n", ct->Wheels[2].Radius);
    printf("read Tires1ForceScale %.9g\n", ct->Tires[1].ForceScale);
    printf("read BodyMass %.9g\n", ct->Body.Mass);
    printf("read BodyInertia5 %.9g\n", ct->Body.InertiaTensor.v1.y);
    printf("read Susp1Damping1 %.9g\n", ct->Suspension[1].Damping[1]);
    printf("read Susp0BumpStop1 %.9g\n", ct->Suspension[0].BumpStop[1]);
    printf("read NumGears %d\n", ct->DriveTrain.NumGears);
    printf("read GearRatios5 %.9g\n", ct->DriveTrain.GearRatios[5]);
    printf("read EngineMOI %.9g\n", ct->Engine.MomentOfInertia);
    printf("read AeroRearDownforce %.9g\n", ct->Aero.RearDownforce);
    printf("read SpeedLimiter %.9g\n", ct->Control.SpeedLimiter);
    printf("read Type %d\n", ct->Type);
    printf("read UsageType %d\n", ct->UsageType);
    printf("read InitialLockStatus %d\n", ct->InitialLockStatus);
    printf("read BeACopLockStatus %d\n", ct->BeACopLockStatus);
    printf("read Skins %d %d %d\n", ct->AvailableSkins[0],
           ct->AvailableSkins[4], ct->AvailableSkins[9]);
    printf("read DefaultSkinNumber %d\n", ct->DefaultSkinNumber);

    free(ct);
}

// -------------------------------------------------------- the string table

// A hand-built LANGTAB payload. The pool's last string has no NUL, which is
// the case langtab's own doc calls out, so the accessors have to carry the
// length back rather than relying on termination.
static const char POOL[] =
    "Honda Civic Type R\0"   //  0, len 18
    "Civic\0"                // 19, len  5
    "6.8 s\0"                // 25, len  5
    "300 km/h\0"             // 31, len  8
    "197 bhp\0"              // 40, len  7
    "Honda";                 // 48, len  5, no NUL after it
#define POOL_LEN (sizeof(POOL) - 1)

static uint8_t g_payload[4096];

static void put_u32(uint8_t *p, uint32_t v)
{
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
    p[2] = (uint8_t)(v >> 16);
    p[3] = (uint8_t)(v >> 24);
}

// { key, offset } pairs. Both tables are binary-searched, so both are
// sorted ascending as *signed* words.
typedef struct { int32_t key; uint32_t off; } Ent;

static int cmp_ent(const void *a, const void *b)
{
    int32_t x = ((const Ent *)a)->key;
    int32_t y = ((const Ent *)b)->key;
    return (x > y) - (x < y);
}

static void build_table(LangTable *t)
{
    Ent ids[] = {
        { 100, 0 },     // "Honda Civic Type R"
        { 101, 19 },    // "Civic"
        { 102, 25 },    // "6.8 s"
        { 103, 31 },    // "300 km/h"
        { 104, 40 },    // "197 bhp"
        { 999, 9000 },  // an offset past the pool: lookup answers NULL
    };
    Ent hashes[] = {
        { (int32_t)bchunk_hash("HONDA"), 48 },  // the unterminated tail
        { (int32_t)bchunk_hash("FORD"), 19 },
        { (int32_t)bchunk_hash(""), 0 },
    };
    size_t nid = sizeof(ids) / sizeof(ids[0]);
    size_t nh = sizeof(hashes) / sizeof(hashes[0]);
    qsort(ids, nid, sizeof(Ent), cmp_ent);
    qsort(hashes, nh, sizeof(Ent), cmp_ent);

    memset(g_payload, 0, sizeof(g_payload));
    memcpy(g_payload + 8, "FE_ENG.BIN", 11);
    put_u32(g_payload + 72, 0);                 // languageEnum = LANG_EN
    put_u32(g_payload + 76, (uint32_t)nh);
    put_u32(g_payload + 80, (uint32_t)nid);
    put_u32(g_payload + 84, (uint32_t)POOL_LEN);

    uint8_t *p = g_payload + 100;
    for (size_t i = 0; i < nh; i++) {
        put_u32(p, (uint32_t)hashes[i].key);
        put_u32(p + 4, hashes[i].off);
        p += 8;
    }
    for (size_t i = 0; i < nid; i++) {
        put_u32(p, (uint32_t)ids[i].key);
        put_u32(p + 4, ids[i].off);
        p += 8;
    }
    memcpy(p, POOL, POOL_LEN);
    p += POOL_LEN;

    if (!langtab_parse(t, g_payload, (uint32_t)(p - g_payload))) {
        printf("PARSE FAILED\n");
        exit(1);
    }
}

static void show(const char *what, const char *tag, const char *s, size_t len)
{
    if (!s) {
        printf("%s %s NULL\n", tag, what);
        return;
    }
    printf("%s %s %zu [%.*s]\n", tag, what, len, (int)len, s);
}

static void accessors(const CarTypeInfo *ct, const LangTable *t,
                      const char *tag)
{
    size_t n;
    const char *s;
    int units;

    n = 0xdead; s = cartypeinfo_get_full_name(ct, t, &n);
    show("full", tag, s, n);
    n = 0xdead; s = cartypeinfo_get_short_name(ct, t, &n);
    show("short", tag, s, n);
    n = 0xdead; s = cartypeinfo_get_car_spec_0_to_60(ct, t, &n);
    show("0to60", tag, s, n);
    for (units = 0; units <= 3; units++) {
        static const int32_t asked[4] = { 0, 1, 2, -1 };
        char what[16];

        snprintf(what, sizeof what, "topspd%d", (int)asked[units]);
        n = 0xdead;
        s = cartypeinfo_get_car_spec_top_speed(ct, asked[units], t, &n);
        show(what, tag, s, n);
    }
    n = 0xdead; s = cartypeinfo_get_car_spec_bhp(ct, t, &n);
    show("bhp", tag, s, n);
    n = 0xdead; s = cartypeinfo_get_manufacturer_name(ct, t, &n);
    show("manuf", tag, s, n);
}

static void scenario_strings(void)
{
    printf("[strings]\n");

    LangTable t;
    build_table(&t);
    printf("parsed numHash %u numID %u textSize %u lang %d file %s\n",
           t.numHash, t.numID, t.textSize, t.languageEnum, t.fileName);
    printf("hash HONDA %d\n", (int32_t)bchunk_hash("HONDA"));
    printf("hash FORD %d\n", (int32_t)bchunk_hash("FORD"));
    printf("hash empty %d\n", (int32_t)bchunk_hash(""));

    CarTypeInfo *ct = calloc(1, sizeof(CarTypeInfo));

    // The ids present, manufacturer present. The field at CarSpecs+0 is
    // set to something no accessor should ever reach for.
    static const CarSpecs good = { 77, 102, 103, 101, 104, 100, 101 };
    ct->pCarSpecs = &good;
    memcpy(ct->ManufacturerName, "HONDA", 6);
    accessors(ct, &t, "good");

    // Every id absent, manufacturer absent.
    static const CarSpecs bad = { 100, 1, 2, 3, 4, 5, 6 };
    ct->pCarSpecs = &bad;
    memcpy(ct->ManufacturerName, "NOPE", 5);
    accessors(ct, &t, "absent");

    // The out-of-range offset: the key is found, the offset is not usable.
    static const CarSpecs oob = { 100, 999, 999, 999, 999, 999, 999 };
    ct->pCarSpecs = &oob;
    memset(ct->ManufacturerName, 0, 16);   // hashes to the empty-string key
    accessors(ct, &t, "oob");

    // Ids that swap two fields round, so an accessor reading the wrong
    // CarSpecs slot answers a different string rather than nothing.
    static const CarSpecs swapped = { 104, 100, 101, 102, 103, 104, 102 };
    ct->pCarSpecs = &swapped;
    memcpy(ct->ManufacturerName, "FORD", 5);
    accessors(ct, &t, "shifted");

    // The km/h and the short name differ here, where the two above share
    // an id.
    static const CarSpecs rotated = { 0, 103, 104, 100, 101, 102, 999 };
    ct->pCarSpecs = &rotated;
    memcpy(ct->ManufacturerName, "HONDA", 6);
    accessors(ct, &t, "rotated");

    // The manufacturer is the one accessor that does not read pCarSpecs at
    // all, so it still answers with a null pCarSpecs. The other five would
    // dereference NULL, which the image does too -- not exercised.
    ct->pCarSpecs = NULL;
    memcpy(ct->ManufacturerName, "FORD", 5);
    size_t n = 0xdead;
    const char *s = cartypeinfo_get_manufacturer_name(ct, &t, &n);
    show("manuf", "nullspecs", s, n);

    // A 16-byte ManufacturerName with no room for a NUL runs on into
    // HeadlightPosition. The image has the same hole; the port inherits it,
    // so pin what it actually does rather than pretending it is guarded.
    memcpy(ct->ManufacturerName, "0123456789ABCDEF", 16);
    ((unsigned char *)ct)[208] = 0;
    printf("manuf overrun hash %d\n", (int32_t)bchunk_hash(ct->ManufacturerName));

    free(ct);
}

// ------------------------------------------------------------- random skin

static void scenario_skins(void)
{
    printf("[skins]\n");

    CarTypeInfo *ct = calloc(1, sizeof(CarTypeInfo));
    static const signed char skins[10] = { 3, 0, 9, -1, -7, 12, 4, 4, 0, 120 };
    memcpy(ct->AvailableSkins, skins, 10);

    // No skins: the answer is the cleared return register, not skins[0] --
    // which is 3 here, so the two are distinguishable.
    ct->NumAvailableSkins = 0;
    CarTypeInfoSkinSeed = 12345;
    // The draw and the seed go out in one printf, but the seed is a global
    // the draw writes and C does not order one argument against another --
    // so take the draw first and read the seed back on its own line.
    int32_t v = cartypeinfo_get_random_skin(ct);
    printf("none %d seed %u\n", v, CarTypeInfoSkinSeed);

    // One skin: bRandomI(1, ...) is always 0, but the seed still moves, so
    // the call is not side-effect free even when its answer is fixed.
    ct->NumAvailableSkins = 1;
    CarTypeInfoSkinSeed = 12345;
    for (int i = 0; i < 3; i++) {
        v = cartypeinfo_get_random_skin(ct);
        printf("one %d %d seed %u\n", i, v, CarTypeInfoSkinSeed);
    }

    // Wider ranges, so the sign-extended bytes show up in the answers.
    for (int32_t nskins = 2; nskins <= 10; nskins += 4) {
        ct->NumAvailableSkins = nskins;
        CarTypeInfoSkinSeed = 1;
        for (int i = 0; i < 8; i++) {
            v = cartypeinfo_get_random_skin(ct);
            printf("draw n%d %d %d seed %u\n", nskins, i, v,
                   CarTypeInfoSkinSeed);
        }
    }

    ct->NumAvailableSkins = 10;
    CarTypeInfoSkinSeed = 0;
    v = cartypeinfo_get_random_skin(ct);
    printf("zeroseed %d seed %u\n", v, CarTypeInfoSkinSeed);
    CarTypeInfoSkinSeed = 0xffffffffu;
    v = cartypeinfo_get_random_skin(ct);
    printf("maxseed %d seed %u\n", v, CarTypeInfoSkinSeed);

    free(ct);
}

// ------------------------------------------------------------- array index

static void scenario_array(void)
{
    printf("[array]\n");

    CarTypeInfo *arr = calloc(8, sizeof(CarTypeInfo));
    for (int i = 0; i < 8; i++) arr[i].Type = 1000 + i;
    CarTypeInfoArray = arr;

    for (int i = 0; i < 8; i++) {
        const CarTypeInfo *p = cartypeinfo_get(i);
        printf("get %d type %d index %td\n", i, p->Type,
               (ptrdiff_t)(p - arr));
    }

    CarTypeInfoArray = NULL;
    free(arr);
}

int main(void)
{
    scenario_layout();
    scenario_strings();
    scenario_skins();
    scenario_array();
    return 0;
}
