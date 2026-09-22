// cardriver -- CarDriver (0x00134ce0 .. 0x00134ea0).
//
// CarDriver is the base of the driver hierarchy -- RealDriver (the human),
// PsychoDriver (the AI) and NullDriver all derive from it -- and on its
// own it is almost entirely an input record: one steering angle, three
// pedals, two gears and a nitro flag, plus the DriveTarget it steers
// through.
//
// Almost every method here is an empty virtual stub. That is not a gap in
// the port; it is what the base class is. Twelve of the thirty-two
// out-of-line functions are `jr ra` with a nop or a cleared register in
// the delay slot, waiting for a derived class to mean something by them.
// They are ported as empty functions with that noted, because the
// physics calls them through the vtable and an absent one would be a
// silent no-op instead of a deliberate one.
//
// 560 bytes. The vtable pointer is at **556**, after the data rather
// than before it: this image is built with the old g++ ABI, which puts
// the vptr at the end of the object. That is worth stating loudly,
// because every other class in this port will have the same shape and
// the instinct is to expect it at offset 0.
//
// See docs/formats/car-driver.md.

#ifndef CARDRIVER_H
#define CARDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "drivetarget.h"

// type#2869 in the debug info, stored as a 32-bit word. The ranges come
// from the gearbox, which is not ported yet, so no names are invented
// here -- only the width, which is what the layout needs.
typedef int32_t Gear;

typedef struct CarDriver {
    DriveTarget MyDriveTarget;  //   0  528 bytes, embedded not inherited
    uint16_t    Steering;       // 528  a BAM; sh to write, lhu to read
    uint16_t    _pad0;          // 530
    float       Throttle;       // 532
    float       Brake;          // 536
    float       EBrake;         // 540
    Gear        DesiredGear;    // 544
    Gear        SportGear;      // 548
    int32_t     NitroFlag;      // 552  a bool stored as a word
    uint32_t    _vtable;        // 556
} CarDriver;

#ifndef CARDRIVER_NO_ASSERT
typedef char cardriver_layout_check[
    (offsetof(CarDriver, MyDriveTarget) == 0
     && offsetof(CarDriver, Steering) == 528
     && offsetof(CarDriver, Throttle) == 532
     && offsetof(CarDriver, Brake) == 536
     && offsetof(CarDriver, EBrake) == 540
     && offsetof(CarDriver, DesiredGear) == 544
     && offsetof(CarDriver, SportGear) == 548
     && offsetof(CarDriver, NitroFlag) == 552
     && offsetof(CarDriver, _vtable) == 556
     && sizeof(CarDriver) == 560) ? 1 : -1];
#endif

// The address the constructor and destructor both write to byte 556,
// built as `lui v0,0x0029 ; addiu v0,v0,9384`. Nothing in this object
// ever reads it. Car does: Drive and UpdateHeadlightsAndHorn dispatch
// through it with vtable.h's `vt_slot`, at the byte offsets below.
//
//      8  destructor          64  SetTarget          120  ZeroSteeringMemory
//     16  Drive (pure)        72  SetSteerToPoint    128  ClearSteeringMemory
//     24  DoSnapshot          80  GetDriverNumber    136  GetDesiredSpeed
//     32  AddJoyHandlers          (pure)             144  GetDesiredTimeToSpeed
//     40  RemoveJoyHandlers   88  StartHonkHorn      152  SetPhysicsMode
//     48  SetLowGear (pure)   96  StopHonkHorn       160  GetSteerToPoint
//     56  SetDesiredSpeed    104  IsHonking
//         (pure)             112  MaxSpeedToTarget
//
// Names from NullDriver's table (0x00292400), which fills in every pure one.
#define CARDRIVER_VTABLE  0x002924a8u
#define NULLDRIVER_VTABLE 0x00292400u

#define CARDRIVER_VT_DRIVE            16
#define CARDRIVER_VT_START_HONK_HORN  88
#define CARDRIVER_VT_STOP_HONK_HORN   96
#define CARDRIVER_VT_IS_HONKING      104

// 0x00134e40. Writes the vtable, runs the DriveTarget constructor, clears
// the inputs and sets DesiredGear to 1.
//
// Two details the listing gives away and a re-implementation would not:
//
//  * **SportGear is never initialised.** The DriveTarget constructor
//    memsets 528 bytes, which stops exactly at Steering, and the run of
//    stores that follows covers Throttle, Brake, EBrake, NitroFlag and
//    DesiredGear but not byte 548. A fresh CarDriver inherits whatever
//    was in the allocation.
//  * **DesiredGear = 1 is written in a delay slot**, after the call that
//    uses the register, which is why it is easy to miss.
//
// DriveTarget's own constructor is not ported -- it calls Clear, which
// reaches into Car -- so this does the part of it that is observable
// from here and nothing more: `bMemSet(this, 0, 528)`, which is the
// first thing that constructor does and the only part CarDriver's own
// stores depend on. The Clear that follows it in the image is left to
// the DriveTarget slice, and `cardriver_init` says so rather than
// pretending the object is fully built.
void cardriver_init(CarDriver *d);

// 0x00134de0. Rewrites the same vtable pointer, then runs the DriveTarget
// destructor -- which is `if (flags & 1) operator delete(this)` and
// nothing else -- and then applies its own flags the same way. The port
// does the vtable write and leaves the freeing to the caller, since
// nothing here owns memory.
void cardriver_fini(CarDriver *d);

// 0x00134d50. `j __as__11DriveTargetR11DriveTarget` -- a tail call, with
// a0 still the CarDriver. That works because MyDriveTarget is at offset
// 0, so the two pointers are the same address; the whole 528-byte record
// is copied over.
void cardriver_set_target(CarDriver *d, const DriveTarget *t);

// 0x00134dd8. `move v0,a0` -- again offset 0, so this hands back the
// CarDriver's own address reinterpreted as its DriveTarget.
DriveTarget *cardriver_get_drive_target(CarDriver *d);

// ------------------------------------------------------- the input record

void cardriver_set_steering(CarDriver *d, uint16_t bam);   // 0x00134d68
void cardriver_set_throttle(CarDriver *d, float f);        // 0x00134d78
void cardriver_set_brake(CarDriver *d, float f);           // 0x00134d70
void cardriver_set_ebrake(CarDriver *d, float f);          // 0x00134d60
void cardriver_set_desired_gear(CarDriver *d, Gear g);     // 0x00134d88
void cardriver_set_sport_gear(CarDriver *d, Gear g);       // 0x00134d80
void cardriver_set_nitro(CarDriver *d, int32_t on);        // 0x00134d58

uint16_t cardriver_get_steering(const CarDriver *d);       // 0x00134dc0
float    cardriver_get_throttle(const CarDriver *d);       // 0x00134db8
float    cardriver_get_brake(const CarDriver *d);          // 0x00134db0
float    cardriver_get_ebrake(const CarDriver *d);         // 0x00134da8
Gear     cardriver_get_desired_gear(const CarDriver *d);   // 0x00134da0
Gear     cardriver_get_sport_gear(const CarDriver *d);     // 0x00134d98
int32_t  cardriver_get_nitro(const CarDriver *d);          // 0x00134d90

// ----------------------------------------------------------- the stubs

// Each of these is `jr ra` with nothing but a nop or a cleared return
// register behind it. They exist so a derived class has something to
// override; the base answers nothing.
//
// The ones that return are explicit about what they return, because a
// caller cannot tell a stub from a computed zero:
//
//   GetSteerToPoint       move v0,zero    -> NULL
//   IsHonking             move v0,zero    -> false
//   GetDesiredTimeToSpeed mtc1 zero,$f0   -> 0.0f
//   GetDesiredSpeed       mtc1 zero,$f0   -> 0.0f
//   MaxSpeedToTarget      mtc1 zero,$f0   -> 0.0f, target ignored
bVector2 *cardriver_get_steer_to_point(CarDriver *d);          // 0x00134ce0
void      cardriver_set_steer_to_point(CarDriver *d, bVector2 *p); // ..4d48
void      cardriver_set_physics_mode(CarDriver *d, int32_t m); // 0x00134ce8
float     cardriver_get_desired_time_to_speed(CarDriver *d);   // 0x00134cf0
float     cardriver_get_desired_speed(CarDriver *d);           // 0x00134d00
void      cardriver_clear_steering_memory(CarDriver *d);       // 0x00134d10
void      cardriver_zero_steering_memory(CarDriver *d);        // 0x00134d18
float     cardriver_max_speed_to_target(CarDriver *d, DriveTarget *t); // ..4d20
int32_t   cardriver_is_honking(CarDriver *d);                  // 0x00134d30
void      cardriver_stop_honk_horn(CarDriver *d);              // 0x00134d38
void      cardriver_start_honk_horn(CarDriver *d);             // 0x00134d40
void      cardriver_add_joy_handlers(CarDriver *d);            // 0x00134dd0
void      cardriver_remove_joy_handlers(CarDriver *d);         // 0x00134dc8

// CarDriver::DoSnapshot (0x0012f150) is **not** ported: it needs
// ReplaySnapshot, the same dependency that stopped CarState::DoSnapshot
// and Engine::DoSnapshot.

#endif
