// drivetarget -- DriveTarget, 0x002086f8 .. 0x0020a840 plus one method
// emitted elsewhere.
//
// DriveTarget is the short list of points the AI is currently steering
// through, together with the speed it wants at each one. It is 528 bytes
// and it is embedded at offset 0 of every CarDriver, which is why the
// layout below had to be spelled out before CarDriver could be.
//
// `DriveTarget.obj` exists (`.text 0x002086f8`, `0x24d0` long) but it is
// not all DriveTarget: seven `OBB` methods and the free function
// `bDoublesBack` (0x00208fa0) are in the same run, which is why the object
// is 9424 bytes against a DriveTarget tally of 8636. Twenty-six methods
// live in it; the copy constructor is emitted out of line at 0x001da210
// inside `CarCollisionDetect.obj`, and `_GLOBAL_$I$__11DriveTarget`
// (0x0020ab48) is the static initialiser. Twenty-eight symbols,
// twenty-six functions to port.
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
// See docs/formats/car-drive-target.md.

#ifndef DRIVETARGET_H
#define DRIVETARGET_H

#include <stddef.h>
#include <stdint.h>

#include "bvector.h"
#include "carstate.h"
#include "trackroute.h"

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
    int8_t   LastPointToScore;                 // 516  retail's; -1 is all
    uint8_t  _pad2[11];                        // 517
} DriveTarget;

// 528 = 33 * 16. The tail padding is not a guess: Points is an array of
// 16-byte vectors, so the record is 16-aligned, and 516 rounds up to 528.
// Nothing writes a vtable pointer into a DriveTarget -- the constructor
// only memsets and calls Clear -- so unlike CarDriver there is no vptr
// hiding in that tail.
//
// Retail put one byte at the front of that tail, and the record stayed 528
// bytes. The name is the port's: retail is stripped and the demo has no
// such field. Clear stores -1 there on every way out (`addiu v0,zero,-1 ;
// sb v0,516(s0)`, retail 0x0021bd98), the copy constructor copies it, and
// DrivingChoice::BuildDriveTargetAroundCar sets it to NumPoints - 1 once
// the points around the car are in (0x00243e7c), before the points that
// lead back to the line. EstimateScore reads it through
// drivetarget_get_last_corner_to_score: with it set, the corners past the
// car are not scored.
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
     && offsetof(DriveTarget, LastPointToScore) == 516
     && sizeof(DriveTarget) == 528) ? 1 : -1];
#endif

// ------------------------------------------------------------------- Car
//
// This carried a stand-in Car for one slice: ten bytes of padding,
// DriverNumber, pPlayer and the embedded CarState, guarded by its own
// `#ifndef CAR_H` because the DriveTarget slice needed those three offsets
// before `car.h` existed. `car.h` exists now -- all 2016 bytes of the real
// record, 72 offsets, and an ARM build behind them -- so the stand-in is
// gone and the real header comes in here.
//
// The three fields DriveTarget reads keep the names and the offsets they
// had, which is why nothing below this line changed when the stand-in was
// removed:
//
//     Car + 10    DriverNumber   int16_t, `lh v1,10(s2)`      Dump only
//     Car + 24    pPlayer        tested against zero          Blend only
//     Car + 64    State          the whole CarState
//
// Everything else that looks like a Car offset in the listing is inside
// that CarState: 96 is State.Position, 112 is State.Velocity, 128 is
// State.Acceleration and 960 is State.VelocityMagnitude.
//
// Including car.h here also retires the ordering rule car.h's own header
// describes. While the stand-in existed, including drivetarget.h first
// would define CAR_H with the stand-in and car.h would then vanish into
// its own guard without a word; now either order gives the real record.
#include "car.h"

// ------------------------------------------------ DrivingLocation, likewise
//
// Its own header since step 11a. The DrivingLocation overload of
// AddPointToTarget (0x00208e60) reads three of its fields, with IsClear
// (retail 0x00239c80) two instructions long:
//
//     lw v0,0(a0) ; sltiu v0,v0,1        IsClear is `pRoute == NULL`
//     lw v0,4(s0)                        pRoutePoint
//     lb t0,8(s0)                        DrivingLine's low byte
#include "drivinglocation.h"

// ------------------------------------------------------------- the constants
//
// The ten pooled floats are `DriveTarget.obj`'s `.lit4`, 0x00321fa8 and
// 0x28 long, so they are anonymous -- the values are quoted where they are
// read. The six named globals below are not, and the map gives them away:
// two of them are the camera's, which is the whole content of Dump's guard.

// 0x00323a50 / 0x00323a54. CalculateLookAheadDistance is six instructions:
// max(State.VelocityMagnitude * Seconds, Default).
extern float AIDriverSecondsToLookAhead;  // 2.0f
extern float AIDriverDefaultLookAhead;    // 20.0f

// 0x00324a60, and its square at 0x00325354, which is in .sbss because
// _GLOBAL_$I$__11DriveTarget computes it at start-up -- four instructions
// that load the first, multiply it by itself and store the second.
extern float DriveTargetMinDistanceToPoint;         // 4.0f
extern float DriveTargetMinDistanceToPointSquared;  // 16.0f after the init

// 0x003235d0 / 0x003235d4. Dump prints nothing unless the camera is
// following one particular car; the shipped values are 1 and -1, so the
// first test alone turns the whole function off.
extern int32_t CameraFollowDefaultCar;       // 1
extern int32_t CameraFollowThisCarInstead;   // -1

// 0x0020ab48. Runs the one line of static initialisation.
void drivetarget_static_init(void);

// ------------------------------------------------------ the free functions
//
// Three of them, all in the AI's half of the image rather than in
// DriveTarget.obj, and all three read nothing out of a Car that is not in
// its CarState.

// 0x001c0e30. Normalises the car's velocity first and the delta second,
// both in place, and returns `thresh < dot`.
int ai_is_point_ahead_of_car(const bVector2 *p, Car *car, float thresh);

// 0x001c0c20. max(VelocityMagnitude * 2.0f, 20.0f), written as the
// comparison `max.s` is rather than as fmaxf.
float ai_calculate_look_ahead_distance(Car *car);

// 0x001c3338. Clears the target and puts a single point one look-ahead
// distance in front of the car: along the velocity when the car is moving,
// along State.Angle when it is under 1 m/s.
void ai_straight_line_predict(Car *car, DriveTarget *t);

// ------------------------------------------------------------- the methods
//
// In address order, which is also roughly the order they depend on each
// other. `DoSnapshot` (0x00208830) is the one method not here: it needs
// `ReplaySnapshot`, the same dependency CarState, Engine, CarDriver,
// Steering, RigidBody, Suspension, Wheel and DriveTrain are all waiting
// on.

// 0x002086f8. bMemSet to zero and then Clear(NULL, 0.0f) -- which, on a
// record the memset has just zeroed, takes its NumPoints == 0 early-out
// and never touches the Car it was not given. On retail that way out
// stores -1 in LastPointToScore too, so a new target scores every corner.
DriveTarget *drivetarget_init(DriveTarget *t);

// 0x00208768. The GNU v2 deleting destructor, minus the delete: the body
// is `if (flag & 1) operator delete(this);` and there is nothing else in
// it, so the object has no destructor of its own.
void drivetarget_destroy(DriveTarget *t);

// 0x00208788. `bMemCpy(dst, src, 528)` and nothing else -- no per-field
// work, no deep copy, and the return value is the destination. CarDriver
// tail-calls it.
DriveTarget *drivetarget_assign(DriveTarget *dst, const DriveTarget *src);

// 0x001da210, out of line in CarCollisionDetect.obj (retail 0x001e7930).
// Member-wise, not a memcpy: five twenty-iteration loops and then the
// scalars, retail's LastPointToScore among them. It does *not* copy the
// three pad runs, which is a real asymmetry against drivetarget_assign
// and the reason both are here.
DriveTarget *drivetarget_copy(DriveTarget *dst, const DriveTarget *src);

// 0x002087b8. bATan of Points[i+1] - Points[i] in x and y.
//
// The clamp is one-sided and that is not a transcription slip: `i` is
// clamped up from -1 to 0 and then down to NumPoints - 2, in that order,
// and never back up again. A NumPoints of 0 or 1 therefore indexes
// Points[-2] and Points[-1] -- an out-of-bounds read in the shipped game,
// the same flavour as Table::GetValue's.
int32_t drivetarget_get_angle(DriveTarget *t, int i);

// 0x00208980. The one that decides what survives a frame. Walks the
// points until one is in front of the car, shifts that one down to zero,
// interpolates a fresh point `speed` along the remaining path and keeps
// only up to it. A speed of zero or less empties the target. Retail
// (0x0021bbb0) ends every way out at one tail that also puts -1 in
// LastPointToScore.
void drivetarget_clear(DriveTarget *t, Car *car, float speed);

// 0x00208b98. Walks the path from the car through the points accumulating
// distance and writes the point `dist` along it into `out`. Returns the
// index of the point *before* the one it landed on -- -1 when it landed on
// the first segment, NumPoints - 1 when it ran off the end and had to
// extrapolate. Returns -1 without writing `out` when there are no points.
int drivetarget_interpolate_point(DriveTarget *t, Car *car, float dist,
                                  bVector3 *out);

// 0x00208e30 / 0x00208e60 / 0x00208f58 / 0x00209048. Four overloads, one
// body: the bVector2 forms build a stack bVector3 and tail-call the
// bVector3 form, and the DrivingLocation forms unpack the location into a
// route number and a route point index and tail-call the wide form.
//
// The bVector2 forms write x, y and z of that stack vector and leave w
// alone, and the wide form copies all sixteen bytes with lqc2/sqc2, so
// Points[i].pad takes whatever was on the stack. The port writes 0.0f
// there instead -- the one deliberate divergence in this file, because an
// indeterminate read is undefined behaviour in C and the disc's value is a
// different number on every call, so no caller could have depended on it.
// drivetarget.c marks every site STACK-W.
void drivetarget_add_point3(DriveTarget *t, const bVector3 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car);
void drivetarget_add_point2(DriveTarget *t, const bVector2 *p, int8_t route,
                            int16_t rpn, int8_t dl, int check, Car *car);
void drivetarget_add_point3_dl(DriveTarget *t, const bVector3 *p,
                               DrivingLocation *loc, int check, Car *car);
void drivetarget_add_point2_dl(DriveTarget *t, const bVector2 *p,
                               DrivingLocation *loc, int check, Car *car);

// 0x002091f0. Which point the car should be steering at, cached for the
// frame in WhichPointIPickedCalculationTime against WorldTimer. Picks the
// first point that is both within 0.342 of straight ahead -- cos 70
// degrees, and the threshold drops to zero above 30 m/s -- and further
// away than DriveTargetMinDistanceToPoint. Falls back to the last point.
int8_t drivetarget_get_first_point(DriveTarget *t, CarState *cs);

// 0x00209358. Respaces the points evenly along the path they already
// describe. Needs three points; the `Car *` is taken and never read.
void drivetarget_resample(DriveTarget *t, Car *car);

// 0x002095f8. Debug. In the shipped image the print calls are gone and
// what is left transforms each point into car space and drops it on the
// floor -- 184 bytes that compute nothing anyone can observe. It is here
// because the transform is the observable part of the guard, and because
// leaving it out would make the method count wrong.
void drivetarget_dump(DriveTarget *t, Car *car, int checkCamera, int unused);

// 0x002096b0, retail 0x0021c920. The distance-weighted average speed the
// car would hold along this target, or -1.0f if any segment needs more
// lateral grip than there is. The big one: 1556 bytes on retail, three
// nested walks and three helpers.
//
// Retail changed two things. The first corner is asked about from the
// car's own velocity rather than from its position
// (drivetarget_calculate_max_speed_from_car), and the second walk stops at
// drivetarget_get_last_corner_to_score rather than at the end.
float drivetarget_estimate_score(DriveTarget *t, Car *car);

// Retail 0x0021bdc8, new in retail. Where EstimateScore's second walk
// stops: NumPoints - 2 while LastPointToScore is -1, LastPointToScore - 1
// once it is set. Both are narrowed to a signed byte, so an empty target
// answers -2.
int8_t drivetarget_get_last_corner_to_score(DriveTarget *t);

// 0x00209cf0, retail 0x0021cfe8. Given three consecutive points, an entry
// speed and a proposed exit speed, decides whether the corner between them
// can be taken -- and clamps the exit speed to the entry speed when it
// cannot even ask. `pOut` is both the proposed speed and the answer.
// Returns 1 when the corner is fine, 0 when it is not.
//
// Retail kept the two early answers here and moved the rest into
// drivetarget_calculate_max_speed_v, which it hands the two velocities.
int drivetarget_calculate_max_speed(DriveTarget *t, Car *car,
                                    const bVector2 *p0, const bVector2 *p1,
                                    const bVector2 *p2, float dist,
                                    float speed, float *pOut);

// Retail 0x0021d130, new in retail: the demo's CalculateMaxSpeed from its
// third test on. `v1` is the velocity into the corner and `v2` the one out
// of it, and whether the change between them over CalculateTime's time
// asks more sideways than GetMaxLateralAcceleration is the answer. A time
// within 0.001 of zero pins *pOut to `speed` and answers yes.
int drivetarget_calculate_max_speed_v(DriveTarget *t, Car *car,
                                      const bVector2 *v1, const bVector2 *v2,
                                      float dist, float speed, float *pOut);

// Retail 0x0021cf38, new in retail. The first corner, taken from where the
// car is going: v1 is State.Velocity as it stands, v2 points from the car
// to `p` at *pOut, the distance is `factor` times |ForwardSpeed| and the
// entry speed is VelocityMagnitude. EstimateScore passes 0.5f. No early
// answers, so a car standing still reaches the 0/0 below.
int drivetarget_calculate_max_speed_from_car(DriveTarget *t, Car *car,
                                             const bVector2 *p, float *pOut,
                                             float factor);

// 0x00209f30. `lui at,0x41f0 ; mtc1 at,$f0 ; jr ra` -- a constant 30.0f
// that never looks at the car it is handed.
float drivetarget_get_max_lateral_acceleration(DriveTarget *t, Car *car);

// 0x00209f40. `if (|b| <= 0.001f && |c| <= 0.001f) return 9999999.0f;`
// then `a / ((b + c) * 0.5f)`. Distance over mean speed. Takes a `this`
// it does not use.
float drivetarget_calculate_time(DriveTarget *t, float a, float b, float c);

// 0x00209fb0. Throws the target away and refills it by integrating the
// car's current acceleration forward in 0.1s steps until it has covered
// the look-ahead distance, filled twenty points, or turned back on
// itself. Hands off to ai_straight_line_predict when the acceleration is
// more than three quarters of the speed -- large, not small.
void drivetarget_fill_with_current_acceleration(DriveTarget *t, Car *car);

// 0x0020a1d8. The same integration, but blended into the points already
// there rather than replacing them, over the first 0.75 seconds of path.
// Once per frame, and only for a car with no player on it.
void drivetarget_blend_with_current_acceleration(DriveTarget *t, Car *car);

// 0x0020a478 / 0x0020a5a8. Slide the list. ShiftRight opens `n` slots at
// the front and blanks them -- position, RoutePointNumber and
// CalculatedSpeed, but *not* Route, DrivingLine or Points[i].pad.
// ShiftLeft drops the first `n` and optionally recomputes the length.
void drivetarget_shift_right(DriveTarget *t, int n);
void drivetarget_shift_left(DriveTarget *t, int n, int recalc);

// 0x0020a688 / 0x0020a6d0. Overwrite an existing slot. Out-of-range
// indices are dropped silently. The 2D form has the same stack-w shape,
// and the same divergence, as the AddPointToTarget pair above.
void drivetarget_set_point2(DriveTarget *t, int i, const bVector2 *p,
                            int8_t route, int16_t rpn, int8_t dl, float speed);
void drivetarget_set_point3(DriveTarget *t, int i, const bVector3 *p,
                            int8_t route, int16_t rpn, int8_t dl, float speed);

// 0x0020a748. Sum of the 3D distances between consecutive points. Length
// is reloaded from and stored back to the record on every iteration, which
// is why it is a field and not an accumulator.
void drivetarget_recalculate_length(DriveTarget *t);

// 0x0020a7a8. Resolves slot `i` back to the track route and route point it
// came from. Returns 0 and nulls both outputs when the slot has none.
//
// There is no upper bound on Route[i] in the image: the negative case is
// handled and anything from 0 to 127 indexes TheTrackRouteManager's
// hundred-entry pTrackRoutes straight. The port uses trmgr_get_route's
// bound instead and answers 0 above 99, because what follows that array
// here is not what followed it on the disc. The `p == NULL` test after the
// route point is computed can never fire and is kept because it is there.
int drivetarget_get_route_and_route_point(DriveTarget *t, int i,
                                          TrackRoute **route,
                                          TrackRoutePoint **pt);

#endif
