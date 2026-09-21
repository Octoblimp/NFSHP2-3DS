// wheel -- the layout of Wheel and the two entry points Suspension calls.
//
// **This header is a layout, not a port.** Wheel is 73 functions and 7112
// bytes and it is its own slice of task 25, after this one. Suspension
// cannot be written without knowing where Wheel keeps its contact normal
// and its matrices, so the record is written down here and the slice that
// follows fills in the behaviour.
//
// The offsets come from the `.mdebug` type for `Wheel` (type#1035, 400
// bytes). Every field Suspension actually touches is confirmed twice over,
// once by that type and once by the instruction that reads it:
//
//     WI             12   Calibrate's `lw v1,12(v0)`
//     State.a        28   ComputeAuxiliaries' `lwc1 $f12,28(v0)`, and
//                         Wheel::GetRotation (0x0019b930) reads the same word
//     WorldMatrix   112   the four `sqc2 ...,112..160(v1)`
//     CarMatrix     176   the four `sqc2 ...,176..224(v0)`
//     Velocity      240   `sqc2 vf2,240(v1)`
//     WorldGroundForce 288  ResolveMoreForces passes `a1 = pWheel + 288`
//     ContactPoint  304   ResolveMoreForces' `lqc2 vf2,304(a1)`
//     ContactNormal 320   ApplyGroundPenaltyImpulse's `lqc2 vf1,320(v0)`
//     Damage        364   ComputeAuxiliaries' `lwc1 $f20,364(v0)`
//
// The rest are on the `.mdebug`'s word alone, which is the same standard
// the other records in this port are held to, and none of them is read
// here.
#ifndef WHEEL_H
#define WHEEL_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "cartypeinfo.h"

// 8 bytes. `a` is the rotation angle in radians and `w` the angular
// velocity; Wheel::GetRotation (0x0019b930) returns the first and
// Wheel::GetAngularVelocity (0x0019b928) the second.
typedef struct WheelState {
    float a; // 0
    float w; // 4
} WheelState;

// 400 bytes, on a PhysicsComponent base like RigidBody and Suspension --
// two list links and the vtable pointer at 8, old-g++ ABI.
typedef struct Wheel {
    uint32_t  pNext;                     //   0  bNode, owned by the list
    uint32_t  pPrev;                     //   4
    uint32_t  _vtable;                   //   8
    const WheelInfo *WI;                 //  12
    const TireInfo  *TI;                 //  16
    void     *CI;                        //  20  ControlInfo, not decoded
    void     *CS;                        //  24  CarState
    WheelState State;                    //  28
    float     MomentOfInertia;           //  36
    uint8_t   _pad0[8];                  //  40  Matrix is 16-aligned
    bMatrix4  Matrix;                    //  48
    bMatrix4  WorldMatrix;               // 112
    bMatrix4  CarMatrix;                 // 176
    bVector4  Velocity;                  // 240
    float     Slip[2];                   // 256
    float     AppliedTorque;             // 264
    int32_t   BrakeLocked;               // 268
    int32_t   LastSign;                  // 272
    float     GroundForce[2];            // 276
    uint8_t   _pad2[4];                  // 284  WorldGroundForce is
                                         //      16-aligned
    bVector4  WorldGroundForce;          // 288
    bVector4  ContactPoint;              // 304
    bVector4  ContactNormal;             // 320
    void     *Terrain;                   // 336  TerrainType
    uint8_t   Slipping;                  // 340
    uint8_t   TouchingGround;            // 341
    uint16_t  NumTimesSkidding;          // 342
    float     ZForce;                    // 344
    float     RoadNoise;                 // 348
    float     CurrentSlip;               // 352
    float     OldSlip;                   // 356
    float     TractionUsage;             // 360
    float     Damage;                    // 364
    float     Brake;                     // 368
    float     EBrake;                    // 372
    float     TractionBoost;             // 376
    float     CatchupFrictionMultiplier; // 380
    void     *TheSkidMaker;              // 384
    uint8_t   _pad1[12];                 // 388
} Wheel;                                 // 400

// Six pointers, spread through the record rather than gathered at the
// front, so the widening on a 64-bit host is not one term -- see
// SUSPENSION_SLACK in suspension.h for the same problem written out in
// full. Counted in WHEEL_SLACK the multiplier is 1 at WI, then 5 for the
// whole span from State to ContactNormal, then 7 at Damage, where the
// Terrain pointer has taken an alignment pad of its own on the way past.
//
// The first draft of this header guarded the assert with
// `#if __SIZEOF_POINTER__ == 4`, on the grounds that nothing in the port
// depends on Wheel's host layout yet. That was a mistake twice over: the
// guard meant the claim was never compiled by either toolchain the project
// actually uses -- the host build skipped it and the ARM build had not been
// run -- and when the ARM build finally ran it failed. `_pad2` is what it
// failed on.
#define WHEEL_SLACK ((size_t)(sizeof(void *) - 4))

// 400 bytes on the handheld; 436 of fields on a 64-bit host, rounded up to
// the pointer's alignment.
#define WHEEL_SIZEOF                                                        \
    ((size_t)((400 + 9 * WHEEL_SLACK + sizeof(void *) - 1)                 \
              / sizeof(void *) * sizeof(void *)))

#ifndef WHEEL_NO_ASSERT
typedef char wheel_layout_check[
    (offsetof(Wheel, WI) == 12 + 1 * WHEEL_SLACK
     && offsetof(Wheel, State) == 28 + 5 * WHEEL_SLACK
     && offsetof(Wheel, WorldMatrix) == 112 + 5 * WHEEL_SLACK
     && offsetof(Wheel, CarMatrix) == 176 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Velocity) == 240 + 5 * WHEEL_SLACK
     && offsetof(Wheel, WorldGroundForce) == 288 + 5 * WHEEL_SLACK
     && offsetof(Wheel, ContactPoint) == 304 + 5 * WHEEL_SLACK
     && offsetof(Wheel, ContactNormal) == 320 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Damage) == 364 + 7 * WHEEL_SLACK
     && sizeof(Wheel) == WHEEL_SIZEOF
     && sizeof(WheelState) == 8
     && sizeof(WheelInfo) == 32) ? 1 : -1];
#endif

// ------------------------------------------------------------- the seams
//
// The two Wheel methods Suspension calls. Both are genuinely Wheel's own
// work -- FindDrivingSurface (0x0019a2a0) forwards to Wheel::CheckTerrain
// and from there into the terrain system, and ExchangeZForces (0x0019a1c8)
// rewrites four of Wheel's own fields -- so neither is ported here.
//
// They are function pointers for the same reason gTrackPathDistanceFn is:
// NULL on the handheld, and tools/suspension_check.py points them at
// stand-ins so the transcript has something to reason about. When the Wheel
// slice lands, these get pointed at the real methods and the seam goes
// away. A NULL seam reads as zero rather than crashing, which keeps
// Suspension's own arithmetic reachable before Wheel exists.

// 0x0019a2a0. Returns the height of the driving surface under the wheel,
// which ComputeAuxiliaries adds to WI->Radius.
typedef float (*WheelFindDrivingSurfaceFn)(Wheel *w, const bVector4 *pos,
                                           const bMatrix4 *r);

// 0x0019a1c8. Takes the touching-ground flag and the z force, updates the
// wheel, and returns the force the suspension records as GroundForce.
typedef float (*WheelExchangeZForcesFn)(Wheel *w, int32_t touching, float z);

extern WheelFindDrivingSurfaceFn gWheelFindDrivingSurfaceFn;
extern WheelExchangeZForcesFn    gWheelExchangeZForcesFn;

#endif // WHEEL_H
