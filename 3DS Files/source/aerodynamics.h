// aerodynamics -- Aerodynamics.obj (0x001a4b58 .. 0x001a4e28), the drag and
// downforce on a car body.
//
// Not a PhysicsComponent: it has no state and no vtable. PhysicsCar and
// MellowMover each hold one and call ResolveForces once a frame, before the
// suspensions, which take its answer -- the total downforce -- as their
// load. Its constructor is inlined into both of theirs, so the port's
// aerodynamics_init is the six stores they make.
//
// See docs/formats/aerodynamics.md.

#ifndef AERODYNAMICS_H
#define AERODYNAMICS_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "cartypeinfo.h"   // AeroInfo, the 16 bytes at CarTypeInfo+752
#include "rigidbody.h"

// --------------------------------------------------------- Aerodynamics

// 24 bytes on the PS2. AutoBalanceDownforce, AeroInfo's fourth float, is
// read by nothing in this object.
//
// The two pointers widen on a 64-bit host, so the
// floats move by 2 * AERODYNAMICS_SLACK; nothing else in the port lays
// this record over image memory.
typedef struct Aerodynamics {
    const AeroInfo *AI;           //  0
    RigidBody      *pBody;        //  4
    float           Boost;        //  8  divides the speed; 1 from the ctor
    float           Draft;        // 12  multiplies the drag; 1 from the ctor
    float           Throttle;     // 16
    float           GroundEffect; // 20  0, or >= 0.5 for the second arm
} Aerodynamics;                   // 24

#define AERODYNAMICS_SLACK ((size_t)(sizeof(void *) - 4))

#ifndef AERODYNAMICS_NO_ASSERT
typedef char aerodynamics_layout_check[
    (sizeof(AeroInfo) == 16
     && offsetof(AeroInfo, AutoBalanceDownforce) == 12
     && offsetof(Aerodynamics, pBody) == 4 + AERODYNAMICS_SLACK
     && offsetof(Aerodynamics, Boost) == 8 + 2 * AERODYNAMICS_SLACK
     && offsetof(Aerodynamics, GroundEffect) == 20 + 2 * AERODYNAMICS_SLACK
     && sizeof(Aerodynamics) == 24 + 2 * AERODYNAMICS_SLACK) ? 1 : -1];
#endif

// ------------------------------------------------------------- the data

// .sdata at 0x00323ee8 and 0x00323eec, writable tuning.
extern float OffThrottleDragFactor;        // 2.0
extern float OffThrottleDragCenterHeight;  // -0.1

// .bss at 0x003096b0 and 0x003096c0, filled by the object's static
// initialiser: the body-frame points the two downforces push at, one unit
// ahead of the centre and one behind. The w lanes stay the zero the
// section starts with.
extern bVector4 FrontDownforceLocation;    // ( 1, 0, 0, 0)
extern bVector4 RearDownforceLocation;     // (-1, 0, 0, 0)

// The object's literal pool, gp-29476 .. -29468.
#define AERODYNAMICS_MIN_SPEED     9.99999975e-05f  // 0x38d1b717
#define AERODYNAMICS_FRONT_SHARE   0.400000006f     // 0x3ecccccd
#define AERODYNAMICS_REAR_SHARE    0.409999996f     // 0x3ed1eb85

// And one built by a `lui` in the instruction stream.
#define AERODYNAMICS_GROUND_EFFECT 0.5f             // lui 0x3f00

// 0x001a4de8, _GLOBAL_$I$FrontDownforceLocation: x = 1 and x = -1, then
// the y and z lanes zeroed.
void aerodynamics_static_init(void);

// ------------------------------------------------------------ the object

// The inlined constructor: AI, pBody, Boost = 1, Draft = 1, Throttle = 0,
// GroundEffect = 0. PhysicsCar's copy (0x00135504) stores Boost and Draft
// first and AI fourth; nothing can see the order.
void aerodynamics_init(Aerodynamics *a, RigidBody *body, const AeroInfo *ai);

// The four setters are inlined wherever they are used; each is one store.
void aerodynamics_set_boost(Aerodynamics *a, float f);
void aerodynamics_set_draft(Aerodynamics *a, float f);
void aerodynamics_set_throttle(Aerodynamics *a, float f);
void aerodynamics_set_ground_effect(Aerodynamics *a, float f);

// 0x001a4b80. The frame's aerodynamic forces on the body, in three
// ApplyForce calls, and the total downforce into `*out` if `out` is not
// NULL. With s = |Velocity| / Boost:
//
//   drag      k = s*Draft*Drag + s*Draft*Drag*(OffThrottleDragFactor - 1)
//                                            *(1 - Throttle)
//             ApplyForce(-k * Velocity, at (0, 0, z)), where z is
//             OffThrottleDragCenterHeight * (1 - Throttle) when
//             GroundEffect >= 0.5 and 0 otherwise
//
//   downforce u = R.v2.z, the body's up axis against world up, floored at
//             0 -- or 1 when GroundEffect >= 0.5
//             v = Velocity * (1 / s) when s > 1e-4, else (1, 0, 0) --
//             a reciprocal and a vmulx, which rounds differently
//             from three divides
//             c = max(dot(v, R.v0), 0), the forward axis against it
//             w = c^4 * u
//             GroundEffect == 0:  front = s*0.40*w * (Front + Rear)
//                                 rear  = s*0.41*w * (Front + Rear)
//             otherwise:          front = s*Front * w
//                                 rear  = s*Rear  * w
//             ApplyForceInFrame((0, 0, -front), FrontDownforceLocation)
//             ApplyForceInFrame((0, 0, -rear),  RearDownforceLocation)
//
//   *out = front + rear
//
// Two things in there are not what they look like. **v is not a unit
// vector** unless Boost is 1: it divides by s, which is the speed over
// Boost. And the downforce is **linear** in speed, not quadratic.
void aerodynamics_resolve_forces(Aerodynamics *a, float *out);

// 0x001a4dc8. `max(speed, 0) * (Front + Rear)`: the downforce the second
// arm would give at full weight, which Calibrate uses.
float aerodynamics_get_downforce_at_speed(const Aerodynamics *a, float speed);

// Retail's 0x001add48 (the demo's 0x001a4b58), the replay's, with no
// section of its own: taking or restoring clears GroundEffect, Boost and
// Throttle, in that order. Boost 0 would divide ResolveForces' speed by
// zero; PhysicsCar::Move sets it again first.
struct ReplaySnapshot;
void aerodynamics_do_snapshot(Aerodynamics *a, struct ReplaySnapshot *s);

#endif
