// mellowmover -- MellowMover.obj (0x00206448 .. 0x002086f8): MellowMover
// and the Mellovator it drives.
//
// A MellowMover is the cheap car. Where a PhysicsCar integrates four
// Suspensions, four Wheels, an Engine and a DriveTrain, a MellowMover's
// PhysicsSystem holds two components -- a RigidBody and a Mellovator -- and
// the Mellovator does everything else in closed form: the suspension is a
// spring force computed from a ground query each step, the engine is two
// table lookups, the gearbox is a pair of shift tables, and the tyres are a
// linear slip model with a friction circle. Its state is the four wheels'
// angular velocities and nothing more. `Car::SetMovementMode` builds one for
// the cars the game does not need to simulate properly: traffic, and the
// AI cars far from the camera.
//
// Two bases, laid out as PhysicsCar's are: CarMover at 0, PhysicsVehicle at
// 8 with its vptr at 20, and the second table's delta turns the
// PhysicsVehicle pointer back into the MellowMover. The four Wheels are not
// components. They are built only so the car has something to render and
// skid with: UpdateCar places them from the Mellovator's answers, and
// nothing integrates them.
//
// The two DoSnapshots (0x002066e0 and 0x002071b8; retail 0x002198c8 and
// 0x0021a3d8) are the replay's, since TASKS 72c. The Mellovator's is in no
// table: MellowMover's calls it directly.
//
// The addresses below are the demo's. Retail's MellowMover.obj is at
// 0x00219628 .. 0x0021b910: the ctor 0x00219628, dtor 0x002197f0,
// Calibrate 0x00219978, InitializeStateFromCar 0x002199c8, UpdateCar
// 0x00219a60, Move 0x00219d38, ComputeAuxiliaries 0x00219ed8, ResolveForces
// 0x00219f50, SetBoost 0x00219f98, JumpStabilizer 0x0021a040; the
// Mellovator's ctor 0x0021a268, Calibrate 0x0021a5c0, GetDerivative
// 0x0021a680, ComputeAuxiliaries 0x0021a8c8, ComputeSuspensionForces
// 0x0021ab10, GetGroundHeightAndWheelPos 0x0021add8, ResolveForces
// 0x0021aed8 and BottomOut 0x0021b498; the static init 0x0021b640. Retail
// changed four things, all ported (TASKS 74): the ctor zeroes
// gUglyTimestepHack before the Mellovator's allocation; UpdateCar draws no
// wheel above its axle's MaxRenderingCompression; Move brakes with
// max(Brake, EBrake * 0.5); and the force-feedback graph starts at 0.3, not
// 0.4. Everything else is the demo's instruction for instruction.
//
// See docs/formats/mellow-mover.md.

#ifndef MELLOWMOVER_H
#define MELLOWMOVER_H

#include <stddef.h>
#include <stdint.h>

#include "aerodynamics.h"
#include "car.h"
#include "cardriver.h"
#include "cartypeinfo.h"
#include "carstate.h"
#include "drivetrain.h"   // Gear and its values
#include "graph.h"
#include "physicscar.h"   // CarMover, CARMOVER_VTABLE, PHYSICSVEHICLE_VTABLE
#include "physicssystem.h"
#include "rigidbody.h"
#include "table.h"
#include "wheel.h"

// ------------------------------------------------------------ Mellovator

// 448 bytes. A PhysicsComponent -- bNode and vptr in the first twelve --
// whose constructor never calls PhysicsComponent's: it stores its own vptr
// and leaves the links to the pool's zeroed slot and AddComponent. The
// names are the mdebug record's; State is a MellovatorState, sixteen bytes
// of `ww[4]`, the four wheels' angular velocities in rad/s.
typedef struct MellovatorState {
    float ww[4];
} MellovatorState;

typedef struct Mellovator {
    uint32_t           pNext;                 //   0  bNode, a p32 handle
    uint32_t           pPrev;                 //   4
    uint32_t           _vtable;               //   8
    RigidBody         *pBody;                 //  12
    const CarTypeInfo *CTI;                   //  16
    TopologyCoordinate *TC;                   //  20  the CarState's
    MellovatorState    State;                 //  24
    float              SuspensionPosition[4]; //  40
    float              SuspensionVelocity[4]; //  56
    float              SuspensionForce[4];    //  72
    int32_t            TouchingGround[4];     //  88  bool, stored as a word
    bVector2           WheelForce[4];         // 104  body-frame x and y
    bVector2           WheelSlip[4];          // 136  longitudinal, lateral
    int32_t            bSlipping[4];          // 168  bool, stored as a word
    int32_t            BrakeLocked[4];        // 184  bool, stored as a word
    float              GroundPenetration[4];  // 200
    uint8_t            _pad216[8];            // 216  nothing reads it
    bVector3           GroundNormal[4];       // 224
    float              RPM;                   // 288
    Gear               CurrentGear;           // 292
    float              Throttle;              // 296
    float              Brake;                 // 300
    uint16_t           Steering;              // 304  a BAM; sh / lhu
    uint8_t            _pad306[2];            // 306  sh leaves it
    Gear               DesiredGear;           // 308
    float              CurrentBoost;          // 312
    float              CurrentFrictionBoost;  // 316
    float              RestLoad[4];           // 320
    Table              TorqueCurve;           // 336
    Table              EngineBraking;         // 356
    float              ShiftUpRPM[9];         // 376
    float              ShiftDownRPM[9];       // 412
} Mellovator;                                 // 448

// The three pointers widen the record by four bytes each on the host, and
// each Table by four more. The k in MELLOVATOR_AT counts them.
#define MELLOWMOVER_SLACK ((size_t)(sizeof(void *) - 4))
#define MELLOVATOR_AT(f, n, k) \
    (offsetof(Mellovator, f) == (size_t)(n) + (k) * MELLOWMOVER_SLACK)

#ifndef MELLOWMOVER_NO_ASSERT
typedef char mellovator_layout_check[
    (MELLOVATOR_AT(_vtable, 8, 0)
     && MELLOVATOR_AT(pBody, 12, 1)
     && MELLOVATOR_AT(CTI, 16, 2)
     && MELLOVATOR_AT(TC, 20, 3)
     && MELLOVATOR_AT(State, 24, 4)
     && MELLOVATOR_AT(SuspensionPosition, 40, 4)
     && MELLOVATOR_AT(SuspensionVelocity, 56, 4)
     && MELLOVATOR_AT(SuspensionForce, 72, 4)
     && MELLOVATOR_AT(TouchingGround, 88, 4)
     && MELLOVATOR_AT(WheelForce, 104, 4)
     && MELLOVATOR_AT(WheelSlip, 136, 4)
     && MELLOVATOR_AT(bSlipping, 168, 4)
     && MELLOVATOR_AT(BrakeLocked, 184, 4)
     && MELLOVATOR_AT(GroundPenetration, 200, 4)
     && MELLOVATOR_AT(GroundNormal, 224, 4)
     && MELLOVATOR_AT(RPM, 288, 4)
     && MELLOVATOR_AT(CurrentGear, 292, 4)
     && MELLOVATOR_AT(Throttle, 296, 4)
     && MELLOVATOR_AT(Brake, 300, 4)
     && MELLOVATOR_AT(Steering, 304, 4)
     && MELLOVATOR_AT(DesiredGear, 308, 4)
     && MELLOVATOR_AT(CurrentBoost, 312, 4)
     && MELLOVATOR_AT(CurrentFrictionBoost, 316, 4)
     && MELLOVATOR_AT(RestLoad, 320, 4)
     && MELLOVATOR_AT(TorqueCurve, 336, 4)
     && MELLOVATOR_AT(EngineBraking, 356, 5)
     && MELLOVATOR_AT(ShiftUpRPM, 376, 6)
     && MELLOVATOR_AT(ShiftDownRPM, 412, 6)
     && sizeof(Mellovator) == 448 + 6 * MELLOWMOVER_SLACK) ? 1 : -1];
#endif

// _vt$10Mellovator, 0x0029f2c8, PhysicsComponent's nine entries: the
// destructor (0x002085d0), GetSize (0x002086b8, 4), GetState()
// (0x002086b0), GetState(float *) (0x00208688), SetState(float *)
// (0x00208660), ResolveForces (0x00207cb8), GetDerivative (0x00207460) and
// ComputeAuxiliaries (0x002076a8).
#define MELLOVATOR_VTABLE     0x0029f2c8u
#define MELLOVATOR_VT_ENTRIES 9

// 0x00207048. The vptr, the two tables -- TorqueCurve over the engine's
// nine torque entries and EngineBraking over its three, both from IdleRPM
// to MaxRPM -- CTI, the shift points at scale 1, then pBody, TC,
// CurrentBoost = 1 and CurrentGear = FIRST_GEAR. Nothing else is written:
// the rest of the record is the pool's zeroes.
Mellovator *mellovator_init(Mellovator *m, const CarTypeInfo *cti,
                            RigidBody *body, TopologyCoordinate *tc);

// 0x002085d0. The vptr, ~PhysicsComponent(this, 0), and operator delete
// when flags & 1.
void mellovator_destroy(Mellovator *m, int32_t flags);

// 0x00208640 / 0x00208630. bOMalloc and bFree on MellovatorSlotPool.
Mellovator *mellovator_new(void);
void        mellovator_delete(void *p);

// 0x002073a0. The rest load of each wheel: the weight of the car plus the
// aero's AutoBalanceDownforce times `downforce`, split front to rear by the
// wheelbase about the centre of gravity -- `cog` is CTI's x when
// UseNewSuspensionCalibration is set and 0 when it is not -- and halved
// across each axle. The rears are stored first.
void mellovator_calibrate(Mellovator *m, float downforce);

// 0x00207418. The four wheel speeds, then BrakeLocked and
// SuspensionPosition cleared in one loop.
void mellovator_set_state4(Mellovator *m, float w0, float w1, float w2,
                           float w3);

// 0x00208660 / 0x00208688 / 0x002086b0 / 0x002086b8. The state is State.ww,
// four floats, copied as two doublewords.
void    mellovator_set_state(Mellovator *m, const float *in);
void    mellovator_get_state(const Mellovator *m, float *out);
float  *mellovator_state(Mellovator *m);
int32_t mellovator_get_size(const Mellovator *m);

// 0x00207460. d[i] = (torque - WheelForce[i].x * feedback) * 124.99999,
// where the torque is the drive -- rear wheels only, from the two tables
// at RPM / CurrentBoost, through the final drive and half the gear ratio --
// plus the brake, and the feedback is MellowForceFeedbackGraph at the
// body's speed. Boost above 1 scales the drive up and, on the rears, the
// feedback down. A locked wheel's derivative is 0.
float *mellovator_get_derivative(Mellovator *m, float *d);

// 0x002076a8. The suspension, then the brake locks -- a wheel below 30
// rad/s under more than 0.95 of brake stops dead and locks, and every lock
// lets go below 0.2 -- then the engine speed from the rear wheels and the
// automatic box. The RPM is clamped to [IdleRPM, MaxRPM] last.
void mellovator_compute_auxiliaries(Mellovator *m);

// 0x002078f0. Each wheel's compression from the ground under it, along the
// body's up axis, clamped to the bump stops, and the spring, damper and
// sway-bar force that comes of it. GroundPenetration is how far past the
// upper stop the ground is.
void mellovator_compute_suspension_forces(Mellovator *m);

// 0x00207bb8. Each wheel's hub in world space and the ground's height and
// normal under it. `pos` and `height` are four each.
void mellovator_get_ground_height_and_wheel_pos(Mellovator *m, bVector3 *pos,
                                                float *height);

// 0x00207cb8. The tyre forces: each grounded wheel's slip against the
// ground, a force against it limited to a friction circle, and a hold
// against the slope when the brakes are locked or the car is stopped on
// them. Every wheel applies its force, grounded or not -- an airborne one
// applies its suspension force alone.
void mellovator_resolve_forces(Mellovator *m);

// 0x00208278. For each wheel pressed past its stop, an impulse against the
// ground's normal proportional to the speed the hub is closing at. Returns
// the sum and adds each to the CarState's WheelBottomOutMagnitude.
float mellovator_bottom_out(Mellovator *m, CarState *cs);

// The one-line accessors, 0x00208410 .. 0x002085c8.
void     mellovator_set_throttle(Mellovator *m, float f);
void     mellovator_set_brake(Mellovator *m, float f);
void     mellovator_set_steering(Mellovator *m, uint16_t bam);
void     mellovator_set_desired_gear(Mellovator *m, Gear g);
void     mellovator_set_current_boost(Mellovator *m, float f);
void     mellovator_set_current_friction_boost(Mellovator *m, float f);
float    mellovator_get_rpm(const Mellovator *m);
Gear     mellovator_get_current_gear(const Mellovator *m);
int32_t  mellovator_get_touching_ground(const Mellovator *m, int32_t i);
float    mellovator_get_suspension_force(const Mellovator *m, int32_t i);
float    mellovator_get_suspension_position(const Mellovator *m, int32_t i);
float    mellovator_get_wheel_angular_velocity(const Mellovator *m, int32_t i);
bVector2 *mellovator_get_wheel_slip(Mellovator *m, int32_t i);
int32_t  mellovator_get_wheel_slipping(const Mellovator *m, int32_t i);

// ----------------------------------------------------------- MellowMover

// 64 bytes. The mdebug record names every field but the two bases and
// pMellovator, which it lists among the methods.
typedef struct MellowMover {
    CarMover           Mover;          //  0  Driver 0, vptr 4
    PhysicsSystem      Vehicle;        //  8  PhysicsVehicle; vptr at 20
    RigidBody         *pBody;          // 24
    Mellovator        *pMellovator;    // 28
    Aerodynamics      *pAerodynamics;  // 32
    const CarTypeInfo *CTI;            // 36
    CarState          *State;          // 40  the Car's own
    Car               *pCar;           // 44
    Wheel             *pWheels[4];     // 48
} MellowMover;                         // 64

#define MELLOWMOVER_AT(f, n, k) \
    (offsetof(MellowMover, f) == (size_t)(n) + (k) * MELLOWMOVER_SLACK)

#ifndef MELLOWMOVER_NO_ASSERT
typedef char mellowmover_layout_check[
    (MELLOWMOVER_AT(Vehicle, 8, 2)
     && MELLOWMOVER_AT(pBody, 24, 2)
     && MELLOWMOVER_AT(pMellovator, 28, 3)
     && MELLOWMOVER_AT(pAerodynamics, 32, 4)
     && MELLOWMOVER_AT(CTI, 36, 5)
     && MELLOWMOVER_AT(State, 40, 6)
     && MELLOWMOVER_AT(pCar, 44, 7)
     && MELLOWMOVER_AT(pWheels, 48, 8)
     && sizeof(MellowMover) == 64 + 12 * MELLOWMOVER_SLACK) ? 1 : -1];
#endif

// _vt$11MellowMover, 0x0029f330, CarMover's layout: the destructor
// (0x00206608), Move (0x00206b28) and DoSnapshot (0x002066e0).
#define MELLOWMOVER_VTABLE 0x0029f330u

// _vt$11MellowMover$14PhysicsVehicle, 0x0029f310, PhysicsSystem's layout
// with delta -8 everywhere: the same destructor, ComputeAuxiliaries
// (0x00206cb8) and ResolveForces (0x00206d30).
#define MELLOWMOVER_VEHICLE_VTABLE 0x0029f310u

#define MELLOWMOVER_VT_ENTRIES 4

// Installs the three tables. The game calls it once at boot, after
// physicscar_install_vtables; a harness calls it after vt_reset().
void mellowmover_install_vtables(void);

// 0x00206448. Both bases, the fields, then a RigidBody and a Mellovator
// from their pools as the system's two components, an Aerodynamics
// (inline, as PhysicsCar's is), the body's SpeedLimiter, Calibrate -- with
// no wheels yet -- the four Wheels, InitializeStateFromCar and
// ComputeAuxiliaries.
MellowMover *mellowmover_init(MellowMover *mm, Car *car,
                              const CarTypeInfo *cti, CarDriver *driver,
                              CarState *cs);

// 0x00206608. Both vptrs, the Aerodynamics, each non-NULL wheel through
// its own destructor with flags 3, ~PhysicsVehicle -- which destroys the
// body and the Mellovator -- ~CarMover(this, 0), and operator delete when
// flags & 1.
void mellowmover_destroy(MellowMover *mm, int32_t flags);

// 0x002086d0 / 0x002086c0. bOMalloc and bFree on MellowMoverSlotPool.
MellowMover *mellowmover_new(void);
void         mellowmover_delete(void *p);

// 0x00206790. The body's centre of gravity and inertia, then the
// Mellovator's rest loads at the downforce the car's ForwardSpeed makes.
void mellowmover_calibrate(MellowMover *mm);

// 0x002067e0. The driver's four controls into the Mellovator, the body
// from the CarState, the wheel speeds, and a virtual ComputeAuxiliaries.
void mellowmover_initialize_state_from_car(MellowMover *mm);

// 0x00206b28. Calibrate, the controls, the aero's ground effect and
// throttle, SetBoost, then IntegrateEuler in as many equal steps as keep
// each at or under MaxiMellowTimeStep, orthonormalising R after each.
// UpdateCar last. Returns dt.
float mellowmover_move(MellowMover *mm, float dt);

// 0x00206878. The body and the Mellovator back into the CarState and the
// wheels.
void mellowmover_update_car(MellowMover *mm, float dt);

// 0x00206cb8. The system's ComputeAuxiliaries; again if BottomOut pushed
// anything; then a virtual ResolveForces.
void mellowmover_compute_auxiliaries(MellowMover *mm);

// 0x00206d30. The Mellovator's ResolveForces through its vptr, the aero,
// and the jump stabiliser. The RigidBody's own ResolveForces is not
// called -- it is empty.
void mellowmover_resolve_forces(MellowMover *mm);

// 0x00206d78. The aero's boost is the CarState's BoostFactor, not `f`;
// `f` goes to the body's catch-up multiplier and the Mellovator's boost,
// and to its friction boost cut by 0.3 for a driver in mode 1 above 30
// mph.
void mellowmover_set_boost(MellowMover *mm, float f);

// The replay's. Retail 0x0021a3d8, a "Mellovator" section: State's sixteen
// bytes; for each wheel its suspension position, velocity and force,
// TouchingGround's low byte, WheelForce, WheelSlip, bSlipping,
// BrakeLocked's low byte, GroundPenetration and GroundNormal; then RPM,
// CurrentGear's low byte, Throttle, Brake, Steering, DesiredGear's low
// byte and the two boosts. Retail 0x002198c8, slot 24, a "MellowMover"
// section begun with the object: the RigidBody, the Mellovator, the
// Aerodynamics, the four Wheels and CarMover's (nothing).
struct ReplaySnapshot;
void mellovator_do_snapshot(Mellovator *m, struct ReplaySnapshot *s);
void mellowmover_do_snapshot(MellowMover *mm, struct ReplaySnapshot *s);

// 0x00206e20. With fewer than two wheels down, a moment against the spin
// from MellowJumpStabilization. With none down and the car still the
// right way up, two more that turn the nose into the direction of travel
// and level the side axis.
void mellowmover_jump_stabilizer(MellowMover *mm);

// ------------------------------------------------------------ the tuning

// MellowMover.obj's .sdata and .sbss.
extern Graph MellowForceFeedbackGraph;      // gp-16824  the initialiser's
extern float MaxiMellowTimeStep;            // gp-16816  0x3c09a027, 0.0084
extern Graph MellowJumpStabilization;       // gp-16808  the initialiser's

// 0x00208420, _GLOBAL_$I$MellowForceFeedbackGraph: the two graphs.
void mellowmover_static_init(void);

#endif
