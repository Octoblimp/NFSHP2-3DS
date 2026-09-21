// cartypeinfo -- CarTypeInfo (0x0017ff38 .. 0x00180500) and the Info
// structs nested inside it.
//
// CarTypeInfo is the car type's data record: 1376 bytes of tuning and
// presentation loaded from the car data, one per car in the game, shared
// by every instance of that car. Nothing here simulates anything. Its
// value to the rest of task 25 is the *layout* -- Wheel, Suspension,
// Engine, DriveTrain, the tyre model and Car all index into it -- so this
// header is mostly a map, and the seven functions are a thin edge.
//
// The prefix CarState already uses (CenterOfGravity at 272, Wheels at 288)
// is re-declared here in full and agrees with carstate.h to the byte.
//
// One field is NOT in the .mdebug dump: a pointer at byte 1368, between
// DefaultSkinNumber and Pad1, which the six string accessors dereference.
// It points at a CarSpecs record of translated-string ids. The dump omits
// it because it is a private member the STABS entry for CarTypeInfo does
// not carry; it was recovered from `lw v0,1368(a0)` in all six.
//
// The nested Info structs split three ways. The ones the physics reads are
// spelled out (WheelInfo, TireInfo, SuspensionInfo, DriveTrainInfo,
// RigidBodyInfo, AeroInfo, ControlInfo; EngineInfo lives in engine.h). The
// ones belonging to later tasks -- sound, camera, HUD -- are carried as
// sized opaque blocks so the offsets after them stay right. Nothing is
// guessed: every block's size comes from the dump.
//
// See docs/formats/car-type-info.md.

#ifndef CARTYPEINFO_H
#define CARTYPEINFO_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "bmatrix.h"
#include "engine.h"
#include "langtab.h"

// -------------------------------------------------------- nested records

// 32 bytes. Position is three bare floats, not a bVector3 -- there is no
// pad, which is why Radius lands at 12. carstate.h says the same.
typedef struct WheelInfo {
    float   PositionX;   //  0
    float   PositionY;   //  4
    float   PositionZ;   //  8
    float   Radius;      // 12
    float   Width;       // 16
    int32_t WheelNumber; // 20
    float   Padding[2];  // 24
} WheelInfo;

// 32 bytes. Two of these in CarTypeInfo -- front and rear.
typedef struct TireInfo {
    float MaxSlipAngle;               //  0
    float MaxLoad;                    //  4
    float ForceScale;                 //  8
    float StaticFrictionCoefficient;  // 12
    float DynamicFrictionCoefficient; // 16
    float dummy[3];                   // 20
} TireInfo;

// 32 bytes. Two of these -- front and rear. Damping and BumpStop are
// two-element arrays; Suspension::GetDamping picks [1] when the
// suspension velocity is <= 0 and [0] when it is positive.
typedef struct SuspensionInfo {
    float Progression;             //  0
    float Stiffness;               //  4
    float Damping[2];              //  8
    float SwayBarStiffness;        // 16
    float BumpStop[2];             // 20
    float MaxRenderingCompression; // 28
} SuspensionInfo;

// 64 bytes.
typedef struct DriveTrainInfo {
    float   ShiftUpPoint;    //  0
    float   ShiftDownRPM;    //  4
    float   FinalDrive[2];   //  8
    float   TorqueSplit;     // 16
    float   ClutchStiffness; // 20
    int32_t NumGears;        // 24
    float   ShiftSpeed;      // 28
    float   GearRatios[8];   // 32
} DriveTrainInfo;

// 80 bytes. CarTypeInfo calls its copy `Body`.
typedef struct RigidBodyInfo {
    float    Mass;          //  0
    float    Xdim;          //  4
    float    Ydim;          //  8
    float    Zdim;          // 12
    bMatrix4 InertiaTensor; // 16
} RigidBodyInfo;

// 16 bytes.
typedef struct AeroInfo {
    float Drag;                 //  0
    float FrontDownforce;       //  4
    float RearDownforce;        //  8
    float AutoBalanceDownforce; // 12
} AeroInfo;

// 48 bytes.
typedef struct ControlInfo {
    float Steering;             //  0
    float Brake;                //  4
    float EBrake;               //  8
    float BrakeBias;            // 12
    float YawControl;           // 16
    float YawControlNFS;        // 20
    float MaxZMomentAcc;        // 24
    float MaxZMomentAccExtreme; // 28
    float SpeedLimiter;         // 32
    float dummy[3];             // 36
} ControlInfo;

// The record at CarTypeInfo+1368. Five translated-string ids; the field at
// 0 is not read by any of the six accessors and is left unnamed.
typedef struct CarSpecs {
    int32_t _unknown0; //  0
    int32_t ZeroTo60;  //  4
    int32_t TopSpeed;  //  8
    int32_t BHP;       // 12
    int32_t FullName;  // 16
    int32_t ShortName; // 20
} CarSpecs;

// ------------------------------------------------------------ the record

typedef struct CarTypeInfo {
    char            CarTypeName[32];                     //    0
    char            BaseModelName[32];                   //   32
    char            GeometryFilename[32];                //   64
    char            CompressedGeometryFilename[32];      //   96
    char            DashGeometryFilename[32];            //  128
    char            CompressedDashGeometryFilename[32];  //  160
    char            ManufacturerName[16];                //  192
    bVector3        HeadlightPosition;                   //  208
    float           HeadlightFOV;                        //  224
    int32_t         HighPerformance;                     //  228
    int32_t         NumAvailableSkins;                   //  232
    int32_t         CarClass;                            //  236
    bVector3        DriverRenderingOffset;               //  240
    bVector3        InCarSteeringWheelRenderingOffset;   //  256
    bVector3        CenterOfGravity;                     //  272
    WheelInfo       Wheels[4];                           //  288
    TireInfo        Tires[2];                            //  416
    RigidBodyInfo   Body;                                //  480
    SuspensionInfo  Suspension[2];                       //  560
    DriveTrainInfo  DriveTrain;                          //  624
    EngineInfo      Engine;                              //  688
    AeroInfo        Aero;                                //  752
    ControlInfo     Control;                             //  768
    uint8_t         Sound[144];                          //  816  task 29
    uint8_t         Camera[272];                         //  960  task 27
    uint8_t         HudInfo[80];                         // 1232  task 21
    uint8_t         LocationProb[20];                    // 1312
    int32_t         Type;                                // 1332
    int32_t         UsageType;                           // 1336
    int32_t         InitialLockStatus;                   // 1340
    int32_t         BeACopLockStatus;                    // 1344
    int8_t          AvailableSkins[10];                  // 1348
    uint8_t         Dummy[6];                            // 1358
    int32_t         DefaultSkinNumber;                   // 1364
    const CarSpecs *pCarSpecs;                           // 1368
    int32_t         Pad1;                                // 1372
} CarTypeInfo;

// One pointer, and it is the last field but one, so the widening is a
// single term -- unlike Engine, this one does fit the CARSTATE_SLACK
// shape. pCarSpecs also forces the whole struct to 8-byte alignment on a
// 64-bit host, so the tail pads out; sizeof is checked with that in mind.
#define CARTYPEINFO_SLACK ((size_t)(sizeof(void *) - 4))

#ifndef CARTYPEINFO_NO_ASSERT
typedef char cartypeinfo_layout_check[
    (offsetof(CarTypeInfo, ManufacturerName)  ==  192
     && offsetof(CarTypeInfo, HeadlightPosition)  == 208
     && offsetof(CarTypeInfo, HeadlightFOV)       == 224
     && offsetof(CarTypeInfo, NumAvailableSkins)  == 232
     && offsetof(CarTypeInfo, CenterOfGravity)    == 272
     && offsetof(CarTypeInfo, Wheels)             == 288
     && offsetof(CarTypeInfo, Tires)              == 416
     && offsetof(CarTypeInfo, Body)               == 480
     && offsetof(CarTypeInfo, Suspension)         == 560
     && offsetof(CarTypeInfo, DriveTrain)         == 624
     && offsetof(CarTypeInfo, Engine)             == 688
     && offsetof(CarTypeInfo, Aero)               == 752
     && offsetof(CarTypeInfo, Control)            == 768
     && offsetof(CarTypeInfo, Sound)              == 816
     && offsetof(CarTypeInfo, Camera)             == 960
     && offsetof(CarTypeInfo, HudInfo)            == 1232
     && offsetof(CarTypeInfo, LocationProb)       == 1312
     && offsetof(CarTypeInfo, Type)               == 1332
     && offsetof(CarTypeInfo, AvailableSkins)     == 1348
     && offsetof(CarTypeInfo, DefaultSkinNumber)  == 1364
     && offsetof(CarTypeInfo, pCarSpecs)          == 1368
     && sizeof(WheelInfo) == 32 && sizeof(TireInfo) == 32
     && sizeof(SuspensionInfo) == 32 && sizeof(DriveTrainInfo) == 64
     && sizeof(RigidBodyInfo) == 80 && sizeof(AeroInfo) == 16
     && sizeof(ControlInfo) == 48 && sizeof(CarSpecs) == 24
     ) ? 1 : -1];
#endif

// The six string accessors, 0x0017ff38 .. 0x0017fff8. Five of them read an
// id out of pCarSpecs and hand it to the translated-string table;
// GetManufacturerName instead passes the *string* at byte 192 to the
// by-name overload, so it is the only one that does not touch pCarSpecs.
//
// The port takes the table as an argument rather than reaching for a
// global, so the cross-checker can drive it. GetTranslatedString(int) is
// 0x0020b0e0 and maps to langtab_get(); GetTranslatedString(const char *)
// is 0x0020b090 and maps to langtab_get_english().
// langtab_get returns a pointer into the pool that is NOT NUL-terminated,
// so the length comes back separately; these pass that straight through
// rather than copying. outLen may not be NULL.
const char *cartypeinfo_get_full_name(const CarTypeInfo *ct,
                                      const LangTable *t,
                                      size_t *outLen);
const char *cartypeinfo_get_short_name(const CarTypeInfo *ct,
                                       const LangTable *t,
                                       size_t *outLen);
const char *cartypeinfo_get_car_spec_0_to_60(const CarTypeInfo *ct,
                                             const LangTable *t,
                                             size_t *outLen);
const char *cartypeinfo_get_car_spec_top_speed(const CarTypeInfo *ct,
                                               const LangTable *t,
                                               size_t *outLen);
const char *cartypeinfo_get_car_spec_bhp(const CarTypeInfo *ct,
                                         const LangTable *t,
                                         size_t *outLen);

// The odd one out. It does not touch pCarSpecs: it hands the *string* at
// byte 192 to the by-name overload (0x0020b090), which in the port means
// hashing it with bStringHash and going through langtab_get_english. That
// overload's caveat applies -- see langtab.h.
const char *cartypeinfo_get_manufacturer_name(const CarTypeInfo *ct,
                                              const LangTable *t,
                                              size_t *outLen);

// 0x001804c0. Returns 0 when there are no skins -- note that is the
// *return register cleared before the branch*, not AvailableSkins[0]. With
// skins it is AvailableSkins[bRandomI(NumAvailableSkins, &seed)], read as
// a signed byte. The seed is the image's global at gp-15456.
extern uint32_t CarTypeInfoSkinSeed;

int32_t cartypeinfo_get_random_skin(const CarTypeInfo *ct);

// 0x001801c0, a free function rather than a method:
//
//     addiu v1,zero,1376 ; lw v0,-21184(gp) ; mult a0,a0,v1 ; addu v0,v0,a0
//
// so it is `CarTypeInfoArray[type]` with the stride written out as an
// immediate. That immediate is the best evidence in the image that the
// record is 1376 bytes: the compiler emitted sizeof(CarTypeInfo) as a
// literal, independently of the .mdebug dump the layout above came from,
// and the two agree.
//
// There is no bounds check. The array is the global at 0x00323930.
extern const CarTypeInfo *CarTypeInfoArray;

const CarTypeInfo *cartypeinfo_get(int32_t carType);

// CarTypeInfoIterator::Reset (0x001810c8) is `sw zero,8(a0)` and nothing
// else; the rest of that class is header-inline and was folded into its
// callers, so there is no layout to recover and one field to zero. Not
// ported -- it would be a guess wearing a function's name.

#endif
