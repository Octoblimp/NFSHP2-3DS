// cardriver -- see cardriver.h.

#include "cardriver.h"

#include "bmem.h"
#include "replay.h"
#include "vtable.h"

void cardriver_init(CarDriver *d)
{
    // The vtable is written *first*, in the delay slot of the jal to the
    // DriveTarget constructor. It lands at 556, past the 528 bytes that
    // constructor clears, so the ordering does not matter here -- but it
    // is the order the image uses and there is no reason to change it.
    d->_vtable = CARDRIVER_VTABLE;

    drivetarget_init(&d->MyDriveTarget);

    d->Throttle = 0.0f;
    d->Steering = 0;
    d->Brake    = 0.0f;
    d->EBrake   = 0.0f;
    d->NitroFlag = 0;

    // `sw v0,544(s0)` sits in the delay slot of the call to Clear, with
    // v0 loaded with 1 four instructions earlier. Neutral is gear 1.
    d->DesiredGear = 1;

    // `lwc1 $f12,532(s0)`: the Throttle just stored, read back.
    drivetarget_clear(&d->MyDriveTarget, NULL, d->Throttle);

    // SportGear is deliberately not written. The memset stops at 528 and
    // no store covers 548, so a fresh CarDriver inherits whatever was in
    // the allocation. Setting it here would be a fix, not a port.
}

void cardriver_fini(CarDriver *d)
{
    // The destructor rewrites the same vtable pointer before running the
    // base destructor -- the standard C++ trick so that a virtual call
    // made while unwinding dispatches to this class and not to a derived
    // one that is already gone.
    d->_vtable = CARDRIVER_VTABLE;

    // `_$_11DriveTarget(this, 2)` follows, and that destructor is
    // `if (flags & 1) operator delete(this)` -- with flags 2, nothing.
    // CarDriver's own flags are cardriver_destroy's.
}

void cardriver_destroy(CarDriver *d, int32_t flags)
{
    cardriver_fini(d);
    if (flags & 1)
        bFree(d);
}

void cardriver_set_target(CarDriver *d, const DriveTarget *t)
{
    // `j __as__11DriveTargetR11DriveTarget` with a0 untouched: a tail
    // call into DriveTarget::operator=, which works only because
    // MyDriveTarget is at offset 0.
    drivetarget_assign(&d->MyDriveTarget, t);
}

DriveTarget *cardriver_get_drive_target(CarDriver *d)
{
    // `move v0,a0`.
    return &d->MyDriveTarget;
}

// ------------------------------------------------------- the input record

void cardriver_set_steering(CarDriver *d, uint16_t bam) { d->Steering = bam; }
void cardriver_set_throttle(CarDriver *d, float f)      { d->Throttle = f; }
void cardriver_set_brake(CarDriver *d, float f)         { d->Brake = f; }
void cardriver_set_ebrake(CarDriver *d, float f)        { d->EBrake = f; }
void cardriver_set_desired_gear(CarDriver *d, Gear g)   { d->DesiredGear = g; }
void cardriver_set_sport_gear(CarDriver *d, Gear g)     { d->SportGear = g; }
void cardriver_set_nitro(CarDriver *d, int32_t on)      { d->NitroFlag = on; }

// `lhu` -- the steering angle comes back zero-extended, so a BAM past a
// half turn reads as a large positive number rather than a negative one.
uint16_t cardriver_get_steering(const CarDriver *d)  { return d->Steering; }
float    cardriver_get_throttle(const CarDriver *d)  { return d->Throttle; }
float    cardriver_get_brake(const CarDriver *d)     { return d->Brake; }
float    cardriver_get_ebrake(const CarDriver *d)    { return d->EBrake; }
Gear     cardriver_get_desired_gear(const CarDriver *d) { return d->DesiredGear; }
Gear     cardriver_get_sport_gear(const CarDriver *d)   { return d->SportGear; }
int32_t  cardriver_get_nitro(const CarDriver *d)        { return d->NitroFlag; }

// ----------------------------------------------------------- the stubs

bVector2 *cardriver_get_steer_to_point(CarDriver *d)
{
    (void)d;
    return NULL;                        // move v0,zero
}

void cardriver_set_steer_to_point(CarDriver *d, bVector2 *p)
{
    (void)d; (void)p;                   // jr ra ; nop -- the point is dropped
}

void cardriver_set_physics_mode(CarDriver *d, int32_t m)
{
    (void)d; (void)m;
}

float cardriver_get_desired_time_to_speed(CarDriver *d)
{
    (void)d;
    return 0.0f;                        // mtc1 zero,$f0
}

float cardriver_get_desired_speed(CarDriver *d)
{
    (void)d;
    return 0.0f;
}

void cardriver_clear_steering_memory(CarDriver *d) { (void)d; }
void cardriver_zero_steering_memory(CarDriver *d)  { (void)d; }

float cardriver_max_speed_to_target(CarDriver *d, DriveTarget *t)
{
    // The target is not even loaded. PsychoDriver's override at
    // 0x00138620 is 360 bytes; this one is four.
    (void)d; (void)t;
    return 0.0f;
}

int32_t cardriver_is_honking(CarDriver *d)
{
    (void)d;
    return 0;                           // move v0,zero
}

void cardriver_stop_honk_horn(CarDriver *d)   { (void)d; }
void cardriver_start_honk_horn(CarDriver *d)  { (void)d; }
void cardriver_add_joy_handlers(CarDriver *d) { (void)d; }
void cardriver_remove_joy_handlers(CarDriver *d) { (void)d; }

// ------------------------------------------------------------- the replay

void cardriver_do_snapshot(CarDriver *d, ReplaySnapshot *s)
{
    // Retail 0x00130958. DesiredGear goes as one signed byte; SportGear and
    // NitroFlag are not saved at all.
    ReplaySnapshot_BeginNamedSection(s, "CarDriver");
    ReplaySnapshot_MoveUShort(s, &d->Steering, 2);
    ReplaySnapshot_MoveFloat(s, &d->Throttle);
    ReplaySnapshot_MoveFloat(s, &d->Brake);
    ReplaySnapshot_MoveFloat(s, &d->EBrake);
    ReplaySnapshot_MoveData(s, &d->DesiredGear, 1, 4, 1);
    drivetarget_do_snapshot(&d->MyDriveTarget, s);
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------ NullDriver

void nulldriver_destroy(NullDriver *d, int32_t flags)
{
    d->Base._vtable = NULLDRIVER_VTABLE;
    cardriver_destroy(&d->Base, flags);
}

void nulldriver_drive(NullDriver *d, float dt)      { (void)d; (void)dt; }
void nulldriver_set_low_gear(NullDriver *d)         { (void)d; }

void nulldriver_set_desired_speed(NullDriver *d, float speed, float time,
                                  int32_t flag)
{
    (void)d; (void)speed; (void)time; (void)flag;
}

void nulldriver_set_target(NullDriver *d, DriveTarget *t)
{
    // Not CarDriver's, which copies the whole target: the null driver
    // drops it.
    (void)d; (void)t;
}

int32_t nulldriver_get_driver_number(NullDriver *d)
{
    (void)d;
    return NULLDRIVER_DRIVER_NUMBER;    // lui v0,0xfffe ; ori v0,v0,0x7961
}

// ------------------------------------------------------------- the tables

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$9CarDriver, 0x002924a8. `__pure_virtual` at 16, 48, 56 and 80.
static const VtEntry cardriver_vt[CARDRIVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(cardriver_destroy),                   //   8  0x00134de0
    { 0, 0, NULL },                         //  16  Drive
    E(cardriver_do_snapshot),               //  24  retail 0x00130958
    E(cardriver_add_joy_handlers),          //  32  0x00134dd0
    E(cardriver_remove_joy_handlers),       //  40  0x00134dc8
    { 0, 0, NULL },                         //  48  SetLowGear
    { 0, 0, NULL },                         //  56  SetDesiredSpeed
    E(cardriver_set_target),                //  64  0x00134d50
    E(cardriver_set_steer_to_point),        //  72  0x00134d48
    { 0, 0, NULL },                         //  80  GetDriverNumber
    E(cardriver_start_honk_horn),           //  88  0x00134d40
    E(cardriver_stop_honk_horn),            //  96  0x00134d38
    E(cardriver_is_honking),                // 104  0x00134d30
    E(cardriver_max_speed_to_target),       // 112  0x00134d20
    E(cardriver_zero_steering_memory),      // 120  0x00134d18
    E(cardriver_clear_steering_memory),     // 128  0x00134d10
    E(cardriver_get_desired_speed),         // 136  0x00134d00
    E(cardriver_get_desired_time_to_speed), // 144  0x00134cf0
    E(cardriver_set_physics_mode),          // 152  0x00134ce8
    E(cardriver_get_steer_to_point),        // 160  0x00134ce0
};

// _vt$10NullDriver, 0x00292400: CarDriver's, with the four pure ones, the
// destructor and SetTarget its own.
static const VtEntry nulldriver_vt[CARDRIVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(nulldriver_destroy),                  //   8  0x00134cc8
    E(nulldriver_drive),                    //  16  0x00134cc0
    E(cardriver_do_snapshot),               //  24  retail 0x00130958
    E(cardriver_add_joy_handlers),          //  32  0x00134dd0
    E(cardriver_remove_joy_handlers),       //  40  0x00134dc8
    E(nulldriver_set_low_gear),             //  48  0x00134c98
    E(nulldriver_set_desired_speed),        //  56  0x00134cb8
    E(nulldriver_set_target),               //  64  0x00134cb0
    E(cardriver_set_steer_to_point),        //  72  0x00134d48
    E(nulldriver_get_driver_number),        //  80  0x00134ca0
    E(cardriver_start_honk_horn),           //  88  0x00134d40
    E(cardriver_stop_honk_horn),            //  96  0x00134d38
    E(cardriver_is_honking),                // 104  0x00134d30
    E(cardriver_max_speed_to_target),       // 112  0x00134d20
    E(cardriver_zero_steering_memory),      // 120  0x00134d18
    E(cardriver_clear_steering_memory),     // 128  0x00134d10
    E(cardriver_get_desired_speed),         // 136  0x00134d00
    E(cardriver_get_desired_time_to_speed), // 144  0x00134cf0
    E(cardriver_set_physics_mode),          // 152  0x00134ce8
    E(cardriver_get_steer_to_point),        // 160  0x00134ce0
};

#undef E

void cardriver_install_vtables(void)
{
    vt_install(CARDRIVER_VTABLE, cardriver_vt, CARDRIVER_VT_ENTRIES);
    vt_install(NULLDRIVER_VTABLE, nulldriver_vt, CARDRIVER_VT_ENTRIES);
}
