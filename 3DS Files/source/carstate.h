// carstate -- CarState.obj (0x001b6170 .. 0x001b6f60).
//
// CarState is the car's *state*, not its physics: 1024 bytes holding where
// the car is, how fast, which way it points, what each of the four wheels is
// doing, and the handful of drivetrain scalars the rest of the game reads.
// Nothing in this object integrates anything. The simulation writes into it
// and the renderer, the sound driver, the HUD and the AI read out of it, so
// it is the seam every other car system meets at -- which is why it is the
// first piece of task 25 rather than the physics.
//
// The object is bounded by CarController before it and Signpost (the head of
// TrackRoute.obj, docs/formats/track-route.md) after it, and holds sixteen
// functions. All sixteen are ported except DoSnapshot -- see the bottom of
// this file.
//
// The struct layout is not guesswork: it comes out of the .mdebug type info
// (docs/formats/mdebug-stabs.md, entry `CarState (size=1024)`) and every
// offset in it was re-derived from the loads and stores in the listing.
// Both agree. See docs/formats/car-state.md.
//
// Three things to know before reading the code:
//
//   * Angles are BAMs (uint16_t, 65536 to the turn) wherever the original
//     stores an angle -- Angle and SteeringAngle -- but GetYaw returns
//     radians, converted with the game's own constants. Those constants are
//     NOT float(M_PI): the image holds 0x40490fd0 for pi where float(pi) is
//     0x40490fdb. Using the library value changes the low bits of every yaw
//     the game has ever computed, so carstate.c hardcodes the image's.
//
//   * WheelTouchingGround is four *bytes*, and nWheelsTouchingGround is a
//     running count maintained by SetWheelTouchingGround rather than
//     recomputed. Write the array directly and the count goes stale.
//
//   * RelCoordMatrix is a cache with an explicit valid bit. GetTransformMatrix
//     builds it on demand and everything that transforms a point goes through
//     that function. Nothing in the object ever clears MatrixValid -- the
//     simulation does, at the top of its timestep -- so a port that forgets
//     to clear it gets last frame's heading forever.
#ifndef CARSTATE_H
#define CARSTATE_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"

// ------------------------------------------------------------ what it needs

// CarTypeInfo is the car's tuning record, 1376 bytes, and CarState reads
// exactly two things out of it: the centre of gravity at 272 and the four
// WheelInfos starting at 288. The whole record belongs to a later task, so
// this is the prefix those two live in rather than the real declaration.
//
// WheelInfo.Position is *twelve* bytes, not a padded bVector3 -- Radius is
// the float straight after it. CalculateWheelMatrices loads all four as one
// quadword and then overwrites the fourth lane with 1.0f, so the radius
// bleeds into the matrix for exactly one instruction. Kept, because a
// three-float load would be a different instruction and this one is free.
//
// The record itself used to be written out here as well as in
// cartypeinfo.h, from back when CarState was ported and CarTypeInfo was
// not. Wheel is the first translation unit to include both headers, and
// two identical definitions of one struct is a redefinition error rather
// than a duplication nobody has to notice -- the same way RigidBodyInfo
// went when Suspension first included rigidbody.h and cartypeinfo.h
// together. cartypeinfo.h owns it now; the size check moved with it.
#include "cartypeinfo.h"

// Only the two fields CarState touches are named; the rest is the gap up to
// them. `CarTypeInfoPrefix` rather than `CarTypeInfo` so that the real
// declaration can land later without a clash.
typedef struct CarTypeInfoPrefix {
    uint8_t  _pad0[272];
    bVector3 CenterOfGravity;                  // 272
    WheelInfo Wheels[4];                       // 288
} CarTypeInfoPrefix;

typedef char carstate_carinfo_off_check[
    (sizeof(CarTypeInfoPrefix) == 416) ? 1 : -1];

// CarState stores a TopologyCoordinate * in its constructor and never looks
// at it again, so it stays opaque here.
typedef struct TopologyCoordinate TopologyCoordinate;

// 11TerrainType. The values matter only in that SetWheelTerrain compares
// them with `<` -- CrossedWheelTerrain keeps the highest terrain a wheel has
// touched this timestep -- and that both reset paths write 1. The full
// enumeration belongs with the collision work in task 27.
typedef int32_t TerrainType;

#define TERRAIN_DEFAULT ((TerrainType)1)

// 4Gear. Likewise: ResetCar writes 1 and nothing here reads it.
typedef int32_t Gear;

// ------------------------------------------------------------- the record

// 1024 bytes. The field order and every offset are the .mdebug layout, which
// is also what the listing's loads and stores use. The two holes are the
// compiler's: eight bytes at 8, to get GeometryPosition onto a 16-byte
// boundary for the quadword loads, and twelve at 1012 to round the record
// up. Neither is ever read, and both are named here so that the harness can
// show they stay unwritten.
typedef struct CarState {
    CarTypeInfoPrefix  *pCarInfo;                  // 0
    TopologyCoordinate *pTopologyCoordinate;       // 4
    uint8_t   _hole8[8];                           // 8

    bVector3  GeometryPosition;                    // 16
    bVector3  Position;                            // 32
    bVector3  Velocity;                            // 48
    bVector3  Acceleration;                        // 64
    bMatrix4  BodyMatrix;                          // 80
    bVector3  AngularVelocity;                     // 144
    bVector3  AngularAcceleration;                 // 160

    bMatrix4  WheelMatrix[4];                      // 176
    bMatrix4  BrakeMatrix[4];                      // 432

    float     WheelAngularVelocity[4];             // 688
    float     WheelAngle[4];                       // 704
    float     WheelZForce[4];                      // 720
    float     WheelRoadNoise[4];                   // 736
    float     WheelBottomOutMagnitude[4];          // 752
    float     WheelSuspensionHeight[4];            // 768
    int8_t    WheelTouchingGround[4];              // 784
    TerrainType WheelTerrain[4];                   // 788
    TerrainType CrossedWheelTerrain[4];            // 804
    bVector2  WheelSlip[4];                        // 820
    float     WheelTractionUsage[4];               // 852

    uint16_t  Angle;                               // 868
    uint16_t  SteeringAngle;                       // 870
    float     Odometer;                            // 872
    float     TractionUsage;                       // 876
    float     SkidLeft;                            // 880
    float     SkidRight;                           // 884
    int32_t   nWheelsTouchingGround;               // 888
    float     ForwardSpeed;                        // 892
    float     VelocityMagnitude;                   // 896
    Gear      CurrentGear;                         // 900
    float     Throttle;                            // 904
    float     RPM;                                 // 908
    float     RedLineSyncRPM;                      // 912
    int32_t   ClutchEngaged;                       // 916
    int32_t   DriverMode;                          // 920
    float     BoostFactor;                         // 924
    int32_t   BurnOutState;                        // 928
    float     BurnOutTime;                         // 932
    float     BurnOutTraction;                     // 936
    float     BurnOutAllow;                        // 940

    bMatrix4  RelCoordMatrix;                      // 944
    int32_t   MatrixValid;                         // 1008
    uint8_t   _tail[12];                           // 1012
} CarState;

// The record is passed between systems and snapshotted whole, so its size is
// part of its meaning rather than an implementation detail. The offsets are
// asserted individually because a compiler that packed or padded differently
// would still land on 1024 by luck of the two holes.
//
// The two leading pointers are the catch. On the 3DS, as on the PS2, they
// are four bytes each and the offsets below are the disc's. On the 64-bit
// host the cross-checker builds for they are eight, which slides everything
// after them by exactly eight bytes. That is not a portability wart to
// paper over with a #ifdef that switches the check off -- it is the one
// place a layout mistake could hide -- so the assert carries the slide as a
// term and keeps its teeth on both. A field in genuinely the wrong place
// still fails on the host; only the uniform pointer-width shift is allowed.
//
// Unlike TrackRoute (docs/formats/track-route.md), these two really are
// pointers that get dereferenced, so they cannot be narrowed to u32 slots
// the way that record's list links were.
#define CARSTATE_SLACK ((size_t)(2 * (sizeof(void *) - 4)))
#define CARSTATE_AT(f, n) \
    (offsetof(CarState, f) == (size_t)(n) + CARSTATE_SLACK)

#ifndef CARSTATE_NO_ASSERT
typedef char carstate_size_check[
    (sizeof(CarState) == 1024 + CARSTATE_SLACK
     && offsetof(CarState, pCarInfo) == 0
     && offsetof(CarState, pTopologyCoordinate) == sizeof(void *)
     && CARSTATE_AT(GeometryPosition, 16)     && CARSTATE_AT(Position, 32)
     && CARSTATE_AT(Velocity, 48)             && CARSTATE_AT(Acceleration, 64)
     && CARSTATE_AT(BodyMatrix, 80)           && CARSTATE_AT(AngularVelocity, 144)
     && CARSTATE_AT(AngularAcceleration, 160) && CARSTATE_AT(WheelMatrix, 176)
     && CARSTATE_AT(BrakeMatrix, 432)         && CARSTATE_AT(WheelAngularVelocity, 688)
     && CARSTATE_AT(WheelAngle, 704)          && CARSTATE_AT(WheelZForce, 720)
     && CARSTATE_AT(WheelRoadNoise, 736)      && CARSTATE_AT(WheelBottomOutMagnitude, 752)
     && CARSTATE_AT(WheelSuspensionHeight, 768) && CARSTATE_AT(WheelTouchingGround, 784)
     && CARSTATE_AT(WheelTerrain, 788)        && CARSTATE_AT(CrossedWheelTerrain, 804)
     && CARSTATE_AT(WheelSlip, 820)           && CARSTATE_AT(WheelTractionUsage, 852)
     && CARSTATE_AT(Angle, 868)               && CARSTATE_AT(SteeringAngle, 870)
     && CARSTATE_AT(Odometer, 872)            && CARSTATE_AT(TractionUsage, 876)
     && CARSTATE_AT(SkidLeft, 880)            && CARSTATE_AT(SkidRight, 884)
     && CARSTATE_AT(nWheelsTouchingGround, 888) && CARSTATE_AT(ForwardSpeed, 892)
     && CARSTATE_AT(VelocityMagnitude, 896)   && CARSTATE_AT(CurrentGear, 900)
     && CARSTATE_AT(Throttle, 904)            && CARSTATE_AT(RPM, 908)
     && CARSTATE_AT(RedLineSyncRPM, 912)      && CARSTATE_AT(ClutchEngaged, 916)
     && CARSTATE_AT(DriverMode, 920)          && CARSTATE_AT(BoostFactor, 924)
     && CARSTATE_AT(BurnOutState, 928)        && CARSTATE_AT(BurnOutTime, 932)
     && CARSTATE_AT(BurnOutTraction, 936)     && CARSTATE_AT(BurnOutAllow, 940)
     && CARSTATE_AT(RelCoordMatrix, 944)      && CARSTATE_AT(MatrixValid, 1008)
     ) ? 1 : -1];
#endif

// --------------------------------------------------------------- the calls

// 0x001b6170. Stores the two pointers, clears Position, GeometryPosition,
// Odometer and DriverMode, then calls ResetCar for everything else.
void carstate_init(CarState *s, TopologyCoordinate *topo,
                   CarTypeInfoPrefix *info);

// 0x001b6570. The full reset: zeroes the kinematics, identities BodyMatrix,
// puts all four wheels on the ground, and sets the drivetrain to its
// standing values -- RPM 1000, gear 1, clutch in, boost and burnout traction
// 1.0, RedLineSyncRPM -1. Ends by zeroing RelCoordMatrix and its valid bit.
void carstate_reset_car(CarState *s);

// 0x001b6718. The subset of ResetCar the sound driver wants between events:
// RPM back to 1000 and the per-wheel state cleared, but the body left where
// it is. Deliberately does NOT touch WheelRoadNoise, the wheel matrices, or
// the cached transform -- see docs/formats/car-state.md.
void carstate_reset_car_for_sound(CarState *s);

// 0x001b67e8. CrossedWheelTerrain[0..3] = 1. The only thing the object does
// per timestep, and the reason CrossedWheelTerrain means "worst terrain this
// wheel touched since the last BeginTimestep".
void carstate_begin_timestep(CarState *s);

// 0x001b6820 / 0x001b6868. The car's heading error in radians: the angle
// between where the body points and where it is actually travelling.
// GetYaw gates on ForwardSpeed < 5.0f and returns 0 below it, because atan2
// of a near-zero velocity is noise. GetYawAlways does not gate.
float carstate_get_yaw(CarState *s);
float carstate_get_yaw_always(CarState *s);

// 0x001b68d0. The cached car-to-world rotation, built on demand. Above a
// velocity of 1.0 (squared) it is built from the direction of travel,
// otherwise from Angle; either way it is orthonormalized and the valid bit
// is set. Returns a pointer into `s`, not a copy.
bMatrix4 *carstate_get_transform_matrix(CarState *s);

// 0x001b6ab0 / 0x001b6b40. World space to car space: subtract Position, then
// multiply by the transpose of the transform. The 2D overload drops z.
void carstate_world_to_car2(CarState *s, bVector2 *out, const bVector2 *in);
void carstate_world_to_car3(CarState *s, bVector3 *out, const bVector3 *in);

// 0x001b6bb0. Car space to world space without the translation -- a
// direction rather than a point.
void carstate_car_to_world_unadjusted(CarState *s, bVector2 *out,
                                      const bVector2 *in);

// 0x001b6c18. The same, plus Position. Returns by value in the original;
// here it writes through `out` so the ABI does not have to be guessed.
void carstate_car_to_world(CarState *s, bVector2 *out, const bVector2 *in);

// 0x001b6c90. Sets the flag and keeps nWheelsTouchingGround in step. Only
// a change of state moves the count.
void carstate_set_wheel_touching_ground(CarState *s, int wheel, int8_t on);

// 0x001b6ce0. Sets WheelTerrain[wheel] and raises CrossedWheelTerrain[wheel]
// to it if the new terrain compares greater.
void carstate_set_wheel_terrain(CarState *s, int wheel, TerrainType t);

// 0x001b6d10 / 0x001b6e58. Rebuilds a wheel's two matrices from WheelAngle,
// SteeringAngle and WheelSuspensionHeight; the no-argument form does all
// four. Wheels 0 and 1 steer, 2 and 3 do not.
void carstate_calculate_wheel_matrices_one(CarState *s, int wheel);
void carstate_calculate_wheel_matrices(CarState *s);

// 0x001b6ea8. GeometryPosition = Position - (CenterOfGravity * BodyMatrix):
// where the model should be drawn, given that the simulation tracks the
// centre of gravity and the artist modelled around a different origin.
void carstate_calculate_geometry_position(CarState *s);

// 0x001b6c88. Empty in the shipped build -- the debug print went out with
// NDEBUG. Kept so the call sites read the same.
void carstate_print_state(CarState *s);

// Not ported: DoSnapshot (0x001b6230), the replay serializer. It is 828
// bytes of ReplaySnapshot::MoveData calls plus the six thunks after
// CalculateGeometryPosition, and ReplaySnapshot is its own object that
// nothing else in the port needs yet. It belongs with the replay work, not
// here. See docs/formats/car-state.md.

#endif // CARSTATE_H
