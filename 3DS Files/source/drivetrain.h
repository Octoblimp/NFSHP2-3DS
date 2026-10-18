// drivetrain -- DriveTrain, 0x00182828 .. 0x00183e10: one contiguous run
// of 39 symbols, 5608 bytes.
//
// There is no DriveTrain.obj. The linker map puts this range inside
// Engine.obj, whose .text is 0x001823d8 and 0x1b98 long, with Engine's
// own nine functions below the run and twenty-five above it and none of
// them interleaved. That is why the vtable, ClutchSpeed and the pooled
// literals below are all quoted as Engine.obj's .rodata, .data and
// .lit4 -- DriveTrain has no sections of its own.
//
// The gearbox, the clutch and the differential: everything
// between the crankshaft and the four rims. Ninth slice of task 25, after
// CarState, Engine, CarTypeInfo, CarDriver, Steering, RigidBody,
// Suspension and Wheel -- and the first one whose every dependency was
// already on the handheld.
//
// It is a PhysicsComponent with exactly one state float, the clutch
// engagement in [0, 1]. GetDerivative does not integrate anything
// physical: it looks the clutch's rate up in a four-entry table indexed by
// the clutch state machine and scales it by DriveTrainInfo::ShiftSpeed, so
// the clutch sweeps in and out at a tuned speed rather than following a
// force.
//
// Three things to keep straight.
//
// **The differential is queried, not stored.** There is no differential
// speed in the record that the integrator owns.
// GetDifferentialAngularVelocity reads the four wheels every time it is
// called, and ComputeAuxiliaries caches the answer in
// DifferentialAngularVelocity for the rest of the frame. Writing that
// field does nothing; SetDifferentialAngularVelocity writes the *wheels*.
//
// **Gear indices are the Gear enum, not zero-based.** GearRatios[2] is
// first gear. The image indexes GearRatios, ShiftUpRPM and ShiftDownRPM
// with CurrentGear directly, so REVERSE and NEUTRAL occupy entries 0 and
// 1 of all three.
//
// **GearShiftMethod ships as 1.** The simple shift-point formula in
// CalculateShiftPoints -- the one that just interpolates ShiftUpPoint
// between idle and the red line -- is dead code in the shipped build. It
// is ported and the transcript runs it, because the value is a writable
// .sdata global the debug menu moved.
//
// Layout from `.mdebug`, `DriveTrain (size=148)`, every offset re-derived
// from the listing. See docs/formats/car-drivetrain.md.

#ifndef DRIVETRAIN_H
#define DRIVETRAIN_H

#include <stddef.h>
#include <stdint.h>

#include "carstate.h"
#include "cartypeinfo.h"
#include "engine.h"
#include "wheel.h"

// 0x00297a30, `_vt$10DriveTrain`. The base's is rigidbody.h's
// PHYSICSCOMPONENT_VTABLE, which the destructor puts back. Recorded
// because the constructor writes it and a later dispatching slice will
// want the value.
#define DRIVETRAIN_VTABLE 0x00297a30u

// GetSize (0x00183db8) is `addiu v0,zero,1`: one float, which is
// sizeof(DriveTrainState) / 4. Honest, like Suspension's two and unlike
// RigidBody's thirty-two.
#define DRIVETRAIN_STATE_FLOATS 1

// ---------------------------------------------------------- the two enums
//
// `4Gear`, type#1053 in the debug info. carstate.h and cardriver.h both
// carry `typedef int32_t Gear` for the width; this is where the values
// live, because this is the object that gives them meaning. They are
// signed and two of them are negative, so every comparison against them in
// the listing is a signed `slt`, never `sltu`.
//
// The two negatives are modes rather than gears. AUTOMATIC asks
// SetDesiredGear to pick; SPORT_SHIFT asks it to follow SportGear and to
// hand back AUTOMATIC when the driver has stopped shifting.
#define SPORT_SHIFT   ((Gear)-2)
#define AUTOMATIC     ((Gear)-1)
#define REVERSE       ((Gear)0)
#define NEUTRAL       ((Gear)1)
#define FIRST_GEAR    ((Gear)2)
#define SECOND_GEAR   ((Gear)3)
#define THIRD_GEAR    ((Gear)4)
#define FOURTH_GEAR   ((Gear)5)
#define FIFTH_GEAR    ((Gear)6)
#define SIXTH_GEAR    ((Gear)7)
#define SEVENTH_GEAR  ((Gear)8)

// `11ClutchState`, type#5747. The order matters twice over: GetDerivative
// indexes ClutchSpeed with it, and ComputeAuxiliaries switches on it with
// a chain the compiler built from `slti v0,v1,2` plus two compares.
//
// ClutchStateString at 0x00307f40 holds "Disengaging", "Disengaged",
// "Engaging", "Engaged" in exactly this order, which is the cross-check
// that the numbering is not guessed.
typedef int32_t ClutchState;

#define CLUTCH_DISENGAGING ((ClutchState)0)
#define CLUTCH_DISENGAGED  ((ClutchState)1)
#define CLUTCH_ENGAGING    ((ClutchState)2)
#define CLUTCH_ENGAGED     ((ClutchState)3)

// ---------------------------------------------------------- the constants
//
// ClutchSpeed, 0x00307f30, four floats in Engine.obj's .data that only
// DriveTrain::GetDerivative reads. Indexed by ClutchState: the clutch
// falls out at 3 per unit of ShiftSpeed, comes in at 1.5, and holds still
// at both ends. It is const data, not a tuning global, so it is spelled
// here rather than declared extern.
#define DRIVETRAIN_CLUTCH_SPEED_DISENGAGING (-3.0f)
#define DRIVETRAIN_CLUTCH_SPEED_DISENGAGED  ( 0.0f)
#define DRIVETRAIN_CLUTCH_SPEED_ENGAGING    ( 1.5f)
#define DRIVETRAIN_CLUTCH_SPEED_ENGAGED     ( 0.0f)

// 0x00321558 and 0x00321560 / 0x00321568, the object's own pooled
// literals. Idling converts IdleRPM one way and both automatic-shift paths
// convert the crankshaft the other.
//
// **Neither is 2pi/60 or 60/2pi.** The correctly rounded floats of those
// are 0x3dd67750 and 0x4118c9eb; the image has 0x3dd67745 and 0x4118c9f3,
// eleven and eight ulps away. 0x4118c9f3 is the decimal 9.549304 -- the
// five-place tabulated value of 60/2pi, spelled out to seven -- and
// 0x3dd67745 is exactly its float reciprocal. So the pair is each other's
// reciprocal to the last bit, and their float product is exactly 1.0, but
// both are a little off the constant they stand for.
//
// That matters because it is the easy thing to get wrong. A port that
// wrote 2pi/60 here, or that kept one constant and spelled the other as
// 1.0f / it, would agree with the image on the round trip and disagree
// with it on every single conversion: every idle test in Idling and every
// shift point in both automatic paths would move.
#define DRIVETRAIN_RPM_TO_RADS 0.104719676f  // 0x3dd67745
#define DRIVETRAIN_RADS_TO_RPM 9.54930401f   // 0x4118c9f3

// -------------------------------------------------------- the tuning set
//
// Eight globals in .sdata with the names the MAP file gives them and the
// values the shipped ELF has. All writable, all reachable from the debug
// menu, so the port keeps them as variables rather than folding them in.
//
// Two are worth reading twice. **GearShiftMethod ships as 1**, which
// selects the torque-crossover shift points and leaves the interpolated
// ones unreachable in the shipped build. And **LIMITEDSLIP is one global
// doing two jobs** in ApplyClutchTorque: it is the threshold the spin
// share is tested against *and*, halved, the share the differential
// clamps to. Move it and both ends move together.
extern float   gEngineBrakingFactor;    // 0x00323970  40.0, unread here
extern float   gShiftUpDetune;          // 0x00323974  0.95
extern float   gShiftDownDetune;        // 0x00323978  0.95
extern int32_t gGearShiftMethod;        // 0x0032397c  1
extern float   gLimitedSlip;            // 0x00323980  0.35
extern float   gClutchLimiter;          // 0x00323984  300.0
extern float   gClutchMatchedThreshold; // 0x00323988  50.0
extern float   gMaxDownShiftOver;       // 0x0032398c  retail's 1.2

// WorldTimeElapsed, 0x00323d00, is not DriveTrain's. The clock object owns
// it (realtime.h, through engine.h), and this object only adds it to
// GearHoldTime. It is 0.0 in the image because it is written every frame,
// which means a transcript that never sets it sees the hold timer stand
// still. The sport-shift scenario sets it.

// ------------------------------------------------------------- the record

// DriveTrain::DriveTrainState, one float: how far the clutch is in, from
// 0 (fully out) to 1 (fully home). GetDerivative sweeps it and
// ComputeAuxiliaries clamps it at both ends.
typedef struct DriveTrainState {
    float clutch;                      // 0
} DriveTrainState;

// 148 bytes, on the same PhysicsComponent base as Engine, Suspension and
// Wheel: two list words and the vtable, and nothing this object reads.
//
// pDriveWheel is in the car's own corner order -- 0 and 1 are the front
// pair, 2 and 3 the rear -- and FinalDrive[0] and FinalDrive[1] follow the
// same split. Every function that touches one axle touches both indices of
// its pair, so a swapped pair shows up as a sign error rather than as
// nothing at all.
typedef struct DriveTrain {
    uint32_t  pNext;                        //   0  bNode, owned by the list
    uint32_t  pPrev;                        //   4
    uint32_t  _vtable;                      //   8
    DriveTrainState State;                  //  12
    const DriveTrainInfo *DTI;              //  16
    Engine   *pEngine;                      //  20
    Wheel    *pDriveWheel[4];               //  24
    CarState *pCarState;                    //  40
    Gear      DesiredGear;                  //  44
    Gear      CurrentGear;                  //  48
    Gear      PreviousGear;                 //  52
    ClutchState CurrentClutchState;         //  56
    int32_t   Shifting;                     //  60  a bool stored as a word
    float     DifferentialAngularVelocity;  //  64
    float     GearHoldTime;                 //  68
    Gear      SportGear;                    //  72
    float     ShiftUpRPM[9];                //  76
    float     ShiftDownRPM[9];              // 112
} DriveTrain;                               // 148

// Every pointer in this record sits in one contiguous run -- DTI, pEngine,
// the four wheels, pCarState -- and DTI is already eight-byte aligned at
// 16 on a host, so the widening is a single term times how many pointers
// an offset has passed. No alignment pad appears anywhere, which is why
// this header needs one SLACK where wheel.h needed a table of multipliers.
//
// Zero on the 32-bit ARM build, four on a 64-bit host.
#define DRIVETRAIN_SLACK ((size_t)(sizeof(void *) - 4))

// Compiled by both toolchains on purpose. An `#if __SIZEOF_POINTER__ == 4`
// around this would make the claim disappear from the host build and the
// exact-offset claim disappear from the ARM one, which is the trap
// CONTINUE.md records against an earlier draft of wheel.h.
#ifndef DRIVETRAIN_NO_ASSERT
typedef char drivetrain_layout_check[
    (sizeof(DriveTrainState) == 4
     && sizeof(DriveTrain) == 148 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, State)        ==  12
     && offsetof(DriveTrain, DTI)          ==  16
     && offsetof(DriveTrain, pEngine)      ==  20 + 1 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, pDriveWheel)  ==  24 + 2 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, pCarState)    ==  40 + 6 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, DesiredGear)  ==  44 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, CurrentGear)  ==  48 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, PreviousGear) ==  52 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, CurrentClutchState)
                                           ==  56 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, Shifting)     ==  60 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, DifferentialAngularVelocity)
                                           ==  64 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, GearHoldTime) ==  68 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, SportGear)    ==  72 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, ShiftUpRPM)   ==  76 + 7 * DRIVETRAIN_SLACK
     && offsetof(DriveTrain, ShiftDownRPM) == 112 + 7 * DRIVETRAIN_SLACK
     ) ? 1 : -1];
#endif

// ----------------------------------------------------------- the free one
//
// 0x00182828. Not a method: a file-scope function the constructor calls,
// and the only place ShiftUpRPM and ShiftDownRPM are ever written.
//
// It fills entries FIRST_GEAR .. NumGears of `up` and FIRST_GEAR+1 ..
// NumGears+1 of `down`, then puts EI->MaxRPM in up[NumGears + 1] so the
// top gear never shifts up. Entries 0 and 1 -- REVERSE and NEUTRAL -- are
// left exactly as the caller had them, which for the constructor means
// uninitialised.
//
// With gGearShiftMethod set, each up point is found by walking the RPM
// from (IdleRPM + MaxRPM) / 2 in 50 RPM steps until the torque at the
// wheels in the next gear beats the torque in this one, falling back to
// MaxRPM - 200 if no crossover turns up first. Both outcomes are then
// scaled by `scale` -- the two arms join *before* the multiply, at
// 0x001829a0, so the fallback is scaled too.
//
// With gGearShiftMethod clear it is IdleRPM + ShiftUpPoint * (RedLineRPM
// - IdleRPM) and `scale` is not applied at all: that arm joins the common
// tail one instruction later, at 0x001829cc.
//
// The down point for gear i+1 is always gShiftDownDetune times the up
// point for gear i, geared across by ratio[i+1] / ratio[i].
void drivetrain_calculate_shift_points(const DriveTrainInfo *dti,
                                       const EngineInfo *ei,
                                       float *up, float *down, float scale);

// ------------------------------------------------------------- the object

// 0x00182a60. Copies the four wheel pointers, calls CalculateShiftPoints
// with gShiftUpDetune, and starts in FIRST_GEAR with the clutch out and
// CLUTCH_ENGAGING.
//
// **PreviousGear, DifferentialAngularVelocity, GearHoldTime and SportGear
// are not initialised.** The listing writes 44, 12, 56, 48 and 60 and
// stops. A caller that reads GetSportGear before the first
// SetDesiredGear(SPORT_SHIFT) reads whatever the slot pool left behind.
// The port keeps the omission, and the harness zeroes the record first, so
// the transcript is reproducible without hiding the fact.
void drivetrain_init(DriveTrain *d, const DriveTrainInfo *dti, Engine *e,
                     Wheel *const *wheels, CarState *cs);

// 0x00182bf0. The gearbox-side speed of the differential, in rad/s at the
// crankshaft: the mean of each driven pair's wheel speed times that pair's
// final drive, summed, halved again if both pairs drive, times the current
// gear ratio.
//
// The halving is skipped entirely when only the rear pair drives -- the
// `bnel` that does it is only reached through the front arm -- so a
// rear-drive car gets its pair's mean and a four-wheel-drive car gets the
// mean of the two pairs.
float drivetrain_get_differential_angular_velocity(const DriveTrain *d);

// 0x00182cc0. The mean of the driven wheels' OldSlip, with the same shape
// -- except that here the front arm halves unconditionally. A front-drive
// car therefore reports **half** its front wheels' mean slip.
float drivetrain_get_drive_wheel_slippage(const DriveTrain *d);

// 0x00182d60. The inverse of GetDifferentialAngularVelocity, applied to
// the wheels rather than to a field: it works out the shortfall against
// the speed asked for and adds an equal share of it to every driven rim.
//
// Below 40 mph, or with both wheels of a pair off the ground, the pair is
// first averaged to a common speed -- that is the launch and the
// wheels-up cases, where letting the two rims disagree is what makes a
// standing start unstable.
void drivetrain_set_differential_angular_velocity(DriveTrain *d, float w);

// 0x00182f48. The same shape again over each driven wheel's
// (AppliedTorque - GroundForce[0] * radius) / momentOfInertia. Used only
// by ModifyClutchTorque.
float drivetrain_get_differential_angular_acceleration(DriveTrain *d);

// 0x00183100. The clutch state machine, once per frame. Caches the
// differential speed, drives the engine's ThrottleOverride, decides when
// the clutch has come home or fallen out, and starts a shift by dropping
// to CLUTCH_DISENGAGING when CurrentGear and DesiredGear disagree.
//
// The CLUTCH_ENGAGED arm is the interesting one: with the throttle open
// past 0.2 and the driven wheels slipping it snaps the whole drivetrain to
// the engine's speed, and otherwise it drags the engine 4% of the way
// towards the differential. Both write the engine's state directly.
void drivetrain_compute_auxiliaries(DriveTrain *d);

// 0x001832f8. out[0] = DTI->ShiftSpeed * ClutchSpeed[CurrentClutchState].
// Returns 0 -- the integrator reads the count from GetSize instead, the
// same convention Engine uses.
int32_t drivetrain_get_derivative(const DriveTrain *d, float *out);

// 0x00183328. Splits a crankshaft torque across the driven wheels and
// takes the same amount back off the engine's RoadTorque. Does nothing at
// all in NEUTRAL, including the RoadTorque subtraction.
//
// Within a pair the split follows the spin share, so the faster rim
// normally takes more -- an open differential. The limited-slip part is
// the clamp: once one rim's share passes gLimitedSlip on either side the
// split is forced to 0.175 / 0.825 the *other* way, which is what moves
// torque off a spinning wheel. With either wheel of the pair airborne the
// threshold widens from 0.35 to 0.5, so the clamp bites sooner.
//
// CarState::BurnOutState overrides the whole calculation: 1 forces the
// split one way and 2 the other.
void drivetrain_apply_clutch_torque(DriveTrain *d, float torque);

// 0x001835a8. The clutch's torque for this frame, by state.
// CLUTCH_DISENGAGED does nothing; the two moving states apply the speed
// difference times ClutchStiffness times how far the clutch is in, clamped
// to +-gClutchLimiter; CLUTCH_ENGAGED applies the engine's whole torque.
void drivetrain_guess_clutch_torque(DriveTrain *d);

// 0x00183688. Only while CLUTCH_ENGAGED, and only after GuessClutchTorque:
// the correction that makes the engine and the drivetrain accelerate
// together. It is the difference between the two accelerations divided by
// the summed inverse inertia of everything the clutch is tied to.
void drivetrain_modify_clutch_torque(DriveTrain *d);

// 0x00183830. `jr ra`. Empty in the shipped build, and ported as empty so
// that the call site a later slice writes has somewhere to go.
void drivetrain_finalize_clutch_torque(DriveTrain *d);

// 0x00183838. True when the throttle is under 0.3 and the differential is
// no faster than idle. Note the 0.0001 rad/s of slop on the idle side, and
// that the comparison is against the *differential*, not the engine.
int32_t drivetrain_idling(const DriveTrain *d);

// 0x00183888. True when the engine and the differential are within
// gClutchMatchedThreshold rad/s of each other.
int32_t drivetrain_clutch_matched(const DriveTrain *d);

// 0x001838c0. Takes a gear from the driver in sport mode. Ignores anything
// outside FIRST_GEAR .. NumGears + 1, and clears GearHoldTime on the way
// out of NEUTRAL. Returns SportGear, changed or not.
Gear drivetrain_set_sport_gear(DriveTrain *d, Gear g);

// 0x00183900. The gear chooser, and the largest function in the object.
//
// Anything that is not AUTOMATIC or SPORT_SHIFT is written straight into
// DesiredGear and handed back.
//
// AUTOMATIC shifts up when the engine passes ShiftUpRPM[CurrentGear] and
// all four wheels are on the ground with CurrentSlip under 4, and down
// when it falls below ShiftDownRPM[CurrentGear] -- or, in first and
// second with the throttle nearly shut, below IdleRPM + 100, which is what
// stops the car stalling at a crawl.
//
// SPORT_SHIFT follows SportGear and returns AUTOMATIC once the driver has
// held the requested gear for ten seconds, or bounced off the limiter in
// a gear above the one they came from.
//
// **Nineteen instructions of the SPORT_SHIFT path are unreachable**: the
// arm at 0x00183b94 that would fall back to AUTOMATIC when the engine bogs
// down. Reaching it needs DesiredGear and SportGear to be neither equal
// nor ordered, and signed `slt` on two ints has no third case. It is
// ported as written; see docs/formats/car-drivetrain.md.
Gear drivetrain_set_desired_gear(DriveTrain *d, Gear g);

// 0x00183c28. `jr ra`, the debug print compiled out, like Wheel's
// SetSliderValue.
void drivetrain_print_current_state(const DriveTrain *d);

// -------------------------------------------------------------- accessors

// 0x00183c78, 0x00183ca0. TorqueSplit is the rear share: >= 0.001 drives
// the rear pair, <= 0.999 drives the front. Both are true between, which
// is how four-wheel drive is spelled -- there is no third flag.
int32_t drivetrain_rear_wheel_drive(const DriveTrain *d);
int32_t drivetrain_front_wheel_drive(const DriveTrain *d);

// 0x00183cc8. NumGears + 1, because gear numbering starts at REVERSE.
Gear drivetrain_get_top_gear(const DriveTrain *d);

// 0x00183d08, 0x00183d10, 0x00183d18, 0x00183d20.
Gear drivetrain_get_desired_gear(const DriveTrain *d);
Gear drivetrain_get_previous_gear(const DriveTrain *d);
Gear drivetrain_get_sport_gear(const DriveTrain *d);
Gear drivetrain_get_current_gear(const DriveTrain *d);

// 0x00183d28. `xori v0,v0,3` then `sltiu v0,v0,1` -- equality with
// CLUTCH_ENGAGED, spelled without a branch.
int32_t drivetrain_is_clutch_engaged(const DriveTrain *d);

// 0x00183d38, 0x00183d40, 0x00183d68.
Engine               *drivetrain_get_engine(const DriveTrain *d);
const DriveTrainInfo *drivetrain_get_drive_train_info(const DriveTrain *d);
ClutchState           drivetrain_get_current_clutch_state(const DriveTrain *d);

// 0x00183d48, 0x00183d58. Unguarded: the gear indexes the array with no
// range check, and REVERSE and NEUTRAL read the two entries
// CalculateShiftPoints never wrote.
float drivetrain_get_shift_down_rpm(const DriveTrain *d, Gear g);
float drivetrain_get_shift_up_rpm(const DriveTrain *d, Gear g);

// 0x00183d70. The hard set: gear in, clutch home, CLUTCH_ENGAGED, and
// DesiredGear and CurrentGear both written. Used to place a car rather
// than to drive it.
void drivetrain_set_state_gear(DriveTrain *d, Gear g);

// 0x00183d90, 0x00183da0, 0x00183db0, 0x00183db8 -- the integrator's four.
void             drivetrain_set_state_array(DriveTrain *d, const float *in);
void             drivetrain_get_state_array(const DriveTrain *d, float *out);
DriveTrainState *drivetrain_get_state(DriveTrain *d);
int32_t          drivetrain_get_size(const DriveTrain *d);

// Retail's 0x0018af10 (the demo's 0x00182b00), the replay's: a section
// named "DriveTrain" with State, the five gear and clutch words, Shifting,
// DifferentialAngularVelocity, GearHoldTime and ShiftUpRPM[0] -- that one
// float of the eighteen.
struct ReplaySnapshot;
void drivetrain_do_snapshot(DriveTrain *d, struct ReplaySnapshot *s);

// operator new and operator delete are the PS2 slot allocator --
// DriveTrainSlotPool at 0x00323090. They and
// the destructor, which is PhysicsComponent's plus that delete, are
// physcomp.h's, beside `_vt$10DriveTrain`.
//
// CheckFunction is declared in `.mdebug` and has no code in the image.

#endif // DRIVETRAIN_H
