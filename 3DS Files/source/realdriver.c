// realdriver -- see realdriver.h.

#include "realdriver.h"

#include <math.h>
#include <stddef.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "drivetrain.h"
#include "eefpu.h"
#include "engine.h"
#include "joyevent.h"
#include "player.h"
#include "race.h"
#include "replay.h"
#include "vtable.h"
#include "world.h"

// ------------------------------------------------------------- the seams

void (*gMaybeAddTrackRoutePointFn)(const bVector3 *, const bVector3 *, float,
                                   int32_t, int32_t);
void (*gCancelTuningDrivingLinesFn)(void);
void (*gRadialBlurOnFn)(int32_t);
void (*gRadialBlurOffFn)(int32_t);
void (*gRadialBlurAlphaFn)(int32_t, float, float);
void (*gReplayRegisterInterestingEventFn)(struct ReplayManager *, float,
                                          const char *);
void    (*gPlayerRerouteJoyEventFn)(struct Player *, JoystickPort, JoyEvent,
                                    uint8_t);
int32_t (*gPlayerIsAllowedToResetFn)(struct Player *);
void    (*gPlayerSelectedResetFn)(struct Player *);
int32_t (*gPlayerIsNisPlayingFn)(const struct Player *);
void    (*gChopperHonkAttackFn)(void);
float (*gCopManagerGetResetDirectionFn)(struct tCopManager *);
void  (*gCopManagerBeACopToggleSirenAndLightsFn)(struct tCopManager *);
void (*gCarResetToRoutePointFn)(struct Car *, struct TrackRoute *,
                                struct TrackRoutePoint *, float, int32_t,
                                float);
void (*gBaseCarSoundStartHonkHornFn)(struct BaseCarSound *);
void (*gBaseCarSoundStopHonkHornFn)(struct BaseCarSound *);

static void radial_blur_on(int32_t view)
{
    if (gRadialBlurOnFn != NULL)
        gRadialBlurOnFn(view);
}

static void radial_blur_off(int32_t view)
{
    if (gRadialBlurOffFn != NULL)
        gRadialBlurOffFn(view);
}

static void register_ebrake_event(void)
{
    // `lw a0,-23008(gp)` straight into the call: the image never tests
    // pReplayManager here. $f12 is the 1.0 the caller loaded for its own
    // clamp, and the name is "EBrake" in .sdata at 0x003231f8.
    if (gReplayRegisterInterestingEventFn != NULL)
        gReplayRegisterInterestingEventFn(pReplayManager, 1.0f, "EBrake");
}

// ----------------------------------------------------------- the globals

// .sdata, with the image's bits.
float PowerSlideYawCoef                = 0.95f;       // 0x003231b8  3f733333
float SteeringSpeed                    = 9.0f;        // 0x003231d8  41100000
float SteeringReturnFactor             = 2.0f;        // 0x003231dc  40000000
float CounterSteerFadeStart            = 13.410818f;  // 0x003231e0  415692b6
float CounterSteerFadeEnd              = 17.88109f;   // 0x003231e4  418f0c79
float MaxSpeedForReverse               = 0.5f;        // 0x003231e8  3f000000
float MinSpeedForThrottle              = -30.0f;      // 0x003231ec  c1f00000
float MinSpeedForThrottleWhenReversing = -2.0f;       // 0x003231f0  c0000000
float BrakingSpeed                     = 0.6f;        // 0x00323200  3f19999a
float UnBrakingSpeed                   = 6.0f;        // 0x00323204  40c00000
float NitrousActiveTime                = 4.0f;        // 0x00323208  40800000
float NitrousRechargeTime              = 0.0f;        // 0x0032320c  00000000

// The seven arrays behind the tables, in the image's .data. Every one is
// file-static there bar the names the symbol table keeps.
static const float SteeringWheelRangeData[10] = {    // 0x002e8798
    45.0f, 15.0f, 11.0f, 9.0f, 8.0f, 7.0f, 6.0f, 6.0f, 6.0f, 6.0f,
};
static const float SteeringRangeData[10] = {         // 0x002e87c0
    45.0f, 13.0f, 8.0f, 5.5f, 4.2f, 3.6f, 3.1f, 2.9f, 2.9f, 2.9f,
};
static const float SteeringSpeedData[10] = {         // 0x002e87e8
    1.0f, 1.0f, 0.92f, 0.78f, 0.64f, 0.54f, 0.48f, 0.42f, 0.38f, 0.34f,
};
static const float SteeringCurveData[6] = {          // 0x002e8810
    0.0f, 0.1f, 0.24f, 0.53f, 0.79f, 1.0f,
};
static const float SteeringInputCurve[9] = {         // 0x002e8888
    1.0f, 0.4f, 0.2f, 0.1f, 0.0f, -0.1f, -0.2f, -0.4f, -1.0f,
};
static const float YawCoeffCurve[5] = {              // 0x002e88c8
    0.8f, 0.9f, 0.92f, 0.95f, 1.0f,
};
static const float BrakingCurveTable[6] = {          // 0x002e88f8
    0.0f, 0.2f, 0.4f, 0.6f, 0.8f, 1.0f,
};

Table SteeringWheelRangeTable;   // 0x002e8828
Table SteeringRangeTable;        // 0x002e8840
Table SteeringSpeedTable;        // 0x002e8858
Table SteeringCurveTable;        // 0x002e8870
Table SteeringInputTable;        // 0x002e88b0
Table YawCoeffTable;             // 0x002e88e0
Table BrakingCurve;              // 0x002e8910

void realdriver_static_init(void)
{
    table_init(&SteeringWheelRangeTable, SteeringWheelRangeData, 10,
               0.0f, 160.0f);
    table_init(&SteeringRangeTable, SteeringRangeData, 10, 0.0f, 160.0f);
    table_init(&SteeringSpeedTable, SteeringSpeedData, 10, 0.0f, 160.0f);
    table_init(&SteeringCurveTable, SteeringCurveData, 6, 0.0f, 1.0f);
    table_init(&SteeringInputTable, SteeringInputCurve, 9, 0.0f, 256.0f);
    table_init(&YawCoeffTable, YawCoeffCurve, 5, 0.0f, 1.0f);
    table_init(&BrakingCurve, BrakingCurveTable, 6, 0.0f, 1.0f);
}

// ------------------------------------------------------ vtable dispatch

typedef void (*VtVoidFn)(void *self);

static void call_void_slot(RealDriver *d, int slot)
{
    const VtEntry *e = vt_slot(d->Base._vtable, slot);

    ((VtVoidFn)e->fn)(vt_this(d, e));
}

// ------------------------------------------------------ the constructor

void realdriver_init(RealDriver *d, Car *car)
{
    // CarDriver's constructor, inlined store for store: see cardriver_init.
    cardriver_init(&d->Base);

    d->pCar             = car;
    d->Port             = -1;
    d->LastNitroRequest = 0;
    d->HandlersAdded    = 0;

    // In the delay slot of the jal to ResetJoyValues.
    d->Base._vtable = REALDRIVER_VTABLE;
    realdriver_reset_joy_values(d);

    d->StartLineState     = 1;
    d->Base.DesiredGear   = RD_GEAR_AUTO;
    d->StopRightNow       = 0;
    d->ForcedEBrakeStop   = 0.0f;
    d->bPowerSlide        = 0;
    d->ManualTransmission = RD_AUTOMATIC;
    d->Reversing          = 0;
    d->LastNitroRequest   = 0;    // a second time
}

void realdriver_fini(RealDriver *d)
{
    Player *pl;

    d->Base._vtable = REALDRIVER_VTABLE;

    pl = d->pCar->pPlayer;
    if (pl != NULL)
        radial_blur_off(pl->PlayerNumber);

    realdriver_remove_joy_handlers(d);
}

void realdriver_destroy(RealDriver *d, int32_t flags)
{
    realdriver_fini(d);

    // `j _$_9CarDriver` with the caller's flags.
    cardriver_destroy(&d->Base, flags);
}

// ---------------------------------------------------------- the handlers

void realdriver_add_joy_handlers(RealDriver *d)
{
    JoystickPort p;

    if (d->HandlersAdded)
        return;

    // Port is reloaded before every call; nothing in between can change
    // it, so one read would do, but the calls are in the image's order.
    p = d->Port;
    AddJoyHandler(p, JOY_EVENT_STEER, realdriver_joy_steer, d);
    AddJoyHandler(p, JOY_EVENT_STEER_ANALOG, realdriver_joy_steer, d);
    AddJoyHandler(p, JOY_EVENT_THROTTLE, realdriver_joy_throttle, d);
    AddJoyHandler(p, JOY_EVENT_THROTTLE_ANALOG, realdriver_joy_throttle, d);
    AddJoyHandler(p, JOY_EVENT_THROTTLE_ANALOG_ALTERNATE,
                  realdriver_joy_throttle, d);
    AddJoyHandler(p, JOY_EVENT_BRAKE, realdriver_joy_brake, d);
    AddJoyHandler(p, JOY_EVENT_BRAKE_ANALOG, realdriver_joy_brake, d);
    AddJoyHandler(p, JOY_EVENT_BRAKE_ANALOG_ALTERNATE, realdriver_joy_brake,
                  d);
    AddJoyHandler(p, JOY_EVENT_REVERSE, realdriver_joy_reverse, d);
    AddJoyHandler(p, JOY_EVENT_REVERSE_ANALOG, realdriver_joy_reverse, d);
    AddJoyHandler(p, JOY_EVENT_EBRAKE, realdriver_joy_ebrake, d);
    AddJoyHandler(p, JOY_EVENT_EBRAKE_ANALOG, realdriver_joy_ebrake, d);
    AddJoyHandler(p, JOY_EVENT_SHIFTUP, realdriver_joy_shift_up, d);
    AddJoyHandler(p, JOY_EVENT_SHIFTDOWN, realdriver_joy_shift_down, d);
    AddJoyHandler(p, JOY_EVENT_RESET_CAR, realdriver_joy_reset_car, d);
    AddJoyHandler(p, JOY_EVENT_HONK_HORN, realdriver_joy_honk_horn, d);
    AddJoyHandler(p, JOY_EVENT_NITRO_BOOST, realdriver_joy_nitro_boost, d);

    d->HandlersAdded = 1;
}

void realdriver_remove_joy_handlers(RealDriver *d)
{
    JoyEvent ev;

    if (!d->HandlersAdded)
        return;

    for (ev = JOY_EVENT_STEER; ev <= JOY_EVENT_NITRO_BOOST; ev++)
        RemoveJoyHandler(d->Port, ev);

    // Through the table, slot 96: a horn held down when the handlers go
    // is let go.
    call_void_slot(d, CARDRIVER_VT_STOP_HONK_HORN);

    d->HandlersAdded = 0;
}

// ------------------------------------------------------- the small ones

void realdriver_disable_start_line_state(RealDriver *d)
{
    d->StartLineState = 0;
    call_void_slot(d, CARDRIVER_VT_SET_LOW_GEAR);
}

void realdriver_enable_start_line_state(RealDriver *d)
{
    d->StartLineState = 1;
}

void realdriver_set_manual_transmission(RealDriver *d, int32_t m)
{
    if (m == RD_MANUAL) {
        d->ManualTransmission = RD_MANUAL;
        d->Base.DesiredGear   = d->pCar->State.CurrentGear;
        return;
    }

    // -1 is stored in the delay slot of the second test, whichever way it
    // goes; any value but 0 and 1 means the sport shift.
    d->Base.DesiredGear   = RD_GEAR_AUTO;
    d->ManualTransmission = (m == 0) ? RD_AUTOMATIC : RD_SPORT;
}

void realdriver_set_low_gear(RealDriver *d)
{
    d->Base.DesiredGear = (d->ManualTransmission == RD_MANUAL) ? 2
                                                              : RD_GEAR_AUTO;
}

void realdriver_force_ebrake_stop(RealDriver *d, float t)
{
    d->ForcedEBrakeStop = t;
}

void realdriver_reset_joy_values(RealDriver *d)
{
    d->EBrakeInput                = 0.0f;
    d->JoySteeringAnalog          = 128;
    d->JoySteeringDigital         = 128;
    d->JoyThrottleDigital         = 0;
    d->JoyThrottleAnalog          = 0;
    d->JoyThrottleAnalogAlternate = 0;
    d->JoyBrakeDigital            = 0;
    d->JoyBrakeAnalog             = 0;
    d->JoyBrakeAnalogAlternate    = 0;
    d->JoyReverseDigital          = 0;
    d->JoyReverseAnalog           = 0;
    d->JoyEBrakeDigital           = 0;
    d->JoyEBrakeAnalog            = 0;
    d->SteeringInput              = 0.0f;
    d->ThrottleInput              = 0.0f;
    d->BrakeInput                 = 0.0f;
    d->ReverseInput               = 0.0f;
}

void realdriver_reset_port_joy_values(JoystickPort port)
{
    int32_t i;

    if (pCurrentWorld == NULL)
        return;
    for (i = 0; i < pCurrentWorld->TotalNumCars; i++) {
        Car        *car = pCurrentWorld->CarTable[i];
        RealDriver *d;

        if (car->TheControlMode != REAL_CONTROL)
            continue;
        d = (RealDriver *)(void *)car->pCarDriver;
        if (d->Port == port)
            realdriver_reset_joy_values(d);
    }
}

JoystickPort realdriver_get_port(RealDriver *d) { return d->Port; }

int32_t realdriver_get_driver_number(RealDriver *d)
{
    // `lh v0,10(v1)`: the car's DriverNumber, sign-extended.
    return d->pCar->DriverNumber;
}

void realdriver_set_desired_speed(RealDriver *d, float speed, float time,
                                  int32_t flag)
{
    (void)d; (void)speed; (void)time; (void)flag;   // jr ra ; nop
}

void realdriver_set_predicted_target(RealDriver *d, DriveTarget *t)
{
    // `j __as__11DriveTargetR11DriveTarget` with a0 the driver: offset 0.
    drivetarget_assign(&d->Base.MyDriveTarget, t);
}

void realdriver_set_stop_right_now(RealDriver *d, int32_t on)
{
    d->StopRightNow = on;
}

void realdriver_set_joystick_port(RealDriver *d, JoystickPort p)
{
    d->Port = p;
}

Car *realdriver_get_car(RealDriver *d) { return d->pCar; }

// ------------------------------------------------------------- Drive

void realdriver_drive(RealDriver *d, float dt)
{
    Car    *car = d->pCar;
    Player *pl;

    // a0 the position as a bVector2, a1 the velocity, $f12 the position's
    // z (`lwc1 $f12,8(a0)`), a2 zero, a3 the car's class.
    if (gMaybeAddTrackRoutePointFn != NULL)
        gMaybeAddTrackRoutePointFn(&car->State.Position,
                                   &car->State.Velocity,
                                   car->State.Position.z, 0,
                                   car->pCarTypeInfo->CarClass);

    // RealDriverAddNearbyDebugTopology(&car->TheTopologyCoordinate,
    // &car->State.Position) is `jr ra ; nop`.

    if (!IsJoystickPluggedIn(d->Port))
        realdriver_reset_joy_values(d);

    realdriver_do_throttle_brake_reverse(d, dt);
    realdriver_do_steering(d, dt, d->Port);

    // Both after the inputs were read, so a stop takes hold next frame.
    if (d->StopRightNow) {
        d->ThrottleInput = 0.0f;
        d->BrakeInput    = 1.0f;
    }

    if (d->StartLineState)
        d->Base.Brake = 1.0f;

    pl = d->pCar->pPlayer;
    if (pl == NULL)
        return;

    if (realdriver_nitro_active(d) && !realdriver_nitro_was_active(d)) {
        radial_blur_on(pl->PlayerNumber);
        // gp-31644, 0x00321054: 0.8 (0x3f4ccccd).
        if (gRadialBlurAlphaFn != NULL)
            gRadialBlurAlphaFn(pl->PlayerNumber, 0.0f, 0.8f);
        return;
    }

    if (!realdriver_nitro_active(d) && realdriver_nitro_was_active(d))
        radial_blur_off(pl->PlayerNumber);
}

// ---------------------------------------------------------- DoSteering

void realdriver_do_steering(RealDriver *d, float dt, JoystickPort port)
{
    Car            *car = d->pCar;
    const bVector3 *v;
    float cur, yawd, ay, spd, range, r, inv, delta, rate, out;

    // The wheels' angle now, in degrees either side of centre: the BAM
    // times 360/65536 (0x3bb40000), folded at 180 (0x43340000).
    cur = (float)d->Base.Steering * 0.0054931640625f;
    if (180.0f <= cur)
        cur -= 360.0f;

    // gp-31640, 0x00321058: 180/pi, 57.29578 (0x42652ee0).
    yawd = carstate_get_yaw(&car->State) * 57.2957763671875f;
    ay   = fabsf(yawd);

    // vmul.xyz, vaddy.x, vaddz.x: (x*x + y*y) + z*z.
    v   = &car->State.Velocity;
    spd = sqrtf((v->x * v->x + v->y * v->y) + v->z * v->z);

    // The lock the speed allows, in degrees. The port handed in, not the
    // driver's own, decides which table.
    if (IsJoystickTypeWheel(port))
        range = table_get_value(&SteeringWheelRangeTable,
                                car->State.ForwardSpeed);
    else
        range = table_get_value(&SteeringRangeTable,
                                car->State.ForwardSpeed);

    // The power slide latches on past 7 degrees of yaw and off under 5,
    // and only above CounterSteerFadeStart.
    if (d->bPowerSlide) {
        if (ay < 5.0f)
            d->bPowerSlide = 0;
        else if (spd < CounterSteerFadeStart)
            d->bPowerSlide = 0;
    } else if (7.0f < ay && CounterSteerFadeStart <= spd) {
        d->bPowerSlide = 1;
    }

    // Steering against the yaw -- a counter-steer -- in a slide, or past
    // what the table allows: the lock opens to the yaw itself, scaled, up
    // to 45 degrees scaled. PowerSlideYawCoef is written and read back.
    if (yawd * d->SteeringInput < 0.0f && (d->bPowerSlide || range < ay)) {
        if (IsJoystickTypeWheel(port))
            PowerSlideYawCoef = 1.0f;
        else
            PowerSlideYawCoef = table_get_value(&YawCoeffTable,
                                                fabsf(d->SteeringInput));
        range = ay * PowerSlideYawCoef;
        if (PowerSlideYawCoef * 45.0f < range)
            range = PowerSlideYawCoef * 45.0f;
    }

    // Back through the response curve to where the stick would be now.
    r   = cur / range;
    inv = table_inverse_lookup(&SteeringCurveTable, fabsf(r));
    cur = (r < 0.0f) ? -inv : inv;

    delta = d->SteeringInput - cur;

    // How far it may move this frame: faster at low speed, faster again
    // (SteeringReturnFactor) on the way back to centre, never under 0.173
    // (gp-31636, 0x0032105c: 0x3e3126e9).
    rate = SteeringSpeed * table_get_value(&SteeringSpeedTable,
                                           car->State.ForwardSpeed);
    if (0.0f < cur) {
        if (d->SteeringInput < cur)
            rate *= SteeringReturnFactor;
    } else if (cur < 0.0f) {
        if (cur < d->SteeringInput)
            rate *= SteeringReturnFactor;
    }
    rate *= dt;
    if (rate < 0.173f)
        rate = 0.173f;

    if (rate < delta)
        delta = rate;
    else if (delta < -rate)
        delta = -rate;

    cur += delta;

    out = table_get_value(&SteeringCurveTable, fabsf(cur)) * range;
    if (cur < 0.0f)
        out = -out;

    // Degrees to a BAM, through the car's steering ratio: cvt.w.s, then an
    // integer divide by 360 (truncating, toward zero), then `sh`.
    d->Base.Steering = (uint16_t)(ee_trunc_w(out
                                             * car->pCarTypeInfo->Control.Steering
                                             * 65536.0f) / 360);
}

// ----------------------------------------------------- the pedal inputs

void realdriver_joy_steer(JoystickPort port, JoyEvent ev, uint8_t value,
                          void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    uint32_t    v;

    (void)port;

    if (ev == JOY_EVENT_STEER)
        d->JoySteeringDigital = value;
    else if (ev == JOY_EVENT_STEER_ANALOG)
        d->JoySteeringAnalog = value;

    // The digital source wins unless it is centred.
    v = d->JoySteeringDigital;
    if (v == 128)
        v = d->JoySteeringAnalog;

    // 255 is full left, exactly -1; anything else is (128 - v) / 128
    // (0x3c000000), so 0 is +1.0 and 254 is -0.984375.
    if (v == 255) {
        d->SteeringInput = -1.0f;
        return;
    }
    d->SteeringInput = (128.0f - (float)v) * 0.0078125f;
}

void realdriver_joy_throttle(JoystickPort port, JoyEvent ev, uint8_t value,
                             void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    uint32_t    v;

    (void)port;

    if (ev == JOY_EVENT_THROTTLE_ANALOG) {
        // A stiff pedal reads four times as far, capped at 255.
        v = DoesJoystickHaveStiffThrottle(d->Port) ? (uint32_t)value << 2
                                                   : value;
        d->JoyThrottleAnalog = (v < 256) ? (uint8_t)v : 255;
    } else if (ev == JOY_EVENT_THROTTLE) {
        d->JoyThrottleDigital = value;
    } else if (ev == JOY_EVENT_THROTTLE_ANALOG_ALTERNATE) {
        // gp-31632, 0x00321060: 1.07 (0x3f88f5c3), capped at 255.0 and
        // converted with fptoui.
        float f = (float)value * 1.07f;
        if (255.0f < f)
            f = 255.0f;
        d->JoyThrottleAnalogAlternate = (uint8_t)(uint32_t)f;
    }

    v = d->JoyThrottleDigital;
    if (v == 0) {
        v = d->JoyThrottleAnalog;
        if (!(d->JoyThrottleAnalogAlternate < v))
            v = d->JoyThrottleAnalogAlternate;
    }

    // gp-31628, 0x00321064: 1/255 (0x3b808081).
    d->ThrottleInput = (float)v * 0.003921568859368563f;
}

void realdriver_joy_reverse(JoystickPort port, JoyEvent ev, uint8_t value,
                            void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    uint32_t    v;

    (void)port;

    if (ev == JOY_EVENT_REVERSE) {
        d->JoyReverseDigital = value;
    } else if (ev == JOY_EVENT_REVERSE_ANALOG) {
        v = value;
        if (DoesJoystickHaveStiffThrottle(d->Port))
            v = (uint32_t)value << 2;
        d->JoyReverseAnalog = (v < 256) ? (uint8_t)v : 255;
    }

    v = d->JoyReverseDigital;
    if (v == 0)
        v = d->JoyReverseAnalog;

    // gp-31624, 0x00321068: 1/255 again.
    d->ReverseInput = (float)v * 0.003921568859368563f;
}

void realdriver_joy_brake(JoystickPort port, JoyEvent ev, uint8_t value,
                          void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    uint32_t    v;

    (void)port;

    // No stiff-pedal scaling and no 1.07 on the brake.
    if (ev == JOY_EVENT_BRAKE_ANALOG)
        d->JoyBrakeAnalog = value;
    else if (ev == JOY_EVENT_BRAKE)
        d->JoyBrakeDigital = value;
    else if (ev == JOY_EVENT_BRAKE_ANALOG_ALTERNATE)
        d->JoyBrakeAnalogAlternate = value;

    v = d->JoyBrakeDigital;
    if (v == 0) {
        v = d->JoyBrakeAnalog;
        if (!(d->JoyBrakeAnalogAlternate < v))
            v = d->JoyBrakeAnalogAlternate;
    }

    // gp-31612, 0x00321074.
    d->BrakeInput = (float)v * 0.003921568859368563f;
}

void realdriver_joy_ebrake(JoystickPort port, JoyEvent ev, uint8_t value,
                           void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    uint32_t    v;

    (void)port;

    if (ev == JOY_EVENT_EBRAKE)
        d->JoyEBrakeDigital = value;
    else if (ev == JOY_EVENT_EBRAKE_ANALOG)
        // `sll v0,a2,1 ; sb`: doubled and *wrapped*, not capped, so an
        // analog e-brake past half travel reads low again. The image's.
        d->JoyEBrakeAnalog = (uint8_t)(value << 1);

    v = d->JoyEBrakeDigital;
    if (v == 0)
        v = d->JoyEBrakeAnalog;

    // gp-31608, 0x00321078.
    d->EBrakeInput = (float)v * 0.003921568859368563f;
}

// ------------------------------------------------ DoThrottleBrakeReverse

void realdriver_do_throttle_brake_reverse(RealDriver *d, float dt)
{
    Car  *car = d->pCar;
    float t, b, fs, fwd, rev, brake, left;

    // Retail's timer (0x0013bb60): it runs down by dt, and the e-brake
    // holds while time is left and the car is faster than 20 mph (gp-31532,
    // 0x410f0c79). Once either fails the timer is cleared. The demo's int
    // flag held the e-brake for as long as it was set.
    left = d->ForcedEBrakeStop - dt;
    fs   = car->State.ForwardSpeed;
    d->ForcedEBrakeStop = left;
    if (0.0f < left && 8.940545082092285f < fabsf(fs)) {
        d->Base.EBrake = 1.0f;
        t = 0.0f;
    } else {
        d->ForcedEBrakeStop = 0.0f;
        d->Base.EBrake = d->EBrakeInput;
        t = d->ThrottleInput;
    }

    b = d->BrakeInput;

    // gp-31620, 0x0032106c: 0.6 (0x3f19999a), a literal and not the
    // BrakingSpeed global beside it, which has the same value.
    if (0.6f < b)
        d->Reversing = 1;
    else if (MinSpeedForThrottleWhenReversing < fs)
        d->Reversing = 0;

    // Moving forward, the brake pedal brakes. Going backward (hard, or at
    // all once reversing), the pedals swap: brake drives, throttle brakes.
    // Otherwise, near stopped, the brake pedal is the reverse pedal.
    if (MaxSpeedForReverse < fs) {
        rev   = 0.0f;
        brake = b;
        fwd   = t;
    } else if (fs < MinSpeedForThrottle
               || (d->Reversing && fs < MinSpeedForThrottleWhenReversing)) {
        fwd   = 0.0f;
        rev   = b;
        brake = t;
    } else {
        brake = 0.0f;
        fwd   = t;
        rev   = b;
    }

    rev = rev + rev;
    if (1.0f < rev)
        rev = 1.0f;

    d->Base.Brake = brake;

    if (0.5f < d->Base.EBrake
        && (((uint32_t)WorldLoopCounter + 1u) & 7u) == 0
        && 10.0f < car->State.VelocityMagnitude)
        register_ebrake_event();

    // gp-31616, 0x00321070: 0.2 (0x3e4ccccd).
    if (fwd + 0.2f < rev) {
        d->Base.Throttle    = rev;
        d->Base.DesiredGear = RD_GEAR_REVERSE;
    } else {
        d->Base.Throttle = fwd;
        if (d->Base.DesiredGear == RD_GEAR_REVERSE)
            call_void_slot(d, CARDRIVER_VT_SET_LOW_GEAR);
    }

    car->State.Throttle = d->Base.Throttle;
}

void realdriver_do_brake(RealDriver *d, float dt)
{
    (void)dt;

    d->Base.EBrake = d->EBrakeInput;
    d->Base.Brake  = d->BrakeInput;

    if (0.5f < d->EBrakeInput
        && (((uint32_t)WorldLoopCounter + 1u) & 7u) == 0
        && 10.0f < d->pCar->State.VelocityMagnitude)
        register_ebrake_event();
}

// ------------------------------------------------------- the gearbox

static void reroute(RealDriver *d, JoystickPort port, JoyEvent ev,
                    uint8_t value)
{
    Player *pl = d->pCar->pPlayer;

    if (pl != NULL && gPlayerRerouteJoyEventFn != NULL)
        gPlayerRerouteJoyEventFn(pl, port, ev, value);
}

void realdriver_joy_shift_up(JoystickPort port, JoyEvent ev, uint8_t value,
                             void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    Car        *car;
    Gear        g;

    if (value == 0)
        return;

    if (d->ManualTransmission == RD_MANUAL) {
        // Not out of reverse, and not past the top: NumGears counts the
        // forward gears and gear 1 is neutral.
        g = d->Base.DesiredGear;
        if (g == RD_GEAR_REVERSE)
            return;
        if (g < d->pCar->pCarTypeInfo->DriveTrain.NumGears + 1)
            d->Base.DesiredGear = g + 1;
        return;
    }

    if (d->ManualTransmission == RD_SPORT) {
        car = d->pCar;
        if (car->TheMovementMode == MELLOW_MOVEMENT)
            return;
        if (d->Base.DesiredGear == RD_GEAR_SPORT) {
            d->Base.SportGear++;
            return;
        }
        // Retail's: the first press starts from the car's gear, one up
        // unless that is already past the top (the demo's always added
        // one).
        d->Base.DesiredGear = RD_GEAR_SPORT;
        g = car->State.CurrentGear;
        d->Base.SportGear =
            (g < car->pCarTypeInfo->DriveTrain.NumGears + 1) ? g + 1 : g;
        return;
    }

    // An automatic box hands the button to the player: retail's turns it
    // into a zone request, or a Be A Cop call.
    reroute(d, port, ev, value);
}

void realdriver_joy_shift_down(JoystickPort port, JoyEvent ev, uint8_t value,
                               void *obj)
{
    RealDriver *d = (RealDriver *)obj;
    Car        *car;
    Gear        g;

    if (value == 0)
        return;

    if (d->ManualTransmission == RD_MANUAL) {
        g = d->Base.DesiredGear;
        if (g == RD_GEAR_REVERSE)
            return;
        if (g < 2)
            return;
        d->Base.DesiredGear = g - 1;
        return;
    }

    if (d->ManualTransmission == RD_SPORT) {
        car = d->pCar;
        if (car->TheMovementMode == MELLOW_MOVEMENT)
            return;
        if (d->Base.DesiredGear == RD_GEAR_SPORT) {
            d->Base.SportGear--;
            return;
        }
        // Retail's: one down from the car's gear, but first stays first
        // (`slti 3`; the demo's always took one off).
        d->Base.DesiredGear = RD_GEAR_SPORT;
        g = car->State.CurrentGear;
        d->Base.SportGear = (g < RD_GEAR_SECOND) ? g : g - 1;
        return;
    }

    reroute(d, port, ev, value);
}

// ---------------------------------------------------------- the reset

void realdriver_joy_reset_car(JoystickPort port, JoyEvent ev, uint8_t value,
                              void *obj)
{
    RealDriver      *d = (RealDriver *)obj;
    Car             *car;
    Player          *pl;
    TrackRoute      *route;
    TrackRoutePoint *point;
    float speed, along, direction;

    (void)port; (void)ev;

    if (d->StartLineState)
        return;
    if (value == 0)
        return;

    car = d->pCar;
    pl  = car->pPlayer;
    if (pl == NULL)
        return;
    if (gPlayerIsAllowedToResetFn == NULL || !gPlayerIsAllowedToResetFn(pl))
        return;

    direction = 1.0f;
    radial_blur_off(pl->PlayerNumber);

    // The speed the car keeps: its forward speed, times how well its nose
    // lines up with the track (the body's x axis dotted with the path's
    // direction, both on the ground plane), neither below zero, capped at
    // RollingResetSpeed. The image also parks the path direction in a
    // stack slot nothing reads.
    //
    // `max.s fd,fs,ft` is `fs < ft ? ft : fs` and `min.s` is
    // `ft < fs ? ft : fs`; written out so a zero keeps its sign as the
    // EE's does.
    speed = car->State.ForwardSpeed;
    speed = (speed < 0.0f) ? 0.0f : speed;
    along = car->State.BodyMatrix.v0.x
                * car->TheTrackPathCoordinate.PathDirection.x
          + car->State.BodyMatrix.v0.y
                * car->TheTrackPathCoordinate.PathDirection.y;
    along = (along < 0.0f) ? 0.0f : along;
    speed = speed * along;
    speed = (speed < RollingResetSpeed) ? speed : RollingResetSpeed;

    // A cop reset faces whichever way the cop manager says.
    if (pCopManager != NULL && car->pCarTypeInfo->UsageType == 1
        && gCopManagerGetResetDirectionFn != NULL)
        direction = gCopManagerGetResetDirectionFn(pCopManager);

    route = car_get_route(d->pCar, 1);
    point = car_get_route_point(d->pCar, 1);
    if (gCarResetToRoutePointFn != NULL)
        gCarResetToRoutePointFn(d->pCar, route, point, speed, 1, direction);

    if (gPlayerSelectedResetFn != NULL)
        gPlayerSelectedResetFn(pl);
}

// ---------------------------------------------------------- the horn

// Car+2056 as retail reads and writes it, a word: CopLights and the three
// bytes after.
static int cop_lights_word(const Car *car)
{
    const uint8_t *p = (const uint8_t *)car + offsetof(Car, CopLights);

    return (p[0] | p[1] | p[2] | p[3]) != 0;
}

static void set_cop_lights(Car *car, int8_t v)
{
    car->CopLights = v;
    memset(car->_hole2025, 0, sizeof car->_hole2025);
}

void realdriver_joy_honk_horn(JoystickPort port, JoyEvent ev, uint8_t value,
                              void *obj)
{
    RealDriver        *d   = (RealDriver *)obj;
    Car               *car = d->pCar;
    const CarTypeInfo *ti  = car->pCarTypeInfo;

    (void)port; (void)ev;

    if (value == 0) {
        call_void_slot(d, CARDRIVER_VT_STOP_HONK_HORN);
        // Retail's: a racer's headlights go off with the horn.
        if (ti->UsageType != 1)
            car->HeadlightsState = 0;
        return;
    }

    call_void_slot(d, CARDRIVER_VT_START_HONK_HORN);

    if (gCancelTuningDrivingLinesFn != NULL)
        gCancelTuningDrivingLinesFn();

    // Retail's: a racer's horn holds its headlights on (the demo's did
    // nothing more). A cop car's horn button is its lights and siren.
    if (ti->UsageType != 1) {
        car->HeadlightsState = 1;
        return;
    }

    if (RaceParametersBeACop) {
        if (gCopManagerBeACopToggleSirenAndLightsFn != NULL)
            gCopManagerBeACopToggleSirenAndLightsFn(pCopManager);
        return;
    }

    // Retail's reads CopLights as a word and turns the lights on at 2, the
    // fast flash (the demo's tested a byte and stored 1).
    if (!cop_lights_word(car)) {
        car->TheSirenMode = SIREN_MODE_01;
        set_cop_lights(car, 2);
    } else {
        set_cop_lights(car, 0);
        car->TheSirenMode = SIREN_MODE_NONE;
    }
}

void realdriver_start_honk_horn(RealDriver *d)
{
    Car *car = d->pCar;

    // A cop's horn makes no sound here; the siren is its sound.
    if (car->pCarTypeInfo->UsageType != 1 && car->pBaseCarSound != NULL
        && gBaseCarSoundStartHonkHornFn != NULL)
        gBaseCarSoundStartHonkHornFn(car->pBaseCarSound);

    // Retail's jumps on to Chopper.obj's 0x001ead40 where the demo's went
    // to HandyDebuggingFunction, an empty one: Easter egg 5's attack.
    if (gChopperHonkAttackFn != NULL)
        gChopperHonkAttackFn();
}

void realdriver_stop_honk_horn(RealDriver *d)
{
    Car *car = d->pCar;

    if (car->pCarTypeInfo->UsageType != 1 && car->pBaseCarSound != NULL
        && gBaseCarSoundStopHonkHornFn != NULL)
        gBaseCarSoundStopHonkHornFn(car->pBaseCarSound);
}

// --------------------------------------------------------- the nitro

void realdriver_joy_nitro_boost(JoystickPort port, JoyEvent ev,
                                uint8_t value, void *obj)
{
    RealDriver *d = (RealDriver *)obj;

    (void)port; (void)ev;

    if (value == 0)
        return;

    // Only a cop, and only in Be A Cop, has a nitro button.
    if (d->pCar->pCarTypeInfo->UsageType != 1)
        return;
    if (!RaceParametersBeACop)
        return;
    if (!realdriver_nitro_available(d))
        return;

    d->Base.NitroFlag   = 1;   // the UsageType still in s1
    d->LastNitroRequest = WorldTimer;
}

// LastNitroRequest is a WorldTimer tick, 4000 to the second (0.00025,
// 0x3983126f), with 0 and INT_MAX as "never". The subtraction is `subu`
// and wraps; cvt.s.w reads the result signed.
static int32_t nitro_valid(const RealDriver *d)
{
    return d->LastNitroRequest != 0 && d->LastNitroRequest != 0x7fffffff;
}

static float nitro_age(const RealDriver *d)
{
    return (float)(int32_t)((uint32_t)WorldTimer
                            - (uint32_t)d->LastNitroRequest) * 0.00025f;
}

int32_t realdriver_nitro_was_active(RealDriver *d)
{
    // Active as of the frame before: the age less this frame's time.
    float f = nitro_age(d) - WorldTimeElapsed;

    if (!nitro_valid(d))
        return 0;
    return 0.0f <= f && f < NitrousActiveTime;
}

int32_t realdriver_nitro_active(RealDriver *d)
{
    if (!nitro_valid(d))
        return 0;
    return nitro_age(d) < NitrousActiveTime;
}

int32_t realdriver_nitro_available(RealDriver *d)
{
    Player *pl = d->pCar->pPlayer;

    // Retail's: none while the car's player watches a NIS.
    if (pl != NULL && gPlayerIsNisPlayingFn != NULL
            && gPlayerIsNisPlayingFn(pl))
        return 0;
    if (!nitro_valid(d))
        return 1;
    return NitrousActiveTime + NitrousRechargeTime <= nitro_age(d);
}

// ----------------------------------------------------------- the replay

void realdriver_do_snapshot(RealDriver *d, ReplaySnapshot *s)
{
    // Retail 0x0013aeb8. ForcedEBrakeStop goes after ManualTransmission,
    // not in its place between them. The port's low byte comes back
    // unsigned (`move t0,zero`).
    ReplaySnapshot_BeginNamedSection(s, "RealDriver");
    ReplaySnapshot_MoveData(s, &d->Port, 1, 4, 0);
    ReplaySnapshot_MoveInt(s, &d->StartLineState, 1);
    ReplaySnapshot_MoveInt(s, &d->StopRightNow, 1);
    ReplaySnapshot_MoveBool(s, &d->bPowerSlide, 1);
    ReplaySnapshot_MoveInt(s, &d->ManualTransmission, 1);
    ReplaySnapshot_MoveFloat(s, &d->ForcedEBrakeStop);
    ReplaySnapshot_MoveUChar(s, &d->JoySteeringDigital, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoySteeringAnalog, 1);
    ReplaySnapshot_MoveFloat(s, &d->SteeringInput);
    ReplaySnapshot_MoveUChar(s, &d->JoyThrottleDigital, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyThrottleAnalog, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyThrottleAnalogAlternate, 1);
    ReplaySnapshot_MoveFloat(s, &d->ThrottleInput);
    ReplaySnapshot_MoveUChar(s, &d->JoyBrakeDigital, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyBrakeAnalog, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyBrakeAnalogAlternate, 1);
    ReplaySnapshot_MoveFloat(s, &d->BrakeInput);
    ReplaySnapshot_MoveUChar(s, &d->JoyReverseDigital, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyReverseAnalog, 1);
    ReplaySnapshot_MoveFloat(s, &d->ReverseInput);
    ReplaySnapshot_MoveUChar(s, &d->JoyEBrakeDigital, 1);
    ReplaySnapshot_MoveUChar(s, &d->JoyEBrakeAnalog, 1);
    ReplaySnapshot_MoveFloat(s, &d->EBrakeInput);
    ReplaySnapshot_MoveTimer(s, &d->LastNitroRequest);
    ReplaySnapshot_MoveBool(s, &d->Reversing, 1);
    cardriver_do_snapshot(&d->Base, s);
    ReplaySnapshot_EndNamedSection(s);
}

// ------------------------------------------------------------ the table

#define E(f) { 0, 0, (VtFn)(f) }

// _vt$10RealDriver, 0x00292a70.
static const VtEntry realdriver_vt[CARDRIVER_VT_ENTRIES] = {
    { 0, 0, NULL },
    E(realdriver_destroy),                  //   8  0x00139058
    E(realdriver_drive),                    //  16  0x00139600
    E(realdriver_do_snapshot),              //  24  0x001390b8, retail 0x0013aeb8
    E(realdriver_add_joy_handlers),         //  32  0x00139288
    E(realdriver_remove_joy_handlers),      //  40  0x00139458
    E(realdriver_set_low_gear),             //  48  0x001395d8
    E(realdriver_set_desired_speed),        //  56  0x0013ac28
    E(cardriver_set_target),                //  64  0x00134d50
    E(cardriver_set_steer_to_point),        //  72  0x00134d48
    E(realdriver_get_driver_number),        //  80  0x0013ac18
    E(realdriver_start_honk_horn),          //  88  0x0013a558
    E(realdriver_stop_honk_horn),           //  96  0x0013a598
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

void realdriver_install_vtable(void)
{
    vt_install(REALDRIVER_VTABLE, realdriver_vt, CARDRIVER_VT_ENTRIES);
}
