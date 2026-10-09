// realdriver -- RealDriver (RealDriver.obj, 0x00138f90 .. 0x0013ac60).
//
// The human's CarDriver. It holds the pad's view of the car -- one byte per
// digital and analog source for each of steering, throttle, brake, reverse
// and e-brake -- and turns it into CarDriver's input record once a frame:
// Drive runs DoThrottleBrakeReverse, then DoSteering, which is where the
// feel of the game's steering lives (the speed-dependent lock, the counter-
// steer and power-slide assist, the return-to-centre rate).
//
// Everything reaches it through JoyHandlers. AddJoyHandlers registers
// eleven handlers on seventeen events, JOY_EVENT_STEER (110) through
// JOY_EVENT_NITRO_BOOST (126), with the driver as the handler's object;
// the joystick layer calls them from GenerateJoyEvents.
//
// 640 bytes, type#2160: CarDriver's 560 and twenty-six fields after it.
// The vptr is CarDriver's, at 556.
//
// Ported but for DoSnapshot (0x001390b8), which needs ReplaySnapshot. Its
// fourteen calls into classes other tasks own go through the seams at the
// bottom of this header; see docs/formats/real-driver.md.

#ifndef REALDRIVER_H
#define REALDRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "cardriver.h"
#include "joyeventid.h"
#include "joystick.h"
#include "table.h"

struct Car;
struct Player;
struct TrackRoute;
struct TrackRoutePoint;
struct tCopManager;
struct BaseCarSound;
struct ReplayManager;

typedef struct RealDriver {
    CarDriver    Base;                        //   0
    struct Car  *pCar;                        // 560
    JoystickPort Port;                        // 564  the constructor stores -1
    int32_t      HandlersAdded;               // 568
    int32_t      StartLineState;              // 572
    int32_t      StopRightNow;                // 576
    float        ForcedEBrakeStop;            // 580  retail's seconds left
    int32_t      bPowerSlide;                 // 584  a bool stored as a word
    int32_t      ManualTransmission;          // 588  0 auto, 1 manual, 2 sport
    uint8_t      JoySteeringDigital;          // 592  128 is centred
    uint8_t      JoySteeringAnalog;           // 593
    uint8_t      _pad594[2];                  // 594
    float        SteeringInput;               // 596  -1 .. 1, left positive
    uint8_t      JoyThrottleDigital;          // 600
    uint8_t      JoyThrottleAnalog;           // 601
    uint8_t      JoyThrottleAnalogAlternate;  // 602
    uint8_t      _pad603;                     // 603
    float        ThrottleInput;               // 604  0 .. 1
    uint8_t      JoyBrakeDigital;             // 608
    uint8_t      JoyBrakeAnalog;              // 609
    uint8_t      JoyBrakeAnalogAlternate;     // 610
    uint8_t      _pad611;                     // 611
    float        BrakeInput;                  // 612
    uint8_t      JoyReverseDigital;           // 616
    uint8_t      JoyReverseAnalog;            // 617
    uint8_t      _pad618[2];                  // 618
    float        ReverseInput;                // 620  set, never read
    uint8_t      JoyEBrakeDigital;            // 624
    uint8_t      JoyEBrakeAnalog;             // 625
    uint8_t      _pad626[2];                  // 626
    float        EBrakeInput;                 // 628
    int32_t      LastNitroRequest;            // 632  a WorldTimer; 0 is never
    int32_t      Reversing;                   // 636  a bool stored as a word
} RealDriver;                                 // 640

// pCar is a pointer, so on a 64-bit host everything after it is four bytes
// further on. The term carries that.
#define REALDRIVER_SLACK ((size_t)(sizeof(void *) - 4))
#define RD_AT(f, n) (offsetof(RealDriver, f) == (size_t)(n) + REALDRIVER_SLACK)

typedef char realdriver_layout_check[
    (offsetof(RealDriver, pCar) == 560
     && RD_AT(Port, 564) && RD_AT(HandlersAdded, 568)
     && RD_AT(StartLineState, 572) && RD_AT(StopRightNow, 576)
     && RD_AT(ForcedEBrakeStop, 580) && RD_AT(bPowerSlide, 584)
     && RD_AT(ManualTransmission, 588) && RD_AT(JoySteeringDigital, 592)
     && RD_AT(JoySteeringAnalog, 593) && RD_AT(SteeringInput, 596)
     && RD_AT(JoyThrottleDigital, 600) && RD_AT(JoyThrottleAnalog, 601)
     && RD_AT(JoyThrottleAnalogAlternate, 602) && RD_AT(ThrottleInput, 604)
     && RD_AT(JoyBrakeDigital, 608) && RD_AT(JoyBrakeAnalog, 609)
     && RD_AT(JoyBrakeAnalogAlternate, 610) && RD_AT(BrakeInput, 612)
     && RD_AT(JoyReverseDigital, 616) && RD_AT(JoyReverseAnalog, 617)
     && RD_AT(ReverseInput, 620) && RD_AT(JoyEBrakeDigital, 624)
     && RD_AT(JoyEBrakeAnalog, 625) && RD_AT(EBrakeInput, 628)
     && RD_AT(LastNitroRequest, 632) && RD_AT(Reversing, 636)
     && sizeof(RealDriver) == 640 + 2 * REALDRIVER_SLACK) ? 1 : -1];

// _vt$10RealDriver, 0x00292a70: CarDriver's twenty-one slots with Drive,
// the joy handlers, SetLowGear, SetDesiredSpeed, GetDriverNumber and the
// horn its own. DoSnapshot, at 24, is NULL until ReplaySnapshot is ported.
#define REALDRIVER_VTABLE 0x00292a70u

// ManualTransmission. 1 is the manual box, whose gear is DesiredGear; 2 is
// the sport shift, where DesiredGear is -2 and SportGear is the gear.
#define RD_AUTOMATIC  0
#define RD_MANUAL     1
#define RD_SPORT      2

// CarDriver::DesiredGear values RealDriver writes. 0 is reverse, -1 lets
// the gearbox choose, -2 hands the choice to SportGear.
#define RD_GEAR_REVERSE  0
#define RD_GEAR_AUTO    (-1)
#define RD_GEAR_SPORT   (-2)

// ------------------------------------------------------------ the tables

// _GLOBAL_$I$PowerSlideYawCoef (0x0013aa88) builds seven Tables over seven
// arrays of the image's data. DoSteering reads four; SteeringInputTable
// and BrakingCurve have no reader in the image, and SteeringCurveTable is
// read both ways, InverseLookup and GetValue.
extern Table SteeringWheelRangeTable;   // 0x002e8828  ForwardSpeed 0..160
extern Table SteeringRangeTable;        // 0x002e8840  ForwardSpeed 0..160
extern Table SteeringSpeedTable;        // 0x002e8858  ForwardSpeed 0..160
extern Table SteeringCurveTable;        // 0x002e8870  0..1
extern Table SteeringInputTable;        // 0x002e88b0  0..256
extern Table YawCoeffTable;             // 0x002e88e0  |SteeringInput| 0..1
extern Table BrakingCurve;              // 0x002e8910  0..1

// PowerSlideYawCoef, gp-23096, 0x003231b8. 0.95 in the image, and a
// global DoSteering *writes* every frame it assists a counter-steer: 1.0
// on a wheel, YawCoeffTable of the stick's deflection otherwise. Nothing
// else reads it, so the stored value only matters within the frame.
extern float PowerSlideYawCoef;

// __CTOR_LIST__'s entry for 0x0013aa88. The seven Table constructors.
void realdriver_static_init(void);

// RealDriver.obj's .sdata tweakables, each an initialised word read
// through gp. Three are never read by anything in the image --
// CounterSteerFadeEnd, BrakingSpeed and UnBrakingSpeed are what is left of
// a counter-steer fade and a brake ramp that were written and then not
// used -- and are exported only so the transcript can print them.
extern float SteeringSpeed;                     // 0x003231d8   9.0
extern float SteeringReturnFactor;              // 0x003231dc   2.0
extern float CounterSteerFadeStart;             // 0x003231e0  13.410818
extern float CounterSteerFadeEnd;               // 0x003231e4  17.88109, unread
extern float MaxSpeedForReverse;                // 0x003231e8   0.5
extern float MinSpeedForThrottle;               // 0x003231ec -30.0
extern float MinSpeedForThrottleWhenReversing;  // 0x003231f0  -2.0
extern float BrakingSpeed;                      // 0x00323200   0.6, unread
extern float UnBrakingSpeed;                    // 0x00323204   6.0, unread
extern float NitrousActiveTime;                 // 0x00323208   4.0 s
extern float NitrousRechargeTime;               // 0x0032320c   0.0 s

// ----------------------------------------------------------- the methods

// 0x00138f90. CarDriver's constructor inlined, store for store (see
// cardriver_init), then pCar, Port -1, the handlers not added, the joy
// values reset and every flag clear but StartLineState, which is 1 -- a
// new driver holds the brake until the race lets it go. DesiredGear ends
// -1. SportGear, as in CarDriver, is left as it was.
void realdriver_init(RealDriver *d, struct Car *car);

// 0x00139058, flags 0 or 2: the vptr rewritten, the radial blur switched
// off if the car has a player, the handlers removed, then ~CarDriver.
void realdriver_fini(RealDriver *d);

// 0x00139058, all of it -- what the table's slot 8 calls.
void realdriver_destroy(RealDriver *d, int32_t flags);

// 0x00139600. Drive: the route editor's recorder (a seam) and the debug
// topology hook (`jr ra`, not ported), the joy values reset if the pad is
// unplugged, DoThrottleBrakeReverse, DoSteering, StopRightNow's and
// StartLineState's overrides, and the nitro's radial blur.
void realdriver_drive(RealDriver *d, float dt);

void realdriver_add_joy_handlers(RealDriver *d);          // 0x00139288
void realdriver_remove_joy_handlers(RealDriver *d);       // 0x00139458
void realdriver_disable_start_line_state(RealDriver *d);  // 0x00139568
void realdriver_enable_start_line_state(RealDriver *d);   // 0x0013ac40
void realdriver_set_manual_transmission(RealDriver *d, int32_t m); // 0x00139598
void realdriver_set_low_gear(RealDriver *d);              // 0x001395d8
// Retail's (0x0013b558): the e-brake held for `t` seconds while the car
// is faster than 20 mph. The demo's (0x00139760) took an on/off int.
void realdriver_force_ebrake_stop(RealDriver *d, float t);
void realdriver_reset_joy_values(RealDriver *d);          // 0x00139768
void realdriver_do_steering(RealDriver *d, float dt, JoystickPort port); // 0x00139838
void realdriver_do_throttle_brake_reverse(RealDriver *d, float dt);// 0x00139d48
void realdriver_do_brake(RealDriver *d, float dt);        // 0x00139ff0, no caller
int32_t realdriver_nitro_was_active(RealDriver *d);       // 0x0013a410
int32_t realdriver_nitro_active(RealDriver *d);           // 0x0013a490
int32_t realdriver_nitro_available(RealDriver *d);        // 0x0013a4f0
void realdriver_start_honk_horn(RealDriver *d);           // 0x0013a558
void realdriver_stop_honk_horn(RealDriver *d);            // 0x0013a598

JoystickPort realdriver_get_port(RealDriver *d);          // 0x0013ac10
int32_t realdriver_get_driver_number(RealDriver *d);      // 0x0013ac18
void realdriver_set_desired_speed(RealDriver *d, float speed, float time,
                                  int32_t flag);          // 0x0013ac28
void realdriver_set_predicted_target(RealDriver *d, DriveTarget *t); // 0x0013ac30
void realdriver_set_stop_right_now(RealDriver *d, int32_t on);     // 0x0013ac38
void realdriver_set_joystick_port(RealDriver *d, JoystickPort p);  // 0x0013ac50
struct Car *realdriver_get_car(RealDriver *d);            // 0x0013ac58

// The eleven handlers. `obj` is the RealDriver; `value` a byte.
void realdriver_joy_steer(JoystickPort port, JoyEvent ev, uint8_t value,
                          void *obj);                     // 0x001397b8
void realdriver_joy_throttle(JoystickPort port, JoyEvent ev, uint8_t value,
                             void *obj);                  // 0x00139bb0
void realdriver_joy_reverse(JoystickPort port, JoyEvent ev, uint8_t value,
                            void *obj);                   // 0x00139cb0
void realdriver_joy_brake(JoystickPort port, JoyEvent ev, uint8_t value,
                          void *obj);                     // 0x00139f18
void realdriver_joy_ebrake(JoystickPort port, JoyEvent ev, uint8_t value,
                           void *obj);                    // 0x00139f98
void realdriver_joy_shift_up(JoystickPort port, JoyEvent ev, uint8_t value,
                             void *obj);                  // 0x0013a060
void realdriver_joy_shift_down(JoystickPort port, JoyEvent ev, uint8_t value,
                               void *obj);                // 0x0013a118
void realdriver_joy_reset_car(JoystickPort port, JoyEvent ev, uint8_t value,
                              void *obj);                 // 0x0013a1c0
void realdriver_joy_honk_horn(JoystickPort port, JoyEvent ev, uint8_t value,
                              void *obj);                 // 0x0013a2e8
void realdriver_joy_nitro_boost(JoystickPort port, JoyEvent ev, uint8_t value,
                                void *obj);               // 0x0013a3a0

// Installs _vt$10RealDriver. The game calls it once at boot.
void realdriver_install_vtable(void);

// ------------------------------------------------------------- the seams

// Every call RealDriver makes into a class another task owns. Each is a
// plain `jal` (or a tail `j`) in the image; the port reaches it through a
// pointer that is NULL until that class exists.
//
// A NULL seam is skipped, and a NULL query answers the value that leaves
// the game as it would be without the class: no blur, no sound, no replay
// event, no reset, and IsAllowedToReset false. That is safe for these
// fourteen -- none of them feeds the physics -- and it is what the
// handheld runs today.

// MaybeAddTrackRoutePoint (0x001bbd18) and CancelTuningDrivingLines
// (0x001bbd90): the free functions, which test pTrackRouteEditor and pass
// the call on. The editor is built on every track load, so both reach it;
// it records a route only in its debug mode, and cancels a tuning flag on
// every route that only its debug mode sets. Task 27.
extern void (*gMaybeAddTrackRoutePointFn)(const bVector3 *position,
                                          const bVector3 *velocity,
                                          float z, int32_t flag,
                                          int32_t car_class);
extern void (*gCancelTuningDrivingLinesFn)(void);

// RadialBlurOn/Off/Alpha (0x0010dc80, 0x0010dcd0, 0x0010dd38): the render
// effect behind a nitro, per player view. Task 27.
extern void (*gRadialBlurOnFn)(int32_t view);
extern void (*gRadialBlurOffFn)(int32_t view);
extern void (*gRadialBlurAlphaFn)(int32_t view, float from, float to);

// ReplayManager::RegisterInterestingEvent (0x0013c290). The image calls it
// on pReplayManager with no NULL test, so a race always has a replay; the
// port has none yet.
extern void (*gReplayRegisterInterestingEventFn)(struct ReplayManager *rm,
                                                 float weight,
                                                 const char *name);

// Player::RerouteJoyEvent (0x001721b8), IsAllowedToReset (0x0017aab8),
// PlayerSelectedReset (0x0017ab08). Task 26.
extern void    (*gPlayerRerouteJoyEventFn)(struct Player *p, JoystickPort port,
                                           JoyEvent ev, uint8_t value);
extern int32_t (*gPlayerIsAllowedToResetFn)(struct Player *p);
extern void    (*gPlayerSelectedResetFn)(struct Player *p);

// tCopManager::GetResetDirection (0x00214740) and
// BeACopToggleSirenAndLights (0x00214610). Task 26. A NULL direction seam
// leaves the reset facing forward, 1.0, as a non-cop car's always is.
extern float (*gCopManagerGetResetDirectionFn)(struct tCopManager *m);
extern void  (*gCopManagerBeACopToggleSirenAndLightsFn)(struct tCopManager *m);

// Car::ResetToRoutePoint (0x00131480). Task 26.
extern void (*gCarResetToRoutePointFn)(struct Car *c, struct TrackRoute *r,
                                       struct TrackRoutePoint *p, float speed,
                                       int32_t flag, float direction);

// BaseCarSound::StartHonkHorn / StopHonkHorn (0x00185330, 0x00185370).
// Task 29.
extern void (*gBaseCarSoundStartHonkHornFn)(struct BaseCarSound *s);
extern void (*gBaseCarSoundStopHonkHornFn)(struct BaseCarSound *s);

#endif
