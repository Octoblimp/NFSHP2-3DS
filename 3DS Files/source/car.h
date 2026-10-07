// car -- Car.obj (0x0012f150 .. 0x00134f6c), plus six methods the compiler
// emitted elsewhere.
//
// Car is the hub of task 25, not its physics. Eighty methods, 22876 bytes,
// and a 2016-byte record -- but thirty-four of those methods make no call
// outside the class at all, and ten of those thirty-four do nothing but
// dispatch through a driver, controller or mover vtable. The simulation
// itself lives in the movers: PhysicsCar,
// MellowMover, BeltMover and the rest, which `SetMovementMode` constructs.
// Car owns the state they write into, the lights, the horn, the wipers, the
// blown tyres and the blinking, and it hands everything else off.
//
// **Car has no vtable.** Its one base is `bTNode<Car>` at offset 0, eight
// bytes of intrusive list link. The `__pure_virtual` the map shows against
// Car.obj belongs to the CarDriver / CarMover / CarController abstract bases
// that share the object file, not to Car.
//
// The layout below is the .mdebug one (`Car (size=2016)`), and every offset
// in it was re-derived from a load or a store in the listing before it was
// written down. See docs/formats/car.md for which instruction confirmed
// which field. Two things are retail's: TheTopologyCoordinate is retail's
// 704 bytes, not the demo's 560, so every field after it is 144 bytes on
// from its demo offset; and retail's four new fields follow the record,
// from 2160, which makes the port's record 2192 bytes (see the record's
// end).
//
// Two things to know before reading the code:
//
//   * Almost every field the game touches is inside `State`, the embedded
//     CarState at offset 64. `GetWheelTraction` reads 916 and 928 off `this`
//     and those are State+852 and State+864, not Car fields. The listing
//     reads through Car; this header reads through State, and the two agree
//     because the offset is fixed.
//
//   * Three embedded records are wider on a 64-bit host than on the console,
//     and they do not widen by the same amount: CarState by two pointers,
//     TopologyCoordinate by a hundred and sixty-two. The asserts at the
//     bottom carry each field's own count. On ARM every slack term is zero
//     and the offsets are the console's exactly.

#ifndef CAR_H
#define CAR_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "carcontroller.h"
#include "carstate.h"
#include "collisionbody.h"
#include "graph.h"
#include "table.h"
#include "topology.h"
#include "trackpath.h"
#include "trackroute.h"

// CarTypeInfo and CarDriver are held by pointer only, so they are named
// rather than included -- and that is not a style choice. `cardriver.h`
// includes `drivetarget.h`, which includes this file, so including
// `cardriver.h` from here closes a cycle: compiling cardriver.c would
// reach `struct Car` with CarDriver's own guard already set and its
// definition not yet reached, and `CarDriver *pCarDriver` would have no
// type. Anything needing the complete records includes their headers
// itself -- car.c does, for `pCarDriver->Steering`.
//
// drivetarget.h is the other end of that cycle and includes this file
// outright. It used to carry a stand-in Car of its own -- the three fields
// the DriveTarget slice read -- and while it did, which of the two headers
// came first decided which Car a translation unit got. Nothing depends on
// order now.
typedef struct Car         Car;
typedef struct CarTypeInfo CarTypeInfo;
typedef struct CarDriver   CarDriver;

// ------------------------------------------------------------ the strangers

// Everything Car only ever holds a pointer to. None of these is task 25's:
// they belong to the replay system, the cop manager, the effect system, the
// render path and the sound mix, which are tasks 26, 27 and 29.
// CarController and CarCollisionBody are not here: Car dispatches through
// both vptrs and reads two of the body's fields, so the records are
// carcontroller.h's and collisionbody.h's, included above.
typedef struct Player            Player;
typedef struct RacingCar         RacingCar;
typedef struct CarMover          CarMover;
typedef struct CarRenderInfo     CarRenderInfo;
typedef struct AnimatedDriver    AnimatedDriver;
typedef struct CarDamage         CarDamage;
typedef struct BaseCarSound      BaseCarSound;
typedef struct tCopManager       tCopManager;

// ------------------------------------------------------------- small records

// 8RideInfo, 8 bytes. Which car, which skin, and two flags the render path
// reads. Held by value inside DriverInfo and by pointer from Car.
typedef struct RideInfo {
    int32_t Type;                 // 0   5CarType
    int8_t  InstanceIndex;        // 4
    int8_t  SkinNumber;           // 5
    int8_t  HasDash;              // 6
    int8_t  CanBeVertexDamaged;   // 7
} RideInfo;                       // 8

// 14DriverTypeEnum. Only TRAFFIC_CAR is tested inside Car, by
// ShouldVisualEffectsBeGenerated, which returns false for it.
typedef int32_t DriverType;

#define DRIVER_TYPE_NONE        ((DriverType)0)
#define DRIVER_TYPE_PLAYER      ((DriverType)1)
#define DRIVER_TYPE_AI_RACER    ((DriverType)2)
#define DRIVER_TYPE_TRAFFIC_CAR ((DriverType)3)
#define DRIVER_TYPE_COP         ((DriverType)4)
#define DRIVER_TYPE_SUPER_COP   ((DriverType)5)

typedef struct CharacterInfo CharacterInfo;

// 10DriverInfo, the demo's 20 bytes and retail's 24. Car holds one by
// pointer and reads DriverType out of it; the rest belongs to the front end.
//
// Retail put a byte in front of the record, so its fields are one byte on
// up to StartingPosition (4) and four bytes on from TheDriverType (8). The
// port keeps the demo's offsets, which the demo checkers read, and puts
// retail's byte at the end, as car.h does Car's new fields.
//
// EliminatedRank is that byte: 0 for a driver still in the event, else the
// rank a knockout round put the driver out at. Retail's DriverInfo
// constructor (0x00188610) zeroes it, and only RaceParameters' new
// 0x001edbc8 sets it, from EventKoState::GetRank as SetupCarsForRace builds
// the next round. RaceCoordinator::InitForRace and InitCars skip a driver
// whose rank is above 0.
typedef struct DriverInfo {
    int8_t         UniqueDriverNumber;  // 0   retail 1
    int8_t         CharacterNumber;     // 1   retail 2
    int8_t         SkillLevel;          // 2   retail 3
    int8_t         StartingPosition;    // 3   retail 4
    DriverType     TheDriverType;       // 4   retail 8
    RideInfo       CurrentRideInfo;     // 8   retail 12
    CharacterInfo *pCharacterInfo;      // 16  retail 20
    int8_t         EliminatedRank;      // 20  retail 0
} DriverInfo;                           // 24

// 25OverrideRenderingPosition, 96 bytes, embedded in Car at 1184. A place
// to put the car for the camera that is not where the simulation has it --
// the front end's car selector drives it, and three bit masks say in which
// views the override, the visibility and the blinking apply.
typedef struct OverrideRenderingPosition {
    bMatrix4 BodyMatrix;        // 0
    bVector3 GeometryPosition;  // 64
    uint32_t OverrideViewBits;  // 80
    uint32_t VisibleViewBits;   // 84
    uint32_t BlinkingViewBits;  // 88
    uint32_t _pad92;            // 92  quadword round-up, never read
} OverrideRenderingPosition;    // 96

#ifndef CAR_NO_ASSERT
typedef char orp_layout_check[
    (offsetof(OverrideRenderingPosition, BodyMatrix)       == 0
     && offsetof(OverrideRenderingPosition, GeometryPosition) == 64
     && offsetof(OverrideRenderingPosition, OverrideViewBits) == 80
     && offsetof(OverrideRenderingPosition, VisibleViewBits)  == 84
     && offsetof(OverrideRenderingPosition, BlinkingViewBits) == 88
     && sizeof(OverrideRenderingPosition) == 96) ? 1 : -1];
#endif

// -------------------------------------------------------------- the enums

// 11ControlMode, at Car+32. Who is steering.
typedef int32_t ControlMode;

#define eNO_CONTROL     ((ControlMode)0)
#define REAL_CONTROL    ((ControlMode)1)
#define AI_CONTROL      ((ControlMode)2)
#define TRAFFIC_CONTROL ((ControlMode)3)
#define COP_CONTROL     ((ControlMode)4)

// 12MovementMode, at Car+36. Which mover integrates the car. Only
// PHYSICS_MOVEMENT runs the real simulation; the other five are the cheap
// movers the game uses for traffic, cops, delivery and the front end.
typedef int32_t MovementMode;

#define eNO_MOVEMENT       ((MovementMode)0)
#define PHYSICS_MOVEMENT   ((MovementMode)1)
#define TRAFFIC_MOVEMENT   ((MovementMode)2)
#define DELIVERY_MOVEMENT  ((MovementMode)3)
#define MELLOW_MOVEMENT    ((MovementMode)4)
#define COP_MOVEMENT       ((MovementMode)5)
#define BELT_MOVEMENT      ((MovementMode)6)

// 20SignalLightStateEnum, at Car+2028 (the demo's 1884).
typedef int32_t SignalLightStateEnum;

#define SIGNAL_LIGHT_ALL_OFF  ((SignalLightStateEnum)0)
#define SIGNAL_LIGHT_LEFT_ON  ((SignalLightStateEnum)1)
#define SIGNAL_LIGHT_RIGHT_ON ((SignalLightStateEnum)2)
#define SIGNAL_LIGHT_ALL_ON   ((SignalLightStateEnum)3)

// 9SirenMode, at Car+2068 (the demo's 1924). The three middle names are
// the image's own: the .mdebug really does spell them SIREN_MODE_01, _02
// and _03.
typedef int32_t SirenMode;

#define SIREN_MODE_NONE   ((SirenMode)0)
#define SIREN_MODE_01     ((SirenMode)1)
#define SIREN_MODE_02     ((SirenMode)2)
#define SIREN_MODE_03     ((SirenMode)3)
#define SIREN_MODE_BROKEN ((SirenMode)4)

// --------------------------------------------------------------- the record

// bTNode<Car>, the intrusive link Race's car list is built from. It is Car's
// only base and it sits at offset 0, so a Car's first two words are its
// links -- the same shape bslotpool.h spells out for bTNode<SlotPool>.
typedef struct CarNode {
    struct CarNode *next;  // 0
    struct CarNode *prev;  // 4
} CarNode;                 // 8

// Spelled `struct Car { ... }` rather than the usual
// `typedef struct Car { ... } Car;` because the typedef is already up with
// the other forward names, and repeating it would be a duplicate typedef --
// legal from C11 on, but not something a layout header needs to depend on.
struct Car {
    CarNode           Link;                     // 0    bTNode<Car>
    int16_t           CarIndex;                 // 8
    int16_t           DriverNumber;             // 10
    CarTypeInfo      *pCarTypeInfo;             // 12
    RideInfo         *pRideInfo;                // 16
    DriverInfo       *MyDriver;                 // 20
    Player           *pPlayer;                  // 24
    RacingCar        *pRacingCar;               // 28
    ControlMode       TheControlMode;           // 32
    MovementMode      TheMovementMode;          // 36
    CarController    *pCarController;           // 40
    CarDriver        *pCarDriver;               // 44
    CarMover         *pCarMover;                // 48
    CarCollisionBody *pDynamicCollisionBody;    // 52
    uint8_t           _hole56[8];               // 56   to align State

    CarState          State;                    // 64   1024 bytes

    Gear              DispGear;                 // 1088
    float             FrictionBoost;            // 1092
    float             DraftFactor;              // 1096
    float             fTractionBoostOverride;   // 1100
    float             fDamageBoostOverride;     // 1104
    uint8_t           _hole1108[12];            // 1108 to align vOldVel

    bVector3          vOldVel;                  // 1120
    bVector3          vOldAngVel;               // 1136
    float             OldSpeed;                 // 1152
    float             AirTimeSwitch;            // 1156
    int8_t            RenderingEnabled;         // 1160
    uint8_t           _hole1161[3];             // 1161
    int32_t           DriverRenderingEnabled;   // 1164
    CarRenderInfo    *pRenderInfo;              // 1168
    AnimatedDriver   *pAnimatedDriver;          // 1172
    uint8_t           _hole1176[8];             // 1176 to align the override

    OverrideRenderingPosition TheOverrideRenderingPosition; // 1184
    TopologyCoordinate        TheTopologyCoordinate;        // 1280
    TrackPathCoordinate       TheTrackPathCoordinate;       // 1984

    int8_t            CopLights;                // 2024
    uint8_t           _hole2025[3];             // 2025
    SignalLightStateEnum SignalLightState;      // 2028
    int32_t           NitroEffectFlag;          // 2032
    int32_t           WantToBlinkHeadlights;    // 2036
    int32_t           WantToHonkHorn;           // 2040
    int32_t           WantTwoHonksAndOrBlinks;  // 2044
    int32_t           HeadlightsAndHornStartTime;   // 2048
    float             HeadlightsAndHornOnDuration;  // 2052
    float             HeadlightsAndHornOffDuration; // 2056
    int32_t           ForceHeadlightsOn;        // 2060
    int32_t           HeadlightsState;          // 2064
    SirenMode         TheSirenMode;             // 2068
    uint32_t          WiperOnTime;              // 2072
    uint32_t          WiperOffTime;             // 2076
    int32_t           WiperState;               // 2080
    CarDamage        *pCarDamage;               // 2084
    uint8_t           BlownTireBits;            // 2088
    uint8_t           NumBlownTires;            // 2089
    uint8_t           _hole2090[2];             // 2090
    float             fBlownTireControllerRumbleTimer; // 2092
    BaseCarSound     *pBaseCarSound;            // 2096
    int32_t           ResetMe;                  // 2100
    int32_t           BlinkTimer;               // 2104
    float             BlinkDuration;            // 2108
    bVector2          LastInTroughPosition;     // 2112
    int32_t           bPoofed;                  // 2120
    int32_t           bVisibleOnTrackMap;       // 2124
    uint8_t           NumTimesSkidding[4];      // 2128, a count a wheel
    uint8_t           RoadBumpBits;             // 2132
    uint8_t           _hole2133[3];             // 2133
    void             *pCaffeineObj;             // 2136
    void             *pLastCarTrailObj;         // 2140
    int32_t           LeaveCarTrails;           // 2144
    int32_t           ForceBuzzTime;            // 2148
    float             fAngleToCamera;           // 2152
    uint32_t          _pad2156;                 // 2156 quadword round-up

    // Retail's four new fields, which retail put among the ones above
    // (its Car is 2200 bytes). They go at the end here so that every
    // demo offset above still holds, but for the 144 bytes retail's
    // TopologyCoordinate adds, and the demo image's checkers still run.
    // Retail's offsets are in the comments. The names are the port's,
    // since retail has no symbols.
    //
    //   vOldPos: the position BeginMovement saves beside vOldVel and
    //   vOldAngVel, and FinishMovement reads.
    //   HeadlightsAndHornSecondOnDuration: the second flash or honk of a
    //   pair. The demo reused the first's duration for it.
    //   JustResetFrames: 2 after a ResetToRoutePoint that asks for it,
    //   counted down by Drive. tPursuit::IsChasedCarStoppable reads it.
    //   InDeepWaterRegistered: set once TriggerCarTerrainEffects has
    //   registered "InDeepWater" with the replay, and cleared when the car
    //   leaves deep water.
    bVector3          vOldPos;                  // 2160 retail 1136
    float             HeadlightsAndHornSecondOnDuration; // 2176 retail 2088
    int32_t           JustResetFrames;          // 2180 retail 2140
    int32_t           InDeepWaterRegistered;    // 2184 retail 2196
    uint32_t          _pad2188;                 // 2188 quadword round-up
};                                              // 2192

// ---------------------------------------------------------------- the asserts
//
// Each field's slack term is the number of four-byte-to-pointer widenings
// that happen at or before it, and they do not run uniformly: fourteen
// pointers and one alignment gap before State, then CarState's own two,
// then TopologyCoordinate's hundred and sixty-two (161 pointers and the
// round-up after the last), then five more.
//
// The gap is worth naming. `CarIndex` and `DriverNumber` leave `pCarTypeInfo`
// at 12, which a 64-bit host must round up to 16 -- four bytes the console
// does not spend. That is the same width as one widened pointer, which is
// why every offset past it reads as one extra slack unit without there being
// an extra pointer. On ARM the term is zero and the coincidence never
// arises.
#define CAR_SLACK ((size_t)(sizeof(void *) - 4))
#define CAR_AT(f, n, k) (offsetof(Car, f) == (size_t)(n) + (k) * CAR_SLACK)

#ifndef CAR_NO_ASSERT
typedef char car_layout_check[
    (CAR_AT(Link, 0, 0)
     && CAR_AT(CarIndex, 8, 2)
     && CAR_AT(DriverNumber, 10, 2)
     && CAR_AT(pCarTypeInfo, 12, 3)
     && CAR_AT(pRideInfo, 16, 4)
     && CAR_AT(MyDriver, 20, 5)
     && CAR_AT(pPlayer, 24, 6)
     && CAR_AT(pRacingCar, 28, 7)
     && CAR_AT(TheControlMode, 32, 8)
     && CAR_AT(TheMovementMode, 36, 8)
     && CAR_AT(pCarController, 40, 8)
     && CAR_AT(pCarDriver, 44, 9)
     && CAR_AT(pCarMover, 48, 10)
     && CAR_AT(pDynamicCollisionBody, 52, 11)
     && CAR_AT(_hole56, 56, 12)
     && CAR_AT(State, 64, 12)
     && CAR_AT(DispGear, 1088, 14)
     && CAR_AT(FrictionBoost, 1092, 14)
     && CAR_AT(DraftFactor, 1096, 14)
     && CAR_AT(fTractionBoostOverride, 1100, 14)
     && CAR_AT(fDamageBoostOverride, 1104, 14)
     && CAR_AT(vOldVel, 1120, 14)
     && CAR_AT(vOldAngVel, 1136, 14)
     && CAR_AT(OldSpeed, 1152, 14)
     && CAR_AT(AirTimeSwitch, 1156, 14)
     && CAR_AT(RenderingEnabled, 1160, 14)
     && CAR_AT(DriverRenderingEnabled, 1164, 14)
     && CAR_AT(pRenderInfo, 1168, 14)
     && CAR_AT(pAnimatedDriver, 1172, 15)
     && CAR_AT(TheOverrideRenderingPosition, 1184, 16)
     && CAR_AT(TheTopologyCoordinate, 1280, 16)
     && CAR_AT(TheTrackPathCoordinate, 1984, 178)
     && CAR_AT(CopLights, 2024, 182)
     && CAR_AT(SignalLightState, 2028, 182)
     && CAR_AT(NitroEffectFlag, 2032, 182)
     && CAR_AT(WantToBlinkHeadlights, 2036, 182)
     && CAR_AT(WantToHonkHorn, 2040, 182)
     && CAR_AT(WantTwoHonksAndOrBlinks, 2044, 182)
     && CAR_AT(HeadlightsAndHornStartTime, 2048, 182)
     && CAR_AT(HeadlightsAndHornOnDuration, 2052, 182)
     && CAR_AT(HeadlightsAndHornOffDuration, 2056, 182)
     && CAR_AT(ForceHeadlightsOn, 2060, 182)
     && CAR_AT(HeadlightsState, 2064, 182)
     && CAR_AT(TheSirenMode, 2068, 182)
     && CAR_AT(WiperOnTime, 2072, 182)
     && CAR_AT(WiperOffTime, 2076, 182)
     && CAR_AT(WiperState, 2080, 182)
     && CAR_AT(pCarDamage, 2084, 183)
     && CAR_AT(BlownTireBits, 2088, 184)
     && CAR_AT(NumBlownTires, 2089, 184)
     && CAR_AT(fBlownTireControllerRumbleTimer, 2092, 184)
     && CAR_AT(pBaseCarSound, 2096, 184)
     && CAR_AT(ResetMe, 2100, 185)
     && CAR_AT(BlinkTimer, 2104, 185)
     && CAR_AT(BlinkDuration, 2108, 185)
     && CAR_AT(LastInTroughPosition, 2112, 185)
     && CAR_AT(bPoofed, 2120, 185)
     && CAR_AT(bVisibleOnTrackMap, 2124, 185)
     && CAR_AT(NumTimesSkidding, 2128, 185)
     && CAR_AT(RoadBumpBits, 2132, 185)
     && CAR_AT(pCaffeineObj, 2136, 186)
     && CAR_AT(pLastCarTrailObj, 2140, 187)
     && CAR_AT(LeaveCarTrails, 2144, 188)
     && CAR_AT(ForceBuzzTime, 2148, 188)
     && CAR_AT(fAngleToCamera, 2152, 188)
     && CAR_AT(_hole1108, 1108, 14)
     && CAR_AT(_hole1161, 1161, 14)
     && CAR_AT(_hole1176, 1176, 16)
     && CAR_AT(_hole2025, 2025, 182)
     && CAR_AT(_hole2090, 2090, 184)
     && CAR_AT(_hole2133, 2133, 185)
     && CAR_AT(_pad2156, 2156, 188)
     && CAR_AT(vOldPos, 2160, 188)
     && CAR_AT(HeadlightsAndHornSecondOnDuration, 2176, 188)
     && CAR_AT(JustResetFrames, 2180, 188)
     && CAR_AT(InDeepWaterRegistered, 2184, 188)
     && CAR_AT(_pad2188, 2188, 188)

     // The holes are asserted by size as well as by offset, and that
     // is not redundant. On this 64-bit host CarState is eight-byte
     // aligned, so shortening _hole56 to four bytes moves nothing --
     // the compiler pads the gap straight back and every offset above
     // still holds. On ARM the alignment is four and the same edit
     // would slide the whole record. Asserting the width makes the
     // host build say so too.
     && sizeof(((Car *)0)->_hole56) == 8
     && sizeof(((Car *)0)->_hole1108) == 12
     && sizeof(((Car *)0)->_hole1161) == 3
     && sizeof(((Car *)0)->_hole1176) == 8
     && sizeof(((Car *)0)->_hole2025) == 3
     && sizeof(((Car *)0)->_hole2090) == 2
     && sizeof(((Car *)0)->_hole2133) == 3

     && sizeof(Car) == (size_t)2192 + 188 * CAR_SLACK
     && sizeof(CarState) == 1024 + CARSTATE_SLACK
     && sizeof(TopologyCoordinate) == TOPOLOGY_SIZEOF
     && sizeof(CarNode) == 2 * sizeof(void *)
     && sizeof(DriverInfo) == 24 + 2 * CAR_SLACK
     && sizeof(RideInfo) == 8) ? 1 : -1];
#endif

// -------------------------------------------------------------- the globals
//
// What `_GLOBAL_$I$fDraftFalloff` (0x001347c0) builds, named as the image
// names them. Five are global in the stabs (`G`) and three file-static
// (`S`: vRoadNoiseSpeedData, ObjectPoints, DamageAboveMatrix); the port
// exports all eight so the transcript can print what the initialiser left
// in them. fDraftFalloff is the one initialised in the image's .data; the
// others are zero until car_static_init runs.
extern const float fDraftFalloff[6];                    // 0x002e84a8
extern bVector2    vDraftSpeedRange[4];                 // 0x002e84c0
extern Table       tDraftFalloff;                       // 0x002e84e0
extern Graph       gDraftSpeedRange;                    // 0x00323000
extern bVector2    vRoadNoiseSpeedData[2];              // 0x00326cf0
extern Graph       gRoadNoiseSpeedScale;                // 0x00323070
extern bVector3    ObjectPoints[13];                    // 0x00326be0
extern bVector4    DamageAboveMatrix[4];                // 0x00326cb0
extern bVector2    PostCollisionYawControlProfileData[4]; // 0x002e8528
extern Graph       PostCollisionYawControlProfile;      // 0x00323078

// A reset car keeps at most this much speed (RealDriver's reset handler).
extern float RollingResetSpeed;                         // 0x00323030

// While set, FinishMovement neither starts the jump cam nor leaves it for
// the after-zone (carfinish.c).
extern int32_t g_DisableAutoReplay;                     // 0x00323040

// ComputeFakeRPM's tweakables, initialised in the image's .sdata, and the
// RPM pairs in its .data. Exported so the transcript can print them and set
// the two debug overrides.
extern float GearRTo1Speed;                             // 0x00323044
extern float Gear1To2Speed;                             // 0x00323048
extern float Gear2To3Speed;                             // 0x0032304c
extern float Gear3To4Speed;                             // 0x00323050
extern float Gear4To5Speed;                             // 0x00323054
extern float Gear5To6Speed;                             // 0x00323058
extern float GearTopSpeed;                              // 0x0032305c
extern float MaxRPMInc;                                 // 0x00323060
extern float MaxSpeedInc;                               // 0x00323064
extern float TestSpeed;                                 // 0x00323068
extern float TestRPM;                                   // 0x003241cc
extern float RPMTable[12];                              // 0x002e84f8

// -------------------------------------------------------------- the methods
//
// car.c's exports. Declared here, where car.c includes them, so that a
// definition drifting from its declaration is a compile error in car.c
// rather than a silent reinterpretation at a call site in another file.

void     car_static_init(void);                          // 0x001347c0

void     car_fake_engine_task(Car *c);                   // 0x00130ff0
void     car_event_handler(Car *c, void *event);         // 0x00131db0
void     car_print_above(Car *c, const char *text, int colour); // 0x00184bc0
void     car_start_blinking(Car *c, float duration);     // 0x00131628
void     car_stop_blinking(Car *c);                      // 0x00131638
int32_t  car_is_blinking(Car *c);                        // 0x00131640
void     car_blink_blink_poof(Car *c);                   // 0x001315f0
int32_t  car_is_poofed(Car *c);                          // 0x001316f8
int32_t  car_calculate_debug_checksum(Car *c);           // 0x00130ee0
float    car_get_wheels_on_ground(Car *c);               // 0x00133128
float    car_get_wheel_traction(Car *c);                 // 0x001330e0
int32_t  car_should_sound_effects_be_generated(Car *c);  // 0x00134188
int32_t  car_should_visual_effects_be_generated(Car *c); // 0x00134130
float    car_get_forward_acceleration(Car *c);           // 0x00133db8
void     car_honk_and_or_blink_headlights(Car *c, float onDuration,
                                          float offDuration, int32_t blink,
                                          int32_t honk, int32_t two);
                                                         // 0x00132508
void     car_turn_wipers_on_for_duration(Car *c, int32_t on, int32_t off);
                                                         // 0x001319c0
void     car_world_to_car(Car *c, bVector2 *out, const bVector2 *in);
                                                         // 0x00138e90
uint16_t car_get_steering(Car *c);                       // 0x00131070

// The draft. The two overloads of CalculateDraftFactor: the one-car form
// is what `other` gives `c`, the no-argument form is the sum over the
// world, capped.
float    car_calculate_draft_factor_from(Car *c, Car *other); // 0x0012ffc8
float    car_calculate_draft_factor(Car *c);             // 0x001300f0

// The dispatchers.
void     car_think(Car *c, float dt);                    // 0x00130180
void     car_drive(Car *c, float dt);                    // 0x001301d0
// Retail's GetRoute and GetRoutePoint hand `find` on to the controller,
// whose AICarController finds where it is first when it has no route; 1
// from every caller but IsFacingWrongWay.
TrackRoute      *car_get_route(Car *c, int find);        // 0x00131740
TrackRoutePoint *car_get_route_point(Car *c, int find);  // 0x00131770
float    car_get_amount_out_of_bounds(Car *c);           // 0x001317a0
void     car_update_sound(Car *c);                       // 0x00133480
int32_t  car_is_collideable(Car *c);                     // 0x001316a0
int32_t  car_is_facing_wrong_way(Car *c);                // 0x001318b8
void     car_update_headlights_and_horn(Car *c);         // 0x00132568

// The borrowed fields, second helping.
void     car_get_car_space_bounding_box(Car *c, bVector3 *min, bVector3 *max);
                                                         // 0x001334c0
Timer    car_get_last_penetration_time(Car *c);          // 0x001334e0
float    car_get_tracked_acceleration(Car *c);           // 0x0012ff40

// Slice three: where the other cars are, the yaw, and the fake engine.
int32_t  car_is_car_to_left(Car *c, Car *other);         // 0x00131ca0
int32_t  car_is_car_to_right(Car *c, Car *other);        // 0x00131ce8
float    car_get_relative_car_position(Car *c, Car *other, float *lateral);
                                                         // 0x00130f10
int32_t  car_is_car_in_front(Car *c, Car *other, uint16_t angle);
                                                         // 0x00131d30
float    car_get_post_collision_yaw_control_boost(Car *c); // 0x001341d0
int32_t  car_is_drifting(Car *c);                        // 0x00134258
float    car_smooth(float cur, float target, float rate); // 0x00134788
void     car_compute_fake_rpm(Car *c);                   // 0x00131080

// Slice four: the modes. carmodes.c, which carmodes.h describes.
void     car_set_control_mode(Car *c, ControlMode mode); // 0x0012fb50
void     car_set_movement_mode(Car *c, MovementMode mode); // 0x0012fd58
void     car_set_to_physics_mode(Car *c, Car *other);    // 0x0012ff68
void     car_set_friction_boost(Car *c, float f);        // 0x0012fd38

// Slice five: on the track. cartrack.c, apart from car.c for the topology.
void     car_find_flat_on_track_position(Car *c, bMatrix4 *m, bVector3 *pos,
                                         uint16_t angle,
                                         TopologyCoordinate *tc);
                                                         // 0x00130c58
void     car_put_flat_on_track(Car *c);                  // 0x00130e90

// Slice six: the reset group. carreset.c, which reaches the modes and the
// ground both.
void     car_reset_core(Car *c, const bVector3 *pos, float speed,
                        uint16_t angle);                 // 0x001312c0
void     car_reset_to_position(Car *c, const bVector3 *pos, float speed,
                               uint16_t angle);          // 0x00131418
void     car_reset_to_route_point(Car *c, TrackRoute *route,
                                  TrackRoutePoint *point, float speed,
                                  int32_t blink, float direction);
                                                         // 0x00131480
void     car_debug_set_position(Car *c, const bVector3 *pos, float speed,
                                uint16_t angle);         // 0x001317d0

// Slice seven: the air under a car and the start of its step. cartrack.c.
float    car_average_air(Car *c, float *time, float *height);
                                                         // 0x00133e48
void     car_begin_movement(Car *c, float dt);           // 0x001303a8

// Slice eight: the step. carmove.c.
float    car_move(Car *c, float dt);                     // 0x00130200
void     car_change_gear(Car *c, Gear gear);             // 0x00130ff8
void     car_calculate_new_catchup_multipliers(Car *c);  // 0x001334f0
void     car_update_position(Car *c, bVector3 *pos);     // 0x00130388

// The three AnimatedDriver methods ChangeGear calls, and the Espresso link
// UpdatePosition calls. AnimatedDriver is the render path's (task 29) and
// Espresso a development tool the port has no side of, so each is a seam
// in carmodes.h's style: NULL is a call the port cannot make yet, and
// reaching it aborts. Nothing sets pAnimatedDriver or pCaffeineObj yet.
//
//   BeginGearChange        0x0019f7a8  QueueAnimation(11)
//   BeginDrivingBackwards  0x0019f7b0  byte 105 set, HandleDrivingBackwards
//   EndDrivingBackwards    0x0019f7d0  byte 105 cleared, ReleaseAnimation(3)
//   espSetObjectPosition   0x00243308  the object and three floats, queued
//                                      for the editor
typedef void (*CarAnimatedDriverFn)(AnimatedDriver *d);
typedef void (*CarEspSetObjectPositionFn)(void *obj, bVector3 *pos);
extern CarAnimatedDriverFn gAnimatedDriverBeginGearChangeFn;
extern CarAnimatedDriverFn gAnimatedDriverBeginDrivingBackwardsFn;
extern CarAnimatedDriverFn gAnimatedDriverEndDrivingBackwardsFn;
extern CarEspSetObjectPositionFn gEspSetObjectPositionFn;

// Slice nine: what the race, the AI and the pursuit ask of a car. carrace.c,
// apart from car.c because DeliverMeFromEvil reaches SetMovementMode and
// FixBlownTires RealDriver.
float    car_get_distance_and_speed(float *speed, Car *a, Car *b);
                                                         // 0x001326b0
void     car_fix_blown_tires(Car *c);                    // 0x00133450
void     car_trigger_tire_blow_out(Car *c, int32_t tires); // 0x00133368
void     car_please_reset_me_later(Car *c);              // 0x00131580
float    car_get_driving_line_speed(Car *c);             // 0x00131700
void     car_deliver_me_from_evil(Car *c, bVector2 *pos, uint16_t angle,
                                  float speed, float time);
                                                         // 0x001326d0

// 9CarEffect (type#1034). TriggerTireBlowOut asks for the blown tire; the
// rest are the render path's, and are here so that its port has them.
typedef int32_t CarEffect;

#define CARFX_NONE                      ((CarEffect)0)
#define CARFX_DRIVE_OVER                ((CarEffect)1)
#define CARFX_DRIVE_OVER2               ((CarEffect)2)
#define CARFX_SKID_SMOKE                ((CarEffect)3)
#define CARFX_TIRE_SPEW                 ((CarEffect)4)
#define CARFX_BOTTOM_OUT                ((CarEffect)5)
#define CARFX_DAM_RADIATOR              ((CarEffect)6)
#define CARFX_DAM_ENGINE                ((CarEffect)7)
#define CARFX_BLOWN_TIRE                ((CarEffect)8)
#define CARFX_DRIVE_ON_FLAT_TIRE        ((CarEffect)9)
#define CARFX_NITRO                     ((CarEffect)10)
#define CARFX_EXHAUST_SMOKE             ((CarEffect)11)
#define CARFX_BREAK_SIDE_MIRROR_LEFT    ((CarEffect)12)
#define CARFX_BREAK_SIDE_MIRROR_RIGHT   ((CarEffect)13)
#define CARFX_BREAK_LICENSE_PLATE_FRONT ((CarEffect)14)
#define CARFX_BREAK_LICENSE_PLATE_RIGHT ((CarEffect)15)
#define CARFX_BREAK_HEADLIGHT_LEFT      ((CarEffect)16)
#define CARFX_BREAK_HEADLIGHT_RIGHT     ((CarEffect)17)
#define CARFX_BREAK_BRAKELIGHT_LEFT     ((CarEffect)18)
#define CARFX_BREAK_BRAKELIGHT_RIGHT    ((CarEffect)19)
#define CARFX_BREAK_WINDSHIELD          ((CarEffect)20)
#define CARFX_BREAK_WINDOW_REAR         ((CarEffect)21)
#define CARFX_BREAK_WINDOW_LEFT_FRONT   ((CarEffect)22)
#define CARFX_BREAK_WINDOW_LEFT_REAR    ((CarEffect)23)
#define CARFX_BREAK_WINDOW_RIGHT_FRONT  ((CarEffect)24)
#define CARFX_BREAK_WINDOW_RIGHT_REAR   ((CarEffect)25)
#define NUM_CARFX                       26

// The five calls slice nine makes out of Car into classes the port does not
// have yet. The three whose answer the car needs, or that move it, abort if
// reached unset, in carmodes.h's style. The effect and the sound only show
// and sound, and a NULL one is skipped, in RealDriver's.
//
//   tCopManager::IsBeingPursued                 0x00213128  task 26, aborts
//   AICarController::GetCurrentDrivingLineSpeed 0x0018ad18  task 26, aborts
//   DeliveryMover::SetDestination               0x001f0ba0  task 26, aborts
//   Car::TriggerEffect                          0x0011e328  task 29, skipped
//   BaseCarSound::TriggerTireBlowOut            0x00185200  task 29, skipped
//
// Car::TriggerEffect is Car's own, but it is not in Car.obj: it sits with
// the effect system's code, and is that port's.
typedef int32_t (*CarCopManagerIsBeingPursuedFn)(tCopManager *m, Car *c);
typedef float   (*CarAIDrivingLineSpeedFn)(CarController *ctl);
typedef void    (*CarDeliveryMoverSetDestinationFn)(CarMover *m, bVector2 *pos,
                                                    uint16_t angle, float speed,
                                                    float time);
typedef void    (*CarTriggerEffectFn)(Car *c, CarEffect effect, float scale,
                                      int32_t where, bVector3 *pos);
typedef void    (*CarBaseCarSoundFn)(BaseCarSound *s);
extern CarCopManagerIsBeingPursuedFn    gCopManagerIsBeingPursuedFn;
extern CarAIDrivingLineSpeedFn          gAICarControllerGetCurrentDrivingLineSpeedFn;
extern CarDeliveryMoverSetDestinationFn gDeliveryMoverSetDestinationFn;
extern CarTriggerEffectFn               gCarTriggerEffectFn;
extern CarBaseCarSoundFn                gBaseCarSoundTriggerTireBlowOutFn;

// Slice ten: the effects the ground under a car makes. careffects.c, apart
// from car.c because it reads the terrain table and the topology. The
// effect goes through slice nine's gCarTriggerEffectFn.
void     car_trigger_car_terrain_effects(Car *c, float distance);
                                                         // 0x00131db8

// BreakableCarItem (the stabs), the item whose damage the terrain effects
// read. Each item has two bits of CarDamage's
// BreakableCarItemDamageAmounts, item i at bit 2i.
#define BREAKABLE_CAR_ITEM_RADIATOR 14

// BaseCarSound::TriggerSplash, 0x00185038, task 29, skipped when NULL. On
// the disc it is 24 bytes: `level` goes to SplashRight (40) if `right`,
// and to SplashLeft (36) if not.
typedef void    (*CarBaseCarSoundSplashFn)(BaseCarSound *s, int32_t right,
                                           int32_t level);
extern CarBaseCarSoundSplashFn          gBaseCarSoundTriggerSplashFn;

// Slice eleven: the end of a car's step. carfinish.c, apart from carmove.c
// because it reaches Collision, the world's car table and the Player.
// World::DoTimestep calls it for every car, through world.h's
// gCarFinishMovementFn, after every car has moved.
void     car_finish_movement(Car *c, float dt);          // 0x00130480

// The four Player methods FinishMovement calls, for the camera zones and
// the jump cam. Player is task 26's. A zone is the camera's, but
// RequestZone also sets the world's time scale or pauses it
// (World::SetTimeScale, SetWorldPaused), and ClearZone puts the scale back
// (ResetTimeScale). So each seam aborts if it is reached unset, in
// carmodes.h's style. Only a car with a Player reaches them, and nothing
// in the port builds a Player yet.
//
//   Player::ClearZone(bool)             0x00171c70  `sound`: ClearZoneSound
//   Player::RequestZone(int, 3 x bool)  0x00171610  answers whether it did
//   Player::IsJumpCamAvailable          0x00170408  builds a PreviewRoute
//   Player::CleanUpJumpCam              0x00170488  deletes it
//
// RequestZone's first bool skips the zone's own timer; FinishMovement
// passes (6, 0, 1, 1) for the jump cam and (7, 0, 0, 1) after it.
typedef void    (*PlayerClearZoneFn)(Player *p, int32_t sound);
typedef int32_t (*PlayerRequestZoneFn)(Player *p, int32_t zone,
                                       int32_t force, int32_t b2,
                                       int32_t b3);
typedef int32_t (*PlayerIsJumpCamAvailableFn)(Player *p);
typedef void    (*PlayerCleanUpJumpCamFn)(Player *p);
extern PlayerClearZoneFn          gPlayerClearZoneFn;
extern PlayerRequestZoneFn        gPlayerRequestZoneFn;
extern PlayerIsJumpCamAvailableFn gPlayerIsJumpCamAvailableFn;
extern PlayerCleanUpJumpCamFn     gPlayerCleanUpJumpCamFn;

// The camera zones FinishMovement names: 6 is the jump cam, 7 the zone it
// asks for when the car has been in the air longer than AirTimeSwitch.
#define PLAYER_ZONE_JUMP_CAM   6
#define PLAYER_ZONE_AFTER_JUMP 7

#endif // CAR_H
