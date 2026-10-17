// psychodriver -- PsychoDriver (retail PsychoDriver.obj, 0x00139760 ..
// 0x0013a6ac and 0x0013ab68 .. 0x0013ad84; the demo's 0x00137620 ..).
//
// The AI's CarDriver. AIDriver's constructor and TrafficDriver's each
// bMalloc one (624 bytes) and build it on their car; from then on the
// AICarController talks to it through CarDriver's table -- SetTarget with
// the action's points, SetDesiredSpeed with the speed it wants -- and
// Car::Drive calls its Drive once a step, which turns the target and the
// speed into CarDriver's input record: a steering angle from three PID
// loops on the car's heading, its velocity's heading and its speed, a
// throttle and a brake, and a gear.
//
// Retail is not the demo's class. It dropped the demo's line predictor
// (RunLinePredict, MaxSpeedAlongPath, DoSpeedPredict, MaxSpeedFromCar and
// MaxSpeedToTarget, and the CarPredictInfo at 564) and CurrentPhysicsMode,
// and added a speed tolerance, an e-brake timer and a direction latch;
// Drive's gear logic and CalcThrottleAndBrake are new.
//
// DoSnapshot (0x00139980) is the replay's, since TASKS 72c.
// Written up in docs/formats/psycho-driver.md; checked against retail by
// tools/psychodriver_check.py.

#ifndef PSYCHODRIVER_H
#define PSYCHODRIVER_H

#include <stddef.h>
#include <stdint.h>

#include "average.h"
#include "bvector.h"
#include "cardriver.h"
#include "drivetarget.h"
#include "table.h"

struct Car;
struct BaseCarSound;

// 624 bytes (AIDriver's bMalloc), 16-aligned. The vptr is CarDriver's, at
// 556.
typedef struct PsychoDriver {
    CarDriver    Base;                          //   0
    struct Car  *pCar;                          // 560
    bVector2     SteerToPoint;                  // 564
    float        MaxThrottle;                   // 572  1.0, and never read
    float        DesiredSpeed;                  // 576  signed: < 0 reverses
    float        TimeToGetToDesiredSpeed;       // 580  counts down in Drive
    float        DesiredSpeedTolerance;         // 584  new in retail
    int32_t      AllowedToUseThrottleAndBrake;  // 588  a bool stored as a word
    float        EBrakeTimer;                   // 592  new in retail
    uint8_t      _unused596[4];                 // 596  nothing reads or writes it
    int32_t      DirectionLatch;                // 600  new in retail, a bool
    PidError    *pBodyError;                    // 604  "Phsycho Body Pid"
    PidError    *pHeadingError;                 // 608  "Phsycho Heading Pid"
    PidError    *pVelocityError;                // 612  "Phsycho Velocity Pid"
    uint8_t      _pad616[8];                    // 616  to 624
} PsychoDriver;

// pCar is a pointer, so on a 64-bit host everything after it is four bytes
// further on, and each PidError pointer adds four more.
#define PSYCHODRIVER_SLACK ((size_t)(sizeof(void *) - 4))
#define PD_AT(f, n, k) \
    (offsetof(PsychoDriver, f) == (size_t)(n) + (k) * PSYCHODRIVER_SLACK)

typedef char psychodriver_layout_check[
    (offsetof(PsychoDriver, pCar) == 560
     && PD_AT(SteerToPoint, 564, 1) && PD_AT(MaxThrottle, 572, 1)
     && PD_AT(DesiredSpeed, 576, 1) && PD_AT(TimeToGetToDesiredSpeed, 580, 1)
     && PD_AT(DesiredSpeedTolerance, 584, 1)
     && PD_AT(AllowedToUseThrottleAndBrake, 588, 1)
     && PD_AT(EBrakeTimer, 592, 1) && PD_AT(DirectionLatch, 600, 1)
     && PD_AT(pBodyError, 604, 1) && PD_AT(pHeadingError, 608, 2)
     && PD_AT(pVelocityError, 612, 3)
     && (sizeof(void *) != 4 || sizeof(PsychoDriver) == 624)) ? 1 : -1];

// _vt$12PsychoDriver, retail 0x002aec50 (the demo's 0x00292890):
// CarDriver's twenty-one slots with everything but the joy handlers,
// MaxSpeedToTarget and SetPhysicsMode its own.
#define PSYCHODRIVER_VTABLE 0x002aec50u

// GetMovementIndex's answers. 3 and 4 are the "fixed" indices: the PID
// weights, the steer-to distance and the steering range come from the
// arrays below instead of the speed tables.
#define PD_INDEX_BELT      0   // BELT_MOVEMENT, or MELLOW without traffic
#define PD_INDEX_PHYSICS   1
#define PD_INDEX_COP       2
#define PD_INDEX_TRAFFIC   3   // TRAFFIC, DELIVERY and anything unknown
#define PD_INDEX_MELLOW    4   // MELLOW_MOVEMENT under TRAFFIC_CONTROL

// ------------------------------------------------------------ the tables

// _GLOBAL_$I$PidProportionalData (retail 0x0013ab68, the demo's
// 0x00138d68) builds seven Tables over the image's data, the first six
// over ForwardSpeed 0..160 and the curve over 0..1. Drive reads five and
// CalcSteerToPoint one; PsychoSteeringCurveTable has no reader.
extern Table PidProportionalTable;      // retail 0x002f0628
extern Table PidDerivativeTable;        // retail 0x002f0640
extern Table PidIntegralTable;          // retail 0x002f0658
extern Table PidSteerToTable;           // retail 0x002f0670
extern Table PsychoSteeringRangeTable;  // retail 0x002f06f0
extern Table PsychoSteeringSpeedTable;  // retail 0x002f0708
extern Table PsychoSteeringCurveTable;  // retail 0x002f0720, unread

// The four weight arrays (retail 0x002aecf8 .. 0x002aed40), one float per
// movement index. Only indices 3 and 4 are read.
extern const float PsychoSteeringProportionalWeight[5];
extern const float PsychoSteeringIntegralWeight[5];
extern const float PsychoSteeringDerivativeWeight[5];
extern const float PsychoDriverSteerToPointSecondsAhead[5];

// fPsychoCounterDiff (retail gp-13408, the demo's 0x00325310), a file
// static the start-up code sets to 0.000958738 (gp-31560): how far apart
// the two heading errors must be before Drive trusts the body's.
extern float fPsychoCounterDiff;

// Drive's `static int warned_already` (retail gp-22576, the demo's
// 0x00323180), counted up each step the steer-to point is over 200 m from
// the car. Nothing reads it.
extern int32_t PsychoDriverWarnedAlready;

// __CTOR_LIST__'s entry for 0x00138d68: the seven Tables and
// fPsychoCounterDiff.
void psychodriver_static_init(void);

// ------------------------------------------------------------- the seams

// BaseCarSound::IsHonking (0x0018d800), for IsHonking. Start and stop are
// realdriver.h's gBaseCarSoundStartHonkHornFn and ...StopHonkHornFn.
extern int32_t (*gBaseCarSoundIsHonkingFn)(struct BaseCarSound *s);

// ----------------------------------------------------- the free functions

// 0x00139700, RadianWrap(unsigned short): the BAM as radians, a turn
// taken off above 3.14159. The test for below -3.14159 is there and never
// passes, as the angle comes in unsigned.
float radian_wrap(uint16_t bam);

// AIDrivingInfo.obj's SteerStraightVector3D (0x001cd148) and
// SteerStraightVelocity3D (0x001cd1d8), which only CalcSteerToPoint calls:
// the point max(5, dist) ahead of the car along its heading, or along its
// velocity. The image adds all four lanes, and the heading's w is a stack
// word it never writes; the port's is 0, so `out->pad` is the position's.
void ai_steer_straight_vector3d(bVector3 *out, struct Car *car, float dist);
void ai_steer_straight_velocity3d(bVector3 *out, struct Car *car, float dist);

// ----------------------------------------------------------- the methods

// 0x00139760. CarDriver's constructor inlined (cardriver_init), then pCar,
// DirectionLatch and AllowedToUseThrottleAndBrake 1, the speed, its time,
// its tolerance and the e-brake timer 0, the vptr, MaxThrottle 1.0, the
// three PidErrors -- each bMalloc(40, name, 0, 16) and Averages of 15 and
// 5 slots (6 and 3 for the velocity's) -- ZeroSteeringMemory,
// ZeroThrottleMemory and the steer-to point (0, 0).
PsychoDriver *psychodriver_init(PsychoDriver *d, struct Car *car);

// 0x001398e8, slot 8: the vptr, each PidError that is set destroyed with
// flags 3 (body, heading, velocity), StopHonkHorn, then ~CarDriver with
// the caller's flags.
void psychodriver_destroy(PsychoDriver *d, int32_t flags);

// 0x00139c48, slot 16. See docs/formats/psycho-driver.md.
void psychodriver_drive(PsychoDriver *d, float dt);

// 0x00139968, slot 56. Retail's takes a tolerance too.
void psychodriver_set_desired_speed(PsychoDriver *d, float speed, float time,
                                    float tolerance, int32_t allowed);

// 0x0013a3e0, slot 64. A target with 0 to 20 points is copied in
// (DriveTarget::operator=) and resampled; NULL, or any other count, is
// dropped.
void psychodriver_set_target(PsychoDriver *d, DriveTarget *t);

// 0x00139a68. The heading error -- the car's Angle less the bearing of
// the steer-to point, wrapped -- into *head, and the velocity's bearing
// less it into *vel at 1 m/s forward or more, else *head again. Returns
// the bearing.
int32_t psychodriver_get_error(PsychoDriver *d, float *head, float *vel);

// 0x00139b28, slot 120: Reset(0) on the body's and the heading's
// PidErrors. 0x00139b68, slot 128: GetError, then Reset each to its own.
void psychodriver_zero_steering_memory(PsychoDriver *d);
void psychodriver_clear_steering_memory(PsychoDriver *d);

// 0x00139bb0: Reset(0) on the velocity's. 0x00139bc0, no caller: Reset to
// |DesiredSpeed| less the car's VelocityMagnitude.
void psychodriver_zero_throttle_memory(PsychoDriver *d);
void psychodriver_clear_throttle_memory(PsychoDriver *d);

// 0x00139be0. PD_INDEX_* by the car's MovementMode.
int32_t psychodriver_get_movement_index(PsychoDriver *d);

// 0x0013a438. Where the car steers: the drive target's point a distance
// on (the speed tables', or the seconds-ahead array's for a fixed index),
// or straight ahead with under two points.
void psychodriver_calc_steer_to_point(PsychoDriver *d);

// 0x0013a548. A throttle and brake from the velocity PID, once the speed
// is more than the tolerance away.
void psychodriver_calc_throttle_and_brake(PsychoDriver *d, float *thr,
                                          float *brk);

// 0x0013a638, 0x0013a658, 0x0013a678, slots 88, 96 and 104: the car's
// sound's, when it has one. IsHonking is 0 without.
void    psychodriver_start_honk_horn(PsychoDriver *d);
void    psychodriver_stop_honk_horn(PsychoDriver *d);
int32_t psychodriver_is_honking(PsychoDriver *d);

int32_t   psychodriver_get_driver_number(PsychoDriver *d);      // 0x0013ac80
void      psychodriver_step_on_it_jeeves(PsychoDriver *d);      // 0x0013acc0
void      psychodriver_set_low_gear(PsychoDriver *d);           // 0x0013acd8
float     psychodriver_get_desired_time_to_speed(PsychoDriver *d); // ..ace8
float     psychodriver_get_desired_speed(PsychoDriver *d);      // 0x0013acf0
void      psychodriver_set_max_throttle(PsychoDriver *d, float f); // ..acf8
bVector2 *psychodriver_get_steer_to_point(PsychoDriver *d);     // 0x0013ad00
void      psychodriver_set_ebrake_timer(PsychoDriver *d, float f); // ..ad08
void      psychodriver_set_steer_to_point(PsychoDriver *d, bVector2 *p); // ad10

// 0x00139980, slot 24, a "PsychoDriver" section: the four speed floats,
// SteerToPoint's 8 bytes, the throttle flag, the e-brake timer, the latch,
// the three PidErrors and then the CarDriver.
struct ReplaySnapshot;
void psychodriver_do_snapshot(PsychoDriver *d, struct ReplaySnapshot *s);

// Installs _vt$12PsychoDriver.
void psychodriver_install_vtables(void);

#endif
