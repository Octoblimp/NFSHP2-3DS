// cardriver -- see cardriver.h.

#include "cardriver.h"

#include <string.h>

DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src)
{
    // 0x00208788: bMemCpy(a0, a1, 528), then `move v0,s0`. The size is an
    // immediate, so it is the whole record every time regardless of how
    // many points are actually in use.
    memcpy(dst, src, sizeof(DriveTarget));
    return dst;
}

void cardriver_init(CarDriver *d)
{
    // The vtable is written *first*, before the DriveTarget constructor
    // runs. It lands at 556, past the 528 bytes that constructor clears,
    // so the ordering does not matter here -- but it is the order the
    // image uses and there is no reason to change it.
    d->_vtable = CARDRIVER_VTABLE;

    // The DriveTarget constructor's memset. Its Clear() is not ported;
    // see cardriver.h.
    memset(&d->MyDriveTarget, 0, sizeof(DriveTarget));

    d->Throttle = 0.0f;
    d->Steering = 0;
    d->Brake    = 0.0f;
    d->EBrake   = 0.0f;
    d->NitroFlag = 0;

    // `sw v0,544(s0)` sits in the delay slot of the call to Clear, with
    // v0 loaded with 1 four instructions earlier. Neutral is gear 1.
    d->DesiredGear = 1;

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
    // Then CarDriver applies its own flags the same way. Neither frees
    // anything the port owns, so nothing more happens here.
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
