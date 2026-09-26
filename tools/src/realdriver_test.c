// Harness for tools/realdriver_check.py: runs the checker's op script on the
// port and prints what the model prints for the image. The ops, their
// arguments and every line's format are the checker's; this file only
// carries them out. See the checker's docstring for the stand-ins, the seam
// mask and why every pointer prints as a label.
//
//     realdriver_test ops.bin > out.txt
//
// The world clock's globals are defined here rather than linked from
// realtime.c, which would bring the joylog in behind it. The loop counter
// starts at the image's 100000.

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "bmem.h"
#include "car.h"
#include "carcontroller.h"
#include "cardriver.h"
#include "carstate.h"
#include "cartypeinfo.h"
#include "copmanager.h"
#include "drivetarget.h"
#include "joyevent.h"
#include "joystick.h"
#include "player.h"
#include "race.h"
#include "realdriver.h"
#include "replay.h"
#include "table.h"
#include "trackroute.h"
#include "vtable.h"
#include "world.h"

int32_t WorldTimer;
int32_t WorldTimeFrames;
float   WorldTimeElapsed;
int32_t WorldLoopCounter = 100000;

enum {
    OP_TAG, OP_FILL, OP_INIT, OP_DUMP, OP_CARF, OP_DRVF, OP_GLOB, OP_PTR,
    OP_ANSWER, OP_MASK, OP_CALL, OP_HANDLER, OP_VT, OP_TABLE, OP_INV,
    OP_STATIC, OP_TARGET
};

enum {
    F_DESTROY, F_DRIVE, F_ADD, F_REMOVE, F_DISABLE_SL, F_ENABLE_SL,
    F_SET_MANUAL, F_SET_LOW_GEAR, F_FORCE_EBRAKE, F_RESET_JOY, F_DO_STEERING,
    F_DTBR, F_DO_BRAKE, F_NITRO_WAS, F_NITRO_ACTIVE, F_NITRO_AVAIL,
    F_START_HONK, F_STOP_HONK, F_GET_PORT, F_GET_DRIVER_NUMBER,
    F_SET_DESIRED_SPEED, F_SET_PREDICTED_TARGET, F_SET_STOP, F_SET_PORT,
    F_GET_CAR
};

enum { P_PLAYER, P_COP, P_SOUND, P_REPLAY };
enum { A_PLUGGED, A_WHEEL, A_STIFF, A_ALLOWED, A_DIRECTION, A_COUNT };

enum {
    S_ROUTE_POINT, S_CANCEL_TUNING, S_BLUR_ON, S_BLUR_OFF, S_BLUR_ALPHA,
    S_REPLAY_EVENT, S_REROUTE, S_ALLOWED_RESET, S_SELECTED_RESET,
    S_RESET_DIRECTION, S_SIREN_TOGGLE, S_RESET_TO_POINT, S_HONK_START,
    S_HONK_STOP
};

#define CTRL_VT   0x01E03200u
#define TGT_SIZE  528

// ------------------------------------------------------------ the script

static int32_t *words_in;
static size_t   nwords_in;
static size_t   rd;

static int32_t next(void)
{
    if (rd >= nwords_in) {
        fprintf(stderr, "ops: ran off the end\n");
        exit(2);
    }
    return words_in[rd++];
}

static char **read_strings(int32_t *count)
{
    int32_t n = next();
    char  **out = calloc((size_t)n + 1, sizeof(char *));
    int32_t i;

    for (i = 0; i < n; i++) {
        int32_t len = next();
        int32_t k;

        out[i] = malloc((size_t)len + 1);
        for (k = 0; k < len; k++)
            out[i][k] = (char)next();
        out[i][len] = 0;
    }
    *count = n;
    return out;
}

static float fbits(int32_t b)
{
    float    f;
    uint32_t u = (uint32_t)b;

    memcpy(&f, &u, 4);
    return f;
}

static uint32_t bitsf(float f)
{
    uint32_t u;

    memcpy(&u, &f, 4);
    return u;
}

// ---------------------------------------------------------- the objects

static RealDriver      drv[2];
static Car             car;
static CarTypeInfo     cti;
static struct Player   player;
static CarController   ctl;
static DriveTarget     tgt;
static ReplayManager   rm_obj;
static TrackRoute      route_obj;
static TrackRoutePoint point_obj;
static char            cop_obj[16];
static char            snd_obj[16];

static uint32_t mask;
static int32_t  ans[A_COUNT];

static const char *label(const void *p)
{
    if (p == NULL)                          return "null";
    if (p == &car)                          return "car";
    if (p == &player)                       return "pl";
    if (p == (void *)cop_obj)               return "cop";
    if (p == &rm_obj)                       return "rm";
    if (p == (void *)snd_obj)               return "snd";
    if (p == &route_obj)                    return "route";
    if (p == &point_obj)                    return "point";
    if (p == &drv[0])                       return "d0";
    if (p == &drv[1])                       return "d1";
    if (p == &car.State.Position)           return "pos";
    if (p == &car.State.Velocity)           return "vel";
    if (p == &ctl)                          return "ctl";
    if (p == &tgt)                          return "tgt";
    if (p == &cti)                          return "cti";
    return "?";
}

static uint32_t fnv(const void *p, size_t n)
{
    const uint8_t *b = p;
    uint32_t       h = 0x811c9dc5u;
    size_t         i;

    for (i = 0; i < n; i++)
        h = (h ^ b[i]) * 0x01000193u;
    return h;
}

// ------------------------------------------------------- the pad layer

static const char *hname(JoyHandler fn)
{
    if (fn == realdriver_joy_steer)       return "steer";
    if (fn == realdriver_joy_throttle)    return "throttle";
    if (fn == realdriver_joy_reverse)     return "reverse";
    if (fn == realdriver_joy_brake)       return "brake";
    if (fn == realdriver_joy_ebrake)      return "ebrake";
    if (fn == realdriver_joy_shift_up)    return "shiftup";
    if (fn == realdriver_joy_shift_down)  return "shiftdown";
    if (fn == realdriver_joy_reset_car)   return "reset";
    if (fn == realdriver_joy_honk_horn)   return "honk";
    if (fn == realdriver_joy_nitro_boost) return "nitro";
    return "?";
}

void AddJoyHandler(JoystickPort port, JoyEvent ev, JoyHandler fn, void *obj)
{
    printf("  joy add port %d ev %d fn %s obj %s\n", (int)port, (int)ev,
           hname(fn), label(obj));
}

void RemoveJoyHandler(JoystickPort port, JoyEvent ev)
{
    printf("  joy remove port %d ev %d\n", (int)port, (int)ev);
}

int32_t IsJoystickPluggedIn(JoystickPort port)
{
    printf("  joy plugged %d -> %d\n", (int)port, (int)ans[A_PLUGGED]);
    return ans[A_PLUGGED];
}

int32_t IsJoystickTypeWheel(JoystickPort port)
{
    printf("  joy wheel %d -> %d\n", (int)port, (int)ans[A_WHEEL]);
    return ans[A_WHEEL];
}

int32_t DoesJoystickHaveStiffThrottle(JoystickPort port)
{
    printf("  joy stiff %d -> %d\n", (int)port, (int)ans[A_STIFF]);
    return ans[A_STIFF];
}

// ----------------------------------------------------------- the seams

static void s_route_point(const bVector3 *pos, const bVector3 *vel, float z,
                          int32_t flag, int32_t car_class)
{
    printf("  seam route-point %s %s z %08x %d %d\n", label(pos), label(vel),
           bitsf(z), (int)flag, (int)car_class);
}

static void s_cancel_tuning(void)
{
    printf("  seam cancel-tuning -\n");
}

static void s_blur_on(int32_t view)
{
    printf("  seam blur-on %d\n", (int)view);
}

static void s_blur_off(int32_t view)
{
    printf("  seam blur-off %d\n", (int)view);
}

static void s_blur_alpha(int32_t view, float from, float to)
{
    printf("  seam blur-alpha %d %08x %08x\n", (int)view, bitsf(from),
           bitsf(to));
}

static void s_replay_event(struct ReplayManager *rm, float weight,
                           const char *name)
{
    printf("  seam replay-event %s %08x %s\n", label(rm), bitsf(weight),
           name ? name : "(null)");
}

static void s_reroute(struct Player *p, JoystickPort port, JoyEvent ev,
                      uint8_t value)
{
    printf("  seam reroute %s %d %d %d\n", label(p), (int)port, (int)ev,
           (int)value);
}

static int32_t s_allowed_reset(struct Player *p)
{
    printf("  seam allowed-reset %s -> %d\n", label(p), (int)ans[A_ALLOWED]);
    return ans[A_ALLOWED];
}

static void s_selected_reset(struct Player *p)
{
    printf("  seam selected-reset %s\n", label(p));
}

static float s_reset_direction(struct tCopManager *m)
{
    printf("  seam reset-direction %s -> %08x\n", label(m),
           (uint32_t)ans[A_DIRECTION]);
    return fbits(ans[A_DIRECTION]);
}

static void s_siren_toggle(struct tCopManager *m)
{
    printf("  seam siren-toggle %s\n", label(m));
}

static void s_reset_to_point(struct Car *c, struct TrackRoute *r,
                             struct TrackRoutePoint *p, float speed,
                             int32_t flag, float direction)
{
    printf("  seam reset-to-point %s %s %s %08x %d %08x\n", label(c),
           label(r), label(p), bitsf(speed), (int)(flag & 0xff),
           bitsf(direction));
}

static void s_honk_start(struct BaseCarSound *s)
{
    printf("  seam honk-start %s\n", label(s));
}

static void s_honk_stop(struct BaseCarSound *s)
{
    printf("  seam honk-stop %s\n", label(s));
}

#define ON(bit) ((mask >> (bit)) & 1u)

static void set_mask(uint32_t m)
{
    mask = m;
    gMaybeAddTrackRoutePointFn   = ON(S_ROUTE_POINT) ? s_route_point : NULL;
    gCancelTuningDrivingLinesFn  = ON(S_CANCEL_TUNING) ? s_cancel_tuning
                                                       : NULL;
    gRadialBlurOnFn              = ON(S_BLUR_ON) ? s_blur_on : NULL;
    gRadialBlurOffFn             = ON(S_BLUR_OFF) ? s_blur_off : NULL;
    gRadialBlurAlphaFn           = ON(S_BLUR_ALPHA) ? s_blur_alpha : NULL;
    gReplayRegisterInterestingEventFn = ON(S_REPLAY_EVENT) ? s_replay_event
                                                           : NULL;
    gPlayerRerouteJoyEventFn     = ON(S_REROUTE) ? s_reroute : NULL;
    gPlayerIsAllowedToResetFn    = ON(S_ALLOWED_RESET) ? s_allowed_reset
                                                       : NULL;
    gPlayerSelectedResetFn       = ON(S_SELECTED_RESET) ? s_selected_reset
                                                        : NULL;
    gCopManagerGetResetDirectionFn = ON(S_RESET_DIRECTION) ? s_reset_direction
                                                           : NULL;
    gCopManagerBeACopToggleSirenAndLightsFn = ON(S_SIREN_TOGGLE)
                                              ? s_siren_toggle : NULL;
    gCarResetToRoutePointFn      = ON(S_RESET_TO_POINT) ? s_reset_to_point
                                                        : NULL;
    gBaseCarSoundStartHonkHornFn = ON(S_HONK_START) ? s_honk_start : NULL;
    gBaseCarSoundStopHonkHornFn  = ON(S_HONK_STOP) ? s_honk_stop : NULL;
}

// ------------------------------------------------------ the controller

static TrackRoute *ctl_route(void *self)
{
    printf("  ctl route %s\n", label(self));
    return &route_obj;
}

static TrackRoutePoint *ctl_point(void *self)
{
    printf("  ctl point %s\n", label(self));
    return &point_obj;
}

static VtEntry ctl_vt[CARCONTROLLER_VT_ENTRIES];

static void free_hook(void *p)
{
    printf("  free %s\n", label(p));
}

static void *malloc_hook(int size, const char *name, int flags, int pool)
{
    (void)flags; (void)pool;
    fprintf(stderr, "unexpected bMalloc %d %s\n", size, name);
    exit(3);
}

// ------------------------------------------------------------- the fields

static void set_carf(int32_t field, int32_t v)
{
    float f = fbits(v);

    switch (field) {
    case 0:  car.DriverNumber = (int16_t)v; break;
    case 1:  car.TheMovementMode = (MovementMode)v; break;
    case 2:  car.State.Position.x = f; break;
    case 3:  car.State.Position.y = f; break;
    case 4:  car.State.Position.z = f; break;
    case 5:  car.State.Velocity.x = f; break;
    case 6:  car.State.Velocity.y = f; break;
    case 7:  car.State.Velocity.z = f; break;
    case 8:  car.State.BodyMatrix.v0.x = f; break;
    case 9:  car.State.BodyMatrix.v0.y = f; break;
    case 10: car.State.Angle = (uint16_t)v; break;
    case 11: car.State.ForwardSpeed = f; break;
    case 12: car.State.VelocityMagnitude = f; break;
    case 13: car.State.CurrentGear = v; break;
    case 14: car.State.Throttle = f; break;
    case 15: car.TheTrackPathCoordinate.PathDirection.x = f; break;
    case 16: car.TheTrackPathCoordinate.PathDirection.y = f; break;
    case 17: car.CopLights = (int8_t)v; break;
    case 18: car.TheSirenMode = (SirenMode)v; break;
    case 19: cti.CarClass = v; break;
    case 20: cti.DriveTrain.NumGears = v; break;
    case 21: cti.Control.Steering = f; break;
    case 22: cti.UsageType = v; break;
    case 23: player.PlayerNumber = v; break;
    default:
        fprintf(stderr, "carf %d\n", (int)field);
        exit(2);
    }
}

static void set_drvf(RealDriver *d, int32_t field, int32_t v)
{
    float f = fbits(v);

    switch (field) {
    case 0:  d->Base.Steering = (uint16_t)v; break;
    case 1:  d->Base.DesiredGear = v; break;
    case 2:  d->Base.SportGear = v; break;
    case 3:  d->Port = v; break;
    case 4:  d->HandlersAdded = v; break;
    case 5:  d->StartLineState = v; break;
    case 6:  d->StopRightNow = v; break;
    case 7:  d->ForcedEBrakeStop = v; break;
    case 8:  d->bPowerSlide = v; break;
    case 9:  d->ManualTransmission = v; break;
    case 10: d->SteeringInput = f; break;
    case 11: d->ThrottleInput = f; break;
    case 12: d->BrakeInput = f; break;
    case 13: d->EBrakeInput = f; break;
    case 14: d->LastNitroRequest = v; break;
    case 15: d->Reversing = v; break;
    case 16: d->JoySteeringDigital = (uint8_t)v; break;
    case 17: d->JoySteeringAnalog = (uint8_t)v; break;
    case 18: d->JoyThrottleDigital = (uint8_t)v; break;
    case 19: d->JoyThrottleAnalog = (uint8_t)v; break;
    case 20: d->JoyThrottleAnalogAlternate = (uint8_t)v; break;
    case 21: d->JoyBrakeDigital = (uint8_t)v; break;
    case 22: d->JoyBrakeAnalog = (uint8_t)v; break;
    case 23: d->JoyBrakeAnalogAlternate = (uint8_t)v; break;
    case 24: d->JoyReverseDigital = (uint8_t)v; break;
    case 25: d->JoyReverseAnalog = (uint8_t)v; break;
    case 26: d->JoyEBrakeDigital = (uint8_t)v; break;
    case 27: d->JoyEBrakeAnalog = (uint8_t)v; break;
    case 28: d->Base.NitroFlag = v; break;
    case 29: d->Base.Throttle = f; break;
    case 30: d->Base.Brake = f; break;
    case 31: d->Base.EBrake = f; break;
    case 32: d->Base._vtable = (uint32_t)v; break;
    default:
        fprintf(stderr, "drvf %d\n", (int)field);
        exit(2);
    }
}

static void set_glob(int32_t id, int32_t v)
{
    float f = fbits(v);

    switch (id) {
    case 0:  WorldTimer = v; break;
    case 1:  WorldTimeElapsed = f; break;
    case 2:  WorldLoopCounter = v; break;
    case 3:  RaceParametersBeACop = v; break;
    case 4:  RollingResetSpeed = f; break;
    case 5:  PowerSlideYawCoef = f; break;
    case 6:  SteeringSpeed = f; break;
    case 7:  SteeringReturnFactor = f; break;
    case 8:  CounterSteerFadeStart = f; break;
    case 9:  CounterSteerFadeEnd = f; break;
    case 10: MaxSpeedForReverse = f; break;
    case 11: MinSpeedForThrottle = f; break;
    case 12: MinSpeedForThrottleWhenReversing = f; break;
    case 13: BrakingSpeed = f; break;
    case 14: UnBrakingSpeed = f; break;
    case 15: NitrousActiveTime = f; break;
    case 16: NitrousRechargeTime = f; break;
    default:
        fprintf(stderr, "glob %d\n", (int)id);
        exit(2);
    }
}

// ---------------------------------------------------------- the prints

static const char *vtname(uint32_t v, char *buf)
{
    if (v == REALDRIVER_VTABLE)
        return "rd";
    if (v == CARDRIVER_VTABLE)
        return "cd";
    sprintf(buf, "%08x", (unsigned)v);
    return buf;
}

static void dump(int slot)
{
    RealDriver *d = &drv[slot];
    char        buf[16];

    printf("d%d st %04x th %08x br %08x eb %08x dg %d sg %d ni %d vt %s "
           "car %s port %d ha %d sl %d stop %d feb %d ps %d mt %d js %d %d "
           "si %08x jt %d %d %d ti %08x jb %d %d %d bi %08x jr %d %d "
           "ri %08x je %d %d ei %08x lnr %d rev %d tgt %08x | cth %08x "
           "cl %d sm %d psyc %08x\n",
           slot, (unsigned)d->Base.Steering, bitsf(d->Base.Throttle),
           bitsf(d->Base.Brake), bitsf(d->Base.EBrake),
           (int)d->Base.DesiredGear, (int)d->Base.SportGear,
           (int)d->Base.NitroFlag, vtname(d->Base._vtable, buf),
           label(d->pCar), (int)d->Port, (int)d->HandlersAdded,
           (int)d->StartLineState, (int)d->StopRightNow,
           (int)d->ForcedEBrakeStop, (int)d->bPowerSlide,
           (int)d->ManualTransmission, d->JoySteeringDigital,
           d->JoySteeringAnalog, bitsf(d->SteeringInput),
           d->JoyThrottleDigital, d->JoyThrottleAnalog,
           d->JoyThrottleAnalogAlternate, bitsf(d->ThrottleInput),
           d->JoyBrakeDigital, d->JoyBrakeAnalog, d->JoyBrakeAnalogAlternate,
           bitsf(d->BrakeInput), d->JoyReverseDigital, d->JoyReverseAnalog,
           bitsf(d->ReverseInput), d->JoyEBrakeDigital, d->JoyEBrakeAnalog,
           bitsf(d->EBrakeInput), (int)d->LastNitroRequest,
           (int)d->Reversing, fnv(&d->Base.MyDriveTarget, TGT_SIZE),
           bitsf(car.State.Throttle), (int)car.CopLights,
           (int)car.TheSirenMode, bitsf(PowerSlideYawCoef));
}

static const struct {
    VtFn        fn;
    const char *name;
} fnames[] = {
#define N(f) { (VtFn)(f), #f }
    N(realdriver_destroy), N(realdriver_drive),
    N(realdriver_add_joy_handlers), N(realdriver_remove_joy_handlers),
    N(realdriver_set_low_gear), N(realdriver_set_desired_speed),
    N(cardriver_set_target), N(cardriver_set_steer_to_point),
    N(realdriver_get_driver_number), N(realdriver_start_honk_horn),
    N(realdriver_stop_honk_horn), N(cardriver_is_honking),
    N(cardriver_max_speed_to_target), N(cardriver_zero_steering_memory),
    N(cardriver_clear_steering_memory), N(cardriver_get_desired_speed),
    N(cardriver_get_desired_time_to_speed), N(cardriver_set_physics_mode),
    N(cardriver_get_steer_to_point),
#undef N
};

static const char *portname(VtFn fn)
{
    size_t i;

    if (fn == NULL)
        return "null";
    for (i = 0; i < sizeof fnames / sizeof fnames[0]; i++)
        if (fnames[i].fn == fn)
            return fnames[i].name;
    return "?";
}

static void print_static(void)
{
    static const struct { const char *name; const float *p; } g[] = {
        { "RollingResetSpeed", &RollingResetSpeed },
        { "PowerSlideYawCoef", &PowerSlideYawCoef },
        { "SteeringSpeed", &SteeringSpeed },
        { "SteeringReturnFactor", &SteeringReturnFactor },
        { "CounterSteerFadeStart", &CounterSteerFadeStart },
        { "CounterSteerFadeEnd", &CounterSteerFadeEnd },
        { "MaxSpeedForReverse", &MaxSpeedForReverse },
        { "MinSpeedForThrottle", &MinSpeedForThrottle },
        { "MinSpeedForThrottleWhenReversing",
          &MinSpeedForThrottleWhenReversing },
        { "BrakingSpeed", &BrakingSpeed },
        { "UnBrakingSpeed", &UnBrakingSpeed },
        { "NitrousActiveTime", &NitrousActiveTime },
        { "NitrousRechargeTime", &NitrousRechargeTime },
    };
    const Table *tabs[7] = {
        &SteeringWheelRangeTable, &SteeringRangeTable, &SteeringSpeedTable,
        &SteeringCurveTable, &SteeringInputTable, &YawCoeffTable,
        &BrakingCurve,
    };
    const VtEntry *vt;
    size_t i;
    int    k, n, count;

    for (i = 0; i < sizeof g / sizeof g[0]; i++)
        printf("glob %s %08x\n", g[i].name, bitsf(*g[i].p));
    for (k = 0; k < 7; k++) {
        const Table *t = tabs[k];

        printf("table %d n %d min %08x max %08x mul %08x data", k,
               (int)t->NumEntries, bitsf(t->MinArg), bitsf(t->MaxArg),
               bitsf(t->IndexMultiplier));
        for (n = 0; n < t->NumEntries; n++)
            printf("%s%08x", n ? " " : " ", bitsf(t->pTable[n]));
        printf("\n");
    }
    vt = vt_table(REALDRIVER_VTABLE, &count);
    for (k = 1; k < 21; k++) {
        if (k < count)
            printf("vt %d %d %d %s\n", 8 * k, (int)vt[k].delta,
                   (int)vt[k].index, portname(vt[k].fn));
        else
            printf("vt %d missing\n", 8 * k);
    }
}

// ------------------------------------------------------------ the calls

static const Table *table_of(int k)
{
    switch (k) {
    case 0: return &SteeringWheelRangeTable;
    case 1: return &SteeringRangeTable;
    case 2: return &SteeringSpeedTable;
    case 3: return &SteeringCurveTable;
    case 4: return &SteeringInputTable;
    case 5: return &YawCoeffTable;
    default: return &BrakingCurve;
    }
}

static void call(int32_t fn, int slot, int32_t a, int32_t b, int32_t c)
{
    RealDriver *d = &drv[slot];

    switch (fn) {
    case F_DESTROY:       realdriver_destroy(d, a); break;
    case F_DRIVE:         realdriver_drive(d, fbits(a)); break;
    case F_ADD:           realdriver_add_joy_handlers(d); break;
    case F_REMOVE:        realdriver_remove_joy_handlers(d); break;
    case F_DISABLE_SL:    realdriver_disable_start_line_state(d); break;
    case F_ENABLE_SL:     realdriver_enable_start_line_state(d); break;
    case F_SET_MANUAL:    realdriver_set_manual_transmission(d, a); break;
    case F_SET_LOW_GEAR:  realdriver_set_low_gear(d); break;
    case F_FORCE_EBRAKE:  realdriver_force_ebrake_stop(d, a); break;
    case F_RESET_JOY:     realdriver_reset_joy_values(d); break;
    case F_DO_STEERING:   realdriver_do_steering(d, fbits(a), b); break;
    case F_DTBR:          realdriver_do_throttle_brake_reverse(d, fbits(a));
                          break;
    case F_DO_BRAKE:      realdriver_do_brake(d, fbits(a)); break;
    case F_NITRO_WAS:     printf("ret %d\n", (int)realdriver_nitro_was_active(d));
                          break;
    case F_NITRO_ACTIVE:  printf("ret %d\n", (int)realdriver_nitro_active(d));
                          break;
    case F_NITRO_AVAIL:   printf("ret %d\n", (int)realdriver_nitro_available(d));
                          break;
    case F_START_HONK:    realdriver_start_honk_horn(d); break;
    case F_STOP_HONK:     realdriver_stop_honk_horn(d); break;
    case F_GET_PORT:      printf("ret %d\n", (int)realdriver_get_port(d)); break;
    case F_GET_DRIVER_NUMBER:
        printf("ret %d\n", (int)realdriver_get_driver_number(d));
        break;
    case F_SET_DESIRED_SPEED:
        realdriver_set_desired_speed(d, fbits(a), fbits(b), c);
        break;
    case F_SET_PREDICTED_TARGET: realdriver_set_predicted_target(d, &tgt); break;
    case F_SET_STOP:      realdriver_set_stop_right_now(d, a); break;
    case F_SET_PORT:      realdriver_set_joystick_port(d, a); break;
    case F_GET_CAR:       printf("ret %s\n", label(realdriver_get_car(d))); break;
    default:
        fprintf(stderr, "call %d\n", (int)fn);
        exit(2);
    }
}

typedef void (*JoyFn)(JoystickPort, JoyEvent, uint8_t, void *);

static void handler(int slot, int32_t h, int32_t port, int32_t ev,
                    int32_t value)
{
    static const JoyFn fns[10] = {
        realdriver_joy_steer, realdriver_joy_throttle,
        realdriver_joy_reverse, realdriver_joy_brake, realdriver_joy_ebrake,
        realdriver_joy_shift_up, realdriver_joy_shift_down,
        realdriver_joy_reset_car, realdriver_joy_honk_horn,
        realdriver_joy_nitro_boost,
    };

    fns[h](port, ev, (uint8_t)value, &drv[slot]);
}

typedef void    (*VVoid)(void *);
typedef void    (*VInt)(void *, int32_t);
typedef void    (*VFloat)(void *, float);
typedef void    (*VSpeed)(void *, float, float, int32_t);
typedef void    (*VPtr)(void *, void *);
typedef int32_t (*RInt)(void *);
typedef float   (*RFloat)(void *);
typedef float   (*RFloatPtr)(void *, void *);
typedef void   *(*RPtr)(void *);

static void vcall(int slot, int32_t vslot, int32_t a, int32_t f1, int32_t f2)
{
    RealDriver    *d = &drv[slot];
    const VtEntry *e = vt_slot(d->Base._vtable, vslot);
    void          *self = vt_this(d, e);

    switch (vslot) {
    case 8:
    case 152:
        ((VInt)e->fn)(self, a);
        break;
    case 16:
        ((VFloat)e->fn)(self, fbits(f1));
        break;
    case 56:
        ((VSpeed)e->fn)(self, fbits(f1), fbits(f2), a);
        break;
    case 64:
    case 72:
        ((VPtr)e->fn)(self, &tgt);
        break;
    case 80:
    case 104:
        printf("vret %d\n", (int)((RInt)e->fn)(self));
        break;
    case 112:
        printf("vret %08x\n", bitsf(((RFloatPtr)e->fn)(self, &tgt)));
        break;
    case 136:
    case 144:
        printf("vret %08x\n", bitsf(((RFloat)e->fn)(self)));
        break;
    case 160:
        printf("vret %s\n", label(((RPtr)e->fn)(self)));
        break;
    default:
        ((VVoid)e->fn)(self);
        break;
    }
}

// ---------------------------------------------------------------- the loop

int main(int argc, char **argv)
{
    FILE    *fh;
    long     size;
    char   **tags;
    int32_t  ntags;
    size_t   end;

    if (argc < 2) {
        fprintf(stderr, "usage: realdriver_test ops.bin\n");
        return 2;
    }
    fh = fopen(argv[1], "rb");
    if (fh == NULL) {
        perror(argv[1]);
        return 2;
    }
    fseek(fh, 0, SEEK_END);
    size = ftell(fh);
    fseek(fh, 0, SEEK_SET);
    words_in = malloc((size_t)size);
    nwords_in = (size_t)size / 4;
    if (fread(words_in, 4, nwords_in, fh) != nwords_in) {
        fprintf(stderr, "short read\n");
        return 2;
    }
    fclose(fh);

    tags = read_strings(&ntags);
    end = (size_t)next();
    end += rd;

    vt_reset();
    cardriver_install_vtables();
    realdriver_install_vtable();
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE)].fn = (VtFn)ctl_route;
    ctl_vt[VT_SLOT(CARCONTROLLER_VT_GET_CURRENT_ROUTE_POINT)].fn =
        (VtFn)ctl_point;
    vt_install(CTRL_VT, ctl_vt, CARCONTROLLER_VT_ENTRIES);
    bSetMemoryHooks(malloc_hook, free_hook);

    memset(&car, 0, sizeof car);
    memset(&cti, 0, sizeof cti);
    memset(&player, 0, sizeof player);
    car.pCarTypeInfo = &cti;
    car.pCarController = &ctl;
    ctl._vtable = CTRL_VT;
    set_mask(0x3fff);

    realdriver_static_init();

    while (rd < end) {
        int32_t op = next();

        switch (op) {
        case OP_TAG:
            printf("[%s]\n", tags[next()]);
            break;
        case OP_FILL: {
            int32_t slot = next(), byte = next();

            memset(&drv[slot], byte & 0xff, sizeof(RealDriver));
            break;
        }
        case OP_INIT:
            realdriver_init(&drv[next()], &car);
            break;
        case OP_DUMP:
            dump(next());
            break;
        case OP_CARF: {
            int32_t field = next(), v = next();

            set_carf(field, v);
            break;
        }
        case OP_DRVF: {
            int32_t slot = next(), field = next(), v = next();

            set_drvf(&drv[slot], field, v);
            break;
        }
        case OP_GLOB: {
            int32_t id = next(), v = next();

            set_glob(id, v);
            break;
        }
        case OP_PTR: {
            int32_t which = next(), on = next();

            switch (which) {
            case P_PLAYER: car.pPlayer = on ? &player : NULL; break;
            case P_COP:
                pCopManager = on ? (tCopManager *)(void *)cop_obj : NULL;
                break;
            case P_SOUND:
                car.pBaseCarSound = on ? (BaseCarSound *)(void *)snd_obj
                                       : NULL;
                break;
            default: pReplayManager = on ? &rm_obj : NULL; break;
            }
            break;
        }
        case OP_ANSWER: {
            int32_t which = next(), v = next();

            ans[which] = v;
            break;
        }
        case OP_MASK:
            set_mask((uint32_t)next());
            break;
        case OP_CALL: {
            int32_t fn = next(), slot = next();
            int32_t a = next(), b = next(), c = next();

            call(fn, slot, a, b, c);
            break;
        }
        case OP_HANDLER: {
            int32_t slot = next(), h = next(), port = next();
            int32_t ev = next(), v = next();

            handler(slot, h, port, ev, v);
            break;
        }
        case OP_VT: {
            int32_t slot = next(), vslot = next(), a = next();
            int32_t f1 = next(), f2 = next();

            vcall(slot, vslot, a, f1, f2);
            break;
        }
        case OP_TABLE: {
            int32_t k = next(), x = next();

            printf("tab %d get %08x -> %08x\n", (int)k, (uint32_t)x,
                   bitsf(table_get_value(table_of(k), fbits(x))));
            break;
        }
        case OP_INV: {
            int32_t k = next(), x = next();

            printf("tab %d inv %08x -> %08x\n", (int)k, (uint32_t)x,
                   bitsf(table_inverse_lookup(table_of(k), fbits(x))));
            break;
        }
        case OP_STATIC:
            print_static();
            break;
        case OP_TARGET: {
            int32_t  seed = next();
            uint8_t *b = (uint8_t *)&tgt;
            int      i;

            for (i = 0; i < TGT_SIZE; i++)
                b[i] = (uint8_t)(seed + 13 * i + (i >> 5));
            break;
        }
        default:
            fprintf(stderr, "op %d\n", (int)op);
            return 2;
        }
    }
    return 0;
}
