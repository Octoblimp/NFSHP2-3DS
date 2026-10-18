// physicscar -- PhysicsCar.obj (0x00134c50 .. 0x001374d8).
//
// A PhysicsCar is what drives a Car when the car is being simulated rather
// than scripted: `Car::SetMovementMode`'s MM_PHYSICS arm builds one. It
// owns a RigidBody, a TwoWheelAckermanSteering, four Wheels, four
// Suspensions, an Engine, a DriveTrain and an Aerodynamics, and every one
// of those except the steering and the aerodynamics is a component of the
// PhysicsSystem it carries. The CarState it reads at construction and
// writes back each step is the Car's own, `&car->State`.
//
// Two bases, so two vptrs. **CarMover** is at 0 (its Driver, then its vptr
// at 4) and **PhysicsVehicle**, which is a PhysicsSystem and adds nothing,
// is at 8 (its vptr at 20). The table the second vptr holds has a delta of
// -8 on every entry, which turns the PhysicsVehicle pointer PhysicsSystem's
// integrator calls through back into the PhysicsCar. In the port the delta
// is `-offsetof(PhysicsCar, Vehicle)`, which is -8 on the 3DS and -16 on the
// 64-bit host.
//
// The object is the demo's, with retail's DoSnapshot (0x00137450) and the
// Timer retail added for it, kept after the demo's fields as Car keeps
// retail's; retail's BottomOut, which runs that Timer, is not here yet
// (TASKS 73).
//
// See docs/formats/physics-car.md.

#ifndef PHYSICSCAR_H
#define PHYSICSCAR_H

#include <stddef.h>
#include <stdint.h>

#include "aerodynamics.h"
#include "car.h"
#include "cardriver.h"
#include "cartypeinfo.h"
#include "carstate.h"
#include "collisionbody.h"     // Timer
#include "drivetrain.h"
#include "engine.h"
#include "graph.h"
#include "physicssystem.h"
#include "rigidbody.h"
#include "steering.h"
#include "suspension.h"
#include "wheel.h"

// -------------------------------------------------------------- CarMover

// 8 bytes: the driver and the vptr. Abstract -- `_vt$8CarMover`'s Move is
// `__pure_virtual` -- so the only CarMover the port builds is the base of
// something else. car.h names the type without defining it.
struct CarMover {
    CarDriver *Driver;     // 0
    uint32_t   _vtable;    // 4
};

// _vt$8CarMover, 0x002923e0: the destructor (0x00134c58), Move (pure) and
// DoSnapshot (0x0012f1e8, `jr ra`). Every mover in the game lays its table
// out the same way.
#define CARMOVER_VTABLE          0x002923e0u
#define CARMOVER_VT_ENTRIES      4
#define CARMOVER_VT_DTOR         8
#define CARMOVER_VT_MOVE        16
#define CARMOVER_VT_DO_SNAPSHOT 24

typedef void  (*CarMoverDtorFn)(void *self, int32_t flags);
typedef float (*CarMoverMoveFn)(void *self, float dt);
typedef void  (*CarMoverDoSnapshotFn)(void *self, void *snap);

// 0x00134c80. Stores the vptr and nothing else: the driver is left as it
// was, and every subclass constructor sets it itself.
void carmover_init(CarMover *m);

// 0x00134c58. Stores the vptr back, then `__builtin_delete` if bit 0.
void carmover_destroy(CarMover *m, int32_t flags);

// 0x00134c50. `jr ra ; sw a1,0(a0)`.
void carmover_set_driver(CarMover *m, CarDriver *d);

// 0x0012f1e8, `jr ra`. Every mover that does not snapshot inherits it --
// NullMover's table has it too.
void carmover_do_snapshot(CarMover *m, void *snap);

// ------------------------------------------------------------ PhysicsCar

// 120 bytes, the demo's 116 and retail's Timer. The names are the mdebug
// record's, except the two bases', which it leaves unnamed, and the Timer.
// Retail has the Timer at 108, so its FrictionBoost and
// YawControlMultiplier are at 112 and 116.
typedef struct PhysicsCar {
    CarMover          Mover;              //   0  Driver 0, vptr 4
    PhysicsSystem     Vehicle;            //   8  PhysicsVehicle; vptr at 20
    RigidBody        *pBody;              //  24
    Steering         *pSteering;          //  28  a TwoWheelAckermanSteering
    Suspension       *pSuspension[4];     //  32
    Wheel            *pWheel[4];          //  48
    Engine           *pEngine;            //  64
    DriveTrain       *pDriveTrain;        //  68
    Aerodynamics     *pAerodynamics;      //  72
    const CarTypeInfo *CTI;               //  76
    CarState         *State;              //  80  &pCar->State
    Car              *pCar;               //  84
    Timer             BrakeStandTimer;    //  88
    Timer             BrakeStandTimerStart; // 92
    int32_t           BrakeStanding;      //  96  bool, stored as a word
    int32_t           ThrottleReleased;   // 100  bool, stored as a word
    int32_t           LurchsLeft;         // 104
    float             FrictionBoost;      // 108  retail's 112
    float             YawControlMultiplier; // 112  retail's 116
    // New in retail at 108, and the name is ours: the constructor zeroes
    // it and retail's BottomOut (physicscar_bottom_out, TASKS 73) starts it
    // when the body is stopped upside down, asking the Car to reset a
    // second later; the replay moves it.
    Timer             FlippedTimer;       // 116  retail's 108
} PhysicsCar;                             // 120

// Every pointer before a field widens it by four bytes on the host. The
// k in PHYSICSCAR_AT is how many pointers come before the field, counting
// CarMover's tail padding, which on the host rounds the base up to 16.
#define PHYSICSCAR_SLACK ((size_t)(sizeof(void *) - 4))
#define PHYSICSCAR_AT(f, n, k) \
    (offsetof(PhysicsCar, f) == (size_t)(n) + (k) * PHYSICSCAR_SLACK)

#ifndef PHYSICSCAR_NO_ASSERT
typedef char physicscar_layout_check[
    (sizeof(CarMover) == 8 + 2 * PHYSICSCAR_SLACK
     && offsetof(CarMover, _vtable) == 4 + PHYSICSCAR_SLACK
     && PHYSICSCAR_AT(Vehicle, 8, 2)
     && PHYSICSCAR_AT(pBody, 24, 2)
     && PHYSICSCAR_AT(pSteering, 28, 3)
     && PHYSICSCAR_AT(pSuspension, 32, 4)
     && PHYSICSCAR_AT(pWheel, 48, 8)
     && PHYSICSCAR_AT(pEngine, 64, 12)
     && PHYSICSCAR_AT(pDriveTrain, 68, 13)
     && PHYSICSCAR_AT(pAerodynamics, 72, 14)
     && PHYSICSCAR_AT(CTI, 76, 15)
     && PHYSICSCAR_AT(State, 80, 16)
     && PHYSICSCAR_AT(pCar, 84, 17)
     && PHYSICSCAR_AT(BrakeStandTimer, 88, 18)
     && PHYSICSCAR_AT(BrakeStandTimerStart, 92, 18)
     && PHYSICSCAR_AT(BrakeStanding, 96, 18)
     && PHYSICSCAR_AT(ThrottleReleased, 100, 18)
     && PHYSICSCAR_AT(LurchsLeft, 104, 18)
     && PHYSICSCAR_AT(FrictionBoost, 108, 18)
     && PHYSICSCAR_AT(YawControlMultiplier, 112, 18)
     && PHYSICSCAR_AT(FlippedTimer, 116, 18)
     && sizeof(PhysicsCar) == 120 + 18 * PHYSICSCAR_SLACK) ? 1 : -1];
#endif

// _vt$10PhysicsCar, 0x00292708, CarMover's layout: the destructor
// (0x001357a8), Move (0x00135c78) and DoSnapshot (the demo's 0x00135580,
// retail's 0x00137450).
#define PHYSICSCAR_VTABLE 0x00292708u

// _vt$10PhysicsCar$14PhysicsVehicle, 0x002926e8, PhysicsSystem's layout
// with delta -8 everywhere: the same destructor, ComputeAuxiliaries
// (0x00135828) and ResolveForces (0x00136cc8).
#define PHYSICSCAR_VEHICLE_VTABLE 0x002926e8u

// _vt$14PhysicsVehicle, 0x00292728: `~PhysicsVehicle` (0x001374d0, a `j`
// to ~PhysicsSystem) and PhysicsSystem's own two methods. The constructor
// stores it between PhysicsSystem's and PhysicsCar's.
#define PHYSICSVEHICLE_VTABLE 0x00292728u

#define PHYSICSCAR_VT_ENTRIES 4

// Installs the four tables above. The game calls it once at boot, after
// physicssystem_install_vtables and physcomp_install_vtables; a harness
// calls it after vt_reset() and may then replace any of them.
void physicscar_install_vtables(void);

// ------------------------------------------------------------ the tuning
//
// PhysicsCar.obj's .sdata and .bss, at their image values. Four more
// words of the .sdata -- ControlInputDebugInfo, LinearYawFrictionBoostSlope,
// TestTorque and TestBrakeTorque -- are left out: no instruction in the
// image reads them through gp. They are the debug menu's.

// Car::PleaseResetMeLater (carrace.c), which retail's BottomOut asks of a
// car stopped on its roof. Through a pointer main.c sets, so the checkers
// that build this file without carrace.c still link; left NULL, the car is
// not put back.
typedef void (*PhysicsCarResetFn)(Car *c);
extern PhysicsCarResetFn gPhysicsCarPleaseResetMeLaterFn;

extern int32_t UseNewSuspensionCalibration; // gp-23356  1
extern int32_t TriggerBounce;               // gp-23352  0
extern float   LowSpeedYawBoost;            // gp-23344  0
extern float   HighSpeedYawBoost;           // gp-23340  1.0
extern float   LowSpeedSpeed;               // gp-23336  0
extern float   HighSpeedSpeed;              // gp-23332  30.0
extern float   MaxYawBonus;                 // gp-23328  0x3f333333
extern float   YawLockThreshold;            // gp-23312  from the initialiser
extern int32_t UseMagicForce;               // gp-23260  0
extern int32_t PhysicsCarResolveCounter;    // gp-23256  counter.3921
extern float   SkidNormalize;               // gp-23252  6.0
extern Graph   JumpStabilization;           // gp-23248  from the initialiser
extern float   ResolveTime;                 // gp-23240
extern float   IterateTime;                 // gp-23236

// Move's. The two debug switches print a state per sub-step;
// SpeedDebugInfo turns the race into a dyno (see physicscar_move).
extern int32_t RigidBodyDebugInfo;          // gp-23364  0
extern int32_t DriveTrainDebugInfo;         // gp-23360  0
extern float   NFSAdjust;                   // gp-23324  0.85
extern float   MaximumTimeStep;             // gp-23320  0x3b902de0, 0.0044
extern float   BurnOutTorqueValue;          // gp-23308  1.5
extern float   BurnOutTorqueValueClip;      // gp-23304  3.0
extern float   BurnOutCancelTorqueValue;    // gp-23300  1.0
extern float   BurnOutMaxSpeed;             // gp-23296  15.0, in mph
extern float   BurnOutTractionValue;        // gp-23292  0.4
extern float   BurnOutMinTime;              // gp-23288  1.0
extern float   BurnOutAllowTime;            // gp-23284  0x3e2aaaab, 1/6
extern float   BurnOutYawMax;               // gp-23280  0x3e490fd0
extern float   BurnOutYawCancel;            // gp-23276  0.3
extern int32_t SpeedDebugInfo;              // gp-23272  0

// The dyno's clock, all .sbss.
extern float   SpeedDebugStartTime;         // gp-23228
extern float   SpeedDebugDisplayTime60;     // gp-23224
extern float   SpeedDebugDisplayTime100;    // gp-23220
extern float   SpeedDebugDisplayTimeQM;     // gp-23216
extern float   SpeedDebug060Time;           // gp-23212
extern float   SpeedDebug0100Time;          // gp-23208
extern float   SpeedDebugQMTime;            // gp-23204
extern float   SpeedDebugQMMeasure;         // gp-23200
extern float   SpeedDebugQMSpeed;           // gp-23196

// .data and .bss, by absolute address.
extern float    BrakeSettings[4];           // 0x002e8550  1, 1, 0.6, 0.6
extern float    EBrakeSettings[4];          // 0x002e8560  0, 0, 1, 1
extern bVector4 SpeedDebugX;                // 0x002e8570
extern bMatrix4 SpeedDebugR;                // 0x002e8580  stored, never read

// 0x00137438, _GLOBAL_$I$RigidBodySlotPool, __CTOR_LIST__[15]: the three
// points of JumpStabilization -- (0, 0), (0.4, 0), (2, 20) -- and
// YawLockThreshold, 0.0872664749 (five degrees).
void physicscar_static_init(void);

// ----------------------------------------------------------- the methods

// 0x00135240. `this` is the caller's 116 bytes -- Car::SetMovementMode's
// `bMalloc(116, ...)`, which the destructor's `__builtin_delete` gives
// back -- and every field is written. In order: CarMover's vptr, the PhysicsSystem, PhysicsVehicle's vptr, then
// the fields, both vptrs again as PhysicsCar's, and then the components:
//
//   * the RigidBody, added, then its IsHP and SpeedLimiter from the CTI;
//   * the steering, inlined in the image and ackerman_init here;
//   * for each corner, a Wheel then a Suspension, both constructed before
//     either is added, the Suspension given the steering only at the front;
//   * the sway bars, 0 with 1 and 2 with 3;
//   * the Engine, added, then its IsHP; the DriveTrain, added;
//   * the Aerodynamics, inlined in the image and aerodynamics_init here.
//
// Then Calibrate, InitializeStateFromCar and ComputeAuxiliaries, called
// directly rather than through the tables, and the four scalars last.
PhysicsCar *physicscar_init(PhysicsCar *pc, const CarTypeInfo *cti,
                            CarDriver *driver, Car *car);

// 0x001357a8. Both vptrs back to PhysicsCar's, the steering destroyed
// through its own table with flags 3, the Aerodynamics given back to its
// pool, then ~PhysicsVehicle with flags 0 -- which destroys every component
// the system owns -- and ~CarMover with the caller's flags, which frees.
void physicscar_destroy(PhysicsCar *pc, int32_t flags);

// 0x00135690. Calibrates the body about the CTI's centre of gravity, then
// splits the car's static load between the axles:
//
//   cog   = UseNewSuspensionCalibration ? CTI.CenterOfGravity.x : 0
//   a     = Wheels[0].PositionX - cog,  b = Wheels[3].PositionX - cog
//   rear  = (a / (a - b)) * 0.5,        front = 0.5 - rear
//   load  = Mass * 9.8 + AutoBalanceDownforce * downforce(ForwardSpeed)
//
// and each front Suspension gets `load * front`, each rear `load * rear`,
// then every Wheel is calibrated.
void physicscar_calibrate(PhysicsCar *pc);

// 0x00135828. The system's own ComputeAuxiliaries, BottomOut, then
// **ResolveForces through the vehicle's vptr**, slot 24.
void physicscar_compute_auxiliaries(PhysicsCar *pc);

// Retail's 0x001377d8 (the demo's 0x00135878). Whether the car is still
// enough to damp: 0 (no), 1 (damp) or 2 (stop dead).
#define DS_NO_DAMP 0
#define DS_DAMP    1
#define DS_DOUSE   2
int32_t physicscar_check_damping_suitability(PhysicsCar *pc);

// Retail's 0x00137938 (the demo's 0x00135970). Penalty impulses for
// bottomed-out corners, the damping CheckDampingSuitability asks for, then
// the debug bounce. If any of them fired, UglyTimestepHack is cleared and
// the system's ComputeAuxiliaries runs again. Retail added the rest: a car
// stopped dead with its up axis under 0.1 of z starts FlippedTimer and asks
// to be reset once it has lain there a second; a moving one clears the
// timer. Stopping dead clears the collision body's ActiveCollisionDetection
// and the other two arms set it; the wheels stop only while one is down.
//
// **The image leaves some words uninitialised** and the port zeroes them.
// The debug bounce's impulse and point are vectors whose fourth lane is
// never stored, and the stop-dead arm stores three words of a stack quad
// and then copies all four into P and L, so their w lanes take whatever
// was on the stack.
void physicscar_bottom_out(PhysicsCar *pc);

// 0x00135b70. A free function, called only from Move, which passes the
// yaw, wheel 2's EBrake, the speed, the CTI's two yaw controls, the
// CarState's DriverMode, the z of the body's forward axis by reference and
// Car::GetPostCollisionYawControlBoost. The names are the port's, from
// that call. `*tilt` is replaced by its absolute value on the way through.
//
//   base    = |tilt| + 1
//   control = yawControl + (driverMode ? boost * NFS : NFS)
//   handbrake on and |yaw| under 20 degrees: base
//   else: base + min(|yaw| * control * t, MaxYawBonus)
//
// with t running LowSpeedYawBoost .. HighSpeedYawBoost across LowSpeedSpeed
// .. HighSpeedSpeed, and not clamped at either end.
float YawFrictionBoost(float yaw, float ebrake, float speed,
                       float yawControl, float yawControlNFS,
                       int32_t driverMode, float *tilt,
                       float postCollisionBoost);

// 0x00135c20. Wheels 0 and 1 get `BrakeBias * 2`; 2 and 3 get
// `(1 - BrakeBias) * 2`, done in double -- `fptodp`, `dpsub`, `dpadd`,
// `dptofp` -- and rounded back once.
float physicscar_get_brake_settings(const PhysicsCar *pc, int32_t wheel);

// 0x00136bb8. Loads the body, the four corners, the engine and the
// drivetrain from the CarState. TestRPM (car.h) overrides the RPM unless
// it holds its shipped 100.
void physicscar_initialize_state_from_car(PhysicsCar *pc);

// 0x00136cc8. The body's ResolveForces through its table, the downforce
// fed to each Suspension (zero unless UseMagicForce), IterateForces, each
// Suspension's second pass and JumpStabilizer, timed into IterateTime and
// ResolveTime. The ticker read between the Suspensions and IterateForces
// is discarded, as the image discards it.
void physicscar_resolve_forces(PhysicsCar *pc);

// 0x00136df8. Five passes of the tyre forces against the body's
// acceleration, between a guess and a finalise. See the document.
void physicscar_iterate_forces(PhysicsCar *pc);

// 0x00137038. Copies the simulation back into the CarState. `dt` is not
// read.
void physicscar_update_car(PhysicsCar *pc, float dt);

// 0x00137340. The catch-up multiplier into the engine, the body, the
// aerodynamics and every wheel, and the draft into the aerodynamics.
void physicscar_set_boost(PhysicsCar *pc, float f);

// 0x001373a0. With fewer than two wheels down, a moment against the spin,
// scaled by the mass and by JumpStabilization at the spin's magnitude.
void physicscar_jump_stabilizer(PhysicsCar *pc);

// 0x001374c8. `jr ra ; swc1 $f12,108(a0)`, retail's 112.
void physicscar_set_friction_boost(PhysicsCar *pc, float f);

// Retail's 0x00137450, the table's DoSnapshot: a section named
// "PhysicsCar" around FrictionBoost, the body, the steering (through its
// table), each wheel then its suspension, the engine, the drive train, the
// aerodynamics, CarMover's empty one, YawControlMultiplier, the two brake
// stand Timers and two bools, LurchsLeft and the flipped Timer.
struct ReplaySnapshot;
void physicscar_do_snapshot(PhysicsCar *pc, struct ReplaySnapshot *s);

// 0x00135c78, the CarMover entry: one frame of the car. In order:
//
//   * the boost from the CarState, and a fresh Calibrate;
//   * the driver's pedals tidied -- with the throttle ahead of both
//     brakes, a brake under half travel is dropped, and otherwise a
//     throttle under half is -- then the steering, the throttle, the sport
//     gear, the nitro and the gear;
//   * the body's motion damping, the burn-out (REAL_CONTROL on a pad, not
//     a wheel), and the yaw-control multiplier the handbrake winds down;
//   * per wheel, the brake, the handbrake and the traction boost, with the
//     yaw-friction boost worked out at wheel 2 and carried into wheel 3,
//     then the blown-tyre and override cuts;
//   * the aerodynamics, the body's yaw-moment clamp and its speed limiter;
//   * IntegrateEuler in equal steps of at most MaximumTimeStep, with the
//     pre-race brake-stand, or in the race the debug dyno, after each;
//   * UpdateCar, and the skid marks.
//
// Returns dt. pCurrentRace (race.h) must be set: the stage is read
// through it with no NULL test.
//
// **Three things the image does that read like slips**, all ported as
// they are:
//
//   * a blown tyre cuts the traction of all four wheels. The per-wheel
//     test is `(1 << i) != 0`, not `BlownTireBits & (1 << i)`;
//   * the burn-out state is stored before Car::IsBlinking is asked, so a
//     blinking car enters the state with last time's BurnOutTime and
//     BurnOutTraction;
//   * the brake-stand stores three words of a stack quad and copies four
//     into the body's momentum, so P.w takes whatever was on the stack.
//     The port zeroes it.
float physicscar_move(PhysicsCar *pc, float dt);

#endif
