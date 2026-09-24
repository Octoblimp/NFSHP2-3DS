// physicssystem -- PhysicsSystem.obj (0x00192438 .. 0x00192c28), the
// integrator every physical object in the game runs on.
//
// A PhysicsSystem is a list of PhysicsComponents and a running total of
// their state sizes. It knows nothing about cars: a component is anything
// that can say how many floats of state it has, copy them out and in, and
// write their derivative, and the system concatenates those into one vector
// and steps it. PhysicsCar's list is a RigidBody, four Suspensions, four
// Wheels, an Engine and a DriveTrain; MellowMover's is two of those;
// Smokeable, Rocket, SmokeBomb and the dropped weapons each build their own.
//
// Two integrators. **IntegrateEuler is the one the game runs** --
// PhysicsCar::Move, MellowMover::Move and Smokeable::Move all call it --
// and IntegrateRungeKutta, a textbook RK4, has no caller anywhere in the
// image. Both are ported.
//
// The list is a bTList<PhysicsComponent>: its head node is the system's
// first eight bytes, so the list's sentinel *is* the system, and each
// component's first eight bytes are its bNode. Those links are 32-bit
// slots, and they are walked through p32.h -- see there.
//
// See docs/formats/physics-system.md.

#ifndef PHYSICSSYSTEM_H
#define PHYSICSSYSTEM_H

#include <stddef.h>
#include <stdint.h>

#include "rigidbody.h"   // PHYSICSCOMPONENT_VTABLE, physicscomponent_init

// ------------------------------------------------------ PhysicsComponent

// 12 bytes: the bNode and the vptr. Every component record in the port
// begins with exactly these three words -- RigidBody, Wheel, Suspension,
// Engine and DriveTrain each declare them as their own first fields -- so a
// component is walked through this view.
typedef struct PhysicsComponent {
    uint32_t pNext;     // 0  bNode::Next, a p32 handle
    uint32_t pPrev;     // 4  bNode::Prev
    uint32_t _vtable;   // 8
} PhysicsComponent;     // 12

// _vt$16PhysicsComponent, 0x00298728, and the slot every component
// table shares. GetSize, both GetStates, SetState and GetDerivative are
// `__pure_virtual` (0x00283c80) in the base's own table.
#define PHYSICSCOMPONENT_VT_DTOR                 8
#define PHYSICSCOMPONENT_VT_GET_SIZE            16
#define PHYSICSCOMPONENT_VT_GET_STATE           24   // float *GetState()
#define PHYSICSCOMPONENT_VT_GET_STATE_ARRAY     32   // GetState(float *)
#define PHYSICSCOMPONENT_VT_SET_STATE_ARRAY     40   // SetState(float *)
#define PHYSICSCOMPONENT_VT_RESOLVE_FORCES      48
#define PHYSICSCOMPONENT_VT_GET_DERIVATIVE      56   // float *(float *)
#define PHYSICSCOMPONENT_VT_COMPUTE_AUXILIARIES 64

// The slots' types, which a table's entries are cast to at the call.
typedef void     (*PhysicsDtorFn)(void *self, int32_t flags);
typedef int32_t  (*PhysicsGetSizeFn)(void *self);
typedef float   *(*PhysicsGetStateFn)(void *self);
typedef void     (*PhysicsStateArrayFn)(void *self, float *a);
typedef float   *(*PhysicsGetDerivativeFn)(void *self, float *out);
typedef void     (*PhysicsVoidFn)(void *self);

// 0x00192bf8 and 0x00192c00: the base's two non-pure virtuals, both
// `jr ra`. RigidBody overrides ResolveForces with another empty one.
void physicscomponent_compute_auxiliaries(void *pc);
void physicscomponent_resolve_forces(void *pc);

// --------------------------------------------------------- PhysicsSystem

// 16 bytes. The mdebug record names only ComponentList; Size is a field
// the dump prints among the methods (`Size:/01,64,32`), and the vptr is at
// 96 bits -- after the data, as g++ 2.9x places it.
typedef struct PhysicsSystem {
    uint32_t pNext;     //  0  ComponentList's head node: the first component
    uint32_t pPrev;     //  4  the last
    int32_t  Size;      //  8  the sum of every component's GetSize
    uint32_t _vtable;   // 12
} PhysicsSystem;        // 16

#ifndef PHYSICSSYSTEM_NO_ASSERT
typedef char physicssystem_layout_check[
    (sizeof(PhysicsComponent) == 12
     && offsetof(PhysicsComponent, _vtable) == 8
     && sizeof(PhysicsSystem) == 16
     && offsetof(PhysicsSystem, Size) == 8
     && offsetof(PhysicsSystem, _vtable) == 12) ? 1 : -1];
#endif

// _vt$13PhysicsSystem, 0x00298708: the destructor, ComputeAuxiliaries and
// ResolveForces. Derived classes -- PhysicsVehicle, then PhysicsCar,
// Smokeable, Rocket and the weapons -- replace the vptr with their own, and
// PhysicsCar's overrides the two methods.
#define PHYSICSSYSTEM_VTABLE 0x00298708u
#define PHYSICSSYSTEM_VT_DTOR                 8
#define PHYSICSSYSTEM_VT_COMPUTE_AUXILIARIES 16
#define PHYSICSSYSTEM_VT_RESOLVE_FORCES      24

// IntegrateEuler's derivative and IntegrateRungeKutta's seven arrays are
// 140 floats each, on the stack. **Nothing checks a system's Size against
// it**: GetDerivative and the rest write as far as the components say.
// PhysicsCar's system is 50 floats -- a RigidBody's 32, two for each of
// four Suspensions and four Wheels, one each for the Engine and the
// DriveTrain.
#define PHYSICSSYSTEM_MAX_STATE 140

// RK4's weights, gp-30008 / -30004 / -30000 (0x3eaaaaab, 0x3f2aaaab,
// 0x3e2aaaab). One third, two thirds and one sixth.
#define PHYSICSSYSTEM_RK_THIRD      0.333333343f
#define PHYSICSSYSTEM_RK_TWO_THIRDS 0.666666687f
#define PHYSICSSYSTEM_RK_SIXTH      0.166666672f

// gp-23232. The milliseconds the last ComputeAuxiliaries took, by
// bGetTickerDifference. Written and never read -- the one reference in the
// image is the store.
extern float AuxTime;

// Installs the port's tables for PhysicsSystem and PhysicsComponent at
// their image addresses. The game calls it once at boot; a harness calls it
// after vt_reset() and may then replace either.
void physicssystem_install_vtables(void);

// 0x00192460. An empty circular list -- both links point at the system --
// the vptr and a zero Size, stored in that order: Next, vptr, Prev, Size.
PhysicsSystem *physicssystem_init(PhysicsSystem *sys);

// 0x00192480. Writes PhysicsSystem's vptr, then takes the first component
// off the list and calls **its** destructor with flags 3 -- destroy and
// free -- until the list is empty, reading the head afresh each time. Then
// ~bTList<PhysicsComponent> with flags 2, which makes the same walk over a
// list that is now empty and returns through ~bList and ~bNode. Frees the
// system itself last if `flags & 1`.
//
// So **a PhysicsSystem owns its components**: destroying one destroys
// every object that was added to it.
void physicssystem_fini(PhysicsSystem *sys, int32_t flags);

// 0x00192528. Appends `c` at the tail, then adds its GetSize to Size. The
// component's vptr is loaded before any link is written.
void physicssystem_add_component(PhysicsSystem *sys, PhysicsComponent *c);

// 0x00192960, 0x001929e8, 0x00192a70. For each component in order: the
// slot (GetDerivative, GetState(float *), SetState(float *)) with the array
// advanced by the floats so far, *then* GetSize, then the next link. Each
// component is asked its size again rather than trusting Size.
void physicssystem_get_derivative(PhysicsSystem *sys, float *out);
void physicssystem_get_state(PhysicsSystem *sys, float *out);
void physicssystem_set_state(PhysicsSystem *sys, const float *in);

// 0x00192580. The derivative of the whole system into a 140-float stack
// array, and then for each component: GetSize, GetState() -- the pointer
// to its live state -- and `state[j] += dt * d[offset + j]` in place.
// Finishes with a virtual ComputeAuxiliaries on the system itself, through
// its own vptr, which is how PhysicsCar gets its override run.
//
// Two details of the walk: the next link is read before the component's
// state is written, and a component whose size is not positive still adds
// that size to the running offset.
void physicssystem_integrate_euler(PhysicsSystem *sys, float dt);

// 0x00192728. Classical RK4 with h = dt / 2 as `dt * 0.5f`:
//
//   y0 = state;              d = f(y0)
//   k1 = h  * d;  SetState(y0 + k1); aux; d = f
//   k2 = h  * d;  SetState(y0 + k2); aux; d = f
//   k3 = dt * d;  SetState(y0 + k3); aux; d = f
//   k4 = dt * d
//   y  = y0 + k1/3;  y += k2 * 2/3;  y += k3/3;  y += k4/6
//   SetState(y); aux
//
// where `aux` is the virtual ComputeAuxiliaries and every array operation
// is over the system's Size, **re-read from the object at each call**.
// Note that k1 and k2 are taken over a half step, so the weights that make
// it RK4 are the ones above and not the usual 1/6, 1/3, 1/3, 1/6.
void physicssystem_integrate_runge_kutta(PhysicsSystem *sys, float dt);

// 0x00192af8. Every component's ComputeAuxiliaries in list order, timed
// with the ticker into AuxTime.
void physicssystem_compute_auxiliaries(PhysicsSystem *sys);

// 0x00192be8. Empty.
void physicssystem_resolve_forces(PhysicsSystem *sys);

// 0x00192bf0. `lw v0,8(a0)`.
int32_t physicssystem_get_size(const PhysicsSystem *sys);

// ------------------------------------------------------ the three helpers

// 0x00192688, 0x001926b8, 0x001926f0. Free functions, used only by
// IntegrateRungeKutta. Each counts `n` down and does nothing when n <= 0.
//
//   ArrayMultiply        out[i] = in[i] * s
//   ArrayAdd             out[i] = a[i] + b[i]
//   ArrayMultiplyAndAdd  out[i] = a[i] + b[i] * s
//
// `out` may be `a`: RK4's last three calls accumulate into their first
// operand, and each element is read before it is written.
void ArrayMultiply(float *out, const float *in, float s, int32_t n);
void ArrayAdd(float *out, const float *a, const float *b, int32_t n);
void ArrayMultiplyAndAdd(float *out, const float *a, const float *b, float s,
                         int32_t n);

#endif
