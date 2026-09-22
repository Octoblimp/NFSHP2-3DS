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
// which field.
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
//     TopologyCoordinate by a hundred and twenty-eight. The asserts at the
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

// 10DriverInfo, 20 bytes. Car holds one by pointer and reads DriverType out
// of it; the rest belongs to the front end.
typedef struct DriverInfo {
    int8_t         UniqueDriverNumber;  // 0
    int8_t         CharacterNumber;     // 1
    int8_t         SkillLevel;          // 2
    int8_t         StartingPosition;    // 3
    DriverType     TheDriverType;       // 4
    RideInfo       CurrentRideInfo;     // 8
    CharacterInfo *pCharacterInfo;      // 16
} DriverInfo;                           // 20

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

// 20SignalLightStateEnum, at Car+1884.
typedef int32_t SignalLightStateEnum;

#define SIGNAL_LIGHT_ALL_OFF  ((SignalLightStateEnum)0)
#define SIGNAL_LIGHT_LEFT_ON  ((SignalLightStateEnum)1)
#define SIGNAL_LIGHT_RIGHT_ON ((SignalLightStateEnum)2)
#define SIGNAL_LIGHT_ALL_ON   ((SignalLightStateEnum)3)

// 9SirenMode, at Car+1924. The three middle names are the image's own: the
// .mdebug really does spell them SIREN_MODE_01, _02 and _03.
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
    TrackPathCoordinate       TheTrackPathCoordinate;       // 1840

    int8_t            CopLights;                // 1880
    uint8_t           _hole1881[3];             // 1881
    SignalLightStateEnum SignalLightState;      // 1884
    int32_t           NitroEffectFlag;          // 1888
    int32_t           WantToBlinkHeadlights;    // 1892
    int32_t           WantToHonkHorn;           // 1896
    int32_t           WantTwoHonksAndOrBlinks;  // 1900
    int32_t           HeadlightsAndHornStartTime;   // 1904
    float             HeadlightsAndHornOnDuration;  // 1908
    float             HeadlightsAndHornOffDuration; // 1912
    int32_t           ForceHeadlightsOn;        // 1916
    int32_t           HeadlightsState;          // 1920
    SirenMode         TheSirenMode;             // 1924
    uint32_t          WiperOnTime;              // 1928
    uint32_t          WiperOffTime;             // 1932
    int32_t           WiperState;               // 1936
    CarDamage        *pCarDamage;               // 1940
    uint8_t           BlownTireBits;            // 1944
    uint8_t           NumBlownTires;            // 1945
    uint8_t           _hole1946[2];             // 1946
    float             fBlownTireControllerRumbleTimer; // 1948
    BaseCarSound     *pBaseCarSound;            // 1952
    int32_t           ResetMe;                  // 1956
    int32_t           BlinkTimer;               // 1960
    float             BlinkDuration;            // 1964
    bVector2          LastInTroughPosition;     // 1968
    int32_t           bPoofed;                  // 1976
    int32_t           bVisibleOnTrackMap;       // 1980
    int32_t           NumTimesSkidding;         // 1984
    uint8_t           RoadBumpBits;             // 1988
    uint8_t           _hole1989[3];             // 1989
    void             *pCaffeineObj;             // 1992
    void             *pLastCarTrailObj;         // 1996
    int32_t           LeaveCarTrails;           // 2000
    int32_t           ForceBuzzTime;            // 2004
    float             fAngleToCamera;           // 2008
    uint32_t          _pad2012;                 // 2012 quadword round-up
};                                              // 2016

// ---------------------------------------------------------------- the asserts
//
// Each field's slack term is the number of four-byte-to-pointer widenings
// that happen at or before it, and they do not run uniformly: fourteen
// pointers and one alignment gap before State, then CarState's own two,
// then TopologyCoordinate's hundred and twenty-eight, then five more.
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
     && CAR_AT(TheTrackPathCoordinate, 1840, 144)
     && CAR_AT(CopLights, 1880, 148)
     && CAR_AT(SignalLightState, 1884, 148)
     && CAR_AT(NitroEffectFlag, 1888, 148)
     && CAR_AT(WantToBlinkHeadlights, 1892, 148)
     && CAR_AT(WantToHonkHorn, 1896, 148)
     && CAR_AT(WantTwoHonksAndOrBlinks, 1900, 148)
     && CAR_AT(HeadlightsAndHornStartTime, 1904, 148)
     && CAR_AT(HeadlightsAndHornOnDuration, 1908, 148)
     && CAR_AT(HeadlightsAndHornOffDuration, 1912, 148)
     && CAR_AT(ForceHeadlightsOn, 1916, 148)
     && CAR_AT(HeadlightsState, 1920, 148)
     && CAR_AT(TheSirenMode, 1924, 148)
     && CAR_AT(WiperOnTime, 1928, 148)
     && CAR_AT(WiperOffTime, 1932, 148)
     && CAR_AT(WiperState, 1936, 148)
     && CAR_AT(pCarDamage, 1940, 149)
     && CAR_AT(BlownTireBits, 1944, 150)
     && CAR_AT(NumBlownTires, 1945, 150)
     && CAR_AT(fBlownTireControllerRumbleTimer, 1948, 150)
     && CAR_AT(pBaseCarSound, 1952, 150)
     && CAR_AT(ResetMe, 1956, 151)
     && CAR_AT(BlinkTimer, 1960, 151)
     && CAR_AT(BlinkDuration, 1964, 151)
     && CAR_AT(LastInTroughPosition, 1968, 151)
     && CAR_AT(bPoofed, 1976, 151)
     && CAR_AT(bVisibleOnTrackMap, 1980, 151)
     && CAR_AT(NumTimesSkidding, 1984, 151)
     && CAR_AT(RoadBumpBits, 1988, 151)
     && CAR_AT(pCaffeineObj, 1992, 152)
     && CAR_AT(pLastCarTrailObj, 1996, 153)
     && CAR_AT(LeaveCarTrails, 2000, 154)
     && CAR_AT(ForceBuzzTime, 2004, 154)
     && CAR_AT(fAngleToCamera, 2008, 154)
     && CAR_AT(_hole1108, 1108, 14)
     && CAR_AT(_hole1161, 1161, 14)
     && CAR_AT(_hole1176, 1176, 16)
     && CAR_AT(_hole1881, 1881, 148)
     && CAR_AT(_hole1946, 1946, 150)
     && CAR_AT(_hole1989, 1989, 151)
     && CAR_AT(_pad2012, 2012, 154)

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
     && sizeof(((Car *)0)->_hole1881) == 3
     && sizeof(((Car *)0)->_hole1946) == 2
     && sizeof(((Car *)0)->_hole1989) == 3

     && sizeof(Car) == (size_t)2016 + 154 * CAR_SLACK
     && sizeof(CarState) == 1024 + CARSTATE_SLACK
     && sizeof(TopologyCoordinate) == TOPOLOGY_SIZEOF
     && sizeof(CarNode) == 2 * sizeof(void *)
     && sizeof(DriverInfo) == 20 + CAR_SLACK
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
TrackRoute      *car_get_route(Car *c);                  // 0x00131740
TrackRoutePoint *car_get_route_point(Car *c);            // 0x00131770
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

#endif // CAR_H
