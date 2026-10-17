// steering -- Steering (0x0019c580, 0x0019c548, 0x0019ba98) and
// TwoWheelAckermanSteering (0x0019bb18, 0x0019c468 .. 0x0019c544).
//
// Steering is a two-field base class: the car type it was built from, and
// a pointer to an array of per-wheel rotation matrices it does not own.
// It computes nothing. TwoWheelAckermanSteering is the only subclass in
// the image, and it is what the wheels actually ask for their steer
// angle.
//
// Ackerman geometry is the reason this exists. In a turn the inside wheel
// has to steer further than the outside one, because it is tracing a
// tighter circle about the same centre. The exact relation is
//
//     cot(outer) = cot(inner) + Track / Wheelbase
//
// and the image solves it with tan(x) ~ x throughout, which turns it into
// one divide. See below.
//
// See docs/formats/car-steering.md.

#ifndef STEERING_H
#define STEERING_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "cartypeinfo.h"

// ------------------------------------------------------------- constants

// The four pool entries SetSteering uses, read out of the ELF at
// 0x00321804 .. 0x00321810.
//
// Two of them are **the object's own trigonometry constants, not the
// library's** -- the same finding CarState turned up, and it is not
// cosmetic here either, because the fold decides which side of the
// half-turn a steering angle lands on.
//
//   0x38c90fdb  2pi/65536        exact to the bit
//   0x40490fd0  3.14159012       float(pi) is 0x40490fdb -- 11 ulps low
//   0x40c90fd0  6.28318024       float(2pi) is 0x40c90fdb -- 11 ulps low
//   0x3fc90fdc  1.57079649       float(pi/2) is 0x3fc90fdb -- one ulp HIGH
//
// The pi/2 is the odd one: the other two are the same low variant that
// CarState carries, and this one is a single ulp the other way.
#define STEERING_BAM_TO_RADIANS 9.58738019e-05f  // 0x38c90fdb
#define STEERING_IMAGE_PI       3.14159012f      // 0x40490fd0
#define STEERING_IMAGE_TWO_PI   6.28318024f      // 0x40c90fd0
#define STEERING_IMAGE_HALF_PI  1.57079649f      // 0x3fc90fdc

// _vt$8Steering at 0x00299018 and _vt$24TwoWheelAckermanSteering at
// 0x00298ff8, both built as `lui 0x002a ; addiu -286xx`. Nothing in
// either class reads them; they are kept so the transcript can watch
// them being written and so a later dispatching slice has the values.
#define STEERING_VTABLE        0x00299018u
#define ACKERMAN_VTABLE        0x00298ff8u

// --------------------------------------------------------------- Steering

// 12 bytes on the PS2. The vtable pointer is at 8, after the data, the
// same old-g++ shape CarDriver has.
typedef struct Steering {
    const CarTypeInfo *CTI;            // 0
    bMatrix4          *SteeringMatrix; // 4   not owned
    uint32_t           _vtable;        // 8
} Steering;

// Both pointers sit at the front, so the widening is uniform and a single
// slack term covers it -- the CARSTATE_SLACK shape rather than Engine's
// mirror struct.
#define STEERING_SLACK ((size_t)(sizeof(void *) - 4))

// 0x0019c580. `sw a1,0(v0)` and `sw v1,8(v0)`: the car type and the
// vtable, and that is all. **SteeringMatrix is left uninitialised** --
// the base class has nothing to point it at, and every subclass is
// expected to aim it at storage of its own.
void steering_init(Steering *s, const CarTypeInfo *cti);

// 0x0019ba98. Rewrites the vtable; the delete is the caller's.
void steering_fini(Steering *s);

// 0x0019c548. `lw v0,4(a0) ; sll a1,a1,6 ; addu v0,v0,a1` -- the index is
// scaled by 64, which is sizeof(bMatrix4), with no bounds check.
bMatrix4 *steering_get_matrix(const Steering *s, int32_t wheel);

// --------------------------------------- TwoWheelAckermanSteering

#define ACKERMAN_MATRICES 2

// 144 bytes. The base is 12 and the array starts at 16, so the PS2 pads
// 12..15 to get bMatrix4 onto a quadword boundary.
//
// That pad has to be written down rather than left to the compiler.
// bMatrix4 is four floats and 4-aligned on both of our targets -- nothing
// gives it the PS2's quadword alignment -- so an implicit pad is exactly
// four bytes of nothing on ARM, where the array lands at 12 instead of
// 16. It is only on a 64-bit host that it appears to work, and then by
// accident: the two widened pointers have already pushed the base to 24
// and supplied the four bytes for their own reason. Hence the pad below
// is conditional -- four bytes on a 32-bit target, none on a 64-bit one,
// where the slack has paid for it already.
typedef struct TwoWheelAckermanSteering {
    Steering base;                              //   0
#if __SIZEOF_POINTER__ == 4
    uint8_t  _pad0[4];                          //  12
#endif
    bMatrix4 AckermanMatrix[ACKERMAN_MATRICES]; //  16
} TwoWheelAckermanSteering;

// A caveat on checking this one with a single slack term. The assert
// below holds on both targets now, but the two paddings it folds into
// `2 * STEERING_SLACK` exist for different reasons: the PS2's is
// quadword alignment for bMatrix4, the host's is pointer alignment for
// the struct. They come to the same number only by coincidence. The
// assert is still worth having; it just proves less than it looks like
// it does, and the transcript is what carries the rest.
#ifndef STEERING_NO_ASSERT
typedef char steering_layout_check[
    (offsetof(Steering, CTI) == 0
     && offsetof(Steering, SteeringMatrix) == 1 * STEERING_SLACK + 4
     && offsetof(Steering, _vtable) == 2 * STEERING_SLACK + 8
     && sizeof(Steering) == 3 * STEERING_SLACK + 12
     && offsetof(TwoWheelAckermanSteering, AckermanMatrix)
        == 2 * STEERING_SLACK + 16
     && sizeof(TwoWheelAckermanSteering) == 2 * STEERING_SLACK + 144
     && sizeof(bMatrix4) == 64) ? 1 : -1];
#endif

// 0x0019c500. Inlines the base constructor -- it writes CTI and the
// vtable itself rather than calling it -- runs a two-iteration loop whose
// body the compiler deleted (the two bMatrix4 default constructors), and
// then **points the base's SteeringMatrix at its own AckermanMatrix[0]**.
// That one store is the whole relationship between the two classes:
// Steering::GetMatrix indexes through it and lands in the subclass.
//
// The matrices are NOT initialised here. They hold whatever the
// allocation did until the first SetSteering.
TwoWheelAckermanSteering *ackerman_init(TwoWheelAckermanSteering *a,
                                        const CarTypeInfo *cti);

// 0x0019c4a0. Rewrites its own vtable, calls ~Steering with flags 0 --
// which rewrites the *base's* vtable over the top -- and only then
// applies its own flags. So a destroyed object is left carrying the base
// class's vtable, not its own.
void ackerman_fini(TwoWheelAckermanSteering *a);

// 0x0019c498. Empty.
void ackerman_compute_auxiliaries(TwoWheelAckermanSteering *a);

// 0x0019bb18. The one function in this object that does anything.
//
//   rad = (float)(bam & 0xffff) * 2pi/65536      -- so rad is in [0, 2pi)
//   if (IMAGE_PI < rad) rad -= IMAGE_TWO_PI      -- fold to (-pi, pi]
//
//   inner = |rad|
//   outer = (Wheelbase * inner) / (Wheelbase + Track * inner)
//
// where Wheelbase is CTI->Wheels[0].PositionX - CTI->Wheels[3].PositionX
// and Track is CTI->Wheels[0].PositionY - CTI->Wheels[1].PositionY. That
// is exact Ackerman with tan(x) replaced by x, which is why there is a
// divide and no atan.
//
// Then the two angles are handed out by *sign*: steering left, matrix 0
// gets the full angle and matrix 1 the reduced one; steering right, the
// two swap and both are negated. The inside wheel is whichever one gets
// the full angle, and which one that is depends on the direction of the
// turn.
//
// Each matrix is bIdentity() followed by four stores -- m[0] and m[5] to
// cos, m[1] to sin, m[4] to -sin -- a rotation about Z. The cosine is
// `bSinF(angle + IMAGE_HALF_PI)`, not a bCos call, so it carries that
// constant's one-ulp error into every steer angle.
void ackerman_set_steering(TwoWheelAckermanSteering *a, uint16_t bam);

// TwoWheelAckermanSteering::operator new (0x0019c478) is
// `bOMalloc(SlotPool at gp-23404)` -- it **ignores the requested size**,
// because a slot pool only ever hands out one size. operator delete
// (0x0019c468) is the matching `bFree`. Both are physcomp.h's
// ackerman_new and ackerman_delete, on TwoWheelAckermanSteeringSlotPool,
// and so are the two destructors, the Ackerman's table and Steering's.
// PhysicsCar's constructor inlines the new rather than calling it.

// Retail's 0x001a5d10 (the demo's 0x0019bac0), the replay's, the
// Ackerman's table entry: AckermanMatrix[0] through the compressed matrix
// move in a section named "TwoWheelAckermanSteering". The image passes 128,
// both matrices' size, which the move does not read, so the second matrix
// is not in the replay; ComputeAuxiliaries makes both from the steering
// angle anyway.
//
// Steering::BaseDoSnapshot (retail's 0x001a67a8), a non-virtual call of
// the table's DoSnapshot, has no caller in the image and is not ported.
struct ReplaySnapshot;
void ackerman_do_snapshot(TwoWheelAckermanSteering *a,
                          struct ReplaySnapshot *s);

#endif
