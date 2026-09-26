// wheel -- Wheel.obj (0x00199c30 .. 0x0019ba40).
//
// One tyre. It carries the wheel's spin state, the matrices the renderer
// and the physics read it through, and the tyre model that turns a slip
// and a load into a force on the ground. Suspension owns the spring along
// its z axis; everything in the contact patch is here.
//
// This header started life as a layout with no port behind it, written so
// Suspension could index into a Wheel before Wheel existed. That is no
// longer true -- the behaviour is in wheel.c now -- but the layout notes
// are kept because they are what the record is checked against.
//
// The offsets come from the `.mdebug` type for `Wheel` (type#1035, 400
// bytes) and every one of the 31 fields has now been confirmed against it
// field by field, not just the nine Suspension happened to touch. The
// instruction that reads each of those nine is still listed, because a
// second witness is worth having:
//
//     WI             12   Suspension::Calibrate's `lw v1,12(v0)`
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
// See docs/formats/car-wheel.md.
#ifndef WHEEL_H
#define WHEEL_H

#include <stddef.h>
#include <stdint.h>

#include "bmatrix.h"
#include "bvector.h"
#include "cartypeinfo.h"
#include "table.h"
#include "terraintype.h"

// 8 bytes. `a` is the rotation angle in radians and `w` the angular
// velocity; Wheel::GetRotation (0x0019b930) returns the first and
// Wheel::GetAngularVelocity (0x0019b928) the second.
typedef struct WheelState {
    float a; // 0
    float w; // 4
} WheelState;

// 4 bytes, `.mdebug` type#1083: a single `SkidSet *pSkidSet`. It is
// embedded in Wheel, not pointed at -- the destructor runs
// `_$_9SkidMaker(this + 384, 2)` and MaybeMakeSkids passes `this + 384`
// to MakeSkid. An earlier draft of this header had the field as a bare
// `void *`, which happens to have the same size and alignment as a struct
// wrapping one pointer and so kept every offset right, but it made the
// two calls read as though the wheel held a pointer to somebody else's
// SkidMaker. The skid trail itself belongs to task 27.
typedef struct SkidMaker {
    void *pSkidSet; // 0
} SkidMaker;

// 400 bytes, on a PhysicsComponent base like RigidBody and Suspension --
// two list links and the vtable pointer at 8, old-g++ ABI.
typedef struct Wheel {
    uint32_t  pNext;                     //   0  bNode, owned by the list
    uint32_t  pPrev;                     //   4
    uint32_t  _vtable;                   //   8
    const WheelInfo *WI;                 //  12
    const TireInfo  *TI;                 //  16
    const ControlInfo *CI;               //  20
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
    int32_t   Terrain;                   // 336  TerrainType, a 32-bit enum
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
    SkidMaker TheSkidMaker;              // 384
    uint8_t   _pad1[12];                 // 388  Wheel is 16-aligned
} Wheel;                                 // 400
//
// Terrain was a `void *` in the first draft of this header, on the reading
// that `TerrainType` was a class. It is not -- `.mdebug` type#140 is a
// 32-bit enum, GetTerrain returns it by value through `lw`, and
// GetDerivative multiplies it by 140 to index TerrainTypeInfoTable. That
// removes one of the pointers the slack count used to carry; see below.

// Five pointers, spread through the record rather than gathered at the
// front, so the widening on a 64-bit host is not one term -- see
// SUSPENSION_SLACK in suspension.h for the same problem written out in
// full. Counted in WHEEL_SLACK the multiplier is 1 at WI, then 5 for the
// whole span from State to CatchupFrictionMultiplier, and 5 again at
// TheSkidMaker, whose single pointer member takes a four-byte alignment
// pad in front of it and then widens by four, which is where the last two
// terms come from.
//
// The first draft of this header guarded the assert with
// `#if __SIZEOF_POINTER__ == 4`, on the grounds that nothing in the port
// depended on Wheel's host layout yet. That was a mistake twice over: the
// guard meant the claim was never compiled by either toolchain the project
// actually uses -- the host build skipped it and the ARM build had not been
// run -- and when the ARM build finally ran it failed. `_pad2` is what it
// failed on.
#define WHEEL_SLACK ((size_t)(sizeof(void *) - 4))

// 400 bytes on the handheld; 428 of fields on a 64-bit host, rounded up to
// the pointer's alignment.
#define WHEEL_SIZEOF                                                        \
    ((size_t)((400 + 7 * WHEEL_SLACK + sizeof(void *) - 1)                  \
              / sizeof(void *) * sizeof(void *)))

#ifndef WHEEL_NO_ASSERT
typedef char wheel_layout_check[
    (offsetof(Wheel, WI) == 12 + 1 * WHEEL_SLACK
     && offsetof(Wheel, State) == 28 + 5 * WHEEL_SLACK
     && offsetof(Wheel, MomentOfInertia) == 36 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Matrix) == 48 + 5 * WHEEL_SLACK
     && offsetof(Wheel, WorldMatrix) == 112 + 5 * WHEEL_SLACK
     && offsetof(Wheel, CarMatrix) == 176 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Velocity) == 240 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Slip) == 256 + 5 * WHEEL_SLACK
     && offsetof(Wheel, AppliedTorque) == 264 + 5 * WHEEL_SLACK
     && offsetof(Wheel, BrakeLocked) == 268 + 5 * WHEEL_SLACK
     && offsetof(Wheel, LastSign) == 272 + 5 * WHEEL_SLACK
     && offsetof(Wheel, GroundForce) == 276 + 5 * WHEEL_SLACK
     && offsetof(Wheel, WorldGroundForce) == 288 + 5 * WHEEL_SLACK
     && offsetof(Wheel, ContactPoint) == 304 + 5 * WHEEL_SLACK
     && offsetof(Wheel, ContactNormal) == 320 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Terrain) == 336 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Slipping) == 340 + 5 * WHEEL_SLACK
     && offsetof(Wheel, TouchingGround) == 341 + 5 * WHEEL_SLACK
     && offsetof(Wheel, NumTimesSkidding) == 342 + 5 * WHEEL_SLACK
     && offsetof(Wheel, ZForce) == 344 + 5 * WHEEL_SLACK
     && offsetof(Wheel, RoadNoise) == 348 + 5 * WHEEL_SLACK
     && offsetof(Wheel, CurrentSlip) == 352 + 5 * WHEEL_SLACK
     && offsetof(Wheel, OldSlip) == 356 + 5 * WHEEL_SLACK
     && offsetof(Wheel, TractionUsage) == 360 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Damage) == 364 + 5 * WHEEL_SLACK
     && offsetof(Wheel, Brake) == 368 + 5 * WHEEL_SLACK
     && offsetof(Wheel, EBrake) == 372 + 5 * WHEEL_SLACK
     && offsetof(Wheel, TractionBoost) == 376 + 5 * WHEEL_SLACK
     && offsetof(Wheel, CatchupFrictionMultiplier) == 380 + 5 * WHEEL_SLACK
     && offsetof(Wheel, TheSkidMaker) == 384 + 6 * WHEEL_SLACK
     && sizeof(Wheel) == WHEEL_SIZEOF
     && sizeof(WheelState) == 8
     && sizeof(SkidMaker) == sizeof(void *)
     && sizeof(WheelInfo) == 32
     && sizeof(TireInfo) == 32) ? 1 : -1];
#endif

// 0x00298f20, `_vt$5Wheel`. The destructor puts PHYSICSCOMPONENT_VTABLE
// back, the same handover RigidBody and Suspension do.
#define WHEEL_VTABLE 0x00298f20u

// Wheel::GetState/SetState move both floats as one 64-bit `ldl`/`ldr`
// pair, so the state array is two entries and GetSize returns 2.
#define WHEEL_STATE_FLOATS 2

// ------------------------------------------------- the image's constants
//
// Every one of these is a word in `.lit4` between 0x00321788 and
// 0x00321800, read out of the ELF rather than spelled as an expression,
// because three of them are not the value their name suggests.
//
// **The object has its own pi, again.** CarState was found holding
// 0x40490fd0/0x40c90fd0 where bMath -- and `float(pi)` -- hold
// 0x40490fdb/0x40c90fdb. Wheel holds exactly the same pair, in all four
// places it folds an angle. The BAM-to-radian scale two words away is
// 0x38c90fdb, which *is* true pi over 32768, so the two spellings sit
// side by side in one function: GuessGroundForce scales an atan result by
// the accurate one and then folds it against the inaccurate one.
#define WHEEL_IMAGE_PI       3.14159012f  // 0x40490fd0, not 0x40490fdb
#define WHEEL_IMAGE_TWO_PI   6.28318024f  // 0x40c90fd0, not 0x40c90fdb
#define WHEEL_IMAGE_HALF_PI  1.57079649f  // 0x3fc90fdc, as Suspension's
#define WHEEL_BAM_TO_RAD     9.58738019e-05f // 0x38c90fdb = true pi/32768

// ComputeAuxiliaries folds State.a into (-628.317993, 628.317993] and
// zeroes it outright if one fold is not enough. 628.317993 is 0x441d145a;
// 200 * WHEEL_IMAGE_PI is 0x441d1458, so this is not that either.
#define WHEEL_ROT_FOLD       628.317993f  // 0x441d145a
#define WHEEL_ROT_GIVE_UP    6283.17969f  // 0x45c45970

// The dead band ComputeAuxiliaries uses to decide LastSign.
#define WHEEL_SPIN_EPSILON   9.99999975e-06f // 0x3727c5ac

// ExchangeZForces floors its normal-alignment term here, CheckTerrain and
// GetDerivative both guard a divide with 0.001, and GuessGroundForce
// damps a reversing torque by 0.15.
#define WHEEL_ZFORCE_FLOOR   0.300000012f   // 0x3e99999a
#define WHEEL_EPSILON        0.00100000005f // 0x3a83126f
#define WHEEL_REVERSE_DAMP   0.150000006f   // 0x3e19999a

// GetPilotFactor ramps over ForwardSpeed in (13.4108181, 22.354...) m/s.
// The second constant is the reciprocal of the span, not the top of it.
#define WHEEL_PILOT_SPEED    13.4108181f    // 0x415692b6
#define WHEEL_PILOT_INV_SPAN 0.111850001f   // 0x3de5119d

// GuessGroundForce compares CarState::ForwardSpeed against 1.0 after
// scaling it by this, which is metres per second to miles per hour.
#define WHEEL_MPS_TO_MPH     2.23699999f    // 0x400f2b02
#define WHEEL_RAD_TO_DEG     57.2957764f    // 0x42652ee0

// The surface CheckTerrain reports when the ground faces away from the
// wheel. Not a height -- a sentinel that Suspension's bump stops reject.
#define WHEEL_NO_SURFACE     (-100.0f)      // 0xc2c80000

// ---------------------------------------------------- the tyre model
//
// Seven load-sensitivity curves, one per two degrees of slip angle, and
// the older single cornering curve behind gUseNewTireForces. Both sets are
// built by a static constructor at 0x0019b558; the Table objects are zero
// in the image and the entry arrays are not, so the ranges below come from
// that constructor's arguments and the entries from `.data`.
#define WHEEL_NUM_LOAD_TABLES 7
#define WHEEL_LOAD_TABLE_ENTRIES 6
#define WHEEL_CORNERING_ENTRIES 7

extern const float gZeroDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gTwoDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gFourDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gSixDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gEightDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gTenDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gTwelveDegreeTable[WHEEL_LOAD_TABLE_ENTRIES];
extern const float gCorneringForceTable[WHEEL_CORNERING_ENTRIES];

extern Table  gLoadSensitivity[WHEEL_NUM_LOAD_TABLES];
extern Table *gLoadSensitivityTable[WHEEL_NUM_LOAD_TABLES];
extern Table  gCorneringForce;

// 0.223402172f, written into MAX_SLIP_ANGLE by the same constructor and
// used as the top of the old cornering curve's range. Zero in the image.
extern float gMaxSlipAngleGlobal;

// 0x0019b558. Fills the eight Tables and MAX_SLIP_ANGLE. The port needs it
// called once before any tyre force is asked for; the original had the
// linker do it.
void wheel_static_init(void);

// ------------------------------------------------------ tuning globals
//
// `.sdata` at 0x00323d18..0x00323d68. Four more in the same block --
// gLoadFactor, gWheelForceFrame, gTireForceEllipseRatio and
// gUglyTimestepHack -- are read by Wheel as well, but Suspension got to
// them first and defines them; wheel.c includes suspension.h for those
// rather than declaring a second copy.
extern float   gWheelMomentOfInertia;            // 0x00323d18  0.01
extern float   gRollingFriction;                 // 0x00323d2c  0.002
extern float   gMaxStaticSlip;                   // 0x00323d34  0.5
extern float   gBrakingTorque;                   // 0x00323d38  4.0
extern float   gEBrakingTorque;                  // 0x00323d3c  10.0
extern float   gStaticToDynamicBrakeForceRatio;  // 0x00323d40  1.2
extern float   gBrakeLockAngularVelocityFactor;  // 0x00323d44  0.1
extern float   gZForceScale;                     // 0x00323d48  1.0
extern float   gPilotFactor;                     // 0x00323d4c  0.85
extern int32_t gWheelDebugInfo;                  // 0x00323d50  0
extern float   gCorneringScale;                  // 0x00323d54  1.0
extern int32_t gUseNewTireForces;                // 0x00323d58  1
extern float   gNewCorneringScale;               // 0x00323d5c  2.5

// ------------------------------------------- TerrainTypeInfo, borrowed
//
// The record is terraintype.h's -- TerrainType.obj's -- and Wheel reads four
// of its floats and nothing else. It indexes the table by stride, so the
// whole record has to be right, and terraintype.h's assert holds it.

// 0x00310a90. NULL by default and pointed at TerrainTypeInfoTable by
// main.c at boot. A NULL table makes every multiplier read as 1.0 rather
// than crashing, which is what the harnesses lean on.
extern const TerrainTypeInfo *gTerrainTypeInfoTable;

// ---------------------------------------------------------- the seams
//
// Wheel reaches two systems through pointers: the terrain query behind
// CheckTerrain, which is Track.obj's (track.c; main.c points the seams at
// it), and the skid trail behind MaybeMakeSkids, which is not ported. They
// are function pointers for the same reason gTrackPathDistanceFn is --
// NULL by default, pointed at stand-ins by tools/wheel_check.py -- so that
// Wheel is checked on its own, whatever is behind them.

// 0x0014f418, TopologyCoordinate::GetElevation. Returns the ground
// height under `pos` and writes the surface's normal. The terrain
// out-parameter is written whenever it is not NULL, and both of Wheel's
// ground queries pass one: CheckTerrain forwards its own -- the wheel's
// Terrain, through FindDrivingSurface -- so the terrain it then feeds to
// GetRoadNoise is the one just reported, while SetState(CarState *, ...)
// runs `addiu a2,sp,192` and puts what comes back into both the wheel and
// the CarState.
//
// The mangled name ends `P8bVector3Pb`, so the real function takes a fifth
// argument, a `bool *`. All four call sites in this object -- CheckTerrain
// at 0x0019a308, SetState at 0x00199ff4 and the two in FindDrivingSurface
// at 0x0019b460 and 0x0019b480 -- reach it with `move t0,zero`, so nothing
// Wheel does can observe it and the seam leaves it out rather than
// carrying a parameter that is NULL on every path.
//
// A NULL seam reports height 0 and a straight-up normal, which makes
// CheckTerrain's own arithmetic run.
typedef float (*TopologyGetElevationFn)(void *topology, const bVector3 *pos,
                                        int32_t *terrainOut,
                                        bVector3 *normalOut);

// 0x001504f0, GetRoadNoise(bVector2, TerrainType). NULL reports 0.
typedef float (*TerrainRoadNoiseFn)(const bVector2 *xy, int32_t terrain);

extern TopologyGetElevationFn gTopologyGetElevationFn;
extern TerrainRoadNoiseFn     gTerrainRoadNoiseFn;

// CheckTerrain reads the TopologyCoordinate out of `CS->[4]`, a CarState
// field the CarState slice left as an undecoded word. Rather than reach
// into it here, wheel.c asks for it through this -- NULL is fine, the seam
// above ignores it.
typedef void *(*WheelTopologyOfCarStateFn)(void *carState);
extern WheelTopologyOfCarStateFn gWheelTopologyOfCarStateFn;

// 0x0019b2d0, MaybeMakeSkids(float). Unlike MaybeMakeSmoke it still has a
// body -- MakeSkid and MakeNoSkid on the SkidMaker at +384 -- and the skid
// trail is task 27's, so wheel_maybe_make_skids hands the wheel and the
// time step to this. NULL makes no skids.
typedef void (*WheelMaybeMakeSkidsFn)(Wheel *w, float dt);
extern WheelMaybeMakeSkidsFn gWheelMaybeMakeSkidsFn;

// --------------------------------------------- what the replay wants
//
// DoSnapshot is the replay serialiser and ReplaySnapshot is not ported --
// it belongs with the replay system, not with the car -- so its four calls
// are seams of the same kind as the terrain ones. MoveData runs in
// whichever direction the snapshot is going, so one body both records and
// plays back, which is exactly why the field list is worth pinning down
// before the snapshot exists.

// 0x001374a8 / 0x001374a0. The section is named "Wheel", the string at
// 0x00323d10.
typedef void (*ReplayBeginSectionFn)(void *snap, const char *name);
typedef void (*ReplayEndSectionFn)(void *snap);

// 0x00134b30, MoveData(float *) -- one float.
typedef void (*ReplayMoveFloatFn)(void *snap, float *p);

// 0x00134b40, MoveData(int *, int) -- a run of words.
typedef void (*ReplayMoveIntsFn)(void *snap, int32_t *p, int32_t n);

// `lbu v0,56(s1)`, `lbu v1,57(s1)`, `or`, `beq zero`: two bytes of the
// snapshot, OR'd together. Which two is the replay system's to name --
// DoSnapshot only asks whether either is set, so the seam reports that and
// nothing else. NULL reads as "no reset", which leaves the record alone.
typedef int32_t (*ReplayShouldResetFn)(const void *snap);

extern ReplayBeginSectionFn gReplayBeginSectionFn;
extern ReplayEndSectionFn   gReplayEndSectionFn;
extern ReplayMoveFloatFn    gReplayMoveFloatFn;
extern ReplayMoveIntsFn     gReplayMoveIntsFn;
extern ReplayShouldResetFn  gReplayShouldResetFn;

// ------------------------------------------ what Suspension asks Wheel
//
// Suspension calls these two through function pointers that suspension.c
// defines and that were NULL until this slice landed. wheel_install_seams
// points them at the real methods.

// 0x0019a2a0. Forwards to CheckTerrain with the wheel's own ContactNormal
// and Terrain as the out parameters.
typedef float (*WheelFindDrivingSurfaceFn)(Wheel *w, const bVector4 *pos,
                                           const bMatrix4 *r);

// 0x0019a1c8. Takes the touching-ground flag and the z force and updates
// the wheel. **It returns 0.0f, always** -- see the note in wheel.c.
typedef float (*WheelExchangeZForcesFn)(Wheel *w, int32_t touching, float z);

extern WheelFindDrivingSurfaceFn gWheelFindDrivingSurfaceFn;
extern WheelExchangeZForcesFn    gWheelExchangeZForcesFn;

// Points the two globals above at wheel_find_driving_surface and
// wheel_exchange_z_forces. Idempotent.
void wheel_install_seams(void);

// --------------------------------------------------------- the methods

// 0x00199c40. Note the fifth argument arrives in t0, not on the stack.
Wheel *wheel_init(Wheel *w, const WheelInfo *wi, const TireInfo *ti,
                  const ControlInfo *ci, void *cs);
// 0x0019b9e0, minus the SkidMaker and PhysicsComponent chaining.
void   wheel_fini(Wheel *w);

// 0x0019a068. Ignores its load argument -- the moment of inertia is the
// global, not anything derived from the car.
void   wheel_calibrate(Wheel *w);

// 0x00199e78 / 0x00199e88 / 0x0019b9a0 / 0x0019b9b8 / 0x0019b9d0 / 0x0019b9d8
void         wheel_set_state2(Wheel *w, float a, float wv);
void         wheel_set_state_w(Wheel *w, float wv);
void         wheel_set_state_array(Wheel *w, const float *in);
void         wheel_get_state_array(const Wheel *w, float *out);
WheelState  *wheel_get_state(Wheel *w);
int32_t      wheel_get_size(const Wheel *w);

// 0x0019a3d0. Returns NULL, not `out` -- Suspension's returns `out`.
float *wheel_get_derivative(Wheel *w, float *out);

// 0x0019a078. Rebuilds Matrix from State.a, folds the angle and resolves
// LastSign; also zeroes GroundForce, AppliedTorque and CurrentSlip.
void wheel_compute_auxiliaries(Wheel *w);

// 0x0019a1c8 and 0x0019a2a0, the two Suspension seams.
float wheel_exchange_z_forces(Wheel *w, int32_t touching, float z);
float wheel_find_driving_surface(Wheel *w, const bVector4 *pos,
                                 const bMatrix4 *r);
// 0x0019a2c8.
float wheel_check_terrain(Wheel *w, bVector3 *normalOut, int32_t *terrainOut,
                          const bVector3 *pos, const bMatrix4 *r);

// 0x0019a480 / 0x0019a520.
void  wheel_check_for_brake_lock(Wheel *w, float v);
float wheel_get_pilot_factor(Wheel *w);

// 0x0019a638 / 0x0019aa20 / 0x0019ab80 / 0x0019ac60. The tyre model.
void  wheel_guess_ground_force(Wheel *w, const bVector2 *unused);
float wheel_get_lateral_force(Wheel *w, float zforce, float slipAngle);
void  wheel_modify_ground_force(Wheel *w, const bVector2 *v);
void  wheel_finalize_ground_force(Wheel *w, int32_t slider);

// 0x0019b120 / 0x0019b1a8.
bVector3 *wheel_get_horizontal_ground_force_world(Wheel *w, bVector3 *out);
bVector3 *wheel_get_horizontal_ground_force_car(Wheel *w, bVector3 *out);

// 0x0019b2c8 and 0x0019b548, both empty in the shipped image.
void wheel_maybe_make_smoke(Wheel *w, float v);
void wheel_maybe_make_tire_spew(Wheel *w, float v);

// 0x0019b2d0. Through gWheelMaybeMakeSkidsFn, above. PhysicsCar::Move
// calls it for each wheel once a frame when the car's visual effects are on.
void wheel_maybe_make_skids(Wheel *w, float dt);

// 0x0019b230. A free function in this object file, not bVector.obj's:
// out = M-transpose * v, the rotate-into-local-frame of a 3x3.
void bRotateVector(bVector3 *o, const bMatrix4 *m, const bVector3 *v);

// 0x00199c30. Empty in the shipped image -- a debug hook whose body was
// compiled out. FinalizeGroundForce calls it once per wheel per frame and
// the arguments are still evaluated.
void SetSliderValue(int32_t which, float lo, float hi, float value);

// -------------------------------------------------------- the accessors
//
// All 40 of them, in image order from 0x0019b6c8. They are one line each
// and none of them is interesting except where noted.
float     wheel_get_moment_of_inertia(const Wheel *w);
float     wheel_get_damage(const Wheel *w);
void      wheel_set_damage(Wheel *w, float v);
int32_t   wheel_is_steering_wheel(const Wheel *w);
int32_t   wheel_is_drive_wheel(const Wheel *w);
float     wheel_get_old_slip(const Wheel *w);
float     wheel_get_current_slip(const Wheel *w);
void      wheel_set_slipping(Wheel *w, uint8_t v);
int8_t    wheel_is_slipping(const Wheel *w);
void      wheel_apply_torque(Wheel *w, float t);
float     wheel_get_z_force(const Wheel *w);
// Always 1.0f. The wheel has no mass field; this is the image's answer.
float     wheel_get_mass(const Wheel *w);
float     wheel_get_radius(const Wheel *w);
bVector4 *wheel_get_contact_normal(Wheel *w);
bVector4 *wheel_get_contact_point(Wheel *w);
bVector4 *wheel_get_ground_force_vector(Wheel *w);
// Returns the WheelInfo itself -- its first three floats are the position.
const bVector3 *wheel_get_rest_position_in_geometry_frame(const Wheel *w);
void      wheel_set_contact_normal(Wheel *w, const bVector4 *v);
void      wheel_set_contact_point(Wheel *w, const bVector4 *v);
void      wheel_set_velocity(Wheel *w, const bVector4 *v);
void      wheel_set_car_matrix(Wheel *w, const bMatrix4 *m);
void      wheel_set_world_matrix(Wheel *w, const bMatrix4 *m);
void      wheel_set_touching_ground(Wheel *w, uint8_t v);
int8_t    wheel_is_touching_ground(const Wheel *w);
void      wheel_set_terrain(Wheel *w, int32_t t);
int32_t   wheel_get_terrain(const Wheel *w);
// Zero unless the wheel is touching the ground.
float     wheel_get_road_noise(const Wheel *w);
// Writes Slip[0..1] and then CurrentSlip from Slip[0] again.
void      wheel_set_slip(Wheel *w, const bVector2 *v);
float    *wheel_get_slip(Wheel *w);
float     wheel_get_traction_usage(const Wheel *w);
int32_t   wheel_modifiable(const Wheel *w);
bMatrix4 *wheel_get_matrix(Wheel *w);
bMatrix4 *wheel_get_car_matrix(Wheel *w);
float     wheel_get_applied_torque(const Wheel *w);
float     wheel_get_torque_response(const Wheel *w);
float     wheel_get_angular_acceleration(const Wheel *w);
float     wheel_get_angular_velocity(const Wheel *w);
float     wheel_get_rotation(const Wheel *w);
void      wheel_set_catchup_friction_multiplier(Wheel *w, float v);
void      wheel_adjust_traction_boost(Wheel *w, float v);
void      wheel_set_traction_boost(Wheel *w, float v);
float     wheel_get_ebrake(const Wheel *w);
void      wheel_set_ebrake(Wheel *w, float v);
void      wheel_set_brake(Wheel *w, float v);

// 0x00199c90. The replay serialiser: three MoveData calls inside a named
// section, and then, if the snapshot says to, twenty-three clears that
// step around MomentOfInertia, LastSign, RoadNoise, Damage and the pad
// behind GroundForce. See docs/formats/car-wheel.md.
void wheel_do_snapshot(Wheel *w, void *snap);

// 0x00199e90. Places the wheel from a CarState -- the replay and network
// path. `cs` is a CarState * and `cti` a CarTypeInfo * that the image
// never reads; both are void * here so this header does not have to drag
// carstate.h in behind it. This is the only method in the object that
// asks the topology for a terrain type; CheckTerrain does not.
void wheel_set_state_from_car_state(Wheel *w, void *cs, void *cti,
                                    float angle, float angularVelocity,
                                    uint16_t steeringAngle,
                                    float suspensionHeight);

#endif // WHEEL_H
