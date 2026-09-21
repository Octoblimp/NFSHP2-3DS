// drivetarget -- DriveTarget's *layout only* (0x002086f8 .. 0x0020a7xx).
//
// DriveTarget is the short list of points the AI is currently steering
// through, together with the speed it wants at each one. It is 528 bytes
// and it is embedded at offset 0 of every CarDriver, which is why it has
// to be spelled out before CarDriver can be.
//
// **None of its 28 methods are ported here.** They are ~8.6 KB of code
// reaching into Car, CarState, TrackRoute and the collision predictor,
// and they are their own slice of task 25. What this header carries is
// the record, so that CarDriver -- which copies it wholesale and does
// nothing else with it -- can be ported and checked now.
//
// Everything below is either in the .mdebug entry or confirmed by an
// instruction. Where the two agree the address is given, because the
// element types are not in the dump and had to come from the code:
//
//   Points[i]            sll v0,i,4 ; addiu v0,v0,16    (0x00208a0c)
//   Route[i]             lb  a2,416(base + i)           (0x00208af0)
//   RoutePointNumber[i]  lh  a3,436(base + i*2)         (0x00208af8)
//   DrivingLine[i]       lb  t0,476(base + i)           (0x00208ae8)
//   NumPoints            lb  v1,0(s0)                   (0x002089a4)
//   Length               lwc1 $f0,512(s0)               (0x002091bc)
//   WhichPointIPicked... lw  v0,504(s1)                 (0x00209218)
//
// The element count is 20 everywhere, and the constructor agrees: it
// opens with a loop counted from 19 down to -1 whose body the compiler
// optimised away to nops, leaving the trip count as the only trace of
// twenty default-constructed members.
//
// See docs/formats/car-driver.md.

#ifndef DRIVETARGET_H
#define DRIVETARGET_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"

#define DRIVETARGET_MAX_POINTS 20

typedef struct DriveTarget {
    int8_t   NumPoints;                        //   0
    uint8_t  _pad0[15];                        //   1  (Points is 16-aligned)
    bVector3 Points[DRIVETARGET_MAX_POINTS];   //  16
    float    CalculatedSpeed[DRIVETARGET_MAX_POINTS];  // 336
    int8_t   Route[DRIVETARGET_MAX_POINTS];            // 416
    int16_t  RoutePointNumber[DRIVETARGET_MAX_POINTS]; // 436
    int8_t   DrivingLine[DRIVETARGET_MAX_POINTS];      // 476
    int32_t  TType;                            // 496  an enum
    int8_t   WhichPointIPicked;                // 500
    uint8_t  _pad1[3];                         // 501
    int32_t  WhichPointIPickedCalculationTime; // 504  loaded with lw
    int32_t  WhichPointIPickedTime;            // 508  AccelerationBlendingTime
    float    Length;                           // 512
    uint8_t  _pad2[12];                        // 516
} DriveTarget;

// 528 = 33 * 16. The tail padding is not a guess: Points is an array of
// 16-byte vectors, so the record is 16-aligned, and 516 rounds up to 528.
// Nothing writes a vtable pointer into a DriveTarget -- the constructor
// only memsets and calls Clear -- so unlike CarDriver there is no vptr
// hiding in that tail.
#ifndef DRIVETARGET_NO_ASSERT
typedef char drivetarget_layout_check[
    (offsetof(DriveTarget, Points) == 16
     && offsetof(DriveTarget, CalculatedSpeed) == 336
     && offsetof(DriveTarget, Route) == 416
     && offsetof(DriveTarget, RoutePointNumber) == 436
     && offsetof(DriveTarget, DrivingLine) == 476
     && offsetof(DriveTarget, TType) == 496
     && offsetof(DriveTarget, WhichPointIPicked) == 500
     && offsetof(DriveTarget, WhichPointIPickedCalculationTime) == 504
     && offsetof(DriveTarget, WhichPointIPickedTime) == 508
     && offsetof(DriveTarget, Length) == 512
     && sizeof(DriveTarget) == 528) ? 1 : -1];
#endif

// 0x00208788. `bMemCpy(dst, src, 528)` and nothing else -- no per-field
// work, no deep copy, and the return value is the destination. CarDriver
// tail-calls it, so it is here rather than waiting for the rest of the
// object.
DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src);

#endif
