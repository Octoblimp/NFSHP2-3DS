// rigidbody -- RigidBody.obj (0x00192ca0 .. 0x0019400c), plus the two
// PhysicsComponent stubs it inherits.
//
// The rigid-body integrator state for every physical object in the game.
// `Suspension`, `PhysicsCar` and `Car` all hold one or point at one, which
// is why it comes before them in the port order even though the task list
// never named it.
//
// It is a classic Baraff-style rigid body: the *state* is position,
// orientation, linear momentum and angular momentum, and the derivative is
// velocity, `star(omega) * R`, force and moment. Velocity, angular velocity
// and the world inertia tensor are auxiliaries recomputed from the state
// rather than integrated.
//
// See docs/formats/rigid-body.md.

#ifndef RIGIDBODY_H
#define RIGIDBODY_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "table.h"

// ------------------------------------------------------------- constants

// The clamps in the four Apply* entry points. All four are magnitude
// limiters of the shape `if (cap < |v|) v *= cap / |v|`, and all four
// scale **all four lanes** including w, because the multiply is a
// `vmulx.xyzw`.
#define RIGIDBODY_MAX_FORCE     1200.0f   // 0x44960000
#define RIGIDBODY_MAX_MOMENT     100.0f   // 0x42c80000
#define RIGIDBODY_MAX_IMPULSE   1000.0f   // 0x447a0000
#define RIGIDBODY_MAX_ANG_IMPULSE 10.0f   // 0x41200000

// The gp pool GetDerivative and ComputeAuxiliaries read, at 0x00323bb0
// and 0x003216c4. Named after what they do rather than what they are,
// because several of them are the same number used for different things.
#define RIGIDBODY_GRAVITY          9.80000019f  // gp-20544
#define RIGIDBODY_LIMIT_BASE       1.89999998f  // gp-29996
#define RIGIDBODY_SPEED_SCALE      2.23602486f  // gp-29992
#define RIGIDBODY_HP_BONUS         1.02999997f  // gp-20488
#define RIGIDBODY_UPHILL_CLAMP     0.300000012f // gp-20524
#define RIGIDBODY_UPHILL_FLOOR     0.899999976f // gp-20528
#define RIGIDBODY_DOWNHILL_CLAMP   0.300000012f // gp-20532
#define RIGIDBODY_DOWNHILL_CEIL    1.10000002f  // gp-20536
#define RIGIDBODY_BRAKE_GAIN       5.0f         // gp-20516
#define RIGIDBODY_BRAKE_FLOOR     -0.5f         // gp-20520
#define RIGIDBODY_DAMP_SPEED_DIV   4.0f         // gp-20512
#define RIGIDBODY_DAMP_SPIN_DIV    2.0f         // gp-20508
#define RIGIDBODY_DAMP_RISE        0.100000001f // gp-20496
#define RIGIDBODY_DAMP_FALL       10.0f         // gp-20492
#define RIGIDBODY_DAMP_L_GAIN      2.0f         // gp-20500
#define RIGIDBODY_DAMP_P_GAIN      8.0f         // gp-20504

// _vt$9RigidBody at 0x002987e8, _vt$16PhysicsComponent at 0x00298728.
#define RIGIDBODY_VTABLE        0x002987e8u
#define PHYSICSCOMPONENT_VTABLE 0x00298728u

// GetSize (0x00193fb8) is `addiu v0,zero,32`: the integrator is told the
// state is 32 floats, which is sizeof(RigidBodyState). GetState/SetState
// only move 29 of them -- the last three are the tail padding after
// MotionDampingFactor and are never written or read.
#define RIGIDBODY_STATE_FLOATS 32
#define RIGIDBODY_STATE_USED   29

// ---------------------------------------------------------- RigidBodyInfo

// 80 bytes. Read-only per-body constants: the mass, a box extent that
// nothing in this object touches, and the body-frame inertia tensor.
typedef struct RigidBodyInfo {
    float    Mass;          //  0
    float    Xdim;          //  4
    float    Ydim;          //  8
    float    Zdim;          // 12
    bMatrix4 InertiaTensor; // 16
} RigidBodyInfo;            // 80

// --------------------------------------------------------- RigidBodyState

// 128 bytes, and only the first 116 are used. This is the vector the
// physics integrator advances; everything else on the body is recomputed
// from it by ComputeAuxiliaries.
typedef struct RigidBodyState {
    bVector4 X;                   //   0  position
    bMatrix4 R;                   //  16  orientation
    bVector4 P;                   //  80  linear momentum
    bVector4 L;                   //  96  angular momentum
    float    MotionDampingFactor; // 112
    uint8_t  _pad[12];            // 116
} RigidBodyState;                 // 128

// -------------------------------------------------------------- RigidBody

// 384 bytes on the PS2.
//
// Bytes 0..11 are the `PhysicsComponent` base, which is itself a `bNode`
// (two list links) plus the vtable pointer -- the old g++ ABI again, so
// the vptr is at 8 rather than at 0. **The two links are 32-bit slots,
// not host pointers**: nothing in RigidBody reads or writes them, the
// owning `bTList<PhysicsComponent>` does, so they are declared as plain
// words and the layout stays exact.
//
// `RBI` is the one real pointer, and it is dereferenced, so it cannot get
// the same treatment. See RIGIDBODY_SLACK.
typedef struct RigidBody {
    uint32_t  pNext;                //   0  bNode, owned by the list
    uint32_t  pPrev;                //   4
    uint32_t  _vtable;              //   8
    const RigidBodyInfo *RBI;       //  12
    RigidBodyState State;           //  16
    bVector4  Velocity;             // 144  auxiliary
    bVector4  AngularVelocity;      // 160  auxiliary
    bMatrix4  Matrix;               // 176  auxiliary: R with X in row 3
    bVector4  ForceAccumulator;     // 240
    bVector4  MomentAccumulator;    // 256
    int32_t   MotionDamping;        // 272  a flag, stored as a word
    int32_t   IsHP;                 // 276  a bool, stored as a word
    float     Mass;                 // 280
    float     Mass_inv;             // 284
    bMatrix4  I_body_inv;           // 288
    bVector4  CenterOfGravity;      // 352
    float     MaxMomentZ;           // 368
    float     SpeedLimiter;         // 372
    float     CatchUpMultiplier;    // 376
    uint8_t   _pad[4];              // 380
} RigidBody;                        // 384

#define RIGIDBODY_SLACK ((size_t)(sizeof(void *) - 4))

// A caveat on checking this with a single slack term, the same one
// Steering carries. On a 64-bit host `RBI` gains four bytes of *alignment
// padding* in front of it as well as four bytes of *width*, so everything
// from State onwards moves by eight = 2 * RIGIDBODY_SLACK. The two fours
// are not the same four: one is the pointer getting wider, the other is
// the struct getting realigned around it. They coincide numerically on
// every host this will be built for, and the transcript is what carries
// the rest of the claim.
#ifndef RIGIDBODY_NO_ASSERT
typedef char rigidbody_layout_check[
    (sizeof(RigidBodyInfo) == 80
     && offsetof(RigidBodyInfo, InertiaTensor) == 16
     && sizeof(RigidBodyState) == 128
     && offsetof(RigidBodyState, R) == 16
     && offsetof(RigidBodyState, P) == 80
     && offsetof(RigidBodyState, L) == 96
     && offsetof(RigidBodyState, MotionDampingFactor) == 112
     && offsetof(RigidBody, pNext) == 0
     && offsetof(RigidBody, _vtable) == 8
     && offsetof(RigidBody, State) == 16 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, Velocity) == 144 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, Matrix) == 176 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, ForceAccumulator) == 240 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, MotionDamping) == 272 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, Mass_inv) == 284 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, I_body_inv) == 288 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, CenterOfGravity) == 352 + 2 * RIGIDBODY_SLACK
     && offsetof(RigidBody, CatchUpMultiplier) == 376 + 2 * RIGIDBODY_SLACK
     && sizeof(RigidBody) == 384 + 2 * RIGIDBODY_SLACK) ? 1 : -1];
#endif

// ------------------------------------------------------------- the tables

// _GLOBAL_$I$__9RigidBodyP13RigidBodyInfo (0x00193d20) builds two Tables
// at static-initialisation time. Nothing else in the image does, so the
// port exposes the same step explicitly and GetDerivative needs it to have
// run. The values are read straight out of the ELF at 0x00308cf0 and
// 0x00308d20.
//
//   AngularMomentumDamping  6 entries over [0, 10]
//   MotionDamping           8 entries over [0,  1]
void rigidbody_static_init(void);

extern const float RigidBodyAngularMomentumDampingValues[6];
extern const float RigidBodyMotionDampingValues[8];
extern Table RigidBodyAngularMomentumDampingTable;
extern Table RigidBodyMotionDampingTable;

// ------------------------------------------------------------- the object

// 0x00192ca0. Stores RBI and the vtable, clears the xyz lanes -- not the
// w lanes -- of X, P, L, Velocity, AngularVelocity and the two
// accumulators, zeroes MotionDampingFactor, MaxMomentZ, SpeedLimiter and
// IsHP, sets CatchUpMultiplier to 1 and MotionDamping to 1, calls
// bIdentity on R, and finishes with CalculateInertiaTensor.
//
// **`Matrix` and `CenterOfGravity` are never touched**, and neither are
// the two bNode links. A fresh body inherits whatever the allocation held
// in all three.
RigidBody *rigidbody_init(RigidBody *rb, const RigidBodyInfo *rbi);

// 0x00193fc0. Calls ~PhysicsComponent, which writes *that* class's
// vtable, and applies the delete flag. It does **not** write RigidBody's
// own vtable first, which is unusual -- most destructors in this image do.
void rigidbody_fini(RigidBody *rb);

// 0x00192c08. The base constructor: one store, of the base's vtable.
void physicscomponent_init(void *pc);

// 0x00192438.
void physicscomponent_fini(void *pc);

// 0x00192f48. Mass and Mass_inv from RBI, and I_body_inv from inverting
// RBI's tensor. Note `Mass_inv` is `1.0f / RBI->Mass` and nothing guards
// a zero mass.
void rigidbody_calculate_inertia_tensor(RigidBody *rb);

// 0x00192f30. **Null-checked**, unlike every other pointer argument in
// this object, and it copies the whole quadword including w.
void rigidbody_calibrate(RigidBody *rb, const bVector4 *cog);

// 0x00192f78. X = *x, R = *r, P = (*p) * Mass, and L = I_world * (*omega)
// where I_world is R * diag(1/I_body_inv[0][0], 1/[1][1], 1/[2][2]) * R^T.
//
// That middle term is the giveaway: it reconstructs the body inertia by
// inverting only the *diagonal* of the inverse tensor, so a tensor with
// off-diagonal terms does not round-trip. The image builds it with
// bIdentity and three reciprocals rather than calling bInvertMatrix.
void rigidbody_set_state(RigidBody *rb, const bVector4 *x, const bMatrix4 *r,
                         const bVector4 *p, const bVector4 *omega);

// 0x00193080. Adds a force at a point, both clamped:
//   ForceAccumulator  += clamp(*f,        1200)
//   MomentAccumulator += clamp(*at x *f,   100)
// The cross product is `vopmula`/`vopmsub`, which writes xyz only, so the
// moment's w lane comes from `at`, not from the product.
void rigidbody_apply_force(RigidBody *rb, const bVector4 *f,
                           const bVector4 *at);

// 0x00193170. The same, with both vectors rotated out of body frame by R
// first.
void rigidbody_apply_force_in_frame(RigidBody *rb, const bVector4 *f,
                                    const bVector4 *at);

// 0x001931e8. `MomentAccumulator += *m`, all four lanes, no clamp.
void rigidbody_apply_moment(RigidBody *rb, const bVector4 *m);

// 0x00193200. Impulses go straight into the momenta rather than the
// accumulators:
//   P += clamp(*j,      1000)
//   L += clamp(*at x *j,  10)
void rigidbody_apply_impulse(RigidBody *rb, const bVector4 *j,
                             const bVector4 *at);

// 0x001932e8. The same, except the angular part is scaled *after* the
// clamp: `L += clamp(at x j, 10) * scale`.
void rigidbody_apply_impulse_scaled(RigidBody *rb, const bVector4 *j,
                                    const bVector4 *at, float scale);

// 0x001933e8. Answers what the velocities *would* be after an impulse,
// without applying it. Only the xyz lanes of `outV` are written -- the
// image stores three scalars, not a quadword.
void rigidbody_test_impulse(RigidBody *rb, bVector4 *outV, bVector4 *outOmega,
                            const bVector4 *j, const bVector4 *at);

// 0x001934e0. `0.5 * dot(P, V) + 0.5 * dot(L, omega)`, xyz only, and the
// two halves are multiplied separately before being added.
float rigidbody_get_energy(const RigidBody *rb);

// 0x00193538. The same quantity for the hypothetical post-impulse state.
float rigidbody_get_test_impulse_energy(RigidBody *rb, const bVector4 *j,
                                        const bVector4 *at);

// 0x00193660. `out.row_i = cross(w, m.row_i)` for the first three rows,
// with the fourth row set to (0, 0, 0, 1) and every row's w lane zeroed.
// This is `star(w) * m`, the derivative of a rotation matrix under an
// angular velocity.
void VectorStarMatrix(bMatrix4 *out, const bVector4 *w, const bMatrix4 *m);

// 0x00193b38. Recomputes Velocity, AngularVelocity and Matrix from the
// state, floors MotionDampingFactor at zero, **resets both accumulators**
// and then applies gravity as a force at the origin.
//
// One deliberate divergence, and it is in a lane nothing reads: the image
// zeroes the accumulators from a stack quadword whose w word it never
// wrote, so ForceAccumulator.w and MomentAccumulator.w pick up stack
// junk. The port zeroes them. See the format doc.
void rigidbody_compute_auxiliaries(RigidBody *rb);

// 0x00193c68. Empty.
void rigidbody_resolve_forces(RigidBody *rb);

// 0x00193c70. **Empty in the image too**, despite the name -- the printf
// it was written around is gone and only the argument computation is
// left, writing to stack temporaries and a return register that the void
// signature discards. Ported as a no-op, with the arithmetic recorded in
// the format doc rather than in code that cannot be observed.
void rigidbody_print_current_state(RigidBody *rb);

// 0x001937c0. The integrator's derivative, written into 29 floats:
//
//   [0..3]    Xdot = Velocity
//   [4..19]   Rdot = star(AngularVelocity) * R
//   [20..23]  Pdot = ForceAccumulator
//   [24..27]  Ldot = MomentAccumulator
//   [28]      d(MotionDampingFactor)
//
// with three things layered on top before the copy: an optional speed
// limiter that pushes back along the body's forward axis, angular
// momentum damping off a table, and -- when MotionDamping is set --
// linear and angular damping proportional to MotionDampingFactor. Then
// Ldot.z is clamped to +/- MaxMomentZ.
//
// Returns `out`.
float *rigidbody_get_derivative(RigidBody *rb, float *out);

// 0x00193f68 and 0x00193f20. 116 bytes each way, X R P L and the damping
// factor, leaving the state's tail padding alone.
void rigidbody_get_state_array(const RigidBody *rb, float *out);
void rigidbody_set_state_array(RigidBody *rb, const float *in);

// 0x00193fb0 and 0x00193fb8.
RigidBodyState *rigidbody_get_state(RigidBody *rb);
int32_t rigidbody_get_size(const RigidBody *rb);

// The one-line accessors, 0x00193df0 .. 0x00193eec. Every getter that
// answers a vector or a matrix answers a **pointer into the object**, not
// a copy, so callers can and do write through them.
void rigidbody_set_l(RigidBody *rb, const bVector4 *l);
void rigidbody_set_r(RigidBody *rb, const bMatrix4 *r);
void rigidbody_set_p(RigidBody *rb, const bVector4 *p);
void rigidbody_set_x(RigidBody *rb, const bVector4 *x);
void rigidbody_set_motion_damping(RigidBody *rb, int32_t on);
void rigidbody_set_catch_up_multiplier(RigidBody *rb, float f);
void rigidbody_set_is_hp(RigidBody *rb, int32_t b);
void rigidbody_set_speed_limiter(RigidBody *rb, float f);
void rigidbody_set_max_moment_z(RigidBody *rb, float f);

bMatrix4 *rigidbody_get_inverse_inertia_tensor(RigidBody *rb);
float     rigidbody_get_inverse_mass(const RigidBody *rb);
bVector4 *rigidbody_get_accumulated_forces(RigidBody *rb);
bVector4 *rigidbody_get_center_of_gravity(RigidBody *rb);
float     rigidbody_get_mass(const RigidBody *rb);
bMatrix4 *rigidbody_get_matrix(RigidBody *rb);
bVector4 *rigidbody_get_angular_momentum(RigidBody *rb);
bVector4 *rigidbody_get_angular_velocity(RigidBody *rb);
bMatrix4 *rigidbody_get_rotation(RigidBody *rb);
bVector4 *rigidbody_get_momentum(RigidBody *rb);
bVector4 *rigidbody_get_velocity(RigidBody *rb);
bVector4 *rigidbody_get_position(RigidBody *rb);

// 0x00193e90. `1.0f / I_body_inv[2][2]` -- the *inverse* tensor's z
// diagonal reciprocated, which is the body-frame moment of inertia about
// z. It does not consult R, so it is the body value, not the world one.
float rigidbody_get_moment_of_inertia_about_z(const RigidBody *rb);

// RigidBody::operator new (0x00193f00) and operator delete (0x00193ef0)
// are bOMalloc/bFree on the slot pool at gp-23408, and new ignores its
// size argument for the same reason CarTypeInfo's and
// TwoWheelAckermanSteering's do. Not ported.
//
// RigidBody::DoSnapshot (0x00192d60) is not ported: ReplaySnapshot again.

#endif
