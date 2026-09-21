// suspension -- Suspension.obj (0x0019bc58 .. 0x0019c468).
//
// 29 methods. One corner of the car: a spring and a damper along the
// wheel's z axis, a sway bar tying it to the corner on the other side, and
// the bookkeeping that turns the result into a wheel matrix and a force on
// the body. Sixth slice of task 25, after CarState, Engine, CarTypeInfo,
// CarDriver, Steering and RigidBody.
//
// It is a PhysicsComponent, so the integrator can walk it, but it is an
// odd one: GetDerivative (0x0019c170) writes two zeroes and returns. The
// state does not integrate. ComputeAuxiliaries recomputes z from the
// ground every frame and differences it for v, which is why the record
// keeps the previous z only long enough to subtract it.
//
// Written up in docs/formats/car-suspension.md.
#ifndef SUSPENSION_H
#define SUSPENSION_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "cartypeinfo.h"
#include "rigidbody.h"
#include "steering.h"
#include "wheel.h"

// 0x00298fb0, 72 bytes -- eighteen slots. The base's is rigidbody.h's
// PHYSICSCOMPONENT_VTABLE. Recorded because the constructor writes it and
// a later dispatching slice will want the value.
#define SUSPENSION_VTABLE 0x00298fb0u

// GetSize (0x0019c410) is `addiu v0,zero,2`: two floats, which is
// sizeof(SuspensionState) / 4. Unlike RigidBody's 32-for-29, this one is
// honest -- both floats are moved by GetState and SetState.
#define SUSPENSION_STATE_FLOATS 2

// --------------------------------------------------------- the tuning set
//
// Ten globals in .sdata that the suspension and tyre code share, with the
// values the shipped ELF has. They are writable and the debug menu moved
// them, so the port keeps them as variables rather than folding them in.
//
// Two are worth reading twice. **GroundPenaltyForce ships as 0.0**, so the
// penetration term ComputeAuxiliaries computes so carefully adds nothing
// to Force in this build -- the same shape as the camera's structurally
// zero velocity record. And **UglyTimestepHack ships as 1.0**, so the
// velocity difference is divided by one; it is a timestep that is not a
// timestep, and the name is the image's, not this port's.
extern float   gLoadFactor;               // 0x00323d60  0.8
extern int32_t gWheelForceFrame;          // 0x00323d64  1
extern float   gTireForceEllipseRatio;    // 0x00323d68  1.5
extern float   gNoSlipCorrectionFactor;   // 0x00323d6c  0.1
extern float   gUglyTimestepHack;         // 0x00323d70  1.0
extern float   gGroundPenaltyImpulse;     // 0x00323d74  0.2
extern float   gGroundPenaltyForce;       // 0x00323d78  0.0
extern float   gMaxGroundPenetration;     // 0x00323d7c  0.15
extern float   gProgressiveDampingFactor; // 0x00323d80  0.1
extern int32_t gNoWheels;                 // 0x00323d84  0

// The two literals ComputeAuxiliaries reaches for out of .lit4, kept as
// named constants because both are load-bearing. gp-29660 is the epsilon
// the timestep is tested against; gp-29656 is the quarter turn that turns
// bSinF into a cosine.
//
// That second word is 0x3fc90fdc, and it is the *same* pool entry
// Steering loads -- float(pi/2) is 0x3fc90fdb, so this is the one-ulp-high
// variant, not a rounded 1.5708f. The two objects were compiled against
// one constant and the port has to spell it the same way in both; see
// STEERING_IMAGE_HALF_PI, which is the same number.
#define SUSPENSION_TIMESTEP_EPSILON 0.0001f      // 0x38d1b717
#define SUSPENSION_IMAGE_HALF_PI    1.57079649f  // 0x3fc90fdc

// ------------------------------------------------------- SuspensionState

// 8 bytes. z is the suspension height and v its rate of change.
typedef struct SuspensionState {
    float z; // 0
    float v; // 4
} SuspensionState;

// ------------------------------------------------------------ Suspension

// 176 bytes on the PS2, on the same PhysicsComponent base RigidBody has:
// two list links and the vtable pointer at 8. SuspensionInfo and WheelInfo
// are cartypeinfo.h's -- the car type owns them and the suspension only
// points at one.
//
// Two paddings are written down rather than left to the compiler. The gap
// at 124 is the PS2 quadword-aligning RestPosition; the twelve bytes at
// 164 are the tail padding that takes the record to 176. Neither target
// gives bVector4 sixteen-byte alignment on its own, so an implicit version
// of either is four or twelve bytes of nothing -- the mistake steering.h
// had made and this header does not repeat.
typedef struct Suspension {
    uint32_t  pNext;                  //   0  bNode, owned by the list
    uint32_t  pPrev;                  //   4
    uint32_t  _vtable;                //   8
    const SuspensionInfo *SI;         //  12
    struct Suspension    *pSwayBar;   //  16  the opposite corner, not owned
    SuspensionState State;            //  20
    float     Force;                  //  28
    bVector4  Position;               //  32  wheel centre, body frame
    bMatrix4  Matrix;                 //  48  Position as a translation
    int32_t   TouchingGround;         // 112
    float     MagicForce;             // 116
    float     RestLoad;               // 120
    uint8_t   _pad0[4];               // 124  RestPosition is 16-aligned
    bVector4  RestPosition;           // 128
    Wheel    *pWheel;                 // 144  not owned
    RigidBody *pBody;                 // 148  not owned
    Steering  *pSteering;             // 152  not owned, and may be NULL
    int32_t   WheelPosition;          // 156  index into the steering matrices
    float     GroundForce;            // 160
    uint8_t   _pad1[12];              // 164  tail padding to 176
} Suspension;                         // 176

// The widening on a 64-bit host, and this one does not fit in a single
// term the way CarState's and RigidBody's do. Five real pointers are
// spread through the record rather than gathered at the front, so the
// offset of a field depends on how many of them precede it -- and on two
// bytes of alignment padding the host inserts in front of SI and pWheel
// and the PS2 does not.
//
// Counted in SUSPENSION_SLACK, the multiplier climbs 1, 2, 3 across the
// front, sits at 3 for the whole span from State to RestPosition, and then
// climbs again 4, 5, 6, 7 through the four pointers at the back. The
// assert below spells out every one rather than hiding them, because the
// alternative is a single term that is right by accident.
#define SUSPENSION_SLACK ((size_t)(sizeof(void *) - 4))

// The record rounds up to the pointer's alignment, so the host's 204 bytes
// of fields become 208 and the handheld's 176 stay 176.
#define SUSPENSION_SIZEOF                                                   \
    ((size_t)((176 + 7 * SUSPENSION_SLACK + sizeof(void *) - 1)             \
              / sizeof(void *) * sizeof(void *)))

#ifndef SUSPENSION_NO_ASSERT
typedef char suspension_layout_check[
    (offsetof(Suspension, pNext) == 0
     && offsetof(Suspension, pPrev) == 4
     && offsetof(Suspension, _vtable) == 8
     && offsetof(Suspension, SI) == 12 + 1 * SUSPENSION_SLACK
     && offsetof(Suspension, pSwayBar) == 16 + 2 * SUSPENSION_SLACK
     && offsetof(Suspension, State) == 20 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, Force) == 28 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, Position) == 32 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, Matrix) == 48 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, TouchingGround) == 112 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, MagicForce) == 116 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, RestLoad) == 120 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, RestPosition) == 128 + 3 * SUSPENSION_SLACK
     && offsetof(Suspension, pWheel) == 144 + 4 * SUSPENSION_SLACK
     && offsetof(Suspension, pBody) == 148 + 5 * SUSPENSION_SLACK
     && offsetof(Suspension, pSteering) == 152 + 6 * SUSPENSION_SLACK
     && offsetof(Suspension, WheelPosition) == 156 + 7 * SUSPENSION_SLACK
     && offsetof(Suspension, GroundForce) == 160 + 7 * SUSPENSION_SLACK
     && sizeof(Suspension) == SUSPENSION_SIZEOF
     && sizeof(SuspensionState) == 8
     && sizeof(SuspensionInfo) == 32) ? 1 : -1];
#endif

// --------------------------------------------------------------- lifetime

// 0x0019bc58. Nine stores and no arithmetic. Note what it does *not* do:
// SI, the three object pointers and WheelPosition are written, pSwayBar is
// nulled, and everything else -- State, Force, Position, Matrix,
// TouchingGround, RestLoad, RestPosition -- is left as the allocation
// found it. Calibrate and ComputeAuxiliaries are expected to run first.
Suspension *suspension_init(Suspension *s, int32_t wheelPosition,
                            RigidBody *body, Wheel *wheel,
                            Steering *steering, const SuspensionInfo *si);

// 0x0019c418. Runs the PhysicsComponent destructor and, if the flag says
// so, the slot-pool delete. The port has neither, so this only unhooks.
void suspension_fini(Suspension *s);

// 0x0019bd40. RestLoad = load, and RestPosition = the wheel's own position
// minus the body's centre of gravity.
//
// The subtraction is a whole quadword, and WheelInfo::Position is three
// bare floats with Radius behind it, so **RestPosition.w comes out as
// WI->Radius - pBody->CenterOfGravity.w**. Nothing reads it -- every later
// use of RestPosition goes through bMulMatrixVec3, which forces w to 1 --
// but the port reproduces it rather than zeroing a lane the image fills.
void suspension_calibrate(Suspension *s, float load);

// ------------------------------------------------------------ the state

// 0x0019bd68. Zeroes z and v. The no-argument overload; the one that takes
// a float array is suspension_set_state_array.
void suspension_set_state(Suspension *s);

// 0x0019c3f0 and 0x0019c3d8. Two floats each way.
void suspension_get_state_array(const Suspension *s, float *out);
void suspension_set_state_array(Suspension *s, const float *in);

// 0x0019c408 and 0x0019c410.
SuspensionState *suspension_get_state(Suspension *s);
int32_t          suspension_get_size(const Suspension *s);

// 0x0019c170. Writes two zeroes and returns the pointer it was given. The
// suspension does not integrate; see the note at the top.
float *suspension_get_derivative(Suspension *s, float *out);

// --------------------------------------------------------- the main pass

// 0x0019bd78, 872 bytes and the whole of the object's arithmetic. In
// order: put the rest position in the world and ask the wheel what is
// under it; clamp the resulting height between the two bump stops and set
// TouchingGround; difference z for v; build the wheel's matrix, steer it,
// wobble it by the damage, and hand both the car-frame and world-frame
// copies to the wheel along with the velocity of the contact point; then
// spring, damper, sway bar and penetration into Force.
//
// **It dereferences pSwayBar unconditionally** whenever TouchingGround is
// set, and the constructor leaves that NULL. SetSwayBar has to have been
// called. The port does not add a guard the image does not have.
void suspension_compute_auxiliaries(Suspension *s);

// 0x0019c0e0. GroundForce = Wheel::ExchangeZForces(TouchingGround, Force
// plus the argument when the wheel is down). The added term is skipped
// when the wheel is in the air but Force is passed either way.
void suspension_resolve_forces(Suspension *s, float extra);

// 0x0019c120. When the wheel is down, applies the wheel's
// WorldGroundForce at the contact point. Does nothing at all when
// gNoWheels is set -- and the vector is still computed first, so the
// debug flag skips the force and not the arithmetic.
void suspension_resolve_more_forces(Suspension *s);

// 0x0019c1b8. The impulse that stops a wheel sinking into the ground.
// Returns the magnitude applied, or zero when the contact point is already
// moving away from the surface. gNoWheels skips the ApplyImpulse and still
// returns the magnitude.
float suspension_apply_ground_penalty_impulse(Suspension *s);

// 0x0019c180. A free function in this object, not a method: the velocity
// of a point offset r from a body's centre, v + w x r.
//
// The cross product is `vopmula.xyz`/`vopmsub.xyz`, which leaves the w
// lane of its first operand alone, so the addition that follows carries
// **w = v.w + w.w** into the result. Three of this object's four vector
// expressions have a w lane like this and the port keeps all of them.
void suspension_get_point_velocity(bVector4 *out, const bVector4 *v,
                                   const bVector4 *w, const bVector4 *r);

// ------------------------------------------------------------- accessors

// 0x0019c2b8, 0x0019c2f8, 0x0019c308 -- straight out of SuspensionInfo.
float suspension_get_sway_bar_stiffness(const Suspension *s);
float suspension_get_stiffness(const Suspension *s);
float suspension_get_progression(const Suspension *s);

// 0x0019c2c8. SI->Damping[1] while the suspension is compressing or still
// (v <= 0) and SI->Damping[0] while it extends.
float suspension_get_damping(const Suspension *s);

// 0x0019c320. Zero while the suspension is inside its rendering limit, and
// **MaxRenderingCompression - z, which is negative or zero, once it is
// past it**. The sign is the image's: this is an offset to add, not a
// depth.
float suspension_get_compression_hack_offset(const Suspension *s);

// 0x0019c3b0. z has been clamped to exactly SI->BumpStop[0], compared with
// `c.eq.s` rather than a tolerance.
int32_t suspension_is_bottomed_out(const Suspension *s);

// 0x0019c3a8, 0x0019c3a0, 0x0019c350.
float   suspension_get_height(const Suspension *s);
float   suspension_get_velocity(const Suspension *s);
int32_t suspension_get_wheel_position(const Suspension *s);

// 0x0019c358, 0x0019c360 -- pointers into the object.
bVector4 *suspension_get_rest_position(Suspension *s);
bMatrix4 *suspension_get_matrix(Suspension *s);

// 0x0019c368, 0x0019c318.
void suspension_set_sway_bar(Suspension *s, Suspension *other);
void suspension_set_magic_force(Suspension *s, float f);

// Suspension::DoSnapshot (0x0019bc88) is not ported: ReplaySnapshot again,
// the same dependency that has held up CarState, Engine, CarDriver,
// Steering and RigidBody. operator new and operator delete are the PS2
// slot allocator and are not ported for the usual reason.

#endif // SUSPENSION_H
